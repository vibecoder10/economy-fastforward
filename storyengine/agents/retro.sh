#!/bin/bash
# StoryEngine Daily Retrospective
# Analyzes daily performance, identifies patterns, updates agent memory
# Runs at 11:10 PM after daily-report.sh and calculate-skills.sh

PROJECT_ROOT="${AGENT_PROJECT_ROOT:-/Users/ryanayler/economy-fastforward}"
AGENTS_DIR="$PROJECT_ROOT/storyengine/agents"
RUBRIC_DATA="$PROJECT_ROOT/rubric/scaffold/data"
RUBRIC_URL="http://localhost:5050"
CLAUDE_BIN="${CLAUDE_BIN:-claude}"
TODAY=$(date +%Y-%m-%d)

echo "=== Daily Retrospective: $TODAY ==="

# Report active status
curl -s -X POST "$RUBRIC_URL/api/agent-status" \
  -H "Content-Type: application/json" \
  -d '{"agent": "orchestrator", "status": "active", "task": "Running daily retrospective"}' 2>/dev/null || true

# Gather inputs
TASK_QUEUE=$(cat "$AGENTS_DIR/task-queue.json" 2>/dev/null || echo "{}")
ACTIVITY_LOG=$(cat "$RUBRIC_DATA/activity-log.json" 2>/dev/null || echo "[]")
AGENT_SKILLS=$(cat "$RUBRIC_DATA/agent-skills.json" 2>/dev/null || echo "{}")
DAILY_REPORT=$(cat "$AGENTS_DIR/reports/$TODAY.md" 2>/dev/null || echo "No report today")
PREV_RETRO=$(cat "$RUBRIC_DATA/retro.json" 2>/dev/null || echo "{}")

# Feed everything to Claude for analysis
RETRO_PROMPT="You are running a daily retrospective for the StoryEngine agent team.
Analyze today's performance and produce a structured JSON retrospective.

## Today's Date
$TODAY

## Today's Activity Log (most recent first, up to last 50 entries)
$(echo "$ACTIVITY_LOG" | python3 -c "import json,sys; data=json.load(sys.stdin); print(json.dumps(data[:50], indent=2))" 2>/dev/null || echo "$ACTIVITY_LOG")

## Current Task Queue State (summary)
$(echo "$TASK_QUEUE" | python3 -c "
import json,sys
q = json.load(sys.stdin)
tabs = q.get('tabs', [])
for t in tabs:
    tasks = t.get('tasks', [])
    done = sum(1 for x in tasks if x.get('status') == 'done')
    total = len(tasks)
    print(f\"Tab {t.get('id')}: {t.get('name')} — {done}/{total} done ({t.get('status','')})\" )
" 2>/dev/null || echo "Could not parse task queue")

## Agent Skill Metrics
$AGENT_SKILLS

## Today's Daily Report
$DAILY_REPORT

## Previous Retrospective (for pattern tracking)
$(echo "$PREV_RETRO" | python3 -c "
import json,sys
r = json.load(sys.stdin)
print('Date:', r.get('date','none'))
print('Patterns:', json.dumps(r.get('recurring_patterns',[])))
print('History entries:', len(r.get('history',[])))
" 2>/dev/null || echo "No previous retro")

## Instructions
Produce ONLY valid JSON (no markdown fences, no explanation) with this exact structure:
{
  \"generated_at\": \"ISO timestamp\",
  \"date\": \"$TODAY\",
  \"summary\": \"2-3 sentence plain English summary of the day\",
  \"what_went_well\": [\"specific item 1\", \"specific item 2\"],
  \"what_failed\": [\"specific item 1\"],
  \"recurring_patterns\": [\"pattern that happened more than once\"],
  \"agent_notes\": {
    \"backend-dev\": \"specific actionable note\",
    \"frontend-dev\": \"specific actionable note\",
    \"qa-engineer\": \"specific actionable note\",
    \"orchestrator\": \"specific actionable note\",
    \"pipeline-tester\": \"specific actionable note\"
  },
  \"metrics\": {
    \"tasks_completed_today\": 0,
    \"tasks_failed_today\": 0,
    \"avg_completion_minutes\": 0,
    \"agents_active\": 0
  }
}

Rules:
- Be specific, not generic. Reference actual task IDs and agent names.
- For recurring_patterns, only list things that happened MORE THAN ONCE.
- Agent notes should be actionable — what specifically should this agent do differently tomorrow.
- Keep everything concise. Max 3 items per list.
- Output ONLY the JSON object, nothing else."

echo "Invoking Claude for analysis..."
RETRO_OUTPUT=$($CLAUDE_BIN --print -p "$RETRO_PROMPT" --model sonnet 2>&1)

if [ -z "$RETRO_OUTPUT" ]; then
  echo "ERROR: Claude returned empty output"
  exit 1
fi

# Write retro.json (merge with history from previous retro)
python3 -c "
import json, sys, os

retro_path = '$RUBRIC_DATA/retro.json'
raw_output = sys.stdin.read()

try:
    cleaned = raw_output.strip()
    fence = chr(96) * 3
    if cleaned.startswith(fence):
        cleaned = chr(10).join(cleaned.split(chr(10))[1:])
    if cleaned.endswith(fence):
        cleaned = chr(10).join(cleaned.split(chr(10))[:-1])
    cleaned = cleaned.strip()
    new = json.loads(cleaned)
except json.JSONDecodeError as e:
    print(f'ERROR: Could not parse: {e}', file=sys.stderr)
    new = {'summary': 'Parse failed', 'what_went_well': [], 'what_failed': ['Parse failed'], 'recurring_patterns': [], 'agent_notes': {}, 'metrics': {}}

try:
    prev = json.load(open(retro_path))
    history = prev.get('history', [])
except:
    history = []

history.append({'date': new.get('date', '$TODAY'), 'completed': new.get('metrics', {}).get('tasks_completed_today', 0), 'failed': new.get('metrics', {}).get('tasks_failed_today', 0), 'summary': new.get('summary', '')})
history = history[-14:]
new['history'] = history

json.dump(new, open(retro_path, 'w'), indent=2)
print('Retro written to', retro_path)
" <<< "$RETRO_OUTPUT"

# Update each agent's memory with their specific retro note
python3 -c "
import json

retro_path = '$RUBRIC_DATA/retro.json'
agents_dir = '$AGENTS_DIR'

try:
    retro = json.load(open(retro_path))
    notes = retro.get('agent_notes', {})
    for agent_id, note in notes.items():
        mem_file = agents_dir + '/memory/' + agent_id + '.md'
        try:
            with open(mem_file, 'r') as f:
                lines = f.readlines()
            entries = [l for l in lines if l.strip().startswith('-')]
            if len(entries) >= 48:
                # Prune oldest 5 entries
                kept = 0
                new_lines = []
                for l in lines:
                    if l.strip().startswith('-'):
                        kept += 1
                        if kept <= 5:
                            continue
                    new_lines.append(l)
                lines = new_lines
            with open(mem_file, 'a') as f:
                f.write('- [retro $TODAY] ' + note + '\n')
            print('Updated memory for', agent_id)
        except FileNotFoundError:
            print('No memory file for', agent_id)
except Exception as e:
    print('Error updating memory:', e)
" 2>&1

# Post to activity feed
curl -s -X POST "$RUBRIC_URL/api/activity-log" \
  -H "Content-Type: application/json" \
  -d "{\"agent\": \"orchestrator\", \"task\": \"daily-retro\", \"summary\": \"Daily retrospective generated for $TODAY\", \"status\": \"completed\"}" 2>/dev/null || true

# Report idle
curl -s -X POST "$RUBRIC_URL/api/agent-status" \
  -H "Content-Type: application/json" \
  -d '{"agent": "orchestrator", "status": "idle", "task": "Retro complete"}' 2>/dev/null || true

echo "=== Retrospective complete for $TODAY ==="
