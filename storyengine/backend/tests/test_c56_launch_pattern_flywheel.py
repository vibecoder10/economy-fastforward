"""Tests for checklist C56 (P4.2-g) — the per-launch pattern flywheel's
wiring into the analytics sync (routes/youtube_sync.py::_writeback_matched_
videos), the seam decisions.md's "two convergent entry points" ruling calls
trigger (b).

Covers:
  1. A video that clears the maturity bar (ctr populated + impressions >=
     LAUNCH_ANALYSIS_MIN_IMPRESSIONS) and hasn't been analyzed yet
     (launch_pattern_analyzed_at IS NULL) is queued for launch analysis,
     and the write-once marker is included in that video's UPDATE.
  2. A video that's ALREADY been analyzed (marker set) is never re-queued.
  3. A video below the impressions bar, or with no ctr yet, is never queued.
  4. channel_patterns.run_launch_pattern_analysis is called with the correct
     batch shape (youtube_video_id + internal_video_id per pending video).
  5. A scoring/DB failure inside the flywheel never breaks the analytics
     sync — the per-row UPDATE (and every other video's writeback) still
     completes.
  6. No pending videos this sync -> the flywheel is never invoked at all.

Same monkeypatch-module-level-function convention as tests/test_channel_
patterns.py / tests/test_c51_candidate_auto_launch.py — no real DB.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/test_c56_launch_pattern_flywheel.py -q
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import routes.youtube_sync as yts

TENANT = "tenant-c56"


def _row(
    internal_id="internal-1",
    cv_video_id="yt-1",
    ctr_percent=5.0,
    impressions=2000,
    launch_pattern_analyzed_at=None,
    view_count=1000,
    published_at=None,
):
    published_at = published_at or (datetime.now(timezone.utc) - timedelta(days=5))
    return {
        "internal_id": internal_id,
        "published_at": published_at,
        "view_count": view_count,
        "like_count": 10,
        "comment_count": 2,
        "impressions": impressions,
        "ctr_percent": ctr_percent,
        "avg_view_duration_seconds": 120,
        "cv_retention": 55.0,
        "watch_time_hours": 10.0,
        "subscribers_gained": 3,
        "cv_video_id": cv_video_id,
        "upload_date": published_at,
        "views_24h": None,
        "views_48h": None,
        "views_7d": None,
        "views_30d": None,
        "ctr_48h": None,
        "retention_48h": None,
        "launch_pattern_analyzed_at": launch_pattern_analyzed_at,
    }


def _run_writeback(monkeypatch, rows, *, run_launch=None):
    async def fake_fetch_all(query, *args):
        return rows

    executed = []

    async def fake_execute(query, *args):
        executed.append((query, args))

    monkeypatch.setattr(yts, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(yts, "execute", fake_execute)

    called = {"args": None}

    async def fake_run_launch(tenant_id, videos):
        called["args"] = (tenant_id, videos)
        if run_launch is not None:
            return await run_launch(tenant_id, videos)
        return {"proposed": 0, "rows": []}

    import channel_patterns
    monkeypatch.setattr(channel_patterns, "run_launch_pattern_analysis", fake_run_launch)

    asyncio.run(yts._writeback_matched_videos(TENANT))
    return executed, called


def test_matured_unanalyzed_video_is_queued_and_marker_written(monkeypatch):
    rows = [_row()]
    executed, called = _run_writeback(monkeypatch, rows)

    assert called["args"] is not None
    tenant_id, videos = called["args"]
    assert tenant_id == TENANT
    assert videos == [{"youtube_video_id": "yt-1", "internal_video_id": "internal-1"}]

    # the per-row UPDATE must include the write-once marker.
    query, args = executed[0]
    assert "launch_pattern_analyzed_at" in query


def test_already_analyzed_video_is_never_requeued(monkeypatch):
    rows = [_row(launch_pattern_analyzed_at=datetime.now(timezone.utc) - timedelta(days=1))]
    executed, called = _run_writeback(monkeypatch, rows)

    assert called["args"] is None  # flywheel never invoked — nothing pending
    query, _args = executed[0]
    assert "launch_pattern_analyzed_at" not in query  # marker already set, not rewritten


def test_below_impressions_bar_is_never_queued(monkeypatch):
    rows = [_row(impressions=500)]  # below LAUNCH_ANALYSIS_MIN_IMPRESSIONS (1000)
    _executed, called = _run_writeback(monkeypatch, rows)
    assert called["args"] is None


def test_no_ctr_yet_is_never_queued(monkeypatch):
    rows = [_row(ctr_percent=None)]
    _executed, called = _run_writeback(monkeypatch, rows)
    assert called["args"] is None


def test_missing_youtube_video_id_is_never_queued(monkeypatch):
    rows = [_row(cv_video_id=None)]
    _executed, called = _run_writeback(monkeypatch, rows)
    assert called["args"] is None


def test_multiple_matured_videos_batched_into_one_call(monkeypatch):
    rows = [
        _row(internal_id="internal-1", cv_video_id="yt-1"),
        _row(internal_id="internal-2", cv_video_id="yt-2"),
        _row(internal_id="internal-3", cv_video_id="yt-3",
             launch_pattern_analyzed_at=datetime.now(timezone.utc)),  # already done
    ]
    _executed, called = _run_writeback(monkeypatch, rows)
    tenant_id, videos = called["args"]
    assert videos == [
        {"youtube_video_id": "yt-1", "internal_video_id": "internal-1"},
        {"youtube_video_id": "yt-2", "internal_video_id": "internal-2"},
    ]


def test_flywheel_failure_never_breaks_the_sync(monkeypatch):
    """A scoring/DB hiccup inside run_launch_pattern_analysis must not
    prevent the per-row UPDATE from completing — the marker was already
    written into that same UPDATE statement before the flywheel call runs."""
    async def boom(tenant_id, videos):
        raise RuntimeError("channel_patterns blew up")

    rows = [_row()]
    executed, called = _run_writeback(monkeypatch, rows, run_launch=boom)
    assert called["args"] is not None  # it was invoked (and raised internally)
    assert len(executed) == 1  # the per-row UPDATE still ran
    query, _args = executed[0]
    assert "launch_pattern_analyzed_at" in query  # marker still written


def test_no_pending_videos_never_invokes_the_flywheel(monkeypatch):
    rows = [_row(ctr_percent=None), _row(impressions=1)]
    _executed, called = _run_writeback(monkeypatch, rows)
    assert called["args"] is None
