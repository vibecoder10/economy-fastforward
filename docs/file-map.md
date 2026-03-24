# Critical File Map

All paths relative to `skills/video-pipeline/`.

## Orchestrator (`orchestrator/`)

| File | What It Does |
|------|-------------|
| `pipeline.py` | Main status-driven router — reads Airtable status, dispatches to bots |
| `pipeline_control.py` | Slack bot — receives `!` commands, triggers pipeline stages |
| `pipeline_constants.py` | Airtable field names, status enums, table IDs |
| `pipeline_config.py` | Environment/config loading |
| `approval_watcher.py` | Monitors Slack for manual approvals |
| `webhook_server.py` | External webhook receiver |
| `handlers/admin_handlers.py` | Admin Slack commands (reset, clear, rebuild) |
| `handlers/style_handlers.py` | Style commands (!style, !visualstyle, !model) |
| `handlers/delete_handlers.py` | Delete/redo commands |

## Bot Folders (Orchestration Order)

| Folder | Stage | Key Files | What It Does |
|--------|-------|-----------|-------------|
| `competitor_scraper/` | Data gathering | `scraper.py`, `run.py` | Scrape competitor YouTube videos |
| `discovery/` | Data gathering | `scanner.py`, `bot.py`, `tracker.py` | Headline scanning + trending topics |
| `title_idea/` | Ideation | `idea_bot.py`, `trending_idea_bot.py`, `curiosity_gap/` | Create title ideas from competitor data |
| `research/` | Research | `agent.py` | Deep factual research via Claude |
| `script/` | Scripting | `run.py`, `story_bible.py`, `brief_translator/` | 6-act script writing (3000-4500 words) |
| `voice/` | Audio | `run.py` | Voice synthesis via ElevenLabs |
| `image_prompts/` | Prompts | `run.py`, `engine/` | 120 image prompts (3-style system) |
| `storyboard/` | Boards | `run.py`, `run_images.py`, `run_extract.py`, `bot.py` | 3x3 storyboard grids |
| `images/` | Generation | `run.py` | Scene images via Seed Dream 4.5 |
| `video_motion/` | Animation | `run_scripts.py`, `run_generate.py`, `animation/` | Video clips via Veo 3.1 |
| `sound/` | Audio | `run_design.py`, `run_effects.py`, `music_selector.py` | Sound FX + background music |
| `thumbnail/` | Thumbnail | `run.py`, `engine.py`, `selector.py`, `templates.py` | YouTube thumbnail via Nano Banana |
| `render/` | Render | `run.py`, `render_video.py`, `audio_sync/` | Remotion rendering + audio alignment |
| `upload/` | Upload | `run.py`, `youtube_uploader.py`, `seo_generator.py` | YouTube draft upload + SEO |

## Shared Infrastructure (`shared/`)

| File | Service |
|------|---------|
| `clients/airtable_client.py` | Airtable — record CRUD, status transitions |
| `clients/anthropic_client.py` | Claude AI — scripts, prompts, analysis, vision |
| `clients/image_client.py` | Kie.ai — images (Seed Dream 4.5), video (Veo 3.1), thumbnails (Nano Banana) |
| `clients/elevenlabs_client.py` | ElevenLabs via Wavespeed — voice synthesis |
| `clients/google_client.py` | Google Drive & Docs — file upload, folder management |
| `clients/slack_client.py` | Slack — notifications (non-blocking) |
| `clients/gemini_client.py` | Gemini Vision — thumbnail spec extraction |
| `clients/apify_client.py` | Apify — YouTube scraping |
| `clients/style_engine.py` | Internal — scene types, camera patterns, holographic system |
| `clients/sentence_utils.py` | Sentence splitting, duration estimation (173 WPM) |
| `clients/sound_client.py` | Sound effect/music selection |
| `profiles/visual/` | 4 visual styles (cinematic_illustration, dossier, hud, mannequin) |
| `profiles/script/` | Script voice profiles (power_doctrine_v1, v2) |
| `json_utils.py` | JSON parsing with 5-step fallback chain |
| `channel_profile.py` | Channel-specific model and profile settings |

## Analytics (`analytics/`)

| File | Purpose |
|------|---------|
| `performance_tracker.py` | Daily YouTube metrics sync (views, CTR, retention, snapshots) |
| `osiris/competitor_scraper.py` | Scrape ALL competitor videos to Competitor Videos table |
| `osiris/performance_analyzer.py` | 48h/7d post-mortem analysis → learnings extraction |
| `osiris/title_analyzer.py` | Title pattern analysis (structural vs semantic) |
| `osiris/learnings_engine.py` | Inject learned patterns into generation prompts |

## Autopilot (`autopilot/`)

| File | Purpose |
|------|---------|
| `autopilot.py` | Main loop (--status, --check-cycle, --force) |
| `autopilot_program.md` | Human-editable config (mission, cadence, weights, thresholds) |
| `core/confidence_scorer.py` | Score ideas using weighted signals (VPH, freshness, topic fit) |
| `core/cadence_manager.py` | Check if production slot available |
| `analysis/thumbnail_analyzer.py` | Claude Vision extraction from competitor thumbnails |
| `monitoring/ctr_monitor.py` | 6h/24h/48h YouTube Analytics checks |
| `learning/learning_extractor.py` | Extract patterns from 48h+ video performance |
| `memory/LEARNINGS.md` | Master summary (always loaded into context) |

## Video Rendering (`remotion-video/`)

| File | Purpose |
|------|---------|
| `src/Main.tsx` | Entry point — maps scenes from render_config.json |
| `src/Scene.tsx` | Core composition (~450 lines) — karaoke captions, Ken Burns, crossfades |
| `src/renderConfig.ts` | Loads render config from `getInputProps()` CLI props |
| `src/transcripts.ts` | Derives word-level timing from render_config |
| `src/segments.ts` | Builds image-to-audio timing segments |
| `remotion.config.ts` | Render settings: concurrency 3, swangle GL, 1GB cache |

## Infrastructure (`infra/`)

| File | Purpose |
|------|---------|
| `setup_cron.sh` | VPS cron job definitions |
| `bot_healthcheck.sh` | Auto-restart Slack bot if dead |
| `setup_swap.sh` | Create 4GB swap for Remotion on 8GB VPS |
| `setup_*.py` | Airtable/YouTube field setup scripts |
| `youtube_auth.py` | YouTube OAuth setup |
| `test_connections.py` | API connection verification |
