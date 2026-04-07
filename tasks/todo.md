# Task Tracking

## Active: SaaS Transformation (2026-04-07)

**Master Plan:** `tasks/dailyjournal.md` — 18-day execution plan (revised from 20)
**Current:** Day 1 — Public `/pricing` page + plan enforcement middleware
**Key Correction:** Day 0 roadmap overestimated gaps. All 3 "broken" endpoints work. Billing UI exists in /settings. All 17 pages are real. Plan revised accordingly.

---

## Handoff — 2026-04-04 (backend-dev: Storyboard Extraction V2)

### Completed
- T27-001 (done by previous session): Supabase Storage bucket + upload helper (storage.py)
- T27-002: Grid cropping + panel extraction (extraction.py) — PIL-based, tested on real grids

### Next: T27-003 — Rewrite storyboard-extract endpoint for Supabase
This task wires extraction.py into the pipeline:
1. Read grid URLs from `scripts` table (storyboard_1_url, storyboard_2_url, storyboard_3_url)
2. For each grid, call `extract_grid()` from extraction.py
3. Clear existing `image_url` on assets before writing new panel URLs
4. Update `assets.image_url` with extracted panel URLs
5. Advance video status to `ready_for_images`

Key context:
- Current `run_storyboard_extract()` in pipeline_executor.py delegates to Airtable pipeline — silently does nothing for Supabase videos
- Rewrite to call extraction.py directly with database reads/writes
- Test video: f9749bd2 ("Drones"), has 6 scenes, tempfile URLs currently still alive (may expire)
- Grid layout is 3x2 (6 panels per grid), NOT 3x3

### Also pending
- T27-004: Re-generate storyboard grids (old URLs expired — but currently still alive)
- T27-005: Persist grid URLs to Supabase Storage after generation
- T27-008: Add permanent storage to ALL image gen steps

---

## Handoff — 2026-04-03 (Session 3)

### Next Session: Start Here

Read this handoff. The autonomous dev team is LIVE and operational. 6 agents, all on Opus, all on cron. The system works end-to-end: PRD → decompose → agents execute → test → learn.

### Immediate Priorities (build these first)

#### 1. Command Center Controls (UI)
Ryan needs full control over the team from the dashboard:

- **Master ON/OFF toggle** — one button to pause/resume ALL agents. When OFF, no agent runs (watcher stops, crons skip). When ON, everything resumes. Implementation: add `team_enabled: true/false` to controls.json. Watcher and run-agent.sh check this flag before proceeding.

- **Clear Task Queue button** — resets `storyengine/agents/task-queue.json` to empty. Shows confirmation modal "Are you sure? This clears all 128 tasks." Endpoint: `DELETE /api/task-queue`.

- **Clear PRD button** — already exists but should ALSO clear the focus directive in controls.json and reset the error tracker files. Currently only deletes prd.json/prd.md/progress.md.

- **Task counter reset** — The "128/128 tasks" in the sidebar should reflect the cleared state. Currently reads from task-queue.json.

#### 2. PRD → Task Queue Flow
When a PRD completes, its tasks should optionally flow into the permanent task queue for ongoing maintenance. Currently they're separate systems. Decision needed: should completed PRD work create follow-up maintenance tasks in the queue?

#### 3. Security Issues Follow-Up
6 security issues documented in the last PRD (SEC-1 through SEC-6). These need to become a new PRD or be added to the task queue:
- SEC-1 (CRITICAL): dev-token bypasses all auth in development mode
- SEC-2 (HIGH): get_scene_audio skips tenant check
- SEC-3 (HIGH): API keys revealed without rate limiting
- SEC-4 (HIGH): Hardcoded IP in CORS allowlist
- SEC-5 (MEDIUM): Dynamic SQL via f-strings
- SEC-6 (MEDIUM): No audit logging for key management

#### 4. Activity Feed Improvements
- Entries older than 24h should be grayed out or collapsed
- Add a "Clear feed" button
- The feed should auto-scroll to show newest entries (currently requires manual Refresh)
- Add WebSocket for real-time updates instead of polling

#### 5. Playwright Auth Fix
13 of 20 QA tests skip because they don't authenticate. The tests need the auth intercept pattern that QA already knows (intercept /api/auth/me). This should be a shared test fixture.

### What Was Built This Session (massive)

**PRD System (full pipeline):**
- Generate PRD button (Claude Opus from rough notes)
- Deploy to Team (decompose → focus → spawn immediately)
- Live decomposition UI (phase labels, pulsing bar, seconds counter)
- PRD watcher cron (every 60s, 3 jobs: PRD tasks, user errors, handoffs)
- Mission status reads from progress.md (not stale prd.json)

**Unified Agent System:**
- ONE runner (run-agent.sh) handles PRD + task queue + handoffs + errors
- Auto-detect PROJECT_ROOT (no more hardcoded paths)
- Completion check requires: queue empty + no PRD + no handoffs + no focus + no user errors
- Auto-restart servers after code commits
- Mandatory health check (frontend + backend) before exit
- Regression tests (Playwright) after commits
- Auto-spawn unblocked agents after PRD work

**6 Agents (all Opus):**
- Orchestrator, Backend Dev, Frontend Dev, QA Engineer, Pipeline Tester, Security Auditor
- All have: live activity posting, team collaboration (handoffs + spawn), cross-agent learning, real skills

**Autonomous Operations:**
- User clicks broken thing → error in activity log → watcher spawns agent within 60s
- Agent finds bug outside its role → handoffs to teammate + spawns them
- QA/Tester finds pattern → writes to responsible agent's memory
- Telegram message → handoff → agent spawns immediately

**First PRD Execution:**
- 14 tasks decomposed from rough voice notes
- All 14 completed (6 backend, 6 frontend, 1 QA, 1 security)
- Pipeline Tester caught 1 real bug
- 20 Playwright tests created
- 6 security issues documented

### Architecture (for next session's reference)

```
Command Center (RUBRIC :5050)
  → Generate PRD (Claude Opus)
  → Deploy to Team (decompose → spawn)
  → Mission progress (poll progress.md)
  → Team Status (agent-status.json)
  → Activity Feed (activity-log.json)

Watcher (cron every 60s — agents/prd-watcher.sh)
  → Job 1: PRD unblocked tasks → spawn agents
  → Job 2: User-browser errors → spawn backend/frontend
  → Job 3: Unaddressed handoffs → spawn receiving agent

Agent Runner (storyengine/agents/run-agent.sh)
  → Check: handoffs? focus? user errors? PRD tasks? task queue?
  → Work on highest priority source
  → Post to activity feed during work
  → Cross-agent learning on bug patterns
  → Restart servers if code changed
  → Run regression tests
  → Health check before exit
  → Auto-spawn newly-unblocked agents

Cron Schedule:
  Every hour :00  — Backend Dev
  Every hour :02  — Frontend Dev
  Every hour :04  — QA Engineer
  Every 3 hours   — Pipeline Tester
  Every 6 hours   — Security Auditor
  Daily 5 AM      — Orchestrator (grand audit)
  Every minute    — PRD Watcher
```

### VPS State
- RUBRIC: http://76.13.119.181:5050
- StoryEngine: http://76.13.119.181:3001
- Backend: port 8001
- Telegram: tmux session `telegram-channel` (Haiku)
- All crons installed
- Branch: agent-dev

---

## Previous Handoff — 2026-04-03 (Session 2)

### What Was Built This Session

**PRD Auto-Generation + Deploy Pipeline:**
1. ✅ "Generate PRD" button — type rough notes → Claude Opus generates structured PRD
2. ✅ "Deploy to Team" — decomposes → sets focus → spawns agents immediately (no cron wait)
3. ✅ POST /api/spawn-agent — run any agent instantly via HTTP
4. ✅ POST /api/generate-prd — async with polling, seconds counter, 10min timeout
5. ✅ Wrapper script (`agents/generate-prd.sh`) avoids exec/spawn Node.js issues

**Unified Agent System (one system, not two):**
6. ✅ `run-agent.sh` now handles BOTH PRD tasks and task-queue work (checks agents/prd.json at startup)
7. ✅ `dispatch.sh` simplified to thin wrapper
8. ✅ `run-team.sh` still works but deploy-prd and spawn-agent both call run-agent.sh now
9. ✅ PRD tasks count toward agent XP/leveling (calculate-skills.sh updated)
10. ✅ Fixed PROJECT_ROOT hardcoded Mac path → auto-detects from script location

**Agent Upgrades:**
11. ✅ Pipeline Tester upgraded to Opus with aggressive browser-first testing
12. ✅ QA Engineer upgraded to Opus
13. ✅ Security Auditor — NEW agent (Opus, every 6h) for auth, injection, data exposure, CORS
14. ✅ All agents: skills fixed — only real skills referenced, Skill tool invocation instructions
15. ✅ All agents: skills visible on Team tab UI (parsed from .md files)

**Autonomous Operations:**
16. ✅ PRD watcher cron (every 60s) — auto-spawns agents when PRD tasks become unblocked
17. ✅ Error watcher — user-browser 404/405 errors auto-spawn backend/frontend agents within 60s
18. ✅ Error-driven task creation — user-browser errors auto-create BUG-USER tasks in queue
19. ✅ Auto-restart servers after agent commits (backend uvicorn, frontend next build+start)
20. ✅ Mandatory health check — every agent checks frontend+backend before exiting, auto-restarts if down
21. ✅ Regression prevention — Playwright tests run after every agent commit

**Team Collaboration:**
22. ✅ All agents can POST handoffs + spawn teammates when stuck
23. ✅ Cross-agent learning — QA/Tester write bug patterns into responsible agent's memory
24. ✅ Live activity posting — agents POST to activity feed during work (start, complete, error)
25. ✅ User-browser errors shown at TOP of every agent's prompt as #1 priority

**Live Decomposition UI:**
26. ✅ Pulsing progress bar during PRD decomposition
27. ✅ Phase labels ("Reading PRD... (45s)" → "Creating tasks... (120s)")
28. ✅ Mission status reads from progress.md (not stale prd.json)

**PRD Execution Results (first real test):**
- 14 tasks decomposed from user's rough notes
- 13/14 completed (6 backend, 6 frontend, 1 QA)
- T14 (security) remaining — now has dedicated Security Auditor agent
- 1 bug found by Pipeline Tester (Profile API 404)
- 20 Playwright tests created by QA

### Current Agent Team (6 agents)

| Agent | Model | Schedule | Role |
|-------|-------|----------|------|
| Orchestrator | Opus/Sonnet | Daily 5 AM | Plans work, audits progress |
| Backend Dev | Opus | Hourly :00 | FastAPI, DB, business logic |
| Frontend Dev | Opus | Hourly :02 | React, TypeScript, UI |
| QA Engineer | Opus | Hourly :04 | Verification, Playwright |
| Pipeline Tester | Opus | Every 3h | Click-through testing, bug filing |
| Security Auditor | Opus | Every 6h | Auth, injection, CORS, secrets |

### What Needs Attention Next

1. ~~**User-browser errors still live**~~ — FIXED. Both 404 on `/api/user/preferences` and 405 on DELETE were stale server issues (already resolved by server restart).

2. ~~**Image generation broken**~~ — FIXED (commit 013963a). Three bugs: (a) LightPipeline missing `_filter_by_scene`, `_is_targeted_run`, `_log_filters`, `_update_status` methods. (b) Status case mismatch: DB stores lowercase but pipeline bots expect capitalized. (c) Targeted runs (single image) triggered retry loop that generated ALL images. All three fixed.

3. **Activity feed needs verification** — live posting instructions added to all agents but not yet tested in a real agent run. Next agent session should produce real-time activity entries.

4. **Security audit T14** — the Security Auditor agent exists but hasn't run yet. Will run on next 6h cron or can be manually spawned.

5. ~~**Delete button broken**~~ — FIXED. Was stale server issue, now works correctly.

5. **Tier 2 product ideas not yet built:**
   - Cost dashboard (track Claude API cost per agent)
   - Agent reputation scores (beyond levels)
   - Visual diff reviews (before/after screenshots in Activity)
   - Telegram command expansion
   - SLA tracking (mean time to resolution)

### VPS State
- RUBRIC: http://76.13.119.181:5050 (Command Center is landing page)
- StoryEngine: http://76.13.119.181:3001
- Backend: port 8001
- Telegram: tmux session `telegram-channel` (Haiku)
- All crons installed including PRD watcher + security auditor + pipeline tester
- Branch: agent-dev

---

## Previous Handoff — 2026-04-03 (Session 1)

### The Vision (Ryan's words — do not lose this)

"I need a fully autonomous dev team that helps me build whatever I want. I want to be able to speak into Telegram or text into Telegram, detail out what I'm seeing, what's not working, and then that goes to the teams. They know exactly where to target, where to build, and they execute to fix everything in real time. They don't need to wait for the cron job. If I make a directive, they just get after it."

"The tester is the most important agent next to the orchestrator. If Claude is just building blindly, no wonder why I don't have a complete system. The tester must be the most expert. His eyes flow the problems down to the dev team to fix."

"I want one line of communication — I send from Telegram, the bot messages the team with instructions that take top priority, all other work gets queued until the problem gets fixed."

### What Was Built This Session (2026-04-02 → 2026-04-03)

**Completed:**
1. ✅ Real skills wired to Team page + Skill Trees (7 skills from `.claude/skills/`)
2. ✅ Edit Instructions button on agent cards (reads/writes agent .md files via modal editor)
3. ✅ Focus Directive vs Messages clarified (PERSISTENT vs ONE-TIME badges, visual distinction)
4. ✅ V5 → main PR created (#337, 113 commits, ~10K lines)
5. ✅ Fixed agent crashes (exit code 126) — prompt piped via stdin to avoid ARG_MAX
6. ✅ Added turbo (96x/day) and ultra (180x/day) cadence levels
7. ✅ Fixed cron Next Up showing wrong countdown for high-freq schedules
8. ✅ Operator messages now override task queue (focus directive moved AFTER task queue in prompt)
9. ✅ Telegram system prompt updated to ALWAYS set focus directive on operator messages
10. ✅ VPS main branch synced to origin/main
11. ✅ **Portable autonomous dev team template** (`agents/` directory):
    - 5 roles: lead, backend, frontend, qa, security (`agents/roles/*.md`)
    - `decompose.sh`: PRD → prd.json with machine-verifiable acceptance criteria
    - `run-team.sh`: iterative agent loop (implement → test → commit → next)
    - `verify.sh`: quality gates (tsc, tests, lint) as Claude Code Stop hook
    - `TEAM.md`: project-level config (stack, commands, rules)
    - PRD template + acceptance criteria writing guide
12. ✅ **Command Center** (replaced Welcome tab):
    - Mission Brief: textarea to paste PRD + "Deploy to Team" button
    - Agent Proposals: approve/reject feature requests inline
    - Team Status: agent dots + focus directive banner
    - APIs: POST /api/deploy-prd, GET /api/mission-status, DELETE /api/mission
13. ✅ Agent role .md files editable from RUBRIC Team tab (portable section with "Edit Instructions")

### What Needs to Be Done Next (PRIORITY ORDER)

#### Priority 1: Wire "Deploy to Team" End-to-End
The Command Center UI exists but clicking "Deploy to Team" does NOT spawn agents. It only writes files and waits for cron.

**What needs to happen:**
1. After `decompose.sh` finishes → set focus directive automatically ("PRD deployed: [title]")
2. After focus directive set → immediately spawn agents via `run-team.sh` in background (not wait for cron)
3. Stream agent status back to Command Center (poll `/api/mission-status`)
4. When all tasks done → orchestrator clears focus directive, Command Center shows "Mission Complete"

**Files:**
- `rubric/scaffold/server.js` — `POST /api/deploy-prd` endpoint needs to chain: decompose → set focus → spawn agents
- `agents/run-team.sh` — needs to work on VPS (currently `CLAUDE_BIN` may not be in PATH)
- Need a new `POST /api/spawn-agent` endpoint that runs `run-team.sh <role>` in background

#### Priority 2: Telegram Instant Execution (no cron wait)
Ryan's single line of communication: text Telegram → agents execute immediately.

**Current flow (broken):**
1. Ryan texts Telegram → bot sets focus directive + sends feedback
2. Agents only see it on next cron cycle (every 15 min)
3. Agents may ignore it if orchestrator already assigned other tasks

**Desired flow:**
1. Ryan texts Telegram → bot sets focus directive
2. Bot ALSO spawns agents immediately via `POST /api/spawn-agent` (or SSH to run `run-team.sh`)
3. Agents start working within seconds, not 15 minutes
4. Progress streams back to Telegram ("Backend Dev started... fixed endpoint... committed")

**Implementation:**
- Update `rubric/scaffold/telegram-system-prompt.md` — after setting focus, bot should call `/api/spawn-agent` for each relevant role
- Add `POST /api/spawn-agent` to `rubric/scaffold/server.js` — runs `run-team.sh <role>` or `run-agent.sh <agent>` in background via `exec()`
- The Telegram bot (running as Haiku in tmux `telegram-channel`) needs its system prompt updated
- Consider: should Telegram bot use `run-team.sh` (new PRD system) or `run-agent.sh` (existing StoryEngine system)? Answer: depends on context. If it's a PRD → `run-team.sh`. If it's a bug fix on StoryEngine → `run-agent.sh` with focus override.

#### Priority 3: Pipeline Tester / QA Agent Upgrade
The Pipeline Tester is Level 1 Novice with 0 tasks done. Ryan says: "That guy must be the most expert person. His eyes flow the problems down to the dev team to fix."

**Current problems:**
- `pipeline-tester.md` runs quick Playwright scripts but doesn't do real click-throughs
- QA Engineer (`qa-engineer.md`) does tsc checks but not browser testing
- Neither agent actually opens the app and navigates like a user
- Both are passive (wait for task queue) instead of proactive (find bugs autonomously)

**What needs to change:**
- Pipeline Tester should be the **primary bug-finder**: opens every page, clicks every button, files bugs
- QA Engineer should be the **verifier**: after devs fix a bug, QA confirms the fix works
- Both need aggressive Playwright instructions: start servers, navigate to every route, test forms, check console errors
- Pipeline Tester's cron should run AFTER frontend-dev and backend-dev (currently at :10/:25/:40/:55 — good timing)
- The tester needs to POST bugs as handoffs to the responsible agent with specific reproduction steps
- Tester should be upgraded from Sonnet to Opus model (it's doing the hardest job)

**Files to update:**
- `storyengine/agents/pipeline-tester.md` — rewrite to be aggressive browser-first tester
- `storyengine/agents/qa-engineer.md` — rewrite as verification-focused, not just tsc
- `storyengine/agents/run-agent.sh` — pipeline-tester should use Opus (line 131: currently Sonnet)

#### Priority 4: Bridge Old System ↔ New System
Two agent systems exist now:
1. `storyengine/agents/run-agent.sh` + `task-queue.json` (StoryEngine-specific, 95 tasks, cron-driven)
2. `agents/run-team.sh` + `prd.json` (portable, PRD-driven, iterative loop)

They need to coexist. When:
- **No PRD deployed + no focus directive** → agents use `run-agent.sh` (current behavior, StoryEngine tasks)
- **PRD deployed via Command Center** → agents use `run-team.sh` (new system)
- **Focus directive from Telegram** → agents use `run-agent.sh` but in focus mode (override task queue)

**Implementation:** The cron entries currently call `run-agent.sh`. Add a wrapper script `agents/dispatch.sh` that checks:
1. Is there a `prd.json`? → run `run-team.sh <role>`
2. Is there a focus directive? → run `run-agent.sh <agent>` (which already has focus override)
3. Neither? → run `run-agent.sh <agent>` (normal task queue)

### VPS State (2026-04-03)
- RUBRIC: http://76.13.119.181:5050 (agent-dev, Command Center is landing page)
- StoryEngine: http://76.13.119.181:3001 (frontend on agent-dev)
- Backend: port 8001 (agent-dev)
- Telegram: tmux session `telegram-channel` (Haiku)
- Cadence: **turbo 96x/day** (every 15 min), crons installed
- Branch: agent-dev (VPS tracks origin/agent-dev)

**Config locations (THE source of truth):**
- `storyengine/.env` — DATABASE_URL, DEV_TENANT_ID, SESSION_SECRET
- `storyengine/frontend/.env.local` — NEXT_PUBLIC_GOOGLE_CLIENT_ID
- `~/.claude/channels/telegram/.env` — TELEGRAM_BOT_TOKEN
- Ryan's tenant: `f6839de2-368c-440d-8559-0292026179fa`
- Auth: ryan.ayler@gmail.com / testtest1

**Key principles from Ryan:**
- "The bots are not going to design themselves. We design the agents, and they work according to our design."
- "One line of communication — Telegram to the team, top priority, no waiting."
- "The tester is the eyes. Without it, agents build blind."
- "I want to pick up this dev team and plop it wherever. Give it a PRD, it ships."

---

## Completed: Pipeline Reorganization (2026-03-24)

Full codebase reorganization of `skills/video-pipeline/`. Each tool is now a standalone folder with its own manifest.json. Agent quality pipeline added (hook/body/CTA with iterative scoring).

## StoryEngine SaaS UI — Current State (2026-03-24)

### Completed Modules

**Module 0: Supabase Migration Verification** ✅
- 51 columns added across 5 tables, 5 schema bugs fixed
- Migrations: 004 (schema parity), 005 (agent + suggestion columns), 006 (niche columns)
- All migrations applied to live Supabase

**Module 1: Design System + Dashboard + Pipeline** ✅
- Dark editorial design tokens (charcoal #0A0A0B, amber #D4A844, teal #1A8A7A)
- 6-tab mobile bottom bar, 7-item collapsible desktop sidebar
- Dashboard: action-first (approvals, activity, stats)
- Pipeline: dropdown filters, search, progress dot cards

**Module 2: Video Detail (5 tabs) + Create** ✅
- `/pipeline/[videoId]` — Info, Script, Visuals, Thumbnail, Performance tabs (Board merged into Visuals)
- `/create` — New video form (title, angle, thesis + advanced options)

**Module 4: Autopilot + Analytics + Agent Suggestions** ✅
- `/analytics` — CTR bar chart (Recharts), revenue estimates, per-video cards
- `/autopilot` — Restyled, agent quality stats, top 3 recommendations
- Suggestion system: suggested_script/title/thumbnail with accept/reject
- Script diff UI, thumbnail variant visual UI

**Module 5: Niche Selection + Topic Discovery** ✅
- `/competitors` — Playing card grid with YouTube thumbnails, VPH, confidence
- Channel filter pills + dropdown
- Card expanded modal (theirs vs yours + thumbnail workshop)
- Thumbnail workshop with prompt iteration carousel
- Niche setup wizard (category → sub-niche → channels)
- `/autopilot` simplified to top 3 decision maker with "View All →" link

**Module 3: Interactive Features** ✅
- Script tab: inline text editing, tone dropdown, per-scene voice generation, collapsible sentence segments
- Visuals tab: storyboard mode toggle (ON: grids side-by-side with magnified CSS panel viewer + VO, OFF: direct image generation cards)
- Per-tab pipeline advancement via StageAdvancer (calls specific stage endpoints, not generic advance)
- Background task polling (useTaskPoller hook)
- Tab consolidation: 6→5 tabs (storyboard merged into visuals)
- Thumbnail tab: "Approve → Render" advancement
- Competitor channel URL input bar on `/competitors`
- Backend: 5 new scene endpoints, expanded script query, targeted voice/image regen with status gate bypass
- Migration 007: tone column on scripts

### Not Yet Built

**Future Modules:**
- Channel onboarding + baseline learning (import existing YouTube data)
- Batch topic selection / "Queue All"
- Calendar production view
- Settings page (Channel Profile, API keys, pipeline config)
- Multi-tenant architecture
- Billing & subscriptions

---

## Handoff Notes

**VPS Info:**
- SSH: `ssh clawd@76.13.119.181` (password: Economyfastforward)
- Frontend: `http://76.13.119.181:3001` (Next.js, port 3001)
- Backend: `http://76.13.119.181:8001` (FastAPI, port 8001)
- Auto-deploy cron: every 5 min pulls git + rebuilds frontend

**Key specs:**
- UI/UX spec: `docs/superpowers/specs/2026-03-23-storyengine-ui-ux-addendum.md`
- Module 5 spec: `docs/superpowers/specs/2026-03-24-module5-niche-discovery-design.md`

**Architecture decisions:**
- Agent pipeline is the PRIMARY script generation path (not a polish layer)
- Brief translator is legacy (VPS cron pipeline)
- Supabase is single source of truth, Airtable data imported
- Suggestions stored as proposed overwrites (human approves inline)
- Autopilot = decision maker (top 3), Competitors = research/browse (all cards)

## Current: Airtable → Supabase Pipeline Wiring (2026-03-26)

**Plan:** `~/.claude/plans/snappy-launching-lantern.md`

**Done:**
- SupabaseAdapter created (`storyengine/backend/supabase_adapter.py`) — 42 sync psycopg2 methods mirroring AirtableClient
- Adapter wired into PipelineExecutor (replaces `pipeline.airtable`)
- Status gates fixed to use `is_at_or_past_stage()`
- psycopg2-binary installed on VPS, deployed
- **✅ Pipeline initialization unblocked** (2026-03-26): LightPipeline replaces VideoPipeline. No full pipeline import needed.
- **✅ Script generation works end-to-end** (2026-03-26): "Generate Script" button → 6 scenes created → status → Ready For Voice
  - Fixed: `airtable_record_id` lookup → direct Supabase UUID lookup (all 13 `run_*` methods)
  - Fixed: `VideoConfig(target_minutes=...)` → `VideoConfig(video_length_minutes=...)`
  - Fixed: Bot subdirs (script/, voice/, etc.) added to sys.path for internal imports
  - Fixed: NoOpSlack/NoOpGoogle with `__getattr__` for safe fallback
  - Fixed: `_update_status()`, `image_filter`, `scene_filter` added to LightPipeline
  - Fixed: `update_idea_fields` returns written fields for verification checks
  - Fixed: Research agent import path (`research.agent` not `research_agent`)

**Missing clients (non-blocking for now):**
- GoogleClient: OAuth credentials not on VPS → Drive folders skip, Google Docs skip
- SlackClient: No SLACK_BOT_TOKEN on VPS → notifications skip
- ElevenLabsClient: No WAVESPEED_API_KEY → voice generation will fail

**Pipeline E2E Test Results (2026-03-31):**
- ✅ Research: 20-field payload generated (Claude API)
- ✅ Script: 15,781 char 6-act script (Claude API, blocked by validation but script saved)
- ✅ Split: 117 sentence segments across 6 scenes (pure Python, no API)
- ✅ Image Prompts: 117 cinematic prompts generated (Claude API)
- ⏭️ Voice: SKIPPED (no ElevenLabs key — mock durations set for testing)
- 🔜 Image Generation: Ready (Kie.ai key available, ~$3 cost)
- 🔜 Remaining: Video Scripts, Video Gen, Sound, Thumbnail, Render, Upload

**Fixes applied:**
- `pipeline_executor.py`: Added `title_idea` to sys.path for research imports
- Migration 013: 9 missing columns across 3 tables
- `AnthropicClient` made optional (try/except) in pipeline init
- Python deps installed: pyairtable, google-auth, google-api-python-client, slack_sdk, mutagen, anthropic, psycopg2-binary

**Next steps:**
1. ⚠️ Run migration 013 on production Supabase (required before VPS pipeline works)
2. Add ElevenLabs API key to vault for voice generation
3. Test image generation step (Kie.ai, $3 cost)
4. Test remaining pipeline steps (video scripts → render)
5. Add Google OAuth + Slack credentials for full pipeline
6. Fix frontend wiring: 4 mock pages, 7 dead buttons, 17 orphan API functions (see docs/reports/WIRING_STATUS.md)

---

## Session: Storyboard & Visuals Tab Redesign + Pipeline UX (2026-04-01)

### Completed
- **Fixed VPS deployment**: stale build chunks causing "This page couldn't load" — server was loading old manifests. Created `infra/storyengine_deploy.sh` auto-deploy cron (every 30 min).
- **Unified Storyboard & Visuals tab**: grids first (340x200, click-to-expand), per-scene VoicePlayer, collapsed narration + image segments.
- **Script tab → Script only**: removed audio transport bar/playback, kept voice generation buttons + status badges.
- **Pipeline steppers**: Both Script and Storyboard tabs now have visual 1-2-3 step indicators with CTA buttons.
- **Script auto-split**: sentences auto-split after script generation completes. "Split Sentences" button removed.
- **"Generate Image Prompts" moved**: from Script tab to Storyboard tab (where it belongs as Step 1).
- **Click to Generate on pending grids**: clickable placeholders instead of passive "Pending" label.
- **Dynamic grid sizing**: storyboard bot now generates right-sized grids (1x2 for 2 panels, etc.) instead of always 3x3.
- **Fixed storyboard skip bug**: `run_images.py` was checking only first scene's status — now checks ALL beats.
- **Fixed status gate**: relaxed `storyboard-images` endpoint from `ready_for_storyboard_images` to `ready_for_image_prompts`.
- **Image prompt guard**: storyboard prompt generation blocked if <50% segments have image prompts.

### Completed (2026-04-01 Session 2)
- **Per-scene storyboard generation**: Backend accepts `?scene=N` query param on both `storyboards` and `storyboard-images` endpoints. Per-scene bypasses status gate. Frontend has per-scene "Gen Prompts", "Gen Grids", "Clear", and "Regenerate" buttons on each scene card.
- **Live progress indicators**: Bot reports "Generating Scene 2/6, Beat 1/3..." via `progress_callback`. Messages flow through task poller to UI in real-time. Purple progress banner shows under storyboard pipeline section.
- **Storyboard status badges**: Each scene card shows its `storyboard_status` (prompts_ready, grids_generated, partial_1_of_2, etc.)
- **Clear old grids**: Per-scene "Clear" button and global "Clear All Storyboards" button wired end-to-end.
- **Grid placeholder click → per-scene**: Clicking empty grid generates grids for THAT scene only (not all scenes).
- **Deploy script race condition fixed**: Root cause was Next.js loading chunk manifest into memory at startup. Old server process lingers after `pkill`, serving HTML referencing old chunk hashes that no longer exist. Fix: SIGTERM → 5s wait → SIGKILL → `fuser -k 3001/tcp` → verify port free → build → start.
- **Tested live**: Per-scene grid generation works end-to-end (Scene 1 Beat 1/2 generated successfully via API, visible in UI).

### In Progress / Next Session
1. Backend needs automatic restart on deploy (currently manual restart required for Python changes)
2. Scene 6 has no storyboard prompts — need to generate prompts before grids
3. Some scenes show `grids_generated` status but have no actual grids (stale status from previous run without scene_filter)

---

## SaaS Transformation Roadmap (2026-04-02)

**Master plan:** `tasks/roadmap.md`

### Phase 0: Foundation (Auth + Onboarding) — NEXT
- [ ] Supabase Auth integration (login/signup/password reset)
- [ ] Auth middleware on all backend routes
- [ ] Login/Signup pages (frontend)
- [ ] Onboarding wizard (4 steps: channel → YouTube → competitors → style)
- [ ] Protected routes (redirect unauthenticated → login)
- [ ] Plan selection page

### Phase 1: Core Product Polish — AFTER Phase 0
- [ ] Dashboard redesign (action-first)
- [ ] Simplified create video flow (3 clicks)
- [ ] Real-time pipeline progress UX
- [ ] Video preview player
- [ ] In-app notifications
- [ ] Settings page completion
- [ ] Empty states + error states

### Phase 2-5: See tasks/roadmap.md for full roadmap

---

## Completed: Cinematic Continuity Contact Sheets (2026-04-01)

Restructured storyboard directive system prompt to produce structured contact sheet prompts that generate visually continuous 3×3 grids. Tested with Gemini — father character consistent across panels, strait geography consistent across 5 panels, data screens share visual language.

**Changes (all in `storyboard/bot.py`):**
1. **Rules 7-8 added** to `<non_negotiable_rules>`: continuity threading (character position, setting locks, visual bridges) + narration-visual alignment (panels must show what narration says)
2. **Contact sheet prompt format restructured**: Preamble with character/setting locks → per-panel descriptions with Kelvin color temps, focal lengths, frame positions, gaze direction → technical footer. Replaces the old freeform format.
3. **Cross-beat state passing**: `prev_beat_exit` dict tracks last keyframe's shot type, composition, and lighting. Injected into next beat's user prompt as `PREVIOUS BEAT EXIT` context block. Wired through `_build_directive_user_prompt()` → `generate_storyboard_directive()` → beat loop.
4. `build_image_prompt_from_keyframe()` already included lighting (no change needed).

**Next:**
- Test on a real video with storyboard generation
- Consider switching contact sheet model from Nano Banana Pro to Gemini (produced much better results in manual testing)

---

## Completed: Page-by-Page UI/UX Overhaul (2026-03-26)

**Branch:** `claude/page-fixes-round1` (pushed, not merged)
**Completion Report:** `docs/reports/COMPLETION_REPORT_D.md`

All 6 sections done:
1. Tab restructure (9→8 tabs, 6-step labeled stepper)
2. ScriptVoiceTab — combined script editing + inline voice per scene
3. StoryboardVisualsTab — voice guard rail + visuals workflow
4. Approval gates — Run Next Step stops at checkpoints
5. Pipeline integrity — voice required before image generation
6. Bug fixes — analytics crash, thumbnails, Gemini retry, character persistence

30/30 checklist items PASS. TypeScript compiles clean.

**Dev tools built:**
- Voice Typer: `~/whisper-dictation/` (Fn key dictation, auto-starts on login)
- Browser Watcher: `~/browser-watcher/watcher.py` (Playwright monitoring)
- Chrome Extension: `~/browser-watcher/extension/` (session recorder with voice + screenshots)
- Session Server: `~/browser-watcher/session_server.py` (bundles sessions → Claude CLI)
- Auto-deploy: `~/browser-watcher/deploy.sh` (commit → push → VPS pull + restart)
