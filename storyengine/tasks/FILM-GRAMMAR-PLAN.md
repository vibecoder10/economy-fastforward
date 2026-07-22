# Film-Grammar Coverage Rebuild - Grand Plan (2026-07-22)

Ryan's goal in one line: dialogue scenes must be SHOT AND CUT LIKE A MOVIE -
not repetitive, not obvious. Acceptance bar (his words): no two consecutive
speaking shots with the same framing; no shot whose only motion is a push-in
or focus-pull.

Status: DESIGN APPROVED, NOT YET IMPLEMENTED. All mapping below is done and
verified (three agent fleets, ~700k tokens of reading) - a fresh session
should implement directly from this file without re-mapping.

## The design (six workstreams, build with Sonnet subagents + review pass)

1. CLASSIFIER DIET FIX (the metronome's root cause, re-run-proven): the
   camera-purpose classifier reads the COMPOSED shot description, which
   carries scene-constant set-dressing boilerplate containing "behind" ->
   every shot classifies REVEAL -> 4-move pool -> anti-repeat forces the
   rigid 4-cycle. Fix: classify from the narrative beat only (moment summary
   + spoken line), or reorder run_coverage so boilerplate appends AFTER
   plan_camera_moves. Calm dialogue then correctly lands STATIC.
2. SCENE MOVE BUDGET: max 1 earned non-static move per scene (env-tunable),
   enforced in plan_camera_moves (only place that sees the whole ordered shot
   list). Fix _MOTION_SYSTEM Rule 1 (coverage_to_app.py ~1956): untagged
   shots default to Fixed lens/static, not "ONE definite move" per shot.
   Watch the route_shot_model side effect (purpose downgrades change clip
   model routing - static routes to cheap default, acceptable and cheaper).
3. SETUP KIT SCALES + SIZE VARIANTS: ~1 setup per 6-8 shots (prompt rule),
   cap 2 consecutive same-setup shots (validator), compound setup ids
   (SETUP B-CU = same axis, tighter) with CODE-side base-letter derivation
   so B-CU shares B's anchor (split on "-" in _setup_id/anchor lookup;
   regex already accepts compound ids, anchor wiring does not).
4. REACTION + INSERT FLOORS with CUT-LENGTH GRAMMAR: guaranteed listener
   reaction shots (key lines on the HEARER's face), inserts as punctuation
   (~1 per 6-8 shots), re-establish wide every ~10 shots. New inline tags
   (REACTION)/(INSERT) + a validator floor parallel to enforce_shot_budget
   (which today only trims, never adds). MUST add new tags to
   _escalate_panel_briefs' protected-row list or moderation sweeps strip
   them. Per-type target durations (wide ~3.5s / medium ~2.5s / insert
   ~1.6s) written to duration_seconds so the assembler cuts like an editor
   and clip generation buys the right Grok tier (6-15s; silent shots today
   are dumb 6s slabs).
5. PROP MANIFEST (finishes the continuity system; refs alone proven not to
   hold - stove/fridge swapped within one setup, whole kitchen swapped by
   shot 125 WITH env ref + anchors active): props JSONB (6-8 {name,
   position} objects) on video_environments, authored at environment
   approval (LLM-extracted from approved reference, creator-editable),
   injected VERBATIM into every scene's planning prompt AND every draw
   prompt - replacing the per-scene LLM prose restatement of the location
   (the actual drift mechanism: fresh paraphrase every scene, words beat
   reference images - same lesson as the style war). Contract triangle:
   build prompt + repair warning + gate are NEW surfaces for this rule.
6. TENSION-DRIVEN SIZING: shot size tightens as the beat escalates. Only
   reliable signal = turn index within the scene's T1..Tn list (prompt-only
   proxy); story_bible.visual_arc.tension_level is optional/scene-level -
   never assume present.

## Verification ladder (cheap-first)
1. Unit tests on: base-letter anchor sharing, move budget, validator floors,
   tag protection through _escalate_panel_briefs.
2. DRY-RUN PROOF (pennies): run the planner on Spanish Class scene 2's real
   script text, print the shot list (setup, size, type, move, duration).
   Ryan reads it like a director before any frame is drawn.
3. Real proof: generate scene 2 pictures (~$1.60) through the new planner,
   judge frames at FULL resolution, then clips through the (already live)
   STS voice-lock path.

## Operating notes for the fresh session
- Two other workstreams live on this repo (static_docu session; check git
  log before assuming HEAD). Never deploy during generations (se health
  active_tasks + generation_claims + log activity - ghost counters exist).
- Voice side is DONE and live (memory: storyengine-sts-voice-lock-shipped).
- Paths below are verified live copies; three stale duplicates exist under
  .claude/worktrees/ - never edit those.

---

# VERBATIM AGENT MAPS (file:line evidence - implement from these)

### SHOT-VARIETY ANALYSIS (synthesis) :: synthesis

The video feels like "the same 3 shots in a cycle" because three layers stack: (1) the coverage planner dealt only 4 setups for 32 shots with a deterministic speaker-to-setup mapping, producing a literal B/C OTS ping-pong for 29 consecutive shots; (2) camera motion is a metronomic 4-recipe rotation (8/8/8/8, fixed period-4 order) of moves that barely move - 25% are fully static rack-focus and the pans rotate from a fixed position - so the (setup, move) pair repeats identically every 4 shots for the whole runtime; (3) the wide establish appears once at shot 100 and never returns, with only 2 inserts in 32 shots. On top of the monotony, the setup-anchor system is FAILING its one job: visual inspection shows the kitchen set drifting between repeats of the same setup and a wholesale kitchen swap by shot 125, so the pipeline currently pays the variety cost of anchoring without getting the continuity benefit. The small-setup-kit and identical-staging-per-letter rules are deliberate design (kill set drift); the unreachable camera purposes on dialogue, the mechanical move rotation, the missing re-establish rule, and the broken anchor enforcement are plain gaps. One analyst conflict matters: the code path predicts camera_move='static' on ~31 shots, but the DB shows 4 named recipes dealt 8/8/8/8 - so a different assignment path than plan_camera_moves populated camera_movement in rotation; that writer must be located before changing motion code. Within the couple-format constraints (locked cast, locked kitchen, 2 speakers), all fixes are camera-side: motivated micro-moves, size variants on the same axis (CU/tight-OTS of the same speaker), inserts of the food/hands already on the counter, and periodic re-establishes - no new locations needed.

### TRACE + MAPS :: dealer

FOUND. The prior analysis correctly identified the code (plan_camera_moves + camera_selector.py) but was wrong that its purpose gates are unreachable — they ARE reached, on every single shot, and that's exactly what produces the rigid 4-cycle. This is the same code, not a different dealer; the mystery is a bug in it, not a bypass of it.

THE DEALER (confirmed by exact signature match): plan_camera_moves() in /Users/ryanayler/economy-fastforward/skills/video-pipeline/storyboard/coverage.py, lines 619-696, specifically the write at lines 663-664:
  sel = select_camera_move(ctx)
  if sel.move:
      shot["camera_move"] = f"{sel.move.id}|{sel.purpose}"
Called from run_coverage() at coverage.py:1028. run_coverage()'s returned moments flow into /Users/ryanayler/economy-fastforward/storyengine/backend/scripts/coverage_to_app.py, whose store_scene() (lines 296-352) does the actual DB write at lines 337-352 (INSERT ... camera_movement ... VALUES ... fr.get("camera_move")). That INSERT is the only place in the repo that writes assets.camera_movement with a non-NULL, non-legacy value — the only other camera_movement writer is supabase_adapter.py's update_image_camera_movement, used by the old Airtable image_prompts/run.py pipeline, not by coverage/storyboard.

PROOF (signature match against prod, read-only): se.sh db "SELECT camera_movement FROM assets WHERE video_id='cd5d2883-427e-4bfb-854d-8849d025d444' AND scene=1" returns exactly 4 distinct values, 8 rows each: over_shoulder_push|REVEAL, pan_right|REVEAL, rack_focus|REVEAL, pan_left|REVEAL — literally the f"{move.id}|{purpose}" format string from coverage.py:664, byte-for-byte. camera_preset_id is NULL on all 32 because this write path never touches that column (owned by camera_presets.py, an unrelated feature). No other writer in the repo produces this "id|PURPOSE" shape.

WHY IT'S A ROTATION, NOT NOISE — verified, not guessed:
1. resolve_purpose() (camera_selector.py:151-172) calls classify_camera_purpose() (animation_prompt_engine.py:243-282) BEFORE any positional purpose gates run. I ran classify_camera_purpose() directly against the real prod image_prompt text for scene 1 (pulled via se.sh db) and it returns REVEAL — because the text contains the word "behind" (from "...cream stove behind Vanessa...", part of coverage.py's SET-DRESSING LOCK boilerplate, lines 955-967, which stamps the IDENTICAL set-dressing line onto every shot's description in the scene "so the image model doesn't invent props"). That boilerplate is appended before plan_camera_moves() runs (955-967 then 1028), so every shot in the scene inherits the same trigger word and resolves REVEAL. The prior analysis assumed dialogue text drives the classifier and dialogue never contains reveal words — true but irrelevant: the classifier reads the full composed shot description, which carries scene-constant boilerplate, not just the spoken line.
2. With purpose=REVEAL constant across the whole scene, score_move() (camera_selector.py:185-231) narrows the catalog (camera_moves.py) to REVEAL moves fitting the inferred subject_kind. The DB's exact 4-member set (over_shoulder_push, pan_right, rack_focus, pan_left, 8x each) matches precisely the REVEAL-purpose moves whose subject_fit includes two_subjects (camera_moves.py:199-281) — the 5th such move, whip_pan, scores far lower because its intensity=5 badly mismatches the "low" target used for every speaking-master shot (camera_selector.py:656, 213-214), so it never wins.
3. The rigid period-4 order comes from two hard rules in score_move(): the anti-repeat hard-exclude on identical legacy_key vs. the immediately-previous move (camera_selector.py:198-201 — pan_left/pan_right share legacy_key="lateral-pan" so can never sit adjacent), plus the recent-3 variety penalty (216-219). With only 4 real candidates and one pairwise exclusion, that mechanically forces the round-robin.
Net effect: because the SAME boilerplate (set-dressing + staging-lock text) is glued onto every shot's description to keep props/geography consistent, the "earn-the-move" classifier sees near-identical input on all 32 shots, makes the same (purpose, subject) decision 32 times, and only the anti-repeat/variety rules are left to pick a winner — a mechanical cycle instead of true per-shot film-grammar judgment. One caveat, labeled honestly: the exact subject_kind trigger phrase could not be re-derived character-for-character (the real classifier input exceeds the 1000-char image_prompt column, so the literal full string wasn't retrievable from prod) — that piece is inference by elimination, not a re-run proof. The purpose=REVEAL/"behind" link IS a re-run proof (ran the real function against real prod text).

WHERE TO FIX (film-grammar logic should replace the rotation):
1. animation_prompt_engine.py:243-282 classify_camera_purpose() — its REVEAL keyword list (line 255-259, includes "behind") substring-matches the FULL shot description, which now includes scene-constant boilerplate by design. Fix: classify off the narrative beat only (moment summary / spoken line), not the composed image description — or reorder coverage.py so the boilerplate tails (955-994) are appended AFTER plan_camera_moves() (1028) runs.
2. coverage.py:619-696 plan_camera_moves()/camera_selector.py:249-265 select_camera_move() — once purpose classification is fixed so most calm OTS dialogue shots correctly resolve STATIC, the remaining earned-REVEAL shots still route through a pure top-score pick with no shot/reverse-shot awareness. Real film-grammar rules (e.g. only the master of an OTS pair earns a move; bias toward the whole catalog, not one subject_fit slice) belong in resolve_purpose()/score_move() (camera_selector.py:151-172, 185-231).

**Key locations:**
- `skills/video-pipeline/storyboard/coverage.py:619` - plan_camera_moves() — the dealer; stamps shot[camera_move] = move_id|PURPOSE or static (write at 663-664/673), called from run_coverage() at line 1028, after the set-dressing/axis/staging boilerplate locks (955-994) have already been appended to every shot's description
- `storyengine/backend/scripts/coverage_to_app.py:337` - store_scene()'s INSERT — the only place in the repo that writes assets.camera_movement to fr.get(camera_move) verbatim (line 351); confirmed by exact id|PURPOSE signature match against prod for video cd5d2883 scene 1
- `skills/video-pipeline/image_prompts/animation_prompt_engine.py:243` - classify_camera_purpose() — substring-matches reveal_words (255-259, includes behind) against the full shot description; matches the scene's boilerplate set-dressing sentence (cream stove behind Vanessa), not narrative content, causing REVEAL on every shot. Verified by running the function directly against real prod image_prompt text.
- `skills/video-pipeline/image_prompts/engine/camera_selector.py:151` - resolve_purpose()/score_move() (185-231) — the earn-the-move gate and deterministic scorer; anti-repeat hard-exclude (198-201) and recency-variety penalty (216-219) force the observed rigid period-4 order once the candidate pool collapses to 4 members
- `skills/video-pipeline/image_prompts/engine/camera_moves.py:199` - CAMERA_MOVES catalog — confirms over_shoulder_push(361), rack_focus(199), pan_left(265), pan_right(274) are exactly the REVEAL-purpose moves whose subject_fit includes two_subjects; whip_pan(300) is the 5th but excluded by intensity=5 mismatch

**Edit plan:**
- Reorder coverage.py's run_coverage(): move the SET-DRESSING/AXIS/STAGING boilerplate-lock appends (955-994) to run AFTER plan_camera_moves() (1028), so purpose classification sees only authored per-shot narrative text, not scene-constant boilerplate.
- Alternatively/additionally, change classify_camera_purpose() (animation_prompt_engine.py:243) to take the moment's summary/spoken line as a separate, narrower input rather than the full composed shot description, so location/geography boilerplate can never trip a REVEAL/SCALE/ISOLATION match.
- Once purpose resolution is fixed and most calm OTS dialogue shots correctly fall back to STATIC, add real film-grammar logic to resolve_purpose()/score_move() (camera_selector.py:151-231) — e.g. only let the MASTER of a shot/reverse-shot pair earn a move, or score across the full catalog instead of one subject_fit slice — replacing the current pure top-score pick that mechanically cycles when the eligible pool is small.

**Risks:**
- The exact substring/hint phrase that resolves subject_kind to two_subjects for these shots was not directly re-derived — the classifier's real input text exceeds the 1000-char image_prompt column, so the literal string wasn't retrievable from prod. Inferred by elimination (only a two_subjects-narrowed pool explains the exact 4-move set across all 32 rows), not confirmed by running the function on the exact real string.
- Reordering the boilerplate-append vs. plan_camera_moves() in coverage.py also changes what text ships into the camera-move's own image_setup composition (appended to shot[description] at 665-668) relative to the SET/AXIS/STAGING tails — needs care to keep the image model's composition instructions coherent, not just fix classification.
- Any fix to classify_camera_purpose or plan_camera_moves changes camera_movement values for ALL future coverage generations across every tenant/video, not just this one — verify against a few other videos/scenes (dialogue-heavy and action-heavy) before shipping, per the run it like a user rule for anything a customer's finished video will show.

### TRACE + MAPS :: planner

Mapped the coverage PLANNER's prompt rules and budget code against Ryan's target film-grammar rebuild. Read skills/video-pipeline/storyboard/coverage.py (1162 lines, full) and the relevant sections of storyengine/backend/scripts/coverage_to_app.py (2657 lines — note the file has moved from the path given in the task to storyengine/backend/scripts/coverage_to_app.py; stale duplicate copies also exist under .claude/worktrees/ and should be ignored). Key finding: today's setup kit is a fixed "3-5 setups" prompt instruction with position-only letters keyed by exact string match for anchor-sharing; there is no reaction/insert budget anywhere (only a soft 'earn an angle' heuristic); pure-dialogue budget is exactly turns+1 masters/0 angles as cited; and no per-line tension signal exists — only an optional per-SCENE tension_level in story_bible.visual_arc. Full breakdown of prompt-vs-code-vs-contract changes and AXIS/SETUPS parsing risk is detailed below.

**Key locations:**
- `skills/video-pipeline/storyboard/coverage.py:63` - _coverage_system_prompt — all planner PROMPT rule text (rules 1-7 + output_format), already receives max_moments/angles_min/angles_max
- `skills/video-pipeline/storyboard/coverage.py:67` - motivated_rule — the only existing 'earn an angle' heuristic (reaction/reveal/emotional-turn), soft, not budgeted
- `skills/video-pipeline/storyboard/coverage.py:151` - rule 5e — SETUPS contract prose, fixed '3-5 setups' regardless of scene length
- `skills/video-pipeline/storyboard/coverage.py:189` - output_format [SETUPS|] line spec — where a scale-with-scene-length instruction would be edited
- `skills/video-pipeline/storyboard/coverage.py:312` - _AXIS_RE / _SETUPS_RE single-line bracket parsers — fragile to multi-line or nested-bracket edits
- `skills/video-pipeline/storyboard/coverage.py:559` - _SETUP_TAG_RE — already syntactically accepts hyphenated compound ids like (SETUP B-CU), but semantics aren't wired for size-variant anchor sharing
- `skills/video-pipeline/storyboard/coverage.py:562` - _setup_id() — treats the full matched tag string as an opaque anchor-dict key; compound ids would NOT share a base letter's background anchor without a code change
- `skills/video-pipeline/storyboard/coverage.py:619` - plan_camera_moves — camera MOVE engine hookup (separate axis from shot SIZE); no per-scene push-in cap counter observed
- `skills/video-pipeline/storyboard/coverage.py:874` - enforce_shot_budget — trims (angles/moments/frames) only; no additive/floor logic for reaction or insert quotas
- `skills/video-pipeline/storyboard/coverage.py:1032` - setup-anchor-owner assignment loop in run_coverage — where a base-letter derivation for compound setup ids would be added
- `storyengine/backend/scripts/coverage_to_app.py:2168` - _coverage_shape — THE per-scene shot-budget policy function, all four dialogue-mode branches
- `storyengine/backend/scripts/coverage_to_app.py:2207` - pure-dialogue branch: return turns+1, 0, 0, turns+1 — exact rule cited in the task
- `storyengine/backend/scripts/coverage_to_app.py:1234` - _escalate_panel_briefs — hard-codes LINE: and [AXIS|] rows as never-rewritten; any new per-shot tag needing the same protection must be added to this same line-matching check
- `skills/video-pipeline/storyboard/bot.py:506` - _format_story_bible_for_beat — visual_arc.tension_level (1-10, per SCENE not per line) and scene_blocks.act are the only structured beat/tension signal available, and it's optional (story_bible may not exist)
- `skills/video-pipeline/image_prompts/engine/camera_selector.py:7` - States 'static by default' discipline already exists; no confirmed hard cap at exactly one earned move per scene (best guess, not fully read)

**Edit plan:**
- (a) Setup-kit scaling with scene length: PROMPT-only change at coverage.py:151-161 and 189-193, deriving a target setup count from the already-passed max_moments/angles_max params. No parser reads setup COUNT today, so zero parsing risk, but also zero enforcement — the LLM can still ignore the target.
- (b) Size-variant setups on same axis: CONTRACT + CODE change. _SETUP_TAG_RE already accepts compound ids syntactically but _setup_id()/setup_anchors treat them as fully separate groups. Needs a base-letter derivation (split on '-') for anchor lookup while keeping the full id for other bookkeeping (e.g. consecutive-repeat counting), plus a new prompt instruction teaching the planner the compound-id syntax. Highest-risk item — silent wrong behavior (non-matching backgrounds) if shipped without the anchor-lookup fix.
- (c) Reaction-shot and insert budgeting in coverage_to_app: currently only a soft prompt heuristic (motivated_rule). enforce_shot_budget and _coverage_shape only ever trim, never add. A real floor/guarantee needs new CODE (a validator parallel to enforce_shot_budget) plus likely a new inline shot-purpose tag (CONTRACT format change, e.g. (REACTION)) and a parser addition kept separate from _SETUP_TAG_RE.
- (d) Beat/tension signal for size progression: no per-line signal exists. Cheapest correct lever is a PROMPT-only proxy using turn index/position within the already-provided T1..Tn list (coverage.py _coverage_user_prompt, lines 257-274) — zero code change. The only real structured tension data (story_bible.visual_arc.tension_level) is scene-granularity and optional; treat it as a coarse hint layered on top of the turn-index proxy, not a replacement.

**Risks:**
- Growing the [SETUPS|] line's content (scaling text, size-variant hints) must not introduce a stray ']' or the _SETUPS_RE single-line parser breaks; it also feeds _escalate_panel_briefs' prop-neutralization pass in coverage_to_app.py which already treats that line as prop-bearing text.
- Compound setup ids (e.g. SETUP B-CU) are already accepted by the regex but NOT wired for anchor-sharing — shipping (b) as a prompt-only change without the code-side base-letter fix will silently produce mismatched backgrounds for 'same setup, tighter' shots, defeating the intent.
- Any new per-shot tag (for reaction/insert budgeting) must be added to _escalate_panel_briefs' protected-row list (currently only LINE: and [AXIS|]) or the moderation-escalation sweep may reword/strip it.
- story_bible.visual_arc tension_level is optional and scene-level only — do not build size-progression logic that assumes it's always present; the turn-index proxy is the only reliably-available signal.
- coverage_to_app.py path differs from what the task specified (storyengine/backend/scripts/ not backend/scripts/ off repo root) — confirm this is the intended live copy before editing; stale duplicates exist under .claude/worktrees/ in three places and must not be edited by mistake.
- Did not fully read image_prompts/engine/camera_selector.py's internals (only grepped) — the claim that no per-scene push-in cap exists is best-guess, not fully verified line-by-line.

### TRACE + MAPS :: motion

Mapped both layers end to end with exact file:line citations. Key finding for MOTION: there are actually THREE authoring points, not two — (1) a deterministic per-shot "earn-the-move" selector at storyboard/compose time, (2) a separate LLM "motion writer" call that turns the selector's tag into the actual free-text Grok prompt, and (3) a clip-stage fallback in pipeline_executor.py that only fires when both upstream stages produced nothing. None of the three enforces a scene-level budget — the selector scores shots independently with only a soft 3-shot variety penalty, and the motion-writer's Rule 1 ("open with ONE definite move... vary the move shot to shot") pushes every UNTAGGED/legacy shot toward invented motion, so "static by default" is only real for shots the selector explicitly tagged static or locked. For ANCHORS: the setup-anchor mechanism holds up WITHIN a scene (image-reference visual similarity + a `[SET | ...]` prose line stamped onto every shot), but that prose line is regenerated FRESH by an LLM call on every single scene — it is never sourced from the environment's own locked description, so two scenes sharing the same physical location independently invent different prop lists in prose. That's the root of "whole kitchen swapped by shot 125": nothing ties a location's props to a canonical, reusable, structured list across scenes.

Known limitation: the exact "shot 125" incident isn't grep-able (no such string in the repo) — the drift mechanism above is a code-derived explanation of how it could happen, not a citation of that specific bug log. Flagged as inference, not verified fact.

**Key locations:**
- `skills/video-pipeline/image_prompts/animation_prompt_engine.py:21` - Header docstring RULE 2: 'Camera is STATIC by default... only add camera motion for REVEAL, SCALE, or ISOLATION' — the stated design intent, not an enforced budget
- `skills/video-pipeline/image_prompts/animation_prompt_engine.py:243` - classify_camera_purpose() — the keyword classifier (REVEAL/SCALE/ISOLATION/STATIC), lines 243-281, matches the cited ~242-281 range
- `skills/video-pipeline/image_prompts/engine/camera_moves.py:1` - Camera Movement Catalog — CameraMove dataclass, ~30 named moves incl. static_locked; each carries motion_prompt + image_setup (a contract between still-composition and motion text)
- `skills/video-pipeline/image_prompts/engine/camera_selector.py:151` - resolve_purpose() — the 'earn-the-move' gate: classify_camera_purpose() first, then two POSITIONAL upgrades (scene-open wide -> ESTABLISH; scene-final + high intensity -> PAYOFF). This is where a scene-level move BUDGET would need to be enforced — currently absent
- `skills/video-pipeline/image_prompts/engine/camera_selector.py:216` - score_move()'s variety penalty: only looks back 3 shots (_RECENT_WINDOW), not a per-scene cap — a scene can earn many moves independently
- `skills/video-pipeline/storyboard/coverage.py:619` - plan_camera_moves() — calls select_camera_move() once per shot across a scene's moments (in shot order), stamps shot['camera_move']='move_id|PURPOSE' or 'static'. is_scene_final only applies to the LAST moment's master (line ~656-657) — the natural home for a hard 'one move max, save it for the peak' counter
- `storyengine/backend/scripts/coverage_to_app.py:1956` - _MOTION_SYSTEM — the LLM system prompt that writes the actual free-text motion line per shot. Rule 1 tells the model to open with ONE definite move on every shot and 'vary the move shot to shot' — this actively fights static-by-default for any shot that isn't explicitly tagged
- `storyengine/backend/scripts/coverage_to_app.py:1975` - Rule 4 of _MOTION_SYSTEM: '(CAMERA LOCKED: ...) ... never substitute a different move. (CAMERA: static) holds a Fixed lens' — the only place static is actually honored, and only for tagged shots
- `storyengine/backend/scripts/coverage_to_app.py:2223` - _write_motion_prompts() — one Claude call per scene, writes video_prompt = motion + appended dialogue line; its own fallback default ('Slow push-in on the main subject, keeping it in frame.') is a SECOND static-default distinct from pipeline_executor's, line ~2270
- `storyengine/backend/scripts/coverage_to_app.py:1996` - _camera_tag() — translates the stamped 'move_id|PURPOSE'/'static' into the (CAMERA LOCKED: ...) / (CAMERA: static) tag fed to the motion writer
- `storyengine/backend/pipeline_executor.py:159` - _apply_camera_preset_override() — pure function, manual per-shot chip override wins outright over the auto/earned motion for silent shots only
- `storyengine/backend/pipeline_executor.py:12734` - vp = video_prompt read from the asset row — the clip stage trusts whatever the storyboard/motion-writer stage already wrote, no re-classification here
- `storyengine/backend/pipeline_executor.py:12819` - The static clip-stage fallback: 'Slow push-in on the main subject...' — only fires when video_prompt is empty (tapped card with nothing authored upstream), i.e. a THIRD, rarely-hit tier
- `storyengine/backend/pipeline_executor.py:12828` - _apply_camera_preset_override(prompt, camera_preset_id) call site
- `storyengine/backend/pipeline_executor.py:12832` - motion_guard(...) prepend — this is the PEOPLE-rule prefix (cutaway/no-new-people), unrelated to camera movement; defined in storyengine/backend/clip_dialogue.py:271
- `storyengine/backend/clip_dialogue.py:271` - motion_guard() definition — people-rule prefix, not a camera-motion rule
- `skills/video-pipeline/storyboard/coverage.py:108` - System-prompt rule 4 (SET-DRESSING LOCK, prose): 'decide once what surfaces and props exist... declare it on the [SET | ...] line, never add/remove/move a prop'. This is an LLM INSTRUCTION re-issued fresh on every scene call, not a structural guarantee
- `skills/video-pipeline/storyboard/coverage.py:305` - parse_set_dressing() — regex-extracts the [SET | ...] free-text line the LLM just invented for THIS scene
- `skills/video-pipeline/storyboard/coverage.py:955` - run_coverage(): set_line = parse_set_dressing(directive_text); if set_line, appends verbatim prose tail to every shot's description (the ANCHOR-TO-DRAW-PROMPT injection point) — good mechanism, bad input (regenerated prose, not a canonical list)
- `skills/video-pipeline/storyboard/coverage.py:539` - _SETUP_ANCHOR text block (~539-555 range cited) — 'Match its background, set dressing, prop placement... EXACTLY' — an image-reference-based anchor, scoped to one camera SETUP letter, reset per scene
- `skills/video-pipeline/storyboard/coverage.py:636` - generate_coverage_frames()'s _setup_ref()/_resolve_owned() — the actual anchor-frame plumbing: first-planned shot per setup owns an asyncio.Future, later same-setup shots await it and attach it as the LAST reference image
- `skills/video-pipeline/storyboard/bot.py:544` - _format_story_bible_for_beat()'s <visual_bible_locations> block — feeds the environment's free-text `description` as context and instructs the LLM to 'reuse each environment's EXACT architecture, props, materials and lighting every time it recurs' — an instruction to a fresh LLM call, not a structural guarantee. THIS is the actual root of cross-scene prop drift: no enumerated/positioned prop list exists anywhere, only prose the LLM must remember and restate correctly every single scene
- `storyengine/backend/scripts/coverage_to_app.py:456` - _scene_locations() — loads video_environments.description as the only per-location content fed downstream; no structured props field exists in the row
- `storyengine/backend/migrations/051_video_environments.sql:18` - video_environments table schema — name, description TEXT, reference_url, status ('draft'|'approved'), source, sort. No structured props column today. This is where a `props JSONB` column would be added
- `storyengine/backend/routes/environments.py:503` - The environments-approval gate: sets status='approved', stamps videos.environments_approved_at — storyboards are blocked until this fires. This is the natural authoring surface for a PROP MANIFEST (creator names 6-8 objects + positions at approval time, same UI/flow as approving the reference image)
- `storyengine/backend/scripts/coverage_to_app.py:1337` - set_block construction in the SHEET-PREVIEW path (_neutralize_risky_props applied) — a SEPARATE, parallel code path from the PICTURES path in coverage.py:955 that must NOT be confused with it (comment at line ~1332 explicitly warns of this)

**Edit plan:**
- MOTION — enforce the budget in ONE place, camera_selector.py/plan_camera_moves() (coverage.py:619), since that's the only call site that sees the whole scene's shot list in order before any prompt is written: add a scene-scoped counter (e.g. max 1 non-static PAYOFF-tier move, or configurable N) so resolve_purpose() downgrades every additional would-be-earned shot back to STATIC once the budget is spent — cheapest, most central enforcement point.
- MOTION — fix the motion-writer's Rule 1 conflict in _MOTION_SYSTEM (coverage_to_app.py:1956): today it tells the LLM to put 'ONE definite move' on every shot regardless of tag; add an explicit instruction that an UNTAGGED shot (no CAMERA LOCKED / no CAMERA: static marker — i.e. a legacy/freeform shot) defaults to Fixed lens / static, mirroring Rule 4's already-correct handling of tagged shots. Otherwise the selector's static verdict is being silently overridden downstream for any shot whose tag doesn't survive to this call.
- MOTION — contract triangle for 'static by default, one earned move per scene': (1) BUILD PROMPT = animation_prompt_engine.py's module docstring Rule 2 (already states the law; needs the camera_selector scene-budget logic to actually match it) + _MOTION_SYSTEM Rules 1 and 4 (coverage_to_app.py:1956-1979, needs the untagged-defaults-to-static fix). (2) REPAIR WARNING = no existing surface found; would need a new check in wherever storyboard repair rounds run (not located in this pass — likely near actions.py's repair verbs) that flags 'scene S has N earned moves, budget is 1' so a repair pass can re-plan. (3) GATE = plan_camera_moves()'s return value (coverage.py: 'planned' count, printed at coverage.py ~1030) — currently only logged, never checked against a budget; would need a hard assert/warning there.
- ANCHORS — author the PROP MANIFEST at environment approval (routes/environments.py ~503-537), the same gate that already blocks storyboards until envs are approved. Add a `props JSONB` column to video_environments (migration alongside 051_video_environments.sql), holding 6-8 {name, position} objects, either creator-entered or LLM-extracted from the approved reference image + description once (not regenerated per scene).
- ANCHORS — inject the manifest at TWO points to close the cross-scene drift gap: (a) into _format_story_bible_for_beat's <visual_bible_locations> block (bot.py:544) as a literal enumerated list instead of/alongside the prose description, so the coverage-planning LLM sees the SAME exact object names every scene; (b) bypass the LLM's restatement entirely by having run_coverage (coverage.py:955) stamp the manifest verbatim onto every shot description the same way it already does for axis_line/setups_line — i.e. code-appended, never re-generated — rather than relying solely on the LLM's own [SET | ...] line, which is the actual drift source today.
- ANCHORS — contract triangle for the prop manifest: (1) BUILD PROMPT = the <visual_bible_locations> instruction in bot.py:544-551 (needs literal-list wording, 'the ONLY 6-8 props in this environment are: ...') + the code-appended tail in coverage.py:955 (new, mirrors the existing set_line/axis_line/setups_line pattern at lines 955-990). (2) REPAIR WARNING = would need a new check, likely in coverage_to_app.py near _neutralize_risky_props's sibling functions, that flags when a shot's description omits/contradicts a manifest object. (3) GATE = the environments-approval gate itself (routes/environments.py:503) should require the props field to be non-empty (or explicitly skipped) before status flips to 'approved', mirroring how reference_url is already required.

**Risks:**
- The 'shot 125 / whole kitchen swapped' failure is not literally grep-able anywhere in the repo — my explanation of the drift mechanism (fresh per-scene LLM restatement of a free-text location description, no structured manifest) is a code-derived hypothesis consistent with everything I traced, not a verified citation of that specific incident. Label: best guess, not checked against the actual failure log.
- I did not locate an existing 'repair warning' or 'gate' code surface specifically for camera moves or prop consistency — both triangle legs 2 and 3 for the two proposed changes are NEW surfaces to be built, not existing ones to extend. Say so plainly to whoever picks this up so they don't go hunting for a nonexistent hook.
- There are two parallel, easily-confused code paths carrying set/axis/setups text: the SHEET-PREVIEW path (coverage_to_app.py ~1290-1360, feeds the gate-sheet image only) and the PICTURES path (coverage.py:955-990, feeds the real per-panel draw prompts). A comment at coverage_to_app.py:1332 explicitly warns these must stay separate — any prop-manifest injection must go into the PICTURES path only, or it'll leak into the disposable sheet preview and do nothing for the real frames.
- plan_camera_moves()'s model-routing side effect (coverage.py ~670-690, route_shot_model) is wired to sel.purpose and runs regardless of whether a move fires — a scene-level budget change that downgrades purposes back to STATIC will also change which clip model gets routed to those shots. Worth checking route_shot_model's STATIC-purpose behavior before implementing the budget, not assumed here.
- I have not verified whether _MOTION_SYSTEM's per-scene single Claude call (coverage_to_app.py:2223) has its own token/shot-count ceiling that would silently drop shots on long scenes — flagged as unexamined, not a claim either way.
