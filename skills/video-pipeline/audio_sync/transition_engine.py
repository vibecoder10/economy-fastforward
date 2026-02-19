"""
Transition type selection between scenes.

Determines the transition style and duration based on style changes
and act boundaries.
"""

from __future__ import annotations

from typing import Any

from .config import CROSSFADE_DURATION, STYLE_CHANGE_FADE, ACT_TRANSITION_BLACK


def determine_transition(
    current_scene: dict[str, Any],
    next_scene: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Choose a transition type and duration between *current_scene* and
    *next_scene*.

    Rules (in priority order):
    1. Act change -> dip-to-black (1.5 s)
    2. Style change within same act -> longer crossfade (0.8 s)
    3. Same style, same act -> quick crossfade (0.4 s)
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

    # Act change -> dip to black
    if cur_act is not None and nxt_act is not None and cur_act != nxt_act:
        return {"type": "dip_to_black", "duration": ACT_TRANSITION_BLACK}

    # Style change within same act -> longer crossfade
    if cur_style and nxt_style and cur_style != nxt_style:
        return {"type": "crossfade", "duration": STYLE_CHANGE_FADE}

    # Default — quick crossfade
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
