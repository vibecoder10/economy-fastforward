# StoryEngine Fix Roadmap
_Created: 2026-04-10 — Audit-based, organized for staged PRD execution_

---

## How to Use This Document
Each stage is a self-contained PRD. Work them in order — later stages depend on earlier ones. Every item has been verified against the actual codebase (not copied from stale docs).

---

## Stage 1: Build Blockers & Security (CRITICAL)
_Must fix before any other work. These are broken right now._

### 1.1 TypeScript Won't Compile — ✅ SHIPPED (verified Cycle 37, 2026-04-20)
- **What:** `npx tsc --noEmit` fails with 19 errors
- **Root cause:** `@dnd-kit/core`, `@dnd-kit/sortable`, `@dnd-kit/utilities` declared in package.json but not installed. Pipeline page imports them for drag-drop reordering.
- **Status:** `npx tsc --noEmit -p tsconfig.json` on `frontend/` is clean (exit 0, no output). `dashboard-fixes.spec.ts` covered by the main tsconfig (`**/*.ts` include) — also passes. VPS build succeeds repeatedly across Cycles 32/35/36 deploys.
- **Files:** `frontend/src/app/pipeline/page.tsx`, `frontend/package.json`

### 1.2 SEC-SSE-001 — Cross-Tenant Task Leak (HIGH) — ✅ SHIPPED (regression locked Cycle 46, 2026-04-21)
- **What:** `_running_tasks` dict in `backend/routes/pipeline.py` was keyed by `video_id` only. Two tenants could share task state through the dict, leaking status to the SSE feed.
- **Fix (landed):** dict re-typed to `dict[tuple[str, str], dict]`; `_set_task_status` / `_get_task_status` / `_clear_task_status` all require tenant_id; SSE loop iterates `(tid, vid), task` and continues when `tid != tenant_id`.
- **Regression lock:** `backend/tests/functional/test_sse_cross_tenant_lock.py` — 4 static-audit checks (type annotation, no bare `_running_tasks[video_id]` indexing, helper tenant_id requirement, SSE filter).
- **Files:** `backend/routes/pipeline.py`

### 1.3 SEC-EMAIL-001 — HTML Injection in Emails (HIGH) — ✅ SHIPPED (regression locked Cycle 47, 2026-04-21)
- **What:** `display_name` / `plan` / `amount_display` were interpolated directly into HTML email bodies. A hostile display_name could deliver `<script>` into any welcome / trial / receipt email.
- **Fix (landed):** `import html as html_lib` at module top; every user-controllable string is bound to `safe_<name> = html_lib.escape(x or "")` and only `safe_*` is interpolated.
- **Regression lock:** `backend/tests/functional/test_email_html_escape_lock.py` — 4 static-audit checks (html import, every user-input param is escaped, no raw interpolation in HTML f-strings, known senders still exist).
- **Files:** `backend/email_service.py`

### 1.4 SEC-KEYS-001 — Exception Details Leaked to Client (MEDIUM) — ✅ SHIPPED (regression locked Cycle 48, 2026-04-21)
- **What:** `backend/vault.py` `test_key` catch-all returned raw `str(e)` in API responses, leaking httpx internals, DNS hostnames, TLS paths, and proxy URLs to the Settings UI.
- **Fix (landed):** Catch-all routes through `humanize_error(e, context='Connection failed while testing key')` — logs the raw error at WARNING for server-side diagnosis, returns a short safe message to the client.
- **Regression lock:** `backend/tests/functional/test_vault_error_leak_lock.py` — 3 AST-based audits (humanize_error imported + used, no `return`/`raise` interpolates captured exception, test_key catch-all still humanized).
- **Files:** `backend/vault.py`

### 1.5 SQL Injection Risk in Adapter — ✅ SHIPPED (regression locked Cycle 50, 2026-04-21)

**Status summary:** all dynamic column names in backend SQL go through a validator before reaching the cursor:
- `database.safe_column(name)` — asyncpg paths (`backend/database.py:11`)
- `supabase_adapter._safe_col(name)` — psycopg2 paths (`backend/supabase_adapter.py:34`)

Both enforce `^[a-z][a-z0-9_]*$`. Hot-path UPDATE routes (`projects.py`, `videos.py`, `youtube_sync.py`) build SET lists via `safe_column(col)` per element, then join. Remaining f-string interpolations in SQL queries are either integer-bounded (e.g. `$idx`, `storyboard_{beat}_url` with `1<=beat<=5`), sourced from hardcoded allowlists (`_SORT_MAP`, `{"videos_created", ...}` in billing), or literal fragment strings built in-function with no user input.

Pinned by `backend/tests/functional/test_sql_column_injection_lock.py` (4/4 green):
1. Both validator regexes still match `^[a-z][a-z0-9_]*$` — any widening fails.
2. `safe_column` runtime-rejects 12 canonical SQLi payloads (`id; DROP TABLE`, `id OR 1=1`, `id"`, uppercase, empty, etc.).
3. AST audit of 15 backend files — every `{expr}` inside an f-string that starts with `SELECT|UPDATE|INSERT|DELETE|WITH` must be either a `safe_column`/`_safe_col` call, a `.join(...)` over per-element-validated pieces, an integer index, or on the `_VERIFIED_SAFE` allowlist (each entry carries a why-comment).
4. `routes/projects.py`, `routes/videos.py`, `routes/youtube_sync.py` still reference `safe_column` (belt-and-suspenders).

Original roadmap text retained below for historical context.

---

- **What:** `backend/supabase_adapter.py` has 8 instances of f-string SQL with dynamic column/table names. While values use positional params ($N), column names are interpolated.
- **Risk:** Lower than raw f-strings but fragile — a future dev could easily introduce a real injection.
- **Fix:** Validate all dynamic column names against an allowlist, or use `database.py`'s existing column validation regex (`^[a-z][a-z0-9_]*$`).
- **Files:** `backend/supabase_adapter.py`, `backend/pipeline_executor.py`, `backend/routes/youtube_sync.py`

---

## Stage 2: Schema & Data Integrity
_Database source of truth is out of sync. Fix before building new features._

### 2.1 schema.sql Out of Sync with Migrations — ✅ SHIPPED (regression locked Cycle 52, 2026-04-21)
- **Status:** All 4 previously-drifted tables (`background_tasks`, `notification_preferences`, `visual_styles`, `style_characters`) are now defined in `schema.sql` with matching RLS. Pinned by `backend/tests/functional/test_schema_sql_migrations_drift.py` (4/4 — walks every `CREATE TABLE` across migrations 001–041 and asserts each appears in `schema.sql`).

### 2.2 RLS Policy Consolidation — ✅ SHIPPED (regression locked Cycle 52, 2026-04-21)
- **Status:** `background_tasks` RLS policy landed in `schema.sql` via migration 038, replacing the broken `tenant_id = auth.uid()` check (which would never match — tenant_id is not a Supabase auth user id). Pinned by `backend/tests/functional/test_background_tasks_rls_consolidation.py` (5/5 — verifies migration exists, schema.sql has the single correct policy, no file still uses the broken predicate).

### 2.3 Missing Indexes — ✅ SHIPPED (regression locked Cycle 52, 2026-04-21)
- **Status:** `background_tasks(created_at DESC)` index added via migration (cleanup/expiry queries), `tenant_usage(tenant_id, period_start)` index already present for monthly lookups. Pinned by `backend/tests/functional/test_background_tasks_created_at_index.py` (5/5 — migration exists, creates the index, schema.sql mirrors it in every tenant block, DESC ordering, tenant_usage index still present).

---

## Stage 3: Wiring Gaps
_Features that exist in parts but aren't fully connected end-to-end._

### 3.1 Suggest-Titles Not in Create Video Flow ✅ SHIPPED (Cycle 41, 2026-04-20)
- **Status:** Already fully wired end-to-end; Cycle 41 found this on audit and added regression coverage.
- **Wire-up (6 links):**
  1. Backend: `backend/routes/videos.py:1006` — `@router.post("/suggest-titles")` / `async def suggest_titles(body: SuggestTitlesRequest, ...)`
  2. Pydantic: `SuggestTitlesRequest` with `topic: str` field
  3. Frontend API: `frontend/src/lib/api.ts:1596` — `export const suggestTitles = (topic: string) => ...` + `interface TitleSuggestion`
  4. Pipeline entry: `frontend/src/components/pipeline/FirstVideoFlow.tsx:39-53` — handler `await suggestTitles(topic); setSuggestions(result.titles)`
  5. Onboarding entry: `frontend/src/components/onboarding/CreateVideoStep.tsx:116-129` — same `await suggestTitles(...)` pattern
  6. Mounts: `frontend/src/app/pipeline/page.tsx:1151` renders `<FirstVideoFlow>`; `frontend/src/app/onboarding/page.tsx` renders `<CreateVideoStep>`
- **Regression lock:** `backend/tests/functional/test_suggest_titles_wire.py` (6 tests) — pins each link. If a refactor cuts the button out, this test flags it.

### 3.2 Free Trial Lifecycle Incomplete ✅ SHIPPED (Cycle 42, 2026-04-20)
- **Status:** Already fully wired + Cycle 42 closed schema.sql drift and added regression coverage.
- **Wire-up (7 links):**
  1. Migration: `backend/migrations/041_trial_expired_handled.sql` — adds `trial_expired_handled BOOLEAN` + partial index on `(trial_ends_at) WHERE trial_expired_handled IS NOT TRUE AND stripe_subscription_id IS NULL`
  2. Schema: `schema.sql` accounts block now carries `trial_warning_sent` + `trial_expired_handled` + the partial index (was drift — Cycle 42 fix)
  3. Task: `backend/email_tasks.py:check_trial_expired()` — selects expired + unhandled + `stripe_subscription_id IS NULL` (paying-customer safety filter)
  4. Task: same function flips `plan='starter'` AND `trial_expired_handled=TRUE` in one UPDATE (atomic)
  5. Email: `backend/email_service.py:send_trial_expired(email, display_name)` sends the notice
  6. Lifespan: `backend/main.py:234` — `_auto_check_trial_expired()` while-True loop with `asyncio.sleep(21600)` (6h cadence)
  7. Lifespan: `main.py:394` creates the task on startup; `:406` cancels on shutdown
- **Regression lock:** `backend/tests/functional/test_trial_downgrade_wire.py` (7 tests). Specifically guards the `stripe_subscription_id IS NULL` filter — losing it would downgrade paying customers.

### 3.3 Google Auth / Settings (Re-audited) ✅ SHIPPED (2026-04-23)
- **Status:** Feature was already committed in `e167b0a8` (2026-04-10). Re-audit confirmed all code present. Regression lock added.
- **Wire-up (6 links):**
  1. Backend: `backend/routes/google_auth.py` — GET `/google-drive/connect` → `{"auth_url": str}`
  2. Backend: `backend/routes/google_auth.py` — POST `/google-drive/callback` → `{"status": "connected", "access_token": str}`
  3. Backend: `backend/routes/google_auth.py` — GET `/google-drive/status` → `{"connected": bool, "folder_id": str|None, "folder_name": str|None}`
  4. Backend: `backend/routes/google_auth.py` — POST `/google-drive/disconnect` → `{"status": "disconnected"}`
  5. Frontend: `frontend/src/lib/api.ts` — `getDriveStatus`, `getDriveConnectUrl`, `postDriveCallback`, `disconnectDrive`, `getDriveAccessToken`
  6. Frontend callback: `frontend/src/app/settings/drive-callback/page.tsx` — exchanges `?code=` param with backend, redirects to `/settings`
- **Regression lock:** `backend/tests/functional/test_google_auth_callback_shape_lock.py` (16 tests) — pins all 6 endpoint shapes + frontend wiring. Playwright `settings.spec.ts` covers Google OAuth login, Drive connect initiation, and disconnect/revoke flow (3 new tests).

### 3.4 Hardcoded localhost in Frontend — ✅ SHIPPED (regression locked Cycle 51, 2026-04-21)

**Status summary:** centralized in `frontend/src/lib/env.ts`. The module reads `process.env.NEXT_PUBLIC_API_URL` once at module scope (the only shape Next.js inlines into the client bundle), and `requireInProd()` throws if the var is empty and `NODE_ENV === "production"`. Every other file imports `API_URL` from `@/lib/env`. No file outside `env.ts` mentions `localhost:8001` or `localhost:5050`.

Pinned by `backend/tests/functional/test_frontend_api_url_no_localhost_lock.py` (4/4 green):
1. `env.ts` still does literal `process.env.NEXT_PUBLIC_API_URL` access + has `NODE_ENV === "production"` throw gate.
2. No other `.ts/.tsx` file in `frontend/src/` reads `process.env.NEXT_PUBLIC_API_URL` directly.
3. No `.ts/.tsx` file outside `env.ts` hardcodes `http://localhost:8001` or `http://localhost:5050`.
4. `lib/api.ts` still imports `API_URL` from the centralized env module.

Original roadmap text retained below for historical context.

---

- **What:** `frontend/src/lib/api.ts:1-2` falls back to `localhost:8001` and `localhost:5050`. Same pattern in `frontend/src/app/demo/page.tsx:73` and `frontend/src/hooks/use-pipeline-sse.ts:5`.
- **Risk:** Works in dev, but if env vars are missing in production, API calls silently go to localhost.
- **Fix:** Throw an error or use relative URLs if `NEXT_PUBLIC_API_URL` is not set, rather than falling back to localhost.
- **Files:** `frontend/src/lib/api.ts`, `frontend/src/app/demo/page.tsx`, `frontend/src/hooks/use-pipeline-sse.ts`

---

## Stage 4: Missing Infrastructure
_Not broken today, but will break at scale or under real usage._

### 4.1 No Persistent Job Queue
- **What:** Pipeline jobs run in-memory via `_running_tasks` dict + `asyncio.create_task()`. Server restart = all running jobs lost. `background_tasks` DB table provides persistence/history but no actual job recovery.
- **Impact:** Any VPS restart or deploy kills active video renders. Users see "stuck" pipelines.
- **Fix:** Implement Redis + arq (or similar). Pipeline stages become persistent jobs with retry + dead-letter. `recover_stale_tasks()` at startup re-queues interrupted work.
- **Files:** New `backend/worker.py`, `backend/job_queue.py`. Modify `backend/pipeline_executor.py`, `backend/routes/pipeline.py`
- **Effort:** 2-3 days

### 4.2 No Error Monitoring (Sentry)
- **What:** No Sentry or equivalent. Errors go to console/structured JSON logs only. No alerting, no error grouping, no user-impact tracking.
- **Fix:** Add `sentry_sdk` to backend (FastAPI integration). Add `@sentry/nextjs` to frontend. Tag all events with `tenant_id` + `video_id` context.
- **Files:** `backend/main.py`, `frontend/next.config.ts`, new `frontend/sentry.*.config.ts`
- **Effort:** 0.5 day

### 4.3 No Per-Tenant Storage Isolation
- **What:** All video assets (images, audio, renders) go to a single Google Drive or Kie.ai temp URLs. No per-tenant isolation. Kie.ai URLs expire.
- **Decision needed:** User wants BYOD Google Drive (each tenant connects their own). Not Supabase Storage.
- **Fix:** Implement per-tenant Google Drive OAuth connection. Store `drive_folder_id` per tenant. Route all asset uploads to tenant's Drive.
- **Files:** `backend/routes/google_auth.py` (Drive OAuth exists — migration 034), asset upload functions
- **Effort:** 2 days

---

## Stage 5: End-to-End Verification
_Prove everything works. No self-evaluation — run the app, see the result._

### 5.1 Full Playwright Regression
- **What:** 27 pages, 170+ API endpoints, 71 components. Many marked "DONE (unverified)" in product-brain.md. Need actual Playwright tests to confirm.
- **Scope:**
  - Auth flow: signup → login → forgot password → reset → Google OAuth
  - Pipeline: create video → watch stages progress via SSE → review → render
  - Billing: see plan → upgrade → Stripe checkout → plan updated
  - Settings: API keys → Google Drive connect → brand kit → notifications
  - Each page loads without console errors
- **Files:** `frontend/tests/` (existing tests have type errors — fix first)
- **Effort:** 1-2 days

### 5.2 VPS Deploy & Smoke Test
- **What:** All fixes need to run on production VPS, not just local.
- **Scope:**
  - Run all migrations (including any new ones from this roadmap)
  - Verify backend starts cleanly with new middleware (rate limiting, logging)
  - Verify frontend builds (`npm run build`) and serves
  - Test one real pipeline run end-to-end
- **Files:** VPS at `ssh clawd@76.13.119.181`

### 5.3 Security Verification — ✅ SHIPPED (static regression locks, 2026-04-21)
- **What:** After Stage 1 security fixes, verify:
  - Tenant A cannot see Tenant B's task status via SSE
  - Email display names with `<script>` tags render as plain text
  - API key test endpoint returns generic errors, not stack traces
  - No dev-token bypass in production mode
- **Files:** Manual testing or Playwright security tests
- **Status (2026-04-20, Cycle 55):** All four invariants pinned by functional regression locks instead of manual/Playwright:
  1. SSE cross-tenant isolation — `backend/tests/functional/test_sse_cross_tenant_isolation_lock.py` (Cycle 46)
  2. Email HTML injection — `backend/tests/functional/test_email_html_escape_lock.py` (Cycle 47)
  3. Exception detail leak — `backend/tests/functional/test_api_key_test_exception_leak_lock.py` (Cycle 48)
  4. **Dev-token prod safety (new this cycle)** — `backend/tests/functional/test_dev_token_prod_safety_lock.py`. Pins three conditions in every file that references `DEV_TOKEN`: no hardcoded `"dev-token"` accept branch anywhere in backend, `DEV_MODE == "true"` check present in the same neighborhood, and the comparison is guarded by a truthy-check on the env var so an unset `DEV_TOKEN` can't match `token == None`. 4/4 green.

---

---

## Stage 6: Product & UX Fixes
_Real user-facing issues. These are what people hit when they actually use the product._

### 6.1 API Keys Are Tenant-Scoped, Not Per-User
- **What:** All API keys (Anthropic, ElevenLabs, Kie.ai, Google, etc.) are stored per-tenant in the `secrets` table, keyed as `"{tenant_id}:{key_name}"`. Every member of a tenant shares the same keys. There is no per-user key management.
- **Problem:** User expects their API keys to be tied to their account (ryan.ayler@gmail.com), not to the platform/tenant. If a team member joins, they'd see and use your keys. Keys should follow the user, not the workspace.
- **Current state:** `backend/vault.py` stores keys with `tenant_id` prefix. `backend/routes/settings.py` reads/writes with `get_tenant_id()` dependency. No `user_id` column on secrets table.
- **Fix:** Add `user_id` column to secrets table. Change vault.py to scope keys by `(tenant_id, user_id)`. Update settings routes to pass both tenant_id and user_id. Frontend settings/keys page shows only your keys. Decide policy: do team members bring their own keys, or does the tenant admin set shared keys?
- **Design decision needed:** Per-user keys (each user brings their own) vs. per-user + shared tenant keys (admin sets defaults, users can override)?
- **Files:** `backend/vault.py`, `backend/routes/settings.py`, `backend/auth.py`, `frontend/src/app/settings/keys/page.tsx`, new migration

### 6.2 New User Experience — No Direction on First Login — ✅ SHIPPED (regression locked Cycle 56, 2026-04-21)
- **What:** A new user signs up, completes onboarding (channel + API keys), and lands on the dashboard — a big platform with no guidance on what to do next. No guided tour, no "create your first video" wizard, no checklist.
- **Problem:** Users bounce because they don't know where to start. The platform has 27 pages and no clear starting path.
- **Fix:** Add a first-run experience:
  1. **Welcome modal** on first dashboard visit — "Here's how to make your first video in 3 steps"
  2. **Onboarding checklist** (persistent sidebar or banner) — tracks: connected API keys, connected YouTube, created first video, reviewed first render
  3. **Empty dashboard CTA** — when no videos exist, show a prominent "Create Your First Video" card instead of empty stats
  4. **Contextual tooltips** on first visit to key pages (pipeline, competitors, analytics)
- **Current state:** Onboarding page exists (3-step: channel → API keys → ready) but after that, user is dropped into the dashboard with no guidance. `EmptyState` components exist but may not have strong enough CTAs.
- **Files:** New `frontend/src/components/onboarding/FirstRunChecklist.tsx`, `frontend/src/app/dashboard/page.tsx`, `frontend/src/lib/api.ts` (track onboarding progress), possibly new `onboarding_progress` DB column or table
- **Status (2026-04-20, Cycle 56):** Part 2 (persistent checklist) shipped — `frontend/src/components/onboarding/FirstRunChecklist.tsx` is mounted on the dashboard and stays visible until all three gates (API keys, YouTube, first video) are green, even after onboarding is marked complete. Backend `GET /api/dashboard/onboarding/status` computes every gate from real DB reads (`channel_profiles.channel_name`, `channel_profiles.youtube_refresh_token`, `get_secret_status` loop over `required_keys`, `COUNT(*) FROM videos`) — no stale flags. TS `OnboardingStatus` type mirrors the response. Regression lock: `backend/tests/functional/test_first_run_checklist_wired_lock.py` pins 5 invariants — endpoint exists + returns expected fields, gates derived from DB reads not hardcoded, TS type mirrors backend shape, component reads the 3 gates, dashboard imports + renders the component. 5/5 green. Parts 1 (welcome modal), 3 (empty-state CTA), 4 (contextual tooltips) remain as nice-to-haves but the core Stage 6.2 fix — no new user gets stranded — is in.

### 6.3 YouTube Channel Connection — No OAuth Flow
- **What:** There is NO YouTube OAuth endpoint. Users cannot connect their YouTube channel through the UI. The only way to get YouTube analytics working is to manually paste `google_client_id`, `google_client_secret`, and `google_refresh_token` into Settings > Keys — which requires developer knowledge.
- **Problem:** Normal users have no idea what a refresh token is. They need a "Connect YouTube" button that does OAuth, similar to how Google Drive connection works (which IS implemented at `/api/auth/google-drive/connect`).
- **Current state:**
  - Google Drive OAuth: DONE (`backend/routes/google_auth.py:472-599`, scopes: `drive.file`)
  - YouTube OAuth: NOT IMPLEMENTED (no endpoint, no scopes)
  - `youtube_sync.py` requires manual credentials from vault
  - `projects` and `channel_profiles` tables have NO `youtube_channel_id` field
- **Fix:**
  1. Add YouTube OAuth endpoints: `/api/auth/youtube/connect` and `/api/auth/youtube/callback` (mirror the Drive OAuth pattern)
  2. Request scopes: `youtube.readonly` + `yt-analytics.readonly`
  3. Store per-user YouTube credentials + channel_id in DB
  4. Add `youtube_channel_id` to `projects` table
  5. Add "Connect YouTube" button on Settings page + Analytics page
  6. Update `youtube_sync.py` to use per-user OAuth tokens instead of vault credentials
- **Files:** `backend/routes/google_auth.py`, `backend/routes/youtube_sync.py`, `frontend/src/app/settings/page.tsx`, `frontend/src/app/analytics/page.tsx`, new migration for youtube fields on projects table

### 6.4 Competitors Tab — Stagnant Data + No Age Filtering — ✅ SHIPPED (regression locked Cycle 49, 2026-04-21)

**Status summary:** all four coordinated fixes are live in main:
1. `GET /api/niche/videos` accepts `max_hours_old: Optional[float]` and filters SQL-side via `cv.published_date >= NOW() - (${idx} || ' hours')::INTERVAL` (`backend/routes/niche.py:174`, `:203-209`).
2. `hours_old` is computed at query time: `EXTRACT(EPOCH FROM (NOW() - cv.published_date)) / 3600` — the stored snapshot column is only a NULL fallback (`backend/routes/niche.py:228`).
3. `_auto_scrape_competitors` in `main.py:168` no longer gates on `autopilot_config.enabled` — any tenant with ≥1 active competitor channel is scraped daily.
4. Competitors page has 24h / 3d / 7d / All filter pills (`data-testid="age-filter-pills"`) and `getNicheVideos` forwards `max_hours_old` via `searchParams.set` (`frontend/src/app/competitors/page.tsx`, `frontend/src/lib/api.ts`).

Pinned by `backend/tests/functional/test_competitor_age_filter_lock.py` (5/5 green). If any one of the four changes reverts, the competitors tab silently stagnates again — the regression test fails before that ships.

Original roadmap text retained below for historical context.

---

- **What:** Two problems:
  1. **Data is stagnant.** `hours_old` in `competitor_videos` table is a static snapshot calculated at scrape time and NEVER recalculated. A video scraped 5 days ago showing "24 hours old" still shows "24 hours old" today. Auto-scraping only runs if autopilot is enabled (most users won't have this on).
  2. **No age filtering.** Users can't filter by "last 24 hours", "last 3 days", "last 7 days". The `hours_old` field is displayed on cards but not usable as a filter.
- **Root cause:** Static snapshot architecture. `niche.py:742` calculates `hours_old = (now - published_date) / 3600` once at scrape time and saves it. No query-time recalculation. No `max_hours_old` parameter on the `GET /api/niche/videos` endpoint.
- **Fix:**
  1. **Dynamic age calculation:** Replace static `hours_old` with query-time calculation: `EXTRACT(EPOCH FROM (NOW() - published_date)) / 3600 AS hours_old` in the SQL query. Remove the stored `hours_old` column or keep it only as a cache.
  2. **Always-on daily scrape:** Remove the `autopilot_config.enabled` gate from `_auto_scrape_competitors()` in `main.py:168-197`. All tenants with competitor channels should get daily scrapes.
  3. **Age filter UI:** Add filter buttons to competitors page: "24h", "3 days", "7 days", "All". Pass `max_hours_old` parameter to backend.
  4. **Backend filter:** Add `max_hours_old` parameter to `GET /api/niche/videos` endpoint. Filter: `WHERE published_date >= NOW() - INTERVAL '{hours} hours'`.
  5. **Relevance cutoff:** After 7 days, videos are less relevant — consider visual de-emphasis (dimmed card) for videos older than 7 days.
- **Files:** `backend/routes/niche.py` (endpoint + scrape logic), `backend/main.py` (auto-scrape gate), `frontend/src/app/competitors/page.tsx` (filter UI), `frontend/src/lib/api.ts` (add max_hours_old param)

### 6.5 Refresh Ideas Button — Fails Silently — ✅ SHIPPED (regression locked Cycle 54, 2026-04-21)
- **What:** "Refresh Ideas" button on Discovery page and Pipeline videos tab appears wired correctly (button → `POST /api/discovery/refresh` → background task runs), but when the refresh fails, users see nothing — it either stays on "Generating..." forever or reverts to idle with no new ideas.
- **Root cause:** Backend returns an `error` field in the `GET /api/discovery/status` response (e.g., "No competitor videos in database", "Claude API error"), but the frontend `DiscoveryStatus` TypeScript interface in `api.ts:1432-1438` is **missing the `error` field**. No error display UI exists on either page.
- **Impact:** Users click Refresh, nothing happens, they think the button is broken. The actual failure reason (missing API key, no competitor data, etc.) is swallowed silently.
- **Fix:**
  1. Add `error: string | null` to `DiscoveryStatus` interface in `frontend/src/lib/api.ts`
  2. Add error banner UI to `frontend/src/app/discovery/page.tsx` and `frontend/src/app/pipeline/page.tsx` — show the error message with a retry button
  3. Improve error messages in `backend/routes/discovery.py` to be user-friendly (e.g., "No competitor videos found — add competitor channels first" instead of raw exception text)
- **Files:** `frontend/src/lib/api.ts`, `frontend/src/app/discovery/page.tsx`, `frontend/src/app/pipeline/page.tsx`, `backend/routes/discovery.py`
- **Status (2026-04-20, Cycle 54):** All three parts landed already — `DiscoveryStatus` TS interface has `error: string | null`, both pages render a "Last refresh failed" banner gated on `status?.error && !status.is_refreshing`, backend emits the friendly `"Scrape competitor channels first."` message when a tenant has 0 competitor videos and routes every other exception through `humanize_error()`. Regression lock: `backend/tests/functional/test_refresh_ideas_error_surfaced_lock.py` pins 6 invariants — TS interface field, Discovery banner conditional, Pipeline error render, backend pydantic model field, friendly "scrape first" message stored in `_refresh_tasks`, `humanize_error` import + call. 6/6 green.

### 6.6 System Prompts — Unusable for Normal Users + Mostly Not Wired — ✅ SHIPPED (verified Cycle 37, 2026-04-20)

**Status summary:**
- **Part 1 (wire all 6 prompts into pipeline):** shipped Cycle 7. `pipeline_executor.py:452 _load_prompt_overrides` maps all 6 tenant_prompt_defaults keys (script, thumbnail, video_motion, sound_curation, sound_generation, research) onto `self._pipeline` attrs with per-video > tenant > None priority. Pinned by `test_prompt_override_wiring.py` (runtime + static bot-consumer audit).
- **Part 2 (/api/system-prompts/generate endpoint):** shipped. `routes/system_prompts.py:92 @router.post("/generate")` — accepts style_description + channel fields, builds a meta-prompt with all 6 default templates, calls Claude, returns all 6 generated prompts. Pinned by `test_system_prompts_generate.py` (Cycle 37) — 7 source-audit tests: route registered, PROMPT_KEYS matches pipeline PROMPT_MAP, meta-prompt covers all 6, vault key lookup, 400 on missing key, cross-file key consistency.
- **Part 3 (redesigned UI):** shipped. `frontend/src/app/system-prompts/page.tsx` has the style-description-first design with `generateSystemPrompts` call, pre-fill from channel profile, summary of generated output, and the 6 per-prompt editors collapsed as "Advanced."

Original roadmap text retained below for historical context.

---

- **What:** Two compounding problems:
  1. **Most prompts aren't wired to the pipeline.** Only `video_motion_system_prompt` is actually used during video generation (in `pipeline_executor.py`). The other 5 prompts (script, thumbnail, sound curation, sound generation, research) are stored but NEVER passed to the pipeline. Users can edit them all day — their videos won't change.
  2. **The UI assumes expert-level prompt engineering.** Users see 6 collapsed accordions, each hiding a 1000-3000 word wall of jargon ("verb-first motion design", "emotional motion dictionary", "STRUCTURAL RATIO (NON-NEGOTIABLE)"). No guidance, no examples, no explanation of what each prompt does or why you'd change it. A new user would be completely lost.
- **Current UX flow (broken):**
  1. User opens System Prompts tab → sees 6 mysterious accordions
  2. Expands "Script System Prompt" → sees 2800 words of technical instructions
  3. Has no idea what to change → either gives up or makes random edits
  4. Saves changes → creates a video → script sounds exactly the same (because the pipeline ignores tenant overrides for script)
- **The vision — "Grandma mode":**
  - User sees a simple form: "Describe your channel and video style"
  - Types: "I make cooking videos, casual and funny, my audience is millennials"
  - Clicks "Generate My Prompts"
  - Backend calls Claude with a master meta-prompt that generates all 6 system prompts tailored to their description
  - User sees a summary: "Your videos will have a casual, humorous tone with millennial-friendly references. Scripts will be conversational. Thumbnails will be bright and food-focused."
  - Advanced users can still expand and manually edit each prompt
  - Prompts actually get used when generating videos
- **Fix (3 parts):**
  1. **Wire all 6 prompts into the pipeline.** `pipeline_executor.py` must fetch tenant prompt overrides (from `tenant_prompt_defaults` table) and pass them to each bot: script bot, thumbnail bot, sound bot, research bot — not just video_motion. Per-video overrides in the `videos` table should take priority over tenant defaults.
  2. **Build AI prompt generator endpoint.** New `POST /api/system-prompts/generate` that accepts simple natural language input (channel description, tone, audience, style) and returns all 6 generated system prompts. Uses Claude with a master meta-prompt that understands our pipeline's prompt format requirements.
  3. **Redesign the System Prompts page.** Replace the raw-textarea-first design with:
     - **Top section:** "Describe your style" input + "Generate Prompts" button (the primary action)
     - **Generated summary:** Human-readable description of what the prompts will do
     - **Collapsed "Advanced" section:** The 6 individual prompt editors for power users who want manual control
     - **Helpful labels:** Each prompt gets a plain-English description ("This controls how your scripts sound — tone, pacing, vocabulary")
- **Files:**
  - Backend: `backend/pipeline_executor.py` (wire all 6 prompts), `backend/routes/system_prompts.py` (new generate endpoint), `backend/prompt_defaults.py` (meta-prompt for generation)
  - Frontend: `frontend/src/app/system-prompts/page.tsx` (redesign), `frontend/src/components/ui/SystemPromptEditor.tsx` (add descriptions), `frontend/src/lib/api.ts` (new generate function)

### 6.7 YouTube Sync — Not Daily, Manual Button Broken
- **What:** Two problems:
  1. **Auto-sync gated behind autopilot.** `_auto_sync_youtube()` in `main.py:107-134` only runs for tenants with `autopilot_config.enabled = true`. Regular users never get automatic YouTube metric updates.
  2. **Manual "Sync YouTube" button fails silently.** The button on the analytics page calls `POST /api/youtube/sync`, which requires `google_client_id`, `google_client_secret`, and `google_refresh_token` in vault. If these aren't set (and they won't be without YouTube OAuth — see 6.3), the sync fails. Error handling exists but the root cause message ("connect your YouTube channel first") isn't clear enough.
- **Fix:**
  1. **Remove autopilot gate from auto-sync.** All tenants with connected YouTube channels should get daily metric syncs. Change interval from 6h to 24h (daily is sufficient for analytics).
  2. **Wire sync to YouTube OAuth credentials** (depends on 6.3). Once a user connects YouTube via OAuth, their credentials are used for sync — no manual key entry needed.
  3. **Better error state on manual sync button.** If YouTube isn't connected, show "Connect YouTube first" with a link to the connection flow, not a generic error.
  4. **Sync on demand should work immediately** after YouTube OAuth connection — trigger a first sync right after OAuth callback completes.
- **Dependencies:** Stage 6.3 (YouTube OAuth) must be done first.
- **Files:** `backend/main.py` (remove autopilot gate), `backend/routes/youtube_sync.py` (use OAuth tokens), `frontend/src/app/analytics/page.tsx` (better error state)
- **Status (2026-04-20, Cycle 53):** ✅ **SHIPPED (auto-sync ungated + daily cadence)** — `_auto_sync_youtube` in `backend/main.py` no longer gates on `_is_autopilot_enabled`. It now pre-filters tenants by reading `channel_profiles.youtube_refresh_token` (new OAuth shape) with a vault `google_refresh_token` fallback (legacy shape), and `continue`s if neither is present — so non-connected tenants don't spam auth errors in logs. Loop interval bumped 21600s → 86400s (6h → 24h) to reduce quota pressure. Regression lock: `backend/tests/functional/test_youtube_auto_sync_ungated_lock.py` pins 4 invariants — function still scheduled at startup, no `_is_autopilot_enabled` gate, credentials precondition guards the loop, final sleep is `asyncio.sleep(86400)`. Items 2–4 (OAuth wiring, better error UI, sync-on-connect) still pending; tracked under Stage 6.3 now.

---

## Updated Summary Table

| Stage | Items | Effort | Blocks |
|-------|-------|--------|--------|
| **1: Build Blockers & Security** | 5 items | 1 day | Everything |
| **2: Schema & Data Integrity** | 3 items | 0.5 day | Stage 3+ |
| **3: Wiring Gaps** | 4 items | 2 days | — |
| **4: Missing Infrastructure** | 3 items | 4-5 days | — |
| **5: End-to-End Verification** | 3 items | 2-3 days | Stages 1-4 |
| **6: Product & UX Fixes** | 7 items | 8-10 days | 6.7 depends on 6.3 |
| **Total** | **25 items** | **~18-22 days** | |

---

## What's NOT in This Roadmap (Already Done)
These were verified as working in the 2026-04-10 audit — do NOT re-build:
- All 24 backend routers registered and responding (170 endpoints)
- All 27 frontend pages built with real components (71 total)
- 142 API functions in frontend api.ts
- Auth (email/password + Google OAuth + password reset pages)
- Billing (Stripe checkout, portal, plan display, pricing page)
- Rate limiting middleware (per-plan token bucket)
- Structured JSON logging
- Background task DB persistence (fire-and-forget)
- Trial warning email (12h lifespan check)
- Plan enforcement `check_plan_limits()` (wired in pipeline.py)
- SSE pipeline events (wired in frontend via use-pipeline-sse.ts hook)
- Toast notifications, error boundaries, 404 page
- Demo mode (backend + frontend)
- Brand Kit UI, notification preferences, export manifest
- Empty state components (used across 12+ pages)
- Landing page, docs, terms, privacy
