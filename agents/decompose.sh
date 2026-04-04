#!/bin/bash
# Decompose a PRD into tasks with machine-verifiable acceptance criteria
# Usage: ./agents/decompose.sh path/to/prd.md

set -e

PRD_FILE=$1
AGENTS_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$AGENTS_DIR")"
CLAUDE_BIN="${CLAUDE_BIN:-claude}"

if [ -z "$PRD_FILE" ] || [ ! -f "$PRD_FILE" ]; then
  echo "Usage: ./agents/decompose.sh path/to/prd.md"
  echo "  Decomposes a PRD into prd.json with machine-verifiable acceptance criteria."
  exit 1
fi

PRD_CONTENT=$(cat "$PRD_FILE")
TEAM_CONFIG=$(cat "$AGENTS_DIR/TEAM.md")
LEAD_INSTRUCTIONS=$(cat "$AGENTS_DIR/roles/lead.md")

echo "Decomposing PRD: $PRD_FILE"
echo "Project root: $PROJECT_ROOT"

# Build the prompt
PROMPT="$TEAM_CONFIG

$LEAD_INSTRUCTIONS

## The PRD to Decompose

$PRD_CONTENT

## Instructions

You are in DECOMPOSE mode. Generate prd.json and progress.md for this PRD.

1. Read the PRD above carefully
2. Break it into 8-15 atomic tasks with machine-verifiable acceptance criteria
3. Order tasks bottom-up: database → backend routes → frontend pages → QA verification → security audit
4. Every acceptance criterion MUST be a shell command that exits 0 on success
5. Write the prd.json file to: $AGENTS_DIR/prd.json
6. Write the progress.md file to: $AGENTS_DIR/progress.md

IMPORTANT:
- Acceptance criteria must be RUNNABLE commands, not descriptions
- Use curl for API tests, npx tsc for type checks, test -f for file existence
- Include Playwright browser test criteria for UI tasks
- Set depends_on correctly — frontend tasks depend on their backend endpoints
- Include at least 1 QA task and 1 security task at the end

Write both files now."

# Run the lead agent
PROMPT_FILE=$(mktemp /tmp/decompose-prompt-XXXXXX.txt)
printf '%s' "$PROMPT" > "$PROMPT_FILE"

$CLAUDE_BIN -p \
  --dangerously-skip-permissions \
  < "$PROMPT_FILE"

rm -f "$PROMPT_FILE"

echo ""
echo "Decomposition complete."
echo "  PRD tasks: $AGENTS_DIR/prd.json"
echo "  Progress:  $AGENTS_DIR/progress.md"
