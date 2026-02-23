# Critical File Map

## Pipeline Core (`skills/video-pipeline/`)

| File | What It Does |
|------|-------------|
| `pipeline.py` | Main orchestrator - reads Airtable status, routes to correct bot |
| `pipeline_control.py` | Slack bot - receives commands, triggers pipeline stages |
| `approval_watcher.py` | Monitors for manual approvals in Slack |
| `discovery_scanner.py` | Finds trending topics for video ideas |
| `research_agent.py` | Deep research on topics using Claude |
| `render_video.py` | Calls Remotion to produce final MP4 |
| `run_*_bot.py` | Individual stage runners (9 scripts) |

## Bot Modules (`skills/video-pipeline/bots/`)

| Bot | Stage | Input | Output |
|-----|-------|-------|--------|
| `idea_bot.py` | Idea generation | YouTube URL or topic | 3 concept variations in Airtable |
| `trending_idea_bot.py` | Trend discovery | YouTube trending scrape | Ideas modeled from viral patterns |
| `idea_modeling.py` | Format extraction | Trending titles | Variable decomposition + format library |
| `script_bot.py` | Scriptwriting | Concept from Ideas table | 6-act, 3000-4500 word script |
| `voice_bot.py` | Voice synthesis | Script text | MP3 narration via ElevenLabs |
| `image_prompt_bot.py` | Prompt engineering | Script scenes | 6 image prompts per scene (120 total) |
| `image_bot.py` | Image generation | Image prompts | PNG images via Seed Dream 4.5 |
| `video_script_bot.py` | Motion prompts | Images + script | Animation motion descriptions |
| `video_bot.py` | Animation | Images + motion prompts | Video clips via Veo 3.1 Fast |
| `thumbnail_bot.py` | Thumbnail | Video title + concept | YouTube thumbnail via Nano Banana Pro |
| `seo_generator.py` | SEO metadata | Title + script | YouTube description, tags, hashtags |
| `youtube_uploader.py` | Upload | Drive video + Airtable record | YouTube unlisted draft + update Airtable |

## API Clients (`skills/video-pipeline/clients/`)

| Client | Service | Key Methods |
|--------|---------|-------------|
| `anthropic_client.py` | Claude AI | `generate()`, `generate_beat_sheet()`, `write_scene()`, `generate_image_prompts()`, `generate_video_prompt()`, `segment_scene_into_concepts()` |
| `airtable_client.py` | Airtable | `get_ideas_by_status()`, `create_idea()`, `create_script_record()`, `update_image_record()`, `update_image_animation_fields()` |
| `elevenlabs_client.py` | ElevenLabs (via Wavespeed) | `generate_and_wait()` (create task + poll + return audio URL) |
| `image_client.py` | Kie.ai | `generate_scene_image()` (Seed Dream 4.5), `generate_video()` (Grok Imagine), `generate_video_veo()` (Veo 3.1), `upgrade_veo_to_1080p()` |
| `google_client.py` | Drive & Docs | `upload_file()`, `create_folder()`, `download_file_to_local()`, `make_file_public()`, `create_document()` |
| `gemini_client.py` | Gemini Vision | `generate_thumbnail_spec()` (extracts style elements from reference image) |
| `slack_client.py` | Slack | `send_message()`, `notify_*()` (pipeline stage notifications, non-blocking) |
| `apify_client.py` | YouTube scraping | `search_trending_videos()`, `analyze_trending_patterns()` |
| `style_engine.py` | Internal | `STYLE_ENGINE_PREFIX/SUFFIX`, `SceneType` enum, `get_documentary_pattern()`, `get_camera_motion()` |
| `sentence_utils.py` | Internal | `split_into_sentences()`, `estimate_sentence_duration()` (173 WPM average) |

## Content Generation (`skills/video-pipeline/`)

| Module | Purpose |
|--------|---------|
| `image_prompt_engine/` | 3-style cinematic prompt system (Dossier 60%, Schema 22%, Echo 18%) |
| `brief_translator/` | Script generation: `script_generator.py` (6-act, 3000-4500 words, Claude Sonnet, 8000 token budget), `scene_expander.py` (20 scenes with narration + visual seeds), `scene_validator.py` (count, format, word distribution), `pipeline_writer.py` (maps brief to pipeline schema), `supplementer.py` (narrative arcs, character dossiers) |
| `audio_sync/` | `transcriber.py` (Whisper API), `aligner.py` (3-strategy matching), `config.py` (timing constraints), `ken_burns_calculator.py` (motion presets), `render_config_writer.py` (Remotion JSON output), `timing_adjuster.py`, `transition_engine.py` |
| `thumbnail_generator/` | Formula-based YouTube thumbnails with 14+ title patterns and 3 template variants |
| `animation/` | Veo 3.1 Fast video clip generation |

## Video Rendering (`remotion-video/`)

| File | Purpose |
|------|---------|
| `src/Main.tsx` | Entry point - maps scenes from render_config.json |
| `src/Scene.tsx` | Core scene composition (karaoke captions, Ken Burns motion, crossfades) |
| `src/segments.ts` | Image-to-audio timing logic |
| `src/transcripts.ts` | Word-level transcript loading |
| `src/captions/Scene [1-20].json` | Per-scene word timestamps |

## Infrastructure

| File | Purpose |
|------|---------|
| `setup_cron.sh` | Installs 4 cron jobs (discovery, queue, healthcheck, approvals) |
| `bot_healthcheck.sh` | Auto-restarts Slack bot if dead |
| `setup_swap.sh` | Creates 4GB swap for Remotion rendering on 8GB VPS |
| `MANUAL_STEP.md` | VPS deployment instructions |
