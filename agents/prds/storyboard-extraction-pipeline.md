# PRD: Storyboard Extraction Pipeline + Video Clips Wiring

**Video:** "Why America Can't Stop $50,000 Drones (But Spends $4M Per Shot)"
**Goal:** Complete the storyboard → extraction → video clips flow end-to-end

---

## Bug Fix (do first)

### BUG-1: Pipeline spinner spins forever
The loading spinner in the top header bar (next to "Run Next Step" / "Skip Stage") never stops spinning. It should stop after the pipeline stage completes or show idle state when nothing is running.

**Files:** `storyengine/frontend/src/components/production/` — check the pipeline header component, likely in `page.tsx` or a shared stepper component. The spinner is tied to `useTaskPoller` — check if the poll never resolves or if the status never clears.

---

## Feature 1: Clean up Storyboard Mode buttons

**Problem:** When storyboard mode is ON, the regular "generate images from prompts" buttons should NOT appear. The only generation flow in storyboard mode is:
1. Generate Image Prompts
2. Generate Storyboard Prompts  
3. Generate Storyboard Grids

The per-segment "Regen" and "Variants" buttons on individual image cards should be hidden in storyboard mode — those are for direct image generation, not storyboard flow.

**Files:**
- `storyengine/frontend/src/components/production/StoryboardVisualsTab.tsx`
- Look for the "Regen" and "Variants" buttons on segment cards (~line 500+)
- Conditionally hide when `storyboardMode === true`

---

## Feature 2: Storyboard Extraction

**What:** After storyboard grids are generated and approved, extract individual panels from the 3x3 grids, upscale them, and store them as the scene's images.

**Backend exists:** `POST /api/pipeline/storyboard-extract/{video_id}` endpoint already exists in `pipeline.py:532`. It calls `run_storyboard_extract()` from `skills/video-pipeline/storyboard/run_extract.py` which:
- Reads storyboard grid URLs from scripts table
- Extracts panels at X,Y coordinates in correct order
- Upscales each panel
- Writes extracted images to assets table with `image_url`

**Frontend needed:** Add an "Extract Panels" button that appears after grids are generated (storyboard_status = "grids_generated"). Place it prominently — this is the next step after grids.

**Files:**
- `storyengine/frontend/src/components/production/StoryboardVisualsTab.tsx` — add Extract button
- `storyengine/frontend/src/lib/api.ts` — add `extractStoryboardPanels(videoId)` if not exists
- Backend endpoint already exists, just needs frontend wiring

---

## Feature 3: Filmstrip View

**What:** After extraction, show all extracted images in a horizontal scrollable filmstrip above ACT 1. Think of it like a sideways film strip — thumbnail-sized images in scene order, scrollable left-right.

**Design:**
- Full-width horizontal scroll container
- Each image is ~120px tall, aspect ratio preserved
- Scene labels (S-01.1, S-01.2, etc.) below each image
- Appears only when extracted images exist
- Clicking an image scrolls to that scene below

**Placement:** Above the "ACT 1" heading in StoryboardVisualsTab, after extraction completes.

**Files:**
- `storyengine/frontend/src/components/production/StoryboardVisualsTab.tsx` — add filmstrip section
- Data source: assets with `image_url` populated, ordered by scene + segment index

---

## Feature 4: Video Clips Page — Wire Extracted Images

**What:** On the Video Clips tab, the clip cards currently show images from `image_url` on assets. After storyboard extraction, these should already be populated. Verify:
- Extracted images appear in the clip cards (replacing empty placeholders)
- The scene ordering is correct (S-01.1, S-01.2, etc.)

**Skip button:** The Video Clips step is optional (expensive at $0.30/clip). Add a visible "Skip Video Clips" button or make the existing "Skip Stage" button work for this step. The user should be able to go directly from extraction → thumbnail → render.

**Files:**
- `storyengine/frontend/src/components/production/VideoClipsTab.tsx`
- Check that clip cards read from the same `image_url` that extraction writes to
- Add skip affordance if not present

---

## Feature 5: Move Action Buttons

**What:** The "Generate Video Prompts" and "Generate All Clips" buttons are currently inside the Video Clips tab content area. Move them up near step 4 (Video Clips) in the pipeline stepper, or create a clear action bar at the top of the tab — similar to how "Run Next Step" works at the top.

**Files:**
- `storyengine/frontend/src/components/production/VideoClipsTab.tsx`
- Position action buttons at the top of the tab, not buried in the content

---

## Feature 6: Test Video Generation (manual verification)

After features 1-5 are built:
1. Run "Generate Video Prompts" on the test video to verify prompts are written correctly
2. Review the generated prompts — are they describing motion/camera for each scene?
3. Generate exactly 1 video clip (first hero shot only) to verify the pipeline works
4. **STOP after generating 1 clip** — do not generate all clips ($34.50 estimated cost)

---

## Acceptance Criteria

- [ ] Pipeline spinner stops when no stage is running
- [ ] Storyboard mode hides per-segment Regen/Variants buttons
- [ ] "Extract Panels" button appears after grids are generated
- [ ] Extraction runs and populates assets with upscaled images
- [ ] Filmstrip shows extracted images in horizontal scroll above ACT 1
- [ ] Video Clips tab shows extracted images in clip cards
- [ ] Video Clips step is skippable
- [ ] Video prompts generate correctly for the test video
- [ ] 1 test video clip generates successfully
- [ ] TypeScript compiles: `cd storyengine/frontend && npx tsc --noEmit`

## Task Breakdown

| # | Task | Role | Depends On |
|---|------|------|------------|
| T1 | Fix pipeline spinner infinite loading | frontend | — |
| T2 | Hide Regen/Variants buttons in storyboard mode | frontend | — |
| T3 | Wire "Extract Panels" button to existing backend endpoint | frontend | — |
| T4 | Build horizontal filmstrip component for extracted images | frontend | T3 |
| T5 | Verify Video Clips tab reads extracted images correctly | frontend | T3 |
| T6 | Add skip affordance for Video Clips step | frontend | — |
| T7 | Move Video Clips action buttons to top of tab | frontend | — |
| T8 | Test video prompt generation on sample video | qa | T3, T5 |
| T9 | Generate 1 test video clip and verify | qa | T8 |
