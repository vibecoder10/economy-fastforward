# HANDOFF - 2026-09-24 (was 2026-09-23) - battleship relay test: roster -> photos -> research -> script done, stopped before voice

## State
- Prod: `7528431a` deployed 17:34Z, healthy, no lock, 0 active work. Branch `main` = origin/main, clean.
- Video `7b6914b6-3ff5-46d0-b05f-138a984baa32` "Every US Battleship Class Ever Built (2026)" (tenant
  Designed Vs Used): **status `ready_for_voice`**, 23/23 paragraphs, 2,678 words, runtime 23 min.
  All of it ran on the no-key relay, $0 spend. Test vehicle only - not to be voiced.
- Script for Ryan to read: `~/AgentVault/Assets/story-engine/docs/battleship-script-2026-09-23.md`.
- Submarine video `6ac28204` untouched.
- What shipped this session:
  1. `fe106021` every-class roster (deployed): roster now 23 classes, runtime auto-set to 23 min.
  2. `4d1b3b26` roster resize log used a status the DB refuses ('info') -> 'completed'.
  3. `7528431a` roster photo search: one-ship names pinned by hull number/year ("Iowa" "BB-4"
     battleship), 'battleship' is a subject word. Before: Iowa/Maine/Texas pulled the STATE articles,
     "Virginia class" pulled the submarine. After: 23/23 verified photos.
  4. Hand-corrected 36 claim-text errors in 23 research cards (audited against the source pages).
- Backend suite: 5410 pass / 4 skip / 3 fail (the 3 old `test_dvsu_saved_evidence_replay.py`
  fixture failures - still unfixed, see prior handoff in git history).

## Next action (start here cold) - updated 2026-09-24
THE REAL VIDEO NOW: `09debd56-6be0-4eb5-ad68-9cead8ba07f5` "Every US Military Helicopter Ever Built (2026)"
(tenant Designed Vs Used, 20 min, relay on, $0 so far). Roster DONE and saved: 20 types, 5 acts x 4, all
services (Army, Navy, Marines, Coast Guard). Next: gather photos (`gather_roster_images`, relay vision -
download + Read every image), then research one machine at a time, then script. Battleship 7b6914b6 =
test only, never voice it.
Shipped today (all deployed): `957a0afb` writer reads quotes not summaries; `741a9b37` set length = roster
size (never resize); `9669f4b0` thesis covers the whole title; `2150bf3d` category titles ("every/all/ever
built") pick the list from the title FIRST, then write thesis + acts around it.
Known: research quote shows ~$0.05 even when the relay does the work ($0) - fix later. After each deploy the
MCP endpoint returns 502 for ~1 min.
Relay answers: Sonnet subagent gets the prompt verbatim, no extra rules from me (fair test), fences stripped.

## Verdict: where a human had to step in (automation blockers, worst first)
1. **Claim text drifts from its source.** Quotes were 100% verbatim, but ~1 in 5 claims added a number,
   a date, a sibling ship's fact or unsupported framing. The card gate only checks the quote exists.
   Fix by removing the re-write step (writer reads the real quote), not by adding a checker.
2. **Two copies of each card.** The script brief reads `research_payload.unit_research_cards` +
   `machine_raw_source_packages`, not the `machine_research_cards` table. Fixes to the table do nothing.
3. **Race:** starting machine N+1 right after N ends can reset N's verdict in
   `research_payload.unit_research_hold_validation` to "pending" (6/23). Re-running research_machine
   on it repairs it. Lost-update on the whole payload.
4. `research_machine` skips a machine that has a card, so a corrected relay answer can't be re-applied.
5. Roster reset needed a manual DB write (old-code roster). One-time.
6. Cancel on a relay-waiting stage ends as "failed: Something went wrong", not "cancelled".
7. Relay-side only (not pipeline): research is 1 machine at a time (138 sequential calls, ~2h).

## Open threads
- Headline slot contract code (from snapshot `4c390eba`) is now LIVE - Ryan chose to ship it.
- The 3 replay-fixture test failures; submarine content notes; VPS PAT rotation - unchanged.

## Gotchas learned this session
- `se token` + header `X-Active-Tenant: <tenant>` reaches tenant-scoped REST (e.g. /api/pipeline/cancel).
- Relay helper `mcp.py` (MCP over HTTP with the ~/.claude.json header) posts answer files without
  pasting them into context - kept in this session's scratchpad; easy to recreate.
- A relay judge answer missing one candidate id is rejected whole ("incomplete judgments").
- `research_payload` is ~1 MB; write it back with a compare-and-swap on md5(research_payload::text).
