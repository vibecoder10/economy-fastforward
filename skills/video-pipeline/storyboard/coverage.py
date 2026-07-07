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
)
from shared.channel_profile import load_profile  # noqa: E402
from orchestrator.pipeline_constants import Models  # noqa: E402

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
setups.{motivated_rule}
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

Third line — the camera kit, ONE line (rule 5e); 3-5 setups cover the whole scene:
[SETUPS | A: WS two-shot — <each body's exact spot on the set, distance apart, orientation to \
camera>; B: MCU OTS over <name>'s <left/right> shoulder onto <name>; C: MCU OTS over <name>'s \
<left/right> shoulder onto <name>, the matched reverse of B; D: matched CU pair, tighter B/C; \
E: INSERT on the props, no people]

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
Plan up to {max_moments} moments from the narration below; pick the moments that carry the scene.
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
            f"few SILENT moments (establishing/insert) around them for variety ---\n{listed}")
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


def panels_per_sheet_for(directive_text: str) -> int:
    """Gate-sheet panel capacity for THIS plan. New-format plans (with an
    [AXIS | ...] line) draw 9-panel 3x3 sheets — the adherence ceiling image
    models hold; legacy plans keep their original 12 so the board-anchor math
    (panel k -> sheet k//cap) still points at the right panel on sheets that
    were approved before the change. Sheet chunking and board anchoring MUST
    both call this on the SAME directive."""
    return 9 if _AXIS_RE.search(directive_text or "") else 12
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

def _url_of(result):
    return result.get("url") if isinstance(result, dict) else result


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
_STYLE_LOCK = (
    " STYLE LOCK: render in the EXACT same art style and rendering quality as the attached "
    "reference image(s). If the reference is a photoreal / live-action / 3D-CG render, this frame "
    "MUST be equally photoreal and realistic — never switch to 2D illustration, painting, cartoon "
    "or anime, and never change the art style or rendering between frames. "
    # A speaking moment's description mentions the spoken words — GPT Image 2
    # drew them as an English speech bubble on live frames (2026-07-03). A
    # character can be MOUTHING words; the words themselves never appear.
    "NEVER draw speech bubbles, dialogue balloons, captions or subtitles; on-screen text or "
    "lettering only if this shot's description explicitly asks for it. "
    # A description that narrates an ARC ("triumph turning to dread, glances at
    # the clock") made GPT Image 2 render a side-by-side two-panel diptych
    # (2026-07-06, PocoAPoco i120) — unusable as a clip source frame.
    "This is ONE SINGLE FRAME — one continuous scene from one camera at one instant. NEVER a "
    "split screen, diptych, side-by-side comparison, before/after, grid, collage, comic panels "
    "or any composition divided into sections. If the description mentions an emotional change, "
    "draw only the LAST beat of it.")

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

# Panels per gate sheet now depends on the plan's format — see
# panels_per_sheet_for(). Sheet chunking (coverage_to_app._plan_sheet_prompts
# caller) and the board-anchor math below must both use it on the same plan.


async def _gen_ref(image_client, prompt, refs, aspect, resolution, attempts=2):
    """Generate one frame via GPT Image 2 (gpt-image-2-image-to-image — our main model; holds the
    cast's identity from the reference sheet far better than nano-banana), with a light retry.
    ponytail: retry only covers transient None/502; a moderation 400 also returns None and may not
    recover — that frame is then skipped (coverage degrades to fewer angles rather than failing)."""
    for i in range(attempts):
        # A raised error (SSL reset, timeout, connection drop) must count as a
        # failed attempt, not escape — an escaped exception here used to kill
        # the whole scene's gather and stop the build mid-run.
        try:
            url = _url_of(await image_client.generate_thumbnail_gpt2(
                prompt, refs, aspect, resolution=resolution))
        except Exception as e:  # noqa: BLE001
            print(f"  frame gen error (attempt {i + 1}/{attempts}): {str(e)[:120]}", flush=True)
            url = None
        if url:
            return url
        await asyncio.sleep(2 * (i + 1))
    return None


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


def plan_camera_moves(moments: list) -> int:
    """Plan a camera move per shot across a scene's coverage moments, in shot
    order (master then angles, moment by moment). Mutates the shot dicts:
    appends the move's image_setup to the drawing description and stamps
    shot["camera_move"]. Returns how many shots earned a move. Best-effort —
    any failure leaves the scene exactly as it was (static/freeform behavior)."""
    try:
        from image_prompts.engine.camera_selector import ShotContext, select_camera_move
    except Exception:
        return 0

    planned = 0
    prev_ids: list = []
    prev_keys: list = []
    try:
        for mi, moment in enumerate(moments):
            shots = [("master", moment.get("master") or {})]
            shots += [("angle", a) for a in (moment.get("angles") or [])]
            speaking = bool(moment.get("speaker") and moment.get("line"))
            for role, shot in shots:
                if not shot.get("description"):
                    continue
                ctx = ShotContext(
                    sentence_text=f"{moment.get('summary') or ''}. {shot['description']}",
                    composition=_SHOT_TYPE_COMPOSITION.get(
                        (shot.get("shot_type") or "MS").upper(), "medium"),
                    # Lip-synced speaking shots want calm moves — cap intensity low
                    intensity="low" if (speaking and role == "master") else "medium",
                    is_scene_open=(mi == 0 and role == "master"),
                    is_scene_final=(mi == len(moments) - 1 and role == "master"),
                    prev_move_ids=prev_ids,
                    prev_legacy_keys=prev_keys,
                )
                sel = select_camera_move(ctx)
                if sel.move:
                    shot["camera_move"] = f"{sel.move.id}|{sel.purpose}"
                    shot["description"] = (
                        f"{shot['description'].rstrip('. ')}. "
                        f"Composed for a {sel.move.name.lower()} camera move: {sel.move.image_setup}"
                    )
                    prev_ids.append(sel.move.id)
                    prev_keys.append(sel.move.legacy_key)
                    planned += 1
                else:
                    shot["camera_move"] = "static"
                    prev_keys.append("static")
    except Exception as e:  # noqa: BLE001 — camera planning must never kill coverage
        print(f"  camera planning failed (shots stay freeform): {str(e)[:120]}", flush=True)
    return planned


async def generate_coverage_frames(moment, cast_url, image_client, profile,
                                   env_url=None, aspect="16:9", resolution="1K", sem=None) -> list[dict] | None:
    """Master frame (anchored on cast) -> each angle (anchored on cast + master).
    Returns frames [{role, shot_type, description, url}] or None if the master fails.
    The master MUST be drawn first (angles reference it), but the angles only depend on
    the master, not on each other — so they draw in PARALLEL. `sem` caps total Kie gens."""
    # cast_url may be one URL or a LIST (e.g. the locked per-character 4-view sheets).
    cast_refs = list(cast_url) if isinstance(cast_url, list) else [cast_url]
    base = cast_refs + ([env_url] if env_url else [])
    sem = sem or asyncio.Semaphore(1)  # no semaphore passed => serial fallback

    async def _gen(prompt, refs):
        async with sem:
            return await _gen_ref(image_client, prompt, refs, aspect, resolution)

    def _board(shot):
        """(anchor_text, extra_ref) when this shot is pinned to an approved board panel.
        The board ref goes LAST so the anchor's 'LAST attached reference' holds."""
        if shot.get("board_url") and shot.get("board_panel"):
            return _BOARD_ANCHOR.format(panel=shot["board_panel"]), [shot["board_url"]]
        return "", []

    m = moment["master"]
    m_anchor, m_ref = _board(m)
    master_prompt = (build_image_prompt_from_keyframe({"composition": m["description"]}, profile)
                     + _STYLE_LOCK + m_anchor)
    master_url = await _gen(master_prompt, base + m_ref)  # master first — angles anchor on it
    if not master_url:
        return None
    frames = [{"role": "master", "shot_type": m["shot_type"], "description": m["description"],
               "camera_move": m.get("camera_move"), "url": master_url}]
    angle_base = cast_refs + [master_url] + ([env_url] if env_url else [])

    async def _angle(a):
        a_anchor, a_ref = _board(a)
        ap = (build_image_prompt_from_keyframe({"composition": a["description"]}, profile)
              + _SAME_SUBJECT + _STYLE_LOCK + a_anchor)
        url = await _gen(ap, angle_base + a_ref)
        return {"role": "angle", "shot_type": a["shot_type"], "description": a["description"],
                "camera_move": a.get("camera_move"), "url": url} if url else None

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
                           profile=None, aspect="16:9", outdir=None) -> str | None:
    """A locked cast wins; otherwise auto-build a cast sheet (from cast_prompt, else the
    story bible) so coverage always has an anchor. Returns the cast URL or None."""
    if cast_url:
        return cast_url
    cp = cast_prompt or cast_prompt_from_story_bible(story_bible, profile or load_profile({}))
    if not cp:
        return None
    print("No locked cast — auto-building a cast sheet (GPT Image 2) ...", flush=True)
    r = await image_client.generate_scene_image_gpt(cp, None, aspect)  # gpt-image-2 text-to-image
    url = r.get("url") if isinstance(r, dict) else r
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
                       board_urls=None) -> dict:
    """Build coverage for one scene/beat: directive -> parse -> matched frames per moment.
    A locked cast (cast_url) wins; otherwise a cast sheet is auto-built from the story
    bible (or cast_prompt) so coverage always has something to lock characters to.
    Saves frames + coverage.json locally with angle/shot-type metadata. No DB writes
    (storing into Image records is Phase 2, where the animator consumes them)."""
    profile = profile or load_profile({})
    os.makedirs(outdir, exist_ok=True)
    cast_url = await resolve_cast_url(cast_url, image_client, cast_prompt=cast_prompt,
                                      story_bible=story_bible, profile=profile,
                                      aspect=aspect, outdir=outdir)
    if not cast_url:
        return {"error": "no cast: provide cast_url, cast_prompt, or a story_bible with characters"}
    if directive_text is None:
        directive_text = await generate_coverage_directive(
            beat_text, video_title, profile, story_bible, beat_scenes, image_prompts or [],
            max_moments=max_moments, angles_min=angles_min, angles_max=angles_max,
            anthropic_client=anthropic_client, model=directive_model)
    with open(os.path.join(outdir, "directive.txt"), "w") as f:
        f.write(directive_text)

    moments = parse_coverage(directive_text)
    if not moments:
        return {"error": "no moments parsed from directive", "directive_chars": len(directive_text)}
    moments = enforce_shot_budget(moments, max_moments, angles_max, max_frames=max_frames)

    # SET-DRESSING LOCK: the planner declares the scene's fixed props once on the
    # [SET | ...] line; stamp it into EVERY shot's image prompt. Per-shot prompts
    # that stay silent about props let the image model invent them — observed
    # live (PocoAPoco kitchen): "cram session" phrasing conjured books/laptops in
    # some panels while the food vanished and reappeared between neighbours.
    set_line = parse_set_dressing(directive_text)
    if set_line:
        tail = f"Set dressing and character blocking, identical in every shot of this scene: {set_line}."
        for m in moments:
            m["master"]["description"] = f"{m['master']['description'].rstrip('. ')}. {tail}"
            for a in m.get("angles") or []:
                a["description"] = f"{a['description'].rstrip('. ')}. {tail}"
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

    # BOARD ANCHOR: pin each shot to its numbered panel on the approved gate
    # sheet(s). Panel numbers are GLOBAL across sheets and count masters then
    # angles in moment order — the exact order _plan_sheet_prompts drew them in
    # (same directive, same deterministic parse + budget, so the k-th shot here
    # IS panel k on the sheets). Only sound when the caller verified the sheets
    # came from THIS directive_text; a re-planned scene passes no board_urls.
    if board_urls:
        k = 0
        _cap = panels_per_sheet_for(directive_text)
        for m in moments:
            for shot in [m["master"], *(m.get("angles") or [])]:
                k += 1
                si = (k - 1) // _cap
                if si < len(board_urls) and board_urls[si]:
                    shot["board_url"], shot["board_panel"] = board_urls[si], k
        print(f"  📌 board anchor: {k} shots pinned to the approved sheet panels "
              f"({_cap}/sheet)", flush=True)

    # Camera Movement Engine: decide each shot's move NOW, before drawing, so
    # the stills are composed for their moves (storytelling formats only —
    # this path IS the storytelling pipeline; data formats never reach it).
    planned = plan_camera_moves(moments)
    if planned:
        print(f"  🎥 camera engine: {planned} shots planned with a move", flush=True)

    # Draw all moments CONCURRENTLY (each: master first, then its angles in parallel),
    # with one shared semaphore capping total in-flight Kie image gens. Collapses ~12
    # strictly-serial frames into ~2 sequential steps — scene coverage goes from ~20 min
    # to a few minutes. Set COVERAGE_CONCURRENCY to tune.
    sem = asyncio.Semaphore(_COVERAGE_CONCURRENCY)
    # return_exceptions: one moment blowing up must not kill the sibling
    # moments' gather — the scene keeps every moment that finished.
    moment_results = await asyncio.gather(*[
        generate_coverage_frames(moment, cast_url, image_client, profile,
                                 env_url=env_url, aspect=aspect, resolution=resolution, sem=sem)
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
