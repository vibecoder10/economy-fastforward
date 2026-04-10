# Task Tracking

## Active Work

**Execution Plan:** `tasks/roadmap.md` — 18-day SaaS transformation
**Current:** Day 2 of 18 (2026-04-08). PRD 2 backend tasks ALL complete (7/7, committed).
**Agent Team:** 6 agents on Opus, PRD 2 in progress. Backend done, frontend next.

## Handoff
**Pipeline Tester (2026-04-10):** PRD2 T1-T11 all verified via acceptance criteria + Playwright. Fixed route ordering bug in settings.py (POST /keys/validate caught by /keys/{key_name} — commit 4057fb1). Auth 401 on /login NOT A BUG (stale RUBRIC entries from before 380178b).

**PRD 2 status:** 11/13 done. T12 (QA Playwright regression) and T13 (already done by qa-engineer) are the only remaining items. T12 dependencies now all met.

**PRD 4 COMPLETE** — All 15/15 tasks done.

**Still open:** 3 SEC bugs in task queue (SEC-SSE-001 cross-tenant SSE, SEC-EMAIL-001 HTML injection, SEC-KEYS-001 exception leak). These are for backend-dev.

Previous handoff (PRD 2):
All 7 PRD 2 backend tasks are committed and passing acceptance criteria:
- Task 1: Migration 029 (trial_warning_sent column)
- Task 2: Query-param token auth in auth.py for SSE connections
- Task 3: SSE stage_change events (already existed)
- Task 4: POST /keys/validate bulk API key testing with timeout
- Task 5: email_service.py shared email module + email.py stub
- Task 6: Billing receipt email on checkout (already wired)
- Task 7: email_tasks.py trial warning system (already created)
Frontend tasks 8-12 are now unblocked. Task queue is empty.

### What Shipped Today (2026-04-08)
- Billing page (`/billing`) with plan comparison, usage bars, Stripe integration
- Critical Bug Fixes PRD: all 14 tasks (6 backend, 6 frontend, 1 QA, 1 security)
- Competitors page refactored (server-side pagination, filters, sort, scrape progress)
- Error boundaries + 404 page
- Toast notification system (replaced 81 alert() calls)
- System prompt editors on pipeline tabs
- Trial countdown badge + banner
- REG24 regression sweep: 24/24 pages, 33/33 API, 9/9 tabs — 0 bugs
- UX Polish PRD backend tasks: render_minutes tracking, suggest-titles endpoint, welcome email

### Next Up (from roadmap Day 3-5)
- [ ] Plan enforcement: `tenant_usage` table, `check_plan_limits()` middleware, usage hooks
- [ ] Free trial logic: 14-day Creator trial on signup, countdown, downgrade-on-expiry
- [ ] Password reset flow: token table, email (Resend), `/reset-password` page
- [ ] Disable dev-token in production mode
- [x] Create video simplification: POST /api/videos/suggest-titles endpoint built
- [ ] Frontend: wire suggest-titles into create video flow (PRD Task 8)

---

## Blocked / Pending

### Storyboard Extraction V2 (from 2026-04-04)
- **T27-003**: Rewrite storyboard-extract endpoint for Supabase
  - Wire `extraction.py` into `pipeline_executor.py` (currently silently does nothing for Supabase videos)
  - Read grid URLs from `scripts` table → call `extract_grid()` → update `assets.image_url`
  - Grid layout is 3x2 (6 panels per grid), NOT 3x3
  - Test video: f9749bd2 ("Drones"), 6 scenes
- **T27-004/005/008**: Permanent storage for all image gen steps (Supabase Storage)

### Security Issues (from Critical Bug Fixes PRD)
- SEC-1 (CRITICAL): dev-token bypasses all auth in dev mode
- SEC-2 (HIGH): get_scene_audio skips tenant check
- SEC-3 (HIGH): API keys revealed without rate limiting
- SEC-4 (HIGH): Hardcoded IP in CORS allowlist
- SEC-5 (MEDIUM): Dynamic SQL via f-strings
- SEC-6 (MEDIUM): No audit logging for key management

### Rubric / Agent Team Improvements
- [x] Cron health audit: crons.json synced with setCadence, security-auditor wired, health checks fixed
- [x] Cadence buttons: all 6 tiers (light/normal/fast/max/turbo/ultra) now sync crontab + crons.json + UI labels
- [x] Feature 1: Concurrency guard — PID lock file + stale lock cleanup in run-agent.sh
- [x] Feature 2: Run timeout — `timeout` command wrapping Claude CLI (30min default)
- [x] Feature 3: Duration + cost tracking — timing, cost heuristic, model in activity log
- [x] Feature 4: Log viewer — `/api/logs` + `/api/logs/:agent` endpoints, dashboard modal with auto-refresh
- [x] Feature 5: Crons-controls sync — grayed out paused/OFF jobs, "Team OFF" badges
- [x] Feature 6: Runtime visualization — `/api/run-history` endpoint, calendar overlay (green/red/amber bars), Scheduled/Actual/Both toggle
- [x] Feature 7: Dashboard notifications — toast alerts polling activity log, auto-dismiss
- [x] Feature 8: Cost summary panel — `/api/cost-summary` endpoint, 24h/7d/30d cards + per-agent bar chart
- Command Center: Master ON/OFF toggle, clear queue button, task counter reset
- Activity feed: auto-scroll, WebSocket for real-time, collapse old entries
- Playwright auth fix: 13/20 QA tests skip (need shared auth intercept fixture)

---

## Latest Handoff (2026-04-08)

**What completed (PRD 2 backend):**
- Task 1: Migration 029 (trial_warning_sent column) — already existed
- Task 2: Query-param token auth for SSE — already existed
- Task 3: SSE stage_change events in /api/activity/stream — NEW: polls stage_transitions table, emits `event: stage_change` alongside `event: activity`
- Task 4: POST /api/settings/keys/validate — already existed
- Task 5: email_service.py extracted from google_auth.py — already existed (named email_service.py not email.py to avoid stdlib shadow)
- Task 6: Billing receipt email on checkout.session.completed — NEW: sends receipt via email_service after Stripe checkout
- Task 7: email_tasks.py with check_trial_warnings() — NEW: finds accounts with trial expiring in 3 days, sends warning, sets trial_warning_sent flag

**Frontend tasks UNBLOCKED:** 8, 9, 12 (depend on task 3), 11 (depends on task 4)
**QA task 14** depends on all other tasks

**Key context for next session:**
- `tasks/roadmap.md` has the full 18-day plan with daily deliverables
- `tasks/decisions.md` has settled architectural choices (10 ADRs)
- email_tasks.py needs to be wired into a background loop in main.py lifespan (not done yet — task 7 only creates the module)

Previous handoffs archived in `tasks/archive/handoffs-2026-03-to-04.md`

## Handoff (2026-04-10 — QA verification + security audit)
PRD2 Pipeline UX: 12/14 done+verified. T12 (full regression) blocked on T3/T4/T7/T10.
- BUG-USER-800807 confirmed fixed (380178b) — backend returns "Invalid or expired session", frontend suppresses auth 401s from RUBRIC
- T9 verified: trial warning wired in main.py lifespan (12h interval), email_tasks.py + migration 029 present
- T2 verified: SSE hook matches backend event shapes exactly (stage_change + task_progress), tsc clean
- T13 security audit DONE — filed 3 bugs for backend-dev:
  - SEC-SSE-001 HIGH: _running_tasks dict at pipeline.py:51 has no tenant scoping — cross-tenant leak via SSE stream
  - SEC-EMAIL-001 HIGH: email_service.py:59,110 — display_name not html.escape()'d in email templates
  - SEC-KEYS-001 MEDIUM: vault.py:326 Gemini key in URL + vault.py:356/settings.py:231 leak exception details
- Remaining: T3 (PipelineStepper), T4 (wire stepper), T7 (key validation UI), T10 (notification provider) for frontend-dev
- T12 (full QA regression) depends on all of the above

## Handoff (2026-04-10)
- PRD 2 (Pipeline UX) is active with 13 tasks, agents executing
- Fixed: ANTHROPIC_API_KEY leak ($64/day), stale progress.md, RUBRIC PRD display, agent coordination
- RUBRIC layout: two-column (queue + activity feed), tasks labeled by PRD
- Agents use OAuth now (no API key charges)
- Monitor: check cost page Apr 11 to confirm $0 API charges
