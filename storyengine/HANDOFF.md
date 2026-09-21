# HANDOFF - 2026-09-21 Agent LLM relay PROVEN end to end on one machine (USS Holland, Call 3)

## State
- Prod: `9930c3da5` deployed, healthy, idle. Migration 163 applied. Nothing deployed this session.
- Branch: `main`. Not mine, left alone: `tasks/decisions.md` (uncommitted edit from another session) and untracked
  `storyengine/jev-key-box.html`.
- Relay is ON for one tenant only: `561b872d-7b73-45e3-9c44-7f30c3566eda` (Designed Vs Used; owns video
  `6ac28204-681c-4839-9d11-6c3ba57b7b6e`). Stored-but-dead Anthropic key, so the flag (not key presence) decides.
- **PROVEN live (this session):** all 6 Call 3 requests for "USS Holland (SS-1)" answered through
  `list_pending_llm_requests` / `answer_llm_request` with real web-searched, sourced content (Naval Submarine League
  archive, Naval Undersea Museum, NavSource). The parked driver resumed by itself, ~2s after each answer, and returned
  `status: completed`.
  - Pipeline's own gates: `unit_research_hold_validation` Holland `passed: true, warnings: []`;
    card `research_summary.passed: true`, `script_brief_readiness.passed: true`, provenance `captured`.
    (Cards live in `videos.research_payload->'unit_research_cards'`; there is no `unit_research_cards` table.)
  - Drive export landed: folder `1cPXLQN1Xs5bWa2lPoQ2KL5ufJrA4ZqRU` ->
    `“Every US Submarine Class Ever Built (2026)”/machines/uss-holland-ss-1.md` (5548 bytes; all six slots with source +
    quote). Verify with `rclone lsl --drive-root-folder-id <id> "gdrive:<folder>"` (note the curly quotes in the name).
    The older sibling folder "Every US Submarine Class Ever Built test" is pre-existing, untouched.
  - No-spend replay: re-running the driver finished in 3s, 0 "waiting for the agent" lines, `agent_llm_requests` stayed at
    6 answered rows (same newest timestamp), and Drive was not re-exported.
- Cards for the other 19 machines are still "Factual research summary pending" - expected, nothing done there.
- **UI fix, verified LOCALLY, NOT deployed:** the video's Research tab said "Research Not Started" (gate was
  `!research.headline`; roster-first videos have no headline) and the stage rail said "detailed research has not started".
  Fixed in `ResearchTab.tsx` (roster mode counts as started; headline falls back to thesis) and `StaticDocuStageRail.tsx`
  (any passed card = in progress). Walked in the in-app browser as DVSU workspace: tab shows 1/20 VERIFIED, Holland
  expands to the saved summary + sources + per-claim assessment; rail says "1/20 ... ready". tsc clean, 14 vitest pass.
  Needs `se deploy <session> --with-frontend` (Ryan's yes, check `~/deploy.lock`) before it shows on prod.
- `se devtoken` wrote to a dead path (`~/economy-fastforward/...`); fixed to this repo's `frontend/.env.local`.
  To view the DVSU video locally: devtoken -> dev server -> nav workspace switcher -> "Designed vs Used".
- Cosmetic, not fixed: the video title itself contains curly quotes, so the UI shows doubled quotes and the Drive folder
  is named `“Every US Submarine Class Ever Built (2026)”`.

## Next action (start here cold)
1. **Fix the MCP connection first (Ryan's call, credential):** the `storyengine` MCP fails in this project with 401
   "Not a valid agent token". Cause: project `.mcp.json` sends `Authorization: Bearer ${STORYENGINE_MCP_TOKEN}` and that
   env var is not set anywhere (not in the app's environment, not in any shell rc, not in settings.json). The project
   entry shadows the WORKING user-level entry in `~/.claude.json`. Either set `STORYENGINE_MCP_TOKEN` (same `se_agent_...`
   token as `~/.claude.json`, e.g. via the `env` block in `~/.claude/settings.json`) and restart the app, or drop the
   project-level entry. Until then the MCP tools are absent in-session.
2. **Stand-in that works now:** call the same tools as plain JSON-RPC over HTTP. `POST https://storyengine.dev/api/mcp`,
   `{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"list_pending_llm_requests","arguments":{...}}}`,
   `Authorization` taken from the user-level `storyengine` entry in `~/.claude.json` (never print it). The endpoint is
   stateless (no initialize/session needed). A 40-line helper is trivial to rewrite.
3. **Decide how many more machines** (20 total, 6 requests each = 120). Each machine: run the driver, answer 6 slots with
   real searches. Driver command (VPS, re-attach-safe; answers already given replay free):
   `scp storyengine/scripts/relay_drive_one_machine.py storyengine-vps:/tmp/` then
   `se run 'export SE_ROOT=$HOME/projects/economy-fastforward/storyengine; nohup $SE_ROOT/backend/venv/bin/python3 /tmp/relay_drive_one_machine.py 561b872d-7b73-45e3-9c44-7f30c3566eda 6ac28204-681c-4839-9d11-6c3ba57b7b6e "<machine>" > /tmp/relay_drive.log 2>&1 < /dev/null &'`
   The driver's wait is 30 min; requests appear one at a time (next ~2s after each answer).
4. Phase 2 (script, Call 4) stays untouched.

## Answer-quality notes (from doing it)
- The stage's prompt demands every fact trace to a search result: many primary sites 403/404 to WebFetch (Smithsonian,
  usni.org, ussnautilus.org, history.navy.mil paths). What worked: Naval Submarine League archive
  (`archive.navalsubleague.org`), Naval Undersea Museum, NavSource. Only put in `quote` text you actually saw verbatim.
- Sources disagree on details (Holland's purchase price $150k vs $165k; end of service 1905 vs 1910). Surface the
  discrepancy inside the candidate `fact` rather than picking silently.

## Open threads
- One-machine research has no MCP tool: MCP `research` = `run_research` = roster discovery (Calls 1-2, would REGENERATE
  the roster); `/api/pipeline/machine-research-one` is a synchronous HTTP route. A real MCP tool/background route would
  remove the driver script - worth building now that Call 3 is proven.
- The driver truncates its `[drive] RESULT` log line at 4000 chars (not valid JSON afterward); read the card from
  `videos.research_payload` instead. `se db` output also caps ~32KB - query fields piecemeal (`jsonb_each`).
- Drive export is fail-soft and its result is discarded, so a failed export leaves no trace except a log warning. Consider
  recording the export result on the card.
- Roster images for the test video are 0/20; bulk `run_unit_research` refuses until gathered (one-machine doesn't need it).
- Call 4 (script) uses `DurableScriptClient`, which won't resubmit an uncertain request - a relay wait that times out
  or is killed by a deploy there needs a reconcile. Phase 2.
- Test roster is hand-composed (Claude-written, not web-verified) - keep / regenerate / discard.
- SECURITY (still open): the VPS git remote URL embeds a GitHub PAT (`~/projects/economy-fastforward/.git/config`); rotate it.
- Stale test, pre-existing: `test_s7_a_scene_action.py::test_migration_154_is_next_free_number`.

## Gotchas learned
- A user-level MCP server's tool list is frozen at session start; `reconnect_session_connector` only re-dials failed
  claude.ai connectors. A project `.mcp.json` entry with an unset `${VAR}` shadows a working user-level entry of the same name.
- `se devtoken` binds to Ryan's default tenant (`ee93e6d1...`), not the DVSU tenant.
- `se run 'cmd &'` hangs the ssh call unless stdin is `< /dev/null`; env prefixes on the same line aren't visible to `$var` there.
- zsh doesn't word-split unquoted `$var` (use `xargs`) and `grep --include=*.py` needs quotes; `se logs` takes `backend|frontend|worker`.
- `rclone cat`/`lsl` take ONE `remote:path` arg (join the folder path onto `gdrive:`); `lsl` has no `-R` and is already recursive.
- Mutation-check new tests: a "replay is instant" test once passed with replay deleted; fixed with a 30s poll + 1s `wait_for`.
