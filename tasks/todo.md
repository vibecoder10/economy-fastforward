# Task Tracking

## Active: Autopilot Brain Implementation

### Chunk 1: Foundation + Decision Engine ✅ COMPLETE

**27 tests passing** - All core components implemented and tested.

| Component | Status | Tests |
|-----------|--------|-------|
| `config_parser.py` | ✅ | 4 |
| `state_manager.py` | ✅ | 4 |
| `cadence_manager.py` | ✅ | 5 |
| `confidence_scorer.py` | ✅ | 5 |
| `notifier.py` | ✅ | 4 |
| `autopilot.py` (main loop) | ✅ | 5 integration |

**Commands working:**
```bash
cd skills/video-pipeline
python -m autopilot.autopilot --status     # Show status
python -m autopilot.autopilot --check-cycle # Run one cycle
python -m autopilot.autopilot --force       # Skip cadence, run now
```

### Next: Chunk 2 - Thumbnail Intel + Memory System

1. **Airtable integration** - Add `get_competitor_videos()` method to airtable_client
2. **Thumbnail analysis** - Claude Vision to analyze competitor thumbnails
3. **Memory system** - LEARNINGS.md, thumbnail_patterns.md files
4. **Pipeline trigger** - Connect autopilot to pipeline execution

### Next: Chunk 3 - CTR Monitoring + Learning Loop

1. **CTR monitor** - 6h/24h/48h checks
2. **Learning extractor** - Extract patterns from results
3. **Cron integration** - Add autopilot jobs to cron schedule

---

## Handoff Notes

**What was done:**
- Complete Chunk 1 implementation with 27 tests
- All core modules: config, state, cadence, scorer, notifier, main loop
- autopilot_program.md config file with mission, weights, thresholds
- Integration tests for full cycle

**What's next:**
- Chunk 2 planning and implementation
- Key dependency: need `airtable_client.get_competitor_videos()` method

**Key files:**
- Design spec: `docs/superpowers/specs/2026-03-18-autopilot-brain-design.md`
- Chunk 1 plan: `docs/superpowers/plans/2026-03-18-autopilot-chunk1-foundation.md`
- Implementation: `skills/video-pipeline/autopilot/`

---

## Completed: Modular Pipeline Refactor

### Status: ALL PHASES COMPLETE ✅

**Phase 1** ✅ `pipeline_constants.py` — Central config registry (436 lines)
**Phase 2** ✅ 12 step files extracted + pipeline.py wired as thin router (4,599→2,533 lines)
**Phase 3** ✅ All hardcoded values in clients/bots migrated to `pipeline_constants` imports (13 files)
**Phase 4** ✅ Shared JSON parser extracted into `json_utils.py`

### Step Files Created (`steps/`)
| File | Lines | Extracts |
|------|-------|----------|
| `step_idea.py` | ~80 | Idea generation (URL/concept + trending) |
| `step_script.py` | ~170 | Brief translator + title refinement |
| `step_voice.py` | ~80 | Voice synthesis + Drive upload |
| `step_sound_design.py` | ~40 | Sound prompt generation |
| `step_sound_effects.py` | ~50 | Sound effect generation |
| `step_image_prompts.py` | ~430 | Scene expansion + styled prompts + Story Bible |
| `step_images.py` | ~300 | Image generation with retry |
| `step_video_scripts.py` | ~135 | Motion prompt generation |
| `step_video_gen.py` | ~130 | Video clip generation |
| `step_thumbnail.py` | ~195 | Thumbnail + title generation |
| `step_render.py` | ~530 | Asset download + Remotion render + Drive upload |
| `step_upload.py` | ~150 | SEO generation + YouTube upload |

---

## Original Analysis

### The Pipeline Steps (Sequential Order)

Each step reads from Airtable, does work, writes results back to Airtable, advances status.

```
1. IDEA           → Idea Logged
2. SCRIPT         → Ready For Scripting → Ready For Voice
3. VOICE          → Ready For Voice → Ready For Image Prompts
4. IMAGE PROMPTS  → Ready For Image Prompts → Ready For Images
5. IMAGES         → Ready For Images → Ready For Sound Design
6. SOUND DESIGN   → Ready For Sound Design → Ready For Sound Effects
7. SOUND EFFECTS  → Ready For Sound Effects → Ready For Video Scripts
8. VIDEO SCRIPTS  → Ready For Video Scripts → Ready For Video Generation
9. VIDEO GEN      → Ready For Video Generation → Ready For Thumbnail
10. THUMBNAIL     → Ready For Thumbnail → Done
11. RENDER        → Ready To Render → Rendered (includes audio_sync + remotion)
12. UPLOAD        → Rendered → Uploaded (Draft)
```

---

### Dependency Analysis: What's Glued Together vs. Independent

#### TRULY INDEPENDENT (can be standalone tools):
- **Step 1 - IDEA**: Creates Airtable records. No shared state with anything. Uses: `anthropic`, `airtable`, `gemini`, `slack`, `apify`. ✅ CLEAN TOOL
- **Step 2 - SCRIPT**: Reads idea from Airtable, writes script records + Google Doc. Uses: `anthropic`, `airtable`, `google`, `slack`. The `brief_translator/` module already exists as self-contained. ✅ CLEAN TOOL
- **Step 3 - VOICE**: Reads script records, generates audio, uploads to Drive. Uses: `elevenlabs`, `google`, `airtable`, `slack`. ✅ CLEAN TOOL
- **Step 5 - IMAGES**: Reads image prompts from Images table, generates PNGs, uploads to Drive. Uses: `image_client`, `google`, `airtable`, `slack`. ✅ CLEAN TOOL
- **Step 6 - SOUND DESIGN**: Reads Images table rows, generates sound prompts. Uses: `anthropic`, `airtable`. Already delegated to `SoundPromptBot`. ✅ CLEAN TOOL
- **Step 7 - SOUND EFFECTS**: Reads sound prompts, generates audio. Uses: `sound_client`, `google`, `airtable`, `slack`. Already delegated to `SoundBot`. ✅ CLEAN TOOL
- **Step 9 - VIDEO GEN**: Reads images + motion prompts, generates clips. Uses: `image_client`, `google`, `airtable`. ✅ CLEAN TOOL
- **Step 10 - THUMBNAIL**: Reads idea, generates thumbnail image + title. Uses: `anthropic`, `image_client`, `google`, `airtable`, `slack`, `gemini`. ✅ CLEAN TOOL
- **Step 12 - UPLOAD**: Reads rendered video from Drive, uploads to YouTube. Uses: `google`, `airtable`, `slack`, YouTube API. ✅ CLEAN TOOL

#### GLUED TOGETHER (must stay as one unit or be carefully split):
- **Step 4 - IMAGE PROMPTS** (~600 lines): This is the **most complex step**. It does:
  1. Read scripts from Airtable
  2. Generate Story Bible (calls `story_bible.py`)
  3. Expand scenes into concepts (calls `deterministic_splitter` + `scene_expander`)
  4. Assign visual styles (calls `sequencer.assign_profile_styles()`)
  5. Resolve accent colors
  6. Build prompts (calls `prompt_builder.build_prompt_from_block()`)
  7. Write to Airtable Images table

  → Steps 2-4 are tightly coupled (Story Bible feeds concepts, concepts feed style assignment). Could potentially split Story Bible generation into its own step, but the rest MUST stay together. **ONE TOOL, but large.**

- **Step 8 - VIDEO SCRIPTS** (~120 lines): Reads images + text, generates motion prompts with camera rotation tracking. Uses `anthropic`, `airtable`, `image_prompt_engine.validate_video_prompt`. The camera history state makes it sequential. ✅ CAN be a tool (camera history is local state within the run).

- **Step 11 - RENDER** (~1100 lines): This is the **second most complex step**. It does:
  1. Download all assets from Drive (images, videos, audio, sound effects)
  2. Run audio sync (Whisper transcription → alignment → timing)
  3. Generate render config JSON
  4. Package for Remotion
  5. Call Remotion render
  6. Upload rendered video to Drive

  → Audio sync + render config + Remotion packaging are tightly coupled. They share local filesystem state (the working directory with downloaded assets). **Must stay as ONE TOOL.**

---

### What ACTUALLY Needs to Happen

#### Phase 1: `pipeline_constants.py` — Central Variable Registry
One file, all shared variables. Every other file imports from here.

```python
# Airtable field names (25+ currently hardcoded as strings across 15+ files)
# Pipeline statuses (13 statuses, currently class constants in pipeline.py)
# Model IDs (4 different versions scattered across 9 bot files)
# API endpoints (5+ URLs hardcoded in client files)
# Tuning constants (timing, word counts, thresholds — scattered across 5+ files)
```

**Impact**: Zero behavior change. Pure extract-and-reference. Every file that touches these values imports from one place.

#### Phase 2: Extract 12 steps into `steps/` directory
Each file = one pipeline step = one "tool". Contract:

```python
# steps/step_voice.py
async def run(ctx: PipelineContext) -> dict:
    """Generate voice overs for all scenes."""
    ...
```

Where `PipelineContext` is a simple dataclass holding:
```python
@dataclass
class PipelineContext:
    # Clients (injected, not created)
    anthropic: AnthropicClient
    airtable: AirtableClient
    google: GoogleClient
    slack: SlackClient
    elevenlabs: ElevenLabsClient
    image_client: ImageClient
    gemini: GeminiClient
    sound_client: SoundClient | None
    apify: ApifyYouTubeClient | None

    # Current video state (set by router before calling step)
    video_title: str
    current_idea_id: str
    current_idea: dict
    project_folder_id: str | None
    video_config: VideoConfig | None
    visual_style: str | None
    core_image_url: str | None

    # Targeting filters
    scene_filter: int | None
    image_filter: int | None
```

`pipeline.py` becomes a ~300-line router:
```python
STEP_MAP = [
    (Statuses.READY_SCRIPTING,       "Brief Translator",  step_script.run),
    (Statuses.READY_VOICE,           "Voice Bot",         step_voice.run),
    (Statuses.READY_IMAGE_PROMPTS,   "Image Prompt Bot",  step_image_prompts.run),
    (Statuses.READY_IMAGES,          "Image Bot",         step_images.run),
    (Statuses.READY_SOUND_DESIGN,    "Sound Prompt Bot",  step_sound_design.run),
    (Statuses.READY_SOUND_EFFECTS,   "Sound Bot",         step_sound_effects.run),
    (Statuses.READY_VIDEO_SCRIPTS,   "Video Script Bot",  step_video_scripts.run),
    (Statuses.READY_VIDEO_GENERATION,"Video Gen Bot",     step_video_gen.run),
    (Statuses.READY_THUMBNAIL,       "Thumbnail Bot",     step_thumbnail.run),
    (Statuses.READY_TO_RENDER,       "Render Bot",        step_render.run),
    (Statuses.RENDERED,              "Upload Bot",        step_upload.run),
]
```

#### Phase 3: Migrate hardcoded values
Every bot/client file that currently hardcodes field names, model IDs, or URLs → import from `pipeline_constants.py`.

#### Phase 4: Shared JSON parser
Extract duplicated pattern from 5+ bots into `clients/json_utils.py`.

---

### Execution Order
1. Phase 1 (constants) — additive, zero risk
2. Phase 2 (extract steps) — mechanical, high line count but straightforward
3. Phase 3 (migrate hardcoded values) — each file individually
4. Phase 4 (JSON parser) — small utility extraction
5. Run all 312 tests after each phase

---

## Previous Completed Items

- [x] Image Prompt Pipeline Fixes (2026-03-14) — DONE
- [x] Visual Style Overhaul: Mannequin → Cinematic Illustration (2026-03-14) — DONE
- [x] Scene Blocking System (Story Bible V2) — DONE (2026-03-14)
- [x] Blocking Script Validation with Senior Editor Pass — DONE (2026-03-14)

## Active: Storyboard Visual Consistency

### Story Bible → Storyboard Wiring ✅
- [x] Wire Story Bible loading into `run_storyboard_grids()` and `run_storyboard_preview()`
- [x] Add `story_bible` param to `generate_storyboard_directive()`
- [x] Inject character/location/arc data into `_build_directive_user_prompt()` as binding constraints
- [x] Add visual bible rule (#6) to `_build_directive_system_prompt()` non-negotiable rules
- [x] Add `_format_story_bible_for_beat()` — extracts characters, locations, visual arc, scene blocks per beat
- [x] Add `_load_story_bible()` — loads + parses Story Bible JSON from Airtable idea fields

### Character Reference Images (BYOC) ✅
- [x] Add `CHARACTER_REFERENCE` to IdeaFields in `pipeline_constants.py`
- [x] Add `_load_character_reference()` to extract image URL from Airtable attachment
- [x] Update `generate_contact_sheet()` to accept `character_reference_url`
- [x] Wire through `run_storyboard_grids()` → `generate_contact_sheet()`
- [x] Fix pre-existing bug: contact sheet was using wrong image_client method
- [x] Document field in `airtable-schema.md`
- [ ] **USER ACTION**: Create `Character Reference` attachment field in Airtable Idea Concepts table

## Handoff
**What was done** (2026-03-18):

### MAJOR: Autopilot Brain Design & Planning Complete

Designed and spec'd a complete autonomous video production orchestrator ("Autopilot Brain") modeled on karpathy/autoresearch. This is the "brain" layer that sits above the existing pipeline.

**Design Spec:** `docs/superpowers/specs/2026-03-18-autopilot-brain-design.md` (789 lines)
**Chunk 1 Implementation Plan:** `docs/superpowers/plans/2026-03-18-autopilot-chunk1-foundation.md` (1941 lines)

**What the autopilot does:**
1. ON/OFF switch via `autopilot_program.md`
2. Cadence management (videos_per_month = 15 → every 2 days)
3. Scores candidates from Competitor Videos table using weighted signals
4. Picks best idea, notifies Slack with full reasoning
5. Analyzes competitor thumbnails (Claude vision) → writes style overrides
6. Triggers pipeline → YouTube draft
7. Monitors CTR at 6h/24h/48h
8. Extracts learnings to persistent memory files (`autopilot/memory/LEARNINGS.md`)
9. Compounds intelligence over time

**Implementation is broken into 3 chunks:**
- **Chunk 1** (plan written): Foundation + Decision Engine — config, state, cadence, scoring, notifier
- **Chunk 2** (not yet planned): Thumbnail Intel + Memory System
- **Chunk 3** (not yet planned): CTR Monitoring + Learning Loop + Integration

**What's next:**
1. **Implement Chunk 1** — Follow the plan at `docs/superpowers/plans/2026-03-18-autopilot-chunk1-foundation.md`
   - 8 tasks, TDD approach, 18+ tests
   - Creates `autopilot/` directory structure
   - Entry point: `python -m autopilot.autopilot --status`
2. After Chunk 1 complete → write Chunk 2 plan
3. Manual pipeline still works — autopilot is purely additive

**Key files to read for context:**
- `docs/superpowers/specs/2026-03-18-autopilot-brain-design.md` — Full design spec
- `docs/superpowers/plans/2026-03-18-autopilot-chunk1-foundation.md` — Implementation plan
- CLAUDE.md now includes autopilot structure and commands

**Cron jobs to add (after implementation):**
- 6:30 AM: `autopilot --check-cycle`
- 7:30 AM: `autopilot.ctr_monitor`
- 8:30 AM: `autopilot.learning_extractor`

---

### Previous (2026-03-18 earlier):
1. **Problem 1 - Duration validation**: Added Slack notification + pipeline halt when "Video Length (min)" is not set in Airtable.
2. **Problem 2 - Script field fix**: Added LOUD failure + script preview + simple `approved` command handler

---

## Backlog

### Phase 2: Character Consistency
- [x] Story Bible → Storyboard wiring (2026-03-18) — DONE
- [ ] Feature 1: Character Reference System (BYOC) — HIGH (next)
- [ ] Feature 5: Style Locking via Golden Frame — HIGH
- [ ] Feature 10: Quality Scoring via Gemini Vision — MEDIUM

### Phase 3: Product Mode
- [ ] Feature 3: One-Shot `!create` Pipeline — HIGH
- [ ] Feature 4: Airtable Schema Optimization — MEDIUM
- [ ] Feature 7: Health Dashboard & Self-Healing — MEDIUM

### Phase 4: Animation Quality
- [ ] Feature 8: Start/End Frame Bridging — MEDIUM
- [ ] Feature 9: Multi-Voice & Sound Design — LOW

---

## Creative Visual Story Engine — Vision Audit (2026-03-18)

**Vision**: A democratized visual storytelling engine that lets anyone create animated content without technical skills. Users bring their story, style, and characters — the system handles everything else.

### Vision Alignment Scorecard

| Pillar | Coverage | Status |
|--------|----------|--------|
| Bring Your Own Story | 80% | ✅ Works well |
| Bring Your Own Style | 60% | 🟡 Needs UI for hot-swap |
| Bring Your Own Characters | 40% | 🔴 CRITICAL GAP |
| Modular & Bulletproof | 50% | 🟡 Two parallel paths |
| End-to-End Execution | 85% | ✅ Works well |

### 🔴 Critical Gap: Character Bible Not Injected into Image Prompts

**Problem**: Story Bible generates exact character descriptions, but `image_prompt_bot.py` does NOT read them. Claude writes prompts from scratch → characters look different every scene.

**Fix Required**:
1. Load Story Bible in `image_prompt_bot.py`
2. Inject character descriptions into Claude's prompt with "USE EXACT" instruction
3. Estimated: 2-3 hours

### Priority Enhancement List

| # | Enhancement | Impact | Effort | Files |
|---|-------------|--------|--------|-------|
| 1 | **Character Bible → Image Prompts** | 🔴 Critical | 2-3 hrs | `image_prompt_bot.py` |
| 2 | **Integrate storyboard into main pipeline** | High | 4-5 hrs | `pipeline.py`, `storyboard_bot.py` |
| 3 | **Character library (persist & reuse)** | High | 3-4 hrs | NEW: `character_library.py` |
| 4 | **Style profile upload UI** | Medium | 2-3 hrs | `channel_profile.py`, `pipeline_control.py` |
| 5 | **Voice selector UI** | Medium | 1-2 hrs | `pipeline_control.py`, `voice_bot.py` |
| 6 | **Multi-format batch render** | Medium | 3-4 hrs | `render_video.py` |
| 7 | **Character consistency validator** | Medium | 4-5 hrs | NEW: `validators/character_consistency.py` |
| 8 | **Script template selection** | Low | 2-3 hrs | `script_generator.py` |

### Architecture Enhancement: Story Bible Central

```
PROPOSED (Story Bible as single source of truth):
┌─────────────────────────────────────────────┐
│            STORY BIBLE (Central)             │
│   Characters │ Locations │ Visual Arc        │
└──────────────────────┬──────────────────────┘
                       │
         ┌─────────────┴─────────────┐
         ▼                           ▼
    Storyboards                Image Prompts
    (Visual Lock)              (Uses Bible)
         │                           │
         └───────────┬───────────────┘
                     ▼
               Consistent Images
```

### New Airtable Fields Needed (Scripts Table)

- [ ] **Storyboard Prompts** (Long Text) — Copy to Gemini for review
- [ ] **Storyboard 1** (Attachment) — First 3×3 grid
- [ ] **Storyboard 2** (Attachment) — Second 3×3 grid
- [ ] **Storyboard 3** (Attachment) — Third 3×3 grid (for 19+ images)

### Storyboard System Built (2026-03-18)

- [x] `generate_scene_storyboard_prompts()` — Groups images into 3×3 grids
- [x] `generate_storyboard_prompts_for_video()` — Processes all scenes
- [x] Calculate storyboard count from image count: `ceil(images/9)`
- [x] Build unified contact sheet prompts with visual consistency anchors
- [x] Fix `ScriptFields.SCENE` to lowercase 'scene' to match Airtable
- [x] XY extraction formula: `Sentence Index = (Storyboard# - 1) × 9 + (Y - 1) × 3 + X`

### Bug Fixes Applied (2026-03-18)

- [x] Remove broken `FIELD` import from pyairtable (pyairtable 3.x compatibility)
- [x] Fix Python 3.9 type hint compatibility (`Optional[dict]` not `dict | None`)
- [x] Fix keyframe parsing to handle Claude's **bold** markdown
- [x] Fix duplicate keyframes by only parsing KEYFRAMES section
- [x] Pass beat duration to directive generator (was hardcoded 10-20s, now uses actual duration)
