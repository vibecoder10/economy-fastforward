# GOAL — StoryEngine: production-ready for paying customers

**North star:** A brand-new customer can sign up, verify, onboard, pay, generate a video, come back later, and upgrade/cancel — reliably, in production, alongside other paying tenants. (Company goal: first 10 customers actually using it.)
**Success looks like:** the 7-step Definition-of-Done journey works end-to-end on a fresh account in prod, with no cross-tenant leaks, no fail-open billing, and no silent generation failures.
**Status:** Phases 1-4 done; 5 backend done (frontend owed); 6-7 code done, infra owed (Ryan); 8 = deploy + verify (needs 1-3 from Ryan). All code-level critical blockers I can verify headlessly are fixed + locked.
**Updated:** 2026-06-22

> This is a SEPARATE plan from `GOAL.md` (which tracks the visual-chain/storyboard
> quality work). Both are live; they don't overlap. Running log: `CHANGELOG.md`.

## Decisions locked (2026-06-22)
- **Domain/HTTPS:** `storyengine.dev` (app + API same origin) → Caddy + Let's Encrypt on the VPS (`infra/Caddyfile.example`, www→apex). Full script/connect CSP verified in-browser on deploy (Google Picker/OAuth are CSP-fragile).
- **Stripe:** go LIVE now. Code wired by Claude; live keys + dashboard objects by Ryan.
- **Trial:** 7-day free trial. Default after expiry = drop to Free tier (2 videos/mo).

## What needs Ryan (human approval / can't be done in code)
1. Stripe dashboard: create 3 products+prices (Starter $25 / Pro $40 / Studio $75),
   a webhook endpoint → `/api/billing/webhook`, enable the Customer Portal, get live keys.
2. Domain → VPS DNS; then Claude installs Caddy (needs the go to touch the live VPS).
3. Redis + an `arq worker` systemd unit on the VPS (install + enable).
4. Confirm the Supabase project is on Pro (daily backups) + decide on PITR.
5. Deploy to prod (kill + systemd revive) — only on Ryan's explicit go.

---

## Phase 1 — Stop the cross-tenant data leaks  `[done]`
Goal: one tenant can never read or delete another tenant's rows.
- [x] `supabase_adapter.py`: tenant-scope every title/status read + both DELETEs (13 methods) via a `_tw()` predicate; fuzzy ILIKE fallbacks now stay in-tenant.
- [x] `routes/review.py`: add `tenant_id` to the 3 storyboard approve/reject UPDATEs (latent IDOR).
- [x] Lock test `test_adapter_tenant_isolation.py` (every query carries tenant_id; deletes scoped in SQL; unbound adapter unchanged).
- [x] Fixed a pre-existing SQL-guard gap (videos.py bounded-`beat` storyboard col) so the suite is green.
Done when: isolation test + SQL-injection guard + existing adapter/isolation tests all pass. ✅ 2026-06-22.

Decision: the unauthenticated Drive media proxy (`routes/media.py`) was re-rated from
CRITICAL to **MEDIUM** — it's a capability gate over unguessable Drive file ids that are
only ever emitted to the owning tenant, with no enumeration. Not a launch blocker.
Tracked as a fast-follow (sign media URLs like the audio-token endpoint).

## Phase 2 — Billing correctness  `[mostly done]`
Goal: charges work, webhooks are safe, unpaid = no access, paid features are gated server-side.
- [x] Webhook idempotency (`stripe_events` table, migration 056, + INSERT ON CONFLICT) — stop double-fire.
- [x] Fail-closed on unpaid even when the price→plan map misses (+ `invoice.payment_failed` + `subscription.created` handled).
- [x] Trial expiry → Free tier (was silently → paid Starter); trial length 14→7 days.
- [x] Idempotent render-minute charge (migration 057 + per-video high-water mark; no double-count on re-render).
- [x] `require_plan(min_tier)` dependency added (ready); applying to Autopilot/Analytics/Competitor routes deferred to Phase 5 (needs frontend 402-handling so free users see an upgrade prompt, not a broken page).
- [ ] Atomic usage increment — NOT done. The check-then-act race is mitigated by `concurrent_jobs=1` on free/starter (serializes their creates) and immaterial on pro/agency (high caps). Documented as residual; the existing lock pins the check+increment shape, so a reserve-refund refactor is a deliberate later change.
- [ ] Wire Stripe env (`STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_*`) + `.env.example` — needs Ryan's live dashboard objects.
Done when: lock tests prove idempotent webhook, fail-closed entitlement, idempotent render charge. ✅ for the code; env + dashboard pending Ryan.

## Phase 3 — Generation reliability  `[done]`
Goal: a customer's pipeline never dies silently or hangs forever.
- [x] Detect Kie ban / credit-exhausted at the boundary (image poll raises a `KIE_ACCOUNT_BLOCKED` marker; text gateway short-circuits its retries); images bot aborts the run; worker treats it as terminal (no arq retry); `humanize_error` maps it to "update your Kie key in Settings → API Keys". Single-source detector `error_utils.is_kie_block`.
- [x] Periodic stuck-job reaper (`reap_stale_running_tasks`, 30-min loop, 3h threshold > 2h max job timeout) — unblocks a 1-job-plan tenant whose worker died, without an API restart.
- [ ] Per-tenant Kie spend counters (images/clips) — deferred (visibility nice-to-have, not a blocker).
Done when: lock tests for ban-handling + reaper; no infinite-spinner path. ✅ 2026-06-22 (`test_kie_block_and_reaper.py` 5/5).

## Phase 4 — Auth hardening  `[mostly done]`
- [x] Stronger password hashing: PBKDF2-SHA256 600k (OWASP floor), self-describing format, transparent rehash-on-login for legacy 100k hashes. (bcrypt/argon2 would need a new dep + VPS install — PBKDF2-600k ships now with zero deps; note as optional future upgrade.)
- [x] Rate-limit + soft lockout on login/register/forgot (in-memory per-IP + per-email sliding window; the global middleware skipped /api/auth).
- [ ] Email verification on the password signup path — moved to Phase 5 (needs `email_verified` column + token + email + a frontend verify page).
Done when: lock tests; manual signup → verify works. ✅ for hashing+throttle (`test_auth_hardening.py` 4/4); verification pending in Phase 5.

## Phase 5 — Onboarding to first value  `[backend done, frontend owed]`
- [x] One source of truth for "required keys": `dashboard.py` onboarding-status DERIVES `required_keys` from `pipeline.PIPELINE_REQUIRED_KEYS` (just Kie). Kills the permanent "finish setup" nag for correctly-set-up Kie-only users. Locked (`test_required_keys_single_source.py`).
- [ ] Enforce onboarding once in `AuthenticatedShell` (not per-page, escapable) — FRONTEND, verify in browser on deploy.
- [ ] Gate "Create Video" on keys with a clear prompt instead of a dead studio / cryptic fail — FRONTEND.
- [ ] Email verification on the password signup path (DoD step 2) — needs `email_verified` column + token + email + `/verify` page.
Done when: fresh account can't get stuck; reaches first artifact. (Backend trap fixed; rest in LAUNCH-CHECKLIST.)

## Phase 6 — Platform reliability  `[code done, infra owed]`
- [x] Global exception handler in `main.py` (clean JSON via humanize_error + track_error, no raw 500s).
- [x] Wrapped the raw `str(e)` leaks in `routes/videos.py` — `test_error_humanization` leak audit clean.
- [x] Security headers in `next.config.ts` (frame/MIME/referrer/permissions/HSTS + frame-ancestors/object-src/base-uri CSP). Full script/connect CSP deferred to when the HTTPS origin exists. Frontend typechecks clean.
- [x] Infra artifacts written: `backend/storyengine-worker.service`, `infra/Caddyfile.example`, expanded `.env.example`.
- [ ] HTTPS + domain + Caddy; Redis + worker; uptime monitor — INFRA (Ryan, LAUNCH-CHECKLIST §1/§2/§6).
Done when: HTTPS live, worker running, alerts fire on failure.

## Phase 7 — DB hardening  `[indexes done]`
- [x] Composite hot-path indexes (migration 058 + schema.sql): `assets(video_id,status)`, `assets(video_id,scene,image_index)`, `scripts(video_id,tenant_id)`.
- [ ] FK `ON DELETE` + soft-delete consistency on child tables — deferred (medium, not a launch blocker).
- [ ] Confirm Supabase backups/PITR — Ryan (LAUNCH-CHECKLIST §5).
Done when: indexes applied; delete paths don't orphan/RESTRICT-fail.

## Phase 8 — Verify the full journey  `[todo]`
- [ ] Walk the 7-step Definition of Done on a fresh account, end to end.
- [ ] Deploy to prod (Ryan's go) + prod smoke test.
Done when: a real new account completes signup→pay→generate→return→cancel.

> Post-launch (noted, not a blocker): RLS is currently inert because the backend
> connects as the table owner (superuser), so every policy is bypassed. Real
> isolation = the app-code `tenant_id` filters (Phase 1). Making RLS fire means a
> dedicated non-superuser app role + per-request `set_config` — a real project,
> deferred. Don't mistake the existing RLS policies for active protection.

## Log
- 2026-06-22 — Six-area launch audit (DB, auth, Stripe, onboarding, generation, platform). Plan written. Phase 1 done: cross-tenant adapter reads/deletes + review.py UPDATEs tenant-scoped, locked by tests.
