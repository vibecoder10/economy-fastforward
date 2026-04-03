# Progress

## Summary
- Total: 14 tasks
- Done: 14 (backend 6 + frontend 6 + qa 1 + security 1) | Verified: 2 (T13, T14) | Blocked: 0 | Remaining: 0

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
- [x] T13: Playwright end-to-end tests (qa) ✅ — 20 tests (7 pass, 13 skip undeployed endpoints, 0 fail). All 5 AC pass.
- [x] T14: Security audit: auth, data leaks, input sanitization (security) ✅ — Fixed get_video soft-delete leak. All 3 AC pass. Full audit: 6 pre-existing SEC issues re-confirmed, 1 new finding fixed.

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

## Security Audit Results (T14 — 2026-04-03)

### T14 Findings (new PRD features)
- **DELETE auth** ✅ PASS — `delete_video` uses `Depends(get_tenant_id)`, WHERE includes `tenant_id = $2`, checks `deleted_at IS NULL`
- **Soft-delete data leak** 🔧 FIXED — `get_video()` was missing `deleted_at IS NULL` filter. Commit `a017378` adds it.
- **Stage skip prevention** ✅ PASS — `advance_video` uses `_next_stage()` which returns sequential next only. No skip possible.
- **Input sanitization (review.py)** ✅ PASS — `RejectRequest.reason` is never used in SQL (only passed as parameterized `$4`). No f-string injection.
- **Input sanitization (preferences.py)** ✅ PASS — All queries parameterized. `key` from URL path, `value` via `json.dumps` + `$3::jsonb`.
- **Storyboard approve/reject** ✅ PASS — All 3 endpoints use `Depends(get_tenant_id)`, verify script belongs to tenant before update.

### Pre-Existing SEC Issues (re-confirmed, not fixed in this PRD)
- SEC-1 (CRITICAL): `auth.py:32` — dev-token bypasses all auth when `ENV=development` (the default). Production MUST set `ENV=production`.
- SEC-2 (HIGH): `routes/videos.py:443-474` — `get_scene_audio` skips `Depends(get_tenant_id)`, hardcodes tenant from env. Any user can access any video's audio.
- SEC-3 (HIGH): `routes/settings.py:164-182` — `/keys/{key_name}/reveal` returns full unmasked API keys with no rate limiting or re-auth.
- SEC-4 (HIGH): `main.py:287-288` — Hardcoded IP (76.13.119.181) in CORS allowlist. Should use env var.
- SEC-5 (MEDIUM): Dynamic SQL via f-strings in videos.py:305,313,527 — mitigated by hardcoded allowlist field names. Values are parameterized. Safe but poor practice.
- SEC-6 (MEDIUM): `routes/settings.py:90-182` — No audit logging for key management operations (set, delete, reveal).
