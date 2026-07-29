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

---

## Method (Ryan's rule, 2026-07-29)

Tune prompts with **free tools** — hand-write the prompt, generate it in ChatGPT,
judge it panel by panel, fix the words, repeat — and only then spend on the real
pipeline. Four free rounds took scene 1 from "no exit exists" to 9/9. Move to
harder scenes deliberately to dial in more laws: dialogue axis, nested screens,
crowds, multi-location action.

Every defect found this way is a *law*, not a fix for one scene.

## Status

These laws are proven in prose and NOT yet implemented in the planner. The build
lane is D3-66 through D3-70 in `tasks/loop-checklist.md`; the acceptance target is
`tasks/evidence/d3-64-fixes/scene1_board_prompt_CORRECTED_v3.txt` — the planner
should emit that shape on its own. Until then, production boards do not obey
these laws.
