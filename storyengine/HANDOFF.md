# HANDOFF - 2026-09-21 DVSU roster gate + Drive folder fix built, pushed, verified; awaiting deploy

## State
- `main` == `origin/main` (`559eebee` + this handoff commit), linear. VPS checkout
  `~/projects/economy-fastforward` is fast-forwarded to the same commit. **Prod backend is still running
  the OLD code and env** (no restart yet) - both fixes below go live on the next deploy.
- VPS `storyengine/.env` now has `DVSU_RESEARCH_DRIVE_FOLDER_ID=1cPXLQN1Xs5bWa2lPoQ2KL5ufJrA4ZqRU`
  (only read at process start).
- Full suite (backend venv): no new failures vs a clean baseline; +4 passing tests total this session.

## Shipped to main this session
1. `2f1a3e45` - `_live_roster_gate` no longer requires `independent_selection_audit` for DVSU v2
   (`factual_100_v1`) rosters (v2 skips that audit by design). Cause of production_guide "roster:
   not_started" for `6ac28204-681c-4839-9d11-6c3ba57b7b6e`; it also blocked run_unit_research and
   roster-image gathering. Verified on the VPS against the video's REAL saved payload: gate now
   returns passed=true, 20 machines, no warnings.
2. `559eebee` - Drive export targets a Shared Drive folder by ID: `google_client.py` passes
   supportsAllDrives/includeItemsFromAllDrives on create_folder/search_folder/search_file/upload_file;
   `dvsu_roster_v2.research_root_folder()` uses `DVSU_RESEARCH_DRIVE_FOLDER_ID` (name lookup when unset),
   used by both roster and machine-packet exports. Live-verified: real export from the VPS with the
   backend's credentials landed in folder `1GP07If5NlbeC8smSooXhCJgrL37DUQrq`, whose parent is
   `1cPXLQN1...` (Ryan's intended Shared Drive folder).

## Next action (start here cold)
0. DONE this evening: deployed `93a47eb3`; MCP `get_production_guide` for `6ac28204...` shows Roster = done,
   next_step = image_gather. Drive fix is live (env var set before the restart); the two old test files remain in
   the old folder `1H7uG1Yd...` (a fresh copy is in the right place) - trash or leave, Ryan's call.
1. **Build the agent LLM relay** so the MCP runs the real pipeline with Claude answering model calls (Ryan:
   "the whole point of the mcp is to run the pipelines exactly as if it had an api key"). Full design:
   `storyengine/docs/agent-llm-relay-2026-09-21/DESIGN.md` (block-and-wait `AgentRelayClient` subclass of
   AnthropicClient overriding `generate()`, `agent_llm_requests` table with fingerprint replay, MCP tools
   `list_pending_llm_requests` + `answer_llm_request`, enabled per tenant only when no API key). Follow
   structured-workflow (trace -> build bottom-up -> verify); it touches >3 files.
2. Then drive Call 3 for ONE machine through the MCP on video `6ac28204...` (real web research by Claude,
   answers via the relay), confirm the Drive export lands in `1cPXLQN1...`, and the no-spend replay proof.
3. Only after that: more machines / script stage. Phase 2 stays untouched until Phase 1 closes.

## Open threads
- No Anthropic API key exists for this tenant (bot_activity 401s); real non-mocked runs fail until fixed.
- Test video `6ac28204...` holds a hand-composed submarine roster (Claude-written, not web-verified) -
  keep / regenerate once a key exists / discard.
- **SECURITY: VPS git remote URL embeds a GitHub personal access token in plain text**
  (`~/projects/economy-fastforward/.git/config`); it also appeared in session output. Rotate it and switch to
  a deploy key or credential helper.
- VPS repo pre-push hook (`.githooks`) blocks pushes of 3+ files unless `tasks/lessons.md` and
  `tasks/todo.md` are updated in the commit.
- An untracked `storyengine/jev-key-box.html` appeared locally mid-session (not from this work) - left alone.

## Gotchas
- Ryan's rule: keep git clean yourself - fetch at start, fast-forward main, linear commits on main, remove
  worktrees/branches you create. Never leave him a merge to remember.
- Context-ceiling hook now warns at 400k (was 150k): `~/.claude/scripts/context-ceiling-warn.py`.
- zsh: `echo =====` errors (`=cmd` expansion) - quote it.

---
paste this to start the next session:
Resume StoryEngine. Read HANDOFF.md, then storyengine/docs/agent-llm-relay-2026-09-21/DESIGN.md. Next action:
build the agent LLM relay (MCP-driven pipeline on Claude's usage) per the design, bottom-up with tests, then
drive DVSU Call 3 for one machine on video 6ac28204-681c-4839-9d11-6c3ba57b7b6e through the MCP.
