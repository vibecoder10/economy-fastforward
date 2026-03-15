"""
Timing adjustment and validation.

Applies pre-roll, post-hold, minimum/maximum display time, and resolves
overlaps to produce final display_start / display_end per scene.
"""

from __future__ import annotations

from typing import Any

from .config import (
    MIN_DISPLAY_SECONDS,
    MAX_DISPLAY_SECONDS,
    MAX_IMAGE_DISPLAY_SECONDS,
    PRE_ROLL_SECONDS,
    POST_HOLD_SECONDS,
)


# ---------------------------------------------------------------------------
# Pre-roll: image appears slightly before narration
# ---------------------------------------------------------------------------

def apply_pre_roll(
    scenes: list[dict[str, Any]],
    pre_roll: float = PRE_ROLL_SECONDS,
) -> list[dict[str, Any]]:
    """
    Set ``display_start`` to ``start_time - pre_roll`` (clamped to 0).

    The viewer needs a fraction of a second to register the new visual
    before the associated narration begins.
    """
    for scene in scenes:
        start = scene.get("start_time")
        if start is not None:
            scene["display_start"] = max(0.0, start - pre_roll)
        else:
            scene["display_start"] = 0.0
    return scenes


# ---------------------------------------------------------------------------
# Post-hold: image lingers briefly after narration
# ---------------------------------------------------------------------------

def apply_post_hold(
    scenes: list[dict[str, Any]],
    post_hold: float = POST_HOLD_SECONDS,
) -> list[dict[str, Any]]:
    """
    Set ``display_end`` to ``end_time + post_hold``, but never extend
    past the next scene's ``display_start``.
    """
    for i, scene in enumerate(scenes):
        end = scene.get("end_time")
        if end is None:
            # Fallback — will be fixed later
            scene["display_end"] = scene.get("display_start", 0.0) + MIN_DISPLAY_SECONDS
            continue

        desired_end = end + post_hold

        # Clamp to next scene's display_start if available
        if i < len(scenes) - 1:
            next_start = scenes[i + 1].get("display_start")
            if next_start is not None:
                desired_end = min(desired_end, next_start)

        scene["display_end"] = desired_end

    return scenes


# ---------------------------------------------------------------------------
# Minimum display time
# ---------------------------------------------------------------------------

def enforce_minimum_display(
    scenes: list[dict[str, Any]],
    min_seconds: float = MIN_DISPLAY_SECONDS,
) -> list[dict[str, Any]]:
    """
    Ensure no image displays for less than *min_seconds*.

    If a scene is too short it is extended; subsequent scenes are shifted
    forward if this creates an overlap.
    """
    for i, scene in enumerate(scenes):
        duration = scene["display_end"] - scene["display_start"]

        if duration < min_seconds:
            scene["display_end"] = scene["display_start"] + min_seconds

            # Shift next scene forward if we now overlap
            if i < len(scenes) - 1:
                if scene["display_end"] > scenes[i + 1]["display_start"]:
                    scenes[i + 1]["display_start"] = scene["display_end"]

    return scenes


# ---------------------------------------------------------------------------
# Maximum display time
# ---------------------------------------------------------------------------

def enforce_maximum_display(
    scenes: list[dict[str, Any]],
    max_seconds: float = MAX_DISPLAY_SECONDS,
) -> list[dict[str, Any]]:
    """
    Clamp any scene longer than *max_seconds*.

    The Ken Burns speed multiplier (calculated later) will slow the zoom
    proportionally for long scenes, so capping here is only a safeguard
    against extreme outliers.
    """
    for scene in scenes:
        duration = scene["display_end"] - scene["display_start"]
        if duration > max_seconds:
            scene["display_end"] = scene["display_start"] + max_seconds
    return scenes


# ---------------------------------------------------------------------------
# Resolve overlaps
# ---------------------------------------------------------------------------

def resolve_overlaps(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Ensure no two scenes overlap: each scene's ``display_start`` must be
    >= the previous scene's ``display_end``.
    """
    for i in range(1, len(scenes)):
        prev_end = scenes[i - 1]["display_end"]
        if scenes[i]["display_start"] < prev_end:
            scenes[i]["display_start"] = prev_end
        # Also make sure display_end >= display_start
        if scenes[i]["display_end"] < scenes[i]["display_start"]:
            scenes[i]["display_end"] = scenes[i]["display_start"] + MIN_DISPLAY_SECONDS
    return scenes


# ---------------------------------------------------------------------------
# Per-image max duration enforcement
# ---------------------------------------------------------------------------

def enforce_max_image_duration(
    scene_raw: list[dict[str, Any]],
    max_seconds: float = MAX_IMAGE_DISPLAY_SECONDS,
    min_seconds: float = 1.0,
) -> list[dict[str, Any]]:
    """Enforce a hard maximum duration per image within a single scene.

    Shaves excess time off images that exceed *max_seconds* and donates
    it to the shortest images in the scene.  This keeps the overall
    scene timeline intact while preventing any single image from
    overstaying.  Much gentler than the old "redistribute evenly"
    approach which flattened all variation.

    Args:
        scene_raw: Per-image entries for ONE scene.  Each dict must
            have ``duration``, ``display_start``, and ``display_end``.
        max_seconds: Hard cap per image (default from config).
        min_seconds: Floor per image (default 1 s).

    Returns:
        The same list with durations, display_start, and display_end
        adjusted in-place.
    """
    if not scene_raw:
        return scene_raw

    has_outlier = any(e["duration"] > max_seconds for e in scene_raw)
    if not has_outlier:
        return scene_raw

    # Pass 1: collect excess from images over the cap
    excess = 0.0
    for entry in scene_raw:
        if entry["duration"] > max_seconds:
            excess += entry["duration"] - max_seconds
            entry["duration"] = max_seconds

    # Pass 2: donate excess to the shortest images (sorted ascending)
    if excess > 0 and len(scene_raw) > 1:
        order = sorted(range(len(scene_raw)), key=lambda i: scene_raw[i]["duration"])
        recipients = [i for i in order if scene_raw[i]["duration"] < max_seconds]
        if recipients:
            per_recipient = round(excess / len(recipients), 2)
            for i in recipients:
                give = min(per_recipient, max_seconds - scene_raw[i]["duration"])
                scene_raw[i]["duration"] = round(scene_raw[i]["duration"] + give, 2)
                excess -= give
                if excess <= 0.01:
                    break

    # Rebuild start/end times to keep the timeline contiguous
    cursor = scene_raw[0]["display_start"]
    for entry in scene_raw:
        entry["display_start"] = round(cursor, 4)
        entry["display_end"] = round(cursor + entry["duration"], 4)
        cursor += entry["duration"]

    return scene_raw


# ---------------------------------------------------------------------------
# Compute display_duration
# ---------------------------------------------------------------------------

def compute_display_durations(
    scenes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Add ``display_duration`` = ``display_end`` - ``display_start``."""
    for scene in scenes:
        scene["display_duration"] = round(
            scene["display_end"] - scene["display_start"], 4
        )
    return scenes


# ---------------------------------------------------------------------------
# Main entry-point
# ---------------------------------------------------------------------------

def adjust_timing(
    scenes: list[dict[str, Any]],
    *,
    pre_roll: float = PRE_ROLL_SECONDS,
    post_hold: float = POST_HOLD_SECONDS,
    min_display: float = MIN_DISPLAY_SECONDS,
    max_display: float = MAX_DISPLAY_SECONDS,
) -> list[dict[str, Any]]:
    """
    Full timing-adjustment pipeline.

    1. Pre-roll (image appears before narration)
    2. Post-hold (image stays after narration)
    3. Minimum display enforcement
    4. Maximum display enforcement
    5. Overlap resolution
    6. Duration computation
    """
    scenes = apply_pre_roll(scenes, pre_roll=pre_roll)
    scenes = apply_post_hold(scenes, post_hold=post_hold)
    scenes = enforce_minimum_display(scenes, min_seconds=min_display)
    scenes = enforce_maximum_display(scenes, max_seconds=max_display)
    scenes = resolve_overlaps(scenes)
    scenes = compute_display_durations(scenes)
    return scenes
