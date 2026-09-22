# HANDOFF - 2026-09-21 (session 5) - dvsu_script_v2 built and wired as the ONLY script writer; three legacy writers deleted; NOT yet walked in the browser, NOT deployed

## State
- Prod: still `8d4f2583d` (untouched, healthy at last check). **Nothing from this session is deployed.**
- Branch: `main`, one linear commit from this session (see `git log -1`). Not pushed.
- Backend suite: `cd backend && ./venv/bin/python -m pytest tests/ -q` -> 5408 passed, 4 skipped, 0 failed (baseline before: 5721 passed - the difference is the ~300 legacy-writer tests removed with the writers).
- Frontend: `npx tsc --noEmit` clean, `npm run build` clean, vitest 17/17 (gate test rewritten).
- Pre-existing, not mine, left alone (unstaged): `frontend/next-env.d.ts`, untracked `jev-key-box.html`, and
  `../tasks/decisions.md` (it carried Ryan's uncommitted Jev entry, so my two decision entries sit in the working
  tree next to it, uncommitted - commit that file once Ryan has looked).
- Untracked `docs/gold-scripts/grammar/` is now COMMITTED as part of this work (its `script_grammar.json`
  note was updated to explain the 150 vs 170 ceiling). Ryan's two judgment calls in it (name-opener
  threshold, generic-praise severity split) still deserve his eyes; they are unchanged.
- Session cut at the context ceiling (~510K tokens) right after the suite went green, per the CLAUDE.md
  ceiling rule - the browser walk was deliberately left to the next session rather than done degraded.

## What shipped (code, tested, not yet deployed)
The plan from session 3/4's handoff, executed as written:

1. **`backend/dvsu_script_v2.py`** - DESIGN.md as code. Prompt = PROMPT-v3 verbatim plus the stateful
   context blocks; code-side audit replaces the paid referee (word bands, forbidden patterns mirroring
   `docs/gold-scripts/grammar`, name-opener budget of 5, submarine `boat` rule, machine-name check);
   at most ONE bounded repair call; `run_script_hold` walks the roster in order, reuses current blocks
   without spend, checkpoints every draft as a preview, saves passed blocks through the unchanged
   `_save_machine_script_block`, advances to `ready_for_voice` only when every machine is current, and
   exports `02-script.md` to the video's Drive research folder fail-soft. Also `preview_readiness`,
   `script_readiness`, `submitted_block` (the hand-written door). 40 tests in `tests/test_dvsu_script_v2.py`.
2. **The two design gaps, resolved** (also appended to DESIGN.md "Implementation - 2026-09-21"):
   every prior paragraph is passed with its act plus the next machine's problem line, model reports
   `bridged_to`; word band 95-120 target / 80-150 hard (gold corpus: median 107, p10 84, p90 129).
3. **`dvsu_research_v2.packet_from_verified_source_package`** - the Call-3 packet was never persisted,
   so the writer rebuilds the six slots from the adapted package (positional on `C3-n` ids). A machine
   with legacy (non-v2) research cannot be scripted; readiness says "run per-machine research".
4. **Deleted, no fallback:** both writers inside `_run_static_script_hold` (now a one-line delegation),
   `factual_machine_pipeline.run_factual_script_hold`/`factual_script_readiness`, the writer+referee in
   `factual_machine_summary` (module is now 155 lines of research helpers), `dvsu_script_operations.py`,
   86 orphaned executor definitions (found by an AST fixpoint tool, see tasks/lessons.md), 12 legacy test
   files and ~170 legacy tests removed by name. `pipeline_executor.py` 22137 -> 17568 lines.
5. **Every gate keyed on the one contract** `dvsu_script_v2`: readiness check, preview/block/submit
   entry points, `run_voice`'s script gate (now for ANY roster video, not just `factual_100_v1`),
   `actions._factual_script_recheck_needed` (now only rechecks v2-written scripts, so rendered legacy
   videos are never bounced back to script on resume). `machine_script_contract == "factual_100_v1"`
   survives only as the research-v2 selector.
6. **Frontend:** `ScriptVoiceTab.tsx`/`ResearchTab.tsx` gate on the v2 contract; the Anton "sentence
   assembly"/"quality audit"/editorial-thesis panels are gone, replaced by "Sources cited" (claim_map)
   plus a bridge/name-opener line; `api.ts` type mirrors the block. Legacy previews/blocks on prod will
   show "Needs review - This saved paragraph is from an older writer. Rerun the script for this machine."
   That is intended.

## Next action (start here cold)
1. **Walk it in the browser like a user (NOT done this session).** `scripts/se.sh devtoken`, then
   `preview_start {name: "storyengine"}` -> the submarine video (20/20 researched under v2) -> Script tab.
   Check: roster panel renders, each card shows "Ready to script" (v2 packet present) or the older-writer
   notice, the free readiness check works, the "Sources cited" block renders on a preview. Screenshots.
   NOTE: local UI talks to the PROD API, so the new backend is only exercised after deploy - the local
   walk proves the frontend against prod's legacy data.
2. Ask Ryan, then `se deploy <session> --with-frontend`. Then ONE paid single-machine preview on the
   submarine video (one Sonnet call, cents) as the first-run proof, read the paragraph with your eyes
   against the v3 standard before running the whole roster (~24 calls).
3. Follow-ups this session deliberately did not take:
   - `_machine_story_plan` + `_script_starvation_*` + `PipelineExecutor.repair_promote_excerpt` (+ its
     route in `routes/pipeline.py` and the Research-tab button) survive only because that research
     self-heal route still calls them. They are downstream of the deleted 5-sentence shape; delete the
     route+method+button together (frontend change).
   - `dvsu_script_operations` DB table is unused now - drop in a migration.
   - `dvsu_script_brief.py` / `script_research_packet.py` / `dvsu_research_handoff.package_brief` are kept
     ONLY because `factual_research_readiness` and the v2 adapter's `script_brief_readiness` still read
     them; they no longer feed any writer. Candidates for the next research-side simplification.
   - Tests deleted by name in `test_machine_documentary_hold.py` (136) included the old
     `check_machine_script_preview_readiness` tests; the new readiness is covered in
     `test_dvsu_script_v2.py` but a direct executor-level readiness test would be worth adding.
   - Roster-size formula question (thesis-driven 24-30 vs minutes-per-machine) still needs Ryan's call.
   - VPS git remote PAT rotation (Ryan only).

## Gotchas learned this session (also in tasks/lessons.md)
- Hand-picked deletion lists miss the closure; the AST fixpoint tool
  (`deadcode_fixpoint.py`, kept only in this session's scratchpad - recreate from lessons.md if needed)
  found 86 executor orphans in six rounds. References in comments/docstrings do not count.
- Never pipe a background test run through `tail`: it hid 245 of 290 failures until a rerun to a file.
- Replacing a block by line span can swallow the line after it - the voice stage's "Preparing the voice
  track" progress line vanished and only a functional test caught it. Diff the span edges.
