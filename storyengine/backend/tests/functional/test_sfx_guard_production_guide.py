"""Tests for the SFX guard's coverage of production_guide.py — gap 3 from
independent review (2026-07-24): `bucket_enabled("sound")` only checked
`render_mode == 'static_docu'` and the creator's `pipeline_stages`; it knew
nothing about custom_film_plan_id / grok_native dialogue_audio /
character_dialogue dialogue_mode, so `_recommend_next_step` could recommend
"Sound design + effects" to the MCP co-pilot for a video that can never
actually do it.

The fix: `get_production_guide` now passes its computed `enabled` stage list
through `status_map.stages_excluding_blocked_sound` (the same shared
list-filter `pipeline_executor.PipelineExecutor._enabled_stages` uses) before
building `bucket_enabled`, so a blocked video's "sound" stage always reports
state "skipped_by_format" and next_step never recommends it.

Same stubbing convention as tests/functional/test_c66_production_guide.py
(the original C66 test file this guard builds on) — no live DB.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_sfx_guard_production_guide.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import production_guide  # noqa: E402

TENANT = "tenant-guide-sfx"
VIDEO = "video-guide-sfx"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _video_row(**overrides):
    row = {
        "video_title": "Test Video", "status": "ready_for_image_prompts",
        "render_mode": None, "pipeline_stages": None, "skip_voice": False,
        "custom_film_plan_id": None, "dialogue_audio": None, "dialogue_mode": None,
        "story_locked_at": None, "characters_approved_at": None,
        "environments_approved_at": None, "thumbnail_url": None,
        "youtube_url": None, "youtube_video_id": None, "story_bible": None,
        "research_payload": {"x": 1},
    }
    row.update(overrides)
    return row


def _summary(**overrides):
    s = {"scenes": 3, "boards": 0, "voiced": 3, "pics": 0, "clips": 0, "cast": 0}
    s.update(overrides)
    return s


def _patch_all(video_row, *, cast_rows=None, env_rows=None, board_rows=None,
                active_rows=None, summary=None):
    async def _fake_fetch_one(query, *args):
        assert "FROM videos WHERE id" in query
        return video_row

    async def _fake_fetch_all(query, *args):
        if "video_characters" in query:
            return cast_rows or []
        if "video_environments" in query:
            return env_rows or []
        if "FROM scripts" in query:
            return board_rows or []
        if "background_tasks" in query:
            return active_rows or []
        raise AssertionError(f"unexpected fetch_all query: {query!r}")

    return (
        patch.object(production_guide, "fetch_one", _fake_fetch_one),
        patch.object(production_guide, "fetch_all", _fake_fetch_all),
        patch.object(production_guide, "video_summary", AsyncMock(return_value=summary or _summary())),
    )


def _guide_for(video_row, **kwargs):
    p1, p2, p3 = _patch_all(video_row, **kwargs)
    with p1, p2, p3:
        return _run(production_guide.get_production_guide(TENANT, VIDEO))


# =============================================================================
# Each non-legacy SFX-blocked render path -> "sound" reports skipped_by_format
# =============================================================================

def test_custom_film_video_sound_stage_skipped_by_format():
    video = _video_row(custom_film_plan_id="11111111-1111-1111-1111-111111111111")
    guide = _guide_for(video)
    by_key = {s["key"]: s for s in guide["stages"]}
    assert by_key["sound"]["state"] == "skipped_by_format"


def test_grok_native_video_sound_stage_skipped_by_format():
    video = _video_row(dialogue_audio="grok_native")
    guide = _guide_for(video)
    by_key = {s["key"]: s for s in guide["stages"]}
    assert by_key["sound"]["state"] == "skipped_by_format"


def test_character_dialogue_video_sound_stage_skipped_by_format():
    video = _video_row(dialogue_mode="character_dialogue")
    guide = _guide_for(video)
    by_key = {s["key"]: s for s in guide["stages"]}
    assert by_key["sound"]["state"] == "skipped_by_format"


def test_static_docu_video_sound_stage_still_skipped_by_format():
    """Regression: static_docu was ALREADY handled via static_stage_plan
    before this fix — must still work identically."""
    video = _video_row(render_mode="static_docu")
    guide = _guide_for(video)
    by_key = {s["key"]: s for s in guide["stages"]}
    assert by_key["sound"]["state"] == "skipped_by_format"
    assert by_key["video"]["state"] == "skipped_by_format"


def test_legacy_video_sound_stage_not_skipped(monkeypatch=None):
    """Regression: the legacy fallback shape (narration_only / everything
    else NULL) must still report sound as a real, runnable stage."""
    video = _video_row(dialogue_mode="narration_only")
    guide = _guide_for(video, summary=_summary(pics=10))
    by_key = {s["key"]: s for s in guide["stages"]}
    assert by_key["sound"]["state"] != "skipped_by_format"


# =============================================================================
# next_step must never recommend the blocked sound stage
# =============================================================================

def test_next_step_never_recommends_sound_for_blocked_video():
    """A video with everything else done except sound/video/thumbnail must
    recommend 'video' (the next real stage), never 'sound', when blocked."""
    video = _video_row(
        dialogue_mode="character_dialogue",
        status="ready_for_sound_design",
        characters_approved_at="2026-01-01T00:00:00Z",
        environments_approved_at="2026-01-01T00:00:00Z",
    )
    board_rows = [
        {"scene": 1, "storyboard_1_url": "https://x/1.png", "storyboard_2_url": None, "storyboard_3_url": None},
    ]
    guide = _guide_for(
        video,
        summary=_summary(pics=6, scenes=1),
        cast_rows=[{"id": "c1", "name": "Ava", "reference_url": "https://x/ava.png"}],
        board_rows=board_rows,
    )
    assert guide["next_step"]["stage"] != "sound"


# =============================================================================
# Explicit creator plan combined with a blocked render path
# =============================================================================

def test_creator_plan_including_sound_on_blocked_video_still_skips_it():
    """Even when the creator explicitly turned "sound" ON in pipeline_stages,
    a blocked render path still force-excludes it — the render-path check is
    additive on top of the creator's plan, never overridden by it."""
    video = _video_row(
        dialogue_audio="grok_native",
        pipeline_stages=["script", "voice", "images", "sound", "video", "render"],
    )
    guide = _guide_for(video)
    by_key = {s["key"]: s for s in guide["stages"]}
    assert by_key["sound"]["state"] == "skipped_by_format"
    # Everything else the creator turned on stays on.
    assert by_key["video"]["state"] != "skipped_by_format"
