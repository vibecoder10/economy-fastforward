#!/usr/bin/env bash
# prd-loader.sh — PRD Queue Orchestrator
#
# Reads prd-queue.json to determine the active PRD, then converts its pending
# tasks into prd.json so the swarm / agents can execute them.
#
# Usage:
#   ./agents/prd-loader.sh              # Load active PRD into prd.json
#   ./agents/prd-loader.sh --status     # Print current PRD queue status
#   ./agents/prd-loader.sh --advance    # Mark active PRD complete, move to next
#   ./agents/prd-loader.sh --what-next  # Print what agents should do right now
#
# Called automatically by prd-watcher.sh when prd.json is stale.

set -euo pipefail

AGENTS_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$AGENTS_DIR/.." && pwd)"
QUEUE_FILE="$AGENTS_DIR/prd-queue.json"
PRD_JSON="$AGENTS_DIR/prd.json"
PROGRESS_FILE="$AGENTS_DIR/progress.md"
RUBRIC_URL="${RUBRIC_URL:-http://localhost:5050}"

# ─── Parse args ───────────────────────────────────────────────────────────────
MODE="load"
case "${1:-}" in
  --status)    MODE="status" ;;
  --advance)   MODE="advance" ;;
  --what-next) MODE="what-next" ;;
  --help|-h)
    echo "Usage: $0 [--status | --advance | --what-next]"
    echo ""
    echo "  (no args)    Load active PRD tasks into prd.json for agent execution"
    echo "  --status     Print PRD queue overview (which PRD, which tasks remain)"
    echo "  --advance    Mark active PRD done and activate the next PRD in queue"
    echo "  --what-next  Print exact task(s) agents should work on right now"
    exit 0
    ;;
esac

# ─── Helpers ─────────────────────────────────────────────────────────────────
die() { echo "ERROR: $*" >&2; exit 1; }

queue_get() {
  python3 -c "
import json, sys
q = json.load(open('$QUEUE_FILE'))
print(json.dumps(q.get('$1', ''), ensure_ascii=False))
" 2>/dev/null || echo "null"
}

active_prd_data() {
  python3 -c "
import json
q = json.load(open('$QUEUE_FILE'))
active_id = q.get('active_prd')
for p in q.get('prds', []):
    if p['id'] == active_id:
        print(json.dumps(p, indent=2))
        break
" 2>/dev/null || echo "null"
}

post_activity() {
  local SUMMARY="$1"
  local STATUS="${2:-info}"
  curl -s -X POST "$RUBRIC_URL/api/activity-log" \
    -H "Content-Type: application/json" \
    -d "{\"agent\":\"prd-loader\",\"task\":\"queue\",\"summary\":\"$SUMMARY\",\"status\":\"$STATUS\"}" 2>/dev/null || true
}

# ─── STATUS ──────────────────────────────────────────────────────────────────
if [ "$MODE" = "status" ]; then
  python3 -c "
import json
q = json.load(open('$QUEUE_FILE'))
active_id = q.get('active_prd')
print('=== PRD Queue Status ===')
print(f'Updated: {q.get(\"updated\",\"?\")}')
print('')
for p in q.get('prds', []):
    marker = '→ ACTIVE' if p['id'] == active_id else ('✓ ' if p.get('status') == 'complete' else '  ')
    done  = p.get('tasks_done', '?')
    total = p.get('tasks_total', '?')
    print(f'{marker} PRD {p[\"id\"]}: {p[\"title\"]}')
    print(f'   Status: {p.get(\"status\",\"?\")} | Tasks: {done}/{total}')
    if p.get('status') == 'active':
        print('   Remaining tasks:')
        for t in p.get('tasks', []):
            if t.get('status') == 'pending':
                deps = ', '.join(t.get('depends_on', [])) or 'none'
                print(f'     [ ] {t[\"id\"]}: {t[\"title\"]} ({t[\"role\"]}) deps={deps}')
    print('')
nxt = q.get('next_prd')
if nxt:
    print(f'Next PRD after active completes: PRD {nxt}')
else:
    print('No next PRD configured — queue ends after active PRD.')
"
  exit 0
fi

# ─── WHAT-NEXT ───────────────────────────────────────────────────────────────
if [ "$MODE" = "what-next" ]; then
  python3 -c "
import json
q = json.load(open('$QUEUE_FILE'))
active_id = q.get('active_prd')
active = next((p for p in q.get('prds', []) if p['id'] == active_id), None)
if not active:
    print('ERROR: No active PRD found in queue.')
    exit(1)

print(f'=== What to Do Next (PRD {active[\"id\"]}: {active[\"title\"]}) ===')
print('')

tasks = active.get('tasks', [])
done_ids = {t['id'] for t in tasks if t.get('status') in ('done','verified')}
pending = [t for t in tasks if t.get('status') == 'pending']

if not pending:
    print('All tasks are done. Run: ./agents/prd-loader.sh --advance')
    exit(0)

unblocked = [t for t in pending if set(t.get('depends_on', [])).issubset(done_ids)]
blocked   = [t for t in pending if t not in unblocked]

if unblocked:
    print('UNBLOCKED (ready to assign):')
    for t in unblocked:
        print(f'  {t[\"id\"]}: [{t[\"role\"]}] {t[\"title\"]}')
    print('')

if blocked:
    print('BLOCKED (waiting on dependencies):')
    for t in blocked:
        remaining_deps = set(t.get('depends_on',[])) - done_ids
        print(f'  {t[\"id\"]}: [{t[\"role\"]}] {t[\"title\"]}')
        print(f'       waiting on: {remaining_deps}')
    print('')

print(f'Overall: {len(done_ids)}/{len(tasks)} done, {len(unblocked)} unblocked, {len(blocked)} blocked')
"
  exit 0
fi

# ─── ADVANCE ─────────────────────────────────────────────────────────────────
if [ "$MODE" = "advance" ]; then
  python3 -c "
import json, sys
from datetime import date

q = json.load(open('$QUEUE_FILE'))
active_id = q.get('active_prd')
prds = q.get('prds', [])

active = next((p for p in prds if p['id'] == active_id), None)
if not active:
    print('ERROR: No active PRD.'); sys.exit(1)

# Check all tasks are done
pending = [t for t in active.get('tasks', []) if t.get('status') == 'pending']
if pending:
    print(f'WARNING: {len(pending)} tasks still pending. Use --what-next to see them.')
    print('Force advance? Edit prd-queue.json manually and re-run.')
    sys.exit(1)

# Mark active as complete
active['status'] = 'complete'
active['completed'] = str(date.today())

# Find next PRD
nxt = q.get('next_prd')
if nxt:
    next_prd = next((p for p in prds if p['id'] == nxt), None)
    if next_prd:
        next_prd['status'] = 'active'
        next_prd['started'] = str(date.today())
        q['active_prd'] = nxt
        q['next_prd'] = None  # clear; human sets next one
        print(f'Advanced: PRD {active_id} complete → PRD {nxt} now active.')
    else:
        print(f'ERROR: next_prd={nxt} not found in prds array.')
        sys.exit(1)
else:
    q['active_prd'] = None
    print(f'PRD {active_id} marked complete. No next PRD — queue finished!')

q['updated'] = str(date.today())
json.dump(q, open('$QUEUE_FILE', 'w'), indent=2)
"

  post_activity "PRD queue advanced" "completed"
  echo ""
  echo "Queue updated. Run --status to see new state."
  exit 0
fi

# ─── LOAD (default) ──────────────────────────────────────────────────────────
# Converts active PRD's pending tasks into prd.json for agent execution.
# Agents then read prd.json as normal — they don't need to know about PRDs.

python3 -c "
import json, sys
from datetime import date

q = json.load(open('$QUEUE_FILE'))
active_id = q.get('active_prd')
if not active_id:
    print('No active PRD. Queue may be complete.')
    sys.exit(0)

active = next((p for p in q.get('prds', []) if p['id'] == active_id), None)
if not active:
    print(f'ERROR: PRD {active_id} not found in queue.'); sys.exit(1)

tasks = active.get('tasks', [])
done_ids = {t['id'] for t in tasks if t.get('status') in ('done', 'verified')}

role_map = {
    'backend':  'backend',
    'frontend': 'frontend',
    'qa':       'qa',
    'security': 'pipeline-tester'
}

prd_tasks = []
for i, t in enumerate(tasks, start=1):
    # Convert task ID (e.g. 'T11') → int (11)
    raw_id = t.get('id', str(i))
    int_id = int(raw_id.lstrip('T')) if isinstance(raw_id, str) and raw_id.startswith('T') else i

    # Map depends_on T-strings to ints
    deps = []
    for d in t.get('depends_on', []):
        try:
            deps.append(int(d.lstrip('T')))
        except:
            pass

    status_map = {'done': 'done', 'verified': 'verified', 'pending': 'pending', 'blocked': 'blocked'}
    status = status_map.get(t.get('status', 'pending'), 'pending')

    prd_tasks.append({
        'id': int_id,
        'title': t.get('title', ''),
        'role': role_map.get(t.get('role', 'backend'), 'backend'),
        'status': status,
        'depends_on': deps,
        'acceptance_criteria': t.get('acceptance_criteria', [
            f'# PRD {active_id} T{int_id} — see agents/prds/prd-{active_id}-*.md for full criteria'
        ]),
        'files_hint': t.get('files_hint', []),
        'prd_source': f'PRD {active_id}: {active[\"title\"]}',
        'prd_file': active.get('file', '')
    })

out = {
    'title': active['title'],
    'created': str(date.today()),
    'source': f'prd-queue:prd-{active_id}',
    'prd_id': active_id,
    'prd_file': active.get('file', ''),
    'total_tasks': len(prd_tasks),
    'tasks_done': len(done_ids),
    'tasks_remaining': len([t for t in prd_tasks if t['status'] == 'pending']),
    'tasks': prd_tasks
}

json.dump(out, open('$PRD_JSON', 'w'), indent=2)
print(f'Loaded PRD {active_id} into prd.json: {len(prd_tasks)} tasks ({len(done_ids)} done, {out[\"tasks_remaining\"]} remaining)')
"

echo ""
echo "Run './agents/prd-loader.sh --what-next' to see unblocked tasks."
echo "Run './agents/swarm.sh \"complete remaining PRD 4 tasks\"' to execute."

post_activity "PRD queue loaded into prd.json" "completed"
