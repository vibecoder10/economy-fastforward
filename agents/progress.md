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

---

# PRD Progress: PRD 3 — UX Polish — Empty States, Dashboard, Create Flow

## Summary
- Total tasks: 11
- Completed: 1
- In progress: 0
- Blocked: 0
- Pending: 10

## Tasks

### Backend
- [x] 1. Fix render_minutes usage increment to pass actual video duration *(completed 2026-04-08)*

### Frontend
- [ ] 2. Add 80%/95% color thresholds to dashboard usage meter bars
- [ ] 3. Add collapsible Advanced Options to pipeline create modal
- [ ] 4. Add success toast on video creation in pipeline page
- [ ] 5. Wire ErrorCard into calendar and analytics error states
- [ ] 6. Add retry button to stage-advancer error state with red GlassCard
- [ ] 7. Audit: verify all 8 pages have Spinner + ErrorCard + EmptyState pattern (depends: 5)

### QA
- [ ] 8. TypeScript build verification — tsc + next build (depends: 2,3,4,5,6,7)
- [ ] 9. Verify no hardcoded hex colors in new/modified components (depends: 8)

### Security
- [ ] 10. Security audit — verify no XSS in EmptyState/ErrorCard (depends: 8)

### QA
- [ ] 11. E2E QA — new user flow with Playwright (depends: 1,8,9,10)

## Notes
- Backend task 1 complete. Remaining tasks are frontend/QA/security.
