# StoryEngine Product Brain
_Last refreshed: 2026-04-13 08:09 (auto-generated)_

---

## Section 1: Product Identity

StoryEngine is an AI video production SaaS that turns a topic or URL into a YouTube-ready video through a 13-stage pipeline. It's built for solo creators and small teams who want data-driven content without a production crew. The moat is the **learning loop**: every video distilled into a content intelligence layer that continuously improves title structures, hook types, and thumbnail strategies per niche.

| Plan | Price/mo | Videos/mo | Key Differentiator |
|------|----------|-----------|-------------------|
| Starter | $29 | 4 | Pipeline access, basic analytics |
| Creator | $79 | 12 | Autopilot, competitor tracking, learning insights |
| Studio | $199 | 40 | Priority render, brand kit, team seats |

**UX Principles:** (1) Action-first — every page answers "what do I do next?" (2) 3-click creation — topic → title pick → go. (3) Visible progress — live stage tracker with ETA. (4) AI insights surface — learning loop surfaces patterns to users. (5) Empty states sell — first-run states explain value, not void. (6) Errors are helpful — toast system + specific recovery instructions. (7) Mobile-aware — responsive layouts, no desktop-only flows.

**Stack:** Next.js 16 + React 19 + TypeScript / FastAPI + asyncpg / Supabase PostgreSQL  
**Design tokens:** `--turquoise`, `--gold`, `--bg-void` | Components: `GlassCard`, `ActionButton`, `StatusPill`

---

## Section 2: Implementation Inventory

### Auth & Access

| Feature | Status | Evidence |
|---------|--------|----------|
| Email/password login + signup | ✅ DONE (verified) | PRD1, `routes/google_auth.py`, `app/login/` |
| Google OAuth | ✅ DONE (verified) | PRD1, `routes/google_auth.py` |
| Password reset (token + email + page) | ✅ DONE (unverified) | `password_reset_tokens` table, `app/forgot-password/`, `app/reset-password/` |
| Onboarding flow (post-signup) | ✅ DONE (unverified) | `app/onboarding/`, recent fix commit 8d43ac1 |
| Multi-tenant RLS (24 policies) | ✅ DONE (verified) | PRD3, `schema.sql`, `tenants` table |
| JWT sessions (30-day) | ✅ DONE (verified) | PRD3 |

### Billing & Plans

| Feature | Status | Evidence |
|---------|--------|----------|
| Billing page + Stripe portal link | ✅ DONE (unverified) | `app/billing/`, `routes/billing.py` |
| Pricing page (3 tiers, feature grid) | ✅ DONE (unverified) | `app/pricing/` |
| Stripe webhook + subscription sync | ✅ DONE (unverified) | `routes/billing.py` |
| Plan enforcement (`check_plan_limits`) | ❌ MISSING | Roadmap Day 1 — not yet built |
| 14-day trial logic | ❌ MISSING | Roadmap Day 2 — not yet built |
| `tenant_usage` table + increment hooks | ✅ DONE (unverified) | `tenant_usage` table in DB |
| Notification preferences backend | ✅ DONE (unverified) | PRD4-T3, `routes/preferences.py` |

### Core Pipeline & UI

| Feature | Status | Evidence |
|---------|--------|----------|
| 13-stage video pipeline | ✅ DONE (verified) | PRD1, `routes/pipeline.py`, `pipeline_executor.py` |
| Dashboard page | ✅ DONE (verified) | PRD1, `app/dashboard/`, `routes/dashboard.py` |
| Pipeline page (stage list + status) | ✅ DONE (verified) | PRD2, `app/pipeline/` |
| Pipeline SSE real-time progress | ✅ DONE (verified) | PRD2, `routes/pipeline.py` (SSE) |
| Create video flow (URL/topic → titles) | ✅ DONE (verified) | PRD1, `app/create/` |
| Review page (approve/reject) | ✅ DONE (unverified) | `app/review/`, `routes/review.py` |
| Storyboard viewer | ✅ DONE (unverified) | `app/storyboard/` |
| Render tab + video preview player | ✅ DONE (unverified) | PRD4-T8, `app/render/` |
| Export manifest endpoint | ✅ DONE (unverified) | PRD4-T5, `GET /api/videos/{id}/export-manifest` |
| Export button + Brand Kit UI | 🔵 ACTIVE | PRD4-T12 |
| Visual styles page | ✅ DONE (unverified) | `app/visuals/`, `routes/visual_styles.py` |
| System prompts editor | ✅ DONE (unverified) | `app/system-prompts/`, `routes/system_prompts.py` |

### Discovery & Competitors

| Feature | Status | Evidence |
|---------|--------|----------|
| Discovery page + idea generation | ✅ DONE (unverified) | `app/discovery/`, `routes/discovery.py` |
| Competitor channels + videos | ✅ DONE (unverified) | `app/competitors/`, `competitor_channels`, `competitor_videos` tables |
| Autopilot config + scoring | ✅ DONE (unverified) | `app/autopilot/`, `routes/autopilot.py`, `autopilot_config` table |
| Calendar view | ✅ DONE (unverified) | `app/calendar/` |
| YouTube sync | ✅ DONE (unverified) | `routes/youtube_sync.py` |

### Analytics & Learning

| Feature | Status | Evidence |
|---------|--------|----------|
| Learning Insights dashboard | ✅ DONE (unverified) | PRD4-T6, `app/learnings/` |
| Analytics 2.0 (topic chart + competitor card) | ✅ DONE (unverified) | PRD4-T7, `routes/analytics.py` |
| Content intelligence distillation pipeline | ✅ DONE (unverified) | `distillation/advisor.py`, `content_intelligence` table |
| Intelligence advisor + recommendations | ✅ DONE (unverified) | PRD4-T1, `GET /api/intelligence/recommendations` |
| Niche meta-analysis (Claude Haiku) | ✅ DONE (unverified) | `distillation/meta_analyzer.py`, `niche_meta_insights` table, migration 040 |
| Auto-distillation background task (12h) | ✅ DONE (unverified) | `_auto_distill_intelligence()` in `main.py` |
| Auto-extract learnings background task (24h) | ✅ DONE (unverified) | `_auto_extract_learnings()` in `main.py` |

### Marketing & Legal

| Feature | Status | Evidence |
|---------|--------|----------|
| Landing page (public `/`) | ❌ MISSING | Roadmap Day 6 (Apr 14) — not yet built |
| Demo mode backend (3 static endpoints) | ✅ DONE (unverified) | PRD4-T4, `routes/demo.py` |
| Demo mode frontend (landing + sub-pages) | 🔵 ACTIVE | PRD4-T11 |
| Getting Started guide (`/docs`) | ✅ DONE (unverified) | PRD4-T9, `app/docs/` |
| Terms of Service + Privacy Policy | ✅ DONE (unverified) | PRD4-T10, `app/terms/`, `app/privacy/` |

### Infrastructure

| Feature | Status | Evidence |
|---------|--------|----------|
| Rate limiting middleware (per-tenant) | ✅ DONE (verified) | PRD3, `rate_limit.py` imported in `main.py` |
| Background task persistence | ✅ DONE (verified) | PRD3, `background_tasks` table |
| Structured logging (JSON + tenant_id) | ✅ DONE (verified) | PRD3, `logging_config.py`, `RequestLoggingMiddleware` |
| Health check endpoint | ✅ DONE (verified) | PRD3 |
| Stale task recovery on startup | ✅ DONE (unverified) | `recover_stale_tasks()` called in `main.py` |
| Job queue (Redis + arq/dramatiq) | ❌ MISSING | Roadmap Day 11 (Apr 21) |
| Error monitoring — Sentry | ❌ MISSING | Roadmap Day 14 (Apr 24) |
| Per-tenant cloud storage | 📋 PLANNED | Deferred — users connect own Google Drive |

### Polish & Launch

| Feature | Status | Evidence |
|---------|--------|----------|
| Brand Kit backend (channel_profile extensions) | ✅ DONE (unverified) | PRD4-T2, `routes/channel_profile.py` |
| Transactional email (Resend) | ❌ MISSING | Roadmap Day 2 — not yet built |
| Beta regression sweep | 🔵 ACTIVE | PRD4-T13 |
| Security audit (auth, RLS, secrets) | 🔵 ACTIVE | PRD4-T14 |
| Performance + load readiness check | 🔵 ACTIVE | PRD4-T15 |

---

## Section 3: Roadmap Progress

| Day | Date | Focus | Status | PRD Reference |
|-----|------|-------|--------|---------------|
| 1 | Apr 7 | Pricing page + plan enforcement | ⚠️ Partial (page ✅, enforcement ❌) | PRD1 / Gap |
| 2 | Apr 8 | Trial + password reset + email | ⚠️ Partial (reset ✅, trial ❌, email ❌) | PRD2 / Gap |
| 3 | Apr 9 | Create video simplification | ✅ Done | PRD1 |
| 4 | Apr 10 | Empty states + error handling | ✅ Done | PRD1/PRD2 |
| 5 | Apr 11 | Pipeline Progress UX (SSE) | ✅ Done | PRD2 |
| 6 | Apr 14 | Landing page | ❌ Not started | — |
| 7 | Apr 15 | Dashboard redesign (action-first) | ⬜ Upcoming | — |
| 8 | Apr 16 | Learning Insights dashboard | ✅ Done | PRD4-T6 |
| 9 | Apr 17 | Analytics 2.0 | ✅ Done | PRD4-T7 |
| 10 | Apr 18 | Settings + Brand Kit | 🔵 Active | PRD4-T12 |
| 11 | Apr 21 | Job Queue P1 (Redis + arq) | ❌ Not started | — |
| 12 | Apr 22 | Job Queue P2 + rate limits | ❌ Not started | — |
| 13 | Apr 23 | Per-tenant storage | 📋 Deferred | — |
| 14 | Apr 24 | Sentry error monitoring | ❌ Not started | — |
| 15 | Apr 25 | Security hardening | 🔵 Active | PRD4-T14 |
| 16 | Apr 28 | Video preview + UI polish | ✅ Done | PRD4-T8 |
| 17 | Apr 29 | Docs + demo mode | ✅ Done | PRD4-T4,T9 |
| 18 | Apr 30 | Beta launch prep | 🔵 Active | PRD4-T13,T15 |

---

## Section 4: Current Priority Gap Queue

### Tier 1 — ACTIVE (PRD 4 remaining tasks)
- **PRD4-T11**: Demo mode frontend — landing + 3 sub-pages (no auth, static data from demo endpoints)
- **PRD4-T12**: Export button + Brand Kit UI + notification preference toggles in Settings
- **PRD4-T13**: Beta regression — full page sweep + API contract audit (curl each endpoint, check 200s)
- **PRD4-T14**: Security audit — cross-tenant SSE isolation, HTML injection in task queue, key exception leak
- **PRD4-T15**: Performance check — k6 load test, DB query timing, SSE backpressure

### Tier 2 — NEXT PRD (unbuilt roadmap items, spec-ready)
- **Landing page** (`/`): hero with demo video embed, 3-tier pricing grid, feature bullets, CTA → signup
- **Plan enforcement**: `check_plan_limits(tenant_id, action)` middleware + 402 response + upgrade CTA
- **14-day trial logic**: `trial_ends_at` on `tenants`, gate on expiry, 3-day warning email via Resend
- **Transactional email (Resend)**: welcome, password reset, trial-ending (3-day), billing receipts
- **Dashboard redesign**: active video cards, pending approvals widget, usage meter, quick-start CTA

### Tier 3 — WEEK 4 (polish before beta)
- Job queue (Redis + arq) — pipeline stages as persistent jobs surviving restarts
- Sentry integration — backend + frontend, structured logs with `tenant_id` context
- Autopilot auto-launch from intelligence recommendations (auto-select top-scored discovery idea)
- Notification preference toggles wired to Resend send/suppress logic

### Tier 4 — POST-BETA
- Per-tenant cloud storage (users connect own Google Drive)
- Team seats + member invites
- Stripe metered billing (per-video overage)
- GCS archival for raw transcripts post-distillation
- Extend distillation to `video_scripts`, `research_payloads`, `agent_paper_trails`

---

## Section 5: PRD Writing Guidelines

**Task structure:** One role (backend/frontend/qa/security), 0.5–2 day sizing, single concern per task. No task spans DB + route + frontend + types — split by layer.

**File path conventions:**
- Backend route: `storyengine/backend/routes/<name>.py` + register in `main.py`
- Pydantic model: `storyengine/backend/models.py`
- Migration: `storyengine/backend/migrations/<NNN>_<name>.sql`
- Frontend page: `storyengine/frontend/src/app/<route>/page.tsx`
- Frontend API: `storyengine/frontend/src/lib/api.ts`
- Frontend types: `storyengine/frontend/src/lib/types.ts`

**Acceptance criteria patterns:**
```
curl http://localhost:8001/api/<endpoint> | jq '.field'   # backend route works
psql $DB -c "SELECT * FROM <table> LIMIT 1;"              # migration applied
cd storyengine/frontend && npx tsc --noEmit               # types compile
grep -r "include_router(<name>)" storyengine/backend/main.py  # router registered
test -f storyengine/backend/routes/<name>.py              # file exists
```

**Wiring checklist (8 items — verify before marking done):**
1. Migration applied (column exists in Supabase, not just schema.sql)
2. Route registered in `main.py` (`app.include_router(...)`)
3. Pydantic model in `models.py` matches route response shape
4. `curl` test returns expected JSON with correct field names
5. Frontend `fetchApi` path matches backend route exactly (including `/api/` prefix)
6. TypeScript types match Pydantic field names exactly
7. Component consumes real API data (not hardcoded/mock)
8. `npx tsc --noEmit` passes with zero errors

**Design system (mandatory for any UI task):** Invoke `web-design-system` skill before writing any component. Use `GlassCard`, `ActionButton`, `StatusPill`. Tokens: `--turquoise` (primary), `--gold` (accent), `--bg-void` (background). Loading + error + empty states required on every data-fetching component.

---

### What NOT to Spec (Already Built — Do Not Reopen)

Email/password login, Google OAuth, password reset flow, onboarding post-signup, multi-tenant RLS, JWT sessions, billing page, pricing page, Stripe webhook sync, `tenant_usage` table, notification preferences backend, 13-stage video pipeline, dashboard page, pipeline page, SSE real-time progress, create video flow, review page, storyboard viewer, render tab, video preview player, export manifest endpoint, visual styles page, system prompts editor, discovery page, competitor channels + videos, autopilot config + scoring, calendar view, YouTube sync, learning insights dashboard, analytics 2.0 frontend, content intelligence distillation, intelligence advisor + recommendations, niche meta-analysis engine, auto-distillation background task, auto-extract learnings task, demo mode backend, getting started `/docs`, terms of service, privacy policy, rate limiting middleware, background task persistence, structured logging, health check, stale task recovery, brand kit backend.
