# DVSU Anton Final Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the DVSU StoryEngine output ready for a 10-video test batch by locking Anton's original music and mix, keeping a composition-aware rotating info card visible throughout every unit, and replacing Never-Built schematic imagery with realistic reconstructions.

**Architecture:** Keep DVSU on the existing `static_docu` path: one narration segment per unit, three generated views, Remotion Ken Burns motion, and one uninterrupted voice track. Add a generic channel-level fixed-music contract, carry one overlay payload per rendered view, and replace the current Never-Built blueprint branch with a design-reference-grounded photoreal reconstruction branch. Other StoryEngine production styles retain their current behavior.

**Tech Stack:** Python 3.11 / FastAPI backend, PostgreSQL via the existing database helpers, TypeScript/React/Remotion 4, pytest, ffmpeg/ffprobe.

---

## Current state and boundaries

- Canonical repository: `/Users/ryanayler/economy-fastforward`.
- DVSU renderer: `storyengine/backend/render_static.py` plus `remotion-video/src/Scene.tsx`.
- DVSU image generation: `storyengine/backend/static_docu.py` and `storyengine/backend/static_docu_contract.py`.
- Supplied music asset: `light_music-lonely-piano-189659.mp3`, Google Drive file ID `1pzOAdbRIchghJsIAEQalBH8UF8zZVjzy`, about 22 minutes long.
- Calibration reference: the published DVSU video **Every US Strategic Bomber Ever Built**, chosen because it matches the current test video's subject and narrator; Anton can nominate a different existing channel reference before calibration.
- Current reviewed artifact: `/Users/ryanayler/Desktop/Projects/DvsU/every-us-strategic-bomber-v2.mp4`, 21:21 long.
- Preserve the approved behavior Anton praised: three complementary angles, roughly 24-second image rotation, smooth alternating push/pull Ken Burns motion, and the existing narrator timing.
- Do not deploy, generate paid images, upload assets, or publish during the code pass. Music ingestion/calibration is a separate post-code asset-configuration step. The single-unit paid reconstruction proof and the 10-video generation batch each require their own fresh quote and Ryan approval. Publishing remains a third, separate explicit approval.
- Preserve unrelated dirty files already in the repository.

## Acceptance contract

1. DVSU uses only Anton's supplied music file as one continuous full-video bed. It does not mood-switch, restart at act boundaries, or skip the first 30 seconds.
2. The final gain is set only after an A/B listening comparison with the published reference. The configured value is channel-level, not a global change for every StoryEngine customer.
3. The info card is visible for the entire unit and changes with each image:
   - View 1: full machine name plus operator/service years.
   - View 2: one sourced key specification.
   - View 3: an exact short closing line from that unit's script.
4. Each view carries `bottom_left` or `bottom_right`, calculated from the rendered image's composition. Existing assets are analyzed when staged for rendering, so they receive composition-aware placement without paid regeneration. Alternation is allowed only as the deterministic tie-break when both corners have equal occupancy.
5. Never-Built and paper-project units output three photorealistic reconstruction views. Schematics or concept art may be used as generation references, but never appear in the final video.
6. A Never-Built unit still says `Design study — never built` in its identifying metadata. Realistic reconstruction must not be presented internally as a historical photograph.
7. A missing or unverified design reference blocks that one unit. It never falls back to an ungrounded guessed design.
8. Every unit in the 10-video batch is 3/3 views before the video is called ready. The generic static-documentary minimum-two recovery behavior does not authorize a DVSU batch release with only two views.

## File map

**Create**

- `storyengine/backend/channel_audio.py` — parse and load the generic channel-level fixed music contract.
- `storyengine/backend/overlay_position.py` — measure subject occupancy in the two card regions on a staged image.
- `storyengine/backend/migrations/155_static_reference_kind.sql` — distinguish historical-photo and design-reference cache rows.
- `storyengine/backend/tests/test_channel_audio.py` — channel music configuration tests.
- `storyengine/backend/tests/test_overlay_position.py` — deterministic composition-position tests with synthetic images.
- `storyengine/backend/tests/functional/test_static_docu_never_built_reconstruction.py` — realistic Never-Built generation contract.

**Modify**

- `storyengine/backend/render_static.py` — stage the fixed track, emit a full-video music bed, and build per-view overlay payloads.
- `storyengine/backend/static_docu.py` — preserve verified-photo precedence, acquire design references, and generate photorealistic Never-Built reconstructions.
- `storyengine/backend/static_docu_contract.py` — give Never-Built units the same three camera roles as ordinary DVSU units.
- `storyengine/schema.sql` — mirror migration 155 for clean installs.
- `storyengine/backend/pipeline_executor.py` — expose design-reference readiness as a verified reference in the existing roster dashboard response.
- `storyengine/backend/tests/test_render_static_anton_feedback.py` — encode Anton's new music and rotating-overlay requirements.
- `storyengine/backend/tests/functional/test_never_built_classification.py` — keep classification conservative while expecting a design-reference lookup instead of a terminal blueprint result.
- `storyengine/backend/tests/functional/test_static_docu_roster_reference_layer.py` — assert the new design-reference cache route.
- `remotion-video/src/renderConfig.ts` — type full-video music beds and per-view overlays.
- `remotion-video/src/components/MusicBed.tsx` — render one uninterrupted fixed bed for configured channels while preserving legacy per-act beds.
- `remotion-video/src/Scene.tsx` — render a persistent per-view info card and crossfade its content/position at image changes.
- `remotion-video/test-fixtures/anton-feedback-props.json` — fixture with identity, spec, quote, and left/right placement examples.

**Remove after replacement**

- `storyengine/backend/tests/functional/test_static_docu_never_built_blueprint.py` — superseded by the reconstruction test file; do not retain contradictory blueprint expectations.

---

### Task 1: Lock the DVSU music asset and calibrated full-video mix

**Files:**

- Create: `storyengine/backend/channel_audio.py`
- Create: `storyengine/backend/tests/test_channel_audio.py`
- Modify: `storyengine/backend/render_static.py`
- Modify: `storyengine/backend/tests/test_render_static_anton_feedback.py`
- Modify: `remotion-video/src/renderConfig.ts`
- Modify: `remotion-video/src/components/MusicBed.tsx`

- [ ] **Step 1: Write the failing channel-audio tests**

Cover these cases:

```python
async def test_fixed_music_config_is_read_from_channel_identity():
    # channel_identity.music_bed -> validated FixedMusicBedConfig
    ...


async def test_missing_fixed_music_config_preserves_legacy_selection():
    # no music_bed block -> None, so non-DVSU rendering is unchanged
    ...


def test_fixed_music_rejects_missing_asset_url_or_invalid_gain():
    # malformed data fails closed to None, never a half-configured render
    ...
```

Use this stored shape, generically named so it is not hardcoded to DVSU:

```json
{
  "music_bed": {
    "mode": "fixed_full_video",
    "asset_url": "https://storage.test/dvsu-channel/channel-assets/light_music-lonely-piano-189659.mp3",
    "file_name": "light_music-lonely-piano-189659.mp3",
    "volume": 0.018,
    "trim_before_seconds": 0,
    "loop": true
  }
}
```

The URL and volume above are test-fixture values only. Do not write a production `music_bed` block until Step 8 returns the real durable URL and listening-calibrated numeric volume.

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
cd storyengine/backend
./venv/bin/python -m pytest tests/test_channel_audio.py tests/test_render_static_anton_feedback.py -q
```

Expected: failures because `channel_audio.py` and the fixed full-video bed contract do not exist.

- [ ] **Step 3: Implement the generic channel music loader**

In `channel_audio.py`, add one validated immutable object:

```python
@dataclass(frozen=True)
class FixedMusicBedConfig:
    asset_url: str
    file_name: str
    volume: float
    trim_before_seconds: float = 0.0
    loop: bool = True
```

Load `channel_profiles.channel_identity`, parse JSON safely, accept only `mode == "fixed_full_video"`, require a non-empty durable asset URL and filename, and clamp nothing silently. Reject volume outside `0.0..1.0` so a bad profile cannot overpower narration.

- [ ] **Step 4: Add the failing render-config tests**

Extend `test_render_static_anton_feedback.py` to assert:

```python
assert beds == [{
    "scope": "video",
    "file": "light_music-lonely-piano-189659.mp3",
    "volume": calibrated_volume,
    "trim_before_seconds": 0.0,
    "loop": True,
}]
```

Also assert that the fixed path never calls the mood classifier and that the old per-act selector remains the fallback when the channel has no fixed music setting.

- [ ] **Step 5: Stage the fixed track once per render**

In `render_static._select_music_beds`:

1. Load `FixedMusicBedConfig` first.
2. Download its durable storage URL into the render's isolated `public/music` folder.
3. Normalize it to 48 kHz stereo exactly once, matching narration.
4. Return one `scope: "video"` bed covering the full render.
5. Skip mood classification, per-act selection, and the current `volume: 0.03` default for that channel.
6. Fall through to the existing per-act behavior for every channel without the fixed contract.

- [ ] **Step 6: Teach Remotion the full-video music scope**

Replace the single required-field interface with a discriminated union so the existing act renderer keeps its required `act` and `mood` values while the fixed full-video bed cannot pretend to be an act bed:

```ts
export interface ActMusicBed {
  scope?: "act";
  act: number;
  file: string;
  mood: string;
  volume: number;
}

export interface FullVideoMusicBed {
  scope: "video";
  file: string;
  volume: number;
  trim_before_seconds: number;
  loop: boolean;
}

export type MusicBed = ActMusicBed | FullVideoMusicBed;
```

Branch on `scope === "video"` before requiring act boundaries. Render one `Audio` sequence from frame zero through the total video duration, honor the exact configured volume, use the configured `trim_before_seconds` (zero for DVSU), and loop only if the video exceeds the track. Narrow all remaining beds to `ActMusicBed` before reading `act` or `mood`; keep the current per-act behavior byte-for-byte for legacy beds.

- [ ] **Step 7: Run focused tests and typecheck**

Run:

```bash
cd storyengine/backend
./venv/bin/python -m pytest tests/test_channel_audio.py tests/test_render_static_anton_feedback.py -q
cd ../../remotion-video
npm run typecheck
```

Expected: focused tests pass and TypeScript reports no errors.

- [ ] **Step 8: Post-code asset setup — ingest and calibrate the supplied track**

1. Download `light_music-lonely-piano-189659.mp3` from the supplied Drive folder.
2. After Ryan authorizes this asset-configuration step, upload it once with `storage.upload_bytes(data, "dvsu-channel/channel-assets/light_music-lonely-piano-189659.mp3", "audio/mpeg", tenant_id)`. This resolves to the DVSU tenant's StoryEngine storage and returns the durable URL; do not commit the 42 MB binary to Git.
3. Put that returned URL—not the fixture URL—into `channel_profiles.channel_identity.music_bed.asset_url`.
4. Compare a 60–90 second voice-plus-music passage against the published **Every US Strategic Bomber Ever Built** reference using the same listening volume and headphones/speakers.
5. Adjust only the channel profile's `music_bed.volume` until the voice/music relationship matches by ear.
6. Confirm speech remains intelligible at the loudest and quietest narration passages.
7. Save the resulting numeric value in the DVSU channel profile and leave it unchanged across the 10-video batch.

- [ ] **Step 9: Commit the music contract**

```bash
git add storyengine/backend/channel_audio.py \
  storyengine/backend/render_static.py \
  storyengine/backend/tests/test_channel_audio.py \
  storyengine/backend/tests/test_render_static_anton_feedback.py \
  remotion-video/src/renderConfig.ts \
  remotion-video/src/components/MusicBed.tsx
git commit -m "feat(dvsu): lock channel music bed and mix"
```

---

### Task 2: Keep the info card visible and rotate grounded content per image

**Files:**

- Create: `storyengine/backend/overlay_position.py`
- Create: `storyengine/backend/tests/test_overlay_position.py`
- Modify: `storyengine/backend/render_static.py`
- Modify: `storyengine/backend/tests/test_render_static_anton_feedback.py`
- Modify: `remotion-video/src/renderConfig.ts`
- Modify: `remotion-video/src/Scene.tsx`
- Modify: `remotion-video/test-fixtures/anton-feedback-props.json`

- [ ] **Step 1: Write the failing backend overlay tests**

Replace the old expectation that views 2 and 3 have empty caption data. Assert this render payload instead:

```python
assert scenes[0]["overlay"] == {
    "kind": "identity",
    "title": "B-52 Stratofortress",
    "body": "USAF • 1955–present",
    "position": "bottom_left",
}
assert scenes[1]["overlay"] == {
    "kind": "spec",
    "title": "KEY SPEC",
    "body": "Wingspan 185 ft",
    "position": "bottom_right",
}
assert scenes[2]["overlay"] == {
    "kind": "script",
    "title": "B-52 Stratofortress",
    "body": "<exact closing punch from scene_text>",
    "position": "bottom_left",
}
```

Add tests for:

- exact script text only, never a paraphrase;
- the last two short sentences being kept together when they form a DVSU antithesis and fit the card;
- a single last sentence when two would exceed the card limit;
- the per-view overlay using the position calculated from its locally staged image;
- no overlay payload when `STATIC_DRAW_CAPTIONS=0` is explicitly set for a legacy render.

- [ ] **Step 2: Run the focused render test and verify failure**

```bash
cd storyengine/backend
./venv/bin/python -m pytest tests/test_render_static_anton_feedback.py -q
```

Expected: failures because views 2 and 3 still carry empty caption fields and there is no overlay object.

- [ ] **Step 3: Build deterministic grounded overlay content**

In `render_static.py`, add pure helpers:

```python
def _closing_script_line(scene_text: str, max_chars: int = 150) -> str:
    """Return the exact final DVSU punch: last two short sentences when they
    fit, otherwise the final sentence. Never summarize or call an LLM."""


def _overlay_for_view(local_index: int, caption: dict, scene_text: str) -> dict:
    """Map view 1 -> identity, view 2 -> sourced spec, view 3 -> script line."""
```

Use `strip_scene_stage_headers` before extracting the script line. Use only `caption.specs[0]` for the key spec. If a field is absent, fall back to another already-grounded caption/script value; do not invent text.

- [ ] **Step 4: Write failing local composition-position tests**

Create synthetic 16:9 images with a light studio background and a dark aircraft-shaped foreground. Tests must prove:

- a subject occupying the lower-left card rectangle selects `bottom_right`;
- a subject occupying the lower-right card rectangle selects `bottom_left`;
- the calculation uses the same normalized card rectangles as Remotion's 76 px side and 68 px bottom margins;
- an exact occupancy tie alternates by view index so the decision is deterministic;
- a corrupt or unreadable image fails render preparation with the image path in the error instead of silently choosing a corner.

- [ ] **Step 5: Calculate the safe corner from every staged render image**

In `overlay_position.py`, add a pure `choose_overlay_position(image_path, view_index)` helper. Resize to the render frame, apply Pillow's edge filter, and count above-threshold edge pixels inside the exact lower-left and lower-right card rectangles. Choose the rectangle with fewer foreground edges; use view-index alternation only when the counts tie.

In `render_static.render_static_video`, call the helper immediately after each image is downloaded into `public_dir` and before `_build_render_config`. Merge the result into that view's in-memory caption JSON as `overlay_position`. This gives new and already-generated assets composition-aware placement on every render without another provider call, paid image regeneration, or database backfill. `_overlay_for_view` must require this value for new static renders; it must not substitute a blind left/right pattern after analysis failure.

- [ ] **Step 6: Type the per-view overlay contract in Remotion**

Add:

```ts
export interface DocumentaryOverlay {
  kind: "identity" | "spec" | "script";
  title: string;
  body: string;
  position: "bottom_left" | "bottom_right";
}
```

Attach `overlay?: DocumentaryOverlay` to each `RenderScene`. Retain the legacy caption fields temporarily only for old fixture compatibility; new static renders use `overlay`.

- [ ] **Step 7: Replace the 6.5-second title card with a persistent per-view card**

In `Scene.tsx`:

1. Remove the scene-level `titleScene` lookup and the hardcoded 6.5-second exit.
2. Render `DocumentaryInfoCard` inside each image `Sequence` using that view's overlay.
3. Fade/crossfade only at the existing image boundary; never leave a blank interval.
4. Keep the card fixed on screen while the image moves under Ken Burns.
5. Use `left: 76` for `bottom_left`, `right: 76` for `bottom_right`, and the same bottom safe margin/card styling in both positions.
6. Keep the card readable but constrain the script line to the tested maximum so it never becomes a paragraph block.

- [ ] **Step 8: Run the focused checks**

```bash
cd storyengine/backend
./venv/bin/python -m pytest \
  tests/test_render_static_anton_feedback.py \
  tests/test_overlay_position.py -q
cd ../../remotion-video
npm run typecheck
```

Expected: overlay mapping and position tests pass; TypeScript reports no errors.

- [ ] **Step 9: Render the local fixture and inspect three moments**

Render the Anton fixture and inspect one frame from each image hold. Confirm:

- the card never disappears during the unit;
- identity -> spec -> script line occurs in order;
- the card changes side when the stored position changes;
- the card does not cover the machine in the fixture;
- the image motion remains the current smooth push/pull pattern.

- [ ] **Step 10: Commit the overlay change**

```bash
git add storyengine/backend/render_static.py \
  storyengine/backend/overlay_position.py \
  storyengine/backend/tests/test_render_static_anton_feedback.py \
  storyengine/backend/tests/test_overlay_position.py \
  remotion-video/src/renderConfig.ts \
  remotion-video/src/Scene.tsx \
  remotion-video/test-fixtures/anton-feedback-props.json
git commit -m "feat(dvsu): rotate persistent composition-aware info cards"
```

---

### Task 3: Replace the Never-Built blueprint branch with realistic reconstruction

**Files:**

- Create: `storyengine/backend/migrations/155_static_reference_kind.sql`
- Modify: `storyengine/schema.sql`
- Modify: `storyengine/backend/static_docu_contract.py`
- Modify: `storyengine/backend/static_docu.py`
- Modify: `storyengine/backend/pipeline_executor.py`
- Modify: `storyengine/backend/tests/functional/test_never_built_classification.py`
- Modify: `storyengine/backend/tests/functional/test_static_docu_roster_reference_layer.py`
- Create: `storyengine/backend/tests/functional/test_static_docu_never_built_reconstruction.py`
- Remove: `storyengine/backend/tests/functional/test_static_docu_never_built_blueprint.py`

- [ ] **Step 1: Write the failing reconstruction contract tests**

Port the useful setup from the old blueprint test, then assert:

```python
assert generated_roles == {"three_quarter", "side_profile", "top_planform"}
assert all(call.reference_image_url for call in generation_calls)
assert captions[0]["design_study"] is True
assert captions[0]["reconstruction_style"] == "photorealistic"
assert captions[0]["sub"].startswith("Design study — never built")
assert all("[never-built: photoreal-reconstruction]" in row["image_prompt"] for row in rows)
```

Also assert:

- the source schematic/concept image is used only as the generation reference, never copied to `assets.image_url` as final content;
- no verified design reference blocks the unit before generation;
- a photoreal QA failure gets one existing bounded retry and then parks the paid result for review;
- an old caption lacking `reconstruction_style == "photorealistic"` is stale and does not count as a completed role;
- a verified cached historical photo wins even when the conservative text classifier falsely labels the unit Never-Built;
- a design-reference upsert cannot replace an existing verified photo row;
- an ordinary built machine continues through the unchanged historical-photo path.

- [ ] **Step 2: Run the Never-Built tests and verify failure**

```bash
cd storyengine/backend
./venv/bin/python -m pytest \
  tests/functional/test_static_docu_never_built_reconstruction.py \
  tests/functional/test_never_built_classification.py \
  tests/functional/test_static_docu_roster_reference_layer.py -q
```

Expected: failures because the current contract generates two blueprint views with no reference input.

- [ ] **Step 3: Add reference-kind storage without changing the cache key**

Migration 155:

```sql
ALTER TABLE static_reference_cache
  ADD COLUMN IF NOT EXISTS reference_kind TEXT NOT NULL DEFAULT 'photo';

ALTER TABLE static_reference_cache
  DROP CONSTRAINT IF EXISTS static_reference_cache_reference_kind_check;

ALTER TABLE static_reference_cache
  ADD CONSTRAINT static_reference_cache_reference_kind_check
  CHECK (reference_kind IN ('photo', 'design'));
```

Mirror the column and check in `storyengine/schema.sql` and the defensive in-process schema guard. Keep the existing `(tenant_id, machine_key)` primary key. Existing rows default to `photo`, preserving their verified-photo provenance. Photo reads require `reference_kind='photo'`; design reads require `reference_kind='design'`, so a design drawing can never be mistaken for a historical photograph.

Make the write priority explicit: a verified `photo` may replace a stale `design` row, but a `design` upsert uses a guarded conflict update and must never replace an existing `photo` row.

- [ ] **Step 4: Acquire and verify a Never-Built design reference**

Keep `_roster_entry_never_built` conservative and preserve the current verified-photo veto before trusting that classifier. Use this order:

1. Query `static_reference_cache` for a verified `reference_kind='photo'` row before branching. If one exists, it wins: treat the unit as built/photo-grounded even if the text classifier says Never-Built. This preserves the current false-classification safety behavior.
2. Only when no cached photo exists, run `_roster_entry_never_built`.
3. Built unit -> existing photo candidate search and `_vision_confirms` unchanged.
4. Never-Built unit -> first reuse a verified `reference_kind='design'` row; otherwise search the unit's own article/source set for a schematic, three-view, concept illustration, or manufacturer drawing.
5. Verify that the candidate depicts the exact named design and contains usable external geometry. Flat media is allowed only in this branch.
6. Host it durably and store `reference_kind='design'` only if no verified photo row now exists. Re-read before the upsert so a concurrent photo verification still wins.
7. If nothing verifies, keep the visible miss state and block generation. Do not invent the design from model memory.

Expose a verified design reference to the roster dashboard as `status: "verified"` plus `kind: "design"`. The existing verified count and UI can then remain unchanged; `kind` is diagnostic detail.

- [ ] **Step 5: Give Never-Built units the full three-view camera contract**

In `static_docu_contract.py`, make `NEVER_BUILT_VIEW_PLANS` use the same three roles as `STATIC_VIEW_PLANS`. Remove the two-view blueprint-only side/top contract. Keep `STATIC_VIEWS_TARGET = 3` and the generic minimum-two recovery constant, while the DVSU batch readiness check in Task 4 requires 3/3.

- [ ] **Step 6: Replace blueprint prompting with photoreal reconstruction prompting**

Replace `_blueprint_prompt` with `_reconstruction_prompt`. Required positive direction:

```text
Create a photorealistic historical reconstruction of this exact paper-project
machine as if a full-size example had been completed and professionally
photographed. Preserve the verified design reference's proportions, component
count, planform, control surfaces, engines/armament, and distinctive geometry.
Use the requested DVSU camera angle, physically plausible materials, natural
surface detail, realistic lighting and scale, and the channel's clean studio
presentation.
```

Required exclusions:

```text
No blueprint, schematic, line drawing, orthographic plate, CAD viewport,
technical illustration, miniature, scale model, toy, labels, dimensions,
watermarks, or embedded text.
```

The first view uses the verified design reference as image input. Later views chain from the first approved realistic reconstruction, matching the existing identity-preserving view-chain behavior.

- [ ] **Step 7: Replace blueprint QA with reconstruction QA**

Keep the existing budget check, generation ledger, one retry, park-on-reject behavior, and role-conformance judge. Replace `_blueprint_render_confirms` with two checks:

1. `_reconstruction_matches_design_reference` — source/render comparison for distinctive geometry and configuration.
2. `_photoreal_reconstruction_confirms` — final image looks like a full-size real machine photographed with plausible materials/lighting, not any prohibited flat/CGI/model form.

Keep the on-screen/internal marker `Design study — never built`; change the asset marker to `[never-built: photoreal-reconstruction]`.

- [ ] **Step 8: Invalidate old blueprint assets automatically**

When the scene is Never-Built, count a done role only if its caption has:

```json
{"design_study": true, "reconstruction_style": "photorealistic"}
```

The current two blueprint rows lack this marker, so they fall into the existing full-regenerate path and are replaced instead of being preserved as two already-complete roles.

- [ ] **Step 9: Run the focused Never-Built tests**

```bash
cd storyengine/backend
./venv/bin/python -m pytest \
  tests/functional/test_static_docu_never_built_reconstruction.py \
  tests/functional/test_never_built_classification.py \
  tests/functional/test_static_docu_roster_reference_layer.py \
  tests/functional/test_static_docu_c2h_render_qa.py \
  tests/functional/test_static_docu_view_chaining.py -q
```

Expected: all focused static-documentary reference, reconstruction, QA, and chaining tests pass.

- [ ] **Step 10: Commit the reconstruction path**

```bash
git add storyengine/backend/migrations/155_static_reference_kind.sql \
  storyengine/schema.sql \
  storyengine/backend/static_docu_contract.py \
  storyengine/backend/static_docu.py \
  storyengine/backend/pipeline_executor.py \
  storyengine/backend/tests/functional/test_never_built_classification.py \
  storyengine/backend/tests/functional/test_static_docu_roster_reference_layer.py \
  storyengine/backend/tests/functional/test_static_docu_never_built_reconstruction.py \
  storyengine/backend/tests/functional/test_static_docu_never_built_blueprint.py
git commit -m "feat(dvsu): render never-built units as realistic reconstructions"
```

---

### Task 4: Prove one unit, then prepare the 10-video batch

**Files:**

- Modify only if a concrete proof failure requires the one allowed fix pass.
- Do not add new process documents or QA gates.

- [ ] **Step 1: Run one combined no-spend check pass**

```bash
cd storyengine/backend
./venv/bin/python -m pytest \
  tests/test_channel_audio.py \
  tests/test_render_static_anton_feedback.py \
  tests/test_render_static_salvage.py \
  tests/test_overlay_position.py \
  tests/functional/test_static_docu_never_built_reconstruction.py \
  tests/functional/test_never_built_classification.py \
  tests/functional/test_static_docu_roster_reference_layer.py \
  tests/functional/test_static_docu_view_chaining.py -q
cd ../../remotion-video
npm run typecheck
```

Expected: focused backend tests pass and TypeScript reports no errors.

- [ ] **Step 2: Render one offline visual fixture**

Use the Anton fixture to verify identity -> spec -> script rotation, persistent visibility, left/right movement, and the unchanged Ken Burns motion. This uses local fixture media and creates no provider spend.

- [ ] **Step 3: Stop for the existing paid-generation approval**

Quote one Never-Built unit: three GPT Image 2 views plus the existing maximum one bounded retry per failed view. Ask Ryan to approve that quoted amount. Do not generate until approved.

- [ ] **Step 4: Generate and inspect one real Never-Built unit**

Use the unit around 13:44 in the bomber test as the proof target. Confirm all three outputs:

- read as full-size, physically real aircraft photography;
- preserve the verified paper design's distinctive geometry;
- contain no line drawing, gray CAD/model look, labels, or schematic treatment;
- have three genuinely different approved camera angles;
- carry correct safe-corner metadata.

- [ ] **Step 5: Render one complete revised proof video**

Render the current bomber project with:

- Anton's supplied track from frame zero;
- calibrated channel gain;
- no act-level track changes or 30-second trim;
- persistent identity/spec/script overlays;
- regenerated realistic Never-Built imagery.

Compare the voice/music balance against the published channel reference and inspect the rebuilt 13:44 section plus one left-facing and one right-facing ordinary aircraft.

- [ ] **Step 6: Apply at most one focused fix pass if the proof has real breakage**

A fix pass is allowed only for a concrete wrong result: obscured subject, disappearing/doubled card, wrong overlay content, voice masking, blueprint/CAD-looking output, wrong aircraft geometry, or a failed render. Do not start a second review/hardening loop.

- [ ] **Step 7: Stop for the exact batch scope and a separate batch-cost approval**

Obtain the exact 10 StoryEngine video IDs/titles from Ryan or Anton. Do not infer the list from drafts or recent projects. If the list is not supplied, stop after the successful proof video and report that single missing input.

For those exact 10 videos, inspect existing completed assets and calculate the remaining paid provider work under the existing DVSU pipeline: missing image generations/retries, voice generation if absent, and any other already-priced provider call the current pipeline requires. Present the total quoted ceiling to Ryan and wait for explicit approval. The one-unit proof approval from Step 3 does not authorize this batch spend.

- [ ] **Step 8: Prepare the approved 10-video test batch**

For every selected title, require before calling the render ready:

- all units have 3/3 approved views;
- each overlay has identity, sourced spec, exact script line, and a valid corner;
- each Never-Built unit has `reconstruction_style=photorealistic` and no old blueprint rows counted as done;
- the fixed DVSU music config is attached;
- voice, final MP4, and two thumbnails exist under the existing DVSU pipeline rules.

Render the 10 videos. Do not upload or publish without Ryan's explicit separate approval.

- [ ] **Step 9: Report the batch outcome plainly**

Report only:

1. how many of 10 rendered successfully;
2. any concrete blocked unit/video and why;
3. the calibrated music value used;
4. where the reviewable MP4s are;
5. that upload/publish has or has not been approved.

---

## Done definition

The StoryEngine change is done when one full proof video visibly satisfies Anton's three requests and the focused checks pass. The 10-video batch is a separate completion milestone: it is done only after Ryan/Anton supplies the exact 10 IDs/titles, Ryan approves the quoted batch ceiling, and all 10 videos render ready for a publish decision. Neither milestone includes upload or publishing authority.
