# HANDOFF - 2026-09-24 - helicopter video: research done 20/20 on the relay; token-cost dive next

## State
- Prod: `0cdcdd27` deployed, healthy, NO lock (removed 19:21Z). Nothing deployed this session.
- THE REAL VIDEO: `09debd56-6be0-4eb5-ad68-9cead8ba07f5` "Every US Military Helicopter Ever Built (2026)"
  (tenant Designed Vs Used, 20 min, relay on, $0 spent). Status `idea_logged`.
  - Roster DONE (20 types). Photos DONE (20/20 US-marked).
  - Research DONE: 20/20 cards, 20/20 verdicts passed (`unit_research_hold_validation`). Guide says research done.
  - Script NOT started.
- Battleship `7b6914b6` = test only, never voice it. Submarine `6ac28204` untouched.

## FIRST: token cost dive (Ryan asked for this next session)
- Each Sonnet helper starts at ~77k context before doing any work (measured from its jsonl usage:
  ~40k shared cached prefix + ~37k agent-specific). Parts: ~55 fully-loaded tool schemas (in-app
  Browser ~20, Artifact, Workflow, iOS Simulator, terminal, widgets, Docs) + ~200 deferred tool names +
  CLAUDE.md chain (~17k tokens: vault CLAUDE.md, 34 KB project CLAUDE.md + its 6 @-imported docs,
  storyengine/CLAUDE.md) + skills list. Exact split not visible - measure it.
- Built `.claude/agents/relay-researcher.md` (Sonnet, 5 tools only). Try it: does it really drop the
  tool schemas? Does it still load the CLAUDE.md chain? Compare its first-turn usage to ~77k.
- Ideas to weigh: turn off in-app Browser / iOS Simulator connectors for StoryEngine sessions; slim the
  34 KB project CLAUDE.md (its @-imports load into every helper).

## Next action (after the token dive)
Script the helicopter video on the relay: `script` verb for 09debd56, then answer its relay requests.
Use one helper per batch of requests, not one per request.

## Open threads
- A relay request waits only 1800s. A long pause kills the stage; re-running research_machine resumes from saved answers.
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
