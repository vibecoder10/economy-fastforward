#!/bin/bash
# StoryEngine Agent Runner
# Usage: ./run-agent.sh <agent-name>
# Agents: orchestrator, backend-dev, frontend-dev, qa-engineer
# Set AGENT_PROJECT_ROOT, CLAUDE_BIN, RUBRIC_URL env vars for VPS use.

set -e

AGENT=$1
PROJECT_ROOT="${AGENT_PROJECT_ROOT:-/Users/ryanayler/economy-fastforward}"
AGENTS_DIR="$PROJECT_ROOT/storyengine/agents"
REPORTS_DIR="$AGENTS_DIR/reports"
RUBRIC_URL="${RUBRIC_URL:-http://localhost:5050}"
CLAUDE_BIN="${CLAUDE_BIN:-claude}"
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

cd "$PROJECT_ROOT"

# ─── Pause Check ──────────────────────────────────────────────────────────────
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
    echo "[$TIMESTAMP] Agent '$AGENT' is paused. Skipping."
    curl -s -X POST "$RUBRIC_URL/api/agent-status" \
      -H "Content-Type: application/json" \
      -d "{\"agent\": \"$AGENT\", \"status\": \"idle\", \"task\": \"Paused by operator\"}" 2>/dev/null || true
    exit 0
  fi
fi

# ─── Branch Setup ─────────────────────────────────────────────────────────────
CURRENT_BRANCH=$(git branch --show-current)
if [ "$CURRENT_BRANCH" != "$BRANCH" ]; then
  echo "Switching to $BRANCH branch..."
  git checkout "$BRANCH" 2>/dev/null || git checkout -b "$BRANCH"
fi

git pull --rebase origin "$BRANCH" 2>/dev/null || true

# ─── Report Active ────────────────────────────────────────────────────────────
curl -s -X POST "$RUBRIC_URL/api/agent-status" \
  -H "Content-Type: application/json" \
  -d "{\"agent\": \"$AGENT\", \"status\": \"active\", \"task\": \"Starting session\"}" 2>/dev/null || true

# ─── Read Inputs ──────────────────────────────────────────────────────────────
AGENT_PROMPT=$(cat "$AGENT_FILE")
TASK_QUEUE=$(cat "$AGENTS_DIR/task-queue.json")

# Read handoffs addressed to this agent
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

# Read operator controls
OPERATOR_CONTROLS=""
if [ -f "$CONTROLS_FILE" ]; then
  OPERATOR_CONTROLS=$(python3 -c "
import json
try:
    c = json.load(open('$CONTROLS_FILE'))
    parts = []
    f = c.get('focus', '')
    if f: parts.append('FOCUS DIRECTIVE (this is your top priority from the operator): ' + f)
    s = c.get('skipped_tasks', [])
    if s: parts.append('SKIPPED TASKS (do NOT pick these): ' + ', '.join(s))
    p = c.get('priority_overrides', {})
    if p: parts.append('PRIORITY OVERRIDES (pick these first, lower number = higher): ' + json.dumps(p))
    print('\n'.join(parts))
except: pass
" 2>/dev/null || echo "")
fi

# ─── Build Prompt ─────────────────────────────────────────────────────────────
PROMPT="You are running as the $AGENT agent for StoryEngine.

## Your Instructions
$AGENT_PROMPT"

if [ -n "$OPERATOR_CONTROLS" ]; then
  PROMPT="$PROMPT

## Operator Controls
$OPERATOR_CONTROLS"
fi

if [ -n "$HANDOFF_NOTES" ]; then
  PROMPT="$PROMPT

## Handoff Notes (from other agents)
$HANDOFF_NOTES"
fi

PROMPT="$PROMPT

## Current Task Queue
$TASK_QUEUE

## Important Rules
- You are on the '$BRANCH' branch.
- Always git pull --rebase before starting work.
- Always git add specific files, commit with a descriptive message, and push when done.
- Only work on ONE task per session. Do it well.
- All timestamps must be UTC ISO-8601 (e.g. $TIMESTAMP).
- When marking a task in_progress, set started_at and assigned_to. When done, set completed_at.
- After completing, POST a handoff to $RUBRIC_URL/api/handoffs if the next related task is for a different agent.
- Report status to RUBRIC at $RUBRIC_URL/api/agent-status

## Output Format (MANDATORY)
At the VERY END of your response, write these TWO sections:

SUMMARY: [One sentence, plain English, for a non-technical person. Example: 'Fixed a bug where image approvals were not saving correctly']

DETAIL:
- [Bullet point 1: what you did, in simple terms]
- [Bullet point 2: why you did it]
- [Bullet point 3: what changed for the user]
- [Any other relevant bullet points]
- [What the next agent should work on]

Begin work now. Pick your next task and execute it."

# ─── Invoke Claude Code ───────────────────────────────────────────────────────
# Use -p (not --print) so Claude can actually edit files and run commands.
# --dangerously-skip-permissions allows headless operation without confirmation prompts.
set +e
OUTPUT=$($CLAUDE_BIN -p "$PROMPT" --dangerously-skip-permissions 2>&1)
CLAUDE_EXIT=$?
set -e

# ─── Save Full Report ────────────────────────────────────────────────────────
REPORT_FILE="$REPORTS_DIR/$RUN_ID.md"
cat > "$REPORT_FILE" << REPORTEOF
# Agent Run: $AGENT
**Date:** $TIMESTAMP
**Run ID:** $RUN_ID

---

$OUTPUT
REPORTEOF

echo "Report saved: $REPORT_FILE"

# ─── Handle Failure ──────────────────────────────────────────────────────────
if [ $CLAUDE_EXIT -ne 0 ]; then
  ERROR_MSG="Agent crashed (exit code $CLAUDE_EXIT)"
  curl -s -X POST "$RUBRIC_URL/api/activity-log" \
    -H "Content-Type: application/json" \
    -d "{\"agent\": \"$AGENT\", \"task\": \"\", \"summary\": $(echo "$ERROR_MSG" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip()))' 2>/dev/null || echo "\"$ERROR_MSG\""), \"status\": \"error\", \"detail_file\": \"$RUN_ID.md\"}" 2>/dev/null || true

  curl -s -X POST "$RUBRIC_URL/api/agent-status" \
    -H "Content-Type: application/json" \
    -d "{\"agent\": \"$AGENT\", \"status\": \"idle\", \"task\": \"$ERROR_MSG\"}" 2>/dev/null || true
  exit 1
fi

# ─── Extract Results ──────────────────────────────────────────────────────────
TASK_LINE=$(echo "$OUTPUT" | grep -oE 'T[0-9]+-[0-9]+' | head -1 || echo "")
SUMMARY_LINE=$(echo "$OUTPUT" | grep "^SUMMARY:" | tail -1 | sed 's/^SUMMARY: *//' || echo "")
DETAIL_LINES=$(echo "$OUTPUT" | sed -n '/^DETAIL:/,/^$/p' | grep "^-" || echo "")

if [ -z "$SUMMARY_LINE" ]; then
  SUMMARY_LINE=$(git log --oneline -1 2>/dev/null | cut -d' ' -f2- || echo "Session completed")
fi

# ─── Post to Activity Feed ───────────────────────────────────────────────────
DETAIL_JSON=$(echo "$DETAIL_LINES" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip()))' 2>/dev/null || echo "\"\"")

curl -s -X POST "$RUBRIC_URL/api/activity-log" \
  -H "Content-Type: application/json" \
  -d "{\"agent\": \"$AGENT\", \"task\": \"$TASK_LINE\", \"summary\": $(echo "$SUMMARY_LINE" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip()))' 2>/dev/null || echo "\"$SUMMARY_LINE\""), \"detail\": $DETAIL_JSON, \"detail_file\": \"$RUN_ID.md\", \"status\": \"completed\"}" 2>/dev/null || true

# ─── Report Idle ──────────────────────────────────────────────────────────────
curl -s -X POST "$RUBRIC_URL/api/agent-status" \
  -H "Content-Type: application/json" \
  -d "{\"agent\": \"$AGENT\", \"status\": \"idle\", \"task\": $(echo "$SUMMARY_LINE" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip()))' 2>/dev/null || echo "\"$SUMMARY_LINE\"")}" 2>/dev/null || true
