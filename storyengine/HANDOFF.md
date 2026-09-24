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

## Next action (start here cold) - Ryan approved "go" on this plan 2026-09-23
Battleship video = test vehicle only, never voice it. Build: **the writer reads real page text, not the
model's summary claim.** NO output checker of any kind (Ryan, firm).

Key fact: the pipeline never opens a source page. `dvsu_research_v2._build_verified_source_package`
stores the model's quote as excerpt `text` and labels it `source_capture_method: "fetched_page"` - nothing
is fetched. The writer's brief (`dvsu_research_v2._machine_packet_markdown`, via
`dvsu_script_v2.brief_for_machine` / `brief_markdown_with_fact_ids`) shows the model-written `answer`
+ quote; the `answer` is where the drift lives (~1 in 5 claims on the battleship run).

Plan (touches >3 files - confirm shape with Ryan before coding):
1. MEASURE first (a test run, not a checker): offline script over the battleship video's 23 machines x
   ~9 cited URLs (read from `research_payload.machine_raw_source_packages`). Fetch each page, find the
   quote, cut a ~500-char passage around it. Report: pages that load, quote found, passage size, and
   whether the 36 known-bad claims' true facts sit inside the passage (audit list: `docs/battleship-relay-test/claim-audit-34.json` + `claim-fixes-applied.json`; also this session's
   JOURNAL/2026-09-23.md + the fixes applied). Show Ryan the numbers.
2. If the numbers are good: at research save time, the server fetches the page and stores the real
   passage on the excerpt (true `fetched_page`). Page won't load -> keep the model's quote alone. Never block.
3. The writer's brief shows the passage as the fact (drop the model `answer`/`headline` from the writer's
   view; keep them for UI labels). Watch the 6000-byte brief cap (`dvsu_script_brief.MAX_BRIEF_BYTES`).
4. Tests with this run's data as fixtures. Then blockers 2 and 3 below (plain bugs).

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
