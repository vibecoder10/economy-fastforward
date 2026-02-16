"""
Image Prompt Engine — Visual Identity System for NanoBanana pipeline.

Replaces generic AI image prompts with a structured visual identity system
producing cinematic, intelligence-briefing-aesthetic imagery across three
styles: Dossier, Schema, and Echo.

Usage
-----
::

    from image_prompt_engine import generate_prompts, resolve_accent_color

    scenes = [
        {"scene_description": "A figure in a dark suit walking through a corridor"},
        {"scene_description": "Aerial city at night with glowing network lines"},
        ...
    ]

    prompts = generate_prompts(
        scenes,
        topic_category="geopolitical",
        seed=42,
    )

    for p in prompts:
        print(p["style"], p["composition"], p["prompt"][:80])
"""

from .prompt_builder import build_prompt, generate_prompts, resolve_accent_color
from .sequencer import assign_styles
from .style_config import (
    ACCENT_COLOR_MAP,
    ACT_STYLE_WEIGHTS,
    COMPOSITION_CYCLE,
    COMPOSITION_DIRECTIVES,
    DEFAULT_CONFIG,
    KEN_BURNS_PAN_ALTERNATES,
    KEN_BURNS_RULES,
    STYLE_SUFFIXES,
    YOUTUBE_STYLE_PREFIX,
)

__all__ = [
    # High-level API
    "generate_prompts",
    "build_prompt",
    "resolve_accent_color",
    "assign_styles",
    # Configuration
    "STYLE_SUFFIXES",
    "YOUTUBE_STYLE_PREFIX",
    "COMPOSITION_DIRECTIVES",
    "COMPOSITION_CYCLE",
    "ACCENT_COLOR_MAP",
    "ACT_STYLE_WEIGHTS",
    "KEN_BURNS_RULES",
    "KEN_BURNS_PAN_ALTERNATES",
    "DEFAULT_CONFIG",
]
