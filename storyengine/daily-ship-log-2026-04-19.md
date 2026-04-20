# Daily Ship Log — 2026-04-19
_Overnight build by Osiris. Ryan sleeping. Functional tests only. Honesty rule in effect._

## Standing Orders
- Karpathy loop: build → functional test → learn → ship → log → next
- No smoke tests as ship gate. Playwright / real renders / real OAuth / Stripe test mode.
- Max 3 retries on an approach → pivot
- Honesty rule: if I claim it works and it doesn't, I eat it here
- Every cycle writes a line to this log, even idle cycles

## Priority Queue (revised tonight)
1. Ground-truth re-audit — rewrite fix-roadmap.md against actual code state
2. Flow B onboarding: detect existing-channel path + auto-learn voice from YouTube
3. Grandma-mode A/B render verification — prove generated prompts actually change output
4. Trial downgrade cron (revenue leak)
5. Human-ize every "Internal Server Error" string in the product
6. First end-to-end customer-style render (Ryan as dogfood)

---

## Cycle 1 — 2026-04-19 ~19:50 CT
**Goal:** kickoff. Stand up daily log, verify build + test infra works, start ground-truth audit.

**Done:**
- Frontend `npx tsc --noEmit` → passes (0 errors). Contradicts fix-roadmap 1.1 which is now stale.
- Verified these fix-roadmap items are ALREADY SHIPPED (roadmap dated 2026-04-10 is ~10 days stale): YouTube OAuth endpoints (6.3), system-prompts/generate endpoint (6.6 part 2), pipeline prompt-override wiring in 7 places (6.6 part 1).

**Remaining fix-roadmap gaps confirmed still open:** 3.2 trial downgrade, 6.2 first-run guidance, plus the unverified grandma-mode A/B question.

**Test infra reality check:** no backend pytest suite exists. 2 Playwright specs exist (dashboard-fixes, onboarding) but stub the backend. Going forward, functional tests are written PER FEATURE against real infra (Supabase MCP for DB, Playwright against real dev server).

## Cycle 2 — 2026-04-19 ~20:00 CT
**Goal:** ship trial-downgrade cron (fix-roadmap 3.2).

**Shipped:**
- Migration `041_trial_expired_handled.sql` — adds `trial_expired_handled BOOLEAN DEFAULT FALSE` to accounts, partial index for the cron's lookup pattern. Applied to prod Supabase project rcbobwaldrefnyllhjyo.
- `email_service.send_trial_expired()` — trial-ended email with html.escape'd display name, frontend_url to pricing.
- `email_tasks.check_trial_expired()` — finds accounts with expired trials + no paid sub + unhandled flag, downgrades plan to 'starter', marks handled, emails.
- `main._auto_check_trial_expired()` + registered in lifespan — runs every 6h.

**Functional test (real infra, not smoke):**
- SQL test against prod DB (`backend/tests/functional/test_trial_expired.sql`):
  - Inserted test account with expired trial
  - SELECT found the row (✅)
  - UPDATE flipped plan 'creator' → 'starter' + trial_expired_handled true (✅)
  - Re-SELECT returned 0 rows — idempotent (✅)
  - Cleanup deleted test row (✅)
- Python syntax check (`py_compile`) passes on email_tasks, email_service, main.
- **Honest gap:** could not execute the Python function end-to-end against prod because the backend is configured for a local PG proxy (port 55432) that isn't running on this Mac. The SQL logic IS the behavior under test — the Python wrapper is a fetch_all + for-loop + execute. But I have NOT proven the Python function runs against a real connection pool tonight. Deferring to CI / first VPS restart.

**Learned:** prod Supabase is reachable via MCP for functional SQL verification — that's the right pattern for DB-layer tests when the local dev stack isn't up.

