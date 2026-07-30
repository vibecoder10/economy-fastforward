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

## S5 — A SCENE STATES WHERE IT IS

Every scene names its location explicitly in its own text, even when it is the
same location as the scene before. The board planner reads one scene at a time; a
scene that says "her ceiling" without naming the room forces the planner to guess,
and a guess becomes a set.

*Provenance: a scene referring only to "her ceiling" and "her grey pod" while the
previous scene had moved the character somewhere else entirely — the planner had
no way to know which set to build.*

---

## How a law becomes behaviour

A law in a document changes nothing. Each law lands in three places, in the same
commit — the contract triangle this project already enforces:

1. **PROMPT** — the law's text enters the script generator's system prompt, so
   scripts are written to satisfy it in the first place.
2. **GATE** — a deterministic check that flags or rejects a script violating it
   (S1: does a scene's location differ from the previous scene's with no transit
   sentence? S3: does every scene declare a location — hard; does a scene's text
   also name another scene's declared location — warn-only, never hard, because
   that check compares prose to prose and directly conflicts with what S1
   requires an outgoing scene's text to contain, see S3's entry above. S5: does
   every scene name a location?). A gate may only be hard when the thing it
   compares against is canonical (a column, not prose) — where no deterministic
   check is feasible, or where the comparison is inherently prose-to-prose, say
   so in the commit and make it advisory rather than pretending a hard gate
   exists.
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

Known gaps, not silently pretended away:
- `static_docu` (product-roundup format) is exempted from the gate — see
  `tasks/deferred-verification.md`'s D6-3 section, item 3, for why and how to re-check it.
- A FOURTH writer to `scripts`, `custom_film_production_runner.py`'s `_script` method
  (~700 lines, whole-arc AV screenplay contract, dialogue segments, language/dubbing
  modes), does not import `story_laws` at all — S3 does not reach it. Judged genuinely
  large rather than a small addition (see D6-3b's report); flagged for its own chunk,
  not silently left uncovered.

S1, S2, S4, S5 remain **not implemented**. S5 (A SCENE STATES WHERE IT IS) has its
groundwork laid — the `scripts.location` column and the `LOCATION:` header convention
S3 introduced are exactly what S5 will consume — but S5's own full contract (every
scene names its location even when unchanged from the scene before) is not yet gated.
Scripts today can and do still violate S1, S2, S4, and S5.
