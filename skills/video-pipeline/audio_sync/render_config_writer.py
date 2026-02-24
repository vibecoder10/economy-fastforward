"""
Generate the ``render_config.json`` consumed by Remotion.

Assembles all timing, Ken Burns, and transition data into the final
per-video render configuration.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import DEFAULT_FPS, DEFAULT_WIDTH, DEFAULT_HEIGHT


def build_render_config(
    video_id: str,
    audio_path: str,
    scenes: list[dict[str, Any]],
    image_dir: str,
    *,
    fps: int = DEFAULT_FPS,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
) -> dict[str, Any]:
    """
    Build the complete render configuration dict.

    Args:
        video_id: Unique video identifier.
        audio_path: Absolute path to the narration audio file.
        scenes: Fully processed scene list (with timing, Ken Burns,
            transitions already assigned).
        image_dir: Directory containing the generated scene images.
        fps: Frames per second for the output video.
        width: Output width in pixels.
        height: Output height in pixels.

    Returns:
        A dict ready to be serialised as ``render_config.json``.
    """
    # Compute total duration from last scene
    total_duration = 0.0
    if scenes:
        last = scenes[-1]
        total_duration = last.get("display_end", 0.0)

    render_scenes = []
    for scene in scenes:
        scene_number = scene.get("scene_number", 0)
        image_index = scene.get("image_index", 0)

        # Build image path — use image_index if present (per-image entry),
        # otherwise fall back to scene_number-only path (legacy per-scene entry)
        if image_index:
            image_filename = (
                f"Scene_{scene_number:02d}_{image_index:02d}.png"
            )
        else:
            image_filename = f"scene_{scene_number:03d}.png"
        image_path = str(Path(image_dir) / image_filename)

        entry: dict[str, Any] = {
            "scene_number": scene_number,
            "image_path": image_path,
            "display_start": round(scene.get("display_start", 0.0), 4),
            "display_end": round(scene.get("display_end", 0.0), 4),
            "display_duration": round(scene.get("display_duration", 0.0), 4),
            "narration_start": round(scene.get("start_time", 0.0) or 0.0, 4),
            "narration_end": round(scene.get("end_time", 0.0) or 0.0, 4),
            "style": scene.get("style") or scene.get("visual_style") or "",
            "composition": (
                scene.get("composition")
                or scene.get("composition_hint")
                or ""
            ),
            "act": scene.get("act") or scene.get("parent_act") or 0,
            "ken_burns": scene.get("ken_burns", {}),
            "transition_in": scene.get("transition_in", {}),
            "transition_out": scene.get("transition_out", {}),
        }

        # Include per-image fields when available
        if image_index:
            entry["image_index"] = image_index
        sentence_text = scene.get("sentence_text", "")
        if sentence_text:
            entry["sentence_text"] = sentence_text

        render_scenes.append(entry)

    return {
        "video_id": video_id,
        "audio_path": audio_path,
        "total_duration_seconds": round(total_duration, 4),
        "fps": fps,
        "resolution": {
            "width": width,
            "height": height,
        },
        "scenes": render_scenes,
    }


def write_render_config(
    config: dict[str, Any],
    output_path: str | Path,
) -> Path:
    """Serialise *config* to JSON on disk."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(config, f, indent=2)
    return output_path


def save_scene_timing(
    scenes: list[dict[str, Any]],
    output_path: str | Path,
) -> Path:
    """
    Save intermediate scene-level timestamps to
    ``scene_timing.json`` (useful for debugging).
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    timing_data = []
    for s in scenes:
        timing_data.append({
            "scene_number": s.get("scene_number"),
            "start_time": s.get("start_time"),
            "end_time": s.get("end_time"),
            "display_start": s.get("display_start"),
            "display_end": s.get("display_end"),
            "display_duration": s.get("display_duration"),
            "alignment_method": s.get("alignment_method"),
            "alignment_score": s.get("alignment_score"),
        })

    with open(output_path, "w") as f:
        json.dump(timing_data, f, indent=2)

    return output_path
