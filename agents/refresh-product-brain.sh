#!/usr/bin/env bash
# refresh-product-brain.sh — Regenerates agents/product-brain.md from live codebase state
#
# Reads the actual codebase (pages, routes, DB tables), current PRD queue, latest handoff,
# and roadmap, then calls Claude to synthesize a fresh product-brain.md.
#
# Usage:
#   ./agents/refresh-product-brain.sh             # Regenerate product-brain.md
#   ./agents/refresh-product-brain.sh --dry-run   # Preview prompt without writing
#
# Called automatically by the Stop hook in .claude/settings.json.
# Run manually when starting a new session on a stale brain (>24h old).

set -euo pipefail

AGENTS_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$AGENTS_DIR/.." && pwd)"
BRAIN_FILE="$AGENTS_DIR/product-brain.md"
QUEUE_FILE="$AGENTS_DIR/prd-queue.json"
ROADMAP_FILE="$PROJECT_ROOT/tasks/roadmap.md"
TODO_FILE="$PROJECT_ROOT/tasks/todo.md"
SCHEMA_FILE="$PROJECT_ROOT/storyengine/schema.sql"
FRONTEND_APP="$PROJECT_ROOT/storyengine/frontend/src/app"
BACKEND_ROUTES="$PROJECT_ROOT/storyengine/backend/routes"
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude 2>/dev/null || echo "$HOME/.npm-global/bin/claude")}"

DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

die() { echo "ERROR: $*" >&2; exit 1; }

[ -f "$QUEUE_FILE" ] || die "prd-queue.json not found"
[ -f "$ROADMAP_FILE" ] || die "roadmap.md not found"

echo "=== Refreshing Product Brain ==="
echo ""

# ─── 1. Introspect live codebase ─────────────────────────────────────────────

FRONTEND_PAGES=$(ls "$FRONTEND_APP" 2>/dev/null \
  | grep -v '\.' \
  | grep -v 'layout\|providers\|global\|globals\|error\|not-found' \
  | sort | tr '\n' ', ' | sed 's/,$//')

BACKEND_ROUTE_FILES=$(ls "$BACKEND_ROUTES" 2>/dev/null \
  | grep '\.py$' | grep -v '__init__' \
  | sed 's/\.py$//' | sort | tr '\n' ', ' | sed 's/,$//')

DB_TABLES=$(grep -E "^CREATE TABLE" "$SCHEMA_FILE" 2>/dev/null \
  | sed 's/CREATE TABLE IF NOT EXISTS //' | sed 's/CREATE TABLE //' \
  | sed 's/ (.*//' | sort | tr '\n' ', ' | sed 's/,$//' || echo "schema.sql not found")

echo "  Frontend pages: $(echo "$FRONTEND_PAGES" | tr ',' '\n' | wc -l | tr -d ' ') found"
echo "  Backend routes: $(echo "$BACKEND_ROUTE_FILES" | tr ',' '\n' | wc -l | tr -d ' ') found"
echo "  DB tables: $(echo "$DB_TABLES" | tr ',' '\n' | wc -l | tr -d ' ') found"
echo ""

# ─── 2. Read state files ──────────────────────────────────────────────────────

PRD_QUEUE_STATE=$(python3 -c "
import json
q = json.load(open('$QUEUE_FILE'))
prds = q.get('prds', [])
lines = []
for p in prds:
    tasks = p.get('tasks', [])
    done = sum(1 for t in tasks if t.get('status') in ('done', 'verified'))
    total = len(tasks)
    status = p.get('status', '?')
    lines.append(f\"PRD {p['id']}: {p['title']} [{status}] — {done}/{total} tasks done\")
    if status == 'active':
        pending = [t for t in tasks if t.get('status') == 'pending']
        if pending:
            lines.append(f\"  Remaining: {', '.join(t.get('id','?') for t in pending[:10])}\")
print('\n'.join(lines))
" 2>/dev/null || cat "$QUEUE_FILE")

TODO_CONTENT=$(cat "$TODO_FILE" 2>/dev/null | head -80 || echo "todo.md not found")
ROADMAP_CONTENT=$(cat "$ROADMAP_FILE" 2>/dev/null || echo "roadmap.md not found")

# Check staleness
TIMESTAMP=$(date '+%Y-%m-%d %H:%M')
LAST_REFRESH="unknown"
if [ -f "$BRAIN_FILE" ]; then
  LAST_REFRESH=$(head -3 "$BRAIN_FILE" | grep "Last refreshed" | sed 's/.*Last refreshed: //' | sed 's/ (.*//' || echo "unknown")
  echo "  Current brain: $LAST_REFRESH"
fi
echo "  Regenerating at: $TIMESTAMP"
echo ""

# ─── 3. Build Claude prompt ───────────────────────────────────────────────────

PROMPT_FILE=$(mktemp /tmp/brain-refresh-XXXXXX.txt)

cat > "$PROMPT_FILE" << PROMPT_EOF
You are regenerating product-brain.md — the single source of truth for an autonomous agent team building StoryEngine, an AI video SaaS.

Your output will be read by the orchestrator agent at the start of every session. It tells the orchestrator what's been built, what's missing, and what to build next. Keep it accurate, compact, and actionable.

## Live Codebase State (source of truth)

Frontend pages detected: ${FRONTEND_PAGES}
Backend route files detected: ${BACKEND_ROUTE_FILES}
DB tables detected: ${DB_TABLES}

## PRD Queue State
${PRD_QUEUE_STATE}

## Latest Handoff (tasks/todo.md)
${TODO_CONTENT}

## Product Roadmap (tasks/roadmap.md)
${ROADMAP_CONTENT}

---

## Instructions

Generate a complete product-brain.md document. The document MUST have these 5 sections, in this order:

### Section 1: Product Identity
- 1 paragraph: what StoryEngine is, who it's for, the moat (learning loop)
- Pricing table: Starter/Creator/Studio with prices and key differentiators
- UX principles (action-first, 3-click creation, etc.)
- Stack line + design tokens (--turquoise, --gold, --bg-void, GlassCard, etc.)

### Section 2: Implementation Inventory
A table grouped by category. Each row: Feature | Status | Evidence (file path, 1 line max).
Status icons: ✅ Done | 🔵 Active (in current PRD) | ❌ Missing (on roadmap, not built) | 📋 Planned (post-launch)

Categories: Auth & Access, Billing & Plans, Core Pipeline & UI, Discovery & Competitors, Analytics & Learning, Marketing & Legal, Infrastructure (gaps), Polish & Launch

**Rules for this section:**
- ✅ Done rows: 1 line max, just the file path evidence
- ❌ Missing rows: 1 line explanation of WHY it matters
- Total rows: 30-45 features. Do not pad with trivia.

### Section 3: Roadmap Progress
The 18-day plan from roadmap.md as a compact table: Day | Date | Focus | Status (✅ Done / 🔵 In Progress / ❌ Not Started / 📋 Pending)

### Section 4: Current Priority Gap Queue
Ordered list of what to build next. Group by tier:
- Tier 1: Active PRD tasks remaining (complete these first)
- Tier 2: Next PRD scope (highest impact unbuilt items)
- Tier 3: Week 4 polish
- Tier 4: Post-beta

For Tier 2, be SPECIFIC: "Job Queue — Redis + arq, pipeline stages as persistent jobs, server restart = lost jobs today"

### Section 5: PRD Writing Guidelines
- Task structure (role, sizing, one concern per task)
- File conventions (backend/frontend/api/types/migrations paths)
- Acceptance criteria patterns (curl, psql, tsc, grep, test -f)
- Wiring checklist (8 checkboxes)
- Design system (mandatory for UI tasks)
- What NOT to spec (already built — 1-line list to avoid duplicates)

---

## Output Rules

1. Start with: "# StoryEngine Product Brain"
2. Second line: "_Last refreshed: ${TIMESTAMP} (auto-generated from live codebase)_"
3. Use compact tables — no redundant prose
4. Total document: 200-350 lines. Do NOT exceed 400 lines.
5. The "What NOT to spec" list at the end is critical — list every completed feature so the orchestrator doesn't re-build it
6. Output ONLY the markdown document, no preamble or explanation

PROMPT_EOF

if [ "$DRY_RUN" = true ]; then
  echo "=== DRY RUN: Prompt preview ==="
  cat "$PROMPT_FILE"
  rm -f "$PROMPT_FILE"
  exit 0
fi

# ─── 4. Call Claude to generate ───────────────────────────────────────────────

echo "Calling Claude (sonnet) to synthesize product brain..."
echo "(Takes 20-40 seconds)"
echo ""

TEMP_OUTPUT=$(mktemp /tmp/brain-output-XXXXXX.md)

set +e
"$CLAUDE_BIN" -p --model sonnet --dangerously-skip-permissions < "$PROMPT_FILE" > "$TEMP_OUTPUT" 2>/dev/null
GEN_EXIT=$?
set -e

rm -f "$PROMPT_FILE"

if [ $GEN_EXIT -ne 0 ] || [ ! -s "$TEMP_OUTPUT" ]; then
  echo "ERROR: Claude failed to generate product brain (exit $GEN_EXIT)."
  echo "Keeping existing product-brain.md unchanged."
  rm -f "$TEMP_OUTPUT"
  exit 1
fi

# Validate output looks like a product brain (not an error message)
if ! head -5 "$TEMP_OUTPUT" | grep -q "StoryEngine"; then
  echo "ERROR: Output doesn't look like a valid product brain. Keeping existing."
  rm -f "$TEMP_OUTPUT"
  exit 1
fi

mv "$TEMP_OUTPUT" "$BRAIN_FILE"

LINE_COUNT=$(wc -l < "$BRAIN_FILE")
echo "✅ product-brain.md refreshed ($LINE_COUNT lines)"
echo "   Location: $BRAIN_FILE"
