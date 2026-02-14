"""Documentary Animation Prompt System - Style Engine

This module defines the visual identity constants and prompt architecture
for Economy FastForward's AI image generation pipeline.

Version: 2.0 (Feb 2026)
"""

from enum import Enum
from typing import List, Tuple


# =============================================================================
# STYLE ENGINE CONSTANTS - 3D Editorial Mannequin Render Style (v3)
# =============================================================================
# CRITICAL: Style engine goes at BEGINNING of prompt, not end.
# Models weight early tokens more heavily.
#
# CHARACTER STYLE: Smooth matte gray mannequin (NOT clay, NOT action figure)
# Think department store display mannequin with smooth continuous surfaces.

STYLE_ENGINE_PREFIX = (
    "3D editorial conceptual render, monochromatic smooth matte gray mannequin figures "
    "with no facial features, smooth continuous surfaces like a department store display mannequin, "
    "photorealistic materials and studio lighting."
)

# Protagonist style description (for reference in prompts)
PROTAGONIST_STYLE = (
    "smooth matte gray mannequin figure — like a high-end department store display mannequin. "
    "Featureless face with only subtle indentations. Smooth continuous body surfaces. "
    "NOT clay, NOT stone, NOT an action figure, NOT a robot. "
    "Golden amber glow emanates from cracked chest."
)

# Negative prompt additions for image generation (to avoid clay/rough textures)
NEGATIVE_PROMPT_ADDITIONS = (
    "clay texture, rough surface, stone, concrete, action figure, ball joints, "
    "mechanical joints, panel lines, robot, matte clay, rough matte, porous surface"
)

STYLE_ENGINE_SUFFIX = (
    "Clean studio lighting, shallow depth of field, matte and metallic material "
    "contrast, cinematic 16:9 composition"
)

# Legacy constant for backwards compatibility (combines prefix + suffix)
STYLE_ENGINE = f"{STYLE_ENGINE_PREFIX} {STYLE_ENGINE_SUFFIX}"

# =============================================================================
# MATERIAL VOCABULARY - For 3D mannequin render style
# =============================================================================
MATERIAL_VOCABULARY = {
    "premium": [
        "polished chrome", "brushed gold", "glass dome", "velvet lining",
        "warm spotlight", "copper accents", "leather with gold foil",
    ],
    "institutional": [
        "brushed steel", "concrete", "frosted glass", "iron chains",
        "cold fluorescent tubes", "matte black", "industrial pipes",
    ],
    "decay": [
        "rusted iron", "cracked concrete", "leaking dark fluid", "corroded metal",
        "flickering warning lights", "oxidized copper", "green patina",
    ],
    "data": [
        "frosted glass panels with etched lines", "chrome clipboards",
        "backlit displays", "embossed metal numerals", "glass gauges with needles",
    ],
    "division": [
        "cracked concrete wall", "glass partition", "steel bars",
        "lighting shift from cool to warm", "material change concrete to marble",
    ],
}

# =============================================================================
# TEXT RULES FOR SCENE IMAGES - 3D style renders text on surfaces
# =============================================================================
TEXT_SURFACE_EXAMPLES = {
    "dates": "embossed chrome numerals on frosted glass panel",
    "currency": "stamped chrome price tag",
    "labels": "gold foil lettering on leather booklet",
    "stamps": "red rubber stamp impression on matte document",
    "data": "etched numbers on brushed steel plate",
}

# Text rules: max 3 elements, max 3 words each, must specify material surface
TEXT_RULE_WITH_TEXT = "no additional text beyond the specified elements"
TEXT_RULE_NO_TEXT = "no text, no words, no labels, no signs, no readable text anywhere in the scene"


# =============================================================================
# SCENE TYPES - Rotate through these for visual variety
# =============================================================================
class SceneType(Enum):
    """6 scene types to rotate through for visual variety."""

    ISOMETRIC_DIORAMA = "isometric_diorama"
    SPLIT_SCREEN = "split_screen"
    JOURNEY_SHOT = "journey_shot"
    CLOSE_UP_VIGNETTE = "close_up_vignette"
    DATA_LANDSCAPE = "data_landscape"
    OVERHEAD_MAP = "overhead_map"


# Scene type configurations with shot prefixes and use cases
SCENE_TYPE_CONFIG = {
    SceneType.ISOMETRIC_DIORAMA: {
        "shot_prefix": "Overhead isometric diorama of",
        "use_when": "Showing systems, flows, economies",
        "visual_language": "Birds-eye tilted view, miniature world",
    },
    SceneType.SPLIT_SCREEN: {
        "shot_prefix": "Split-screen diorama showing",
        "use_when": "Comparing two realities, before/after",
        "visual_language": "Left/right divide, contrasting warm/cool palettes",
    },
    SceneType.JOURNEY_SHOT: {
        "shot_prefix": "Wide journey shot of",
        "use_when": "Showing progression, decline, timelines",
        "visual_language": "Path leading into distance, perspective depth",
    },
    SceneType.CLOSE_UP_VIGNETTE: {
        "shot_prefix": "Close-up of",
        "use_when": "Emotional human moments",
        "visual_language": "Single figure, tight crop, expressive lighting",
    },
    SceneType.DATA_LANDSCAPE: {
        "shot_prefix": "Data landscape showing",
        "use_when": "Making statistics feel real/physical",
        "visual_language": "Charts/graphs becoming physical terrain or objects",
    },
    SceneType.OVERHEAD_MAP: {
        "shot_prefix": "Overhead map view of",
        "use_when": "Geographic or systemic views",
        "visual_language": "Top-down, flow lines, heat map colors",
    },
}


# =============================================================================
# DOCUMENTARY CAMERA PATTERN - Per-scene rhythm
# =============================================================================
class CameraRole(Enum):
    """Documentary camera roles for narrative rhythm."""

    WIDE_ESTABLISHING = "wide_establishing"
    MEDIUM_HUMAN_STORY = "medium_human_story"
    DATA_METAPHOR = "data_metaphor"
    PULL_BACK_REVEAL = "pull_back_reveal"


# Camera role to scene type mappings
CAMERA_ROLE_SCENE_TYPES = {
    CameraRole.WIDE_ESTABLISHING: [
        SceneType.ISOMETRIC_DIORAMA,
        SceneType.OVERHEAD_MAP,
        SceneType.JOURNEY_SHOT,
    ],
    CameraRole.MEDIUM_HUMAN_STORY: [
        SceneType.CLOSE_UP_VIGNETTE,
        SceneType.JOURNEY_SHOT,  # Side view variant
    ],
    CameraRole.DATA_METAPHOR: [
        SceneType.DATA_LANDSCAPE,
        SceneType.SPLIT_SCREEN,
        SceneType.JOURNEY_SHOT,
    ],
    CameraRole.PULL_BACK_REVEAL: [
        SceneType.JOURNEY_SHOT,  # Extreme wide
        SceneType.OVERHEAD_MAP,
        SceneType.ISOMETRIC_DIORAMA,
    ],
}


# =============================================================================
# CAMERA MOVEMENT VOCABULARY - For video animation prompts
# =============================================================================

# Default camera movements per scene type (from Image Prompt System v2)
CAMERA_MOVEMENT_VOCAB = {
    SceneType.ISOMETRIC_DIORAMA: "Slow push-in with slight rotation",
    SceneType.SPLIT_SCREEN: "Slow lateral pan from left to right",
    SceneType.JOURNEY_SHOT: "Slow tracking along the path",
    SceneType.CLOSE_UP_VIGNETTE: "Very slow drift to the right",
    SceneType.DATA_LANDSCAPE: "Slow crane upward",
    SceneType.OVERHEAD_MAP: "Slow push-in",
}

# Hero shot camera movements (more dramatic, for 10s clips)
CAMERA_MOVEMENT_HERO = {
    SceneType.ISOMETRIC_DIORAMA: "Slow push-in with slight rotation gradually revealing full depth",
    SceneType.SPLIT_SCREEN: "Slow lateral pan from left to right crossing the divide",
    SceneType.JOURNEY_SHOT: "Slow tracking along the path with depth reveal",
    SceneType.CLOSE_UP_VIGNETTE: "Very slow drift with subtle rack focus",
    SceneType.DATA_LANDSCAPE: "Slow crane upward revealing the scale",
    SceneType.OVERHEAD_MAP: "Slow push-in with slight rotation surveying the landscape",
}

# String-based camera movements for all shot types (used by video prompt generator)
# These are more varied and dynamic than just "push-in"
SHOT_TYPE_CAMERA_MOVEMENTS = {
    # Establishing shots - show the world
    "wide_establishing": [
        "Slow crane down into the scene",
        "Gentle drift from left to right surveying the scene",
        "Slow pull-back revealing the full scope",
        "Steady hold with subtle parallax shift",
    ],
    # Diorama - 3/4 angle miniature
    "isometric_diorama": [
        "Slow orbit around the diorama",
        "Gentle push-in with slight rotation",
        "Slow crane upward revealing layers",
        "Subtle drift with parallax depth",
    ],
    # Human story - emotional focus
    "medium_human_story": [
        "Slow drift toward the subject",
        "Gentle lateral tracking following the figure",
        "Very slow push-in on the face",
        "Subtle sway with the subject breathing",
    ],
    # Close-up - detail focus
    "close_up_vignette": [
        "Very slow drift to the right",
        "Gentle rack focus between elements",
        "Slow rotation around the object",
        "Subtle breathing zoom",
    ],
    # Data viz
    "data_landscape": [
        "Slow crane upward",
        "Gentle tilt down across the data",
        "Slow tracking along the graph line",
        "Steady hold as data animates",
    ],
    # Split comparison
    "split_screen": [
        "Slow lateral pan from left to right",
        "Gentle drift crossing the divide",
        "Subtle push-in on both halves",
        "Slow wipe transition between sides",
    ],
    # Reveal shots - dramatic
    "pull_back_reveal": [
        "Slow pull-back revealing the full scale",
        "Gradual crane upward and outward",
        "Gentle zoom out with rotation",
        "Slow drift backward unveiling context",
    ],
    # Map view
    "overhead_map": [
        "Slow push-in on the focal point",
        "Gentle drift across the terrain",
        "Slow rotation surveying the landscape",
        "Subtle crane down into the map",
    ],
    # Journey/path
    "journey_shot": [
        "Slow tracking along the path",
        "Gentle dolly forward into the distance",
        "Slow lateral pan following the journey",
        "Subtle drift with depth parallax",
    ],
}

# Hero versions (10s clips) - add more complexity
SHOT_TYPE_CAMERA_MOVEMENTS_HERO = {
    "wide_establishing": "Slow crane down into the scene, then gentle drift revealing the full scope",
    "isometric_diorama": "Slow orbit around the diorama gradually revealing all layers",
    "medium_human_story": "Slow drift toward the subject with subtle rack focus",
    "close_up_vignette": "Very slow rotation around the object with breathing zoom",
    "data_landscape": "Slow crane upward revealing the full scale of data",
    "split_screen": "Slow lateral pan from left to right, crossing the divide completely",
    "pull_back_reveal": "Slow pull-back revealing the full scale, then gentle rotation",
    "overhead_map": "Slow push-in with rotation surveying the entire landscape",
    "journey_shot": "Slow tracking along the path with gradual depth reveal",
}

# Motion vocabulary for 3D mannequin render style (NEVER use fast/sudden/dramatic)
MOTION_VOCABULARY = {
    "figures": [
        "mannequin subtly shifts weight",
        "mannequin slowly turns body",
        "mannequin's arm gradually lifts",
        "mannequin's head gently tilts down",
        "fingers slowly close around handle",
    ],
    "mechanical": [
        "gears slowly rotate",
        "pipes subtly vibrate",
        "gauge needles drift",
        "lever gradually pulls down",
        "cracks slowly spread through concrete",
    ],
    "environmental": [
        "dust particles float through light beams",
        "fog wisps curl between objects",
        "light slowly sweeps across surface",
        "reflections shift on chrome",
    ],
    "data": [
        "chart bars slowly rise",
        "trend line gradually draws itself",
        "numerals gently pulse with light",
        "glass panel slowly illuminates",
    ],
    "atmospheric": [
        "warm spotlight slowly brightens",
        "shadows gradually lengthen",
        "ambient light subtly shifts from cool to warm",
        "lens flare drifts across frame",
    ],
}

# Speed words - ALWAYS use these, NEVER use fast/sudden/dramatic
SPEED_WORDS_ALLOWED = ["slow", "subtle", "gentle", "soft", "gradual", "drifting", "easing"]
SPEED_WORDS_FORBIDDEN = ["fast", "sudden", "dramatic", "explosive", "rapid", "intense", "quick"]


def get_camera_motion(scene_type, is_hero: bool = False) -> str:
    """Get the appropriate camera motion for a scene/shot type.

    Args:
        scene_type: The scene type - can be SceneType enum or shot_type string
        is_hero: If True, use hero shot motion (more dramatic)

    Returns:
        Camera motion string for video prompt
    """
    import random

    # Handle string shot types (from Airtable Shot Type field)
    if isinstance(scene_type, str):
        shot_type = scene_type.lower().strip()

        if is_hero:
            return SHOT_TYPE_CAMERA_MOVEMENTS_HERO.get(shot_type, "Slow push-in with depth reveal")

        # Get random movement from the list for variety
        movements = SHOT_TYPE_CAMERA_MOVEMENTS.get(shot_type)
        if movements:
            return random.choice(movements)
        return "Slow push-in"  # fallback

    # Handle SceneType enum (legacy)
    if is_hero:
        return CAMERA_MOVEMENT_HERO.get(scene_type, CAMERA_MOVEMENT_VOCAB.get(scene_type, "Slow push-in"))
    return CAMERA_MOVEMENT_VOCAB.get(scene_type, "Slow push-in")


def get_random_atmospheric_motion() -> str:
    """Get a random atmospheric motion element for video prompts."""
    import random
    return random.choice(MOTION_VOCABULARY["atmospheric"])


def get_documentary_pattern(segment_count: int) -> List[CameraRole]:
    """Get the documentary camera pattern for a given number of segments.

    The 4-Shot Documentary Pattern:
    1. WIDE ESTABLISHING — Set the scene at macro level
    2-3. MEDIUM HUMAN STORY — Zoom into person experiencing the topic
    4-5. DATA/METAPHOR — Visualize the mechanism or data
    6. PULL BACK REVEAL — Wide shot showing scale/consequence

    Args:
        segment_count: Number of segments/images in the scene

    Returns:
        List of CameraRole assignments for each segment
    """
    if segment_count >= 6:
        return [
            CameraRole.WIDE_ESTABLISHING,    # 1
            CameraRole.MEDIUM_HUMAN_STORY,   # 2
            CameraRole.MEDIUM_HUMAN_STORY,   # 3
            CameraRole.DATA_METAPHOR,        # 4
            CameraRole.DATA_METAPHOR,        # 5
            CameraRole.PULL_BACK_REVEAL,     # 6
        ] + [CameraRole.PULL_BACK_REVEAL] * (segment_count - 6)
    elif segment_count == 5:
        return [
            CameraRole.WIDE_ESTABLISHING,
            CameraRole.MEDIUM_HUMAN_STORY,
            CameraRole.MEDIUM_HUMAN_STORY,
            CameraRole.DATA_METAPHOR,
            CameraRole.PULL_BACK_REVEAL,
        ]
    elif segment_count == 4:
        return [
            CameraRole.WIDE_ESTABLISHING,
            CameraRole.MEDIUM_HUMAN_STORY,
            CameraRole.DATA_METAPHOR,
            CameraRole.PULL_BACK_REVEAL,
        ]
    elif segment_count == 3:
        return [
            CameraRole.WIDE_ESTABLISHING,
            CameraRole.MEDIUM_HUMAN_STORY,
            CameraRole.PULL_BACK_REVEAL,
        ]
    elif segment_count == 2:
        return [
            CameraRole.MEDIUM_HUMAN_STORY,
            CameraRole.PULL_BACK_REVEAL,
        ]
    else:
        return [CameraRole.WIDE_ESTABLISHING]


def get_scene_type_for_segment(
    segment_index: int,
    total_segments: int,
    previous_scene_type: SceneType = None,
) -> Tuple[SceneType, CameraRole]:
    """Get the appropriate scene type for a segment, avoiding consecutive same types.

    Args:
        segment_index: 0-based index of current segment
        total_segments: Total number of segments in scene
        previous_scene_type: The scene type used for the previous segment

    Returns:
        Tuple of (SceneType, CameraRole) for this segment
    """
    # Get documentary pattern for this scene
    pattern = get_documentary_pattern(total_segments)
    camera_role = pattern[min(segment_index, len(pattern) - 1)]

    # Get allowed scene types for this camera role
    allowed_types = CAMERA_ROLE_SCENE_TYPES[camera_role]

    # Filter out previous scene type to avoid consecutive same-type
    if previous_scene_type and len(allowed_types) > 1:
        filtered_types = [t for t in allowed_types if t != previous_scene_type]
        if filtered_types:
            allowed_types = filtered_types

    # Select scene type (rotate through allowed types based on index)
    scene_type = allowed_types[segment_index % len(allowed_types)]

    return scene_type, camera_role


# =============================================================================
# PROMPT WORD BUDGET - Hard limits (v2: increased for 3D style detail)
# =============================================================================
PROMPT_MIN_WORDS = 120
PROMPT_MAX_WORDS = 150

# Word budget breakdown (v2: style engine split to prefix/suffix)
WORD_BUDGET = {
    "style_engine_prefix": 18,  # STYLE_ENGINE_PREFIX constant (goes FIRST)
    "shot_type": 6,
    "scene_composition": 20,
    "focal_subject": 25,  # More words needed for mannequin body language
    "environmental_storytelling": 35,
    "style_engine_suffix": 15,  # STYLE_ENGINE_SUFFIX constant
    "lighting": 15,
    "text_rule": 10,
}


def validate_prompt_length(prompt: str) -> Tuple[bool, int, str]:
    """Validate that a prompt is within the word budget.

    Args:
        prompt: The generated prompt to validate

    Returns:
        Tuple of (is_valid, word_count, message)
    """
    word_count = len(prompt.split())

    if word_count < PROMPT_MIN_WORDS:
        return False, word_count, f"Too short: {word_count} words (min {PROMPT_MIN_WORDS})"
    elif word_count > PROMPT_MAX_WORDS:
        return False, word_count, f"Too long: {word_count} words (max {PROMPT_MAX_WORDS})"
    else:
        return True, word_count, f"Valid: {word_count} words"


# =============================================================================
# 5-LAYER PROMPT ARCHITECTURE (v2: 3D Editorial Clay Render)
# =============================================================================
PROMPT_ARCHITECTURE = """
[STYLE_ENGINE_PREFIX] + [SHOT TYPE] + [SCENE COMPOSITION] + [FOCAL SUBJECT] + [ENVIRONMENTAL STORYTELLING] + [STYLE_ENGINE_SUFFIX + LIGHTING] + [TEXT RULE]

CRITICAL: Style engine prefix goes FIRST - models weight early tokens more heavily.

Layer Definitions:

1. STYLE_ENGINE_PREFIX (locked, ~18 words) — ALWAYS FIRST:
   "3D editorial conceptual render, monochromatic smooth matte gray mannequin figures with no facial features, photorealistic materials and studio lighting."

2. SHOT TYPE (1 phrase, ~6 words) — Camera framing:
   - Isometric overhead view of...
   - Wide cinematic shot of...
   - Close-up of...
   - Split-screen composition divided by...
   - Low angle looking up at...
   - Bird's-eye view of...

3. SCENE COMPOSITION (1-2 phrases, ~20 words) — Physical environment:
   - Be concrete with MATERIALS: "a brushed steel desk in a concrete office"
   - Material vocabulary: concrete, brushed steel, chrome, glass, leather, velvet, polished wood, frosted glass, rusted iron, matte black, copper, brass
   - NO abstract concepts. Describe a PLACE with MATERIALS.

4. FOCAL SUBJECT (1-2 phrases, ~25 words) — Main character/object:
   - ALWAYS faceless matte gray mannequin: "one faceless matte gray mannequin in a suit"
   - Specify count and scale: "one mannequin at medium scale", "three mannequin figures"
   - Include BODY LANGUAGE (critical since no face): "shoulders slumped", "arms reaching upward", "head bowed", "leaning forward confidently"
   - Include action: "pulling a lever", "walking across", "standing at"

5. ENVIRONMENTAL STORYTELLING (2-3 phrases, ~35 words) — Background/middle-ground:
   - Symbolic objects in appropriate MATERIALS: "chrome checkmark medallions", "rusted padlock icons"
   - Visual metaphors using physical objects: "cracking pipes leaking dark fluid"
   - Data made physical: "bar charts on chrome clipboards", "embossed metal numerals"

6. STYLE_ENGINE_SUFFIX + LIGHTING (locked + scene-specific, ~30 words):
   - "Clean studio lighting, shallow depth of field, matte and metallic material contrast, cinematic 16:9 composition"
   - Plus scene lighting: "[warm description] vs [cool description]"

7. TEXT RULE (always last, ~10 words):
   - If NO text: "no text, no words, no labels, no signs, no readable text anywhere in the scene"
   - If text included: "no additional text beyond the specified [elements]"
   - Text MUST have material surface: "embossed chrome numerals", "stamped metal tag"
   - Max 3 text elements, max 3 words each
"""


# =============================================================================
# EXAMPLE PROMPTS - Reference for the AI (3D Editorial Clay Render Style)
# =============================================================================
EXAMPLE_PROMPTS = [
    # Image 1 — WIDE ESTABLISHING (Isometric Diorama)
    (
        "3D editorial conceptual render, monochromatic smooth matte gray mannequin figures with no facial "
        "features, photorealistic materials and studio lighting. Isometric overhead view "
        "of a miniature America as a brushed steel diorama, glowing amber clusters marking "
        "tech hubs, dim concrete zones elsewhere, small matte gray mannequin figures "
        "crowded in the dim zones arms reaching toward the glow, chrome price tag barriers "
        "ringing each bright cluster, migration flow lines etched into frosted glass floor. "
        "Clean studio lighting, shallow depth of field, matte and metallic material contrast, "
        "cinematic 16:9 composition, warm amber vs cold steel blue lighting contrast, "
        "no text beyond the etched flow lines"
    ),
    # Image 2 — MEDIUM HUMAN STORY
    (
        "3D editorial conceptual render, monochromatic smooth matte gray mannequin figures with no facial "
        "features, photorealistic materials and studio lighting. Medium shot of one matte "
        "gray mannequin in a wrinkled suit sitting at a brushed steel desk, shoulders "
        "slumped head bowed, laptop screen glowing with job listings, beside it a stack "
        "of documents on cracked concrete surface, through frosted glass window a dim "
        "cityscape. Clean studio lighting, shallow depth of field, matte and metallic "
        "material contrast, cinematic 16:9 composition, warm desk lamp amber vs cold "
        "window blue-gray lighting, no text no words no labels"
    ),
    # Image 3 — CLOSE-UP VIGNETTE
    (
        "3D editorial conceptual render, monochromatic smooth matte gray mannequin figures with no facial "
        "features, photorealistic materials and studio lighting. Close-up of matte gray "
        "mannequin hands gripping edges of a chrome desk, knuckles tensed showing strain, "
        "on the desk surface stamped metal rejection letter with red 'DENIED' impression, "
        "chrome calculator displaying '$4200', shallow depth of field blurring background "
        "of stacked moving boxes. Clean studio lighting, matte and metallic material "
        "contrast, cinematic 16:9 composition, warm amber overhead vs cool chrome "
        "reflections, no additional text beyond the specified elements"
    ),
    # Image 4 — DATA LANDSCAPE
    (
        "3D editorial conceptual render, monochromatic smooth matte gray mannequin figures with no facial "
        "features, photorealistic materials and studio lighting. Wide shot of a broken "
        "chrome bridge spanning a dark void, left cliff of cracked concrete with matte "
        "gray mannequin figures shoulders slumped looking across, right cliff of polished "
        "marble with gleaming glass buildings and copper cranes, bridge fractured in the "
        "middle with chrome price tags falling into darkness, embossed metal numerals "
        "'36T' on a steel plate at the fracture point. Clean studio lighting, shallow "
        "depth of field, matte and metallic material contrast, cinematic 16:9 composition, "
        "cold concrete gray on left vs warm golden glow on right, no additional text "
        "beyond the specified numerals"
    ),
]
