# Research-summary automation diagnostic

Scope: source-only diagnostic at the current local checkout. The reported worker observation—an autobuild task marked `completed` with “1 of 2 researched” while the saved 20-item roster remains blocked—was not read from the live database in this audit. The findings below identify the source paths capable of producing that mismatch. No provider, worker, HTTP endpoint, test, or production mutation was run.

## Intended automated path

1. A static-documentary autobuild treats research as required. Once runtime roster selection is complete, it first requires verified roster images, then calls `PipelineExecutor.run_unit_research`; only `ready_for_scripting` advances the video ([backend/actions.py:1941-1994](../../backend/actions.py#L1941-L1994)).

2. `run_unit_research` recomputes the roster gate, records `research_phase = "unit_research"`, runs the full locked-roster hold, persists `research_payload`, and moves the video to `ready_for_scripting` only if `unit_research_hold_validation.passed` is true. Otherwise it logs/returns `failed` with the aggregate validation warnings ([backend/pipeline_executor.py:12501-12581](../../backend/pipeline_executor.py#L12501-L12581)).

3. The source-producing unit of work is `run_one_machine_research`. It resolves the requested label against the locked roster and calls `_run_unit_research_hold(..., target_machine=matched)`. A rejected card returns `needs_review` with saved payload and warnings; a passing targeted card returns `completed` without advancing the complete-roster status ([backend/pipeline_executor.py:11334-11399](../../backend/pipeline_executor.py#L11334-L11399)). Thus a source package/card can be durably saved even though the overall research gate is still false.

4. The autobuild fallback exists specifically because the untargeted hold can refuse a fresh multi-machine roster. It walks the hold’s persisted `units` in locked-roster order through the one-machine operation, rather than bypassing the gate ([backend/actions.py:1485-1524](../../backend/actions.py#L1485-L1524)). It records per-machine attempted failure counts in `research_payload.roster_loop_attempts` and avoids redoing already-cleared entries on a resume ([1512-1519](../../backend/actions.py#L1512-L1519), [1563-1592](../../backend/actions.py#L1563-L1592)).

## Partial failure and the reported completed task

1. The fallback deliberately continues after a failed or `needs_review` machine, collects each machine’s warning, and returns `status="needs_review"` with a message formatted as `"{done}/{total} machines researched; ... still need review"` ([backend/actions.py:1758-1785](../../backend/actions.py#L1758-L1785)). This explains a message such as “1/2 machines researched” as a partial progress/park result, not a complete 20-item roster result.

2. Both autobuild branches pass that `needs_review` result directly to `_set_task_status` and return; they do not advance the video ([backend/actions.py:1982-1994](../../backend/actions.py#L1982-L1994), [2055-2079](../../backend/actions.py#L2055-L2079)).

3. `_set_task_status` intentionally normalizes every terminal status other than `failed` to `completed`. For `needs_review`, it sets an additive in-memory `needs_review=True`, but stores/polls the normalized task status as `completed` ([backend/routes/pipeline.py:504-538](../../backend/routes/pipeline.py#L504-L538)). Therefore a worker/task display that says `completed` alongside a partial “1/2 researched; ... needs review” message is source-consistent: it denotes a parked review result, not full research completion.

4. ARQ’s generic stage worker does the opposite for a direct `needs_review` stage result: it persists `failed` because the separate worker process cannot carry the in-memory flag ([backend/worker.py:104-143](../../backend/worker.py#L104-L143)). Autobuild does not use that generic runner; `arq_run_autobuild` delegates terminal status ownership to `make_autobuild_step` ([backend/worker.py:318-335](../../backend/worker.py#L318-L335), [448-465](../../backend/worker.py#L448-L465)). This route difference is material when interpreting worker status.

## Durable progress, retry, and reporting

* Per-machine source/card state is persisted in `machine_research_cards` and compatibility-mirrored in `research_payload`; aggregate readiness is rebuilt from compact validation rows. The aggregate report stores `ready_count`, `roster_count`, individual action/warning summaries, and `unit_research_hold_validation` ([backend/pipeline_executor.py:12283-12355](../../backend/pipeline_executor.py#L12283-L12355)).
* On retry, the automation reads current saved payload, builds pending work from hold units whose `passed` is false, and rereads a saved machine verdict after each operation ([backend/actions.py:1546-1561](../../backend/actions.py#L1546-L1561), [1608-1628](../../backend/actions.py#L1608-L1628)). It limits automatic research to two failed rounds per machine; after that it parks the item as needing manual one-machine research ([backend/actions.py:1706-1716](../../backend/actions.py#L1706-L1716)).
* The direct “research locked machines” route passes the executor’s returned status through `_set_task_status` ([backend/routes/pipeline.py:1317-1353](../../backend/routes/pipeline.py#L1317-L1353)). It shares the same normalization behavior, so `needs_review` can be shown as completed there as well.
* The Research UI does distinguish the underlying result: it counts cards with backend-owned readiness, disables approval unless all locked items pass, and renders `Verified`, `Revalidate needed`, `Needs review`, or `Not run` per roster entry ([frontend/src/components/production/ResearchTab.tsx:1199-1227](../../frontend/src/components/production/ResearchTab.tsx#L1199-L1227), [1382-1455](../../frontend/src/components/production/ResearchTab.tsx#L1382-L1455), [1648-1723](../../frontend/src/components/production/ResearchTab.tsx#L1648-L1723)).

## Existing test evidence

* `test_machine_2_failure_does_not_abort_remaining_roster` asserts that automation attempts later independent machines after one machine reaches `needs_review`, returns a message containing the partial count, and deliberately passes raw `needs_review` to the task setter; its comments explicitly note real task normalization to `completed` ([backend/tests/functional/test_g8_roster_research_loop.py:321-358](../../backend/tests/functional/test_g8_roster_research_loop.py#L321-L358)).
* `test_retry_only_re_researches_the_failed_machine_and_respects_attempt_bound` covers three resumptions: passed machines are not repeated, the remaining failure receives two automatic attempts, and the third pass parks it for manual one-machine research ([backend/tests/functional/test_g8_roster_research_loop.py:862-917](../../backend/tests/functional/test_g8_roster_research_loop.py#L862-L917)).
* `test_all_machines_pass_in_order_and_status_advances` only advances the video after every mocked roster item passes ([backend/tests/functional/test_g8_roster_research_loop.py:220-241](../../backend/tests/functional/test_g8_roster_research_loop.py#L220-L241)).

## Limits

This source audit does not prove whether the observed `1/2` message came from the 20-item video, a separate two-item target subset, an older task row, or a stale UI poll. Confirming that requires read-only correlation of the exact video ID, `background_tasks` autobuild row, current `videos.status`, `research_payload.unit_roster`, `unit_research_hold_validation.units`, and compact-card count. No implementation design is included here.
