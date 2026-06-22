# StoryEngine — Launch Checklist (the parts only Ryan can do)

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
