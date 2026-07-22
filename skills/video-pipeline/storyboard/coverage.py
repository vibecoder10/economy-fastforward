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


def _setup_id(shot) -> str | None:
    """The shot's camera-setup letter from its description tag, or None for
    legacy plans / NEUTRAL inserts without one."""
    m = _SETUP_TAG_RE.match(shot.get("description") or "")
    return m.group(1).upper() if m else None

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


def plan_camera_moves(moments: list, render_style: str | None = None,
                       video_model_id: str | None = None) -> int:
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
    except Exception:
        return 0

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
        budget = _scene_move_budget()
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
        print(f"  camera planning failed (shots stay freeform): {str(e)[:120]}", flush=True)
    return planned


async def generate_coverage_frames(moment, cast_url, image_client, profile,
                                   env_url=None, aspect="16:9", resolution="1K", sem=None,
                                   model_override=None, setup_anchors=None) -> list[dict] | None:
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
            return await _gen_ref(image_client, prompt, refs, aspect, resolution,
                                  model_override=model_override)

    def _resolve_owned(shot, url):
        """Resolve the setup future this shot owns (idempotent, never raises)."""
        if not shot.get("setup_anchor_owner"):
            return
        fut = setup_anchors.get(shot.get("setup_id"))
        if fut is not None and not fut.done():
            fut.set_result(url)

    async def _setup_ref(shot):
        """(anchor_text, extra_ref) for a non-owner shot whose setup already has
        an anchor frame. Empty for owners, unknown setups, and failed anchors."""
        sid = shot.get("setup_id")
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
               "image_model": master_model}]
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
                "image_model": model_used} if url else None

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
                       board_urls=None, model_override=None,
                       render_style=None, video_model_id=None) -> dict:
    """Build coverage for one scene/beat: directive -> parse -> matched frames per moment.
    A locked cast (cast_url) wins; otherwise a cast sheet is auto-built from the story
    bible (or cast_prompt) so coverage always has something to lock characters to.
    Saves frames + coverage.json locally with angle/shot-type metadata. No DB writes
    (storing into Image records is Phase 2, where the animator consumes them).

    model_override: videos.image_model_override ('nano-banana-2' | 'gpt-image-2' | 'z-image' |
    None). Threaded down to every frame draw via generate_coverage_frames/_gen_ref (the shared
    shared.clients.image_model_router resolver) AND to the cast-sheet auto-build below — GPT
    Image 2 stays the default and the content-policy/failure fallback either way.

    render_style/video_model_id (C13b): videos.render_style ('animated' | 'realistic' | None)
    and videos.video_model — the IMAGE model_override above never mixes with these, they're
    the separate CLIP-model routing guardrail, passed straight through to plan_camera_moves()
    (shot-plan time, before any frame is drawn) -> shared.model_router.route_shot_model()."""
    profile = profile or load_profile({})
    os.makedirs(outdir, exist_ok=True)
    cast_url = await resolve_cast_url(cast_url, image_client, cast_prompt=cast_prompt,
                                      story_bible=story_bible, profile=profile,
                                      aspect=aspect, outdir=outdir, model_override=model_override)
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
        # BALANCED boards (Ryan, 2026-07-21): panel->sheet is no longer a
        # fixed stride ((k-1)//cap) — boards are evenly sized via
        # sheet_chunk_sizes(), the SAME function _plan_sheet_prompts chunks
        # with, so anchoring and chunking cannot disagree on boundaries.
        # _bounds[i] = the last (1-based) global panel number on sheet i.
        _total = sum(1 + len(m.get("angles") or []) for m in moments)
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
    planned = plan_camera_moves(moments, render_style=render_style, video_model_id=video_model_id)
    if planned:
        print(f"  🎥 camera engine: {planned} shots planned with a move", flush=True)

    # SETUP ANCHORS (Ryan, 2026-07-21): tag every shot with its camera-setup id
    # and make the FIRST-planned shot of each setup that setup's anchor owner —
    # its landed frame becomes the canonical room every later same-setup shot
    # copies (see _SETUP_ANCHOR / generate_coverage_frames's docstring). Plan
    # order makes the wait graph acyclic; concurrency below is unchanged (an
    # owner never waits on a setup future, so the gather still fans out).
    setup_anchors: dict = {}
    anchored_shots = 0
    for moment in moments:
        for shot in [moment["master"], *(moment.get("angles") or [])]:
            sid = _setup_id(shot)
            if not sid:
                continue
            shot["setup_id"] = sid
            if sid not in setup_anchors:
                setup_anchors[sid] = asyncio.get_running_loop().create_future()
                shot["setup_anchor_owner"] = True
            else:
                anchored_shots += 1
    if anchored_shots:
        print(f"  🔗 setup anchors: {len(setup_anchors)} camera setups, "
              f"{anchored_shots} repeat shots will copy their setup's anchor frame", flush=True)

    # Draw all moments CONCURRENTLY (each: master first, then its angles in parallel),
    # with one shared semaphore capping total in-flight Kie image gens. Collapses ~12
    # strictly-serial frames into ~2 sequential steps — scene coverage goes from ~20 min
    # to a few minutes. Set COVERAGE_CONCURRENCY to tune.
    sem = asyncio.Semaphore(_COVERAGE_CONCURRENCY)
    # return_exceptions: one moment blowing up must not kill the sibling
    # moments' gather — the scene keeps every moment that finished.
    moment_results = await asyncio.gather(*[
        generate_coverage_frames(moment, cast_url, image_client, profile,
                                 env_url=env_url, aspect=aspect, resolution=resolution, sem=sem,
                                 model_override=model_override, setup_anchors=setup_anchors)
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
