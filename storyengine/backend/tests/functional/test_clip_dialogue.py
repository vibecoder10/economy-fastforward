"""Tests for clip_dialogue — card↔line matching, prompts, and the real
ffmpeg audio strip. database is stubbed; ffmpeg is required (as in prod).

Run: python3 tests/functional/test_clip_dialogue.py  (from backend dir)
"""

import os
import subprocess
import sys
import tempfile
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.modules.setdefault("database", types.SimpleNamespace(fetch_all=None, fetch_one=None, execute=None))

import asyncio  # noqa: E402
from clip_dialogue import norm, match_lines, speaking_prompt, strip_audio, mux_voice  # noqa: E402

LINES = [
    {"speaker": "Tom", "text": "Mom! Dad! Come here! Come quickly!", "audio_url": "u", "duration": 1.8},
    {"speaker": "Lisa", "text": "It is a baby bird.", "audio_url": "u", "duration": 1.5},
]


def test_matching():
    # Card text carries attribution + punctuation; line words are verbatim inside.
    card = 'Tom is playing in the garden. Tom says: "Mom! Dad! Come here! Come quickly!"'
    m = match_lines(card, LINES)
    assert len(m) == 1 and m[0]["speaker"] == "Tom", m
    # Narration-only card matches nothing
    assert match_lines("He waits for his family.", LINES) == []
    # Case/punct insensitive
    assert norm('"It IS a baby bird!"') == "it is a baby bird"
    assert len(match_lines("Lisa whispers: it is a baby bird", LINES)) == 1
    print("✓ card↔line matching")


def test_prompt():
    p = speaking_prompt([LINES[0]])
    assert "Tom speaks" in p and "Come quickly!" in p and "exactly as shown" in p
    print("✓ speaking prompt")


def _make_clip(td):
    clip = os.path.join(td, "in.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=2",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                    "-c:v", "libx264", "-c:a", "aac", "-shortest", clip], check=True, capture_output=True)
    return open(clip, "rb").read()


def _streams(data):
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        f.write(data)
        path = f.name
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
                          "-of", "csv=p=0", path], capture_output=True, text=True).stdout
    os.unlink(path)
    return sorted(s for s in out.strip().splitlines() if s)


def _make_tone(td):
    tone = os.path.join(td, "tone.mp3")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    "sine=frequency=880:duration=1", tone], check=True, capture_output=True)
    return open(tone, "rb").read()


def test_strip_and_mux():
    with tempfile.TemporaryDirectory() as td:
        clip = _make_clip(td)
        assert _streams(clip) == ["audio", "video"]
        silent = asyncio.run(strip_audio(clip))
        assert _streams(silent) == ["video"], _streams(silent)
        tone = _make_tone(td)
        muxed = asyncio.run(mux_voice(clip, [tone], delay_seconds=0.5))
        assert _streams(muxed) == ["audio", "video"], _streams(muxed)
        muxed2 = asyncio.run(mux_voice(clip, [tone, tone]))  # concat path
        assert _streams(muxed2) == ["audio", "video"]
    print("✓ ffmpeg strip + mux (single delayed + concat)")


if __name__ == "__main__":
    test_matching()
    test_prompt()
    test_strip_and_mux()
    print("\nALL 3 TESTS PASSED")
