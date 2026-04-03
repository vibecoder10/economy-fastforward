#!/usr/bin/env bash
# prd-watcher.sh — Runs every 60s via cron. Two jobs:
#   1. Spawn agents when PRD tasks become unblocked
#   2. Spawn agents when user hits errors in the browser (auto-fix)
# This is the heartbeat of the autonomous team — ensures nothing sits idle.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PRD_FILE="$PROJECT_ROOT/agents/prd.json"
PROGRESS_FILE="$PROJECT_ROOT/agents/progress.md"
AGENTS_DIR="$PROJECT_ROOT/storyengine/agents"
ACTIVITY_LOG="$PROJECT_ROOT/rubric/scaffold/data/activity-log.json"
CLAUDE_BIN="${CLAUDE_BIN:-/home/clawd/.npm-global/bin/claude}"
LOCK_FILE="/tmp/prd-watcher.lock"
ERROR_TRACK="/tmp/prd-watcher-errors-seen.txt"

# Prevent concurrent runs
if [ -f "$LOCK_FILE" ]; then
  LOCK_AGE=$(( $(date +%s) - $(stat -c %Y "$LOCK_FILE" 2>/dev/null || echo 0) ))
  [ "$LOCK_AGE" -gt 1800 ] && rm -f "$LOCK_FILE"
  [ -f "$LOCK_FILE" ] && exit 0
fi
echo $$ > "$LOCK_FILE"
trap "rm -f $LOCK_FILE" EXIT

spawn_agent() {
  local AGENT="$1"
  local REASON="$2"
  if pgrep -f "run-agent.sh.*$AGENT" > /dev/null 2>&1; then
    return  # already running
  fi
  echo "[watcher] Spawning $AGENT — $REASON"
  cd "$AGENTS_DIR" && CLAUDE_BIN="$CLAUDE_BIN" nohup bash run-agent.sh "$AGENT" > "/tmp/prd-$AGENT.log" 2>&1 &
}

# ─── Job 1: PRD unblocked tasks ───────────────────────────────────────────
if [ -f "$PRD_FILE" ] && [ -f "$PROGRESS_FILE" ]; then
  DONE_IDS=$(grep -oP 'T(\d+):.*✅' "$PROGRESS_FILE" 2>/dev/null | grep -oP 'T\d+' | sed 's/T//' | tr '\n' ',' | sed 's/,$//')

  ROLES_TO_SPAWN=$(python3 -c "
import json
prd = json.load(open('$PRD_FILE'))
done = set([int(x) for x in '$DONE_IDS'.split(',') if x])
role_map = {'backend': 'backend-dev', 'frontend': 'frontend-dev', 'qa': 'qa-engineer', 'pipeline-tester': 'pipeline-tester', 'security': 'security-auditor'}
to_spawn = set()
for t in prd.get('tasks', []):
    if t.get('status') in ('done', 'verified'): continue
    tid = t.get('id')
    if tid in done: continue
    deps = set(t.get('depends_on', []))
    if deps and not deps.issubset(done): continue
    role = t.get('role', '')
    agent = role_map.get(role, '')
    if agent: to_spawn.add(agent)
for a in to_spawn:
    print(a)
" 2>/dev/null || true)

  for AGENT in $ROLES_TO_SPAWN; do
    spawn_agent "$AGENT" "PRD tasks unblocked"
  done
fi

# ─── Job 2: User-browser errors → auto-spawn agents to fix ────────────────
if [ -f "$ACTIVITY_LOG" ]; then
  # Track which errors we've already spawned for (avoid respawning every minute)
  touch "$ERROR_TRACK"

  NEW_ERRORS=$(python3 -c "
import json
try:
    logs = json.load(open('$ACTIVITY_LOG'))
    seen = set(open('$ERROR_TRACK').read().strip().split('\n')) if open('$ERROR_TRACK').read().strip() else set()
    # Activity log is newest-first (unshift). Check first 30 entries for recent errors.
    errors = [e for e in logs[:30] if e.get('agent') == 'user-browser' and e.get('status') == 'error']
    for e in errors:
        key = e.get('task', '') + '|' + str(e.get('timestamp', ''))
        if key in seen or not key.strip(): continue
        summary = e.get('summary', '')
        task = e.get('task', '')
        if '/api/' in task:
            print('backend-dev|' + key)
        else:
            print('frontend-dev|' + key)
except: pass
" 2>/dev/null || true)

  if [ -n "$NEW_ERRORS" ]; then
    SPAWN_BACKEND=false
    SPAWN_FRONTEND=false

    while IFS= read -r line; do
      AGENT=$(echo "$line" | cut -d'|' -f1)
      KEY=$(echo "$line" | cut -d'|' -f2-)
      echo "$KEY" >> "$ERROR_TRACK"
      if [ "$AGENT" = "backend-dev" ]; then SPAWN_BACKEND=true; fi
      if [ "$AGENT" = "frontend-dev" ]; then SPAWN_FRONTEND=true; fi
    done <<< "$NEW_ERRORS"

    if [ "$SPAWN_BACKEND" = true ]; then
      spawn_agent "backend-dev" "user hit API errors"
    fi
    if [ "$SPAWN_FRONTEND" = true ]; then
      spawn_agent "frontend-dev" "user hit UI errors"
    fi
    # Always spawn pipeline-tester after fixes to verify
    if [ "$SPAWN_BACKEND" = true ] || [ "$SPAWN_FRONTEND" = true ]; then
      spawn_agent "pipeline-tester" "verify user-error fixes"
    fi
  fi

  # Clean up error tracker (keep last 200 entries)
  tail -200 "$ERROR_TRACK" > "$ERROR_TRACK.tmp" 2>/dev/null && mv "$ERROR_TRACK.tmp" "$ERROR_TRACK" || true
fi
