#!/bin/bash
# ============================================================================
# Telegram Channels Setup for StoryEngine Agent Dashboard
# ============================================================================
# This script helps set up Claude Code Channels with Telegram on the VPS.
# It creates a persistent Claude session that receives Telegram messages
# and can interact with the RUBRIC dashboard API.
#
# Prerequisites:
#   1. Create a Telegram bot via BotFather (https://t.me/BotFather)
#      - Send /newbot, name it "StoryEngine Agents"
#      - Save the bot token
#   2. Claude Code v2.1.80+ installed on VPS
#   3. Bun installed: curl -fsSL https://bun.sh/install | bash
#
# Usage:
#   bash telegram-channels-setup.sh setup    # First-time setup
#   bash telegram-channels-setup.sh start    # Start the channel session
#   bash telegram-channels-setup.sh stop     # Stop the channel session
#   bash telegram-channels-setup.sh status   # Check if running
# ============================================================================

PROJECT_ROOT="${AGENT_PROJECT_ROOT:-/home/clawd/projects/economy-fastforward}"
TMUX_SESSION="telegram-channel"
LOG_FILE="/tmp/storyengine-agents/telegram-channel.log"
SYSTEM_PROMPT_FILE="$PROJECT_ROOT/rubric/scaffold/telegram-system-prompt.md"
MODEL="${TELEGRAM_MODEL:-sonnet}"

mkdir -p /tmp/storyengine-agents

case "${1:-help}" in

setup)
  echo "=== Telegram Channel Setup ==="
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

  # Check if already running
  if tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
    echo "Session '$TMUX_SESSION' already running. Use 'stop' first or 'tmux attach -t $TMUX_SESSION'."
    exit 1
  fi

  # Check bun is installed
  if ! command -v bun &>/dev/null; then
    echo "ERROR: Bun not installed. Run: curl -fsSL https://bun.sh/install | bash"
    exit 1
  fi

  # Kill zombie telegram plugin processes (only ONE bot polling consumer allowed)
  pkill -f 'bun.*telegram.*start' 2>/dev/null || true
  sleep 2

  # Start in tmux so it persists after SSH disconnect
  # Uses 'script' to preserve PTY (Claude exits in print mode if no TTY)
  # --channels enables channel notification listener (REQUIRED for Telegram)
  # --model for message routing
  tmux new-session -d -s "$TMUX_SESSION" \
    "export PATH=/home/clawd/.bun/bin:/home/clawd/.npm-global/bin:/home/clawd/bin:\$PATH && cd $PROJECT_ROOT && script -q -f $LOG_FILE -c 'claude --channels plugin:telegram@claude-plugins-official --model $MODEL --dangerously-skip-permissions'"

  echo "Telegram channel started in tmux session '$TMUX_SESSION'"
  echo "  Model: $MODEL"
  echo "  Attach: tmux attach -t $TMUX_SESSION"
  echo "  Logs:   tail -f $LOG_FILE"
  ;;

stop)
  if tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
    tmux kill-session -t "$TMUX_SESSION"
    echo "Telegram channel session stopped."
  else
    echo "No active session found."
  fi
  ;;

status)
  if tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
    echo "Telegram channel: RUNNING"
    echo "  Attach: tmux attach -t $TMUX_SESSION"
  else
    echo "Telegram channel: STOPPED"
    echo "  Start:  bash telegram-channels-setup.sh start"
  fi
  ;;

*)
  echo "Usage: bash telegram-channels-setup.sh {setup|start|stop|status}"
  echo ""
  echo "Commands:"
  echo "  setup   — Show first-time setup instructions"
  echo "  start   — Start the Telegram channel in tmux"
  echo "  stop    — Stop the channel session"
  echo "  status  — Check if the channel is running"
  ;;

esac
