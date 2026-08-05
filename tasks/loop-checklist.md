# Loop checklist - environments location fix (maestro run 2026-08-05)

## Definition of Complete
1. For a video whose script scenes carry structured `location` fields (MCP
   submit_script / Story Law S3), environment extraction returns EVERY distinct
   scene location - proven by a regression test modeled on the real PocoAPoco
   case (7 scene locations, "the kitchen at home" never named in dialogue,
   extractor must return all 7) with NO LLM call on that path.
2. Scripts without structured scene locations still extract via the existing
   Claude prose path, unchanged. When only SOME scenes carry locations, the
   prompt is seeded with the known list and the final result is the union -
   a structured location can never be dropped by the LLM.
3. POST create-one-environment endpoint on the environments router: creates a
   single named environment row (tenant-scoped, draft state) that the existing
   per-environment regenerate / patch / upload / approve routes can operate on.
   Recovery from a missed location = one row + one image, never a full redraw.
4. Matching MCP `add_environment` tool in storyengine/backend/routes/mcp.py,
   following the conventions of the existing environment MCP tools
   (design_environments / edit_environment / redo_environment / delete_environment).
5. New tests sit next to the existing environments tests; full relevant backend
   suite green vs recorded baseline; zero live/paid API calls in tests
   (Anthropic client mocked).
6. Committed on branch `claude/dreamy-mclaren-54a4fc` in this worktree.
   NOT deployed, NOT merged to main - Ryan's explicit go required.

## ASSUMPTIONS (user absent - made by orchestrator, correct me if wrong)
- No frontend UI work this round: the environments UI lists rows from the DB,
  so a row created via the new endpoint appears automatically. The recovery
  surface is API + MCP.
- OUT: making run_environments_design_step skip-if-done (bigger redesign,
  parked); any SFX/frontend work; deploy.
- Spend envelope: $0. No paid generations, no live LLM calls, tests mocked.
- Dedupe semantics for scene locations: case-insensitive + whitespace-normalized,
  preserve first-seen casing and scene order.

## Chunks
- [x] ENV-1 (S) [B][V] Extraction fix + create-one endpoint + MCP add_environment + tests
      - Part A: `_extract_locations_from_script` in
        storyengine/backend/routes/environments.py (~line 166) currently sends
        only video["script"] prose to Claude. Trace where submit_script stores
        per-scene `location` (Story Law S3) and: if ALL scenes have non-empty
        locations -> bypass the LLM entirely, return the deduped ordered list;
        if SOME -> seed the extraction prompt with the known locations AND
        union them into the result; if NONE -> existing behavior unchanged.
      - Part B: POST create-one-environment route (match existing router
        prefix/auth/tenant patterns; Pydantic models in models.py; row shape
        compatible with regenerate/patch/upload/approve flows).
      - Part C: MCP add_environment tool in routes/mcp.py wired to the same
        logic as Part B (no copy-paste divergence - shared helper).
      - Part D: tests next to existing environments tests incl. the 7-location
        kitchen regression; stash-proof; suite vs baseline.
- [x] ENV-2 (judge) Orchestrator review of ENV-1 evidence, then session-end
      docs (todo/lessons/decisions if warranted) and completion report.
- [x] ENV-3 (orchestrator) Deploy 319fbd99 + live verification: endpoint on prod openapi, add_environment in deployed mcp.py, kitchen draft row 2dc7f70a created on the real video, original 6 rows untouched.

## Parked for Ryan
- ~$0.05: generate the kitchen environment image (POST /environments/2dc7f70a-df34-4074-bce2-d0b6b2134b8b/regenerate on video d39892b2) and approve it. The draft row is in place; this is the only remaining step for that video.
- Whether run_environments_design_step should become skip-if-done like other stages (docs/failure-modes.md resumability table marks it full-redraw).
- Note: MCP connectors opened BEFORE this deploy still list 97 tools; reconnect/new session to see add_environment.
