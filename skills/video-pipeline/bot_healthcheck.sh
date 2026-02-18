#!/bin/bash
# Bot Health Check — verifies pipeline_control.py (Slack bot) is running.
# If the bot is down, restarts it and sends a Slack alert.
#
# Called every 15 minutes by cron.
# The bot MUST be running for emoji reactions on discovery messages to work.
#
# Logs: /tmp/pipeline-bot-health.log

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON3="/home/clawd/pipeline-bot/venv/bin/python"
PID_FILE="/tmp/pipeline-bot.pid"
BOT_SCRIPT="pipeline_control.py"

# Check if bot process is alive
bot_is_running() {
    # Check PID file first
    if [ -f "$PID_FILE" ]; then
        local pid
        pid=$(cat "$PID_FILE" 2>/dev/null)
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
    fi

    # Fallback: check if any python process is running pipeline_control.py
    if pgrep -f "$BOT_SCRIPT" > /dev/null 2>&1; then
        # Update PID file with found process
        pgrep -f "$BOT_SCRIPT" | head -1 > "$PID_FILE"
        return 0
    fi

    return 1
}

# Send Slack alert using curl (doesn't depend on Python being working)
send_slack_alert() {
    local message="$1"
    local webhook_url

    # Try to read Slack webhook from .env file
    if [ -f "$SCRIPT_DIR/../../.env" ]; then
        local bot_token
        bot_token=$(grep '^SLACK_BOT_TOKEN=' "$SCRIPT_DIR/../../.env" | cut -d'=' -f2- | tr -d '"' | tr -d "'")
        local channel_id
        channel_id=$(grep '^SLACK_CHANNEL_ID=' "$SCRIPT_DIR/../../.env" | cut -d'=' -f2- | tr -d '"' | tr -d "'" || echo "C0A9U1X8NSW")

        if [ -n "$bot_token" ]; then
            curl -s -X POST "https://slack.com/api/chat.postMessage" \
                -H "Authorization: Bearer $bot_token" \
                -H "Content-Type: application/json" \
                -d "{\"channel\": \"${channel_id:-C0A9U1X8NSW}\", \"text\": \"$message\"}" \
                > /dev/null 2>&1
        fi
    fi
}

# Main check
if bot_is_running; then
    echo "[$(date)] Bot is running (PID: $(cat "$PID_FILE" 2>/dev/null || echo '?'))"
else
    echo "[$(date)] Bot is DOWN! Attempting restart..."

    # Start the bot in the background
    cd "$SCRIPT_DIR"
    nohup $PYTHON3 "$BOT_SCRIPT" > /tmp/pipeline-bot.log 2>&1 &
    NEW_PID=$!
    echo "$NEW_PID" > "$PID_FILE"

    # Wait a moment and verify it started
    sleep 3

    if kill -0 "$NEW_PID" 2>/dev/null; then
        echo "[$(date)] Bot restarted successfully (PID: $NEW_PID)"
        send_slack_alert ":warning: *Pipeline Bot Restarted*\nThe Slack bot (pipeline_control.py) was found dead and has been auto-restarted.\nEmoji reactions on discovery messages should work again.\nPID: $NEW_PID"
    else
        echo "[$(date)] FAILED to restart bot!"
        send_slack_alert ":rotating_light: *Pipeline Bot FAILED to Restart*\nThe Slack bot is down and could not be restarted automatically.\nEmoji reactions on discovery messages will NOT work.\nPlease SSH in and start it manually: cd $SCRIPT_DIR && python3 pipeline_control.py"
    fi
fi
