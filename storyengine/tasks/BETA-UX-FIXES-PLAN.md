# StoryEngine - Beta First-User UX Fixes + 5-Style Engine (BUILD SPEC)

Status: READY TO BUILD - handed to Codex for execution (Ryan's Claude plan resets
Sunday). This is a STANDALONE spec: build from THIS file, no original chat needed.
Owner: authored by Osiris (Fable) via maestro. Created / finalized 2026-07-23.
Repo: github.com/vibecoder10/economy-fastforward, branch main; paths below are
relative to `storyengine/`. LINE NUMBERS MAY HAVE DRIFTED (files were edited live) -
re-grep the quoted anchors before editing (that's SWEEP-0, the first step).
Trigger: first real StoryEngine user + a beta user hit confusion on the finish
page and thought the chat had stalled (panicked about spent credits).

**FOR THE EXECUTOR (Codex):** decisions marked [RESOLVED] are locked - build them.
Recommended order: SWEEP-0 re-pin -> Lanes 1/3/4 (beta fires) + Lane 2 (5 styles +
knob schema) in parallel -> Lane 5 (Design Your Own; depends on Lane 2's schema).
Keep main releasable per commit; verify each user-facing change by actually walking
the flow in the browser, not just building. Still needs Ryan before those chunks:
the DEC items NOT marked [RESOLVED], and DEC-CHOICE-COPY wording.

---

## Ryan's decisions (locked)
- **Force a pick, no default.** At creation the user must choose their VIDEO
  STYLE before starting - one of 4 named styles (below). No hidden default = no
  surprise spend. The choice sets render mode, script profile, image density,
  language/dubbing - and reframes the finish page.
- **5 video-style profiles, each LABELLED with a short description** (today the
  first 4 are SCATTERED across 3 systems; the work is to unify them into one
  labelled, described, selectable pick). Each style's label + description is
  **surfaced in EVERY UI surface AND every chat feature** - creation, finish page,
  and all co-pilots - so the user always knows which style they're in.
  1. **Poco a Poco** - "Animated bilingual stories with real dubbed voices."
  2. **Easy English** - "Simple-English animated stories for language learners."
  3. **DvsU** - "Ken Burns photo documentary - a listicle of items, a few images each."
  4. **Power Doctrine** - "Investigative documentary - a picture for every beat, animated."
  5. **Design Your Own** - "Describe your vision; StoryEngine assembles the pieces
     into a custom film." A natural-language vision prompt -> an LLM planner that
     KNOWS every knob and how to combine them -> a per-SECTION assembly. Ryan's
     stress test: one video that mixes static documentary images, animated
     documentary clips, a little cartoon speaking dialogue in another language, and
     a Seedance cinematic outro - "assemble any puzzle piece into any motion picture."
  (Descriptions above are drafts - final wording via DEC-CHOICE-COPY.)
- **Scope = the whole flow:** creation form -> finish page -> all chat co-pilots.
- **Every style must have ENOUGH images to tell its story** (Power Doctrine ~per
  sentence/visual cue; DvsU 3-4 per item) - not the coarse counts shipping today.
- **North Star (NOT this build, direction only):** a huge built-in free stock
  library (Pixabay-scale, ~6.2M+ images) creators can pull from. Design the knob
  schema so an "image source" dimension (generate vs library) can slot in later.

## Honest corrections (VERIFIED in code - quotes in surface map)
1. **Chat stall = architecture bug, not a slow model.** `POST /api/chat` is
   synchronous; long work runs as background tasks *after* the turn returns; the
   docked `ChatCore` never consumes the SSE `task_progress` channel that already
   exists and that the home `CreatedCard` already uses. Fix = wiring. Low-risk.
2. **Power Doctrine's beat->image->video flow is ALREADY LIVE - just paced too
   coarse. This is a TUNE, not a build.** Every animated video already does
   image-prompt-per-shot then motion-prompt-per-image
   (`coverage_to_app.py:2932 _write_motion_prompts`, gated by `gate_motion_prompt`
   at :2785). The only problem: the coverage planner paces ~1 image / 8s of speech
   (`coverage_to_app.py:2626 COVERAGE_PACING_SECONDS=8`), so a 725-word script got
   ~30 images instead of the ~50 a per-sentence cadence would give. Fix = lower
   the pacing constant or switch to a per-sentence formula. See DEC-DENSITY / DEC-BEATPATH.
3. **The original beat engine still exists but is RETIRED - do NOT resurrect it.**
   `skills/video-pipeline/storyboard/bot.py` (`segment_script_into_beats:354`,
   `build_image_prompt_from_keyframe:1352`) + `video_motion/run_scripts.py` are
   present, but the `/storyboards` endpoint returns HTTP 410 and `run_next_step`
   routes every storyboard stage to `run_coverage_stage`
   (`pipeline_executor.py:13617-13619`). Its beat = a ~40s / 9-panel (3x3) grid,
   not one-per-sentence. Coverage already does the same image->motion shape, so
   tune coverage; don't un-retire the grid path.
4. **DvsU today = ONE image per scene, NOT 3-4 per machine** (`static_docu.py`
   ~1530, `image_index=1`; held full narration in `render_static.py:179` + Ken
   Burns). So DvsU is also under-imaged vs Ryan's spec -> its own small fix.
5. **The 4 styles are scattered across 3 layers, no unified picker:** Poco/Easy
   English = `channel_identity.visual_format` (animated dialogue) + dialogue-shape
   auto-detect (`dialogue_intelligence.py:32` threshold 0.8) + STS
   (`clip_dialogue.py:405-434`, ElevenLabs `/v1/speech-to-speech`); DvsU =
   `render_mode='static_docu'` via `static_mode_for_tenant` (`static_docu.py:62`);
   Power Doctrine = a script profile (`power_doctrine_v1/v2`). Unifying these into
   one 4-way creation pick is the core productization work.
6. **60-day deletion does not exist in code.** No retention/purge/TTL anywhere.
   Warning users about it is either a promise we must build, or copy we must
   soften. See DEC-RETENTION.

---

## Definition of Complete (graded against this, not the checkboxes)
1. A brand-new user is walked from signup to first finished video with a visible
   "you are here" pipeline map, and NEVER sees a dead spinner - the co-pilot
   always says what it is doing ("writing scene 2 of 3", "drawing image 12/30").
2. At creation the user makes ONE clear, required pick from 5 LABELLED,
   DESCRIBED video styles, and sees in plain English what each means for cost and
   image count BEFORE committing. The chosen style's label + description follows
   the video through every UI surface AND every chat co-pilot.
3. Each style generates enough images to tell its story (Power Doctrine ~1 per
   sentence/visual cue; DvsU 3-4 per item), not the coarse counts shipping today.
4. The finish page reads clearly: voiceover-comes-at-the-end is obvious; "Animate
   everything" and "Animate scene" are visually distinct; the progress text is
   clean and out of the cramped box; a static video isn't pushed to animate.
5. A user not on their own Google Drive is clearly warned their media lives on
   StoryEngine (and the retention reality) and is nudged to connect Drive.
6. DvsU stays its own static format; Power Doctrine produces the richer per-cue
   density; the 4 named styles are presets over a shared knob schema.
7. "Design Your Own" exists: a user describes a vision in plain language and the
   system assembles a coherent per-section plan from the knobs - and the extreme
   stress test (static + animated + cartoon dialogue in another language +
   Seedance outro, in one video) renders end to end.

---

## Surface map (real files, from read-only recon)
- **Finish page:** `frontend/src/components/production/ScenesWorkspaceTab.tsx`
  - "Animate everything" button ~1508-1515 (rendered via `createPortal` into a
    StageRail slot). Per-scene "Animate scene" ~1793-1802 (SAME className/color).
  - Messy stretched progress text ~1626-1649. "No voice yet" banner ~1345-1355.
  - Stage rail: `production/StageRail.tsx` (+ `StaticDocuStageRail.tsx`).
  - Cost chip: `components/video-detail/cost-ledger-chip.tsx`.
- **Chat co-pilot (ONE component):** `frontend/src/components/chat/ChatCore.tsx`
  - Home command center (`ChatHome.tsx`) + docked video co-pilot
    (`app/pipeline/[videoId]/page.tsx` ~1021/1063).
  - Synchronous `sendChatTurn` -> `POST /api/chat` (`lib/api.ts` 3061-3065).
  - Live channel already exists: `hooks/use-pipeline-sse.ts` ->
    `GET /api/pipeline/stream` (events `stage_change`, `task_progress.message`).
  - Home `CreatedCard` (ChatCore 1914-1934) already shows live progress.
    Docked co-pilot shows NOTHING (comment ChatCore 286-287).
  - Backend: `routes/chat.py`; SSE `routes/pipeline.py event_generator` ~3145-3255;
    progress hook `_set_task_status(video_id,"running",message=...)` (pipeline.py 373).
    Per-scene messages in `scripts/coverage_to_app.py` `_p(...)`; NO per-image counter.
- **Creation forms:** onboarding `components/onboarding/CreateVideoStep.tsx`
  (length 5/10/15, aspect, resolution, research, AI voice y/n) + main wizard
  `app/pipeline/page.tsx` (style, style_preset, stage toggles `PIPELINE_STAGES`).
  `createVideo` params `lib/api.ts` 391-425 - NO motion field. Only motion lever
  today = the "video" stage toggle (`PIPELINE_STAGES` line 167).
- **Shot/image count:** `backend/pipeline_executor.py` 11532-11537
  (`default_scenes = max(2,min(8,round(minutes*2.5)))`, ~145 wpm).
  Animated: `backend/scripts/coverage_to_app.py` 2545-2626 (paced ~1 shot/8s,
  cap 40/scene) + `backend/render_perform.py` (subdivides narration, loops/freezes).
  Static: `backend/static_docu.py` 1529-1537 (ONE image/scene) +
  `backend/render_static.py` `_build_render_config` 176-233 (held full narration).
- **Google Drive:** `backend/storage.py` (`STORAGE_BACKEND` default `google_drive`),
  proxy `backend/routes/media.py serve_drive_file`. Connect/skip UI
  `frontend/src/app/settings/page.tsx` ~437-526. Onboarding has NO Drive step.
- **Onboarding:** chat-first default (`app/onboarding/page.tsx` redirects to `/`
  unless `?manual=1`). Chat-first via `ChatCore start_onboarding`. Classic wizard
  at `?manual=1`: Channel -> Tools(keys) -> YouTube -> Style -> First Video.
- **Profiles:** `skills/video-pipeline/shared/profiles/script/*.py`
  (`neutral_v1`, `power_doctrine_v1`, `power_doctrine_v2`, `schema.py`). Loaded via
  `backend/routes/script_profiles.py` line 28. Profiles carry NO image logic.
  (Edit canonical `skills/video-pipeline/...`, NOT a `.claude/worktrees/...` copy.)

---

## The work - 5 lanes (parallel across lanes, sequential within a lane)

Legend: (S)=Sonnet build, (H)=Haiku grunt. Layers [D]data [B]backend [U]ui [V]verify.

### SWEEP-0 (H) [V] - post-merge re-pin  *(run FIRST, at execution start)*
After the other sessions merge, re-verify the anchors above still match
(`ScenesWorkspaceTab.tsx`, `ChatCore.tsx`, the two creation forms,
`static_docu.py`). These files are edited live; report line drift so briefs stay
accurate. Pure mechanical -> Haiku.

### Lane 1 - Co-pilot never looks stalled  *(shared file ChatCore.tsx -> sequential)*
- **L1-CHAT-SSE (S) [U][V]** - Wire the DOCKED `ChatCore` to `usePipelineSSE` so
  long jobs show live progress in the dock, mirroring `CreatedCard`. This is the
  direct fix for the "dock shows nothing -> user thinks it stalled -> panic" bug.
  Files: `ChatCore.tsx` (~286 + docked usage), `hooks/use-pipeline-sse.ts`.
- **L1-CHAT-MSG (S) [B][U][V]** - Finer + broader progress messages: add per-image
  counters in `coverage_to_app.py` loops ("drawing image 12/30"); make sure the
  script-gen and voice-gen stages also emit `_set_task_status` messages (not just
  coverage). Verify `POST /api/chat` returns promptly and hands long work to the
  background - if the chat turn itself blocks on a long LLM/generation call, make
  it acknowledge immediately and report via SSE. Files: `coverage_to_app.py`,
  `routes/pipeline.py`, `routes/chat.py`.
- **L1-CHAT-MAP (S) [U]** - "You are here" pipeline map in the co-pilot: a compact
  sequential stage strip (Research -> Script -> Voice -> Characters -> Environments
  -> Storyboards -> Pictures -> Sound -> Clips -> Thumbnail -> Render) with the
  current stage highlighted. Directly answers "map how the chat shows what the UI
  does, in sequential order." Also show the video's STYLE label + description at the
  top of the strip (from the style-metadata module) so the co-pilot always states
  which style is in play. Files: `ChatCore.tsx` + a small StageMap component.

### Lane 2 - The 4-style pick + right image density  *(creation + backend)*

The style->config mapping the worker implements (this is the planning decision;
worker just wires it):

| Style | render_mode | script profile | image density | animation | language/dubbing |
|---|---|---|---|---|---|
| Poco a Poco | coverage | dialogue/neutral | dialogue-shape | animated (grok_native) | bilingual + STS |
| Easy English | coverage | neutral (simple) | dialogue-shape | animated | one language, simple |
| DvsU | static_docu | neutral | 3-4 imgs / item, Ken Burns | static | narrator |
| Power Doctrine | coverage | power_doctrine_v2 | ~1 img / sentence | animated | narrator |

- **L2-STYLE-PICK (S) [D][B][U][V]** - Unify the 3 scattered layers
  (`channel_identity.visual_format` + `render_mode` + `script_profile`) into ONE
  required 4-way "video style" pick at creation, wired to a per-video override of
  the channel auto-set. Surfaces: both creation forms (`CreateVideoStep.tsx` +
  `pipeline/page.tsx`), `lib/api.ts createVideo`, backend `routes/videos.py` +
  `static_docu.static_mode_for_tenant` + the dialogue-shape/profile selection.
  Plain-English "what this style costs / how many images" at the pick. BIGGEST
  chunk - likely split into a UI chunk + a backend-plumbing chunk. Design of the
  mapping table above is done; implementation is the worker's.
  **DESIGN PRINCIPLE (load-bearing - enables "Design Your Own" + Phase 2):** build
  profiles as PRESETS over a named DIMENSION SCHEMA (render_mode, script_profile,
  image_density, animation, language, dubbing, segmentation, camera, quality_laws,
  + a future image_source knob for the stock library), NOT hardcoded branches. The
  4 named styles are 4 rows of preset knob-values; the 5th ("Design Your Own")
  composes rows per-section (Lane 5). This is what makes the whole vision cheap
  instead of a rewrite.
  **STYLE METADATA = ONE SOURCE OF TRUTH:** define the styles as a single data
  module (id, label, short description, knob-preset). EVERY surface reads from it -
  creation cards, finish page, and all chat co-pilots - so the label + description
  appear everywhere and never drift. Lane 1 (chat) and Lane 3 (page) consume this.
- **L2-PD-DENSITY (S) [B][V]** - Power Doctrine density TUNE (DEC-DENSITY RESOLVED:
  ~1 image per sentence / visual cue). PREFERRED approach: change `_coverage_shape`
  to segment by visual cue / sentence boundary (folding trivial fragments into the
  adjacent cue), rather than just lowering the `COVERAGE_PACING_SECONDS` env knob -
  the env tweak is the quick fallback. Land ~50 images for a 5-min/725-word script.
  Files: `backend/scripts/coverage_to_app.py` ~2626 (`_coverage_shape`). Small
  change, HIGH blast radius (image + clip spend) -> VERIFY resulting count + cost
  on a real short video.
- **L2-DVSU-STYLE (S) [D][B][V]** - Expose the DvsU channel's LIVE profile config
  as a selectable style under a GENERIC public name (DEC-DVSU RESOLVED: dynamic
  mirror, do NOT hardcode numbers). The style REFERENCES the DvsU channel's
  `channel_identity` / `channel_profiles` config so it stays in sync as that
  channel changes - it is not a copied snapshot. Design note: the style system must
  support BOTH fixed presets (Poco, Easy English, Power Doctrine) AND channel-bound
  dynamic styles (this one). Files: `static_docu.static_mode_for_tenant`,
  `routes/channel_profile.py`, the style-metadata module. NO hardcoded 3-4/item
  change here - if DvsU should be 3-4/item, that is a tweak to the DvsU CHANNEL
  config, which this style then inherits automatically.
- **L2-STYLE-VERIFY (S) [V]** - After the above land, generate one short video in
  EACH of the 4 styles and confirm each produces the right shape (Poco bilingual+
  STS, Easy English single-lang, DvsU = its channel's live config, Power Doctrine
  ~1/sentence animated). Deferred-verification (real generation spend - batch + quote cost).

### Lane 3 - Finish page clarity  *(shared file ScenesWorkspaceTab.tsx)*
- **L3-PAGE (S) [U][V]** - (a) Differentiate the two animate buttons: primary
  "Animate everything" vs secondary/outline "Animate scene" (distinct weight/color
  so they don't read as the same action). (b) Clean up + relocate the stretched
  progress text out of the cramped portal box, above the icon row, as a tidy
  single line / small stat row. (c) Make voiceover-at-the-end unmistakable
  (stepper / Sound-stage label + keep the "No voice yet" banner). (d) If the video
  is a static slideshow, say so and don't push "Animate everything" as if required.
  (e) Show the video's STYLE label + description (from the style-metadata module)
  at the top so the user always knows what they're making.
  Files: `ScenesWorkspaceTab.tsx` ~1345 / ~1508 / ~1626-1649 / ~1793.

### Lane 4 - Google Drive warning
- **L4-DRIVE (S) [U][V]** - Skip-Drive warning: honest copy in the settings Drive
  card + a banner in onboarding/create when no Drive is connected ("your media is
  stored on StoryEngine and may be removed - connect your Drive to own your
  files"). Files: `settings/page.tsx` ~448, onboarding/create surfaces. Copy
  wording depends on DEC-RETENTION.

### Lane 5 - "Design Your Own" (composable engine + NL planner)  *(biggest; DEPENDS on Lane 2 knob schema)*
The stress-test capability: assemble any pieces into any film. Two new capabilities
beyond the 4 presets:
- **L5-SECTIONS (S) [D][B][V]** - Per-SECTION knob application. Today render_mode,
  language, character/dialogue, and image density are per-VIDEO. Make them
  assignable per scene/section (a plan = an ordered list of sections, each with its
  own knob values). This is the load-bearing change. HIGH blast radius (render
  pipeline). Files: `render_static.py` / `render_perform.py` (per-section render),
  `static_docu.static_mode_for_tenant` -> per-section, `pipeline_executor.py` stage
  plan, coverage + dialogue + Seedance clip paths. Likely SPLIT into sub-chunks.
- **L5-PLANNER (S) [B][U][V]** - The NL vision planner: a 5th creation card "Design
  Your Own" -> a "describe your video" prompt -> an LLM given the FULL knob schema +
  every piece's capabilities, outputting a validated per-section plan (the L5-SECTIONS
  schema). Do the LLM thinking on OUR subscription where possible (free), hand
  StoryEngine the structured plan. Show the user the assembled plan in plain English
  + cost BEFORE they commit - no silent/surprise assembly. The co-pilot can drive it
  too. Files: creation UI, a planner module, `routes/chat.py`.
- **L5-STRESS (S) [V]** - Acceptance: render Ryan's extreme example end to end -
  static doc images -> animated doc clips -> a cartoon speaking dialogue in another
  language -> Seedance cinematic outro - in ONE video. Deferred-verification (real
  spend; quote cost, one run).

**Sequencing call:** Lane 5 is a genuine BUILD (not a fix) and by far the largest,
and it DEPENDS on Lane 2's knob schema. Recommend shipping Lanes 1/3/4 (the beta
fires) + Lane 2 (the 5 presets + schema) FIRST, then Lane 5 rides the schema as a
focused follow-on - so the urgent first-user fixes are NOT blocked behind the
ambitious engine.

---

## Decision-chunks (parked - do NOT block the loop; Ryan reacts at review)
- **DEC-BEATPATH [RESOLVED 2026-07-23]** - TUNE the live coverage path (option a),
  do NOT un-retire the old beat/3x3-grid engine. Why: coverage already does
  image->motion per shot; un-retiring resurrects a deliberately-killed subsystem
  for no gain. Ryan confirmed the target density (below), which the tune delivers.
- **DEC-DENSITY [RESOLVED 2026-07-23]** - Ryan: "the density used to be
  essentially an image per visual cue, roughly an image per sentence - I want
  that." TARGET = **~1 image per sentence / visual cue** (~50 for a 5-min/725-word
  script vs ~30 today). Implementation treats the unit as a VISUAL CUE, so trivial
  sentence fragments fold into the adjacent cue (avoids choppiness) while still
  landing ~1 image per sentence. Cost increase (~+67% image + clip spend) is
  ACCEPTED as the cost of telling the story properly.
- **DEC-DVSU [RESOLVED 2026-07-23]** - Do NOT hardcode DvsU's numbers. The DvsU
  style is a DYNAMIC MIRROR of the DvsU channel's live profile config - whatever
  that channel is set to today (currently static_docu / Ken Burns) IS the style,
  and if the channel changes tomorrow the style changes with it. Expose it under a
  GENERIC public name (not the customer's "DvsU"/"Designed vs Used" brand - see
  DEC-CHOICE-COPY). Wanting DvsU at 3-4 images/item = a tweak to the DvsU CHANNEL
  config, which the style inherits automatically - not a code change to the style.
- **DEC-RETENTION [RESOLVED 2026-07-23]** - Ship the HONEST warning now (L4-DRIVE):
  "media stored on StoryEngine isn't guaranteed long-term - connect your Drive to
  keep your files." NO hard 60-day timer / purge job in this pass (deletion is
  irreversible; build a real TTL later as its own careful chunk if wanted).
- **DEC-CHOICE-COPY** - Exact upfront wording for the 5-style pick (what each style
  is, cost, image count) AND the GENERIC public name for the DvsU-mirror style
  (candidates: "Photo Listicle", "Object Showcase", "Product Documentary").
  **Rec:** Osiris drafts; Ryan approves before ship. (Only open item left.)

---

## Phase 2 - Save + learn novel profiles (deferred; rides on Lane 5)
"Design Your Own" (Lane 5) builds the customize/assemble engine. Phase 2 is the
remainder of Ryan's vision - the system saving and learning good novel combos:
- **P2-SAVE (later)** - when a Design-Your-Own plan doesn't match any saved style,
  offer "Save as a new style" (named, per-tenant). Saved styles then appear in the
  creation pick alongside the 5 built-ins.
- **P2-LEARN (later, rule-based first)** - detect a recurring custom combo ("you've
  used this 3x - save it as your channel default?"). Start rule-based, NOT ML.
- **P2-LIBRARY (North Star)** - the Pixabay-scale free stock library as an
  `image_source` knob (generate vs library). Design the schema to accept it now;
  build later.
Guardrail carried from Lane 5: assembly is USER-DRIVEN, never silent-auto - silent
mixing reintroduces the unpredictability that panicked the beta user.

## Execution model
- Lanes 1-4 touch mostly different files -> dispatch the four lane-leads in
  PARALLEL once SWEEP-0 confirms anchors. Within a lane, sequential (shared files).
- Every chunk verified visually (run-it-like-a-user) before its box is ticked:
  walk the flow locally with `se devtoken` + local dev server, then one
  `/se-smoke` pass on prod after deploy.
- Main stays releasable at every commit. Backup the big live-edited files before
  wholesale rewrites (offer first).
- Kickoff after merge: "Invoke maestro, read this plan, run SWEEP-0, then
  dispatch the four lanes."
