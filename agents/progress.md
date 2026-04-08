# PRD Progress: Critical Bug Fixes — Competitors, Video Pipeline, and Analytics

## Summary
- Total tasks: 14
- Completed: 13
- In progress: 0
- Blocked: 0
- Pending: 1

## Tasks

### Backend
- [x] 1. Add database indexes for competitor_videos queries *(completed 2026-04-08 — migration 028 already applied)*
- [x] 2. Add GET /api/niche/videos endpoint with pagination, filters, sort *(completed 2026-04-08 — already implemented)*
- [x] 3. Add cascade delete to DELETE /api/niche/channels/{channel_id} *(completed 2026-04-08 — enhanced with discovery_ideas FK cleanup)*
- [x] 4. Enhance scrape status with per-channel progress + add cancel endpoint *(completed 2026-04-08 — already implemented)*
- [x] 5. Relax pipeline status validation for thumbnail and video-scripts endpoints *(completed 2026-04-08 — thumbnail: ready_for_voice, video-scripts: ready_for_images)*
- [x] 6. Enhance YouTube sync with error_type field and retry logic *(completed 2026-04-08 — already implemented)*

### Frontend
- [x] 7. Add getNicheVideos() to frontend api.ts + update TypeScript types *(completed 2026-04-08 — already implemented in prior session)*
- [x] 8. Refactor competitors page: pagination, filters, sort, scrape progress, cancel *(completed 2026-04-08 — already implemented in prior session)*
- [x] 9. Fix getCompletedSteps — remove rendered from terminal status list *(completed 2026-04-08)*
- [x] 10. Add descriptive error messages for pipeline stage buttons *(completed 2026-04-08 — relaxed ThumbnailTab gate to ready_for_voice, improved friendlyError for new backend format, show descriptive 400 errors in toast)*
- [x] 11. Add sync error display + re-auth link on analytics page *(completed 2026-04-08 — already implemented in prior session)*
- [x] 12. TypeScript compilation check — all changes compile cleanly *(completed 2026-04-08 — tsc --noEmit passes)*

### QA
- [ ] 13. QA: Acceptance criteria verification (depends: 12)

### Security
- [x] 14. Security: Validate new endpoints require auth and sanitize inputs *(completed 2026-04-08 — all endpoints use Depends(get_tenant_id), inputs validated by Pydantic/query params)*

## Notes
- All 6 backend tasks complete. Frontend tasks 7, 8, 10, 11 are now UNBLOCKED.
- Profile 404 and Analytics 404: Both endpoints work fine with auth (tested via curl). The errors were transient — likely from a server restart.
- Thumbnail 400: Fixed by relaxing validation from ready_for_images to ready_for_voice. Videos with scripts can now generate thumbnails.
- Video-scripts: Relaxed from ready_for_sound_design to ready_for_images.
- Task 3 enhanced: cascade delete now also nullifies discovery_ideas.competitor_video_id FK.
