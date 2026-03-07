"""Holographic Intelligence Display Style Engine

Re-exports all constants from image_prompt_engine.style_config and adds
legacy compatibility constants for the animation pipeline.

Version: 4.0 (Mar 2026) — Holographic Intelligence Display system
"""

from typing import List, Tuple

# Import all holographic constants from the canonical source
from image_prompt_engine.style_config import (
    # Enums
    ContentType,
    DisplayFormat,
    ColorMood,
    # Config dicts
    CONTENT_TYPE_CONFIG,
    CONTENT_TYPE_KEYWORDS,
    DISPLAY_FORMAT_CONFIG,
    CONTENT_FORMAT_AFFINITY,
    COLOR_MOOD_CONFIG,
    COLOR_MOOD_KEYWORDS,
    COLOR_MOOD_PRIORITY,
    # Constants
    HOLOGRAPHIC_SUFFIX,
    MAX_CONSECUTIVE_CONTENT_TYPE,
    MAX_CONSECUTIVE_FORMAT,
    MAX_CONSECUTIVE_PALETTE,
    KEN_BURNS_RULES as _HOLOGRAPHIC_KEN_BURNS_RULES,
    KEN_BURNS_PAN_ALTERNATES,
    # Functions
    resolve_content_type,
    resolve_color_mood,
    resolve_display_format,
)


# =============================================================================
# PROMPT WORD BUDGET
# =============================================================================
PROMPT_MIN_WORDS = 60
PROMPT_MAX_WORDS = 150


# =============================================================================
# CAMERA MOVEMENT VOCABULARY — For video animation prompts
# =============================================================================

CAMERA_MOVEMENT_BY_FORMAT = {
    DisplayFormat.WAR_TABLE: [
        "Slow orbit around the table surface",
        "Gentle push-in toward the center of the projection",
        "Slow crane upward revealing the full table layout",
        "Subtle drift with parallax depth between table and floating panels",
    ],
    DisplayFormat.WALL_DISPLAY: [
        "Slow push-in toward the central display",
        "Gentle lateral pan across the data panels",
        "Slow drift from left panel to right panel",
        "Subtle crane downward from overview to detail",
    ],
    DisplayFormat.FLOATING_PROJECTION: [
        "Slow orbit around the floating objects",
        "Gentle push-in between floating elements",
        "Slow rise from below the projection level",
        "Subtle rotation revealing different angles of the display",
    ],
    DisplayFormat.MULTI_PANEL: [
        "Slow lateral pan from left panel to right panel",
        "Gentle pull-back revealing all panels at once",
        "Slow drift connecting the panels visually",
        "Subtle push-in on the central connecting element",
    ],
    DisplayFormat.CLOSE_UP_DETAIL: [
        "Very slow drift to the right across the data",
        "Gentle push-in on the key data point",
        "Slow breathing zoom on the focal element",
        "Subtle rack focus between foreground and background data",
    ],
}

CAMERA_MOVEMENT_HERO = {
    DisplayFormat.WAR_TABLE: "Slow orbit around the table with gradual push-in revealing layers of data",
    DisplayFormat.WALL_DISPLAY: "Slow push-in toward the display with gentle lateral drift across panels",
    DisplayFormat.FLOATING_PROJECTION: "Slow orbit around floating objects with depth reveal between elements",
    DisplayFormat.MULTI_PANEL: "Slow lateral sweep across all panels then gentle push-in on the focal panel",
    DisplayFormat.CLOSE_UP_DETAIL: "Very slow drift with breathing zoom revealing hidden data layers",
}

SPEED_WORDS_ALLOWED = ["slow", "subtle", "gentle", "soft", "gradual", "drifting", "easing"]
SPEED_WORDS_FORBIDDEN = ["fast", "sudden", "dramatic", "explosive", "rapid", "intense", "quick"]

MOTION_VOCABULARY = {
    "holographic": [
        "data nodes slowly pulse with light",
        "connection lines gradually illuminate",
        "holographic surface subtly ripples",
        "floating labels gently drift into position",
        "wireframe edges slowly glow brighter",
    ],
    "data": [
        "chart bars slowly rise to full height",
        "trend line gradually draws itself across the display",
        "ticker tape scrolls across the bottom",
        "percentage numbers slowly count upward",
        "warning indicators pulse with soft rhythm",
    ],
    "environmental": [
        "ambient equipment glow subtly shifts color",
        "console lights gently flicker in the periphery",
        "dust particles float through projection beams",
        "faint reflection drifts across dark surfaces",
    ],
    "atmospheric": [
        "holographic projection edges softly shimmer",
        "particle effects slowly dissipate at display boundaries",
        "ambient light subtly shifts in the background",
        "projection beam slowly sweeps across the room",
    ],
}


# =============================================================================
# LEGACY COMPATIBILITY — For animation/image_generator.py and pipeline.py
# =============================================================================

from enum import Enum as _Enum


STYLE_ENGINE_PREFIX = (
    "Holographic intelligence display, dark high-security operations center, "
    "holographic projections floating in dark space, clinical precision, "
    "data-dense analytical visualization, photorealistic rendering, "
    "16:9 cinematic composition."
)

STYLE_ENGINE_SUFFIX = (
    "No people visible, no human figures, no faces, no silhouettes, "
    "only holographic data displays and dark room environment, "
    "cinematic depth of field, subtle ambient equipment glow."
)

STYLE_ENGINE = f"{STYLE_ENGINE_PREFIX} {STYLE_ENGINE_SUFFIX}"

ANONYMOUS_FIGURE_STYLE = (
    "No human figures allowed. Use measurement icons or labeled silhouette "
    "outlines for scale reference only."
)

MATERIAL_VOCABULARY = {
    "premium": [
        "holographic gold wireframe", "brass instrument bezels",
        "polished console surfaces", "amber status indicators",
    ],
    "institutional": [
        "dark console banks", "security-grade displays",
        "reinforced server racks", "military-grade equipment",
    ],
    "data": [
        "holographic projections", "translucent data overlays",
        "glowing node networks", "floating analytical panels",
    ],
}

TEXT_RULE_WITH_TEXT = "text elements must be data-formatted labels, numbers, percentages, or classification stamps only"
TEXT_RULE_NO_TEXT = "no narrative text, only analytical data labels and readouts"


class SceneType(_Enum):
    """Legacy scene types — mapped to new display formats."""
    ISOMETRIC_DIORAMA = "isometric_diorama"
    SPLIT_SCREEN = "split_screen"
    JOURNEY_SHOT = "journey_shot"
    CLOSE_UP_VIGNETTE = "close_up_vignette"
    DATA_LANDSCAPE = "data_landscape"
    OVERHEAD_MAP = "overhead_map"


class CameraRole(_Enum):
    """Legacy camera roles — maintained for animation pipeline."""
    WIDE_ESTABLISHING = "wide_establishing"
    MEDIUM_HUMAN_STORY = "medium_human_story"
    DATA_METAPHOR = "data_metaphor"
    PULL_BACK_REVEAL = "pull_back_reveal"


SCENE_TYPE_CONFIG = {
    SceneType.ISOMETRIC_DIORAMA: {
        "shot_prefix": "Overhead holographic war table displaying",
        "use_when": "Showing systems, flows, networks",
        "visual_language": "Top-down angled view, full holographic table visible",
    },
    SceneType.SPLIT_SCREEN: {
        "shot_prefix": "Multi-panel holographic command display showing",
        "use_when": "Comparing two realities, before/after",
        "visual_language": "Multiple panels, contrasting data, connecting elements",
    },
    SceneType.JOURNEY_SHOT: {
        "shot_prefix": "Holographic timeline projection showing",
        "use_when": "Showing progression, decline, timelines",
        "visual_language": "Sequential panels, chronological flow, connecting threads",
    },
    SceneType.CLOSE_UP_VIGNETTE: {
        "shot_prefix": "Close-up holographic detail showing",
        "use_when": "Key data points, critical details",
        "visual_language": "Tight crop on data, minimal surrounding context",
    },
    SceneType.DATA_LANDSCAPE: {
        "shot_prefix": "Holographic data terminal displaying",
        "use_when": "Financial data, statistics, charts",
        "visual_language": "Wall display with charts, tickers, data readouts",
    },
    SceneType.OVERHEAD_MAP: {
        "shot_prefix": "Holographic geographic map projecting",
        "use_when": "Geographic or systemic views",
        "visual_language": "War table map, route lines, position markers",
    },
}

CAMERA_ROLE_SCENE_TYPES = {
    CameraRole.WIDE_ESTABLISHING: [
        SceneType.ISOMETRIC_DIORAMA,
        SceneType.OVERHEAD_MAP,
        SceneType.JOURNEY_SHOT,
    ],
    CameraRole.MEDIUM_HUMAN_STORY: [
        SceneType.CLOSE_UP_VIGNETTE,
        SceneType.DATA_LANDSCAPE,
    ],
    CameraRole.DATA_METAPHOR: [
        SceneType.DATA_LANDSCAPE,
        SceneType.SPLIT_SCREEN,
        SceneType.JOURNEY_SHOT,
    ],
    CameraRole.PULL_BACK_REVEAL: [
        SceneType.JOURNEY_SHOT,
        SceneType.OVERHEAD_MAP,
        SceneType.ISOMETRIC_DIORAMA,
    ],
}


def get_camera_motion(scene_type, is_hero: bool = False) -> str:
    """Get camera motion for a scene/shot type. Supports both new and legacy types."""
    import random

    if isinstance(scene_type, DisplayFormat):
        if is_hero:
            return CAMERA_MOVEMENT_HERO.get(scene_type, "Slow push-in with depth reveal")
        movements = CAMERA_MOVEMENT_BY_FORMAT.get(scene_type)
        if movements:
            return random.choice(movements)
        return "Slow push-in"

    if isinstance(scene_type, str):
        shot_type = scene_type.lower().strip()
        format_map = {
            "war_table": DisplayFormat.WAR_TABLE,
            "wall_display": DisplayFormat.WALL_DISPLAY,
            "floating": DisplayFormat.FLOATING_PROJECTION,
            "multi_panel": DisplayFormat.MULTI_PANEL,
            "close_up_detail": DisplayFormat.CLOSE_UP_DETAIL,
            "wide_establishing": DisplayFormat.WAR_TABLE,
            "isometric_diorama": DisplayFormat.WAR_TABLE,
            "medium_human_story": DisplayFormat.WALL_DISPLAY,
            "close_up_vignette": DisplayFormat.CLOSE_UP_DETAIL,
            "data_landscape": DisplayFormat.WALL_DISPLAY,
            "split_screen": DisplayFormat.MULTI_PANEL,
            "pull_back_reveal": DisplayFormat.WAR_TABLE,
            "overhead_map": DisplayFormat.WAR_TABLE,
            "journey_shot": DisplayFormat.MULTI_PANEL,
        }
        mapped = format_map.get(shot_type)
        if mapped:
            return get_camera_motion(mapped, is_hero)
        return "Slow push-in"

    if isinstance(scene_type, SceneType):
        legacy_to_format = {
            SceneType.ISOMETRIC_DIORAMA: DisplayFormat.WAR_TABLE,
            SceneType.SPLIT_SCREEN: DisplayFormat.MULTI_PANEL,
            SceneType.JOURNEY_SHOT: DisplayFormat.MULTI_PANEL,
            SceneType.CLOSE_UP_VIGNETTE: DisplayFormat.CLOSE_UP_DETAIL,
            SceneType.DATA_LANDSCAPE: DisplayFormat.WALL_DISPLAY,
            SceneType.OVERHEAD_MAP: DisplayFormat.WAR_TABLE,
        }
        mapped = legacy_to_format.get(scene_type, DisplayFormat.WAR_TABLE)
        return get_camera_motion(mapped, is_hero)

    return "Slow push-in"


def get_random_atmospheric_motion() -> str:
    """Get a random atmospheric motion element for video prompts."""
    import random
    return random.choice(MOTION_VOCABULARY["atmospheric"])


def get_documentary_pattern(segment_count: int) -> List[CameraRole]:
    """Get the documentary camera pattern for a given number of segments."""
    if segment_count >= 6:
        return [
            CameraRole.WIDE_ESTABLISHING,
            CameraRole.MEDIUM_HUMAN_STORY,
            CameraRole.MEDIUM_HUMAN_STORY,
            CameraRole.DATA_METAPHOR,
            CameraRole.DATA_METAPHOR,
            CameraRole.PULL_BACK_REVEAL,
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
    """Get the appropriate scene type for a segment, avoiding consecutive same types."""
    pattern = get_documentary_pattern(total_segments)
    camera_role = pattern[min(segment_index, len(pattern) - 1)]
    allowed_types = CAMERA_ROLE_SCENE_TYPES[camera_role]

    if previous_scene_type and len(allowed_types) > 1:
        filtered_types = [t for t in allowed_types if t != previous_scene_type]
        if filtered_types:
            allowed_types = filtered_types

    scene_type = allowed_types[segment_index % len(allowed_types)]
    return scene_type, camera_role


def validate_prompt_length(prompt: str) -> Tuple[bool, int, str]:
    """Validate that a prompt is within the word budget."""
    word_count = len(prompt.split())
    if word_count < PROMPT_MIN_WORDS:
        return False, word_count, f"Too short: {word_count} words (min {PROMPT_MIN_WORDS})"
    elif word_count > PROMPT_MAX_WORDS:
        return False, word_count, f"Too long: {word_count} words (max {PROMPT_MAX_WORDS})"
    else:
        return True, word_count, f"Valid: {word_count} words"


# =============================================================================
# PROMPT ARCHITECTURE REFERENCE & EXAMPLE PROMPTS
# =============================================================================

PROMPT_ARCHITECTURE = """
[DISPLAY FORMAT framing] + [DISPLAY CONTENT detailed description] + [COLOR MOOD palette] + [UNIVERSAL SUFFIX]
"""

EXAMPLE_PROMPTS = [
    (
        "Overhead angled view of a holographic war table surface projecting "
        "a detailed map of the Persian Gulf and Strait of Hormuz, Iran's "
        "coastline to the north and Oman to the south, shipping lane corridors "
        "marked with blue directional arrows, 150 red dots representing anchored "
        "oil tankers clustered outside the strait in the Gulf of Oman, the "
        "chokepoint marked with a pulsing red barrier line, country labels in "
        "clean sans-serif text for Iran Iraq Saudi Arabia Kuwait UAE Oman Qatar, "
        "floating data panels above the table showing oil price at $148.20 and "
        "shipping traffic down 70%, cool teal and cyan holographic light against "
        "dark background, clinical intelligence aesthetic"
        + HOLOGRAPHIC_SUFFIX
    ),
    (
        "Front-facing view of a massive holographic wall display showing "
        "a financial data terminal with oil price candlestick chart spiking "
        "violently upward with red warning indicators flashing at the peak, "
        "scrolling ticker tape below showing WTI crude at $148.20 and Brent at "
        "$152.40 climbing with percentage gains of +340%, side panels showing "
        "inflation rate climbing to 9.2% and bond yield spiking to 5.8% and "
        "currency index dropping 12%, red and amber warning colors dominating "
        "the display, emergency alert aesthetic, pulsing warning indicators"
        + HOLOGRAPHIC_SUFFIX
    ),
    (
        "Eye-level view of holographic objects floating in dark space showing "
        "two wireframe objects for scale comparison, on the left a small military "
        "drone rotating slowly with floating price tag reading $2,000, on the right "
        "a massive VLCC supertanker 330 meters long with floating price tag reading "
        "$200,000,000, a risk calculation panel below showing cost-to-attack versus "
        "cost-to-defend ratio at 1:100000, deep navy blue and steel holographic "
        "wireframes with clean white labels, military precision aesthetic"
        + HOLOGRAPHIC_SUFFIX
    ),
]
