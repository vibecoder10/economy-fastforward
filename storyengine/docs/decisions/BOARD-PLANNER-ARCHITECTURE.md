# BOARD PLANNER ARCHITECTURE — make the prompt calculated, not invented

Ryan, 2026-07-30: *"why cant this be deterministic and calculated, not invented and
hallucinated. I mean we know which laws we want the prompt to follow and it just
ignores things and does its own thing."*

It can be. The current design is backwards, and the day's evidence says so exactly.

## The diagnosis

Today's board prompt is produced like this:

    scene prose --> PLANNER LLM (writes the whole directive as prose)
                --> deterministic composer (light templating)
                --> IMAGE MODEL --> sheet

The planner LLM is asked to write the finished artifact while honouring 29 laws
described to it in a system prompt. It is a writer, so it paraphrases: it keeps the
laws it finds convenient and quietly drops the rest.

**The evidence, from one proof run on 2026-07-30.** Laws that SURVIVED into the
emitted prompt were the ones written by code or enforced by a gate: per-location set
blocks with real prohibitions, stated headcounts, the caption rule, no duplicate
panels. Laws that were PROMPT-ONLY were paraphrased away: pair adjacency and the
two-shot (the emitted prompt seated the speakers "roughly two meters apart" with no
close two-shot), and the population/depth rule (thinned to one line). Meanwhile the
inputs the prompt merely *claimed* went unchecked: it asserted attached cast
references that never reached the call, declared the style twice and contradictorily
("an animated scene" and "Photorealistic, cinematic film still"), and described the
world inconsistently — a warren of "cylindrical" pods containing a "spherical" pod.

Three failure classes, one cause: **we asked a model for the artifact instead of
asking it for facts and building the artifact ourselves.**

## The fix

    scene prose --> PLANNER LLM --> STRUCTURED PLAN (validated JSON, no prose)
                --> DETERMINISTIC RENDERER (canonical data + coverage catalogue + laws)
                --> IMAGE MODEL --> sheet

The LLM never writes a line of the final prompt. It fills a schema. Code renders.

### What the model is for (genuine language understanding)
Reading the scene text and returning, per moment: its order, its LOCATION, its
REGISTER (dialogue / expression / action / insert), a one-line action summary, the
speaker and verbatim line if any, and flags — is this a location change, is this a
discovery beat, is this a duration beat. Plus which moment carries the scene. That is
comprehension, and a model should do it.

### What is calculated, never invented
- **Set blocks, material map, prop manifest** — inserted VERBATIM from one canonical
  per-video set definition (L3, L20). No paraphrase, no per-scene re-description.
- **Style** — one string from the video's own style field, stated once (L29).
- **Cast identity tags** — short tags from the cast records, stated once (L6). And the
  reference images are ATTACHED, or the sentence claiming them is not written (L28).
- **Camera kit** — SELECTED from a coverage catalogue keyed by register and location
  count, not invented. A dialogue pair yields master, MS two-shot, matched OTS pair,
  insert, neutral reverse (L1, L13, L14). An action beat yields travel and exit
  setups (L4). A discovery beat yields wide, low angle, macro insert, and a diegetic
  POV if the object is a lens (L18, L19).
- **Per-panel camera facts** — height, barrier side, frame fraction and face
  visibility are PROPERTIES OF THE CHOSEN SETUP plus the moment's register, so they
  are looked up, not written (L5). Backgrounds follow from camera position (L16).
- **Panel allocation** — how many panels per moment and which setup each uses, by
  rule: establish, develop, insert, payoff; never two adjacent panels on the same
  setup unless the action progresses (L9, L21).
- **Group arrangement per camera** — computed by flipping the seating order for a
  reverse angle instead of asking a model to remember (L22).
- **Boundary blocks** — INCOMING and OUTGOING rendered from the film-level transition
  plan (L23-L26).
- **Constraints slot** — a fixed, complete rendering of every prohibition (L2, L27).

### Why this makes the laws real
A law in a system prompt is a request. A law in a renderer is a fact, and a law in a
schema validator is a wall. Under this design most of the 29 laws stop being
instructions at all — they become properties of the code path, impossible to omit
because nothing is left to omit them. The gates that were dismissed as "semantic and
not deterministically checkable" mostly become checkable, because they now inspect a
structured plan instead of prose: does every moment have a location? does a location
change carry a bridge moment? does a dialogue pair have a two-shot panel? is any
panel identical to another?

### Honest limits
1. **The image model still hallucinates.** A perfectly deterministic prompt can still
   be drawn wrong — today it drew tubes where the text said sphere. This removes one
   whole layer of drift; the board gate and the arbiter catch the rest. Determinism in
   the prompt is not determinism in pixels, and no amount of prompt engineering makes
   it so.
2. **A rigid catalogue risks sameness.** Mitigation: the model chooses among VALID
   options for the register rather than inventing setups, and the catalogue carries
   several patterns per register. Convention is not monotony — it is what makes a cut
   legible.
3. **Some laws remain judgement.** Whether a moment "carries the scene," whether an
   escalation earns itself — those stay with the model or with Ryan. They are also the
   ones where drift matters least.

## Sequence

1. Define the canonical per-video record: cast (with reference asset ids), style, and
   the set/material map per location. This is the item already filed as the headline
   next build; it is a prerequisite for everything else here.
2. Define the structured plan schema and switch the planner call to emit it. Keep the
   old prose path behind a flag until the new one beats it on the same scene.
3. Build the renderer: catalogue, allocation rules, verbatim insertion, constraints.
4. Move the gates onto the structured plan.
5. Prove it the way everything else was proven this week: one scene, one board, judged
   against BOARD-LAWS.md, compared to the hand-written sheet Ryan scored 9/9.
