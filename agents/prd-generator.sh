#!/usr/bin/env bash
# prd-generator.sh — Autonomous PRD Inventor
#
# Reads the product roadmap + current PRD queue state, then invokes Claude
# to author the next PRD document. This fills the queue when it runs low
# so agents always have something to work on.
#
# Usage:
#   ./agents/prd-generator.sh               # Auto-detect what PRD to write next
#   ./agents/prd-generator.sh --preview     # Show what the next PRD would cover (no write)
#   ./agents/prd-generator.sh --prd 5       # Force-generate PRD 5
#   ./agents/prd-generator.sh --prd 5 --title "Job Queue & Reliability"
#
# The generated PRD is written to: agents/prds/prd-N-<slug>.md
# It is then registered in prd-queue.json automatically.
#
# Run this manually, or wire into a cron/monitor when queue depth < 2 pending PRDs.

set -euo pipefail

AGENTS_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$AGENTS_DIR/.." && pwd)"
QUEUE_FILE="$AGENTS_DIR/prd-queue.json"
PRDS_DIR="$AGENTS_DIR/prds"
ROADMAP_FILE="$PROJECT_ROOT/tasks/roadmap.md"
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude 2>/dev/null || echo "$HOME/.npm-global/bin/claude")}"
RUBRIC_URL="${RUBRIC_URL:-http://localhost:5050}"

# ─── Parse args ───────────────────────────────────────────────────────────────
PREVIEW=false
FORCE_PRD_ID=""
FORCE_TITLE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --preview)        PREVIEW=true; shift ;;
    --prd)            FORCE_PRD_ID="$2"; shift 2 ;;
    --title)          FORCE_TITLE="$2"; shift 2 ;;
    --help|-h)
      echo "Usage: $0 [--preview] [--prd N] [--title 'Title']"
      echo ""
      echo "  (no args)       Auto-detect next PRD number and invent it from roadmap"
      echo "  --preview       Show what the next PRD would cover (dry run, no write)"
      echo "  --prd N         Force the PRD ID number (e.g., --prd 5)"
      echo "  --title TEXT    Override the PRD title"
      exit 0 ;;
    *)                echo "Unknown arg: $1"; exit 1 ;;
  esac
done

die() { echo "ERROR: $*" >&2; exit 1; }

[ -f "$QUEUE_FILE" ] || die "prd-queue.json not found at $AGENTS_DIR/prd-queue.json"
[ -f "$ROADMAP_FILE" ] || die "roadmap.md not found at $ROADMAP_FILE"
[ -d "$PRDS_DIR" ] || mkdir -p "$PRDS_DIR"

post_activity() {
  curl -s -X POST "$RUBRIC_URL/api/activity-log" \
    -H "Content-Type: application/json" \
    -d "{\"agent\":\"prd-generator\",\"task\":\"generate\",\"summary\":\"$1\",\"status\":\"${2:-info}\"}" 2>/dev/null || true
}

# ─── Determine next PRD number ────────────────────────────────────────────────
QUEUE_STATE=$(python3 -c "
import json
q = json.load(open('$QUEUE_FILE'))
prds = q.get('prds', [])
active_id = q.get('active_prd')
max_id = max((p['id'] for p in prds), default=0)
pending_count = sum(1 for p in prds if p.get('status') == 'pending')
active_prd = next((p for p in prds if p['id'] == active_id), None)
active_remaining = 0
if active_prd:
    tasks = active_prd.get('tasks', [])
    active_remaining = sum(1 for t in tasks if t.get('status') == 'pending')

# Collect existing PRD titles/ids for context
existing = [{'id': p['id'], 'title': p['title'], 'status': p.get('status','?')} for p in prds]

print(f\"MAX_ID={max_id}\")
print(f\"PENDING_PRDS={pending_count}\")
print(f\"ACTIVE_REMAINING={active_remaining}\")
print(f\"ACTIVE_ID={active_id}\")
import json as j
print(f\"EXISTING_JSON={j.dumps(existing)}\")
" 2>/dev/null)

eval "$QUEUE_STATE"
NEXT_PRD_ID="${FORCE_PRD_ID:-$((MAX_ID + 1))}"

echo "=== PRD Generator ==="
echo "  Current queue: PRDs 1-${MAX_ID} exist"
echo "  Active: PRD ${ACTIVE_ID} (${ACTIVE_REMAINING} tasks remaining)"
echo "  Pending PRDs in queue: ${PENDING_PRDS}"
echo "  Will generate: PRD ${NEXT_PRD_ID}"
echo ""

# ─── Build the roadmap context ────────────────────────────────────────────────
# Read the full roadmap + summarize what the existing PRDs already covered
EXISTING_PRDS_SUMMARY=$(python3 -c "
import json
existing = json.loads('$EXISTING_JSON')
lines = []
for p in existing:
    lines.append(f\"PRD {p['id']}: {p['title']} [{p['status']}]\")
print('\n'.join(lines))
" 2>/dev/null)

ROADMAP_CONTENT=$(cat "$ROADMAP_FILE")

# ─── Load product brain (live codebase state) ─────────────────────────────────
PRODUCT_BRAIN=""
BRAIN_FILE="$AGENTS_DIR/product-brain.md"
if [ -f "$BRAIN_FILE" ]; then
  PRODUCT_BRAIN=$(cat "$BRAIN_FILE")
  BRAIN_AGE_HOURS=$(python3 -c "
import os, time
mtime = os.path.getmtime('$BRAIN_FILE')
age_h = (time.time() - mtime) / 3600
print(f'{age_h:.0f}')
" 2>/dev/null || echo "?")
  echo "  Product brain loaded (${BRAIN_AGE_HOURS}h old): $BRAIN_FILE"
  if [ "${BRAIN_AGE_HOURS}" != "?" ] && [ "${BRAIN_AGE_HOURS}" -gt 24 ] 2>/dev/null; then
    echo "  WARNING: product-brain.md is >24h old. Consider running ./agents/refresh-product-brain.sh"
  fi
else
  echo "  WARNING: agents/product-brain.md not found."
  echo "  Run ./agents/refresh-product-brain.sh to generate it."
  echo "  Falling back to roadmap-only PRD generation (less accurate)."
fi
echo ""

# Also pull any existing PRD files for context on scope/style
EXISTING_PRD_SAMPLE=""
HIGHEST_PRD="$PRDS_DIR/prd-${MAX_ID}-*.md"
if ls $HIGHEST_PRD 2>/dev/null | head -1 | grep -q "."; then
  EXISTING_PRD_SAMPLE=$(head -120 $(ls $HIGHEST_PRD 2>/dev/null | head -1) 2>/dev/null || echo "")
fi

# ─── Preview mode ─────────────────────────────────────────────────────────────
if [ "$PREVIEW" = true ]; then
  echo "=== PREVIEW: What PRD ${NEXT_PRD_ID} would cover ==="
  echo ""
  echo "Existing PRDs:"
  echo "$EXISTING_PRDS_SUMMARY"
  echo ""
  echo "Roadmap gaps not yet covered by PRDs 1-${MAX_ID}:"
  python3 -c "
roadmap = open('$ROADMAP_FILE').read()
# Identify week/tier sections not addressed by existing PRDs
import re
weeks = re.findall(r'(Week \d+.*?)(?=Week \d+|$)', roadmap, re.DOTALL)
for w in weeks[:4]:
    print(w[:300].strip())
    print('...')
    print()
" 2>/dev/null || true
  exit 0
fi

# ─── Compose the generation prompt ────────────────────────────────────────────
PROMPT_FILE=$(mktemp /tmp/prd-gen-XXXXXX.txt)

cat > "$PROMPT_FILE" << PROMPT_EOF
You are a Senior Product Manager and Engineering Lead working on StoryEngine — an AI video production SaaS ("topic in, video out").

Your job: Write PRD ${NEXT_PRD_ID} for the autonomous agent team.

## What You Know About StoryEngine

### Current Product State (AUTHORITATIVE — generated from live codebase)
${PRODUCT_BRAIN:-"⚠️  product-brain.md not available. Use roadmap + existing PRDs as fallback."}

### Product Roadmap (18-day plan — use product state above to check which days are done)
${ROADMAP_CONTENT}

### PRDs Already Written (DO NOT repeat this work)
${EXISTING_PRDS_SUMMARY}

### Style Reference (how existing PRDs are written)
The PRDs follow this format:
- Clear title: "PRD N: Feature Area — Short Description"
- Priority + target
- Context section: what EXISTS, what's MISSING, why it matters
- Design system section (mandatory for UI work)
- Tasks (T1, T2, T3...) each with: Role, Priority, Problem, Implementation steps, Files, Acceptance criteria (checkboxes)
- Dependency graph showing parallel lanes
- Agent assignment table with estimated effort

Each task:
- Has a single role: backend-dev, frontend-dev, qa-engineer, or security-auditor
- Has acceptance criteria as checkboxes (converted to shell commands by the loader)
- Addresses ONE concern (no "build X AND wire Y" — those are two tasks)
- Is sized at 15-45 minutes of agent effort

${FORCE_TITLE:+## Requested Title: $FORCE_TITLE}

## Your Task

Write **PRD ${NEXT_PRD_ID}** as a complete markdown document.

**Rules:**
1. Check the "Implementation Inventory" in the Current Product State first — DO NOT spec anything marked ✅ Done
2. Check the "Current Priority Gap Queue" — work from Tier 2 downward (Tier 1 = active PRD, don't duplicate it)
3. Pick the highest-priority UNADDRESSED items. Group related features into parallel lanes (backend + frontend can run simultaneously)
4. 8-15 tasks total — enough for 1-2 days of agent work
5. Every task must reference exact file paths in the StoryEngine repo (storyengine/backend/ or storyengine/frontend/src/)
6. Backend tasks come before frontend tasks that depend on them
7. QA/security tasks come last (after all implementation)
8. Be SPECIFIC — not "add endpoint" but "add POST /api/endpoint to routes/X.py that does X, Y, Z"
9. Acceptance criteria must be verifiable shell commands (curl, psql, tsc, grep, test -f)
10. The "What NOT to spec" list in the product state is your guard rail — check it before every task
11. Use the roadmap's tier analysis (Week 1 = payable, Week 2 = UX, Week 3 = reliable, Week 4 = launchable) to pick the right focus

Write the complete PRD now. Output ONLY the markdown document, no preamble.
PROMPT_EOF

# ─── Generate PRD with Claude ─────────────────────────────────────────────────
echo "Generating PRD ${NEXT_PRD_ID} with Claude..."
echo "(This may take 30-60 seconds)"
echo ""

post_activity "Generating PRD ${NEXT_PRD_ID} from roadmap" "started"

PRD_OUTPUT=$(mktemp /tmp/prd-gen-output-XXXXXX.md)

set +e
"$CLAUDE_BIN" -p --model opus --dangerously-skip-permissions < "$PROMPT_FILE" > "$PRD_OUTPUT" 2>/dev/null
GEN_EXIT=$?
set -e

rm -f "$PROMPT_FILE"

if [ $GEN_EXIT -ne 0 ] || [ ! -s "$PRD_OUTPUT" ]; then
  echo "ERROR: Claude failed to generate PRD (exit $GEN_EXIT)."
  echo "Check that claude CLI is available: $CLAUDE_BIN"
  rm -f "$PRD_OUTPUT"
  exit 1
fi

# ─── Extract title to make slug ───────────────────────────────────────────────
PRD_TITLE=$(head -5 "$PRD_OUTPUT" | grep "^# PRD" | sed 's/^# PRD [0-9]*: //' | head -1)
if [ -z "$PRD_TITLE" ]; then
  PRD_TITLE="${FORCE_TITLE:-Generated PRD ${NEXT_PRD_ID}}"
fi

# Create filesystem-safe slug
PRD_SLUG=$(echo "$PRD_TITLE" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9 ]//g' | tr ' ' '-' | sed 's/--*/-/g' | cut -c1-40 | sed 's/-$//')

PRD_FILE="$PRDS_DIR/prd-${NEXT_PRD_ID}-${PRD_SLUG}.md"

mv "$PRD_OUTPUT" "$PRD_FILE"

echo "✅ PRD written to: $PRD_FILE"
echo "   Title: $PRD_TITLE"
echo ""

# ─── Register in prd-queue.json ──────────────────────────────────────────────
python3 -c "
import json, re
from datetime import date

q = json.load(open('$QUEUE_FILE'))
prds = q.get('prds', [])

# Check if PRD N already registered
if any(p['id'] == $NEXT_PRD_ID for p in prds):
    print(f'PRD $NEXT_PRD_ID already in queue — updating file reference only')
    for p in prds:
        if p['id'] == $NEXT_PRD_ID:
            p['file'] = 'agents/prds/prd-$NEXT_PRD_ID-$PRD_SLUG.md'
            p['title'] = '$PRD_TITLE'
    json.dump(q, open('$QUEUE_FILE','w'), indent=2)
    exit(0)

# Count tasks in the new PRD
try:
    content = open('$PRD_FILE').read()
    task_count = len(re.findall(r'^## T\d+:', content, re.MULTILINE))
except:
    task_count = 0

new_entry = {
    'id': $NEXT_PRD_ID,
    'title': '$PRD_TITLE',
    'file': 'agents/prds/prd-$NEXT_PRD_ID-$PRD_SLUG.md',
    'status': 'pending',
    'tasks_total': task_count,
    'tasks_done': 0,
    'notes': 'Auto-generated from roadmap by prd-generator.sh on $(date +%Y-%m-%d)'
}

prds.append(new_entry)
q['prds'] = prds

# If no next_prd is set, point the active PRD's successor to this one
active_id = q.get('active_prd')
if active_id and q.get('next_prd') is None:
    q['next_prd'] = $NEXT_PRD_ID

q['updated'] = '$(date +%Y-%m-%d)'
json.dump(q, open('$QUEUE_FILE','w'), indent=2)
print(f'Registered PRD $NEXT_PRD_ID in queue ({task_count} tasks). Set as next_prd.')
" 2>/dev/null

echo ""
echo "Queue updated. Run './agents/prd-loader.sh --status' to see the new queue state."
echo ""
echo "To preview the generated PRD:"
echo "  cat '$PRD_FILE'"
echo ""
echo "To activate after current PRD completes:"
echo "  ./agents/prd-loader.sh --advance"

post_activity "PRD ${NEXT_PRD_ID} generated: ${PRD_TITLE}" "completed"

# ─── Commit the new PRD ───────────────────────────────────────────────────────
cd "$PROJECT_ROOT"
git add "$PRD_FILE" "$QUEUE_FILE" 2>/dev/null || true
git commit -m "feat: auto-generate PRD ${NEXT_PRD_ID} — ${PRD_TITLE}

Generated by prd-generator.sh from tasks/roadmap.md.
Registered in agents/prd-queue.json as status=pending." 2>/dev/null || echo "(git commit skipped — nothing staged or git error)"

echo ""
echo "✅ Done. PRD ${NEXT_PRD_ID} is in the queue and committed."
