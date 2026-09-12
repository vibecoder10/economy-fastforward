# StoryEngine — Launch Checklist (the parts only Ryan can do)

## DVSU title-list channel automation — 2026-09-12

Outcome: an operator supplies a list of titles once; StoryEngine researches the right machines, verifies coverage and evidence, creates script/voice/images/thumbnail/video, checks the result, and advances the list automatically with durable progress and bounded recovery.
Definition of done: title-list intake and deduplicated durable queue; one representative real DVSU title passes the complete production path and output review; remaining items continue without stage-by-stage clicks; real blockers remain visible with saved work and an actionable reason. Use configured delivery visibility; public release/schedule is not invented.
Status: integrated implementation verified locally and against isolated PostgreSQL; second release and actual-video proof in progress. Updated: 2026-09-12.
Current step: release verified list-to-unlisted workflow. Next action: deploy backend/worker/frontend with migrations 157/158, attach Anton's existing video to the list without duplicating it, then verify actual research and production continuation.
Authority: Ryan explicitly approved deployment and execution of the channel-automation job in this task. Normal implementation, correction, required provider production and validation within this job are authorized; preserve completed videos and avoid duplicate paid jobs. Reuse existing configured providers. Current test title is Anton's British carrier video; no unrelated videos or random new titles.
Scope default: interpret the existing carrier title as British carrier designs and British carrier conversions, including export service with the operating navy stated. Audit escort/conversion classes; do not invent a Royal-Navy-only restriction that would silently discard Majestic. No arbitrary runtime padding or removal of real classes to pass a gate.
Blocker: none for current implementation/deploy/investigation.

| Boundary | Current evidence | Gap / acceptance needed |
| --- | --- | --- |
| Title -> roster | 15-class British roster saved; false class rejection fixed and deployed; omitted escorts/conversions independently identified | `roster_coverage.py` + executor: separate source-based omission review, cached against exact title/roster/boundary; corrective discovery before paid downstream stages |
| Per-machine research -> script | Existing per-machine research/repair and quality laws | Prove required evidence clears without manual card-by-card operation; preserve passed cards |
| Reference -> production image | Existing verified-reference cache and identity checks; alternative-search fix tested | Recover true reference misses and verify actual generated subject/era/views |
| Voice/thumbnail/render | Thumbnail failure fixed/deployed; voice was best-effort and could be skipped | `actions.py`: saved narration required at fresh and resumed gates; actual encoded output review still required |
| Run All durability | 217 local tests for current fixes | Approved release, exact-job live readback, actual continuation |
| List -> successive videos | Existing CSV/chat intake and calendar; launch used process-local tasks, queue stopped at launched, separate create/link writes, no duplicate keys, daily cadence | `routes/queue.py`, `main.py`, additive migration: atomic video link, deterministic title key, ARQ dispatch, serial progression, exact terminal readback and bounded recovery; calendar title-list UI |
| Delivery / ongoing operation | DVSU connected; previous unlisted delivery verified; finish previously stopped at render | `queue_delivery.py`, `youtube_publish.py`, queue/worker/actions and migration 158: explicit unlisted delivery, saved exact channel, durable ambiguous-insert protection, required thumbnail and owner/privacy readback. Global render-only default and legacy capped full_auto behavior preserved. |

- [x] Release the tested Run All repair. **Done when:** focused commit pushed/deployed, backend and worker match, API/queue healthy, original unrelated edits preserved. **Evidence:** commit `7efe09b98` pushed/deployed; deploy exit 0, worker parity verified, healthy API with ARQ, frontend HTTP 200, zero active work and normal drain readback.
- [x] Complete code/live gap audit and prioritize missing work. **Done when:** each missing boundary has a concrete owner/module and observable acceptance test; reuse existing paths instead of a parallel automation system. **Evidence:** boundary table and implemented owners below; existing queue, worker and publisher reused. Independent live coverage audit rejected incomplete original roster; its first response also exposed secondary-source/date weaknesses, corrected in the review prompt and gates before broader production.
- [ ] Implement title-list intake and durable progression gaps. **Done when:** test list creates each intended video once, automatically queues/resumes the next item, and survives retries without duplicate spend or blocking unrelated items.
- [ ] Repair source/roster and production-stage gaps on Anton's video. **Done when:** current-title roster is source-grounded, required evidence and correct references pass; script, voice, images and thumbnail complete through automated flow.
- [ ] Prove representative audiovisual output and delivery. **Done when:** actual encoded movie is visually/audibly reviewed, claims and subject identity spot-checked against sources, saved completion/delivery readback verified.
- [ ] Verify list progression and finish operating contract. **Done when:** list-level state advances from completion/failure correctly without stage clicks; quality/budget/provider blockers and next automatic action are visible; checklist/evidence and storage receipt complete.
Execution evidence: reuse `tasks/dvsu-run-all-learning.json`; prior narrow repair details below. Parent integrated **235 tests passed**, Python compilation, frontend TypeScript and 4 UI-model tests passed. Browser verified DVSU mode/delivery defaults, two unique titles from a three-line duplicate input, disabled empty submit. Actual PostgreSQL isolated-schema proof passed: 2 concurrent requests -> 1 winner; normalized replay inserts 0; failed managed item allows next; reserved video reused; live legacy claim blocks until release. `tasks/dvsu-queue-db-proof.json`; all probe schemas dropped and absence verified. Probe exposed UUID/text advisory-lock mismatch, repaired in both real claim paths. Remote owned temporary scripts removed (6,745 + 49,415 bytes); no media/accepted-source deletion. Second release and encoded/unlisted production proof remain unchecked.

## DVSU Run All automation — 2026-09-12

Outcome: verify Anton's new carrier video matches its title and repair Run All so required research and production stages continue automatically.
Definition of done: exact live stop diagnosed; roster checked against independent historical sources; durable fixes pass affected positive/negative regressions; deployment and production proof recorded separately.
Status: local implementation and integration checks complete; production proof pending. Updated: 2026-09-12.
Current step: deployment approved; preparing focused commit. Next action: push verified main and use `scripts/se.sh deploy dvsu-run-all-automation`; verify backend/worker parity and live health, then continue expanded channel-automation checklist above. No frontend/Remotion changes in this first release.
Blocker: none for approved deployment/execution. Live production proof pending.
Boundaries: canonical checkout `/Users/ryanayler/economy-fastforward/storyengine`, main at `973caefc`; preserve existing dirty UI/docs and accepted video assets. No publication or duplicate paid generation.
- [x] Diagnose exact video, title/roster accuracy and automation stop. **Done when:** live saved state and independent sources explain the mismatch/missing work. **Evidence:** `3f902e62-3ffa-4472-baf4-d0dfe9a20e49`, 15 roster entries, 10 verified photos/5 misses, zero research cards; saved pipeline failure rejects Illustrious/Audacious/Centaur because completed-count descriptions mention planned orders. Research memo documents missing British escort types and scope inconsistencies. Browser inspected all ten displayed references; Majestic image shows Australian HMAS Melbourne with US Midway behind it. Sources/readback in `tasks/dvsu-run-all-live-audit.json` and `tasks/dvsu-british-roster-audit.md`.
- [x] Implement required automation repairs (local). **Done when:** Run All handles missing research/reference work and resumes valid completed stages without silently accepting incomplete artifacts. **Evidence:** completed-class detection; current-gate resume and invalid-roster corrective discovery; two bounded carrier-specific photo searches retaining identity checks; truthful stalled/review/thumbnail failures; durable ARQ Run All dispatch with exclusive claim, uncertain-enqueue reconciliation and exact-job terminal state; research prompt audits national scope and escort categories.
- [x] Verify affected workflow (local). **Done when:** original failure and relevant negative cases pass meaningful regressions; remaining external dependencies are explicit. **Evidence:** parent integrated 217 tests passed, Python compilation and diff check passed; source fact audit and all ten visible photo thumbnails inspected. No production generation, worker-kill experiment or encoded-output review performed. Whole-build worker timeout 7200s/max 3 tries; forced death after retry exhaustion relies on existing 180-minute stale reaper and remains unproven live. Final roster completeness is not certified pending nationality boundary and corrected research.
- [ ] Deploy and prove live continuation. **Done when:** authorized focused release and exact-video readback demonstrate continuation; no claim of full production completion without actual output review.
Evidence/learning receipt: `tasks/dvsu-run-all-learning.json`.
Local evidence: 217 integrated regression tests passed in `tasks/dvsu-run-all-learning.run-all-regressions.log`; original stop/unfinished negative cases, actual executor resume, reference alternative search/identity rejection, saved-thumbnail completion, explicit stalled-stage reporting and queue/recovery behavior covered. Existing Starlette deprecation warning only in this suite. Worker also observed an older separate C16d test collection issue (pre-existing stub lacks `_unit_display_name`); not counted as passing. Read-only provider checks: Anthropic/ElevenLabs/Kie valid; Kie reports 9608 credits, no generation proof implied. Learning receipt remains open through the pending production proof.
Storage: no render/download batch. Internal available 19GiB; keep expensive media work off internal storage. Existing bounded caches retained: pytest 44KiB, functional bytecode 956KiB at measurement. Small audit/learning evidence retained (~36KiB before final log); completed remote provider-preflight script 649 bytes -> absent, verified by remote test; physical recovery below disk reporting precision. Zero media/source deletions, VPS free 141GiB.

## DVSU customer YouTube connection — 2026-09-08

Outcome: allow the supplied customer email to authorize DVSU and provide a usable customer handoff.
Status: customer connected; carrier video uploaded and unlisted visibility verified. Updated: 2026-09-11.
Current step / next action: deploy approved tested thumbnail handling and verify live version. Current video's thumbnail repaired; no public release authorized.
- [x] Repair existing YouTube thumbnail. **Done when:** thumbnails.set succeeds for h9P3mFlwP58 and actual thumbnail is visually verified; never re-upload video. **Evidence:** source PNG 3,739,963 bytes exceeded YouTube 2MB limit and was labeled JPEG by old adapter. Converted same design to compliant JPEG; thumbnails.set returned thumbnailSetResponse; YouTube CDN visually shows carrier/title/red-arrow design. Exact channel checked before update; existing video retained.
- [x] Durable thumbnail completion handling (local). **Done when:** regression tests prove failure is visible and retry repairs thumbnail without duplicate video; source normalized within provider limits. **Evidence:** parent ran backend venv pytest on test_youtube_publish_quota, test_c16e_upload_skip_if_done, test_c33_youtube_quota: 45 passed, existing Starlette deprecation warning; diff check passed. Normalization, bounded transient retries, persisted partial failure, thumbnail-only retry/quota and explicit force behavior covered. System Python 3.9 was rejected before tests; rerun used project Python 3.11. Repair storage: JPEG was 465,011 bytes; removed only completed repair's two temporary image copies (4,204,974 bytes total), original Drive source and YouTube output preserved; VPS 141G available.
- [ ] Deploy thumbnail completion handling. **Done when:** approved focused commit deployed and live behavior verified. Ryan approved deployment; 45 focused tests rechecked passing, services healthy, no active tasks or deploy lock; unrelated dirty changes excluded.
Blocker: none for upload preflight. Google app remains Testing; this does not complete long-term production verification.
- [x] Verify customer connection. **Done when:** saved channel matches Anton's supplied ID and token exists. **Evidence:** live readback confirms UCO4gtSa3rpOutrZ45-OjYyA, Designed vs Used, token present on 2026-09-11.
- [x] Upload carrier video as unlisted. **Done when:** YouTube readback confirms the video on the correct channel with unlisted visibility. **Evidence:** YouTube videos.list confirms h9P3mFlwP58 on UCO4gtSa3rpOutrZ45-OjYyA, privacyStatus unlisted, madeForKids false, duration PT26M50S; processing still underway. One upload request, no forced retry. VPS had 141G available; existing uploader owns temporary download cleanup; source/master preserved.
- [x] Verify YouTube processing and playback. **Done when:** processing succeeds and uploaded video plays. **Evidence:** YouTube API reports processed/succeeded, correct channel and unlisted visibility. Browser player displayed video imagery and advanced from 0:00 to 0:14 with changing captions, then paused. This is a playback spot-check, not a full editorial/audio review. Link https://www.youtube.com/watch?v=h9P3mFlwP58. No media downloaded or new render scratch created during verification.
Authority: Ryan supplied the customer email for this previously approved connection; do not send a message or authorize the customer's Google account.
Definition of done: saved test-user readback and a verified customer connection route.

- [x] Correct customer invitation target. **Done when:** existing live link displays owner-supplied `UCO4gtSa3rpOutrZ45-OjYyA` and remains unused with renewed 48-hour expiry. Keep exact-channel guard and do not relabel an existing token as connected to the new ID. **Source:** Anton's channel URL supplied by Ryan on 2026-09-09; previous stored ID was incorrect. **Evidence:** scoped update of unused invitation e7a8483c-a24f-4bbc-ac86-cd9eb12f062b; database readback confirms correct ID, unused status, expiry 2026-09-12 04:01:51 UTC; existing public landing displays correct ID and Designed vs Used. No token/profile relabeling or guard bypass; customer authorization remains unverified.

- [x] Add customer test user. **Done when:** Google Cloud lists the supplied email in the dedicated project's audience. **Evidence:** Chrome Audience page for `storyengine-youtube-prod` shows saved row `howtotonys@gmail.com` on 2026-09-08.
- [x] Provide customer connection handoff. **Done when:** customer route is available without Ryan sharing his login. **Evidence:** live landing and Google redirect verified; actual customer consent pending.
  - [x] Implement expiring invitation, browser-bound OAuth state and exact channel match. **Done when:** valid connection saves only intended tenant; expired/replayed/wrong-channel attempts fail. **Evidence:** 14 focused tests pass (8 invitation + 6 OAuth diagnostics).
  - [x] Deploy and create customer link. **Done when:** live unauthenticated landing displays DVSU and Google authorization uses dedicated client; give Ryan message/link. **Evidence:** deployed 861503de4; frontend build passed; live Google chooser uses dedicated client and both scopes; callback invalid-state case shows safe error without login; DB invitation unused, expires 2026-09-10 21:00 UTC. Initial build needed Suspense, Google redirect needed CSP form-action correction; both verified after repair. Link kept out of tracker because it is a bearer invitation.

All the CODE-level launch blockers are fixed and tested (see `CHANGELOG.md` /
`LAUNCH-READINESS.md`). These remaining items need your accounts, your domain,
or a live-prod action, so they're yours. Do them in order; nothing here needs
code changes.

## 1. HTTPS + domain — storyengine.dev  (blocks Stripe live + secure logins)
- [ ] DNS A records → VPS `76.13.119.181`:
      `storyengine.dev` and `www.storyengine.dev`.
- [ ] On the VPS: install Caddy, put `infra/Caddyfile.example` at
      `/etc/caddy/Caddyfile` (already set to storyengine.dev + www→apex redirect),
      `sudo systemctl reload caddy`. Caddy auto-issues the HTTPS cert.
- [ ] In `storyengine/.env`: `FRONTEND_URL`, `ALLOWED_ORIGINS`, `NEXT_PUBLIC_API_URL`
      = `https://storyengine.dev` (already the defaults in `.env.example`).
- [ ] Rebuild the frontend (`npm run build`) — `NEXT_PUBLIC_API_URL` is baked in at
      build time — then restart both services.
- [ ] Full CSP (script-src/connect-src): I'll finalize + verify this IN THE BROWSER
      once it's live — this app uses the Google Drive Picker + Google OAuth, which are
      CSP-fragile, so it must be tested against the real deploy, not guessed. The safe
      header set (frame/MIME/referrer/HSTS + frame-ancestors/object-src) is already on.

## 2. Redis + arq worker  (blocks reliable generation under load)
- [ ] Install Redis on the VPS and enable it.
- [ ] Set `REDIS_URL` in `storyengine/.env` (default `redis://localhost:6379`).
- [ ] Install + enable `backend/storyengine-worker.service` (mirrors the backend
      unit). Confirm `app.state.arq` is non-None at startup (logs).
      Without this, every pipeline stage runs inside the web process.

## 3. Stripe — LIVE mode  (blocks taking payment at all)
In the Stripe dashboard (live mode):
- [ ] Create 3 products with recurring monthly prices matching the pricing page:
      **Starter $25, Pro $40, Studio $75**.
- [ ] Copy each Price ID into `storyengine/.env`:
      `STRIPE_PRICE_STARTER`, `STRIPE_PRICE_PRO`, `STRIPE_PRICE_AGENCY`.
      (These must match exactly — a wrong ID makes the webhook fall back to `free`.)
- [ ] Set `STRIPE_SECRET_KEY` (`sk_live_…`).
- [ ] Create a webhook endpoint → `https://storyengine.dev/api/billing/webhook`,
      subscribed to: `checkout.session.completed`, `customer.subscription.created`,
      `customer.subscription.updated`, `customer.subscription.deleted`,
      `invoice.payment_failed`. Put the signing secret in `STRIPE_WEBHOOK_SECRET`.
- [ ] Enable the **Customer Portal** (Billing → Customer portal) and allow
      cancel / switch-plan / update-card. The portal 500s until this is on.
      Upgrades/downgrades + proration are configured here (no code path for them).

## 4. Secrets + safety env  (set before launch)
- [ ] `SESSION_SECRET` — `openssl rand -hex 32`. Auth fails closed without it.
- [ ] `HEALTH_TOKEN` — otherwise `/api/health/detailed` is wide open.
- [ ] Confirm `DEV_MODE` is unset (no dev-token login in prod).
- [ ] Rotate the Supabase DB password (it's only in local `.env`, but hygiene).

## 5. Supabase backups  (data-loss protection)
- [ ] Confirm the Supabase project is on **Pro** (daily backups, 7-day retention).
      Free tier has NO automated backups. Enable PITR if you can't tolerate any
      data loss. Write a one-line restore runbook.

## 6. Observability  (know when it breaks)
- [ ] Add an uptime monitor (UptimeRobot / Better Stack) hitting
      `https://storyengine.dev/api/health`.
- [ ] (Optional, I can wire it) Reuse the existing ntfy.sh canary topic to alert
      on the backend error-rate threshold.

## 7. Then verify the full journey  (I'll drive this once 1-3 are live)
Sign up → verify → onboard → pay (real card, you can refund) → generate a video →
log back in → cancel via the portal. This is Phase 8 in `LAUNCH-READINESS.md`.

---
### Still owed on the CODE side (frontend, needs the live app to verify)
These are written up but want browser verification on the deployed HTTPS app:
- Enforce onboarding app-wide (AuthenticatedShell) + make "Create Video" route to
  the keys modal when keys are missing (instead of a dead studio).
- Email verification on the password signup path (DoD step 2): add the
  `email_verified` column + token + verification email + a `/verify` page.
- Attach `require_plan(...)` to the Autopilot/Analytics/Competitor routes once the
  frontend shows a clean upgrade prompt on 402.
I'll do these against the running app so I can confirm them in the browser.
