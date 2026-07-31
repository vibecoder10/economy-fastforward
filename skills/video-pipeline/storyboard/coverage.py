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
from storyboard.shot_archetypes import format_archetype_menu, get_archetype  # noqa: E402
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

def _coverage_system_prompt(profile, max_moments: int, angles_min: int, angles_max: int,
                            board_rules_text: str = "") -> str:
    cg = profile.color_grade
    # quality_rules board/image scope (BOARD-LAWS.md "Runtime-editable rules"):
    # a tenant's own active board-scoped quality_rules rows, pre-composed by
    # the caller (quality_rules.compose_rules_text over quality_rules.
    # active_board_rules — a DB read that belongs in the backend layer, not
    # here). "" (every caller today, and any tenant with no board-scoped
    # rules configured) omits the block — byte-identical to before this
    # feature existed.
    board_rules_block = (
        f"\n<board_quality_rules>\n{board_rules_text.strip()}\n</board_quality_rules>\n"
        if (board_rules_text or "").strip() else "")
    # D11-1: the professional shot-archetype library (storyboard/
    # shot_archetypes.py) — a richer, OPTIONAL descriptor than the bare
    # shot_type letter code, injected the same way board_rules_block is:
    # its own labeled block, referenced by rule 27 below.
    archetype_library_block = f"\n<shot_archetype_library>\n{format_archetype_menu()}\n</shot_archetype_library>\n"
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
{board_rules_block}{archetype_library_block}
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
8) MULTIPLE LOCATIONS — SCOPE EACH SET, FORBID CROSS-CONTAMINATION (BOARD-LAWS.md L3). Most \
scenes hold one location, and the single [SET | ...] line covers them — skip this rule entirely. \
But when THIS scene's narration moves the story between two or more distinct locations (rule \
4b's BRIDGE moments), the single-location contract is not enough and is a PROVEN failure: a lock \
that reads "identical in every shot of THIS SCENE" gets applied to every panel regardless of \
location, so a corridor shot renders with bedroom furniture. Instead, for a multi-location scene: \
do NOT write a plain [SET | ...] line; write ONE [LOCSET | <Location Name> | <text>] line PER \
LOCATION instead — same content contract as [SET | ...] (fixed dressing, key surfaces, what a \
character touches or uses), scoped to that ONE location and applying ONLY to panels tagged with \
it. Tag EVERY [MOMENT n | ...] header with which location it's in, "LOCATION: <name> |" FIRST \
inside the bracket, before the one-line description — e.g. "[MOMENT 5 | LOCATION: Corridor | \
Nyla runs down the tunnel]". State explicitly, in each [LOCSET | ...] line, that its props never \
appear in a different location's panels — e.g. "These props appear ONLY in Pod panels; never in \
a Corridor panel." Cross-contamination must be forbidden explicitly, never left to implication. \
Anything a character touches, uses, or passes through (a door, a hatch, a switch) belongs to \
exactly ONE location's [LOCSET | ...] line, authored as a PERMANENT feature and made VISIBLE in \
that location's own establishing wide before any panel uses it (L7) — never introduced only in \
the panel that needs it. State its scale relative to the character and how it meets the surface \
the character arrives on (L8), and repeat both facts in every establishing wide of that location.
9) THE SET'S MATERIAL MAP, ONCE (L20). When the scene's primary set is PART TRANSPARENT and PART \
SOLID (glass panes plus a solid shell, a window wall plus interior walls, and the like), state \
which surfaces are solid and which are transparent, and where the boundary between them runs — \
ONCE, on a [MATERIAL | ...] line, never re-invented per moment. Ambiguity here is what let one \
version of a scene draw the set fully opaque and the correction draw it fully transparent, both \
wrong. If a later moment needs a property the set lacks (contrast, a mounting point, a surface \
for something to be flush-mounted in), find it inside the already-stated material map — never \
silently redefine the set to get it. Omit the [MATERIAL | ...] line for a uniformly one-material set.
10) MOTION IS LEGAL — THE PLANTED-ACTOR CONVENTION IS SCOPED TO ONE LOCATION, NOT THE SCENE (L4). \
Rule 5e's "actors are planted and never move" applies WITHIN one camera setup's staging (a \
conversation, one location) — it is NOT a rule that characters must stay in one place for the \
WHOLE scene. When a moment involves a character moving, crossing, exiting, or changing location \
(a BRIDGE moment, rule 4b), that moment's setup must be MOTION-CAPABLE: describe a move directly \
— "exits frame-right and camera holds", "runs toward the lens", "travels alongside her down the \
corridor", "camera pans to hold her as she crosses" — never freeze a moving beat into the same \
static planted-body language a seated conversation uses. A scene that is entirely action (a \
chase, an escape, a crossing) may have every setup be motion-capable; a scene that is entirely a \
planted conversation keeps rule 5e's convention throughout; most scenes mix both and must say so \
per setup.
11) FOUR CAMERA FACTS, EVERY PANEL, ALL SCREEN-RELATIVE (L5). Beyond the setup letter, every \
MASTER and ANGLE line must make FOUR facts unambiguous, stated or directly inferable from the \
sentence: (a) which side of any barrier (glass, a doorway, a screen) the lens is on, when the \
scene has one; (b) the camera's height (bed height, eye height, low tilted up, standing height); \
(c) what fraction of the frame the subject occupies (a tenth of the frame, fills the middle \
third, fills the lower two-thirds); (d) FACE VISIBILITY AS AN EXPLICIT TERM — one of: to-lens, \
three-quarter, profile, or from-behind. A close shot whose whole purpose is an expression must \
use "to-lens" or "three-quarter", never leave visibility to be inferred from body direction alone \
(rule 5g's face-readability requirement is fact (d)'s minimum bar on an expression beat, not a \
separate rule).
12) A REPEATED SETUP NAMES WHAT IT PROGRESSES FROM (L9). When a setup letter repeats (the SAME \
camera returns to cover a later beat of the same staging), its description must name the SAME \
frame side, or the SAME surface, that the earlier panel with that letter established — "THAT SAME \
frame-RIGHT pane she touched in panel 3", "still on the frame-LEFT side of the bed". An \
unqualified repeat ("pressed to the glass" with no side named) reads as the subject teleporting to \
a different spot on the set, not as continuous coverage.
13) A MOVING BODY IS TIED TO A VISIBLE LINE (L10). Any panel where the subject travels (runs, \
walks, drives) must tie their direction of travel to a visible line INSIDE THAT SAME PANEL — name \
a vanishing point or a converging structural line (a corridor's walls, a road's edges, a \
hallway's ceiling line) and state that the subject travels ALONG it, past a named shoulder or \
side. A drive direction and a vanishing point stated as two separate, unlinked facts render as \
unrelated — the body's turn floats free of the space it's supposedly moving through.
14) A SCREEN, MONITOR, WINDOW OR MIRROR IS A SECOND FRAME (L11). When the set includes one \
(declared as a permanent feature on the [SET|]/[LOCSET|] line), specify its CONTENT in every \
single panel where it's visible — what's actually showing, not just that it's on. Repeat the same \
content description (or a stated escalation — wider one instant, the same feed later) so the \
audience never watches the nested image drift between panels that show it.
15) BACKGROUND PEOPLE ARE PART OF THE SET (L12). If a panel shows a crowd, sleepers, extras, or \
any group behind the hero, state their appearance (at minimum: clothing tone, posture, state — \
asleep, still, generic) so the hero's contrast is AUTHORED, not left to luck. State population in \
DEPTH too when the container repeats in depth (stacked pods, rows, cells): only the FRONT layer \
reads clearly; anything behind that front layer falls into shadow, unreadable — and never let two \
figures render inside a single container meant for one.
16) A SHIFT OF ATTENTION NAMES WHAT'S FIXED AND WHAT MOVES (L15). When a character's attention \
turns toward another character or object without a full re-stage, state explicitly what stays \
FIXED (chair, hips, feet, the direction the wide already established) and what MOVES (head, \
shoulders, gaze) — plus the prohibition: "chairs and knees unchanged, only the head and shoulders \
turn." An unanchored phrase like "turns three-quarter toward him" reads as a full re-staging, not \
a glance, and can rotate an entire room that was never meant to move.
17) A REVERSE ANGLE CHANGES WHAT'S BEHIND THE SUBJECT (L16). On the [SETUPS | ...] line, state \
what sits BEHIND the subject for each named camera position — never carry one setup's background \
into its reverse. If a setup places the camera BETWEEN the subject and a light source or screen, \
that source is BEHIND CAMERA in that setup: it shows only as light falling on the face, never as \
an object visible behind them. Naming a screen as simultaneously in front of camera (lighting the \
subject) and behind the subject (visible in frame) is a geometric impossibility — pick one per \
setup, never both.
18) LOCK THE HEADCOUNT, AND STATE THE ARRANGEMENT FROM EACH CAMERA (L17, L22). Any panel showing \
a group states the count AS A NUMBER — "exactly five elites, never four and never six" — never \
left to be implied by a list of names. A number alone is not enough: fold WHO sits or stands \
WHERE, as seen from THIS camera position specifically, into the same flowing sentence — for \
example "five elites fill the row, Priya nearest camera at the frame-left end, then Marcus, then \
the three others receding toward frame-right" — and remember a reverse angle reads that order \
BACKWARDS, so restate the order for the reverse rather than assuming it carries over. Write this \
as ordinary descriptive prose (see rule 23) — NEVER as a labelled heading like "ARRANGEMENT: ..." \
inside the panel's own sentence. A count stated once from the front and never restated for the \
opposing angle is exactly how a figure quietly drops from a reverse wide.
19) A DISCOVERY OBJECT IS PLANTED WITHOUT BEING ANNOUNCED (L18). When a beat is built around a \
character finding or noticing something already present in the set (a hidden detail, a planted \
object), that object must be genuinely visible in the panels BEFORE it's noticed — but NOT \
emphasised: no extra light, no glow, no centred composition, no enlarging, no indicator marking it \
out, in any panel before the notice beat. It stays the exact same size and position from the \
panel where it's introduced through the panel where it's finally noticed — the SHOT SIZE changes \
as the coverage moves in, the OBJECT never does.
20) A DIEGETIC CAMERA POV IS ITS OWN SETUP, MARKED NEUTRAL (L19). When a character looks into a \
lens, mirror, screen, or camera that exists INSIDE the story, give it its own SETUP entry that \
occupies that object's exact position (e.g. mounted in the ceiling, behind the mirror's glass) and \
mark it NEUTRAL on the [SETUPS|] line — it legally breaks the axis. In that setup's panels, the \
character's eyes go DIRECTLY into camera with NO three-quarter softening — no flinch, no \
glance-away. Apply L16: the object's own housing (the lens's own casing, the mirror's frame) is \
never visible from inside itself. Give the shot the device's own optical signature (a faint barrel \
distortion for a security lens, a mirror's flat plane) so it reads as that device's view, not a \
stylistic flourish.
21) A STILL PANEL CANNOT SHOW DURATION (L21). If a beat's content is "time passes and nothing \
changes," NO panel can carry it — never write two panels with the same setup and the same staging \
as an intentional identical repeat to suggest a stretch of time. The hold belongs to the \
MOTION/EDIT layer (a longer clip on one still), not to the board. Where the narration calls for a \
stillness-holding beat, spend the panel on an ESCALATION instead: the SAME subject, but CLOSER or \
WIDER than the panel before it, so the sheet gains new information rather than repeating the same one.
22) SCENE BOUNDARIES ARE ASSIGNED, NOT CHOSEN, WHEN GIVEN (L23-L26). If this prompt includes \
INCOMING and/or OUTGOING blocks below the narration, your FIRST panel (when INCOMING is present) \
and/or LAST panel (when OUTGOING is present) of the WHOLE scene are NOT free choices — a \
film-level boundary pass assigned them, because a cut is a relationship between two scenes that no \
single scene's planner can see on its own. When INCOMING is present, your scene's very first \
MASTER must satisfy the stated relationship to the previous scene's ending panel (matching shape/ \
subject for MATCH, continuing the action and screen direction for CONTINUATION, opening on what \
was looked at for a SIGHTLINE BRIDGE, and so on per L24's six relationships) — follow its \
"specifically: ..." instruction exactly. When OUTGOING is present, plan your scene's content so \
its FINAL panel can BE the stated description — build toward it, don't fight it. Never let your \
scene's first or last panel drift from an assigned INCOMING/OUTGOING block; the scene plans only \
its MIDDLE. Absent either block (most scenes, until a film-level boundary pass exists — see the \
STATUS note at the end of BOARD-LAWS.md), plan the first and last panels exactly as before this \
rule existed.
23) INSTRUCTIONS ARE NOT CAPTIONS — EVERY PANEL BRIEF IS ORDINARY PROSE (L27). Text written to \
INSTRUCT the drawer can be RENDERED by it, as text. NEVER phrase a MASTER or ANGLE line's \
description as a labelled directive — no all-caps heading, no "WORD WORD WORD: ..." colon-led \
block, no bracketed note — anywhere inside the sentence itself. A small caption strip is drawn \
under every panel from its number and shot type ONLY; any labelled block written into a panel's \
own description gets absorbed into that strip and BAKED ONTO THE ARTWORK verbatim — proven live: \
an arrangement fact written as "ARRANGEMENT AS SEEN FROM THIS CAMERA (REVERSED): ..." printed \
itself onto the panel exactly as typed. State every fact this rule set asks for (camera facts, \
arrangement, fixed-vs-moves, material, headcount) as ONE flowing descriptive sentence about what \
is physically in the frame — never as a heading, a directive, or a note bolted onto the front of \
the sentence. The only bracketed/parenthetical tags a panel description may carry are the \
existing structural ones this scene's format already defines — "(SETUP X)", "(REACTION)", \
"(INSERT)", "(BRIDGE)" — never a new one invented to hold a fact that belongs in prose.
24) STATE WHY EVERY SHOT EXISTS, ON ITS OWN ROW, NEVER INSIDE THE SENTENCE. Immediately under \
EVERY MASTER and ANGLE line, add its own row: `PURPOSE: <kind> | <why this shot exists, one short \
clause>`. <kind> is exactly ONE of: story, action, information, emotion, spatial — pick whichever \
is closest, never invent a new word. The clause after the pipe is a plain reason a human would \
recognize — what this shot is FOR, not what it shows (the description above it already shows \
that) — e.g. "shows how Ryan gets from the pod to the corridor", "the audience needs to see her \
decide before she moves", "proves the corridor is genuinely empty before the reveal". This is \
bookkeeping for the edit, never for the frame: it lives on its OWN line, is stripped before the \
shot ever reaches the image drawer, and must NEVER be folded into the MASTER/ANGLE sentence \
itself — rule 23 above already forbids inventing a new bracket/tag inside a panel description, and \
a PURPOSE row is exactly the kind of labelled fact that rule exists to keep out of the artwork.
25) STATE HOW EVERY SHOT CUTS IN FROM WHAT CAME BEFORE, ON ITS OWN ROW (D9-6). Immediately under \
EVERY MASTER and ANGLE line's PURPOSE row, add its own row: `TRANSITION: <kind> | <bridge, only \
when the cut is not continuous>`. <kind> is exactly ONE of: opening, continuous, time_cut, \
location_cut, montage, memory — pick whichever is closest, never invent a new word. "opening" is \
only ever the scene's very first shot. "continuous" means this shot picks up the exact same \
instant/space the previous shot ended on — no bridge needed, omit the pipe and the text entirely. \
Every OTHER kind is a real cut, and needs a bridge clause after the pipe: one short phrase naming \
what carries the viewer across it — the thing that stays recognizable, or the thing that explains \
the jump, e.g. "the same hallway light fixture, now behind them" or "her hand on the same doorknob, \
hours later". Same discipline as rule 24: its OWN row, never folded into the MASTER/ANGLE sentence.
26) STATE WHAT EARLIER SHOT CAUSED THIS ONE TO EXIST, ON ITS OWN ROW (D9-7). Immediately under \
EVERY MASTER and ANGLE line except the scene's very first shot, add its own row: `CAUSED_BY: \
M<n>-MASTER` or `CAUSED_BY: M<n>-ANGLE<k>`, naming the EARLIER shot (by its moment number and \
whether it was that moment's MASTER or its k-th ANGLE, counting from 1) whose action or revelation \
is the reason this shot exists — never a shot that comes later, never this shot itself. The scene's \
very first shot is the only one allowed to skip this row (nothing precedes it to be caused by). \
Same discipline as rules 24-25: its OWN row, never folded into the MASTER/ANGLE sentence.
27) YOU MAY NAME THIS SHOT'S PROFESSIONAL ARCHETYPE, ON ITS OWN ROW (D11-1). The \
<shot_archetype_library> block above lists the working vocabulary of professional static shot \
archetypes (establishing, coverage, detail, angle, composition, specialty) — a richer descriptor \
than the bare shot_type letter code, naming not just how tight the frame is but WHICH kind of shot \
this is and why a director would reach for it. Immediately under EVERY MASTER and ANGLE line's \
CAUSED_BY row (or its TRANSITION/PURPOSE row when CAUSED_BY is absent — the scene's very first \
shot), you MAY add its own row: `ARCHETYPE: <id>`, naming the ONE archetype id from the library \
above that best matches this shot. This is OPTIONAL, not required — never invent an id that isn't \
in the library, and simply omit the row when nothing fits cleanly; an absent ARCHETYPE row is not \
an error. Same discipline as rules 24-26: its OWN row, never folded into the MASTER/ANGLE sentence \
— rule 23 already forbids inventing a new bracket/tag inside a panel description.
28) YOU MAY GIVE THIS SHOT STRUCTURED DP (DIRECTOR OF PHOTOGRAPHY) FIELDS, ON ITS OWN ROW (D11-2). \
Rule 11 above already asks you to make the camera's height, frame-fraction and lens-adjacent facts \
unambiguous IN PROSE, inside the MASTER/ANGLE sentence itself — that stays exactly as it is, every \
panel, every time. This row is ADDITIONAL, OPTIONAL, structured data alongside that prose, never a \
replacement for it: immediately under EVERY MASTER and ANGLE line's ARCHETYPE row (or its \
CAUSED_BY/TRANSITION/PURPOSE row when ARCHETYPE is absent), you MAY add its own row: `DP: \
<lens_mm> | <camera_height> | <dof>`. All three parts are independently optional, but their ORDER \
is fixed — write only the parts you have and keep the pipe for any part you skip so a LATER part \
still lands in its own slot, e.g. `DP: 35mm | eye | shallow`, `DP: 85mm | | shallow` (camera_height \
skipped), or `DP: | low |` (lens_mm and dof skipped). <lens_mm> is a plain focal length in \
millimeters with the literal 'mm' suffix, an integer roughly 10-200 (e.g. "35mm", "85mm", "135mm"). \
<camera_height> is exactly ONE of: ground, low, waist, chest, eye, high, overhead. <dof> (depth of \
field) is exactly ONE of: shallow, medium, deep. This is OPTIONAL, not required — omit the row \
entirely when you have nothing more precise to add than rule 11's own prose already states. \
ARCHETYPE SYNERGY: when this shot also carries an ARCHETYPE row, that archetype's own typical lens \
(part of its catalog entry) is a sensible DEFAULT for this row's lens_mm — match it unless this \
shot's specific staging genuinely calls for something else. Same discipline as rules 24-27: its OWN \
row, never folded into the MASTER/ANGLE sentence — rule 23 already forbids inventing a new \
bracket/tag inside a panel description.
</rules>

<output_format>
Output ONLY the coverage plan, nothing else.

First line — the scene's fixed set dressing AND geography, ONE line, concrete and visual:
[SET | the constant physical dressing of this scene (each key surface and exactly what sits on \
it) PLUS where each character stands and which way they face, e.g. "wooden island with a bowl \
of eggs, loose potatoes and onions on a cutting board; counters clear; no books, papers or \
laptop. Ryan stands at the LEFT end of the island facing Vanessa; Vanessa at the RIGHT end \
facing Ryan"]

MULTI-LOCATION SCENES ONLY (rule 8) — skip this entirely for a one-location scene: instead of the \
single [SET | ...] line above, write ONE [LOCSET | <Location Name> | <text>] line per location, \
same content contract, each ending with an explicit cross-contamination prohibition (e.g. "These \
props appear ONLY in Pod panels; never in a Corridor panel."). Then tag every [MOMENT n | ...] \
header below with "LOCATION: <name> | " immediately after "MOMENT n |" and before the one-line \
description.

MIXED-MATERIAL SETS ONLY (rule 9) — skip for a uniform-material set:
[MATERIAL | which surfaces of the set are solid and which are transparent, and where the \
boundary between them runs, stated once]

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
PURPOSE: <kind> | <why THIS shot exists, one short clause> (rule 24 — its OWN row, right under \
the MASTER line above, kind is one of story/action/information/emotion/spatial)
TRANSITION: <kind> | <bridge, omit the pipe+text for "continuous"> (rule 25 — its OWN row, right \
under the PURPOSE row, kind is one of opening/continuous/time_cut/location_cut/montage/memory)
CAUSED_BY: M<n>-MASTER or M<n>-ANGLE<k> (rule 26 — its OWN row, right under the TRANSITION row, \
naming the EARLIER shot whose action caused this one; omit entirely only for the scene's very \
first shot)
ARCHETYPE: <id> (rule 27 — OPTIONAL, its OWN row, right under the CAUSED_BY row; omit entirely \
when no id in <shot_archetype_library> fits cleanly)
DP: <lens_mm> | <camera_height> | <dof> (rule 28 — OPTIONAL, its OWN row, right under the \
ARCHETYPE row; each of the three parts is independently optional but position-fixed — keep the \
pipe for any part you skip)
- ANGLE [shot_type]: same instant, different camera — same format: setup letter, then frame \
placement + eyeline, then what the new framing emphasises. The axis still holds.
PURPOSE: <kind> | <why THIS angle exists> (rule 24 — every MASTER and ANGLE gets its own row)
TRANSITION: <kind> | <bridge, omit for "continuous"> (rule 25 — every MASTER and ANGLE gets its own row)
CAUSED_BY: M<n>-MASTER or M<n>-ANGLE<k> (rule 26 — every MASTER and ANGLE gets its own row, except \
the scene's very first shot)
ARCHETYPE: <id> (rule 27 — OPTIONAL, every MASTER and ANGLE may carry one)
DP: <lens_mm> | <camera_height> | <dof> (rule 28 — OPTIONAL, every MASTER and ANGLE may carry one)
- ANGLE [shot_type]: ...
PURPOSE: <kind> | ...
TRANSITION: <kind> | ...
CAUSED_BY: M<n>-...
ARCHETYPE: <id> (optional)
DP: <lens_mm> | <camera_height> | <dof> (optional)

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


def format_boundary_blocks(incoming: dict | None = None, outgoing: dict | None = None) -> str:
    """L23-L26 (BOARD-LAWS.md 'scene boundaries'): render the INCOMING/OUTGOING
    text a film-level boundary pass would hand a scene's planner, in the exact
    shape BOARD-LAWS.md's L23 specifies and rule 22 of _coverage_system_prompt
    tells the planner to obey. NOT the boundary pass itself — that film-level
    pass (walking every scene-to-scene seam, picking one of L24's six
    relationships, and writing the OUT/IN description for each) is out of
    scope for this chunk (see storyengine/tasks/deferred-verification.md for
    the recommended follow-up chunk). This is only the RENDERING half: given
    already-decided boundary facts, place them correctly in the prompt this
    scene's planner reads.

    incoming: {"description": "<what the previous scene's final panel showed>",
               "relationship": "<MATCH|NESTED HANDOFF|CONTINUATION|SIGHTLINE
               BRIDGE|CONTRAST|ELLIPSIS>", "instruction": "<what THIS scene's
               first panel must do about it>"} or None to omit.
    outgoing: {"description": "<what THIS scene's final panel must show>",
               "relationship": "<one of the six, from this scene's own
               perspective — how the NEXT scene opens>"} or None to omit.
    Returns "" when both are None/empty — byte-identical to before this
    feature existed for every caller that never passes them (every caller
    today)."""
    blocks = []
    if incoming and (incoming.get("description") or "").strip():
        blocks.append(
            f"INCOMING — the previous scene ended on: {incoming['description'].strip()}. "
            f"Your FIRST panel relates to it by {(incoming.get('relationship') or '').strip() or 'the stated relationship'}, "
            f"specifically: {(incoming.get('instruction') or '').strip() or 'satisfy that relationship in your opening panel.'}"
        )
    if outgoing and (outgoing.get("description") or "").strip():
        blocks.append(
            f"OUTGOING — your FINAL panel must be: {outgoing['description'].strip()}, "
            f"because the next scene opens by {(outgoing.get('relationship') or '').strip() or 'the stated relationship'}."
        )
    if not blocks:
        return ""
    return "\n\n--- SCENE BOUNDARIES (rule 22 — these are ASSIGNED, not chosen) ---\n" + "\n\n".join(blocks)


def _coverage_user_prompt(beat_text, video_title, story_bible, beat_scenes, image_prompts,
                          incoming: dict | None = None, outgoing: dict | None = None) -> str:
    parts = [f'Plan cinematic COVERAGE for "{video_title or "this scene"}".',
             f"\nScene narration:\n{beat_text.strip()}"]
    bible = _format_story_bible_for_beat(story_bible, beat_scenes or [])
    if bible:
        parts.append(f"\n--- VISUAL BIBLE (binding) ---\n{bible}\n--- END VISUAL BIBLE ---")
    if image_prompts:
        listed = "\n".join(f"  - {p}" for p in image_prompts if p)
        parts.append(f"\n--- EXISTING SHOT IDEAS (use as the moments to cover) ---\n{listed}")
    boundary_block = format_boundary_blocks(incoming, outgoing)
    if boundary_block:
        parts.append(boundary_block)
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
    incoming: dict | None = None, outgoing: dict | None = None, board_rules_text: str = "",
) -> str:
    """Run Claude to produce the coverage plan text. Returns the raw directive.
    model: pass a valid model id for a DIRECT Anthropic client (its built-in default can be
    stale); leave None to use the client's own default (e.g. the Kie-routed market model).

    incoming/outgoing (L23-L26): optional scene-boundary facts from a film-level boundary
    pass — see format_boundary_blocks. None (the default, every caller today) omits the
    SCENE BOUNDARIES block entirely, byte-identical to before this feature existed.

    board_rules_text (quality_rules board/image scope): pre-composed active board-scoped
    quality-rule text (quality_rules.compose_rules_text over quality_rules.active_board_rules
    — a backend-layer DB read; this module stays DB-free and takes the already-fetched text
    as plain data, same pattern as `profile`/`story_bible`). "" (the default) omits the
    <board_quality_rules> block entirely."""
    if anthropic_client is None:
        from shared.clients.anthropic_client import AnthropicClient
        anthropic_client = AnthropicClient()
    kwargs = dict(
        prompt=_coverage_user_prompt(beat_text, video_title, story_bible, beat_scenes, image_prompts,
                                     incoming=incoming, outgoing=outgoing),
        system_prompt=_coverage_system_prompt(profile, max_moments, angles_min, angles_max,
                                              board_rules_text=board_rules_text),
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


# D6-2: L16 (A REVERSE ANGLE CHANGES THE BACKGROUND) — the [SETUPS|...]
# line's own catalogue example already teaches the planner to write "the
# matched reverse of B" when a setup is a matched reverse pair (rule 5e).
# That phrase is the ONE place this relationship is genuinely authored —
# parsing it out is a COMPUTATION, not an invention, and is exactly what
# BOARD-PLANNER-ARCHITECTURE.md names as the target for this law
# ("Backgrounds follow from camera position"). A setup that never uses the
# phrase (a legacy plan, or a scene with no true reverse pair) parses to no
# entry — honest, not a guess.
_REVERSE_PAIR_RE = re.compile(
    r"\b([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)?)\s*:\s*[^;]*?\b(?:the\s+)?matched\s+reverse\s+of\s+"
    r"([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)?)", re.IGNORECASE)


def parse_reverse_setup_pairs(setups_line: str | None) -> dict:
    """{setup_id: reverse_partner_id}, populated in BOTH directions, parsed
    from the [SETUPS|...] line's "the matched reverse of X" phrasing. Empty
    dict when the line has no such phrase — callers (apply_reverse_
    background_lock, apply_group_arrangement_lock) treat that as "no
    computed pairing available for this scene" and fall back to a baked
    reminder/repeat stamp instead of the fully computed flip."""
    pairs: dict = {}
    for m in _REVERSE_PAIR_RE.finditer(setups_line or ""):
        a, b = m.group(1).upper(), m.group(2).upper()
        pairs[a] = b
        pairs.setdefault(b, a)
    return pairs


# =============================================================================
# BOARD LAWS (storyengine/BOARD-LAWS.md) — multi-location + material-map
# directive schema. Additive and byte-compatible: a single-location plan
# keeps using the plain [SET | ...] line (_SET_RE/parse_set_dressing,
# unchanged above); a MULTI-location plan ALSO carries one [LOCSET |
# <name> | <text>] block per location (a deliberately different keyword
# from [SET | ...] so the two can never collide in the same regex, and a
# legacy single-location directive that has never seen this feature parses
# byte-identically to before it existed — parse_location_sets returns {}).
# =============================================================================
_LOCSET_RE = re.compile(r"\[LOCSET\s*\|\s*([^|\]]+?)\s*\|\s*([^\]]+)\]", re.IGNORECASE)
_MATERIAL_RE = re.compile(r"\[MATERIAL\s*\|\s*([^\]]+)\]", re.IGNORECASE)
# A moment header may carry an optional "LOCATION: <name> |" prefix INSIDE
# its own [MOMENT n | ...] bracket (parse_coverage strips this out of the
# summary text and stores it as moment["location"]) — e.g. "[MOMENT 5 |
# LOCATION: Corridor | Nyla runs down the tunnel]". No new top-level regex
# needed; _MOMENT_RE (above) already captures the whole bracket body.
_MOMENT_LOCATION_RE = re.compile(r"^\s*LOCATION\s*:\s*([^|]+?)\s*\|\s*(.*)$", re.IGNORECASE | re.DOTALL)


def parse_location_sets(directive_text: str) -> dict:
    """L3 (LOCATION SCOPING): every [LOCSET | <name> | <text>] block in the
    plan, in the order they appear — {location_name: set_text}. Empty dict
    for a legacy/single-location plan that carries no LOCSET blocks at all
    (the normal case today; callers fall back to parse_set_dressing's single
    scene-wide [SET | ...] line, unchanged). Duplicate location names keep
    the LAST occurrence (a planner correcting itself mid-output)."""
    out: dict = {}
    for m in _LOCSET_RE.finditer(directive_text or ""):
        out[m.group(1).strip()] = m.group(2).strip()
    return out


def parse_material_map(directive_text: str) -> str | None:
    """L20 (MATERIAL MAP): the plan's [MATERIAL | ...] line — which surfaces
    of the set are solid and which are transparent, and where the boundary
    runs. None when the planner omitted it (a set with no mixed-material
    property, or a legacy plan predating this law)."""
    m = _MATERIAL_RE.search(directive_text or "")
    return m.group(1).strip() if m else None


def _norm_env_name(s: str) -> str:
    """Lowercase and collapse punctuation/dashes to single spaces — mirrors
    coverage_to_app._norm_env_text so a video_environments.name row matches
    a directive's LOCSET header regardless of case/dash differences."""
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def canonical_material_line(canonical_envs: list | None, location_sets: dict,
                            matched_env: dict | None) -> str:
    """D6-1c (L20 — MATERIAL MAP, PICTURES path): the SAME canonical-wins-
    over-prose precedence coverage_to_app._canonical_material_line already
    gives the $0.05 sheet PREVIEW, mirrored here so run_coverage's REAL
    per-shot draw prompts read video_environments.material_map (migration
    142) too — never only the planner LLM's own [MATERIAL | ...] line.

    Returns "" (never invents) when no canonical material_map exists
    anywhere relevant, so run_coverage's existing parse_material_map(...)
    fallback fires unchanged. NULL-safe by construction: every
    video_environments row in production today has material_map NULL
    (confirmed live, 38 rows / 0 populated), so this returns "" for all of
    them and behavior is byte-identical to before this function existed.

    Multi-location scene (location_sets non-empty): one verbatim clause per
    LOCSET name with a matching approved environment carrying a
    material_map — same KNOWN GAP as the preview's twin (a location with no
    canonical entry is simply omitted, never mixed with an LLM clause for
    the same block).

    D6-6e fix (mirrors coverage_to_app._canonical_material_line's identical
    fix — kept in sync so the two never diverge): _find used to require
    EXACT normalized equality between a LOCSET key and an approved
    environment's name, so a key phrased with a leading article or extra
    prose ("The Elite Viewing Hall") silently failed to match "Elite
    Viewing Hall" and that location's material dropped out while a
    plainer-named sibling ("Pod") matched and appeared alone. Now matches
    the same way _match_scene_env-adjacent header matching does elsewhere:
    the approved name must appear as a whole, space-bounded phrase WITHIN
    the LOCSET key's normalized text, not be identical to it.

    Single-location scene: matched_env's material_map, or "" if none."""
    def _find(name: str) -> str:
        padded = f" {_norm_env_name(name)} "
        for e in (canonical_envs or []):
            n = _norm_env_name(e.get("name") or "")
            if n and f" {n} " in padded:
                return (e.get("material_map") or "").strip()
        return ""

    if location_sets:
        parts = []
        for loc in location_sets:
            mm = _find(loc)
            if mm:
                parts.append(f"{loc.upper()}: {mm}")
        return " ".join(parts)
    if matched_env:
        return (matched_env.get("material_map") or "").strip()
    return ""


def _env_locks_text(row: dict) -> str:
    """D9-3b (migration 152, PICTURES path): join an environment row's
    architecture_lock + lighting_time_weather_lock + palette_lock into ONE
    verbatim clause, skipping whichever is empty/NULL. Mirrors
    coverage_to_app._env_locks_text's join-skip-empty pattern exactly, kept
    in sync by hand rather than imported — this module is the one
    coverage_to_app.py imports FROM (see its own `from storyboard.coverage
    import (...)`), never the reverse, the same boundary
    canonical_material_line already respects for material_map above.
    "" when none of the three are populated."""
    return "; ".join(p for p in (
        (row.get("architecture_lock") or "").strip(),
        (row.get("lighting_time_weather_lock") or "").strip(),
        (row.get("palette_lock") or "").strip(),
    ) if p)


def canonical_environment_locks_line(canonical_envs: list | None, location_sets: dict,
                                     matched_env: dict | None) -> str:
    """D9-3b (Custom Film EnvironmentLock harvest, migration 152 — PICTURES
    path): the SAME canonical-wins precedence canonical_material_line gives
    material_map, one clause over, for architecture_lock/lighting_time_
    weather_lock/palette_lock. Mirrors coverage_to_app._canonical_
    environment_locks_line's exact shape (same multi-location loop/single-
    location fallback, same whole-word _find matcher) so run_coverage's
    REAL per-shot draw prompts read video_environments' three lock columns
    too — the same data canonical_envs/matched_env already carry today for
    material_map (coverage_to_app._approved_envs' SELECT was extended to
    fetch all three lock columns in D9-3, migration 152 — no new plumbing
    needed here, only this reader).

    Returns "" (never invents) when no canonical lock text exists anywhere
    relevant. Unlike material_map there is no planner-LLM equivalent line
    to fall back to (no [LOCKS | ...] directive tag exists in the coverage
    grammar) — "" simply omits the ENVIRONMENT LOCKS block entirely below,
    byte-identical to every video before migration 152 and every video
    whose environments haven't been re-approved since (locks NULL).

    Multi-location scene (location_sets non-empty): one verbatim clause per
    LOCSET name with a matching approved environment carrying locks — same
    KNOWN GAP canonical_material_line documents (a location with no
    canonical locks is simply omitted from this string).

    Single-location scene: matched_env's joined locks, or "" if none."""
    def _find(name: str) -> str:
        padded = f" {_norm_env_name(name)} "
        for e in (canonical_envs or []):
            n = _norm_env_name(e.get("name") or "")
            if n and f" {n} " in padded:
                return _env_locks_text(e)
        return ""

    if location_sets:
        parts = []
        for loc in location_sets:
            lx = _find(loc)
            if lx:
                parts.append(f"{loc.upper()}: {lx}")
        return " ".join(parts)
    if matched_env:
        return _env_locks_text(matched_env)
    return ""


def _split_moment_location(raw_summary: str) -> tuple:
    """Strip an optional 'LOCATION: <name> | ' prefix off a [MOMENT n | ...]
    bracket's captured text. Returns (location_or_None, remaining_summary).
    A moment with no LOCATION prefix (every scene today, and every
    single-location scene going forward) returns (None, raw_summary)
    unchanged — byte-compatible with every plan parsed before this law."""
    m = _MOMENT_LOCATION_RE.match(raw_summary or "")
    if not m:
        return None, (raw_summary or "").strip()
    return m.group(1).strip(), m.group(2).strip()


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


def check_material_map_consistency(canonical_material: str, directive_text: str) -> int:
    """D6-1c (L20) drift ALARM — same discipline as check_prop_manifest_
    consistency above: NOT a gate, never blocks or rewrites the draw, just
    logs loudly. A canonical-vs-emitted comparison is technically canonical
    on one side, but the OTHER side here is still the planner's own free
    prose ([MATERIAL | ...]), and per the standing ruling a prose-versus-
    prose (or prose-adjacent) comparison must WARN, never block — this
    path draws REAL paid pictures, so a false positive here would block a
    paying customer's build for a wording difference, not a real defect.

    Returns 1 (and logs) when BOTH a canonical material_map and the
    planner's own [MATERIAL | ...] line exist for this scene and they
    disagree (normalized substring check, cheap and deterministic — no
    LLM judgment call). Returns 0 when either side is empty (nothing to
    compare) or they agree; 0 for every video today since no
    video_environments.material_map row is populated yet (NULL-safe)."""
    if not canonical_material:
        return 0
    planner_line = parse_material_map(directive_text)
    if not planner_line:
        return 0
    norm_canonical = _norm_env_name(canonical_material)
    norm_planner = _norm_env_name(planner_line)
    if norm_canonical and norm_canonical not in norm_planner and norm_planner not in norm_canonical:
        print(f"  ⚠️ material-map drift check: the canonical map ('{canonical_material}') "
              f"disagrees with the planner's own [MATERIAL | ...] line ('{planner_line}') — "
              f"the canonical version wins the draw prompt; worth a human glance, not a "
              f"hard failure", flush=True)
        return 1
    return 0


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

# D9-1 (film-studio audit harvest): a per-shot "why this shot exists" tag,
# mirroring backend/custom_film_director.py's ShotDraft fields — progression_kinds
# (enum: story/action/information/emotion/spatial) and narrative_purpose (free
# prose). Written as its OWN metadata row directly under a shot's own dash
# line — same two-part "LABEL: part1 | part2" grammar as LINE: above, just
# per-shot instead of per-moment — e.g. "PURPOSE: spatial | shows how Ryan
# gets from the pod to the corridor". Deliberately NEVER folded into the
# shot's own description sentence: rule 23/L27 (INSTRUCTIONS ARE NOT CAPTIONS)
# forbids inventing a new bracket/tag inside a panel description (a labelled
# fact there gets absorbed into the caption strip and baked onto the artwork
# verbatim, proven live) — and this text is prose-length, not a short
# structural token like "(REACTION)", so the risk is real. _SHOT_RE's capture
# swallows everything up to the next shot/moment marker (DOTALL), so a
# PURPOSE row sitting right after a shot's own dash line lands at the TAIL of
# THIS shot's own captured text — matched here at the end (\Z) and stripped
# before the description is stored. A directive with no PURPOSE line (every
# directive before this chunk) matches nothing: parse_coverage's output is
# byte-identical to before this chunk existed.
_PURPOSE_LINE_RE = re.compile(
    r"\n\s*\*{0,2}\s*PURPOSE\s*\*{0,2}\s*:\s*([a-z]+)\s*\|\s*(.+?)\s*\Z", re.IGNORECASE | re.DOTALL)

# D9-6 (film-studio audit harvest, second harvest chunk): a per-shot "how does
# this cut in from what came before" tag, mirroring backend/
# custom_film_director.py's ShotDraft.transition_from_previous (enum: opening/
# continuous/time_cut/location_cut/montage/memory — TRANSITION_KINDS) and
# .continuity_bridge (free prose, optional — required by Custom Film's HARD
# gate whenever the kind isn't "continuous", custom_film_director.py:895-898).
# Same "own row, LABEL: part1 | part2" grammar as PURPOSE — the bridge half of
# the pipe is OPTIONAL (a "continuous" cut needs no bridge text at all, so the
# planner may omit the pipe and everything after it). A directive with no
# TRANSITION line (every directive before this chunk) matches nothing.
_TRANSITION_LINE_RE = re.compile(
    r"\n\s*\*{0,2}\s*TRANSITION\s*\*{0,2}\s*:\s*([A-Za-z_]+)\s*(?:\|\s*(.*?))?\s*\Z",
    re.IGNORECASE | re.DOTALL)

# D9-7 (film-studio audit harvest, second harvest chunk): a per-shot "which
# EARLIER shot caused this one to exist" reference, mirroring ShotDraft.
# caused_by (a tuple of earlier shot_keys, HARD-required for every non-first
# shot — custom_film_director.py:280, :882-884). The flagship coverage
# grammar has no LLM-assigned shot_key, so the reference format taught here
# is a LABEL the planner can derive purely from context it has already
# written by the time it reaches this row: "M<moment_number>-MASTER" or
# "M<moment_number>-ANGLE<k>" (k = 1-based position among that moment's own
# ANGLE lines) — never a running global shot count the planner would have to
# track across the whole scene. Single reference only (not a tuple like
# Custom Film's caused_by) — see check_shot_causality_present's docstring for
# why. A directive with no CAUSED_BY line matches nothing.
_CAUSED_BY_LINE_RE = re.compile(
    r"\n\s*\*{0,2}\s*CAUSED\s*_?\s*BY\s*\*{0,2}\s*:\s*(.+?)\s*\Z",
    re.IGNORECASE | re.DOTALL)

# D11-1 (film-studio audit follow-on, professional shot-archetype library): a
# per-shot OPTIONAL reference into storyboard.shot_archetypes.SHOT_ARCHETYPES
# — a richer descriptor than the bare shot_type letter code, naming WHICH
# professional archetype (establishing/coverage/detail/angle/composition/
# specialty) this shot most resembles. Same "own row" grammar as CAUSED_BY —
# a single id, no pipe — but unlike every prior row this one is OPTIONAL for
# the planner to write AT ALL (rule 27: "you MAY"), not just optional in its
# second half. Extracted here purely as text; validity against the catalog
# is checked separately (check_shot_archetype_valid, warn-only, D6 Ruling 1
# — no canonical vocabulary is hard-enforced against free LLM prose, but an
# ARCHETYPE id IS a deterministic claim like CAUSED_BY's label, so it can be
# checked for catalog membership even while staying warn-only for rollout).
# A directive with no ARCHETYPE line (every directive before this chunk)
# matches nothing.
_ARCHETYPE_LINE_RE = re.compile(
    r"\n\s*\*{0,2}\s*ARCHETYPE\s*\*{0,2}\s*:\s*(.+?)\s*\Z",
    re.IGNORECASE | re.DOTALL)

# D11-2 (film-studio audit follow-on, per-shot DP-as-data): the audit that
# harvested archetype identity (D11-1) found the remaining CAMERA vocabulary
# — lens, camera height, depth of field — still living ONLY as prose: the
# channel-wide LensProfile (`profile.lens_profile.focal_range`, injected once
# into <channel_style> above) and rule 11's per-panel FOUR CAMERA FACTS, whose
# own check_camera_facts_present docstring admits facts (b) camera height and
# (c) frame-fraction are "free prose with no fixed vocabulary to scan for...
# NOT mechanically checkable today". Rule 11's own prose stays exactly as
# is — this row is ADDITIONAL, OPTIONAL, structured data, not a replacement.
#
# camera_height's fixed vocabulary is a NEW controlled set, not lifted
# wholesale from rule 11 (rule 11 is deliberately free prose, so it has no
# fixed vocabulary to "match" in the literal sense) — but it reuses rule 11's
# own recognizable single words where they exist ("eye" <- rule 11's "eye
# height", "low" <- rule 11's "low tilted up") and extends with the other
# common professional heights rule 11's illustrative examples don't happen to
# name (ground/waist/chest/high/overhead), so this row can express the same
# RANGE of heights rule 11's prose already covers, just as one checkable word
# instead of a sentence.
CAMERA_HEIGHT_KINDS = ("ground", "low", "waist", "chest", "eye", "high", "overhead")
# dof (depth of field) mirrors the "shallow depth of field" phrasing already
# used elsewhere in this module (see _INSERT_FRAMING_CLAUSE below) plus the
# two other common professional terms.
DOF_KINDS = ("shallow", "medium", "deep")
DP_LENS_MIN_MM = 10
DP_LENS_MAX_MM = 200

# Same "own row" grammar as CAUSED_BY/ARCHETYPE — captured as raw text (up to
# \Z) and split into its three position-fixed slots by _parse_dp_row below,
# rather than three separate optional regex groups: a DP row's slots are
# pipe-separated and each independently optional, which a single flat regex
# with nested optional groups would make unreadable and fragile to get right
# (rule 28). A directive with no DP line (every directive before this chunk)
# matches nothing.
_DP_LINE_RE = re.compile(
    r"\n\s*\*{0,2}\s*DP\s*\*{0,2}\s*:\s*(.+?)\s*\Z",
    re.IGNORECASE | re.DOTALL)
_DP_LENS_RE = re.compile(r"^(\d{1,3})\s*mm$", re.IGNORECASE)


def _parse_dp_row(raw: str) -> tuple[int | None, str | None, str | None, str | None]:
    """Split a DP row's raw captured text (everything after "DP:") into its
    three position-fixed, independently-optional slots — lens_mm | \
    camera_height | dof (rule 28) — parsing lens_mm into an int and \
    lowercasing the other two, same "store as authored, validate separately"\
    split as shot_archetype/check_shot_archetype_valid.

    Returns (lens_mm, camera_height, dof, lens_raw). lens_mm is an int ONLY
    when the lens slot matched the taught "<digits>mm" shape exactly (any
    range check against DP_LENS_MIN_MM/DP_LENS_MAX_MM happens later, in
    check_shot_dp_valid — a matched-but-out-of-range value like "5mm" still
    becomes lens_mm=5 here, an int, so the checker can report the actual
    number). lens_raw carries the original lens-slot text ONLY when it was
    non-empty but did NOT parse into that shape (e.g. "fifty mm", "35" with
    no suffix) — otherwise lens_mm would silently become None, indistinguishable
    from "no lens value written at all". check_shot_dp_valid uses lens_raw to
    flag that malformed-but-present case; it is never persisted (not one of
    the three fields threaded into frame dicts/assets)."""
    parts = [p.strip() for p in raw.split("|")]
    parts = (parts + ["", "", ""])[:3]
    lens_part, height_part, dof_part = parts
    lens_mm, lens_raw = None, None
    if lens_part:
        lm = _DP_LENS_RE.match(lens_part)
        if lm:
            lens_mm = int(lm.group(1))
        else:
            lens_raw = lens_part
    camera_height = height_part.lower() if height_part else None
    dof = dof_part.lower() if dof_part else None
    return lens_mm, camera_height, dof, lens_raw


def _strip_shot_metadata_rows(desc: str) -> tuple[str, dict]:
    """Peels every trailing per-shot metadata row — D9-1's PURPOSE, D9-6's
    TRANSITION, D9-7's CAUSED_BY, D11-1's ARCHETYPE, D11-2's DP — off the TAIL
    of a shot's raw captured text (in whatever order the planner actually
    wrote them), before what's left is treated as the final stored
    description.

    Each row pattern anchors at \\Z (the current end of `desc`) but its
    captured text is "everything up to \\Z", so if PURPOSE's row sits ABOVE
    a still-present TRANSITION/CAUSED_BY/ARCHETYPE/DP row, a naive "try
    PURPOSE first" scan would let PURPOSE's own capture swallow those later
    rows whole (DOTALL matches across the newlines between them). To avoid
    that, every pass tries all five patterns and commits ONLY the one whose
    match STARTS LATEST in the current `desc` — i.e. the row that is actually
    sitting at the true tail right now — strips just that one row, and
    re-scans. That peels rows one at a time, tail-first, regardless of which
    of the five the planner wrote last, making extraction robust to any
    order and any subset of the five optional rows: all five, any four,
    three, two, one, or (every plan before D9-1 existed) none, which is the
    byte-compatible legacy case this function must reproduce exactly: zero
    rows in, zero rows stripped, `desc` unchanged.

    Returns (clean_description, {purpose_kind, shot_purpose, transition_kind,
    continuity_bridge, caused_by, shot_archetype, lens_mm, camera_height,
    dof}) — every value None if its row (or that row's own slot) never
    appeared."""
    meta = {"purpose_kind": None, "shot_purpose": None, "transition_kind": None,
            "continuity_bridge": None, "caused_by": None, "shot_archetype": None,
            "lens_mm": None, "camera_height": None, "dof": None}
    # _dp_lens_raw is a PARSE-ONLY artifact (leading underscore, same
    # convention as _flatten_shots' "_mi" bookkeeping key) — the original
    # lens-slot text ONLY when it was present but malformed (see
    # _parse_dp_row), used solely by check_shot_dp_valid to flag that case.
    # It is never one of the three DP fields threaded into frame dicts or
    # persisted to assets.
    meta["_dp_lens_raw"] = None
    extracted: set[str] = set()
    while True:
        candidates = []
        if "purpose" not in extracted:
            pm = _PURPOSE_LINE_RE.search(desc)
            if pm:
                candidates.append(("purpose", pm))
        if "transition" not in extracted:
            tm = _TRANSITION_LINE_RE.search(desc)
            if tm:
                candidates.append(("transition", tm))
        if "caused_by" not in extracted:
            cm = _CAUSED_BY_LINE_RE.search(desc)
            if cm:
                candidates.append(("caused_by", cm))
        if "archetype" not in extracted:
            am = _ARCHETYPE_LINE_RE.search(desc)
            if am:
                candidates.append(("archetype", am))
        if "dp" not in extracted:
            dm = _DP_LINE_RE.search(desc)
            if dm:
                candidates.append(("dp", dm))
        if not candidates:
            break
        # The candidate starting LATEST in `desc` is the one truly sitting
        # at the tail right now — commit only that one this pass.
        key, match = max(candidates, key=lambda kv: kv[1].start())
        if key == "purpose":
            meta["purpose_kind"] = match.group(1).strip().lower()
            meta["shot_purpose"] = match.group(2).strip()
        elif key == "transition":
            meta["transition_kind"] = match.group(1).strip().lower()
            bridge = (match.group(2) or "").strip()
            meta["continuity_bridge"] = bridge or None
        elif key == "caused_by":
            meta["caused_by"] = match.group(1).strip()
        elif key == "archetype":
            meta["shot_archetype"] = match.group(1).strip().lower()
        else:
            lens_mm, camera_height, dof, lens_raw = _parse_dp_row(match.group(1))
            meta["lens_mm"] = lens_mm
            meta["camera_height"] = camera_height
            meta["dof"] = dof
            meta["_dp_lens_raw"] = lens_raw
        desc = desc[:match.start()].rstrip()
        extracted.add(key)
    return desc, meta


def parse_coverage(directive_text: str) -> list[dict]:
    """Parse the coverage plan into moments. Each moment: {moment_number, summary,
    location, master:{shot_type,description}, angles:[...], speaker, line}.
    speaker/line are set only for a speaking moment (the planner assigns dialogue
    at draw time). location (L3, rule 8) is set only for a multi-location scene
    whose [MOMENT n | ...] header carries a "LOCATION: <name> | " prefix — None
    for every scene parsed before this law existed, and for any single-location
    scene going forward (byte-compatible: nothing about a legacy plan's parse
    output changes).

    Each shot dict also carries purpose_kind/shot_purpose (D9-1), transition_kind/
    continuity_bridge (D9-6), caused_by (D9-7), shot_archetype (D11-1), and
    lens_mm/camera_height/dof (D11-2) — parsed from that shot's own trailing
    metadata rows (_strip_shot_metadata_rows), all None when the
    corresponding row (or, for the DP row, that row's own slot) is absent
    (every plan before D9-1 existed for the first two pairs, before D9-6/D9-7
    for the next two, before D11-1 for shot_archetype, and before this chunk
    for the three DP fields, plus any shot the planner didn't tag going
    forward — WARN-only per D6 Ruling 1, never a hard gate, see
    check_shot_purpose_present / check_shot_transition_present /
    check_shot_transition_bridge_present / check_shot_causality_present /
    check_shot_causality_valid / check_shot_archetype_valid /
    check_shot_dp_valid)."""
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
            # D9-1/D9-6/D9-7: peel the shot's own trailing PURPOSE/TRANSITION/
            # CAUSED_BY rows (if any) off the end BEFORE what's left is
            # treated as final description text — see
            # _strip_shot_metadata_rows' docstring for why this must never
            # reach the image draw prompt.
            desc, meta = _strip_shot_metadata_rows(desc)
            shot = {"shot_type": m.group(2).strip().upper(), "description": desc, **meta}
            if m.group(1).upper() == "MASTER" and master is None:
                master = shot
            else:
                angles.append(shot)
        # A moment needs a master; angles are optional. A single-speaker dialogue
        # beat is often just ONE master shot of the speaker (one line = one shot,
        # one speaker per shot) — forcing an angle there bloated frame count and
        # made the writer cram two speakers onto one shot when lines ran out.
        if master:
            location, summary = _split_moment_location(h.group(2))
            moments.append({"moment_number": int(h.group(1)), "summary": summary,
                            "location": location,
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

# D6-6d (BOARD-LAWS.md L28 — NEVER ASSERT AN INPUT THAT IS NOT ATTACHED):
# _STYLE_LOCK's "match... the attached reference image(s)" is FALSE on the
# one call shape where it used to fire with nothing genuinely attached —
# allow_auto_cast_generation=False (the approval-bound Custom Film path)
# called before any character is locked and with no matched environment,
# so `base` (cast_refs + env_url) is empty for a MASTER shot (angles always
# carry at least the just-drawn master frame as a real attached image, so
# this gap is master-shots-only in practice — see generate_coverage_frames'
# has_refs check below, computed per-shot from the ACTUAL refs list handed
# to that shot's _gen() call, never guessed). Mirrors _sheet_header's
# has_cast_refs=False fallback (storyengine/backend/scripts/
# coverage_to_app.py) in spirit: when nothing is genuinely attached, point
# the drawer at THIS SHOT'S OWN description instead of a claimed image, and
# keep only the style-CONSISTENCY promise (never switch art style/medium
# between frames) — a promise that needs no reference image to be true.
_STYLE_LOCK_NO_REFS = (
    " STYLE LOCK: render this frame as a photoreal, live-action-style cinematic film still, "
    "exactly as described above — never 2D illustration, painting, cartoon or anime. Hold this "
    "EXACT same rendering quality and style across every frame of this film; never switch art "
    "style or medium between frames."
    + _STYLE_LOCK_HYGIENE)


def _style_block_for(style_prefix: str, refs: list) -> str:
    """The STYLE LOCK text for one specific frame's draw call (D6-6d). A
    stated channel style (style_prefix truthy) already leads the prompt and
    outranks any reference's own style, so the hygiene-only block applies
    unchanged — this branch is untouched by this fix. Without a stated
    style, the classic match-the-refs STYLE LOCK applies ONLY when `refs`
    (the ACTUAL list about to be passed to this shot's _gen() call) holds
    at least one genuinely attached image (any(refs), not bool(refs) — a
    caller can hand a list containing a lone None, e.g. cast_url=None
    normalized to [None], which must count as NOTHING attached); otherwise
    the no-refs wording fires so the prompt never claims an input that
    isn't in the call."""
    if style_prefix:
        return _STYLE_LOCK_HYGIENE
    return _STYLE_LOCK if any(refs) else _STYLE_LOCK_NO_REFS


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
_INLINE_TAG_RE = re.compile(r"\((REACTION|INSERT|BRIDGE)\)", re.IGNORECASE)


def _shot_tag(shot) -> str | None:
    """"REACTION", "INSERT" or "BRIDGE" if the shot's description carries
    that inline tag (C3 item 1; BRIDGE added for L3/L4 board-law motion/
    location-change detection), else None. A setup id is always letters/
    digits/hyphens (see _SETUP_TAG_RE), so this can never match INSIDE a
    "(SETUP X)" tag — the two regexes are structurally disjoint, not just
    separately defined."""
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


def scene_has_motion(moments: list, location_sets: dict | None = None) -> bool:
    """L4 (MOTION IS LEGAL): True when this scene contains at least one
    moving/location-changing beat — a shot tagged "(BRIDGE)" (rule 4b), or a
    genuinely multi-location scene (parse_location_sets returned 2+ named
    locations, rule 8) even if a planner slip left a BRIDGE shot untagged.
    Deterministic and cheap; the ONE shared detector the STAGING LOCK repair
    tail (run_coverage, PICTURES path) and the sheet-preview composer
    (coverage_to_app._plan_sheet_prompts) both call, so the two can never
    silently disagree on whether a scene's camera kit language should be
    the planted-conversation convention or the motion-capable one."""
    if location_sets and len(location_sets) >= 2:
        return True
    for m in moments or []:
        for shot in [m.get("master") or {}, *(m.get("angles") or [])]:
            if _shot_tag(shot) == "BRIDGE":
                return True
    return False


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


# =============================================================================
# BOARD LAWS GATE leg (storyengine/BOARD-LAWS.md "How a law becomes
# behaviour") — deterministic, warning-only checks in the SAME
# check_prop_manifest_consistency/check_facing_law_compliance pattern: never
# block or rewrite, just count and log loudly so a human catches drift the
# planner's own prose didn't prevent. Each function's docstring states
# exactly what it can and cannot catch — several BOARD-LAWS.md laws (L7, L8,
# L12, L13, L14, L15, L16, L18) are explicitly judged NOT deterministically
# checkable with today's schema (semantic/cross-panel/vision-judge
# territory) and have NO function here; see the coverage_to_app.py commit
# and this chunk's report for the full per-law GATE disposition.
# =============================================================================

_GROUP_NOUN_RE = re.compile(
    r"\b(elites?|crowd|extras?|sleepers?|onlookers?|audience|spectators?|figures|"
    r"others|group|bystanders?|passengers?)\b", re.IGNORECASE)
_NUMBER_TOKEN_RE = re.compile(
    r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|dozen)\b",
    re.IGNORECASE)
_ARRANGEMENT_TERM_RE = re.compile(
    r"\b(frame-left|frame-right|left to right|right to left|nearest camera|"
    r"nearest the camera|beyond (?:him|her|them)|end of the row|front row|back row)\b",
    re.IGNORECASE)


def check_headcount_stated(moments: list[dict]) -> int:
    """L17 (LOCK THE HEADCOUNT): flags a shot whose description names a GROUP
    (a crowd/extras/sleepers/elites/etc — _GROUP_NOUN_RE) with no NUMBER
    token anywhere in the same description (_NUMBER_TOKEN_RE, digits or
    number-words). Heuristic, not semantic: it can't confirm the STATED
    count is correct, only that SOME count is stated at all — a real miscount
    (five elites claimed, four actually drawn) is an image-level defect no
    text gate can catch; this only catches the "count omitted entirely"
    failure mode. Warning-only, mirrors check_prop_manifest_consistency."""
    warnings = 0
    for m in moments:
        for shot in [m["master"], *(m.get("angles") or [])]:
            desc = shot.get("description") or ""
            if _GROUP_NOUN_RE.search(desc) and not _NUMBER_TOKEN_RE.search(desc):
                warnings += 1
                print(f"  ⚠️ headcount check (L17): moment {m.get('moment_number')} "
                      f"({shot.get('shot_type')}) names a group with no stated number — "
                      "worth a human glance, not a hard failure", flush=True)
    return warnings


def check_group_arrangement_stated(moments: list[dict]) -> int:
    """L22 (STATE GROUP ARRANGEMENT PER CAMERA POSITION): among shots that
    already pass check_headcount_stated (a group noun AND a number both
    present), flags any with no positional/order term (_ARRANGEMENT_TERM_RE)
    — a count with no stated arrangement is exactly the pattern L22's
    provenance describes (a reverse wide instructed with an explicit "all
    five" still rendered four, because the seating order was only ever given
    from the front). Heuristic, warning-only."""
    warnings = 0
    for m in moments:
        for shot in [m["master"], *(m.get("angles") or [])]:
            desc = shot.get("description") or ""
            if (_GROUP_NOUN_RE.search(desc) and _NUMBER_TOKEN_RE.search(desc)
                    and not _ARRANGEMENT_TERM_RE.search(desc)):
                warnings += 1
                print(f"  ⚠️ group-arrangement check (L22): moment {m.get('moment_number')} "
                      f"({shot.get('shot_type')}) states a headcount but no arrangement/order "
                      "from THIS camera — worth a human glance, not a hard failure", flush=True)
    return warnings


_FACE_VIS_TERM_RE = re.compile(
    r"\b(to-lens|to lens|three-quarter|profile|from-behind|from behind|square to the lens|"
    r"face-to-camera|face to camera)\b", re.IGNORECASE)


def check_camera_facts_present(moments: list[dict]) -> int:
    """L5 (CAMERA FACTS PER PANEL), PARTIAL gate — only fact (d), face
    visibility as an explicit term, is checked here; facts (a) barrier-side,
    (b) camera height and (c) frame-fraction are free prose with no fixed
    vocabulary to scan for (a wide variety of correct phrasings exist for
    each), so they are NOT mechanically checkable today — say so plainly
    rather than pretend a keyword scan covers them. Scoped to the same shots
    _carries_facing_law already treats as expression-carrying (a speaking
    master, a REACTION angle, or any MCU/CU/ECU not tagged INSERT) — the
    shots L5's face-visibility fact actually matters for. Warning-only."""
    warnings = 0
    for m in moments:
        for shot in [m["master"], *(m.get("angles") or [])]:
            if not _carries_facing_law(m, shot, shot is m["master"]):
                continue
            desc = shot.get("description") or ""
            if not _FACE_VIS_TERM_RE.search(desc):
                warnings += 1
                print(f"  ⚠️ camera-facts check (L5): moment {m.get('moment_number')} "
                      f"({shot.get('shot_type')}) has no explicit face-visibility term "
                      "(to-lens/three-quarter/profile/from-behind) — worth a human glance, "
                      "not a hard failure", flush=True)
    return warnings


_FRAME_SIDE_TERM_RE = re.compile(
    r"\b(frame-left|frame-right|same pane|same side|same spot|same position|that same|"
    r"still on|as (?:before|in panel))\b", re.IGNORECASE)


def check_repeated_setup_frame_side(moments: list[dict]) -> int:
    """L9 (FRAME-SIDE CONTINUITY ON REPEATED SETUPS): flags the SECOND-and-
    later occurrence of a given setup id (exact id — a size variant like
    "B-CU" is its own id here, deliberately NOT collapsed to its base family,
    since L9 is about a literal camera repeat, not a same-axis punch-in)
    whose description carries no frame-side/surface continuity term
    (_FRAME_SIDE_TERM_RE). Scans shots in plan order across the whole scene
    (moments are already planner-ordered). Warning-only."""
    warnings = 0
    seen: set = set()
    for m in moments:
        for shot in [m["master"], *(m.get("angles") or [])]:
            sid = _setup_id(shot)
            if not sid:
                continue
            desc = shot.get("description") or ""
            if sid in seen and not _FRAME_SIDE_TERM_RE.search(desc):
                warnings += 1
                print(f"  ⚠️ frame-side continuity check (L9): moment {m.get('moment_number')} "
                      f"repeats SETUP {sid} with no frame-side/surface continuity term — "
                      "worth a human glance, not a hard failure", flush=True)
            seen.add(sid)
    return warnings


_MOTION_VERB_RE = re.compile(
    r"\b(runs?|running|sprints?|sprinting|drives?|driving|travels?|travell?ing|"
    r"walks? (?:away|toward)|races?|racing|dashes?|dashing)\b",
    re.IGNORECASE)
# Deliberately EXCLUDES "exits frame" — a camera-holds-while-subject-exits
# setup (L4's own example phrasing) is a static camera watching a subject
# leave, not body-vector-tied-to-a-visible-line travel; it has no vanishing
# line to anchor to and L10 does not apply to it (see check_motion_axis_
# anchor's docstring for the acceptance-target precedent).
_AXIS_ANCHOR_TERM_RE = re.compile(
    r"\b(vanishing point|vanishing line|converge[sd]?|converging|same axis|same line|"
    r"past (?:her|his|their) (?:near|far)? ?shoulder)\b", re.IGNORECASE)


def check_motion_axis_anchor(moments: list[dict]) -> int:
    """L10 (BODY VECTOR TO VISIBLE AXIS): flags a shot whose description
    reads as directional TRAVEL (_MOTION_VERB_RE — runs/drives/travels/
    exits frame/etc) but names no visible line the travel ties to
    (_AXIS_ANCHOR_TERM_RE — a vanishing point/line, a converging structural
    line, "past X shoulder"). Deliberately NOT triggered by a bare
    "(BRIDGE)" tag alone: a bridge/threshold moment (climbing through a
    doorway, stepping onto a walkway) is not always body-vector travel in
    L10's sense — the acceptance target's own approved threshold panel
    (scene1_board_prompt_CORRECTED_v3.txt panel [7]) carries no vanishing-
    line language and is correct as written; a corridor RUN a few panels
    later is where L10 actually bites. Warning-only, heuristic (motion-verb
    detection is prose-pattern matching, not a semantic read of the shot)."""
    warnings = 0
    for m in moments:
        for shot in [m["master"], *(m.get("angles") or [])]:
            desc = shot.get("description") or ""
            if _MOTION_VERB_RE.search(desc) and not _AXIS_ANCHOR_TERM_RE.search(desc):
                warnings += 1
                print(f"  ⚠️ motion-axis check (L10): moment {m.get('moment_number')} "
                      f"({shot.get('shot_type')}) reads as a moving beat with no visible-line "
                      "anchor for the travel direction — worth a human glance, not a hard "
                      "failure", flush=True)
    return warnings


_WS_ONLY_PUNCT_RE = re.compile(r"[^a-z0-9 ]+")


def check_no_duplicate_panels(moments: list[dict]) -> int:
    """L21 (A BOARD CANNOT SHOW DURATION): flags a shot whose normalized
    description (lowercased, punctuation stripped) is BYTE-IDENTICAL to an
    earlier shot's in the same scene — the exact failure the law's
    provenance describes (two panels deliberately specified as identical to
    express a held moment). MUST run on the freshly-parsed descriptions,
    same ordering constraint as check_facing_law_compliance — a lock tail
    appended below (SET/AXIS/STAGING/...) is identical scene-wide text and
    would swamp this check with false positives if it ran after them.
    Exact-match only (no fuzzy/near-duplicate detection — that needs a
    similarity threshold this chunk did not tune); a near-identical-but-not-
    exact repeat is NOT caught here, only the literal duplicate. Warning-only."""
    warnings = 0
    seen: dict = {}
    for m in moments:
        for shot in [m["master"], *(m.get("angles") or [])]:
            norm = _WS_ONLY_PUNCT_RE.sub(" ", (shot.get("description") or "").lower())
            norm = " ".join(norm.split())
            if not norm:
                continue
            if norm in seen:
                warnings += 1
                print(f"  ⚠️ duplicate-panel check (L21): moment {m.get('moment_number')} "
                      f"({shot.get('shot_type')}) repeats moment {seen[norm]}'s panel text "
                      "verbatim — a still can't show duration; escalate (closer/wider) "
                      "instead of repeating — worth a human glance, not a hard failure",
                      flush=True)
            else:
                seen[norm] = m.get("moment_number")
    return warnings


def check_material_map_present_when_mixed(directive_text: str) -> int:
    """L20 (DEFINE THE SET'S MATERIAL MAP ONCE): if this scene's set text
    (the single [SET|...] line, or every [LOCSET|...] block) mentions BOTH a
    transparent-surface term (glass/transparent/window/clear pane) AND a
    solid-surface term (solid/opaque/wall/shell/matte) — i.e. reads as a
    mixed-material set — but the plan carries no [MATERIAL|...] line, flags
    it: this is exactly the ambiguity L20's provenance describes (a
    part-glass/part-solid set redefined a different way by every scene that
    touches it). A uniformly one-material set correctly needs no
    [MATERIAL|...] line and is never flagged. Warning-only, heuristic (a set
    can be legitimately mixed-material and still fully unambiguous in prose
    without a dedicated line; this only flags the OMISSION, not real
    ambiguity)."""
    if parse_material_map(directive_text):
        return 0
    texts = list(parse_location_sets(directive_text).values())
    single = parse_set_dressing(directive_text)
    if single:
        texts.append(single)
    transparent_re = re.compile(r"\b(glass|transparent|window|clear pane)\b", re.IGNORECASE)
    solid_re = re.compile(r"\b(solid|opaque|matte|shell)\b", re.IGNORECASE)
    warnings = 0
    for t in texts:
        if transparent_re.search(t) and solid_re.search(t):
            warnings += 1
            print("  ⚠️ material-map check (L20): a set reads as mixed transparent/solid but "
                  "no [MATERIAL | ...] line was found — worth a human glance, not a hard "
                  "failure", flush=True)
    return warnings


def check_location_scoping(moments: list[dict], location_sets: dict) -> int:
    """L3 (LOCATION SCOPING): for a multi-location scene, flags a panel
    tagged with location A whose description mentions a phrase that is
    DISTINCTIVE to a different location B — present in B's [LOCSET|...] text
    but absent from every other location's text (a cheap, no-shared-
    vocabulary proxy for "this prop belongs only to that other place"),
    capped at 6 distinctive phrases per location to keep this cheap and
    avoid noise on common words. Same "cheap deterministic direction, not
    proof of an error" discipline as check_prop_manifest_consistency: a
    shot CAN legitimately reference another location in passing prose
    ("through the glass, the corridor's blue glow") without literally
    naming a distinctive furniture phrase, so a 0 here is not proof of zero
    cross-contamination, only of none this heuristic can see. Returns 0 for
    a single-location scene (no [LOCSET|...] blocks) — nothing to scope.
    Warning-only."""
    if not location_sets or len(location_sets) < 2:
        return 0

    def _phrases(text: str) -> list[str]:
        return [p.strip().lower() for p in re.split(r"[;,]", text or "") if len(p.strip()) > 3]

    phrases_by_loc = {loc: _phrases(text) for loc, text in location_sets.items()}
    distinctive: dict = {}
    for loc, phrases in phrases_by_loc.items():
        others_text = " ".join(t.lower() for l2, t in location_sets.items() if l2 != loc)
        distinctive[loc] = [p for p in phrases if p and p not in others_text][:6]

    warnings = 0
    for m in moments:
        loc = m.get("location")
        if not loc:
            continue
        for other_loc, phrases in distinctive.items():
            if other_loc == loc:
                continue
            for shot in [m["master"], *(m.get("angles") or [])]:
                desc = (shot.get("description") or "").lower()
                for p in phrases:
                    if p in desc:
                        warnings += 1
                        print(f"  ⚠️ location-scoping check (L3): moment "
                              f"{m.get('moment_number')} tagged '{loc}' mentions '{p}', "
                              f"distinctive to '{other_loc}' — worth a human glance, not a "
                              "hard failure", flush=True)
    return warnings


_NESTED_FRAME_NOUN_RE = re.compile(r"\b(screen|monitor|mirror|feed)\b", re.IGNORECASE)
_CONTENT_BEARING_RE = re.compile(
    r"\b(shows?|showing|shown|displays?|displaying|reflect(?:s|ing)?|feed of|picture of|"
    r"holding a feed)\b", re.IGNORECASE)


def check_nested_frame_content_specified(moments: list[dict]) -> int:
    """L11 (NESTED FRAMES): flags a shot whose description mentions a
    second-frame noun (screen/monitor/mirror/feed) with no content-bearing
    language nearby (shows/displays/reflects/feed of/...) — i.e. the nested
    frame is referenced but what's ON it is left unstated, the exact drift
    L11 exists to stop. Heuristic and coarse (word-proximity only, not
    "is the content genuinely consistent panel to panel" — that needs a
    vision judge). Warning-only."""
    warnings = 0
    for m in moments:
        for shot in [m["master"], *(m.get("angles") or [])]:
            desc = shot.get("description") or ""
            if _NESTED_FRAME_NOUN_RE.search(desc) and not _CONTENT_BEARING_RE.search(desc):
                warnings += 1
                print(f"  ⚠️ nested-frame check (L11): moment {m.get('moment_number')} "
                      f"({shot.get('shot_type')}) names a screen/monitor/mirror/feed with no "
                      "stated content — worth a human glance, not a hard failure", flush=True)
    return warnings


_POV_SETUP_TERM_RE = re.compile(r"\b(POV|lens'?s? own position|mirror's own)\b", re.IGNORECASE)
_INTO_CAMERA_RE = re.compile(r"\binto camera\b|\bto.?lens\b|\bsquare to the lens\b", re.IGNORECASE)


def check_pov_setup_neutral_and_into_camera(moments: list[dict]) -> int:
    """L19 (DIEGETIC CAMERA POV): flags a shot that reads as a diegetic-
    camera POV setup (_POV_SETUP_TERM_RE) but is missing either the NEUTRAL
    marker or an into-camera/to-lens eyeline term. Heuristic (keyword
    detection of "POV" is a coarse proxy for "this IS a diegetic-camera
    setup" — a scene could use the word differently); warning-only."""
    warnings = 0
    for m in moments:
        for shot in [m["master"], *(m.get("angles") or [])]:
            desc = shot.get("description") or ""
            if not _POV_SETUP_TERM_RE.search(desc):
                continue
            if "NEUTRAL" not in desc.upper() or not _INTO_CAMERA_RE.search(desc):
                warnings += 1
                print(f"  ⚠️ diegetic-POV check (L19): moment {m.get('moment_number')} "
                      f"({shot.get('shot_type')}) reads as a POV setup but is missing NEUTRAL "
                      "and/or an into-camera eyeline term — worth a human glance, not a hard "
                      "failure", flush=True)
    return warnings


_CAPTION_LEAK_RE = re.compile(r"(?:\b[A-Z]{2,}\b[ ]?){3,}:")


def check_no_caption_leaking_labels(moments: list[dict]) -> int:
    """L27 (INSTRUCTIONS ARE NOT CAPTIONS): flags a shot description that
    contains a labelled-directive pattern — three or more consecutive
    ALL-CAPS words followed by a colon (e.g. "ARRANGEMENT AS SEEN FROM THIS
    CAMERA (REVERSED): ...") — the exact live-proven failure where such text
    printed itself verbatim onto the panel's caption strip. Deliberately
    narrow (3+ caps words + colon) so it doesn't fire on legitimate emphasis
    words (NEVER, ALWAYS, NEUTRAL) or the format's own "(SETUP X)"/
    "(REACTION)"/"(INSERT)"/"(BRIDGE)" parenthetical tags, none of which are
    colon-terminated ALL-CAPS runs. Warning-only."""
    warnings = 0
    for m in moments:
        for shot in [m["master"], *(m.get("angles") or [])]:
            desc = shot.get("description") or ""
            if _CAPTION_LEAK_RE.search(desc):
                warnings += 1
                print(f"  ⚠️ caption-leak check (L27): moment {m.get('moment_number')} "
                      f"({shot.get('shot_type')}) contains an all-caps labelled directive that "
                      "will print itself onto the caption strip — rewrite as ordinary prose — "
                      "worth a human glance, not a hard failure", flush=True)
    return warnings


# =============================================================================
# D6-2 (storyengine/tasks/loop-checklist.md, PHASE D6) — NEW gates for L12,
# L15, L18, which previously had NO deterministic check at all (see the
# board-laws-build commit note: "honestly NOT built where semantic (L6, L7,
# L8, L12, L13, L14, L15, L16, L18...)"). Same warning-only discipline as
# every check_* above — LESSON from D6-1's review round: a gate may only be
# HARD when the thing it compares against is CANONICAL data or code's own
# generated text; every one of these compares planner PROSE against a
# heuristic pattern, so all three stay warning-only.
# =============================================================================

_POPULATION_DESC_RE = re.compile(
    r"\b(clothing|robes?|uniforms?|posture|asleep|stillness|generic|pale|shadow(?:s|ed)?|"
    r"stacked|depth|front layer|unreadable|silhouettes?|hooded|cloaked)\b", re.IGNORECASE)


def check_population_specified(moments: list[dict]) -> int:
    """L12 (SPECIFY THE POPULATION), NEW gate: among shots that already pass
    check_headcount_stated (a group noun AND a number both present), flags
    any with no descriptive/appearance term (_POPULATION_DESC_RE) — a count
    with no stated LOOK is exactly the pattern L12 exists to stop
    (unspecified background figures rendering pale by luck; bodies stacking
    through a transparent container until each reads as two people).
    Heuristic, warning-only."""
    warnings = 0
    for m in moments:
        for shot in [m["master"], *(m.get("angles") or [])]:
            desc = shot.get("description") or ""
            if (_GROUP_NOUN_RE.search(desc) and _NUMBER_TOKEN_RE.search(desc)
                    and not _POPULATION_DESC_RE.search(desc)):
                warnings += 1
                print(f"  ⚠️ population check (L12): moment {m.get('moment_number')} "
                      f"({shot.get('shot_type')}) states a headcount but no appearance/posture "
                      "description for the group — worth a human glance, not a hard failure",
                      flush=True)
    return warnings


_ATTENTION_SHIFT_RE = re.compile(
    r"\b(turns?\s+(?:toward|towards|to face)|glances?\s+(?:toward|towards|at)|"
    r"shifts?\s+(?:her|his|their)?\s*attention|looks?\s+(?:over|toward|towards)|"
    r"head\s+turns?)\b", re.IGNORECASE)
_FIXED_ANCHOR_STATED_RE = re.compile(
    r"\b(chairs?|hips?|feet|legs?|torso|knees?)\b[^.]{0,60}\b(fixed|unchanged|stay(?:s)?|"
    r"planted|do(?:es)?\s*not\s+move|don'?t\s+move|never\s+move)\b", re.IGNORECASE)


def check_attention_orientation_stated(moments: list[dict]) -> int:
    """L15 (SEPARATE ATTENTION FROM ORIENTATION), NEW gate: flags a shot
    that reads as a partial attention shift (_ATTENTION_SHIFT_RE — turns
    toward/glances at/shifts attention/looks toward) with no stated FIXED
    anchor term nearby (_FIXED_ANCHOR_STATED_RE — chair/hips/feet/knees
    stated unchanged) — the exact drift L15's provenance describes ("turned
    three-quarter toward him" rotating an entire room that was never meant
    to move). Heuristic and coarse: "turns toward" can legitimately describe
    a full re-stage too, so this only flags the OMISSION of an anchor term,
    never a genuine contradiction. Warning-only."""
    warnings = 0
    for m in moments:
        for shot in [m["master"], *(m.get("angles") or [])]:
            desc = shot.get("description") or ""
            if _ATTENTION_SHIFT_RE.search(desc) and not _FIXED_ANCHOR_STATED_RE.search(desc):
                warnings += 1
                print(f"  ⚠️ attention-orientation check (L15): moment {m.get('moment_number')} "
                      f"({shot.get('shot_type')}) reads as a partial attention shift with no "
                      "stated FIXED anchor (chair/hips/feet) — worth a human glance, not a hard "
                      "failure", flush=True)
    return warnings


_EMPHASIS_TERM_RE = re.compile(
    r"\b(glow(?:s|ing)?|gleam(?:s|ing)?|spotlit|spot-?lit|highlighted?|luminous|"
    r"catches?\s+the\s+light|draws?\s+the\s+eye|shimmer(?:s|ing)?)\b", re.IGNORECASE)
_DISCOVERY_VERB_RE = re.compile(
    r"\b(notices?|discovers?|spots?|catches?\s+sight\s+of|finally\s+sees?)\b", re.IGNORECASE)


def check_discovery_object_unremarked(moments: list[dict]) -> int:
    """L18 (A DISCOVERY OBJECT IS PLANTED WITHOUT BEING ANNOUNCED), NEW gate
    — deliberately coarse and SCENE-scoped, not panel-to-panel: only runs
    when the scene contains a discovery beat at all (_DISCOVERY_VERB_RE —
    notices/discovers/spots/...), then flags any shot in that same scene
    whose description carries emphasis-lighting language (_EMPHASIS_TERM_RE
    — glow/gleam/spotlit/highlighted/draws the eye/...). This CANNOT confirm
    the emphasis lands on the SAME object, or that it appears BEFORE the
    notice beat specifically — today's schema has no per-shot object
    identity or ordering-relative-to-a-named-beat to check that precisely
    (the same honest gap check_location_scoping's docstring names for a
    different law). It only flags the higher-level co-occurrence as worth a
    human's eye. Warning-only. See apply_reverse_background_lock's sibling
    functions below and this chunk's commit message for why L18 gets NO
    repair leg (the fact it protects is one-off narrative content, not a
    scene-wide constant that can be captured once and repeated)."""
    warnings = 0
    has_discovery = any(
        _DISCOVERY_VERB_RE.search(shot.get("description") or "")
        for m in moments for shot in [m["master"], *(m.get("angles") or [])]
    )
    if not has_discovery:
        return 0
    for m in moments:
        for shot in [m["master"], *(m.get("angles") or [])]:
            desc = shot.get("description") or ""
            if _EMPHASIS_TERM_RE.search(desc):
                warnings += 1
                print(f"  ⚠️ discovery-object check (L18): moment {m.get('moment_number')} "
                      f"({shot.get('shot_type')}) uses emphasis-lighting language in a scene "
                      "that also contains a discovery beat — confirm the planted object isn't "
                      "given away early — worth a human glance, not a hard failure", flush=True)
    return warnings


def check_shot_purpose_present(moments: list[dict]) -> int:
    """D9-1 (film-studio audit harvest): the dormant Custom Film director's
    ShotDraft HARD-requires narrative_purpose + progression_kinds on every
    shot (backend/custom_film_director.py:279-284) — the flagship coverage
    pipeline planned shots with no motivation at all ({shot_type,
    description} only). Ryan's ruling on the audit: harvest that schema into
    the flagship, but per the standing D6 Ruling 1 (a gate may only be HARD
    when it compares against something CANONICAL) this stays WARN-only —
    there is no canonical "correct" purpose to compare a shot's prose
    against, only whether the planner stated one at all.

    Flags any shot (master or angle) with no parsed purpose_kind AND no
    shot_purpose (the coverage system prompt's per-shot "PURPOSE: <kind> |
    <text>" row, extracted by parse_coverage — see _PURPOSE_LINE_RE). This
    WILL trip on every plan from before this chunk existed (the row simply
    never appears) and on any code-synthesized filler shot (a floor-added
    REACTION/INSERT/re-establish from enforce_reaction_insert_floors, which
    has no LLM-authored prose to draw a purpose from) — that is the intended
    signal, not a false positive: exactly the shots nobody stated a reason
    for. Warning-only, same 'worth a human glance, not a hard failure'
    discipline as every check_* above."""
    warnings = 0
    for m in moments:
        for shot in [m["master"], *(m.get("angles") or [])]:
            if not (shot.get("purpose_kind") or shot.get("shot_purpose")):
                warnings += 1
                print(f"  ⚠️ shot-purpose check (D9-1): moment {m.get('moment_number')} "
                      f"({shot.get('shot_type')}) carries no PURPOSE: line — no stated "
                      "narrative_purpose/progression_kind for this shot — worth a human glance, "
                      "not a hard failure", flush=True)
    return warnings


def check_shot_transition_present(moments: list[dict]) -> int:
    """D9-6 (film-studio audit harvest, second harvest chunk): the dormant
    Custom Film director's ShotDraft HARD-requires transition_from_previous
    on every shot (backend/custom_film_director.py:288-290, TRANSITION_KINDS
    enum: opening/continuous/time_cut/location_cut/montage/memory) — the
    flagship coverage pipeline planned shots with no cut-type signal at all.
    Ryan's ruling on the audit: harvest that schema, same warn-only
    discipline as check_shot_purpose_present (D6 Ruling 1 — no canonical cut
    type to check a shot's stated kind against, only whether one was stated).

    Flags any shot (master or angle) with no parsed transition_kind (the
    coverage system prompt's per-shot "TRANSITION: <kind> | <bridge>" row,
    rule 25, extracted by parse_coverage via _strip_shot_metadata_rows).
    Trips on every plan from before this chunk existed and on any code-
    synthesized filler shot — same intended signal as check_shot_purpose_
    present, not a false positive."""
    warnings = 0
    for m in moments:
        for shot in [m["master"], *(m.get("angles") or [])]:
            if not shot.get("transition_kind"):
                warnings += 1
                print(f"  ⚠️ shot-transition check (D9-6): moment {m.get('moment_number')} "
                      f"({shot.get('shot_type')}) carries no TRANSITION: line — no stated cut "
                      "type for this shot — worth a human glance, not a hard failure", flush=True)
    return warnings


def check_shot_transition_bridge_present(moments: list[dict]) -> int:
    """D9-6 companion check: Custom Film HARD-requires a continuity_bridge on
    any shot whose transition_from_previous isn't "continuous"
    (custom_film_director.py:895-898 — `elif not shot.continuity_bridge:
    raise error`). Softened to warn per the same D6 Ruling 1 discipline: a
    non-continuous cut with no bridge clause is worth a human glance (is the
    cut actually legible?), never a hard failure.

    Only evaluates shots that HAVE a stated transition_kind — a shot with no
    kind at all is already flagged by check_shot_transition_present above,
    and re-flagging it here for also lacking a bridge would double-count the
    same missing row. "opening" is ALSO exempt, same as "continuous" — in
    Custom Film's own model an "opening" shot is structurally always the
    scene's first (custom_film_director.py:870-874 forces continuity_bridge
    to None there; :888-890 forbids "opening" on any non-first shot), so by
    the time Custom Film's own :895-898 bridge check runs, "opening" can
    never reach it. Mirroring that faithfully means "opening" never needs a
    bridge either, not just "continuous". Flags a shot whose kind is
    anything other than "continuous"/"opening" and whose continuity_bridge
    is empty/absent."""
    warnings = 0
    for m in moments:
        for shot in [m["master"], *(m.get("angles") or [])]:
            kind = shot.get("transition_kind")
            if kind and kind not in ("continuous", "opening") and not shot.get("continuity_bridge"):
                warnings += 1
                print(f"  ⚠️ shot-transition-bridge check (D9-6): moment {m.get('moment_number')} "
                      f"({shot.get('shot_type')}) has TRANSITION: {kind} but no bridge clause — "
                      "a non-continuous cut with nothing stated to carry the viewer across it — "
                      "worth a human glance, not a hard failure", flush=True)
    return warnings


def _build_shot_causality_index(moments: list[dict]) -> list[tuple[str, dict, int]]:
    """D9-7 helper: (label, shot_dict, ordinal) for every shot in this
    scene's draw/output order — each moment's master then its angles,
    moments in plan order, same order _flatten_shots uses elsewhere.

    `label` mirrors exactly what rule 26 teaches the planner to write in a
    CAUSED_BY row: "M<moment_number>-MASTER" for a moment's master shot,
    "M<moment_number>-ANGLE<k>" for its k-th (1-based) angle — both
    derivable by the planner from context it already has by the time it
    writes that row (the moment header, and this shot's own position among
    that moment's angles), never a running global shot count it would have
    to track across the whole scene. `ordinal` is this shot's 0-based
    position in that same draw order — the ONE thing that lets
    check_shot_causality_valid tell "earlier" from "later" without caring
    what the label text looks like."""
    index: list[tuple[str, dict, int]] = []
    ordinal = 0
    for m in moments:
        mn = m.get("moment_number")
        master = m.get("master")
        if master:
            index.append((f"M{mn}-MASTER", master, ordinal))
            ordinal += 1
        for k, a in enumerate(m.get("angles") or [], start=1):
            index.append((f"M{mn}-ANGLE{k}", a, ordinal))
            ordinal += 1
    return index


def check_shot_causality_present(moments: list[dict]) -> int:
    """D9-7 (film-studio audit harvest, second harvest chunk): the dormant
    Custom Film director's ShotDraft HARD-requires caused_by on every shot
    except the scene's true first (backend/custom_film_director.py:280,
    :882-884 — `if not shot.caused_by or ...: raise error`) — the flagship
    coverage pipeline planned shots with no causal chain at all. Ryan's
    ruling: harvest that schema, warn-only per D6 Ruling 1 (no canonical
    "correct" cause to check a shot's stated reference against, only
    whether one was stated).

    Only a SINGLE caused_by reference is taught here (unlike Custom Film's
    tuple of shot_keys) — the flagship coverage grammar has no LLM-assigned
    shot_key to build a reliable multi-reference list from, and one clear
    reference is more likely to be authored correctly than a list the
    planner has to keep internally consistent; see rule 26.

    Flags any shot except the scene's very first (ordinal 0 in
    _build_shot_causality_index — the one shot Custom Film's own HARD gate
    also exempts, custom_film_director.py:870-874) with no parsed caused_by."""
    warnings = 0
    for label, shot, ordinal in _build_shot_causality_index(moments):
        if ordinal == 0:
            continue  # the scene's true first shot is allowed to be uncaused
        if not shot.get("caused_by"):
            warnings += 1
            print(f"  ⚠️ shot-causality check (D9-7): shot {label} carries no CAUSED_BY: line — "
                  "no stated earlier cause for this shot — worth a human glance, not a hard "
                  "failure", flush=True)
    return warnings


def check_shot_causality_valid(moments: list[dict]) -> int:
    """D9-7 companion check: unlike a free-prose PURPOSE clause, a CAUSED_BY
    reference is a deterministic claim — it names a SPECIFIC earlier shot by
    label, so whether that label actually exists AND actually sits earlier
    in the scene's draw order is mechanically checkable (mirrors Custom
    Film's own two-part validation, custom_film_director.py:882-884: the
    referenced shot_key must be in `seen_shot_keys`, i.e. already compiled).
    Still warn-only per D6 Ruling 1 — even a deterministic mismatch is a
    planner mistake worth a human glance, not grounds to block a draw.

    Flags a shot whose caused_by (case-insensitively) doesn't match any
    label in this scene, OR matches a label whose ordinal is NOT strictly
    earlier than this shot's own (points at itself or at a later shot)."""
    warnings = 0
    index = _build_shot_causality_index(moments)
    label_to_ordinal = {label.upper(): ordinal for label, _shot, ordinal in index}
    for label, shot, ordinal in index:
        cb = shot.get("caused_by")
        if not cb:
            continue
        target = label_to_ordinal.get(cb.strip().upper())
        if target is None:
            warnings += 1
            print(f"  ⚠️ shot-causality check (D9-7): shot {label}'s CAUSED_BY references "
                  f"'{cb}', which does not match any shot in this scene — worth a human glance, "
                  "not a hard failure", flush=True)
        elif target >= ordinal:
            warnings += 1
            print(f"  ⚠️ shot-causality check (D9-7): shot {label}'s CAUSED_BY references "
                  f"'{cb}', which is not an EARLIER shot in this scene — worth a human glance, "
                  "not a hard failure", flush=True)
    return warnings


def check_shot_archetype_valid(moments: list[dict]) -> int:
    """D11-1 (film-studio audit follow-on, professional shot-archetype
    library): unlike PURPOSE's free prose, an ARCHETYPE row is a
    deterministic claim — it names a SPECIFIC id that either exists in
    storyboard.shot_archetypes.SHOT_ARCHETYPES or doesn't, mirroring exactly
    how check_shot_causality_valid checks CAUSED_BY's label against this
    scene's own shot index. The catalog here is a fixed, global constant
    (not scene-scoped like CAUSED_BY's labels), so the check is even simpler:
    a straight membership test via shot_archetypes.get_archetype.

    Still WARN-only per the standing D6 Ruling 1 discipline — even though
    catalog membership is 100% mechanically decidable (unlike a free-prose
    PURPOSE clause, which is why THAT stays warn-only for a different
    reason), Ryan's ruling on this harvest chunk keeps it warn-only for
    ROLLOUT: the ARCHETYPE row is brand new and OPTIONAL (rule 27 — the
    planner "MAY" tag a shot, never "must"), so there is no track record yet
    proving real plans actually comply when they DO tag a shot. This check
    is explicitly HARD-ELIGIBLE under Ruling 1 the moment that track record
    exists (a canonical catalog to compare against is exactly what Ruling 1
    requires for a hard gate) — promoting it needs a separate, deliberate
    ruling once live plans show the id vocabulary is being used correctly,
    not a silent escalation buried in this chunk.

    Only evaluates shots that HAVE a stated shot_archetype — an untagged
    shot is not an error (the row is optional), so absence is never flagged
    here, only an invalid VALUE is. Flags a shot whose shot_archetype
    (already lowercased at parse time by _strip_shot_metadata_rows) doesn't
    match any id in the catalog."""
    warnings = 0
    for m in moments:
        for shot in [m["master"], *(m.get("angles") or [])]:
            archetype_id = shot.get("shot_archetype")
            if not archetype_id:
                continue
            if get_archetype(archetype_id) is None:
                warnings += 1
                print(f"  ⚠️ shot-archetype check (D11-1): moment {m.get('moment_number')} "
                      f"({shot.get('shot_type')}) has ARCHETYPE: {archetype_id}, which is not in "
                      "the shot archetype catalog — worth a human glance, not a hard failure",
                      flush=True)
    return warnings


def check_shot_dp_valid(moments: list[dict]) -> int:
    """D11-2 (film-studio audit follow-on, per-shot DP-as-data): unlike rule
    11's own camera-height/frame-fraction prose — which check_camera_facts_
    present's docstring admits is "free prose with no fixed vocabulary to
    scan for... NOT mechanically checkable today" — the DP row's three slots
    ARE each a deterministic claim once written: lens_mm is a number with a
    checkable range, camera_height and dof are each drawn from a small fixed
    vocabulary (CAMERA_HEIGHT_KINDS / DOF_KINDS above). This is the whole
    point of giving DP its own structured row instead of leaving it inside
    rule 11's prose. Mirrors check_shot_archetype_valid's "only evaluate
    shots that HAVE a value, absence is never an error" discipline — the row
    is entirely optional (rule 28: "you MAY").

    DETERMINISTIC-ELIGIBLE, WARN-only for rollout (D6 Ruling 1, same
    reasoning check_shot_archetype_valid's docstring gives for ARCHETYPE):
    all three checks below ARE canonical membership/range tests, which is
    exactly what Ruling 1 requires to be hard-eligible, but the DP row is
    brand new and OPTIONAL with no track record yet of real plans writing it
    correctly — promoting any of the three to a hard gate needs its own
    deliberate ruling once that track record exists, not a silent escalation
    here.

    Flags, independently per shot, ANY of:
      - lens_mm parsed to an int (the "<digits>mm" shape matched) but outside
        [DP_LENS_MIN_MM, DP_LENS_MAX_MM]
      - the lens slot had TEXT but it did NOT match that shape at all (the
        parse-only meta["_dp_lens_raw"] artifact — see _parse_dp_row — a
        malformed lens value that would otherwise silently vanish to None,
        indistinguishable from "no lens value written")
      - camera_height present but not one of CAMERA_HEIGHT_KINDS
      - dof present but not one of DOF_KINDS
    A shot with none of the three slots written at all is never flagged."""
    warnings = 0
    for m in moments:
        for shot in [m["master"], *(m.get("angles") or [])]:
            lens_mm = shot.get("lens_mm")
            lens_raw = shot.get("_dp_lens_raw")
            camera_height = shot.get("camera_height")
            dof = shot.get("dof")
            if lens_mm is None and lens_raw is None and camera_height is None and dof is None:
                continue
            label = f"moment {m.get('moment_number')} ({shot.get('shot_type')})"
            if lens_raw is not None:
                warnings += 1
                print(f"  ⚠️ shot-DP check (D11-2): {label} has DP: lens '{lens_raw}', which is "
                      "not a valid '<10-200>mm' lens value — worth a human glance, not a hard "
                      "failure", flush=True)
            elif lens_mm is not None and not (DP_LENS_MIN_MM <= lens_mm <= DP_LENS_MAX_MM):
                warnings += 1
                print(f"  ⚠️ shot-DP check (D11-2): {label} has DP: lens {lens_mm}mm, outside "
                      f"the {DP_LENS_MIN_MM}-{DP_LENS_MAX_MM}mm range — worth a human glance, "
                      "not a hard failure", flush=True)
            if camera_height is not None and camera_height not in CAMERA_HEIGHT_KINDS:
                warnings += 1
                print(f"  ⚠️ shot-DP check (D11-2): {label} has DP camera_height "
                      f"'{camera_height}', which is not one of {CAMERA_HEIGHT_KINDS} — worth a "
                      "human glance, not a hard failure", flush=True)
            if dof is not None and dof not in DOF_KINDS:
                warnings += 1
                print(f"  ⚠️ shot-DP check (D11-2): {label} has DP dof '{dof}', which is not one "
                      f"of {DOF_KINDS} — worth a human glance, not a hard failure", flush=True)
    return warnings


# =============================================================================
# D12-3 (board rhythm report): visual-RHYTHM checks — shot-size runs, lens
# repetition, purpose-kind monotony — read the SAME structured per-shot data
# D9-1 (purpose_kind)/D9-6 (transition_kind)/D11-1 (shot_archetype)/D11-2
# (lens_mm) harvested. Distinct from enforce_setup_variety's CAMERA-SETUP-
# family cap (with its own repair leg, below) — that one already covers
# camera-position variety; these three dimensions are untouched by it and
# nothing before this chunk reported on them at all. Same warning-only,
# "worth a human glance, not a hard failure" discipline as every check_*
# above: never blocks, never rewrites a shot, just counts and logs loudly.
# build_rhythm_report itself is a PURE function (no printing, no mutation)
# that the three checks below and coverage_to_app.py's sheet-preview surface
# both draw on (the three checks reuse its own sequence helpers), so the
# report and the warnings can never silently disagree on what "the longest
# run was".
# =============================================================================

_SHOT_SIZE_RUN_THRESHOLD = 2   # >2 consecutive identical shot_type (3rd+ shot) trips the check
_LENS_RUN_THRESHOLD = 3        # >3 consecutive identical lens_mm (4th+ shot) trips the check
_PURPOSE_RUN_THRESHOLD = 3     # >3 consecutive identical purpose_kind (4th+ shot) trips the check


def _rhythm_size_sequence(moments: list[dict]) -> list[tuple]:
    """(moment_number, shot_type) for every shot in scene draw order,
    EXCLUDING shot_type == "INSERT" (SHOT_TYPES' own dedicated punctuation-
    shot value — see the module's SHOT_TYPES constant and the planner
    grammar's "(SETUP E)(INSERT) ..." example at rule 5f; the CODE-added
    insert floor also always stamps shot_type="INSERT", see
    enforce_reaction_insert_floors' `_place(target_mi, "INSERT", ...)` call)
    and any shot with no shot_type at all (a legacy/malformed row). An
    excluded shot is fully ABSENT from the sequence — it neither extends nor
    breaks a neighboring run — mirroring how _carries_facing_law excludes an
    INSERT-tagged shot from rule 5g's face-visibility requirement entirely
    rather than merely skipping it in place: an INSERT's framing is a
    deliberate detail-punctuation choice, not part of the coverage's
    visual-size rhythm. REACTION shots are deliberately NOT excluded here —
    unlike INSERT, nothing else in this module exempts a REACTION shot from
    a shot-type-shaped check (_carries_facing_law actively INCLUDES it), so
    this doesn't invent a new exemption for it either."""
    seq = []
    for m in moments:
        mn = m.get("moment_number")
        for shot in [m["master"], *(m.get("angles") or [])]:
            st = (shot.get("shot_type") or "").upper()
            if not st or st == "INSERT":
                continue
            seq.append((mn, st))
    return seq


def _rhythm_lens_sequence(moments: list[dict]) -> list[tuple]:
    """(moment_number, lens_mm) for every shot with a parsed lens_mm (D11-2,
    rule 28 — optional, its own DP row). A shot with no lens_mm is ABSENT
    from the sequence, same non-extend-non-break reasoning as
    _rhythm_size_sequence — a legacy plan (predates D11-2) or any shot the
    planner simply didn't tag can never produce a false run."""
    seq = []
    for m in moments:
        mn = m.get("moment_number")
        for shot in [m["master"], *(m.get("angles") or [])]:
            lens_mm = shot.get("lens_mm")
            if lens_mm is None:
                continue
            seq.append((mn, lens_mm))
    return seq


def _rhythm_purpose_sequence(moments: list[dict]) -> list[tuple]:
    """(moment_number, purpose_kind) for every shot with a parsed
    purpose_kind (D9-1, rule 24 — optional in the sense that a legacy plan
    has none; check_shot_purpose_present above is the gate that flags a
    CURRENT-era plan for omitting it). Same absence-not-break reasoning as
    the two sequences above."""
    seq = []
    for m in moments:
        mn = m.get("moment_number")
        for shot in [m["master"], *(m.get("angles") or [])]:
            purpose_kind = shot.get("purpose_kind")
            if not purpose_kind:
                continue
            seq.append((mn, purpose_kind))
    return seq


def _longest_run(sequence: list[tuple], value_key: str) -> dict | None:
    """The longest maximal run of consecutive equal values in `sequence` (a
    list of (moment_number, value) pairs already filtered to the values a
    dimension cares about — see the three _rhythm_*_sequence functions
    above). Returns None for an empty sequence (every field on this
    dimension absent — the legacy-plan case), else {value_key: <value>,
    "length": <int>, "start_moment": <moment_number the run started at>}.
    Ties keep the FIRST (earliest) longest run, matching how a human
    scanning the scene top-to-bottom would find it."""
    if not sequence:
        return None
    best_len, best_value, best_start = 0, None, None
    i, n = 0, len(sequence)
    while i < n:
        value = sequence[i][1]
        j = i
        while j < n and sequence[j][1] == value:
            j += 1
        run_len = j - i
        if run_len > best_len:
            best_len, best_value, best_start = run_len, value, sequence[i][0]
        i = j
    return {value_key: best_value, "length": best_len, "start_moment": best_start}


def build_rhythm_report(moments: list[dict]) -> dict:
    """D12-3 (board rhythm report): a compact, PURE (no printing, no
    mutation) summary of this scene's plan-level visual rhythm — shot-size
    runs, lens repetition, purpose-kind monotony, archetype variety,
    transition-kind mix. Nothing before this chunk reported on ANY of this,
    even though the structured per-shot data has existed since D9-1/D9-6/
    D11-1/D11-2. Distinct from enforce_setup_variety's CAMERA-SETUP-family
    repair above — this never touches or reorders a shot, it only reports.

    Tolerant of every field being None (a legacy plan predating D9-1/D9-6/
    D11-1/D11-2, or any plan where the planner simply never wrote a given
    optional row): each dimension's sequence helper drops an absent shot
    from consideration entirely, so an all-absent scene reports None/empty
    for every dimension that depends on that field — never a crash, never a
    false run.

    Returns a dict:
      shot_type_counts: {shot_type: count} across EVERY shot (INSERT
        included — a genuine tally of the scene's shot-size mix, distinct
        from longest_size_run's INSERT-excluded rhythm reading below).
      longest_size_run: {"shot_type", "length", "start_moment"} or None —
        the longest consecutive run of the SAME shot_type among non-INSERT
        shots (_rhythm_size_sequence); the exact sequence
        check_shot_size_rhythm below flags against _SHOT_SIZE_RUN_THRESHOLD.
      longest_lens_run: {"lens_mm", "length", "start_moment"} or None — same
        shape, over shots with a parsed lens_mm (D11-2).
      longest_purpose_run: {"purpose_kind", "length", "start_moment"} or
        None — same shape, over shots with a parsed purpose_kind (D9-1).
      archetype_diversity: {"distinct", "total"} — how many DIFFERENT
        shot_archetype ids (D11-1) appear across how many TOTAL tagged
        shots; {"distinct": 0, "total": 0} when no shot carries one. Counts
        whatever id was WRITTEN, valid or not — check_shot_archetype_valid
        above is the one place catalog validity is judged, never here.
      transition_mix: {transition_kind: count} (D9-6) across every shot
        that stated one; {} when none did."""
    size_seq = _rhythm_size_sequence(moments)
    lens_seq = _rhythm_lens_sequence(moments)
    purpose_seq = _rhythm_purpose_sequence(moments)

    shot_type_counts: dict = {}
    archetype_total = 0
    archetype_distinct: set = set()
    transition_counts: dict = {}
    for m in moments:
        for shot in [m["master"], *(m.get("angles") or [])]:
            st = (shot.get("shot_type") or "").upper()
            if st:
                shot_type_counts[st] = shot_type_counts.get(st, 0) + 1
            archetype_id = shot.get("shot_archetype")
            if archetype_id:
                archetype_total += 1
                archetype_distinct.add(archetype_id)
            transition_kind = shot.get("transition_kind")
            if transition_kind:
                transition_counts[transition_kind] = transition_counts.get(transition_kind, 0) + 1

    return {
        "shot_type_counts": shot_type_counts,
        "longest_size_run": _longest_run(size_seq, "shot_type"),
        "longest_lens_run": _longest_run(lens_seq, "lens_mm"),
        "longest_purpose_run": _longest_run(purpose_seq, "purpose_kind"),
        "archetype_diversity": {"distinct": len(archetype_distinct), "total": archetype_total},
        "transition_mix": transition_counts,
    }


def check_shot_size_rhythm(moments: list[dict]) -> int:
    """D12-3: flags every shot beyond _SHOT_SIZE_RUN_THRESHOLD (2) in a run
    of consecutive identical shot_type among non-INSERT shots (see
    _rhythm_size_sequence — an INSERT punctuation shot is excluded from the
    run entirely, mirroring how _carries_facing_law exempts an INSERT-tagged
    shot from rule 5g). Same run-detection algorithm as enforce_setup_
    variety's CAMERA-SETUP-family cap above, but WARN-only — no swap, no
    repair, just a loud log, same 'worth a human glance, not a hard failure'
    discipline as every check_* above. A run of length <= 2 never fires; a
    run of length N > 2 fires N-2 warnings, one per shot past the cap
    (mirrors enforce_setup_variety's own per-offender counting)."""
    warnings = 0
    seq = _rhythm_size_sequence(moments)
    i, n = 0, len(seq)
    while i < n:
        shot_type = seq[i][1]
        j = i
        while j < n and seq[j][1] == shot_type:
            j += 1
        run_len = j - i
        if run_len > _SHOT_SIZE_RUN_THRESHOLD:
            for k in range(i + _SHOT_SIZE_RUN_THRESHOLD, j):
                warnings += 1
                print(f"  ⚠️ shot-size rhythm check (D12-3): moment {seq[k][0]} continues a "
                      f"{run_len}-shot run of {shot_type} in a row (non-INSERT) — worth a human "
                      "glance, not a hard failure", flush=True)
        i = j
    return warnings


def check_lens_rhythm(moments: list[dict]) -> int:
    """D12-3 companion check: same run-detection algorithm as
    check_shot_size_rhythm, over lens_mm (D11-2, rule 28 — optional) instead
    of shot_type, threshold _LENS_RUN_THRESHOLD (3). A shot with no lens_mm
    is absent from the sequence (see _rhythm_lens_sequence) — never flagged,
    never breaks a neighboring run — so a legacy plan or any scene that
    simply never uses the DP row stays completely silent."""
    warnings = 0
    seq = _rhythm_lens_sequence(moments)
    i, n = 0, len(seq)
    while i < n:
        lens_mm = seq[i][1]
        j = i
        while j < n and seq[j][1] == lens_mm:
            j += 1
        run_len = j - i
        if run_len > _LENS_RUN_THRESHOLD:
            for k in range(i + _LENS_RUN_THRESHOLD, j):
                warnings += 1
                print(f"  ⚠️ lens rhythm check (D12-3): moment {seq[k][0]} continues a "
                      f"{run_len}-shot run of {lens_mm}mm in a row — worth a human glance, "
                      "not a hard failure", flush=True)
        i = j
    return warnings


def check_purpose_monotony(moments: list[dict]) -> int:
    """D12-3 companion check: same run-detection algorithm again, over
    purpose_kind (D9-1, rule 24 — optional) instead of shot_type, threshold
    _PURPOSE_RUN_THRESHOLD (3). A shot with no purpose_kind is absent from
    the sequence (see _rhythm_purpose_sequence) — never flagged, never
    breaks a neighboring run — so a legacy plan or any scene that simply
    never uses the PURPOSE row stays completely silent."""
    warnings = 0
    seq = _rhythm_purpose_sequence(moments)
    i, n = 0, len(seq)
    while i < n:
        purpose_kind = seq[i][1]
        j = i
        while j < n and seq[j][1] == purpose_kind:
            j += 1
        run_len = j - i
        if run_len > _PURPOSE_RUN_THRESHOLD:
            for k in range(i + _PURPOSE_RUN_THRESHOLD, j):
                warnings += 1
                print(f"  ⚠️ purpose monotony check (D12-3): moment {seq[k][0]} continues a "
                      f"{run_len}-shot run of purpose '{purpose_kind}' in a row — worth a human "
                      "glance, not a hard failure", flush=True)
        i = j
    return warnings


# =============================================================================
# D6-2 REPAIR LEGS — BOARD-LAWS.md L11, L12, L15, L16, L17, L19, L22. Every
# law here previously had a PROMPT leg (the coverage system prompt, rules
# 12/14-20 above) and, for some, a warning-only GATE — and NOTHING else, so
# each evaporated the moment a single shot was redrawn: assets.image_prompt
# is stamped VERBATIM from moments[i]["master"/"angles"]["description"]
# (store_scene, coverage_to_app.py) and redraw_asset_image reuses that
# stored prompt verbatim, so whatever text never made it into a shot's OWN
# description at BUILD time is gone forever, redraw after redraw. These
# functions run in the SAME place and on the SAME freshly-parsed,
# pre-lock-tail descriptions as the check_* gates above (identical
# reasoning: the SET/MATERIAL/AXIS/STAGING/FACING/SEQUENCE/PROP lock tails
# appended further down in run_coverage are boilerplate that would swamp
# these heuristics — GROUP_NOUN_RE, NESTED_FRAME_NOUN_RE etc — with false
# matches if it ran first).
#
# Per BOARD-PLANNER-ARCHITECTURE.md, L16 and L22 get the STRONGER
# treatment: a COMPUTED property (WHICH setup reverses WHICH, and the
# seating order MECHANICALLY FLIPPED for that reverse) rather than prose
# repeated verbatim. L11/L12/L17 get the "declare once, stamp everywhere"
# pattern already proven by the SET-dressing lock. L15/L19 get a FIXED
# instructional reminder stamped onto every shot the existing gate would
# flag — the same pattern the FACING LOCK below already uses. L18 gets NO
# repair leg — admitted honestly in check_discovery_object_unremarked's
# docstring and this chunk's commit message.
# =============================================================================

def apply_nested_frame_content_lock(moments: list[dict]) -> int:
    """L11 REPAIR LEG (NESTED FRAMES): the FIRST shot in scene order whose
    description names a nested-frame noun (screen/monitor/mirror/feed) AND
    states its content (passes check_nested_frame_content_specified's
    positive case) becomes the CANONICAL content statement for that noun.
    Every LATER shot naming the SAME noun with no content of its own gets
    that canonical statement stamped on — repeating an established fact,
    never inventing new content — so a single-shot redraw of a later panel
    can't silently drop what's showing on the screen (L11's provenance: "the
    content drifts from panel to panel"). A noun that's never once given
    content anywhere in the scene stays unrepaired — nothing canonical to
    repeat; the existing warning-only gate still flags it honestly. Returns
    the number of shots repaired."""
    canonical: dict[str, str] = {}
    n = 0
    for m in moments:
        for shot in [m["master"], *(m.get("angles") or [])]:
            desc = shot.get("description") or ""
            noun_m = _NESTED_FRAME_NOUN_RE.search(desc)
            if not noun_m:
                continue
            noun = noun_m.group(1).lower()
            if _CONTENT_BEARING_RE.search(desc):
                canonical.setdefault(noun, desc.strip())
            elif noun in canonical:
                tail = (f"Nested-frame content lock: the {noun} in this panel shows the SAME "
                        f"content established elsewhere in this scene — matching this scene's "
                        f"own {noun} content: \"{canonical[noun][:220]}\"")
                shot["description"] = f"{shot['description'].rstrip('. ')}. {tail}"
                n += 1
    return n


def _extract_arrangement_clause(desc: str) -> str | None:
    """The FULL SENTENCE (bounded by '.' characters) containing this shot's
    group-noun mention — the canonical form used by apply_group_arrangement_
    lock to capture, repeat and (for L22) flip this scene's headcount+
    arrangement fact. Deliberately captures the WHOLE sentence rather than
    starting exactly at the noun match, because the count almost always
    precedes the noun in English ("exactly five elites..."), which a
    noun-anchored slice would cut off. None when no group noun is present."""
    gm = _GROUP_NOUN_RE.search(desc or "")
    if not gm:
        return None
    start = desc.rfind(".", 0, gm.start())
    start = 0 if start == -1 else start + 1
    end = desc.find(".", gm.end())
    end = len(desc) if end == -1 else end
    return desc[start:end].strip()


_ARRANGEMENT_ORDER_SPLIT_RE = re.compile(r",?\s*then\s+|,\s+(?=[A-Za-z])", re.IGNORECASE)
_FRAME_SIDE_SWAP = {
    "frame-left": "frame-right", "frame-right": "frame-left",
    "left to right": "right to left", "right to left": "left to right",
}
_FRAME_SIDE_SWAP_RE = re.compile("|".join(re.escape(k) for k in _FRAME_SIDE_SWAP), re.IGNORECASE)


def compute_reverse_arrangement(arrangement_text: str) -> str | None:
    """L22's actual COMPUTATION (BOARD-PLANNER-ARCHITECTURE.md: "computed by
    flipping the seating order for a reverse angle instead of asking a model
    to remember"): split the canonical arrangement sentence into its comma/
    "then"-separated ordered clauses, REVERSE their order, and swap every
    frame-left/frame-right (and left-to-right/right-to-left) token. This is
    a genuine mechanical transformation — the order is inverted by code,
    never re-guessed by a model.

    Returns None when the source text doesn't parse into at least 2 ordered
    clauses (too short/free-form to safely reverse) — an honest failure,
    never a guess; callers fall back to a baked repeat-as-is stamp instead."""
    if not arrangement_text:
        return None
    clauses = [c.strip() for c in _ARRANGEMENT_ORDER_SPLIT_RE.split(arrangement_text) if c.strip()]
    if len(clauses) < 2:
        return None
    swapped = [_FRAME_SIDE_SWAP_RE.sub(lambda mm: _FRAME_SIDE_SWAP[mm.group(0).lower()], c)
               for c in reversed(clauses)]
    return ", then ".join(swapped)


def apply_reverse_background_lock(moments: list[dict], reverse_pairs: dict) -> int:
    """L16 REPAIR LEG (A REVERSE ANGLE CHANGES THE BACKGROUND) — COMPUTED,
    not baked prose. reverse_pairs ({setup_id: reverse_partner_id}, both
    directions — parse_reverse_setup_pairs) reads the ONE place this
    relationship is genuinely authored: the [SETUPS|...] line's own "the
    matched reverse of X" phrasing. WHICH setup reverses WHICH is therefore
    a COMPUTED FACT here, never re-typed or re-guessed per shot — exactly
    what BOARD-PLANNER-ARCHITECTURE.md names as the target for this law
    ("Backgrounds follow from camera position (L16)"). Every shot drawn
    from a setup with a known reverse partner (matched by its FULL compound
    id, e.g. "B-CU", or falling back to its BASE family, e.g. "B" — a
    size-variant shares its family's exact background/axis, so it inherits
    the same reverse relationship) gets a FIXED, code-written anti-
    carryover instruction. The actual background CONTENT is still the
    planner's/drawer's job — this stamp only forbids the one failure mode
    L16's provenance recorded: one setup's background bleeding into its
    reverse, or a front light source rendering as a visible object behind
    the reverse camera. Empty reverse_pairs (no "matched reverse of" phrase
    anywhere in this scene — legacy plans, or a scene with no reverse pair)
    repairs nothing; L16 falls back to prose-only for that scene, same as
    before this function existed."""
    if not reverse_pairs:
        return 0
    n = 0
    for m in moments:
        for shot in [m["master"], *(m.get("angles") or [])]:
            sid = _setup_id(shot)
            if not sid:
                continue
            partner = reverse_pairs.get(sid) or reverse_pairs.get(_setup_base_id(sid))
            if not partner:
                continue
            tail = (
                f"Reverse-angle background lock (computed): this camera SETUP {sid} is the "
                f"matched reverse of SETUP {partner}. Whatever sits behind the subject in "
                f"SETUP {partner} must NOT reappear behind them here — state what genuinely "
                f"sits behind the subject from THIS camera position. If SETUP {partner}'s light "
                f"source or screen sat in FRONT of that camera, it is now BEHIND THIS camera "
                f"instead: it lights the subject's face here, it is never a visible object in "
                f"this frame.")
            shot["description"] = f"{shot['description'].rstrip('. ')}. {tail}"
            n += 1
    return n


def apply_group_arrangement_lock(moments: list[dict], reverse_pairs: dict) -> int:
    """L17 + L22 REPAIR LEG (LOCK THE HEADCOUNT + STATE GROUP ARRANGEMENT
    PER CAMERA POSITION — always paired in BOARD-LAWS.md rule 18). The
    FIRST shot in scene order that states a group's headcount AND its
    arrangement (passes check_group_arrangement_stated's positive case)
    becomes this scene's CANONICAL arrangement statement, persisted onto
    that shot's own shot["group_arrangement"]. Every LATER shot naming the
    same kind of group with no arrangement of its own is repaired one of
    two ways:

    1. COMPUTED FLIP (preferred — L22's actual "computed" target): if the
       shot's own camera SETUP is the reverse_pairs partner of the
       establishing shot's setup, compute_reverse_arrangement() mechanically
       reverses the canonical order and swaps frame-left/frame-right.
    2. BAKED REPEAT (fallback): same-side setups, an undetermined reverse
       relationship, or arrangement text that doesn't parse into an
       orderable list — the canonical statement is repeated verbatim. Still
       closes the L17 drift gap (the count survives) even when L22's flip
       can't be computed.

    Every repaired shot's computed/repeated text is ALSO written onto
    shot["group_arrangement"] (migration 143's assets.group_arrangement
    column, persisted by store_scene) — not just baked into the image
    prompt. A scene where no shot ever states a canonical arrangement
    repairs nothing; check_headcount_stated/check_group_arrangement_stated
    still flag that honestly. Returns the number of shots repaired (the
    establishing shot itself is not counted — it needed no repair)."""
    canonical = None          # the establishing shot's full arrangement clause
    canonical_setup = None    # its SETUP id, for reverse-pair lookup
    n = 0
    for m in moments:
        for shot in [m["master"], *(m.get("angles") or [])]:
            desc = shot.get("description") or ""
            has_group = bool(_GROUP_NOUN_RE.search(desc))
            has_number = bool(_NUMBER_TOKEN_RE.search(desc))
            has_arrangement = bool(_ARRANGEMENT_TERM_RE.search(desc))
            if has_group and has_number and has_arrangement:
                clause = _extract_arrangement_clause(desc) or desc.strip()
                if canonical is None:
                    canonical = clause
                    canonical_setup = _setup_id(shot)
                shot["group_arrangement"] = clause
                continue
            if not (has_group and canonical):
                continue
            sid = _setup_id(shot)
            is_reverse_of_canonical = bool(
                canonical_setup and sid and (
                    reverse_pairs.get(sid) == canonical_setup
                    or reverse_pairs.get(_setup_base_id(sid)) == canonical_setup
                )
            )
            flipped = compute_reverse_arrangement(canonical) if is_reverse_of_canonical else None
            if flipped:
                tail = (f"Group arrangement lock (computed — this SETUP is the reverse of the "
                        f"establishing shot's SETUP {canonical_setup}, order flipped): {flipped}.")
                shot["group_arrangement"] = flipped
            else:
                tail = (f"Group arrangement lock: same headcount and arrangement as established "
                        f"elsewhere in this scene — {canonical}.")
                shot["group_arrangement"] = canonical
            shot["description"] = f"{shot['description'].rstrip('. ')}. {tail}"
            n += 1
    return n


def apply_population_lock(moments: list[dict]) -> int:
    """L12 REPAIR LEG (SPECIFY THE POPULATION): the FIRST shot in scene
    order whose description names a group AND carries population-
    description language (_POPULATION_DESC_RE — clothing/posture/shadow/
    depth terms) is captured as this scene's canonical population statement.
    Every LATER shot naming a group with no descriptive language of its own
    gets that canonical statement repeated — the same "declare once, stamp
    everywhere" pattern as the SET-dressing lock, applied to the specific
    fact L12 is about (what the background people look like), never a fresh
    invention."""
    canonical = None
    n = 0
    for m in moments:
        for shot in [m["master"], *(m.get("angles") or [])]:
            desc = shot.get("description") or ""
            if not _GROUP_NOUN_RE.search(desc):
                continue
            if _POPULATION_DESC_RE.search(desc):
                if canonical is None:
                    canonical = desc.strip()
            elif canonical:
                tail = (f"Population lock: the background population's look is fixed for this "
                        f"whole scene, matching how it was established elsewhere: "
                        f"\"{canonical[:220]}\"")
                shot["description"] = f"{shot['description'].rstrip('. ')}. {tail}"
                n += 1
    return n


_ATTENTION_LOCK_TAIL = (
    "Attention-vs-orientation lock: if this is a shift of ATTENTION rather than a full "
    "re-stage, state explicitly what stays FIXED (chair, hips, feet, the direction already "
    "established) and what MOVES (head, shoulders, gaze) — a partial turn must never read as "
    "the whole body and chair re-staging.")


def apply_attention_orientation_lock(moments: list[dict]) -> int:
    """L15 REPAIR LEG: every shot check_attention_orientation_stated's same
    heuristic would flag gets the law's own requirement stamped onto its
    OWN description as a fixed instructional reminder — the SAME pattern
    the existing FACING LOCK (facing_tail, in run_coverage below) already
    uses: a fixed, code-written sentence, not scene-specific content, so it
    can't be paraphrased away and survives a redraw baked into
    image_prompt."""
    n = 0
    for m in moments:
        for shot in [m["master"], *(m.get("angles") or [])]:
            desc = shot.get("description") or ""
            if _ATTENTION_SHIFT_RE.search(desc) and not _FIXED_ANCHOR_STATED_RE.search(desc):
                shot["description"] = f"{shot['description'].rstrip('. ')}. {_ATTENTION_LOCK_TAIL}"
                n += 1
    return n


_POV_LOCK_TAIL = (
    "Diegetic POV lock: this is a NEUTRAL setup occupying the in-story device's own "
    "position — the eyes go DIRECTLY into camera with no three-quarter softening, no "
    "flinch, no glance-away, and the device's own housing (lens casing, mirror frame) is "
    "never visible from inside itself.")


def apply_pov_diegetic_lock(moments: list[dict]) -> int:
    """L19 REPAIR LEG (DIEGETIC CAMERA POV): every shot the existing
    check_pov_setup_neutral_and_into_camera gate would flag (POV setup
    language present, NEUTRAL or into-camera term missing) gets the law's
    own requirement stamped as a fixed reminder — same FACING-LOCK-style
    pattern as apply_attention_orientation_lock above."""
    n = 0
    for m in moments:
        for shot in [m["master"], *(m.get("angles") or [])]:
            desc = shot.get("description") or ""
            if not _POV_SETUP_TERM_RE.search(desc):
                continue
            if "NEUTRAL" not in desc.upper() or not _INTO_CAMERA_RE.search(desc):
                shot["description"] = f"{shot['description'].rstrip('. ')}. {_POV_LOCK_TAIL}"
                n += 1
    return n


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
                    # D9-1: purpose_kind/shot_purpose describe WHAT a shot shows
                    # and WHY — they travel with the content, not the position,
                    # or a swap would leave a shot's stated purpose describing a
                    # framing/action that no longer lives there.
                    a["purpose_kind"], b["purpose_kind"] = b.get("purpose_kind"), a.get("purpose_kind")
                    a["shot_purpose"], b["shot_purpose"] = b.get("shot_purpose"), a.get("shot_purpose")
                    # D9-6/D9-7: same reasoning extends to transition_kind/
                    # continuity_bridge/caused_by — they describe WHY and HOW
                    # this specific piece of content cuts in and what earlier
                    # content it follows from, not a fact about the numbered
                    # position it happens to occupy. They move WITH the
                    # description they were authored to explain.
                    a["transition_kind"], b["transition_kind"] = b.get("transition_kind"), a.get("transition_kind")
                    a["continuity_bridge"], b["continuity_bridge"] = b.get("continuity_bridge"), a.get("continuity_bridge")
                    a["caused_by"], b["caused_by"] = b.get("caused_by"), a.get("caused_by")
                    # D11-1: shot_archetype is the same kind of content-
                    # describing fact as purpose/transition/caused_by above —
                    # it names WHAT KIND of shot this content is, not a fact
                    # about the position it occupies, so it moves WITH the
                    # description too.
                    a["shot_archetype"], b["shot_archetype"] = b.get("shot_archetype"), a.get("shot_archetype")
                    # D11-2: lens_mm/camera_height/dof describe HOW this
                    # specific piece of content was meant to be shot — a DP
                    # choice made FOR this content, not a fact about the
                    # numbered position it occupies — so, same reasoning as
                    # every field above, they move WITH the description too.
                    a["lens_mm"], b["lens_mm"] = b.get("lens_mm"), a.get("lens_mm")
                    a["camera_height"], b["camera_height"] = b.get("camera_height"), a.get("camera_height")
                    a["dof"], b["dof"] = b.get("dof"), a.get("dof")
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

# =============================================================================
# GENRE-AWARE PACING (D12-1) — cut-rhythm multiplier on top of the
# composition default above, keyed by genre FAMILY. A "wide" isn't always
# 3.5s: an action scene should hold it for less, a contemplative one for
# more. Multiplies _COMPOSITION_DURATION_SECONDS' base value; NEVER applied
# to a speaking shot (stamp_shot_durations already skips those below —
# length comes from measured speech, genre has no say in it).
#
#   action_thriller  0.75x — faster cuts, shorter holds (chases, heists, war)
#   drama             1.0x — the historical default; also the catch-all for
#                             any genre text that matches no family below
#   emotional         1.3x — longer takes, holds on the frame (romance,
#                             slice-of-life, coming-of-age)
#   mystery_suspense  1.15x — a bit slower than drama, biased toward the
#                             slow reveal (a mystery earns its wide)
#   comedy            1.0x — SAME duration as drama. Comedy's real pacing
#                             signal is reaction-shot FREQUENCY, not hold
#                             length — see the note in
#                             _genre_pacing_multiplier below for why that
#                             isn't wired up in this chunk.
#
# Genre text is free-form LLM output (story_bible_native.py's own genre
# prompt: "one or two words, e.g. 'geopolitical thriller', 'explainer'"),
# not a fixed enum — so resolution is substring-keyword matching against
# _GENRE_FAMILY_KEYWORDS below, case-insensitive, never exact-match only.
# Absent OR unrecognized genre text -> multiplier 1.0 EXACTLY. That is the
# invariant this feature must never break: every video without a D10-2ab
# native story bible (every video predating it, or one whose bible produced
# no narrative section) gets byte-identical durations to pre-D12-1 output —
# literally the same float, not merely "close to 1.0".
# =============================================================================
GENRE_PACING = {
    "action_thriller": 0.75,
    "drama": 1.0,
    "emotional": 1.3,
    "mystery_suspense": 1.15,
    "comedy": 1.0,
}

# Checked in THIS order — a family earlier in the dict wins a substring
# match over one later (e.g. "psychological thriller" matches mystery_
# suspense's own entry before it ever reaches action_thriller's plain
# "thriller" keyword; "melodrama" matches emotional before drama's bare
# "drama" substring would). Order encodes priority, not alphabetical
# convenience — do not reorder without re-checking the overlap cases in
# test_coverage.py's D12-1 section.
_GENRE_FAMILY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "mystery_suspense": (
        "mystery", "suspense", "noir", "detective", "whodunit", "whodunnit",
        "true crime", "psychological thriller", "psychological suspense",
    ),
    "comedy": (
        "comedy", "comedic", "satire", "sitcom", "parody", "farce",
    ),
    "emotional": (
        "emotional", "contemplative", "romance", "romantic", "melodrama",
        "slice of life", "slice-of-life", "coming-of-age", "coming of age",
        "tearjerker",
    ),
    "action_thriller": (
        "action", "thriller", "war", "heist", "spy", "espionage", "military",
        "chase", "crime thriller",
    ),
    "drama": (
        "drama", "dialogue-driven", "dialogue driven", "biography", "biopic",
    ),
}


def _genre_pacing_multiplier(genre: str | None) -> float:
    """D12-1: resolve free-text `genre` (story_bible.narrative.genre — see
    _genre_pacing_signal below for where callers read it from, and the
    module comment above GENRE_PACING for the family table) to a duration
    multiplier via _GENRE_FAMILY_KEYWORDS' case-insensitive substring
    match. None, empty, non-string, or text matching no family's keywords
    all return 1.0 EXACTLY — the byte-identical default (see GENRE_PACING's
    docstring for why that must be exact, not approximate).

    Comedy scope decision (D12-1): comedy's real pacing signal is
    reaction-shot FREQUENCY (cutting to the listener's face for the laugh),
    not hold length — but enforce_reaction_insert_floors (this module,
    above) exposes no per-call frequency knob today, only the module
    constant _REACTION_TURNS_PER_SHOT, and adding one means rebuilding that
    floor's call contract, which this chunk's brief explicitly rules out
    ("do NOT rebuild the floors"). Comedy is therefore guidance-only here:
    multiplier 1.0, identical to drama, until a future chunk exposes a real
    knob."""
    if not genre or not isinstance(genre, str):
        return 1.0
    g = genre.strip().lower()
    if not g:
        return 1.0
    for family, keywords in _GENRE_FAMILY_KEYWORDS.items():
        if any(kw in g for kw in keywords):
            return GENRE_PACING.get(family, 1.0)
    return 1.0


_MIN_SHOT_DURATION_SECONDS = 1.0
_MAX_SHOT_DURATION_SECONDS = 6.0


def _clamp_shot_duration(seconds: float) -> float:
    """D12-1 safety net: no genre multiplier (today's set, or a future
    tweak) can push a stamped duration outside [1.0, 6.0]s — under a second
    reads as a flash-cut glitch, over six as a stalled frame. Today's
    actual range (0.75x * 1.6s closeup = 1.2s .. 1.3x * 3.5s wide = 4.55s)
    never touches either bound; this exists for the NEXT multiplier someone
    adds, not because the current table needs it."""
    return max(_MIN_SHOT_DURATION_SECONDS, min(_MAX_SHOT_DURATION_SECONDS, seconds))


def stamp_shot_durations(moments: list, genre: str | None = None) -> int:
    """Stamp shot["duration_seconds"] on every SILENT shot in `moments` —
    every angle, and every master EXCEPT a speaking moment's master (that
    one's clip-length comes from measured speech at animate/assemble time,
    never from this table). Idempotent (safe to call more than once; always
    overwrites with the same deterministic value for a given shot_type and
    genre).

    genre (D12-1): the video's story_bible narrative genre — see
    _genre_pacing_signal (below, this module) for where run_coverage reads
    it from. Multiplies the composition base duration by GENRE_PACING's
    family factor (via _genre_pacing_multiplier), then clamps to
    [1.0, 6.0]s (_clamp_shot_duration). None (the default, and every call
    site before D12-1) resolves to multiplier 1.0, and 1.0x times any of
    today's three base values stays exactly that value (float identity,
    `x * 1.0 == x`, and the clamp is a no-op inside [1.6, 3.5]) — so every
    existing caller and every video without a genre signal gets
    byte-identical output to before this feature.

    Returns how many shots were stamped."""
    mult = _genre_pacing_multiplier(genre)
    n = 0
    for moment in moments:
        speaking = bool(moment.get("speaker") and moment.get("line"))
        m = moment.get("master")
        if m and not speaking:
            base = _COMPOSITION_DURATION_SECONDS.get(
                _SHOT_TYPE_COMPOSITION.get((m.get("shot_type") or "").upper(), "medium"), 2.5)
            m["duration_seconds"] = _clamp_shot_duration(base * mult)
            n += 1
        for a in moment.get("angles") or []:
            base = _COMPOSITION_DURATION_SECONDS.get(
                _SHOT_TYPE_COMPOSITION.get((a.get("shot_type") or "").upper(), "medium"), 2.5)
            a["duration_seconds"] = _clamp_shot_duration(base * mult)
            n += 1
    return n


# =============================================================================
# D10-3c: genre accessor — reads run_coverage's OWN story_bible param.
# =============================================================================
# scene_aware_bible (D10-3a, storyengine/backend/scripts/coverage_to_app.py)
# already attaches a `narrative` dict (genre/tone/themes/..., off
# videos.story_bible.narrative — D10-2ab, backend/story_bible_native.py)
# onto the SAME bible object every real caller threads into run_coverage as
# `story_bible` (coverage_to_app.generate_coverage_for_video passes
# `story_bible=bible` at both of its run_coverage call sites, unchanged by
# this chunk). So genre is ALREADY inside this module by the time
# run_coverage runs — this file never imports storyengine/backend to get
# it; the value flows IN via the existing parameter, not the reverse, so
# skills/video-pipeline stays backend-agnostic. A story_bible with no
# narrative section (every video before D10-2ab, or one whose bible
# produced none) returns None below, same as no story_bible at all.
#
# tone (story_bible['narrative']['tone']) is NOT threaded by this accessor:
# GENRE_PACING (D12-1) keys off genre only, so a tone value nothing
# consumes would be dead weight. Any future pacing rule that wants tone can
# read story_bible['narrative']['tone'] directly — same dict, same key,
# no new plumbing required.
def _genre_pacing_signal(story_bible: dict | None) -> str | None:
    """This video's genre off story_bible['narrative']['genre'], or None
    when story_bible is absent, carries no narrative section, or genre is
    empty/non-string. Feeds stamp_shot_durations' GENRE_PACING (D12-1)."""
    narrative = (story_bible or {}).get("narrative")
    if not isinstance(narrative, dict):
        return None
    genre = narrative.get("genre")
    return genre.strip() if isinstance(genre, str) and genre.strip() else None


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
    either way.

    location_sets (D6-6c) is derived from this SAME directive_text (rule 8's
    [LOCSET|...] blocks) and threaded into enforce_shot_budget so the
    deterministic bridge signals fire for BOTH callers of this one pipeline
    identically — never re-derived per caller, so the sheet preview and the
    real pictures draw can't silently disagree on which moment is the
    bridge."""
    moments = parse_coverage(directive_text or "")
    if not moments:
        return None
    location_sets = parse_location_sets(directive_text or "")
    moments = enforce_shot_budget(moments, max_moments, angles_max, max_frames=max_frames,
                                  location_sets=location_sets)
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
    # without one, the classic match-the-refs STYLE LOCK applies ONLY when
    # this specific shot's refs list actually has something in it (D6-6d —
    # _style_block_for computed per-shot, below, from the REAL refs list
    # handed to that shot's _gen() call, never from `base` alone).
    style_prefix = _stated_style_prefix(profile)

    m = moment["master"]
    master_url, master_model = None, None
    try:
        s_anchor, s_ref = await _setup_ref(m)
        m_anchor, m_ref = _board(m, board_is_last=not s_ref)
        master_refs = base + m_ref + s_ref
        master_prompt = (style_prefix
                         + build_image_prompt_from_keyframe({"composition": m["description"]}, profile)
                         + _style_block_for(style_prefix, master_refs) + m_anchor + s_anchor)
        master_url, master_model = await _gen(master_prompt, master_refs)  # master first — angles anchor on it
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
               "duration_seconds": m.get("duration_seconds"),
               # D6-2 (migration 143): the per-shot location/arrangement
               # signals stamped onto the shot dict by run_coverage's
               # persist + L17/L22 repair-leg blocks — threaded through here
               # so store_scene can write them into assets.shot_location /
               # assets.group_arrangement. None for a shot with no group/
               # location signal, unchanged from before this column existed.
               "shot_location": m.get("shot_location"),
               "group_arrangement": m.get("group_arrangement"),
               # D9-1 (migration 147): the per-shot narrative-purpose signal
               # parse_coverage extracted from this shot's own "PURPOSE: ..."
               # row — threaded through here so store_scene can write it into
               # assets.purpose_kind / assets.shot_purpose. None for a shot
               # the planner didn't tag (every shot before this chunk, and
               # any floor-added filler shot going forward).
               "purpose_kind": m.get("purpose_kind"),
               "shot_purpose": m.get("shot_purpose"),
               # D9-6/D9-7 (migration 148): the per-shot transition/causality
               # signals parse_coverage extracted from this shot's own
               # "TRANSITION: ..." / "CAUSED_BY: ..." rows — threaded through
               # here so store_scene can write them into assets.
               # transition_kind / assets.continuity_bridge / assets.
               # caused_by. None for a shot the planner didn't tag.
               "transition_kind": m.get("transition_kind"),
               "continuity_bridge": m.get("continuity_bridge"),
               "caused_by": m.get("caused_by"),
               # D11-1 (migration 149): the OPTIONAL per-shot professional
               # shot-archetype id parse_coverage extracted from this shot's
               # own "ARCHETYPE: <id>" row — threaded through here so
               # store_scene can write it into assets.shot_archetype. None
               # for the overwhelming majority of shots (row omitted, or a
               # row generated before this migration).
               "shot_archetype": m.get("shot_archetype"),
               # D11-2 (migration 150): the OPTIONAL per-shot structured DP
               # (director of photography) fields parse_coverage extracted
               # from this shot's own "DP: <lens_mm> | <camera_height> |
               # <dof>" row — threaded through here so store_scene can write
               # them into assets.lens_mm / assets.camera_height /
               # assets.dof. None for the overwhelming majority of shots
               # (row omitted, or a shot generated before this migration).
               "lens_mm": m.get("lens_mm"),
               "camera_height": m.get("camera_height"),
               "dof": m.get("dof")}]
    angle_base = cast_refs + [master_url] + ([env_url] if env_url else [])

    async def _angle(a):
        url = None
        try:
            s_anchor, s_ref = await _setup_ref(a)
            a_anchor, a_ref = _board(a, board_is_last=not s_ref)
            angle_refs = angle_base + a_ref + s_ref
            ap = (style_prefix
                  + build_image_prompt_from_keyframe({"composition": a["description"]}, profile)
                  + _SAME_SUBJECT + _style_block_for(style_prefix, angle_refs) + a_anchor + s_anchor)
            url, model_used = await _gen(ap, angle_refs)
        finally:
            _resolve_owned(a, url)
        return {"role": "angle", "shot_type": a["shot_type"], "description": a["description"],
                "camera_move": a.get("camera_move"), "routed_model": a.get("routed_model"),
                "routing_reason": a.get("routing_reason"), "url": url,
                "image_model": model_used,
                "duration_seconds": a.get("duration_seconds"),
                # D6-2 (migration 143) — see the master frame's dict above.
                "shot_location": a.get("shot_location"),
                "group_arrangement": a.get("group_arrangement"),
                # D9-1 (migration 147) — see the master frame's dict above.
                "purpose_kind": a.get("purpose_kind"),
                "shot_purpose": a.get("shot_purpose"),
                # D9-6/D9-7 (migration 148) — see the master frame's dict above.
                "transition_kind": a.get("transition_kind"),
                "continuity_bridge": a.get("continuity_bridge"),
                "caused_by": a.get("caused_by"),
                # D11-1 (migration 149) — see the master frame's dict above.
                "shot_archetype": a.get("shot_archetype"),
                # D11-2 (migration 150) — see the master frame's dict above.
                "lens_mm": a.get("lens_mm"),
                "camera_height": a.get("camera_height"),
                "dof": a.get("dof")} if url else None

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


# Rule 4b PROMISES the planner a bridge moment is additive ("if a location
# change needs one, plan one more moment than the stated cap"), so the moment
# cap below counts NARRATED moments only. Runaway brake: a scene legitimately
# needs one bridge per location change (two covers an A→B→C scene), and past
# that it's a planner slip tagging everything — an exempt moment is real image
# spend, so extra bridges go back to competing for cap slots like any other
# moment.
_MAX_EXEMPT_BRIDGES = 2

# D6-6c: a structural, moment-summary-scoped mirror of story_laws.py's S1
# _TRANSIT_HINTS_RE/_has_transit_language (storyengine/backend/story_laws.py —
# a DIFFERENT package root than this file, so this is a deliberate,
# documented duplication rather than a cross-root import, the same reasoning
# canonical_material_line already uses to mirror coverage_to_app's
# _canonical_material_line). Deliberately checked against the moment's own
# ONE-LINE `summary` (the planner's "[MOMENT n | one-line description of
# what happens]" text) and NEVER against a shot's verbose `description` —
# a shot's description repeats scene-wide camera-kit boilerplate ("lens on
# the catwalk side...") on EVERY shot in the scene regardless of which
# moment it belongs to (L7: establishing shots legitimately frame a hatch/
# corridor before it's used), so matching against it would false-positive
# on ordinary establishing shots. The one-line summary is the planner's own
# short account of what HAPPENS in that moment — the same register as S1's
# "write the actual beat: the door, the threshold, the exit, the travel,
# the arrival" — so a real transit beat's summary reliably uses this
# vocabulary while an unrelated summary ("she whispers to herself") does not.
_TRANSIT_HINTS_RE = re.compile(
    r"\b("
    r"door|doorway|hatch|threshold|corridor|hallway|hall|stairs?|stairwell|"
    r"elevator|lift|window|gate|entrance|exit|"
    r"walks?\s+(?:to|into|toward|through|out)|"
    r"steps?\s+(?:into|through|out|toward|inside|off)|"
    r"enters?|exits?|arrives?|departs?|"
    r"heads?\s+(?:to|toward|for|out)|"
    r"leaves?|climbs?|crosses?\s+(?:into|through)|"
    r"runs?\s+(?:to|into|toward|down|through)"
    r")\b",
    re.IGNORECASE,
)


def _is_bridge_moment(m, location_sets: dict | None = None, prev_location: str | None = None) -> bool:
    """True when this moment IS rule 4b's bridge — the extra transition
    moment that shows HOW the characters got from one location to the
    next — whether or not the LLM planner remembered to write the literal
    "(BRIDGE)" tag on it (D6-6c). The tag alone is a text-generation choice
    the planner applies inconsistently call to call — found live: the SAME
    scene's exit beat got the tag on only 1 of 3 real planner calls — so a
    hard budget cut should never hinge on that coin flip alone. This ORs
    the tag with two structural signals derived from the parsed plan
    itself, never from a fresh LLM judgment call:

      1. (unchanged) the MASTER or an ANGLE carries the literal "(BRIDGE)"
         tag. Rule 4b puts it on the MASTER, but a slip that tags an angle
         instead still describes a location change, so this reads the same
         master-plus-angles span scene_has_motion does (via the same
         _shot_tag reader).
      2. (new) a location change within the parsed plan: this moment's own
         declared LOCATION (rule 8's per-moment "LOCATION: <name> |" tag)
         differs from the previous KEPT moment's location.
      3. (new) the S1 transit sentence, restated at moment scope: this
         moment's one-line summary uses transit language (a door/hatch/
         corridor/threshold, or a verb of arriving/leaving/climbing/
         crossing — _TRANSIT_HINTS_RE).

    Signals 2 and 3 are BOTH gated on location_sets carrying 2+ LOCSET
    blocks (rule 8) — the planner's OWN structural assertion that this
    scene genuinely spans more than one location. Neither fires on an
    ordinary single-location scene, so a plain conversation whose summary
    happens to mention a door in passing is untouched. location_sets=None
    (every call site before D6-6c, and every legacy/single-location plan)
    disables both new signals entirely, leaving ONLY the original tag
    check — byte-identical to this function's pre-D6-6c behavior until a
    caller opts in by passing a real location_sets."""
    for shot in [m.get("master") or {}, *(m.get("angles") or [])]:
        if _shot_tag(shot) == "BRIDGE":
            return True
    if location_sets and len(location_sets) >= 2:
        location = m.get("location")
        if location and prev_location and location.lower() != prev_location.lower():
            return True
        if _TRANSIT_HINTS_RE.search(m.get("summary") or ""):
            return True
    return False


def enforce_shot_budget(moments: list, max_moments: int, angles_max: int,
                        max_frames: int = None, location_sets: dict | None = None) -> list:
    """HARD shot budget (D1): the directive prompt ASKS for at most max_moments
    and angles_max angles, but the planner is an LLM and overshoots (observed
    live: 17 moments / 35 frames against a 12/0 budget). Enforce in code BEFORE
    any drawing spend: trim extra angles per moment, then drop tail moments past
    the cap. Dialogue lines are never lost — the caller's reconcile folds
    overflow turns onto the last speaking shot.

    BRIDGE moments are EXEMPT from the moment cap (D6-6a). Rule 4b tells the
    planner in writing that a bridge is ADDITIVE — "it does NOT count against
    the {max_moments} cap above ... plan one more moment than the stated cap" —
    and rule 4b's own example puts the bridge at the location change, which on
    a scene that CLOSES on one lands past the cutoff. A blunt tail slice
    therefore silently deleted exactly the moment the prompt had just promised
    was free: found live on a 3-moment "escape" scene whose 4th moment WAS the
    escape, so the scene never showed the character get out. The cap now counts
    narrated moments only, so the two legs of the contract agree.

    Bridge-ness no longer depends ONLY on the LLM planner remembering to write
    the literal "(BRIDGE)" tag (D6-6c) — see _is_bridge_moment's docstring for
    the two additional structural signals (a per-moment location change, and
    S1 transit language in the moment's own summary), both gated on
    location_sets (rule 8's multi-location LOCSET blocks, from
    parse_location_sets(directive_text)) so an ordinary single-location scene
    is completely unaffected. location_sets=None (every call site before
    D6-6c) disables the new signals entirely and leaves this function
    byte-identical to its pre-D6-6c self.

    A bridge stays exempt only while it still sits BETWEEN two kept moments
    (rule 4b's own definition: inserted "BETWEEN the last narrated moment at
    the old location and the first narrated moment at the new one"). Once the
    moment before it has been trimmed away, it leads out of a location the cut
    never reaches — it stops being a bridge and goes back to needing a cap slot
    like any other moment.

    max_frames (optional) is a TOTAL frame ceiling on top of the per-moment
    caps (Ryan's channel pacing rule, e.g. ≤40 shots for a ~2-min film):
    angles are stripped from the tail moments first — masters (the lip-sync
    units and story beats) are never sacrificed for an angle. It is a hard
    provider ceiling (the Custom Film BOM path passes max_frames == the
    approved count) and the bridge exemption does NOT pierce it: an additive
    bridge that pushes a scene over max_frames is still trimmed back by the
    ceiling pass below, exactly as today."""
    planned = sum(1 + len(m.get("angles") or []) for m in moments)
    for m in moments:
        if isinstance(m.get("angles"), list) and len(m["angles"]) > angles_max:
            m["angles"] = m["angles"][:angles_max]
    kept: list = []
    narrated = 0        # moments that have consumed a cap slot
    bridges_exempt = 0
    prev_kept = True    # a bridge at index 0 has no earlier moment to bridge FROM
    prev_location = None  # location of the last KEPT moment (D6-6c signal 2)
    for m in moments:
        if (_is_bridge_moment(m, location_sets, prev_location) and prev_kept
                and bridges_exempt < _MAX_EXEMPT_BRIDGES):
            kept.append(m)
            bridges_exempt += 1
            prev_location = m.get("location") or prev_location
            continue
        if narrated < max_moments:
            kept.append(m)
            narrated += 1
            prev_kept = True
            prev_location = m.get("location") or prev_location
        else:
            prev_kept = False
    if len(kept) < len(moments):
        moments = kept
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
    if bridges_exempt and len(moments) > max_moments:
        # Say it out loud: the scene is over its stated moment cap ON PURPOSE,
        # so a reader of the logs never mistakes an additive bridge for the
        # budget leaking (no-silent-caps, in reverse).
        print(f"  🌉 {bridges_exempt} BRIDGE moment(s) kept as ADDITIVE (rule 4b) — "
              f"{len(moments)} moments against a {max_moments} narrated cap", flush=True)
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
                       canonical_envs=None, matched_env=None,
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
    unanchored — honest degradation, not silent wrong-panel composition).

    canonical_envs/matched_env (D6-1c, L20): the SAME approved-environment
    list and single scene-matched env dict coverage_to_app.generate_
    coverage_for_video already fetches via _approved_envs/_match_scene_env
    for props= above — reused (never re-queried; this module has no DB
    handle) so the MATERIAL MAP LOCK below can prefer video_environments.
    material_map over the planner's own [MATERIAL | ...] line, same
    precedence as the sheet PREVIEW path. Both None (every caller before
    this chunk, and the CLI's main()) is unchanged behavior — the fallback
    to parse_material_map(directive_text) fires exactly as it does today.

    The same two params (D9-3b, migration 152) also feed the ENVIRONMENT
    LOCKS block just below MATERIAL MAP LOCK — coverage_to_app.py's
    _approved_envs SELECT already fetches architecture_lock/lighting_time_
    weather_lock/palette_lock alongside material_map, so no new plumbing
    was needed, only canonical_environment_locks_line reading the same
    dicts. NULL locks (every row before an environment is re-approved post-
    migration-152) mean the block is omitted, same as material_map's
    fallback-to-prose story but with no prose to fall back to."""
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

    # BOARD LAWS gate leg (storyengine/BOARD-LAWS.md) — every deterministic
    # check built for this chunk, ALL warning-only, ALL run here on the same
    # freshly-parsed, pre-lock-tail descriptions as the facing-law check
    # above (for the identical reason: a lock tail's boilerplate would swamp
    # several of these with false positives if it ran after them).
    location_sets = parse_location_sets(directive_text)
    check_headcount_stated(moments)
    check_group_arrangement_stated(moments)
    check_camera_facts_present(moments)
    check_repeated_setup_frame_side(moments)
    check_motion_axis_anchor(moments)
    check_no_duplicate_panels(moments)
    check_material_map_present_when_mixed(directive_text)
    check_location_scoping(moments, location_sets)
    check_nested_frame_content_specified(moments)
    check_pov_setup_neutral_and_into_camera(moments)
    check_no_caption_leaking_labels(moments)
    # D6-2 NEW gates — L12, L15, L18 previously had no gate at all. Same
    # warning-only discipline as every check_* above.
    check_population_specified(moments)
    check_attention_orientation_stated(moments)
    check_discovery_object_unremarked(moments)
    # D9-1 (film-studio audit harvest): a shot with no stated narrative
    # purpose — same warning-only discipline as every check_* above.
    check_shot_purpose_present(moments)
    # D9-6/D9-7 (film-studio audit harvest, second harvest chunk): a shot
    # with no stated cut type, a non-continuous cut with no bridge, and a
    # shot with no/invalid causal reference — same warning-only discipline.
    check_shot_transition_present(moments)
    check_shot_transition_bridge_present(moments)
    check_shot_causality_present(moments)
    check_shot_causality_valid(moments)
    # D11-1 (film-studio audit follow-on): a shot tagged with an ARCHETYPE id
    # that isn't in the catalog — same warning-only discipline; absence is
    # never flagged since the row is optional (rule 27).
    check_shot_archetype_valid(moments)
    # D11-2 (film-studio audit follow-on): a shot's DP row with an
    # out-of-vocabulary camera_height/dof, a lens value outside 10-200mm, or
    # a malformed lens value — same warning-only discipline; absence is never
    # flagged since the row is optional (rule 28).
    check_shot_dp_valid(moments)
    # D12-3 (board rhythm report): a shot-size run, a lens-value run, or a
    # purpose-kind run beyond its own threshold — same warning-only
    # discipline; a shot missing the field it checks is absent from the
    # run entirely, so a legacy plan (or a plan that just never wrote a
    # given optional row) stays silent, same reasoning as D9-1/D11-2 above.
    check_shot_size_rhythm(moments)
    check_lens_rhythm(moments)
    check_purpose_monotony(moments)

    # D6-2 (migration 143, storyengine/backend/migrations/143_per_shot_
    # location_and_arrangement.sql): persist the per-moment location — which
    # already lives in memory (moment["location"], set by parse_coverage
    # from the "LOCATION: <name> |" moment-header prefix) but until now was
    # only ever baked into prose (the LOCSET set-dressing tail below), never
    # carried on the shot dict itself so nothing downstream could persist it
    # as data — onto every shot so generate_coverage_frames/store_scene can
    # write it into the new assets.shot_location column. Loss-free: a
    # single-location scene's moments carry location=None, unchanged.
    for m in moments:
        for shot in [m["master"], *(m.get("angles") or [])]:
            shot["shot_location"] = m.get("location")

    # D6-2 REPAIR LEGS — BOARD-LAWS.md L11/L12/L15/L16/L17/L19/L22 (see the
    # big comment block above apply_nested_frame_content_lock for the full
    # rationale). Run here, on the SAME freshly-parsed, pre-lock-tail
    # descriptions as the gates just above — identical ordering reasoning.
    _reverse_setup_pairs = parse_reverse_setup_pairs(parse_setups_line(directive_text))
    n_reverse_bg = apply_reverse_background_lock(moments, _reverse_setup_pairs)
    if n_reverse_bg:
        print(f"  🔄 reverse-angle background lock applied to {n_reverse_bg} shot(s) "
              "(L16, computed)", flush=True)
    n_arrangement = apply_group_arrangement_lock(moments, _reverse_setup_pairs)
    if n_arrangement:
        print(f"  👥 group-arrangement lock applied to {n_arrangement} shot(s) (L17/L22)",
              flush=True)
    n_nested = apply_nested_frame_content_lock(moments)
    if n_nested:
        print(f"  🖥️ nested-frame content lock applied to {n_nested} shot(s) (L11)", flush=True)
    n_population = apply_population_lock(moments)
    if n_population:
        print(f"  👤 population lock applied to {n_population} shot(s) (L12)", flush=True)
    n_attention = apply_attention_orientation_lock(moments)
    if n_attention:
        print(f"  🎯 attention-orientation lock applied to {n_attention} shot(s) (L15)", flush=True)
    n_pov = apply_pov_diegetic_lock(moments)
    if n_pov:
        print(f"  📷 diegetic-POV lock applied to {n_pov} shot(s) (L19)", flush=True)
    # L18 (A DISCOVERY OBJECT IS PLANTED WITHOUT BEING ANNOUNCED) deliberately
    # gets NO repair leg here — see check_discovery_object_unremarked's
    # docstring above. The fact it protects (an object staying un-emphasized
    # until its notice beat) is one-off narrative content specific to a
    # single moment, not a scene-wide constant that can be captured once and
    # repeated the way SET dressing, a population description or a headcount
    # can — and a naive "never change" stamp would directly contradict rule
    # 19's own instruction that shot size legitimately changes as coverage
    # moves in ("the SHOT SIZE changes... the OBJECT never does"). PROMPT
    # (rule 19) + GATE only; admitted honestly in this chunk's commit
    # message rather than pretending a repair exists.

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
    # L3 (LOCATION SCOPING) — a multi-location scene carries per-location
    # [LOCSET | name | text] blocks instead of one scene-wide [SET | ...]
    # line (rule 8). When present, each shot is stamped with ONLY its OWN
    # moment's location text (moment["location"], set by parse_coverage's
    # LOCATION: prefix) plus an explicit cross-contamination prohibition —
    # never the whole scene's blanket set_line, which is the exact bug L3's
    # provenance describes (a corridor shot drawn with bedroom furniture
    # because the lock read "identical in every shot of this scene"). A
    # location-tagged shot whose OWN location has no matching LOCSET block
    # (a planner slip) falls back to the plain set_line/insert_tail path
    # below so it never goes unstamped.
    set_line = parse_set_dressing(directive_text)
    # location_sets already computed above (BOARD LAWS gate leg) — reused here.
    if location_sets:
        for m in moments:
            loc = m.get("location")
            loc_text = location_sets.get(loc) if loc else None
            for shot in [m["master"], *(m.get("angles") or [])]:
                if loc_text:
                    other_names = [n for n in location_sets if n != loc]
                    others = f" (never the dressing of {', '.join(other_names)})" if other_names else ""
                    tail = (f"Set dressing, identical in every panel of this scene tagged "
                            f"'{loc}'{others}: {loc_text}.")
                    if _shot_tag(shot) == "INSERT":
                        tail += " This is a detail insert — no faces visible, detail only."
                    shot["description"] = f"{shot['description'].rstrip('. ')}. {tail}"
                elif set_line:
                    tail = f"Set dressing and character blocking, identical in every shot of this scene: {set_line}."
                    shot["description"] = f"{shot['description'].rstrip('. ')}. {tail}"
        print(f"  🪑 location-scoped set lock applied ({len(location_sets)} location(s))", flush=True)
    elif set_line:
        tail = f"Set dressing and character blocking, identical in every shot of this scene: {set_line}."
        insert_tail = (f"Set dressing continuity with the rest of this scene (lighting, palette, "
                       f"surfaces), identical throughout: {set_line}. This is a detail insert — "
                       f"no faces visible, detail only.")
        for m in moments:
            for shot in [m["master"], *(m.get("angles") or [])]:
                this_tail = insert_tail if _shot_tag(shot) == "INSERT" else tail
                shot["description"] = f"{shot['description'].rstrip('. ')}. {this_tail}"
        print("  🪑 set-dressing lock applied to every shot", flush=True)

    # MATERIAL MAP LOCK (L20): the set's solid/transparent boundary, stated
    # once on [MATERIAL | ...] (rule 9), stamped into every shot the same
    # way the set-dressing lock is — so a single-shot redraw can't quietly
    # re-invent the set as all-glass or all-solid.
    #
    # D6-1c: the CODE-RENDERED, canonical video_environments.material_map
    # (via canonical_envs/matched_env, threaded in from coverage_to_app's
    # SAME _approved_envs/_match_scene_env the PREVIEW path already uses)
    # WINS over the planner LLM's own [MATERIAL | ...] line — this real
    # per-shot draw prompt used to read ONLY the LLM's prose, silently
    # diverging from the $0.05 preview whenever a creator had authored a
    # canonical map. "" (never invents) when no canonical entry exists,
    # so parse_material_map(directive_text) fires exactly as it always has
    # — NULL-safe: every video_environments row in production today has
    # material_map NULL, so this branch is a no-op in practice until a row
    # is populated.
    _canonical_material = canonical_material_line(canonical_envs, location_sets, matched_env)
    material_line = _canonical_material or (parse_material_map(directive_text) or "")
    if material_line:
        tail = f"Material map, fixed for this whole set: {material_line}."
        for m in moments:
            for shot in [m["master"], *(m.get("angles") or [])]:
                shot["description"] = f"{shot['description'].rstrip('. ')}. {tail}"
        print("  🧱 material-map lock applied to every shot", flush=True)
    # D6-1c drift ALARM (warning-only, never blocks — see the function's own
    # docstring for why a canonical-vs-prose disagreement here still WARNs
    # rather than gates: a false positive would block a paying customer's
    # real draw over a wording difference).
    check_material_map_consistency(_canonical_material, directive_text)

    # ENVIRONMENT LOCKS (D9-3b, migration 152, Custom Film EnvironmentLock
    # harvest): three narrower canonical facts (architecture_lock/lighting_
    # time_weather_lock/palette_lock) harvested at environment-approval
    # time — stamped into every shot immediately after MATERIAL MAP LOCK
    # above, same per-shot stamping mechanics, same canonical_envs/
    # matched_env channel (D6-1c's already threaded down from
    # coverage_to_app.py; the SELECT feeding it was extended to fetch these
    # three columns in D9-3, so no new plumbing is needed here, only this
    # reader). Unlike material_map there is no planner-LLM [LOCKS | ...]
    # directive line to fall back to, so "" (no canonical row — every
    # caller before this chunk, and every video whose environments haven't
    # been re-approved since migration 152) simply omits the block —
    # byte-identical to before this chunk.
    env_locks_line = canonical_environment_locks_line(canonical_envs, location_sets, matched_env)
    if env_locks_line:
        tail = f"Environment locks, fixed for this whole set: {env_locks_line}."
        for m in moments:
            for shot in [m["master"], *(m.get("angles") or [])]:
                shot["description"] = f"{shot['description'].rstrip('. ')}. {tail}"
        print("  🔒 environment-locks lock applied to every shot", flush=True)

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
    #
    # L4 (MOTION IS LEGAL) fix: this tail used to say "the actors are PLANTED
    # and never move" UNCONDITIONALLY, on every scene regardless of content —
    # exactly the contradiction L4's provenance describes (a static-tableau
    # convention applied to a scene where a character wakes, crosses a room
    # and runs down a corridor, so the exit silently vanished). A scene with
    # a (BRIDGE) shot (rule 4b — a moving/location-changing beat) gets the
    # motion-capable phrasing instead; a purely planted scene is unaffected —
    # byte-identical tail text to before this law existed.
    setups_line = parse_setups_line(directive_text)
    if setups_line:
        if scene_has_motion(moments, location_sets):
            tail = (f"Camera kit for this scene — setups covering a planted conversation hold "
                    f"the actors still; a setup covering a moving beat (a BRIDGE, an exit, a "
                    f"run) is MOTION-CAPABLE instead and describes the move directly (exits "
                    f"frame-right and camera holds, travels alongside, runs toward the lens) — "
                    f"never freeze a moving beat into planted-body staging. Every shot is one of "
                    f"these setups: {setups_line}. When a setup letter repeats, name the same "
                    f"frame side or surface it progresses from; never repeat an earlier panel of "
                    f"this scene identically — escalate closer or wider instead.")
        else:
            tail = (f"Camera kit for this scene — the actors are PLANTED and never move; every "
                    f"shot is one of these setups viewing the same frozen staging: {setups_line}. "
                    f"When a setup letter repeats, name the same frame side or surface it "
                    f"progresses from; never repeat an earlier panel of this scene identically — "
                    f"escalate closer or wider instead.")
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
    #
    # D10-3c/D12-1: `story_bible` (this function's own parameter — see its
    # docstring above) already carries `narrative.genre` when
    # scene_aware_bible (coverage_to_app.py, D10-3a) attached one;
    # _genre_pacing_signal reads it straight off — no new run_coverage
    # parameter needed. GENRE_PACING then scales the base duration above by
    # the genre family's cut-rhythm factor. A video with no genre signal
    # gets genre=None here, which resolves to multiplier 1.0 — byte-
    # identical to pre-D12-1 durations.
    genre = _genre_pacing_signal(story_bible)
    n_durations = stamp_shot_durations(moments, genre=genre)
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
