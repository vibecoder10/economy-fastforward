"""
Transition type selection between scenes.

Determines the transition style and duration based on style changes,
act boundaries, and (D12-2) the incoming shot's authored transition_kind
(migration 148, assets.transition_kind — threaded through render_config
scene dicts by whichever caller reads the assets table; see
storyengine/backend/render_static.py's _build_render_config).
"""

from __future__ import annotations

from typing import Any

from .config import (
    CROSSFADE_DURATION,
    STYLE_CHANGE_FADE,
    ACT_TRANSITION_BLACK,
    HARD_CUT_DURATION,
    LOCATION_CUT_FADE,
    MONTAGE_FADE,
    MEMORY_DISSOLVE,
)

# D12-2: per-boundary transition_kind -> distinct treatment. Keyed by the
# INCOMING shot's transition_kind (next_scene["transition_kind"] — the value
# describes how THAT shot cuts in from the previous one, mirroring
# ShotDraft.transition_from_previous). "opening" is deliberately absent: the
# very first scene's transition_in is hardcoded to fade_from_black by
# assign_transitions and never routed through this map, so "whatever the
# first boundary does today" needs no entry here. A kind this map doesn't
# recognize (None, "", unrecognized future value, "opening") falls through
# to the generic quick-crossfade default below, same as no kind at all.
TRANSITION_KIND_TREATMENTS: dict[str, dict[str, Any]] = {
    "continuous": {"type": "cut", "duration": HARD_CUT_DURATION},
    "time_cut": {"type": "cut", "duration": HARD_CUT_DURATION},
    "location_cut": {"type": "crossfade", "duration": LOCATION_CUT_FADE},
    "montage": {"type": "crossfade", "duration": MONTAGE_FADE},
    "memory": {"type": "dissolve", "duration": MEMORY_DISSOLVE},
}


def determine_transition(
    current_scene: dict[str, Any],
    next_scene: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Choose a transition type and duration between *current_scene* and
    *next_scene*.

    Rules (in priority order — 1 and 2 encode proven editorial intent and
    WIN regardless of transition_kind; kind only applies where today's
    logic would otherwise fall through to the generic quick crossfade):
    1. Act change -> dip-to-black (1.5 s)
    2. Style change within same act -> longer crossfade (0.8 s)
    3. next_scene carries a recognized transition_kind -> that kind's
       dedicated treatment (TRANSITION_KIND_TREATMENTS) — continuous/
       time_cut -> hard cut, location_cut -> quick crossfade, montage ->
       short crossfade, memory -> long dissolve.
    4. No kind (absent/NULL/unrecognized) -> quick crossfade (0.4 s), byte-
       identical to pre-D12-2 behavior — every video rendered before
       migration 148 has NULL transition_kind on every asset row and lands
       here exactly as it always has.
    """
    if next_scene is None:
        # Last scene — fade to black
        return {"type": "fade_to_black", "duration": 1.0}

    cur_act = current_scene.get("act") or current_scene.get("parent_act")
    nxt_act = next_scene.get("act") or next_scene.get("parent_act")

    cur_style = (
        current_scene.get("style")
        or current_scene.get("visual_style")
        or ""
    )
    nxt_style = (
        next_scene.get("style")
        or next_scene.get("visual_style")
        or ""
    )

    # Act change -> dip to black (wins over kind)
    if cur_act is not None and nxt_act is not None and cur_act != nxt_act:
        return {"type": "dip_to_black", "duration": ACT_TRANSITION_BLACK}

    # Style change within same act -> longer crossfade (wins over kind)
    if cur_style and nxt_style and cur_style != nxt_style:
        return {"type": "crossfade", "duration": STYLE_CHANGE_FADE}

    # D12-2: incoming shot's transition_kind -> its dedicated treatment.
    kind = (next_scene.get("transition_kind") or "").strip().lower()
    treatment = TRANSITION_KIND_TREATMENTS.get(kind)
    if treatment is not None:
        return dict(treatment)  # copy — never let a caller mutate the shared map

    # Default — quick crossfade (also the fallback for absent/unrecognized kind)
    return {"type": "crossfade", "duration": CROSSFADE_DURATION}


def assign_transitions(
    scenes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Assign ``transition_in`` and ``transition_out`` to every scene.

    The first scene always fades from black; each subsequent scene's
    ``transition_in`` mirrors the previous scene's ``transition_out``.
    """
    for i, scene in enumerate(scenes):
        # transition_in
        if i == 0:
            scene["transition_in"] = {"type": "fade_from_black", "duration": 1.0}
        else:
            # Mirror the previous scene's transition_out
            prev_out = scenes[i - 1].get("transition_out", {})
            scene["transition_in"] = {
                "type": prev_out.get("type", "crossfade"),
                "duration": prev_out.get("duration", CROSSFADE_DURATION),
            }

        # transition_out
        next_scene = scenes[i + 1] if i < len(scenes) - 1 else None
        scene["transition_out"] = determine_transition(scene, next_scene)

    return scenes
