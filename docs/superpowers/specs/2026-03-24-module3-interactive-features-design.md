# Module 3: Interactive Features — Design Spec

**Date:** 2026-03-24
**Status:** Draft
**Scope:** Make the video detail page fully interactive — script editing, voice generation, storyboard review, image generation, and pipeline advancement.

---

## Overview

Module 3 transforms the 6-tab video detail page from read-only to interactive. Every tab that currently displays data gets controls to edit, regenerate, approve, and advance through the pipeline.

**Pipeline flow reflected in UI:**
```
Script (edit/regen) → Voice (generate per-scene) → Image Prompts (auto)
  → [Storyboard toggle]
      ├─ ON:  Generate grids → Review panels (magnified viewer) → Advance = extract + upscale
      └─ OFF: Generate images directly → Review → Approve
  → Thumbnail → Render
```

---

## 1. Script Tab — Interactive Editing

### Current State
Read-only scene list. Accept/reject for agent suggestions only.

### New Interactions

**Scene card structure (per scene):**
- Scene badge + act label
- Tone dropdown: `Serious | Conversational | Urgent | Concise`
- Regenerate Scene button — re-calls Claude with tone setting, replaces scene text
- Editable script text — click to activate textarea, auto-saves on blur
- Voice generation button (teal) — appears when script text exists but no voice
- Mini audio player — appears after voice is generated (play/pause, waveform, duration, redo button)
- Collapsible sentence segments — collapsed by default, expand to see image splits

**Sentence segments (expanded state):**
- Lists each segment with: image index, segment text, word count, duration (words ÷ 2.5 wps), visual style tag
- Split handles (⋮⋮) between segments for adjusting where one ends and next begins
- Re-split button — auto-recalculates segments after editing scene text
- Segments always visible when expanded, same layout as the collapsed toggle but inline

**Voice generation:**
- Teal "Generate Voice" button on scene card when script exists + no voice
- After generation: mini audio player replaces the button
- Player: play/pause circle, waveform bar, timestamp, "Redo" button to regenerate
- Voice state persists — regenerating script text shows warning that voice will need re-generation

### Backend Requirements

| Endpoint | Method | Purpose | Exists? |
|----------|--------|---------|---------|
| `/api/videos/{id}/script` | GET | Fetch scenes | Yes |
| `/api/pipeline/script/{id}` | POST | Regenerate full script | Yes |
| `/api/videos/{id}/scenes/{scene}/text` | PATCH | Update single scene text | **New** |
| `/api/videos/{id}/scenes/{scene}/tone` | PATCH | Update scene tone setting | **New** |
| `/api/pipeline/voice/{id}` | POST | Generate voice for all scenes | Yes |
| `/api/pipeline/voice/{id}?scene={n}` | POST | Generate voice for single scene | **New** (query param) |
| `/api/videos/{id}/scenes/{scene}/segments` | GET | Get sentence text segments | **New** |
| `/api/videos/{id}/scenes/{scene}/segments` | PUT | Update segment split points | **New** |

---

## 2. Visuals Tab — Storyboard Mode + Image Generation

### Current State
Read-only grid of generated images grouped by scene.

### New: Storyboard Mode Toggle

Top of the Visuals tab has a toggle: **Storyboard Mode ON/OFF**. This controls the entire visual generation flow.

When toggled, writes `storyboard_on_off` to the video's scenes in the database.

**Storyboard ON info banner:**
> "Image prompts → 3×3 contact grids per scene → review panels → advance to extract + upscale"

**Storyboard OFF info banner:**
> "Image prompts → generate final images directly (faster, no grid review)"

### Pipeline Progress Indicator

Horizontal step indicator at top showing where the scene is in the visual pipeline:

**Storyboard ON (4 steps):**
1. Prompts Generated ✓
2. Storyboard Grids (current/pending)
3. Panel Review
4. Final Images (extract + upscale on advance)

**Storyboard OFF (3 steps):**
1. Prompts Generated ✓
2. Generate Images (current/pending)
3. Review & Approve

---

### 2A. Storyboard ON — Grid Review with VO

**Per-scene card contains:**

1. **Scene header** — badge, act label, image count, grid count, approval count
2. **VO player** — embedded at top of each scene card
   - Play/pause button, waveform visualization, timestamp
   - As audio plays, the currently-corresponding panel gets an amber highlight + speaker icon in the grid
   - Same audio from the Script tab (scene voice-over)
3. **Storyboard grids side by side** — 1-5 grids per scene depending on image count (9 panels per grid)
   - Each grid: 3×3 contact sheet image
   - Panel numbers overlaid (1, 2, 3... continuous across grids)
   - Status indicators on each panel: ✓ green (approved), ✗ red (rejected), no icon (pending)
   - Regen button per grid (regenerates that 3×3 contact sheet)
   - Grids scroll horizontally when 3+ grids exist
4. **Storyboard prompt (collapsible)** — below the grids, an expandable section showing the full storyboard directive prompt
   - Collapsed by default (one-line preview)
   - Expand to see the full prompt that was sent to the grid generator
   - Editable — user can manually alter the prompt before regenerating a grid
   - "Regen with edited prompt" button appears when prompt text is modified
   - This is the directive-level prompt (controls the whole grid composition), separate from per-panel image prompts
5. **Magnified panel viewer** — click any panel in a grid to open detail below
   - **This is a CSS crop/zoom of the grid image region, NOT an extracted image**
   - No API calls, no credits — purely a UI magnification
   - Shows: enlarged panel, sentence text for that segment, collapsible prompt (per-panel image prompt)
   - Actions: Approve, Reject, Regen Panel, Edit Prompt, Hero Shot toggle
   - Arrow key navigation crosses grid boundaries seamlessly (panel 9 → panel 10 = grid 1 → grid 2)
5. **Keyboard shortcuts** — ← → navigate panels, Space play/pause VO, A approve, R reject
6. **Advance button** — "Extract & Upscale Approved" — only appears when panels are reviewed
   - This is the pipeline advancement action (costs credits)
   - Extracts approved panels from contact sheets and upscales to production resolution
   - Only triggers when user explicitly advances

**Grid sizing:**
- Each grid: 280×280px on desktop, scales down proportionally on mobile
- Panels within grid: ~90×90px (clickable to magnify)
- Magnified view: 180-200px enlarged crop

**Grid count per scene:**
- Scene with 1-9 images → 1 grid
- Scene with 10-18 images → 2 grids
- Scene with 19-27 images → 3 grids (rare, very long scenes)
- Last grid may have empty slots (dashed border placeholder)

### 2B. Storyboard OFF — Direct Image Generation

**Per-scene card contains:**

1. **Scene header** — badge, act label, segment count, generated count, cost
2. **VO player** — same as storyboard mode
3. **Segment cards** — one horizontal card per image segment:
   - Image thumbnail (160×90px) or placeholder if not generated
   - Sentence text for that segment
   - Collapsible prompt (collapsed by default, one-line preview, expand to see full + edit)
   - Image index badge, visual style tag (dossier/schema/echo)
   - Actions:
     - **Not generated:** amber "Generate · $0.025" button
     - **Generated:** Regenerate, 3 Variants ($0.075), Edit Prompt, Hero Shot toggle
4. **"Generate All Missing"** button — batch generates all ungenerated segments for the scene
5. **Cost display** — per-image and cumulative, always visible

### Backend Requirements

| Endpoint | Method | Purpose | Exists? |
|----------|--------|---------|---------|
| `/api/videos/{id}/assets` | GET | Fetch all assets | Yes |
| `/api/videos/{id}/storyboard-mode` | PATCH | Toggle storyboard on/off | **New** |
| `/api/pipeline/storyboards/{id}` | POST | Generate storyboard grids | Yes |
| `/api/pipeline/storyboard-images/{id}` | POST | Generate grid images | Yes |
| `/api/pipeline/storyboard-extract/{id}` | POST | Extract + upscale approved panels | Yes |
| `/api/pipeline/images/{id}` | POST | Generate images directly | Yes |
| `/api/pipeline/images/{id}?scene={n}&index={i}` | POST | Generate single image | **New** (query params) |
| `/api/pipeline/images/{id}?scene={n}&variants=3` | POST | Generate 3 variants | **New** (query params) |
| `/api/assets/{id}/approve` | PATCH | Approve panel/image | Yes |
| `/api/assets/{id}/reject` | PATCH | Reject panel/image | Yes |
| `/api/pipeline/prompts/{id}` | POST | Generate image prompts | Yes |

---

## 3. Approve & Advance Pipeline Stages

### Current State
Single "Approve & Advance" button on info tab. Works but limited.

### New: Per-Tab Advancement

Each tab gets contextual advancement controls based on the pipeline stage.

**Info Tab (idea_logged → approved):**
- "Approve Idea" button advances to `approved` status
- "Reject" button with reason field

**Script Tab (ready_for_scripting → ready_for_voice):**
- "Approve Script → Generate Voice" button appears after all scenes have script text
- Disabled with message if any scene is empty
- Triggers voice generation for all scenes, advances status

**Script Tab (ready_for_voice → ready_for_image_prompts):**
- "All Voices Ready → Generate Prompts" button appears when all scenes have voice
- Advances and triggers prompt generation

**Visuals Tab — Storyboard ON (multiple stages):**
- Stage-aware buttons:
  - `ready_for_storyboards`: "Generate Storyboard Grids" — triggers grid generation
  - `ready_for_storyboard_images`: "Generate Grid Images" — triggers contact sheet generation
  - `ready_for_storyboard_extraction`: "Extract & Upscale Approved → Next Stage" — extracts panels, advances
- Each button validates prerequisites (e.g., enough panels approved)

**Visuals Tab — Storyboard OFF:**
- `ready_for_images`: "Generate All Images" — triggers batch generation
- After generation: "Approve & Advance to Thumbnail" — advances when enough images approved

**Thumbnail Tab (ready_for_thumbnail → ready_to_render):**
- "Approve Thumbnail → Ready to Render" button
- Shows current thumbnail with CTR prediction if available

**General Pattern:**
- Advance button is always amber, positioned top-right of the tab
- Shows the next stage name so user knows what they're advancing to
- Polling indicator while background task runs (spinner + "Generating..." message)
- Success: status updates, tab refreshes automatically
- Failure: error toast with message, retry button

### Backend Requirements

All advancement endpoints already exist:
- `PATCH /api/videos/{id}/advance` — generic advance to next status
- `POST /api/pipeline/{stage}/{id}` — trigger specific stage
- `GET /api/pipeline/task/{id}` — poll background task status

**New:**
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/pipeline/status/{id}` | GET | Current status + next action + prerequisites | Exists, may need enrichment |

---

## 4. Task Polling & Background Generation UI

All generation actions (voice, images, storyboards, extraction) run as background tasks.

### Polling Pattern (Frontend)

```
User clicks "Generate" → POST /api/pipeline/{stage}/{id}
  → Button becomes spinner: "Generating..."
  → Poll GET /api/pipeline/task/{id} every 3 seconds
  → Status: running → show progress message
  → Status: completed → refetch data, show success toast
  → Status: failed → show error message + retry button
  → After 30s with no change → show "Taking longer than expected" message
```

### UI States

| State | Button | Message |
|-------|--------|---------|
| Ready | Amber, enabled | "Generate Voice" / "Generate Grid" etc. |
| Running | Spinner, disabled | "Generating voice for Scene 3..." |
| Complete | Green flash, then reset | Toast: "Voice generated" |
| Failed | Red, retry enabled | "Failed: [error]. Retry?" |
| Polling timeout | Amber warning | "Still processing. Check back shortly." |

---

## 5. Component Architecture

### New Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `SceneEditor` | `components/video-detail/scene-editor.tsx` | Editable scene card with tone, regen, voice |
| `SegmentList` | `components/video-detail/segment-list.tsx` | Collapsible sentence segments with split handles |
| `VoicePlayer` | `components/video-detail/voice-player.tsx` | Mini audio player (play/pause, waveform, redo) |
| `StoryboardViewer` | `components/video-detail/storyboard-viewer.tsx` | Grids side-by-side with magnified panel viewer |
| `PanelMagnifier` | `components/video-detail/panel-magnifier.tsx` | CSS crop/zoom of grid region — NO extraction |
| `ImageSegmentCard` | `components/video-detail/image-segment-card.tsx` | Per-segment image card (storyboard OFF path) |
| `StageAdvancer` | `components/video-detail/stage-advancer.tsx` | Per-tab advancement button with polling |
| `TaskPoller` | `components/video-detail/task-poller.tsx` | Hook/component for polling background tasks |
| `PromptExpander` | `components/video-detail/prompt-expander.tsx` | Collapsible prompt viewer/editor |

### Modified Components

| Component | Changes |
|-----------|---------|
| `script-tab.tsx` | Replace read-only list with `SceneEditor` + `SegmentList` |
| `visuals-tab.tsx` | Add storyboard toggle, split into ON/OFF paths |
| `storyboard-tab.tsx` | **Merge into visuals-tab.tsx** — storyboard is now a mode of the visuals tab, not a separate tab |
| `info-tab.tsx` | Keep existing advance/reject, minor polish |
| `thumbnail-tab.tsx` | Add `StageAdvancer` for ready_to_render |

### Tab Consolidation

The current 6-tab structure has a dedicated "Storyboard" tab that becomes redundant since storyboard review is now a mode of the Visuals tab.

**New tab structure (5 tabs):**
1. Info
2. Script (editing + voice generation)
3. Visuals (storyboard toggle, image generation, panel review — all visual pipeline)
4. Thumbnail
5. Performance

---

## 6. Pipeline Advancement Logic (Branching Flow)

### The Problem

The pipeline has a linear status progression in `status_map.py` (18 stages), but the storyboard toggle creates a branching path. The generic `PATCH /api/videos/{id}/advance` calls `_next_stage()` which always returns the next linear status — this doesn't work for storyboard ON/OFF branching.

### Solution: Per-Tab Buttons Call Specific Stage Endpoints

The per-tab advancement buttons do NOT call the generic `/advance` endpoint. Instead, each button calls the specific pipeline stage endpoint it needs:

| Tab | Button | Calls | Sets Status To |
|-----|--------|-------|---------------|
| Info | "Approve Idea" | `PATCH /advance` | `approved` → `ready_for_scripting` |
| Script | "Approve → Voice" | `POST /pipeline/voice/{id}` | `ready_for_voice` (voice bot handles status) |
| Script | "Voices Ready → Prompts" | `POST /pipeline/prompts/{id}` | `ready_for_image_prompts` |
| Visuals (SB ON) | "Generate Grids" | `POST /pipeline/storyboards/{id}` | `ready_for_storyboards` |
| Visuals (SB ON) | "Generate Grid Images" | `POST /pipeline/storyboard-images/{id}` | `ready_for_storyboard_images` |
| Visuals (SB ON) | "Extract & Upscale" | `POST /pipeline/storyboard-extract/{id}` | `ready_for_images` |
| Visuals (SB OFF) | "Generate Images" | `POST /pipeline/images/{id}` | `ready_for_images` (skips storyboard stages) |
| Thumbnail | "Approve → Render" | `POST /pipeline/render/{id}` | `ready_to_render` |

**Key:** Storyboard OFF skips `ready_for_storyboards` → `ready_for_storyboard_images` → `ready_for_storyboard_extraction` entirely. The "Generate Images" button jumps directly from `ready_for_image_prompts` to `ready_for_images` via the `/pipeline/images/{id}` endpoint.

### PIPELINE_STAGES (UI Progress Dots) vs status_map.py

`PIPELINE_STAGES` in `models.py` is a 10-dot simplified view for progress dots. It does NOT need to include every sub-stage — the dots represent major milestones. The full 18-stage flow in `status_map.py` remains the source of truth for backend routing. No changes needed to either.

### Single-Scene Regeneration (Bypass Status Gate)

When a user edits one scene's script and wants to regenerate just that voice, the video may already be past `ready_for_voice` (e.g., at `ready_for_images`). Single-scene operations use **targeted endpoints** that do NOT enforce the linear status gate:

- `POST /pipeline/voice/{id}?scene={n}` — regenerates voice for one scene regardless of current video status
- `POST /pipeline/images/{id}?scene={n}&index={i}` — regenerates one image regardless of status

These targeted endpoints log to `bot_activity` but do NOT change the video's overall status. They are "edit-in-place" operations, not pipeline advancement.

---

## 7. Database Changes

### New Columns

**scripts table:**
- `tone` (TEXT, default 'serious') — per-scene tone setting
- Note: `voice_status` already exists in schema — no migration needed for it

### Segments Data Model

Segments are NOT a new table. They are computed from the `assets` table:
- Each row in `assets` where `video_id` matches and `scene` matches has a `sentence_text` and `image_index`
- `GET /api/videos/{id}/scenes/{scene}/segments` queries assets for that scene, returns ordered by `image_index`
- `PUT /api/videos/{id}/scenes/{scene}/segments` accepts an array of `{image_index: number, sentence_text: string}` and updates the corresponding asset rows
- Adjusting split points = reassigning which words from the scene text go to which asset's `sentence_text`

### Storyboard Mode Toggle

`PATCH /api/videos/{id}/storyboard-mode` writes `storyboard_on_off` to ALL script rows for that video (bulk update).

**Mid-pipeline toggle behavior:**
- Toggling OFF after grids are generated: grids are preserved but skipped. Pipeline advances to direct image generation.
- Toggling ON after images are generated: no effect on existing images. Storyboard workflow starts fresh for any scenes that don't have grids yet.
- Toggle does NOT change video status — it only affects which "next step" buttons appear in the UI.

### Partial Voice Failure Handling

Voice generation per-scene can partially fail. The UI handles this:
- Each scene card shows its own voice status: ready (green), failed (red), generating (spinner)
- The advancement button shows progress: "18/20 voices ready" with warning icon
- Individual "Retry" button on failed scenes
- Advance button disabled until all scenes have voice (or user manually skips with "Advance Anyway" secondary action)

### New API Endpoints Summary

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `PATCH /api/videos/{id}/scenes/{scene}/text` | PATCH | Update single scene text (optimistic UI) |
| `PATCH /api/videos/{id}/scenes/{scene}/tone` | PATCH | Update tone setting |
| `POST /api/pipeline/voice/{id}?scene={n}` | POST | Voice for single scene (bypasses status gate) |
| `GET /api/videos/{id}/scenes/{scene}/segments` | GET | Get segments from assets table |
| `PUT /api/videos/{id}/scenes/{scene}/segments` | PUT | Update segment text splits |
| `PATCH /api/videos/{id}/storyboard-mode` | PATCH | Toggle storyboard on/off (all scenes) |
| `POST /api/pipeline/images/{id}?scene={n}&index={i}` | POST | Single image gen (bypasses status gate) |
| `POST /api/pipeline/images/{id}?scene={n}&variants=3` | POST | 3 variant generation |

---

## 8. Key Design Decisions

1. **Magnified viewer, not extraction.** Clicking a storyboard panel crops/zooms into that region of the grid image using CSS. No API calls, no credits. Extraction + upscaling only happens when the user explicitly advances to the next pipeline stage.

2. **VO player on visual cards.** The core review workflow is listening to narration while scanning panels. The audio player lives on the Visuals tab scene cards, not just the Script tab.

3. **Collapsible by default.** Sentence segments, prompts, and panel details are all collapsed. Expand on demand. Keeps the view clean for scanning.

4. **Storyboard as a mode, not a tab.** Merged into Visuals tab with a toggle. Reduces tab count from 6 to 5, puts the entire visual pipeline in one place.

5. **Grids side by side.** 1-5 storyboard grids per scene shown horizontally (within the existing 3-grid-max schema: `storyboard_1_url`, `storyboard_2_url`, `storyboard_3_url`). Review the full visual flow at a glance. Arrow keys cross grid boundaries. If a future schema supports more grids, the UI scales automatically.

6. **Per-tab buttons call specific stage endpoints, not generic advance.** This solves the branching storyboard ON/OFF flow. Each button knows exactly which pipeline endpoint to trigger. The generic `/advance` endpoint is only used for simple linear transitions (e.g., idea_logged → approved).

7. **Targeted regeneration bypasses status gates.** Single-scene voice regen and single-image regen work regardless of the video's current pipeline status. They are edit-in-place operations that don't change overall video status.

8. **Background task polling.** All generation is async. Frontend polls every 3s and shows progress. Success auto-refreshes data. Failure shows retry.

9. **Optimistic UI for text edits.** Scene text editing (auto-save on blur) reflects immediately in the UI before the PATCH roundtrip completes. Segment splits and tone changes also use optimistic updates. Generation actions (voice, images) do NOT use optimistic UI — they show explicit loading states.

10. **Keyboard shortcuts only activate when storyboard viewer is focused.** Arrow keys, Space, A, R shortcuts require focus on the storyboard component to avoid conflicting with browser defaults (Space = scroll, arrows = scroll).

---

## 9. Cost Impact

No new API costs for the review workflow (magnified viewer is CSS-only). Generation costs are the same as CLI pipeline:

| Action | Cost | Trigger |
|--------|------|---------|
| Voice per scene | ~$0.15-0.30 | "Generate Voice" button |
| Image prompts | ~$0.05 (Claude) | Auto on advance |
| Storyboard grid | ~$0.075/grid | "Generate Grid" per grid |
| Regen grid | ~$0.075/grid | "Regen" button on grid (regenerates full 3×3, not individual panel) |
| Image (direct) | $0.025 | "Generate" per segment |
| 3 Variants | $0.075 | "3 Variants" button |
| Extract + upscale | $0.025/panel | "Advance" button (batch, only on explicit advancement) |

**Note:** "Regen Panel" in the magnified viewer regenerates the entire grid containing that panel ($0.075), not just the individual panel. This is a limitation of the contact sheet generation model. Cost is always shown next to generation buttons so user knows before clicking.
