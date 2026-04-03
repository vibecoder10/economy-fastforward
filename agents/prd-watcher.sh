#!/usr/bin/env bash
# prd-watcher.sh — Runs every 60s, spawns agents when their PRD tasks become unblocked
# Called by cron or run in a loop. Ensures no task sits idle because its agent already exited.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PRD_FILE="$PROJECT_ROOT/agents/prd.json"
PROGRESS_FILE="$PROJECT_ROOT/agents/progress.md"
AGENTS_DIR="$PROJECT_ROOT/storyengine/agents"
CLAUDE_BIN="${CLAUDE_BIN:-/home/clawd/.npm-global/bin/claude}"
LOCK_FILE="/tmp/prd-watcher.lock"

# Exit if no active PRD
[ -f "$PRD_FILE" ] || exit 0
[ -f "$PROGRESS_FILE" ] || exit 0

# Prevent concurrent runs
if [ -f "$LOCK_FILE" ]; then
  LOCK_AGE=$(( $(date +%s) - $(stat -c %Y "$LOCK_FILE" 2>/dev/null || echo 0) ))
  # Stale lock (>30 min) — remove it
  [ "$LOCK_AGE" -gt 1800 ] && rm -f "$LOCK_FILE"
  [ -f "$LOCK_FILE" ] && exit 0
fi
echo $$ > "$LOCK_FILE"
trap "rm -f $LOCK_FILE" EXIT

# Parse done task IDs from progress.md
DONE_IDS=$(grep -oP 'T(\d+):.*✅' "$PROGRESS_FILE" | grep -oP 'T\d+' | sed 's/T//' | tr '\n' ',' | sed 's/,$//')

# Find roles with unblocked pending tasks
ROLES_TO_SPAWN=$(python3 -c "
import json
prd = json.load(open('$PRD_FILE'))
done = set([int(x) for x in '$DONE_IDS'.split(',') if x])
role_map = {'backend': 'backend-dev', 'frontend': 'frontend-dev', 'qa': 'qa-engineer', 'pipeline-tester': 'pipeline-tester'}
to_spawn = set()
for t in prd.get('tasks', []):
    if t.get('status') in ('done', 'verified'): continue
    tid = t.get('id')
    if tid in done: continue  # already done in progress.md
    deps = set(t.get('depends_on', []))
    if deps and not deps.issubset(done): continue  # still blocked
    role = t.get('role', '')
    agent = role_map.get(role, '')
    if agent: to_spawn.add(agent)
for a in to_spawn:
    print(a)
" 2>/dev/null)

[ -z "$ROLES_TO_SPAWN" ] && exit 0

# Check which agents are already running
for AGENT in $ROLES_TO_SPAWN; do
  if pgrep -f "run-agent.sh.*$AGENT" > /dev/null 2>&1; then
    continue  # already running
  fi
  echo "[prd-watcher] Spawning $AGENT (unblocked tasks found)"
  cd "$AGENTS_DIR" && CLAUDE_BIN="$CLAUDE_BIN" nohup bash run-agent.sh "$AGENT" > "/tmp/prd-$AGENT.log" 2>&1 &
done
