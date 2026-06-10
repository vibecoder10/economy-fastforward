# Spec: Creator Control Run — Stop, Character Design, Storyboard Gate
*Defined with Ryan 2026-06-10. Decisions confirmed: finals = extract approved panels;
characters = AI-generate + edit/upload with review; per-video + save-to-project reuse;
storyboard gate mandatory for all videos.*

## Why
Three problems from the first Model-A-Video production test:
1. No way to stop generation after hitting go (money keeps burning).
2. No character consistency across images (same character looks different every scene).
3. Images generate straight from prompts — no cheap visual review loop before the
   expensive batch. Storyboards must become the mandatory gate.

## Ground truth (audited 2026-06-10, file:line evidence in session notes)
- Storyboard system EXISTS but optional (`scripts.storyboard_on_off`, per-scene Gen
  Prompts/Gen Grids in StoryboardVisualsTab, statuses ready_for_storyboards →
  storyboard_images → storyboard_extraction). Grids: 9-panel contact sheets,
  Nano Banana Pro, $0.075/grid. Extraction writes panels INTO assets.image_url
  (generation_method='storyboard_extract') — panels can BE the finals.
- Character primitives EXIST: videos.character_reference_url (single URL, consumed
  by storyboard bot via nano-banana image_input), Story Bible exact-costume text
  consistency, style-character generation UI in /profile, upload infra
  (storyboard-grid-upload + storage.upload_bytes), projects.character_references JSONB.
- Cancel: nothing for pipeline stages. Proven in-repo pattern: niche.py /scrape/cancel
  (flag checked between loop iterations). background_tasks CHECK already includes
  'cancelled' (never written). Generation loops have zero cancel checks; arq abort unused.

## Phase 1 — Stop generation (ship first; safety)
- `POST /api/pipeline/cancel/{video_id}`: set running background_tasks row →
  status='cancelled' + in-memory flag keyed (tenant_id, video_id).
- Cooperative checks between paid items (cross-process-safe via DB read, in-memory
  fast path): images/run.py scene + retry loops, video_motion/run_generate.py before
  each clip, storyboard grid loop. Executor injects a `should_cancel()` callable.
- Semantics (default, veto if wrong): finish the in-flight item, keep all completed
  (paid) assets, task ends as 'cancelled' with a friendly message, stage status
  unchanged — clicking the stage again resumes (existing resume logic fills gaps only).
- Frontend: red Stop button beside every running-progress display (production tabs
  using use-task-poller) + confirm dialog. New api.ts cancelPipelineTask().

## Phase 2 — Character Design step (per video)
- New table `video_characters` (tenant_id, video_id, name, costume/description,
  reference_url, status draft|approved, sort). Keep character_reference_url as the
  "primary" pointer for backward compat with the storyboard bot.
- Flow: after script completes → video enters 'ready_for_character_design'.
  Backend generates the Story Bible at this point if missing (modeled-script path
  has none), then one portrait per bible character via nano-banana-2 in the video's
  visual style (~$0.025/character, e.g. ESL family of 4 ≈ $0.10).
- UI: "Characters" section on the video page — portrait card per character with
  Regenerate, Upload replacement (reuse upload_bytes path), edit description,
  and Approve all → unlocks storyboards. Very visible: this is THE character
  design moment per video.
- "Save to project": copies {name, reference_url, costume} into
  projects.character_references (column already exists). New videos offer
  "use saved characters" so a series keeps the same cast.
- Wiring: storyboard grids get ALL approved refs (image_input accepts a list);
  scene-image regeneration path passes refs (generate_scene_image already has the
  param); thumbnail gets the primary character ref (today it gets none).
- Videos whose bible has no characters (pure data/doc videos) auto-skip this step.

## Phase 3 — Mandatory storyboard gate
- storyboard_on_off defaults On for ALL new videos; the images stage refuses to run
  until story is locked.
- New explicit lock: `POST /api/videos/{id}/lock-story` → sets videos.story_locked_at.
  UI shows a "Lock story & create images" moment with cost preview.
- Review loop before lock: grids render per scene; redo per BOARD (per-grid/beat,
  not just per-scene — new ?beat= param through storyboard run_images), with a
  running spend counter ($0.075 per redo). No hard cap on redos (default; veto if
  you want a soft confirm after N).
- After lock: extraction crops approved panels into assets (existing path) +
  AI upscale pass for render resolution. Honest cost note: the upscale pass is
  per-panel (~$0.025 ea ≈ $1.85 for 74) — the gate's savings are in ITERATION
  (you redo $0.075 boards, not $1.85 batches) and fidelity (finals = approved
  boards), not in the final pass itself.
- Pipeline stages list/UI updated so Storyboard appears as a first-class mandatory
  stage with its own dot.

## Defaults Ryan can veto
1. Stop = graceful (finish current item, keep paid work, resumable).
2. No cap on board redos; show running cost instead.
3. Character step auto-skips for character-less videos.
4. Stop button appears on every tab with a running task (not a single global bar).

## Order & sizing
Phase 1 (S) → Phase 2 (M) → Phase 3 (M). Each phase ships + verifies independently
(functional tests + live click-test on the bird video f32ed182 / a fresh modeled run).
