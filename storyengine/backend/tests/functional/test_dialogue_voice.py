"""Functional tests for dialogue_voice.synthesize_video_segments.

No network, no DB: database + storage are stubbed (the module-stub pattern
from tasks/lessons.md). Proves the walk contract — voice routing (narrator vs
cast), resume skip, per-segment jsonb persistence, cancel keeps paid work,
missing-speaker warning falls back to the narrator voice.

Run: python3 tests/functional/test_dialogue_voice.py  (from backend dir)
"""

import asyncio
import json
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# ── Stub database + storage BEFORE importing the module under test ──
_db = types.ModuleType("database")
_storage = types.ModuleType("storage")

STATE = {"scripts": [], "executes": [], "uploads": []}


async def _fetch_all(query, *args):
    if "video_characters" in query:
        return [
            {"name": "Lisa", "voice_name": "voice-lisa"},
            {"name": "Tom", "voice_name": "voice-tom"},
            {"name": "Uncast", "voice_name": None},
        ]
    if "FROM scripts" in query:
        return STATE["scripts"]
    return []


async def _execute(query, *args):
    STATE["executes"].append((query, args))


async def _fetch_one(query, *args):
    # actions.py (imported below, transitively, by the money-safety fix's
    # `from actions import budget_refusal, ...`) needs this name to exist at
    # its own module-import time — never actually called here since
    # budget_refusal itself is monkeypatched to a no-op right below.
    return None


async def _upload_bytes(data, path, content_type=None, tenant_id=None):
    STATE["uploads"].append(path)
    return f"https://drive.example/{path}"


_db.fetch_all = _fetch_all
_db.execute = _execute
_db.fetch_one = _fetch_one
_storage.upload_bytes = _upload_bytes
sys.modules["database"] = _db
sys.modules["storage"] = _storage

from dialogue_voice import synthesize_video_segments, _as_segments, _mp3_duration_seconds  # noqa: E402

# Money-safety fix (C56): synthesize_video_segments now calls
# actions.budget_refusal before every real ElevenLabs call and
# generation_ledger.record_ledger_entry after each one. None of this file's
# tests are about the spend cap (see test_money_safety_gaps_c56.py for that
# — it exercises this exact function's ledger writes and refusals directly),
# so patch both to "never refuse, ledger writes are no-ops" — every existing
# assertion here keeps testing exactly what it tested before this fix.
import actions as _actions_mod  # noqa: E402
import generation_ledger as _ledger_mod  # noqa: E402


async def _fake_budget_refusal(tenant_id, video_id, quote, label="this generation"):
    return None


async def _fake_record_ledger_entry(**kwargs):
    STATE.setdefault("ledger_calls", []).append(kwargs)


_actions_mod.budget_refusal = _fake_budget_refusal
_ledger_mod.record_ledger_entry = _fake_record_ledger_entry


class FakeTTS:
    def __init__(self):
        self.calls = []

    async def generate_voice(self, text, voice_id=None, **settings):
        self.calls.append({"text": text, "voice_id": voice_id, **settings})
        return {"audio_content": b"ID3fakemp3bytes", "content_type": "audio/mpeg"}


def _scene(scene, segments, voice_id="narrator-voice"):
    return {"id": f"script-{scene}", "scene": scene, "voice_id": voice_id,
            "dialogue_segments": json.dumps(segments)}


def test_voice_routing_and_persistence():
    STATE["scripts"] = [_scene(1, [
        {"type": "narration", "text": "Tom is playing in the garden."},
        {"type": "dialogue", "speaker": "Tom", "text": "Mom! Come here!"},
        {"type": "dialogue", "speaker": "Lisa", "text": "It is a baby bird."},
    ])]
    STATE["executes"], STATE["uploads"] = [], []
    tts = FakeTTS()

    result = asyncio.run(synthesize_video_segments("vid", "tenant", tts))

    assert result["segments_voiced"] == 3, result
    assert result["cancelled"] is False
    assert not result["warnings"], result["warnings"]
    # Narration → narrator voice, no performance knobs
    assert tts.calls[0]["voice_id"] == "narrator-voice"
    assert "style" not in tts.calls[0]
    # Dialogue → cast voice + performance knobs
    assert tts.calls[1]["voice_id"] == "voice-tom"
    assert tts.calls[1]["style"] == 0.2 and tts.calls[1]["speed"] == 1.05
    assert tts.calls[2]["voice_id"] == "voice-lisa"
    # Persisted after EVERY segment (3 segments → 3 UPDATEs)
    assert len(STATE["executes"]) == 3
    final = json.loads(STATE["executes"][-1][1][0])
    assert all(s["audio_url"] and s["duration"] > 0 for s in final)
    assert final[1]["voice_name"] == "voice-tom"
    # Upload paths follow {video}/voice/S{n}-seg{i}.mp3
    assert STATE["uploads"][0] == "vid/voice/S1-seg1.mp3"
    print("✓ voice routing + per-segment persistence")


def test_resume_skips_voiced_segments():
    STATE["scripts"] = [_scene(2, [
        {"type": "narration", "text": "Already done.",
         "audio_url": "https://drive.example/old.mp3", "duration": 2.1},
        {"type": "dialogue", "speaker": "Lisa", "text": "Still to do."},
    ])]
    STATE["executes"], STATE["uploads"] = [], []
    tts = FakeTTS()

    result = asyncio.run(synthesize_video_segments("vid", "tenant", tts))

    assert result["segments_voiced"] == 1 and result["segments_skipped"] == 1, result
    assert len(tts.calls) == 1 and tts.calls[0]["voice_id"] == "voice-lisa"
    assert STATE["uploads"] == ["vid/voice/S2-seg2.mp3"]  # index keeps timeline position
    print("✓ resume skips already-voiced segments")


def test_missing_speaker_falls_back_with_warning():
    STATE["scripts"] = [_scene(3, [
        {"type": "dialogue", "speaker": "Dr. May", "text": "The bird needs rest."},
    ])]
    STATE["executes"], STATE["uploads"] = [], []
    tts = FakeTTS()

    result = asyncio.run(synthesize_video_segments("vid", "tenant", tts))

    assert result["segments_voiced"] == 1
    assert len(result["warnings"]) == 1 and "Dr. May" in result["warnings"][0]
    assert tts.calls[0]["voice_id"] == "narrator-voice"
    print("✓ missing cast voice → narrator fallback + warning")


def test_cancel_keeps_paid_work():
    STATE["scripts"] = [_scene(4, [
        {"type": "narration", "text": "First."},
        {"type": "narration", "text": "Second."},
    ])]
    STATE["executes"], STATE["uploads"] = [], []
    tts = FakeTTS()
    flags = iter([False, True])  # allow seg 1, cancel before seg 2

    async def cancel_check():
        return next(flags, True)

    result = asyncio.run(synthesize_video_segments("vid", "tenant", tts, cancel_check=cancel_check))

    assert result["cancelled"] is True
    assert result["segments_voiced"] == 1
    assert len(STATE["executes"]) == 1  # seg 1's work persisted
    print("✓ cancel between segments keeps completed work")


def test_scene_filter():
    STATE["scripts"] = [
        _scene(1, [{"type": "narration", "text": "Scene one."}]),
        _scene(2, [{"type": "narration", "text": "Scene two."}]),
    ]
    STATE["executes"], STATE["uploads"] = [], []
    tts = FakeTTS()

    result = asyncio.run(synthesize_video_segments("vid", "tenant", tts, scene_filter=2))

    assert result["segments_voiced"] == 1
    assert STATE["uploads"] == ["vid/voice/S2-seg1.mp3"]
    print("✓ scene_filter targets one scene")


def test_helpers():
    assert _as_segments(None) is None
    assert _as_segments("not json") is None
    assert _as_segments("[]") is None
    assert _as_segments('[{"type":"narration","text":"x"}]')[0]["text"] == "x"
    # Fallback estimate when bytes aren't a real MP3
    assert _mp3_duration_seconds(b"junk", "five words of test text") == 2.0
    print("✓ helpers (jsonb parsing, duration fallback)")


if __name__ == "__main__":
    test_voice_routing_and_persistence()
    test_resume_skips_voiced_segments()
    test_missing_speaker_falls_back_with_warning()
    test_cancel_keeps_paid_work()
    test_scene_filter()
    test_helpers()
    print("\nALL 6 TESTS PASSED")
