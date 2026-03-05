#!/bin/bash
# Cron job wrapper — provides environment setup, error handling, locking,
# and Slack failure notifications for all pipeline cron jobs.
#
# Usage: cron_wrapper.sh <job-name> <log-file> <command...>
#
# Example:
#   cron_wrapper.sh "discovery" /tmp/pipeline-discover.log python pipeline.py --discover
#
# Features:
#   - Sources .env for API keys
#   - Detects Python venv automatically
#   - Sends Slack alert on failure (so you actually wake up to a notification)
#   - File locking to prevent overlapping runs
#   - Logs start/end time and exit code
#   - Git pull with graceful failure (non-blocking)

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

JOB_NAME="${1:?Usage: cron_wrapper.sh <job-name> <log-file> <command...>}"
LOG_FILE="${2:?Usage: cron_wrapper.sh <job-name> <log-file> <command...>}"
shift 2
COMMAND=("$@")

if [ ${#COMMAND[@]} -eq 0 ]; then
    echo "Error: no command specified"
    exit 1
fi

LOCK_FILE="/tmp/pipeline-${JOB_NAME}.lock"

# ── Locking ──────────────────────────────────────────────────────────
# Prevent overlapping runs of the same job
cleanup_lock() {
    rm -f "$LOCK_FILE"
}

if [ -f "$LOCK_FILE" ]; then
    LOCK_PID=$(cat "$LOCK_FILE" 2>/dev/null)

    # Check lock age — any lock older than MAX_LOCK_AGE is stale regardless of PID
    LOCK_AGE=$(( $(date +%s) - $(stat -c %Y "$LOCK_FILE" 2>/dev/null || echo 0) ))
    MAX_LOCK_AGE=${MAX_LOCK_AGE:-14400}  # Default 4 hours, overridable per job
    if [ "$LOCK_AGE" -gt "$MAX_LOCK_AGE" ]; then
        echo "[$(date)] Stale lock detected (age: ${LOCK_AGE}s > ${MAX_LOCK_AGE}s), removing" >> "$LOG_FILE"
        rm -f "$LOCK_FILE"
    elif [ -n "$LOCK_PID" ] && kill -0 "$LOCK_PID" 2>/dev/null; then
        # PID is alive — but verify it's actually a pipeline process, not a reused PID
        LOCK_PROC=$(ps -p "$LOCK_PID" -o comm= 2>/dev/null || echo "")
        if echo "$LOCK_PROC" | grep -qE "python|bash|pipeline"; then
            echo "[$(date)] SKIPPED: $JOB_NAME already running (PID $LOCK_PID, proc: $LOCK_PROC)" >> "$LOG_FILE"
            exit 0
        else
            echo "[$(date)] Stale lock: PID $LOCK_PID is '$LOCK_PROC' (not a pipeline process), removing" >> "$LOG_FILE"
            rm -f "$LOCK_FILE"
        fi
    else
        # PID is dead — stale lock
        echo "[$(date)] Cleaning stale lock (PID $LOCK_PID is dead)" >> "$LOG_FILE"
        rm -f "$LOCK_FILE"
    fi
fi

echo $$ > "$LOCK_FILE"
trap cleanup_lock EXIT

# ── Heartbeat — log immediately so we know cron fired ────────────────
echo "" >> "$LOG_FILE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" >> "$LOG_FILE"
echo "[$(date)] CRON FIRED: $JOB_NAME (PID $$)" >> "$LOG_FILE"

# ── Environment ──────────────────────────────────────────────────────
# Ensure standard tools are on PATH (cron has minimal PATH)
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"

# Source .env for API keys if it exists
if [ -f "$REPO_DIR/.env" ]; then
    set -a
    source "$REPO_DIR/.env"
    set +a
fi

# Detect Python — prefer the pipeline venv, fall back to repo venv, then system
detect_python() {
    local candidates=(
        "/home/clawd/pipeline-bot/venv/bin/python"
        "$REPO_DIR/venv/bin/python"
        "$SCRIPT_DIR/venv/bin/python"
    )
    for candidate in "${candidates[@]}"; do
        if [ -x "$candidate" ]; then
            echo "$candidate"
            return
        fi
    done
    # Fall back to system python3
    echo "python3"
}

PYTHON3=$(detect_python)
export PYTHON3

# ── Slack notification ───────────────────────────────────────────────
send_failure_alert() {
    local exit_code="$1"
    local tail_log="$2"

    local bot_token="${SLACK_BOT_TOKEN:-}"
    local channel_id="${SLACK_CHANNEL_ID:-C0A9U1X8NSW}"

    if [ -z "$bot_token" ]; then
        return
    fi

    local message=$(cat <<MSG
:rotating_light: *Cron Job Failed: ${JOB_NAME}*
Exit code: ${exit_code}
Time: $(date '+%Y-%m-%d %H:%M %Z')

\`\`\`
${tail_log}
\`\`\`

Check full log: \`${LOG_FILE}\`
MSG
)

    curl -s -X POST "https://slack.com/api/chat.postMessage" \
        -H "Authorization: Bearer $bot_token" \
        -H "Content-Type: application/json" \
        -d "$(jq -n --arg channel "$channel_id" --arg text "$message" \
            '{channel: $channel, text: $text}')" \
        > /dev/null 2>&1 || true
}

# ── Git pull (best-effort) ───────────────────────────────────────────
cd "$REPO_DIR" || {
    echo "[$(date)] FATAL: Cannot cd to $REPO_DIR" >> "$LOG_FILE"
    send_failure_alert 1 "Cannot cd to $REPO_DIR"
    exit 1
}

# Pull latest code — non-fatal if it fails (stale code is better than no run)
# Timeout prevents hangs from git prompts or network issues
if ! timeout 30 git pull origin main --ff-only >> "$LOG_FILE" 2>&1; then
    echo "[$(date)] WARNING: git pull failed or timed out — running with existing code" >> "$LOG_FILE"
fi

# ── Run the command ──────────────────────────────────────────────────
cd "$SCRIPT_DIR" || {
    echo "[$(date)] FATAL: Cannot cd to $SCRIPT_DIR" >> "$LOG_FILE"
    send_failure_alert 1 "Cannot cd to $SCRIPT_DIR"
    exit 1
}

# Replace "python" in command with detected Python path
FINAL_CMD=()
for arg in "${COMMAND[@]}"; do
    if [ "$arg" = "python" ] || [ "$arg" = "python3" ]; then
        FINAL_CMD+=("$PYTHON3")
    else
        FINAL_CMD+=("$arg")
    fi
done

echo "[$(date)] Running: ${FINAL_CMD[*]}" >> "$LOG_FILE"

# Execute with output to log
"${FINAL_CMD[@]}" >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

echo "[$(date)] END: $JOB_NAME (exit code: $EXIT_CODE)" >> "$LOG_FILE"

# ── Notify on failure ────────────────────────────────────────────────
if [ $EXIT_CODE -ne 0 ]; then
    TAIL_LOG=$(tail -20 "$LOG_FILE" 2>/dev/null || echo "(no log output)")
    send_failure_alert "$EXIT_CODE" "$TAIL_LOG"
fi

exit $EXIT_CODE
