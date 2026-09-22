# StoryEngine Product Brain
_Last refreshed: 2026-04-10 06:43 (auto-generated)_

---

## Section 1: Product Identity

StoryEngine is an AI video production SaaS that turns a topic or URL into a fully produced YouTube video — script, voice, images, animation, and upload — with zero manual steps. Built for solo creators and small teams who want channel-scale output without a production crew. The moat: an autonomous autopilot that learns from CTR and VPH data, compounding title formulas and visual styles over time.

### Pricing

| Tier | Price | Videos/mo | Key Differentiator |
|------|-------|-----------|-------------------|
| Starter | $29/mo | 4 | Core pipeline, community support |
| Creator | $79/mo | 15 | Autopilot, brand kit, analytics |
| Studio | $199/mo | 50 | API access, team seats, white-label |

### UX Principles

1. **Action-first** — Dashboard answers "what do I do next?" Every page has one primary CTA.
2. **3-click creation** — URL/topic → pick title → pipeline starts. Zero config required.
3. **Visible progress** — SSE real-time stage tracker. Current step + ETA always visible.
4. **AI insights surface** — Learning patterns, CTR formulas, competitor gaps shown in UI.
5. **Empty states sell** — No blank pages. Every empty state explains value and prompts action.
6. **Errors are helpful** — Toast notifications with specific next steps, never raw API errors.
7. **Mobile-aware** — Responsive layouts. Key dashboards usable on phone.

### Stack

**Frontend:** Next.js 16 · React 19 · TypeScript · TailwindCSS 4 · Framer Motion · React Query  
**Backend:** FastAPI · asyncpg · Supabase PostgreSQL  
**Design tokens:** `--turquoise` (primary) · `--gold` (accent) · `--bg-void` (background)  
**Components:** `GlassCard` · `ActionButton` · `StatusPill`

---

## Section 2: Implementation Inventory

### Auth & Access

| Feature | Status | Evidence |
|---------|--------|----------|
| Email/password login + JWT | ✅ DONE (verified) | `backend/routes/auth.py` · PRD2 |
| Tenant isolation (all UPDATE/SELECT) | ✅ DONE (verified) | commit 1d0bb9c · PRD3 |
| Password reset (token + email + page) | ✅ DONE (unverified) | `backend/migrations/` · `app/reset-password/` |
| Google OAuth | ✅ DONE (unverified) | `backend/routes/google_auth.py` |
| API key CRUD + validate endpoint | ✅ DONE (verified) | `backend/routes/settings.py` · fix 4057fb1 · PRD2 |
| Dev token disabled in production | ✅ DONE (unverified) | `backend/routes/auth.py` |

### Billing & Plans

| Feature | Status | Evidence |
|---------|--------|----------|
| Billing page (`/billing`) | ✅ DONE (verified) | `frontend/src/app/billing/` · PRD1 |
| Pricing page (`/pricing`) | ✅ DONE (verified) | `frontend/src/app/pricing/` · PRD1 |
| Stripe checkout + portal | ✅ DONE (unverified) | `backend/routes/billing.py` |
| Plan enforcement middleware | ✅ DONE (unverified) | `backend/routes/billing.py` |
| 14-day Creator trial on signup | ✅ DONE (verified) | `migrations/029_*.sql` · PRD2-T1 |
| Trial countdown badge + banner | ✅ DONE (verified) | `frontend/src/components/` · PRD2 |
| Trial warning email (3-day) | ✅ DONE (verified) | `backend/email_tasks.py` · PRD2-T7 |
| Billing receipt email | ✅ DONE (verified) | `backend/routes/billing.py` · PRD2-T6 |
| Render minutes tracking | ✅ DONE (unverified) | `backend/routes/videos.py` |
| Notification preferences | ✅ DONE (verified) | `migrations/031_notification_prefs.sql` · PRD4-T3 |

### Core Pipeline & UI

| Feature | Status | Evidence |
|---------|--------|----------|
| Pipeline page with stage tabs | ✅ DONE (verified) | `frontend/src/app/pipeline/` · PRD2 |
| SSE real-time stage progress | ✅ DONE (verified) | `backend/routes/pipeline.py` · `frontend/src/hooks/` · PRD2-T2 |
| System prompt editors (per stage) | ✅ DONE (unverified) | `frontend/src/app/system-prompts/` |
| Video preview player (RenderTab) | ✅ DONE (verified) | `frontend/src/components/video-detail/` · PRD4-T8 |
| Create video: suggest-titles endpoint | ✅ DONE (unverified) | `backend/routes/videos.py` |
| Export manifest endpoint | ✅ DONE (verified) | `backend/routes/videos.py` · PRD4-T5 |
| Export button + Brand Kit UI | ✅ DONE (verified) | `frontend/src/app/` · PRD4-T12 |
| Storyboard viewer | ✅ DONE (unverified) | `frontend/src/app/storyboard/` |
| Visuals/assets viewer | ✅ DONE (unverified) | `frontend/src/app/visuals/` |
| Review/approval flow | ✅ DONE (unverified) | `frontend/src/app/review/` |

### Discovery & Competitors

| Feature | Status | Evidence |
|---------|--------|----------|
| Discovery page (ideas + trending) | ✅ DONE (unverified) | `app/discovery/` · `backend/routes/discovery.py` |
| Competitors page (paginate/filter/sort) | ✅ DONE (unverified) | `frontend/src/app/competitors/` |
| Niche + channel profile management | ✅ DONE (unverified) | `backend/routes/niche.py` · `routes/channel_profile.py` |

### Analytics & Learning

| Feature | Status | Evidence |
|---------|--------|----------|
| Analytics 2.0 (topic chart + competitor card) | ✅ DONE (verified) | `frontend/src/app/analytics/` · PRD4-T7 |
| Topic performance endpoint | ✅ DONE (verified) | `backend/routes/analytics.py` · PRD4-T1 |
| Competitor benchmark endpoint | ✅ DONE (verified) | `backend/routes/analytics.py` · PRD4-T1 |
| Learning Insights dashboard redesign | ✅ DONE (verified) | `frontend/src/app/learnings/` · PRD4-T6 |
| Autopilot dashboard | ✅ DONE (unverified) | `app/autopilot/` · `backend/routes/autopilot.py` |
| Calendar view | ✅ DONE (unverified) | `frontend/src/app/calendar/` |

### Marketing & Legal

| Feature | Status | Evidence |
|---------|--------|----------|
| Landing page (`/`) | ✅ DONE (verified) | `frontend/src/app/page.tsx` · PRD2 |
| Getting Started guide (`/docs`) | ✅ DONE (verified) | `frontend/src/app/docs/` · PRD4-T9 |
| Terms of Service (`/terms`) | ✅ DONE (verified) | `frontend/src/app/terms/` · PRD4-T10 |
| Privacy Policy (`/privacy`) | ✅ DONE (verified) | `frontend/src/app/privacy/` · PRD4-T10 |
| Demo mode backend (3 no-auth endpoints) | ✅ DONE (verified) | `backend/routes/demo.py` · PRD4-T4 |
| Demo mode frontend (landing + 3 sub-pages) | ✅ DONE (verified) | `frontend/src/app/demo/` · PRD4-T11 |
| Brand Kit backend (channel_profile extensions) | ✅ DONE (verified) | `backend/migrations/` · PRD4-T2 |

### Infrastructure

| Feature | Status | Evidence |
|---------|--------|----------|
| Rate limiting (per-tenant) | ✅ DONE (unverified) | `backend/main.py` · PRD3 |
| Redis job queue (arq) + retry | ✅ DONE (unverified) | PRD3 |
| Per-tenant Supabase Storage | ✅ DONE (unverified) | PRD3 |
| Sentry error monitoring (BE + FE) | ✅ DONE (unverified) | PRD3 |
| CORS lockdown | ✅ DONE (unverified) | `backend/main.py` · PRD3 |
| Email service module (Resend) | ✅ DONE (verified) | `backend/email_service.py` · PRD2-T5 |

### Polish & Launch

| Feature | Status | Evidence |
|---------|--------|----------|
| Toast notification system | ✅ DONE (unverified) | `frontend/src/components/ui/` |
| Error boundaries + 404 page | ✅ DONE (unverified) | `frontend/src/app/` |
| Empty states (top 8 pages) | ✅ DONE (unverified) | `frontend/src/app/` |
| Beta regression sweep | ✅ DONE (verified) | commit 33d5624 · PRD4-T13 |
| Security audit (6 findings) | ✅ DONE (verified) | commit c535c38 · PRD4-T14 |
| Performance readiness check | ✅ DONE (verified) | commit a6b8be7 · PRD4-T15 |
| SEC-SSE-001: cross-tenant SSE isolation | 🔵 ACTIVE | `backend/routes/pipeline.py` — bug queue |
| SEC-EMAIL-001: HTML injection in emails | 🔵 ACTIVE | `backend/email_service.py` — bug queue |
| SEC-KEYS-001: exception leak on key validate | 🔵 ACTIVE | `backend/routes/settings.py` — bug queue |

---

## Section 3: Roadmap Progress

| Day | Date | Focus | Status | PRD |
|-----|------|-------|--------|-----|
| 1 | 2026-04-07 | Billing UI | ✅ Done | PRD1 |
| 2 | 2026-04-08 | Plan Enforcement | ✅ Done | PRD1 |
| 3 | 2026-04-08 | Trial + Password Reset | ✅ Done | PRD2 |
| 4 | 2026-04-08 | Fix Broken Endpoints + Empty States | ✅ Done | PRD1 |
| 5 | 2026-04-08 | Create Video Simplification | ✅ Done | PRD1 |
| 6 | 2026-04-09 | Pipeline Progress UX (SSE) | ✅ Done | PRD2 |
| 7 | 2026-04-08 | Error Handling + Toasts | ✅ Done | PRD2 |
| 8 | 2026-04-08 | Landing Page | ✅ Done | PRD2 |
| 9 | 2026-04-09 | Transactional Email | ✅ Done | PRD2 |
| 10 | 2026-04-09 | Dashboard Redesign | ✅ Done | PRD2 |
| 11–12 | 2026-04-09 | Job Queue + Rate Limiting | ✅ Done | PRD3 |
| 13 | 2026-04-09 | Per-tenant Storage | ✅ Done | PRD3 |
| 14 | 2026-04-09 | Error Monitoring (Sentry) | ✅ Done | PRD3 |
| 15 | 2026-04-09 | Security Hardening | ✅ Done | PRD3 |
| 16 | 2026-04-10 | Learning Insights Dashboard | ✅ Done | PRD4-T6 |
| 17 | 2026-04-10 | Analytics 2.0 | ✅ Done | PRD4-T7 |
| 18 | 2026-04-10 | Video Preview + Brand Kit + Demo + Docs + Legal | ✅ Done | PRD4-T8–T12 |
| — | 2026-04-10 | Beta Regression + Security + Perf Audit | ✅ Done | PRD4-T13–T15 |

---

## Section 4: Current Priority Gap Queue

### Tier 1 — ACTIVE (open bugs, block beta launch)
- **SEC-SSE-001** — `backend/routes/pipeline.py`: verify `video.tenant_id == auth.tenant_id` before streaming
- **SEC-EMAIL-001** — `backend/email_service.py`: sanitize user-controlled fields before HTML rendering
- **SEC-KEYS-001** — `backend/routes/settings.py` `POST /keys/validate`: catch and redact internal exceptions

### Tier 2 — NEXT PRD (post-bug-fix)
- Storyboard Extraction V2: wire `extraction.py` into `pipeline_executor.py` for Supabase videos; grid is 3×2; test video f9749bd2
- Permanent asset storage: Supabase Storage for all image-gen output (T27-004/005/008 from blocked queue)
- Onboarding flow: guided first-login walkthrough — page stub at `/onboarding` exists, needs wiring
- YouTube publish: direct upload from StoryEngine UI via stored OAuth (currently CLI-only)
- Autopilot Settings UI: expose `autopilot_program.md` weights (cadence, thresholds) in Settings page

### Tier 3 — WEEK 4 (polish)
- Mobile layout audit: pipeline tabs + dashboard at 375px viewport
- Notification preferences UI wired to `PATCH /api/preferences/notifications` (migration 031 exists)
- Profile page: avatar upload, timezone selector, channel URL field

### Tier 4 — POST-BETA
- Team seats + multi-user tenants
- White-label domain support (Studio tier)
- A/B title testing dashboard wired to `title_tests` table
- Public API documentation
- Zapier/Make integration for pipeline triggers

---

## Section 5: PRD Writing Guidelines

### Task Structure
Every task needs: **role** (`backend-dev` | `frontend-dev` | `qa-engineer` | `security`), **size** (S < 2h · M 2–4h · L 4–8h), **one concern** — never mix backend + frontend in the same task.

### File Path Conventions

| Layer | Path |
|-------|------|
| Backend route | `storyengine/backend/routes/{name}.py` |
| Pydantic model | `storyengine/backend/models.py` (append) |
| Route registration | `storyengine/backend/main.py` (`app.include_router(...)`) |
| DB migration | `storyengine/backend/migrations/0NN_{name}.sql` |
| Frontend page | `storyengine/frontend/src/app/{route}/page.tsx` |
| Frontend component | `storyengine/frontend/src/components/{category}/` |
| API helper | `storyengine/frontend/src/lib/api.ts` (append) |
| TypeScript types | `storyengine/frontend/src/lib/types.ts` (append) |

### Acceptance Criteria Patterns

```bash
curl -s http://localhost:8001/api/{endpoint} | jq '.key'          # route responds
psql $DATABASE_URL -c "\d {table}" | grep {column}               # column exists
grep -n "{router_name}" storyengine/backend/main.py              # route registered
cd storyengine/frontend && npx tsc --noEmit                       # 0 type errors
test -f storyengine/backend/migrations/0NN_{name}.sql            # migration committed
```

### Wiring Checklist (all 8 required before marking done)

1. DB column exists in Supabase (not just schema.sql)
2. Backend route registered in `main.py`
3. Pydantic model in `models.py` matches route response shape exactly
4. Frontend `api.ts` calls the correct endpoint path
5. TypeScript types match backend field names exactly (copy, don't retype)
6. Component wired to real API data — no mock/hardcoded values
7. Loading + error + empty states all render
8. `npx tsc --noEmit` passes with 0 errors

### Design System (mandatory for all UI tasks)

Use design tokens: `var(--turquoise)`, `var(--gold)`, `var(--bg-void)`. Use `GlassCard` for content containers, `ActionButton` for primary CTAs, `StatusPill` for pipeline states. Dark theme only — no white backgrounds. Invoke `web-design-guidelines` skill before submitting any UI task.

### What NOT to Spec (already built — do not re-implement)

Email/password login, JWT auth, Google OAuth, tenant isolation, API key CRUD, API key validation, billing page, pricing page, Stripe checkout, plan enforcement middleware, 14-day trial logic, trial countdown badge, trial warning email, billing receipt email, render minutes tracking, notification preferences backend, pipeline page with tabs, SSE stage streaming, system prompt editors, video preview player, suggest-titles endpoint, export manifest endpoint, export button, brand kit UI, storyboard viewer, visuals viewer, review/approval flow, discovery page, competitors page, niche management, channel profile management, analytics 2.0, topic performance endpoint, competitor benchmark endpoint, learning insights dashboard, autopilot dashboard, calendar view, landing page, docs/help page, terms of service, privacy policy, demo mode backend, demo mode frontend, brand kit backend migration, rate limiting, Redis job queue, per-tenant Supabase storage, Sentry integration, CORS lockdown, email service module, toast notification system, error boundaries, 404 page, empty states, password reset flow, dev-token production disable, beta regression sweep, security audit, performance readiness check.
