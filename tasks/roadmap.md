# StoryEngine SaaS — Daily Journal & Roadmap

> "Topic in, video out" — but for every creator, not just us.

---

## Product Vision

**StoryEngine** transforms an internal AI video production pipeline into a multi-tenant SaaS platform where YouTube creators input a topic and receive a fully produced video draft — script, voice, visuals, sound, thumbnail, and render — with AI learning from their channel's performance to improve over time.

**Target Users:** YouTube creators (solo or small teams) producing educational, explainer, or documentary-style content who want to 10x their output without hiring a production team.

**Moat:** The learning loop. Every video a creator publishes feeds performance data back into the system, making future videos better. Competitors can copy features but not accumulated channel-specific intelligence.

---

## Current State Assessment (Revised 2026-04-04)

### What EXISTS and WORKS

| Layer | Status | Details |
|-------|--------|---------|
| **Video Pipeline** | 95% functional | 13-stage pipeline: idea → research → script → voice → image prompts → images → sound → video clips → thumbnail → render → upload. All stages tested end-to-end through image prompts. Voice/images/render need API keys. |
| **Backend API** | 150+ endpoints | **22 route modules** (FastAPI + asyncpg). Dashboard, videos, assets, pipeline (25+ endpoints), review, activity, settings, autopilot, billing, google_auth, profile, projects, preferences, channel_profile, niche, learning_extraction, youtube_sync, analytics, discovery, agents, skills, visual_styles. |
| **Database** | Multi-tenant + RLS | 19+ tables with tenant_id, **24 RLS policies**, 24+ indexes, 13+ migrations. Supabase PostgreSQL. Tables: tenants, users, memberships, accounts, videos, scripts, assets, competitor_channels, competitor_videos, learnings, title_insights, title_tests, stage_transitions, bot_activity, projects, user_preferences, autopilot_config, discovery_ideas, visual_styles. |
| **Frontend** | **23 pages** | Dashboard, pipeline, video detail (7 tabs), competitors, autopilot, analytics, settings, settings/keys, create, activity, review, calendar, discovery, learnings, render, storyboard, visuals, profile, **login**, **onboarding**. Next.js 16 + React 19 + TailwindCSS 4 + Framer Motion. |
| **Authentication** | ✅ Working | Email/password (PBKDF2-SHA256) + Google OAuth. JWT sessions (30-day). Auth middleware on all routes via `Depends(get_tenant_id)`. Login + signup pages exist. |
| **Onboarding** | ✅ Working | 3-step wizard: Channel setup → API keys → Ready. Skip options. Status tracking endpoint. |
| **Billing Backend** | ✅ Wired (no UI) | Stripe checkout, webhooks (subscription created/updated/deleted), customer portal, plan tracking in accounts table. 3 tiers (Starter/Pro/Agency). |
| **Multi-tenancy** | ✅ Strong | Tenant model + memberships (owner/admin/member roles). RLS on all user-facing tables. Query enforcement via `WHERE tenant_id = $1`. |
| **Autopilot** | Partial | Toggle + config exist. Launch endpoint is a stub. Learning loop memory system built but not wired to SaaS. |
| **Agent Team** | ✅ Live | 6 autonomous agents (all Opus): Orchestrator, Backend Dev, Frontend Dev, QA, Pipeline Tester, Security Auditor. PRD decomposition + auto-execution. RUBRIC command center at :5050. |
| **Background Tasks** | 4 auto-tasks | YouTube sync, learning extraction, title analysis, competitor scraping. Run in-process (asyncio). |

### What's MISSING for SaaS (Revised — many gaps now CLOSED)

| Gap | Severity | Status |
|-----|----------|--------|
| ~~Authentication~~ | ~~CRITICAL~~ | **✅ DONE** — Email/password + Google OAuth + JWT |
| ~~Onboarding~~ | ~~CRITICAL~~ | **✅ DONE** — 3-step wizard works |
| ~~Billing Backend~~ | ~~CRITICAL~~ | **✅ DONE** — Stripe checkout + webhooks + portal |
| **Billing UI (frontend)** | CRITICAL | No `/billing` page. Can't purchase. Stripe is wired but invisible to users. |
| **Plan Enforcement** | CRITICAL | No feature gating. Free users can do everything paid users can. |
| **Password Reset** | HIGH | No recovery flow. Users locked out if they forget password. |
| **3 Broken Endpoints** | HIGH | `create-idea` (undefined fn), `upload` (missing endpoint), `skills/pipeline/*` (route ordering bug). |
| **Job Queue** | HIGH | In-process asyncio. Server restart = lost jobs. No retry/priority/dead-letter. |
| **Asset Storage** | HIGH | Single Google Drive. No per-tenant isolation. Kie.ai temp URLs expire. Supabase Storage partially wired. |
| **Error Monitoring** | HIGH | Console only. No Sentry. No structured error tracking. |
| **Email Notifications** | MEDIUM | Slack-only. No transactional email (welcome, password reset, billing). |
| **Team Invitations** | MEDIUM | Multi-tenant schema supports teams, but no invite flow, no role enforcement in app layer. |
| **Landing Page** | MEDIUM | No marketing site. No pricing page. No demo. |
| **Documentation** | MEDIUM | No help docs, no API reference, no tooltips. |
| **Rate Limiting** | MEDIUM | No per-tenant API rate limits or concurrent job limits. |
| **Video Preview** | LOW | No in-app video player for final output. |
| **Audit Logging** | LOW | No `audit_logs` table. `stage_transitions` + `bot_activity` partial. |
| **Data Export** | LOW | No GDPR export. No bulk download. |

---

## SaaS Pricing Model (Proposed)

| Plan | Price | Videos/mo | Features |
|------|-------|-----------|----------|
| **Starter** | $49/mo | 4 | Pipeline, 1 visual style, basic analytics |
| **Creator** | $149/mo | 15 | + Autopilot, learning loop, 3 visual styles, priority render |
| **Studio** | $399/mo | 50 | + Team (3 seats), all styles, API access, white-label render |
| **Enterprise** | Custom | Unlimited | + SSO, dedicated infra, custom integrations |

**Usage-based add-ons:** Extra videos ($8/each), premium voice clones ($20/mo), 4K render ($3/video).

**API cost pass-through:** Platform absorbs Claude/ElevenLabs/image gen costs within plan limits. Overages billed at 1.5x cost.

---

## Implementation Roadmap (Revised 2026-04-04)

> Many Phase 0 items are now DONE. Roadmap restructured to reflect actual state.

### Phase 0: Foundation — ~~"Make it Real"~~ ✅ MOSTLY COMPLETE
> Auth, onboarding, billing backend already exist.

- [x] **0.1 Auth integration** — ✅ Email/password (PBKDF2-SHA256) + Google OAuth + JWT sessions (30-day)
- [x] **0.2 Auth middleware** — ✅ All 22 route modules use `Depends(get_tenant_id)`
- [x] **0.3 Login/Signup pages** — ✅ `/login` page with email + Google OAuth
- [x] **0.4 Onboarding wizard** — ✅ 3-step wizard (channel → API keys → ready)
- [x] **0.5 Protected routes** — ✅ JWT required on all API routes
- [x] **0.6 Stripe backend** — ✅ Checkout, webhooks, portal, subscription tracking
- [ ] **0.7 Password reset flow** — Email-based recovery. Needs: `password_reset_tokens` table, send-email endpoint, reset page.
- [ ] **0.8 Disable dev-token** — Remove `dev-token` bypass in production mode. Add `ENV=production` to deploy.

### Phase 1: Billing & Plan Enforcement (Week 1) — "Make it Payable"
> Stripe backend exists but users can't see or buy plans. This is the #1 blocker.

- [ ] **1.1 `/billing` page** — Current plan, usage stats, upgrade/downgrade buttons, invoice history. Stripe portal link for card management.
- [ ] **1.2 `/pricing` page** — Public pricing grid (Starter $49 / Pro $149 / Agency $399). Feature comparison table. CTA → checkout.
- [ ] **1.3 Plan enforcement middleware** — `check_plan_limits()` dependency. Before pipeline: check video count vs plan limit. Before render: check render minutes. Return 402 with upgrade prompt.
- [ ] **1.4 `tenant_usage` table** — Track: videos_created, api_calls, render_minutes, storage_bytes. Increment on each action. Reset monthly.
- [ ] **1.5 Upgrade prompts** — When user hits limit: modal with "You've used 4/4 videos this month. Upgrade to Pro for 15/month." Not blocking — informative.
- [ ] **1.6 Free trial** — 14-day Creator trial on signup. No CC required. After 14 days: downgrade to Starter limits. Show countdown in dashboard.
- [ ] **1.7 Plan badges** — Show current plan in sidebar/nav. "Pro" badge. Subtle, not annoying.

### Phase 2: Core Product Polish (Week 2-3) — "Make it Good"
> Fix UX gaps that would make a new user bounce.

- [ ] **2.1 Fix 3 broken endpoints** — `create-idea` (undefined `run_idea_bot`), `upload` (missing endpoint), `skills/pipeline/*` (route ordering).
- [ ] **2.2 Dashboard redesign** — Answer "What should I do next?" Active video progress cards, pending approvals, recent completions, quick-start CTA.
- [ ] **2.3 Create video simplification** — Current form is power-user. New: paste URL or type topic → AI suggests 3 titles → pick one → pipeline starts. 3 clicks.
- [ ] **2.4 Pipeline progress UX** — Real-time stage tracking. SSE stream (`/api/activity/stream` exists). Current stage highlighted, ETA, "View Live" per stage.
- [ ] **2.5 Empty states (all 23 pages)** — Competitors empty → "Add your first competitor". Analytics empty → "Publish a video to see insights." Each page has a compelling CTA.
- [ ] **2.6 Error states** — Global error boundary. Per-component error cards with retry. Toast notifications for pipeline events (success/failure/approval needed).
- [ ] **2.7 Settings page completion** — Key validation feedback, setup guides, "required vs optional" labeling. Integration status indicators.
- [ ] **2.8 In-app notifications** — Toast system for: stage completions, errors, approvals needed. Replace Slack dependency for user-facing alerts.

### Phase 3: Infrastructure for Scale (Week 4-5) — "Make it Reliable"
> The invisible stuff that prevents outages at multi-tenant scale.

- [ ] **3.1 Redis + job queue** — Replace in-process asyncio with `arq` or `dramatiq`. Each pipeline stage = a job. Enables: retries, priority, concurrency limits, dead letter queue, survive server restarts.
- [ ] **3.2 Per-tenant asset storage** — Supabase Storage (already partially wired) or Cloudflare R2. Per-tenant folders. Signed URLs. Replace Google Drive for SaaS users.
- [ ] **3.3 Error monitoring (Sentry)** — Capture exceptions with tenant_id + video_id context. Alert on error rate spikes. Source maps for frontend.
- [ ] **3.4 Structured logging** — JSON logs: tenant_id, video_id, stage, duration_ms, cost. Ship to Axiom or Datadog.
- [ ] **3.5 Rate limiting** — Per-tenant: API rate limits (100 req/min Starter, 500 Pro), concurrent pipeline jobs (1/3/5 by plan).
- [ ] **3.6 Background task persistence** — Store task state in DB (not in-memory). Survive server restarts. Show task history.
- [ ] **3.7 Health checks** — Expand `/api/health`: DB connectivity, queue depth, active tasks, storage availability. Uptime monitoring (BetterUptime or similar).
- [ ] **3.8 Transactional email** — Welcome email, password reset, billing receipts, weekly digest. Resend or Postmark.

### Phase 4: Growth Features (Week 6-9) — "Make it Sticky"
> Features that increase retention and reduce churn.

- [ ] **4.1 Learning insights dashboard** — Show users WHAT the AI learned. "Your audience responds to X", "Best CTR formula: Z". Makes the moat visible. **Pull this EARLY — it's the wow feature.**
- [ ] **4.2 Template library** — Pre-built styles + script structures. "Geopolitics Explainer", "Tech Review", "Finance Deep-Dive". Customizable.
- [ ] **4.3 Voice clone** — ElevenLabs voice clone per channel. Upload 5min sample → custom voice on all videos. Premium add-on ($20/mo).
- [ ] **4.4 Brand kit** — Logo, colors, intro/outro, watermark. Applied to all renders. Stored in projects table.
- [ ] **4.5 Team collaboration** — Invite members (email). Roles: Admin/Editor/Viewer. `invitations` table. Shared video library.
- [ ] **4.6 Analytics 2.0** — CTR trends over time, best posting times, topic performance heatmap. Competitor benchmarking. AI-generated weekly digest email.
- [ ] **4.7 Batch operations** — Multi-select competitor videos → "Queue All". Multi-select ideas → "Produce All". Progress dashboard.
- [ ] **4.8 Export & download** — Video (MP4), script (PDF), thumbnail (PNG), all assets (ZIP). Supabase Storage signed URLs.
- [ ] **4.9 Calendar view** — Production calendar: scheduled, in-progress, published. Drag to reschedule. Autopilot cadence overlay.
- [ ] **4.10 Webhook API** — Notify external systems: video complete, approval needed, published. Zapier/Make.com integration.
- [ ] **4.11 Video preview player** — In-app player for rendered output. Thumbnail preview. Script overlay toggle.

### Phase 5: Launch (Week 10-12) — "Make it Public"
> Marketing, documentation, go-to-market.

- [ ] **5.1 Landing page** — Hero with demo video, feature grid, pricing, testimonials. Separate Next.js marketing site or `/` route.
- [ ] **5.2 Documentation** — Getting started guide, API reference, FAQ, troubleshooting. Mintlify or Nextra.
- [ ] **5.3 Demo mode** — Public demo with pre-loaded data. Browse pipeline without signup. "Try it free" CTA.
- [ ] **5.4 Beta program** — Invite 10-20 creators. Structured feedback. Fix critical issues. Testimonial collection.
- [ ] **5.5 Launch checklist** — Security audit, load test (k6), backup strategy, incident response, legal (ToS, privacy policy, DPA).
- [ ] **5.6 Product Hunt / launch campaign** — Scheduled launch with demo video, social assets, email sequence.

---

## Feature Priority Matrix

```
                    HIGH IMPACT
                        │
     Phase 0 (Auth)     │     Phase 1 (UX Polish)
     Phase 2 (Billing)  │     Phase 4.1 (Templates)
                        │     Phase 4.2 (Voice Clone)
    ────────────────────┼────────────────────────────
                        │
     Phase 3 (Infra)    │     Phase 4 (Growth)
     Phase 5 (Launch)   │     Phase 4.4 (Teams)
                        │     Phase 4.9 (Webhooks)
                        │
                    LOW IMPACT
     HIGH EFFORT ───────┼──────── LOW EFFORT
```

---

## Daily Log

### Day 1 — 2026-04-02

**Focus:** Strategic analysis and roadmap creation.

**Completed:**
- Full codebase audit: pipeline (13 stages, 95% functional), backend (90+ endpoints, 18 routers), frontend (~15 pages), database (19 tables, multi-tenant schema)
- Identified 14 critical SaaS gaps
- Created 5-phase implementation roadmap with ~40 discrete tasks
- Proposed pricing model (Starter $49 → Enterprise custom)
- Created this journal for daily tracking

**Key Insights:**
1. The hardest part is already done — the pipeline works. The gap is packaging it as a product.
2. The learning loop is the competitive moat. Phase 4.1 (learning insights) should be pulled earlier — it's the "wow" feature.
3. The existing Slack bot (`pipeline_control.py`) is a treasure trove of battle-tested logic. Many commands map 1:1 to dashboard features.

---

### Day 2 — 2026-04-04

**Focus:** Deep audit of what actually exists. Massive roadmap revision.

**What Changed Since Day 1:**
Between Day 1 and today, the autonomous agent team (6 agents on Opus) executed a full PRD cycle. This resulted in auth, billing backend, onboarding, Google OAuth, and agent infra being built. The original roadmap's Phase 0 is now ~80% complete — the biggest gaps shifted from "build auth" to "build billing UI + enforce plans."

**Full Audit Results (23 pages, 22 route modules, 150+ endpoints):**

| Category | Day 1 Assessment | Actual State (Day 2) |
|----------|-----------------|---------------------|
| Auth | ❌ Dev tokens only | ✅ Email/password + Google OAuth + JWT (30-day) |
| Onboarding | ❌ No first-time flow | ✅ 3-step wizard (channel → keys → ready) |
| Billing backend | ❌ No Stripe | ✅ Stripe checkout + webhooks + portal + 3 tiers |
| Multi-tenancy | ~70% | ✅ Full RLS (24 policies), memberships, roles |
| Frontend pages | ~15 | 23 pages (login, onboarding, calendar, discovery, learnings, review, profile added) |
| Backend routes | 18 modules | 22 modules (billing, google_auth, profile, projects, preferences, visual_styles added) |
| Agent team | Concept | ✅ 6 agents live on cron, PRD decomposition, RUBRIC command center |

**Revised Priority Stack (what to build NOW):**

1. **Billing UI** (CRITICAL) — Stripe is wired but invisible. `/billing` page + `/pricing` page. Without this, product can't make money.
2. **Plan enforcement** (CRITICAL) — No feature gating exists. Free users get everything. Need `check_plan_limits()` middleware.
3. **Fix 3 broken endpoints** (HIGH) — `create-idea`, `upload`, `skills/pipeline/*` are broken in production.
4. **Password reset** (HIGH) — No recovery flow. Users locked out if they forget password.
5. **Empty/error states** (HIGH) — 23 pages, most have no empty state. New users see blank pages.
6. **Create video simplification** (MEDIUM) — Current form requires power-user knowledge. Need: paste URL → pick title → go.

**Roadmap restructured to 5 phases (down from 6):**
- Phase 0 (Foundation): ✅ Mostly done. 2 items remain (password reset, disable dev-token).
- Phase 1 (Billing): NEW priority. `/billing` page, plan enforcement, usage tracking, trial.
- Phase 2 (UX Polish): Fix broken endpoints, empty states, pipeline progress, notifications.
- Phase 3 (Infrastructure): Redis queue, Sentry, storage, rate limiting.
- Phase 4 (Growth): Learning insights, templates, voice clone, teams, analytics 2.0.
- Phase 5 (Launch): Landing page, docs, demo, beta program.

**Architecture Observations:**
1. **TypeScript types are manually maintained** (`types.ts` = 142 lines). No OpenAPI/zod generation. Type drift is inevitable — consider generating from Pydantic models.
2. **`api.ts` has 150+ lines of fetch wrappers** but no retry logic, no caching, no request dedup. React Query is used on the frontend but not consistently.
3. **Background tasks are in-memory only.** `pipeline_executor.py` runs asyncio tasks. Server restart = all running jobs vanish. This WILL cause support tickets.
4. **`accounts` table stores Stripe data** (customer_id, subscription_id, plan, status) but there's no usage metering table. Need `tenant_usage` before enforcement.
5. **Route ordering bug** — `skills.py` has a catch-all pattern that prevents `/api/skills/pipeline/*` from matching. Fix: register specific routes before catch-all.

**Tomorrow's Plan (Day 3):**
- Phase 1.1: Build `/billing` page
  - Read billing.py backend routes (checkout, portal, subscription status)
  - Read accounts table schema (stripe fields)
  - Build: current plan display, usage stats, upgrade button, portal link
  - Wire to Stripe checkout for plan changes
- Phase 1.2: Build `/pricing` public page
  - Feature comparison grid
  - 3 tiers with CTA buttons
  - Can be viewed without auth (marketing page)

---

## This Week's Sprint (2026-04-04 → 2026-04-10)

> Phase 1: Billing & Plan Enforcement — "Make it payable"

### Day 3 (Apr 5) — Billing UI
- [ ] Build `/billing` page (current plan, usage, upgrade CTA, portal link)
- [ ] Build `/pricing` page (public, 3 tiers, feature comparison, CTA → checkout)
- [ ] Wire both to Stripe checkout endpoints that already exist

### Day 4 (Apr 6) — Plan Enforcement
- [ ] Create `tenant_usage` table (videos_created, render_minutes, storage_bytes, api_calls, period_start)
- [ ] Build `check_plan_limits()` FastAPI dependency
- [ ] Wire enforcement into pipeline execution (block when over limit, return 402)
- [ ] Add usage increment hooks to pipeline stages

### Day 5 (Apr 7) — Trial + Password Reset
- [ ] Add 14-day trial logic (trial_ends_at on accounts, check on each request)
- [ ] Build password reset flow (token table, send-email endpoint, /reset-password page)
- [ ] Transactional email via Resend (welcome + reset + trial ending)

### Day 6 (Apr 8) — Fix Broken Endpoints + Empty States
- [ ] Fix `create-idea` (wire `run_idea_bot` or replace)
- [ ] Fix `upload` (add missing endpoint)
- [ ] Fix `skills/pipeline/*` (route ordering)
- [ ] Add empty states to top 5 pages (dashboard, pipeline, competitors, analytics, learnings)

### Day 7 (Apr 9) — Create Video Simplification
- [ ] New create flow: URL/topic input → AI suggests 3 titles → pick → go
- [ ] Simplify `/create` page to single input with expandable "Advanced" section
- [ ] Wire to research → idea pipeline with sensible defaults

### Day 8 (Apr 10) — Sprint Review + Next Week Planning
- [ ] Test full signup → onboarding → billing → create video → pipeline flow
- [ ] Fix any broken wiring discovered in E2E test
- [ ] Write next week's sprint (Phase 2: UX Polish or Phase 3: Infrastructure)

---

## Architecture Decisions Log

### ADR-001: Custom JWT Auth (not Supabase Auth)
**Decision:** ✅ IMPLEMENTED — Custom auth with PBKDF2-SHA256 + JWT, not Supabase Auth.
**What was built:** `google_auth.py` handles registration, login, Google OAuth. JWT signed with SESSION_SECRET (30-day expiry). Accounts table stores credentials.
**Trade-off:** Must implement password reset ourselves (Supabase Auth does it free). But: full control over auth flow, no Supabase Auth SDK dependency on frontend.

### ADR-002: S3-compatible storage (not Google Drive)
**Decision:** Migrate asset storage from Google Drive to Supabase Storage or Cloudflare R2.
**Why:** Google Drive requires per-user OAuth, has rate limits, URLs need conversion for Airtable. S3 gives: signed URLs, per-tenant isolation, CDN, no OAuth dance.
**Trade-off:** Migration effort. Existing pipeline writes to Drive everywhere. Need adapter layer.

### ADR-003: Redis job queue (not in-process asyncio)
**Decision:** Add Redis-backed job queue for pipeline execution.
**Why:** Current in-process tasks die with the server. No retry. No priority. No concurrency control across tenants. Redis enables: persistent jobs, rate limiting per tenant, horizontal scaling.
**Trade-off:** Operational complexity (Redis server). Worth it for reliability.

### ADR-004: Pooled API keys (not BYOK for launch)
**Decision:** Platform provides API keys for Claude, ElevenLabs, image gen. Users don't bring their own.
**Why:** BYOK creates terrible onboarding ("go sign up for 5 services before you can use ours"). Pool keys, absorb cost, bill via subscription.
**Trade-off:** Higher COGS. Offset by subscription pricing. BYOK available as Enterprise option.

---

## Metrics to Track Post-Launch

| Metric | Target | Why |
|--------|--------|-----|
| Signup → First Video | < 15 min | Onboarding quality |
| Videos per user per month | 4+ (Starter), 10+ (Creator) | Engagement |
| Time to first render | < 45 min | Pipeline speed |
| Monthly churn | < 8% | Product-market fit |
| NPS | > 40 | User satisfaction |
| Cost per video (platform) | < $15 | Unit economics |
| CTR improvement (user's channel) | 10%+ after 10 videos | Learning loop effectiveness |

---

### ADR-005: Autonomous Agent Team (6 agents, all Opus)
**Decision:** ✅ IMPLEMENTED — 6 AI agents run on cron, handle PRDs, fix bugs, test UI.
**What was built:** Orchestrator, Backend Dev, Frontend Dev, QA, Pipeline Tester, Security Auditor. RUBRIC command center. PRD decomposition + auto-execution. Cross-agent handoffs. Telegram integration.
**Trade-off:** High API cost (~$50-100/day at turbo cadence). Offset by velocity — the agent team built auth, billing, onboarding in 2 days. Can scale back cadence after initial build sprint.

### ADR-006: Supabase Storage for SaaS (not Google Drive)
**Decision:** PARTIALLY IMPLEMENTED — Supabase Storage wired for storyboard grids. Google Drive still used for voice/images/video by the VPS pipeline.
**Migration plan:** SaaS users → Supabase Storage exclusively. Legacy VPS pipeline → Google Drive (existing). Adapter layer in `supabase_adapter.py` already abstracts storage.

---

## Competitive Landscape

| Competitor | What They Do | Our Advantage |
|-----------|-------------|---------------|
| **Pictory** | Script → video (stock footage) | We generate custom images, not stock. Our pipeline is deeper (research → script → custom visuals). |
| **Synthesia** | AI avatar videos | We target documentary/explainer, not talking heads. Our visual system is cinematic, not corporate. |
| **InVideo** | Template-based video editor | We're AI-first (topic in, video out). No manual editing required. |
| **Opus Clip** | Long → short clips | We CREATE content, they repurpose. Different market. |
| **None (our moat)** | — | The learning loop. After 10 videos, the system knows your audience. CTR improves automatically. No competitor has this. |

---

*This journal is updated daily. Each session adds to the daily log and adjusts the roadmap as we learn.*
