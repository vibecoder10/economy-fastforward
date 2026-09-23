# HANDOFF - 2026-09-23 - battleship relay test: roster -> photos -> research -> script done, stopped before voice

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

## Next action (start here cold)
The battleship video was only a test vehicle - Ryan: do NOT voice or finish it. The job now is fixing
the pipeline gaps it exposed. Start with blocker 1 below (claim text vs its source page), then 2 and 3.
Plan the fix with Ryan before coding; per scripts-are-never-blocked, a new check warns, never blocks.

## Verdict: where a human had to step in (automation blockers, worst first)
1. **Claim text drifts from its source.** Quotes were 100% verbatim, but ~1 in 5 claims added a number,
   a date, a sibling ship's fact or unsupported framing. The card gate only checks the quote exists.
   Needs a claim-vs-page number check in research (advisory, per scripts-are-never-blocked).
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
