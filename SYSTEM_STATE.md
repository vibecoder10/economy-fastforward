# System State — Economy FastForward

> Last updated: 2026-06-12

---

## 1. VPS Details

| Field | Value |
|-------|-------|
| **User** | `clawd` |
| **Path** | `/home/clawd/projects/economy-fastforward/` |
| **OS** | Linux (Ubuntu-based) |
| **CPU** | 4 vCPU |
| **RAM** | 16 GB + 4 GB swap (`/swapfile`, `vm.swappiness=10`) |
| **Swap setup** | `setup_swap.sh` — required for Remotion rendering (OOMs without it) |
| **PID file** | `/tmp/pipeline-bot.pid` (Slack bot) |
| **Logs** | `/tmp/pipeline-*.log` |

---

## 2. Pipeline Architecture (Reorganized March 2026)

Each production tool is a standalone folder in orchestration order. Shared infrastructure lives in `shared/`.

### Bot Folders (`skills/video-pipeline/`)

| Folder | Purpose | Key Files |
|--------|---------|-----------|
| `orchestrator/` | Pipeline brain — status-driven router, Slack bot | `pipeline.py`, `pipeline_control.py`, `pipeline_constants.py`, `handlers/` |
| `autopilot/` | Autonomous intelligence — CTR/VPH data-driven video selection | `autopilot.py`, `core/`, `analysis/`, `monitoring/`, `learning/`, `memory/` |
| `competitor_scraper/` | Pull competitor YouTube data | `scraper.py`, `run.py` |
| `discovery/` | Headline scanning + trending topics | `scanner.py`, `bot.py`, `tracker.py` |
| `title_idea/` | Title creation from data-backed research | `idea_bot.py`, `trending_idea_bot.py`, `curiosity_gap/` |
| `research/` | Deep-dive factual research | `agent.py` |
| `script/` | 6-scene script writing | `run.py`, `story_bible.py`, `brief_translator/` (11 files + 7 tests) |
| `voice/` | Voice synthesis (ElevenLabs) | `run.py` |
| `image_prompts/` | Image prompt generation (3-style system) | `run.py`, `engine/` (prompt_builder, sequencer, style_config) |
| `storyboard/` | Storyboard grid generation | `run.py`, `run_images.py`, `run_extract.py` |
| `images/` | Image creation (Seed Dream 4.5) | `run.py` |
| `video_motion/` | Video scripts + clip generation (Veo 3.1) | `run_scripts.py`, `run_generate.py` |
| `sound/` | Sound FX + Music selection | `run_design.py`, `run_effects.py`, `music_selector.py` |
| `thumbnail/` | Thumbnail generation | `run.py`, `engine.py`, `selector.py`, `templates.py` |
| `render/` | Audio sync + Remotion rendering | `run.py`, `render_video.py`, `audio_sync/` (7 files + 4 tests) |
| `upload/` | YouTube upload + SEO | `run.py`, `youtube_uploader.py`, `seo_generator.py` |
| `analytics/` | Performance tracking + Osiris learning | `performance_tracker.py`, `osiris/` |

### Shared Infrastructure

| Folder | Purpose |
|--------|---------|
| `shared/clients/` | API wrappers (airtable, anthropic, image, elevenlabs, google, slack, etc.) |
| `shared/clients/vision_client.py` | Provider-chained vision calls (Kie Gemini → Kie Claude → direct Anthropic, ingestion-verified). ALL vision goes through this — the Kie Claude gateway silently drops image blocks when it drifts (2026-06-12). Used by storyboard QA, model_video thumbnail pass, approve-cast rewrite. |
| `shared/profiles/visual/` | Visual style profiles (cinematic_illustration, dossier, hud, mannequin) |
| `shared/profiles/script/` | Script voice profiles (power_doctrine_v1, v2) |
| `shared/json_utils.py` | JSON parsing utilities |
| `shared/channel_profile.py` | Channel-specific settings |
| `infra/` | Setup scripts, cron, healthcheck, auth, StoryEngine deploy |
| `infra/storyengine_deploy.sh` | Auto-deploys frontend (rebuild) + backend (restart) on code changes |

### Backward Compatibility

Old import paths (e.g., `from clients.airtable_client import ...`) still work via shim files that re-export from new locations. Shims exist at: `clients/`, `bots/`, `steps/`, `visual_profiles/`, `script_profiles/`, `brief_translator/`, `image_prompt_engine/`, `audio_sync/`, `osiris/`, `curiosity_gap/`, `handlers/`.

### Remotion

| Path | Purpose |
|------|---------|
| `remotion-video/` | TypeScript/Remotion video rendering project |
| `remotion-video/src/Main.tsx` | Entry point — maps scenes from render_config.json |
| `remotion-video/src/Scene.tsx` | Core composition (~450 lines) — karaoke captions, Ken Burns, crossfades |
| `remotion-video/src/renderConfig.ts` | Loads render config from `getInputProps()` CLI props |
| `remotion-video/src/transcripts.ts` | Derives word-level timing from render_config (no static caption files) |
| `remotion-video/src/segments.ts` | Builds image-to-audio timing segments |
| `remotion-video/remotion.config.ts` | Render settings: concurrency, GL renderer, cache size |

### Remotion Render Config

Settings in `remotion.config.ts` and `render_video.py` CLI flags:

| Setting | Value | Source |
|---------|-------|--------|
| Concurrency | 3 | `remotion.config.ts:6`, `render_video.py:122` |
| Video image format | JPEG (quality 70) | `remotion.config.ts:4-5` |
| OpenGL renderer | `swangle` (software WebGL, no GPU) | `remotion.config.ts:7`, `render_video.py:123` |
| Timeout | 180,000 ms (3 min per frame) | `remotion.config.ts:8`, `render_video.py:124` |
| Offthread video cache | 1 GB (1,073,741,824 bytes) | `remotion.config.ts:9`, `render_video.py:125` |
| Overwrite output | true | `remotion.config.ts:3` |

Captions are loaded dynamically from `render_config.json` via `getInputProps()` at render time. The old static `captions/Scene [1-20].json` files are gitignored and deleted — they caused stale caption bugs when Remotion's `.remotion/` webpack cache served old data.

### Documentation Structure

| Path | Purpose |
|------|---------|
| `tasks/todo.md` | Current tasks + session handoffs |
| `tasks/lessons.md` | Hard-won patterns (read every session) |
| `tasks/roadmap.md` | Product roadmap + SaaS journal |
| `docs/` | Core reference docs (airtable-schema, api-patterns, etc.) |
| `docs/reports/` | Completion reports, wiring status, migration reports |
| `docs/reviews/` | System reviews (animation, architecture) |
| `docs/reference/` | Outdated but preserved docs (MANUAL_STEP.md) |
| `docs/superpowers/plans/` | Feature implementation plans |
| `docs/superpowers/specs/` | Detailed feature specs |

### Config & Env

| Path | Purpose |
|------|---------|
| `.env` | All secrets (gitignored, never committed) |
| `.env.example` | Template with descriptions for all required env vars |
| `CLAUDE.md` | AI assistant instructions and codebase reference |

### Claude Code Skills

| Skill | Purpose |
|-------|---------|
| `thinking-partner` | Co-creation mode — insights, challenges, alternatives before code |
| `structured-workflow` | GSD-inspired Discuss → Plan → Execute → Verify for multi-step tasks |
| `webapp-testing` | Playwright verification for frontend work |
| `react-best-practices` | React/Next.js performance patterns |
| `next-best-practices` | Next.js routing, RSC, data patterns |
| `composition-patterns` | Component architecture patterns |
| `supabase-postgres-best-practices` | DB schema, queries, RLS |
| `remotion-best-practices` | Remotion video rendering patterns |
| `web-design-guidelines` | UI/UX audit against design guidelines |

---

## 3. Airtable Tables & Key Fields

**Base ID:** `appCIcC58YSTwK3CE`

### Idea Concepts Table (`tblrAsJglokZSkC8m`)

Single source of truth for all ideas. This is the primary table that drives the pipeline.

**Core fields:**
`Status`, `Video Title`, `Hook Script`, `Past Context`, `Present Parallel`, `Future Prediction`, `Thumbnail Prompt`, `Writer Guidance`, `Original DNA` (JSON), `Source`

**Research fields:**
`Framework Angle`, `Headline`, `Timeliness Score`, `Audience Fit Score`, `Content Gap Score`, `Source URLs`, `Executive Hook`, `Thesis`, `Date Surfaced`, `Research Payload` (JSON), `Thematic Framework`

**Pipeline fields:**
`Script`, `Scene File Path`, `Accent Color`, `Video ID`, `Scene Count`, `Validation Status`, `Drive Folder ID`

**Optional fields:**
`Reference URL`, `Idea Reasoning`, `Source Views`, `Source Channel`, `Google Drive Folder ID`, `Thumbnail`, `Pipeline Mode`, `Notes`, `Upload Status`, `YouTube Video ID`, `YouTube URL`

**Performance fields (daily sync):**
`Views`, `Likes`, `Comments`, `Subscribers Gained`, `Impressions`, `CTR (%)`, `Avg View Duration (s)`, `Avg Retention (%)`, `Watch Time (hours)`, `Views 24h`, `Views 48h`, `Views 7d`, `Views 30d`, `CTR 48h (%)`, `Retention 48h (%)`, `Last Analytics Sync`, `Upload Date`

### Script Table (`tbluGSepeZNgb0NxG`)

| Field | Purpose |
|-------|---------|
| `scene` | Scene sequence number |
| `Scene text` | Narration text |
| `Title` | Video title (string-matched to Ideas table) |
| `Voice ID` | ElevenLabs voice ID |
| `Script Status` | `Create` → `Finished` |
| `Voice Status` | Voice synthesis status |
| `Voice Over` | Audio file attachment |
| `Sources` | Bibliography (scene 1 only) |

### Images Table (`tbl3luJ0zsWu0MYYz`)

| Field | Purpose |
|-------|---------|
| `Scene` | Scene reference |
| `Image Index` | Position within scene (1-6) |
| `Sentence Text` | Narration excerpt |
| `Image Prompt` | Generated prompt (75-110 words) |
| `Shot Type` | Composition type |
| `Video Title` | String-matched to Ideas table |
| `Status` | `Pending` → `Done` |
| `Image` | Generated PNG attachment |
| `Hero Shot` | Checkbox — 10s vs 6s clip |
| `Video Clip URL` | Google Drive link to video clip |
| `Animation Status` | Video generation status |

### Known Schema Issues

- **String joins, not linked records:** Tables joined by `Title` = `Video Title`. Typos break relationships.
- **3 overlapping status fields on Images:** `Status`, `Video Status`, `Animation Status` — must update all relevant ones.
- **`Sentence Index` duplicates `Image Index`:** Same value, different names.
- **Thumbnail field format inconsistent:** Code tries 3 field name/format fallbacks.

---

## 4. Google Drive Folder Structure

**Root parent folder ID:** `1zqsSvdyLWTRIt-Ri8VQELbYHhJihn6YD`
- Env var: `GOOGLE_DRIVE_FOLDER_ID`
- Established from n8n workflow (production folder)

**Organization:**
```
Root Parent Folder (1zqsSvdyLWTRIt-Ri8VQELbYHhJihn6YD)
├── [Video Title A]/
│   ├── scene_1.png ... scene_N.png
│   ├── voice_over_scene_1.mp3 ...
│   ├── video_clip_scene_1.mp4 ...
│   ├── thumbnail.png
│   └── final.mp4
├── [Video Title B]/
│   └── ...
└── ...
```

- One subfolder per video, named by video title
- `get_or_create_folder()` is idempotent — searches before creating
- `find_folder_by_keywords()` handles title mismatches (3+ char keyword overlap scoring)
- Drive URLs are permanent; Airtable attachment URLs expire in ~2 hours
- On Kie.ai 500 errors: proxy fallback downloads image → re-uploads to Drive → retries with Drive URL

### Upload Methods (`google_client.py`)

| Method | Input | Best For | Mechanism |
|--------|-------|----------|-----------|
| `upload_file()` | `content: bytes` | Small files (images, audio) | In-memory, single request |
| `upload_large_file()` | `file_path: str` | Large files (video, >100 MB) | Chunked resumable (50 MB chunks) |

Both methods:
- **Update in-place:** If `check_existing=True` (default), search for existing file by name in folder. If found, replace content via `files().update()` instead of creating a duplicate.
- Use Google's resumable upload protocol
- Handle transient HTTP errors (500, 502, 503, 504) with backoff retry

`upload_large_file()` streams from disk — never loads the entire file into memory. Prints upload progress as percentage per chunk.

---

## 5. Slack Channel

| Field | Value |
|-------|-------|
| **Channel ID** | `C0A9U1X8NSW` |
| **Purpose** | Pipeline control and notifications |
| **Bot token env var** | `SLACK_BOT_TOKEN` |

**Bot commands:** `!status`, `!run`, `!update`, `!logs`, `!health`, `!queue`, `!approve`, `!reject`

**Autopilot commands:** `autopilot on/off`, `autopilot status`, `autopilot force`, `autopilot config`, `autopilot learnings`, `autopilot patterns thumb/title`, `autopilot ctr [title]`

**Notification methods (all non-blocking):**

| Method | When |
|--------|------|
| `notify_pipeline_start()` | Pipeline begins processing a video |
| `notify_idea_generated()` | 3 concept variations created |
| `notify_script_start/done()` | Script generation begins/completes |
| `notify_voice_start/done()` | Voice synthesis begins/completes |
| `notify_image_prompts_start/done()` | Image prompt generation begins/completes |
| `notify_images_start/done()` | Image generation begins/completes |
| `notify_thumbnail_done()` | Thumbnail created |
| `notify_pipeline_complete()` | All assets ready for Remotion render |
| `notify_youtube_draft_ready()` | Upload as unlisted YouTube draft |
| `notify_error()` | Any stage failure (non-blocking) |

---

## 6. Cron Schedule

**Timezone:** `America/Los_Angeles` (US/Pacific)
**Source:** `skills/video-pipeline/infra/setup_cron.sh`

Each job auto-pulls from GitHub (`git pull origin main --ff-only`) before running.

| Time | Job | Command | Timeout |
|------|-----|---------|---------|
| 5:00 AM PT | Competitor Scraper | `osiris.competitor_scraper` | 10 min |
| 5:30 AM PT | Channel Scraper | `pipeline.py --competitors` | 10 min |
| **6:30 AM PT** | **Autopilot Decision Cycle** | `autopilot --check-cycle` | 15 min |
| 7:00 AM PT | Performance Tracker | `performance_tracker.py --recent` | 10 min |
| **7:30 AM PT** | **Autopilot CTR Monitor** | `autopilot.ctr_monitor` | 10 min |
| 8:00 AM PT | Pipeline Queue Runner | `pipeline.py --run-queue` | 4 hours |
| **8:30 AM PT** | **Autopilot Learning Extractor** | `autopilot.learning_extractor` | 10 min |
| 9:00 AM PT | Discovery Scanner | `pipeline.py --discover` | 10 min |
| Every 15 min | Bot Health Check | `bot_healthcheck.sh` | — |
| Every 30 min | Approval Watcher | `approval_watcher.py` | 10 min |

**Bold = Autopilot jobs** (added March 2026)

> **Note:** `setup_cron.sh` says `0 5 * * *` with `CRON_TZ=America/Los_Angeles`, but the actual VPS crontab runs discovery at 2PM UTC. Actual crontab takes precedence.

**Health check behavior:**
1. Checks `/tmp/pipeline-bot.pid` and verifies process is alive
2. Falls back to `pgrep -f "pipeline_control.py"`
3. If bot is dead: restarts it, saves new PID, sends Slack alert
4. If restart fails: sends critical alert with SSH instructions

---

## 7. Pipeline Stages

Status-driven pipeline. Airtable `Status` field gates each stage. One video processes at a time.

```
Idea Logged                  → Manual approval needed (Slack or approval_watcher)
    ↓
Ready For Scripting          → script_bot.py (6-act, 3000-4500 word script via Claude)
    ↓
Ready For Voice              → voice_bot.py (ElevenLabs narration via Wavespeed)
    ↓
Ready For Image Prompts      → image_prompt_bot.py (120 prompts, 3-style system)
    ↓
Ready For Images             → image_bot.py (Seed Dream 4.5, 120 images)
    ↓
Ready For Video Scripts       → video_script_bot.py (motion descriptions) [MANUAL ONLY — costly]
    ↓
Ready For Video Generation    → video_bot.py (Veo 3.1 Fast clips) [MANUAL ONLY — costly]
    ↓
Ready For Thumbnail          → thumbnail_bot.py (Nano Banana Pro)
    ↓
Ready To Render              → render_video.py (Remotion → final.mp4)
    ↓
Rendered                     → youtube_uploader.py (unlisted draft)
    ↓
Uploaded (Draft)             → Awaiting manual publish on YouTube
    ↓
Done
```

**Rules:**
- Never skip a status. Always update via Airtable client.
- Check status before processing.
- Video Scripts and Video Generation are skipped in automated runs (too expensive). Trigger manually.
- If a bot crashes, restart from its status — the pipeline is idempotent.

---

## 8. Autopilot Brain (March 2026)

Autonomous orchestration layer above the pipeline. Learns from CTR/VPH/retention data to auto-select and produce winning videos.

**Status:** Chunks 1-3 complete (102 tests). Foundation, thumbnail analysis, CTR monitoring, and learning extraction all implemented.

**Components:**
- `core/` — Config parser, state manager, cadence manager, confidence scorer, notifier
- `analysis/` — Thumbnail analyzer (Claude Vision), adapter (REPLACE:/APPEND:), title selector
- `monitoring/` — CTR monitor (6h/24h/48h), early warning system, performance comparator
- `learning/` — Pattern library, learning extractor, memory writer
- `memory/` — LEARNINGS.md, thumbnail_patterns.md, title_patterns.md, experiments_log.md

**Commands:** `python -m autopilot.autopilot --status`, `--check-cycle`, `--force`

**Design spec:** `docs/superpowers/specs/2026-03-18-autopilot-brain-design.md`

---

## 9. Osiris Learning System (March 2026)

Performance analysis system that extracts patterns from video metrics and competitor data.

- `osiris/competitor_scraper.py` — Scrapes all competitor videos into Competitor Videos table
- `osiris/performance_analyzer.py` — 48h/7d post-mortem analysis → learnings extraction
- `osiris/title_analyzer.py` — Title pattern analysis (structural vs semantic)
- `osiris/learnings_engine.py` — Injects learned patterns into generation prompts

**Related tables:** Competitor Videos, Osiris Learnings, Title Insights

---

## 10. StoryEngine Agent System (April 2026)

### Architecture

6 autonomous agents on cron, managed via RUBRIC dashboard + Telegram.

| Agent | Model | Schedule | Role |
|-------|-------|----------|------|
| Pipeline Tester | Opus | Hourly :10 | Test every page, file bugs |
| Backend Dev | Opus | Every 2h :00 | Fix backend bugs |
| Frontend Dev | Opus | Every 2h :02 | Fix frontend bugs |
| QA Engineer | Opus | Every 2h :04 | Verify fixes |
| Orchestrator | Opus | 8AM + 8PM | Health report to Telegram |
| Security Auditor | Opus | Every 6h | Security audit |

### Key Files

| Path | Purpose |
|------|---------|
| `storyengine/agents/run-agent.sh` | Unified agent runner (controls, prompts, ops mode) |
| `storyengine/agents/{role}.md` | System prompt per agent |
| `storyengine/agents/standing-orders/{role}.md` | Ops mode standing orders (when task queue is complete) |
| `storyengine/agents/task-queue.json` | Task queue (26 tabs, 161 tasks) |
| `storyengine/agents/memory/{role}.md` | Persistent agent memory (max 50 entries) |
| `storyengine/agents/blueprints/` | Product vision + role-specific blueprints |
| `storyengine/backend/storyengine-backend.service` | systemd unit for FastAPI (port 8001) |
| `storyengine/frontend/storyengine-frontend.service` | systemd unit for Next.js (port 3001) |
| `storyengine/backend/canaries/validator_drift.py` | Synthetic canary: upstream 4xx error-schema drift (system timer, every 6h) |
| `storyengine/backend/canaries/vision_drift.py` | Synthetic canary: Kie vision paths (Gemini + Claude gateway) must SEE a known image — ingestion-token + content asserts (user timer, hourly, ~$0.002/run, ntfy alert on failure) |
| `storyengine/backend/canaries/install_vision_canary.sh` | Installs the vision canary as user systemd units (no root; clawd has linger) |
| `storyengine/agents/setup-crons.sh` | Cron schedule installer |
| `storyengine/agents/daily-report.sh` | Daily report + PR + Telegram push |
| `storyengine/agents/notify-telegram.sh` | Shared Telegram notification helper |
| `rubric/scaffold/server.js` | RUBRIC HTTP API (status, controls, activity, spawn) |
| `rubric/scaffold/data/controls.json` | Operator control surface (on/off, focus, feedback) |
| `rubric/scaffold/data/handoffs.json` | Agent-to-agent message queue |
| `rubric/scaffold/data/activity-log.json` | Real-time event stream |
| `rubric/scaffold/telegram-healthcheck.sh` | Auto-restart Telegram tmux if dead |

### Ops Mode (Build → Operations Transition)

When the task queue is complete (all tasks done + verified), agents enter **Ops Mode** instead of exiting idle:
- Pipeline Tester: tests every page, files bugs that auto-activate dev agents
- Dev agents: fix bugs filed by tester, return to standing orders when queue is clear
- QA: verifies fixes
- Orchestrator: pushes health report + launch score (X/8) to Telegram
- Feedback loop: tester files bug → devs fix → QA verifies → all return to standing orders

### Launch Checklist (8 criteria)

1. All pages render without console errors
2. Auth flow works end-to-end
3. Billing/subscription flow works
4. Pipeline runs a video E2E through UI
5. Mobile responsive (375x667)
6. Performance (<3s page load)
7. No critical security vulnerabilities
8. All API endpoints return correct data

---

## 11a. Content Intelligence / Data Distillation (April 2026)

Vectorization pipeline that distills raw data (transcripts, research) into structured intelligence + vector embeddings. Reduces Supabase egress by replacing large TEXT reads with compact summaries.

### New Files
| Path | Purpose |
|------|---------|
| `storyengine/backend/distillation/__init__.py` | Module entry point |
| `storyengine/backend/distillation/embeddings.py` | OpenAI text-embedding-3-small wrapper |
| `storyengine/backend/distillation/distiller.py` | Claude Haiku summarization prompts |
| `storyengine/backend/distillation/pipeline.py` | Orchestrator: raw → summarize → embed → store |
| `storyengine/backend/routes/intelligence.py` | API: `/api/intelligence/*` (search, backfill, stats, insights) |
| `storyengine/backend/migrations/036_enable_pgvector.sql` | Enable pgvector extension |
| `storyengine/backend/migrations/037_content_intelligence.sql` | content_intelligence table + indexes |
| `storyengine/backend/migrations/081_machine_research_cards.sql` | Tenant/video/machine-keyed compact research checkpoints; dual-written with legacy `videos.research_payload.unit_research_cards` |

### New Table: `content_intelligence`
| Column | Type | Purpose |
|--------|------|---------|
| source_type | TEXT | 'competitor_transcript', 'video_script', etc. |
| source_id | UUID | FK to source row |
| summary | TEXT | LLM-generated summary (~500 bytes) |
| structured_metadata | JSONB | Extracted intelligence (hook type, topics, structure) |
| embedding | vector(1536) | Semantic search vector |

### API Endpoints
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/intelligence/backfill` | POST | Trigger bulk transcript distillation |
| `/api/intelligence/backfill/status` | GET | Check backfill progress |
| `/api/intelligence/search?q=...` | GET | Semantic similarity search |
| `/api/intelligence/stats` | GET | Distillation progress + savings |
| `/api/intelligence/record/{id}` | GET | Single record intelligence |
| `/api/intelligence/insights/topics` | GET | Aggregated topic distribution |
| `/api/intelligence/insights/hooks` | GET | Hook pattern distribution with VPH |
| `/api/intelligence/insights/thumbnails` | GET | Thumbnail visual patterns (face, layout, style) |
| `/api/intelligence/insights/timing` | GET | Best publish days/hours |
| `/api/intelligence/insights/virality` | GET | Viral videos (high views/sub ratio) + their DNA |

### Full Video DNA (extracted per competitor video)
| DNA Component | Source | Fields |
|---|---|---|
| Title DNA | Claude Haiku | structure, curiosity_gap, power_words, clickability |
| Hook DNA | Claude Haiku | type, opening_line, first_open_loop, time_to_hook |
| Content DNA | Claude Haiku | topics, entities, tone, timeliness, niche_category |
| Structure DNA | Claude Haiku | arc, pacing, words_per_minute |
| Retention DNA | Claude Haiku | first_5min_summary, open_loops, payoff_quality |
| Villain DNA | Claude Haiku | type, name, reveal_position, stakes_personal |
| Engagement | Claude Haiku | comment_bait, share_trigger, polarizing |
| Thumbnail DNA | Gemini Vision | face, emotion, text, colors, composition, clickbait signals |
| Performance | Raw metrics | views, vph, like_ratio, comment_ratio, views_per_sub_ratio |
| Timing | yt-dlp | published_day, published_hour, has_chapters |

### Additional New Files
| Path | Purpose |
|------|---------|
| `storyengine/backend/distillation/thumbnail_analyzer.py` | Gemini Vision thumbnail analysis |
| `storyengine/backend/migrations/038_extended_video_dna.sql` | Extended scraper columns |

### Modified Files
- `routes/autopilot.py` — Candidate detail lazy-loads transcript, returns distilled intelligence
- `routes/discovery.py` — Prefers distilled summaries over raw transcripts for idea generation
- `routes/learning_extraction.py` — Uses distilled hook types before falling back to raw transcript analysis
- `routes/niche.py` — Extended scraper (comment_count, subs, chapters, tags, derived ratios) + auto-distills after scraping

---

## 11. Known Issues / Tech Debt

### Critical

- **String joins instead of linked records** — Idea Concepts, Scripts, and Images tables are joined by `Title` = `Video Title` string matching. Typos silently break relationships. Should migrate to Airtable linked records.
- **3 overlapping status fields on Images table** — `Status`, `Video Status`, `Animation Status` track related but separate states. Easy to miss updating one.

### Medium

- **`Sentence Index` duplicates `Image Index`** — Same value, confusing names. Rename to `Segment Index`.
- **Thumbnail field format inconsistency** — Code tries 3 field name/format combos as fallbacks. Should standardize.
- **No cost tracking** — No per-image or per-video cost logging. Budget alerts exist only for animation pipeline (80% threshold).
- **No audit trail** — No `CreatedBy`, `ProcessedBy`, or modification timestamps on records.
- **No soft deletes** — Old/failed records clutter tables. No archive mechanism.
- **MANUAL_STEP.md is outdated** — Superseded by `setup_cron.sh`. Moved to `docs/reference/MANUAL_STEP.md`.

### Low

- **No pagination for large batches** — Works for single-video processing; would need pagination for bulk operations.
- **Attachment format inconsistency** — Some fields use `[{"url": ...}]`, others use plain URLs.

### Proposed Improvements (from docs/reviews/ANIMATION_SYSTEM_REVIEW.md)

1. Character Consistency Engine (BYOC) — HIGH priority
2. One-Shot `!create` Pipeline (Product Mode) — HIGH priority
3. Airtable Schema Optimization (Phase 1 quick wins) — MEDIUM priority
4. Pipeline Health Dashboard & Self-Healing — MEDIUM priority
5. Smart Image-to-Animation Bridging — MEDIUM priority
6. Prompt A/B Testing & Quality Scoring — MEDIUM priority
7. Multi-Voice & Sound Design Layer — LOW priority

---

## 9. Cost Per Video

| Operation | Unit Cost | Volume per Video | Subtotal |
|-----------|-----------|-----------------|----------|
| Image generation (Seed Dream 4.5) | $0.025/image | 120 images | $3.00 |
| Video clips (Veo 3.1 Fast) | $0.30/clip | 20-40 clips | $6.00-$12.00 |
| Thumbnail (Nano Banana Pro) | $0.075/image | 1-3 images | $0.08-$0.23 |
| Voice synthesis (ElevenLabs) | ~$0.30/1000 chars | — | $1.00-$2.00 |
| Claude API (Sonnet) | ~$0.01-$0.05/call | 20-30 calls | $0.30-$1.50 |
| Whisper transcription | ~$0.006/min | — | $0.15 |
| **Total per video** | | | **~$11-$19** |

**Rules:**
- Never add unnecessary API calls in loops. Batch where possible.
- Use `--dry-run` flags or mock API responses for testing. Don't burn $15 on a test run.
- Budget alerts exist at 80% threshold (animation pipeline).
- YouTube upload quota: 10,000 units/day, ~1,600 per upload (max ~6 uploads/day).

---

## 10. Title System

### Title Patterns Library (`title_patterns.json`)

Competitor analysis document with proven formulas from 3 channels:
- **Economy Rewind (ER):** 6 formulas — systemic patterns, cycles, betrayals, power figures
- **Mindplicit (MP):** 5 formulas — dark psychology, Machiavellian self-improvement
- **Chill Financial History (CFH):** 5 formulas — country-as-character storytelling
- **Economy FastForward (EFF):** 9 hybrid formulas combining all three sources

### 8 Title Architectures (ARCH)

| Architecture | Hook Type | Example Pattern |
|-------------|-----------|-----------------|
| **ARCH-1** | Specific Number + Stakes | Concrete dollar amounts |
| **ARCH-2** | Contradiction Hook | Sounds wrong but true |
| **ARCH-3** | Countdown/Deadline | Ticking clock urgency |
| **ARCH-4** | Hidden Actor Reveal | Who's really behind events |
| **ARCH-5** | Victim's Fatal Mistake | Irreversible errors |
| **ARCH-6** | Comparative Betrayal | Historical parallels |
| **ARCH-7** | Quiet Power Move | Unnoticed important events |
| **ARCH-8** | Inevitability Frame | Outcome already decided |

### Formula Tracking

- **Airtable field:** `Title Formula` — stores which formula (e.g., `EFF-2`) generated each title
- **Weekly CTR report:** `performance_tracker.py` runs a Sunday report (`weekday() == 6`) that:
  1. Groups all uploaded videos by `Title Formula`
  2. Computes average CTR per formula
  3. Posts a ranked Slack summary (best-performing formulas first)

---

## 11. Thumbnail System

### Three Templates (`thumbnail_title/templates.py`)

| Template | Name | Weight | Layout |
|----------|------|--------|--------|
| **A** | CFH Split | 60% | Character on left 60%, secondary element on right, text upper-right |
| **B** | Mindplicit Banner | 10% | Full-width text banner top 20%, dramatic scene below |
| **C** | Power Dynamic | 30% | Two-figure narrative — victim (cold blue, left) vs power figure (warm amber, right), red arrow |

All templates: 16:9 (1280x720), editorial comic style via Nano Banana Pro.

### Template Selection (`thumbnail_title/selector.py`)

Selection is keyword-driven against topic, title, summary, framework angle, and tags:

- **POWER_KEYWORDS → Template C:** robot, ai replace, monopoly, inequality, corporate, billionaire, oligarch, who owns, who controls, who profits, ban, blacklist, purge, weapon, sanctions, trap, control, dominance, leverage, coercion, force, punish, puppet, chess, weaponize, crush, destroy, eliminate, betray, backstab, exploit
- **STRATEGY_KEYWORDS → Template B:** machiavelli, strategy, hidden, secret, never do, warning, dark, manipulation, power play
- **Default → Template A**

### Machiavellian Visual Vocabulary (`thumbnail_title/prompt_builder.py`)

~50% of thumbnails get a random Machiavellian element injected:
- Puppet strings descending from top of frame
- Chess pieces scattered on ground
- Shadowy hand reaching from edge
- Tilted crown falling through air
- Cracked golden scale of justice
- Dagger with dollar-sign handle stuck in a map

### CAPS Word Guidance (`thumbnail_title/title_generator.py`)

The CAPS word in the title must be visceral (PURGE, TRAP, KILLED, CRUSHED, WEAPONIZED, BLACKLISTED, BANNED, BETRAYED, RIGGED, DOOMED). Generic structural words (STAGE, STEP, PHASE, PATTERN) are banned. The CAPS word must match the `red_word` in the thumbnail prompt for visual-verbal coherence.

---

## 12. Git Branch Strategy

### Branches

| Branch | Purpose |
|--------|---------|
| `main` | Production. Auto-deployed to VPS via `git pull --ff-only` on every cron run. |
| `claude/*` | Feature branches created by Claude Code for development work. |

### Workflow

1. **Development** happens on `claude/*` feature branches
2. **Push** to the feature branch with `git push -u origin <branch-name>`
3. **PRs** are created from feature branches into `main`
4. **Merging** to `main` triggers auto-deployment: the next cron run pulls the latest code via `git pull origin main --ff-only`
5. **Never push broken code to `main`** — it auto-deploys within the hour

### Claude Code Push Rules

- Always push to the designated `claude/*` branch
- Branch names follow the pattern: `claude/<description>-<session-id>`
- Never force-push or push directly to `main` without explicit permission
- On push failure due to network errors: retry up to 4 times with exponential backoff (2s, 4s, 8s, 16s)

---

## Model A Video (added 2026-06-10)

Dashboard button → modal (YouTube URL) → async modeling task → new video at
`idea_logged` with a full prompt-asset pack. Nothing renders/uploads without
explicit user action.

### New Files
| Path | Purpose |
|------|---------|
| `storyengine/backend/routes/model_video.py` | API: `POST /api/model-video`, `POST /api/model-video/{id}/retry`. Background task: yt-dlp extract (oEmbed fallback) → DNA distill (Haiku) → modeled idea + prompt pack (Sonnet) → persist (videos fields, 8 assets prompt rows, competitor_videos attribution, best-effort Drive brief). Status polled via existing `GET /api/pipeline/task/{video_id}`. |
| `storyengine/backend/tests/functional/test_model_video.py` | 6 stubbed runtime tests (happy path, transcript fallback, oEmbed fallback, friendly failures, URL parsing) |
| `storyengine/frontend/src/components/dashboard/model-video-modal.tsx` | Modal: URL input → task progress → failed/retry states → redirect to `/pipeline/{id}` |

### Modified
| Path | Change |
|------|--------|
| `storyengine/backend/main.py` | Registered `model_video.router` |
| `storyengine/backend/error_utils.py` | Added `user_facing()` marker so deliberate user copy survives the `_set_task_status` humanize funnel |
| `storyengine/frontend/src/lib/api.ts` | `modelVideo()`, `retryModelVideo()`, `ModelVideoResponse` |
| `storyengine/frontend/src/app/dashboard/page.tsx` | "Model A Video" button + modal wiring |
| `storyengine/frontend/src/components/dashboard/index.ts` | Export `ModelVideoModal` |

No DB migration needed — reuses `videos.reference_url/original_dna/research_payload/title_candidates/thumbnail_prompt`, `assets.image_prompt/video_prompt`, `competitor_videos.our_video_id/modeled_at`.


---

## Creator Control Run (added 2026-06-11)

Spec: docs/superpowers/specs/2026-06-10-creator-control-run.md. Three shipped phases:
Stop button (cooperative cancel), per-video Character Design step, mandatory
storyboard gate (Lock Story before image spend).

### New Files
| Path | Purpose |
|------|---------|
| `storyengine/backend/cancel_registry.py` | Dual-layer cancel flags (in-memory TTL + background_tasks 'cancelled' marker row for cross-process/arq). Stale cleanup happens at run-start in `_set_task_status`. |
| `storyengine/backend/routes/characters.py` | `/api/videos/{id}/characters/*`: design cast (bible or Claude-reads-script) → Kie portraits, regenerate/edit/upload/delete, approve (gates visuals), save/import project cast |
| `storyengine/backend/migrations/046_video_characters.sql` | video_characters table (+RLS) + videos.characters_approved_at |
| `storyengine/backend/migrations/047_story_lock.sql` | videos.story_locked_at; scripts.storyboard_on_off default 'On' |
| `storyengine/backend/tests/functional/test_cancel_generation.py` | 7 tests: registry semantics, image-bot halt, contract pins, job-limit exemption |
| `storyengine/backend/tests/functional/test_characters.py` | 5 tests: cast extraction, wiring + lock-gate pins |
| `storyengine/frontend/src/components/production/StopGenerationButton.tsx` | Red Stop beside running generation (Visuals, Clips, Storyboard, Voice tabs) |
| `storyengine/frontend/src/components/production/CharactersTab.tsx` | Characters tab: portrait cards, approve bar, save/use saved cast |

### Key wiring
- `POST /api/pipeline/cancel/{video_id}` — exempt from the concurrent-job rate limit
  (`_JOB_LIMIT_EXEMPT_PREFIXES` in rate_limit.py). Loops check `pipeline.should_cancel`
  between paid items (images, clips, grids, voice). Stop keeps paid work; stage re-run resumes.
- Approved cast → `pipeline.character_reference_urls` → storyboard bot →
  `image_client.generate_with_reference` (Kie image_input list).
- Gates in pipeline_executor: characters pending approval block grids/images;
  `story_locked_at` required for full image runs + storyboard extraction.
  `POST /{video_id}/lock-story` requires ≥1 reviewed grid; unlock-story to iterate.
