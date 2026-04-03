# Progress

## Summary
- Total: 14 tasks
- Done: 4 | Verified: 0 | Blocked: 5 | Remaining: 5

## Tasks
- [x] T1: Database migration: soft delete, video clip prompts, user preferences (backend) ✅
- [x] T2: Fix stage progression — _next_stage uses full 18-stage pipeline order (backend) ✅
- [ ] T3: Add storyboard approve/reject and bulk-approve endpoints (backend) — depends on T1 ✅
- [ ] T4: Add DELETE /api/videos/{id} soft-delete endpoint (backend) — depends on T1 ✅
- [ ] T5: Add video clip prompt generation + user preferences endpoints (backend) — depends on T1 ✅
- [x] T6: Fix thumbnail generation with pipeline logic + autopilot patterns (backend) ✅
- [ ] T7: Wire storyboard approve/reject buttons to API (frontend) — **BLOCKED** on T3 (backend not implemented)
- [x] T8: Fix stage progress circles, approve button, default Production tab (frontend) ✅
- [ ] T9: Add video delete button + confirmation modal (frontend) — **BLOCKED** on T4 (backend not implemented)
- [ ] T10: Render image thumbnails, fix storyboard mode, add video clip prompt UI (frontend) — **BLOCKED** on T5 (backend not implemented)
- [ ] T11: Add tab drag-to-reorder with persistence (frontend) — **BLOCKED** on T5 (backend not implemented)
- [ ] T12: Full production build passes (frontend) — **BLOCKED** on T7-T11
- [ ] T13: Playwright end-to-end tests (qa) — **BLOCKED** waiting on T12 (which needs T7-T11, which need T1-T6)
- [ ] T14: Security audit: auth, data leaks, input sanitization (security) — **BLOCKED** on T3, T4, T5 (none implemented yet)

## Blocked Tasks
- T7 (frontend): Blocked on T3 — storyboard approve/reject backend endpoints not implemented
- T9 (frontend): Blocked on T4 — DELETE endpoint not implemented
- T10 (frontend): Blocked on T5 — video clip prompt + user preferences endpoints not implemented
- T11 (frontend): Blocked on T5 — user preferences endpoints not implemented
- T12 (frontend): Blocked on T7, T9, T10, T11
- T13 (qa): Blocked on T12 — entire backend (T1-T6) and frontend (T7-T11) chains must complete first
- T14 (security): Blocked on T3, T4, T5 — backend endpoints not yet implemented, nothing to audit

## Dependency Graph
```
T1 (migration) ──┬── T3 (storyboard endpoints) ──── T7 (storyboard UI)
                  ├── T4 (delete endpoint) ───────── T9 (delete UI)
                  └── T5 (prompts + prefs) ──┬────── T10 (visuals/clips UI)
                                             └────── T11 (tab drag)
T2 (fix stage) ──────────────────────────────────── T8 (stage UI + default tab)
T6 (fix thumbnail) ─────────────────────────────── T10 (thumbnail UI)

T7, T8, T9, T10, T11 ── T12 (build passes) ── T13 (QA) 
T3, T4, T5 ── T14 (security)
```

## Security Issues (Pre-Audit Findings — T14 blocked, but existing code reviewed)
- SEC-1 (CRITICAL): `auth.py:31-33` — dev-token "dev-token" bypasses all JWT auth when ENV=development (the default). Must ensure this is gated to dev-only deployments.
- SEC-2 (HIGH): `routes/videos.py:424-455` — `get_scene_audio` endpoint skips `Depends(get_tenant_id)`, hardcodes tenant_id from env. Any user can access any video's audio.
- SEC-3 (HIGH): `routes/settings.py:164-182` — `/keys/{key_name}/reveal` returns full unmasked API keys with no rate limiting or re-auth.
- SEC-4 (HIGH): `main.py:287-288` — Hardcoded IP (76.13.119.181) in CORS allowlist. Should use env var.
- SEC-5 (MEDIUM): `routes/videos.py:311,508,560` — Dynamic SQL via f-strings (mitigated by hardcoded field names, but poor practice).
- SEC-6 (MEDIUM): `routes/settings.py:90-182` — No audit logging for key management operations (set, delete, reveal).

### T14 Guidance for Backend Agents (when T3/T4/T5 are implemented):
- T4 (delete): Ensure `DELETE /api/videos/{id}` checks `tenant_id` — soft-delete must be tenant-scoped. All list queries must filter `deleted_at IS NULL`.
- T3 (review): Ensure approve/reject endpoints sanitize `reason` field — no raw string interpolation into SQL.
- T5 (preferences): Ensure user preferences are tenant-scoped. Video prompt generation must validate input.

## Notes
- The `_next_stage()` function in `storyengine/backend/routes/videos.py:104` looks correct — it walks `PIPELINE_STAGES` list. The bug may be that videos have status values not in the 10-stage list (e.g., `researching`, `scripting`). The frontend `STATUS_LABEL` map at `pipeline/page.tsx:34` has ~20 statuses while the backend `PIPELINE_STAGES` only has 10. Investigate during T2.
- Storyboards are stored in `scripts` table (storyboard_1_url through storyboard_5_url), NOT a `storyboard_panels` table. Approve/reject endpoints in T3 must update `scripts.storyboard_status`.
- No `video_clips` table exists — clips are in `assets` table with video_clip_url. T5 must add `prompt` column to `assets` or add a column to the existing table.
- Default tab is `"ideas"` at `pipeline/page.tsx:132`. T8 changes this to `"production"`.
- `list_videos` at `videos.py:114` has no `deleted_at IS NULL` filter — T4 must add it.
- Last migration is 022. New migration should be 023.
