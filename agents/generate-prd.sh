#!/usr/bin/env bash
# generate-prd.sh — Run Claude CLI to generate PRD, write result to file
# Usage: generate-prd.sh <prompt-file> <result-file>
set -euo pipefail

PROMPT_FILE="${1:?Usage: generate-prd.sh <prompt-file> <result-file>}"
RESULT_FILE="${2:?Usage: generate-prd.sh <prompt-file> <result-file>}"

CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude 2>/dev/null || echo "$HOME/.npm-global/bin/claude")}"

# Run Claude and capture output
OUTPUT=$("$CLAUDE_BIN" -p --model opus --output-format text < "$PROMPT_FILE" 2>/tmp/generate-prd-stderr.log) || {
  ERROR=$(cat /tmp/generate-prd-stderr.log 2>/dev/null || echo "unknown error")
  python3 -c "import json; print(json.dumps({'status':'error','error':'''$ERROR'''[:300]}))" > "$RESULT_FILE"
  exit 1
}

# Write result as JSON
python3 -c "
import json, sys
prd = sys.stdin.read()
with open('$RESULT_FILE', 'w') as f:
    json.dump({'status': 'done', 'prd': prd}, f)
" <<< "$OUTPUT"
