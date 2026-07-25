"""Tests for the SFX guard's coverage of routes/videos.py::advance_video —
gap 2 from independent review (2026-07-24): the human "Advance" button used
by every production tab writes `videos.status` with a RAW
`UPDATE videos SET status = $1`, never funneled through PipelineExecutor.
_update_video_status/_enabled_stages the way every other status write is.
Before this fix it could park an SFX-blocked video at
ready_for_sound_design/ready_for_sound_effects, contradicting the documented
invariant that every status write reroutes around a blocked sound stage.

The fix reroutes `next_status` through the SAME
`PipelineExecutor._enabled_stages` static method (called directly, not
re-derived) + `status_map.resolve_planned_status` every other reroute uses,
right before the write — both for the plain "advance one step" path and the
explicit `?to=` skip-to-target path.

Not a spend risk on its own (advance_video never triggers a paid
generation) — this is about the STATUS INVARIANT being actually true, which
production_guide.py and any future caller that trusts "a video is never at
ready_for_sound_design/effects when its render path can't play it" depends on.

No live DB: routes.videos.fetch_one/execute are monkeypatched.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_sfx_guard_advance_video.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import routes.videos as videos_route  # noqa: E402

TENANT = "tenant-advance-sfx"
VIDEO = "video-advance-sfx"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _sfx_blocked_video(status: str, **extra) -> dict:
    row = {
        "id": VIDEO, "status": status,
        "custom_film_plan_id": None, "render_mode": None,
        "dialogue_audio": None, "dialogue_mode": "character_dialogue",
        "pipeline_stages": None,
    }
    row.update(extra)
    return row


def _legacy_video(status: str, **extra) -> dict:
    row = {
        "id": VIDEO, "status": status,
        "custom_film_plan_id": None, "render_mode": None,
        "dialogue_audio": None, "dialogue_mode": "narration_only",
        "pipeline_stages": None,
    }
    row.update(extra)
    return row


def _patch_db(monkeypatch, video: dict):
    calls = []

    async def _fake_fetch_one(query, *args):
        return dict(video)

    async def _fake_execute(query, *args):
        calls.append((query, args))
        return "UPDATE 1"

    monkeypatch.setattr(videos_route, "fetch_one", _fake_fetch_one)
    monkeypatch.setattr(videos_route, "execute", _fake_execute)
    return calls


# =============================================================================
# Plain "advance one step" path (no `to`)
# =============================================================================

def test_advance_reroutes_past_sound_for_blocked_video(monkeypatch):
    """Natural next step from ready_for_images is ready_for_sound_design —
    for a blocked video, the write must land on ready_for_video_scripts
    instead, not park at ready_for_sound_design."""
    video = _sfx_blocked_video("ready_for_images")
    calls = _patch_db(monkeypatch, video)

    result = _run(videos_route.advance_video(VIDEO, to=None, tenant_id=TENANT))

    assert result["status"] == "ready_for_video_scripts"
    assert result["previous"] == "ready_for_images"
    status_updates = [c for c in calls if "UPDATE videos SET status" in c[0]]
    assert len(status_updates) == 1
    assert status_updates[0][1][0] == "ready_for_video_scripts"


def test_advance_from_sound_design_itself_reroutes_for_blocked_video(monkeypatch):
    """A video ALREADY parked at ready_for_sound_design (written before this
    fix, or by some other path) must skip past ready_for_sound_effects too,
    landing on ready_for_video_scripts in one Advance click."""
    video = _sfx_blocked_video("ready_for_sound_design")
    _patch_db(monkeypatch, video)

    result = _run(videos_route.advance_video(VIDEO, to=None, tenant_id=TENANT))

    assert result["status"] == "ready_for_video_scripts"


def test_advance_unaffected_for_legacy_video(monkeypatch):
    """Regression: a video whose render path DOES play sound effects must
    advance normally, one step at a time, unchanged from before this fix."""
    video = _legacy_video("ready_for_images")
    _patch_db(monkeypatch, video)

    result = _run(videos_route.advance_video(VIDEO, to=None, tenant_id=TENANT))

    assert result["status"] == "ready_for_sound_design"


# =============================================================================
# Explicit `?to=` skip-to-target path
# =============================================================================

def test_advance_to_explicit_target_past_sound_still_reroutes_if_needed(monkeypatch):
    """Even an explicit `to=` request landing inside the blocked sound range
    gets rerouted — the invariant holds regardless of how next_status was
    derived."""
    video = _sfx_blocked_video("ready_for_images")
    _patch_db(monkeypatch, video)

    result = _run(videos_route.advance_video(VIDEO, to="ready_for_sound_effects", tenant_id=TENANT))

    assert result["status"] == "ready_for_video_scripts"


def test_advance_to_target_past_sound_entirely_is_unaffected(monkeypatch):
    """A `to=` target that's already past the sound stage needs no reroute —
    unaffected by this guard, works exactly as before."""
    video = _sfx_blocked_video("ready_for_images")
    _patch_db(monkeypatch, video)

    result = _run(videos_route.advance_video(VIDEO, to="ready_for_video_scripts", tenant_id=TENANT))

    assert result["status"] == "ready_for_video_scripts"


def test_advance_to_invalid_target_still_raises_400(monkeypatch):
    """Reroute logic must not interfere with the existing validation — an
    unreachable target still 400s exactly as before."""
    video = _sfx_blocked_video("ready_for_images")
    _patch_db(monkeypatch, video)

    with pytest.raises(HTTPException) as exc_info:
        _run(videos_route.advance_video(VIDEO, to="not_a_real_status", tenant_id=TENANT))
    assert exc_info.value.status_code == 400
