# Camera Movement Engine — Grand Plan

**Status: Phases 1-4 BUILT + verified locally (2026-07-06). NOT yet deployed to the VPS —
deploy via `se deploy` needs Ryan's go, then prove on a real video build.**
**Decisions locked with Ryan:** earn-the-move discipline / rules + Claude tie-break /
own catalog seeded by aicameramovements.com / engine first, UI later.

## The goal

StoryEngine auto-picks a camera move per shot **before the image is drawn**, sets the
image composition up so the move can land, then feeds the matching motion phrase into
the animation prompt. A camera move is a contract between two prompts:

- A dolly-in only reads as depth if the image has foreground/midground/background layers.
- An orbit needs a hero subject with space around it.
- A pass-through needs a foreground portal (door, window, gap).
- A tilt-up reveal needs vertical content worth revealing.
- A rack focus needs two subjects at different depths.

Today the camera decision happens at animation time on an already-drawn, motion-blind
image. That's the root problem this engine fixes.

## Where it lives

The product pipeline is `skills/video-pipeline/` (the backend sys.path-injects it in
`backend/pipeline_executor.py:23-35`). So the engine lives there and is automatically
inside the deployed product:

- `image_prompts/engine/camera_moves.py` — NEW: the catalog (~40 moves, 7 categories)
- `image_prompts/engine/camera_selector.py` — NEW: the auto-selector
- `image_prompts/run.py` — WIRE: select move per concept, inject image_setup, persist
- `video_motion/run_scripts.py` — WIRE: read planned move, honor it in motion prompt
- `shared/clients/anthropic_client.py` — WIRE: `generate_video_prompt(planned_camera=...)`

## What already exists (keep, don't break)

- `CAMERA_MOVEMENTS` 8-key dict + `detect_camera_movement()` in
  `image_prompts/engine/prompt_builder.py:1193` — used for rotation history. KEEP.
  Every catalog move maps to one of these legacy keys and its motion_prompt contains
  a legacy-detectable keyword, so detection/rotation keep working unchanged.
- Earn-the-move gate: `classify_camera_purpose()` (REVEAL/SCALE/ISOLATION/STATIC) in
  `image_prompts/animation_prompt_engine.py:243`. KEEP as the gate; selector extends
  it with two more earned cases (scene-opening establishing shot, final-shot payoff).
- `assets.camera_movement` column (schema.sql:338) + `ImageFields.CAMERA_MOVEMENT`
  ("Camera Movement") + supabase_adapter mapping. Already there; now actually used.
- `validate_video_prompt()` camera-repeat + unjustified-camera checks. KEEP.

## Phase 1 — Catalog (`camera_moves.py`)

Dataclass `CameraMove`: id, name, category, motion_prompt, image_setup, best_for
(purposes served), subject_fit, pace, intensity (1-5), model_support, avoid_when,
legacy_key. ~40 moves across: dolly/track, zoom/lens, drone/crane, pan/tilt,
physical, human-camera, specials. Seeded by aicameramovements.com's 46, pruned/tuned
to what grok-imagine / seedance / veo / kling execute cleanly.

## Phase 2 — Selector (`camera_selector.py`)

`select_camera_move(ctx)` — deterministic scoring:
1. Gate first: purpose from sentence + position bonuses (scene-open establish,
   scene-final payoff). STATIC → return None (most shots).
2. Score catalog: purpose fit, subject fit (character/environment/data), composition
   fit (wide/medium/closeup), pace vs narrative intensity, model support.
3. Anti-repeat: exclude last-used legacy_key (consecutive), penalize recent move ids.
4. Tie-break: if top 2 within threshold and an anthropic client is provided, one
   cached Haiku call picks; otherwise deterministic first.

## Phase 3 — Two-way wiring

Image side (`image_prompts/run.py`): after concept expansion, select move per concept
(tracking planned-move history across the video), append `move.image_setup` to the
visual description before `build_prompt()`, persist move id to Camera Movement via a
duck-typed adapter call (safe on both supabase_adapter and legacy AirtableClient).

Motion side (`video_motion/run_scripts.py`): read Camera Movement off the record,
look up the catalog move, pass its `motion_prompt` into
`generate_video_prompt(planned_camera=...)` which uses it as the `{camera_motion}`
slot value. No planned move stored (old videos, storyboard-extract assets, chat
assets) → exact current behavior. Fully backward compatible.

## Phase 4 — Verification (text-only on desktop threads)

- Import-load + syntax checks on all touched modules.
- Synthetic-shot harness: run the selector over a scripted variety of shots, print
  chosen move + injected image_setup + motion phrase, eyeball the logic. Free.
- Real paid clip proof: ASK FIRST (~$1-2), or ride the next real video build.

## Out of scope this pass (later)

- UI: per-shot move override picker on Scenes page (engine stores the move; UI reads
  the same column when we build it).
- Storyboard/coverage grid path planning (falls back gracefully today).
- Per-tenant camera style preferences (catalog supports it via filtering later).
