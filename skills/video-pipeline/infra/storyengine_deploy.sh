#!/bin/bash
# Auto-deploy StoryEngine frontend AND backend when code changes after git pull.
#
# Usage: bash infra/storyengine_deploy.sh
#
# How it works:
#   1. Compares current HEAD with the commit hash from the last successful deploy
#   2. If storyengine/frontend/ files changed: rebuild + restart Next.js
#   3. If storyengine/backend/ files changed: restart uvicorn
#   4. Stores commit hash on success so it doesn't redeploy unnecessarily
#
# Frontend deploy strategy:
#   - Kill ALL Next.js processes and force-release port 3001
#   - Verify nothing is listening on 3001
#   - Build (site is briefly offline during ~60s build)
#   - Start new server only after build completes
#
# Backend deploy strategy:
#   - Kill uvicorn process (graceful SIGTERM → SIGKILL)
#   - Start new uvicorn process
#   - Verify health endpoint responds
#
# Root cause of stale chunks (frontend):
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
BACKEND_DIR="$REPO_DIR/storyengine/backend"
STATE_FILE="/tmp/storyengine-last-build-commit"
LOG_FILE="/tmp/storyengine-deploy.log"

# Detect backend Python — prefer backend venv, fall back to repo venv, then system
detect_backend_python() {
    local candidates=(
        "$BACKEND_DIR/venv/bin/python3"
        "$REPO_DIR/venv/bin/python3"
    )
    for candidate in "${candidates[@]}"; do
        if [ -x "$candidate" ]; then
            echo "$candidate"
            return
        fi
    done
    echo "python3"
}

BACKEND_PYTHON=$(detect_backend_python)

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"; }

slack_alert() {
    local msg="$1"
    if [ -f "$REPO_DIR/.env" ]; then
        set -a; source "$REPO_DIR/.env"; set +a
    fi
    if [ -n "$SLACK_BOT_TOKEN" ]; then
        curl -s -X POST "https://slack.com/api/chat.postMessage" \
            -H "Authorization: Bearer $SLACK_BOT_TOKEN" \
            -H "Content-Type: application/json" \
            -d "$(jq -n --arg ch "${SLACK_CHANNEL_ID:-C0A9U1X8NSW}" \
                --arg txt "$msg" \
                '{channel: $ch, text: $txt}')" > /dev/null 2>&1 || true
    fi
}

# Ensure dirs exist
if [ ! -d "$FRONTEND_DIR" ]; then
    log "ERROR: Frontend dir not found at $FRONTEND_DIR"
    exit 1
fi
if [ ! -d "$BACKEND_DIR" ]; then
    log "ERROR: Backend dir not found at $BACKEND_DIR"
    exit 1
fi

# Get current commit
CURRENT_COMMIT=$(cd "$REPO_DIR" && git rev-parse HEAD 2>/dev/null)
LAST_BUILD_COMMIT=$(cat "$STATE_FILE" 2>/dev/null || echo "")

# First run — no state file yet. Record current commit, skip build
# (assume the currently running servers match the current code)
if [ -z "$LAST_BUILD_COMMIT" ]; then
    echo "$CURRENT_COMMIT" > "$STATE_FILE"
    log "First run — recorded current commit $CURRENT_COMMIT as baseline"
    exit 0
fi

# Same commit — nothing to do
if [ "$CURRENT_COMMIT" = "$LAST_BUILD_COMMIT" ]; then
    exit 0
fi

# Check which parts changed between last build and now
FRONTEND_CHANGES=$(cd "$REPO_DIR" && git diff --name-only "$LAST_BUILD_COMMIT" "$CURRENT_COMMIT" 2>/dev/null | grep "^storyengine/frontend/" | head -10)
BACKEND_CHANGES=$(cd "$REPO_DIR" && git diff --name-only "$LAST_BUILD_COMMIT" "$CURRENT_COMMIT" 2>/dev/null | grep "^storyengine/backend/" | head -10)

if [ -z "$FRONTEND_CHANGES" ] && [ -z "$BACKEND_CHANGES" ]; then
    # No StoryEngine changes — update marker and skip
    echo "$CURRENT_COMMIT" > "$STATE_FILE"
    log "No StoryEngine changes ($LAST_BUILD_COMMIT → $CURRENT_COMMIT), skipping deploy"
    exit 0
fi

log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
log "StoryEngine changes detected ($LAST_BUILD_COMMIT → $CURRENT_COMMIT):"
[ -n "$FRONTEND_CHANGES" ] && { log "Frontend:"; echo "$FRONTEND_CHANGES" >> "$LOG_FILE"; }
[ -n "$BACKEND_CHANGES" ] && { log "Backend:"; echo "$BACKEND_CHANGES" >> "$LOG_FILE"; }

# ──────────────────────────────────────────────────────────────────
# BACKEND DEPLOY (if backend files changed)
# Restart uvicorn — no build step needed for Python
# Done BEFORE frontend so both are restarting in parallel-ish
# ──────────────────────────────────────────────────────────────────
if [ -n "$BACKEND_CHANGES" ]; then
    log "Restarting backend (uvicorn)..."

    # Install new deps if requirements.txt changed
    if echo "$BACKEND_CHANGES" | grep -q "requirements.txt"; then
        log "requirements.txt changed — running pip install"
        $BACKEND_PYTHON -m pip install -r "$BACKEND_DIR/requirements.txt" >> "$LOG_FILE" 2>&1
    fi

    # Graceful shutdown — port-scoped so this NEVER matches a sibling
    # service that also happens to run `uvicorn main:app` (e.g. the
    # systemd-managed prod backend, or any future app on this box).
    # This script starts its uvicorn with `--port 8001`, so 8001 is in argv.
    pkill -f "uvicorn main:app.*8001" 2>/dev/null || true

    # Wait up to 5 seconds for graceful stop
    for i in 1 2 3 4 5; do
        if ! pgrep -f "uvicorn main:app.*8001" > /dev/null 2>&1; then
            log "Backend stopped gracefully after ${i}s"
            break
        fi
        sleep 1
    done

    # Force kill if still alive
    pkill -9 -f "uvicorn main:app.*8001" 2>/dev/null || true
    sleep 1

    # Release port 8001
    fuser -k 8001/tcp 2>/dev/null || true
    sleep 1

    # Start fresh
    cd "$BACKEND_DIR"
    nohup $BACKEND_PYTHON -m uvicorn main:app --host 0.0.0.0 --port 8001 >> /tmp/storyengine-backend.log 2>&1 &
    BACKEND_PID=$!
    sleep 5

    # Verify backend is up
    if curl -sf http://localhost:8001/api/health > /dev/null 2>&1; then
        log "Backend restarted successfully (PID $BACKEND_PID)"
    else
        log "WARNING: Backend may not be responding — check /tmp/storyengine-backend.log"
        slack_alert ":warning: StoryEngine backend restart may have failed. Check /tmp/storyengine-backend.log"
    fi
fi

# ──────────────────────────────────────────────────────────────────
# FRONTEND DEPLOY (if frontend files changed)
# ──────────────────────────────────────────────────────────────────
if [ -n "$FRONTEND_CHANGES" ]; then

# Install deps if package-lock changed
if echo "$FRONTEND_CHANGES" | grep -q "package-lock.json"; then
    log "package-lock.json changed — running npm install"
    cd "$FRONTEND_DIR" && npm install >> "$LOG_FILE" 2>&1
fi

# ──────────────────────────────────────────────────────────────────
# STEP 1: Kill StoryEngine's OWN Next.js frontend and force-release
# its port. Scoped to processes whose cwd is FRONTEND_DIR — never a
# bare `pkill -f "next-server"` / `pkill -f "next start"`.
#
# WHY: a compiled Next.js server process shows up in `ps` as just
# "next-server (vX)" with no port or path in its argv, so a bare
# pkill -f matches EVERY Next.js app on the box by cmdline text alone.
# That's exactly what sent a clean SIGTERM to the Hailey follow-up
# processor's next-server on 2026-07-14 — it stayed down 6 days
# because nothing was watching it. Hailey now runs under systemd with
# Restart=always as a second safety net, but this script must not be
# able to touch it at all. Match on cwd instead of cmdline text.
# ──────────────────────────────────────────────────────────────────
log "Killing StoryEngine frontend (scoped to $FRONTEND_DIR)..."

storyengine_frontend_pids() {
    local pid cwd
    for pid in $(pgrep -f "next-server|next start|npm run start" 2>/dev/null); do
        cwd=$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)
        [ "$cwd" = "$FRONTEND_DIR" ] && echo "$pid"
    done
}

# SIGTERM first (graceful), cwd-scoped
for pid in $(storyengine_frontend_pids); do kill "$pid" 2>/dev/null || true; done

# Wait up to 5 seconds for graceful shutdown
for i in 1 2 3 4 5; do
    if [ -z "$(storyengine_frontend_pids)" ]; then
        log "Server stopped gracefully after ${i}s"
        break
    fi
    sleep 1
done

# SIGKILL anything still alive — still cwd-scoped, never a bare pkill -f
for pid in $(storyengine_frontend_pids); do kill -9 "$pid" 2>/dev/null || true; done
sleep 1

# Force-release port 3001 (handles OS TIME_WAIT state). fuser here
# targets whatever exact PID is bound to TCP port 3001, not a name
# pattern, so this stays scoped to StoryEngine's own port (Hailey
# listens on 3022, a different port, so it can never be the PID fuser
# finds here).
fuser -k 3001/tcp 2>/dev/null || true
sleep 1

# Verify port is free
if fuser 3001/tcp 2>/dev/null; then
    log "ERROR: Port 3001 still in use after kill — aborting deploy"
    exit 1
fi

log "Port 3001 confirmed free"

# ──────────────────────────────────────────────────────────────────
# STEP 2: Build (site is offline during this ~60s build window)
# ──────────────────────────────────────────────────────────────────
log "Running npm run build..."
cd "$FRONTEND_DIR"
if ! npm run build >> "$LOG_FILE" 2>&1; then
    log "BUILD FAILED — starting server with old build"
    nohup npm run start >> /tmp/storyengine-frontend.log 2>&1 &
    slack_alert ":warning: StoryEngine frontend build failed. Check /tmp/storyengine-deploy.log"
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
    log "Frontend restarted successfully on port 3001"
else
    log "WARNING: Frontend may not be responding — check /tmp/storyengine-frontend.log"
    slack_alert ":warning: StoryEngine frontend may not be responding after deploy. Check /tmp/storyengine-frontend.log"
fi

fi  # end frontend deploy

# ──────────────────────────────────────────────────────────────────
# Update state file — marks this commit as deployed
# ──────────────────────────────────────────────────────────────────
echo "$CURRENT_COMMIT" > "$STATE_FILE"
log "Deploy complete ($CURRENT_COMMIT)"
