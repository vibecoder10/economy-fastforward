#!/usr/bin/env bash
# The ONE sanctioned way to deploy StoryEngine on the VPS.
#
# Why this exists: multiple agent sessions work this box in parallel. A raw
# restart kills uvicorn's in-process background tasks — i.e. another session's
# RUNNING VIDEO BUILD — and ships whatever is on main at that second. This
# script serializes deploys behind a lock file and leaves an audit trail.
#
# Usage (on the VPS):
#   ~/projects/economy-fastforward/storyengine/scripts/vps-deploy.sh <session-name> [--with-frontend] [--with-remotion] [--force]
#
# Lock protocol (~/deploy.lock):
#   - ANY session doing prod work that must not be interrupted (a deploy, a
#     proof run, a paid pipeline run) writes its name + task + timestamp into
#     ~/deploy.lock, and removes it when done.
#   - This script REFUSES to run while the lock exists (unless --force, which
#     only overrides a known-stale operator lock). --force NEVER bypasses the
#     active-work drain/wait.
set -euo pipefail

LOCK="$HOME/deploy.lock"
REPO="$HOME/projects/economy-fastforward"
LOG="$HOME/deploys.log"
WHO="${1:?usage: vps-deploy.sh <session-name> [--with-frontend] [--with-remotion] [--force]}"
shift || true
ARGS="${*:-}"
DRAIN_TIMEOUT_SECONDS="${DRAIN_TIMEOUT_SECONDS:-7200}"
KILL_BIN="${STORYENGINE_KILL_BIN:-/bin/kill}"

if [ -f "$LOCK" ] && [[ "$ARGS" != *--force* ]]; then
  echo "DEPLOY BLOCKED — another session holds the lock:"
  cat "$LOCK"
  echo "Wait for it to finish, or rerun with --force ONLY if the lock is stale (>2h old)."
  exit 1
fi

printf '%s deploying, started %s\n' "$WHO" "$(date -u +%FT%TZ)" > "$LOCK"
DRAIN_SET=0

# Python runtime used by the backend and the direct-to-Postgres drain control.
PYTHON="python3"
for v in "$REPO/storyengine/backend/.venv" "$REPO/storyengine/backend/venv" "$HOME/.venv" "$HOME/venv"; do
  [ -x "$v/bin/python3" ] && PYTHON="$v/bin/python3"
done
DRAIN="$REPO/storyengine/scripts/drain_control.py"

cleanup() {
  code=$?
  trap - EXIT INT TERM
  if [ "$DRAIN_SET" = "1" ]; then
    if ! "$PYTHON" "$DRAIN" undrain \
      --owner "deploy:$WHO" \
      --reason "deploy command exited with status $code"; then
      echo "CRITICAL — automatic undrain failed. Recover with: se undrain --owner deploy:$WHO" >&2
    fi
  fi
  rm -f "$LOCK"
  exit "$code"
}
trap cleanup EXIT INT TERM

# Close the race BEFORE looking at active work. The DB transition and every
# generation claim share one advisory transaction lock, so once this returns,
# no later paid claim can enter. Existing work is not cancelled.
"$PYTHON" "$DRAIN" drain \
  --owner "deploy:$WHO" \
  --reason "safe production deploy"
DRAIN_SET=1

echo "drain: enabled; waiting for active work to finish (timeout ${DRAIN_TIMEOUT_SECONDS}s)"
"$PYTHON" "$DRAIN" wait \
  --timeout "$DRAIN_TIMEOUT_SECONDS" \
  --interval 5 \
  --settle 2

cd "$REPO"
BEFORE=$(git rev-parse --short HEAD)
git pull --ff-only
AFTER=$(git rev-parse --short HEAD)
echo "code: $BEFORE -> $AFTER"

# Python deps (venv if one exists next to the backend, else user install).
PIP="pip3"
for v in "$REPO/storyengine/backend/.venv" "$REPO/storyengine/backend/venv" "$HOME/.venv" "$HOME/venv"; do
  [ -x "$v/bin/pip" ] && PIP="$v/bin/pip"
done
$PIP install -q -r storyengine/backend/requirements.txt || \
  $PIP install -q --user -r storyengine/backend/requirements.txt || \
  echo "WARN: pip install failed — check deps by hand"

if [[ "$ARGS" == *--with-remotion* ]]; then
  (
    cd remotion-video
    npm ci --no-audit --no-fund
    npm run generate:motion-audio
    npm run typecheck
    npm ls @fontsource/noto-sans --depth=0 >/dev/null
    test -f node_modules/@fontsource/noto-sans/latin-ext-400.css
    test -f node_modules/@fontsource/noto-sans/latin-ext-600.css
    test -f node_modules/@fontsource/noto-sans/latin-ext-700.css
    find node_modules/@fontsource/noto-sans/files -type f -name '*.woff2' \
      -print -quit | grep -q .
  )
  REMOTION_BROWSER=$(command -v google-chrome || command -v chromium || true)
  if [ ! -x remotion-video/node_modules/.bin/remotion ] || [ -z "$REMOTION_BROWSER" ]; then
    echo "DEPLOY FAILED — Remotion CLI or browser runtime is unavailable." >&2
    exit 1
  fi
  echo "remotion runtime: verified ($REMOTION_BROWSER)"
  (
    cd storyengine/backend
    "$PYTHON" scripts/run_migrations_strict.py
  )
  echo "remotion schema: strict migrations complete"
fi

# Restart the backend by its exact unit PID. NEVER pkill -f uvicorn on this
# box — it has matched voice-osiris AND the ssh session itself before.
PID=$(systemctl show -p MainPID --value storyengine-backend.service)
if [ -n "$PID" ] && [ "$PID" != "0" ]; then kill -9 "$PID"; fi
sleep 4
for _ in 1 2 3 4 5; do
  systemctl is-active --quiet storyengine-backend.service && break
  sleep 3
done
echo "backend: $(systemctl is-active storyengine-backend.service)"

BACKEND_OK=0
for _ in 1 2 3 4 5 6 7 8 9 10; do
  HEALTH=$(curl -sf --max-time 5 http://localhost:8001/api/health 2>/dev/null || true)
  if [[ "$HEALTH" == *'"status":"healthy"'* ]] && [[ "$HEALTH" == *'"draining":true'* ]]; then
    BACKEND_OK=1
    break
  fi
  sleep 3
done
if [ "$BACKEND_OK" != "1" ]; then
  echo "DEPLOY FAILED — backend did not become healthy while drain stayed enabled." >&2
  echo "${HEALTH:-no health response}" >&2
  exit 1
fi
echo "backend health: verified (drain still enabled)"

# Restart the arq worker from the same freshly pulled checkout. A backend-only
# restart leaves a long-lived worker importing the previous Python source.
# Resolve and kill only this unit's exact MainPID; NEVER pkill by command line.
WORKER_UNIT="storyengine-worker.service"
WORKER_PID=$(systemctl show -p MainPID --value "$WORKER_UNIT")
if [ -z "$WORKER_PID" ] || [ "$WORKER_PID" = "0" ]; then
  echo "DEPLOY FAILED — worker unit has no exact MainPID to restart." >&2
  exit 1
fi
"$KILL_BIN" -9 "$WORKER_PID"

NEW_WORKER_PID=""
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if systemctl is-active --quiet "$WORKER_UNIT"; then
    NEW_WORKER_PID=$(systemctl show -p MainPID --value "$WORKER_UNIT")
    if [ -n "$NEW_WORKER_PID" ] \
      && [ "$NEW_WORKER_PID" != "0" ] \
      && [ "$NEW_WORKER_PID" != "$WORKER_PID" ]; then
      break
    fi
  fi
  sleep 3
done
if [ -z "$NEW_WORKER_PID" ] \
  || [ "$NEW_WORKER_PID" = "0" ] \
  || [ "$NEW_WORKER_PID" = "$WORKER_PID" ]; then
  echo "DEPLOY FAILED — worker did not restart with a fresh exact MainPID." >&2
  exit 1
fi

EXPECTED_WORKER_DIR=$(readlink -f "$REPO/storyengine/backend" 2>/dev/null || true)
WORKER_DIR=$(systemctl show -p WorkingDirectory --value "$WORKER_UNIT")
WORKER_DIR=$(readlink -f "$WORKER_DIR" 2>/dev/null || true)
WORKER_EXEC=$(systemctl show -p ExecStart --value "$WORKER_UNIT")
if [ "$WORKER_DIR" != "$EXPECTED_WORKER_DIR" ] \
  || [[ "$WORKER_EXEC" != *"$EXPECTED_WORKER_DIR/"* ]]; then
  echo "DEPLOY FAILED — worker is not running from the deployed checkout." >&2
  echo "worker directory: ${WORKER_DIR:-missing}" >&2
  echo "worker exec: ${WORKER_EXEC:-missing}" >&2
  exit 1
fi
echo "worker: active (pid $NEW_WORKER_PID)"
echo "worker code parity: commit=$AFTER directory=$WORKER_DIR"

if [[ "$ARGS" == *--with-frontend* ]]; then
  (cd storyengine/frontend && npm run build)
  FPID=$(systemctl show -p MainPID --value storyengine-frontend.service)
  if [ -n "$FPID" ] && [ "$FPID" != "0" ]; then kill -9 "$FPID"; fi
  sleep 4
  echo "frontend: $(systemctl is-active storyengine-frontend.service)"
  # Poll like the backend section above. Next.js cold-starts slower than the 4s
  # pause, so a single bare curl (exit 7 under `set -e`, no `|| true`) used to
  # abort the whole script before the deploys.log append — a green deploy
  # reported dead. Retry until it answers 200, only fail after the full window.
  FRONTEND_OK=0
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    FRONTEND_HTTP=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://localhost:3001 2>/dev/null || true)
    if [ "$FRONTEND_HTTP" = "200" ]; then
      FRONTEND_OK=1
      break
    fi
    sleep 3
  done
  if [ "$FRONTEND_OK" != "1" ]; then
    echo "DEPLOY FAILED — frontend did not return HTTP 200 (last: ${FRONTEND_HTTP:-no response})." >&2
    exit 1
  fi
  echo "frontend health: HTTP 200"
fi

printf '%s %s deployed %s -> %s %s\n' "$(date -u +%FT%TZ)" "$WHO" "$BEFORE" "$AFTER" "$ARGS" >> "$LOG"
echo "DONE — deployed $AFTER; automatic undrain follows (log: $LOG)"
