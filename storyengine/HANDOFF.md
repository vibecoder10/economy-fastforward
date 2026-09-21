# HANDOFF - 2026-09-21 Clean slate: suite green, machine research visible, MCP tools for the by-hand run

## Where things stand
- Prod: `da3db6b0b` deployed and healthy. `main` == `origin/main`. Backend suite **5680 passed, 0 failed** (was 88 red).
  Frontend: tsc clean, 58 vitest pass, production build passes. Not mine, left alone: `tasks/decisions.md` (uncommitted
  edit from another session) and untracked `storyengine/jev-key-box.html`.
- Pipeline being rebuilt step by step (legacy steps deleted on purpose): **Roster -> Gather images -> Research -> Script ->
  Voice -> Pictures -> Video**, driven through the StoryEngine MCP. **No Anthropic key exists on purpose**; the agent LLM
  relay answers model calls instead. Test video `6ac28204-681c-4839-9d11-6c3ba57b7b6e`, tenant
  `561b872d-7b73-45e3-9c44-7f30c3566eda` ("Designed vs Used", relay ON).
- State of that video: Roster 20/20 done. Gather images 0/20. Research **1/20** (USS Holland verified; Drive export
  `Every US Submarine Class Ever Built (2026)/machines/uss-holland-ss-1.md` under folder `1cPXLQN1Xs5bWa2lPoQ2KL5ufJrA4ZqRU`).
  The other 19 machines are for Ryan to run by hand to test the whole research phase.

## How to run one machine by hand (new, live)
1. `get_production_guide {video_id}` - `next_step.tool` now names the tool for the step.
2. `research_machine {video_id, machine}` - free, relay-only, returns at once; the run waits in the background.
   Name is matched to the locked roster (case-insensitive); a wrong name returns the valid list. One machine at a time.
3. `list_pending_llm_requests {video_id}` -> do that prompt's own web searches (primary/institutional sources; only quote
   text you actually saw) -> `answer_llm_request` with ONLY the JSON asked. Six requests per machine (problem, design,
   trade_off, outcome_candidates, surprising_fact, contrast); each next one appears ~2s after an answer.
4. Done when the guide's research stage advances and the Research tab shows the card VERIFIED (UI shows it now).
   Re-running a machine replays cached answers for free (proved live on Holland: no new requests).
- **Gather images is different:** `gather_roster_images {video_id}` is PAID and quote-gated (no `confirm_token` = quote only). It does NOT go
  through the relay: its photo judge calls a vision model directly (Anthropic key if the workspace has one, else Kie - see the Luna bullet below).
  `research_machine` does NOT need images gathered.
- **Gather images photo check = Kie gpt-5-6-luna (built 2026-09-21, tested, NOT yet deployed).** Ryan picked cheap Kie; Gemini Flash could not be
  tested (Kie's Gemini and Claude endpoints were down all morning: HTTP 200 `{"code":500}` / 530), and Ryan pointed at Luna ($0.056/M in,
  $0.336/M out, `POST /codex/v1/responses`, `input_image` data URLs, json_schema `text.format` works). Replay of 3 saved Sonnet judgments
  (Thresher, Holland, Los Angeles): same selected photo 3/3, identity agreement 28/31 (Luna stricter on wrong-ship photos), $0.0023-0.0026 per
  machine, 110-145 s per machine at medium reasoning, so Gather images now runs 4 machines at once (`ROSTER_GATHER_CONCURRENCY`, ~10-12 min for 20). Quote now $0.01/machine ($0.20 for 20).
  Rollback: `REFERENCE_JUDGE_PROVIDER=kie_claude` in the VPS env. Direct Anthropic is still used first when a key exists. Backend suite 5693 passed.
  Not touched: `static_docu._vision_yes_no` / `_vision_confirms` still call Kie Claude directly (other flows).
  **Next: commit, `git push origin main` from the Mac, `se deploy`, then `gather_roster_images {video_id}` (quote, then confirm) and walk the Gather tab.**

## What this session changed
- MCP: +2 tools (`gather_roster_images`, `research_machine`), 100 -> 102; guide names the tool; shared route guards/jobs in
  `routes/pipeline.py`; 15 new tests (`tests/functional/test_roster_stage_mcp_tools.py`), mutation-checked.
- UI: Research tab no longer says "Research Not Started" for roster-first videos (no headline); stage rail counts a passed card.
- Test suite: 88 red -> 0 by three parallel triage workers, every diff reviewed. Legacy tests for deleted steps were rewritten
  or deleted, not resurrected. **Two real bugs fixed:** `_machine_documentary_hold_roster_entries` wrongly returned nothing for
  rosters outside 3-40 machines (Gather images would sit empty), and `research_claim_assessment._replay_failed_assessment`
  could rebuild a passing receipt from a role-less failed narrative response. `schema.sql` backfilled with 7 missing tables.
- Config/data: deleted project `.mcp.json` (its unset `${STORYENGINE_MCP_TOKEN}` shadowed the working user-level entry ->
  401 "Not a valid agent token"; restart the app to get the MCP tools back in-session). Video title cleaned: was
  `“Every US Submarine Class Ever Built (2026)”` (literal curly quotes), now without; the Drive folder was renamed to match.
  `se devtoken` now writes to this repo's `frontend/.env.local`.
- Stand-in when the in-session MCP is down: the endpoint is stateless JSON-RPC, POST `https://storyengine.dev/api/mcp`
  `{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"...","arguments":{...}}}` with the `Authorization` header
  from the user-level `storyengine` entry in `~/.claude.json` (never print it).

## Open items (nothing else is hidden)
- **SECURITY (Ryan only):** the VPS git remote URL embeds a GitHub PAT (`~/projects/economy-fastforward/.git/config`); rotate it.
- Decide: the 20-machine test roster was hand-composed (Claude-written, not web-verified) - keep / regenerate / discard.
- The red "Run All stopped at Gather images ... Authentication failed" banner is a Sept 19 failure from before the relay; it
  is accurate history, not a live bug, and clears when a new task runs.
- Possible small product gap: the rebuilt photo selector dropped the old launch/commission-year search hints (same-name ships).
  Dead code left in place: `static_docu._recover_cached_roster_reference`; `run_research` has an unreachable prefetch dispatch
  for static_docu. `schema.sql` still lacks the columns migrations 157/158 added to `production_queue` (no test checks it).
- One-machine research leaves `research_payload.research_phase` at `roster_complete`; the UI and rail handle it, but a real
  "researching" phase would be cleaner.
- Call 4 (script) uses `DurableScriptClient`, which will not resubmit an uncertain request - a relay wait killed by a deploy
  there needs a reconcile. Phase 2, untouched.
- A deploy restarts the API and kills an in-flight `research_machine` wait; just call the tool again - answered requests replay.

## Gotchas learned
- A project `.mcp.json` entry with an unset `${VAR}` shadows a same-named user-level entry; "Not a valid agent token" is the
  `se_agent_` prefix check, not a revoked token.
- A user-level MCP tool list is frozen at session start; new tools need a fresh session (or the HTTP stand-in above).
- `se db` output caps ~32KB - query fields piecemeal (`jsonb_each`); cards live in `videos.research_payload`, not a table.
- `rclone cat`/`lsl` take ONE `remote:path` arg; `lsl` has no `-R`. Folder names with curly quotes need exact characters.
- zsh does not word-split `$var` (use `xargs`); `se run 'cmd &'` needs `< /dev/null`; `git worktree` test runs need the
  gitignored `remotion-video/public` folder or 28 `test_custom_film_remotion` tests fail (environment, not code).
- Mutation-check new tests: stash the source change and confirm the test fails without it.
