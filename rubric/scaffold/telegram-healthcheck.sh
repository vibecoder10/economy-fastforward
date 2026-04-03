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

mkdir -p "$(dirname "$LOG_FILE")"

# Source Telegram helper for notify_telegram()
source "$PROJECT_ROOT/storyengine/agents/notify-telegram.sh" 2>/dev/null || true

# Check if tmux session exists and has a running process
session_is_alive() {
  if tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
    return 0
  fi
  return 1
}

# Main check
if session_is_alive; then
  echo "[$(date)] Telegram channel is running"
else
  echo "[$(date)] Telegram channel is DOWN — restarting..."

  # Kill any stale tmux session remnants
  tmux kill-session -t "$TMUX_SESSION" 2>/dev/null || true

  # Restart the Telegram Claude session
  tmux new-session -d -s "$TMUX_SESSION" \
    "cd $PROJECT_ROOT && $CLAUDE_BIN --channels plugin:telegram@claude-plugins-official --dangerously-skip-permissions 2>&1 | tee -a $LOG_FILE"

  # Wait for startup
  sleep 5

  if session_is_alive; then
    echo "[$(date)] Telegram channel restarted successfully"
    # Alert via direct Telegram API (session might not be ready yet for message relay)
    notify_telegram "Telegram channel was down — auto-restarted at $(date +%H:%M)"
  else
    echo "[$(date)] FAILED to restart Telegram channel"
    notify_telegram "CRITICAL: Telegram channel failed to restart. Manual intervention needed."
  fi
fi
