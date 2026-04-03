#!/bin/bash
# Run an agent role against the current PRD
# Usage:
#   ./agents/run-team.sh lead prd.md     # Decompose a PRD into tasks
#   ./agents/run-team.sh backend         # Run backend agent (loops until done)
#   ./agents/run-team.sh frontend        # Run frontend agent
#   ./agents/run-team.sh qa              # Run QA verification
#   ./agents/run-team.sh security        # Run security audit
#   ./agents/run-team.sh all             # Run all roles sequentially

set -e

ROLE=$1
PRD_FILE=$2
AGENTS_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$AGENTS_DIR")"
CLAUDE_BIN="${CLAUDE_BIN:-claude}"

if [ -z "$ROLE" ]; then
  echo "Usage: ./agents/run-team.sh <role> [prd-file]"
  echo ""
  echo "Roles:"
  echo "  lead [prd.md]  — Decompose PRD into tasks"
  echo "  backend        — Build API endpoints, database, business logic"
  echo "  frontend       — Build UI components, pages, client wiring"
  echo "  qa             — Verify tasks, browser testing, bug filing"
  echo "  security       — Security audit, vulnerability scanning"
  echo "  all            — Run all roles sequentially"
  exit 1
fi

# If "lead" with a PRD file, delegate to decompose.sh
if [ "$ROLE" = "lead" ] && [ -n "$PRD_FILE" ]; then
  exec bash "$AGENTS_DIR/decompose.sh" "$PRD_FILE"
fi

# For "all", run each role sequentially
if [ "$ROLE" = "all" ]; then
  echo "Running all roles sequentially..."
  for r in backend frontend qa security; do
    echo ""
    echo "=========================================="
    echo "  Running: $r"
    echo "=========================================="
    bash "$AGENTS_DIR/run-team.sh" "$r" || echo "  $r finished (may have blocked tasks)"
  done
  echo ""
  echo "All roles complete. Running lead review..."
  bash "$AGENTS_DIR/run-team.sh" "lead"
  exit 0
fi

# Check role file exists
ROLE_FILE="$AGENTS_DIR/roles/$ROLE.md"
if [ ! -f "$ROLE_FILE" ]; then
  echo "Error: Role file not found: $ROLE_FILE"
  echo "Available roles: $(ls "$AGENTS_DIR/roles/" | sed 's/.md//g' | tr '\n' ' ')"
  exit 1
fi

# Check prd.json exists
if [ ! -f "$AGENTS_DIR/prd.json" ]; then
  echo "Error: No prd.json found. Run decompose first:"
  echo "  ./agents/run-team.sh lead path/to/prd.md"
  exit 1
fi

# Gather context
TEAM_CONFIG=$(cat "$AGENTS_DIR/TEAM.md")
ROLE_INSTRUCTIONS=$(cat "$ROLE_FILE")
PRD=$(cat "$AGENTS_DIR/prd.json")
PROGRESS=$(cat "$AGENTS_DIR/progress.md" 2>/dev/null || echo "No progress yet. All tasks are pending.")
GIT_LOG=$(cd "$PROJECT_ROOT" && git log --oneline -20 2>/dev/null || echo "No git history.")

# Check for project-specific context
PROJECT_CONTEXT=""
if [ -f "$PROJECT_ROOT/CLAUDE.md" ]; then
  PROJECT_CONTEXT="## Project Instructions (CLAUDE.md)
$(head -100 "$PROJECT_ROOT/CLAUDE.md")"
fi

# Build the prompt
PROMPT="$TEAM_CONFIG

$ROLE_INSTRUCTIONS

$PROJECT_CONTEXT

## Current PRD & Tasks
\`\`\`json
$PRD
\`\`\`

## Current Progress
$PROGRESS

## Recent Git History
\`\`\`
$GIT_LOG
\`\`\`

## Your Mission

You are the **$ROLE** agent. Work through your tasks autonomously:

1. Read the PRD tasks and progress above
2. Find the next task assigned to your role that is pending and has all dependencies met
3. Implement it
4. Run its acceptance criteria to verify
5. If pass: git commit, update progress.md, move to next task
6. If fail after 3 attempts: mark as blocked in progress.md, move to next task
7. Repeat until all your tasks are done or blocked

When finished, update progress.md with final status.

IMPORTANT: You are autonomous. Do not ask for permission. Implement, test, commit, continue.
Do NOT stop after one task — keep going until all your role's tasks are complete or blocked.

Begin work now."

# Run the agent
PROMPT_FILE=$(mktemp /tmp/agent-$ROLE-XXXXXX.txt)
printf '%s' "$PROMPT" > "$PROMPT_FILE"

echo "Starting $ROLE agent..."
echo "  PRD: $(python3 -c "import json; print(json.load(open('$AGENTS_DIR/prd.json')).get('title','Unknown'))" 2>/dev/null || echo "Unknown")"
echo "  Progress: $AGENTS_DIR/progress.md"
echo ""

$CLAUDE_BIN -p \
  --dangerously-skip-permissions \
  < "$PROMPT_FILE"

AGENT_EXIT=$?
rm -f "$PROMPT_FILE"

if [ $AGENT_EXIT -ne 0 ]; then
  echo "Agent $ROLE exited with code $AGENT_EXIT"
fi

echo ""
echo "$ROLE agent session complete."
echo "Progress: $(cat "$AGENTS_DIR/progress.md" 2>/dev/null | grep -c '\[x\]' || echo 0) tasks done"
