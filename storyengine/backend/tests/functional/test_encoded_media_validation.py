"""Real ffmpeg/ffprobe acceptance checks for provider-bound MP4 files."""

from __future__ import annotations

import asyncio
from pathlib import Path
import shutil
import subprocess

import pytest

import encoded_media
from encoded_media import EncodedMediaError, validate_encoded_video


pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="ffmpeg and ffprobe are required",
)


def _make_mp4(path: Path, *, audio: bool = True, seconds: float = 1.0) -> None:
    command = [
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", f"color=c=blue:s=160x90:d={seconds}",
    ]
    if audio:
        command += [
            "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={seconds}",
            "-shortest", "-c:a", "aac",
        ]
    command += ["-c:v", "mpeg4", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(command, check=True, capture_output=True)


@pytest.mark.asyncio
async def test_valid_video_with_audio_fully_decodes(tmp_path):
    path = tmp_path / "valid.mp4"
    _make_mp4(path)

    result = await validate_encoded_video(path, expected_duration=1.0)

    assert result["duration_seconds"] > 0
    assert result["video_codec"]
    assert result["audio_codec"]
    assert result["size_bytes"] > 0


@pytest.mark.asyncio
async def test_empty_and_corrupt_outputs_are_rejected(tmp_path):
    empty = tmp_path / "empty.mp4"
    empty.touch()
    corrupt = tmp_path / "corrupt.mp4"
    corrupt.write_bytes(b"not an mp4" * 20)

    with pytest.raises(EncodedMediaError, match="missing or empty"):
        await validate_encoded_video(empty)
    with pytest.raises(EncodedMediaError, match="ffprobe could not read"):
        await validate_encoded_video(corrupt)


@pytest.mark.asyncio
async def test_video_without_audio_is_rejected(tmp_path):
    path = tmp_path / "silent.mp4"
    _make_mp4(path, audio=False)

    with pytest.raises(EncodedMediaError, match="no audio stream"):
        await validate_encoded_video(path)


@pytest.mark.asyncio
async def test_implausible_timeline_duration_is_rejected(tmp_path):
    path = tmp_path / "short.mp4"
    _make_mp4(path, seconds=1.0)

    with pytest.raises(EncodedMediaError, match="differs from timeline"):
        await validate_encoded_video(path, expected_duration=20.0)


@pytest.mark.asyncio
async def test_timeout_kills_and_reaps_validator_process(monkeypatch, tmp_path):
    class HungProcess:
        def __init__(self):
            self.returncode = None
            self.killed = False
            self.communicate_calls = 0
            self.wait_calls = 0

        def kill(self):
            self.killed = True
            self.returncode = -9

        async def communicate(self):
            self.communicate_calls += 1
            return b"", b""

        async def wait(self):
            self.wait_calls += 1
            return self.returncode

    process = HungProcess()

    async def create_process(*args, **kwargs):
        return process

    wait_calls = 0

    async def fake_wait_for(awaitable, *, timeout):
        nonlocal wait_calls
        wait_calls += 1
        if wait_calls == 1:
            awaitable.close()
            raise asyncio.TimeoutError
        return await awaitable

    monkeypatch.setattr(encoded_media.asyncio, "create_subprocess_exec", create_process)
    monkeypatch.setattr(encoded_media.asyncio, "wait_for", fake_wait_for)
    monkeypatch.setenv("ENCODED_MEDIA_VALIDATION_TIMEOUT_SECONDS", "30")

    with pytest.raises(EncodedMediaError, match="upload was not started"):
        await encoded_media._run("ffmpeg", "-i", str(tmp_path / "hung.mp4"))

    assert process.killed is True
    assert process.communicate_calls == 0
    assert process.wait_calls == 1
