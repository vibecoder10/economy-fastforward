#!/bin/bash
# StoryEngine Agent Runner v3
# Features: memory, blueprints, handoffs, controls, smart tasks, Slack, completion detection
# Usage: ./run-agent.sh <agent-name>

set -e

AGENT=$1
# Auto-detect PROJECT_ROOT from script location (works on both Mac and VPS)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="${AGENT_PROJECT_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
AGENTS_DIR="$PROJECT_ROOT/storyengine/agents"
REPORTS_DIR="$AGENTS_DIR/reports"
RUBRIC_URL="${RUBRIC_URL:-http://localhost:5050}"
CLAUDE_BIN="${CLAUDE_BIN:-claude}"
SLACK_WEBHOOK="${SLACK_WEBHOOK:-}"
BRANCH="agent-dev"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
RUN_ID="$AGENT-$(date +%Y%m%d-%H%M%S)"

if [ -z "$AGENT" ]; then
  echo "Usage: ./run-agent.sh <orchestrator|backend-dev|frontend-dev|qa-engineer>"
  exit 1
fi

AGENT_FILE="$AGENTS_DIR/$AGENT.md"
if [ ! -f "$AGENT_FILE" ]; then
  echo "Error: Agent file not found: $AGENT_FILE"
  exit 1
fi

mkdir -p "$REPORTS_DIR"

# ─── Telegram Helper ────────────────────────────────────────────────────────
source "$AGENTS_DIR/notify-telegram.sh" 2>/dev/null || true

# ─── Slack Helper ────────────────────────────────────────────────────────────
# Uses Slack Bot Token API (existing pipeline bot) or webhook
notify_slack() {
  local MSG="$1"
  if [ -n "$SLACK_BOT_TOKEN" ] && [ -n "$SLACK_CHANNEL_ID" ]; then
    curl -s -X POST "https://slack.com/api/chat.postMessage" \
      -H "Authorization: Bearer $SLACK_BOT_TOKEN" \
      -H "Content-Type: application/json" \
      -d "{\"channel\": \"$SLACK_CHANNEL_ID\", \"text\": \"$MSG\"}" 2>/dev/null || true
  elif [ -n "$SLACK_WEBHOOK" ]; then
    curl -s -X POST "$SLACK_WEBHOOK" \
      -H "Content-Type: application/json" \
      -d "{\"text\": \"$MSG\"}" 2>/dev/null || true
  fi
}

AGENT_DISPLAY=$(echo "$AGENT" | sed 's/-/ /g' | sed 's/\b./\U&/g' 2>/dev/null || echo "$AGENT")

cd "$PROJECT_ROOT"

# ─── Pause Check ────────────────────────────────────────────────────────────
CONTROLS_FILE="$PROJECT_ROOT/rubric/scaffold/data/controls.json"
if [ -f "$CONTROLS_FILE" ]; then
  IS_PAUSED=$(python3 -c "
import json
try:
    data = json.load(open('$CONTROLS_FILE'))
    print('true' if '$AGENT' in data.get('paused_agents', []) else 'false')
except: print('false')
" 2>/dev/null || echo "false")

  if [ "$IS_PAUSED" = "true" ]; then
    curl -s -X POST "$RUBRIC_URL/api/agent-status" \
      -H "Content-Type: application/json" \
      -d "{\"agent\": \"$AGENT\", \"status\": \"idle\", \"task\": \"Paused by operator\"}" 2>/dev/null || true
    exit 0
  fi
fi

# ─── Branch Setup ───────────────────────────────────────────────────────────
CURRENT_BRANCH=$(git branch --show-current)
if [ "$CURRENT_BRANCH" != "$BRANCH" ]; then
  git checkout "$BRANCH" 2>/dev/null || git checkout -b "$BRANCH"
fi
git pull --rebase origin "$BRANCH" 2>/dev/null || true

# ─── Completion Check ───────────────────────────────────────────────────────
ALL_DONE=$(python3 -c "
import json
try:
    q = json.load(open('$AGENTS_DIR/task-queue.json'))
    tasks = [t for tab in q.get('tabs', []) for t in tab.get('tasks', [])]
    pending = [t for t in tasks if t.get('status') not in ('done', 'blocked')]
    unverified = [t for t in tasks if t.get('status') == 'done' and not t.get('verified')]
    if not pending and not unverified: print('COMPLETE')
    elif not pending and unverified: print('AWAITING_QA')
    else: print('WORKING')
except: print('WORKING')
" 2>/dev/null || echo "WORKING")

# Check for active PRD before declaring complete — PRD work overrides task queue
HAS_PRD_WORK="false"
if [ -f "$PROJECT_ROOT/agents/prd.json" ]; then
  _PRD_ROLE=""
  case "$AGENT" in
    backend-dev) _PRD_ROLE="backend" ;; frontend-dev) _PRD_ROLE="frontend" ;;
    qa-engineer) _PRD_ROLE="qa" ;; pipeline-tester) _PRD_ROLE="qa" ;; orchestrator) _PRD_ROLE="lead" ;;
  esac
  _PRD_PENDING=$(python3 -c "
import json
try:
    prd = json.load(open('$PROJECT_ROOT/agents/prd.json'))
    print(len([t for t in prd.get('tasks', []) if t.get('role') == '$_PRD_ROLE' and t.get('status') in ('pending', 'in_progress')]))
except: print(0)
" 2>/dev/null || echo "0")
  [ "$_PRD_PENDING" -gt 0 ] && HAS_PRD_WORK="true"
fi

if [ "$ALL_DONE" = "COMPLETE" ] && [ "$HAS_PRD_WORK" = "false" ]; then
  notify_slack ":trophy: *ALL TASKS COMPLETE.* StoryEngine build phase is done. $AGENT_DISPLAY entering standby."
  curl -s -X POST "$RUBRIC_URL/api/agent-status" \
    -H "Content-Type: application/json" \
    -d "{\"agent\": \"$AGENT\", \"status\": \"idle\", \"task\": \"All tasks complete — standby mode\"}" 2>/dev/null || true
  exit 0
fi

# ─── Report Active ──────────────────────────────────────────────────────────
curl -s -X POST "$RUBRIC_URL/api/agent-status" \
  -H "Content-Type: application/json" \
  -d "{\"agent\": \"$AGENT\", \"status\": \"active\", \"task\": \"Starting session\"}" 2>/dev/null || true

# ─── Read Inputs ────────────────────────────────────────────────────────────
AGENT_PROMPT=$(cat "$AGENT_FILE")
TASK_QUEUE=$(cat "$AGENTS_DIR/task-queue.json")

# ─── PRD Check (unified system — PRD tasks take priority over task queue) ──
PRD_SECTION=""
PRD_JSON_FILE="$PROJECT_ROOT/agents/prd.json"
if [ -f "$PRD_JSON_FILE" ]; then
  # Map agent name to PRD role
  PRD_ROLE=""
  case "$AGENT" in
    backend-dev)      PRD_ROLE="backend" ;;
    frontend-dev)     PRD_ROLE="frontend" ;;
    qa-engineer)      PRD_ROLE="qa" ;;
    pipeline-tester)  PRD_ROLE="qa" ;;
    orchestrator)     PRD_ROLE="lead" ;;
  esac

  PENDING_PRD=$(python3 -c "
import json
try:
    prd = json.load(open('$PRD_JSON_FILE'))
    tasks = [t for t in prd.get('tasks', []) if t.get('role') == '$PRD_ROLE' and t.get('status') in ('pending', 'in_progress')]
    print(len(tasks))
except: print(0)
" 2>/dev/null || echo "0")

  if [ "$PENDING_PRD" -gt 0 ]; then
    PRD_CONTENT=$(cat "$PRD_JSON_FILE")
    PRD_PROGRESS=$(cat "$PROJECT_ROOT/agents/progress.md" 2>/dev/null || echo "No progress yet.")
    PRD_SECTION="
## 🎯 ACTIVE PRD — THIS TAKES PRIORITY OVER TASK QUEUE

A PRD has been deployed via Command Center. You have **$PENDING_PRD pending tasks** assigned to your role ($PRD_ROLE).
**Work on PRD tasks FIRST before any task queue work.**

### PRD Tasks
\`\`\`json
$PRD_CONTENT
\`\`\`

### Current Progress
$PRD_PROGRESS

### How to work on PRD tasks
1. Find the next pending task for role '$PRD_ROLE' where all depends_on tasks are done/verified
2. Implement it fully
3. Run its acceptance criteria commands to verify
4. If pass: git commit, then update \`$PROJECT_ROOT/agents/progress.md\` (mark task [x], update summary counts)
5. If fail after 3 attempts: mark as blocked in progress.md with reason
6. Move to next task — do NOT stop after one task
7. When all your role's tasks are done or blocked, fall through to the regular task queue below
"
    # Update status to show PRD work
    curl -s -X POST "$RUBRIC_URL/api/agent-status" \
      -H "Content-Type: application/json" \
      -d "{\"agent\": \"$AGENT\", \"status\": \"active\", \"task\": \"PRD: $PENDING_PRD tasks pending ($PRD_ROLE)\"}" 2>/dev/null || true
  fi
fi

# Blueprint
BLUEPRINT=""
case "$AGENT" in
  backend-dev)  BLUEPRINT_FILE="$AGENTS_DIR/blueprints/backend.md" ;;
  frontend-dev) BLUEPRINT_FILE="$AGENTS_DIR/blueprints/frontend.md" ;;
  qa-engineer)  BLUEPRINT_FILE="$AGENTS_DIR/blueprints/qa.md" ;;
  orchestrator) BLUEPRINT_FILE="$AGENTS_DIR/blueprints/orchestrator.md" ;;
  *)            BLUEPRINT_FILE="" ;;
esac
if [ -n "$BLUEPRINT_FILE" ] && [ -f "$BLUEPRINT_FILE" ]; then
  BLUEPRINT=$(cat "$BLUEPRINT_FILE")
fi

# Model selection — Opus for code writers, Sonnet for reviewers/testers
MODEL_FLAG=""
case "$AGENT" in
  backend-dev)      MODEL_FLAG="--model opus" ;;
  frontend-dev)     MODEL_FLAG="--model opus" ;;
  qa-engineer)      MODEL_FLAG="--model opus" ;;
  pipeline-tester)    MODEL_FLAG="--model opus" ;;
  security-auditor)   MODEL_FLAG="--model opus" ;;
  orchestrator)
    if [ "$ORCHESTRATOR_MODE" = "grand" ]; then
      MODEL_FLAG="--model opus"
    else
      MODEL_FLAG="--model sonnet"
    fi
    ;;
esac

# Product vision (shared by ALL agents)
PRODUCT_VISION=""
VISION_FILE="$AGENTS_DIR/blueprints/product-vision.md"
if [ -f "$VISION_FILE" ]; then
  PRODUCT_VISION=$(cat "$VISION_FILE")
fi

# Orchestrator mode
ORCH_MODE="${ORCHESTRATOR_MODE:-micro}"

# Memory
MEMORY=""
MEMORY_FILE="$AGENTS_DIR/memory/$AGENT.md"
if [ -f "$MEMORY_FILE" ]; then
  MEMORY=$(cat "$MEMORY_FILE")
fi

# Handoffs
HANDOFF_NOTES=""
if [ -f "$PROJECT_ROOT/rubric/scaffold/data/handoffs.json" ]; then
  HANDOFF_NOTES=$(python3 -c "
import json
try:
    h = json.load(open('$PROJECT_ROOT/rubric/scaffold/data/handoffs.json'))
    mine = [x for x in h if x.get('to') == '$AGENT' and not x.get('read')]
    for m in mine[-3:]:
        print('### From ' + m.get('from','?') + ' (task ' + m.get('task_id','') + ')')
        print(m.get('message',''))
        if m.get('files_changed'): print('Files: ' + ', '.join(m['files_changed']))
        print()
except: pass
" 2>/dev/null || echo "")
fi

# Controls
OPERATOR_CONTROLS=""
if [ -f "$CONTROLS_FILE" ]; then
  OPERATOR_CONTROLS=$(python3 -c "
import json
try:
    c = json.load(open('$CONTROLS_FILE'))
    parts = []
    f = c.get('focus', '')
    if f: parts.append('FOCUS DIRECTIVE (top priority from operator): ' + f)
    s = c.get('skipped_tasks', [])
    if s: parts.append('SKIPPED TASKS (do NOT pick): ' + ', '.join(s))
    p = c.get('priority_overrides', {})
    if p: parts.append('PRIORITY OVERRIDES (pick first): ' + json.dumps(p))
    print('\n'.join(parts))
except: pass
" 2>/dev/null || echo "")
fi

# Operator Feedback
OPERATOR_FEEDBACK=""
if [ -f "$CONTROLS_FILE" ]; then
  OPERATOR_FEEDBACK=$(python3 -c "
import json
try:
    c = json.load(open('$CONTROLS_FILE'))
    fb = [x for x in c.get('feedback', []) if '$AGENT' not in x.get('read_by', [])]
    for f in fb[-5:]:
        print('- ' + f.get('message', ''))
except: pass
" 2>/dev/null || echo "")
fi

# ─── User-Browser Errors (HIGHEST PRIORITY — fix what the user sees broken) ─
ACTIVITY_LOG="$PROJECT_ROOT/rubric/scaffold/data/activity-log.json"
USER_ERRORS=""
if [ -f "$ACTIVITY_LOG" ]; then
  USER_ERRORS=$(python3 -c "
import json
try:
    logs = json.load(open('$ACTIVITY_LOG'))
    # Activity log is newest-first (unshift). Read from start for recent errors.
    errors = [e for e in logs[:50] if e.get('agent') == 'user-browser' and e.get('status') == 'error']
    seen = set()
    for e in errors[-20:]:
        key = e.get('task', '')
        if key not in seen:
            seen.add(key)
            print('- ' + e.get('summary', '')[:200])
except: pass
" 2>/dev/null || echo "")

  # Auto-create bug tasks from user-browser errors (only for backend/frontend agents)
  if [ -n "$USER_ERRORS" ] && { [ "$AGENT" = "backend-dev" ] || [ "$AGENT" = "frontend-dev" ]; }; then
    python3 -c "
import json, time
try:
    logs = json.load(open('$ACTIVITY_LOG'))
    tq_path = '$AGENTS_DIR/task-queue.json'
    tq = json.load(open(tq_path))
    # Activity log is newest-first (unshift). Read from start for recent errors.
    errors = [e for e in logs[:50] if e.get('agent') == 'user-browser' and e.get('status') == 'error']
    # Deduplicate
    seen_tasks = {t.get('title','') for tab in tq.get('tabs',[]) for t in tab.get('tasks',[])}
    seen_keys = set()
    new_tasks = []
    for e in errors[-10:]:
        key = e.get('task','')
        summary = e.get('summary','')
        if key in seen_keys: continue
        seen_keys.add(key)
        title = 'BUG-USER: ' + summary[:100]
        if any(title[:60] in existing for existing in seen_tasks): continue
        role = 'backend' if '/api/' in key else 'frontend'
        if ('$AGENT' == 'backend-dev' and role != 'backend') or ('$AGENT' == 'frontend-dev' and role != 'frontend'): continue
        new_tasks.append({
            'id': 'BUG-USER-' + str(int(time.time()))[-6:],
            'title': title,
            'role': '$AGENT'.replace('-dev',''),
            'status': 'pending',
            'priority': 'critical',
            'description': 'User hit this error while clicking through the website. Fix immediately.\nEndpoint: ' + key + '\nError: ' + summary
        })
    if new_tasks and tq.get('tabs'):
        tq['tabs'][0].setdefault('tasks', []).extend(new_tasks[:3])  # max 3 auto-created
        json.dump(tq, open(tq_path, 'w'), indent=2)
        print(f'Auto-created {len(new_tasks[:3])} bug tasks from user-browser errors')
except Exception as ex:
    print(f'Auto-task creation failed: {ex}')
" 2>/dev/null || true
  fi
fi

# ─── Build Prompt ───────────────────────────────────────────────────────────
# Inject orchestrator mode if applicable
ORCH_SECTION=""
if [ "$AGENT" = "orchestrator" ]; then
  RECENT_COMMITS=$(git log --since="1 hour ago" --oneline --no-merges 2>/dev/null | head -10 || echo "none")
  ORCH_SECTION="
## Orchestrator Mode: $ORCH_MODE
$(if [ "$ORCH_MODE" = "grand" ]; then echo 'Run a FULL audit. Review all tabs. Create new tasks. Write end-of-day summary to Google Doc.'; else echo 'MICRO review — quick check only. What did the agents just commit in the last hour? Is the focus directive being followed? Any stuck tasks? Keep it under 5 minutes.'; fi)

## Recent Commits (last hour)
$RECENT_COMMITS
"
fi

PROMPT="You are running as the $AGENT agent for StoryEngine."

# User errors go FIRST — highest priority
if [ -n "$USER_ERRORS" ]; then
  PROMPT="$PROMPT

## 🚨 LIVE USER ERRORS — FIX THESE FIRST (before any task queue or PRD work)
The operator just clicked through the website and hit these errors. These are REAL bugs the user is experiencing RIGHT NOW. Fix them before doing anything else.

$USER_ERRORS

After fixing user errors, continue with your normal task queue / PRD work below."
fi

PROMPT="$PROMPT

## Product Vision (THE NORTH STAR — every task must push toward this)
$PRODUCT_VISION

## Your Instructions
$AGENT_PROMPT"

if [ -n "$ORCH_SECTION" ]; then
  PROMPT="$PROMPT
$ORCH_SECTION"
fi

if [ -n "$BLUEPRINT" ]; then
  PROMPT="$PROMPT

## Codebase Blueprint
$BLUEPRINT"
fi

if [ -n "$MEMORY" ]; then
  PROMPT="$PROMPT

## Your Memory (lessons from past sessions)
$MEMORY"
fi

if [ -n "$HANDOFF_NOTES" ]; then
  PROMPT="$PROMPT

## Handoff Notes (from other agents)
$HANDOFF_NOTES"
fi

if [ -n "$PRD_SECTION" ]; then
  PROMPT="$PROMPT
$PRD_SECTION"
fi

PROMPT="$PROMPT

## Current Task Queue
$TASK_QUEUE"

# Operator directives go LAST so they override task queue decisions
if [ -n "$OPERATOR_CONTROLS" ]; then
  PROMPT="$PROMPT

## ⚠️ OPERATOR OVERRIDE (this overrides the task queue above)
$OPERATOR_CONTROLS
If the focus directive conflicts with the task queue, FOLLOW THE FOCUS DIRECTIVE. Drop whatever task you were going to pick and work on what the operator says instead."
fi

if [ -n "$OPERATOR_FEEDBACK" ]; then
  PROMPT="$PROMPT

## 🔴 OPERATOR MESSAGES (read these BEFORE picking a task)
These are direct messages from the human operator. Address them FIRST, before any task queue work:
$OPERATOR_FEEDBACK"
fi

PROMPT="$PROMPT

## Important Rules
- You are on the '$BRANCH' branch.
- Always git pull --rebase before starting work.
- Always git add specific files, commit with a descriptive message, and push when done.
- Only work on ONE task per session. Do it well.
- All timestamps must be UTC ISO-8601 (e.g. $TIMESTAMP).
- When marking a task in_progress, set started_at and assigned_to. When done, set completed_at.
- After completing, POST a handoff to $RUBRIC_URL/api/handoffs if the next related task is for a different agent.
- If you learned something useful, append ONE LINE to storyengine/agents/memory/$AGENT.md (max 50 entries, prune old ones).

## Output Format (MANDATORY)
At the VERY END of your response, write these TWO sections:

SUMMARY: [One sentence, plain English, for a non-technical person]

DETAIL:
- [What you did, in simple terms]
- [Why you did it]
- [What changed for the user]
- [What the next agent should work on]

Begin work now. Pick your next task and execute it."

# ─── Invoke Claude ──────────────────────────────────────────────────────────
# Write prompt to temp file then pipe via stdin to avoid "Argument list too long" (ARG_MAX)
PROMPT_FILE=$(mktemp /tmp/agent-prompt-XXXXXX.txt)
printf '%s' "$PROMPT" > "$PROMPT_FILE"
set +e
OUTPUT=$($CLAUDE_BIN -p $MODEL_FLAG --dangerously-skip-permissions < "$PROMPT_FILE" 2>&1)
CLAUDE_EXIT=$?
set -e
rm -f "$PROMPT_FILE"

# ─── Save Report ────────────────────────────────────────────────────────────
REPORT_FILE="$REPORTS_DIR/$RUN_ID.md"
cat > "$REPORT_FILE" << REPORTEOF
# Agent Run: $AGENT
**Date:** $TIMESTAMP
**Run ID:** $RUN_ID

---

$OUTPUT
REPORTEOF

echo "Report saved: $REPORT_FILE"

# ─── Handle Failure ─────────────────────────────────────────────────────────
if [ $CLAUDE_EXIT -ne 0 ]; then
  ERROR_MSG="Agent crashed (exit code $CLAUDE_EXIT)"
  curl -s -X POST "$RUBRIC_URL/api/activity-log" \
    -H "Content-Type: application/json" \
    -d "{\"agent\": \"$AGENT\", \"task\": \"\", \"summary\": $(echo "$ERROR_MSG" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip()))' 2>/dev/null || echo "\"$ERROR_MSG\""), \"status\": \"error\", \"detail_file\": \"$RUN_ID.md\"}" 2>/dev/null || true
  curl -s -X POST "$RUBRIC_URL/api/agent-status" \
    -H "Content-Type: application/json" \
    -d "{\"agent\": \"$AGENT\", \"status\": \"idle\", \"task\": \"$ERROR_MSG\"}" 2>/dev/null || true
  notify_slack ":x: *$AGENT_DISPLAY* crashed: $ERROR_MSG"
  notify_telegram "❌ *${AGENT_DISPLAY}* crashed: ${ERROR_MSG}"
  exit 1
fi

# ─── Extract Results ────────────────────────────────────────────────────────
TASK_LINE=$(echo "$OUTPUT" | grep -oE 'T[0-9]+-[0-9]+' | head -1 || echo "")
SUMMARY_LINE=$(echo "$OUTPUT" | grep "^SUMMARY:" | tail -1 | sed 's/^SUMMARY: *//' || echo "")
DETAIL_LINES=$(echo "$OUTPUT" | sed -n '/^DETAIL:/,/^$/p' | grep "^-" || echo "")

if [ -z "$SUMMARY_LINE" ]; then
  SUMMARY_LINE=$(git log --oneline -1 2>/dev/null | cut -d' ' -f2- || echo "Session completed")
fi

# ─── Post to Activity Feed ──────────────────────────────────────────────────
DETAIL_JSON=$(echo "$DETAIL_LINES" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip()))' 2>/dev/null || echo "\"\"")
SUMMARY_JSON=$(echo "$SUMMARY_LINE" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip()))' 2>/dev/null || echo "\"$SUMMARY_LINE\"")

curl -s -X POST "$RUBRIC_URL/api/activity-log" \
  -H "Content-Type: application/json" \
  -d "{\"agent\": \"$AGENT\", \"task\": \"$TASK_LINE\", \"summary\": $SUMMARY_JSON, \"detail\": $DETAIL_JSON, \"detail_file\": \"$RUN_ID.md\", \"status\": \"completed\"}" 2>/dev/null || true

# ─── Mark Feedback as Read ─────────────────────────────────────────────────
if [ -f "$CONTROLS_FILE" ]; then
  python3 -c "
import json
try:
    c = json.load(open('$CONTROLS_FILE'))
    changed = False
    for fb in c.get('feedback', []):
        if '$AGENT' not in fb.get('read_by', []):
            fb.setdefault('read_by', []).append('$AGENT')
            changed = True
    if changed:
        json.dump(c, open('$CONTROLS_FILE', 'w'), indent=2)
except: pass
" 2>/dev/null || true
fi

# ─── Upload Screenshots to Google Doc (QA + Pipeline Tester only) ───────────
if [ "$AGENT" = "qa-engineer" ] || [ "$AGENT" = "pipeline-tester" ]; then
  echo "Uploading screenshots to Google Doc..."
  python3 "$AGENTS_DIR/update_visual_report.py" "$TASK_LINE" "$SUMMARY_LINE" 2>&1 || true
fi

# ─── Slack Notification ─────────────────────────────────────────────────────
notify_slack ":white_check_mark: *$AGENT_DISPLAY* completed $TASK_LINE: $SUMMARY_LINE"

# ─── Telegram: Task Completed ──────────────────────────────────────────────
notify_telegram "✅ *${AGENT_DISPLAY}* finished: ${SUMMARY_LINE}"

# ─── Telegram: Boss Message (if agent included one) ───────────────────────
BOSS_MSG=$(echo "$OUTPUT" | grep "^MESSAGE_BOSS:" | head -1 | sed 's/^MESSAGE_BOSS: *//' || echo "")
if [ -n "$BOSS_MSG" ]; then
  BOSS_MSG_ESC=$(echo "$BOSS_MSG" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip()))' 2>/dev/null || echo "\"$BOSS_MSG\"")
  notify_telegram "📩 *${AGENT_DISPLAY}* says:
${BOSS_MSG}

_Reply to respond — they'll see it next cycle_"
fi

# ─── Telegram: Proposal (if agent included one) ───────────────────────────
PROPOSAL_JSON=$(echo "$OUTPUT" | sed -n '/^PROPOSAL_JSON:/,/^END_PROPOSAL$/p' | grep -v '^PROPOSAL_JSON:\|^END_PROPOSAL$' | tr -d '\n' || echo "")
if [ -n "$PROPOSAL_JSON" ]; then
  PROP_RESP=$(curl -s -X POST "$RUBRIC_URL/api/proposals" \
    -H "Content-Type: application/json" \
    -d "$PROPOSAL_JSON" 2>/dev/null || echo "")
  PROP_TITLE=$(echo "$PROPOSAL_JSON" | python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('title','New idea'))" 2>/dev/null || echo "New idea")
  PROP_ID=$(echo "$PROP_RESP" | python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('id',''))" 2>/dev/null || echo "")
  notify_telegram "💡 *${AGENT_DISPLAY}* proposes:
${PROP_TITLE}

_Reply /approve ${PROP_ID} or /reject ${PROP_ID}_"
fi

# ─── Restart Servers After Code Changes ────────────────────────────────────
# Agents commit code but running servers serve old code. Restart so testers see changes.
if [ -n "$TASK_LINE" ] || [ -n "$SUMMARY_LINE" ]; then
  CHANGED_FILES=$(git diff --name-only HEAD~1 2>/dev/null || echo "")
  if echo "$CHANGED_FILES" | grep -q "storyengine/backend/"; then
    echo "Backend files changed — restarting uvicorn..."
    pkill -f "uvicorn main:app.*8001" 2>/dev/null || true
    sleep 1
    cd "$PROJECT_ROOT/storyengine/backend" && nohup ./venv/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8001 > /tmp/storyengine-backend.log 2>&1 &
    echo "Backend restarted on port 8001"
    cd "$PROJECT_ROOT"
  fi
  if echo "$CHANGED_FILES" | grep -q "storyengine/frontend/"; then
    echo "Frontend files changed — rebuilding and restarting..."
    cd "$PROJECT_ROOT/storyengine/frontend"
    npm run build > /tmp/storyengine-frontend-build.log 2>&1 || echo "Frontend build failed"
    # Kill old next server and start fresh
    pkill -f "next.*3001" 2>/dev/null || true
    sleep 2
    fuser -k 3001/tcp 2>/dev/null || true
    nohup npx next start -p 3001 > /tmp/storyengine-frontend.log 2>&1 &
    echo "Frontend rebuilt and restarted on port 3001"
    cd "$PROJECT_ROOT"
  fi
fi

# ─── Regression Check (run Playwright tests if they exist) ─────────────────
PLAYWRIGHT_DIR="$PROJECT_ROOT/storyengine/frontend/tests"
if [ -d "$PLAYWRIGHT_DIR" ] && ls "$PLAYWRIGHT_DIR"/*.spec.ts 1>/dev/null 2>&1; then
  echo "Running regression tests..."
  cd "$PROJECT_ROOT/storyengine/frontend"
  REGRESSION_RESULT=$(npx playwright test --reporter=line 2>&1 | tail -5)
  REGRESSION_EXIT=$?
  cd "$PROJECT_ROOT"
  if [ $REGRESSION_EXIT -ne 0 ]; then
    echo "⚠️  REGRESSION DETECTED:"
    echo "$REGRESSION_RESULT"
    curl -s -X POST "$RUBRIC_URL/api/activity-log" \
      -H "Content-Type: application/json" \
      -d "{\"agent\": \"$AGENT\", \"task\": \"regression\", \"summary\": \"REGRESSION: Playwright tests failed after $AGENT commit\", \"status\": \"error\"}" 2>/dev/null || true
  else
    echo "✅ Regression tests passed"
  fi
fi

# ─── PRD: Auto-Spawn Unblocked Agents ──────────────────────────────────────
# After completing PRD work, check if other roles became unblocked and spawn them
if [ -f "$PROJECT_ROOT/agents/prd.json" ]; then
  python3 -c "
import json, subprocess, os
try:
    prd = json.load(open('$PROJECT_ROOT/agents/prd.json'))
    tasks = prd.get('tasks', [])
    done_ids = {t['id'] for t in tasks if t.get('status') in ('done', 'verified')}
    role_to_agent = {'backend': 'backend-dev', 'frontend': 'frontend-dev', 'qa': 'qa-engineer', 'pipeline-tester': 'pipeline-tester'}
    spawned = set()
    for t in tasks:
        if t.get('status') != 'pending': continue
        deps = set(t.get('depends_on', []))
        if deps and not deps.issubset(done_ids): continue
        role = t.get('role', '')
        agent = role_to_agent.get(role, '')
        if agent and agent != '$AGENT' and agent not in spawned:
            spawned.add(agent)
            print(f'Spawning {agent} (unblocked)')
            subprocess.Popen(
                ['bash', 'run-agent.sh', agent],
                cwd='$AGENTS_DIR',
                env={**os.environ, 'CLAUDE_BIN': '$CLAUDE_BIN'},
                stdout=open(f'/tmp/prd-{agent}.log', 'w'),
                stderr=subprocess.STDOUT
            )
except Exception as e:
    print(f'Auto-spawn check failed: {e}')
" 2>/dev/null || true
fi

# ─── Health Check (MANDATORY — no agent leaves the site broken) ────────────
echo "Running health check..."
FRONTEND_OK=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:3001/ 2>/dev/null || echo "000")
BACKEND_OK=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8001/api/videos 2>/dev/null || echo "000")

if [ "$FRONTEND_OK" != "200" ]; then
  echo "⚠️  FRONTEND DOWN (HTTP $FRONTEND_OK) — restarting..."
  pkill -f 'next.*3001' 2>/dev/null || true
  sleep 2
  fuser -k 3001/tcp 2>/dev/null || true
  sleep 1
  cd "$PROJECT_ROOT/storyengine/frontend"
  npm run build > /tmp/storyengine-frontend-build.log 2>&1 || echo "Build failed"
  nohup npx next start -p 3001 > /tmp/storyengine-frontend.log 2>&1 &
  echo "Frontend restarted"
  cd "$PROJECT_ROOT"
  # Notify
  curl -s -X POST "$RUBRIC_URL/api/activity-log" \
    -H "Content-Type: application/json" \
    -d "{\"agent\": \"$AGENT\", \"task\": \"health-check\", \"summary\": \"Frontend was DOWN — auto-restarted\", \"status\": \"completed\"}" 2>/dev/null || true
fi

if [ "$BACKEND_OK" = "000" ]; then
  echo "⚠️  BACKEND DOWN — restarting..."
  pkill -f 'uvicorn.*8001' 2>/dev/null || true
  sleep 1
  cd "$PROJECT_ROOT/storyengine/backend"
  nohup ./venv/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8001 > /tmp/storyengine-backend.log 2>&1 &
  echo "Backend restarted"
  cd "$PROJECT_ROOT"
  curl -s -X POST "$RUBRIC_URL/api/activity-log" \
    -H "Content-Type: application/json" \
    -d "{\"agent\": \"$AGENT\", \"task\": \"health-check\", \"summary\": \"Backend was DOWN — auto-restarted\", \"status\": \"completed\"}" 2>/dev/null || true
fi

echo "Health check: frontend=$FRONTEND_OK backend=$BACKEND_OK"

# ─── Report Idle ────────────────────────────────────────────────────────────
curl -s -X POST "$RUBRIC_URL/api/agent-status" \
  -H "Content-Type: application/json" \
  -d "{\"agent\": \"$AGENT\", \"status\": \"idle\", \"task\": $SUMMARY_JSON}" 2>/dev/null || true

# ─── Smart Task Generation ──────────────────────────────────────────────────
# If a task was completed, check if follow-up tasks should be auto-created
if [ -n "$TASK_LINE" ]; then
  echo "Checking for follow-up tasks..."
  TASK_QUEUE_FRESH=$(cat "$AGENTS_DIR/task-queue.json")
  TASK_GEN=$($CLAUDE_BIN -p "$(cat <<TASKEOF
You just completed task $TASK_LINE for StoryEngine as the $AGENT agent.
Summary: $SUMMARY_LINE

Current task queue:
$TASK_QUEUE_FRESH

Check if this completed task creates follow-up work for another agent:
- backend-dev built an endpoint → frontend-dev needs to wire it (type + API call + component)
- frontend-dev wired a component → qa-engineer needs to verify it
- qa-engineer found issues → fix task for the responsible agent

If follow-ups needed: edit storyengine/agents/task-queue.json to add 1-2 new tasks to the right tab. Include role, description, depends_on referencing $TASK_LINE. Commit and push.

If NO follow-ups needed: just say "No follow-ups needed" and exit.

CRITICAL: Do NOT invent new features. Only create tasks directly caused by the completed work. Max 2 tasks.
TASKEOF
)" --model sonnet --dangerously-skip-permissions 2>&1 || true)
  echo "Task gen result: $(echo "$TASK_GEN" | tail -3)"
fi
