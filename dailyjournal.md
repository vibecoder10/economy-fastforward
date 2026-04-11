# Daily Journal — StoryEngine SaaS Transformation

> Track what's real, what's missing, and what to build next. Updated daily.

---

## State of the Product (April 11, 2026)

### Honest Assessment: ~75% Production-Ready

The 6-agent team has been building at high velocity since April 6. The old 18-day roadmap (in `tasks/roadmap.md`) is now stale — many items marked as "Day 10+" are already done, while some "Day 2" items still have gaps. This journal replaces that plan with an accurate, current-state assessment.

### What EXISTS and WORKS (Verified)

| Layer | Evidence | Status |
|-------|----------|--------|
| **Video Pipeline** | 13 stages (research → upload), 60+ test files, all `run.py` entry points real | 100% |
| **Frontend** | 32 pages, 85 components, Framer Motion animations, responsive layout | 90% |
| **Backend API** | 26 route files, 171+ endpoints, all registered in `main.py` | 95% |
| **Database** | 25+ tables, 40 migrations, pgvector, tenant_usage, RLS policies | 95% |
| **Auth** | Email/password (PBKDF2-SHA256) + Google OAuth + JWT (30-day) + password reset flow | 100% |
| **Billing** | Stripe checkout + webhooks + portal + pricing page ($25/$40/$75) | 85% |
| **Plan Enforcement** | `check_plan_limits()` called in video create, pipeline start, discovery launch | 85% |
| **Rate Limiting** | Per-plan token bucket middleware (free:15/min, starter:30, creator:100, studio:300) | 100% |
| **Onboarding** | Multi-step wizard: channel → API keys → style → first video | 100% |
| **Landing Page** | Root `page.tsx`: hero, value props, pipeline steps, stats, pricing tiers, CTA | 80% |
| **Error Handling** | Toast notifications, global error boundary, 404 page | 90% |
| **Health Checks** | `/api/health` (DB + tasks) + `/api/health/detailed` (token-protected) | 100% |
| **Background Tasks** | 7 async tasks: learnings, YouTube sync, competitor scrape, trial warnings, intelligence distillation, meta-analysis | 100% |
| **Task Persistence** | DB-backed `background_tasks` table + startup recovery | 100% |
| **Intelligence** | Content distillation + pgvector embeddings + meta-analysis + advisor | 100% |
| **Pipeline Progress** | SSE streaming from backend, frontend hook wired | 80% |
| **Logging** | Structured JSON formatter + request logging middleware | 100% |
| **Dev-token** | Environment-gated: requires `DEV_MODE=true` AND `DEV_TOKEN` env var | 100% |
| **Legal Pages** | `/terms` and `/privacy` pages exist | 80% |
| **Demo Page** | `/demo` with static pre-loaded data | 70% |
| **Docs Page** | `/docs` with getting started guide | 60% |
| **Google Drive OAuth** | Per-user Drive connection + folder picker | 100% |

### What's ACTUALLY Still Missing

#### Tier 1: BLOCKING (fix before accepting money)

| # | Gap | Detail | Effort |
|---|-----|--------|--------|
| 1 | **Trial auto-downgrade** | `trial_ends_at` exists, warning emails fire, but NO job downgrades expired trials to free plan. Users on expired trials keep Creator access forever. | 0.5 day |
| 2 | **3 security bugs** | SEC-SSE-001: cross-tenant `_running_tasks` leak. SEC-EMAIL-001: HTML injection in email templates. SEC-KEYS-001: exception details in API responses. | 1 day |
| 3 | **QA smoke test** | PRD3 Tasks 8-11 incomplete. No end-to-end verification that billing → plan enforcement → pipeline → render actually works for a real user. | 1-2 days |
| 4 | **Deploy migrations 036-040** | Intelligence tables (pgvector, content_intelligence, niche_meta_insights) + onboarding columns not yet on production VPS. | 0.5 day |

#### Tier 2: HIGH (users churn without these)

| # | Gap | Detail | Effort |
|---|-----|--------|--------|
| 5 | **Create video simplification** | `POST /api/videos/suggest-titles` endpoint built but NOT wired to frontend. Current create flow requires power-user knowledge. | 1 day |
| 6 | **Video preview player** | No in-app playback of rendered MP4s. Users must download to see result. | 0.5 day |
| 7 | **Landing page polish** | Landing page exists but could be stronger — no demo video embed, no social proof/testimonials, no animated pipeline visualization. | 1 day |
| 8 | **Mobile responsiveness audit** | Bottom-tab nav exists for mobile, but no systematic audit of all 32 pages on small screens. | 0.5 day |
| 9 | **Comprehensive empty states** | Some pages still show blank grids for new users. Top 8 pages need compelling CTAs. | 0.5 day |

#### Tier 3: MEDIUM (needed for retention & growth)

| # | Gap | Detail | Effort |
|---|-----|--------|--------|
| 10 | **Redis job queue** | Pipeline runs in-process asyncio. Server restart = lost jobs. No retry logic, no dead letter queue. This is the biggest reliability risk. | 2-3 days |
| 11 | **Sentry error monitoring** | No external error tracking. Logs exist but no alerting on spikes. Flying blind on user-facing errors. | 0.5 day |
| 12 | **Team collaboration** | Multi-tenant schema supports roles (owner/admin/member) but no invite flow, no team management UI. Needed for Studio tier ($75/mo). | 1-2 days |
| 13 | **Webhook API** | No external integrations (Zapier, Make.com). Limits automation-minded users. | 1-2 days |
| 14 | **Data export / GDPR** | No bulk download. No "delete my data" flow. Legal requirement in EU. | 1 day |
| 15 | **Load testing** | No k6 or equivalent. Don't know how many concurrent users/pipelines the system handles. | 0.5 day |

#### Tier 4: POLISH (launch quality & stickiness)

| # | Gap | Detail | Effort |
|---|-----|--------|--------|
| 16 | **Docs content depth** | `/docs` page exists but content is thin. Need: API reference, pipeline stage docs, troubleshooting. | 1-2 days |
| 17 | **Demo mode enrichment** | `/demo` exists with static data. Need pre-loaded pipeline walkthrough showing real output quality. | 1 day |
| 18 | **Voice clone** | ElevenLabs supports voice cloning. Premium feature for Studio tier. Not built. | 1 day |
| 19 | **Brand kit UI** | Backend migration 030 exists (brand_kit). Frontend partially wired in profile page. Need: logo upload, intro/outro, watermark. | 1 day |
| 20 | **CI/CD pipeline** | Just `git pull --ff-only` on VPS. No automated tests in deploy flow. | 1 day |
| 21 | **Backup strategy** | No documented backup for Supabase data. Supabase Pro has daily backups, but no verified restore process. | 0.5 day |

---

## Feature Set Blueprint

### Core Product Loop

```
ACQUIRE:  Landing page → Pricing → Sign up → 14-day Creator trial
CREATE:   Paste URL/topic → AI suggests titles → Pick one → Pipeline runs
PRODUCE:  Research → Script → Voice → Images → Sound → Video → Thumbnail → Render
REVIEW:   Edit script inline, regenerate images, swap thumbnails, adjust voice
PUBLISH:  Download MP4 or auto-upload as YouTube draft
LEARN:    AI monitors CTR/retention → extracts patterns → next video improves
GROW:     Autopilot picks topics → generates videos → learns autonomously
```

### Pricing Tiers (Current)

| | Starter ($25/mo) | Creator ($40/mo) | Studio ($75/mo) |
|---|---|---|---|
| Videos/month | 4 | 15 | Unlimited |
| Channels | 1 | 1 | Multi-channel |
| Visual styles | 1 | 3 | All + custom |
| Autopilot | No | Yes | Yes |
| Analytics & Learnings | No | Yes | Yes |
| Competitor analysis | No | Yes | Yes |
| Team seats | 1 | 1 | 3 |
| Render priority | Standard | Priority | Dedicated |

### What Makes This Different (The Moat)

1. **Learning loop**: After 10 videos, the system knows your audience. CTR improves automatically. No competitor has this.
2. **Full pipeline**: 18 stages from topic to YouTube draft. Not a template editor, not a clip repurposer. AI creates original content.
3. **Intelligence layer**: Content distillation + vector embeddings + meta-analysis. Each video makes the system smarter for all users.
4. **Autopilot**: System picks topics, generates videos, monitors performance, extracts learnings, and feeds them back. Hands-off growth.

---

## Sequential Execution Plan

### Phase 1: Launch-Ready (4-5 days)

**Goal: Fix the remaining blockers and verify the product works end-to-end.**

| Day | Date | Focus | Deliverables | Success Criteria |
|-----|------|-------|-------------|------------------|
| **1** | Apr 12 | Security + Trial Lifecycle | Fix 3 SEC bugs (SSE tenant scoping, email HTML escape, exception sanitization). Add trial expiry background job that downgrades expired trials to free plan. | No cross-tenant data leak. Expired trials lose Creator access. |
| **2** | Apr 13 | Create Video Flow + Empty States | Wire suggest-titles into create flow (paste URL → 3 AI titles → pick → go). Add compelling empty states to dashboard, pipeline, competitors, analytics, learnings, discovery. | 3-click video creation from a topic. New users see helpful CTAs, not blank pages. |
| **3** | Apr 14 | Deploy + E2E Smoke Test | Deploy migrations 036-040 to VPS. Restart backend. Run full user journey: signup → onboarding → create video → pipeline stages → render → download. Verify billing checkout → plan upgrade → limits enforced. | Complete user journey works on production. No 500 errors on core flows. |
| **4** | Apr 15 | Landing Page Polish + Video Preview | Add demo video embed, social proof section, and animated pipeline visualization to landing page. Build in-app video player for rendered output. Mobile responsiveness quick-fixes. | Landing page converts. Users preview videos in-app. |
| **5** | Apr 16 | Monitoring + Backup + Beta Invites | Sentry integration (backend + frontend). Verify Supabase backup strategy. Invite 5-10 beta creators. Fix any issues from Day 3 smoke test. | Errors tracked externally. Backup verified. Beta users onboarded. |

### Phase 2: Reliability & Stickiness (5-7 days)

**Goal: Make the product reliable enough for paying users and sticky enough to retain them.**

| Day | Date | Focus | Deliverables |
|-----|------|-------|-------------|
| **6-7** | Apr 17-18 | Redis Job Queue | Replace in-process asyncio with Redis-backed persistent job queue. Pipeline stages as durable jobs with retry, priority, dead letter queue. Server restart no longer kills running pipelines. |
| **8** | Apr 19 | Docs + Demo Enrichment | Flesh out /docs with pipeline stage explanations, FAQ, troubleshooting. Pre-load /demo with a real rendered video walkthrough. |
| **9** | Apr 20 | Brand Kit + Settings Polish | Wire brand kit UI (logo, colors, intro/outro per channel). Complete settings page with integration status indicators, API key validation feedback. |
| **10** | Apr 21 | Team Collaboration (Studio Tier) | Invite flow: owner sends email invite → invitee joins tenant → role-based access (admin can edit, member can view). Team management page. |

### Phase 3: Scale & Growth (5+ days, post-beta feedback)

**Goal: Features that make the product a competitive SaaS platform.**

| Priority | Feature | Why |
|----------|---------|-----|
| HIGH | GDPR data export/deletion | Legal requirement for EU users |
| HIGH | Load testing (k6) | Know the breaking point before scaling |
| HIGH | CI/CD pipeline | Automated tests before deploy |
| MEDIUM | Webhook API | Enable Zapier/Make.com integrations |
| MEDIUM | Voice clone | Premium Studio feature |
| MEDIUM | Analytics 2.0 | CTR trends, topic heatmaps, posting time optimization |
| LOW | Public API | For power users and enterprise |
| LOW | White-label | Future revenue stream |

---

## Metrics to Track Post-Launch

| Metric | Target | Why |
|--------|--------|-----|
| Signup → first video created | < 15 min | Onboarding quality |
| Videos per user per month | 4+ Starter, 10+ Creator | Engagement |
| Time to first render | < 45 min | Pipeline speed |
| Monthly churn | < 8% | Product-market fit |
| CTR improvement after 10 videos | 10%+ | Learning loop effectiveness |
| Platform cost per video | < $15 | Unit economics |
| Error rate (5xx) | < 0.5% | Reliability |
| Uptime | > 99.5% | Trust |

---

## Daily Log

### Day 0 — April 11, 2026 (Fresh Assessment)

**Focus:** Comprehensive audit of actual product state vs. stale roadmap assumptions.

**Key Findings:**
1. **Product is ~75% launch-ready**, not 55% as a surface audit might suggest. The landing page, plan enforcement, error handling, rate limiting, and dev-token gating all exist — the April 6 roadmap assumed they didn't.
2. **The 18-day roadmap is obsolete.** The agent team built things out of order. New plan: 5 days to launch-ready, 5 more days to reliable, then ongoing growth features.
3. **Biggest actual gaps:** Trial auto-downgrade (business logic), 3 security bugs (trust), create video simplification (UX), and Redis job queue (reliability).
4. **The intelligence stack is ahead of schedule.** Content distillation, pgvector embeddings, meta-analysis, and the advisor are all built. This is the moat feature and it's ready.
5. **171 API endpoints** are wired across 26 route files. The backend is effectively complete. Remaining work is frontend polish, security fixes, and infrastructure hardening.

**Corrections to Old Roadmap:**
- "Day 1: Build billing UI" → ALREADY DONE (billing page + pricing page + Stripe wiring)
- "Day 2: Plan enforcement" → ALREADY DONE (check_plan_limits called in 3 route files)
- "Day 3: Trial + password reset" → MOSTLY DONE (password reset complete, trial warning emails fire, missing: auto-downgrade)
- "Day 4: Fix broken endpoints" → NOT NEEDED (endpoints all work)
- "Day 5: Pipeline progress UX" → MOSTLY DONE (SSE streaming wired)
- "Day 6: Landing page" → ALREADY DONE (exists in root page.tsx)
- "Day 7: Dashboard redesign" → ALREADY DONE (action-first with usage meter)
- "Day 8: Learning insights" → ALREADY DONE (intelligence stack + frontend panels)
- "Day 9: Analytics 2.0" → ALREADY DONE (CTR timeline, framework performance, competitor benchmarking)
- "Day 11-12: Job queue" → NOT DONE (still needed)
- "Day 13: Per-tenant storage" → PARTIALLY DONE (Google Drive OAuth per-user, Supabase Storage wired for storyboards)
- "Day 14: Error monitoring" → NOT DONE (structured logging exists, Sentry not integrated)
- "Day 15: Security hardening" → PARTIALLY DONE (CORS env-driven, rate limiting active, 3 SEC bugs remain)

**Tomorrow's Plan (Day 1 — April 12):**
1. Fix SEC-SSE-001: Scope `_running_tasks` dict by `(tenant_id, video_id)` in `routes/pipeline.py`
2. Fix SEC-EMAIL-001: `html.escape()` display_name in `email_service.py` templates
3. Fix SEC-KEYS-001: Sanitize exception details in `vault.py` and `settings.py` error responses
4. Add trial expiry background job in `main.py` lifespan: check every 6h, downgrade expired trials to free plan, send expiry notification email
5. Deploy and verify

---

*Updated each session. Previous detailed roadmap preserved at `tasks/roadmap.md`.*
