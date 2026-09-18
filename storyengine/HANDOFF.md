# HANDOFF - 2026-09-18 both designs approved, exact wiring traced, Phase 1 (roster+research) ready to implement - handing off to a fresh session for context reasons

## State
- Prod: unchanged, not touched. Last verified: 0229e9fb deployed, healthy.
- Branch `main`: this session committed only `.gitignore` (`140b7921`, adds `.worktrees/`) and,
  moments ago, this file + CHECKLIST.md + the two DESIGN.md docs. Everything else `git status`
  shows (hundreds of task/doc files) is OTHER sessions' work - not touched, not committed.
- **Isolated worktree ready:** `/Users/ryanayler/AgentVault/Projects/story-engine/.worktrees/
  dvsu-pipeline-v2`, branch `feature/dvsu-pipeline-v2`, forked off `140b7921`. Empty - no
  implementation code written yet. `cd`/`change_directory` there before writing any code; don't
  go up past its root in shell commands (resets your granted directory back to the main checkout -
  happened once this session).
- What shipped this session: recovered the script-writing design (existed as an unwritten Drive
  hand-prototype, wasn't "missing" like a stale resume claimed) into
  `docs/dvsu-script-pipeline-v2-2026-09-18/DESIGN.md`; got Ryan's decisions on both designs' open
  questions; ran two read-only trace agents mapping the EXACT current code (call sites, roster
  shape Gather Images needs, the frontend's real research-data contract, confirmed the live DVSU
  video is on the `factual_100_v1` branch); set up the worktree. **Zero implementation code
  written.** This is a clean planning/research handoff, not a mid-feature one.

## Next action (start here cold)
Read `CHECKLIST.md`'s Active section first (it has the condensed technical wiring facts), then
both DESIGN.md files. Then `change_directory` into the worktree above and start Phase 1:

1. Write a new module implementing Call 1 (thesis+acts, no search) + Call 2 (roster+shared-
   context, 1 search-enabled call) from `docs/dvsu-research-pipeline-v2-2026-09-18/DESIGN.md`.
2. Wire it into `run_roster_selection` (`storyengine/backend/pipeline_executor.py:11008-11200`) in
   place of the current `research.agent.run_research(...)` call - see CHECKLIST.md for the exact
   allow-listed keys the caller currently merges (needs extending for `shared_context`/`acts`) and
   the roster shape Gather Images needs (`unit_roster` list of `{name/title, designation?, code?,
   member_units?}` + the `roster_selection.version=1` marker so Gather Images' gate still passes).
3. Write a new module implementing Call 3 (per-machine research packet, 6 targeted searches) from
   the same DESIGN.md, plus a small adapter translating its 6-slot output into the legacy shape
   `ResearchTab.tsx` actually reads (`unit_research_cards[].evidence_segments[]` with `kind` in
   `original_problem/engineering_decision/tradeoff/reality`, plus a `research_summary` object) -
   full field-level detail is in CHECKLIST.md.
4. Wire it into `_run_unit_research_hold`'s `factual_100_v1` branch
   (`pipeline_executor.py:13030-13489+`), replacing `factual_source_search.py`/
   `research_claim_assessment.py`/`factual_machine_summary.py`'s research path there.
5. Verify locally: `scripts/se.sh devtoken`, run the frontend dev server (launch.json name
   `storyengine`, port 3001, auto-logs-in against prod API), walk Research/Roster tabs for the
   live submarine video (`44dbf2b2-a27a-47ea-a608-4c31c906be9a`) or a fresh test video, in the
   Browser pane per this session's mandatory "run it like a user" rule.
6. **Do not touch script-writing wiring yet.** Ryan explicitly said: "worry about gathering the
   information cheaply first, then worry about how we compile the information in the script-
   writing stage." Script-writing (`_run_static_script_hold`, `pipeline_executor.py:14770`) is
   Phase 2, after Phase 1 is verified.

## Phase 2 prep (script-writing) - traced this session, captured now so it isn't lost

A second trace agent finished after Phase 1 planning was already done. Key facts for whenever
Phase 2 starts:

- **The real live write path for `factual_100_v1` is `factual_machine_pipeline.run_factual_script_hold`
  (`factual_machine_pipeline.py:140`), NOT `_run_static_script_hold`** - that function
  (`pipeline_executor.py:14770`) returns early at line 14792 for factual_100_v1 videos; its big
  writer-prompt body (neighbor context, `name_opener_slots`, etc.) is dead for DVSU specifically.
- Today's per-machine flow is **two paid calls**, not one: writer (`_script_writer_prompt`,
  `factual_machine_summary.py:535-563`) then a separate referee/review call (`_review_prompt`/
  `review_existing_factual_summary`, same file) - confirms the v2 design's "drop the referee call"
  is a real, meaningful simplification, not just theoretical.
- Writer output today: `{paragraph, claim_map:[{sentence, fact_ids}]}` - `fact_ids` point into
  the brief, later materialized into citations by `materialize_script_draft`
  (`script_research_packet.py:285`). The v2 design's `{sentence, source_url, quote}` claim_map
  shape does not exist anywhere yet - it's new. Zero hits anywhere for `opened_with_name`/
  `bridged_to`/`bridg`/`opening_name` - also wholly new.
- Persistence is two separate things with **different key shapes**: preview checkpoint
  (`_checkpoint_machine_script_preview`, keyed by normalized machine code) always written;
  production save (`_save_machine_script_block`, only on `save_target_script=True` or the bulk
  run) writes the `scripts` table + `videos.script` + `videos.script_validation.
  machine_script_blocks` keyed by the **raw** machine name - a real mismatch to account for.
  `scripts.sources` column is dead/never written anywhere in the backend, not just for DVSU.
- **Bigger UI tension than research's:** `ScriptVoiceTab.tsx`'s pass/fail gate
  (`machinePreviewPassesContract`/`machinePreviewPassesEditorialGate`, lines 215-248) hard-checks
  `compiler_version === 2 && factual_passed === true && editorial_review_version === version &&
  audit.passed && ...`. A new single-call v2 writer does not produce `compiler_version`/
  `factual_passed`/`editorial_review` at all - this gate will read every new preview as failed
  unless it's rewritten. Given CHECKLIST's "no DB, Drive export only" decision, this frontend
  literally has nothing DB-backed to read for the new design - **this specific tension needs a
  real decision with Ryan before Phase 2 implementation, more so than research's version of the
  same tension.**
- The existing per-machine loop (`factual_machine_pipeline.py:173`, `for scene, machine in
  selected:`) already runs strictly in roster order, sequentially, one `await` at a time - good
  skeleton to keep for the v2 design's ordering requirement. But it has **zero** state threading
  today for prior-sibling-paragraph content or a running opening-name tally - both need to be
  added as new accumulator params through the loop, not restructured from scratch.
- `dvsu_script_brief.build_dvsu_brief` and `script_research_packet.compile_script_packet` ARE
  live/load-bearing today (not dead code) - but their current 4-field brief shape
  (`intended_role/design/actual_use/outcome`) doesn't match the new 6-slot research packet, so
  they can't be reused as-is; expect a rewrite, not a patch. (Don't confuse with
  `dvsu_research_handoff.package_brief` - a different, UI-readiness-only helper, not part of the
  write path.)

## Open threads
- After Phase 1's new call sites are wired, re-grep for importers of the old DVSU-only modules
  (`factual_source_search.py`, `research_claim_assessment.py`, `factual_machine_summary.py`'s
  research path, `class_context_assessment.py`, `factual_class_context.py`,
  `contextual_source_identity.py`, `factual_machine_pipeline.py`, `factual_machine_research.py`)
  and delete any left with zero consumers - Ryan wants a clean rewrite, not old code left dangling
  unused. **Do NOT delete `research/agent.py`, `roster_selection.py`, or `roster_coverage.py`** -
  all three have other real consumers outside DVSU (see CHECKLIST.md for exactly which).
- Phase 2 (script-writing) needs its own trace of `_run_static_script_hold` - one was run this
  session but its result was never folded back before this handoff landed; redo it (or just read
  `pipeline_executor.py:14770` onward directly) when Phase 2 starts.
- Old pipeline's live state (20/20 roster, 20/20 images, 20/20 research, 1/20 scripts) still
  untouched - not yet decided whether it's preserved/migrated or discarded once new logic is live.

## Gotchas learned this session
- Drive is a better source of truth than HANDOFF.md for "does this design/code already exist"
  questions on this project - HANDOFF.md's own prose has been overwritten/lost across sessions
  more than once; the Drive project folder (`StoryEngine Research/Every US Submarine Class Ever
  Built (2026)/`) retained real prototype work each time. Check Drive before trusting a "not
  started" claim in this file.
- When Ryan says "other sessions cracked the code," don't assume literal hidden software exists -
  confirm what he means before spending a trace agent hunting for it. This session first
  misinterpreted it as hidden implementation; it meant the hand-prototyped system prompts.
- The existing frontend's research-data contract is far more specific than "whatever's in
  research_payload" - it's tied to legacy field/kind names from the old pipeline
  (`ResearchTab.tsx`'s 4 "Anton slots"). Any new research module needs a translation step, not a
  1:1 clean rewrite, to avoid a frontend change.

---
paste this to start the next session (or this is what the cloud handoff carries automatically):
Resume StoryEngine. Read CHECKLIST.md's Active section, then HANDOFF.md, then both DESIGN.md docs
under docs/dvsu-research-pipeline-v2-2026-09-18/ and docs/dvsu-script-pipeline-v2-2026-09-18/.
Change into the worktree at .worktrees/dvsu-pipeline-v2/storyengine and implement Phase 1 (roster
creation + research run, Calls 1-3) per HANDOFF.md's Next Action section. Do not touch
script-writing wiring yet - that's Phase 2, after Phase 1 is verified live in the browser.
