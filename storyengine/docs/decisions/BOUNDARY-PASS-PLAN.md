# The film-level boundary pass — plan (D6-5)

Plan document only. No production code touched. This answers the five
questions HANDOFF.md backlog item 4 asks, using L23-L26 in `BOARD-LAWS.md`
as the spec and `tasks/evidence/d3-64-fixes/TRANSITION-PLAN-example.txt` as
the acceptance target: this plan must be capable of producing that exact
artifact, boundary for boundary.

## Why this is a real build and not a chunk

L23 says a cut cannot be authored inside a scene, because the planner that
boards a scene only ever sees that scene's text. A relationship between two
scenes has to be decided by something that can see both of them at once.
Nothing today sees more than one scene. That is the whole reason this needs
its own pass, running once per video, before any scene boards.

## The consumer already exists on main — verified, not assumed

The task brief said to check this rather than assume it. First pass on
this checked only `storyengine/backend` and missed it — the renderer
actually lives at repo-root `skills/video-pipeline/storyboard/coverage.py`,
a different root than `storyengine/backend/scripts/coverage_to_app.py`.
Corrected and re-verified directly against `main`: `feat/board-laws` is
fully merged (0 commits ahead of main, worktree clean, nothing stranded).

**It exists on `main`, finished and tested.** Three pieces, all landed
together, all optional/additive (every new parameter defaults to `None`,
so every caller before this feature is byte-identical):

1. `skills/video-pipeline/storyboard/coverage.py:510-546`,
   `format_boundary_blocks(incoming, outgoing)` — the actual text renderer.
   It takes two dicts and returns exactly L23's block shape:

   ```
   INCOMING — the previous scene ended on: <description>. Your FIRST panel
   relates to it by <relationship>, specifically: <instruction>

   OUTGOING — your FINAL panel must be: <description>, because the next
   scene opens by <relationship>.
   ```

   `incoming = {"description": ..., "relationship": ..., "instruction": ...}`,
   `outgoing = {"description": ..., "relationship": ...}`. Both are plain
   f-string interpolation of the dict values — no LLM call in this
   function, no paraphrase, so it inserts stored text VERBATIM. That
   satisfies requirement 4 already, for free.

2. `skills/video-pipeline/storyboard/coverage.py:580-598`,
   `generate_coverage_directive(..., incoming=None, outgoing=None, ...)` —
   the per-scene planner call, which threads `incoming`/`outgoing` into
   `_coverage_user_prompt` (line 549), which calls `format_boundary_blocks`
   and appends its output to the prompt Claude sees when planning that
   scene's shot list.

3. `scripts/coverage_to_app.py:1626-1822`, `_plan_sheet_prompts(...,
   incoming=None, outgoing=None)` — the deterministic sheet-prompt composer.
   Places the INCOMING block on the first sheet only and the OUTGOING block
   on the last sheet only (a scene can span multiple sheets; only the
   sheet holding the scene's true first/last panel is boundary-constrained).
   Covered by `test_incoming_outgoing_placed_on_first_and_last_sheet_only`
   in `storyengine/backend/tests/functional/
   test_board_laws_sheet_and_quality_rules.py:164`. `format_boundary_blocks`
   itself is covered by `test_format_boundary_blocks_shape` and
   `test_format_boundary_blocks_empty_when_neither_given` in
   `skills/video-pipeline/tests/test_board_laws.py:149-165`.

`format_boundary_blocks`'s own docstring (lines 511-520) says outright:
this is "NOT the boundary pass itself... out of scope for this chunk," and
points at `tasks/deferred-verification.md` (repo-root copy; a duplicate
also lives at `storyengine/tasks/deferred-verification.md`) for the
recommended follow-up. That file (lines 950-992) contains an unbuilt
sketch of this exact pass — module location, storage shape, and a cost
estimate. This plan verifies that sketch against the real schema,
disagrees with it in one place (see Q3), and turns it into a chunk list a
worker can execute.

**Chunk 3 verdict, corrected: unblocked.** Because the renderer and its
kwargs are already on `main`, chunk 3 (wiring `ensure_boundaries()` into
`generate_storyboard_sheet_for_scene` and threading `scene_boundary_in`/
`scene_boundary_out` into the existing `generate_coverage_directive`/
`_plan_sheet_prompts` calls) has no merge dependency at all. It depends
only on chunk 2 (the pass that produces the data) — see the corrected
chunk list in section 7.

**Consequence for this plan:** don't invent the output contract. The
renderer's dict shape is fixed and tested. The boundary pass's only job is
to produce dicts in that shape and get them to the two call sites above.

## 1. Where it lives above the scene

**New module:** `skills/video-pipeline/storyboard/transitions.py`, next to
`coverage.py`, not inside it. `coverage.py`'s entire per-scene surface
(`generate_coverage_directive`, `_coverage_user_prompt`,
`_plan_sheet_prompts`) is scene-scoped by construction — one `beat_text`
argument, one scene's rows. The boundary pass reads every scene of a video
at once, which is the one thing `coverage.py`'s functions cannot do and
should not be made to do. A sibling module keeps that boundary honest
instead of smuggling a video-wide loop into a scene-scoped file.

**Where it plugs into the status machine.** `backend/status_map.py` is the
real machine (verified: `STAGE_ORDER`, `STAGE_PREREQS`,
`STATUS_STAGE`/`STAGE_FIRST_STATUS` maps every Supabase status to a
user-facing stage and its prerequisites). The images stage's Supabase
entry point is `"ready_for_image_prompts"`, dispatched by
`PipelineExecutor.run_coverage_stage` (`backend/pipeline_executor.py:14654`,
wired at `pipeline_executor.py:14419` as
`"ready_for_storyboards": self.run_coverage_stage`). The actual per-scene
storyboard planning happens one level down, in
`generate_storyboard_sheet_for_scene` (`scripts/coverage_to_app.py:1838`),
which already does the one thing that makes this easy:

```python
scenes = await fetch_all(
    "SELECT scene, scene_text FROM scripts WHERE video_id=$1 AND tenant_id=$2 "
    "AND scene IS NOT NULL AND scene_text IS NOT NULL ORDER BY scene", vid, tenant)
targets = [s for s in scenes if scene is None or s["scene"] == scene]
```

It already fetches every scene's text, in order, before looping over the
`targets` it actually boards this call. The boundary pass hooks in right
there: **before** the `targets` loop, call
`transitions.ensure_boundaries(video_id, tenant_id, scenes)`. That function
either returns already-stored boundaries (see Q3) or computes and stores
the missing/stale ones, then each scene in the loop reads its own
`incoming`/`outgoing` and passes them into the
`generate_coverage_directive(...)` and `_plan_sheet_prompts(...)` calls that
already accept those kwargs.

This is not a new pipeline STAGE in `status_map.py` (no new
`STAGE_ORDER` entry, no new Supabase status) — it is a precondition check
inside the existing `ready_for_storyboards`/images stage, the same way
character-sheet presence and environment approval are hard gates inside
that stage today rather than their own stage. Reason to pick this over a
new named stage: a new stage would need its own status value, its own
`STAGE_PREREQS` wiring, and a UI checkpoint, for something that has no
independent user-facing checkpoint — nobody reviews "boundaries" the way
they review a script or a storyboard. It runs, gates silently on failure
(see Q6), and the storyboard gate proceeds.

It must run after the script is final (S3/S5 stable — a scene's location
and boundaries can't be planned mid-rewrite) and strictly before the first
`generate_coverage_directive` call for ANY scene in the video, because the
first scene's own INCOMING block depends on the pass having already run.

## 2. What it reads

One call, once per video (or once per stale boundary — see Q3), reading:

- Every row from `scripts` for the video: `scene`, `scene_text`, in
  `ORDER BY scene` — the exact query `generate_storyboard_sheet_for_scene`
  already runs. No new query needed for the base read.
- Each scene's `[SET|]`/`[LOCSET|]` location name, parsed the same way
  `coverage.py`'s `parse_location_sets`/`parse_set_dressing` already do,
  if available at the time the pass runs. Not required — the pass can run
  on scene TEXT alone, since L24's relationships (MATCH, CONTINUATION,
  SIGHTLINE BRIDGE, CONTRAST, ELLIPSIS, NESTED HANDOFF) are readable from
  what happens in the prose, not from a coverage plan that doesn't exist
  yet for scene N+1 when scene N is being planned. Location and axis data
  helps disambiguate CONTINUATION vs ELLIPSIS but is not a hard input.
- Cast identity (name only, from `video_characters`) so a boundary
  description can say "she" unambiguously when handed to a downstream
  planner call that has no other context for pronouns.

Nothing else. No image data, no prior boards — this pass runs on pure
script text, which is the whole reason its cheapest proof (Q8) costs $0.

## 3. What it writes

Per boundary: relationship type (one of L24's six), the OUT shot ending
the earlier scene, the IN shot opening the later one, what carries across.

**Storage: two JSONB columns on `scripts`, not a new table.**

```
scene_boundary_out JSONB   -- this scene's OUTGOING half (what the NEXT scene needs)
scene_boundary_in  JSONB   -- this scene's INCOMING half (what THIS scene needs)
```

Shape, matching `format_boundary_blocks`'s dict contract exactly so no
translation layer is needed between storage and renderer:

```
scene_boundary_out = {
  "relationship": "MATCH" | "NESTED HANDOFF" | "CONTINUATION" |
                   "SIGHTLINE BRIDGE" | "CONTRAST" | "ELLIPSIS",
  "description": "<exact text of this scene's final panel>",
  "carries": "<one-line note: what carries across — subject, shape,
               direction, light, or a frame-within-the-frame>",
  "scene_text_hash": "<sha256 of the two scenes' scene_text, concatenated>"
}
scene_boundary_in = {
  "relationship": "<same six values>",
  "description": "<exact text of the PREVIOUS scene's final panel>",
  "instruction": "<what THIS scene's first panel must do about it>",
  "scene_text_hash": "<same pairwise hash>"
}
```

`description`/`relationship`/`instruction` map 1:1 onto
`format_boundary_blocks`'s `incoming` dict; `description`/`relationship`
onto its `outgoing` dict (`carries` is planning metadata for humans and
the next stage's judgment call — it is not rendered into the board prompt,
because L23's block text doesn't ask for it, and stuffing more prose into
a prompt block that already has an exact required shape is how paraphrase
creeps back in).

**Why a table was the deferred-verification.md sketch's first idea, and
why this plan overrides it in favor of two JSONB columns.** That sketch
(lines 971-980) proposed the same two-column idea but hedged with "or a
small satellite table." Verified against the real schema
(`information_schema.columns` on `scripts`, 38 columns, `se db` read-only):
`coverage_directive`/`coverage_directive_hash` already live as
plain columns on `scripts`, one JSONB/text pair per scene, with exactly
the staleness pattern (`_scene_text_hash`) this needs. A boundary "belongs"
to one scene as its OUTGOING half and the adjacent scene as its INCOMING
half, same as the existing pattern where a scene's own plan lives on its
own row. A satellite table would need its own migration, its own foreign
keys, and its own join everywhere a scene is read — for data that is
always read exactly one row at a time, by scene id. No tradeoff here worth
naming twice: columns win, use them.

**Migration: 145.** Verified free by listing
`storyengine/backend/migrations/` (the real migrations directory — the
task brief's `storyengine/migrations/` only holds one unrelated 2024 sync
file; `storyengine/backend/migrations/` is where every recent numbered
migration actually lives, confirmed by `run_migrations_strict.py` and the
schema-drift test). Highest committed migration on `main` is `141_static_
reference_misses.sql`. `142`, `143`, and `144` are not on disk yet but are
reserved: 142 = D6-1 canonical inputs (in flight), 143 = D6-2 repair
stamps, 144 = D6-3 S3 scene location (in flight). `145_scene_boundary_
columns.sql` is the first number this plan can safely claim:

```sql
ALTER TABLE scripts
  ADD COLUMN IF NOT EXISTS scene_boundary_out JSONB,
  ADD COLUMN IF NOT EXISTS scene_boundary_in  JSONB;
```

Nullable, additive, no backfill, no default — every existing row reads as
"no boundary planned yet," which is simply true.

## 4. How each scene prompt receives its blocks

Already built, verified above — this section states the contract so the
new module targets it correctly rather than re-deriving it.

`generate_storyboard_sheet_for_scene` reads its own scene's
`scene_boundary_in`/`scene_boundary_out` from the two new columns (one
extra `SELECT` alongside the existing `scene, scene_text` query, or two
extra columns added to that same query — trivial), and passes them
straight through:

```python
directive = await generate_coverage_directive(
    beat_text, video_title, profile, story_bible, beat_scenes, image_prompts,
    incoming=scene_boundary_in, outgoing=scene_boundary_out, ...)
...
prompts = _plan_sheet_prompts(
    moments, style_dir, ...,
    incoming=scene_boundary_in, outgoing=scene_boundary_out)
```

Both call sites insert the stored dict verbatim through
`format_boundary_blocks` — confirmed by reading that function (section
above): it does plain f-string substitution of `description`/
`relationship`/`instruction`, no model call, no rewriting. The only place
an LLM ever touches this text is when the boundary PASS first writes it
(Q5) — once written, it is frozen data from there on, exactly like
`coverage_directive` itself is frozen data once a scene's plan is saved.

## 5. Model judgment vs. calculated

**Model judgment, once per boundary:** which of L24's six relationships
fits, and the prose for the OUT/IN descriptions. This is reading two
scenes' prose and picking the connective tissue between them — real
comprehension, same class of task `coverage.py`'s planner already does per
scene. One call.

**Calculated, deterministic, checked over the STORED plan, not prose:**

- **L25 (direction/eyeline carries across the cut).** Once a boundary's
  `description` fields exist as structured text (not free prose — see the
  refinement below), a gate can regex-extract a frame-side token
  (`frame-right`/`frame-left`/`frame-RIGHT` etc., case-insensitive, the
  same vocabulary L0/L10/L25 already use everywhere in `BOARD-LAWS.md`)
  from the OUT description and the IN description, and assert: if OUT
  states an exit direction, IN's entry direction is the OPPOSITE screen
  side (exits frame-right -> enters frame-left) UNLESS the relationship is
  CONTINUATION-with-reversal (L25's own "if a reversal is intended, the
  turn itself must be a panel" carve-out) or the pair is a NESTED
  HANDOFF/MATCH where no travel is claimed. This is mechanical string
  matching on a fixed, small vocabulary — genuinely a gate, not a
  simulated one.
- **L26 (no accidental near-repeat).** Also mechanical, but only after the
  OUT/IN text is structured: compare OUT's shot descriptor (a small fixed
  vocabulary again — shot size WS/MS/CU, and location name) against IN's.
  Flag when they're EQUAL on both size and location but the relationship
  is NOT one of the two that explicitly license an exact repeat (MATCH,
  NESTED HANDOFF) — the near-repeat failure mode is specifically "similar
  but not identical," which text similarity alone can't detect reliably
  without a much fussier NLP layer. Being honest instead of pretending:
  this gate reliably catches "same shot size and same location, not
  declared as a deliberate match" (a real, useful subset of L26), and
  cannot catch a near-miss that differs only in framing detail expressed
  as different words for the same picture (e.g. "her face fills the
  frame" vs. "close on her face"). That residual is judged, not gated —
  the same honest limit `BOARD-LAWS.md`'s method section already accepts
  for image-level defects.

**The concrete mechanism that makes both gates possible:** the planner
call must return OUT/IN descriptions as a SMALL structured record, not
free prose, e.g. `{"shot_size": "WS", "exit_direction": "frame-right",
"location": "Corridor", "prose": "<the sentence for humans/the renderer>"}`
— the `prose` field is what `format_boundary_blocks` renders; the other
fields exist ONLY so L25/L26 can check them without parsing English. This
mirrors `BOARD-PLANNER-ARCHITECTURE.md`'s whole thesis exactly: ask the
model for facts, not sentences, then compute or render from the facts.
Skipping this and gating on the prose sentence directly would work today
but would rot the first time a boundary's wording changes — the same
failure `BOARD-PLANNER-ARCHITECTURE.md` already diagnosed for the
scene-level prompt.

## 6. The three legs, per law

Per `BOARD-LAWS.md`'s "How a law becomes behaviour" pattern
(`STORY-LAWS.md` states it explicitly; `BOARD-LAWS.md` implies the same
contract): PROMPT, GATE, REPAIR, same commit.

**L23 — transitions planned above the scene.**
- PROMPT: the boundary-pass system prompt states L23 directly — read both
  named scenes, decide the relationship, produce the OUT/IN facts. This is
  the pass's entire reason to exist, so it's the whole prompt, not a rule
  buried in a longer list.
- GATE: a video cannot enter its first `generate_coverage_directive` call
  with `scene_boundary_in IS NULL AND scene > 1` (first scene legitimately
  has no incoming boundary) or `scene_boundary_out IS NULL AND scene <
  max(scene)`. `ensure_boundaries()` itself is that gate — it runs and
  fills the gap before the scene loop proceeds, so the gate and the fix
  are the same call.
- REPAIR: `scene_boundary_out`/`scene_boundary_in` regenerate automatically
  when `scene_text_hash` no longer matches the current pair of scenes
  (script edited after the boundary was planned) — the same
  hash-and-compare staleness pattern `coverage_directive_hash` already
  uses, extended to a PAIR of scene hashes as `tasks/deferred-
  verification.md` already correctly anticipated.

**L24 — the six legal relationships.**
- PROMPT: the six relationships and their per-type requirements (L24's own
  bullet list) go into the boundary-pass system prompt verbatim — this is
  a closed enum, so the prompt is also effectively a schema.
- GATE: `relationship` is validated against the six literal strings by a
  Pydantic/enum field (or a plain `assert value in {...}` if the codebase
  isn't using Pydantic for this call) — reject and retry once on an
  invalid value, same as any other closed-enum LLM output in this
  codebase. This is a real, complete gate; nothing honest to admit is
  missing here.
- REPAIR: an invalid relationship value never reaches storage — the gate
  runs before the write, so there is nothing to repair after the fact by
  design.

**L25 — direction and eyeline carry across the cut.**
- PROMPT: L25's text, plus the reversal carve-out, goes into the
  boundary-pass prompt so the model states `exit_direction`/`entry_
  direction` consistently in the first place.
- GATE: the mechanical frame-side check described in section 5 above —
  real, deterministic, runs on the structured fields, not prose.
- REPAIR: on gate failure, one automatic re-ask to the same model with the
  specific violation named ("your IN direction must be frame-left because
  OUT exits frame-right"), same one-retry pattern L24 uses. A second
  failure freezes that boundary and surfaces it as a review item rather
  than looping — the project's contract-triangle discipline treats a gate
  that can't be satisfied automatically as a signal for a human, never as
  license to keep re-rolling.

**L26 — no accidental near-repeat.**
- PROMPT: L26's exact text plus the MATCH/NESTED-HANDOFF exemption.
- GATE: the shot-size + location equality check in section 5 — HONEST
  ADMISSION: this gate catches the exact-attribute-collision subset of
  near-repeat and nothing more. A near-repeat that differs only in worded
  framing detail is not deterministically catchable without a much larger
  investment (semantic similarity scoring, which introduces its own false
  positives), so it is not gated — it is left to the same panel-by-panel
  human judgment `BOARD-LAWS.md`'s method section already relies on for
  pixel-level defects the prompt layer can't reach.
- REPAIR: same one-retry-then-freeze pattern as L25, sharing the retry
  wrapper (one function, two failure reasons) rather than two copies of
  the same loop.

## 7. Chunking

Four chunks, dependency-ordered. Each is sized for one worker, one pass.

- **Chunk 1 — [D] Storage.** Migration 145 (section 3), plus reading the
  two new columns into the existing `scripts` query in
  `generate_storyboard_sheet_for_scene`. No new logic — pure plumbing so
  chunk 2 has somewhere to write. Depends on nothing.
- **Chunk 2 — [B] The pass itself.** New `skills/video-pipeline/storyboard/
  transitions.py`: `ensure_boundaries(video_id, tenant_id, scenes)` —
  walks every adjacent scene pair, skips pairs whose stored
  `scene_text_hash` still matches (staleness check), calls one Claude
  request per stale boundary (or one batched request across the whole
  video — see the cost note in Q8; start with per-boundary calls, it's
  simpler to gate and retry, and revisit batching only if per-video cost
  is a real problem), applies the L24 enum gate and the L25/L26
  mechanical gates from section 5-6, retries once on gate failure, writes
  `scene_boundary_out`/`scene_boundary_in` on the two adjacent `scripts`
  rows. Also owns the scene-count-change handling in section 9. Depends
  on chunk 1.
- **Chunk 3 — [B] Wire into the storyboard gate. UNBLOCKED.** One call to
  `ensure_boundaries()` inserted into `generate_storyboard_sheet_for_scene`
  before its `targets` loop (section 1), plus threading
  `scene_boundary_in`/`scene_boundary_out` into the existing
  `generate_coverage_directive(...)`/`_plan_sheet_prompts(...)` calls —
  both already accept `incoming`/`outgoing` on `main` today (corrected
  finding above; the earlier draft of this plan wrongly thought this
  chunk was blocked on an unmerged worktree). Depends only on chunk 2.
- **Chunk 4 — [V] Proof.** The $0 proof run (section 8) plus, once chunk 3
  is live, one real $0.05-0.20 board run on a fresh multi-scene video,
  judged against `BOARD-LAWS.md` L23-L26 the same way every other law in
  this project was proven — read the produced INCOMING/OUTGOING text
  before judging any drawn pixels, per `tasks/deferred-verification.md`'s
  own recommendation. Depends on chunk 3.

## 8. The cheapest proof

A boundary plan over 8 scenes is pure text — the project's own method
(hand-write, generate free, judge, fix words, then spend) applies exactly,
and the first proof costs nothing because there is no image in it yet.

**The 8-scene structure does not exist as data yet, and the proof must not
create it the wrong way.** Video `686b4651` has six scenes on disk today.
It becomes eight only once scene 1 is split into three (the escape / the
run and its dead end / the return — Ryan's approved split, still pending),
which is exactly why `TRANSITION-PLAN-example.txt` has 7 boundaries for an
8-scene film. That video must never be re-split in place: re-deriving its
scenes runs `DELETE FROM scripts WHERE video_id=...` and would orphan
$1.85 of already-drawn assets. The eight-scene script will be authored
onto a NEW video later, not onto `686b4651`. So this proof cannot read
`686b4651`'s real rows — it hand-writes fresh 8-scene prose (the same
bubble-pod story `TRANSITION-PLAN-example.txt` already describes) and
simulates against that, never against the live 6-scene video.

**The $0 proof run:** hand-write scene prose for the 8-scene bubble-pod
structure `TRANSITION-PLAN-example.txt` already describes, then
hand-simulate the boundary pass: for each of the 7 adjacent pairs,
hand-write the JSON record section 3 specifies (not just prose) and run it
through the REAL `format_boundary_blocks` function (on `main` today,
verified above) to confirm the rendered text. Compare the rendered output,
boundary by boundary, against `TRANSITION-PLAN-example.txt`'s
hand-approved prose.

**What makes it pass:** all 7 boundaries render text that says the same
thing `TRANSITION-PLAN-example.txt` says (not byte-identical wording — the
same relationship, the same OUT/IN facts, the same carries-across note),
AND the L25/L26 mechanical checks from section 5 correctly pass all 7 (no
false positive) when run against the hand-written structured records. If
either check fires on a boundary the worked example treats as legal — for
example flagging boundary 3->4's deliberate exact MATCH as a false
near-repeat — that is a gate bug to fix before any model call is ever
made, exactly the kind of defect the project's method is designed to catch
before spending a cent.

## 9. Scene count changes — insertion, renumbering, re-split

A script is not frozen. Scene 1 splitting into three is the concrete case
in front of this project right now, and it will not be the last time a
scene count changes after boundaries have already been planned. The pass
has to survive that, not just a fixed script.

**What happens to stored records on a renumber.** A boundary record lives
on two adjacent rows (`scene_boundary_out` on the earlier scene,
`scene_boundary_in` on the later one) and is keyed by the PAIR's
`scene_text_hash`, not by scene number. Renumbering scene 2 to scene 4
(because two new scenes were inserted ahead of it) does not by itself
invalidate that scene's own boundary content — the text of scene 2 didn't
change. What it DOES invalidate is ADJACENCY: scene 2's old neighbours are
no longer its neighbours. So the rule is: **a boundary record is valid
only for the specific pair of scene numbers it was computed for.** Any
insertion, deletion, or renumbering between two previously-adjacent scenes
invalidates both of that pair's halves (the earlier scene's
`scene_boundary_out` and the later scene's `scene_boundary_in`), even
though neither scene's own TEXT changed — because the boundary's OUT/IN
description no longer names the actual neighbour.

**How the pass detects this without a separate "did numbering change"
flag.** `ensure_boundaries()` (chunk 2) always recomputes its adjacency
list fresh from the current `ORDER BY scene` query before checking
anything stored — it never trusts a cached notion of "scene N's
neighbour is scene N+1." For every adjacent pair in that fresh list, it
checks whether a stored record exists on BOTH sides AND whether that
record's own `scene_text_hash` matches the hash of the CURRENT pair (both
scenes' current text, hashed together — the same field already defined in
section 3). A hash mismatch covers both cases in one check: the text
changed (a rewrite), or the pair itself changed (a renumber/insert/split),
because a record computed for the old pair (e.g. scene 1 + scene 2) simply
has no matching record when the fresh list asks about a new pair (e.g.
scene 3 + scene 4). No entry means no match, which is treated identically
to a stale hash: recompute. This is why the plan stores the hash on the
PAIR rather than on either scene alone — a per-scene hash could not tell
the difference between "my text changed" and "my neighbour changed,"
and both require the same fix (recompute this boundary).

**Consequence for a split like scene 1 into three.** The old scene 1's
single `scene_boundary_out` (if one existed) is simply orphaned — the
scenes it referenced (old 1, old 2) no longer form an adjacent pair once
scene 1 becomes scenes 1a/1b/1c. `ensure_boundaries()` does not need to
detect "a split happened" as its own event; it only needs to walk the
fresh scene list, find that 1a-1b, 1b-1c, and 1c-2 have no matching stored
record (or, for 1c-2, that the record on file was computed for a different
pair), and recompute those three boundaries. The other four boundaries
(2-3, 3-4, 4-5, 5-6, becoming 2-3 through 5-6 unshifted except in number)
keep their stored records if their `scene_text_hash` still matches —
splitting scene 1 costs 3 new boundary computations, not 7.

## What could not be determined, and where this plan guesses

- **Per-boundary vs. per-video batching for the model call (chunk 2).**
  `tasks/deferred-verification.md` flags this same choice and doesn't
  resolve it. This plan recommends starting per-boundary (simpler retry
  and gate story, section 7) and named the fallback rather than picking
  blind — an honest open call, not a hidden one.
- **Exact system-prompt wording for the boundary-pass model call.** Not
  drafted here — section 6 states what each law's PROMPT leg must contain,
  but the literal prompt text is chunk 2's build-time work, tuned the same
  free-first way every other prompt in this project was tuned, not
  something a plan document should freeze in advance.
- **Migrations 142-144's exact content.** Confirmed reserved, not free:
  142 = D6-1 canonical inputs, 143 = D6-2 repair stamps, 144 = D6-3 S3
  scene location, all in flight elsewhere. This plan takes their owners
  and purpose on the coordinator's word rather than reading those chunks'
  own files, which were not located to cross-check against. 145 is this
  plan's number.
