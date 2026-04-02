#!/bin/bash
# StoryEngine Agent Runner
# Usage: ./run-agent.sh <agent-name>
# Agents: orchestrator, backend-dev, frontend-dev, qa-engineer
# Set AGENT_PROJECT_ROOT, CLAUDE_BIN, RUBRIC_URL env vars for VPS use.

set -e

AGENT=$1
PROJECT_ROOT="${AGENT_PROJECT_ROOT:-/Users/ryanayler/economy-fastforward}"
AGENTS_DIR="$PROJECT_ROOT/storyengine/agents"
RUBRIC_URL="${RUBRIC_URL:-http://localhost:5050}"
CLAUDE_BIN="${CLAUDE_BIN:-claude}"
BRANCH="agent-dev"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

if [ -z "$AGENT" ]; then
  echo "Usage: ./run-agent.sh <orchestrator|backend-dev|frontend-dev|qa-engineer>"
  exit 1
fi

AGENT_FILE="$AGENTS_DIR/$AGENT.md"
if [ ! -f "$AGENT_FILE" ]; then
  echo "Error: Agent file not found: $AGENT_FILE"
  exit 1
fi

cd "$PROJECT_ROOT"

# ─── Pause Check ──────────────────────────────────────────────────────────────
# If controls.json exists and this agent is paused, exit immediately.
CONTROLS_FILE="$AGENTS_DIR/controls.json"
if [ -f "$CONTROLS_FILE" ]; then
  IS_PAUSED=$(python3 -c "
import json, sys
try:
    data = json.load(open('$CONTROLS_FILE'))
    agents = data.get('agents', {})
    agent_ctrl = agents.get('$AGENT', {})
    print('true' if agent_ctrl.get('paused', False) else 'false')
except Exception:
    print('false')
" 2>/dev/null || echo "false")

  if [ "$IS_PAUSED" = "true" ]; then
    echo "[$TIMESTAMP] Agent '$AGENT' is paused via controls.json. Exiting."
    curl -s -X POST "$RUBRIC_URL/api/agent-status" \
      -H "Content-Type: application/json" \
      -d "{\"agent\": \"$AGENT\", \"status\": \"paused\", \"task\": \"Skipped — agent is paused\"}" 2>/dev/null || true
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

# ─── Read Agent Definition ────────────────────────────────────────────────────
AGENT_PROMPT=$(cat "$AGENT_FILE")

# ─── Read Task Queue ──────────────────────────────────────────────────────────
TASK_QUEUE=$(cat "$AGENTS_DIR/task-queue.json")

# ─── Read Handoff Notes ──────────────────────────────────────────────────────
# Pull last 3 unread notes addressed to this agent from handoffs.json
HANDOFFS_FILE="$AGENTS_DIR/handoffs.json"
HANDOFF_NOTES=""
if [ -f "$HANDOFFS_FILE" ]; then
  HANDOFF_NOTES=$(python3 -c "
import json, sys
try:
    data = json.load(open('$HANDOFFS_FILE'))
    notes = data.get('notes', [])
    unread = [n for n in notes if '$AGENT' in n.get('to', []) and not n.get('read_by', {}).get('$AGENT', False)]
    recent = unread[-3:]
    if not recent:
        sys.exit(0)
    for n in recent:
        print(f\"- [{n.get('from','?')} @ {n.get('timestamp','?')}]: {n.get('message','')}\")
except Exception:
    pass
" 2>/dev/null || echo "")
fi

# ─── Read Operator Controls ──────────────────────────────────────────────────
# Extract skipped_tasks and priority_overrides from controls.json
OPERATOR_CONTROLS=""
if [ -f "$CONTROLS_FILE" ]; then
  OPERATOR_CONTROLS=$(python3 -c "
import json, sys
try:
    data = json.load(open('$CONTROLS_FILE'))
    lines = []
    skipped = data.get('skipped_tasks', [])
    if skipped:
        lines.append('Skipped tasks (DO NOT work on these):')
        for t in skipped:
            lines.append(f'  - {t}')
    priorities = data.get('priority_overrides', [])
    if priorities:
        lines.append('Priority overrides (work on these FIRST):')
        for p in priorities:
            lines.append(f'  - {p}')
    agent_ctrl = data.get('agents', {}).get('$AGENT', {})
    focus = agent_ctrl.get('focus', '')
    if focus:
        lines.append(f'Focus directive for you: {focus}')
    print('\n'.join(lines))
except Exception:
    pass
" 2>/dev/null || echo "")
fi

# ─── Build Prompt ─────────────────────────────────────────────────────────────
# Assemble the full prompt with all injected context sections.

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

## Handoff Notes
Other agents left these notes for you (most recent last):
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
- If you need to pass context to another agent, write a note to storyengine/agents/handoffs.json with {\"from\": \"$AGENT\", \"to\": [\"target-agent\"], \"message\": \"...\", \"timestamp\": \"$TIMESTAMP\", \"read_by\": {}}.
- Report status to RUBRIC at $RUBRIC_URL/api/agent-status
- At the VERY END of your response, write a single line starting with SUMMARY: followed by a plain-English one-sentence description of what you did (for a non-technical person). Example: \"SUMMARY: Fixed a bug where image approvals weren't being saved correctly\"

Begin work now. Pick your next task and execute it."

# ─── Invoke Claude Code ───────────────────────────────────────────────────────
# Capture exit code without letting set -e kill the script.
set +e
OUTPUT=$($CLAUDE_BIN --print -p "$PROMPT" 2>&1)
CLAUDE_EXIT=$?
set -e

echo "$OUTPUT"

# ─── Handle Claude Failure ────────────────────────────────────────────────────
if [ $CLAUDE_EXIT -ne 0 ]; then
  ERROR_MSG="Claude exited with code $CLAUDE_EXIT"
  echo "ERROR: $ERROR_MSG"

  # Post error to activity feed
  curl -s -X POST "$RUBRIC_URL/api/activity-log" \
    -H "Content-Type: application/json" \
    -d "{\"agent\": \"$AGENT\", \"task\": \"\", \"summary\": $(echo "$ERROR_MSG" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip()))' 2>/dev/null || echo "\"$ERROR_MSG\""), \"status\": \"error\"}" 2>/dev/null || true

  # Report error status
  curl -s -X POST "$RUBRIC_URL/api/agent-status" \
    -H "Content-Type: application/json" \
    -d "{\"agent\": \"$AGENT\", \"status\": \"error\", \"task\": \"$ERROR_MSG\"}" 2>/dev/null || true

  exit 1
fi

# ─── Extract Results ──────────────────────────────────────────────────────────
TASK_LINE=$(echo "$OUTPUT" | grep -oE 'T[0-9]+-[0-9]+' | head -1 || echo "")
SUMMARY_LINE=$(echo "$OUTPUT" | grep "^SUMMARY:" | tail -1 | sed 's/^SUMMARY: *//' || echo "")

if [ -z "$SUMMARY_LINE" ]; then
  # Fallback: use the last git commit message
  SUMMARY_LINE=$(git log --oneline -1 2>/dev/null | cut -d' ' -f2- || echo "Session completed")
fi

# ─── Post Success to Activity Feed ────────────────────────────────────────────
curl -s -X POST "$RUBRIC_URL/api/activity-log" \
  -H "Content-Type: application/json" \
  -d "{\"agent\": \"$AGENT\", \"task\": \"$TASK_LINE\", \"summary\": $(echo "$SUMMARY_LINE" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip()))' 2>/dev/null || echo "\"$SUMMARY_LINE\""), \"status\": \"completed\"}" 2>/dev/null || true

# ─── Report Idle ──────────────────────────────────────────────────────────────
curl -s -X POST "$RUBRIC_URL/api/agent-status" \
  -H "Content-Type: application/json" \
  -d "{\"agent\": \"$AGENT\", \"status\": \"idle\", \"task\": $(echo "$SUMMARY_LINE" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip()))' 2>/dev/null || echo "\"$SUMMARY_LINE\"")}" 2>/dev/null || true
