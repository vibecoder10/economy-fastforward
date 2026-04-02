# Orchestrator Blueprint

## Pipeline Flow
```
idea_logged -> ready_for_scripting -> ready_for_voice -> ready_for_storyboards ->
ready_for_images -> ready_for_thumbnail -> ready_to_render -> rendered -> uploaded_draft -> done
```
Each stage has: status indicator, data fields, actions (buttons), transitions (confirmation UI).

## Tab Map

| # | Tab | Path | What Must Work | Backend Routes | Frontend Components |
|---|-----|------|---------------|---------------|-------------------|
| 1 | Pipeline List | `/pipeline` | Video cards with 10 status badges, discovery carousel, launch | `GET /api/videos`, `GET /api/discovery/ideas`, `POST /api/discovery/refresh` | `pipeline/page.tsx`, `video-card.tsx` |
| 2 | Video Detail: Info | `/pipeline/[videoId]` | Research payload, original DNA, writer guidance, source metadata | `GET /api/videos/{id}` | `ResearchTab.tsx`, `info-tab.tsx` |
| 3 | Video Detail: Script | `/pipeline/[videoId]` | Scene list, script_validation display, segment editing | `GET /api/videos/{id}/script`, `PUT .../segments`, `GET .../segments` | `ScriptTab.tsx`, `script-tab.tsx`, `segment-list.tsx` |
| 4 | Video Detail: Voice | `/pipeline/[videoId]` | Voice gen trigger, voice_status per scene, audio player | `POST /api/pipeline/voice/{id}`, `GET .../script` | `ScriptVoiceTab.tsx`, `voice-player.tsx` |
| 5 | Video Detail: Storyboard | `/pipeline/[videoId]` | Per-scene prompt gen, grid gen, clear, status badges | `POST /api/pipeline/storyboards/{id}`, `POST .../storyboard-images/{id}`, `DELETE .../storyboards/{scene}` | `StoryboardTab.tsx`, `storyboard-viewer.tsx` |
| 6 | Video Detail: Visuals | `/pipeline/[videoId]` | Image display, approval, variant gen, prompt text | `GET .../assets`, `PATCH /api/assets/{id}/approve`, `POST /api/pipeline/images/{id}` | `StoryboardVisualsTab.tsx`, `VisualsTab.tsx`, `visuals-tab.tsx` |
| 7 | Video Detail: Thumbnail | `/pipeline/[videoId]` | Thumbnail gen, approval, agent suggestions accept/reject | `POST /api/pipeline/thumbnail/{id}`, `POST .../accept-suggestion` | `ThumbnailTab.tsx`, `thumbnail-tab.tsx` |
| 8 | Video Detail: Render | `/pipeline/[videoId]` | Render trigger, progress tracking, output download | `POST /api/pipeline/render/{id}`, `GET .../task/{id}` | `RenderTab.tsx` |
| 9 | Video Detail: Performance | `/pipeline/[videoId]` | Snapshot metrics, post-mortems, agent scores, suggestions | `GET /api/videos/{id}` (all fields on VideoDetail) | `PerformanceTab.tsx`, `performance-tab.tsx` |
| 10 | Competitors | `/competitors` | Candidate cards, confidence breakdown, transcripts, scrape status | `GET /api/autopilot/candidates`, `GET /api/niche/channels`, `GET /api/niche/scrape/status` | `competitors/page.tsx`, `playing-card.tsx`, `card-expanded.tsx` |
| 11 | Discovery Ideas | `/discovery` | Idea cards, refresh, launch modal, title selection, dismiss | `GET /api/discovery/ideas`, `POST .../refresh`, `POST .../launch`, `POST .../dismiss` | `discovery/page.tsx` (NEW) |
| 12 | Learnings | `/learnings` | Pattern cards, extract/analyze actions, enable/disable toggle | `GET /api/learnings`, `POST .../extract`, `POST .../analyze-titles`, `POST .../analyze-transcripts` | `learnings/page.tsx` (NEW) |
| 13 | Autopilot | `/autopilot` | Toggle, config editing, YouTube sync, background task status | `GET /api/autopilot/summary`, `POST .../config`, `POST .../toggle`, `POST /api/youtube/sync` | `autopilot/page.tsx` |
| 14 | Settings | `/settings` | API keys CRUD, project profile, visual styles | `GET/POST/DELETE /api/settings/keys/*`, `GET/PUT /api/projects/current`, `GET/POST /api/visual-styles` | `settings/page.tsx` |
| 15 | Analytics | `/analytics` | Overview stats, CTR timeline, framework performance | Routes TBD (not built yet) | `analytics/page.tsx` (stub) |
| 16 | Profile | `/profile` | User info display, edit form | Routes TBD (not built yet) | `profile/page.tsx` (stub) |

## Audit Methodology
For each tab:
1. List every feature the tab should display (from task queue)
2. Check: does the backend endpoint exist? (`grep @router routes/FILE.py`)
3. Check: does the frontend type match? (`grep FIELD_NAME lib/types.ts`)
4. Check: does the component render the data? (`grep FIELD_NAME components/PATH`)
5. Check: does the action button trigger the right endpoint? (`grep ENDPOINT lib/api.ts`)
6. Write tasks for anything missing or mismatched

## Backend Route Summary
```
GET    /api/health                              — Health check
GET    /api/dashboard/summary                   — Dashboard stats
GET    /api/videos                              — List videos (optional ?status=)
POST   /api/videos                              — Create video
GET    /api/videos/{id}                         — Video detail (all fields)
PATCH  /api/videos/{id}                         — Update video fields
PATCH  /api/videos/{id}/advance                 — Advance pipeline status
PATCH  /api/videos/{id}/reject                  — Reject video
GET    /api/videos/{id}/assets                  — List assets for video
GET    /api/videos/{id}/assets/variants         — Image variants (?scene=&index=)
GET    /api/videos/{id}/script                  — List script scenes
GET    /api/videos/{id}/audio/{scene}           — Get audio URL for scene
PATCH  /api/videos/{id}/styles                  — Update visual style/color/model
POST   /api/videos/{id}/accept-suggestion       — Accept agent suggestion
POST   /api/videos/{id}/reject-suggestion       — Reject agent suggestion
PATCH  /api/videos/{id}/scenes/{s}/text         — Update scene text
PATCH  /api/videos/{id}/scenes/{s}/tone         — Update scene tone
GET    /api/videos/{id}/scenes/{s}/segments     — List segments for scene
PUT    /api/videos/{id}/scenes/{s}/segments     — Update segments
PATCH  /api/videos/{id}/storyboard-mode         — Toggle storyboard mode
DELETE /api/videos/{id}/storyboards             — Clear all storyboards
DELETE /api/videos/{id}/storyboards/{s}         — Clear scene storyboard
PATCH  /api/assets/{id}/approve                 — Approve asset
PATCH  /api/assets/{id}/reject                  — Reject asset
POST   /api/assets/batch-approve                — Batch approve/reject
GET    /api/review/pending                      — Pending review items
GET    /api/activity                            — Activity feed
GET    /api/activity/stats                      — Bot/error/cost stats
POST   /api/pipeline/create-idea                — Create idea
POST   /api/pipeline/research/{id}              — Run research
POST   /api/pipeline/script/{id}                — Generate script
POST   /api/pipeline/voice/{id}                 — Generate voice
POST   /api/pipeline/split/{id}                 — Split script into segments
POST   /api/pipeline/prompts/{id}               — Generate image prompts
POST   /api/pipeline/storyboards/{id}           — Generate storyboard prompts
POST   /api/pipeline/story-bible/{id}           — Generate story bible
POST   /api/pipeline/storyboard-images/{id}     — Generate storyboard grids
POST   /api/pipeline/storyboard-extract/{id}    — Extract panels from grid
POST   /api/pipeline/images/{id}                — Generate images
POST   /api/pipeline/sound-prompts/{id}         — Generate sound prompts
POST   /api/pipeline/sound-effects/{id}         — Generate sound effects
POST   /api/pipeline/video-scripts/{id}         — Generate video scripts
POST   /api/pipeline/video-generation/{id}      — Generate video clips
POST   /api/pipeline/thumbnail/{id}             — Generate thumbnail
POST   /api/pipeline/render/{id}                — Trigger render
POST   /api/pipeline/upload/{id}                — Upload to YouTube
POST   /api/pipeline/run-next/{id}              — Run next pipeline step
GET    /api/pipeline/status/{id}                — Pipeline status
GET    /api/pipeline/task/{id}                   — Task poll status
GET    /api/pipeline/task/{id}/clear             — Clear stale task
POST   /api/pipeline/orchestrate                — Full orchestration
POST   /api/pipeline/orchestrate/decide         — Decide next step
POST   /api/pipeline/reset/{id}                 — Reset pipeline to stage
GET    /api/settings/keys                       — List API keys
GET    /api/settings/keys/{name}                — Key status
POST   /api/settings/keys/{name}                — Set key
DELETE /api/settings/keys/{name}                — Delete key
POST   /api/settings/keys/{name}/test           — Test key
GET    /api/settings/keys/{name}/reveal         — Reveal key
GET    /api/autopilot/summary                   — Full autopilot state
GET    /api/autopilot/candidates                — Ranked candidates
GET    /api/autopilot/learnings                 — Title/hook learnings
POST   /api/autopilot/config                    — Update config
POST   /api/autopilot/toggle                    — Enable/disable
POST   /api/autopilot/launch/{id}               — Launch candidate
GET    /api/niche/config                        — Niche setup status
POST   /api/niche/setup                         — Set niche
GET    /api/niche/channels                      — List competitor channels
POST   /api/niche/channels                      — Add channel
DELETE /api/niche/channels/{id}                 — Remove channel
POST   /api/niche/scrape                        — Trigger scrape
GET    /api/niche/scrape/status                 — Scrape progress
GET    /api/discovery/ideas                     — List discovery ideas
GET    /api/discovery/status                    — Discovery status
POST   /api/discovery/refresh                   — Generate new ideas
POST   /api/discovery/ideas/{id}/launch         — Launch idea as video
POST   /api/discovery/ideas/{id}/dismiss        — Dismiss idea
GET    /api/learnings                           — List learning patterns
POST   /api/learnings/extract                   — Extract from own videos
POST   /api/learnings/extract/{id}              — Extract from one video
POST   /api/learnings/analyze-titles            — Analyze competitor titles
POST   /api/learnings/analyze-transcripts       — Analyze competitor hooks
POST   /api/youtube/sync                        — Sync YouTube metrics
GET    /api/youtube/sync/status                 — Sync progress
GET    /api/channel-profile                     — Channel profile (legacy)
PUT    /api/channel-profile                     — Update profile (legacy)
GET    /api/projects/current                    — Current project
PUT    /api/projects/current                    — Update project
GET    /api/visual-styles                       — List visual styles
POST   /api/visual-styles                       — Create style
PUT    /api/visual-styles/{id}/activate         — Activate style
DELETE /api/visual-styles/{id}                  — Delete style
POST   /api/visual-styles/{id}/characters       — Add character
DELETE /api/visual-styles/{id}/characters/{cid} — Remove character
POST   /api/visual-styles/characters/generate   — Generate character image
POST   /api/visual-styles/analyze-image         — Analyze style from image
GET    /api/agents/stats                        — Agent pipeline stats
GET    /api/agents/videos                       — Agent results list
GET    /api/agents/videos/{id}                  — Agent result detail
POST   /api/agents/videos/{id}/run              — Run agent pipeline
GET    /api/agents/videos/{id}/task             — Agent task status
GET    /api/skills                              — Skills summary
GET    /api/skills/pipeline/order               — Pipeline skill order
GET    /api/skills/pipeline/cost                — Pipeline cost estimate
GET    /api/skills/{id}                         — Skill detail
```

## Frontend Page Summary
```
/                  — Dashboard (redirect or summary)
/dashboard         — Dashboard overview (stats, latest video, pipeline dist)
/pipeline          — Video list with status filters, discovery carousel
/pipeline/[videoId]— Video detail (tabbed: Info, Script, Voice, Storyboard, Visuals, Thumbnail, Render, Performance)
/competitors       — Competitor channels, candidate cards, scrape controls
/autopilot         — Autopilot toggle, config, YouTube sync
/analytics         — Analytics dashboard (stub — needs backend)
/settings          — API keys, project profile, visual styles
/profile           — User profile (stub — needs backend)
/review            — Pending review queue (scripts, images, thumbnails)
/visuals           — Visual review page
/storyboard        — Storyboard review page
/render            — Render page
```

## Task Queue Format
Structure: `{ version, current_tab, tabs: [{ id, name, path, status, tasks }] }`

Task fields:
- `id` — unique ID (e.g., `T1-001`)
- `title` — short description
- `role` — `frontend`, `backend`, or `qa`
- `status` — `pending`, `in_progress`, `done`, `blocked`
- `description` — detailed requirements
- `files` — array of files to modify (optional)
- `depends_on` — task ID that must complete first (optional)
- `verified` — boolean, set by QA after verification (optional)
- `started_at`, `completed_at` — timestamps (optional)

Tab status values: `pending`, `in_progress`, `complete`

Reading: parse JSON, find tab by `current_tab` or iterate `tabs[]`.
Writing: update task `status`, set `completed_at`, advance `current_tab` when tab is done.
