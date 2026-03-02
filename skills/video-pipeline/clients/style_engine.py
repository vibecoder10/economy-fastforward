"""Cinematic Photorealistic Documentary Style Engine

This module defines the visual identity constants and prompt architecture
for Economy FastForward's AI image generation pipeline.

Visual Identity: Cinematic photorealistic documentary photography.
Think Sicario, Zero Dark Thirty, The Big Short.

Characters: Anonymous human figures with faces always obscured by shadow,
silhouette, backlighting, or camera angle. Never show clear facial features.
Documentary photography where identities are protected.

Version: 3.0 (Mar 2026) — Unified cinematic photorealistic identity
"""

from enum import Enum
from typing import List, Tuple


# =============================================================================
# STYLE ENGINE CONSTANTS - Cinematic Photorealistic Documentary (v3)
# =============================================================================
# CRITICAL: Style engine goes at BEGINNING of prompt, not end.
# Models weight early tokens more heavily.
#
# CHARACTER STYLE: Anonymous human figures with faces obscured by shadow,
# silhouette, backlighting, or camera angle. Documentary photography
# where identities are protected.

STYLE_ENGINE_PREFIX = (
    "Cinematic photorealistic editorial photograph, dark moody atmosphere, "
    "desaturated color palette with cold teal accent lighting, Rembrandt lighting, "
    "deep shadows, shallow depth of field, subtle film grain, documentary photography "
    "style, shot on Arri Alexa 65 with 35mm Master Prime lens, 16:9 cinematic "
    "composition, epic scale."
)

# Anonymous human figure description (for reference in prompts)
ANONYMOUS_FIGURE_STYLE = (
    "anonymous human figure with face completely obscured — hidden by deep shadow, "
    "silhouette, backlighting, or turned away from camera. Documentary photography "
    "where identities are protected. Real clothing, real skin texture, real body "
    "language. Never show clear facial features."
)

STYLE_ENGINE_SUFFIX = (
    "Real Kodak Vision3 500T 35mm film grain, silver halide noise, high contrast, "
    "crushed blacks, organic halation effects around light sources, visible "
    "atmospheric particulate, cinematic color grade."
)

# Legacy constant for backwards compatibility (combines prefix + suffix)
STYLE_ENGINE = f"{STYLE_ENGINE_PREFIX} {STYLE_ENGINE_SUFFIX}"

# =============================================================================
# MATERIAL VOCABULARY - Cinematic photorealistic environments
# =============================================================================
MATERIAL_VOCABULARY = {
    "premium": [
        "polished mahogany", "leather chairs", "crystal decanters",
        "gold-framed documents", "warm tungsten light",
    ],
    "institutional": [
        "concrete bunkers", "fluorescent corridors", "steel doors",
        "security cameras", "industrial ventilation",
    ],
    "decay": [
        "peeling paint", "water stains", "rusted infrastructure",
        "flickering lights", "abandoned equipment",
    ],
    "data": [
        "Bloomberg terminals", "holographic displays",
        "translucent teal data overlays", "glowing monitors in dark rooms",
    ],
    "division": [
        "lighting shift warm to cold", "material change luxury to decay",
        "barriers", "checkpoints",
    ],
}

# =============================================================================
# TEXT RULES FOR SCENE IMAGES
# =============================================================================
TEXT_SURFACE_EXAMPLES = {
    "dates": "weathered ink on aged parchment",
    "currency": "embossed numbers on a worn banknote",
    "labels": "stenciled letters on a military crate",
    "stamps": "red rubber stamp impression on classified document",
    "data": "glowing numbers on a dark monitor screen",
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
        "shot_prefix": "Overhead establishing shot of",
        "use_when": "Showing systems, flows, economies",
        "visual_language": "Birds-eye view, full environment visible, surveillance perspective",
    },
    SceneType.SPLIT_SCREEN: {
        "shot_prefix": "Split composition showing",
        "use_when": "Comparing two realities, before/after",
        "visual_language": "Left/right divide, contrasting warm/cool palettes, lighting shift",
    },
    SceneType.JOURNEY_SHOT: {
        "shot_prefix": "Wide tracking shot of",
        "use_when": "Showing progression, decline, timelines",
        "visual_language": "Path leading into distance, perspective depth, tracking movement",
    },
    SceneType.CLOSE_UP_VIGNETTE: {
        "shot_prefix": "Extreme close-up of",
        "use_when": "Emotional human moments, critical details",
        "visual_language": "Tight crop, shallow DOF, hands/objects filling frame",
    },
    SceneType.DATA_LANDSCAPE: {
        "shot_prefix": "Environmental detail, no human figure, objects telling the story",
        "use_when": "Making statistics feel real/physical",
        "visual_language": "Bloomberg terminals, trading floors, data screens in dark rooms",
    },
    SceneType.OVERHEAD_MAP: {
        "shot_prefix": "Top-down surveillance shot of",
        "use_when": "Geographic or systemic views",
        "visual_language": "Top-down, security camera perspective, strategic overview",
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

# Default camera movements per scene type
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
SHOT_TYPE_CAMERA_MOVEMENTS = {
    # Establishing shots - show the world
    "wide_establishing": [
        "Slow crane down into the scene",
        "Gentle drift from left to right surveying the scene",
        "Slow pull-back revealing the full scope",
        "Steady hold with subtle parallax shift",
    ],
    # Overhead establishing
    "isometric_diorama": [
        "Slow orbit around the scene",
        "Gentle push-in with slight rotation",
        "Slow crane upward revealing layers",
        "Subtle drift with parallax depth",
    ],
    # Human story - emotional focus
    "medium_human_story": [
        "Slow drift toward the subject",
        "Gentle lateral tracking following the figure",
        "Very slow push-in on the silhouette",
        "Subtle sway with atmospheric haze drifting",
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
    "isometric_diorama": "Slow orbit around the scene gradually revealing all layers",
    "medium_human_story": "Slow drift toward the subject with subtle rack focus",
    "close_up_vignette": "Very slow rotation around the object with breathing zoom",
    "data_landscape": "Slow crane upward revealing the full scale of data",
    "split_screen": "Slow lateral pan from left to right, crossing the divide completely",
    "pull_back_reveal": "Slow pull-back revealing the full scale, then gentle rotation",
    "overhead_map": "Slow push-in with rotation surveying the entire landscape",
    "journey_shot": "Slow tracking along the path with gradual depth reveal",
}

# Motion vocabulary for cinematic documentary style (NEVER use fast/sudden/dramatic)
MOTION_VOCABULARY = {
    "figures": [
        "figure subtly shifts weight",
        "silhouette slowly turns",
        "figure's arm gradually lifts",
        "figure's head gently tilts down",
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
        "reflections shift on wet pavement",
    ],
    "data": [
        "chart bars slowly rise",
        "trend line gradually draws itself",
        "monitor screens gently pulse with light",
        "ticker tape scrolls across dark screen",
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
# PROMPT WORD BUDGET - Hard limits (v3: increased for cinematic detail)
# =============================================================================
PROMPT_MIN_WORDS = 120
PROMPT_MAX_WORDS = 200

# Word budget breakdown (v3: cinematic photorealistic)
WORD_BUDGET = {
    "style_engine_prefix": 35,  # STYLE_ENGINE_PREFIX constant (goes FIRST)
    "shot_type": 6,
    "scene_composition": 25,
    "focal_subject": 30,  # Anonymous figures with body language and environment
    "environmental_storytelling": 40,
    "style_engine_suffix": 25,  # STYLE_ENGINE_SUFFIX constant
    "lighting": 20,
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
# 5-LAYER PROMPT ARCHITECTURE (v3: Cinematic Photorealistic Documentary)
# =============================================================================
PROMPT_ARCHITECTURE = """
[STYLE_ENGINE_PREFIX] + [SHOT TYPE] + [SCENE COMPOSITION] + [FOCAL SUBJECT] + [ENVIRONMENTAL STORYTELLING] + [STYLE_ENGINE_SUFFIX + LIGHTING] + [TEXT RULE]

CRITICAL: Style engine prefix goes FIRST - models weight early tokens more heavily.

Layer Definitions:

1. STYLE_ENGINE_PREFIX (locked, ~35 words) — ALWAYS FIRST:
   "Cinematic photorealistic editorial photograph, dark moody atmosphere, desaturated
   color palette with cold teal accent lighting, Rembrandt lighting, deep shadows,
   shallow depth of field, subtle film grain, documentary photography style, shot on
   Arri Alexa 65 with 35mm Master Prime lens, 16:9 cinematic composition, epic scale."

2. SHOT TYPE (1 phrase, ~6 words) — Camera framing:
   - Overhead establishing shot of...
   - Wide tracking shot of...
   - Extreme close-up of...
   - Split composition showing...
   - Top-down surveillance shot of...

3. SCENE COMPOSITION (1-2 phrases, ~25 words) — Physical environment:
   - Be concrete with real-world PLACES: "a darkened military command center"
   - Cinematic environments: boardrooms, trading floors, government vaults,
     abandoned facilities, war rooms, corridors of power
   - NO abstract concepts. Describe a REAL PLACE.

4. FOCAL SUBJECT (1-2 phrases, ~30 words) — Main character/object:
   - ALWAYS anonymous human figures: faces hidden by shadow, silhouette, backlighting
   - Specify count and framing: "a lone figure silhouetted against monitors"
   - Include BODY LANGUAGE: "shoulders slumped", "arms crossed", "leaning forward"
   - Include action: "signing documents", "walking through corridor"

5. ENVIRONMENTAL STORYTELLING (2-3 phrases, ~40 words) — Background/middle-ground:
   - Objects that tell stories: classified documents, trading terminals, empty chairs
   - Visual metaphors using real objects: "a bridge with missing sections"
   - Data made tangible: "Bloomberg screens with red tickers", "stacks of currency"

6. STYLE_ENGINE_SUFFIX + LIGHTING (locked + scene-specific, ~45 words):
   - "Real Kodak Vision3 500T 35mm film grain, silver halide noise, high contrast,
     crushed blacks, organic halation effects around light sources, visible atmospheric
     particulate, cinematic color grade."
   - Plus scene lighting: "[warm description] vs [cool description]"

7. TEXT RULE (always last, ~10 words):
   - If NO text: "no text, no words, no labels, no signs, no readable text anywhere in the scene"
   - If text included: "no additional text beyond the specified [elements]"
   - Max 3 text elements, max 3 words each
"""


# =============================================================================
# EXAMPLE PROMPTS - Reference (Cinematic Photorealistic Documentary Style)
# =============================================================================
EXAMPLE_PROMPTS = [
    # Image 1 — WIDE ESTABLISHING (Overhead)
    (
        "Cinematic photorealistic editorial photograph, dark moody atmosphere, "
        "desaturated color palette with cold teal accent lighting, Rembrandt lighting, "
        "deep shadows, shallow depth of field, subtle film grain, documentary photography "
        "style, shot on Arri Alexa 65 with 35mm Master Prime lens, 16:9 cinematic "
        "composition, epic scale. Overhead establishing shot of a darkened military "
        "command center, banks of glowing monitors casting cold teal light across "
        "silhouetted figures at their stations, classified documents scattered across "
        "a central briefing table, a single red phone illuminated by a cone of warm "
        "tungsten light. Real Kodak Vision3 500T 35mm film grain, silver halide noise, "
        "high contrast, crushed blacks, organic halation effects around the monitor "
        "screens, visible atmospheric particulate, cinematic color grade, cold teal "
        "monitors vs warm tungsten desk lamp, no text no words no labels"
    ),
    # Image 2 — MEDIUM HUMAN STORY
    (
        "Cinematic photorealistic editorial photograph, dark moody atmosphere, "
        "desaturated color palette with cold teal accent lighting, Rembrandt lighting, "
        "deep shadows, shallow depth of field, subtle film grain, documentary photography "
        "style, shot on Arri Alexa 65 with 35mm Master Prime lens, 16:9 cinematic "
        "composition, epic scale. Medium shot of an anonymous figure in a tailored suit "
        "seated at a mahogany desk, face completely in shadow from Rembrandt side lighting, "
        "warm desk lamp casting amber glow on scattered financial reports, through a rain-"
        "streaked window behind him a cold blue cityscape of distant towers. Real Kodak "
        "Vision3 500T 35mm film grain, silver halide noise, high contrast, crushed blacks, "
        "organic halation effects around the desk lamp, visible atmospheric particulate, "
        "cinematic color grade, warm amber desk lamp vs cold blue window light, no text "
        "no words no labels"
    ),
    # Image 3 — CLOSE-UP VIGNETTE
    (
        "Cinematic photorealistic editorial photograph, dark moody atmosphere, "
        "desaturated color palette with cold teal accent lighting, Rembrandt lighting, "
        "deep shadows, shallow depth of field, subtle film grain, documentary photography "
        "style, shot on Arri Alexa 65 with 35mm Master Prime lens, 16:9 cinematic "
        "composition, epic scale. Extreme close-up of a weathered hand hovering over a "
        "red button on a military console, shallow depth of field blurring banks of "
        "switches and warning lights behind, veins visible on the hand, sweat glistening "
        "under harsh overhead fluorescent. Real Kodak Vision3 500T 35mm film grain, "
        "silver halide noise, high contrast, crushed blacks, organic halation effects "
        "around the red button glow, visible atmospheric particulate, cinematic color "
        "grade, cold fluorescent overhead vs warm red button glow, no text no words "
        "no labels"
    ),
    # Image 4 — DATA LANDSCAPE
    (
        "Cinematic photorealistic editorial photograph, dark moody atmosphere, "
        "desaturated color palette with cold teal accent lighting, Rembrandt lighting, "
        "deep shadows, shallow depth of field, subtle film grain, documentary photography "
        "style, shot on Arri Alexa 65 with 35mm Master Prime lens, 16:9 cinematic "
        "composition, epic scale. Environmental detail, no human figure, objects telling "
        "the story, a Wall Street trading terminal in a darkened room, Bloomberg screens "
        "displaying green spikes and red crashes, the glow of six monitors illuminating "
        "an empty leather chair, coffee cup still steaming, papers scattered mid-sentence. "
        "Real Kodak Vision3 500T 35mm film grain, silver halide noise, high contrast, "
        "crushed blacks, organic halation effects around the glowing monitors, visible "
        "atmospheric particulate, cinematic color grade, cold teal monitor glow vs warm "
        "ambient room light, no text no words no labels"
    ),
]
