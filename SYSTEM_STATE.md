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
