# HANDOFF - 2026-07-30 - roster reference-photo loop shipped; DvsU carrier video ready to drive

> The previous handoff (phase D6 / Board Laws - the script-staleness finding, the three rulings,
> phase D7) was archived intact to `tasks/HANDOFF-D6-boardlaws.md`. Read it if you are picking up
> that lane instead of this one.

## State
- **Prod: `068ce0b3` deployed, healthy.** Backend + frontend active, API healthy, no deploy lock.
  All 8 commits from this session are LIVE (verified with `git merge-base --is-ancestor`):
  c7116ef0, f615772a, 4dbd9049, 53dd98a0, 4031bc02, f53b562a, 08e7cf31, 47f8e3eb. They shipped
  bundled inside the Board Laws deploy. `static_reference_misses` exists on prod with RLS enabled.
- **Branch: main**, local == origin/main, ahead of prod. **`82fd0051` (auto-sweep progress fix) is
  pushed but NOT deployed** - deploy it before or alongside the first UI drive, or the Roster panel
  will still look frozen during an automatic sweep.
  Clean apart from untracked evidence/`.bak` files.
- **Target video:** `d2e37cd6-521a-43aa-a14d-ce096a783c1e` - "Every British Aircraft Carrier Class
  Ever Built". Tenant **`561b872d`** (NOT ee93e6d1 - that is the owner account that appears in
  request logs). Status `idea_logged`, 23-machine roster, 15/23 reference photos.

What shipped this session:
- Photos now fetch automatically even when the roster gate rejects a roster. The fetch call used
  to sit below the gate's early return, so a rejected roster got zero photos, indefinitely.
- The roster gate separates real defects from pacing nitpicks. 23 ships for a 20-minute video is
  now `needs_review`, not a dead end.
- Search aliases plumbed into the photo lookup; additive `member_units` research field added.
- **Trust hole closed**: a photo could be marked "verified" even when the vision model said it was
  the wrong machine. Added a 3-char floor + word-boundary anchor to designation matching (the
  token "91" from a pennant number was matching "No. 91 Squadron RAF").
- Sweeps are durable - a mid-sweep deploy no longer silently kills them with no record.
- Per-machine miss reasons + never-built detection (CVA-01 is the live case).
- Ship-shaped regression net: `backend/tests/functional/test_ship_roster_shapes.py`.
- Purged 2 cache rows holding photos of the wrong ship (41 -> 39 rows).

## Next action (start here cold)
**RESEARCH STAGE IS COMPLETE - drive the Script stage next.** All 23 machine research
cards live on the video row (prod referee 23/23 PASS, status ready_for_scripting, roster
gate green: 22/23 photos verified + CVA-01 honestly never-built). The cards were authored
by the subscription-Claude research simulator at $0 API cost - simulator home:
`/private/tmp/claude-501/-Users-ryanayler-economy-fastforward-storyengine/a7a8e921-5f70-4bb6-ad3b-1f30c34e21f9/scratchpad/simulator/`
(STATE.md there has the full mechanics; cards/, packages/, raw/ hold all artifacts -
COPY THEM SOMEWHERE DURABLE if the scratchpad gets wiped).

Next: open the video page (local dev, Designed vs Used channel), use the MACHINE SCRIPT
ROSTER panel - run 1 single-machine script test first, review the paragraph, then run all
23. Script generation uses workspace API keys (paid) OR extend the simulator to write
script paragraphs the same evidence-grounded way. Then voice -> pictures -> render.
**Hard cap $20/video; quote cost before every paid stage.**

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
- **"Archer class" alias collision - real risk, unfixed.** The roster entry
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
