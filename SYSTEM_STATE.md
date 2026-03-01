# System State — Economy FastForward

> Last updated: 2026-03-01

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

## 2. Key File Paths

### Pipeline Core (`skills/video-pipeline/`)

| File | Purpose |
|------|---------|
| `pipeline.py` | Main orchestrator — reads Airtable status, routes to correct bot |
| `pipeline_control.py` | Slack bot — receives `!` commands, triggers pipeline stages |
| `approval_watcher.py` | Monitors Airtable for manual approvals |
| `discovery_scanner.py` | Finds trending topics for video ideas |
| `research_agent.py` | Deep research on topics using Claude |
| `render_video.py` | Calls Remotion to produce final MP4 |
| `performance_tracker.py` | Daily YouTube metrics sync → Airtable |

### API Clients (`skills/video-pipeline/clients/`)

| File | Service |
|------|---------|
| `airtable_client.py` | Airtable — record CRUD, status transitions |
| `google_client.py` | Google Drive & Docs — file upload, folder management |
| `image_client.py` | Kie.ai — image/video generation (Seed Dream 4.5, Veo 3.1) |
| `elevenlabs_client.py` | ElevenLabs via Wavespeed — voice synthesis |
| `anthropic_client.py` | Claude AI — scripts, prompts, analysis |
| `slack_client.py` | Slack — notifications (non-blocking) |
| `gemini_client.py` | Gemini Vision — thumbnail spec extraction |
| `style_engine.py` | Internal — scene types, camera patterns |

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

### Config & Env

| Path | Purpose |
|------|---------|
| `.env` | All secrets (gitignored, never committed) |
| `.env.example` | Template with descriptions for all required env vars |
| `CLAUDE.md` | AI assistant instructions and codebase reference |

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
**Source:** `skills/video-pipeline/setup_cron.sh`

Each job auto-pulls from GitHub (`git pull origin main --ff-only`) before running.

| Time | Job | Command | Timeout |
|------|-----|---------|---------|
| 2:00 PM UTC (6:00 AM PST) daily | Discovery Scanner | `pipeline.py --discover` | 10 min |
| 6:00 AM UTC daily | Performance Tracker | `performance_tracker.py` | 10 min |
| 8:00 AM PT daily | Pipeline Queue Runner | `pipeline.py --run-queue` | 4 hours |
| Every 15 min | Bot Health Check | `bot_healthcheck.sh` | — |
| Every 30 min | Approval Watcher | `approval_watcher.py` | 10 min |

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

## 8. Known Issues / Tech Debt

### Critical

- **String joins instead of linked records** — Idea Concepts, Scripts, and Images tables are joined by `Title` = `Video Title` string matching. Typos silently break relationships. Should migrate to Airtable linked records.
- **3 overlapping status fields on Images table** — `Status`, `Video Status`, `Animation Status` track related but separate states. Easy to miss updating one.

### Medium

- **`Sentence Index` duplicates `Image Index`** — Same value, confusing names. Rename to `Segment Index`.
- **Thumbnail field format inconsistency** — Code tries 3 field name/format combos as fallbacks. Should standardize.
- **No cost tracking** — No per-image or per-video cost logging. Budget alerts exist only for animation pipeline (80% threshold).
- **No audit trail** — No `CreatedBy`, `ProcessedBy`, or modification timestamps on records.
- **No soft deletes** — Old/failed records clutter tables. No archive mechanism.
- **MANUAL_STEP.md is outdated** — Superseded by `setup_cron.sh` but still exists.

### Low

- **No pagination for large batches** — Works for single-video processing; would need pagination for bulk operations.
- **Attachment format inconsistency** — Some fields use `[{"url": ...}]`, others use plain URLs.

### Proposed Improvements (from ANIMATION_SYSTEM_REVIEW.md)

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
