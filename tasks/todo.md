# Task Tracking

## Active Work

**Execution Plan:** `tasks/roadmap.md` — 18-day SaaS transformation
**Current:** Day 2 of 18 (2026-04-08). Billing page shipped. Critical Bug Fixes PRD complete (14/14 tasks).
**Agent Team:** 6 agents on Opus, task queue cleared (194/194 done). Ready for next PRD.

### What Shipped Today (2026-04-08)
- Billing page (`/billing`) with plan comparison, usage bars, Stripe integration
- Critical Bug Fixes PRD: all 14 tasks (6 backend, 6 frontend, 1 QA, 1 security)
- Competitors page refactored (server-side pagination, filters, sort, scrape progress)
- Error boundaries + 404 page
- Toast notification system (replaced 81 alert() calls)
- System prompt editors on pipeline tabs
- Trial countdown badge + banner
- REG24 regression sweep: 24/24 pages, 33/33 API, 9/9 tabs — 0 bugs

### Next Up (from roadmap Day 3-5)
- [ ] Plan enforcement: `tenant_usage` table, `check_plan_limits()` middleware, usage hooks
- [ ] Free trial logic: 14-day Creator trial on signup, countdown, downgrade-on-expiry
- [ ] Password reset flow: token table, email (Resend), `/reset-password` page
- [ ] Disable dev-token in production mode
- [ ] Create video simplification: URL/topic → 3 title suggestions → pick → go

---

## Blocked / Pending

### Storyboard Extraction V2 (from 2026-04-04)
- **T27-003**: Rewrite storyboard-extract endpoint for Supabase
  - Wire `extraction.py` into `pipeline_executor.py` (currently silently does nothing for Supabase videos)
  - Read grid URLs from `scripts` table → call `extract_grid()` → update `assets.image_url`
  - Grid layout is 3x2 (6 panels per grid), NOT 3x3
  - Test video: f9749bd2 ("Drones"), 6 scenes
- **T27-004/005/008**: Permanent storage for all image gen steps (Supabase Storage)

### Security Issues (from Critical Bug Fixes PRD)
- SEC-1 (CRITICAL): dev-token bypasses all auth in dev mode
- SEC-2 (HIGH): get_scene_audio skips tenant check
- SEC-3 (HIGH): API keys revealed without rate limiting
- SEC-4 (HIGH): Hardcoded IP in CORS allowlist
- SEC-5 (MEDIUM): Dynamic SQL via f-strings
- SEC-6 (MEDIUM): No audit logging for key management

### Rubric / Agent Team Improvements
- Command Center: Master ON/OFF toggle, clear queue button, task counter reset
- Activity feed: auto-scroll, WebSocket for real-time, collapse old entries
- Playwright auth fix: 13/20 QA tests skip (need shared auth intercept fixture)

---

## Latest Handoff (2026-04-08)

**What completed:**
- Backend-dev: Migration 028 (4 indexes), niche videos API, cascade delete, pipeline validation relaxed, YouTube sync error handling
- Frontend-dev: Competitors page refactor, niche videos wiring, pipeline error messages, analytics sync errors, TypeScript clean
- Billing page: 3-tier plan comparison, usage bars, Stripe checkout + portal, BYOK explainer
- Settings page: removed duplicate billing UI (580→430 lines)

**Key context for next session:**
- `tasks/roadmap.md` has the full 18-day plan with daily deliverables
- `tasks/decisions.md` has settled architectural choices (10 ADRs)
- All Rubric agent task queue cleared — ready for new PRD or individual tasks
- VPS branch was `agent-dev`, now merged to main. VPS may need `git pull`.

Previous handoffs archived in `tasks/archive/handoffs-2026-03-to-04.md`
