# Daily Journal — Economy FastForward SaaS Transformation

> "Topic in, video out" — for every creator, not just us.

---

## Current State Snapshot (2026-04-06)

### What EXISTS and WORKS

| Layer | Status | Evidence |
|-------|--------|----------|
| **Video Pipeline** | 100% implemented | All 13 stages (script → upload) have real `run.py` entry points. 60+ test files. |
| **Autopilot** | Real implementation | 431-line `autopilot.py` with scoring, cadence, state persistence. 102 tests. |
| **Backend API** | 23 routers, 150+ endpoints | Dashboard, pipeline (25+ endpoints), billing, auth, autopilot, discovery, analytics, agents, skills. All registered in main.py. |
| **Database** | 14+ tables, multi-tenant | UUIDs, tenant_id scoping, 24 RLS policies, 24+ indexes. Supabase PostgreSQL. |
| **Frontend** | 24 pages | Dashboard, pipeline, video detail, competitors, autopilot, analytics, settings, login, onboarding, calendar, discovery, learnings, review, profile. |
| **Auth** | Working | Email/password (PBKDF2-SHA256) + Google OAuth. JWT 30-day sessions. AuthProvider on frontend. |
| **Onboarding** | Working | 3-step wizard (channel → API keys → ready). |
| **Billing Backend** | Stripe wired | Checkout, webhooks (subscription lifecycle), portal. 3 tiers in env vars. |
| **Agent Team** | 6 autonomous agents | Orchestrator, Backend Dev, Frontend Dev, QA, Pipeline Tester, Security Auditor. RUBRIC command center. |

### What's MISSING for Production SaaS

#### Tier 1: BLOCKING (can't charge money without these)

| # | Gap | Why It Blocks | Effort |
|---|-----|---------------|--------|
| 1 | **Billing UI** | Stripe is wired but invisible. No `/billing` or `/pricing` page. Users can't purchase. | 1 day |
| 2 | **Plan Enforcement** | No feature gating. Free users can do everything. `check_plan_limits()` doesn't exist. | 1 day |
| 3 | **Free Trial Logic** | No trial period. No grace period. No downgrade flow. | 0.5 day |
| 4 | **3 Broken Endpoints** | `create-idea` (undefined fn), `upload` (missing), `skills/pipeline/*` (route ordering). | 0.5 day |
| 5 | **Password Reset** | No recovery flow. Users locked out permanently if they forget password. | 0.5 day |
| 6 | **Disable dev-token** | `dev-token` bypasses all auth. Must be removed for production. | 0.5 day |

#### Tier 2: HIGH (users will churn without these)

| # | Gap | Why It Matters | Effort |
|---|-----|----------------|--------|
| 7 | **Empty States** | 24 pages, most show blank when no data. New users see nothing helpful. | 1 day |
| 8 | **Error Handling** | No global error boundary. No toast notifications. Pipeline failures are silent. | 1 day |
| 9 | **Create Video Simplification** | Current form requires power-user knowledge. Need: paste URL → pick title → go. | 1 day |
| 10 | **Pipeline Progress UX** | No real-time stage tracking visible to users. SSE exists but unused. | 1 day |
| 11 | **Landing Page** | No marketing site. No way to discover the product. | 1 day |
| 12 | **Transactional Email** | No welcome email, no password reset email, no billing receipts. | 1 day |

#### Tier 3: MEDIUM (needed for retention & growth)

| # | Gap | Why It Matters | Effort |
|---|-----|----------------|--------|
| 13 | **Job Queue** | In-process asyncio. Server restart = lost jobs. No retry/priority. | 2 days |
| 14 | **Per-tenant Storage** | Single Google Drive. No isolation. Kie.ai URLs expire. | 2 days |
| 15 | **Learning Insights Dashboard** | The moat feature — show users what AI learned about their audience. | 1 day |
| 16 | **Team Collaboration** | Multi-tenant schema supports it, but no invite flow or role enforcement. | 1 day |
| 17 | **Analytics 2.0** | CTR trends, best posting times, topic heatmap. Current analytics is basic. | 1 day |
| 18 | **Video Preview Player** | No in-app player for rendered output. | 0.5 day |
| 19 | **Rate Limiting** | No per-tenant API limits or concurrent job limits. | 0.5 day |
| 20 | **Error Monitoring (Sentry)** | Console only. No structured error tracking. | 0.5 day |

#### Tier 4: POLISH (launch quality)

| # | Gap | Why It Matters | Effort |
|---|-----|----------------|--------|
| 21 | **Documentation** | No help docs, no API reference, no tooltips. | 2 days |
| 22 | **Demo Mode** | No public demo. Can't show product without signup. | 1 day |
| 23 | **Voice Clone** | ElevenLabs voice clone per channel. Premium add-on. | 1 day |
| 24 | **Brand Kit** | Logo, colors, intro/outro, watermark per channel. | 1 day |
| 25 | **Webhook API** | External integrations (Zapier, Make.com). | 1 day |
| 26 | **Data Export / GDPR** | No bulk download. No GDPR compliance. | 0.5 day |
| 27 | **Load Testing** | No k6 or equivalent. Don't know breaking point. | 0.5 day |

---

## Sequential Execution Plan

> 20 working days to production-ready SaaS. Each day has a clear deliverable.

### Week 1: "Make it Payable" (Revenue Path)

| Day | Focus | Deliverables | Success Criteria |
|-----|-------|-------------|------------------|
| **1** | Billing UI | `/billing` page (current plan, usage, upgrade CTA, portal link) + `/pricing` page (3 tiers, feature grid) | User can see their plan and click "Upgrade" |
| **2** | Plan Enforcement | `tenant_usage` table, `check_plan_limits()` middleware, usage increment hooks | Free user blocked at video limit with upgrade prompt |
| **3** | Trial + Password Reset | 14-day trial logic, password reset flow (token table + email + page), disable dev-token | New signup gets 14-day Creator trial. Forgot password works. |
| **4** | Fix Broken Endpoints + Empty States | Fix `create-idea`, `upload`, `skills/pipeline/*`. Add empty states to top 8 pages. | No 500 errors on core flows. New users see helpful CTAs. |
| **5** | Create Video Simplification | New create flow: URL/topic → AI suggests 3 titles → pick → pipeline starts | 3-click video creation from topic input |

### Week 2: "Make it Good" (Core UX)

| Day | Focus | Deliverables | Success Criteria |
|-----|-------|-------------|------------------|
| **6** | Pipeline Progress UX | Real-time stage tracker with SSE. Current stage highlighted, ETA. | User sees "Generating Script... 2/6 scenes" live |
| **7** | Error Handling + Toasts | Global error boundary, toast notification system, pipeline event toasts | Errors surface visually. Successes celebrated. |
| **8** | Landing Page | Marketing site at `/`. Hero, feature grid, pricing, demo video embed. | Public page that sells the product |
| **9** | Transactional Email | Resend integration: welcome, password reset, trial ending (3-day warning), billing receipts | Users get email on signup, reset, and billing events |
| **10** | Dashboard Redesign | Action-first dashboard: active video cards, pending approvals, quick-start CTA, usage meter | Dashboard answers "What should I do next?" |

### Week 3: "Make it Reliable" (Infrastructure)

| Day | Focus | Deliverables | Success Criteria |
|-----|-------|-------------|------------------|
| **11** | Job Queue | Redis + arq/dramatiq. Pipeline stages as persistent jobs. Retry, priority, dead letter. | Server restart doesn't kill running pipelines |
| **12** | Job Queue (cont.) + Rate Limiting | Finish job queue wiring. Add per-tenant rate limits and concurrent job limits. | Tenant can't overwhelm system. Jobs survive restarts. |
| **13** | Per-tenant Storage | Supabase Storage for SaaS users. Per-tenant folders. Signed URLs. | Each tenant's assets isolated. URLs don't expire. |
| **14** | Error Monitoring | Sentry integration (backend + frontend). Structured logging with tenant_id context. | Errors captured with full context. Alert on spikes. |
| **15** | Security Hardening | CORS lockdown, SQL injection audit, rate limiting on auth endpoints, CSRF tokens | No OWASP top 10 vulnerabilities |

### Week 4: "Make it Sticky" (Growth & Launch)

| Day | Focus | Deliverables | Success Criteria |
|-----|-------|-------------|------------------|
| **16** | Learning Insights Dashboard | Show users what AI learned: patterns, CTR formulas, topic performance | Users say "wow, it knows my audience" |
| **17** | Analytics 2.0 | CTR trends over time, topic heatmap, competitor benchmarking | Data-driven decisions visible |
| **18** | Video Preview + Brand Kit | In-app video player, logo/colors/watermark settings per channel | Users can preview and brand their videos |
| **19** | Documentation + Demo | Help docs (getting started, FAQ), public demo with pre-loaded data | New users can self-serve. Demo sells without signup. |
| **20** | Beta Launch Prep | Load test (k6), backup strategy, ToS/privacy policy, invite 10 beta creators | Ready to accept paying users |

---

## Feature Set Blueprint

### Core Product (what makes this a SaaS)

```
USER JOURNEY:
  Sign Up (email/Google) → Onboarding (channel + niche) → Free Trial (14-day Creator)
       ↓
  Create Video: paste URL or type topic → AI suggests 3 titles → pick one → go
       ↓
  Pipeline runs: research → script → voice → images → sound → video → thumbnail → render
       ↓
  Review: script editing, image regeneration, thumbnail workshop, voice tweaks
       ↓
  Publish: download MP4 or auto-upload as YouTube draft
       ↓
  Learn: AI monitors CTR/retention → extracts patterns → next video is better
       ↓
  Autopilot: system picks topics, generates videos, learns autonomously
```

### Pricing Tiers

| | Starter ($49/mo) | Creator ($149/mo) | Studio ($399/mo) |
|---|---|---|---|
| Videos/month | 4 | 15 | 50 |
| Visual styles | 1 | 3 | All |
| Autopilot | - | Yes | Yes |
| Learning loop | Basic | Full | Full |
| Team seats | 1 | 1 | 3 |
| Render priority | Standard | Priority | Dedicated |
| API access | - | - | Yes |
| Voice clone | - | - | Yes |

### UI/UX Design Principles

1. **Answer "What should I do next?"** — Dashboard is action-first, not data-first
2. **3-click creation** — Topic in, title picked, pipeline running. Power users get expandable "Advanced"
3. **Progress is visible** — Every pipeline stage shows real-time status with ETA
4. **AI insights surface** — Don't hide the learning loop. Show users what the system discovered
5. **Empty states sell** — Every empty page has a compelling CTA, not a blank div
6. **Errors are helpful** — Toast notifications with actionable text, not silent failures
7. **Mobile-aware** — 6-tab bottom bar on mobile, collapsible sidebar on desktop

---

## Daily Log

### Day 0 — 2026-04-06 (Planning)

**Focus:** Full SaaS analysis and sequential execution plan.

**Completed:**
- Comprehensive audit: 24 frontend pages, 23 backend routers, 14+ DB tables, full pipeline
- Identified 27 gaps across 4 severity tiers
- Created 20-day sequential execution plan
- Defined feature set blueprint and pricing tiers
- Established UI/UX design principles

**Key Insights:**
1. **The pipeline is 100% done.** All 13 stages have real implementations. This is the hard part, and it's finished.
2. **Auth + billing backend exist but billing has no UI.** Revenue is one page away.
3. **The learning loop is the moat.** It should be visible to users early (Day 16), not hidden behind the dashboard.
4. **Agent team is operational** but focused on internal dev, not user-facing quality. Should pivot to UX bugs post-launch.
5. **Biggest risk is not features — it's wiring.** The CLAUDE.md warns that unwired features are the #1 bug source. Every feature needs end-to-end verification.

**Tomorrow's Plan (Day 1):**
- Build `/billing` page: current plan display, usage stats, upgrade/downgrade buttons, invoice link
- Build `/pricing` page: public pricing grid with 3 tiers, feature comparison, CTA → Stripe checkout
- Wire both to existing Stripe checkout/portal endpoints
- Verify end-to-end: signup → see free plan → click upgrade → Stripe checkout → plan updated

---

### Day 1 — 2026-04-07 (Corrected Assessment + Revised Plan)

**Focus:** Morning audit revealed the state is significantly better than the Day 0 roadmap assumed. Revised the entire plan.

#### Audit Corrections (what the roadmap got wrong)

| Roadmap Claim | Actual State | Impact |
|---------------|-------------|--------|
| "3 broken endpoints" (create-idea, upload, skills/pipeline) | **All 3 work.** `create-idea` calls `executor.create_idea()`, `upload` exists at `/upload/{video_id}`, skills catch-all is correctly last. | **Day 4 eliminated.** No fixes needed. |
| "No billing UI" | **Billing UI exists in `/settings`.** Stripe checkout, portal link, plan display with 3 tiers ($25/$40/$75). | Day 1 scope shrinks — need `/pricing` public page, not rebuild billing from scratch. |
| "Most pages are stubs" | **All 17 pages are real implementations** with API integration, state management, and styled components. | Empty states still needed but the pages themselves are production-grade. |
| "No auth guard" | **`AuthenticatedShell.tsx` exists** with plan gating. Pro features locked. Route protection works. | Auth layer is done. Focus shifts to enforcement depth. |
| Pricing: "$49 / $149 / $399" | **Settings page shows $25 / $40 / $75.** Stripe price IDs in env vars. | Need to decide: are these the real prices or placeholders? |

#### What ACTUALLY Still Needs Building

**Tier 1 — Revenue Blockers (can't charge without these):**

| # | Gap | What Exists | What's Missing | Effort |
|---|-----|-------------|----------------|--------|
| 1 | **Public `/pricing` page** | Billing in /settings (auth required) | Public page for non-logged-in visitors to see plans and click "Start Free Trial" | 0.5 day |
| 2 | **Plan enforcement** | Auth guard blocks Pro routes | No video count limit, no render limit, no `tenant_usage` table, no `check_plan_limits()` | 1 day |
| 3 | **Free trial logic** | Accounts table has `plan` field | No `trial_ends_at`, no 14-day countdown, no downgrade-on-expiry | 0.5 day |
| 4 | **Password reset** | Email/password auth works | No recovery flow, no token table, no reset page, no email sending | 0.5 day |
| 5 | **Transactional email** | None | No welcome, reset, trial-ending, or billing emails. Need Resend or similar. | 0.5 day |
| 6 | **Disable dev-token** | Dev bypass exists for development | Must be environment-gated for production | 0.25 day |

**Tier 2 — User Retention (users churn without these):**

| # | Gap | What Exists | What's Missing | Effort |
|---|-----|-------------|----------------|--------|
| 7 | **Empty states** | All pages render real data | No helpful CTAs when data is empty. New user sees blank grids. | 1 day |
| 8 | **Error handling / toasts** | Some inline error display | No global error boundary, no toast system, pipeline failures silent | 1 day |
| 9 | **Create video simplification** | `/create` or pipeline create exists | Current flow requires domain knowledge. Need: paste URL → pick title → go | 1 day |
| 10 | **Pipeline progress UX** | SSE endpoint exists | No real-time stage visualization. User doesn't know what's happening. | 1 day |
| 11 | **Landing page** | No public marketing site | Need hero, feature showcase, pricing, demo video embed | 1 day |
| 12 | **Dashboard redesign** | Dashboard shows stats + recent videos | Not action-first. Should answer "what do I do next?" | 0.5 day |

**Tier 3 — Scale & Reliability:**

| # | Gap | Effort |
|---|-----|--------|
| 13 | Job queue (Redis + persistent jobs) | 2 days |
| 14 | Per-tenant storage (Supabase Storage) | 1.5 days |
| 15 | Error monitoring (Sentry) | 0.5 day |
| 16 | Security hardening (CORS, SQL audit, CSRF) | 1 day |
| 17 | Rate limiting per plan | 0.5 day |

**Tier 4 — Growth & Polish:**

| # | Gap | Effort |
|---|-----|--------|
| 18 | Learning insights dashboard (THE moat feature) | 1 day |
| 19 | Analytics 2.0 (CTR trends, heatmaps) | 1 day |
| 20 | Video preview player + brand kit | 1 day |
| 21 | Documentation + help | 1.5 days |
| 22 | Demo mode (public, pre-loaded) | 1 day |
| 23 | Beta launch prep (load test, legal, invites) | 1 day |

---

## Revised Sequential Execution Plan (18 Days)

> Shortened from 20 to 18 days. Day 4 eliminated (endpoints not broken). Some days consolidated.

### Week 1: "Make it Payable" (Revenue Path)

| Day | Date | Focus | Deliverables | Success Criteria |
|-----|------|-------|-------------|------------------|
| **1** | Apr 7 | Public Pricing + Plan Enforcement | `/pricing` public page (3 tiers, feature grid, CTA → checkout). `tenant_usage` table. `check_plan_limits()` middleware. | Non-logged-in user sees pricing. Logged-in user blocked at video limit. |
| **2** | Apr 8 | Trial + Password Reset + Email | 14-day trial on signup. Password reset flow (token → email → page). Resend integration for 3 emails (welcome, reset, trial-ending). Disable dev-token in prod. | New signup gets trial. Forgot password works. Dev-token off in production. |
| **3** | Apr 9 | Create Video Simplification | Simplified create: URL or topic → AI suggests 3 titles → pick → pipeline starts. Expandable "Advanced" for power users. | 3-click video creation. |
| **4** | Apr 10 | Empty States + Error Handling | Empty states on all key pages (dashboard, pipeline, competitors, analytics, learnings, discovery). Global error boundary. Toast notification system. | New user sees helpful CTAs. Errors surface visually. |
| **5** | Apr 11 | Pipeline Progress UX | Real-time stage tracker (SSE). Current stage highlighted with ETA. Per-stage "View Details" expansion. | User sees "Generating Script... 2/6 scenes" live. |

### Week 2: "Make it Good" (Core UX + Marketing)

| Day | Date | Focus | Deliverables | Success Criteria |
|-----|------|-------|-------------|------------------|
| **6** | Apr 14 | Landing Page | Marketing page at `/`. Hero section, feature showcase, pricing embed, demo video, social proof area. | Public page that sells the product. |
| **7** | Apr 15 | Dashboard Redesign | Action-first dashboard: active video progress cards, pending approvals, quick-start CTA, usage meter (videos used / plan limit). | Dashboard answers "What should I do next?" |
| **8** | Apr 16 | Learning Insights Dashboard | Surface AI learnings: proven patterns, CTR formulas, topic performance, anti-patterns. Pull from memory files + Osiris tables. | Users say "wow, it knows my audience." |
| **9** | Apr 17 | Analytics 2.0 | CTR trends over time, topic performance heatmap, competitor benchmarking, best-performing framework analysis. | Data-driven decisions visible and actionable. |
| **10** | Apr 18 | Settings Completion + Brand Kit | API key validation feedback, integration status indicators, brand kit (logo, accent color, intro/outro), channel profile editor. | Settings page is complete. Brand elements persist to renders. |

### Week 3: "Make it Reliable" (Infrastructure)

| Day | Date | Focus | Deliverables | Success Criteria |
|-----|------|-------|-------------|------------------|
| **11** | Apr 21 | Job Queue (Part 1) | Redis + arq/dramatiq setup. Pipeline stages as persistent jobs. Basic retry + dead letter queue. | Jobs survive server restart. |
| **12** | Apr 22 | Job Queue (Part 2) + Rate Limiting | Finish queue wiring. Per-tenant rate limits (by plan). Concurrent job limits (1 Starter / 3 Pro / 5 Studio). | No tenant can overwhelm system. |
| **13** | Apr 23 | Per-tenant Storage | Supabase Storage for SaaS. Per-tenant folders. Signed URLs. Migrate asset references from Kie.ai temp URLs. | Assets isolated per tenant. URLs permanent. |
| **14** | Apr 24 | Error Monitoring + Logging | Sentry (backend + frontend). Structured JSON logging with tenant_id + video_id context. Alert on error rate spikes. | Errors captured with context. Alerting works. |
| **15** | Apr 25 | Security Hardening | CORS lockdown (remove hardcoded IPs). SQL injection audit (f-strings → parameterized). CSRF tokens. Auth rate limiting. Audit logging. | No OWASP top 10 vulnerabilities. |

### Week 4: "Make it Launchable" (Polish + Go-Live)

| Day | Date | Focus | Deliverables | Success Criteria |
|-----|------|-------|-------------|------------------|
| **16** | Apr 28 | Video Preview + Polish | In-app video player for rendered output. Thumbnail preview. Script overlay toggle. UI polish pass across all pages. | Users preview videos in-app. |
| **17** | Apr 29 | Documentation + Demo | Getting started guide, FAQ, tooltips on complex features. Public demo with pre-loaded data (browse without signup). | New users self-serve. Demo converts without auth. |
| **18** | Apr 30 | Beta Launch Prep | Load test (k6). Backup strategy. ToS + Privacy Policy. Invite 10 beta creators. Launch checklist verification. | Ready to accept paying users. |

---

## Pricing Decision Needed

**Current state:** Settings page shows $25 / $40 / $75 per month.
**Roadmap proposed:** $49 / $149 / $399 per month.

These are very different price points. Need to decide:
- Are current prices placeholders from early dev?
- Does the value justify $149/mo for Creator tier?
- Competitor analysis: Pictory ($25-$75), Synthesia ($29-$89), InVideo ($25-$60)

**Recommendation:** Start with competitive pricing ($29 / $79 / $199) for beta. Increase after proving the learning loop moat. The autonomous CTR improvement is the premium justifier — but it needs proof first.

---

## Architecture Observations (from today's audit)

1. **Billing types are scattered.** `Subscription` interface lives in `api.ts` inline, not in `types.ts`. Should consolidate.
2. **Plan gating already works** in `AuthenticatedShell.tsx` for route-level blocking, but there's no per-action enforcement (e.g., "you've used 4/4 videos this month").
3. **Settings page does double duty** — project settings + billing. Consider separating into dedicated tabs or pages as complexity grows.
4. **The 6-agent team** is powerful but currently focused on internal dev velocity. Post-launch, these agents should shift to: monitoring user errors, auto-fixing pipeline failures, and A/B testing UI improvements.
5. **SSE endpoint exists** (`/api/activity/stream`) but the frontend doesn't consume it for pipeline progress. This is the lowest-hanging UX improvement.

---

**Today's Execution (Day 1):**
1. Build `/pricing` public page — visible without login, 3 tiers, feature comparison table, CTA → Stripe checkout
2. Create `tenant_usage` table — videos_created, render_minutes, storage_bytes, api_calls, period_start/end
3. Build `check_plan_limits()` FastAPI dependency — intercepts pipeline actions, checks against plan limits
4. Wire usage increment hooks into pipeline stages — count videos, renders, API calls
5. Add upgrade prompt modal — triggered when user hits limit, shows plan comparison + upgrade CTA
6. Verify end-to-end: free user → create videos → hit limit → see upgrade prompt → checkout → upgraded

---

*Updated daily. Each session adds to the log and adjusts the plan as we learn.*
