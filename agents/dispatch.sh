#!/usr/bin/env bash
# dispatch.sh — Routes to the right agent system based on context
#
# Usage: ./agents/dispatch.sh <role>
#   role: backend-dev, frontend-dev, qa-engineer, pipeline-tester, orchestrator
#
# Decision logic:
#   1. PRD deployed (agents/prd.json exists + pending tasks) → run-team.sh
#   2. Focus directive or normal tasks → run-agent.sh (StoryEngine system)
#
# This script is called by cron instead of run-agent.sh directly.

set -euo pipefail

ROLE="${1:?Usage: dispatch.sh <role>}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
STORYENGINE_AGENTS="$PROJECT_ROOT/storyengine/agents"

# Map StoryEngine agent names to portable team roles
declare -A ROLE_MAP=(
  [backend-dev]=backend
  [frontend-dev]=frontend
  [qa-engineer]=qa
  [pipeline-tester]=qa
  [orchestrator]=lead
)

TEAM_ROLE="${ROLE_MAP[$ROLE]:-$ROLE}"

# --- Decision: PRD or StoryEngine? ---

PRD_FILE="$SCRIPT_DIR/prd.json"

if [ -f "$PRD_FILE" ]; then
  # Check if PRD has pending tasks for this role
  PENDING=$(python3 -c "
import json, sys
try:
    prd = json.load(open('$PRD_FILE'))
    tasks = [t for t in prd.get('tasks', []) if t.get('role') == '$TEAM_ROLE' and t.get('status') in ('pending', 'in_progress')]
    print(len(tasks))
except: print(0)
" 2>/dev/null || echo "0")

  if [ "$PENDING" -gt 0 ]; then
    echo "[dispatch] PRD active with $PENDING pending tasks for $TEAM_ROLE — using run-team.sh"
    cd "$PROJECT_ROOT" && exec bash agents/run-team.sh "$TEAM_ROLE"
  fi
fi

# No active PRD (or no tasks for this role) — fall through to StoryEngine system
echo "[dispatch] No active PRD for $TEAM_ROLE — using run-agent.sh ($ROLE)"
cd "$STORYENGINE_AGENTS" && exec bash run-agent.sh "$ROLE"
