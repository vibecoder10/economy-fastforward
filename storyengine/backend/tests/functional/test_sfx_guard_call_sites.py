"""Tests for the SFX render-path guard at its two remaining wired call
sites (the auto-advance path and the pure helper itself are covered in
tests/test_sfx_guard_auto_advance.py and tests/test_render_path_plays_sfx.py):

  1. routes/pipeline.py's `_require_render_path_plays_sfx` — the REST-endpoint
     defense-in-depth gate for POST /sound-prompts/{id} and
     POST /sound-effects/{id}. Both endpoints call `_require_stage_enabled`
     THEN this — it must raise a 400 naming the render path and reason when
     blocked, and be a complete no-op (no exception) when SFX will play.
  2. actions.py's `blocked_reason("sound", summary)` — the money gate three
     independent doors already converge on (routes/mcp.py's `_call_verb`,
     routes/chat.py's classifier dispatch, agent_brain.py's tool-state text).
     Adding a "sound" branch here is a single-file change that closes all
     three at once; this pins that the branch actually fires and reads
     `video_summary()`'s `plays_sfx`/`sfx_blocked_reason` keys, never
     re-deriving the condition.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_sfx_guard_call_sites.py -q
"""
import os
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import routes.pipeline as pipeline_route  # noqa: E402
import actions  # noqa: E402


# =============================================================================
# 1. routes/pipeline.py::_require_render_path_plays_sfx
# =============================================================================

def test_require_render_path_plays_sfx_raises_400_for_custom_film_video():
    video = {"custom_film_plan_id": "plan-1", "render_mode": None,
             "dialogue_audio": None, "dialogue_mode": None}
    with pytest.raises(HTTPException) as exc_info:
        pipeline_route._require_render_path_plays_sfx(video)
    assert exc_info.value.status_code == 400
    assert "Custom Film" in exc_info.value.detail


def test_require_render_path_plays_sfx_raises_400_for_static_docu_video():
    video = {"custom_film_plan_id": None, "render_mode": "static_docu",
             "dialogue_audio": None, "dialogue_mode": None}
    with pytest.raises(HTTPException) as exc_info:
        pipeline_route._require_render_path_plays_sfx(video)
    assert exc_info.value.status_code == 400
    assert "static-documentary" in exc_info.value.detail


def test_require_render_path_plays_sfx_raises_400_for_grok_native_video():
    video = {"custom_film_plan_id": None, "render_mode": None,
             "dialogue_audio": "grok_native", "dialogue_mode": None}
    with pytest.raises(HTTPException):
        pipeline_route._require_render_path_plays_sfx(video)


def test_require_render_path_plays_sfx_raises_400_for_character_dialogue_video():
    video = {"custom_film_plan_id": None, "render_mode": None,
             "dialogue_audio": None, "dialogue_mode": "character_dialogue"}
    with pytest.raises(HTTPException):
        pipeline_route._require_render_path_plays_sfx(video)


def test_require_render_path_plays_sfx_allows_legacy_fallback_video():
    """No exception — the historical default (44/71 prod videos) must never
    be blocked by this guard."""
    video = {"custom_film_plan_id": None, "render_mode": None,
             "dialogue_audio": None, "dialogue_mode": None}
    pipeline_route._require_render_path_plays_sfx(video)  # must not raise


def test_require_render_path_plays_sfx_allows_narration_only_video():
    """Mirrors the real prod video (146242df-cbe0-4a25-9a78-e11bfa22526b)
    found stuck at ready_for_sound_design — narration_only is NOT
    character_dialogue."""
    video = {"custom_film_plan_id": None, "render_mode": None,
             "dialogue_audio": None, "dialogue_mode": "narration_only"}
    pipeline_route._require_render_path_plays_sfx(video)  # must not raise


# =============================================================================
# 2. actions.py::blocked_reason("sound", summary)
# =============================================================================

def _summary(plays_sfx: bool, sfx_blocked_reason=None, **extra) -> dict:
    row = {
        "scenes": 5, "pics": 20, "clips": 10, "cast": 2, "status": "ready_for_sound_design",
        "plays_sfx": plays_sfx, "sfx_blocked_reason": sfx_blocked_reason,
    }
    row.update(extra)
    return row


def test_blocked_reason_sound_blocked_when_plays_sfx_false():
    summary = _summary(plays_sfx=False, sfx_blocked_reason="this video is a static-documentary render.")
    reason = actions.blocked_reason("sound", summary)
    assert reason is not None
    assert "static-documentary" in reason


def test_blocked_reason_sound_blocked_falls_back_to_generic_text_when_no_reason_given():
    summary = _summary(plays_sfx=False, sfx_blocked_reason=None)
    reason = actions.blocked_reason("sound", summary)
    assert reason is not None
    assert "drops sound effects" in reason


def test_blocked_reason_sound_allowed_when_plays_sfx_true():
    summary = _summary(plays_sfx=True)
    assert actions.blocked_reason("sound", summary) is None


def test_blocked_reason_sound_allowed_when_plays_sfx_key_missing():
    """summary.get("plays_sfx", True) — a summary built before this field
    existed (or any caller that doesn't compute it) must default to allowed,
    same as the legacy-fallback default everywhere else in this guard."""
    summary = {"scenes": 5, "pics": 20, "clips": 10, "cast": 2, "status": "ready_for_sound_design"}
    assert actions.blocked_reason("sound", summary) is None


def test_blocked_reason_other_verbs_unaffected_by_plays_sfx_false():
    """The plays_sfx check is scoped to verb=='sound' only — it must not leak
    into other verbs' needs-based gating."""
    summary = _summary(plays_sfx=False, sfx_blocked_reason="blocked", pics=0)
    # "images" needs pics>0 for verbs like "voice"/"animate" — unaffected by
    # the sound-specific plays_sfx flag; "script" needs nothing.
    assert actions.blocked_reason("script", summary) is None
