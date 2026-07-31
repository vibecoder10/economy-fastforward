"""Shot Archetype Catalog — the durable vocabulary of professional static shot
setups (D11-1, film-studio audit follow-on).

WHY THIS EXISTS: the audit that harvested camera MOVEMENT into a 37-entry
metadata catalog (image_prompts/engine/camera_moves.py — this module's
structural template) found the STATIC shot vocabulary still a bare
unannotated string: `SHOT_TYPES = "ELS, WS, MS, MCU, CU, ECU, OTS, INSERT"`
(storyboard/coverage.py). That string still exists and still drives the
`shot_type` field every MASTER/ANGLE line declares — this catalog does not
replace it. What it adds is a RICHER, OPTIONAL descriptor: not just "how
tight is the frame" (shot_type) but "which professional archetype is this,
and why would a director reach for it" (purpose, emotion, avoid_when,
what it typically follows).

Same key idea as camera_moves.py: an archetype is a CONTRACT for the image
setup — ``image_setup`` is composition guidance the STILL IMAGE should follow
for the archetype to read as intended (mirrors CameraMove.image_setup's
phrasing style exactly, so the two catalogs slot into image-prompt
composition guidance the same way).

The coverage planner (storyboard/coverage.py's system prompt, rule 27) may
OPTIONALLY tag a shot with the closest archetype id from this catalog, via
its own trailing `ARCHETYPE: <id>` row — same "own row, never inside the
sentence" grammar as PURPOSE/TRANSITION/CAUSED_BY (D9-1/D9-6/D9-7). Extracted
by coverage.py's `_strip_shot_metadata_rows`, validated (warn-only, D6 Ruling
1) by coverage.py's `check_shot_archetype_valid` against THIS catalog —
lookup and menu-rendering live here; the coverage-specific parse/check glue
lives in coverage.py, same separation camera_moves.py keeps from its own
selector (camera_selector.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Categories — exactly the six the D11-1 brief specifies. Order here is the
# order format_archetype_menu() groups and prints them in.
CATEGORY_ESTABLISHING = "establishing"
CATEGORY_COVERAGE = "coverage"
CATEGORY_DETAIL = "detail"
CATEGORY_ANGLE = "angle"
CATEGORY_COMPOSITION = "composition"
CATEGORY_SPECIALTY = "specialty"

CATEGORY_ORDER = (
    CATEGORY_ESTABLISHING, CATEGORY_COVERAGE, CATEGORY_DETAIL,
    CATEGORY_ANGLE, CATEGORY_COMPOSITION, CATEGORY_SPECIALTY,
)


@dataclass(frozen=True)
class ShotArchetype:
    """One professional shot archetype: what it's for, what it costs, and
    what the still image needs to look like for it to read correctly."""

    id: str
    name: str
    aliases: tuple            # other names a planner or human might call this
    category: str             # one of CATEGORY_* above
    purpose: str               # why a director reaches for this shot — the prompt-menu line
    emotion: str                # the feeling/effect this archetype typically serves
    typical_duration_s: float   # a reasonable single-shot screen duration, seconds
    typical_lens: str           # plain-English focal-length guidance
    image_setup: str            # composition the still image should follow (mirrors CameraMove)
    avoid_when: str = ""        # plain-English condition that breaks this archetype
    pairs_well_after: tuple = field(default_factory=tuple)  # archetype ids this often follows


SHOT_ARCHETYPES: dict[str, ShotArchetype] = {a.id: a for a in [

    # ------------------------------------------------------------------
    # ESTABLISHING
    # ------------------------------------------------------------------
    ShotArchetype(
        id="establishing_wide", name="Establishing Wide",
        aliases=("master establishing shot", "scene opener"),
        category=CATEGORY_ESTABLISHING,
        purpose="opens a scene by showing the whole space and where everyone stands in it",
        emotion="orientation, calm confidence in the geography",
        typical_duration_s=4.0, typical_lens="24-35mm wide",
        image_setup="compose the full set edge to edge with every character placed at their "
                    "declared position, generous headroom, nothing cropped",
        avoid_when="the scene has already been established earlier and nothing has changed",
    ),
    ShotArchetype(
        id="extreme_wide", name="Extreme Wide (ELS)",
        aliases=("extreme long shot", "vista shot"),
        category=CATEGORY_ESTABLISHING,
        purpose="shows a character or subject dwarfed by a vast space — pure scale",
        emotion="isolation, awe, insignificance against the world",
        typical_duration_s=3.5, typical_lens="16-24mm ultra-wide",
        image_setup="place the subject small within the frame, surrounded on most sides by open "
                    "environment, strong horizon or vanishing point",
        avoid_when="the beat is intimate — extreme distance reads as detachment, not connection",
    ),
    ShotArchetype(
        id="aerial_establishing", name="Aerial Establishing",
        aliases=("drone establishing shot", "birds-eye establishing"),
        category=CATEGORY_ESTABLISHING,
        purpose="opens on a location from above to show its full layout before dropping to eye level",
        emotion="scale, scope, the world before the story",
        typical_duration_s=4.0, typical_lens="24mm wide, elevated",
        image_setup="compose from a high aerial vantage with the location's full footprint "
                    "visible, roads/paths/structures readable as a layout",
        avoid_when="the scene is an interior — nothing to see from above",
    ),
    ShotArchetype(
        id="environmental_wide", name="Environmental Wide",
        aliases=("wide in context",),
        category=CATEGORY_ESTABLISHING,
        purpose="shows a character doing something WITHIN their environment — place and action together",
        emotion="context, the character belongs to (or is shaped by) this place",
        typical_duration_s=3.5, typical_lens="24-35mm wide",
        image_setup="compose the character at a natural human scale within the frame, environment "
                    "detail readable around them, action legible from this distance",
    ),
    ShotArchetype(
        id="location_reveal", name="Location Reveal",
        aliases=("new location reveal",),
        category=CATEGORY_ESTABLISHING,
        purpose="the FIRST shot of a new location in the story — tells the audience where they are now",
        emotion="a beat of arrival, sometimes surprise",
        typical_duration_s=3.5, typical_lens="24-35mm wide",
        image_setup="compose the space with its single most identifying feature dead center or on "
                    "a strong third, immediately legible as a NEW place",
        pairs_well_after=("establishing_wide", "aerial_establishing"),
    ),

    # ------------------------------------------------------------------
    # COVERAGE (the workhorse sizes + standard dialogue/action angles)
    # ------------------------------------------------------------------
    ShotArchetype(
        id="wide", name="Wide Shot (WS)",
        aliases=("full shot of the space",),
        category=CATEGORY_COVERAGE,
        purpose="shows full bodies and their staging relative to each other and the set",
        emotion="neutral default — geography over feeling",
        typical_duration_s=3.0, typical_lens="28-35mm",
        image_setup="compose full figures head to foot with margin above and below, staging and "
                    "spacing between characters clearly readable",
    ),
    ShotArchetype(
        id="full", name="Full Shot",
        aliases=("full figure shot",),
        category=CATEGORY_COVERAGE,
        purpose="frames a single character head to toe — body language and wardrobe read fully",
        emotion="neutral, presentational",
        typical_duration_s=3.0, typical_lens="35-50mm",
        image_setup="compose one character head to foot filling most of the frame height, full "
                    "posture and gesture visible",
    ),
    ShotArchetype(
        id="cowboy", name="Cowboy Shot",
        aliases=("mid-thigh shot", "american shot"),
        category=CATEGORY_COVERAGE,
        purpose="frames mid-thigh up — enough body language for a confrontation or a hands-on-hips beat",
        emotion="confidence, readiness, a standoff",
        typical_duration_s=3.0, typical_lens="35-50mm",
        image_setup="compose from mid-thigh up, hands and stance visible, enough width to show "
                    "a weapon, tool, or prop at the hip if the beat calls for one",
    ),
    ShotArchetype(
        id="medium", name="Medium Shot (MS)",
        aliases=("waist-up shot", "conversational default"),
        category=CATEGORY_COVERAGE,
        purpose="the default conversational frame — waist up, gesture and expression both readable",
        emotion="neutral, the workhorse of dialogue coverage",
        typical_duration_s=3.0, typical_lens="35-50mm",
        image_setup="compose waist-up, both hands visible if gesturing, natural conversational "
                    "eyeline",
    ),
    ShotArchetype(
        id="medium_close", name="Medium Close-Up (MCU)",
        aliases=("chest-up shot",),
        category=CATEGORY_COVERAGE,
        purpose="chest up — carries the emotional weight of dialogue without going fully intimate",
        emotion="engagement, the audience leaning in",
        typical_duration_s=2.5, typical_lens="50-85mm",
        image_setup="compose chest up, face sharp and well-lit, shoulders anchoring the bottom "
                    "of frame",
    ),
    ShotArchetype(
        id="close", name="Close-Up (CU)",
        aliases=("face shot",),
        category=CATEGORY_COVERAGE,
        purpose="fills the frame with the face — the audience reads the exact expression",
        emotion="intimacy, emphasis, a moment that matters",
        typical_duration_s=2.5, typical_lens="85-100mm",
        image_setup="compose the face filling most of the frame, eyes sharp, minimal background "
                    "visible",
        avoid_when="the moment is casual or informational — a close-up spends emotional capital",
    ),
    ShotArchetype(
        id="extreme_close", name="Extreme Close-Up (ECU)",
        aliases=("macro face shot", "eyes-only shot"),
        category=CATEGORY_COVERAGE,
        purpose="isolates one feature (eyes, hands, mouth) — maximum emphasis, often a turning point",
        emotion="tension, revelation, the beat the whole scene has been building to",
        typical_duration_s=2.0, typical_lens="100mm+ macro",
        image_setup="compose a single feature filling the entire frame, everything else cropped "
                    "away",
        avoid_when="used more than once or twice a scene — it stops reading as special",
    ),
    ShotArchetype(
        id="ots", name="Over-the-Shoulder (OTS)",
        aliases=("over shoulder shot", "dirty single"),
        category=CATEGORY_COVERAGE,
        purpose="anchors a listener in frame while favoring the speaker — the standard dialogue reverse",
        emotion="connection between two people, conversational presence",
        typical_duration_s=3.0, typical_lens="50-85mm",
        image_setup="compose over one character's shoulder — their head and shoulder soft in the "
                    "near foreground, the speaker sharp beyond, both faces or profiles readable",
    ),
    ShotArchetype(
        id="pov", name="Point of View (POV)",
        aliases=("subjective camera", "diegetic pov"),
        category=CATEGORY_COVERAGE,
        purpose="puts the audience directly in a character's eyes for one beat",
        emotion="subjectivity, immersion, sometimes dread",
        typical_duration_s=2.5, typical_lens="24-35mm wide",
        image_setup="compose as a first-person view with no visible protagonist, framed neutrally "
                    "and looking straight into what the character is looking at",
    ),
    ShotArchetype(
        id="two_shot", name="Two-Shot",
        aliases=("dual shot",),
        category=CATEGORY_COVERAGE,
        purpose="holds two characters in one frame — their relationship IS the shot",
        emotion="relationship, shared stakes",
        typical_duration_s=3.5, typical_lens="35-50mm",
        image_setup="compose both characters in frame together, their relative distance and body "
                    "orientation to each other doing the emotional work",
    ),
    ShotArchetype(
        id="group_shot", name="Group Shot",
        aliases=("ensemble shot",),
        category=CATEGORY_COVERAGE,
        purpose="holds three or more characters — establishes who is present and how they're arranged",
        emotion="collective stakes, a crowd's mood",
        typical_duration_s=3.5, typical_lens="28-35mm",
        image_setup="compose every named character in frame at a legible size, arrangement and "
                    "attention (who's looking at whom) explicitly stated",
    ),
    ShotArchetype(
        id="clean_single", name="Clean Single",
        aliases=("clean over",),
        category=CATEGORY_COVERAGE,
        purpose="frames one speaker alone, no listener visible — isolates their reaction or line",
        emotion="focus entirely on this one character",
        typical_duration_s=2.5, typical_lens="50-85mm",
        image_setup="compose one character alone filling the frame, no second body or shoulder "
                    "intruding into the composition",
        pairs_well_after=("ots",),
    ),
    ShotArchetype(
        id="walk_and_talk", name="Walk-and-Talk",
        aliases=("tracking dialogue shot",),
        category=CATEGORY_COVERAGE,
        purpose="keeps two moving characters framed together while they talk — momentum and dialogue at once",
        emotion="urgency, forward motion, business getting done",
        typical_duration_s=4.0, typical_lens="35-50mm",
        image_setup="compose both characters mid-stride, travel direction clear, open space ahead "
                    "of them for the motion to read",
        avoid_when="the beat is static or seated — nothing to walk through",
    ),

    # ------------------------------------------------------------------
    # DETAIL
    # ------------------------------------------------------------------
    ShotArchetype(
        id="insert", name="Insert",
        aliases=("prop insert", "detail shot"),
        category=CATEGORY_DETAIL,
        purpose="a tight cutaway to an object or detail the story needs the audience to register",
        emotion="a fact plainly stated — rarely emotional on its own",
        typical_duration_s=2.0, typical_lens="85-100mm macro",
        image_setup="compose the object alone, filling most of the frame, no people, background "
                    "soft or empty",
    ),
    ShotArchetype(
        id="cutaway", name="Cutaway",
        aliases=("reaction cutaway",),
        category=CATEGORY_DETAIL,
        purpose="briefly leaves the main action to show something happening elsewhere in the same space/time",
        emotion="context, dramatic irony, or a ticking clock",
        typical_duration_s=2.0, typical_lens="35-50mm",
        image_setup="compose the secondary subject/action clearly, distinct enough from the main "
                    "shot that the cut reads as deliberate, not confusing",
    ),
    ShotArchetype(
        id="macro_detail", name="Macro Detail",
        aliases=("extreme detail shot",),
        category=CATEGORY_DETAIL,
        purpose="magnifies texture or fine mechanism — the tiny thing that carries big meaning",
        emotion="precision, obsession, or wonder at scale",
        typical_duration_s=2.0, typical_lens="100mm+ macro",
        image_setup="compose extremely close on texture/mechanism, shallow depth of field, the "
                    "rest of the object out of focus or out of frame",
    ),
    ShotArchetype(
        id="discovery_insert", name="Discovery Insert",
        aliases=("planted-object reveal",),
        category=CATEGORY_DETAIL,
        purpose="reveals an object the story has planted, without announcing its importance yet",
        emotion="quiet significance the audience will only understand later",
        typical_duration_s=2.0, typical_lens="85mm",
        image_setup="compose the object neutrally among ordinary surroundings — visible but not "
                    "spotlit, so its importance isn't telegraphed",
        pairs_well_after=("wide", "medium"),
    ),
    ShotArchetype(
        id="texture_detail", name="Texture Detail",
        aliases=("surface detail shot",),
        category=CATEGORY_DETAIL,
        purpose="lingers on a surface or material to set mood before or after the main action",
        emotion="atmosphere, a breath between beats",
        typical_duration_s=2.5, typical_lens="85-100mm",
        image_setup="compose a surface or material filling the frame, raking light to bring out "
                    "texture, no people",
    ),
    ShotArchetype(
        id="action_detail", name="Action Detail",
        aliases=("hands-doing-the-thing shot",),
        category=CATEGORY_DETAIL,
        purpose="isolates the hands or feet actually performing an action — mechanics over face",
        emotion="competence, tension, or urgency in the doing",
        typical_duration_s=2.0, typical_lens="50-85mm",
        image_setup="compose hands/feet mid-action filling most of the frame, the specific "
                    "mechanical detail of the action clearly legible",
    ),

    # ------------------------------------------------------------------
    # ANGLE (camera position/height, not framing size)
    # ------------------------------------------------------------------
    ShotArchetype(
        id="dutch", name="Dutch Angle",
        aliases=("canted angle", "tilted frame"),
        category=CATEGORY_ANGLE,
        purpose="tilts the horizon to signal something is wrong — disorientation as composition",
        emotion="unease, instability, danger",
        typical_duration_s=2.5, typical_lens="35-50mm",
        image_setup="compose with the horizon/verticals tilted off level, the tilt reinforcing "
                    "the subject's imbalance or threat",
        avoid_when="the beat is calm — a canted frame reads as alarm even when nothing is wrong",
    ),
    ShotArchetype(
        id="low_angle", name="Low Angle",
        aliases=("hero angle", "looking-up shot"),
        category=CATEGORY_ANGLE,
        purpose="shoots up at the subject so they dominate the frame — power, threat, or heroism",
        emotion="power, intimidation, or triumph",
        typical_duration_s=2.5, typical_lens="24-35mm wide",
        image_setup="compose from below eye level looking up, subject looming against sky or "
                    "ceiling, foreground ground plane visible at the bottom",
        avoid_when="the shot is meant to be intimate or vulnerable — low-angle reads as power",
    ),
    ShotArchetype(
        id="high_angle", name="High Angle",
        aliases=("looking-down shot",),
        category=CATEGORY_ANGLE,
        purpose="shoots down at the subject — diminishes them, or simply surveys the space",
        emotion="vulnerability, smallness, or god's-eye detachment",
        typical_duration_s=2.5, typical_lens="24-35mm wide",
        image_setup="compose from above eye level looking down, subject smaller in frame, ground "
                    "or floor detail visible around them",
    ),
    ShotArchetype(
        id="top_down", name="Top-Down (Bird's-Eye Flat)",
        aliases=("directly overhead shot", "flat lay shot"),
        category=CATEGORY_ANGLE,
        purpose="a perfectly vertical overhead view — turns a layout into a graphic, map-like image",
        emotion="clinical clarity, sometimes surveillance",
        typical_duration_s=3.0, typical_lens="35mm, directly overhead",
        image_setup="compose as a flat top-down view directly above the subject, arranged with "
                    "graphic clarity like a diagram or map",
        avoid_when="the scene's meaning depends on faces or horizon lines",
    ),
    ShotArchetype(
        id="profile", name="Profile Shot",
        aliases=("side-on shot",),
        category=CATEGORY_ANGLE,
        purpose="shoots a character dead-on from the side — graphic, formal, or confrontational",
        emotion="formality, distance, or a face-off between two profiles",
        typical_duration_s=2.5, typical_lens="50-85mm",
        image_setup="compose the subject in strict side profile, camera perpendicular to their "
                    "eyeline, features cleanly silhouetted against the background",
    ),
    ShotArchetype(
        id="worms_eye", name="Worm's-Eye View",
        aliases=("ground-level looking-up shot",),
        category=CATEGORY_ANGLE,
        purpose="shoots from ground level straight up — extreme scale and disorientation",
        emotion="awe, threat, or complete powerlessness",
        typical_duration_s=2.5, typical_lens="16-24mm ultra-wide",
        image_setup="compose from ground level looking almost straight up, the subject towering "
                    "and foreshortened, sky or ceiling filling most of the frame",
        avoid_when="the moment is small or quiet — this angle is inherently monumental",
    ),
    ShotArchetype(
        id="birds_eye", name="Bird's-Eye (High Aerial)",
        aliases=("high aerial angle",),
        category=CATEGORY_ANGLE,
        purpose="a high, angled aerial view (not perfectly vertical) that surveys action from above",
        emotion="scope, detachment, watching the pieces move",
        typical_duration_s=3.0, typical_lens="24-35mm, elevated",
        image_setup="compose from a high angled vantage with the action and its surroundings both "
                    "readable, subjects small but distinct",
    ),

    # ------------------------------------------------------------------
    # COMPOSITION (graphic/framing treatment)
    # ------------------------------------------------------------------
    ShotArchetype(
        id="static_symmetry", name="Static Symmetry",
        aliases=("centered symmetrical shot",),
        category=CATEGORY_COMPOSITION,
        purpose="a perfectly centered, symmetrical frame — order, formality, or control",
        emotion="stillness, control, sometimes unease at the perfection",
        typical_duration_s=3.0, typical_lens="35-50mm",
        image_setup="compose with the subject dead center and the frame's left and right halves "
                    "mirroring each other as closely as the set allows",
    ),
    ShotArchetype(
        id="nested_frame", name="Nested Frame",
        aliases=("frame within a frame",),
        category=CATEGORY_COMPOSITION,
        purpose="frames the subject through a doorway, window, or other architectural frame",
        emotion="confinement, voyeurism, or a sense of being observed",
        typical_duration_s=3.0, typical_lens="35-50mm",
        image_setup="compose the subject visible through a doorway, window, archway or similar "
                    "opening that itself frames the edges of the shot",
        avoid_when="no natural architectural frame exists in the set",
    ),
    ShotArchetype(
        id="silhouette", name="Silhouette",
        aliases=("backlit silhouette",),
        category=CATEGORY_COMPOSITION,
        purpose="strips the subject to pure shape against a bright background — identity through form alone",
        emotion="mystery, drama, or anonymity",
        typical_duration_s=3.0, typical_lens="35-50mm",
        image_setup="compose the subject as a dark shape against a bright backlit background "
                    "(window, sunset, doorway), no facial detail visible, silhouette shape clean",
    ),
    ShotArchetype(
        id="reflection", name="Reflection Shot",
        aliases=("mirror composition",),
        category=CATEGORY_COMPOSITION,
        purpose="shows the subject in a mirror, window, or water surface instead of directly",
        emotion="introspection, duality, or a truth the subject can't face directly",
        typical_duration_s=3.0, typical_lens="50-85mm",
        image_setup="compose the subject's reflection sharp and central in a mirror, glass, or "
                    "water surface, the reflective surface's edges visible in frame",
        avoid_when="no reflective surface exists in the set",
    ),
    ShotArchetype(
        id="reveal_framing", name="Reveal Framing",
        aliases=("staged reveal composition",),
        category=CATEGORY_COMPOSITION,
        purpose="composes the frame so the payoff detail is deliberately withheld until the shot lands",
        emotion="anticipation resolving into surprise or dread",
        typical_duration_s=3.0, typical_lens="35-50mm",
        image_setup="compose with the payoff element placed so it reads only once the eye travels "
                    "to it — off to one side, partially obscured, or at the edge of focus",
    ),
    ShotArchetype(
        id="negative_space", name="Negative Space",
        aliases=("isolation composition",),
        category=CATEGORY_COMPOSITION,
        purpose="surrounds a small subject with a large empty field — loneliness or scale through emptiness",
        emotion="isolation, smallness, quiet",
        typical_duration_s=3.0, typical_lens="35-50mm",
        image_setup="compose the subject small within the frame, most of the composition given "
                    "over to open, empty space around them",
    ),
    ShotArchetype(
        id="foreground_frame", name="Foreground Frame",
        aliases=("shooting through an object",),
        category=CATEGORY_COMPOSITION,
        purpose="shoots through a foreground object (foliage, rails, glass) to add depth and a hidden vantage",
        emotion="voyeurism, intimacy, or being watched",
        typical_duration_s=2.5, typical_lens="50-85mm",
        image_setup="compose with an out-of-focus foreground element partially obscuring the "
                    "frame's edges, the subject sharp beyond it",
        avoid_when="no natural foreground element exists to shoot through",
    ),

    # ------------------------------------------------------------------
    # SPECIALTY (situational, used sparingly)
    # ------------------------------------------------------------------
    ShotArchetype(
        id="memory_flash", name="Memory Flash",
        aliases=("flashback insert",),
        category=CATEGORY_SPECIALTY,
        purpose="a brief, visually distinct insert of a remembered or imagined moment",
        emotion="the past intruding on the present",
        typical_duration_s=2.0, typical_lens="50mm, softer focus",
        image_setup="compose with a visually distinct treatment from the surrounding scene — "
                    "softer focus, different light, or desaturated color — so it reads as memory",
        avoid_when="the scene has no established memory/flashback device to cut to",
    ),
    ShotArchetype(
        id="freeze_reaction", name="Freeze Reaction",
        aliases=("held reaction shot",),
        category=CATEGORY_SPECIALTY,
        purpose="holds on a character's face at the exact instant they register something — no action, pure reaction",
        emotion="the emotional hinge of the scene",
        typical_duration_s=2.5, typical_lens="85mm",
        image_setup="compose tight on the face at the precise beat of realization, everything "
                    "else in the frame secondary to the expression",
        pairs_well_after=("close", "extreme_close"),
    ),
    ShotArchetype(
        id="whip_reveal", name="Whip Reveal",
        aliases=("snap-pan reveal",),
        category=CATEGORY_SPECIALTY,
        purpose="a sudden reframe that reveals a second subject the audience didn't know was there",
        emotion="shock, comic timing, or a jolt of new information",
        typical_duration_s=1.5, typical_lens="35-50mm",
        image_setup="compose the reveal subject fully framed and unmistakable — the surprise "
                    "comes from the cut/motion into it, not from hiding it once it lands",
        avoid_when="the tone is slow and contemplative",
    ),
    ShotArchetype(
        id="split_diopter", name="Split Diopter",
        aliases=("dual-focus composition",),
        category=CATEGORY_SPECIALTY,
        purpose="keeps a near and far subject both in sharp focus at once — two things matter equally, right now",
        emotion="tension between two simultaneous truths",
        typical_duration_s=3.0, typical_lens="35mm near / 85mm far, both sharp",
        image_setup="compose one subject close in the foreground and a second subject distant in "
                    "the background, BOTH rendered in crisp focus simultaneously",
        avoid_when="only one subject in the scene actually matters right now",
    ),
    ShotArchetype(
        id="hero_shot", name="Hero Shot",
        aliases=("iconic pose shot",),
        category=CATEGORY_SPECIALTY,
        purpose="a deliberately iconic, poster-worthy framing of a character at a triumphant beat",
        emotion="triumph, arrival, the moment the story has built toward",
        typical_duration_s=3.0, typical_lens="24-35mm wide, low",
        image_setup="compose the subject centered or on a strong third, striking a deliberate "
                    "pose, generous space around them, dramatic light",
        avoid_when="used more than once — a hero shot is a single peak, not a recurring size",
    ),
    ShotArchetype(
        id="long_lens_compression", name="Long-Lens Compression",
        aliases=("compressed telephoto shot",),
        category=CATEGORY_SPECIALTY,
        purpose="a long lens flattens the space between subject and background — closeness or crowding without proximity",
        emotion="claustrophobia, false intimacy, or being boxed in",
        typical_duration_s=2.5, typical_lens="135-200mm telephoto",
        image_setup="compose the subject against a background that reads unnaturally close behind "
                    "them, flattened depth, background details enlarged relative to normal",
    ),
    ShotArchetype(
        id="wide_lens_distortion", name="Wide-Lens Distortion",
        aliases=("fisheye-adjacent shot",),
        category=CATEGORY_SPECIALTY,
        purpose="an aggressively wide lens close to the subject exaggerates size and distance — unsettling emphasis",
        emotion="disorientation, aggression, or dreamlike wrongness",
        typical_duration_s=2.0, typical_lens="14-20mm ultra-wide, close",
        image_setup="compose with the nearest subject/object exaggerated in size relative to "
                    "everything behind it, edges of the frame slightly bowing",
        avoid_when="the beat is calm or naturalistic — this look is inherently stylized",
    ),
]}


def get_archetype(archetype_id: str) -> ShotArchetype | None:
    """Look up a catalog archetype by id. Returns None for unknown/blank ids.
    Case/whitespace tolerant (mirrors camera_moves.get_move), since a planner
    may write ``ARCHETYPE: Close_Up`` where the canonical id is ``close``."""
    if not archetype_id:
        return None
    return SHOT_ARCHETYPES.get(archetype_id.strip().lower())


def archetypes_for_category(category: str) -> list[ShotArchetype]:
    """All archetypes in the given category, catalog order."""
    return [a for a in SHOT_ARCHETYPES.values() if a.category == category]


def format_archetype_menu() -> str:
    """Compact, prompt-ready menu of the whole catalog, grouped by category —
    one line per archetype: ``id — purpose`` with ``avoid_when`` appended in
    parens only where it exists (deliberately terse: this block is injected
    into the coverage system prompt on every call, so its size is a real
    token-budget line item, not just documentation)."""
    lines = []
    for cat in CATEGORY_ORDER:
        members = archetypes_for_category(cat)
        if not members:
            continue
        lines.append(f"{cat.upper()}:")
        for a in members:
            tail = f" (avoid when {a.avoid_when})" if a.avoid_when else ""
            lines.append(f"  {a.id} — {a.purpose}{tail}")
    return "\n".join(lines)


# =============================================================================
# D11-3 (mechanical prompt compiler — film-studio audit point 18 closure,
# Ryan: "the prompt assembler was not really mechanical but really invented
# from the ai — are the prompts mechanically assembled from the database of
# the shot angles and cinematography language?"). Before this chunk,
# shot_archetype/lens_mm/camera_height/dof (D11-1/D11-2) were parsed,
# validated (warn-only) and PERSISTED, but never actually CONSUMED by prompt
# assembly — the draw prompt's cinematography language was still 100% the
# planner LLM's own prose, with these structured fields riding alongside as
# inert metadata. compose_shot_cinematography is the fix: a PURE function
# that translates those fields into the clause that LEADS the draw prompt,
# every assembly point (skills/video-pipeline/storyboard/coverage.py's
# generate_coverage_frames, storyengine/backend/scripts/coverage_to_app.py's
# _plan_sheet_prompts and redraw_asset_image) now calls instead of drawing
# straight from the planner's free prose.
#
# COOKIE-CUTTER GUARD (Ryan's amendment, same day): "make sure how it gets
# assembled is strategic and not robotic, the last thing we want is a
# cookie-cutter video." Three deliberate scope limits keep this true:
#   1. CRAFT ONLY, NEVER SCENE MOOD. This function ADDS geometry/optics
#      facts only — framing, lens, height, depth, plus the archetype's own
#      composition guidance and (item 3, below) a plain location name — and
#      NOTHING ELSE. It never invents mood, lighting, or palette language of
#      its own; those keep flowing from the scene's own data (story-bible
#      mood/tension, environment locks, channel color grade, genre) through
#      their EXISTING channels (the <channel_style> block, the
#      [MATERIAL|]/environment-lock lines, the planner's own prose) —
#      channels this function never reads and never touches. Honest caveat:
#      a HANDFUL of the 45 catalog entries above (predating this chunk, from
#      D11-1) embed an archetype-INTRINSIC optical trait in their own
#      image_setup text where the treatment defines the shot itself, not a
#      per-scene choice this compiler is making — e.g. silhouette's required
#      backlight, hero_shot's dramatic light, texture_detail's raking light.
#      Those are catalog content (audited at D11-1, unchanged here), not
#      output this function invents; verbatim reproduction is the whole
#      point (see the planted-marker proof). The same archetype chosen in
#      two different scenes still produces two DIFFERENT full prompts,
#      because everything surrounding this clause (subject, style, palette,
#      environment) differs even when the clause itself doesn't.
#   2. COMPACT, NEVER DOMINANT. Target one-to-two sentences — the archetype
#      segment plus the DP segment, nothing more. The shot's own AI-written
#      subject/action sentence (rule 29's job for a tagged shot) stays the
#      dominant content of the final prompt; this clause leads it, never
#      swamps it.
#   3. DATA-DRIVEN VARIETY, NEVER RANDOMIZED. Where a deterministic,
#      non-prose signal is already available on the shot (shot_location —
#      D6-2/migration 143, parsed from the moment's own "LOCATION: <name> |"
#      header prefix, never LLM prose written INTO this clause), the
#      ESTABLISHING category's clause interpolates it — "this is <name>" —
#      so an establishing shot doesn't read as a context-free stock phrase
#      across scenes that actually happen in different places. Absent a
#      known location (every single-location scene, and every scene before
#      D6-2 existed), or for any non-establishing archetype, no
#      interpolation happens — same fields in, same clause out, always;
#      variety comes from the DATA differing, never from chance.
#   CHOICE DIVERSITY IS GUARDED ELSEWHERE, NOT HERE: whether a scene
#   actually VARIES its shot archetypes/lenses/sizes shot-to-shot is
#   coverage.py's job — enforce_setup_variety's consecutive-repeat-cap
#   repair leg, the D12-3 rhythm checks (check_shot_size_rhythm/
#   check_lens_rhythm/check_purpose_monotony), and build_rhythm_report's own
#   archetype_diversity metric ({"distinct", "total"} distinct shot_archetype
#   ids across a scene's tagged shots — coverage.py, ~line 2691). This
#   function's job is to faithfully RENDER whatever shot was already chosen;
#   it never chooses, diversifies, or judges one.
#
# Fixed-wording phrase tables for the DP segment — camera_height/dof VALUES
# are validated elsewhere (coverage.py's CAMERA_HEIGHT_KINDS/DOF_KINDS +
# check_shot_dp_valid, warn-only); this module only TRANSLATES a value into
# a phrase, it never validates one, so an unrecognized value (already
# flagged by that check) still renders — via the literal f-string fallback
# below — rather than raising or silently vanishing. Every phrase is a fixed
# constant string keyed on the exact word rule 28 teaches the planner to
# write, so the lookup is one deterministic dict read, never a judgment call.
_CAMERA_HEIGHT_PHRASE = {
    "ground": "camera at ground level",
    "low": "a low camera angle, tilted up",
    "waist": "camera at waist height",
    "chest": "camera at chest height",
    "eye": "camera at eye level",
    "high": "a high camera angle, looking down",
    "overhead": "camera directly overhead",
}
_DOF_PHRASE = {
    "shallow": "shallow depth of field, background soft",
    "medium": "medium depth of field",
    "deep": "deep focus, background sharp",
}


def compose_shot_cinematography(shot) -> str:
    """PURE, deterministic translation of a shot's structured archetype/DP
    fields (plus, optionally, its shot_location) into the CRAFT-ONLY
    cinematography clause that leads its draw prompt. Same fields in,
    byte-identical clause out, ALWAYS — no LLM call, no network, no
    randomness, no clock, no mutation of `shot`. See the COOKIE-CUTTER GUARD
    comment above this function for why the clause is scoped to geometry/
    optics only (never mood/lighting/palette) and kept to one-to-two
    sentences.

    ``shot`` may be any mapping supporting ``.get()`` — a parsed coverage
    shot dict (storyboard.coverage.parse_coverage's output, carrying
    shot_archetype/lens_mm/camera_height/dof alongside description/
    shot_type/etc.) or a freshly re-SELECTed ``assets`` DB row (redraw_
    asset_image's fresh-beats-baked repair-leg pattern) — compose reads
    only five keys, ignores everything else, and never touches
    ``shot["description"]`` (the redundancy-guard check that scans THAT
    field, check_shot_camera_prose_redundant in coverage.py, depends on
    this function never seeing or being influenced by planner prose).

    At most TWO segments (sentences), joined with ". " when both are
    present — the compact budget the cookie-cutter guard's item 2 sets:
      1. the shot's ARCHETYPE's own ``image_setup`` composition guidance,
         verbatim from the 45-entry SHOT_ARCHETYPES catalog above — the
         SAME text format_archetype_menu() shows the planner and
         coverage.check_shot_archetype_valid validates against, now
         finally CONSUMED instead of only carried as metadata. Absent (no
         shot_archetype, or an id not in the catalog — already caught,
         warn-only, by check_shot_archetype_valid) contributes nothing to
         this segment. When this archetype is in CATEGORY_ESTABLISHING AND
         shot["shot_location"] is a non-empty string, an em-dash clause —
         "— this is <location>" — folds into this SAME sentence (never a
         third segment) — the one deliberate interpolation point (the
         cookie-cutter guard's item 3). Never fires for any other category,
         and never invents a location that isn't already known data.
      2. a DP (director-of-photography) phrase built from lens_mm/
         camera_height/dof in FIXED wording (_CAMERA_HEIGHT_PHRASE/
         _DOF_PHRASE above) — never the planner's own prose. Each of the
         three parts is independently optional, exactly mirroring rule 28's
         own "all three parts are independently optional" DP row grammar.

    Returns "" when the shot has NEITHER a valid archetype NOR any DP
    field — the byte-identical-legacy case every assembly point depends on:
    a shot with no structured fields (every plan before D11-1/D11-2, and
    any shot the planner simply didn't tag) gets nothing prepended to its
    description, ever."""
    segments = []

    archetype = get_archetype(shot.get("shot_archetype"))
    if archetype is not None:
        archetype_segment = archetype.image_setup.strip().rstrip(". ")
        # Interpolation folds into the SAME sentence (em dash, not a new
        # period) so the compact "one-to-two sentences max" budget (segment
        # 1 here, segment 2 the DP phrase below) never grows a third —
        # see the COOKIE-CUTTER GUARD comment above this function.
        location = (shot.get("shot_location") or "").strip()
        if location and archetype.category == CATEGORY_ESTABLISHING:
            archetype_segment = f"{archetype_segment} — this is {location}"
        segments.append(archetype_segment)

    dp_bits = []
    lens_mm = shot.get("lens_mm")
    if lens_mm is not None:
        dp_bits.append(f"shot on a {lens_mm}mm lens")
    camera_height = shot.get("camera_height")
    if camera_height:
        dp_bits.append(_CAMERA_HEIGHT_PHRASE.get(camera_height, f"camera at {camera_height} height"))
    dof = shot.get("dof")
    if dof:
        dp_bits.append(_DOF_PHRASE.get(dof, f"{dof} depth of field"))
    if dp_bits:
        segments.append(", ".join(dp_bits))

    if not segments:
        return ""
    return ". ".join(segments) + "."
