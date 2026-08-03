# HANDOFF - updated 2026-08-03 - script stage in progress on the carrier video

## CURRENT STATE (read this block first, ignore older sections below until needed)
- Mission "bulletproof API pipeline" is DONE and deployed (research 23/23 on d2e37cd6,
  full trail in tasks/loop-checklist.md G-section). Now in the SCRIPT stage of
  "Every British Aircraft Carrier Class Ever Built" (d2e37cd6, tenant 561b872d).
- Script cards written so far: Argus (good, 1 glitch phrase), Hermes (ship-ready),
  Furious (passed referee but language broken - see G20 below). 20 carriers unwritten.
- Ryan's quality rulings this stage (all in tasks/decisions.md): word-ceiling
  near-misses are nits not blocks (G18, grace band deployed); language quality
  matters - referee checks facts but "can't hear" grammar.
- G20 language polish pass (cheap Haiku call fixes grammar, facts locked, referee
  re-checks, discard-on-regression) deployed but went SILENT on first live run
  (polished:false, no logs). G20b (hardened reply parsing - likely true culprit -
  + loud outcome logging) merged 4b7b9063, deploy #8 in flight as of handoff.
- SOLVED 2026-08-03 17:18Z, cause named by the new logging on a live Furious rerun:
  `[polish] outcome=discarded_new_blocking detail=claim_map row 4 needs two
  independent sources or a hedge for exact numerical detail(s): eighteen`.
  The polish pass WORKS and the discard-protection worked as designed: polish
  dropped the hedge word ("roughly eighteen-inch" -> unhedged), the referee
  correctly flagged the now-exact number, fallback kept the draft.
- NEXT (chunk G20c, first thing in the fresh session): one-line fix + test - the
  polish prompt must treat hedge words guarding numbers (roughly/about/around/
  some/over) as load-bearing facts, never removed. Same worktree pattern, merge,
  deploy (ask Ryan), rerun Furious, expect outcome=applied + clean paragraph,
  THEN Ryan's go on Run All Script Cards (~$1.50-3, video capped at $20... check
  actual max_spend on d2e37cd6 first - it was NULL, consider setting one).
- G20c (hedge law) + G20d (per-sentence salvage) BOTH deployed (0e9b4072) and PROVEN live 18:25Z: Furious rerun -> [polish] outcome=applied, clean 134-word paragraph, referee passed. Polish chapter closed. $20 max_spend now set on d2e37cd6. NEXT: Ryan's go on Run All Script Cards (20 carriers, ~$1.50-3), then walk the script stage in the UI.
- UI driving notes: dev server via launch.json 'storyengine' + se devtoken; JS
  .click() opens dialogs but Confirm buttons need a full pointer-event sequence
  (pattern in session; dialogs sometimes render off-viewport).
- Parked backlog: G4/G6/G7/G10/G11/G15/G19 candidates + C13 + GAP3 plan
  (tasks/GAP3-identity-plan.md) in tasks/loop-checklist.md; Stripe webhook chip.

# OLDER: HANDOFF - 2026-07-30 evening - MISSION: make the standalone API pipeline bulletproof

## Read this first
Ryan's explicit request (2026-07-30, repeated and firm): **the DVsU pipeline must run
bulletproof on StoryEngine ALONE - no MCP, no coordinator session, no simulator - using
the workspace API keys.** Today's session proved the full research stage end-to-end and
fixed 8 real pipeline bugs, but three capabilities that made it work still live OUTSIDE
the engine, in coordinator-side scripts. Your job is to move them IN. No cutting corners.

## State (all verified, referee-proof)
- Video d2e37cd6 ("Every British Aircraft Carrier Class Ever Built", tenant 561b872d):
  status `ready_for_scripting`, roster green (22/23 photos + CVA-01 honestly never-built),
  **all 23 research cards on the row, each passing prod's own referee** (23/23 PASS run
  ON the VPS with prod code). Script stage is unlocked, untouched. Hard cap $20/video.
- Prod deployed at `f75da81d`-era main (last deploy 67e8224e + handoff commit). Healthy.
- The research simulator (subscription-Claude subagents + mechanical provenance
  verification) is archived at **`tasks/evidence/dvsu-research-simulator/`** - its
  STATE.md documents the whole method; build_package.py / validate_card.py /
  reanchor_card.py / submit_research.py are the reference implementations you are
  porting FROM.
- Pipeline fixes already shipped today (deployed, tested - do not redo): live roster-gate
  recompute (`_live_roster_gate`), never-built machines satisfy the roster stage, ship
  vocab in `_visual_identity_warnings` + `_anton_source_slot_hints` (incl. sunk/completed/
  commissioned/ordered), Commonwealth+gov.uk+NAO source tiers, class entries exempt from
  the sibling-pennant designation screen, "20.9 m2" not a designation, auto-sweep live
  progress + task_type. Tests: `backend/tests/functional/test_live_roster_gate.py`,
  `test_visual_identity_cross_domain.py`, `test_source_tier_domains.py`,
  `test_ship_roster_shapes.py` (extended).

## 2026-07-31 - DEPLOYED + LIVE TEST RAN + the real last mile found (G8/G9 in flight)
Everything below (G1/G2/G2b/G5 + the D-session's work + migrations 146-153) is DEPLOYED
to prod (c6a9ba5c, 13:19Z). Ship rescue ran: d2e37cd6 back to 23/23 cards, idempotent.
The live user-path test (chat -> create -> approve -> research) then found, in order:
- Roster path only triggers on title regex every/all/ever-built/complete-list (G6 chunk);
  no default per-video spend cap exists (G7); a compound reply to an approval card
  silently destroys it and title-edit requests are ignored (G9 IN FLIGHT, chat.py:2041);
  and THE BIG ONE: the autobuild chain dead-ends at the Jul-12 bulk-generation safety
  gate because nothing engine-side loops roster entries through the safe one-machine
  research path - the carrier video only ever worked because the coordinator looped by
  hand (G8 IN FLIGHT). Both G8/G9 briefs + full diagnosis in tasks/loop-checklist.md.
- Test videos on prod: c18589b3 (wrong format, harmless, ~$0.75 max), d05efae3 (KGV,
  $5 cap, roster discovered 5 ships, parked at the gate - the designated live subject
  for G8's deferred verification; Ryan has approved re-running research on it).
- After G8/G9 merge: needs a second deploy window (ask Ryan) + resume the live test on
  d05efae3, then the ledger cost report.
- RESOLVED 2026-08-01: Ryan topped up $10. Per his call, the live proof ran on the
  REAL carrier video instead of a throwaway: the Repair All (Orchestrator) button on
  d2e37cd6 walked the 4 needs-review cards cheapest-verb-first and finished ALL 23
  research cards passing in ~5 min (2 fixed FREE by the G2 re-anchor pass on replay-
  drifted citations, 2 via penny repairs). Video at ready_for_scripting, script cards
  unlocked, seen in the UI. The DVsU research chapter of the carrier Bible is DONE,
  by the engine alone, through the product UI. The 5-ship test video (2709939d) was
  never run and can be deleted or kept as a spare test subject. Remaining candidates
  (G4/G6/G7/G10/G11/G15, C13, GAP3 plan approval, Stripe chip) unchanged.
- WAS BLOCKING, 23:27Z (now resolved): **the workspace Anthropic API account was OUT OF CREDITS** - every
  model call on prod fails ("credit balance is too low", request req_011Cdb16DNLx...).
  ALL customer builds are dead until Ryan tops up (Anthropic console, Plans & Billing).
  The final proof video (2709939d, "All 5 King George V Class Battleships Ever Built",
  $5 cap) is created, approved, and cost $0 - it died pre-spend. Re-run = one build
  click after top-up. G16 (pennant tolerance + writer-prompt rules) is DEPLOYED
  (4a5da1de, deploy #4) but its live proof is pending that top-up. Chat UI showed the
  customer NOTHING for this failure - the park/failure-visibility bug on the list
  demonstrated live.
- LATE UPDATE: three deploys shipped (final: 89d151cd, 19:58Z - G13 ship-aware gather
  + G14 tier-floor-to-advisory per Ryan's decision in tasks/decisions.md). Retry #2 on
  d05efae3: all 5 ships now WRITE cards (big step), 0/5 pass on exactly two remaining
  hard classes -> chunk G16 in loop-checklist.md (pennant-prefix identity tolerance +
  content-shape rules moved into the writer prompt). G8b attempt bound means the next
  live proof needs a fresh 5-ship video. Stripe webhook crash found in passing
  (billing.py:145, task chip spawned). Ryan's standing rule recorded in memory +
  lessons.md: 2+ failed rounds against a gate = question the design, bring him the
  issue + one fix.

## 2026-07-30 late session - GAP 1 + GAP 2 SHIPPED to LOCAL main (not pushed, not deployed)
Maestro loop "dvsu-bulletproof"; full evidence in tasks/loop-checklist.md top section.
- **G1 gatherer fallbacks** merged 51d5a67c: tolerant normalizer now IS the referee's
  comparison fold (_normalized_source_text, used at validate time 1497/1510); NA
  Discovery JSON API (retry on empty 202) -> real Wayback availability-API fallback
  fires exactly when live fetch + tavily_raw_content are both empty; iwm.org.uk in
  exclude_domains on every Tavily call + one extra naval-scoped query for ship
  contexts. +15 offline fixture tests. Adversarially verified: capture_method is
  server-side only, referee overwrites card-claimed methods, so provenance cannot be
  forged through the new methods.
- **G2 repair convergence** merged 9e6b3f81: free deterministic pre-repair pass
  (re-anchor by excerpt text + inflection swaps, ported from reanchor_card.py) runs
  before each paid round and consumes none; repair prompt now gets NAMED per-failure
  fixes by reusing the interactive Repair-button machinery (_segment_surgery_plan);
  (D48) quirk fixed (allowed_designations also scans the display name). 8 tests incl.
  a zero-paid-rounds convergence proof. Adversarially verified: re-anchor constrained
  to the machine's own fetched package, referee re-validates from scratch after.
- **G2b** merged ba44fc62: _is_naval_gather_context word-boundary matching
  (championship/friendship/flagship no longer trigger; battleship/warship added as
  explicit terms).
- **GAP 3 NOT built, by design**: scoping plan for Ryan at tasks/GAP3-identity-plan.md
  (collision confirmed live: 21 rows / 23 entries, indices 9+21 overwritten; Phase 0 =
  key by roster_index + replay, decision pending).
- **Fresh-eyes audit (G-FINAL)**: every in-sandbox DoC element MET; no spec drops, no
  vacuous tests, no dead code. Suite on local main: 1 failed / 3983 passed - the one
  failure is pre-existing test_youtube_oauth_diagnostics (routes.google_auth attr
  missing), NOT this loop's.
- **New finding, parked as G4-candidate**: seed_reference_from_url (static_docu.py:2276,
  the human paste-a-URL photo path) has no fallback chain - dead/bot-walled pasted
  URLs reject generically instead of trying Wayback.
- **Ryan still owes** (see completion report + G-DEC chunks): yes/no on the paid 5-ship
  proof run (quote from the estimator first, cap $20), the GAP3 plan call, a deploy
  window (bundle with the D-session's parked deploy - nothing from either loop is on
  prod yet).

## The mission: three gaps, in priority order

### GAP 1 - the pipeline's own web gatherer has no fallbacks (highest value)
Where: `pipeline_executor.py::_gather_verified_machine_source_package` (~line 7503,
Tavily-based) and static_docu's reference fetching. Today the coordinator's
`build_package.py` (in the archived simulator) did what the pipeline cannot:
- **Per-excerpt mechanical verification** with a tolerant normalizer: strip citation
  markers ("carrier.[9]"), collapse orphan spaces before punctuation AND one-sided
  hyphen spaces ("equipped- Hellcat" from stripped inline tags), fold smart quotes/
  dashes, NBSP. Every one of these each rejected REAL excerpts today before being fixed.
- **Fallback chain when a live fetch fails**: National Archives Discovery records ->
  their JSON API (`/API/records/v1/details/{id}`, retry on empty 202 responses);
  any URL -> real Wayback snapshot via the availability API (never trust a claimed
  archive URL - query the CDX/availability API yourself; an agent fabricated one today).
- **Source steering**: iwm.org.uk 403s ALL automation (curl, WebFetch, everything) -
  the gather prompt/source list must prefer awm.gov.au + rmg.co.uk collection object
  pages, .gov.uk, naval-encyclopedia.com, naval-history.net, uboat.net.
Port all three into the pipeline's gather step so a machine whose best sources sit
behind a bot-wall still yields a passing package. Add tests with recorded fixtures.

### GAP 2 - repair rounds don't converge without a coordinator
Where: the card build/repair loop in `_run_unit_research_hold` (~9937-10440; repair
prompt ~10386). Today's cards needed 1-3 rounds WITH precise coordinator feedback; the
pipeline's generic repair prompt would burn its 2 rounds on the same machines. Port the
mechanical lessons (all are string-checkable before spending a model call):
- Deterministic PRE-repair pass (free): re-anchor citations by excerpt TEXT when ids/
  locators drifted (reanchor_card.py logic); single-word grounding fixes are usually an
  inflection swap to the excerpt's own word ("spent"->"spending", drop "seen"/"ship"/
  "plus"/"toward").
- Feed the repair prompt STRUCTURED, named fixes, not just warning strings: which
  segment, which row to re-cite (a hinted Tier 1-3 row for that beat), the exact rules -
  fields must contain the display name's LAST token; the specificity check passes if a
  field OPENS with the machine's first 4 tokens; never kind "context"/"spec"; required
  beats never on Tier-4 rows; apostrophes tokenize ("Attacker's" leaves a stray "s").
- Known checker quirk to fix or document: `_unit_code`'s 4-token glob makes a bracketed
  pennant like "(D48)" read as an unsupported designation inside
  why_this_unit_deserves_a_paragraph for class-style names.

### GAP 3 - machine identity is guessed from a glued display string (structural)
The collisions are REAL on this very video: both "Lend-Lease escort carriers ... class
(US-built)" entries -> machine_key LENDLEASEESCORTCARRIERS; both CVA-01-containing
entries -> CVA01. `machine_research_cards` silently overwrote 2 of 23 rows (21 on the
table; payload holds all 23 and readers fall back, so it is benign TODAY by accident).
Fix per the parked plan: research DECLARES identity per roster entry -
`canonical_name`, `search_aliases`, `disambiguators`, `identifier_kind`, `member_units` -
and machine_key derives from canonical identity, never the glued string. Includes:
migration for machine_research_cards keys, the two collision pairs on this video,
and killing the downstream regex re-derivations (the handoff notes below list the known
next breakages: `_BUILT_COUNT_ZERO_RE`, `_GENERIC` in static_docu, "M4"/"MB" token
collisions for ground vehicles). This deserves its own GOAL.md planning pass with Ryan
before implementation - scope it, show him the plan, then build.

## Definition of Complete
A fresh test video with a ship roster (clone d2e37cd6's shape or make a small 5-ship
one) runs `run research` -> photos -> per-machine research **through the pipeline's own
API path only** (no MCP, no coordinator, no sidecar files) and reaches
ready_for_scripting with all cards passing the referee - proven by driving the UI like
a user and by `se db` reads, not by code inspection. Gatherer fallback + repair-lesson
+ normalizer behavior each pinned by tests. Budget: quote any paid test run first
(a 5-ship roster keeps it small); deploys via `se deploy` protocol.

## Where everything lives
- Reference implementations: `tasks/evidence/dvsu-research-simulator/` (STATE.md first).
- Today's commits (all on main, deployed): 82fd0051, 564055a6, 88afae2e, 574a0b6b,
  94ace070, bcb5f446, 023b15ec + handoff/evidence commits.
- The carrier video continues separately: script stage is next there (see Open threads).

## Open threads
- **Auto-sweep progress bug - FIXED but NOT DEPLOYED.** Commit `82fd0051`, pushed to origin/main,
  NOT on prod (prod is `068ce0b3`). The Roster panel's live progress used to fire only for the
  manual "Re-check missing" button, because `showRunning` matched the literal string
  `"machine reference"` which only `recheck_roster_references` writes; the auto-dispatched sweep
  showed a frozen panel for ~10 minutes. Fix threads a structured `task_type="roster_prefetch"`
  through the task-status channel instead of string-matching, with the old substring match kept as
  a backstop. Verified against the auto path specifically. **This is the one thing pending a
  deploy** - `./scripts/se.sh deploy <session-name> --with-frontend` (session name BEFORE flags or
  the frontend build silently skips). It touches the frontend, so `--with-frontend` is required.
- **NEW bug found by that work, not fixed.** `_db_persist_task`'s existing-running-row lookup
  (`WHERE video_id=$1 AND status='running'`) has no `task_type` filter. If a manual recheck and an
  auto sweep are ever concurrently active (the C16 gap below), the manual path's `_set_task_status`
  can UPDATE the auto sweep's own `background_tasks` row instead of inserting its own, stomping the
  auto sweep's progress message. Pre-existing and generic to every route using `_set_task_status`.
- **RESOLVED for this video (cache photo verified = MV Rapana, a real MAC ship); the alias MECHANISM risk stands until GAP 3 lands.** The roster entry
  `"Archer class / Empire Mac-Ship conversions"` describes MAC ships, but slash-splitting yields the
  alias `"Archer class"`, which matches the real-but-different RN Archer-class escort carrier. The
  alias mechanism can now cache a confidently wrong ship. The token hardening does not catch it -
  this is a name collision, not a substring bug.
- **3 suspect cache rows NOT purged** (not authorized): Boeing B-47 Stratojet (`NNSA-NSO-990.jpg`,
  unidentifiable filename), Northrop Grumman B-2 Spirit (primarily an F-35B training photo),
  Rockwell B-1 Lancer (identical file to the separate B-1B row). Needs a visual check.
- **Parked decisions for Ryan.** C13: should `submit_research` run the unit-research hold? It skips
  it today, and the MCP docs call that path "THE STANDARD WAY", so the strictest gate runs on the
  least-used route. C15: subvariant-padding was reclassified SOFT, loosening the gate for aircraft
  rosters (B-29 + B-29B padding now advances flagged instead of blocking). C16: a manual re-check
  can run concurrently with an auto sweep, risking duplicate PAID vision calls.
- **Next phase, agreed but not started - domain-agnostic machine identity.** Everything in this loop
  patched an aircraft-shaped foundation. The channel must cover helicopters, ships, bombers, ground
  vehicles, jeeps. Ground vehicles are worse than ships: "M4 Sherman" -> token `m4` (collides with
  M4 carbine, M4 motorway); "Willys MB" -> `mb`. Already-identified next breakages:
  `_BUILT_COUNT_ZERO_RE` enumerates ships/units/aircraft/hulls/vehicles/prototypes but NOT
  helicopters/tanks/jeeps; `_GENERIC` in `static_docu.py` lists singular "helicopter"/"tank" but not
  plurals. Real fix: research DECLARES identity (canonical_name, search_aliases, disambiguators,
  identifier_kind) instead of downstream regexes re-deriving it from a glued display string. Needs
  its own GOAL.md planning session.
- Full chunk history, evidence and known-debt reasoning: `tasks/loop-checklist.md` (top section).
  Live-check recipes Ryan still owes: `tasks/deferred-verification.md`.

## Gotchas learned this session
- **Agent worktree isolation can branch from a STALE head, not current local main.**
  The G2 worker's worktree was based on efc50bd8 while main already had the G1 merge;
  the worker caught it with `git merge-base --is-ancestor <required-sha> HEAD` before
  building. Every worker brief must state the required base sha and make that check
  step 0, with "merge the sha in, or stop and flag" as the remedy.
- **Verify claims against real DB rows, not fixtures.** A never-built classifier passed 11 tests
  against an enriched fixture while doing literally nothing on the real row - the real CVA-01 has
  `status="cancelled-built"` (not `"cancelled"`) with `built_count="0 ships built"`. Pull the actual
  row with `se db` before trusting any chunk report.
- **Worktree isolation fails when the orchestrating session's cwd is outside the git repo** (e.g.
  running from ~/Desktop). Parallel lanes must be file-scoped by brief instead.
- **`git stash` is dangerous with concurrent workers in one checkout.** A `stash pop` collided with
  another lane's commits and briefly wiped a worker's uncommitted changes. Use file-copy swaps for
  stash-proofs; if you must stash, always `git stash push -- <explicit paths>`.
- **Raw test counts drift when other lanes commit mid-session.** The trustworthy method is running
  the suite with and without the change and diffing the sorted FAILED/ERROR lines.
- **The in-app Browser pane hits a login wall on prod** and does not carry Ryan's session. Do not
  script past auth - that is an explicit project boundary. Ryan drives a logged-in window, or the
  check is deferred.
