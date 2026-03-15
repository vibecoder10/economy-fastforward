"""Configuration helpers for scene expansion.

Provides profile-aware getters for visual styles, compositions,
style distributions, and the prompt template builder.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional
from pipeline_constants import Models
from json_utils import parse_json_response

PROMPT_TEMPLATE_PATH = Path(__file__).parent / "prompts" / "concept_expand.txt"


def _get_profile():
    """Return the active visual profile, or None."""
    try:
        from visual_profiles import load_profile
        return load_profile()
    except Exception:
        return None


# Hardcoded fallback valid styles
_DEFAULT_VALID_STYLES = {"dossier", "schema", "echo"}

# Hardcoded fallback compositions
_DEFAULT_COMPOSITIONS = {
    "wide", "medium", "closeup", "environmental",
    "portrait", "overhead", "low_angle",
}

# Hardcoded fallback style distribution
_DEFAULT_STYLE_DISTRIBUTION = {
    1: {"dossier": 90, "schema": 10, "echo": 0},
    2: {"dossier": 70, "schema": 30, "echo": 0},
    3: {"dossier": 45, "schema": 20, "echo": 35},
    4: {"dossier": 35, "schema": 20, "echo": 45},
    5: {"dossier": 50, "schema": 35, "echo": 15},
    6: {"dossier": 65, "schema": 35, "echo": 0},
}


def get_valid_styles() -> set:
    """Get valid visual styles from profile substyles or default."""
    profile = _get_profile()
    if profile and profile.style_system.substyles:
        return set(profile.style_system.substyles.keys())
    return _DEFAULT_VALID_STYLES


# Legacy name — callers should use get_valid_styles()
VALID_STYLES = _DEFAULT_VALID_STYLES


def get_valid_compositions() -> set:
    """Get valid compositions from profile or default."""
    profile = _get_profile()
    if profile and profile.rotation.compositions:
        return set(profile.rotation.compositions)
    return _DEFAULT_COMPOSITIONS


def get_style_distribution() -> dict:
    """Get style distribution by act from profile or default."""
    profile = _get_profile()
    if profile and profile.rotation.scene_expander_style_distribution:
        return profile.rotation.scene_expander_style_distribution
    return _DEFAULT_STYLE_DISTRIBUTION


def get_default_style() -> str:
    """Get the default/fallback visual style name from profile or 'dossier'."""
    profile = _get_profile()
    if profile and profile.style_system.substyles:
        # Return the highest-weight substyle as default
        return max(
            profile.style_system.substyles,
            key=lambda k: profile.style_system.substyles[k].weight,
        )
    return "dossier"


def _pick_composition(visual_style: str, index: int, recent_compositions: list[str]) -> str:
    """Pick a composition using affinity mapping with anti-repetition.

    If the profile has a composition_affinity for the given visual_style,
    prefer those compositions. Fall back to full rotation if preferred
    options would violate the anti-repetition constraint (3+ consecutive).
    """
    all_compositions = list(get_valid_compositions())
    profile = _get_profile()
    affinity = None
    if profile and profile.raw.get("composition_affinity"):
        affinity = profile.raw["composition_affinity"].get(visual_style)

    # Count trailing repetitions
    max_consecutive = 3

    def _would_repeat(comp: str) -> bool:
        if len(recent_compositions) < max_consecutive - 1:
            return False
        return all(c == comp for c in recent_compositions[-(max_consecutive - 1):])

    if affinity:
        # Try preferred compositions in order
        for comp in affinity:
            if not _would_repeat(comp):
                return comp
        # All preferred would repeat — try remaining compositions
        remaining = [c for c in all_compositions if c not in affinity]
        for comp in remaining:
            if not _would_repeat(comp):
                return comp

    # No affinity or all options exhausted — modulo rotation
    comp = all_compositions[index % len(all_compositions)]
    if _would_repeat(comp):
        # Shift to next option
        for offset in range(1, len(all_compositions)):
            alt = all_compositions[(index + offset) % len(all_compositions)]
            if not _would_repeat(alt):
                return alt
    return comp


# Legacy names — callers should use getters above
VALID_COMPOSITIONS = _DEFAULT_COMPOSITIONS
STYLE_DISTRIBUTION = _DEFAULT_STYLE_DISTRIBUTION

# Concept count range by words in scene text
MIN_CONCEPTS = 6
MAX_CONCEPTS = 12
MIN_WORDS_PER_CONCEPT = 10   # ~4s at 2.5 wps — prevents flash images
MAX_WORDS_PER_CONCEPT = 25   # ~10s at 2.5 wps — keeps pacing engaging


def _estimate_concept_count(scene_text: str) -> int:
    """Decide how many concepts a scene should have based on word count.

    Ensures every concept stays within MAX_WORDS_PER_CONCEPT words.
    """
    word_count = len(scene_text.split())
    # Need at least ceil(word_count / MAX_WORDS_PER_CONCEPT) concepts
    min_needed = max(MIN_CONCEPTS, -(-word_count // MAX_WORDS_PER_CONCEPT))
    ideal = max(min_needed, min(MAX_CONCEPTS, round(word_count / 15)))
    return ideal


def _build_style_weights_text(act_number: int) -> str:
    """Build human-readable style weight text for the prompt."""
    style_dist = get_style_distribution()
    dist = style_dist.get(act_number, style_dist.get(1, {}))
    if not dist:
        return "- Single style (no substyle distribution)"
    lines = []
    for style_name, pct in dist.items():
        lines.append(f"- {style_name.title()}: {pct}%")
    if act_number in (1, 2, 6) and dist.get("echo", 0) == 0:
        lines.append("- Echo is NOT allowed in this act")
    return "\n".join(lines)


def _build_prompt(
    scene_number: int,
    scene_text: str,
    visual_seeds: str,
    accent_color: str,
    act_number: int,
    concept_count: int,
    total_scenes: int,
) -> str:
    """Build the concept expansion prompt for one scene."""
    template = PROMPT_TEMPLATE_PATH.read_text()
    return template.format(
        SCENE_NUMBER=scene_number,
        SCENE_TEXT=scene_text,
        VISUAL_SEEDS=visual_seeds or "(none provided)",
        ACCENT_COLOR=accent_color.replace("_", " "),
        ACT_NUMBER=act_number,
        CONCEPT_COUNT=concept_count,
        STYLE_WEIGHTS=_build_style_weights_text(act_number),
        TOTAL_SCENES=total_scenes,
    )


def _parse_response(response_text: str) -> dict:
    """Extract JSON from the LLM response."""
    result = parse_json_response(response_text, default=None)
    if result is None:
        raise ValueError("No JSON found in response")
    return result
