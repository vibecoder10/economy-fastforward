# HANDOFF - 2026-09-24 - helicopter video: roster + photos done on the relay; 5 pipeline fixes shipped

## State
- Prod: `0cdcdd27` deployed 14:34Z, healthy, no lock, 0 active work.
- Branch: `main` = origin/main after this handoff commit. Clean.
- THE REAL VIDEO: `09debd56-6be0-4eb5-ad68-9cead8ba07f5` "Every US Military Helicopter Ever Built (2026)"
  (tenant Designed Vs Used, 20 min, relay on, $0 spent). Status `idea_logged`.
  - Roster DONE: 20 types, 5 acts x 4, every service (Army, Navy, Marines, Coast Guard).
  - Photos DONE: 20/20 verified, all US-marked (I checked every photo by eye).
  - Research NOT started. Script NOT started.
- Battleship `7b6914b6` = test only, never voice it. Submarine `6ac28204` untouched.
- What shipped this session (all deployed):
  1. `957a0afb` script writer reads the verbatim source quote, never the research model's summary
     (all 34 battleship drift errors lived in the summary). Measuring run: docs/battleship-relay-test/passage-measure.md.
  2. `741a9b37` set video length = roster size (20 min = 20 machines), never auto-resized. Reverses 2026-09-23 rule.
  3. `9669f4b0` thesis must cover everything the title names.
  4. `2150bf3d` category titles ("every/all/ever built") pick the LIST from the title first, then write
     thesis + acts around it (`dvsu_roster_v2._call_category_roster` / `_call_story_for_roster`).
  5. `0cdcdd27` photo judge gets the video title, reports `operator_match`; foreign/civil photos only as fallback.

## Next action (start here cold)
Research the helicopter video, one machine at a time, on the relay:
1. `get_production_guide 09debd56-6be0-4eb5-ad68-9cead8ba07f5` (roster + image_gather should read done).
2. `research_machine(video_id, machine="R-4 Hoverfly")` (exact roster names: see guide/roster).
3. Loop 6 relay requests per machine (problem, design, trade-off, outcomes, surprising fact, contrast):
   `cd storyengine/scripts/relay && python3 mcp.py pending 09debd56-...` -> give each `req/<id>.json` to a
   Sonnet subagent (prompt verbatim, web search, raw JSON only) -> `python3 mcp.py answer <id> <file>`.
   Check the stage name printed by `pending`; `waitnew.sh` only matches `_judge_via_relay|_call|research`.
4. After each machine, confirm its verdict with `get_production_guide` (race bug below).

## Open threads
- Race: starting machine N+1 right after N can reset N's verdict to "pending" in
  `research_payload.unit_research_hold_validation` (6/23 on battleships). Re-run `research_machine` on it.
- Two card copies: script brief reads `research_payload`, not the `machine_research_cards` table.
- `research_machine` skips a machine that already has a card (a corrected answer can't be re-applied).
- Research/roster quote shows ~$0.05 even when the relay does all the work ($0). Fix later.
- Cancel on a relay-waiting stage ends "failed", not "cancelled".
- 3 old `test_dvsu_saved_evidence_replay.py` failures (suite: 5417 pass / 4 skip / 3 fail).

## Gotchas learned this session
- After every deploy the MCP endpoint returns 502 for ~1 min; wait for `curl -X POST .../api/mcp` -> 401.
- `research` does not redo a completed roster: reset with
  `se db --write "update videos set research_payload=jsonb_build_object('machine_script_contract', research_payload->'machine_script_contract') where id=... and status='idea_logged'"`.
- Photos are cached per TENANT + machine in `static_reference_cache`, not per video. To redo one, delete its row.
- Photo judge requests run 4 at a time, ~60-95k chars each: never list them into chat, use `scripts/relay/`.
- Give the relay subagent the pipeline prompt verbatim with no extra rules of mine - else the test is not fair.
