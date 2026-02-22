# Economy FastForward - Agent Operating Manual

> AI-powered documentary video production pipeline.
> Topic in, 25-minute video out.

---

## Workflow Orchestration

### 1. Plan Node Default

- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately - don't keep pushing
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

### 2. Subagent Strategy

- Use subagents liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- For complex problems, throw more compute at it via subagents
- One task per subagent for focused execution

### 3. Self-Improvement Loop

- After ANY correction from the user: update `tasks/lessons.md` with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops
- Review `tasks/lessons.md` at session start for relevant project context

### 4. Verification Before Done

- Never mark a task complete without proving it works
- Diff behavior between main and your changes when relevant
- Ask yourself: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness

### 5. Demand Elegance (Balanced)

- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes - don't over-engineer
- Challenge your own work before presenting it

### 6. Autonomous Bug Fixing

- When given a bug report: just fix it. Don't ask for hand-holding
- Point at logs, errors, failing tests - then resolve them
- Zero context switching required from the user
- Go fix failing CI tests without being told how

---

## Task Management

1. **Plan First**: Write plan to `tasks/todo.md` with checkable items
2. **Verify Plan**: Check in before starting implementation
3. **Track Progress**: Mark items complete as you go
4. **Explain Changes**: High-level summary at each step
5. **Document Results**: Add review section to `tasks/todo.md`
6. **Capture Lessons**: Update `tasks/lessons.md` after corrections

---

## Core Principles

- **Simplicity First**: Make every change as simple as possible. Impact minimal code.
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
- **Minimal Impact**: Changes should only touch what's necessary. Avoid introducing bugs.

---

# Project Architecture

## System Overview

This is a **status-driven, multi-stage video production pipeline** that transforms research topics into 25-minute documentary videos. The entire pipeline is orchestrated through Airtable status fields, with each bot advancing the status after completing its work.

```
Research/Idea ──► Script ──► Voice ──► Image Prompts ──► Images ──► Video Scripts
    ──► Video Generation ──► Thumbnail ──► Render ──► Upload
```

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Orchestration | Python 3.11+ (async) | Pipeline control, bot execution |
| Database | Airtable (3 tables) | Status tracking, asset metadata, source of truth |
| AI - Scripts | Claude (Anthropic) Sonnet | Research, scriptwriting, prompt engineering |
| AI - Images | Kie.ai (Seed Dream 4.5) | Still image generation |
| AI - Animation | Kie.ai (Veo 3.1 Fast) | Image-to-video clips |
| AI - Thumbnails | Kie.ai (Nano Banana Pro) | YouTube thumbnail generation |
| AI - QC | Gemini Vision | Image quality scoring |
| Voice | ElevenLabs | Narrator voice synthesis |
| Transcription | OpenAI Whisper API | Word-level audio timestamps |
| Video Render | Remotion 4.0 (React/TS) | Final MP4 composition with karaoke captions |
| Storage | Google Drive | Media file storage (images, audio, video) |
| Control | Slack Bot | Remote pipeline control (`!status`, `!run`, `!update`) |
| Frontend | Next.js 14 (StoryEngine) | Research discovery UI |

## Critical File Map

### Pipeline Core (`skills/video-pipeline/`)
| File | What It Does |
|------|-------------|
| `pipeline.py` | Main orchestrator - reads Airtable status, routes to correct bot |
| `pipeline_control.py` | Slack bot - receives commands, triggers pipeline stages |
| `approval_watcher.py` | Monitors for manual approvals in Slack |
| `discovery_scanner.py` | Finds trending topics for video ideas |
| `research_agent.py` | Deep research on topics using Claude |
| `render_video.py` | Calls Remotion to produce final MP4 |
| `run_*_bot.py` | Individual stage runners (9 scripts) |

### Bot Modules (`skills/video-pipeline/bots/`)
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

### API Clients (`skills/video-pipeline/clients/`)
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

### Content Generation (`skills/video-pipeline/`)
| Module | Purpose |
|--------|---------|
| `image_prompt_engine/` | 3-style cinematic prompt system (Dossier 60%, Schema 22%, Echo 18%) |
| `brief_translator/` | Script generation: `script_generator.py` (6-act, 3000-4500 words, Claude Sonnet, 8000 token budget), `scene_expander.py` (20 scenes with narration + visual seeds), `scene_validator.py` (count, format, word distribution), `pipeline_writer.py` (maps brief to pipeline schema), `supplementer.py` (narrative arcs, character dossiers) |
| `audio_sync/` | `transcriber.py` (Whisper API), `aligner.py` (3-strategy matching), `config.py` (timing constraints), `ken_burns_calculator.py` (motion presets), `render_config_writer.py` (Remotion JSON output), `timing_adjuster.py`, `transition_engine.py` |
| `thumbnail_generator/` | Formula-based YouTube thumbnails with 14+ title patterns and 3 template variants |
| `animation/` | Veo 3.1 Fast video clip generation |

### Video Rendering (`remotion-video/`)
| File | Purpose |
|------|---------|
| `src/Main.tsx` | Entry point - maps scenes from render_config.json |
| `src/Scene.tsx` | Core scene composition (karaoke captions, Ken Burns motion, crossfades) |
| `src/segments.ts` | Image-to-audio timing logic |
| `src/transcripts.ts` | Word-level transcript loading |
| `src/captions/Scene [1-20].json` | Per-scene word timestamps |

### Infrastructure
| File | Purpose |
|------|---------|
| `setup_cron.sh` | Installs 4 cron jobs (discovery, queue, healthcheck, approvals) |
| `bot_healthcheck.sh` | Auto-restarts Slack bot if dead |
| `setup_swap.sh` | Creates 4GB swap for Remotion rendering on 8GB VPS |
| `MANUAL_STEP.md` | VPS deployment instructions |

---

## Status-Driven Pipeline (CRITICAL)

The pipeline is a **state machine** driven by the `Status` field in the Airtable Idea Concepts table. Every bot reads the current status, does its work, then advances the status.

### Three Entry Paths Into the Pipeline
1. **Discovery Scanner** (`discovery_scanner.py`): Scans Reuters, AP, Bloomberg, FT, WSJ headlines → filters through Machiavellian lens → generates 2-3 ideas → posts to Slack → user reacts with emoji (1/2/3) → writes to Airtable as "Approved"
2. **Idea Bot** (`bots/idea_bot.py`): Takes YouTube URL or concept → generates 3 viral concept variations → writes as "Idea Logged"
3. **Trending Idea Bot** (`bots/trending_idea_bot.py`): Scrapes YouTube trending → models from format library → writes as "Idea Logged"

### Status Flow
```
Idea Logged
  ↓ [Manual approval in Airtable UI]
Approved
  ↓ [ApprovalWatcher auto-triggers Research Agent → 7-prompt deep research cycle]
Ready For Scripting
  ↓ [Brief Translator: validates research → generates 6-act script → expands 20-30 scenes]
Ready For Voice
  ↓ [Voice Bot synthesizes narration per scene via ElevenLabs]
Ready For Image Prompts
  ↓ [Styled Image Prompts: expand scenes → 4-7 images each → styled 120-150 word prompts]
Ready For Images
  ↓ [Image Bot generates images via Seed Dream 4.5]
Ready For Video Scripts
  ↓ [Video Script Bot generates motion prompts]
Ready For Video Generation
  ↓ [Video Bot animates via Veo 3.1 Fast — MANUAL, cost-controlled via --animate]
Ready For Thumbnail
  ↓ [Thumbnail Bot generates YouTube thumbnail via Nano Banana Pro]
Ready To Render
  ↓ [Remotion renders final MP4]
Done
  ↓ [YouTube upload — currently manual]
Rendered / Uploaded (Draft)
```

### Rules for Status Changes

- **NEVER skip a status**. Each status gates the next stage. If you jump from "Ready For Voice" to "Ready For Images", the image prompts won't exist.
- **ALWAYS update status via Airtable client** after a bot completes. Never leave a record in a stale status.
- **Check status BEFORE processing**. Bots must verify the record is in the expected status before starting work.
- **Failed records**: Set status to `Failed - [Stage Name]` with error details in the `Notes` field. Don't leave records stuck in an intermediate state.
- **Resume safety**: The status-driven design means any interruption (crash, rate limit, network failure) can be resumed by simply re-running the pipeline. It will pick up from the current status.

### CLI Commands (Quick Reference)
```bash
# Discovery & Ideas
python discovery_scanner.py                          # Scan headlines → Slack
python pipeline.py --idea "URL/concept"              # URL analysis → 3 concepts
python pipeline.py --trending                        # Trending YouTube analysis

# Research
python research_agent.py --topic "topic"             # Deep 7-prompt research
python approval_watcher.py --daemon                  # Auto-research approved ideas

# Pipeline Control
python pipeline.py                                   # Auto-run next available step
python pipeline.py --full "URL"                      # End-to-end: Idea → Render
python pipeline.py --from-stage scripting            # Resume from specific stage
python pipeline.py --styled-prompts                  # Generate image prompts only
python pipeline.py --animate "Video Title"           # Animation (cost-controlled)
python pipeline.py --animate "Video Title" --estimate # Cost estimate only
```

---

## Airtable Schema

### Idea Concepts Table (Source of Truth for NEW ideas)
Core fields (always written):
- `Status`, `Video Title`, `Hook Script`, `Past Context`, `Present Parallel`, `Future Prediction`
- `Thumbnail Prompt`, `Writer Guidance`, `Original DNA` (JSON backup), `Source`

Rich fields (written by research):
- `Framework Angle`, `Headline`, `Timeliness Score`, `Audience Fit Score`, `Content Gap Score`
- `Source URLs`, `Executive Hook`, `Thesis`, `Date Surfaced`
- `Research Payload` (JSON), `Thematic Framework`

Optional fields:
- `Reference URL`, `Idea Reasoning`, `Source Views`, `Source Channel`
- `Google Drive Folder ID`, `Thumbnail`, `Pipeline Mode`, `Notes`
- `Upload Status`, `YouTube Video ID`, `YouTube URL`

### Scripts Table
- `Scene`, `Scene text`, `Title`, `Voice ID`
- `Script Status`: "Create" → "Finished"
- `Voice Status`, `Voice Over` (attachment URL)
- `Sources` (show notes for YouTube description)

### Images Table
- `Scene`, `Image Index`, `Sentence Text`, `Image Prompt`, `Shot Type`
- `Video Title`, `Aspect Ratio`, `Status`: "Pending" → "Done"
- `Image` (attachment), `Video`, `Video Prompt`
- Animation: `Hero Shot`, `Video Clip URL`, `Animation Status`, `Video Duration`

### Known Schema Issues (See ANIMATION_SYSTEM_REVIEW.md Feature 4)
- **CRITICAL**: Tables joined by string matching (`Title` = `Video Title`), NOT linked records. Typos break relationships.
- Images table has 3 overlapping status fields (`Status`, `Video Status`, `Animation Status`). Update ALL relevant ones.
- `Sentence Index` and `Image Index` are the same value with different names.
- Thumbnail field format is inconsistent - code tries 3 field name/format combos as fallbacks.

### Airtable Error Recovery Pattern (Used Everywhere)
The codebase uses graceful field degradation when writing to Airtable:
```
Try: Create with all fields
Catch UnknownField → extract bad field from error → retry without it (loop)
Finally: If still failing → create with core fields only → update rich fields individually
```
**Follow this pattern** when adding new Airtable writes. Never let a single bad field kill the whole record creation.

---

## API Integration Patterns

### Async Pattern (Standard)
All bots use async Python. Follow this pattern:
```python
async def process_record(record_id: str):
    record = await airtable.get_record(record_id)
    # ... do work ...
    await airtable.update_record(record_id, {"Status": "Next Status"})
```

### Retry Pattern
Use `tenacity` for API retries. All external APIs (Kie.ai, ElevenLabs, Google Drive) are flaky:
```python
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=30))
async def call_external_api(...):
```

### Image Generation (Kie.ai)
- Task-based: create task → poll for completion → download result
- Poll status codes: 0=Queue, 1=Running, 2=Success, 3=Failed
- Retry up to 3 times on failure with different seeds
- Models: `seedream/4.5-edit` (scene images with reference), `nano-banana-pro` (thumbnails/text), `grok-imagine/image-to-video` (animation), `veo3_fast`/`veo3` (advanced video)
- **Proxy fallback**: On 500 errors for image URLs, the client downloads the image, re-uploads to Google Drive, makes it public, and retries with the Drive URL. Follow this pattern for resilience.
- Veo 3.1 supports 1080p upgrade via `upgrade_veo_to_1080p()` (polls separately, 90s retry if still processing)

### Voice Synthesis (ElevenLabs via Wavespeed)
- Voice ID: `G17SuINrv2H9FC6nvetn` (configured in .env)
- Uses Wavespeed v3 API endpoint (ElevenLabs turbo), not direct ElevenLabs API
- Polling: create task → poll up to 30 times at 5s intervals → return audio URL
- Upload to Google Drive after generation

### Audio Alignment (Whisper → Fuzzy Match)
- Whisper API returns word-level timestamps
- 3-strategy alignment: full-excerpt fuzzy match → anchor-word fallback → proportional estimate
- Minimum 60% similarity threshold for fuzzy matching
- Timing constraints: MIN_DISPLAY 3s, MAX_DISPLAY 18s, CROSSFADE 0.4s, ACT_TRANSITION_BLACK 1.5s

### Google APIs (Drive & Docs)
- Exponential backoff on 503 (MAX_RETRIES=3, INITIAL_BACKOFF=1.0s)
- Docs API can be unavailable - code returns `GoogleDocsUnavailableError` gracefully
- Drive URLs must be converted to direct download format for Airtable attachments
- Airtable attachment URLs expire in 2 hours, but Drive URLs are permanent

### YouTube Upload
- YouTube API quota: 10,000 units/day, ~1,600 units per upload (max ~6 uploads/day)
- Always upload as **unlisted** draft, never public
- Thumbnail upload failures are warnings (non-blocking) - the video still uploads

### JSON Response Parsing (Universal Pattern)
All Claude/Gemini responses use this fallback chain:
```
Try: json.loads(response) directly
Catch: Remove markdown fences (```json ... ```), try again
Catch: Extract JSON substring, try again
Catch: Fix common issues (trailing commas, unescaped quotes), try again
Catch: Regex extraction from raw text
Catch: Return defaults/fallback
```
**Follow this pattern** when parsing any AI-generated JSON. Never assume clean JSON output.

### Polling Pattern (Universal)
All async operations (voice, images, videos) use:
```python
# Wait before first poll (API needs processing time)
await asyncio.sleep(initial_wait)  # 5s for images, varies by service
for attempt in range(max_attempts):
    status = await check_status(task_id)
    if status == SUCCESS: return result
    if status == FAILURE: return None
    await asyncio.sleep(poll_interval)
return None  # Timeout
```

---

## Data Architecture

### Video DNA (Core Data Structure)
Every idea carries metadata DNA that flows through the entire pipeline:
```python
{
    "source_type": "youtube_url" | "concept" | "trending",
    "original_dna": str,          # JSON snapshot of source data
    "reference_url": str,          # Source URL
    "viral_title": str,
    "hook_script": str,            # First 15 seconds
    "narrative_logic": {
        "past_context": str,       # Historical setup
        "present_parallel": str,   # Current situation
        "future_prediction": str   # What happens next
    },
    "thumbnail_visual": str,
    "writer_guidance": str         # Tone and approach notes
}
```
**All content uses Past → Present → Future framing.** This is the Economy FastForward brand voice. Don't break this structure.

### Research Payload (14-Field JSON)
Output by `research_agent.py`, stored in `Research Payload` field, consumed by brief_translator:
```python
{
    "headline": str,              # Compelling video title
    "thesis": str,                # Core argument (2-3 sentences)
    "executive_hook": str,        # 15-second opening hook
    "fact_sheet": str,            # 10+ specific facts with numbers/dates
    "historical_parallels": str,  # 3+ events with dates, figures, outcomes
    "framework_analysis": str,    # Analytical lens (Machiavellian, systems thinking, etc.)
    "character_dossier": str,     # 3+ key figures (name, role, actions, visuals)
    "narrative_arc": str,         # What happened → Why matters → What's next
    "counter_arguments": str,     # Strongest opposing arguments + rebuttals
    "visual_seeds": str,          # 5+ visual concepts for image generation
    "source_bibliography": str,   # Key sources and reports
    "themes": str,                # 3+ intellectual frameworks
    "psychological_angles": str,  # Viewer hooks (fears, aspirations, curiosities)
    "narrative_arc_suggestion": str  # 6-act structure with emotional arcs
}
```

### Brief Translator Validation
Before scripting, the brief translator validates research across 8 criteria:
- Hook strength, Fact density, Framework depth, Historical parallel richness
- Character visualizability, Implication specificity, Visual variety, Structural completeness
- Tolerance: Up to 1 FAIL + 4 WEAK still passes (if research_enriched=true)
- Runs targeted gap-filling via `supplementer.py` if validation fails

### Scene JSON Structure
Output by brief_translator, defines every scene for downstream consumption:
```python
{
    "total_acts": 6, "total_scenes": 25,
    "acts": [{
        "act_number": 1, "act_title": "The Hook",
        "time_range": "0:00-1:30", "word_target": 225,
        "scenes": [{
            "scene_number": 1, "narration_text": "...",
            "duration_seconds": 36,
            "visual_style": "dossier|schema|echo",
            "composition": "wide|medium|closeup|...",
            "ken_burns": "slow zoom in|out|pan left|right|...",
            "mood": "tension|revelation|urgency"
        }]
    }]
}
```
Duration calculation: `word_count / 2.5 wps = seconds`. Images per scene: `ceil(duration / 9)`.

### Trending Idea Format Library
The v2 idea engine decomposes viral titles into typed variables:
- `number`, `authority_qualifier`, `core_topic`, `extreme_benefit`, `specific_mechanism`, `time_anchor`, `target_audience`
- 10 psychological triggers: longevity, fear, practical_value, curiosity_gap, authority, urgency, contrarian, aspiration, outrage, scale
- Format library is **persisted across runs** in a config file. New formats accumulate over time.

### Slack Notifications
Every pipeline stage sends Slack notifications. They are **non-blocking** (wrapped in try/except). Never let a Slack failure kill a pipeline run. The notification methods are:
`notify_pipeline_start()`, `notify_idea_generated()`, `notify_script_start/done()`, `notify_voice_start/done()`, `notify_image_prompts_start/done()`, `notify_images_start/done()`, `notify_thumbnail_done()`, `notify_pipeline_complete()`, `notify_youtube_draft_ready()`, `notify_error()`

---

## Cost Awareness

Every API call costs money. Be aware of these costs when building features:

| Operation | Cost | Volume per Video |
|-----------|------|-----------------|
| Image generation (Seed Dream 4.5) | $0.025/image | 120 images = $3.00 |
| Video clip (Veo 3.1 Fast) | $0.30/clip | 20-40 clips = $6-12 |
| Thumbnail (Nano Banana Pro) | $0.075/image | 1-3 = $0.075-0.225 |
| Voice synthesis (ElevenLabs) | ~$0.30/1000 chars | ~$1-2 per video |
| Claude API (Sonnet) | ~$0.01-0.05/call | ~20-30 calls = $0.30-1.50 |
| Whisper transcription | ~$0.006/min | ~$0.15 per video |
| **Total per video** | | **~$11-19** |

**Rules:**
- Never add unnecessary API calls in loops. Batch where possible.
- When testing, use `--dry-run` flags or mock API responses. Don't burn $15 on a test run.
- Log costs when introducing new API integrations. Add to this table.
- Budget alerts exist at 80% threshold (animation pipeline).

---

## Image Prompt Engine (3-Style System)

The visual system uses 3 cinematic styles distributed across 6 narrative acts:

| Style | Weight | Look | When Used |
|-------|--------|------|-----------|
| **Dossier** | 60% | Photorealistic, Rembrandt lighting, accent colors | Investigation, corporate, power |
| **Schema** | 22% | Data overlay, glowing nodes, HUD aesthetics | Systems, networks, data |
| **Echo** | 18% | Painterly, historical, candlelit | Backstory, historical context |

### Prompt Architecture (4 Layers)
1. `YOUTUBE_STYLE_PREFIX` - Cinematic photorealism foundation
2. Scene description - Narrative content from script
3. `COMPOSITION_DIRECTIVES` - Camera angles (7 types cycle for variety)
4. `STYLE_SUFFIXES` - Style-specific atmosphere

### Two Style Systems (YouTube vs Animation)
- **YouTube pipeline** (`image_prompt_engine/`): Photorealistic cinematic (Dossier/Schema/Echo)
- **Animation pipeline** (`clients/style_engine.py`): 3D clay render mannequin style (faceless, matte gray, golden chest glow)
- The style engine has 9 SceneTypes: WIDE_ESTABLISHING, ISOMETRIC_DIORAMA, MEDIUM_HUMAN_STORY, CLOSE_UP_VIGNETTE, DATA_LANDSCAPE, SPLIT_SCREEN, PULL_BACK_REVEAL, OVERHEAD_MAP, JOURNEY_SHOT
- `get_documentary_pattern()` returns camera rotation for N images
- Image prompt word count: 75-110 words per prompt (validated)

### Rules
- Max 4 consecutive scenes with the same style (anti-clustering)
- 7 composition types cycle: wide, medium, closeup, environmental, portrait, overhead, low_angle
- Ken Burns motion is assigned based on composition type
- 6 images per scene, 20 scenes = 120 images per video

---

## Remotion Rendering System

### How It Works
1. `render_config.json` defines per-scene timing, Ken Burns params, transitions
2. `Main.tsx` maps scenes to Remotion `<Sequence>` components
3. `Scene.tsx` handles: image display, audio sync, karaoke captions, crossfades, Ken Burns motion
4. Captions are word-level karaoke: current word = yellow (#FFE135), past = white, future = gray
5. 6 continuous motion patterns rotate across scenes (push-in, pull-out, pan-left, pan-right, rise, sink)

### Rendering Commands
```bash
cd remotion-video && npm run studio   # Preview
cd remotion-video && npm run render   # Render final MP4 to out/final.mp4
```

### Rules
- Scene.tsx is ~450 lines. Be surgical when editing - test changes in studio first.
- Word-level transcript data lives in `src/captions/Scene [1-20].json`.
- The 4GB swap file is required for rendering on the 8GB VPS. Without it, Remotion OOMs.
- `segmentData.ts` is gitignored - it's generated, not committed.

---

## Infrastructure & Deployment

### Production VPS
- Path: `/home/clawd/projects/economy-fastforward/`
- 8GB RAM + 4GB swap (for Remotion rendering)
- Auto-pulls from GitHub on every cron run (`git pull --ff-only`)

### Cron Schedule (US/Pacific)
| Time | Job | Timeout |
|------|-----|---------|
| 5:00 AM | `pipeline.py --discover` (idea discovery) | 10 min |
| 8:00 AM | `pipeline.py --run-queue` (process pipeline) | 4 hours |
| Every 15 min | `bot_healthcheck.sh` (restart Slack bot if dead) | - |
| Every 30 min | `approval_watcher.py` (check for approvals) | 10 min |

### Slack Bot Commands
`!status`, `!run`, `!update`, `!logs`, `!health`, `!queue`, `!approve`, `!reject`

### Rules
- Code pushed to `main` auto-deploys via the hourly `git pull --ff-only`. Don't push broken code to main.
- The Slack bot (`pipeline_control.py`) runs as a background process. PID tracked at `/tmp/pipeline-bot.pid`.
- Healthcheck auto-restarts the bot and sends Slack alert. Don't assume the bot is always running.
- All logs go to `/tmp/pipeline-*.log` on VPS. Reference these when debugging production issues.

---

## Common Failure Modes & Fixes

| Failure | Symptoms | Root Cause | Fix |
|---------|----------|-----------|-----|
| Images don't match script | Visual disconnect from narration | Prompt didn't capture scene intent | Check `image_prompt_engine/prompt_builder.py`, improve scene-to-prompt mapping |
| Audio alignment fails | Scenes have wrong timing, 3s uniform durations | Whisper transcription error or fuzzy match below 60% | Check `audio_sync/aligner.py`, lower threshold or improve anchor-word matching |
| Airtable record stuck | Status never advances | Bot crashed mid-processing, status not updated | Manually set status to correct value in Airtable, check bot logs |
| Image generation returns None | Empty images in Airtable | Kie.ai API timeout or rate limit | Check `clients/image_client.py` retry logic, verify API key |
| Remotion OOM | Render crashes silently | Not enough RAM | Run `setup_swap.sh`, verify 4GB swap exists |
| Slack bot unresponsive | Commands get no response | Process died, healthcheck hasn't run yet | Check `/tmp/pipeline-bot.pid`, restart `pipeline_control.py` |
| Google Drive upload fails | Assets missing from Drive | OAuth token expired | Refresh token in `.env`, check `clients/google_client.py` |
| Thumbnail field not updating | Thumbnail appears generated but not linked | Field name/format mismatch in Airtable | Known issue - code tries 3 fallback formats. Check `airtable_client.py` |
| Style clustering | Multiple consecutive scenes look identical | Sequencer anti-clustering not triggering | Check `image_prompt_engine/sequencer.py`, verify max 4 consecutive same-style rule |
| Airtable field mismatch | `UnknownField` error on create | New field added to code but not to Airtable UI | Add the field in Airtable first, then update code. The graceful degradation pattern will drop unknown fields. |
| YouTube quota exceeded | 403 on upload | >6 uploads/day (10,000 units/day, ~1,600 per upload) | Wait until next day. Quota resets at midnight Pacific. |
| Veo 3.1 still processing | `upgrade_veo_to_1080p()` returns None | HD upscale takes longer than expected | Retry after 90 seconds. The API returns the URL once processing finishes. |
| ElevenLabs timeout | Voice generation poll hits 30 attempts | Audio too long or API backlogged | Increase `max_attempts` in `elevenlabs_client.py` or split text into smaller chunks |
| Google Docs unavailable | 503 on document creation | Google Docs API intermittent outage | Code returns `GoogleDocsUnavailableError` gracefully. Non-blocking - pipeline continues without Docs backup. |

---

## Development Patterns

### When Adding a New Bot Stage
1. Create bot in `bots/` following existing patterns (async, Airtable status read/write)
2. Add status transition to `pipeline.py` router
3. Add `run_*_bot.py` script for standalone execution
4. Add Slack command in `pipeline_control.py` if user-triggerable
5. Update this document's status flow

### When Modifying Airtable Schema
1. Update field in Airtable UI first
2. Update `clients/airtable_client.py` field references
3. Update any bots that read/write the changed field
4. Test with a single record before running full pipeline
5. Document the change in `ANIMATION_SYSTEM_REVIEW.md`

### When Adding a New API Integration
1. Create client in `clients/` with async methods and retry logic
2. Add API key to `.env.example` with description
3. Add cost per call to the Cost Awareness table above
4. Add error handling for rate limits (429) and timeouts
5. Test with a single call before integrating into pipeline

### When Editing Remotion Components
1. Run `npm run studio` first to see current state
2. Make changes and verify in studio preview
3. Test with `npm run render` on a short clip before full render
4. Scene.tsx is the most critical file - be surgical, don't refactor unless asked

### Python Code Style
- Async/await everywhere. Don't introduce sync blocking calls.
- Use `httpx` for HTTP (async), not `requests`.
- Use `pydantic` for data models where structured data is involved.
- Use `python-dotenv` for env vars. Load at module level.
- Use `rich` for console output in CLI tools.
- Follow existing error handling: log error, update Airtable status to failed, continue to next record.

---

## Testing Strategy

### Before Declaring Any Pipeline Change "Done"
1. **Unit test**: Does the function produce correct output for known input?
2. **Integration test**: Does it correctly read from and write to Airtable?
3. **Single-record test**: Run the bot against ONE real Airtable record
4. **Dry run**: Process a full video with `--dry-run` if available
5. **Cost check**: Will this change increase per-video cost? By how much?

### Test Locations & Coverage (170 tests passing as of Feb 2026)
```
image_prompt_engine/tests/    77 tests  (style system, prompt building, sequencing)
brief_translator/tests/       67 tests  (validation, scene expansion, pipeline writing)
tests/test_pipeline_integration.py  26 tests  (end-to-end integration)
audio_sync/tests/             —         (alignment, timing, Ken Burns)
thumbnail_generator/          —         (generation tests)
```

### Running Tests
```bash
cd skills/video-pipeline && python -m pytest image_prompt_engine/tests/
cd skills/video-pipeline && python -m pytest brief_translator/tests/
cd skills/video-pipeline && python -m pytest tests/test_pipeline_integration.py
cd skills/video-pipeline && python -m pytest audio_sync/tests/
```

### Key Integration Tests Verify
- Research output has all validator fields
- Brief has all script generator fields
- Scenes have required fields + visual identity markers
- All prompts end with "16:9"
- Ken Burns has 3+ unique directions, pan directions alternate
- Visual identity distribution matches targets (60D/22S/18E)
- Status chain is valid, no mismatches
- Scene dir is project-relative (not hardcoded VPS path)

---

## Session Startup Checklist

Every new session, before doing any work:

1. Read `tasks/lessons.md` for patterns to avoid
2. Read `tasks/todo.md` for current sprint state
3. Check `ANIMATION_SYSTEM_REVIEW.md` for roadmap context
4. If working on pipeline changes: read the relevant bot + client files first
5. If working on Remotion: run `npm run studio` to see current state
6. If debugging production: check VPS logs via `!logs` Slack command

---

## Roadmap Awareness (from ANIMATION_SYSTEM_REVIEW.md)

When the user asks for features, be aware of these planned improvements:

| Priority | Feature | Status |
|----------|---------|--------|
| HIGH | Character Consistency Engine (BYOC) | Not started |
| HIGH | One-Shot `!create` Pipeline (Product Mode) | Not started |
| HIGH | Style Locking via Golden Frame | Not started |
| DONE | Auto-Pull from GitHub on Cron | Shipped |
| DONE | Veo 3.1 Fast Integration | Shipped |
| MEDIUM | Airtable Schema Optimization | Not started |
| MEDIUM | Pipeline Health Dashboard & Self-Healing | Not started |
| MEDIUM | Smart Image-to-Animation Bridging | Not started |
| MEDIUM | Prompt A/B Testing & Quality Scoring | Not started |
| LOW | Multi-Voice & Sound Design Layer | Not started |

If a task relates to one of these features, reference the detailed spec in `ANIMATION_SYSTEM_REVIEW.md` before implementing. Don't reinvent what's already been designed.

---

## Environment Variables Reference

See `.env.example` for all required variables. Critical ones:

| Variable | Service | Notes |
|----------|---------|-------|
| `ANTHROPIC_API_KEY` | Claude AI | Scripts, prompts, analysis |
| `AIRTABLE_API_KEY` | Airtable | Personal access token |
| `AIRTABLE_BASE_ID` | Airtable | `appCIcC58YSTwK3CE` |
| `ELEVENLABS_API_KEY` | ElevenLabs | Voice synthesis |
| `ELEVENLABS_VOICE_ID` | ElevenLabs | `G17SuINrv2H9FC6nvetn` |
| `OPENAI_API_KEY` | Whisper API | Audio transcription |
| `KIE_AI_API_KEY` | Kie.ai | Images, video, thumbnails |
| `GOOGLE_CLIENT_ID/SECRET/REFRESH_TOKEN` | Google | Drive & Docs OAuth |
| `GOOGLE_DRIVE_FOLDER_ID` | Google Drive | Parent folder for all projects |
| `SLACK_BOT_TOKEN` | Slack | Bot control interface |
| `SLACK_CHANNEL_ID` | Slack | `C0A9U1X8NSW` |

### Rules
- Never commit `.env`. It's gitignored.
- When adding new env vars, ALWAYS update `.env.example` with a description.
- The Whisper dependency was removed from requirements.txt (saved 2GB on VPS). We use the API, not local Whisper.

---

## What Makes a 100x Agent on This Project

1. **Understand the state machine.** Every bug, every feature, every change touches the status flow. If you don't know which status you're in, you'll break the pipeline.

2. **Airtable is the source of truth.** Not local files, not logs, not git. Airtable. When in doubt, read the record.

3. **Cost is real.** Every image costs $0.025. Every video clip costs $0.30. A careless loop can burn $50. Always think about cost impact.

4. **Test on one record first.** Never run a change against the full pipeline without testing on a single record. The pipeline processes 120 images per video.

5. **The pipeline is production 24/7.** Cron runs at 5 AM and 8 AM Pacific. Code pushed to main deploys automatically. Don't push broken code.

6. **Read before you write.** This codebase has patterns. The bots follow patterns. The clients follow patterns. Read 2-3 existing examples before writing new code.

7. **Reference the roadmap.** Features 1-10 in `ANIMATION_SYSTEM_REVIEW.md` are detailed specs. Don't redesign what's already been thought through.

8. **Think in pipelines.** Every change has upstream and downstream effects. If you change the script format, you break image prompt generation. If you change image naming, you break Remotion rendering. Trace the full data flow.

9. **Log everything.** When adding features, add logging. The VPS runs headless. Slack alerts and log files are the only visibility.

10. **Ship incrementally.** This pipeline processes real videos. Ship small, verified changes. Don't refactor 5 files at once.
