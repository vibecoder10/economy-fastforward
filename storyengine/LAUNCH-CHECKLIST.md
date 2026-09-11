# StoryEngine — Launch Checklist (the parts only Ryan can do)

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
