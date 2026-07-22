"""Functional tests for U3 — voice-less pipeline flow for dialogue-format
videos (PocoAPoco shape).

Ryan's intent: for majority-performed-dialogue videos, a clip already arrives
voice-locked (Grok performs the line, ElevenLabs speech-to-speech re-voices in
the pinned cast voice — carries_own_line, migration 114), because clip
generation auto-chains the per-segment TTS/STS render clock during Animate
(pipeline_executor.py's run_dialogue_voice auto-chain) whenever a scene is
unvoiced. So the separate Script&Voice "Generate Voice" step is redundant
noise for that shape — but ONLY that shape. A narrated documentary (DvsU) that
merely quotes a line or two must never trip the same auto-skip; its render
clock genuinely needs the voice-over stage.

Covers two write paths, both auto-skip-voice hooks:
  1. dialogue_intelligence.tag_video_dialogue — fires when the just-tagged
     script turns out MAJORITY performed dialogue by word share
     (DIALOGUE_MAJORITY_THRESHOLD). Guarded: fail-safe on no evidence
     (empty/missing segments keeps voice), never for static_docu, only
     flips skip_voice false->true, never overrides an explicit 'voice' in
     pipeline_stages.
  2. routes/videos.py update_video (PATCH /api/videos/{id}) — a creator who
     explicitly picks dialogue_audio='grok_native' for a character-dialogue
     video is opting out of the voice-over stage just as explicitly. Same
     false->true-only and static_docu guards, plus: never overrides an
     explicit skip_voice in the SAME request, and only applies to
     dialogue_mode='character_dialogue' videos.

No network, no live DB — fetch_one/fetch_all/execute are monkeypatched at the
module-attribute level (same convention as tests/test_c46d_trust_boundaries.py
and tests/functional/test_c14_model_override_and_render_style.py).

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_u3_dialogue_voiceless_flow.py -q
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth import get_tenant_id
import dialogue_intelligence
import routes.videos as videos_route  # noqa: E402

TENANT = "00000000-0000-0000-0000-000000000000"
VIDEO_ID = "video-u3-1"


# ---------------------------------------------------------------------------
# 1. dialogue_intelligence.tag_video_dialogue — the majority-dialogue hook
# ---------------------------------------------------------------------------

def _video_row(**overrides):
    row = {
        "id": VIDEO_ID,
        "script": "some script text",
        "dialogue_audio": None,
        "render_mode": None,
        "skip_voice": False,
        "skip_voice_source": None,
        "pipeline_stages": None,
    }
    row.update(overrides)
    return row


def _wire_tag(monkeypatch, video, scenes, segments_by_scene, *, cast=None,
              detected_mode="character_dialogue", tenant_static_format=False):
    """Wires fetch_one/fetch_all/execute + detect_dialogue_mode/segment_scene
    for tag_video_dialogue. `segments_by_scene` maps scene id -> segments list
    returned for that scene (or a single list reused for every scene).
    static_docu.static_mode_for_tenant is stubbed to `tenant_static_format`
    (default False) so the guard's own real implementation — a live DB query
    — never runs unmocked in these DB-free tests."""
    writes = []

    import static_docu

    async def fake_static_mode(_tenant_id):
        return tenant_static_format

    monkeypatch.setattr(static_docu, "static_mode_for_tenant", fake_static_mode)

    async def fake_fetch_one(query, *args):
        if "FROM videos" in query:
            return dict(video)
        return None

    async def fake_fetch_all(query, *args):
        if "FROM video_characters" in query:
            return cast or []
        if "FROM scripts" in query:
            return scenes
        return []

    async def fake_execute(query, *args):
        writes.append((query, args))
        return "UPDATE 1"

    async def fake_detect_mode(script_text, tenant_id):
        return detected_mode

    async def fake_segment_scene(text, cast_names, tenant_id):
        if isinstance(segments_by_scene, dict):
            return segments_by_scene[text]
        return segments_by_scene

    monkeypatch.setattr(dialogue_intelligence, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(dialogue_intelligence, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(dialogue_intelligence, "execute", fake_execute)
    monkeypatch.setattr(dialogue_intelligence, "detect_dialogue_mode", fake_detect_mode)
    monkeypatch.setattr(dialogue_intelligence, "segment_scene", fake_segment_scene)
    return writes


def _skip_voice_writes(writes):
    return [w for w in writes if "SET skip_voice = true" in w[0]]


def test_pocoapoco_shape_100pct_dialogue_auto_skips(monkeypatch):
    """(a) A script that's ALL performed dialogue (PocoAPoco shape) crosses
    the majority threshold and auto-sets skip_voice=true."""
    scenes = [{"id": "sc-1", "scene": 1, "scene_text": "scene one"}]
    segments = [
        {"type": "dialogue", "speaker": "Marco", "text": "Espera espera por favor amigo"},
        {"type": "dialogue", "speaker": "Sofia", "text": "Por que siempre llegas tarde hoy"},
    ]
    writes = _wire_tag(monkeypatch, _video_row(), scenes, segments,
                        cast=[{"name": "Marco"}, {"name": "Sofia"}])

    result = asyncio.run(dialogue_intelligence.tag_video_dialogue(VIDEO_ID, TENANT))

    assert result["dialogue_mode"] == "character_dialogue"
    assert result["dialogue_share"] == 1.0
    assert result["voice_auto_skipped"] is True
    skip_writes = _skip_voice_writes(writes)
    assert len(skip_writes) == 1
    assert skip_writes[0][1] == (VIDEO_ID,)


def test_dvsu_shape_narrator_with_two_quoted_lines_never_auto_skips(monkeypatch):
    """(b) A narrated documentary that merely QUOTES a couple of lines (DvsU
    shape) — even though the tagging pass still calls it
    'character_dialogue' for those quoted lines — must stay well under the
    majority threshold and never auto-skip. Two short dialogue quotes buried
    in a long narration block."""
    scenes = [{"id": "sc-1", "scene": 1, "scene_text": "scene one"}]
    narration_sentence = " ".join(["word"] * 20)  # 20-word narration sentences
    segments = (
        [{"type": "narration", "text": narration_sentence} for _ in range(9)]
        + [
            {"type": "dialogue", "speaker": "Historian", "text": "It changed everything"},
            {"type": "dialogue", "speaker": "Engineer", "text": "We had no choice"},
        ]
    )
    writes = _wire_tag(monkeypatch, _video_row(), scenes, segments,
                        cast=[{"name": "Historian"}, {"name": "Engineer"}])

    result = asyncio.run(dialogue_intelligence.tag_video_dialogue(VIDEO_ID, TENANT))

    assert result["dialogue_mode"] == "character_dialogue"
    assert result["dialogue_share"] < dialogue_intelligence.DIALOGUE_MAJORITY_THRESHOLD
    assert "voice_auto_skipped" not in result
    assert _skip_voice_writes(writes) == []


def test_empty_segments_fail_safe_never_auto_skips(monkeypatch):
    """(c) Nothing tagged (or every scene came back empty) — no evidence of
    majority dialogue, so the fail-safe keeps voice rather than guessing."""
    scenes = [{"id": "sc-1", "scene": 1, "scene_text": "scene one"}]
    writes = _wire_tag(monkeypatch, _video_row(), scenes, [])

    result = asyncio.run(dialogue_intelligence.tag_video_dialogue(VIDEO_ID, TENANT))

    assert result["dialogue_mode"] == "character_dialogue"
    assert "dialogue_share" not in result
    assert "voice_auto_skipped" not in result
    assert _skip_voice_writes(writes) == []


def test_narration_only_mode_short_circuits_before_any_share_math(monkeypatch):
    """Non-dialogue videos are untouched — same early return as before U3."""
    scenes = [{"id": "sc-1", "scene": 1, "scene_text": "scene one"}]
    writes = _wire_tag(monkeypatch, _video_row(), scenes, [], detected_mode="narration_only")

    result = asyncio.run(dialogue_intelligence.tag_video_dialogue(VIDEO_ID, TENANT))

    assert result == {"dialogue_mode": "narration_only", "scenes_tagged": 0}
    assert _skip_voice_writes(writes) == []


def test_static_docu_render_mode_never_auto_skips_even_at_100pct(monkeypatch):
    """Guard: render_mode='static_docu' — voice IS the narration there —
    blocks the auto-skip even for a 100%-dialogue script."""
    scenes = [{"id": "sc-1", "scene": 1, "scene_text": "scene one"}]
    segments = [{"type": "dialogue", "speaker": "A", "text": "all dialogue all the time here"}]
    writes = _wire_tag(monkeypatch, _video_row(render_mode="static_docu"), scenes, segments,
                        cast=[{"name": "A"}])

    result = asyncio.run(dialogue_intelligence.tag_video_dialogue(VIDEO_ID, TENANT))

    assert result["dialogue_share"] == 1.0
    assert "voice_auto_skipped" not in result
    assert _skip_voice_writes(writes) == []


def test_tenant_static_format_never_auto_skips(monkeypatch):
    """Guard: even when the VIDEO row isn't stamped static_docu, a tenant
    whose channel format is a static documentary must block the auto-skip
    (static_mode_for_tenant check)."""
    scenes = [{"id": "sc-1", "scene": 1, "scene_text": "scene one"}]
    segments = [{"type": "dialogue", "speaker": "A", "text": "all dialogue all the time here"}]
    writes = _wire_tag(monkeypatch, _video_row(), scenes, segments, cast=[{"name": "A"}],
                        tenant_static_format=True)

    result = asyncio.run(dialogue_intelligence.tag_video_dialogue(VIDEO_ID, TENANT))

    assert "voice_auto_skipped" not in result
    assert _skip_voice_writes(writes) == []


def test_already_skipped_never_double_writes_true_to_false_safe(monkeypatch):
    """Guard: skip_voice already true — nothing to flip, and definitely no
    path that could ever flip it back to false."""
    scenes = [{"id": "sc-1", "scene": 1, "scene_text": "scene one"}]
    segments = [{"type": "dialogue", "speaker": "A", "text": "all dialogue all the time here"}]
    writes = _wire_tag(monkeypatch, _video_row(skip_voice=True), scenes, segments,
                        cast=[{"name": "A"}])

    result = asyncio.run(dialogue_intelligence.tag_video_dialogue(VIDEO_ID, TENANT))

    assert "voice_auto_skipped" not in result
    assert _skip_voice_writes(writes) == []


def test_explicit_pipeline_stages_voice_blocks_auto_skip(monkeypatch):
    """Guard: a creator who explicitly kept 'voice' in this video's
    pipeline_stages plan is not overridden, even at 100% dialogue share."""
    scenes = [{"id": "sc-1", "scene": 1, "scene_text": "scene one"}]
    segments = [{"type": "dialogue", "speaker": "A", "text": "all dialogue all the time here"}]
    writes = _wire_tag(
        monkeypatch,
        _video_row(pipeline_stages=["script", "voice", "images", "video", "render"]),
        scenes, segments, cast=[{"name": "A"}],
    )

    result = asyncio.run(dialogue_intelligence.tag_video_dialogue(VIDEO_ID, TENANT))

    assert "voice_auto_skipped" not in result
    assert _skip_voice_writes(writes) == []


# ---------------------------------------------------------------------------
# 1b. P5 BLOCKER fix — bidirectional auto-skip (skip_voice_source, migration 116)
# ---------------------------------------------------------------------------

def _revert_writes(writes):
    return [w for w in writes if "SET skip_voice = false" in w[0]]


def test_THE_REGRESSION_reclassified_narration_reverts_auto_skip(monkeypatch):
    """THE blocker scenario from the sweep: a video tagged character_dialogue
    at >=0.8 dialogue share auto-skips voice (source='auto'). The creator
    regenerates the script into something narration-heavy; re-tagging now
    concludes narration_only. Before this fix skip_voice stayed stuck true —
    voice never ran, the character_dialogue-gated Animate auto-chain never
    fired, and render hard-failed "Missing audio: Scene N.mp3" with no
    self-serve recovery (voiceSkipped hides the frontend's voice controls).
    This proves the auto-detector can undo what it itself set."""
    scenes = [{"id": "sc-1", "scene": 1, "scene_text": "scene one"}]
    # Video already auto-skipped by a PRIOR tagging pass (source='auto').
    video = _video_row(skip_voice=True, skip_voice_source="auto")
    writes = _wire_tag(
        monkeypatch, video, scenes, [], detected_mode="narration_only",
    )

    result = asyncio.run(dialogue_intelligence.tag_video_dialogue(VIDEO_ID, TENANT))

    assert result["dialogue_mode"] == "narration_only"
    assert result["voice_auto_restored"] is True
    reverts = _revert_writes(writes)
    assert len(reverts) == 1
    assert reverts[0][1] == (VIDEO_ID,)


def test_dialogue_share_dropping_below_threshold_also_reverts_auto_skip(monkeypatch):
    """Same bidirectional fix, but the mode is STILL character_dialogue —
    only the dialogue SHARE dropped back under the majority threshold (e.g.
    a rewrite added a lot of new narration around the same dialogue lines).
    Must revert just like the mode-flip case."""
    scenes = [{"id": "sc-1", "scene": 1, "scene_text": "scene one"}]
    narration_sentence = " ".join(["word"] * 20)
    segments = (
        [{"type": "narration", "text": narration_sentence} for _ in range(9)]
        + [{"type": "dialogue", "speaker": "A", "text": "one short line"}]
    )
    video = _video_row(skip_voice=True, skip_voice_source="auto")
    writes = _wire_tag(monkeypatch, video, scenes, segments, cast=[{"name": "A"}])

    result = asyncio.run(dialogue_intelligence.tag_video_dialogue(VIDEO_ID, TENANT))

    assert result["dialogue_mode"] == "character_dialogue"
    assert result["dialogue_share"] < dialogue_intelligence.DIALOGUE_MAJORITY_THRESHOLD
    assert result["voice_auto_restored"] is True
    assert len(_revert_writes(writes)) == 1


def test_manual_skip_survives_reclassification(monkeypatch):
    """A creator's own explicit skip (skip_voice_source='manual' — the
    GuidedNextStep button, or a grok_native PATCH) must NEVER be auto-flipped
    back, even when this same pass concludes the video no longer qualifies."""
    scenes = [{"id": "sc-1", "scene": 1, "scene_text": "scene one"}]
    video = _video_row(skip_voice=True, skip_voice_source="manual")
    writes = _wire_tag(monkeypatch, video, scenes, [], detected_mode="narration_only")

    result = asyncio.run(dialogue_intelligence.tag_video_dialogue(VIDEO_ID, TENANT))

    assert "voice_auto_restored" not in result
    assert _revert_writes(writes) == []


def test_legacy_null_source_never_auto_flipped(monkeypatch):
    """A pre-migration-116 row has skip_voice=true with no provenance
    (skip_voice_source is NULL) — treated the same as 'manual', never
    auto-reverted, since we have no evidence the detector set it."""
    scenes = [{"id": "sc-1", "scene": 1, "scene_text": "scene one"}]
    video = _video_row(skip_voice=True, skip_voice_source=None)
    writes = _wire_tag(monkeypatch, video, scenes, [], detected_mode="narration_only")

    result = asyncio.run(dialogue_intelligence.tag_video_dialogue(VIDEO_ID, TENANT))

    assert "voice_auto_restored" not in result
    assert _revert_writes(writes) == []


def test_no_revert_when_skip_voice_already_false(monkeypatch):
    """Nothing to revert when skip_voice was never set — a plain
    narration-only (or below-threshold) video must not generate a spurious
    revert write."""
    scenes = [{"id": "sc-1", "scene": 1, "scene_text": "scene one"}]
    video = _video_row(skip_voice=False, skip_voice_source=None)
    writes = _wire_tag(monkeypatch, video, scenes, [], detected_mode="narration_only")

    result = asyncio.run(dialogue_intelligence.tag_video_dialogue(VIDEO_ID, TENANT))

    assert "voice_auto_restored" not in result
    assert _revert_writes(writes) == []


def test_forward_auto_skip_stamps_source_auto(monkeypatch):
    """The forward-setting write (skip_voice false->true) now also stamps
    skip_voice_source='auto' in the same UPDATE, so a later pass knows it's
    eligible to revert."""
    scenes = [{"id": "sc-1", "scene": 1, "scene_text": "scene one"}]
    segments = [{"type": "dialogue", "speaker": "A", "text": "all dialogue all the time here"}]
    writes = _wire_tag(monkeypatch, _video_row(), scenes, segments, cast=[{"name": "A"}])

    result = asyncio.run(dialogue_intelligence.tag_video_dialogue(VIDEO_ID, TENANT))

    assert result["voice_auto_skipped"] is True
    skip_writes = _skip_voice_writes(writes)
    assert len(skip_writes) == 1
    assert "skip_voice_source = 'auto'" in skip_writes[0][0]


# ---------------------------------------------------------------------------
# 2. PATCH /api/videos/{id} — dialogue_audio='grok_native' hook
# ---------------------------------------------------------------------------

def _videos_client() -> TestClient:
    app = FastAPI()
    app.include_router(videos_route.router)
    app.dependency_overrides[get_tenant_id] = lambda: TENANT
    return TestClient(app)


def test_patch_grok_native_sets_skip_voice_true(monkeypatch):
    async def fake_fetch_one(query, *args):
        return {"id": VIDEO_ID, "dialogue_mode": "character_dialogue",
                "render_mode": None, "skip_voice": False}

    writes = []

    async def fake_execute(query, *args):
        writes.append((query, args))
        return "UPDATE 1"

    monkeypatch.setattr(videos_route, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(videos_route, "execute", fake_execute)
    client = _videos_client()
    resp = client.patch(f"/api/videos/{VIDEO_ID}", json={"dialogue_audio": "grok_native"})
    assert resp.status_code == 200, resp.text
    query, params = writes[0]
    assert "dialogue_audio" in query and "skip_voice" in query
    # column order in `updates` follows dict insertion: dialogue_audio then skip_voice
    assert params[0] == "grok_native"
    assert params[1] is True


def test_patch_grok_native_never_flips_true_back_to_false(monkeypatch):
    """Guard: skip_voice already true stays true — the hook only ever adds a
    true write, never removes or overrides an existing true."""
    async def fake_fetch_one(query, *args):
        return {"id": VIDEO_ID, "dialogue_mode": "character_dialogue",
                "render_mode": None, "skip_voice": True}

    writes = []

    async def fake_execute(query, *args):
        writes.append((query, args))
        return "UPDATE 1"

    monkeypatch.setattr(videos_route, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(videos_route, "execute", fake_execute)
    client = _videos_client()
    resp = client.patch(f"/api/videos/{VIDEO_ID}", json={"dialogue_audio": "grok_native"})
    assert resp.status_code == 200, resp.text
    query, params = writes[0]
    # Only dialogue_audio was in the request body — the hook must not add a
    # redundant/duplicate skip_voice column when it's already true.
    assert "skip_voice" not in query
    assert params == ("grok_native", VIDEO_ID, TENANT)


def test_patch_grok_native_respects_explicit_skip_voice_in_same_request(monkeypatch):
    """A caller who explicitly sends skip_voice=false alongside
    dialogue_audio='grok_native' in the SAME request wins — the hook only
    fills in skip_voice when the caller didn't specify it."""
    async def fake_fetch_one(query, *args):
        return {"id": VIDEO_ID, "dialogue_mode": "character_dialogue",
                "render_mode": None, "skip_voice": False}

    writes = []

    async def fake_execute(query, *args):
        writes.append((query, args))
        return "UPDATE 1"

    monkeypatch.setattr(videos_route, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(videos_route, "execute", fake_execute)
    client = _videos_client()
    resp = client.patch(
        f"/api/videos/{VIDEO_ID}",
        json={"dialogue_audio": "grok_native", "skip_voice": False},
    )
    assert resp.status_code == 200, resp.text
    query, params = writes[0]
    assert params[0] == "grok_native"
    assert params[1] is False  # the caller's explicit choice, untouched


def test_patch_grok_native_static_docu_never_auto_skips(monkeypatch):
    async def fake_fetch_one(query, *args):
        return {"id": VIDEO_ID, "dialogue_mode": "character_dialogue",
                "render_mode": "static_docu", "skip_voice": False}

    writes = []

    async def fake_execute(query, *args):
        writes.append((query, args))
        return "UPDATE 1"

    monkeypatch.setattr(videos_route, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(videos_route, "execute", fake_execute)
    client = _videos_client()
    resp = client.patch(f"/api/videos/{VIDEO_ID}", json={"dialogue_audio": "grok_native"})
    assert resp.status_code == 200, resp.text
    query, params = writes[0]
    assert "skip_voice" not in query


def test_patch_grok_native_non_dialogue_video_never_auto_skips(monkeypatch):
    """A video that isn't tagged character_dialogue at all (dialogue_audio is
    otherwise meaningless there) never gets the auto-skip write."""
    async def fake_fetch_one(query, *args):
        return {"id": VIDEO_ID, "dialogue_mode": None,
                "render_mode": None, "skip_voice": False}

    writes = []

    async def fake_execute(query, *args):
        writes.append((query, args))
        return "UPDATE 1"

    monkeypatch.setattr(videos_route, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(videos_route, "execute", fake_execute)
    client = _videos_client()
    resp = client.patch(f"/api/videos/{VIDEO_ID}", json={"dialogue_audio": "grok_native"})
    assert resp.status_code == 200, resp.text
    query, params = writes[0]
    assert "skip_voice" not in query


# ---------------------------------------------------------------------------
# 2b. P5 fix — PATCH stamps skip_voice_source='manual' (never auto-reverted)
# ---------------------------------------------------------------------------

def test_patch_grok_native_stamps_skip_voice_source_manual(monkeypatch):
    """The grok_native auto-fill (a creator's explicit dialogue_audio choice,
    not the dialogue detector) must stamp skip_voice_source='manual' in the
    SAME write, so dialogue_intelligence.tag_video_dialogue's bidirectional
    auto-revert never touches it later."""
    async def fake_fetch_one(query, *args):
        return {"id": VIDEO_ID, "dialogue_mode": "character_dialogue",
                "render_mode": None, "skip_voice": False}

    writes = []

    async def fake_execute(query, *args):
        writes.append((query, args))
        return "UPDATE 1"

    monkeypatch.setattr(videos_route, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(videos_route, "execute", fake_execute)
    client = _videos_client()
    resp = client.patch(f"/api/videos/{VIDEO_ID}", json={"dialogue_audio": "grok_native"})
    assert resp.status_code == 200, resp.text
    query, params = writes[0]
    assert "skip_voice_source" in query
    # column order in `updates`: dialogue_audio, skip_voice, then the
    # server-stamped skip_voice_source appended after the body loop.
    assert params[0] == "grok_native"
    assert params[1] is True
    assert params[2] == "manual"


def test_patch_explicit_skip_voice_stamps_manual(monkeypatch):
    """GuidedNextStep's skip button sends {skip_voice: true} directly through
    this generic PATCH path — that's exactly as much a creator action as the
    grok_native auto-fill, so it must be stamped 'manual' too."""
    async def fake_fetch_one(query, *args):
        return {"id": VIDEO_ID, "dialogue_mode": None,
                "render_mode": None, "skip_voice": False}

    writes = []

    async def fake_execute(query, *args):
        writes.append((query, args))
        return "UPDATE 1"

    monkeypatch.setattr(videos_route, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(videos_route, "execute", fake_execute)
    client = _videos_client()
    resp = client.patch(f"/api/videos/{VIDEO_ID}", json={"skip_voice": True})
    assert resp.status_code == 200, resp.text
    query, params = writes[0]
    assert "skip_voice_source" in query
    assert params[0] is True  # skip_voice
    assert params[1] == "manual"


def test_patch_grok_native_never_flips_true_back_to_false_no_source_stamp(monkeypatch):
    """When skip_voice was already true and the request only carries
    dialogue_audio (no explicit skip_voice, no auto-fill trigger since it's
    already true), no skip_voice_source write happens either — nothing about
    skip_voice changed in this request."""
    async def fake_fetch_one(query, *args):
        return {"id": VIDEO_ID, "dialogue_mode": "character_dialogue",
                "render_mode": None, "skip_voice": True}

    writes = []

    async def fake_execute(query, *args):
        writes.append((query, args))
        return "UPDATE 1"

    monkeypatch.setattr(videos_route, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(videos_route, "execute", fake_execute)
    client = _videos_client()
    resp = client.patch(f"/api/videos/{VIDEO_ID}", json={"dialogue_audio": "grok_native"})
    assert resp.status_code == 200, resp.text
    query, params = writes[0]
    assert "skip_voice_source" not in query


if __name__ == "__main__":
    import inspect
    mod = sys.modules[__name__]
    test_fns = [obj for name, obj in vars(mod).items()
                if name.startswith("test_") and inspect.isfunction(obj)]
    print(f"{len(test_fns)} test functions found — run via pytest for monkeypatch support")
