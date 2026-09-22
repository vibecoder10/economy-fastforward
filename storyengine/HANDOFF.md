# HANDOFF - 2026-09-22 - dvsu_script_v2 is the only script writer (built, tested, committed); submarine video staged for scripting on the relay; deploy pending

## State
- Prod: `8d4f2583d` deployed, healthy (`se health` 2026-09-22: frontend 200, no deploy lock). **This session's commit is NOT deployed.**
- Branch: `main` at `c1dd9547`, ahead of origin by 1, not pushed. Unstaged and not mine: `../tasks/decisions.md`
  (carries Ryan's uncommitted Jev entry plus my two new entries), untracked `jev-key-box.html`.
- Backend suite 5408 passed / 0 failed (baseline 5721; the difference is ~300 legacy-writer tests deleted with the writers). Frontend tsc, build, vitest clean.
- What shipped this session:
  - `backend/dvsu_script_v2.py`: DESIGN.md as code. One paid Sonnet call per machine, code-side audit instead of a referee call, one bounded repair, stateful roster-order hold, readiness, hand-submit door, fail-soft `02-script.md` Drive export. Design gaps closed: bridge context = every prior paragraph tagged by act + next machine's problem line; word band 95-120 target / 80-150 hard. 40 tests.
  - The three legacy writers are gone with no flag and no fallback: both branches inside `_run_static_script_hold` (now a one-line delegation), `factual_machine_pipeline.run_factual_script_hold`, `factual_machine_summary`'s writer+referee, `dvsu_script_operations.py`, 86 orphaned executor definitions, 12 legacy test files. Executor 22137 -> 17568 lines.
  - Every gate keys on the one contract `dvsu_script_v2` (readiness, preview/block/submit, voice gate for any roster video, resume-time stale recheck only for v2-written scripts). Frontend gates on it too; Anton panels replaced by "Sources cited".
  - `dvsu_research_v2.packet_from_verified_source_package`: the writer rebuilds the six-slot brief from the saved package (the Call-3 packet was never persisted).
  - Video `6ac28204-681c-4839-9d11-6c3ba57b7b6e` (Every US Submarine Class Ever Built) verified ready: 20/20 packets reconstruct, 7 acts + thesis saved, relay enabled and opted in, status advanced `approved -> ready_for_scripting` (the executor's script gate refuses `approved`).
- NOT done: the browser walk of the Script tab (cut at the context ceiling), the deploy, any paid script call.

## Next action (start here cold)
1. Ryan says "deploy". Then from this Mac: `git push origin main`, then `scripts/se.sh deploy <session-name> --with-frontend`, then `scripts/se.sh health` (expect `c1dd9547`).
2. Walk it like a user: `scripts/se.sh devtoken`, `preview_start {name: "storyengine"}`, open video 6ac28204 -> Script tab. Expect 20 cards "Ready to script", the free readiness check green, no console errors. Screenshot.
3. Script ONE machine on the relay first: MCP `script` tool is the whole-roster verb, so use `POST /api/pipeline/machine-script-preview/6ac28204-681c-4839-9d11-6c3ba57b7b6e` `{machine: "<first roster machine>", confirmed_paid_run: true}` (or the Script tab's "Run Script" button), then loop `list_pending_llm_requests` -> `answer_llm_request` (prompt asks for the JSON block shape in `dvsu_script_v2._OUTPUT_SHAPE`). Read the paragraph against `docs/gold-scripts/standards/DvsU_Script_Writing_System.md` with your eyes. Only then run the whole roster (MCP `script`, ~20 calls, bulk reuses nothing yet).

## Open threads
- `_machine_story_plan` + `_script_starvation_*` + `repair_promote_excerpt` (+ route in `routes/pipeline.py` + Research-tab button) survive only because that self-heal route still calls them; delete all three together (frontend change).
- `dvsu_script_operations` DB table is now unused - drop in a migration. `dvsu_script_brief.py` / `script_research_packet.py` / `dvsu_research_handoff.package_brief` feed only research readiness now - candidates for the next research-side cut.
- `docs/gold-scripts/grammar/` is committed; Ryan's two judgment calls in it (name-opener threshold, generic-praise severity) are unchanged and unreviewed.
- Roster-size formula (thesis-driven 24-30 vs minutes-per-machine) still needs Ryan's call. VPS git remote PAT rotation (Ryan only).

## Gotchas learned this session
- Hand-picked deletion lists miss the closure: an AST fixpoint (dead when no Name/Attribute/string ref outside its own span; comments don't count) found 86 executor orphans in six rounds. Recipe in tasks/lessons.md.
- Never pipe a background test run through `tail`: it hid 245 of 290 failures until a rerun to a file.
- Replacing a block by line span swallowed the line after it (the voice stage's "Preparing the voice track" progress line); only a functional test caught it. Diff span edges.
- The production guide says "script: start" for a video whose status is `approved`, but `run_script` refuses anything before `ready_for_scripting` - hand-run research via the relay never advances status; the free MCP `advance` verb fixes it.
