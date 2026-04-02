#!/bin/bash
# StoryEngine Agent Runner
# Usage: ./run-agent.sh <agent-name>
# Agents: orchestrator, backend-dev, frontend-dev, qa-engineer
# Set AGENT_PROJECT_ROOT and CLAUDE_BIN env vars for VPS use.

set -e

AGENT=$1
PROJECT_ROOT="${AGENT_PROJECT_ROOT:-/Users/ryanayler/economy-fastforward}"
AGENTS_DIR="$PROJECT_ROOT/storyengine/agents"
RUBRIC_URL="${RUBRIC_URL:-http://localhost:5050}"
CLAUDE_BIN="${CLAUDE_BIN:-claude}"
BRANCH="agent-dev"

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

# Ensure we're on the right branch
CURRENT_BRANCH=$(git branch --show-current)
if [ "$CURRENT_BRANCH" != "$BRANCH" ]; then
  echo "Switching to $BRANCH branch..."
  git checkout "$BRANCH" 2>/dev/null || git checkout -b "$BRANCH"
fi

# Pull latest changes
git pull --rebase origin "$BRANCH" 2>/dev/null || true

# Report active status to RUBRIC
curl -s -X POST "$RUBRIC_URL/api/agent-status" \
  -H "Content-Type: application/json" \
  -d "{\"agent\": \"$AGENT\", \"status\": \"active\", \"task\": \"Starting session\"}" 2>/dev/null || true

# Read the agent definition
AGENT_PROMPT=$(cat "$AGENT_FILE")

# Read the current task queue
TASK_QUEUE=$(cat "$AGENTS_DIR/task-queue.json")

# Invoke Claude Code with the agent's prompt + task queue context
$CLAUDE_BIN --print -p "$(cat <<EOF
You are running as the $AGENT agent for StoryEngine.

## Your Instructions
$AGENT_PROMPT

## Current Task Queue
$TASK_QUEUE

## Important
- You are on the '$BRANCH' branch
- Always git pull --rebase before starting work
- Always git add specific files, commit, and push when done
- Only work on ONE task per session
- Report status to RUBRIC at $RUBRIC_URL/api/agent-status

Begin work now. Pick your next task and execute it.
EOF
)"

# Report idle status to RUBRIC
curl -s -X POST "$RUBRIC_URL/api/agent-status" \
  -H "Content-Type: application/json" \
  -d "{\"agent\": \"$AGENT\", \"status\": \"idle\", \"task\": \"Session complete\"}" 2>/dev/null || true
