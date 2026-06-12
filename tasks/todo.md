# Task Tracking

## ★ THREAD HANDOFF — read this first (2026-06-12, end of the long UI/dialogue thread)

**North star (in agent memory too):** any person pastes a YouTube link → the
machine replicates that video (new script/idea) FULLY UNATTENDED. Ryan has a
queue of people wanting their channels automated; every design choice must
work without a human in the loop. Intelligence layers detect format — never
manual flags.

**Working video:** the "Injured Baby Bird" ESL kids animation,
`f32ed182-be1f-4a24-a8de-bb8db4ac88df` (Ryan's tenant `ee93e6d1-…`).
Modeled from a reference link, Kie-only stack (Claude gateway, images, TTS,
video). Prod = systemd services from /home/clawd/projects/economy-fastforward
(auto via git push to main + pull; backend restart = kill -9 MainPID, it
hangs draining SSE). Dev repo = /home/clawd/economy-fastforward.

**State of the product right now (all live on storyengine.dev):**
- ONE-button guided flow: GuidedNextStep banner is the only primary CTA
  (always-watching task watcher, lock built in, failure cards). Storyboard
  tab = workspace: per-scene Redo pictures / Start scene over (auto-chains
  plan→pictures), per-board hover-X delete, drag-drop replace, Advanced ⋯
  menus. next-action.ts is the single decision table — add states THERE.
- Storyboard → final pictures: extraction crops with the generation-time
  layout (grid_layout_for), per-scene resume, runs AUTOMATICALLY at Lock
  Story (silent plumbing). 86/86 panels extracted for the bird video.
- Animatic: per-scene "Watch this scene" player (panels + narration,
  word-proportional timing, $0). All 8 scenes verified playing.
- Dialogue intelligence (NEW): scripts auto-tagged into narrator/dialogue
  timelines (videos.dialogue_mode, scripts.dialogue_segments jsonb,
  video_characters.voice_name). Bird video: 65 dialogue lines, voices cast.
  Trigger: POST /api/videos/{id}/script/tag-dialogue (auto-hook after
  modeled script stage only — non-modeled path NOT hooked yet).
- Lip test PASSED: `lisa-dialogue-test.mp4` in the video's Drive folder =
  Grok image-to-video speaking clip + ElevenLabs voice mux. The approved
  recipe: ElevenLabs character voices + Grok lip movement, narrator pauses
  during dialogue (decisions.md 2026-06-12).

**NEXT BUILDS (approved plan, in order — (a) DONE 2026-06-12 pt 7; clips UX
contract locked in decisions.md "Video Clips stage UX contract"):**
a. Per-segment voice synthesis (Kie ElevenLabs, voice ID param; narrator
   voice for narration segs, video_characters.voice_name for dialogue) →
   {video}/voice/S{n}-seg{i}.mp3, audio_url+duration into the jsonb.
b. Animatic plays the segment timeline (radio-play rehearsal, $0) — Ryan
   approves the rhythm here before clip spend.
c. Grok clip pipeline: grok-imagine/image-to-video (duration is a STRING
   "6"–"30", 480p/720p, ~$0.05–0.12/clip, resultJson is a JSON string,
   URLs expire 24h, always has own audio → mute & overlay ElevenLabs).
   Clean [KFn|MS|10s] label bars off panels FIRST (Grok reproduces them).
d. Per-scene "Animate this scene" button (clips beside boards, scene gate)
   → bulk animate with cost confirm (~$2-4/video on Grok vs $6-12 Veo).
e. Render: Remotion segment timeline (narration pauses ↔ dialogue clips).
f. Hook tag-dialogue into the non-modeled script path; audition Tom's
   voice (current 'Mark' is adult; Finn vBKc2FfBKJfcZNyEt1n6 is the boy).

**Read before coding:** tasks/lessons.md (top 4 sections are this thread's
hard-won traps: Drive HTML interstitials, env-loading order, watcher races,
Kie quirks), tasks/decisions.md (dialogue decisions), docs/ + CLAUDE.md
wiring protocol. Session history below.

## Handoff (2026-06-12 pt 11 — vision rerouted + canary live)

The morning's dead Kie Claude vision REVERTED on its own (12/12 repro calls
fine by evening) — classic provider drift, so the fix is structural:
- `shared/clients/vision_client.py`: ALL product vision goes through one
  provider chain (Kie Gemini 2.5 Flash with per-call ingestion proof →
  Kie Claude → direct Anthropic). 9 unit tests.
- Rerouted: model_video thumbnail pass (now a separate vision pass whose
  observation is injected into the pack prompt as TEXT — generation never
  carries an image block), storyboard `_grid_style_matches_reference`,
  characters approve-cast rewrite.
- `canaries/vision_drift.py` hourly USER systemd timer (no root; linger on)
  + ntfy alert (same topic as validator canary). Known image: red circle on
  blue at Supabase `assets/<tenant>/canary/vision_canary.png` (~$1.5/mo).
- NOT migrated (legacy YouTube pipeline, direct Anthropic SDK):
  autopilot/analysis/thumbnail_analyzer.py, video_dispatch/verify_output.py.

## Handoff (2026-06-12 pt 7 — clips UX contract locked + per-segment voice SHIPPED)

Ryan answered 8 design questions for the clips stage (full contract appended to
decisions.md as "Video Clips stage UX contract" — read it before touching the
clips tab). Headlines: three-rung trust ladder (card tap ~$0.10 → "Animate this
scene" → banner-gated "Animate everything"), Generate Prompts button dies
(prompts auto-run silently), ALL segments get clips, 💬+name badge on dialogue
cards, voice auto-chain on tap, cost confirm >$0.50 only, play-inline +
hover Redo/X on cards, strip + ⋯ Advanced replaces all six header surfaces.
Found during recon: VideoClipsTab cost is fake (86×$0.30 hardcoded = $25.80;
Grok is ~$0.10/6s → ~$8.60), the model dropdown writes videos.video_model but
the BACKEND IGNORES IT (Grok hardcoded in image_client.py:704-785), and no
single-clip endpoint exists at all — both get wired during the clips build.

STEP (a) PER-SEGMENT VOICE SYNTHESIS SHIPPED:
- backend/dialogue_voice.py: walks scripts.dialogue_segments; narrator voice
  (scripts.voice_id) for narration, video_characters.voice_name for dialogue
  (stability .45 / style .2 / speed 1.05 — client gained style+speed params),
  uploads {video}/voice/S{n}-seg{i}.mp3 via storage.upload_bytes, writes
  audio_url + duration (+voice_name) into the jsonb AFTER EVERY segment
  (resume-safe), 3 attempts/segment with 5s backoff (Kie TTS flakes
  "internal error" transiently — hit twice live), cooperative cancel.
- executor.run_dialogue_voice (auto-tags untagged videos first; narration-only
  videos complete as a no-op) + silent auto-hook after full voice runs for
  dialogue-mode videos + POST /api/pipeline/dialogue-voice/{video_id}?scene=N.
- 6 functional tests: tests/functional/test_dialogue_voice.py (module-stub
  pattern, zero network) — voice routing, resume skip, per-segment persist,
  cancel-keeps-work, scene filter, helpers.
- Bird video live: scene 1 verified (14/14 voiced; real MPEG bytes pulled via
  authorized Drive API; header duration == db duration; 19.4s timeline).
  Tom RECAST Mark→Finn (his cast voice was IDENTICAL to the narrator —
  cast_character_voices now excludes the narrator's voice from the roster);
  scripts.voice_id was an off-roster id, set to Mark explicitly. Full 8-scene
  run (158 segs, ~$1-2 TTS) launched in background — check segment counts via
  scripts.dialogue_segments before building (b).

CLIPS TAB REBUILT same session (the UX contract is now LIVE code):
- POST /api/pipeline/clip/{video_id}?asset_id=&scene=&force= — ONE endpoint
  for all three rungs (tap a card / Animate this scene / Animate everything);
  executor.run_clip_generation honors videos.video_model via MODEL_REGISTRY
  (grok + veo-3.1 fast/quality wired; others rejected with friendly copy),
  proxies panel images via PUBLIC_MEDIA_BASE/api/media/drive/{id} for Kie,
  downloads clips IMMEDIATELY (24h URL expiry) → Drive {video}/clips/
  S{nn}-{ii}.mp4 → assets.video_clip_url, semaphore(3), cancel support,
  full-run-complete advances to ready_for_thumbnail.
- GET /api/videos/{id}/dialogue-map (💬 badges), DELETE /api/videos/{id}/
  clips/{asset_id} (hover-X: clears column + trashes Drive copy).
- VideoClipsTab rebuilt: status strip + ⋯ Advanced (model picker with real
  prices, coming-soon disabled, re-run prompts, motion instructions toggle);
  scene groups with "Animate this scene · $X"; tap card = animate (~$0.10,
  no confirm), tap done card = play inline; hover Redo/X; failed = red Try
  again; 💬 speaker badges via dialogue-map substring match; motion prompts
  AUTO-RUN silently on arrival (promptlessCount guard); confirms only >$0.50.
- next-action.ts: clips trust ladder (Animate scene 1 → Animate the rest →
  thumbnail) + clipCost()/CLIP_COST_PER_MODEL as the single price source;
  GuidedNextStep passes clipsDone/clipsTotal. Old Generate Prompts/Generate
  All Clips/Advance Stage/visible dropdown/always-on prompt editor all gone.

VERIFIED LIVE ON PROD (Playwright + API, Ryan's tenant):
- Tap → $0.10 Grok clip → Drive {video}/clips/S01-01.mp4 → assets row →
  plays via media proxy (frames eyeballed: on-model Pixar Tom, real motion).
- Tab renders: "1 of 86 pictures animated · ≈ $8.50 · Grok Imagine", 8 scene
  buttons, 34 💬 badges, real card pictures, zero old surfaces, banner shows
  "Animate the rest". Console clean on warm backend (cold-start 502s are
  transient, see lessons).
- THREE live bugs found+fixed en route: assets column is duration_seconds;
  clip gate + banner keyed on lagging status strings (bird video =
  ready_for_images with 86/86 finals); GET /api/videos/{id} SELECTed
  story_locked_at but never passed it to VideoDetail → banner re-offered
  Lock forever (one-line constructor fix).

STEP (c) DIALOGUE SPEAKING CLIPS SHIPPED (same day, Ryan: "S1.2 got no
dialogue — fix"): backend/clip_dialogue.py — norm/match_lines pairs a card's
sentence_text with the scene's tagged dialogue lines (same containment logic
as the frontend 💬 badge), speaking_prompt() directs Grok lip movement,
mux_voice() replaces Grok's invented audio with the segment's ElevenLabs
line(s) via ffmpeg (concat for multi-line cards), strip_audio() silences
narration clips (renderer narrates over them). run_clip_generation now:
speaking cards get the speaking prompt + a clip long enough for the line +
the voice muxed in; unvoiced scenes auto-chain run_dialogue_voice first
(contract Q5); mux failures keep the raw clip with a logged warning.
3 functional tests incl. a REAL ffmpeg mux round-trip.
ALSO fixed: NULL duration_seconds rows crashed the whole video-scripts run
('.get(key, default)' ≠ NULL-safe — see lessons); clips tab switched to the
always-on useTaskWatcher (purple progress pill shows ANY running task, taps
during a run explain what's running instead of a bare 409).

LIP-SYNC, FINAL FORM (Ryan: "way off the other direction — research how
people actually do this", then "the BOY's lips moved with Lisa's line"):
dialogue clips are AUDIO-DRIVEN PORTRAIT CUT-INS. 💬 cards →
image_client.generate_talking_video (Kie `infinitalk/from-audio`: the
SPEAKER'S APPROVED PORTRAIT (video_characters.reference_url) + segment
ElevenLabs mp3 via media-proxy URLs + who-speaks prompt → talking clip,
length = audio length, $0.015/s ≈ $0.03-0.05/line, 7-10 min/clip, poll
budget 15 min). Why portrait not panel: on multi-character panels the
model animates the MOST PROMINENT face (Tom mouthed Lisa's line — Ryan
caught it watching; my still-frame check had called it wrong). Portrait =
one subject = can't miss + deterministic + the approved lip-test recipe.
Verified live on S2.1: Lisa alone, articulating, $0.03. Fallback: full
panel when speaker has no portrait (logged warning). Vision onset
detection + mux + speaker-crop all RETIRED (git history); strip_audio
stays for narration clips. Multi-line cards: first line only.

⚠ DISCOVERED: CLAUDE-VIA-KIE VISION IS DEAD (gateway drift) — images
become /mnt-style file refs the model can't see (272 input tokens, no
image; haiku refuses, sonnet preambles then ends; URL and base64 both).
Likely silently degrading: model_video thumbnail style-DNA (modeled
videos!), storyboard vision QA loop, approve-cast description rewrite.
NEEDS ITS OWN INVESTIGATION + canary. _call_claude now joins all text
blocks (content[0] truncated multi-block replies).

NEXT: (b) animatic plays the segment timeline (radio-play rehearsal, $0,
Ryan approves rhythm here); (e) render: Remotion segment timeline
(narration pauses ↔ dialogue cut-ins as inserts); (f) hook tag-dialogue
into the non-modeled script path.

## Handoff (2026-06-12 pt 6 — dialogue intelligence SHIPPED, lip test PASSED)

Ryan greenlit the dialogue plan with decisions (recorded in decisions.md):
ElevenLabs character voices + Grok lips; narrator pauses; convert bird video
in place; everything must serve UNATTENDED channel automation (north-star,
also in agent memory).

DONE this session:
1. LIP TEST PASSED: Grok clip from Lisa's portrait — she visibly speaks
   (mouth movement, acting, leans to the bird Grok added from the prompt);
   muxed with a Kie/ElevenLabs line → `lisa-dialogue-test.mp4` in the bird
   video's Drive folder for Ryan to watch. Cost ~$0.06.
2. DIALOGUE INTELLIGENCE LIVE (dialogue_intelligence.py + migration 048):
   detect_dialogue_mode (whole script → character_dialogue|narration_only),
   segment_scene (ordered narrator/speaker timeline, attributions dropped,
   words verbatim, 60% retention sanity check), cast_character_voices
   (stable Kie ElevenLabs voice ID per character; curated 13-voice subset;
   full 67-voice enum + preview URLs in the session notes below).
   POST /api/videos/{id}/script/tag-dialogue + auto-hook after modeled
   script stage (best-effort). Bird video: character_dialogue, 8 scenes,
   65 dialogue lines, cast: Tom=Mark, Lisa=Brittney, Mom=Tiffany, Dad=Brian,
   Dr. May=Bella, Baby Bird=Emma. (Audit: Tom's 'Mark' is an adult voice —
   audition via https://static.aiquickdraw.com/elevenlabs/voice/<id>.mp3,
   Finn vBKc2FfBKJfcZNyEt1n6 is the boy option.)
3. Kie ElevenLabs API facts: voice param takes the ID (names rejected),
   input {text<=5000, voice, stability .45, style .2, speed 1.05 reads
   younger}; do NOT send language_code on multilingual-v2.

NEXT (in order, per the approved plan):
a. Per-segment voice synthesis: walk dialogue_segments, TTS each segment
   (narrator voice for narration, character voice_name for dialogue) via Kie,
   upload {video}/voice/S{n}-seg{i}.mp3, write audio_url+duration into the
   jsonb. Executor stage + banner progress.
b. Animatic plays the new timeline (radio-play rehearsal, $0).
c. Grok clip client in the pipeline (grok-imagine/image-to-video, duration
   STRING, mux ElevenLabs line over dialogue clips, label-bar cleanup first).
d. Per-scene "Animate this scene" + scene-gate + bulk with cost confirm.
e. Render: Remotion timeline with narration pauses + dialogue clip audio.
f. Auto-hook the NON-modeled script path too (only modeled path hooked now).

## Handoff (2026-06-12 pt 5 — extraction geometry fix, upscale policy wall, dialogue-clips plan)

Ryan: scene 2 animatic showed 3-panels-in-one and didn't rotate; scenes 7/8 had
no player; 82/85 mystery. All fixed + verified (Playwright: 8/8 players, S2
plays 6 single panels, audio rolling):
1. EXTRACTION GEOMETRY: extraction.py guessed grid layout from dark-band pixel
   detection; scene 2's 2x3 grid was misread → full-row composite crops, 3
   empty slots. Fix: `grid_layout_for(panel_count)` (mirrors bot._grid_layout),
   executor chunks scene slots 9-per-beat and passes exact rows/cols; detection
   is fallback only. Scene 2 re-extracted → 6 clean panels.
2. PER-SCENE RESUME on extraction: scenes with all slots filled are skipped.
3. UPSCALE = POLICY WALL, not a bug: nano-banana-2 refuses to regenerate
   images of CHILDREN (Google Prohibited Use policy) — all 82 upscales filtered,
   0 credits, ~40 min wasted. Auto-upscale now DISABLED (EXTRACT_AUTO_UPSCALE
   env to re-enable). Needs an ESRGAN-class non-generative upscaler on Kie for
   stills; clips path makes stills less critical.
4. AnimaticPlayer: never unmounts on audio error; retries once with fresh
   token (5-min TTL — players outlive it). Root cause of the missing 7/8
   players was the pre-fix HTML audio killing the component at mount.
5. Known warts for the clips phase: some panels keep their [KFn|MS|10s] label
   bar (white-on-black text defeats the brightness>100 trim scan — fix before
   clips, Grok will reproduce labels from reference); scene 2 gained a 6th
   slot with no sentence_text (executor inserts rows for extra real panels).
6. DB env gotcha: load backend/.env BEFORE root .env in scripts — root has a
   dead DATABASE_URL and the legacy Drive parent.

DIALOGUE-CLIPS PLAN written and reported to Ryan (NOT built — awaiting his
sign-off on: Grok-native vs ElevenLabs character voices for dialogue;
narration pauses vs ducks during dialogue; convert bird script in place).

## Handoff (2026-06-12 pt 4 — animatic player, silent extraction, dead audio fix, Grok Imagine validated)

Ryan: voice player dead on the storyboard page; extraction should be invisible
("do it in the background"); build the animatic player; switch clips to Grok
Imagine (cheaper) — research what Kie expects. All done except the Grok pipeline
wiring (researched + smoke-tested, integration is THE next build):
1. DEAD AUDIO, two root causes: (a) SecureAudioPlayer guessed
   `https://<host>:8001` for the API (unreachable port in prod); (b) the backend
   audio proxy streamed Drive PUBLIC links → HTML interstitial served as
   "200 audio/mpeg" — players sat at 0:00/0:00. Fixed: API_URL from env +
   authorized Drive API download (same as routes/media.py). Verified: real
   ID3/MPEG bytes, Playwright played scene 1 to 6.7s/28.7s.
2. ANIMATIC PLAYER (AnimaticPlayer.tsx): per-scene $0 preview — final pictures
   under the scene's narration, per-panel duration = sentence word-count share,
   caption overlay, progress bar, panel counter. Mounted on scene cards when
   finals exist; falls back to plain voice player until then. Live: 8 players.
3. SILENT EXTRACTION: Lock Story now auto-starts storyboard-extract (banner
   shows progress; visible step remains only as failure recovery, relabeled
   "Finish making your pictures"). next-action gained finalsMissing guard:
   clips step can never show for a video with 0 finals (the skip-trap Ryan
   screenshotted). Bird video: locked + extracted in background → 82/85 panels
   (3 slots skipped as blank boards — per-segment regen exists in scene
   details if they matter). Upscale ran but no _hd URLs recorded — check
   whether upscale writes in place now (cache fix makes that fine) or skipped.
4. GROK IMAGINE (clips at ~1/6 the cost) — researched on Kie docs + LIVE
   smoke test: model `grok-imagine/image-to-video`, same jobs API
   (createTask/recordInfo), input {image_urls:[proxy URL], prompt, mode:
   "normal", duration:"6"–"30" STRING, resolution:"480p"|"720p"}. Test clip
   from real S1 panel: $0.048, 31s generation, on-model Pixar look, real story
   beat (Tom kneels to the bird). 720p ≈ $0.09–0.12/clip vs Veo Fast $0.30
   (video drops $6–12 → ~$2–4). NO start/end-frame support (Veo keeps that);
   audio always baked in (strip/duck under narration); result URLs expire 24h
   (download immediately); resultJson is a JSON STRING with resultUrls.
   Veo 3.1 Lite ($0.15 flat) is the middle option.

NEXT BUILD (agreed direction): per-scene "Animate this scene" button (clips
appear beside the boards, scene 1 = motion taste-test gate before bulk run),
clip model selector defaulting to grok-imagine/image-to-video, motion presets
by shot type (LS=push-in, ECU=parallax, etc.), then bulk "animate everything".

## Handoff (2026-06-12 pt 3 — ONE-button consolidation of the pipeline page)

Ryan (with screenshot): the storyboard stage had FOUR competing "what now" surfaces
(header Run Next Step/Skip Stage, the guided banner, an 8-button action bar, a
4-step tracker with its own giant CTA) — "consolidate to one button, Apple-esque,
grandma-proof, regeneration lives on the scene cards." Shipped + verified on prod
(Playwright: every old surface gone, exactly one Next-up banner, 0 console errors):
1. GuidedNextStep banner = THE button. New `useTaskWatcher` (use-task-poller.ts)
   watches the video's task slot CONTINUOUSLY → progress + Stop appear in the
   banner no matter which control started the work. Lock Story is now executed BY
   the banner (gold button, kind "lock", zero-board guard in next-action.ts).
   Watcher fires onComplete/onFailed only on live-observed transitions
   (wasRunningRef) + epoch guard so in-flight polls can't misfire after markStarted.
2. Header: Run-next/Skip/Reset/Export → one ⋯ menu. Stepper passive.
3. Storyboard tab: stats row, action bar, tracker, toggle, inline progress banner
   all deleted. One status strip ("8 scenes · 12 of 12 boards" + Unlock when
   locked + ⋯ Advanced: model, upscale, delete finals, re-extract missing,
   start over, skip stage). Scene cards: "Plan this scene" / "Draw the pictures" /
   "Redo pictures" (slot-clears then regen, plan kept) / "Start scene over" which
   AUTO-CHAINS plan→pictures via chainRef consumed in watcher onComplete — the old
   clear-wipes-prompts dead end is gone. Stop dispatches `se:stop-requested` so
   pending chain stages stand down (cancelled reads as completed to pollers).
4. Adversarial review workflow ran (21 agents; verify phase partially hit session
   limits — self-verified the flagged races): fixed stale failure card, zero-board
   lock, menu outside-click close, watcher poll race, chain-409 retry, duplicate
   failure toasts, jargon (Final pictures / picture plans), dead computed values.
Playwright note: headless verification of prod needs /api/auth/me stubbed via
route interception (instant fulfill) — the mount-time /me fetch gets ERR_ABORTED
under headless; everything after auth proxies fine (see /tmp/verify_final.py pattern).
Known minor (documented, not fixed): banner may flicker idle for ≤3s between chain
stages (two watcher instances); switching tabs mid-chain drops the queued stage
(banner self-heals: next action becomes "Finish your storyboard").

Bird video remains: review boards → Lock the story (now the one gold button) →
Create the final pictures.

## Handoff (2026-06-12 pt 2 — per-board X delete, drop-to-replace, stale cache fix)

Ryan: "Drive images aren't what's on screen; no clean way to delete ONE storyboard
image without losing prompts; want to drag Drive images onto a board." All three done:
1. STALE SCREEN: boards regenerate IN PLACE on Drive (same file id) but the media
   proxy said max-age=86400 immutable → browser showed yesterday's pixels for a day.
   Proxy now: ETag = Drive md5Checksum, Cache-Control public no-cache, If-None-Match
   → 304 without download. Verified live (200 + md5 etag, 304 on revalidate).
   → Ryan: a hard refresh once and from then on boards are always current.
2. PER-BOARD X: DELETE /api/videos/{id}/storyboards/{scene}/{beat} clears ONE slot,
   keeps prompts + other boards, trashes the Drive copy (folder matches screen),
   guards scene status (only downgrades grids_generated→prompts_ready for in-range
   beats). Hover X on every filled board card. Bot's per-beat resume skip means
   "create storyboard" after an X only regenerates the missing slot (~$0.07).
3. DROP-TO-REPLACE: drag-drop existed but was invisible (replace-in-place + cached
   URL = nothing seemed to happen). Now: "Drop to replace this picture" overlay,
   uploads land in {video}/storyboard/S{n}-B{m}.png (replaces bot grid in place,
   was orphan grids/ folder), cache-busted <img> after upload, success/error toasts.
   Per-scene Clear confirm now warns it's a FULL redo and points at the X.
Also: trashed empty duplicate Drive video folder (created by a root-.env diagnostic
script — see lessons). Full cycle (upload→proxy-serve→X-delete→Drive-trash) verified
on prod against the bird video's unused slot 5. Tests 5/5 + 7/7, tsc clean.

Bird video remains: review boards → Lock Story → Create final pictures.

## Handoff (2026-06-12 — style drift root causes + vision QA loop)

Ryan: "scene styles still don't match, stale extracted images showing, last scene has
three of the same images." All three fixed + verified by eye:
1. STALE EXTRACTED: 74 pre-storyboard asset images (image_url set, never extracted)
   showed in the Extracted Panels section. Cleared (image_url/drive_image_url NULL,
   status pending). Drive files remain in the library.
2. DUPLICATE PANELS: the director template's HERO BEAT EXPANSION explicitly asked for
   sub-shots showing "the SAME subject — don't change what's shown" (3 crayon panels,
   4 chair holds). Rules now demand visually distinct panels / fewer keyframes + blanks.
3. STYLE DRIFT (2D/photoreal mixed with 3D): two layers —
   a. Template preamble HARDCODED "Cinematic 2D animated illustration..." (the April
      never-hardcode-style lesson again). Now interpolates profile.visual_style_directive
      (= the video's Image Style Override).
   b. Even with correct prompts everywhere, nano-banana-pro stochastically rendered
      photoreal ~1 in 4-12 grids. Instructions can't fix randomness → added a vision
      QA loop: every reference-conditioned grid is compared to the cast sheet
      (Haiku via Kie) and regenerated once on mismatch. Caught a live drift on its
      first run.
KIE CLAUDE VISION GATEWAY QUIRKS (calibrated live, see bot._grid_style_matches_reference):
   URL image sources unreliable, assistant prefill IGNORED, small max_tokens IGNORED
   on vision calls → use base64 images + parse a 'FINAL: YES/NO' closing line.
Bird video: 12/12 boards now style-consistent (audited via the calibrated checker +
eyeballed S1/S5/S8). Ready for review → Lock Story.

## Handoff (2026-06-11 pt 4 — character consistency: labeled cast sheet)

Ryan: "character styles are all over the place in the boards." Root causes + fixes:
1. SIX separate portrait refs in image_input dilute each other — model can't map
   names to faces. FIX: approve_cast composes ONE labeled cast sheet (PIL, portrait
   + name per tile) -> videos.character_reference_url; executor passes it as the
   single reference; generate_contact_sheet prompt says "match these EXACT labeled
   characters."
2. Story Bible character text diverged from approved portraits (text fought image).
   FIX: approval syncs bible descriptions to the cast.
3. Stored descriptions described what portraits were generated FROM, not what they
   show (gen takes liberties: "light blue tee" -> red). FIX: vision pass at approval
   rewrites each description from the actual portrait pixels.
Result (visually verified): all 13 boards across 8 scenes now share one cast —
same Tom/Lisa/Mom/Dad/Dr. May in every panel. Boards ready for Ryan to review+lock.
Note: per-scene storyboard CLEAR also wipes that scene's prompts — regen prompts
before grids (bit Ryan on scene 4, me on scene 1; worth auto-chaining later).
Also this session: media proxy (/api/media/drive/{id}) replaced Supabase serving
copies — Supabase bucket purged (92 objects), Drive is sole media store.

## Handoff (2026-06-11 pt 3 — grandma-proof guided flow + storage reliability)

Ryan's storyboard run silently failed + "UI is confusing, needs next-next-next."

Root causes found & fixed:
1. Kie rejected character refs ('image_input file type not supported') — the stored
   drive.google.com URLs had degraded into HTML interstitials (even lh3 CDN form).
   FIX: dual persistence — Drive stays the organized library, Supabase Storage is the
   serving copy and the URL we store (storage.py drive branch). Public 'assets' bucket
   created. Bird video backfilled (6 portraits + grids + 74 images) via authorized
   Drive download.
2. generate_with_reference poll budget was 120s; multi-ref grids take 2-4 min →
   silent 'returned None'. Budget now 450s. Misleading "$0.07 so far" log on failure
   still exists (bot.py increments cost before checking result) — minor, open.
3. Bird video storyboard now COMPLETE: 12 grids across 8 scenes (scene 4 was deleted
   by Ryan mid-debug; regenerated per-scene). Story still UNLOCKED — Ryan reviews
   boards → Lock → Create final pictures.

Guided UX (from 7-agent audit + synthesis, full report in workflow output):
- lib/next-action.ts: getNextAction() decision table → ONE plain-English next action
  per state (label, cost, tab, step N of 10).
- GuidedNextStep banner on the video page: big single CTA, live progress + Stop,
  PERSISTENT failure card with Try Again (replaces 6s toasts).
- Tabs renumbered 1·Research … 10·Results; storyboard tab buttons in plain English.

UX backlog (synthesis items not yet built): Advanced overflow menus per tab (hide
Reset/Skip/Upscale), disabled-button reason captions, per-segment failed badges with
"Fix missing pictures (N)", tab lock icons for not-ready tabs, cost-confirm pattern
for every >$0.50 action, stepper/pill unification via STATUS_LABELS. Full decision
table + per-tab hierarchy in the uiux-map workflow output.

## Handoff (2026-06-11 pt 2 — Drive consolidated under RAD Creations/Projects/Storyengine)

Everything now lives in ONE tree (Ryan's requested layout):
  Storyengine/<video title>/{characters/, storyboard/, images/} + scripts/voice/briefs in root.
- StoryEngine backend GOOGLE_DRIVE_FOLDER_ID redirected to the Storyengine folder
  (old value in storyengine/.env.bak-20260611). google_client folder lookups are now
  parent-scoped (global name search would have resurrected old folders / collided on
  generic subfolder names). Path routing: scene images + extracted panels -> images/,
  grids -> storyboard/, portraits -> characters/.
- Migrations executed (file ids unchanged, all stored URLs intact): both video folders
  moved + internally sorted; legacy 'StoryEngine Assets' uuid tree emptied + trashed;
  the legacy Power Doctrine pipeline's 'Economy Fastforward' folder moved WHOLESALE
  under Storyengine — its folder id is unchanged so the root .env and all existing
  links keep working without modification.
- Frontend renders Drive images via lh3.googleusercontent.com CDN (toDisplayImageUrl)
  since uc?export=download links don't load in <img> tags.

## Handoff (2026-06-11 — Creator Control Run shipped: Stop, Characters, Story Lock)

All three phases of docs/superpowers/specs/2026-06-10-creator-control-run.md are LIVE:
- Stop button on Visuals/Clips/Storyboard/Voice tabs; cooperative cancel keeps paid
  work, stage re-run resumes. Live-verified twice (grids stopped mid-run; a found
  cancel-eaten race + stale-clear race fixed and re-verified with a 3s cancel).
- Characters tab between Script and Storyboard: design cast → 6/6 portraits generated
  live for the bird video (Tom, Lisa, Mom, Dad, Dr. May, Baby Bird), approve gate
  blocks grids/images until approved (verified live), cast saved to project.
- Mandatory storyboard: storyboard_on_off defaults On, toggle replaced with REQUIRED
  badge, Lock Story (needs ≥1 reviewed grid) gates full image runs + extraction
  (both refusals verified live), unlock-story to iterate.
- Adversarial review pre-deploy: 11 claims refuted, 2 confirmed + fixed (cancel
  endpoint was blocked by the concurrent-job limiter; schema.sql missing
  video_characters RLS).

### Bird video state (f32ed182) — heads up
During live testing a cancel race let an image run complete: the video now sits at
ready_for_sound_design with 74 generated images (~$1.85, styled by the modeled
Pixar DNA — review them, they're likely usable). Cast is approved + saved to the
project; scene 1 has a storyboard grid; story is UNLOCKED. For a clean full-flow
test of the new gates, model a fresh video: script → Characters tab → approve →
grids → redo boards → Lock Story → Extract.

### Open items
1. Storyboard grid generation is not yet blocked AFTER lock (only images/extract are
   gated) — locking then regenerating boards is possible; unlock-to-iterate is the
   official path. Consider gating grids post-lock or auto-unlocking on grid regen.
2. Stale 'running' background_tasks rows accumulate when a task's terminal write
   misses (cleaned by recover_stale_tasks on restart) — they inflate the concurrent-
   job count between restarts.
3. voice_duration_seconds still not recorded in Kie voice mode (word-count fallback).
4. Characters tab does not auto-resume polling if the page reloads mid-design
   (background task continues; refresh shows the finished cast).

## Handoff (2026-06-10 pt 4 — voice via Kie + full click-path to ready_for_images)

Ryan: "voice uses kie as well." Shipped + verified live on the bird video (f32ed182):
- ElevenLabsClient Kie gateway mode: createTask/recordInfo jobs against
  elevenlabs/text-to-speech-multilingual-v2 (SoundClient pattern). Kie only accepts
  its OWN voice roster — off-roster ids rejected with "not within the range of
  allowed options"; falls back to "Mark" (1SM7GgM6IMuvQlz2BwM3) with a logged warning.
  Kie.ai is now the ONLY required pipeline key (anthropic + elevenlabs both optional).
- Voice click: 8/8 scenes voiced via Kie, audio in Drive. NOTE: voice_duration_seconds
  not recorded in Kie mode (engine falls back to word-count timing) — worth fixing.
- Prompts click first produced ZERO prompts: the modeled concept asset rows carry
  image_prompt values, so the engine's resume logic saw all scenes "completed."
  Fixed: full prompt runs on modeled videos clear generation_method='modeled' rows
  first (pack stays archived in original_dna). Re-run: 74 prompts across 8 scenes,
  ALL carrying the animation style (image_style_override active in the engine log).
- Current state: f32ed182 at ready_for_images with 74 styled prompts. Next click
  (Images) costs ~$1.85 kie credit + clips after — left for Ryan per cost rules.
- Watch items: prompts came out "2D animated illustration" (profile prefix blends
  with the 3D-Pixar override — consider selecting visual profile from the modeled
  DNA); story_bible column empty though the engine generated one in-run.
## Handoff (2026-06-10 pt 3 — replicate mode shipped + modeled script path)

Ryan's correction: Model A Video must REPLICATE the dropped-in video (same genre/
style/audience, sibling topic), NOT adapt it to his channel. Shipped + verified on
his video f32ed182 (ESL turtle reference fVdj037FNYI):
- Pack prompt rewritten to replicate-mode, channel profile removed, reference
  thumbnail attached as vision input. Result: "🐦😱 What Should We Do To Help The
  Injured Baby Bird? | Easy English Listening for Beginners (A2 Level)" + image DNA
  "3D Pixar/Disney CG animation style..." (observed from the thumbnail).
- New `script_dna` → `videos.script_system_prompt`; `pipeline_executor.run_script`
  branches for source='modeled' → `_run_modeled_script` (direct generation in the
  reference's style, 8 scene rows, documentary validation skipped). Verified: script
  opens "Look! A baby bird is on the ground. It cannot fly. What should we do?" —
  8 scenes, ready_for_voice.
- Click path verified end-to-end through script. Voice is next and needs Ryan's
  ElevenLabs key; then images/clips run on kie credit via existing buttons (the
  image prompts stage should honor image_style_override — NOT yet verified live,
  next test after voice).

## Handoff (2026-06-10 pt 2 — Kie-routed Claude + modeled click-through path)

Ryan's goal: paste link → modeled title/script/image DNA/video DNA → click through to a
similar finished video. Shipped and verified live on his video f32ed182 (tenant ee93e6d1):

- **All Claude calls via Kie.ai** (his directive). model_video routes kie-first; the
  PIPELINE bots too: `AnthropicClient` gateway mode via `ANTHROPIC_BASE_URL`
  (set by pipeline_executor when tenant has kie key but no anthropic key).
  Gateway traps found live: Bearer auth (SDK `auth_token`), Kie WAF blocks the SDK
  User-Agent (override it), dated model ids 422 (normalize to undated aliases),
  server-side web_search tools not executed (stripped in gateway mode), and **Kie 500s
  any non-streaming response taking >~110s — gateway mode must STREAM** (12/12 research
  calls failed non-streaming; identical call streams fine).
- **Modeled DNA steers downstream stages** via existing channels: writer_guidance
  (script), image_style_override (image prompts), thumbnail_style_override (thumbnail),
  video_motion_system_prompt (clip prompts). Pack prompt outputs explicit
  image_dna/motion_dna/thumbnail_dna. Full pack archived in original_dna (research
  stage overwrites research_payload by design). video_length_minutes now set from
  reference duration (script gen refuses to run without it).
- **Bug fixes en route:** psycopg2 UUID adapter registered in supabase_adapter
  (research save crashed: "can't adapt type 'UUID'"); rate limiter 429-storm fixed
  (read tenants.plan instead of accounts+trial → trial users got free-tier 15/min;
  also free floor now 60/min, both plan-name generations mapped).
- **Verified click-path on prod DB:** Model → idea+DNA ✓ → Research click (41KB
  payload, Kie-streamed, ~4min) ✓ → Script click (11.7KB script, editorial validation
  PASSED, ready_for_voice) ✓. Voice is the next click and needs Ryan's ElevenLabs key
  (BYOK) — that's where it correctly stops today.

### Open items
1. Ryan must add his ElevenLabs key (Settings → Keys) for voice; then images/clips run
   on his kie credit via existing buttons.
2. Script stage produced ONE scripts row holding the whole script (scene=1). Pre-existing
   script-stage behavior, not modeling-specific — verify voice/image stages handle it,
   or whether 6-scene splitting should happen here.
3. yt-dlp cookies support merged (PR #456): export YouTube cookies to
   ~/.config/storyengine/youtube_cookies.txt to unlock transcripts.
4. Other storyengine routes (learn-voice, suggest-titles, distiller) still anthropic-direct
   — task chip open ("Route all backend Claude calls through Kie.ai", partially done:
   pipeline bots + model_video covered).

## Handoff (2026-06-10 — Model A Video shipped)

### What shipped
"Model A Video" Dashboard feature: button → modal (one field: YouTube URL) →
`POST /api/model-video` creates a tenant-scoped video row at `idea_logged` and runs a
background task (extract via yt-dlp with oEmbed fallback → style-DNA distill via Haiku →
new modeled idea + prompt pack via Sonnet → persist). Pack lands in: videos fields
(title/headline, thesis, writer_guidance, title_candidates, thumbnail_prompt,
original_dna, research_payload incl. 8 scene_concepts + blockers), 8 `assets` rows
(image_prompt + video_prompt, generation_method='modeled'), `competitor_videos`
attribution upsert (our_video_id, modeled_at), best-effort Drive markdown brief.
Progress polled via existing `/api/pipeline/task/{video_id}` + `useTaskPoller`.
Retry endpoint: `POST /api/model-video/{video_id}/retry`. No migration needed.

### Verified
- Backend functional tests 6/6 (`tests/functional/test_model_video.py`), humanization suite still green
- `tsc --noEmit` clean, `npm run build` passes
- Live E2E on VPS against real DB (disposable test tenant, cleaned up): full happy path
  with mock Claude endpoint (ANTHROPIC_API_URL override), real oEmbed fallback (yt-dlp is
  bot-blocked on this VPS IP — see lessons), plan-limit 402 enforced, 401 unauthenticated,
  invalid-URL 400, missing-key actionable error
- Playwright UI E2E: button → modal → validation → failed state w/ Retry → modeled video
  visible in Pipeline list + detail page

### Known gaps / follow-ups
1. ~~No live-Claude run~~ RESOLVED same-day: Ryan clarified Claude calls go through
   Kie.ai. model_video now resolves creds kie-first (`https://api.kie.ai/claude/v1/messages`,
   Bearer auth, `stream:false` required, models claude-sonnet-4-5 / claude-haiku-4-5,
   beware 200-with-error-body) with direct-Anthropic fallback. NOTE: the rest of the
   backend (distiller, learn-voice, suggest-titles, pipeline executor) still hits
   api.anthropic.com directly with anthropic_api_key — aligning those to Kie is open work.
2. yt-dlp is bot-blocked on the VPS IP ("Sign in to confirm you're not a bot") — oEmbed
   fallback covers title/channel/thumbnail, but transcripts won't extract until cookies
   or a different egress is configured. Affects competitor scraping too, worth its own fix.
3. Videos whose modeling failed keep the "Modeling a reference video…" placeholder title
   in Pipeline; retry from the modal fixes them, but a retry affordance on the video card
   would be nicer.

## Handoff (2026-04-19 — Osiris full-autonomy overnight ship mode started)

### Context
Ryan granted full-autonomy ship-while-sleep mandate (see `~/.claude/projects/-Users-osiris-claude-agent/memory/project_storyengine_full_autonomy.md`). Single-agent (Osiris) continuous builder, Karpathy build-test-learn loop, functional tests only (no smoke-test ship gate). Daily ship log at `storyengine/daily-ship-log-YYYY-MM-DD.md`.

### Completed this cycle
- **Trial-downgrade cron (fix-roadmap 3.2)** — migration 041, `send_trial_expired` email, `check_trial_expired` task, `_auto_check_trial_expired` wired in lifespan @ 6h interval. Functional test in `backend/tests/functional/test_trial_expired.sql` green against prod Supabase.
- **Humanize error strings (frontend)** — 11 raw-error leak sites routed through `humanizeError()`. Pages: login, forgot-password, reset-password, settings/drive-callback, settings/youtube-callback, system-prompts, profile, competitors. Components: CreateVideoStep, FirstVideoFlow, storyboard-viewer. `npx tsc --noEmit` clean. Users no longer see "API error 500" or "Failed to fetch".
- **Flow B slice 1 — existing-channel detection** — new `GET /api/youtube/my-videos` endpoint fetches user's top uploads via OAuth + uploads-playlist pattern. Frontend `YouTubeConnectStep` auto-fetches + renders "We found N top-performing videos on your channel" card after OAuth succeeds. Backend functional tests (4/4 ✅) including live contract check against googleapis.com.
- **Flow B slice 2 — voice auto-learn** — new `POST /api/youtube/learn-voice` endpoint: top-5 videos → Claude Sonnet 4 voice summarization → persists `channel_profiles.style_description`. **Reordered onboarding steps** to `channel → keys → youtube → style → video` so voice-learn can pre-fill the Style step. `StyleSetupStep` shows "We drafted this from your top YouTube videos" banner when pre-filled. Backend functional test `test_learn_voice.py` (3/3 ✅) including LIVE 401 contract test against api.anthropic.com. `npx tsc --noEmit` clean.
- **Grandma-mode override audit + script bot wired (Cycle 6)** — Cycle 1's "wiring in 7 places" claim was wrong. `test_prompt_override_wiring.py` (3 tests ✅) audits via runtime + static grep. Found 1/6 bots reading their override (video_motion only). Wired the `script` bot end-to-end: `script_generator.py` (`system_prompt_override` param → `anthropic_client.generate(system_prompt=...)`) + `brief_translator/__init__.py` (both `BriefTranslator.__init__` and `translate_brief` convenience func) + `script/run.py` (passes `getattr(pipeline, "script_system_prompt", None)`). 2/6 wired after Cycle 6.
- **All 6 bots wired (Cycle 7)** — completed the grandma-mode rollout. Thumbnail bot (3 Claude call sites via `ThumbnailTitleEngine` → `TitleGenerator` + `ThumbnailPromptBuilder`, wired in `thumbnail/run.py`). Sound bots (`SoundPromptBot` now takes both `sound_curation_` and `sound_generation_` overrides, wired in `sound/run_design.py`). Research bot (`ResearchAgent` + `run_research` take override, wired at SaaS executor boundary `pipeline_executor.py:run_research`). Audit test broadened regex to match `self._pipeline.<attr>`; CONSUMER_SPEC updated. **6/6 WIRED** with a full-loop regression guard asserting all 6 stay wired.
- **Backend error humanization (Cycle 8)** — new `storyengine/backend/error_utils.py` with `humanize_error(err, context=...)` mirror of frontend `src/lib/errors.ts`. Fixed 11 HTTPException leak sites across 6 customer-facing routes (visual_styles.py × 5, intelligence.py × 1, pipeline.py × 1, system_prompts.py × 1, youtube_channel.py × 1, videos.py × 1). Raw `str(e)` / upstream-API bodies no longer reach users; all get logged at WARNING with `[humanize_error]` prefix for dev grep. Functional test `test_error_humanization.py` (8/8 ✅) including static audit regex-scan that asserts 0 raw-error leaks across all 6 customer-facing route files — acts as a regression guard for any new route added later.
- **Background-task error humanization (Cycle 9)** — closed the leak surface flagged as Cycle 8's honest gap. `_set_task_status` in `routes/pipeline.py` now humanizes at the write boundary, covering all ~15 `str(e)` call sites in one change. `routes/agents.py` agent-pipeline run uses `humanize_error(e, context="The agent pipeline hit an error")` at both the in-memory `_set_task` and the `bot_activity` INSERT. Runtime test `test_set_task_status_humanizes_failure_errors` (via FastAPI-free module stubs) proves a raw `HTTPSConnectionPool(host='api.kie.ai'...)` input never leaks into `_running_tasks['error']`. Full suite: 9/9 green. Prompt-override wiring test still 6/6 WIRED.
- **Activity-feed humanization (Cycle 10)** — uncovered a third independent leak surface: `pipeline_executor._log_activity` writes `message` to `bot_activity` which `/api/activity` returns verbatim to the UI. ~20 call sites in `pipeline_executor.py` pass `error_msg = str(e)`. Fixed with a single-line funnel guard inside `_log_activity` (`humanize_error(message)` when status=="failed"). Also fixed `/orchestrator/decide` returning `reasoning=f"Orchestrator error: {e}"`. Static-grep test added. 10/10 tests green.
- **Orchestrator result humanization (Cycle 11)** — closed the 4th and last leak funnel flagged in Cycle 10's honest gap. `claude_orchestrator.ClaudeOrchestrator.execute` previously built `OrchestratorResult(error=str(e))` on exception; now runs through `humanize_error(e, context=f"Executing {decision.skill_id} hit an error")` so `/orchestrator/execute` callers never see raw stack text. 10/10 tests still green. Four leak surfaces, four cycles, one helper, zero API growth.
- **Transcript-based voice-learn (Cycle 12)** — upgraded `/api/youtube/learn-voice` (Flow B slice 2) from titles+descriptions to actual yt-dlp transcripts. New `_fetch_transcripts_for_videos` helper runs 5 concurrent yt-dlp fetches via `asyncio.gather(run_in_executor(...))` reusing `routes.niche._extract_video_info`. Silent per-video fallback (transcript → description → `(no description)`). `TRANSCRIPT_CHAR_CAP=2000` bounds per-video context cost. Response surface adds `transcript_count` + `has_transcript` per video so frontend can show signal strength. 4 new tests (mixed prompt path, silent-fail, char-cap, template-mentions-transcripts) + 3 existing = 7/7 green in `test_learn_voice.py`. Regression suites still clean (10/10 humanize, 6/6 override-wired).
- **UI signal-strength banner (Cycle 13)** — surfaced `transcript_count` from Cycle 12 into `StyleSetupStep.tsx` with three-state copy: "learned from N transcripts (+M descriptions)" / "learned from N descriptions — add captions for sharper voice learning" / generic fallback. `api.ts` + `onboarding/page.tsx` types+state plumbing. `npx tsc --noEmit` clean.
- **Prod deploy of Cycles 8-13 (Cycle 14)** — Ryan granted SSH to VPS (clawd@76.13.119.181). Stashed dirty runtime artifacts on `~/projects/economy-fastforward`, `git pull origin main` (19 commits behind), `pip install -q`, `npm install && npm run build`, `sudo systemctl restart` both services. Migration 041 auto-applied. storyengine.dev `/` + `/api/health` + `/onboarding` all 200. Ran both functional suites against live VPS env: `test_error_humanization.py` 10/10, `test_learn_voice.py` 7/7. First time tonight's work reached production.
- **Runtime E2E activity-feed audit (Cycle 15)** — `tests/functional/test_activity_feed_no_raw_errors.py`: two passive scans against live prod DB (`bot_activity.message` + `background_tasks.error_message` for 16 raw-exception signatures — HTTPSConnectionPool, Traceback, Errno, 6 Python exception types, 3 upstream API hostnames, Connection aborted/refused/reset) + a helper-pattern pin that guards against adding a pattern to the catalog the helper can't strip. 3/3 green on VPS: 87 failed bot_activity rows + 1 failed background_task scanned, zero leaks. Closes the "needs a live backend" honest-gap flagged in Cycles 8-11.
- **Kie.ai validator hotfix (live customer bug)** — Ryan hit "Saved but validation failed" on the TOOLS onboarding step. Root cause: `vault.test_api_key` called `api.kie.ai/api/v1/user/balance` which 404s (deprecated endpoint) AND Kie.ai uses the 200-OK-with-error-body pattern, so checking HTTP status alone would still be wrong. Fixed by switching to `/api/v1/chat/credit` + parsing `{code, msg, data}` body. Ryan's key was valid all along (4335.86 credit). Shipped as commit `a61a4d2e`, pulled+restarted on VPS, verified `test_api_key` returns `{'success': True, 'message': 'Kie.ai API key valid (credit: 4335.86)'}`. 35-min turnaround screenshot→fix-live.
- **ElevenLabs validator hotfix (Ryan 2nd report)** — Same bug class. `/v1/user` requires the `user_read` scope which Ryan's TTS-only key doesn't have. Fixed by switching to `/v1/voices` (the endpoint StoryEngine actually calls for voice-picker population) + parsed the 401 body to distinguish `invalid_api_key` from `missing_permissions` for an actionable error message. Shipped as commit `bfcc9b46`. Verified green on VPS. Principle: validate against endpoints we actually use, not "hello world" endpoints.
- **TOOLS step UI fix (Cycle 17)** — Ryan's "4 keys but only 3 to enter, no Continue button" report. ElevenLabs groups two backend keys into one visual card, but the progress counter/disabled gate was counting raw keys. Switched to provider-count semantics (`renderItems.length`, `every(configured)` per grouped provider). `ApiKeysStep.tsx` commit `946ea7aa`, shipped, browser-verified live — counter reads "2 of 3 connected" and button reads "Connect all 3 tools to continue" with coherent state.
- **Dashboard WelcomeQuest — the "huge win" (Cycle 18)** — closed the "no onboarding after keys" gap. New `components/dashboard/welcome-quest.tsx` renders a three-step quest panel (add competitors → distill first insight → create first video) above the dashboard's analytics widgets, visible only while `video_count === 0`, dismissible with localStorage persistence. Backend added a `first_run: {competitor_count, distilled_count, video_count}` block to `/api/dashboard/onboarding/status`. Commit `68b9ee9d`, both services restarted on VPS, browser-verified live with all three cards rendering "0 of 3 done" on a fresh account.
- **Intelligence-teaser strategy memo (Task #24)** — Ryan's "do we let them run a free pass to get hooked?" question. Wrote a strategy memo at `storyengine/notes/intelligence-teaser-strategy-2026-04-19.md`. Recommendation: don't build the StoryEngine-funded teaser yet. BYOK already gives us a near-free hook (user's own credits cost pennies, $0 to us). First ship the UX changes shipped tonight + add event tracking, measure dropoff for two weeks, THEN decide whether to spend engineering on a funded teaser targeted at the specific dropoff point.

### Next in queue (priority order)
1. First real end-to-end customer-style render (Ryan as dogfood) — proves live output variation between two overrides end-to-end. Task #11.
2. **Audit the other `test_api_key` branches for the 200-OK-with-error-body pattern** — Anthropic, OpenAI, Gemini, ElevenLabs, Tavily all check HTTP status only. Same bug class would hit all of them if any provider silently moves to 200+JSON-code style.
3. **Synthetic canary for upstream-validator drift** — hourly cron hits `test_api_key` against known-good keys for each provider, pages on regression. Catches endpoint deprecation (like the Kie.ai one) before users see "validation failed."
4. Live yt-dlp stability test against a stable public YouTube URL (catches version drift + YouTube anti-scrape changes).
5. Fresh fix-roadmap.md rewrite against ground truth (drop items already shipped).
6. Clean-replacement override semantics — when an override is present, also strip the profile-derived voice preamble from the user-prompt body. (Current v1: override lands as `system_prompt`, preamble still in user body → Claude blends.)
7. Hourly launchd/cron wrap of Cycle 15's audit — continuous surveillance instead of ad-hoc runs.
8. Bump pydantic + pyjwt to satisfy supabase lib requirements (noted as non-fatal warnings during Cycle 14 deploy).

### Open questions for Ryan
- **Override replacement semantics:** currently the tenant override lands as Claude's `system_prompt` while the profile-derived voice preamble still lives in the user-prompt body → Claude blends the two. Clean-replacement (skip profile preamble when override present) is a follow-up decision once we measure output variation end-to-end.
- **Python-layer test harness:** backend expects local PG proxy on :55432 that isn't running on this Mac. For functional Python tests (not just SQL), either start the proxy or write tests as VPS-executable scripts.

## Handoff (2026-04-14 — PRD 3 T5 Storage + Bug Triage)

### Completed
- PRD 3 T5: Extended `storyengine/backend/storage.py` with Supabase Storage backend
  - `STORAGE_BACKEND` env var: "google_drive" (default) or "supabase"
  - Per-tenant path isolation: `{tenant_id}/{video_id}/{filename}`
  - `create_signed_url()` for time-limited access
  - All 4 acceptance criteria pass
- Investigated 5 live user errors: all routes work, errors were transient

### Next
- T12 (QA): Storage isolation verification — ready for qa-engineer
- T13 (Security): Final infrastructure audit — deps now met (T5 done)
- Consider updating `pipeline_executor.py` and `extraction.py` callers to pass `tenant_id` when `STORAGE_BACKEND=supabase`

---

## Handoff (2026-04-11 — Autopilot Intelligence + Second-Order Distillation)

### Phase 5: Intelligence Advisor (DONE)
- `storyengine/backend/distillation/advisor.py` (NEW) — IntelligenceAdvisor class
  - Queries content_intelligence aggregates for best-performing patterns
  - Returns: best hook type, thumbnail style, title structure, publish timing, top topics
  - `to_prompt_context()` formats for Claude prompt injection
  - `to_dict()` serializes for API response
  - Parallel async queries, confidence = min(1.0, sample_size / 50)
- Wired into `routes/autopilot.py` — Intelligence scoring now matches candidate DNA against niche recommendations
  - Candidates with matching hook_type get +15, title_structure +10, topics +10
  - Candidates query LEFT JOINs content_intelligence for hook_type, title_structure, topic_tags
  - New `GET /api/autopilot/recommendations` endpoint for dashboard
- Wired into `routes/discovery.py` — `_get_learnings_context()` now includes niche intelligence recommendations section

### Phase 6: Auto-Distillation + Meta-Analysis (DONE)
- `_auto_distill_intelligence()` background task in main.py (12h cycle, 25 videos/batch)
- `_auto_generate_meta_insights()` background task in main.py (24h cycle)
- `storyengine/backend/distillation/meta_analyzer.py` (NEW) — Second-order distillation
  - Gathers 10+ aggregated pattern queries (hooks, titles, thumbnails, topics, timing, controversy, tones, viral videos)
  - Sends to Claude Haiku for meta-analysis
  - Extracts: top_patterns, combination_insights, timing_strategy, contrarian_findings, niche_signature
  - Stores in `niche_meta_insights` table (upserted per tenant)
- `storyengine/backend/migrations/040_niche_meta_insights.sql` (NEW) — niche_meta_insights table
- `routes/intelligence.py` — 3 new endpoints:
  - `GET /api/intelligence/recommendations` — advisor recommendations
  - `GET /api/intelligence/meta-insights` — latest meta-analysis report
  - `POST /api/intelligence/meta-insights/generate` — trigger meta-analysis

### Phase 7: Frontend Dashboard (DONE)
- `api.ts`: New types + API functions (IntelligenceRecommendations, NicheMetaInsights, 4 new fetch functions)
- `analytics/page.tsx`: Two new panels in Niche Intelligence section:
  - **AI Recommendations** — 4-card grid: Best Hook, Best Title Structure, Best Thumbnail, Best Timing + top topics
  - **Niche Meta-Analysis** — Claude-generated report with top patterns, contrarian findings, winning combinations
  - Generate button for meta-analysis when 20+ videos distilled

### What's next:
1. **Deploy**: Restart backend to auto-apply migrations 036-040 + start background tasks
2. **Trigger backfill**: `POST /api/intelligence/backfill?batch_size=50` (or wait 12h for auto-distillation)
3. **Trigger meta-analysis**: `POST /api/intelligence/meta-insights/generate` (or wait 24h)
4. Extend distillation to video_scripts, research_payloads, agent_paper_trails
5. Add GCS archival for raw transcripts after distillation
6. Autopilot auto-launch: use recommendations to auto-select which discovery idea to launch

**Design decisions:** See `tasks/decisions.md` — ADR 2026-04-11

### Previous: Phases 1-4 (Content Intelligence Full Stack) — DONE
- Backend distillation pipeline (Haiku + Gemini Vision + OpenAI embeddings)
- 10 intelligence API endpoints + frontend UI
- Intelligence-driven scoring in autopilot + discovery

---

## Active Work

**Execution Plan:** `tasks/roadmap.md` — 18-day SaaS transformation
**Current PRD:** PRD 3 — Infrastructure (Security, Rate Limiting, Task Persistence, Logging, Health Check)
**Agent Team:** 6 agents on Opus. PRD 2 mostly complete (11/13). PRD 4 complete (15/15).

### PRD 3 Progress
- [x] **Task 1** (SEC-1, SEC-2, SEC-3): Already done by agent team — verified
- [x] **Task 2** (SEC-4, SEC-5, SEC-6): SEC-4/SEC-6 already done. SEC-5 safety comments added to all 12 f-string SQL queries
- [x] **Task 3**: Rate limiting middleware (`rate_limit.py`) — per-plan token bucket, concurrent job limits
- [x] **Task 4**: Persistent background tasks — migration 032, `_db_persist_task()` fire-and-forget, `recover_stale_tasks()` on startup
- [ ] **Task 5**: Per-tenant storage — DEFERRED (users will connect own Google Drives, not Supabase Storage)
- [x] **Task 6**: Structured JSON logging (`logging_config.py`) — all `print()` in main.py replaced with `logger.*`
- [x] **Task 7**: Health check expansion — `/api/health` checks DB + active tasks, `/api/health/detailed` with token auth
- [ ] **Task 8**: QA security verification (depends on Tasks 1-2)
- [ ] **Task 9**: QA infrastructure verification (depends on Tasks 3-7)
- [ ] **Task 10**: Frontend health status indicator (depends on Task 7)
- [ ] **Task 11**: Security final audit (depends on all tasks)

## Handoff (2026-04-10 — PRD 3 Phase 1+2 Build)

**What was built:**
- `storyengine/backend/rate_limit.py` (NEW) — Token bucket rate limiter per plan (free: 15/min, starter: 30, creator: 100, studio: 300). Concurrent pipeline job limits. Skips health/auth paths.
- `storyengine/backend/logging_config.py` (NEW) — StructuredFormatter (JSON), RequestLoggingMiddleware, error rate tracking (10/5min threshold)
- `storyengine/backend/migrations/032_background_tasks.sql` (NEW) — Persistent task tracking table with RLS
- `storyengine/backend/routes/pipeline.py` — Added `_db_persist_task()` (fire-and-forget DB writes on key transitions), `recover_stale_tasks()` (startup recovery). 61 `_set_task_status` calls now pass `tenant_id=tenant_id` for DB persistence.
- `storyengine/backend/main.py` — Wired RateLimitMiddleware + RequestLoggingMiddleware. Replaced ALL 18 `print()` with `logger.*`. Added startup task recovery. Expanded `/api/health` + new `/api/health/detailed`.
- `storyengine/schema.sql` — Added background_tasks table definition
- 10 route files — Added SEC-5 SECURITY comments to all f-string SQL queries

**Design decisions:**
- Task tracking is dual-layer: in-memory dict for real-time progress (sync-compatible with progress callbacks), DB for persistence/history. Fire-and-forget via `asyncio.create_task()`.
- Task 5 (per-tenant Supabase Storage) deferred — user wants BYOD Google Drive model.
- Rate limiting is in-memory (resets on restart) — acceptable for v1 since it's protective not billing-critical.

**What's next (Phase 3):**
- Tasks 8-9: QA verification of security + infrastructure
- Task 10: Frontend health status indicator component
- Task 11: Final security audit
- Deploy to VPS and verify migration 032 runs

**Previous:** PRD2 T1-T11 verified. PRD 4 complete (15/15).

**PRD 2 status:** 11/13 done. T12 (QA Playwright regression) and T13 (already done by qa-engineer) are the only remaining items. T12 dependencies now all met.

**PRD 4 COMPLETE** — All 15/15 tasks done.

**Still open:** 3 SEC bugs in task queue (SEC-SSE-001 cross-tenant SSE, SEC-EMAIL-001 HTML injection, SEC-KEYS-001 exception leak). These are for backend-dev.

Previous handoff (PRD 2):
All 7 PRD 2 backend tasks are committed and passing acceptance criteria:
- Task 1: Migration 029 (trial_warning_sent column)
- Task 2: Query-param token auth in auth.py for SSE connections
- Task 3: SSE stage_change events (already existed)
- Task 4: POST /keys/validate bulk API key testing with timeout
- Task 5: email_service.py shared email module + email.py stub
- Task 6: Billing receipt email on checkout (already wired)
- Task 7: email_tasks.py trial warning system (already created)
Frontend tasks 8-12 are now unblocked. Task queue is empty.

### What Shipped Today (2026-04-08)
- Billing page (`/billing`) with plan comparison, usage bars, Stripe integration
- Critical Bug Fixes PRD: all 14 tasks (6 backend, 6 frontend, 1 QA, 1 security)
- Competitors page refactored (server-side pagination, filters, sort, scrape progress)
- Error boundaries + 404 page
- Toast notification system (replaced 81 alert() calls)
- System prompt editors on pipeline tabs
- Trial countdown badge + banner
- REG24 regression sweep: 24/24 pages, 33/33 API, 9/9 tabs — 0 bugs
- UX Polish PRD backend tasks: render_minutes tracking, suggest-titles endpoint, welcome email

### Next Up (from roadmap Day 3-5)
- [ ] Plan enforcement: `tenant_usage` table, `check_plan_limits()` middleware, usage hooks
- [ ] Free trial logic: 14-day Creator trial on signup, countdown, downgrade-on-expiry
- [ ] Password reset flow: token table, email (Resend), `/reset-password` page
- [ ] Disable dev-token in production mode
- [x] Create video simplification: POST /api/videos/suggest-titles endpoint built
- [ ] Frontend: wire suggest-titles into create video flow (PRD Task 8)

---

## Blocked / Pending

### Storyboard Extraction V2 (from 2026-04-04)
- **T27-003**: Rewrite storyboard-extract endpoint for Supabase
  - Wire `extraction.py` into `pipeline_executor.py` (currently silently does nothing for Supabase videos)
  - Read grid URLs from `scripts` table → call `extract_grid()` → update `assets.image_url`
  - Grid layout is 3x2 (6 panels per grid), NOT 3x3
  - Test video: f9749bd2 ("Drones"), 6 scenes
- **T27-004/005/008**: Permanent storage for all image gen steps (Supabase Storage)

### Security Issues (from Critical Bug Fixes PRD)
- SEC-1 (CRITICAL): dev-token bypasses all auth in dev mode
- SEC-2 (HIGH): get_scene_audio skips tenant check
- SEC-3 (HIGH): API keys revealed without rate limiting
- SEC-4 (HIGH): Hardcoded IP in CORS allowlist
- SEC-5 (MEDIUM): Dynamic SQL via f-strings
- SEC-6 (MEDIUM): No audit logging for key management

### Rubric / Agent Team Improvements
- [x] Cron health audit: crons.json synced with setCadence, security-auditor wired, health checks fixed
- [x] Cadence buttons: all 6 tiers (light/normal/fast/max/turbo/ultra) now sync crontab + crons.json + UI labels
- [x] Feature 1: Concurrency guard — PID lock file + stale lock cleanup in run-agent.sh
- [x] Feature 2: Run timeout — `timeout` command wrapping Claude CLI (30min default)
- [x] Feature 3: Duration + cost tracking — timing, cost heuristic, model in activity log
- [x] Feature 4: Log viewer — `/api/logs` + `/api/logs/:agent` endpoints, dashboard modal with auto-refresh
- [x] Feature 5: Crons-controls sync — grayed out paused/OFF jobs, "Team OFF" badges
- [x] Feature 6: Runtime visualization — `/api/run-history` endpoint, calendar overlay (green/red/amber bars), Scheduled/Actual/Both toggle
- [x] Feature 7: Dashboard notifications — toast alerts polling activity log, auto-dismiss
- [x] Feature 8: Cost summary panel — `/api/cost-summary` endpoint, 24h/7d/30d cards + per-agent bar chart
- Command Center: Master ON/OFF toggle, clear queue button, task counter reset
- Activity feed: auto-scroll, WebSocket for real-time, collapse old entries
- Playwright auth fix: 13/20 QA tests skip (need shared auth intercept fixture)

---

## Latest Handoff (2026-04-08)

**What completed (PRD 2 backend):**
- Task 1: Migration 029 (trial_warning_sent column) — already existed
- Task 2: Query-param token auth for SSE — already existed
- Task 3: SSE stage_change events in /api/activity/stream — NEW: polls stage_transitions table, emits `event: stage_change` alongside `event: activity`
- Task 4: POST /api/settings/keys/validate — already existed
- Task 5: email_service.py extracted from google_auth.py — already existed (named email_service.py not email.py to avoid stdlib shadow)
- Task 6: Billing receipt email on checkout.session.completed — NEW: sends receipt via email_service after Stripe checkout
- Task 7: email_tasks.py with check_trial_warnings() — NEW: finds accounts with trial expiring in 3 days, sends warning, sets trial_warning_sent flag

**Frontend tasks UNBLOCKED:** 8, 9, 12 (depend on task 3), 11 (depends on task 4)
**QA task 14** depends on all other tasks

**Key context for next session:**
- `tasks/roadmap.md` has the full 18-day plan with daily deliverables
- `tasks/decisions.md` has settled architectural choices (10 ADRs)
- email_tasks.py needs to be wired into a background loop in main.py lifespan (not done yet — task 7 only creates the module)

Previous handoffs archived in `tasks/archive/handoffs-2026-03-to-04.md`

## Handoff (2026-04-10 — QA verification + security audit)
PRD2 Pipeline UX: 12/14 done+verified. T12 (full regression) blocked on T3/T4/T7/T10.
- BUG-USER-800807 confirmed fixed (380178b) — backend returns "Invalid or expired session", frontend suppresses auth 401s from RUBRIC
- T9 verified: trial warning wired in main.py lifespan (12h interval), email_tasks.py + migration 029 present
- T2 verified: SSE hook matches backend event shapes exactly (stage_change + task_progress), tsc clean
- T13 security audit DONE — filed 3 bugs for backend-dev:
  - SEC-SSE-001 HIGH: _running_tasks dict at pipeline.py:51 has no tenant scoping — cross-tenant leak via SSE stream
  - SEC-EMAIL-001 HIGH: email_service.py:59,110 — display_name not html.escape()'d in email templates
  - SEC-KEYS-001 MEDIUM: vault.py:326 Gemini key in URL + vault.py:356/settings.py:231 leak exception details
- Remaining: T3 (PipelineStepper), T4 (wire stepper), T7 (key validation UI), T10 (notification provider) for frontend-dev
- T12 (full QA regression) depends on all of the above

## Handoff (2026-04-10)
- PRD 2 (Pipeline UX) is active with 13 tasks, agents executing
- Fixed: ANTHROPIC_API_KEY leak ($64/day), stale progress.md, RUBRIC PRD display, agent coordination
- RUBRIC layout: two-column (queue + activity feed), tasks labeled by PRD
- Agents use OAuth now (no API key charges)
- Monitor: check cost page Apr 11 to confirm $0 API charges

## Handoff (2026-06-08 — pipeline import repair + Youtuber agent)
- **Fixed:** 5 stale shim-name imports left by 17b03be0 — pipeline now imports cleanly again (orchestrator.pipeline + all 5 touched entrypoints verified). Branch `claude/repair-pipeline-imports`. Done in an isolated git worktree (~/yt-repair) to avoid the storyengine dev-swarm's git stash/checkout/reset on the shared tree.
- **Not done / next:** smoke test was import-only (no paid run). Before relying on production: run a single-video dry pass, and reinstall the setup_cron.sh production jobs (queue/discover/autopilot) — they are NOT in the live crontab (only storyengine/agents swarm + bot_healthcheck).
- **Separate effort:** standing up a new Hermes agent profile `Youtuber` (~/.hermes/profiles/youtuber) as the YouTube production brain that drives this pipeline; multi-channel generalization planned (ChannelConfig). See ~/Desktop/Power_Doctrine Pipeline-main-integration/HERMES_REBUILD_PLAN.md.
- **Caution:** `/home/clawd/pipeline-bot/venv` (referenced by infra detect_python) does not exist; live fallback is repo-root `economy-fastforward/venv`.

## Handoff (2026-06-08 — neuter Slack for customer-facing bot)
- SlackClient no longer raises without a token; degrades to a silent no-op (enabled flag + guarded API methods). Verified: no-token instantiation + all notify_* return None, no exceptions.
- Paired with blanking SLACK_BOT_TOKEN/SLACK_APP_TOKEN in the VPS .env (gitignored) so the pipeline posts nothing to Slack. The legacy Slack listener (pipeline_control.py) is already stopped + its healthcheck cron disabled.
- Context: pipeline is being driven by the new Telegram bot @YoutubeAGI_bot (Hermes profile 'youtuber'); Slack is being retired.

## Handoff (2026-06-08 — multi-tenant ChannelConfig foundation)
- DONE: dedicated free Supabase project `youtuber` + multi-tenant schema (creators/channels/channel_config/drive_connections/videos/competitors/video_metrics, RLS on). `shared/channels/` ChannelConfig loader. Threaded into VideoPipeline + --channel flag. Verified: default-equivalent for economy_fastforward + distinct config loads for a second channel.
- NEXT: (1) per-creator Google Drive OAuth connect flow (needs a hosted OAuth callback for the Telegram UX — design decision). (2) Supabase-backed status machine so state_store='supabase' channels actually produce (videos table read/write path; today only config is multi-tenant, EFF still on Airtable). (3) wire onboarding to auto-create a creator's ChannelConfig.
- Secrets: YOUTUBER_DB_URL in VPS .env (gitignored). psycopg2-binary added to requirements.

## Handoff (2026-06-10 — yt-dlp YouTube bot-check investigation)
- DONE: confirmed VPS IP is hard-flagged by YouTube (all player clients, latest yt-dlp, PO-token provider, youtube-transcript-api all blocked — see lessons.md). Wired `YTDLP_COOKIES_FILE` + `YTDLP_PROXY` env support into routes/niche.py (`_ytdlp_antibot_opts()`); verified wiring + graceful degradation + flat-listing/oEmbed regression on real videos. Branch `claude/ytdlp-bot-check-fix`.
- ACTION NEEDED (Ryan): export YouTube cookies from a logged-in browser (Get cookies.txt extension, Netscape format), upload to the VPS (e.g. /home/clawd/.config/storyengine/youtube_cookies.txt), add `YTDLP_COOKIES_FILE=<path>` to storyengine/backend/.env, restart backend + worker. Use a throwaway/secondary Google account — YouTube can flag accounts used for scraping. Alternative: set `YTDLP_PROXY` to a residential proxy.
- After cookies/proxy are in place, re-verify: `_extract_video_info("PHe0bXAIuk0")` returns title + transcript, then check Model A Video extract, competitor scrape, voice-learn.
