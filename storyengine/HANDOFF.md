# HANDOFF - 2026-09-21 Agent LLM relay built + deployed; Call 3 (Holland) parked, waiting for MCP answers

## State
- `main` == `origin/main`, prod runs `9930c3da` (relay + its follow-up). Migration 163 applied. Prod healthy, idle.
- **Relay is ON for exactly one tenant:** `tenants.agent_llm_relay = true` for `561b872d-7b73-45e3-9c44-7f30c3566eda`
  ("Designed Vs Used", owner of test video `6ac28204-681c-4839-9d11-6c3ba57b7b6e`). All other tenants: off.
- **A live run is parked right now.** A driver process on the VPS (pid 1977744, started 15:13:56 UTC, log
  `/tmp/relay_drive.log`) is running Call 3 for machine **"USS Holland (SS-1)"** (act 1). Its first model call is
  waiting as request `83faa295-30f8-4eec-a49e-57ead0954b0a` (stage `_call_one_slot`, slot "why the authority
  needed it", `web_search` allowed, JSON `{"answer","source_url","quote"}` expected). The wait times out at ~15:44 UTC;
  if it has expired, just re-run the driver (command below) - every answer already given is replayed, nothing re-asked.
- Verified live so far: executor picked `AgentRelayClient`; request parked scoped to the video with the `web_search`
  tool; `get_production_guide` shows `agent_llm_relay.pending_requests: 1`; `get_workspace_info` shows
  `agent_llm_relay: true`.
- NOT yet verified live: `list_pending_llm_requests` / `answer_llm_request` (deployed, unit-tested, but the session
  that deployed them held a pre-deploy MCP connection with the old 98-tool list - user-level MCP servers can't be
  re-dialed mid-session). A FRESH session gets all 100 tools.

## Next action (start here cold)
1. Confirm the new tools exist: ToolSearch `select:mcp__storyengine__list_pending_llm_requests,mcp__storyengine__answer_llm_request`.
2. `list_pending_llm_requests {video_id: 6ac28204-...}` -> for each request: run the real web search the prompt
   asks for (use WebSearch/WebFetch; primary/institutional sources over Wikipedia), answer with
   `answer_llm_request` = ONLY the JSON the prompt specifies. Call 3 for one machine = 6 slots (problem, design,
   trade_off, outcome_candidates, surprising_fact, contrast); the next request appears ~2s after each answer.
3. When the driver prints `[drive] RESULT`, check: `unit_research_cards` for Holland in `research_payload`
   (`se db`), the pipeline's own gates passed (no warnings), Drive export landed in folder `1cPXLQN1...`
   (`DVSU_RESEARCH_DRIVE_FOLDER_ID`), then the **no-spend replay proof**: re-run the driver, expect zero new rows in
   `agent_llm_requests` and an immediate result.
4. Restart the driver if it expired (same command re-attaches to the same requests):
   `se run 'export SE_ROOT=$HOME/projects/economy-fastforward/storyengine; nohup $SE_ROOT/backend/venv/bin/python3 /tmp/relay_drive_one_machine.py 561b872d-7b73-45e3-9c44-7f30c3566eda 6ac28204-681c-4839-9d11-6c3ba57b7b6e "USS Holland (SS-1)" > /tmp/relay_drive.log 2>&1 < /dev/null &'`
   (script is `storyengine/scripts/relay_drive_one_machine.py`; scp it to `/tmp/` first if missing). Note: `se run` with
   a bare `&` can hang the ssh call - redirect stdin from /dev/null as above.
5. Only after that: decide how many more machines (20 machines = 120 requests). Phase 2 (script) stays untouched.

## Why a driver script, not the MCP `research` verb
- MCP `research` = `run_research` = roster discovery (Calls 1-2). It would REGENERATE the roster, not run Call 3.
- Call 3 for one machine lives at `POST /api/pipeline/machine-research-one/{video_id}`, a SYNCHRONOUS HTTP handler
  (would hold the request open while waiting) and `se devtoken` binds to Ryan's default tenant, not DVSU. So the
  driver runs the same executor method (`run_one_machine_research`) in its own VPS process. Candidate follow-up:
  a real MCP tool / background route for one-machine research so no driver is needed.

## Shipped this session (all on main, deployed)
- `5168dbc0` Agent LLM relay: migration 163, `agent_relay.py`, `agent_relay_client.py`, executor wiring, MCP tools
  `list_pending_llm_requests` + `answer_llm_request`, production_guide hint, 17 tests. Design + deviations:
  `docs/agent-llm-relay-2026-09-21/DESIGN.md`.
- `9930c3da` bind the video in `run_one_machine_research` / `run_roster_selection` / `run_story_bible` (they skip
  `_install_cancel_support`), +1 test.
- Suite: zero new failures vs a clean baseline (the ~70-85 failing tests are pre-existing).

## Decisions made / found
- Relay flag is AUTHORITATIVE (flag on = relay). Design said "only when the tenant has no key"; the DVSU tenant has a
  stored-but-DEAD Anthropic key (out of credits 09-12, "Authentication failed" 09-19), so "has a key" can't decide.
- Request-scoped MCP tools (`generate_modeled_ideas`, `regenerate_scene_text`, ...) are NOT relayed: block-and-wait
  would deadlock the call the agent must answer from. Only background/executor runs use it.
- Known limit: Call 4 (script) uses `DurableScriptClient`, which won't resubmit an uncertain request - a relay wait
  that times out / is killed by a deploy there needs a reconcile. Phase 2.

## Open threads
- Roster images for the test video are not gathered (`0/20`); bulk `run_unit_research` refuses until they are.
  One-machine research doesn't require it. Image gathering may itself call a model - unchecked.
- Test video roster is hand-composed (Claude-written, not web-verified) - keep / regenerate / discard.
- **SECURITY: VPS git remote URL embeds a GitHub personal access token** (`~/projects/economy-fastforward/.git/config`);
  rotate it, switch to a deploy key or credential helper. (Still open from last handoff.)
- Another session has an uncommitted edit to `tasks/decisions.md`; untracked `storyengine/jev-key-box.html` - both left alone.
- Pre-existing stale test: `test_s7_a_scene_action.py::test_migration_154_is_next_free_number`.

## Gotchas
- Ryan's rule: keep git clean yourself - fetch at start, linear commits on main, remove worktrees/branches you create.
- zsh doesn't word-split unquoted `$var` (use `xargs`), and `grep --include=*.py` needs quotes.
- Push hook: 3+ changed files needs `tasks/lessons.md` + `tasks/todo.md` in the commit.
- `se logs` service names: `backend|frontend|worker` (not the systemd unit names).

---
paste this to start the next session:
Resume StoryEngine. Read HANDOFF.md. The agent LLM relay is deployed and a Call 3 run for "USS Holland (SS-1)" on
video 6ac28204-681c-4839-9d11-6c3ba57b7b6e is parked waiting for answers. Next action: confirm the new MCP tools
(list_pending_llm_requests / answer_llm_request) are available, answer the pending requests with real web-searched
content, and finish the one-machine Call 3 + Drive export + no-spend replay proof per HANDOFF.md.
