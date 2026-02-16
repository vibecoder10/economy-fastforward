"""
Prompt builder for the visual identity system.

Takes scene descriptions and sequencing metadata, produces fully constructed
image generation prompts ready for NanoBanana.
"""

from __future__ import annotations

from typing import Optional

from .style_config import (
    ACCENT_COLOR_MAP,
    COMPOSITION_DIRECTIVES,
    DEFAULT_CONFIG,
    STYLE_SUFFIXES,
    YOUTUBE_STYLE_PREFIX,
)
from .sequencer import assign_styles


def resolve_accent_color(
    accent_color: Optional[str] = None,
    topic_category: Optional[str] = None,
) -> str:
    """Determine the accent color for a video.

    Uses the explicit *accent_color* if provided, otherwise looks up
    *topic_category* in :data:`ACCENT_COLOR_MAP`, falling back to the
    default accent color.
    """
    if accent_color:
        return accent_color
    if topic_category:
        return ACCENT_COLOR_MAP.get(
            topic_category,
            DEFAULT_CONFIG["default_accent_color"],
        )
    return DEFAULT_CONFIG["default_accent_color"]


def build_prompt(
    scene_description: str,
    style: str,
    composition: str,
    accent_color: str,
) -> str:
    """Assemble a complete image generation prompt.

    Structure: ``[YOUTUBE_STYLE_PREFIX] [SCENE_DESCRIPTION], [COMPOSITION_DIRECTIVE], [STYLE_SUFFIX]``

    The cinematic dossier prefix is placed FIRST because image generation
    models weight early tokens more heavily, establishing the photorealistic
    cinematic look before scene-specific content.

    Parameters
    ----------
    scene_description : str
        What the image depicts (from the script / visual seeds).
    style : str
        One of ``"dossier"``, ``"schema"``, ``"echo"``.
    composition : str
        A key from :data:`COMPOSITION_DIRECTIVES`.
    accent_color : str
        The accent color string (e.g. ``"cold teal"``).

    Returns
    -------
    str
        The complete prompt string, ready for the image generation model.
    """
    # Cinematic dossier prefix — establishes the photorealistic look
    prefix = YOUTUBE_STYLE_PREFIX.replace("[ACCENT_COLOR]", accent_color)

    comp_text = COMPOSITION_DIRECTIVES.get(composition, "")
    suffix = STYLE_SUFFIXES[style].replace("[ACCENT_COLOR]", accent_color)

    parts = [prefix + " " + scene_description.rstrip(", ")]
    if comp_text:
        parts.append(comp_text)
    parts_str = ", ".join(parts)

    # The suffix already starts with ", " so we just concatenate.
    return parts_str + suffix


def generate_prompts(
    scenes: list[dict],
    *,
    accent_color: Optional[str] = None,
    topic_category: Optional[str] = None,
    act_timestamps: Optional[dict] = None,
    seed: Optional[int] = None,
) -> list[dict]:
    """Generate fully constructed prompts for an entire video.

    Parameters
    ----------
    scenes : list[dict]
        Each dict must contain at minimum:
        - ``"scene_description"`` (str): what the image depicts.
        Optionally:
        - ``"act"`` (str): act override; if omitted, derived from position.
    accent_color : str, optional
        Explicit accent color for the video.
    topic_category : str, optional
        Topic category used to auto-select accent color if *accent_color*
        is not provided.
    act_timestamps : dict, optional
        Custom act timestamp breakpoints. Falls back to defaults.
    seed : int, optional
        RNG seed for reproducible style sequencing.

    Returns
    -------
    list[dict]
        One entry per scene with keys: ``prompt``, ``style``, ``composition``,
        ``accent_color``, ``act``, ``index``, ``ken_burns``.
    """
    color = resolve_accent_color(accent_color, topic_category)
    total_images = len(scenes)

    # Generate the style/composition sequence.
    assignments = assign_styles(
        total_images,
        act_timestamps=act_timestamps,
        seed=seed,
    )

    results: list[dict] = []
    for scene, assignment in zip(scenes, assignments):
        desc = scene.get("scene_description", "")
        style = assignment["style"]
        composition = assignment["composition"]

        prompt = build_prompt(desc, style, composition, color)

        results.append({
            "prompt": prompt,
            "style": style,
            "composition": composition,
            "accent_color": color,
            "act": assignment["act"],
            "index": assignment["index"],
            "ken_burns": assignment["ken_burns"],
        })

    return results
