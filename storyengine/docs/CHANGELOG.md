# StoryEngine Launch-Readiness CHANGELOG

Running log for the "production-ready for paying customers" mission.
Plan: `LAUNCH-READINESS.md`. Format per phase: Issues → Fixes → Remaining risks.

---

## 2026-06-22

### Audit (all six areas)
Ran a six-area read-only audit (DB/multi-tenancy, auth, Stripe, onboarding,
generation reliability, platform/infra). Headline: the core is more solid than
feared (account isolation mostly disciplined, JWTs sound, webhook signature
verified, generation resumes mid-failure). Real launch-killers: no payment path
configured at all, plain-HTTP bare IP, two data-isolation gaps, non-idempotent
webhook, opaque failure when a tenant's Kie key is banned.

### Phase 1 — Cross-tenant data leaks  ✅ DONE

**Issues discovered**
- `supabase_adapter.py` — the per-tenant adapter (built with `tenant_id` in
  `pipeline_executor.py:200`) ignored that tenant_id in every title/status
  lookup. `get_ideas_by_status` did a global status scan (could pull another
  tenant's video into a pipeline run); `find_idea_by_title` / `get_scripts_by_title`
  / `get_all_images_for_video` matched by title across all tenants (+ a fuzzy
  ILIKE fallback); `delete_scripts_for_video` / `delete_images_for_video` DELETEd
  by title across all tenants. Auto-triggers on any title/status collision — no
  secret needed. This was the real exploitable isolation bug.
- `routes/review.py` — storyboard approve/reject/approve-all gated the SELECT by
  tenant but the follow-up UPDATE used `WHERE id = $1` only (latent IDOR if the
  gate is ever refactored away).
- (Pre-existing) `routes/videos.py` bounded-`beat` storyboard column interpolation
  wasn't in the SQL-injection guard's allowlist, so that guard was failing 3/4.

**Fixes implemented**
- Added `SupabaseAdapter._tw()` — a tenant-isolation predicate that AND-s
  `tenant_id = %s` into every title/status query when a tenant is bound, and is a
  no-op for standalone/CLI callers (no tenant). Applied to 13 methods including
  both DELETEs; fuzzy ILIKE fallbacks now stay in-tenant.
- `review.py`: added `AND tenant_id = $2` to all three UPDATEs.
- New lock test `tests/functional/test_adapter_tenant_isolation.py` — proves every
  query carries the tenant param, both deletes are scoped in SQL, and an unbound
  adapter is unchanged. (3/3 pass.)
- Whitelisted `tw` in the SQL-injection guard's `_SAFE_EXPR_NAMES` (it's a constant
  fragment with a hardcoded alias + parameterized value — same category as the
  existing `where`/`cols`). Added the two pre-existing `videos.py` storyboard-col
  lines to `_VERIFIED_SAFE`. SQL guard now 4/4.
- Regression-checked: adapter col-allowlist (5/5), characters (5/5), cancel (7/7) all green.

**Remaining risks**
- The Drive media proxy (`routes/media.py`) stays an UNAUTHENTICATED capability
  gate: it serves any Drive file id present in our DB, without checking the file
  belongs to the requesting tenant. Re-rated CRITICAL→MEDIUM: file ids are long,
  unguessable, not enumerable, and only ever emitted to the owning tenant, so a
  cross-tenant read needs an out-of-band id leak (same model as an S3 presigned
  URL or a YouTube unlisted link). Fast-follow: sign media URLs with a short-lived
  tenant-scoped token like the existing `/audio-token` endpoint.
- RLS policies in the schema are inert (backend connects as table owner / superuser,
  which bypasses RLS). Real isolation is the app-code filters above. Switching to a
  non-superuser app role is post-launch.

### Phase 2 — Billing correctness  ✅ CODE DONE (env + dashboard pending Ryan)

**Issues discovered**
- Webhook was NOT idempotent — Stripe's at-least-once retries re-fired handlers
  (duplicate receipt emails, double side effects). No dedup table existed.
- `_handle_subscription_updated` failed OPEN: if a non-active subscription's price
  didn't map to a known plan, it left `plan` untouched, so an unpaid customer kept
  full access. `invoice.payment_failed` and `subscription.created` weren't handled.
- Expired trials dropped to `'starter'` — a PAID tier — handing out paid access free.
- Every successful render incremented `tenant_usage.render_minutes` unconditionally,
  so re-rendering one video (normal during editing) billed the monthly allowance again.
- Paid features (Autopilot/Analytics/Competitor) had no server-side plan check.

**Fixes implemented**
- `stripe_events` dedup table (migration 056 + schema.sql). Webhook now INSERTs the
  event id ON CONFLICT DO NOTHING before dispatch and skips duplicates.
- `_handle_subscription_updated` rewritten to fail CLOSED: any non-active status sets
  `plan='free'` regardless of price mapping. Added `_handle_payment_failed` (→ past_due
  + free) and routed `customer.subscription.created` to the updated handler.
- Trial expiry → `'free'` (was `'starter'`); trial length 14→7 days (`TRIAL_DAYS` const).
  Updated the trial-downgrade lock test to assert `'free'` and forbid any paid tier.
- Idempotent render billing: `videos.render_minutes_charged` high-water mark (migration
  057 + schema.sql) + `_charge_render_minutes()` that charges only the delta above what
  the video was already charged. Replaced both unconditional increment sites.
- Added `require_plan(min_tier)` dependency (trial users resolve to 'pro', so they pass).
- New lock test `test_billing_failclose_idempotency.py` (fail-closed + payment_failed +
  active-grant + idempotency wiring). All billing locks green (webhook 6/6, plan-limits
  5/5, trial 7/7, drift 4/4).

**Remaining risks**
- Stripe is still UNCONFIGURED in prod — needs Ryan to create live products/prices, a
  webhook endpoint → `/api/billing/webhook`, enable the Customer Portal, and set
  `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` / `STRIPE_PRICE_{STARTER,PRO,AGENCY}`
  on the VPS. No code change makes payments work without this.
- `require_plan` is not yet ATTACHED to the premium routers — deferred to Phase 5 so the
  frontend can show a clean upgrade prompt on 402 instead of a broken page. Until then,
  plan tiers for those features remain UI-only.
- check-then-act race on the video/render limit is unaddressed (mitigated by
  concurrent_jobs=1 on low tiers; high caps on pro/agency). Reserve-refund refactor later.
- Post-expiry trial default = Free tier (Ryan can change to lock-until-pay).

### Phase 3 — Generation reliability  ✅ DONE

**Issues discovered**
- Kie is the single upstream for text+image+video+voice. A banned / out-of-credit
  key (the literal `用户已被封禁` string, or an insufficient-credit code) failed
  OPAQUELY: the image poll returned a silent None → bot reported "X images still
  pending" → 3 retry rounds → arq retried the stage 2-3x. The customer saw an
  un-actionable message and the whole retry budget burned against a dead key.
- A worker that died mid-stage left a `background_tasks` row stuck 'running'.
  `recover_stale_tasks()` only ran at API startup, so on free/starter
  (concurrent_jobs=1) one zombie row blocked ALL further generation for that
  tenant until someone restarted the API.

**Fixes implemented**
- Single-source detector `error_utils.is_kie_block()` + `KIE_BLOCK_MARKER`; covers
  the Chinese ban strings, insufficient-credit/balance text, and our own marker.
- `image_client.poll_for_completion` now RAISES `RuntimeError("KIE_ACCOUNT_BLOCKED: …")`
  on a block (instead of silent None), and re-raises blocks caught in the poll loop.
- `images/run.py` per-item handler re-raises a block so `gather()` aborts the whole
  run instead of burning every image + 3 retry rounds.
- `kie_unified.py` text gateway detects a block in the HTTP error/empty-content
  paths and raises the marker immediately (no more blind retries).
- `worker._terminal_failure()` makes a Kie block TERMINAL — persists the humanized
  "fix your Kie key" copy and returns WITHOUT re-raising, so arq doesn't retry.
- `humanize_error` maps any block signal to "Your Kie.ai key looks blocked or out
  of credit … update it in Settings → API Keys" (checked before the generic auth branch).
- Periodic reaper `reap_stale_running_tasks()` (pipeline.py) + `_auto_reap_stale_tasks`
  lifespan loop (main.py, 30-min cadence). Threshold 180min > the 120min max job
  timeout, so it only ever reaps true zombies, never a live render.
- Lock test `test_kie_block_and_reaper.py` (5/5).

**Remaining risks**
- Per-tenant Kie SPEND is still unmetered (plan caps count videos + render-minutes,
  not per-image/clip Kie calls). A runaway video can exhaust a tenant's Kie credit
  without a counter. Deferred — visibility feature, not a launch blocker.
- Reaper threshold means a worker-death zombie blocks a 1-job tenant up to ~3h
  before auto-clearing. Tied to the 2h max job timeout; can't safely go lower
  without a worker heartbeat.

### Phase 4 — Auth hardening  ✅ hashing + throttle DONE (email-verify in Phase 5)

**Issues discovered**
- Passwords hashed with PBKDF2-SHA256 at 100k iterations — below the OWASP floor.
- `/api/auth/{login,register,forgot-password}` had NO brute-force protection: the
  global RateLimitMiddleware skips `/api/auth/` and keys on tenant_id (none exists
  pre-login), so an attacker could spray passwords at full speed.

**Fixes implemented**
- PBKDF2-SHA256 raised to 600k iterations in a self-describing hash format
  (`pbkdf2_sha256$<iters>$<salt>$<key>`). Legacy `salt:key` hashes still verify and
  are transparently re-hashed at the new factor on the next successful login.
- In-memory sliding-window brute-force guard (`_auth_rate_limit`): per-IP + per-email,
  10 attempts / 5 min, wired into login, register, and forgot-password. Honors
  `X-Forwarded-For` (for the coming reverse proxy).
- Lock test `test_auth_hardening.py` (4/4). Existing auth locks still green.

**Remaining risks**
- bcrypt/argon2 would be stronger than PBKDF2 but need a new dependency + VPS install;
  PBKDF2-600k is the no-dep launch choice. Optional future upgrade.
- Auth rate-limit state is per-process (in-memory) — correct for the single-worker
  deploy; move to Redis before scaling to multiple workers.
- 30-day JWT in localStorage is non-revocable (XSS exposure) — not addressed; tighten
  with shorter tokens / httpOnly cookie post-launch.
- Email verification not yet implemented — Phase 5 (Definition-of-Done step 2).

### Phase 5 (backend) — Onboarding key-trap  ✅ DONE

**Issue** — Three places disagreed on which API keys a tenant needs: onboarding
/status (`dashboard.py`) demanded 4 keys (anthropic, elevenlabs, elevenlabs_voice_id,
kie) while the pipeline `/readiness` gate needs only kie. A Kie-only tenant who was
correctly set up to generate was marked "onboarding incomplete" forever and nagged
to add keys the pipeline routes through Kie anyway.

**Fix** — `dashboard.py` now derives `required_keys` from `pipeline.PIPELINE_REQUIRED_KEYS`
(single source of truth). Lock test `test_required_keys_single_source.py` (2/2).

**Remaining (frontend, verify on deploy)** — enforce onboarding in AuthenticatedShell;
route "Create Video" to the keys modal when keys are missing; email verification.

### Phase 6 — Platform reliability  ✅ CODE DONE (infra owed)

**Issues** — No global exception handler (uncaught errors → raw 500). 3 raw `str(e)`
leaks in `routes/videos.py` (Drive sync + dialogue) surfaced third-party error bodies.
No security headers (clickjacking/MIME-sniffing). No HTTPS, no Redis/worker unit.

**Fixes** — Catch-all `@app.exception_handler(Exception)` in main.py returns clean
JSON via `humanize_error` + `track_error` (HTTPException keeps its own handler).
Wrapped the 3 leaks (the 4th, a positional ValueError parser message, is intentional
user copy and isn't matched by the leak lock). Security headers in `next.config.ts`
(X-Frame-Options DENY, nosniff, Referrer-Policy, Permissions-Policy, HSTS, + a
non-resource CSP: frame-ancestors/object-src/base-uri — the full script/connect CSP
waits for the HTTPS origin so it can't break the app now). Wrote the infra artifacts:
`storyengine-worker.service`, `infra/Caddyfile.example`, expanded `.env.example`.

**Remaining (Ryan)** — HTTPS+domain+Caddy, Redis+worker install, uptime monitor.

### Phase 7 — DB hot-path indexes  ✅ DONE

Migration 058 + schema.sql: `idx_assets_video_status(video_id,status)`,
`idx_assets_video_scene(video_id,scene,image_index)`, `idx_scripts_video_tenant(video_id,tenant_id)`
— the composites for the pipeline's most frequent filters. FK ON DELETE / soft-delete
consistency deferred (medium, not a blocker). Supabase backups = Ryan.

### Test-infra note (pre-existing, not introduced this session)
A few tests that `import routes.pipeline` under pytest hit
`ImportError: cannot import name 'stage_enabled_in_plan' from 'status_map' (unknown
location)` — a sys.path-shadowing artifact in the test harness (reproduced before any
change this session). The real backend imports cleanly (`python3 -c "import
routes.pipeline"` works; prod runs fine) and `status_map.py:370` defines the symbol.
Affects `test_cross_tenant_task_isolation` and one function in `test_error_humanization`.
Worth a conftest fix later; not a launch blocker.

---

## Summary — where StoryEngine stands for launch (2026-06-22)

**Fixed + locked (code):** cross-tenant data leaks (adapter + review.py); webhook
idempotency; fail-closed billing on unpaid; trial→Free + 7-day; idempotent render
charge; Kie-ban handling (fast, actionable, no budget burn) + stuck-job reaper;
stronger password hashing + auth brute-force guard; onboarding key-trap; global
exception handler + error-leak wrapping; security headers; hot-path indexes.
~13 new/updated lock tests, all green; full backend compiles; frontend typechecks.

**Needs Ryan (can't be done in code) — see LAUNCH-CHECKLIST.md:** Stripe live
products/prices/webhook/portal + keys; domain + HTTPS (Caddy) + frontend rebuild;
Redis + arq-worker service; Supabase backups/PITR; uptime monitor.

**Owed on the frontend (verify in the browser on the deployed HTTPS app):**
onboarding enforcement + create-gating, email verification, attach `require_plan`
to premium routes.
