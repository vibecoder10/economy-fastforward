"""
Sequencing engine for the Holographic Intelligence Display system.

Assigns a content type, display format, color mood, and Ken Burns direction
to each image position in the video, respecting rotation constraints and
narrative-arc pacing rules.

Version: 4.0 (Mar 2026) — Holographic Intelligence Display system
"""

from __future__ import annotations

import random
from typing import Optional

from .style_config import (
    ContentType,
    DisplayFormat,
    ColorMood,
    CONTENT_FORMAT_AFFINITY,
    KEN_BURNS_PAN_ALTERNATES,
    KEN_BURNS_RULES,
    ACT_MOOD_WEIGHTS,
    DEFAULT_CONFIG,
    FORMAT_CYCLE,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def assign_styles(
    total_images: int,
    act_timestamps: Optional[dict] = None,
    *,
    seed: Optional[int] = None,
) -> list[dict]:
    """Assign content_type, display_format, color_mood, and ken_burns for every image.

    Parameters
    ----------
    total_images : int
        Number of images in the video.
    act_timestamps : dict, optional
        Mapping of ``"act{N}_end"`` to seconds. Falls back to defaults.
    seed : int, optional
        If provided, seeds the RNG for reproducible results.

    Returns
    -------
    list[dict]
        One entry per image with keys: ``index``, ``timestamp``, ``act``,
        ``content_type``, ``display_format``, ``color_mood``, ``ken_burns``.
    """
    if act_timestamps is None:
        act_timestamps = DEFAULT_CONFIG["act_timestamps"]

    rng = random.Random(seed)
    total_seconds = act_timestamps["act6_end"]
    image_duration = total_seconds / total_images

    assignments: list[dict] = []

    for i in range(total_images):
        timestamp = i * image_duration
        act = _get_act(timestamp, act_timestamps)

        content_type = _select_content_type(act, i, total_images, assignments, rng)
        display_format = _select_display_format(content_type, i, assignments, rng)
        color_mood = _select_color_mood(act, i, total_images, assignments, rng)
        ken_burns = _select_ken_burns(display_format, assignments)

        assignments.append({
            "index": i,
            "timestamp": round(timestamp, 2),
            "act": act,
            "content_type": content_type.value,
            "display_format": display_format.value,
            "color_mood": color_mood.value,
            "ken_burns": ken_burns,
        })

    return assignments


# ---------------------------------------------------------------------------
# Act resolution
# ---------------------------------------------------------------------------

def _get_act(timestamp: float, act_timestamps: dict) -> str:
    """Return the act name (``"act1"`` .. ``"act6"``) for a timestamp."""
    if timestamp < act_timestamps["act1_end"]:
        return "act1"
    if timestamp < act_timestamps["act2_end"]:
        return "act2"
    if timestamp < act_timestamps["act3_end"]:
        return "act3"
    if timestamp < act_timestamps["act4_end"]:
        return "act4"
    if timestamp < act_timestamps["act5_end"]:
        return "act5"
    return "act6"


# ---------------------------------------------------------------------------
# Content type selection
# ---------------------------------------------------------------------------

def _count_trailing(history: list[dict], key: str, value: str) -> int:
    """Count how many consecutive images at the tail of *history* have *value* for *key*."""
    count = 0
    for entry in reversed(history):
        if entry[key] == value:
            count += 1
        else:
            break
    return count


def _select_content_type(
    act: str,
    index: int,
    total_images: int,
    history: list[dict],
    rng: random.Random,
) -> ContentType:
    """Select content type, enforcing max 2 consecutive same type."""
    all_types = list(ContentType)

    # Filter out types that have hit max consecutive
    max_consec = DEFAULT_CONFIG["max_consecutive_content_type"]
    if history:
        last_type = history[-1]["content_type"]
        run = _count_trailing(history, "content_type", last_type)
        if run >= max_consec:
            all_types = [t for t in all_types if t.value != last_type]

    return rng.choice(all_types)


# ---------------------------------------------------------------------------
# Display format selection
# ---------------------------------------------------------------------------

def _select_display_format(
    content_type: ContentType,
    index: int,
    history: list[dict],
    rng: random.Random,
) -> DisplayFormat:
    """Select display format based on content type affinity, enforcing max 2 consecutive."""
    # Preferred formats for this content type
    preferred = list(CONTENT_FORMAT_AFFINITY.get(
        content_type,
        [DisplayFormat.WAR_TABLE, DisplayFormat.WALL_DISPLAY],
    ))
    # Add remaining formats as fallback options
    all_formats = preferred + [f for f in FORMAT_CYCLE if f not in preferred]

    # Filter out formats that have hit max consecutive
    max_consec = DEFAULT_CONFIG["max_consecutive_format"]
    if history:
        last_format = history[-1]["display_format"]
        run = _count_trailing(history, "display_format", last_format)
        if run >= max_consec:
            all_formats = [f for f in all_formats if f.value != last_format]
            if not all_formats:
                all_formats = list(FORMAT_CYCLE)

    # Weight preferred formats higher
    weights = []
    for f in all_formats:
        if f in preferred:
            weights.append(3.0)
        else:
            weights.append(1.0)

    return rng.choices(all_formats, weights=weights, k=1)[0]


# ---------------------------------------------------------------------------
# Color mood selection
# ---------------------------------------------------------------------------

def _select_color_mood(
    act: str,
    index: int,
    total_images: int,
    history: list[dict],
    rng: random.Random,
) -> ColorMood:
    """Select color mood based on act weights, enforcing max 3 consecutive same palette."""
    weights = dict(ACT_MOOD_WEIGHTS.get(act, ACT_MOOD_WEIGHTS["act1"]))

    # Enforce max consecutive palette constraint
    max_consec = DEFAULT_CONFIG["max_consecutive_palette"]
    if history:
        last_mood = history[-1]["color_mood"]
        run = _count_trailing(history, "color_mood", last_mood)
        if run >= max_consec:
            # Zero out the over-used mood
            for mood in ColorMood:
                if mood.value == last_mood:
                    weights[mood] = 0.0

    # Normalize and pick
    moods = list(weights.keys())
    w = [weights[m] for m in moods]
    total_w = sum(w)
    if total_w == 0:
        return ColorMood.STRATEGIC

    return rng.choices(moods, weights=w, k=1)[0]


# ---------------------------------------------------------------------------
# Ken Burns direction
# ---------------------------------------------------------------------------

def _select_ken_burns(display_format: DisplayFormat, history: list[dict]) -> str:
    """Choose a Ken Burns zoom/pan direction, alternating pans to avoid monotony."""
    base = KEN_BURNS_RULES.get(display_format, "slow_zoom_in")

    # For pan-based directions, alternate with previous same-format entries
    if base in KEN_BURNS_PAN_ALTERNATES:
        same_format = [h for h in history if h["display_format"] == display_format.value]
        if same_format and same_format[-1]["ken_burns"] == base:
            return KEN_BURNS_PAN_ALTERNATES[base]
    return base
