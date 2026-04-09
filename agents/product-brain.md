# StoryEngine Product Brain

_Last refreshed: 2026-04-09 (handcrafted from live codebase audit)_
_Next refresh: run `./agents/refresh-product-brain.sh` after any session_

---

## Product Identity

**What it is:** StoryEngine — "topic in, video out." Multi-tenant SaaS where creators type a topic and the AI pipeline handles everything: research → script → voice → custom images → video clips → thumbnail → render → YouTube upload.

**The moat:** The learning loop. After 10 videos, the AI knows the user's audience. CTR improves automatically. No competitor has this.

**Pricing tiers:**
| Tier | Price | Videos/mo | Key features |
|------|-------|-----------|--------------|
| Starter | $25/mo | 4 | 1 visual style, standard render |
| Creator | $40/mo | 15 | 3 styles, autopilot, full learning loop |
| Studio | $75/mo | 50 | All styles, API access, voice clone, 3 seats |

**UX principles:** Action-first dashboard, 3-click video creation, visible pipeline progress, AI insights surface, empty states sell, errors are helpful, mobile-aware.

**Stack:** Next.js 16 + React 19 + TypeScript + TailwindCSS 4 + Framer Motion | FastAPI + asyncpg + Supabase PostgreSQL
**Design tokens:** `--turquoise` (#00D4AA), `--gold`, `--orange`, `--bg-void` (#0A0A0B), `GlassCard`, `ActionButton`, `StatusPill`, `Spinner`, `Modal`

---

## Implementation Inventory

### Auth & Access
| Feature | Status | Evidence |
|---------|--------|----------|
| Email/password auth (PBKDF2-SHA256) | ✅ Done | `routes/settings.py`, `routes/google_auth.py` |
| Google OAuth | ✅ Done | `routes/google_auth.py`, `/login` page |
| JWT 30-day sessions | ✅ Done | auth middleware in `main.py` |
| AuthenticatedShell route protection | ✅ Done | `frontend/src/components/` |
| dev-token bypass (disabled in prod) | ✅ Done | env-gated |
| Onboarding wizard (3-step: channel → keys → done) | ✅ Done | `frontend/src/app/onboarding/` |
| Password reset flow (token → email → page) | ✅ Done | `password_reset_tokens` table, `/forgot-password`, `/reset-password` |
| Multi-tenant isolation (tenant_id scoping) | ✅ Done | `tenants` + `memberships` tables, RLS |

### Billing & Plans
| Feature | Status | Evidence |
|---------|--------|----------|
| Stripe checkout + webhooks + portal | ✅ Done | `routes/billing.py` |
| `/billing` page (plan display, usage bars, upgrade CTA) | ✅ Done | `frontend/src/app/billing/` |
| `/pricing` public page (3 tiers, feature grid, CTA) | ✅ Done | `frontend/src/app/pricing/` |
| Plan enforcement middleware (`check_plan_limits`) | ✅ Done | `tenant_usage` table, usage hooks |
| Free trial logic (14-day Creator trial on signup) | ✅ Done | `accounts` table, trial countdown |
| Trial countdown badge + banner | ✅ Done | frontend components |
| Transactional email (welcome, reset, trial warning) | ✅ Done | `email_service.py`, `email_tasks.py` |
| Billing receipt email on checkout | ✅ Done | wired in `routes/billing.py` |

### Core Pipeline & UI
| Feature | Status | Evidence |
|---------|--------|----------|
| Full video pipeline (research→render→upload) | ✅ Done | 13 stages, all with `run.py` entry points |
| Pipeline dashboard (all stages, status tabs) | ✅ Done | `frontend/src/app/pipeline/` |
| Video detail page (all production tabs) | ✅ Done | `frontend/src/components/production/` |
| Pipeline progress UX (SSE real-time stage tracking) | ✅ Done | `/api/activity/stream` SSE, `stage_transitions` table |
| Script review + approval | ✅ Done | `routes/review.py`, `/review` page |
| Render tab + `RenderTab.tsx` | ✅ Done | component exists |
| System prompt editors (per pipeline stage) | ✅ Done | `routes/system_prompts.py`, `/system-prompts` |
| Storyboard viewer | ✅ Done | `frontend/src/app/storyboard/` |
| Visuals page | ✅ Done | `frontend/src/app/visuals/` |

### Discovery & Competitors
| Feature | Status | Evidence |
|---------|--------|----------|
| Competitors page (pagination, filters, scrape progress) | ✅ Done | `frontend/src/app/competitors/`, `routes/` |
| Discovery page | ✅ Done | `frontend/src/app/discovery/`, `routes/discovery.py` |
| Autopilot page + controls | ✅ Done | `frontend/src/app/autopilot/`, `routes/autopilot.py` |
| Calendar page | ✅ Done | `frontend/src/app/calendar/` |

### Analytics & Learning
| Feature | Status | Evidence |
|---------|--------|----------|
| Analytics page (overview, CTR timeline, framework perf) | ✅ Done | `frontend/src/app/analytics/`, `routes/analytics.py` |
| Learnings page (pattern cards, extract/analyze actions) | ✅ Done | `frontend/src/app/learnings/`, `routes/learning_extraction.py` |
| Learnings insights redesign (hero stats, recommendations, topic perf) | 🔵 PRD 4 T1 | `frontend/src/app/learnings/page.tsx` |
| Analytics 2.0 (topic heatmap, competitor benchmark) | 🔵 PRD 4 T2 | `routes/analytics.py` + analytics page |
| Video preview player (in-app, RenderTab) | 🔵 PRD 4 T3 | `components/production/RenderTab.tsx` |

### Marketing & Legal
| Feature | Status | Evidence |
|---------|--------|----------|
| Landing page (hero, features, pricing, CTA) | ✅ Done | `frontend/src/app/page.tsx` |
| `/terms` and `/privacy` legal pages | ✅ Done | `frontend/src/app/terms/`, `privacy/` |
| `/demo` page | ✅ Done | `frontend/src/app/demo/` |
| `/docs` page | ✅ Done | `frontend/src/app/docs/` |

### Infrastructure (Gaps — Week 3 of roadmap)
| Feature | Status | Evidence |
|---------|--------|----------|
| Job Queue (Redis + arq/dramatiq, persistent pipeline jobs) | ❌ Missing | No Redis setup. Pipeline uses in-process asyncio. Server restart = lost jobs. |
| Per-tenant storage (Supabase Storage, signed URLs) | ❌ Missing | Assets use Kie.ai URLs (expire) and Google Drive (not isolated). |
| Error monitoring (Sentry, backend + frontend) | ❌ Missing | Console only. No structured error tracking. |
| Security hardening (CORS lockdown, SQL audit, CSRF) | ❌ Missing | SEC-1 through SEC-6 open in todo.md |
| Rate limiting per plan (concurrent job limits) | ❌ Missing | No per-tenant API rate limits |
| Storyboard extraction V2 (Supabase rewrite) | ❌ Blocked | T27-003: `extraction.py` not wired into pipeline for Supabase videos |
| Permanent asset storage (all image gen steps) | ❌ Missing | T27-008: Kie.ai URLs expire |

### Polish & Launch (Week 4 of roadmap)
| Feature | Status | Evidence |
|---------|--------|----------|
| Getting started guide (help docs, FAQ) | 🔵 PRD 4 (T9 pending) | `/docs` page exists but needs content |
| Brand kit (logo, accent color, intro/outro per channel) | 📋 Planned | Week 4 Day 10 |
| Load testing (k6), backup strategy | 📋 Planned | Week 4 Day 18 |
| Webhook API (Zapier, Make.com) | 📋 Planned | Tier 4 |
| GDPR / data export | 📋 Planned | Tier 4 |

---

## Roadmap Progress (18-Day Plan)

| Day | Date | Focus | Status |
|-----|------|-------|--------|
| 1 | Apr 7 | Public pricing + plan enforcement | ✅ Done |
| 2 | Apr 8 | Trial + password reset + email + dev-token | ✅ Done |
| 3 | Apr 9 | Create video simplification | 🔵 In progress (PRD 4 T4-T7) |
| 4 | Apr 10 | Empty states + error handling | ✅ Done (PRD 1) |
| 5 | Apr 11 | Pipeline progress UX | ✅ Done (PRD 2) |
| 6 | Apr 14 | Landing page | ✅ Done |
| 7 | Apr 15 | Dashboard redesign | 📋 Pending |
| 8 | Apr 16 | Learning insights dashboard | 🔵 In progress (PRD 4 T1) |
| 9 | Apr 17 | Analytics 2.0 | 🔵 In progress (PRD 4 T2) |
| 10 | Apr 18 | Settings completion + brand kit | 📋 Pending |
| 11 | Apr 21 | Job queue (Part 1) | ❌ Not started |
| 12 | Apr 22 | Job queue (Part 2) + rate limiting | ❌ Not started |
| 13 | Apr 23 | Per-tenant storage | ❌ Not started |
| 14 | Apr 24 | Error monitoring + logging | ❌ Not started |
| 15 | Apr 25 | Security hardening | ❌ Not started |
| 16 | Apr 28 | Video preview + UI polish | 🔵 In progress (PRD 4 T3) |
| 17 | Apr 29 | Documentation + demo | 🔵 In progress (PRD 4 T9) |
| 18 | Apr 30 | Beta launch prep | 📋 Pending |

---

## Current Priority Gap Queue

### Tier 1 — Active (PRD 4 remaining tasks T11-T15)
PRD 4 is the active PRD. Complete these before generating PRD 5.

### Tier 2 — Next PRD (Week 3: Infrastructure)
1. **Job Queue** — Redis + arq. Pipeline stages as persistent jobs. Retry, dead letter. Server restart kills jobs today.
2. **Per-tenant Storage** — Supabase Storage for SaaS. Kie.ai URLs expire and aren't tenant-isolated.
3. **Error Monitoring** — Sentry (backend + frontend). No visibility into production errors.
4. **Security Hardening** — SEC-1 (dev-token in dev), SEC-4 (hardcoded CORS IP), SEC-5 (f-string SQL), rate limiting on auth.

### Tier 3 — Week 4: Polish & Launch
5. **Dashboard redesign** — Action-first: active video cards, pending approvals, quick-start CTA, usage meter.
6. **Brand kit** — Logo, accent color, intro/outro, watermark per channel. Persist to render.
7. **Settings completion** — API key validation feedback, integration status indicators.
8. **Beta launch prep** — Load test (k6), ToS/Privacy complete, invite 10 beta creators.

### Tier 4 — Post-Beta
9. Webhook API (Zapier, Make.com)
10. GDPR / data export
11. Team collaboration (invite flow, role enforcement — schema supports it)
12. Voice clone per channel

---

## Live Codebase Snapshot

**Frontend pages (26):** activity, analytics, autopilot, billing, calendar, competitors, dashboard, demo, discovery, docs, forgot-password, learnings, login, onboarding, pipeline, pricing, privacy, profile, render, reset-password, review, settings, storyboard, system-prompts, terms, visuals + landing (page.tsx)

**Backend route files (24):** activity, analytics, assets, autopilot, billing, channel_profile, dashboard, demo, discovery, google_auth, learning_extraction, niche, pipeline, preferences, profile, projects, review, settings, skills, system_prompts, videos, visual_styles, youtube_sync, agents

**DB tables (22):** tenants, users, memberships, videos, scripts, assets, competitor_channels, competitor_videos, learnings, title_insights, title_tests, autopilot_config, discovery_ideas, channel_profiles, accounts, projects, user_preferences, tenant_prompt_defaults, stage_transitions, bot_activity, tenant_usage, password_reset_tokens

---

## PRD Writing Guidelines for This Product

### Task Structure
Each task: single role (backend-dev | frontend-dev | qa-engineer | security-auditor), 15-45 min effort, ONE concern. 8-15 tasks per PRD.

### File Conventions
- Backend: `storyengine/backend/routes/<name>.py` — register in `storyengine/backend/main.py`
- Frontend pages: `storyengine/frontend/src/app/<page>/page.tsx`
- Frontend components: `storyengine/frontend/src/components/<category>/<Name>.tsx`
- API layer: `storyengine/frontend/src/lib/api.ts`
- Types: `storyengine/frontend/src/lib/types.ts`
- DB migrations: `storyengine/backend/migrations/<NNN>_<name>.sql` + update `storyengine/schema.sql`
- Pydantic models: `storyengine/backend/models.py`

### Acceptance Criteria Patterns
```bash
# API endpoint exists
curl -s -o /dev/null -w '%{http_code}' http://localhost:8001/api/endpoint | grep -q 200

# DB column exists
psql "$DATABASE_URL" -c "SELECT column_name FROM information_schema.columns WHERE table_name='videos'" | grep -q new_column

# TypeScript compiles
cd storyengine/frontend && npx tsc --noEmit

# File exists
test -f storyengine/backend/routes/new_route.py

# Router registered in main.py
grep -q "new_route" storyengine/backend/main.py
```

### Wiring Checklist (every feature must pass)
- DB column exists (migrated, not just in schema.sql)
- Route registered in `main.py`
- Pydantic model matches route response
- Frontend fetchApi calls correct endpoint path
- TypeScript types match backend response fields
- Component wired to real API data (not mock)
- Loading + error + empty states handled
- `npx tsc --noEmit` passes

### Design System (mandatory for all UI tasks)
- Dark background: `var(--bg-void)` (#0A0A0B), cards: `glass-card` class
- Accents: `var(--turquoise)` (#00D4AA), `var(--gold)`, `var(--orange)`, `var(--red)` for errors
- Text: `var(--text-primary)`, `var(--text-secondary)`, `var(--text-tertiary)`
- Font: `font-display` for headings
- Components: `GlassCard`, `ActionButton`, `StatusPill`, `Spinner`, `Modal`, `FilterSelect`, `VerdictBadge`
- Motion: Framer Motion with container/item stagger pattern

### What NOT to Spec (already built — do not duplicate)
Auth, billing UI, Stripe, plan enforcement, trial logic, password reset, email service, landing page, pricing page, legal pages, pipeline core, SSE progress tracking, toast system, error boundaries, empty states, onboarding wizard, competitors page, discovery, analytics baseline, learnings baseline.
