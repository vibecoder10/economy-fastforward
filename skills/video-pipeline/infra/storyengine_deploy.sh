#!/bin/bash
# Auto-rebuild StoryEngine frontend when code changes after git pull.
#
# Usage: bash infra/storyengine_deploy.sh
#
# How it works:
#   1. Compares current HEAD with the commit hash from the last successful build
#   2. If storyengine/frontend/ files changed between them: rebuild + restart
#   3. Stores commit hash on success so it doesn't rebuild unnecessarily
#
# State file: /tmp/storyengine-last-build-commit
# Run this via cron every 30 minutes (added by setup_cron.sh)

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"
FRONTEND_DIR="$REPO_DIR/storyengine/frontend"
STATE_FILE="/tmp/storyengine-last-build-commit"
LOG_FILE="/tmp/storyengine-deploy.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"; }

# Ensure frontend dir exists
if [ ! -d "$FRONTEND_DIR" ]; then
    log "ERROR: Frontend dir not found at $FRONTEND_DIR"
    exit 1
fi

# Get current commit
CURRENT_COMMIT=$(cd "$REPO_DIR" && git rev-parse HEAD 2>/dev/null)
LAST_BUILD_COMMIT=$(cat "$STATE_FILE" 2>/dev/null || echo "")

# First run — no state file yet. Record current commit, skip build
# (assume the currently running server matches the current code)
if [ -z "$LAST_BUILD_COMMIT" ]; then
    echo "$CURRENT_COMMIT" > "$STATE_FILE"
    log "First run — recorded current commit $CURRENT_COMMIT as baseline"
    exit 0
fi

# Same commit — nothing to do
if [ "$CURRENT_COMMIT" = "$LAST_BUILD_COMMIT" ]; then
    exit 0
fi

# Check if frontend files changed between last build and now
FRONTEND_CHANGES=$(cd "$REPO_DIR" && git diff --name-only "$LAST_BUILD_COMMIT" "$CURRENT_COMMIT" 2>/dev/null | grep "^storyengine/frontend/" | head -10)

if [ -z "$FRONTEND_CHANGES" ]; then
    # No frontend changes — update marker and skip
    echo "$CURRENT_COMMIT" > "$STATE_FILE"
    log "No frontend changes ($LAST_BUILD_COMMIT → $CURRENT_COMMIT), skipping build"
    exit 0
fi

log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
log "Frontend changes detected ($LAST_BUILD_COMMIT → $CURRENT_COMMIT):"
echo "$FRONTEND_CHANGES" >> "$LOG_FILE"

# Install deps if package-lock changed
if echo "$FRONTEND_CHANGES" | grep -q "package-lock.json"; then
    log "package-lock.json changed — running npm install"
    cd "$FRONTEND_DIR" && npm install >> "$LOG_FILE" 2>&1
fi

# Build
log "Running npm run build..."
cd "$FRONTEND_DIR"
if ! npm run build >> "$LOG_FILE" 2>&1; then
    log "BUILD FAILED — will retry on next run"
    # Send Slack alert if possible
    if [ -f "$REPO_DIR/.env" ]; then
        set -a; source "$REPO_DIR/.env"; set +a
    fi
    if [ -n "$SLACK_BOT_TOKEN" ]; then
        curl -s -X POST "https://slack.com/api/chat.postMessage" \
            -H "Authorization: Bearer $SLACK_BOT_TOKEN" \
            -H "Content-Type: application/json" \
            -d "$(jq -n --arg ch "${SLACK_CHANNEL_ID:-C0A9U1X8NSW}" \
                --arg txt ":warning: StoryEngine frontend build failed after code update. Check /tmp/storyengine-deploy.log" \
                '{channel: $ch, text: $txt}')" > /dev/null 2>&1 || true
    fi
    exit 1
fi

# Restart Next.js server
log "Build succeeded — restarting Next.js server..."
pkill -f "next start --port 3001" 2>/dev/null || true
pkill -f "next-server" 2>/dev/null || true
sleep 3

cd "$FRONTEND_DIR"
nohup npm run start >> /tmp/storyengine-frontend.log 2>&1 &
sleep 8

# Verify server is up
if curl -sI http://localhost:3001/ 2>/dev/null | grep -q "200"; then
    log "Server restarted successfully on port 3001"
    echo "$CURRENT_COMMIT" > "$STATE_FILE"
else
    log "WARNING: Server may not be responding after restart — check /tmp/storyengine-frontend.log"
    # Still update state to avoid rebuild loop
    echo "$CURRENT_COMMIT" > "$STATE_FILE"
fi
