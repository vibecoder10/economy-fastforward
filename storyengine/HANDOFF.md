# HANDOFF - 2026-09-21 Agent LLM relay built + deployed; first Call 3 run parked waiting for MCP answers

## State
- Prod: `9930c3da5` deployed, healthy, idle (`se.sh health` 15:18 UTC). Migration 163 applied.
- Branch: `main` == `origin/main` at `ccf5874f`. Not mine, left alone: `tasks/decisions.md` (uncommitted edit from
  another session) and untracked `storyengine/jev-key-box.html`.
- Shipped: agent LLM relay - a workspace opted in via `tenants.agent_llm_relay` has the MCP agent answer the real
  pipeline's model calls (`agent_relay.py`, `agent_relay_client.py`, migration 163, MCP tools
  `list_pending_llm_requests` + `answer_llm_request`, guide hint `agent_llm_relay.pending_requests`). 18 new tests, zero
  new failures vs a clean baseline. Design + deviations: `docs/agent-llm-relay-2026-09-21/DESIGN.md`.
- Relay is ON for one tenant only: `561b872d-7b73-45e3-9c44-7f30c3566eda` (Designed Vs Used; owns video `6ac28204-...`).
  It has a stored-but-dead Anthropic key, so the flag (not key presence) decides.
- Verified live: executor picks `AgentRelayClient`; request parks scoped to the video with `web_search`; the MCP
  `get_production_guide` shows `pending_requests: 1`; `get_workspace_info` shows `agent_llm_relay: true`.
- NOT done: answering via `answer_llm_request` (unproven live), Holland's finished card, Drive export, no-spend replay.
- A driver is parked NOW: VPS pid 1977744, log `/tmp/relay_drive.log`, machine "USS Holland (SS-1)", request
  `83faa295-30f8-4eec-a49e-57ead0954b0a` (slot 1 of 6, `{"answer","source_url","quote"}`). Its 30-min wait ends ~15:44 UTC.

## Next action (start here cold)
Confirm this session has the new tools: ToolSearch `select:mcp__storyengine__list_pending_llm_requests,mcp__storyengine__answer_llm_request`.
(The deploying session held a frozen 98-tool list; a FRESH session gets all 100. If they're missing, the MCP connection
is stale - start another session.) Then:
1. `list_pending_llm_requests {video_id: "6ac28204-681c-4839-9d11-6c3ba57b7b6e"}`; per request do the real web search the
   prompt asks (primary/institutional sources over Wikipedia), reply via `answer_llm_request` with ONLY the JSON asked.
   Six slots: problem, design, trade_off, outcome_candidates, surprising_fact, contrast. Next one appears ~2s later.
2. If the driver expired (`se run 'pgrep -af relay_drive'` is empty), re-attach - answers already given replay free:
   `scp storyengine/scripts/relay_drive_one_machine.py storyengine-vps:/tmp/` then
   `se run 'export SE_ROOT=$HOME/projects/economy-fastforward/storyengine; nohup $SE_ROOT/backend/venv/bin/python3 /tmp/relay_drive_one_machine.py 561b872d-7b73-45e3-9c44-7f30c3566eda 6ac28204-681c-4839-9d11-6c3ba57b7b6e "USS Holland (SS-1)" > /tmp/relay_drive.log 2>&1 < /dev/null &'`
3. On `[drive] RESULT` in the log: check Holland's `unit_research_cards` (`se db`), that the pipeline's own gates passed,
   the Drive export landed in folder `1cPXLQN1...`, then the no-spend proof: re-run the driver -> zero new rows in
   `agent_llm_requests`, immediate result.
4. Then decide how many more machines (20 = 120 requests). Phase 2 (script, Call 4) stays untouched.

## Open threads
- One-machine research has no MCP tool: MCP `research` = `run_research` = roster discovery (Calls 1-2, would REGENERATE
  the roster); `/api/pipeline/machine-research-one` is a synchronous HTTP route. A real MCP tool/background route would
  remove the driver script - worth building once Call 3 is proven.
- Roster images for the test video are 0/20; bulk `run_unit_research` refuses until gathered (one-machine doesn't need it).
- Call 4 (script) uses `DurableScriptClient`, which won't resubmit an uncertain request - a relay wait that times out
  or is killed by a deploy there needs a reconcile. Phase 2.
- Test roster is hand-composed (Claude-written, not web-verified) - keep / regenerate / discard.
- SECURITY (still open): the VPS git remote URL embeds a GitHub PAT (`~/projects/economy-fastforward/.git/config`); rotate it.
- Stale test, pre-existing: `test_s7_a_scene_action.py::test_migration_154_is_next_free_number`.

## Gotchas learned this session
- A user-level MCP server's tool list is frozen at session start; `reconnect_session_connector` only re-dials failed
  claude.ai connectors. Ship new MCP tools in one session, drive them from the next.
- `se devtoken` binds to Ryan's default tenant (`ee93e6d1...`), not the DVSU tenant.
- `se run 'cmd &'` hangs the ssh call unless stdin is `< /dev/null`; env prefixes on the same line aren't visible to `$var` there.
- zsh doesn't word-split unquoted `$var` (use `xargs`) and `grep --include=*.py` needs quotes; `se logs` takes `backend|frontend|worker`.
- Mutation-check new tests: my first "replay is instant" test passed with replay deleted; fixed with a 30s poll + 1s `wait_for`.
