"""
Prompt builder for the Holographic Intelligence Display system.

Takes scene descriptions and sequencing metadata, produces fully constructed
image generation prompts for the holographic intelligence display aesthetic.

Version: 4.0 (Mar 2026) — Holographic Intelligence Display system
"""

from __future__ import annotations

import re
from typing import Optional

from .style_config import (
    ColorMood,
    COLOR_MOOD_CONFIG,
    COLOR_MOOD_KEYWORDS,
    COLOR_MOOD_PRIORITY,
    ContentType,
    CONTENT_TYPE_KEYWORDS,
    DisplayFormat,
    DISPLAY_FORMAT_CONFIG,
    HOLOGRAPHIC_SUFFIX,
    DEFAULT_CONFIG,
    resolve_color_mood,
    resolve_content_type,
    resolve_display_format,
)
from .sequencer import assign_styles


# ---------------------------------------------------------------------------
# Style-language patterns to strip from scene descriptions
# ---------------------------------------------------------------------------
_STYLE_STRIP_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bcinematic(?:\s+photorealistic)?\b",
        r"\bphotorealistic\b",
        r"\bholographic\b",
        r"\b16:\s?9\b",
        r"\b8K\s+resolution\b",
        r"\bshallow depth of field\b",
        r"\bfilm grain\b",
    ]
]


def _strip_style_language(description: str) -> str:
    """Remove style/lighting/camera language from a scene description."""
    cleaned = description
    for pat in _STYLE_STRIP_PATTERNS:
        cleaned = pat.sub("", cleaned)
    cleaned = re.sub(r",\s*,", ",", cleaned)
    cleaned = re.sub(r"^\s*,\s*", "", cleaned)
    cleaned = re.sub(r"\s*,\s*$", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


def resolve_scene_color_mood(
    scene_description: str,
    video_color_mood: str = "strategic",
) -> str:
    """Pick a color mood for a single image based on scene content.

    Scans *scene_description* for keyword matches in COLOR_MOOD_KEYWORDS.
    Returns the mood value with the most hits. Falls back to *video_color_mood*.
    """
    mood = resolve_color_mood(scene_description)
    # If resolve_color_mood found keywords, use that; otherwise fall back
    text_lower = scene_description.lower()
    has_any_hit = False
    for keywords in COLOR_MOOD_KEYWORDS.values():
        if any(kw in text_lower for kw in keywords):
            has_any_hit = True
            break
    if has_any_hit:
        return mood.value
    return video_color_mood


def build_prompt(
    scene_description: str,
    content_type: str,
    display_format: str,
    color_mood: str,
    image_style_override: Optional[str] = None,
) -> str:
    """Assemble a complete holographic intelligence display prompt.

    Follows the master template::

        [DISPLAY FORMAT framing] [DISPLAY CONTENT] [COLOR MOOD] [UNIVERSAL SUFFIX]

    Parameters
    ----------
    scene_description : str
        What the image depicts — the analytical content description.
    content_type : str
        Value from ContentType enum (e.g. ``"geographic_map"``).
    display_format : str
        Value from DisplayFormat enum (e.g. ``"war_table"``).
    color_mood : str
        Value from ColorMood enum (e.g. ``"strategic"``).
    image_style_override : str, optional
        Per-video style override from Airtable.

    Returns
    -------
    str
        The complete prompt string, ready for image generation.
    """
    # Resolve the display format framing text
    fmt_enum = _format_from_value(display_format)
    framing = DISPLAY_FORMAT_CONFIG[fmt_enum]["framing"]

    # Resolve color mood prompt language
    mood_enum = _mood_from_value(color_mood)
    mood_language = COLOR_MOOD_CONFIG[mood_enum]["prompt_language"]

    # Clean scene description
    clean_desc = _strip_style_language(scene_description).rstrip(". ")

    if image_style_override and image_style_override.strip():
        mood_language = _apply_style_override(mood_language, image_style_override)

    # Assemble: [Framing] [Content] [Color Mood] [Suffix]
    return f"{framing} {clean_desc}, {mood_language}{HOLOGRAPHIC_SUFFIX}"


def _format_from_value(value: str) -> DisplayFormat:
    """Convert a string value to DisplayFormat enum."""
    for fmt in DisplayFormat:
        if fmt.value == value:
            return fmt
    return DisplayFormat.WAR_TABLE


def _mood_from_value(value: str) -> ColorMood:
    """Convert a string value to ColorMood enum."""
    for mood in ColorMood:
        if mood.value == value:
            return mood
    return ColorMood.STRATEGIC


def _apply_style_override(mood_language: str, override: str) -> str:
    """Apply an image style override to the color mood layer."""
    stripped = override.strip()
    if stripped.upper().startswith("REPLACE:"):
        return stripped[len("REPLACE:"):].strip()
    if stripped.startswith("+"):
        return mood_language + " " + stripped[1:].strip()
    if stripped.upper().startswith("APPEND:"):
        return mood_language + " " + stripped[len("APPEND:"):].strip()
    return mood_language + " " + stripped


def generate_prompts(
    scenes: list[dict],
    *,
    accent_color: Optional[str] = None,
    topic_category: Optional[str] = None,
    act_timestamps: Optional[dict] = None,
    seed: Optional[int] = None,
    image_style_override: Optional[str] = None,
) -> list[dict]:
    """Generate fully constructed prompts for an entire video.

    Parameters
    ----------
    scenes : list[dict]
        Each dict must contain at minimum:
        - ``"scene_description"`` (str): what the image depicts.
    accent_color : str, optional
        Explicit color mood override (maps to a ColorMood value).
    topic_category : str, optional
        Topic category (unused in v4, kept for API compatibility).
    act_timestamps : dict, optional
        Custom act timestamp breakpoints.
    seed : int, optional
        RNG seed for reproducible sequencing.
    image_style_override : str, optional
        Per-video style override applied to every prompt.

    Returns
    -------
    list[dict]
        One entry per scene with keys: ``prompt``, ``content_type``,
        ``display_format``, ``color_mood``, ``act``, ``index``, ``ken_burns``.
    """
    total_images = len(scenes)

    # Generate the content_type/format/mood sequence
    assignments = assign_styles(
        total_images,
        act_timestamps=act_timestamps,
        seed=seed,
    )

    results: list[dict] = []
    for scene, assignment in zip(scenes, assignments):
        desc = scene.get("scene_description", "")
        content_type = assignment["content_type"]
        display_format = assignment["display_format"]
        color_mood = assignment["color_mood"]

        # Per-scene color mood rotation based on content
        scene_mood = resolve_scene_color_mood(desc, color_mood)

        prompt = build_prompt(
            desc, content_type, display_format, scene_mood,
            image_style_override=image_style_override,
        )

        results.append({
            "prompt": prompt,
            "content_type": content_type,
            "display_format": display_format,
            "color_mood": scene_mood,
            "act": assignment["act"],
            "index": assignment["index"],
            "ken_burns": assignment["ken_burns"],
        })

    return results


# ---------------------------------------------------------------------------
# Legacy API compatibility — resolve_accent_color
# ---------------------------------------------------------------------------

def resolve_accent_color(
    accent_color: Optional[str] = None,
    topic_category: Optional[str] = None,
) -> str:
    """Legacy API: returns a color mood value string.

    Maps old accent_color/topic_category to new color mood system.
    """
    if accent_color:
        # Map old accent colors to new mood values
        accent_to_mood = {
            "cold teal": "strategic",
            "warm amber": "archive",
            "muted crimson": "alert",
            "muted green": "contagion",
            "deep green": "contagion",
        }
        return accent_to_mood.get(accent_color, accent_color)
    if topic_category:
        category_to_mood = {
            "geopolitical": "strategic",
            "ai_tech": "strategic",
            "corporate_power": "power",
            "surveillance": "strategic",
            "economic": "personal",
            "financial": "personal",
            "historical_power": "archive",
            "old_money": "archive",
            "conflict": "alert",
            "warfare": "alert",
            "political_violence": "alert",
            "military": "power",
            "markets": "contagion",
            "growth": "contagion",
            "trade": "contagion",
        }
        return category_to_mood.get(topic_category, "strategic")
    return "strategic"


def resolve_scene_accent_color(
    scene_description: str,
    video_accent_color: str,
) -> str:
    """Legacy API: resolve per-scene accent color.

    Maps to the new color mood system.
    """
    return resolve_scene_color_mood(scene_description, video_accent_color)
