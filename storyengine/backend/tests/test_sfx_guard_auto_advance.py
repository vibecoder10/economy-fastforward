"""Tests for the SFX render-path guard's auto-advance wiring
(pipeline_executor.py's `_run_next_step_status_map` and `_enabled_stages`).

Background (see docs/failure-modes.md's "Per-Stage Resumability" table and
storyengine/backend/status_map.py's render_path_plays_sfx): only ONE of
run_render's five dispatch branches ever mixes assets.sound_effect_url into
the final video. A video whose render path is one of the other four
(Custom Film, static_docu, grok_native, character_dialogue) must never run
the paid sound stage — and a video that reached ready_for_sound_design/
ready_for_sound_effects BEFORE this guard existed must not deadlock there.

Covers:
  1. `_enabled_stages` excludes "sound" (added on top of any explicit
     pipeline_stages plan) exactly when render_path_plays_sfx(video) is
     False, and leaves it in when True — both with pipeline_stages=None
     (the historical "full pipeline" default) and with an explicit plan.
  2. `_run_next_step_status_map`: a video AT ready_for_sound_design or
     ready_for_sound_effects whose render path can't play SFX is advanced
     past the stage WITHOUT run_sound_prompts/run_sound_effects ever being
     called (proven by monkeypatching them to raise if invoked) — the
     "must not deadlock" requirement for a video written to that status
     before this guard existed.
  3. The SAME entry point, for a video whose render path CAN play SFX
     (mirrors the real legacy-fallback video found stuck at
     ready_for_sound_design in prod, id 146242df-cbe0-4a25-9a78-e11bfa22526b:
     render_mode/dialogue_audio NULL, dialogue_mode='narration_only') is
     completely unaffected — the real handler still runs. This is the
     regression check: the guard must never trap a legitimate video.

No live DB: pipeline_executor.execute/fetch_one are monkeypatched, same
convention as tests/test_c55_full_auto_continuation.py.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/test_sfx_guard_auto_advance.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys

_BACKEND = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import pipeline_executor as pe_mod  # noqa: E402
from pipeline_executor import PipelineExecutor  # noqa: E402
import status_map as sm  # noqa: E402

TENANT = "tenant-sfx-guard"
VIDEO = "video-sfx-guard"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _sfx_blocked_video(status: str, **extra) -> dict:
    """A video on the character-dialogue perform render path — one of the
    four branches that drops sound effects."""
    row = {
        "id": VIDEO, "status": status, "tenant_id": TENANT,
        "custom_film_plan_id": None, "render_mode": None,
        "dialogue_audio": None, "dialogue_mode": "character_dialogue",
        "pipeline_stages": None,
    }
    row.update(extra)
    return row


def _legacy_video(status: str, **extra) -> dict:
    """Mirrors the real prod video (146242df-cbe0-4a25-9a78-e11bfa22526b)
    found stuck at ready_for_sound_design: NULL render_mode/dialogue_audio,
    dialogue_mode='narration_only' — the legacy fallback path that DOES
    play sound effects."""
    row = {
        "id": VIDEO, "status": status, "tenant_id": TENANT,
        "custom_film_plan_id": None, "render_mode": None,
        "dialogue_audio": None, "dialogue_mode": "narration_only",
        "pipeline_stages": None,
    }
    row.update(extra)
    return row


def _patch_db(monkeypatch, video: dict):
    """fetch_one returns `video` for _get_video's SELECT * query; execute
    just records calls (status updates, stage_transitions inserts)."""
    calls = []

    async def _fake_fetch_one(query, *args):
        return dict(video)

    async def _fake_execute(query, *args):
        calls.append((query, args))
        return "UPDATE 1"

    monkeypatch.setattr(pe_mod, "fetch_one", _fake_fetch_one)
    monkeypatch.setattr(pe_mod, "execute", _fake_execute)
    return calls


# =============================================================================
# 1. _enabled_stages
# =============================================================================

def test_enabled_stages_excludes_sound_when_sfx_blocked_and_no_explicit_plan():
    video = _sfx_blocked_video("ready_for_sound_design")
    stages = PipelineExecutor._enabled_stages(video)
    assert stages is not None
    assert "sound" not in stages
    # Every other stage stays in — this is an EXCLUSION, not a restriction.
    assert "render" in stages and "upload" in stages and "video" in stages


def test_enabled_stages_none_when_sfx_plays_and_no_explicit_plan():
    video = _legacy_video("ready_for_sound_design")
    assert PipelineExecutor._enabled_stages(video) is None


def test_enabled_stages_drops_sound_from_an_explicit_plan_when_sfx_blocked():
    video = _sfx_blocked_video(
        "ready_for_sound_design",
        pipeline_stages=["script", "voice", "images", "sound", "video", "render"],
    )
    stages = PipelineExecutor._enabled_stages(video)
    assert "sound" not in stages
    assert set(stages) == {"script", "voice", "images", "video", "render"}


def test_enabled_stages_keeps_explicit_plan_unchanged_when_sfx_plays():
    plan = ["script", "voice", "images", "sound", "video", "render"]
    video = _legacy_video("ready_for_sound_design", pipeline_stages=plan)
    stages = PipelineExecutor._enabled_stages(video)
    assert set(stages) == set(plan)


def test_enabled_stages_none_video_returns_none():
    assert PipelineExecutor._enabled_stages(None) is None


# =============================================================================
# 2. _run_next_step_status_map — SFX-blocked video must skip, not deadlock
# =============================================================================

def _forbid_sound_handlers(monkeypatch, ex: PipelineExecutor):
    """run_sound_prompts/run_sound_effects must NEVER be called for an
    SFX-blocked video — raise if they are, so a regression that removes the
    guard fails loudly instead of just spending money quietly."""
    async def _boom(video_id):
        raise AssertionError(f"run_sound_prompts/run_sound_effects called for blocked video {video_id}")

    monkeypatch.setattr(ex, "run_sound_prompts", _boom)
    monkeypatch.setattr(ex, "run_sound_effects", _boom)


def test_sfx_blocked_video_at_ready_for_sound_design_skips_and_advances(monkeypatch):
    video = _sfx_blocked_video("ready_for_sound_design")
    calls = _patch_db(monkeypatch, video)
    ex = PipelineExecutor(TENANT)
    _forbid_sound_handlers(monkeypatch, ex)

    result = _run(ex._run_next_step_status_map(VIDEO))

    assert result["status"] == "ready_for_video_scripts"
    assert result.get("skipped_stage") == "sound"
    assert "character-dialogue" in result["message"]
    # The status write and the stage_transitions log both fired.
    status_updates = [c for c in calls if "UPDATE videos SET status" in c[0]]
    assert len(status_updates) == 1
    assert status_updates[0][1][0] == "ready_for_video_scripts"
    transitions = [c for c in calls if "INSERT INTO stage_transitions" in c[0]]
    assert len(transitions) == 1


def test_sfx_blocked_video_at_ready_for_sound_effects_skips_and_advances(monkeypatch):
    video = _sfx_blocked_video("ready_for_sound_effects")
    calls = _patch_db(monkeypatch, video)
    ex = PipelineExecutor(TENANT)
    _forbid_sound_handlers(monkeypatch, ex)

    result = _run(ex._run_next_step_status_map(VIDEO))

    assert result["status"] == "ready_for_video_scripts"
    assert result.get("skipped_stage") == "sound"


# =============================================================================
# 3. Regression: a real legacy-fallback video is completely unaffected
# =============================================================================

def test_legacy_video_at_ready_for_sound_design_still_runs_the_real_handler(monkeypatch):
    """Mirrors the real prod video found stuck at ready_for_sound_design
    (146242df-cbe0-4a25-9a78-e11bfa22526b) — render_mode/dialogue_audio
    NULL, dialogue_mode='narration_only'. render_path_plays_sfx is True for
    this shape, so the guard must be a complete no-op: the real
    run_sound_prompts handler still runs, unchanged from before this guard
    existed."""
    video = _legacy_video("ready_for_sound_design")
    _patch_db(monkeypatch, video)
    ex = PipelineExecutor(TENANT)

    called = {}

    async def _fake_run_sound_prompts(video_id):
        called["video_id"] = video_id
        return {"status": "completed"}

    monkeypatch.setattr(ex, "run_sound_prompts", _fake_run_sound_prompts)

    result = _run(ex._run_next_step_status_map(VIDEO))

    assert called.get("video_id") == VIDEO
    assert result == {"status": "completed"}


def test_legacy_video_at_ready_for_sound_effects_still_runs_the_real_handler(monkeypatch):
    video = _legacy_video("ready_for_sound_effects")
    _patch_db(monkeypatch, video)
    ex = PipelineExecutor(TENANT)

    called = {}

    async def _fake_run_sound_effects(video_id):
        called["video_id"] = video_id
        return {"status": "completed"}

    monkeypatch.setattr(ex, "run_sound_effects", _fake_run_sound_effects)

    result = _run(ex._run_next_step_status_map(VIDEO))

    assert called.get("video_id") == VIDEO
    assert result == {"status": "completed"}


# =============================================================================
# 4. Sanity: the real prod video shape (as read via `se db`, 2026-07-24)
# =============================================================================

def test_real_prod_stuck_video_shape_plays_sfx():
    """id 146242df-cbe0-4a25-9a78-e11bfa22526b, read live from prod:
    render_mode=null, dialogue_audio=null, dialogue_mode='narration_only',
    custom_film_plan_id=null. It is NOT sfx-blocked — the guard leaves it
    alone, confirming the fix doesn't regress the one real video this task
    was checked against."""
    video = {
        "render_mode": None, "dialogue_audio": None,
        "dialogue_mode": "narration_only", "custom_film_plan_id": None,
    }
    assert sm.render_path_plays_sfx(video) is True
