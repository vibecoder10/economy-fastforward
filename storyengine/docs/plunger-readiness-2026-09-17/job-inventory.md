# Selected-machine job inventory

This is a read-only inventory of existing contracts. It does not select an implementation.

## Durable queue already present

- `backend/job_queue.py:19-39` has the fixed `_STAGE_HANDLERS` registry. It maps a stage name to an ARQ handler; it has no selected-machine research or preview-preparation stage.
- `backend/job_queue.py:42-108` exposes `enqueue_stage(arq_pool, stage, video_id, tenant_id, attempt=1, **stage_kwargs) -> str | None`. It builds the normal id as `"{stage}:{video_id}:{attempt}"` through `make_job_id` at `backend/job_queue.py:36-38`, and forwards stage kwargs to the handler.
- `backend/routes/pipeline.py:861-1011` provides `_enqueue_or_fallback(...)`. With ARQ it derives the next attempt from `background_tasks`, calls `enqueue_stage`, and persists `pending` with `job_id` and `attempt`; duplicate queue identity is a `409` (lines 903-929). If `durable_only` is false, Redis absence/failure falls back to process-local `BackgroundTasks` (lines 1004-1011).
- `backend/worker.py:39-216` provides `_run_stage(ctx, stage, executor_method, video_id, tenant_id, attempt, **method_kwargs)`. It persists `running`, then `completed`, `failed`, or `cancelled` rows in `background_tasks`; normal exceptions are re-raised for ARQ retry. It forwards declared kwargs to the executor method.
- Worker registration is explicit: `backend/worker.py:643-720` lists registered `arq_run_*` functions and per-stage timeout/retry limits. There is no `arq_run_machine_research_one`, machine-preview-preparation handler, or registration.

## Existing selected-machine routes

- `backend/routes/pipeline.py:1286-1317` is `POST /machine-research-one/{video_id}`. Its body is `MachineResearchRequest` (`backend/routes/pipeline.py:123-126`) with `machine`, `confirmed_paid_run`, and optional `source_urls`. It calls `PipelineExecutor.run_one_machine_research(video_id, machine, source_urls=...)` directly; it neither calls `_enqueue_or_fallback` nor returns a job id.
- `backend/routes/pipeline.py:1194-1221` is `POST /machine-script-preview/{video_id}`. Its body is `MachineScriptPreviewRequest` (`backend/routes/pipeline.py:112-114`) with `machine` and `confirmed_paid_run`; it too calls the executor directly and returns the completed result, without a job id.
- The frontend mirrors these synchronous shapes: `frontend/src/lib/api.ts:1059-1092` declares `MachineScriptPreviewResponse` and `runMachineScriptPreview`; `frontend/src/lib/api.ts:1094-1110` declares `OneMachineResearchResult` and `runOneMachineResearch`. Neither response type includes `job_id` or an operation/status URL.

## Selected machine and production-status evidence

- `backend/pipeline_executor.py:11481-11518` accepts `(video_id, machine, source_urls=None)`, checks the exact locked roster with `_locked_roster_item_for_machine`, snapshots `unit_roster`, and targets only `matched` in `_run_unit_research_hold`.
- Its docstring says it refreshes one locked card without replacing the rest of the roster (`backend/pipeline_executor.py:11482`). On its successful save, `backend/pipeline_executor.py:11542-11553` writes `status = original_status` and guards the write with equality of the saved `unit_roster` snapshot. This is evidence that successful selected-machine research preserves the existing video status and refuses a concurrent roster mutation.
- `backend/pipeline_executor.py:16552-16566` validates the selected locked machine before calling `_run_static_script_hold`; its docstring says the preview does not touch production script rows or video status. The route repeats that contract in `backend/routes/pipeline.py:1199`.

## Status, cancellation, and locking that exist today

- Durable queued task polling is video-wide: `GET /task/{video_id}` at `backend/routes/pipeline.py:3477-3510` reads `_get_task_status_async`, which falls back to the most recent `background_tasks` row at `backend/routes/pipeline.py:687-727`. It returns status/message/error/task_type, not `job_id` or machine identity.
- The matching frontend `TaskStatus` type at `frontend/src/lib/api.ts:2622-2651` also has no job id or selected-machine field; `getPipelineTaskStatus` is a video-wide poll at `frontend/src/lib/api.ts:1379-1380`.
- Cancellation is `POST /cancel/{video_id}` at `backend/routes/pipeline.py:3422-3455`. It calls `cancel_registry.request_cancel` for the whole video and reports a cooperative `cancelling` state; it does not accept a job id or machine.
- `_is_task_active(video_id, tenant_id, lane='main')` at `backend/routes/pipeline.py:612-684` is backed by the video-wide `generation_claims` authority. It can block conflicting work by lane, but selected-machine routes above do not call it before their direct executor calls.
- The all-machine `POST /machine-research/{video_id}` route at `backend/routes/pipeline.py:1319-1356` uses `BackgroundTasks` and the in-process status dict, not ARQ. It checks `_is_task_active`, but does not provide a durable job id.

## Material contract gaps for a durable asynchronous selected-machine preparation operation

1. No existing stage-map entry, ARQ handler, or worker registration invokes the selected-machine executor method with a `machine` argument.
2. The current selected-machine API responses are terminal synchronous results; they expose no durable job id, pending status, or selected-machine operation identity.
3. Current polling and cancellation are video-wide. They cannot report or cancel one selected-machine operation by job id while another video task has history.
4. The direct selected-machine routes have no `_is_task_active`/generation-claim reservation in their route path. Their locked-roster checks protect identity, but this inventory found no selected-machine-specific durable concurrency claim.
5. ARQ's generic `_run_stage` accepts kwargs, but only registered handler signatures can receive them. A new stage would need a matching handler and registry entry before the existing queue can dispatch it.

The existing code documents status preservation for successful one-machine research and for preview generation, but this inventory does not establish a durable asynchronous selected-machine preparation path today.
