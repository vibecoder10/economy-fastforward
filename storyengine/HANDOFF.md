# HANDOFF - 2026-09-21 Gather images done (20/20), Luna photo judge live, above-water preference in scoring

## Where things stand
- Prod: `4db5a66b4` deployed and healthy (the scoring change below is committed after it; see Next). Backend suite **5705 passed**.
  Not mine, left alone: `tasks/decisions.md` (uncommitted edit from another session) and untracked `storyengine/jev-key-box.html`.
- Pipeline being rebuilt step by step (legacy steps deleted on purpose): **Roster -> Gather images -> Research -> Script ->
  Voice -> Pictures -> Video**, driven through the StoryEngine MCP. The agent LLM relay answers Research/Script model calls.
  Test video `6ac28204-681c-4839-9d11-6c3ba57b7b6e`, tenant `561b872d-7b73-45e3-9c44-7f30c3566eda` ("Designed vs Used", relay ON).
  **That workspace DOES have a stored `anthropic_api_key` (saved Sept 18) and Anthropic rejects it as invalid (401).** The old handoff
  said none existed. Not touched (credential). The judge now falls back to Kie Luna on a rejected key, but Ryan should fix or delete it.
- State of that video: Roster 20/20 done. **Gather images 20/20 done** (guide says done). Research **1/20** (USS Holland verified; Drive
  export `Every US Submarine Class Ever Built (2026)/machines/uss-holland-ss-1.md`). The other 19 machines are for Ryan to run by hand.
- How Gather got to 20/20 (spend: about $0.02 of Luna; 8 photos judged, then Ryan said no more spending): the Luna sweep judged 8 machines
  (2 kept: Tang, Porpoise); the other 18 photos were **placed by hand** (Osiris viewed candidates, verified identity from the source
  caption/file title, hosted them, wrote receipts with `manual` set and no paid judge). Backup of the replaced rows:
  scratchpad `backup_reference_cache_2026-09-21.jsonl` (not in repo). All 18 are above-water shots (surfaced, dockside, dry dock, launch, on the ways).
- Why by hand: source discovery is the weak spot. "A-class"/"S-class" returned Mercedes cars, "Barracuda class (V-1 group)" returned German
  V-1 flying bombs, "F-class" returned British destroyers, "Skate class" returned a deck log. Fix idea: pass the roster entry's `role`/era
  (US submarine) into the Commons queries so class names stop colliding. Not built.

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
- **Gather images photo check = Kie gpt-5-6-luna (live).** Direct Anthropic is used first when a valid key exists; a rejected key (401/403) falls back
  to Luna. Replay of 3 saved Sonnet judgments: same photo 3/3, identity agreement 28/31, ~$0.0025/machine. Each judgment takes 110-145 s, so
  Luna gets a 420 s HTTP timeout, and the sweep runs 4 machines at once (`ROSTER_GATHER_CONCURRENCY`). Provider outages and rejected keys are NOT
  saved as permanent results (a rerun retries); deterministic 4xx, refusals and unreadable output still are. Quote is $0.01/machine.
  Rollback: `REFERENCE_JUDGE_PROVIDER=kie_claude`. Kie's Gemini and Claude endpoints were down that morning; `codex/v1/responses` stayed up.
  Not touched: `static_docu._vision_yes_no` / `_vision_confirms` still call Kie Claude directly.
- **Seed-photo preference (committed after the deploy, not yet on prod):** `reference_selection.choose_candidate(candidates, judgments, machine)` now
  nudges scores: +8 when a submarine photo's FILE TITLE says launch/dry dock/on the ways (captions are ignored, they mention launch dates),
  -8 when the judge's own limitations say the subject is small in the frame, -5 for text printed on the photo. Adjustments are recorded on the
  selection as `score_adjustments`. Checked offline against the 8 saved judgments (free): flips Barbel to the launch shot, Lafayette and Skipjack
  off the small-subject picks. NOT live-tested with a model. A bigger fix would add explicit `hull_exposure` / `prominence` fields to the judge schema;
  that needs a paid test (~$0.003/machine). Judge scores also rate "whole boat in frame" too high: it gave a sliver-of-frame Pomodon photo 98.

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
- **UX found walking the Gather tab (not fixed):** a red "Run All stopped at Research - Something went wrong. Please try again." banner still shows
  on a video whose Gather is done (stale history, vague wording); the "Retry missing images" button still shows at 20/20 verified;
  the panel subtitle says "Untitled documentary"; hand-placed photos show a "Single source" badge (judged ones say "Compared N photos").
- **Ryan's call:** fix or delete the invalid `anthropic_api_key` for "Designed vs Used" (Settings). Until then Anthropic 401s and Luna is the fallback.
- A session's in-app MCP connection goes stale after a deploy (502 on every call while /api/health is 200). Stand-in: POST the JSON-RPC to
  `https://storyengine.dev/api/mcp` with the header from the `storyengine` entry in `~/.claude.json`, or restart the app.
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
