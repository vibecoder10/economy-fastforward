# BOARD LAWS — how a story is told and visualised in storyboards

**These are universal laws, not notes about one video.** Every law below states a
general rule of visual storytelling that any scene of any film must satisfy. Each
was discovered by a specific failure, and that failure is recorded underneath in
italics as *provenance* — evidence that the law is real, never a limit on its
scope. If a law reads as being about a particular character, set or story, it is
written wrong and should be rewritten.

Priority order behind all of it: **the script is the most important step, the
storyboard is the second.** Get those two wrong and nothing downstream can save
the film.

## How these were established

Hand-written board prompts, generated on a free tool with no character sheets and
no environment references, judged panel by panel, rewritten, repeated. A
four-round arc took one scene from "the board contains no exit at all" to nine of
nine panels approved; a five-round arc covered a dialogue scene with a nested
screen; a scene built around a hidden object and a look into the lens passed on
its first round. Every prompt version is preserved in
`tasks/evidence/d3-64-fixes/`. Total spend: nothing.

These laws are cumulative with the AXIS-contract system proven 2026-07-07, which
they extend rather than replace.

---

## Index by craft area

- **The camera resolves in screen space** — L0, L5, L10, L19
- **Space and geography hold across shots** — L1, L9, L13, L14, L15, L16
- **The set is defined before it is shot** — L3, L7, L8, L11, L20, L30
- **People are specified, not assumed** — L6, L12, L17, L22
- **Inputs must be real** — L28, L29
- **Action is legal** — L4
- **Panel discipline** — L2, L21, L27
- **Scene boundaries: the cut between sheets** — L23, L24, L25, L26
- **Laws that belong to the script** — S1-S5, in `STORY-LAWS.md`

---

## The camera

**L0 — SCREEN SPACE ONLY.** Image models cannot execute world-space camera
geometry. Resolve every spatial instruction into frame coordinates: frame-left and
frame-right, fractions of the frame, what occupies which region. The planner
resolves the geometry; the drawer paints an already-finished frame.
*Provenance: research, 2026-07-07 — world-space placement instructions failed
almost every time; screen-space placement held nine panels out of nine.*

**L5 — CAMERA FACTS PER PANEL.** Every panel states four things, all
screen-relative: (1) which side of any barrier the lens is on; (2) camera height;
(3) what fraction of the frame the subject occupies; (4) **face visibility as an
explicit term** — to-lens, three-quarter, profile, or from-behind.
*Provenance: a close-up whose entire purpose was an expression, written with the
subject looking away from the lens, rendered with the face turned away. The prompt
was obeyed; it asked for the wrong thing.*

**L10 — BODY VECTOR TO VISIBLE AXIS.** A motion panel ties the subject's travel
direction to a visible line inside the same panel: state that the vanishing line
is visible past a named shoulder, that the set's lines converge on it, and that
the subject travels along it.
*Provenance: a run specified with a drive direction and a vanishing point in
separate clauses; the two rendered as unrelated, so the subject's turn floated free
of the corridor she was running down.*

**L19 — DIEGETIC CAMERA POV.** When a character looks into a lens, mirror, screen
or camera that exists inside the story, define a setup that occupies that object's
position, mark it NEUTRAL (it legally breaks the axis), and state that the eyes go
directly into camera with no three-quarter. Apply L16 to it: the object's own
housing is not visible from inside itself. Give the shot the device's optical
signature so it reads as that device's view rather than a stylistic flourish.

---

## Space and geography

**L1 — AXIS LOCK.** The camera never crosses the 180 line. Each character holds one
frame side and one looking direction for the whole scene. Over-the-shoulder pairs
go over opposite shoulders at matched sizes. Only an explicit NEUTRAL marker resets
the axis.

**L9 — FRAME-SIDE CONTINUITY ON REPEATED SETUPS.** A repeated setup must name the
same frame side, or the same surface, that it progresses from. A repeat should read
as editing; unqualified, it reads as teleporting.
*Provenance: a repeated wide asked only for a subject "pressed to the glass," and
she appeared at a different pane than the shot it was progressing from.*

**L13 — COVERAGE AGREES WITH THE WIDE.** Two-character coverage must be consistent
with the spacing the establishing wide establishes. An over-the-shoulder pair
implies adjacency; if the wide then shows people between them, the audience feels
the contradiction even when it cannot name it. Either place them adjacent, or state
the compression in the setup.

**L14 — GIVE THE PAIR A TWO-SHOT.** A spatial relationship the audience never sees
stated does not exist, however correct the underlying data is. Before covering a
pair in singles or over-the-shoulders, include one medium two-shot holding both in
the same frame at the same size. Coverage runs master, then two-shot of the pair,
then singles; skipping the middle rung leaves the geography unread.
*Provenance: a seating correction genuinely present in the wides and invisible to
the viewer, because the wide was too wide to read and over-the-shoulders compress
space by design.*

**L15 — SEPARATE ATTENTION FROM ORIENTATION.** When a character shifts attention to
another, state what stays FIXED — chair, hips, feet, the direction the wide
established — and what MOVES — head, shoulders, gaze. State the prohibition too. A
partial turn that does not name its anchor becomes a full re-staging.
*Provenance: "turned three-quarter toward him" rotated both bodies and both chairs
into a face-to-face configuration, breaking a room where everyone faced one way.*

**L16 — A REVERSE ANGLE CHANGES THE BACKGROUND.** State what sits behind the subject
for each camera position, and never carry one background across opposing angles. If
the camera stands between the subject and a light source or screen, that source is
behind camera: it appears as light on the face, never as an object behind them.
*Provenance: a setup that placed the camera in front of a row and also asked for the
screen visible behind them — a geometric impossibility, which the model resolved by
turning the entire room around.*

---

## The set

**L3 — LOCATION SCOPING.** Define a set per location, scope it to the panels in that
location, and forbid cross-contamination explicitly rather than by implication. Never
declare one location's dressing as applying to every panel of a scene.
*Provenance: a scene whose corridor shots rendered as a bedroom, reproducing the
furniture list item for item, because the lock read "identical in every shot of this
scene."*

**L7 — ESTABLISH BEFORE USE.** Anything a character touches, uses or passes through
must be visible in that location's establishing wide before the panel that uses it,
and must be authored into the set definition as a permanent feature — not mentioned
only in the panel that needs it.
*Provenance: an exit that existed only in the panel where it opened; the establishing
wides drew an unbroken wall, so the character climbed out through a door that had
never been there.*

**L8 — SCALE AND ARRIVAL SURFACE.** Establishing an element is not enough; its scale
must establish too. State its size relative to the character, and how it meets the
surface the character arrives on. Repeat both facts in the establishing wides.
*Provenance: an opening given a position but no scale, drawn small enough to crawl
through, contradicting the shot where the character walked out of it upright.*

**L11 — NESTED FRAMES.** A screen, monitor, window or mirror inside the set is a
second frame. Specify its content in every panel where it is visible, or the content
drifts from panel to panel.

**L20 — DEFINE THE SET'S MATERIAL MAP ONCE.** State which surfaces of a set are solid
and which are transparent, and where the boundary between them runs — once, for the
whole film. Ambiguity lets every scene invent its own version of the set. When a
scene needs a property the set lacks (contrast, a mounting point, a surface), find it
inside the established set rather than redefining the set.
*Provenance: a part-glass, part-solid interior that one scene wrote as fully opaque to
get contrast for a small dark object, and the correction then wrote as fully
transparent. Both were half-right, because the material map had never been written
down.*

**L30 — THE BOARD NAMES THE SCRIPT'S DECLARED LOCATION (STORY-LAWS.md S6).** When the
script states a scene's location, the board's location-declaring text — the FIXED SET
or LOCSET header, the MATERIAL MAP, the ENVIRONMENT LOCKS — must name it. The script
is the origin of truth; a board that never says "kitchen" for a scene the script
places in a kitchen is not merely a bad picture, it is a faithful render of a plan
that silently dropped the script's own stated fact.
*Provenance: tenant PocoAPoco video d39892b2-0c85-4752-85d7-b61ca209342a, scene 1 —
the script's stated location was "the kitchen at home"; the 32,790-character assembled
board prompt never contained the word "kitchen," and the board drew the bedroom
instead.*

---

## People

**L6 — IDENTITY ONCE.** State appearance once, at the top, as a short locked tag.
Never repeat wardrobe descriptions per panel: long re-descriptions fight the reference
images and consume the word budget camera facts need. References own what things look
like; prose owns where the camera is and what fills the frame.

**L12 — SPECIFY THE POPULATION.** Background people are part of the set. State what
the crowd, the sleepers, the extras look like, so the hero's contrast is authored
rather than accidental. State the population in depth too: how many occupants per
container, and that anything behind the readable front layer falls into shadow.
*Provenance: unspecified background figures rendered pale, which made the hero stand
out by luck; and transparent containers rendering bodies stacked through one another
until each looked like it held two people.*

**L17 — LOCK THE HEADCOUNT.** State the number of people in every panel where a group
appears, as a number, and forbid drift. Counts silently drift whenever they are
implied by a list rather than stated as a quantity.

---

## Action

**L4 — MOTION IS LEGAL.** The fixed-camera, planted-actor convention applies within a
location, not across a scene. Characters may move, cross, exit and change location.
Planted staging is correct for a conversation and a category error for action: action
needs setups that describe a move — exits frame-right and camera holds, runs toward
the lens, travels alongside.
*Provenance: a static-tableau board architecture, validated on a seated conversation,
applied to a scene where a character wakes, crosses a room and runs down a corridor.
It could not express a character leaving a room, so the exit silently vanished from
the board.*

**L21 — A BOARD CANNOT SHOW DURATION.** A still panel can show a moment, never a
length of time. If a beat's content is "time passes and nothing changes," no panel
can carry it: never spend a panel on an identical repeat of an earlier one. Note
the hold for the motion and edit layer, and use the panel to escalate instead —
same subject, closer or wider, so the sheet gains information rather than
repeating it.
*Provenance: two panels of a nine-panel sheet were deliberately specified as
identical, to express a character's stillness lasting. They rendered identical
exactly as instructed — proving a nested frame can be matched across panels — and
the repetition read as waste, because the beat was a duration and a frame cannot
hold one.*

**L22 — STATE GROUP ARRANGEMENT PER CAMERA POSITION.** A headcount alone does not
hold. State who sits or stands where AS SEEN FROM THIS CAMERA, and remember that a
reverse angle reads the order backwards. When the arrangement is stated once from
the front and never restated for the opposing angle, the model must work the order
out for itself and quietly drops a figure.
*Provenance: a reverse wide instructed with an explicit "all five" still rendered
four, because the seating order had only ever been given from the front-on side.*

---

## Panel discipline

**L2 — ONE ACTION PER PANEL.** One action. Never mirror or flip a panel. No readable
text in panel artwork except the panel-number label.

**L27 — INSTRUCTIONS ARE NOT CAPTIONS.** Text written to instruct the drawer can be
rendered by it as text. Never phrase a panel brief as a labelled directive — an
all-caps heading, a colon, a bracketed note — because a caption strip will absorb it
and bake it into the sheet. State the same fact as ordinary prose describing what is
in the frame, and state once, in the sheet header, exactly what the caption strip may
contain and that nothing else ever appears there.
*Provenance: an arrangement instruction written as "ARRANGEMENT AS SEEN FROM THIS
CAMERA (REVERSED): ..." inside a panel brief was rendered verbatim into that panel's
caption strip. The instruction worked — the headcount held — and it printed itself
onto the artwork.*

**L28 — NEVER ASSERT AN INPUT THAT IS NOT ATTACHED.** A prompt that says "match the
attached reference images" when nothing is attached does not merely fail to
constrain the drawer — it licenses invention and makes the invention confident,
because the model believes it is matching something. Either attach the references,
or describe what to draw instead. The same applies to any claimed input: a style
reference, a previous panel, a cast sheet. Assert only what is genuinely in the
call.
*Provenance: an emitted board prompt instructed "Draw every character consistently
across every panel, matching their appearance to the attached reference images"
while the characters never reached the call; the model invented a cast and drew it
consistently, which reads as deliberate and is impossible to notice from the prompt
text alone.*

**L29 — DECLARE ONE STYLE, ONCE.** The style is the single most visible property of
a frame and must be stated exactly once, from one source of truth, with nothing that
contradicts it. A prompt carrying two style claims lets the model choose, and it will
choose the one you did not want.
*Provenance: the same emitted prompt described "a storyboard sheet for an ANIMATED
scene" and, two sentences later, "the same art style, Photorealistic, cinematic film
still." The model resolved the contradiction toward photorealism, so an animated
film's board came back live-action — a defect invisible in the law text and obvious
in the picture.*

---

## Scene boundaries — the cut between two sheets

**L23 — TRANSITIONS ARE PLANNED ABOVE THE SCENE.** A boundary between two scenes
cannot be authored inside either of them. A scene-scoped planner sees one scene and
therefore cannot make a cut. Before boarding, a film-level pass walks every
boundary and records four things: the relationship type, the OUT shot that ends the
earlier scene, the IN shot that opens the later one, and what carries across
(subject, shape, direction, light, or a frame-within-the-frame). Each scene's board
prompt then receives two blocks it did not choose for itself:

    INCOMING — the previous scene ended on: <exact description of that final panel>.
    Your FIRST panel relates to it by <relationship>, specifically: <instruction>.

    OUTGOING — your FINAL panel must be: <exact description>, because the next
    scene opens by <relationship>.

Without those blocks each sheet begins and ends wherever it likes, and the film
stutters at every seam even when every scene is internally perfect.

**L24 — THE LEGAL BOUNDARY RELATIONSHIPS.** A cut between scenes is one of these,
chosen deliberately, never left to chance. Each has a requirement:
- **MATCH** — the two shots share a shape, composition or subject, so meaning
  transfers across the cut. Requirement: state the shared element and hold the
  framing close enough that a viewer sees it as the same shape.
- **NESTED HANDOFF** — the image ending one scene becomes an image inside a screen,
  mirror or window opening the next. Requirement: the nested version must repeat the
  original framing exactly (see L11), then the next panel reveals its new context.
- **CONTINUATION** — the same subject continues one action across the cut, usually
  through a location change. Requirement: the action and its screen direction
  continue unbroken (see L25).
- **SIGHTLINE BRIDGE** — one scene ends on someone looking; the next opens on what
  they are looking at, or moves the camera to where they were looking from.
  Requirement: the look must be readable in the OUT shot.
- **CONTRAST** — the cut works by opposition: intimate to vast, dark to bright,
  empty to crowded, still to moving. Requirement: name the axis of opposition and
  make it large; a small contrast reads as an accident.
- **ELLIPSIS** — same place, later. Requirement: something visible must have changed
  to mark elapsed time — light, a prop's state, an absence.

**L25 — DIRECTION AND EYELINE CARRY ACROSS THE CUT.** Screen direction does not
reset at a scene boundary. A subject exiting frame-right enters the next scene from
frame-left to continue travelling the same way; an eyeline pointing frame-right is
answered by a subject at frame-right. A direction that reverses without an on-screen
turn reads as the character changing their mind. If a reversal is intended, the
turn itself must be a panel — usually the OUT shot.

**L26 — NO ACCIDENTAL NEAR-REPEAT AT A BOUNDARY.** Two shots that are similar but
not identical across a cut read as a stutter. At a boundary, either match
deliberately and exactly, or change decisively — shot size, angle, or location. The
one thing a seam cannot survive is *almost* the same picture.

---

## Laws that belong to the script

Boarding a script is the cheapest way to find script defects, but the board cannot
fix them. Those laws live in `STORY-LAWS.md` (S1-S6): narrate every location
change; a payoff must be paid for earlier; one scene is one location and one
continuous beat; the script is the source of truth for cast; a scene states where
it is; the script is the origin of truth, and changing it invalidates what came
before. L30 above is the board's own enforcement leg of S6, for location specifically.

---

## Method

**Tune with free tools before spending anything.** Hand-write the board prompt,
generate it on a free tool, judge it panel by panel, fix the WORDS, repeat. Then, and
only then, spend on the real pipeline. Escalate to harder scenes on purpose — dialogue
axis, nested screens, crowds, hidden objects, multi-location action — because each new
difficulty surfaces new laws.

**Every defect becomes a law, not a patch.** If a fix applies only to the scene in
front of you, it has not been understood yet.

**Judge every batch on the full rubric, unprompted.** Per-shot purpose against facing
and framing; pair-wise axis, eyelines and cut grammar; scene-level causality and style
drift. Then trace every failure to its prompt and classify it: either the model
disobeyed a correct instruction, or the instruction itself was wrong. Only the first
kind is worth re-rolling; the second kind is a law.

**Keep the best-known-good, and be willing to regress to it.** Every version is saved
so a revert is one command. Iteration is progress only while each round beats the last
known-good version, not merely the previous attempt — fixes can and do introduce the
next defect.

**Judge at the cheapest artifact that shows the defect.** A wrong-facing character
caught on a board costs one board; caught after the frames, it costs every frame. The
board is where the film is decided.

---

## How a law becomes behaviour

A law in a document changes nothing. Each law lands in three places, in the same
commit — the contract triangle this project already enforces:

1. **PROMPT** — the law's text enters the board planner's system prompt, so plans
   are written to satisfy it in the first place. For the L-series this means the
   coverage planner's system prompt and the sheet-prompt assembly that composes
   what the drawer actually receives.
2. **GATE** — a deterministic check that flags or rejects output violating the law.
   Some are mechanical (L17: is the stated headcount present in every group panel?
   L5: does every panel carry all four camera facts? L3: does a panel's text name
   props from a location it is not in?). Others are not deterministically checkable
   with today's schema (L13, L14) and need either a schema addition or a vision
   judge. Where no deterministic gate is feasible, say so in the commit rather than
   pretending one exists.
3. **REPAIR** — the law's text is stamped into the per-shot artifact the next stage
   reads, so a regeneration or a manual repair inherits the rule instead of
   reverting to pre-law behaviour. This project already stamps SET, AXIS, STAGING
   and SEQUENCE locks this way; every new law needs its own stamp or it evaporates
   the first time a single shot is redrawn.

Runtime-editable rules belong in the `quality_rules` table so a new ruling does not
require a code deploy. That table currently has no board or image scope — adding
one is a prerequisite, not an optimisation.

**A law with a prompt leg but no gate is a suggestion. A law with a prompt and a
gate but no repair leg survives until the first redraw. All three, or it is prose.**

## Status

Partially implemented as of 2026-07-29, and deployed to production (migrations 142, 143, 144 applied
2026-07-30 04:02Z).

Laws with live code, verified by an independent reviewer: L3, L6, L11, L12, L15, L16, L17, L19, L20,
L22, L28, L29 all have a gate or a repair leg or both. L16 and L22 are genuinely CALCULATED rather
than instructed, which is what BOARD-PLANNER-ARCHITECTURE.md asked for. L18 has a gate and
deliberately no repair leg, because a naive stamp would contradict that law's own "shot size changes"
clause. L23 to L26 have a renderer (`format_boundary_blocks`) and a written plan
(`BOUNDARY-PASS-PLAN.md`) but nothing yet PRODUCES the boundary records, so those four are not live.

Known gaps, stated plainly rather than left implied:
- The canonical set and material data reaches the $0.05 sheet PREVIEW path but NOT yet the real
  per-shot pictures path, where `run_coverage` still reads the planner's own `[MATERIAL|]` line. Filed
  as chunk D6-1c and it BLOCKS the proof run, because a dry run that inspects only the preview would
  report compliant while the pictures actually paid for still diverge.
- L29 remains live for preset-only videos, whose style resolves through a separate mechanism that the
  style resolver never touches. Filed as D6-1d.
- Every canonical column is NULL for all existing rows, so the fallback path is the only path running
  in production today. The laws are enforceable, not yet enforced on real data.

The acceptance target for the planner build is unchanged:
`tasks/evidence/d3-64-fixes/scene1_board_prompt_CORRECTED_v3.txt`, the sheet Ryan scored 9 out of 9. A
planner should emit that shape unaided. That has NOT been demonstrated yet - it is chunk D6-6a, a $0
dry run, followed by D6-6b, one paid board, which needs Ryan's explicit approval.
