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
