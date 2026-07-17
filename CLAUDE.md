# Economy FastForward — AI Video Production Pipeline
"Topic in, video out — length configured per-idea in SupaBase"

---

## VPS Deploy Coordination Rule (MANDATORY — multiple agent sessions share this box)

Restarting the StoryEngine backend kills uvicorn's in-process background tasks — that means
**another session's running video build dies** and whatever is on main ships instantly. Sessions
have clobbered each other this way. The protocol:

1. **Deploy ONLY via the script:** `~/projects/economy-fastforward/storyengine/scripts/vps-deploy.sh <your-session-name> [--with-frontend]` (on the VPS). Never raw-kill uvicorn, never `pkill -f uvicorn` (it has matched voice-osiris and the ssh session itself).
2. **The lock file is law:** `~/deploy.lock` on the VPS. Before ANY prod work that must not be interrupted (a deploy, a proof run, a paid pipeline run), write your session name + task + timestamp into it; delete it when done. The deploy script refuses to run while it exists. If you find a lock older than ~2 hours, it's probably stale — check `~/deploys.log` and proceed with `--force` only then.
3. **Local tree discipline:** don't build in the shared `~/economy-fastforward` checkout — use a git worktree + feature branch, fold back to main only deploy-ready work (main must ALWAYS be deployable, because any session's restart ships it). Run `git status` before touching shared files.
4. **After deploying**, append what you shipped to `~/deploys.log` (the script does this) and confirm the service came back: `systemctl is-active storyengine-backend.service`.

---

## Web Design Rule (MANDATORY)
**For ANY website/UI work** — building pages, components, layouts, styling, or visual changes — **invoke the `web-design-system` skill FIRST** before writing any code. This skill establishes design foundations, component choices, and visual best practices. No exceptions, even for "small" UI tweaks.

---

## Structural Change Rule
**MANDATORY:** Any session that moves, renames, creates, or deletes files/folders MUST update `SYSTEM_STATE.md` before committing. This includes:
- New bots, steps, or modules
- Renamed or moved files
- Changed import paths
- New cron jobs or Slack commands
- New Supabase tables or fields

---

## Visual Output Verification Rule (MANDATORY)
**Before declaring ANY visual generation task complete** — images, keyframes, thumbnails, storyboards, video — **you MUST:**

1. **Download/fetch ALL output assets** from the specified folder
2. **Visually review EVERY frame** — don't just check that files exist
3. **Compare against the brief/prompt/expected result** — verify character appearance, composition, location details match
4. **Run vision analysis** (Claude vision) to check character appearance against specifications:
   - Expected: Black man → actual image must show dark brown skin
   - Expected: White man → actual image must show fair/light skin
   - Expected: Office with glass walls → actual image must show glass walls
5. **Flag any discrepancies immediately** — do NOT send broken work to the user
6. **Only AFTER verification passes** do you report "done" and send files

**Why:** On 2026-04-07, generated keyframes with wrong character appearance (white instead of Black). I didn't look at the output before sending. This verification process prevents that.

**Implementation:**
- Use `video_dispatch.verify_output.verify_images_in_folder()` before reporting completion
- Use `video_dispatch.verify_output.verify_keyframes()` in dispatch.py (PHASE 1.5)
- For any visual work: download folder, analyze, verify, then report

**Code location:** `skills/video-pipeline/video_dispatch/verify_output.py` (382 lines, handles both keyframes and generic image folders)

---

## 🦸 Superpowers Skill Integration

**Skills are NOT optional. Invoke them BEFORE acting.** Use the `Skill` tool.

### Skill → Scenario Mapping

| Scenario | Skill to Invoke FIRST | Why |
|----------|----------------------|-----|
| **ANY website/UI work** | `web-design-system` | Design foundations FIRST. No exceptions. |
| **Product idea / feature direction / "how should we..."** | `thinking-partner` | Co-create, don't just execute. Insights before code. |
| **New feature (3+ steps or multi-layer)** | `structured-workflow` | Discuss → Plan → Execute → Verify. No improvising. |
| **User shares rough notes / brainstorming** | `thinking-partner` then `structured-workflow` | Think first, then structure. |
| **Bug report / test failure** | `systematic-debugging` | Diagnose before fixing. No guessing. |
| **About to say "done" or "fixed"** | `verification-before-completion` | Prove it works. Run commands. Show output. |
| **2+ independent tasks** | `dispatching-parallel-agents` | Parallelize for speed |
| **Need feature isolation** | `using-git-worktrees` | Safe experimentation |
| **Next.js code (pages, routes, API, RSC)** | `next-best-practices` | Correct patterns for routing, data fetching, caching |
| **React components (hooks, state, props)** | `react-best-practices` | 65 performance rules, avoid waterfalls and re-renders |
| **Component architecture / refactoring** | `composition-patterns` | Compound components, avoid boolean prop sprawl |
| **Database schema, queries, Postgres** | `supabase-postgres-best-practices` | Indexes, RLS, schema design, connection pooling |
| **Remotion video code (scenes, timing, audio)** | `remotion-best-practices` | Domain-specific Remotion patterns |
| **Testing UI / verifying frontend works** | `webapp-testing` | Playwright scripts catch broken icons, links, wiring |
| **UI review / design audit** | `web-design-guidelines` | Audit against Web Interface Guidelines |

### The 1% Rule

If there's even a **1% chance** a skill applies → **invoke it**.

---

## Stack
**Pipeline:** Python 3.11+ (async) · Remotion · Supabase (orchestration DB) · Claude (scripts) · Kie.ai (images/video) · ElevenLabs (voice) · Whisper (transcription) · Google Drive (storage) · Slack (control)
**StoryEngine:** Next.js 16 · React 19 · TypeScript · TailwindCSS 4 · Framer Motion · React Query · FastAPI · Supabase PostgreSQL · asyncpg

## Repo Structure

```
skills/video-pipeline/           # Core pipeline (each tool = standalone folder)
├── orchestrator/                # Pipeline brain — status router, Slack bot
│   ├── pipeline.py              # Main status-driven router
│   ├── pipeline_control.py      # Slack bot commands
│   ├── pipeline_constants.py    # Field names, status enums, table IDs
│   ├── pipeline_config.py       # Env/config loading
│   ├── approval_watcher.py      # Slack approval monitoring
│   ├── webhook_server.py        # External webhook receiver
│   └── handlers/                # Slack command handlers (admin, style, delete)
│
├── autopilot/                   # Autonomous intelligence (CTR/VPH driven)
│   ├── autopilot.py             # Main loop (--status, --check-cycle, --force)
│   ├── autopilot_program.md     # Human-editable config
│   ├── core/                    # Config, state, cadence, scorer, notifier
│   ├── analysis/                # Thumbnail analyzer, adapter, title selector
│   ├── monitoring/              # CTR monitor, early warning, perf comparator
│   ├── learning/                # Pattern library, learning extractor, memory writer
│   ├── memory/                  # LEARNINGS.md, patterns (git-tracked)
│   └── tests/                   # 102 tests
│
├── competitor_scraper/          # Pull competitor YouTube data
├── discovery/                   # Headline + trending topic scanning
├── title_idea/                  # Title creation from data-backed research
│   ├── idea_bot.py, trending_idea_bot.py, idea_modeling.py
│   └── curiosity_gap/           # Gap-based title generation (6 tests)
├── research/                    # Deep-dive factual research (agent.py)
│
├── script/                      # 6-scene script writing
│   ├── run.py                   # Script generation step
│   ├── story_bible.py           # Character/location bibles
│   └── brief_translator/        # Research → script pipeline (11 files, 7 tests)
├── voice/                       # Voice synthesis (ElevenLabs)
├── image_prompts/               # Image prompt generation
│   ├── run.py                   # Prompt generation step
│   └── engine/                  # 3-style system: Dossier 60%, Schema 22%, Echo 18%
├── storyboard/                  # Storyboard grid generation
├── images/                      # Image creation (Seed Dream 4.5)
├── video_motion/                # Video scripts + clip generation (Veo 3.1)
│   └── animation/               # 3D animation pipeline
├── sound/                       # Sound FX + Music selection
├── thumbnail/                   # Thumbnail generation (templates, Gemini director)
├── render/                      # Audio sync + Remotion rendering
│   ├── render_video.py          # Calls Remotion CLI
│   └── audio_sync/              # Whisper alignment (7 files, 4 tests)
├── upload/                      # YouTube upload + SEO
│
├── analytics/                   # Performance tracking
│   ├── performance_tracker.py   # Daily YouTube metrics sync
│   └── osiris/                  # Learning system (48h/7d analysis, title patterns)
│
├── shared/                      # Cross-bot infrastructure
│   ├── clients/                 # API wrappers (airtable, anthropic, image, google, etc.)
│   ├── profiles/visual/         # Visual styles (cinematic_illustration, dossier, hud, mannequin)
│   ├── profiles/script/         # Script voice profiles (power_doctrine_v1, v2)
│   ├── json_utils.py            # JSON parsing with fallback chain
│   └── channel_profile.py       # Channel-specific settings
│
├── infra/                       # Setup scripts, cron, healthcheck, auth
│   ├── setup_cron.sh            # VPS cron job definitions
│   ├── bot_healthcheck.sh       # Auto-restart Slack bot
│   └── setup_*.py               # Airtable/YouTube field setup scripts
│
├── tests/                       # Integration tests
└── requirements.txt

remotion-video/                  # TypeScript/Remotion video renderer
storyengine/                     # Production dashboard (Next.js 16 + FastAPI + Supabase)
├── frontend/                    # Next.js 16, React 19, TailwindCSS 4, Framer Motion
│   ├── src/app/                 # App Router: dashboard, pipeline, create, analytics, etc.
│   ├── src/components/          # production/, video-detail/, ui/, autopilot/, nav/
│   ├── src/hooks/               # use-task-poller (background task polling)
│   └── src/lib/                 # api.ts, types.ts, constants.ts
├── backend/                     # FastAPI, asyncpg, 14 route modules
│   ├── main.py                  # Route registration (ALWAYS check when adding routes)
│   ├── models.py                # Pydantic models (source of truth for API shapes)
│   ├── routes/                  # dashboard, videos, pipeline, assets, autopilot, etc.
│   ├── pipeline_executor.py     # Background task orchestrator
│   ├── job_queue.py             # arq enqueue abstraction (stage → Redis job)
│   ├── task_store.py            # db_persist_task() — background_tasks DB writes
│   └── worker.py                # arq WorkerSettings + stage handlers
└── schema.sql                   # Canonical DB schema (9 tables, 51+ columns)
tasks/                           # Task tracking, lessons learned
├── todo.md                      # Current tasks + handoffs
├── lessons.md                   # Hard-won patterns (read EVERY session)
└── roadmap.md                   # Product roadmap + SaaS journal
docs/                            # Reference documentation
├── reports/                     # Completion reports, wiring status, migrations
├── reviews/                     # System reviews (animation, architecture)
├── reference/                   # Outdated but preserved docs
└── superpowers/                 # Feature plans + specs
```

## Architecture

### System Layers
1. **Autopilot** — Top-level intelligence. Fed by CTR, VPH, AVD data. Auto-enhancing. Decides WHAT to make.
2. **Orchestrator** — Calls each bot at the right time. Status-driven via Airtable. Decides WHEN to run each step.
3. **Bot Folders** — Each tool is standalone. Does ONE thing. Called by orchestrator or CLI.
4. **Shared** — API clients, visual profiles, utilities. Used by all bots.

### Pipeline Flow (Status-Driven)
```
Idea Logged → (approval) → Ready For Scripting → script/
→ Ready For Voice → voice/ → Ready For Image Prompts → image_prompts/
→ Ready For Images → images/ → Ready For Video Scripts → video_motion/
→ Ready For Video Generation → video_motion/ → Ready For Thumbnail → thumbnail/
→ Ready To Render → render/ → Rendered → upload/ → Done
```

CRITICAL: Never skip a status. Always update via Airtable client. Check status before processing.

### Autopilot Brain
Autonomous orchestration layer above the pipeline:
1. Reads config from `autopilot_program.md` (weights, cadence, thresholds)
2. Scores candidate ideas from Competitor Videos table
3. Picks best idea, notifies Slack with reasoning
4. Writes style overrides to Airtable
5. Triggers pipeline execution → YouTube draft
6. Monitors CTR at 6h/24h/48h → extracts learnings to memory files

```bash
cd skills/video-pipeline
python -m autopilot.autopilot --status       # Show state
python -m autopilot.autopilot --check-cycle  # Run one cycle
python -m autopilot.autopilot --force        # Skip cadence
```

### Import Conventions
All imports use canonical paths:
```python
from orchestrator.pipeline_constants import IdeaFields, Statuses
from shared.clients.airtable_client import AirtableClient
from shared.clients.anthropic_client import AnthropicClient
from shared.profiles.visual import load_profile
from shared.profiles.script.schema import ScriptProfile
from shared.json_utils import parse_json_response
from image_prompts.engine.prompt_builder import build_prompt
from render.audio_sync.aligner import align_words
from script.brief_translator.script_generator import generate_script
from title_idea.curiosity_gap.gap_title_engine import generate_titles
from analytics.osiris.learnings_engine import inject_learnings
```

---

## Session Protocol

### Session Start (EVERY session, no exceptions)
1. Check current branch and recent commits: `git log --oneline -5`
2. Read `tasks/lessons.md` — hard-won patterns that prevent repeat mistakes
3. Read `tasks/decisions.md` — settled architectural choices (don't re-litigate these)
4. Read `tasks/todo.md` — pick up where the last session left off
5. Understand what bot folder we're working on before touching code

### Session End (EVERY session, no exceptions)
Claude Code has NO memory between sessions. Before ending ANY session:
1. Update `tasks/todo.md` with current progress and what's next
2. Update `tasks/lessons.md` if ANY corrections were made
3. Update `tasks/decisions.md` if ANY architectural choices were made (append-only)
4. Commit all changes with a descriptive message
5. If work is incomplete, leave a clear `## Handoff` section in `tasks/todo.md`

---

## Execution Protocol

**For non-trivial features (3+ steps or multi-layer), invoke `structured-workflow` skill.** It enforces: Discuss → Plan → Execute → Verify.

**For any product/feature decision, invoke `thinking-partner` skill.** Lead with insight, not agreement.

For all tasks:
1. THINK: What's the most interesting observation about this task? Share it first.
2. UNDERSTAND: Read relevant files. If requirements are ambiguous, ASK — don't guess.
3. SEARCH: grep/glob for similar existing functionality before creating anything new.
4. PLAN: Before writing code, outline files to modify and why.
5. Wait for approval on changes touching >3 files.
6. IMPLEMENT: One logical change at a time.
7. VERIFY: Run tests after every change.

## Anti-Bandaid Rules
* If a fix requires modifying >3 files, STOP. Question the architecture first.
* Never patch around a design flaw — propose refactoring the design instead.
* Remove dead code. No commented-out blocks. No unused imports.
* **Challenge my approach if it adds unnecessary complexity. I expect pushback.**
* **Do not affirm my statements blindly. Question assumptions, offer counterpoints.**
* **Proactively surface insights** — if you see a simpler path, a reuse opportunity, or a risk I haven't mentioned, say so before I ask. Use the `thinking-partner` skill.
* **For any non-trivial feature**: run the structured-workflow (discuss → plan → execute → verify). Don't jump to code.

## Commands
```bash
# Video Pipeline tests
cd skills/video-pipeline
python -m pytest tests/ -x                                    # Integration tests
python -m pytest script/brief_translator/tests/ -x            # Script tests
python -m pytest image_prompts/engine/tests/ -x               # Prompt engine tests
python -m pytest autopilot/tests/ -x                          # Autopilot tests
python -m pytest title_idea/curiosity_gap/tests/ -x           # Curiosity gap tests
python -m pytest render/audio_sync/tests/ -x                  # Audio sync tests
cd remotion-video && npm run typecheck                        # TypeScript check

# StoryEngine
cd storyengine/frontend && npx tsc --noEmit                   # Frontend type check
cd storyengine/frontend && npm run build                      # Frontend production build
cd storyengine/frontend && npm run dev                        # Frontend dev (port 3001)
cd storyengine/backend && python -m uvicorn main:app --reload --port 8001  # Backend dev
cd storyengine/backend && arq backend.worker.WorkerSettings                # arq queue worker (requires Redis)
```

## Key Reference Docs (auto-loaded — keep small)
* Common failure modes → @docs/failure-modes.md
* Cost breakdown → @docs/cost-awareness.md
* Environment variables → @docs/env-vars.md
* Image Prompt Engine → @docs/image-prompt-engine.md
* Remotion rendering → @docs/remotion-rendering.md
* Infrastructure & deployment → @docs/infrastructure.md

## Extended Reference (read on demand — NOT auto-loaded)
* Autopilot Brain design spec → docs/superpowers/specs/2026-03-18-autopilot-brain-design.md
* Airtable schema & field maps → docs/airtable-schema.md
* API integration patterns → docs/api-patterns.md
* Data architecture → docs/data-architecture.md
* Product roadmap → tasks/roadmap.md
* Completion reports → docs/reports/
* System reviews → docs/reviews/

## Core Principles
- **Thinking Partner First**: You are a co-creator, not a code executor. Before building, offer insights, challenge weak ideas, propose alternatives. Lead with the most interesting observation you have — never open with "Sure, I can do that."
- **Simplicity First**: Make every change as simple as possible.
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
- Minimal impact — change only what needs changing
- Ship incrementally — small, tested commits over big bangs

## Testing
780+ tests across 6 test suites. Run the relevant suite after every change. Never mark a task done until tests pass.

---

## Working Patterns

### 1. Plan Mode Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately

### 2. Subagent Strategy
- Use subagents liberally to keep main context window clean
- One task per subagent for focused execution
- **Model policy — brains vs hands (MANDATORY):** The premium session model (Fable/Opus tier) is for the main loop only — orchestration, architecture decisions, adversarial verification, and final synthesis/deliverables. ALL fan-out subagent work — codebase exploration, file reading, search sweeps, web research, mechanical edits — runs on **Sonnet**: pass `model: "sonnet"` on every Agent call, and `{model: 'sonnet'}` in workflow `agent()` opts. Only escalate a subagent to the premium model when that subtask itself demands deep reasoning (judging, complex verification, synthesis) — and say so when you do.

### 3. Self-Improvement Loop
- After ANY correction from the user: update `tasks/lessons.md` with the pattern
- **This is not optional.** Every correction not captured will be repeated.

### 4. Verification Before Done
- Never mark a task complete without proving it works
- **Trace the full execution path.** A function that exists but is never called is dead code.

### 5. Autonomous Bug Fixing
- When given a bug report: just fix it. Don't ask for hand-holding.
- Zero context switching required from the user.

### 6. Trace Before Touch (Complex Tasks)
- For ANY audit, fix, or multi-file change: run ALL diagnostic commands FIRST
- **Do NOT jump to fixing when given a multi-phase task.** Diagnose first.

## Task Management
1. **Plan First**: Write plan to `tasks/todo.md`
2. **Track Progress**: Mark items complete as you go
3. **Capture Lessons**: Update `tasks/lessons.md` after corrections
4. **Handoff**: Before session ends, write what's next

---

## ⚠️ MANDATORY WIRING AUDIT PROTOCOL

**This applies to EVERY task. No exceptions.**

### Before marking ANY task as complete, verify ALL of these:

**Entry Points:**
- How does this code get triggered? (orchestrator/pipeline.py flag? cron? Slack command?)
- Is the trigger ACTUALLY wired? (not just the module existing, but the caller invoking it)

**Data Flow:**
- Do Airtable field names in code EXACTLY match the real Airtable fields?
- Test one real Airtable read AND one real write — not mocks

**Integration:**
- Are new imports added to all files that call the new code?
- Do Slack notifications actually fire? Test live, don't assume.

**Smoke Test:**
- Run the actual command on VPS with real data
- Check Airtable for expected records
- Check Slack for expected messages

**Documentation:**
- Update CLAUDE.md if new CLI flags or Slack commands were added
- Update infra/setup_cron.sh if new cron jobs were added (AND run it to install)

### Common Failure Modes to Watch For:
- `Image Model Override` is a Multiple Select (returns list, not string)
- `Visual Style` is a Single Select (returns string)
- Airtable UNKNOWN_FIELD_NAME errors are silent — the write appears to succeed but drops the field
- Cron jobs written to setup_cron.sh are NOT automatically installed — must run `bash infra/setup_cron.sh`
- Slack commands in orchestrator/pipeline_control.py require both the command handler AND the import

---

## 🎯 StoryEngine Full-Stack Development Protocol

**Goal: One-shot shipping. Build it wired the first time. Debug less, ship faster.**

Inspired by [Anthropic's harness design](https://www.anthropic.com/engineering/harness-design-long-running-apps): separate planning from building from verification. Never self-evaluate — prove it works.

### The Rule

**Every StoryEngine feature touches 4 layers. All 4 must be wired in one pass:**

```
Database (schema.sql / migration)
    ↕ column names must match exactly
Backend (routes/*.py + models.py + main.py)
    ↕ response shape must match exactly
Frontend Types (lib/types.ts or inline)
    ↕ field names must match exactly
Frontend UI (components/*.tsx + pages/*.tsx)
```

**If you build a layer without wiring it to the layers above and below, you've created dead code.** This is the #1 source of bugs in this project.

### StoryEngine Architecture Reference

```
storyengine/
├── frontend/                   # Next.js 16 + React 19 + TypeScript
│   ├── src/app/                # App Router pages
│   ├── src/components/         # UI components (production/, video-detail/, ui/, autopilot/)
│   ├── src/hooks/              # Custom hooks (use-task-poller)
│   └── src/lib/                # api.ts (fetchApi wrapper), types, constants
│
├── backend/                    # FastAPI + asyncpg + Supabase PostgreSQL
│   ├── main.py                 # Route registration (14 routers)
│   ├── models.py               # Pydantic request/response models
│   ├── database.py             # Connection pool
│   ├── routes/                 # 14 route files
│   ├── pipeline_executor.py    # Background task orchestrator
│   └── migrations/             # SQL migration files
│
├── schema.sql                  # Canonical DB schema (source of truth)
└── MIGRATION_REPORT.md         # Migration history
```

**Key files to always check:**
- `backend/main.py` — Is the new router registered?
- `backend/models.py` — Does the Pydantic model match what the route returns?
- `frontend/src/lib/api.ts` — Does fetchApi call the right endpoint?
- `frontend/src/lib/types.ts` — Do TypeScript types match the backend response?

### Development Workflow (Plan → Build → Wire → Verify)

**EVERY StoryEngine feature follows this sequence. No exceptions.**

#### Step 1: TRACE (before writing any code)

Map the full wiring chain for the feature:
```
1. What DB table/columns are involved? Do they exist in schema.sql?
2. What backend route handles this? Is it registered in main.py?
3. What Pydantic model defines the request/response shape?
4. What frontend API call fetches/sends this data?
5. What component renders/submits this data?
6. What happens on error? Loading state? Empty state?
```

Write this trace as a comment before coding. If any layer is missing, build it.

#### Step 2: BUILD (bottom-up, one layer at a time)

Build in this order — each layer validated before moving up:

1. **Database** — Add migration if new columns needed. Verify column exists:
   ```sql
   SELECT column_name FROM information_schema.columns
   WHERE table_name = 'videos' AND column_name = 'new_field';
   ```

2. **Backend route** — Add/modify route. Verify:
   - Route registered in `main.py` (`app.include_router(...)`)
   - Pydantic model in `models.py` matches response shape
   - SQL query column names match schema.sql EXACTLY
   - Test with curl: `curl http://localhost:8001/api/endpoint`

3. **Frontend API** — Add fetch call. Verify:
   - Endpoint path matches backend route EXACTLY (including `/api/` prefix)
   - Request/response types match Pydantic model field names EXACTLY
   - Error handling exists (loading, error, empty states)

4. **Frontend UI** — Wire component to API data. Verify:
   - Component receives data from the API call (not hardcoded/mock)
   - Field names in JSX match the API response EXACTLY
   - User actions trigger the right API mutations
   - Loading/error/empty states render correctly

#### Step 3: VERIFY (prove it works end-to-end)

**Use `webapp-testing` skill (Playwright) to verify the running app.** This is NOT optional.

```bash
# Start both servers
cd storyengine/backend && python -m uvicorn main:app --reload --port 8001 &
cd storyengine/frontend && npm run dev &

# Then use Playwright to:
# 1. Navigate to the page
# 2. Verify data loads (no console errors, no empty states when data exists)
# 3. Test the user action (click, submit, etc.)
# 4. Verify the result (UI updates, no errors)
```

**Self-evaluation is unreliable.** "The code looks right" is not verification. Run the app, see the result.

### StoryEngine Wiring Checklist (before marking ANY feature complete)

```
□ DB column exists (not just in schema.sql — actually in Supabase)
□ Backend route registered in main.py
□ Backend route returns correct shape (curl test)
□ Pydantic model matches route response
□ Frontend fetchApi calls correct endpoint path
□ Frontend types match backend response field names
□ Component wired to real API data (not mock/hardcoded)
□ Loading state shows while fetching
□ Error state handles API failures
□ Empty state handles no data
□ TypeScript compiles: cd storyengine/frontend && npx tsc --noEmit
□ No console errors in browser (check via Playwright or manual)
```

### StoryEngine Commands

```bash
# Frontend
cd storyengine/frontend && npm run dev                    # Dev server (port 3001)
cd storyengine/frontend && npx tsc --noEmit               # Type check
cd storyengine/frontend && npm run build                   # Production build

# Backend
cd storyengine/backend && python -m uvicorn main:app --reload --port 8001  # Dev server

# Full-stack verification
# Use webapp-testing skill with Playwright for end-to-end checks
```

### Skill Integration For StoryEngine Work

When working on StoryEngine, skills trigger in this order:

| Phase | Skills to Invoke | What They Catch |
|-------|-----------------|-----------------|
| **Before coding** | `next-best-practices` (routes/pages), `react-best-practices` (components) | Wrong patterns, waterfalls, RSC boundary mistakes |
| **Component design** | `composition-patterns` (if 3+ props or reusable) | Boolean prop sprawl, missed compound component opportunities |
| **Database changes** | `supabase-postgres-best-practices` | Missing indexes, bad schema patterns, RLS issues |
| **After building** | `webapp-testing` (Playwright verification) | Broken wiring, console errors, missing states |
| **Before "done"** | `web-design-guidelines` (visual audit) | Design system violations, accessibility gaps |

### Common StoryEngine Wiring Failures

| Failure | How It Happens | Prevention |
|---------|---------------|------------|
| Route not registered | New file in routes/ but `app.include_router()` missing from main.py | Always check main.py after creating a route file |
| Field name mismatch | Backend returns `video_title`, frontend expects `title` | Copy field names from Pydantic model to TypeScript type — don't retype |
| Column doesn't exist | SQL references column from schema.sql that was never migrated | Run migration BEFORE writing route code |
| API path wrong | Frontend calls `/api/videos/detail` but route is `/api/videos/{id}` | curl the endpoint first, then copy the exact path |
| Stale React Query cache | Data updates but UI shows old data | Invalidate the right query key after mutations |
| Missing loading state | Component renders empty div while data loads | Always destructure `{ data, isLoading, error }` from useQuery |
| POST body shape wrong | Frontend sends `{ title: "..." }` but Pydantic expects `{ video_title: "..." }` | Match Pydantic model field names exactly in fetch body |
