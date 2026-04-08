#!/bin/bash
# ============================================================================
# Telegram Channels Setup for StoryEngine Agent Dashboard
# ============================================================================
# Manages the Claude Code Telegram bot session on the VPS.
#
# Prerequisites:
#   1. Create a Telegram bot via BotFather (https://t.me/BotFather)
#   2. Claude Code installed on VPS
#   3. Bun installed: curl -fsSL https://bun.sh/install | bash
#
# Usage:
#   bash telegram-channels-setup.sh setup     # First-time setup
#   bash telegram-channels-setup.sh start     # Start the channel session
#   bash telegram-channels-setup.sh stop      # Stop the channel session
#   bash telegram-channels-setup.sh status    # Check if running (detailed)
#   bash telegram-channels-setup.sh diagnose  # Full diagnostic dump
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="${AGENT_PROJECT_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
TMUX_SESSION="telegram-channel"
LOG_DIR="/tmp/storyengine-agents"
LOG_FILE="$LOG_DIR/telegram-channel.log"
MODEL="${TELEGRAM_MODEL:-haiku}"

mkdir -p "$LOG_DIR"

# ─── Prerequisite checks ───────────────────────────────────────────────────
check_prerequisites() {
  local errors=0

  echo "Checking prerequisites..."

  # Claude CLI
  if command -v claude &>/dev/null; then
    local ver
    ver=$(claude --version 2>/dev/null | head -1 || echo "unknown")
    echo "  ✓ Claude CLI installed ($ver)"
  else
    echo "  ✗ Claude CLI not found"
    errors=$((errors + 1))
  fi

  # Bun
  if command -v bun &>/dev/null; then
    echo "  ✓ Bun installed"
  else
    echo "  ✗ Bun not found — run: curl -fsSL https://bun.sh/install | bash"
    errors=$((errors + 1))
  fi

  # tmux
  if command -v tmux &>/dev/null; then
    echo "  ✓ tmux installed"
  else
    echo "  ✗ tmux not found — run: apt install tmux"
    errors=$((errors + 1))
  fi

  # Telegram config
  local tg_env="$HOME/.claude/channels/telegram/.env"
  local tg_approved="$HOME/.claude/channels/telegram/approved"
  if [ -f "$tg_env" ]; then
    echo "  ✓ Telegram bot token configured"
  else
    echo "  ✗ Telegram bot token missing ($tg_env)"
    echo "    Run: claude --channels plugin:telegram@claude-plugins-official"
    echo "    Then: /telegram:configure YOUR_BOT_TOKEN"
    errors=$((errors + 1))
  fi

  if [ -d "$tg_approved" ] && [ -n "$(ls -A "$tg_approved" 2>/dev/null)" ]; then
    local chats
    chats=$(ls "$tg_approved" | wc -l)
    echo "  ✓ $chats approved Telegram chat(s)"
  else
    echo "  ⚠ No approved Telegram chats — bot will start but can't receive messages"
    echo "    Pair: message your bot on Telegram, then /telegram:access pair CODE"
  fi

  # Healthcheck cron
  if crontab -l 2>/dev/null | grep -q "telegram-healthcheck.sh"; then
    echo "  ✓ Healthcheck cron installed"
  else
    echo "  ⚠ Healthcheck cron not installed — bot won't auto-restart"
    echo "    Fix: bash $SCRIPT_DIR/../../storyengine/agents/setup-crons.sh"
    echo "    Or:  the healthcheck will self-install on first run"
  fi

  return $errors
}

case "${1:-help}" in

setup)
  echo "=== Telegram Channel Setup ==="
  echo ""
  check_prerequisites
  echo ""
  echo "Step 1: Install the Telegram plugin"
  echo "  Run in Claude Code:"
  echo "    /plugin marketplace add anthropics/claude-plugins-official"
  echo "    /plugin install telegram@claude-plugins-official"
  echo "    /reload-plugins"
  echo ""
  echo "Step 2: Configure your bot token"
  echo "  Run in Claude Code:"
  echo "    /telegram:configure YOUR_BOT_TOKEN_FROM_BOTFATHER"
  echo ""
  echo "Step 3: Start with channels enabled"
  echo "  Exit Claude Code, then run:"
  echo "    bash telegram-channels-setup.sh start"
  echo ""
  echo "Step 4: Pair your Telegram account"
  echo "  - Open Telegram, message your bot"
  echo "  - Copy the pairing code it replies with"
  echo "  - In the Claude session, run:"
  echo "    /telegram:access pair YOUR_CODE"
  echo "    /telegram:access policy allowlist"
  echo ""
  echo "After pairing, you can message your bot from Telegram and"
  echo "Claude will respond with full project context."
  ;;

start)
  echo "Starting Telegram channel session..."
  echo ""
  check_prerequisites || {
    echo ""
    echo "Fix the issues above before starting."
    exit 1
  }
  echo ""

  # Check if already running
  if tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
    echo "Session '$TMUX_SESSION' already running."
    echo "  Attach: tmux attach -t $TMUX_SESSION"
    echo "  Stop:   bash telegram-channels-setup.sh stop"
    exit 1
  fi

  # Kill zombie telegram plugin processes
  pkill -f 'bun.*telegram.*start' 2>/dev/null || true
  sleep 2

  # Start in tmux with script PTY wrapper
  tmux new-session -d -s "$TMUX_SESSION" \
    "cd $PROJECT_ROOT && script -q -f $LOG_FILE -c 'claude --channels plugin:telegram@claude-plugins-official --model $MODEL --dangerously-skip-permissions'"

  # Record start time
  date +%s > "$LOG_DIR/telegram-channel-started"
  tmux list-panes -t "$TMUX_SESSION" -F '#{pane_pid}' 2>/dev/null | head -1 > "$LOG_DIR/telegram-channel.pid"

  # Wait for Claude to actually start
  echo "Waiting for Claude to initialize..."
  local attempts=0
  for i in $(seq 1 6); do
    sleep 5
    if pstree -p "$(cat "$LOG_DIR/telegram-channel.pid" 2>/dev/null)" 2>/dev/null | grep -qE 'claude|node'; then
      echo ""
      echo "Telegram channel started successfully!"
      echo "  Model:  $MODEL"
      echo "  Attach: tmux attach -t $TMUX_SESSION"
      echo "  Logs:   tail -f $LOG_FILE"
      echo "  Stop:   bash telegram-channels-setup.sh stop"
      exit 0
    fi
    printf "."
  done
  echo ""
  echo "WARNING: tmux session started but Claude process not yet detected."
  echo "This may be normal (slow startup). Check:"
  echo "  tmux attach -t $TMUX_SESSION"
  ;;

stop)
  if tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
    tmux kill-session -t "$TMUX_SESSION"
    pkill -f 'bun.*telegram.*start' 2>/dev/null || true
    rm -f "$LOG_DIR/telegram-channel.pid"
    echo "Telegram channel session stopped."
  else
    echo "No active session found."
  fi
  ;;

status)
  echo "=== Telegram Bot Status ==="
  echo ""

  # Session
  if tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
    echo "tmux session: RUNNING"
    local pane_pid
    pane_pid=$(tmux list-panes -t "$TMUX_SESSION" -F '#{pane_pid}' 2>/dev/null | head -1)
    if [ -n "$pane_pid" ] && pstree -p "$pane_pid" 2>/dev/null | grep -qE 'claude|node'; then
      echo "Claude process: ALIVE"
    else
      echo "Claude process: DEAD (zombie session)"
    fi
  else
    echo "tmux session: NOT RUNNING"
  fi

  # Age
  if [ -f "$LOG_DIR/telegram-channel-started" ]; then
    local started age_s
    started=$(cat "$LOG_DIR/telegram-channel-started" 2>/dev/null || echo 0)
    age_s=$(( $(date +%s) - started ))
    echo "Session age: $(( age_s / 60 )) minutes"
  fi

  # Log freshness
  if [ -f "$LOG_FILE" ]; then
    local log_age
    log_age=$(( $(date +%s) - $(stat -c %Y "$LOG_FILE" 2>/dev/null || echo 0) ))
    echo "Last log write: ${log_age}s ago"
  else
    echo "Log file: not found"
  fi

  # Crash state
  local crashes
  crashes=$(cat "$LOG_DIR/telegram-crash-count" 2>/dev/null || echo 0)
  echo "Consecutive crashes: $crashes"
  if [ -f "$LOG_DIR/telegram-backoff-until" ]; then
    local until remaining
    until=$(cat "$LOG_DIR/telegram-backoff-until" 2>/dev/null || echo 0)
    remaining=$(( until - $(date +%s) ))
    if [ "$remaining" -gt 0 ]; then
      echo "Backoff: ${remaining}s remaining"
    fi
  fi

  # Cron
  echo ""
  if crontab -l 2>/dev/null | grep -q "telegram-healthcheck.sh"; then
    echo "Healthcheck cron: INSTALLED"
  else
    echo "Healthcheck cron: MISSING (bot won't auto-restart!)"
  fi

  # Config
  echo ""
  if [ -f "$HOME/.claude/channels/telegram/.env" ]; then
    echo "Bot token: configured"
  else
    echo "Bot token: MISSING"
  fi
  local approved_count
  approved_count=$(ls "$HOME/.claude/channels/telegram/approved/" 2>/dev/null | wc -l)
  echo "Approved chats: $approved_count"
  ;;

diagnose)
  echo "=== Full Diagnostic Dump ==="
  echo ""
  bash "$0" status
  echo ""
  echo "=== Recent healthcheck log ==="
  tail -30 "$LOG_DIR/telegram-healthcheck.log" 2>/dev/null || echo "(no log)"
  echo ""
  echo "=== Recent session log (last 20 lines) ==="
  tail -20 "$LOG_FILE" 2>/dev/null || echo "(no log)"
  echo ""
  echo "=== tmux pane contents ==="
  tmux capture-pane -t "$TMUX_SESSION" -p 2>/dev/null | tail -20 || echo "(no session)"
  echo ""
  echo "=== Process tree ==="
  local pid
  pid=$(tmux list-panes -t "$TMUX_SESSION" -F '#{pane_pid}' 2>/dev/null | head -1)
  if [ -n "$pid" ]; then
    pstree -p "$pid" 2>/dev/null || echo "(no process tree)"
  else
    echo "(no tmux pane)"
  fi
  echo ""
  echo "=== Telegram-related processes ==="
  pgrep -af 'telegram|bun.*start' 2>/dev/null || echo "(none)"
  ;;

*)
  echo "Usage: bash telegram-channels-setup.sh {setup|start|stop|status|diagnose}"
  echo ""
  echo "Commands:"
  echo "  setup    — Show first-time setup instructions + prerequisite check"
  echo "  start    — Start the Telegram channel in tmux (with verification)"
  echo "  stop     — Stop the channel session"
  echo "  status   — Detailed status: session, process, crashes, config"
  echo "  diagnose — Full diagnostic dump for debugging"
  ;;

esac
