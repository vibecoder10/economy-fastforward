"""Fail-closed validation for encoded video artifacts before external storage."""

from __future__ import annotations

import asyncio
import json
import math
import os
from pathlib import Path
from typing import Any


class EncodedMediaError(RuntimeError):
    pass


async def _kill_and_reap(process: asyncio.subprocess.Process) -> None:
    """Stop a validator subprocess and collect it without an unbounded wait."""
    if process.returncode is None:
        process.kill()
    try:
        await asyncio.wait_for(process.wait(), timeout=10.0)
    except asyncio.TimeoutError:
        # SIGKILL has already stopped ffmpeg/ffprobe.  A pathological asyncio
        # transport must not keep the ARQ job stuck indefinitely during cleanup.
        pass


async def _run(*command: str) -> tuple[int, bytes, bytes]:
    timeout = max(
        30.0,
        min(7200.0, float(os.getenv("ENCODED_MEDIA_VALIDATION_TIMEOUT_SECONDS", "1800"))),
    )
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        await _kill_and_reap(process)
        raise EncodedMediaError(
            f"{command[0]} media validation timed out after {timeout:.0f}s; upload was not started"
        ) from exc
    except asyncio.CancelledError:
        await _kill_and_reap(process)
        raise
    return process.returncode or 0, stdout, stderr


def _positive_duration(value: Any) -> float | None:
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return None
    return duration if math.isfinite(duration) and duration > 0 else None


async def validate_encoded_video(
    path: str | Path,
    *,
    expected_duration: float | None = None,
) -> dict[str, Any]:
    """Require decodable video+audio streams and a credible finite duration.

    The full decode happens exactly once per invocation. Callers should invoke
    this once at each distinct artifact boundary (local render and downloaded
    upload source), because storage transfer can corrupt an otherwise valid file.
    """
    media_path = Path(path)
    if not media_path.is_file() or media_path.stat().st_size <= 0:
        raise EncodedMediaError("Encoded video is missing or empty")

    rc, stdout, stderr = await _run(
        "ffprobe", "-v", "error", "-show_streams", "-show_format",
        "-of", "json", str(media_path),
    )
    if rc != 0:
        raise EncodedMediaError(
            f"ffprobe could not read the encoded video: {stderr.decode('utf-8', 'replace')[-600:]}"
        )
    try:
        probe = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EncodedMediaError("ffprobe returned invalid media metadata") from exc

    streams = probe.get("streams") if isinstance(probe, dict) else None
    streams = streams if isinstance(streams, list) else []
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    if not video_streams:
        raise EncodedMediaError("Encoded output has no video stream")
    if not audio_streams:
        raise EncodedMediaError("Encoded output has no audio stream")

    duration = _positive_duration((probe.get("format") or {}).get("duration"))
    if duration is None:
        durations = [_positive_duration(stream.get("duration")) for stream in streams]
        duration = max((value for value in durations if value is not None), default=None)
    if duration is None:
        raise EncodedMediaError("Encoded output has no finite positive duration")

    expected = _positive_duration(expected_duration)
    if expected is not None:
        tolerance = max(5.0, min(60.0, expected * 0.10))
        if abs(duration - expected) > tolerance:
            raise EncodedMediaError(
                f"Encoded duration {duration:.2f}s differs from timeline {expected:.2f}s "
                f"by more than {tolerance:.2f}s"
            )

    rc, _, stderr = await _run(
        "ffmpeg", "-v", "error", "-xerror", "-i", str(media_path),
        "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-",
    )
    if rc != 0:
        raise EncodedMediaError(
            f"Encoded video failed full audio/video decode: "
            f"{stderr.decode('utf-8', 'replace')[-600:]}"
        )
    return {
        "duration_seconds": duration,
        "video_codec": video_streams[0].get("codec_name"),
        "audio_codec": audio_streams[0].get("codec_name"),
        "size_bytes": media_path.stat().st_size,
    }
