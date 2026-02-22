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
| `script_bot.py` | Scriptwriting | Concept from Ideas table | 6-act, 3000-4500 word script |
| `voice_bot.py` | Voice synthesis | Script text | MP3 narration via ElevenLabs |
| `image_prompt_bot.py` | Prompt engineering | Script scenes | 6 image prompts per scene (120 total) |
| `image_bot.py` | Image generation | Image prompts | PNG images via Seed Dream 4.5 |
| `video_script_bot.py` | Motion prompts | Images + script | Animation motion descriptions |
| `video_bot.py` | Animation | Images + motion prompts | Video clips via Veo 3.1 Fast |
| `thumbnail_bot.py` | Thumbnail | Video title + concept | YouTube thumbnail via Nano Banana Pro |

### API Clients (`skills/video-pipeline/clients/`)
| Client | Service | Key Methods |
|--------|---------|-------------|
| `anthropic_client.py` | Claude AI | `generate()` with system prompts |
| `airtable_client.py` | Airtable | `get_ideas_by_status()`, `create_script()`, `update_image_record()` |
| `elevenlabs_client.py` | ElevenLabs | `generate_voice()` |
| `image_client.py` | Kie.ai | `generate_image()` with retries |
| `google_client.py` | Drive & Docs | `upload_images()`, `write_script_doc()` |
| `gemini_client.py` | Gemini Vision | `score_image()` |
| `slack_client.py` | Slack | `post_message()` |
| `style_engine.py` | Internal | Style constants, prompt architecture |

### Content Generation (`skills/video-pipeline/`)
| Module | Purpose |
|--------|---------|
| `image_prompt_engine/` | 3-style cinematic prompt system (Dossier 60%, Schema 22%, Echo 18%) |
| `brief_translator/` | Script generation with 6-act structure and 11 analytical frameworks |
| `audio_sync/` | Whisper transcription + fuzzy scene-to-audio alignment |
| `thumbnail_generator/` | Formula-based YouTube thumbnail creation |
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

The pipeline is a **state machine** driven by the `Status` field in the Airtable Ideas table. Every bot reads the current status, does its work, then advances the status.

### Status Flow
```
Idea Logged
  ↓ [Idea Bot selects concept]
Ready For Scripting
  ↓ [Script Bot generates 6-act script]
Ready For Voice
  ↓ [Voice Bot synthesizes narration via ElevenLabs]
Ready For Image Prompts
  ↓ [Image Prompt Bot generates 120 prompts]
Ready For Images
  ↓ [Image Bot generates 120 images via Seed Dream 4.5]
Ready For Video Scripts
  ↓ [Video Script Bot generates motion prompts]
Ready For Video Generation
  ↓ [Video Bot animates via Veo 3.1 Fast]
Ready For Thumbnail
  ↓ [Thumbnail Bot generates YouTube thumbnail]
Ready To Render
  ↓ [Remotion renders final MP4]
Done
  ↓ [Upload to YouTube]
Rendered / Uploaded (Draft)
```

### Rules for Status Changes

- **NEVER skip a status**. Each status gates the next stage. If you jump from "Ready For Voice" to "Ready For Images", the image prompts won't exist.
- **ALWAYS update status via Airtable client** after a bot completes. Never leave a record in a stale status.
- **Check status BEFORE processing**. Bots must verify the record is in the expected status before starting work.
- **Failed records**: Set status to `Failed - [Stage Name]` with error details in the `Notes` field. Don't leave records stuck in an intermediate state.

---

## Airtable Schema

### Ideas Table (Source of Truth)
Key fields: `Title`, `Status`, `Concept`, `Research Brief`, `Script`, `Voice URL`, `Google Drive Folder ID`, `Thumbnail`, `Pipeline Mode`, `Notes`

### Scripts Table
Key fields: `Title`, `Script Text`, `Act [1-6]`, `Scene Count`, `Word Count`, `Framework`

### Images Table
Key fields: `Video Title`, `Scene Number`, `Image Index`, `Prompt`, `Image URL`, `Status`, `Video Status`, `Animation Status`, `Style`, `Composition`

### Known Schema Issues (See ANIMATION_SYSTEM_REVIEW.md Feature 4)
- Tables are joined by string matching (`Title` = `Video Title`), NOT linked records. **Typos break relationships.**
- Images table has 3 overlapping status fields (`Status`, `Video Status`, `Animation Status`). Update ALL relevant ones.
- `Sentence Index` and `Image Index` are the same value with different names.
- Thumbnail field format is inconsistent - the code tries 3 different field name/format combos as fallbacks.

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

### Voice Synthesis (ElevenLabs)
- Voice ID: `G17SuINrv2H9FC6nvetn` (configured in .env)
- Returns MP3 audio stream
- Upload to Google Drive after generation

### Audio Alignment (Whisper → Fuzzy Match)
- Whisper API returns word-level timestamps
- 3-strategy alignment: full-excerpt fuzzy match → anchor-word fallback → proportional estimate
- Minimum 60% similarity threshold for fuzzy matching

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

### Test Locations
- `image_prompt_engine/tests/` - Style system tests
- `brief_translator/tests/` - Script generation tests
- `audio_sync/tests/` - Alignment and timing tests
- `thumbnail_generator/test_generator.py` - Thumbnail generation tests

### Running Tests
```bash
cd skills/video-pipeline && python -m pytest image_prompt_engine/tests/
cd skills/video-pipeline && python -m pytest brief_translator/tests/
cd skills/video-pipeline && python -m pytest audio_sync/tests/
```

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
