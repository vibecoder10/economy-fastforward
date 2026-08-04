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
NEXT: pictures stage - "Build to pictures" / aircraft views (0/23 ready, 3 views per aircraft targeted). PAID - quote
first, get Ryan's go. ~$17.80 of the $20 cap remains ledgered-free, but remember ~$5-6 unledgered script spend already
happened today. G24 escalated_model log watch still deferred (no new script cards this session).
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
