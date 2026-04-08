# PRD Progress: PRD 2 — Pipeline UX, Landing Page, Notifications

## Summary
- Total tasks: 14
- Completed: 12
- In progress: 0
- Blocked: 0
- Pending: 2

## Tasks

### Backend
- [x] 1. Add trial_warning_sent column migration (029) *(completed 2026-04-08)*
- [x] 2. Add query-param token auth fallback for SSE connections *(completed 2026-04-08)*
- [x] 3. Enhance SSE endpoint to emit stage_change events *(completed 2026-04-08)*
- [x] 4. Create POST /api/settings/keys/validate endpoint *(completed 2026-04-08)*
- [x] 5. Extract shared email utility *(completed 2026-04-08)*
- [x] 6. Add billing receipt email on checkout *(completed 2026-04-08)*
- [x] 7. Create trial expiry warning email task *(completed 2026-04-08)*

### Frontend
- [x] 8. Create usePipelineSSE hook *(completed 2026-04-08)*
- [x] 9. Build PipelineStepper component *(completed 2026-04-08)*
- [x] 10. Upgrade landing page with 7 sections *(completed 2026-04-08)*
- [ ] 11. Add API key validation UI (depends: 4) — UNBLOCKED
- [x] 12. Create PipelineNotificationProvider *(completed 2026-04-08)*
- [x] 13. Add compelling empty states to 5 pages *(completed 2026-04-08)*

### QA
- [ ] 14. QA: Full-flow verification — waiting on task 11

## Notes
- All 7 backend tasks verified complete with acceptance criteria passing.
- CRITICAL BUG FIXED: email.py shadowed stdlib, broke auth on all routes.
- Task 11 now UNBLOCKED. Only tasks 11 and 14 remain.
