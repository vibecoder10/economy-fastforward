# HANDOFF - 2026-07-02 (chat asset intake day + the hybrid dialogue chain)

(The prior director-pass handoff is preserved as `HANDOFF.md.bak-20260702-153439`.)

Written at the end of a very large session. Read this + GOAL.md Phase F, then go.
Prod is main @ 2b5b8ea2, everything below deployed and live.

## UPDATE 2026-07-02 (later session): the assembler is BUILT + DEPLOYED

The task below is DONE - prod @ f964a9c6. backend/render_perform.py implements
the agreed design: per scene, every dialogue_segments voice laid end to end
into ONE track (dialogue lines get a 0.5s head-pad mirroring the clip mux
lead + 0.25s tail beat), speaking shots windowed to exactly their line span
(assigned_dialogue first, sentence-containment fallback for pre-065 rows),
narration blocks split across shots by sentence word count, ALL clips muted.
run_render routes character_dialogue+voice_over videos to it; the post-animate
scene preview uses it too (plain stitch fallback). 10 unit tests
(tests/functional/test_render_perform.py) + local ffmpeg smoke test pass.

PROVEN on prod data: bird video f32ed182 scene 2 (9 voiced segments incl. 5
character lines, 5 clips) assembled in-process on the VPS into a 32.51s video
against a 32.50s track - voices continuous, merged-turn masters (Mom+Dad in
one window) handled, one intentional inter-line beat. No prod rows touched.

STILL OWED for the full product proof: the Marco video (9abb9d51) has all 21
segments voiced but ZERO clips - when Ryan drives approve-Marco → environments
→ storyboard → animate (his D2 proof), the scene preview and final render will
come out of the assembler automatically. Listen for mouth/track alignment on
the speaking shots there; the head-pad constant is PERFORM-env-tunable
(PERFORM_DIALOGUE_TAIL, PERFORM_MIN_SHOT) if pacing needs a nudge.

## UPDATE 2 (same session): dialogue-line alignment chain FIXED (prod @ 35b60d89)

Ryan's shot review caught lines sitting ~2 shots early. Root causes + fixes
(all proven by replaying the REAL cached planner output + script + segments):
turn splitter no longer merges same-speaker lines across narration (ONE
splitter now - coverage._scene_turns, backend delegates); reconcile respects
the planner's LINE markers (text-first matching, verbatim stamp, silents stay
silent, no line ever lost); shot budget scales silent inserts with narration
(Marco scene: 12 moments = 6 speaking + 6 inserts); coverage masters get
their mux via clip_dialogue.match_assigned (summaries never matched
match_lines - voice_over masters had NO voice muxed); scenes opening on a
line get a 1.6s lead-in (PERFORM_SCENE_LEADIN) so the establishing shot
isn't dropped. 20 unit tests + full-chain replay (tests/functional/
test_dialogue_alignment.py). Ryan re-runs pictures on the Marco video next
(~$2 for the scene); the assembler renders it.

## UPDATE 3 (2026-07-04): PocoAPoco = couple format, Option A voice lock, EP2 staged

Ryan's pivots, all LIVE on prod (latest @ d92c4a2d): channel format = Ryan &
Vanessa couple dialogue (house template registered, project cast LOCKED with
voice pins that now travel through the locked-cast import: Ryan=Adam
zKTOd8cx…, Vanessa=Pamela pmruOMcx…, ElevenLabs DIRECT key in the PocoAPoco
vault). Production mode = OPTION A: grok_native (Grok animates AND speaks)
+ clip_dialogue.swap_voice per speaking clip (ElevenLabs speech-to-speech,
timing preserved so lips stay synced; VOICE_SWAP=off kill switch; falls back
to Grok's take). InfiniteTalk dual-animator routing stays wired as plan B
(TALKING_CLIP_MODEL). Pure-dialogue scenes plan masters-only in BOTH modes
(the stitch plays every clip - extra frames ADD runtime).

STAGED, DO NOT SPEND WITHOUT RYAN'S GO: EP2 "El Desayuno" 05ec4952 at the
gate (script scrubbed of stage directions, cast+voices imported, 22-frame
plan). Ryan said: "we'll do another test video end to end" - wait for his
go, then run pictures -> animate (grok + voice swap) -> stitch in ONE run
(~$4). Coffee Short 71a6b034 + dinner ep1 b885122f parked (voice_over era).
Ryan-owed: rotate the VPS sudo password (it's in a chat transcript). nginx
client_max_body_size 25m added (uploads over 1MB used to die at nginx).

## THE ORIGINAL TASK (done - kept for design context): the performance-track assembler (Ryan said build it)

The hybrid bilingual format (characters speak Spanish, narrator teaches in English)
works end to end EXCEPT the final render. Three correct pieces exist with nothing
assembling them:

1. Narrator scene MP3 - teaching/narration ONLY (voice/run.py `narration_text` strips
   speaker lines + markdown for dialogue-mode videos).
2. Per-line character audio - `scripts.dialogue_segments` jsonb: ordered
   [{type: narration|dialogue, speaker?, text, audio_url?, duration?}] per scene,
   synthesized by backend/dialogue_voice.py (durations measured via mutagen).
3. Lip-synced speaking shots - clip gen muxes each line's audio onto its clip
   (pipeline_executor.py ~:2080, `mux_voice`; coverage assigns one master frame
   per dialogue turn via assets.assigned_dialogue).

THE GAP: the voice_over render path (Remotion, `run_render` -> `run_render_bot`)
times the whole scene off the narrator MP3 alone (render/run_audio_sync.py:
Whisper word timestamps -> per-shot windows from each shot's sentence_text).
Character lines have NO reserved time on that clock - and grep confirms NOTHING
under skills/video-pipeline/render/ reads dialogue_segments. The stitch path
(render_stitch.py, grok_native only) never lays narration at all.

DESIGN (agreed with Ryan): per scene, concatenate segment audio in timeline order
(narrator seg -> Marco line -> narrator seg -> Sofia line...) into ONE scene track;
time each shot's window to its segment's span (speaking shots show exactly while
their line plays - mouths match because the talking clips were generated FROM that
same audio; narration shots subdivide narrator segments sentence-wise like today).
All clips play MUTED; the assembled track carries every voice. Build it so all
render paths can use it; prove with a one-scene real render on the test video below.
Estimated ~half a day incl. proof. Watch out: the old Remotion Scene.tsx
"muted-clip + narrator" bug is why grok_native bypasses Remotion - decide whether to
extend Remotion's config (narration_start/end fields already exist in
render/audio_sync/render_config_writer.py) or assemble audio+windows and reuse the
FFmpeg stitcher with an overlay track (likely simpler: stitch clips by window, then
mux the assembled scene track over the video).

## The live test video (Ryan's new channel)

- Tenant: PocoAPoco's Workspace `44ecc95a-80f3-4261-8294-f963c03af2bd` (operate via
  the command-center switcher; note X-Active-Tenant with a hand-minted token gets
  "Not a member" - run engine fns in-process on the VPS instead).
- Video: `9abb9d51-d9fd-41e3-9ad2-27a282fd9e7f` "El Niño Que Siempre Llegaba Tarde"
  - Script: hybrid dialogue format (rewritten BY the copilot as a product test - it
    nailed the format but changed the twist from abuela to broken-clock; Ryan hasn't
    objected yet). 1 scene, 353 words.
  - dialogue_mode=character_dialogue, 21 segments (Marco 4 lines, Sofia 2, narrator 15).
    Voices auto-cast: Marco=Finn, Sofia=Emma - Ryan should LISTEN for Spanish accent
    quality and maybe pin native voices before producing at volume.
  - Scene-1 voice flag RESET (the first take read the raw text incl. labels - fixed);
    "Create the voiceover" regenerates cleanly (~$0.30) and now reads teaching-only.
  - Still owed on this video: approve Marco (Characters tab - Ryan may want him
    redesigned as a man; the old kid-flag refusal is FIXED by the scrub, see below),
    environments (or skip), then storyboard -> animate (this doubles as the D2 clip
    proof Ryan wants to drive through the UI).

## Shipped + proven on prod today (details in GOAL.md Phase F log)

1. Chat asset intake F1-F6 COMPLETE (drop CSV/PDF/character sheets into chat ->
   production queue + autopilot drain / verbatim scripts / house script template /
   locked cast / channel format lock). See memory `storyengine-chat-asset-intake`.
2. Semantic scene split - unmarked scripts split one-beat-per-scene (verbatim-guarded).
3. D1 per-scene shot budget - `_coverage_shape` + `enforce_shot_budget` trims the LLM
   planner IN CODE before image spend (the planner provably ignores prompt caps).
4. Kid-safe image prompts - `scrub_minor_terms` in shared/clients/image_client.py
   rewrites minor words at the send boundary (Ryan's call: never say them, no
   rerouting); planners also told appearance-only. GPT Image 2 stays the engine.
5. Dialogue chain fixes: brief-path scripts now get dialogue-tagged (was: never ->
   hybrid silently off); bold `**Marco:**` speaker labels parse as dialogue turns;
   narrator VO reads narration only; Performance Track card on Script & Voice tab
   shows the split before any spend.
6. UI fixes: dock chat pins to newest content (confirm-card buttons rendered below
   the fold - the "no button UI" bug, reproduced + fixed + verified); cast-gate
   banner on the Scenes tab (designed-but-unapproved cast looked like a skipped step).
7. VPS deploy coordination: deploys ONLY via storyengine/scripts/vps-deploy.sh
   <session-name> [--with-frontend]; ~/deploy.lock guards prod work; rule lives in
   the repo CLAUDE.md. Used for ~15 deploys today, zero collisions.

## Working setup (do it this way)

- Build in the git worktree `~/economy-fastforward-intake`, branch
  `feat/chat-asset-intake`; fold to main only deploy-ready; other agents share the
  main tree. Worktree frontend needs .env.local copied from the main checkout and an
  APFS-cloned node_modules (cp -Rc; symlinks break Turbopack).
- Verify frontend with tsc + next build (local preview can't reach authed pages);
  real proofs on prod via scp'd python scripts run with
  `cd backend && PYTHONPATH=. venv/bin/python ...` (import pipeline_executor first
  when you need skills/ modules like voice.run or shared.clients).
- Mint tokens: memberships JOIN ON user_id (not account_id); 2h expiry; `$$` in
  ssh-heredoc SQL gets eaten by bash - scp script files instead.
- New producer chat ops MUST go into producer_prompt.py's OUTPUT FORMAT schema (not
  just prose) or the model invents sibling keys; the app appends truthful result
  lines - the producer must never claim success itself.

## Open follow-ups (after the assembler)

- Pin Spanish-native voices for PocoAPoco's cast; then save-to-project + LOCK the
  cast (Profile -> Channel cast) so the channel runs hands-free.
- Same-speaker turns separated by narration currently MERGE into one speaking shot
  (coverage `_dialogue_turns`) - may want them separate for the echo format.
- House script template should DOMINATE the writer stage (F4 caveat - it rides the
  system prompt and competes with brief_translator's act machinery).
- Copilot verb gap: "change the character's design prompt" fumbles (it only knows
  image-prompt edits on existing assets).
- Dock attachments (chat file-drop is home-only); shorts repurposing (G4 leftover).
- Ryan-owed: publish the Google OAuth consent screen (BLOCKS new-user onboarding);
  reconnect the real YouTube channel before real uploads.
