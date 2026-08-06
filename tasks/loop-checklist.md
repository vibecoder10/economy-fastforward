# Loop checklist - ACTION stage-direction channel (maestro run 2026-08-06, loop 3 / S7)

Prior loops: ENV-1 (loop 1) and S6 script-origin-of-truth (loop 2) are COMPLETE,
merged to main, deployed 2026-08-05 (8c5ad01c). This loop builds ON S6.
Session: kind-mclean-96ca38, branch claude/kind-mclean-96ca38, THIS worktree:
/Users/ryanayler/economy-fastforward/storyengine/.claude/worktrees/kind-mclean-96ca38

## Definition of Complete
1. submit_script (storyengine/backend/routes/mcp.py) accepts optional
   scenes[].action; fallback: an "ACTION: ..." line at the start of scene text
   is parsed AND left in place, same pattern as LOCATION: today. Stored on the
   scripts row via a new migration (precedent: scripts.location, migration 144).
2. The LIVE board planner (coverage_to_app.py _plan_sheet_prompts /
   generate_storyboard_sheet_for_scene + storyboard/coverage.py
   generate_coverage_directive - NOT storyboard/bot.py, dead 410) injects each
   scene's stage directions into the planning prompt with an instruction to
   stage at least one action keyframe panel per direction. The S6 warn-only
   check (check_prop_action_presence) is EXTENDED to cover authored stage
   directions, surfaced in the completion message (same "; N warning(s)" slot).
3. Voice, dialogue lip-sync, and sync_video_script (routes/videos.py ~1644)
   NEVER include stage-direction text in anything spoken or voiced - proven by
   tests. (P11 carry-over: sync_video_script deliberately does not join
   location; ACTION must get the same treatment.)
4. submit_script MCP tool description documents the field; the script quality
   critic (S6 save-time lint) does not penalize ACTION lines.
5. Tests beside existing backend tests, green under backend/venv python (never
   system python3); zero new failures vs baseline (end of S6: "28 failed, 4607
   passed, 4 skipped" - all 28 pre-existing in test_custom_film_remotion.py).
6. NOTHING deployed, NOTHING merged to main (main auto-ships on any session's
   restart). Merge + prod migration parked for Ryan's explicit go.

## ASSUMPTIONS (Ryan absent - correct me if wrong)
- Evidence case: tenant PocoAPoco video d39892b2-0c85-4752-85d7-b61ca209342a -
  scene 1 celebration dance never boarded, scene 6 sprint boarded only by lucky
  inference. Demo = an authored ACTION reaching a panel + the warn check
  naming a direction no panel staged.
- Storage shape mirrors LOCATION's pattern exactly (pin after recon).
- Warn-only = never blocks board generation, never blocks a paid build (P3
  standing ruling: prose-vs-prose must WARN only - stage-direction presence in
  panels is prose-vs-prose, so WARN is settled law, not a choice).
- Spend envelope: $0. No paid generations, no live LLM calls in tests (mock
  Anthropic/Kie), no deploy, no prod DB writes.
- Work stays on branch claude/kind-mclean-96ca38 in THIS worktree.

## Spend log
(empty - $0 envelope)

## PINNED CONTRACTS carried from S6 (still law unless recon contradicts)
- P1: Live planner = backend/scripts/coverage_to_app.py (_plan_sheet_prompts,
  generate_storyboard_sheet_for_scene) + skills/video-pipeline/storyboard/
  coverage.py (generate_coverage_directive = the ONE planning LLM call;
  plan_moments_deterministic parses it). bot.py is DEAD (410) - never touch.
- P3: canonical-field-vs-composer-text may HARD-block; prose-vs-prose WARNs.
- P5/S6-A: coverage scene SQL now selects location; planner prompt has a
  DECLARED LOCATION block; [PROPS|] rule 30 -> moment["props"] via
  parse_coverage; check_prop_action_presence warn + completion-message suffix.
- P6/P13: backend tests: cd storyengine/backend && ./venv/bin/python -m pytest
  (venv = symlink to main checkout's venv, Python 3.11.14). Skills suite:
  full-suite collection broken pre-existing - run TARGETED skills test files
  with the backend venv python only. Baseline after S6: 28 failed / 4607
  passed / 4 skipped (28 all in tests/functional/test_custom_film_remotion.py).
- P11: sync_video_script deliberately does NOT emit LOCATION into spoken/
  exported prose; videos.script fans out to 5 consumers (originality hook
  fingerprint, dialogue-mode classifier, cast extraction, drive export,
  staleness hash) - any ACTION handling there must not disturb them.
- Lane law from S6 incident: isolation experiments NEVER stash/revert another
  lane's files in a shared tree - use a temp clone. Workers stage ONLY their
  own files; never git add storyengine/backend/venv.

## NEW PINS (this loop - law for every brief)
- N1: Column = scripts.action TEXT (nullable, no default, no backfill), new
  migration file backend/migrations/154_scene_action.sql (recon: latest file
  is 153_*; builder verifies 154 is the next free number; mirror 144's style;
  runner = _run_pending_migrations() on boot, nothing to install).
- N2: API field = scenes[].action, optional string, in _SUBMIT_SCRIPT_TOOL's
  raw inputSchema dict (mcp.py ~1812; NO Pydantic model exists - validation is
  manual in user_script._normalize_external_scenes). Fallback: ONE
  "ACTION: ..." header line in the scene's leading header block, mirroring
  _LOCATION_HEADER_RE (case-insensitive, first non-blank lines). LOCATION: and
  ACTION: may coexist at the top IN EITHER ORDER - each parser skips over the
  other header when scanning. Submit path NEVER rewrites text (header stays);
  update_scene_text edit path extracts AND strips, exactly as it does for
  location today. One ACTION line per scene; multiple beats live as prose in
  that one line.
- N3: Never-spoken law enforced at the SPEECH BOUNDARIES, not at storage:
  (a) voice/run.py narration_text() strips leading ACTION:/LOCATION: header
  lines (local regex - skills package cannot import backend; this ALSO fixes
  the latent LOCATION leak recon found: submit-path in-text LOCATION survives
  into scene_text and narration mode never strips it today);
  (b) backend/dialogue_intelligence.py segment_scene() strips headers at
  entry (imports story_laws) so dialogue_segments never contains them - which
  transitively protects dialogue_voice + clip_dialogue lip-sync.
  sync_video_script stays UNCHANGED (P11).
- N4: Planner injection mirrors S6-A's location param trick: new optional
  param (default None) on generate_coverage_directive/_coverage_user_prompt
  keeps dead bot.py callers byte-identical. Warn check for authored directions
  is WARN-only (P3), surfaced in the SAME completion-message warning-count
  slot S6 added.
- N5: Critic = pure LLM judge (script_quality.critique_script +
  originality._SCRIPT_JUDGE_SYSTEM); no deterministic token gate exists. Add a
  structural-header carve-out (ACTION:/LOCATION: header lines are stage
  directions, never spoken, never penalized as speech/pacing) to the judge
  prompt; S3 location law must keep passing when an ACTION line precedes the
  LOCATION line.
- N6: Migration count note: loop-handoff's "162/162" was applied-file count on
  prod; the numbering max in backend/migrations/ is 153. Trust the directory.

## Chunks
- [x] R1 RECON - backend map + tasks extract DONE (pins N1-N6); planner-path
      sweep still in flight, feeds CHUNK-B's brief.
- [x] SETUP-0 (H) [V] DONE. venv = symlink to main checkout's venv (Python
      3.11.14). Baseline VERBATIM: "28 failed, 4614 passed, 4 skipped,
      9 warnings in 83.43s" - all 28 FAILED in tests/functional/
      test_custom_film_remotion.py. (4614 vs S6's 4607: +7 from the S6-C
      follow-up/ENV-3 commits merged after S6's final count - all-clear.)
      Official baseline for VERIFY steps = 28 / 4614 / 4.
- [x] CHUNK-A (S) [D][B][V] MERGED - commit 9a4c4362 (S7-A:). Migration 154
      (additive, mirrors 144); story_laws _ACTION_HEADER_RE +
      _extract_leading_header shared scanner (order-independent coexistence,
      existing location behavior unchanged); _normalize_external_scenes
      explicit field -> ACTION: fallback -> None, text never rewritten; BOTH
      accept_external_script and set_user_script INSERTs carry action;
      _SUBMIT_SCRIPT_TOOL schema + description paragraph; update_scene_text
      double extraction with COALESCE (same persist-on-removed-header
      semantics location already has - consistent, noted); one carve-out
      sentence in originality._SCRIPT_JUDGE_SYSTEM. Evidence: 35 new tests,
      targeted 267 passed, stash-proof (ImportError at collection ->
      green after pop). FOLLOW-UP (parked, out of scope): platform-generation
      path (pipeline_executor modeled-script INSERT + supabase_adapter
      .create_script_record) doesn't carry action - the generator never emits
      ACTION lines today, so no leak; wire when platform generation learns
      to author actions.
- [x] CHUNK-B (S) [B][V] MERGED - commits ea147362 + 5a674cdf (S7-B:).
      DECLARED STAGE DIRECTIONS block in _coverage_user_prompt (after
      DECLARED LOCATION; rule 31 cross-ref, rule 30 untouched; action=None
      keeps prompt byte-identical for bot.py callers); _scene_text_hash(text,
      action=None) - old hash byte-identical when no action; BOTH save sites
      (SHEET ~3579, FRAME ~5641) and BOTH compare sites (~3393, ~5496) use the
      same composition + same per-iteration variable; warn-only
      check_stage_direction_presence (sibling of prop check, content-word
      heuristic, never raises) + separate counter + "; N stage-direction
      warning(s)" suffix on all three completed paths; FRAME scenes SQL now
      selects location+action and the narrative-branch fresh-plan passes both
      (closes S6's location gap there in passing). Evidence: 17+3 new backend
      tests incl. save==compare ROUND-TRIP (fresh plan -> reuse, no replan -
      the paid-silent-replan guard, added on bounce), skills-side 194 targeted
      green, stash-proof at collection, 117 targeted green post-commit.
      4 sibling fixtures updated (SQL substring -> WHERE-tail pattern,
      precedented, forced by the SQL change - honest flag accepted).
      PARKED follow-up: run_coverage's internal directive_text=None fallback
      (coverage.py ~4968) still plans with neither location nor action.
- [x] CHUNK-C (S) [B][V] MERGED - commit 03b6a43c (S7-C:).
      _strip_leading_stage_headers in voice/run.py narration_text (runs FIRST,
      plain + bolded forms, either order; transitively covers
      custom_film_production_runner._voice which imports narration_text);
      segment_scene strips via story_laws chain before the Claude call
      (protects dialogue_voice + clip_dialogue + render_perform +
      redo_dialogue_scene_voice transitively); full sweep table of every
      scene_text->speech surface with verdicts (no third boundary found;
      Custom Film AV format never uses the header convention).
      sync_video_script byte-identical. Evidence: 24 new tests incl.
      storage-law-vs-speech-law pair + FakeClaudeCapture prompt assertions;
      stash-proof at collection; targeted 345 passed.
      FINDINGS routed: (1) S7-A broke test_d7_2_staleness_hash.py (6-arg
      UPDATE vs 5-arg fake) -> bounced to A lane, fix in flight;
      (2) caption pipeline (render_static._gather_segments + run_split) feeds
      RAW scene_text into caption segments - header could become an on-screen
      caption row with no audio under it -> out of scope, spawn_task chip
      filed for Ryan (task: fix caption pipeline leaking scene header lines).
- [x] BOUNCE-ROUND (post-review): A follow-up b2237056 (3 arg-count-pinned
      fixtures fixed); orchestrator's own read of voice/run.py caught the
      "**ACTION**: x" colon-outside-bold escape -> C follow-up 94ec88de
      (voice regex) + A follow-up 4cd14a54 (story_laws bold tolerance, both
      forms, values captured clean, plain-form byte-identical).
- [x] VERIFY-ALL DONE - BY ORCHESTRATOR'S OWN RUN (the Haiku verifier
      reported main-checkout numbers despite the pinned absolute path - its
      totals fingerprinted the wrong tree; settled by own eyes per standing
      rule). Verbatim in worktree @ 5c8119bb: "29 failed, 4709 passed, 4
      skipped, 9 warnings in 80.14s"; FAILED grep = "28 tests/functional/
      test_custom_film_remotion.py" (the 29th was test_learn_voice
      ::test_live_anthropic_contract, a PRE-EXISTING live-network test that
      hit a transient 502 and passed on the immediate re-run). Arithmetic
      EXACT: 4742 collected = baseline 4646 + 96 new (A 46 + B 20 + C 30);
      zero new failures. Skills targeted: "194 passed in 0.70s" (matches
      builder exactly).
- [x] DOCS (S) DONE - commits 9001f3e0 (SYSTEM_STATE S7 section + todo
      handoff + 3 decisions + 2 lessons + live recipes) + ed5178c5 (folded in
      the two follow-up commits) + 5c8119bb (em-dash sweep; grep-proven clean
      in all S7-added sections, older text untouched).
- [x] JUDGE-FINAL DONE - completion report delivered with explicit verdict:
      COMPLETE (code-level), live-proof recipes deferred to Ryan (not
      deployed; backend cannot run against real DB locally - S6 precedent).
      Loop total: 10 commits (7 code + 3 docs) on claude/kind-mclean-96ca38.

## Loop lessons
- The Haiku full-suite verifier ran the MAIN checkout despite an absolute
  worktree path pinned in its brief, and its skills count (177) matched
  nothing real. Caught because total-collection arithmetic fingerprints the
  tree (4646 = main, 4742 = worktree). Standing rule held: agent-vs-agent
  contradictions get settled by the orchestrator's own eyes in the pinned
  tree. Trick to keep: always check TOTAL collected count, not just the
  failed count.
- tests/functional/test_learn_voice.py::test_live_anthropic_contract makes a
  LIVE network call inside the "unit" suite and can flake with 502s -
  pre-existing, not S7's; candidate for a skip-without-key guard someday.

## Parked for Ryan
- Merge to main + prod migration + deploy (explicit go required).
- Live re-run proof on PocoAPoco d39892b2 (deferred recipe).
