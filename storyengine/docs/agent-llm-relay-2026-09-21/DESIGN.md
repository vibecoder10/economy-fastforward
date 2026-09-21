# Agent LLM relay - run StoryEngine's real pipeline with Claude (via MCP) answering where the API key would

Status: v1 BUILT 2026-09-21 (unit-tested; not yet deployed / live-verified). Author: Osiris session 2026-09-21.

Build deviations from the design below (found while tracing the code):
- Injection is the pipeline executor only. Request-scoped sites (`_resolve_tenant_anthropic_client`,
  `rewrite_scene_text`) are NOT relayed: block-and-wait would hang the very MCP call the agent must
  answer from. Those tools already have free "do it yourself" twins (`edit_scene_text`, ...).
- The relay client is scoped to a video by `PipelineExecutor._install_cancel_support(video_id)` calling
  `client.bind(video_id, should_cancel)` - `generate()` itself has no video argument.
- Enablement flag is a `tenants.agent_llm_relay` boolean (default false), set by an operator with SQL, and it is
  AUTHORITATIVE - flag on = relay, regardless of stored keys. The design said "only when the tenant has NO key",
  but the DVSU tenant has a stored-but-dead key (out of credits / 401), so "has a key" can't decide it.
- `answer_llm_request` on an already-answered request REPLACES the answer (needed to correct one the stage's
  parser rejected: the identical request would otherwise replay the bad answer forever).
- Known limit: Call 4 (script paragraph) goes through `DurableScriptClient`, which refuses to resubmit an
  uncertain request. A relay wait that times out or is killed by a deploy leaves that operation
  `submitted` -> needs reconcile. Phase 2; Call 1-3 are unaffected (their checkpoint is the request row).

Goal (Ryan): "the whole point of the MCP is to
run the pipelines of StoryEngine exactly as if it had an API key" - the website/pipeline logic runs unchanged;
the connected MCP agent (Claude, on the user's subscription) supplies the model responses.

## Why what exists is not enough
- `submit_research` / `submit_script` are hand-offs of a FINISHED result. `submit_research` overwrites the whole
  `research_payload` and sets `ready_for_scripting`, knows only the legacy shape, and skips the real stage code
  (DVSU v2 Call 1-3 never run). So it cannot verify or drive v2.
- The `research` / `script` verbs run the real code but call the model with a key; this tenant has none
  (`bot_activity` 401s; executor init logs "AnthropicClient skipped" -> `self._pipeline.anthropic = None`).

## The hook that already exists
`AnthropicClient.generate()` (skills/video-pipeline/shared/clients/anthropic_client.py) is the single choke point
for model calls (the only raw SDK calls, `messages.create/stream`, are inside it). Every higher-level method
(`generate_beat_sheet`, ...) and every DVSU call goes through it with (prompt, system_prompt, model, tools,
max_tokens, temperature). `shared/research_response.request_fingerprint` already hashes exactly those inputs.

## Design
`AgentRelayClient(AnthropicClient)` - overrides only `generate()`; same signature, returns the same text.
1. Compute `fingerprint` (reuse `request_fingerprint`). Look up `agent_llm_requests` (tenant_id, video_id, fingerprint).
   - answered -> return `response_text` immediately (replay: survives restarts, retries, re-runs; identical
     request never asks twice).
   - none -> insert a `pending` row (prompt, system_prompt, model, tools, max_tokens, temperature, stage label).
2. **Block-and-wait like a slow API call**: poll the row every ~2s (`await asyncio.sleep`), no exception plumbing
   and no re-running the verb. Per-request timeout (default 30 min) -> raise a clear error; the row stays and a
   later re-run replays any answers already given. Honors `should_cancel()`.
3. New MCP tools (routes/mcp.py, same auth/tenant scoping as the other tools):
   - `list_pending_llm_requests(video_id?)` -> id, stage, model, prompt, system_prompt, tools (so the agent knows to
     use its own web search), max_tokens, age.
   - `answer_llm_request(request_id, response)` (and a batch form) -> stores verbatim text; the waiting stage
     resumes within ~2s and moves to the next call. `response` must be exactly what the model would return
     (e.g. the JSON the prompt asks for) - the pipeline's own parsers and gates judge it, same as a real model.
4. **Injection / enablement:** where the pipeline builds its client - executor init (pipeline_executor.py ~9368,
   env `ANTHROPIC_API_KEY`), and the tenant-BYOK resolvers (routes/mcp.py `_resolve_tenant_anthropic_client`,
   routes/videos.py `rewrite_scene_text`) - use `AgentRelayClient` iff the tenant has NO key AND the workspace has
   relay enabled (new setting `agent_llm_relay`, default off). A real key always wins -> "exactly as if it had a key".
5. Visibility: `get_production_guide` / `get_video` and the pipeline task status surface "waiting for agent:
   N pending" so neither the agent nor the UI thinks the run hung.

## Files (v1)
migration (`agent_llm_requests`; verify column existence live, not just schema.sql) - `agent_relay_client.py`
(client) - executor/route client wiring (2-3 sites) - `routes/mcp.py` (2 tools + dispatch) - settings flag -
`production_guide.py` hint - tests (relay unit, stage wait/resume with a fake answerer, tenant isolation).
Update SYSTEM_STATE.md (new module/table/tools).

## Rules / risks to honor
- Money: zero provider spend for relayed calls; other paid generation (images, clips, voice) keeps its quote+yes gate.
- Trust: same as `submit_*` - an authenticated tenant agent; answers are stored data, size-capped, never executed.
  Pending prompts are pipeline-built (may embed prior research text) - tenant-scoped reads only.
- Long waits occupy a worker slot; deploy/restart kills the wait but not the answers (fingerprint replay resumes).
- v1 scope: the `generate()` choke point only (covers DVSU roster Calls 1-2, Call 3, script). CLI bots in
  `skills/*` that build their own `AnthropicClient()` are out of scope.
- 120 requests for a 20-machine Call 3 is real volume (6 searches x 20). Verify first with ONE machine
  (recipe: tasks/live-verification-queue.md, DVSU Phase 1 item 2), then decide how many to run.

## Verification (run it like a user)
Drive the whole thing through the MCP against the test video `6ac28204-681c-4839-9d11-6c3ba57b7b6e`: quote/run the
`research` verb -> `list_pending_llm_requests` -> answer each with real web-searched content -> watch
`get_production_guide` advance -> check Drive export lands in folder `1cPXLQN1...` -> no-spend replay proof
(re-run, zero new pending rows).
