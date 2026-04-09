#!/usr/bin/env bash
# refresh-product-brain.sh — Regenerates agents/product-brain.md from live codebase state
#
# Reads the actual codebase (pages, routes, DB tables), current PRD queue, latest handoff,
# recent git commits, and roadmap, then calls Claude to synthesize a fresh product-brain.md.
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
PRDS_DIR="$AGENTS_DIR/prds"
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

# Latest migration number
LATEST_MIGRATION=$(ls "$PROJECT_ROOT/storyengine/backend/migrations/" 2>/dev/null \
  | grep '\.sql$' | sort | tail -1 || echo "unknown")

echo "  Frontend pages: $(echo "$FRONTEND_PAGES" | tr ',' '\n' | wc -l | tr -d ' ') found"
echo "  Backend routes: $(echo "$BACKEND_ROUTE_FILES" | tr ',' '\n' | wc -l | tr -d ' ') found"
echo "  DB tables: $(echo "$DB_TABLES" | tr ',' '\n' | wc -l | tr -d ' ') found"
echo "  Latest migration: $LATEST_MIGRATION"
echo ""

# ─── 2. Read PRD queue state (with verified vs unverified distinction) ────────

PRD_QUEUE_STATE=$(python3 -c "
import json
q = json.load(open('$QUEUE_FILE'))
prds = q.get('prds', [])
active_id = q.get('active_prd')
lines = []
for p in prds:
    tasks = p.get('tasks', [])
    verified = sum(1 for t in tasks if t.get('status') == 'verified')
    done = sum(1 for t in tasks if t.get('status') in ('done', 'verified'))
    total = len(tasks)
    status = p.get('status', '?')
    lines.append(f\"PRD {p['id']}: {p['title']} [{status}] — {verified} verified / {done} done / {total} total\")
    if status == 'active':
        for t in tasks:
            s = t.get('status', 'pending')
            sym = 'V' if s == 'verified' else ('x' if s == 'done' else ' ')
            lines.append(f\"  [{sym}] {t.get('id','?')}: {t.get('title','?')} ({t.get('role','?')}) [{s}]\")
print('\n'.join(lines))
" 2>/dev/null || cat "$QUEUE_FILE")

# ─── 3. Roadmap — extract just the execution plan tables (not full 380 lines) ─

ROADMAP_PLAN=$(python3 -c "
import re
content = open('$ROADMAP_FILE').read()
# Extract from 'Sequential Execution Plan' through the end of Week 4 table
match = re.search(r'(## (Revised )?Sequential Execution Plan.*?)(\n---|\n## [A-Z])', content, re.DOTALL)
if match:
    print(match.group(1)[:3500])  # cap at ~3500 chars
else:
    # Fallback: grab lines with Day | Date | Focus patterns
    lines = [l for l in content.split('\n') if '|' in l or l.strip().startswith('###') or 'Week' in l]
    print('\n'.join(lines[:80]))
" 2>/dev/null || head -80 "$ROADMAP_FILE")

# ─── 4. Latest handoff + git log ──────────────────────────────────────────────

TODO_CONTENT=$(cat "$TODO_FILE" 2>/dev/null | head -60 || echo "todo.md not found")

RECENT_COMMITS=$(git -C "$PROJECT_ROOT" log --oneline -20 2>/dev/null \
  || echo "git log unavailable")

# ─── 5. PRD completion summary (for verified/done distinction) ────────────────

PRD_SUMMARY=$(for f in "$PRDS_DIR"/prd-*.md; do
  [ -f "$f" ] || continue
  head -3 "$f" | grep "^# PRD" || true
done 2>/dev/null)

# ─── 6. Check staleness ───────────────────────────────────────────────────────

TIMESTAMP=$(date '+%Y-%m-%d %H:%M')
if [ -f "$BRAIN_FILE" ]; then
  LAST=$(head -3 "$BRAIN_FILE" | grep "Last refreshed" \
    | sed 's/.*Last refreshed: //' | sed 's/ (.*//' || echo "unknown")
  echo "  Previous brain: $LAST"
fi
echo "  Regenerating at: $TIMESTAMP"
echo ""

# ─── 7. Build Claude synthesis prompt ─────────────────────────────────────────

PROMPT_FILE=$(mktemp /tmp/brain-refresh-XXXXXX.txt)

cat > "$PROMPT_FILE" << PROMPT_EOF
You are regenerating product-brain.md — the autonomous agent team's single source of truth for StoryEngine, an AI video SaaS.

The orchestrator reads this document at the start of every session. It must be accurate, compact, and actionable.

---

## LIVE CODEBASE EVIDENCE

Frontend pages detected: ${FRONTEND_PAGES}
Backend route files detected: ${BACKEND_ROUTE_FILES}
DB tables detected: ${DB_TABLES}
Latest migration: ${LATEST_MIGRATION}

## PRD QUEUE STATE (with task-level verification status)
${PRD_QUEUE_STATE}

PRD documents on file:
${PRD_SUMMARY}

## RECENT GIT COMMITS (last 20 — use to infer what was built this session)
${RECENT_COMMITS}

## CURRENT HANDOFF (tasks/todo.md)
${TODO_CONTENT}

## 18-DAY EXECUTION PLAN (from roadmap)
${ROADMAP_PLAN}

---

## OUTPUT INSTRUCTIONS

Write the COMPLETE product-brain.md. Sections must appear in this exact order:

### Section 1: Product Identity
- 1 short paragraph: what StoryEngine is, who it's for, the moat
- Pricing table: Starter/Creator/Studio (prices, videos/mo, key differentiator)
- 7 UX principles (action-first, 3-click, visible progress, AI insights surface, empty states sell, errors helpful, mobile-aware)
- Stack: Next.js 16 + FastAPI + Supabase | design tokens: --turquoise, --gold, --bg-void, GlassCard, ActionButton, StatusPill

### Section 2: Implementation Inventory
Feature table grouped by category. Columns: Feature | Status | Evidence

**Status rules (strict — follow exactly):**
- ✅ DONE (verified) — appears as 'verified' in prd-queue.json task list OR in a completed PRD
- ✅ DONE (unverified) — file exists in codebase but no PRD verification record
- 🔵 ACTIVE — task exists in current active PRD with pending/done (not yet verified) status
- ❌ MISSING — on roadmap, not in any PRD, no file evidence
- 📋 PLANNED — beyond current roadmap horizon

Evidence: shortest possible file path. For verified tasks, include PRD task ID (e.g., "PRD2-T3").

Categories: Auth & Access | Billing & Plans | Core Pipeline & UI | Discovery & Competitors | Analytics & Learning | Marketing & Legal | Infrastructure | Polish & Launch

Keep to 35-45 rows total. No padding.

### Section 3: Roadmap Progress
Compact table: Day | Date | Focus | Status | PRD Reference
Use recent git commits and PRD queue state to determine status accurately.

### Section 4: Current Priority Gap Queue
Tiers:
- Tier 1 — ACTIVE: list remaining PRD tasks by ID
- Tier 2 — NEXT PRD: top 4-5 unbuilt items from roadmap, specific enough to become PRD tasks
- Tier 3 — WEEK 4: polish items
- Tier 4 — POST-BETA: post-launch items

### Section 5: PRD Writing Guidelines
- Task structure (role/sizing/one concern)
- File path conventions (backend/frontend/api/types/migrations)
- Acceptance criteria patterns (curl, psql, tsc, grep, test -f)
- Wiring checklist (8 items)
- Design system (mandatory for UI)
- **What NOT to spec** — bullet list of every ✅ DONE feature name. This is the guard rail.

---

## FORMAT RULES
- Start with: # StoryEngine Product Brain
- Line 2: _Last refreshed: ${TIMESTAMP} (auto-generated)_
- Use compact tables throughout
- Total: 200-350 lines, hard cap 400
- Output ONLY the markdown document

PROMPT_EOF

if [ "$DRY_RUN" = true ]; then
  echo "=== DRY RUN: Prompt preview (first 60 lines) ==="
  head -60 "$PROMPT_FILE"
  echo "..."
  echo "(Full prompt: $(wc -l < "$PROMPT_FILE") lines)"
  rm -f "$PROMPT_FILE"
  exit 0
fi

# ─── 8. Call Claude to synthesize ─────────────────────────────────────────────

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
echo ""

# ─── 9. Auto-commit the refreshed brain ───────────────────────────────────────

cd "$PROJECT_ROOT"
if git diff --quiet "$BRAIN_FILE" 2>/dev/null; then
  echo "   (No changes to commit — brain content unchanged)"
else
  git add "$BRAIN_FILE" 2>/dev/null || true
  git commit -m "chore(brain): auto-refresh product-brain.md — ${TIMESTAMP}" \
    --no-verify 2>/dev/null \
    && echo "   Committed: product-brain.md" \
    || echo "   (git commit skipped — no repo or nothing to commit)"
fi
