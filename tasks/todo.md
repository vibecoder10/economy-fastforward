# Task Tracking

## Handoff (2026-04-19 — Osiris full-autonomy overnight ship mode started)

### Context
Ryan granted full-autonomy ship-while-sleep mandate (see `~/.claude/projects/-Users-osiris-claude-agent/memory/project_storyengine_full_autonomy.md`). Single-agent (Osiris) continuous builder, Karpathy build-test-learn loop, functional tests only (no smoke-test ship gate). Daily ship log at `storyengine/daily-ship-log-YYYY-MM-DD.md`.

### Completed this cycle
- **Trial-downgrade cron (fix-roadmap 3.2)** — migration 041, `send_trial_expired` email, `check_trial_expired` task, `_auto_check_trial_expired` wired in lifespan @ 6h interval. Functional test in `backend/tests/functional/test_trial_expired.sql` green against prod Supabase.
- **Humanize error strings (frontend)** — 11 raw-error leak sites routed through `humanizeError()`. Pages: login, forgot-password, reset-password, settings/drive-callback, settings/youtube-callback, system-prompts, profile, competitors. Components: CreateVideoStep, FirstVideoFlow, storyboard-viewer. `npx tsc --noEmit` clean. Users no longer see "API error 500" or "Failed to fetch".
- **Flow B slice 1 — existing-channel detection** — new `GET /api/youtube/my-videos` endpoint fetches user's top uploads via OAuth + uploads-playlist pattern. Frontend `YouTubeConnectStep` auto-fetches + renders "We found N top-performing videos on your channel" card after OAuth succeeds. Backend functional tests (4/4 ✅) including live contract check against googleapis.com.
- **Flow B slice 2 — voice auto-learn** — new `POST /api/youtube/learn-voice` endpoint: top-5 videos → Claude Sonnet 4 voice summarization → persists `channel_profiles.style_description`. **Reordered onboarding steps** to `channel → keys → youtube → style → video` so voice-learn can pre-fill the Style step. `StyleSetupStep` shows "We drafted this from your top YouTube videos" banner when pre-filled. Backend functional test `test_learn_voice.py` (3/3 ✅) including LIVE 401 contract test against api.anthropic.com. `npx tsc --noEmit` clean.
- **Grandma-mode override audit + script bot wired (Cycle 6)** — Cycle 1's "wiring in 7 places" claim was wrong. `test_prompt_override_wiring.py` (3 tests ✅) audits via runtime + static grep. Found 1/6 bots reading their override (video_motion only). Wired the `script` bot end-to-end: `script_generator.py` (`system_prompt_override` param → `anthropic_client.generate(system_prompt=...)`) + `brief_translator/__init__.py` (both `BriefTranslator.__init__` and `translate_brief` convenience func) + `script/run.py` (passes `getattr(pipeline, "script_system_prompt", None)`). 2/6 wired after Cycle 6.
- **All 6 bots wired (Cycle 7)** — completed the grandma-mode rollout. Thumbnail bot (3 Claude call sites via `ThumbnailTitleEngine` → `TitleGenerator` + `ThumbnailPromptBuilder`, wired in `thumbnail/run.py`). Sound bots (`SoundPromptBot` now takes both `sound_curation_` and `sound_generation_` overrides, wired in `sound/run_design.py`). Research bot (`ResearchAgent` + `run_research` take override, wired at SaaS executor boundary `pipeline_executor.py:run_research`). Audit test broadened regex to match `self._pipeline.<attr>`; CONSUMER_SPEC updated. **6/6 WIRED** with a full-loop regression guard asserting all 6 stay wired.
- **Backend error humanization (Cycle 8)** — new `storyengine/backend/error_utils.py` with `humanize_error(err, context=...)` mirror of frontend `src/lib/errors.ts`. Fixed 11 HTTPException leak sites across 6 customer-facing routes (visual_styles.py × 5, intelligence.py × 1, pipeline.py × 1, system_prompts.py × 1, youtube_channel.py × 1, videos.py × 1). Raw `str(e)` / upstream-API bodies no longer reach users; all get logged at WARNING with `[humanize_error]` prefix for dev grep. Functional test `test_error_humanization.py` (8/8 ✅) including static audit regex-scan that asserts 0 raw-error leaks across all 6 customer-facing route files — acts as a regression guard for any new route added later.
- **Background-task error humanization (Cycle 9)** — closed the leak surface flagged as Cycle 8's honest gap. `_set_task_status` in `routes/pipeline.py` now humanizes at the write boundary, covering all ~15 `str(e)` call sites in one change. `routes/agents.py` agent-pipeline run uses `humanize_error(e, context="The agent pipeline hit an error")` at both the in-memory `_set_task` and the `bot_activity` INSERT. Runtime test `test_set_task_status_humanizes_failure_errors` (via FastAPI-free module stubs) proves a raw `HTTPSConnectionPool(host='api.kie.ai'...)` input never leaks into `_running_tasks['error']`. Full suite: 9/9 green. Prompt-override wiring test still 6/6 WIRED.
- **Activity-feed humanization (Cycle 10)** — uncovered a third independent leak surface: `pipeline_executor._log_activity` writes `message` to `bot_activity` which `/api/activity` returns verbatim to the UI. ~20 call sites in `pipeline_executor.py` pass `error_msg = str(e)`. Fixed with a single-line funnel guard inside `_log_activity` (`humanize_error(message)` when status=="failed"). Also fixed `/orchestrator/decide` returning `reasoning=f"Orchestrator error: {e}"`. Static-grep test added. 10/10 tests green.
- **Orchestrator result humanization (Cycle 11)** — closed the 4th and last leak funnel flagged in Cycle 10's honest gap. `claude_orchestrator.ClaudeOrchestrator.execute` previously built `OrchestratorResult(error=str(e))` on exception; now runs through `humanize_error(e, context=f"Executing {decision.skill_id} hit an error")` so `/orchestrator/execute` callers never see raw stack text. 10/10 tests still green. Four leak surfaces, four cycles, one helper, zero API growth.
- **Transcript-based voice-learn (Cycle 12)** — upgraded `/api/youtube/learn-voice` (Flow B slice 2) from titles+descriptions to actual yt-dlp transcripts. New `_fetch_transcripts_for_videos` helper runs 5 concurrent yt-dlp fetches via `asyncio.gather(run_in_executor(...))` reusing `routes.niche._extract_video_info`. Silent per-video fallback (transcript → description → `(no description)`). `TRANSCRIPT_CHAR_CAP=2000` bounds per-video context cost. Response surface adds `transcript_count` + `has_transcript` per video so frontend can show signal strength. 4 new tests (mixed prompt path, silent-fail, char-cap, template-mentions-transcripts) + 3 existing = 7/7 green in `test_learn_voice.py`. Regression suites still clean (10/10 humanize, 6/6 override-wired).
- **UI signal-strength banner (Cycle 13)** — surfaced `transcript_count` from Cycle 12 into `StyleSetupStep.tsx` with three-state copy: "learned from N transcripts (+M descriptions)" / "learned from N descriptions — add captions for sharper voice learning" / generic fallback. `api.ts` + `onboarding/page.tsx` types+state plumbing. `npx tsc --noEmit` clean.
- **Prod deploy of Cycles 8-13 (Cycle 14)** — Ryan granted SSH to VPS (clawd@76.13.119.181). Stashed dirty runtime artifacts on `~/projects/economy-fastforward`, `git pull origin main` (19 commits behind), `pip install -q`, `npm install && npm run build`, `sudo systemctl restart` both services. Migration 041 auto-applied. storyengine.dev `/` + `/api/health` + `/onboarding` all 200. Ran both functional suites against live VPS env: `test_error_humanization.py` 10/10, `test_learn_voice.py` 7/7. First time tonight's work reached production.
- **Runtime E2E activity-feed audit (Cycle 15)** — `tests/functional/test_activity_feed_no_raw_errors.py`: two passive scans against live prod DB (`bot_activity.message` + `background_tasks.error_message` for 16 raw-exception signatures — HTTPSConnectionPool, Traceback, Errno, 6 Python exception types, 3 upstream API hostnames, Connection aborted/refused/reset) + a helper-pattern pin that guards against adding a pattern to the catalog the helper can't strip. 3/3 green on VPS: 87 failed bot_activity rows + 1 failed background_task scanned, zero leaks. Closes the "needs a live backend" honest-gap flagged in Cycles 8-11.
- **Kie.ai validator hotfix (live customer bug)** — Ryan hit "Saved but validation failed" on the TOOLS onboarding step. Root cause: `vault.test_api_key` called `api.kie.ai/api/v1/user/balance` which 404s (deprecated endpoint) AND Kie.ai uses the 200-OK-with-error-body pattern, so checking HTTP status alone would still be wrong. Fixed by switching to `/api/v1/chat/credit` + parsing `{code, msg, data}` body. Ryan's key was valid all along (4335.86 credit). Shipped as commit `a61a4d2e`, pulled+restarted on VPS, verified `test_api_key` returns `{'success': True, 'message': 'Kie.ai API key valid (credit: 4335.86)'}`. 35-min turnaround screenshot→fix-live.
- **ElevenLabs validator hotfix (Ryan 2nd report)** — Same bug class. `/v1/user` requires the `user_read` scope which Ryan's TTS-only key doesn't have. Fixed by switching to `/v1/voices` (the endpoint StoryEngine actually calls for voice-picker population) + parsed the 401 body to distinguish `invalid_api_key` from `missing_permissions` for an actionable error message. Shipped as commit `bfcc9b46`. Verified green on VPS. Principle: validate against endpoints we actually use, not "hello world" endpoints.
- **TOOLS step UI fix (Cycle 17)** — Ryan's "4 keys but only 3 to enter, no Continue button" report. ElevenLabs groups two backend keys into one visual card, but the progress counter/disabled gate was counting raw keys. Switched to provider-count semantics (`renderItems.length`, `every(configured)` per grouped provider). `ApiKeysStep.tsx` commit `946ea7aa`, shipped, browser-verified live — counter reads "2 of 3 connected" and button reads "Connect all 3 tools to continue" with coherent state.
- **Dashboard WelcomeQuest — the "huge win" (Cycle 18)** — closed the "no onboarding after keys" gap. New `components/dashboard/welcome-quest.tsx` renders a three-step quest panel (add competitors → distill first insight → create first video) above the dashboard's analytics widgets, visible only while `video_count === 0`, dismissible with localStorage persistence. Backend added a `first_run: {competitor_count, distilled_count, video_count}` block to `/api/dashboard/onboarding/status`. Commit `68b9ee9d`, both services restarted on VPS, browser-verified live with all three cards rendering "0 of 3 done" on a fresh account.
- **Intelligence-teaser strategy memo (Task #24)** — Ryan's "do we let them run a free pass to get hooked?" question. Wrote a strategy memo at `storyengine/notes/intelligence-teaser-strategy-2026-04-19.md`. Recommendation: don't build the StoryEngine-funded teaser yet. BYOK already gives us a near-free hook (user's own credits cost pennies, $0 to us). First ship the UX changes shipped tonight + add event tracking, measure dropoff for two weeks, THEN decide whether to spend engineering on a funded teaser targeted at the specific dropoff point.

### Next in queue (priority order)
1. First real end-to-end customer-style render (Ryan as dogfood) — proves live output variation between two overrides end-to-end. Task #11.
2. **Audit the other `test_api_key` branches for the 200-OK-with-error-body pattern** — Anthropic, OpenAI, Gemini, ElevenLabs, Tavily all check HTTP status only. Same bug class would hit all of them if any provider silently moves to 200+JSON-code style.
3. **Synthetic canary for upstream-validator drift** — hourly cron hits `test_api_key` against known-good keys for each provider, pages on regression. Catches endpoint deprecation (like the Kie.ai one) before users see "validation failed."
4. Live yt-dlp stability test against a stable public YouTube URL (catches version drift + YouTube anti-scrape changes).
5. Fresh fix-roadmap.md rewrite against ground truth (drop items already shipped).
6. Clean-replacement override semantics — when an override is present, also strip the profile-derived voice preamble from the user-prompt body. (Current v1: override lands as `system_prompt`, preamble still in user body → Claude blends.)
7. Hourly launchd/cron wrap of Cycle 15's audit — continuous surveillance instead of ad-hoc runs.
8. Bump pydantic + pyjwt to satisfy supabase lib requirements (noted as non-fatal warnings during Cycle 14 deploy).

### Open questions for Ryan
- **Override replacement semantics:** currently the tenant override lands as Claude's `system_prompt` while the profile-derived voice preamble still lives in the user-prompt body → Claude blends the two. Clean-replacement (skip profile preamble when override present) is a follow-up decision once we measure output variation end-to-end.
- **Python-layer test harness:** backend expects local PG proxy on :55432 that isn't running on this Mac. For functional Python tests (not just SQL), either start the proxy or write tests as VPS-executable scripts.

## Handoff (2026-04-14 — PRD 3 T5 Storage + Bug Triage)

### Completed
- PRD 3 T5: Extended `storyengine/backend/storage.py` with Supabase Storage backend
  - `STORAGE_BACKEND` env var: "google_drive" (default) or "supabase"
  - Per-tenant path isolation: `{tenant_id}/{video_id}/{filename}`
  - `create_signed_url()` for time-limited access
  - All 4 acceptance criteria pass
- Investigated 5 live user errors: all routes work, errors were transient

### Next
- T12 (QA): Storage isolation verification — ready for qa-engineer
- T13 (Security): Final infrastructure audit — deps now met (T5 done)
- Consider updating `pipeline_executor.py` and `extraction.py` callers to pass `tenant_id` when `STORAGE_BACKEND=supabase`

---

## Handoff (2026-04-11 — Autopilot Intelligence + Second-Order Distillation)

### Phase 5: Intelligence Advisor (DONE)
- `storyengine/backend/distillation/advisor.py` (NEW) — IntelligenceAdvisor class
  - Queries content_intelligence aggregates for best-performing patterns
  - Returns: best hook type, thumbnail style, title structure, publish timing, top topics
  - `to_prompt_context()` formats for Claude prompt injection
  - `to_dict()` serializes for API response
  - Parallel async queries, confidence = min(1.0, sample_size / 50)
- Wired into `routes/autopilot.py` — Intelligence scoring now matches candidate DNA against niche recommendations
  - Candidates with matching hook_type get +15, title_structure +10, topics +10
  - Candidates query LEFT JOINs content_intelligence for hook_type, title_structure, topic_tags
  - New `GET /api/autopilot/recommendations` endpoint for dashboard
- Wired into `routes/discovery.py` — `_get_learnings_context()` now includes niche intelligence recommendations section

### Phase 6: Auto-Distillation + Meta-Analysis (DONE)
- `_auto_distill_intelligence()` background task in main.py (12h cycle, 25 videos/batch)
- `_auto_generate_meta_insights()` background task in main.py (24h cycle)
- `storyengine/backend/distillation/meta_analyzer.py` (NEW) — Second-order distillation
  - Gathers 10+ aggregated pattern queries (hooks, titles, thumbnails, topics, timing, controversy, tones, viral videos)
  - Sends to Claude Haiku for meta-analysis
  - Extracts: top_patterns, combination_insights, timing_strategy, contrarian_findings, niche_signature
  - Stores in `niche_meta_insights` table (upserted per tenant)
- `storyengine/backend/migrations/040_niche_meta_insights.sql` (NEW) — niche_meta_insights table
- `routes/intelligence.py` — 3 new endpoints:
  - `GET /api/intelligence/recommendations` — advisor recommendations
  - `GET /api/intelligence/meta-insights` — latest meta-analysis report
  - `POST /api/intelligence/meta-insights/generate` — trigger meta-analysis

### Phase 7: Frontend Dashboard (DONE)
- `api.ts`: New types + API functions (IntelligenceRecommendations, NicheMetaInsights, 4 new fetch functions)
- `analytics/page.tsx`: Two new panels in Niche Intelligence section:
  - **AI Recommendations** — 4-card grid: Best Hook, Best Title Structure, Best Thumbnail, Best Timing + top topics
  - **Niche Meta-Analysis** — Claude-generated report with top patterns, contrarian findings, winning combinations
  - Generate button for meta-analysis when 20+ videos distilled

### What's next:
1. **Deploy**: Restart backend to auto-apply migrations 036-040 + start background tasks
2. **Trigger backfill**: `POST /api/intelligence/backfill?batch_size=50` (or wait 12h for auto-distillation)
3. **Trigger meta-analysis**: `POST /api/intelligence/meta-insights/generate` (or wait 24h)
4. Extend distillation to video_scripts, research_payloads, agent_paper_trails
5. Add GCS archival for raw transcripts after distillation
6. Autopilot auto-launch: use recommendations to auto-select which discovery idea to launch

**Design decisions:** See `tasks/decisions.md` — ADR 2026-04-11

### Previous: Phases 1-4 (Content Intelligence Full Stack) — DONE
- Backend distillation pipeline (Haiku + Gemini Vision + OpenAI embeddings)
- 10 intelligence API endpoints + frontend UI
- Intelligence-driven scoring in autopilot + discovery

---

## Active Work

**Execution Plan:** `tasks/roadmap.md` — 18-day SaaS transformation
**Current PRD:** PRD 3 — Infrastructure (Security, Rate Limiting, Task Persistence, Logging, Health Check)
**Agent Team:** 6 agents on Opus. PRD 2 mostly complete (11/13). PRD 4 complete (15/15).

### PRD 3 Progress
- [x] **Task 1** (SEC-1, SEC-2, SEC-3): Already done by agent team — verified
- [x] **Task 2** (SEC-4, SEC-5, SEC-6): SEC-4/SEC-6 already done. SEC-5 safety comments added to all 12 f-string SQL queries
- [x] **Task 3**: Rate limiting middleware (`rate_limit.py`) — per-plan token bucket, concurrent job limits
- [x] **Task 4**: Persistent background tasks — migration 032, `_db_persist_task()` fire-and-forget, `recover_stale_tasks()` on startup
- [ ] **Task 5**: Per-tenant storage — DEFERRED (users will connect own Google Drives, not Supabase Storage)
- [x] **Task 6**: Structured JSON logging (`logging_config.py`) — all `print()` in main.py replaced with `logger.*`
- [x] **Task 7**: Health check expansion — `/api/health` checks DB + active tasks, `/api/health/detailed` with token auth
- [ ] **Task 8**: QA security verification (depends on Tasks 1-2)
- [ ] **Task 9**: QA infrastructure verification (depends on Tasks 3-7)
- [ ] **Task 10**: Frontend health status indicator (depends on Task 7)
- [ ] **Task 11**: Security final audit (depends on all tasks)

## Handoff (2026-04-10 — PRD 3 Phase 1+2 Build)

**What was built:**
- `storyengine/backend/rate_limit.py` (NEW) — Token bucket rate limiter per plan (free: 15/min, starter: 30, creator: 100, studio: 300). Concurrent pipeline job limits. Skips health/auth paths.
- `storyengine/backend/logging_config.py` (NEW) — StructuredFormatter (JSON), RequestLoggingMiddleware, error rate tracking (10/5min threshold)
- `storyengine/backend/migrations/032_background_tasks.sql` (NEW) — Persistent task tracking table with RLS
- `storyengine/backend/routes/pipeline.py` — Added `_db_persist_task()` (fire-and-forget DB writes on key transitions), `recover_stale_tasks()` (startup recovery). 61 `_set_task_status` calls now pass `tenant_id=tenant_id` for DB persistence.
- `storyengine/backend/main.py` — Wired RateLimitMiddleware + RequestLoggingMiddleware. Replaced ALL 18 `print()` with `logger.*`. Added startup task recovery. Expanded `/api/health` + new `/api/health/detailed`.
- `storyengine/schema.sql` — Added background_tasks table definition
- 10 route files — Added SEC-5 SECURITY comments to all f-string SQL queries

**Design decisions:**
- Task tracking is dual-layer: in-memory dict for real-time progress (sync-compatible with progress callbacks), DB for persistence/history. Fire-and-forget via `asyncio.create_task()`.
- Task 5 (per-tenant Supabase Storage) deferred — user wants BYOD Google Drive model.
- Rate limiting is in-memory (resets on restart) — acceptable for v1 since it's protective not billing-critical.

**What's next (Phase 3):**
- Tasks 8-9: QA verification of security + infrastructure
- Task 10: Frontend health status indicator component
- Task 11: Final security audit
- Deploy to VPS and verify migration 032 runs

**Previous:** PRD2 T1-T11 verified. PRD 4 complete (15/15).

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

## Handoff (2026-06-08 — pipeline import repair + Youtuber agent)
- **Fixed:** 5 stale shim-name imports left by 17b03be0 — pipeline now imports cleanly again (orchestrator.pipeline + all 5 touched entrypoints verified). Branch `claude/repair-pipeline-imports`. Done in an isolated git worktree (~/yt-repair) to avoid the storyengine dev-swarm's git stash/checkout/reset on the shared tree.
- **Not done / next:** smoke test was import-only (no paid run). Before relying on production: run a single-video dry pass, and reinstall the setup_cron.sh production jobs (queue/discover/autopilot) — they are NOT in the live crontab (only storyengine/agents swarm + bot_healthcheck).
- **Separate effort:** standing up a new Hermes agent profile `Youtuber` (~/.hermes/profiles/youtuber) as the YouTube production brain that drives this pipeline; multi-channel generalization planned (ChannelConfig). See ~/Desktop/Power_Doctrine Pipeline-main-integration/HERMES_REBUILD_PLAN.md.
- **Caution:** `/home/clawd/pipeline-bot/venv` (referenced by infra detect_python) does not exist; live fallback is repo-root `economy-fastforward/venv`.
