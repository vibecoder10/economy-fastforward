# Progress

## Summary
- Total: 14 tasks
- Done: 11 (backend 6 + frontend 5) | Verified: 0 | Blocked: 0 | Remaining: 3 (frontend-build, qa, security)

## Tasks
- [x] T1: Database migration: soft delete, video clip prompts, user preferences (backend) ✅
- [x] T2: Fix stage progression — _next_stage uses full 18-stage pipeline order (backend) ✅
- [x] T3: Add storyboard approve/reject and bulk-approve endpoints (backend) ✅
- [x] T4: Add DELETE /api/videos/{id} soft-delete endpoint (backend) ✅
- [x] T5: Add video clip prompt generation + user preferences endpoints (backend) ✅
- [x] T6: Fix thumbnail generation with pipeline logic + autopilot patterns (backend) ✅
- [x] T7: Wire storyboard approve/reject buttons to API (frontend) ✅
- [x] T8: Fix stage progress circles, approve button, default Production tab (frontend) ✅
- [x] T9: Add video delete button + confirmation modal (frontend) ✅
- [x] T10: Render image thumbnails, fix storyboard mode, add video clip prompt UI (frontend) ✅
- [x] T11: Add tab drag-to-reorder with persistence (frontend) ✅
- [x] T12: Full production build passes (frontend) ✅
- [ ] T13: Playwright end-to-end tests (qa) — depends on T12 (now unblocked)
- [ ] T14: Security audit: auth, data leaks, input sanitization (security) — deps met (T3, T4, T5 done)

## Frontend Commits (this session)
- `87c7f20` feat(frontend): T7 — wire storyboard approve/reject buttons to API
- `718e5ce` feat(frontend): T9 — add video delete button with confirmation modal
- `3184d6f` feat(frontend): T11 — add tab drag-to-reorder with persistence

## What Was Done (Frontend)
- **T7**: Added `approveStoryboard`, `rejectStoryboard`, `bulkApproveStoryboards` to api.ts. Wired review page and StoryboardTab to use real API endpoints instead of local-only state.
- **T9**: Added delete button (trash icon, visible on hover) to video cards on pipeline page. Confirmation modal with soft-delete via `deleteVideo` API.
- **T10**: Acceptance criteria already passing — VisualsTab renders imageUrl, VideoClipsTab shows prompts, image-segment-card renders asset.image_url.
- **T11**: Installed @dnd-kit. Added SortableTab component with drag handle. Pipeline page tabs are drag-reorderable with persistence via user preferences API.
- **T12**: `npx tsc --noEmit` and `npm run build` both pass clean.

## Dependency Graph
```
T1 (migration) ──┬── T3 (storyboard endpoints) ──── T7 (storyboard UI) ✅
                  ├── T4 (delete endpoint) ───────── T9 (delete UI) ✅
                  └── T5 (prompts + prefs) ──┬────── T10 (visuals/clips UI) ✅
                                             └────── T11 (tab drag) ✅
T2 (fix stage) ──────────────────────────────────── T8 (stage UI + default tab) ✅
T6 (fix thumbnail) ─────────────────────────────── T10 (thumbnail UI) ✅

T7, T8, T9, T10, T11 ── T12 (build passes) ✅ ── T13 (QA) 
T3, T4, T5 ── T14 (security)
```

## Security Issues (Pre-Audit Findings — T14 now unblocked)
- SEC-1 (CRITICAL): `auth.py:31-33` — dev-token "dev-token" bypasses all JWT auth when ENV=development (the default). Must ensure this is gated to dev-only deployments.
- SEC-2 (HIGH): `routes/videos.py:424-455` — `get_scene_audio` endpoint skips `Depends(get_tenant_id)`, hardcodes tenant_id from env. Any user can access any video's audio.
- SEC-3 (HIGH): `routes/settings.py:164-182` — `/keys/{key_name}/reveal` returns full unmasked API keys with no rate limiting or re-auth.
- SEC-4 (HIGH): `main.py:287-288` — Hardcoded IP (76.13.119.181) in CORS allowlist. Should use env var.
- SEC-5 (MEDIUM): `routes/videos.py:311,508,560` — Dynamic SQL via f-strings (mitigated by hardcoded field names, but poor practice).
- SEC-6 (MEDIUM): `routes/settings.py:90-182` — No audit logging for key management operations (set, delete, reveal).
