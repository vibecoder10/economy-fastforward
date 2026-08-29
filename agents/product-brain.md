# StoryEngine Product Brain

_Last refreshed: 2026-07-21 12:05 (auto-generated)_

---

## Section 1: Product Identity

StoryEngine is a multi-tenant AI video SaaS: a creator types a topic (or points at a reference video), and the pipeline runs research → script → voice → cast/environment design → storyboards → coverage images → sound → clips → thumbnail → render → YouTube upload end to end. The moat is the learning loop — per-channel patterns (CTR, title structure, thumbnail style) feed autopilot so quality compounds instead of resetting every video, and an MCP server exposes the same production surface to Claude so a creator (or their agent) can direct a channel conversationally.

**Pricing (ratified 2026-07-20, `tasks/decisions.md`):**
| Tier | Price | Videos/mo | Key differentiator |
|------|-------|-----------|---------------------|
| Starter | $29/mo | 12, capped at 10 min length | 1 channel workspace, core pipeline |
| Pro | $79/mo | Unlimited (fair-use) | Channel DNA, MCP access, autopilot dial, unlimited uploads |
| Agency | $199/mo | Unlimited (fair-use) | Full-auto autopilot, multi-channel ($49/mo/extra workspace — no Stripe object yet), MCP access |

Annual (~20% off: $24/$64/$159) is display-only on `/pricing` — no annual Stripe price object exists yet, checkout is monthly-only.

**7 UX principles:** action-first (every screen answers "what's next"), 3-click video creation, visible pipeline progress (SSE, not polling-and-hope), AI insights surface (learnings/patterns shown, not buried), empty states sell (never a blank page), errors are helpful (named cause + next step, never a raw 500), mobile-aware layouts.

**Stack:** Next.js 16 + React 19 + TypeScript + TailwindCSS 4 + Framer Motion (frontend) · FastAPI + asyncpg + Supabase PostgreSQL + arq/Redis queue (backend). Design tokens: `--turquoise` (#00D4AA), `--gold`, `--bg-void` (#0A0A0B); components `GlassCard`, `ActionButton`, `StatusPill`.

---

## Section 2: Implementation Inventory

**Status legend:** ✅ verified (task marked `verified`, or belongs to a `complete` PRD) · ✅ unverified (built via non-PRD engineering loop — no PRD record) · 🔵 ACTIVE (in current PRD4, done or pending, not yet verified) · ❌ MISSING (roadmap item, no PRD, no code) · 📋 PLANNED

### Auth & Access
| Feature | Status | Evidence |
|---------|--------|----------|
| Email/password + Google OAuth + password reset, JWT sessions | ✅ DONE (verified) | PRD1, `routes/google_auth.py`, `routes/settings.py` |
| Onboarding wizard | ✅ DONE (verified) | PRD1, `frontend/src/app/onboarding/` |
| Multi-tenant isolation (tenant_id + RLS) | ✅ DONE (verified) | PRD3, `tenants`/`memberships` tables |
| MCP agent tokens (tenant-scoped, plan-gated) | ✅ DONE (unverified) | C57/C62, `agent_tokens` table, `routes/agent_access.py` |
| Workspace-as-channel model (1 workspace = 1 channel) | ✅ DONE (unverified) | C61b, `get_workspace_info` MCP tool |

### Billing & Plans
| Feature | Status | Evidence |
|---------|--------|----------|
| Stripe checkout + webhooks + portal | ✅ DONE (verified) | PRD1, `routes/billing.py` |
| `/billing` + `/pricing` pages, ratified ladder copy | ✅ DONE (unverified) | C63, `frontend/src/app/pricing/` |
| Plan enforcement (video count + length cap) | ✅ DONE (verified) | PRD1/C62, `routes/billing.py::enforce_video_length_cap` |
| MCP tier gate + good-standing gate (lapsed Stripe kills token same-day) | ✅ DONE (unverified) | C57, `agent_tokens.authenticate_with_standing` |
| Feature board (suggest/vote/status ladder) | ✅ DONE (unverified) | C65, `routes/feature_board.py`, `/ideas` |
| Extra-channel seat Stripe price object | ❌ MISSING | no Stripe object yet (decisions.md 2026-07-20) |

### Core Pipeline & UI
| Feature | Status | Evidence |
|---------|--------|----------|
| Full pipeline (research→render→upload), arq queue | ✅ DONE (verified) | PRD3, `backend/pipeline_executor.py`, `backend/worker.py` |
| Chat-primary create surface (converged, 1 INSERT path) | ✅ DONE (unverified) | C38, `routes/videos.py::create_video` |
| Per-stage resumability (skip-if-done: voice/sound/clips/images/thumbnail/upload) | ✅ DONE (unverified) | C16b/C16d/C16e, `docs/failure-modes.md` |
| Generation claims (no double-dispatch races) | ✅ DONE (unverified) | C16a, `generation_claims` table |
| Model routing (per-scene, channel-style-aware) | ✅ DONE (unverified) | C13/C13b/C14, `shared/model_router.py` |
| Draft-pass / finalize trust ladder | ✅ DONE (unverified) | C17/C18, `generation_passes` table |
| Style presets (5 image-engine profiles) + gallery + chat door | ✅ DONE (unverified) | C20/C21a/C21b, `style_presets` table |
| Camera-preset chips (12 curated moves) | ✅ DONE (unverified) | C23, `routes/camera_presets.py` |
| MCP process brain (canonical stage order + gap detection) + media tools | ✅ DONE (unverified) | C66/C48, `production_guide.py`, `routes/mcp.py` |
| Video preview player (RenderTab) | 🔵 ACTIVE (PRD4-T8) | `frontend/src/components/production/RenderTab.tsx` |

### Discovery & Competitors
| Feature | Status | Evidence |
|---------|--------|----------|
| Discovery + autopilot + calendar pages | ✅ DONE (verified) | PRD2, `frontend/src/app/discovery/`, `/autopilot`, `/calendar` |
| Competitor scraper + channel patterns | ✅ DONE (unverified) | `routes/channel_patterns.py`, `competitor_videos` table |
| Early-warning launch classifier (per-channel CTR outlier) | ✅ DONE (unverified) | C58, `early_warning.py` |
| Reference-video modeling (Model A Video, title gap engine) | ✅ DONE (unverified) | C38/C59, `title_idea/curiosity_gap/` |

### Analytics & Learning
| Feature | Status | Evidence |
|---------|--------|----------|
| Analytics backend (topic-perf + competitor-benchmark endpoints) | 🔵 ACTIVE (PRD4-T1) | `routes/analytics.py` |
| Learning Insights dashboard redesign | 🔵 ACTIVE (PRD4-T6) | `frontend/src/app/learnings/page.tsx` |
| Analytics 2.0 frontend (topic chart + competitor card) | 🔵 ACTIVE (PRD4-T7) | `frontend/src/app/analytics/` |
| Channel DNA + patterns | ✅ DONE (unverified) | `routes/channel_dna.py`, `channel_patterns` table |

### Marketing & Legal
| Feature | Status | Evidence |
|---------|--------|----------|
| Landing page | ✅ DONE (verified) | PRD2, `frontend/src/app/page.tsx` |
| Transactional email (Resend: welcome/reset/trial/receipts) | ✅ DONE (verified) | PRD2 |
| Legal pages (Terms + Privacy) | 🔵 ACTIVE (PRD4-T10) | `frontend/src/app/terms/`, `/privacy` |
| Getting Started / help docs | 🔵 ACTIVE (PRD4-T9) | `frontend/src/app/docs/` |
| Demo mode (backend done, frontend pending) | 🔵 ACTIVE (PRD4-T4 done / T11 pending) | `routes/demo.py`, `frontend/src/app/demo/` |

### Infrastructure
| Feature | Status | Evidence |
|---------|--------|----------|
| arq/Redis job queue (persistent stages, retry) | ✅ DONE (verified) | PRD3, `backend/worker.py`, `infra/setup_worker.sh` |
| Rate limiting + security hardening (CORS, CSRF, auth limits) | ✅ DONE (verified) | PRD3, `rate_limit.py` |
| Ledger uniqueness backstop (no duplicate spend) | ✅ DONE (unverified) | C16c, `generation_ledger_dedup_idx` |
| Export manifest backend | 🔵 ACTIVE (PRD4-T5) | `GET /api/videos/{id}/export-manifest` |
| Brand Kit + notification preferences backend | 🔵 ACTIVE (PRD4-T2, T3) | `routes/channel_profile.py`, `routes/preferences.py` |
| Per-tenant object storage (Supabase Storage, signed URLs) | ❌ MISSING | assets still resolved via Kie/Drive + signed proxy (C25a), not migrated |
| Error monitoring (Sentry) | ❌ MISSING | console/log only |

### Polish & Launch
| Feature | Status | Evidence |
|---------|--------|----------|
| Export button + Brand Kit UI + notification toggles | 🔵 ACTIVE (PRD4-T12, pending) | not yet in `frontend/src/app/settings/` |
| Beta launch regression sweep | 🔵 ACTIVE (PRD4-T13, pending) | not started |
| Security audit (auth, tenant isolation, secrets) | 🔵 ACTIVE (PRD4-T14, pending) | not started |
| Performance & load readiness check | 🔵 ACTIVE (PRD4-T15, pending) | not started |
| Dashboard redesign (action-first cards) | ❌ MISSING | roadmap Day 10, not in any PRD |
| Invite-a-manager flow | ❌ MISSING | traced C61b, not built — seeded on feature board |

---

## Section 3: Roadmap Progress

| Day | Date | Focus | Status | PRD Reference |
|-----|------|-------|--------|----------------|
| 1 | 2026-04-08 | Billing UI | ✅ Done | PRD1 |
| 2 | 2026-04-08 | Plan enforcement | ✅ Done | PRD1, C62 |
| 3 | 2026-04-08 | Trial + password reset | ✅ Done | PRD1 |
| 4 | 2026-04-08 | Fix broken endpoints + empty states | ✅ Done | PRD1 |
| 5 | 2026-04-08 | Create video simplification | ✅ Done | PRD1, C38 |
| 6 | 2026-04-08 | Pipeline progress UX (SSE) | ✅ Done | PRD2 |
| 7 | 2026-04-08 | Error handling + toasts | ✅ Done | PRD2 |
| 8 | 2026-04-08 | Landing page | ✅ Done | PRD2 |
| 9 | 2026-04-08 | Transactional email | ✅ Done | PRD2 |
| 10 | — | Dashboard redesign | ❌ Not started | none |
| 11 | 2026-04-08 | Job queue | ✅ Done | PRD3 |
| 12 | 2026-04-08 | Job queue cont. + rate limiting | ✅ Done | PRD3 |
| 13 | — | Per-tenant storage | ❌ Not started | none (PRD3's "Storage" scope was task persistence, not object storage) |
| 14 | — | Error monitoring (Sentry) | ❌ Not started | none |
| 15 | 2026-04-08 | Security hardening | ✅ Done | PRD3 |
| 16 | 2026-04-08→ | Learning Insights dashboard | 🔵 Built, unverified | PRD4-T1, T6 |
| 17 | 2026-04-08→ | Analytics 2.0 | 🔵 Built, unverified | PRD4-T7 |
| 18 | 2026-04-08→ | Video preview + Brand Kit | 🔵 In progress | PRD4-T2, T8, T12 |

_Note: since PRD4 opened (2026-04-08), most engineering effort has run through a parallel, non-PRD-tracked worker loop (the "C-numbered" chunks in `tasks/todo.md`) — MCP surface, model routing, trust ladder, style/camera presets, feature board — rather than advancing PRD4's remaining 5 tasks. That's why PRD4 is still 10/15 done as of 2026-07-21._

---

## Section 4: Current Priority Gap Queue

### Tier 1 — ACTIVE (PRD4, 5 tasks remaining; T1-T10 built, not yet verified)
- T11: Demo mode frontend — landing + 3 sub-pages
- T12: Export button + Brand Kit UI + notification toggles
- T13: Beta launch regression sweep (full page + API)
- T14: Security audit (auth, tenant isolation, secrets)
- T15: Performance & load readiness check

### Tier 2 — NEXT PRD (Week 3/4 gaps not yet in a PRD)
1. **Dashboard redesign** (Day 10) — action-first cards: active videos, pending approvals, quick-start CTA, usage meter.
2. **Per-tenant object storage** (Day 13) — migrate asset URLs off Kie.ai/Drive onto Supabase Storage with signed URLs; today's signed-proxy fix (C25a/C48) covers auth, not storage location.
3. **Error monitoring** (Day 14) — Sentry backend + frontend, tenant_id in every structured log line.
4. **Sheet auto-split on content-filter rejection** — root cause diagnosed 2026-07-20 (OpenAI density scoring on caption-dense sheets); Ryan ruled no nano-fallback, fix the structure instead.
5. **Extra-channel seat Stripe price** — $49/mo object referenced in ratified pricing copy but not created in Stripe yet.

### Tier 3 — Week 4 Polish
- Settings completion (API key validation feedback, integration status indicators)
- `rate_limit.py`'s `_get_tenant_plan` legacy-tenant fallback dedupe (C60 STOP item — needs a live DB check first)
- MCP OAuth wrapper for claude.ai Desktop/phone connectors (bearer-token only today)

### Tier 4 — POST-BETA
- Webhook API (Zapier, Make.com)
- GDPR / data export
- Invite-a-manager flow (traced C61b, not built — also seeded on the feature board)
- Voice clone per channel
- Annual billing (Stripe price objects + toggle — currently display-only)

---

## Section 5: PRD Writing Guidelines

### Task structure
Each task: single role (backend | frontend | qa | security), 15-45 min effort, ONE concern. 8-15 tasks per PRD, dependencies declared explicitly (`depends_on`).

### File conventions
- Backend routes: `storyengine/backend/routes/<name>.py` — must register in `storyengine/backend/main.py`
- Pydantic models: `storyengine/backend/models.py` (source of truth for API shape)
- Migrations: `storyengine/backend/migrations/<NNN>_<name>.sql` + update `storyengine/schema.sql` (latest: `113_storyboard_errors.sql`)
- Frontend pages: `storyengine/frontend/src/app/<page>/page.tsx`
- Frontend components: `storyengine/frontend/src/components/<category>/<Name>.tsx`
- API layer: `storyengine/frontend/src/lib/api.ts`; types: `storyengine/frontend/src/lib/types.ts`

### Acceptance criteria patterns
```bash
curl -s -o /dev/null -w '%{http_code}' http://localhost:8001/api/endpoint | grep -q 200
psql "$DATABASE_URL" -c "SELECT column_name FROM information_schema.columns WHERE table_name='videos'" | grep -q new_column
cd storyengine/frontend && npx tsc --noEmit
test -f storyengine/backend/routes/new_route.py
grep -q "new_route" storyengine/backend/main.py
```

### Wiring checklist (every feature must pass)
1. DB column exists (migrated, not just in schema.sql)
2. Route registered in `main.py`
3. Pydantic model matches route response exactly
4. Frontend `fetchApi` calls the correct endpoint path
5. TypeScript types match backend response field names
6. Component wired to real API data, not mock/hardcoded
7. Loading + error + empty states all handled
8. `npx tsc --noEmit` passes clean

### Design system (mandatory for UI tasks)
Invoke `web-design-system` skill first. Dark background `var(--bg-void)`, `glass-card` class for panels, accents `var(--turquoise)`/`var(--gold)`/`var(--orange)`/`var(--red)`. Components: `GlassCard`, `ActionButton`, `StatusPill`, `Spinner`, `Modal`. Motion: Framer Motion container/item stagger.

### What NOT to spec (already built — guard rail)
Auth (email/password, Google OAuth, password reset, onboarding, MCP agent tokens, workspace-as-channel), billing (Stripe checkout/webhooks/portal, `/billing`+`/pricing` pages, plan enforcement, MCP tier gate, good-standing gate, feature board), full pipeline + arq queue + chat-primary create + per-stage resumability + generation claims + model routing + draft-pass/finalize + style presets + camera-preset chips + director memory + inline chat storyboards/per-scene approve, MCP process brain + media tools + environments tool family, discovery/autopilot/calendar pages, competitor scraper + channel patterns, early-warning classifier, reference-video modeling (Model A Video, title gap engine), Channel DNA, landing page, transactional email, ledger dedup backstop, rate limiting + security hardening.
