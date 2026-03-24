"""
Per-scene Ken Burns effect calculator.

Determines zoom direction, speed multiplier, and scale/offset parameters
based on each scene's composition type and display duration.
"""

from __future__ import annotations

from typing import Any

from .config import (
    MIN_DISPLAY_SECONDS,
    get_ken_burns_presets,
    get_composition_direction_map,
    get_ken_burns_base_duration,
    get_ken_burns_pan_alternates,
)


def calculate_ken_burns(
    composition: str,
    display_duration: float,
    scene_index: int,
) -> dict[str, Any]:
    """
    Calculate Ken Burns parameters for a single scene.

    Args:
        composition: Composition hint (``wide``, ``medium``, ``closeup``,
            ``environmental``, ``portrait``, ``overhead``, ``low_angle``).
        display_duration: How long the image will be on screen (seconds).
        scene_index: Zero-based scene position, used to alternate pan
            directions for visual variety.

    Returns:
        Dict with ``direction``, ``speed_multiplier``, and the
        scale/offset keys from :data:`KEN_BURNS_PRESETS`.
    """
    # Use profile-aware getters (falls back to hardcoded defaults)
    direction_map = get_composition_direction_map()
    presets = get_ken_burns_presets()
    base_duration = get_ken_burns_base_duration()

    direction = direction_map.get(
        composition.lower() if composition else "",
        "slow_zoom_in",
    )

    # Alternate pan direction for variety (every other medium/environmental)
    pan_alts = get_ken_burns_pan_alternates()
    if direction in pan_alts and scene_index % 2 == 0:
        direction = pan_alts[direction]

    # Speed multiplier — slower zoom for longer scenes
    safe_duration = max(display_duration, MIN_DISPLAY_SECONDS)
    speed_multiplier = round(base_duration / safe_duration, 3)

    config = presets.get(direction, presets.get("slow_zoom_in", {})).copy()
    config["direction"] = direction
    config["speed_multiplier"] = speed_multiplier

    return config


def assign_ken_burns(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Add ``ken_burns`` configuration to every scene.

    Reads ``composition`` (or ``composition_hint``) and
    ``display_duration`` from each scene dict.
    """
    base_duration = get_ken_burns_base_duration()
    for i, scene in enumerate(scenes):
        composition = (
            scene.get("composition")
            or scene.get("composition_hint")
            or "wide"
        )
        display_duration = scene.get("display_duration", base_duration)

        scene["ken_burns"] = calculate_ken_burns(
            composition=composition,
            display_duration=display_duration,
            scene_index=i,
        )

    return scenes
