# STORY LAWS — how a script must be written so it can be filmed

**Universal laws, not notes about one video.** These govern the SCRIPT layer: what
a scene must contain before anyone tries to board it. They were all discovered by
boarding a script and hitting something the board could not draw — which is the
cheapest place to find a script defect, and the only layer where fixing one costs
nothing.

Companion document: `BOARD-LAWS.md` governs the visual layer. A law belongs here
if no storyboard, however well written, could fix it.

Priority order: **the script is the most important step, the storyboard is the
second.** Get those two wrong and nothing downstream can save the film.

---

## S1 — NARRATE EVERY LOCATION CHANGE

If a character is in one place and then in another, the script contains the
transit. Not a summary of it — the actual beat: the door, the threshold, the
travel, the arrival. A board asked to draw an unnarrated move will either invent
one or silently skip it, and both read on screen as a broken cut.

*Provenance: found twice in the same story. A character sealed inside a room was
described as "then she is up and moving" in a corridor, with no sentence for
getting out — so the board drew no exit and the film cut from inside to outside
with nothing between. Two scenes later the same character was back inside, again
with no sentence for returning.*

**S1's hard/warn split (D6-4 ruling — this is what actually shipped, read it
before assuming S1 is a single check):** S1 is two questions, and Ruling 1 (a
gate may only be HARD when what it compares is CANONICAL) puts them on opposite
sides of the line. "Does scene N's location differ from scene N-1's?" compares
two CANONICAL COLUMN values (`scripts.location`) — reliable, and eligible to be
hard. But a location changing between scenes is not itself a defect; stories are
supposed to move characters around, so nothing is ever blocked on that fact
alone. "Was a transit actually narrated?" is inherently PROSE detection — there
is no reliable way to recognise a narrated threshold in free text, and a real
transit written in words the checker doesn't recognise must never be punished
as if it were missing. Per Ruling 1 this MUST warn, always, permanently. So: the
location-change comparison is canonical and reliably computed, but the only
thing that check can ever report is a WARNING, never a block — see
`backend/story_laws.py`'s `check_location_transit_law` for the implementation
and the same ruling spelled out in code.

## S2 — A PAYOFF MUST BE PAID FOR EARLIER

A theme asserted in the closing scene has to be bought by a cost the character
pays before it. If the last line states the idea, an earlier scene must have
proved it the hard way. An unearned closing line reads as the writer's opinion
rather than the character's discovery.

*Provenance: a closing line about where power really lies, asserted rather than
earned. Fixed by making an earlier escape attempt fail — the character finds the
real exit only after the obvious one is gone, so the final line becomes the
conclusion of an experience instead of a caption on it.*

## S3 — ONE SCENE IS ONE LOCATION AND ONE CONTINUOUS BEAT

When the story changes location, or moves into a distinct phase of action, that is
a new scene. A scene that tries to hold several locations and several phases will
be boarded as a compressed summary: the planner allocates a handful of panels per
scene, so a scene carrying four beats gets one panel each and the story reads as
a series of disconnected stills.

Symptoms that a scene is doing too much: its beats span more than one location;
its coverage cannot establish anything because every panel is a different moment;
a reader has to be told what happened between two panels.

*Provenance: an opening scene asked to carry waking, a decision, an escape through
a hatch, a corridor run, a failure and a return — six beats across two locations.
Split into three scenes (the escape, the run and its dead end, the return), each
gets real coverage.*

**S3/S1 interaction (D6-3b ruling, do not re-tighten this without re-reading it):**
the GATE's `cross_location_text` check — does a scene's text name another scene's
declared location? — compares PROSE to PROSE, and is WARN-ONLY, permanently. It
can never block. This is not a missing feature; it is required by S1 (NARRATE
EVERY LOCATION CHANGE): an outgoing scene's text legitimately, necessarily names
the place the story is headed to — "She leaves the corridor behind and steps onto
the bridge" is exactly what S1 demands, and it will always mention the destination
scene's location. Hard-blocking on that text would put S3 in direct conflict with
S1. The conflict resolves in S1's favor: S1 governs whether the script is filmable
at all, S3 governs whether a scene is the right size. The same reasoning covers
dialogue/memory naming another place ("I grew up in the corridor") and a character
looking through a window or screen at another location (legal per BOARD-LAWS L11).
Only the OTHER S3 check — `no_location`, a scene with no declared location at all
— is a hard gate: `location` is a real column, not a guess, so its absence is a
fact, not an interpretation.

## S4 — THE SCRIPT IS THE SOURCE OF TRUTH FOR CAST

Every character the script describes must be cast as the script describes them. If
the script says a woman in gold and an old man, the visual layer does not get to
render three interchangeable figures in navy. Where the script and the character
bible disagree, one of them is wrong and a human decides which — silently
following the bible loses the writer's intent, and silently following the script
loses continuity.

*Provenance: a scene whose script named two specific speakers while its board cast
three generic elders in different wardrobe entirely, so the dialogue's visual
identity did not match the words being spoken.*

**Ruling, 2026-07-29.** The case that produced this law was decided by Ryan in favour of the script: a scene whose
script named a woman in gold and an old man, boarded instead as three interchangeable navy-suited elders, is a board
defect and not a continuity reference. The script's cast is canonical and the board is regenerated to match it. Where a
script and a character bible disagree, this is the direction the ruling sets, though the law still requires a human to
make the call rather than silently following either side.

**S4 gets a PARTIAL, warn-only gate (D6-4) — not a full one, and it never can
be.** `video_characters.name` IS a real canonical column, but the other side of
the comparison is the script's free text, and matching a canonical name against
prose is still fundamentally a prose search — a script can legitimately
describe a character without ever using their sheet name ("a woman in gold"
instead of "Elder Mara"). Per Ruling 1 that can only ever warn. What's built
(`backend/story_laws.py`'s `check_cast_consistency_law`) flags two directions:
a cast member never named anywhere in the script, and a dialogue speaker in the
script with no matching cast entry. It does NOT and cannot decide which side is
right — that is a human call. **This is the exact still-open case from
HANDOFF.md: the script says "a woman in gold" and "an old man," the board cast
three named navy-suited elders. The check will flag that mismatch. Ryan still
owes a ruling on which one is canonical for that video — this chunk does not
resolve it, only surfaces it.**

## S5 — A SCENE STATES WHERE IT IS

Every scene names its location explicitly in its own text, even when it is the
same location as the scene before. The board planner reads one scene at a time; a
scene that says "her ceiling" without naming the room forces the planner to guess,
and a guess becomes a set.

*Provenance: a scene referring only to "her ceiling" and "her grey pod" while the
previous scene had moved the character somewhere else entirely — the planner had
no way to know which set to build.*

**S5 was already fully implemented by D6-3 — D6-4 found this, built nothing new,
and is only correcting the record.** S5's full text ("every scene names its
location... even when unchanged from the scene before") is EXACTLY what a hard,
per-scene, no-exception `location IS NOT NULL` check enforces — it never makes an
exception for "same location as before," so it already satisfies S5's own
"even when unchanged" clause. That check is `story_laws.check_scene_location_law`'s
`no_location` leg, described under S3 below. All three legs already existed
before D6-4: PROMPT (`SCENE_LOCATION_LAW` requires a header on every scene, not
just changed ones), GATE (`no_location`, unconditional), REPAIR
(`edit_scene_text`/`regenerate_scene_text` carry the column forward and
re-check). No separate S5 function or test file exists, and none should be
added — see `backend/story_laws.py`'s module docstring for the same note in
code.

## S6 — THE SCRIPT IS THE ORIGIN OF TRUTH, AND CHANGING IT INVALIDATES WHAT CAME BEFORE

Everything downstream is derived from the script: the cast, the environments, the
boards, the coverage, the voice. So when scene text changes, every artifact built from
the older text is stale by construction. A pipeline that overwrites scene text without
marking those artifacts stale does not produce a quality defect, it produces a faithful
render of a script that no longer exists. The stale artifact must be flagged rather than
silently kept, and it is never preserved for continuity against the script's own words.

The practical rule: a scene-text write is not just a write. It is an event with
consequences, and the consequences are the whole reason a script edit is cheap while a
redraw is not.

*Provenance: a scene whose script named a woman in gold and an old man was boarded as
three interchangeable navy-suited elders, and the mismatch was read for days as a
casting or drawing failure. Timestamps proved otherwise. The characters were generated
2026-07-27 at 23:33, the boards were drawn 2026-07-29 at 07:06, and the scene text
naming those two characters was not written until 2026-07-30 at 01:46. The cast was a
faithful render of the script as it stood; nothing marked it stale when the script
moved. 15 of the 28 videos holding characters have a scene edited after their cast was
created, so this is the normal condition and not one video's accident.*

---

## How a law becomes behaviour

A law in a document changes nothing. Each law lands in three places, in the same
commit — the contract triangle this project already enforces:

1. **PROMPT** — the law's text enters the script generator's system prompt, so
   scripts are written to satisfy it in the first place.
2. **GATE** — a deterministic check that flags or rejects a script violating it.
   A gate may only be HARD (blocking) when the thing it compares is CANONICAL
   (a column, not prose); a prose-vs-prose comparison must WARN, never block.
   Where no deterministic check is feasible at all, say so in the commit and
   admit the gap rather than pretending a check exists. Per-law shape:
   - **S1** (narrate every location change): does scene N's `location` column
     differ from scene N-1's (canonical, reliably computed) — but that fact
     alone is never a defect, so nothing is ever blocked on it. Was a transit
     actually narrated — inherently prose, so this can only ever warn. See
     S1's own entry above for the full split.
   - **S2** (a payoff must be paid for earlier): NO deterministic check exists,
     none is planned. Judgement about dramatic structure, not a fact any
     column or reliable text pattern can verify.
   - **S3** (one scene, one location): does every scene declare a location —
     hard (`no_location`); does a scene's text also name another scene's
     declared location — warn-only, never hard, because that check compares
     prose to prose and directly conflicts with what S1 requires an outgoing
     scene's text to contain (see S3's entry above).
   - **S4** (script is the source of truth for cast): PARTIAL, warn-only. One
     side (`video_characters.name`) is canonical, but matching it against the
     script's free text is still a prose search, so this can never be hard.
     See S4's own entry above.
   - **S5** (a scene states where it is): already fully satisfied by S3's own
     `no_location` check — hard, unconditional, no separate check exists or
     should exist. See S5's own entry above.
3. **REPAIR** — the law's text is carried into the artifact the next stage reads,
   so a regeneration or a manual edit inherits the rule instead of reverting.

Runtime-editable rules belong in the `quality_rules` table, already consumed by
the script stage, so a new ruling does not require a code deploy.

## Status

**S3 implemented (D6-3, 2026-07-29; corrected D6-3b, same day, after an independent
verifier ran the gate live and found four real defects — see that commit's message for
the full list).** `backend/story_laws.py` is the one place the S3 text and its
deterministic checks live. PROMPT: reaches the ACT-based docu path (via
`pipeline_executor.resolve_prompt`, riding along any tenant/per-video override the same
way standing preferences do), the modeled/style-replicated path (its own inline prompt,
now importing the shared constant instead of a hand-rolled copy), and the MCP
`submit_script` tool description (an external agent is told the contract, not silently
left to guess it). GATE, two severities (see the S3/S1 interaction box above):
`no_location` is hard (blocks); `cross_location_text` is warn-only, permanently.
Hard-fail at generation for paths (a) and (b): for (b) (modeled), checked BEFORE any
DB write — a failing script writes nothing. For (a) (ACT-based docu), the check runs
AFTER `_write_script_records` has already progressively written the new scenes (a
pre-existing property of that shared writer, not something this gate controls) — on a
violation the gate deletes those rows and records the failure on
`videos.script_validation` before returning `needs_review`, so nothing bad is left
silently sitting in `scripts`, but this is a delete-after-write, not a check-before-write,
and the two paths should not be assumed identical. WARN-only for `set_user_script`
(creator-verbatim bypass, by design — records both severities, blocks on neither).
Hard-reject on `no_location`/warn-only on `cross_location_text` for
`accept_external_script` (agent-submitted, already had a reject contract). A `needs_review`
result is surfaced honestly through BOTH the in-process task path (routes/pipeline.py's
existing `_set_task_status`) and the arq worker path (`worker.py:_run_stage`, added
D6-3b) — the arq path has no way to represent `needs_review` as its own
`background_tasks.status` (hard CHECK constraint, no such bucket) so it persists
`failed` with the violation text rather than silently normalizing to `completed`, which
was the actual defect: a gate that reports success while blocking the work. REPAIR:
`edit_scene_text` and `regenerate_scene_text` (routes/videos.py) carry the scene's
location forward via `COALESCE(new, existing)`, and D6-3b added a post-write re-check
(warn-only, returned as `story_law_s3_warnings`) so an edit that reintroduces a
violation is visible rather than silently undetected.

Known gaps, not silently pretended away (carried from D6-3, still true):
- `static_docu` (product-roundup format) is exempted from the S3 gate — see
  `tasks/deferred-verification.md`'s D6-3 section, item 3, for why and how to re-check it.
  S1's gate is never reached there either, for the same reason (no location concept).
- A FOURTH writer to `scripts`, `custom_film_production_runner.py`'s `_script` method
  (~700 lines, whole-arc AV screenplay contract, dialogue segments, language/dubbing
  modes), does not import `story_laws` at all — S3 does not reach it, and neither does
  S1 (D6-4 built on the exact same three paths D6-3 reached, no more, no less). Judged
  genuinely large rather than a small addition (see D6-3b's report); flagged for its own
  chunk (D6-3f), not silently left uncovered.
- Migration 144 (`scripts.location`) had NOT been applied to the production database as
  of this chunk (`se db` confirmed the column doesn't exist yet on prod — `\d scripts`
  shows no `location` column) — expected, since S3/D6-3 has not been deployed
  (`se deploy`) yet, and this chunk is under the same zero-deploy constraint. The
  migration auto-applies on the next backend restart (`main.py`'s `_run_pending_
  migrations`, best-effort at startup). Until that deploy happens, EVERY scene in
  production has `location = NULL` implicitly (the column doesn't exist), so S3's
  `no_location` gate — and by extension S5 — would hard-block every single script
  generation the moment this code goes live, on videos that were never given a chance
  to carry a location. Read as: this whole gate stack (S3, S5, and S1's canonical half)
  is DORMANT until deploy, and deploy day needs the migration confirmed applied FIRST,
  or every video's next script generation fails.

**S1 (NARRATE EVERY LOCATION CHANGE) implemented (D6-4, 2026-07-29).**
`backend/story_laws.py`'s `check_location_transit_law` (GATE, pure, no I/O) and
`LOCATION_TRANSIT_LAW` (PROMPT). Reaches the SAME three paths D6-3's S3 reached, no
more: PROMPT rides alongside `SCENE_LOCATION_LAW` in `pipeline_executor.resolve_prompt`
(ACT-based docu path) and `_run_modeled_script`'s inline prompt (modeled path), and the
MCP `submit_script` tool description now explains S1 to a submitting agent (and no
longer overclaims that a cross-location mention gets rejected — that line was stale,
predating D6-3b's ruling; fixed in the same commit). GATE: cross-scene by nature (needs
scene N-1), so it can ONLY run where the full scene list is available — the SAME
gate call sites D6-3 already established (the docu path's post-write `_check_scene_
location_law`, now paired with a sibling `_check_location_transit_law`; the modeled
path's pre-write in-memory scene list; `set_user_script` and `accept_external_script`
in user_script.py). It CANNOT run in a genuinely per-scene write path with no neighbour
visible — none of S3's four writers actually work that way at the point the gate runs
(the ACT-based docu writer inserts per-act, but the gate reads back the FULL video after
the write, same as S3's own gate does), so this was not a real constraint in practice,
only a documented one. Warn-only, permanently, on both legs (see S1's own entry above
for the hard/warn split) — never blocks anywhere. REPAIR: `edit_scene_text` and
`regenerate_scene_text` (routes/videos.py) re-run the check after every edit and surface
warnings under their OWN key, `story_law_s1_warnings` (separate from S3's
`story_law_s3_warnings` — no existing caller's behavior changes). Because an S1 warning
concerns a PAIR of scenes, both repair legs match on either half of the pair
(`from_scene`/`to_scene`), not just the edited scene number, or an edit to the OUTGOING
scene of an unnarrated pair would silently show nothing.

**S5 (A SCENE STATES WHERE IT IS) — found ALREADY IMPLEMENTED by D6-3 (confirmed D6-4,
2026-07-29), nothing new built.** See S5's own entry above and `backend/story_laws.py`'s
module docstring for the reasoning. This corrects D6-3's own status section, which
called S5 "not implemented" while its `no_location` check already satisfied S5's full
contract — an honest documentation gap, not a code gap.

**S4 (THE SCRIPT IS THE SOURCE OF TRUTH FOR CAST) — PARTIAL, warn-only gate implemented
(D6-4, 2026-07-29).** `backend/story_laws.py`'s `check_cast_consistency_law` (GATE only —
see S4's own entry above for why PROMPT and REPAIR are thinner here). PROMPT: honestly
ABSENT. There is no sensible injection point analogous to S1/S3's script-generation
prompts — cast is extracted FROM the script (`routes/characters.py`'s `_extract_cast`)
rather than the other way around, and video_characters doesn't exist until AFTER the
script does, so there is nothing to tell the script-writer that would change anything.
GATE: wired at `routes/characters.py`'s `approve_cast` — the earliest point both the
script and the canonical `video_characters` rows exist together (script-generation time
is too early; `video_characters` doesn't exist yet). Free read (no LLM call), best-effort,
surfaced in the approval's own completion message, never blocks the approval. REPAIR:
`update_character`'s PATCH endpoint re-runs the check when a character's `name` is
edited (the only field the check compares) and returns `story_law_s4_warnings` on the
response — cheap (two free SELECTs), never blocks the edit, skipped entirely when only
`description`/`identity_tag` change (nothing the check compares moved). NOT wired into
`design_characters`/`regenerate_character`/script-generation time — those either predate
`video_characters` existing or are the same background-task shape as `approve_cast`
already covers once cast is locked in.

**S2 (A PAYOFF MUST BE PAID FOR EARLIER) — admitted, no gate, none planned.** No
deterministic check exists in `story_laws.py` and none is planned. "Is the closing theme
earned by an earlier cost" is a judgement about dramatic structure, not a fact any
column or reliable text pattern can answer — a hard OR warn gate here would be security
theatre, pretending a check exists where none is possible. This is a permanent
admission, not a placeholder for a future chunk.

**S6 (THE SCRIPT IS THE ORIGIN OF TRUTH, AND CHANGING IT INVALIDATES WHAT CAME
BEFORE) — all three legs landed, 2026-07-30.** GATE + REPAIR landed first (D7-2:
`videos.characters_hash`/`environments_hash`, migration 145 — every script write
recomputes and compares the hash the CURRENT cast/environments were generated from,
flagging `video_characters.status`/`video_environments.status = 'stale'` on a mismatch,
FLAG-never-delete, wired at `routes/videos.py`'s `sync_video_script` choke point plus
the direct-write paths that bypass it; D7-3: a scene edit also invalidates the scene's
stored `coverage_directive_hash` and voice/image/clip pointers, not just cast/
environments). PROMPT landed in this chunk (D7-6): `backend/story_laws.py`'s
`SCRIPT_IS_SOURCE_OF_TRUTH_LAW` rides along the SAME two script-generation call sites
S1/S3 already reach — `pipeline_executor.resolve_prompt` (ACT-based docu path, appended
after `SCENE_LOCATION_LAW`/`LOCATION_TRANSIT_LAW`) and `_run_modeled_script`'s inline
prompt (modeled path) — plus the MCP `submit_script` tool description (`routes/mcp.py`)
and `user_script.py`'s module docstring and `accept_external_script` docstring, so a
human or agent using the external-script acceptance surface is told the same contract.
Unlike S1/S3, S6 has no per-scene deterministic check of its own to add to
`story_laws.py` — "did the writer treat the script as canonical" is not a fact any
column or reliable text pattern can verify — so PROMPT is intentionally S6's only leg
in that module; GATE and REPAIR are instead the hash-compare/invalidation MECHANISM
already living in `routes/videos.py` (D7-2/D7-3), not duplicated here. UI leg (D7-4,
also landed 2026-07-30): an orange "stale" badge and explanatory line on the
Characters/Environments tabs, plus warning banners near their Approve bar and in the
Scenes tab (where storyboard/redraw spend actually happens), surface the GATE's flag to
a human before money is spent on a stale cast/environment/redraw — a flag nobody sees
is the same as no flag. Known gap, not silently pretended away: `user_script.py`'s
`set_user_script`/`accept_external_script` write `videos.script` directly (like the
three paths D7-2's own status note already lists) but are NOT among the paths D7-2
gives an explicit `_flag_stale_cast_and_environments` call — an external/creator-
submitted script that changes the story does not currently re-trigger the GATE.
Flagged here, not fixed in this chunk (D7-6 is PROMPT-only, and both call sites belong
to routes/videos.py's staleness mechanism, out of scope for this pass).

**S6-A (the LIVE storyboard planner consumes the script's per-scene location) — landed
2026-08-05.** A separate, narrower application of S6's principle from D7-6 above (which
covers cast/environment/scene STALENESS after an edit): this chunk makes the board
actually READ `scripts.location` in the first place, rather than re-deriving a scene's
location from prose alone. `storyengine/backend/scripts/coverage_to_app.py`'s
`generate_storyboard_sheet_for_scene` now selects `scripts.location` and threads it
three ways — into `_match_scene_env`'s environment-matching preference (a canonical
match beats phrase-scoring free prose), into the planning prompt
(`storyboard/coverage.py`'s `generate_coverage_directive`/`_coverage_user_prompt`, as a
stated fact the planner's `[SET|]`/`[LOCSET|]` header(s) must name), and into the FIXED
SET header itself (prepended when the planner's own line doesn't already name it). GATE:
BOARD-LAWS.md's new L30 (`_assert_scene_location_declared`), a HARD gate — canonical
`scripts.location` vs. composer-owned prompt text, not prose-vs-prose — peer of L29,
same catch/blocked_scenes flow, NULL-location scenes exempt. Provenance: tenant
PocoAPoco video d39892b2-0c85-4752-85d7-b61ca209342a, scene 1 — script location "the
kitchen at home", the assembled board prompt never said "kitchen," board drew the
bedroom.
