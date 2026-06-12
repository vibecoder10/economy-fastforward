"""Tests for clip_dialogue — card↔line matching and the real ffmpeg mux.

Pure functions tested directly; mux/strip tested against a generated test
video + tone (ffmpeg required, as in prod). database is stubbed.

Run: python3 tests/functional/test_clip_dialogue.py  (from backend dir)
"""

import os
import subprocess
import sys
import tempfile
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.modules.setdefault("database", types.SimpleNamespace(fetch_all=None))

import asyncio  # noqa: E402
from clip_dialogue import norm, match_lines, speaking_prompt, mux_voice, strip_audio  # noqa: E402

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
    p2 = speaking_prompt(LINES)
    assert "Then Lisa speaks" in p2
    print("✓ speaking prompt")


def _make_media(td):
    clip = os.path.join(td, "in.mp4")
    tone = os.path.join(td, "tone.mp3")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=2",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                    "-c:v", "libx264", "-c:a", "aac", "-shortest", clip], check=True, capture_output=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=880:duration=1",
                    tone], check=True, capture_output=True)
    return open(clip, "rb").read(), open(tone, "rb").read()


def _streams(data):
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        f.write(data)
        path = f.name
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
                          "-of", "csv=p=0", path], capture_output=True, text=True).stdout
    os.unlink(path)
    return sorted(s for s in out.strip().splitlines() if s)


def test_mux_and_strip():
    with tempfile.TemporaryDirectory() as td:
        clip, tone = _make_media(td)
        muxed = asyncio.run(mux_voice(clip, [tone]))
        assert _streams(muxed) == ["audio", "video"], _streams(muxed)
        muxed2 = asyncio.run(mux_voice(clip, [tone, tone]))  # concat path
        assert _streams(muxed2) == ["audio", "video"]
        silent = asyncio.run(strip_audio(clip))
        assert _streams(silent) == ["video"], _streams(silent)
    print("✓ ffmpeg mux (single + concat) and strip")


if __name__ == "__main__":
    test_matching()
    test_prompt()
    test_mux_and_strip()
    print("\nALL 3 TESTS PASSED")
