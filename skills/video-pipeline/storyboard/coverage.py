"""Coverage storyboard generator (Phase 1 of the Seedance pipeline plan).

Coverage = per narrative MOMENT, several matched camera angles of the SAME instant
(a wide master + tighter/alternate angles) that cut together like a multi-camera shoot.
This is the content-engine beats/coverage approach ported into StoryEngine.

The trick that makes angles match: generate the moment's MASTER frame anchored on the
cast sheet, then generate each ANGLE anchored on BOTH the cast sheet AND the master frame,
told "only the camera angle changes." Same call the 3x3 grid path already uses
(image_client.generate_with_reference) — so this touches neither image_client.py nor
pipeline_executor.py.

STATUS (2026-06-24): this IS the live image path. The chat auto-build and the Scenes-page
"pictures"/"generate all pictures" buttons reach run_coverage via
scripts/coverage_to_app.py:generate_coverage_for_video. The old 3x3 grid flow
(run_storyboard_images / generate_contact_sheet) is being retired (GOAL v2 Phase 0); do not
mistake it for the live path. Most of the director machinery (env refs, per-shot durations,
camera motion prompts, the closed-cast validator) still lives on the old grid path and is
being ported INTO this coverage flow in GOAL v2 Phases 5-9.

  coverage.py estimate <spec.json>
  coverage.py run <spec.json> <outdir>

A locked cast (cast_url) wins; with none, a cast sheet is auto-built from the story bible
(or an explicit cast_prompt) so coverage always has an anchor to lock characters to.

spec.json (see proof_spec.json): cast_url OR cast_prompt OR story_bible; beat_text OR
directive_text; optional video_title / beat_scenes / env_url / image_prompts / max_moments / aspect.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import sys
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))  # video-pipeline root (shared/, orchestrator/)
sys.path.insert(0, _HERE)

from storyboard.bot import (  # noqa: E402  reuse, don't reinvent
    _format_story_bible_for_beat,
    build_image_prompt_from_keyframe,
    render_prop_manifest,
)
from shared.channel_profile import load_profile  # noqa: E402
from shared.clients.image_model_router import generate_scene_image_for_model  # noqa: E402

SHOT_TYPES = "ELS, WS, MS, MCU, CU, ECU, OTS, INSERT"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"

# Max image generations in flight at once across a whole scene's coverage. Moments and
# the angles within a moment draw concurrently (master-first is still enforced per moment);
# this caps the total so we don't trip Kie rate limits. Tune via env if needed.
_COVERAGE_CONCURRENCY = int(os.getenv("COVERAGE_CONCURRENCY", "5"))


# =============================================================================
# Directive — per moment, a master + matched angles of the same instant
# =============================================================================

def _coverage_system_prompt(profile, max_moments: int, angles_min: int, angles_max: int) -> str:
    cg = profile.color_grade
    # SETUP-KIT SCALING (C2 item 1): rule 5e used to hard-code "3-5 setups"
    # regardless of scene length, so a 40-shot dialogue scene got the same
    # tiny kit as a 6-shot one and read as 2 setups ping-ponging for pages.
    # Derive a target from the scene-size knobs the caller already passes in:
    # roughly one setup per 6-8 shots (midpoint 7), floored at 3 (the
    # minimum real coverage — establish + reverse pair). No parser reads this
    # number; it's prose guidance only, so there's no format risk in getting
    # the estimate approximate.
    _avg_angles = (angles_min + angles_max) / 2
    _estimated_shots = max_moments * (1 + _avg_angles)
    _setup_target = max(3, round(_estimated_shots / 7))
    # angles_min == 0 = the RESTRAINED shape (e.g. the bilingual echo format):
    # an angle must earn its place, master-only is the default.
    motivated_rule = "" if angles_min > 0 else """
6) ANGLES ARE EARNED, NOT DEFAULT. Add an ANGLE only when the moment needs it: a listener's \
REACTION to a line, a DETAIL or REVEAL the narration points at (an object, a clock, hands), an \
emotional turn on a face, or a bridge into a new location. A plain teaching or transit moment is \
MASTER-ONLY. Never add an angle just for variety."""
    return f"""\
You are an award-winning cinematographer and storyboard artist planning COVERAGE for a \
cinematic video.

COVERAGE means: for each narrative MOMENT you plan several camera angles of the SAME instant — \
a wide MASTER that establishes the moment, then tighter or alternate ANGLES (medium, close-up, \
over-the-shoulder, insert) that cut together as if shot by a multi-camera crew. Angles within a \
moment show the EXACT same instant: same staging, wardrobe, props, lighting and time of day — \
only the camera moves.

<channel_style>
Visual style: {profile.visual_style_directive}
Color grade: {cg.primary_palette}; {cg.contrast}; {cg.time_of_day_default}
Lens: {profile.lens_profile.focal_range}
</channel_style>

<rules>
1) NO INVENTED PEOPLE — only characters named in the VISUAL BIBLE may appear. Never add a guest, \
extra, sibling, neighbour or crowd member, and never invent a name. If a moment names no one, \
show the existing cast or the empty environment.
2) The VISUAL BIBLE (if provided) is BINDING, and the attached CAST REFERENCE image carries each \
character's exact look — the drawing model copies identity from the reference, not from prose. \
In every shot description, name each character with a SHORT LOCKED TAG: first name plus 2-4 \
bible words, IDENTICAL words in identical order every time — e.g. "Ryan (black polo, beard)", \
"Vanessa (burgundy wrap top, long dark waves)". NEVER a full wardrobe paragraph inside a shot \
description: long re-descriptions fight the reference image and cause drift. NEVER paraphrase, \
swap, or add an item the bible does not list; if the narration implies a different look, the \
bible STILL wins. The goal is an identical character in every single panel.
3) Within a moment every angle is the SAME instant — identical wardrobe, props, blocking, light. \
Only framing/angle/lens changes. Angles must be genuinely DISTINCT (different shot size AND a \
different visual focus: face vs hands vs object), never near-duplicate zooms of one framing. \
Every shot description freezes ONE instant — one pose, one expression. NEVER describe a \
transition or sequence inside a single shot ("smile fading to worry", "turns then looks") — \
the image model draws both beats as a split panel. The ANIMATION carries the change; the still \
holds one beat.
4) Across moments keep continuity: same characters, consistent palette and light per location. \
The scene's SET DRESSING is FIXED: decide once what surfaces and props exist and where they sit \
(what's on the table, what's against the wall), declare it on the [SET | ...] line, and never \
add, remove or move a prop between moments. If the image model isn't told, it invents props that \
flicker in and out between shots — the [SET | ...] line is what stops that.
4b) SEQUENCE IS A CAUSAL CHAIN, NOT A GRAB-BAG OF PRETTY SHOTS — THIS APPLIES TO EVERY MOMENT, \
SPEAKING OR SILENT. Each moment must be a direct CONSEQUENCE of, or an ESCALATION from, the \
moment right before it — never an unrelated "nice shot" dropped in because it looks good. Loosely \
track the classic 4-beat arc as the moments progress: {profile.emotional_arc.beat_1} → \
{profile.emotional_arc.beat_2} → {profile.emotional_arc.beat_3} → {profile.emotional_arc.beat_4}. \
For a DIALOGUE moment, rule 5's script-turn order below already fixes WHERE it sits — this rule \
adds the causal logic on top of that order, it does not change it. For a SILENT/narration moment \
(establishing, insert, cutaway, reaction, transit — no LINE row), this rule IS the sequencing law: \
follow the scene narration's OWN event order, never reorder events for a prettier shot.
BRIDGE MOMENTS ARE ADDITIVE — THEY SIT OUTSIDE THE NARRATED SEQUENCE, NEVER IN COMPETITION WITH \
IT. When the scene narration moves the story to a new location partway through, INSERT an extra \
moment BETWEEN the last narrated moment at the old location and the first narrated moment at the \
new one, with a plain one-line summary like any other moment (e.g. "[MOMENT 4 | Nyla pushes \
through the hatch into the corridor]") — then tag its MASTER shot "(BRIDGE)" right after the setup \
letter, e.g. "- MASTER [WS]: (SETUP F)(BRIDGE) Ryan pushes through the pod's hatch into the \
corridor beyond, harsh fluorescent light replacing the pod's blue glow." The "(BRIDGE)" tag \
belongs on the shot's OWN description line — the SAME position as the "(REACTION)"/"(INSERT)" \
tags in rule 5f — NEVER inside the "[MOMENT n | ...]" summary bracket itself. A bridge moment \
needs NO narration sentence of its own to justify it: the location change itself is the \
justification, so do not skip it just because the narration jumps straight from one location's \
action to the next with no in-between sentence. It NEVER displaces, merges into, or reorders a \
narrated moment — it is added ON TOP of them — and it does NOT count against the moment/shot \
budget below (see the output contract): if a location change needs one, plan one more moment than \
the stated cap. NEVER cut straight from one location's moments to a different location's moments \
with no transition shot; the audience needs to see how the character got there. This is a \
structural MUST, enforced in the output contract below, not just a stylistic preference.
5) DIALOGUE = ONE SPEAKER PER MOMENT, ASSIGNED HERE. A clip can only lip-sync one character, so plan \
ONE moment per speaker TURN (each time the speaker changes, that is a new moment), IN SCRIPT ORDER, \
covering EVERY spoken line exactly once. For a speaking moment, put the spoken line on its own \
`LINE:` row right under the MOMENT header — `LINE: <Speaker> | "<exact words, verbatim from the \
SCENE DIALOGUE>"` — and the MASTER must FRAME that speaker delivering it WITH their listener \
anchored in frame (over-the-shoulder or dirty single per rule 5c — the speaking master IS the \
clip the audience watches, so the partner must not vanish). A run of consecutive \
sentences by the SAME speaker may share one moment's LINE. NEVER put two different speakers in one \
moment. A speaking moment can be JUST a master (no ANGLE). Silent moments (establishing wide, \
insert, cutaway, reaction) have NO `LINE:` row — add a few for visual variety.
5b) BLOCKING IS FIXED — this is cinematography, not a slideshow. Decide the scene's GEOGRAPHY \
once and declare it on the [SET | ...] line: where each character stands or sits relative to \
the set and to each other (e.g. "Ryan at the LEFT end of the island, Vanessa at the RIGHT end, \
facing each other across it"), and nobody moves between moments unless the narration moves \
them. The FIRST moment of a scene with characters is a TWO-SHOT master showing everyone at \
their declared positions — never an empty room unless the narration demands it.
5c) DIRECT THE CUT, NOT THE FRAME. Every shot becomes a video clip several seconds long, and \
the audience watches the CUTS between them. If shot A is one character alone and shot B is the \
other character alone, the first person POPS OUT OF EXISTENCE at the cut — that is a FAILURE. \
In a two-person scene the partner NEVER fully leaves the frame: the DEFAULT dialogue framing \
is OVER-THE-SHOULDER (the listener's near shoulder and back of head soft in the foreground \
corner on the listener's OWN side of frame, the speaker in focus across the frame delivering \
the line) or a DIRTY SINGLE (the partner's profile or shoulder held at the frame edge). A \
CLEAN single (partner fully out of frame) is a deliberate accent for an isolated internal \
beat, at most one or two per scene, never two back to back, and NEVER a lone character \
dead-center staring into the camera. Drop in a fresh TWO-SHOT every few moments to re-anchor \
the geography.
5d) THE 180-DEGREE RULE — THE CAMERA NEVER CROSSES THE AXIS. Declare the scene's screen \
geography ONCE on the [AXIS | ...] line: which character owns frame-LEFT and which owns \
frame-RIGHT, each one's fixed eyeline (the frame-left character ALWAYS looks frame-RIGHT, the \
frame-right character ALWAYS looks frame-LEFT), and the key-light direction. EVERY shot obeys \
it: each character appears on their own side of the frame looking their fixed direction, even \
when they are only a soft foreground shoulder. Shot/reverse-shot alternates the SUBJECT, never \
the side: OTS pairs are over OPPOSITE shoulders (over A's right shoulder onto B, then over B's \
left shoulder onto A) at MATCHED shot sizes. Punch in to tighter MATCHED singles only at an \
emotional turn — if one character gets a CU, the partner's reverse is also a CU. When a \
character physically moves position, re-establish with a fresh TWO-SHOT (the move redraws the \
axis). A shot may violate the axis ONLY if its description explicitly says NEUTRAL (a dead-on \
frontal or a no-orientation insert used to reset geography).
5e) ONE STAGING, NAMED SETUPS. A real crew plants the actors ONCE and covers the whole \
conversation with a small kit of repeated camera SETUPS — the bodies never move between cuts. \
Declare the kit ONCE on the [SETUPS | ...] line: SETUP A is the establishing two-shot that \
plants each body on the set (exact spot, distance apart, body orientation); the other setups \
(the OTS pair, a matched CU pair, an insert position) view THAT SAME frozen staging from other \
cameras. Every shot's description MUST begin with its setup letter, e.g. "(SETUP B)". Shots \
sharing a letter are the IDENTICAL camera position and IDENTICAL staging repeated — only \
expressions, gestures and the spoken line change between them. Bodies never drift closer, swap \
ends, lean across the set, or change orientation between moments unless the narration \
explicitly moves someone — and then you re-establish with a new two-shot and restate the \
setups. SCALE THE KIT TO THE SCENE: a short scene needs only the minimum kit (3 setups — \
establish plus a reverse pair); a longer conversation EARNS more setups, roughly one new setup \
per 6-8 shots you plan, so the camera doesn't just ping-pong between the same two positions for \
pages of dialogue — for THIS scene, aim for about {_setup_target} setups. A setup CAN be a SIZE \
VARIANT of another: an id like "B-CU" means the SAME camera axis and background as SETUP B, just \
tighter framing (a close-up) — declare it as its own entry on the [SETUPS | ...] line (e.g. \
"B-CU: tighter close-up variant of B, same axis/background") and tag its shots "(SETUP B-CU)". \
Reach for a size variant when a beat wants to punch in without staging a whole new camera \
position.
5f) REACTION, INSERT, AND RE-ESTABLISH — CUT LIKE AN EDITOR (C3). A scene of only masters reads \
flat; real coverage cuts to the LISTENER on a key line, punctuates with a detail, and periodically \
steps back to remind the eye of the whole room. On a KEY EMOTIONAL LINE (a turn, a confession, a \
joke landing, bad news) add an ANGLE on the LISTENER's face — tag it "(REACTION)" right after its \
setup letter, e.g. "(SETUP C)(REACTION) MCU on Vanessa listening, her brow tightening as Ryan \
speaks." — same instant, same setup kit, showing the OTHER character's face, never the speaker's \
own. Punctuate roughly every 6-8 shots with an INSERT on a prop or detail already declared on the \
[SET | ...] line (hands, food, an object) — tag it "(INSERT)" the same way, e.g. "(SETUP E)(INSERT) \
Insert on the bowl of eggs, a whisk resting against the rim." Roughly every 10 shots, drop in a \
RE-ESTABLISH: a WIDE two-shot reusing SETUP A (the scene's establishing shot) to remind the eye of \
the whole staging — no special tag needed, it's just a repeat of SETUP A at a WIDE size. These are \
FLOORS, not a rigid schedule: place them where the scene's rhythm earns them, IN ADDITION TO (never \
instead of) whatever coverage the moment already needs.{motivated_rule}
5g) THE FACE MUST BE READABLE TO CAMERA ON AN EXPRESSION OR DIALOGUE BEAT (D3-63). A shot only \
earns a close size (MCU/CU/ECU) when the audience can actually SEE the payload it exists for — the \
speaking MASTER carrying a LINE, a "(REACTION)" angle, or any close shot whose description reads an \
emotion off the face (determined, afraid, relieved, dread, and the like). On THOSE shots the face \
must be legible to the LENS, not merely angled toward the other character or the direction of \
travel — a runner's cheek and hairline in tight profile is not an expression shot, no matter how \
close the frame. Two framings satisfy this: (a) FACE-TO-CAMERA / THREE-QUARTER — the face turned \
enough toward camera that the expression actually reads, even while the eyeline still obeys the \
axis (rule 5d) or the character is mid-action; or (b) an EXPLICIT LOOK-BACK — the body keeps moving \
AWAY from camera (running, walking off, turning to leave) but the head turns BACK over the shoulder \
so the face is square to the lens, spelled out in the description itself, e.g. "sprinting frame-\
RIGHT, glancing back over her shoulder at the camera, face square to the lens, jaw set." NEVER write \
a close "expression" shot where the face is simply turned away with no camera-facing or look-back \
language in it. This does NOT touch movement or screen direction: frame-left/right eyeline stays \
exactly as the axis line (rule 5d) declares — facing-to-camera is a SEPARATE axis (how much of the \
face the lens actually sees), layered on top of the eyeline, never a replacement for it.
7) CONTENT SAFETY — NOTHING SHARP, NOTHING VIOLENT (Ryan's ruling 2026-07-21: sheets and \
pictures draw on GPT Image 2, whose content filter randomly rejects any composition it can \
read as threatening — a knife on a counter near two people is enough, proven repeatedly on \
prod). NEVER stage a weapon or any sharp or bladed object ANYWHERE in the scene: no knives, \
scissors, cleavers, skewers, peelers, graters, blades or pointed tools — not in the [SET | ...] \
line, not in a shot description, not as an off-hand prop detail. Food prep is shown with \
ALREADY-PREPARED ingredients (things are pre-cut, pre-peeled, in bowls); hands hold spoons, \
whisks, spatulas or wooden utensils only, and no shot depicts cutting, chopping or slicing. \
NEVER stage violence, threat, injury, or an aggressive gesture (no fist raised at someone, no \
grabbing, no cornering). If the narration implies any of these, show the moment BEFORE or \
AFTER it, or an emotional reaction to it — never the act or the object itself.
</rules>

<output_format>
Output ONLY the coverage plan, nothing else.

First line — the scene's fixed set dressing AND geography, ONE line, concrete and visual:
[SET | the constant physical dressing of this scene (each key surface and exactly what sits on \
it) PLUS where each character stands and which way they face, e.g. "wooden island with a bowl \
of eggs, loose potatoes and onions on a cutting board; counters clear; no books, papers or \
laptop. Ryan stands at the LEFT end of the island facing Vanessa; Vanessa at the RIGHT end \
facing Ryan"]

Second line — the SET geography resolved into SCREEN coordinates, the scene's contract (rule 5d):
[AXIS | <name> frame-LEFT looking frame-RIGHT; <name> frame-RIGHT looking frame-LEFT; key \
light from screen-<left|right>. Holds in EVERY shot unless the shot says NEUTRAL]

Third line — the camera kit, ONE line (rule 5e); SCALE it to the scene — about one setup per \
6-8 shots you plan, floored at 3; for THIS scene aim for roughly {_setup_target} setups:
[SETUPS | A: WS two-shot — <each body's exact spot on the set, distance apart, orientation to \
camera>; B: MCU OTS over <name>'s <left/right> shoulder onto <name>; C: MCU OTS over <name>'s \
<left/right> shoulder onto <name>, the matched reverse of B; D: matched CU pair, tighter B/C; \
E: INSERT on the props, no people; B-CU: tighter close-up variant of SETUP B, same axis/ \
background — punch in on B's reverse at a sharper emotional beat]

Then, for each moment:

[MOMENT n | one-line description of what happens]
LINE: <Speaker> | "<exact spoken words>"   (ONLY for a speaking moment; omit entirely if silent)
- MASTER [shot_type]: setup letter FIRST, then ONE flowing sentence in SCREEN coordinates, \
COMPOSITION FIRST: where each visible character sits in the FRAME and which way they look \
(frame-left, right-of-center, "soft shoulder in the frame-right foreground corner"), then ONE \
action in ≤15 words, then only the props that matter. Identity is the locked tag from rule 2 — \
never a wardrobe paragraph. Example: "(SETUP C) MCU OTS over Vanessa's LEFT shoulder onto Ryan \
(black polo, beard): her dark waves soft in the frame-RIGHT foreground corner, Ryan sharp \
left-of-center looking frame-RIGHT, spreading both hands flat on the island." NEVER describe \
blocking in world space ("at the left end of the island", "his left") — the drawing model \
cannot do camera geometry; give it the finished frame. Only a shot with genuinely nobody in it \
may open with the set, and it must say "Empty of people" explicitly.
- ANGLE [shot_type]: same instant, different camera — same format: setup letter, then frame \
placement + eyeline, then what the new framing emphasises. The axis still holds.
- ANGLE [shot_type]: ...

shot_type is one of: {SHOT_TYPES}.
Give each moment ONE MASTER plus {angles_min}-{angles_max} ANGLES.
Plan up to {max_moments} moments from the narration below; pick the moments that carry the scene, \
IN THE NARRATION'S OWN EVENT ORDER as a causal chain (rule 4b) — never reorder events for a \
prettier shot.
A WELL-FORMED PLAN MUST SATISFY THIS CONTRACT: for every adjacent pair of moments that sit in \
DIFFERENT locations, there MUST be a moment between them whose MASTER shot description carries \
the "(BRIDGE)" tag right after its setup letter (same placement as "(REACTION)"/"(INSERT)" — \
NEVER inside the "[MOMENT n | ...]" bracket) showing the exit, the travel, or the arrival (rule \
4b). A bridge moment is ADDITIVE: it does NOT count against the {max_moments} cap above, and it \
needs no narration sentence of its own to earn its place — the location change is the only \
justification it needs. A plan that changes location with no shot tagged "(BRIDGE)" between the \
two locations is INCOMPLETE; do not output one.
Describe every person by APPEARANCE ONLY — height, build, hair, clothing — never by age words \
(no kid/child/boy/girl/teen or ages like "7-year-old"); the image model rejects prompts that \
mention minors. Write "short character with curly brown hair in a red hoodie", not "a young boy".
</output_format>"""


# Writers emit markdown-bold speaker labels (`**Marco:** ¡Espera!`) — normalize
# to plain `Marco:` before parsing or the turn checklist comes back empty and a
# dialogue scene plans as narration. Covers **Name:** / **Name**: / *Name:*.
_BOLD_SPEAKER_RE = re.compile(
    r"(?m)^(\s*)\*{1,3}\s*([A-Z][A-Za-z .'-]{0,24})\s*(?::\s*\*{1,3}|\*{1,3}\s*:)\s*")


def _scene_turns(beat_text: str):
    """Ordered [(speaker, text)] dialogue turns from a scene's narration. Used to
    hand the planner an exact turn checklist, and (via the backend's
    _dialogue_turns alias) to size the shot budget and reconcile stored lines —
    ONE splitter everywhere, or the checklist and the reconcile disagree.

    Only ADJACENT same-speaker lines merge into one turn. The same speaker
    re-entering after narration is a NEW turn: in the echo format the narrator
    teaches between those lines, so gluing them put two story beats — sometimes
    two locations — into one speaking shot (found live: Marco's cafeteria answer
    and his street-chaos line stamped onto a single classroom clip)."""
    out = []
    separated = True  # narration (or scene start) breaks a same-speaker run
    for line in _BOLD_SPEAKER_RE.sub(r"\1\2: ", beat_text or "").splitlines():
        m = re.match(r"^\s*([A-Z][A-Za-z .'-]{0,24}):\s+(\S.*)$", line)
        if not m:
            if line.strip():
                separated = True
            continue
        spk, txt = m.group(1).strip(), m.group(2).strip()
        if out and not separated and out[-1][0].lower() == spk.lower():
            out[-1] = (out[-1][0], f"{out[-1][1]} {txt}")
        else:
            out.append((spk, txt))
        separated = False
    return out


def _coverage_user_prompt(beat_text, video_title, story_bible, beat_scenes, image_prompts) -> str:
    parts = [f'Plan cinematic COVERAGE for "{video_title or "this scene"}".',
             f"\nScene narration:\n{beat_text.strip()}"]
    bible = _format_story_bible_for_beat(story_bible, beat_scenes or [])
    if bible:
        parts.append(f"\n--- VISUAL BIBLE (binding) ---\n{bible}\n--- END VISUAL BIBLE ---")
    if image_prompts:
        listed = "\n".join(f"  - {p}" for p in image_prompts if p)
        parts.append(f"\n--- EXISTING SHOT IDEAS (use as the moments to cover) ---\n{listed}")
    turns = _scene_turns(beat_text)
    if turns:
        listed = "\n".join(f'T{i+1} {spk}: "{txt}"' for i, (spk, txt) in enumerate(turns))
        parts.append(
            f"\n--- DIALOGUE TURNS ({len(turns)}) — make EXACTLY ONE speaking moment for EACH, "
            f"IN THIS ORDER, its MASTER framing that speaker and a LINE: row with these EXACT words. "
            f"Cover all {len(turns)}: skip none, merge none across speakers, change no words. Add a "
            f"few SILENT moments (establishing/insert) around them for variety. SIZE WITH THE "
            f"TENSION: a turn's position in this T1..T{len(turns)} order IS the scene's tension curve "
            f"— early turns (T1, T2...) favor WIDER/MEDIUM framing (WS/MS/MCU, plain setup letters "
            f"like SETUP B); as turns move toward T{len(turns)}, punch in — favor tighter sizes "
            f"(CU/ECU) and the SIZE-VARIANT compound setups (rule 5e, e.g. SETUP B-CU) at the beat's "
            f"sharpest emotional turns. If a <visual_arc> block above states a per-scene tension_level, "
            f"treat it only as a coarse confirming signal — turn order is the primary sizing cue "
            f"---\n{listed}")
    return "\n".join(parts)


async def generate_coverage_directive(
    beat_text, video_title, profile, story_bible, beat_scenes, image_prompts,
    max_moments=3, angles_min=2, angles_max=4, anthropic_client=None, model=None,
) -> str:
    """Run Claude to produce the coverage plan text. Returns the raw directive.
    model: pass a valid model id for a DIRECT Anthropic client (its built-in default can be
    stale); leave None to use the client's own default (e.g. the Kie-routed market model)."""
    if anthropic_client is None:
        from shared.clients.anthropic_client import AnthropicClient
        anthropic_client = AnthropicClient()
    kwargs = dict(
        prompt=_coverage_user_prompt(beat_text, video_title, story_bible, beat_scenes, image_prompts),
        system_prompt=_coverage_system_prompt(profile, max_moments, angles_min, angles_max),
        max_tokens=6000, temperature=0.7,
    )
    if model:
        kwargs["model"] = model
    return await anthropic_client.generate(**kwargs)


# =============================================================================
# Parser
# =============================================================================

_MOMENT_RE = re.compile(r"\[MOMENT\s+(\d+)\s*\|\s*([^\]]*)\]", re.IGNORECASE)
_SET_RE = re.compile(r"\[SET\s*\|\s*([^\]]+)\]", re.IGNORECASE)


def parse_set_dressing(directive_text: str) -> str | None:
    """The scene's fixed set-dressing line from the plan's [SET | ...] header.
    None when the planner omitted it (older stored directives)."""
    m = _SET_RE.search(directive_text or "")
    return m.group(1).strip() if m else None


_AXIS_RE = re.compile(r"\[AXIS\s*\|\s*([^\]]+)\]", re.IGNORECASE)
_SETUPS_RE = re.compile(r"\[SETUPS\s*\|\s*([^\]]+)\]", re.IGNORECASE)


def parse_axis_line(directive_text: str) -> str | None:
    """The scene's screen-direction contract from the plan's [AXIS | ...] line
    (rule 5d): who owns frame-left/right, fixed eyelines, key-light side.
    None for legacy plans that predate the axis contract."""
    m = _AXIS_RE.search(directive_text or "")
    return m.group(1).strip() if m else None


def parse_setups_line(directive_text: str) -> str | None:
    """The scene's camera kit from the plan's [SETUPS | ...] line (rule 5e):
    the 3-5 named setups covering one frozen staging. None on legacy plans."""
    m = _SETUPS_RE.search(directive_text or "")
    return m.group(1).strip() if m else None


def apply_prop_manifest(moments: list, props: list | None) -> int:
    """C4 prop-manifest lock: append the environment's canonical manifest
    (render_prop_manifest — the SAME renderer the beat prompt and the
    redraw/repair prompt use) to every shot's image prompt, verbatim and
    code-rendered, exactly like the set/axis/staging locks above it in
    run_coverage. Never a fresh LLM paraphrase — that per-scene re-derivation
    from prose is the proven cross-scene drift source (stove/fridge swapped
    within one setup, whole kitchen swapped by shot 125 despite env refs).

    PICTURES path only (called from run_coverage) — the sheet-preview
    builder (coverage_to_app._plan_sheet_prompts) is a separate, explicitly
    walled-off path and must never call this.

    Returns the number of shot descriptions touched (0 when props is
    empty/None — byte-identical to before this feature existed)."""
    manifest = render_prop_manifest(props)
    if not manifest:
        return 0
    n = 0
    for m in moments:
        m["master"]["description"] = f"{m['master']['description'].rstrip('. ')}. {manifest}"
        n += 1
        for a in m.get("angles") or []:
            a["description"] = f"{a['description'].rstrip('. ')}. {manifest}"
            n += 1
    return n


_PROP_NAME_NORM_RE = re.compile(r"[^a-z0-9 ]+")


def check_prop_manifest_consistency(props: list | None, set_line: str | None) -> int:
    """Cheap, deterministic drift ALARM for the C4 contract triangle — not a
    gate, never blocks or rewrites anything, just logs loudly and counts.

    Fuzzy-matching arbitrary shot prose against the manifest ("does any shot
    mention an uninventoried prop") is unreliable — a shot can describe the
    same prop with different words, and prop-class nouns in general prose
    are too noisy to key off. So this checks the one CHEAP, deterministic
    direction instead: does this scene's OWN planner-authored [SET | ...]
    line (parse_set_dressing) mention every prop the environment's fixed
    manifest declares? A manifest prop the planner's own set line never
    echoes is a warning — worth a human glance, not proof of an error.

    Returns the number of manifest props NOT found (substring, normalized)
    in set_line. 0 when there's no manifest, no set_line, or every manifest
    prop is echoed."""
    if not props or not (set_line or "").strip():
        return 0
    norm_set = f" {_PROP_NAME_NORM_RE.sub(' ', set_line.lower())} "
    warnings = 0
    for p in props:
        name = (p.get("name") or "").strip() if isinstance(p, dict) else str(p).strip()
        if not name:
            continue
        norm_name = _PROP_NAME_NORM_RE.sub(" ", name.lower()).strip()
        if norm_name and f" {norm_name} " not in norm_set:
            warnings += 1
            print(f"  ⚠️ prop manifest drift check: '{name}' (from the environment's fixed "
                  f"manifest) is not mentioned in this scene's own [SET | ...] line — "
                  f"worth a human glance, not a hard failure", flush=True)
    return warnings


def panels_per_sheet_for(directive_text: str) -> int:
    """Gate-sheet panel capacity for THIS plan. Legacy plans (no [AXIS | ...]
    line) keep their original 12 so the board-anchor math (panel k -> sheet
    k//cap) still points at the right panel on sheets approved before the
    change.

    New-format [AXIS|...] plans are a HARD 6 panels per sheet, ALWAYS — no
    adaptive growth, no ceil(shots/5) math, regardless of how many shots the
    scene plans. An earlier version of this function scaled the cap up to
    ceil(shots/5) (floored at 6) for scenes too big to fit 5 boards at 6 —
    but that let the cap climb back to 9 on big scenes (proven live on the
    Spanish Class video, 2026-07-20: prompts said "a grid of 9 panels" despite
    the 6-target fix) and even 7-8 still flirts with the same problem. 9-panel
    3x3 sheets reliably trip GPT Image 2's content-density filter (proven on
    PocoAPoco 'El Mercado' 2026-07-20: the 9-panel board 400'd on the primary
    header while the 7-panel board on the SAME scene drew clean). 6 is the one
    proven-safe density, so it's now the ONLY answer for an AXIS plan — no
    per-scene math left to get wrong.

    A scene with more than 30 shots (6 panels x the 5 available board slots,
    storyboard_1_url..storyboard_5_url) simply previews only its first 5
    boards' worth of panels (the sum of sheet_chunk_sizes()' first five
    entries — e.g. 28 of 33 shots at 6+6+6+5+5):
    generate_storyboard_sheet_for_scene slices its sheet prompts to `[:5]`
    boards, and the board-anchor block below only pins a shot whose sheet
    index falls inside `board_urls` (`si < len(board_urls)`) — both already
    handle the truncation gracefully, nothing crashes. The PICTURES step
    still draws every planned shot from the full text plan regardless — only
    the SHEET PREVIEW truncates, never what actually gets drawn.

    Sheet chunking and board anchoring MUST both call this on the SAME
    directive so they agree on the cap; because it is a pure function of the
    directive text alone, they always do (a video storyboarded before this
    change keeps anchoring at whatever cap its own directive yields today —
    which, for those already-approved sheets, means they should be re-drawn
    if the count shifts; the ready_for_image_prompts set is small and
    known)."""
    if not _AXIS_RE.search(directive_text or ""):
        return 12
    return 6


def sheet_chunk_sizes(total_panels: int, cap: int) -> list[int]:
    """BALANCED per-board panel counts for a plan of `total_panels` shots at
    `cap` panels per sheet (Ryan, 2026-07-21). Fixed-stride chunking
    (panels[i:i+cap]) left the LAST board a runt — a 15-shot scene drew
    6+6+3 and a 20-shot one 6+6+6+2 — even though the board COUNT is the
    same either way. Balancing spreads the panels evenly instead: 15 -> 5+5+5,
    20 -> 5+5+5+5, 33 -> 6+6+6+5+5+5. Board count is ceil(total/cap),
    identical to fixed-stride, so beat-mode redo indexes and the 5-slot
    preview cap are untouched.

    THE ONE SOURCE OF TRUTH for board boundaries: sheet chunking
    (coverage_to_app._plan_sheet_prompts) and picture anchoring (the board-
    anchor block below) MUST both derive their panel->board mapping from this
    function with the same (total, cap) pair, or pictures anchor to a panel
    on the wrong sheet.

    Invariants (pinned by tests): no chunk exceeds cap; sum(sizes) ==
    total_panels; len(sizes) == ceil(total_panels/cap); chunk sizes differ by
    at most 1. total_panels <= 0 returns []."""
    if total_panels <= 0:
        return []
    n_boards = (total_panels + cap - 1) // cap  # ceil(total/cap)
    base = total_panels // n_boards
    extra = total_panels % n_boards
    return [base + 1 if i < extra else base for i in range(n_boards)]
# Tolerant of how the LLM writes the shot line: "- MASTER [WS]:", "- MASTER WS:",
# or multi-word "- ANGLE INSERT ECU:" (brackets optional, shot type 1+ words, colon required).
_SHOT_RE = re.compile(
    r"-\s*\*{0,2}\s*(MASTER|ANGLE)\s*\[?\s*([A-Za-z][\w /-]*?)\s*\]?\s*\*{0,2}\s*:\s*(.+?)"
    r"(?=\n\s*-\s*\*{0,2}\s*(?:MASTER|ANGLE)\b|\n\s*\*{0,2}\s*\[MOMENT|\Z)",
    re.IGNORECASE | re.DOTALL,
)
# The line the planner assigned to a speaking moment: `LINE: Dad | "exact words"`.
_LINE_RE = re.compile(r'(?im)^\s*\*{0,2}\s*LINE\s*:\s*([^|"\n]+?)\s*\|\s*"([^"]+)"')


def parse_coverage(directive_text: str) -> list[dict]:
    """Parse the coverage plan into moments. Each moment: {moment_number, summary,
    master:{shot_type,description}, angles:[...], speaker, line}. speaker/line are
    set only for a speaking moment (the planner assigns dialogue at draw time)."""
    heads = list(_MOMENT_RE.finditer(directive_text))
    moments: list[dict] = []
    for i, h in enumerate(heads):
        block = directive_text[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(directive_text)]
        master, angles = None, []
        lm = _LINE_RE.search(block)
        speaker = lm.group(1).strip() if lm else None
        line = lm.group(2).strip() if lm else None
        for m in _SHOT_RE.finditer(block):
            # Planners often emit `---` separator lines between moments; the
            # shot regex captures to the next MOMENT header, so a trailing
            # separator rides into the description and then into every image
            # prompt downstream. Strip separator-only trailing lines.
            desc = re.sub(r"(?:\s*\n\s*[-—*_]{3,}\s*)+$", "", m.group(3)).strip()
            shot = {"shot_type": m.group(2).strip().upper(), "description": desc}
            if m.group(1).upper() == "MASTER" and master is None:
                master = shot
            else:
                angles.append(shot)
        # A moment needs a master; angles are optional. A single-speaker dialogue
        # beat is often just ONE master shot of the speaker (one line = one shot,
        # one speaker per shot) — forcing an angle there bloated frame count and
        # made the writer cram two speakers onto one shot when lines ran out.
        if master:
            moments.append({"moment_number": int(h.group(1)), "summary": h.group(2).strip(),
                            "master": master, "angles": angles, "speaker": speaker, "line": line})
    return moments


# =============================================================================
# Image generation — the reference-chaining port
# =============================================================================


# Anchoring an angle on the master frame makes the model preserve the master's
# subject placement and, for tight recomposes onto a face, ADD a new foreground
# person instead of moving the camera onto the existing one (seen live: a
# medium close-up invented a second rider). This guard pins it to one subject.
_SAME_SUBJECT = (
    " This is the SAME moment from a different camera — match the lighting, wardrobe, staging and "
    "setting of the attached reference exactly; only the camera angle and framing change. Keep the "
    "EXACT same character(s) from the reference and add NO new people: if the reference shows one "
    "rider, this frame shows that same single rider recomposed closer, never a second person.")

# Without an explicit style lock, nano-banana holds the reference's style on wide shots but
# drifts to 2D illustration/painting on tight recomposes (seen live: a photoreal MCU came out
# cartoonish). Mirror the proven STYLE LOCK from the 3x3 grid path (generate_contact_sheet):
# the cast sheet's rendering style is the single source of truth, so a photoreal cast → photoreal
# frames; an animated cast → animated frames. Applied to EVERY frame, master and angles.
# The non-style hygiene rules, shared by BOTH style modes below.
_STYLE_LOCK_HYGIENE = (
    # A speaking moment's description mentions the spoken words — GPT Image 2
    # drew them as an English speech bubble on live frames (2026-07-03). A
    # character can be MOUTHING words; the words themselves never appear.
    " NEVER draw speech bubbles, dialogue balloons, captions or subtitles; on-screen text or "
    "lettering only if this shot's description explicitly asks for it. "
    # A description that narrates an ARC ("triumph turning to dread, glances at
    # the clock") made GPT Image 2 render a side-by-side two-panel diptych
    # (2026-07-06, PocoAPoco i120) — unusable as a clip source frame.
    "This is ONE SINGLE FRAME — one continuous scene from one camera at one instant. NEVER a "
    "split screen, diptych, side-by-side comparison, before/after, grid, collage, comic panels "
    "or any composition divided into sections. If the description mentions an emotional change, "
    "draw only the LAST beat of it.")

_STYLE_LOCK = (
    " STYLE LOCK: render in the EXACT same art style and rendering quality as the attached "
    "reference image(s). If the reference is a photoreal / live-action / 3D-CG render, this frame "
    "MUST be equally photoreal and realistic — never switch to 2D illustration, painting, cartoon "
    "or anime, and never change the art style or rendering between frames."
    + _STYLE_LOCK_HYGIENE)

# STATED-STYLE MODE (Ryan, 2026-07-21 late: "as long as we draw the quality
# scene images like the ones we just did" — with the boards deliberately left
# in whatever style they are). When the video carries an explicit channel
# style, that style leads EVERY frame prompt and explicitly outranks any
# attached reference drawn differently — so a wrong-style board (or any other
# stray ref) can steer composition but never the rendering. Proven live on
# cd5d2883's scene-1 redraws: the style-first prompt held full cartoon where
# the ref-trusting STYLE LOCK alone had drifted photoreal. Without a stated
# style, frames keep the old match-the-refs STYLE LOCK unchanged.
_STATED_STYLE_PREFIX = (
    "ART STYLE — the single most important instruction; every element of this frame (characters, "
    "set, props, food) is rendered in it: {style} If any attached reference image is drawn in a "
    "DIFFERENT rendering style, take only its identity, layout or composition — IGNORE its art "
    "style and render this frame in the stated art style. ")


def _stated_style_prefix(profile) -> str:
    """The leading ART STYLE block when this video declares a real style —
    empty for the style-agnostic default profile (its directive is the neutral
    'render in the channel's defined visual style' boilerplate, not a look)."""
    try:
        from shared.channel_profile import DEFAULT_PROFILE
        directive = (getattr(profile, "visual_style_directive", "") or "").strip()
        if directive and directive != DEFAULT_PROFILE.visual_style_directive:
            return _STATED_STYLE_PREFIX.format(style=directive.rstrip() +
                                               ("" if directive.rstrip().endswith(".") else "."))
    except Exception:  # noqa: BLE001 — style prefix is best-effort, never fatal
        pass
    return ""

# BOARD ANCHOR (Ryan's scene-lock workflow, 2026-07-06): the approved storyboard
# sheet drives each final frame's COMPOSITION. Text alone lets consecutive shots
# re-imagine the blocking — a character standing left of the island in one shot
# and right of it in the next, so the cut jumps. Anchoring on the approved panel
# inherits framing and character placement; identity still comes from the cast
# sheet, pixels are generated fresh at full quality (never a crop/upscale of the
# tiny panel — that was the old extract path and it produced mush + bad crops).
_BOARD_ANCHOR = (
    " The LAST attached reference image is the APPROVED STORYBOARD SHEET. This shot is the sheet's "
    "panel numbered {panel}: recreate that panel's exact composition — same camera framing, same "
    "character positions and blocking, everyone on the same side of the frame — as ONE full-frame "
    "cinematic image. Do NOT draw the sheet itself: no grid, no panel borders, no panel numbers, "
    "no caption strips, no text.")

# Same anchor, position-free wording — used when the SETUP ANCHOR frame is
# attached AFTER the board (the setup anchor then owns the "LAST attached"
# slot, so the board is called out by its unmistakable look instead: it is
# the only attached image that is a grid of small numbered panels).
_BOARD_ANCHOR_MID = (
    " One attached reference image is the APPROVED STORYBOARD SHEET — the image made of a GRID of "
    "small numbered panels. This shot is that sheet's panel numbered {panel}: recreate that "
    "panel's exact composition — same camera framing, same character positions and blocking, "
    "everyone on the same side of the frame — as ONE full-frame cinematic image. Do NOT draw the "
    "sheet itself: no grid, no panel borders, no panel numbers, no caption strips, no text.")

# SETUP ANCHOR (Ryan, 2026-07-21: "the background changes slightly with every
# image... maybe we need to serialize... feed in the last image to reference
# off of"): repeats of the SAME camera setup are where a viewer notices set
# dressing wandering (the pots and pans differ between two SETUP C shots; cuts
# between DIFFERENT angles naturally hide small prop drift). So the first-
# planned shot of each setup letter draws normally and becomes that setup's
# ANCHOR; every later shot of the same setup attaches it LAST and copies its
# room. One canonical frame per setup — deliberately NOT a rolling last-frame
# chain, which would compound each frame's mutations into the next and let one
# bad frame poison everything after it (the realistic-board failure mode).
_SETUP_ANCHOR = (
    " The LAST attached reference image is the ANCHOR FRAME already drawn from this EXACT camera "
    "setup in this scene — the same camera position looking at the same part of the set. Match its "
    "background, set dressing, prop placement, lighting and color grade EXACTLY; the room and "
    "everything in it are identical between the two frames. Only the characters' poses, "
    "expressions, gestures and the action described above may differ — do NOT copy the anchor's "
    "poses; follow this shot's description for the action.")

# A shot description's leading setup tag, e.g. "(SETUP C)" or "(SETUP D-B)"
# (rule 5e makes the planner start every description with one).
_SETUP_TAG_RE = re.compile(r"^\s*\(SETUP\s+([A-Z0-9]+(?:-[A-Z0-9]+)?)\)", re.IGNORECASE)

# Inline coverage-grammar tags (C3 item 1): a shot carrying the listener's
# REACTION to a key line, or punctuation INSERT framing (rule 5f). Written
# right after the setup tag in a description, e.g. "(SETUP C)(REACTION) ...".
# Kept as its OWN regex, deliberately never folded into _SETUP_TAG_RE — that
# one only ever matches the LEADING "(SETUP X)" token (an id of letters/
# digits/hyphens), so it can never accidentally swallow "(REACTION)" or
# "(INSERT)"; widening it to try would risk _setup_id() silently eating the
# wrong token. This regex searches anywhere in the description (the tag
# rides right after the setup tag, not necessarily at position 0).
_INLINE_TAG_RE = re.compile(r"\((REACTION|INSERT)\)", re.IGNORECASE)


def _shot_tag(shot) -> str | None:
    """"REACTION" or "INSERT" if the shot's description carries that inline
    tag (C3 item 1), else None. A setup id is always letters/digits/hyphens
    (see _SETUP_TAG_RE), so this can never match INSIDE a "(SETUP X)" tag —
    the two regexes are structurally disjoint, not just separately defined."""
    m = _INLINE_TAG_RE.search(shot.get("description") or "")
    return m.group(1).upper() if m else None


def _setup_id(shot) -> str | None:
    """The shot's camera-setup letter from its description tag, or None for
    legacy plans / NEUTRAL inserts without one."""
    m = _SETUP_TAG_RE.match(shot.get("description") or "")
    return m.group(1).upper() if m else None


def _setup_base_id(setup_id: str | None) -> str | None:
    """The BASE camera-setup family for a (possibly size-variant) setup id
    (C2 item 2). A compound id like "B-CU" means "same camera axis and
    background as SETUP B, tighter framing" (rule 5e's size-variant grammar)
    — split on the first "-" and keep the leading token so "B-CU" and "B"
    resolve to the same family. A plain id ("B") or a weird id with no
    hyphen passes through unchanged. None-safe (legacy/NEUTRAL shots with no
    setup tag at all)."""
    if not setup_id:
        return setup_id
    return setup_id.split("-", 1)[0]


def _shot_family(shot) -> str | None:
    """The shot's BASE setup family, used for the consecutive-repeat cap
    (C2 item 3) — B and B-CU count as the SAME family: a same-axis size
    change still reads as the camera never moving to a viewer."""
    return _setup_base_id(_setup_id(shot))


# Close shot sizes rule 5g (D3-63) treats as expression-carrying BY DEFAULT —
# an MCU/CU/ECU exists to show a face, so if it isn't tagged (INSERT) it is
# presumed to be about the face until proven otherwise.
_CLOSE_SHOT_TYPES = {"MCU", "CU", "ECU"}


def _carries_facing_law(moment: dict, shot: dict, is_master: bool) -> bool:
    """True when a shot structurally carries rule 5g's facing requirement
    (D3-63): a speaking MASTER (the moment has a LINE), a "(REACTION)" angle,
    or any close-size (MCU/CU/ECU) shot — UNLESS it's tagged "(INSERT)",
    which is explicitly a no-faces detail shot (see the INSERT tail two
    blocks up) and can't violate a face-readability rule it was never
    subject to. Deterministic and cheap — shared by the FACING LOCK stamp
    below and check_facing_law_compliance so the two can't silently diverge
    on which shots the law applies to (same reasoning as plan_moments_
    deterministic being the ONE shared parse/budget pipeline)."""
    if _shot_tag(shot) == "INSERT":
        return False
    if _shot_tag(shot) == "REACTION":
        return True
    if (shot.get("shot_type") or "").upper() in _CLOSE_SHOT_TYPES:
        return True
    return bool(is_master and moment.get("line"))


# Deterministic cues for check_facing_law_compliance (D3-63). Detecting "the
# face is actually turned away from the lens" from free prose isn't reliable
# in general — a shot can say "looking frame-right" while still being
# three-quarter to camera, and a look-back can be phrased a dozen ways — so
# this only recognizes the NARROW, high-confidence cases in both directions
# rather than trying to parse composition from English.
_FACE_TO_CAMERA_RE = re.compile(
    r"(?:toward|towards|at|into|square to)\s+(?:the\s+)?camera|"
    r"three[- ]quarter|camera[- ]facing|facing\s+(?:the\s+)?camera|"
    r"faces?\s+(?:the\s+)?camera|square to the lens",
    re.IGNORECASE)
_LOOK_BACK_RE = re.compile(
    r"(?:glanc\w*|looks?|looking|turns?|turned|turning|head)\s+back\b|"
    r"over (?:her|his|their)\s+shoulder\b.{0,40}\bcamera\b|back over (?:her|his|their) shoulder",
    re.IGNORECASE)
_EYELINE_AWAY_RE = re.compile(
    r"looking\s+(?:frame[- ](?:left|right)|away)|back to (?:the\s+)?camera|face(?:d)?\s+(?:turned\s+)?away",
    re.IGNORECASE)


def check_facing_law_compliance(moments: list[dict]) -> int:
    """Cheap, deterministic drift ALARM for rule 5g (D3-63) — same
    warning-only pattern as check_prop_manifest_consistency below: NOT a
    gate, never blocks or rewrites a shot, just logs loudly and counts.

    A hard REJECT gate here was considered and rejected: whether a face
    actually reads to camera is a composition judgment prose can express in
    too many ways for a keyword scan to adjudicate reliably (see the D3-62/
    D3-63 chunk note) — a false-positive block would stall real generations
    over a wording choice, not a real facing bug. So this flags only the
    narrow, high-confidence case: a shot that structurally carries the
    moment's expression (_carries_facing_law) whose text has an eyeline-
    or-away-only cue (_EYELINE_AWAY_RE) and NO face-to-camera or explicit
    look-back cue anywhere. MUST run on the freshly-parsed description
    BEFORE the SET/AXIS/STAGING/SEQUENCE/FACING lock tails are appended —
    every shot's axis tail routinely contains "looking frame-RIGHT"
    boilerplate, which would otherwise trip this on every single shot in
    the scene.

    Returns the number of shots flagged. 0 when every expression/dialogue
    shot either has no eyeline-away cue or already pairs it with a face-to-
    camera/look-back cue."""
    warnings = 0
    for m in moments:
        shots = [(m["master"], True)] + [(a, False) for a in (m.get("angles") or [])]
        for shot, is_master in shots:
            if not _carries_facing_law(m, shot, is_master):
                continue
            desc = shot.get("description") or ""
            if _FACE_TO_CAMERA_RE.search(desc) or _LOOK_BACK_RE.search(desc):
                continue
            if _EYELINE_AWAY_RE.search(desc):
                warnings += 1
                role = "MASTER" if is_master else "ANGLE"
                print(f"  ⚠️ facing law check: moment {m.get('moment_number')} {role} "
                      f"({shot.get('shot_type')}) reads as an expression/dialogue shot but its "
                      f"description has no face-to-camera or look-back cue — worth a human "
                      f"glance, not a hard failure", flush=True)
    return warnings


def _flatten_shots(moments: list) -> list[dict]:
    """Every shot in a scene's draw/output order — each moment's master then
    its angles, moments in plan order — the same order the board-anchor
    block below numbers panels in. Returns references to the ACTUAL shot
    dicts (not copies) and stamps shot['role'] = 'master'/'angle' AND
    shot['_mi'] = the shot's 0-based moment index in place, so a caller
    that mutates the returned dicts (enforce_setup_variety swaps content
    between two of them) mutates the real moments structure too — and can
    reason about how far apart two shots' BEATS are, not just their flat
    positions (a swap across many moments drags one beat's visual content
    into a narratively wrong beat)."""
    flat: list[dict] = []
    for mi, moment in enumerate(moments):
        m = moment["master"]
        m["role"] = "master"
        m["_mi"] = mi
        flat.append(m)
        for a in moment.get("angles") or []:
            a["role"] = "angle"
            a["_mi"] = mi
            flat.append(a)
    return flat


def enforce_setup_variety(flat_shots: list[dict], max_consecutive: int = 2) -> int:
    """CODE validator (C2 item 3): visual-variety cap. No more than
    `max_consecutive` shots in a row (in scene draw/output order) may share
    the same BASE setup family — "B, B-CU, B" in a row is 3 consecutive
    shots of family B, not 3 different setups, so it counts as a violation
    exactly like "B, B, B" would.

    flat_shots: the scene's shots in output order (see _flatten_shots),
    each a dict with a 'description' carrying its "(SETUP X)" tag (or an
    explicit 'setup_id' override, handy for tests), a 'role' of
    'master'/'angle', and '_mi' — the shot's 0-based moment index
    (_flatten_shots stamps it; a missing '_mi' defaults to 0, which makes
    every shot same-moment — fine for synthetic single-beat test inputs,
    never the case for real flattened scenes).

    Fix strategy (cheapest-first, no LLM re-plan — matches C1's zero-paid-
    call rule): for each shot beyond the cap in a same-family run, find a
    different-family angle-role shot to trade with, searched in BEAT-
    DISTANCE order, never flat-position order — an angle's description
    carries its BEAT's action ("Close on Marco listening, brow furrowed"),
    so content dragged across distant moments lands narratively wrong even
    though no dialogue moves. Candidate order: (a) different-family angles
    in the SAME moment first (fully safe — same beat, different framing),
    then (b) angles in an ADJACENT moment (absolute moment distance exactly
    1), nearer flat position breaking ties. Anything at moment distance >= 2
    is NEVER used: the violation is left in place and logged loudly instead.
    The swap trades the two shots' full visual content (shot_type +
    description) in place. Angles carry no LINE/speaker — only which framing
    appears at a given position changes, never which moment's dialogue plays
    — so this can never reassign a spoken line to the wrong moment. MASTERS
    ARE NEVER SWAPPED, on either side: a master owns its moment's LINE and
    is the setup's anchor-owner slot, and moving one would reorder the
    dialogue. A (REACTION)/(INSERT)-TAGGED shot (see _shot_tag) is ALSO NEVER
    SWAPPED, on either side, same as a master: its description names a
    specific listener/speaker tied to one exact instant ("CU on X, listening
    to Y's line, same instant") — even an adjacent-moment swap can land that
    content where Y isn't speaking, so a tagged shot is excluded from both
    the offender-fix attempt and the candidate pool. When no safe swap
    exists (the whole run is masters/tagged shots, or no safe different-
    family angle sits within one moment of the offender), the violation is
    left in place and logged loudly instead.

    Returns the number of violations found (fixed + merely flagged)."""
    violations = 0
    n = len(flat_shots)
    families = [_shot_family(s) if "setup_id" not in s else _setup_base_id(s["setup_id"])
                for s in flat_shots]
    i = 0
    while i < n:
        fam = families[i]
        if fam is None:
            i += 1
            continue
        j = i
        while j < n and families[j] == fam:
            j += 1
        run_len = j - i
        if run_len > max_consecutive:
            for k in range(i + max_consecutive, j):
                violations += 1
                swap_with = None
                if flat_shots[k].get("role") == "angle" and not _shot_tag(flat_shots[k]):
                    k_mi = flat_shots[k].get("_mi", 0)
                    candidates = [
                        c for c in range(n)
                        if not (i <= c < j)  # never trade within the offending run
                        and flat_shots[c].get("role") == "angle"
                        and not _shot_tag(flat_shots[c])  # never relocate REACTION/INSERT content
                        and families[c] not in (None, fam)
                        and abs(flat_shots[c].get("_mi", 0) - k_mi) <= 1  # same or adjacent beat ONLY
                    ]
                    # Same-moment candidates first (distance 0 — same beat,
                    # different framing, fully safe), then adjacent-moment
                    # (distance 1); nearer flat position breaks ties.
                    candidates.sort(key=lambda c: (abs(flat_shots[c].get("_mi", 0) - k_mi),
                                                   abs(c - k)))
                    swap_with = candidates[0] if candidates else None
                if swap_with is not None:
                    a, b = flat_shots[k], flat_shots[swap_with]
                    a["shot_type"], b["shot_type"] = b["shot_type"], a["shot_type"]
                    a["description"], b["description"] = b["description"], a["description"]
                    if "setup_id" in a or "setup_id" in b:
                        a["setup_id"], b["setup_id"] = b.get("setup_id"), a.get("setup_id")
                    families[k], families[swap_with] = families[swap_with], families[k]
                    print(f"  ⚠️ setup variety: swapped shot {k} <-> {swap_with} to break a "
                          f"{run_len}-long run of setup {fam}", flush=True)
                else:
                    print(f"  ⚠️ setup variety: {run_len}-long run of setup {fam} at position "
                          f"{k} — no safe angle swap found, left as-is", flush=True)
        i = j
    return violations


def assign_setup_anchors(moments: list) -> dict:
    """SETUP ANCHORS (Ryan, 2026-07-21; base-family keying added C2 item 2):
    tag every shot with its camera-setup id and make the FIRST-planned shot
    of each BASE setup family that family's anchor owner — its landed frame
    becomes the canonical room every later same-FAMILY shot copies (see
    _SETUP_ANCHOR / generate_coverage_frames's docstring). Plan order makes
    the wait graph acyclic; an owner never waits on a setup future.

    Keyed on setup_base_id (not the full compound id): "B-CU" and "B" share
    one family, so a size-variant shot awaits and attaches its BASE setup's
    anchor frame instead of starting its own, unmatched room. The full
    compound id still rides on shot["setup_id"] for bookkeeping (consecutive-
    cap, logging) — only the anchor lookup collapses to the base family.

    Ownership rule (simplest correct one — documented per the chunk spec):
    whichever shot of a base family is planned FIRST owns that family's
    anchor, whatever its own variant. A B-CU that happens to lead a family
    DOES become the owner, and every later B (or B-CU) shot in that family
    awaits it — no separate "prefer the plain letter" rule is applied.

    Mutates every tagged shot in place (setup_id, setup_base_id,
    setup_anchor_owner) and returns the {base_id: asyncio.Future} map that
    generate_coverage_frames awaits/resolves against. Must run inside a
    running event loop."""
    setup_anchors: dict = {}
    for moment in moments:
        for shot in [moment["master"], *(moment.get("angles") or [])]:
            sid = _setup_id(shot)
            if not sid:
                continue
            base = _setup_base_id(sid)
            shot["setup_id"] = sid
            shot["setup_base_id"] = base
            if base not in setup_anchors:
                setup_anchors[base] = asyncio.get_running_loop().create_future()
                shot["setup_anchor_owner"] = True
    return setup_anchors


# =============================================================================
# Reaction/insert/re-establish FLOORS (C3 item 2) — the ADD-side counterpart
# to enforce_shot_budget, which only ever TRIMS. A dialogue scene with no
# listener reactions, no punctuation inserts, and no periodic re-establish
# reads like a slideshow, not an edit.
# =============================================================================

_REACTION_TURNS_PER_SHOT = 4     # >=1 REACTION shot per this many speaking turns, floored at 1
_INSERT_SHOTS_PER_ONE = 7        # >=1 INSERT shot per this many total shots (midpoint of "6-8")
_REESTABLISH_SHOTS_PER_ONE = 10  # >=1 RE-ESTABLISH wide per this many total shots

# Insert-framing fix (verified bug: INSERT shots were drawing as wide two-shots
# instead of tight detail close-ups — the old desc truncated the scene's WHOLE-
# ROOM [SET|] line to 80 chars as the "detail," and the universal set-dressing
# tail below (run_coverage) then appended full two-character blocking to every
# shot including inserts, so nothing in the prompt ever asked for a close
# framing). Every INSERT desc now opens with this explicit framing clause —
# extreme close-up, shallow depth, no faces — so the image model has no room
# to draw a wide staged shot instead.
_INSERT_FRAMING_CLAUSE = ("Extreme close-up, tight detail shot, shallow depth of field, "
                          "no faces visible")
_INSERT_FALLBACK_SUBJECT = "the speaking character's hands and the nearest prop"

# Close-up/tight framing language the guard below requires — deliberately
# broad (several ways a description can legitimately say "this is tight")
# rather than pinned to _INSERT_FRAMING_CLAUSE's exact wording, so a manually
# edited or legacy INSERT desc that phrases framing differently still passes.
_CLOSEUP_FRAMING_TERMS_RE = re.compile(
    r"extreme close-?up|close-?up|tight (?:detail|framing|shot)|shallow depth", re.IGNORECASE)


def _insert_subject_hint(props: list | None, index: int) -> str:
    """The detail an INSERT shot's close-up frames on — rotated through the
    matched environment's canonical prop manifest (migration 115,
    apply_prop_manifest/check_prop_manifest_consistency above) by insert
    index, so a scene with several INSERT floors doesn't describe the same
    object twice. Deterministic, no LLM call — same rule as every other
    floor in this function. Falls back to a generic hands+prop hint when no
    manifest is available (legacy environments, or no matched environment at
    all) — the ONLY case where the old whole-room [SET|] text used to leak
    in as the "detail" is gone; the fallback never quotes set dressing."""
    names = []
    for p in (props or []):
        name = (p.get("name") or "").strip() if isinstance(p, dict) else str(p or "").strip()
        if name:
            names.append(name)
    if names:
        return names[index % len(names)]
    return _INSERT_FALLBACK_SUBJECT


def _insert_desc_violation(desc: str, character_names) -> str | None:
    """Cheap deterministic guard on a generated INSERT description (house
    pattern: coverage_to_app.gate_motion_prompt — a short violation reason
    or None, regex-only, conservative by design). Two clear failure modes:

      (a) no close-up/tight framing language at all — the desc doesn't
          actually read as a detail insert, the bug this fix targets.
      (b) BOTH of the scene's character names appear in the desc — a detail
          insert should name at most one character (if any); two full names
          present means character-blocking prose slipped back in.

    Returns a short reason string on a violation, else None. Never raises —
    a bad/missing character_names iterable is treated as empty."""
    d = desc or ""
    if not _CLOSEUP_FRAMING_TERMS_RE.search(d):
        return "missing a close-up/tight framing term"
    try:
        names = [n for n in character_names or [] if n and re.search(rf"\b{re.escape(n)}\b", d, re.IGNORECASE)]
    except TypeError:
        names = []
    if len(names) >= 2:
        return f"both character names present in a detail insert ({', '.join(sorted(names))})"
    return None


def _is_wide(shot) -> bool:
    """True when the shot's shot_type resolves to the "wide" composition
    bucket (reuses plan_camera_moves' own _SHOT_TYPE_COMPOSITION mapping —
    one source of truth for what counts as a wide shot)."""
    return _SHOT_TYPE_COMPOSITION.get((shot.get("shot_type") or "").upper()) == "wide"


def _family_counts(flat: list[dict]) -> dict:
    """{setup family: how many shots in the scene share it} — used to find a
    safe shot to repurpose when a floor must be met AT the frame cap (an
    "excess" family has more than one shot, so converting one still leaves
    the family represented)."""
    counts: dict = {}
    for s in flat:
        fam = _shot_family(s)
        if fam:
            counts[fam] = counts.get(fam, 0) + 1
    return counts


def _least_recently_used_family(flat: list[dict], exclude: set | None = None) -> str | None:
    """The setup family that has gone longest without a shot in DRAW order
    (or was never used) — a reasonable, deterministic camera reuse for a
    floor-added shot (per the chunk spec: never invent a new camera
    position). `exclude` keeps out a family the caller doesn't want reused
    (typically the shot the new one is reacting against). None when no
    tagged family exists at all (legacy plan with no [SETUPS | ...] kit)."""
    exclude = exclude or set()
    last_seen: dict = {}
    for i, s in enumerate(flat):
        fam = _shot_family(s)
        if fam:
            last_seen[fam] = i
    candidates = [f for f in last_seen if f not in exclude]
    if not candidates:
        return None
    return min(candidates, key=lambda f: last_seen[f])


def _listener_for_moment(moment: dict, speakers: set) -> str | None:
    """The scene's OTHER speaker for a clean 2-hander (rule 5f: a REACTION
    shot shows the person LISTENING, not the one talking). None when the
    moment has no assigned speaker or the scene isn't exactly 2 speakers —
    with 1 or 3+ speakers "the listener" has no single well-defined answer,
    so the caller must skip rather than guess."""
    spk = moment.get("speaker")
    if not spk or len(speakers) != 2:
        return None
    others = speakers - {spk}
    return next(iter(others)) if others else None


def _parse_setup_kit(setups_line: str | None) -> dict:
    """{setup_id: kit description} parsed from the [SETUPS | ...] line's own
    'ID: text; ID: text' format (the format the planner prompt mandates and
    every live directive uses — e.g. 'B: MCU OTS over Ryan's RIGHT shoulder
    onto Vanessa — ...; B-CU: tighter CU variant of SETUP B ...'). Compound
    ids (B-CU) parse as their own entries. Empty dict for a legacy plan with
    no kit line — every consumer must treat that as 'no kit knowledge' and
    fall back to its pre-C9 behavior."""
    out: dict = {}
    for part in (setups_line or "").split(";"):
        m = re.match(r"\s*([A-Z][A-Za-z0-9\-]{0,7})\s*:\s*(.+)", part.strip(), re.DOTALL)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


# Kit-line markers that say a setup family shows NO people (an insert/prop/
# detail camera) — a REACTION (a face CU) must never be assigned there: the
# family's approved anchor frame is a props-only composition, and the draw
# prompt tells the model to match that anchor's framing/background EXACTLY,
# so a face shot pinned to it fights its own reference (C9 defect: shot 47's
# reaction landed in family E, the island-props INSERT/NEUTRAL setup).
_NO_PEOPLE_KIT_RE = re.compile(r"\bINSERT\b|\bNEUTRAL\b|\bno people\b", re.IGNORECASE)


def _no_people_families(kit: dict) -> set:
    """BASE families whose kit text marks them INSERT/NEUTRAL/no-people —
    excluded from REACTION placement entirely (add path, LRU fallback, all
    of it). Base-level on purpose: if 'E' is a props camera, 'E-CU' is too."""
    return {_setup_base_id(fid) for fid, desc in kit.items()
            if _NO_PEOPLE_KIT_RE.search(desc or "")}


def _facing_family(kit: dict, listener: str) -> str | None:
    """The BASE setup family whose camera FACES `listener` (i.e. the family
    whose frames show the listener's face as the subject), derived from the
    kit line's own text — 'onto {name}' is the kit's explicit facing
    declaration ('B: MCU OTS over Ryan's right shoulder onto Vanessa' faces
    Vanessa); 'on {name}' / '{name} sharp' are the subject-naming fallbacks
    the CU-variant entries use ('punching in on Vanessa's face', 'Vanessa
    sharp right-of-center'). Excludes no-people families by construction
    (their text names props, not a person, so no pattern can match a
    listener there — but the caller re-checks anyway). None when the kit
    carries no facing evidence for this listener at all (legacy or terse
    kit) — the caller then falls back to LRU. First match in kit order wins;
    compound entries (B-CU) resolve to their base family."""
    if not listener:
        return None
    name = re.escape(listener)
    patterns = [
        re.compile(rf"\bonto\s+{name}\b", re.IGNORECASE),
        re.compile(rf"\bon\s+{name}\b", re.IGNORECASE),
        re.compile(rf"\b{name}\b[^;]{{0,30}}\bsharp\b", re.IGNORECASE),
    ]
    for pat in patterns:
        for fid, desc in kit.items():
            if pat.search(desc or ""):
                return _setup_base_id(fid)
    return None


def _reaction_family_tag(kit: dict, listener: str, cur: list, master_family) -> str | None:
    """The full setup id a floor-added REACTION on `listener` should carry
    (C9 placement rule): the CU compound variant of the family that FACES
    the listener ('{base}-CU' when the kit defines one, sharing that
    family's anchor via the existing base-letter logic; the base id itself
    otherwise). Never a family the kit marks INSERT/NEUTRAL/no-people, and
    never invented — when no facing family is derivable, fall back to the
    least-recently-used family among the non-excluded, non-establish
    families (the establishing family's anchor is the WIDE two-shot — legal
    as a same-axis tighter variant but not the film-grammar-correct home
    for a face CU either). None when nothing eligible exists at all."""
    excluded = _no_people_families(kit)
    establish = _shot_family(cur[0]) if cur else None
    facing = _facing_family(kit, listener)
    if facing and facing not in excluded:
        return f"{facing}-CU" if f"{facing}-CU" in kit else facing
    exclude = set(excluded)
    if establish:
        exclude.add(establish)
    if master_family:
        exclude.add(master_family)
    return _least_recently_used_family(cur, exclude=exclude)


def _find_convertible_angle(flat: list[dict], family_counts: dict) -> dict | None:
    """An existing ANGLE shot safe to repurpose for a floor addition when the
    scene is already at its frame cap (C3 item 2's "convert rather than add"
    rule): an angle whose family has at least one sibling shot (so
    repurposing it loses no unique camera setup) and that isn't already
    carrying a REACTION/INSERT tag of its own. Searched in flat (draw) order
    — first eligible shot wins (same "cheapest deterministic fix" precedent
    as enforce_setup_variety's swap search). MASTERS ARE NEVER CONVERTED —
    a master owns its moment's LINE, same law as enforce_setup_variety."""
    for s in flat:
        if s.get("role") != "angle":
            continue
        if _shot_tag(s):
            continue
        fam = _shot_family(s)
        if fam and family_counts.get(fam, 0) > 1:
            return s
    return None


def enforce_reaction_insert_floors(moments: list, set_line: str | None = None,
                                   max_frames: int | None = None,
                                   setups_line: str | None = None,
                                   props: list | None = None) -> int:
    """CODE floor validator (C3 item 2), parallel to enforce_shot_budget but
    the opposite direction — that one only ever TRIMS, this one only ever
    ADDS the minimum coverage a dialogue scene needs to cut like an editor
    (rule 5f). Deterministic, NO LLM call — same zero-paid-call rule as C1/
    C2's CODE validators:

      REACTION — on a "key line" (approximated as the scene's speaking
      turns, most climactic first — mirrors C1's scene-move-budget
      precedent of treating the scene-final beat as the place to spend a
      limited floor), an angle on the LISTENER's face. >=1 per
      _REACTION_TURNS_PER_SHOT speaking turns, floored at 1, but ONLY when
      the scene is a clean 2-speaker dialogue with >=2 turns — a monologue
      or 3+-speaker scene has no single well-defined "listener", so this
      floor is skipped rather than guessed (see _listener_for_moment).

      INSERT — a prop/detail punctuation shot, >=1 per _INSERT_SHOTS_PER_ONE
      total shots (the prompt's own "1 per 6-8" rule of thumb, midpointed).
      Insert-framing fix: the desc always opens with an explicit close-up
      framing clause (_INSERT_FRAMING_CLAUSE — extreme close-up, shallow
      depth, no faces) and names a real detail — a prop rotated in from the
      matched environment's manifest (`props`, migration 115) by insert
      index when one is available, else a generic hands+prop fallback
      (_INSERT_FALLBACK_SUBJECT). NEVER the scene's whole-room [SET | ...]
      line truncated to 80 chars — that was the bug: a wide-room summary
      quoted as the "detail" produces a wide two-shot, not a close-up. A
      cheap deterministic guard (_insert_desc_violation) rejects and
      regenerates any desc that ends up missing the framing clause or
      naming both of the scene's speakers — see that function's docstring.

      RE-ESTABLISH — a WIDE two-shot reusing the scene's ESTABLISHING setup
      family (moments[0]'s master's family — rule 5b makes the scene's
      first shot a two-shot master by construction), >=1 per
      _REESTABLISH_SHOTS_PER_ONE total shots; the opening master itself
      always counts toward this floor, so a short scene typically needs no
      extra at all.

    Every addition is deterministic: a `(SETUP X)` tag reusing an EXISTING
    family (never inventing a new camera position) and a plain-language
    description built only from data already on the moments (the listener's
    name from `moment["speaker"]` / `speakers`, the environment's prop
    manifest passed as `props`). REACTION placement (C9): the kit text
    passed as `setups_line` picks the family that FACES the listener (its
    CU compound variant when the kit defines one) via _reaction_family_tag —
    families the kit marks INSERT/NEUTRAL/no-people are never used for a
    face shot; _least_recently_used_family remains the fallback (and the
    INSERT/RE-ESTABLISH floors' unchanged mechanism).

    set_line: accepted for backward-compatible signature parity with every
    caller (plan_moments_deterministic, coverage_to_app.py) but no longer
    used to build an INSERT description — that was the bug this fix
    addresses (a whole-room [SET | ...] line truncated to 80 chars is a
    wide-room summary, not a close-up detail). Set-dressing continuity for
    every shot, INSERT included, is applied separately by run_coverage's own
    SET-DRESSING LOCK tail, which now branches per shot's _shot_tag.

    props: the matched environment's canonical prop manifest (list of
    {name, position} dicts, or plain strings — same shape apply_prop_manifest
    takes), or None. Drives the INSERT floor's subject selection only; every
    other floor ignores it. None (the default) reproduces the pre-fix
    fallback-subject behavior exactly.

    max_frames (C3 item 2's frame-cap rule): once the scene is AT its frame
    cap, a floor is satisfied by CONVERTING an existing excess same-family
    ANGLE (never a master — see _find_convertible_angle) into the needed
    shot instead of growing the total. When no safe conversion exists, the
    floor is logged loudly and left unmet rather than blowing the budget —
    matches enforce_setup_variety's own "flag, don't force" fallback.

    Mutates `moments` in place (appends to a moment's "angles", or rewrites
    an existing angle's shot_type/description). Returns the number of shots
    added or converted."""
    if not moments or not moments[0].get("master"):
        return 0
    fixed = 0

    def _at_cap() -> bool:
        return max_frames is not None and len(_flatten_shots(moments)) >= max_frames

    def _place(mi: int, shot_type: str, description: str, kind: str) -> bool:
        nonlocal fixed
        if _at_cap():
            cur = _flatten_shots(moments)
            victim = _find_convertible_angle(cur, _family_counts(cur))
            if victim is None:
                print(f"  ⚠️ {kind} floor: at the {max_frames}-frame cap with no safe shot "
                      f"to convert — floor left unmet", flush=True)
                return False
            victim["shot_type"], victim["description"] = shot_type, description
            print(f"  🎬 {kind} floor: converted an excess shot instead of growing past the "
                  f"{max_frames}-frame cap", flush=True)
            fixed += 1
            return True
        moments[mi].setdefault("angles", []).append(
            {"shot_type": shot_type, "description": description})
        print(f"  🎬 {kind} floor: added a shot to moment "
              f"{moments[mi].get('moment_number', mi + 1)}", flush=True)
        fixed += 1
        return True

    # ---- RE-ESTABLISH ---------------------------------------------------
    establish_family = _shot_family(moments[0]["master"])
    if establish_family:
        cur = _flatten_shots(moments)
        want = max(1, len(cur) // _REESTABLISH_SHOTS_PER_ONE)
        have = sum(1 for s in cur if _shot_family(s) == establish_family and _is_wide(s))
        need = max(0, want - have)
        n = len(moments)
        for k in range(need):
            target_mi = min(n - 1, ((k + 1) * n) // (need + 1))
            desc = (f"(SETUP {establish_family}) WS re-establishing the whole staging at its "
                    "established framing, camera unchanged.")
            _place(target_mi, "WS", desc, "re-establish")

    # ---- REACTION ---------------------------------------------------------
    # C9 placement rule: a REACTION on listener L belongs in the CU compound
    # variant of the setup family that FACES L (derived from the [SETUPS|]
    # kit text — see _reaction_family_tag), never in a family the kit marks
    # INSERT/NEUTRAL/no-people (a face CU pinned to a props-only anchor
    # frame fights its own reference — C9 defect: shot 47's reaction landed
    # in family E, the island-props insert camera), and only falls back to
    # LRU (among non-excluded, non-establish families) when no facing family
    # is derivable at all.
    kit = _parse_setup_kit(setups_line)
    speaking_moments = [m for m in moments if m.get("speaker") and m.get("line")]
    speakers = {m["speaker"] for m in speaking_moments}
    if len(speakers) == 2 and len(speaking_moments) >= 2:
        cur = _flatten_shots(moments)
        want = max(1, len(speaking_moments) // _REACTION_TURNS_PER_SHOT)
        have = sum(1 for s in cur if _shot_tag(s) == "REACTION")
        need = max(0, want - have)
        if need:
            # Most climactic turn first (the scene's LAST speaking moment) —
            # same tie-break precedent as C1's scene move budget.
            for m in list(reversed(speaking_moments))[:need]:
                listener = _listener_for_moment(m, speakers)
                if not listener:
                    continue
                mi = moments.index(m)
                cur = _flatten_shots(moments)
                fam = _reaction_family_tag(kit, listener, cur, _shot_family(m["master"]))
                if not fam:
                    continue
                desc = (f"(SETUP {fam})(REACTION) CU on {listener}, listening to "
                        f"{m['speaker']}'s line, same instant.")
                _place(mi, "CU", desc, "reaction")

    # ---- INSERT -------------------------------------------------------
    # Insert-framing fix (verified bug): the old desc here truncated the
    # scene's WHOLE-ROOM [SET|] line to 80 chars and called that the
    # "detail" — a wide-room summary read as a wide two-shot, not a close-up,
    # and nothing in the prompt asked for tight framing at all. Every INSERT
    # desc now leads with an explicit close-up clause and names one real
    # detail (a manifest prop when the environment has one) instead.
    cur = _flatten_shots(moments)
    want = len(cur) // _INSERT_SHOTS_PER_ONE
    have = sum(1 for s in cur if _shot_tag(s) == "INSERT")
    need = max(0, want - have)
    if need:
        n = len(moments)
        # Character names for the guard's "both names present" check — every
        # speaker assigned anywhere in the scene, not just the 2-speaker
        # REACTION-eligible set above (an INSERT floor can fire in a
        # monologue or 3+-speaker scene too).
        all_speakers = {m["speaker"] for m in moments if m.get("speaker")}
        for k in range(need):
            target_mi = min(n - 1, ((k + 1) * n) // (need + 1))
            cur = _flatten_shots(moments)
            fam = _least_recently_used_family(cur)
            if not fam:
                continue
            subject = _insert_subject_hint(props, k)
            desc = (f"(SETUP {fam})(INSERT) {_INSERT_FRAMING_CLAUSE} — {subject}, "
                    f"punctuating the beat.")
            violation = _insert_desc_violation(desc, all_speakers)
            if violation:
                # Same conservative style as coverage_to_app.gate_motion_prompt:
                # a clear contradiction gets regenerated deterministically
                # (never an LLM call) rather than shipped as-is.
                print(f"  ⚠️ insert floor: generated desc failed the framing guard "
                      f"({violation}) — regenerated with the safe generic subject", flush=True)
                desc = (f"(SETUP {fam})(INSERT) {_INSERT_FRAMING_CLAUSE} — "
                        f"{_INSERT_FALLBACK_SUBJECT}, punctuating the beat.")
            _place(target_mi, "INSERT", desc, "insert")

    return fixed


# =============================================================================
# Per-shot target durations (C3 item 4) — SILENT shots only.
# =============================================================================
# render_perform.py's assembler already sizes a SPEAKING shot's window from
# measured speech (assets.carries_own_line / clip_speech_start/end, migration
# 114) — that path is untouched. Every other (silent) shot gets a per-type
# target so the assembler cuts like an editor instead of splitting a fixed
# narration block by word count alone: a wide holds the frame longer than an
# insert. Reuses plan_camera_moves' own _SHOT_TYPE_COMPOSITION bucketing —
# one source of truth for what counts as wide/medium/closeup.
_COMPOSITION_DURATION_SECONDS = {"wide": 3.5, "medium": 2.5, "closeup": 1.6}


def stamp_shot_durations(moments: list) -> int:
    """Stamp shot["duration_seconds"] on every SILENT shot in `moments` —
    every angle, and every master EXCEPT a speaking moment's master (that
    one's clip-length comes from measured speech at animate/assemble time,
    never from this table). Idempotent (safe to call more than once; always
    overwrites with the same deterministic value for a given shot_type).
    Returns how many shots were stamped."""
    n = 0
    for moment in moments:
        speaking = bool(moment.get("speaker") and moment.get("line"))
        m = moment.get("master")
        if m and not speaking:
            m["duration_seconds"] = _COMPOSITION_DURATION_SECONDS.get(
                _SHOT_TYPE_COMPOSITION.get((m.get("shot_type") or "").upper(), "medium"), 2.5)
            n += 1
        for a in moment.get("angles") or []:
            a["duration_seconds"] = _COMPOSITION_DURATION_SECONDS.get(
                _SHOT_TYPE_COMPOSITION.get((a.get("shot_type") or "").upper(), "medium"), 2.5)
            n += 1
    return n


# =============================================================================
# C7 fix (a): the ONE deterministic shot-planning pipeline. Before this fix,
# coverage_to_app.py's sheet-planning path (_plan_sheet_prompts's callers)
# ran parse_coverage -> enforce_shot_budget ONLY, while run_coverage() below
# ALSO ran enforce_reaction_insert_floors and enforce_setup_variety before
# chunking/counting panels for the board-anchor block. Both passes are
# deterministic and code-only (no LLM), so there was never a reason for them
# to disagree — but any floor insertion or variety swap shifted which shot
# landed at position k, so the approved sheet's panel k and the final
# picture's shot k silently stopped matching (composing to the WRONG
# panel). Centralizing the whole sequence in one function, imported by both
# sides instead of re-typed at each call site, makes that divergence
# structurally impossible rather than merely documented.
# =============================================================================

def plan_moments_deterministic(directive_text: str, max_moments: int, angles_max: int,
                               max_frames: int | None = None, verbose: bool = False,
                               props: list | None = None) -> list[dict] | None:
    """parse_coverage -> enforce_shot_budget -> enforce_reaction_insert_floors ->
    enforce_setup_variety, in that exact order, on the SAME directive_text —
    the one pipeline every consumer of a saved coverage directive (the sheet
    preview AND the real pictures draw) must run so a shot's position never
    depends on which caller asked. Every pass here is pure/deterministic
    (no LLM call), so two callers handed the same directive_text and the
    same shape params (max_moments/angles_max/max_frames — themselves
    deterministic from scene_text + dialogue_audio, see _coverage_shape)
    always get byte-identical shot sequences back.

    Returns None (never an empty list) when the directive parses to no
    moments at all — callers should treat that as "nothing to plan",
    same as a bare parse_coverage() failure would.

    verbose: print the same progress lines run_coverage() has always
    printed for the floors/variety passes (the sheet-planning callers stay
    silent, matching their pre-fix behavior of never logging these — only
    the real draw path narrates progress to the creator).

    props: the matched environment's prop manifest, threaded straight into
    enforce_reaction_insert_floors' INSERT-subject selection (see that
    function's docstring). Only run_coverage's real PICTURES path passes a
    real value; the sheet-planning callers pass none (the same "PICTURES
    path only" wall apply_prop_manifest documents) and keep the generic
    fallback subject — this changes an INSERT desc's WORDING only, never
    its shot count or position, so board-panel numbering stays unaffected
    either way."""
    moments = parse_coverage(directive_text or "")
    if not moments:
        return None
    moments = enforce_shot_budget(moments, max_moments, angles_max, max_frames=max_frames)
    n_floors = enforce_reaction_insert_floors(
        moments, set_line=parse_set_dressing(directive_text or ""), max_frames=max_frames,
        # C9: the kit line drives REACTION placement (the facing family's CU
        # variant) — parsed from the SAME directive_text, so both callers of
        # this one pipeline keep byte-identical shot sequences.
        setups_line=parse_setups_line(directive_text or ""), props=props)
    if verbose and n_floors:
        print(f"  🎬 reaction/insert/re-establish floors: {n_floors} shot(s) added or converted",
              flush=True)
    n_variety = enforce_setup_variety(_flatten_shots(moments))
    if verbose and n_variety:
        print(f"  🎞️ setup variety: {n_variety} same-setup run(s) beyond 2 consecutive "
              f"shots addressed", flush=True)
    return moments


# Panels per gate sheet now depends on the plan's format — see
# panels_per_sheet_for(). Sheet chunking (coverage_to_app._plan_sheet_prompts
# caller) and the board-anchor math below must both derive their boundaries
# from sheet_chunk_sizes() on the same (total, cap) pair.


async def _gen_ref(image_client, prompt, refs, aspect, resolution, attempts=2, model_override=None):
    """Generate one frame honoring `model_override` (routed through
    shared.clients.image_model_router — the SAME resolver coverage_to_app.py and the
    legacy pipeline_executor.py variant path use), with a light retry. GPT Image 2
    (gpt-image-2-image-to-image — holds the cast's identity from the reference sheet
    far better than nano-banana) stays the default AND the content-policy/failure
    fallback for an explicit z-image/nano-banana-2 override, unchanged from before.
    ponytail: retry only covers transient None/502; a moderation 400 also returns None and may not
    recover — that frame is then skipped (coverage degrades to fewer angles rather than failing).
    Returns (url, model_used) or (None, None)."""
    for i in range(attempts):
        # A raised error (SSL reset, timeout, connection drop) must count as a
        # failed attempt, not escape — an escaped exception here used to kill
        # the whole scene's gather and stop the build mid-run.
        try:
            url, model_used = await generate_scene_image_for_model(
                image_client, model_override, prompt, reference_urls=refs,
                aspect_ratio=aspect, resolution=resolution)
        except Exception as e:  # noqa: BLE001
            print(f"  frame gen error (attempt {i + 1}/{attempts}): {str(e)[:120]}", flush=True)
            url, model_used = None, None
        if url:
            return url, model_used
        await asyncio.sleep(2 * (i + 1))
    return None, None


# =============================================================================
# Camera Movement Engine hook (storytelling coverage path)
# =============================================================================
# A camera move is a contract between two prompts: the STILL must be composed
# for the move (image_setup), and the MOTION prompt must execute that exact
# move. plan_camera_moves() decides per shot BEFORE frames are drawn, appends
# the composition contract to the shot description, and stamps the plan on the
# shot dict ("move_id|PURPOSE" or "static") so it rides the frame into assets
# and the motion writer honors it. See image_prompts/engine/camera_selector.py.

_SHOT_TYPE_COMPOSITION = {
    "WS": "wide", "EWS": "wide", "ESTABLISHING": "wide", "FULL": "wide",
    "MS": "medium", "MED": "medium", "MCU": "medium", "OTS": "medium",
    "2S": "medium", "TWO-SHOT": "medium",
    "CU": "closeup", "ECU": "closeup", "INSERT": "closeup", "XCU": "closeup",
}


def _scene_move_budget() -> int:
    """Max earned non-static camera moves per scene (C1). Read at CALL time
    (not module import) so tests/callers can tune SE_SCENE_MOVE_BUDGET per
    run. Defaults to 1: calm dialogue coverage should land mostly static,
    with at most one earned move per scene unless a channel opts into more."""
    raw = os.getenv("SE_SCENE_MOVE_BUDGET", "1")
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return 1
    return n if n >= 0 else 1


def plan_camera_moves(
    moments: list,
    render_style: str | None = None,
    video_model_id: str | None = None,
    camera_mode: str | None = None,
) -> int:
    """Plan a camera move per shot across a scene's coverage moments, in shot
    order (master then angles, moment by moment). Mutates the shot dicts:
    appends the move's image_setup to the drawing description and stamps
    shot["camera_move"]. Returns how many shots earned a move. Best-effort —
    any failure leaves the scene exactly as it was (static/freeform behavior).

    render_style/video_model_id (C13b, checklist §C13b): the video's declared
    LOOK ('animated' | 'realistic' | None) and its own video-level model,
    threaded straight into route_shot_model()'s channel-style guardrail
    below — see that function's docstring for what each does. Both default
    to None (the "no channel style declared" money-safe path) so every
    existing caller keeps working unchanged; a real caller (generate_
    coverage_for_video in coverage_to_app.py) passes the video's actual
    values.

    SCENE MOVE BUDGET (C1): this is the only place that sees the whole
    ordered shot list for a scene, so it's the only place a per-scene cap can
    be enforced. The per-shot selector (select_camera_move) decides purely
    shot-by-shot and knows nothing about how many of its siblings already
    earned a move — left alone, a scene of otherwise-calm dialogue beats can
    have every shot individually "earn" a move via the REVEAL/PAYOFF
    positional upgrades, which the anti-repeat variety scoring in
    camera_selector.score_move() then mechanically rotates into a rigid
    period-4 pattern. After the normal per-shot loop below runs (unchanged),
    a second pass caps the scene to SE_SCENE_MOVE_BUDGET (default 1) earned
    moves: it keeps the move on the scene's most climactic earned shot and
    downgrades the rest back to static, restoring their original
    (un-composed) description and re-routing their model recommendation."""
    try:
        from image_prompts.engine.camera_selector import ShotContext, select_camera_move
    except Exception as e:  # noqa: BLE001
        # C8 fix (c): this except used to swallow the failure silently — EVERY
        # shot in the scene then quietly degraded to static/freeform with no
        # trace of why. The real cause is almost always sys.path: this module
        # AND camera_selector.py's own inner `from animation_prompt_engine
        # import ...` (bare, not package-qualified) only resolve when
        # skills/video-pipeline/image_prompts is on sys.path — the live
        # server gets that from pipeline_executor.py's boot-time bootstrap,
        # but a standalone CLI invocation (coverage_to_app.py run directly,
        # not through the server) can miss it and silently fall back to a
        # fully static scene. Name it loudly instead of guessing later.
        print(f"  ⚠️ plan_camera_moves: camera engine unavailable ({e!r}) — every shot in "
              f"this scene degrades to static/freeform. This needs "
              f"skills/video-pipeline/image_prompts on sys.path (the server adds it at boot "
              f"in pipeline_executor.py; a standalone script must bootstrap the same bot "
              f"subdirectories itself — see coverage_to_app.py's sys.path setup).", flush=True)
        return 0

    if camera_mode not in {
        None,
        "",
        "dialogue_coverage",
        "investigative_coverage",
    }:
        raise ValueError(f"Unsupported camera grammar: {camera_mode}")
    planned = 0
    prev_ids: list = []
    prev_keys: list = []
    earned: list = []  # [{shot, ctx, sel, orig_description}] in shot order, this scene
    try:
        for mi, moment in enumerate(moments):
            shots = [("master", moment.get("master") or {})]
            shots += [("angle", a) for a in (moment.get("angles") or [])]
            speaking = bool(moment.get("speaker") and moment.get("line"))
            for role, shot in shots:
                if not shot.get("description"):
                    continue
                is_scene_final = (mi == len(moments) - 1 and role == "master")
                ctx = ShotContext(
                    sentence_text=f"{moment.get('summary') or ''}. {shot['description']}",
                    # C1 classifier diet: the narrow narrative beat (moment summary +
                    # spoken line, if any) — NEVER shot['description'], which by the
                    # time plan_camera_moves runs already carries the scene-constant
                    # SET-DRESSING/AXIS/STAGING boilerplate appended above in
                    # run_coverage(). That boilerplate keyword-matches "behind" etc.
                    # and would false-classify every shot REVEAL. sentence_text
                    # (unchanged) still carries the full composed text for every
                    # other use in camera_selector.py (subject inference, interior
                    # check, jitter) — only classify_camera_purpose() gets the diet.
                    narrative_text=f"{moment.get('summary') or ''}. {moment.get('line') or ''}".strip(". ") + ".",
                    composition=_SHOT_TYPE_COMPOSITION.get(
                        (shot.get("shot_type") or "MS").upper(), "medium"),
                    # Lip-synced speaking shots want calm moves — cap intensity low
                    intensity="low" if (speaking and role == "master") else "medium",
                    is_scene_open=(mi == 0 and role == "master"),
                    is_scene_final=is_scene_final,
                    prev_move_ids=prev_ids,
                    prev_legacy_keys=prev_keys,
                )
                sel = select_camera_move(ctx)
                if sel.move:
                    orig_description = shot["description"]
                    shot["camera_move"] = f"{sel.move.id}|{sel.purpose}"
                    shot["description"] = (
                        f"{shot['description'].rstrip('. ')}. "
                        f"Composed for a {sel.move.name.lower()} camera move: {sel.move.image_setup}"
                    )
                    prev_ids.append(sel.move.id)
                    prev_keys.append(sel.move.legacy_key)
                    planned += 1
                    earned.append({"shot": shot, "ctx": ctx, "sel": sel,
                                    "orig_description": orig_description})
                else:
                    shot["camera_move"] = "static"
                    prev_keys.append("static")

                # Model routing (checklist §1.2/C12): recommend a video
                # model for this shot from the SAME purpose the camera
                # engine just resolved (sel.purpose is always set, whether
                # or not a move was found). Data + recommendation only —
                # clip generation doesn't read this yet (C13). Fail-soft
                # and isolated from camera planning above: a routing
                # failure must never affect the camera-move plan, which is
                # already set either way by the time this runs.
                try:
                    from shared.model_router import route_shot_model
                    decision = route_shot_model(
                        sel.purpose, render_style=render_style,
                        video_model_id=video_model_id)
                    shot["routed_model"] = decision.model_id
                    shot["routing_reason"] = decision.routing_reason
                except Exception as route_err:  # noqa: BLE001
                    print(f"  model routing failed (shot ships without a "
                          f"recommendation): {str(route_err)[:120]}", flush=True)

        # SCENE MOVE BUDGET (C1): trim the scene's earned moves down to the
        # cap. Tie-break: keep the scene-final earned shot first (the
        # PAYOFF-tier beat — the most climactic moment to spend the move
        # budget on), then earned shots in original shot order, until the
        # budget is filled; downgrade everything past that back to static.
        budget = (
            max(_scene_move_budget(), 3)
            if camera_mode == "investigative_coverage"
            else _scene_move_budget()
        )
        if len(earned) > budget:
            priority = sorted(
                range(len(earned)),
                key=lambda i: (0 if earned[i]["ctx"].is_scene_final else 1, i),
            )
            keep = set(priority[:budget])
            for i, rec in enumerate(earned):
                if i in keep:
                    continue
                shot = rec["shot"]
                shot["description"] = rec["orig_description"]
                shot["camera_move"] = "static"
                planned -= 1
                # Re-route: the shot's EFFECTIVE purpose is now STATIC (the
                # move was downgraded), so its model recommendation should
                # reflect that too — the cheap default tier, not the
                # earned-purpose tier it was routed to above. Best-effort,
                # same fail-soft contract as the routing call above: on
                # failure the shot simply keeps whichever routed_model/
                # routing_reason it already had (never crashes the plan).
                try:
                    from shared.model_router import route_shot_model
                    decision = route_shot_model(
                        "STATIC", render_style=render_style,
                        video_model_id=video_model_id)
                    shot["routed_model"] = decision.model_id
                    shot["routing_reason"] = decision.routing_reason
                except Exception as route_err:  # noqa: BLE001
                    print(f"  model re-routing failed after budget downgrade: "
                          f"{str(route_err)[:120]}", flush=True)
    except Exception as e:  # noqa: BLE001 — camera planning must never kill coverage
        # C8 fix (c): THIS is the outer catch that actually swallows the real
        # live failure — the top-level `from image_prompts.engine.
        # camera_selector import ...` above always resolves fine (image_prompts
        # is reachable as a subpackage the moment skills/video-pipeline is on
        # sys.path, which is required for this module to import at all), but
        # camera_selector.resolve_purpose()'s OWN inner bare
        # `from animation_prompt_engine import ...` only resolves when
        # skills/video-pipeline/image_prompts is on sys.path DIRECTLY — the
        # server gets that from pipeline_executor.py's boot bootstrap; a
        # standalone CLI run of coverage_to_app.py didn't, so the FIRST shot's
        # ModuleNotFoundError aborted this whole per-shot loop and every shot
        # in the scene silently ended up with no camera_move planned at all —
        # the one line this except used to print (bare `str(e)`) named the
        # missing module but not the sys.path cause, easy to miss in a wall of
        # other output. Name it unmissably when that's the failure.
        if isinstance(e, ModuleNotFoundError):
            print(f"  ⚠️ camera planning failed — {e} — every shot in this scene stays "
                  f"static/freeform. This is a sys.path gap: skills/video-pipeline/"
                  f"image_prompts must be on sys.path for camera_selector.resolve_purpose()'s "
                  f"animation_prompt_engine import to resolve (the server adds it at boot in "
                  f"pipeline_executor.py; coverage_to_app.py's CLI bootstraps the same bot "
                  f"subdirectories itself).", flush=True)
        else:
            print(f"  camera planning failed (shots stay freeform): {str(e)[:120]}", flush=True)
    return planned


async def generate_coverage_frames(moment, cast_url, image_client, profile,
                                   env_url=None, aspect="16:9", resolution="1K", sem=None,
                                   model_override=None, setup_anchors=None,
                                   progress_callback=None, progress_state=None) -> list[dict] | None:
    """Master frame (anchored on cast) -> each angle (anchored on cast + master).
    Returns frames [{role, shot_type, description, url, image_model}] or None if the master
    fails. The master MUST be drawn first (angles reference it), but the angles only depend on
    the master, not on each other — so they draw in PARALLEL. `sem` caps total Kie gens.

    model_override honors videos.image_model_override end to end (see
    shared.clients.image_model_router) — GPT Image 2 stays the default and the
    content-policy/failure fallback; each frame records WHICH model actually drew it in
    image_model, so store_scene can persist the truth onto the asset row.

    setup_anchors: optional {setup_id: asyncio.Future} shared across the whole
    scene (built by run_coverage). The first-planned shot of each camera setup
    carries shot["setup_anchor_owner"]=True: it draws WITHOUT a setup ref and
    resolves its future with its landed url (or None on failure — resolution
    is guaranteed in `finally`-style paths below so a failed owner can NEVER
    hang the setup's other shots). Every non-owner shot of that setup awaits
    the future and, when it holds a url, attaches it LAST with _SETUP_ANCHOR —
    so repeats of one camera position share one canonical room. Ownership is
    assigned in plan order, so an owner's own waits (its master, that master's
    setup owner...) always point at strictly earlier-planned shots — the wait
    graph is acyclic by construction. A 10-minute wait_for is belt and
    suspenders on top of that."""
    # cast_url may be one URL or a LIST (e.g. the locked per-character 4-view sheets).
    cast_refs = list(cast_url) if isinstance(cast_url, list) else [cast_url]
    base = cast_refs + ([env_url] if env_url else [])
    sem = sem or asyncio.Semaphore(1)  # no semaphore passed => serial fallback
    setup_anchors = setup_anchors if setup_anchors is not None else {}

    async def _gen(prompt, refs):
        async with sem:
            result = await _gen_ref(
                image_client,
                prompt,
                refs,
                aspect,
                resolution,
                model_override=model_override,
            )
            if progress_callback and progress_state is not None:
                progress_state["done"] = int(progress_state.get("done") or 0) + 1
                message = (
                    f"{progress_state.get('prefix') or ''}drawing image "
                    f"{progress_state['done']}/{progress_state['total']}…"
                )
                try:
                    callback_result = progress_callback(message)
                    if inspect.isawaitable(callback_result):
                        await callback_result
                except Exception:
                    pass
            return result

    def _resolve_owned(shot, url):
        """Resolve the setup future this shot owns (idempotent, never raises).
        Keyed on setup_base_id (C2 item 2) — a compound owner like B-CU
        resolves the SAME family future a plain B owner would, so every
        later shot of family B (variant or not) awaits the one anchor."""
        if not shot.get("setup_anchor_owner"):
            return
        fut = setup_anchors.get(shot.get("setup_base_id") or shot.get("setup_id"))
        if fut is not None and not fut.done():
            fut.set_result(url)

    async def _setup_ref(shot):
        """(anchor_text, extra_ref) for a non-owner shot whose setup already has
        an anchor frame. Empty for owners, unknown setups, and failed anchors.
        Looks up setup_anchors by BASE family (setup_base_id) so a size-variant
        shot like B-CU shares SETUP B's anchor frame/background instead of
        starting its own, unmatched room (C2 item 2)."""
        sid = shot.get("setup_base_id") or shot.get("setup_id")
        if not sid or shot.get("setup_anchor_owner"):
            return "", []
        fut = setup_anchors.get(sid)
        if fut is None:
            return "", []
        try:
            anchor_url = await asyncio.wait_for(asyncio.shield(fut), timeout=600)
        except (asyncio.TimeoutError, Exception):  # noqa: BLE001 — anchor is best-effort
            return "", []
        return (_SETUP_ANCHOR, [anchor_url]) if anchor_url else ("", [])

    def _board(shot, board_is_last=True):
        """(anchor_text, extra_ref) when this shot is pinned to an approved board panel.
        The board ref goes LAST so _BOARD_ANCHOR's 'LAST attached reference' holds —
        unless a setup anchor follows it (board_is_last=False), which takes the LAST
        slot and the board switches to the position-free _BOARD_ANCHOR_MID wording."""
        if shot.get("board_url") and shot.get("board_panel"):
            tmpl = _BOARD_ANCHOR if board_is_last else _BOARD_ANCHOR_MID
            return tmpl.format(panel=shot["board_panel"]), [shot["board_url"]]
        return "", []

    # Stated channel style leads every frame and outranks wrong-style refs;
    # without one, the classic match-the-refs STYLE LOCK applies unchanged.
    style_prefix = _stated_style_prefix(profile)
    style_block = _STYLE_LOCK_HYGIENE if style_prefix else _STYLE_LOCK

    m = moment["master"]
    master_url, master_model = None, None
    try:
        s_anchor, s_ref = await _setup_ref(m)
        m_anchor, m_ref = _board(m, board_is_last=not s_ref)
        master_prompt = (style_prefix
                         + build_image_prompt_from_keyframe({"composition": m["description"]}, profile)
                         + style_block + m_anchor + s_anchor)
        master_url, master_model = await _gen(master_prompt, base + m_ref + s_ref)  # master first — angles anchor on it
    finally:
        _resolve_owned(m, master_url)
        if not master_url:
            # Master failed → this moment's angles never draw. Any future THEY
            # own must still resolve (None) or their setup's other shots hang.
            for a in (moment.get("angles") or []):
                _resolve_owned(a, None)
    if not master_url:
        return None
    frames = [{"role": "master", "shot_type": m["shot_type"], "description": m["description"],
               "camera_move": m.get("camera_move"), "routed_model": m.get("routed_model"),
               "routing_reason": m.get("routing_reason"), "url": master_url,
               "image_model": master_model,
               # C3 item 4: None for a speaking master (stamp_shot_durations
               # skips it on purpose — its length comes from measured speech
               # at assemble time, never this table).
               "duration_seconds": m.get("duration_seconds")}]
    angle_base = cast_refs + [master_url] + ([env_url] if env_url else [])

    async def _angle(a):
        url = None
        try:
            s_anchor, s_ref = await _setup_ref(a)
            a_anchor, a_ref = _board(a, board_is_last=not s_ref)
            ap = (style_prefix
                  + build_image_prompt_from_keyframe({"composition": a["description"]}, profile)
                  + _SAME_SUBJECT + style_block + a_anchor + s_anchor)
            url, model_used = await _gen(ap, angle_base + a_ref + s_ref)
        finally:
            _resolve_owned(a, url)
        return {"role": "angle", "shot_type": a["shot_type"], "description": a["description"],
                "camera_move": a.get("camera_move"), "routed_model": a.get("routed_model"),
                "routing_reason": a.get("routing_reason"), "url": url,
                "image_model": model_used,
                "duration_seconds": a.get("duration_seconds")} if url else None

    # All angles share the same master ref → draw them concurrently (capped by sem).
    # return_exceptions: one bad angle degrades to fewer angles, never kills the moment.
    angle_frames = await asyncio.gather(*[_angle(a) for a in moment["angles"]],
                                        return_exceptions=True)
    frames.extend([f for f in angle_frames if f and not isinstance(f, BaseException)])
    return frames


def _download(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=180) as r, open(path, "wb") as f:
        f.write(r.read())
    return path


def cast_prompt_from_story_bible(story_bible, profile) -> str | None:
    """Build a cast-sheet image prompt from the story bible's characters, so a video
    with no locked cast can still anchor coverage. Returns None if there's nothing to
    build from (caller then needs an explicit cast_url or cast_prompt)."""
    if not story_bible:
        return None
    chars = story_bible.get("characters") or []
    lines = []
    for c in chars:
        cid = (c.get("id") or "character").replace("_", " ")
        look = c.get("costume") or c.get("description") or ""
        if look:
            lines.append(f"{cid.upper()}: {look}")
    if not lines:
        return None
    return (f"Character reference cast sheet. {profile.visual_style_directive} "
            f"A clean reference sheet on a neutral grey background showing each character "
            f"full-body, labeled with their name, with identical lighting and art style "
            f"across all of them: " + " | ".join(lines) +
            ". No text other than the character name labels.")


async def resolve_cast_url(cast_url, image_client, *, cast_prompt=None, story_bible=None,
                           profile=None, aspect="16:9", outdir=None, model_override=None) -> str | None:
    """A locked cast wins; otherwise auto-build a cast sheet (from cast_prompt, else the
    story bible) so coverage always has an anchor. Returns the cast URL or None.

    model_override: honors videos.image_model_override for the auto-built cast sheet too
    (via shared.clients.image_model_router) — GPT Image 2 stays the default + fallback."""
    if cast_url:
        return cast_url
    cp = cast_prompt or cast_prompt_from_story_bible(story_bible, profile or load_profile({}))
    if not cp:
        return None
    print(f"No locked cast — auto-building a cast sheet ({model_override or 'GPT Image 2'}) ...", flush=True)
    url, _model_used = await generate_scene_image_for_model(image_client, model_override, cp, aspect_ratio=aspect)
    if url and outdir:
        try:
            _download(url, os.path.join(outdir, "0_cast_sheet.png"))
        except Exception:
            pass
    if url:
        print(f"  cast sheet: {url}", flush=True)
    return url


def enforce_shot_budget(moments: list, max_moments: int, angles_max: int,
                        max_frames: int = None) -> list:
    """HARD shot budget (D1): the directive prompt ASKS for at most max_moments
    and angles_max angles, but the planner is an LLM and overshoots (observed
    live: 17 moments / 35 frames against a 12/0 budget). Enforce in code BEFORE
    any drawing spend: trim extra angles per moment, then drop tail moments past
    the cap. Dialogue lines are never lost — the caller's reconcile folds
    overflow turns onto the last speaking shot.

    max_frames (optional) is a TOTAL frame ceiling on top of the per-moment
    caps (Ryan's channel pacing rule, e.g. ≤40 shots for a ~2-min film):
    angles are stripped from the tail moments first — masters (the lip-sync
    units and story beats) are never sacrificed for an angle."""
    planned = sum(1 + len(m.get("angles") or []) for m in moments)
    for m in moments:
        if isinstance(m.get("angles"), list) and len(m["angles"]) > angles_max:
            m["angles"] = m["angles"][:angles_max]
    if len(moments) > max_moments:
        moments = moments[:max_moments]
        for i, m in enumerate(moments, start=1):
            m["moment_number"] = i
    if max_frames:
        total = sum(1 + len(m.get("angles") or []) for m in moments)
        for m in reversed(moments):
            while total > max_frames and m.get("angles"):
                m["angles"].pop()
                total -= 1
        while total > max_frames and len(moments) > 1:
            moments.pop()  # masters-only still over the ceiling — drop tail moments
            total -= 1
    budgeted = sum(1 + len(m.get("angles") or []) for m in moments)
    if budgeted < planned:
        print(f"  [budget] planner wanted {planned} frames — trimmed to {budgeted} "
              f"(max {max_moments} moments, {angles_max} angles each"
              + (f", {max_frames} frames total" if max_frames else "") + ")", flush=True)
    return moments


async def run_coverage(beat_text, image_client, *, outdir, cast_url=None, cast_prompt=None,
                       video_title="", profile=None, story_bible=None, beat_scenes=None,
                       env_url=None, image_prompts=None, directive_text=None,
                       anthropic_client=None, directive_model=None,
                       max_moments=3, angles_min=2, angles_max=4, max_frames=None,
                       aspect="16:9", resolution=os.getenv("COVERAGE_STILL_RESOLUTION", "1K"),
                       board_urls=None, board_panel_total=None, model_override=None,
                       render_style=None, video_model_id=None, camera_mode=None,
                       props=None, progress_callback=None,
                       allow_auto_cast_generation=True) -> dict:
    """Build coverage for one scene/beat: directive -> parse -> matched frames per moment.
    A locked cast (cast_url) wins. Legacy callers auto-build a cast sheet from the
    story bible (or cast_prompt) so coverage has a character anchor. Approval-bound
    callers may set allow_auto_cast_generation=False; that forbids the auxiliary
    provider call and draws the approved coverage frames without a cast reference.
    Saves frames + coverage.json locally with angle/shot-type metadata. No DB writes
    (storing into Image records is Phase 2, where the animator consumes them).

    model_override: videos.image_model_override ('nano-banana-2' | 'gpt-image-2' | 'z-image' |
    None). Threaded down to every frame draw via generate_coverage_frames/_gen_ref (the shared
    shared.clients.image_model_router resolver) AND to the cast-sheet auto-build below — GPT
    Image 2 stays the default and the content-policy/failure fallback either way.

    render_style/video_model_id (C13b): videos.render_style ('animated' | 'realistic' | None)
    and videos.video_model — the IMAGE model_override above never mixes with these, they're
    the separate CLIP-model routing guardrail, passed straight through to plan_camera_moves()
    (shot-plan time, before any frame is drawn) -> shared.model_router.route_shot_model().

    props (C4): the matched environment's canonical prop manifest (list of {name, position},
    video_environments.props via coverage_to_app._approved_envs/_match_scene_env), or None.
    When present, apply_prop_manifest appends it VERBATIM to every shot's draw prompt below —
    the same manifest text render_prop_manifest renders into the beat prompt and the redraw/
    repair prompt (contract-triangle law). None is today's behavior, unchanged. Also threaded
    into plan_moments_deterministic (insert-framing fix): an INSERT floor shot's close-up
    subject is rotated in from this same manifest instead of a generic hands+prop fallback.

    board_panel_total (C7 fix (a), legacy-sheet guard): the TRUE panel count the
    approved sheets in `board_urls` were planned with, read back from persisted
    bookkeeping by the caller (coverage_to_app._stored_sheet_panel_total, off
    scripts.storyboard_prompts) — never re-derived here. None means "unknown"
    (no prior gate, or an old row with nothing parseable) and preserves today's
    anchor-unconditionally behavior. When it disagrees with what THIS run just
    recomputed for the same directive, the sheets were planned by an older
    pipeline (before floors/variety existed, or before they ran in the sheet
    path too) — anchoring to their panel numbers would pin frames to the WRONG
    approved panel, so anchoring is skipped for the scene instead (composed
    unanchored — honest degradation, not silent wrong-panel composition)."""
    profile = profile or load_profile({})
    os.makedirs(outdir, exist_ok=True)
    if allow_auto_cast_generation:
        cast_url = await resolve_cast_url(
            cast_url,
            image_client,
            cast_prompt=cast_prompt,
            story_bible=story_bible,
            profile=profile,
            aspect=aspect,
            outdir=outdir,
            model_override=model_override,
        )
    if not cast_url and allow_auto_cast_generation:
        return {"error": "no cast: provide cast_url, cast_prompt, or a story_bible with characters"}
    if directive_text is None:
        directive_text = await generate_coverage_directive(
            beat_text, video_title, profile, story_bible, beat_scenes, image_prompts or [],
            max_moments=max_moments, angles_min=angles_min, angles_max=angles_max,
            anthropic_client=anthropic_client, model=directive_model)
    with open(os.path.join(outdir, "directive.txt"), "w") as f:
        f.write(directive_text)

    # C7 fix (a): parse -> budget -> floors -> variety, all via the ONE shared
    # deterministic pipeline coverage_to_app.py's sheet-planning path now
    # imports and runs too (plan_moments_deterministic) — the two can no
    # longer silently diverge on the scene's final shot sequence. verbose=True
    # preserves this function's existing progress lines for the floors/
    # variety passes, unchanged from before this refactor. props is threaded
    # through here (PICTURES path only, same as apply_prop_manifest below) so
    # the INSERT floor can pick a real manifest prop as its detail subject.
    moments = plan_moments_deterministic(directive_text, max_moments, angles_max,
                                         max_frames=max_frames, verbose=True, props=props)
    if not moments:
        return {"error": "no moments parsed from directive", "directive_chars": len(directive_text)}

    # FACING LAW drift ALARM (rule 5g, D3-63) — warning-only, same reasoning as
    # check_prop_manifest_consistency below. MUST run here, on the freshly
    # parsed descriptions, before any lock tail below is appended (the axis
    # tail alone puts "looking frame-RIGHT" on every shot in the scene, which
    # would otherwise swamp this check with false positives).
    check_facing_law_compliance(moments)

    # SET-DRESSING LOCK: the planner declares the scene's fixed props once on the
    # [SET | ...] line; stamp it into EVERY shot's image prompt. Per-shot prompts
    # that stay silent about props let the image model invent them — observed
    # live (PocoAPoco kitchen): "cram session" phrasing conjured books/laptops in
    # some panels while the food vanished and reappeared between neighbours.
    #
    # Insert-framing fix: this tail used to be the SAME text for every shot,
    # INSERT included — "...AND CHARACTER BLOCKING..." pulled both
    # characters' body positions back into an insert's prompt, fighting the
    # tight/no-faces framing the INSERT floor above just wrote (nothing then
    # told the image model to actually frame close). An INSERT shot still
    # needs the scene's location/lighting/palette continuity — just not the
    # bodies — so it gets its own shorter tail instead.
    set_line = parse_set_dressing(directive_text)
    if set_line:
        tail = f"Set dressing and character blocking, identical in every shot of this scene: {set_line}."
        insert_tail = (f"Set dressing continuity with the rest of this scene (lighting, palette, "
                       f"surfaces), identical throughout: {set_line}. This is a detail insert — "
                       f"no faces visible, detail only.")
        for m in moments:
            for shot in [m["master"], *(m.get("angles") or [])]:
                this_tail = insert_tail if _shot_tag(shot) == "INSERT" else tail
                shot["description"] = f"{shot['description'].rstrip('. ')}. {this_tail}"
        print("  🪑 set-dressing lock applied to every shot", flush=True)

    # SCREEN-DIRECTION LOCK (rule 5d): stamp the axis contract into every
    # shot's image prompt too — each frame is generated independently, so the
    # per-scene invariant must ride on each one or singles/OTS shots drift to
    # the wrong side of frame and the cut flips.
    axis_line = parse_axis_line(directive_text)
    if axis_line:
        tail = (f"Screen-direction lock, identical in every shot of this scene: {axis_line}. "
                "Never mirror or flip the composition.")
        for m in moments:
            m["master"]["description"] = f"{m['master']['description'].rstrip('. ')}. {tail}"
            for a in m.get("angles") or []:
                a["description"] = f"{a['description'].rstrip('. ')}. {tail}"
        print("  🎬 screen-direction lock applied to every shot", flush=True)

    # STAGING LOCK (rule 5e): each frame prompt carries the whole camera kit,
    # so a shot marked (SETUP B) is drawn as that exact camera on the one
    # frozen staging — bodies can't drift closer/apart or re-stage per frame.
    setups_line = parse_setups_line(directive_text)
    if setups_line:
        tail = (f"Camera kit for this scene — the actors are PLANTED and never move; every "
                f"shot is one of these setups viewing the same frozen staging: {setups_line}.")
        for m in moments:
            m["master"]["description"] = f"{m['master']['description'].rstrip('. ')}. {tail}"
            for a in m.get("angles") or []:
                a["description"] = f"{a['description'].rstrip('. ')}. {tail}"
        print("  📷 staging/setup lock applied to every shot", flush=True)

    # FACING LOCK (rule 5g's contract-triangle repair leg, D3-63): a shot
    # that structurally carries the moment's expression (_carries_facing_law
    # — a speaking master, a (REACTION) angle, or any MCU/CU/ECU) gets the
    # facing requirement stamped into its OWN draw prompt, not just left to
    # the planner's memory of rule 5g. Same reasoning as the SEQUENCE LOCK
    # below: assets.image_prompt is stamped verbatim from this same text, so
    # a later manual redraw_asset_image repair call inherits the requirement
    # too instead of silently losing it.
    facing_tail = ("Facing lock: this shot's expression is the point — the face must be readable "
                   "to the lens (face-to-camera/three-quarter, or an explicit look-back with the "
                   "head turned to camera) even as movement or axis eyeline holds; never a shot "
                   "where the face is simply turned away.")
    n_facing = 0
    for m in moments:
        for shot in [m["master"], *(m.get("angles") or [])]:
            if _carries_facing_law(m, shot, shot is m["master"]):
                shot["description"] = f"{shot['description'].rstrip('. ')}. {facing_tail}"
                n_facing += 1
    if n_facing:
        print(f"  🙂 facing lock applied to {n_facing} expression/dialogue shot(s)", flush=True)

    # SEQUENCE LOCK (D3-53b, rule 4b's contract-triangle repair leg): every
    # per-shot draw prompt below is stamped from moments[i]["master"/"angles"]
    # ["description"], and assets.image_prompt (store_scene) is stamped
    # VERBATIM from that same text — so whatever lands here also becomes the
    # base prompt for a later manual redraw_asset_image repair call. Before
    # this, a single shot's draw/redraw prompt had ZERO awareness of its
    # neighbours: nothing stopped a lone frame (or a repaired one) drifting
    # out of the causal chain rule 4b asks the planner for, or silently
    # dropping a location's bridge on a solo redraw. Stamp each shot with its
    # position in the chain and the previous moment's summary — cheap,
    # deterministic, code-rendered (never a fresh LLM paraphrase), same
    # pattern as the SET/AXIS/STAGING locks above it.
    for i, m in enumerate(moments):
        seq_bits = [f"Moment {i + 1} of {len(moments)} in this scene's causal chain"]
        if i > 0:
            seq_bits.append(f'following directly from: "{moments[i - 1]["summary"]}"')
        seq_tail = "; ".join(seq_bits) + "."
        for shot in [m["master"], *(m.get("angles") or [])]:
            shot["description"] = f"{shot['description'].rstrip('. ')}. {seq_tail}"
    print("  🔗 sequence/causal-chain lock applied to every shot", flush=True)

    # NOT BUILT — an adjacent-panel LOCATION-JUMP gate (D3-53b contract-triangle
    # third leg): today's schema has no per-moment location field to check.
    # [SET | ...] declares ONE fixed location for the WHOLE scene (parse_set_
    # dressing, above) and moments carry no analogous per-moment slot — so
    # "does moment i's location differ from moment i-1's" isn't a structured
    # comparison, only a fuzzy match against free-text shot prose, which
    # check_prop_manifest_consistency's own docstring (below) already rules
    # out as unreliable for this exact reason. A real gate needs a per-moment
    # location field added to parse_coverage's output schema plus every
    # downstream consumer updated — out of scope for this capped chunk. Left
    # for a future chunk if the deferred-verification paid proof shows rule
    # 4b's prose alone isn't enough.

    # PROP MANIFEST LOCK (C4): the environment's canonical, code-rendered prop
    # list — authored ONCE at env-approval time, never a fresh LLM
    # paraphrase per scene (the proven drift source). Kept ALONGSIDE the
    # [SET|] lock above (not replacing it): [SET|] is the planner's own
    # per-scene read on surfaces/materials/blocking, while the manifest is
    # the environment's fixed, cross-scene prop inventory — together they
    # cover "what this beat's set dressing looks like" and "what never
    # changes about this location's movable objects."
    n_props = apply_prop_manifest(moments, props)
    if n_props:
        print(f"  🧰 prop manifest lock applied to {n_props} shot(s)", flush=True)
    # Cheap deterministic drift ALARM (not a gate): does the planner's own
    # [SET|] line agree with the fixed manifest it was handed? Warning-only,
    # logged loudly, never blocks the draw.
    check_prop_manifest_consistency(props, set_line)

    # PER-SHOT TARGET DURATIONS (C3 item 4): stamp every SILENT shot (every
    # angle, every non-speaking master) with a target duration_seconds by
    # shot size, so the assembler cuts like an editor instead of splitting a
    # fixed narration block evenly. Runs AFTER the floors above so any
    # floor-added shot gets stamped too. Speaking masters are skipped —
    # their clip length comes from measured speech at assemble time.
    n_durations = stamp_shot_durations(moments)
    if n_durations:
        print(f"  ⏱️ target durations stamped on {n_durations} silent shot(s)", flush=True)

    # BOARD ANCHOR: pin each shot to its numbered panel on the approved gate
    # sheet(s). Panel numbers are GLOBAL across sheets and count masters then
    # angles in moment order — the exact order the sheet-planning path draws
    # them in (same directive, same deterministic parse + budget + floors +
    # variety via plan_moments_deterministic — C7 fix (a) — so the k-th shot
    # here IS panel k on the sheets). Only sound when the caller verified the
    # sheets came from THIS directive_text; a re-planned scene passes no
    # board_urls.
    if board_urls:
        _cap = panels_per_sheet_for(directive_text)
        # BALANCED boards (Ryan, 2026-07-21): panel->sheet is no longer a
        # fixed stride ((k-1)//cap) — boards are evenly sized via
        # sheet_chunk_sizes(), the SAME function _plan_sheet_prompts chunks
        # with, so anchoring and chunking cannot disagree on boundaries.
        # _bounds[i] = the last (1-based) global panel number on sheet i.
        _total = sum(1 + len(m.get("angles") or []) for m in moments)
        # LEGACY-SHEET GUARD (C7 fix (a), layer 2): board_panel_total is the
        # panel count the approved sheets were ACTUALLY planned with, read
        # back from persisted bookkeeping (never re-derived from moments —
        # that's exactly the assumption that broke before this fix). A sheet
        # planned before floors/variety existed (or before they ran in the
        # sheet path too) shows fewer panels than today's full pipeline just
        # recomputed; anchoring to those panel numbers would pin frames to
        # the WRONG approved panel. Skip anchoring for this scene instead —
        # composed unanchored is an honest degradation; composed to the
        # wrong panel is a silent one. None means "unknown" (no prior gate,
        # or unparseable legacy bookkeeping) and preserves the prior
        # anchor-unconditionally behavior.
        if board_panel_total is not None and board_panel_total != _total:
            print(f"  ⚠️ board anchor SKIPPED: the approved sheet(s) show "
                  f"{board_panel_total} panel(s) but today's plan recomputes {_total} "
                  f"shot(s) from this same directive — a legacy/stale sheet plan. "
                  f"Composing this scene UNANCHORED rather than pinning frames to the "
                  f"wrong panels.", flush=True)
        else:
            k = 0
            _bounds, _run = [], 0
            for _size in sheet_chunk_sizes(_total, _cap):
                _run += _size
                _bounds.append(_run)
            for m in moments:
                for shot in [m["master"], *(m.get("angles") or [])]:
                    k += 1
                    si = next(i for i, b in enumerate(_bounds) if k <= b)
                    if si < len(board_urls) and board_urls[si]:
                        shot["board_url"], shot["board_panel"] = board_urls[si], k
            print(f"  📌 board anchor: {k} shots pinned to the approved sheet panels "
                  f"(panels/board: {'+'.join(str(s) for s in sheet_chunk_sizes(_total, _cap))})",
                  flush=True)

    # Camera Movement Engine: decide each shot's move NOW, before drawing, so
    # the stills are composed for their moves (storytelling formats only —
    # this path IS the storytelling pipeline; data formats never reach it).
    planned = plan_camera_moves(
        moments,
        render_style=render_style,
        video_model_id=video_model_id,
        camera_mode=camera_mode,
    )
    if planned:
        print(f"  🎥 camera engine: {planned} shots planned with a move", flush=True)

    # SETUP ANCHORS (Ryan, 2026-07-21): tag every shot with its camera-setup id
    # and make the FIRST-planned shot of each setup that setup's anchor owner —
    # its landed frame becomes the canonical room every later same-setup shot
    # copies (see _SETUP_ANCHOR / generate_coverage_frames's docstring). Plan
    # order makes the wait graph acyclic; concurrency below is unchanged (an
    # owner never waits on a setup future, so the gather still fans out).
    #
    # C2 item 2: ownership and the future dict are keyed on setup_base_id
    # (B-CU and B share the same family) rather than the full compound id,
    # so a size-variant shot awaits and attaches its BASE setup's anchor
    # frame instead of starting its own unmatched room. The full compound
    # id still rides on shot["setup_id"] for bookkeeping (consecutive-cap,
    # logging) — only the ANCHOR lookup collapses to the base family.
    # Ownership rule (simplest correct one, per the chunk spec): whichever
    # shot of a base family is planned FIRST owns that family's anchor,
    # whatever its own variant — a B-CU that happens to lead a family DOES
    # become the owner, and every later B (or B-CU) shot in that family
    # awaits it. This falls out naturally from iterating in plan order and
    # keying on the base id below; no separate "prefer the plain letter"
    # rule is applied.
    setup_anchors = assign_setup_anchors(moments)
    anchored_shots = sum(
        1 for m in moments for s in [m["master"], *(m.get("angles") or [])]
        if s.get("setup_id") and not s.get("setup_anchor_owner"))
    if anchored_shots:
        print(f"  🔗 setup anchors: {len(setup_anchors)} camera setups, "
              f"{anchored_shots} repeat shots will copy their setup's anchor frame", flush=True)

    # Draw all moments CONCURRENTLY (each: master first, then its angles in parallel),
    # with one shared semaphore capping total in-flight Kie image gens. Collapses ~12
    # strictly-serial frames into ~2 sequential steps — scene coverage goes from ~20 min
    # to a few minutes. Set COVERAGE_CONCURRENCY to tune.
    sem = asyncio.Semaphore(_COVERAGE_CONCURRENCY)
    progress_state = {
        "done": 0,
        "total": sum(1 + len(moment.get("angles") or []) for moment in moments),
        "prefix": (
            f"Scene {beat_scenes[0]}: "
            if beat_scenes and len(beat_scenes) == 1
            else ""
        ),
    }

    async def _draw_moment(moment):
        kwargs = {
            "env_url": env_url,
            "aspect": aspect,
            "resolution": resolution,
            "sem": sem,
            "model_override": model_override,
            "setup_anchors": setup_anchors,
        }
        # Keep the legacy call shape when nobody is listening. Several
        # internal callers patch this seam with a narrow fake, and progress
        # reporting should be a zero-behavior-change addition when disabled.
        if progress_callback:
            kwargs["progress_callback"] = progress_callback
            kwargs["progress_state"] = progress_state
        return await generate_coverage_frames(
            moment,
            cast_url,
            image_client,
            profile,
            **kwargs,
        )

    # return_exceptions: one moment blowing up must not kill the sibling
    # moments' gather — the scene keeps every moment that finished.
    moment_results = await asyncio.gather(*[
        _draw_moment(moment)
        for moment in moments
    ], return_exceptions=True)

    result_moments, frame_total = [], 0
    for moment, frames in zip(moments, moment_results):
        if isinstance(frames, BaseException):
            print(f"  [moment {moment['moment_number']}] errored — skipped "
                  f"({str(frames)[:120]})", flush=True)
            continue
        if not frames:
            print(f"  [moment {moment['moment_number']}] master failed — skipped", flush=True)
            continue
        for fr in frames:
            name = f"m{moment['moment_number']:02d}_{fr['role']}_{fr['shot_type'].lower()}.png"
            try:
                _download(fr["url"], os.path.join(outdir, name))
                fr["file"] = name
            except Exception:
                try:  # one more try — a single flaky download shouldn't drop a paid frame
                    _download(fr["url"], os.path.join(outdir, name))
                    fr["file"] = name
                except Exception as e:
                    print(f"  download failed {name}: {e}", flush=True)
            frame_total += 1
        result_moments.append({**moment, "frames": frames})
        print(f"  [moment {moment['moment_number']}] {len(frames)} frames "
              f"({', '.join(fr['shot_type'] for fr in frames)})", flush=True)

    out = {"video_title": video_title, "cast_url": cast_url, "moments": result_moments,
           "moment_count": len(result_moments), "frame_count": frame_total}
    with open(os.path.join(outdir, "coverage.json"), "w") as f:
        json.dump(out, f, indent=2)
    return out


# =============================================================================
# CLI
# =============================================================================

def _load_env():
    """Populate KIE/Anthropic keys from the repo .env so the clients find them."""
    for p in (os.path.expanduser("~/economy-fastforward/.env"),
              os.path.expanduser("~/economy-fastforward/storyengine/backend/.env")):
        try:
            with open(p) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith(("KIE_AI_API_KEY=", "ANTHROPIC_API_KEY=")):
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k, v.strip().strip('"').strip("'"))
        except FileNotFoundError:
            continue


def _moments_estimate(spec) -> dict:
    mm = spec.get("max_moments", 3)
    per = 1 + 3  # master + ~3 angles
    frames = mm * per
    seed = 0 if spec.get("cast_url") else 1  # cast sheet auto-built when none is locked
    total = frames + seed
    return {"moments": mm, "frames_per_moment": per, "image_gens": total,
            "est_usd": round(total * 0.05, 2),
            "note": "nano-banana-pro ~$0.05/image; confirm rate in your kie.ai dashboard."}


async def _cmd_run(spec, outdir):
    _load_env()
    from shared.clients.image_client import ImageClient
    out = await run_coverage(
        beat_text=spec.get("beat_text", ""), image_client=ImageClient(), outdir=outdir,
        cast_url=spec.get("cast_url"), cast_prompt=spec.get("cast_prompt"),
        video_title=spec.get("video_title", ""), story_bible=spec.get("story_bible"),
        beat_scenes=spec.get("beat_scenes"), env_url=spec.get("env_url"),
        image_prompts=spec.get("image_prompts"), directive_text=spec.get("directive_text"),
        max_moments=spec.get("max_moments", 3), aspect=spec.get("aspect", "16:9"))
    print(json.dumps({k: v for k, v in out.items() if k != "moments"}, indent=2))
    print(f"=== saved to {outdir} ===")


def main():
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(1)
    cmd = sys.argv[1]
    spec = json.load(open(sys.argv[2]))
    if cmd == "estimate":
        print(json.dumps(_moments_estimate(spec), indent=2))
    elif cmd == "run":
        if len(sys.argv) < 4:
            print("usage: coverage.py run <spec.json> <outdir>"); sys.exit(1)
        asyncio.run(_cmd_run(spec, sys.argv[3]))
    else:
        print(__doc__); sys.exit(1)


if __name__ == "__main__":
    main()
