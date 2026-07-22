# Film-Grammar Rebuild — loop checklist (2026-07-22)

Plan source: tasks/FILM-GRAMMAR-PLAN.md (design approved, maps verified — do NOT re-map).
NOTE: tasks/loop-checklist.md and loop-handoff.md belong to the PARALLEL static_docu
session. This build uses THIS file + FILM-GRAMMAR-HANDOFF.md. Never touch theirs.

## ASSUMPTIONS (made autonomously, per handoff authority)
- Commit to main directly (project convention; each chunk self-contained + tested).
- No deploy this session unless Ryan says go; dry-run proof runs without deploying.
- Dry-run planner call (pennies, workspace LLM key) is pre-approved by the plan file.
- Prop manifest: existing envs have no props yet -> absent manifest must fall back
  to today's behavior cleanly (no backfill this session).

## Definition of Complete (Ryan's acceptance bar, from the plan)
1. No two consecutive speaking shots with the same framing (setup+size).
2. No shot whose only motion is a push-in or focus-pull; calm dialogue lands
   STATIC; max 1 earned non-static move per scene (env-tunable).
3. Guaranteed listener reactions on key lines, inserts as punctuation (~1/6-8
   shots), re-establish wide ~every 10 shots; per-type durations
   (wide ~3.5s / medium ~2.5s / insert ~1.6s) written to duration_seconds.
4. Setup kit scales (~1 setup per 6-8 shots), size-variant compound ids
   (B-CU) share base-letter anchors, max 2 consecutive same-setup shots.
5. Prop manifest: props JSONB on video_environments, authored at approval,
   injected VERBATIM into planning + draw prompts (PICTURES path only).
6. Proof: unit tests green + scene-2 (video cd5d2883) dry-run shot list
   printed for Ryan (setup, size, type, move, duration) BEFORE any frames.

## Chunks

- [x] C1 [B][V] Motion axis (59cba120: stash-proof 6/8 fail-then-pass, 0 new failures both suites; budget downgrade verified by orchestrator read) — classifier diet + scene move budget.
  Classifier reads narrative beat only (moment summary + spoken line), NOT the
  composed description (animation_prompt_engine.py:243 classify_camera_purpose;
  boilerplate appends at coverage.py:955-994 run AFTER plan_camera_moves at
  1028, or pass narrow input — keep composition text coherent either way).
  Scene move budget: max 1 earned non-static move per scene, env-tunable, in
  plan_camera_moves (coverage.py:619) — only place seeing the whole ordered
  list. Fix _MOTION_SYSTEM Rule 1 (coverage_to_app.py:1956): untagged shots
  default Fixed lens/static. Check route_shot_model STATIC behavior
  (coverage.py ~670-690) before shipping budget. [V] unit tests: budget
  enforcement, classifier ignores boilerplate; stash-proof.

- [x] C2 [B][V] Shot-size grammar (79d70f7e + 010be7b5: orchestrator caught earliest-not-nearest swap defect; fixed to same/adjacent-beat-only, test-pinned; byte-identical failure set) — setup scaling + size variants + tension sizing.
  Prompt: ~1 setup per 6-8 shots derived from max_moments (coverage.py:151-161,
  189-193); compound setup ids (SETUP B-CU = same axis tighter) taught in
  prompt. CODE: base-letter derivation (split "-") in _setup_id/anchor lookup
  (coverage.py:562, anchor loop 1032, _setup_ref 636) so B-CU shares B's
  anchor; keep full id for repeat counting. Validator: cap 2 consecutive
  same-setup shots. Tension sizing: prompt-only turn-index proxy over T1..Tn
  (coverage.py:257-274); story_bible tension_level optional coarse hint only.
  Watch _SETUPS_RE single-line parser (no stray ']'). [V] unit tests:
  base-letter anchor sharing, consecutive cap; stash-proof.

- [x] C3 [B][V] Reaction/insert floors (4d692311: assets.duration_seconds column pre-existed unused — no migration; pro-rata weight verified by orchestrator read to not touch carries_own_line path; byte-identical failure sets both suites) + cut-length grammar.
  New inline tags (REACTION)/(INSERT); parser separate from _SETUP_TAG_RE.
  Validator floor parallel to enforce_shot_budget (coverage.py:874 — today
  only trims): guaranteed listener reactions on key lines, inserts ~1/6-8
  shots, re-establish wide ~every 10 shots. MUST add new tags to
  _escalate_panel_briefs protected rows (coverage_to_app.py:1234, today only
  LINE:/[AXIS|]). Per-type durations -> duration_seconds (wide 3.5 / medium
  2.5 / insert 1.6) so assembler cuts like an editor + Grok tier buys right.
  [V] unit tests: floors add shots, tags survive escalation; stash-proof.

- [x] C4 [D][B][U][V] Prop manifest (0334c7ee: migration 115 written NOT applied — deferred recipe = run_migrations_strict.py; soft gate per spec; fail-soft ordering orchestrator-read-verified; UI editing = API/MCP only, no frontend form) — kills cross-scene prop drift.
  Migration 115: props JSONB on video_environments (6-8 {name, position}).
  Author at approval gate (routes/environments.py:503): LLM-extract from
  approved reference + description ONCE; creator-editable via existing env
  edit surface. Inject VERBATIM: (a) bot.py:544 <visual_bible_locations> as
  literal enumerated list; (b) coverage.py:955 code-appended tail on every
  shot description (PICTURES path ONLY — never the sheet-preview path,
  coverage_to_app.py ~1290-1360, see warning comment at 1332), replacing
  reliance on the LLM's own [SET|] restatement. Contract triangle: build
  prompt + repair warning + gate (require props non-empty or explicit skip
  before status='approved'). Absent props -> today's behavior. [V] unit
  tests: injection verbatim, empty-props fallback; stash-proof.

- [x] C5 SWEEP (read-only) — verdict FIX-FIRST: 1 BLOCKER (sheet-vs-pictures shot-list divergence breaks board-anchor panel mapping), 2 SHOULD-FIX (hardcoded "two-shot" re-establish phrasing invites invented people; variety swap can relocate REACTION speaker text), 1 NOTE (stray-']' latent fragility). All other claimed protections confirmed real.

- [x] C7 [B][V] Sweep fixes (a0088271: plan_moments_deterministic shared by sheet+pictures paths; legacy-sheet guard verified against prod rows — "a grid of N panels" present on all cd5d2883 scenes; neutral re-establish phrasing; REACTION/INSERT excluded from swaps) — original spec:
  (a) BLOCKER — sheet/pictures parity: _plan_sheet_prompts callers
  (coverage_to_app.py ~1662-1692, ~1831-1840) must run the IDENTICAL
  deterministic passes (enforce_shot_budget -> enforce_reaction_insert_floors
  -> enforce_setup_variety, same order as run_coverage) before chunking, so
  sheet panels match what pictures will draw. PLUS guard: in run_coverage's
  board-anchor block (~1693-1714), if the recomputed shot count mismatches
  the stored board panel count (legacy sheets drawn pre-rebuild), skip
  board-anchoring (unanchored composition) instead of anchoring wrong.
  (b) Re-establish floor: derive phrasing from the actual opening shot's
  content, drop the hardcoded "two-shot" claim (coverage.py ~1029).
  (c) Exclude REACTION/INSERT-tagged shots from enforce_setup_variety swaps
  on BOTH sides (offender + candidate), like masters. — adversarial review of C1-C4 against the plan's
  risks: parser fragility (_AXIS_RE/_SETUPS_RE), sheet-vs-pictures path
  separation, tag protection, anchor wiring for compound ids, route_shot_model
  side effect, motion-writer override of static verdicts, cross-tenant blast
  radius. Findings -> new chunks.

- [x] C6 [V] DRY-RUN PROOF (complete after C8+C9 re-runs on the SAME saved directive, zero extra LLM calls: 48 shots, 0 framing repeats, 1/1 move, 8/8 reactions on facing-family CUs, 6/6 inserts, 3/3 re-establish, correct home-kitchen env) — original result: — ran clean (1 LLM call, ~$0.09 est): 36 shots, 0 framing repeats, 1/1 move, sizing escalates. GAPS: reactions 0/8 (pure-dialogue budget turns+1/0-angles starves the floor — C8a), inserts 2/5 (at cap), scene-2 env mislocked to cooking-class by _match_scene_env word-count fallback (C8b). Re-grade after C8.

- [x] C8 [B][V] Dry-run gap fixes (92986387: pure-dialogue max_frames = masters + derived headroom capped by COVERAGE_FLOOR_HEADROOM_CAP; env matcher needs >=2 distinct hits or 2x margin, else envs[0]; loud sys.path failure + CLI bootstrap; re-run proof: 48 shots, 8/8 reactions, 6/6 inserts, scene-2 env corrected — both cd5d2883 scenes proven on real data)

- [x] C9 [B][V] Reaction placement rule (29f971c8: reactions use facing-family CU compound parsed from [SETUPS|] "onto {name}"; INSERT/NEUTRAL + establish families excluded; LRU fallback; stash-proofed) — orchestrator catch on v2 list:
  reactions must use the CU compound of the family FACING the listener
  (parse "onto {name}" from the [SETUPS|] kit); never the INSERT/NEUTRAL
  family (shot 47 landed on E = props-only anchor). Fallback LRU among
  non-excluded families. Re-run deterministic proof, regen v2 list.
  (a) Fund the floors in _coverage_shape's pure-dialogue branch
  (coverage_to_app.py ~2207: turns+1, 0, 0, turns+1): add headroom for
  ~1 reaction per 4-5 turns + ~1 insert per 6-8 + re-establishes so
  enforce_reaction_insert_floors can actually place them. Cost note: more
  frames = proportionally more picture spend per dialogue scene.
  (b) _match_scene_env: stop single-stray-word wins ("class" beat the home
  kitchen for scene 2 of cd5d2883); require phrase/majority evidence or
  fall back to scene order/story-bible mapping; fix must be provably right
  on BOTH scene 1 and scene 2 of cd5d2883.
  (c) Optional hygiene: standalone CLI sys.path fix so plan_camera_moves
  doesn't silently degrade to all-static outside the server (loud, not
  silent, at minimum). — run the planner on Spanish Class scene 2
  (video cd5d2883) real script text; print shot list (setup, size, type,
  move, duration) for Ryan. Read-only against prod DB (se db); LLM call is
  pennies. NO frames drawn. Grade output against DoC items 1-4.

## Lessons (append as corrections happen)
- (none yet)
