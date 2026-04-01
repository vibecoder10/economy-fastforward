# Task Tracking

## Completed: Pipeline Reorganization (2026-03-24)

Full codebase reorganization of `skills/video-pipeline/`. Each tool is now a standalone folder with its own manifest.json. Agent quality pipeline added (hook/body/CTA with iterative scoring).

## StoryEngine SaaS UI — Current State (2026-03-24)

### Completed Modules

**Module 0: Supabase Migration Verification** ✅
- 51 columns added across 5 tables, 5 schema bugs fixed
- Migrations: 004 (schema parity), 005 (agent + suggestion columns), 006 (niche columns)
- All migrations applied to live Supabase

**Module 1: Design System + Dashboard + Pipeline** ✅
- Dark editorial design tokens (charcoal #0A0A0B, amber #D4A844, teal #1A8A7A)
- 6-tab mobile bottom bar, 7-item collapsible desktop sidebar
- Dashboard: action-first (approvals, activity, stats)
- Pipeline: dropdown filters, search, progress dot cards

**Module 2: Video Detail (5 tabs) + Create** ✅
- `/pipeline/[videoId]` — Info, Script, Visuals, Thumbnail, Performance tabs (Board merged into Visuals)
- `/create` — New video form (title, angle, thesis + advanced options)

**Module 4: Autopilot + Analytics + Agent Suggestions** ✅
- `/analytics` — CTR bar chart (Recharts), revenue estimates, per-video cards
- `/autopilot` — Restyled, agent quality stats, top 3 recommendations
- Suggestion system: suggested_script/title/thumbnail with accept/reject
- Script diff UI, thumbnail variant visual UI

**Module 5: Niche Selection + Topic Discovery** ✅
- `/competitors` — Playing card grid with YouTube thumbnails, VPH, confidence
- Channel filter pills + dropdown
- Card expanded modal (theirs vs yours + thumbnail workshop)
- Thumbnail workshop with prompt iteration carousel
- Niche setup wizard (category → sub-niche → channels)
- `/autopilot` simplified to top 3 decision maker with "View All →" link

**Module 3: Interactive Features** ✅
- Script tab: inline text editing, tone dropdown, per-scene voice generation, collapsible sentence segments
- Visuals tab: storyboard mode toggle (ON: grids side-by-side with magnified CSS panel viewer + VO, OFF: direct image generation cards)
- Per-tab pipeline advancement via StageAdvancer (calls specific stage endpoints, not generic advance)
- Background task polling (useTaskPoller hook)
- Tab consolidation: 6→5 tabs (storyboard merged into visuals)
- Thumbnail tab: "Approve → Render" advancement
- Competitor channel URL input bar on `/competitors`
- Backend: 5 new scene endpoints, expanded script query, targeted voice/image regen with status gate bypass
- Migration 007: tone column on scripts

### Not Yet Built

**Future Modules:**
- Channel onboarding + baseline learning (import existing YouTube data)
- Batch topic selection / "Queue All"
- Calendar production view
- Settings page (Channel Profile, API keys, pipeline config)
- Multi-tenant architecture
- Billing & subscriptions

---

## Handoff Notes

**VPS Info:**
- SSH: `ssh clawd@76.13.119.181` (password: Economyfastforward)
- Frontend: `http://76.13.119.181:3001` (Next.js, port 3001)
- Backend: `http://76.13.119.181:8001` (FastAPI, port 8001)
- Auto-deploy cron: every 5 min pulls git + rebuilds frontend

**Key specs:**
- UI/UX spec: `docs/superpowers/specs/2026-03-23-storyengine-ui-ux-addendum.md`
- Module 5 spec: `docs/superpowers/specs/2026-03-24-module5-niche-discovery-design.md`

**Architecture decisions:**
- Agent pipeline is the PRIMARY script generation path (not a polish layer)
- Brief translator is legacy (VPS cron pipeline)
- Supabase is single source of truth, Airtable data imported
- Suggestions stored as proposed overwrites (human approves inline)
- Autopilot = decision maker (top 3), Competitors = research/browse (all cards)

## Current: Airtable → Supabase Pipeline Wiring (2026-03-26)

**Plan:** `~/.claude/plans/snappy-launching-lantern.md`

**Done:**
- SupabaseAdapter created (`storyengine/backend/supabase_adapter.py`) — 42 sync psycopg2 methods mirroring AirtableClient
- Adapter wired into PipelineExecutor (replaces `pipeline.airtable`)
- Status gates fixed to use `is_at_or_past_stage()`
- psycopg2-binary installed on VPS, deployed
- **✅ Pipeline initialization unblocked** (2026-03-26): LightPipeline replaces VideoPipeline. No full pipeline import needed.
- **✅ Script generation works end-to-end** (2026-03-26): "Generate Script" button → 6 scenes created → status → Ready For Voice
  - Fixed: `airtable_record_id` lookup → direct Supabase UUID lookup (all 13 `run_*` methods)
  - Fixed: `VideoConfig(target_minutes=...)` → `VideoConfig(video_length_minutes=...)`
  - Fixed: Bot subdirs (script/, voice/, etc.) added to sys.path for internal imports
  - Fixed: NoOpSlack/NoOpGoogle with `__getattr__` for safe fallback
  - Fixed: `_update_status()`, `image_filter`, `scene_filter` added to LightPipeline
  - Fixed: `update_idea_fields` returns written fields for verification checks
  - Fixed: Research agent import path (`research.agent` not `research_agent`)

**Missing clients (non-blocking for now):**
- GoogleClient: OAuth credentials not on VPS → Drive folders skip, Google Docs skip
- SlackClient: No SLACK_BOT_TOKEN on VPS → notifications skip
- ElevenLabsClient: No WAVESPEED_API_KEY → voice generation will fail

**Pipeline E2E Test Results (2026-03-31):**
- ✅ Research: 20-field payload generated (Claude API)
- ✅ Script: 15,781 char 6-act script (Claude API, blocked by validation but script saved)
- ✅ Split: 117 sentence segments across 6 scenes (pure Python, no API)
- ✅ Image Prompts: 117 cinematic prompts generated (Claude API)
- ⏭️ Voice: SKIPPED (no ElevenLabs key — mock durations set for testing)
- 🔜 Image Generation: Ready (Kie.ai key available, ~$3 cost)
- 🔜 Remaining: Video Scripts, Video Gen, Sound, Thumbnail, Render, Upload

**Fixes applied:**
- `pipeline_executor.py`: Added `title_idea` to sys.path for research imports
- Migration 013: 9 missing columns across 3 tables
- `AnthropicClient` made optional (try/except) in pipeline init
- Python deps installed: pyairtable, google-auth, google-api-python-client, slack_sdk, mutagen, anthropic, psycopg2-binary

**Next steps:**
1. ⚠️ Run migration 013 on production Supabase (required before VPS pipeline works)
2. Add ElevenLabs API key to vault for voice generation
3. Test image generation step (Kie.ai, $3 cost)
4. Test remaining pipeline steps (video scripts → render)
5. Add Google OAuth + Slack credentials for full pipeline
6. Fix frontend wiring: 4 mock pages, 7 dead buttons, 17 orphan API functions (see WIRING_STATUS.md)

---

## Session: Storyboard & Visuals Tab Redesign + Pipeline UX (2026-04-01)

### Completed
- **Fixed VPS deployment**: stale build chunks causing "This page couldn't load" — server was loading old manifests. Created `infra/storyengine_deploy.sh` auto-deploy cron (every 30 min).
- **Unified Storyboard & Visuals tab**: grids first (340x200, click-to-expand), per-scene VoicePlayer, collapsed narration + image segments.
- **Script tab → Script only**: removed audio transport bar/playback, kept voice generation buttons + status badges.
- **Pipeline steppers**: Both Script and Storyboard tabs now have visual 1-2-3 step indicators with CTA buttons.
- **Script auto-split**: sentences auto-split after script generation completes. "Split Sentences" button removed.
- **"Generate Image Prompts" moved**: from Script tab to Storyboard tab (where it belongs as Step 1).
- **Click to Generate on pending grids**: clickable placeholders instead of passive "Pending" label.
- **Dynamic grid sizing**: storyboard bot now generates right-sized grids (1x2 for 2 panels, etc.) instead of always 3x3.
- **Fixed storyboard skip bug**: `run_images.py` was checking only first scene's status — now checks ALL beats.
- **Fixed status gate**: relaxed `storyboard-images` endpoint from `ready_for_storyboard_images` to `ready_for_image_prompts`.
- **Image prompt guard**: storyboard prompt generation blocked if <50% segments have image prompts.

### Completed (2026-04-01 Session 2)
- **Per-scene storyboard generation**: Backend accepts `?scene=N` query param on both `storyboards` and `storyboard-images` endpoints. Per-scene bypasses status gate. Frontend has per-scene "Gen Prompts", "Gen Grids", "Clear", and "Regenerate" buttons on each scene card.
- **Live progress indicators**: Bot reports "Generating Scene 2/6, Beat 1/3..." via `progress_callback`. Messages flow through task poller to UI in real-time. Purple progress banner shows under storyboard pipeline section.
- **Storyboard status badges**: Each scene card shows its `storyboard_status` (prompts_ready, grids_generated, partial_1_of_2, etc.)
- **Clear old grids**: Per-scene "Clear" button and global "Clear All Storyboards" button wired end-to-end.
- **Grid placeholder click → per-scene**: Clicking empty grid generates grids for THAT scene only (not all scenes).
- **Deploy script race condition fixed**: Root cause was Next.js loading chunk manifest into memory at startup. Old server process lingers after `pkill`, serving HTML referencing old chunk hashes that no longer exist. Fix: SIGTERM → 5s wait → SIGKILL → `fuser -k 3001/tcp` → verify port free → build → start.
- **Tested live**: Per-scene grid generation works end-to-end (Scene 1 Beat 1/2 generated successfully via API, visible in UI).

### In Progress / Next Session
1. Backend needs automatic restart on deploy (currently manual restart required for Python changes)
2. Scene 6 has no storyboard prompts — need to generate prompts before grids
3. Some scenes show `grids_generated` status but have no actual grids (stale status from previous run without scene_filter)

---

## Completed: Cinematic Continuity Contact Sheets (2026-04-01)

Restructured storyboard directive system prompt to produce structured contact sheet prompts that generate visually continuous 3×3 grids. Tested with Gemini — father character consistent across panels, strait geography consistent across 5 panels, data screens share visual language.

**Changes (all in `storyboard/bot.py`):**
1. **Rules 7-8 added** to `<non_negotiable_rules>`: continuity threading (character position, setting locks, visual bridges) + narration-visual alignment (panels must show what narration says)
2. **Contact sheet prompt format restructured**: Preamble with character/setting locks → per-panel descriptions with Kelvin color temps, focal lengths, frame positions, gaze direction → technical footer. Replaces the old freeform format.
3. **Cross-beat state passing**: `prev_beat_exit` dict tracks last keyframe's shot type, composition, and lighting. Injected into next beat's user prompt as `PREVIOUS BEAT EXIT` context block. Wired through `_build_directive_user_prompt()` → `generate_storyboard_directive()` → beat loop.
4. `build_image_prompt_from_keyframe()` already included lighting (no change needed).

**Next:**
- Test on a real video with storyboard generation
- Consider switching contact sheet model from Nano Banana Pro to Gemini (produced much better results in manual testing)

---

## Completed: Page-by-Page UI/UX Overhaul (2026-03-26)

**Branch:** `claude/page-fixes-round1` (pushed, not merged)
**Completion Report:** `COMPLETION_REPORT_D.md`

All 6 sections done:
1. Tab restructure (9→8 tabs, 6-step labeled stepper)
2. ScriptVoiceTab — combined script editing + inline voice per scene
3. StoryboardVisualsTab — voice guard rail + visuals workflow
4. Approval gates — Run Next Step stops at checkpoints
5. Pipeline integrity — voice required before image generation
6. Bug fixes — analytics crash, thumbnails, Gemini retry, character persistence

30/30 checklist items PASS. TypeScript compiles clean.

**Dev tools built:**
- Voice Typer: `~/whisper-dictation/` (Fn key dictation, auto-starts on login)
- Browser Watcher: `~/browser-watcher/watcher.py` (Playwright monitoring)
- Chrome Extension: `~/browser-watcher/extension/` (session recorder with voice + screenshots)
- Session Server: `~/browser-watcher/session_server.py` (bundles sessions → Claude CLI)
- Auto-deploy: `~/browser-watcher/deploy.sh` (commit → push → VPS pull + restart)
