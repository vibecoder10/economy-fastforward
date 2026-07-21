#!/usr/bin/env bash
# The ONE sanctioned way to deploy StoryEngine on the VPS.
#
# Why this exists: multiple agent sessions work this box in parallel. A raw
# restart kills uvicorn's in-process background tasks — i.e. another session's
# RUNNING VIDEO BUILD — and ships whatever is on main at that second. This
# script serializes deploys behind a lock file and leaves an audit trail.
#
# Usage (on the VPS):
#   ~/projects/economy-fastforward/storyengine/scripts/vps-deploy.sh <session-name> [--with-frontend] [--force]
#
# Lock protocol (~/deploy.lock):
#   - ANY session doing prod work that must not be interrupted (a deploy, a
#     proof run, a paid pipeline run) writes its name + task + timestamp into
#     ~/deploy.lock, and removes it when done.
#   - This script REFUSES to run while the lock exists (unless --force, which
#     you use only when the lock is clearly stale — older than ~2 hours).
set -euo pipefail

LOCK="$HOME/deploy.lock"
REPO="$HOME/projects/economy-fastforward"
LOG="$HOME/deploys.log"
WHO="${1:?usage: vps-deploy.sh <session-name> [--with-frontend] [--force]}"
shift || true
ARGS="${*:-}"

if [ -f "$LOCK" ] && [[ "$ARGS" != *--force* ]]; then
  echo "DEPLOY BLOCKED — another session holds the lock:"
  cat "$LOCK"
  echo "Wait for it to finish, or rerun with --force ONLY if the lock is stale (>2h old)."
  exit 1
fi

# Active-generation guard (docs/SHEET-MODERATION-LAW.md, Operations rules):
# the backend restart below is a kill -9 — it takes every in-process
# background task down with it, including a paid picture/video run
# mid-flight. That happened for real on 2026-07-21. Refuse to deploy while
# the backend reports active work, unless --force.
HEALTH=$(curl -s --max-time 5 http://localhost:8001/api/health 2>/dev/null || true)
ACTIVE=$(printf '%s' "$HEALTH" | grep -o '"active_tasks":[0-9-]*' | sed 's/[^0-9-]*//g' || true)
if [ -n "$ACTIVE" ] && [ "$ACTIVE" -gt 0 ] && [[ "$ARGS" != *--force* ]]; then
  echo "DEPLOY BLOCKED — active-generation guard: $ACTIVE task(s) running on this box right now."
  echo "$HEALTH"
  echo "A deploy kill -9's the backend and strands any in-flight run (paid work included)."
  echo "Wait for it to finish, or rerun with --force ONLY if you accept killing active work."
  exit 1
fi

printf '%s deploying, started %s\n' "$WHO" "$(date -u +%FT%TZ)" > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

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

if [[ "$ARGS" == *--with-frontend* ]]; then
  (cd storyengine/frontend && npm run build)
  FPID=$(systemctl show -p MainPID --value storyengine-frontend.service)
  if [ -n "$FPID" ] && [ "$FPID" != "0" ]; then kill -9 "$FPID"; fi
  sleep 4
  echo "frontend: $(systemctl is-active storyengine-frontend.service)"
fi

printf '%s %s deployed %s -> %s %s\n' "$(date -u +%FT%TZ)" "$WHO" "$BEFORE" "$AFTER" "$ARGS" >> "$LOG"
echo "DONE — deployed $AFTER (log: $LOG)"
