# PRD 2: Pipeline UX — Real-time Progress, Landing Page, Notifications — Progress

**Total tasks:** 13
**Done:** 11/13
**Remaining:** 2 (T12 QA regression, T13 security audit)

## Task Status

- [x] T1: SSE backend — dual event types + query-param auth fallback (backend) — done, verified 2026-04-10
- [x] T2: SSE frontend hook — use-pipeline-sse.ts (frontend) — done, verified 2026-04-10
- [x] T3: PipelineStepper component — 13-stage visual stepper (frontend) — done, verified 2026-04-10
- [x] T4: Wire PipelineStepper to video detail + pipeline list SSE (frontend) — done, verified 2026-04-10
- [x] T5: Landing page upgrade — 7 sections with social proof + pricing (frontend) — done, verified 2026-04-10
- [x] T6: Backend POST /api/settings/keys/validate endpoint (backend) — done, verified 2026-04-10 (fixed route ordering bug)
- [x] T7: Frontend settings key validation UI with test buttons (frontend) — done, verified 2026-04-10
- [x] T8: Shared email utility + billing receipt email (backend) — done, verified 2026-04-10
- [x] T9: Trial warning migration + email task (backend) — done, verified 2026-04-10
- [x] T10: PipelineNotificationProvider — SSE-driven toast notifications (frontend) — done, verified 2026-04-10
- [x] T11: Empty states for dashboard, pipeline, competitors, analytics, learnings (frontend) — done, verified 2026-04-10
- [ ] T12: QA full PRD 2 regression — Playwright smoke tests (qa-engineer) — pending, deps met
- [ ] T13: Security audit — SSE auth, key validation sanitization, email injection (qa-engineer) — pending, deps met

## Bugs Found During Verification

- **BUG-PT-ROUTE-ORDER** (FIXED): POST /api/settings/keys/validate was unreachable due to FastAPI route ordering — /keys/{key_name} caught it first. Fixed in commit 4057fb1 by moving /keys/validate before parameterized routes.

## Summary

T1-T11 all implemented, acceptance criteria pass, Playwright-verified. Fixed one route ordering bug (T6). TSC: 0 errors. 5/5 workflows PASS, 0 console errors, 0 network errors. T12-T13 ready for QA agent.

---

# PRD 4: Growth & Launch — Progress (COMPLETE)

**Total tasks:** 15
**Done:** 15/15
**Remaining:** 0

## Task Status

- [x] T1: Analytics backend — topic-performance + competitor-benchmark endpoints (backend) — done
- [x] T2: Brand Kit backend — migration + channel_profile extensions (backend) — done
- [x] T3: Notification preferences backend — migration + GET/PATCH endpoints (backend) — done
- [x] T4: Demo mode backend — 3 static demo endpoints, no auth (backend) — done
- [x] T5: Export manifest backend — GET /api/videos/{id}/export-manifest (backend) — done
- [x] T6: Learning Insights dashboard redesign (frontend) — done
- [x] T7: Analytics 2.0 frontend — topic chart + competitor card (frontend) — done
- [x] T8: Video preview player on RenderTab (frontend) — done
- [x] T9: Getting Started guide & help page at /docs (frontend) — done
- [x] T10: Legal pages — Terms of Service + Privacy Policy (frontend) — done
- [x] T11: Demo mode frontend — landing + 3 sub-pages (frontend) — done
- [x] T12: Export button + Brand Kit UI + Notification toggles (frontend) — done
- [x] T13: Beta launch regression — full page + API sweep (qa) — done
- [x] T14: Security audit — auth, tenant isolation, secrets (pipeline-tester) — done
- [x] T15: Performance & load readiness check (qa) — done 2026-04-10

## Summary

PRD 4 complete. All 15 tasks done and verified. Performance check passed with P1 recommendations (dashboard/summary and settings/keys slow due to sequential DB queries). See `storyengine/agents/reports/qa-engineer-performance-T15.md` for full report.
