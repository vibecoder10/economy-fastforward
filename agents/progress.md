# PRD Progress: PRD 2 — Pipeline UX, Landing Page, Notifications

## Summary
- Total tasks: 14
- Completed: 5
- In progress: 0
- Blocked: 1
- Pending: 8

## Tasks

### Backend
- [ ] 1. Add trial_warning_sent column migration (029)
- [x] 2. Add query-param token auth fallback for SSE connections *(done — auth.py has query_params fallback)*
- [ ] 3. Enhance SSE endpoint to emit stage_change events (depends: 2)
- [ ] 4. Create POST /api/settings/keys/validate endpoint
- [ ] 5. Extract shared email utility from google_auth.py
- [ ] 6. Add billing receipt email on checkout (depends: 5)
- [ ] 7. Create trial expiry warning email task (depends: 1, 5)

### Frontend
- [x] 8. Create usePipelineSSE hook *(completed 2026-04-08)*
- [x] 9. Build PipelineStepper component *(completed 2026-04-08)*
- [x] 10. Upgrade landing page with 7 sections *(completed 2026-04-08)*
- [ ] 11. Add API key validation UI (depends: 4) — BLOCKED
- [x] 12. Create PipelineNotificationProvider *(completed 2026-04-08)*
- [x] 13. Add compelling empty states to 5 pages *(completed 2026-04-08)*

### QA
- [ ] 14. QA: Full-flow verification (depends: 3, 6, 7, 8, 9, 10, 11, 12, 13)

## Notes
- All frontend tasks done except task 11 (blocked on backend task 4).
- Backend task 2 confirmed done. Tasks 1, 3, 4, 5, 6, 7 still pending.
