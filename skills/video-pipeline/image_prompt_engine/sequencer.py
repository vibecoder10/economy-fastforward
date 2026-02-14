"""
Sequencing engine for the visual identity system.

Assigns a visual style (dossier / schema / echo) and composition directive
to each image position in the video, respecting the narrative-arc pacing
rules defined in the PRD.
"""

from __future__ import annotations

import random
from typing import Optional

from .style_config import (
    ACT_STYLE_WEIGHTS,
    COMPOSITION_CYCLE,
    DEFAULT_CONFIG,
    KEN_BURNS_PAN_ALTERNATES,
    KEN_BURNS_RULES,
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
    """Assign style, composition, and Ken Burns direction for every image.

    Parameters
    ----------
    total_images : int
        Number of images in the video.
    act_timestamps : dict, optional
        Mapping of ``"act{N}_end"`` to seconds. Falls back to
        ``DEFAULT_CONFIG["act_timestamps"]``.
    seed : int, optional
        If provided, seeds the RNG for reproducible results.

    Returns
    -------
    list[dict]
        One entry per image with keys: ``index``, ``timestamp``, ``act``,
        ``style``, ``composition``, ``ken_burns``.
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

        style = _select_style(act, i, total_images, assignments, rng)
        composition = _select_composition(style, assignments)
        ken_burns = _select_ken_burns(composition, assignments)

        assignments.append({
            "index": i,
            "timestamp": round(timestamp, 2),
            "act": act,
            "style": style,
            "composition": composition,
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
# Style selection with sequencing rules
# ---------------------------------------------------------------------------

def _count_trailing_style(history: list[dict], style: str) -> int:
    """Count how many consecutive images at the tail of *history* have *style*."""
    count = 0
    for entry in reversed(history):
        if entry["style"] == style:
            count += 1
        else:
            break
    return count


def _select_style(
    act: str,
    index: int,
    total_images: int,
    history: list[dict],
    rng: random.Random,
) -> str:
    """Select the visual style for position *index*, enforcing all global rules."""

    # Rule 6: First and last images must be Dossier.
    if index == 0 or index == total_images - 1:
        return "dossier"

    echo_run = _count_trailing_style(history, "echo") if history else 0

    # Rule 3: If in an echo cluster below minimum, FORCE continuation.
    if echo_run > 0 and echo_run < DEFAULT_CONFIG["echo_cluster_min"]:
        return "echo"

    # Rule 3+4: If in an echo cluster at/above max, FORCE exit to Dossier.
    if echo_run >= DEFAULT_CONFIG["echo_cluster_max"]:
        return "dossier"

    # If in an echo cluster between min and max, decide: continue or exit.
    # Rule 4: exiting always goes to Dossier.
    if echo_run > 0:
        act_echo_weight = ACT_STYLE_WEIGHTS[act].get("echo", 0)
        if act in ("act1", "act2", "act6"):
            act_echo_weight = 0
        if act_echo_weight > 0 and rng.random() < act_echo_weight:
            return "echo"
        return "dossier"  # Rule 4: exit echo cluster → always Dossier

    # --- Not in an echo cluster. Normal weighted selection. ---
    weights = dict(ACT_STYLE_WEIGHTS[act])

    # Rule 2: No Echo in acts 1, 2, or 6.
    if act in ("act1", "act2", "act6"):
        weights["echo"] = 0.0

    # Rule 3 (isolated-single prevention): Don't start an echo run if we
    # can't sustain at least the minimum cluster size.
    if weights.get("echo", 0) > 0:
        min_cluster = DEFAULT_CONFIG["echo_cluster_min"]
        if index + min_cluster >= total_images:
            weights["echo"] = 0.0
        else:
            remaining_in_act = _remaining_images_in_act(
                index, total_images, act, history,
            )
            if remaining_in_act < min_cluster:
                weights["echo"] = 0.0

    # Compensate for forced cluster continuation: starting an echo cluster
    # commits at least echo_cluster_min images, which inflates the effective
    # echo rate.  Reduce the start probability proportionally.
    if weights.get("echo", 0) > 0:
        avg_cluster = (
            DEFAULT_CONFIG["echo_cluster_min"] + DEFAULT_CONFIG["echo_cluster_max"]
        ) / 2
        weights["echo"] = weights["echo"] / avg_cluster

    # Rule 1: No more than max_consecutive same style.
    # For Dossier, reduce effective max near the end of the video to account
    # for the forced-Dossier last image (prevents N consecutive + forced last
    # from exceeding the limit).
    max_consecutive = DEFAULT_CONFIG["max_consecutive_same_style"]
    remaining_to_end = total_images - 1 - index

    for style_name in ("dossier", "schema", "echo"):
        if weights.get(style_name, 0) == 0:
            continue
        effective_max = max_consecutive
        if style_name == "dossier" and 0 < remaining_to_end <= max_consecutive:
            effective_max = max_consecutive - 1
        run = _count_trailing_style(history, style_name)
        if run >= effective_max:
            weights[style_name] = 0.0

    # Rule 5: Schema rarely clusters.
    if history and history[-1]["style"] == "schema":
        schema_run = _count_trailing_style(history, "schema")
        # Determine the strictest limit across the entire schema run.
        # A run that started outside Act 5 keeps the stricter limit even
        # if the current image falls into Act 5 (prevents cross-act escape).
        schema_max = (
            DEFAULT_CONFIG["schema_cluster_max_act5"]
            if act == "act5"
            else DEFAULT_CONFIG["schema_cluster_max_default"]
        )
        cluster_start_idx = len(history) - schema_run
        if 0 <= cluster_start_idx < len(history):
            start_act = history[cluster_start_idx]["act"]
            if start_act != "act5":
                schema_max = min(
                    schema_max, DEFAULT_CONFIG["schema_cluster_max_default"],
                )
        if schema_run >= schema_max:
            weights["schema"] = 0.0
        elif act != "act5":
            weights["schema"] = weights.get("schema", 0) * 0.2

    # Normalize and pick.
    total_w = sum(weights.values())
    if total_w == 0:
        return "dossier"

    r = rng.random() * total_w
    cumulative = 0.0
    for style, w in weights.items():
        cumulative += w
        if r <= cumulative:
            return style
    return "dossier"  # fallback


def _remaining_images_in_act(
    current_index: int,
    total_images: int,
    current_act: str,
    history: list[dict],
) -> int:
    """Estimate how many images remain in the current act after *current_index*."""
    # Count how many images were already in this act.
    act_start_index = current_index  # will walk backwards
    for entry in reversed(history):
        if entry["act"] == current_act:
            act_start_index = entry["index"]
        else:
            break
    # Rough estimate: proportional to act time share.
    act_timestamps = DEFAULT_CONFIG["act_timestamps"]
    total_seconds = act_timestamps["act6_end"]
    act_durations = _act_durations(act_timestamps)
    act_fraction = act_durations.get(current_act, 0) / total_seconds
    estimated_act_images = max(1, round(total_images * act_fraction))
    images_used = current_index - act_start_index
    return max(0, estimated_act_images - images_used)


def _act_durations(act_timestamps: dict) -> dict:
    ends = [
        ("act1", 0, act_timestamps["act1_end"]),
        ("act2", act_timestamps["act1_end"], act_timestamps["act2_end"]),
        ("act3", act_timestamps["act2_end"], act_timestamps["act3_end"]),
        ("act4", act_timestamps["act3_end"], act_timestamps["act4_end"]),
        ("act5", act_timestamps["act4_end"], act_timestamps["act5_end"]),
        ("act6", act_timestamps["act5_end"], act_timestamps["act6_end"]),
    ]
    return {name: end - start for name, start, end in ends}


# ---------------------------------------------------------------------------
# Composition selection
# ---------------------------------------------------------------------------

def _select_composition(style: str, history: list[dict]) -> str:
    """Pick the next composition directive, cycling within same-style runs."""
    # Find the index of the last composition used for this style.
    same_style = [h for h in history if h["style"] == style]
    if not same_style:
        return COMPOSITION_CYCLE[0]

    last_comp = same_style[-1]["composition"]
    try:
        idx = COMPOSITION_CYCLE.index(last_comp)
    except ValueError:
        idx = -1
    return COMPOSITION_CYCLE[(idx + 1) % len(COMPOSITION_CYCLE)]


# ---------------------------------------------------------------------------
# Ken Burns direction
# ---------------------------------------------------------------------------

def _select_ken_burns(composition: str, history: list[dict]) -> str:
    """Choose a Ken Burns zoom/pan direction, alternating pans to avoid monotony."""
    base = KEN_BURNS_RULES.get(composition, "slow_zoom_in")

    # For pan-based directions, alternate with previous same-composition entries.
    if base in KEN_BURNS_PAN_ALTERNATES:
        same_comp = [h for h in history if h["composition"] == composition]
        if same_comp and same_comp[-1]["ken_burns"] == base:
            return KEN_BURNS_PAN_ALTERNATES[base]
    return base
