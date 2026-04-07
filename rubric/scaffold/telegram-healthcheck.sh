#!/bin/bash
# Telegram Channel Healthcheck v2 — Hardened
# Fixes: zombie detection, crash loops, cron self-healing, startup verification
#
# Called every 15 minutes by cron. Self-installs cron if missing.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="${AGENT_PROJECT_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
TMUX_SESSION="telegram-channel"
LOG_DIR="/tmp/storyengine-agents"
LOG_FILE="$LOG_DIR/telegram-channel.log"
HEALTHCHECK_LOG="$LOG_DIR/telegram-healthcheck.log"
CLAUDE_BIN="${CLAUDE_BIN:-claude}"
MODEL="${TELEGRAM_MODEL:-haiku}"

# Session age limit — 6 hours (was 2h, too aggressive = 12 restarts/day)
# Claude Code channels mode handles context internally; only recycle on actual degradation
MAX_AGE_SECONDS=21600

# Crash tracking — prevent restart loops
CRASH_FILE="$LOG_DIR/telegram-crash-count"
MAX_CRASHES_BEFORE_BACKOFF=3
BACKOFF_FILE="$LOG_DIR/telegram-backoff-until"

# State files
AGE_FILE="$LOG_DIR/telegram-channel-started"
PID_FILE="$LOG_DIR/telegram-channel.pid"

mkdir -p "$LOG_DIR"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# Source Telegram helper for notify_telegram()
source "$PROJECT_ROOT/storyengine/agents/notify-telegram.sh" 2>/dev/null || true

# ─── Self-healing cron ──────────────────────────────────────────────────────
# If our cron entry is missing (reboot, crontab -r, etc.), re-add it.
# This is the #1 reason the bot stays dead: cron disappears and nobody restarts.
ensure_cron_exists() {
  if ! crontab -l 2>/dev/null | grep -q "telegram-healthcheck.sh"; then
    log "CRON MISSING — self-installing healthcheck cron"
    (crontab -l 2>/dev/null; echo "*/15 * * * * bash $SCRIPT_DIR/telegram-healthcheck.sh >> $HEALTHCHECK_LOG 2>&1 # telegram-healthcheck") | crontab -
    log "Cron re-installed"
  fi
}
ensure_cron_exists

# ─── Crash backoff ──────────────────────────────────────────────────────────
# If we've crashed N times in a row, wait before retrying (prevents tight restart loops
# that burn CPU/logs and never succeed because the underlying issue isn't transient)
check_backoff() {
  if [ -f "$BACKOFF_FILE" ]; then
    local backoff_until now
    backoff_until=$(cat "$BACKOFF_FILE" 2>/dev/null || echo 0)
    now=$(date +%s)
    if [ "$now" -lt "$backoff_until" ]; then
      local remaining=$(( backoff_until - now ))
      log "BACKING OFF — ${remaining}s remaining (too many consecutive crashes). Will retry after backoff."
      exit 0
    else
      # Backoff expired, clear it
      rm -f "$BACKOFF_FILE"
    fi
  fi
}

increment_crash_count() {
  local count=0
  [ -f "$CRASH_FILE" ] && count=$(cat "$CRASH_FILE" 2>/dev/null || echo 0)
  count=$((count + 1))
  echo "$count" > "$CRASH_FILE"

  if [ "$count" -ge "$MAX_CRASHES_BEFORE_BACKOFF" ]; then
    # Exponential backoff: 5min, 15min, 30min, 60min (capped)
    local multiplier=$((count - MAX_CRASHES_BEFORE_BACKOFF + 1))
    [ "$multiplier" -gt 4 ] && multiplier=4
    local backoff_seconds=$((300 * multiplier * multiplier))
    local backoff_until=$(( $(date +%s) + backoff_seconds ))
    echo "$backoff_until" > "$BACKOFF_FILE"
    log "CRASH #$count — backing off for ${backoff_seconds}s ($(( backoff_seconds / 60 ))min)"
    notify_telegram "⚠️ Telegram bot crashed $count times. Backing off ${backoff_seconds}s. Check logs: tail -50 $HEALTHCHECK_LOG" 2>/dev/null || true
  fi
}

reset_crash_count() {
  rm -f "$CRASH_FILE" "$BACKOFF_FILE"
}

# ─── Liveness checks ───────────────────────────────────────────────────────

session_exists() {
  tmux has-session -t "$TMUX_SESSION" 2>/dev/null
}

# Robust process check — multiple strategies to find Claude inside tmux
claude_process_alive() {
  if ! session_exists; then
    return 1
  fi

  local pane_pid
  pane_pid=$(tmux list-panes -t "$TMUX_SESSION" -F '#{pane_pid}' 2>/dev/null | head -1)
  [ -z "$pane_pid" ] && return 1

  # Strategy 1: pstree (most reliable — shows full process tree)
  if command -v pstree &>/dev/null; then
    pstree -p "$pane_pid" 2>/dev/null | grep -qE 'claude|node' && return 0
  fi

  # Strategy 2: recursive child search via /proc
  # Walk the process tree manually — works even when pstree isn't installed
  local children
  children=$(pgrep -P "$pane_pid" 2>/dev/null)
  for child in $children; do
    # Check child itself
    ps -p "$child" -o args= 2>/dev/null | grep -qE 'claude|node' && return 0
    # Check grandchildren (script -> bash -> claude)
    local grandchildren
    grandchildren=$(pgrep -P "$child" 2>/dev/null)
    for gc in $grandchildren; do
      ps -p "$gc" -o args= 2>/dev/null | grep -qE 'claude|node' && return 0
      # Check great-grandchildren (script -> bash -> node -> claude)
      local ggc
      ggc=$(pgrep -P "$gc" 2>/dev/null)
      for g in $ggc; do
        ps -p "$g" -o args= 2>/dev/null | grep -qE 'claude|node' && return 0
      done
    done
  done

  return 1
}

# Check if the session is actually processing messages (not hung)
session_is_responsive() {
  # If log has been written to in the last 60 minutes, session is responsive
  # (Telegram plugin polls every few seconds, so a truly alive session writes frequently)
  if [ -f "$LOG_FILE" ]; then
    local last_mod now age
    last_mod=$(stat -c %Y "$LOG_FILE" 2>/dev/null || echo 0)
    now=$(date +%s)
    age=$((now - last_mod))
    [ "$age" -lt 3600 ] && return 0
  fi
  return 1
}

# Combined liveness: tmux exists AND (process alive OR session responsive)
session_is_alive() {
  if ! session_exists; then
    log "tmux session '$TMUX_SESSION' does not exist"
    return 1
  fi

  if claude_process_alive; then
    return 0
  fi

  if session_is_responsive; then
    # Log is fresh — Claude might be between subprocess calls. Benefit of doubt.
    log "Claude process not found but log is fresh — assuming alive"
    return 0
  fi

  log "tmux exists but Claude is dead and session is unresponsive"
  return 1
}

# ─── Start/restart ──────────────────────────────────────────────────────────

kill_session() {
  # Kill tmux session
  tmux kill-session -t "$TMUX_SESSION" 2>/dev/null || true

  # Kill orphaned telegram plugin processes from OUR session only
  # (Don't use broad pkill that kills unrelated processes)
  if [ -f "$PID_FILE" ]; then
    local old_pid
    old_pid=$(cat "$PID_FILE" 2>/dev/null)
    if [ -n "$old_pid" ]; then
      # Kill the process tree rooted at our session's shell
      pkill -TERM -P "$old_pid" 2>/dev/null || true
      kill -TERM "$old_pid" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
  fi

  # Wait for processes to die gracefully before killing telegram pollers
  sleep 2

  # Only kill telegram pollers if no other tmux telegram session exists
  if ! tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
    pkill -f 'bun.*telegram.*start' 2>/dev/null || true
  fi

  sleep 1
}

start_session() {
  kill_session

  # Verify Telegram plugin is configured before starting
  local tg_env="$HOME/.claude/channels/telegram/.env"
  local tg_approved="$HOME/.claude/channels/telegram/approved"
  if [ ! -f "$tg_env" ]; then
    log "ERROR: Telegram not configured — missing $tg_env"
    log "Run: claude --channels plugin:telegram@claude-plugins-official"
    log "Then: /telegram:configure YOUR_BOT_TOKEN"
    notify_telegram "❌ Telegram bot config missing. Run setup on VPS." 2>/dev/null || true
    increment_crash_count
    return 1
  fi
  if [ ! -d "$tg_approved" ] || [ -z "$(ls -A "$tg_approved" 2>/dev/null)" ]; then
    log "WARNING: No approved Telegram chats — bot will start but can't receive messages"
    log "Pair your chat: /telegram:access pair YOUR_CODE"
  fi

  # Start Claude with Telegram channels in tmux
  # Uses 'script' to preserve PTY (Claude requires TTY in interactive mode)
  tmux new-session -d -s "$TMUX_SESSION" \
    "cd $PROJECT_ROOT && script -q -f $LOG_FILE -c '$CLAUDE_BIN --channels plugin:telegram@claude-plugins-official --model $MODEL --dangerously-skip-permissions'"

  # Record start time and session PID
  date +%s > "$AGE_FILE"
  local pane_pid
  pane_pid=$(tmux list-panes -t "$TMUX_SESSION" -F '#{pane_pid}' 2>/dev/null | head -1)
  [ -n "$pane_pid" ] && echo "$pane_pid" > "$PID_FILE"

  # ─── Startup verification ─────────────────────────────────────────────────
  # Wait for Claude to actually start (not just tmux session to exist)
  # Previous version declared success after 5s without checking if Claude connected
  local attempts=0
  local max_attempts=6  # 30 seconds total (6 x 5s)
  log "Waiting for Claude to start..."

  while [ $attempts -lt $max_attempts ]; do
    sleep 5
    attempts=$((attempts + 1))

    if ! session_exists; then
      log "STARTUP FAILED — tmux session died during startup (attempt $attempts)"
      increment_crash_count
      return 1
    fi

    if claude_process_alive; then
      log "Claude process detected after ${attempts}x5s = $((attempts * 5))s"
      reset_crash_count
      return 0
    fi
  done

  # Timed out waiting for Claude — session exists but Claude never started
  log "STARTUP TIMEOUT — tmux alive but Claude process never appeared after $((max_attempts * 5))s"
  # Capture what's in the tmux pane for debugging
  tmux capture-pane -t "$TMUX_SESSION" -p 2>/dev/null | tail -20 >> "$HEALTHCHECK_LOG"
  increment_crash_count
  # Don't kill the session — maybe it's still starting up slowly
  return 1
}

# ─── Main logic ─────────────────────────────────────────────────────────────

check_backoff

# Check 1: Is session alive?
if ! session_is_alive; then
  if session_exists; then
    RESTART_REASON="zombie (tmux alive, Claude dead)"
  else
    RESTART_REASON="session not running"
  fi

  log "Telegram bot is DOWN — reason: $RESTART_REASON"

  if start_session; then
    log "Telegram bot restarted successfully (model=$MODEL, reason=$RESTART_REASON)"
    notify_telegram "🔄 Bot restarted: $RESTART_REASON ($(date +%H:%M))" 2>/dev/null || true
  else
    log "FAILED to restart — will retry next healthcheck (with backoff if repeated)"
  fi
  exit 0
fi

# Check 2: Is session too old? (context overflow prevention)
if [ -f "$AGE_FILE" ]; then
  STARTED_AT=$(cat "$AGE_FILE" 2>/dev/null || echo 0)
  NOW=$(date +%s)
  AGE=$((NOW - STARTED_AT))

  if [ "$AGE" -gt "$MAX_AGE_SECONDS" ]; then
    log "Session is ${AGE}s old (max ${MAX_AGE_SECONDS}s) — recycling for context freshness"

    if start_session; then
      log "Recycled successfully (model=$MODEL, was ${AGE}s old)"
    else
      log "FAILED to recycle — old session may still be running"
      notify_telegram "⚠️ Failed to recycle Telegram bot after ${AGE}s" 2>/dev/null || true
    fi
    exit 0
  fi
fi

# Check 3: Keepalive — but only if session appears idle
# Don't send keystrokes if the session was recently active (avoid interfering with conversations)
if [ -f "$LOG_FILE" ]; then
  LAST_MOD=$(stat -c %Y "$LOG_FILE" 2>/dev/null || echo 0)
  NOW=$(date +%s)
  IDLE_TIME=$((NOW - LAST_MOD))

  if [ "$IDLE_TIME" -gt 600 ]; then
    # Only send keepalive if idle for 10+ minutes
    tmux send-keys -t "$TMUX_SESSION" "" Enter 2>/dev/null || true
    log "Session idle for ${IDLE_TIME}s — keepalive sent"
  else
    log "Session active (last activity ${IDLE_TIME}s ago) — skipping keepalive"
  fi
else
  # No log file yet — send keepalive
  tmux send-keys -t "$TMUX_SESSION" "" Enter 2>/dev/null || true
  log "No log file — keepalive sent"
fi

# Session is healthy
CRASH_COUNT=$(cat "$CRASH_FILE" 2>/dev/null || echo 0)
AGE_HUMAN=""
if [ -f "$AGE_FILE" ]; then
  STARTED=$(cat "$AGE_FILE" 2>/dev/null || echo 0)
  AGE_S=$(( $(date +%s) - STARTED ))
  AGE_HUMAN=" age=$(( AGE_S / 60 ))min"
fi
log "OK (model=$MODEL${AGE_HUMAN} crashes=$CRASH_COUNT)"
