"""FIX 3 backstop test: render_stitch._trim_dead_space must cap a no-speech
clip at its assets.duration_seconds target in the fallback (plain-stitch)
render path too — this is the backstop for when the performance-track
assembler (render_perform.py) fails and pipeline_executor falls back to
plain stitch_video. Before this fix a no-speech clip (bounds=None) passed
through _trim_dead_space completely untrimmed, so even the fallback path
could ship a 6s staring shot the coverage plan only wanted for 2s.

No real ffmpeg: _probe_duration/_speech_bounds/_run_subprocess are stubbed —
this proves the cap DECISION and the ffmpeg command built for it, not ffmpeg
itself (mirrors the stubbing convention in tests/test_render_static_speed.py).
"""

import os
import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import render_stitch as rs  # noqa: E402


def _stub_no_speech(monkeypatch, mod, dur: float, run_subprocess=None):
    async def fake_probe_duration(path):
        return dur

    async def fake_speech_bounds(path, d):
        return None  # no speech detected → treated as B-roll/no-speech clip

    monkeypatch.setattr(mod, "_probe_duration", fake_probe_duration)
    monkeypatch.setattr(mod, "_speech_bounds", fake_speech_bounds)
    if run_subprocess is not None:
        monkeypatch.setattr(mod, "_run_subprocess", run_subprocess)


@pytest.mark.asyncio
async def test_no_speech_clip_capped_at_assets_duration_seconds(tmp_path, monkeypatch):
    clip_path = tmp_path / "clip_000.mp4"
    clip_path.write_bytes(b"fake")
    ran = {}

    async def fake_run_subprocess(cmd):
        Path(cmd[-1]).write_bytes(b"trimmed")
        ran["cmd"] = cmd
        return 0, ""

    _stub_no_speech(monkeypatch, rs, dur=6.0, run_subprocess=fake_run_subprocess)

    clips = [{"scene": 1, "image_index": 1, "video_clip_url": "u",
              "video_duration": 6.0, "duration_seconds": 2.5}]
    out = await rs._trim_dead_space([clip_path], tmp_path, None, clips)

    assert len(out) == 1
    assert out[0] != clip_path, "a capped copy must be produced, not the raw 6s clip"
    assert "cmd" in ran, "no-speech clip over its planned duration must be re-encoded"
    cmd = ran["cmd"]
    assert "-t" in cmd and cmd[cmd.index("-t") + 1] == "2.500"


@pytest.mark.asyncio
async def test_no_speech_clip_decimal_duration_seconds_does_not_crash(tmp_path, monkeypatch):
    """assets.duration_seconds is Postgres NUMERIC — asyncpg hands it back as
    decimal.Decimal, same crash family as FIX 1. The cap path must cast it."""
    clip_path = tmp_path / "clip_000.mp4"
    clip_path.write_bytes(b"fake")

    async def fake_run_subprocess(cmd):
        Path(cmd[-1]).write_bytes(b"trimmed")
        return 0, ""

    _stub_no_speech(monkeypatch, rs, dur=6.0, run_subprocess=fake_run_subprocess)

    clips = [{"scene": 1, "image_index": 1, "video_clip_url": "u",
              "video_duration": Decimal("6.0"), "duration_seconds": Decimal("2.5")}]
    out = await rs._trim_dead_space([clip_path], tmp_path, None, clips)
    assert len(out) == 1 and out[0] != clip_path


@pytest.mark.asyncio
async def test_no_speech_clip_within_planned_duration_left_untouched(tmp_path, monkeypatch):
    """A no-speech clip already at (or within _TRIM_MIN_GAIN of) its planned
    duration isn't worth a re-encode — same policy as the existing trim path."""
    clip_path = tmp_path / "clip_000.mp4"
    clip_path.write_bytes(b"fake")

    async def fail_run_subprocess(cmd):
        raise AssertionError("must not re-encode a clip already at its cap")

    _stub_no_speech(monkeypatch, rs, dur=2.5, run_subprocess=fail_run_subprocess)

    clips = [{"scene": 1, "image_index": 1, "video_clip_url": "u",
              "video_duration": 2.5, "duration_seconds": 2.5}]
    out = await rs._trim_dead_space([clip_path], tmp_path, None, clips)
    assert out[0] == clip_path


@pytest.mark.asyncio
async def test_no_speech_clip_with_no_duration_seconds_stays_untrimmed(tmp_path, monkeypatch):
    """Backward compatibility: no assets row info (or no stamped
    duration_seconds) → behaves exactly as before, untouched B-roll."""
    clip_path = tmp_path / "clip_000.mp4"
    clip_path.write_bytes(b"fake")

    async def fail_run_subprocess(cmd):
        raise AssertionError("no cap target — must not attempt to trim")

    _stub_no_speech(monkeypatch, rs, dur=6.0, run_subprocess=fail_run_subprocess)

    clips = [{"scene": 1, "image_index": 1, "video_clip_url": "u", "video_duration": 6.0}]
    out = await rs._trim_dead_space([clip_path], tmp_path, None, clips)
    assert out[0] == clip_path

    # also covers the caller passing no clips list at all (older call sites)
    out2 = await rs._trim_dead_space([clip_path], tmp_path, None, None)
    assert out2[0] == clip_path
