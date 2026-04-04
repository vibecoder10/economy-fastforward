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
MODEL="${TELEGRAM_MODEL:-haiku}"
# Restart every 4 hours to prevent context window overflow
MAX_AGE_SECONDS=14400
AGE_FILE="/tmp/storyengine-agents/telegram-channel-started"

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

start_session() {
  # Kill any stale tmux session remnants
  tmux kill-session -t "$TMUX_SESSION" 2>/dev/null || true
  sleep 2

  # Start with --channels + model. Uses 'script' to preserve PTY (Claude exits in print mode if no TTY)
  # --channels is REQUIRED for Telegram notification listener
  tmux new-session -d -s "$TMUX_SESSION" \
    "cd $PROJECT_ROOT && script -q -f $LOG_FILE -c '$CLAUDE_BIN --channels plugin:telegram@claude-plugins-official --model $MODEL --dangerously-skip-permissions'"

  # Record start time for age checks
  date +%s > "$AGE_FILE"

  sleep 5
}

# ─── Check 1: Is session alive? ──────────────────────────────────────────────
if ! session_is_alive; then
  echo "[$(date)] Telegram channel is DOWN — restarting..."
  start_session

  if session_is_alive; then
    echo "[$(date)] Telegram channel restarted successfully (model=$MODEL)"
    notify_telegram "Telegram channel was down — auto-restarted at $(date +%H:%M)" 2>/dev/null || true
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
    else
      echo "[$(date)] FAILED to recycle Telegram channel"
      notify_telegram "CRITICAL: Telegram channel failed to recycle. Manual intervention needed." 2>/dev/null || true
    fi
    exit 0
  fi
fi

echo "[$(date)] Telegram channel is running (model=$MODEL)"
