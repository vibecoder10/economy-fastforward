#!/usr/bin/env bash
# prd-watcher.sh — Autonomous PRD lifecycle + agent heartbeat.
# Runs every 60s via cron. Jobs (in order):
#
#   0. PRD LIFECYCLE — self-feeding loop (runs first every tick):
#      a. No active PRD?        → activate first pending PRD in queue
#      b. Queue < 2 pending?    → auto-generate next PRD from tasks/roadmap.md
#      c. Active PRD 100% done? → auto-advance queue + load next PRD
#      d. prd.json missing?     → auto-load active PRD into prd.json
#
#   1. Spawn agents for any unblocked PRD tasks
#   2. Spawn agents when user hits errors in the browser (auto-fix)
#   3. Spawn agents for unread handoffs
#
# Turn this on once. It feeds itself forever.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
QUEUE_DIR="$PROJECT_ROOT/agents"
PRD_FILE="$QUEUE_DIR/prd.json"
QUEUE_FILE="$QUEUE_DIR/prd-queue.json"
AGENTS_DIR="$PROJECT_ROOT/storyengine/agents"
ACTIVITY_LOG="$PROJECT_ROOT/rubric/scaffold/data/activity-log.json"
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude 2>/dev/null || echo "$HOME/.npm-global/bin/claude")}"
LOCK_FILE="/tmp/prd-watcher.lock"
ERROR_TRACK="/tmp/prd-watcher-errors-seen.txt"

# ─── Prevent concurrent runs ─────────────────────────────────────────────────
if [ -f "$LOCK_FILE" ]; then
  LOCK_AGE=$(( $(date +%s) - $(stat -f %m "$LOCK_FILE" 2>/dev/null || stat -c %Y "$LOCK_FILE" 2>/dev/null || echo 0) ))
  [ "$LOCK_AGE" -gt 1800 ] && rm -f "$LOCK_FILE"
  [ -f "$LOCK_FILE" ] && exit 0
fi
echo $$ > "$LOCK_FILE"
trap "rm -f $LOCK_FILE" EXIT

# ─── Master Kill Switch ───────────────────────────────────────────────────────
CONTROLS_FILE="$PROJECT_ROOT/rubric/scaffold/data/controls.json"
if [ -f "$CONTROLS_FILE" ]; then
  TEAM_ENABLED=$(python3 -c "
import json
try:
    data = json.load(open('$CONTROLS_FILE'))
    print('true' if data.get('team_enabled', True) else 'false')
except: print('true')
" 2>/dev/null || echo "true")
  if [ "$TEAM_ENABLED" = "false" ]; then
    exit 0
  fi
fi

RUBRIC_URL="${RUBRIC_URL:-http://localhost:5050}"

# ─── Helpers ─────────────────────────────────────────────────────────────────
post_activity() {
  local AGENT="${1:-watcher}"
  local TASK="${2:-lifecycle}"
  local SUMMARY="$3"
  local STATUS="${4:-info}"
  curl -s -X POST "$RUBRIC_URL/api/activity-log" \
    -H "Content-Type: application/json" \
    -d "{\"agent\":\"$AGENT\",\"task\":\"$TASK\",\"summary\":\"$(echo "$SUMMARY" | sed 's/"/\\"/g' | head -c 200)\",\"status\":\"$STATUS\"}" 2>/dev/null || true
}

spawn_agent() {
  local AGENT="$1"
  local REASON="$2"
  if pgrep -f "run-agent.sh.*$AGENT" > /dev/null 2>&1; then
    return  # already running
  fi
  echo "[watcher] Spawning $AGENT — $REASON"
  post_activity "$AGENT" "spawn" "Spawning $AGENT: $REASON" "starting"
  cd "$AGENTS_DIR" && CLAUDE_BIN="$CLAUDE_BIN" nohup bash run-agent.sh "$AGENT" > "/tmp/prd-$AGENT.log" 2>&1 &
}

# ═══════════════════════════════════════════════════════════════════════════════
# JOB 0: PRD LIFECYCLE — The autonomous self-feeding loop
# ═══════════════════════════════════════════════════════════════════════════════
if [ -f "$QUEUE_FILE" ]; then

  # ── 0a: Bootstrap — if no active PRD, activate the first pending one ─────────
  ACTIVE_PRD=$(python3 -c "
import json
q = json.load(open('$QUEUE_FILE'))
a = q.get('active_prd')
print(a if a is not None else 'none')
" 2>/dev/null || echo "none")

  if [ "$ACTIVE_PRD" = "none" ] || [ "$ACTIVE_PRD" = "null" ]; then
    echo "[watcher] No active PRD — looking for pending PRD to activate..."
    FIRST_PENDING=$(python3 -c "
import json
q = json.load(open('$QUEUE_FILE'))
p = next((x for x in q.get('prds', []) if x.get('status') == 'pending'), None)
print(p['id'] if p else 'none')
" 2>/dev/null || echo "none")

    if [ "$FIRST_PENDING" != "none" ]; then
      echo "[watcher] Activating PRD $FIRST_PENDING..."
      python3 -c "
import json
from datetime import date
q = json.load(open('$QUEUE_FILE'))
for p in q.get('prds', []):
    if p['id'] == $FIRST_PENDING:
        p['status'] = 'active'
        p['started'] = str(date.today())
        q['active_prd'] = $FIRST_PENDING
        break
q['updated'] = str(date.today())
json.dump(q, open('$QUEUE_FILE', 'w'), indent=2)
" 2>/dev/null
      post_activity "watcher" "lifecycle" "Activated PRD $FIRST_PENDING" "started"
      ACTIVE_PRD="$FIRST_PENDING"
    else
      echo "[watcher] No pending PRDs — will generate one from roadmap."
    fi
  fi

  # ── 0b: Auto-generate next PRD if queue is running low (< 2 pending) ─────────
  PENDING_PRDS=$(python3 -c "
import json
q = json.load(open('$QUEUE_FILE'))
print(sum(1 for p in q.get('prds', []) if p.get('status') == 'pending'))
" 2>/dev/null || echo "99")

  if [ "$PENDING_PRDS" -lt 2 ]; then
    GEN_LOCK="/tmp/prd-generator.lock"
    if [ ! -f "$GEN_LOCK" ]; then
      echo "[watcher] Queue low ($PENDING_PRDS pending PRDs). Generating next PRD from roadmap..."
      post_activity "watcher" "generate" "Queue low — generating next PRD from roadmap" "started"
      touch "$GEN_LOCK"
      # Background — generation takes ~30s, don't block the watcher tick
      (
        bash "$QUEUE_DIR/prd-generator.sh" > /tmp/prd-generator.log 2>&1
        rm -f "$GEN_LOCK"
      ) &
    else
      echo "[watcher] PRD generation already running (lock exists). Skipping."
    fi
  fi

  # ── 0c: Detect PRD completion → auto-advance and load next ───────────────────
  if [ -f "$PRD_FILE" ] && [ "$ACTIVE_PRD" != "none" ] && [ "$ACTIVE_PRD" != "null" ]; then
    PRD_STATUS=$(python3 -c "
import json
try:
    prd = json.load(open('$PRD_FILE'))
    tasks = prd.get('tasks', [])
    if not tasks:
        print('empty')
    else:
        pending = [t for t in tasks if t.get('status') not in ('done', 'verified')]
        print('complete' if not pending else f'pending:{len(pending)}')
except:
    print('error')
" 2>/dev/null || echo "error")

    if [ "$PRD_STATUS" = "complete" ]; then
      echo "[watcher] ✅ PRD $ACTIVE_PRD is 100% done. Auto-advancing queue..."
      post_activity "watcher" "advance" "PRD $ACTIVE_PRD complete — advancing to next" "completed"

      ADVANCE_OUT=$(bash "$QUEUE_DIR/prd-loader.sh" --advance 2>/dev/null || echo "ERROR")
      echo "[watcher] $ADVANCE_OUT"

      if ! echo "$ADVANCE_OUT" | grep -qiE "ERROR|still pending"; then
        # Successfully advanced — load the new active PRD into prd.json
        bash "$QUEUE_DIR/prd-loader.sh" > /tmp/prd-loader.log 2>&1 || true
        post_activity "watcher" "load" "Loaded next PRD into prd.json after advance" "completed"
      fi

    elif [ "$PRD_STATUS" = "empty" ] || [ "$PRD_STATUS" = "error" ]; then
      # prd.json is corrupt or empty — reload from queue
      echo "[watcher] prd.json is empty/corrupt. Reloading..."
      bash "$QUEUE_DIR/prd-loader.sh" > /tmp/prd-loader.log 2>&1 || true
    fi
    # "pending:N" → normal operation, nothing to do
  fi

  # ── 0d: prd.json missing with an active PRD → auto-load ──────────────────────
  if [ ! -f "$PRD_FILE" ] && [ "$ACTIVE_PRD" != "none" ] && [ "$ACTIVE_PRD" != "null" ]; then
    echo "[watcher] prd.json not found but PRD $ACTIVE_PRD is active. Loading..."
    bash "$QUEUE_DIR/prd-loader.sh" > /tmp/prd-loader.log 2>&1 || true
    post_activity "watcher" "load" "Auto-loaded PRD $ACTIVE_PRD into prd.json" "started"
  fi

fi  # end QUEUE_FILE block

# ═══════════════════════════════════════════════════════════════════════════════
# JOB 1: Spawn agents for unblocked PRD tasks
# ═══════════════════════════════════════════════════════════════════════════════
if [ -f "$PRD_FILE" ]; then
  ROLES_TO_SPAWN=$(python3 -c "
import json
prd = json.load(open('$PRD_FILE'))
done_ids = set(t.get('id') for t in prd.get('tasks', []) if t.get('status') in ('done', 'verified'))
role_map = {
    'backend':  'backend-dev',
    'frontend': 'frontend-dev',
    'qa':       'qa-engineer',
    'pipeline-tester': 'pipeline-tester',
    'security': 'security-auditor'
}
to_spawn = set()
for t in prd.get('tasks', []):
    if t.get('status') in ('done', 'verified'): continue
    deps = set(t.get('depends_on', []))
    if deps and not deps.issubset(done_ids): continue
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

# ═══════════════════════════════════════════════════════════════════════════════
# JOB 2: User-browser errors → auto-spawn agents to fix
# ═══════════════════════════════════════════════════════════════════════════════
if [ -f "$ACTIVITY_LOG" ]; then
  touch "$ERROR_TRACK"

  NEW_ERRORS=$(python3 -c "
import json
try:
    logs = json.load(open('$ACTIVITY_LOG'))
    seen = set(open('$ERROR_TRACK').read().strip().split('\n')) if open('$ERROR_TRACK').read().strip() else set()
    errors = [e for e in logs[:30] if e.get('agent') == 'user-browser' and e.get('status') == 'error']
    for e in errors:
        key = e.get('task', '') + '|' + str(e.get('timestamp', ''))
        if key in seen or not key.strip(): continue
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
    if [ "$SPAWN_BACKEND" = true ] || [ "$SPAWN_FRONTEND" = true ]; then
      spawn_agent "pipeline-tester" "verify user-error fixes"
    fi
  fi

  tail -200 "$ERROR_TRACK" > "$ERROR_TRACK.tmp" 2>/dev/null && mv "$ERROR_TRACK.tmp" "$ERROR_TRACK" || true
fi

# ═══════════════════════════════════════════════════════════════════════════════
# JOB 3: Unaddressed handoffs → spawn receiving agent
# ═══════════════════════════════════════════════════════════════════════════════
HANDOFFS_FILE="$PROJECT_ROOT/rubric/scaffold/data/handoffs.json"
if [ -f "$HANDOFFS_FILE" ]; then
  HANDOFF_AGENTS=$(python3 -c "
import json
try:
    handoffs = json.load(open('$HANDOFFS_FILE'))
    for h in handoffs[-10:]:
        to_agent = h.get('to', '')
        hid = h.get('id', '')
        read_by = h.get('read_by', [])
        is_read = h.get('read', False)
        if not to_agent or is_read: continue
        if 'watcher' in read_by: continue
        from_agent = h.get('from', 'unknown')
        print(to_agent + '|' + hid + '|' + from_agent)
except: pass
" 2>/dev/null || true)

  if [ -n "$HANDOFF_AGENTS" ]; then
    while IFS= read -r line; do
      AGENT=$(echo "$line" | cut -d'|' -f1)
      HID=$(echo "$line" | cut -d'|' -f2)
      FROM=$(echo "$line" | cut -d'|' -f3)
      curl -s -X POST "$RUBRIC_URL/api/handoffs/$HID/read" \
        -H "Content-Type: application/json" \
        -d '{"agent":"watcher"}' 2>/dev/null || true
      post_activity "$AGENT" "handoff" "Spawning for handoff from $FROM" "starting"
      spawn_agent "$AGENT" "unaddressed handoff from $FROM"
    done <<< "$HANDOFF_AGENTS"
  fi
fi
