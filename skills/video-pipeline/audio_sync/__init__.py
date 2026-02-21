"""
audio_sync — Whisper-driven image timing for Remotion.

High-level API consumed by the pipeline orchestrator::

    from audio_sync import AudioSyncPipeline

    sync = AudioSyncPipeline()
    words       = sync.transcribe(audio_path)
    aligned     = sync.align(scene_list, words)
    timed       = sync.adjust_timing(aligned)
    config      = sync.generate_render_config(video_id, audio_path, timed, image_dir)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .transcriber import (
    WordTimestamp,
    transcribe,
    transcribe_api,
    extract_words,
    save_whisper_raw,
    load_whisper_raw,
)
from .aligner import (
    align_scenes_to_timestamps,
    validate_alignment,
)
from .timing_adjuster import adjust_timing
from .transition_engine import assign_transitions
from .ken_burns_calculator import assign_ken_burns
from .render_config_writer import (
    build_render_config,
    write_render_config,
    save_scene_timing,
)
class AudioSyncPipeline:
    """
    End-to-end orchestrator for the audio-sync pipeline.

    Wraps transcription, alignment, timing adjustment, transition
    assignment, Ken Burns calculation, and render config generation
    into a simple procedural API.

    Transcription always uses the OpenAI Whisper API (no local model).
    """

    def __init__(self, **_kwargs) -> None:
        pass

    # ------------------------------------------------------------------
    # Step 1 — Transcribe
    # ------------------------------------------------------------------

    def transcribe(
        self,
        audio_path: str,
        cache_dir: str | Path | None = None,
    ) -> list[WordTimestamp]:
        """Run Whisper API on *audio_path* and return word timestamps."""
        return transcribe(audio_path, cache_dir=cache_dir)

    # ------------------------------------------------------------------
    # Step 2 — Align
    # ------------------------------------------------------------------

    def align(
        self,
        scene_list: list[dict[str, Any]],
        whisper_words: list[WordTimestamp],
    ) -> list[dict[str, Any]]:
        """Match each scene's script_excerpt to word timestamps."""
        aligned = align_scenes_to_timestamps(scene_list, whisper_words)
        report = validate_alignment(aligned)
        self._last_alignment_report = report
        return aligned

    # ------------------------------------------------------------------
    # Step 3 — Adjust timing
    # ------------------------------------------------------------------

    def adjust_timing(
        self,
        aligned_scenes: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Apply pre-roll, post-hold, min/max display, transitions, Ken Burns."""
        scenes = adjust_timing(aligned_scenes)
        scenes = assign_transitions(scenes)
        scenes = assign_ken_burns(scenes)
        return scenes

    # ------------------------------------------------------------------
    # Step 4 — Generate render config
    # ------------------------------------------------------------------

    def generate_render_config(
        self,
        video_id: str,
        audio_path: str,
        scenes: list[dict[str, Any]],
        image_dir: str,
        output_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        """
        Build and optionally persist the render config.

        If *output_dir* is provided the following files are written::

            {output_dir}/
            ├── scene_timing.json     # intermediate debug data
            └── render_config.json    # final config for Remotion
        """
        config = build_render_config(
            video_id=video_id,
            audio_path=audio_path,
            scenes=scenes,
            image_dir=image_dir,
        )

        if output_dir is not None:
            out = Path(output_dir)
            save_scene_timing(scenes, out / "scene_timing.json")
            write_render_config(config, out / "render_config.json")

        return config

    # ------------------------------------------------------------------
    # Convenience — run everything
    # ------------------------------------------------------------------

    def run(
        self,
        audio_path: str,
        scene_list: list[dict[str, Any]],
        video_id: str,
        image_dir: str,
        timing_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        """
        Execute the full pipeline: transcribe -> align -> adjust -> config.

        Args:
            audio_path: Path to the narration audio (.mp3/.wav).
            scene_list: List of scene dicts (must contain ``script_excerpt``).
            video_id: Unique video identifier.
            image_dir: Directory containing generated scene images.
            timing_dir: Optional directory for caching Whisper output
                and writing the render config.

        Returns:
            The render configuration dict.
        """
        # Transcribe
        words = self.transcribe(audio_path, cache_dir=timing_dir)

        # Align
        aligned = self.align(scene_list, words)

        # Adjust timing + transitions + Ken Burns
        timed = self.adjust_timing(aligned)

        # Build render config
        config = self.generate_render_config(
            video_id=video_id,
            audio_path=audio_path,
            scenes=timed,
            image_dir=image_dir,
            output_dir=timing_dir,
        )

        return config


__all__ = [
    "AudioSyncPipeline",
    "WordTimestamp",
    "transcribe",
    "transcribe_api",
    "extract_words",
    "save_whisper_raw",
    "load_whisper_raw",
    "align_scenes_to_timestamps",
    "validate_alignment",
    "adjust_timing",
    "assign_transitions",
    "assign_ken_burns",
    "build_render_config",
    "write_render_config",
    "save_scene_timing",
]
