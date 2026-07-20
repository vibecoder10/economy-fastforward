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

---

## C15 — Copilot Routing Conversation + Itemized Per-Tier Confirm Cards (added 2026-07-18)

The conversational door for C11-C14's per-scene router (checklist §1.2
`[B]`/`[U]`, `tasks/storyengine-copilot-ux-map.md` §1): the copilot's paid
`animate`/`build` confirm now itemizes the SAME quote by model/tier instead
of one blended number — "Scene 12 is your reveal — Veo Quality ($1.25);
Grok elsewhere. Total $4.20 vs $25 all-premium."

**One resolver, no parallel math (`storyengine/backend/actions.py`):**
- `_routed_clip_costs` (C13/C14's money-summing query) was refactored into
  `_routed_clip_rows()` — the SAME query, now also selecting `scene` and
  `routing_reason` alongside `routed_model`/`model_override` — plus a
  `_resolved_price(row, video_model)` one-liner wrapping
  `resolve_clip_model()`'s call. Both the real quote (`_routed_clip_costs`,
  unchanged behavior) and the new itemization (`cost_breakdown`) call these
  same two functions — one query, one precedence call, two views of the
  identical row set.
- New `cost_breakdown(tenant_id, video_id, verb, scene, summary)`: groups
  each row's resolved price by `model_id` into `{model_id, display_name,
  tier, count, subtotal}` lines. `total = round(sum(raw_prices), 2)` —
  the IDENTICAL formula `estimate_cost`'s animate/build branches already
  use — so the itemized total always equals what the confirm card's plain
  `cost_text` already showed. Per-line subtotals go through a new
  `_reconcile_rounding()` helper: round each group to cents, then nudge the
  largest group by any leftover penny, so
  `round(sum(line["subtotal"] for line in lines), 2)` always equals
  `total` exactly — independent per-group rounding can otherwise drift a
  cent from rounding the whole sum once.
- `all_premium_total`: `len(rows) * _premium_reference_price()` (the
  cheapest per-clip price among wired `tier=="premium"` models — today just
  `veo-3.1-quality`, $1.25). Explicitly illustrative — never a second real
  cost path, only "what if every shot used the flagship tier instead."
- `hero_scenes`: rows whose resolved model's `tier=="premium"`, each
  carrying its OWN `routing_reason` straight from the asset row —
  verbatim, never re-derived, per the checklist's "reuse routing_reason —
  don't re-derive" requirement.
- Returns `None` with the exact same guards `estimate_cost`'s animate/build
  branches already use (no shot plan before pictures exist; an empty
  per-scene quote that falls back to a flat guess; any non-clip verb) —
  callers fall back to the plain `cost_text` unchanged in those cases.
- New `guardrail_note(render_style)`: one sentence mirroring
  `shared.model_router.route_shot_model`'s own C13b guardrail phrasing
  exactly ("channel is set to Animated, so everything stays on Grok." /
  "channel is set to Realistic, so shots route across the photoreal
  lineup." / "no channel look set — using your default model.").
- `video_summary()` gained `render_style` (additive SELECT column on the
  existing `videos` query) so the copilot's confirm-building code can read
  the channel's declared look without a second round-trip.

**Copilot phrasing (`storyengine/backend/routes/chat.py`):**
- `_handle_copilot`'s paid-confirm branch calls `cost_breakdown` right
  after `estimate_cost`, then folds three things into the confirm `intro`
  text when a breakdown exists: the itemized "N × Model ($X.XX)" lines, the
  all-premium comparison ("vs $X.XX all-premium", only when it's actually
  higher), and — only for a genuinely MIXED plan (more than one model in
  the breakdown) — up to 3 hero scenes by number with their real
  `routing_reason`, plus the guardrail note.
- `_confirm_card()` gained an optional 4th `breakdown` param: the card dict
  gains a `"breakdown"` key ONLY when there's something to itemize
  (`breakdown["lines"]` non-empty) — a call with no breakdown arg (the
  pre-C15 call shape, still used everywhere else) produces the byte-
  identical pre-C15 card.
- `agent_brain.py::_tool_cost`'s "Finishing adds ~$X" tail optionally
  itemizes the same way (a cheap add, per the checklist's "if it can
  cheaply include the same breakdown, do it there too") — wrapped in its
  own try/except so a broken/erroring `cost_breakdown` call never breaks
  the "how much has this cost?" read (falls back to the plain tail).

**Frontend (additive only):**
- `ChatCard` (`storyengine/frontend/src/lib/api.ts`) gained an optional
  `breakdown?: ChatCostBreakdown` (`lines`/`total`/`all_premium_total`/
  `hero_scenes`, mirroring the backend dict field-for-field).
- `ConfirmActionCard` (`storyengine/frontend/src/components/chat/
  ChatCore.tsx`) renders the itemized lines + all-premium comparison line +
  up to 3 hero-scene call-outs in a small panel between the card's label
  and its Do-it/Cancel buttons, ONLY when `card.breakdown` is present and
  non-empty — otherwise renders exactly the pre-C15 card (no visual
  change for any verb/state with nothing to itemize).

### New Files
| Path | Purpose |
|------|---------|
| `storyengine/backend/tests/functional/test_c15_itemized_cost_breakdown.py` | 13 tests: breakdown-sums-to-total, all-premium comparison, routing_reason passthrough, uniform-plan/no-hero case, both `estimate_cost`-matching None-guards, non-clip-verb None, `guardrail_note` wording, `_confirm_card` payload shape |

### Modified
| Path | Change |
|------|--------|
| `storyengine/backend/actions.py` | `_routed_clip_costs` refactored onto new `_routed_clip_rows`/`_resolved_price`; new `cost_breakdown()`, `guardrail_note()`, `_premium_reference_price()`, `_reconcile_rounding()`; `video_summary()` gains `render_style` |
| `storyengine/backend/routes/chat.py` | Imports `cost_breakdown`/`guardrail_note`; `_confirm_card()` gains optional `breakdown` param; `_handle_copilot`'s confirm-building block folds itemization/hero-scenes/guardrail into `intro` and the card |
| `storyengine/backend/agent_brain.py` | `_tool_cost`'s finishing-adds tail optionally itemizes via `cost_breakdown`, fail-soft |
| `storyengine/backend/tests/functional/test_agent_brain_cost_tool.py` | 2 new tests: itemized tail present when `cost_breakdown` available; fail-soft when it errors |
| `storyengine/frontend/src/lib/api.ts` | `ChatCard` gains optional `breakdown`; new `ChatCostBreakdown`/`ChatCostBreakdownLine` types |
| `storyengine/frontend/src/components/chat/ChatCore.tsx` | `ConfirmActionCard` renders the itemized panel when `card.breakdown` is present |
| `tasks/storyengine-wiring-fix-checklist.md` | §1.2 C15 line ticked with summary |
| `tasks/live-verification-queue.md` | New §C15 deferral (live chat round-trip recipe) |

**Verify:** `cd storyengine/backend && ./venv/bin/python -m pytest
tests/functional/test_c15_itemized_cost_breakdown.py
tests/functional/test_c13_clip_model_routing.py
tests/functional/test_c14_model_override_and_render_style.py
tests/functional/test_agent_brain_cost_tool.py -q` — 41 passed. Confirmed
non-vacuous via `git stash` on `actions.py`/`agent_brain.py`/`routes/chat.py`
(the new test file and the 2 new `test_agent_brain_cost_tool.py` tests are
untracked/uncommitted, unaffected by the stash): 12 of the 13 new C15-file
tests fail against the pre-change source (2 are `_confirm_card`-signature/
payload tests that TypeError or assert against the missing 4th param; the
other 10 raise/assert against the missing `cost_breakdown`/`guardrail_note`
functions or their absent effects); the 1 remaining test
(`test_confirm_card_omits_breakdown_key_entirely_when_absent`) legitimately
still passes pre-change — it pins the pre-C15-compatible "no breakdown arg"
call shape, which was never broken. Full backend suite: 839 passed (824
baseline + 15 new: 13 in the new C15 file + 2 in
`test_agent_brain_cost_tool.py`) / 16 pre-existing failures (same file list
as C14) / 1 pre-existing error (`vault.py`'s `test_api_key` collision) —
zero new failures. `python -m py_compile` clean on all 5 touched/added `.py`
files. Frontend: `npx tsc --noEmit` clean; `npm run build` clean (required
`NEXT_PUBLIC_API_URL` set — same pre-existing project requirement as C14).

**Deferred to `tasks/live-verification-queue.md` §C15** (exact recipe
there): a real chat round-trip — seed a mixed-routing video, type "animate
scene 3" in the dock, confirm the itemized card/text and the "how much has
this cost?" tail both show the real numbers, tap Do It, confirm the clips
that generate match what was itemized. Requires a live LLM call (the
copilot's classifier/agent-brain) and a live video with real scene assets;
no no-DB path exists for either in this sandbox.

**Deploy-safety note:** every new field is additive and conditionally
populated — `breakdown` only ever appears on the confirm card when
`cost_breakdown` actually has lines to show; `render_style` was already
read/written by C13b/C14, this chunk only adds it to one more read
(`video_summary`). An old frontend build (pre-C15) simply never reads the
new `breakdown` key and renders identically; a new frontend against an old
backend that never sends `breakdown` also renders identically (the
component's `hasBreakdown` check is `!!breakdown && breakdown.lines.length
> 0`, false on `undefined`). No existing field, endpoint, or card shape
changed — auto-deploy safe, ff-merge safe.

## C15a — MONEY GAP: Quote on the Home Producer's "Make it" Tap (added 2026-07-18)

The 2026-07-18 director-gap audit found the ONE paid path in the entire chat
surface that skipped the quote+confirm law every other paid verb obeys: the
home chat's `ProductionPlanCard` "Make it" button fires `_handle_approve` →
`create_video` → `_make_autobuild_step(..., target="pictures")`
(`storyengine/backend/routes/chat.py` ~L478-549) — a real paid autobuild
(research/script → ~scenes × 6 × PICTURE_COST worth of pictures) with no cost
shown or confirmed anywhere before it fires.

**Why shape (a), not a second confirm card:** C15's itemized
`cost_breakdown()` needs a real shot plan (`storyboard/coverage.py`'s
`plan_camera_moves`), which doesn't exist until AFTER the script is written —
exactly why `cost_breakdown` already returns `None` pre-plan. There is
nothing real to itemize at plan time, so a `_confirm_card`-style breakdown
round-trip would be theater. Instead the ProductionPlanCard itself now
carries an honest, hedged estimate line, making the single existing "Make it"
tap informed consent rather than a blind one — no new UI step, no new tap.

**Backend (`storyengine/backend/actions.py`):**
- New `estimate_plan_cost(video_length_minutes=None) -> tuple[float, str,
  int]`: a thin wrapper, NOT a new cost formula. No video row exists at plan
  time, so there's no real `video_summary()` to hand `estimate_cost`.
  **Orchestrator review (same day):** the first pass ignored the plan's own
  `video_length_minutes` entirely — a flat ~5-scene guess for every length,
  meaning a 20-30 min plan showed the SAME "≈$1.50" a 1-min plan showed, then
  spent several times that once pictures actually generated. Fixed by
  deriving the real scene count from length via the SAME formula the live
  script generator already targets, imported verbatim (no new ratio):
  `VideoConfig.act_count` (`skills/video-pipeline/orchestrator/
  pipeline_config.py:53` — `max(3, min(6, video_length_minutes // 2)) if
  video_length_minutes >= 3 else 1`). Traced end to end that this is the
  REAL number, not just a plausible-looking one: `VideoConfig` (built from
  this exact `video_length_minutes`) is handed to `script_generator.
  generate_script()`, whose prompt instructs "Structure it in {act_count}
  acts" (`script_generator.py:638/643`); `brief_translator.
  _write_script_records` then writes exactly ONE `scripts` row per act
  ("one per act", `scene_number=act_num`); `SupabaseAdapter.
  create_script_record` inserts with `scene=scene_number` — so `act_count`
  IS the real "scenes" number `video_summary()` later counts and this same
  `estimate_cost` build branch prices. Builds the synthetic summary
  `{"model": "grok-imagine", "status": "idea_logged", "scenes":
  <derived act_count>, "pics": 0}` and calls `estimate_cost(None, None,
  "build", None, summary)` — the SAME pre-pictures math (`cost = scenes * 6
  * PICTURE_COST`) that branch already ran, just fed a real scene count
  instead of 0. `video_length_minutes=None` (or an invalid value —
  clamped/caught, never raises) keeps the EXACT pre-existing flat-guess
  behavior: `scenes=0` routes to `estimate_cost`'s own "scenes or 5"
  fallback unchanged. Returns a 3rd value, `scenes_used` (the derived count,
  or 5 on fallback — read off the identical `summary["scenes"] or 5`
  expression `estimate_cost` itself evaluates, not a second computation), so
  the card text can name its own scene count. Honest cap surfaced, not
  hidden: `act_count` maxes at 6 for any video >=12 min — a real property of
  the live formula — so a 20-min and a 30-min quote are identical, both
  capped at the 12-min figure.

**Backend (`storyengine/backend/routes/chat.py`):**
- Imports `estimate_plan_cost as _estimate_plan_cost`.
- New `_stamp_plan_estimate(data)`: given a producer turn's raw JSON `data`,
  if `data["plan"]` is a dict, reads `plan.spec.video_length_minutes` (may be
  missing/None — handled) and calls `_estimate_plan_cost(minutes)`, then sets
  `plan["estimated_cost"]` (float) and `plan["estimated_cost_text"]` (e.g.
  `"Making this ≈ $1.80 — pictures for ~6 scenes (rough estimate; refined
  once the script's written)."` for a 20-min plan, vs `"≈ $0.30 — pictures
  for ~1 scenes"` for a 1-min plan). No-ops silently (no KeyError, no
  mutation) when there's no plan yet (an "asking" phase turn) or the plan is
  malformed (defensive — producer JSON is LLM-authored); wrapped in its own
  try/except so a broken estimate call never blocks the plan turn itself.
  chat.py still does zero scene-count math of its own — `scenes_used` comes
  straight from `estimate_plan_cost`.
- Called from BOTH home-producer plan-emission sites, right after
  `_annotate_style_recommendation` and before `_apply_and_merge_profile_ops`:
  `_seed_producer` (the onboarding hand-off) and the main intake turn inside
  `chat_turn()`. Both call sites needed the fix — this is the same
  "call-site drift" class of bug C04's `_resolve_producer_client` fix
  guarded against, so both are now source-locked by a test.

**Frontend (additive only, UNCHANGED by the length-scaling follow-up — only
the server-side wording/number changed):**
- `ProductionPlan` (`storyengine/frontend/src/lib/api.ts`) gains optional
  `estimated_cost?: number` / `estimated_cost_text?: string`.
- `ProductionPlanCard` (`storyengine/frontend/src/components/chat/
  ChatCore.tsx`) renders a new "Estimated cost" `Section` (new
  `CircleDollarSign` icon import from `lucide-react`) directly above the
  Make-it/Cancel row, ONLY when `plan.estimated_cost_text` is truthy — an
  older frontend build simply never reads the key and renders byte-identical
  to before; a plan payload from an older/legacy conversation transcript
  (persisted before this fix, no estimate keys at all) renders identically
  too, since the guard is `!!plan.estimated_cost_text`.

### New Files
| Path | Purpose |
|------|---------|
| `storyengine/backend/tests/functional/test_c15a_plan_cost_quote.py` | 12 tests: `estimate_plan_cost` matches a direct `estimate_cost` call on the identical synthetic summary when length is unknown (no-parallel-math proof) + is never zero/negative; scene count for every tested length equals `VideoConfig.act_count` exactly (sourcing proof) and cost = scenes×6×PICTURE_COST; cost scales monotonically with length AND a 30-min plan quotes strictly more than a 1-min plan (the exact regression pinned); a 12/20/30-min plan all quote the SAME capped figure (honest-cap proof); `_stamp_plan_estimate` adds a length-scaled quote naming its own scene count; a 1-min vs 20-min plan produce different quotes; missing/None length falls back to the original flat guess; no-ops (no KeyError) on a plan-less "asking" turn; no-ops on a malformed (non-dict) plan; a legacy pre-fix plan payload has no estimate keys, and history-hydration (`get_conversation_for_video`) never calls the stamp; source lock that BOTH `_seed_producer` and `chat_turn` call `_stamp_plan_estimate` |

### Modified
| Path | Change |
|------|--------|
| `storyengine/backend/actions.py` | `estimate_plan_cost()` gains a `video_length_minutes` param, derives the real scene count via `orchestrator.pipeline_config.VideoConfig.act_count`, returns a 3rd `scenes_used` value |
| `storyengine/backend/routes/chat.py` | `_stamp_plan_estimate` threads `plan.spec.video_length_minutes` into `_estimate_plan_cost`; card text now names its own scene count |
| `storyengine/frontend/src/lib/api.ts` | `ProductionPlan` gains optional `estimated_cost`/`estimated_cost_text` |
| `storyengine/frontend/src/components/chat/ChatCore.tsx` | `ProductionPlanCard` renders the new "Estimated cost" section when present; `CircleDollarSign` added to the `lucide-react` import |
| `tasks/storyengine-wiring-fix-checklist.md` | C15a line ticked with summary |
| `tasks/live-verification-queue.md` | New §C15a deferral (live "Make it" tap recipe) |

## C15b — Director Review Loop, Part 1: Inline Storyboards + Per-Scene Approve (added 2026-07-18)

Ryan's Hermes-director vision — "the copilot sends me the storyboards for
scene 1, I approve or tell it what's wrong" — had one half already built
(revise-by-description: prompt studio → `_rewrite_prompt` →
`redraw_asset_image`) and two missing: the chat surface never showed an
image at all, and there was no per-scene approve verb (only whole-video
`approve_cast`/`approve_environments` gates existed). This chunk closes
both, reusing the existing classify → dispatch → confirm-card machinery
instead of adding a parallel path.

**Backend (`storyengine/backend/actions.py`):**
- New `approve_scene` verb in `ACTIONS`: `{"runner": "approve_scene", "paid":
  False, "needs": "pictures", ...}`. Free and reversible (the `assets.status`
  column can always be flipped again), so it deliberately carries NO confirm
  card — `routes/chat.py`'s existing `if not cfg["paid"]:` branch runs it
  straight from the classifier's pick, same as `approve_cast`/`lock`/`advance`.
- New `_runner_approve_scene(tenant_id, video_id, background_tasks, pending)`:
  reads `pending["scene"]`; `None` → a clarifying question, no write attempted.
  Otherwise a single tenant+video+scene scoped `UPDATE assets SET
  status='approved' ... WHERE video_id=$1 AND tenant_id=$2 AND scene=$3` — the
  same column `routes/assets.py`'s per-asset `approve`/`batch-approve`
  endpoints already write, just scoped to a whole scene in one query instead
  of one asset id or a hand-picked list. Parses the `UPDATE N` command tag to
  report how many shots were touched; 0 rows → "nothing to approve there"
  instead of a false "approved ✓". Registered in `RUNNERS["approve_scene"]`.

**Backend (`storyengine/backend/routes/chat.py`):**
- New `kind: "show"` alongside the existing `read|action|prompt` — dispatched
  in `_handle_copilot` right after the `kind == "prompt"` branch, before the
  paid-verb legality gate (mirrors how prompt-studio bypasses the verb table
  entirely). Both decision-schema copies got the new vocabulary: the inline
  fallback classifier prompt (`_handle_copilot`'s own JSON prompt) AND
  `agent_brain.py::_decision_schema()`/its system prompt — kept in sync so
  neither the agent-brain path nor its legacy-classifier fallback can regress
  independently (same class of drift C04's `_resolve_producer_client` guard
  and C15a's dual-call-site test protect against).
- New `_media_proxy_url(url)`: converts a stored Drive link (`?id=`/`&id=` or
  `/d/<id>/` share-link shape) into `{PUBLIC_MEDIA_BASE}/api/media/drive/{id}`
  — the SAME conversion `pipeline_executor.py`'s per-clip `_proxy_url` and
  `routes/characters.py`'s `_fetch_image_bytes` already do (Drive's public
  links unpredictably degrade into HTML interstitials; the authorized proxy
  streams reliably). A URL that was never a Drive link (e.g. the Supabase
  storage backend's own public URL) passes through unchanged — it was never
  a Drive link to convert, matching the existing precedent exactly. Never
  returns a raw `drive.google.com` URL.
- New `_handle_show_op(tenant_id, video_id, summary, data, ui_context,
  _reply)`: scene comes from the classifier's `data["scene"]` or falls back
  to `ui_context["scene"]` (the page the creator is looking at); neither
  present → a clarifying question. Query is tenant+video+scene scoped
  (`WHERE video_id=$1 AND tenant_id=$2 AND scene=$3`) and capped via both the
  SQL `LIMIT $4` (`_MAX_SHOW_IMAGES = 6`) AND a client-side `rows[:6]` slice
  (defense-in-depth — a turn can never surface more than 6 images regardless
  of what the query returns). No pictures yet for that scene → a friendly
  offer to generate them naming a REAL quote (`actions.estimate_cost(...,
  "images", scene, summary)` — the same per-scene pricing the "images" verb's
  own confirm card already uses, no second price path), not an empty/broken
  card. Every image URL is run through `_media_proxy_url` before it ever
  reaches the card payload. Card shape (new, additive — see below); reply
  text nudges toward the new approve verb ("... or "approve scene N" if
  these are good").
- `agent_brain.py`'s `run_copilot_brain` system prompt and `_decision_schema`
  gained matching `kind=show`/`approve_scene` guidance so the smarter
  tool-using loop makes the identical decision the fallback classifier would.

**New card shape** (`{"id": "scene_boards", "label": "Scene 2 storyboards",
"type": "single", "options": [], "images": [{"url":
"https://storyengine.dev/api/media/drive/FILE1", "label": "Scene 2 · shot 1",
"asset_id": "asset-1", "scene": 2, "index": 1}, ...]}`) — additive `images`
field only ever appears on this card; every other card (`confirm_action`,
`prompt_apply`, `secure_key`, selector cards) is byte-identical to before.

**Frontend (`storyengine/frontend/src/lib/api.ts`):**
- New `ChatCardImage` interface (`url`, `label`, `asset_id`, `scene`,
  `index`); `ChatCard` gains optional `images?: ChatCardImage[]` — absent on
  every pre-C15b card and on every card type that isn't `scene_boards`.

**Frontend (`storyengine/frontend/src/components/chat/ChatCore.tsx`):**
- `MessageThread` now renders a `SceneBoardsGrid` under ANY assistant
  message's card that carries a non-empty `images` array — gated on the
  field, not the card id, so an old frontend build (field absent) and an old
  backend build (key never sent) both render byte-identical to pre-C15b.
  Unlike the ephemeral `confirm_action`/`prompt_apply` cards (which only ever
  render for the LAST turn), the boards persist in every past message so they
  stay visible when scrolling back through the conversation.
- `SceneBoardsGrid`: a 3-column thumbnail grid (capped at 6 client-side too),
  each tile a `<a target="_blank">` to the full-size proxied URL (the simple
  fallback door the checklist explicitly allows — `ScenesWorkspaceTab.tsx`'s
  `BoardLightbox` is a private, unexported component in a different file, so
  reaching into it would mean exporting/refactoring a component this chunk
  doesn't otherwise touch). A failed image swap to its label text instead of
  the browser's broken-image icon (`onError` + per-image `broken` state).

**Scenes tab approve-button gap (found, not fixed here):** the CURRENT Scenes
tab (`ScenesWorkspaceTab.tsx`/`SegmentCard`) has NO approve affordance at
all — no `status` field read, no approve button, no `approveAsset`/
`batchApproveAssets` call anywhere in that file. Those calls only exist in
the older, still-linked `/review` page (`app/review/page.tsx` +
`storyboard-viewer.tsx`) — a different, asset-by-asset review flow. Per the
checklist's own instruction ("note it as a gap for the orchestrator rather
than building new tab UI in this chunk"), no new Scenes-tab UI was built
here; `approve_scene` today is chat-only until a future chunk adds a
scene-level approve control to `SegmentCard`.

**Tests:** new `storyengine/backend/tests/functional/
test_c15b_show_and_approve_scene.py` (18 tests) — `approve_scene` registry
shape + free/no-confirm; no-scene clarifying question with NO write attempted;
tenant+video+scene-scoped UPDATE (asserts the WHERE clause AND the exact
bound param tuple `(video_id, tenant_id, scene)`); a different tenant gets its
own scoped call (no leaked/hardcoded tenant); zero-rows → "nothing to
approve"; singular/plural shot wording; `_media_proxy_url` converts both
Drive URL shapes and passes non-Drive URLs through unchanged (`None`
in/`None` out); `_handle_show_op` — no-scene clarifying question, `ui_context`
fallback, tenant+video+scene-scoped+capped query (an 8-row fake response
proves the client-side cap independent of the SQL LIMIT), every returned
image URL is asserted to NOT contain `drive.google.com` (negative check, not
just a shape check) and DOES contain `/api/media/drive/`, empty-scene offers
a real quote, reply nudges toward `approve_scene`; both decision-schema
copies (`agent_brain._decision_schema()` and the `_handle_copilot` source)
carry the new `show`/`approve_scene` vocabulary. All 18 confirmed non-vacuous
via `git stash` (every test fails against the pre-C15b source — 15 with
`AttributeError`/`KeyError` on the missing function/verb, 2 on the missing
schema vocabulary, 1 on the missing registry entry).

Full backend suite: 869 passed (851 baseline + 18 new) / 16 pre-existing
failures (identical file list to C15a) / 1 pre-existing error — zero new
failures. `python -m py_compile` clean on all three touched `.py` files.
Frontend: `npx tsc --noEmit` clean; `npm run build` clean (with
`NEXT_PUBLIC_API_URL` set — the sandbox has no `.env.production`, a
pre-existing, unrelated condition of this checkout, not a C15b regression).

**Deploy-safe:** additive only in both directions. New backend + old
frontend: the frontend never reads `card.images`, so a "show" card renders
its text only (a bit less useful, never broken); a chat.py/agent_brain.py
`show`/`approve_scene` addition is inert without a matching frontend build,
but the assistant TEXT reply always carries the substance either way. Old
backend + new frontend: `ChatCore.tsx`'s new grid render is gated on
`card.images?.length`, which is `undefined`/falsy on every payload an old
backend sends — renders byte-identical to pre-C15b. No DB migration, no new
generation/paid path, no changed request/response shape on any EXISTING
card or verb. Auto-deploy safe, ff-merge safe.

**Deferred to `tasks/live-verification-queue.md` §C15b:** a real chat
round-trip — "show me scene 2's boards" → see the images inline → "approve
scene 2" → confirm the specific scene's assets flip to `approved` in the DB
and no other scene's/tenant's rows move (no paid key in the sandbox to drive
a real video through to pictures).

### New Files
| Path | Purpose |
|------|---------|
| `storyengine/backend/tests/functional/test_c15b_show_and_approve_scene.py` | 18 tests covering `approve_scene` (registry, scoped UPDATE, tenant isolation, zero-row wording), `_media_proxy_url` (both Drive URL shapes, non-Drive passthrough, None-safety), `_handle_show_op` (scoping, capping, proxy-only URLs, empty-scene quote, approve-verb nudge), and both decision-schema copies carrying the new vocabulary |

### Modified
| Path | Change |
|------|--------|
| `storyengine/backend/actions.py` | New `approve_scene` verb (`paid=False`, `needs="pictures"`) + `_runner_approve_scene` (tenant+video+scene-scoped `UPDATE assets SET status='approved'`), registered in `RUNNERS` |
| `storyengine/backend/routes/chat.py` | New `kind="show"` dispatch + `_handle_show_op` + `_media_proxy_url`; fallback classifier prompt and JSON schema gain `show`/`approve_scene` vocabulary |
| `storyengine/backend/agent_brain.py` | `_decision_schema()` and `run_copilot_brain`'s system prompt gain matching `show`/`approve_scene` vocabulary |
| `storyengine/frontend/src/lib/api.ts` | New `ChatCardImage` interface; `ChatCard` gains optional `images?: ChatCardImage[]` |
| `storyengine/frontend/src/components/chat/ChatCore.tsx` | `MessageThread` renders a new `SceneBoardsGrid` under any card carrying `images`; new `ChatCardImage` type import |
| `tasks/storyengine-wiring-fix-checklist.md` | C15b line ticked with summary |
| `tasks/live-verification-queue.md` | New §C15b deferral (live show/approve round-trip recipe) |

**Verify:** `cd storyengine/backend && ./venv/bin/python -m pytest
tests/functional/test_c15a_plan_cost_quote.py -q` — 12 passed. Confirmed
non-vacuous via `git stash` on `actions.py`/`routes/chat.py` (the new test
file is untracked, unaffected by the stash) TWICE — once for the original
fix, once for the length-scaling follow-up (8 of the 12 current tests fail
against the pre-follow-up source: `TypeError`/`ValueError` on the changed
`estimate_plan_cost` signature, or the exact "1-min == 20-min" regression the
review flagged; the other 4 legitimately still pass, pinning behavior that
was never broken). Full backend suite: 851 passed (839 baseline + 12 new,
was 846/7 before this follow-up) / 16 pre-existing failures (same file list
as C15) / 1 pre-existing error (`vault.py`'s `test_api_key` collision) —
zero new failures. `python -m py_compile` clean on both touched `.py` files.
Frontend: `npx tsc --noEmit` clean; `npm run build` clean (required
`NEXT_PUBLIC_API_URL` set in-sandbox — same pre-existing project requirement
as C14/C15) — no frontend files touched by the length-scaling follow-up,
re-verified anyway since the card's wording changed server-side.

**Example estimates (verified in-sandbox):** 1 min → 1 scene → ≈$0.30; 3-5
min → 3 scenes → ≈$0.90; 10 min → 5 scenes → ≈$1.50 (same figure the
original flat-guess fallback also lands on, coincidentally); 12-30 min → 6
scenes (capped) → ≈$1.80; no length yet → falls back to the original 5-scene
guess → ≈$1.50 (unchanged from the first pass).

**Deferred to `tasks/live-verification-queue.md` §C15a** (exact recipe
there): a fresh home chat conversation through to a plan, confirming the
"Estimated cost" line renders with a real, length-scaled `≈$` figure naming
its own scene count, tapping "Make it", and confirming the autobuild
proceeds exactly as before (unchanged plumbing — only the display quote is
new). Requires a live LLM producer call (no no-DB path exists for
`call_producer` in this sandbox).

**Deploy-safety note:** both new fields (`estimated_cost`,
`estimated_cost_text`) are additive and only ever populated on `plan` when a
plan exists — old frontend + new backend: the old build never reads the two
new keys, so `ProductionPlanCard` renders byte-identical to before (no
runtime error, no layout shift); new frontend + old backend: the old backend
never sends the keys, so the new "Estimated cost" `Section`'s `!!plan.
estimated_cost_text` guard is false and the section simply doesn't render —
the rest of the card (look/story/titles/thumbnails/Make-it button) is
unchanged either direction. No existing field, endpoint, or card shape
changed, and `_handle_approve`'s create+autobuild plumbing is completely
untouched (only the plan payload the creator sees before tapping "Make it"
changed) — auto-deploy safe, ff-merge safe.

## C15c — Director Memory: Durable Preference Store (added 2026-07-18)

Ryan's vision: a correction said once ("the kitten is gray", "never use
premium models on Poco") becomes a STANDING preference the chat remembers
across conversations and videos — before this chunk, only the transcript
persisted, so every correction had to be re-said. Scope kept tight per the
checklist: store + hydrate + recall, explicit instructions only, no
auto-learning.

**Database (migration `091_director_preferences.sql`, applied LIVE via
Supabase MCP against `wrromlupsmyzrrcqlucn`, confirmed via
`information_schema.columns`):** new table `director_preferences` (`id`,
`tenant_id` FK, `scope` — the literal `'channel'` or a video_id's text form,
`text` — the creator's words verbatim, `source` — always `'user'` this
chunk, `active` bool for soft-delete, `created_at`/`updated_at`), index on
`(tenant_id, scope, active, created_at DESC)`. RLS enabled, no policies
(playbook §7 pattern — the backend connects as `postgres`, which bypasses
RLS; proven safe already for `secrets`/`static_reference_cache`/
`channel_video_retention`, migration 083). A real table was chosen over
JSONB-on-`channel_profiles` (the existing `creator_brief` pattern) because
preferences need to be LISTED individually, DELETED individually, and
scoped per-video as well as per-channel — a JSONB blob keyed by onboarding
field names has no row identity for any of that.

**Backend (`storyengine/backend/routes/chat.py`), mirrors the existing
`_save_creator_brief`/`_hydrate_creator_brief` pattern (fail-soft
everywhere — a memory DB error never breaks a chat turn):**
- `_save_preference(tenant_id, text, scope)` — INSERT, verbatim text
  (trimmed, never paraphrased), fail-soft.
- `_list_preferences(tenant_id, video_id=None)` — active rows for
  `scope IN ('channel', <video_id if given>)`, tenant-bound, newest first,
  capped at `_PREF_CAP=20`, fail-soft `-> []`.
- `_preferences_brief(tenant_id, video_id=None)` — the additive
  "STANDING PREFERENCES" system-prompt block both chats hydrate every turn;
  numbers 1..N newest-first, tags video-scoped rows `(this video only)`,
  length-capped at `_PREF_BLOCK_MAX_CHARS=3000`, fail-soft `-> ""`.
- `_deactivate_preference(tenant_id, ref, video_id=None)` — "forget #N" /
  "forget that" / text match, in order: numeric position (matches the same
  newest-first numbering hydration shows), exact text, substring, then a
  generic reference ("that"/"it"/"last"/...) falls back to the single
  most-recent active preference. Soft-delete only (`UPDATE ... SET
  active=false`, never `DELETE`). Fail-soft `-> (False, "")`.
- `_handle_remember_op`/`_handle_forget_op` — the in-video co-pilot's
  `kind=="remember"`/`kind=="forget"` branches; `remember` defaults
  `scope='channel'` unless the model explicitly says `scope='video'`
  (mapped to `str(video_id)`).
- `_apply_profile_ops` gained `"remember"`/`"forget"` ops for the HOME
  producer chat (always channel-scoped there — home chat has no single
  "current video" in scope, unlike the in-video co-pilot).
- Hydration wired into BOTH system-prompt builders: `chat_turn`'s
  `system_prompt` build (`+ await _preferences_brief(tenant_id)`, channel-
  wide only) and `_handle_copilot`'s `summary_with_assets`
  (`+ await _preferences_brief(tenant_id, video_id)`, channel-wide + this
  video's own) — this is what flows into `agent_brain.run_copilot_brain`'s
  system prompt too (it receives `summary_with_assets` as `summary_line`),
  so the tool-using brain sees the same preferences the fallback classifier
  does with no separate wiring.

**Classification (both decision paths, kept in sync — same class of drift
C04's `_resolve_producer_client` guard and C15a/C15b's dual-call-site tests
protect against):**
- `agent_brain.py`'s `_decision_schema()` and `run_copilot_brain`'s system
  prompt gained `kind: "remember"|"forget"` + a `scope` field, with guidance
  to trigger on "always...", "never...", "remember that...", "from now
  on..." (verbatim capture, never paraphrased) and to treat a plain "what do
  you remember?" as `kind=read` answered from the hydrated list, not a
  remember/forget op.
- `_handle_copilot`'s inline fallback classifier prompt gained the same
  vocabulary and instructions, and its JSON schema line now reads
  `"kind":"read|action|prompt|show|remember|forget"` (two C15b tests that
  exact-matched the old 4-value enum were updated to the new 6-value one —
  same vocabulary check, not a behavior change).
- `producer_prompt.py`'s `PRODUCER_SYSTEM_PROMPT` gained matching
  `remember`/`forget` op documentation (WORD FOR WORD capture) plus
  instructions to answer "what do you remember" from the "STANDING
  PREFERENCES" block directly, not via an op.

**Deferred to `tasks/live-verification-queue.md` §C15c:** a real
conversational round-trip — say a standing instruction, confirm the
"Got it — I'll remember: ..." reply, start a FRESH conversation, confirm the
producer/co-pilot still honors it, then "forget that" and confirm it stops
hydrating (no paid key needed for this, but it does need a live LLM call
this sandbox can't make).

### New Files
| Path | Purpose |
|------|---------|
| `storyengine/backend/migrations/091_director_preferences.sql` | New `director_preferences` table + index + RLS-enabled-no-policies |
| `storyengine/backend/tests/functional/test_c15c_director_memory.py` | 38 tests: save/list/hydrate/forget helpers (verbatim, scoping, cap, fail-soft), the two op handlers, both chat system-prompt call sites (source-locked), both decision schemas' vocabulary, and the home producer's `remember`/`forget` profile_ops |

### Modified
| Path | Change |
|------|--------|
| `storyengine/schema.sql` | New `director_preferences` table definition, matching the live migration |
| `storyengine/backend/routes/chat.py` | New `_save_preference`/`_list_preferences`/`_preferences_brief`/`_deactivate_preference`/`_handle_remember_op`/`_handle_forget_op`; `_apply_profile_ops` gained `remember`/`forget`; both system-prompt builders (`chat_turn`, `_handle_copilot`) hydrate the preferences brief; `_handle_copilot` dispatches `kind=="remember"`/`"forget"`; fallback classifier prompt + JSON schema gained the vocabulary |
| `storyengine/backend/agent_brain.py` | `_decision_schema()` and `run_copilot_brain`'s system prompt gained `remember`/`forget` + `scope` field and classification guidance |
| `storyengine/backend/producer_prompt.py` | `PRODUCER_SYSTEM_PROMPT` gained `remember`/`forget` op documentation + profile_ops schema entries |
| `storyengine/backend/tests/functional/test_c15b_show_and_approve_scene.py` | Two exact-match assertions updated from the 4-value `kind` enum to the new 6-value one (vocabulary check only, not a behavior change) |

**Verify:** `cd storyengine/backend && ./venv/bin/python -m pytest
tests/functional/test_c15c_director_memory.py -q` — 38 passed. Confirmed
non-vacuous via `git stash` on the four modified `.py` files (the new test
file and migration are untracked, unaffected by the stash) — all 38 fail
against the pre-C15c source (missing functions/attributes and vocabulary).
Full backend suite: 907 passed (869 baseline + 38 new) / 16 pre-existing
failures (identical file list to C15a/C15b) / 1 pre-existing error — zero
new failures. `python -m py_compile` clean on all four touched `.py` files
plus both test files. Frontend untouched — no `tsc`/`build` run (chat text
is the UI this chunk; a future Settings page to list/manage preferences is
noted here as a follow-up, not built).

**Deploy-safety note:** additive only. New table, no existing table/column
touched. Both system-prompt builders only ever ADD the preferences block
(empty string when there's nothing to hydrate, or on any DB error) — old
behavior is exactly preserved for every tenant with zero preferences saved.
New backend + old frontend: no frontend change exists to be out of sync
with (chat text only). Old backend + new... n/a, nothing shipped frontend-
side. `kind=="remember"`/`"forget"` are new decision values the model only
emits when it recognizes the new vocabulary in its own (also-updated)
system prompt, so an old-prompt/new-code mismatch can't happen — the prompt
and the dispatch code ship together in this one chunk. Auto-deploy safe,
ff-merge safe.

## C15d — One Director Voice + Data Reach (added 2026-07-18)

The audit found two chat surfaces that should be ONE director drifting
apart: the home producer spoke in `producer_prompt.PRODUCER_SYSTEM_PROMPT`'s
full creative-producer personality, while the in-video copilot's tool loop
(`agent_brain.run_copilot_brain`) ran on a thin task-classifier prompt with
none of that tone. Separately, the "what should I make next" / "how's my
channel doing" data briefs were wired into the HOME chat's prompt only —
the copilot's tool loop had no way to reach competitor/performance/learnings
data from inside a video. Both fixed prompt-only + read-tools, zero new paid
paths, zero verb/schema changes.

**A. Shared director voice — `producer_prompt.DIRECTOR_VOICE`:** the tone
core (warm/sharp-producer address, "co-thinking partner" — push back, real
opinions, not a yes-machine — "DIAGNOSE BEFORE YOU ACT", and the "NEVER
mention internal machinery" pipeline/stage/render ban) extracted out of the
middle of `PRODUCER_SYSTEM_PROMPT` into its own module-level constant.
`PRODUCER_SYSTEM_PROMPT` now composes it (`intro + DIRECTOR_VOICE + planning
rubric`) instead of inlining it — same final string content as before, just
no longer duplicated when a second consumer needs the same tone.
`agent_brain.run_copilot_brain`'s system prompt now opens with
`DIRECTOR_VOICE` too (imported from `producer_prompt`), explicitly framing
itself as "the SAME director as the studio's home producer, not a different
voice" — but its state-grounded action discipline, op/verb instructions,
confidence gating, and JSON decision schema (`_decision_schema()`) are
untouched; the voice is prepended, the classification contract is not
touched.

**B. Data reach — `channel_briefs.py` (new module):**
`_next_to_make_brief`/`_own_performance_brief`/`_learnings_brief` (scored
unmodeled competitor winners, the creator's own synced YouTube analytics,
and proven learned patterns — each tenant-scoped, each already fail-soft
`-> ""` on a DB error) moved out of `routes/chat.py` into their own module
with no dependency on `chat.py` or `agent_brain.py`, so both can import the
identical implementation with zero circular-import risk.
`routes/chat.py`'s `_loop_brief` (used by both home-producer prompt call
sites) now imports these three from `channel_briefs` instead of defining
its own copies — same names, same call sites, no behavior change there.
`agent_brain.py` gained a new read-only `channel_data` tool
(`_tool_channel_data`, dispatched via `_run_tool`, documented in
`TOOL_DOC`) that calls the SAME three functions and concatenates their
output; if every section comes back empty (nothing synced/scraped yet) it
returns a plain "No channel performance or competitor data available yet."
rather than an empty string, so the model never has to guess. The system
prompt teaches the model to call it for channel-level questions ("what
should I make next?", "how are my videos doing?", "what works for us?")
before answering.

**Regression pins (verified, not just asserted):** the copilot's decision
schema's full verb/op vocabulary is unchanged; C15c's STANDING PREFERENCES
hydration is still present in both `chat.chat_turn` and
`chat._handle_copilot` (source-inspected); `routes.chat._next_to_make_brief`
etc. are literally the same function objects as `channel_briefs`'s (identity
check, not just "no error") proving one source, not a fork.

### New Files
| Path | Purpose |
|------|---------|
| `storyengine/backend/channel_briefs.py` | Shared, tenant-scoped, fail-soft data briefs (`_next_to_make_brief`, `_own_performance_brief`, `_learnings_brief`) — moved out of `routes/chat.py` so `agent_brain.py` can import the same implementation with no circular import |
| `storyengine/backend/tests/functional/test_c15d_voice_and_data_reach.py` | 15 tests: `DIRECTOR_VOICE` content + composition into both prompts (including a live-run proof against `agent_brain.run_copilot_brain` via a fake client, not just source inspection), decision-schema/verb-vocabulary regression pin, C15c preference-hydration regression pin, shared-brief identity check, `channel_data` tool doc/dispatch/fail-soft/ranking behavior, and tenant-scoping + fail-soft re-proof for all three moved brief functions |

### Modified
| Path | Change |
|------|--------|
| `storyengine/backend/producer_prompt.py` | New `DIRECTOR_VOICE` constant; `PRODUCER_SYSTEM_PROMPT` restructured to compose it (duplicate sentences removed from their old inline spots) — same effective prompt content |
| `storyengine/backend/agent_brain.py` | `run_copilot_brain`'s system prompt now opens with `DIRECTOR_VOICE`; new `_tool_channel_data`, `TOOL_DOC` entry, and `_run_tool` dispatch for `channel_data` |
| `storyengine/backend/routes/chat.py` | `_next_to_make_brief`/`_own_performance_brief`/`_learnings_brief` removed (now imported from `channel_briefs`); `_loop_brief` and both producer prompt call sites unchanged otherwise |

**Deploy-safety note:** prompt-only + read-only tool, no schema/table
changes, no verb/op changes, no paid path touched. Worst case if the tone
composition were somehow wrong is a copilot reply that sounds a bit off —
never a broken action, never an extra dollar spent. `channel_data` is a pure
SELECT-and-format read reachable only through the model's own tool-call
loop, same trust boundary as the five tools already there. Auto-deploy
safe, ff-merge safe — the orchestrator issues the final verdict.

**Verify:** `cd storyengine/backend && ./venv/bin/python -m pytest
tests/functional/test_c15d_voice_and_data_reach.py -q` — 15 passed.
Confirmed non-vacuous via `git stash` on the three modified `.py` files
(`channel_briefs.py` moved aside for the same run, since it's untracked and
survives a plain stash) — the test module fails to even collect against the
pre-C15d source (`ModuleNotFoundError: No module named 'channel_briefs'`).
Full backend suite: 922 passed (907 baseline + 15 new) / 16 pre-existing
failures (identical file list to C15a/b/c) / 1 pre-existing error — zero
new failures. `python -m py_compile` clean on all four touched/added `.py`
files. Frontend untouched — no `tsc`/`build` run (this chunk is chat-prompt
and backend-tool only, no frontend surface changed).

## C16a — DB-Backed Generation Claim: S7-1 CRITICAL + S7-6 MED Fix (added 2026-07-18)

The S7 queue/idempotency sweep (C16, §S7 in
`docs/reports/2026-07-17-storyengine-agent-audit-findings.md`) found the
chat-driven autobuild/copilot dispatch (`routes/chat.py`'s
`_handle_approve`/`_run_pending_action` -> `actions.py`'s
`make_autobuild_step`/`make_action_step`) scheduled paid background work via
a bare `background_tasks.add_task(...)` with **zero concurrency guard** —
zero grep hits for the existing guard anywhere in chat.py/actions.py. A
double-tap or a retried chat turn ran two concurrent `_run` loops on the
same video -> double paid generation (S7-1 CRITICAL). The only existing
guard, `routes/pipeline.py`'s `_running_tasks`/`_side_lanes` in-process
dicts, is restart-fragile and chat never consulted it at all (S7-6 MED,
folded into this chunk). This chunk closes both: a new DB table both chat
AND the manual routes now consult before dispatching paid work.

**A. `generation_claims` table (migration 092, live via Supabase MCP) +
`generation_claims.py` module:** `(tenant_id, video_id, stage)` UNIQUE, plus
`claimed_at`/`claimed_by` (debug label, not access control). `acquire()` is
TOCTOU-free via a per-VIDEO Postgres advisory transaction lock
(`pg_advisory_xact_lock(hashtext(tenant:video)::bigint)`) that serializes
the whole stale-sweep -> cross-stage-check -> `INSERT ... ON CONFLICT DO
NOTHING RETURNING stage` sequence inside one transaction — critically, the
lock is keyed on the VIDEO, not the stage, so it also closes the race a
plain per-row `ON CONFLICT` could never see: an acquire for `stage="main"`
racing an acquire for `stage="voice"` on the SAME video. A claim older than
2 hours is swept and retaken (a crashed run must never wedge a video for
good). `release()` is a plain `DELETE`. Fail-soft vs fail-closed is an
explicit split: `acquire()`/`is_blocked()` **DENY** (fail-closed) on any DB
error — a DB outage must never open the double-spend window; `release()` is
best-effort only (logs, never raises) — a failed release just leaves the
row for the next `acquire()`'s stale sweep to clear, degrading to "locked
for up to 2h", never a permanent wedge.

**Lane granularity (justified, not arbitrary):** reuses
`routes/pipeline.py`'s EXISTING lane vocabulary instead of inventing a
parallel one. `"main"` is the one exclusive lane every full-pipeline stage
(script/storyboards/images/render/...) already runs in; voice/characters/
thumbnail are independent side lanes that block "main" and are blocked by
it, but never by each other. Chat's whole-video autobuild chain claims
`stage="main"` — not a separate `"autobuild"` label — because it walks the
identical stages a manual main-lane click would; a single-stage copilot verb
claims its own lane name when one exists (`voice`/`characters`/`thumbnail`
via `generation_claims.stage_for_verb`), else `"main"` (script, storyboards,
images, animate, sound, render, research, upload, build). This is what makes
the unification real: a manual "Generate Voice" click and a chat "voice"
verb claim the IDENTICAL stage name, so they genuinely conflict — a
made-up `"autobuild"` label would not have composed with the existing dict
at all without a cross-reference table.

**B. Chat gated at all three paid dispatch sites** (`routes/chat.py`):
`_handle_approve`'s post-create autobuild kickoff, `_run_pending_action`'s
`"build"` verb, and `_run_pending_action`'s single-stage copilot verb each
now call `generation_claims.acquire(tenant_id, video_id, stage, claimed_by=...)`
BEFORE scheduling; on denial they return the same friendly line
(`chat._ALREADY_WORKING_REPLY` = "I'm already working on that — I'll let
you know when it's done.") and do **not** call `background_tasks.add_task`.
Runner verbs (approve_cast/lock/drive_sync/seo/...) are explicitly
untouched — S7-1 names only the autobuild/copilot dispatch, and runners
already reuse existing route handlers.

**C. Release wired into the actual task body** (`actions.py`):
`make_action_step` gained a `stage` kwarg (the caller's already-acquired
lane); `make_autobuild_step` always releases `"main"`. Both release the
claim in the SAME `finally` block that already runs on every exit path
(success, the first-error `break`, an early `return`, and any raised
exception) — traced, not assumed: the release call sits ahead of the
existing `asyncio.sleep(20/30)` + `_clear_task_status` cleanup in that one
`finally`, so it fires exactly once per run regardless of how the run
ended.

**D. Manual routes unified onto the same table** (`routes/pipeline.py` +
`videos.py`/`environments.py`/`characters.py`): `_is_task_active` is now
`async def`. Its existing in-process dict/lane check is the unchanged FAST
PATH (short-circuits immediately when already busy, no DB round-trip); when
the dict says clear, it now additionally calls
`generation_claims.is_blocked(tenant_id, video_id, lane)` and returns that —
so a claim held by chat (gated as of this same chunk) blocks a manual click
too, and survives a restart the in-process dict would have forgotten. All
~35 call sites across the 4 route files were updated to `await` it
(mechanical — each was already inside an `async def` handler).

### New Files
| Path | Purpose |
|------|---------|
| `storyengine/backend/generation_claims.py` | The claim module: `acquire`/`release`/`is_blocked`/`stage_for_verb` — TOCTOU-free atomic acquire via `pg_advisory_xact_lock`, fail-closed on DB error |
| `storyengine/backend/migrations/092_generation_claims.sql` | `generation_claims` table + unique index, applied live via Supabase MCP |
| `storyengine/backend/tests/functional/test_c16a_generation_claims.py` | 25 tests: module acquire/deny/release/stale-retake/lane-blocking/fail-closed-vs-fail-soft, `stage_for_verb` mapping, chat's 3 dispatch sites (denied -> no `add_task` + busy reply; granted -> correct stage + scheduled), runner-verb bypass, and `make_action_step`/`make_autobuild_step` release-on-success/release-on-exception |
| `storyengine/backend/tests/functional/queue_recovery/test_c16a_manual_routes_claim_check.py` | 6 tests: static lock (no unawaited `_is_task_active(` call sites remain), `_is_task_active` is async, DB consulted when the in-process dict is clear (both busy and free), in-process-busy short-circuits without touching the DB |

### Modified
| Path | Change |
|------|--------|
| `storyengine/backend/actions.py` | `make_action_step` gained `stage` kwarg + releases it in `_run`'s finally; `make_autobuild_step` releases `"main"` in its finally |
| `storyengine/backend/routes/chat.py` | `import generation_claims`; `_ALREADY_WORKING_REPLY` constant; all 3 paid dispatch sites (`_handle_approve`, `_run_pending_action`'s "build" and single-verb branches) now acquire-then-schedule |
| `storyengine/backend/routes/pipeline.py` | `import generation_claims`; `_is_task_active` is now `async def` and consults `generation_claims.is_blocked` when the in-process dict is clear; 27 call sites updated to `await` |
| `storyengine/backend/routes/videos.py`, `environments.py`, `characters.py` | 8 combined `_is_task_active` call sites updated to `await` |
| `storyengine/schema.sql` | `generation_claims` table added (mirrors migration 092) |

**Deploy-safety note:** what changes for existing flows — a genuine
double-tap/retry on the same video now gets a friendly refusal instead of
double-billing; a single legitimate click/turn is completely unaffected
(the claim is acquired and released within that one request/task's
lifetime, invisible to the user). The one new failure mode this
introduces: a claim that's acquired but never released (e.g. a hard process
kill between `acquire()` and the `finally` block, or a `release()` that
itself hits a DB error) would make a video look "busy" to every future
click/chat turn on that lane — but this self-heals: `acquire()`'s stale
sweep retakes any claim older than 2 hours automatically, so the worst case
is a **2-hour wait**, never a permanent wedge, matching the existing
`STALE_TASK_THRESHOLD_MIN`/reaper design already in `routes/pipeline.py`
for the exact same class of problem. Auto-deploy safe. **ff-merge
candidate** — ONLY the double-dispatch path is refused; every existing
single-action flow (manual button, chat turn, one-tap confirm) runs
byte-identically to before. The orchestrator issues the final verdict; it
should specifically verify the claim actually gates the 3 chat dispatch
sites and that release-on-completion/failure can't leak a stuck claim (both
proven in the test evidence above, not just asserted).

**Verify:** `cd storyengine/backend && ./venv/bin/python -m pytest
tests/functional/test_c16a_generation_claims.py
tests/functional/queue_recovery/test_c16a_manual_routes_claim_check.py -q`
— 31 passed. Confirmed non-vacuous via `git stash -u` on every touched/new
source file (test files excluded from the stash) — 6 failures + 1 collection
error against the pre-C16a source (`ModuleNotFoundError: No module named
'generation_claims'`). Full backend suite: 953 passed (922 baseline + 31
new) / 16 pre-existing failures (identical file list to C15a/b/c/d) / 1
pre-existing error — zero new failures. `python -m py_compile` clean on all
7 touched/added `.py` files. Migration 092 confirmed live via
`information_schema.columns` (6 columns: id/tenant_id/video_id/stage/
claimed_at/claimed_by), unique index `generation_claims_unique` on
`(tenant_id, video_id, stage)`, and `relrowsecurity=true` — all queried
directly against project `wrromlupsmyzrrcqlucn`. Frontend untouched — no
`tsc`/`build` run (backend-only chunk, no UI surface). Live double-tap
round-trip (two real overlapping chat turns on one video) deferred to
`tasks/live-verification-queue.md` §C16a — needs a live LLM+DB session, no
key in the sandbox.

## C16b — Coverage Skip-If-Done + Scene Allowlist: S7-2 CRITICAL Fix (added 2026-07-18)

**Problem (audit §S7-2):** `scripts/coverage_to_app.py::generate_coverage_for_video`
is the ONE paid stage with no skip-if-done guard — only the directive TEXT was
cached (`coverage_directive_hash`); every invocation called the paid
`run_coverage()` for every scene with script text, even a scene that was already
fully drawn under an unchanged script. A second click of "Generate all pictures",
or an autobuild resume that revisits the image phase, re-billed every scene from
scratch. Clips already skip via `video_url IS NULL`; voice/sound already skip-if-done.

**Fix:**
- New helper `_expected_coverage_frame_count(directive_text, max_moments, angles_max,
  max_frames)` — runs the SAME `parse_coverage()` + `enforce_shot_budget()` calls
  `run_coverage()` itself makes when handed a saved directive, so "how many frames
  SHOULD exist" is derived from the actual planner math, never guessed.
- **Completeness rule (exact):** a scene is COMPLETE under the current directive
  hash iff (a) `scripts.coverage_directive_hash` matches `_scene_text_hash(scene_text)`
  [pre-existing re-plan gate, unchanged] AND (b) the count of `assets` rows for that
  scene with `generation_method='coverage'` AND both `image_url` and
  `drive_image_url` NOT NULL is `>=` `_expected_coverage_frame_count()` computed from
  that SAME saved directive under today's `_coverage_shape()` params. Can't
  false-positive-skip a half-drawn scene: `store_scene()` only INSERTs a row per
  frame that actually drew (its `usable` filter requires a real local file), so a
  crash or content-policy skip mid-scene leaves the row count under the expected
  count and correctly reads as incomplete.
- **Scene allowlist:** new `only_scenes: list[int] | None = None` param — when set,
  `targets` is narrowed to exactly those scenes AND each one is treated as an
  explicit "redo this" (skip-if-done bypassed for it); every other scene is never
  even queried. This is finalize's (C17) future entry point.
- **Force semantics (caller-by-caller):**

  | Caller | Behavior |
  |--------|----------|
  | Scenes-page "Generate all pictures" (`routes/pipeline.py::run_coverage_images`, `scene=None`) | Skip-if-done (default) |
  | Per-scene "regenerate scene N" (same route, `scene=N`) | **Forced** — existing redo verb still fully redraws |
  | Chat/autobuild image phase (`actions.py`) | Skip-if-done (default) — the money-safety win: an autobuild resume/retry no longer re-bills already-drawn scenes |
  | Co-pilot dock (`pipeline_executor.py::run_coverage_images/run_coverage_stage`) | Skip-if-done when `scene=None` (all scenes); forced when a specific `scene` is passed |
  | Per-frame redraw (`routes/pipeline.py::run_redraw_image` → `redraw_asset_image`) | Untouched — separate function, never calls `generate_coverage_for_video` |

  No `force: bool` param was added — every legitimate "redo" flow is already
  reachable via the existing `scene=N` param or the new `only_scenes` allowlist,
  both of which bypass skip-if-done for the scenes they name.
- **Incidental fix (found while building this, in-scope because it blocks any
  end-to-end test of this function):** `render_style`/`video_model_id` were
  referenced at the `run_coverage()` call site inside `generate_coverage_for_video`,
  but the `v` row's SELECT here never fetched those two columns (only the
  neighboring `generate_storyboard_sheet_for_scene` did) — **every real
  "Generate pictures" invocation has raised `NameError` since C13b (commit
  `8f923f3`)**, the ONE paid image stage silently broken in production. No test
  caught it because every existing coverage test exercises sub-functions
  (`parse_coverage`/`generate_coverage_frames`/`plan_camera_moves`), never
  `generate_coverage_for_video` end-to-end. Fixed by adding `render_style,
  video_model` to the SELECT and assigning them, mirroring the neighboring
  function exactly.

### New Files
| Path | Purpose |
|------|---------|
| `storyengine/backend/tests/functional/test_c16b_coverage_skip_if_done.py` | 14 tests: complete+matching-hash scene skipped (`run_coverage` not called), incomplete scene regenerates, zero-drawn regenerates, hash-mismatch regenerates regardless of row count, no-saved-directive regenerates, explicit `scene=N` forces a complete scene, `only_scenes` allowlist forces the named scene(s) and leaves others unqueried (single + multi-scene), summary message counts skipped vs processed, `_expected_coverage_frame_count` pure unit tests (incl. angle-trim), and the render_style/video_model_id NameError fix |

### Modified
| Path | Change |
|------|--------|
| `storyengine/backend/scripts/coverage_to_app.py` | `generate_coverage_for_video` gains `only_scenes` param + skip-if-done guard + force-scene override; new `_expected_coverage_frame_count()` helper; `v`'s SELECT now fetches `render_style`/`video_model` (NameError fix); summary message reports skipped-scene count |

**Deploy-safety note:** the only behavior change for existing flows is that a
scene whose script hasn't changed AND whose pictures are already fully drawn is
no longer re-billed on a second "Generate all pictures" click or an autobuild
resume — this is a pure cost fix, never a loss of function: the per-scene
"regenerate scene N" button/verb and the per-frame redraw verb
(`redraw_asset_image`) are both untouched and still force a fresh draw on
request. The NameError fix is strictly a bug fix — the call path was crashing
100% of the time it reached a real draw, so there is no working prior behavior
it could regress. Auto-deploy safe. **ff-merge candidate** — additive param,
default behavior only skips work that would have produced byte-identical
prompts/pixels; the orchestrator should specifically verify the skip condition
can't fire on a scene missing rows and that `only_scenes`-excluded scenes are
provably never queried (both pinned in the test evidence below).

**Verify:** `cd storyengine/backend && ./venv/bin/python -m pytest
tests/functional/test_c16b_coverage_skip_if_done.py -q` — 14 passed. Confirmed
non-vacuous via `git stash push -- storyengine/backend/scripts/coverage_to_app.py`
— collection error against the pre-C16b source (`ImportError: cannot import
name '_expected_coverage_frame_count'`). Full backend suite: 967 passed (953
baseline + 14 new) / 16 pre-existing failures (identical file list to
C15a-d/C16a) / 1 pre-existing error — zero new failures. `skills/video-pipeline`
coverage suite: `python -m pytest tests/test_coverage.py -q` — 8 passed / 1
pre-existing failure (`test_drops_moment_with_no_angles`, unrelated to this
chunk) — matches the pinned baseline exactly. `python -m py_compile` clean.
Frontend untouched — no UI surface, backend-only chunk. Live re-invoke proof
(run "Generate all pictures" twice on a real video, confirm the second run
spends $0 and logs skip messages) deferred to `tasks/live-verification-queue.md`
§C16b — needs a live DB + paid API session, not available in the sandbox.

## C16c — `generation_ledger` Uniqueness Backstop: S7-5 HIGH Fix (added 2026-07-18)

**Problem (audit §S7-5):** `generation_ledger` (migration 087) had NO
uniqueness constraint, and `record_ledger_entry()` was a plain INSERT — if a
double-spend race fired upstream (two concurrent workers each finish polling
the SAME Kie task and both call `record_ledger_entry` for it), the ledger
recorded the same paid unit twice, inflating `videos.total_cost`. Only the
clip stage (C07) ever threaded a real `kie_task_id`; images/voice/thumbnail/
sound (C08) all passed `None`.

**Fix:**
- **Migration 093** (idempotent, `CREATE UNIQUE INDEX IF NOT EXISTS
  generation_ledger_dedup_idx ON generation_ledger (video_id, stage,
  kie_task_id) WHERE kie_task_id IS NOT NULL`) — a PARTIAL unique index.
  Rows with `kie_task_id IS NULL` are never deduped (Postgres NULL-distinctness),
  which is the honest, intentional limit for stages that don't carry a real
  provider id. Applied LIVE via Supabase MCP against `wrromlupsmyzrrcqlucn`.
  Pre-apply duplicate scan (`GROUP BY video_id, stage, kie_task_id HAVING
  COUNT(*) > 1 WHERE kie_task_id IS NOT NULL`) found **zero rows** — the table
  is empty in prod today (0 total rows, 0 with a `kie_task_id`; no paid
  generation has landed a ledger row yet), so no backfill/cleanup was needed.
  Confirmed live via `pg_indexes`.
- `record_ledger_entry()` (`storyengine/backend/generation_ledger.py`) now
  inserts with `ON CONFLICT (video_id, stage, kie_task_id) WHERE kie_task_id
  IS NOT NULL DO NOTHING`, and inspects asyncpg's command-status string
  (`"INSERT 0 0"` = conflict fired) to log a loud `DUPLICATE SKIPPED` line —
  the one signal that the backstop actually caught a double-spend race. The
  `videos.total_cost` rollup UPDATE still always runs (a straight
  `SUM(actual_cost)` recompute), so a skipped duplicate can't be reflected as
  a phantom charge either way. Fail-soft is fully preserved — same
  try/except, still never raises.
- **Provider-id threading (giving the constraint teeth beyond clips):**
  Added `task_id_out: Optional[list]` to `ImageClient.generate_and_wait`,
  `generate_scene_image_zimage`, `generate_with_reference`,
  `generate_thumbnail_gpt2`, and `generate_scene_image_gpt`
  (`skills/video-pipeline/shared/clients/image_client.py`) — same
  fresh-box-per-call, append-don't-assign pattern C07 already used for clips
  (`generate_video`'s `task_id_out`). Threaded through
  `image_model_router.generate_scene_image_for_model` (every branch: z-image,
  nano-banana-2 with/without refs, the GPT default/fallback ladder). Wired
  into the THREE call sites that write exactly ONE ledger row per ONE
  underlying Kie task:
  - `coverage_to_app.py::redraw_asset_image` (stage="image")
  - `pipeline_executor.py::_run_channel_formula_thumbnail` (stage="thumbnail")
  - `pipeline_executor.py::run_thumbnail`'s "modeled on reference" branch (stage="thumbnail")

  Each passes a fresh `task_id_box: list = []` through the attempt(s) and
  reads `task_id_box[0] if task_id_box else None` into `record_ledger_entry`
  — same convention as the clip path.
- **Left `kie_task_id=None` (documented, not a gap):** `run_image_variants`
  and `run_images`/`store_scene` all aggregate MANY images (many distinct Kie
  tasks) into ONE ledger row (`units=N`) — a single task id can't honestly
  represent a batch, and re-running the batch mints brand-new task ids
  anyway, so threading one wouldn't add real dedup protection. The
  "from-scratch" legacy thumbnail path (`run_thumbnail_bot()` →
  `skills/video-pipeline/thumbnail/run.py`) is a separate older subsystem
  that doesn't surface a task id back through `result` today. Voice
  (ElevenLabs) and sound never expose a reusable per-unit task id at all.
  **Tradeoff spelled out in migration 093's header:** a made-up UNIQUE value
  (e.g. `uuid4()`) would never collide — zero protection, pure decoration. A
  made-up CONSTANT value (e.g. the literal `"voice"`) would be worse than
  nothing: it would wrongly dedup two LEGITIMATE separate spends on the same
  video (second real voiceover of the same video would silently refuse to
  record). NULL is the only honest value when the provider call doesn't hand
  back a real id.

### New Files
| Path | Purpose |
|------|---------|
| `storyengine/backend/migrations/093_generation_ledger_dedup_index.sql` | The partial unique index + full call-site audit of which stages carry real task ids vs. remain None and why |

### Modified
| Path | Change |
|------|--------|
| `storyengine/backend/generation_ledger.py` | `ON CONFLICT ... DO NOTHING` + loud duplicate-skip logging; fail-soft preserved |
| `storyengine/backend/tests/functional/test_generation_ledger.py` | +4 tests: duplicate skipped/first row intact/logged, distinct task ids both insert, NULL never deduped, fail-soft preserved on the new conflict path; fake DB updated to honor the partial-index semantics only when the query text carries `ON CONFLICT` (so `git stash` on the source alone reproduces the pre-fix duplicate-row bug, not just the missing log line) |
| `skills/video-pipeline/shared/clients/image_client.py` | `task_id_out` param on 5 image-generation methods (append, don't assign) |
| `skills/video-pipeline/shared/clients/image_model_router.py` | `task_id_out` threaded through every branch of `generate_scene_image_for_model`/`_gpt_default` |
| `skills/video-pipeline/tests/test_image_model_router.py` | FakeImageClient accepts `task_id_out`; +7 tests pinning the box is threaded to the right branch, accumulates across fallback attempts (box[0] = first attempt), and is None-safe for callers that don't pass it |
| `storyengine/backend/scripts/coverage_to_app.py` | `redraw_asset_image` threads a fresh `task_id_box` into `record_ledger_entry` |
| `storyengine/backend/pipeline_executor.py` | The two single-image thumbnail paths thread a fresh `task_id_box`; `run_image_variants`/`run_images`/the legacy thumbnail path get documenting comments for why they stay `None` |
| `storyengine/schema.sql` | `generation_ledger_dedup_idx` added alongside the table definition |

**Deploy-safety note:** additive index (`IF NOT EXISTS`, confirmed empty table
pre-apply) + `ON CONFLICT DO NOTHING` insert semantics. Can this change any
LEGITIMATE flow? No: a real ON CONFLICT can only fire when `(video_id, stage,
kie_task_id)` is an EXACT repeat of an existing row's non-NULL key — that only
happens on the double-spend race this chunk exists to close (the same
provider task recorded twice), never on two genuinely different generations
(different task ids, or `kie_task_id IS NULL` which is never deduped at all).
The `total_cost` rollup is unconditional and SUM-based either way. **ff-merge
candidate** — purely additive (new index, new optional param with `None`
default throughout, new `ON CONFLICT` clause that only ever changes behavior
on an exact duplicate key). Does not touch C16a's claim logic or C16b's
skip-if-done logic.

**Verify:** `cd storyengine/backend && ./venv/bin/python -m pytest
tests/functional/test_generation_ledger.py -q` — 20 passed (16 baseline + 4
new). Non-vacuous via `git stash push -- storyengine/backend/generation_ledger.py`
— 1 failure (the log-line assertion) on the first fake-DB pass; after
tightening the fake to only enforce dedup when the query text itself carries
`ON CONFLICT`, the same stash reproduces the ORIGINAL bug exactly: the
duplicate row lands (`len(LEDGER_ROWS) == 2`), proving the test is a real
regression guard, not vacuous. `cd skills/video-pipeline && <backend venv>
python -m pytest tests/test_image_model_router.py -q` — 19 passed (12
baseline + 7 new); non-vacuous via `git stash` on `image_client.py` +
`image_model_router.py` — 6 of the 7 new tests fail with `TypeError:
unexpected keyword argument 'task_id_out'`. Full backend suite: 971 passed
(967 baseline + 4 new) / 16 pre-existing failures (identical file list to
C15a-d/C16a/C16b) / 1 pre-existing error — zero new failures. `python -m
py_compile` clean on every touched file. Frontend untouched — no UI surface,
backend-only chunk. Live duplicate-scan + `pg_indexes` results are pasted
above (empty table, index confirmed live). Live race-proof (fire two
concurrent requests at the same provider task and confirm exactly one ledger
row lands) deferred to `tasks/live-verification-queue.md` §C16c — needs a
live DB + concurrent paid-API session, not available in the sandbox.

## C16d — Queue Hardening: S7-3/S7-4/S7-7/S7-8/S7-9 Fixes (added 2026-07-18)

**Problem (audit §S7, hardening tier — C16a/b/c already shipped the three
critical/gating fixes S7-1/S7-2/S7-5):**
- **S7-3 HIGH:** `PipelineExecutor.run_thumbnail` (all 3 completion branches —
  modeled/channel-formula/legacy from-scratch) unconditionally regenerated +
  ledger-billed on EVERY call, including a routine status-machine resume.
- **S7-4 HIGH:** `routes/pipeline.py::_enqueue_or_fallback` hardcoded
  `attempt=1` — since arq's job_id (`f"{stage}:{video_id}:{attempt}"`) is kept
  for 24h (`keep_result=86400`), a hardcoded 1 collided with arq's OWN dedup on
  every legitimate second run; when `enqueue_stage` returned `None` for that
  reason, the function silently `return`ed with no persisted row and no error
  — the caller got a 200 "running" response for a job that was never queued.
- **S7-7 MED:** when the arq/Redis pool failed to connect at startup, every
  stage silently fell back to in-process BackgroundTasks — a supported
  degraded mode, but invisible outside one startup log line.
- **S7-8 LOW:** `task_store.db_persist_task`'s "pending" branch was a plain
  check-then-insert with no DB-level constraint behind it — a TOCTOU race
  between two concurrent calls for the SAME arq job_id could land two rows.
- **S7-9 LOW:** resumability was undocumented per stage.

**Fixes (all 5 shipped — none split out):**

1. **S7-3 — thumbnail skip-if-done.** `run_thumbnail(video_id, force=False)`
   now checks `videos.thumbnail_url` right after fetching the video, BEFORE
   any of the three completion branches run — one guard covers all three
   (the channel-formula branch is only ever reached FROM run_thumbnail, so
   gating at the top is sufficient, unlike C16b's per-scene coverage guard).
   `force=True` is the only bypass, threaded explicitly by every caller that
   represents a real "redo it": `actions.py::make_action_step` special-cases
   `name == "run_thumbnail"` to always pass `force=True` (the ACTIONS verb's
   label is literally "Redo the thumbnail" — never a first-time call);
   `routes/chat.py::_make_prompt_regen`'s "Apply & redo" prompt-studio path;
   and `routes/pipeline.py`'s `POST /thumbnail/{video_id}?force=true` (new
   query param, mirroring the pre-existing `POST /clip/{video_id}?force=true`
   convention). Callers representing natural first-time progression —
   `actions.py`'s autobuild finish chain (already double-guarded by its own
   pre-existing `not thumbnail_url` check), the arq/queue stage runner, and
   `claude_orchestrator.py`'s skill dispatch — pass nothing and get the
   default skip.

   The ONE frontend surface that hits this route serves BOTH intents from
   the same button (`ThumbnailTab.tsx`'s label flips "Generate Thumbnail" /
   "Regenerate" off the SAME `handleRegenerate` handler) — traced via
   `GuidedNextStep.tsx`/`next-action.ts` (natural "Create your thumbnail" at
   `status===ready_for_thumbnail`, no force) vs. `ThumbnailTab.tsx` (this
   chunk: now passes `{force: "true"}` only when `video.thumbnail_url` is
   already set, i.e. only when the label actually reads "Regenerate").

2. **S7-4 — arq attempt + honest dedup signal.** `_enqueue_or_fallback` now
   derives `attempt` from `COALESCE(MAX(attempt), 0) + 1` over prior
   `background_tasks` rows for that `(video_id, tenant_id, task_type)` —
   the same source `main.py`'s restart-recovery already reads
   (`row["attempt"] + 1`). When `enqueue_stage` STILL returns `None` after
   that (a genuine concurrent duplicate — the residual race the attempt fix
   can't close), the function now raises `HTTPException(409, "Task already
   running")` — the SAME shape `_is_task_active` gates already raise
   elsewhere, which the frontend already retries on (`ThumbnailTab.tsx`/
   `stage-advancer.tsx`'s existing 409→clearStaleTask→retry handling). A
   `except HTTPException: raise` guards this from being swallowed by the
   surrounding `except Exception` (which still handles the pre-existing
   degraded-queue fallback for a genuine connection-style error — S7-7's
   behavior is untouched). `**stage_kwargs` threading (`job_queue.enqueue_stage`
   → arq's `enqueue_job(**kwargs)` → `worker.py`'s `arq_run_thumbnail(...,
   force=False)` → `_run_stage(..., **method_kwargs)` → `method(video_id,
   **method_kwargs)`) carries S7-3's `force` through the arq path too, so
   Regenerate behaves identically whether or not Redis is up.

3. **S7-7 — degraded-queue visibility.** Both `GET /api/health` and
   `GET /api/health/detailed` now include `"queue": "arq" |
   "degraded-inprocess"`, read straight from `app.state.arq` (the same
   attribute the lifespan sets on connect/failure, and `_enqueue_or_fallback`
   reads via `_get_arq_pool`). Data only — no UI banner this chunk (frontend
   follow-up).

4. **S7-8 — background_tasks job_id uniqueness.** Live duplicate-scan FIRST
   (required by chunk spec): `SELECT job_id, count(*) ... GROUP BY job_id
   HAVING count(*) > 1` against `wrromlupsmyzrrcqlucn` → **zero rows** (468
   total rows in `background_tasks`, 0 of them carry a job_id at all — arq has
   never actually been in the loop in prod; every stage so far ran via the
   in-process fallback). Safe to index with no cleanup. **Migration 094**
   (idempotent, `CREATE UNIQUE INDEX IF NOT EXISTS background_tasks_job_id_uidx
   ON background_tasks (job_id) WHERE job_id IS NOT NULL`) applied LIVE via
   Supabase MCP, confirmed via `pg_indexes` (alongside a pre-existing plain
   `background_tasks_job_id_idx` that was live in prod but never captured in
   schema.sql — a pre-existing drift, left alone, out of this chunk's scope).
   `task_store.db_persist_task`'s shared INSERT (used by both the "pending"
   and "running" branches) now carries `ON CONFLICT (job_id) WHERE job_id IS
   NOT NULL DO NOTHING` — the race's loser becomes a silent no-op instead of
   a duplicate row, with the NULL-job_id (in-process fallback) path
   completely unaffected (NULL never conflicts). Fail-soft (the function has
   never raised out to a caller) is fully preserved.

5. **S7-9 — resumability table.** Added to `docs/failure-modes.md`: voice,
   sound prompts, sound effects, clips, images/coverage (since C16b), and
   thumbnail (since this chunk) skip-if-done; research, script, and render
   fully restart every call (all three relatively low-stakes — cheap LLM
   calls or local compute, no external per-call billing at risk beyond one
   redundant call); **upload has NO re-publish guard at all** — a re-invoke
   can mint a SECOND YouTube draft, not just re-spend. Flagged as a follow-up,
   not fixed here (out of this chunk's 5-item scope).

### New Files
| Path | Purpose |
|------|---------|
| `storyengine/backend/migrations/094_background_tasks_job_id_unique.sql` | Partial UNIQUE index behind S7-8's ON CONFLICT fix; live duplicate-scan result in the header comment |
| `storyengine/backend/tests/functional/test_c16d_thumbnail_skip_if_done.py` | 5 tests: skip-if-done default+existing thumbnail (no ledger call, activity log line), no-skip when NULL/blank thumbnail_url, force=True bypasses, video-not-found ordering |
| `storyengine/backend/tests/functional/test_c16d_enqueue_or_fallback.py` | 5 tests: attempt derived from MAX(attempt)+1, attempt=1 with no history, dedup-hit raises honest 409 (not silent, doesn't double-run via fallback), generic Exception still falls back (S7-7 regression pin), no-arq-pool skips the attempt query entirely |
| `storyengine/backend/tests/functional/test_c16d_health_queue_status.py` | 3 tests: `/api/health` and `/api/health/detailed` both report `degraded-inprocess`/`arq` off `app.state.arq` directly (no TestClient/lifespan — main.py imports cleanly standalone) |
| `storyengine/backend/tests/functional/test_c16d_task_store_job_id_conflict.py` | 4 tests: a true `asyncio.gather` TOCTOU race (fake DB snapshots the SELECT result BEFORE yielding, so both callers see "not found" before either INSERTs) lands exactly one row post-fix; sequential calls still short-circuit via the pre-existing SELECT check; NULL job_id rows are never deduped; fail-soft preserved on a hard DB error |

### Modified
| Path | Change |
|------|--------|
| `storyengine/backend/pipeline_executor.py` | `run_thumbnail` gains `force: bool = False` + the skip-if-done guard (one check covers all 3 completion branches) |
| `storyengine/backend/actions.py` | `make_action_step` special-cases `run_thumbnail` to always pass `force=True` (mirrors the pre-existing `run_script`/`ensure_scriptable` special-case) |
| `storyengine/backend/routes/chat.py` | `_make_prompt_regen`'s thumbnail branch passes `force=True` |
| `storyengine/backend/routes/pipeline.py` | `POST /thumbnail/{video_id}` gains `force: bool = False` query param, threaded to both the fallback closure and `_enqueue_or_fallback`; `_enqueue_or_fallback` derives `attempt` from `MAX(attempt)+1`, raises 409 on a genuine dedup-hit instead of a silent no-op, and accepts `**stage_kwargs` |
| `storyengine/backend/job_queue.py` | `enqueue_stage` accepts `**stage_kwargs`, forwarded to `arq_pool.enqueue_job` |
| `storyengine/backend/worker.py` | `_run_stage` accepts `**method_kwargs`; `arq_run_thumbnail` gains `force: bool = False`, threaded through |
| `storyengine/backend/main.py` | `/api/health` and `/api/health/detailed` add `"queue": "arq" \| "degraded-inprocess"` |
| `storyengine/backend/task_store.py` | `db_persist_task`'s shared INSERT gains `ON CONFLICT (job_id) WHERE job_id IS NOT NULL DO NOTHING` |
| `storyengine/schema.sql` | `background_tasks_job_id_uidx` added alongside the table definition |
| `storyengine/frontend/src/components/production/ThumbnailTab.tsx` | `handleRegenerate` passes `{force: "true"}` only when `video.thumbnail_url` is already set (the "Regenerate" case, not "Generate Thumbnail") |
| `docs/failure-modes.md` | New "Per-Stage Resumability" table (S7-9) |

**Deploy-safety assessment (per fix):**
- **S7-3 (thumbnail skip-if-done):** ff-merge candidate. The only behavior
  change for existing flows is that a video with an already-set
  `thumbnail_url` is no longer re-billed by a non-explicit caller — every
  real "redo" path (chat verb, prompt-studio apply, Scenes-page Regenerate)
  is traced and threads `force=True` explicitly, proven by the test suite's
  guard/no-guard/force-bypass assertions. Pure cost fix, no loss of function.
- **S7-4 (attempt + honest 409):** ff-merge candidate for the attempt-fix
  half (purely additive — a query that used to always return "0 prior" now
  returns the real count; behavior is IDENTICAL for any video/stage with no
  prior arq history). The 409-instead-of-silent-200 half is a real behavior
  change for the (currently unreached in prod — 0 of 468 rows carry a
  job_id) arq-active path: a caller that previously got a fake "success" now
  gets an honest error. Recommend the orchestrator specifically confirm the
  frontend's existing 409-retry handling (already wired for `_is_task_active`
  409s) covers this new source too before flagging fully safe — the test
  suite proves the backend contract but doesn't exercise the live frontend.
- **S7-7 (health queue field):** ff-merge candidate. Purely additive JSON
  field, no existing consumer of either endpoint is broken by an extra key.
- **S7-8 (background_tasks job_id unique index):** ff-merge candidate.
  Additive index (`IF NOT EXISTS`, confirmed empty-of-job_id table pre-apply)
  + `ON CONFLICT DO NOTHING` insert semantics — can only ever change behavior
  on an EXACT duplicate job_id, which was already a bug being raced against,
  never a legitimate two-different-jobs case (NULL job_id, the common path
  today, is never deduped at all).
- **S7-9 (docs):** no runtime change, nothing to assess.

**Verify:** `cd storyengine/backend && ./venv/bin/python -m pytest
tests/functional/test_c16d_thumbnail_skip_if_done.py
tests/functional/test_c16d_enqueue_or_fallback.py
tests/functional/test_c16d_health_queue_status.py
tests/functional/test_c16d_task_store_job_id_conflict.py -q` — 17 passed.
Non-vacuous per file via `git stash push -- <file>`: `pipeline_executor.py`
stashed → 2/5 fail (guard + force kwarg both gone); `routes/pipeline.py`
stashed → 2/5 fail (attempt derivation + honest-409); `main.py` stashed →
3/3 fail (queue field missing); `task_store.py` stashed → 1/4 fails, and
only after restructuring the fake DB so the race actually reproduces the
TOCTOU window (snapshot-then-yield, not yield-then-snapshot — the first
attempt was accidentally vacuous because a non-suspending fake let one
caller's whole SELECT+INSERT complete before the other's SELECT ever ran,
which the pre-existing app-level check alone already covered regardless of
the DB-level fix). Full backend suite: `./venv/bin/python -m pytest tests/ -q`
— 988 passed (971 baseline + 17 new) / 16 pre-existing failures (identical
file list to C15a-d/C16a-c) / 1 pre-existing error — zero new failures.
`python -m py_compile` clean on every touched Python file. Frontend: DID
touch `ThumbnailTab.tsx` (needed for the force-intent signal to actually
reach the backend — see fix 1 above) — `npx tsc --noEmit` clean; `npm run
build` compiles + type-checks clean, then fails at the static-prerender step
on a pre-existing sandbox gap (`NEXT_PUBLIC_API_URL is required in
production builds`), unrelated to this change. Live: duplicate-scan (zero
rows) + `pg_indexes` confirmation pasted above. Live re-invoke proof (hit
`POST /thumbnail/{id}` twice on a real video, confirm the second call spends
$0 with `force` omitted and DOES redraw with `force=true`; force a genuine
concurrent double-enqueue and confirm the 409) deferred to
`tasks/live-verification-queue.md` §C16d — needs a live DB + paid API
session, not available in the sandbox.

## C17 — `draft_pass` + `finalize` Verbs: the Trust-Ladder Centerpiece (added 2026-07-19)

**Problem (checklist §1.3 "Draft cheap, finish expensive" + §S7 "C17 design
requirements"):** the trust ladder Ryan wants — draft the whole video cheap,
approve the scenes that matter, finalize only those at routed/premium
quality — had two verbs missing from the registry, and the S7 sweep (C16)
found the queue had zero idempotency for chat-driven paid dispatch until
C16a-c shipped the prerequisites (DB-backed claims, coverage skip-if-done +
scene allowlist, ledger uniqueness backstop). This chunk builds C17 on top
of all three.

**Design decision — what "draft the whole video" covers:** pictures are
already cheap and stage-shared (the `images` verb, unchanged); "draft"
describes CLIP generation specifically, the expensive step this whole
trust ladder is about. `draft_pass` therefore needs `pictures` (same gate as
`animate`) and only touches clips.

**`run_clip_generation` gains two additive params (`pipeline_executor.py`):**
- `force_model_id`: when set, EVERY row this call processes animates through
  this model_id, completely bypassing `resolve_clip_model` (and therefore
  `assets.routed_model`/`model_override`) for the call. `draft_pass` passes
  the cheapest wired `tier="draft"` model here — the routing recommendation
  those columns hold is NEVER read or written during a draft pass, so it
  survives byte-identical for `finalize` to resolve against later.
- `only_scenes: list[int]`: mirrors C16b's `generate_coverage_for_video`
  allowlist exactly — `WHERE ... AND scene = ANY($3::int[])` scopes the SQL
  fetch itself, so a scene NOT in the list is never even returned from the
  DB, let alone touched. `finalize` passes the approved-scene list here
  combined with `force=True` (an approved scene's existing DRAFT clip must
  be OVERWRITTEN with the real tier, not skipped as "already has a clip").

Both params default to `None`/unused — every existing caller (`animate`,
the per-scene redo button) is byte-identical.

**Lane choice:** both verbs claim `generation_claims` stage `"main"`.
`generation_claims.stage_for_verb()` needed ZERO code changes — neither verb
is in `SIDE_LANES` (voice/characters/environments/thumbnail), so it already
falls through to `"main"`, which is exactly right: a whole-video clip pass
must conflict with any other main-lane work in flight (script rewrite,
images, render), the same as a manual "Animate everything" click would.

**Pass identity — the S7 "job key = (video_id, stage, pass, scene_set_hash)"
requirement:** new module `backend/generation_passes.py` + migration 095
(new table `generation_passes`, UNIQUE `(tenant_id, video_id, pass,
scene_set_hash)`) — a DIFFERENT problem than `generation_claims` solves.
The claim guards CONCURRENT double-dispatch and is released the instant a
run ends; it says nothing about a SEQUENTIAL repeat (the same "finalize"
arriving again after the first run already completed and released its
claim). `scene_set_hash()` hashes SORTED `(scene, target_model_id)` pairs —
not just scene numbers — so approving MORE scenes, or changing a routing
override, between two finalize calls mints a NEW hash (a legitimate new
pass, never wrongly deduped), while a bare repeat of the IDENTICAL pass
hashes identically and is refused by `already_done()` BEFORE any claim is
even attempted. A row is written ONLY on successful completion
(`mark_done`, fail-soft, never raises) — a failed run leaves no row, so it
stays retryable with the identical scene set. Deliberately NOT reused:
`background_tasks.job_id`'s C16d unique index — that channel already
carries UI-poll semantics (`db_persist_task`'s running/pending/completed
state machine) that repurposing it for pass-identity would have risked
disturbing; a small purpose-built table keeps the two concerns separate.

**Registry + runners (`actions.py`):** `draft_pass`/`finalize` are
runner-style verbs (`ACTIONS[...]["runner"]`, like `seo`/`approve_scene`) —
`_runner_draft_pass`/`_runner_finalize` each explicitly acquire the claim
and check `generation_passes.already_done` themselves (mirroring the
"build" verb's explicit pattern), since `_run_pending_action`'s generic
runner-dispatch branch does NOT claim on a verb's behalf. `_approved_scenes`
reads `assets.status='approved'` (C15b's `approve_scene` machinery) via
`DISTINCT scene`. `_draft_tier_model_id()` resolves the cheapest WIRED
`tier="draft"` model from `MODEL_REGISTRY` — data-driven, never hardcodes
"grok-imagine" (today's only draft-tier entry, but the function reads the
registry's `tier`/`wired`/`cost_per_clip` fields, not a literal string).

**Money — `estimate_cost`/`cost_breakdown` extended for both verbs**, reusing
the SAME `_routed_clip_rows`/`_resolved_model_id` one-resolver pattern C15
established (no parallel math): `draft_pass` prices every not-yet-clipped
row at the draft-tier price regardless of routed_model/override (matching
what the run will actually do); `finalize` prices ONLY `_approved_scenes()`
rows at their real resolved (override > routed > default) tier. Both
itemizations sum to exactly `estimate_cost`'s own total (the same
sums-to-total invariant C15's tests pin for `animate`/`build`) — this is
what C18's "draft $X now, finalize N scenes $Y later vs $Z all-premium"
savings line will read from; C18 combines both calls' numbers into copy,
no new backend math needed.

**Classifier vocabulary:** both `routes/chat.py`'s legacy one-shot
classifier and `agent_brain.py`'s tool-loop brain gained `draft_pass`/
`finalize` in the verb enum + VERB MEANINGS prose, explicitly worded to
distinguish `draft_pass`/"draft the whole video"/"rough cut" (cheap) from
`build`/"animate everything" (real routed/premium quality) — the two tiers
must never be conflated by the classifier.

**`[U]` deliberately NONE this chunk** (checklist: C18 owns GuidedNextStep
labels, Approve ticks, and the savings-line copy) — confirmed
`routes/chat.py::_confirm_card` renders sensible text for both new verbs
completely unmodified (it reads `ACTIONS[verb]["label"]` generically).

### New Files
| Path | Purpose |
|------|---------|
| `storyengine/backend/generation_passes.py` | `scene_set_hash()`, `already_done()`, `mark_done()` — the durable (video, pass, scene-set+target-models) dedup identity, distinct from `generation_claims`'s concurrency guard |
| `storyengine/backend/migrations/095_generation_passes.sql` | New `generation_passes` table + UNIQUE `(tenant_id, video_id, pass, scene_set_hash)` index, applied LIVE via Supabase MCP against `wrromlupsmyzrrcqlucn`, confirmed via `information_schema.columns` |
| `storyengine/backend/tests/functional/test_c17_draft_pass_and_finalize.py` | 13 tests: draft-tier resolution is data-driven; `force_model_id` overrides every row regardless of routing and never writes routed_model/model_override; `only_scenes` scopes the SQL fetch itself (unapproved scene never touched, row-level asserted); scene_set_hash same-set/larger-set/routing-change behavior; estimate_cost/cost_breakdown sums-to-total for both verbs (incl. zero-approved-scenes = zero cost, proven non-vacuous against the OLD fallback path); claim-denied busy reply with no dispatch (both verbs); already-done pass refused without reclaiming; nothing-approved refuses before any claim attempt; full success path (claim → dispatch → run_clip_generation kwargs → mark_done → release); confirm card renders for both verbs |

### Modified
| Path | Change |
|------|--------|
| `storyengine/backend/pipeline_executor.py` | `run_clip_generation` gains `only_scenes: list = None` (WHERE-scoped scene allowlist) and `force_model_id: str = None` (per-row resolution override, bypassing `resolve_clip_model` entirely when set) |
| `storyengine/backend/actions.py` | New ACTIONS entries `draft_pass`/`finalize`; `_draft_tier_model_id()`, `_approved_scenes()`; `_routed_clip_rows`/`_routed_clip_costs` gain `only_scenes`; `cost_breakdown`/`estimate_cost` extended for both verbs; `_runner_draft_pass`/`_runner_finalize` + `RUNNERS` entries; new `_ALREADY_WORKING_REPLY` constant |
| `storyengine/backend/routes/chat.py` | Legacy classifier's verb enum + VERB MEANINGS prose gain `draft_pass`/`finalize` |
| `storyengine/backend/agent_brain.py` | Tool-loop brain's `_decision_schema()` verb enum + VERB MEANINGS prose gain `draft_pass`/`finalize` |
| `storyengine/schema.sql` | `generation_passes` table added (the schema-drift test caught the initial omission — migration-only isn't sufficient, schema.sql is the fresh-install source of truth) |

**Deploy-safety assessment:** ff-merge candidate. Both verbs are brand-new
additive registry entries — no existing verb's behavior, gate, price, or
copy changes. `run_clip_generation`'s two new params are opt-in and default
to inert values for every existing caller (`animate`'s per-scene/per-card/
whole-video calls, the per-scene redo button) — byte-identical. New table
(`generation_passes`, migration 095, applied live) has zero foreign-key or
trigger interaction with any existing table besides the two `REFERENCES`
(tenants/videos, `ON DELETE CASCADE`, same pattern as `generation_claims`).
Classifier prompt changes are purely additive vocabulary. No existing
route, column, or price constant is touched.

**Verify:** `cd storyengine/backend && ./venv/bin/python -m pytest
tests/functional/test_c17_draft_pass_and_finalize.py -q` — 13 passed.
Non-vacuous via `git stash push -- actions.py agent_brain.py
pipeline_executor.py routes/chat.py ../schema.sql` (the new
`generation_passes.py`/migration/test file are untracked and survive the
stash): 12/13 fail against pre-C17 source (`KeyError`/`AttributeError` on
the missing verbs/functions); the 13th (`scene_set_hash`'s pure hash-
function test) legitimately still passes, since it exercises only the new
standalone `generation_passes.py` module the stash doesn't touch — expected,
not a gap. `python -m py_compile` clean on all 6 touched/added `.py` files.
Full backend suite: `./venv/bin/python -m pytest tests/ -q` — 1001 passed
(988 baseline + 13 new) / 16 pre-existing failures (identical file list to
C15a-d/C16a-d) / 1 pre-existing error — zero new failures. Frontend
untouched (no UI surface this chunk — `[U]` is C18's). Live full-cycle
(draft the whole video → approve 3 scenes → finalize → confirm only those 3
regenerate → ledger shows both passes) deferred to
`tasks/live-verification-queue.md` §C17 with an exact recipe — needs a live
DB + paid API session, not available in the sandbox.

## C18 — Draft/Finalize UI: GuidedNextStep Labels + Scene Approve Ticks + Savings Line (added 2026-07-19)

**Problem (checklist §1.3 [U], UX map §2):** C17 shipped `draft_pass`/
`finalize` chat-only. Three clickable-door gaps: GuidedNextStep's one-big-
button never mentioned either verb; ScenesWorkspaceTab had NO approve
affordance at all (C15b's own gap note — `approve_scene` was chat-only);
nowhere showed the "draft now, finalize later, vs all-premium" savings math.

**`[B]` thin — two doors, one registry, reused runners:** three new routes in
`routes/pipeline.py`, all calling `actions.RUNNERS[verb]` DIRECTLY (the exact
function chat's `_run_pending_action` already calls) — no parallel claim/
dedupe/dispatch logic written into the route layer:
- `POST /api/pipeline/actions/{video_id}/draft-pass` and `.../finalize` —
  shared body `_run_action_runner()` calls the runner, then detects whether
  it actually scheduled work by diffing `len(background_tasks.tasks)`
  before/after (every guard branch inside the runner — no draft tier,
  nothing to draft, already done, nothing approved, lane busy — returns
  without ever calling `add_task`, so a zero delta is a reliable "did not
  schedule" signal, unlike string-matching the runner's free-form chat
  reply). A non-scheduled reply that equals `actions._ALREADY_WORKING_REPLY`
  becomes HTTP 409 (concurrent-dispatch case); every OTHER non-scheduled
  reply ("already drafted", "nothing approved yet") is a graceful 200
  `status="skipped"` — a real "nothing to do yet" state is not an error.
- `POST /api/pipeline/actions/{video_id}/approve-scene` (body `{scene: int}`)
  — the missing clickable half of C15b's `approve_scene` verb. Calls
  `actions.RUNNERS["approve_scene"]` with `background_tasks=None` (the verb
  never schedules anything — free, synchronous, reversible), tenant-scoped
  video existence check first.
- `GET /api/pipeline/actions/{video_id}` (existing endpoint) gains an
  additive `breakdown` field per action, calling `actions.cost_breakdown`
  the same way chat's confirm cards already do — `None` for every verb
  except animate/build/draft_pass/finalize. This is the ONLY new backend
  math: `cost_breakdown` itself gains one additive key, `scene_count`
  (`len({row scenes})`) — GuidedNextStep needs N ("Finalize N approved
  scenes") server-computed, never guessed by counting asset rows (a scene
  has multiple).

**`[U]` — three pieces, existing components, existing design language:**
1. **GuidedNextStep** (`frontend/src/components/production/GuidedNextStep.tsx`):
   a new override branch, checked after the existing failure/running/
   celebrate branches (so it can never pre-empt a real in-flight task or
   error), sits between the old per-scene "Animate scene 1"/"Animate the
   rest" ladder and the "Create your thumbnail" step. `action.key ===
   "clips-taste"` (pictures ready, nothing animated) + a live, unblocked
   `draft_pass` action → **"Draft the whole video (~$X)"**; `action.key ===
   "thumbnail"` (everything animated) + a live, unblocked `finalize` action
   with `scene_count > 0` → **"Finalize N approved scenes (~$Y)"**. Both
   numbers are `cost_text` straight off `GET /api/pipeline/actions/{id}` —
   never hardcoded. Confirm flow reuses ScenesWorkspaceTab's existing
   two-tap `confirmable()` shape (tap arms → button becomes "Confirm — $X",
   a "Cancel" link appears; tap again fires) rather than inventing a new
   affordance or forcing a modal. On fire: `runDraftPass`/`runFinalize` →
   `status==="running"` calls the SAME `markStarted()` the rest of the file
   already uses (so the existing RUNNING banner + Stop button + poll-driven
   completion toast all apply for free); `status==="skipped"` is a plain
   info toast, never an error banner. A **"Skip"** link beside the button
   reuses the file's OWN existing `start()` handler unchanged — for the
   draft offer that's the pre-C18 "review, navigate to Scenes" behavior;
   for the finalize offer that's literally running the thumbnail stage
   directly (identical to what tapping the OLD "Create your thumbnail"
   button already did) — a fail-safe escape hatch if the finalize offer
   ever over-triggers (see gap note below). Whenever `draft_pass`/`finalize`
   aren't wired/blocked for a video (no draft-tier model registered), both
   offers resolve to `null` and the ORIGINAL pre-C18 ladder renders
   byte-identical — this is a strict superset, not a replacement.
2. **Scene Approve ticks** (`ScenesWorkspaceTab.tsx`'s scene header, next to
   the `SegmentBadge`): a small pill — "Approve" (outline) when no asset in
   the scene carries `status==='approved'`, "Approved ✓" (green, static)
   once one does, mirroring `_approved_scenes`' own "any approved row in a
   scene approves the whole scene" reading. Calls the new `approveScene()`
   API function → the SAME `approve_scene` runner chat's "approve scene N"
   already uses. Invalidates `["video-assets", id]` (the tick's own source
   of truth) AND `["video-actions", id]` (so `finalize`'s live `scene_count`
   /cost refreshes immediately — GuidedNextStep and this tab share that
   query key/cache). Only rendered when the scene has pictures (`sceneCards.
   length > 0`) — there's nothing to approve otherwise, matching the runner's
   own "no pictures yet" reply.
3. **Savings line**: computed in `GuidedNextStep.tsx` from the SAME two
   `VideoActionInfo.breakdown` objects backing both buttons — `draftTotal`/
   `allPremiumTotal` from `draft_pass`'s breakdown (its `all_premium_total`
   covers every not-yet-clipped row in the video, a stable whole-video
   reference regardless of whether draft already ran, since `cost_breakdown`
   doesn't filter on clip existence), `finalizeTotal`/`sceneCount` from
   `finalize`'s. The ONLY client-side arithmetic is `combinedTotal =
   draftTotal + finalizeTotal` (explicitly allowed — "addition of two
   server-provided numbers"). Renders as "Draft $X now + finalize N scene(s)
   $Y later ≈ $Z total vs $W all-premium" once scenes are approved, or a
   shorter "Draft $X now ≈ $X total vs $W all-premium if you stop there"
   before anything's approved yet (N=0) — shown under BOTH the draft and
   finalize buttons since it reads live off both actions regardless of
   which one is currently offered.

**Known gap, called out rather than silently accepted:** `cost_breakdown`'s
`finalize` quote does not know whether an approved scene's clip was already
regenerated by a PRIOR finalize call (it prices every currently-approved row
at its routed tier unconditionally, matching C17's own pre-existing
semantics — the money-safety backstop against a real double-spend is
`generation_passes`' scene-set-hash dedup INSIDE the runner, not the
estimator). Practical effect: after a finalize completes, if `action.key`
is still `"thumbnail"` (true — finalize doesn't change `clipsDone`/
`clipsTotal`) the Finalize button can keep re-offering itself with a
nonzero quote. Tapping it again is SAFE (the runner's pass-hash dedup
replies "already finalized… nothing's changed", `status="skipped"`, zero
re-spend) — but it is a UX wrinkle, not fixed this chunk (would need a
new "already finalized this exact set" signal threaded through
`cost_breakdown`, a real backend change out of this UI-only chunk's scope).
The "Skip — go straight to the thumbnail" link is the deliberate escape
hatch for this case; flagged for a future chunk if it proves annoying in
live use.

### Modified
| Path | Change |
|------|--------|
| `storyengine/backend/actions.py` | `cost_breakdown()` gains additive `scene_count` key (distinct scene count behind the itemization) |
| `storyengine/backend/routes/pipeline.py` | New `_run_action_runner()` helper + `POST /actions/{id}/draft-pass`, `POST /actions/{id}/finalize`, `POST /actions/{id}/approve-scene` (+ `ApproveSceneRequest`); `list_video_actions` gains additive `breakdown` per action |
| `storyengine/backend/tests/functional/test_c17_draft_pass_and_finalize.py` | +2 assertions (not new test functions) pinning `cost_breakdown["scene_count"]` for both draft_pass (3) and finalize (2) |
| `storyengine/backend/tests/functional/test_c18_guided_actions_ui.py` (new) | 7 tests: draft-pass/finalize route 404 tenant-scoping, dispatch-through-the-same-runner proof, `_ALREADY_WORKING_REPLY` → 409 translation, graceful non-error "skipped" for a plain nothing-to-do reply, approve-scene route 404 + runner-passthrough-with-correct-scene, `list_video_actions` breakdown additive-and-None-elsewhere |
| `storyengine/frontend/src/lib/api.ts` | `VideoActionInfo.breakdown: ChatCostBreakdown \| null`; `ChatCostBreakdown` gains `scene_count: number`; new `runDraftPass()`, `runFinalize()`, `approveScene()` |
| `storyengine/frontend/src/components/production/GuidedNextStep.tsx` | New draft/finalize override branch (two-tap confirm, savings line, skip escape hatch) between the old clips-taste and thumbnail steps; `["video-actions", id]` query added, folded into `refreshAll()` |
| `storyengine/frontend/src/components/production/ScenesWorkspaceTab.tsx` | Scene header gains the Approve tick/badge; `handleApproveScene()`; `approvingScene` state |

**Deploy-safety assessment:** ff-merge candidate, backend-leads-frontend
safe both directions. New backend on old frontend: the three new routes and
the `breakdown` field are pure additions an old frontend build never calls/
reads — zero behavior change. New frontend on old backend (the real risk,
since the VPS frontend only redeploys with `--with-frontend`): `GET .../
actions/{id}` without a `breakdown` key would make `VideoActionInfo.
breakdown` `undefined` at runtime despite the TS type claiming `| null` —
every read is optional-chained (`draftInfo?.breakdown?.total`, `?? draftInfo
?.cost ?? 0`), so both offers and the savings line fail closed to "nothing
to show" rather than crashing or rendering `undefined`/`NaN`; the three POST
routes would 404 on an old backend, caught by each handler's try/catch →
toast, never an unhandled exception. Backend and frontend changes are
correctness-additive on both sides of every skew direction — ff-merge safe
either way, though shipping both together (`--with-frontend`) is still the
intended path so the three new pieces actually appear.

**Verify:** `cd storyengine/backend && ./venv/bin/python -m pytest
tests/functional/test_c18_guided_actions_ui.py tests/functional/
test_c17_draft_pass_and_finalize.py -q` — 20 passed. Non-vacuous: `git stash
push -- storyengine/backend/actions.py storyengine/backend/routes/
pipeline.py` then rerunning `test_c18_guided_actions_ui.py` alone — all 7
fail (`KeyError: 'breakdown'`, `AttributeError` on the missing routes/
attributes) against pre-C18 source; stash popped clean, re-verified green.
`python -m py_compile` clean on `actions.py`, `routes/pipeline.py`, both test
files. Full backend suite: `./venv/bin/python -m pytest tests/ -q` — 1008
passed (1001 baseline + 7 new test functions; the 2 C17-file assertion
additions don't add test count) / 16 pre-existing failures (identical file
list to C15a-d/C16a-d/C17) / 1 pre-existing error — zero new failures.
Frontend: `npx tsc --noEmit` clean; `npm run build` compiles + typechecks
clean (fails only at static-prerender on the pre-existing sandbox gap,
`NEXT_PUBLIC_API_URL` unset — unrelated, same as every prior chunk's build
run). Live click-through (draft → tick 3 scenes → finalize → confirm
savings-line numbers match the ledger) deferred to `tasks/live-
verification-queue.md` §C18 — needs a live DB + paid API session, not
available in the sandbox.

## C16e — Upload Re-Publish Guard (added 2026-07-19)

**Problem (found by C16d's S7-9 resumability pass, docs/failure-modes.md's
"Per-Stage Resumability" table): `PipelineExecutor.run_upload` had NO
re-invoke guard at all** — unlike voice/sound/clips/images/thumbnail (all
skip-if-done by now), every call unconditionally ran either the per-tenant
native upload path (`youtube_publish.upload_video_to_youtube`) or the legacy
from-scratch bot. A second invocation (a routine status-machine resume, an
arq retry, a chat "upload it" double-tap, claude_orchestrator's skill
dispatch re-firing) minted a genuine SECOND YouTube draft — recoverable
(delete it in Studio) but messy, and burns ~1,600 of the 10,000/day YouTube
API quota units for nothing.

**Fix — mirrors C16d's `run_thumbnail` guard exactly, at the executor layer:**

1. `PipelineExecutor.run_upload(video_id, force: bool = False)` now checks
   `videos.youtube_url` OR `videos.youtube_video_id` right after fetching the
   video — either column being non-blank skips the entire method (both the
   native path's `channel_profiles` lookup and the legacy bot) and returns
   `{"status": "completed", "skipped": True, "youtube_url": ..., "youtube_video_id": ...}`
   plus an activity-log line, with `force=True` the only bypass. Every real
   caller (the autobuild finish chain via `run_next_step`'s `"rendered":
   self.run_upload` mapping, the arq/queue stage runner, `claude_
   orchestrator.py`'s skill dispatch, the manual `POST /upload/{video_id}`
   route, and the chat "upload" verb via `actions.make_action_step`) passes
   nothing and gets the skip-if-done default — no caller sets `force=True`
   yet (see the new `?force=true` route param below, added for a future
   genuinely-new-upload affordance).

2. `routes/pipeline.py`'s `POST /upload/{video_id}` gains `force: bool =
   False`, threaded to `executor.run_upload(video_id, force=force)` AND to
   `_enqueue_or_fallback(..., force=force)` (which already forwards
   `**stage_kwargs` to the arq path generically, unchanged since C16d).
   `worker.py`'s `arq_run_upload` gains the matching `force: bool = False`
   parameter, forwarded to `_run_stage`.

3. **Deliberate design DIFFERENCE from C16d's thumbnail verb** (which always
   forces): the chat "upload" verb does NOT force. New shared helper
   `actions.already_uploaded_reply(tenant_id, video_id)` returns a friendly
   message naming the existing YouTube URL (or id, if only that's set) when
   the video is already uploaded, or `None` otherwise. `routes/chat.py::
   _run_pending_action`'s "upload" branch calls this BEFORE claiming a
   `generation_claims` lane or scheduling any `background_tasks` — a
   double-tap on an already-uploaded video gets the friendly reply
   immediately and starts nothing (no wasted claim, no wasted task).
   **Justification:** unlike "redo the thumbnail" (unambiguous — there is no
   other way to say "regenerate" in this codebase, so C16d always forces),
   an explicit "upload it"/"publish" chat turn on an already-uploaded video
   is much more likely to be an accidental repeat (the same request re-sent,
   or the autobuild finish chain having just uploaded it moments earlier)
   than genuine intent to mint a second draft — and a duplicate draft is
   real, non-refundable quota burn, not just a redundant $0 API call. The
   executor's own `force=` guard (checked independently on every call,
   regardless of caller) is the actual money/quota-safety backstop; the chat
   short-circuit only keeps the reply honest instead of scheduling a task
   that would silently skip. A genuinely-new upload stays possible via the
   route's `force=true` (not yet wired to any chat verb or UI control this
   chunk — noted as a follow-up, since `UploadTab.tsx`'s "Upload to YouTube"
   button already disables itself once `youtubeUrl` exists, so there's no
   existing UI hook to force from).

**Invariant achieved:** a double-tap (any caller, any door) can never mint a
second YouTube draft; a deliberate re-upload stays possible via
`?force=true` on the manual route.

### New Files
| Path | Purpose |
|------|---------|
| `storyengine/backend/tests/functional/test_c16e_upload_skip_if_done.py` | 11 tests across 3 layers: executor guard (skip on url-set/id-set/force-bypass/blank-string/video-not-found, upload client asserted NOT called when skipped), `actions.already_uploaded_reply` (None/url-named/id-fallback), `chat._run_pending_action`'s upload branch (double-tap → no dispatch + friendly reply; not-yet-uploaded → normal claim+schedule) |

### Modified
| Path | Change |
|------|--------|
| `storyengine/backend/pipeline_executor.py` | `run_upload` gains `force: bool = False` + the skip-if-done guard (checks `youtube_url`/`youtube_video_id` before the channel_profiles lookup) |
| `storyengine/backend/actions.py` | New `already_uploaded_reply(tenant_id, video_id)` helper |
| `storyengine/backend/routes/chat.py` | Imports `already_uploaded_reply`; `_run_pending_action`'s "upload" branch checks it before claiming a lane/scheduling |
| `storyengine/backend/routes/pipeline.py` | `POST /upload/{video_id}` gains `force: bool = False` query param, threaded to the executor call and `_enqueue_or_fallback` |
| `storyengine/backend/worker.py` | `arq_run_upload` gains `force: bool = False`, threaded through `_run_stage` |

**Deploy-safety assessment:** ff-merge candidate. Purely additive: a new
optional `force` parameter (default `False`, preserving today's behavior
shape apart from now correctly refusing a duplicate draft) on `run_upload`/
the manual route/the arq handler; a new standalone helper function; one new
early-return branch in `_run_pending_action` that only fires for `verb ==
"upload"`. No column/schema change (youtube_video_id/youtube_url already
existed), no frontend change, no existing caller's signature broken (all new
params have defaults). Old frontend + new backend: byte-identical behavior
except a genuine safety improvement (no more accidental duplicate drafts).
Frontend untouched this chunk — no UI hook for `force=true` yet; noted as a
follow-up (a "Re-upload" affordance on `UploadTab.tsx` if a genuine
re-upload need ever comes up in practice).

**Verify:** `cd storyengine/backend && ./venv/bin/python -m pytest
tests/functional/test_c16e_upload_skip_if_done.py -q` — 11 passed.
Non-vacuous: `git stash push -- storyengine/backend/actions.py
storyengine/backend/pipeline_executor.py storyengine/backend/routes/chat.py
storyengine/backend/routes/pipeline.py storyengine/backend/worker.py` then
rerunning the same file — 8/11 fail (`AssertionError` from the boom-mocks
actually being reached, `AttributeError` on the missing `already_uploaded_reply`/
`_already_uploaded_reply`) against pre-C16e source; stash popped clean,
re-verified green. `python -m py_compile` clean on all 5 touched files + the
new test file. Full backend suite: `./venv/bin/python -m pytest tests/ -q` —
1019 passed (1008 baseline + 11 new) / 16 pre-existing failures (identical
file list to every prior chunk) / 1 pre-existing error — zero new failures.
Frontend untouched — confirmed via `git diff --stat` (no `storyengine/
frontend` paths in the diff). Live re-invoke-costs-zero-quota proof deferred
to `tasks/live-verification-queue.md` §C16e — needs a real connected YouTube
channel + an already-uploaded test video, not available in the sandbox.

## C20 — `style_presets` Catalog + `GET /api/style-presets` + Executor Mapping (added 2026-07-19)

**Problem (checklist §2.1, "5 rich Python visual profiles invisible to
users; UI shows only 6 shallow hardcoded presets"):** `skills/video-pipeline/
shared/profiles/visual/*.py` defines 5 real image-generation ENGINES
(neutral_v1, holographic_hud, cinematic_dossier, clay_mannequin,
cinematic_illustration — each with its own scene-type variety, camera/
composition cycling, anti-clustering rules, and a `TemplateMetadata`
dataclass explicitly labeled "what customers see during onboarding") — but
no route or table ever surfaced them. The only user-visible style pickers
today are the 6 shallow hardcoded `VISUAL_PRESETS` (pixar_3d/flat_2d/
realistic/anime/watercolor/comic, `frontend/src/lib/visual-presets.ts`).

**Fix — DB catalog + read route + executor precedence, [D]+[B] slice (C21
builds the gallery UI):**

1. **New `style_presets` table (migration 096, applied LIVE via Supabase
   MCP against `wrromlupsmyzrrcqlucn`, confirmed via `information_schema` +
   a live row-count query — 5 rows):** `id` (TEXT PK — the profile MODULE
   NAME, e.g. `"holographic_hud"`, exactly matching
   `shared.profiles.visual._PROFILE_MODULES`'s keys, so a valid row id is
   always something `load_profile()` already knows how to resolve),
   `display_name`, `description`, `tags` (jsonb), `best_for` (jsonb),
   `cost_tier`, `preview_url` (nullable — no generated preview image exists
   yet for any profile), `source` (`'python_profile'`), `sort`, `active`,
   timestamps. RLS enabled, no policies (playbook §7 pattern — backend
   connects as `postgres`, BYPASSRLS; this is a GLOBAL catalog, not tenant
   data, so there's no tenant policy to write anyway).
   - **Seed data extracted verbatim from each profile module's
     `TemplateMetadata`** (read every one of the 5 `.py` files directly —
     not invented copy): `neutral_v1` ("Neutral Documentary (default)",
     cost_tier low), `holographic_hud` ("Holographic Intelligence Display",
     low), `cinematic_dossier` ("Cinematic Intelligence Briefing", mid),
     `clay_mannequin` ("Clay Mannequin Dioramas", mid),
     `cinematic_illustration` ("Cinematic Animated Illustration", low).
     Excludes the `"mannequin_storytelling"` legacy alias (same module as
     cinematic_illustration, not a distinct 6th profile). `sort` follows
     `_PROFILE_MODULES`'s own declaration order — no subjective ranking
     introduced.
   - **Idempotency choice — justified:** `INSERT ... ON CONFLICT (id) DO
     UPDATE` refreshing ONLY the code-derived columns (display_name/
     description/tags/best_for/cost_tier/sort/source/updated_at).
     Deliberately does NOT touch `active`/`preview_url` — those are the two
     fields a future admin control (C21+) may mutate, and a reseed must
     never silently reactivate a disabled preset or wipe a manually-set
     preview image.
   - `videos.style_preset_id` (TEXT, nullable) added in the SAME migration,
     `REFERENCES style_presets(id) ON DELETE SET NULL`. In `schema.sql` the
     FK is attached via a separate `ALTER TABLE ADD CONSTRAINT` placed AFTER
     the `style_presets` CREATE TABLE (schema.sql runs top-to-bottom on a
     fresh DB per its own header — the `videos` table is created far
     earlier in the file, so an inline forward-reference there would break
     a fresh bootstrap).

2. **`GET /api/style-presets`** (new `routes/style_presets.py`, registered
   in `main.py`): returns `{"presets": [...]}` ordered `sort, id`, active
   rows only, JSONB `tags`/`best_for` defensively parsed (mirrors
   `routes/visual_styles.py`'s `_parse_jsonb`). **Auth posture mirrors `GET
   /api/models`** (`routes/model_registry.py`): `Depends(get_tenant_id)`
   required even though the data is a global (non-tenant-scoped) catalog —
   consistent with every other route in this app, no reason to leave a
   style-catalog read unauthenticated.

3. **`create_video` accepts optional `style_preset_id`** (`models.py`'s
   `CreateVideoRequest`): new `routes/videos.py::_resolve_style_preset_id`
   validates it against `style_presets` (must exist AND be active); a
   real id passes through unchanged, blank/`None` is a silent no-op (the
   common case), an unknown/inactive id raises `400` — matching this same
   function's existing `reference_url` precedent a few lines above (fail
   fast on a bad explicit choice, don't silently drop it, since a picker UI
   should never send a bogus id). Stored on `videos.style_preset_id` in the
   same INSERT; also added to `get_video`'s SELECT + `VideoDetail` response
   (read-layer completeness — C21's UI doesn't consume it yet, but nothing
   about exposing an already-stored column is "dead code").

4. **Executor mapping — the VISUAL_PROFILE env seam**
   (`pipeline_executor.py`'s `_load_idea`, checklist's "existing seam at
   L6358", re-located this session at what is now ~L6385 after C19's
   sweep): new module-level pure helper `_resolve_visual_profile_id(idea)`
   replaces the old one-line `idea.get(IdeaFields.VISUAL_STYLE) or
   "neutral_v1"`.
   - **Before:** `visual_style = idea.get(IdeaFields.VISUAL_STYLE) or
     "neutral_v1"`
   - **After:** `visual_style = _resolve_visual_profile_id(idea)`, where the
     helper is `(idea.get(IdeaFields.STYLE_PRESET_ID) or "").strip() or
     (idea.get(IdeaFields.VISUAL_STYLE) or "").strip() or "neutral_v1"`.
   - **Fail-soft, exactly as required:** a video with no `style_preset_id`
     (every video created before this chunk, and any video where a creator
     never picks one) reproduces the ORIGINAL resolution byte-for-byte —
     the new field only wins when a validated, real id is present.
   - New `IdeaFields.STYLE_PRESET_ID = "Style Preset Id"`
     (`orchestrator/pipeline_constants.py`) + `"Style Preset Id":
     "style_preset_id"` added to `supabase_adapter.py`'s `IDEA_FIELD_MAP`
     (auto-reverses into `IDEA_COLUMN_MAP`) — without this mapping,
     `_row_to_idea` silently drops the raw `style_preset_id` column and the
     new field would never reach `_load_idea`'s `idea` dict at all.

**A real, pre-existing bug this surfaced (not fixed here, noted for C21):**
`videos.visual_style` is populated TODAY by the 6-shallow-preset system
(values like `"Pixar 3D"`, traced via `GET /style-default`'s
`_normalize_style_preset` call and `ChatCore.tsx`'s `PRESET_LABELS` map),
not by a Python profile module id — so the "existing" VISUAL_PROFILE seam
has likely been silently falling back to `"neutral_v1"` for every real
tenant since it was written (`load_profile()` logs `"Unknown profile:
Pixar 3D"` and returns `None`, never raising). C20's `style_preset_id` is
the FIRST value ever written to that seam guaranteed to resolve correctly,
by construction (validated against the same id space `load_profile()`
reads).

**S9-5 relationship note (docs/reports/2026-07-17-storyengine-agent-audit-
findings.md's "two parallel style systems" finding) — three axes exist, not
two:**
1. **`style_presets` (this chunk) → `VISUAL_PROFILE` env** — the
   STRUCTURAL image-engine choice (which Python module's scene-type/camera/
   composition logic runs). The 5 rich profiles live here.
2. **`visual_styles` table (migration 010, existing "VisualStyle CRUD" on
   `profile/page.tsx`, query key `["visualStyles"]`) → exported via
   `upsert_active_visual_style`/`_export_visual_style` into
   `videos.image_style_override` → `VISUAL_STYLE_DESCRIPTION` env** —
   free-text aesthetic OVERLAY (a project-scoped library of named "looks",
   each with its own reference characters), stacked ON TOP of whichever
   engine axis 1 selects.
3. **Frontend's hardcoded `VISUAL_PRESETS` (6 shallow items,
   `visual-presets.ts` + `producer_prompt.VISUAL_PRESETS`)** — ALSO feeds
   the SAME axis as #2 (`VISUAL_STYLE_DESCRIPTION`), just via a different,
   non-DB-backed source of free-text look sentences. This is the thing the
   checklist's "UI shows only 6 shallow hardcoded presets" complaint is
   actually about.
   Axis 1 (structural engine) and axis 2/3 (aesthetic overlay) are
   COMPLEMENTARY, not duplicates — a video can meaningfully pick BOTH a
   `style_preset_id` (e.g. `holographic_hud`'s zero-human-figures HUD
   engine) AND an `image_style_override` (a specific color/lighting
   description layered into that engine's prompts). **C21's job:** build
   the gallery UI for axis 1 (this chunk's catalog) and DECIDE whether/how
   to reconcile axis 2 vs axis 3 (both already serve the same purpose;
   `visual_styles` is the more capable, DB-backed, user-extensible one) —
   NOT to merge axis 1 into either of them, they answer different
   questions.

### New Files
| Path | Purpose |
|------|---------|
| `storyengine/backend/migrations/096_style_presets.sql` | `style_presets` table + 5-row seed (idempotent `ON CONFLICT DO UPDATE`, code-derived columns only) + `videos.style_preset_id` column, applied live |
| `storyengine/backend/routes/style_presets.py` | `GET /api/style-presets` |
| `storyengine/backend/tests/functional/test_c20_style_presets.py` | 10 tests: route shape/order/JSONB-string-tolerance/auth-required, `_resolve_style_preset_id` (blank/valid/invalid), `_resolve_visual_profile_id` (precedence/fail-soft/blank-is-missing) |

### Modified
| Path | Change |
|------|--------|
| `storyengine/schema.sql` | `style_presets` table (appended after `generation_passes`, migration-096-era) + `videos.style_preset_id` column (no inline FK — see ordering note above) + the FK constraint attached after `style_presets` exists |
| `storyengine/backend/main.py` | Imports + registers `style_presets.router` |
| `storyengine/backend/models.py` | `CreateVideoRequest.style_preset_id` + `VideoDetail.style_preset_id` |
| `storyengine/backend/routes/videos.py` | New `_resolve_style_preset_id` helper; `create_video`'s INSERT + `get_video`'s SELECT/response gain `style_preset_id` |
| `storyengine/backend/pipeline_executor.py` | New module-level `_resolve_visual_profile_id(idea)`; `_load_idea` calls it instead of the inline `idea.get(IdeaFields.VISUAL_STYLE) or "neutral_v1"` |
| `storyengine/backend/supabase_adapter.py` | `IDEA_FIELD_MAP` gains `"Style Preset Id": "style_preset_id"` |
| `skills/video-pipeline/orchestrator/pipeline_constants.py` | `IdeaFields.STYLE_PRESET_ID = "Style Preset Id"` |

**Deploy-safety assessment:** ff-merge candidate. Purely additive: a new
table + a new nullable FK column (default NULL, existing rows unaffected);
a new route (no existing route touched); `CreateVideoRequest`/`VideoDetail`
gain optional fields with `None` defaults (every existing caller that omits
`style_preset_id` behaves identically); `_resolve_visual_profile_id`'s
fail-soft chain reproduces the EXACT prior expression when
`style_preset_id` is absent (proven by
`test_fails_soft_to_legacy_visual_style_when_preset_missing` +
`test_fails_soft_to_default_when_both_missing`). No existing migration,
route, or model field renamed or removed. Frontend untouched — confirmed
via `git diff --stat` (no `storyengine/frontend` paths in the diff); C21
builds the gallery UI against this endpoint.

**Verify:** `cd storyengine/backend && ./venv/bin/python -m pytest
tests/functional/test_c20_style_presets.py -q` — 10 passed. Non-vacuous:
`git stash` (tracked files only — the new untracked `style_presets.py`/
migration/test file stay in place) then rerunning — collection ERRORS
(`ImportError: cannot import name '_resolve_visual_profile_id' from
'pipeline_executor'`) against pre-C20 source; `git stash pop` restored
clean, re-verified green. `python -m py_compile` clean on all 6 touched/
added `.py` files. Full backend suite: `./venv/bin/python -m pytest tests/
-q` — **1029 passed (1019 baseline + 10 new) / 16 pre-existing failures
(identical file list to every prior chunk) / 1 pre-existing error — zero
new failures.** `test_schema_sql_migrations_drift.py` (which independently
checks every migration's table appears in `schema.sql`) passes, confirming
the `style_presets` table was actually added to `schema.sql`, not just the
migration file. Live checks: `information_schema.columns` on both
`style_presets` (12 columns, correct types) and `videos.style_preset_id`
(TEXT) confirmed via Supabase MCP against `wrromlupsmyzrrcqlucn`; live
row-count/content query confirms exactly 5 seeded rows in the expected sort
order with the expected display_name/cost_tier/source values;
`pg_class.relrowsecurity` confirms RLS is enabled. Frontend untouched (no
`[U]` this chunk — C21 owns the gallery). Live "pick a preset → generated
prompts carry its style system" end-to-end check (checklist §2.1's own
`[V]` line) deferred to `tasks/live-verification-queue.md` §C20 — needs a
live DB + a real pipeline run, and completes together with C21 once the
picker UI exists to drive it from.

## C19a — Frontend-state fixes: poll consolidation + price source + redundancy trim (added 2026-07-19)

**Trigger:** §S9 frontend-state sweep (S9-1/S9-2/S9-8), the pre-C21 gate. Frontend-only, no
new features, no visual changes — a behavior-preserving refactor.

**S9-1 — ONE task watcher per video page.** `pipeline/[videoId]/page.tsx` used to run its own
gated `useTaskPoller` (Run-Next flow) WHILE `GuidedNextStep` (always-on) and the active tab
(`ScenesWorkspaceTab` always-on, or one of 7 other tabs gated by their own local `taskRunning`)
each mounted a SECOND independent `useTaskWatcher`/`useTaskPoller` — up to 3 concurrent 3s
`setInterval`s hitting `getPipelineTaskStatus` for the same video. Fix: `page.tsx` now owns the
ONE `useTaskWatcher` call; a new `TaskWatcherBridge` (`{running, message, markStarted, subscribe}`)
is passed down as a prop to `GuidedNextStep` and all 9 live tabs. A new `useSharedTaskWatcher`
hook (in `hooks/use-task-poller.ts`) is the drop-in replacement for both the old always-on
`useTaskWatcher` (GuidedNextStep, ScenesWorkspaceTab — `enabled` defaults `true`) and the old
gated `useTaskPoller` (7 other tabs — `enabled: <tab's own local taskRunning>`, same semantics as
before: a tab's `onComplete`/`onFailed` only fires while it believes it started the work, exactly
like the standalone poller's `enabled` prop used to gate its own interval). Chose **props over
context**: only 10 direct children of one page component consume the bridge, no deep nesting —
React Context would add indirection for zero benefit here.

**S9-2 — GuidedNextStep price source.** `getNextAction()` (`lib/next-action.ts`) computed clip
cost via `clipCost()`, which reads the mutable `CLIP_COST_PER_MODEL` module cache — populated by
`page.tsx`'s own `useEffect` one render AFTER `videoActions.prices.clip` arrives, so the banner
could show the `$0.30` fallback (or a previous video's price) on first paint. Fix: `NextActionInputs`
gained an optional `clipPriceByModel` field; a new `resolveClipCost()` helper prefers it over the
cache, falling back to `clipCost()` unchanged when absent (so `getNextAction`'s only other would-be
caller, if one is ever added, keeps the old behavior for free). `GuidedNextStep` now passes
`videoActions?.prices?.clip` (a query it already ran) straight through — reactive on the SAME
render the fetch resolves, mirroring `ScenesWorkspaceTab`'s `priceForModel`/`perClip` pattern
referenced in the finding.

**S9-8 — redundancy trim: decided to KEEP, not drop.** The video page runs 3 freshness mechanisms
against `["video-assets", videoId]` during a running task: the hoisted watcher's `onProgress`
invalidation (registered only by `ScenesWorkspaceTab`, only while it's the mounted/active tab),
`page.tsx`'s own 5s `refetchInterval` (unconditional, every tab, drives the cost estimate), and SSE
(`onTaskProgress` — fires only on the terminal `"completed"` status, never mid-stage; `onStageChange`
— fires only on a backend status-string transition). These do NOT cover the same events: the 5s
interval is the ONLY thing keeping `video-assets` (and the cost estimate) fresh page-wide while a
non-Scenes tab is active during a running stage. Removing it would go stale under that condition —
a real regression. Left in place, with the reasoning inline as a comment at the query site
(`page.tsx`, `costAssets` query).

### Modified
| Path | Change |
|------|--------|
| `storyengine/frontend/src/hooks/use-task-poller.ts` | New `TaskWatcherHandlers`/`TaskWatcherBridge` types + `useSharedTaskWatcher()` hook (subscribes to the bridge instead of opening its own interval) |
| `storyengine/frontend/src/app/pipeline/[videoId]/page.tsx` | Hosts the ONE `useTaskWatcher`; builds the `subscribe`-based bridge; its own Run-Next flow becomes a `useSharedTaskWatcher` subscriber; `taskWatcher` passed to `GuidedNextStep` + all 9 tabs; S9-8 reasoning documented at the `costAssets` query |
| `storyengine/frontend/src/lib/next-action.ts` | `NextActionInputs.clipPriceByModel` (optional) + `resolveClipCost()` helper; both `clips-taste`/`clips-rest` cost computations use it |
| `storyengine/frontend/src/components/production/GuidedNextStep.tsx` | Takes `taskWatcher` prop, drops its own `useTaskWatcher`; passes `videoActions.prices.clip` into `getNextAction()` |
| `storyengine/frontend/src/components/production/ScenesWorkspaceTab.tsx` | Takes `taskWatcher` prop, drops its own `useTaskWatcher` |
| `storyengine/frontend/src/components/production/{ResearchTab,ScriptVoiceTab,CharactersTab,EnvironmentsTab,SoundTab,ThumbnailTab,RenderTab}.tsx` | Take `taskWatcher` prop; swap `useTaskPoller` → `useSharedTaskWatcher` (same `enabled`-gated `onComplete`/`onFailed`/`onProgress` bodies, unchanged) |

**Known minor deviation (disclosed, not hidden):** `RenderTab` previously polled at a slower 10s
cadence (render is a 10-20 minute job); it now rides the shared watcher's fixed 3s cadence like
every other consumer, since one shared interval can't serve two cadences. This can only make
Render's own completion/progress checks land SOONER, never later — the extra lightweight status
GETs over a 10-20 minute render are immaterial. Everything else was already 3s.

**Out of scope (confirmed dead, left untouched — S9-6/C19b's job):** `ScriptTab.tsx`,
`StoryboardTab.tsx`, `VoiceReviewTab.tsx` still call the standalone `useTaskPoller` — none are
imported by `pipeline/[videoId]/page.tsx` (verified via `grep -rln` for each component name across
`app/`+`components/`); leaving them alone rather than wiring dead code into the new bridge.

**Deploy-safety assessment:** ff-merge candidate. Behavior-preserving refactor: every tab's
`onComplete`/`onFailed`/`onProgress` body is byte-identical to before, only the wrapper hook
changed; the `enabled` gate (per-tab `taskRunning` flag) is preserved exactly, so no tab can now
fire its side effects for work it didn't start (verified by reading every onFailed body — several
show attributed toasts/alerts, e.g. `"Sound generation failed"`, that would have been a real
regression if subscriptions were unconditional instead of `enabled`-gated). Frontend-only; no
backend/schema/route touched. What could regress: a stale `taskWatcher` prop reference across
renders causing a missed subscription — ruled out by `useMemo`-stabilizing the bridge object on
`[running, message, markStarted, subscribe]` and `subscribeTaskWatcher`/dispatch callbacks using
refs internally (same pattern the pre-existing hooks already used), so `tsc`/build catch any
prop-shape mismatch and did.

**Verify:** `cd storyengine/frontend && npx tsc --noEmit` — clean. `npm run build` — compiles and
typechecks clean; fails at the prerender step on `NEXT_PUBLIC_API_URL is required in production
builds`, confirmed pre-existing by `git stash`-ing this chunk's changes and re-running the same
build (identical failure against unmodified `main`). Grep-proof: exactly one `useTaskWatcher(`
mount remains (`page.tsx`), and `useSharedTaskWatcher(` appears in all 9 live consumers (`page.tsx`,
`GuidedNextStep`, `ScenesWorkspaceTab`, `ResearchTab`, `ScriptVoiceTab`, `CharactersTab`,
`EnvironmentsTab`, `SoundTab`, `ThumbnailTab`, `RenderTab`) and zero dead files. No backend files
touched — no Python suite run, correctly (nothing to run). No frontend unit-test harness exists in
this repo; no Playwright click-through was run this session — deferred to
`tasks/live-verification-queue.md` §C19a (one build running → banner + tab both show progress;
completion refreshes assets exactly once, not 2-3x).

## C21a — Card-Kind Lookup Refactor + New Video "Look Engine" Gallery (added 2026-07-19)

**Split from C21 (checklist §2.1 [U]).** The full C21 brief was: gallery UI in
both doors + chat LOOK card sourced from `GET /api/style-presets` + DELETE
`visual-presets.ts`/`producer_prompt.VISUAL_PRESETS` + producer/chat backend
sourcing. Tracing the deletion (Step 1 of the wiring-audit protocol, before
touching code) surfaced a real entanglement that changes the risk profile:
`routes/chat.py`'s `_detect_reference_style_preset` + `_annotate_style_
recommendation` ALSO import `producer_prompt.VISUAL_PRESETS`, but for a
DIFFERENT purpose than the LOOK card — a vision call classifies a modeled
reference video's animation medium (3D CG vs 2D flat vs anime vs
photoreal...) into one of those 6 ids, entirely unrelated to which of the 5
`style_presets` ENGINE rows (holographic_hud, clay_mannequin, ...) is
picked. Deleting the dict without first deciding how (or whether) to keep
that vision-classification feature working is exactly the kind of
"patch around a design flaw" CLAUDE.md's Anti-Bandaid rule says to stop and
question — so this chunk ships C21a (the safe, self-contained, high-value
half) and defers C21b (deletions + producer backend sourcing + the chat
LOOK card + the vision-detector fix) to its own pass. This is the exact
split the chunk brief itself pre-authorized ("Too big → split C21a/C21b").

**C21a scope — frontend only, two independent pieces:**

1. **S9-3 fix — one `cardKind()` lookup replaces 4 scattered `card.id`
   string-match sites in `ChatCore.tsx`** (audit's L201, 460-479, 685-691,
   1349 — all four confirmed still present pre-change by direct read, not
   re-trusting the audit's line numbers). `cardKind(card): "prompt_apply" |
   "confirm_action" | "secure_key" | "connect" | "images" | "generic"` is
   the ONE place a card gets classified; every render site now branches on
   its result instead of comparing `card.id`/a field inline:
   - The `actionCard` finder (`lastCards?.find(...)`) now checks
     `ACTION_CARD_KINDS.has(cardKind(c))` instead of a 3-literal `||` chain.
   - The 3-branch `actionCard?.id === "X" && <Component>` JSX became ONE
     `ACTION_CARD_RENDERERS: Partial<Record<CardKind, () => ReactNode>>`
     lookup + `{actionCard && !sending && ACTION_CARD_RENDERERS[cardKind(actionCard)]?.()}`
     — every prop/handler byte-identical to the branch it replaces (confirmed
     by diff: only the dispatch shape changed, not a single callback body).
   - `MessageThread`'s inline scene-boards filter now reads
     `cardKind(c) === "images"` (same field-based guard as before, just
     routed through the shared function instead of its own inline check).
   - `SelectorCards`' connect-button check now reads `cardKind(card) === "connect"`.
   - Before: 4 independent literal comparisons, no shared vocabulary. After:
     1 function + 1 render-lookup table; a 5th card kind (C21b's LOOK
     gallery) is one new `if` in `cardKind()` + one new entry in
     `ACTION_CARD_RENDERERS`/an options-renderer, not a 5th scattered check.
   - `isSliderCard` (a pre-existing single unified helper, not one of the
     audit's 4 scattered sites) is untouched.

2. **New Video "Look Engine" gallery** (`app/pipeline/page.tsx`) — the FIRST
   UI to ever send `style_preset_id` (C20 wired the backend end-to-end but
   no caller ever populated it). New section, clearly separate from and
   ABOVE the existing "Style description" section (renamed from "Visual
   style" for clarity — same fields/logic, untouched):
   - **Two independent, complementary axes, both visible at once** (S9-5):
     "Look engine" (new, optional, `style_preset_id` — WHICH engine's
     scene/camera/composition craft runs) sits above "Style description"
     (existing, optional, `image_style_override`/`visual_style_label` — a
     free-text aesthetic layered on top). Helper copy under each explains
     the distinction; picking one never clears the other, and both travel
     independently in `createVideo`'s payload. This is the UI reconciliation
     C21's brief asked for — NOT a backend merge (there is none; C20 already
     established these are different `videos` columns feeding different env
     seams).
   - New `frontend/src/hooks/use-style-presets.ts` — `useStylePresets()`
     wraps `useQuery({queryKey: ["style-presets"], queryFn: getStylePresets,
     staleTime: 5min})`, mirroring `ScenesWorkspaceTab`'s `["models"]` query
     exactly (same staleTime, same "long-lived code-derived catalog" reasoning).
     ONE fetcher (`getStylePresets` in `lib/api.ts`); C21b's chat LOOK card
     reuses the SAME hook so React Query dedupes the request under the SAME
     key instead of each door fetching its own copy.
   - New `frontend/src/components/style/StylePresetGallery.tsx` — the
     reusable gallery card grid: loading (spinner), error (message + retry
     button calling `refetch()`), empty (fail-soft text: "your channel's
     default will be used" — matches `_resolve_visual_profile_id`'s own
     fail-soft chain, so the copy is honest about what happens), and the
     populated grid (display_name, up to 2 `best_for` tags, a `cost_tier`
     badge). **S9-4 onError, built in from the start:** since NO seeded
     `python_profile` row has a `preview_url` yet (confirmed via C20's live
     row check), "no url" is treated as the NORMAL case — a labeled
     placeholder icon, not a broken `<img>` pointed at nothing; a future
     `preview_url` that 404s falls back the same way via `onError`.
   - `lib/api.ts` gained `StylePreset`/`StylePresetsResponse` types (mirror
     the backend `StylePresetResponse` field-for-field) + `getStylePresets()`
     + `style_preset_id?: string` on `createVideo`'s payload type (the
     frontend `createVideo` type had NEVER gained this field — C20 was
     backend-only, confirmed via that chunk's own "frontend untouched"
     note).
   - `handleCreate` now sends `style_preset_id: styleEngineId || undefined`
     alongside the existing `image_style_override`/`visual_style_label` —
     additive, the existing style-description flow's payload fields are
     unchanged. New `styleEngineId` state resets on both modal-close and
     mutation-success (mirroring `stylePresetId`/`styleCustom`'s existing
     reset sites).
   - **S9-4 also fixed on the PRE-EXISTING "Style description" preset grid**
     (the 6-item picker, still live until C21b deletes it): new
     `PresetPreviewImage` (page.tsx) and `PresetOptionImage` (ChatCore.tsx)
     wrap the old bare `<img>` with the same onError → label-swap pattern,
     since that picker remains user-facing for one more chunk and the
     constraint was scoped to "C21," not specifically "C21b."

**C21b — what's left, and the recommended approach (for whoever picks it
up):** delete `visual-presets.ts` + `producer_prompt.VISUAL_PRESETS`; make
`_spec_to_create_request` in `routes/chat.py` set `CreateVideoRequest.
style_preset_id` directly from the card pick (drop the `VISUAL_PRESETS`
dict lookup entirely — `style_preset_id` is validated downstream by
`_resolve_style_preset_id` already, no backend duplication needed); add a
fail-soft `_style_presets_brief(tenant_id)` (try/except → a minimal
hardcoded 1-2-line default, never a crashed turn) injected into BOTH brief
compositions (`_seed_producer` ~L2990, `chat_turn`'s intake turn ~L3626) so
Claude's LOOK card options come from the live table instead of a hardcoded
6-value instruction (`PRODUCER_SYSTEM_PROMPT`'s CARD GUIDANCE "LOOK" bullet
needs rewriting to reference that block, matching how `reference_url`'s
"use these EXACT values" pattern already works elsewhere in the prompt); add
the new gallery-card kind to `ChatCore.tsx`'s `cardKind()`/renderer tables
(this chunk built the lookup specifically so this is a one-entry addition).
**The vision-detector entanglement:** `_detect_reference_style_preset` +
`_annotate_style_recommendation`'s style-card branch answer "what does the
reference video's ANIMATION MEDIUM look like" (pixar_3d/flat_2d/realistic/
anime/watercolor/comic) — a question with NO correct answer in the engine
catalog's vocabulary (holographic_hud/cinematic_dossier/clay_mannequin/
cinematic_illustration/neutral_v1 aren't animation-medium categories).
Recommended fix: give the vision classifier its OWN small private constant
(e.g. `_REFERENCE_VISION_STYLES` inside `chat.py`, not exported, not a
second copy of a "duplicated list" since it now serves ONLY this one
narrow purpose) so the reference-modeling feature keeps working unchanged,
while the LOOK gallery card's options come from the DB and the
`recommended_value`/`recommended_hint` annotation either stops firing on
that card (mismatched vocabulary) or is dropped entirely until a genuine
vision-classify-into-5-engines prompt is designed — NOT attempted here, out
of scope for a mechanical deletion pass.

### New Files
| Path | Purpose |
|------|---------|
| `storyengine/frontend/src/hooks/use-style-presets.ts` | Shared `useStylePresets()` — one `["style-presets"]` query, reused by the New Video gallery and (C21b) the chat LOOK card |
| `storyengine/frontend/src/components/style/StylePresetGallery.tsx` | The reusable Look Engine gallery card grid — loading/error/empty states, onError-safe preview images |

### Modified
| Path | Change |
|------|--------|
| `storyengine/frontend/src/lib/api.ts` | `StylePreset`/`StylePresetsResponse` types + `getStylePresets()`; `createVideo`'s payload type gains `style_preset_id?: string` |
| `storyengine/frontend/src/app/pipeline/page.tsx` | New "Look engine" section (gallery, `styleEngineId` state) above the renamed "Style description" section; `handleCreate` sends `style_preset_id`; new `PresetPreviewImage` onError wrapper for the existing preset grid |
| `storyengine/frontend/src/components/chat/ChatCore.tsx` | New `cardKind()` + `ACTION_CARD_KINDS`/`ACTION_CARD_RENDERERS` lookup replacing 4 scattered `card.id` string-match sites; new `PresetOptionImage` onError wrapper for the existing LOOK option image |

**Deploy-safety assessment:** ff-merge candidate. Purely additive/refactor,
frontend-only: `createVideo`'s new field is optional (every existing caller
that omits it behaves identically); the `cardKind()` refactor is
behavior-preserving by construction (every prop/handler carried over
unchanged, verified by diff); the onError wrappers only change what happens
on an already-broken image load (strictly better, never a regression); the
new gallery section is additive UI with its own loading/error/empty states
that never blocks form submission. Backend untouched — confirmed via `git
diff --stat` (no `storyengine/backend` paths). **Skew check:** old frontend
+ new backend — N/A, no backend changed this chunk. New frontend + current
(C20) backend — `GET /api/style-presets` already exists and already returns
5 real rows (confirmed live in C20), so the gallery renders real data
immediately, not a placeholder; `style_preset_id` on `createVideo` already
validates server-side (`_resolve_style_preset_id`, C20) so a bad value 400s
exactly like `reference_url` does today, never a silent drop.

**Verify:** `cd storyengine/frontend && npx tsc --noEmit` — clean. `npm run
build` — compiles and typechecks clean (`Compiled successfully`, `Finished
TypeScript`); fails at the prerender step on the same pre-existing
`NEXT_PUBLIC_API_URL is required in production builds` error documented in
every prior frontend chunk (C19a et al.), not a regression from this
change. Grep-proof: zero remaining `card.id === "` / `c.id === "` comparisons
in `ChatCore.tsx` outside `cardKind()`'s own definition and the pre-existing,
unrelated `isSliderCard` helper (`grep -n '\.id === "' ChatCore.tsx` — 4
lines, all inside `cardKind()`/`isSliderCard`). No backend files touched —
no Python suite run (nothing to run; confirmed via `git status --short`:
only `storyengine/frontend/**` + this file + the checklist changed). No
frontend unit-test harness exists in this repo; a live click-through
(gallery renders 5 real presets, picking one reaches `create_video` with a
valid `style_preset_id`, a build actually runs the `holographic_hud`
engine) is deferred to `tasks/live-verification-queue.md` §C20/§C21 (extended
below), completing together with C21b once the chat door is wired too.

---

## C21b — Delete the Duplicated Preset Lists + Producer/Chat Backend
Sourcing + Chat Gallery Card (added 2026-07-19)

**P2.1b part 2 (checklist §2.1 [U]/[V], closing out the split C21a left
open).** §C21a's split rationale (above) found a real entanglement before
any deletion could be safe: `producer_prompt.VISUAL_PRESETS` served TWO
unrelated vocabularies at once — (a) the chat "style" LOOK card's six
style-DESCRIPTION options (pixar_3d/flat_2d/realistic/anime/watercolor/comic
— a free-text aesthetic overlay, feeding `image_style_override`/
`visual_style_label` and, via `channel_format.render_style_for_preset`,
C13b's `render_style` guardrail) and (b) the reference-video vision
classifier's (`_detect_reference_style_preset`/`_annotate_style_
recommendation`) ANIMATION-MEDIUM vocabulary — the SAME six ids answering a
completely different question, with NO valid mapping onto the 5
`style_presets` ENGINE rows (holographic_hud/cinematic_dossier/
clay_mannequin/cinematic_illustration/neutral_v1).

**Resolution — one canonical dict, two use sites, one new axis:**

1. **`channel_format.STYLE_DESCRIPTIONS`** (new module-level dict, `channel_
   format.py`) is now the SINGLE source for the six style-description ids —
   replacing `producer_prompt.VISUAL_PRESETS` (deleted entirely, name and
   all) and `frontend/src/lib/visual-presets.ts` (deleted entirely). Chosen
   home: `channel_format.py` already owned this vocabulary's domain
   (`style_preset_for_format`, `render_style_for_preset`, `_ANIMATED_
   PRESETS` all already lived there) and has zero import-cycle risk (a leaf
   module, imports only `database`) — cleaner than either producer_prompt.py
   (now correctly narrowed to prompt TEXT, not data) or a brand-new module.
   Four call sites now import from here: `routes/chat.py`'s
   `_detect_reference_style_preset` (renamed from reading `VISUAL_PRESETS`
   — same ids, honestly reframed in its docstring as "ANIMATION MEDIUM
   classification", not a second copy), `_annotate_style_recommendation`
   (label lookup), `_spec_to_create_request` (the chat "style" card's
   id → `image_style_override`/`visual_style_label` mapping, UNCHANGED
   behavior — pinned by test), and `routes/projects.py`'s
   `_channel_style_dna` (cast-generation look sentence).
2. **New `GET /api/style-descriptions`** (`routes/style_descriptions.py`,
   registered in `main.py`) — a thin read-only view over `channel_format.
   STYLE_DESCRIPTIONS`, same posture as `GET /api/models` over a Python
   constant (no DB table needed — this axis was never DB-backed and still
   isn't; nothing to seed/migrate). This is the ONE source both frontend
   doors now read instead of each hardcoding a copy.
3. **A genuinely NEW, ADDITIVE axis reaches chat for the first time:**
   `CreateVideoRequest.style_preset_id` (the 5-row ENGINE catalog, C20) was
   only reachable from the New Video door before this chunk (C21a). Chat's
   `_spec_to_create_request` now ALSO reads `spec.get("style_preset_id")`
   and passes it straight through — validated downstream by the existing
   `_resolve_style_preset_id` (no duplicate validation). This is deliberately
   ADDITIVE to, not a replacement of, the axis-B mapping above — both a
   `visual_style` (description) pick and a `style_preset_id` (engine) pick
   can travel on the same `CreateVideoRequest` simultaneously, neither
   clobbering the other (pinned by `test_spec_to_create_request_both_axes_
   together`).

**Correcting §C21a's own recommendation:** that section's handoff text said
`_spec_to_create_request` should "drop the VISUAL_PRESETS dict lookup
entirely" and set `style_preset_id` "directly from the card pick" — read
literally, that would have REPURPOSED the existing "style" card (which emits
one of the 6 axis-B ids) to instead emit one of the 5 axis-A ids, silently
breaking `image_style_override`/`visual_style_label`/the C13b guardrail for
every existing chat flow. This chunk's own brief (checklist entry + UX map
§3) is explicit that the LOOK card must carry BOTH axes at once — so the
axis-B mapping in `_spec_to_create_request` was KEPT unchanged (just
re-sourced from `channel_format.STYLE_DESCRIPTIONS`), and `style_preset_id`
passthrough was added as a THIRD, independent field read from a NEW,
separate `"look_engine"` card/spec key — never sharing the `visual_style`
field the "style" card already owns. Flagging this per CLAUDE.md's
instruction to say so, not silently follow a written recommendation found to
be wrong on inspection.

**The new "look_engine" card (chat's door onto the C20/C21a engine
gallery):**
- `producer_prompt.PRODUCER_SYSTEM_PROMPT` gained a new CARD GUIDANCE bullet
  ("LOOK ENGINE") teaching the producer this is an ADVANCED, OPTIONAL,
  separate axis from "style" — offered rarely (only when the creator
  explicitly asks about a different rendering engine), never blocking the
  ordinary "plan" flow. Its options must come from a live "LOOK ENGINE
  PRESETS" data block, never invented ids — mirrors the `reference_url`
  "use these EXACT values" precedent already in the prompt.
  `plan.spec.style_preset_id` was added to the JSON schema (optional, null
  by default).
- New fail-soft `routes/chat._style_presets_brief(tenant_id)`: reads the
  LIVE `style_presets` table (same data `GET /api/style-presets` serves) and
  formats it as that "LOOK ENGINE PRESETS" block; any DB error or an empty
  table falls back to a frozen one-line default (`neutral_v1`) — never a
  crashed turn, and unlike most `_brief` helpers here it ALWAYS returns a
  non-empty block (an empty block would make the card meaningless even when
  the model wanted to offer it). Wired into BOTH producer entry points —
  `_seed_producer` and `chat_turn`'s main intake turn — alongside the
  existing brief chain (source-locked by test).
- `_handle_approve`'s selections-merge block (where the creator's actual
  card picks override the LLM's own spec) gained one line:
  `if selections.get("look_engine"): spec = {**spec, "style_preset_id":
  selections["look_engine"]}` — mirrors the pre-existing `selections["style"]
  -> spec["visual_style"]` line exactly, same authoritative-over-the-LLM
  treatment.
- `ChatCore.tsx`: `cardKind()` gained one new branch (`card.id ===
  "look_engine"` → `"look_engine"`) — C21a built this lookup specifically so
  a new card kind is a one-line addition, confirmed here. `SelectorCards`
  renders it by reusing `StylePresetGallery` (the SAME component + the SAME
  `["style-presets"]` React Query key as the New Video gallery, C21a) inline
  alongside whatever other cards are showing (e.g. "style" + "look_engine"
  + "length" can all appear together) — NOT a new top-level flow, matching
  the brief's "extend the existing LOOK card rather than inventing a new
  flow" fallback instruction, applied as "extend the existing card-rendering
  machinery" since a literal single-card merge would have conflated the two
  axes' distinct option shapes.
- `ProductionPlanCard`'s "Look" summary line had its own THIRD hardcoded
  copy of the six ids/labels (`PRESET_LABELS`, found while tracing, not
  mentioned in the original checklist entry) — replaced with a
  `styleDescriptionById(styleDescriptions, ...)` lookup against the same
  server-sourced list, closing a duplicate the audit hadn't caught.

**Frontend deletion + re-pointing (`visual-presets.ts` had exactly 2 readers
per §C21a's own accounting — both re-pointed, no others found):**
- New `frontend/src/hooks/use-style-descriptions.ts` — `useStyleDescriptions()`
  mirrors `use-style-presets.ts`'s `useStylePresets()` exactly (same
  `staleTime`, same "long-lived code-derived catalog" reasoning), backed by
  new `getStyleDescriptions()`/`StyleDescription` type in `lib/api.ts`. Icon
  path (`/style-icons/<id>.png`) is kept as a pure frontend filename
  convention (`styleDescriptionIcon(id)`), not server data — unchanged from
  before, just derived instead of stored on the deleted type.
  **Skew-fallback** (network failure only, NOT a maintained duplicate):
  `STYLE_DESCRIPTIONS_FALLBACK`, a frozen 6-entry array, explicitly commented
  as the "offline safety net" — mirrors `ScenesWorkspaceTab.tsx`'s
  `FALLBACK_WIRED_MODELS` precedent exactly. Returned only when
  `query.isError` (an old backend 404ing the new endpoint, or a genuine
  network failure) — a merely-loading or genuinely-empty state renders `[]`
  the same way `useStylePresets`'s consumers already do.
- `app/pipeline/page.tsx`'s pre-existing 6-item "Style description" grid
  (renamed from "Visual style" in C21a) now maps over `styleDescriptions`
  from the hook instead of the deleted `VISUAL_PRESETS` const; `PresetPreviewImage`
  takes a `StyleDescription` instead of the deleted `VisualPreset` type.
- `ChatCore.tsx`'s "style" card options + `ProductionPlanCard`'s label lookup
  both re-pointed the same way (`styleDescriptionById` against the shared
  hook's data, called once in `ChatCore` and threaded down as a prop to both
  `SelectorCards` and `ProductionPlanCard`).

### New Files
| Path | Purpose |
|------|---------|
| `storyengine/backend/routes/style_descriptions.py` | `GET /api/style-descriptions` — thin view over `channel_format.STYLE_DESCRIPTIONS` |
| `storyengine/backend/tests/functional/test_c21b_style_axis_split.py` | 22 tests: dict/endpoint shape, live-read proof for the vision classifier + label lookup, `_spec_to_create_request` axis independence, `_style_presets_brief` fail-soft, `_handle_approve`/entry-point source-locks, grep-proofs |
| `storyengine/frontend/src/hooks/use-style-descriptions.ts` | Shared `useStyleDescriptions()` + skew-fallback array + `styleDescriptionIcon`/`styleDescriptionById` helpers |

### Modified
| Path | Change |
|------|--------|
| `storyengine/backend/channel_format.py` | New `STYLE_DESCRIPTIONS` dict — the one canonical source, replacing `producer_prompt.VISUAL_PRESETS` |
| `storyengine/backend/producer_prompt.py` | `VISUAL_PRESETS` deleted; new "LOOK ENGINE" CARD GUIDANCE bullet + `spec.style_preset_id` in the JSON schema |
| `storyengine/backend/routes/chat.py` | `_spec_to_create_request` sources axis-B from `channel_format.STYLE_DESCRIPTIONS` + adds `style_preset_id` passthrough; `_detect_reference_style_preset`/`_annotate_style_recommendation` re-sourced + honestly re-documented; `_handle_approve` merges `selections["look_engine"]`; new `_style_presets_brief` wired into both producer entry points |
| `storyengine/backend/routes/projects.py` | `_channel_style_dna` re-sourced from `channel_format.STYLE_DESCRIPTIONS` |
| `storyengine/backend/main.py` | Registers `style_descriptions.router` |
| `storyengine/frontend/src/lib/api.ts` | New `StyleDescription`/`StyleDescriptionsResponse` types + `getStyleDescriptions()` |
| `storyengine/frontend/src/app/pipeline/page.tsx` | "Style description" grid + `handleCreate`'s preset lookup re-sourced from `useStyleDescriptions()` |
| `storyengine/frontend/src/components/chat/ChatCore.tsx` | `cardKind()`/`CardKind` gain `"look_engine"`; `SelectorCards` renders it via `StylePresetGallery`; "style" card options + `ProductionPlanCard`'s label lookup re-sourced; both threaded the shared hook's data down as a prop |

### Deleted
| Path | Why |
|------|-----|
| `storyengine/frontend/src/lib/visual-presets.ts` | Hardcoded duplicate of `channel_format.STYLE_DESCRIPTIONS`; both its 2 readers (`ChatCore.tsx`, `pipeline/page.tsx`) re-pointed to the server-sourced hook |
| `storyengine/backend/producer_prompt.VISUAL_PRESETS` (dict, not the file) | Hardcoded duplicate of the same vocabulary; all 4 readers re-pointed to `channel_format.STYLE_DESCRIPTIONS` |

**Deploy-safety assessment:** ff-merge candidate. No schema/migration this
chunk (the style-description axis was never DB-backed and still isn't — a
static Python dict served over a thin GET route, same posture as `/api/
models`). **Skew both directions:**
- **Old frontend + new backend:** the old frontend never calls `GET
  /api/style-descriptions` (doesn't know it exists) and never sends
  `style_preset_id` from chat (doesn't have the `"look_engine"` card) —
  behaves byte-identically to pre-C21b. The renamed backend imports
  (`channel_format.STYLE_DESCRIPTIONS` instead of `producer_prompt.
  VISUAL_PRESETS`) are pure internal refactors with identical externally
  observable behavior (pinned by the live-read monkeypatch tests) — an old
  frontend sees no difference at all.
- **New frontend + old backend:** `useStyleDescriptions()` 404s against an
  old backend lacking the new route → falls back to
  `STYLE_DESCRIPTIONS_FALLBACK` (all 6 ids/labels/looks, frozen) — both
  frontend doors keep rendering the full picker, not a blank gap. The chat
  "look_engine" card can never be emitted by an OLD backend (the card kind
  and the `_style_presets_brief` prompt text don't exist there), so a new
  frontend's `cardKind()`/`StylePresetGallery` addition for that card kind
  simply never triggers — dead code path, not a broken one.
- Every new/changed field is additive and optional (`style_preset_id` on
  chat's spec, the new card kind, the new endpoint) — no existing conversation
  or video-creation path changes behavior when it doesn't opt in.

**Verify:** Backend — 22 new tests in `test_c21b_style_axis_split.py`
(dict/endpoint shape; `_detect_reference_style_preset`/`_annotate_style_
recommendation` PROVEN to read `channel_format.STYLE_DESCRIPTIONS` live via
monkeypatching it to a distinctive non-standard id and confirming the
classifier picks it up — a regression that re-hardcoded the six ids inline
would silently fail this exact test; `_spec_to_create_request`'s axis-B
mapping pinned unchanged + the new `style_preset_id` passthrough + both-axes-
together + blank-string-is-None; `_handle_approve`'s selections-merge
source-locked; `_style_presets_brief`'s real-rows/DB-error/empty-table paths;
both producer entry points' source-locked to actually call the new brief
function; `_channel_style_dna`'s source re-checked; two grep-proofs — zero
real `VISUAL_PRESETS` code references anywhere in the backend tree (a regex
scan distinguishing real usage from historical comments) and zero remaining
imports of the deleted `@/lib/visual-presets` module anywhere in the
frontend tree). Confirmed non-vacuous via `git stash` (tracked-file revert,
untracked new files removed): the whole test module fails to even COLLECT
against the pre-C21b source (`ImportError: cannot import name
'STYLE_DESCRIPTIONS' from 'channel_format'`). `python -m py_compile` clean
on all 5 touched/added `.py` files. Full backend suite: 1051 passed
(1029 baseline + 22 new) / 16 pre-existing failures / 1 pre-existing error —
zero new failures, and the exact 16 failing test names were diffed byte-for-
byte against the same suite run on the stashed pre-C21b source (identical
set, confirming none of the 16 are attributable to this chunk).
Frontend — `npx tsc --noEmit` clean; `npm run build` compiles + typechecks
clean (`Compiled successfully`, `Finished TypeScript`; fails only at the
same pre-existing `NEXT_PUBLIC_API_URL` prerender gap every prior frontend
chunk hits). Grep-proofs: zero `.id === "` comparisons in `ChatCore.tsx`
outside `cardKind()`/`isSliderCard`; zero remaining code readers of
`visualPresetById`/`VisualPreset`/`visual-presets` anywhere in `frontend/src`
(only historical comments remain). No live chat round-trip this session (no
paid Anthropic/Kie key in the sandbox) — extended checklist in
`tasks/live-verification-queue.md` §C21b (both-axes-through-chat, the new
card's rarity/optionality, the vision classifier's unaffected behavior, and
the DB-error fail-soft path).

---

## C19b — S9-6 dead-code delete (added 2026-07-19)

**What:** Deleted 13 confirmed-dead frontend files (4,017 lines total) flagged by the S9 sweep
(`docs/reports/2026-07-17-storyengine-agent-audit-findings.md` §S9-6). Every deletion was
re-verified fresh with `grep -rn` for both the import path and the bare component/JSX name across
all of `storyengine/frontend/src` (not just trusted from the prior audit, since code had moved
since C19a/C21a/C21b touched adjacent files) — zero importers found for any of them.

**Deleted — `components/video-detail/`** (10 of 12 files; the other 2 gained a 3rd live sibling
since the sweep — see below):
| File | Lines |
|------|-------|
| `info-tab.tsx` | 348 |
| `panel-magnifier.tsx` | 28 |
| `performance-tab.tsx` | 182 |
| `pipeline-action-bar.tsx` | 114 |
| `scene-editor.tsx` | 158 |
| `script-tab.tsx` | 149 |
| `segment-list.tsx` | 113 |
| `stage-advancer.tsx` | 227 |
| `storyboard-viewer.tsx` | 514 |
| `thumbnail-tab.tsx` | 195 |

**Kept in `video-detail/` (3, not 2 — re-verified live):** `cost-ledger-chip.tsx` (imported by
`app/pipeline/[videoId]/page.tsx`), `prompt-expander.tsx` and `voice-player.tsx` (both imported by
`components/production/ScenesWorkspaceTab.tsx`; `prompt-expander.tsx` also by `StoryboardTab.tsx`
before it was deleted — its only other importer is the still-live ScenesWorkspaceTab, so it stays).

**Deleted — `components/production/`:**
| File | Lines | Why |
|------|-------|-----|
| `ScriptTab.tsx` | 1,114 | Superseded by `ScriptVoiceTab.tsx`; frozen field-name bug; zero importers |
| `StoryboardTab.tsx` | 350 | Zero importers (confirmed fresh, not just re-trusting C19a's note) |
| `VoiceReviewTab.tsx` | 525 | Zero importers |

**Kept — `app/pipeline/[videoId]/storyboards/page.tsx` (348 lines): FLAGGED, NOT deleted.**
The audit called this route orphaned (no in-app `Link`/`router.push` targets it — confirmed by
grepping every `` `/pipeline/${...}` `` navigation site in the tree; all target the base
`/pipeline/${id}` page, none append `/storyboards`). But it is NOT undocumented dead weight:
`storyengine/agents/blueprints/frontend.md`'s route catalog (line 40) still lists it as a real,
purposeful page ("Full-page storyboard review — scene grids, panel detail modal, extract all"),
and `docs/reports/WIRING_STATUS.md` (lines 45, 174) marks it WIRED with real backend actions
(Approve→`advanceVideo`, Regenerate, Extract All). The chunk spec's own instruction was explicit:
"if the operating docs reference it, flag instead of delete." Both do. Left in place pending a
follow-up that either (a) confirms the blueprint/WIRING_STATUS entries are stale documentation of
an already-consolidated route and deletes file + doc entries together, or (b) re-links it from the
video-detail page's Storyboard tab if it's meant to stay reachable. Not this chunk's call to make
unilaterally — no code changes needed either way, so leaving it doesn't block anything.

**Verify:** `npx tsc --noEmit` clean. `npm run build` — compiles + typechecks clean with
`NEXT_PUBLIC_API_URL` set (`Compiled successfully`, `Finished TypeScript`, all 32 routes including
`/pipeline/[videoId]/storyboards` build); without the env var it fails only at the same
pre-existing prerender gap every prior frontend chunk hits (`NEXT_PUBLIC_API_URL is required in
production builds` — unrelated to this change). No backend files touched — backend test suite not
re-run for this chunk.

**Deploy-safety assessment:** ff-merge candidate. Pure deletion of code with zero live importers,
proven by fresh grep at delete-time, not by trusting a two-day-old audit. No behavior change for
any reachable path. The one file NOT deleted (`storyboards/page.tsx`) is left exactly as it was —
no risk either way.

## C22 — Conversational Style Creation: "make me a new style…" (added 2026-07-19)

**Checklist §2.1 [U] / P2.1c (UX map §3):** the gallery C21a/C21b built only ever surfaces the
FIXED catalogs (5 `style_presets` engine rows, 6 `channel_format.STYLE_DESCRIPTIONS` looks) — a
creator could never add their OWN. This chunk gives the producer chat a conversational door onto
the one axis actually meant to be user-extensible.

**Scope decision (made explicit, per the brief):** a chat-created "style" is a tenant-owned STYLE
DESCRIPTION — a new row in the EXISTING `visual_styles` CRUD table (migration 010, the profile
page's "Visual Styles" manager, `["visualStyles"]` query; C20's axis-2 in its "three axes" note
above) — NOT a new `style_presets` row. `style_presets` rows are Python rendering ENGINES
(`shared.profiles.visual.*`, each with its own scene-type/camera/composition logic); a creator's
words can describe a LOOK, never author a new engine. The `visual_styles` CRUD was already exactly
fit for purpose — free-text `style_profile` JSON (`{"prompt_prefix": "<look sentence>"}`, rendered
by `identity._style_profile_to_look`), a name, activate/deactivate, cascade-deleting characters —
so this chunk adds a conversational front door onto it, reusing its EXACT route handlers. No
fourth style system (that would be S9-5's whole complaint, repeated a third time).

**The confirm-before-save guarantee — the actual hard part.** Every existing `profile_ops` verb
(`add_competitor`, `set_niche`, `remember`, …) executes the instant the producer emits it; the ONE
exception (`remove_competitor`) gets its "are you sure" purely in NL, trusting the model to re-emit
the op on the creator's next "yes". That pattern is not good enough for money-adjacent-feeling,
identity-adjacent data like a saved style — the brief explicitly wants "no row until the creator
confirms," provable in a test, not a hope. So this chunk borrows a DIFFERENT existing pattern
instead: `_handle_copilot`'s `pending_action`/`confirm_action` two-turn state machine (stash a
draft in conversation `state`, require the creator's own next-turn tap to actually run it) — but
built fresh for the HOME producer path, since `_handle_copilot`'s version is video-scoped and
`chat_turn` (the home path) had no prior "propose now, execute next turn, deterministically" shape
of its own.

1. **Turn 1 — draft (LLM-driven, DB-inert).** New `profile_ops` verb `draft_style`
   (`producer_prompt.py`, taught alongside `remember`/`use_style` with the same "wired up" framing
   the rest of the vocabulary uses): `{"op":"draft_style","value":{"name":"<short name>","look":"<one
   sentence>"}}`. Its handler in `routes/chat.py::_apply_profile_ops` does **exactly one thing**:
   `state["pending_style_draft"] = {"name": ..., "look": ...}` and a confirmation line. It NEVER
   calls `fetch_one`/`execute`/`create_visual_style` — proven directly in
   `tests/functional/test_c22_style_draft.py::test_draft_style_stashes_pending_draft_and_touches_no_database`,
   which leaves `database.fetch_one/fetch_all/execute` bound to the test module's `_boom` stubs (any
   write attempt would raise `AssertionError` and fail the test).
2. **The preview card.** New `chat._style_draft_card(draft)` builds `{"id":"style_draft", "label":
   <name>, "body": <look>, "options":[yes/no]}` — reusing the `label`/`body`/`options` fields
   `ChatCard` already has (no new frontend-facing field needed; `body` is the same field
   `prompt_apply` already carries a draft in). New `chat._maybe_attach_style_draft_card(data, state)`
   attaches it to `data["cards"]` ONLY when THIS turn's `profile_ops` (or the known alt-key spellings
   `queue_ops`/`file_ops`/`asset_ops`, mirroring `_apply_and_merge_profile_ops`'s own tolerance)
   actually included `draft_style` AND `state["pending_style_draft"]` is non-empty — so the LLM's own
   prose can never manufacture a save-ready card without a real draft having been stashed first.
   Called from both producer entry points (`chat_turn`'s intake turn and `_seed_producer`'s
   onboarding-seed turn), right after `_apply_and_merge_profile_ops`.
3. **Turn 2 — confirm (deterministic, LLM never consulted).** New `chat_turn` step 3.6, positioned
   BEFORE the normal intake turn (which would otherwise just hand `selections.style_draft` to the
   LLM as text) and BEFORE the 3.5 identity-command check:
   ```python
   if body.selections and "style_draft" in body.selections and state.get("pending_style_draft"):
       return await _handle_style_draft_confirm(body.selections, conversation_id, tenant_id, transcript, state)
   ```
   `_handle_style_draft_confirm` pops `state["pending_style_draft"]` (cleared either way — no stale
   re-confirm on an unrelated later "yes"); on `selections.style_draft == "yes"` it calls
   `routes.visual_styles.create_visual_style(CreateStyleRequest(name=draft["name"],
   style_profile={"prompt_prefix": draft["look"]}), tenant_id=tenant_id)` **directly** — the SAME
   function `POST /api/visual-styles` (the profile page's create button) calls, invoked the same way
   `_handle_approve` calls `create_video` directly (bypassing the ASGI/`Depends` machinery, not
   forking the route's logic). Any other value, or no pending draft at all, is a friendly no-op with
   zero DB calls — proven by monkeypatching `create_visual_style` to an `AssertionError`-raising stub
   in the "no" test. A CRUD failure (e.g. a DB error) fails soft to a friendly line, never a crashed
   turn.
4. **"Use <name>" — resolves via the CRUD's own activate semantics.** New `use_style` op: looks up
   the tenant's `visual_styles` row by exact name (case-insensitive) with an `ILIKE '%...%'` fallback,
   then calls `routes.visual_styles.activate_visual_style(style_id, tenant_id=tenant_id)` — the SAME
   function the profile page's "Set active" control calls. This is a CHANNEL-WIDE switch (mirrors
   `identity.build_identity_context`'s existing precedence: `video.image_style_override` (per-video) >
   the ACTIVE `visual_styles` row (channel-wide) > `channel_profiles.style_description`) — distinct
   from `set_visual_style` (which overwrites the single free-text default, not a saved reusable row).
   A saved style can ALSO be resolved for just the video being planned right now, without switching
   the channel default: new `_visual_styles_brief(tenant_id)` (fail-soft, empty-when-nothing-saved,
   unlike `_style_presets_brief`'s frozen fallback — an empty section is correct here) lists the
   tenant's saved styles by name + look, wired into both producer entry points; the prompt instructs
   the producer to set `spec.image_style_override`/`visual_style_label` straight from a matching saved
   entry when the creator names it for "this one," reusing fields `_spec_to_create_request` already
   wires end-to-end (no new plumbing needed there).
5. **Docked (in-video) co-pilot / `agent_brain.py` — deliberately NOT touched.** Every existing
   channel-config verb (`add_competitor`, `set_niche`, `set_channel_format`, …) lives ONLY in the home
   producer's `profile_ops`, never in the docked co-pilot's `kind` classifier or `agent_brain.py`'s
   tool-loop schema — channel-level configuration has never been a docked-copilot concern, and a
   saved style is exactly that (project-scoped, not video-scoped). Extending the docked schema too
   would be new surface with no existing precedent asking for it and no path in `identity.py` to
   change an EXISTING video's style after creation anyway (that's the UX map's separate, unbuilt
   "video header chip, locked once images exist" clickable-door feature) — adding it here would be
   scope creep, not "as appropriate." Flagged explicitly rather than silently skipped.
6. **Frontend.** New `CardKind` entry `"style_draft"` in `ChatCore.tsx`'s `cardKind()` lookup (C21a's
   refactor point — one more entry, no new string-match branch) and in `ACTION_CARD_KINDS`. New
   `StyleDraftCard` component (text-only preview + Save/Not-quite buttons, same shape as
   `ConfirmActionCard`) — deliberately NO image preview (the cost-cap constraint: an image preview
   here would be paid generation with no quote gate). On "yes," `queryClient.invalidateQueries({
   queryKey: ["visualStyles"] })` fires from `ChatCore.tsx` — the home chat and `/profile` are
   different route trees but share ONE `QueryClient` (`app/providers.tsx` wraps the whole app), so
   this reaches the Profile page's query directly instead of relying on its 30s default `staleTime`
   window to eventually notice the new row.

### New Files
| Path | Purpose |
|------|---------|
| `storyengine/backend/tests/functional/test_c22_style_draft.py` | 23 tests across all 7 layers above |

### Modified
| Path | Change |
|------|--------|
| `storyengine/backend/producer_prompt.py` | `draft_style`/`use_style` vocabulary taught in prose + the JSON schema's `profile_ops` example list |
| `storyengine/backend/routes/chat.py` | `_apply_profile_ops` gains `draft_style`/`use_style` branches; new `_visual_styles_brief`, `_style_draft_card`, `_maybe_attach_style_draft_card`, `_handle_style_draft_confirm`; `chat_turn` step 3.6 intercept; `_visual_styles_brief`/`_maybe_attach_style_draft_card` wired into both `chat_turn` and `_seed_producer` |
| `storyengine/frontend/src/components/chat/ChatCore.tsx` | New `"style_draft"` `CardKind` + `ACTION_CARD_RENDERERS` entry + `StyleDraftCard` component; `useQueryClient` import + `["visualStyles"]` invalidation on save |

**Deploy-safety assessment:** ff-merge candidate. Purely additive: two new `profile_ops` verbs (an
unrecognized op was already silently ignored by `_apply_profile_ops`'s `if kind == ...` chain before
this chunk, so older transcripts/replays are unaffected); one new `ChatCard` id or an older frontend
build simply never renders (falls through `cardKind()`'s `generic` case, same as any card kind added
before it); no existing route, migration, or Pydantic field changed or removed; the CRUD write path
(`routes/visual_styles.py`) is untouched, only called from a new call site. `ScenesWorkspaceTab.tsx`
NOT touched this chunk (no S9-7 trust-ladder extraction needed) — that lands with C23, which does
touch that file.

**Verify:** `cd storyengine/backend && ./venv/bin/python -m pytest
tests/functional/test_c22_style_draft.py -q` — 23 passed. Non-vacuous: `git stash` (the three
modified tracked files only; the new test file kept in place) — all 23 fail against pre-C22 source
(`AttributeError: module 'routes.chat' has no attribute '_visual_styles_brief'` etc.); `git stash
pop` restored clean, re-verified green. `python -m py_compile` clean on all touched/added `.py`
files. Full backend suite: **1074 passed (1051 baseline + 23 new) / 16 pre-existing failures / 1
pre-existing error** — the failing/erroring test name list is BYTE-IDENTICAL to a full stashed-baseline
rerun (`diff` on sorted `FAILED`/`ERROR` lines from both runs: zero output), not just an eyeballed
count match. Frontend: `npx tsc --noEmit` clean; `npm run build` compiles+typechecks clean (same
pre-existing `NEXT_PUBLIC_API_URL` prerender gap every prior frontend chunk hits, unset in this
sandbox). Grep-proof: `card.id === "` matches in `ChatCore.tsx` exist only inside `cardKind()` (plus
the pre-existing `isSliderCard` helper) — zero new scattered string-match sites. Live conversational
round-trip (draft → confirm → row appears in Profile → "use it" on a new video) deferred to
`tasks/live-verification-queue.md` §C22 — needs a live DB + a real Anthropic/Kie key to actually
drive the producer LLM.

## C23 — Camera-Preset Chips: `/api/camera-presets` + scene chip + sheet (added 2026-07-19)

**Checklist §2.2 / P2.2 (UX map §4):** the 40+-move camera catalog (`image_prompts.engine.
camera_moves.py`) was auto-only — `camera_selector.py`'s "earn the move" system picks a move at
shot-plan time and stamps it onto `assets.camera_movement`, but a creator could never see or
override it. This chunk exposes a curated subset over a new endpoint, a per-shot chip + preset
sheet in the Scenes tab, and a conversational door through the copilot — the same "two doors, one
write path" law every prior UX-map chunk follows.

### C23-prep — S9-7 hook extraction (audit finding, required before touching this file again)

The audit (`docs/reports/2026-07-17-storyengine-agent-audit-findings.md` §S9-7) flagged
`ScenesWorkspaceTab.tsx` at 2399/2403 lines with an explicit constraint: extract the clip
trust-ladder/auto-resume state machine (~L530-1099) to a hook BEFORE C23 lands its chip there.
New `frontend/src/hooks/use-clip-trust-ladder.ts` (172 lines) now owns: `generatingClipIds`/
`failedClipIds`/`confirmKey` state, the `clipResumeRef`/`prevRunningRef` refs, `startClipTask`/
`animateOne`/`animateScene`/`animateAll`/`maybeResumeClips`, the running→idle auto-resume
trigger effect, and `confirmable()`. Deliberately NOT moved: `chainRef`/`generatingScene` (the
storyboard plan→draw auto-chain, a separate concern) and the `onComplete`/`onFailed`/Stop-event
handlers in the component, since those three callbacks serve BOTH the chain and the clip machine
— they now reach into the hook's exposed setters (`setGeneratingClipIds` etc.) and
`cancelResume()` the same way they always reached into local `setState` calls (forward-reference-
by-closure, the same pattern the pre-existing code already used for `markStarted`). `animateAll`'s
signature changed from a zero-arg closure to `(pendingIds: string[])` since it no longer closes
over `clipCards` itself — the one call site (`confirmable("all", remainingCost, () =>
animateAll(clipCards.filter(...)))`) was updated to match. Behavior-preserving: `tsc --noEmit`
clean, `npm run build` compiles+typechecks clean (32/32 routes). **Line count: 2403 → 2321
(-82)**; the removed logic reappears in the new 172-line hook. Commit `ffab537` (`C23-prep: ...`).

### Backend

- **`GET /api/camera-presets`** (new `routes/camera_presets.py`, registered in `main.py`) — reads
  `image_prompts.engine.camera_moves.CAMERA_MOVES` server-side via `get_move()`, same "the Python
  catalog is the source of truth, no hardcoded frontend copy" posture as `/api/models` and
  `/api/style-presets`. Auth: `Depends(get_tenant_id)` only, mirroring `/api/models` exactly (a
  global catalog, not tenant-scoped data). Curated to 12 ids (`CURATED_PRESET_IDS`, hand-picked by
  reading the catalog's own category/`best_for`/pace comments for a spread across every purpose):
  `dolly_in, dolly_out, crash_zoom_in, slow_zoom_in, pan_right, tilt_up_reveal, crane_up_reveal,
  drone_orbit, orbit_right, whip_pan, handheld_follow, static_locked`. Each entry: `id`, `name`,
  `motion_prompt` (the exact contract text fed to clip generation), `best_for` (purpose tags, for
  the sheet's grouping), `category`, and `preview` (the catalog's own `image_setup` text — no real
  preview images exist for camera moves, so this is the closest honest thing to one; `null` for
  `static_locked`, which has no composition contract). `static_locked` is included deliberately —
  it's the "force no movement" pick, distinct from clearing back to Auto (`NULL` — earn-the-move
  decides again).
- **`assets.camera_preset_id`** (migration 097, applied LIVE via the Supabase MCP `execute_sql`
  tool against `wrromlupsmyzrrcqlucn`, confirmed via `information_schema.columns`, `schema.sql`
  updated) — a nullable TEXT column mirroring `model_override` (migration 090) exactly: `NULL` =
  no manual pick, falls through to the auto/"earned" `camera_movement`. Written by **`PATCH
  /api/assets/{asset_id}/camera-preset`** (new endpoint in `routes/assets.py`, same tenant-scoping
  + `get_move()` validation pattern as `update_model_override`) — blank/omitted clears the
  override, an unknown id 400s.
- **The composition seam — `pipeline_executor._apply_camera_preset_override(prompt, camera_
  preset_id)`** (new module-level pure function, no DB/I/O, directly unit-testable). Called from
  `run_clip_generation._one`'s silent/non-dialogue-shot branch, right after the existing
  `video_prompt`-or-default fallback and BEFORE `motion_guard`'s people-rule prefix:
  ```python
  prompt = (r.get("video_prompt") or "").strip() or ("Slow push-in on the main subject. ...")
  prompt = _apply_camera_preset_override(prompt, r.get("camera_preset_id"))
  prompt = motion_guard(r.get("image_prompt"), r.get("sentence_text"), cast_names) + prompt
  ```
  `_apply_camera_preset_override` calls `get_move(camera_preset_id)`; a hit REPLACES `prompt`
  outright with `move.motion_prompt` (guaranteeing the [V] contract — the composed prompt not just
  *contains* but *equals* the preset's contract text before the people-rule prefix is added); a
  miss (NULL/blank/unknown id — every row before C23) returns `prompt` unchanged, byte-identical.
  The dialogue/speaking branch (character-voiced shots) was deliberately left untouched this
  chunk — the camera chip targets narration/b-roll shots, the common case, and speaking-shot
  motion composition is a materially different (audio-timed, lip-sync-adjacent) code path; not
  wired to read `camera_preset_id` yet, flagged as a known gap below.
- **Conversational door — `actions.py`'s new `camera_preset` verb** ("use a crash zoom on scene
  12", "put scene 4's camera back to auto"). `ACTIONS["camera_preset"]` is `paid: False` (no
  confirm card, same as `approve_scene`) with `needs: "pictures"`. New `_runner_camera_preset`
  resolves free text to a catalog id — tries `get_move()` directly first (in case the classifier
  already learned a real id from `GET /api/camera-presets`), then a small alias map
  (`_CAMERA_PRESET_ALIASES`: "crash zoom"→`crash_zoom_in`, "push in"→`dolly_in`, "pull back"→
  `dolly_out`, "pan"→`pan_right`, "tilt up"→`tilt_up_reveal`, "crane up"→`crane_up_reveal`,
  "drone"/"orbit"→`drone_orbit`/`orbit_right`, "whip pan"→`whip_pan`, "handheld"→`handheld_follow`,
  "static"/"no movement"→`static_locked`), or recognizes "auto"/"clear"/"default" as an explicit
  clear — then writes `UPDATE assets SET camera_preset_id=$1 WHERE video_id=$2 AND tenant_id=$3
  AND scene=$4`, the SAME column the clickable chip writes (scene-scoped, not per-shot, since the
  classifier's `pending` dict carries a scene number not a shot index — mirrors how "animate scene
  N" already treats a whole scene as the unit). Registered in `RUNNERS`; the verb was added to
  BOTH classifiers that need to recognize it — `agent_brain.py`'s agentic tool-loop schema (the
  docked in-video copilot) and `routes/chat.py`'s legacy one-shot classifier fallback — same two
  places `approve_scene` lives, per the C15b precedent the task named explicitly. An unrecognized
  move phrase writes nothing and asks the creator to try a different word (never guesses/writes
  garbage into the column).

### Frontend

- **`Asset` type** (`lib/api.ts`) gains `camera_movement`/`camera_preset_id` (both already read by
  `GET /api/videos/{id}/assets`, updated to select them). New `CameraPresetInfo`/
  `CameraPresetsResponse` types, `getCameraPresets()`, `updateAssetCameraPreset(assetId, id |
  null)`.
- **`ScenesWorkspaceTab.tsx`**: new `["camera-presets"]` query (`staleTime` 5 min, same as
  `["models"]`); new `describeCameraMove(asset, presets)` module-level helper — reads
  `camera_preset_id` (manual) first, falls back to parsing `camera_movement` ("move_id|PURPOSE" or
  "static"), else `"Auto"` — fail-safe by construction, every branch returns a label so a shot
  with zero camera data still renders an `"Auto"` chip, never a broken one. New camera-move chip
  in `SegmentCard`'s badge row (next to the existing C14 model badge, same gating on
  `canAnimate`, same purple "manual" dot convention) — tap opens the new `CameraPresetSheet`
  (reuses the exact `ModelOverrideSheet` pattern: `Modal`, active-highlight, a "clear" button),
  which groups the curated presets by `best_for` purpose (Reveal/Scale/Establish/Isolation/
  Payoff, `static_locked`'s empty `best_for` falling into an "Other" group) per UX map §4. Picking
  a preset calls `handleSetCameraPreset` → `updateAssetCameraPreset` → invalidates
  `["video-assets", video.id]`, same invalidation the model-override sheet already uses, so the
  chip updates immediately without a page reload.

### New/Modified Files
| Path | Change |
|------|--------|
| `storyengine/frontend/src/hooks/use-clip-trust-ladder.ts` | NEW — S9-7 extraction (prep commit) |
| `storyengine/backend/migrations/097_asset_camera_preset.sql` | NEW — `assets.camera_preset_id` |
| `storyengine/backend/routes/camera_presets.py` | NEW — `GET /api/camera-presets` |
| `storyengine/backend/tests/functional/test_c23_camera_presets.py` | NEW — 20 tests across all 4 layers |
| `storyengine/backend/routes/assets.py` | New `PATCH /api/assets/{id}/camera-preset` |
| `storyengine/backend/routes/videos.py` | `GET /assets` SELECT gains `camera_movement, camera_preset_id` |
| `storyengine/backend/pipeline_executor.py` | New `_apply_camera_preset_override`; wired into `run_clip_generation._one`'s silent-shot branch |
| `storyengine/backend/actions.py` | New `camera_preset` verb/runner + alias resolver |
| `storyengine/backend/agent_brain.py` | Docked copilot's decision schema + VERB MEANINGS gain `camera_preset` |
| `storyengine/backend/routes/chat.py` | Legacy classifier's schema + verb prose gain `camera_preset` |
| `storyengine/backend/main.py` | `camera_presets.router` registered |
| `storyengine/schema.sql` | `assets.camera_preset_id` documented |
| `storyengine/frontend/src/lib/api.ts` | `Asset.camera_movement`/`.camera_preset_id`; `CameraPresetInfo`; `getCameraPresets`/`updateAssetCameraPreset` |
| `storyengine/frontend/src/components/production/ScenesWorkspaceTab.tsx` | Camera-move chip + `CameraPresetSheet`; `describeCameraMove`/`humanizeCameraId` helpers |

**Known gap, flagged not silently skipped:** the dialogue/speaking-shot clip-composition branch
(character-voiced clips, InfiniteTalk/Grok-speaking paths) does not read `camera_preset_id` yet —
only the silent/narration branch does. A manual camera pick on a speaking shot is currently a
no-op at generation time (the chip still writes the column and the sheet still shows "manual",
but the next animate won't honor it for that shot). Scoped out of this chunk deliberately (camera
moves on lip-synced dialogue shots is a materially different, audio-timing-constrained problem);
next chunk to touch clip composition should close this or the chip needs a shot-type-aware
disabled state.

**Verify:** `cd storyengine/backend && ./venv/bin/python -m pytest
tests/functional/test_c23_camera_presets.py -q` — 20 passed. Non-vacuous: `git stash` (tracked
files only, test file + `routes/camera_presets.py` + migration left in place) — import fails
(`ImportError: cannot import name '_apply_camera_preset_override'`); `git stash pop` restored
clean. `python -m py_compile` clean on every touched/added `.py` file. Full backend suite: **1094
passed (1074 baseline + 20 new) / 16 pre-existing failures / 1 pre-existing error** — the
failing/erroring test name list is BYTE-IDENTICAL to a full stashed-baseline rerun (diffed, zero
output), not just a count match. Frontend: `npx tsc --noEmit` clean; `npm run build`
compiles+typechecks clean (32/32 routes, same pre-existing `NEXT_PUBLIC_API_URL` prerender gap
every prior frontend chunk hits). Live "pick crash zoom → real clip's motion prompt carries it,
end to end through a real animate" deferred to `tasks/live-verification-queue.md` §C23 (no paid
Kie/Anthropic key in this sandbox, and no live DB to drive the actual UI click-through).

**Deploy-safety assessment:** ff-merge candidate, with the known dialogue-branch gap disclosed
above (not a regression — dialogue clips simply don't read the new column yet, exactly like every
other row before this chunk). Skew both directions: an OLD frontend against a NEW backend never
calls the new endpoints, so nothing changes; a NEW frontend against an OLD backend gets a 404 on
`/api/camera-presets` — the query fails soft (`cameraPresets` defaults to `[]`), the chip still
renders (`describeCameraMove` falls back to `camera_movement`/"Auto" without needing the presets
list at all) and the sheet just shows "couldn't load the preset list" instead of crashing. Every
new DB read/write is additive (`camera_preset_id` NULL for every existing row); the one touched
hot path (`run_clip_generation._one`) is proven byte-identical when the column is NULL, which is
every row that existed before this migration ran. The prep commit (hook extraction) was verified
independently as behavior-preserving before any C23 code touched the file.

## C24 — `videos.script_profile` + `GET /api/script-profiles` + `SCRIPT_PROFILE` seam (added 2026-07-19)

**Checklist §2.3 / P2.3:** `shared.profiles.script/*.py` (`neutral_v1` default, `power_doctrine_v2`/
`power_doctrine_v1` opt-in) already existed as a runtime engine, but nothing let a creator pick one
per video — mirrors C20's `VISUAL_PROFILE` seam exactly, same "two doors, one write path" law.

### Backend

- **`videos.script_profile`** (migration 098, applied LIVE via the Supabase MCP `apply_migration`
  tool against `wrromlupsmyzrrcqlucn`, confirmed via `information_schema.columns`, `schema.sql`
  updated) — a nullable TEXT column, **no FK** (unlike `style_preset_id`/migration 096): the
  catalog is a small code-reviewed Python registry (`list_profiles()`, 3 rows), not admin-mutable
  table data — same "no new DB table" rationale `camera_preset_id`/migration 097 already used for
  `camera_moves.py`. `NULL` = no explicit pick (every pre-C24 video).
- **`GET /api/script-profiles`** (new `routes/script_profiles.py`, registered in `main.py`) — reads
  `shared.profiles.script.list_profiles()` + `load_script_profile(id)` server-side, same "the
  Python catalog is the source of truth" posture as `/api/camera-presets`/`/api/style-presets`.
  Returns `id`/`display_name`/`description`/`best_for`/`is_default`, copy pulled verbatim from each
  profile's own `template_metadata` (nothing hand-written) — `neutral_v1` sorts first
  (`is_default=true`), then `power_doctrine_v2`/`power_doctrine_v1` in registration order. Auth:
  `Depends(get_tenant_id)` only, mirroring `/api/camera-presets` (a global catalog).
- **`orchestrator.pipeline_constants.IdeaFields.SCRIPT_PROFILE = "Script Profile"`** — the exact
  Airtable field name `shared/profiles/script/README.md`'s "Profile Selection Order" already
  documented ("1. Airtable field: `Script Profile`"), so this closes a doc/code gap that predated
  C24. Added to `supabase_adapter.IDEA_FIELD_MAP` (`"Script Profile": "script_profile"`) — since
  `_row_to_idea`/`_get_video`/`get_idea` all `SELECT *`, the new column flows into the Airtable-
  shaped idea dict automatically, no other adapter change needed (C16b lesson: fail-soft `.get()`,
  confirmed via `test_missing_field_entirely_also_falls_back`).
- **The executor seam — `pipeline_executor._resolve_script_profile_id(idea)`** (new module-level
  function, mirrors `_resolve_visual_profile_id` byte-for-byte in shape): `(idea.get(IdeaFields.
  SCRIPT_PROFILE) or "").strip() or "neutral_v1"`. Wired into `_load_idea` right next to the
  `VISUAL_PROFILE` line:
  ```python
  os.environ["SCRIPT_PROFILE"] = _resolve_script_profile_id(idea)
  ```
  Set **unconditionally** (not only when a per-video pick exists) — same stash-proofing rationale
  as `VISUAL_STYLE_DESCRIPTION`'s own comment ("a previous tenant's value can never leak in"). The
  consumer: `script/brief_translator/__init__.py`'s `self.profile = load_script_profile()` (called
  with NO args — env-var-or-default is the only precedence that function call exercises), which
  itself resolves `os.getenv("SCRIPT_PROFILE", "").strip() or DEFAULT_PROFILE_ID` where
  `DEFAULT_PROFILE_ID = "neutral_v1"` — confirmed by reading `shared/profiles/script/__init__.py`.
  Byte-identical contract: `_resolve_script_profile_id({})` → `"neutral_v1"` →
  `os.environ["SCRIPT_PROFILE"] = "neutral_v1"` → `load_script_profile()`'s own env lookup returns
  the SAME neutral profile it would have without C24 touching anything (its unset-env fallback is
  also `"neutral_v1"`). Power Doctrine is never the fallback anywhere in this seam — opt-in only,
  per `storyengine/CLAUDE.md`'s "Power Doctrine as a default identity... deleted on purpose, don't
  resurrect" rule.
- **Write-time validation — `routes/videos.py`'s new `_resolve_script_profile(script_profile)`**
  (sync, no DB round-trip needed — checks `shared.profiles.script.list_profiles()` in-process,
  unlike `_resolve_style_preset_id`'s async DB query): blank/`None` → `None` (silent no-op, the
  common case); a real registered id passes through unchanged; an unknown id raises 400. Called
  from BOTH write paths:
  - `create_video`'s INSERT gains `script_profile` (19th → 20th column/param).
  - `update_video`'s generic PATCH `allowed_fields` gains `"script_profile"`, re-validated inline
    before the dynamic `SET` loop — this is the "existing video-update path" the ScriptVoiceTab
    door writes through, so both doors share ONE validation + ONE column.
  `get_video`'s `SELECT`/`VideoDetail` response also gained `script_profile` (read path).
- **Conversational door — `actions.py`'s new `script_profile` verb** ("write it in the
  investigative style", "put the script voice back to neutral"). `ACTIONS["script_profile"]` is
  `paid: False, needs: None` (settable before or after a script exists — no confirm card, same as
  `camera_preset`/`approve_scene`). New `_resolve_script_profile_text(text)` tries a real registry
  id directly first, then a small alias map (`_SCRIPT_PROFILE_ALIASES`: "investigative"/
  "investigative reveal"/"power doctrine"/"follow the money"/"incentive chain"/"analyst" →
  `power_doctrine_v2`; "framework explainer"/"framework"/"documentary"/"teaching" →
  `power_doctrine_v1`), or recognizes an exact clear-word ("auto"/"automatic"/"clear"/"default"/
  "neutral"/"neutral_v1"/"normal") as `None` — **never** as a route to Power Doctrine (pinned by
  `test_power_doctrine_never_reachable_via_clear_words`). New `_runner_script_profile` writes
  `UPDATE videos SET script_profile=$1 WHERE id=$2 AND tenant_id=$3`, the SAME column both other
  doors write. Registered in `RUNNERS`; the verb was added to BOTH classifiers — `agent_brain.py`'s
  agentic tool-loop schema + VERB MEANINGS prose, and `routes/chat.py`'s legacy one-shot
  classifier's ACTIONS list + prose + JSON schema — same two places `camera_preset` lives (C23
  precedent). An unrecognized voice phrase writes nothing and asks the creator to try a different
  word.

### Frontend

- **`lib/api.ts`**: new `ScriptProfile`/`ScriptProfilesResponse` types + `getScriptProfiles()`;
  `createVideo()`'s data type gains `script_profile?: string`.
- **New `hooks/use-script-profiles.ts`** — one shared `["script-profiles"]` query (5 min
  `staleTime`, mirrors `use-style-presets.ts`), used by both write doors below.
- **New Video "Advanced options"** (`pipeline/page.tsx`): a native `<select id="new-script-
  profile">` (label via `htmlFor`, explicit `background`/`color` for Windows dark-mode contrast per
  the web-interface-guidelines pass) — "Neutral (default)" plus every non-default registered
  profile, with the selected profile's own `description` shown below it (falls back to the default
  profile's description when nothing is picked — never invented copy). New `newScriptProfile` state,
  reset alongside the other "new*" fields on both `createMutation.onSuccess` and the modal's
  `onClose`; wired into `handleCreate`'s `createMutation.mutate({ ..., script_profile:
  newScriptProfile || undefined })`.
- **`ScriptVoiceTab.tsx`**: new `ScriptVoiceCard` component (placed right after the tab's "Script
  N/M · Voice N/M" top action bar, before the Script System Prompt editor) — a `GlassCard` with a
  labeled native `<select>` (current value = `video.script_profile || ""`), disabled while saving,
  writing through `updateVideo(video.id, { script_profile })` → invalidates `["video", video.id]`
  (the same key every other in-tab field mutation already uses). Explicitly documented in-file as a
  DIFFERENT axis from the pre-existing `CustomVoiceCard` just above it (that's the ElevenLabs AUDIO
  voice; this is the shared.profiles.script WRITING voice) to head off the obvious naming
  confusion.

### New/Modified Files
| Path | Change |
|------|--------|
| `storyengine/backend/migrations/098_video_script_profile.sql` | NEW — `videos.script_profile` |
| `storyengine/backend/routes/script_profiles.py` | NEW — `GET /api/script-profiles` |
| `storyengine/backend/tests/functional/test_c24_script_profiles.py` | NEW — 19 tests across all 5 layers |
| `storyengine/frontend/src/hooks/use-script-profiles.ts` | NEW — shared `["script-profiles"]` query |
| `storyengine/backend/routes/videos.py` | New `_resolve_script_profile`; `script_profile` in create_video INSERT, get_video SELECT/response, update_video allowed_fields |
| `storyengine/backend/models.py` | `CreateVideoRequest.script_profile`, `VideoDetail.script_profile` |
| `storyengine/backend/pipeline_executor.py` | New `_resolve_script_profile_id(idea)`; wired into `_load_idea` next to `VISUAL_PROFILE` |
| `storyengine/backend/supabase_adapter.py` | `IDEA_FIELD_MAP["Script Profile"] = "script_profile"` |
| `skills/video-pipeline/orchestrator/pipeline_constants.py` | `IdeaFields.SCRIPT_PROFILE = "Script Profile"` |
| `storyengine/backend/actions.py` | New `script_profile` verb/runner + alias resolver |
| `storyengine/backend/agent_brain.py` | Docked copilot's decision schema + VERB MEANINGS gain `script_profile` |
| `storyengine/backend/routes/chat.py` | Legacy classifier's schema + ACTIONS list + prose gain `script_profile` |
| `storyengine/backend/main.py` | `script_profiles.router` registered |
| `storyengine/schema.sql` | `videos.script_profile` documented |
| `storyengine/frontend/src/lib/api.ts` | `ScriptProfile`/`ScriptProfilesResponse` types; `getScriptProfiles`; `createVideo`'s `script_profile` field |
| `storyengine/frontend/src/app/pipeline/page.tsx` | New Video "Advanced" script-voice select + state |
| `storyengine/frontend/src/components/production/ScriptVoiceTab.tsx` | New `ScriptVoiceCard` |

**Verify:** `cd storyengine/backend && ./venv/bin/python -m pytest
tests/functional/test_c24_script_profiles.py -q` — 19 passed. `python -m py_compile` clean on every
touched/added `.py` file. Full backend suite: **1113 passed (1094 baseline + 19 new) / 16
pre-existing failures / 1 pre-existing error** — the failing/erroring test name list is
BYTE-IDENTICAL to the pre-change baseline run (diffed, zero output). Frontend: `npx tsc --noEmit`
clean; `npm run build` compiles+typechecks clean (32/32 routes, same pre-existing
`NEXT_PUBLIC_API_URL` prerender gap every prior frontend chunk hits — confirmed cosmetic by
re-running with a dummy value set, which completes 32/32). Also spot-checked
`skills/video-pipeline/tests/test_pipeline_integration.py`: 2 pre-existing failures (image-prompt
marker assertions, unrelated to script profiles — confirmed via `git stash` on the one touched
pipeline-package file, `pipeline_constants.py`, same 2 failures reproduce with it stashed out).

Checklist §2.3 left UNCHECKED on purpose: `[D]`/`[B]`/`[U]` are all built and unit-verified, but
the full `[V]` ("generate the same topic under both profiles; scripts differ per profile laws") is
a paid live check (Claude script-generation calls), deferred to
`tasks/live-verification-queue.md` §C24 with an exact recipe. Per this chunk's own instructions,
only tick the checklist once that live check actually passes.

**Deploy-safety assessment:** ff-merge candidate. Additive-only: `script_profile` is NULL for
every existing row (no backfill needed), the executor seam is proven byte-identical on NULL/blank,
and both write doors reject unknown ids rather than silently storing garbage. Skew both directions:
an OLD frontend against a NEW backend never sends `script_profile`, so `create_video`/`update_video`
behave exactly as before; a NEW frontend against an OLD backend gets a 404 on
`/api/script-profiles` — the New Video select's data is `undefined` → `scriptProfiles` defaults to
`[]` → the select still renders with just "Neutral (default)" (fail-soft, not a crash), and
`ScriptVoiceCard` degrades the same way. No known gaps analogous to C23's dialogue-branch caveat —
script profiles only affect `brief_translator`'s prompt assembly (a text-generation seam, not a
per-shot composition path), so there's no partial-coverage branch to disclose.

## C25a — S5-1 BLOCKER fix: media proxy tenant auth (added 2026-07-19)

**Checklist §S5-1 (audit `tasks/docs/reports/2026-07-17-storyengine-agent-audit-findings.md`):**
`routes/media.py::serve_drive_file` had NO auth dependency, and its `_is_allowed()` file-id
allowlist checked `assets`/`scripts`/`videos`/`video_characters`/`chat_assets`/`projects` ACROSS
THE WHOLE DATABASE with no tenant clause — a leaked/guessed 33-44 char Drive id served ANY
tenant's file to ANYONE. This closes it.

### Mechanism chosen (traced first, per the checklist's own warning not to break every image)

Traced how media URLs actually authenticate today before picking a fix: `<img>`/`<video>` tags
can't send an `Authorization` header, and the app's frontend (3001) and backend (8001) are
different origins in prod, so cookies don't help either. But `auth.verify_token` **already**
accepts a JWT via `?token=` for SSE ("EventSource cannot set Authorization headers"), and
`routes/videos.py::create_audio_token`/`_audio_token_tenant` already do EXACTLY this for audio
playback: a short-lived, tenant-carrying JWT in `?token=` on an `<audio>` URL. This is not a new
pattern for this codebase — it's the existing, accepted answer to "browser media tag can't send
headers." C25a extends it to `/api/media/drive/{file_id}` rather than inventing a fourth
mechanism, and reuses the SAME session-JWT-in-query-param path SSE already trusts.

Two token shapes both work (both carry a `tenant_id` claim, decoded identically):
1. **The user's own full session JWT** (30 days, already in `localStorage["token"]` for every
   `fetchApi()` call) — the frontend attaches it unchanged. No new mint-and-cache dance, no new
   endpoint; same credential, same privilege, reused for one more purpose.
2. **A short-lived (`purpose: "media"`, 60 min) token from the new `mint_media_token(tenant_id)`**
   — for backend code that fetches its OWN proxy over plain HTTP with a KNOWN `tenant_id` but no
   live user session to forward (cast-sheet vision, environment vision rewrite, talking-clip
   generation — these are backend-to-Kie/backend-to-self fetches, not `<img>` renders).

Never bakes a token into a PERSISTED url (e.g. a chat message's stored image url) — chat.py's
`_media_proxy_url` still returns the same bare, unauthenticated-shaped proxy path it always did;
the frontend attaches live auth at RENDER time (`withMediaAuth`), so a chat history reload months
later still works with whatever session is live then, instead of a baked-in token going stale.

### Backend

- **`routes/media.py`**: `_ALLOWLIST_SQL` — every one of the 7 `EXISTS` subqueries gained
  `tenant_id = $2`, e.g. (before) `SELECT 1 FROM assets WHERE image_url LIKE $1 OR ...` → (after)
  `SELECT 1 FROM assets WHERE tenant_id = $2 AND (image_url LIKE $1 OR ...)`. `_is_allowed(file_id,
  tenant_id)` now takes tenant_id and the in-memory cache key is `(file_id, str(tenant_id))` (was
  bare `file_id`) so no tenant can inherit another tenant's cached "allowed". New
  `_media_token_tenant(token) -> uuid.UUID`: 401 on missing/invalid/expired token, else the
  `tenant_id` claim (mirrors `_audio_token_tenant`'s shape). New `mint_media_token(tenant_id,
  minutes=60)`: signs a `{"purpose": "media", "tenant_id", "exp", "iss": "storyengine"}` JWT with
  `SESSION_SECRET`. `serve_drive_file(file_id, request, token=None)` now resolves
  `tenant_id = _media_token_tenant(token)` BEFORE calling `_is_allowed(file_id, tenant_id)` — no
  DB query happens pre-auth (proven by a test that makes `_is_allowed` raise if called).
- **Backend-internal chokepoints wired to mint their own token** (all already had `tenant_id` in
  scope, none had a live user session to forward): `routes/characters.py::_fetch_image_bytes`
  (now takes `tenant_id`, cast-sheet portrait fetch), `_build_cast_sheet`'s per-character vision
  pass, `lock_project_cast`'s per-image vision pass; `routes/environments.py`'s per-environment
  vision-rewrite pass; `pipeline_executor.py`'s `_proxy_url` closure (talking-clip generation,
  `self.tenant_id`). `routes/chat.py::_media_proxy_url` deliberately left untouched (see mechanism
  note above — it's a persisted-URL producer, not a live fetch).
- **Extension-suffix bug caught mid-fix**: `pipeline_executor.py` appended a cosmetic `.png`/`.mp3`
  suffix to the END of these URLs for Kie model validators that reject extension-less URLs. With a
  `?token=` now in the URL, appending at the tail corrupts the token
  (`...?token=eyJ...XYZ.mp3` fails to decode). Added `_with_ext(url, ext)` which inserts the
  suffix into the path BEFORE the query string, and updated both call sites
  (`generate_talking_video`'s image + audio args) to use it instead of raw string concatenation.
- **Rate-limit exemption** (`rate_limit.py`'s `_SKIP_PREFIXES` including `/api/media/`): kept.
  The exemption existed for performance (74 images/page), not security — now that the route hard
  401s on a missing/invalid token before touching the DB or Drive, an unauthenticated scraper gets
  nothing regardless of request volume. Revisit only if abuse is observed from AUTHENTICATED
  accounts hammering the route (a different problem — per-plan `PLAN_LIMITS` still applies
  everywhere else those accounts touch).

### Frontend

- **`lib/utils.ts`**: new `withMediaAuth(url)` — appends `?token=<localStorage token>` (SSR-safe,
  no-ops server-side). New `appendQueryParam(url, key, value)` — a second query param added
  correctly (`&`, not a second `?`) regardless of what's already on the url. `toDisplayImageUrl`/
  `toDisplayVideoUrl` now route their result through `withMediaAuth`, AND handle the
  already-proxied-URL case (anything matching `/api/media/drive/` passes through with auth
  attached, rather than only converting raw `drive.google.com` links) — this is what makes chat's
  pre-built proxy urls authenticate too, without chat.py needing to change.
- **`components/chat/ChatCore.tsx`** (`SceneBoardsGrid`): `img.url` (built by `_media_proxy_url`)
  now wrapped in `withMediaAuth()` for both the `<a href>` (open-in-new-tab) and `<img src>`.
- **`components/production/ScenesWorkspaceTab.tsx`**: two call sites hand-rolled a `?cb=<bust>`
  cache-buster directly after `toDisplayImageUrl(...)` — now that that result already carries
  `?token=`, the old `${url}?cb=${bust}` string-template would have produced a second, invalid `?`
  and silently dropped the cache-buster. Both switched to `appendQueryParam(url, "cb", bust)`.
- Every OTHER consumer of `toDisplayImageUrl`/`toDisplayVideoUrl` (`CharactersTab.tsx`,
  `EnvironmentsTab.tsx`, `RenderTab.tsx`, `ThumbnailTab.tsx`, `app/profile/page.tsx`) needed NO
  per-file change — the auth attachment lives in the one shared function they already call.

### New/Modified Files
| Path | Change |
|------|--------|
| `storyengine/backend/routes/media.py` | Tenant-scoped `_ALLOWLIST_SQL`/`_is_allowed`; new `_media_token_tenant`, `mint_media_token`; `serve_drive_file` requires a resolved tenant before any allowlist query |
| `storyengine/backend/routes/characters.py` | `_fetch_image_bytes(url, tenant_id)`; 2 more vision-fetch call sites mint a media token |
| `storyengine/backend/routes/environments.py` | Vision-rewrite call site mints a media token |
| `storyengine/backend/pipeline_executor.py` | `_proxy_url` mints a media token; new `_with_ext()` fixes the extension-after-token-corruption bug |
| `storyengine/frontend/src/lib/utils.ts` | New `withMediaAuth`, `appendQueryParam`; `toDisplayImageUrl`/`toDisplayVideoUrl` attach auth + pass through already-proxied urls |
| `storyengine/frontend/src/components/chat/ChatCore.tsx` | `SceneBoardsGrid` wraps `img.url` in `withMediaAuth` |
| `storyengine/frontend/src/components/production/ScenesWorkspaceTab.tsx` | 2 cache-bust call sites switched to `appendQueryParam` |
| `storyengine/backend/tests/functional/test_c25a_media_tenant_auth.py` | NEW — 18 tests: allowlist tenant-scoping, cross-tenant denial, token validation, 401/404/502 route behavior |

**Verify:** `cd storyengine/backend && ./venv/bin/python -m pytest
tests/functional/test_c25a_media_tenant_auth.py -q` — 18 passed. Non-vacuous: `git stash` on the
4 touched backend files re-ran the same test file against the PRE-fix code — 11/18 failed (the
other 7 are tenant-agnostic shape assertions), proving the tests actually exercise the new
behavior, not just the new API surface. `python -m py_compile` clean on all 4 touched `.py` files.
Full backend suite: **1131 passed (1113 baseline + 18 new) / 16 pre-existing failures / 1
pre-existing error** — zero new failures, same failing-test-name set as the pre-change baseline.
Frontend: `npx tsc --noEmit` clean; `npm run build` compiles+typechecks clean (32/32 routes, same
pre-existing `NEXT_PUBLIC_API_URL` prerender gap every prior chunk hits, confirmed cosmetic by
re-running with a dummy value set).

Checklist §S5-1 ticked: the BLOCKER (tenant-blind allowlist + no auth dependency) is genuinely
closed. C26 (MCP endpoint) is now unblocked per the checklist's own gate.

**Deploy-safety assessment — the skew window is real, addressed explicitly:**
Backend auto-deploys hourly; frontend only redeploys on an explicit `--with-frontend`. Two
mismatched-version scenarios:
1. **NEW backend + OLD frontend** (the routine hourly case, and the dangerous one): old frontend's
   `toDisplayImageUrl`/`toDisplayVideoUrl` don't attach `?token=` yet → every `<img>`/`<video>` on
   an already-open tab, and any page the OLD frontend serves until its own redeploy, requests the
   proxy with NO token → new backend 401s → **every image blanks out app-wide** until the frontend
   redeploys. This is exactly the failure mode the chunk brief called out as the one to take
   seriously, and it is real.
2. **NEW frontend + OLD backend**: old backend's `serve_drive_file` has no `token` parameter at
   all — FastAPI ignores unknown query params, so the extra `?token=` is silently dropped and the
   OLD (unauthenticated) route behavior runs unchanged. Harmless — this direction is a non-issue.
3. **mid-session while the backend restarts**: a tab that's been open across the hourly backend
   restart is running old JS with no token — same failure as (1).

**No grace path was added in this pass** (an accept-but-log-unsigned fallback, or a dual-accept
window, would mean the tenant-blind bug stays live — a genuine 401 the instant the query param is
absent IS the fix; softening it defeats the point). Given that, **this cannot ff-merge on its own
timeline** — it needs to land as a **coordinated deploy**: `--with-frontend` in the SAME deploy
that ships this backend change, not the routine backend-only hourly pull. Recommendation: **hold
on this branch until the next `--with-frontend` deploy window**, then ship backend+frontend
together (VPS Deploy Coordination Rule §1: `vps-deploy.sh <session> --with-frontend`, lock file
held for the duration). Flagged in `tasks/live-verification-queue.md` §C25a as REQUIRED before
that deploy: confirm every image surface (Scenes workspace, chat boards, characters/environments,
thumbnails, render preview) actually renders post-deploy with a live browser pass — Playwright per
`webapp-testing`, not self-evaluation.

## C25b — S5-5/6/7 security hardening batch (added 2026-07-19)

**Checklist §C25b (audit `docs/reports/2026-07-17-storyengine-agent-audit-findings.md` §S5):**
three independent MED findings. Deliberately kept clear of every file C25a touched (media.py,
characters.py/environments.py vision-fetch paths, pipeline_executor's talking-clip path, frontend
utils/ChatCore/ScenesWorkspaceTab) — no overlap with the held branch.

**S5-5 — SQLi-lock coverage gap:** `tests/functional/test_sql_column_injection_lock.py`'s
`AUDIT_FILES` never covered `routes/characters.py`, `routes/environments.py`, `routes/queue.py`,
`routes/chat.py`. Added all 4. Adding them surfaced two false-positive shapes in the AST audit
itself (not real vulnerabilities — every offending column name traced back to a hardcoded literal
or a closed dict, never request input):
- `len(params)` / `len(params) - 1` arithmetic sizing `$N` placeholders (characters.py/
  environments.py/queue.py's `UPDATE ... SET {', '.join(sets)} WHERE id = $N AND ... = $N+1`
  pattern) — the audit's safe-by-index regex only recognized bare `idx ± N`, not `len(x) ± N`.
  Extended the regex (`len\(\w+\)(\s*[-+]\s*\d+)?`) — same safety class as `idx`, len() can only
  ever return an int. This ALSO retroactively fixed a genuine pre-existing failure in this same
  test caused by `routes/youtube_sync.py`'s identical `len(values)` shape (see Verify below).
- `chat.py`'s `key_col` (`_delete_competitor`, ~L2005/2011 — a hardcoded 2-way ternary,
  `("channel_url", ...) if url else ("channel", ...)`, never from request input) and `col`
  (`_apply_profile_ops`, ~L2311 — `_PROFILE_FIELD_COLS[kind]`, a closed 4-entry dict, gated by
  `kind in _PROFILE_FIELD_COLS` before use) — added both to `_VERIFIED_SAFE` with a comment on
  why each is safe. `routes/characters.py`/`routes/environments.py`/`routes/queue.py` needed no
  further changes — their only SQL f-string is the `sets`-join update, already safe-by-join.

**S5-6 — visual_styles bare-id mutations:** `activate_visual_style` and `delete_visual_style`
(`routes/visual_styles.py`) did an ownership `SELECT ... WHERE id = $1 AND project_id = $2`, then
mutated with `UPDATE/DELETE ... WHERE id = $1` only — no project_id repeated in the mutating
query. `visual_styles` has no `tenant_id` column (schema.sql: `project_id UUID REFERENCES
projects(id)`, tenant scoping goes through `projects.tenant_id`), so `project_id` is the correct
repeated clause. Fixed all 3 call sites: `activate_visual_style`'s activation UPDATE (~L416),
`delete_visual_style`'s reactivate-first-default UPDATE (~L448), and its own DELETE (~L453) — each
now carries `AND project_id = $2` with `project_id` as an explicit bound param.

**S5-7 — health/detailed fails open:** `main.py`'s `/api/health/detailed` used `if token and (not
auth... or ...)` — when `HEALTH_TOKEN` was unset, the whole condition short-circuited False and
the endpoint (error rate, task queue depth, memory/uptime) served with zero auth. Now: `if not
token: raise HTTPException(503, ...)` before the bearer-token check, so a missing HEALTH_TOKEN
fails closed instead of failing open. `/api/health` (the plain check, needed unauthenticated by
uptime monitors and carrying the C16d/S7-7 queue-status field) is untouched and still public.

### New/Modified Files
| Path | Change |
|------|--------|
| `storyengine/backend/tests/functional/test_sql_column_injection_lock.py` | +4 `AUDIT_FILES`; `len(\w+)` safe-by-index regex; 3 new `_VERIFIED_SAFE` entries (chat.py key_col ×2, col) |
| `storyengine/backend/routes/visual_styles.py` | 3 mutating queries gained `AND project_id = $2` |
| `storyengine/backend/main.py` | `/api/health/detailed` fails closed (503) when `HEALTH_TOKEN` unset |
| `storyengine/backend/tests/functional/test_c16d_health_queue_status.py` | Updated the no-token test to use a real token (old behavior assumed fail-open); added 3 new tests for the fail-closed gate, the 401-wrong-token path, and that `/api/health` stays public |
| `storyengine/backend/tests/test_visual_styles_tenant_scoping.py` | NEW — 5 tests: activate/delete scoped to project_id, cross-tenant 404 + zero mutation, and a direct forged-project_id call against a fake table proving the WHERE clause itself (not just the route's 404 pre-check) blocks the mutation |

**Verify:** SQLi lock — canary proof: injecting a raw `f"UPDATE production_queue SET {bad_col} =
$1 ..."` into `routes/queue.py` (bad_col from `body.status`, unrouted) makes
`test_no_unvalidated_column_interpolations` fail immediately; reverted, passes again. visual_styles
— non-vacuous via `git stash` on `routes/visual_styles.py` alone: 3/5 new tests fail against
pre-fix code (`test_activate_scopes_update_to_project`, `test_delete_scopes_to_project_and_rejects_
cross_tenant`, `test_delete_active_style_reactivates_scoped_default`), pass after. health/detailed
— non-vacuous via `git stash` on `main.py` alone: the new fail-closed test fails pre-fix (endpoint
serves with no exception), passes after. `python -m py_compile` clean on all 3 touched `.py`
files. **Pre-existing-failure note:** `test_sql_column_injection_lock.py::
test_no_unvalidated_column_interpolations` WAS already failing on a clean checkout before this
chunk — confirmed via `git stash -u` full-tree baseline (1113P/16F/1E) — root cause was
`routes/youtube_sync.py`'s `len(values)` shape tripping the same false-positive the 4 new files
also tripped. The `len(\w+)` regex fix resolves it for both, so this chunk's actual full-suite
result is 16→**15** pre-existing failures, not merely "no new failures." Full backend suite:
**1122 passed / 15 failed / 1 error** (true clean-checkout baseline on this branch, confirmed via
`git stash -u`, was **1113P/16F/1E** — the checklist's stated "1131P/16F/1E" is C25a's
post-fix count; C25a is parked on the separate `claude/c25a-media-auth-hold` branch and is NOT
present on this branch, so 1113 is the correct baseline to diff against here). Net: +9 passing
(5 new visual_styles tests + 3 new health tests + 1 previously-failing SQLi-lock test now fixed),
zero new failures, one pre-existing failure resolved. Frontend: untouched (`git status` confirms
zero files under `storyengine/frontend/`) — no `tsc`/`build` run needed.

Checklist §C25b ticked — all 3 MED findings closed with regression locks.

**Deploy-safety assessment — clean ff-merge candidate:** all 3 fixes are backend-only,
additive-shaped (new WHERE clauses, a new 503 branch, test-file changes), and touch none of
C25a's files. No frontend skew risk (S5-7's 503 only fires for callers who already need
`HEALTH_TOKEN`; S5-6's stricter WHERE only removes an unreachable-in-practice path since the
prior SELECT already enforced project_id; S5-5 is test-only). Safe to ff-merge to main on the
routine hourly deploy — no coordination needed, unlike C25a.

**Next up: C26 · MCP endpoint + agent_tokens + auth (checklist S5-3/S5-4 design laws).** MUST ship
DARK behind `MCP_ENABLED=false` per the C25 sweep's own gate note — do not flip it on without a
separate explicit go-ahead.

## C26 — P2.4a StoryEngine MCP endpoint + agent_tokens migration + auth, SHIPPED DARK (added 2026-07-19)

**Checklist §P2.4a** (`tasks/storyengine-copilot-ux-map.md` §7, "the Higgsfield-killer door";
`docs/reports/2026-07-17-storyengine-agent-audit-findings.md` §S5-2/S5-3/S5-4 design laws). Scope
deliberately held to endpoint + tokens + auth + one read-only proof tool — C27 does the full tool
set + money gate, C28 the Settings UI, C29 the live external-client loop.

**`agent_tokens` table (migration 099, applied LIVE via Supabase MCP against `wrromlupsmyzrrcqlucn`,
confirmed via `information_schema.columns`):** `id, tenant_id, name, token_hash, created_at,
last_used_at, revoked_at` — RLS on, no policies (same playbook §7 pattern as generation_claims/
generation_passes/style_presets). `token_hash` is a plain sha256 hex digest (`agent_tokens.py::
_hash_token`), NOT a slow KDF — deliberate: this hashes a 256-bit random secret with zero
guessable structure, not a human password, so pbkdf2/bcrypt would only tax every MCP call for no
security benefit (contrast google_auth.py's pbkdf2, which defends a genuinely low-entropy secret).
Plaintext is generated once by `create_agent_token()`, returned to the caller, and never persisted
anywhere — schema.sql updated with the same CREATE TABLE block.

**Distinct auth dependency — S5-4 design law:** `backend/auth_agent.py::get_agent_tenant_id` parses
`Authorization: Bearer se_agent_<secret>`, calls `agent_tokens.authenticate()` (hash lookup +
`revoked_at IS NULL` — S5-3, re-checked on every single request, no caching), 401s on anything else.
`auth.py` (verify_token/get_tenant_id, the session/Supabase JWT surface every other route uses) is
completely untouched — grep-proof test asserts `se_agent_`/`agent_tokens`/`auth_agent` appear
nowhere in `auth.py`'s source, and that `auth_agent.py` never imports `auth.py` at all. This is the
concrete fix for the finding that worried the audit: without this separation, an agent token would
satisfy the SAME `Depends(get_tenant_id)` every other route uses, including
`/api/settings/keys/{name}/reveal` (decrypted BYOK material) — worse than the money-gated paid
verbs, since key-reveal isn't gated at all.

**MCP endpoint — protocol shape justified:** `routes/mcp.py`, single `POST /api/mcp` JSON-RPC 2.0
route (`initialize` / `tools/list` / `tools/call`), no SSE stream, no `Mcp-Session-Id` transport
negotiation. The UX map §7 spec names "streamable-HTTP MCP endpoint" only parenthetically as an
alternative file/route name, not as a transport mandate — and this server has zero
server-initiated pushes and no long-running tool in v1, so the fuller Streamable HTTP transport
buys nothing yet. Whether a real external MCP client actually needs it instead of bare
JSON-RPC-over-POST is the explicit open question deferred to C29's live loop test (see
`tasks/live-verification-queue.md` §C26).

**v1 tool surface — deliberately minimal (2 tools, both read-only, both tenant-scoped):**
`list_videos` (id/title/status, `SELECT ... WHERE tenant_id = $1`) and `get_video` (reuses
`actions.video_summary()` byte-for-byte — no new query path). Explicitly EXCLUDED per the audit's
design laws: every paid/generation verb (S5's money gate doesn't exist on this door until C27),
`remember`/`forget` (S5-2 — MCP v1 must EXCLUDE memory-writing tools outright, not merely
confirm-gate them), and any media/asset URL in a tool result (C25a's Drive media-proxy tenant-auth
fix is HELD on `claude/c25a-media-auth-hold`, not on this branch — `video_summary()` never returns
one anyway, but a test pins the guarantee at the MCP boundary too).

**Mint/list/revoke — the OTHER auth boundary:** `routes/agent_access.py`
(`POST/GET /api/agent-tokens`, `DELETE /api/agent-tokens/{id}`) uses the NORMAL session auth
(`Depends(get_tenant_id)`, same as every other authed route) — minting/revoking a token is a USER
action, never something an agent-authed request can do. Registered unconditionally in main.py (not
gated by `MCP_ENABLED` — it's exactly as safe as any other session-authed route with no caller yet).
C28 wires the Settings "Agent access" UI to these three routes.

**Dark-by-default (the deploy-safety mechanism):** `main.py` only does
`app.include_router(mcp_routes.router)` inside `if os.getenv("MCP_ENABLED", "").lower() == "true":`
— confirmed by actually reloading `main.py` under each env state (not reading the source): with
`MCP_ENABLED` unset, `"false"`, or absent, `/api/mcp` is NOT in `app.routes` at all (a request
404s exactly like any other undefined path); with `MCP_ENABLED=true` it registers. `/api/agent-tokens`
is present in both cases (unconditional, per above).

### New Files
| Path | Purpose |
|------|---------|
| `storyengine/backend/migrations/099_agent_tokens.sql` | `agent_tokens` table, applied live |
| `storyengine/backend/agent_tokens.py` | mint/list/revoke/authenticate — the only module that touches token_hash |
| `storyengine/backend/auth_agent.py` | `get_agent_tenant_id` — the distinct MCP-only auth dependency (S5-4) |
| `storyengine/backend/routes/mcp.py` | `POST /api/mcp` JSON-RPC endpoint; `list_videos`/`get_video` tools |
| `storyengine/backend/routes/agent_access.py` | session-authed mint/list/revoke routes for C28's UI |
| `storyengine/backend/tests/functional/test_c26_mcp_agent_tokens.py` | 27 tests (see Verify) |

### Modified Files
| Path | Change |
|------|--------|
| `storyengine/backend/main.py` | +`agent_access` import/registration (unconditional); MCP router registration gated by `MCP_ENABLED=true` |
| `storyengine/schema.sql` | `agent_tokens` table appended (mirrors migration 099) |

**Verify:** 27 new tests, all passing standalone AND under pytest — mint stores hash-not-plaintext
(assert stored hash != plaintext, plaintext string absent from the DB row); authenticate
round-trip; revoked-token rejected on the immediate next call (S5-3); revoke is idempotent +
tenant-scoped (cross-tenant revoke attempt returns False); `authenticate()`'s last_used_at update
is fail-soft (a raising `execute()` still returns the tenant_id); `list_agent_tokens()` never
includes `token_hash`. `get_agent_tenant_id`: missing header / wrong scheme / wrong prefix /
revoked token all 401; valid token returns the tenant UUID. Structural separation: `auth.py` grep
clean of `se_agent_`/`agent_tokens`/`auth_agent`, exactly one `verify_token`/`get_tenant_id`
definition each; `auth_agent.py` never imports `auth.py`. Cross-acceptance BOTH directions: a real
agent token fed into `auth.verify_token` 401s (proving key-reveal and every ordinary route stay
unreachable); a real session JWT fed into `get_agent_tenant_id` 401s (wrong prefix, rejected before
the DB). `routes/mcp.py`: `tools/list` is exactly `{list_videos, get_video}` (asserts 8 named
paid/write/memory verbs are absent); both tools proven tenant-scoped with two-tenant fake data;
`get_video`'s result text scanned for `http://`/`https://`/`drive.google`/`_url"`/`media_url` — none
present. `main.py`: real reload under `MCP_ENABLED` unset/false/true — route absent/absent/present;
`/api/agent-tokens` present regardless. **Non-vacuous via `git stash -u`** on all 7 new/changed
files together: with them stashed, `pytest tests/functional/test_c26_mcp_agent_tokens.py` errors
with "file or directory not found" (the module doesn't exist) — popped, all 27 pass again.
`python -m py_compile` clean on every touched/new `.py` file. **Full backend suite: 1149 passed /
15 failed / 1 error** — baseline (per the prior handoff) was **1122 passed / 15 failed / 1 error**;
1149 − 1122 = exactly the 27 new tests, same 15 pre-existing failure names, same 1 pre-existing
error. Zero new failures. Frontend: untouched (`git status` confirms zero files under
`storyengine/frontend/`) — no `tsc`/build run needed.

Checklist §C26 ticked. Live MCP-client connection test deferred to `tasks/live-verification-queue.md`
§C26 (after the coordinated deploy + `MCP_ENABLED` flip — needs C25a merged first).

**Deploy-safety assessment — ff-merge candidate, dark-shipped:** every new route this chunk adds is
either (a) gated behind `MCP_ENABLED` (unset in prod today, so `/api/mcp` genuinely does not exist
post-merge — zero new external surface) or (b) `/api/agent-tokens`, a normal session-authed route
with no UI caller yet (C28), which is no more reachable-by-mistake than any other authed endpoint
with no frontend button pointing at it. `main.py`'s only unconditional change is one router
registration line + a new import name; `schema.sql`/migration 099 is a pure additive `CREATE TABLE
IF NOT EXISTS`. No overlap with C25a's held files. Safe to ff-merge to main on the routine hourly
deploy — the MCP surface stays inert until a deliberate, separate `MCP_ENABLED=true` flip
(explicitly NOT part of this chunk) coordinated with C25a's media-proxy fix landing first.

**Next up: C27 · P2.4b full tool set + quote/confirm_token money gate on every paid tool** (S5-2
constraint stands: memory-writing tools stay excluded or confirm-gated + attributed via C28's "via
agent" chip — do not silently add `remember`/`forget` to the MCP surface without that).

---

## C27 — P2.4b StoryEngine MCP full tool set + quote/confirm_token money gate, SHIPPED DARK (added 2026-07-19)

**Checklist §P2.4b** (`tasks/storyengine-copilot-ux-map.md` §7; `docs/reports/2026-07-17-storyengine-
agent-audit-findings.md` §S5-2 constraint + the rate-limit gap C26 flagged). Expands C26's 2
read-only tools to the FULL `actions.ACTIONS` verb registry (free + paid) plus 5 more read tools
plus `create_video`, with a two-step quote/confirm_token money gate on every paid verb. Still dark
behind `MCP_ENABLED` — no new external surface until a deliberate flag flip + C25a lands.

**One registry, three doors — no forked dispatch:** every verb tool (free or paid) dispatches
through `routes.chat._run_pending_action` — the EXACT function chat's own confirm-card tap-to-run
path calls, proven by patching THAT function (not an MCP-local copy) in
`test_c27_mcp_toolset_money_gate.py::test_paid_verb_confirmed_call_dispatches_same_runner_as_chat`.
`_run_pending_action` gained one new parameter, `caller: str = "chat"` — default preserves every
existing chat.py call site's `claimed_by="chat:<verb>"` string byte-for-byte (pinned by
`test_run_pending_action_default_caller_is_chat_unchanged`); MCP passes `caller="agent:<token
name>"`. Underneath, `_run_pending_action` still holds C16a's generation_claims concurrency lock,
C16b's skip-if-done, C16c's ledger backstop, and C16e's upload skip-if-already-uploaded — this
chunk adds a gate IN FRONT, never touches what's inside.

**Tool surface v2 (`routes/mcp.py`):**
- **Reads (7, unchanged tenant scoping, no media URLs):** `list_videos`, `get_video` (from C26) +
  new `get_scenes` (per-scene pics/clips/approved/routed_model/routing_reason/camera_preset_id —
  hand-written query, deliberately never SELECTs an `*_url` column), `get_script` (scene_text/
  status/voice_status/tone, same no-URL discipline), `get_ledger` (reuses
  `routes.videos.get_video_ledger` verbatim), `list_style_presets` (reuses
  `routes.style_presets.list_style_presets`, `preview_url` explicitly stripped — belt-and-
  suspenders, same posture C26 took with `get_video`), `list_models` (reuses
  `routes.model_registry.list_models` verbatim — no URLs in that shape at all).
- **Free writes (12, execute immediately, no confirm_token):** every `actions.ACTIONS` verb with
  `paid: False` — `approve_cast`, `approve_environments`, `skip_environments`, `approve_scene`,
  `camera_preset`, `script_profile`, `lock`, `unlock`, `drive_push`, `drive_sync`, `advance` — plus
  `create_video` (a special case, not an ACTIONS verb: reuses `routes.videos.create_video`
  verbatim; free because creating the row spends nothing — the first paid verb run against that
  video is what gates on a quote; `thumbnail_url` stripped from its result, belt-and-suspenders).
- **Paid (15, the money gate below):** every `paid: True` verb — `script`, `characters`,
  `storyboards`, `images`, `voice`, `animate`, `draft_pass`, `finalize`, `sound`, `thumbnail`,
  `render`, `research`, `seo`, `upload`, `build`.
- **Upload-in-v1 call (explicit, per the chunk's own instruction to state it):** INCLUDED, named
  `upload` (not `upload_draft_to_youtube` — matches the ACTIONS verb name, not the UX map's prose).
  Carries BOTH required semantics: C16e's skip-if-already-uploaded (`actions.already_uploaded_reply`
  checked before a quote is even minted, so a repeat "upload" call never mints a fresh
  confirm_token for a second YouTube draft) AND the money gate below (quote → confirm_token →
  redeem, same as every other paid verb — "paid" here means "always confirms", matching
  `ACTIONS["upload"]`'s own `paid: True` comment: "Free in dollars but it PUBLISHES").
- **S5-2 pin:** `remember`/`forget`/`set_budget` are not in `actions.ACTIONS` at all, so there was
  nothing to wrap — a test (`test_s5_2_memory_tools_never_appear`) pins their absence regardless,
  and the superseded C26 assertion in `test_c26_mcp_agent_tokens.py` was updated (not deleted) to
  match the new surface while keeping that exclusion.

**The money gate — `confirm_tokens.py` (new module, migration 100, `mcp_confirm_tokens` table,
applied LIVE via Supabase MCP against `wrromlupsmyzrrcqlucn`, confirmed present):** DB-row-backed
(chat's `pending_action` lives in one conversation's state across two turns of the SAME
conversation; an MCP client's quoting and confirming `tools/call` are two independent HTTP
requests, possibly different backend processes — needs a real durable token, same reasoning that
made `agent_tokens` a DB row instead of a stateless JWT). Design:
- **Single-use:** `redeem()` is ONE atomic `UPDATE ... WHERE used_at IS NULL ... ` — the row-count
  IS the check, no read-then-write race (same pattern as `agent_tokens.revoke_agent_token`).
- **Short-lived:** 10-minute expiry (`confirm_tokens.TTL_SECONDS`), checked in the SAME atomic
  UPDATE (`expires_at > now()`).
- **Parameter-bound:** the token is minted against `params_hash(verb, scene, change, length_min,
  target)` — a canonical sha256 of the exact quoted call. The confirming call recomputes the hash
  from ITS OWN arguments; the redeem UPDATE's WHERE clause requires an exact match on tenant,
  video, verb, AND params_hash — so a token minted for "animate scene 3" cannot spend on "animate
  scene 12" (`test_confirm_token_rejects_params_mismatch_bait_and_switch`, and the same proof one
  layer up through `_call_verb` in `test_paid_verb_params_mismatched_confirm_refused`). The "build"
  verb's server-derived `target` ("pictures" vs "finish") rides in the same hash, so a video that
  crosses that boundary between quote and confirm naturally invalidates the token
  (`test_build_verb_target_rides_the_params_hash`).
- Token shape mirrors `agent_tokens.py`: `mcpc_<43-char urlsafe secret>`, sha256 hex hash stored
  (not a slow KDF — same "this hashes 256 bits of pure entropy, not a human password" rationale).

**The money-gate matrix (`_call_verb` in `routes/mcp.py`), test names:**
`test_paid_verb_without_confirm_token_returns_quote_not_execution` (quote returned, `_run_pending_
action` NOT awaited), `test_paid_verb_wrong_confirm_token_refused`, `test_paid_verb_expired_or_
reused_token_refused`, `test_paid_verb_params_mismatched_confirm_refused`, `test_confirm_token_is_
single_use` (redeem twice — second is False), `test_confirm_token_expires`, `test_paid_verb_
confirmed_call_dispatches_same_runner_as_chat` (the same-runner proof), `test_free_verb_dispatches_
immediately_no_confirm_token_ever_touched` (patches `confirm_tokens.create`/`redeem` to RAISE if
touched at all — proves a free verb never goes near the gate), `test_blocked_verb_refused_before_
any_quote_minted` (missing prerequisite refuses before `confirm_tokens.create` is even called),
`test_verb_call_is_tenant_scoped` (mirrors C26's `get_video` tenant test). One quoted refusal path
(`test_paid_verb_wrong_confirm_token_refused`): a garbage `confirm_token` on the "animate" tool
returns `isError: true`, message "confirm_token is invalid, expired, already used, or doesn't match
these exact arguments — call this tool again WITHOUT confirm_token to get a fresh quote", and
`_run_pending_action` is proven never awaited.

**Rate limiting (the C26-flagged gap, fixed at the extractor):** `rate_limit.py::
_extract_tenant_from_jwt` (now `async`) recognizes the `se_agent_` prefix BEFORE attempting a JWT
decode and resolves the tenant via `agent_tokens.authenticate()` — the SAME DB-backed,
revocation-aware lookup `auth_agent.py` uses for the real auth decision — with a 30s TTL cache keyed
by a sha256 hash of the token (never the plaintext) to avoid a DB round-trip on every single
request. `RateLimitMiddleware.dispatch`'s one call site (`_extract_tenant_from_jwt`) is now
`await`ed. Proof: `test_agent_token_request_is_rate_limited_per_tenant` seeds a tenant's bucket to
the free-plan limit (60/min) and shows a real `se_agent_...`-bearer request 429s through the actual
middleware `dispatch()` (not just the extractor in isolation);
`test_agent_token_request_passes_through_under_the_limit` shows it passes when under the limit;
`test_session_jwt_path_is_unaffected` proves the existing JWT path never even reaches the new
branch (asserts `agent_tokens.authenticate` is NOT called for a real session JWT).

**Attribution (the seam for C28's "via agent" chip):** `mcp_rpc` resolves the calling token's
display name via a new fail-soft `agent_tokens.name_for_token()` (one extra SELECT by token_hash,
never raises, falls back to the generic `"agent"` string on any miss — never blocks the call) and
threads `caller=f"agent:{name}"` into `_dispatch` → `_call_verb` → `_run_pending_action` →
`generation_claims.acquire(..., claimed_by=f"{caller}:{verb}")` (single-stage verbs and the "build"
autobuild chain) and, via `pending["caller"]`, into `actions._runner_draft_pass`/`_runner_finalize`'s
own independent claims (those two runners claim their own lane rather than going through
`_run_pending_action`'s generic claim path — same seam, threaded one level deeper).
**What C28's chip should read:** `generation_claims.claimed_by LIKE 'agent:%'` — this is LIVE
attribution (true only while a claim is held, the same ephemeral signal chat's own `claimed_by`
already carries) — deliberately not a new durable column/migration, per the audit's "smallest
correct v1" framing for S5-2. Free verbs (approve_scene, camera_preset, ...) and `create_video`
have no generation_claims row at all (nothing to claim), so there is no durable "via agent" marker
for those today — a real historical record would need a new column, explicitly out of this
chunk's scope; noted as a C28 follow-up if wanted.

### New Files
| Path | Purpose |
|------|---------|
| `storyengine/backend/migrations/100_mcp_confirm_tokens.sql` | `mcp_confirm_tokens` table, applied live |
| `storyengine/backend/confirm_tokens.py` | create/redeem/params_hash — the money-gate token |
| `storyengine/backend/tests/functional/test_c27_mcp_toolset_money_gate.py` | 33 tests (tool surface, money-gate matrix, attribution) |
| `storyengine/backend/tests/functional/test_c27_rate_limit_agent_tokens.py` | 6 tests (extractor + end-to-end middleware) |

### Modified Files
| Path | Change |
|------|--------|
| `storyengine/backend/routes/mcp.py` | Full verb-registry tool surface + money gate + attribution (see above) |
| `storyengine/backend/routes/chat.py` | `_run_pending_action` gains `caller: str = "chat"` param, threaded into 2 `claimed_by` call sites + into `pending` for runner verbs |
| `storyengine/backend/actions.py` | `_runner_draft_pass`/`_runner_finalize` read `pending["caller"]` for their own `claimed_by` |
| `storyengine/backend/agent_tokens.py` | +`name_for_token()` (fail-soft display-name lookup for attribution) |
| `storyengine/backend/rate_limit.py` | `_extract_tenant_from_jwt` now `async`, recognizes `se_agent_` tokens via `agent_tokens.authenticate()` (hashed 30s cache) |
| `storyengine/backend/main.py` | Comment update only (C26→C26/C27 references) — no behavior change |
| `storyengine/schema.sql` | `mcp_confirm_tokens` table appended (mirrors migration 100) |
| `storyengine/backend/tests/functional/test_c26_mcp_agent_tokens.py` | 2 assertions updated (superseded, not deleted) to match the expanded tool surface — still pins list_videos/get_video present + S5-2 exclusions |

**Verify:** 39 new tests (33 + 6), all passing standalone and under pytest. **Non-vacuous via
`git stash push`** on the 7 tracked modified files (confirm_tokens.py/migration left untouched,
since they're new/untracked): re-running the two new C27 test files against the stashed
(pre-chunk) code produced **22 failed + 6 errored** (`AttributeError: module 'routes.mcp' has no
attribute 'agent_tokens'` etc.) — only the 11 `confirm_tokens.py`-only unit tests passed (that
module is independent of the stashed files). Stash popped, all 39 pass again. `python -m
py_compile` clean on every touched/new `.py` file. **Full backend suite: 1188 passed / 15 failed /
1 error** — baseline (C26 handoff) was **1149 passed / 15 failed / 1 error**; 1188 − 1149 = exactly
the 39 new tests, same 15 pre-existing failure names, same 1 pre-existing error. Zero new failures.
(One transient regression during development: adding migration 100 without updating `schema.sql`
tripped `test_schema_sql_migrations_drift.py` — fixed by appending the same `CREATE TABLE` block to
`schema.sql`, confirmed clean before the final run above.) Frontend: untouched (`git status`
confirms zero files under `storyengine/frontend/`) — no `tsc`/build run needed, matches the
checklist's `[U]` none this chunk.

Checklist §C27 ticked. Live MCP-client full-loop verify (create → route → draft → finalize →
upload draft, every paid step quote-gated) deferred to `tasks/live-verification-queue.md` §C27 —
rides with C29 after the coordinated deploy (`MCP_ENABLED=true` + C25a merged first).

**Deploy-safety assessment — ff-merge candidate, still dark:** every change in this chunk is either
(a) inside `routes/mcp.py`, structurally unreachable while `MCP_ENABLED` is unset in prod (the
entire expanded tool surface + money gate is dead code externally until that flag flips), (b) the
`rate_limit.py` extractor fix, which is a pure ADDITION (an `se_agent_`-prefixed bearer was
previously always `None` from this function; every other bearer shape — real session JWTs, garbage
— takes the exact same path as before, proven by `test_session_jwt_path_is_unaffected`), or (c) the
`_run_pending_action`/`_runner_draft_pass`/`_runner_finalize` `caller` parameter additions, which
default to the byte-identical pre-C27 `claimed_by` strings for every existing chat.py call site
(pinned by `test_run_pending_action_default_caller_is_chat_unchanged`). No overlap with C25a's held
files. Safe to ff-merge to main on the routine hourly deploy — the MCP surface stays inert until a
deliberate, separate `MCP_ENABLED=true` flip coordinated with C25a's media-proxy fix landing first.

**Next up: C28 · P2.4c Settings "Agent access" UI + "via agent" attribution chip** (mint/list/revoke
UI already has session-authed routes from C26 — `routes/agent_access.py` — this chunk just needs
the frontend; the attribution chip reads `generation_claims.claimed_by LIKE 'agent:%'` live, per
this chunk's note above, plus whatever task-status-message surfacing makes sense for the
in-progress UI).

## C28 — P2.4c Settings "Agent access" UI + "via agent" attribution chip (added 2026-07-19)

**Checklist P2.4c (tasks/storyengine-copilot-ux-map.md §7):** the frontend for the mint/list/revoke
routes C26 shipped (`routes/agent_access.py`, session-authed, already registered unconditionally in
`main.py` — no `MCP_ENABLED` gate on this half of the surface) plus a running-task "via agent"
chip so a web user isn't surprised by ghost activity an agent started.

**Settings UI — `storyengine/frontend/src/app/settings/agent-access/page.tsx` (new):** a new
"Agent Access" tab in the Profile hub (`components/nav/hub-tabs.tsx`'s `PROFILE_TABS`, between
"API Keys" and "Billing"), deliberately built with `/settings/keys`' component vocabulary (`Card`/
`Modal`/`Spinner` from `@/components/ui`) rather than `/settings/page.tsx`'s `GlassCard` style —
an agent token is structurally the same kind of thing as an API key: a secret minted once, tested
never, revoked later. Ships: list (name, created, last used, revoked badge — revoked tokens stay
in the list, struck-through, for audit, never deleted from view), "Create token" (name input →
`createAgentToken` → the response's plaintext `token` is shown in the SAME modal exactly once with
a copy button and a "you won't see this again" warning), "Revoke" per active token (a confirm
modal, not a bare click — mirrors the destructive-action pattern elsewhere in the app), and a
"How to connect" block giving the literal MCP endpoint (`${API_URL}/api/mcp`) plus an honest note
that it requires `MCP_ENABLED` on the server. Loading/error/empty states covered. React Query
(`["agentTokens"]`) invalidates on both mint and revoke.

**Plaintext-once discipline (verified by trace, not just written):** `createMutation`'s `onSuccess`
calls `setMintedToken(result)` (component `useState`) and separately `invalidateQueries` on the
LIST query — it never calls `queryClient.setQueryData` with the mutation result, so the plaintext
never enters the React Query cache (only the id/name/created_at-shaped list does, per
`agent_access.py`'s own `list_tokens` route, which never selects `token_hash`). No
`localStorage`/`sessionStorage` write anywhere in the new file (grepped — zero hits). Closing the
modal (backdrop, Escape, or the "Done" button — all three route through the same
`closeCreateModal`) sets `mintedToken` back to `null`; there is no path to re-open the modal and
see the same token again, matching the backend's own "shown once" contract
(`agent_access.py::create_token`'s docstring).

**"Via agent" chip — the attribution seam, extended one field, not rebuilt:** traced the C19a
shared task watcher (`hooks/use-task-poller.ts`) end to end: `GuidedNextStep`'s running banner
reads `taskWatcher.running`/`taskWatcher.message` directly off the `TaskWatcherBridge` object
`pipeline/[videoId]/page.tsx` constructs from its ONE `useTaskWatcher({videoId, ...})` poll against
`GET /api/pipeline/task/{video_id}` (`routes/pipeline.py::get_task_status`) — that endpoint did
NOT carry attribution before this chunk (checked: response was `{status, message, error}` only).
Smallest correct backend addition (no new migration, no durable column — same ephemeral,
best-effort framing C27 already flagged for this signal):
  - `generation_claims.py` gains `get_claimed_by(tenant_id, video_id)` — read-only, and
    deliberately FAIL-SOFT (returns `None` on any DB error), unlike `acquire()`/`is_blocked()`
    which fail closed — there is no money-safety reason for a UI chip to deny anything.
  - `routes/pipeline.py` gains `_agent_name_from_claimed_by(claimed_by)` — the pure parser turning
    `"agent:<name>:<verb...>"` (routes/mcp.py's `caller=f"agent:{name}"` threaded through every
    `generation_claims.acquire()` an MCP-dispatched verb makes) into `"<name>"`; every other shape
    (`"chat:..."`, `None`) returns `None` — the fail-safe the chip depends on.
  - `get_task_status` now returns an additive `via_agent` field, looked up ONLY while
    `status == "running"` (a finished task's claim is already released — no DB round-trip wasted
    on the common case).
  - Frontend: `TaskStatus.via_agent` (optional, `api.ts`), `useTaskWatcher` now
    tracks a `viaAgent` state mirroring `message`'s exact lifecycle (set while active, cleared to
    `null` on completion AND on `markStarted()`'s optimistic arm — a locally-started run has no
    attribution to show yet, so any stale agent name from a PREVIOUS run is cleared immediately
    rather than flashing briefly), threaded onto `TaskWatcherBridge.viaAgent` and read directly off
    the bridge in `GuidedNextStep` (same pattern `running` already uses — no signature change to
    `useSharedTaskWatcher`'s return value was needed). Chip renders only `{!locking && viaAgent &&
    ...}` — absent/null `via_agent` renders nothing, by construction.

**Tests — `storyengine/backend/tests/functional/test_c28_agent_attribution.py` (new, 15 tests):**
pure-parser cases (single-verb claim, `build:target` claim, chat-held → `None`, `None`/empty →
`None`, defensive `"agent:"` with no name segment → `None`), `get_claimed_by` (returns the live
claim, `None` on no claim, ignores >2h-stale rows, fails soft on DB error — never raises — and is
tenant-scoped: a claim under tenant A never surfaces for tenant B's lookup, mirroring
`test_cross_tenant_task_isolation.py`'s existing contract for the rest of this task-status
machinery), and the endpoint itself (`via_agent` present + correct name when claim is agent-held,
absent when chat-held, absent when no claim, and — the cost-consciousness check — the claim lookup
is never even called when the task isn't `"running"`). **Non-vacuous via `git stash push` on the 2
tracked modified files** (`generation_claims.py`, `routes/pipeline.py`): 14 of 15 tests failed
against the pre-chunk code (`KeyError: 'via_agent'`, `AttributeError` on the missing parser/lookup
functions) — the 15th (`test_task_status_idle_response_still_has_no_via_agent_key_crash`) legitimately
passes both ways, since the idle branch's 3-key shape predates this chunk. Stash popped, all 15
pass again. `python -m py_compile` clean on both touched files.

**Full backend suite: 1203 passed / 15 failed / 1 error** — baseline (C27 handoff) was **1188
passed / 15 failed / 1 error**; 1203 − 1188 = exactly the 15 new tests, same 15 pre-existing
failure names, same 1 pre-existing error. Zero new failures.

**Frontend:** `npx tsc --noEmit` clean. `npm run build` — clean with `NEXT_PUBLIC_API_URL` set;
without it, `/privacy` fails to prerender on the SAME pre-existing `env.ts` `requireInProd` guard
that has nothing to do with this chunk (confirmed via `git log` — `env.ts` and `privacy/page.tsx`
are both untouched by this diff; the guard predates C28 entirely) — this is the "prerender quirk
pre-existing" the chunk brief itself named, not a new regression. `/settings/agent-access`
prerendered successfully as a static page alongside the other 32 routes once the env var was set.

**Files touched:**

| File | Change |
|------|--------|
| `storyengine/backend/generation_claims.py` | + `get_claimed_by()` (read-only, fail-soft) |
| `storyengine/backend/routes/pipeline.py` | + `_agent_name_from_claimed_by()`; `get_task_status` gains additive `via_agent` field |
| `storyengine/backend/tests/functional/test_c28_agent_attribution.py` | New — 15 tests (parser, `get_claimed_by`, endpoint) |
| `storyengine/frontend/src/app/settings/agent-access/page.tsx` | New — the Settings "Agent access" UI |
| `storyengine/frontend/src/components/nav/hub-tabs.tsx` | + "Agent Access" tab in `PROFILE_TABS` |
| `storyengine/frontend/src/lib/api.ts` | + `AgentToken`/`AgentTokenCreated` types, `getAgentTokens`/`createAgentToken`/`revokeAgentToken`; `TaskStatus` gains optional `via_agent` |
| `storyengine/frontend/src/hooks/use-task-poller.ts` | `useTaskWatcher` tracks/returns `viaAgent`; `TaskWatcherBridge` gains `viaAgent` |
| `storyengine/frontend/src/app/pipeline/[videoId]/page.tsx` | Threads `viaAgent` from `useTaskWatcher` into the `taskWatcher` bridge memo |
| `storyengine/frontend/src/components/production/GuidedNextStep.tsx` | Running banner renders the "via agent: `<name>`" chip when `taskWatcher.viaAgent` is set |

Checklist §C28 ticked. No live click-through (mint → copy → connect a real MCP client → chip
appears on a live agent-driven run) — deferred to `tasks/live-verification-queue.md` §C28, rides
with C29 after the coordinated deploy + `MCP_ENABLED` flip (same dependency C26/C27 already
carry — this chunk's backend/frontend changes are independently safe to ship now; only the
end-to-end MCP connection itself needs the flag).

**Deploy-safety assessment — ff-merge candidate:** the Settings UI calls only `routes/agent_access.py`
(session-authed, registered unconditionally, already live on main since C26 — no skew: main
already has the routes this chunk's frontend calls) and the `get_task_status` endpoint (also
already on main, this chunk only ADDS a field additively — any OLDER frontend build still parses
the response fine since it simply ignores the unknown key, and this NEWER frontend handles a
hypothetical rollback to an older backend fine too, since `via_agent` is read as `task.via_agent ??
null` everywhere, never assumed present). No migration, no `MCP_ENABLED` interaction (the chip and
the Settings UI both work whether or not MCP is enabled — an agent token can be minted/revoked
regardless; it just can't be USED to call the dark MCP endpoint until the flag flips, same as
before this chunk). No overlap with C25a's held files. Safe to ff-merge to main on the routine
hourly deploy.

**Next up: C29 · P2.4d full external-client loop verify (create → route → draft → finalize →
upload draft).** This is a LIVE verification chunk — it needs the coordinated deploy, the
`MCP_ENABLED=true` flip, AND a real external MCP client (Claude Desktop or equivalent) to drive
the actual conversation from "outside" the app. Recommend the orchestrator treat C29 as a
`tasks/live-verification-queue.md` entry (folding in §C26/§C27/§C28's already-deferred live checks)
plus a separate sandbox-side dry-run of the JSON-RPC surface (`initialize`/`tools/list`/
`tools/call` against a local `MCP_ENABLED=true` backend with a minted token, no real external
client) rather than a normal Sonnet-worker build chunk — there is no more code to write here; C25a
(media-proxy tenant-auth fix) still needs to land via its coordinated deploy first, same
dependency C26/C27 already flagged.

---

## C29 — P2.4d external-client loop verify: sandbox dry-run + consolidated live recipe (added 2026-07-19)

**Checklist §P2.4d, as split by the chunk brief itself** (`tasks/storyengine-wiring-fix-checklist.md`
line 263: "recommend folding into `tasks/live-verification-queue.md` ... plus a sandbox-side
JSON-RPC dry-run, rather than a normal build chunk"). The original spec — a full external-client
loop (create → route → draft → finalize → upload draft) driven by a REAL MCP client against a REAL
coordinated deploy — needs infrastructure this sandbox does not have (no route to the VPS, no MCP
client installed here, no Kie key). Split into the two halves that ARE possible:

**(a) The sandbox half — `test_c29_mcp_full_session_dry_run.py` (new, 2 tests):** an 11-step
simulated external-client session driven entirely through the REAL ASGI app
(`main.app`, `TestClient`, `MCP_ENABLED=true` via the same reload-main technique C26's test file
established) — real HTTP requests, real JSON-RPC envelope, real `RateLimitMiddleware`, real
`auth_agent.get_agent_tenant_id` dependency, real `agent_tokens.authenticate`/`create_agent_token`/
`revoke_agent_token`, and — the centerpiece — the REAL `confirm_tokens.create`/`redeem` money-gate
logic (only its own DB `execute()` call is faked, same technique C27's own test file uses; the gate
ITSELF runs for real, which is what makes the canary proof below meaningful). Session:

  1. `initialize` — real dispatch.
  2. `tools/list` — paid verb schemas carry `confirm_token`, free verbs don't, S5-2 memory-tool
     exclusion still holds.
  3. `create_video` (free) — dispatches through the real `routes.videos.create_video` (patched at
     that module's own boundary, same as C26/C27's test files) — `thumbnail_url` confirmed stripped
     from the MCP result (C25a hold).
  4. `get_video` — reads back the created video's summary.
  5. `script` (a paid verb) with NO `confirm_token` — returns a quote + `confirm_token`; the
     executor (`routes.chat._run_pending_action`, stubbed) is proven NOT invoked.
  6. Same verb WITH that `confirm_token` — dispatches; `run_pending_mock.assert_awaited_once_with`
     pins the EXACT args (`tenant_id`, `video_id`, `{"verb": "script", "scene": None, "change":
     None, "length_min": None}`, `background_tasks`, `caller="agent:C29 Dry-Run Session"`) — the
     attribution seam proven end-to-end from the bearer token's display name through to the
     executor call.
  7. The SAME `confirm_token` again (reuse) — refused (`isError: true`, the exact "invalid,
     expired, already used..." message), executor STILL called exactly once (not twice).
  8. `get_ledger` — stubbed spend rows returned through the real `get_video_ledger` route function
     boundary.
  9. Revoke the agent token via the REAL `DELETE /api/agent-tokens/{id}` route (session-authed via
     `app.dependency_overrides[auth.get_tenant_id]`, mirroring how a logged-in web session would
     revoke it).
  10. The next MCP call with the now-revoked token — real 401, immediately (S5-3, no cache on the
      auth decision itself).
  Plus, separately: `MCP_ENABLED` unset/false — a REAL `POST /api/mcp` request now 404s (test_c26's
  version only inspected `app.routes` structurally; this one actually sends the request).

**What's real vs. stubbed (stated plainly, per the file's own docstring):** real — the ASGI request/
response cycle, JSON-RPC framing, `RateLimitMiddleware`, `auth_agent.get_agent_tenant_id`, every
`agent_tokens.*` function, every `confirm_tokens.*` function (money gate). Stubbed — `routes.videos.
create_video`/`get_video_ledger` (DB writes, tested elsewhere), `actions.video_summary`/
`blocked_reason`/`estimate_cost`/`cost_breakdown`/`already_uploaded_reply` (tested in C27's money-gate
matrix), `routes.chat._run_pending_action` (the "executor" — the chunk brief's own words: "executor
stubbed, assert the real runner was invoked with the right args"), and the DB layer under
`agent_tokens`/`confirm_tokens` (an in-memory fake table — no live Postgres in this sandbox, same
`_FakeStore`/`_FakeConfirmStore` pattern as `test_c26_mcp_agent_tokens.py`/
`test_c27_mcp_toolset_money_gate.py`).

**Canary proof (in place of `git stash`, per the chunk brief's own instruction — this is a new test
of EXISTING code, not new production code, so a stash-based non-vacuous proof doesn't apply the same
way):** temporarily changed `routes/mcp.py`'s `if not ok:` (the confirm_token redeem-result check,
line 563) to `if False:` — i.e., neutered the money gate so a failed/reused token would dispatch
anyway. Re-ran `test_c29_mcp_full_session_dry_run.py`: **step 7 (token-reuse refusal) failed**
(`assert False is True` — the reuse call's `isError` came back `False` instead of `True`, because
the neutered check let the second, already-spent confirm_token dispatch a SECOND time). Reverted the
one-line change (confirmed via `git diff --stat routes/mcp.py` showing zero diff), re-ran — both
tests pass again. This is the sandbox-available equivalent of the checklist's usual
`git stash`-based non-vacuous proof: it shows the test actually exercises the money gate's real
logic, not a tautology that would pass even with the gate broken.

**(b) The live half — `tasks/live-verification-queue.md` §C29 (new section, placed near the top,
right after the "WHEN YOU'RE AT THE COMPUTER" priority list):** the ONE consolidated runbook folding
together C26's ("does a real MCP client actually connect, does it need the fuller Streamable HTTP
transport"), C27's ("live money-gate spot-check — real quote, real spend, real ledger row"), and
C28's ("mint → copy → connect → chip appears on a live agent-driven run") already-deferred live
checks — not four separate fragments. Six ordered steps: (1) coordinated deploy folding in C25a's
held branch + `--with-frontend` (references §C25a's own existing required check, doesn't duplicate
it), (2) flip `MCP_ENABLED=true` + `se.sh restart backend`, (3) mint a token in Settings → Agent
Access, (4) connect a real MCP client — exact `.mcp.json`-shaped config JSON given (URL + bearer
header) for Claude Code/Desktop/Hermes, explicitly framed as the live answer to the "does bare
JSON-RPC-over-POST suffice, or does a real client need SSE/Streamable-HTTP" question `routes/mcp.py`'s
own module docstring left open, (5) run the UX-map §7 example session for real on a disposable
2-scene test video (`create_video` → `draft_pass` quote → confirm → `finalize` quote → confirm →
`get_ledger` + the "via agent" chip + `claimed_by` all checked live), (6) revoke + confirm 401. Every
step states its expected result AND its rollback note (unsetting `MCP_ENABLED` + restart is the
universal rollback — instant dark, no migration to reverse). **Cost**: capped at **~$1–2**, itemized
per step 5 using the REAL registry prices (`skills/video-pipeline/shared/channel_profile.py`) —
draft-tier Grok Imagine clips ($0.09/6s-clip) + z-image or GPT-Image-2 pictures for a 2-scene test
video (~$0.20–0.80 per pass), explicitly forbidding a premium finalize (Veo Quality/Seedance, which
would run $6–50 per `docs/cost-awareness.md`'s own clip table) unless Ryan deliberately opts in.
Old §C26/§C27/§C28 pointers: none previously existed as their own queue sections (none of those
three chunks had shipped a standalone entry — checked, zero prior matches in the file) — added tiny
one-line redirect stubs (`### §C26 / §C27 / §C28 — see §C29 above`) so anyone following
`SYSTEM_STATE.md`'s existing "deferred to `tasks/live-verification-queue.md` §C26/§C27/§C28" pointers
lands on real content instead of a dead anchor.

### New Files
| Path | Purpose |
|------|---------|
| `storyengine/backend/tests/functional/test_c29_mcp_full_session_dry_run.py` | 11-step simulated external-client MCP session (2 tests) — see (a) above |

### Modified Files
None (routes/mcp.py's one-line canary edit was made and reverted locally, never committed —
confirmed via `git diff --stat routes/mcp.py` showing zero diff before this chunk's commit).

**Verify:** 2 new tests, both passing. Non-vacuous per the canary proof above (not `git stash`, since
this test exercises EXISTING C26/C27 code rather than adding new production code — the neutered-gate
canary is the equivalent proof for this shape of chunk). `python -m py_compile` clean on the new test
file and on `routes/mcp.py` (post-revert). **Full backend suite: 1205 passed / 15 failed / 1 error**
— baseline (C28 handoff) was **1203 passed / 15 failed / 1 error**; 1205 − 1203 = exactly the 2 new
tests, same 15 pre-existing failure names (`test_activity_feed_no_raw_errors.py` ×2,
`test_auto_scrape_ungated.py`, `test_clip_dialogue.py`, `test_dialogue_alignment.py`,
`test_discovery_error_surfacing.py`, `test_discovery_generation_no_leak.py` ×2, `test_model_video.py`
×2, `test_refresh_ideas_error_surfaced_lock.py`, `test_suggest_titles_wire.py`,
`test_youtube_my_videos.py`, `test_youtube_oauth_diagnostics.py` ×2), same 1 pre-existing error
(`test_validator_error_parsing.py::test_api_key`) — zero new failures. Frontend: untouched (`git
status` confirms zero files under `storyengine/frontend/`) — no `tsc`/build run needed.

Checklist §C29 ticked (the sandbox dry-run half; the live runbook half is tracked as its own
checklist-style steps inside `tasks/live-verification-queue.md` §C29, ticked independently by
whoever runs it on the VPS).

**Deploy-safety assessment — ff-merge candidate:** the ONLY production code touched this chunk is
the temporary, reverted canary edit to `routes/mcp.py` (confirmed zero diff via `git diff --stat`
before commit) — the real shipped diff is exactly one new test file (test-only, zero runtime
surface) plus two docs edits (`tasks/live-verification-queue.md`, this section). Nothing here
changes what's reachable in prod: `MCP_ENABLED` is still unset there, `/api/mcp` still structurally
doesn't exist. Safe to ff-merge to main on the routine hourly deploy — this chunk doesn't move C29's
own live half forward (that still needs the coordinated deploy + flag flip Ryan runs manually per
the new runbook), it only proves the code that's ALREADY on main behaves correctly under a real
HTTP session and gives Ryan the one recipe to run when ready.

**Next up: C30 · P3.1a preset/model choices queryable next to CTR/retention snapshots (Phase 3
begins)** — the learning-loop phase: surfacing which style preset / clip model a video used
alongside its CTR/retention numbers, plus the aggregation query that groups performance "by choice"
(a prerequisite for C31's "by style" analytics panel).

---

## C30 — P3.1a preset/model performance aggregation: `videos`-direct, no migration (added 2026-07-19)

**Checklist §3.1 `[D]`+`[B]` slice** (the loop's Phase 3 opener — "which visual styles / models /
presets actually earn views on this channel", the prerequisite for C31's "by style" UI panel +
producer citations). `[U]` is explicitly out of scope for this chunk (C31 does it) — frontend
untouched, confirmed via `git status` showing zero files under `storyengine/frontend/`.

**The linkage question, answered first (investigated via a Sonnet sub-agent read of
`routes/youtube_sync.py`, `routes/analytics.py`, `channel_briefs.py`, `agent_brain.py` before
writing any code):** published-video performance (CTR/views/retention) does **not** need a join to
`channel_videos` to reach StoryEngine's own `videos` rows. `videos` already carries its own
performance columns (`views`, `ctr`, `avg_retention`, `impressions`, `views_24h/48h/7d/30d`,
`ctr_48h`, `retention_48h`, `last_analytics_sync`) — written by
`youtube_sync.py::_writeback_matched_videos` (`~L371-423`), the SAME sync job that fills
`channel_videos`, one step later, gated on `_match_internal_videos` (`~L324-368`) finding a match.
Critically, `pipeline_executor.py::run_upload` sets `videos.youtube_video_id` **immediately on
upload** with no `channel_videos` insert anywhere in that path — a `channel_videos` row only
appears later, on the next `/api/youtube/sync` channel-uploads-playlist walk (capped at
`MAX_CHANNEL_VIDEOS=200`, requires channel-wide OAuth). So `videos.youtube_video_id IS NOT NULL`
with zero matching `channel_videos` row is a normal, expected state — requiring that join would
silently drop freshly-published videos. `routes/analytics.py::get_framework_performance` and
`channel_briefs.py::_own_performance_brief` already establish this exact "read `videos` directly,
never `channel_videos`" precedent for per-video-attribute aggregation; C30 follows it. **No
migration needed** — every column the aggregation touches (`style_preset_id` C20, `render_style`
C13b, `script_profile` C24, `assets.model_used`/`generation_ledger.model` C13/C07) already exists.

### What shipped

**New module `storyengine/backend/analytics_by_style.py`** — the ONE aggregation, two callers
(so the UI/endpoint and the copilot can never disagree, same "one implementation, N callers"
shape as `channel_briefs.py`'s existing three briefs):
- `get_style_performance(tenant_id) -> dict` with keys `by_style_preset`, `by_render_style`,
  `by_script_profile`, `by_clip_model`. Each list item: `{dimension, choice, video_count,
  synced_count, avg_ctr, avg_retention, total_views, total_spend}`.
- The three column dimensions (`_aggregate_column`) group straight off `videos` with the spend
  joined from a `generation_ledger` CTE:
  ```sql
  WITH spend AS (
    SELECT video_id, SUM(actual_cost) AS spend FROM generation_ledger
    WHERE tenant_id = $1 GROUP BY video_id
  )
  SELECT v.{column} AS choice, COUNT(*)::int AS video_count,
         COUNT(*) FILTER (WHERE v.last_analytics_sync IS NOT NULL)::int AS synced_count,
         ROUND(AVG(v.ctr) FILTER (WHERE v.last_analytics_sync IS NOT NULL)::numeric, 2) AS avg_ctr,
         ROUND(AVG(v.avg_retention) FILTER (WHERE v.last_analytics_sync IS NOT NULL)::numeric, 2) AS avg_retention,
         COALESCE(SUM(v.views), 0)::bigint AS total_views,
         COALESCE(SUM(s.spend), 0)::numeric AS total_spend
  FROM videos v LEFT JOIN spend s ON s.video_id = v.id
  WHERE v.tenant_id = $1 AND v.deleted_at IS NULL
    AND v.{column} IS NOT NULL AND v.{column} != ''
  GROUP BY v.{column} ORDER BY avg_ctr DESC NULLS LAST
  ```
  (`{column}` is always one of the 3 fixed literals in `_COLUMN_DIMENSIONS`, never caller input —
  no injection surface.)
- The 4th dimension, clip model, can't group directly off a `videos` column (a video's clips can
  route across multiple models, C13's mixed-routing money invariant) — `_aggregate_clip_model`
  instead picks each video's **dominant** model (the one that ran the most of its clips, via
  `ROW_NUMBER() OVER (PARTITION BY video_id ORDER BY COUNT(*) DESC, model ASC)` over
  `generation_ledger WHERE stage='clip'`) so a video's performance is attributed exactly once,
  never split or double-counted across model buckets.
- **Honest NULL handling**: `video_count` counts every video with that choice set; `synced_count`
  is the subset with `last_analytics_sync IS NOT NULL` (the same flag `_own_performance_brief`
  already treats as "has real data"). Averages use SQL `FILTER` over the synced subset only, so an
  unpublished/not-yet-synced video is counted but never drags an average toward zero pretending to
  be a real data point — its `avg_ctr`/`avg_retention` come back as JSON `null`, not `0`/`0.0`.
- **Fail-soft per dimension**: each of the 4 queries is wrapped in its own try/except returning
  `[]` on error — one broken GROUP BY can't sink the other three or 500 the endpoint.

**`routes/analytics.py`** — new `GET /api/analytics/by-style` (same router, no `main.py` change
needed — `analytics.router` was already registered). Thin wrapper: `return await
get_style_performance(tenant_id)`, `response_model=StylePerformanceResponse`.

**`models.py`** — new `StyleChoiceAggregate` + `StylePerformanceResponse` Pydantic models (per
codebase convention — most `routes/analytics.py` endpoints predate `response_model` typing, this
new one uses it, matching `routes/autopilot.py`'s `List[CompetitorCandidate]` etc. precedent).

**The read-tool, one implementation reused (checklist's explicit ask)** — `channel_briefs.py`
gets a 4th brief, `_style_performance_brief(tenant_id)`, calling `analytics_by_style
.get_style_performance` directly (not a re-derived query) and formatting the top 3 choices per
dimension **that clear `MIN_SAMPLE=2` synced videos** (so it never invents a trend out of one
lucky video) into producer-citable text ("By style preset - pixar_3d: 6.5% CTR, 55% retention (2
videos, $42.10 spent)"). Wired into BOTH existing surfaces that already call the other 3 briefs
(the C15d "one director voice + data reach" symmetry) — `agent_brain.py::_tool_channel_data` (the
in-video copilot's `channel_data` tool, doc string updated) and `routes/chat.py::_loop_brief` (the
home producer's always-on context). C31 builds the actual UI panel and the producer's live
citation logic on top of this same data; this chunk only makes the numbers reachable.

### Verify

**Non-vacuous via `git stash`** (tracked-file changes stashed + `analytics_by_style.py` moved
aside, `test_c30_style_performance.py` left in place): `ModuleNotFoundError: No module named
'analytics_by_style'` on collection — proves the tests exercise real new code, not tautologies.
Stash popped, file restored, re-ran clean.

10 new tests in `storyengine/backend/tests/functional/test_c30_style_performance.py`:
- `get_style_performance` groups correctly across all 4 dimensions from stub rows spanning 2
  style-preset groups (one synced, one "no data yet") + render_style/script_profile/clip_model
  groups; asserts tenant_id is the first bound param on every one of the 4 queries.
- NULL/no-data-yet honesty: a group with `synced_count=0` comes back `avg_ctr=None,
  avg_retention=None` (never coerced to 0), while `total_spend` still counts real ledger spend
  for that unsynced video.
- Dominant-clip-model dimension returns the expected model set from stubbed
  `generation_ledger`-shaped rows.
- One dimension's query raising (`by_render_style`) leaves it `[]` while the other 3 dimensions
  still come back populated — fail-soft proven per-dimension, not just at the top level.
- `GET /api/analytics/by-style` (TestClient) returns the identical shape/numbers as the direct
  function call, and an all-empty-DB scenario returns `{}`-shaped empty lists (never crashes).
- `_style_performance_brief` cites the exact same numbers the endpoint returned (`"pixar_3d: 6.5%
  CTR, 55% retention (2 videos, $42.10 spent)"` verbatim in both), skips the sub-`MIN_SAMPLE`
  "dossier" group, returns `""` fail-soft on a DB error, and `agent_brain._run_tool("channel_data",
  ...)` reaches the new brief section end-to-end.

`python -m py_compile` clean on all 7 touched/new files. **Full backend suite: 1215 passed / 15
failed / 1 error** — baseline (C29 handoff) was **1205 passed / 15 failed / 1 error**; 1215 − 1205
= exactly the 10 new tests; the failing-test-name list is byte-identical to the baseline's 15 (same
`test_activity_feed_no_raw_errors.py` ×2, `test_auto_scrape_ungated.py`, `test_clip_dialogue.py`,
`test_dialogue_alignment.py`, `test_discovery_error_surfacing.py`,
`test_discovery_generation_no_leak.py` ×2, `test_model_video.py` ×2,
`test_refresh_ideas_error_surfaced_lock.py`, `test_suggest_titles_wire.py`,
`test_youtube_my_videos.py`, `test_youtube_oauth_diagnostics.py` ×2) plus the same 1 pre-existing
error (`test_validator_error_parsing.py::test_api_key`) — zero new failures.

**Live verification deferred** to `tasks/live-verification-queue.md` §C30 (no migration to
information_schema-confirm, so the only live check is "real channel data aggregates sensibly" —
needs a tenant with actual synced YouTube analytics across 2+ style presets, which the sandbox
doesn't have).

### New Files
| Path | Purpose |
|------|---------|
| `storyengine/backend/analytics_by_style.py` | the one aggregation — `get_style_performance()` |
| `storyengine/backend/tests/functional/test_c30_style_performance.py` | 10 tests, all 3 layers |

### Modified Files
| Path | Change |
|------|--------|
| `storyengine/backend/routes/analytics.py` | new `GET /api/analytics/by-style` |
| `storyengine/backend/models.py` | `StyleChoiceAggregate` + `StylePerformanceResponse` |
| `storyengine/backend/channel_briefs.py` | new `_style_performance_brief` |
| `storyengine/backend/agent_brain.py` | `_tool_channel_data` + `TOOL_DOC` now include it |
| `storyengine/backend/routes/chat.py` | `_loop_brief` now includes it |

**Deploy-safety assessment — ff-merge candidate:** purely additive. New route, no `main.py`
change (router already registered); new Pydantic models (additive fields, nothing renamed/removed);
`channel_briefs`/`agent_brain`/`chat.py` changes only ADD a 4th brief call alongside the existing 3
— an old brief's behavior is byte-unchanged (the new brief's own failure is caught inside itself
and contributes `""`, same fail-soft shape as the other 3). No schema/migration risk (zero DDL this
chunk). No paid-generation surface touched. Safe to ff-merge on the routine hourly deploy.

**Next up: C31 · P3.1b analytics "by style" panel + producer cites channel-data in LOOK
recommendations** — build the frontend panel reading `GET /api/analytics/by-style`, and wire the
producer's LOOK-recommendation copy to cite `_style_performance_brief`'s numbers explicitly (this
chunk only made the tool reachable, didn't change what the producer says yet).

---

## C31 — P3.1b "by style" analytics panel + producer LOOK citations (added 2026-07-19)

**Checklist §3.1 `[U]` closer** (the preset-performance loop's last piece — C30 built the
aggregation and made it reachable by both chat surfaces; this chunk gives it a face on the
Analytics page and teaches the producer to actually QUOTE the numbers, not just have access to
them). Two doors note (UX map): the copilot's `channel_data` tool already covers the
conversational read (C30) — nothing more to wire there.

### `[U]` Analytics "by style" panel

New section on the existing `storyengine/frontend/src/app/analytics/page.tsx`, placed right after
the existing "What's Working (by framework)" block (same page, matching its established
GlassCard/tab-strip visual language — no new design system introduced). Four dimension tabs with
labels taken verbatim from schema.sql's own column comments so the UI vocabulary matches what the
columns actually mean, not a guess: **Look Engine** (`by_style_preset` — `style_preset_id`,
migration 097 FK), **Channel Look** (`by_render_style` — `render_style`, migration 089's
'animated'/'realistic' declaration), **Script Voice** (`by_script_profile` — migration 098's
editorial voice), **Clip Model** (`by_clip_model` — dominant model per video, from
`generation_ledger`). Table columns per the spec: Choice · Videos (`synced_count`/`video_count`
synced) · Avg CTR · Avg Retention · Total Views · Total Spend · Cost/1k Views.

- **"No data yet" contract (C30's `synced_count`, honored, not re-derived)**: a row with
  `synced_count === 0` renders its CTR/Retention cells as an italic "no data yet" label (not a
  bare dash — the spec asked for a CLEAR no-data state, distinguishable from a real small number)
  and the whole row is dimmed (`opacity: 0.55`); Total Views/Total Spend still render normally for
  that row because C30's aggregation already keeps those honest (spend on an unsynced video is
  still real ledger spend). Unlike the "What's Working (by framework)" panel above it (which
  `HAVING COUNT(*) >= 2`-filters weak groups out entirely), this panel shows EVERY row the endpoint
  returns, including `video_count === 1` groups — full transparency is the explicit ask here, the
  MIN_SAMPLE-style filtering is only for the chat brief's citation discipline (channel_briefs.py),
  not for what a user browsing their own dashboard gets to see.
- **Cost-per-1k-views — derived, no new math source**: `costPer1kViews(total_spend, total_views)`
  computes `total_spend / (total_views / 1000)` from the SAME two fields the endpoint already
  serves, nothing else. Guards `total_views <= 0` (and null/undefined) to `"--"` before dividing —
  never NaN/Infinity.
- **Fail-safe rendering, everywhere**: `pct1`/`pct0`/`money` helpers each return `"--"` on
  null/undefined/NaN input rather than rendering `NaN%` or `$NaN` — every cell in the table routes
  through one of these three or the explicit "no data yet" branch, so there is no path from a
  missing backend field to a broken-looking cell.
- **Loading/error/empty states**: `useQuery({queryKey: ["style-performance"], queryFn:
  getStylePerformance})` — spinner while loading, a plain "couldn't load" line on error (matches
  the page's existing inline-error tone, doesn't blow away the rest of the page), and the shared
  `EmptyState` component when the selected dimension's array is empty (e.g. a brand-new channel
  with only one look ever used).
- **New API surface** (`frontend/src/lib/api.ts`): `StyleChoiceAggregate` +
  `StylePerformanceResponse` interfaces copied field-for-field from
  `backend/models.py` (never retyped by hand), and `getStylePerformance()` hitting the existing
  `GET /api/analytics/by-style` (C30, unchanged this chunk).

**dataviz skill note**: this chunk didn't build a chart — the spec explicitly allows "a compact
table or bar comparison" and a table was in scope and simplest for showing 5+ numeric columns
side by side per row; no `dataviz` read was needed since no chart/mark/palette code was written.

### `[B]` Producer cites channel data in LOOK recommendations

**`storyengine/backend/producer_prompt.py`** — one new paragraph appended to the existing LOOK
bullet inside `CARD GUIDANCE:` (between the six-option LOOK card instruction and the LENGTH
bullet, not a freestanding section — keeps the citation logic attached to the exact moment the
producer is picking a look):

> "CITING CHANNEL DATA WHEN RECOMMENDING A LOOK (checklist §3.1/C31 — the preset-performance
> loop, the moat Higgsfield can't copy): when a "PERFORMANCE BY CREATIVE CHOICE" block is present
> below, weave its real numbers into your LOOK pitch instead of recommending blind — e.g. "your
> holographic videos average 2.1x the channel CTR — want to stay with it?" or "flat_2d has run the
> most videos here but pixar_3d is pulling a stronger CTR, if you want a switch." Only cite a
> choice that block actually lists, and always use its exact numbers — never invent, round up, or
> extrapolate a stat that isn't there. If that block is ABSENT, or a choice you'd otherwise
> recommend simply isn't in it, say nothing about channel performance and recommend on creative
> merit alone — never fabricate a number or imply data exists when it doesn't. This applies
> whenever you're recommending a LOOK, not only on the first turn."

No new ops, no new tool, no schema/route change — `_style_performance_brief` was already appended
to `_loop_brief` (C30) which is already passed into `build_system_prompt(brief)` at both call
sites in `routes/chat.py`; this chunk only teaches the model what to DO with the numbers that were
already arriving.

### Verify

**Non-vacuous via `git stash`** (only `producer_prompt.py` stashed,
`test_c31_style_citation.py` left in place): all 5 new tests fail — `AssertionError` on the
citation phrase not being in the prompt — proving they exercise the real added text, not a
tautology. Stash popped, re-ran clean.

**5 new tests, `storyengine/backend/tests/functional/test_c31_style_citation.py`** (C15d
prompt-pin pattern — prove the REAL composed runtime string, not just source text):
- The instruction text is present in `PRODUCER_SYSTEM_PROMPT`, lives inside the LOOK bullet's
  `CARD GUIDANCE:` block (ordering-asserted: between the LOOK card instruction and the LENGTH
  bullet, not a new top-level section), and forbids fabrication when the data block is absent.
- **The pin**: `channel_briefs._style_performance_brief` (monkeypatched `analytics_by_style
  .get_style_performance` with a stub matching C30's own test fixture shape — one synced
  `holographic_hud` group, one sub-`MIN_SAMPLE` `dossier` group) produces a real brief string,
  fed into `producer_prompt.build_system_prompt(brief)` — asserts BOTH the citation instruction
  AND the brief's actual cited numbers (`"holographic_hud"`, `"8.4% CTR"`) coexist in the ONE
  composed prompt string an Anthropic call would actually receive.
- A second pin with an all-empty brief (`_style_performance_brief` returns `""`) proves the
  composed prompt carries NO "PERFORMANCE BY CREATIVE CHOICE" brief content (checked via the
  brief's own literal header sentence, not the instruction's paraphrase of it, since the
  instruction text itself necessarily names the block) while the citation instruction remains
  present — the "stay silent when absent" contract has real data (or its absence) to apply to.

`python -m py_compile` clean on all touched/new backend files. **Full backend suite: 1220 passed /
15 failed / 1 error** — baseline (C30 handoff) was **1215 passed / 15 failed / 1 error**; 1220 −
1215 = exactly the 5 new tests; the failing-test-name list and the 1 error are byte-identical to
the baseline's (same `test_activity_feed_no_raw_errors.py` ×2, `test_auto_scrape_ungated.py`,
`test_clip_dialogue.py`, `test_dialogue_alignment.py`, `test_discovery_error_surfacing.py`,
`test_discovery_generation_no_leak.py` ×2, `test_model_video.py` ×2,
`test_refresh_ideas_error_surfaced_lock.py`, `test_suggest_titles_wire.py`,
`test_youtube_my_videos.py`, `test_youtube_oauth_diagnostics.py` ×2, plus
`test_validator_error_parsing.py::test_api_key`) — zero new failures.

**Frontend**: `npx tsc --noEmit` clean. `npm run build` reproduces a PRE-EXISTING prerender
failure on `/pipeline` AND `/analytics` (`NEXT_PUBLIC_API_URL is required in production builds`) —
confirmed unrelated to this chunk by re-running with `NEXT_PUBLIC_API_URL` set: build completes
cleanly, all 33 routes generate including `/analytics`, and the new panel's route is part of that
clean build.

**Live verification deferred** to `tasks/live-verification-queue.md` §C31 (needs a tenant with
real synced multi-preset analytics to see actual citation/panel numbers rendered, same data
dependency C30 already deferred).

### New Files
| Path | Purpose |
|------|---------|
| `storyengine/backend/tests/functional/test_c31_style_citation.py` | 5 tests, prompt-pin pattern |

### Modified Files
| Path | Change |
|------|--------|
| `storyengine/backend/producer_prompt.py` | LOOK bullet gains the channel-data citation instruction |
| `storyengine/frontend/src/app/analytics/page.tsx` | new "Performance by Style" panel (4 dimension tabs) |
| `storyengine/frontend/src/lib/api.ts` | `StyleChoiceAggregate`/`StylePerformanceResponse` types + `getStylePerformance()` |

**Deploy-safety assessment — ff-merge candidate:** purely additive both sides. Backend: one new
paragraph appended inside an existing prompt string (no schema/route/model change, no new op, no
new paid path) — an old turn where the brief is empty behaves byte-identical since the added
instruction only fires when there's data to cite. Frontend: one new page section reading an
already-shipped (C30) GET endpoint; every other component/query on the page is untouched. No
paid-generation surface touched anywhere in this chunk. Safe to ff-merge on the routine hourly
deploy.

**Next up: C32 · P3.2 legacy stubs** — `confidence_scorer.py`'s `momentum`/`retention`
placeholders, `learning_extractor.run_daily_extraction()`'s unwired Airtable CTR TODO, and
`osiris/learnings_engine.get_competitor_title_patterns()`'s empty-string stub: wire each to real
data or delete the call sites (Anti-Bandaid rule — no dark stubs left standing). May split into
sub-chunks depending on how entangled each turns out to be with the legacy Airtable pipeline vs.
StoryEngine's own reimplementation.

---

## C32 — P3.2 legacy stubs: scorer placeholders + learning_extractor + competitor_title_patterns (added 2026-07-19)

**Checklist §3.2 closer.** All three named stubs live in `skills/video-pipeline/` (the legacy
Airtable/VPS-cron pipeline for the real Economy FastForward channel — per `tasks/decisions.md`
2026-03-26, this is a permanently separate system from StoryEngine SaaS's Supabase-backed
`videos` table, not the same channel dogfooded through the SaaS). Traced each stub's reachability
from something that actually runs (VPS cron, per `infra/setup_cron.sh`) before deciding wire vs.
inert vs. delete — none of the three are called from StoryEngine's backend.

### Verdict table

| Item | Reachable from | Was | Action | Why |
|------|-----------------|-----|--------|-----|
| `ConfidenceScorer._score_channel_momentum` / `_score_retention_patterns` | `autopilot.autopilot --check-cycle` cron (6:30/7:30 AM, `infra/setup_cron.sh`) → `Autopilot.scorer` → `ConfidenceScorer.score()` — a REAL decision path (picks which idea becomes a produced, paid-for video) | Flat `50.0` constants carrying `0.10`/`0.08` config weight — a fixed, unearned +9.0 added to every candidate's score before comparing against `min_confidence_score` (60) | **Honest-inert**: weights pinned to `0.0` in both `autopilot_program.md` (source of truth) and `WeightsConfig` defaults; the other four weights renormalized in their original ratio (0.30:0.25:0.20:0.07 → 0.37:0.30:0.24:0.09, still sums to 1.0) so the score isn't just silently missing 18% of its scale. `ConfidenceScorer.__init__` now logs a `WARNING` once per scorer construction if either weight is ever non-zero again (regression guard, proven to fire — see below). Methods themselves are left in place (not deleted) — they're a real seam for a future fix, just disconnected from the score today. | No data pipeline exists for either signal: `competitor_scraper` stores point-in-time snapshots (no time series → no real "momentum"), and `topic_performance.md` only ever records CTR, never retention (the writer that would populate retention — `learning_extractor` — is itself the next stub below). Implementing either "for real" needs a new data pipeline, not a one-function fix — out of proportion for a stub-cleanup pass; the checklist's own escape hatch ("or remove the weights") is the right-sized move. |
| `learning_extractor.run_daily_extraction()` | `autopilot-learn` cron (`infra/setup_cron.sh` line ~158, daily) | `# TODO: Integrate with Airtable to get actual CTR data` — printed a reassuring "Learning extraction is ready" and returned, having done nothing. Root cause is actually TWO gaps, not one: (1) `ExperimentState.status` is NEVER set to `"monitoring"` anywhere in the codebase (`state_manager.record_production_cycle` only ever writes `"producing"`) — the `status != "monitoring"` guard has therefore never once been false in production; (2) even past that guard, no code pulls CTR/retention from Airtable into `LearningExtractor.extract_all()`/`MemoryWriter`. This is why `LEARNINGS.md` has shown "Videos produced: 0" since the file was written. | **Honest-inert, left running.** Docstring now states both gaps explicitly and points at this section. Function now emits a `logging.warning` every run ("NOT WIRED... no learnings will be extracted") instead of the old "ready" print. Removed two now-fully-unused local instantiations (`LearningExtractor()`, `MemoryWriter()` — never called either before or after this change). **Not deprecated in favor of StoryEngine's `routes/learning_extraction.py`** despite that route being a complete, working equivalent (title/hook/framework extraction gated on real CTR/retention) — because it reads the Supabase `videos` table per-tenant, and the legacy Economy FastForward channel has no tenant row there. Deprecating this cron job would remove the channel's only learning loop, even though that loop is currently a no-op — worse than leaving an honest, cheap, zero-cost no-op running. | Wiring both gaps for real is a state-machine + data-pull feature spanning `autopilot.py`, `ctr_monitor.py`, and this file — more than a "fix the stub" change, and it duplicates work StoryEngine already did properly for its own tenants. Flagged as a follow-up (not this chunk's job to build a second growth loop from scratch), same pattern as the documented upload-reupload-guard gap in `docs/failure-modes.md`. |
| `osiris/learnings_engine.LearningsEngine.get_competitor_title_patterns()` | **Nothing** — grepped the entire repo; zero call sites beyond its own definition | Hardcoded `return ""` with a "Future: Query a new Competitor Patterns table" comment — dead on arrival, no caller ever existed | **Deleted.** No callers to update. | Genuinely unreachable dead code per the C19b discipline — grep-proofed below. |
| *(bonus, caught by this chunk's own `[V]` grep)* `PatternLibrary.get_best_structures_for_topic()` | **Nothing** — zero call sites | `# TODO: Cross-reference with topic_performance.md` — returned the same hardcoded 5-structure list regardless of input `topic_category` | **Deleted.** No callers to update. | Same shape as the item above — the checklist's own verification grep (`grep -rn "TODO" autopilot analytics`) would have caught this one too had it been left in, so it's cleaned up in the same pass rather than leaving one TODO standing while removing three others. |

### Grep-proofs

```
$ grep -rn "TODO" skills/video-pipeline/autopilot skills/video-pipeline/analytics --include=*.py
(no output)

$ grep -rn "get_competitor_title_patterns" --include=*.py .
(no output beyond nothing — deleted cleanly, zero callers existed before deletion either)

$ grep -rn "get_best_structures_for_topic" --include=*.py .
(no output — deleted cleanly, zero callers existed before deletion either)
```

### Non-vacuous proof (weight-zeroing actually changes behavior)

Constructing `ConfidenceScorer` with the REAL `autopilot_program.md` config produces no warning
and the two placeholder components contribute `0.0` to the weighted sum (confirmed: scoring the
same candidate under the old `0.10`/`0.08` weights vs. the new `0.0`/`0.0` weights changes
`ScoredIdea.score` — the placeholder was previously moving the number that's compared against
`min_confidence_score`). Constructing `ConfidenceScorer` with a config that still carries the old
non-zero placeholder weights (regression scenario) correctly fires the two `WARNING` log lines
("has weight 0.10 but its scorer is unimplemented... Expected 0.0... until it's wired"),
proving the guard is live, not a decoration.

### Tests / Verify

- `python -m py_compile` clean on all 5 touched files.
- `cd skills/video-pipeline && python -m pytest autopilot/tests/ -q` → **144 passed, 2 failed**
  — identical to the pre-existing baseline (both failures are `test_integration.py`'s
  `test_full_cycle_selects_best_candidate` / `test_force_ignores_cadence`, caused by an unrelated
  pre-existing f-string bug in `autopilot.py:306`
  (`f"...{best_score:.0f if best_score else 'N/A'}"` is not valid format-spec syntax) — not one of
  this chunk's three named items, left untouched, out of scope). **Zero new failures.**
- `test_config_parser.py` needed no changes: its `SAMPLE_CONFIG` fixture is a self-contained
  markdown string exercising the parser's correctness generically, not the real
  `autopilot_program.md` file's specific numbers.
- Backend full suite: **1220 passed / 15 failed / 1 error** — byte-identical to the documented
  baseline (this chunk touches zero files under `storyengine/`).
- Frontend: **untouched** (`git status` confirms zero changes under `storyengine/frontend/`) —
  no build/tsc check needed.

### Modified Files
| Path | Change |
|------|--------|
| `skills/video-pipeline/autopilot/core/confidence_scorer.py` | Removed TODOs from `_score_channel_momentum`/`_score_retention_patterns` docstrings (now state clearly why each is a permanent placeholder pending real data); added one-time `WARNING` log in `__init__` if either weight is non-zero |
| `skills/video-pipeline/autopilot/core/config_parser.py` | `WeightsConfig` defaults: `channel_momentum`/`retention_patterns` → `0.0`; other four renormalized to sum to 1.0 |
| `skills/video-pipeline/autopilot/autopilot_program.md` | Same reweighting in the real production config, with an explanatory comment block |
| `skills/video-pipeline/autopilot/learning/learning_extractor.py` | `run_daily_extraction()` docstring now documents both real gaps (missing state transition + missing CTR pull); replaced misleading "ready" print with an honest `logging.warning`; removed two dead local instantiations |
| `skills/video-pipeline/analytics/osiris/learnings_engine.py` | Deleted `get_competitor_title_patterns()` (zero callers) |
| `skills/video-pipeline/autopilot/learning/pattern_library.py` | Deleted `get_best_structures_for_topic()` (zero callers, same TODO-stub shape, caught by this chunk's own verify grep) |

### Deploy-safety assessment — ff-merge candidate

This chunk touches only `skills/video-pipeline/` (legacy Airtable/VPS-cron code), never
`storyengine/`. It deploys via the SAME hourly `git pull --ff-only` cron mechanism described in
`docs/infrastructure.md` — no separate StoryEngine deploy step applies. What changes for the next
cron run: `autopilot-cycle` picks ideas using the renormalized (still-sums-to-1.0) weights instead
of weights that included two silently-inert placeholder terms — this changes absolute scores
slightly (both directions shift together) but does not introduce a new failure mode; `autopilot-learn`
now logs a clear `WARNING` instead of a misleading "ready" message, with identical (zero) real
effect either way. No schema change, no new cron job, no new paid path, no route/model changes.
Safe to ff-merge on the routine hourly deploy — cron config itself is unchanged (no entries added
or removed in `infra/setup_cron.sh`, so nothing needs re-running on the VPS beyond the normal git
pull).

## C32a — pre-existing invalid f-string fix (added 2026-07-19)

Fixed the exact bug C32 flagged as out-of-scope: `autopilot.py:306`/`:310` used
`f"{best_score:.0f if best_score else 'N/A'}"` — a conditional expression
inside a format spec, which is not valid syntax (`ValueError: Invalid format
specifier`). Replaced with a `best_score_str = f"{best_score:.0f}" if
best_score is not None else "N/A"` computed once and interpolated plainly
into both the `print` and the Slack `_notify` message (`is not None` rather
than a truthiness check, so a legitimate score of exactly `0` would still
render `"0"`, not `"N/A"` — the more correct read of the original intent).
Two-line, single-purpose diff.

**Honest result — the fix works, but does NOT turn the suite green.** The
crash is gone (`test_full_cycle_selects_best_candidate` /
`test_force_ignores_cadence` no longer raise `ValueError`), but both tests
still fail, now on `assert result is True` — a **second, independent,
pre-existing bug** the crash had been masking: `test_integration.py`'s mock
Airtable fixtures hardcode absolute `Published Date` values
(`2026-03-17T12:00:00Z` / `2026-03-16T12:00:00Z`, clearly meant to read as
"~24h / ~48h old" when the test was written). `check_cycle` computes
`hours_old` itself from that date against `datetime.now(timezone.utc)`
(`autopilot.py:149-156`) — it ignores the fixture's own `'Hours Old': 24`
field entirely. Against this session's system clock (2026-07-19) those dates
are ~124 days old, past `ConfidenceScorer.MAX_HOURS` (168h/7d), so
`timing_freshness` scores `0` for both candidates and the composite drops to
~49-63 — under `min_confidence_score: 60` — so `scorer.get_best()` correctly
returns `None` and `check_cycle` correctly returns `False`. Confirmed by
direct computation (not guesswork): constructing `IdeaCandidate`s with the
fixture's *intended* `hours_old` (24/48) scores 62.7-69.9 under the current
(post-C32) weights — comfortably over threshold — while the *actual*
124-day-old dates the fixture produces score ~49. This is a time-bomb test
fixture (absolute dates rot as wall-clock time advances), not a production
code defect, and not caused by or related to the f-string. Left unfixed per
this chunk's explicit scope (surgical f-string-only diff) and per the "don't
force-fix tests to pass" instruction — flagged as a new, distinct follow-up
(fixture should compute `Published Date` relative to `datetime.now()` at
test run time, e.g. via `freezegun` or a computed offset, not a hardcoded
absolute timestamp).

**Verify:** `python -m py_compile skills/video-pipeline/autopilot/autopilot.py`
clean. `cd skills/video-pipeline && python -m pytest autopilot/tests/ -q` →
**144 passed / 2 failed** (same count as the pre-existing baseline; the 2
failures changed from crash to a different, documented assertion failure —
net zero regression, zero new failures introduced, the named bug genuinely
fixed). Backend suite untouched — `git diff --stat` confirms only
`skills/video-pipeline/autopilot/autopilot.py` changed, zero `storyengine/`
files touched.

### Modified Files
| Path | Change |
|------|--------|
| `skills/video-pipeline/autopilot/autopilot.py` | Fixed invalid f-string format-spec at ~L306/L310 (conditional expression inside `:.0f` spec is not valid syntax) — extracted a `best_score_str` computed with a real ternary before interpolation |

### Deploy-safety assessment — ff-merge candidate

Single-file change inside `skills/video-pipeline/` (legacy cron pipeline),
touches only a `print`/Slack-notification string on the "no candidates meet
threshold" path — cosmetic/logging only, no scoring/decision logic changed.
Ships on the routine hourly `git pull --ff-only`, no VPS coordination needed.
Safe to ff-merge.

## C32b — time-bomb fixture fix, `test_integration.py` (added 2026-07-19)

Fixed the fixture C32a diagnosed: `mock_airtable`'s two competitor-video
records hardcoded absolute `Published Date` strings (`2026-03-17T12:00:00Z`
/ `2026-03-16T12:00:00Z`) meant to read as ~24h/~48h old at write time, but
`check_cycle` computes `hours_old` from that date against
`datetime.now(timezone.utc)` (`autopilot.py:149-156`) — it ignores the
fixture's own `'Hours Old': 24`/`48` fields entirely, which is what let the
dates silently rot past `ConfidenceScorer.MAX_HOURS` (168h) without anyone
noticing. Changed both `Published Date` values to be computed at test-run
time: `(datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()...`
and `...timedelta(hours=48)...`, so the fixture always represents the
24h/48h-old candidates it was written to be, regardless of wall-clock date.
Added `from datetime import datetime, timedelta, timezone` to the test
file's imports (timezone already used lower in the file; datetime/timedelta
were missing at module scope).

**Verify:** `python -m py_compile` clean on the touched test file. `cd
skills/video-pipeline && python -m pytest autopilot/tests/ -q` → **146
passed / 0 failed** (both previously-failing tests now pass; net +2 vs
C32a's 144/2 baseline, zero new failures). Backend suite untouched — only
`skills/video-pipeline/autopilot/tests/test_integration.py` changed.

**Sweep for the same rot pattern:** grepped all `autopilot/tests/*.py` for
absolute `202x-xx-xxT...` timestamps. Found five more hardcoded dates
(`test_state_manager.py`, `test_pattern_library_curiosity_gap.py`,
`test_memory_writer_structure.py`, `test_memory_writer.py`,
`test_pattern_library.py`, `test_notifier.py`) — none are time-bombs: they're
either opaque strings round-tripped through save/load equality checks
(`test_state_manager.py`'s `last_cycle`) or static markdown content /
assertion strings (`Last updated: 2026-03-18`, `notify_not_ready(...,
next_date="2026-03-20")`) that are never diffed against `datetime.now()` or
any computed age. Confirmed by grepping those files for
`datetime.now|MAX_HOURS|freshness|days_until|age` — no hits. Only
`test_integration.py`'s `Published Date` fields feed an actual age
computation, so it was the only fixture at risk.

### Modified Files (C32b)
| Path | Change |
|------|--------|
| `skills/video-pipeline/autopilot/tests/test_integration.py` | `mock_airtable` fixture's `Published Date` values now computed relative to `datetime.now(timezone.utc)` (now-24h / now-48h) instead of hardcoded absolute strings; added `datetime`/`timedelta` import |

### Deploy-safety assessment — ff-merge candidate

Test-only change, zero production code touched. No behavior change to
anything that runs in prod — purely fixes a test fixture so CI reflects
reality. Safe to ff-merge; no VPS coordination needed.

**Next up: C33 · P3.4 quota guard + own-video VPH.**

## C33 — P3.4 quota guard + own-video VPH (added 2026-07-19)

Checklist §3.4's two audit findings: (1) "YouTube quota (10k units/day ~ 6 uploads) documented but
not enforced in code" — the upload path had zero guard, a bad day just eats a raw 403; (2) "VPH
computed for competitors only, never for own videos — scorecards compare apples to oranges."

### Quota guard

**Scope decision, investigated first:** the 10,000-units/day quota is billed to a Google Cloud
PROJECT, not a channel. Grepped every `GOOGLE_OAUTH_CLIENT_ID`/`SECRET` read across the backend
(`youtube_publish.py`, `routes/youtube_sync.py`, `routes/google_auth.py`, `routes/youtube_channel.py`,
`routes/model_video.py`, `routes/videos.py`) — every one reads the SAME two env vars, no per-tenant
client id/secret anywhere. So every tenant's OAuth token is minted from one shared OAuth app, meaning
every tenant's Data API calls draw down the SAME pool. **Counter is GLOBAL (no `tenant_id`)** — a
per-tenant counter would under-count the real cross-tenant risk (tenant A could exhaust the pool
while tenant B's counter still reads "plenty left").

**Storage:** new dedicated table (migration 101, applied live via MCP to project
`wrromlupsmyzrrcqlucn` — confirmed via `information_schema.columns` + `pg_class.relrowsecurity`),
not a reuse of `generation_ledger` (migration 087) — that table is shaped for a different question
("what did THIS VIDEO cost in dollars", `video_id` NOT NULL, USD `actual_cost`); forcing a
video-less, non-dollar, cross-tenant API-unit counter through it would need nullable-video hacks for
a worse fit than a 3-column table. RLS enabled with no policies, matching the proven-safe pattern
from `secrets`/`static_reference_cache`/`channel_video_retention` (migration 083 — backend connects
as `postgres`, bypasses RLS via `rolbypassrls=true`).
```sql
CREATE TABLE IF NOT EXISTS youtube_quota_usage (
  day DATE PRIMARY KEY, units_used INTEGER NOT NULL DEFAULT 0, updated_at TIMESTAMPTZ DEFAULT now()
);
```

**New module `storyengine/backend/youtube_quota.py`** — unit costs from Google's published YouTube
Data API v3 quota-cost table (`videos.insert`=1600, `thumbnails.set`=50, `videos.update`=50,
`search.list`=100, `videos.list`/`channels.list`/`playlistItems.list`=1 each; cross-checked against
`youtube_data_api.py`'s pre-existing header comment, which already documented the list-call costs).
YouTube Analytics API (separate quota system) is deliberately NOT counted. `DEFAULT_CEILING = 9000`
(env `YOUTUBE_DAILY_QUOTA_CEILING`), leaving ~1,000 units headroom under the real 10,000/day limit —
more conservative than the checklist's illustrative "10k, 6 uploads" framing, by design. Reset key:
`_pt_today()` via `zoneinfo.ZoneInfo("America/Los_Angeles")` (stdlib, no new dependency) — matches
YouTube's real midnight-PT reset, not UTC midnight. `get_quota_status()` / `record_units()` /
`check_quota_available()` are all fail-soft: any DB error is logged and treated as "0 used today" —
a broken tracker must never itself block a real upload.

**Wired:**
- `youtube_publish.py::upload_video_to_youtube` — the ONLY `videos().insert` call site in the
  codebase (confirmed via grep; `pipeline_executor.py::run_upload` is the only caller). Checked
  BEFORE downloading the render/thumbnail (fail fast, no wasted bandwidth on a blocked upload);
  refusal returns `{"error": <quota_exceeded_message>, "quota_exceeded": True}`, which
  `pipeline_executor.py`'s existing `if up.get("error"): raise Exception(up["error"])` already turns
  into a clean failed-stage message — no raw 403 ever reaches the user. Actual spend recorded AFTER
  a successful upload (re-derived from whether the thumbnail actually shipped, not the pre-flight
  estimate), never before, so a failed upload never falsely counts against the budget.
- `routes/youtube_sync.py::_run_sync` — records the Data API list-call cost (channels.list +
  playlistItems.list pages + videos.list batches, ~1-10 units/tenant/day) for an honest running
  total. NOT gated — cheap enough (single digits to low tens of units) that adding a refusal path
  here would risk breaking analytics sync for negligible quota protection; the upload guard above is
  where refusal actually matters (1,600+ units vs. ~1-10).
- `main.py` — both `/api/health` and `/api/health/detailed` now carry a `youtube_quota:
  {date_pt, units_used, ceiling, remaining}` field (C16d/C25b pattern: each check wrapped in its own
  try/except so a broken quota read can't sink the rest of the health response).

### Own-video VPH

**New module `storyengine/backend/own_vph.py`**: `compute_own_vph(views, published_at) -> float |
None`. Reuses `routes.niche._calculate_vph` (the SAME math the competitor side already uses to rank
`competitor_videos` — confirmed this function already exists and is already imported the same way
by `routes/intelligence.py`) rather than reimplementing it — lazy-imported to avoid load-order
coupling, same discipline `channel_briefs.py` already documents for its own circular-import
avoidance. Returns `None` (not `0.0`) for the two dishonest cases: unpublished (`published_at` is
None), and published under `MIN_HOURS_FOR_VPH = 1.0` hours ago (a near-zero denominator doesn't just
divide-by-zero, it extrapolates a handful of views into a wildly misleading rate — e.g. 500 views 90
seconds after publish would otherwise read as "20,000/hr"). Derived at READ TIME, no stored column —
every caller already has `views`/`view_count` + a publish timestamp in hand from its own query.

**Wired at the three "own performance" surfaces the spec named:**
- `channel_briefs.py::_own_performance_brief` — added `upload_date` to the SELECT, `~{vph:.0f}/hr`
  appended per video line when available. This is the copilot's "how did my videos do?" answer —
  now velocity-aware, finally comparable to `_next_to_make_brief`'s competitor VPH.
- `routes/analytics.py::get_channel_videos` (`GET /api/analytics/videos`) — added `"vph":
  compute_own_vph(r["view_count"], r["published_at"])`. Noted honestly: this endpoint has no
  frontend caller today (checked `grep -rn getChannelVideos frontend/src` — zero hits, pre-existing
  dead wiring this chunk didn't create); added for consistency and to be ready when a caller exists.
- `analytics_by_style.py`'s aggregation (C30) — added `avg_vph`, computed IN SQL (not a per-row
  Python pass, since the query already groups server-side): `views / hours-since-upload_date`,
  excluding rows published under an hour ago via the same `MIN_HOURS_FOR_VPH` floor, filtered to the
  same synced subset as `avg_ctr`/`avg_retention`. Added to `models.py`'s `StyleChoiceAggregate`
  (Pydantic `response_model` would otherwise silently strip an unlisted field — locked by a
  dedicated test) and surfaced as a new "Avg VPH" column in `analytics/page.tsx`'s by-style table
  (mirrors the existing CTR/Retention column pattern exactly — `npx tsc --noEmit` clean).

**Legacy check (avoid duplicating):** searched `performance_tracker`/`ctr_monitor` in
`skills/video-pipeline` for an existing own-VPH computation — none found; that side never computed
own velocity either, only competitor VPH via the same `calculate_vph` this StoryEngine-side fix
mirrors. Nothing to reuse from there; `routes.niche._calculate_vph` (StoryEngine's own competitor-VPH
calculator, already live) was the correct, closer reuse target and is what `own_vph.py` wraps.

### Verify

**Non-vacuous via file-hide + `git stash`:** moved `youtube_quota.py`/`own_vph.py` out of the tree
(keeping the 3 new test files) → all three fail to collect (`ModuleNotFoundError`); separately,
`git stash -u` (stashes tracked changes + all untracked new files together) then popped clean.
Restored, re-ran green.

`python -m py_compile` clean on every touched/new backend file.

21 new tests across 3 files:
- `tests/functional/test_c33_youtube_quota.py` (12 tests) — units accumulate across calls;
  default ceiling is 9000 (not the checklist's illustrative 10k); the checklist's own "6 uploads
  fit, 7th refused" scenario reproduced exactly with an explicit 10,000-unit ceiling env override
  (6×1600=9600≤10000 passes, 7th would be 11,200>10,000, refused, message names the exact
  used/ceiling numbers + "midnight Pacific"); `upload_cost()` thumbnail math; fail-soft on read AND
  write DB errors (read failure never blocks a normal-cost check, write failure never raises after a
  real upload); midnight-PT reset (two different Pacific-day keys are independent counters, proven
  by monkeypatching `_pt_today()`); a direct cross-check that `_pt_today()` really uses
  America/Los_Angeles (`2026-07-19T06:00:00Z` == `2026-07-18` Pacific, not `2026-07-19`); both health
  endpoints carry the field.
- `tests/functional/test_c33_own_vph.py` (6 tests) — unpublished → None; zero/near-zero-hours guard
  → None (both "published this instant" and a future/clock-skew timestamp); known fixture (1,200
  views / 24h → 50.0 VPH, matching the checklist's own worked example) from both a `datetime` and an
  ISO string; 0 views with a real publish date → `0.0` (an honest answer, unlike the unpublished/
  zero-hours cases); direct cross-check against `routes.niche._calculate_vph` proving this is a thin
  wrapper, not a parallel reimplementation that could drift.
- `tests/functional/test_c33_vph_wiring.py` (3 tests) — `avg_vph` survives `_aggregate_column`/
  `_aggregate_clip_model`'s dict-building AND survives FastAPI's `response_model` filtering (the
  exact failure mode of adding a field to SQL/dict but forgetting the Pydantic model).

**Full backend suite:** `./venv/bin/python -m pytest tests/ -q` → **1241 passed / 15 failed / 1
error** (baseline 1220/15/1 + this chunk's 21 new tests, zero new failures — the same 15
pre-existing failures, none touching any file this chunk modified). Discovered and fixed one
drift-checker regression along the way: `test_schema_sql_migrations_drift.py` failed until
`youtube_quota_usage` was also added to `schema.sql` (migration alone isn't enough — that test
enforces schema.sql stays the fresh-install source of truth).

**Autopilot suite (untouched — confirmed via `git status`, zero files under `skills/video-pipeline/`
changed this chunk):** `cd skills/video-pipeline && python3 -m pytest autopilot/tests/ -q` → **146
passed / 0 failed**, unchanged from the C32b baseline.

**Live proof:** migration 101 applied via Supabase MCP `apply_migration` to project
`wrromlupsmyzrrcqlucn`; confirmed via `execute_sql` — `information_schema.columns` shows the 3
expected columns/types, `pg_class.relrowsecurity` = `true`. No live quota/VPH sanity run (would
need a real upload or real synced channel data) — deferred to `tasks/live-verification-queue.md`
§C33 per this chunk's spec.

### Modified/New Files (C33)
| Path | Change |
|------|--------|
| `storyengine/backend/youtube_quota.py` | NEW — global daily quota tracker (unit costs, PT-day key, fail-soft check/record) |
| `storyengine/backend/own_vph.py` | NEW — `compute_own_vph()`, thin wrapper over `routes.niche._calculate_vph` |
| `storyengine/backend/migrations/101_youtube_quota_usage.sql` | NEW — `youtube_quota_usage` table + RLS-no-policies |
| `storyengine/schema.sql` | Added `youtube_quota_usage` section (drift-checker requirement) |
| `storyengine/backend/youtube_publish.py` | Quota check before upload (fail-fast before download), unit recording after success |
| `storyengine/backend/routes/youtube_sync.py` | Records sync-side Data API list-call units (not gated) |
| `storyengine/backend/main.py` | `/api/health` + `/api/health/detailed` carry `youtube_quota` field |
| `storyengine/backend/channel_briefs.py` | `_own_performance_brief` adds `upload_date` to SELECT + VPH line |
| `storyengine/backend/routes/analytics.py` | `get_channel_videos` adds `vph` field |
| `storyengine/backend/analytics_by_style.py` | Both aggregation queries add `avg_vph` (SQL-derived) |
| `storyengine/backend/models.py` | `StyleChoiceAggregate.avg_vph` |
| `storyengine/frontend/src/lib/api.ts` | `StyleChoiceAggregate.avg_vph`, `ChannelVideo.vph` |
| `storyengine/frontend/src/app/analytics/page.tsx` | New "Avg VPH" column in the by-style table |
| `storyengine/backend/tests/functional/test_c33_youtube_quota.py` | NEW — 12 tests |
| `storyengine/backend/tests/functional/test_c33_own_vph.py` | NEW — 6 tests |
| `storyengine/backend/tests/functional/test_c33_vph_wiring.py` | NEW — 3 tests |

### Deploy-safety assessment — ff-merge candidate

Additive across the board: new table (RLS-locked, no policy access from anon/authenticated), new
modules, new fields on existing responses (nothing removed/renamed), one new frontend table column.
No behavior change for a tenant with zero YouTube activity today (quota check reads "0 used" and
passes through; VPH is `None` until a video has real synced data). The one path with real
production consequence — the upload quota gate — only ever *adds* a refusal it didn't have before;
it cannot make an upload that used to succeed now fail for any reason other than the tenant's
project genuinely being near its real Google-enforced ceiling. Safe to ff-merge.

**Next up: C34 · SWEEP S10 (multi-tenant branding) + P3.4 SEO branding parameterization.** Per the
loop's sweep-then-fix playbook, recommend the orchestrator dispatches the S10 sweep first (Explore
half) and folds its findings into the same chunk as the SEO-branding fix (`upload/seo_generator.py`'s
hardcoded `@Power_Doctrine`/`#PowerDoctrine`, checklist §3.4's last unfixed bullet) rather than
sequencing them as two separate chunks.

## C34a — S10-1 CRITICAL fix: remove/hard-block the legacy upload fallback (added 2026-07-19)

Audit finding §S10-1 (docs/reports/2026-07-17-storyengine-agent-audit-findings.md, found by the C34
sweep): `pipeline_executor.py::run_upload` fell through to `self._pipeline.run_upload_bot()` (the
legacy `skills/video-pipeline/upload/` bot) whenever a tenant had no connected YouTube channel
(`channel_profiles.youtube_refresh_token`). That legacy bot (a) hardcoded `@Power_Doctrine` SEO onto
the TENANT's video via Airtable fields, (b) uploaded through the SHARED VPS OAuth token files — i.e.
onto RYAN's own YouTube channel, category 25, not the tenant's — and (c) never passed through C33's
YouTube quota guard (that guard lives entirely inside `youtube_publish.upload_video_to_youtube`, the
native path's own function; the legacy bot never calls it). None of that is recoverable after the
fact — it publishes.

### The fix

**Executor is the authority.** `pipeline_executor.py::run_upload` — the `if cp and
cp.get("youtube_refresh_token"):` native-path branch is untouched (byte-identical); the `else` no
longer falls through to `self._pipeline.run_upload_bot()`. It now returns immediately:
```python
error_msg = "Connect your YouTube channel first — Settings → YouTube."
await self._log_activity(bot_name, video_id, "failed", error_msg)
return {"status": "failed", "error": error_msg}
```
This sits AFTER the pre-existing C16e skip-if-done guard (an already-uploaded video still short-
circuits to "Already uploaded — skipping" before the channel check even runs) and BEFORE any code
that could touch `self._pipeline`.

**Every caller traced** (all funnel through this one method, so the fix is centralized):
- `routes/pipeline.py POST /upload/{video_id}` (manual trigger) — gets `{"status":"failed","error":
  ...}` back, surfaced via the existing `_set_task_status` channel.
- `actions.make_action_step` (chat "upload" verb, and the MCP `upload` tool via
  `routes/mcp.py` → `routes/chat.py::_run_pending_action` → this same factory) — the existing
  `if result.get("error"): break` / `_set_task_status(..., result.get("status"), result.get("error"))`
  loop (unchanged) surfaces it identically to any other stage failure (e.g. a render failure) — no
  special-casing needed.
- `claude_orchestrator.py`'s skill-dispatch map (`"upload": executor.run_upload`) — same dict return,
  same existing handling.
- `worker.py::arq_run_upload` → `_run_stage` — `status=="failed"` path persists the error to
  `background_tasks` and (since it isn't a Kie-block "terminal failure") raises `RuntimeError` so arq
  retries up to `max_tries=3` — harmless (no spend, same as any other non-terminal stage failure
  today; not special-cased further, matching existing convention).
- **Autobuild "finish" chain** (`actions.make_autobuild_step`) — traced in full: `DONE_STATUSES`
  includes `"rendered"` itself, so the finish loop's top-of-iteration check
  (`if target == "finish" and status in DONE_STATUSES: return`) stops BEFORE ever reaching the
  generic `ex.run_next_step(video_id)` fallback for a rendered video — upload was never part of the
  automatic finish chain to begin with (by design: it's a paid, PUBLISHING action, gated behind an
  explicit "upload" verb). `run_next_step`'s status map (`"rendered": self.run_upload`) is still the
  path for `routes/discovery.py`, `routes/queue.py`, `routes/autopilot.py`, and
  `routes/pipeline.py`'s other `run_next_step` call sites — all get the same dict-return handling,
  no changes needed since the fix lives inside `run_upload` itself.

**Route gate (belt-and-suspenders, not the authority).** `routes/pipeline.py`'s
`POST /upload/{video_id}` now checks `channel_profiles.youtube_refresh_token` right after
`_require_stage_enabled` and BEFORE `_is_task_active`/`_set_task_status` — so an unconnected tenant
never claims a task lock for a request that can't succeed. Same copy as the executor
("Connect your YouTube channel first — Settings → YouTube."), `HTTPException(400, ...)`. Explicitly
documented as non-authoritative — an internal caller (chat, MCP, orchestrator, arq) reaches
`PipelineExecutor.run_upload` directly, bypassing this route.

### Legacy package verdict: DELETE (operator-confirmed, not "leave for cron")

Original brief's default was "leave it if only Ryan's own Airtable cron pipeline
(`orchestrator/pipeline.py`) still uses it." Mid-chunk, the operator (Ryan) stated he no longer runs
Power Doctrine or its Slack channel — the prototype that got this project started. That changes the
calculus: the legacy upload bot wasn't protecting a live workflow.

**Deleted** (grep-proofed — nothing else imports these):
`skills/video-pipeline/upload/run.py`, `seo_generator.py`, `youtube_uploader.py`, `manifest.json`.
```
$ grep -rn "upload\.run\b|upload\.seo_generator|upload\.youtube_uploader" --include=*.py .
(no output)
```
**Kept:** `skills/video-pipeline/upload/run_package.py` + `__init__.py` — a DIFFERENT feature living
in the same folder (packages assets for Remotion, called from `render/run.py:113` and
`orchestrator/pipeline.py:1302`'s `package_for_remotion()`), unrelated to YouTube upload/SEO/publish.
Confirmed still reachable:
```
$ grep -rn "package_for_remotion" --include=*.py .
orchestrator/pipeline.py:885:    async def package_for_remotion(self) -> dict:
orchestrator/pipeline.py:1302:        props = await pipeline.package_for_remotion()
render/run.py:113:    props = await pipeline.package_for_remotion()
```
`manifest.json` was scanned by `shared/skill_registry.py` (a `*/manifest.json` glob), but
`get_registry()` is never instantiated anywhere in the repo except its own module docstring —
confirmed dead infrastructure, so deleting the manifest breaks nothing live.

**SaaS backend can no longer reach `skills/video-pipeline/upload/`'s deleted files at all** — not
just "unreachable," literally removed: the `run_upload_bot` closure + its assignment onto the
`LightPipeline` shim (`pipeline_executor.py::_ensure_initialized`, previously lines 6542-6544/6580)
are deleted, since nothing calls `self._pipeline.run_upload_bot` anymore.
```
$ grep -rn "run_upload_bot" --include=*.py .
storyengine/backend/pipeline_executor.py:<docstring line citing the removed shim by name, for history>
storyengine/backend/tests/functional/test_c34a_upload_no_legacy_fallback.py:<the tests proving it's gone>
```
(the legacy cron pipeline's method is named `run_youtube_upload_bot` — a different name, kept as a
stub, see below — not `run_upload_bot`, which was only ever the `LightPipeline` shim's name.)

**Ryan's legacy cron pipeline** (`orchestrator/pipeline.py`) — the stage-10 hookup
(`get_idea_by_status(STATUS_RENDERED)` → `run_youtube_upload_bot`) is removed surgically from
`run_next_step`'s crawler, with an inline comment explaining why (matches this chunk's fix rationale
— same shared-OAuth/Power-Doctrine path StoryEngine had to wall off). A `Rendered` idea in that
pipeline now just falls through to "No work to do" instead of crashing on the deleted import — upload
is a manual (YouTube Studio) step for that pipeline until/unless a replacement is built (a C37-level
product call, not reopened here). `run_youtube_upload_bot` itself is kept, but reduced to a soft-fail
stub (`{"status": "failed", "error": "YouTube upload bot removed (C34a)..."}`) rather than deleted
outright, because `orchestrator/pipeline_control.py:1411`'s Slack `upload`/`run uploads?` command
still calls it directly — deleting the method would turn that (rarely-used, per the operator) Slack
command into an `AttributeError` crash instead of a clean message. The module still imports fine
(`python -m py_compile` clean); `package_for_remotion`'s import of `upload.run_package` is untouched.

### Verify

**Non-vacuous via `git stash`:** full stash of every C34a file change, re-ran the new test file
against pre-fix code — 4 of 8 new tests correctly FAIL (the ones asserting the fallback is gone/route
gate exists), 4 pass unchanged (video-not-found, already-uploaded skip, connected-tenant native path,
route-proceeds-when-connected) — proving the tests exercise the actual fix, not tautologies. Popped
clean, re-ran green (8/8).

**8 new tests** — `tests/functional/test_c34a_upload_no_legacy_fallback.py`: unconnected tenant gets
the clear error and `self._pipeline` (a sentinel that raises on ANY attribute access) is never
touched; `run_upload_bot` no longer exists in `_ensure_initialized`'s source nor is called from
`run_upload`'s executable body (docstring mentions allowed); video-not-found and already-uploaded
skip-if-done still short-circuit correctly (ordering pin); connected-tenant native path unchanged;
`routes/pipeline.py`'s route gate rejects with 400 before claiming a task lock, and passes through
silently when connected.

**Pre-existing `test_c16e_upload_skip_if_done.py`** (11 tests, connected-tenant coverage) — all still
pass unchanged; this chunk did not touch that branch's logic.

**Full backend suite:** `./venv/bin/python -m pytest tests/ -q` → **1249 passed / 15 failed / 1
error** (baseline 1241/15/1 + this chunk's 8 new tests, zero new failures — identical 15
pre-existing failure names, none touching any file this chunk modified).

**Autopilot suite (untouched except the one surgical `orchestrator/pipeline.py` edit, which the
suite doesn't cover):** `cd skills/video-pipeline && python3 -m pytest autopilot/tests/ -q` → **146
passed / 0 failed**, unchanged from the C32b baseline.

`python -m py_compile` clean on every touched/new file (`pipeline_executor.py`, `routes/pipeline.py`,
`orchestrator/pipeline.py`, `orchestrator/pipeline_control.py` (unchanged, compile-checked anyway
since it references the stub), `upload/run_package.py`, the new test file).

**Frontend:** untouched — `git status --short storyengine/frontend/` empty. No `npx tsc --noEmit`
needed (nothing to check); explicitly flagged, not silently skipped.

**Live verification deferred** to `tasks/live-verification-queue.md` §C34a: an unconnected tenant
actually seeing "Connect your YouTube channel first — Settings → YouTube." in the live chat/UI.

### Modified/New/Deleted Files (C34a)
| Path | Change |
|------|--------|
| `storyengine/backend/pipeline_executor.py` | `run_upload`'s no-channel branch returns a clear failure instead of calling `self._pipeline.run_upload_bot()`; deleted the now-dead `run_upload_bot` closure + shim assignment in `_ensure_initialized` |
| `storyengine/backend/routes/pipeline.py` | `POST /upload/{video_id}` gains a connected-channel precondition (400) before the task-lock is claimed |
| `skills/video-pipeline/orchestrator/pipeline.py` | `run_next_step`'s stage-10 upload hookup removed surgically (Rendered now falls through to "No work to do"); `run_youtube_upload_bot` reduced to a soft-fail stub (kept only because `pipeline_control.py` still calls it) |
| `skills/video-pipeline/upload/run.py` | DELETED |
| `skills/video-pipeline/upload/seo_generator.py` | DELETED |
| `skills/video-pipeline/upload/youtube_uploader.py` | DELETED |
| `skills/video-pipeline/upload/manifest.json` | DELETED (described the now-deleted `run.py` entry point; dead metadata, no live loader reads it) |
| `storyengine/backend/tests/functional/test_c34a_upload_no_legacy_fallback.py` | NEW — 8 tests |

### Deploy-safety assessment — ff-merge candidate

Connected-tenant behavior is byte-identical (proven above). An unconnected tenant that would
previously have silently shipped onto Ryan's own channel now gets a clear, safe failure instead —
strictly a bug fix, no legitimate workflow depended on the old fallback (operator-confirmed: Power
Doctrine cron + its Slack channel are retired). The legacy cron pipeline (`orchestrator/pipeline.py`)
still imports and runs fine; its one remaining upload entry point (the Slack command) degrades to a
clear message instead of crashing. Safe to ff-merge; no VPS coordination needed beyond the routine
hourly `git pull --ff-only` (a running video build elsewhere on the VPS is unaffected — this chunk
touches no in-flight generation code).

**Next up: C34b · S10-2/S10-3 voice + Slack de-globalization** — no tenant silently gets Ryan's
cloned ElevenLabs voice (explicit onboarding choice, stock default) and `SlackClient` becomes a no-op
for SaaS tenant runs (tenant content must not post to Ryan's workspace). Then C34c, C35, C36,
C37(Ryan).

## C34b — S10-2/S10-3 fix: voice + Slack de-globalization (added 2026-07-19)

Audit findings §S10-2/§S10-3 (docs/reports/2026-07-17-storyengine-agent-audit-findings.md, C34
sweep). Both bugs share one root shape: SaaS-tenant-reachable legacy bot code
(`skills/video-pipeline/voice/run.py`, `thumbnail/run.py`, `upload/run.py`, etc. — wired onto the
`LightPipeline` shim in `pipeline_executor.py::_ensure_initialized`) reads/writes globals (an env var,
a Slack bot token) that belong to Ryan's own single-tenant identity, with no per-tenant scoping at all.

### S10-2 — the cross-tenant voice leak (the real bug, not just a bad default)

`Models.VOICE_ID` (`pipeline_constants.py:415`) hardcoded Ryan's own ElevenLabs clone
(`G17SuINrv2H9FC6nvetn`) as the literal fallback. Worse: `pipeline_executor.py::_ensure_initialized`
had a `VOICE_CONFIG_KEYS` "restore process-level voice defaults" step (added by the DvsU 2026-07-07
fix, meaning well — "don't drop a tenant's configured voice") that snapshotted
`os.environ["ELEVENLABS_VOICE_ID"]` BEFORE clearing it and restored it whenever a tenant had no vault
override. On the shared storyengine backend process, that snapshot is whatever identity's `.env`
happens to be loaded — i.e. Ryan's own cloned voice — so **any SaaS tenant who skipped the voice step
narrated in Ryan's actual cloned voice.** Confirmed by tracing `vault.get_secret`: with a `tenant_id`,
it NEVER falls back to env vars (by design, security comment in `vault.py`) — so the leak could only
be coming from this executor-level restore, not vault.

**Fix, three parts:**
1. `elevenlabs_voice_id` removed from `VOICE_CONFIG_KEYS` (now `("elevenlabs_model_id",
   "elevenlabs_voice_style")` only — those two are non-identity engine-tuning knobs, kept
   restore-eligible on purpose). `elevenlabs_voice_id` is still LOADED from vault into env (so a
   tenant's own choice reaches `ElevenLabsClient`) — it just never gets the process-default restore.
2. `_ensure_initialized`'s `ElevenLabsClient(...)` construction now passes `voice_id` EXPLICITLY:
   `os.environ.get("ELEVENLABS_VOICE_ID") or STOCK_NARRATOR_VOICE_ID` — resolved fresh, per tenant, at
   construction time. Deliberately bypasses `ElevenLabsClient.DEFAULT_VOICE_ID`/`Models.VOICE_ID`
   entirely for this call site: those are evaluated ONCE at first import in this shared multi-tenant
   process and would freeze in whichever identity's env happened to be set at that moment (a second,
   subtler leak vector — closed by never relying on them here).
3. `STOCK_NARRATOR_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"` (new module constant, `pipeline_executor.py`) —
   ElevenLabs' own premade/stock "Rachel" voice, publicly documented, already used as the onboarding
   placeholder example (`ApiKeysStep.tsx` `KEY_FORMAT_HINTS`). `Models.VOICE_ID`'s literal fallback
   also changed to this same id, for hygiene (covers Ryan's own legacy cron pipeline — a separate
   process/env — if IT ever runs with no `ELEVENLABS_VOICE_ID` set either).

**Onboarding nudge already exists — no UI built this chunk.** `ApiKeysStep.tsx` already renders an
`elevenlabs_voice_id` field ("Voice ID", unmasked, placeholder `21m00Tcm4TlvDq8ikWAM`) under the
ElevenLabs provider card in onboarding, reachable again via Settings → API Keys
(`app/settings/keys/page.tsx`). Follow-up (not this chunk): a friendlier voice-PICKER (browse/preview
ElevenLabs voices) instead of a raw ID paste field — flagged, not built.

**Ryan's own voice is preserved by**: his legacy single-tenant cron pipeline
(`skills/video-pipeline/orchestrator/`, a completely separate process from the StoryEngine SaaS
backend) reads `ELEVENLABS_VOICE_ID` directly from its OWN `.env` — untouched by any of this. For
Ryan's *storyengine tenant* (if he uses the SaaS product himself) to keep his cloned voice there, he
needs his own vault-set `elevenlabs_voice_id` (Settings → API Keys) — same mechanism as any tenant, no
special-casing.

### S10-3 — SlackClient posting tenant content into Ryan's retired channel

`SlackClient` (`shared/clients/slack_client.py`) was "enabled whenever a bot token is present" — no
per-tenant scoping, and reachable from SaaS runs via the same `LightPipeline` legacy-bot wiring
(`voice/run.py`'s `notify_voice_start/done`, plus the two flagged sites in `thumbnail/run.py` and
`upload/run.py`). Per operator decision (`tasks/decisions.md` 2026-07-19): Ryan retired the prototype
channel (C0A9U1X8NSW) entirely — no per-tenant Slack integration is wanted.

**Fix:** notifications are now OPT-IN, not opt-out. `SlackClient.__init__` requires BOTH a bot token
AND `SLACK_NOTIFICATIONS_ENABLED=true` (new env var, default `"false"`) to enable — a token alone is no
longer sufficient. This is a single change at the client's constructor, so it covers every
instantiation site without a per-site audit needed for regressions; a FUTURE legacy stage added to
SaaS reach is silent by default, not opt-out (the "can't regress" design the checklist asked for).

**Every `SlackClient()` instantiation site, and its behavior now:**
| Site | Process | Behavior now |
|------|---------|-------------|
| `storyengine/backend/pipeline_executor.py:6366` | SaaS backend (multi-tenant) | Silent — `storyengine/.env` must never set `SLACK_NOTIFICATIONS_ENABLED` |
| `skills/video-pipeline/autopilot/autopilot.py:99` | Legacy cron | Silent unless `SLACK_NOTIFICATIONS_ENABLED=true` in that pipeline's own `.env` |
| `render/render_video.py:464,537,547` | Legacy cron | Same |
| `autopilot/monitoring/ctr_monitor.py:290` | Legacy cron | Same |
| `analytics/performance_tracker.py:739` | Legacy cron | Same |
| `analytics/osiris/performance_analyzer.py:550`, `title_analyzer.py:560`, `competitor_scraper.py:291` | Legacy cron (Osiris) | Same |
| `competitor_scraper/run.py:84` | Legacy cron | Same |
| `orchestrator/pipeline.py:103,1044` | Legacy cron (main orchestrator) | Same |
| `orchestrator/pipeline_control.py:2897,2940,2988,3036,3345` | Legacy Slack bot process | Same — the Bolt `AsyncApp` itself still needs `SLACK_BOT_TOKEN` to start; these particular follow-up notifications now ALSO need the new flag |
| `discovery/bot.py:153` | Legacy Slack bot process | Same |
| `orchestrator/approval_watcher.py:316` | Legacy cron | Same |
| `infra/test_connections.py:72` | Manual ops diagnostic | Updated to check `client.enabled` first and print a clear "disabled (…)" line instead of crashing on `client.client is None` |

Per the checklist's explicit guidance ("if the ONLY consumers are cron jobs posting to a dead channel,
prefer defaulting the whole client to disabled-unless-env-set... the cron side simply goes quiet
(harmless)") — that is exactly what happens here: every legacy-cron site goes silent by default too,
which matches Ryan's own stated intent ("I don't use ... the Slack channel anymore"), not just the
SaaS-reachable ones. Re-enabling any of them is one env var away if he changes his mind (OPEN C37).

### Verify

**Non-vacuous via `git stash`:** stashed all 6 source-file changes (test file is untracked, unaffected
by stash), re-ran the new test file against pre-fix code — 6 of 12 tests correctly FAIL (the voice
stock-default, cross-tenant-leak-pin, `VOICE_CONFIG_KEYS` source pin, `STOCK_NARRATOR_VOICE_ID`
constant, `pipeline_constants.py` literal, and Slack-disabled-by-default tests); 6 pass unchanged
(tenant's-own-vault-voice, model/style-still-restore, and the three other Slack on/off combinations —
proving those assertions describe pre-existing/orthogonal behavior, not tautologies). Popped clean,
re-ran green (12/12).

**12 new tests** —
`tests/functional/test_c34b_voice_and_slack_tenant_isolation.py`: no-vault-voice-and-no-leaked-env
gets the stock id; tenant's own vault voice wins; the cross-tenant-leak regression pin (simulates a
leaked identity voice already sitting in process env, proves a no-override tenant never receives it,
and that the env var isn't silently restored either); model/style tuning keys still restore from
process default (scope check — only voice_id was removed); `VOICE_CONFIG_KEYS` source pin;
`STOCK_NARRATOR_VOICE_ID` constant pin; `pipeline_constants.py` literal pin; four SlackClient
enabled/disabled combinations (token-only, neither, both, flag-only); `notify()` is a true no-op when
disabled (the actual call shape legacy bot code uses).

**Full backend suite:** `./venv/bin/python -m pytest tests/ -q` → **1261 passed / 15 failed / 1
error** (baseline 1249/15/1 + this chunk's 12 new tests, zero new failures — identical pre-existing
failure/error names, none touching any file this chunk modified).

**Autopilot suite** (touched: `pipeline_constants.py`, `slack_client.py`, `infra/test_connections.py`
all live under `skills/video-pipeline`, imported by autopilot): `cd skills/video-pipeline && python3
-m pytest autopilot/tests/ -q` → **146 passed / 0 failed**, unchanged.

**Legacy `skills/video-pipeline/tests/` suite:** pre-existing environment-only failures/collection
errors on this box (missing `_cffi_backend` for `cryptography`'s rust bindings under system Python,
plus unrelated PIL/image-prompt-marker failures) — confirmed unrelated to this chunk's files (none of
the failing tests reference `slack_client` or `pipeline_constants`'s voice constant; failure messages
are about `16:9 aspect ratio`/`photorealistic` prompt markers and storyboard panel extraction, not
Slack or voice). Not fixed here — pre-existing, out of scope.

`python -m py_compile` clean on every touched/new file (`pipeline_executor.py`, `pipeline_constants.py`,
`slack_client.py`, `infra/test_connections.py`, the new test file).

**Frontend:** untouched — `git status --short storyengine/frontend/` empty. No `npx tsc --noEmit`
needed; explicitly flagged, not silently skipped.

**Live verification deferred** to `tasks/live-verification-queue.md` §C34b: an actual ElevenLabs
listen-check (SaaS tenant with no configured voice really narrates as "Rachel," not Ryan's clone) and
a live Slack-silence check (trigger a SaaS voice/thumbnail run with `SLACK_BOT_TOKEN` present in the
storyengine backend's env and confirm nothing posts).

### Modified/New Files (C34b)
| Path | Change |
|------|--------|
| `storyengine/backend/pipeline_executor.py` | New `STOCK_NARRATOR_VOICE_ID` constant; `VOICE_CONFIG_KEYS` narrowed to `(elevenlabs_model_id, elevenlabs_voice_style)`; `ElevenLabsClient(...)` construction now passes `voice_id` explicitly |
| `skills/video-pipeline/orchestrator/pipeline_constants.py` | `Models.VOICE_ID` literal fallback changed from Ryan's clone id to the stock voice id |
| `skills/video-pipeline/shared/clients/slack_client.py` | `SlackClient.__init__` now requires `SLACK_NOTIFICATIONS_ENABLED=true` in addition to a bot token to enable |
| `skills/video-pipeline/infra/test_connections.py` | `test_slack()` checks `client.enabled` first, prints a clear disabled-reason line instead of an `AttributeError` |
| `.env.example` | Documented `SLACK_NOTIFICATIONS_ENABLED` (default false); annotated Slack section as legacy-cron-only |
| `docs/env-vars.md` | `ELEVENLABS_VOICE_ID` and `SLACK_BOT_TOKEN`/`SLACK_CHANNEL_ID` rows annotated legacy-cron-only; new `SLACK_NOTIFICATIONS_ENABLED` row |
| `storyengine/backend/tests/functional/test_c34b_voice_and_slack_tenant_isolation.py` | NEW — 12 tests |

### Deploy-safety assessment — ff-merge candidate

Ryan's own voice/Slack behavior is unaffected: his legacy cron pipeline reads `ELEVENLABS_VOICE_ID` and
`SLACK_BOT_TOKEN` from its own separate `.env`, and this chunk doesn't touch that env or that process's
control flow beyond the client-level opt-in flag (which he can set for himself if he wants his cron's
Slack notifications back). The SaaS backend gets strictly safer behavior — a tenant with no configured
voice now gets a neutral stock voice instead of a specific person's identity, and no tenant content can
reach Ryan's workspace even if a stray bot token exists in that process's env. No paid path changed, no
migration. Safe to ff-merge; no VPS coordination needed beyond the routine hourly `git pull --ff-only`.

**Next up: C34c · thumbnail/title/category genericization** (S10-4/S10-5/S10-6) — niche-neutral
thumbnail fallback (currently a geopolitical world map template), neutral system-prompt default in
`title_generator.py` (currently hardcodes "Economy FastForward finance channel"), and persisting the
already-computed YouTube category instead of always uploading category 27. Then C35, C36, C37(Ryan).

## C34c — S10-4/S10-5/S10-6 fix: thumbnail/title/category genericization (added 2026-07-19)

Audit findings §S10-4/§S10-5/§S10-6 (docs/reports/2026-07-17-storyengine-agent-audit-findings.md, C34
sweep). Same root shape as C34b: SaaS-tenant-reachable legacy code carrying Ryan's own Economy
FastForward assumptions with no niche-neutral default underneath.

### S10-4 — thumbnail template default was a blind world map

`thumbnail/selector.py::select_template` fell back to Template A (Map + Barrier — a geopolitical
satellite-map visual) UNCONDITIONALLY whenever a video's content matched none of the
person/split/symbolic keyword lists — reachable for any brand-new tenant with no channel thumbnail
history via `pipeline_executor.py::run_thumbnail`'s from-scratch-bot fallback. A cooking or ESL channel
with a video about neither people nor geopolitics would still get a bright satellite map thumbnail.

**Fix, two-signal:** Template A is now reached by (1) `GEO_KEYWORDS` — the video's OWN content is
explicitly geopolitical/macro-economic (map, border, chokepoint, trade route, GDP, reserve currency,
etc. — matches `templates.py`'s existing "best_for" for Template A), checked after person/split/
symbolic exactly where the old blanket default used to sit, or (2) `GEO_NICHE_KEYWORDS` — a
niche-informed fallback consulted ONLY when nothing else matched: the tenant's own niche (`finance`,
`economic`, `geopolit`, `politic`, etc.) still earns Template A even on an ambiguous video. Niche
reaches `select_template` two ways — an explicit `"niche"` key on `video_metadata` (now built by
`thumbnail/run.py`), falling back to a new `CHANNEL_NICHE` env var that `pipeline_executor.py`'s
`_load_prompt_overrides` exports from `IdentityContext.niche` (same cross-package seam pattern as the
existing `VISUAL_STYLE_DESCRIPTION`, since `skills/` can't import the backend). Everything else falls
through to a NEW **Template E (Subject Focus)** — a niche-neutral template (one dominant subject drawn
from the video's own content, no map/country/geopolitics assumption baked into the prompt) added to
`templates.py` + `prompt_builder.py`'s per-template variable-fill guidance. Ryan's legacy channel still
lands on Template A either way (its content is inherently geopolitical AND its niche says so, when a
niche signal is available at all) — the legacy Airtable-only pipeline (no `CHANNEL_NICHE` at all)
reproduces the OLD keyword-only behavior for the content that actually earns it, byte-for-byte.

### S10-5 — TITLE_GENERATION_SYSTEM_PROMPT hardcoded "Economy FastForward, a finance/economics
YouTube channel" + a geopolitics-flavored MANDATORY caps-word vocabulary (PURGE/TRAP/WEAPONIZED/
BLACKLISTED/...). Traced why it looked "unreachable" in practice: `_load_prompt_overrides` always
resolves a non-blank `thumbnail` engine-template override for every StoryEngine tenant (fed to BOTH
`ThumbnailPromptBuilder` and `TitleGenerator` via the same `pipeline.thumbnail_system_prompt` — worth
flagging as a pre-existing mismatch, not fixed this chunk: title generation borrows the *thumbnail*
craft template, not a dedicated `title` one, even though `engine_templates.py` already has a
niche-neutral `title` key sitting unwired in `PROMPT_MAP`'s "intentionally left out for now — Phase 3
wires it" comment). So the hardcoded prompt was dead for every current StoryEngine tenant and live only
for (a) the legacy Airtable-only pipeline, which has no override mechanism at all, and (b) any future
call site that forgets to wire one — the checklist's "unguarded regression trap."

**Fix:** rewrote `TITLE_GENERATION_SYSTEM_PROMPT` niche-neutral in the same style as
`engine_templates.py`'s already-neutral templates — generic "[Subject]" formula shapes (was
"[Country]"), a caps-word rule that says MATCH the register to the video's own content instead of a
fixed branded vocabulary, examples spanning cooking/language-learning/investigation registers. The
mechanical contract (exactly one CAPS word, the JSON schema) is untouched — that's the thumbnail's
yin-yang mechanism, not a niche assumption. `TITLE_FORMULAS` (the opt-in `preferred_formula` examples,
reached by zero live callers today) is left as Ryan's preserved legacy pattern set, same treatment as
`tasks/engine-identity-seeds/power-doctrine.md`. **Bonus fix caught in the same file:** the USER prompt
(not just the system prompt) had `f'Generate a title for this Economy FastForward video:'` hardcoded
UNCONDITIONALLY — this fired on every call regardless of override, meaning every StoryEngine tenant's
title-generation call (Poco a Poco, Designed vs Used, Slow English) was ALSO leaking "Economy
FastForward" into its user turn even with a proper tenant override in the system prompt. Fixed to a
plain `'Generate a title for this video:'`.

### S10-6 — computed YouTube category thrown away, upload always shipped category 27

`youtube_publish.py::generate_and_store_seo` already computes a real `category_id`
(education/entertainment/howto/people/news/science → YouTube's numeric id) from the video's own
title+script via its SEO Claude call, and returns it in its response dict — but the UPDATE right below
only persisted `seo_description`/`seo_tags`/`seo_hashtags`, dropping the category on the floor.
`upload_video_to_youtube` then always passed the hardcoded `_DEFAULT_CATEGORY` ("27" — Education) to
`_do_youtube_upload`, so every tenant's video landed in Education on YouTube regardless of what the SEO
pass determined its real category to be.

**Fix:** new `videos.seo_category_id TEXT` column (migration 102, applied LIVE via Supabase MCP to
`wrromlupsmyzrrcqlucn`, confirmed via `information_schema.columns`) — reuses the exact same
storage/UPDATE pattern as the other three SEO fields, no new table. `generate_and_store_seo` now writes
the computed category into it in the same UPDATE statement. `upload_video_to_youtube` SELECTs it and
passes it through to `_do_youtube_upload` as the real `category_id` argument, falling back to
`_DEFAULT_CATEGORY` only when the column is NULL or blank (SEO never generated, or a video that
predates migration 102) — pure additive, backward-compatible. C16d's skip-if-done guard and C33's
quota guard are both untouched (neither reads/writes category).

### Verify

**Non-vacuous via `git stash`:** stashed all 9 source-file changes (`git stash push -- <files>`, test
files are untracked and unaffected) and re-ran the new tests against pre-fix code: 7 of 19
`thumbnail/tests/` assertions correctly FAIL (the 3 neutral-default-template_e tests, the
`test_preferred_template_override_bypasses_selection` 5-key set check, and 3 of the `title_generator`
de-branding/leak pins), and 3 of 5 `test_c34c_seo_category.py` tests correctly FAIL (persistence +
pass-through — the 2 already-defaults-to-27 tests pass unchanged, as expected, since that fallback
behavior is pre-existing). Popped clean, re-ran green (19/19, 5/5).

**24 new tests** —
`skills/video-pipeline/thumbnail/tests/test_selector.py` (19): unmatched content + no/unmatched niche
→ `template_e` (3 variants: no niche, cooking niche, ESL niche); content-level `GEO_KEYWORDS` still
earns `template_a` even against a contradicting niche; niche-level fallback earns `template_a` on
ambiguous content, both via the explicit `"niche"` key and via the `CHANNEL_NICHE` env-var seam
(mirrors the legacy pipeline's shape — no `"niche"` key at all); a realistic Ryan-style headline still
lands on `template_a`; B/C/D keyword priority unchanged (regression pins); the 5-template registry key
set. `skills/video-pipeline/thumbnail/tests/test_title_generator.py` (5): no branding/geo-caps-word
list literal-text pin; examples span multiple niches with no forced `[Country]`; JSON-schema mechanic
unchanged; default-vs-override precedence; the user-prompt leak regression (proven against a tenant
override, since that's exactly the case that was silently broken). `storyengine/backend/tests/
functional/test_c34c_seo_category.py` (5): category persisted in the same UPDATE as the other SEO
fields; unknown-category still defaults to "27"; upload passes through a stored category; falls back
to "27" on `NULL` and on `""` (both round-trip shapes considered).

`python -m py_compile` clean on every touched/new file. Full backend suite: **1266 passed / 15 failed /
1 error** (baseline 1261/15/1 + this chunk's 5 new backend tests, identical pre-existing
failure/error names — zero new failures). `skills/video-pipeline` thumbnail tests run standalone (no
suite-wide `skills/video-pipeline/tests/` baseline exists to diff against — see C34b's note on the
pre-existing environment-only collection failures there, unrelated to this chunk). Autopilot suite not
re-run — grepped `autopilot/` for `select_template`/`title_generator`/`TEMPLATES`/`thumbnail.selector`:
zero hits, this chunk touches nothing autopilot imports.

**Frontend:** untouched — `git status --short storyengine/frontend/` empty; no new field is consumed
by the frontend today (`generate-seo`'s response is displayed as-is; no `category_id`/`seo_category_id`
reference anywhere in `frontend/src/`), so no wiring gap was created. No `npx tsc --noEmit` needed;
explicitly flagged, not silently skipped.

**Live verification deferred** to `tasks/live-verification-queue.md` §C34c: an actual thumbnail render
for a non-geo/non-person/non-split/non-symbolic video on a tenant with no niche configured (confirm it
really renders Template E's subject-focused look, not a map) and a real upload with a non-Education
category resolved by the SEO pass (confirm the YouTube Studio category actually changes from
Education).

### Modified/New Files (C34c)
| Path | Change |
|------|--------|
| `skills/video-pipeline/thumbnail/selector.py` | `GEO_KEYWORDS`/`GEO_NICHE_KEYWORDS` added; default fallback changed from unconditional `template_a` to niche-informed `template_a` → neutral `template_e` |
| `skills/video-pipeline/thumbnail/templates.py` | New `TEMPLATE_E_SUBJECT_FOCUS` + `template_e` registry entry; docstring updated to five templates |
| `skills/video-pipeline/thumbnail/prompt_builder.py` | `_get_variable_descriptions` branch for `template_e` |
| `skills/video-pipeline/thumbnail/engine.py` | Docstring: `template_a..template_d` → `template_a..template_e` |
| `skills/video-pipeline/thumbnail/run.py` | `video_metadata["niche"]` now sourced from the `CHANNEL_NICHE` env var |
| `skills/video-pipeline/thumbnail/title_generator.py` | `TITLE_GENERATION_SYSTEM_PROMPT` rewritten niche-neutral; user-prompt "Economy FastForward" literal removed; module/class docstrings updated |
| `storyengine/backend/pipeline_executor.py` | `_load_prompt_overrides` exports `CHANNEL_NICHE` env var from `IdentityContext.niche` |
| `storyengine/backend/youtube_publish.py` | `generate_and_store_seo` persists `seo_category_id`; `upload_video_to_youtube` reads it and passes it through to `_do_youtube_upload`, falling back to `_DEFAULT_CATEGORY` |
| `storyengine/backend/migrations/102_videos_seo_category_id.sql` | NEW — `ALTER TABLE videos ADD COLUMN IF NOT EXISTS seo_category_id TEXT` (applied live) |
| `storyengine/schema.sql` | `videos.seo_category_id TEXT` added, documented |
| `skills/video-pipeline/thumbnail/tests/__init__.py`, `test_selector.py`, `test_title_generator.py` | NEW — 19 + 5 tests |
| `storyengine/backend/tests/functional/test_c34c_seo_category.py` | NEW — 5 tests |

### Deploy-safety assessment — ff-merge candidate

Ryan's legacy Template A path is preserved: proven by `test_ryans_legacy_content_still_lands_on_template_a`
(a realistic Economy FastForward-style headline with zero niche info, exactly the legacy Airtable
pipeline's shape, still selects `template_a` via `GEO_KEYWORDS`) and
`test_geopolitics_niche_env_var_fallback_selects_template_a` (the `CHANNEL_NICHE` env-var path). The
migration is purely additive (`ADD COLUMN IF NOT EXISTS`, nullable, no backfill needed — existing rows
read as `NULL` and fall back to the exact old "27" behavior). No paid path changed (SEO generation
already called the same Claude endpoint; this chunk only changed what happens to the category value it
already returns). Safe to ff-merge; no VPS coordination needed beyond the routine hourly
`git pull --ff-only` (the migration is already live on Supabase, independent of the code deploy).

**Next up: C35 · P3.4 Whisper-key friction + Claude tier map single-sourcing.**

## C34d — two micro follow-ups flagged (not fixed) by C34c (added 2026-07-19)

Checklist C34d: both items were explicitly called out as "not fixed this chunk" in C34c's own
report and deferred here.

### 1 — the neutral `title` engine template was wired but unplugged

`engine_templates.py`'s `ENGINE_TEMPLATES["title"]` already existed (Phase 3 promoted it from a thin
scaffold to the real neutral title craft), but `pipeline_executor.py::_load_prompt_overrides`'s
`PROMPT_MAP` omitted `"title"` entirely (its own comment: `"title` is intentionally left out for now —
Phase 3 wires it"`), so `self._pipeline` never got a `title_system_prompt` attribute. The only override
path that reached `TitleGenerator` was `thumbnail/run.py` handing `ThumbnailTitleEngine` a single
`system_prompt_override` (read from `pipeline.thumbnail_system_prompt`), which `ThumbnailTitleEngine`
then fanned out to BOTH `ThumbnailPromptBuilder` (correct) AND `TitleGenerator` (wrong — title silently
inherited the thumbnail visual-director craft template, or whatever tenant/per-video thumbnail override
was set, instead of its own niche-neutral title craft or a future title-specific tenant override).

**Fix, three-file seam:**
- `pipeline_executor.py`'s `PROMPT_MAP` gained `"title": (None, "title_system_prompt")` — no per-video
  column exists for title (same shape as `research`), so precedence is tenant override (a
  `tenant_prompt_defaults` row with `prompt_key='title'`, settable directly today; no onboarding UI
  writes one yet — that's a separate, larger "Generate My Style" 6→7 key expansion, out of scope here)
  > the neutral `title` engine template > None.
- `ThumbnailTitleEngine.__init__` (`thumbnail/engine.py`) gained an independent
  `title_system_prompt_override` parameter, passed to `TitleGenerator` instead of the thumbnail
  `system_prompt_override`. `ThumbnailPromptBuilder` keeps receiving `system_prompt_override` exactly as
  before — the two are now fully decoupled.
- `thumbnail/run.py`'s `ThumbnailTitleEngine(...)` call site now passes
  `title_system_prompt_override=getattr(pipeline, "title_system_prompt", None)` alongside the existing
  `system_prompt_override=getattr(pipeline, "thumbnail_system_prompt", None)`.

Net effect: every StoryEngine tenant's title generation now resolves the niche-neutral `title` engine
template (identity-filled with the channel's own name/niche/audience/voice) by default, instead of
silently borrowing whatever thumbnail craft/override happened to be set. `TITLE_GENERATION_SYSTEM_PROMPT`
(the `TitleGenerator`'s own built-in default, used only when `title_system_prompt_override` is `None`
AND `_load_prompt_overrides` was never called — e.g. a standalone/legacy caller) is unaffected and stays
the C34c-fixed neutral fallback of last resort.

### 2 — `thumbnail/selector.py` keyword lists matched substrings, not words

`PERSON_KEYWORDS`/`SPLIT_KEYWORDS`/`SYMBOLIC_KEYWORDS`/`GEO_KEYWORDS`/`GEO_NICHE_KEYWORDS` were all
checked with a plain `kw in searchable` substring test — `"king" in "talking"` is `True`, so any video
whose text merely contained "talking", "breaking", "viking", etc. would silently earn Template B
(person-focused) with zero actual person content.

**Fix:** each keyword now compiles into a regex anchored with `\b` at the START of the keyword only
(`_compile_keyword_pattern`/`_any_keyword_match` in `selector.py`), not at both ends. Anchoring only the
start blocks the "king"-inside-"talking" class of bug (there is no word boundary between two letters
mid-word) while deliberately preserving every intentional word-stem entry in these lists — `"financ"` →
finance/financial/financing, `"geopolit"` → geopolitical, `"strangl"` → strangling/strangled,
`"weaponiz"` → weaponized, `"assassin"` → assassinate — and plain nouns still match their plurals
(`"agent"` → "agents"). Multi-word phrases (`"prime minister"`, `"who is"`, `"debt trap"`) are
unaffected — the literal phrase, including its internal space, still has to appear, just anchored to a
word start instead of any substring position. `GEO_NICHE_KEYWORDS`' niche-string check got the identical
treatment for consistency (same bug class, same fix).

### Verify

**Non-vacuous via `git stash`** (two separate stashes, since the two fixes are independent and touch
disjoint files):
- Stashed `thumbnail/selector.py` only, kept the new tests: 1 of the 6 new `test_selector.py` assertions
  (`test_king_substring_inside_talking_does_not_trigger_person_template`) correctly FAILS against
  pre-fix code (`template_b` instead of the expected `template_e`); the other 5 new tests plus all 19
  pre-existing tests pass unchanged (none of them exercised the bug). Popped clean, re-ran 25/25 green.
- Stashed `pipeline_executor.py` + `thumbnail/run.py` + `thumbnail/engine.py`, kept the new backend test
  file: all 3 new tests in `test_c34d_title_prompt_wiring.py` correctly FAIL against pre-fix code (no
  `title_system_prompt` attribute at all; the static grep for `title_system_prompt_override=` in
  `run.py` finds nothing). Popped clean, re-ran 3/3 green.

**9 new tests** — `skills/video-pipeline/thumbnail/tests/test_selector.py` (+6): "king"-in-"talking"/
"breaking" no longer trips Template B; a genuine standalone "king" mention still does; the multi-word
phrase `"prime minister"` still matches in full; the word-stem keywords `"financ"`/`"strangl"` still
match their longer forms (`"Financial"`/`"Strangled"`); the plural of a plain-word keyword
(`"agent"`→"agents") still matches; `GEO_NICHE_KEYWORDS`' `"financ"` stem still matches a longer niche
string via the `CHANNEL_NICHE` seam. `skills/video-pipeline/thumbnail/tests/test_engine.py` (NEW file,
3): `ThumbnailTitleEngine`'s `title_system_prompt_override` and `system_prompt_override` reach two
different sub-objects and are never equal when both are set; a thumbnail-only override does NOT leak
into the title generator (regression pin for the exact pre-fix bug); both default to `None`.
`storyengine/backend/tests/functional/test_c34d_title_prompt_wiring.py` (NEW file, 3):
`_load_prompt_overrides` sets `title_system_prompt` to the neutral title template (not the thumbnail
one, not `None`); a `tenant_prompt_defaults` row with `prompt_key='title'` beats the neutral template;
`thumbnail/run.py` statically reads `title_system_prompt` as its own `getattr` call, separate from
`thumbnail_system_prompt`.

`python -m py_compile` clean on every touched/new file. Full backend suite: **1269 passed / 15 failed /
1 error** (baseline 1266/15/1 + this chunk's 3 new backend tests, identical pre-existing failure/error
names — zero new failures). `skills/video-pipeline` thumbnail tests: **28 passed** (19 baseline + 6 + 3
new, standalone run — no suite-wide baseline exists there, see C34b/C34c's note on the pre-existing
environment-only collection failures elsewhere in that tree).

**Frontend:** untouched — `git status --short` shows no `storyengine/frontend/` paths; neither fix
touches an API response shape or a frontend-consumed field, so no `npx tsc --noEmit` was needed
(explicitly checked, not silently skipped).

### Modified/New Files (C34d)
| Path | Change |
|------|--------|
| `storyengine/backend/pipeline_executor.py` | `_load_prompt_overrides`'s `PROMPT_MAP` gains `"title": (None, "title_system_prompt")`; stale "Phase 3 wires it" comment replaced |
| `skills/video-pipeline/thumbnail/engine.py` | `ThumbnailTitleEngine.__init__` gains `title_system_prompt_override`, passed to `TitleGenerator` independently of `system_prompt_override` (still passed to `ThumbnailPromptBuilder`) |
| `skills/video-pipeline/thumbnail/run.py` | `ThumbnailTitleEngine(...)` call site passes `title_system_prompt_override=getattr(pipeline, "title_system_prompt", None)` |
| `skills/video-pipeline/thumbnail/selector.py` | `_compile_keyword_pattern`/`_any_keyword_match` (start-anchored `\b` regex) replace all five keyword lists' plain `in` substring checks |
| `skills/video-pipeline/thumbnail/tests/test_selector.py` | +6 word-boundary regression tests |
| `skills/video-pipeline/thumbnail/tests/test_engine.py` | NEW — 3 tests for the title/thumbnail override decoupling |
| `storyengine/backend/tests/functional/test_c34d_title_prompt_wiring.py` | NEW — 3 tests for the `PROMPT_MAP`/`title_system_prompt` wire |

### Deploy-safety assessment — ff-merge candidate

Both fixes are pure behavior corrections with no schema change and no new paid call site (title
generation still makes exactly the same one Claude call per video; selector.py is a pure in-process
keyword match, not a network call). The title fix can only ever REDUCE how often title generation
borrows an unrelated (thumbnail) prompt — the new template only wins when the resolved thumbnail-borrow
would previously have applied, and per-video/tenant title overrides (once the onboarding UI adds a 7th
key) will always win over it, matching every other prompt key's precedence. The selector fix can only
ever REDUCE false-positive Template B/C/D/A matches (word-boundary anchoring is a strict subset of plain
substring matching) — proven no real keyword occurrence regresses via the 3 word-stem/plural/phrase
tests above. Safe to ff-merge; no VPS coordination needed, no migration to run.

## C35 — P3.4 Whisper-key friction + Claude tier map single-sourcing (added 2026-07-19)

Two independent P3.4 audit findings (docs/reports/2026-07-17-storyengine-agent-audit-findings.md
Sweep 2 findings 4/5; tasks/storyengine-wiring-fix-checklist.md §3.4).

### Whisper-key friction — traced, then fixed at the actual silent-failure point

Traced today's live keyless-tenant behavior before touching anything: the only real Whisper
(OpenAI) call site left in the codebase is `skills/video-pipeline/render/audio_sync/transcriber.py`,
used by the legacy Airtable-cron pipeline's `render/run_audio_sync.py` stage. StoryEngine SaaS's
three real render paths (`render_perform.py`, `render_static.py`, `render_stitch.py`) never call
Whisper at all — captions/word-timing simply aren't wired into the SaaS render engine today, so
`routes/pipeline.py`'s existing "pipeline still runs without it" readiness hint (the C04 soft-hint
precedent, `PIPELINE_OPTIONAL_KEYS`) is actually accurate for those paths, left unchanged.

The REAL bug was in `run_audio_sync.py` itself: when `OPENAI_API_KEY` is missing (or every scene's
transcription otherwise fails), the per-scene `except Exception: continue` swallowed the error,
and the function still returned a "bot": "Audio Sync" dict with NO `"error"` key and 0
`duration_updates` — every caller (the Slack `sync` command, the direct `pipeline.run_audio_sync()`
call) reported this as **success**, matching the exact silent-failure symptom already documented in
docs/failure-modes.md ("Audio alignment fails ... 3s uniform durations").

Fix — smallest honest improvement, no new paid integration (Kie has no confirmed Whisper-equivalent
in this codebase, so `[B]` routing through Kie wasn't feasible; C04's graceful-degradation precedent
followed instead):
- `transcriber.py` gains `is_configured()` — single source of truth for "can Whisper run at all."
- `run_audio_sync.py` now (a) fails FAST with a clear `{"error": ...}` + a Slack notification the
  moment the key is missing/placeholder, before burning time on Drive downloads or doomed API
  calls, and (b) after the per-scene loop, if `duration_updates == 0` (every scene failed for ANY
  reason), returns a clear error instead of writing `render_config.json` and claiming success.

### Claude tier map — single-sourced

Traced ~15 independent call sites across storyengine/backend hardcoding the same Claude
smart/fast tier ids (`routes/chat.py` ×3, `routes/videos.py` ×2, `routes/model_video.py`,
`routes/pipeline.py`, `routes/script_templates.py`, `routes/discovery.py`,
`routes/system_prompts.py`, `routes/youtube_channel.py`, `producer_prompt.py`, `static_docu.py`,
`identity_builder.py`, `user_script.py`, `originality.py`, `youtube_publish.py`,
`claude_orchestrator.py`, `distillation/distiller.py`, `distillation/meta_analyzer.py`,
`render_static.py`, `scripts/coverage_to_app.py` ×5, `kie_unified.py`'s own
`AnthropicDirectClient.generate` default) instead of one shared map. Three of those independent
copies (`claude_orchestrator.DECISION_MODEL`, `routes/system_prompts.py`,
`routes/youtube_channel.py`, plus `kie_unified.AnthropicDirectClient`'s own default parameter) had
drifted to a stale `"claude-sonnet-4-20250514"` id that **404s on the live Anthropic API today**
(confirmed by a pre-existing comment in `producer_prompt.py`) — a genuine live bug fixed alongside
the consolidation, not just duplication.

Single source: `shared/channel_profile.py::CLAUDE_MODELS` (next to `MODEL_REGISTRY`, mirroring the
C09 single-price-source pattern) + `claude_model_for_direct_client(client, tier="smart")` (replaces
the repeated `"claude-sonnet-4-6" if type(client).__name__ == "AnthropicDirectClient" else None`
idiom). `storyengine/backend/actions.py` re-exports both (same re-export pattern as `CLIP_COST`
etc.); every one of the ~20 call sites above now imports from there instead of carrying its own
literal. `kie_unified.py`'s `CLAUDE_MODEL_ALIASES` translation table and `canaries/validator_drift.py`
/`canaries/vision_drift.py`'s pinned probe strings are deliberately NOT folded in (documented in
`channel_profile.py`'s own comment) — different concerns (a compat shim for old ids; drift canaries
that must pin a version on purpose).

Regression pin: `storyengine/backend/tests/functional/test_c35_claude_tier_single_source.py` — (1)
the map's shape/values, (2) `actions.py`'s re-export, (3) a static AST-based audit walking every
`.py` file under `storyengine/backend` for the canonical literal strings, allowlisting only
`kie_unified.py` and `canaries/*.py`. Non-vacuous: reverting the source (keeping only the new test)
fails all 3 assertions, listing all ~30 duplicate/stale sites.

### Verify

**Non-vacuous via `git stash`** (two separate stashes):
- Stashed the Whisper fix files only, kept the new test file: 7 of 9
  `test_run_audio_sync_keyless.py` assertions correctly FAIL against pre-fix code (missing/placeholder
  key silently "succeeds" with 0 durations; all-scenes-failed also silently "succeeds"). Popped clean,
  re-ran 9/9 green, full `render/audio_sync/tests/` suite 61/61.
- Stashed all ~20 tier-map consumer files (kept `test_c35_claude_tier_single_source.py`): all 3
  assertions fail (map doesn't exist; `actions.py` doesn't re-export it; the static audit finds ~30
  literal-hardcoding sites). Popped clean, re-ran 3/3 green.

One test needed updating, not just adding: `tests/functional/test_learn_voice.py` pinned the OLD
stale `"claude-sonnet-4-20250514"` id as the expected request body model — updated to assert against
`CLAUDE_MODELS["anthropic"]["smart"]` (the bug-fixed value), with a comment explaining why.

**Full backend suite:** `./venv/bin/python -m pytest tests/ -q` → **1272 passed** (1269 baseline + 3
new tier-map tests) **/ 15 pre-existing failures / 1 pre-existing error** — matches the documented
baseline exactly, zero new failures. `skills/video-pipeline` autopilot suite: **146/0** (unaffected —
`channel_profile.py` only gained new symbols, nothing removed/changed). `py_compile` clean across all
~27 touched files.

**Frontend:** untouched — no `storyengine/frontend/` paths in `git status --short`.

### Modified/New Files (C35)
| Path | Change |
|------|--------|
| `skills/video-pipeline/render/audio_sync/transcriber.py` | + `is_configured()` |
| `skills/video-pipeline/render/run_audio_sync.py` | Upfront key-check (fail fast with error + Slack notify); post-loop `duration_updates == 0` guard (never silently "succeed" with 0 timed images) |
| `skills/video-pipeline/render/audio_sync/tests/test_run_audio_sync_keyless.py` | NEW — 9 tests |
| `skills/video-pipeline/shared/channel_profile.py` | + `CLAUDE_MODELS` dict, `claude_model_for_direct_client()` |
| `storyengine/backend/actions.py` | Re-exports `CLAUDE_MODELS`, `claude_model_for_direct_client` |
| `storyengine/backend/{routes/chat.py, routes/videos.py, routes/model_video.py, routes/pipeline.py, routes/script_templates.py, routes/discovery.py, routes/system_prompts.py, routes/youtube_channel.py, producer_prompt.py, static_docu.py, identity_builder.py, user_script.py, originality.py, youtube_publish.py, claude_orchestrator.py, distillation/distiller.py, distillation/meta_analyzer.py, render_static.py, scripts/coverage_to_app.py, kie_unified.py}` | Hardcoded Claude tier literal replaced with the single-source import; `kie_unified.AnthropicDirectClient.generate`'s default `model` param now resolves lazily instead of defaulting to the stale 404ing id |
| `storyengine/backend/tests/functional/test_learn_voice.py` | Updated stale-id assertion to the bug-fixed canonical value |
| `storyengine/backend/tests/functional/test_c35_claude_tier_single_source.py` | NEW — 3 tests (shape/values, re-export, static no-duplication audit) |

### Deploy-safety assessment — ff-merge candidate

Both fixes are behavior corrections with no schema change and no new paid integration. The Whisper
fix can only ever turn a previously-silent "success" into a clear, correctly-labeled failure — no
path that worked before now fails, and no path that failed before now silently "succeeds." The tier
map fix is a pure refactor for ~17 of the ~20 sites (identical literal value, single source instead
of N copies) plus a genuine bug fix for the 4 stale-id sites (`claude_orchestrator.py`,
`routes/system_prompts.py`, `routes/youtube_channel.py`, `kie_unified.AnthropicDirectClient`'s
default) that were confirmed 404ing — fixing a confirmed-broken call can only improve those code
paths, never regress a working one. Safe to ff-merge; no VPS coordination needed, no migration to
run.

## C36 — P3.3 UX debt batch: checkpoint-audio, cold-start card, budget ceiling, confidence telemetry (added 2026-07-19)

Four independent findings from the copilot-flow audit (docs/reports/2026-07-17-storyengine-agent-
audit-findings.md Sweep 1, findings 3/6/7/8; tasks/storyengine-wiring-fix-checklist.md §3.3). This is
the final BUILD chunk of the loop — C37 is Ryan's decision chunk (create-surface convergence, per-user
BYOK), composed by the orchestrator, not built here.

### Item 1 — checkpoint-audio expectation

The pictures-review checkpoint (`actions.make_autobuild_step`'s target="pictures" stop) deliberately
defers voice to the finish phase (voice is the slowest paid step, not needed to review pictures) — but
two surfaces implied audio should already be there:

1. `actions.PICTURES_READY_MSG` said only "review them, then say animate it" — never mentioning voice
   isn't there yet. Fixed: now reads "review them (no voice yet, that's next), then say...".
2. `ScenesWorkspaceTab.tsx`'s hard gate (`!hasVoice && !voiceSkipped` → a blocking "Voice Required"
   card) didn't distinguish "no pictures yet, voice hasn't run" from "pictures exist, voice is
   deliberately deferred" — a video built via the default chat autobuild (pictures made, voice not yet
   run, `skip_voice` false) hit the SAME hard block reviewing pictures the chat had just told the
   creator to go review. Fixed: the gate now only blocks when `!hasPictures` too; when pictures exist
   without voice, an inline advisory banner replaces the block ("No voice yet — that's expected here...
   review the visuals now, audio comes next").

### Item 2 — cold-start card

A fresh conversation with zero competitor data (`routes/chat.py`'s proactive-idea-pitch branch in
`chat_turn()`) silently fell to the generic "dragon video" `_GREETING` forever — no way out. Fixed:
when `_recent_competitor_rows()` is genuinely empty (NOT when it's empty because of a missing
Anthropic key — that's P0.4's territory, and a competitors card would be misleading there), the
greeting now carries a one-tap `_add_competitors_card()` ("Add 3 competitors now" / "Not now — give me
examples"). The follow-up turns (card tap, then the URL paste) are handled by a new standalone
`_handle_cold_start_competitor_followup()` — extracted as its own function (not left inline in
`chat_turn()`) specifically so it's independently testable, reusing the SAME
`analyze_competitors`/`_parse_urls` calls the onboarding "competitors" step already uses, WITHOUT
routing through the onboarding step machine (`state["onboarding_step"]`) — this fires for an
already-onboarded creator who simply never added competitors, so re-triggering connect_yt/
connect_drive/upsell would be a regression, not a fix.

### Item 3 — budget ceiling (the substantial item)

`videos.max_spend` — an OPTIONAL, nullable per-video spend cap (migration 103, applied LIVE via
Supabase MCP against `wrromlupsmyzrrcqlucn`, confirmed via `information_schema.columns`, committed to
`schema.sql` next to `total_cost`). NULL (the default) is byte-identical to every video that existed
before this migration — nothing reads/writes it unless a creator sets one.

**One column, three doors** (per the design note):
1. **Existing video-update path** — `routes/videos.py`'s generic `PATCH /api/videos/{id}` (`allowed_
   fields`), validated (must be a positive number or `null` to clear).
2. **UI field** — `BudgetCapCard` in `ScriptVoiceTab.tsx` (next to `ScriptVoiceCard`, same
   GlassCard/PATCH pattern), showing real spend-so-far (`video.total_cost`) alongside the cap input.
3. **Chat verb** — new `budget_cap` verb (free, no confirm — like `camera_preset`/`script_profile`):
   "cap this video at $15" / "remove the cap", parsed by `actions._resolve_budget_cap_text()`, written
   by `actions._runner_budget_cap()`. Wired into both classifiers' prompts (the legacy one-shot
   classifier in `routes/chat.py` AND `agent_brain.py`'s tool-loop brain) and `routes/mcp.py`'s
   dynamically-generated tool list (auto-picked up since it's a `paid: False` `actions.ACTIONS` entry).

**The gate**: `actions.budget_check(summary, quote_cost)` — pure function, no DB. Returns `None` when
there's no cap or the quote fits under it; otherwise a dict with `cap`/`spent`/`quote`/`projected`/
`message`. `spent` reads `summary["total_cost"]` — the REAL `generation_ledger` rollup (C07/C08),
newly added to `video_summary()`'s SELECT alongside `max_spend` — deliberately NOT the existing
`summary["spent"]` key (the artifact-count estimate every other caller already reads), to avoid
regressing legacy videos that accrued real spend before the C07 ledger existed and were never
backfilled (which would read as total_cost=$0 for them).

**Never silent-blocks** (the money-gate philosophy: quote honestly, let the human decide):
- `routes/chat.py`'s paid-verb confirm-card path folds `budget_warning` into the SAME one-tap card —
  the "yes" option relabels to "Do it anyway · $X" and a `budget` key rides the payload; tapping it IS
  the explicit override, no second confirmation step invented. Omitted entirely (byte-identical card)
  when there's no cap or the quote fits.
- `routes/mcp.py`'s quote response carries the same `budget_warning` key; the confirm_token is still
  minted (the agent isn't blocked), it's just told first.
- `actions.make_autobuild_step()`'s loop checks `video.get("max_spend")` against `video.get(
  "total_cost")` at the top of every iteration (before that iteration's paid step) AND before the
  pre-loop "finish" voice pass — already-at/over-cap pauses cleanly (task status "completed", a
  message naming the cap and spend, "say keep going to continue" — mirroring the existing no-progress/
  18-iteration-cap stop pattern, not a failure). No per-iteration quote exists at this granularity
  (each iteration can be a different-priced stage), so the honest check available here is "have we
  already reached the cap" rather than "would this specific step exceed it" — documented as the
  deliberate distinction from the confirm-card path's precise quote+total check.

### Item 4 — confidence telemetry

`COPILOT_CONFIDENCE = 0.55` (`routes/chat.py`) gates every copilot classification (from either
`agent_brain.run_copilot_brain()` or the legacy one-shot fallback) with zero visibility into real
traffic — no way to tell whether 0.55 is even the right number without guessing. Smallest useful fix:
`routes/chat._log_classification_confidence()` writes ONE row per classified turn — a `logger.info`
line plus an INSERT into the EXISTING `bot_activity` table (no new table: `bot_name='copilot_
classifier'`, a compact `kind=... verb=... confidence=... source=... gated=...` message on the same
`message` column every other bot's activity rows already use) — called in `_handle_copilot()`
immediately after the classifier decision is unpacked, BEFORE the confidence-gate branch, so a turn
that gets stuck in the clarify-loop is recorded too, not just the ones that pass. Deliberately fail-
soft (a broken telemetry write must never break a chat turn) and deliberately NOT a dashboard — out
of scope this chunk, per the checklist ("no dashboards this chunk").

### Verify

**Non-vacuous via `git stash`**: stashed the 5 modified backend `.py` files (`actions.py`,
`agent_brain.py`, `routes/chat.py`, `routes/mcp.py`, `routes/videos.py`; schema.sql included, new
migration/test files kept), reran the 3 new C36 test files: **24 of 27 assertions correctly FAIL**
against pre-C36 code (`AttributeError`s for every new function/verb that doesn't exist yet, a stale
`PICTURES_READY_MSG` with no voice mention, a `_confirm_card`/mcp quote with no budget key). The 3
incidental passes are the "no cap set" / "under cap" autobuild/card paths, which are supposed to be
byte-identical to before — passing them pre-fix is correct, not vacuous. Popped clean, reran green.

**Cap-gate matrix** (`test_c36_budget_cap.py`, 16 tests): `test_video_detail_model_and_get_video_
query_carry_max_spend` (the wiring lock — caught a REAL bug live: `GET /api/videos/{id}` uses
`response_model=VideoDetail`, a strict Pydantic model that silently drops undeclared DB columns, and
its own SELECT is an explicit column list, not `SELECT *` — both needed `max_spend` added by hand or
the whole UI door would always read null; fixed in `models.py` + `routes/videos.py` in this same
chunk); `test_budget_check_no_cap_is_byte_identical_none` / `test_budget_check_under_cap_returns_none`
/ `test_budget_check_would_exceed_surfaces_the_breach` / `test_budget_check_exactly_at_cap_is_not_a_
breach` (the pure gate); `test_resolve_budget_cap_text_*` / `test_runner_budget_cap_sets_and_clears` /
`test_budget_cap_verb_registered_free_no_confirm` (the chat verb); `test_confirm_card_carries_budget_
warning_when_present` / `test_confirm_card_omits_budget_key_when_no_warning` (the card); `test_
autobuild_pauses_cleanly_when_at_or_over_cap` / `test_autobuild_under_cap_proceeds_normally` / `test_
autobuild_no_cap_is_byte_identical_to_before` (the loop — the actual cap-gate matrix); `test_mcp_
quote_carries_budget_warning` (the MCP door).

**Confidence telemetry** (`test_c36_confidence_telemetry.py`, 4 tests): writes one `bot_activity` row
with the right fields; records ungated/legacy turns too, not just gated ones; fails soft on a broken
DB write; source-lock confirms the log call sits BEFORE the confidence-gate branch in `_handle_
copilot()`.

**Cold-start + checkpoint-audio** (`test_c36_cold_start_and_checkpoint_audio.py`, 8 tests): the
checkpoint message mentions voice; the add-competitors card shape; all 6 states of the follow-up
handler (not-awaiting passthrough, skip, add→collecting, collecting+no-URLs re-prompt, collecting+URLs
→ analyze+clear, stale-value fallthrough).

**Migration proof**: `apply_migration` (idempotent `ADD COLUMN IF NOT EXISTS`) against
`wrromlupsmyzrrcqlucn`, confirmed via `information_schema.columns` (`max_spend | numeric | YES`
nullable). `schema.sql` updated in the same commit.

**Full backend suite**: `./venv/bin/python -m pytest tests/ -q` → **1300 passed** (1272 baseline + 28
new C36 tests) **/ 15 pre-existing failures / 1 pre-existing error** — matches the documented baseline
exactly, zero new failures. `py_compile` clean on all touched `.py` files. `npx tsc --noEmit` clean
(frontend: `ScenesWorkspaceTab.tsx`, `ScriptVoiceTab.tsx`, `lib/api.ts`).

### Modified/New Files (C36)

| Path | Change |
|------|--------|
| `storyengine/backend/migrations/103_videos_max_spend.sql` | NEW — `ALTER TABLE videos ADD COLUMN IF NOT EXISTS max_spend NUMERIC` |
| `storyengine/schema.sql` | `videos.max_spend NUMERIC` added next to `total_cost` |
| `storyengine/backend/actions.py` | `PICTURES_READY_MSG` mentions voice deferral; `video_summary()` selects/returns `total_cost`/`max_spend`; new `budget_check()`, `_resolve_budget_cap_text()`, `_runner_budget_cap()`; new `budget_cap` ACTIONS/RUNNERS entry; `make_autobuild_step()`'s loop + pre-loop voice pass both check the cap before spending |
| `storyengine/backend/routes/chat.py` | `_confirm_card()` accepts `budget_warning`; paid-verb path computes it via `_budget_check`; classifier prompt + JSON schema gain `budget_cap`; new `_log_classification_confidence()` called in `_handle_copilot()`; new `_add_competitors_card()` + `_handle_cold_start_competitor_followup()`, wired into `chat_turn()`'s fresh-conversation branch and a new §3.7 step |
| `storyengine/backend/agent_brain.py` | Decision schema + verb-meanings text gain `budget_cap` |
| `storyengine/backend/routes/mcp.py` | Quote response carries `budget_warning`; docstring/tool-schema text updated for `budget_cap` |
| `storyengine/backend/routes/videos.py` | `PATCH /api/videos/{id}` allowlists + validates `max_spend`; `GET /api/videos/{id}`'s explicit SELECT column list now names `max_spend` (caught live — was silently dropped otherwise) |
| `storyengine/backend/models.py` | `VideoDetail.max_spend: Optional[float] = None` (without this, `response_model=VideoDetail` silently drops the column from every API response) |
| `storyengine/frontend/src/components/production/ScenesWorkspaceTab.tsx` | "Voice Required" gate now checks `hasPictures`; new inline advisory banner when pictures exist without voice |
| `storyengine/frontend/src/components/production/ScriptVoiceTab.tsx` | New `BudgetCapCard`, rendered next to `ScriptVoiceCard` |
| `storyengine/frontend/src/lib/api.ts` | `VideoDetail.max_spend?: number \| null` |
| `storyengine/backend/tests/functional/test_c36_budget_cap.py` | NEW — 16 tests |
| `storyengine/backend/tests/functional/test_c36_confidence_telemetry.py` | NEW — 4 tests |
| `storyengine/backend/tests/functional/test_c36_cold_start_and_checkpoint_audio.py` | NEW — 8 tests |

### Deploy-safety assessment

All four items are additive/opt-in: `max_spend` defaults to NULL (no behavior change until a creator
sets one); the confidence-telemetry write is a fail-soft side effect with no user-visible change; the
cold-start card only appears when there's genuinely zero competitor data (never on an existing/working
path); the checkpoint-audio fix only WIDENS when the Scenes tab renders (adds a bypass + advisory,
narrows nothing). No path that worked before now fails. Safe to ff-merge; no VPS coordination needed
beyond the already-applied migration (which is idempotent and was applied live this chunk).

**Deferred to `tasks/live-verification-queue.md` §C36**: live end-to-end proof (set a cap via chat,
hit it mid-autobuild on a real tenant, confirm the pause card and the "Do it anyway" confirm-card
wording render correctly in the actual UI/dock).

**BUILD queue complete after this chunk. Next up: C37 — Ryan's decision chunk (create-surface
convergence, per-user BYOK slice), composed by the orchestrator, not built by a worker session.**

---

## C40 — P4.1a Channel DNA digest data model: provenance envelope on `channel_identity` (added 2026-07-19)

First build chunk of Phase 4 (Channel DNA ingestion, decisions.md 2026-07-19 "Phase 4 Pillar 1").
Storage discipline every later ingestion chunk (C41-C45) builds on — no ingestion orchestration, no
UI, no chat changes here.

### The problem: 3 writers, 2 merge styles, 0 provenance

`channel_profiles.channel_identity` JSONB (migration 070) is written by THREE different call sites,
each its own way:
- `identity_builder.build_channel_identity` — a full rebuild of voice/hook/structure/research/
  thumbnail_style from the channel's own top videos, written with a **blind overwrite**
  (`channel_identity = $3`) that silently erased whatever channel_format or the thumbnail-formula
  cache had written.
- `channel_format.set_channel_format` — chat-driven visual_format/format_locked edits, via a SQL
  `INSERT ... ON CONFLICT DO UPDATE ... COALESCE(...) || $2::jsonb` merge (fine for its own field,
  blind to any envelope).
- `pipeline_executor._run_channel_formula_thumbnail`'s thumbnail_blueprint cache — the same kind of
  SQL `||` merge, best-effort (wrapped in try/except, "cache is a bonus").

No record of WHO set a field, WHEN, or what it replaced. `identity.py::build_identity_context` was
named in the chunk brief as a reader to guard, but it turns out its SQL never selects
`channel_identity` at all (it reads `channel_name`/`niche`/`target_audience`/`style_description`/
`frameworks` off channel_profiles directly) — so it was already structurally safe; pinned with a test
so a future refactor can't start leaking the envelope through it.

### The fix: one shared helper, three migrated writers

New `storyengine/backend/channel_dna_meta.py` — the ONE place that mutates the JSONB from now on:
- `stamp_identity_write(identity, fields, learner, confidence=None) -> dict` — read-modify-write
  merge. Core contract (quoting the module): *"every field NOT passed in `fields` (including ones
  from a DIFFERENT writer ...) is preserved byte-for-byte; the envelope itself (`_sources`,
  `_history`) is preserved and extended, never clobbered; a write can never smuggle new content INTO
  the envelope keys."* Adds `_sources: {field: {learner, at, confidence}}` (stamped for every touched
  field, even a no-op re-confirmation) and appends one `_history` entry (`{at, learner,
  fields_changed, previous}`) only when a value actually changed, capped at `HISTORY_LIMIT = 20`
  (oldest dropped first).
- `field_provenance(identity, field)` / `restore_field(identity, field, history_index)` — read one
  field's provenance, or undo a specific historical change (itself stamped `learner="restore"`, so
  it's provenance-tracked and reversible in turn).
- `coerce_identity(raw)` — the asyncpg-no-codec JSONB-as-string normalizer, deduplicated out of
  `channel_format._identity` and reused by every writer.

All three writers now fetch the current `channel_identity`, call `stamp_identity_write`, and do a
plain `channel_identity = $N::jsonb` UPDATE with the merged result (Python-side merge replaces the
old SQL `||`/blind-overwrite approaches). `pipeline_executor`'s cache write was extracted to a
module-level `_cache_channel_thumbnail_blueprint()` function (was inline in a method) so it's
independently unit-testable without invoking the surrounding thumbnail-generation method.

### Verify

19 new tests in `storyengine/backend/tests/test_channel_dna_meta.py`: helper unit tests (stamp/
provenance/restore/history-bound/full identity_builder-shaped write), a reader byte-identity test
(`build_identity_context_from_rows` produces an identical `IdentityContext` with or without an
envelope-carrying `channel_identity` key on the row), and one merge test PER real writer
(monkeypatched `fetch_one`/`execute`, no live DB) proving each one's update preserves the OTHER two
writers' fields + provenance + history. Non-vacuous: `git stash` of the three modified writer files
(keeping the new helper + test file) reproduces exactly 3 failures (the per-writer merge tests) and
16 passes (the pure-helper/reader tests, unaffected by the writers) — confirmed live.

**Full backend suite**: `./venv/bin/python -m pytest tests/ -q` → **1319 passed** (1300 baseline + 19
new C40 tests) **/ 15 pre-existing failures / 1 pre-existing error** — matches the documented
baseline exactly, zero new failures. `py_compile` clean on all touched `.py` files.

### Modified/New Files (C40)

| Path | Change |
|------|--------|
| `storyengine/backend/channel_dna_meta.py` | NEW — `stamp_identity_write`, `field_provenance`, `restore_field`, `coerce_identity` |
| `storyengine/backend/identity_builder.py` | `build_channel_identity`'s final write now fetches current `channel_identity`, merges via `stamp_identity_write`, writes `$3::jsonb` instead of a blind `$3` overwrite |
| `storyengine/backend/channel_format.py` | `_identity()` now delegates to `coerce_identity`; `set_channel_format` fetches the FULL current identity (not just the format sub-fields), merges via `stamp_identity_write`, writes a plain `$2::jsonb` (SQL `||` merge removed — Python already merged) |
| `storyengine/backend/pipeline_executor.py` | New module-level `_cache_channel_thumbnail_blueprint()` (above `class PipelineExecutor`) replaces the inline SQL `||` cache write in `_run_channel_formula_thumbnail` |
| `storyengine/backend/tests/test_channel_dna_meta.py` | NEW — 19 tests |

### Deploy-safety assessment

No new table, no migration (JSONB shape change only, per checklist C40 `[D]`) — nothing to apply on
deploy. All three writers' PUBLIC behavior is unchanged (`set_channel_format` still returns the same
`fmt` dict, `build_channel_identity` still returns the same `identity` dict, the thumbnail cache still
caches the same blueprint string) — only the JSONB actually persisted grows two extra top-level keys
that every real reader already ignores structurally (they pluck specific known keys, never iterate).
Existing rows with no `_sources`/`_history` keys degrade gracefully (`coerce_identity`/
`stamp_identity_write` treat a missing envelope as empty and start one on the next write) — no
backfill needed. Frontend untouched (backend-only diff, confirmed via `git diff --stat`). Safe to
ff-merge.

**Next chunk: C41 · P4.1b unified ingestion orchestrator** (`channel_dna.py::learn_channel` sequencing
the existing learners) — see `tasks/todo.md` handoff.

---

## C41 — P4.1b unified Channel-DNA ingestion orchestrator: `channel_dna.py::learn_channel` (added 2026-07-19)

Second build chunk of Phase 4 Pillar 1. Sequences the EXISTING channel-DNA learners behind one
function — no new learner logic, this is refactor-to-call + sequencing + concurrency safety + a
digest-ready result contract for C42 (the chat front door). Builds on C40's provenance envelope.

### What `learn_channel` does

`storyengine/backend/channel_dna.py::learn_channel(tenant_id, *, channel_url=None,
example_script_text=None, reference_video_url=None, progress_cb=None) -> dict`, five steps, all
fail-soft except the claim itself:

| Step | Reuses | Runs when | Fail-soft behavior |
|------|--------|-----------|---------------------|
| 1. import | `routes.onboarding._import_channel_videos` (now returns a saved-count instead of `None` — the one signature change, backward-compatible since its only other caller discards the return value) | `channel_url` given (own channel or not — idempotent ON CONFLICT upsert either way) | zero videos found -> `failed`, sequence continues |
| 2. identity_builder | `identity_builder.build_channel_identity` unmodified | always | transcript fetch / LLM failure -> `failed` with the reason, other steps still run |
| 3. script_template | `routes.script_templates.analyze_and_save_template` unmodified | `example_script_text` given | too-short example / bad analysis -> `failed`; a pre-check query (`SELECT id FROM script_templates ...`) run BEFORE the call distinguishes "replaced your house template" from "saved your first one" (the function itself DELETEs first, so post-hoc you can't tell) |
| 4. channel_format | `channel_format.set_channel_format` unmodified | always, gated by CONFIDENCE not by caller input | locks only when identity_builder detected both `style` AND `motion` across >= 2 analyzed videos (`_format_confident`) — otherwise `skipped` with the detection surfaced unlocked, since `channel_format.apply_format_defaults` reads the lock unconditionally on every future bare-title build |
| 5. reference_video | `routes.model_video._parse_youtube_id` / `_resolve_claude_creds` / `_extract_video_info` (via `routes.niche`) / `_oembed_fallback` / `_fetch_transcript_supadata` / `_distill_dna`, all unmodified | `reference_video_url` given | any extraction/credential/distill failure -> `failed`; on success, folds `{summary, structured_metadata, source_url, source_title}` into a NEW `reference_video_style` field via `channel_dna_meta.stamp_identity_write(..., learner="reference_video")` — closes the audit finding that Model A Video's DNA never persisted past the one video it modeled |

### Concurrency: channel-level claim (migration 104 + `generation_claims.py` additions)

C40's decisions.md note flagged the read-modify-write race on `channel_identity` as future work "once
C41's ingestion orchestrator can run" — this chunk closes it. `generation_claims` (C16a) is video-keyed
(`video_id NOT NULL`), but `learn_channel` operates on a whole tenant, no single video. Rather than a
parallel table, migration 104 makes `generation_claims.video_id` nullable and adds a SECOND partial
unique index, `(tenant_id, stage) WHERE video_id IS NULL` — the ORIGINAL `(tenant_id, video_id, stage)`
index never fires for NULL rows (Postgres treats NULLs as distinct), so without the new index two
concurrent tenant-level claims could both insert. New `generation_claims.acquire_channel()` /
`release_channel()` are the only callers that ever write a NULL-video-id row; every existing per-video
`acquire()`/`release()`/`is_blocked()` call site and its SQL is untouched (verified: their own tests
still pass unmodified). `learn_channel` acquires stage `"dna"` before any learner runs and releases in
a `finally` (including on an unexpected exception) — a double `learn_channel` call, or a future
identity-editing chat op sharing the same stage, now genuinely serializes instead of racing.

### Result contract (for C42's confirmable digest card)

```json
{
  "ok": true,
  "busy": false,
  "error": null,
  "learners": {
    "import_channel_videos": {"status": "learned", "summary": "Imported 12 video(s) from the channel.", "fields_written": ["channel_videos"], "error": null},
    "identity_builder": {"status": "learned", "summary": "Learned voice, cadence, hooks, and structure, plus a thumbnail formula from 3 of your top video(s).", "fields_written": ["voice_tone", "cadence", "hook_style", "structure", "research_approach", "real_quotes", "signature_phrases", "visual_format", "thumbnail_style", "style_description", "hook_examples", "cadence_example", "structure_example"], "error": null},
    "script_template": {"status": "skipped", "summary": "No example script provided.", "fields_written": [], "error": null},
    "channel_format": {"status": "learned", "summary": "Locked your channel format: 3D animation / animated.", "fields_written": ["visual_format", "format_locked"], "error": null},
    "reference_video": {"status": "skipped", "summary": "No reference video provided.", "fields_written": [], "error": null}
  },
  "identity": { "...current channel_identity dict, with _sources/_history..." }
}
```
A denied claim short-circuits to `{"ok": false, "busy": true, "error": "Already learning this channel's DNA — try again in a moment.", "learners": {}, "identity": <current, unmodified>}` before any learner runs.

### Cost per run (tenant's own key — BYOK, no new paid integration)

identity_builder (always runs): up to (top_n+4)=7 Firecrawl scrape attempts (2 proxy modes each) to
land 3 transcripts, 1 Claude distill call (~2200 max_tokens), +1 Claude vision call if thumbnails were
found (~1400 max_tokens). script_template (optional): +1 Claude call (~1200 max_tokens). reference_video
(optional): +up to 2 Claude calls (~2048 max_tokens, one retry on bad JSON). Worst case (all optional
inputs supplied): ~4-5 Claude calls, roughly **$0.05-$0.30** per cost-awareness.md's Sonnet/Haiku
per-call figures, plus Firecrawl scrape credits (external, not in that table). channel_format and the
import step make no LLM calls.

### Verify

18 new tests: 14 in `storyengine/backend/tests/functional/test_c41_channel_dna.py` (orchestration —
happy-path call order, optional-input skip vs channel_format's independent confidence gate, per-learner
failure isolation, not-my-channel import-first, claim held/released incl. on an exception escaping a
monkeypatched step, double-run busy refusal with zero learners run; plus two "for real" tests against a
fake DB — script_template's replaced-vs-saved wording via the pre-check query, and reference_video's
fold-in through the REAL `stamp_identity_write` proving `_sources["reference_video_style"].learner ==
"reference_video"`) + 4 for `generation_claims.acquire_channel`/`release_channel` (fake-pool: acquire/
deny/release/reacquire cycle, fail-closed on DB error, fail-soft release). Non-vacuous: `git stash` of
`generation_claims.py` + `routes/onboarding.py` (the two modified files; `channel_dna.py` + the test
file + the migration are new/untracked and stay) reproduces exactly **10 of 14** orchestration-file
failures (every test touching `acquire_channel`/`release_channel`, directly or via `channel_dna`'s own
`generation_claims` import) — confirmed live, then the stash was popped back.

**Full backend suite**: `./venv/bin/python -m pytest tests/ -q` -> **1333 passed** (1319 baseline + 14
new C41 tests in the channel_dna file; the 4 generation_claims fake-pool tests are counted inside that
same 14) **/ 15 pre-existing failures / 1 pre-existing error** — matches baseline exactly, zero new
failures. `py_compile` clean on all touched/new `.py` files.

### Modified/New Files (C41)

| Path | Change |
|------|--------|
| `storyengine/backend/channel_dna.py` | NEW — `learn_channel` orchestrator + 5 `_run_*` per-learner step functions + `_format_confident` |
| `storyengine/backend/migrations/104_generation_claims_channel_level.sql` | NEW — `generation_claims.video_id` nullable + partial unique index `(tenant_id, stage) WHERE video_id IS NULL` |
| `storyengine/backend/generation_claims.py` | Additive: `acquire_channel()` / `release_channel()` (video-less claim variant). Existing `acquire()`/`release()`/`is_blocked()`/SQL untouched |
| `storyengine/backend/routes/onboarding.py` | `_import_channel_videos` now returns an `int` (saved count) instead of `None` — the only other caller (`connect_youtube`'s `background_tasks.add_task`) discards the return value, so this is additive |
| `storyengine/backend/tests/functional/test_c41_channel_dna.py` | NEW — 18 tests (14 orchestration/learner + 4 claim) |

### Deploy-safety assessment

One migration (104), additive: `ALTER COLUMN ... DROP NOT NULL` + `CREATE UNIQUE INDEX IF NOT EXISTS`
— no data rewrite, no existing row can become NULL retroactively, every existing per-video claim path
byte-identical (proven: their tests pass unmodified). `channel_dna.py` is a new module with no route
wired to it yet — **not reachable from chat, UI, or onboarding until C42/C45 wire a door to it**; it is
importable and covered by tests but has zero live callers today, so this chunk cannot regress any
existing user-facing flow. `_import_channel_videos`'s new return value is additive (old caller ignored
it; nothing reads a `None` return anywhere). Frontend untouched (confirmed via `git diff --stat` —
`storyengine/frontend/` shows no changes). Safe to ff-merge.

**Deferred to `tasks/live-verification-queue.md` §C41** (also the natural live test for **C42**, which
gives this function its first real caller): running `learn_channel` against a real tenant + real
channel — this chunk's `[V]` is unit-only per the checklist (no route, no UI yet).

**Next chunk: C42 · P4.1c chat front door + confirmable digest card** — wire `learn_channel` behind a
"learn this channel: <url>" chat intent (ack-now background-task pattern, `progress_cb` already
supports this), render the digest as a per-field confirm-before-save card (closing identity_builder's
save-without-review gap noted in the P4.1 scout), route corrections to C44's seam.

## C42 — P4.1c "learn this channel" chat front door + confirmable digest card (added 2026-07-19)

Third build chunk of Phase 4 Pillar 1. Gives C41's `learn_channel` its first real caller: a chat
intent, a confirmable digest card, and a thin HTTP door C45 (onboarding) and a future MCP tool can
reuse. No new learner logic — this is wiring + a small envelope extension for the run report.

### Chat intent wiring

`routes/chat.py`'s `_learn_channel_intent(msg)` is a SIBLING of `_identity_intent`, not a rewrite of
it: `_identity_intent`'s "voice/style" wording still means "just show/rebuild the identity_builder
view"; `_learn_channel_intent` (requires "channel" + a learn/study/analyze/manage/managing verb)
means "run every learner and show the full digest." Dispatched in `chat_turn` at a new step **3.4**,
BEFORE step 3.5's `_identity_intent` check, so "learn my channel's voice" gets the broader C41
treatment instead of identity_builder alone. Matches the three spec examples verbatim: "learn this
channel: `<url>`", "learn my channel", "here's a channel I'm managing `<url>`". `_extract_channel_url`
pulls the URL/handle out of the message by reusing `routes.onboarding._extract_channel_id_from_url`
as the validity check — the same parser `channel_dna._run_import` uses, so intent and orchestrator
always agree on what counts as a channel reference.

`_handle_learn_channel` mirrors `_handle_build_identity`'s exact ack-now + background-task shape
(Firecrawl scrapes + several Claude calls can exceed a chat turn's gateway window): acks immediately
— *"🧬 On it — analyzing the channel, this takes a couple of minutes; ~$0.10-0.30 of your API
budget."* — states the cost per the checklist's explicit money-honesty requirement, and schedules
`channel_dna.learn_channel(tenant_id, channel_url=...)` as a `background_tasks.add_task`.

**Money-rule flag (per the checklist's own ask):** storyengine/CLAUDE.md's hard rule reads "anything
that triggers paid generation... gets a cost quote and a yes first," and this DOES spend the tenant's
own Claude/Firecrawl credits. No confirm gate was added here, matching two existing precedents: (1)
`_handle_build_identity` (identity_builder alone) already ships unconfirmed, and (2) research/SEO
verbs run unconfirmed by established convention (this checklist's own explicit instruction for this
chunk). If "paid generation" in that hard rule was meant to cover ANY spend rather than just
image/clip/voice generation, this ask should get a confirm card too — flagging for Ryan rather than
guessing.

### Digest card + provenance-aware actions

`_dna_digest_intent` ("show the channel digest", "what did you learn") -> `_handle_show_channel_digest`
reads `channel_profiles.channel_identity`, and — if there's anything learned — builds the digest card
via `_build_dna_digest_card(identity, run)`: one row per learner (name/label/status/summary, from the
persisted `_last_run` report) and one row per known identity field actually present (`voice_tone`,
`cadence`, `hook_style`, `structure`, `research_approach`, `visual_format`, `thumbnail_style`,
`reference_video_style` — absent fields are simply omitted, never manufactured), each carrying its
`_sources` provenance (learner + timestamp) and a `revertable` flag from
`channel_dna_meta.latest_history_index_for_field`. An honest header appears when any learner failed:
*"Here's what I could learn about your channel — a step or two hit a snag... ask me to try again any
time."* New card kind `"channel_dna_digest"` added to ChatCore's `cardKind()` lookup table (S9-3
pattern) and `ACTION_CARD_KINDS` — zero new `card.id === "..."` string-match branches anywhere else.

Card actions, dispatched deterministically at chat_turn step **3.6b** (source-locked before producer
intake, same discipline `_handle_style_draft_confirm` established for C22, gated on
`state["pending_dna_digest"]` so a card can't be manufactured from LLM prose alone):
- **Keep** (default) — no write at all; the values are already saved per C41's write-then-review
  design. The button just clears the pending marker and acknowledges.
- **Revert** a field — `channel_dna.revert_field(tenant_id, field)` re-resolves the latest history
  index SERVER-SIDE (never trusts a client-supplied index — the identity may have changed between
  render and tap) and calls `channel_dna_meta.restore_field`, the exact C40 undo mechanism.
- **Correct** (free text, e.g. "actually the voice is more playful") — saves a channel-scope
  `director_preference` via the EXISTING `_save_preference` (the same write C15c's `remember` op
  uses). This is the deterministic, form-posted version of that write, not the full LLM-classified
  remember/forget routing — C44 formally wires that; today the checklist calls for exactly this much.

### `_last_run` envelope extension (channel_dna_meta.py)

New reserved envelope key `_last_run` (added to `ENVELOPE_KEYS`, alongside `_sources`/`_history`) —
`{"at", "ok", "learners": {...}}`, the same shape `learn_channel` already returns, stashed via a NEW
`stamp_last_run()` that deliberately bypasses `stamp_identity_write`'s per-field provenance loop (it's
a run report, not a field a learner taught — no `_sources` stamp, no `_history` entry of its own).
`channel_dna._persist_last_run` writes it at the end of every non-busy `learn_channel` call, fail-soft:
an `execute()` hiccup falls back to the identity as already fetched rather than breaking an otherwise-
successful run. New `latest_history_index_for_field()` is the shared "is there a prior value to
revert to" query both the digest card and `revert_field` use — a field's very FIRST-ever write IS
revertable (back to absent), by C40's own existing design (see
`test_restore_field_to_previously_absent_sets_none`), so the digest shows Revert even on a channel's
first-ever learn.

### Thin HTTP route (`routes/channel_dna.py`, NEW) — one implementation, two doors

`POST /api/channel-dna/learn` (ack-now, same shape as the chat door — checks `channel_dna.is_learning`
first for a friendlier immediate "busy" message, then backgrounds the SAME `learn_channel` call) and
`GET /api/channel-dna/status` (reads the SAME `_last_run` envelope key, zero second read path). Tests
pin `routes.channel_dna.learn_channel is channel_dna.learn_channel` — literally the same callable, not
a re-implementation. Registered in `main.py`. Not yet wired to an MCP tool this chunk:
`routes/mcp.py`'s tool calls are synchronous request/response (see `_call_create_video`'s
BackgroundTasks plumbing for the closest existing precedent), and a tool that blocks for 1-2 minutes
of Firecrawl+Claude work is a different reliability shape than the existing read-only/create-video
tools — deferred rather than rushed, flagged here per the checklist's own "if cheap" hedge. C25a's held
media-proxy files were not touched (`routes/mcp.py` itself was read but not edited).

### Verify

37 new tests in `storyengine/backend/tests/functional/test_c42_learn_channel_chat.py`, eight groups:
(1) `channel_dna_meta.stamp_last_run`/`latest_history_index_for_field`; (2) `channel_dna._persist_last_run`
(success + fail-soft-fallback), `revert_field` (success/"nothing to revert"/tenant-scoping), `is_learning`
(true/false/fail-open); (3) `_learn_channel_intent`/`_extract_channel_url` matching the three spec
phrasings + negative cases; (4) `_handle_learn_channel` acks immediately, states the cost, and proves
the ACTUAL orchestrator call only happens inside the backgrounded job (never awaited inline), including
a job-never-raises-out-of-the-task case; (5) `_build_dna_digest_card` shape (provenance, honest failed-
learner header, revertable flag) + `_handle_show_channel_digest` (no-identity-yet friendly reply vs.
card-rendered-and-pending-armed); (6) `_handle_dna_digest_action` keep/revert/correct, including the
"ask for what's missing" replies when a field/correction text is blank; (7) source-lock (`inspect.
getsource` proves step 3.4/3.6b run before 3.5's `_identity_intent` and before the normal-intake `user_
parts` assembly); (8) the thin route (same-callable identity check, ack/busy, status shape, empty-status
fail-safe). Non-vacuous: `git stash -u` (channel_dna.py/channel_dna_meta.py/main.py/routes/chat.py
modified + routes/channel_dna.py/the test file untracked) reproduces the exact pre-chunk baseline
(**1333 passed / 15 failed / 1 error**, confirmed live), then the stash was popped back.

**Full backend suite**: `./venv/bin/python -m pytest tests/ -q` -> **1370 passed** (1333 baseline + 37
new C42 tests) **/ 15 pre-existing failures / 1 pre-existing error** — zero new failures. `py_compile`
clean on all touched/new `.py` files. Frontend: `npx tsc --noEmit` clean; `npm run build` clean (with
`NEXT_PUBLIC_API_URL` set — the build's existing prerender requirement, unrelated to this chunk).
`grep 'card.id === "'` on ChatCore.tsx shows the new check living ONLY inside `cardKind()` — zero new
scattered string-match branches.

### Modified/New Files (C42)

| Path | Change |
|------|--------|
| `storyengine/backend/channel_dna_meta.py` | Additive: `LAST_RUN_KEY`/`ENVELOPE_KEYS` extended, `stamp_last_run()`, `latest_history_index_for_field()` |
| `storyengine/backend/channel_dna.py` | Additive: `_persist_last_run()` (wired into `learn_channel`'s return), `revert_field()`, `is_learning()` |
| `storyengine/backend/routes/chat.py` | Additive: `_learn_channel_intent`/`_extract_channel_url`/`_handle_learn_channel`, `_dna_digest_intent`/`_build_dna_digest_card`/`_handle_show_channel_digest`/`_handle_dna_digest_action`, dispatch wiring in `chat_turn` (steps 3.4/3.6b) |
| `storyengine/backend/routes/channel_dna.py` | NEW — thin `POST /learn` + `GET /status` door, reuses `channel_dna.learn_channel` directly |
| `storyengine/backend/main.py` | `channel_dna` router registered |
| `storyengine/backend/tests/functional/test_c42_learn_channel_chat.py` | NEW — 37 tests |
| `storyengine/frontend/src/lib/api.ts` | Additive: `ChatDnaLearnerRow`/`ChatDnaFieldRow` types, `ChatCard.header`/`.learners`/`.fields`/`.any_failed` |
| `storyengine/frontend/src/components/chat/ChatCore.tsx` | Additive: `"channel_dna_digest"` `cardKind()`/`ACTION_CARD_KINDS` entry, `DnaDigestCard` component + `ACTION_CARD_RENDERERS` wiring |

### Deploy-safety assessment

No migration, no schema change (the `_last_run` envelope key lives inside the existing
`channel_identity` JSONB, same no-new-table discipline C40 established). `routes/channel_dna.py` is a
new router with no other route depending on it. `routes/chat.py`'s new dispatch steps (3.4/3.6b) sit
strictly BEFORE the existing 3.5/3.6/producer-intake paths and only fire on their own new intent
predicates (`_learn_channel_intent`/`_dna_digest_intent`/the `channel_dna_digest` selections key) — an
ordinary "make a video about..." turn never touches this code (none of those predicates match). C25a's
held media-proxy branch untouched. Frontend changes are purely additive (new optional `ChatCard`
fields, a new card-kind branch) — an older frontend build simply never renders the new card, same
"additive and safe" posture every prior card-kind addition (C15b/C21b/C22) documented. Safe to
ff-merge.

**Deferred to `tasks/live-verification-queue.md` §C42 (subsumes §C41's entry — merged; see that file):**
the real end-to-end pass — a real channel learned via chat, the digest actually rendering in the
browser, a live Revert/Correct round-trip — plus an MCP tool for `learn_channel`, and C41's own
original live-verification ask (this chunk gives it its first real caller).

**Next chunk: C43 · P4.1d consumption audit + convergence** — every build path must read the ONE saved
DNA object; reconcile `identity.py`'s per-request injection vs `system_prompts.py`'s one-shot `tenant_
prompt_defaults` writes (they can silently fight today); reconcile the TWO thumbnail-formula impls
(`pipeline_executor` vs `identity_builder`).

## C43 — P4.1d Channel-DNA consumption audit + convergence (added 2026-07-19)

Fourth build chunk of Phase 4 Pillar 1. Traces every generation path to confirm it reads the ONE
saved DNA object through a documented seam, then reconciles the two risks the P4.1 scout flagged:
`system_prompts.py` silently fighting `identity_builder`'s writes, and two independent thumbnail-
formula code paths drifting apart. Audit-first, smallest-correct-fix — no big refactor.

### Consumption audit (every generation path traced to its DNA seam)

All 5 entry points (chat `routes/chat.py`, the arq queue worker `worker.py`, `routes/autopilot.py`,
direct API routes `routes/pipeline.py`/`routes/videos.py`, and `routes/queue.py`) instantiate the SAME
`pipeline_executor.PipelineExecutor(tenant_id)` and call its `run_*` stage methods — there is
genuinely ONE execution engine, not a parallel per-door implementation of any stage.

| Path (`PipelineExecutor` method) | Reads DNA via | Gap? |
|---|---|---|
| `run_script`, `run_machine_script_preview/block` | `_load_prompt_overrides` → `build_identity_context` → `resolve_prompt` (per-video > tenant > identity-filled neutral template) | none |
| `run_research` | same, PLUS a direct `channel_identity->'research_approach'` read appended as extra context (pipeline_executor.py:7727-7742) | none — documented equivalent pattern |
| `run_thumbnail` (legacy from-scratch path) | same, PLUS a direct `channel_identity->'thumbnail_style'` read appended to `thumbnail_system_prompt` (pipeline_executor.py:7385-7405) | none |
| `run_thumbnail` → `_run_channel_formula_thumbnail` (own-brand modeling, tried FIRST) | direct `channel_identity->>'thumbnail_blueprint'` + `channel_identity->'thumbnail_style'` (as "consensus", explicitly overriding the blueprint on conflict) reads (pipeline_executor.py:14403,14432) | none — see thumbnail convergence below |
| `run_video_scripts` (motion prompts) | `_load_prompt_overrides` (`video_motion` key) | none |
| `run_video_generation` (clip generation) | none directly — consumes the motion instructions `run_video_scripts` already wrote to DB | none — identity already baked in upstream |
| `run_prompts`, `run_storyboard_prompts`, `run_storyboard_images`, `run_images` | `_export_visual_style` → `build_identity_context` → `VISUAL_STYLE_DESCRIPTION`/`CHANNEL_NICHE` env seam (skills pipeline can't import the backend) | none — documented sibling seam to `_load_prompt_overrides`, same source function |
| `run_coverage_stage` → `static_docu.generate_static_images_for_video` (static-docu render mode) | direct `channel_identity->'visual_format'` read (`static_docu.static_mode_for_tenant`) | none — reads one known key, structurally envelope-safe, same pattern C40 already audited |
| `run_sound_prompts`/`run_sound_effects` | `_load_prompt_overrides` (no engine template for these keys — `resolve_prompt` returns `None`, bot's own neutral default is used unless a tenant override exists) | none — by design (docs/image-prompt-engine.md style split, no DNA-derived sound craft yet) |
| `run_render`, `run_upload`, `run_voice` | none | none — mechanical/TTS stages, no creative-voice injection point |
| chat's `_export_visual_style`/character/environment generation | same `build_identity_context` seam via `routes/characters.py` helpers reused by `run_characters` | none |

**Gap assessed, not fixed:** the scout flagged "creator_brief never reaches generation." Traced:
`routes/chat.py`'s `creator_brief` JSONB (`_BRIEF_KEYS = ("intent", "goals", "niche_angle", "channel",
"competitors")`) is conversation-continuity memory for the CHAT PRODUCER (so a fresh chat session
doesn't re-ask what it already knows) — a different column, different purpose, from the
voice/hook/structure DNA that `identity.py`/`identity_builder` feed into generation. Confirmed correct
design, not a gap: forcing it into the generation seam would conflate "what the creator told the
producer once" with "how the channel's own videos actually sound," which is exactly the DNA-from-
real-videos principle `identity_builder.py`'s own docstring states ("Source of truth = the videos, not
operator input").

### Precedence law: already correct, now provenance-visible

`pipeline_executor.resolve_prompt` (pinned by the pre-existing `tests/test_resolve_prompt.py`) already
implements: per-video override > tenant override (`tenant_prompt_defaults`) > neutral engine template
filled with the channel's identity. A tenant override still gets `engine_templates.safe_fill`'s
identity substitution — this was already the checklist's recommended law, verified correct, no code
change needed there.

The REAL risk was silence, not precedence: `routes/system_prompts.py::generate_prompts` (the "generate
my prompts from a style description" endpoint) wrote `channel_profiles.style_description` with a
BLIND `UPDATE` — the exact same column `identity_builder.build_channel_identity` COALESCE-writes and
stamps into `channel_identity._sources`. A creator running "generate prompts" after DNA-learning ran
could silently erase the learned voice with zero record of who did it. Fix: `generate_prompts` now
ALSO read-modify-writes `channel_identity` through `channel_dna_meta.stamp_identity_write(learner=
"system_prompts")` before its existing column write — same precedence, same behavior, but a later
`channel_dna` digest now shows the overwrite (`_sources.style_description.learner == "system_prompts"`)
instead of it vanishing silently, and any OTHER identity_builder-owned field (e.g. `voice_tone`)
survives untouched (proven by test — the merge-not-replace guarantee C40 built stamp_identity_write
for).

### Thumbnail-formula convergence: shared vision-call primitive, not a schema merge

Confirmed what each of the two flagged code paths actually does before choosing (per the chunk's own
hedge):
- `identity_builder._thumbnail_style` — vision pass over UP TO 3 of the channel's top thumbnails →
  an AGGREGATE consensus style JSON (`layout`/`subject`/`text_style`/`color_palette`/`mood`/
  `recurring_elements`), written to `channel_identity.thumbnail_style`.
- `routes/model_video.py::_describe_thumbnail_style` (called from `pipeline_executor.
  _run_channel_formula_thumbnail`) — vision pass over the ONE best-performing thumbnail → a DETAILED
  per-image blueprint (style/scene/objects/composition/text tiers/palette), cached via
  `pipeline_executor._cache_channel_thumbnail_blueprint` into `channel_identity.thumbnail_blueprint`.

These are not duplicate computations of the same thing — different schemas for different consumers.
`_run_channel_formula_thumbnail` already treats them as complementary: it reads BOTH fields and
explicitly has `thumbnail_style` ("consensus") WIN any conflict with `thumbnail_blueprint` when
transforming a spec for a new video (pipeline_executor.py:14424-14440, `_transform_channel_thumbnail_
spec`'s prompt literally says "wins any conflict with the blueprint"). Collapsing the two JSON schemas
into one would be a bigger, riskier refactor than this chunk's own "smallest correct changes"
constraint allows, and would risk breaking that existing tie-break logic.

The GENUINE drift risk was reliability, not schema: `identity_builder._thumbnail_style` hit Kie's
Claude gateway directly with a raw httpx POST — the EXACT endpoint `shared/clients/vision_client.py`
exists to route around, because (per that module's own docstring) it "has twice drifted into silently
dropping image blocks — HTTP 200, plausible text, but the model never saw the pixels."
`_describe_thumbnail_style` already used the safe `vision_call` helper for this reason (its own
docstring: "NOT the Claude gateway directly: the gateway silently drops image blocks when it
drifts"). Fix: `identity_builder._thumbnail_style` now calls the SAME `vision_call` primitive
(`kie_key=..., tier="fast", max_tokens=1400`, images capped at 3 as before) instead of its own
bespoke httpx call — one safe vision-call implementation now backs both thumbnail-formula learners,
closing the reliability drift, while their two distinct JSON artifacts (and the pipeline's existing
consensus-wins-over-blueprint precedence) stay exactly as they were. `_KIE_CLAUDE_URL` (now dead)
removed; `CLAUDE_MODELS` import (no longer used in this file) removed.

**Byte-identity proof for the no-DNA fallback:** `pipeline_executor.py` — home of
`_run_channel_formula_thumbnail`, `_cache_channel_thumbnail_blueprint`, and the entire own-brand-vs-
legacy fallback chain — has ZERO lines changed by this chunk (`git diff --stat -- pipeline_executor.py`
is empty). The convergence lives entirely inside `identity_builder.py`'s vision-call primitive, so a
tenant with no channel DNA (no top thumbnail, no blueprint, no key) hits the exact same short-circuits
in the exact same order as before.

### Verify

New `storyengine/backend/tests/functional/test_c43_dna_convergence.py`, 5 tests: (1)
`generate_prompts` stamps `style_description` into `channel_identity._sources` with
`learner="system_prompts"` while an unrelated prior `identity_builder` field (`voice_tone`) survives
byte-for-byte, and a `_history` entry records the overwrite; (2) the existing 6-row
`tenant_prompt_defaults` write is unaffected (regression guard); (3) `_thumbnail_style` calls
`vision_call` exactly once with the expected `kie_key`/`tier="fast"`/`max_tokens=1400`/images-capped-
at-3 args, and `_KIE_CLAUDE_URL` no longer exists on the module (proves this is a real replacement,
not a second parallel path); (4) no key or no thumbnail URLs still returns `None` (byte-identical
short-circuit); (5) every vision provider failing (`VisionUnavailable`) degrades to `None`, never
raises. Non-vacuous: `git stash -u` (identity_builder.py/routes/system_prompts.py modified, the new
test file untracked) reproduces the exact pre-chunk baseline (**1370 passed / 15 failed / 1 error**,
confirmed live), then the stash was popped back. `pipeline_executor.py`'s own diff-stat is empty
(quoted above) — the strongest possible proof of the fallback-ordering claim.

**Full backend suite**: `./venv/bin/python -m pytest tests/ -q` → **1375 passed** (1370 baseline + 5
new C43 tests) **/ 15 pre-existing failures / 1 pre-existing error** — zero new failures. `py_compile`
clean on all touched/new `.py` files. `tests/test_resolve_prompt.py` (precedence law),
`tests/test_channel_dna_meta.py` (envelope), and `tests/functional/test_system_prompts_generate.py`
(source-audit) all still pass unmodified — 33/33.

Frontend: untouched (this chunk is entirely a backend consumption/convergence fix — no new UI
surface, no API shape change any frontend code depends on). No `npx tsc`/`npm run build` re-run
needed; nothing in `storyengine/frontend/` has a diff.

### Modified Files (C43)

| Path | Change |
|------|--------|
| `storyengine/backend/routes/system_prompts.py` | `generate_prompts` now also stamps `channel_identity.style_description` via `channel_dna_meta.stamp_identity_write(learner="system_prompts")` before its existing column write |
| `storyengine/backend/identity_builder.py` | `_thumbnail_style` now calls `shared.clients.vision_client.vision_call` instead of a raw httpx POST to Kie's Claude gateway; dead `_KIE_CLAUDE_URL` constant and unused `CLAUDE_MODELS` import removed |
| `storyengine/backend/tests/functional/test_c43_dna_convergence.py` | NEW — 5 tests |

### Deploy-safety assessment

No migration, no schema change, no new route, no frontend surface. Both fixes preserve existing
return shapes and existing precedence/fallback behavior for every caller — proven by
`pipeline_executor.py` having a zero-line diff and by the "unrelated field survives" + "no-key/no-url
short-circuit unchanged" tests above. Safe to ff-merge.

**Deferred to `tasks/live-verification-queue.md` §C43:** a real "generate prompts" run against a
tenant with DNA already learned, confirming the digest (`show the channel digest`) surfaces the
`system_prompts` provenance tag on `style_description`; a real `_thumbnail_style` vision call against
real thumbnails, confirming the Gemini-first `vision_call` chain returns usable JSON on live Kie
credentials (no live vision call was made this chunk — all 5 tests mock `vision_call`/`httpx`).

**Next chunk: C44 · corrections loop wiring** — formalize the LLM-classified remember/forget routing
that C42's digest-card "correct" action deliberately deferred (today it's a deterministic form-post to
`_save_preference`, not the full natural-language classification `_handle_copilot`'s remember/forget
triggers already do elsewhere).

---

## C44 — P4.1e corrections loop wiring: `director_preferences` reach GENERATION, not just chat (added 2026-07-19)

Fifth build chunk of Phase 4 Pillar 1 — the last conceptual piece of Channel DNA. C15c gave the chat
producer/co-pilot a "STANDING PREFERENCES" system-prompt block, hydrated fresh every turn. C42's digest
card wired the "correct" action to save those same channel-scope `director_preferences` rows. But until
this chunk, nothing except CHAT ever read them back — a correction said once ("actually the voice is
more playful") never touched script/research/thumbnail/title/video_motion generation. This chunk closes
that gap: a channel-scoped correction now genuinely overrides the learned DNA value everywhere
generation reads it, with no JSONB hand-editing (corrections live in `director_preferences` only; the
digest's per-field flag is a read-time keyword match, not a write into `channel_identity`).

### The seam chosen, and why

C43's own consumption-audit table names `identity.build_identity_context` as the ONE function every
generation stage shares: `pipeline_executor._load_prompt_overrides` calls it once per run and feeds the
result through `resolve_prompt` for every text stage (script/research/thumbnail/title/video_motion/
sound_curation/sound_generation); `_export_visual_style` calls it again for the image pipeline's
`VISUAL_STYLE_DESCRIPTION`/`CHANNEL_NICHE` env-var seam. `engine_templates.safe_fill` is downstream of
that (it only fills placeholders in whatever text `resolve_prompt` already picked) and doesn't see the
image-pipeline path at all — so `build_identity_context` is the only function that actually satisfies
"ALL stages share." `IdentityContext` gained one new field, `standing_preferences: str = ""`, populated
by a new `identity._standing_preferences_block(tenant_id)`: a channel-scope-ONLY (`scope = 'channel'`),
capped (20 rows / 3000 chars, matching C15c's own `_PREF_CAP`/`_PREF_BLOCK_MAX_CHARS` discipline),
fail-soft (`except Exception -> ""`) read of `director_preferences`, run as its OWN try/except separate
from the existing `projects`/`channel_profiles`/`visual_styles` lookup — a preferences-table hiccup
can't suppress the rest of identity resolution, and vice versa.

**Deliberately NOT an import of `routes.chat._list_preferences`**, even though that function already
does the exact channel-scope query needed (`_list_preferences(tenant_id, video_id=None)`). `routes/chat.py`
sits on top of a heavy import chain — a FastAPI `APIRouter`, `actions.py` (which does its own
`sys.path.insert` for the entire `skills/video-pipeline` package), `vault`, `generation_claims`,
`channel_briefs`, `producer_prompt` — that `identity.py` must not pull in: it's a low-level module
imported by every lightweight identity/prompt unit test (`test_identity_context.py`,
`test_resolve_prompt.py`, `test_engine_templates.py`), and by every generation stage in the pipeline.
The query itself is intentionally SMALLER than `_list_preferences` (no video-scope union — see the
boundary note below), so duplicating six lines of SQL here is the correct trade against inverting the
module-dependency direction (a domain-core module importing a route file).

### Precedence law, extended one rung

`pipeline_executor.resolve_prompt` (pinned by the pre-existing `test_resolve_prompt.py`, C43's
precedence-law test) already implemented: per-video override > tenant override (`tenant_prompt_defaults`)
> neutral engine template filled with the channel's identity. This chunk adds the new rung: **explicit
per-video prompt > tenant_prompt_defaults > standing preferences > identity-learned values > neutral
template.** Concretely: after `resolve_prompt` picks whichever source won and runs it through
`engine_templates.safe_fill`, it APPENDS `identity.standing_preferences` — never templates it in, so it
rides along on top of a per-video override, a tenant override, OR the neutral template alike:

```python
if chosen:
    filled = engine_templates.safe_fill(chosen, identity)
    return filled + (getattr(identity, "standing_preferences", "") or "")
return None
```

The block itself is pre-formatted with the framing:

> `STANDING CREATOR DIRECTIONS (obey these over any conflicting learned style):`

— mirroring C15c's chat framing (`STANDING PREFERENCES (obey unless the creator overrides this turn; ...)`)
verbatim in spirit but deliberately a DIFFERENT string: C15c's is per-turn chat guidance ("the creator
can still override THIS turn"), this one is a standing generation directive with no per-turn escape
hatch (a build has no "this turn" to override anything with). Pinned by
`test_c15c_preferences_brief_framing_unchanged`, which asserts `_preferences_brief`'s own text is
untouched and does NOT contain the new string.

A tenant/per-video override is a full human-authored prompt and still wins outright per the law above;
appending preferences on top doesn't reverse that. What it DOES override is the neutral template's own
identity-learned content (voice_style/niche/etc. baked in by `engine_templates.render`) — exactly the
gap the checklist named ("a correction... must OVERRIDE the learned DNA value everywhere generation
reads it"). Because `standing_preferences` defaults to `""` for every existing `IdentityContext`
construction (every test, every tenant with zero preferences), this is a pure no-op — proven by
`test_resolve_prompt_no_preferences_is_byte_identical_to_pre_c44` and by the untouched pre-C44
`test_resolve_prompt.py` suite still passing unmodified.

### The per-video boundary — confirmed, not changed

Checklist asked to confirm the boundary against C15c's own scoping rather than assume it. C15c's
`director_preferences.scope` is either the literal `'channel'` or a video_id's text form; C15c's own
`_preferences_brief(tenant_id, video_id=None)` already only ever hydrates a video-scoped row into THAT
video's own co-pilot chat, never the home producer's channel-wide chat. Generation inherits the same
logic one level further: `build_identity_context(tenant_id, video)` is called once per run for ONE
video, but its result — and specifically `_standing_preferences_block`, which takes only `tenant_id`,
never `video_id` — has no way to know it's "this video's chat session" vs. a completely unrelated video
being built next. A creator noting "the kitten in THIS video is orange, not gray" is a fact about one
video, not an instruction about how the CHANNEL should sound going forward; letting it leak into every
future build for every other video would be a correctness bug, not a feature. So: video-scoped
preferences stay exactly where C15c put them (chat-only, that video's own co-pilot), and only
`scope = 'channel'` rows ever reach generation. Pinned by
`test_standing_preferences_block_queries_channel_scope_only` (asserts the literal query parameter) and
`test_handle_show_channel_digest_passes_preferences_into_the_card` (asserts `_list_preferences` is
called with `video_id=None` from the digest path too).

### Digest extension: keyword match + an unconditional footer

`routes/chat.py::_build_dna_digest_card` gained a `preferences` parameter (fetched by
`_handle_show_channel_digest` via the SAME `_list_preferences(tenant_id, video_id=None)` chat hydration
already calls — one query, two consumers, no second parallel read). Two additions, matching the
checklist's own hedge ("keyword/field-tag match is fine; don't build NLP; if a cheap match isn't
reliable, just list standing directions in a footer instead"):

- **`overridden_by` per field** — `_match_preference_override(field_key, pref_texts)` checks each active
  preference's text (newest-first) for a cheap keyword hit against a small per-field map
  (`_FIELD_OVERRIDE_KEYWORDS`: `voice_tone` -> "voice"/"tone", `visual_format` -> "visual"/"b-roll"/
  "broll"/"footage"/"animation", etc.) and returns the first (most recent) match, or `None`.
- **`standing_directions` footer** — EVERY active channel-scope preference, unconditionally, regardless
  of whether it keyword-matched any field. Chose this hybrid over a footer-only design specifically
  because a clean keyword hit ("actually the voice is more playful" -> `voice_tone`) is strictly more
  useful shown inline next to the field it corrects than buried in a flat list — but a real correction
  often won't use the field's exact word ("never use stock-footage-style b-roll" DOES happen to match
  `visual_format`'s keyword list here, but plenty of real phrasing won't), so the footer guarantees
  nothing is ever silently hidden just because the keyword match missed.

Frontend (`ChatCore.tsx`'s `DnaDigestCard`, `lib/api.ts`): `ChatDnaFieldRow.overridden_by` (optional,
renders an inline "Overridden by your standing direction: ..." note, gold-colored, reusing the already-
imported `PencilLine` icon) and `ChatCard.standing_directions` (optional, renders a "Your standing
directions" footer section reusing the already-imported `History` icon) — both additive, zero new icon
imports, an older frontend build simply never reads either key. storyengine's own CLAUDE.md mandates the
`web-design-system` skill before any UI work; that skill is not installed in this environment (only the
review-only `web-design-guidelines` skill exists here) — flagged rather than silently skipped; the
change instead follows the existing `DnaDigestCard` component's established CSS-variable/icon language.

### Verify

21 new tests in `storyengine/backend/tests/functional/test_c44_corrections_loop.py`, five groups: (1)
`identity._standing_preferences_block` — empty/no-rows, the obey-over framing + numbering, the
channel-scope-only query parameter, fail-soft on a DB error, length cap, blank-text rows ignored; (2)
`build_identity_context_from_rows`/`build_identity_context` wiring — the field carries through, defaults
to `""`, populates from a real (faked) DB read, and a preferences-table error doesn't suppress the rest
of identity resolution; (3) `pipeline_executor.resolve_prompt` — both blocks (identity-filled template +
standing preferences) coexist with the framing intact, preferences ride along under a tenant override
AND a per-video override, the pre-C44 byte-identical regression case (empty preferences), and a
no-template/no-override key still returns `None` (preferences never manufacture a prompt out of
nothing); (4) `routes/chat.py` — `_match_preference_override`'s keyword hit/miss, `_build_dna_digest_card`'s
`overridden_by` + `standing_directions`, and `_handle_show_channel_digest` passing `_list_preferences`'s
result through with `video_id=None`; (5) the C15c regression pin — `_preferences_brief`'s own framing
text is unchanged and distinct from the new string. Non-vacuous: `git stash` of the three modified `.py`
files (`identity.py`/`pipeline_executor.py`/`routes/chat.py`; the new test file stays) reproduces 20 of
21 failures against the pre-C44 baseline — the 21st (`test_resolve_prompt_no_preferences_is_byte_identical_to_pre_c44`)
correctly still PASSES against old code too, since it's the explicit no-op regression pin, not a new-
behavior test — confirmed live, stash popped back.

**Full backend suite**: `./venv/bin/python -m pytest tests/ -q` -> **1396 passed** (1375 baseline + 21
new C44 tests) **/ 15 pre-existing failures / 1 pre-existing error** — same failing-test-name list as
C40-C43's documented baseline, zero new failures. `py_compile` clean on all touched/new `.py` files.
`tests/test_resolve_prompt.py` (12 pre-existing cases), `tests/test_identity_context.py`,
`tests/test_engine_templates.py`, `tests/test_channel_dna_meta.py`, and both C41/C42/C43's own functional
test files all pass unmodified (105/105 across that combined re-run).

Frontend: `npx tsc --noEmit` clean; `npm run build` clean (same pre-existing `NEXT_PUBLIC_API_URL`
prerender note, unrelated to this chunk). `grep 'card.id === "'` on `ChatCore.tsx` shows zero new
matches — the only new JSX lives inside the pre-existing `channel_dna_digest` `cardKind()` branch.

### Modified/New Files (C44)

| Path | Change |
|------|--------|
| `storyengine/backend/identity.py` | NEW `IdentityContext.standing_preferences` field (default `""`); NEW `_standing_preferences_block(tenant_id)`; `build_identity_context_from_rows`/`build_identity_context` thread the new field through (own fail-soft boundary, independent of the existing project/profile lookup) |
| `storyengine/backend/pipeline_executor.py` | `resolve_prompt` appends `identity.standing_preferences` after whichever prompt source won, before returning |
| `storyengine/backend/routes/chat.py` | NEW `_FIELD_OVERRIDE_KEYWORDS`/`_match_preference_override`; `_build_dna_digest_card` gained a `preferences` param + `overridden_by` per field + `standing_directions` footer; `_handle_show_channel_digest` fetches preferences via the existing `_list_preferences(tenant_id, video_id=None)` and threads them through |
| `storyengine/backend/tests/functional/test_c44_corrections_loop.py` | NEW — 21 tests |
| `storyengine/frontend/src/lib/api.ts` | Additive: `ChatDnaFieldRow.overridden_by`, `ChatCard.standing_directions` |
| `storyengine/frontend/src/components/chat/ChatCore.tsx` | `DnaDigestCard` renders the new `overridden_by` inline note + `standing_directions` footer (reuses existing `PencilLine`/`History` icon imports, no new imports) |

### Deploy-safety assessment

No migration, no schema change (`director_preferences` already exists, C15c), no new route. Both new
reads (`_standing_preferences_block`, the digest's `_list_preferences` call) are fail-soft and additive
— a tenant with zero standing preferences gets byte-identical output to pre-C44 everywhere (proven by
the explicit regression-pin test and by every pre-existing `test_resolve_prompt.py`/
`test_identity_context.py` case passing unmodified). Frontend fields are optional/additive on both
sides: an older frontend never reads `overridden_by`/`standing_directions` and renders exactly as
before; an older backend never sends them and the new frontend code paths simply don't render (both
guarded by truthy/length checks). Safe to ff-merge.

**Deferred to `tasks/live-verification-queue.md` §C44:** a real end-to-end round-trip — say a channel-
wide correction in chat ("actually the voice is more playful"), confirm the digest shows it in the
footer (and, if it keyword-matches, inline on `voice_tone`), then run a REAL script/research/thumbnail
generation for that tenant and confirm the standing-directions block is actually present in the system
prompt sent to Claude. No paid key in this sandbox to run that live.

**Next chunk: C45 · P4.1f onboarding hookup + intelligence-report retirement** — the P4.1 closer: wire
onboarding to call C41's `learn_channel` orchestrator instead of its own dead-end path; retire
`_build_intelligence_report` gracefully (it has live routes — needs a deprecation plan, not a silent
delete).

## C45 — P4.1f onboarding hookup + intelligence-report retirement — the P4.1 closer (added 2026-07-19)

Sixth and final build chunk of Phase 4 Pillar 1. Two halves: wire onboarding into C41's
`learn_channel` orchestrator, and gracefully retire onboarding's dead-end 4th intelligence pipeline
(`_build_intelligence_report`) the P4.1 scout flagged. **P4.1 (C40-C45) is now COMPLETE.**

### Tracing the LIVE onboarding surface first (the surprise this chunk turned up)

`routes/onboarding.py`'s own module docstring described a "5-step onboarding flow" ending in an
INTELLIGENCE step — but `storyengine/frontend/src/app/onboarding/page.tsx` no longer renders that flow
by default: `/onboarding` redirects straight to `/` (the chat-driven onboarding), and the multi-step
form (`OnboardingContent`, still reachable at `/onboarding?manual=1`) has its own `STEPS` array —
`channel, keys, youtube, style, video` — which never even had a competitors/intelligence step in the
UI. Grepping the ENTIRE frontend (`api.ts`, every `.tsx`) for any call to
`/api/onboarding/intelligence-report*` returned zero hits. The real, live onboarding is
`routes/chat.py`'s `_handle_onboarding` step machine (`intent → key → key_claude → goals/channel →
channel → competitors → connect_yt → connect_drive → upsell → modeling/done`), which calls
`routes.onboarding.connect_youtube`/`analyze_competitors` directly (not over HTTP) and — critically —
NEVER calls `_build_intelligence_report`. Its `_finish_onboarding` already gets competitor-driven
recommendations from a DIFFERENT, newer mechanism (`_propose_modeling_angles`/
`_generate_competitor_ideas`), which superseded the intelligence-report path before this chunk even
started. This reframed both halves of the task: the "hookup" point is `connect_youtube` (the one real
call site), not a new onboarding step; the "retirement" is pure backend cleanup with no frontend
re-pointing needed, because nothing ever pointed at it.

### Half 1 — onboarding hookup

`routes.onboarding.connect_youtube` used to fire-and-forget `_import_channel_videos` as its only
background task. It now schedules ONE task, `_import_then_learn(tenant_id, channel_url, channel_name,
learn)`: awaits the import (unchanged), then — if `learn` is true — calls
`channel_dna.learn_channel(tenant_id)` with **no** `channel_url` ("own-channel mode"): learn_channel's
own optional step-1 import is skipped, since the import just above already seeded `channel_videos`;
passing the URL again would make learn_channel re-scrape the same channel via yt-dlp a second time.
`learn` is decided by a new `_has_usable_generation_key(tenant_id)` (sibling check to
`routes.chat._has_generation_key` — same two vault slots, duplicated rather than imported to avoid a
chat.py↔onboarding.py import cycle) computed BEFORE scheduling: a keyless tenant gets **zero**
background tasks scheduled for this (not a task destined to fail for free) and `connect_youtube`'s
response carries `"dna_learning": "needs_key"` instead of `"started"`.

`routes/chat.py`'s `_handle_onboarding` "channel" step reads that field and extends its existing ack:
cost-honest ("~$0.10-0.30 of your API budget") when DNA learning actually started, or a non-blocking
"add a generation key (Settings → Keys)" hint when it didn't — either way the step still advances to
"competitors" (never blocks onboarding on a missing key, the C04 precedent). Claim safety is entirely
inherited from C41: a second `learn_channel` call for the same tenant (e.g. a "learn this channel" chat
ask fired moments later) is refused as busy by `generation_claims.acquire_channel`, not raced.

**Digest surface — chosen, not both offered.** The task allowed two designs: a dedicated
"learning…then show the card" onboarding step, or delivering the digest as the first home-chat
message. Rejected the first because nothing else in this flow waits either — every background step
(competitor analysis, connect_youtube's import) already fires-and-forgets, so inventing a wait state
here would be the ONE place in the flow that behaves differently. Instead extended
`_finish_onboarding` — the existing end-of-flow moment that already reaches back for competitor
results (`_propose_modeling_angles`) — with a new `_finish_onboarding_dna_note(tenant_id)`: reads
`channel_profiles.channel_identity`, and (a) returns `("", None)` if no channel was ever connected
(`_last_run` absent — nothing to report), (b) a "still learning, ask me in a bit" text note with no
card if `channel_dna.is_learning` is still true, or (c) a text note PLUS the exact same
`_build_dna_digest_card(identity, run, preferences)` C42's "show the channel digest" chat intent
renders — one digest, both surfaces, no second card-shape to maintain. The card is appended to
whichever cards list the finishing turn already has (the modeling-angle selection card, or nothing in
the no-competitor-data fallback) — proven safe because the frontend already renders `cards` as a list
(`ChatCore.tsx`'s `cards.map(...)`), not a single card, so two unrelated cards on one turn is an
existing, not a new, pattern.

### Half 2 — intelligence-report retirement (graceful)

Confirmed via grep that `intelligence_reports` (the table `_build_intelligence_report` writes) has
exactly ONE referencing file in the whole backend — `routes/onboarding.py` itself — versus
`content_intelligence` (a similarly-named but DIFFERENT table, populated by
`distillation/pipeline.py` and read by `routes/intelligence.py`, `routes/discovery.py`,
`routes/autopilot.py`, `routes/dashboard.py`, the analytics page's `getIntelligenceStats`/
`getIntelligenceRecommendations` etc.) — the chunk brief's parenthetical calling out
"`content_intelligence` nobody reads" conflated the two; `content_intelligence` is very much alive and
was NOT touched. `intelligence_reports` is the genuinely dead-end table.

The three routes (`POST /intelligence-report`, `GET /intelligence-report/status/{job_id}`,
`GET /intelligence-report`) now `raise HTTPException(410, ...)` pointing at Channel DNA as the
replacement — mirroring this repo's own existing retirement convention (`routes/pipeline.py`'s several
410 stubs) rather than inventing a new deprecation shape. A shape-preserving thin-proxy to the DNA
digest was considered and rejected: the two response shapes (`title_ideas`/`thumbnail_insights`/... vs.
`learners`/`fields`/provenance) don't align cheaply, and with zero live callers there's no real client
to keep happy with a translated shape — an honest 410 is simpler and more discoverable. Unlike
`routes/pipeline.py`'s precedent (which leaves the old body sitting unreachable below the raise),
`_build_intelligence_report`, `_fallback_intelligence_report`, `_parse_report_json`, and
`_run_intelligence_report_job` are DELETED outright — the checklist's own explicit ask ("delete dead
helpers with grep-proofs"), consistent with this repo's "no commented-out/dead code" rule. The
`_report_jobs` in-memory dict and the never-actually-used `IntelligenceReportRequest` Pydantic model
went with them. `intelligence_reports` (the table) is untouched — no drop migration, retired-in-place;
the `/status` endpoint's historical `SELECT id FROM intelligence_reports ...` existence check (for a
tenant who generated one under the old flow) is left alone, since it's a read of pre-existing data, not
part of the retired write path.

### Verification

19 new tests in `storyengine/backend/tests/functional/test_c45_onboarding_dna_hookup.py`. Non-vacuous:
a parallel docs commit on this branch (`9ac1fbb`) accidentally folded part of this chunk's
`routes/onboarding.py` diff into history mid-session (a `git add -A` swept up in-progress edits), which
would have distorted a plain `git stash` proof — instead swapped `git show 8b44187:...` (the pre-C45
baseline commit, C44's tip) into `routes/onboarding.py` and `routes/chat.py`, ran the new suite (18/19
fail against that baseline — only the grep-based "no remaining callers" proof trivially passes since
the old file predates the new helper names), then restored the current files and confirmed `git diff
--stat` matched exactly. Full backend suite **1415P/15F/1E** = baseline(1396)+19, zero new failures,
identical 15 failure names/1 error. `py_compile` clean on every touched module. Frontend untouched (no
re-pointing needed — confirmed zero pre-existing callers); `npx tsc --noEmit` clean regardless. No
migration, no schema change, no new route (3 existing routes now 410).

### Modified/New Files (C45)

| Path | Change |
|------|--------|
| `storyengine/backend/routes/onboarding.py` | Module docstring rewritten (reflects the chat-driven flow, documents the retirement); `connect_youtube` now schedules `_import_then_learn` (new) instead of bare `_import_channel_videos`, gated by new `_has_usable_generation_key`; response gains `dna_learning`; `_build_intelligence_report`/`_fallback_intelligence_report`/`_parse_report_json`/`_run_intelligence_report_job`/`_report_jobs`/`IntelligenceReportRequest` DELETED; the 3 intelligence-report routes now raise `HTTPException(410, ...)` |
| `storyengine/backend/routes/chat.py` | `_handle_onboarding`'s "channel" step ack extended per `dna_learning`; NEW `_finish_onboarding_dna_note`; `_finish_onboarding` appends the DNA note/card to both its exit paths |
| `storyengine/backend/tests/functional/test_c45_onboarding_dna_hookup.py` | NEW — 19 tests |

### Deploy-safety assessment

No migration, no schema change, no new route (only 410s replacing live-but-uncalled bodies on 3
existing ones). `connect_youtube`'s new behavior is additive for every existing caller — the response
gains a field (`dna_learning`), nothing removed; a keyless tenant's behavior is unchanged apart from
that new field (still imports, still returns 200). Safe to ff-merge.

**Deferred to `tasks/live-verification-queue.md` §C45:** the live acceptance test that closes the
WHOLE P4.1 arc — a fresh tenant onboards, connects a real channel, the Channel-DNA learn pass actually
runs and produces a digest, and that digest visibly informs the next real production. No paid key in
this sandbox to run that live.

**P4.1 (C40-C45) COMPLETE.** Next: either C46 (quality-rules engine, awaiting Ryan's yes) or P4.2
(tenant-autopilot scouting) — the orchestrator decides.

---

## C46a — Generalize the script-quality critic hook (added 2026-07-19)

First build chunk of the quality-rules engine (decisions.md 2026-07-19: Ryan's HARD constraint —
formalizes his existing dial-in work, never a parallel path). Traced the audit's two named artifacts
before writing any code: `originality.py::grade_script`/`grade_script_with_client` (the fail-open LLM
judge — verdict pass/revise/regenerate, niche-adaptive) and the DvsU EDIT-loop pattern
(`pipeline_executor.py`'s `_run_static_script_hold`, same-draft targeted edit with named violations,
2-round bound, then needs_review). Also found `_grade_and_maybe_revise_script` ALREADY wired into
`run_script` at 2 call sites (modeled path L~11669, plain brief_translator path L~11768 pre-change) —
this chunk generalizes/absorbs that existing hook rather than adding a parallel one.

**New module `storyengine/backend/script_quality.py`:** `critique_script(tenant_id, video_id,
script_payload, *, rules_text=None, client=None) -> CritiqueResult` reuses `originality._SCRIPT_JUDGE_
SYSTEM` and `_build_script_judge_user_prompt` VERBATIM (imported, not re-typed) for the 5 universal
gates; when `rules_text` is given, appends a second grading pass returning per-rule `rule_verdicts`.
`rules_text` seam wired to this tenant's `script_templates.structure` (the channel's house script
format, same query `routes/script_templates.py::apply_default_template` already uses to steer the
WRITER) — cheap, existing, honest; C46b replaces this with the real per-channel rules table.
`edit_draft_with_violations(scenes, violations, *, client)` generalizes DvsU's exact edit-prompt
("EDIT THIS DRAFT MINIMALLY... change ONLY what the violations name") from its 5-sentence paragraph
shape to an arbitrary multi-scene script, using the `@@@SCENE n@@@` sentinel format the modeled-script
path and `user_script.py` already share — kept as a standalone parser (`_parse_scene_markers`) so this
module has zero pipeline_executor import (mirrors originality.py's own DB-optional decoupling).
`run_critique_and_edit(...)` is the orchestrator: grade once; `revise` → same-draft edit loop bounded
at `MAX_EDIT_ROUNDS=2`; `regenerate` → ONE fresh reroll via a caller-supplied callback (originality's
own bound); still failing after those bounds → `needs_review`.

**pipeline_executor.py wiring — ONE absorbed call site + one telemetry-only site:**
`_grade_and_maybe_revise_script` (signature-compatible: `(video_id, regenerate=None, *,
hold_status=None)`) now calls `script_quality.run_critique_and_edit` instead of
`grade_script_with_client` directly — the SAME single grading call this pipeline already made here,
never a second one (traced and confirmed no prior double-grading risk). It fetches/persists scenes via
the `scripts` table (DELETE+INSERT+`videos.script` UPDATE, same pattern the modeled-script/user_script
save paths already use), attaches violations to `videos.script_validation.quality_critic` (the
established "passed"/"checks" field, not a new one), and — new behavior — returns `{"needs_review":
bool, "violations": [...]}` so callers can gate the stage advance; returns `{}` (falsy) when grading
couldn't run at all, so a caller/test ignoring the return value keeps the pre-C46a "always advance"
behavior (proven by a dedicated test). `hold_status`: the modeled path already commits
`status=ready_for_voice` inside `_run_modeled_script` BEFORE grading runs, so its `run_script` call site
passes `hold_status=current_status` — if still `needs_review` after the bound, this reverts the video's
status rather than leaving an unresolved script silently advanced; the plain brief_translator path needs
no hold_status since grading there runs BEFORE its own status-advance code. **Additivity for the
static-docu roster path:** `_run_static_script_hold` already runs its OWN stricter hard-gate harness
(`_validate_machine_story_sentences` + its bounded EDIT loop — grounding law, claim maps, hedge words,
twist taxonomy). Per decisions.md 2026-07-19's additivity constraint, the generic critic must never
re-judge or override that harness, so `run_script`'s roster branch calls new
`_telemetry_quality_critique(video_id, hold_result)` instead — ONE best-effort grade recorded onto
`applied_intelligence.retention_grade` for visibility, no edit loop, no status change, skipped entirely
on a failed hold. This is genuinely NEW coverage (that path fired zero grading calls before C46a), not
a duplicate. `user_script.py`'s `user_supplied` bypass is untouched and still returns before any of this
code runs (pinned by a dedicated test).

**Cost:** 1-3 extra Claude calls per script generation for the plain/modeled paths (1 grade + up to 2
edit-rounds' re-grades, or 1 grade + 1 reroll re-grade) — same class as originality's existing single
grade call, confirmed absorbed not duplicated (test asserts exactly 1 call on a `pass` verdict). The
static-docu path gains exactly 1 new telemetry call where it previously had zero.

### Verification

35 new tests: `storyengine/backend/tests/test_script_quality.py` (22, pure-module unit tests — verdict
matrix, fail-open, rules_text addendum, scene-marker round-trip, edit-loop bound, orchestrator's full
pass/revise/regenerate matrix incl. parse-failure-stops-the-loop and regenerate-returns-nothing-usable)
+ `storyengine/backend/tests/test_c46a_quality_critic_wiring.py` (13, PipelineExecutor wiring — absorbed
single-call no-double-grading, rules_text sourced from `script_templates`, scene persistence on revise,
needs_review+violations-attached with/without hold_status revert, `run_script`'s 3 call sites incl. the
user_supplied bypass and the static-docu telemetry-only path). Non-vacuous: `git stash` on
`pipeline_executor.py` alone → 11/13 wiring tests fail (2 legitimately still pass — they pin unchanged
pre-existing behavior: falsy-return backward-compat and the plain-path pass-through); separately moved
`script_quality.py` aside → `test_script_quality.py` fails to collect (`ModuleNotFoundError`), confirming
the new module itself is exercised, not vacuously imported. `python -m py_compile` clean on all 4
touched/new files. Full backend suite **1450P/15F/1E** = baseline(1415P/15F/1E, independently
re-confirmed via the same stash+file-move) + exactly 35, identical 15 failure names/1 error, zero new
failures. Existing `tests/test_machine_documentary_hold.py` (239 tests, incl. the
`_grade_and_maybe_revise_script`-is-noop'd animated-video test) still passes unchanged. Frontend
untouched — confirmed via `git status`/`git diff --stat` on `storyengine/frontend`, no `tsc`/`build` run
needed.

### Modified/New Files (C46a)

| Path | Change |
|------|--------|
| `storyengine/backend/script_quality.py` | NEW — generic critic + DvsU-style bounded edit loop |
| `storyengine/backend/pipeline_executor.py` | `_grade_and_maybe_revise_script` rewritten to call `script_quality` (signature gains `hold_status` kwarg, return value gains `{needs_review, violations}`); `_record_applied_retention` extended to record `rule_verdicts` when present; NEW `_telemetry_quality_critique`; both `run_script` call sites (modeled, plain) now check the grade's return value and short-circuit to `{"status": "needs_review", ...}` without advancing status; the static-docu roster branch gains the telemetry call |
| `storyengine/backend/tests/test_script_quality.py` | NEW — 22 tests |
| `storyengine/backend/tests/test_c46a_quality_critic_wiring.py` | NEW — 13 tests |

### Deploy-safety assessment

**Recommend ff-merge candidate, not yet ff-merged by this chunk** (leaving that call to the orchestrator
per protocol) — no migration, no schema change, no new route. The one real behavior change: a script
that STILL needs review after the full bounded loop no longer silently advances to `ready_for_voice` on
the plain and modeled paths (pre-C46a: always advanced, "silent nudge" only). This is a deliberate,
spec'd formalization of DvsU's own `_save_machine_script_block`'s `all_passed` gating convention, but it
IS user-visible behavior for any tenant whose script fails the bounded critic — worth a scan of
production data for how often that verdict path actually fires before/shortly after deploy (no live
key in this sandbox to test that empirically here). Additive elsewhere: `script_validation` gains one
new JSON key (`quality_critic`), `applied_intelligence.retention_grade` gains an optional `rule_verdicts`
key, both backward-compatible with any reader that doesn't know about them.

**Deferred to `tasks/live-verification-queue.md` §C46a:** live grade-a-real-script run (a real Claude
call against a real weak/strong script, confirming the judge still discriminates the way
`originality.py`'s own self-test proves it does standalone).

Next: **C46b · per-channel rules store** (new table modeled on the QL/QD row shape + `shared/profiles/
script`'s typed schema; replaces the `script_templates.structure` stopgap `rules_text` source above with
the real thing).

## C46b — Per-channel quality-rules store with scope-aware resolution (added 2026-07-19)

Builds the real rules table C46a's `rules_text` seam stubbed out. Traced the two named artifacts first:
`storyengine/notes/dvsu-quality-law.md` (74 QL/QD laws, each row `id | law (testable) | evidence | Triangle
B/R/G | severity` — the row shape to steal, minus the B/R/G legs which this chunk's `[D]` spec didn't ask
to store) and `shared/profiles/script/schema.py`'s typed `ValidationConfig`/`RetentionConfig` dataclasses
(confirmed a distinct axis — that schema is a channel's WRITER-facing voice config, this table is
GRADER-facing law rows; no overlap, no refactor needed).

**New `quality_rules` table (migration 105, applied LIVE via Supabase MCP against
`wrromlupsmyzrrcqlucn`, confirmed via `information_schema.columns`):** `tenant_id`, `rule_id` text (e.g.
"QL-12"), `law` text, `evidence` text nullable, `severity` (`hard_gate`|`warn`|`guidance`), `applies_to`
jsonb (default `{"all": true}`), `source` (`doc_upload`|`chat`|`seed`), `active` bool, created/updated.
`UNIQUE (tenant_id, rule_id)`. RLS enabled, no policies (same deny-all-to-anon pattern as
`agent_tokens`/`mcp_confirm_tokens`).

**`applies_to` vocabulary (Ryan's 2026-07-19 scoping requirement: resolved from DATA the video already
carries, never LLM judgment about which gates apply — full rationale in the migration's own header
comment, mirrored in `quality_rules.py`'s module docstring):**

| Key | Matches when | Video column(s) read |
|---|---|---|
| `"all": true` | always | none — universal |
| `"research": true` | research stage actually ran (not skipped) | `videos.research_skipped` (false/NULL = ran) + `videos.pipeline_stages` (the workflow plan; NULL = full pipeline = research included, else must be a plan member) via `status_map.stage_enabled_in_plan` |
| `"story": true` | narrative/documentary-arc laws (twist, punch, act spine) | `videos.render_mode == 'static_docu'` — the one render_mode this signal set can identify as arc-driven today; extend the resolver's `resolve_video_shape()`, not its contract, as more arc-driven formats land |
| `"animated": true` | | `videos.render_style == 'animated'` |
| `"realistic": true` | | `videos.render_style == 'realistic'` |
| `"channel_format": "<value>"` | STRING-valued, case-insensitive match | a `channel_format_value` the CALLER supplies (forward-compatible stub — `channel_rules.py` does no `channel_profiles` lookup of its own this chunk; a rule scoped this way simply never matches until a caller starts passing the value; pipeline_executor's call site doesn't pass one yet, an honest scope-boundary, not a bug) |

A rule matches if ANY key resolves true (OR across keys — a hybrid research+story video, e.g. DvsU's
`static_docu` render_mode with research not skipped, collects BOTH scopes' rules). An unrecognized
applies_to key is logged and skipped, never crashes; a rule with only unrecognized keys never matches
any video (fails closed on garbage scope, confirmed by `caplog`-asserting the exact warning fires).

**Scope-resolution quote** (`quality_rules.py`):
```python
def resolve_video_shape(video_row: dict) -> dict:
    video_row = video_row or {}
    return {
        "all": True,
        "research": _research_active(video_row),
        "story": (video_row.get("render_mode") or "") == "static_docu",
        "animated": (video_row.get("render_style") or "") == "animated",
        "realistic": (video_row.get("render_style") or "") == "realistic",
    }
```
`active_rules_for_video(video_row, rules)` is a PURE function (no DB) — `pipeline_executor.py` fetches the
tenant's active rule rows itself (via its own already-patched `fetch_all`, matching
`tests/test_c46a_quality_critic_wiring.py`'s established fake-DB convention) and hands them in, rather
than `quality_rules.py` opening a second, separately-mockable DB surface for the same table — this is
what let the existing C46a wiring test (`test_sources_rules_text_from_script_templates_structure`) keep
passing byte-for-byte unmodified against the new code path.

**Severity reaches the critic's blocking logic (minimal, justified extension to `script_quality.py`):**
C46a's `CritiqueResult`/`run_critique_and_edit` gained an optional `severity_by_rule: Optional[Dict[str,
str]]` parameter (default `None` — byte-identical when omitted). New `script_quality._apply_rule_severity`
deterministically upgrades a judge's own `verdict: "pass"` to `"revise"` whenever a FAILED `rule_verdict`
names a rule tagged `hard_gate` in that map — severity is an authored fact about the rule, not something
the grading call's own holistic verdict should be trusted alone to encode. `warn`/`guidance` failures
never force a verdict change (informational only, still surfaced via `violations`). `compose_rules_text`
formats each rule as `[<rule_id>] [<SEVERITY>] <law> (why: <evidence>)`, hard-gate first, and instructs
the judge to echo the exact bracketed id back in `rule_verdicts[].rule` so the severity map can match it
after grading. Proven end-to-end (not just at the `script_quality` unit level): a hard-gate rule the
judge under-called as "pass" still reaches `run_critique_and_edit`'s bounded edit loop inside
`pipeline_executor._grade_and_maybe_revise_script`
(`test_hard_gate_rule_failure_reaches_the_bounded_edit_loop` — 3 Claude calls: grade(forced-revise) →
edit → re-grade(pass), scene rows actually persisted).

**`pipeline_executor.py` rewiring:** `_grade_and_maybe_revise_script`'s `rules_text` seam now sources from
`quality_rules.active_rules_for_video` + `compose_rules_text` FIRST, with `script_templates.structure`
(the channel's house FORMAT prose — a distinct, still-useful signal: quality_rules answers "what must
this script clear," script_templates answers "what shape should this script take") kept as an ADDITIONAL
appended block under a `--- CHANNEL HOUSE FORMAT ---` header, never dropped. When no quality_rules rows
exist yet AND no script_templates row exists, `rules_text` stays exactly `""` — confirmed
byte-compatible with pre-C46b/pre-C46a behavior (`test_empty_quality_rules_and_no_template_is_byte_
compatible_with_c46a`).

**Ingestion doors (two doors law):**
1. **Chat op `draft_quality_rules`** (`routes/chat.py`, mirrors C22's `draft_style` confirm pattern
   exactly): value `{"asset_id": ...}` (reuses the C05 `chat_assets.parsed_text` path) or `{"text": ...}`.
   Calls `quality_rules.parse_rules_document` — NEVER writes a row, only stashes
   `state["pending_quality_rules_draft"]`. A `quality_rules_draft` preview card (rule count + hard-gate/
   warn/guidance split + a 3-rule preview) is attached ONLY when this turn's ops genuinely included the
   op AND a real draft was stashed (never manufactured from the LLM's own words). `chat_turn`'s dispatch
   intercepts the card's "yes"/"no" tap at step 3.6a — BEFORE the normal producer-intake turn — and
   `_handle_quality_rules_draft_confirm` is the ONLY place `quality_rules.bulk_create_rules` gets called
   from chat, gated strictly on an explicit `"yes"`. Producer taught the vocabulary in both the prose
   guidance and the JSON schema's `profile_ops` example list (same lock C22 used for `draft_style`/
   `use_style`, proven by a source-string assertion on `PRODUCER_SYSTEM_PROMPT`).
2. **Thin CRUD route** (`routes/quality_rules.py`, registered in `main.py`): `GET/POST/PATCH/DELETE
   /api/quality-rules[/{id}]`, tenant-scoped via `Depends(get_tenant_id)`, every write going through
   `quality_rules.py`'s CRUD functions (never a second implementation) — for C47's MCP pickup and a
   future settings UI (no UI this chunk, per spec).

**Parser (`quality_rules.py`):** `parse_markdown_table` is a DETERMINISTIC, zero-cost regex/pipe-table
splitter that round-trips `dvsu-quality-law.md`'s own row shape (`| ID | Law | Evidence | Triangle | Sev
|`) exactly — tried FIRST by `parse_rules_document`, dropping the Triangle (B/R/G) column (not part of
this chunk's stored row shape). `llm_parse_rules_prose` is the ONE Claude-call fallback for a rules doc
that isn't table-shaped (plain prose/bullets) — only reached when the table parser finds zero rows,
proven by a test whose fallback client raises `AssertionError` if ever called against table input.
`suggest_applies_to` is a zero-cost keyword heuristic (research/story keyword lists) that proposes a
DEFAULT scope at ingestion time only — explicitly documented as distinct from, never a substitute for,
`active_rules_for_video`'s runtime resolution (which reads video data, never a law's wording) — the human
sees and can edit the suggestion on the confirm card before anything saves.

**Not this chunk (explicit scope boundaries):** DvsU's 74 laws are NOT seeded here — C46c does that
deliberately as the reference-tenant proof. No gate-behavior changes beyond feeding the existing critic
real rules (C46c lands the hard-gate replacements for `_validate_machine_story_sentences`). No settings
UI for the CRUD route. `channel_format` scope key has no live data source yet (documented stub).

### Verification

61 new tests: `storyengine/backend/tests/test_quality_rules.py` (39, pure-module — scope matrix incl. the
research/story/hybrid/unknown-key/channel_format cases, `compose_rules_text` severity tagging + ordering,
`script_quality._apply_rule_severity` unit + one full `critique_script()` end-to-end call proving the
upgrade fires, `parse_markdown_table` round-tripping a REAL excerpt copied verbatim from
`dvsu-quality-law.md` incl. header/separator-row skipping and Triangle-column drop, `suggest_applies_to`'s
keyword heuristic, `llm_parse_rules_prose` incl. fail-open-to-empty-list, `parse_rules_document`'s
table-first/LLM-fallback precedence, and every CRUD function against a fake tenant-scoped DB) +
`storyengine/backend/tests/functional/test_c46b_quality_rules_wiring.py` (22, wiring — real
`quality_rules` DB rows scope-matched into a real `_grade_and_maybe_revise_script` call incl. the
hybrid-video and out-of-scope-exclusion cases, house-format-kept-additional, the empty-rules
byte-compatibility pin, the hard-gate-reaches-the-edit-loop end-to-end proof, the full chat draft →
card → confirm → `bulk_create_rules` flow incl. the "no" discard and CRUD-raises fail-soft paths, the
`chat_turn` source-lock intercept assertion, producer-prompt vocabulary, and all 4 CRUD route functions
tenant-scoped). Non-vacuous via `git stash push` on the 6 tracked modified files (`main.py`,
`pipeline_executor.py`, `producer_prompt.py`, `routes/chat.py`, `script_quality.py`, `schema.sql`) +
temporarily moving aside the 2 new modules (`quality_rules.py`, `routes/quality_rules.py`) — both new
test files fail to collect (`ModuleNotFoundError`) against pre-chunk code, confirming they exercise the
new modules, not vacuously pass. `python -m py_compile` clean on all 8 touched/new backend `.py` files.
Full backend suite **1511P/15F/1E** = baseline (1450P/15F/1E) + exactly 61, identical 15 pre-existing
failure names/1 error (all unrelated — YouTube OAuth/oembed, discovery error-surfacing, activity-feed,
clip-dialogue ffmpeg — none touch chat/pipeline_executor/script_quality/quality_rules), zero new
failures.

### Modified/New Files (C46b)

| Path | Change |
|------|--------|
| `storyengine/backend/migrations/105_quality_rules.sql` | NEW — the table + applies_to vocabulary doc, applied LIVE |
| `storyengine/schema.sql` | `quality_rules` table appended (canonical schema mirror) |
| `storyengine/backend/quality_rules.py` | NEW — pure scope resolver + CRUD + ingestion parser |
| `storyengine/backend/routes/quality_rules.py` | NEW — thin tenant-scoped CRUD route |
| `storyengine/backend/main.py` | registers `quality_rules.router` |
| `storyengine/backend/script_quality.py` | `critique_script`/`run_critique_and_edit` gain optional `severity_by_rule`; new `_apply_rule_severity` |
| `storyengine/backend/pipeline_executor.py` | `_grade_and_maybe_revise_script`'s rules_text seam re-pointed to `quality_rules`, `script_templates.structure` kept as an additional block |
| `storyengine/backend/routes/chat.py` | new `draft_quality_rules` op, `_quality_rules_draft_card`, `_maybe_attach_quality_rules_draft_card`, `_handle_quality_rules_draft_confirm`, dispatch intercept at 3.6a |
| `storyengine/backend/producer_prompt.py` | teaches `draft_quality_rules` (prose + `profile_ops` schema example) |
| `storyengine/backend/tests/test_quality_rules.py` | NEW — 39 tests |
| `storyengine/backend/tests/functional/test_c46b_quality_rules_wiring.py` | NEW — 22 tests |

### Deploy-safety assessment

**Recommend ff-merge candidate, not yet ff-merged by this chunk** (leaving that call to the orchestrator
per protocol) — new migration (additive table, no existing-table ALTER, zero risk to any current query),
new route (dark until a caller exists — no frontend calls it yet), new chat op (dormant until the
producer LLM actually emits `draft_quality_rules`, which needs a real chat turn to exercise — the
prompt-vocabulary tests only pin that the words are TAUGHT, not that a live model reliably emits them).
The one real behavior change on the hot path: `_grade_and_maybe_revise_script`'s `rules_text` composition
changed shape — byte-compatible today (zero `quality_rules` rows exist for any tenant yet, confirmed via
the live Supabase check above showing the fresh table has 0 rows), so this ships inert until either a
chat upload or a manual CRUD POST puts a row in. Frontend untouched — confirmed via `git status` on
`storyengine/frontend`, no `tsc`/`build` run needed.

**Deferred to `tasks/live-verification-queue.md` §C46b:** real doc-upload → parse → confirm-card → save
round trip (incl. the dvsu-quality-law.md doc itself), the prose-fallback LLM parser against a real
model, and a real grading call proving scope-matched rules actually change judge behavior.

Next: **C46c · DvsU deltas as reference implementation** — seed DvsU's 74 laws (Section 3's DELTAS +
already-ruled Section 4 items) as the first TABLE-DRIVEN gates via this chunk's `bulk_create_rules`/
`source="seed"`, replacing the hardcoded `_validate_machine_story_sentences` constants with reads from
this table. Proves the engine generalizes beyond one tenant's stopgap.

---

## C46c — DvsU deltas as the reference-tenant table-driven gates (added 2026-07-19)

**Headline finding before writing any code:** D1 (word floor 80 not 95), D2 (twist-or-substitute hard
gate), and D3 (expanded twist taxonomy) were already ALL landed in `pipeline_executor.py` as hardcoded
constants in an earlier session, byte-identical to the law (`_ANTON_PARAGRAPH_HARD_MIN_WORDS = 80`,
the OR-1-approved twist-or-substitute gate, the 16-item `_DVSU_TWIST_TYPES` menu) — the doc's §3 DELTAS
table describing them as still-open gaps is STALE, not a live to-do. Only QL-12 (banned-hype list) was a
genuine mismatch: the hardcoded check (`_validate_static_unit_paragraph`) bans a different, older ad hoc
superlative-PHRASE list ("one of the greatest", "undoubtedly", "iconic"...) than QL-12's actual banned-
ADJECTIVE list (incredible, amazing, stunning, insane, epic, jaw-dropping, mind-blowing, game-changing,
breathtaking, unbelievable, spectacular). This chunk's real job, given that, is proving the engine can
take these values FROM THE TABLE when seeded rather than re-deriving new numbers — the reference
implementation is about the MECHANISM, not new law content.

**Seed script (`storyengine/backend/scripts/seed_dvsu_quality_rules.py`, NOT wired into any migration/
cron/auto-seed path — DvsU is a real production tenant on the LIVE db):** parses
`storyengine/notes/dvsu-quality-law.md` via C46b's `quality_rules.parse_markdown_table`, which extracts
exactly **74 rows (QL-1..QL-74)** — QD-1..QD-6 (Section 5) use a 4-column table format the parser's
5-cell-minimum requirement doesn't match, so they're not extracted; this is fine, since every QD law
(closer freedom, grounding scope, rounding hedges, exact-date sourcing, editorial-thesis warn-only, the
QL-1-restating word target) is already reflected in the ALREADY-LANDED hardcoded code's own `QD-N`-tagged
comments, confirmed by grep. Severities come straight from the doc's own Sev column (53 hard_gate / 14
warn / 7 guidance). `applies_to` scope is assigned by SECTION, not the generic keyword-heuristic
`suggest_applies_to()` (that's an ingestion-time DEFAULT for an arbitrary doc, never authoritative for a
doc whose structure is already known): QL-1..20 (Writing craft + Mechanical, the paragraph-assembly
gates) → `story` (49 rows once the 46-74 production sections are folded in below); QL-21..24 (Channel
identity) → `all`; QL-25..45 (Research and selection) → `research`; QL-46..74 (Voiceover/Image/
Thumbnail/Producer file) → `story` as the closest existing fit — **flagged, not papered over: C46b's
`applies_to` vocabulary has no dedicated voiceover/image/thumbnail scope key today**, so these 29 rows
share "story" with the paragraph-assembly laws even though they govern different downstream artifacts;
a real gap for a future chunk to add discrete keys for, not a mistake made silently. Final split: story
49 / research 21 / all 4 = 74. `--dry-run` is the DEFAULT (parses + reports counts, zero DB touch,
confirmed by making tenant resolution explode if reached); `--apply` is required to actually write, via
`bulk_create_rules(source="seed")` (idempotent — reruns edit rows in place, never duplicate). Tenant
resolution accepts `--tenant-id <uuid>` or `--channel-name <substring>` (refuses to proceed on anything
but exactly one match).

**Table-wins mechanism (`quality_rules.resolve_dvsu_overrides`, pure — no DB):** takes a video's already
ACTIVE + SCOPE-MATCHED `quality_rules` rows (the same list `active_rules_for_video` returns) and extracts
structured VALUES by parsing specific rule_ids' `law` text with targeted regexes proven against the REAL
doc text:
```python
_QL1_WORD_LAW_RE = re.compile(
    r"under\s+(\d+)\s+spoken\s+words.*?warn\s+(\d+)\s*-\s*(\d+).*?over\s+(\d+)",
    re.IGNORECASE | re.DOTALL,
)
```
— QL-1 → `word_floor` (hard_min/warn_top/hard_max/severity), QL-3 → `twist_gate` (severity only), QL-4 →
`twist_menu` (11 subtypes parsed from the law text UNIONED with the 5 canonical types, which live only in
the doc's discarded Evidence column so stay a small hardcoded constant), QL-12 → `banned_hype_words`
(the 11-word list parsed straight out of the parenthetical). A rule_id absent from the matched set, OR
present but its `law` text reworded away from the pattern, means that key is simply missing from the
returned dict — never raises, never half-applies a broken value. `pipeline_executor.py`'s
`_validate_static_unit_paragraph`, `_validate_machine_story_sentences`, and `_anton_preview_quality_audit`
each gained an optional `rule_overrides: Optional[dict] = None` parameter (100% backward compatible — the
9000-line `test_machine_documentary_hold.py` suite calls these with 2-3 positional args hundreds of times
and needed zero changes beyond one fetch-call-list assertion). Severity drives blocking vs advisory
uniformly: `severity != "hard_gate"` demotes a check's warning to `_ADVISORY_PREFIX`-tagged (never
blocks) rather than suppressing it outright — matches the doc's own "warn = flag, ships if deliberate"
language. QL-12 specifically UNIONS the table-parsed list with the pre-existing ad hoc phrase list rather
than replacing it (additivity is sacred — the two lists catch different things; seeding QL-12 must never
lose coverage the channel already had).

**Wiring (`PipelineExecutor._load_dvsu_rule_overrides`, new):** fetches the tenant's active `quality_rules`
rows via the SAME `fetch_all` pattern C46b's `_grade_and_maybe_revise_script` already established
(`"SELECT rule_id, law, evidence, severity, applies_to FROM quality_rules WHERE tenant_id = $1 AND
active"`), scope-matches via `quality_rules.active_rules_for_video`, resolves via
`resolve_dvsu_overrides`, and fails open (`{}`) on any error. Called ONCE per `_run_static_script_hold`
run (not per machine — proven by a wiring-lock test asserting the fetch appears textually before the
per-machine `for i, machine in selected_units:` loop) and threaded into all 5 validator call sites plus
the `_anton_preview_quality_audit` call (wiring-lock tests grep the method's own source slice for every
call site, mirroring `test_first_run_checklist_wired_lock.py`'s established source-inspection pattern).

**Generalization proof (checklist requirement — at least one non-DvsU-specific law):** QL-1's word-floor
shape (hard floor / warn band / hard ceiling) is generic craft law, not aircraft-specific.
`test_resolve_dvsu_overrides_generalizes_to_a_second_non_dvsu_tenant` feeds a hypothetical "Acme
Explainers" tenant's OWN completely different word-count law ("Reject under 40 spoken words; warn 40-60;
reject over 300") through the exact same `resolve_dvsu_overrides` and gets ITS OWN numbers back — nothing
in the resolver reads "DvsU," "aircraft," or any channel-specific string; the mechanism is pure
scope-matching + regex extraction over whatever law text a tenant's own rows carry.

**Open rulings NOT decided this chunk (§4 of the doc) — left for Ryan:**
- **OR-5 — crew-hate variant scope** (bring the "Most Hated" pilot-testimony format in as a separate
  named mode with its own overrides, or leave it out of scope?). Not landed in code either way.
- **OR-6 — corpus hygiene** (tag MostHated-Warships as an anti-pattern, exclude from style-seed sets?).
  Not a code change — a corpus-curation/prompt-seed decision outside this chunk's touch surface.
- **OR-9 — fixed thumbnail-text set** (add "BY PILOTS"/"BY CREWS" to the 5 locked phrases, or route via
  the open 2-4-word rule?). No thumbnail-text enum exists in code today to land this into regardless.
- OR-1 through OR-4, OR-7, OR-8 are already ruled AND already landed (confirmed above) — not re-litigated.

### Verification

28 new tests across 4 files. `storyengine/backend/tests/test_quality_rules.py` (+8): `resolve_dvsu_
overrides` against REAL law text copied verbatim from the doc for QL-1/QL-4/QL-12 — correct extraction,
graceful skip on unparseable law text, per-rule-id independence (only QL-12 seeded → only that key
returned), and the second-tenant generalization proof. `storyengine/backend/tests/
test_machine_documentary_hold.py` (+8): table override wins over the hardcoded constant (word floor,
hype words, twist menu), severity demotes hard→advisory for all three deltas, and 3 explicit
`rule_overrides=None`-vs-omitted-vs-`{}` byte-identity assertions. `storyengine/backend/tests/functional/
test_c46c_dvsu_deltas_wiring.py` (+6, NEW): `_load_dvsu_rule_overrides` fetch/scope-match/resolve,
scope-exclusion (a story-scoped row must not match a non-static_docu video), fail-open on a DB error, and
2 wiring-lock tests proving the call sites actually thread the resolved value through. `storyengine/
backend/tests/functional/test_c46c_seed_dvsu_quality_rules.py` (+6, NEW): the seed script's section-
boundary scope assignment against the REAL doc (74 rows, exact QL-1..QL-74 id sequence, 49/21/4 scope
split, known severities), and a dry-run-never-touches-DB proof.

Non-vacuous via `git stash -u` — reverted to pre-C46c code, ran the FULL suite: **15 failed, 1511 passed,
1 error** (identical names/count to C46b's own baseline), confirming the 15/1 are genuinely pre-existing
and unrelated to this chunk. Popped the stash back; re-ran: **15 failed, 1539 passed, 1 error** = exactly
1511 + 28 new, zero new failures. The DvsU harness's own pre-existing suite
(`test_machine_documentary_hold.py`, 239 tests before this chunk) stayed 100% green — every one of those
calls omits `rule_overrides` (the new 4th positional arg), so they exercise the byte-identical fallback
path by construction. `python -m py_compile` clean on all 7 touched/new backend `.py` files.

### Modified/New Files (C46c)

| Path | Change |
|------|--------|
| `storyengine/backend/quality_rules.py` | new `resolve_dvsu_overrides` (pure) + its regex extractors |
| `storyengine/backend/pipeline_executor.py` | `_validate_static_unit_paragraph`, `_validate_machine_story_sentences`, `_anton_preview_quality_audit` gain optional `rule_overrides`; new `_load_dvsu_rule_overrides`; `_run_static_script_hold` resolves overrides once and threads them through |
| `storyengine/backend/scripts/seed_dvsu_quality_rules.py` | NEW — the (not auto-run) DvsU seed script |
| `storyengine/backend/tests/test_quality_rules.py` | +8 tests |
| `storyengine/backend/tests/test_machine_documentary_hold.py` | +8 tests, +1 fetch-call-list assertion updated for the new quality_rules read |
| `storyengine/backend/tests/functional/test_c46c_dvsu_deltas_wiring.py` | NEW — 6 tests |
| `storyengine/backend/tests/functional/test_c46c_seed_dvsu_quality_rules.py` | NEW — 6 tests |

### Deploy-safety assessment

**Recommend ff-merge candidate, not yet ff-merged by this chunk** (orchestrator's call per protocol).
Zero behavior change for every tenant with no `quality_rules` rows (everyone, today — the live table
still has 0 rows per C46b's own check, unchanged by this chunk since the seed script is explicitly NOT
run here): every new `rule_overrides` parameter defaults to `None`/`{}` and every gate falls back to
today's exact hardcoded constant, proven both by direct byte-identity assertions and by the full
pre-existing 239-test DvsU suite staying green untouched. The one thing that changes ANYTHING once
someone runs the seed script with `--apply` is the DvsU tenant's own script-hold gates — no other tenant
is reachable by this code path (`applies_to` scoping + `tenant_id`-scoped fetch). Frontend untouched —
confirmed via `git status` on `storyengine/frontend`.

**Live seed run — deferred to `tasks/live-verification-queue.md` §C46c** (this chunk deliberately does
NOT seed the live DB): exact command, expected row count, and a post-seed smoke plan (one DvsU script
generation, confirm the QL-1/QL-12 gates actually fire from table values).

Next: **C46d · trust boundaries** — MCP/agent-submitted scripts (C47 ingest) pass the SAME critic;
`user_supplied` verbatim scripts keep their explicit no-gate bypass (`user_script.py`'s contract). Wires
the critic verdict into the C42 digest/chat surfaces so failures list rule-by-rule.

## C46d — Trust boundaries: the ingest gate + verdict surfacing (added 2026-07-19)

**The gate (`user_script.py::accept_external_script`, new):** the seam C47's MCP `submit_script` tool
will call. Traced first: `user_script.py`'s existing `set_user_script` is the ONLY external-script door
today — it installs the creator's OWN text VERBATIM (`script_source='user_supplied'`), no grading, no
gate, "the creator's word is final." An agent/MCP submission is a DIFFERENT trust class entirely
(decisions.md 2026-07-19 MCP-economics entry: "agent-authored scripts pass through the SAME quality-rules
critic as platform-generated ones — the rules engine is the trust boundary that makes externally-written
content safe to accept"), so `accept_external_script` is a SEPARATE function, not a flag on
`set_user_script` — refusing `source='user_supplied'` outright (`ValueError`) keeps the two contracts from
ever blurring.

**Design call — REJECT, not rewrite:** `run_script`'s own critic (`script_quality.run_critique_and_edit`)
owns a bounded same-draft EDIT loop for content WE generated — editing our own draft is fair game.
Editing an AGENT'S submitted draft is not: the words aren't ours to silently change, and a server-side
rewrite of someone else's submission would be a worse trust story than an honest rejection. So this
function calls `script_quality.critique_script` directly (one grading call, verdict-only, proven by the
FakeClient call-count assertions in every test) and branches on the verdict alone:
  - `'pass'` (including WARN/GUIDANCE-severity rule failures that never flip the verdict —
    `script_quality._apply_rule_severity`'s existing C46b enforcement, unmodified): **ACCEPT.** Saved
    through the exact scene/`videos.script` save path `set_user_script` already uses (same INSERT shape,
    same best-effort dialogue tagging), `script_source` = the caller's `source` (default
    `'agent_submitted'`) — never `'user_supplied'`, so `run_script`'s own
    `script_source == 'user_supplied'` bypass guard can never accidentally fire for it. Any WARN-severity
    rule failures ride along as non-blocking `warnings`, distinct from `violations`.
  - `'revise'`/`'regenerate'` (a universal retention gate OR a hard-gate channel rule failed): **REJECT.**
    Nothing is saved (proven: `writes == []` in the reject tests), nothing advances, the full rule-by-rule
    `violations` list (failing_gates + failed rule ids) is returned so the SUBMITTING AGENT can fix its own
    draft and resubmit.

Same tenant-scoped rules sourcing `_grade_and_maybe_revise_script` already established
(`quality_rules.list_all_rules` → `active_rules_for_video` scope-match → `compose_rules_text`
severity map), same niche resolution via `identity.build_identity_context`, same fail-open contract on a
missing/broken tenant Claude client (`kie_unified.get_text_client_for_tenant` failing → `client=None` →
`critique_script`'s own pre-existing fail-open path returns a default `pass`) — a transient config problem
must never indefinitely block a submission no human is standing by to retry.

**Verdict surfacing bug found while tracing the "natural host" (checklist item 3a) — fixed as part of
this chunk, not deferred:** `routes/videos.py::_parse_script_validation` (the `GET /api/videos/{id}`
serializer every video-detail page fetch uses) only passed a `script_validation` JSON blob through
unchanged when it contained a `"checks"` key; anything else — including a script_validation blob carrying
ONLY `{"quality_critic": {...}}`, which is EXACTLY what `_grade_and_maybe_revise_script` writes for a
plain (non-static-docu) script and what `accept_external_script` writes on accept — fell through to the
legacy plain-text parser, found zero `[PASS]`/`[FAIL]` lines, and silently returned `None`. The C46d
banner would have had nothing to render for the single most common case. Fix: the passthrough condition
now also accepts `"quality_critic" in parsed`. Pinned by 3 new tests (`quality_critic`-only passthrough,
legacy plain-text still converts, `checks`-shape still passes through unchanged).

**`quality_critic` record extended** (both `_grade_and_maybe_revise_script`'s write in
`pipeline_executor.py` and `accept_external_script`'s own write use the SAME shape) with `rule_verdicts`
(the critic's per-rule pass/fail list) and `severity_by_rule` (this tenant's own severity map) — new keys
only, every existing reader/test keeps working unmodified. This is what lets the frontend render
"rule-by-rule with severity," not just a flattened violations-strings list.

**Task-status/chat message gap found + fixed (checklist item 3b):** traced whether "the task-status
message already carries needs_review" — it did NOT. `run_script`'s two `needs_review` return dicts
(`plain` and `modeled` paths) carried `"violations"` but no `"error"`/`"message"` key, and
`routes/pipeline.py`'s `_set_task_status` NORMALIZES any non-running/non-failed status string to
`"completed"` — so a needs_review script silently polled/chatted back as a bare "completed" with **zero**
indication anything was flagged (`actions.py::make_action_step`'s `_run` already reads
`result.get("error") or result.get("message")` as its display text; `routes/pipeline.py`'s direct
`/script` route read only `result.get("error")`, dropping the message path entirely). Minimal fix: both
`needs_review` return dicts now also carry a `"message"` field (the same joined-violations string already
used for `_log_activity`), and the direct route's `_set_task_status` call gained the same
`error-or-message` fallback `make_action_step` already had — one line, matching an existing convention
instead of inventing a new one.

**Frontend (`ScriptVoiceTab.tsx`, the natural host — the existing "Script Validation" card already reads
`script_validation` and sits right where a creator reviews scenes before voice):** new "Quality Review
Needed" card, rendered only when `script_validation.quality_critic` is present and `!passed` — lists every
failing universal gate + failed rule (rule-by-rule, `FAIL`/`WARN` badge from `severity_by_rule`, note text
when the critic supplied one), fail-safe (any parse error renders nothing, never throws). Two actions:
  - **"Use it anyway"** — calls the EXISTING `advanceVideo`/`PATCH /api/videos/{id}/advance` verb (no new
    backend code; the same helper `handleApprove` already uses two lines above). Gated behind a light
    `confirmDialog`, same pattern as `handleApprove`. Free and effectively reversible: the hold only ever
    parks `videos.status`, never deletes or rewrites anything, so moving on costs nothing and re-running
    "script" would simply re-grade it again.
  - **"Regenerate"** — wired to the ALREADY-EXISTING `handleRegenerateScript` callback (`runPipelineStage`
    → `run_script`'s own re-grading path) — zero new regenerate logic, this card just gives the existing
    action a home when a hold is active.
No new icons/imports needed (`AlertCircle`, `Wand2`, `Loader2`, `ActionButton` were already imported).
`ActionButton`'s `icon={loading ? Loader2 : Wand2}` pattern (no spin animation on the icon itself) matches
`ThumbnailTab.tsx`'s own established convention exactly — not a new inconsistency introduced here.

### Verification

15 new tests, `tests/test_c46d_trust_boundaries.py`: the accept/reject/warn matrix (pass→saved+source+
status advance+one grading call; universal-gate revise→reject, nothing saved; hard-gate channel RULE
failure→reject with the rule id named, proving severity enforcement fires for external content too;
WARN-severity rule failure alone→accept with `warnings` populated, `violations` empty; no-client→fails
open→accepts), the `user_supplied` refusal (raises before any DB touch), tenant scoping (mismatched tenant
= "not found", zero DB writes beyond the lookup), 5 parametrized bad-scene-shape cases (empty list, wrong
type, missing/blank text, mixed dict/non-dict — all raise before any `execute` call, a `forbidden_execute`
fixture asserts this), and 3 `_parse_script_validation` tests (the quality_critic-only fix, plus 2
regression checks proving the pre-existing `checks`-shape and legacy-plain-text paths are untouched). Also
edited 2 pinned C46a tests (`test_c46a_quality_critic_wiring.py`) to expect the new `"message"` key on
`needs_review` — the dict shape genuinely changed, so the assertions were extended, not weakened.

Non-vacuous via plain `git stash` (source files only — the new untracked test file stays in place, so it
runs against PRE-C46d code): **13 of 15 new tests fail** (the 2 that still pass are the deliberately-
unaffected legacy-format/checks-shape regression checks) — `AttributeError: module 'user_script' has no
attribute 'accept_external_script'` and the quality_critic-only blob dropping to `None`, confirming the
tests exercise real, non-trivial new behavior. Popped back, full suite: **1554 passed, 15 failed, 1
error** = baseline (1539/15/1) + exactly 15, zero new failures, identical failure names to every prior
chunk's baseline. `python -m py_compile` clean on all 4 touched/new backend `.py` files.

Frontend: `npx tsc --noEmit` clean. `npm run build` — compiles and typechecks clean
("Compiled successfully", "Finished TypeScript"); the one build-time error encountered
(`NEXT_PUBLIC_API_URL is required in production builds`) is a pre-existing environment-config requirement
unrelated to this chunk (confirmed: setting the env var for the build made every route, including
`/pipeline/[videoId]`, prerender/compile with zero errors).

Live round-trip (a real MCP `submit_script` call once C47 registers the tool, plus a real browser look at
the "Quality Review Needed" card against a genuinely needs_review video) deferred to
`tasks/live-verification-queue.md` §C46d — this chunk ships the gate + surfacing, C47 wires the actual MCP
tool registration next.

### Modified/New Files (C46d)

| Path | Change |
|------|--------|
| `storyengine/backend/user_script.py` | new `accept_external_script` (+ `_normalize_external_scenes` shape validator) — the C47 ingest seam |
| `storyengine/backend/routes/videos.py` | `_parse_script_validation` passthrough condition widened to `"checks" in parsed or "quality_critic" in parsed` |
| `storyengine/backend/pipeline_executor.py` | `_grade_and_maybe_revise_script`'s `quality_critic` record gains `rule_verdicts`/`severity_by_rule`; both `needs_review` return dicts in `run_script` gain a `"message"` field |
| `storyengine/backend/routes/pipeline.py` | direct `/script` route's `_set_task_status` call gains the `error-or-message` fallback |
| `storyengine/backend/tests/test_c46a_quality_critic_wiring.py` | 2 pinned assertions extended for the new `"message"` key |
| `storyengine/backend/tests/test_c46d_trust_boundaries.py` | NEW — 15 tests |
| `storyengine/frontend/src/components/production/ScriptVoiceTab.tsx` | new "Quality Review Needed" banner card + `handleUseAnyway`/`usingAnyway` |

### Deploy-safety assessment

**Recommend ff-merge candidate.** Zero behavior change for any EXISTING flow: `_grade_and_maybe_revise_
script`'s new dict keys are additive-only (every existing reader keys off already-present fields); the
`needs_review` return dicts' new `"message"` key is additive (only 2 pinned tests needed their exact-
dict-equality assertions extended, and both were updated in this same chunk, not left broken);
`_parse_script_validation`'s widened condition is STRICTLY more permissive (nothing that used to pass
through now gets dropped, and nothing that used to convert via the plain-text branch is affected — proven
by the 2 regression tests). `accept_external_script` itself is inert until C47 registers an MCP tool that
calls it — dead code with tests today, live once C47 ships. Frontend banner only renders when
`script_validation.quality_critic.passed === false`, a state that exists on zero videos in production
today (no tenant has ever hit a needs_review script hold that reached this exact shape in the live DB, per
C46a/b/c's own "0 rows" quality_rules state) — so the new card is present in the bundle but unreachable
until a real needs_review script occurs.

Next: **C47 · MCP setup surface** — expose the SETUP layer (system prompts, script templates, quality
rules, channel DNA read/corrections/learn trigger, script/style profile selection) through MCP tools, PLUS
the content-ingest tools `submit_research(video_id, payload)` / `submit_script(video_id, scenes)` — the
latter now has `accept_external_script` ready and waiting to be called. May split C47a (setup)/C47b
(ingest) on size.

## C46e — Land Ryan's OR rulings + the per-channel pattern capability (added 2026-07-19)

Three parts, per decisions.md's 2026-07-19 OR-5/OR-6/OR-9 rulings and the same-day OR-6 expansion +
import-caveat entries.

**Part 1 — OR-5 ("Most Hated" named mode) + D7 verification.** The mode-selection mechanism itself
(`pipeline_executor.py::_dvsu_mode_profile`, opt-in via an explicit `research_payload.dvsu_mode` field,
never inferred from the title) turned out to ALREADY be landed — Ryan wrote it directly on 2026-07-16,
ahead of the formal 2026-07-19 ruling that rubber-stamped it. What was genuinely missing: the mode's
overrides (opener budget, memorable-fact source) were hardcoded in `_dvsu_mode_profile`, never sourced
from the `quality_rules` table. Landed: a new `dvsu_mode` string-valued `applies_to` scope key
(`quality_rules.py`, parallel to `channel_format`); two new `resolve_dvsu_overrides` keys
(`opener_budget`/`memorable_source`) parsed from two hand-authored seed rows (QL-7-MH/QL-9-MH,
`scripts/seed_dvsu_quality_rules.py::_MOST_HATED_MODE_ROWS`); `_machine_story_plan` now accepts an
optional `dvsu_rule_overrides` param and prefers the table value over the hardcoded default ONLY when
`mode_profile["mode"] == "most_hated"` (never leaks into spec-block); `_load_dvsu_rule_overrides` resolves
the video's own `dvsu_mode` value (`_dvsu_mode_value_for_video`, video-level, never per-title-inference)
and threads it into the scope match. D7 (QL-10 number rendering) turned out to ALSO already be landed
(`_raw_digit_mentions_for_voiceover`/`_written_unit_abbreviations_for_voiceover`, "OR-4 approved" dated
2026-07-16) — mode-agnostic, unblocked now that OR-5 is ruled. Law doc updated: §3 D1/D2/D3/D7 rows
corrected from "open gap"/"pending" to "landed" (D1-D3 per C46c's own finding; D7 per this chunk); §4
OR-5/OR-6/OR-9 rulings recorded with the 2026-07-19 date, mirroring OR-8's existing "RULED" annotation
style.

**Part 2 — OR-6 EXPANDED (`channel_patterns` store + exclusion + import-time proposals).** New table
`channel_patterns` (migration 106, applied LIVE via Supabase MCP against `wrromlupsmyzrrcqlucn`, confirmed
via `information_schema.columns`, mirrored into `schema.sql`): `tenant_id`, `pattern` text, `polarity`
('anti'|'good'), `evidence` jsonb, `source` ('import_analysis'|'launch_analysis'|'manual'), `status`
('proposed'|'confirmed'|'retired'), `confirmed_at`/`confirmed_by`, timestamps. New module
`channel_patterns.py`, three layers (mirrors `quality_rules.py`'s split): (a) pure
`confirmed_anti_video_ids_from_rows` — only `status='confirmed' AND polarity='anti'` rows ever exclude
anything, proven directly rather than trusted to SQL alone; (b) CRUD (`list_patterns`, `create_pattern`,
`bulk_create_patterns`, `update_pattern`, `confirm_pattern`, `retire_pattern`); (c) import-time analysis
(`score_outlier_patterns` — pure, per-metric [vph/ctr/retention] outlier detection against the channel's
OWN median, min-cohort-gated; `propose_patterns_from_analytics`/`run_import_pattern_analysis` — the
DB-touching wrapper that persists `status='proposed'` rows from a tenant's imported `channel_videos`
analytics history). Wired: (1) EXCLUSION — `identity_builder.py::_ranked_videos` (the real style-seed
picker OR-6's own MostHated-Warships example was about) now calls `confirmed_anti_video_ids` and filters
matched `video_id`s out of the ranked candidate pool before slicing to `top_n`; `originality.py`'s
guardrails were traced and deliberately NOT wired — they operate on StoryEngine's own `videos` table
(a different id-space than imported `channel_videos`) for plot-diversity, not style modeling, so an
exclusion hook there today would be permanently-unreachable dead code until P4.2's per-launch trigger
gives it real evidence to match against. (2) IMPORT-TIME PROPOSALS — `channel_dna.py::learn_channel` gains
a sixth learner, `_run_pattern_analysis`, always runs (no optional-input gate, like `channel_format`),
surfaced in the `_last_run` digest alongside the other five. (3) CONFIRM/RETIRE — a thin route
(`routes/channel_patterns.py`, registered in `main.py`) plus a chat surface: the DNA digest card
(`routes/chat.py::_build_dna_digest_card`) gains a `patterns` section (proposed rows only, additive/
optional field) rendered by `ChatCore.tsx`'s `DnaDigestCard` with Confirm/Retire buttons wired through
`_handle_dna_digest_action`'s new `confirm_pattern`/`retire_pattern` actions — nothing takes effect until
Confirm is tapped. Per-launch incremental proposals (P4.2's flywheel) are explicitly NOT built here — the
seam is `create_pattern(..., source="launch_analysis")`, already fully supported by the store.

**Part 3 — OR-9 verification (QL-66).** The checklist's "verify QL-66's landed code already matches,
expected no change" premise did NOT hold: no code anywhere in this repo (StoryEngine's
`_run_channel_formula_thumbnail`/`_transform_channel_thumbnail_spec`, or the legacy skills/video-pipeline
thumbnail bot) implemented the five-locked-phrase + open-rule law at all — StoryEngine's thumbnail
generation is a fully generic, LLM-driven blueprint transform with no series-aware phrase lock. Landed
(genuinely new, minimal): `_DVSU_LOCKED_THUMBNAIL_SERIES` (the five locked phrases, regex-matched against
the title) + `_dvsu_thumbnail_series_warning` (pure function, unit-tested) wired as an ADVISORY-only check
(`bot_activity` log, status="running" since the table's CHECK constraint has no "warning" value) inside
`_run_channel_formula_thumbnail` — deliberately not a hard gate, since this chunk didn't budget to
load-test a hard block on a live generation path. "BY PILOTS"/"BY CREWS" deliberately absent from the
locked set (per Ryan's ruling — not yet proven out as their own series).

**Non-vacuous verification:** `git stash -u` reverted to pre-C46e code, ran the FULL suite: **15 failed,
1554 passed, 1 error** (identical names/count to the stated baseline). With C46e restored: **15 failed,
1624 passed, 1 error** — +70 new tests, zero new failures, zero new errors. `python -m py_compile` clean
on every touched file. Frontend `npx tsc --noEmit` clean; `npm run build` compiles + typechecks
successfully but fails at the unrelated static-prerender step (`NEXT_PUBLIC_API_URL` missing in this
sandbox — a pre-existing environment requirement, not a C46e regression).

### Modified/New Files (C46e)

| Path | Change |
|------|--------|
| `storyengine/backend/migrations/106_channel_patterns.sql` | NEW — `channel_patterns` table, applied live |
| `storyengine/backend/channel_patterns.py` | NEW — store + exclusion resolver + import-time analysis |
| `storyengine/backend/routes/channel_patterns.py` | NEW — thin CRUD/confirm/retire route |
| `storyengine/backend/quality_rules.py` | `dvsu_mode` scope key; `opener_budget`/`memorable_source` in `resolve_dvsu_overrides` |
| `storyengine/backend/scripts/seed_dvsu_quality_rules.py` | `_MOST_HATED_MODE_ROWS` (QL-7-MH/QL-9-MH) appended to the seed set |
| `storyengine/backend/pipeline_executor.py` | `_dvsu_mode_value_for_video`; `_machine_story_plan` gains `dvsu_rule_overrides` param; `_load_dvsu_rule_overrides` threads `dvsu_mode_value`; `_DVSU_LOCKED_THUMBNAIL_SERIES` + `_dvsu_thumbnail_series_warning` (QL-66) wired advisory-only into `_run_channel_formula_thumbnail` |
| `storyengine/backend/identity_builder.py` | `_ranked_videos` excludes confirmed-anti video_ids |
| `storyengine/backend/channel_dna.py` | `_run_pattern_analysis` — sixth `learn_channel` learner |
| `storyengine/backend/routes/chat.py` | digest card gains `patterns`; `_handle_dna_digest_action` gains `confirm_pattern`/`retire_pattern` |
| `storyengine/backend/main.py` | registers `channel_patterns.router` |
| `storyengine/frontend/src/lib/api.ts` | `ChatDnaPatternRow` type; `patterns` field on `ChatCard` |
| `storyengine/frontend/src/components/chat/ChatCore.tsx` | digest card renders proposed patterns + Confirm/Retire |
| `storyengine/schema.sql` | `channel_patterns` table mirrored |
| `storyengine/notes/dvsu-quality-law.md` | §3 D1/D2/D3/D7 corrected; §4 OR-5/OR-6/OR-9 rulings recorded |
| 6 new/extended test files | `tests/test_channel_patterns.py` (NEW), `tests/functional/test_c46e_or5_wiring.py` (NEW), `tests/functional/test_c46e_pattern_exclusion_wiring.py` (NEW), `tests/test_quality_rules.py`, `tests/test_machine_documentary_hold.py`, `tests/functional/test_c46c_seed_dvsu_quality_rules.py`, `tests/functional/test_c41_channel_dna.py`, `tests/functional/test_c42_learn_channel_chat.py` extended |

### Deploy-safety assessment

**Recommend ff-merge candidate.** Every new override/scope key is additive and fails to today's exact
behavior when absent (no tenant has a seeded QL-7-MH/QL-9-MH row until the seed script runs with
`--apply`, which stays a deliberate by-name operation — same posture as C46c). `_machine_story_plan`'s new
third parameter defaults to `None`, byte-identical to its pre-C46e call shape for every existing caller
that doesn't pass it. `channel_patterns` starts empty for every tenant (migration just landed) — the
`learn_channel` sixth learner will report "skipped" until a tenant's `channel_videos` analytics actually
produce an outlier past the threshold, and the exclusion set is empty until a human confirms a proposal,
so `identity_builder._ranked_videos` behaves identically to before for every tenant today. The QL-66
thumbnail check is advisory-only (never blocks). One real risk surface: `_run_pattern_analysis` runs on
EVERY `learn_channel` call (like `channel_format`), adding one more DB query (`channel_videos` fetch) per
run — cheap, no new paid API calls, fails soft.

**Pre-existing, unrelated finding surfaced during this chunk (not fixed, not in scope):** the Supabase
advisory flagged `public.static_reference_cache` and `public.channel_video_retention` as RLS-disabled,
fully exposed to the anon/authenticated PostgREST path. Neither table was touched by C46e — flagging per
the MCP tool's own instruction, not remediating (enabling RLS without policies would block all access;
that decision needs Ryan).

Next: **C47 · MCP setup surface** (unchanged from C46d's own note above) — `channel_patterns` CRUD/confirm/
retire is now also ready for that surface to expose, alongside quality rules/system prompts/channel DNA.

## C47 — MCP setup surface + content-ingest surface (added 2026-07-19)

decisions.md 2026-07-19's TWO entries land as ONE chunk (not split — the checklist's own "may split
C47a/C47b on size" note was pre-authorized but wasn't needed): the "MCP is the setup brain" insight
(expose the SETUP layer through MCP tools) and the "MCP economics" play (the connected agent thinks
on its OWN Claude subscription; StoryEngine accepts the RESULT through the same validated store+
advance paths). Every new tool wraps an EXISTING function/route verbatim — no new business logic,
no parallel store, no forked dispatch — same discipline C26/C27 established for the verb registry.

**Setup tools (16, all free — no `confirm_token`, every write attributed):**
`get_channel_dna` (wraps `channel_dna._current_identity`), `learn_channel_start`/`learn_channel_
status` (wrap `routes.channel_dna.start_learn_channel`/`get_learn_channel_status` — the SAME
BackgroundTasks ack-now shape the HTTP door uses, busy-claim state passes through unreinterpreted),
`list_quality_rules`/`upsert_quality_rule`/`deactivate_quality_rule` (wrap `quality_rules.py`'s CRUD
— `upsert_quality_rule` stamps a NEW `source="mcp_agent"` value, added to `quality_rules.SOURCES`,
distinguishing an agent-written rule from one typed through chat/parsed from a doc), `list_channel_
patterns`/`confirm_channel_pattern`/`retire_channel_pattern` (wrap `channel_patterns.py`'s CRUD/
confirm/retire — the REAL `confirmed_by` column, not just a log line, carries the calling agent's
name: OR-6's human-confirm gate, an agent acting for its owner, attributed), `get_script_template`/
`set_script_template` (wrap `routes.script_templates.list_templates`/`analyze_and_save_template` —
the tool checks for an existing template first and reports "replaced" vs "saved" honestly, same
distinction `channel_dna.py`'s own learner step already surfaces), `list_script_profiles` (wraps
`routes.script_profiles.list_script_profiles`), `get_system_prompts`/`set_system_prompt` (wrap
`routes.system_prompts.list_prompts`/`upsert_prompt` — see the honest scoping note below on C43
provenance), `set_render_style`/`set_style_preset` (wrap the generic `PATCH /api/videos/{id}` path).

**`script_profile`/`budget_cap` are deliberately NOT duplicated as `set_script_profile`/
`set_budget_cap`:** these already exist as free MCP verb tools, auto-generated from `actions.ACTIONS`
since C27 (`_verb_tools()`) — the checklist's own "existing verbs/columns" phrasing. Adding a second,
differently-shaped tool for the same write path would be redundant surface, not a new capability.

**A real gap found and fixed while tracing `set_style_preset`:** `videos.style_preset_id` had NO
write path after video creation at all — `create_video` accepted it, but the generic `PATCH
/api/videos/{id}` route's `allowed_fields` allowlist never included it (unlike `render_style`/
`script_profile`/`max_spend`, which all got that same-chunk treatment in C13b/C24/C36). Fixed
minimally: `style_preset_id` added to `allowed_fields`, reusing `_resolve_style_preset_id` — the
SAME catalog validator `create_video` already calls — verbatim (2-line change, `routes/videos.py`).
`set_style_preset` (and, for free, the web UI/any future caller) can now actually clear or change a
video's visual-profile engine post-creation.

**Ingest tools (2, free to run — the thinking already happened on the caller's own subscription):**
- `submit_research(video_id, payload)` — new `research_ingest.py` module (mirrors `user_script.py`'s
  per-domain layering from C46d). Traced the REAL shape `run_research` stores
  (`pipeline_executor.py::run_research`'s own save tail, `research_payload` JSONB — no dedicated
  Pydantic schema exists; it's whatever the research agent + roster-hold steps produce) and every
  downstream reader that assumes list/dict types without re-checking (`_roster_validation`,
  `enrich_research_payload_readiness`, `_machine_bucket_summary`). `_validate_research_shape` catches
  a malformed submission (wrong-typed `unit_roster`/`unit_research_cards`/`machine_discovery_
  buckets`/etc.) with a concrete field name BEFORE any DB write, instead of a later opaque crash deep
  in a pipeline stage. Reuses `pipeline_executor._roster_validation` VERBATIM (not reimplemented) as
  the accept/reject gate for machine-roster/documentary titles — same deterministic warnings/gaps a
  real research run would produce. Explicit scope boundary, stated in the module docstring: this does
  NOT run `_run_unit_research_hold` (the expensive live per-machine source-fetch/verification pass) —
  that's a distinct, separately-billable action, not a shape or gate check; an externally-submitted
  payload is trusted on the roster gate's strength, the same way `set_user_script` trusts a creator's
  verbatim text. On a pass: saves via the EXACT SAME `UPDATE videos SET research_payload=...,
  thesis=..., executive_hook=..., status='ready_for_scripting', research_skipped=FALSE` `run_research`
  itself issues. **Honest gap flagged, not silently invented around:** unlike `videos.script_source`,
  `research_payload` has no sibling provenance column — `source` (the submitting agent's identity) is
  logged, not persisted, since adding a new schema column was past this chunk's "no new logic" scope.
- `submit_script(video_id, scenes)` — thin wrapper over C46d's `user_script.accept_external_script`
  (`source="agent_submitted"`), already built and waiting for exactly this call site. No new logic
  here at all; the accept/reject/warn matrix is entirely C46d's.

**Honest scoping note — C43 provenance and `set_system_prompt`:** the checklist flagged "the C43
provenance stamping applies" for system prompts. Traced: C43's stamping (`routes/system_prompts.py::
generate_prompts` → `channel_dna_meta.stamp_identity_write(learner="system_prompts")`) is scoped
SPECIFICALLY to the `style_description`/`channel_identity` write inside the "generate all 6 from a
style description" flow — `tenant_prompt_defaults` (what `set_system_prompt`/`upsert_prompt` actually
writes) has no provenance column of its own to stamp at all (just `prompt_key`/`prompt_text`/
`updated_at`). `set_system_prompt` therefore logs its caller (same as the other no-column setup
writes) rather than inventing a stamp target that doesn't exist — flagged here rather than silently
assumed to already be covered.

**Attribution, concretely:** `confirm_channel_pattern`/`retire_channel_pattern` pass `caller` into
the REAL `confirmed_by` column (structural, DB-visible); `upsert_quality_rule` passes
`source="mcp_agent"` into the REAL `source` column (structural, DB-visible); every other setup write
(`learn_channel_start`, `set_script_template`, `set_system_prompt`, `set_render_style`,
`set_style_preset`, `deactivate_quality_rule`) logs the caller via a new `_log_setup_write` helper —
no column exists on those tables to stamp it into, an honest gap rather than a schema change past
this chunk's scope.

**No media URLs (C25a hold), verified:** `channel_identity` (what `get_channel_dna` returns) is
structurally free of generated-media-asset URLs by `channel_dna_meta.py`'s own design (voice/hooks/
structure/thumbnail-formula TEXT fields only) — the one text field that legitimately carries a URL,
`reference_video_style.source_url`, is a creator-supplied YouTube reference link (an INPUT the user
gave, not a generated OUTPUT asset the C25a hold targets), same distinction the module docstring
already draws. Pinned by a grep-style test over every new tool's description/schema for
`preview_url`/`thumbnail_url`/`image_url`/`video_clip_url`, plus a byte-identity round-trip test on
`get_channel_dna`.

### Verification

42 new tests, `tests/functional/test_c47_mcp_setup_and_ingest.py`: tool-surface pins (every new name
present, `script_profile`/`budget_cap` NOT duplicated, S5-2 memory-tool exclusion still holds against
the larger v3 surface, no setup/ingest tool carries `confirm_token`, `learn_channel_start`'s
description states its real BYOK cost); "same callable" proof for every setup tool (patches the REAL
underlying module/route function each MCP handler wraps — `routes.channel_dna.start_learn_channel`,
`quality_rules.create_rule`/`list_all_rules`/`deactivate_rule`, `channel_patterns.confirm_pattern`/
`retire_pattern`/`list_patterns`, `routes.script_templates.analyze_and_save_template`/`list_
templates`, `routes.script_profiles.list_script_profiles`, `routes.system_prompts.list_prompts`/
`upsert_prompt`, `routes.videos.update_video` — and asserts the exact tenant-scoped call args, not
just "a call happened"); attribution proofs (`source="mcp_agent"` reaches `create_rule`,
`confirmed_by=caller` reaches `confirm_pattern`/`retire_pattern`); `submit_script`'s accept/reject
matrix through the real (patched-at-the-module-level) `user_script.accept_external_script`;
`submit_research`'s shape-validation unit tests (bad list/dict-typed fields raise with the concrete
field name), the roster-gate reuse (patches `pipeline_executor._roster_validation` itself, proving no
reimplementation), and the save+advance path on a pass (asserts the exact `UPDATE videos SET...` args
`run_research` itself would write); a pinned regression test on `routes/videos.py::update_video`'s
source asserting `style_preset_id` stays in `allowed_fields` with its validator wired.

Non-vacuous via plain `git stash` (tracked source files only, plus the new untracked `research_
ingest.py` moved aside so the import fails too — the new test file itself stays in place): the test
module fails to even COLLECT (`ModuleNotFoundError: No module named 'research_ingest'`), confirming
every one of the 42 tests depends on real, non-trivial new code, not a vacuously-passing assertion.
Restored, full suite: **1666 passed, 15 failed, 1 error** = baseline (1624/15/1) + exactly 42, zero
new failures, identical failure names to the prior chunk's own baseline. `python -m py_compile` clean
on all 4 touched/new backend `.py` files (`routes/mcp.py`, `routes/videos.py`, `quality_rules.py`,
`research_ingest.py`).

Frontend: **untouched** — zero files changed under `storyengine/frontend/`. This chunk is entirely
backend (MCP tool registry + one small pipeline-adjacent module), dark behind `MCP_ENABLED` same as
C26/C27; there is no UI surface for setup/ingest tools by design (checklist: "NO UI. Everything still
dark behind MCP_ENABLED").

Live round-trip (a real MCP client calling the setup + ingest tools against a real tenant, including
a real `learn_channel_start` BYOK spend and a real `submit_script`/`submit_research` accept+reject
pair) deferred to `tasks/live-verification-queue.md` §C29 Step 5b (folded into the existing MCP
go-live runbook, not a new fragment — same reasoning C26/C27/C28 already established: one deploy, one
flag flip, one client connection, walk every deferred check together).

### Modified/New Files (C47)

| Path | Change |
|------|--------|
| `storyengine/backend/routes/mcp.py` | +16 setup tools, +2 ingest tools, `_dispatch` routing, module docstring TOOL SURFACE v3 section |
| `storyengine/backend/routes/videos.py` | `style_preset_id` added to `update_video`'s `allowed_fields`, validated via the existing `_resolve_style_preset_id` |
| `storyengine/backend/quality_rules.py` | `SOURCES` gains `"mcp_agent"` |
| `storyengine/backend/research_ingest.py` | NEW — `accept_submitted_research` (shape validation + roster-gate reuse + save/advance) |
| `storyengine/backend/tests/functional/test_c47_mcp_setup_and_ingest.py` | NEW — 42 tests |
| `tasks/live-verification-queue.md` | §C29 gains Step 5b (setup + ingest live session), fold-ins list gains C47 |

### Deploy-safety assessment

**Recommend ff-merge candidate.** Still dark: every new tool is registered on the SAME `routes/
mcp.py` router that only exists when `MCP_ENABLED=true` (unchanged default/unset behavior — 404,
structurally absent). `style_preset_id`'s new allowlist entry is the one change reachable outside the
MCP flag (the ordinary web UI's `PATCH /api/videos/{id}` also gains this field) — strictly additive
(a field that could never be set before now can; nothing that used to work changes), and re-validated
through the SAME catalog check `create_video` already trusted, so a bad id still 400s exactly like it
always has at creation time. `quality_rules.SOURCES` gaining `"mcp_agent"` is additive (existing
values unaffected). Every ingest tool is dead code until `MCP_ENABLED=true` AND a caller mints an
agent token — same posture C26/C27 shipped with.

Next: **P4.2 tenant-autopilot SCOUT (Explore, per the Phase-4 outline)** — the orchestrator
dispatches it.

---

## C48–C51 — P4.2 tenant-autopilot SCOUT + dial + candidate auto-launch (see tasks/todo.md / tasks/storyengine-wiring-fix-checklist.md for detail)

Note: these four chunks landed without a SYSTEM_STATE.md entry — `tasks/todo.md`'s "Also done" log and
`tasks/storyengine-wiring-fix-checklist.md`'s checkbox entries are the durable record for this stretch
(commit 97c7d7a is C51). Flagging the gap here rather than silently continuing it; C52 below resumes
logging to this file since it creates a new file (the structural-change rule's trigger).

## C52 — autopilot proposals surface + minimal in-app notify (P4.2-c, added 2026-07-19)

The read/decide surface for C51's `autopilot_proposals` table (propose_only dry-run picks): reuses the
existing candidates/launch machinery end to end, adds no new notification infra.

**Backend:** `autopilot_proposals.py` gains `list_proposals`/`count_pending`/`get_proposal`/
`mark_decided` (the last is the only writer of the 'proposed' -> 'accepted'/'dismissed' transition, an
atomic `WHERE status='proposed'` UPDATE) and a best-effort `bot_activity` notify row per new proposal
(reuses the EXISTING activity-feed table — no new table). `routes/autopilot.py` gains `GET /proposals`,
`POST /proposals/{id}/accept` (calls the EXISTING `launch_candidate` FIRST, only marks 'accepted' after
it succeeds — a failed launch never reaches `mark_decided`, so the proposal survives untouched; refuses
if the C50 kill switch is tripped), `POST /proposals/{id}/dismiss`, and an additive
`AutopilotState.pending_proposals_count` field on the existing summary response. `routes/mcp.py` gains
`list_autopilot_proposals` (read) / `accept_autopilot_proposal` / `dismiss_autopilot_proposal` (free,
`decided_by='mcp_agent'`) — all three call the SAME `routes.autopilot.accept_proposal`/`dismiss_proposal`
functions the HTTP door uses. `accept_autopilot_proposal` classifies as free (no `confirm_token`) — it's
not an `actions.ACTIONS` verb, and it re-triggers the SAME unguarded `launch_candidate` path a human's
Launch click (and C51's auto_draft dial level) already call with zero gate; every PAID stage the
resulting pipeline reaches still enforces its own confirm/needs_approval gate independently.

**Frontend:** `/autopilot` page gains a "Proposals" card (title, confidence + VPH/Freshness/Intel
breakdown line, "proposed Xh ago", Accept/Dismiss buttons wired via React Query) and a gold "N proposals
pending" header pill. Mirrors the existing `GlassCard`/`StatusPill` idiom (no `web-design-system` skill
exists in this environment — noted, not invented).

### Verification

27 new tests (`storyengine/backend/tests/test_c52_autopilot_proposals_surface.py`), non-vacuous via
`git stash` (all 27 fail against pre-C52 code, all 27 pass after). Full suite: **1714P/15F/1E** — the
same 15 pre-existing failures/1 error as the 1687P/15F/1E baseline, zero new (1687+27=1714). Frontend
`npx tsc --noEmit` clean; `npm run build` succeeds (confirmed by temporarily setting
`NEXT_PUBLIC_API_URL` — this sandbox has no `.env.production`, a pre-existing gap unrelated to this
chunk, reproduced identically with C52's frontend changes stashed out). No live DB/backend in this
sandbox — Playwright live-run deferred, recipe added at `tasks/live-verification-queue.md` §C52.

### Modified/New Files (C52)

| Path | Change |
|------|--------|
| `storyengine/backend/autopilot_proposals.py` | +`list_proposals`/`count_pending`/`get_proposal`/`mark_decided`, notify-on-create |
| `storyengine/backend/routes/autopilot.py` | +`GET /proposals`, +`POST /proposals/{id}/accept\|dismiss`, +`accept_proposal`/`dismiss_proposal` shared functions, `AutopilotState.pending_proposals_count` |
| `storyengine/backend/routes/mcp.py` | +3 autopilot-proposal tools, `_dispatch` routing, module docstring TOOL SURFACE v4 section |
| `storyengine/backend/tests/test_c52_autopilot_proposals_surface.py` | NEW — 27 tests |
| `storyengine/frontend/src/lib/api.ts` | +`AutopilotProposal` type, +3 fetch functions, `AutopilotState.pending_proposals_count` |
| `storyengine/frontend/src/app/autopilot/page.tsx` | +Proposals card, +pending-count header pill, `ProposalRow` component |
| `tasks/live-verification-queue.md` | +§C52 live-check recipe |

### Deploy-safety assessment

**Recommend ff-merge candidate.** Backend is additive/skew-safe: new routes, new Pydantic fields with
defaults, no changed response shapes on existing fields — an old frontend against a new backend simply
ignores `pending_proposals_count` and never calls the new routes. New frontend against an old (pre-C52)
backend: the Proposals card's `useQuery` 404s on `/api/autopilot/proposals` and renders the existing
`ErrorCard` (with retry) rather than crashing the page — acceptable degraded UX for the narrow
backend-merges-first/frontend-ships-later window, not a break. `accept_autopilot_proposal`'s free
(no-confirm-token) classification is deliberate and reasoned in `routes/mcp.py`'s new "AUTOPILOT
PROPOSAL TOOLS" section — flagged here in case a future reviewer wants to re-litigate it.

Known gap (not fixed here, matches the existing `launch_candidate`/upload precedent already documented
in `docs/failure-modes.md`'s per-stage resumability table): two concurrent `accept` calls on the SAME
proposal could both pass the initial `status='proposed'` check before either's `launch_candidate` call
completes its `competitor_videos.our_video_id` write, racing to create two videos from one candidate.
`mark_decided`'s atomic guard prevents the proposal BOOKKEEPING from double-writing, but doesn't prevent
the underlying double-launch — that race lives in `launch_candidate` itself, pre-existing, out of this
chunk's scope.

**FIXED by C53 below** (`launch_candidate`'s atomic claim) — this known gap is closed, see §C53.

## C53 — auto-draft verification (audit-then-wire) + launch_candidate double-launch race fix (P4.2-d, added 2026-07-19)

**Audit (half 1) — is the auto-draft money path gated at least as strictly as a human-clicked Launch?**
Traced `routes/autopilot.py::launch_candidate` end to end (it's the ONE launch function — a human
clicking "Launch" on `/autopilot` or `/calendar`, C52's `accept_proposal`, and C51's auto_draft dial
level all call this exact same function, so there is no separate "human path" to be stricter than;
whatever gates run here apply identically to every caller):

1. **`actions.budget_check`** (the optional per-video `max_spend` cap) is NOT consulted anywhere on
   this path — it only exists inside `routes/chat.py`'s confirm-card flow and `routes/mcp.py`'s tool
   flow (both quote-then-tap doors), never inside `pipeline_executor.py`'s stage-running code that
   `launch_candidate`'s background `_run_full_pipeline` loop actually drives. Since this applies
   identically whether triggered by a human's Launch click or the auto_draft loop, it does NOT violate
   the audit's actual invariant (auto ⪰ human strictness) — it's a pre-existing gap shared by both
   doors, not a new asymmetry, so left unfixed per the chunk's explicit scope (only wire an asymmetry,
   don't invent a new feature). Flagged here for a future chunk: `max_spend` caps are silently
   unenforced on any video driven through `run_next_step`/`_run_full_pipeline` rather than through
   chat/MCP.
2. **The approval-gate stop** (`PipelineExecutor.APPROVAL_GATE_STATUSES`, `pipeline_executor.py`
   ~L13304-13328: `ready_for_voice`/`ready_for_images`/`ready_for_thumbnail`) fires identically for
   auto-launched videos — `_run_full_pipeline`'s loop calls the SAME `executor.run_next_step(video_id)`
   a human's "Run Next Step" click calls, and breaks on `status in ("failed", "needs_approval",
   "idle")`. It surfaces in the EXISTING approval UI with zero new plumbing: the stop is just the
   `videos.status` column landing on one of those 3 values, which `frontend/src/lib/next-action.ts`
   (read by `pipeline/[videoId]/page.tsx`, `PipelineStepper.tsx`, the dashboard) already maps to an
   approval CTA — an auto-launched video reaching `ready_for_voice` shows the identical "needs
   approval" banner a human-created video would.
3. **`check_plan_limits`** (the 402 plan-limit gate) was the one genuine bypass. The regression lock
   (`tests/functional/test_plan_limits_enforcement_lock.py`) covers exactly 3 UI create routes
   (`videos.py::create_video`, `pipeline.py::create_idea`, `discovery.py::launch_idea`) —
   `launch_candidate` was never in that list and never called `check_plan_limits` at all, so a
   free-plan tenant's autopilot could create unlimited videos via auto_draft with zero human
   double-click to notice. **Wired**: `launch_candidate` now calls
   `check_plan_limits(tenant_id, "video")` as the FIRST thing in the function (before the candidate
   fetch, matching `discovery.py::launch_idea`'s exact placement) and `increment_usage(tenant_id,
   "videos_created")` right after the video INSERT (matching the same house pattern). Added as a 4th
   entry point to `test_all_video_create_entrypoints_guarded` in the regression lock test, plus a
   dedicated behavioral test (`tests/test_c53_launch_candidate_gates.py`) proving the gate actually
   fires (AST inspection alone can't prove a call fires the right side effects at the right time).

**Race fix (half 2) — the double-launch race documented in §C52's "Known gap" above.** `our_video_id`
can't double as a claim sentinel (it's a real FK to `videos(id)`, migration 080 — no sentinel UUID
exists before a video row does), so the fix is a plain new claim column rather than repurposing that
one. Migration 109 (`competitor_videos.launch_claimed_at TIMESTAMPTZ`, applied LIVE via Supabase MCP
against project `wrromlupsmyzrrcqlucn`, confirmed via `information_schema.columns`) backs an atomic
claim in `launch_candidate`:

```sql
UPDATE competitor_videos SET launch_claimed_at = NOW()
WHERE id = $1 AND tenant_id = $2 AND our_video_id IS NULL
  AND (launch_claimed_at IS NULL OR launch_claimed_at < NOW() - INTERVAL '10 minutes')
RETURNING id
```

Only one concurrent caller can get a row back — Postgres's row lock serializes the two UPDATEs, and
the second one's WHERE re-evaluates against the now-claimed row and matches nothing. The loser gets a
clean `409 "Candidate already launched or a launch is already in progress"` before touching anything
paid; zero second video row is created. `launch_candidate`'s body past the claim was split into a
helper (`_do_launch_candidate`) wrapped in try/except: on success, the final `UPDATE ... SET
our_video_id = $1, launch_claimed_at = NULL` makes the launch permanent; on ANY exception before that
point, an except block clears `launch_claimed_at` back to NULL (guarded by `our_video_id IS NULL`, so
it can never clobber a launch that actually succeeded) and re-raises — a failed launch releases the
candidate instead of wedging it forever. The 10-minute window in the claim's WHERE clause is a
belt-and-suspenders sweep for the one case the except-block release can't reach: the process getting
killed mid-request, between acquiring the claim and running the except handler.

### Verification (C53)

6 new tests (`tests/test_c53_launch_candidate_gates.py`): plan-limit gate fires before any query,
`increment_usage` fires after the insert, a genuine concurrent race (`asyncio.gather` with a
deliberately-forced interleave point so both callers reach the claim check before either mutates —
documented inline in the test as approximating what Postgres's row lock guarantees for the real single
UPDATE statement) resolves to exactly one winner + one 409 loser + exactly one video row, an
already-launched candidate is rejected via the fast 400 path, a failure after the claim releases it,
and a retry right after that failure succeeds (proving the release isn't cosmetic). Non-vacuous via
`git stash` on `routes/autopilot.py`: 4 of 6 fail against pre-C53 code (the other 2 pass either way —
they're not testing the new gates specifically). `test_plan_limits_enforcement_lock.py`'s
`test_all_video_create_entrypoints_guarded` also extended with `launch_candidate` as a 4th entry point,
independently confirmed non-vacuous the same way (fails with `launch_candidate` stashed out). Full
backend suite: **1720P/15F/1E** = baseline (1714P/15F/1E) + exactly 6 new tests, same 15 pre-existing
failures/1 error, zero new failures. `python -m py_compile` clean on all touched/new files. No frontend
touched (`git status` confirms zero `storyengine/frontend/` diffs) — matches the chunk's `[U]` scope
(none this chunk; the approval UI already renders the stop via the existing status-driven components,
confirmed by audit item 2 above, not built here).

### Modified/New Files (C53)

| Path | Change |
|------|--------|
| `storyengine/backend/routes/autopilot.py` | `launch_candidate` gains `check_plan_limits`/`increment_usage` + the atomic `launch_claimed_at` claim; body split into `_do_launch_candidate` helper for the try/except release-on-failure wrap |
| `storyengine/backend/migrations/109_competitor_launch_claim.sql` | NEW — `competitor_videos.launch_claimed_at TIMESTAMPTZ`, applied live |
| `storyengine/backend/tests/test_c53_launch_candidate_gates.py` | NEW — 6 tests |
| `storyengine/backend/tests/functional/test_plan_limits_enforcement_lock.py` | `launch_candidate` added as a 4th guarded entry point |

### Deploy-safety assessment

**Recommend ff-merge candidate.** Additive migration (new nullable column, `ADD COLUMN IF NOT EXISTS`,
idempotent). `check_plan_limits` now runs on a path that previously had none — this DOES change
behavior for any tenant currently AT or OVER their plan limit using autopilot launch (they'll now get a
402 instead of an unlimited extra video) — this is the intended fix, not a regression, but flagging the
behavior change explicitly since the playbook's ff-merge bar asks for "the default/existing path is
provably unchanged": for a tenant UNDER their limit (the default/common case), behavior is
byte-identical. The race-fix claim column is a no-op for every existing row (`launch_claimed_at` starts
NULL everywhere) and only ever matters under actual concurrent launch attempts, which is exactly the
bug it fixes.

## C54 — per-tenant weekly budget ceiling + kill-switch writers + closing the kill-switch queue-drain gap (P4.2-e, added 2026-07-19)

Two things this chunk builds on top of C50's dial columns (migration 107, `autopilot_dial.py` read
accessor): (1) the FIRST writers for `weekly_budget_cap`/`dial_level`/kill-switch, and (2) closing a
real gap C51 flagged — the kill switch only gated the C51 candidate path, never the pre-existing
`production_queue` drain (`routes/queue.py::auto_produce_next`), which is unconditionally paid and had
zero dial awareness of its own.

**`storyengine/backend/autopilot_dial.py`** (still the one home for the dial) gains:
- `get_weekly_spend(tenant_id)` — sums `generation_ledger.actual_cost` (NOT `videos.total_cost`, which
  is a per-video CUMULATIVE lifetime rollup with no "since when" axis) since `weekly_spend_reset_at`,
  after first rolling the window forward via `_ensure_reset_window` (an atomic
  `INSERT ... ON CONFLICT (tenant_id) DO UPDATE ... WHERE weekly_spend_reset_at IS NULL OR < now() -
  interval '7 days'` — the WHERE guard means a losing concurrent caller's conflicting statement
  re-evaluates the guard once the winner commits and finds it already rolled, so it becomes a no-op).
- `check_weekly_budget(tenant_id) -> (ok, spent, cap)` — cap `None` is always ok (no cap set, today's
  default for every tenant); breach is `spent >= cap` (exact-boundary inclusive).
- `trip_kill_switch(tenant_id, reason) -> bool` — the FIRST kill-switch writer. Idempotent: the upsert's
  `WHERE kill_switch_tripped_at IS NULL` guard means a second trip in the same tick never overwrites the
  FIRST recorded reason, and the bot_activity notify (loud, never a silent pause) only fires when this
  call actually tripped it (return value signals that).
- `clear_kill_switch(tenant_id)` — the ONLY clearer. Called exclusively from the new
  `POST /api/autopilot/kill-switch/reset` route (and its MCP mirror) — never automatically.

**`storyengine/backend/main.py`** — the per-tenant tick inside `_auto_produce_queue`'s loop was
extracted into `_produce_for_tenant(tenant_id)` so the gating is independently testable. Reads the dial
ONCE per tenant per tick: a tripped kill switch OR a budget breach skips the tenant ENTIRELY — the queue
drain (`routes.queue.auto_produce_next`) AND the candidate fallback (`autopilot_launch.
auto_launch_best_candidate`) both — closing the gap described above. A breach trips the switch (never a
silent pause) before skipping.

**`storyengine/backend/autopilot_launch.py`** — the `auto_draft`/`full_auto` branch gains its OWN
defense-in-depth `check_weekly_budget` call immediately before calling `launch_candidate` (candidate
scoring above it can take real time, so the loop-level check could be stale by then). The `propose_only`
branch returns before this code is ever reached, so a budget breach structurally cannot block a free
proposal — pinned by `test_propose_only_never_reaches_the_budget_check` (the budget-check fake raises
`AssertionError` if called at all in that branch).

**`storyengine/backend/routes/autopilot.py`**:
- `ConfigUpdate`/`POST /config` now accepts `dial_level` (validated against `DIAL_LEVELS`, 400 on a bad
  value) and `weekly_budget_cap` (validated `>0` or `null` to clear — `null`-vs-"omitted" is
  distinguished via Pydantic's `model_fields_set`, not an `is not None` check, so a caller CAN explicitly
  clear an existing cap). The response now re-reads `get_autopilot_dial` + `get_weekly_spend` after the
  write so it reflects what was ACTUALLY saved (a pre-existing gap: before this chunk, `/config`'s
  response never surfaced real dial state at all — it silently returned the model's hardcoded defaults
  even after a `/summary` call showed the true values).
- `AutopilotConfig` gains `weekly_spent` (additive, fail-soft to `None` on a ledger-sum hiccup) — surfaced
  on both `/summary` and `/config`'s response.
- NEW `POST /api/autopilot/kill-switch/reset` — the explicit human re-enable, attributed via
  `AuthUser.email`, drops a `bot_activity` row naming who cleared it.

**`storyengine/backend/routes/mcp.py`** — two new tools, both classified FREE (no `confirm_token`):
`set_autopilot_dial` (same bucket as `set_render_style`/`set_style_preset` — a routing/config guardrail,
not a spend itself) and `reset_autopilot_kill_switch` (a real judgment call per the checklist's own
framing — decided FREE by the SAME precedent as `accept_autopilot_proposal`: it isn't an
`actions.ACTIONS` verb so the confirm gate doesn't wrap it, it only re-arms EXISTING unattended paths
that already ran ungated, and every individual paid stage those paths reach still enforces its own gate
— clearing the switch does not bypass a future re-trip if spend is still over cap). Both dispatch through
the SAME `routes.autopilot.update_config`/`reset_kill_switch` functions the HTTP doors use.

**`storyengine/frontend/src/app/autopilot/page.tsx`** — new "Autonomy & Budget" card (3-option dial
selector with one-line explanations, weekly budget cap input with "spent $Y of $X this week"/"no cap
set" line) plus a prominent red kill-switch banner (reason, when, "Re-enable" button) shown above the
existing enabled/disabled banner when tripped. `src/lib/api.ts` gains the matching `AutopilotConfig`
field additions (all optional, so an older backend simply omits them) and
`resetAutopilotKillSwitch()`.

### Verification (C54)

29 new tests (`tests/test_c54_weekly_budget_kill_switch.py`) + 4 more added to
`tests/test_c51_candidate_auto_launch.py` (2 pre-existing tests updated to patch the new pre-launch
budget check; 2 new: budget-breach-trips-and-skips-launch, propose_only-never-reaches-the-check; the
stale main.py wiring test was retargeted at the extracted `_produce_for_tenant` plus one new test
proving `_auto_produce_queue`'s loop actually calls it). Non-vacuous via `git stash` on the 5 touched
backend files: all 29 new tests fail (mostly with `RuntimeError: DATABASE_URL not set` — the stashed
code has no monkeypatchable functions to intercept) when stashed, pass restored. Full backend suite:
**1752P/15F/1E** = baseline (1720P/15F/1E) + 32 new tests (29 + 3 net new in test_c51, one renamed),
same 15 pre-existing failures + same 1 error, zero new failures. Frontend: `npx tsc --noEmit` clean,
`npm run build` succeeds (with `NEXT_PUBLIC_API_URL` set — a pre-existing, unrelated production-build
requirement the sandbox doesn't set by default). No Playwright run (sandbox has no route to a live
backend) — manual verification recipe appended to `tasks/live-verification-queue.md` §C54.

### Modified/New Files (C54)

| Path | Change |
|------|--------|
| `storyengine/backend/autopilot_dial.py` | Adds `get_weekly_spend`, `check_weekly_budget`, `trip_kill_switch`, `clear_kill_switch`, `_ensure_reset_window`, `_rows_affected`, `_notify_kill_switch_tripped` |
| `storyengine/backend/main.py` | `_auto_produce_queue`'s per-tenant body extracted into `_produce_for_tenant` (kill-switch + budget gate covers queue drain AND candidate fallback) |
| `storyengine/backend/autopilot_launch.py` | `auto_draft`/`full_auto` branch gains its own pre-launch `check_weekly_budget` re-check |
| `storyengine/backend/routes/autopilot.py` | `ConfigUpdate`/`update_config` accept `dial_level`/`weekly_budget_cap`; response re-reads real dial state + `weekly_spent`; NEW `POST /kill-switch/reset` route + `KillSwitchResetResult` model |
| `storyengine/backend/routes/mcp.py` | NEW `set_autopilot_dial` / `reset_autopilot_kill_switch` tools + handlers, wired into `TOOLS`/`_dispatch` |
| `storyengine/backend/tests/test_c54_weekly_budget_kill_switch.py` | NEW — 29 tests |
| `storyengine/backend/tests/test_c51_candidate_auto_launch.py` | 2 tests updated (new budget-check patch required), 2 new tests, main.py wiring test retargeted + 1 new wiring test |
| `storyengine/backend/tests/test_autopilot_dial_route.py` | `weekly_spent` added to the fixture + one assertion |
| `storyengine/frontend/src/app/autopilot/page.tsx` | NEW "Autonomy & Budget" card + kill-switch banner |
| `storyengine/frontend/src/lib/api.ts` | `AutopilotConfig` dial/budget/kill-switch fields; NEW `resetAutopilotKillSwitch()` + `KillSwitchResetResult` |

No new migration — C50's migration 107 already added every column this chunk writes to.

### Deploy-safety assessment

**Skew note (backend deploys hourly ahead of frontend — separate `--with-frontend` build):** the new
`weekly_spent`/dial/kill-switch fields on `AutopilotConfig` are all additive and optional on both the
Pydantic model and the TypeScript interface — an old frontend against the new backend simply ignores the
new fields (unchanged rendering); a stale frontend calling the NEW `POST /kill-switch/reset` route or
`set_autopilot_dial`/`reset_autopilot_kill_switch` MCP tools before a `--with-frontend` deploy is a
non-issue since nothing calls them until the new frontend ships. Backend-only deploy is safe standalone;
frontend needs the backend's new routes to already exist (correct order — backend leads).

**Recommend ff-merge candidate.** No migration. For every tenant that has never set a `dial_level`
other than the default or a `weekly_budget_cap` (100% of tenants today, since C50 only added the columns
with no writer until now), `check_weekly_budget` always returns `(True, spent, None)` — the cap-None
branch — so `_produce_for_tenant`'s new budget gate is a provable no-op on the default path; only a
tenant that explicitly sets a cap via the new `/config` fields or MCP tool can ever trip it. The kill
switch queue-drain fix is a strict bug fix (a tripped switch skipping only half the automation was never
intended behavior) and cannot fire for any tenant that has never been tripped (100% of tenants today,
since C50 added the column with nothing to trip it before this chunk).

## C54b — hardening: "no autonomy without a ceiling" server-side invariant (orchestrator review, added 2026-07-19)

Orchestrator review of C54 found one real gap: nothing stopped `dial_level` being raised to
`auto_draft`/`full_auto` with `weekly_budget_cap` still `NULL` — `check_weekly_budget`'s NULL-cap-always-ok
posture (correct for `propose_only` tenants) then meant unattended spending with NO ceiling, reachable
via the free `set_autopilot_dial` MCP tool with no confirm.

**`storyengine/backend/autopilot_dial.py`** gains `validate_dial_change(current, *, new_dial_level,
cap_provided, new_cap) -> Optional[str]` — the ONE shared invariant both writers call. It computes the
EFFECTIVE dial_level/cap the change would produce (the new value if supplied, else whatever's already on
the row) and rejects (returns an error string; `None` = valid) if the effective state is elevated with no
cap. One computation covers all four shapes: raise-with-no-cap-anywhere (rejected), raise-with-cap-
supplied-in-the-same-call (allowed), clear-an-existing-cap-while-elevated (rejected), clear-the-cap-AND-
lower-to-propose_only-in-the-same-call (allowed).

**Writers**: `routes/autopilot.py::update_config` calls `validate_dial_change` (400 on violation) after
its existing `dial_level`/`cap>0` checks, using the CURRENT row (`get_autopilot_dial`) as the baseline.
`routes/mcp.py::set_autopilot_dial` needed NO new call — it already dispatches straight through
`update_config`, so the invariant is enforced transitively with zero parallel logic (confirmed by new
end-to-end tests that exercise the real `update_config`, not a mock).

**Runtime belt-and-suspenders** (any row that predates/escapes the writers): `autopilot_launch.py`'s
`auto_launch_best_candidate` computes an `effective_dial_level` right after the kill-switch check — an
elevated `dial_level` with no cap demotes to `"propose_only"` for that tick (loud `logger.warning`, never
a kill-switch trip — this is a config anomaly, not a spend breach) — and the branch decision below uses
`effective_dial_level`, not the raw `dial.dial_level`. `main.py::_produce_for_tenant` logs the SAME
condition (visibility on every tick regardless of which path runs) but doesn't itself branch on
dial_level — the queue drain never has, and autopilot_launch.py does its own demotion internally, so a
loop-level behavior change would be redundant.

**Kill-switch reset transparency**: `KillSwitchResetResult` gains `previous_kill_switch_reason`/
`previous_kill_switch_tripped_at` — the trip THIS call just cleared (`None`/`None` if it was a harmless
no-op). `reset_kill_switch` reads the prior dial state BEFORE clearing. The bot_activity notify message
now includes the prior reason too. This is what makes `reset_autopilot_kill_switch` staying FREE (no
confirm_token) defensible per the orchestrator's framing: the agent's response forces it to see (and
should be made to surface) WHAT went wrong, not just "ok, cleared."

**Frontend** (`storyengine/frontend/src/app/autopilot/page.tsx`): the Auto-Draft/Full Auto dial buttons
are `disabled` (with a `title` tooltip) whenever `config.weekly_budget_cap == null`, with an inline gold
hint line above the selector ("Set a weekly budget cap below before enabling Auto-Draft or Full Auto.")
so a user doesn't hit the 400 blind. `handleSetDial` also surfaces a red inline error if the call is
rejected anyway (e.g. a stale cache in another tab already cleared the cap) — belt-and-suspenders on the
client, not a replacement for the disabled state.

### Verification (C54b)

17 new tests: 7 pure-function `validate_dial_change` cases, 4 HTTP-route invariant tests (`POST /config`
raise-without-cap rejected / raise-with-cap-in-same-request allowed / clear-while-elevated rejected /
clear-with-simultaneous-lower allowed), 4 MCP end-to-end tests (same four shapes, but calling
`_call_set_autopilot_dial` against the REAL `update_config`, not mocked, to prove the invariant holds
through that door too), 1 runtime-demotion test in `autopilot_launch.py` (proposal created, launch never
called, kill switch never tripped, warning logged), 1 runtime-demotion LOG test in `main.py`'s
`_produce_for_tenant`. Plus the kill-switch-reset test was split in two (carries-prior-reason /
harmless-no-op) and 2 pre-existing C51 tests were fixed to supply `weekly_budget_cap` now that raising
the dial in a test fixture without one demotes to propose_only. Non-vacuous via `git stash` on the 5
touched backend `.py` files (test files kept): all 15 hardening-specific tests fail restored-to-pass (the
4 "allowed" shapes pass either way, correctly — old code never rejected anything, so they're not testing
the new gate specifically, same posture C53's stash-proof noted). Full backend suite: **1771P/15F/1E** =
previous C54 baseline (1752P/15F/1E) + 19 new tests, same 15 pre-existing failures + same 1 error, zero
new failures. Frontend: `npx tsc --noEmit` clean, `npm run build` succeeds.

### Modified/New Files (C54b)

| Path | Change |
|------|--------|
| `storyengine/backend/autopilot_dial.py` | NEW `validate_dial_change` |
| `storyengine/backend/routes/autopilot.py` | `update_config` calls the invariant; `KillSwitchResetResult`/`reset_kill_switch` carry the prior trip reason |
| `storyengine/backend/routes/mcp.py` | Docstring/description updates only — the invariant enforcement is transitive via `update_config`, no functional change needed |
| `storyengine/backend/autopilot_launch.py` | `effective_dial_level` demotion (elevated + no cap -> propose_only, logged, never tripped) |
| `storyengine/backend/main.py` | `_produce_for_tenant` logs the same condition (visibility only, no behavior branch) |
| `storyengine/backend/tests/test_c54_weekly_budget_kill_switch.py` | +17 tests (see above) |
| `storyengine/backend/tests/test_c51_candidate_auto_launch.py` | 2 tests fixed (now supply `weekly_budget_cap`), 1 new runtime-demotion test |
| `storyengine/frontend/src/app/autopilot/page.tsx` | Dial buttons disabled without a cap + inline hint/error |

No new migration.

### Deploy-safety assessment

**Recommend ff-merge candidate, stacked on C54's commit.** Same no-op-on-default-path argument as C54
itself: for every tenant that has never set a `weekly_budget_cap` (100% today, since neither C50 nor C54
shipped a writer that could set one before this pass merges alongside it), `dial_level` has also never
been raised past `propose_only` through these doors (the SAME invariant blocks it), so the runtime
demotion in `autopilot_launch.py`/`main.py` is unreachable on the default path — it only ever fires for a
row an operator hand-edited directly in the DB, bypassing both writers entirely. The MCP tool's
classification (FREE, no confirm_token) is now backed by a hard ceiling: the worst a rogue/injected call
can do is resume spend up to a cap a human explicitly set, never uncapped.

---

## C56 — per-launch pattern flywheel: the SECOND channel_patterns trigger (P4.2-g, added 2026-07-19)

Closes decisions.md's 2026-07-19 "Pattern learning has TWO convergent entry points" law. C46e built
trigger (a) — the IMPORT-TIME bulk analyzer (`channel_patterns.run_import_pattern_analysis`, migration
106, called from `channel_dna.py::learn_channel`). This chunk builds trigger (b) — PER-LAUNCH
incremental proposals from each new platform-published video's own analytics — and, in doing so, fixed a
latent gap in trigger (a): **it had no dedup at all**, so re-running `learn_channel` on an unchanged
outlier set would have re-inserted duplicate `proposed` rows every time.

**The seam** (exactly as C46e's own docstring anticipated): `routes/youtube_sync.py::_writeback_
matched_videos` (the per-video analytics writeback that already runs on every `/api/youtube/sync` call —
manual button + `main.py`'s daily auto-sync) now queues any video that clears a maturity bar and hasn't
been analyzed yet, then makes ONE batched call to a new `channel_patterns.run_launch_pattern_analysis`.

**Maturity bar** (`LAUNCH_ANALYSIS_MIN_IMPRESSIONS = 1000` in `youtube_sync.py`): reuses the EXACT bar
`routes/learning_extraction.py::extract_learnings` already established as the SaaS-native learnings
loop's "matured enough to analyze" gate — `ctr_percent IS NOT NULL AND impressions >= 1000` — rather than
inventing a new time-based (48h/7d) threshold. That wall-clock convention exists elsewhere in the SAME
file (`_calculate_snapshots`'s `views_24h/48h/7d/30d`/`ctr_48h`/`retention_48h` write-once columns) but
nothing reads those as a GATE anywhere in the codebase — they're display-only snapshots — so following
that pattern instead of the actually-load-bearing impressions/ctr gate would have been inventing a
second, redundant maturity definition.

**Write-once marker**: new column `videos.launch_pattern_analyzed_at` (migration 110, `ADD COLUMN IF NOT
EXISTS`, applied live) — same convention as the existing snapshot columns. Written INTO THE SAME per-row
`UPDATE videos` statement `_writeback_matched_videos` already issues (no extra query), unconditionally
once the video qualifies — regardless of whether the subsequent analysis call actually proposes anything
or even fails — so a channel that syncs daily only pays the launch-analysis cost once per video, ever,
and a permanent per-video failure never retries forever.

**Analysis brain — REUSED, not forked**: `run_launch_pattern_analysis(tenant_id, videos)` calls the SAME
`propose_patterns_from_analytics` / `score_outlier_patterns` the import-time analyzer uses (identical
`MIN_COHORT=5`, `OUTLIER_THRESHOLD_PCT=30%` thresholds, zero duplication), scored ONCE for the whole batch
of newly-matured videos in one sync pass (not once per video — a channel's first sync after this ships
could have many already-matured platform videos cross the marker simultaneously; recomputing the
channel-wide outlier scan per video would be needless repeated work against the same data snapshot), then
narrows results to candidates whose `evidence.video_ids` match one of THIS batch's videos — a candidate
about some other, unrelated video that also happens to be an outlier this run is never proposed by this
trigger (that's the periodic/import-time bulk sweep's job, not per-launch's).

**Dedup — NEW shared gate, retrofit onto BOTH triggers**: `channel_patterns._dedupe_candidates_against_
rows` (pure) keys a candidate on `(video_id, metric)` — mirrors the repo's existing dedup precedent in
`routes/learning_extraction.py::extract_learnings` (keys on `(category, pattern_name)` before upserting
into `learnings`, same shape, different table). Rule: an existing `proposed`/`confirmed` row sharing the
key always wins (never re-propose an active claim); an existing `retired` row sharing the key only loses
to a NEW candidate with a STRICTLY LARGER `evidence.cohort_size` (more channel history collected since a
human walked it back = genuinely newer evidence, per decisions.md's "retirement was a human decision;
re-proposing needs NEW evidence" — cohort size only grows, so it's a clean, honest proxy for "newer" with
no new timestamp column needed); a candidate that can't be keyed (missing evidence shape) is always kept.
The async wrapper (`_dedupe_candidates`) fetches the tenant's existing patterns across EVERY status and
EVERY source (an import-analysis row blocks a launch-analysis re-propose of the same claim, and vice
versa — one dedup brain, not two) and fails OPEN (returns candidates unfiltered) on a DB hiccup — worst
case is a duplicate a human can retire, never a silently-dropped real proposal. `run_import_pattern_
analysis` now calls this too (previously had none at all).

**Notify**: `channel_patterns._notify_launch_pattern_proposed` drops one `bot_activity` row per persisted
launch-analysis pattern (C52's `autopilot_proposals.py::_notify_proposal_created` is the copied
precedent), with a REAL `video_id` (unlike the autopilot-proposal notify, which uses NULL since no video
exists yet at proposal time) — best-effort, never raises. No frontend change needed: `routes/chat.py`'s
DNA-digest card (`_proposed_channel_patterns` / `_build_dna_digest_card`) already renders any
`status='proposed'` row regardless of `source`, confirmed by reading the query (`list_patterns(tenant_id,
status="proposed")`, no `source` filter) — `launch_analysis` rows show up there for free.

### Verification (C56)

28 new tests (20 in `tests/test_channel_patterns.py`: 9 pure dedup-resolver cases, 3 async-wrapper cases,
1 import-trigger-now-dedupes integration case, 5 `run_launch_pattern_analysis` cases incl. cross-video
narrowing + fail-soft + dedup-convergence, 2 notify cases; 8 in new `tests/test_c56_launch_pattern_
flywheel.py` covering the `_writeback_matched_videos` wiring: queued-and-marker-written, already-analyzed
never-requeued, below-impressions-bar/no-ctr/missing-youtube-id never queued, multi-video batching, and
flywheel-failure-never-breaks-the-sync). NON-VACUOUS via `git stash` on the two touched `.py` source
files (test files kept): all 28 new tests fail against the pre-C56 code (`AttributeError: has no
attribute 'run_launch_pattern_analysis'`, or the dedup tests failing outright since the function didn't
exist), 29 pre-existing `test_channel_patterns.py` tests unaffected either way. Full backend suite:
**1799P/15F/1E** = previous baseline (1771P/15F/1E) + 28 new tests, SAME 15 pre-existing failures (verified
by name-diff, not just count) + same 1 error, zero new failures. `py_compile` clean on both touched files.
No frontend changes (none expected per scope — confirmed the existing digest card already renders
`launch_analysis`-sourced rows with no source filter).

### Modified/New Files (C56)

| Path | Change |
|------|--------|
| `storyengine/backend/migrations/110_launch_pattern_analyzed_marker.sql` | NEW — `videos.launch_pattern_analyzed_at TIMESTAMPTZ`, applied live + confirmed via `information_schema` |
| `storyengine/backend/channel_patterns.py` | NEW `_candidate_key`/`_dedupe_candidates_against_rows` (pure)/`_dedupe_candidates` (async); `run_import_pattern_analysis` now dedupes; NEW `run_launch_pattern_analysis` + `_notify_launch_pattern_proposed`; module-level `execute` import added |
| `storyengine/backend/routes/youtube_sync.py` | NEW `LAUNCH_ANALYSIS_MIN_IMPRESSIONS` constant; `_writeback_matched_videos` queues matured/unanalyzed videos, writes the marker in the existing per-row UPDATE, and makes one batched post-loop call to the flywheel (fail-soft) |
| `storyengine/backend/tests/test_channel_patterns.py` | +20 tests |
| `storyengine/backend/tests/test_c56_launch_pattern_flywheel.py` | NEW — 8 tests |

### Deploy-safety assessment

**ff-merge candidate.** Purely additive: a new nullable column (default NULL, no backfill needed — every
existing video simply queues for launch analysis exactly once on its next sync, same as a brand-new
video would), a new function nothing else calls yet except the one new call site, and that call site is
wrapped in its own try/except so a scoring bug can't break the analytics sync that already runs today.
The per-row `UPDATE videos` statement's existing columns/values are completely unchanged when a video
doesn't qualify for launch analysis (the new `update_fields` key is only added conditionally). No prior
behavior is touched: `run_import_pattern_analysis`'s NEW dedup pass only ever REMOVES candidates it would
previously have proposed (never adds), and only when a matching row already exists — a tenant with zero
existing `channel_patterns` rows (everyone, until C46e's import learner or this chunk's flywheel first
run for them) sees byte-identical behavior to before.

### Known limitation (reported, not fixed — out of scope)

On a tenant's FIRST sync after this ships, every already-matured, already-matched platform video crosses
the maturity bar simultaneously and gets queued in one batch — bounded by that tenant's number of
platform-launched videos (not the whole `channel_videos` table), and the whole batch still only costs ONE
`propose_patterns_from_analytics` scan (see "Analysis brain" above), so this is a one-time, self-limiting
cost rather than a recurring one — but it's still worth flagging as a first-sync cost bump for a
long-running channel adopting this feature late.

## C55 — full-auto continuation past an approval gate (P4.2-f, added 2026-07-19)

dial=full_auto is supposed to proceed through finalize+upload UNLESS the kill switch is tripped or the
weekly cap is breached, checked at every stage transition. Two DIFFERENT stop-points needed this, both
hit by the SAME two pre-existing loops (`routes/autopilot.py`'s and `routes/queue.py`'s
`_run_full_pipeline` closures, which already call `run_next_step` in a for-cycle) — no new scheduler:

1. The `needs_approval` stop `PipelineExecutor._run_next_step_status_map` produces at the three
   `APPROVAL_GATE_STATUSES` (`ready_for_voice`/`ready_for_images`/`ready_for_thumbnail`).
2. A stop the checklist's own framing hadn't named but tracing found: BOTH `_run_full_pipeline` loops
   hardcode `"rendered"` into their terminal-status set and `break` **before ever calling
   `run_next_step` again** — so even for `auto_draft` today, a rendered video never reaches
   `run_upload` without a human's "Upload" click. Full-auto's contract ("proceeds through
   finalize+upload") is unmet unless this stop is ALSO passed for eligible videos — fixed as part of
   this chunk, not deferred.

**`storyengine/backend/pipeline_executor.py`** gains the ONE eligibility check both stops share,
`PipelineExecutor.full_auto_may_continue(video_id, video, checkpoint) -> bool` (public — the loops that
need it for stop #2 live outside the class):
- Scope: `video.source` must start with `'autopilot'` — `'autopilot_<channel>'` for a candidate launch
  (`routes/autopilot.py::_do_launch_candidate`) or `'autopilot_queue'` for an autopilot-drained queue
  item (see the `routes/queue.py` bullet below). A human-launched video's source never matches, so it
  always stops, at any dial_level — checked FIRST, before any dial read.
- `dial_level == 'full_auto'` exactly (`auto_draft`/`propose_only` never continue).
- `kill_switch_tripped_at IS NULL`.
- `weekly_budget_cap IS NOT NULL` — C54b's runtime-demotion invariant re-applied at this seam: an
  elevated dial with no cap is treated as NOT full_auto (logged, never a kill-switch trip).
- `check_weekly_budget()` says ok — a breach trips the kill switch (C54's law: never a silent pause)
  and returns False, so the video parks exactly like an ordinary stop; nothing already generated is
  rolled back.
- On True: writes ONE `bot_activity` row (`bot_name='autopilot_full_auto'`) per checkpoint passed —
  attribution that can never be mistaken for a human approval, mirroring
  `routes/videos.py::advance_video`'s `stage_transitions.triggered_by='user'` (the existing "who
  approved" record for the images/thumbnail gates).

`_full_auto_continue_past_gate(video_id, video, gate_status)` wraps the eligibility check for stop #1
and, when eligible, calls `_full_auto_pass_gate` — the gate-specific action a human would otherwise
trigger, mirroring the real human path exactly (never a parallel status machine):
- `ready_for_voice`: calls `run_voice()` (which advances the status itself, same as a human's "Generate
  Voice" click).
- `ready_for_thumbnail`: calls `run_thumbnail()` ONLY if `thumbnail_url` isn't already set (mirrors the
  human path's "Generate Thumbnail" then "Approve & Advance"), then advances.
- `ready_for_images`: advances directly (the human's only remaining action here is "Approve &
  Advance" — `routes/videos.py::advance_video`). "Advance" means the SAME chokepoint every stage handler
  already uses (`_update_video_status`, which honors a reduced `pipeline_stages` plan) plus a
  `stage_transitions` row with `triggered_by='autopilot_full_auto'`.

`_run_next_step_status_map` calls `_full_auto_continue_past_gate` at the exact point it would otherwise
return `needs_approval` — the only change to that method.

**`storyengine/backend/routes/autopilot.py`** and **`storyengine/backend/routes/queue.py`** — stop #2:
both `_run_full_pipeline` closures now `SELECT *` (not just `status`) and, when the freshly-read status
is `'rendered'`, call `executor.full_auto_may_continue(video_id, video, "rendered (pre-upload)")` before
honoring the terminal break; only when that's False does the loop actually break. Every OTHER terminal
status (`uploaded`/`uploaded_draft`/`done`/`published`/`failed`) always breaks — upload's own
skip-if-already-uploaded guard (`run_upload`'s `force=False` default, C16e) means this can never mint a
second draft even if `run_next_step` gets called after a video is somehow already uploaded.

**`storyengine/backend/routes/queue.py`** — `launch_queue_item` gains an `via: str = "queue"` keyword
(default unchanged — every human `/next/launch`/`/{item_id}/launch` click). `auto_produce_next` (the
autopilot queue-drain loop) now passes `via="autopilot_queue"` instead — the ONLY thing that lets
`full_auto_may_continue`'s scope check tell an autopilot-drained queue launch apart from a manual one
(both otherwise build an identical video row). The existing cadence/in-flight dedup queries (here and in
`autopilot_launch.py`) already match `source LIKE 'autopilot%' OR source = 'queue'`, so this rename
doesn't drop `'autopilot_queue'` rows from either check.

**`storyengine/backend/autopilot_launch.py`** — docstring/comments updated to point at the real
implementation above (previously said "carrying a full_auto draft through to finalize+upload is C55, not
this chunk" — now names `full_auto_may_continue`/`_full_auto_continue_past_gate` and where they're
consulted). No logic change in this file — `full_auto` and `auto_draft` still launch identically; the
difference is entirely downstream, in whether the build continues past the stops.

**`docs/failure-modes.md`** — the "upload" resumability row was stale (claimed "no re-upload guard...
flagged as a follow-up — not fixed in C16d"); C16e (commit a43110b, prior to this chunk) already added
the skip-if-done guard for EVERY caller. Corrected during this chunk's audit since C55's item 5 depends
on that fact being right.

### Verification (C55)

16 new tests (`tests/test_c55_full_auto_continuation.py`): the 5-gate eligibility contract on
`full_auto_may_continue` (scope short-circuit with proof the dial is never even read, both non-full_auto
dial levels, kill-switch-tripped, elevated-no-cap-never-trips, budget-breach-trips-and-stops,
happy-path-with-attribution-row); the real `_run_next_step_status_map` seam (eligible video continues,
human-launched video with the SAME dial=full_auto still stops, dial-turned-down-mid-build stops);
`_full_auto_pass_gate`'s three per-gate mechanics (voice calls run_voice, thumbnail generates only if
missing then advances with the right `triggered_by`, images advances directly); the 'rendered'
pre-upload stop run via the ACTUAL `routes.autopilot._do_launch_candidate` closure (captured through a
fake `BackgroundTasks`, then awaited directly — not a reimplementation) for both the eligible-continues
and ineligible-still-stops cases; and `routes.queue.auto_produce_next`'s source-tagging fix. NON-VACUOUS
via `git stash` on the 5 touched source files (test file kept): 13 of 16 fail against pre-C55 code (the
3 "should still stop" tests pass both before and after, correctly — they're regression guards for
unchanged behavior, not proofs of new behavior). Full backend suite: **1815P/15F/1E** = baseline
(1799P/15F/1E) + 16 new tests, SAME 15 pre-existing failures (verified by name-diff, not just count) +
same 1 error, zero new failures. `py_compile` clean on all touched `.py` files. No frontend changes
(none expected — the dial UI already exists from C54, and the pipeline UI already shows stage progress;
an auto-continued gate simply never shows an "approval needed" affordance, no code change needed for
that).

### Modified/New Files (C55)

| Path | Change |
|------|--------|
| `storyengine/backend/pipeline_executor.py` | NEW `full_auto_may_continue`, `_full_auto_continue_past_gate`, `_full_auto_pass_gate`, `_FULL_AUTO_SOURCE_PREFIX`; `_run_next_step_status_map` calls the continuation check at its `needs_approval` return; `get_next_status_supabase` added to the `status_map` import |
| `storyengine/backend/routes/autopilot.py` | `_run_full_pipeline` (inside `_do_launch_candidate`) fetches the full video row and consults `full_auto_may_continue` before honoring the `'rendered'` terminal break |
| `storyengine/backend/routes/queue.py` | `launch_queue_item` gains `via` kwarg (default `'queue'`, unchanged); `auto_produce_next` passes `via='autopilot_queue'`; its own `_run_full_pipeline` gets the same `'rendered'` full-auto check as autopilot.py's |
| `storyengine/backend/autopilot_launch.py` | Docstring/comments only — points at the real C55 implementation |
| `docs/failure-modes.md` | Corrected the stale "upload has no re-upload guard" row (fixed since C16e) |
| `storyengine/backend/tests/test_c55_full_auto_continuation.py` | NEW — 16 tests |

### Deploy-safety assessment

**Recommend ff-merge candidate — but see the live-verification-queue recipe before ever setting a real
tenant to full_auto.** Every existing tenant/video is provably unaffected on the default path:
`full_auto_may_continue` returns `False` at the very first check (`video.source` prefix) for every video
that isn't autopilot-launched — which is 100% of videos today outside of C51's candidate/queue-autopilot
paths, since `dial_level` defaults to `'propose_only'` and no tenant has ever set `full_auto` (the dial
UI only shipped the 3-option selector in C54; nothing before this chunk could even reach `full_auto`
behavior, since `full_auto` and `auto_draft` were identical until now). For a tenant who HAS explicitly
dialed to `full_auto` with a cap set, this chunk is the intended, requested behavior change — not an
accidental one — and every dial/kill-switch/budget invariant from C50/C54/C54b is re-checked fresh at
every checkpoint, so a human can stop it at any time via the existing kill-switch/dial UI. Money-path
risk is bounded by the SAME weekly cap C54 already enforces, re-checked at each of the (at most) 4
checkpoints a build can cross (voice, images, thumbnail, pre-upload) — not a new spend surface, just
removing the human click between existing paid stages for a tenant who asked for that. Backend-only
change; no frontend deploy needed.

## C57 — MCP ⇄ existing-billing wiring: "the token IS the paywall" (added 2026-07-19)

decisions.md's MCP-monetization entry + its CORRECTION: Stripe billing ALREADY EXISTS
(`routes/billing.py`) — this chunk wires the MCP agent-token surface into it, no new billing system.

**Good-standing helper (NEW, `storyengine/backend/routes/billing.py`):** no pre-existing "good
standing" concept existed to extract — `check_plan_limits`/`_get_tenant_plan` only ever read
`plan`/`trial_ends_at`, never `stripe_status` (written by every webhook handler in this file but,
until now, dead data for gating purposes). Added `_good_standing_from_fields(*, trial_ends_at,
stripe_subscription_id, stripe_status) -> (ok, reason)` — the ONE decision function, mirroring TWO
dichotomies this file already draws elsewhere rather than inventing a third: (1)
`_handle_subscription_updated`'s own `sub_status != "active"` fail-closed/open line; (2) the
trial-downgrade cron's `stripe_subscription_id IS NULL` safety filter for "is this a genuine trial"
(test_trial_downgrade_wire.py). Verdict table: `stripe_status IS NULL` (never subscribed) → good;
`'active'` → good; active trial (`trial_ends_at` future AND no `stripe_subscription_id`) → good;
anything else (`past_due`/`canceled`/`unpaid`/`incomplete`/theoretical `trialing`) → NOT good ("has
lapsed"). Honest inherited quirk: Stripe's `trialing` status is fail-closed here, same as the webhook
already treats it — moot today since `create_checkout` never sets `trial_period_days`.
`is_account_in_good_standing(tenant_id)` wraps it with the SAME membership→accounts join
`_get_tenant_plan` uses, extended with the 3 extra columns that join never needed.

**Mint gate:** `storyengine/backend/routes/agent_access.py::create_token` calls
`is_account_in_good_standing` before minting — 402 `subscription_lapsed` with a `/billing` renew
pointer when not in good standing. A commented SEAM sits right below it for the NOT-YET-decided
"which tier gets MCP" tier check (item 5 — deliberately unimplemented).

**Verify gate + the piggyback (`storyengine/backend/agent_tokens.py`):** new
`authenticate_with_standing(token) -> (tenant_id, ok, reason)`, additive alongside the untouched
`authenticate()` (still used by `rate_limit.py`'s tenant-resolution path, unaffected). Piggybacks the
account's good-standing fields onto the SAME per-request token-row query via one JOIN
(`agent_tokens` → `memberships` → `accounts`) instead of a second round trip — avoids doubling the
DB cost `auth_agent.py` already pays every MCP call. Calls the SAME `_good_standing_from_fields` (ONE
definition, locked by a regression test). `storyengine/backend/auth_agent.py::get_agent_tenant_id`
now calls this instead of `authenticate()`: unknown/revoked token → unchanged 401; valid token, lapsed
account → NEW 402 with a renew-here message that surfaces in the agent's chat — existing tokens die
same-day with zero revocation machinery, since every call re-checks live.

**Plan-gate audit (the free-tenant-unlimited-via-Claude risk) — REAL FINDING:** `create_video`
(MCP) and `accept_autopilot_proposal` (MCP) were ALREADY gated — both dispatch through the exact
route/function (`routes.videos.create_video`, `routes.autopilot.launch_candidate` via
`accept_proposal`) the existing `check_plan_limits('video')` lock already pins. But the `render`/
`build` MCP tools (and the IDENTICAL chat verbs, and autopilot's full-auto continuation loop) call
`PipelineExecutor.run_render` DIRECTLY via `actions.py`'s dispatcher — bypassing
`routes/pipeline.py::run_render`, the ONLY place that ever called `check_plan_limits(tenant_id,
"render")`. Render-minute cap enforcement was a no-op for chat, MCP, and full-auto alike — not an
MCP-specific bug, a shared-path one this audit was built to catch. **Fixed at the ONE method every
caller converges on:** `PipelineExecutor.run_render` (`storyengine/backend/pipeline_executor.py`) now
calls `check_plan_limits(self.tenant_id, "render")` itself, failing the same way its other error
paths already do (`{"status": "failed", "error": ...}`, never raises) so every caller's existing
error handling picks it up unchanged. The route's own pre-check is left in place (redundant, harmless,
faster synchronous 402 before a background task even queues).

**Tests:** new `tests/functional/test_c57_mcp_billing_gate.py` (24 tests: good-standing decision
matrix, mint/verify gates, ONE-definition lock). Extended `test_plan_limits_enforcement_lock.py`
(+3: `run_render` executor-level gate, MCP create_video/accept_autopilot_proposal confirmatory
locks). Extended `test_c26_mcp_agent_tokens.py`/`test_c29_mcp_full_session_dry_run.py`'s DB fakes to
answer the new piggybacked JOIN query (existing happy-path tests simulate a free-tier "good
standing" account — unaffected). Non-vacuous via stash: 25 of the 27 new/changed tests fail without
the fix (the 2 that don't — the MCP create_video/accept_autopilot_proposal locks — are confirmatory
of ALREADY-correct pre-C57 behavior, not new fixes). Full suite **1842P/15F/1E** = baseline(1815P) +
27, same 15 failures/1 error by name, zero new.

**No migration** — `stripe_status`/`stripe_subscription_id`/`trial_ends_at`/`plan` all already exist
(migrations 022/026). **No frontend.** **Deploy-skew:** MCP surface stays dark (`MCP_ENABLED` off in
prod) except the `PipelineExecutor.run_render` fix, which is live the moment this merges — it only
ADDS enforcement to a path that was silently unenforced for chat's render/build verbs and autopilot's
full-auto loop today; the default (no cap set, or under-cap) behavior is byte-identical.

**Parked decision added:** checklist's C37 OPEN list gains item 6, "which tier gets MCP" (recommend
pro+agency) — was only in decisions.md's correction entry before, not the tracked parked-decisions
list.

## C49 — MCP atomic-surface completion (added 2026-07-20)

Checklist "MCP atomic-surface completion" + decisions.md 2026-07-19's "model this video" extension:
21 new MCP tools in `storyengine/backend/routes/mcp.py`, ALL thin wrappers over existing route/module
functions — no new pipeline logic, same registry discipline as C26/C27/C47 (PAID = confirm_token
money gate, FREE = attributed write, READ = no media URL). Same file, no new module (kept the
single-registry convention every earlier MCP chunk used).

**New generic paid-gate helper (`_paid_gate`, routes/mcp.py):** the 3 new PAID tools below have no
`actions.ACTIONS` verb of their own, so `_call_verb`'s gate doesn't apply to them. `_paid_gate` reuses
`confirm_tokens.py`'s EXACT `create()`/`redeem()`/`params_hash()` — same `mcp_confirm_tokens` table,
same single-use/10-minute/params-bound token — keyed by the tool's own name (in the `verb` column)
and a subject id like `asset_id`/`char_id` (in the `change` column) instead of a scene number. No new
money mechanism.

**Shot-level (6 tools):** `get_shots` (wraps `routes.videos.get_video_assets`, strips `image_url`/
`video_clip_url`), `edit_shot_image_prompt`/`edit_shot_motion_prompt`/`set_shot_model_override` (wrap
`routes.assets.update_image_prompt`/`update_video_prompt`/`update_model_override` — the last is the
checklist's named "C14 endpoint"), `improve_prompt` (wraps `routes.pipeline.improve_prompt`),
`redraw_shot` (PAID, wraps `routes.pipeline.run_redraw_image`, quoted at `actions.PICTURE_COST`).

**Script surgery (3 tools):** `get_scene_script` (filters `_call_get_script`'s own result to one
scene — zero new SQL), `edit_scene_text` (wraps `routes.videos.update_scene_text`),
`regenerate_scene_text` (wraps `routes.videos.rewrite_scene_text` — FREE, uses the tenant's OWN
Anthropic key directly, same BYOK classification as `learn_channel_start`, not billed by
StoryEngine).

**Character granularity (3 tools):** `get_characters` (wraps `routes.characters.list_characters`,
strips `reference_url`), `edit_character` (wraps `update_character`), `redo_character_sheet` (PAID,
wraps `regenerate_character`, quoted at `actions.PICTURE_COST`).

**Voice control (2 tools):** `set_narrator_voice` (wraps `routes.settings.set_api_key` HARDCODED to
`key_name="elevenlabs_voice_id"` only — not a general secret-setter), `redo_dialogue_scene_voice`
(PAID, wraps `routes.pipeline.run_dialogue_voice`, quote reuses `actions.estimate_cost`'s real
"voice" pricing — no parallel cost math). Narration-mode single-scene voice redo needed NO new tool —
the existing `voice` ACTIONS-verb tool already accepts a `scene` argument.

**Pre-publish (2 tools + one real gap fixed):** `get_publish_info` (reads `seo_description`/
`seo_tags`/`seo_hashtags`/`seo_category_id`), `edit_publish_info` (wraps `youtube_publish.save_seo`).
**Real gap found+fixed:** `seo_category_id` had NO edit path at all — only `generate_and_store_seo`'s
own Claude-computed write. Added an optional `category_id` param to `youtube_publish.save_seo()`
(resolves a friendly name via the SAME `_CATEGORY_IDS` map `generate_and_store_seo` already uses, or
passes a raw id through) and wired `routes.videos.save_video_seo`'s PATCH body to it too — so the
existing HTTP door gained the same capability as the new MCP tool, not a second implementation.

**Analytics reads (2 tools):** `get_style_performance` (wraps `routes.analytics.get_by_style_
performance`), `get_top_channel_videos` (wraps `get_channel_videos`, ranks by views, strips
`thumbnail_url`/`watch_url` — own-channel VPH + top-N in one tool, per decisions.md's "model this
video" data-feed ask).

**Reference-modeling reads (4 tools):** `pull_reference_video_metadata` (wraps `routes.niche.
_extract_video_info` via `asyncio.to_thread`, KEPT SYNCHRONOUS — judgment call, see below),
`get_channel_top_performers` (wraps `routes.niche.list_videos` with `sort=views_desc`, strips
`thumbnail_url`/`url`/`channel_url`, keeps `video_id` as the reference), `score_title_gap_structures`
(wraps `title_idea/curiosity_gap/gap_title_engine.score_structures` — the pure, deterministic,
Claude-FREE half of that engine), `suggest_video_titles` (wraps the existing `routes.videos.
suggest_titles` — the platform-native, tenant-scoped BYOK title generator).

**Judgment call — yt-dlp shape kept synchronous, not start/poll:** `_extract_video_info` has no
existing HTTP endpoint of its own (only called internally by `niche.py`'s scrape task and
`model_video.py`'s multi-stage pipeline); C47's `learn_channel_start` needed the start/poll shape
because it runs 1-2 MINUTES — a single-video yt-dlp pull is normally seconds, so `pull_reference_
video_metadata` awaits it directly in the request/response cycle instead of inventing a second
task-polling mechanism for one read tool. Flagged (not proven) — the sandbox has no network to
yt-dlp; if a live run shows this stalls the request past a client's timeout (bot-check retries can
be slow), that decision should flip to start/poll. See `tasks/live-verification-queue.md` §C29 Step
5c.

**Explicitly SKIPPED — "no existing seam" (per the checklist's own house rule, don't build new
pipeline capability to fill a gap):**
- `title_idea/idea_modeling.py::generate_modeled_ideas` and `GapTitleEngine`'s Claude-calling half
  (`_call_claude_for_titles`) both hardcode `shared.clients.anthropic_client.AnthropicClient()` — a
  GLOBAL env-var-keyed client (this repo-root `.env`'s `ANTHROPIC_API_KEY`), not tenant-scoped BYOK.
  Wrapping either directly in the multi-tenant SaaS backend would either charge Ryan's own key for
  every tenant's MCP call or require inventing a tenant-scoping adapter — real new logic, not a thin
  wrap. Only `score_structures` (the pure scoring half, no client at all) is wrapped;
  `suggest_video_titles` (existing, tenant-scoped) is the practical "generate the actual title text"
  tool instead.
- A per-dialogue-SEGMENT (as opposed to per-scene) voice redo has no existing endpoint at any
  granularity finer than `run_dialogue_voice(scene=...)` — not wrapped.

**Tests:** new `tests/functional/test_c49_mcp_atomic_surface.py`, 29 tests — tool-surface presence +
confirm_token classification, same-callable proofs (patches the REAL underlying route/module
function for every FREE/READ tool), a full real (non-mocked `confirm_tokens`) quote→confirm round
trip for `redraw_shot` proving it dispatches through the SAME `routes.pipeline.run_redraw_image` the
HTTP door calls, ownership/bait-and-switch refusals before any quote is minted, `redo_character_
sheet`/`redo_dialogue_scene_voice` dispatch proofs (the latter reusing `actions.estimate_cost`'s real
pricing), the no-media-URL invariant on every read that could carry one, and a proof
`score_title_gap_structures` never constructs `GapTitleEngine` (patched to raise if touched). Non-
vacuous via `git stash` (28 of 29 fail without the implementation — the 1 that doesn't,
`test_s5_2_memory_tools_still_excluded`, is a pre-existing invariant this chunk didn't change). Full
suite **1871P/15F/1E** = baseline(1842P) + 29, same 15 failures/1 error by name, zero new.

**No migration, no frontend.** **Deploy-skew:** none — MCP surface stays dark (`MCP_ENABLED` off in
prod); the one non-MCP change (`youtube_publish.save_seo`'s new optional `category_id` param) is
additive and backward-compatible (default `None`, no behavior change for existing callers) —
`routes.videos.save_video_seo`'s existing callers that never send `category_id` see byte-identical
behavior.

**Composition recipes added:** `tasks/live-verification-queue.md` §C29 gains Step 5c (C49's live
session) and a new "Composition recipes" subsection with 6 worked examples (ideation batch,
data-directed fix, A/B takes, remote QC, one-off demo, and the "model this video" flagship recipe —
runnable end-to-end today except its media-bearing board-review steps, which stay on C48/C25a).

---

## C39 — delete the orphaned /storyboards standalone page (MICRO, added 2026-07-20)

One of C37's 5 open items ("orphaned /storyboards route"), answered and queued. Structural change:
one file deleted.

**Fresh grep-proof of orphanhood (per C19b discipline — re-proved, not trusted from the old audit):**
`storyengine/frontend/src/app/pipeline/[videoId]/storyboards/page.tsx` had zero inbound references —
grepped the whole frontend for `href=.*storyboards`, `router.push(.*storyboards`, template-literal
route strings (`` videoId}/storyboards ``, `` .id}/storyboards `` ), and any `Link` to the path.
The only `storyboards` hits in `lib/api.ts` are backend API endpoint calls (`/api/videos/{id}/
storyboards...` — DELETE/PATCH calls used by `ScenesWorkspaceTab`), not frontend routes. The
video-detail page's tab system (`app/pipeline/[videoId]/page.tsx`) has no `storyboards` tab id at
all — its tabs are `research/script-voice/characters/environments/scenes/sound/thumbnail/render/
upload/performance`, and the in-page storyboard functionality lives entirely inside the `scenes` tab
(`ScenesWorkspaceTab`). Confirmed orphaned — deleted.

**SACRED boundary (untouched, verified via `git show --stat` on the deletion commit):**
- Storyboard CREATION stage (pipeline): `storyengine/backend/pipeline_executor.py`
  `run_storyboard_prompts`/`run_storyboard_images`/`run_storyboard_extract`/`run_storyboard_sheet`,
  wired in `storyengine/backend/worker.py`'s `arq_run_storyboards` — not in this commit's diff.
- In-page Storyboard tab: `storyengine/frontend/src/components/production/ScenesWorkspaceTab.tsx`
  (the `scenes` tab's storyboard generate/clear/approve UI) — not in this commit's diff.

**Also left alone (judgment call, in scope for a future chunk if ever needed, not this MICRO one):**
`storyengine/frontend/src/components/storyboard/` (`SceneGrid`, `PanelDetail`,
`StoryboardProgressBar`, barrel `index.ts`) — grepped and found imported ONLY by the now-deleted
page, so it's dead code too, but the task scope was explicitly "deletes only the unreachable route."
Left in place rather than guessing at a wider cleanup.

**Deleted:** `storyengine/frontend/src/app/pipeline/[videoId]/storyboards/page.tsx` (`git rm -r` on
the directory).

**Docs fixed (stale entries about this page, not a full rewrite of either doc):**
- `storyengine/agents/blueprints/frontend.md` — removed the route-table row for
  `/pipeline/[videoId]/storyboards`.
- `docs/reports/WIRING_STATUS.md` — route-table row (was `WIRED`) now reads `DELETED (C39,
  2026-07-20)` with the reason; bug-log item 6 ("Storyboard approve is a mock" — FIXED) annotated
  with the follow-up deletion. Pre-existing staleness elsewhere in that 2026-03-31 audit doc (e.g.
  `/storyboard` singular, `StoryboardVisualsTab`, both already renamed/removed before this chunk) is
  untouched — out of scope for this MICRO chunk.

**Verification:** `.next` cache had to be cleared first — it held a stale generated-types reference
to the deleted page (`'.next/types/app/pipeline/[videoId]/storyboards/page.ts'`) that broke `tsc`
until removed; not a real regression, just build-cache staleness. After `rm -rf .next`:
`npx tsc --noEmit` clean; `NEXT_PUBLIC_API_URL=... npm run build` succeeds, route table in the build
output no longer lists `/pipeline/[videoId]/storyboards`. Backend untouched by this chunk but the
full suite was re-run anyway to prove no accidental damage: **1871P/15F/1E**, exact match to
baseline (same 15 named failures/1 error, zero new/missing).

---

## C38 — create-surface convergence, chat-primary (added 2026-07-20)

Ryan's C37 ruling: the producer chat plan is THE create door, the New Video form is the power-user
door; Model A Video / onboarding's create step / FirstVideoFlow must stop being independent
implementations — thin wrappers into those two, no parallel create logic, UX entry points unchanged.

**TRACE (all 5 surfaces, before any code) — 4 of 5 were ALREADY converged:**

| Surface | Endpoint | INSERT site (pre-C38) |
|---|---|---|
| Producer chat plan | internal (chat.py's `_handle_approve`) | none of its own — imports and calls `routes.videos.create_video` directly (`routes/chat.py`'s own module docstring: "REUSES create_video ... does not reinvent video creation") |
| New Video form | `POST /api/videos` | `routes/videos.py::create_video` (the canonical function) |
| FirstVideoFlow | same `POST /api/videos` | none of its own — `frontend/src/app/pipeline/page.tsx`'s `handleFirstVideoCreate` calls the SAME `createMutation.mutate` (`mutationFn: createVideo`) the New Video form's submit handler calls; it was already a thin wrapper before this chunk |
| Onboarding create step | n/a | none of its own — `routes/onboarding.py`'s docstring: its steps are driven by `routes/chat.py`'s `_handle_onboarding` step machine (proposed idea cards funnel through the same chat → create_video path); zero `INSERT INTO videos` in onboarding.py |
| **Model A Video** | `POST /api/model-video` | **`routes/model_video.py::model_video` had its own `INSERT INTO videos` + its own `check_plan_limits`/`increment_usage` calls — the one genuine holdout** |

Also present (unrelated to the 5 UX doors, left alone): `pipeline_executor.py::create_idea` (the
lightweight topic-only idea logger behind `POST /api/pipeline/create-idea`), `routes/discovery.py::
launch_idea`, `routes/autopilot.py::launch_candidate`, `routes/queue.py` — these are separate
programmatic/autopilot entry points, not one of C37's 5 named UX doors, and each already has its own
locked plan-limit gate coverage (see below) — out of scope for this convergence.

**Canonical function: `routes/videos.py::create_video`.** Chosen because it already had the most
complete gating/setup (plan-limit gate, project resolution, static-docu/render-mode detection, house
script template, locked channel format defaults, locked cast, Drive workspace sync, and — critically —
an existing `reference_url`/`is_modeled` branch built for the New Video form's "copy this video's
style" clone path). That branch only supported ONE shape before this chunk though: a real title +
reference_url, always hardcoding `preserve_topic=True` into the background `_run_modeling` call. Model
A Video's shape — a reference link with NO topic yet, deriving a brand-new modeled idea — needed
`preserve_topic=False`, which the function could produce internally (`_run_modeling`'s own docstring
already documented both modes) but no caller could reach.

**The fix — extend create_video's title handling to make both shapes reachable, not fork it:**
- `models.py`: `CreateVideoRequest.title` is now `Optional[str] = None` (was required `str`). Every
  existing caller (New Video form, chat, MCP's `create_video` tool) always sends a real title, so this
  is additive — MCP's tool still 400s its own way if title is blank (`routes/mcp.py::_call_create_video`
  does its own `if not title: return _error_result(...)` before ever building the Pydantic model, so
  its behavior is unchanged; it was never derived from the Pydantic schema).
- `routes/videos.py::create_video`: computes `title = (body.title or "").strip()`; if there's no title
  and no `reference_url` → `400 "Title is required."` (unchanged refusal shape, just moved after
  `reference_url` is parsed so both required-ness rules — title-required, valid-YouTube-link — can be
  checked in one pass). `preserve_topic = is_modeled and bool(title)` — title present = copy style onto
  it (old behavior, unchanged); title absent = derive a new idea (Model A Video's shape, newly
  reachable). `preserve_topic` (not a literal `True`) is now forwarded into the
  `background_tasks.add_task(_run_modeling, ...)` call; the task-status message shown while polling
  also branches on it ("Copying the video's style…" vs "Queued for modeling…", matching each shape's
  old copy).
- `routes/model_video.py::model_video`: no longer touches the `videos` table. Builds
  `CreateVideoRequest(reference_url=url)` (title omitted) and calls `routes.videos.create_video`
  directly (same in-process call pattern chat.py and MCP's tool already use — not an HTTP round trip).
  Its own `check_plan_limits`/`increment_usage`/`_get_or_create_project`/raw INSERT are all deleted;
  the canonical function's gate now covers this path (it was never one of the 4 AST-locked entry
  points `test_plan_limits_enforcement_lock.py` names, so removing its OWN separate gate call doesn't
  touch that lock's coverage — it just stops being a second, unlocked gate). `retry_model_video` (the
  `/retry` endpoint) is untouched — it re-triggers `_run_modeling` on an existing row, no INSERT
  involved. `_run_modeling` itself (the background extraction/analysis/persist stages) is UNCHANGED —
  `tests/functional/test_model_video.py`'s 8 tests (2 pre-existingly failing, unrelated — see below)
  still exercise it directly and pass/fail identically before and after.
- Endpoint path unchanged (`POST /api/model-video`, same request/response shape) — zero frontend
  changes needed; `frontend/src/lib/api.ts::modelVideo()` and `model-video-modal.tsx` are untouched.
  Confirmed the frontend never reads the response's `status` field (it unconditionally sets
  `phase = "running"` after any successful call), so `create_video`'s DB status
  (`"idea_logged"`) replacing the old synthetic `"running"` string is invisible to the UI.

**A pre-existing side-effect widening, checked and judged safe, not fixed further:** Model A Video
videos now ALSO get `apply_default_template`/`apply_format_defaults`/`apply_locked_cast` (they run for
every `create_video` call, is_modeled or not) — previously Model A Video's own INSERT skipped all
three. Traced each: `apply_format_defaults` only touches `visual_style`/`render_style` (never
`image_style_override`), so it can't collide with `_persist_style_overrides`'s
`COALESCE(NULLIF(image_style_override,''), ...)` precedence rule — this exact interaction already
ships today for the New Video form's existing `reference_url` clone path (`preserve_topic=True`), so
extending it to `preserve_topic=False` adds no new risk class. `apply_default_template` prepends the
house script template to `script_system_prompt`, which the background modeling job later over
writes with a straight `=` (not a COALESCE) whenever it computes its own `script_dna` override — this
was ALREADY the case for the shipped clone path before C38; this chunk didn't introduce it and it's
out of scope to fix here (a template-vs-modeling precedence question, not a create-surface one).

**Remaining `INSERT INTO videos` sites (grepped, each justified):** `pipeline_executor.py`
(`PipelineExecutor.create_idea` — the lightweight `/api/pipeline/create-idea` topic logger, a distinct
programmatic entry point, not one of the 5 UX doors), `supabase_adapter.py` (legacy Airtable-parity
adapter, not part of the StoryEngine SaaS create surface), `routes/discovery.py::launch_idea`,
`routes/queue.py`, `routes/autopilot.py::launch_candidate` — all pre-existing, all outside C37's 5
named doors, all independently plan-limit-gated already (autopilot's via C53). `routes/videos.py`'s
own INSERT is the canonical one. No new INSERT sites added.

**Plan-limit lock status: unaffected, verified by direct re-run.** `tests/functional/
test_plan_limits_enforcement_lock.py` (AST-based, pins `check_plan_limits`/`increment_usage` calls in
`create_video`/`pipeline.py::create_idea`/`discovery.py::launch_idea`/`autopilot.py::launch_candidate`)
and `tests/test_c53_launch_candidate_gates.py` — both re-run clean, unchanged. Model A Video was never
one of the 4 locked names (confirmed by reading the lock test's own entry-points list), so this
convergence doesn't touch that lock's scope — it just stops running its own separate, unlocked gate.

**Tests:** new `tests/functional/test_c38_create_convergence.py` (8 tests) — behavioral proof the
Model A Video endpoint calls the real `routes.videos.create_video` with `title` empty + the right
`reference_url` (not a fake/mock double), a bad-URL-before-any-create-video-call guard, source-level
pins that `preserve_topic` is derived from title presence (not hardcoded), the title-required 400
still exists, a grep-proof that `model_video.py` has no `INSERT INTO videos` left, and 3 already-
converged-surface locks (FirstVideoFlow/New-Video-form share one mutation in `page.tsx`; chat.py still
imports/uses `create_video`; onboarding.py has no INSERT of its own). Non-vacuous via `git stash`: 4 of
8 fail against the pre-C38 code (the other 4 pin already-shipped, unchanged behavior — chat/onboarding/
FirstVideoFlow convergence predates this chunk). Full suite **1879P/15F/1E** = baseline(1871P) + 8,
same 15 named failures/1 error, zero new/missing (independently confirmed via `git stash` on the 3
touched .py files: reverts to 1871P/15F/1E identically). `tests/functional/test_model_video.py`'s 2
pre-existing failures (`test_happy_path_persists_everything`, `test_bot_blocked_extraction_uses_
oembed_fallback`) are UNCHANGED by this chunk — confirmed via the same stash: both fail identically
before and after, they exercise `_run_modeling` directly and this chunk never touched it.

**No migration, no new tables/columns.** Frontend: `npx tsc --noEmit` clean, zero files touched
(endpoint path/shape held stable on purpose — "converge behind the door, not through it").

**Deploy-skew:** none in either direction. Old frontend + new backend: `POST /api/model-video` request/
response shape is byte-identical, so an old frontend build still works against the new backend
unattended. New frontend + old backend: N/A, no frontend changed. Backend-only, additive-shaped
(`CreateVideoRequest.title` widened from required to optional — a strictly larger accepted set, no
existing caller's request shape becomes invalid) — safe for the routine hourly `git pull --ff-only`
auto-deploy with no `--with-frontend` coordination needed.

**No migration, no backend change, no deploy-skew** — frontend-only route deletion + two doc edits.

## C58 — early-warning launch classifier (Follow-up queue, the last P4.2 scout gap, added 2026-07-20)

SaaS-side port of the CONCEPT in `skills/video-pipeline/autopilot/monitoring/early_warning.py` (legacy
`EarlyWarning.classify()`: fixed absolute CTR% bands, e.g. "CTR < 2.5% = CRITICAL"). The legacy
thresholds are hardcoded percentages that mean something different on every channel — this port keeps
the SHAPE (a small number of tiers, cheap, evidence-backed) but replaces the absolute numbers with the
SAME data-derived, per-channel, evidence-attached law `channel_patterns.py` (C46e/C56) already
established: a video's early trajectory is judged ONLY against its OWN channel's history.

**Classifier** (NEW `storyengine/backend/early_warning.py`): `classify_early_signal(video_ctr_48h,
channel_ctr_48h_values)` is pure — compares one video's `ctr_48h` (the write-once 48h-post-publish
snapshot `routes/youtube_sync.py::_calculate_snapshots` already locks for EVERY video at the identical
milestone) against the median of this SAME tenant's OTHER videos' `ctr_48h` values. Because every
video's `ctr_48h` is captured at the exact same maturity point, this comparison is maturity-matched BY
CONSTRUCTION — never a same-day CTR mashing a brand-new video against a channel veteran's lifetime
average (design constraint 2's honesty requirement). Reuses `channel_patterns.MIN_COHORT` (5, need at
least this many comparable videos to trust a median) and `channel_patterns.OUTLIER_THRESHOLD_PCT` (30%,
directly as the `underperforming` cutoff — this channel's OWN existing definition of an outlier, not a
new number); `watch` is half that (15%). Bands: `delta_pct <= -30%` → `underperforming`; `-30% < delta_pct
<= -15%` → `watch`; else → `ok` (a warning system has no separate "doing great" tier — beating the median
is just `ok`). Returns `None` (never guesses) when `video_ctr_48h` is missing or fewer than 5 comparable
videos exist — see "young" below for what happens next in that case.

**"Young" definition — self-bounding, no time-window constant needed:** a video is classified EXACTLY
ONCE, the first sync where its `ctr_48h` is available (in the DB already, OR landing THIS sync via
`_calculate_snapshots`) AND it has never been classified (`early_signal_at IS NULL`). Because `ctr_48h`
is itself a write-once 48h milestone, this window opens at most once per video (whichever sync first has
`ctr_48h` populated — for a video whose `ctr_48h` predates this feature, that's simply the first sync run
with this code deployed, a natural backfill with no special-cased catch-up path) and closes forever once
`run_early_signal_classification` successfully classifies it (`early_signal_at` stamped). **Exception:**
when the channel's cohort is too thin (`classify_early_signal` returns `None` for that reason, not a
missing `ctr_48h`), `early_signal_at` is deliberately left `NULL` so the SAME video is retried on a later
sync once the channel accumulates enough sibling launches — "too little history" self-heals instead of
silently guessing or giving up forever (the checklist's "never guess without data" requirement, pinned by
`test_leaves_marker_untouched_when_cohort_too_thin`).

**Storage** (migration 111, `ADD COLUMN IF NOT EXISTS`, applied LIVE via Supabase MCP against
`wrromlupsmyzrrcqlucn`, confirmed via `information_schema.columns`): `videos.early_signal TEXT` ('ok' |
'watch' | 'underperforming' | NULL, CHECK-constrained), `videos.early_signal_evidence JSONB` (the raw
numbers/N/thresholds behind the call — same evidence-jsonb discipline as `channel_patterns.evidence`),
`videos.early_signal_at TIMESTAMPTZ` (the write-once marker). Columns added to the existing per-video row
(no new table) per design constraint 5. `schema.sql` updated to match — and, while there, also picked up
the pre-existing gap where C56's `launch_pattern_analyzed_at` (migration 110) had never been added to
`schema.sql`'s `videos` table definition (found during this chunk, fixed alongside).

**Seam**: `routes/youtube_sync.py::_writeback_matched_videos` (the SAME per-video analytics writeback
C56 hooked) gains a second batched, fail-soft trigger alongside the existing launch-pattern-flywheel one
— independent of it (a video can clear BOTH the C56 impressions>=1000 bar and the C58 ctr_48h-present
bar in the same sync and queue for both; `test_both_flywheels_fire_independently_for_the_same_video`
pins this). `pending_early_signal` collects `{"internal_video_id", "ctr_48h"}` for every young video this
sync (using the effective post-update `ctr_48h`: `r["ctr_48h"] if r["ctr_48h"] is not None else
update_fields.get("ctr_48h")`, so a freshly-landing-this-sync snapshot is picked up in the SAME sync it
lands, not one sync later), then makes ONE batched call to `early_warning.run_early_signal_classification`
after the per-row UPDATE loop, wrapped in try/except (fail-soft — a classifier/DB hiccup never breaks the
sync; unlike C56's marker, `early_signal_at` is written OR deliberately left NULL entirely inside
`run_early_signal_classification` itself, so a failure here just means next-sync retry, never a
half-written state).

**Notify**: `early_warning._notify_underperforming` drops ONE `bot_activity` row (`bot_name=
"early_warning"`) ONLY when the level is `underperforming` — never for `ok`/`watch` — and, because
`early_signal_at` is write-once, this can only ever fire once per video, never on a repeat sync (design
constraint 1). Mirrors `channel_patterns._notify_launch_pattern_proposed` (C52's notify precedent) —
best-effort, never raises, never undoes the already-persisted classification write on failure.

**Surface** (design constraint 6 — additive, no frontend work required this chunk):
- `models.py`'s `VideoSummary` (not just `VideoDetail`, so it flows to the list endpoint too) gains
  `early_signal: Optional[str]`; `VideoDetail` additionally gains `early_signal_evidence: Optional[dict]`
  and `early_signal_at: Optional[str]`.
- `routes/videos.py`: `GET /api/videos` (list) and `GET /api/videos/{id}` (detail) both select and return
  the new field(s) — the exact same response shapes the frontend's video list and detail pages already
  fetch.
- `routes/analytics.py::GET /api/analytics/videos` (the Analytics page's "videos actually on the channel"
  list) gains a `LEFT JOIN videos v ON v.id = cv.internal_video_id` and an `early_signal` key in the
  per-row dict — the most natural badge slot (a small pill next to the title/thumbnail on that list row);
  no frontend change made this chunk.
- **MCP decision: no new tool.** The existing `get_video`/`list_videos` MCP tools dispatch through
  `actions.video_summary` (a compact PRODUCTION-status dict — title/status/scene counts/spend), not
  through `VideoDetail`/`VideoSummary`, so they don't pick up `early_signal` for free, and adding
  analytics fields to a "production status" tool would be scope creep on an unrelated surface. A
  dedicated new read tool for one narrow field was judged not worth the MCP tool-surface bloat this
  chunk — the HTTP surfaces above are the reader today; revisit if/when an MCP consumer actually needs
  it (analogous to `get_style_performance`/`get_channel_top_performers`'s existing analytics-tool
  pattern, which this could join later).

### Verification (C58)

31 new tests, NEW `tests/test_c58_early_signal.py`: 13 pure `classify_early_signal` cases (ok/watch/
underperforming bands incl. exact boundary values, no-ctr/thin-cohort/non-positive-median → None,
evidence shape, None-filtering in history, and a lock that `UNDERPERFORMING_THRESHOLD_PCT ==
channel_patterns.OUTLIER_THRESHOLD_PCT` — reuse, not a parallel constant); 11
`run_early_signal_classification` cases (persist-when-classifiable, marker-left-untouched-when-cohort-
too-thin, self-exclusion from its own history, notify-only-on-underperforming, notify-failure-doesn't-
undo-the-write, one-video's-failure-doesn't-abort-the-batch, non-numeric-ctr-never-raises, history-
fetch-fails-soft, empty-input-never-queries, tenant-scoping, cross-tenant-isolation-across-two-calls); 7
`_writeback_matched_videos` wiring cases (already-matured-unclassified queued, freshly-matured-this-sync
queued using the just-written snapshot, already-classified NEVER requeued, not-yet-matured never queued,
classifier-exception never breaks the per-row UPDATE, no-pending never invokes the classifier,
both-flywheels-fire-independently-for-the-same-video). NON-VACUOUS via `git stash` (stashed
`early_warning.py`, the migration, `schema.sql`, `models.py`, and the 3 touched route files, keeping the
new test file): collection fails outright (`ModuleNotFoundError: No module named 'early_warning'`)
against the pre-C58 tree — the strongest possible non-vacuity proof. Restored via `git stash pop`, all 31
re-pass. Full backend suite: **1910P/15F/1E** = baseline (1879P/15F/1E) + 31, SAME 15 pre-existing
failures (verified by name) + same 1 error, zero new. `py_compile` clean on all 6 touched/new `.py` files.
No frontend touched (per design constraint 6) — `npx tsc` not run this chunk.

### Modified/New Files (C58)

| Path | Change |
|------|--------|
| `storyengine/backend/migrations/111_early_signal.sql` | NEW — `videos.early_signal`/`early_signal_evidence`/`early_signal_at`, applied live + confirmed via `information_schema` |
| `storyengine/schema.sql` | `videos` table gains the 3 new columns AND the pre-existing (C56) `launch_pattern_analyzed_at` column that schema.sql had never picked up |
| `storyengine/backend/early_warning.py` | NEW — `classify_early_signal` (pure), `_channel_ctr48_history`, `_notify_underperforming`, `run_early_signal_classification` |
| `storyengine/backend/routes/youtube_sync.py` | `_writeback_matched_videos` gains `pending_early_signal` collection (independent of C56's `pending_launch_analysis`) + a fail-soft batched call to `early_warning.run_early_signal_classification`; SELECT gains `v.early_signal_at` |
| `storyengine/backend/models.py` | `VideoSummary` gains `early_signal`; `VideoDetail` gains `early_signal_evidence`/`early_signal_at` |
| `storyengine/backend/routes/videos.py` | `list_videos`/`get_video` SELECT + response construction gain the new field(s) |
| `storyengine/backend/routes/analytics.py` | `get_channel_videos` gains a `LEFT JOIN videos` + `early_signal` in the response dict |
| `storyengine/backend/tests/test_c58_early_signal.py` | NEW — 31 tests |

### Deploy-safety assessment

**ff-merge candidate.** Purely additive: 3 new nullable columns (default NULL, no backfill — every
existing video simply queues for early-signal classification exactly once on its next sync, same as a
brand-new video would), a new module nothing else calls yet except the one new call site, wrapped in its
own try/except so a classifier bug can't break the analytics sync that already runs today. The per-row
`UPDATE videos` statement's existing columns/values are unchanged when a video doesn't qualify (the new
trigger only ever ADDS a queue entry, never alters `update_fields`). `VideoSummary`/`VideoDetail`/the
analytics videos response all gain fields with default `None` — any existing frontend build (old or new)
ignores unrecognized/null fields identically; no existing field's shape or meaning changed. No spend path
touched (design constraint 1 — read-only signal, confirmed: no write to `total_cost`/`generation_ledger`/
kill-switch/pause anywhere in `early_warning.py`).

## C59 — Tenant-scoped BYOK adapter for the title-modeling brains + the two skipped MCP tools (Follow-up queue, added 2026-07-20)

**What C49 actually found, re-verified:** `title_idea/idea_modeling.py`'s `decompose_title`/
`generate_modeled_ideas` already took `anthropic_client` as a REQUIRED parameter — never constructed
one internally — so the "hardcodes a global-env `AnthropicClient()`" framing was slightly imprecise.
The real defect: both functions called `anthropic_client.messages.create(model=..., max_tokens=...,
messages=[...])` — the raw `anthropic.AsyncAnthropic` SDK shape — but EVERY real caller in this repo
(`TrendingIdeaBot.self.anthropic`, `orchestrator/pipeline.py`'s `--more-ideas` path,
`pipeline_control.py`) passes a `shared.clients.anthropic_client.AnthropicClient` WRAPPER instance,
which exposes only `.generate()` and has no `.messages` attribute at all (confirmed via AST attribute
scan of the class body). So every real invocation silently failed — the broad `except Exception` in
both functions caught the `AttributeError` and returned `None`/`[]` — with NO existing test ever
catching it (no test file for `idea_modeling.py` existed before this chunk). The wiring (client passed
as a parameter) was already correct; the CONTRACT on the receiving end was wrong. `GapTitleEngine`
(`title_idea/curiosity_gap/gap_title_engine.py`), by contrast, was already correctly built: `__init__(self,
anthropic_client=None)` with a lazy `@property` that only constructs a global-env `AnthropicClient()`
when `None` is passed — already additive/optional, and its Claude call site already uses `.generate()`.

**Threading shape:** NO new parameter was added to either function — the pre-existing `anthropic_client`
parameter (required, no default) was already the injection point once its contract matched what callers
actually pass. Fixed `decompose_title` (`title_idea/idea_modeling.py:59-65`) and `generate_modeled_ideas`
(`title_idea/idea_modeling.py:187-191`) to call `anthropic_client.generate(prompt=..., system_prompt=...,
model=Models.CLAUDE_SONNET, max_tokens=...)` instead of `.messages.create(...)` — the SAME interface
`GapTitleEngine._call_claude_for_titles` already used successfully. `Models.CLAUDE_SONNET` (this
package's own single source, `orchestrator/pipeline_constants.py`, itself env-overridable) is UNCHANGED
— same model id for both the legacy default path and the new tenant-scoped MCP path, since neither
function accepts a model override.

**Proof legacy default is unaffected:** `GapTitleEngine.__init__`/its lazy `anthropic_client` property are
untouched by this chunk (grep-verifiable — no diff touches those lines); the legacy call sites
(`pipeline.anthropic = AnthropicClient()`, `TrendingIdeaBot(anthropic_client=pipeline.anthropic, ...)`)
are untouched too — same construction as before. What changed is strictly the internal METHOD called on
whatever client object is handed in, which is required to make the function actually run (a genuine bug
fix) rather than a behavior change to preserve — there was no working legacy behavior at the
implementation level to preserve, since the bug fired for every real caller identically (see non-vacuity
below: 5 of 6 new pipeline-side tests fail against pre-fix code with the EXACT `'FakeAnthropicClient'
object has no attribute 'messages'` error).

**Key resolution reused from:** `routes/videos.py::rewrite_scene_text` (regenerate_scene_text's
underlying route) — `api_key = await get_secret("anthropic_api_key", tenant_id)`; missing-key error
matched VERBATIM: `"Anthropic API key required. Configure it in Settings > API Keys."` (pinned as
`mcp.py`'s `_NO_ANTHROPIC_KEY_ERROR` constant and asserted equal to a grep of the exact string still
present in `routes/videos.py` — the "match the exact existing wording" constraint, proven not just
duplicated by feel). New `routes/mcp.py::_resolve_tenant_anthropic_client(tenant_id)` helper: resolves
the vault key, returns `None` on miss, else `_ensure_pipeline_on_path()` (factored out of
`_call_score_title_gap_structures`'s inline sys.path snippet — now shared by 3 call sites, not
duplicated) + constructs `shared.clients.anthropic_client.AnthropicClient(api_key=api_key)` — the SAME
wrapper class every legacy caller uses, just tenant-keyed instead of env-keyed.

**MCP tools + classification:** `generate_modeled_ideas` (thin wrap: `decompose_title` per seed title →
`extract_format` → `generate_modeled_ideas`, all pre-existing `idea_modeling.py` functions, zero new
pipeline logic) and `generate_gap_titles` (thin wrap over `GapTitleEngine.generate_titles` — the
Claude-calling half `score_title_gap_structures` deliberately left unwrapped per C49's own "no existing
seam" note). Both registered FREE-BYOK in `_ATOMIC_FREE_HANDLERS` (no `confirm_token`), matching C49's
classification precedent for `regenerate_scene_text`/`suggest_video_titles` — re-verified from C49's own
tool descriptions: "Free — uses the tenant's own configured Anthropic key directly (not billed by
StoryEngine, so no confirm_token), same as `learn_channel_start`." Both attributed via
`_log_setup_write`. Tenant-scoped inputs only (`seed_titles`/`niche_variables`/`hook`/`thesis`/`facts` —
no video_id, no media URL in any input or output field name — checked programmatically in the test
file). `_REFERENCE_MODELING_TOOLS` grows from 4 to 6 tools.

**Model-id findings:** NO stale hardcoded literal Claude model ids found in either touched file — both
already reference `orchestrator.pipeline_constants.Models.CLAUDE_SONNET` (the legacy `skills/
video-pipeline` package's OWN single source, itself `CLAUDE_SONNET_MODEL` env-overridable), not a raw
pinned string like the C35 pattern (`claude-sonnet-4-20250514`, confirmed 404ing). This is a DIFFERENT
single source than `shared/channel_profile.py`'s `CLAUDE_MODELS` (the StoryEngine SaaS backend's own
source, used by `routes/videos.py::rewrite_scene_text` and other backend-native Claude calls) — by
design, per `storyengine/CLAUDE.md`: "StoryEngine SaaS (`storyengine/backend`) is canonical;
`skills/video-pipeline/` is the legacy Airtable side." Forcing these two shared legacy functions onto
`channel_profile.py`'s model id would fork the legacy package's OWN model convention for only these two
call sites while leaving every other `Models.CLAUDE_SONNET` use in that package alone — a sweep-adjacent
change explicitly out of scope, and would break "byte-identical legacy default." Left as-is; both the
legacy path and the new tenant-scoped MCP path resolve the SAME model via the SAME constant, since neither
function accepts a model override — no divergence, nothing to fix here.

**Tests:** pipeline-side `title_idea/tests/test_idea_modeling.py` (NEW directory+file, 6 tests) uses a
minimal hand-rolled `FakeAnthropicClient` (only `.generate()`, no `.messages` — matching the real wrapper
exactly) rather than importing the real `AnthropicClient`, to stay hermetic against this sandbox's broken
system-python `cryptography`/`_cffi_backend` (a pre-existing, already-baselined environment issue — see
`title_idea/curiosity_gap/tests/test_integration.py`'s 1 pre-existing failure — unrelated to this chunk,
NOT fixed here). Backend-side `storyengine/backend/tests/functional/test_c59_title_modeling_byok.py` (NEW,
12 tests): tool surface + FREE classification, no-media-url schema check, missing-key clean-error (both
tools + wording-match grep against `routes/videos.py`), vault resolver call-shape proof
(`("anthropic_api_key", tenant_id)`), tenant-isolation proof (the client object reaching the REAL
`idea_modeling`/`GapTitleEngine` functions carries the tenant's key, patched-in per test), same-callable
proof (patches the real `idea_modeling` module functions, not a parallel reimplementation), bad-input
short-circuits BEFORE any vault lookup (both tools), and a re-proof of C49's `score_title_gap_structures`
never-constructs-`GapTitleEngine` invariant (guards against this chunk accidentally wiring the scoring-only
tool to the engine). NON-VACUOUS via `git stash` on both changed source files independently: pipeline-side
5/6 new tests fail (exact `AttributeError: 'FakeAnthropicClient' object has no attribute 'messages'`);
backend-side 11/12 new tests fail (`AttributeError: module 'routes.mcp' has no attribute
'_call_generate_gap_titles'` etc.) — both restored via `git stash pop`, full re-pass.

**Suite counts:** pipeline suite (`title_idea/curiosity_gap/tests/` + new `title_idea/tests/`): baseline
**56P/1F** (the 1 pre-existing failure is the same `_cffi_backend`/cryptography panic noted above) →
after **62P/1F**, same failure by name, +6. Backend full suite: baseline **1910P/15F/1E** (re-confirmed
live via stash, same 15 failures/1 error by name as this session's starting point) → after **1922P/15F/1E**
= baseline + 12, SAME 15 failures + SAME 1 error by name, zero new. `py_compile` clean on both touched
`.py` files + both new test files. No frontend touched — `npx tsc` not run this chunk (backend/pipeline-
only change).

### Modified/New Files (C59)

| Path | Change |
|------|--------|
| `skills/video-pipeline/title_idea/idea_modeling.py` | `decompose_title`/`generate_modeled_ideas` fixed to call `anthropic_client.generate(...)` instead of the incompatible `.messages.create(...)` |
| `skills/video-pipeline/title_idea/tests/test_idea_modeling.py` | NEW (new `tests/` dir under `title_idea/`) — 6 tests |
| `storyengine/backend/routes/mcp.py` | NEW `_GENERATE_MODELED_IDEAS_TOOL`/`_GENERATE_GAP_TITLES_TOOL` tool defs (added to `_REFERENCE_MODELING_TOOLS`); NEW `_ensure_pipeline_on_path()` helper (factored out of `_call_score_title_gap_structures`'s inline snippet, now shared); NEW `_resolve_tenant_anthropic_client()` + `_NO_ANTHROPIC_KEY_ERROR`; NEW `_call_generate_modeled_ideas`/`_call_generate_gap_titles` handlers, registered in `_ATOMIC_FREE_HANDLERS` |
| `storyengine/backend/tests/functional/test_c59_title_modeling_byok.py` | NEW — 12 tests |

### Deploy-safety assessment

**ff-merge candidate.** Purely additive: 2 new MCP tool names (dark by default — `MCP_ENABLED` off in
prod, same as every other MCP chunk), no migration, no schema change, no existing route/model/frontend
field touched. The `idea_modeling.py` fix changes an internal call site inside two functions that had NO
working legacy call path to regress (every real caller already hit the `AttributeError`, silently
swallowed) — so there is no observable behavior change for existing callers to worry about; if anything
this fixes previously-silent failures for `TrendingIdeaBot`'s trending-idea-generation flow and the
`--more-ideas` CLI debug path. No spend path touched by StoryEngine's own ledger — both new tools are
BYOK (tenant's own key, never StoryEngine-billed), same non-billing shape as `regenerate_scene_text`/
`suggest_video_titles`/`learn_channel_start`.

---

## C60 — MICRO maintenance pair: dead-component deletion + rate-limit dedup finding (added 2026-07-20)

Follow-up queue item. Two independent halves — (a) shipped (structural deletion), (b) stopped short of
a merge because the two implementations are NOT behaviorally identical (see below); reported, not forced.

### (a) Deleted `storyengine/frontend/src/components/storyboard/` (DONE)

C39 left this folder in place, noting it was already dead but out of that chunk's scope (see C39 entry
above — "grepped and found imported ONLY by the now-deleted page"). This chunk re-proved orphanhood
fresh (per C19b discipline) rather than trusting C39's note, then deleted it.

**Fresh grep-proof:** grepped the whole frontend (`src/`) for every export name (`SceneGrid`,
`PanelDetail`, `StoryboardProgressBar`) and every plausible import path (`components/storyboard`,
`storyboard/index`, `scene-grid`, `panel-detail`, `storyboard/progress-bar`, `from ".../storyboard"`).
The only hits were internal cross-references within the folder itself (`panel-detail.tsx` importing
the `StoryboardPanel` type from `./scene-grid`, and the barrel `index.ts` re-exporting from both) — zero
external consumers. `ScenesWorkspaceTab.tsx`'s `handleGenerateSceneGrids` is an unrelated function name
(triggers the backend storyboard-sheet generation call), not an import of this folder.

**SACRED boundary confirmed untouched:** the in-page storyboard UI inside
`storyengine/frontend/src/components/production/ScenesWorkspaceTab.tsx` and the backend storyboard
pipeline stages (`storyengine/backend/pipeline_executor.py` `run_storyboard_*`, `skills/video-pipeline/
storyboard/`) do not import anything from the deleted folder — confirmed by the grep above (no hits
outside the deleted folder) and by inspection of `ScenesWorkspaceTab.tsx`'s import block.

**Deleted (`git rm`):** `storyengine/frontend/src/components/storyboard/{index.ts, scene-grid.tsx,
panel-detail.tsx, progress-bar.tsx}`.

**Verified:** `rm -rf .next && npx tsc --noEmit` clean (no output). `NEXT_PUBLIC_API_URL=... npm run
build` succeeded, all 33 routes generated, no errors.

### (b) `rate_limit.py` vs `routes/billing.py` `_get_tenant_plan` — STOPPED, not merged

Read both implementations in full before touching anything, per the chunk's own instruction to STOP if
semantics differ in any way. They differ in two real ways, not just style:

1. **Legacy-tenant fallback.** `rate_limit.py`'s version (lines ~139-154), when the
   `accounts JOIN memberships` lookup finds no row, falls back to `SELECT plan FROM tenants WHERE
   id = $1` (the pre-`accounts`-table legacy plan column, still live in `schema.sql`'s `tenants` table)
   before defaulting to `"free"`. `routes/billing.py`'s version has no such fallback — it returns
   `"free"` immediately on no membership row. For any tenant that predates the `accounts`/`memberships`
   split (no membership row) but still carries a non-free legacy `tenants.plan`, the two functions
   return different answers for the identical input.
2. **60s TTL cache.** `rate_limit.py` caches the resolved plan per `tenant_id` for 60 seconds
   (`_plan_cache`); `routes/billing.py` re-queries every call. Documented/intentional in `rate_limit.py`
   (added to fix a prior 429-storm bug — see `tasks/lessons.md` "rate limiter and billing resolved
   plans differently"), but it means a plan change is visible to billing checks immediately and to rate
   limiting up to 60s later.

Per the chunk's explicit branch ("match the canonical one only if rate_limit's behavior stays identical
for every input; otherwise STOP and report"): behavior is NOT identical for every input (divergence #1
is a real output difference, not just latency), so no merge was performed. Forcing rate_limit.py onto
billing.py's version verbatim would silently drop the legacy-tenant fallback for any tenant lacking a
membership row — a regression, not a cleanup.

**Import-cycle check (answered for whichever chunk picks this back up):** no cycle today. `rate_limit.py`
already does deferred (function-body) imports for `database` and `agent_tokens` rather than module-level
imports; `routes/billing.py` imports only `os`/`uuid`/`stripe`/`fastapi`/`pydantic`/`typing`/`auth`/
`database`/`email_service` — none of which import `rate_limit` or `main`. `main.py` imports `rate_limit`
(line 17) before it imports `routes` (line 18), but since nothing `routes/billing.py` pulls in reaches
back to `rate_limit`, a deferred `from routes.billing import _get_tenant_plan` inside
`rate_limit.py`'s function body would not cycle.

**No code changed for (b).** No lock-test added (would need to assert something true — "one definition
remains" is false; two intentionally-different definitions exist). Flagged in `tasks/todo.md` for a
follow-up chunk that first resolves the product question: are there still tenants with no membership
row relying on the legacy `tenants.plan` fallback? If not, delete the fallback from rate_limit.py first
(as a separate, reviewable change with its own line in this log), THEN dedup onto one shared helper. If
so, the fallback needs to move to billing.py's version too before anything can be deduped.

### Full-suite verification

Backend: `./venv/bin/python -m pytest -q` from `storyengine/backend` → **1922 passed, 15 failed, 1
error** — identical to the session baseline (1922P/15F/1E), same failures by name, zero new (expected:
(a) only touched frontend files, (b) made no code changes). Frontend: `rm -rf .next && npx tsc --noEmit`
clean; `npm run build` succeeded (33 routes).

### Modified/Deleted Files (C60)

| Path | Change |
|------|--------|
| `storyengine/frontend/src/components/storyboard/index.ts` | DELETED |
| `storyengine/frontend/src/components/storyboard/scene-grid.tsx` | DELETED |
| `storyengine/frontend/src/components/storyboard/panel-detail.tsx` | DELETED |
| `storyengine/frontend/src/components/storyboard/progress-bar.tsx` | DELETED |
| `storyengine/backend/rate_limit.py` | Unchanged — read only, finding reported above |
| `storyengine/backend/routes/billing.py` | Unchanged — read only, finding reported above |

### Deploy-safety assessment

**ff-merge candidate.** (a) removes dead frontend code with zero live consumers, proven by full-repo
grep and a clean `tsc`/`build`. (b) made no functional changes at all — pure investigation, nothing to
regress.
