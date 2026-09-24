# HANDOFF - 2026-09-24 - helicopter video: script done 20/20 on the relay; voice next (PAID)

## State
- Prod: `0cdcdd27` deployed, healthy, NO lock. Nothing deployed this session.
- THE REAL VIDEO: `09debd56-6be0-4eb5-ad68-9cead8ba07f5` "Every US Military Helicopter Ever Built (2026)"
  (tenant Designed Vs Used, 20 min, relay on, $0 spent). Status `ready_for_voice`.
  - Roster, photos, research, script: all DONE. Script = 20/20 paragraphs.
- Battleship `7b6914b6` = test only, never voice it. Submarine `6ac28204` untouched.

## Token cost (solved)
- Measured: general-purpose Sonnet helper starts at 77k; `relay-researcher` agent type starts at 26k.
  The ~51k gap is loaded tool schemas. The slim agent still loads the CLAUDE.md chain (~11k).
- Script used ONE relay-researcher helper for all 20 requests: 302k tokens total (`scripts/relay/script_brief.md`).
- `.claude/settings.local.json` (local, gitignored) denies iOS Simulator, widgets, Claude Docs for
  StoryEngine sessions. Ryan wants the in-app browser kept (no limits on future builds).
- Not done, optional: slim the 34 KB project CLAUDE.md (every helper loads it).

## Next action
Voice is PAID (ElevenLabs). Quote first, get Ryan's yes, then run `voice` for 09debd56.

## Open threads
- `backend/dvsu_script_v2.py` ~L159: submarine terminology rule fires on the helicopter video (its thesis says
  "hunt submarines"). Task chip made. Script already written with it; no "boat" harm seen.
- A relay request waits only 1800s. A long pause kills the stage; re-running resumes from saved answers.
- Race: starting machine N+1 right after N can reset N's verdict to "pending" (re-run `research_machine`).
- Two card copies: script brief reads `research_payload`, not the `machine_research_cards` table.
- `research_machine` skips a machine that already has a card (a corrected answer can't be re-applied).
- Research/roster/script quotes show ~$0.02-0.05 even when the relay does all the work ($0). Fix later.
- Cancel on a relay-waiting stage ends "failed", not "cancelled".
- 3 old `test_dvsu_saved_evidence_replay.py` failures (suite: 5417 pass / 4 skip / 3 fail).

## Gotchas learned this session
- After every deploy the MCP endpoint returns 502 for ~1 min; wait for `curl -X POST .../api/mcp` -> 401.
- `research` does not redo a completed roster: reset with
  `se db --write "update videos set research_payload=jsonb_build_object('machine_script_contract', research_payload->'machine_script_contract') where id=... and status='idea_logged'"`.
- Photos are cached per TENANT + machine in `static_reference_cache`, not per video. To redo one, delete its row.
- Photo judge requests run 4 at a time, ~60-95k chars each: never list them into chat, use `scripts/relay/`.
- Give the relay subagent the pipeline prompt verbatim with no extra rules of mine - else the test is not fair.
