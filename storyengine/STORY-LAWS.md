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
   sentence? S3: does a scene span more than one location? S5: does every scene
   name a location?). Where no deterministic check is feasible, say so in the
   commit rather than pretending one exists.
3. **REPAIR** — the law's text is carried into the artifact the next stage reads,
   so a regeneration or a manual edit inherits the rule instead of reverting.

Runtime-editable rules belong in the `quality_rules` table, already consumed by
the script stage, so a new ruling does not require a code deploy.

## Status

Not implemented. No S-law currently reaches the script generator's prompt, gate or
repair path. Scripts today can and do violate all five.
