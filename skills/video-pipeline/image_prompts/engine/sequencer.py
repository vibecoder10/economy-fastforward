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
    ESTABLISHING_FORMATS,
    FORMAT_CYCLE,
    # Profile-aware getters
    get_max_consecutive_content_type,
    get_max_consecutive_format,
    get_max_consecutive_palette,
    get_max_consecutive_close_up,
    get_act_mood_weights,
    get_default_config,
    get_ken_burns_rules,
    get_ken_burns_pan_alternates,
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
    config = get_default_config()
    if act_timestamps is None:
        act_timestamps = config["act_timestamps"]

    rng = random.Random(seed)
    total_seconds = act_timestamps["act6_end"]
    image_duration = total_seconds / total_images

    assignments: list[dict] = []

    for i in range(total_images):
        timestamp = i * image_duration
        act = _get_act(timestamp, act_timestamps)

        # Detect act transitions for establishing shot preference
        prev_act = assignments[-1]["act"] if assignments else None
        first_of_act = (i == 0) or (act != prev_act)

        content_type = _select_content_type(act, i, total_images, assignments, rng)
        display_format = _select_display_format(
            content_type, i, assignments, rng,
            is_first_of_act=first_of_act,
        )
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
    """Select content type, enforcing max consecutive constraint from profile."""
    all_types = list(ContentType)

    # Filter out types that have hit max consecutive
    max_consec = get_max_consecutive_content_type()
    if history:
        last_type = history[-1]["content_type"]
        run = _count_trailing(history, "content_type", last_type)
        if run >= max_consec:
            all_types = [t for t in all_types if t.value != last_type]

    return rng.choice(all_types)


# ---------------------------------------------------------------------------
# Display format selection
# ---------------------------------------------------------------------------

def _is_first_of_act(index: int, history: list[dict]) -> bool:
    """Return True if this is the first image in a new act."""
    if index == 0:
        return True
    if not history:
        return True
    # We don't know the current act yet at this point, but the caller
    # has already computed it — so we check if the previous entry's act
    # differs.  However, this function is called before the act is
    # stored, so we rely on the caller passing the right context.
    return False


def _select_display_format(
    content_type: ContentType,
    index: int,
    history: list[dict],
    rng: random.Random,
    *,
    is_first_of_act: bool = False,
) -> DisplayFormat:
    """Select display format based on content type affinity, enforcing rotation rules.

    Rules enforced:
    - Max 2 consecutive same format (general)
    - close_up_detail never consecutive (max 1)
    - First image of each act prefers war_table or wall_display (establishing shots)
    - war_table and wall_display get higher weight (workhorses)
    - close_up_detail gets reduced weight (~1 per scene for punctuation)
    """
    # Preferred formats for this content type
    preferred = list(CONTENT_FORMAT_AFFINITY.get(
        content_type,
        [DisplayFormat.WAR_TABLE, DisplayFormat.WALL_DISPLAY],
    ))
    # Add remaining formats as fallback options
    all_formats = preferred + [f for f in FORMAT_CYCLE if f not in preferred]

    # --- Constraint: max consecutive same format ---
    max_consec = get_max_consecutive_format()
    if history:
        last_format = history[-1]["display_format"]
        run = _count_trailing(history, "display_format", last_format)
        if run >= max_consec:
            all_formats = [f for f in all_formats if f.value != last_format]
            if not all_formats:
                all_formats = list(FORMAT_CYCLE)

    # --- Constraint: close_up_detail never consecutive ---
    max_close_up = get_max_consecutive_close_up()
    if history:
        last_format = history[-1]["display_format"]
        if last_format == DisplayFormat.CLOSE_UP_DETAIL.value:
            run = _count_trailing(history, "display_format", last_format)
            if run >= max_close_up:
                all_formats = [f for f in all_formats if f != DisplayFormat.CLOSE_UP_DETAIL]
                if not all_formats:
                    all_formats = list(FORMAT_CYCLE)

    # --- Preference: first image of act → establishing shot ---
    if is_first_of_act and any(f in all_formats for f in ESTABLISHING_FORMATS):
        all_formats = [f for f in all_formats if f in ESTABLISHING_FORMATS]

    # --- Diversity boost: unseen formats get a weight bonus after 8 images ---
    seen_formats = {h["display_format"] for h in history} if history else set()
    diversity_threshold = 8  # start boosting unseen formats after this many images

    # --- Weights: workhorse formats higher, close_up lower ---
    workhorse = {DisplayFormat.WAR_TABLE, DisplayFormat.WALL_DISPLAY}
    weights = []
    for f in all_formats:
        if f in preferred:
            w = 3.0
        elif f in workhorse:
            w = 2.0
        elif f == DisplayFormat.CLOSE_UP_DETAIL:
            w = 1.0  # visual punctuation — lower frequency than workhorses
        else:
            w = 1.0

        # Boost unseen formats to ensure variety
        if len(history) >= diversity_threshold and f.value not in seen_formats:
            w *= 5.0

        weights.append(w)

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
    """Select color mood based on act weights, enforcing max consecutive palette constraint."""
    mood_weights = get_act_mood_weights()
    weights = dict(mood_weights.get(act, mood_weights.get("act1", {})))

    # Enforce max consecutive palette constraint
    max_consec = get_max_consecutive_palette()
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
    kb_rules = get_ken_burns_rules()
    pan_alts = get_ken_burns_pan_alternates()
    base = kb_rules.get(display_format, "slow_zoom_in")

    # For pan-based directions, alternate with previous same-format entries
    if base in pan_alts:
        same_format = [h for h in history if h["display_format"] == display_format.value]
        if same_format and same_format[-1]["ken_burns"] == base:
            return pan_alts[base]
    return base
