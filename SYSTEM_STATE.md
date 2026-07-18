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

---

## C01a — Schema/Migration Hygiene (added 2026-07-17)

Follow-up to the S6 schema-drift sweep (`docs/reports/2026-07-17-storyengine-agent-audit-findings.md`).
`storyengine/schema.sql` was stale (missing 11 live tables, still declared the
dead `title_tests` table) and one applied prod migration had no source file
in git. All three new migration files below are confirmed idempotent no-ops
against the current live DB (see commit message + report for the proof).

### New Files
| Path | Purpose |
|------|---------|
| `storyengine/backend/migrations/050_enable_rls_auth_tables.sql` | Reconstruction of a migration applied to prod on 2026-06-12 with no git source (S6 finding #1). Filename matches the exact row already in the live `_migrations` table, so the migration runner (`main.py::_run_pending_migrations()`, filename-keyed) always skips it — pure documentation/reproducibility, never re-executes. |
| `storyengine/backend/migrations/082_untracked_ad_hoc_tables.sql` | Backfills `secrets` and `static_reference_cache` (previously created only via in-process `CREATE TABLE IF NOT EXISTS` in `vault.py` / `static_docu.py`, invisible to the migration lineage) into tracked migrations. Both in-process guards are kept (belt-and-suspenders), not removed. |
| `storyengine/backend/migrations/083_enable_rls_ad_hoc_tables.sql` | Enables RLS (no policies) on `secrets`, `static_reference_cache`, `channel_video_retention` — closes the public PostgREST/anon access path. Safe because the backend connects as the `postgres` role (table owner, `BYPASSRLS`), proven inline in the file. |

### Modified
| Path | Change |
|------|--------|
| `storyengine/schema.sql` | Regenerated from live introspection: added the 11 tables created by migrations 041-081 that were missing (`intelligence_reports`, `channel_videos`, `secrets`, `channel_profile_documents`, `chat_assets`, `production_queue`, `script_templates`, `channel_analytics_daily`, `static_reference_cache`, `channel_video_retention`, `machine_research_cards`); removed the dead `title_tests` declaration (no live table, zero code references). |

---

## C02 — Image-Model Override Honored on Coverage Path (added 2026-07-17)

Follow-up to checklist §0.1 ("Image-model dropdown is cosmetic ⚠ worst
offender" — `tasks/storyengine-wiring-fix-checklist.md`). The Pictures model
select writes `videos.image_model_override`, but `coverage_to_app.py`'s
character-sheet / storyboard-sheet / redraw-picture calls, the legacy
`pipeline_executor.py` image-variant path, AND the primary bulk "Generate all
pictures" path (`generate_coverage_for_video` → `run_coverage` →
`generate_coverage_frames` → `_gen_ref` in `storyboard/coverage.py`) each
hardcoded (or ad hoc branched) their own model choice, ignoring it.

**Correction from the first C02 pass (same day):** that pass fixed only the
3 `coverage_to_app.py` call sites + the legacy path and left the bulk path
flagged as a "known gap," reasoning it was deferred to the C11-C15 per-scene
router. That reasoning was wrong — C11-C15 route per-SCENE CLIP/video models
(Veo/Grok/Kling), a different axis from IMAGE models (gpt-image-2/nano-
banana-2/z-image). The bulk image path was covered nowhere else and is the
primary flow real users hit (`ScenesWorkspaceTab.tsx`'s "Generate all
pictures" button → stage `coverage-images` → `POST /coverage-images/{id}` →
`generate_coverage_for_video`, same function the chat auto-build's `actions.py`
loop calls). This follow-up commit closes that gap — see the second table
below.

### New Files
| Path | Purpose |
|------|---------|
| `skills/video-pipeline/shared/clients/image_model_router.py` | The ONE resolver every image-model-selecting call site now uses: `generate_scene_image_for_model(image_client, model_override, prompt, reference_urls, aspect_ratio, resolution) -> (url, model_used)`. GPT Image 2 stays the default AND the fallback for an explicit z-image/nano-banana-2 override that fails or gets content-policy blocked. `VALID_IMAGE_MODELS = {"nano-banana-2", "gpt-image-2", "z-image"}` is the single source of truth for the 3 values the Pictures selector writes. |
| `skills/video-pipeline/tests/test_image_model_router.py` | 12 unit tests (FakeImageClient, no network) covering all 3 overrides, their fallback-on-failure paths, and proving the default (no-override) path calls the exact same methods with the exact same arguments as before this fix. |
| `storyengine/backend/migrations/084_asset_image_model.sql` | `ALTER TABLE assets ADD COLUMN IF NOT EXISTS image_model TEXT` — records which model actually drew each picture. Applied live to project `wrromlupsmyzrrcqlucn` via Supabase MCP; will also auto-apply (no-op) on next backend startup via `_run_pending_migrations()`. |

### Modified (first pass — redraw/redo/legacy paths)
| Path | Change |
|------|--------|
| `storyengine/backend/scripts/coverage_to_app.py` | `redo_characters`, `generate_storyboard_sheet_for_scene`, `redraw_asset_image` now read `videos.image_model_override` and route through `generate_scene_image_for_model` instead of a hardcoded `generate_scene_image_gpt` call. `redraw_asset_image` persists the resolved model onto `assets.image_model`. |
| `storyengine/backend/pipeline_executor.py` | `run_image_variants` (the legacy Airtable-driven variant-regen path, ~L13690-13770) replaced its bespoke model branching (which never actually distinguished 'gpt-image-2' from no-override, and never called GPT at all when a reference image existed) with the same shared resolver; the INSERT into `assets` now writes `image_model`. |
| `skills/video-pipeline/shared/clients/image_client.py` | `generate_scene_image_gpt`'s two success returns now include a `"model"` key (`"gpt-image-2"` or `"nano-banana-2"`, whichever branch actually produced the URL) so the resolver can report the truth even when GPT's own internal content-policy fallback fires. Purely additive to the returned dict — every existing caller only reads `.get("url")`. |
| `storyengine/backend/routes/videos.py` | `GET /{video_id}/assets` and `GET /{video_id}/assets/variants` now SELECT `image_model`. |
| `storyengine/frontend/src/lib/api.ts` | `Asset` and `ImageVariant` interfaces gained `image_model?: string \| null`. |
| `storyengine/frontend/src/components/production/ScenesWorkspaceTab.tsx` | `SegmentCard` shows a small top-right badge naming the model that actually generated each panel (from `asset.image_model`), so a mismatch against the Pictures selector's current value is visible instead of silent. |

### Modified (follow-up pass — the bulk "Generate all pictures" path)
| Path | Change |
|------|--------|
| `skills/video-pipeline/storyboard/coverage.py` | `_gen_ref` now takes `model_override` and routes through `generate_scene_image_for_model` instead of a hardcoded `generate_thumbnail_gpt2` call; returns `(url, model_used)`. `generate_coverage_frames` threads `model_override` down to `_gen_ref` and stamps `"image_model"` onto every master/angle frame dict. `run_coverage` gained a `model_override` param, threaded to both `generate_coverage_frames` and `resolve_cast_url` (the auto-built cast-sheet anchor now honors the override too). `resolve_cast_url` routes its cast-sheet draw through the same resolver. |
| `storyengine/backend/scripts/coverage_to_app.py` | `generate_coverage_for_video` — THE bulk "Generate all pictures" entry point — now SELECTs `image_model_override` and passes it to both `resolve_cast_url` calls and to `run_coverage`. `store_scene`'s `INSERT INTO assets` now writes `image_model` from each frame's resolved model (the value `generate_coverage_frames` stamped on it), so coverage assets — the majority of a video's pictures — record the truth. |
| `skills/video-pipeline/tests/test_coverage.py` | Added `test_generate_coverage_frames_honors_model_override` — an integration test proving the bulk path (`generate_coverage_frames`/`_gen_ref`) resolves a `z-image` override for both the master and angle frame, with no GPT fallback. |

The gap flagged in the first pass is now closed: the primary "Generate all
pictures" flow honors `image_model_override` end to end, with GPT Image 2
unchanged as the default and the content-policy/failure fallback.

---

## C03 — Single-Sourced `wired` Flag + `GET /api/models` (added 2026-07-17)

Follow-up to checklist §0.2 ("Dead model options in the registry" —
`tasks/storyengine-wiring-fix-checklist.md`). `MODEL_REGISTRY` listed 3 video
models (Kling 3.0 Pro, Runway Gen-4 Turbo, Hailuo 2.3 Standard) with no live
generation path. The Scenes clip-model dropdown hand-copied its own
`WIRED_MODELS` constant, separate from `pipeline_executor.run_clip_generation`'s
own hardcoded `wired = {...}` set — the two could (and did) drift, so the
dropdown offered models the backend then rejected with "isn't available yet".

Both call sites (and the new endpoint below) now read a single `wired: bool`
field on `ModelProfile` itself — one flag, one registry entry, no second set
to keep in sync. `storyengine/backend/` has no registry of its own; it
imports `shared.channel_profile.MODEL_REGISTRY` from `skills/video-pipeline/`
via the same `sys.path` pattern `routes/skills.py` already uses.

### New Files
| Path | Purpose |
|------|---------|
| `storyengine/backend/routes/model_registry.py` | `GET /api/models` — returns every `MODEL_REGISTRY` entry (`id`, `name`, `kind` (always `"video"` today — the registry has no image models), `wired`) plus `default_video_model`. Read straight off the registry so it stays trivially extensible (a later chunk, C11/P1.1, adds `best_for`/`tier`/`cost_per_clip` to the same response). |
| `storyengine/backend/tests/functional/test_model_registry.py` | 3 tests (FastAPI `TestClient`, `get_tenant_id` dependency overridden, no DB needed) proving the endpoint returns all 7 registry entries and that the 3 dead models come back `wired:false` while the 4 live ones come back `wired:true`. |

### Modified
| Path | Change |
|------|--------|
| `skills/video-pipeline/shared/channel_profile.py` | `ModelProfile` gained `wired: bool = False`. Set `wired=True` on `GROK_IMAGINE`, `SEEDANCE_2_FAST`, `VEO_31_FAST`, `VEO_31_QUALITY`; explicit `wired=False` on `KLING_30_PRO`, `RUNWAY_GEN4_TURBO`, `HAILUO_23_STANDARD`. |
| `storyengine/backend/pipeline_executor.py` | `run_clip_generation`'s gate (~L11775-11783) dropped its own hardcoded `wired = {...}` set; now checks `profile.wired` on the same `MODEL_REGISTRY` entry it already looked up. |
| `storyengine/backend/main.py` | Registered `model_registry.router`. |
| `storyengine/frontend/src/lib/api.ts` | Added `VideoModelInfo` / `ModelsResponse` types and `getModels()`. |
| `storyengine/frontend/src/components/production/ScenesWorkspaceTab.tsx` | Deleted the hand-copied `WIRED_MODELS` constant. The clip-model `<select>` now derives its options from `useQuery(["models"], getModels)`, filtered to `kind === "video" && wired`. A small `FALLBACK_WIRED_MODELS` (Grok Imagine only) covers the case where the endpoint is unreachable/empty — the dropdown is never rendered broken or empty. |
| `skills/video-pipeline/tests/test_storyboard_bot.py` | Fixed a stale `len(MODEL_REGISTRY) == 6` assertion (registry has held 7 entries since `seedance-2-fast` was added — pre-existing, unrelated failure found while touching this file) and added `test_wired_flag_matches_live_generation_path`. |

`curl http://127.0.0.1:8001/api/models` verified locally (backend booted with
no DB/Redis — `DEV_MODE=true`/`DEV_TOKEN`/`DEV_TENANT_ID`, since the route
never touches the database): the 3 dead models come back `wired:false`, the
4 live ones `wired:true`, exactly matching `pipeline_executor`'s gate. The
live/paid step ("selecting every wired model actually generates a clip") is
deferred — see `tasks/live-verification-queue.md` §C03.

## C04 — Home Producer Works Kie-Only (added 2026-07-17)

Follow-up to checklist §0.4. The home Producer (`routes/chat.py`'s main chat
intake turn in `chat_turn`, and the onboarding hand-off in `_seed_producer`)
hard-required `anthropic_api_key` and told a Kie-only tenant to go add one,
even though the in-video co-pilot (`_handle_copilot`) already had a working
fallback via `kie_unified.get_text_client_for_tenant` (direct Anthropic key
first, else the Kie.ai key). Both home entry points now go through a shared
`_resolve_producer_client` helper that mirrors `_handle_copilot`'s exact
try/except — no new resolution logic invented. `producer_prompt.call_producer`
now takes the resolved client and drives it through its `.client.messages.create(...)`
shape (identical for `KieClaudeClient` and `AnthropicDirectClient`) instead of
building its own Anthropic-only client from a raw `api_key`. A soft, one-time
"add an Anthropic key for the sharpest plans" tip is appended to the plan
reply when running on the Kie fallback — never a wall.

### New Files
| Path | Purpose |
|------|---------|
| `storyengine/backend/tests/functional/test_producer_kie_fallback.py` | 6 tests: `_resolve_producer_client` falls back to `KieClaudeClient` (Kie-only), still prefers `AnthropicDirectClient` (both keys), returns `None` (not a raise) with neither key; a source lock that both home entry points call the shared resolver and the old hard `anthropic_api_key` gate is gone from `_seed_producer`; `call_producer` drives a fake resolved client (proves no Anthropic-specific assumption downstream) and still fails soft with nothing configured. |

### Modified
| Path | Change |
|------|--------|
| `storyengine/backend/producer_prompt.py` | `call_producer` gained a `client` kwarg (the tenant's resolved text client); uses `client.client.messages.create(...)` when given, falling back to the legacy `_client(api_key)` path only when no client is passed (kept for the module self-test). Module docstring updated — no longer claims "Direct Anthropic call (NOT the Kie gateway)". |
| `storyengine/backend/routes/chat.py` | Added `_resolve_producer_client` (mirrors `_handle_copilot`'s `get_text_client_for_tenant` try/except), `_NO_KEY_PRODUCER_MSG`, `_KIE_PRODUCER_HINT`, `_with_kie_hint`. Both `_seed_producer` and the `chat_turn` producer intake turn now resolve via `_resolve_producer_client` instead of hard-requiring `anthropic_api_key`, and call `call_producer(..., client=client)`. The soft hint is appended to `assistant_text` once per conversation (`state["kie_hint_shown"]`) only when a plan is produced on the Kie fallback client. |

`./venv/bin/python -m pytest tests/ -q` run before and after (via `git stash`):
same 16 pre-existing failures + 1 pre-existing error on both, unrelated to
this change (YouTube OAuth, discovery error-surfacing, SQL-injection lock,
etc.) — confirmed by diff, not just inspection. The live step ("fresh
Kie-only tenant completes onboarding → gets a production plan on home, no
error") needs a real Kie key and is deferred — see
`tasks/live-verification-queue.md` §C04.

## C05 — Docked Co-Pilot Accepts File Attachments (added 2026-07-17)

Follow-up to checklist §0.6. The docked co-pilot's file drop was dead on
arrival two ways: (1) `ChatCore.attachFiles` hard early-returned `if (docked)
return;`, and (2) even the docked `<Composer>` render never passed it
`attachments`/`uploading`/`onAttach` at all, so there was no drop-zone or
paperclip affordance in the dock in the first place — only the home welcome
and home "started" composers wired those props. Both are fixed: the docked
composer now passes the same props as home, and `attachFiles` uploads in
both modes, passing `videoId` through when docked.

`chat_assets` gained a `video_id UUID` column (migration
`085_chat_assets_video_id.sql`, applied live) so a docked drop is stamped to
the video it landed on at upload time — `POST /api/chat/upload` now accepts
an optional `video_id` form field, verifies the video belongs to the
tenant (fail-soft to unscoped on mismatch, never errors the upload), and
persists it on the `chat_assets` row. The home chat sends no `video_id` —
unchanged.

Separately, `_handle_copilot` (the video-scoped turn handler) previously
returned before the turn-level `_attach_assets`/`_assets_brief` call ran at
all (that call lives further down `chat_turn`, gated behind `if not
video_id`), so even a `body.attachments` id list on a docked turn was
silently dropped — the copilot could never reference a file dropped mid
conversation. `_handle_copilot` now calls the same `_attach_assets` helper
the home flow uses (no new path invented) and folds `_assets_brief` into the
summary line fed to both `agent_brain.run_copilot_brain` and the legacy
classifier prompt, so a follow-up like "use the reference I dropped" has the
file in context.

### New Files
| Path | Purpose |
|------|---------|
| `storyengine/backend/migrations/085_chat_assets_video_id.sql` | `ALTER TABLE chat_assets ADD COLUMN IF NOT EXISTS video_id UUID` + `idx_chat_assets_tenant_video` index. Applied live to project `wrromlupsmyzrrcqlucn` via Supabase MCP; column confirmed present via `information_schema.columns`. |

### Modified
| Path | Change |
|------|--------|
| `storyengine/schema.sql` | `chat_assets` gained `video_id UUID` + its index, matching migration 085. |
| `storyengine/backend/routes/chat.py` | `/api/chat/upload` takes optional `video_id` form field, verifies tenant ownership, persists it on the INSERT. `_handle_copilot` now calls `_attach_assets` on `body.attachments` (mirroring the home turn path) and threads `_assets_brief(...)` into the summary line used by both `agent_brain.run_copilot_brain` and the legacy classifier prompt. A lone file drop with no message gets a "saved to this video, what should I do with it" reply instead of the generic ask-me-anything line. |
| `storyengine/frontend/src/lib/api.ts` | `uploadChatAsset(file, conversationId, videoId?)` — new optional third param, sent as a `video_id` form field. |
| `storyengine/frontend/src/components/chat/ChatCore.tsx` | Removed the `if (docked) return;` early-return in `attachFiles`; it now passes `videoId` through when docked. The docked `<Composer>` render now passes `attachments`/`uploading`/`onAttach`/`onRemoveAttachment` (previously omitted entirely — the dock had no attach UI at all). Updated the stale "home chat only" comment on `Composer`'s `attachments` prop. |

Scope note: this chunk stops at "the dropped reference is saved + attached to
the video and the copilot can reference it in conversation." It does NOT
route a dropped image into the CharactersTab cast-generation flow (i.e.
auto-using it as a locked character reference) — that deeper filing is a
later chunk, same pattern as `filed_as` on other `chat_assets` rows.

`cd storyengine/frontend && npx tsc --noEmit` clean. `python -m py_compile
routes/chat.py` clean. `./venv/bin/python -m pytest tests/ -q -k "chat or
upload"` — 5 passed. Full suite: same 16 pre-existing failures + 1
pre-existing error before and after (confirmed via `git stash`), unrelated
to this change. The live step ("open a video's co-pilot dock, drop a PNG,
confirm it lands in `chat_assets` with the video's id and the copilot
references it") needs a running app + browser and is deferred — see
`tasks/live-verification-queue.md` §C05.

## C06 — Research-Skipped Transparency Chip + One-Tap Enable (added 2026-07-18)

Follow-up to checklist §0.5. `actions.make_autobuild_step` (the chain behind
"Build the video" — chat's `_handle_approve`/`_run_pending_action("build")` and
the `/api/pipeline/build/{id}` button) has always skipped the optional research
stage for non-`static_docu` videos: `idea_logged`/`approved` jumps straight to
`ready_for_scripting` instead of running `research.agent`. That default is
UNCHANGED — this chunk only makes it visible and reversible.

**Recording (`[D]`+`[B]`):** checked whether the existing per-video
`pipeline_stages` plan already represented this and it doesn't — a video's
plan is normally `NULL`/full (research technically "enabled"), yet the
autobuild's skip branch bypasses the plan entirely and skips research anyway
(pre-existing behavior, unchanged). Plan state and "did research actually run
this build" are two different facts, so a new column was needed: migration
`086_videos_research_skipped.sql` (`ALTER TABLE videos ADD COLUMN IF NOT
EXISTS research_skipped BOOLEAN DEFAULT FALSE`), applied live to project
`wrromlupsmyzrrcqlucn` via Supabase MCP, column confirmed via
`information_schema.columns`. `make_autobuild_step`'s skip branch now writes
`research_skipped = TRUE` right before advancing; `static_docu` videos (which
always research first) never set it.
`pipeline_executor.run_research`'s save now also sets `research_skipped =
FALSE` in the same UPDATE that persists the payload — so tapping "Run
research" (or any path that actually runs research) clears the flag once it
completes, gate-pass or not (research DID run either way).

**Clickable door (`[U]`):** `GuidedNextStep.tsx` (the pipeline page's one
next-step surface) renders a "Research: skipped (script writes from topic) —
Run research" chip whenever `video.research_skipped` is true, with a one-tap
button that calls the SAME manual trigger endpoint the Research tab's own
button uses (`POST /api/pipeline/research/{id}`, i.e.
`runPipelineStage(id, "research")`). That endpoint's own gate
(`_require_stage_enabled`) was widened: a manual tap now WIDENS the video's
`pipeline_stages` plan to include `"research"` first (instead of 400ing) if
the video's plan had switched it off at creation, so the chip's one-tap always
works. The chip disappears on its own — `refreshAll()` (already wired to the
task watcher's `onComplete`) refetches the video and `research_skipped` reads
`false`.

**Conversational door:** three deterministic "I'm building it now" messages
that unconditionally claimed "I'll research it" were corrected to check the
video's actual `render_mode` and say the true thing (`routes/chat.py`
`_handle_approve` and `_run_pending_action("build")`; `routes/pipeline.py`
`/build/{video_id}`). `producer_prompt.py`'s system prompt also now instructs
the producer to say plainly, when proposing a "full" plan, that the script
writes straight from the topic with no separate research pass (and that one
can be run afterward from the video's page) — this part isn't unit-testable
without a live LLM call.

**Found but explicitly NOT fixed in C06 (flagged for a future chunk):**
`make_autobuild_step`'s skip branch doesn't consult the plan before skipping —
so a video whose plan EXPLICITLY includes research (`workflow: "research"` or
a custom plan with `"research"` in it) still gets silently skipped by the
same chat-triggered autobuild, and `resolve_planned_status` then routes it
straight to `"done"` with no research and no script. This predates C06 (I
only added a DB write inside the existing branch — the control flow is
untouched), and P0.5 explicitly scoped this chunk to "record the fact, don't
change when research runs." The transparency chip's one-tap fix (calling
`/research/{id}` directly, bypassing the autobuild chain) works correctly
regardless of this bug.

**C06a (fixed):** the bug above was confirmed real and fixed as its own
chunk. `make_autobuild_step`'s idea_logged/approved, non-`static_docu` skip
branch now does `research_plan = parse_stage_plan(video.get("pipeline_stages"))`
and, when `research_plan is not None and "research" in research_plan`, calls
`ex.run_research(video_id)` (advancing on `status == "ready_for_scripting"`,
hard-stopping the build with a failure message on research failure) instead
of writing `research_skipped = TRUE` and skipping straight to
`ready_for_scripting`. A `None` plan (the ordinary default/full pipeline —
every existing and default video) is untouched: `research_plan is None` is
false for the `and` check, so the default path still skips exactly as
before, confirmed byte-identical by a `git stash`-verified non-vacuous test.
`static_docu` is structurally unreachable from the new check (its own `if`
branch above always `continue`s or `return`s first), so it can't double-run
research. New tests:
`storyengine/backend/tests/functional/test_autobuild_explicit_research_plan.py`
(5 tests: default-skips-unchanged, explicit `["research"]`-only plan runs
research, custom plan naming research alongside other stages runs research,
a restricted plan NOT naming research still skips, `static_docu` with
research also in its plan researches exactly once). Full backend suite: same
16 pre-existing failures + 1 pre-existing error before/after (confirmed via
`git stash`). Live "a real `workflow:"research"` autobuild actually runs
research and writes a script" needs a running app + Claude API key —
deferred to `tasks/live-verification-queue.md` §C06a.

### New Files
| Path | Purpose |
|------|---------|
| `storyengine/backend/migrations/086_videos_research_skipped.sql` | `ALTER TABLE videos ADD COLUMN IF NOT EXISTS research_skipped BOOLEAN DEFAULT FALSE`. Applied live to project `wrromlupsmyzrrcqlucn` via Supabase MCP; column confirmed present via `information_schema.columns`. |
| `storyengine/backend/tests/functional/test_research_skipped_chip.py` | Locks: non-`static_docu` autobuild records `research_skipped=TRUE` and never calls `run_research`; `static_docu` always calls `run_research` and never records the skip; same for `approved` status. 3 tests, stubs `database`/`pipeline_executor`/`routes.pipeline`. |

### Modified
| Path | Change |
|------|--------|
| `storyengine/schema.sql` | `videos` gained `research_skipped BOOLEAN DEFAULT false`, matching migration 086. |
| `storyengine/backend/actions.py` | `make_autobuild_step`'s non-`static_docu` skip branch now writes `research_skipped = TRUE` before advancing to `ready_for_scripting`. |
| `storyengine/backend/pipeline_executor.py` | `run_research`'s save UPDATE now also sets `research_skipped = FALSE`. |
| `storyengine/backend/routes/pipeline.py` | `/api/pipeline/research/{video_id}` widens the video's `pipeline_stages` plan to include `"research"` (instead of 400ing) when a manual trigger arrives for a video whose plan excluded it. `/api/pipeline/build/{video_id}`'s start message now checks `render_mode` instead of unconditionally claiming "research". |
| `storyengine/backend/models.py` | `VideoDetail` gained `research_skipped: bool = False`. |
| `storyengine/backend/routes/videos.py` | `GET /api/videos/{id}` SELECTs and returns `research_skipped`. |
| `storyengine/backend/routes/chat.py` | `_handle_approve` and `_run_pending_action("build")`'s "I'm building it now" messages check `render_mode` instead of unconditionally claiming a research pass. |
| `storyengine/backend/producer_prompt.py` | System prompt: the "full" workflow plan summary now tells the creator plainly that the script writes from the topic without a research pass. |
| `storyengine/frontend/src/lib/api.ts` | `VideoDetail` gained `research_skipped?: boolean`. |
| `storyengine/frontend/src/components/production/GuidedNextStep.tsx` | New "Research: skipped — Run research" chip, rendered above every state card, with a one-tap handler reusing `runPipelineStage(id, "research")` + the existing task-watcher/toast/refresh plumbing. |

`cd storyengine/frontend && npx tsc --noEmit` clean. `python -m py_compile`
clean on every touched backend file. `./venv/bin/python -m pytest
tests/functional/test_research_skipped_chip.py -q` — 3 passed (verified they
fail without the `actions.py`/`pipeline_executor.py` fix via `git stash`, so
they're not vacuous). Full suite: same 16 pre-existing failures + 1
pre-existing error before and after (confirmed via `git stash`), unrelated to
this change. The live step ("create a default video, see the chip, tap it,
confirm research runs and the chip clears") needs a running app + browser and
is deferred — see `tasks/live-verification-queue.md` §C06.

## C07 — `generation_ledger` Table + Clip-Path Ledger Write + `total_cost` Rollup (added 2026-07-18)

Checklist §0.3 (`tasks/storyengine-wiring-fix-checklist.md`): the cost
counter was wrong — price estimates were duplicated in 3 places and
`videos.total_cost` was never rolled up from real spend (confirmed live: no
INSERT/UPDATE anywhere in the codebase ever wrote a non-zero value into it
before this change; it just sat at its `DEFAULT 0`). New **`generation_ledger`**
table is now the single source of truth for `videos.total_cost`, wired for
the FIRST paid-generation call site (clips, `pipeline_executor.run_clip_generation`).
C08 (next) adds images/voice/thumbnail/sound; C09 single-sources price
constants (`actions.py` estimates, deletes the `next-action.ts` duplicate);
C10 adds the UI ("Est → Actual" chip + ledger drawer).

New `storyengine/backend/generation_ledger.py::record_ledger_entry()` does
two things per call, both wrapped in one try/except that never re-raises
(fail-soft — a completed clip already cost real money; losing its ledger
row is a bookkeeping miss, failing the caller would be a disaster):
1. `INSERT INTO generation_ledger (tenant_id, video_id, stage, model, units, unit_cost, actual_cost, kie_task_id) VALUES (...)`
2. `UPDATE videos SET total_cost = (SELECT COALESCE(SUM(actual_cost),0) FROM generation_ledger WHERE video_id=$1) WHERE id=$1`

Step 2 is a **recompute**, not an increment — every call is idempotent-safe
and self-healing regardless of call order or retries.

`run_clip_generation`'s `_one(r)` closure (one async task per clip, run
concurrently under a semaphore) calls `record_ledger_entry(stage="clip",
model=<the video's resolved video_model>, units=1, unit_cost=actual_cost=
clip_cost, kie_task_id=...)` right after each clip's `assets.video_clip_url`
write succeeds — `clip_cost` is the SAME value already computed from
`MODEL_REGISTRY[model_id].cost_per_clip` (via `clip_cost_for()`), never a
new hardcoded number. `kie_task_id` is captured via a new optional
`task_id_out: Optional[list]` parameter threaded through
`ImageClient.generate_video` / `generate_video_seedance` /
`generate_video_veo` / `generate_talking_video` (skills/video-pipeline) — a
FRESH empty list per clip (`task_id_box`, declared inside `_one(r)`), not a
shared attribute on the client instance, so concurrent clip generations on
the same shared `ImageClient` never clobber each other's Kie taskId.

Existing `stage_transitions.cost` / `bot_activity.cost` columns are
**unchanged and not double-counted against** — they're informational
activity-feed numbers (`_log_activity(..., cost=cost)` /
`_log_transition(..., cost=...)`) summed ad hoc by `/api/activity` and
`/api/dashboard` per request; nothing ever wrote them back into
`videos.total_cost`, so there was nothing to reconcile. Flagged as a
possible deprecation candidate once every stage's spend flows through
`generation_ledger` (C08+), not removed here.

### New Files
| Path | Purpose |
|------|---------|
| `storyengine/backend/migrations/087_generation_ledger.sql` | Creates `generation_ledger` (tenant_id, video_id, stage, model, units, unit_cost, actual_cost, kie_task_id, created_at), its two indexes (`video_id`; `tenant_id, created_at`), and enables RLS with no policies (mirrors migration 083's `secrets`/`static_reference_cache`/`channel_video_retention` pattern — backend connects as `postgres`, BYPASSRLS). Applied live to project `wrromlupsmyzrrcqlucn` via Supabase MCP `apply_migration`; table, both columns and both indexes, and `relrowsecurity=true` all confirmed via `information_schema`/`pg_indexes`/`pg_class`. |
| `storyengine/backend/generation_ledger.py` | `record_ledger_entry()` — the single write path into `generation_ledger` + `videos.total_cost`. Fail-soft by design (see above). |
| `storyengine/backend/tests/functional/test_generation_ledger.py` | 6 tests against an in-memory fake `database.execute`: row written with correct fields; `total_cost` == `SUM(actual_cost)` after one write; a second write accumulates via recompute (proven by seeding a stale non-ledger `total_cost=999` and confirming it's REPLACED, not incremented, by the first real write); a write for one video never touches another video's `total_cost`; a forced exception on the INSERT never propagates and leaves neither table changed; `kie_task_id` defaults to `NULL` when not captured. |

### Modified
| Path | Change |
|------|--------|
| `storyengine/schema.sql` | New `generation_ledger` table (placed next to `stage_transitions`/`bot_activity`), its two indexes, and its RLS-enable line (no policy), matching migration 087. |
| `storyengine/backend/pipeline_executor.py` | `run_clip_generation`: `animate()` closures (Grok/Seedance) and `_animate_recover()` now accept/forward `task_id_out`; the InfiniteTalk, Grok-speaking, and silent/Veo branches each pass a fresh per-clip `task_id_box`; right after a clip's `assets.video_clip_url` write, calls `record_ledger_entry(...)`. New top-level import `from generation_ledger import record_ledger_entry`. |
| `skills/video-pipeline/shared/clients/image_client.py` | `generate_video`, `generate_video_seedance`, `generate_video_veo`, `generate_talking_video` each gained an optional `task_id_out: Optional[list] = None` param — when passed, the Kie taskId is appended right after `createTask` succeeds. Backward compatible (defaults to `None`; the one other caller, `skills/video-pipeline/video_motion/run_generate.py`, is unaffected). |

`python -m py_compile` clean on every touched backend/pipeline file (no
frontend touched in C07 — `tsc` N/A). `./venv/bin/python -m pytest
tests/functional/test_generation_ledger.py tests/functional/test_schema_sql_migrations_drift.py
-q` — 10 passed. Full suite: same 16 pre-existing failures + 1 pre-existing
error before and after (confirmed via `git stash -u`), unrelated to this
change (742 passed baseline → 748 passed with the 6 new ledger tests added,
zero new failures). The live check ("generate one real clip, confirm a
`generation_ledger` row appears and `videos.total_cost` increments by the
matching amount") needs a paid Kie call and is deferred — see
`tasks/live-verification-queue.md` §C07.

**Known gaps intentionally left for later chunks:** `unit_cost`/`actual_cost`
are currently the same value (Kie's task-status payload never returns an
actual-spend figure, only URLs) — C09's "single price source" work is the
natural place to revisit if Kie ever adds one. The InfiniteTalk
audio-driven speaking-clip sub-path prices itself off `INFINITALK_USD_PER_SEC`
(env var), not `MODEL_REGISTRY.cost_per_clip` — pre-existing design (
InfiniteTalk isn't a selectable `video_model`), unchanged by C07; the ledger
row for that sub-path still records `model=<the video's resolved
video_model>` (e.g. `grok-imagine`) since that's what the checklist's "the
resolved clip model" field means, not the internal fallback animator used
for lip-sync — worth a closer look in C08/C09 if InfiniteTalk spend needs
its own line item.

## C08 — Ledger Writes on Images/Voice/Thumbnail/Sound (added 2026-07-18)

Checklist §0.3b (`tasks/storyengine-wiring-fix-checklist.md`): extends C07's
`generation_ledger`/`record_ledger_entry()` (unchanged — no schema/logic
edit) to every remaining paid-generation call site, so `videos.total_cost`
now reflects FULL per-video spend, not just clips. **Units decision:
per-call/per-batch**, not per-image — one row per completed generation call
(a whole `store_scene()` batch, one redraw, one voice run, one thumbnail,
one sound-effects run), matching C07's per-clip precedent and avoiding
120-rows-per-video. Every write is fail-soft via C07's existing
`record_ledger_entry()` try/except — no new failure mode.

**Price sourcing (no new hardcoded numbers — extracted 3 existing inline
literals into named constants so ledger + the UI's confirm-card estimate can
never drift apart silently; full single-sourcing into `MODEL_REGISTRY`/
`/api/models` is still C09):**
- `actions.py` gained `VOICE_COST_ESTIMATE = 0.30`, `SOUND_COST_ESTIMATE =
  0.20`, `THUMBNAIL_COST = 0.10` — these were bare literals inside
  `estimate_cost()`'s `voice`/`sound`/`thumbnail` branches before C08; now
  named constants that branch AND the new ledger call sites both read.
  `PICTURE_COST` (0.08, pre-existing since C07) is unchanged, reused as-is.
- **image** stage → `actions.PICTURE_COST` (0.08) at all 4 image-gen call
  sites (see table below).
- **voice** stage → `actions.VOICE_COST_ESTIMATE` (0.30), one row per
  `run_voice()` call that voiced ≥1 scene. Flat, not per-scene/per-char —
  this is the SAME rough number the confirm card already quotes for the
  whole "voice" verb regardless of scene count (ElevenLabs has no per-call
  actual-spend figure surfaced anywhere in this codebase to derive a metered
  rate from); noted as a known accuracy gap for C09, not invented here.
- **thumbnail** stage → `actions.THUMBNAIL_COST` (0.10), one row at each of
  `run_thumbnail`'s 3 mutually-exclusive completion paths (modeled-on-
  reference / channel's-own-formula / from-scratch legacy bot) — only one
  fires per call, so no double-count risk between them.
- **sound** stage → `SoundClient.ESTIMATED_COST_PER_GENERATION` (0.05,
  `skills/video-pipeline/shared/clients/sound_client.py`) — a MORE precise
  existing number than `actions.SOUND_COST_ESTIMATE`, since `sound_bot.py`
  already multiplies it out per real generation into
  `result["estimated_cost"]` (used for the Slack completion notification);
  the ledger write reuses that exact computed value, not the flatter verb
  estimate.

### Call sites hooked
| Stage | File : Function | Completion hook | Units this call | Price constant |
|-------|------------------|------------------|------------------|-----------------|
| image | `scripts/coverage_to_app.py` : `store_scene()` | after all frames of one scene's coverage batch are inserted | `n` frames stored | `actions.PICTURE_COST` |
| image | `scripts/coverage_to_app.py` : `redraw_asset_image()` | after the redrawn `assets.image_url` UPDATE | 1 | `actions.PICTURE_COST` |
| image | `pipeline_executor.py` : `run_images()` | right after `self._pipeline.run_image_bot()` returns (covers the completed/cancelled/errored-partway branches alike — placed before they diverge, since any images it made already cost money) | `result["image_count"]` | `actions.PICTURE_COST` |
| image | `pipeline_executor.py` : `run_image_variants()` | after the variant-generation loop, before return | `created` variants | `actions.PICTURE_COST` |
| voice | `pipeline_executor.py` : `run_voice()` | right after `self._pipeline.run_voice_bot()` returns (covers completed + cancelled-but-kept-some branches) | 1 (flat per run, see price note above) | `actions.VOICE_COST_ESTIMATE` |
| thumbnail | `pipeline_executor.py` : `run_thumbnail()` (modeled-on-reference branch) | after `thumbnail_url` UPDATE, before return | 1 | `actions.THUMBNAIL_COST` |
| thumbnail | `pipeline_executor.py` : `_run_channel_formula_thumbnail()` | after `thumbnail_url` UPDATE, before return | 1 | `actions.THUMBNAIL_COST` |
| thumbnail | `pipeline_executor.py` : `run_thumbnail()` (from-scratch legacy-bot branch) | after `_log_activity(..., "completed", ...)`, before return | 1 | `actions.THUMBNAIL_COST` |
| sound | `pipeline_executor.py` : `run_sound_effects()` | right after `self._pipeline.run_sound_bot()` returns, before the error/status branches | `result["total_generated"]` | `SoundClient.ESTIMATED_COST_PER_GENERATION` |

**Not hooked, on purpose:** `scripts/coverage_to_app.py`'s `redo_characters()`
(4-view character-sheet regeneration) — spec named it, but it's reachable
ONLY from that file's CLI `main()` (`--character` flag), never from any
route or `pipeline_executor.py` method; hooking dead code would fabricate
coverage without a live path to verify against. `run_characters()` (the
LIVE character-design verb, `pipeline_executor.py`) generates portraits via
`routes.characters._generate_portrait` on its own retry loop with no
existing named price constant anywhere (`estimate_cost()`'s "characters"
verb uses an inline `0.03` never extracted) — left for C09 (single-sourcing)
rather than inventing a fourth constant here; `characters` was not one of
the 4 stages this chunk's task named.

### Modified
| Path | Change |
|------|--------|
| `storyengine/backend/actions.py` | Named `VOICE_COST_ESTIMATE`, `SOUND_COST_ESTIMATE`, `THUMBNAIL_COST` constants (extracted from `estimate_cost()`'s inline literals); `estimate_cost()` now reads them. |
| `storyengine/backend/pipeline_executor.py` | `run_voice`, `run_images`, `run_image_variants`, `run_sound_effects`, `run_thumbnail`, `_run_channel_formula_thumbnail` each gained a `record_ledger_entry(...)` call at their completion point(s) (see table above). No changes to `run_clip_generation` (C07, untouched). |
| `storyengine/backend/scripts/coverage_to_app.py` | New top-level import `from generation_ledger import record_ledger_entry`. `store_scene()` now tracks `models_used` per frame and writes one ledger row after the batch; `redraw_asset_image()` writes one row after its UPDATE. |
| `storyengine/backend/tests/functional/test_generation_ledger.py` | +6 tests: one per new stage's price-constant reuse (image/voice/thumbnail/sound), one proving all 5 stages (clip + the 4 new ones) sum into `total_cost` without double-counting, one confirming C07's fail-soft guarantee holds identically for every new stage. Imports the REAL constants (`actions.PICTURE_COST` etc., `SoundClient.ESTIMATED_COST_PER_GENERATION`) rather than re-typing literals, so drift in the source constants breaks this test too. |

`python -m py_compile` clean on every touched file. `./venv/bin/python -m
pytest tests/functional/test_generation_ledger.py -q` — 12 passed (6 C07 +
6 new C08). Full suite: same 16 pre-existing failures + 1 pre-existing error
before and after (confirmed via `git stash`; 748 passed baseline → 754
passed with the 6 new tests added, zero new failures). The live check
("generate a real image/voice/thumbnail/sound-effect batch, confirm each
stage's ledger row lands and `total_cost` sums across all 5 stages") needs
paid API calls and is deferred — see `tasks/live-verification-queue.md` §C08.

**Deploy-safety note:** every new write goes through C07's existing
`record_ledger_entry()`, whose try/except already never re-raises — none of
C08's call sites can newly break generation. Backend-only (no frontend/DB
schema touched). No double-count risk against C07's clip rows: every row
carries a distinct `stage` value (`clip` vs `image`/`voice`/`thumbnail`/
`sound`), and `total_cost` is a straight `SUM(actual_cost)` recompute, so
adding more stages only adds more addends to that sum.

## C09 — Single Price Source + Real Model-Aware Pricing (added 2026-07-18)

Checklist §0.3c: C07/C08 left prices scattered — `actions.py`'s
`CLIP_COST`/`PICTURE_COST`/etc. hand-mirrored `MODEL_REGISTRY` and the
frontend's `next-action.ts` hand-mirrored `actions.CLIP_COST` on top of
that. Two hand-copies of the same 4 clip prices, kept in sync by nothing
but discipline.

**STEP 1 finding (the important one): Kie.ai does NOT return a real
per-generation cost.** Read every field the two Kie-polling clients ever
touch (`shared/clients/image_client.py`'s `poll_for_completion`/
`_poll_veo_completion`, `storyengine/backend/kie_unified.py`) — the
`recordInfo`/`veo/record-info` job-status response only ever carries
`taskId`/`state`/`status`/`successFlag`/`resultJson`/`resultUrls`/
`failMsg`/`failCode`, no matter which model ran. Kie DOES expose `GET
/api/v1/chat/credit` (confirmed via docs.kie.ai) — an **account-wide
remaining balance**, not a per-task charge, and with several
clips/images generating concurrently (`ModelProfile.max_concurrent`) a
balance snapshot can't be attributed to one generation without a race.
Conclusion: registry prices remain the source of truth; live dashboard
reconciliation is queued (`tasks/live-verification-queue.md` §C09), not
built here — no fabricated cost field.

**STEP 2 — single source:** every generation price now lives in
`skills/video-pipeline/shared/channel_profile.py`, next to
`MODEL_REGISTRY`:
- `CLIP_PRICE_BY_MODEL` — derived FROM `ModelProfile.cost_per_clip`
  (cheapest tier per wired model), not hand-typed.
- `IMAGE_PRICE_BY_MODEL` / `picture_price_for(model_id)` — **new**:
  per-model image price (gpt-image-2 0.08 UNCONFIRMED, nano-banana-2
  0.025, z-image 0.004) instead of one flat `PICTURE_COST` regardless of
  which of the 3 real image models drew the pixels.
- `THUMBNAIL_PRICE` — corrected **0.10 → 0.075** to match the real Nano
  Banana Pro rate (`docs/cost-awareness.md`).
- `VOICE_PRICE_PER_1K_CHARS` (0.30) — voice is now metered per real
  character count, not a flat `$0.30`/run.
- `SOUND_PRICE_ESTIMATE` — unchanged value, kept for `actions.py`'s
  pre-generation quote only (the ledger write still uses
  `SoundClient.ESTIMATED_COST_PER_GENERATION` directly, per C08).

`storyengine/backend/actions.py` re-exports these under its pre-existing
names (`CLIP_COST`, `PICTURE_COST`, `THUMBNAIL_COST`, `VOICE_COST_ESTIMATE`,
`SOUND_COST_ESTIMATE`) so no existing `from actions import ...` call site
needed touching — `estimate_cost()` and every `record_ledger_entry()`
caller now provably read the SAME object (locked by
`test_actions_prices_are_the_same_object_as_channel_profile`).

**Accuracy upgrades wired at the call sites that know enough to use them:**
- `pipeline_executor.run_image_variants`, `coverage_to_app.store_scene`,
  `coverage_to_app.redraw_asset_image` — now price with
  `picture_price_for(model_used)` (the REAL model that drew the pixels,
  already tracked in the `model` column) instead of always the flat
  0.08 default. A mixed-model batch or unknown model still falls back to
  the default (never a KeyError, never a guess at which model dominated).
- `voice/run.py`'s `run()` now returns `total_chars` (the exact narration
  character count sent to ElevenLabs this call); `pipeline_executor.run_voice`
  meters `actual_cost = total_chars/1000 * VOICE_PRICE_PER_1K_CHARS` when
  available, falling back to the flat `VOICE_COST_ESTIMATE` only if
  `total_chars` is missing/zero. A 6000-char video now ledgers ~20x a
  300-char one instead of both landing on the same flat `$0.30`.
- `actions.estimate_cost()`'s "voice" verb quote now queries
  `SUM(length(scene_text))` from `scripts` for a real pre-generation
  estimate instead of the flat guess (falls back to the flat estimate
  when no script exists yet).
- `GET /api/models` (`routes/model_registry.py`) gained a `cost_per_clip`
  field (pulled forward from the planned C11 chunk, since C09 needed it)
  — the Scenes tab's own model-dropdown prices itself straight off this
  query's own data now, not a side-channel mutation from a sibling
  component.

**Frontend duplicate deleted:** `next-action.ts`'s hardcoded
`CLIP_COST_PER_MODEL` literal (`{"grok-imagine": 0.10, ...}`) is now an
empty runtime cache populated ONLY from the backend, two ways: `GET
/api/models`'s `cost_per_clip` (`ScenesWorkspaceTab.tsx`, synced via a
`priceByModel` memo read on the SAME render `modelsData` arrives — not
the mutable-cache side channel, which populates one render too late) and
`GET /api/pipeline/actions/{id}`'s `prices.clip` (the video page,
unchanged pattern). A single `CLIP_COST_FALLBACK = 0.30` (the priciest
wired model) covers the brief gap before either sync has run — not a
second price table, one conservative scalar. `page.tsx`'s hardcoded
picture-cost fallback (`pictures * 0.08`) now reads
`videoActions.prices.picture` instead.

**Flagged for Ryan — NOT silently changed:**
- `IMAGE_PRICE_BY_MODEL["gpt-image-2"] = 0.08` — StoryEngine's DEFAULT
  image engine (`storyengine/CLAUDE.md` "Image gen policy"). Kie doesn't
  publish one flat rate for it (quality/resolution-tiered — OpenAI's own
  published range is roughly $0.006–$0.21/image). `docs/cost-awareness.md`'s
  old $0.025 figure is nano-banana-2's real rate (a DIFFERENT model,
  explicit-override only) mislabeled "Seed Dream 4.5" (that model name
  doesn't appear anywhere in the current codebase — doc was stale).
  0.08 is kept as the existing estimate, not replaced with the
  unrelated 0.025, but it is UNCONFIRMED — needs a Kie dashboard read.
- `THUMBNAIL_PRICE` 0.10 → 0.075 WAS changed (not just flagged) — Nano
  Banana Pro is a flat-rate Kie model and the number already matched
  `docs/cost-awareness.md`, unlike the GPT Image 2 case above.

### Modified
| Path | Change |
|------|--------|
| `skills/video-pipeline/shared/channel_profile.py` | New price section below `MODEL_REGISTRY`: `IMAGE_PRICE_BY_MODEL`, `picture_price_for()`, `PICTURE_PRICE_DEFAULT`, `THUMBNAIL_PRICE`, `VOICE_PRICE_PER_1K_CHARS`, `VOICE_PRICE_FLAT_ESTIMATE`, `SOUND_PRICE_ESTIMATE`, `clip_price_for()`, `CLIP_PRICE_BY_MODEL`. |
| `skills/video-pipeline/voice/run.py` | `run()` tracks and returns `total_chars` on all 3 return paths (cancelled/targeted/final). |
| `storyengine/backend/actions.py` | Price constants are now a re-export block from `shared.channel_profile` (with a `.resolve()`'d sys.path insert — see below); `estimate_cost()`'s "voice" branch queries real character count. |
| `storyengine/backend/pipeline_executor.py` | `run_voice` meters per-character; `run_image_variants` prices with `picture_price_for(model_used)`. |
| `storyengine/backend/scripts/coverage_to_app.py` | `store_scene()`/`redraw_asset_image()` price with `picture_price_for()`. |
| `storyengine/backend/routes/model_registry.py` | `VideoModelResponse` gained `cost_per_clip`. |
| `docs/cost-awareness.md` | Fixed stale "Seed Dream 4.5" label → nano-banana-2; added the GPT Image 2 unconfirmed-price note and single-source pointer. |
| `storyengine/frontend/src/lib/next-action.ts` | `CLIP_COST_PER_MODEL` literal deleted → empty runtime cache + `CLIP_COST_FALLBACK`. |
| `storyengine/frontend/src/lib/api.ts` | `VideoModelInfo` gained `cost_per_clip`. |
| `storyengine/frontend/src/components/production/ScenesWorkspaceTab.tsx` | `modelsData`/`priceByModel`/`priceForModel` moved to the top of the component; `perClip`/`remainingCost`/`sceneCost`/the model-dropdown labels all read `priceForModel`/`cost_per_clip` directly instead of the mutable cache. |
| `storyengine/frontend/src/app/pipeline/[videoId]/page.tsx` | Picture-cost fallback reads `videoActions.prices.picture` instead of a hardcoded `0.08`. |
| `storyengine/backend/tests/functional/test_generation_ledger.py` | +4 tests: single-source identity, `picture_price_for()` per-model rates, an image ledger row priced by actual model, a voice ledger row metered by real char count. `THUMBNAIL_COST` assertion updated 0.10 → 0.075. |
| `storyengine/backend/tests/functional/test_model_registry.py` | +1 test: `/api/models`' `cost_per_clip` matches the registry exactly, `null` for unwired models. |

**A latent bug caught mid-chunk:** `actions.py`'s new `shared.channel_profile`
import used the same unresolved `Path(__file__).parent.parent.parent`
pattern as `pipeline_executor.py`/`routes/model_registry.py` — but 3
lightweight test files (`test_autobuild_explicit_research_plan.py`,
`test_producer_kie_fallback.py`, `test_research_skipped_chip.py`) import
`actions.py` after their OWN unresolved `os.path.join(dirname(__file__),
"..", "..")` sys.path insert, so `actions`'s `__file__` carried
un-collapsed `..` segments and 3× `.parent` landed on a nonexistent
directory instead of the repo root. Fixed with `.resolve()` before taking
`.parent` — the other two files' identical pattern is pre-existing and
untouched (nothing currently imports them the same fragile way), noted
here rather than fixed, since fixing code you didn't break is scope creep.

`python -m py_compile` clean on every touched backend file; `.resolve()`'d
sys.path insert lets `import shared.channel_profile` work standalone.
`npx tsc --noEmit` clean. `./venv/bin/python -m pytest
tests/functional/test_generation_ledger.py tests/functional/test_model_registry.py
-q` — 20 passed. Full suite (`git stash` compare): 759 passed / 16 failed /
1 error both before and after — same 16 pre-existing failures (YouTube
OAuth, SQL-injection lock, discovery error-surfacing, etc., all unrelated
to pricing), zero new failures, +5 passed (the new tests).

**Deploy-safety note:** consolidating prices changes 2 user-visible
numbers: thumbnail quotes/ledger rows go from $0.10 → $0.075 (a
correction toward `docs/cost-awareness.md`'s existing figure, not a new
guess), and per-model image ledger rows for nano-banana-2/z-image drop
from the flat $0.08 to their real $0.025/$0.004 (GPT Image 2 — the
default engine most videos actually use — is unchanged at $0.08).
Neither changes what a creator is CHARGED (StoryEngine doesn't bill
per-generation yet); both only change what the cost dashboard/ledger
*reports* was spent, and only in the direction of being cheaper/more
accurate. Frontend still compiles and shows costs with no local
duplicate constant — confirmed via `tsc --noEmit` and by tracing
`priceForModel`/`videoActions.prices` reads by hand (no live browser
session in this sandbox). Live Kie-dashboard price confirmation (esp.
GPT Image 2 $0.08) queued — see `tasks/live-verification-queue.md` §C09.

## C09a — Price-Accuracy Pass on the Single Price Source (added 2026-07-18)

Follow-up to C09: applied Kie's PUBLISHED per-model/per-resolution pricing
(confirmed $0.005/credit rate, `kie.ai/<model>` pages) to
`shared/channel_profile.py`, in place of the guesses/mislabels C09 flagged.
Resolved by first tracing the LIVE code path each model uses (which
resolution it requests, which duration, which model actually draws a
thumbnail) so the researched price is applied to the RIGHT tier, not just
the cheapest or most obvious one:

- **`IMAGE_PRICE_BY_MODEL["gpt-image-2"]`: 0.08 → 0.05.** GPT Image 2 is
  tiered by resolution (1K=$0.03, 2K=$0.05, 4K=$0.08); the live call path
  (`image_model_router.generate_scene_image_for_model`, the one resolver
  every image call site uses) defaults `resolution="2K"` and nothing
  overrides it — 2K tier, not the 4K guess the old 0.08 amounted to.
- **`IMAGE_PRICE_BY_MODEL["nano-banana-2"]`: 0.025 → 0.04.** The old 0.025
  was actually a mislabeled "Seed Dream 4.5" figure (that model doesn't
  exist in this codebase anymore). nano-banana-2's real published 1K tier
  (the one `generate_with_reference`/`generate_scene_image` request) is
  $0.04.
- **`IMAGE_PRICE_BY_MODEL["z-image"]`: 0.004 unchanged**, now confirmed
  against published pricing instead of just the model-picker's label text.
- **`THUMBNAIL_PRICE`: 0.075 → 0.05, AND its whole basis corrected.** C09's
  "Nano Banana Pro flat rate" label was wrong — tracing
  `PipelineExecutor.run_thumbnail`/`_run_channel_formula_thumbnail` shows
  the PRIMARY thumbnail call is `generate_thumbnail_gpt2`/
  `generate_scene_image_gpt` (GPT Image 2, defaulting to the same 2K tier
  as scene images) every time; `generate_with_reference` (nano-banana-pro)
  only fires as a same-call fallback when GPT returns no url. Thumbnails
  now price at `IMAGE_PRICE_BY_MODEL["gpt-image-2"]` directly (same number,
  correct reason) instead of a separately-guessed Nano Banana Pro figure.
- **`MODEL_REGISTRY["grok-imagine"].cost_per_clip`: {6:0.10,10:0.15,15:0.20}
  → {6:0.09,10:0.15,15:0.225}.** Grok Imagine is $0.015/s at 720p (Kie
  published); StoryEngine requests 720p by default
  (`pipeline_executor.run_clip_generation`: `_vres = video.get(
  "video_resolution") or "720p"`). Each tier is now that per-second rate ×
  the tier's seconds, not a flat guess per tier.
- **`MODEL_REGISTRY["seedance-2-fast"].cost_per_clip`: {6:0.30,10:0.50} →
  {6:0.60,10:1.00}.** Seedance 2.0 has 4 published tiers by
  resolution×input; `ImageClient.generate_video_seedance` hardcodes
  `"resolution": "720p"` and ALWAYS passes `first_frame_url` (an image
  input), so the "720p with input" tier ($0.100/s) is the only one this
  code path can ever hit — a real ~2x price correction, not a rounding
  tweak.
- **Left unchanged, explicitly flagged (not silently trusted) — see
  `tasks/live-verification-queue.md` §C09 for the narrowed remaining list:**
  `veo-3.1-fast`/`veo-3.1-quality` (two conflicting public prices — current
  registry values already match the lower/cut figure, needs a dashboard
  read to pick one for certain), `kling-3.0-pro` (only a "Turbo" tier price
  found, unconfirmed same SKU), `runway-gen4-turbo` (low-confidence
  secondary source only), `hailuo-2.3-standard` (fal.ai, out of scope for
  the Kie research pass) — the last 3 are UNWIRED (`wired=False`), so no
  live spend depends on them.

**Not touched:** `VOICE_PRICE_PER_1K_CHARS`, `SOUND_PRICE_ESTIMATE` (voice
and sound don't route through Kie, so this Kie-pricing research pass
doesn't apply — both remain queued in `tasks/live-verification-queue.md`
§C09 against their own sources).

### Modified (C09a)
| Path | Change |
|------|--------|
| `skills/video-pipeline/shared/channel_profile.py` | `IMAGE_PRICE_BY_MODEL`, `THUMBNAIL_PRICE`, `GROK_IMAGINE.cost_per_clip`, `SEEDANCE_2_FAST.cost_per_clip` updated to researched values (see above); sourcing comments added at each changed constant; FLAG comments added at `veo-3.1-fast`/`veo-3.1-quality`/`kling-3.0-pro`/`runway-gen4-turbo`/`hailuo-2.3-standard` (values unchanged). |
| `storyengine/backend/actions.py` | One stale comment fixed (`"$0.08"` → `PICTURE_COST`) — no logic change; re-export block untouched. |
| `docs/cost-awareness.md` | Full rewrite of the price table + basis section: researched per-model/per-resolution prices, $0.005/credit sourcing, kie.ai/<model> pointers, narrowed "still dashboard-pending" list. |
| `tasks/live-verification-queue.md` §C09 | Narrowed to only the still-uncertain models (veo-3.1 price-cut question, kling, runway, grok image-gen, ElevenLabs) — the rest struck as resolved by this pass. |
| `storyengine/backend/tests/functional/test_generation_ledger.py` | Updated pinned values: `PICTURE_COST`/`THUMBNAIL_COST` 0.08/0.075 → 0.05, `picture_price_for("nano-banana-2")` 0.025 → 0.04 (2 tests + 1 ledger-row assertion). |
| `skills/video-pipeline/tests/test_storyboard_bot.py` | `test_cost_assigned`: grok-imagine 6s tier 0.10 → 0.09. |

`python -m py_compile` clean on every touched backend/pipeline file.
`npx tsc --noEmit` clean (frontend reads prices via API, no local
duplicate — nothing to break). `./venv/bin/python -m pytest
tests/functional/test_generation_ledger.py tests/functional/test_model_registry.py
-q` — 20 passed. Backend full suite (`git stash` compare): 759 passed / 16
failed / 1 error both before and after — same pre-existing failures
(YouTube OAuth, SQL-injection lock, discovery error-surfacing, etc.,
unrelated to pricing), zero new failures. `skills/video-pipeline` suite
(`git stash` compare, `tests/` minus 2 pre-broken collection files
unrelated to this change — missing `sound_prompt_bot`/other module):
before 24 failed/281 passed/3 errors, after identical 24/281/3 — zero new
failures, and the one price-pinned test (`test_cost_assigned`) was updated
to the new correct value rather than left red.

**Deploy-safety note:** same as C09 — these numbers only feed the cost
dashboard/ledger (`generation_ledger`, `videos.total_cost`, the UI's
"Est → Actual" chip); StoryEngine doesn't bill per-generation yet, so no
creator gets charged differently. The change makes reported spend MORE
accurate, in both directions (thumbnail/gpt-image-2 costs report lower;
nano-banana-2 and Seedance costs report higher, Seedance materially so —
~2x). Frontend still compiles with no local price duplicate to drift.

---

## C10 — UI "Est → Actual" Cost Chip + Ledger Drawer (added 2026-07-18)

The user-facing payoff of C07–C09a's ledger: the video page's cost chip now
shows the pre-generation-style estimate NEXT TO the real ledgered spend
(`"Est. $X → Actual $Y"`), with a click-to-open drawer breaking the actual
down by stage (`pictures $2.40, clips $3.90, voice $0.55…`). Also wires the
same read into the in-video copilot as a new `cost` tool, so "how much has
this cost?" is grounded in `generation_ledger` instead of guessed.

**New backend read endpoint:** `GET /api/videos/{id}/ledger` (in
`routes/videos.py`, reuses the existing `videos` router — no new
`include_router` needed). Tenant-scoped: 404s if the video doesn't exist for
the caller's tenant. Returns `{video_id, total_cost, by_stage, rows}` —
`total_cost` is read straight off the `videos` row (the same
`SUM(actual_cost)` rollup `generation_ledger.py::record_ledger_entry`
recomputes on every write — never re-summed here, so the chip and the
drawer can't disagree), `by_stage` groups `generation_ledger.actual_cost` by
`stage` (unknown/NULL stage falls back to `"other"`), `rows` is every ledger
row for the video (stage, model, units, unit_cost, actual_cost, kie_task_id,
created_at) in insertion order. New Pydantic models `LedgerRow` /
`VideoLedgerResponse` in `models.py`. `videos.total_cost` was ALREADY
returned by `GET /api/videos/{id}` (VideoDetail extends VideoSummary,
`total_cost: float = 0`) — confirmed pre-existing from C07, no change
needed there.

**Frontend:** new `CostLedgerChip` component
(`storyengine/frontend/src/components/video-detail/cost-ledger-chip.tsx`)
replaces the old single-value "Est. Cost" chip in the video-detail page
header (`storyengine/frontend/src/app/pipeline/[videoId]/page.tsx`). Shows
`Est. $X → Actual $Y` (Est. = the page's existing `estimatedCost`, computed
from `videoActions.summary.spent`/asset counts, unchanged; Actual =
`video.total_cost`); click opens a drawer that lazy-fetches
`GET /api/videos/{id}/ledger` (`enabled: open`, so a closed chip costs zero
extra requests) and lists the stage breakdown. States: loading spinner,
error with a retry button, and an explicit empty state ("No spend recorded
yet — actual cost is $0.00…") for a video with no ledger rows — none of
these render broken. New API client fn `getVideoLedger()` +
`VideoLedger`/`LedgerRow` types in `lib/api.ts`. **No local price constant
reintroduced** — every dollar figure the chip/drawer show came from the
server (`videoActions.prices`/`summary.spent`/the new ledger endpoint), per
the C09 rule.

**Conversational door:** `agent_brain.py` gets a new `cost` tool
(`_tool_cost`) alongside the existing `actions`/`script`/`shots`/`prompt`/
`history` tools — reads `generation_ledger` directly (same table the drawer
reads), groups by stage largest-first, and appends what finishing adds via
`actions.estimate_cost("build", ...)` (the SAME estimator the build confirm
card uses — no second price table). Wired into `TOOL_DOC` and `_run_tool`'s
dispatch so the copilot can call it mid-conversation; the system prompt
already tells the model to use it instead of the `actions` cost estimates
for "how much has this cost?"-shaped questions.

### Modified / added (C10)
| Path | Change |
|------|--------|
| `storyengine/backend/models.py` | New `LedgerRow` + `VideoLedgerResponse` Pydantic models. |
| `storyengine/backend/routes/videos.py` | New `GET /{video_id}/ledger` route (`get_video_ledger`); imports the two new models. |
| `storyengine/backend/agent_brain.py` | New `_tool_cost()`; `cost` added to `TOOL_DOC` and `_run_tool()` dispatch. |
| `storyengine/backend/tests/functional/test_video_ledger_endpoint.py` | New — 5 tests against the route function directly (fake `fetch_one`/`fetch_all`): 404 on missing video, empty-ledger $0 response (no 500), `total_cost` sourced from the videos row (not re-summed even when it would differ from the visible rows' sum), stage grouping/summing, NULL-stage → `"other"` fallback. |
| `storyengine/backend/tests/functional/test_agent_brain_cost_tool.py` | New — 4 tests for `_tool_cost`: no-spend phrasing, grouped-with-finishing-tail phrasing (locks the exact "Actual spend so far $X: a $, b $. Finishing adds ~$Y." format), no tail when nothing's left to spend, reachable via `_run_tool` dispatch. |
| `storyengine/frontend/src/lib/api.ts` | New `getVideoLedger()`, `VideoLedger`/`LedgerRow` types, next to `getVideoActions`. |
| `storyengine/frontend/src/components/video-detail/cost-ledger-chip.tsx` | New `CostLedgerChip` component (chip + click-open drawer, loading/error/empty states). |
| `storyengine/frontend/src/app/pipeline/[videoId]/page.tsx` | Header's old single-value "Est. Cost" block replaced with `<CostLedgerChip .../>`; new import. |

**Verify:** `cd storyengine/backend && ./venv/bin/python -m pytest
tests/functional/test_video_ledger_endpoint.py
tests/functional/test_agent_brain_cost_tool.py
tests/functional/test_generation_ledger.py -q` — 25 passed. Full backend
suite (`git stash` compare, new test files left untracked so the "before"
run proves they fail without their code — which they did, +9 failures on
top of baseline): 25 failed/759 passed/1 error before (16 pre-existing +
the 9 new tests in this chunk failing without their code), 16 failed/768
passed/1 error after (759 + 9 new: 5 ledger-endpoint + 4 agent-brain-cost,
all now passing) — the SAME 16 pre-existing failures both times, identical
file list (YouTube OAuth, SQL-injection lock on an unrelated file
`routes/youtube_sync.py`, discovery error-surfacing, etc.), zero new
failures introduced, zero fixed by accident. `python -m py_compile` clean on `models.py`, `routes/videos.py`,
`agent_brain.py`. `cd storyengine/frontend && npx tsc --noEmit` — clean
(exit 0).

**Trace (ledger row → chip):** `generation_ledger.record_ledger_entry()`
(C07/C08 call sites) → `INSERT INTO generation_ledger` +
`UPDATE videos SET total_cost = SUM(...)` → `GET /api/videos/{id}` returns
`total_cost` (VideoDetail, unchanged since C07) → page.tsx's
`videoForTabs`/header reads `video.total_cost` → `<CostLedgerChip
actualCost={video.total_cost}>` renders "Actual". Drawer: click → `GET
/api/videos/{id}/ledger` → `VideoLedgerResponse.by_stage` → drawer's
per-stage rows.

**Not provable without a running app + browser** (queued in
`tasks/live-verification-queue.md` §C10): generate one real scene, confirm
a `generation_ledger` row appears, `total_cost` increments, and the chip's
"Actual" + the drawer's per-stage sum both match it live.

**Deploy-safety note:** backend change is additive only (new route, new
Pydantic models, new tool in a fallback-safe agent loop — `agent_brain`
already falls back to the legacy classifier on any unexpected shape).
Frontend fails safe: `estimatedCost`/`actualCost` default to `0` before the
chip ever queries the new endpoint (chip renders immediately off data the
page already has), and the drawer's own loading/error/empty states mean a
lagging or erroring backend never produces a broken render — worst case the
drawer shows a retry button. Backend can deploy ahead of frontend with zero
effect (unused route); frontend cannot meaningfully deploy ahead of backend
(drawer would 404-error, but that's the handled error state, not a crash).

## C11 — Model Decision Table: `best_for`/`tier` on `/api/models` (added 2026-07-18)

Turns the video-model registry into a data-driven decision table so the
per-scene router (C12+) can pick a model from data instead of hardcoded
logic. No routing logic in this chunk — additive fields only.

**`ModelProfile`** (`skills/video-pipeline/shared/channel_profile.py`) gets
two new fields, documented inline with the tag vocabulary:
- `best_for: list[str]` — editorial tags from a fixed 6-tag vocabulary:
  `draft`, `hero`, `broll`, `multi_shot`, `character`, `atmospheric`.
- `tier: str` — cost band, one of `draft` | `standard` | `premium` (a
  different axis than `best_for`'s `"draft"` tag — a model can be
  `tier="standard"` and still carry `best_for=["draft"]`).

All 7 registry entries were set. The 4 wired models are sourced directly
from `docs/reports/2026-07-17-higgsfield-vs-storyengine-gap-analysis.md`'s
routing table (line ~85): Grok Imagine = `tier="draft"`,
`best_for=["draft", "broll"]`; Seedance 2.0 = `tier="standard"`,
`best_for=["multi_shot"]`; Veo 3.1 Fast = `tier="standard"`,
`best_for=["atmospheric", "broll"]`; Veo 3.1 Quality = `tier="premium"`,
`best_for=["hero"]`. The 3 unwired models (Kling 3.0 Pro, Runway Gen-4
Turbo, Hailuo 2.3 Standard) have no product routing guidance yet — tagged
by best-effort analogy to `cost_per_clip` and capabilities (Kling's
keyframe camera control + premium-band cost → `tier="premium"`,
`best_for=["character", "hero"]`, echoing Higgsfield's own
"character-driven → Kling" framing; Runway and Hailuo → `tier="standard"`,
`best_for=["broll", "atmospheric"]`/`["broll"]` by cost proximity). These 3
have zero live routing consequence today since `wired=False` already gates
them out.

**`GET /api/models`** (`storyengine/backend/routes/model_registry.py`):
`VideoModelResponse` gets `best_for: list[str] = []` and `tier: str =
"standard"`, populated straight from the same `ModelProfile` entry
(`profile.best_for` / `profile.tier`) — no second hand-copied table.

### Modified (C11)
| Path | Change |
|------|--------|
| `skills/video-pipeline/shared/channel_profile.py` | `ModelProfile` gains `best_for`/`tier` fields (with vocabulary docstring); all 7 model instances set both. |
| `storyengine/backend/routes/model_registry.py` | `VideoModelResponse` gains `best_for`/`tier`; `list_models()` populates them from the registry entry; module docstring updated (was a forward-reference to "a later chunk C11", now describes the shipped state). |
| `storyengine/backend/tests/functional/test_model_registry.py` | 2 new tests: `test_every_model_has_tier_and_best_for_from_allowed_vocabulary` (every model has a tier in the allowed set and only-vocabulary `best_for` tags), `test_best_for_and_tier_match_registry_and_gap_analysis_routing` (endpoint matches `MODEL_REGISTRY` 1:1, plus 4 gap-analysis spot-checks). |

**Verify:** `cd storyengine/backend && ./venv/bin/python -m pytest
tests/functional/test_model_registry.py -q` — 6 passed (4 pre-existing +
2 new). Confirmed non-vacuous via `git stash` on just the two source files
(`channel_profile.py` + `routes/model_registry.py`, test file left in
place): both new tests fail with `KeyError: 'tier'` / `KeyError:
'best_for'` on the pre-change source, pass after `git stash pop`. Full
backend suite unchanged: 770 passed / 16 pre-existing failures / 1
pre-existing error, same file list as C10 (YouTube OAuth, SQL-injection
lock on `routes/youtube_sync.py`, discovery error-surfacing, etc.) — zero
new failures, zero fixed by accident. `python -m py_compile` clean on both
touched `.py` files. `npx tsc --noEmit` not run — no frontend files
touched (by design; C14 does the UI).

## C12 — Per-Scene Model Router + `routed_model`/`routing_reason`/`model_used` Columns (added 2026-07-18)

Router module + migration only — clip generation does not read `routed_model`
yet (that's C13), no UI (C14). Data + recommendation, computed and persisted
at shot-plan time.

**New module `skills/video-pipeline/shared/model_router.py`**:
`route_shot_model(purpose, is_multi_shot=False) -> RoutingDecision(model_id,
routing_reason)`. Pure lookup over C11's `MODEL_REGISTRY.best_for`/`tier`/
`wired` fields — no second hardcoded capability table. Purpose → tag
priority: `REVEAL`/`PAYOFF` → `hero` tag (→ `veo-3.1-quality`); `ESTABLISH`
→ `atmospheric` (→ `veo-3.1-fast`); `SCALE`/`ISOLATION` → `broll` (→
`veo-3.1-fast`); anything else (including `STATIC` — no camera-move purpose
earned) → `draft` (→ `grok-imagine`, same as `DEFAULT_VIDEO_MODEL`).
`is_multi_shot=True` (no current caller sets this — forward-looking hint)
→ `multi_shot` tag (→ `seedance-2-fast`). Only ever matches against
`wired=True` registry entries; falls back to `DEFAULT_VIDEO_MODEL` with
reason `"default"` if a tag has no wired match (belt-and-braces — today's
registry always has one).

**Migration 088** (`storyengine/backend/migrations/088_scene_model_routing.sql`,
applied LIVE via Supabase MCP against project `wrromlupsmyzrrcqlucn`,
confirmed via `information_schema.columns`): `assets` gains 3 nullable TEXT
columns, no defaults — `routed_model`, `routing_reason` (this chunk writes
both), `model_used` (stays NULL — C13's column). `assets` is the live
per-scene/shot row table (confirmed by tracing `store_scene()` and every
other `INSERT INTO assets` site in `pipeline_executor.py`/`static_docu.py`/
`supabase_adapter.py`/`routes/model_video.py` — none of the others run the
camera engine, so `assets` + the coverage path is the one shot-plan write
path that has a "purpose" to route from). `schema.sql` updated to match
(canonical source, mirrors the migration-084 `image_model` pattern).

**Routing written at shot-plan time**: `storyboard/coverage.py`'s
`plan_camera_moves()` (runs BEFORE any frame is drawn) now computes a
routing decision right after each shot's camera-move `Selection` is
resolved, using the SAME `sel.purpose` the camera engine just computed —
stamps `shot["routed_model"]`/`shot["routing_reason"]`. Wrapped in its own
try/except, separate from (and after) the camera-move assignment, so a
routing failure never touches the camera-move plan — only that shot's
routing fields stay unset. `generate_coverage_frames()` carries both fields
through to the frame dict exactly like it already does for `camera_move`;
`coverage_to_app.py`'s `store_scene()` persists them onto the `assets`
INSERT (2 new placeholders, `model_used` omitted entirely from the INSERT
so it's NULL).

### New Files
| Path | Purpose |
|------|---------|
| `skills/video-pipeline/shared/model_router.py` | Data-driven purpose → model router over `MODEL_REGISTRY` |
| `storyengine/backend/migrations/088_scene_model_routing.sql` | `routed_model`/`routing_reason`/`model_used` on `assets`, idempotent |
| `storyengine/backend/tests/functional/test_scene_model_routing.py` | 10 tests: router unit tests + `store_scene()` write-path persistence |

### Modified
| Path | Change |
|------|--------|
| `skills/video-pipeline/storyboard/coverage.py` | `plan_camera_moves()` stamps `routed_model`/`routing_reason` per shot (fail-soft, isolated try/except); `generate_coverage_frames()` propagates both into master/angle frame dicts |
| `storyengine/backend/scripts/coverage_to_app.py` | `store_scene()` INSERT gains `routed_model`, `routing_reason` columns/params; `model_used` deliberately not included |
| `storyengine/schema.sql` | `assets` table gains the 3 new columns (documented inline) |
| `skills/video-pipeline/tests/test_coverage.py` | sys.path gains the `image_prompts` bot subdir (needed for `camera_selector.resolve_purpose()`'s bare `import animation_prompt_engine` to resolve standalone); 3 new tests: frame-propagation, `plan_camera_moves` stamps routing matching the router directly, fail-soft isolation from camera-move assignment |

**Verify:** Router + write-path: `cd storyengine/backend && ./venv/bin/python
-m pytest tests/functional/test_scene_model_routing.py -q` — 10 passed.
Shot-plan integration: `./venv/bin/python -m pytest
../../skills/video-pipeline/tests/test_coverage.py -q` — 7 passed, 1
pre-existing unrelated failure (`test_drops_moment_with_no_angles`,
confirmed failing identically with C12 stashed — a parser edge case
untouched by this chunk). Confirmed non-vacuous via `git stash` on
`coverage.py`/`coverage_to_app.py` + moving `model_router.py` aside: all
new tests fail (`KeyError: 'routed_model'`, `ModuleNotFoundError: No module
named 'shared.model_router'`), pass again after restoring. Full backend
suite: 780 passed (770 baseline + 10 new) / 16 pre-existing failures (same
file list as C11) / 1 pre-existing error — zero new failures. `python -m
py_compile` clean on all 5 touched/added `.py` files. Live column check:
`information_schema.columns` on project `wrromlupsmyzrrcqlucn` shows
`routed_model`, `routing_reason`, `model_used` — all `text`, nullable, no
default. **Deferred to `tasks/live-verification-queue.md` §C12**: an actual
video build showing `routed_model`/`routing_reason` land on real `assets`
rows (needs a live Kie/Anthropic key run through the coverage pipeline —
no paid generation in this sandbox). `npx tsc --noEmit` not run — no
frontend files touched (by design; C14 does the UI).

**Grep sweep (checklist §1.1 [V]):** no OTHER hardcoded model-capability
table for video clip models found. Other `best_for`/`tier` hits in the repo
are unrelated domains — visual-style profiles (`clay_mannequin.py`,
`cinematic_dossier.py`, `holographic_hud.py`, etc.), script-voice profiles
(`power_doctrine_v1/v2.py`, `neutral_v1.py`), image-prompt camera-move
purposes (`camera_moves.py`), thumbnail templates (`thumbnail/templates.py`),
and unrelated frontend "tier" usages (subscription rate-limit tier,
evidence source-tier, resolution tier strings) — none of these describe
video clip models. `ScenesWorkspaceTab.tsx`'s `FALLBACK_WIRED_MODELS` (the
C09b-flagged offline-only exception) still carries only `id`/`label`, no
best_for/tier copy — confirmed unchanged.

**Deploy-safety note:** additive only — new fields with safe defaults
(`best_for: [] `, `tier: "standard"`) on an existing Pydantic response
model; no existing field renamed/removed, no routing behavior changes (no
code reads these fields yet). Auto-deploy safe, ff-merge safe.

## C13 — Clip Generation Reads Per-Scene Routed Model; Records `model_used` (added 2026-07-18)

The FIRST behavior change on the paid clip path: `run_clip_generation`
(`storyengine/backend/pipeline_executor.py`) now resolves a model PER ROW
instead of once for the whole run, and the pre-spend quote
(`actions.estimate_cost`) sums per-scene resolved prices instead of one
flat video-level price times a count.

**New resolver `shared/model_router.resolve_clip_model(routed_model,
video_model_id, scene_override=None)`**: precedence is (1) `scene_override`
— a seam for C14's future per-scene-override column, always `None` today,
no column exists yet; (2) `routed_model` (C12's `assets.routed_model`) —
ONLY if it names a `MODEL_REGISTRY` entry with `wired=True`; (3)
`video_model_id` — the video-level model the caller already resolved
(itself already gated wired upstream, and itself falls back to
`DEFAULT_VIDEO_MODEL` if the video has no model set). A NULL, unknown, or
un-wired `routed_model` falls through step 2 and returns `video_model_id`
UNCHANGED — byte-identical to what every video did before this chunk.
Locked by 6 pure unit tests in `test_scene_model_routing.py`.

**`run_clip_generation` per-row wiring** (`pipeline_executor.py`): the
initial assets SELECT now also fetches `routed_model`. Inside the per-row
`_one(r)` closure, right after `sc, idx = r["scene"], r["image_index"]`,
`row_model_id = resolve_clip_model(r.get("routed_model"), model_id)` is
computed; when it differs from the outer video-level `model_id`, a fresh
`row_profile`/`row_durations`/`row_animate` are resolved
(`MODEL_REGISTRY.get(row_model_id)`, its `durations`, and a NEW
`_animate_for(mid)` factory — the same seedance-vs-grok branch the
video-level `animate` closure used to pick once, now callable per row).
When it's unchanged, `row_profile, row_durations, row_animate = profile,
durations, animate` — the EXACT pre-C13 objects, so the fallback path is
provably byte-identical, not just numerically close. Every place the old
code read `profile`/`durations`/`animate`/`model_id` inside `_one` (the
speaking-line duration/cost calc, the silent-shot duration/veo-branch/cost
calc, `_animate_recover`'s two call sites, the `strip_audio` check) now
reads the row-scoped variants; `_animate_recover` gained an `animate_fn`
parameter (defaults to the outer `animate` for any caller that doesn't
pass one).

**`model_used` write** (migration 088's 3rd column, unused until now): a
SEPARATE `UPDATE assets SET model_used = $1 WHERE id = $2` right after the
existing `video_clip_url` write, in its OWN try/except — a forced failure
on this write cannot fail the clip result (the money-earning write already
committed by the time it runs).

**Ledger pricing by actual model** (money invariant #1): the
`record_ledger_entry(..., model=...)` call at clip completion now passes
`effective_model_id` (the model that ACTUALLY ran this clip — see the
orchestrator-review fix below; NOT always `row_model_id`, the routed
target) instead of the video-level `model_id` — a mixed-routing video's
ledger prices each row by its own engine.

**Orchestrator-review fix, same chunk, before merge — the SPEAKING branch
has no Veo case**: pre-review, the code assumed `row_model_id`/`row_profile`
always described what actually ran. Not true for the `if lines:` (speaking/
dialogue) branch: `_animate_for()` only ever returns a Seedance or Grok
closure there — there is no Veo case (Veo only animates in the SILENT
`else` branch, via a dedicated `client.generate_video_veo` call). A row
purpose-routed to Veo (REVEAL/PAYOFF/ESTABLISH/SCALE/ISOLATION) that ALSO
carries a matched dialogue line (reachable whenever `dialogue_mode ==
"character_dialogue"` AND `dialogue_audio != "grok_native"` — i.e.
`native_voices` False — AND `match_lines`/`match_assigned` finds a scripted
line with `audio_url` set) would silently animate through Grok's closure
while `clip_cost`/the ledger/`model_used` all still claimed Veo at its
$1.25 price — a false cost record for real spend of ~$0.09–0.22. This is
NOT a new bug C13 invented outright — the SAME mismatch existed pre-C13 at
the (narrower) video level, if a whole video's own default model was set to
Veo and it had ANY speaking coverage row — but C13's per-scene routing
massively widens the reachable surface (a shot earns Veo by CAMERA PURPOSE
alone now, no video-level Veo choice needed). Fixed in the same commit,
before merge:
- A new `effective_model_id` variable (initialized to `row_model_id`,
  refined as the branch resolves) is now the ONLY value written to
  `model_used`/the ledger's `model` field — never `row_model_id` directly.
- In the speaking branch's Grok/Seedance-fallback leg (`if not clip_url:`,
  after an InfiniteTalk attempt/skip): if `row_model_id` isn't Seedance and
  isn't `DEFAULT_VIDEO_MODEL` (i.e. it's a Veo id, or any future id
  `_animate_for` doesn't special-case), `row_model_id`/`row_profile`/
  `row_durations`/`row_animate` are forced DOWN to `DEFAULT_VIDEO_MODEL`
  ("grok-imagine") BEFORE duration/cost are computed — this also
  incidentally fixes the pre-existing narrower video-level-Veo+speaking
  gap, not just C13's new one. `effective_model_id` is set to the
  (possibly-forced) `row_model_id` right after.
- When InfiniteTalk itself succeeds (`talked = True`), `effective_model_id`
  is set to `talking_model` (env `TALKING_CLIP_MODEL`, default
  `"infinitalk"`) — InfiniteTalk ran, not whatever model routing picked;
  `model_used`/the ledger now say `"infinitalk"` (a free-text label, same
  convention as C08's non-registry ledger model strings like
  `"elevenlabs"`/`"gpt-image-2"`), never a clip-model id that never ran.
- The non-speaking (silent) `else` branch is unaffected — it already has a
  real Veo case, so `row_model_id` there always names the true engine;
  `effective_model_id = row_model_id` at its tail just keeps the two
  branches' contracts identical for the shared downstream code.
2 new tests pin this (`test_speaking_branch_veo_routed_row_falls_back_to_grok_not_veo`,
`test_speaking_branch_infinitalk_success_records_infinitalk_not_routed_model`
in `test_c13_clip_model_routing.py`), confirmed non-vacuous via `git stash`
on `pipeline_executor.py` alone (both fail against the pre-fix source, the
other 9 file tests unaffected). Full suite after the fix: 797 passed (795 +
2) / 16 pre-existing failures / 1 pre-existing error — zero new failures.

**Quote path** (`actions.estimate_cost`, money invariant #2): new
`_routed_clip_costs(tenant_id, video_id, scene, video_model)` helper fetches
each not-yet-clipped row's `routed_model` and prices it via
`CLIP_COST[resolve_clip_model(routed_model, video_model)]` (cheapest wired
tier — same simplification the old flat quote already made). Wired into
both the `"animate"` verb (scene-scoped and whole-video) and the `"build"`
verb's finish-phase branch — but ONLY when pictures already exist (money
invariant #3: before a shot plan exists there is no per-scene routing to
sum, so `"build"` with zero pictures still falls back to the pre-C13 flat
`scenes * 6 * clip` guess, and a per-scene animate quote on an EMPTY scene
still falls back to the pre-C13 "guess 4 clips" fallback — both confirmed
unchanged by dedicated tests). `actions.py`'s `from database import
execute, fetch_one` import stays as-is (a `try/except ImportError` around a
separate `from database import fetch_all` falls back to `fetch_all = None`)
so the several test files that stub a bare-bones `database` module
(`execute`/`fetch_one` only) keep importing `actions.py` unchanged — this
was caught live by the full-suite run (3 tests errored on first pass,
fixed before this chunk shipped).

**Other clip-generation call sites traced**: `run_fix_text_card` and
`run_recrop_panel` (`pipeline_executor.py`) both delegate to
`run_clip_generation(asset_id=...)` — covered automatically, no separate
resolution logic. `routes/chat.py` and `routes/pipeline.py` call the same
`run_clip_generation` method — also covered. The legacy Airtable-based
`orchestrator/pipeline.py::run_video_gen_bot()` (reached via
`PipelineExecutor.run_video_generation`, a DIFFERENT, older pipeline that
never touches the StoryEngine `assets` table or its `routed_model` column)
is untouched — out of scope, C12 never wrote routing data for it either.
`routes/model_video.py`/`scripts/static_docu.py`/`scripts/supabase_adapter.py`
confirmed (grep) to do no clip generation at all.

### Modified
| Path | Change |
|------|--------|
| `skills/video-pipeline/shared/model_router.py` | New `resolve_clip_model()` — precedence resolver over C12's registry lookup |
| `storyengine/backend/pipeline_executor.py` | `run_clip_generation`: SELECT gains `routed_model`; per-row `resolve_clip_model()` + `_animate_for()` factory; `model_used`/ledger price by a new `effective_model_id` (not always `row_model_id` — see orchestrator-review fix above); speaking branch forces non-Seedance/non-`DEFAULT_VIDEO_MODEL` rows down to Grok before cost/duration; InfiniteTalk success reports `talking_model` |
| `storyengine/backend/actions.py` | `estimate_cost`'s `"animate"`/`"build"` verbs sum per-row routed prices via new `_routed_clip_costs()`; `fetch_all` import made optional (try/except) |
| `storyengine/backend/tests/functional/test_scene_model_routing.py` | +6 tests: `resolve_clip_model()` precedence/fallback/override unit tests |
| `storyengine/backend/tests/functional/test_c13_clip_model_routing.py` | New — 11 tests: quote summation (5) + real `run_clip_generation` wiring (6, via `PipelineExecutor.__new__` + monkeypatched DB/storage/image-client, same technique as `test_prompt_override_wiring.py` — 4 routing tests + 2 orchestrator-review speaking-branch tests) |

**Verify:** `cd storyengine/backend && ./venv/bin/python -m pytest
tests/functional/test_scene_model_routing.py
tests/functional/test_c13_clip_model_routing.py -q` — 27 passed. Confirmed
non-vacuous via `git stash`: the initial 15 tests all fail against pre-C13
source (9 in the new file, 6 `ImportError`-collected in the extended file);
the 2 orchestrator-review tests fail against the C13 source BEFORE that
fix, with the other 9 file tests unaffected (stashing just
`pipeline_executor.py` alone) — both stash passes confirmed, pass again
after `stash pop`. Full backend suite: 797 passed (780 baseline + 17 new)
/ 16 pre-existing failures (same file list as C12) / 1 pre-existing error
(`vault.py`'s `test_api_key` function name/pytest collision, unrelated) —
zero new failures, zero fixed by accident. `python -m py_compile` clean on
all 5 touched/added `.py` files. No frontend files touched (by design;
C14/C15 own the UI and copilot copy).

**Deferred to `tasks/live-verification-queue.md` §C13**: an actual mixed-
routing video build (some scenes routed to Veo, some to Grok) with real Kie
keys, confirming clips actually differ per scene, `model_used` lands on
real `assets` rows, the ledger prices each row correctly, and the UI's
pre-spend quote for that video matches the real spend — no paid Kie key in
this sandbox.

**Deploy-safety note:** for EXISTING videos (every asset row inserted
before C12 shipped routing, and any row whose shot-plan-time routing
try/except fired), `routed_model` is NULL on every row —
`resolve_clip_model(None, model_id)` returns `model_id` unchanged, so
`row_profile/row_durations/row_animate` are literally the SAME objects the
pre-C13 code used (not just equal — `is` the same profile/closure), the
`model_used` write is a new no-risk side-effect, and the ledger simply
records the SAME model it always did — behavior is byte-identical. For NEW
videos whose scenes DO carry a wired `routed_model` (every coverage build
since C12 landed), clips can now animate through a DIFFERENT model per
scene, cost differently per scene, and get a `model_used` value recorded —
this is the intended new behavior, gated entirely by data already written
by C12 (no feature flag needed; a scene only diverges from the video's
default if C12's router actually picked something different and that model
is wired). Auto-deploy safe, ff-merge safe.

## C13b — Channel-Style Routing Guardrail (added 2026-07-18)

Ryan's 2026-07-18 product rule: the video's LOOK gates model choice BEFORE
scene importance does. Animated channels (e.g. Poco a Poco — ElevenLabs
voice-over + Grok animation) must stay in the Grok family; Grok is
genuinely good at animating ONE stylized scene, but has no realistic
capability, and the realistic palette (Seedance/Veo/Kling/Runway/Hailuo) is
priced/built for photoreal work. As shipped, C12/C13's router routed
REVEAL/PAYOFF scenes on EVERY video to `veo-3.1-quality` regardless of the
channel's look — wrong for an animated channel. This chunk adds the
guardrail before C14's UI ships model badges.

**`ModelProfile.styles`** (`shared/channel_profile.py`): a THIRD data-only
axis alongside C11's `best_for`/`tier` — fixed vocabulary `animated` |
`stylized` | `realistic` | `cinematic` (docstring documents each). Assigned
to all 7 registry entries from Ryan's rule + docs/cost-awareness.md's
per-model notes (no other model has documented animated-scene capability):
Grok Imagine = `["animated", "stylized"]` (explicitly NOT "realistic");
Seedance 2.0 = `["realistic"]`; Veo 3.1 Fast/Quality = `["realistic",
"cinematic"]` each; Kling 3.0 Pro = `["realistic", "cinematic"]`; Runway
Gen-4 Turbo / Hailuo 2.3 = `["realistic"]` each. `GET /api/models`
(`routes/model_registry.py`) exposes `styles` the same way C11 exposed
`best_for`/`tier` — data only, read straight off the registry entry.

**Migration 089** (`storyengine/backend/migrations/089_video_render_style.sql`,
applied LIVE via Supabase MCP against project `wrromlupsmyzrrcqlucn`,
confirmed via `information_schema.columns`): `videos` gains `render_style`
TEXT, nullable, no default, no CHECK constraint (matches the sibling
`render_mode` column's pattern — enforced by the two write sites, not the
schema). `'animated'` | `'realistic'` | NULL (undeclared — every video
today). `schema.sql` updated to match.

**Router guardrail** (`shared/model_router.py::route_shot_model`, new
`render_style`/`video_model_id` params, both default `None`): (1)
`render_style` falsy (every video today) → returns `video_model_id` (or
`DEFAULT_VIDEO_MODEL`) **UNCHANGED**, reason `"channel style not set —
using channel default"` — this DELIBERATELY disables the C12 purpose→tier
cascade until a channel opts in, the money-safe default (no premium
upgrade recommendations on a channel that hasn't declared its look). (2)
`render_style` set → the SAME multi_shot→purpose-tag→draft cascade as
before, but every lookup is now filtered to wired models whose `styles`
include the declared value (the "palette") — an animated channel therefore
NEVER matches veo/seedance even for a REVEAL/PAYOFF ("hero") shot; it falls
through the cascade to whatever wired model IS in that palette (today, only
Grok, tagged `draft`/`broll`), producing a reason like `"reveal scene, but
channel is animated → Grok Imagine"`. (3) No wired model anywhere carries
the declared style (a value nothing is tagged with) → same video-level
fallback as (1), reason names the unmatched style. `resolve_clip_model`
needed NO change — traced and confirmed: when `render_style` is unset the
router hands back `video_model_id` itself as `routed_model`, which
`resolve_clip_model` either accepts (if wired) or falls through to
`video_model_id` anyway (if not) — byte-identical either path.

**Wiring trace — how `render_style` reaches the router**: `storyboard/
coverage.py::plan_camera_moves(moments, render_style=None,
video_model_id=None)` (new kwargs, default `None` so every existing caller
keeps working) threads both straight into `route_shot_model()`. `run_coverage()`
gained the same two kwargs, passed down to `plan_camera_moves()`.
`storyengine/backend/scripts/coverage_to_app.py::generate_coverage_for_video`
— the LIVE production path (`pipeline_executor.run_coverage_images` →
this function; confirmed the ONLY other `run_coverage()` caller,
`main()`'s CLI debug tool, is NOT part of the live wiring and was
deliberately left untouched, out of scope) — now SELECTs `render_style,
video_model` alongside its existing `image_style_override`/`visual_style`/
`image_model_override` fetch and passes them through to `run_coverage()`.

**Auto-derivation (investigated, partially implemented — reused existing
classifiers, invented no new inference)**: `create_video`
(`routes/videos.py`) stores `visual_style`/`image_style_override` as raw
text (a preset id like `pixar_3d` OR a freeform label like "Pixar 3D" OR
fully custom text); the channel-format lock (`channel_format.py`) can also
fill `visual_style` AFTER insert via `apply_format_defaults`. Two existing
functions already turn that raw text into one of exactly SIX canonical
preset ids (or `None` when unmappable) — `routes/videos.py::
_normalize_style_preset` (used by `GET /videos/style-default`) and
`channel_format.py::style_preset_for_format` (used by the locked-format
default). Since `realistic` is literally one of those six presets and the
other five (`pixar_3d`/`flat_2d`/`anime`/`watercolor`/`comic`) are all
illustrated/stylized looks, the six-way split maps onto `render_style`
with NO new ambiguity to invent: new `channel_format.render_style_for_preset(preset)`
returns `'realistic'` for the `realistic` preset, `'animated'` for the
other five, `None` only when `preset` itself is `None` (the existing
functions' own "ambiguous, don't guess" case). Wired into BOTH paths that
resolve a preset: (1) `apply_format_defaults` — now also sets `render_style
= COALESCE(render_style, ...)` in the SAME `UPDATE` that sets `visual_style`
from the locked channel format, using the identical `preset` it already
resolved (no second guess); (2) `create_video`'s INSERT — derives
`render_style` from whichever of `image_style_override`/`visual_style` the
creator explicitly gave AND `_normalize_style_preset` resolves
unambiguously (checked in that precedence order, matching `_resolve_style`'s
existing priority), else leaves it `None`. Deliberately NOT derived: the
"modeled"/clone path (reference-URL videos hold at `idea_logged` with no
style field set until an out-of-band copy runs later — deriving at INSERT
time would be premature) and any freeform style text that doesn't match one
of the six presets' keywords. No UI/copilot control for setting
`render_style` directly — that rides C14/C15 as specified.

### New Files
| Path | Purpose |
|------|---------|
| `storyengine/backend/migrations/089_video_render_style.sql` | `videos.render_style`, idempotent |
| `storyengine/backend/tests/functional/test_render_style_derivation.py` | 5 tests: `render_style_for_preset()` + the two derivation call chains |

### Modified
| Path | Change |
|------|--------|
| `skills/video-pipeline/shared/channel_profile.py` | `ModelProfile.styles` field (vocabulary docstring) + populated on all 7 registry entries |
| `skills/video-pipeline/shared/model_router.py` | `route_shot_model()` gains `render_style`/`video_model_id` params + the style-palette guardrail cascade; docstring rewritten |
| `skills/video-pipeline/storyboard/coverage.py` | `plan_camera_moves()`/`run_coverage()` gain `render_style`/`video_model_id` kwargs (default `None`), threaded to `route_shot_model()` |
| `storyengine/backend/scripts/coverage_to_app.py` | `generate_coverage_for_video`'s video SELECT gains `render_style, video_model`; passed through to `run_coverage()` |
| `storyengine/backend/channel_format.py` | New `render_style_for_preset()`; `apply_format_defaults()` also sets `render_style` from the same resolved preset |
| `storyengine/backend/routes/videos.py` | `create_video`'s INSERT gains `render_style`, derived from `image_style_override`/`visual_style` via `_normalize_style_preset` + `render_style_for_preset` |
| `storyengine/backend/routes/model_registry.py` | `VideoModelResponse` gains `styles`; `list_models()` populates it from the registry entry |
| `storyengine/schema.sql` | `videos` table gains `render_style` (documented inline) |
| `storyengine/backend/tests/functional/test_scene_model_routing.py` | 6 tests updated to pass an explicit `render_style` (the C12 cascade is now opt-in — see below); 9 new tests for the guardrail itself |
| `storyengine/backend/tests/functional/test_model_registry.py` | 2 new tests: `styles` vocabulary + registry match |
| `skills/video-pipeline/tests/test_coverage.py` | `test_plan_camera_moves_stamps_routed_model_on_shots` updated to pass explicit `render_style`/`video_model_id` (else it became vacuous); 1 new test for the no-style default |

**C12/C13 tests changed by the deliberate default-behavior change** (all in
`test_scene_model_routing.py` unless noted): `test_reveal_purpose_routes_to_hero_tier_model`,
`test_payoff_purpose_routes_to_hero_tier_model`,
`test_establish_purpose_routes_to_atmospheric_tier_model`,
`test_ordinary_static_shot_routes_to_cheap_draft_model` (style switched to
`"animated"` — it's the only palette with a `draft`-tagged model),
`test_none_or_unrecognized_purpose_treated_as_static` (same, `"animated"`),
`test_only_ever_returns_a_wired_model`, `test_multi_shot_hint_routes_to_multi_shot_tier_model`,
`test_fallback_path_never_raises_and_always_returns_a_reason` — each now
passes an explicit `render_style` to keep exercising the C12 cascade;
without it every one would silently hit the new opt-out default instead
(same numeric answer in most cases since `DEFAULT_VIDEO_MODEL ==
"grok-imagine"`, but for the WRONG reason). Plus
`test_coverage.py::test_plan_camera_moves_stamps_routed_model_on_shots`
(same fix, matching style/video_model_id passed to both sides of its
cross-check). `resolve_clip_model`'s own tests were NOT touched — that
function didn't change.

**Verify:** `cd storyengine/backend && ./venv/bin/python -m pytest
tests/functional/test_scene_model_routing.py tests/functional/test_model_registry.py
tests/functional/test_render_style_derivation.py -q` — 38 passed. `./venv/bin/python
-m pytest ../../skills/video-pipeline/tests/test_coverage.py -q` — 8 passed,
1 pre-existing unrelated failure (`test_drops_moment_with_no_angles`,
confirmed identical with this chunk stashed). Confirmed non-vacuous via
`git stash` on `model_router.py`/`channel_profile.py`/`coverage.py`: the new
guardrail tests fail (`TypeError: route_shot_model() got an unexpected
keyword argument 'render_style'` / wrong model picked) against the
pre-change source, pass again after `stash pop`. Full backend suite: 813
passed (797 baseline + 16 new: 9 in `test_scene_model_routing.py` + 2 in
`test_model_registry.py` + 5 in `test_render_style_derivation.py`) / 16
pre-existing failures (same file list as C13) / 1 pre-existing error
(`vault.py`'s `test_api_key` name collision) — zero new failures, confirmed
against a `git stash` baseline run showing the identical 797/16/1 (plus 1
extra transient error from the new test file being untracked — expected,
not a regression). `python -m py_compile` clean on all 9 touched/added
`.py` files. Live column check: `information_schema.columns` on project
`wrromlupsmyzrrcqlucn` shows `render_style` — `text`, nullable, no default.
No frontend files touched (by design; C14/C15 own the UI/copilot).

**Deferred to `tasks/live-verification-queue.md` §C13b**: declaring
`render_style` on a real video and confirming routing actually respects it
end-to-end through a live coverage build (no paid Kie/Anthropic key in this
sandbox).

**Deploy-safety note:** for EXISTING videos (`render_style` NULL on all of
them), routing behavior CHANGES on purpose — `routed_model` recommendations
collapse from C12/C13's purpose-based tier-upgrading back to the video's
own default model (reason now says so explicitly) — but the CLIPS
THEMSELVES are unaffected: C13's `resolve_clip_model` already fell back
identically whenever `routed_model` was unwired/unknown, and a
video-level-model `routed_model` is either wired (accepted, same net
result) or unwired (falls through to `video_model_id` anyway) — so already-
running builds see no generation-path change, only quieter/more
conservative recommendations. For NEW videos with a declared
`render_style` (none exist yet — no UI sets it, only the narrow
auto-derivation paths above), routing now respects the channel's look.
Auto-deploy safe, ff-merge safe.

## C14 — Per-Scene Model Badge + Override Sheet + Channel Look Control (added 2026-07-18)

The `[U]` half of checklist §1.2: makes C12/C13/C13b's per-scene routing
VISIBLE (badge + "why" tooltip) and OVERRIDABLE (one-tap sheet), and
surfaces `videos.render_style` (built in C13b, no control existed for it
until now) as a "Channel look" selector in the Scenes workspace.

**Migration 090** (`storyengine/backend/migrations/090_asset_model_override.sql`,
applied LIVE via Supabase MCP against project `wrromlupsmyzrrcqlucn`,
confirmed via `information_schema.columns`): `assets` gains
`model_override` TEXT, nullable, no default. This is the column
`shared.model_router.resolve_clip_model()` already reserved as its
`scene_override` parameter (C13's docstring: "C14 owns that UI") — C13
wired the precedence logic and called it with `scene_override=None`
everywhere; this chunk is the first thing that ever writes a non-NULL
value into it, and the first thing that reads it back into that parameter.

**Backend wiring (the seam C13 left, now closed):**
- `pipeline_executor.py::run_clip_generation`'s asset SELECT gains
  `model_override`; the per-row resolve call becomes
  `resolve_clip_model(r.get("routed_model"), model_id,
  scene_override=r.get("model_override"))` — an override wins over
  `routed_model`, an unwired override falls through to `routed_model`
  exactly like an unwired `routed_model` falls through to the video
  default (same precedence chain C13 already documented, now actually fed).
- `actions.py::_routed_clip_costs`'s SELECT and per-row price lookup gained
  the identical `model_override` read + `scene_override=` pass-through, so
  the pre-spend quote (`estimate_cost`'s `animate`/`build` verbs) sums the
  SAME resolved price generation will actually charge — a manually
  overridden scene no longer under- or over-quotes.
- `PATCH /api/assets/{id}/model-override` (new, `routes/assets.py`): sets
  or clears (`null`/`""`) one asset's `model_override`. Tenant-scoped
  (404 on a miss), validates a non-empty value against
  `MODEL_REGISTRY[...].wired` (400 otherwise) — the same gate
  `run_clip_generation` itself enforces, so this can never save a choice
  that would silently no-op at generation time.
- `render_style` folded into the EXISTING generic `PATCH /api/videos/{id}`
  (`routes/videos.py::update_video`'s `allowed_fields`) rather than a new
  endpoint — validates `{"animated", "realistic", None}`; `None` is a
  valid write (clears back to "Auto"/undeclared), not a no-op. Also added
  to `get_video`'s SELECT + `VideoDetail` construction (`render_style` was
  written by C13b but never read back by the single-video GET) and to
  `models.py`'s `VideoDetail` Pydantic model.
- `GET /api/videos/{id}/assets` (`routes/videos.py`) now selects
  `routed_model, routing_reason, model_used, model_override` alongside the
  existing columns — none of the four were passed through to the frontend
  before this chunk (checked; C13b's SYSTEM_STATE note assuming
  `routes/videos.py` "already touched" this was for `render_style` on
  `videos`, not these four columns on `assets` — they were still backend-
  only until now).

**Frontend (`ScenesWorkspaceTab.tsx`):**
- Per-scene model badge next to each `SegmentCard`'s `SegmentBadge` label:
  effective model = `model_override > routed_model > video default` before
  a clip exists, `model_used` once it does; label sourced from `["models"]`
  (no hardcoded name/price table); "why" tooltip = `routing_reason`, or
  "Manual override"/"Channel default". A small dot marks a manually
  overridden scene (matches the copilot-UX-map spec: "override badge gets
  a dot so routed vs manual is visually distinct"). Gated on `canAnimate`
  (`videoStageEnabled`) — an images-only plan shows no clip-model badge at
  all rather than a meaningless one (the wiring checklist's fail-safe rule).
- Tap the badge → `ModelOverrideSheet` (built on the existing `Modal`
  primitive): lists every wired model with name + $/clip straight off the
  same `["models"]` query the Clips dropdown already uses, highlights the
  currently-effective one, and a "Use recommendation" button (only shown
  when overridden) that clears back to the router's own pick. Picking a
  model calls `PATCH .../model-override` then invalidates
  `["video-assets", video.id]` so the badge and every cost display refresh
  together.
- "Channel look" select (Auto/Animated/Realistic) added to the existing
  model-controls bar next to Clips, backed by `updateVideo(id, {
  render_style })`; one line of visible helper text appears under the bar
  when a look is declared ("Animated channels stay on Grok — no premium
  upgrades." / the realistic equivalent), plus a fuller explanation on
  hover.

### New Files
| Path | Purpose |
|------|---------|
| `storyengine/backend/migrations/090_asset_model_override.sql` | `assets.model_override`, idempotent |
| `storyengine/backend/tests/functional/test_c14_model_override_and_render_style.py` | 8 tests: the two PATCH endpoints (tenant-scoping, validation, clear-to-null) |

### Modified
| Path | Change |
|------|--------|
| `skills/video-pipeline/shared/model_router.py` | No change — `resolve_clip_model`'s `scene_override` param already existed (C13); this chunk is callers finally feeding it a real value |
| `storyengine/backend/pipeline_executor.py` | `run_clip_generation`'s asset SELECT + resolve call read `model_override` as `scene_override` |
| `storyengine/backend/actions.py` | `_routed_clip_costs`'s SELECT + price lookup read `model_override` as `scene_override` |
| `storyengine/backend/routes/assets.py` | New `PATCH /{asset_id}/model-override`; `ModelOverrideUpdate` Pydantic model |
| `storyengine/backend/routes/videos.py` | `render_style` added to `update_video`'s `allowed_fields` + validation; `get_video`'s SELECT/response gains `render_style`; `get_video_assets`'s SELECT gains `routed_model, routing_reason, model_used, model_override` |
| `storyengine/backend/models.py` | `VideoDetail` gains `render_style` |
| `storyengine/backend/tests/functional/test_c13_clip_model_routing.py` | 3 new tests for override precedence (quote + generation path); helper fixtures gain a `model_override` param |
| `storyengine/frontend/src/lib/api.ts` | `Asset` gains `routed_model`/`routing_reason`/`model_used`/`model_override`; `VideoDetail` gains `render_style`; new `updateAssetModelOverride()` |
| `storyengine/frontend/src/components/production/ScenesWorkspaceTab.tsx` | Per-scene model badge + `ModelOverrideSheet` (new) + "Channel look" select + helper text |
| `storyengine/schema.sql` | `assets` table gains `model_override` (documented inline) |
| `tasks/storyengine-wiring-fix-checklist.md` | §1.2: `[B]`/`[D]`/`[U]` ticked (cumulative C12+C13+C14 work); `[V]` annotated partially-done with the deferral |

**Verify:** `cd storyengine/backend && ./venv/bin/python -m pytest
tests/functional/test_c13_clip_model_routing.py
tests/functional/test_c14_model_override_and_render_style.py -q` — 22
passed. Confirmed non-vacuous via `git stash` on
`actions.py`/`pipeline_executor.py`: the 3 new override-precedence tests in
`test_c13_clip_model_routing.py` fail against the pre-change source (asset
query missing `model_override`), pass again after `stash pop`; the 8 new
endpoint tests (untracked file, unaffected by the stash) fail 7-of-8 with
the routes reverted (the 8th incidentally still 400s for a different
reason — "no valid fields" instead of "invalid value" — both are correct
behavior for their respective code states, not a false pass). Full backend
suite: 824 passed (813 baseline + 11 new: 3 in `test_c13_clip_model_routing.py`
+ 8 in the new file) / 16 pre-existing failures (identical file list to
C13b) / 1 pre-existing error (`vault.py`'s `test_api_key` collision) — zero
new failures, confirmed against a `git stash` baseline run showing the
identical 16/1. `python -m py_compile` clean on all 6 touched/added `.py`
files. Frontend: `npx tsc --noEmit` clean; `npm run build` clean (required
`NEXT_PUBLIC_API_URL` set and `npm install` first — neither installed in
this sandbox by default, both are pre-existing project requirements
unrelated to this chunk). Live column check: `information_schema.columns`
on project `wrromlupsmyzrrcqlucn` shows `model_override` — `text`,
nullable, no default, alongside the existing `routed_model`/
`routing_reason`/`model_used`.

**Deferred to `tasks/live-verification-queue.md` §C14** (exact recipe
there): a real Playwright pass — badges rendering with real routing data,
the override sheet actually changing `assets.model_override`, the Channel
look control actually changing `videos.render_style` — and the full
checklist §1.2 `[V]` (real clip generation on an overridden scene,
confirming `model_used`/the ledger/the badge all agree, and that the quote
a creator confirmed matches what was actually spent). Both require a live
video with real scene assets behind it; unlike `GET /api/models` (C03's
no-DB `DEV_MODE` case, which only reads the in-process `MODEL_REGISTRY`),
`GET /api/videos/{id}/assets` queries the real `assets` table — there is no
no-DB path for it in this sandbox.

**Deploy-safety note:** every new/changed column is nullable and additive
(`model_override` defaults NULL on every existing row); `resolve_clip_model`
falls through to EXACTLY pre-C14 behavior whenever `model_override` is
unset (every asset row today); the new endpoints are additive (no existing
route's behavior changed — `update_video`'s `allowed_fields` gained one
entry, `get_video`/`get_video_assets` gained SELECT columns that were
already nullable in the schema); the new UI is additive and gated
(`canAnimate`/`videoStageEnabled`) so an images-only plan renders nothing
new. Backend and frontend changes ship together in this one chunk — no
backend-ahead-of-frontend or frontend-ahead-of-backend gap: the frontend
reads exactly the four asset fields and the one video field this chunk's
backend changes newly serve, and every backend change is additive so an
OLD deployed frontend (pre-C14) simply ignores the new fields it doesn't
know about. Auto-deploy safe, ff-merge safe.
