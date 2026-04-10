# StoryEngine Product Brain
_Last refreshed: 2026-04-09 20:28 (auto-generated)_

---

## Section 1: Product Identity

StoryEngine is an AI-powered YouTube video production SaaS that takes a topic and outputs a publish-ready video — script, voiceover, images, captions, and thumbnail — with a single click. Built for solo creators and small teams who want data-driven content without a production team. Moat: an autopilot intelligence layer that learns from CTR/VPH data and improves future videos automatically.

| Tier | Price | Videos/mo | Key Differentiator |
|------|-------|-----------|-------------------|
| Starter | Free | 2 | Try the full pipeline, limited analytics |
| Creator | $29/mo | 8 | Full pipeline + autopilot + 14-day trial |
| Studio | $99/mo | 25 | Priority render, brand kit, API access |

**7 UX Principles:**
1. **Action-first** — every page answers "what do I do next?"
2. **3-click creation** — topic → title pick → pipeline starts
3. **Visible progress** — real-time SSE stage tracker, no black boxes
4. **AI insights surface** — learnings, patterns, and CTR data visible to users
5. **Empty states sell** — every empty state has a CTA that starts a video
6. **Errors are helpful** — toasts with actionable next steps, never raw stack traces
7. **Mobile-aware** — responsive layouts, touch-friendly controls

**Stack:** Next.js 16 + React 19 + TypeScript | FastAPI + asyncpg | Supabase PostgreSQL
**Design tokens:** `--turquoise`, `--gold`, `--bg-void` | Components: `GlassCard`, `ActionButton`, `StatusPill`

---

## Section 2: Implementation Inventory

### Auth & Access

| Feature | Status | Evidence |
|---------|--------|----------|
| Email/password login | ✅ DONE (unverified) | `frontend/src/app/login` |
| Google OAuth | ✅ DONE (unverified) | `backend/routes/google_auth.py` |
| Password reset (token + email + page) | ✅ DONE (unverified) | `frontend/src/app/forgot-password`, `password_reset_tokens` table |
| Onboarding flow | ✅ DONE (unverified) | `frontend/src/app/onboarding` |
| Multi-tenancy + tenant isolation | ✅ DONE (unverified) | `tenants`, `memberships` tables |

### Billing & Plans

| Feature | Status | Evidence |
|---------|--------|----------|
| Billing page (plan + usage + upgrade) | ✅ DONE (unverified) | `frontend/src/app/billing` |
| Pricing page (3 tiers, feature grid) | ✅ DONE (unverified) | `frontend/src/app/pricing` |
| Stripe integration | ✅ DONE (unverified) | `backend/routes/billing.py` |
| Notification preferences (backend + migration) | ✅ DONE (unverified) | PRD4-T3, `migrations/031_notification_prefs.sql` |
| Trial countdown badge + banner | ✅ DONE (unverified) | Shipped 2026-04-08 |
| Brand Kit backend (migration + channel_profile) | ✅ DONE (unverified) | PRD4-T2 |
| Plan enforcement middleware (`check_plan_limits`) | ❌ MISSING | Roadmap Day 2 — `tenant_usage` table exists, no middleware |
| Free trial logic (14-day, downgrade-on-expiry) | ❌ MISSING | Roadmap Day 3 — no trial lifecycle wired |
| Export button + Brand Kit UI + Notification toggles | 🔵 ACTIVE | PRD4-T12 |

### Core Pipeline & UI

| Feature | Status | Evidence |
|---------|--------|----------|
| Dashboard | ✅ DONE (unverified) | `frontend/src/app/dashboard`, `backend/routes/dashboard.py` |
| Pipeline page + stage tabs | ✅ DONE (unverified) | `frontend/src/app/pipeline` |
| Video creation flow | ✅ DONE (unverified) | `backend/routes/videos.py` |
| AI title suggestions endpoint | ✅ DONE (unverified) | `POST /api/videos/suggest-titles` — backend built |
| Storyboard viewer | ✅ DONE (unverified) | `frontend/src/app/storyboard` |
| Video preview player (Render tab) | ✅ DONE (unverified) | PRD4-T8 |
| System prompt editors (pipeline tabs) | ✅ DONE (unverified) | `frontend/src/app/system-prompts` |
| Export manifest endpoint | ✅ DONE (unverified) | PRD4-T5 — `GET /api/videos/{id}/export-manifest` |
| Toast notification system | ✅ DONE (unverified) | Shipped — replaced 81 `alert()` calls |
| Error boundaries + 404 page | ✅ DONE (unverified) | Shipped 2026-04-08 |

### Discovery & Competitors

| Feature | Status | Evidence |
|---------|--------|----------|
| Idea discovery page | ✅ DONE (unverified) | `frontend/src/app/discovery`, `backend/routes/discovery.py` |
| Competitors page (paginated, filtered, sortable) | ✅ DONE (unverified) | Refactored 2026-04-08 — server-side pagination |
| Competitor channel management | ✅ DONE (unverified) | `competitor_channels`, `competitor_videos` tables |

### Analytics & Learning

| Feature | Status | Evidence |
|---------|--------|----------|
| Analytics backend (topic-performance + competitor-benchmark) | ✅ DONE (unverified) | PRD4-T1 — `backend/routes/analytics.py` |
| Analytics 2.0 frontend (topic chart + competitor card) | ✅ DONE (unverified) | PRD4-T7 — `frontend/src/app/analytics` |
| Learning Insights dashboard redesign | ✅ DONE (unverified) | PRD4-T6 — `frontend/src/app/learnings` |
| Autopilot config + controls | ✅ DONE (unverified) | `frontend/src/app/autopilot`, `autopilot_config` table |
| YouTube performance sync | ✅ DONE (unverified) | `backend/routes/youtube_sync.py` |

### Marketing & Legal

| Feature | Status | Evidence |
|---------|--------|----------|
| Getting Started / help page | ✅ DONE (unverified) | PRD4-T9 — `frontend/src/app/docs` |
| Terms of Service | ✅ DONE (unverified) | PRD4-T10 — `frontend/src/app/terms` |
| Privacy Policy | ✅ DONE (unverified) | PRD4-T10 — `frontend/src/app/privacy` |
| Landing page (marketing, hero, pricing embed) | ✅ DONE (unverified) | Shipped — public root route |
| Demo mode backend (3 static endpoints, no auth) | ✅ DONE (unverified) | PRD4-T4 — `backend/routes/demo.py` |
| Demo mode frontend (landing + 3 sub-pages) | 🔵 ACTIVE | PRD4-T11 — `frontend/src/app/demo` |

### Infrastructure

| Feature | Status | Evidence |
|---------|--------|----------|
| SSE pipeline stage events | ✅ DONE (unverified) | PRD2 complete — `stage_transitions` table |
| Background task orchestrator | ✅ DONE (unverified) | `backend/pipeline_executor.py` |
| Job queue (Redis + arq, persistent) | ❌ MISSING | Roadmap Day 11-12 — not started |
| Per-tenant Supabase Storage + signed URLs | ❌ MISSING | Roadmap Day 13 — not started |
| Per-tenant rate limiting | ❌ MISSING | Roadmap Day 12 — not started |
| Sentry error monitoring (backend + frontend) | ❌ MISSING | Roadmap Day 14 — not started |
| Security hardening (OWASP audit) | 🔵 ACTIVE | PRD4-T14 — pending |

### Polish & Launch

| Feature | Status | Evidence |
|---------|--------|----------|
| Beta launch regression sweep | 🔵 ACTIVE | PRD4-T13 — pending |
| Performance & load readiness check | 🔵 ACTIVE | PRD4-T15 — pending |

---

## Section 3: Roadmap Progress

| Day | Date | Focus | Status | PRD Reference |
|-----|------|-------|--------|---------------|
| 1 | 2026-04-07 | Billing UI | ✅ Done | PRD1 |
| 2 | 2026-04-08 | Plan Enforcement | ❌ Skipped | Roadmap — unstarted |
| 3 | 2026-04-08 | Trial + Password Reset | ⚠️ Partial | Pages exist; trial lifecycle missing |
| 4 | 2026-04-08 | Empty States + Fix Endpoints | ✅ Done | PRD1 |
| 5 | 2026-04-08 | Create Video Simplification | ⚠️ Partial | Backend done; frontend not wired |
| 6 | 2026-04-08 | Pipeline Progress UX (SSE) | ✅ Done | PRD2 |
| 7 | 2026-04-08 | Error Handling + Toasts | ✅ Done | Critical Bug Fixes PRD |
| 8 | 2026-04-08 | Landing Page | ✅ Done | Shipped |
| 9 | 2026-04-08 | Transactional Email | ⚠️ Partial | `email_service.py` built; not fully wired |
| 10 | 2026-04-08 | Dashboard Redesign | ✅ Done | PRD1 |
| 11 | — | Job Queue (Redis/arq) | ❌ Not started | Roadmap |
| 12 | — | Job Queue + Rate Limiting | ❌ Not started | Roadmap |
| 13 | — | Per-tenant Storage | ❌ Not started | Roadmap |
| 14 | — | Error Monitoring (Sentry) | ❌ Not started | Roadmap |
| 15 | — | Security Hardening | 🔵 Active | PRD4-T14 |
| 16 | — | Learning Insights | ✅ Done early | PRD4-T6 |
| 17 | — | Analytics 2.0 | ✅ Done early | PRD4-T7 |
| 18 | — | Video Preview + Brand Kit | ⚠️ Partial | T8 done; T12 pending |

---

## Section 4: Current Priority Gap Queue

**Tier 1 — ACTIVE (PRD4 remaining tasks)**
- `PRD4-T11`: Demo mode frontend — `/demo` landing + pipeline demo, analytics demo, autopilot demo sub-pages
- `PRD4-T12`: Export button + Brand Kit UI + Notification preference toggles (frontend)
- `PRD4-T13`: Beta regression — 24 pages + 33 API endpoints + 9 pipeline tabs sweep
- `PRD4-T14`: Security audit — auth flows, tenant isolation, secrets, OWASP top 10
- `PRD4-T15`: Performance & load readiness check

**Tier 2 — NEXT PRD (specific unbuilt roadmap items)**
- Plan enforcement: `check_plan_limits()` in `backend/auth.py`; increment `tenant_usage` on video create/render; return 403 with upgrade prompt when limit hit
- Free trial lifecycle: set `trial_expires_at = NOW() + 14 days` on signup; cron to flip plan to `starter` on expiry; frontend countdown banner
- Job queue: Redis + arq worker; pipeline stages as persistent jobs with retry + dead-letter; survives server restart
- Rate limiting: `slowapi` per-tenant limits on `POST /api/pipeline/*` and `POST /api/videos/*`
- Suggest-titles frontend: wire `POST /api/videos/suggest-titles` into create video flow (3-title picker UI)

**Tier 3 — WEEK 4 (polish before GA)**
- Per-tenant Supabase Storage with signed URLs (isolate assets per tenant)
- Sentry integration (`sentry_sdk` backend + `@sentry/nextjs` frontend, tenant_id context)
- Mobile responsive pass on pipeline + dashboard
- Onboarding checklist (first-video guided flow with progress steps)
- Transactional email completion (welcome, trial warning, billing receipts via Resend)

**Tier 4 — POST-BETA**
- API access tier (Studio plan — programmatic video creation)
- Zapier/webhook integrations for pipeline events
- Team collaboration (shared workspace, role-based access)
- Storyboard extraction V2 (Supabase Storage for all image gen steps)
- Calendar-based publish scheduling

---

## Section 5: PRD Writing Guidelines

### Task Structure
- **Role**: `backend` | `frontend` | `qa` | `security` | `devops`
- **Sizing**: S (< 2h), M (2–4h), L (4–8h) — break anything larger into multiple tasks
- **One concern per task**: never mix DB migration + route + UI in a single task
- **Naming**: `T{N}: {What} — {where} ({role})`

### File Path Conventions
```
backend route:  storyengine/backend/routes/{name}.py
pydantic models: storyengine/backend/models.py
router registry: storyengine/backend/main.py
migration:       storyengine/backend/migrations/{NNN}_{name}.sql
frontend page:   storyengine/frontend/src/app/{page}/page.tsx
component:       storyengine/frontend/src/components/{category}/{Name}.tsx
api layer:       storyengine/frontend/src/lib/api.ts
types:           storyengine/frontend/src/lib/types.ts
```

### Acceptance Criteria Patterns
```bash
curl http://localhost:8001/api/{endpoint}              # route exists + returns correct shape
psql $DATABASE_URL -c "SELECT {col} FROM {table}"     # column exists in DB (not just schema.sql)
cd storyengine/frontend && npx tsc --noEmit            # TypeScript compiles clean
grep -r "include_router" storyengine/backend/main.py  # router registered
test -f storyengine/backend/migrations/{NNN}*.sql     # migration file on disk
```

### Wiring Checklist (8 items — every feature, no exceptions)
1. DB column exists — actually migrated, not just in `schema.sql`
2. Backend route registered in `main.py` via `app.include_router()`
3. Pydantic model in `models.py` matches route response shape exactly
4. Frontend `fetchApi` call uses correct endpoint path — curl test first, then copy
5. TypeScript types in `types.ts` match backend field names exactly (copy, don't retype)
6. Component wired to real API data — no hardcoded/mock values in JSX
7. Loading + error + empty states all render correctly
8. `npx tsc --noEmit` passes with zero errors

### Design System (mandatory for all UI tasks)
- Invoke `web-design-system` skill BEFORE writing any UI code — no exceptions
- Tokens: `--turquoise` (primary), `--gold` (accent), `--bg-void` (dark background)
- Components: `GlassCard` (all cards), `ActionButton` (CTAs), `StatusPill` (status badges)
- TailwindCSS 4 utility classes — no inline styles, no arbitrary values without token
- Dark theme by default — light theme is not supported

### What NOT to Spec (already ✅ DONE — guard rail)
Do not write PRD tasks for any of the following — they are already implemented:

- Login / signup / Google OAuth
- Password reset flow (forgot-password page, token table, reset-password page)
- Onboarding page
- Dashboard page
- Billing page + Pricing page + Stripe integration
- Notification preferences backend + migration (031)
- Trial countdown badge + banner
- Brand Kit backend (channel_profile migration)
- Pipeline page + stage tabs
- Storyboard viewer
- Video preview player on Render tab
- System prompt editors
- Toast notification system (all 81 alert() calls replaced)
- Error boundaries + 404 page
- Competitors page (server-side pagination, filters, sort)
- Discovery page
- Analytics backend (topic-performance, competitor-benchmark endpoints)
- Analytics 2.0 frontend (topic chart, competitor card)
- Learning Insights dashboard
- Autopilot controls + config
- YouTube performance sync
- Getting Started / help page (`/docs`)
- Terms of Service (`/terms`) + Privacy Policy (`/privacy`)
- Landing page (public marketing root)
- Demo mode backend (3 static endpoints, no auth required)
- SSE pipeline stage events
- Background task orchestrator (`pipeline_executor.py`)
- Export manifest endpoint (`GET /api/videos/{id}/export-manifest`)
- AI title suggestions endpoint (`POST /api/videos/suggest-titles`)
