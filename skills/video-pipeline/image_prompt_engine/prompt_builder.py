"""
Prompt builder for the visual identity system.

Takes scene descriptions and sequencing metadata, produces fully constructed
image generation prompts ready for NanoBanana.
"""

from __future__ import annotations

import re
from typing import Optional

from .style_config import (
    ACCENT_COLOR_MAP,
    COMPOSITION_DIRECTIVES,
    DEFAULT_CONFIG,
    STYLE_SUFFIXES,
    YOUTUBE_STYLE_PREFIX,
)
from .sequencer import assign_styles

# ---------------------------------------------------------------------------
# Style-language patterns to strip from scene descriptions before appending
# the style suffix.  The scene expansion prompt instructs the LLM to omit
# these, but this acts as a safety net to prevent duplicate directives.
# ---------------------------------------------------------------------------
_STYLE_STRIP_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        # Lighting
        r"\bRembrandt lighting\b",
        r"\bdramatic (?:side |back )?lighting\b",
        r"\bchiaroscuro\b",
        r"\bcandlelight lighting\b",
        r"\bsingle dramatic light source\b",
        # Camera / lens
        r"\bshot on Arri Alexa\b",
        r"\b\d{2,3}\s?mm lens\b",
        r"\b16:\s?9\b",
        # Color grading
        r"\bdesaturated (?:color )?palette\b",
        r"\bcold teal accent(?:\s*lighting)?\b",
        r"\bwarm amber (?:tones|accent)\b",
        r"\bmuted crimson accent\b",
        # Depth of field / film stock
        r"\bshallow depth of field\b",
        r"\bbokeh\b",
        r"\bsubtle film grain\b",
        r"\bheavy film grain\b",
        r"\bfilm grain\b",
        # Style / mood meta-language
        r"\bcinematic(?:\s+photorealistic)?\b",
        r"\bphotorealistic\b",
        r"\bdocumentary(?:\s+photography)?\s+style\b",
        r"\bdark moody atmosphere\b",
        r"\bepic scale\b",
        # Composition terminology (handled by suffix)
        r"\brule of thirds\b",
        r"\bleading lines\b",
    ]
]


def _strip_style_language(description: str) -> str:
    """Remove style/lighting/camera language from a scene description.

    This prevents duplication with the style suffix and YouTube prefix that
    are appended by :func:`build_prompt`.
    """
    cleaned = description
    for pat in _STYLE_STRIP_PATTERNS:
        cleaned = pat.sub("", cleaned)
    # Collapse leftover punctuation artifacts (double commas, leading commas).
    cleaned = re.sub(r",\s*,", ",", cleaned)
    cleaned = re.sub(r"^\s*,\s*", "", cleaned)
    cleaned = re.sub(r"\s*,\s*$", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


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


def _apply_style_override(prefix: str, override: str) -> str:
    """Apply an image style override to the prefix.

    - ``"REPLACE: ..."`` — use the override as the entire prefix.
    - ``"+" or "APPEND: ..."`` — append the override to the default prefix.
    - Otherwise — append the override to the default prefix (additive default).
    """
    stripped = override.strip()
    if stripped.upper().startswith("REPLACE:"):
        return stripped[len("REPLACE:"):].strip()
    if stripped.startswith("+"):
        return prefix + " " + stripped[1:].strip()
    if stripped.upper().startswith("APPEND:"):
        return prefix + " " + stripped[len("APPEND:"):].strip()
    # Default: additive
    return prefix + " " + stripped


def build_prompt(
    scene_description: str,
    style: str,
    composition: str,
    accent_color: str,
    image_style_override: Optional[str] = None,
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
    image_style_override : str, optional
        Per-video style override from Airtable. If provided:
        - ``"REPLACE: ..."`` replaces the default prefix entirely.
        - ``"+" or "APPEND: ..."`` appends to the default prefix.
        - Otherwise appends to the default prefix (additive default).

    Returns
    -------
    str
        The complete prompt string, ready for the image generation model.
    """
    # Cinematic dossier prefix — establishes the photorealistic look
    prefix = YOUTUBE_STYLE_PREFIX.replace("[ACCENT_COLOR]", accent_color)

    if image_style_override and image_style_override.strip():
        prefix = _apply_style_override(prefix, image_style_override)

    comp_text = COMPOSITION_DIRECTIVES.get(composition, "")
    suffix = STYLE_SUFFIXES[style].replace("[ACCENT_COLOR]", accent_color)

    # Strip any style/lighting/camera language that leaked into the scene
    # description to avoid duplicating what the prefix and suffix provide.
    clean_desc = _strip_style_language(scene_description)

    parts = [prefix + " " + clean_desc.rstrip(", ")]
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
    image_style_override: Optional[str] = None,
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
    image_style_override : str, optional
        Per-video style override applied to every prompt's prefix.

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

        prompt = build_prompt(desc, style, composition, color,
                              image_style_override=image_style_override)

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
