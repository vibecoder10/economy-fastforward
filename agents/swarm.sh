#!/usr/bin/env bash
# swarm.sh — Directive-driven agent swarm
#
# Usage:
#   ./agents/swarm.sh "Finish the drones video. Stuck on storyboard visuals."
#   ./agents/swarm.sh --url /pipeline/VIDEO_ID "Fix the extraction pipeline"
#   ./agents/swarm.sh --dry-run "What's broken on the storyboard tab?"
#   ./agents/swarm.sh --skip-observe "Add nano banana upscale to extraction"
#
# Phases: OBSERVE → PLAN → EXECUTE → VERIFY
# The Pipeline Tester is the entry point, not the exit.

set -euo pipefail

# ─── Parse Arguments ──────────────────────────────────────────────────────────
URL_HINT=""
DRY_RUN=false
SKIP_OBSERVE=false
DIRECTIVE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --url)       URL_HINT="$2"; shift 2 ;;
    --dry-run)   DRY_RUN=true; shift ;;
    --skip-observe) SKIP_OBSERVE=true; shift ;;
    *)           DIRECTIVE="$1"; shift ;;
  esac
done

if [ -z "$DIRECTIVE" ]; then
  echo "Usage: ./agents/swarm.sh [--url /path] [--dry-run] [--skip-observe] \"directive\""
  echo ""
  echo "Examples:"
  echo "  ./agents/swarm.sh \"Finish the drones video. Stuck on storyboard visuals.\""
  echo "  ./agents/swarm.sh --url /pipeline/abc123 \"Fix extraction pipeline\""
  echo "  ./agents/swarm.sh --dry-run \"What's broken on the visuals tab?\""
  exit 1
fi

# ─── Setup ────────────────────────────────────────────────────────────────────
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AGENTS_DIR="$PROJECT_ROOT/agents"
SE_AGENTS="$PROJECT_ROOT/storyengine/agents"
RUBRIC_URL="${RUBRIC_URL:-http://localhost:5050}"
FLOWS_URL="${FLOWS_URL:-http://localhost:5050}"
CLAUDE_BIN="${CLAUDE_BIN:-claude}"
SWARM_ID="swarm-$(date +%Y%m%d-%H%M%S)"
SWARM_STATE="$PROJECT_ROOT/rubric/scaffold/data/swarm-state.json"
MAX_RETRIES=2
MAX_CONCURRENT=2

echo "==========================================="
echo "  SWARM: $SWARM_ID"
echo "  Directive: $DIRECTIVE"
echo "  Dry run: $DRY_RUN"
echo "  Skip observe: $SKIP_OBSERVE"
echo "==========================================="

# ─── Helpers ──────────────────────────────────────────────────────────────────
source "$SE_AGENTS/notify-telegram.sh" 2>/dev/null || true

write_swarm_state() {
  local PHASE="$1"
  local STATUS="$2"
  mkdir -p "$(dirname "$SWARM_STATE")"
  python3 -c "
import json, os
state = {}
if os.path.exists('$SWARM_STATE'):
    try: state = json.load(open('$SWARM_STATE'))
    except: pass
state['id'] = '$SWARM_ID'
state['directive'] = '''$DIRECTIVE'''
state['phase'] = '$PHASE'
state['phase_status'] = '$STATUS'
state.setdefault('started_at', '$(date -u +%Y-%m-%dT%H:%M:%SZ)')
state.setdefault('phases', {})
state['phases'].setdefault('$PHASE', {})
state['phases']['$PHASE']['status'] = '$STATUS'
json.dump(state, open('$SWARM_STATE', 'w'), indent=2)
" 2>/dev/null || true
}

post_activity() {
  local TASK="$1"
  local SUMMARY="$2"
  local STATUS="$3"
  curl -s -X POST "$RUBRIC_URL/api/activity-log" \
    -H "Content-Type: application/json" \
    -d "{\"agent\":\"swarm\",\"task\":\"$TASK\",\"summary\":\"$(echo "$SUMMARY" | sed 's/"/\\"/g' | head -c 200)\",\"status\":\"$STATUS\"}" 2>/dev/null || true
}

post_workflow_event() {
  local EVENT="$1"
  local DATA="$2"
  case "$EVENT" in
    workflow:start)
      curl -s -X POST "$FLOWS_URL/api/workflow-events" \
        -H "Content-Type: application/json" \
        -d "{\"event\":\"workflow:start\",\"workflowId\":\"directive-swarm\"}" 2>/dev/null || true
      ;;
    step:start)
      curl -s -X POST "$FLOWS_URL/api/workflow-events" \
        -H "Content-Type: application/json" \
        -d "{\"event\":\"step:start\",\"stepIndex\":$DATA}" 2>/dev/null || true
      ;;
    step:complete)
      curl -s -X POST "$FLOWS_URL/api/workflow-events" \
        -H "Content-Type: application/json" \
        -d "{\"event\":\"step:complete\",\"stepIndex\":$DATA}" 2>/dev/null || true
      ;;
    step:error)
      curl -s -X POST "$FLOWS_URL/api/workflow-events" \
        -H "Content-Type: application/json" \
        -d "{\"event\":\"step:error\",\"stepIndex\":$DATA}" 2>/dev/null || true
      ;;
    step:warn)
      curl -s -X POST "$FLOWS_URL/api/workflow-events" \
        -H "Content-Type: application/json" \
        -d "{\"event\":\"step:warn\",\"stepIndex\":$DATA}" 2>/dev/null || true
      ;;
    workflow:complete)
      curl -s -X POST "$FLOWS_URL/api/workflow-events" \
        -H "Content-Type: application/json" \
        -d "{\"event\":\"workflow:complete\",\"workflowId\":\"directive-swarm\"}" 2>/dev/null || true
      ;;
  esac
}

set_focus() {
  local MSG="$1"
  local CONTROLS="$PROJECT_ROOT/rubric/scaffold/data/controls.json"
  if [ -f "$CONTROLS" ]; then
    python3 -c "
import json
data = json.load(open('$CONTROLS'))
data['focus'] = '''$MSG'''
json.dump(data, open('$CONTROLS', 'w'), indent=2)
" 2>/dev/null || true
  fi
}

count_tasks() {
  local STATUS="$1"
  python3 -c "
import json
try:
    prd = json.load(open('$AGENTS_DIR/prd.json'))
    count = sum(1 for t in prd.get('tasks', []) if t.get('status') == '$STATUS')
    print(count)
except: print(0)
" 2>/dev/null || echo "0"
}

get_unblocked_roles() {
  python3 -c "
import json
try:
    prd = json.load(open('$AGENTS_DIR/prd.json'))
    done_ids = set()
    for t in prd.get('tasks', []):
        if t.get('status') in ('done', 'verified'):
            done_ids.add(t.get('id'))
    role_map = {'backend': 'backend-dev', 'frontend': 'frontend-dev', 'qa': 'qa-engineer', 'pipeline-tester': 'pipeline-tester'}
    to_spawn = set()
    for t in prd.get('tasks', []):
        if t.get('status') != 'pending': continue
        deps = set(t.get('depends_on', []))
        if deps and not deps.issubset(done_ids): continue
        role = t.get('role', '')
        agent = role_map.get(role, '')
        if agent: to_spawn.add(agent)
    for a in to_spawn:
        print(a)
except: pass
" 2>/dev/null || true
}

spawn_agent() {
  local AGENT="$1"
  local REASON="$2"
  # Don't spawn if already running
  if pgrep -f "run-agent.sh.*$AGENT" > /dev/null 2>&1; then
    echo "  [swarm] $AGENT already running, skipping"
    return
  fi
  # Respect concurrency limit
  local RUNNING
  RUNNING=$(pgrep -f "run-agent.sh" 2>/dev/null | wc -l | tr -d ' ')
  if [ "$RUNNING" -ge "$MAX_CONCURRENT" ]; then
    echo "  [swarm] Max concurrent ($MAX_CONCURRENT) reached, deferring $AGENT"
    return
  fi
  echo "  [swarm] Spawning $AGENT — $REASON"
  post_activity "execute" "Spawning $AGENT: $REASON" "started"
  cd "$SE_AGENTS" && CLAUDE_BIN="$CLAUDE_BIN" nohup bash run-agent.sh "$AGENT" > "/tmp/swarm-$AGENT.log" 2>&1 &
}

# ─── Lock: prevent concurrent swarms ─────────────────────────────────────────
LOCK_FILE="/tmp/swarm.lock"
if [ -f "$LOCK_FILE" ]; then
  LOCK_AGE=$(( $(date +%s) - $(stat -f %m "$LOCK_FILE" 2>/dev/null || stat -c %Y "$LOCK_FILE" 2>/dev/null || echo 0) ))
  if [ "$LOCK_AGE" -gt 7200 ]; then
    echo "  [swarm] Stale lock (${LOCK_AGE}s old), removing"
    rm -f "$LOCK_FILE"
  else
    echo "ERROR: Another swarm is running (lock age: ${LOCK_AGE}s). Wait or remove $LOCK_FILE."
    exit 1
  fi
fi
echo $$ > "$LOCK_FILE"
trap "rm -f $LOCK_FILE; set_focus ''" EXIT

# ─── Set focus directive so cron agents defer ─────────────────────────────────
set_focus "SWARM ACTIVE: $DIRECTIVE"

# ─── Initialize ──────────────────────────────────────────────────────────────
write_swarm_state "init" "starting"
post_activity "$SWARM_ID" "SWARM STARTED: $DIRECTIVE" "started"
post_workflow_event "workflow:start" ""
notify_telegram "Swarm started: $DIRECTIVE" 2>/dev/null || true

cd "$PROJECT_ROOT"

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 1: OBSERVE
# ═══════════════════════════════════════════════════════════════════════════════
if [ "$SKIP_OBSERVE" = true ]; then
  echo ""
  echo "=== PHASE 1: OBSERVE (skipped — using directive as observations) ==="
  cat > "$AGENTS_DIR/swarm-observations.md" <<OBSEOF
# Swarm Observations

## Directive
"$DIRECTIVE"

## Observed
$(date -u +%Y-%m-%dT%H:%M:%SZ)

## Current State
(Observation skipped by operator. Directive used as problem statement.)

## Problems Found
(See directive above — operator described the problem directly.)

## What Works
(Unknown — observation skipped.)
OBSEOF
  post_workflow_event "step:start" 0
  post_workflow_event "step:complete" 0
else
  echo ""
  echo "=== PHASE 1: OBSERVE ==="
  post_workflow_event "step:start" 0
  write_swarm_state "observe" "running"

  OBSERVER_ROLE=$(cat "$AGENTS_DIR/roles/observer.md")

  URL_SECTION=""
  if [ -n "$URL_HINT" ]; then
    URL_SECTION="## URL Hint
Navigate directly to: $URL_HINT"
  fi

  OBSERVE_PROMPT="$OBSERVER_ROLE

## Human Directive
$DIRECTIVE

$URL_SECTION

## Output
Write your observations to: $AGENTS_DIR/swarm-observations.md
Save screenshots to: $SE_AGENTS/screenshots/

Begin observing now."

  OBSERVE_FILE=$(mktemp /tmp/swarm-observe-XXXXXX.txt)
  printf '%s' "$OBSERVE_PROMPT" > "$OBSERVE_FILE"

  echo "  Launching Pipeline Tester (observe mode)..."
  set +e
  $CLAUDE_BIN -p --model opus --dangerously-skip-permissions < "$OBSERVE_FILE" > /tmp/swarm-observe-output.log 2>&1
  OBSERVE_EXIT=$?
  set -e
  rm -f "$OBSERVE_FILE"

  if [ ! -f "$AGENTS_DIR/swarm-observations.md" ]; then
    echo "ERROR: Observer did not produce swarm-observations.md (exit code: $OBSERVE_EXIT)"
    post_workflow_event "step:error" 0
    post_activity "observe" "OBSERVE FAILED: No observations produced" "error"
    write_swarm_state "observe" "failed"
    exit 1
  fi

  FINDINGS=$(grep -c "^\d\." "$AGENTS_DIR/swarm-observations.md" 2>/dev/null || echo "?")
  echo "  Observations complete. Findings: $FINDINGS"
  post_workflow_event "step:complete" 0
  write_swarm_state "observe" "done"
  post_activity "observe" "OBSERVE complete: $FINDINGS findings" "completed"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 2: PLAN
# ═══════════════════════════════════════════════════════════════════════════════
echo ""
echo "=== PHASE 2: PLAN ==="
post_workflow_event "step:start" 1
write_swarm_state "plan" "running"

SYNTHESIZER_ROLE=$(cat "$AGENTS_DIR/roles/synthesizer.md")
OBSERVATIONS=$(cat "$AGENTS_DIR/swarm-observations.md")

# Gather codebase context for the synthesizer
BACKEND_ROUTES=""
if [ -d "$PROJECT_ROOT/storyengine/backend/routes" ]; then
  BACKEND_ROUTES=$(grep -r "router\.\(get\|post\|put\|delete\|patch\)" "$PROJECT_ROOT/storyengine/backend/routes/" --include="*.py" 2>/dev/null | head -50 || true)
fi

FRONTEND_API=""
if [ -f "$PROJECT_ROOT/storyengine/frontend/src/lib/api.ts" ]; then
  FRONTEND_API=$(head -100 "$PROJECT_ROOT/storyengine/frontend/src/lib/api.ts" 2>/dev/null || true)
fi

PLAN_PROMPT="$SYNTHESIZER_ROLE

## Human Directive
$DIRECTIVE

## Live System Observations (from Pipeline Tester)
$OBSERVATIONS

## Existing Backend Routes (grep summary)
\`\`\`
$BACKEND_ROUTES
\`\`\`

## Frontend API Client (first 100 lines)
\`\`\`typescript
$FRONTEND_API
\`\`\`

## Output Files
Write prd.json to: $AGENTS_DIR/prd.json
Write progress.md to: $AGENTS_DIR/progress.md

## Important
- Use the EXACT prd.json schema from your instructions
- Every acceptance_criteria must be a runnable shell command
- Stay tight — only tasks for the directive
- Commit both files after writing them

Begin synthesizing now."

PLAN_FILE=$(mktemp /tmp/swarm-plan-XXXXXX.txt)
printf '%s' "$PLAN_PROMPT" > "$PLAN_FILE"

echo "  Launching Orchestrator (synthesize mode)..."
set +e
$CLAUDE_BIN -p --model opus --dangerously-skip-permissions < "$PLAN_FILE" > /tmp/swarm-plan-output.log 2>&1
PLAN_EXIT=$?
set -e
rm -f "$PLAN_FILE"

if [ ! -f "$AGENTS_DIR/prd.json" ]; then
  echo "ERROR: Synthesizer did not produce prd.json (exit code: $PLAN_EXIT)"
  post_workflow_event "step:error" 1
  post_activity "plan" "PLAN FAILED: No prd.json produced" "error"
  write_swarm_state "plan" "failed"
  exit 1
fi

TASK_COUNT=$(python3 -c "import json; print(len(json.load(open('$AGENTS_DIR/prd.json')).get('tasks',[])))" 2>/dev/null || echo "?")
echo "  Plan complete. Tasks created: $TASK_COUNT"
post_workflow_event "step:complete" 1
write_swarm_state "plan" "done"
post_activity "plan" "PLAN complete: $TASK_COUNT tasks created" "completed"

# ─── Dry run stops here ──────────────────────────────────────────────────────
if [ "$DRY_RUN" = true ]; then
  echo ""
  echo "=== DRY RUN COMPLETE ==="
  echo "  Observations: $AGENTS_DIR/swarm-observations.md"
  echo "  PRD: $AGENTS_DIR/prd.json"
  echo "  Progress: $AGENTS_DIR/progress.md"
  post_workflow_event "workflow:complete" ""
  write_swarm_state "done" "dry-run-complete"
  post_activity "$SWARM_ID" "SWARM DRY RUN COMPLETE: $TASK_COUNT tasks planned" "completed"
  notify_telegram "Swarm dry-run done: $TASK_COUNT tasks planned for: $DIRECTIVE" 2>/dev/null || true
  exit 0
fi

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 3: EXECUTE
# ═══════════════════════════════════════════════════════════════════════════════
RETRY_COUNT=0

run_execute_phase() {
  echo ""
  echo "=== PHASE 3: EXECUTE (attempt $((RETRY_COUNT + 1))) ==="
  post_workflow_event "step:start" 2
  write_swarm_state "execute" "running"

  # Spawn initial agents
  local ROLES
  ROLES=$(get_unblocked_roles)
  if [ -z "$ROLES" ]; then
    echo "  No unblocked tasks found. Skipping execute."
    post_workflow_event "step:complete" 2
    return
  fi

  for ROLE in $ROLES; do
    spawn_agent "$ROLE" "Swarm execute: unblocked tasks"
  done

  # Poll for completion
  echo "  Polling for task completion..."
  local POLL_COUNT=0
  local MAX_POLLS=120  # 120 * 60s = 2 hours max
  while [ $POLL_COUNT -lt $MAX_POLLS ]; do
    sleep 60

    local PENDING
    PENDING=$(count_tasks "pending")
    local IN_PROGRESS
    IN_PROGRESS=$(count_tasks "in_progress")
    local DONE
    DONE=$(count_tasks "done")
    local BLOCKED
    BLOCKED=$(count_tasks "blocked")
    local REMAINING=$((PENDING + IN_PROGRESS))

    echo "  [poll $POLL_COUNT] done=$DONE pending=$PENDING in_progress=$IN_PROGRESS blocked=$BLOCKED"

    # All tasks done or blocked
    if [ "$REMAINING" -eq 0 ]; then
      echo "  All tasks complete or blocked."
      break
    fi

    # Spawn newly unblocked agents
    local NEW_ROLES
    NEW_ROLES=$(get_unblocked_roles)
    for ROLE in $NEW_ROLES; do
      spawn_agent "$ROLE" "Swarm execute: dependency cleared"
    done

    POLL_COUNT=$((POLL_COUNT + 1))
  done

  # Wait for any remaining agent processes to finish
  echo "  Waiting for running agents to finish..."
  local WAIT_COUNT=0
  while pgrep -f "run-agent.sh" > /dev/null 2>&1 && [ $WAIT_COUNT -lt 30 ]; do
    sleep 10
    WAIT_COUNT=$((WAIT_COUNT + 1))
  done

  post_workflow_event "step:complete" 2
  write_swarm_state "execute" "done"
  post_activity "execute" "EXECUTE complete: $(count_tasks 'done') tasks done, $(count_tasks 'blocked') blocked" "completed"
}

run_execute_phase

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 4: VERIFY
# ═══════════════════════════════════════════════════════════════════════════════
run_verify_phase() {
  echo ""
  echo "=== PHASE 4: VERIFY ==="
  post_workflow_event "step:start" 3
  write_swarm_state "verify" "running"

  VERIFIER_ROLE=$(cat "$AGENTS_DIR/roles/verifier.md")
  PRD_CONTENT=$(cat "$AGENTS_DIR/prd.json")
  PROGRESS_CONTENT=$(cat "$AGENTS_DIR/progress.md")

  VERIFY_PROMPT="$VERIFIER_ROLE

## Human Directive
$DIRECTIVE

## PRD (tasks + acceptance criteria)
\`\`\`json
$PRD_CONTENT
\`\`\`

## Current Progress
$PROGRESS_CONTENT

## Output
Write your verification report to: $AGENTS_DIR/swarm-verification.md
If any criteria fail, add bug tasks to: $AGENTS_DIR/prd.json
Save screenshots to: $SE_AGENTS/screenshots/

Begin verification now."

  VERIFY_FILE=$(mktemp /tmp/swarm-verify-XXXXXX.txt)
  printf '%s' "$VERIFY_PROMPT" > "$VERIFY_FILE"

  echo "  Launching Pipeline Tester (verify mode)..."
  set +e
  $CLAUDE_BIN -p --model opus --dangerously-skip-permissions < "$VERIFY_FILE" > /tmp/swarm-verify-output.log 2>&1
  VERIFY_EXIT=$?
  set -e
  rm -f "$VERIFY_FILE"

  if [ ! -f "$AGENTS_DIR/swarm-verification.md" ]; then
    echo "  WARNING: Verifier did not produce swarm-verification.md"
    post_workflow_event "step:warn" 3
    return 1
  fi

  # Count failures
  local FAILURES
  FAILURES=$(grep -ci "FAIL" "$AGENTS_DIR/swarm-verification.md" 2>/dev/null || echo "0")
  local PASSES
  PASSES=$(grep -ci "PASS" "$AGENTS_DIR/swarm-verification.md" 2>/dev/null || echo "0")

  echo "  Verification: $PASSES pass, $FAILURES fail"
  post_activity "verify" "VERIFY: $PASSES pass, $FAILURES fail" "completed"

  if [ "$FAILURES" -gt 0 ]; then
    post_workflow_event "step:warn" 3
    write_swarm_state "verify" "failures"
    return 1
  else
    post_workflow_event "step:complete" 3
    write_swarm_state "verify" "done"
    return 0
  fi
}

# Verify → retry loop
set +e
run_verify_phase
VERIFY_RESULT=$?
set -e

while [ "$VERIFY_RESULT" -ne 0 ] && [ "$RETRY_COUNT" -lt "$MAX_RETRIES" ]; do
  RETRY_COUNT=$((RETRY_COUNT + 1))
  echo ""
  echo "=== RETRY $RETRY_COUNT/$MAX_RETRIES ==="
  post_activity "$SWARM_ID" "Retrying: $RETRY_COUNT/$MAX_RETRIES" "started"

  # Re-execute (verifier should have filed bug tasks)
  run_execute_phase

  # Re-verify
  set +e
  run_verify_phase
  VERIFY_RESULT=$?
  set -e
done

# ═══════════════════════════════════════════════════════════════════════════════
# COMPLETE
# ═══════════════════════════════════════════════════════════════════════════════
echo ""
echo "==========================================="

FINAL_DONE=$(count_tasks "done")
FINAL_BLOCKED=$(count_tasks "blocked")
FINAL_STATUS="complete"

if [ "$VERIFY_RESULT" -ne 0 ]; then
  FINAL_STATUS="partial"
  echo "  SWARM PARTIAL: $FINAL_DONE tasks done, $FINAL_BLOCKED blocked, verification failures remain"
  post_workflow_event "step:error" 3
else
  echo "  SWARM COMPLETE: $FINAL_DONE tasks done, all verified"
fi

post_workflow_event "workflow:complete" ""
write_swarm_state "done" "$FINAL_STATUS"

SUMMARY="Swarm $FINAL_STATUS: $FINAL_DONE done, $FINAL_BLOCKED blocked. Directive: $DIRECTIVE"
post_activity "$SWARM_ID" "$SUMMARY" "completed"
notify_telegram "$SUMMARY" 2>/dev/null || true

echo ""
echo "  Results:"
echo "    Observations: $AGENTS_DIR/swarm-observations.md"
echo "    PRD: $AGENTS_DIR/prd.json"
echo "    Progress: $AGENTS_DIR/progress.md"
echo "    Verification: $AGENTS_DIR/swarm-verification.md"
echo "    Swarm state: $SWARM_STATE"
echo "==========================================="
