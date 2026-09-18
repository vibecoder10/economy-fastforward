# HANDOFF - 2026-09-18 (update 2: StoryEngine MCP configured, drive live verification next)

## 2026-09-18 update 2 — use the StoryEngine MCP to run Phase 1's live verification

Ryan gave this repo a production StoryEngine MCP endpoint: `https://storyengine.dev/api/mcp`.
It's registered project-wide in `.mcp.json` at repo root (commit `86e3e1e`), auth wired via
`Authorization: Bearer ${STORYENGINE_MCP_TOKEN}` (commit `b74290c`) — the actual token lives ONLY
in this repo root's local, gitignored `.env` (`STORYENGINE_MCP_TOKEN=...`), never committed.

**If this is a fresh container** (new session, not a continuation of the one that set this up),
`.env` won't exist yet — the token never left that container. Ask Ryan for it again before
anything MCP-dependent below can work; don't guess or fabricate one.

### First actions, in order

1. Confirm the `storyengine` MCP server actually connected this session (new MCP servers only
   load at session start, which is why this is a fresh-session handoff item, not something the
   prior session could finish itself). Check your tool list / `ToolSearch` for `mcp__storyengine__*`
   tools. If absent, check `.env` has `STORYENGINE_MCP_TOKEN` set and the server shows as
   connected — don't assume tool names, discover the real ones first (list/describe tools if the
   server exposes that, or just look at what's in your toolset).
2. Read `CHECKLIST.md`'s Active section (top of file) and `tasks/live-verification-queue.md`'s
   "DVSU research pipeline v2 — Phase 1" section (near the top, added this session) — that's the
   exact recipe this MCP access is for. Read `docs/dvsu-research-pipeline-v2-2026-09-18/DESIGN.md`
   too if you need the prompt/shape details.
3. **Money gate, before triggering anything:** a real Roster (Call 1+2) + single-machine Research
   (Call 3) run is REAL paid generation (Anthropic + web search) against PRODUCTION data, on
   whatever video you target. Per this project's hard rule, get Ryan's explicit cost-quote-and-yes
   FIRST, even though he handed you the MCP token — the token being live doesn't substitute for
   the per-run confirmation. Rough shape of the ask: Call 1 (no search, cheap) + Call 2 (1 search
   call, roster) + Call 3 for ONE machine only (6 small search calls) — keep the first live test to
   one machine, not the full 20-25 roster, to bound cost. Quote it, wait for yes.
4. Once approved: use the MCP tools to run Roster then Research-for-one-machine on the target
   video (the live submarine video `44dbf2b2-a27a-47ea-a608-4c31c906be9a`, "US Submarine Class
   Evolution," already confirmed on the `factual_100_v1` contract — or a fresh test video if Ryan
   prefers not to touch that one). Verify the results match what Phase 1's code promises: real
   thesis/acts/roster/shared_context landed, `roster_selection.status == "completed"`, the one
   researched machine's card passes its readiness gates, and (per the known, documented, harmless
   wrinkle) its `evidence_segments[].source_excerpt` carries a `"Regarding <machine>: "` prefix —
   confirm that's the only oddity, not a sign of a deeper problem.
5. If the MCP surface doesn't give you enough to confirm results (e.g. no DB-read tool), fall back
   to whatever the MCP DOES expose plus the Supabase MCP (already connected in this account) for a
   direct read of the `videos.research_payload` row — don't block entirely on one tool gap.
6. Walk the Research/Roster tabs in an actual browser if you have any way to reach the frontend
   (this project's CLAUDE.md mandates driving the real UI, not just API/DB checks, before calling
   visual/UI-adjacent work done) — if this session still has no route to a running frontend, say so
   plainly rather than skipping it silently, and note it as still-deferred.
7. Report results back to Ryan plainly: what ran, what it cost, what you verified, and an explicit
   Phase 1 verdict (done / not done / partial + why) — don't leave this as another "implemented but
   unverified" handoff if the live run actually happened.

---

## 2026-09-18 update — Phase 1 built and pushed, not yet live-verified

A cloud session (no local Mac/VPS access, no SSH route) implemented Phase 1 directly on
`main-khm80l` per this file's "Next action" below, using this repo's orchestrator+Sonnet-worker
loop (`tasks/orchestrator-and-worker-playbook.md`). Shipped:
- `storyengine/backend/dvsu_roster_v2.py` (Call 1 thesis+acts, Call 2 roster+shared-context),
  wired into `run_roster_selection`, commit `a4fd6f5`.
- `storyengine/backend/dvsu_research_v2.py` (Call 3, six targeted searches per machine, + adapter
  to the legacy `unit_research_cards`/`ResearchTab.tsx` shape), wired into `_run_unit_research_hold`,
  commit `65545d8`.
- Both gated behind `factual_machine_research.is_factual_machine_contract(payload)` — every other
  `static_docu` video (any tenant) is provably untouched (tests assert the old code path is called
  and the new modules are never invoked, and vice versa).
- Drive export (fail-soft) of the DESIGN.md file layout is wired into both new modules.
- Full backend suite: zero regressions (133 failed/5474 passed/9 skipped/4 errors, FAILED/ERROR set
  byte-identical to the pre-change baseline). No frontend files touched.

**Not done: any live model call, any live search, any browser run.** This session's sandbox has no
VPS/SSH route and no way to reach the real Anthropic/search/Drive services the way production does.
Exact recipe for what's left: `tasks/live-verification-queue.md`, "DVSU research pipeline v2 —
Phase 1" section — a real roster+research run on the live submarine video, a browser walk of
Research/Roster tabs, and a no-spend-skip proof. Do that next, then get Ryan's acceptance, before
starting Phase 2. See `CHECKLIST.md`'s Active section for the same status, condensed.

One known cosmetic wrinkle, not a correctness issue: Call 3's adapter prefixes stored quotes with
`"Regarding <machine>: "` for legacy-matcher compatibility (see `dvsu_research_v2.py::_candidate_text`'s
docstring for why) — will show up verbatim in `evidence_segments[].source_excerpt`. Flag to Ryan
during the live verification pass in case it should be cleaned up before Phase 2 reads it.

---

# Original handoff - 2026-09-18 both designs approved, exact wiring traced, Phase 1 (roster+research) ready to implement - handing off to a fresh session for context reasons

## State
- Prod: unchanged, not touched. Last verified: 0229e9fb deployed, healthy.
- Branch `main`: this session committed only `.gitignore` (`140b7921`, adds `.worktrees/`) and,
  moments ago, this file + CHECKLIST.md + the two DESIGN.md docs. Everything else `git status`
  shows (hundreds of task/doc files) is OTHER sessions' work - not touched, not committed.
- **Isolated worktree ready:** `/Users/ryanayler/AgentVault/Projects/story-engine/.worktrees/
  dvsu-pipeline-v2`, branch `feature/dvsu-pipeline-v2`, forked off `140b7921`. Empty - no
  implementation code written yet. `cd`/`change_directory` there before writing any code; don't
  go up past its root in shell commands (resets your granted directory back to the main checkout -
  happened once this session).
- What shipped this session: recovered the script-writing design (existed as an unwritten Drive
  hand-prototype, wasn't "missing" like a stale resume claimed) into
  `docs/dvsu-script-pipeline-v2-2026-09-18/DESIGN.md`; got Ryan's decisions on both designs' open
  questions; ran two read-only trace agents mapping the EXACT current code (call sites, roster
  shape Gather Images needs, the frontend's real research-data contract, confirmed the live DVSU
  video is on the `factual_100_v1` branch); set up the worktree. **Zero implementation code
  written.** This is a clean planning/research handoff, not a mid-feature one.

## Next action (start here cold)
Read `CHECKLIST.md`'s Active section first (it has the condensed technical wiring facts), then
both DESIGN.md files. Then `change_directory` into the worktree above and start Phase 1:

1. Write a new module implementing Call 1 (thesis+acts, no search) + Call 2 (roster+shared-
   context, 1 search-enabled call) from `docs/dvsu-research-pipeline-v2-2026-09-18/DESIGN.md`.
2. Wire it into `run_roster_selection` (`storyengine/backend/pipeline_executor.py:11008-11200`) in
   place of the current `research.agent.run_research(...)` call - see CHECKLIST.md for the exact
   allow-listed keys the caller currently merges (needs extending for `shared_context`/`acts`) and
   the roster shape Gather Images needs (`unit_roster` list of `{name/title, designation?, code?,
   member_units?}` + the `roster_selection.version=1` marker so Gather Images' gate still passes).
3. Write a new module implementing Call 3 (per-machine research packet, 6 targeted searches) from
   the same DESIGN.md, plus a small adapter translating its 6-slot output into the legacy shape
   `ResearchTab.tsx` actually reads (`unit_research_cards[].evidence_segments[]` with `kind` in
   `original_problem/engineering_decision/tradeoff/reality`, plus a `research_summary` object) -
   full field-level detail is in CHECKLIST.md.
4. Wire it into `_run_unit_research_hold`'s `factual_100_v1` branch
   (`pipeline_executor.py:13030-13489+`), replacing `factual_source_search.py`/
   `research_claim_assessment.py`/`factual_machine_summary.py`'s research path there.
5. Verify locally: `scripts/se.sh devtoken`, run the frontend dev server (launch.json name
   `storyengine`, port 3001, auto-logs-in against prod API), walk Research/Roster tabs for the
   live submarine video (`44dbf2b2-a27a-47ea-a608-4c31c906be9a`) or a fresh test video, in the
   Browser pane per this session's mandatory "run it like a user" rule.
6. **Do not touch script-writing wiring yet.** Ryan explicitly said: "worry about gathering the
   information cheaply first, then worry about how we compile the information in the script-
   writing stage." Script-writing (`_run_static_script_hold`, `pipeline_executor.py:14770`) is
   Phase 2, after Phase 1 is verified.

## Open threads
- After Phase 1's new call sites are wired, re-grep for importers of the old DVSU-only modules
  (`factual_source_search.py`, `research_claim_assessment.py`, `factual_machine_summary.py`'s
  research path, `class_context_assessment.py`, `factual_class_context.py`,
  `contextual_source_identity.py`, `factual_machine_pipeline.py`, `factual_machine_research.py`)
  and delete any left with zero consumers - Ryan wants a clean rewrite, not old code left dangling
  unused. **Do NOT delete `research/agent.py`, `roster_selection.py`, or `roster_coverage.py`** -
  all three have other real consumers outside DVSU (see CHECKLIST.md for exactly which).
- Phase 2 (script-writing) needs its own trace of `_run_static_script_hold` - one was run this
  session but its result was never folded back before this handoff landed; redo it (or just read
  `pipeline_executor.py:14770` onward directly) when Phase 2 starts.
- Old pipeline's live state (20/20 roster, 20/20 images, 20/20 research, 1/20 scripts) still
  untouched - not yet decided whether it's preserved/migrated or discarded once new logic is live.

## Gotchas learned this session
- Drive is a better source of truth than HANDOFF.md for "does this design/code already exist"
  questions on this project - HANDOFF.md's own prose has been overwritten/lost across sessions
  more than once; the Drive project folder (`StoryEngine Research/Every US Submarine Class Ever
  Built (2026)/`) retained real prototype work each time. Check Drive before trusting a "not
  started" claim in this file.
- When Ryan says "other sessions cracked the code," don't assume literal hidden software exists -
  confirm what he means before spending a trace agent hunting for it. This session first
  misinterpreted it as hidden implementation; it meant the hand-prototyped system prompts.
- The existing frontend's research-data contract is far more specific than "whatever's in
  research_payload" - it's tied to legacy field/kind names from the old pipeline
  (`ResearchTab.tsx`'s 4 "Anton slots"). Any new research module needs a translation step, not a
  1:1 clean rewrite, to avoid a frontend change.

---
paste this to start the next session (or this is what the cloud handoff carries automatically):
Resume StoryEngine. Read HANDOFF.md's TOP section ("update 2 — use the StoryEngine MCP to run
Phase 1's live verification") first, then CHECKLIST.md's Active section, then
tasks/live-verification-queue.md's "DVSU research pipeline v2 — Phase 1" section. Phase 1's code
(Calls 1-3) is already implemented, tested, and pushed to main-khm80l (commits a4fd6f5, 65545d8) -
do NOT re-implement it. Your job is to drive the live verification using the storyengine MCP
(.mcp.json, token in local .env) per HANDOFF.md's numbered steps: confirm the MCP connected, get
Ryan's cost-quote-and-yes for a real paid run, run Roster + single-machine Research on the live
submarine video, verify the results, and report a plain done/not-done verdict. Do not touch
script-writing wiring - that's Phase 2, after Phase 1 is verified live and Ryan accepts it.
