# Loop checklist - script is origin of truth for storyboards (maestro run 2026-08-05, loop 2)

Prior loop (ENV-1 environments location fix) is complete and committed on this
branch - see git log fbdff463..319fbd99. This loop builds ON it.

## Definition of Complete
1. **Location fidelity:** For a video whose script scenes carry structured
   `location` fields, every assembled storyboard prompt names that scene's
   location as its FIXED SET, and a post-assembly hard lint (peer of the L29
   DECLARE-ONE-STYLE gate) fails the scene if the location name is absent -
   proven by a regression test modeled on PocoAPoco video
   d39892b2-0c85-4752-85d7-b61ca209342a scene 1 ("the kitchen at home" - the
   shipped board never said "kitchen").
2. **No blind spend:** The storyboards QUOTE response lists per-scene
   readiness - any scene whose location has no approved environment produces
   a named warning BEFORE money is spent, instead of silently drawing the
   scene in a neighboring set.
3. **No poisoned saves:** edit_environment PATCH (REST + MCP twin, same
   helper) rejects a description containing style keywords from the SAME
   list L29 enforces, with an error naming the offending word. A description
   that would later hard-fail boards can no longer be saved. (Scene 2 of the
   evidence video got NO board because of exactly this.)
4. **Props reach panels:** A planning pass extracts named props / physical
   gags from each scene's dialogue (e.g. "Dos boletos" tickets, water bottle,
   trash-can salute) and the shot plan places them; a post-plan check flags
   any extracted prop/action that appears in zero panel descriptions.
5. **Honest quotes:** The storyboards quote is computed from the same scene/
   location counts the job will actually run with, and the completion message
   appends quoted-vs-actual (evidence video: $0.35 quoted, $1.10+ actual).
6. **Format-locked references:** Environment reference generation injects the
   channel's locked visual_format (channel DNA), so a format-locked channel
   can never receive a photorealistic reference.
7. All new code tested beside existing backend tests (backend venv python,
   never system python3); full relevant suites green vs baseline
   (backend baseline: 4557 passed / 28 pre-existing failures).
8. Committed on this branch in this worktree. NOT deployed, NOT merged -
   Ryan's explicit go required.

## ASSUMPTIONS (user said "use /maestro to build it" - no Q&A round; correct me if wrong)
- DONE = the 6 fixes above, in the kickoff's value order; demo = the lint
  catching the kitchen case + a quote showing per-scene warnings.
- OUT: deploying; re-touching ENV-1's extractor (_extract_locations_from_script)
  beyond consuming its output; wiring SFX; any unrelated storyboard redesign.
- Spend envelope: $0. No paid generations, no live LLM calls in tests
  (Anthropic/Kie clients mocked). Live re-run of the PocoAPoco video is a
  deferred recipe for Ryan, not part of this run.
- STAKES: nothing irreversible - all work stays on this branch.
- GATES parked for Ryan: deploy go; whether the location lint should be
  hard-fail (assumed YES per kickoff "hard-fails") vs warn-only.

## PINNED CONTRACTS (from recon - law for every brief)
- P1: The LIVE board planner is storyengine/backend/scripts/coverage_to_app.py
  (_plan_sheet_prompts, called by generate_storyboard_sheet_for_scene) +
  skills/video-pipeline/storyboard/coverage.py (generate_coverage_directive =
  the ONE planning LLM call; plan_moments_deterministic parses it). The
  kickoff's named file skills/video-pipeline/storyboard/bot.py is DEAD in the
  SaaS backend (routes/pipeline.py run_storyboards opens with an unconditional
  410 raise; CLAUDE.md: "Deleted on purpose, don't resurrect"). Items 1/2/4
  target the coverage path. Do NOT resurrect bot.py paths; bot.py stays
  untouched except where coverage_to_app already imports from it.
- P2: Hard-gate precedent: SheetPromptContractViolation in coverage_to_app.py;
  L29 = _assert_single_style_declaration over _STYLE_KEYWORDS, post-assembly
  pre-return inside _plan_sheet_prompts, caught per-scene into blocked_scenes
  (never crashes the batch, never reaches the paid draw). The new location
  lint is a PEER: same exception class, same catch site, gate text scoped the
  same way (header/character/set/material/env-locks/constraints - NOT free
  panel prose, to avoid L11-style false positives).
- P3: Standing ruling (check_material_map_consistency docstring): canonical-
  field-vs-composer-text may HARD-block; prose-vs-prose must WARN only.
  Location lint (scripts.location vs composer-written set_block) = hard gate.
  Prop/gag panel-presence check (dialogue prose vs panel prose) = WARN-only,
  surfaced in the completion message, never blocks a paid build.
- P4: _STYLE_KEYWORDS is the single source of truth for style words. The
  edit_environment save-time lint imports THE SAME constant - if import
  weight of coverage_to_app demands, extract the tuple to a tiny leaf module
  and re-import it in coverage_to_app (no second copy, no divergence).
- P5: coverage_to_app's scene SQL currently selects only scene, scene_text -
  never location. scripts.location exists (migration 144) and is correct
  (ENV-1). Item 1 = plumb it: SQL select, planner-prompt hint (known-location
  so [MOMENT|LOCATION:] headers use it), _match_scene_env prefers the stated
  location over prose heuristics, set_block names it, then the P2 lint.
- P6: Tests: backend suite via cd storyengine/backend && ./venv/bin/python -m
  pytest (backend venv, never system python3); skills suite via
  cd skills/video-pipeline && python -m pytest tests/ -x. Gate tests imitate
  test_d6_1_canonical_inputs.py / test_d6_1b_gate_scope_and_honest_status.py
  (pytest.raises(SheetPromptContractViolation, match=...)).

## PINNED CONTRACTS part 2 (from recon B)
- P7: Quote divergence root cause: actions.estimate_cost "storyboards" branch
  = scenes x PICTURE_COST ($0.05); real job generate_storyboard_sheet_for_scene
  draws len(sheet_chunk_sizes(shot_count, panels_per_sheet)) boards per scene
  (capped 5), each one paid draw. Honest quote = same chunking math: exact
  when a scene's coverage directive already exists (compute shot_count via
  plan_moments_deterministic), honest RANGE otherwise. One estimator feeds all
  4 surfaces (chat _confirm_card, mcp _call_verb, pipeline list_video_actions,
  agent_brain _tool_state) - fix estimate_cost, all surfaces inherit.
- P8: Completion message slot = generate_storyboard_sheet_for_scene's final
  return dict ("Storyboard ready for N scene(s)..."). Actual spend = local
  accumulation of round(ok * sheet_price, 2) already computed per scene in
  that loop - no ledger read-back needed.
- P9: MCP edit_environment calls routes/environments.py update_environment()
  DIRECTLY (one implementation). Style lint goes inside update_environment;
  HTTPException(400, detail=...) with detail < 160 chars surfaces verbatim as
  a frontend toast (errors.ts humanizeError passes short details through).
  environments.py ALREADY imports from scripts.coverage_to_app
  (_enforce_stylized_media), so `from scripts.coverage_to_app import
  _STYLE_KEYWORDS` adds zero new import weight - no leaf-module extraction
  needed.
- P10: "Scene readiness" definition (decision): a scene's location is READY
  when a video_environments row matches it (normalized via the existing
  _dedupe_locations casefold rule) AND has reference_url IS NOT NULL - the
  functional gate _approved_envs actually uses (NOT status='approved').
  Scenes with scripts.location NULL are flagged separately ("no declared
  location") - never silently passed.
- P11: sync_video_script stays UNCHANGED (decision). location is already
  SELECTed there but deliberately not joined - the LOCATION: header must
  never reach spoken/exported prose, and videos.script fans out to 5
  consumers (originality hook fingerprint, dialogue-mode classifier, cast
  extraction, drive export, staleness hash). The board planner reads
  scripts.location directly from the scripts table instead (P5).
- P12: Channel DNA: channel_profiles.channel_identity JSONB, key
  visual_format + format_locked; helpers get_channel_format /
  style_preset_for_format / STYLE_DESCRIPTIONS[preset]["look"] in
  backend/channel_format.py. run_environments_design_step currently reads
  ONLY video.image_style_override; fix = fallthrough chain
  image_style_override -> video.visual_style/style_preset ->
  locked channel format look -> existing default.
- P13: Backend venv does NOT exist in this worktree - SETUP-0 creates or
  symlinks it. Expected baseline ballpark: ~4556 passed / 4 skipped / 28
  pre-existing failures all in tests/functional/test_custom_film_remotion.py
  (worktree font-asset scaffold gap). Record the REAL verbatim counts.

## Chunks
- [x] RECON-A (S) storyboard/pipeline sweep - DONE (P1-P6)
- [x] RECON-B (S) backend sweep - DONE (P7-P13)
- [x] SETUP-0 (H) [V] DONE. venv = symlink to main checkout's venv (Python
      3.11.14). Baseline VERBATIM: "28 failed, 4557 passed, 4 skipped,
      9 warnings in 87.55s" - all 28 in tests/functional/
      test_custom_film_remotion.py (expected scaffold gap). Skills suite:
      full-suite collection broken pre-existing (test_ctr_12h_tracking.py
      needs performance_tracker module, under BOTH interpreters) - builders
      run TARGETED skills test files with the backend venv python, never the
      whole skills suite, and do NOT try to fix that collection error.
- [x] CHUNK-A (S) [B][V] MERGED pending independent spot-verify - commits
      6ddfa8e2 + 4ed5aea7 (S6-A:). Scene SQL selects location;
      _match_scene_env(location=) preference (exact-normalized then
      containment) before prose heuristics; generate_coverage_directive/
      _coverage_user_prompt location param (DECLARED LOCATION block, default
      None keeps bot.py callers byte-identical); _plan_sheet_prompts prepends
      location onto set_line when planner's [SET|] misses it (single-location
      scenes; multi-loc rely on [LOCSET|] headers); NEW HARD GATE L30
      _assert_scene_location_declared (article-tolerant, NULL-exempt, same
      _style_gate_text scope + blocked_scenes catch); [PROPS|] rule 30 in
      planner prompt -> moment["props"] via parse_coverage; WARN-only
      check_prop_action_presence + "; N prop/action warning(s)" in completion
      message. BOARD-LAWS.md L30 + STORY-LAWS.md documented. Evidence:
      stash-proof (ImportError at collection), new backend file 18 passed,
      skills targeted 67 passed, full suite "28 failed, 4597 passed, 4
      skipped" = baseline failures only (4557+18+22C=4597 corroborates).
      Resolves C's cross-lane flag: the 35 were FakeDB fixtures hardcoding
      the old column list, fixed in 4ed5aea7.
      INCIDENT (lesson to log): C's isolation experiment stashed A's
      uncommitted edits in the shared worktree; A recovered them but a stale
      years-old stash got swept into the pop and conflicted with
      tasks/deferred-verification.md (resolved by discarding the stale
      stash's version). Rule for future briefs: isolation experiments never
      stash/revert another lane's files in a shared tree - use a temp clone.
- [x] VERIFY-A (H) CLEAN. Verbatim suite tail "28 failed, 4597 passed, 4
      skipped, 9 warnings in 78.04s"; grep: all 28 FAILED lines in
      test_custom_film_remotion.py; new files 40 passed (backend, both S6
      files) + 12 passed (skills); stash list normal (A's temp stash gone,
      historical stashes untouched); git status = orchestrator loop docs +
      untracked venv symlink only (workers: NEVER git add
      storyengine/backend/venv).
      DECISION (quote semantics, for B): estimate_cost's numeric cost =
      UPPER bound of the board-count range (never undersell - underselling
      IS the bug); cost_text explains the range; exact single figure when
      every scene already has a coverage directive.
- [x] CHUNK-C (S) [B][V] MERGED - commit 0c663567 (S6-C:). Lint
      _reject_style_keywords imports _STYLE_KEYWORDS live (no copy), wired in
      update_environment (description + material_map) AND create_environment;
      MCP twins covered by construction (mcp.py calls the route functions).
      DNA fallthrough _resolve_environment_style_dna wired in BOTH
      run_environments_design_step and regenerate_environment (builder found
      a second independent style_dna line there and fixed it). Evidence:
      stash-proof (18/22 fail stashed, 4 legitimately test unchanged clean
      paths; 22/22 after pop), new file "22 passed", sibling files "73
      passed", isolation run reproducing baseline with A's files reverted.
      CROSS-LANE FLAG: at C's final HEAD the full suite showed 35 new
      failures attributed via isolation to CHUNK-A's in-progress commits -
      MUST be zero in A's final report (verify independently).
      Follow-ups captured: (1) env NAME with style keyword reaches L29 gate
      text via the multi-location LOCSET branch - name linting parked;
      (2) _resolve_style's visual_style handling collapses unresolved preset
      ids to generic boilerplate (pre-existing, spawn_task chip filed).
- [x] CHUNK-B (S) [B][V] MERGED - commit 8a667f18 (S6-B:).
      estimate_storyboard_workload in coverage_to_app (same math as the
      draw: plan_moments_deterministic -> _expected_coverage_frame_count ->
      sheet_chunk_sizes, cap 5; exact when directive fresh, [1,5] range
      otherwise; per-scene location_covered via _location_env_match factored
      from _match_scene_env with behavior unchanged - A's tests still pass
      unmodified). estimate_cost storyboards branch uses it (lazy import,
      side-effect-ordering rationale verified). storyboard_quote_warnings
      wired: mcp _call_verb quote dict, chat _confirm_card text, pipeline
      list_video_actions additive field (UI ignores it today - noted).
      Quoted-vs-actual appended on all three completion return paths.
      Evidence: stash-proof, 10 new tests incl. quote-math==job-math against
      the REAL _plan_sheet_prompts, full suite "28 failed, 4607 passed, 4
      skipped" = baseline + 10, zero new failures, S6-A (18) and S6-C (22)
      files still green. ORCHESTRATOR MONEY CHECK (own eyes): _get_or_plan_
      directive is a pure DB read + hash check, NEVER plans/calls an LLM -
      the run-start quote adds one cheap query, no second paid planning
      call. 3 collateral test fixes are call-count/dispatch updates,
      legitimate.
- [ ] JUDGE-FINAL Orchestrator review of all evidence, decisions/todo/lessons
      updates, deferred-verification recipes for live checks, completion
      report. Live UI walk is DEFERRED (backend cannot run against real DB
      locally - memory: rotated DATABASE_URL; changes not deployed), mirroring
      loop 1's pattern: exact recipes for Ryan instead.

## Lane discipline
- A and C touch DISJOINT files (A: storyboard/coverage.py + scripts/
  coverage_to_app.py + tests; C: routes/environments.py + tests). Both commit
  to this branch in THIS worktree: stage ONLY your own files, retry once on
  index.lock collision.
- B waits for A (same-file edge on coverage_to_app.py + real data dependency
  on A's location matcher).

## Spend log
- (empty - $0 envelope)

## Parked for Ryan
- Deploy + live verification (carried from loop 1 - see
  storyengine/tasks/deferred-verification.md).
- Hard-fail vs warn-only for the new location lint (assumed hard-fail).
