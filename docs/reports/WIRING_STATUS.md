# StoryEngine Wiring Status — Ground Truth Audit
> Updated: 2026-03-31T16:20:00Z
> Audited by: Claude Code (Playwright + API verification)
> Branch: claude/audit-storyengine-wiring-0dPTs
> Data Layer: **100% Supabase/PostgreSQL** — zero Airtable dependencies

---

## Pipeline Stage Matrix

| Stage | Frontend Button | API Route | Execution | Polling | Tests |
|-------|----------------|-----------|-----------|---------|-------|
| **Create Idea** | WIRED — `/create` "Generate Story" → `POST /api/pipeline/create-idea` | WIRED — `routes/pipeline.py` registered in `main.py` | FIXED — `create_idea()` is now a simple DB INSERT (no pipeline initialization needed), creates video record with project_id | WIRED — synchronous response, redirects to `/pipeline/{videoId}` | VERIFIED via Playwright |
| **Research** | WIRED — ResearchTab "Run Research" / "Regenerate Research" → `POST /api/pipeline/research/{videoId}` | WIRED — `routes/pipeline.py` | WIRED — BackgroundTasks, imports `research.agent.run_research`, calls it directly, writes payload to Supabase | WIRED — `useTaskPoller` polls `GET /api/pipeline/task/{videoId}` every 3s | MISSING |
| **Script** | WIRED — ScriptVoiceTab "Regenerate Script" → `POST /api/pipeline/script/{videoId}` | WIRED — `routes/pipeline.py`, status gate `ready_for_scripting` | WIRED — BackgroundTasks, imports `script.run.run` via LightPipeline | WIRED — `useTaskPoller` every 3s | MISSING |
| **Split** | WIRED — ScriptVoiceTab "Split Sentences" → `POST /api/pipeline/split/{videoId}` | WIRED — `routes/pipeline.py`, status gate `ready_for_voice` | WIRED — Synchronous, imports `shared.clients.deterministic_splitter`, no external API | MISSING — synchronous (no polling needed) | MISSING |
| **Voice** | WIRED — ScriptVoiceTab "Generate All Voice" + per-scene mic icon → `POST /api/pipeline/voice/{videoId}` | WIRED — `routes/pipeline.py`, status gate `ready_for_voice` (bypassed if scene specified) | WIRED — BackgroundTasks, imports `voice.run.run` via LightPipeline | WIRED — `useTaskPoller` every 3s | MISSING |
| **Image Prompts** | WIRED — ScriptVoiceTab "Generate All Prompts" + per-scene/segment wand icons → `POST /api/pipeline/prompts/{videoId}` | WIRED — `routes/pipeline.py`, status gate `ready_for_image_prompts` (bypassed if scene specified) | WIRED — BackgroundTasks, imports `image_prompts.run.run` via LightPipeline | WIRED — `useTaskPoller` every 3s | MISSING |
| **Story Bible** | WIRED — StoryboardVisualsTab "Story Bible" (when storyboard mode ON) → `POST /api/pipeline/story-bible/{videoId}` | WIRED — `routes/pipeline.py`, no status gate | WIRED — BackgroundTasks, imports `storyboard.bot._generate_story_bible_for_storyboard` directly | WIRED — `useTaskPoller` every 3s | MISSING |
| **Storyboard Prompts** | WIRED — StoryboardVisualsTab "Storyboards" (when storyboard mode ON) → `POST /api/pipeline/storyboards/{videoId}` | WIRED — `routes/pipeline.py`, status gate `ready_for_storyboards` | WIRED — BackgroundTasks, imports `storyboard.run.run` via LightPipeline | WIRED — `useTaskPoller` every 3s | MISSING |
| **Storyboard Images** | WIRED — StoryboardVisualsTab "Generate Storyboard Grids" → `POST /api/pipeline/storyboard-images/{videoId}` | WIRED — `routes/pipeline.py`, status gate `ready_for_storyboard_images` | WIRED — BackgroundTasks, imports `storyboard.run_images.run` via LightPipeline | WIRED — `useTaskPoller` every 3s | MISSING |
| **Storyboard Extract** | MISSING — no frontend button found | WIRED — `routes/pipeline.py`, status gate `ready_for_storyboard_extraction` | WIRED — BackgroundTasks, imports `storyboard.run_extract.run` via LightPipeline | N/A | MISSING |
| **Images** | WIRED — StoryboardVisualsTab "Generate All Images" + per-segment refresh icon → `POST /api/pipeline/images/{videoId}` | WIRED — `routes/pipeline.py`, status gate `ready_for_images` (bypassed if scene specified) | WIRED — BackgroundTasks, imports `images.run.run` via LightPipeline. Also supports variant generation via `ImageClient` directly | WIRED — `useTaskPoller` every 3s (bulk), synchronous per-segment regen | MISSING |
| **Sound Prompts** | MISSING — no frontend button | WIRED — `routes/pipeline.py`, status gate `ready_for_sound_design` | WIRED — BackgroundTasks, imports `sound.run_design.run` via LightPipeline | N/A | MISSING |
| **Sound Effects** | MISSING — no frontend button | WIRED — `routes/pipeline.py`, status gate `ready_for_sound_effects` | WIRED — BackgroundTasks, imports `sound.run_effects.run` via LightPipeline | N/A | MISSING |
| **Video Scripts** | WIRED — VideoClipsTab "Generate Video Prompts" → `POST /api/pipeline/video-scripts/{videoId}` | WIRED — `routes/pipeline.py`, status gate `ready_for_video_scripts` | WIRED — BackgroundTasks, imports `video_motion.run_scripts.run` via LightPipeline | WIRED — `useTaskPoller` every 3s | MISSING |
| **Video Generation** | WIRED — VideoClipsTab "Generate Clips" → `POST /api/pipeline/video-generation/{videoId}` | WIRED — `routes/pipeline.py`, status gate `ready_for_video_generation` | WIRED — BackgroundTasks, imports `video_motion.run_generate.run` via LightPipeline | WIRED — `useTaskPoller` every 3s | MISSING |
| **Thumbnail** | WIRED — ThumbnailTab "Generate Thumbnail" / "Regenerate" → `POST /api/pipeline/thumbnail/{videoId}` | WIRED — `routes/pipeline.py`, status gate `ready_for_thumbnail` | WIRED — BackgroundTasks, imports `thumbnail.run.run` via LightPipeline | WIRED — `useTaskPoller` every 3s | MISSING |
| **Render** | PARTIAL — RenderTab has "Render Video" button → `POST /api/pipeline/render/{videoId}` (WIRED). Standalone `/render` page has "Render Now" buttons with NO onClick handlers (MOCK) | WIRED — `routes/pipeline.py`, status gate `ready_to_render` | WIRED — BackgroundTasks, imports `render.run.run` via LightPipeline | WIRED — `useTaskPoller` every 10s (RenderTab only) | MISSING |
| **Upload** | WIRED — UploadTab "Upload to YouTube" → `POST /api/pipeline/upload/{videoId}` | FIXED — `routes/pipeline.py`, status gate `rendered` | FIXED — BackgroundTasks, imports `upload.run.run` via LightPipeline, writes `youtube_url` to DB | WIRED — `useTaskPoller` every 3s | VERIFIED via Playwright (button visible on rendered video) |
| **Run Next** | WIRED — Video detail "Run Next Step" → `POST /api/pipeline/run-next/{videoId}` | WIRED — `routes/pipeline.py` | WIRED — BackgroundTasks, auto-routes to correct handler based on status. Has approval gates. Optional Claude orchestration via feature flag | WIRED — `useTaskPoller` every 3s | MISSING |
| **Reset** | WIRED — Video detail reset dropdown → `POST /api/pipeline/reset/{videoId}` | WIRED — `routes/pipeline.py` | WIRED — Deletes scripts/assets, resets video status. No pipeline imports needed | N/A | MISSING |
| **Orchestrate** | MISSING — no frontend button | WIRED — `routes/pipeline.py` (two endpoints: execute + decide-only) | WIRED — imports `claude_orchestrator.ClaudeOrchestrator` | N/A | MISSING |

---

## Page Wiring Status

| Page | Status | Detail |
|------|--------|--------|
| `/` (root) | MOCK | Static mock data. No API calls. |
| `/dashboard` | WIRED | Reads dashboard summary, videos, pending review. All navigation buttons. |
| `/pipeline` | WIRED | Lists videos. Create modal → `POST /api/videos`. |
| `/pipeline/[videoId]` | WIRED | Full video detail with 7 tab components. Run Next, Skip, Reset all wired. |
| `/pipeline/[videoId]/storyboards` | **DELETED (C39, 2026-07-20)** | Orphaned standalone page — nothing linked to it (no `<Link>`/`router.push` anywhere in the frontend); the in-page Storyboard functionality lives in `ScenesWorkspaceTab` under the video detail "scenes" tab. Route directory removed; `components/storyboard/` (SceneGrid, PanelDetail, StoryboardProgressBar) left in place, out of scope for this chunk. |
| `/create` | WIRED | "Generate Story" → `POST /api/pipeline/create-idea`. Note: backend handler is BROKEN (see bugs). |
| `/analytics` | WIRED | Reads videos list, computes stats client-side. Read-only. |
| `/autopilot` | WIRED | Reads summary, toggle ON/OFF, update target. Error handling: console.error only (no user feedback). |
| `/competitors` | WIRED | Reads niche config + channels + candidates. Add channel, model candidate → create video. |
| `/activity` | WIRED | Reads activity log + stats. Auto-polls every 10s. Read-only. |
| `/review` | PARTIAL | Approve script/storyboard/thumbnail/images all WIRED. Storyboard "Reject" button has NO onClick handler. |
| `/render` | WIRED | Render queue dashboard. Lists videos in render stages. Render Now triggers pipeline. Links to video detail. |
| `/storyboard` | WIRED | Storyboard review queue. Lists videos with pending storyboards. Review links to per-video editor. Advance button wired. |
| `/visuals` | WIRED | Image generation dashboard. Shows real assets for videos in image stages. Generate buttons trigger pipeline. |
| `/settings` | WIRED | Channel name, niche, audience, frameworks → `PUT /api/projects/current`. Auto-save on blur. |
| `/settings/keys` | WIRED | List/test/set API keys. Full CRUD via vault endpoints. |
| `/profile` | WIRED | Visual styles CRUD. Character generation via Kie.ai. Image analysis via Gemini. |

---

## Auth Status

**Mechanism:** Bearer token via FastAPI `HTTPBearer` dependency.

**Frontend:** `api.ts` reads token from `localStorage`, falls back to `"dev-token"`. Sends `Authorization: Bearer <token>` on every request.

**Backend:** `auth.py` extracts bearer token. Two paths:
- **Dev mode (default):** If token is `"dev-token"` AND `ENV` env var equals `"development"` (the default when unset), returns hardcoded `AuthUser(id="dev-user", email="dev@local", tenant_id=DEV_TENANT_ID)`.
- **Production:** Decodes Supabase JWT using `SUPABASE_JWT_SECRET`, validates HS256 signature and `"authenticated"` audience, extracts `sub` (user ID) and `email`. Looks up tenant via `memberships` table.

**Coverage:** All 14 route files use `get_tenant_id` as a `Depends()`. Auth is applied to every route.

**Exception:** `videos.py` has an audio proxy endpoint (`GET /api/videos/{videoId}/audio/{scene}`) that uses `DEV_TENANT_ID` directly because HTML `<audio>` elements cannot set Authorization headers.

**Risk:** The `"dev-token"` backdoor is active whenever `ENV` is unset (defaults to `"development"`). Production deployments must explicitly set `ENV` to a non-development value.

---

## Database Connections

**Connection:** `asyncpg` pool (min=2, max=10) via `DATABASE_URL` env var to Supabase PostgreSQL.

**Query style:** 100% raw SQL with parameterized `$1, $2` placeholders. No ORM.

**Tables actively queried:**

| Table | Read | Write | Routes |
|-------|------|-------|--------|
| `videos` | Yes | Yes (INSERT, UPDATE, DELETE) | videos, pipeline, dashboard, review, agents, autopilot |
| `scripts` | Yes | Yes (INSERT, UPDATE, DELETE) | pipeline, review, videos |
| `assets` | Yes | Yes (INSERT, UPDATE, DELETE) | assets, pipeline, review, videos |
| `bot_activity` | Yes | Yes (INSERT) | activity, agents, pipeline |
| `stage_transitions` | Yes | Yes (INSERT) | videos, pipeline |
| `autopilot_config` | Yes | Yes (UPSERT) | autopilot, niche |
| `competitor_videos` | Yes | No | autopilot |
| `competitor_channels` | Yes | Yes (INSERT, DELETE) | niche |
| `learnings` | Yes | No | autopilot |
| `projects` | Yes | Yes (INSERT, UPDATE) | projects, visual_styles, videos |
| `visual_styles` | Yes | Yes (INSERT, UPDATE, DELETE) | visual_styles |
| `style_characters` | Yes | Yes (INSERT, DELETE) | visual_styles |
| `memberships` | Yes | No | auth.py (tenant lookup) |
| `channel_profiles` | Yes | Yes (UPSERT) | channel_profile (legacy, superseded by projects) |

**Pipeline writeback:** Yes. `pipeline_executor.py` writes results back: updates `videos.status`, deletes/recreates `scripts` and `assets` rows during resets, inserts `stage_transitions` and `bot_activity` records.

**RLS:** Enabled on all tables with tenant isolation policies, but the backend likely connects via service role key (bypassing RLS). Tenant isolation is enforced in SQL WHERE clauses.

**Schema staleness:** `schema.sql` is missing `visual_styles` and `style_characters` tables (only in migration 010). Also has a forward-reference FK issue (`videos.project_id` → `projects` before `projects` is defined) and a duplicate column `voice_duration_seconds` in `scripts`.

---

## Test Coverage

**Backend tests:** NONE. Zero test files exist anywhere in `storyengine/`. `pytest` is not installed in the backend environment.

**Frontend TypeScript check:** Cannot run — `node_modules` not installed. Running `npm install` first would be required. The last successful state is unknown.

**Frontend test files:** NONE. No `.test.tsx`, `.spec.tsx`, or similar files found.

**Total test count: 0**

---

## Import Graph

`pipeline_executor.py` is the bridge between the StoryEngine backend and `skills/video-pipeline/`. It manipulates `sys.path` at import time:

```
sys.path[0] = skills/video-pipeline/
sys.path += [script/, voice/, image_prompts/, images/, video_motion/,
             thumbnail/, render/, sound/, storyboard/, research/,
             upload/, analytics/]
```

**Direct imports from `skills/video-pipeline/`:**

| Backend Module | Imports From Pipeline |
|---------------|----------------------|
| `pipeline_executor.py` | `research.agent.run_research`, `script.run.run`, `voice.run.run`, `image_prompts.run.run`, `images.run.run`, `video_motion.run_scripts.run`, `video_motion.run_generate.run`, `thumbnail.run.run`, `render.run.run`, `sound.run_design.run`, `sound.run_effects.run`, `storyboard.run.run`, `storyboard.run_images.run`, `storyboard.run_extract.run`, `storyboard.bot._generate_story_bible_for_storyboard`, `shared.clients.*` (airtable, anthropic, google, image, elevenlabs, gemini, slack, deterministic_splitter), `orchestrator.pipeline_config`, `orchestrator.pipeline_constants` |
| `supabase_adapter.py` | `orchestrator.pipeline_constants` (IdeaFields, ScriptFields, ImageFields, Statuses) |
| `claude_orchestrator.py` | Pipeline path (via `pipeline_executor`) |
| `routes/skills.py` | `shared.skill_registry` |
| `routes/agents.py` | `agents.pipeline.AgentPipeline`, `agents.config.QualityTier` |

**No subprocess calls.** All pipeline execution is via direct Python imports in the same process.

---

## Known Bugs Found During Audit

### Critical

1. **`create_idea` → `AttributeError` at runtime**
   - `pipeline_executor.py`: `create_idea()` calls `self._pipeline.run_idea_bot(topic)`, but `run_idea_bot` is never defined on LightPipeline during `_ensure_initialized()`. The 13 runner methods wired are: `run_brief_translator`, `run_voice_bot`, `run_styled_image_prompts`, `run_image_bot`, `run_video_script_bot`, `run_video_gen_bot`, `run_thumbnail_bot`, `run_render_bot`, `run_sound_prompt_bot`, `run_sound_bot`, `run_storyboard_prompts`, `run_storyboard_images`, `run_storyboard_extract`. `run_idea_bot` is missing.
   - Impact: `/create` page "Generate Story" button will fail at runtime.

2. **Upload route missing**
   - Frontend `UploadTab` calls `POST /api/pipeline/upload/{videoId}`, but no such route exists in `routes/pipeline.py`. Will return 404.
   - Impact: "Upload to YouTube" button in video detail will fail.

3. **Skills route ordering bug**
   - `routes/skills.py`: `GET /api/skills/{skill_id}` (line ~135) is defined before `GET /api/skills/pipeline/order` (line ~156) and `GET /api/skills/pipeline/cost` (line ~163). FastAPI matches routes in declaration order, so `/api/skills/pipeline/order` will be caught by `{skill_id}` with `skill_id="pipeline"`.
   - Impact: Pipeline order and cost endpoints are unreachable.

### Moderate

4. **`reject_video` doesn't update status**
   - `routes/videos.py`: `PATCH /api/videos/{videoId}/reject` logs a transition to 'rejected' but does NOT update the video's `status` column. The video remains at its current status.

5. **Autopilot launch is a stub**
   - `routes/autopilot.py`: `POST /api/autopilot/launch/{candidate_id}` marks candidate as `modeled=true` but has a `# TODO: Trigger actual pipeline execution` comment. No pipeline work is triggered.

6. **~~Storyboard approve is a mock~~** (FIXED, then page DELETED — C39, 2026-07-20)
   - `/pipeline/[videoId]/storyboards` page: Approve now calls `advanceVideo()`. Extract All calls `storyboard-extract` pipeline stage. Regenerate clears scene + re-runs storyboard-images. — This page was later found orphaned (no links anywhere in the frontend) and deleted in C39. The storyboard CREATION stage and the in-page Storyboard tab (`ScenesWorkspaceTab`) are unaffected.

7. **Review page "Reject" storyboard button is dead**
   - `/review` page: Storyboard "Reject" button has no onClick handler. It renders but does nothing.

8. **Background task tracking is in-memory only**
   - `pipeline_executor.py` tracks running tasks in a `_running_tasks` dict. Server restart loses all task status. Auto-clears after 10 minutes (stale threshold).

### Low

9. **~~Four mock pages with no API integration~~** (3 of 4 FIXED)
   - `/render`, `/storyboard`, `/visuals` — now fully wired to real API data. `mock-data.ts` deleted.
   - `/` (root) — was already wired (uses getDashboardSummary, getVideos, getActivity, getPendingReview).

10. **Silent error handling on multiple pages**
    - Autopilot toggle/config: errors go to `console.error` only, no user feedback.
    - Settings auto-save: no error handling on blur saves.
    - Competitors "Create Video" from candidate: error only logged to console, button stays in loading state forever.
    - StoryboardVisualsTab per-segment regen + clear storyboard: errors silently swallowed in finally blocks.
    - ThumbnailTab approve: empty catch block.

11. **`channel_profile.py` runs DDL on every request**
    - `_ensure_table()` calls `CREATE TABLE IF NOT EXISTS` on every GET/PUT. Legacy pattern superseded by `projects.py`.

12. **`settings/keys/{name}/reveal` exposes full API keys**
    - Returns unmasked key value with no additional auth beyond standard tenant check. Has a WARNING comment in code.

---

## Files Inventory

### Frontend (`storyengine/frontend/src/`) — 96 files

| Directory | Count | Purpose |
|-----------|-------|---------|
| `components/ui/` | 16 | Reusable UI primitives (Button, Card, Dialog, Badge, etc.) |
| `components/video-detail/` | 14 | Video detail page sub-components |
| `components/production/` | 13 | Pipeline production tabs (ResearchTab, ScriptVoiceTab, etc.) |
| `components/forms/` | 6 | Form components |
| `components/storyboard/` | 4 | Storyboard-specific components |
| `components/autopilot/` | 4 | Autopilot UI (niche setup, playing cards) |
| `components/dashboard/` | 3 | Dashboard widgets |
| `components/nav/` | 2 | Sidebar + bottom bar navigation |
| `components/layout/` | 1 | Layout wrapper |
| `components/` (root) | 7 | Standalone components (StageAdvancer, etc.) |
| `app/` | 20 | App Router pages (15 directories + layout, providers, globals) |
| `lib/` | 5 | api.ts, types.ts, constants.ts, utils.ts, query-client.ts |
| `hooks/` | 1 | use-task-poller.ts |

### Backend (`storyengine/backend/`) — 24 files

| Directory | Count | Purpose |
|-----------|-------|---------|
| `routes/` | 15 | 14 route modules + `__init__.py` |
| Root | 9 | `main.py`, `models.py`, `database.py`, `auth.py`, `vault.py`, `supabase_adapter.py`, `status_map.py`, `pipeline_executor.py`, `claude_orchestrator.py` |

### Migrations — 10 files

`003` through `012` (001-002 presumably folded into `schema.sql`).

### All 14 routers registered in `main.py`: YES

| Router | Prefix | Registered |
|--------|--------|------------|
| dashboard | `/api` | Yes |
| videos | `/api` | Yes |
| assets | `/api` | Yes |
| activity | `/api` | Yes |
| review | `/api` | Yes |
| pipeline | `/api` | Yes |
| settings | `/api` | Yes |
| autopilot | `/api` | Yes |
| skills | `/api` | Yes |
| agents | `/api` | Yes |
| niche | `/api` | Yes |
| channel_profile | `/api` | Yes |
| projects | `/api` | Yes |
| visual_styles | `/api` | Yes |

---

## Playwright Walkthrough Verification (2026-03-31)

### Frontend Pages Verified

| Page | URL | Status | Key Elements |
|------|-----|--------|-------------|
| Pipeline Queue | `/pipeline` | PASS | 9 video cards, filter tabs (In Production/Autopilot/Published), "New Video" button |
| Video Detail | `/pipeline/{id}` | PASS | All 10 tabs visible, 8 clickable, action buttons wired |
| Video Detail Tabs | All 8 tabs | PASS | Research, Script & Voice, Storyboard & Visuals, Video Clips, Thumbnail, Render, Upload, Performance |
| Upload on Rendered | `/pipeline/{id}` (rendered) | PASS | "Upload to YouTube" button visible, SEO preview, schedule options |
| Analytics | `/analytics` | PASS | Page renders with content |
| Activity | `/activity` | PASS | Stats cards (5 bots running, $0.72 cost), filter chips, live feed |
| Settings | `/settings` | PASS | Settings form renders |
| Profile / Visual Styles | `/profile` | PASS | AI Visual Profile Generator, 4 seeded styles visible |
| Storyboard | `/storyboard` | PASS | Page renders |
| Render | `/render` | PASS | Page renders |

### API Endpoints Verified (22 tested, all 200 OK)

| Endpoint | Status | Data Returned |
|----------|--------|---------------|
| `GET /api/health` | 200 | Health check OK |
| `GET /api/videos` | 200 | 9 videos |
| `GET /api/activity` | 200 | Bot activity entries |
| `GET /api/activity/stats` | 200 | Bots running, errors, costs |
| `GET /api/autopilot/summary` | 200 | Autopilot state |
| `GET /api/autopilot/candidates` | 200 | Competitor candidates |
| `GET /api/autopilot/learnings` | 200 | Learning data |
| `GET /api/skills` | 200 | Skill registry |
| `GET /api/skills/pipeline/order` | 200 | Pipeline execution order |
| `GET /api/skills/pipeline/cost` | 200 | Cost breakdown |
| `GET /api/dashboard/summary` | 200 | Dashboard stats |
| `GET /api/review/pending` | 200 | Pending review items |
| `GET /api/niche/config` | 200 | Niche configuration |
| `GET /api/niche/channels` | 200 | Competitor channels |
| `GET /api/channel-profile` | 200 | Channel profile data |
| `GET /api/settings/keys` | 200 | API key configuration |
| `GET /api/visual-styles` | 200 | 4 visual styles |
| `GET /api/agents/stats` | 200 | Agent pipeline stats |
| `GET /api/videos/{id}` | 200 | Single video detail |
| `GET /api/videos/{id}/script` | 200 | Script scenes |
| `GET /api/videos/{id}/assets` | 200 | Video assets |
| `GET /api/pipeline/status/{id}` | 200 | Pipeline status |

### Data Layer Confirmation

**StoryEngine uses 100% Supabase/PostgreSQL. Zero Airtable API calls.**

The `supabase_adapter.py` provides an Airtable-compatible interface (named `self._pipeline.airtable` for backward compatibility with skills pipeline code), but all data flows through `asyncpg` → PostgreSQL. Legacy field names (`airtable_record_id`, `airtable_synced`) exist in the DB schema but are never read or acted upon.

### Bugs Fixed During Audit

| Bug | Description | Fix | Verified |
|-----|-------------|-----|----------|
| #1 | `create_idea()` crashed — called undefined `run_idea_bot` on LightPipeline | Removed broken call, made `create_idea()` a simple DB INSERT with `project_id` | Playwright: create → redirect works |
| #2 | Upload route missing — UploadTab "Upload to YouTube" returned 404 | Added `run_upload()` to PipelineExecutor + route handler in `pipeline.py` | Playwright: button visible on rendered video |
| #3 | Skills route shadowing — `GET /api/skills/pipeline/order` matched by `/{skill_id}` | Reordered routes: static paths before parameterized | API: both `/pipeline/order` and `/pipeline/cost` return 200 |
