"""
Image Prompt Engine — Holographic Intelligence Display System.

Produces holographic intelligence display visualizations — the aesthetic
of a classified military/intelligence operations center where data, maps,
documents, and analysis are projected on holographic surfaces.

Zero human figures. Every frame carries actual analytical information.

Usage
-----
::

    from image_prompt_engine import generate_prompts

    scenes = [
        {"scene_description": "A detailed map of the Strait of Hormuz with shipping lanes"},
        {"scene_description": "Oil price candlestick chart spiking with warning indicators"},
        ...
    ]

    prompts = generate_prompts(scenes, seed=42)

    for p in prompts:
        print(p["content_type"], p["display_format"], p["prompt"][:80])
"""

from .prompt_builder import (
    build_prompt,
    generate_prompts,
    resolve_accent_color,
    resolve_scene_accent_color,
    resolve_scene_color_mood,
)
from .sequencer import assign_styles
from .style_config import (
    ContentType,
    DisplayFormat,
    ColorMood,
    CONTENT_TYPE_CONFIG,
    CONTENT_TYPE_KEYWORDS,
    DISPLAY_FORMAT_CONFIG,
    CONTENT_FORMAT_AFFINITY,
    COLOR_MOOD_CONFIG,
    COLOR_MOOD_KEYWORDS,
    COLOR_MOOD_PRIORITY,
    HOLOGRAPHIC_SUFFIX,
    KEN_BURNS_RULES,
    KEN_BURNS_PAN_ALTERNATES,
    ACT_MOOD_WEIGHTS,
    DEFAULT_CONFIG,
    FORMAT_CYCLE,
    resolve_content_type,
    resolve_color_mood,
    resolve_display_format,
)

__all__ = [
    # High-level API
    "generate_prompts",
    "build_prompt",
    "resolve_accent_color",
    "resolve_scene_accent_color",
    "resolve_scene_color_mood",
    "assign_styles",
    # Configuration
    "ContentType",
    "DisplayFormat",
    "ColorMood",
    "CONTENT_TYPE_CONFIG",
    "CONTENT_TYPE_KEYWORDS",
    "DISPLAY_FORMAT_CONFIG",
    "CONTENT_FORMAT_AFFINITY",
    "COLOR_MOOD_CONFIG",
    "COLOR_MOOD_KEYWORDS",
    "COLOR_MOOD_PRIORITY",
    "HOLOGRAPHIC_SUFFIX",
    "ACT_MOOD_WEIGHTS",
    "DEFAULT_CONFIG",
    "FORMAT_CYCLE",
    "KEN_BURNS_RULES",
    "KEN_BURNS_PAN_ALTERNATES",
    "resolve_content_type",
    "resolve_color_mood",
    "resolve_display_format",
]
