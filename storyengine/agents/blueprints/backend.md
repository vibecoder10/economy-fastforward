# Backend Blueprint

> Complete reference for building FastAPI routes in StoryEngine.
> Source files: `storyengine/backend/`

---

## Route Registry

| Router File | Prefix | Tags |
|---|---|---|
| `routes/dashboard.py` | `/api/dashboard` | dashboard |
| `routes/videos.py` | `/api/videos` | videos |
| `routes/assets.py` | `/api/assets` | assets |
| `routes/activity.py` | `/api/activity` | activity |
| `routes/review.py` | `/api/review` | review |
| `routes/pipeline.py` | `/api/pipeline` | pipeline |
| `routes/settings.py` | `/api/settings` | settings |
| `routes/autopilot.py` | `/api/autopilot` | autopilot |
| `routes/skills.py` | `/api/skills` | skills |
| `routes/agents.py` | `/api/agents` | agents |
| `routes/niche.py` | `/api/niche` | niche |
| `routes/channel_profile.py` | `/api/channel-profile` | channel-profile |
| `routes/projects.py` | `/api/projects` | projects |
| `routes/visual_styles.py` | `/api/visual-styles` | visual-styles |
| `routes/discovery.py` | `/api/discovery` | discovery |
| `routes/learning_extraction.py` | `/api/learnings` | learnings |
| `routes/youtube_sync.py` | `/api/youtube` | youtube-sync |

All routers are registered in `main.py` via `app.include_router(module.router)`.
Health check: `GET /api/health` (defined directly in main.py).

---

## Endpoints (by file)

### dashboard.py
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/dashboard/summary` | Aggregated stats: active bots, pending review, pipeline distribution, cost, latest video |

### videos.py
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/videos` | List videos (optional `?status=`, `?limit=`, `?offset=`) |
| `POST` | `/api/videos` | Create video idea (body: `CreateVideoRequest`) |
| `GET` | `/api/videos/{video_id}` | Full video detail |
| `PATCH` | `/api/videos/{video_id}` | Update allowed fields (revision_notes, video_title, headline, thumbnail_prompt, thumbnail_style_override) |
| `PATCH` | `/api/videos/{video_id}/advance` | Move video to next pipeline stage |
| `PATCH` | `/api/videos/{video_id}/reject` | Flag/reject video (optional `?reason=`) |
| `GET` | `/api/videos/{video_id}/assets` | All assets for video (excludes variant_candidate) |
| `GET` | `/api/videos/{video_id}/assets/variants` | Variant candidate assets (`?scene=&index=` required) |
| `GET` | `/api/videos/{video_id}/script` | Full script (all scenes ordered) |
| `GET` | `/api/videos/{video_id}/audio/{scene}` | Proxy-stream voice audio from Google Drive |
| `PATCH` | `/api/videos/{video_id}/styles` | Update visual_style, accent_color, image_model_override, video_model |
| `POST` | `/api/videos/{video_id}/accept-suggestion` | Accept agent suggestions (body: `{accept: ["script","title","thumbnail"]}`) |
| `POST` | `/api/videos/{video_id}/reject-suggestion` | Clear all suggested_* fields |
| `PATCH` | `/api/videos/{video_id}/scenes/{scene}/text` | Update scene narration text |
| `PATCH` | `/api/videos/{video_id}/scenes/{scene}/tone` | Update scene tone (serious/conversational/urgent/concise) |
| `GET` | `/api/videos/{video_id}/scenes/{scene}/segments` | Get timed segments with cumulative timing |
| `PUT` | `/api/videos/{video_id}/scenes/{scene}/segments` | Batch update segment sentence_text |
| `PATCH` | `/api/videos/{video_id}/storyboard-mode` | Toggle storyboard on/off for all scenes |
| `DELETE` | `/api/videos/{video_id}/storyboards` | Clear all storyboard data, restore original prompts |
| `DELETE` | `/api/videos/{video_id}/storyboards/{scene}` | Clear storyboard for one scene, restore original prompts |

### assets.py
| Method | Path | Description |
|---|---|---|
| `PATCH` | `/api/assets/{asset_id}/approve` | Approve single asset |
| `PATCH` | `/api/assets/{asset_id}/reject` | Reject single asset |
| `POST` | `/api/assets/batch-approve` | Batch approve/reject (body: `BatchApproval`) |

### activity.py
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/activity` | Bot activity log (optional `?status=`, `?limit=`, `?offset=`) |
| `GET` | `/api/activity/stats` | Running bots, errors today, cost today |
| `GET` | `/api/activity/stream` | SSE endpoint for real-time activity updates (polls every 5s) |

### review.py
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/review/pending` | All items needing review: scripts, storyboards, thumbnails, images |

### pipeline.py
| Method | Path | Description |
|---|---|---|
| `POST` | `/api/pipeline/create-idea` | Create video idea (body: `CreateIdeaRequest`) |
| `POST` | `/api/pipeline/research/{video_id}` | Run research + auto-cascade through pipeline |
| `POST` | `/api/pipeline/script/{video_id}` | Generate script |
| `POST` | `/api/pipeline/voice/{video_id}` | Generate voice (`?scene=` for targeted) |
| `POST` | `/api/pipeline/split/{video_id}` | Split scene text into timed segments (synchronous) |
| `POST` | `/api/pipeline/prompts/{video_id}` | Generate image prompts (`?scene=&index=` for targeted) |
| `POST` | `/api/pipeline/storyboards/{video_id}` | Generate storyboard prompts (`?scene=` for targeted) |
| `POST` | `/api/pipeline/story-bible/{video_id}` | Generate Story Bible |
| `POST` | `/api/pipeline/storyboard-images/{video_id}` | Generate storyboard images (`?scene=` for targeted) |
| `POST` | `/api/pipeline/storyboard-extract/{video_id}` | Extract frames from storyboard grids |
| `POST` | `/api/pipeline/images/{video_id}` | Generate images (`?scene=&index=&variants=` for targeted/variants) |
| `POST` | `/api/pipeline/sound-prompts/{video_id}` | Generate sound design prompts |
| `POST` | `/api/pipeline/sound-effects/{video_id}` | Generate sound effects |
| `POST` | `/api/pipeline/video-scripts/{video_id}` | Generate video motion scripts |
| `POST` | `/api/pipeline/video-generation/{video_id}` | Generate video clips |
| `POST` | `/api/pipeline/thumbnail/{video_id}` | Generate thumbnail |
| `POST` | `/api/pipeline/render/{video_id}` | Render final video |
| `POST` | `/api/pipeline/upload/{video_id}` | Upload to YouTube as unlisted draft |
| `POST` | `/api/pipeline/run-next/{video_id}` | Auto-detect and run next step |
| `GET` | `/api/pipeline/status/{video_id}` | Current pipeline status + next action |
| `GET` | `/api/pipeline/task/{video_id}` | Poll background task status (running/completed/failed) |
| `GET` | `/api/pipeline/task/{video_id}/clear` | Clear stale task status |
| `POST` | `/api/pipeline/orchestrate` | Claude-driven orchestration (body: `OrchestrateRequest`) |
| `POST` | `/api/pipeline/orchestrate/decide` | Claude decides without executing |
| `POST` | `/api/pipeline/reset/{video_id}` | Reset pipeline stage + delete downstream data |

### settings.py
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/settings/keys` | List all API key statuses (masked) |
| `GET` | `/api/settings/keys/{key_name}` | Status of specific key |
| `POST` | `/api/settings/keys/{key_name}` | Set/update API key (body: `SetKeyRequest`) |
| `DELETE` | `/api/settings/keys/{key_name}` | Delete API key from Vault |
| `POST` | `/api/settings/keys/{key_name}/test` | Test API key validity |
| `GET` | `/api/settings/keys/{key_name}/reveal` | Reveal full unmasked key value |

### autopilot.py
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/autopilot/summary` | Full state + config + candidates + learnings |
| `GET` | `/api/autopilot/candidates` | Competitor candidates (`?limit=&min_vph=&include_modeled=`) |
| `GET` | `/api/autopilot/learnings` | Learned patterns (`?category=&limit=`) |
| `POST` | `/api/autopilot/config` | Update config (body: `ConfigUpdate`) |
| `POST` | `/api/autopilot/toggle` | Enable/disable (body: `ToggleRequest`) |
| `POST` | `/api/autopilot/launch/{candidate_id}` | Launch production from competitor video |

### skills.py
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/skills` | List all skills with availability |
| `GET` | `/api/skills/pipeline/order` | Pipeline skills in execution order |
| `GET` | `/api/skills/pipeline/cost` | Estimated cost breakdown |
| `GET` | `/api/skills/{skill_id}` | Single skill detail |

### agents.py
| Method | Path | Description |
|---|---|---|
| `POST` | `/api/agents/videos/{video_id}/run` | Trigger agent quality pipeline (body: `RunAgentRequest`) |
| `GET` | `/api/agents/videos/{video_id}` | Full paper trail for agent run |
| `GET` | `/api/agents/videos/{video_id}/task` | Poll agent task status |
| `GET` | `/api/agents/videos` | List videos with agent quality scores |
| `GET` | `/api/agents/stats` | Aggregate agent stats |

### niche.py
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/niche/config` | Get niche configuration |
| `POST` | `/api/niche/setup` | Save niche category + sub-niche |
| `GET` | `/api/niche/channels` | List competitor channels |
| `POST` | `/api/niche/channels` | Add competitor channel (body: `ChannelAdd`) |
| `DELETE` | `/api/niche/channels/{channel_id}` | Remove competitor channel |
| `POST` | `/api/niche/scrape` | Trigger yt-dlp scrape of all active channels (background) |
| `GET` | `/api/niche/scrape/status` | Check scrape task status |

### channel_profile.py
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/channel-profile` | Get channel profile (legacy) |
| `PUT` | `/api/channel-profile` | Update channel profile (upsert) |
| `GET` | `/api/channel-profile/integrations` | Integration connection statuses |

### projects.py
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/projects/current` | Get current project (auto-creates if none) |
| `PUT` | `/api/projects/current` | Partial update current project |
| `GET` | `/api/projects/channel-profile` | Backward compat redirect |

### visual_styles.py
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/visual-styles` | List all styles with characters |
| `POST` | `/api/visual-styles` | Create new style |
| `POST` | `/api/visual-styles/characters/generate` | Generate character image via Kie.ai |
| `POST` | `/api/visual-styles/analyze-image` | Analyze reference image via Gemini Vision |
| `PUT` | `/api/visual-styles/{style_id}/activate` | Activate style (deactivates others) |
| `DELETE` | `/api/visual-styles/{style_id}` | Delete user-created style (not defaults) |
| `POST` | `/api/visual-styles/{style_id}/characters` | Create character for a style |
| `DELETE` | `/api/visual-styles/{style_id}/characters/{character_id}` | Delete character |

### discovery.py
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/discovery/ideas` | List ideas (`?status=&limit=&batch_date=`, default status=fresh) |
| `GET` | `/api/discovery/status` | Refresh status + batch info |
| `POST` | `/api/discovery/refresh` | Generate ideas from competitors via Claude (background) |
| `POST` | `/api/discovery/ideas/{idea_id}/launch` | One-click launch: create video + start pipeline |
| `POST` | `/api/discovery/ideas/{idea_id}/dismiss` | Mark idea as dismissed |

### learning_extraction.py
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/learnings` | List learnings (`?category=&active_only=&limit=`) |
| `POST` | `/api/learnings/extract` | Extract patterns from all unprocessed videos with CTR data |
| `POST` | `/api/learnings/extract/{video_id}` | Extract patterns from single video |
| `POST` | `/api/learnings/analyze-titles` | Analyze competitor title patterns |
| `POST` | `/api/learnings/analyze-transcripts` | Analyze competitor transcript hook patterns |

### youtube_sync.py
| Method | Path | Description |
|---|---|---|
| `POST` | `/api/youtube/sync` | Trigger YouTube metrics sync (background) |
| `GET` | `/api/youtube/sync/status` | Check sync task status |

---

## Pydantic Models (models.py)

| Model | Key Fields |
|---|---|
| `VideoSummary` | id, video_title, status, thumbnail_url, accent_color, total_cost, views, ctr, created_at, updated_at |
| `VideoDetail` | extends VideoSummary + airtable_record_id, headline, source, framework_angle, thematic_framework, hook_script, past_context, present_parallel, future_prediction, writer_guidance, thesis, executive_hook, research_payload(dict), original_dna(dict), script, story_bible, thumbnail_prompt, thumbnail_style_override, visual_style, image_style_override, image_model_override, video_model, video_length_minutes, youtube_url, avg_retention, impressions, likes, comments, performance_verdict |
| `VideoAdvance` | (empty body) |
| `VideoReject` | reason(optional) |
| `AssetSummary` | id, video_id, video_title, scene, image_index, image_url, image_prompt, status, shot_type, hero_shot, created_at |
| `AssetApproval` | status ("approved"/"rejected") |
| `BatchApproval` | asset_ids(list), status |
| `SceneTextUpdate` | text |
| `SceneToneUpdate` | tone (serious/conversational/urgent/concise) |
| `SegmentUpdate` | segments: list[{image_index, sentence_text}] |
| `StoryboardModeUpdate` | enabled(bool) |
| `CreateVideoRequest` | title, source_url(opt), framework_angle(opt), video_length_minutes(opt, default=10) |
| `ScriptScene` | id, video_id, scene, scene_text, voice_over_url, voice_status, script_status, sources, storyboard_on_off |
| `ActivityEntry` | id, bot_name, video_id, video_title, status, message, cost, created_at |
| `ActivityStats` | bots_running, errors_today, cost_today |
| `DashboardSummary` | active_bots, pending_review, pipeline_distribution(dict), cost_today, cost_week(list), errors, latest_video(VideoSummary), total_videos |
| `PendingReview` | scripts(list[dict]), storyboards(list[dict]), thumbnails(list[dict]), images(list[dict]) |

**Pipeline stages** (defined in `PIPELINE_STAGES`):
`idea_logged` -> `ready_for_scripting` -> `ready_for_voice` -> `ready_for_storyboards` -> `ready_for_images` -> `ready_for_thumbnail` -> `ready_to_render` -> `rendered` -> `uploaded_draft` -> `done`

Many routes define additional models inline. Check the route file for request/response shapes.
---

## Database Schema

### Core Tables

| Table | Columns |
|---|---|
| `tenants` | id(UUID PK), name, slug(unique), plan, created_at |
| `users` | id(UUID PK), email, display_name, avatar_url, created_at |
| `memberships` | id(UUID PK), user_id(FK users), tenant_id(FK tenants), role(owner/admin/member), created_at |
| `accounts` | id(UUID PK), email, display_name, plan, created_at, updated_at |

### Content Tables

| Table | Columns |
|---|---|
| `videos` | id(UUID PK), tenant_id(FK), project_id(FK), airtable_record_id(unique), video_title, status, headline, source, framework_angle, thematic_framework, hook_script, past_context, present_parallel, future_prediction, writer_guidance, thesis, executive_hook, script, seo_description, seo_tags, seo_hashtags, research_payload(JSONB), original_dna(JSONB), source_urls, date_surfaced, timeliness_score, audience_fit_score, content_gap_score, structure_confidence, curiosity_structure, monetization_risk, thumbnail_prompt, thumbnail_style_override, thumbnail_text, thumbnail_approach, accent_color, visual_style, image_model_override, image_style_override, story_bible, script_validation, title_candidates, title_formula, character_reference_url, thumbnail_url, video_length_minutes, clip_duration_seconds, final_video_url, drive_folder_link, drive_folder_id, youtube_video_id, youtube_url, upload_status, upload_date, views, impressions, likes, comments, subscribers_gained, ctr, avg_view_duration_seconds, avg_retention, watch_time_hours, views_24h/48h/7d/30d, ctr_48h, ctr_12h, ctr_24h, retention_48h, last_analytics_sync, post_mortem_48h/7d, performance_verdict, storyboard_status, storyboard_preview_url, storyboard_beat_count, video_model, scene_file_path, core_image_url, scene_count, validation_status, video_id_internal, framework, sources, pipeline_mode, notes, reference_url, idea_reasoning, source_views, source_channel, final_video_attachment_url, structure_source, pattern_library_snapshot, title_poll_result, poll_closed, thumbnail_palette, summary, agent_paper_trail(JSONB), agent_hook_score, agent_body_score, agent_tier, agent_cost, suggested_script, suggested_title, suggested_thumbnail_prompt, suggested_thumbnail_urls(JSONB), suggestion_source, suggestion_scores(JSONB), suggestion_status, total_cost, learnings_extracted_at, created_at, updated_at |
| `scripts` | id(UUID PK), tenant_id(FK), video_id(FK videos), airtable_record_id(unique), airtable_id, scene(int), title, scene_text, script_status, voice_status, voice_over_url, voice_duration_seconds, voice_id, sources, framework, psych_angle, sound_map, sfx_status, drive_folder, script_validation, unverified_claims, storyboard_on_off, storyboard_prompts, storyboard_beat_count, storyboard_status, storyboard_1/2/3/4/5_url, created_at, updated_at |
| `assets` | id(UUID PK), tenant_id(FK), video_id(FK videos), airtable_record_id(unique), video_title, scene(int), sentence_index(int), sentence_text, image_index(int), duration_seconds, image_prompt, original_image_prompt, shot_type, image_url, status, sound_prompt, sound_effect_url, sound_volume, video_prompt, video_url, video_status, video_duration, video_clip_url, aspect_ratio, animation_status, intensity, content_type, hero_shot(bool), drive_image_url, storyboard_grid_url, panel_position, generation_method, camera_movement, assigned_video_duration, estimated_clip_cost, created_at, updated_at |
| `projects` | id(UUID PK), account_id(FK accounts), tenant_id(FK tenants), name, niche, target_audience, visual_style, visual_profile_json(JSONB), accent_color, custom_accent_color, frameworks(JSONB), character_references(JSONB), created_at, updated_at |

### Competitor & Learning Tables

| Table | Columns |
|---|---|
| `competitor_channels` | id(UUID PK), tenant_id(FK), airtable_record_id(unique), channel_url, channel_name, category, active(bool), last_scraped(date), notes, created_at |
| `competitor_videos` | id(UUID PK), tenant_id(FK), airtable_record_id(unique), video_id(text), title, published_date, vph, views, channel, url, channel_url, hours_old, scrape_date, modeled(bool), our_video, topic_cluster, curiosity_structure, structure_confidence, thumbnail_style_json, yin_yang_approach, yin_yang_text, analysis_date, modeled_by_us(bool), our_ctr_result, modeled_at, our_video_id(FK videos), thumbnail_url, transcript, duration_seconds, description, likes, updated_at, created_at. UNIQUE(tenant_id, video_id) |
| `learnings` | id(UUID PK), tenant_id(FK), airtable_record_id(unique), pattern, category, detail, confidence, sample_size, avg_ctr, avg_retention, source_videos, active(bool), created_date, last_updated, created_at |
| `title_insights` | id(UUID PK), tenant_id(FK), airtable_record_id(unique), name, pattern_name, description, example_titles, analysis_date, pattern_type, avg_vph, count, confidence, videos_analyzed, vph_threshold, created_at |
| `title_tests` | id(UUID PK), tenant_id(FK), airtable_record_id(unique), idea, title_text, structure, structure_confidence, thumbnail_text, thumbnail_approach, source_patterns, pattern_library_snapshot, poll_result, poll_closed(bool), ctr_12h/24h/48h, selected(bool), video_title, created_at |
| `discovery_ideas` | id(UUID PK), tenant_id(FK), source_type, competitor_video_id(FK), competitor_title, competitor_channel, competitor_url, competitor_vph, competitor_thumbnail_url, our_angle, hook, framework, estimated_appeal, appeal_breakdown(JSONB), title_options(JSONB), status, selected_title_index, launched_video_id(FK videos), batch_date, batch_id, created_at, updated_at |

### Config & Tracking Tables

| Table | Columns |
|---|---|
| `autopilot_config` | id(UUID PK), tenant_id(FK unique), enabled(bool), videos_per_month, production_interval_days, videos_per_scrape, weights(JSONB), thresholds(JSONB), last_cycle, niche_category, sub_niche, created_at, updated_at |
| `channel_profiles` | id(UUID PK), tenant_id(FK unique), channel_name, niche, target_audience, frameworks(JSONB), created_at, updated_at |
| `stage_transitions` | id(UUID PK), video_id(FK videos), tenant_id(FK), from_status, to_status, triggered_by, cost, duration_seconds, error_message, created_at |
| `bot_activity` | id(UUID PK), tenant_id(FK), bot_name, video_id(FK videos), status(started/running/completed/failed), message, cost, created_at |
| `_migrations` | filename(TEXT PK), applied_at |

`visual_styles` and `style_characters` tables created by migration `010_visual_styles.sql` (not in schema.sql).

---

## Database Connection (database.py)

Three functions from `database.py`. Pool: asyncpg, min=2 max=10. Uses `$1,$2,...` params (NOT `%s`).
- `fetch_all(query, *args)` -> `list[dict]`
- `fetch_one(query, *args)` -> `dict | None`
- `execute(query, *args)` -> `str` (e.g. "UPDATE 1")

## Auth

Every route: `tenant_id: str = Depends(get_tenant_id)` from `auth.py`. Dev: `DEV_TENANT_ID` env var. Prod: JWT.

---

## Pipeline Executor (pipeline_executor.py)

Lazy-init: `PipelineExecutor(tenant_id)` loads API keys from Vault, creates LightPipeline.
Clients: SupabaseAdapter (required), AnthropicClient, GoogleClient, SlackClient, ImageClient, ElevenLabsClient, GeminiClient (all optional).

### Key Methods

| Method | What it does |
|---|---|
| `create_idea(topic, source)` | Insert video record, return `{video_id, status}` |
| `run_research(video_id)` | Run research agent, update video with research_payload |
| `run_script(video_id)` | Generate 6-scene script via brief_translator |
| `run_voice(video_id, scene=None)` | Generate voice narration (all or one scene) |
| `run_split(video_id)` | Split scene text into timed segments (synchronous) |
| `run_prompts(video_id, scene=None, index=None)` | Generate image prompts |
| `run_images(video_id, scene=None, index=None)` | Generate images |
| `run_image_variants(video_id, scene, index, variants)` | Generate multiple image variants |
| `run_storyboard_prompts(video_id, scene=None, progress_callback=None)` | Generate storyboard prompts |
| `run_storyboard_images(video_id, scene=None, progress_callback=None)` | Generate storyboard grid images |
| `run_storyboard_extract(video_id)` | Extract frames from storyboard grids |
| `run_story_bible(video_id)` | Generate character/location story bible |
| `run_sound_prompts(video_id)` | Generate sound design prompts |
| `run_sound_effects(video_id)` | Generate sound effects |
| `run_video_scripts(video_id)` | Generate video motion scripts |
| `run_video_generation(video_id)` | Generate video clips (Veo 3.1) |
| `run_thumbnail(video_id)` | Generate thumbnail |
| `run_render(video_id)` | Render final video via Remotion |
| `run_upload(video_id)` | Upload to YouTube as unlisted draft |
| `run_next_step(video_id)` | Auto-detect current status, run next stage |

### Status Flow
```
idea_logged -> ready_for_scripting -> ready_for_voice -> ready_for_storyboards
-> ready_for_images -> ready_for_thumbnail -> ready_to_render -> rendered
-> uploaded_draft -> done
```

### Background Task Pattern
All pipeline routes use `BackgroundTasks`:
1. Validate video exists + correct status
2. Check no task already running (`_get_task_status`)
3. Set task status to "running"
4. Add background task that calls executor method
5. Return immediately with `PipelineResponse(status="running")`
6. Frontend polls `GET /api/pipeline/task/{video_id}` for completion

---

## Background Tasks (main.py lifespan)

Four background loops run on startup (only for tenants with autopilot enabled):

| Task | Interval | What it does |
|---|---|---|
| `_auto_extract_learnings` | 24h | Extract patterns from videos with CTR data |
| `_auto_sync_youtube` | 6h | Pull YouTube metrics into videos table |
| `_auto_analyze_competitor_titles` | 24h | Detect title + hook patterns from competitors |
| `_auto_scrape_competitors` | 24h | Scrape competitor channels via yt-dlp |

---

## Migrations

Auto-run on startup via `_run_pending_migrations()`. Tracked in `_migrations` table.
Files: `backend/migrations/NNN_description.sql` (sorted by filename, each runs once).
Current: 003 through 020.

---

## Patterns

### Adding a New Route
1. Create `routes/my_feature.py` with `router = APIRouter(prefix="/api/my-feature", tags=["my-feature"])`
2. Import `from auth import get_tenant_id` and `from database import fetch_all, fetch_one, execute`
3. Use `tenant_id: str = Depends(get_tenant_id)` on every endpoint
4. Register in `main.py` line 13: add to `from routes import ...` and add `app.include_router(my_feature.router)`

### Query Patterns
- **Read one**: `row = await fetch_one("SELECT * FROM t WHERE id = $1 AND tenant_id = $2", id, tid)` -> dict or None
- **Read many**: `rows = await fetch_all("SELECT * FROM t WHERE tenant_id = $1 LIMIT $2", tid, limit)` -> list[dict]
- **Write**: `result = await execute("UPDATE t SET x = $1 WHERE id = $2", val, id)` -> str like "UPDATE 1"
- **Dynamic updates**: Build `updates[]`, `params[]`, `idx` counter. Append `f"col = ${idx}"` per field. End with `"updated_at = now()"`. Pass `*params` to execute.
- **JSONB writes**: Must use explicit cast: `$1::jsonb` with `json.dumps(data)`

### Error Handling
- 404: `raise HTTPException(status_code=404, detail="Not found")` when `fetch_one` returns None
- 400: Invalid input (wrong enum values, empty required fields)
- 409: Task already running (check `_get_task_status(video_id)`)
- 502: Upstream API failure (Kie.ai, Gemini, etc.)

### Adding a Migration
1. Create `backend/migrations/NNN_description.sql` (next number after 020)
2. Use `ADD COLUMN IF NOT EXISTS` / `CREATE TABLE IF NOT EXISTS` (idempotent)
3. Update `schema.sql` to match (canonical source of truth)
4. Auto-runs on next server startup

### Background Task Pattern
Use `BackgroundTasks` from FastAPI. Track status in module-level `dict[str, dict]` keyed by tenant_id or video_id. Expose `/status` polling endpoint. Set `{"running": True}` before launch, update to `{"running": False, ...}` on completion/error.

### Tenant Isolation
Every query MUST filter by `tenant_id`. Never return cross-tenant data. All tables have tenant_id + index.
