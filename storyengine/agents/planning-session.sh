#!/bin/bash
# Daily Planning Session — creates today's work plan
# Runs at 6:00 AM, before the morning briefing at 7:00 AM

PROJECT_ROOT="${AGENT_PROJECT_ROOT:-/home/clawd/projects/economy-fastforward}"
AGENTS_DIR="$PROJECT_ROOT/storyengine/agents"
RUBRIC_DATA="$PROJECT_ROOT/rubric/scaffold/data"
RUBRIC_URL="http://localhost:5050"
CLAUDE_BIN="${CLAUDE_BIN:-claude}"
TODAY=$(date +%Y-%m-%d)

echo "=== Planning Session: $TODAY ==="

# Report active status
curl -s -X POST "$RUBRIC_URL/api/agent-status" \
  -H "Content-Type: application/json" \
  -d '{"agent": "orchestrator", "status": "active", "task": "Running daily planning session"}' 2>/dev/null || true

# Gather inputs
TASK_QUEUE=$(cat "$AGENTS_DIR/task-queue.json" 2>/dev/null || echo "{}")
AGENT_SKILLS=$(cat "$RUBRIC_DATA/agent-skills.json" 2>/dev/null || echo "{}")
RETRO=$(cat "$RUBRIC_DATA/retro.json" 2>/dev/null || echo "{}")
ACTIVITY_LOG=$(cat "$RUBRIC_DATA/activity-log.json" 2>/dev/null || echo "[]")
CONTROLS=$(cat "$RUBRIC_DATA/controls.json" 2>/dev/null || echo "{}")

# Summarize task queue
QUEUE_SUMMARY=$(echo "$TASK_QUEUE" | python3 -c "
import json, sys
q = json.load(sys.stdin)
current = q.get('current_tab', 1)
tabs = q.get('tabs', [])
for t in tabs:
    tasks = t.get('tasks', [])
    pending = [x for x in tasks if x.get('status') == 'pending']
    done = [x for x in tasks if x.get('status') == 'done']
    blocked = [x for x in tasks if x.get('status') == 'blocked']
    active = '>>> ' if t.get('id') == current else '    '
    print(f\"{active}Tab {t.get('id')}: {t.get('name')} — {len(done)}/{len(tasks)} done, {len(pending)} pending, {len(blocked)} blocked ({t.get('status','')})\")
    if t.get('id') == current:
        for task in pending[:8]:
            role = task.get('role', '?')
            depends = task.get('depends_on', '')
            dep_str = f' (depends on {depends})' if depends else ''
            print(f'         - [{role}] {task.get(\"title\", \"?\")}{dep_str}')
" 2>/dev/null || echo "Could not parse queue")

# Summarize skills
SKILLS_SUMMARY=$(echo "$AGENT_SKILLS" | python3 -c "
import json, sys
data = json.load(sys.stdin)
agents = data.get('agents', {})
for name, s in agents.items():
    print(f\"  {name}: Lv.{s.get('level',1)} {s.get('title','Novice')} — {s.get('tasks_completed',0)} done, {s.get('qa_pass_rate',0)*100:.0f}% QA, {s.get('avg_completion_minutes',0)}m avg\")
" 2>/dev/null || echo "No skills data")

# Build prompt
PLAN_PROMPT="You are the team lead for a 5-person dev team. Create today's work plan.

## Today's Date
$TODAY

## Current Task Queue
$QUEUE_SUMMARY

## Agent Performance
$SKILLS_SUMMARY

## Yesterday's Retro
$(echo "$RETRO" | python3 -c "
import json, sys
r = json.load(sys.stdin)
print('Summary:', r.get('summary', 'No retro'))
print('Patterns:', json.dumps(r.get('recurring_patterns', [])))
print('Agent notes:', json.dumps(r.get('agent_notes', {}), indent=2))
" 2>/dev/null || echo "No retro data")

## Current Focus Directive
$(echo "$CONTROLS" | python3 -c "import json,sys; print(json.load(sys.stdin).get('focus','None set'))" 2>/dev/null || echo "None set")

## Recent Activity (last 10 events)
$(echo "$ACTIVITY_LOG" | python3 -c "
import json, sys
log = json.load(sys.stdin)[:10]
for e in log:
    status_icon = 'done' if e.get('status') == 'completed' else 'FAIL'
    print(f\"  [{status_icon}] {e.get('agent','?')}: {e.get('summary','?')}\")
" 2>/dev/null || echo "No recent activity")

## Instructions
Create a daily plan. Output ONLY valid JSON (no markdown fences) with this structure:
{
  \"date\": \"$TODAY\",
  \"summary\": \"2-3 sentences describing what the team should accomplish today. Plain English, no jargon.\",
  \"assignments\": {
    \"backend-dev\": {\"tasks\": [\"Task description in plain English\"], \"reason\": \"Why this agent gets these tasks\"},
    \"frontend-dev\": {\"tasks\": [\"Task description\"], \"reason\": \"Why\"},
    \"qa-engineer\": {\"tasks\": [\"Task description\"], \"reason\": \"Why\"},
    \"pipeline-tester\": {\"tasks\": [\"Task description\"], \"reason\": \"Why\"},
    \"orchestrator\": {\"tasks\": [\"Task description\"], \"reason\": \"Why\"}
  },
  \"blockers\": [\"Plain English description of anything blocking progress\"],
  \"decisions_needed\": [\"Questions for the boss, if any\"],
  \"estimated_completion\": \"When the current tab/milestone should be done\"
}

Rules:
- Assign tasks based on agent skill levels and past performance
- Put the most important/blocking tasks first
- If an agent has nothing to do, say 'Stand by — waiting for [X] to finish'
- Keep all text in plain English — the boss is non-technical
- Max 3 tasks per agent per day
- Flag dependencies clearly in blockers"

echo "Creating daily plan..."
PLAN_OUTPUT=$($CLAUDE_BIN --print -p "$PLAN_PROMPT" --model sonnet 2>&1)

if [ -z "$PLAN_OUTPUT" ]; then
  echo "ERROR: Claude returned empty output"
  exit 1
fi

# Write daily-plan.json
python3 -c "
import json, sys

raw = sys.stdin.read().strip()
fence = chr(96) * 3
if raw.startswith(fence):
    raw = chr(10).join(raw.split(chr(10))[1:])
if raw.endswith(fence):
    raw = chr(10).join(raw.split(chr(10))[:-1])
raw = raw.strip()

try:
    plan = json.loads(raw)
except json.JSONDecodeError as e:
    print(f'ERROR: Could not parse plan: {e}', file=sys.stderr)
    plan = {'date': '$TODAY', 'summary': 'Planning failed', 'assignments': {}, 'blockers': ['Plan generation failed'], 'decisions_needed': [], 'estimated_completion': 'Unknown'}

json.dump(plan, open('$RUBRIC_DATA/daily-plan.json', 'w'), indent=2)
print('Daily plan written to $RUBRIC_DATA/daily-plan.json')
" <<< "$PLAN_OUTPUT"

# Update priority overrides in controls.json based on assignments
python3 -c "
import json

plan_path = '$RUBRIC_DATA/daily-plan.json'
controls_path = '$RUBRIC_DATA/controls.json'

try:
    plan = json.load(open(plan_path))
except:
    exit(0)

try:
    controls = json.load(open(controls_path))
except:
    controls = {'paused_agents': [], 'skipped_tasks': [], 'priority_overrides': {}}

# Read task queue to map plan task descriptions to task IDs
try:
    queue = json.load(open('$AGENTS_DIR/task-queue.json'))
    current_tab = queue.get('current_tab', 1)
    current_tasks = []
    for tab in queue.get('tabs', []):
        if tab.get('id') == current_tab:
            current_tasks = tab.get('tasks', [])
            break
except:
    current_tasks = []

# For each agent assignment, find matching pending tasks and set priority
priority = {}
for agent_id, assignment in plan.get('assignments', {}).items():
    agent_pending = [t for t in current_tasks if t.get('role', '') in agent_id and t.get('status') == 'pending']
    if agent_pending:
        priority[agent_id] = [agent_pending[0].get('id', '')]

if priority:
    controls['priority_overrides'] = priority
    json.dump(controls, open(controls_path, 'w'), indent=2)
    print('Updated priority overrides for', list(priority.keys()))
else:
    print('No priority updates needed')
" 2>&1

# Report idle
curl -s -X POST "$RUBRIC_URL/api/agent-status" \
  -H "Content-Type: application/json" \
  -d '{"agent": "orchestrator", "status": "idle", "task": "Planning session complete"}' 2>/dev/null || true

# Post to activity feed
curl -s -X POST "$RUBRIC_URL/api/activity-log" \
  -H "Content-Type: application/json" \
  -d "{\"agent\": \"orchestrator\", \"task\": \"daily-plan\", \"summary\": \"Daily planning session complete for $TODAY\", \"status\": \"completed\"}" 2>/dev/null || true

echo "=== Planning session complete ==="
