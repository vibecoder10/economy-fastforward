# Timeline Workbench - mission plan (draft for Ryan's approval)

Drafted 2026-07-28 from a full read-only recon of main @ 4bd6ad5b. Status: DRAFT.
Mission ID when approved: D4. Filed from D3-47.

## The vision, in one paragraph (Ryan's words, 2026-07-28)

The Timeline view becomes the production workbench. Storyboards show up as
blocks on the timeline. Approving a storyboard "unpacks" it into its image
slots. Images generate into clips. The chat drives all of it - "generate
images for storyboards 1 and 2" makes those slots fill on the timeline.
Everything is viewable and unpackable on the timeline.

## The good news from recon

More of this exists than expected:

- The backend can already generate images for a LIST of scenes
  (`generate_coverage_for_video(only_scenes=[1,2])`) - built for finalize,
  already in production use. The primitive Ryan is asking for exists.
- Per-shot clip generation already runs in its own parallel lane with
  per-asset locking (`?asset_ids=a,b,c`). Slots-to-clips is wired backend-side.
- The panel-to-shot mapping already has a frontend parser
  (`parseEnforcedPlan` in canvas-shared/shot-plan-parsers.ts) - board panel N
  maps to assets row `image_index = 99 + N`. No new table needed to know
  which image slot belongs to which storyboard panel.
- A zero-cost test path exists: `plan_only=1` writes a real shot plan and
  board placeholders without drawing anything. We can build and verify the
  whole read path for free.

## The three honest constraints (do not promise around these)

1. **Images land per SCENE, not per slot.** The image writer saves a whole
   scene's frames in one atomic batch. Slots for a scene will fill as a group,
   not one by one. Clips DO fill one by one. The timeline must show the truth:
   images = scene-batch fill, clips = per-slot fill.
2. **No time ruler in v1.** Durations do not exist before clips are made
   (silent shots have one, speaking shots size from measured speech later).
   A time-proportional ruler would lie. V1 is ordinal lanes - blocks in
   order, no seconds. The ruler comes when clips exist.
3. **Chat cannot say "storyboards 1 and 2" today.** The whole chat contract
   (classifier, pending action, cost quote) is single-scene scalar. Widening
   it touches the money-quote path - the highest-consequence code in the app.
   That is its own carefully-tested chunk, not a side effect.

## Vocabulary decision (recommended)

"Storyboard N" = scene N's storyboard. One scene, one storyboard block on
the timeline (a scene can span up to 5 board sheets internally - still one
block). This matches how the chat already numbers scenes and avoids a second
numbering system.

## Build log

- T1 DONE 2026-07-28: branch feat/t1-timeline-slot-model @ c7dcdb62.
  buildTimelineSlots() in canvas-shared/timeline-slots.ts, 13/13 unit tests
  (vitest added - the frontend had NO unit runner before, only Playwright).
  Parser verdict re-proven two ways: parseEnforcedPlan is canonical,
  image_index = COVERAGE_INDEX_BASE(100) + per-frame increment over the same
  post-budget moments list the sheets are built from. TWO NEW FINDINGS:
  (a) storyboard_prompts is truncated to 5 sheets but the picture pass draws
  every planned shot - panels past sheet 5 surface as honest "overflow"
  slots (board null, real fill-state). (b) The LIVE clip-failure path never
  persists a failure marker on the asset row - a failed clip is
  indistinguishable from never-attempted. state=failed is wired defensively
  but only fires for static_docu markers today. T2/T3: do NOT build a
  failure badge that promises to fire for animation channels. NEW BACKEND
  CHUNK FILED: T5b - persist a clip-failure marker on assets in the live
  path so the timeline can show failed honestly (goes with T5).

- T2 DONE 2026-07-28 (second pass, after Ryan's layout correction): branch
  feat/t2-timeline-altitude @ 96ec9e7c. Horizontal editor timeline docked
  at the bottom of the canvas: player region above (plays final_video_url
  when it exists - proven on 973c9bd6), Video track with storyboard-face
  segments that unpack IN PLACE into slot cells, Voice lane (real
  voice_over_url blocks), Music lane placeholder, inert playhead + zoom +
  mutes, honest ruler (sequence markers now, real timecodes auto-activate
  when T2b exposes durations - proven synthetically). Orchestrator walked
  both test videos personally on localhost before merge. 13/13 tests, tsc
  and build clean.

## Chunks

T1. Slot model (frontend-pure, tested). One function: storyboards + assets
    in, slot list out (planned / pending / image / clip / failed per slot).
    Must resolve a known parser discrepancy (plan says 40 shots, boards draw
    27 - the boards are the truth) before anything renders.
T2. Timeline altitude becomes real, read-only. Replace the static mock,
    flip the SOON tag. Storyboard blocks per scene; expand to see slots.
    Zero spend, pure frontend. Ship complete or keep the tab disabled.
T2b. (H, backend, small) Expose assets.video_duration and
    assigned_video_duration on the existing GET /api/videos/{id}/assets
    serializer - the DB holds real per-clip seconds but the API drops them
    (proven by curl 2026-07-28), which is the only thing blocking the real
    proportional ruler. Frontend already activates automatically (proven
    synthetically). No new endpoint.
T3. Unpack + approve. Clicking/approving a storyboard block expands it into
    image slots and persists that state. Reuse the existing storyboard
    approval route if it fits - do NOT invent a third approval mechanism.
T4. Scene-list chat routing. "generate images for storyboards 1 and 2"
    reaches `only_scenes=[1,2]` with ONE correct combined cost quote.
    HIGHEST RISK CHUNK - touches classifier contract + both money-quote
    functions. Unit tests on the quote math before any live turn.
T5. Live fill. On each progress tick, refresh assets and diff into slot
    states (the proven D3-31 pattern - no new SSE event type). Honest
    granularity per constraint 1.
T6. Slots to clips. Per-slot / multi-slot animate via the existing clip
    lane. Slot shows image -> animating -> clip. UI must cap fan-out (no
    one-click 40-clip bill).
T7. Partial-spend gating. Today the pictures approval gate fires once;
    an unpack-then-fill flow could walk past the cap in $0.30 increments.
    Extend gating to track cumulative session spend.
T8. Proof walk. Drive plan -> unpack -> fill -> clip on the real app with
    screenshots at every gate. Needs one small Ryan-approved spend
    (minimum route: plan_only + one short scene).

Dependencies: T1 -> T2 -> T3 -> T4 -> T7. T3 -> T5 -> T6. T8 last (consumes
T4 and T6). T5 and T6 do NOT wait on T4 - slot fill works for today's
per-scene buttons too, so the timeline is useful before chat routing lands.

## Phasing recommendation

- Phase 1 (zero spend, ships value alone): T1 + T2 + T3. The timeline
  exists, storyboards showcase on it, approving unpacks into slots.
- Phase 2: T5 + T6. Slots fill live and become clips.
- Phase 3: T4 + T7 together (routing + gating land in the same phase so
  the money path is never widened without its guard - contract triangle law).
- Phase 4: T8 proof walk.

## Ryan's expanded vision (2026-07-28, second pass - his words distilled)

- The chat surface IS the product now. The old click-through pipeline pages
  get retired eventually; they stay untouched for now. The old UI's small
  side co-pilot inverts: chat up front as the driver, windows show assets.
- Folder UX: characters, scenes, storyboards all land in clean asset folders
  that tie back to the user's own Google Drive folders (storage is already
  Drive - this is surfacing it, not new plumbing).
- The timeline is the editor function - peek under the hood, edit anything;
  once locked in, flip to automation. Quick generate-and-edit always stays
  one chat message away.
- Flow he described: storyboards populate the timeline as they are drawn ->
  chat proactively RECOMMENDS the next step ("ready to generate images, or
  just one storyboard?") -> "generate images from storyboard 1" unpacks it
  in place, sitting next to still-packed storyboard 2 -> targeted edit:
  "change storyboard 1 image 5 to have the character do X" rewrites the
  prompt and regenerates that one image in one go. The system knows where
  you are at all times.
- New requirement this adds to T4/T5: the chat should also PROACTIVELY offer
  the generate step when storyboards finish, not only respond to commands.
  The approval-gate machinery (D3-20) is the natural home for that offer.
- Targeted-edit regen ("storyboard 1 image 5") maps to existing pieces:
  ui_context asset targeting (D3-5) + edit_shot_image_prompt + single-shot
  redraw. Slot addressing from the timeline must feed the same targeting.
- CAVEAT filed, not planned: DvsU channels need a similar timeline
  population but have real layout nuances vs animation channels. Own
  planning pass later; do not let it block the animation-channel build.

## Decisions - MADE by Ryan 2026-07-28, plan is APPROVED to build

1. Storyboard N = scene N. Locked.
2. SUPERSEDED same day - see the layout correction below.
3. Clips-first (T5/T6 before T4/T7). Locked, with Ryan's rider: after
   clips-first lands, the chat must be able to "do whatever we ask" - T4 is
   not a nice-to-have, it is the committed follow-on, full command coverage.

## LAYOUT CORRECTION (Ryan, 2026-07-28, overrides decision 2)

Ryan rejected the first T2 build (vertical stack of storyboard lane cards)
with an OpenArt director-suite screenshot: "thats not a timeline, this is a
timeline." The OpenArt reference is the literal layout spec (consistent with
the standing Director UI target):

- HORIZONTAL track-based editor timeline DOCKED AT THE BOTTOM of the canvas.
- The area above it is the player/preview (our existing "Your video will
  land here" canvas center; the rendered video plays there when it exists).
- Video track: a horizontal filmstrip of segments in scene order. Pre-clip,
  a segment is the scene's storyboard block (sheet thumbnails); clicking it
  expands/unpacks to its slot tiles (T1 model unchanged - the data layer
  survives this correction untouched).
- Audio lanes below the video track (voice/narration per scene, music) -
  render real data read-only; empty lanes show a muted add-slot affordance
  that does nothing in v1.
- Time ruler and timecodes: shown with REAL numbers when clip/voice
  durations exist; before durations exist the ruler area stays but shows
  sequence markers (Scene 1, Scene 2...) instead of fake seconds. Never
  invent seconds - honesty rule stands, expressed inside the horizontal
  layout instead of by going vertical.
- Zoom slider and track mute toggles: visual placeholders acceptable in v1
  read-only; Add shot / Add music / Add voiceover buttons are T3+, not v1.

Second clarification (two more OpenArt screenshots, same day) - the altitude
mapping is now explicit:
- OpenArt Scene view (scene rows, each with its shot cards and Add Shot
  affordances) = our existing Scene altitude. The rejected vertical
  storyboard-card stack was accidentally rebuilding this.
- OpenArt Shot editor (single shot, player + own filmstrip scrubber,
  Recreate / Modify / Extend / Upscale / Grab Frame verbs) = our Shot
  altitude, still a SOON stub - future mission, do not build now.
- OpenArt Timeline = the real editor timeline and the T2 target. Unpacking
  a storyboard happens ON the video track: the packed segment expands in
  place into per-shot cells side by side, like adjacent clip thumbnails in
  any editor. A playhead line exists from v1 (inert until playback exists).
