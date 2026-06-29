# GOAL - StoryEngine v2: the intelligent director system (correctness pass)

**Mission:** a person uses the chat like a Claude chat and is guided start to finish to build
the most-likely-viral video for their channel, based on real data. The system models a chosen
competitor video (idea, script, style, hooks, thumbnail, cadence, length), draws a storyboard
that shows real camera angles and moves the story forward, locks the characters, and animates
clean grok-imagine clips with real motion. It should feel like an ultra-smart director in the
room.

**Ryan directive (2026-06-27):** the chat is the product's Higgsfield-style MCP / Claude co-pilot
for video production. It must be proactive on every page and every generation step, suggest good
video ideas before the user has to ask, critique and improve prompts, analyze generated images to
judge whether angles make sense for the storyline, and let the creator change channel/modeling
strategy conversationally by dropping YouTube links or saying things like "model this channel for
the highest chance of success." This file is the live source of truth for that behavior.

**This pass is a full sweep to make the system exactly that, fixed at the root.** It is grounded
in an end-to-end multi-agent audit (2026-06-24, 19 agents, adversarially verified at high
confidence). Old GOAL (the chat-first producer build, Phases 1-7, mostly shipped) is preserved in
`GOAL.md.bak-20260624-221122`.

---

## The one root cause (read this first)

StoryEngine has **two parallel image/video pipelines that drifted apart**:

- **The old "grid" path** (`bot.py` 3x3 contact sheet -> `run_storyboard_prompts` /
  `run_storyboard_images` / `run_images`, `run_split`, `segment_script`, the `video_motion`
  camera-writer). This holds almost ALL the director-grade machinery: environment locking,
  per-shot durations, camera-aware motion prompts, the closed-cast validator, story-lock.
- **The new "coverage" path** (`scripts/coverage_to_app.py:generate_coverage_for_video` ->
  `skills/video-pipeline/storyboard/coverage.py`). This is what the chat auto-build and the
  Scenes-page buttons **actually run today**. It draws good multi-angle coverage anchored on a
  cast sheet - but it **inherited almost none of the old machinery**.

Every "fix" so far landed on whichever path the fixer happened to read. The live path a real user
hits is a third thing (coverage) that is missing the integrations. That is why: style defaults to
realistic, every clip is a 6-second "slow push-in" metronome, backgrounds drift, and every
character is injected into every scene. Orphaned old code also gets mistaken for working features
(stale "not wired" comments, a broken self-test). **This is the "fixed but nothing changed at the
root" pattern, named.**

**The cure:** make coverage the single live pipeline, and port / rebuild the director machinery
INTO it; then redirect or delete the old competing paths so there is ONE path. Re-architecture,
which is in scope for this pass.

---

## Decisions locked (with Ryan, 2026-06-24)

1. **grok-imagine first.** Optimize the whole clip path for grok-imagine via kie.ai. Seedance is
   the next goal, not this one.
2. **Root-fix, re-architect where needed.** No band-aids. Where the root is rotten, rebuild it.
3. **Data-foundation phase is in.** The audit confirmed it is half-broken (see Phase 1).
4. **Acceptance gate = a correct Scene 1, proven by screenshots** (see below). Spend is allowed
   only through Scene 1's storyboard, images, and clips, and only if the storyboard shows the
   characters and scenes defined well.
5. **Proof rule (anti-rot):** every phase is proven by a REAL run with a screenshot or a DB
   check, never a self-test. Self-tests that assert on stale strings are how we got fake "done."

---

## Honest state of the 9 subsystems (verified)

| # | Subsystem | Intended | What it actually does today | Live? |
|---|---|---|---|---|
| 1 | **Director chat** | Guide start->finish, pitch a modeled idea on start, suggest by convo | Chat IS wired end to end (real producer call every turn, real auto-build, real co-pilot actions). But "intelligence" is shallow: proactive idea pitch fires ONCE in onboarding only; returning users get a static greeting. Producer gets only a thin brief + a length number, never the competitors' real winning titles/hooks/format. | Wired but hollow |
| 2 | **Style detect->apply** | Know the modeled video's style, ask/recommend, apply everywhere | Two good halves that never meet on the chat path. A real vision style-detector exists (`model_video.py`) but only on the URL-paste flows. Application is style-aware now (commit e19f5241). The "Worth modeling" chat click sends a plain text title with no video ref, so detection never runs and style silently defaults to **realistic**. | Partial (break in the middle) |
| 3 | **Length** | Recommend from THE example video, warn if too short | Slider + recommendation + flow-through all work. But the chat anchor is the tenant-wide MEDIAN of all competitors, not the specific modeled video. A separate non-chat path uses the exact runtime but never asks and clamps to 3 min. | Wired but wrong anchor |
| 4 | **Storyboard angles** | Multiple angles per scene + story moves forward | Multi-angle coverage is real and reaches the final video. But NO story-progression rule exists (only visual continuity), and each scene is planned in isolation with no memory of prior scenes. Some entry points still route to the old single-sheet path. | Partial |
| 5 | **Per-shot timing** | Vary clip length per shot; equal only to extend one scene | Every narration clip is a fixed **6 seconds**. Coverage never stamps a duration, so the clip generator falls through to 6s for all. The 3 components that would vary it are all dead/orphaned. A metronome. | Broken at root |
| 6 | **grok motion + @image** | Camera/motion prompts + @image refs telling who does what | The @image mechanism is live. But coverage writes NO motion prompt, so every narration clip uses ONE hardcoded "slow push-in." The real camera-aware writer only runs on the later FINISH path, not when pictures/clips are first made. | Half wired |
| 7 | **Character lock + 1/scene** | Lock characters; 1 per scene unless very distinct pair | Locking is real (cast sheet + bible + style lock). 1-per-scene is enforced NOWHERE. Worse, the bible marks every character "present everywhere," so all characters get injected into every scene. | Lock yes, count no |
| 8 | **Scene consistency** | Locked, consistent backgrounds; continuity | The env-lock machinery exists but the live coverage path never passes an environment reference (env_url is always None), and the one env-aware path is broken by a name-vs-id key mismatch. Backgrounds rest on re-described prose only. | Inert on live path |
| 9 | **Real data** | Viral picks based on real competitor numbers | API key IS set on prod; daily scrape works (real views present). But onboarding + "model-a-video" still use bot-blocked yt-dlp and write **views=0** rows. Confirmed: 27 of 50 competitor rows real, 23 are zeros polluting the home/discovery filters. | Half real |

---

## grok-imagine prompting rules (baked from research, for Phase 7)

kie.ai gateway. Base `https://api.kie.ai`, `POST /api/v1/jobs/createTask`, `Authorization: Bearer
<key>`. Models: `grok-imagine/image-to-video` (I2V), `grok-imagine/text-to-video`,
`grok-imagine/image-to-image`. Grok Imagine 1.5.

1. **Prompt is a motion script, not a description.** Formula: `[subject + its motion] + [camera +
   its move] + [light/atmosphere shift]`. Do NOT re-describe what is already in the frame - the
   model sees it.
2. **Front-load the camera move and key action.** The engine reads left to right and drops
   tail-end instructions. Lighting/atmosphere go last.
3. **Never contradict the input frame.** Motion must be reachable from the existing pose/framing
   (a seated subject cannot run). This is the #1 cause of warped output.
4. **No negative prompts.** The video model ignores them. Say what you want, positively.
5. **Name one concrete camera move per clip:** dolly/push-in, pull-back, pan, tilt, tracking,
   crane, orbit/arc, dolly-zoom, slow zoom, handheld sway. Add **"Unfixed lens"** when moving the
   camera, **"Fixed lens"** for a locked static shot.
6. **Quantify motion with adverbs and beats:** "slowly," "quickly," "with large amplitude," "she
   takes one step back, turns her head 30 degrees." Mood words ("cinematic, dramatic") give the
   model nothing to animate.
7. **Sequence actions in order** within one prompt; use **"Shot Switch"** for an intentional cut
   inside one clip.
8. **Shot type up front** ("wide / medium / close-up / low-angle / POV"); for I2V the framing is
   set by the input image, so use the shot word to aim the camera move (push from wide into a
   close-up), not to reframe.
9. **`duration` is the length lever, 6-30s, 1s steps.** Per request, so different shots get
   different lengths. Type quirk: I2V wants a STRING ("6"), T2V wants a NUMBER (6). Make short
   native takes and stitch.
10. **@image token = `@imageN ` (1-based + trailing space).** Multi-tag chaining is only for
    image-to-image. **Critical for us: grok-imagine I2V uses only the FIRST image as the motion
    reference; extra images are ignored.** So character consistency on a clip must come from the
    PANEL already containing the locked character (coverage's cast anchor), not from a second
    @image. Multi-@image composition, if needed, happens at an image-to-image stage before I2V.
11. `resolution` "480p" or "720p" (default 480p). `aspect_ratio` one of 2:3 / 3:2 / 1:1 / 16:9 /
    9:16; for I2V it follows the input image if omitted. Prompt is English-only, max 5000 chars.
12. Async: `createTask` returns a `taskId`; get the result by `callBackUrl` webhook (preferred) or
    poll Get Task Details.

---

## Acceptance gate (Ryan's words, exact)

Scene 1 is generated with a storyboard that **shows the angles and progresses the storyline
forward**, with characters and scenes **defined well** in the storyboard. Verify with screenshots.
Only then is there permission to spend, through Scene 1's storyboard, images, and clips - and only
if the characters are represented and the scenes/characters are well defined.

---

## Phases

Each phase lists the root fix, the key files (from the audit), and the proof. Phase 0 is the
keystone - most other phases port their fix INTO the unified path it creates.

### Phase 0 - Unify on ONE pipeline (keystone) `[code-complete 2026-06-29: status-map + Claude orchestrator swapped to coverage (run_coverage_stage); false-proof signals dead. Legacy routes now RETIRED: /prompts /storyboards /storyboard-images /storyboard-extract /images return 410 (reversible). The one live frontend leak (Script & Voice tab "Generate image prompts" buttons) removed; dead components (both VisualsTab variants, image-segment-card) + orphaned /visuals + /storyboard pages deleted (backup at storyengine/.legacy-backup-20260629-*); 4 dead api.ts wrappers removed. Backend compiles, frontend builds clean. LOCAL ONLY - not deployed. NEEDS a Model-A-Video/autopilot run to verify end-to-end (user-test, paid). Remaining: own-channel ingestion, prod zero-row purge.]`
The whole pass depends on this. Make coverage the single live image/clip path and kill the
competing routes.
- Make `generate_coverage_for_video` (coverage) the only image generator a user can reach. Route
  the status map (`pipeline_executor.py:2088-2093`, `ready_for_storyboards -> run_storyboard_prompts`)
  and the co-pilot verbs (`chat.py:533,535`, "storyboards"/"images") to coverage; remove or
  clearly retire the old `bot.py` grid path so no entry point produces a different result.
- Make the clip generator read what coverage writes (sets up Phases 5-7).
- **Kill false-proof signals:** fix the broken producer self-test (`producer_prompt.py:230`
  asserts "MY CHANNEL", header is now "THIS CREATOR'S CHANNEL"); delete the stale "not wired"
  comment in `coverage.py`; fix lying docstrings (`pipeline_config.py` per-segment duration claim;
  `producer_prompt.py:107` "injects proven titles/hooks/look").
- **Proof:** one real chat-built video; confirm via DB + screenshots that every image/clip came
  from the coverage path and no old-path entry point is reachable.

### Phase 1 - Data foundation (real numbers) `[mostly done; dead-video pruning added 2026-06-29]`
DEAD-VIDEO FRESHNESS (2026-06-29): UI test caught the #1 and #2 "Worth modeling"
picks pointing at videos REMOVED from YouTube yet shown as fresh/accelerating (gray
thumbnail = dead). Fix shipped: migration 067 adds competitor_videos.removed_at;
`youtube_data_api.fetch_live_video_ids` batch-checks ids (removed/private => absent);
the /suggested-models endpoint fetches a wider set, soft-flags dead rows (removed_at),
and returns the top 5 LIVE; `_run_scrape` prunes the whole table each run; recent-rows
/ channel-intel / median queries all exclude removed_at IS NOT NULL. All fail-soft.
STILL REMAIN: own-channel ingestion + prod zero-row purge (the older Phase 1 items).
Confirmed half-broken: key is set, daily scrape works, but onboarding + model-a-video write
zeros (23 of 50 rows for the owner tenant).
- Extract one shared `youtube_data_api` helper (single-video + channel) and route EVERY ingestion
  path through it: `onboarding.py` (replace the yt-dlp list + HTML date scrape) and
  `model_video.py:_run_modeling` (replace `_extract_video_info`; keep Supadata for the transcript
  only). `niche.py` already uses the API (commit 49ed96ad).
- Fail loud if `YOUTUBE_API_KEY` is missing (surface "add a YouTube Data API key") instead of
  silently writing zeros.
- Stop persisting `views=0` competitor rows from any path, and purge existing zero rows (they fail
  the `views>0` home filter and block future real upserts).
- **Proof:** re-run onboarding/model-a-video for a channel; confirm competitor_videos rows carry
  real views/duration/vph; home "Worth modeling" shows real numbers.

### Phase 2 - Director chat intelligence `[built 2026-06-29, LOCAL - pending deploy + prod proof]`
BUILT: (1) migration 066 adds channel_profiles.channel_intel JSONB; (2) chat.py
_compute_channel_intel / _get_channel_intel / _channel_intel_brief mine
competitor_videos (top titles, title/hook pattern, thumbnail motifs from
thumbnail_style_json, median runtime, upload cadence) - lazy-first, cached with a
12h TTL, all fail-soft; (3) the rich brief is injected at BOTH producer
build_system_prompt sites (intake turn + _seed_producer); (4) proactive open turn:
a returning onboarded user opening a fresh home conversation now gets a modeled
idea pitch (_generate_competitor_ideas -> _present_ideas_turn) instead of the
static _GREETING, fail-soft to the greeting. Fixed the lying producer_prompt
docstring. Verified locally: py_compile + a stubbed-DB unit test (median/cadence
math, brief text, empty-data fallback all pass). NEEDS: deploy (pull + backend
restart auto-applies 066) + the real prod proof on Ryan's tenant.

Make channel intelligence always-on, not a one-time onboarding seed.
- Persist a rich creator brief on `channel_profiles` (top titles, hook patterns, thumbnail motifs,
  median cadence/runtime), refreshed when scrapes complete - not just the 5 thin `_BRIEF_KEYS`
  (`chat.py:1427`).
- Feed that rich brief into `build_system_prompt` on EVERY producer turn (`chat.py:2046`,
  `_seed_producer`) so script/style/hook/thumbnail suggestions are genuinely modeled.
- Proactive open turn for RETURNING users: when `chat_turn` gets no message and the user is
  onboarded with competitor data, run `_generate_competitor_ideas` / `_present_ideas_turn` to
  pitch a fresh modeled idea instead of the static `_GREETING` (`chat.py:1995,2022`).
- **Proof:** open the home chat as an onboarded user; it pitches a specific modeled idea and the
  producer references real competitor titles/hooks.

### Phase 3 - Style: detect -> recommend -> apply `[todo]`
Connect the two good halves on the chat path.
- "Worth modeling" click and "model this" must pass the reference video id/url so the chat-created
  video is `is_modeled` and `_run_modeling` fires (today `ChatCore.tsx:431` sends plain text;
  `_spec_to_create_request` omits `reference_url`, `chat.py:393`). Detection lives at
  `model_video.py:380` `_describe_scene_style`.
- Show the detected style ("3D Pixar") to the creator as a confirmable recommendation, not a
  silent DB write.
- Never silently default to realistic: if no style is set, either inherit the detected style or
  ask - do not fall through to the photoreal default (`coverage_to_app.py:95`).
- **Proof:** model a Pixar video via chat; storyboard + frames render Pixar (screenshot), style
  was shown and confirmed.

### Phase 4 - Length from the SPECIFIC modeled video `[partial 2026-06-29: deterministic slider backstop done]`
DONE (2026-06-29): the chat length slider now anchors its DEFAULT to the channel's
real competitor median runtime via a deterministic backstop in `_stamp_length_default`
(shared `_competitor_median_seconds`). If the producer picks a normal-form length
below the channel median, the slider opens on the channel median instead (creator can
still drag down); intentional short-form (<2 min) is left alone. Caught live: a "kid
won't clean room" turn defaulted to 5 min though the channel runs ~8 min median / ~15
min top-performers. Unit-tested. STILL TODO: anchor on the SPECIFIC modeled video's
runtime (not just the median) when there's a reference, and unify with the
model_video.py exact-runtime path (which clamps to a 3-min minimum).

- Anchor the recommendation on the chosen video's runtime, not the tenant median
  (`_modeled_runtime_hint`, `chat.py:1411`). Unify with the `model_video.py` exact-runtime path
  (which today never asks and clamps to a 3-min minimum).
- Add a deterministic too-short backstop, not just LLM free text.
- **Proof:** model a 12-min video; chat recommends ~12 min and warns sensibly on a 20s request.

### Phase 5 - Storyboard angles + story progression `[todo]` (into coverage)
- Keep multi-angle coverage (it works). Add a story-progression rule to the coverage directive
  ("advance, never restate") and cross-scene memory (pass prior-scene summaries) - today
  `_coverage_system_prompt` enforces only visual continuity and each scene runs in isolation.
- Add an acceptance check that Scene 1 yields more than one distinct angle and advances.
- **Proof:** Scene 1 storyboard shows distinct angles and clearly progresses (screenshot).

### Phase 6 - Per-shot timing `[todo]` (into coverage)
- Stamp a per-shot duration onto coverage assets (today `store_scene` inserts none -> clips fall
  to fixed 6s). Vary by shot type (the `_CUT` table exists but only paints the static PNG); allow
  grok's 6-30s. Identical lengths only to extend one scene across angles.
- Expand the clip generator beyond the binary 6/10 (`run_clip_generation`; also
  `run_generate.py:89-90`). Retire the dead `run_split` after folding its varied-duration logic
  into coverage.
- **Proof:** a built scene shows clips of varied lengths (DB durations + watch).

### Phase 7 - grok-imagine motion + @image `[todo]` (into coverage, research-baked)
- Generate a per-shot camera/motion prompt into each coverage asset's `video_prompt` (today NULL
  -> one hardcoded "slow push-in"). Reuse/relocate the good camera writer
  (`video_motion/run_scripts.py` `generate_video_prompt`) so it runs when pictures/clips are first
  made, not only on FINISH.
- Apply the 12 rules above: motion script not description, front-load the camera move, one move
  per clip, no negatives, quantified beats, `duration` (string for I2V), Fixed/Unfixed lens.
- **@image correctness:** I2V uses only the FIRST image, so the panel must already contain the
  locked character; a second @image (cast sheet) is ignored on I2V. Keep character identity in the
  panel, not in a second clip reference.
- **Proof:** clips show real, varied camera motion (watch), prompts are per-shot in the DB.

### Phase 8 - Character lock + 1-per-scene `[todo]` (into coverage)
- Add per-scene presence data so the bible no longer marks every character "present everywhere"
  (today `load_character_bible` hardcodes `scenes_present=[]`).
- Enforce 1 character per scene with the "very distinct pair" exception (human+dragon, human+dog) -
  no cap exists today. Down-select the directive to the scene's actual character(s).
- Port the closed-cast validator (anti-invention scrub, old `run_storyboard_prompts` path) into
  coverage so it protects the live images.
- **Proof:** a 2-character script yields scenes with one character each (except the allowed pair);
  no invented/extra people (screenshots).

### Phase 9 - Scene consistency / environment lock `[todo]` (into coverage)
- Load approved `video_environments` in `generate_coverage_for_video` and thread a per-scene env
  reference image into `run_coverage` (today env_url is always None) so each scene's master frame
  is anchored on the approved location, with angles chained on master+env.
- Single-source the location key: generate the Story Bible first (it owns canonical location ids),
  derive environments from bible locations, and resolve env by that same id - kill the
  name-vs-slug mismatch.
- Make the gates real on the live coverage routes (enforce `environments_approved_at` and
  `story_locked_at`); stop the auto-build from blanket-stamping `environments_approved_at`.
- **Proof:** the same location looks consistent across a scene's angles and scene to scene
  (screenshots).

### Phase 10 - The Scene 1 proof (acceptance gate) `[todo]` `[SPEND HERE]`
On the unified path, build Scene 1 end to end and verify against the gate above.
- Generate the Scene 1 storyboard; screenshot-verify it shows the angles, progresses the story,
  and defines characters + scene well.
- Only then spend through Scene 1's images and clips. Watch the clips for real motion, locked
  characters, consistent background, varied shot lengths.
- This is the single go/no-go for the pass.

---

## Sequencing

1. **Phase 0** (unify) - the keystone, do first.
2. **Phase 1** (data) can run in parallel with **Phases 2, 3, 4** (chat / style / length).
3. **Phases 5-9** port the director machinery into the unified coverage path.
4. **Phase 10** is the proof and the spend.

## Out of scope (this pass)
- Seedance (next goal).
- Full multi-scene final render/stitch polish, voice/SFX polish, dialogue mode.
- Anything past a verified, correct Scene 1.

## Log
- 2026-06-24: Multi-agent end-to-end audit (19 agents, adversarially verified, high confidence).
  Root cause found: two diverged pipelines; the live "coverage" path is missing the old path's
  director machinery. Prod check: YOUTUBE_API_KEY set, 27/50 competitor rows real (23 zeros from
  onboarding/model-a-video). grok-imagine prompting rules researched (kie.ai, Grok Imagine 1.5).
  This plan written. Prior GOAL backed up to GOAL.md.bak-20260624-221122.
- 2026-06-24 (overnight): Phase 0 + 1 code work on branch `feat/director-pass` (NOT deployed,
  no spend). Phase 0: killed the false-proof signals (broken self-test, stale/lying docstrings)
  and unified the INTERACTIVE image path on coverage (co-pilot dock verbs now draw via coverage,
  not the old grid). Phase 1: model-a-video + onboarding now fetch via the YouTube Data API
  (real views/duration), heal/skip zero rows, and fail loud without a key. All touched files
  compile; no new test regressions (286 skills tests pass; the 5 failures are pre-existing on
  main). Deferred (need Ryan + a real run): the run_next_step status-map swap, the own-channel
  onboarding ingestion, and the one-time prod purge of the 23 existing zero rows. See
  storyengine/HANDOFF-REPORT.md.
- 2026-06-25 (live test + reliability): deployed Phase 0+1 to prod and live-tested "Model A
  Video". Phase 1 PROVEN end to end (competitor row persisted real 1,325 views / 881s; style
  detected "3D CG Pixar"). Surfaced + fixed a RELIABILITY root cause: the Kie Claude gateway
  500'd then HUNG a modeling run. Decision (Ryan): Claude + vision analysis run on DIRECT
  Anthropic; Kie only for image/video generation (+ fallback). Deployed: model_video
  ._resolve_claude_creds Anthropic-first (was Kie-first); vision_client chain Anthropic-first
  (was Kie-first → ~2.5min of Kie timeouts); stale Anthropic model ids → claude-sonnet-4-6.
  Both verified with real calls. KNOWN MINOR (todo, fold into Phase 4): modeling sets length via
  COALESCE(video_length_minutes, ref) so it keeps the create-form default instead of adopting the
  reference's real runtime.
- 2026-06-29: Phase 0 finished in code. New `run_coverage_stage` (mirrors the proven chat
  auto-build image phase) is now what the autopilot status map (`ready_for_storyboards`/
  `_images`/`_extraction`) and the Claude orchestrator (`storyboard`/`images`) call — the old 3x3
  grid handlers are no longer reachable from those paths. Killed the last lying false-proof
  signal (chat.py "handlers no-op now" comment; they actually ran the full old grid). The chat
  build path was already coverage; this brings the autopilot/orchestrator onto the same single
  path. NOT yet verified end-to-end — needs one Model-A-Video/autopilot run (paid, ~$1-2) to
  confirm the unified path draws correctly and stops at the pictures checkpoint. Legacy explicit
  routes (/storyboards, /prompts, /images) still call the old grid; need a frontend-usage check
  before redirect/retire.
- 2026-06-29 (Phase 0 finish - legacy route retirement, LOCAL only, not deployed): traced every
  legacy route from backend -> api.ts -> component -> mount point. Finding: exactly ONE live leak
  to the old grid - the Script & Voice tab's "Generate image prompts" buttons (scene + segment)
  calling /prompts. Everything else (/images, /storyboards, /storyboard-images, /storyboard-extract,
  both VisualsTab variants, image-segment-card, /visuals + /storyboard top-level pages) was already
  dead/unmounted. Actions: (1) removed the prompt buttons + orphaned state/handlers/effect/imports
  from ScriptVoiceTab so it's script+voice only; (2) deleted the 3 dead components + 2 orphaned
  pages (backup at .legacy-backup-20260629-*); (3) removed 4 dead api.ts wrappers
  (runPromptsForScene/Segment, runImageForSegment/Variants); (4) retired the 5 backend routes with
  a reversible 410 Gone guard. runSplit (/split) kept - it's the legit script segment-splitter.
  Verified: backend py_compile OK, frontend `npm run build` OK (route table shows /visuals +
  /storyboard gone, /pipeline/[videoId]/storyboards + /review intact). DEPLOYED to prod (commit
  e2fe3dfc; pulled on VPS, frontend rebuilt, both systemd units bounced via kill -9 + revive).
  PROVEN live on storyengine.dev: /visuals + /storyboard now 404 (deleted pages gone),
  /pipeline/x/storyboards + /review + /login still 200. Still owed: the paid Model-A-Video
  end-to-end proof (does the unified coverage path draw correctly + stop at pictures), own-channel
  ingestion, prod zero-row purge.
