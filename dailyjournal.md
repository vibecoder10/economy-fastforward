# StoryEngine SaaS — Daily Journal & Roadmap

> "Topic in, video out" — but for every creator, not just us.

---

## Product Vision

**StoryEngine** transforms an internal AI video production pipeline into a multi-tenant SaaS platform where YouTube creators input a topic and receive a fully produced video draft — script, voice, visuals, sound, thumbnail, and render — with AI learning from their channel's performance to improve over time.

**Target Users:** YouTube creators (solo or small teams) producing educational, explainer, or documentary-style content who want to 10x their output without hiring a production team.

**Moat:** The learning loop. Every video a creator publishes feeds performance data back into the system, making future videos better. Competitors can copy features but not accumulated channel-specific intelligence.

---

## Current State Assessment (2026-04-02)

### What EXISTS and WORKS

| Layer | Status | Details |
|-------|--------|---------|
| **Video Pipeline** | 95% functional | 13-stage pipeline: idea → research → script → voice → image prompts → images → sound → video clips → thumbnail → render → upload. All stages tested. |
| **Backend API** | 90+ endpoints | 18 route modules (FastAPI + asyncpg). Videos, pipeline, autopilot, discovery, analytics, learnings, settings, niche, agents, visual styles. |
| **Database** | Multi-tenant schema | 19 tables with tenant_id, RLS policies, 40+ indexes, 20 migrations. Supabase PostgreSQL. |
| **Frontend** | ~15 pages | Dashboard, pipeline list, video detail (5 tabs), competitors, autopilot, analytics, settings, create, activity, review. Next.js 16 + React 19 + TailwindCSS 4. |
| **Autopilot** | Partial | Competitor scoring, idea selection, theme extraction work. Learning feedback loop incomplete. |
| **Background Tasks** | 4 auto-tasks | YouTube sync (6h), learning extraction (24h), title analysis (24h), competitor scraping (24h). |

### What's MISSING for SaaS

| Gap | Severity | Current State |
|-----|----------|---------------|
| **Authentication** | CRITICAL | Dev tokens only. No login/signup/password reset. No OAuth. |
| **Onboarding** | CRITICAL | No first-time user flow. User must know what to configure manually. |
| **Billing & Subscriptions** | CRITICAL | No Stripe. No plan limits. No usage metering. No paywalls. |
| **API Key Provisioning** | HIGH | Users must bring their own Claude/ElevenLabs/Kie.ai keys. No pooled keys. |
| **Job Queue** | HIGH | Background tasks run in-process (asyncio). No Redis/Celery. Can't scale beyond 1 worker. |
| **Asset Storage** | HIGH | Single Google Drive account. No per-tenant storage isolation. |
| **Email Notifications** | HIGH | Slack-only. No email, no in-app notifications. |
| **Error Monitoring** | HIGH | Console logging only. No Sentry, no structured error tracking. |
| **Landing Page** | MEDIUM | No marketing site. No pricing page. No demo. |
| **User Documentation** | MEDIUM | No help docs, no tooltips, no onboarding guides. |
| **Rate Limiting** | MEDIUM | No per-tenant API rate limiting or concurrent job limits. |
| **Team Collaboration** | MEDIUM | Single user per tenant. No invites, roles, or shared editing. |
| **Video Preview** | MEDIUM | No in-app video player for rendered output. |
| **Mobile UX** | LOW | Bottom nav exists but overall mobile experience untested. |
| **White-labeling** | LOW | Not needed for launch. |

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

## Implementation Roadmap (Sequential Phases)

### Phase 0: Foundation (Week 1-2) — "Make it Real"
> Auth, onboarding, and the minimum viable paywall.

- [ ] **0.1 Supabase Auth integration** — Email/password signup + login + password reset. Supabase Auth handles JWT, session management, email verification. Replace dev-token with real auth flow.
- [ ] **0.2 Auth middleware on all routes** — Every API endpoint requires valid JWT. Tenant isolation enforced (already mostly done via `get_tenant_id`).
- [ ] **0.3 Login/Signup pages** — Clean branded pages. Social OAuth (Google) as stretch goal.
- [ ] **0.4 Onboarding wizard** — 4 steps: (1) Channel name + niche, (2) Connect YouTube (OAuth), (3) Add 3+ competitor channels, (4) Choose visual style. Creates tenant, project, channel_profile, autopilot_config.
- [ ] **0.5 Protected routes** — Redirect unauthenticated users to login. Redirect new users (no tenant) to onboarding.
- [ ] **0.6 Plan selection page** — Show pricing tiers. No Stripe yet — just store selected plan in tenant table.

### Phase 1: Core Product Polish (Week 3-4) — "Make it Good"
> Fix the UX gaps that would make a new user bounce.

- [ ] **1.1 Dashboard redesign** — First thing users see. Must answer: "What should I do next?" Show: active video progress, pending approvals, recent completions, quick-start CTA.
- [ ] **1.2 Create video flow** — Simplify. Current form is power-user oriented. New flow: paste URL or type topic → AI suggests titles + angles → user picks one → pipeline starts. 3 clicks to video.
- [ ] **1.3 Pipeline progress UX** — Real-time progress tracking. Current stage highlighted, ETA displayed, "View Live" for each stage output. SSE already exists (`/api/activity/stream`), wire it to UI.
- [ ] **1.4 Video preview player** — Rendered video playable in-app. Thumbnail preview, script overlay option. Currently no way to see the final product without going to YouTube.
- [ ] **1.5 In-app notifications** — Toast notifications for: pipeline stage completions, errors, approvals needed. Replace Slack dependency for user-facing alerts.
- [ ] **1.6 Settings page completion** — API key management UI exists but needs: key validation feedback, setup guides per service, "required vs optional" labeling.
- [ ] **1.7 Empty states** — Every page needs a compelling empty state. Competitors page with no channels → "Add your first competitor" CTA. Analytics with no data → "Publish your first video to see insights."
- [ ] **1.8 Error states** — Global error boundary. Per-component error cards. Retry buttons. Currently errors may silently fail in UI.

### Phase 2: Billing & Usage (Week 5-6) — "Make it Sustainable"
> Stripe integration, usage tracking, plan enforcement.

- [ ] **2.1 Stripe integration** — Checkout sessions for plan signup. Customer portal for plan changes. Webhook handler for subscription events.
- [ ] **2.2 Usage metering** — Track per-tenant: videos created, API calls, render minutes, storage used. Store in `tenant_usage` table.
- [ ] **2.3 Plan enforcement** — Before pipeline execution: check video count against plan limit. Before render: check render minutes. Soft limits (warning at 80%) + hard limits (block at 100%).
- [ ] **2.4 Billing dashboard** — Current plan, usage bars, next invoice date, upgrade CTA. In settings page.
- [ ] **2.5 Upgrade prompts** — Contextual "Upgrade to unlock" when hitting limits. Not annoying — helpful.
- [ ] **2.6 Free trial** — 14-day trial on Creator plan. No credit card required. Converts to Starter or churns.

### Phase 3: Infrastructure for Scale (Week 7-8) — "Make it Reliable"
> Job queues, storage, monitoring — the invisible stuff that prevents outages.

- [ ] **3.1 Redis + job queue** — Replace in-process asyncio tasks with Redis-backed queue (e.g., `arq` or `dramatiq`). Each pipeline stage = a job. Enables: retries, priority, concurrency limits, dead letter queue.
- [ ] **3.2 Per-tenant asset storage** — S3-compatible storage (Supabase Storage or Cloudflare R2). Per-tenant folders. Signed URLs for asset access. Replace single Google Drive.
- [ ] **3.3 Structured logging** — JSON logs with tenant_id, video_id, stage, duration, cost. Ship to Datadog/Grafana/Axiom.
- [ ] **3.4 Error monitoring** — Sentry integration. Capture exceptions with tenant context. Alert on error rate spikes.
- [ ] **3.5 Health checks** — `/api/health` already exists. Add: database connectivity, Redis connectivity, queue depth, background task heartbeats.
- [ ] **3.6 Rate limiting** — Per-tenant API rate limits. Per-tenant concurrent pipeline job limits (Starter: 1, Creator: 3, Studio: 5).
- [ ] **3.7 Database connection pooling** — Current: min=2, max=10. For multi-tenant: use PgBouncer or Supabase pooler. Connection per tenant isolation.

### Phase 4: Growth Features (Week 9-12) — "Make it Sticky"
> Features that increase retention and expand usage.

- [ ] **4.1 Template library** — Pre-built visual styles + script structures. "Geopolitics Explainer", "Tech Review", "Finance Deep-Dive". Users can customize and save.
- [ ] **4.2 Voice clone integration** — ElevenLabs voice clone per channel. Creator uploads 5min sample → custom voice used for all videos.
- [ ] **4.3 Brand kit** — Logo, colors, intro/outro, watermark, font. Applied to all renders automatically. Stored in channel_profile.
- [ ] **4.4 Team collaboration** — Invite team members (email). Roles: Admin, Editor, Viewer. Shared video library. Comment threads on videos.
- [ ] **4.5 Calendar view** — Production calendar showing: scheduled videos, in-progress, published. Drag to reschedule. Autopilot cadence visualized.
- [ ] **4.6 Analytics 2.0** — Channel-level trends (CTR over time, best posting times, topic performance). Competitor benchmarking. AI-generated weekly digest.
- [ ] **4.7 Batch operations** — Select multiple competitor videos → "Queue All" → autopilot creates ideas for each. Select multiple ideas → "Produce All" → sequential pipeline execution.
- [ ] **4.8 Export & download** — Download: rendered video (MP4), script (PDF/DOCX), thumbnail (PNG), all assets (ZIP). Currently assets live in Google Drive only.
- [ ] **4.9 Webhook API** — Notify external systems on: video completed, approval needed, published. Enable Zapier/Make.com integrations.
- [ ] **4.10 Learning insights dashboard** — Show users WHAT the AI has learned about their channel. "Your audience responds to X", "Avoid Y", "Best CTR formula: Z". Makes the learning loop visible and trustworthy.

### Phase 5: Launch (Week 13-14) — "Make it Public"
> Marketing site, documentation, launch preparation.

- [ ] **5.1 Landing page** — Hero with demo video, feature grid, pricing table, testimonials (beta users), CTA.
- [ ] **5.2 Documentation** — Getting started guide, API reference (if exposing), FAQ, troubleshooting.
- [ ] **5.3 Demo mode** — Public demo with pre-loaded data. Let visitors click through the pipeline without signing up.
- [ ] **5.4 Beta program** — Invite 10-20 creators. Collect feedback. Fix critical issues.
- [ ] **5.5 Launch checklist** — Security audit, load testing, backup strategy, incident response plan, legal (ToS, privacy policy).

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

### Day 1 — 2026-04-02 (Today)

**Focus:** Strategic analysis and roadmap creation.

**Completed:**
- Full codebase audit: pipeline (13 stages, 95% functional), backend (90+ endpoints, 18 routers), frontend (~15 pages), database (19 tables, multi-tenant schema)
- Identified 14 critical SaaS gaps (auth, billing, onboarding, job queue, storage, notifications, monitoring, rate limiting, docs, landing page, teams, preview, mobile, error states)
- Created 5-phase implementation roadmap with ~40 discrete tasks
- Proposed pricing model (Starter $49 → Enterprise custom)
- Created this journal for daily tracking

**Key Insights:**
1. The hardest part is already done — the pipeline works. The gap is packaging it as a product.
2. Multi-tenancy is 70% there — tenant_id on all tables + RLS policies exist. Missing: auth flow, plan enforcement, per-tenant resource isolation.
3. The learning loop is the competitive moat. Phase 4.10 (learning insights dashboard) should be pulled earlier — it's the "wow" feature.
4. Google Drive as asset storage won't scale. Per-tenant S3/R2 is Phase 3 but may need to be pulled into Phase 1 if onboarding breaks without it.
5. The existing Slack bot (`pipeline_control.py` at 150KB) is a treasure trove of battle-tested logic. Many Slack commands map 1:1 to dashboard features.

**Tomorrow's Plan (Day 2):**
- Begin Phase 0.1: Supabase Auth integration
  - Set up Supabase Auth in the project
  - Create auth utility functions (signUp, signIn, signOut, getSession)
  - Create login/signup pages
  - Add auth middleware to backend routes
  - Test end-to-end auth flow

---

## Architecture Decisions Log

### ADR-001: Supabase Auth (not custom JWT)
**Decision:** Use Supabase Auth for authentication.
**Why:** Already using Supabase for database. Auth is built-in, handles email verification, password reset, OAuth, session management. Free for <50k MAU.
**Trade-off:** Vendor lock-in to Supabase. Acceptable — already committed to Supabase PostgreSQL.

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

*This journal is updated daily. Each session adds to the daily log and adjusts the roadmap as we learn.*
