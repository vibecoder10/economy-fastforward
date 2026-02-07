"""Documentary Animation Prompt System - Style Engine

This module defines the visual identity constants and prompt architecture
for Economy FastForward's AI image generation pipeline.

Version: 2.0 (Feb 2026)
"""

from enum import Enum
from typing import List, Tuple


# =============================================================================
# STYLE ENGINE CONSTANT - Appended to every image prompt
# =============================================================================
STYLE_ENGINE = (
    "Lo-fi 2D digital illustration, paper-cut collage diorama with layered depth, "
    "visible brushstroke textures, subtle film grain, muted earth tones with selective "
    "neon accent lighting, tilt-shift miniature depth of field, Studio Ghibli background "
    "painting meets editorial infographic, 16:9 cinematic composition"
)


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

# Motion vocabulary for the paper-cut style (NEVER use fast/sudden/dramatic)
MOTION_VOCABULARY = {
    "figures": [
        "figure gently turns head toward",
        "silhouette slowly reaches hand forward",
        "paper-cut figures subtly sway in place",
        "character's hair and clothes drift as if underwater",
    ],
    "environmental": [
        "paper layers shift with gentle parallax depth",
        "leaves and particles drift slowly across frame",
        "smoke or fog wisps curl through the scene",
        "light beams slowly sweep across the surface",
    ],
    "data": [
        "flow lines slowly pulse and travel along their paths",
        "numbers and text elements gently float upward",
        "graph lines draw themselves left to right",
        "cracks slowly spread across the surface",
    ],
    "atmospheric": [
        "warm light gently pulses like breathing",
        "dust particles float through light beams",
        "subtle film grain flickers",
        "shadows slowly shift as if clouds passing overhead",
    ],
}

# Speed words - ALWAYS use these, NEVER use fast/sudden/dramatic
SPEED_WORDS_ALLOWED = ["slow", "subtle", "gentle", "soft", "gradual", "drifting", "easing"]
SPEED_WORDS_FORBIDDEN = ["fast", "sudden", "dramatic", "explosive", "rapid", "intense", "quick"]


def get_camera_motion(scene_type: SceneType, is_hero: bool = False) -> str:
    """Get the appropriate camera motion for a scene type.

    Args:
        scene_type: The scene type (ISOMETRIC_DIORAMA, etc.)
        is_hero: If True, use hero shot motion (more dramatic)

    Returns:
        Camera motion string for video prompt
    """
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
# PROMPT WORD BUDGET - Hard limits
# =============================================================================
PROMPT_MIN_WORDS = 80
PROMPT_MAX_WORDS = 120

# Word budget breakdown
WORD_BUDGET = {
    "shot_type": 5,
    "scene_composition": 15,
    "focal_subject": 20,
    "environmental_storytelling": 30,
    "style_engine": 40,  # STYLE_ENGINE constant
    "lighting": 10,
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
# 5-LAYER PROMPT ARCHITECTURE
# =============================================================================
PROMPT_ARCHITECTURE = """
[SHOT TYPE] + [SCENE COMPOSITION] + [FOCAL SUBJECT] + [ENVIRONMENTAL STORYTELLING] + [STYLE_ENGINE + LIGHTING]

Layer Definitions:
1. SHOT TYPE (1 phrase) — Camera framing:
   - Overhead isometric diorama of...
   - Side view of...
   - Extreme wide shot of...
   - Close-up of...
   - Split-screen showing...
   - First-person perspective looking at...

2. SCENE COMPOSITION (1-2 phrases) — Physical scene/environment:
   - Be concrete: "a small dim apartment", "a frozen American landscape as layered paper-cut panorama"
   - NO abstract concepts. Describe a PLACE.

3. FOCAL SUBJECT (1-2 phrases) — Main character/object doing something:
   - Always include action or state: "young engineer at desk", "paper-cut workers reaching toward glow"
   - Include emotion: "expression determined but trapped"

4. ENVIRONMENTAL STORYTELLING (2-3 phrases) — Background/middle-ground details:
   - Symbolic objects: "stack of apartment listings with crossed-out prices"
   - Visual metaphors: "broken bridge made of dollar bills spanning a canyon"
   - Data made physical: "migration flow arrows drawn in pencil fading to nothing"

5. STYLE ENGINE + LIGHTING (locked):
   - STYLE_ENGINE constant
   - Scene-specific lighting: "[warm color] representing [concept] vs [cool color] representing [concept]"
"""


# =============================================================================
# EXAMPLE PROMPTS - Reference for the AI
# =============================================================================
EXAMPLE_PROMPTS = [
    # Image 1 — WIDE ESTABLISHING
    (
        "Overhead isometric map of America as a paper-cut diorama, glowing orange "
        "clusters marking tech hubs in SF Austin NYC Boston, dim blue-gray everywhere "
        "else, tiny paper figures crowded in the dim zones reaching toward the glow, "
        "red price tag barriers ringing each bright cluster, migration flow arrows "
        "drawn in pencil fading to nothing, warm neon vs cool shadow contrast, "
        "lo-fi 2D digital illustration with layered paper depth and visible brushstroke "
        "textures, subtle film grain, tilt-shift miniature depth of field, Studio Ghibli "
        "background painting meets editorial infographic, 16:9 cinematic wide shot, "
        "soft volumetric lighting through paper layers"
    ),
    # Image 2 — MEDIUM HUMAN STORY
    (
        "Side view of a young engineer at a desk in a small dim apartment, laptop screen "
        "showing job offers from San Francisco, beside her a stack of apartment listings "
        "with crossed-out prices, through the window a quiet small-town street with bare "
        "trees, her expression determined but trapped, split warm desk lamp light vs cold "
        "blue window light, paper-cut collage style with layered depth, muted earth tones "
        "with selective amber and blue accents, visible hand-drawn linework, lo-fi 2D "
        "digital illustration with film grain, 16:9 cinematic frame"
    ),
    # Image 3 — CLOSE-UP VIGNETTE
    (
        "Close-up of hands holding a crumpled apartment rejection letter, calculator beside "
        "them showing $4200 monthly payment, wedding ring on finger suggesting family stakes, "
        "warm amber light from above casting shadows across the paper textures, shallow "
        "depth of field with blurred background of packed moving boxes never opened, "
        "paper-cut collage with visible torn edges, muted earth tones with red accent on "
        "the rejection stamp, lo-fi 2D digital illustration with brushstroke texture and "
        "film grain, 16:9"
    ),
    # Image 4 — DATA LANDSCAPE
    (
        "A broken bridge made of dollar bills spanning a deep canyon, left cliff edge "
        "labeled TALENT with crowds of paper-cut workers looking across, right cliff "
        "labeled OPPORTUNITY with gleaming miniature city skyline and cranes, bridge "
        "crumbling in the middle with price tags falling into the void, equation fragments "
        "floating in dusty air, isometric perspective with tilt-shift blur at edges, muted "
        "palette with red warning accents on the fracture point, lo-fi 2D digital "
        "illustration with film grain and brushstroke overlay, 16:9 cinematic composition"
    ),
]
