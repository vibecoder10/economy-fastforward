#!/bin/bash
# Telegram Channel Healthcheck
# Checks if the tmux session 'telegram-channel' is alive.
# If dead, restarts it and sends a Telegram alert via direct API call.
# Called every 15 minutes by cron.
#
# Mirrors the pattern in: skills/video-pipeline/infra/bot_healthcheck.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="${AGENT_PROJECT_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
TMUX_SESSION="telegram-channel"
LOG_FILE="/tmp/storyengine-agents/telegram-channel.log"
CLAUDE_BIN="${CLAUDE_BIN:-claude}"
SYSTEM_PROMPT_FILE="$PROJECT_ROOT/rubric/scaffold/telegram-system-prompt.md"
MODEL="${TELEGRAM_MODEL:-sonnet}"
# Restart every 2 hours to prevent context window overflow and idle timeouts
# Was 4 hours (14400s) but Claude Code sessions go unresponsive before that
MAX_AGE_SECONDS=7200
AGE_FILE="/tmp/storyengine-agents/telegram-channel-started"

mkdir -p "$(dirname "$LOG_FILE")"

# Source Telegram helper for notify_telegram()
source "$PROJECT_ROOT/storyengine/agents/notify-telegram.sh" 2>/dev/null || true

# Check if tmux session exists
session_exists() {
  tmux has-session -t "$TMUX_SESSION" 2>/dev/null
}

# Check if Claude process is actually running inside the session
# The tmux session can stay alive (via 'script' wrapper) even after Claude exits/hangs.
# This is the root cause of the mid-day timeout: healthcheck saw tmux alive but Claude was dead.
claude_process_alive() {
  # Get the PID of the tmux pane's shell, then check if claude/node is a descendant
  local pane_pid
  pane_pid=$(tmux list-panes -t "$TMUX_SESSION" -F '#{pane_pid}' 2>/dev/null | head -1)
  [ -z "$pane_pid" ] && return 1

  # Look for claude or node process in the process tree under the tmux pane
  pgrep -P "$(pgrep -P "$pane_pid" -d,)" -a 2>/dev/null | grep -qE 'claude|node' && return 0
  # Also check direct children (process tree varies by OS)
  pstree -p "$pane_pid" 2>/dev/null | grep -qE 'claude|node' && return 0

  return 1
}

# Check if the log file has been written to recently (stale = bot is dead/hung)
log_is_fresh() {
  [ ! -f "$LOG_FILE" ] && return 1
  local last_mod now age
  last_mod=$(stat -c %Y "$LOG_FILE" 2>/dev/null || echo 0)
  now=$(date +%s)
  age=$((now - last_mod))
  # If log hasn't been touched in 30 minutes, consider it stale
  # (Telegram plugin polls regularly, so a healthy session writes to log)
  [ "$age" -lt 1800 ]
}

# Full liveness check: tmux exists AND (claude process alive OR log is fresh)
session_is_alive() {
  if ! session_exists; then
    echo "[$(date)] tmux session does not exist"
    return 1
  fi

  if claude_process_alive; then
    return 0
  fi

  if log_is_fresh; then
    # Log is fresh, Claude might be between operations — give benefit of doubt
    return 0
  fi

  echo "[$(date)] tmux session exists but Claude process is dead and log is stale"
  return 1
}

start_session() {
  # Kill any stale tmux session remnants
  tmux kill-session -t "$TMUX_SESSION" 2>/dev/null || true

  # Kill zombie telegram plugin processes (only ONE bot polling consumer allowed)
  pkill -f 'bun.*telegram.*start' 2>/dev/null || true
  sleep 3

  # Start with --channels + model. Uses 'script' to preserve PTY (Claude exits in print mode if no TTY)
  # --channels is REQUIRED for Telegram notification listener
  # PATH must include bun (Telegram MCP server requires it) and npm-global (for claude CLI)
  tmux new-session -d -s "$TMUX_SESSION" \
    "export PATH=/home/clawd/.bun/bin:/home/clawd/.npm-global/bin:/home/clawd/bin:\$PATH && cd $PROJECT_ROOT && script -q -f $LOG_FILE -c '$CLAUDE_BIN --channels plugin:telegram@claude-plugins-official --model $MODEL --dangerously-skip-permissions'"

  # Record start time for age checks
  date +%s > "$AGE_FILE"

  sleep 5
}

# ─── Check 1: Is session alive? ──────────────────────────────────────────────
if ! session_is_alive; then
  # Determine if this is a zombie (tmux alive but Claude dead) vs fully dead
  if session_exists; then
    echo "[$(date)] Telegram channel is ZOMBIE (tmux alive, Claude dead) — recycling..."
    RESTART_REASON="zombie session (Claude process died inside tmux)"
  else
    echo "[$(date)] Telegram channel is DOWN — restarting..."
    RESTART_REASON="session not running"
  fi

  start_session

  if session_exists; then
    echo "[$(date)] Telegram channel restarted successfully (model=$MODEL, reason=$RESTART_REASON)"
    notify_telegram "Telegram bot restarted: $RESTART_REASON ($(date +%H:%M))" 2>/dev/null || true
    # Check if the new session hit an auth error (OAuth token expired)
    sleep 8
    if tmux capture-pane -t "$TMUX_SESSION" -p 2>/dev/null | grep -qE 'Please run /login|authentication_error|token has expired'; then
      echo "[$(date)] AUTH ERROR: OAuth token expired — bot is stuck at login prompt"
      notify_telegram "🔑 Telegram bot OAuth token EXPIRED. Bot is up but can't respond. SSH in and run /login to fix." 2>/dev/null || true
    fi
  else
    echo "[$(date)] FAILED to restart Telegram channel"
    notify_telegram "CRITICAL: Telegram channel failed to restart. Manual intervention needed." 2>/dev/null || true
  fi
  exit 0
fi

# ─── Check 2: Is session too old? (context overflow prevention) ──────────────
if [ -f "$AGE_FILE" ]; then
  STARTED_AT=$(cat "$AGE_FILE" 2>/dev/null || echo 0)
  NOW=$(date +%s)
  AGE=$((NOW - STARTED_AT))

  if [ "$AGE" -gt "$MAX_AGE_SECONDS" ]; then
    echo "[$(date)] Telegram channel is ${AGE}s old (max ${MAX_AGE_SECONDS}s) — recycling to clear context..."
    start_session

    if session_is_alive; then
      echo "[$(date)] Telegram channel recycled successfully (model=$MODEL)"
      # Check if recycled session hit an auth error
      sleep 8
      if tmux capture-pane -t "$TMUX_SESSION" -p 2>/dev/null | grep -qE 'Please run /login|authentication_error|token has expired'; then
        echo "[$(date)] AUTH ERROR: OAuth token expired after recycle"
        notify_telegram "🔑 Telegram bot OAuth token EXPIRED. Bot is up but can't respond. SSH in and run /login to fix." 2>/dev/null || true
      fi
    else
      echo "[$(date)] FAILED to recycle Telegram channel"
      notify_telegram "CRITICAL: Telegram channel failed to recycle. Manual intervention needed." 2>/dev/null || true
    fi
    exit 0
  fi
fi

# ─── Check 3: Auth error detection — catch expired OAuth mid-session ─────────
# If the token expires while the session is running, Claude will print an auth
# error but the process stays alive. Detect this and alert immediately.
if tmux capture-pane -t "$TMUX_SESSION" -p 2>/dev/null | grep -qE 'Please run /login|authentication_error|token has expired'; then
  echo "[$(date)] AUTH ERROR: OAuth token expired in running session"
  notify_telegram "🔑 Telegram bot OAuth token EXPIRED. Bot is up but can't respond. SSH in and run /login to fix." 2>/dev/null || true
  exit 0
fi

# ─── Check 4: Keepalive — prevent Claude idle timeout ────────────────────────
# Claude Code sessions can go idle and stop processing channel messages
# even though the process is technically alive. Sending an empty Enter
# keystroke to the tmux pane resets the idle timer.
# This runs every 15 min (via cron), which is well within typical idle timeouts.
tmux send-keys -t "$TMUX_SESSION" "" Enter 2>/dev/null || true

echo "[$(date)] Telegram channel is running (model=$MODEL, keepalive sent)"
