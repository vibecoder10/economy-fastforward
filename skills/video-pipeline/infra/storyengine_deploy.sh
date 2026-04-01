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
# Deploy strategy:
#   - Kill ALL Next.js processes and force-release port 3001
#   - Verify nothing is listening on 3001
#   - Build (site is briefly offline during ~60s build)
#   - Start new server only after build completes
#
# Root cause of stale chunks:
#   Next.js loads chunk manifest INTO MEMORY at startup. If an old server
#   process lingers while a new build changes chunk hashes, the old server
#   serves HTML referencing chunks that no longer exist → 500 errors.
#   The fix: ensure NO server runs during build + verify port is free.
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

# ──────────────────────────────────────────────────────────────────
# STEP 1: Kill ALL Next.js processes and force-release port
# Aggressive shutdown — we MUST guarantee nothing serves stale chunks
# ──────────────────────────────────────────────────────────────────
log "Killing all Next.js processes..."

# SIGTERM first (graceful)
pkill -f "next start" 2>/dev/null || true
pkill -f "next-server" 2>/dev/null || true

# Wait up to 5 seconds for graceful shutdown
for i in 1 2 3 4 5; do
    if ! pgrep -f "next-server" > /dev/null 2>&1; then
        log "Server stopped gracefully after ${i}s"
        break
    fi
    sleep 1
done

# SIGKILL anything still alive
pkill -9 -f "next-server" 2>/dev/null || true
pkill -9 -f "next start" 2>/dev/null || true
sleep 1

# Force-release port 3001 (handles OS TIME_WAIT state)
fuser -k 3001/tcp 2>/dev/null || true
sleep 1

# Verify port is free
if fuser 3001/tcp 2>/dev/null; then
    log "ERROR: Port 3001 still in use after kill — aborting deploy"
    exit 1
fi

log "Port 3001 confirmed free"

# ──────────────────────────────────────────────────────────────────
# STEP 2: Build (site is offline during this ~60s window)
# ──────────────────────────────────────────────────────────────────
log "Running npm run build..."
cd "$FRONTEND_DIR"
if ! npm run build >> "$LOG_FILE" 2>&1; then
    log "BUILD FAILED — starting server with old build"
    nohup npm run start >> /tmp/storyengine-frontend.log 2>&1 &
    # Send Slack alert
    if [ -f "$REPO_DIR/.env" ]; then
        set -a; source "$REPO_DIR/.env"; set +a
    fi
    if [ -n "$SLACK_BOT_TOKEN" ]; then
        curl -s -X POST "https://slack.com/api/chat.postMessage" \
            -H "Authorization: Bearer $SLACK_BOT_TOKEN" \
            -H "Content-Type: application/json" \
            -d "$(jq -n --arg ch "${SLACK_CHANNEL_ID:-C0A9U1X8NSW}" \
                --arg txt ":warning: StoryEngine frontend build failed. Check /tmp/storyengine-deploy.log" \
                '{channel: $ch, text: $txt}')" > /dev/null 2>&1 || true
    fi
    exit 1
fi

log "Build succeeded"

# ──────────────────────────────────────────────────────────────────
# STEP 3: Start new server (guaranteed fresh build, no stale chunks)
# ──────────────────────────────────────────────────────────────────
cd "$FRONTEND_DIR"
nohup npm run start >> /tmp/storyengine-frontend.log 2>&1 &
sleep 8

# Verify server is up
if curl -sI http://localhost:3001/ 2>/dev/null | grep -q "200"; then
    log "Server restarted successfully on port 3001"
    echo "$CURRENT_COMMIT" > "$STATE_FILE"
else
    log "WARNING: Server may not be responding — check /tmp/storyengine-frontend.log"
    echo "$CURRENT_COMMIT" > "$STATE_FILE"
fi
