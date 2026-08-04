# HANDOFF - 2026-08-03 - script stage complete (23/23), polish + gates hardened; VOICE is next

## State
- Prod: da9841bb deployed (se health verified, 23:18Z - 6th deploy today), backend + worker + frontend healthy.
- Branch: main pushed clean through a96d8d6b (docs). Session worktree claude/dazzling-euclid-adafcc fully folded back.
  Pre-existing dirt in the shared checkout, untouched and unrelated: storyengine/frontend/next-env.d.ts,
  storyengine/tasks/loop-handoff.md (stale July content), stray storyengine/tasks/HANDOFF-D6-boardlaws.md (cleanup candidate).
- What shipped this session:
  - G20c/G20d: polish hedge law + per-sentence salvage. Polish proven live at scale: 15+ applied, 3 safe discards, 0 crashes.
  - G21a/G21b/G22: script gate honors tier-floor-as-advisory (G14 ruling); roster name-collision fix (Attacker/Ruler + latent
    CVA-01 pair); designation check accepts real name words instead of demanding the filler word "class".
  - G23a: hand-edit door - POST /api/pipeline/machine-script-submit/{video_id} {"machine","paragraph"} - free, verbatim,
    same referee. Used to land the final 5 cards at $0. G23b volume gate DROPPED per Ryan (measurement refuted the
    thin-folder theory; see tasks/decisions.md 2026-08-03 at repo root).
  - G24a/G24b: writer violation-memory across presses + auto-escalation to a stronger writer model after 2 rejections.
  - Carrier video d2e37cd6-521a-43aa-a14d-ce096a783c1e (tenant 561b872d-7b73-45e3-9c44-7f30c3566eda): 1/23 -> 23/23
    production scenes, status ready_for_voice. $20 max_spend set. ~$5-6 spent today (script calls do NOT ledger - backlog).

## Next action (start here cold)
Voice stage on d2e37cd6. Per-scene resumable/skip-if-done (skills/video-pipeline/voice/run.py:86-96), so safe to retry.
VOICE STAGE COMPLETE (2026-08-03 ~23:55Z, this session): Ryan approved the $2.17 quote in-session; the MCP voice verb ran it.
All 23 scenes voice_status=Done, video auto-advanced to ready_for_image_prompts. Ledger: ONE clean row, elevenlabs,
21,736 chars x $0.0001 = $2.17 actual (voice DOES ledger, unlike script - the no-ledger backlog is script-stage only).
Verified: get_script 23/23 Done; UI walk (worktree frontend + copied .env.local) shows VOICE green "All 23 segment(s)
voiced", cost chip Est $0.00 -> Actual $2.17, CTA now "Build to pictures"; asset-level proof = pulled one Drive voice file
via rclone (gdrive: copyid), real MP3 128kbps/44.1kHz mono, 63.7s, sample sent to Ryan. Narrator voice used:
1SM7GgM6IMuvQlz2BwM3 (workspace-configured, NOT the Rachel fallback).
New small findings: (a) scripts.voice_duration_seconds left NULL by the voice stage for all 23 (duration comes from
ffprobe fine; render/audio-sync computes later - backlog note, not a blocker); (b) voice_over_url is a raw
drive.google.com/uc link that anonymous fetch answers with a Google sign-in page - fine for the OAuth'd app + Ryan's own
browser, but any future in-app audio player for non-owner viewers will need proxying; (c) the "2/23 single-machine script
tests passed" copy nit seen live again (already on backlog).
V3 SWITCH (2026-08-04 ~00:30Z, Ryan's call mid-session): tenant elevenlabs_model_id set to eleven_v3 via the app door
(POST /api/settings/keys/elevenlabs_model_id, minted tenant token) - ALL FUTURE voice runs are v3. Carrier video final
audio state per Ryan ("as long as we have them for now and switched it for future"): scenes 1-8 = v3, scenes 9-23 = v2
(redo cancelled mid-run at his word; same narrator voice throughout so the seam is subtle). Voice spend total $2.97
ledgered ($2.17 v2 full + $0.11 scene-1 v3 + $0.69 scenes 2-8 v3); $17.03 cap headroom.
Re-voice mechanics learned (for the next voice redo): the skip guard keys on scripts.script_status='Finished' - to
re-voice, flip target scenes to 'Create' (VPS script over asyncpg; se db is read-only). Drive uploads can UPDATE IN PLACE
(same file id, new bytes - scene 4 proved it), so a file id is NOT proof of audio freshness; compare bytes/duration.
MCP voice quote shows the whole-video estimate even scene-scoped; actual ledger meters synthesized chars only (quoter nit).
Cancel endpoint POST /api/pipeline/cancel/{video_id} works cleanly (kept 7 tracks, ledgered exactly what was synthesized).
NEW BUG (backlog): scripts.voice_id stamps a stale/hardcoded id (1SM7GgM6...) while the runtime provably used the vault
voice (Wq15xSaY3gWvazBRaGEU) - the column lies about which narrator spoke.
FIXES BUILT THIS SESSION (worktree branch claude/sad-shamir-e31572, NOT deployed - deploy window parked with Ryan):
- cd221993 roster counter: header now "23/23 production scenes scripted. Script complete." (was "2/23 tests passed");
  verified live in the UI by the orchestrator.
- f33c29df voice duration stamping: mutagen parse of the MP3 bytes, written in the SAME update as voice_over_url;
  stash-proven tests, 0 new failures (28 pre-existing custom_film_remotion asset failures identical before/after).
  Backfill recipe for the 23 NULL-duration rows: routes/videos.py::_drive_file_id ->
  routes/media.py::_download_via_drive_api -> voice/run.py::mp3_duration_seconds -> UPDATE (raw GET on Drive links
  returns HTML interstitials - do not backfill that way).
PICTURES ATTEMPT #1 FAILED, $0 SPENT (2026-08-04 01:53Z, Ryan had approved the $3.45 quote): task died in 31s, all 23
scenes, zero images attempted, zero asset rows. ROOT CAUSE (code-read confirmed): static_docu.py::_scene_subjects plans
ALL scenes' title-card metadata in ONE model call capped at max_tokens=1800; a 23-machine roster needs ~2x that, the JSON
array truncates, the local STRICT _parse_json_array (no salvage - NOT shared/json_utils) returns None, subjects={}, and
every scene bounces on the caption_sub "•" metadata gate (reason missing_title_metadata) before any spend. Past 5-scene
live tests fit under the cap - size-dependent bug. Misleading error surfaced ("no segment reached 2 verified views") AND
bot_activity showed the customer only "Something went wrong. Please try again." (failure-visibility backlog bug bitten by
a real spend attempt). Fix in flight: Sonnet worker chunking the planner (batches + retry + truthful error), tests, on
branch claude/sad-shamir-e31572.
RESOLVED (2026-08-04 ~02:40Z): planner fix landed (4313e3ba, chunks of 6 + retry + truthful error, live bug reproduced
in a failing test first, 0 new failures) plus a NEW carousel UI Ryan requested mid-session (cf0dd225, arrows + N/3
indicator in each Aircraft Views card, click-cycle verified live on a 3-view machine). DEPLOYED 710d2a17 (backend +
frontend, zero-activity window, Ryan pre-authorized "deploy whenever you think it's safe"). Then the ONE-MACHINE PROOF
(Ryan's rule, now in tasks/lessons.md: first post-fix run = smallest billable unit): images scene 1 only = $0.15 quoted
(scene-scoped quoter now honest) and $0.15 ledgered (3 x $0.05). Output visually verified by the orchestrator: HMS Argus,
flush deck, no island, real 1918 dazzle scheme from the verified Wikimedia ref, white studio bg, no text; title-card
metadata grounded ("Royal Navy • 1918", flush-deck spec chip) - the planner fix works end to end. Carousel verified
live with the real images (1/3 three-quarter -> 2/3 top-oblique -> 3/3 engineering detail). Two accepted nits sent to
Ryan with the images: deck tone varies slightly between views; the "detail" view is a third full-ship angle, not a tight
crop. Video total ledgered $3.12 of $20.
ROTATION SAGA (2026-08-04 03:00-04:30Z, Ryan rejected round 1 - "3 of the same image"): root cause was the VIEW CONTRACT
itself (all three directions literally said "three-quarter"; side profiles forbidden). Fix rounds, all on branch then
main: cbd65d5c rotated contract (three_quarter / side_profile / top_planform) + role-conformance vision QA + skip-if-done;
dc848cba bow-quarter spec relaxed (slightly-elevated press photo, not eye-level) + FILL MODE (rerun generates only missing
views, never re-bills done ones - also the only door a parked view has); 9bcbe131 reject visibility (rejected frames
re-hosted on drive_image_url + judge reason markers in image_prompt; POST /api/pipeline/static-qa-approve/{asset_id}
promotes a parked frame by hand). Deploys: c8cc9cb9, bf0b19e9 (+9bcbe131 pending deploy with the chain change).
LIVE RESULT on Argus (scene 1): side_profile + top_planform PASS and are genuinely rotated (Ryan has the images);
three_quarter role-REJECTED 6x total across rounds (~$0.30 burned) - the raw side-on historical reference photo's angle
bleeds into every generation and beats the wording.
THE REAL FIX (Ryan's architecture, dispatched as the view-chain worker): anchor chaining - first clean render (from the
raw photo) becomes the image INPUT for every other angle; rotating a clean studio render works where fighting the photo
does not. Identity QA still judges against the ORIGINAL photo so the chain cannot drift. Fill mode makes it self-healing
(Argus's done side_profile = her anchor for the missing quarter view). Plumbing: anchors must go through the media proxy,
NOT raw drive.google.com links (Kie's fetcher hits Drive sign-in walls).
LESSON (in tasks/lessons.md + durable memory): repeated angle/style failures = question the INPUT ANCHOR before the
wording; the char-sheet anchoring rule was already house law and should have transferred to machines.
CHAIN PROVEN (04:10-04:18Z): 0171078f anchor chaining deployed (209a050a) - the chained quarter attempt produced a CLEAN
elevated quarter view (geometry solved), rejected only for bow-vs-stern orientation by the judge (reject reasons now
visible in image_prompt markers, rejected frame preserved on drive_image_url - evidence sent to Ryan). Evidence-backed
tune 82df4c9c (three_quarter accepts EITHER end; side-on/top-down still rejected) deployed 61a77dae.
AWAITING RYAN'S ONE-WORD GO for: (1) promote the preserved Argus quarter frame via POST /api/pipeline/static-qa-approve/
{asset_id} (asset = scene 1 image_index 1, $0); (2) 22-machine batch (~$3.30-4.00, quote via MCP images whole-video
first; Argus fills/skips via fill mode). Ledgered $3.57 of $20. Browser-pane note: localhost:3001 screenshot capture desyncs from scroll; DOM reads are the reliable channel.
Remember ~$5-6 unledgered script spend. G24 escalated_model log watch still deferred.
1. Ask Ryan which narrator voice: tenant 561b872d may have no elevenlabs_voice_id in the vault (engine default = stock
   "Rachel"). This is a creative call, get it before spending.
2. Quote the cost: 23 scenes x ~140 words each is ~20k chars, about $2 at ElevenLabs $0.10/1k chars. Get Ryan's explicit go.
3. Trigger the engine's own voice stage (find the verb in storyengine/backend/routes/pipeline.py; the MCP `voice` tool
   also exists). Auth for direct REST: se devtoken CANNOT bind this tenant (both Ryan accounts resolve to an older
   ee93e6d1 owner membership) - mint with:
   ssh storyengine-vps '~/projects/economy-fastforward/storyengine/backend/venv/bin/python3 /tmp/mint_tenant_token.py ryan.ayler@gmail.com 561b872d-7b73-45e3-9c44-7f30c3566eda'
4. Verify per-scene audio via get_script (voice status per scene) + a UI walk of the Script/Voice tab.

## Open threads
- G24 live proof deferred by design: on the next video with a hard card, watch backend logs for
  `[script] machine=... escalated_model=... reason=two_rejections` and confirm the third draft stops repeating rejections.
- Backlog: Run All Script Cards has no skip guard (rerolls saved cards - G21c candidate in tasks/loop-checklist.md);
  script-stage calls write no generation_ledger rows; UI copy nits (roster header counts preview tests "2/23" not real
  scenes; roster gate line self-contradicts); bot_activity scrubs referee detail to "Something went wrong";
  older parked items (G4/G6/G7/G10/G11/G15/G19, C13, GAP3, Stripe chip) unchanged in tasks/loop-checklist.md.

## Gotchas learned this session
- Hand-submitted machine cards (G23a house rules, full list in loop-checklist G23a entry): no semicolons; no only/never
  unless verbatim in slot evidence; each beat sentence may cite ONLY its own plan-slot evidence (memorable_fact facts are
  unusable cross-slot); final sentence may not introduce new named entities; hedge any number-bearing sentence; digits
  matching evidence tokens beat spelled-out number words.
- Worktree UI driving: the worktree's own launch.json starts the WORKTREE frontend - copy storyengine/frontend/.env.local
  (prod API URL + dev token) into the worktree's frontend first, or auth silently breaks against a stray localhost:8001.
- Batch-press scripts must log the FULL blocking-warnings list per item; summary lines lie (tasks/lessons.md 2026-08-03).
