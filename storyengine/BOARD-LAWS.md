# BOARD LAWS — the storyboard prompt contract

Ryan's priority order: **the script is the most important step, the storyboard is
the second.** Get those two wrong and nothing downstream can save the video. These
laws govern what the board planner must emit.

Established 2026-07-29 by hand-writing a corrected scene-1 board prompt and
testing it free in ChatGPT, with no character sheets and no environment locks,
across four rounds: v1 scored 7/9 panels, v2 scored 8/9, v3 scored **9/9 —
Ryan: "this is exactly what we want. This is perfect."** Every defect found in
those rounds is a law below. Prompt versions and the rejected production prompt
are preserved in `tasks/evidence/d3-64-fixes/`.

The laws are cumulative with the proven AXIS-contract system (2026-07-07), which
they extend rather than replace.

---

## The inherited law (do not break it)

**L0 — SCREEN SPACE ONLY.** Image models measurably cannot execute world-space
camera geometry ("three feet to her left at 45 degrees" fails ~100%). The
planner resolves all blocking into frame coordinates; the drawer paints a
finished frame. Every law below is expressed in screen space for this reason.

**L1 — AXIS LOCK.** The camera never crosses the 180 line. Each character holds
one frame side and one looking direction for the whole scene. Over-the-shoulder
pairs go over *opposite* shoulders at *matched* sizes. Only an explicit NEUTRAL
marker legally resets the axis.

**L2 — ONE ACTION PER PANEL.** Never mirror or flip a panel. No readable text in
panel artwork except the panel-number label.

---

## The new laws

**L3 — LOCATION SCOPING.** Sets are defined per location and scoped to the panels
in that location. A scene may contain more than one location. Props from one
location never appear in another, and this must be stated as a prohibition, not
implied. *Never* write "identical in every shot of this scene" across locations —
that single phrase caused corridor shots to render as a bedroom, item for item.

**L4 — MOTION IS LEGAL.** The fixed-camera / planted-actor rule applies *within a
location*, not across a scene. A character may move, cross, exit, and change
location. Planted staging is correct for a conversation and a category error for
action: a wake-cross-run scene needs setups that describe a move (exits
frame-right and camera holds / runs toward the lens / travels alongside).

**L5 — CAMERA FACTS PER PANEL.** Every panel states four things, all
screen-relative:
1. which side of any barrier the lens is on (inside the glass vs shooting in
   through it — the single biggest variable in a glass-walled set, and the one
   most often left implied);
2. camera height;
3. how much of the frame the subject occupies;
4. **face visibility as an explicit term** — to-lens / three-quarter / profile /
   from-behind. "Body angled toward the window" is ambiguous between her face and
   the back of her head, and that ambiguity is what produced the wrong-facing
   shot Ryan caught by eye.

**L6 — IDENTITY ONCE.** Appearance is stated once, at the top, as a short locked
tag. Never repeat wardrobe descriptions per panel: long re-descriptions provably
fight the cast reference images, and they consume the word budget that camera
facts need. References own *what things look like*; prose owns *where the camera
is and what fills the frame*.

**L7 — ESTABLISH BEFORE USE.** Anything a character touches, uses, or passes
through must be visible in that location's establishing wide *before* the panel
that uses it, and must be authored into the location's SET definition as a
permanent feature — not mentioned only in the panel that needs it. The hatch
Nyla escapes through existed only in the threshold panel, so the wides drew a
seamless sphere and she climbed out of a door that had never existed.

**L8 — SCALE AND ARRIVAL SURFACE.** Establishing an element is not enough; its
scale must establish too. Any opening or object a character passes through states
(a) its size relative to the character ("diameter roughly three-quarters of her
standing height — she climbs through upright with a duck of the head, never a
porthole she would crawl through on her stomach") and (b) how it meets the
surface she arrives on ("sill flush with the catwalk that runs directly outside,
so it opens straight onto that walkway at foot level"). Both facts repeat in the
establishing wides.

**L9 — FRAME-SIDE CONTINUITY ON REPEATED SETUPS.** A repeated setup must name the
same frame side or the same surface it progresses from. "Pressed to the glass"
unqualified made a repeated wide read as the character relocating to a different
pane instead of progressing at the same one. A repeat should feel like editing,
never like teleporting.

**L10 — BODY VECTOR TO VISIBLE AXIS.** A motion panel ties the subject's travel
direction to a visible line *in the same panel*: state that the vanishing line is
visible past a named shoulder, that the set's lines converge on it, and that her
travel runs along it — "her direction of travel and the corridor's vanishing line
must read as the same axis." Specifying drive direction and vanishing point
separately lets the two float free of each other.

**L11 — NESTED FRAMES.** A screen, monitor, window, or mirror inside the set is a
second frame. Specify its content in every panel where it is visible, or the
content drifts panel to panel. (Added for scene 2, whose building-sized screen
shows the warren below.)

**L12 — SPECIFY THE POPULATION.** Background people are part of the set. State
what the crowd, the sleepers, the extras look like, so the hero's contrast is
authored rather than accidental. In scene 2's screen feed the other pod occupants
were unspecified; the model invented pale sleepwear, which made Nyla pop — by
luck. Luck does not repeat across six scenes. Where a hero must stand out, say
what everyone else looks like and say what makes the hero different (the only
dark figure, the only one standing, the only one awake). Also state what the
population does IN DEPTH: how many occupants per container, and that anything
behind the readable front layer falls into shadow — scene 2 rendered bodies
stacked through the transparent pods until each pod looked like it held two
people.

**L13 — COVERAGE AGREES WITH THE WIDE.** Two-character coverage must be
consistent with the seating and spacing the establishing wide establishes. An
over-the-shoulder pair implies the two are adjacent; if the wide then reveals
people sitting between them, the audience feels the contradiction even when it
cannot name it. Either seat them adjacent in the wide, or state the compression
in the setup ("long lens across the row, the intervening figures soft and out of
focus in the foreground"). Ryan caught this in scene 2 panels 4 and 6 against
panel 5.

**L14 — GIVE THE PAIR A TWO-SHOT.** A spatial relationship the audience never
sees stated does not exist, however correct the data is. Before covering a
dialogue pair in singles or over-the-shoulders, include one medium two-shot that
holds BOTH characters in the same frame at the same size, so their adjacency and
spacing are unmistakable. Coverage runs master, then two-shot of the pair, then
singles — skipping the middle rung is why scene 2's corrected seating was
invisible to Ryan even though the wides were fixed: the wide was too wide to read
and the over-the-shoulders compress space by design. Prefer converting a
redundant wide into the two-shot rather than adding a panel.

**L15 — SEPARATE ATTENTION FROM ORIENTATION.** When a character shifts attention
to another character, state what stays FIXED and what MOVES: the chair, hips and
knees stay pointed where the wide established them; only head, shoulders and gaze
turn. Say it as a prohibition too. Scene 2 v3 asked for one speaker "turned
three-quarter toward him" and the model rotated both bodies and both armchairs
into a face-to-face dinner-table configuration — breaking the hall's geography,
since every other panel has the row facing the screen. A partial turn that does
not name its anchor becomes a full re-staging.

**L16 — A REVERSE ANGLE CHANGES THE BACKGROUND.** State what sits behind the
subject for each camera position, and never carry one background across opposing
angles. If the camera stands between the subject and a light source or screen,
that source is BEHIND CAMERA: it appears as light on the subject's face, never as
an object behind them. Scene 2 v4 asked for a camera forward of the row *and* for
the screen to be visible past the far speaker — a geometric impossibility, which
the model resolved by turning the whole room around. When a setup reverses, say
explicitly what is now visible behind the subject and what is now off-frame.

**L17 — LOCK THE HEADCOUNT.** State the number of people in every panel where a
group appears, as a number, and forbid drift ("exactly five, never four and never
six"). Counts silently drift between panels whenever they are implied by a list
rather than stated as a quantity — scene 2 lost an elite between the wide and the
screen insert.

**L18 — THE UNREMARKED PLANT (the exception to L7).** When the *discovery* of an
object is the story beat, L7's establish-before-use still applies, but emphasis is
forbidden. State that the object is genuinely present and genuinely visible in the
earlier panels, state that it is small and ordinary among its neighbours, and then
forbid every form of emphasis explicitly — no lighting it, no glow, no indicator,
no centring the composition on it, no enlarging it. "Easy to miss on a first look
and unmistakable on a second." From the notice panel onward it must not change
size or position: the shot sizes change, the object never does. Without the ban on
emphasis the model announces the object and kills the reveal; without the plant the
discovery is invented.

**L19 — DIEGETIC CAMERA POV.** When a character looks at a lens, mirror, or camera
that exists inside the story, define a setup that OCCUPIES that object's position,
mark it NEUTRAL (it legally breaks the axis), and state that the character's eyes
go directly into the lens — "square to the lens, eyes directly into camera, no
three-quarter." Then apply L16 to it: from that position the object's own housing
is NOT visible, because the camera is inside it, and what surrounds the subject is
whatever lies on the far side of them. Optionally state the optical signature of
the diegetic device (barrel distortion for a security lens) so the shot reads as
that device's view rather than a stylistic choice.

*(L18 and L19 are derived from craft reasoning while writing scene 3 and are
UNTESTED until that scene's free round is judged.)*

---

## Method (Ryan's rule, 2026-07-29)

Tune prompts with **free tools** — hand-write the prompt, generate it in ChatGPT,
judge it panel by panel, fix the words, repeat — and only then spend on the real
pipeline. Four free rounds took scene 1 from "no exit exists" to 9/9. Move to
harder scenes deliberately to dial in more laws: dialogue axis, nested screens,
crowds, multi-location action.

Every defect found this way is a *law*, not a fix for one scene.

**Keep the best-known-good, and be willing to regress to it.** Ryan's rule during
the scene-2 rounds: "if this gets any worse, we need to regress back to the one
that I said I didn't see the two people together — I would actually call that
good." Every version is saved and committed so a revert is one command, never a
rewrite. Iteration is only progress while each round is better than the last
KNOWN-GOOD version, not merely better than the previous attempt — two of scene
2's later defects were introduced by fixes, so forward motion is not automatically
improvement. When a round regresses, revert and re-approach; do not iterate
forward from a worse state.

## Status

These laws are proven in prose and NOT yet implemented in the planner. The build
lane is D3-66 through D3-70 in `tasks/loop-checklist.md`; the acceptance target is
`tasks/evidence/d3-64-fixes/scene1_board_prompt_CORRECTED_v3.txt` — the planner
should emit that shape on its own. Until then, production boards do not obey
these laws.
