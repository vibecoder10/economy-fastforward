# PRD Progress: PRD 2 — Pipeline UX, Landing Page, Notifications

## Summary
- Total tasks: 14
- Completed: 2
- In progress: 0
- Blocked: 5
- Pending: 7

## Tasks

### Backend
- [ ] 1. Add trial_warning_sent column migration (029)
- [ ] 2. Add query-param token auth fallback for SSE connections
- [ ] 3. Enhance SSE endpoint to emit stage_change events (depends: 2)
- [ ] 4. Create POST /api/settings/keys/validate endpoint
- [ ] 5. Extract shared email utility from google_auth.py
- [ ] 6. Add billing receipt email on checkout (depends: 5)
- [ ] 7. Create trial expiry warning email task (depends: 1, 5)

### Frontend
- [ ] 8. Create usePipelineSSE hook (depends: 3) — BLOCKED
- [ ] 9. Build PipelineStepper component (depends: 8) — BLOCKED
- [x] 10. Upgrade landing page with 7 sections *(completed 2026-04-08 — hero, how-it-works, features, stats, pricing, CTA, footer)*
- [ ] 11. Add API key validation UI (depends: 4) — BLOCKED
- [ ] 12. Create PipelineNotificationProvider (depends: 8) — BLOCKED
- [x] 13. Add compelling empty states to 5 pages *(completed 2026-04-08 — already existed from prior sessions, all acceptance criteria pass)*

### QA
- [ ] 14. QA: Full-flow verification (depends: 3, 6, 7, 8, 9, 10, 11, 12, 13)

## Notes
- Task 10 done. Landing page now has all 7 sections, all acceptance criteria pass.
- Tasks 8, 9, 11, 12 are BLOCKED on backend tasks 2, 3, 4.
- Task 13 has no dependencies — next up for frontend.
- Profile 404 and Analytics 404s: Backend routes registered but returning 404. Handed off to backend-dev.
