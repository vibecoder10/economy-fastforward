# HANDOFF - 2026-09-21 Research 20/20 verified, relay photo judge proven live, matcher fix deployed

## Where things stand
- Prod: see the last deploy line in `~/deploys.log` (`main` == `origin/main`). Backend suite **5715 passed**.
  Not mine, left alone: `tasks/decisions.md` (uncommitted edit from another session) and untracked `storyengine/jev-key-box.html`.
- Pipeline being rebuilt step by step (legacy steps deleted on purpose): **Roster -> Gather images -> Research -> Script ->
  Voice -> Pictures -> Video**, driven through the StoryEngine MCP. The agent LLM relay answers Research/Script model calls.
  Test video `6ac28204-681c-4839-9d11-6c3ba57b7b6e`, tenant `561b872d-7b73-45e3-9c44-7f30c3566eda` ("Designed vs Used", relay ON).
  **The invalid `anthropic_api_key` for this workspace was DELETED on 2026-09-21 at Ryan's request** (Anthropic rejected it with 401; audit row in
  `bot_activity`). No key now -> Gather images judges through the MCP relay. **Ryan's rule: key installed -> use it; no key -> use the MCP relay.**
  Note the `NEXT_PUBLIC_DEV_TOKEN` (`se devtoken`) is Ryan's OTHER tenant (`ee93e6d1`), so Settings-API calls with it do NOT touch "Designed vs Used".
- State of that video: Roster 20/20 done. **Gather images 20/20 done. Research 20/20 done** (guide: "Detailed machine research is complete";
  Research tab shows 20/20 VERIFIED; every card's `script_brief_readiness.passed` is true). Next stage: **Script** (`get_production_guide` next_step).
  Research was done by Sonnet worker agents answering the relay one machine at a time (a run is strictly serial per video: a second start returns 409).
  Their answers lean on NavSource/Naval Submarine League/Johnston guides; some secondary (Naval-Encyclopedia, Covert Shores, WarHistory, GlobalSecurity) and a
  few figures conflict across sources (flagged inside the answers). history.navy.mil 404s, USNI/Britannica/si.edu are blocked for the fetch tool. A human spot check of
  the cards before Script is worthwhile (three answers carry small inferences: GW "Oct-Nov 1957", Ohio surprising-fact last line, Permit contrast wording).
- How Gather got to 20/20 (spend: about $0.02 of Luna; 8 photos judged, then Ryan said no more spending): the Luna sweep judged 8 machines
  (2 kept: Tang, Porpoise); the other 18 photos were **placed by hand** (Osiris viewed candidates, verified identity from the source
  caption/file title, hosted them, wrote receipts with `manual` set and no paid judge). Backup of the replaced rows:
  scratchpad `backup_reference_cache_2026-09-21.jsonl` (not in repo). All 18 are above-water shots (surfaced, dockside, dry dock, launch, on the ways).
- Why by hand: source discovery was the weak spot (now fixed in code, see the subject bullet below). "A-class"/"S-class" returned Mercedes cars, "Barracuda class (V-1 group)" returned German
  V-1 flying bombs, "F-class" returned British destroyers, "Skate class" returned a deck log.

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
- **Gather images judge (rule set by Ryan, deployed):** `reference_selection.judge_mode(tenant)` -> installed Anthropic key = use it (a rejected key
  surfaces "rejected the API key (HTTP 401)", no silent switch); no key = the MCP agent relay (`_judge_via_relay`): one parked request per machine listing the
  candidates' image URLs, the agent opens and looks at them and answers with the judgment JSON via `list_pending_llm_requests` / `answer_llm_request`
  (free, replays on re-run, model label `agent-vision`); no key and relay off = clear error. `gather_roster_images` is free with no quote in relay mode, quoted
  (~$0.10/machine, Sonnet-measured) only when a key is installed. **Kie Luna is opt-in only** (`REFERENCE_JUDGE_PROVIDER=kie_luna`, or `kie_claude`) and needs a Kie key; replay of 3 saved
  Sonnet judgments gave the same photo 3/3 at ~$0.0025/machine, 110-145 s each (420 s HTTP timeout). Provider outages and rejected keys are not saved as permanent results.
  **Relay judge PROVEN LIVE 2026-09-21** on proof video `dc217efd-d3a9-43f5-b731-73b634234953` ("US Interwar Submarine Classes (Gather proof)", 4 machines, hand-built
  roster payload; delete it whenever): 4 parked requests answered by looking at the images -> O-class = USS O-1 in dry dock, L-class = USS L-1 trials, R-class = R-boats at a dock,
  Narwhal class = no photo (only a nested group shot and an unrelated Sailfish) - correctly left unverified. Free, no spend.
- **Discovery always names the subject (deployed, unit-tested, not live-run):** `reference_sources.roster_subject(title, thesis)` reads the machine noun
  (submarine/aircraft/helicopter/tank/warship/locomotive/rocket/ship) and `_machine_documentary_hold_roster_entries` puts it in every entry's `facts["subject"]`;
  `_category` and the view criteria use it, so queries read `"S-class" submarine`, not `"S-class"`. **Live-confirmed on the proof roster:** every candidate was a submarine
  (no cars/bombs). Remaining gap: the query does not name the COUNTRY, so L-class and O-class also pulled British boats and a North Korean Sang-O (the judge rejected them
  by caption). Adding "US Navy" from the title/thesis to the subject would tighten it (small change in `reference_sources.roster_subject`, not done).
- **Seed-photo preference (deployed):** `reference_selection.choose_candidate(candidates, judgments, machine)` now
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

## Research gotchas learned this session (all in code, none in docs)
- **Brief budget:** after a machine's six relay answers the pipeline builds a compact writer brief from the ANSWER TEXTS and fails the card if it exceeds 6000 bytes
  (`dvsu_script_brief.MAX_BRIEF_BYTES`), even though every answer was accepted. Keep each single answer <= 450 chars, each candidate fact <= 220, ~2,300-2,700 chars total per machine
  (>= ~5,100 failed; <= ~4,500 passed). The MCP guide gives no per-machine status, so verify by `se db` on `videos.research_payload->'unit_research_cards'` (`script_brief_readiness.passed`)
  and by grepping the backend log for "Factual source research stopped at". Replacing an answer = `answer_llm_request` on the SAME request_id, then `research_machine` again (replays free).
- **Matcher label bug, FIXED and deployed (76f09ca9):** `factual_machine_research.candidate_mentions_machine` could never match labels ending in a parenthetical
  ("Barracuda class (V-1 group)", "Tang class (SS-563)") or with a parenthesised hull code ("USS Nautilus (SSN-571)"); those cards failed "no traceable exact-machine excerpts"
  even with perfect answers. Test: `tests/test_research_class_identity.py`. Backend suite now 5716 passed.
- `list_pending_llm_requests status=answered` returns the oldest 50 and is huge (saved to a file; parse with python3).

## Open items (nothing else is hidden)
- **UX (Research tab, not fixed):** with 20/20 VERIFIED the green button in the Research command bar still reads "Research incomplete".
- **UX found walking the Gather tab (not fixed):** a red "Run All stopped at Research - Something went wrong. Please try again." banner still shows
  on a video whose Gather is done (stale history, vague wording); the "Retry missing images" button still shows at 20/20 verified;
  the panel subtitle says "Untitled documentary"; hand-placed photos show a "Single source" badge (judged ones say "Compared N photos").
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
