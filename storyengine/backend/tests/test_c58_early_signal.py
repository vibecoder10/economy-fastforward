"""Tests for checklist follow-up queue C58 — the early-warning launch
classifier (backend/early_warning.py) and its wiring into the analytics
sync (routes/youtube_sync.py::_writeback_matched_videos).

Covers:
  1. classify_early_signal (pure): ok/watch/underperforming bands, too-thin
     cohort -> None (never guesses), no ctr_48h yet -> None, non-positive
     median -> None, evidence shape carries the numbers/N/thresholds.
  2. run_early_signal_classification: persists early_signal/_evidence/_at
     when classifiable; leaves the marker untouched (self-healing retry)
     when the cohort is too thin; notifies bot_activity ONLY on
     'underperforming', exactly once; a notify failure doesn't break the
     persisted write; a per-video classification/write failure doesn't
     abort the rest of the batch; history-fetch failure fails soft;
     tenant scoping (history query + notify + UPDATE all carry the given
     tenant_id, never cross-tenant).
  3. Wiring into _writeback_matched_videos: a video whose ctr_48h is
     already set (prior sync) and never classified is queued; a video
     whose ctr_48h newly lands THIS sync (hours_since >= 48) is queued;
     an already-classified video (early_signal_at set) is NEVER
     re-queued (mature videos stop re-classifying); a video with no
     ctr_48h yet is never queued; a classifier exception never breaks the
     per-row UPDATE or the rest of the sync; no pending videos -> the
     classifier is never invoked at all.

Same monkeypatch-module-level-function convention as tests/test_channel_
patterns.py / tests/test_c56_launch_pattern_flywheel.py — no real DB.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/test_c58_early_signal.py -q
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import early_warning as ew
import routes.youtube_sync as yts

TENANT = "tenant-c58"


# ---------------------------------------------------------------------------
# classify_early_signal — pure.
# ---------------------------------------------------------------------------

def _history(median_ctr: float, n: int = 5) -> list[float]:
    """n values whose median is exactly median_ctr (odd n keeps it exact)."""
    assert n % 2 == 1
    half = n // 2
    return [median_ctr - i * 0.1 for i in range(half, 0, -1)] + [median_ctr] + [
        median_ctr + i * 0.1 for i in range(1, half + 1)
    ]


def test_classify_returns_none_without_video_ctr():
    assert ew.classify_early_signal(None, _history(5.0)) is None


def test_classify_returns_none_below_min_cohort():
    assert ew.classify_early_signal(2.0, [5.0, 5.0]) is None  # only 2, need 5


def test_classify_returns_none_when_median_non_positive():
    assert ew.classify_early_signal(1.0, [0.0, 0.0, 0.0, 0.0, 0.0]) is None


def test_classify_ok_when_at_channel_median():
    result = ew.classify_early_signal(5.0, _history(5.0))
    assert result["level"] == "ok"


def test_classify_ok_when_above_channel_median():
    result = ew.classify_early_signal(8.0, _history(5.0))
    assert result["level"] == "ok"


def test_classify_watch_band():
    # 20% below median -> between watch (15%) and underperforming (30%).
    result = ew.classify_early_signal(4.0, _history(5.0))
    assert result["level"] == "watch"


def test_classify_underperforming_band():
    # 50% below median -> past the 30% underperforming bar.
    result = ew.classify_early_signal(2.5, _history(5.0))
    assert result["level"] == "underperforming"


def test_classify_boundary_exactly_at_watch_threshold_is_watch():
    # Exactly -15% delta.
    median = 10.0
    video_ctr = median * (1 - ew.WATCH_THRESHOLD_PCT / 100.0)
    result = ew.classify_early_signal(video_ctr, _history(median))
    assert result["level"] == "watch"


def test_classify_boundary_exactly_at_underperforming_threshold():
    median = 10.0
    video_ctr = median * (1 - ew.UNDERPERFORMING_THRESHOLD_PCT / 100.0)
    result = ew.classify_early_signal(video_ctr, _history(median))
    assert result["level"] == "underperforming"


def test_classify_evidence_carries_numbers_n_and_thresholds():
    result = ew.classify_early_signal(2.5, _history(5.0))
    ev = result["evidence"]
    assert ev["metric"] == "ctr_48h"
    assert ev["maturity"] == "48h"
    assert ev["video_ctr_48h"] == 2.5
    assert ev["channel_median_ctr_48h"] == 5.0
    assert ev["cohort_size"] == 5
    assert ev["delta_pct"] == -50.0
    assert ev["watch_threshold_pct"] == ew.WATCH_THRESHOLD_PCT
    assert ev["underperforming_threshold_pct"] == ew.UNDERPERFORMING_THRESHOLD_PCT


def test_classify_none_values_in_history_are_filtered():
    values = _history(5.0) + [None, None]  # type: ignore[list-item]
    result = ew.classify_early_signal(2.5, values)
    assert result["evidence"]["cohort_size"] == 5  # Nones don't inflate the cohort


def test_underperforming_threshold_reuses_channel_patterns_outlier_bar():
    """C58's underperforming cutoff must be the SAME number channel_patterns
    already calls an outlier — reuse, not a parallel constant."""
    import channel_patterns as cp
    assert ew.UNDERPERFORMING_THRESHOLD_PCT == cp.OUTLIER_THRESHOLD_PCT
    assert ew.WATCH_THRESHOLD_PCT == cp.OUTLIER_THRESHOLD_PCT / 2.0


# ---------------------------------------------------------------------------
# run_early_signal_classification — DB-touching, monkeypatched module fns.
# ---------------------------------------------------------------------------

def _setup(monkeypatch, *, history_rows, execute_should_raise_on=None):
    """history_rows: [{"id": ..., "ctr_48h": ...}, ...] for _channel_ctr48_history.
    Returns (fetch_calls, execute_calls) lists recording every call."""
    fetch_calls = []
    execute_calls = []

    async def fake_fetch_all(query, *args):
        fetch_calls.append((query, args))
        return history_rows

    async def fake_execute(query, *args):
        execute_calls.append((query, args))
        if execute_should_raise_on and execute_should_raise_on in query:
            raise RuntimeError("boom")

    monkeypatch.setattr(ew, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(ew, "execute", fake_execute)
    return fetch_calls, execute_calls


def test_classifies_and_persists_when_cohort_is_enough(monkeypatch):
    history = [{"id": f"other-{i}", "ctr_48h": 5.0} for i in range(5)]
    fetch_calls, execute_calls = _setup(monkeypatch, history_rows=history)

    result = asyncio.run(ew.run_early_signal_classification(
        TENANT, [{"internal_video_id": "vid-1", "ctr_48h": 2.5}],
    ))
    assert result["classified"] == 1
    update_calls = [c for c in execute_calls if "UPDATE videos" in c[0]]
    assert len(update_calls) == 1
    query, args = update_calls[0]
    assert "early_signal" in query and "early_signal_evidence" in query and "early_signal_at" in query
    assert args[0] == "underperforming"
    assert args[-2] == "vid-1"
    assert args[-1] == TENANT  # tenant-scoped WHERE clause


def test_leaves_marker_untouched_when_cohort_too_thin(monkeypatch):
    history = [{"id": "other-1", "ctr_48h": 5.0}]  # only 1, need 5
    _fetch_calls, execute_calls = _setup(monkeypatch, history_rows=history)

    result = asyncio.run(ew.run_early_signal_classification(
        TENANT, [{"internal_video_id": "vid-1", "ctr_48h": 2.5}],
    ))
    assert result["classified"] == 0
    assert not any("UPDATE videos" in c[0] for c in execute_calls)  # never written


def test_excludes_the_video_itself_from_its_own_history(monkeypatch):
    # 5 OTHER videos plus this video's own (older) ctr_48h row must not
    # count toward its own cohort or skew its own median.
    history = [{"id": f"other-{i}", "ctr_48h": 5.0} for i in range(5)]
    history.append({"id": "vid-1", "ctr_48h": 999.0})  # itself — must be excluded
    _fetch_calls, execute_calls = _setup(monkeypatch, history_rows=history)

    asyncio.run(ew.run_early_signal_classification(
        TENANT, [{"internal_video_id": "vid-1", "ctr_48h": 2.5}],
    ))
    update_calls = [c for c in execute_calls if "UPDATE videos" in c[0]]
    assert len(update_calls) == 1
    assert update_calls[0][1][0] == "underperforming"  # median stayed 5.0, not skewed by 999


def test_notifies_only_on_underperforming(monkeypatch):
    history = [{"id": f"other-{i}", "ctr_48h": 5.0} for i in range(5)]
    _fetch_calls, execute_calls = _setup(monkeypatch, history_rows=history)

    # 'ok' band: at the median.
    asyncio.run(ew.run_early_signal_classification(
        TENANT, [{"internal_video_id": "vid-ok", "ctr_48h": 5.0}],
    ))
    assert not any("bot_activity" in c[0] for c in execute_calls)

    execute_calls.clear()
    # 'underperforming' band.
    asyncio.run(ew.run_early_signal_classification(
        TENANT, [{"internal_video_id": "vid-bad", "ctr_48h": 2.5}],
    ))
    notify_calls = [c for c in execute_calls if "bot_activity" in c[0]]
    assert len(notify_calls) == 1
    assert notify_calls[0][1][0] == TENANT
    assert notify_calls[0][1][2] == "vid-bad"


def test_notify_failure_does_not_undo_the_persisted_write(monkeypatch):
    history = [{"id": f"other-{i}", "ctr_48h": 5.0} for i in range(5)]
    _fetch_calls, execute_calls = _setup(
        monkeypatch, history_rows=history, execute_should_raise_on="bot_activity",
    )
    result = asyncio.run(ew.run_early_signal_classification(
        TENANT, [{"internal_video_id": "vid-bad", "ctr_48h": 2.5}],
    ))
    assert result["classified"] == 1  # the UPDATE succeeded before the notify blew up
    assert any("UPDATE videos" in c[0] for c in execute_calls)


def test_one_videos_write_failure_does_not_abort_the_batch(monkeypatch):
    history = [{"id": f"other-{i}", "ctr_48h": 5.0} for i in range(5)]
    calls = {"n": 0}

    async def fake_fetch_all(query, *args):
        return history

    async def fake_execute(query, *args):
        if "UPDATE videos" in query:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("db hiccup on first video")

    monkeypatch.setattr(ew, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(ew, "execute", fake_execute)

    result = asyncio.run(ew.run_early_signal_classification(
        TENANT,
        [
            {"internal_video_id": "vid-1", "ctr_48h": 2.5},
            {"internal_video_id": "vid-2", "ctr_48h": 2.5},
        ],
    ))
    assert result["classified"] == 1  # first failed, second succeeded
    assert calls["n"] == 2


def test_non_numeric_ctr_never_raises(monkeypatch):
    history = [{"id": f"other-{i}", "ctr_48h": 5.0} for i in range(5)]
    _fetch_calls, execute_calls = _setup(monkeypatch, history_rows=history)
    result = asyncio.run(ew.run_early_signal_classification(
        TENANT, [{"internal_video_id": "vid-1", "ctr_48h": "not-a-number"}],
    ))
    assert result["classified"] == 0
    assert not any("UPDATE videos" in c[0] for c in execute_calls)


def test_history_fetch_failure_fails_soft(monkeypatch):
    async def boom(query, *args):
        raise RuntimeError("db down")

    monkeypatch.setattr(ew, "fetch_all", boom)
    result = asyncio.run(ew.run_early_signal_classification(
        TENANT, [{"internal_video_id": "vid-1", "ctr_48h": 2.5}],
    ))
    assert result["classified"] == 0
    assert "error" in result


def test_empty_videos_list_never_queries(monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("should never be called")

    monkeypatch.setattr(ew, "fetch_all", boom)
    monkeypatch.setattr(ew, "execute", boom)
    result = asyncio.run(ew.run_early_signal_classification(TENANT, []))
    assert result == {"classified": 0}


def test_history_query_is_tenant_scoped(monkeypatch):
    fetch_calls, _execute_calls = _setup(monkeypatch, history_rows=[])
    asyncio.run(ew.run_early_signal_classification(
        TENANT, [{"internal_video_id": "vid-1", "ctr_48h": 2.5}],
    ))
    assert len(fetch_calls) == 1
    query, args = fetch_calls[0]
    assert "tenant_id = $1" in query
    assert args == (TENANT,)


def test_cross_tenant_isolation_history_never_leaks(monkeypatch):
    """Two tenants classified in separate calls each only ever see their
    OWN tenant_id passed to the history query — no shared/global cache."""
    seen_tenants = []

    async def fake_fetch_all(query, *args):
        seen_tenants.append(args[0])
        return [{"id": f"other-{i}", "ctr_48h": 5.0} for i in range(5)]

    async def fake_execute(query, *args):
        pass

    monkeypatch.setattr(ew, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(ew, "execute", fake_execute)

    asyncio.run(ew.run_early_signal_classification(
        "tenant-a", [{"internal_video_id": "vid-1", "ctr_48h": 2.5}],
    ))
    asyncio.run(ew.run_early_signal_classification(
        "tenant-b", [{"internal_video_id": "vid-2", "ctr_48h": 2.5}],
    ))
    assert seen_tenants == ["tenant-a", "tenant-b"]


# ---------------------------------------------------------------------------
# Wiring into routes/youtube_sync.py::_writeback_matched_videos.
# ---------------------------------------------------------------------------

def _row(
    internal_id="internal-1",
    cv_video_id="yt-1",
    ctr_percent=5.0,
    impressions=2000,
    ctr_48h=None,
    early_signal_at=None,
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
        "ctr_48h": ctr_48h,
        "retention_48h": None,
        "launch_pattern_analyzed_at": launch_pattern_analyzed_at,
        "early_signal_at": early_signal_at,
    }


def _run_writeback(monkeypatch, rows, *, run_early_signal=None, run_launch=None):
    async def fake_fetch_all(query, *args):
        return rows

    executed = []

    async def fake_execute(query, *args):
        executed.append((query, args))

    monkeypatch.setattr(yts, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(yts, "execute", fake_execute)

    called = {"launch": None, "early_signal": None}

    async def fake_run_launch(tenant_id, videos):
        called["launch"] = (tenant_id, videos)
        if run_launch is not None:
            return await run_launch(tenant_id, videos)
        return {"proposed": 0, "rows": []}

    async def fake_run_early_signal(tenant_id, videos):
        called["early_signal"] = (tenant_id, videos)
        if run_early_signal is not None:
            return await run_early_signal(tenant_id, videos)
        return {"classified": 0}

    import channel_patterns
    import early_warning
    monkeypatch.setattr(channel_patterns, "run_launch_pattern_analysis", fake_run_launch)
    monkeypatch.setattr(early_warning, "run_early_signal_classification", fake_run_early_signal)

    asyncio.run(yts._writeback_matched_videos(TENANT))
    return executed, called


def test_already_matured_unclassified_video_is_queued(monkeypatch):
    """ctr_48h already set from a prior sync (published 5 days ago, so this
    sync doesn't newly write it), never classified -> queued (the catch-up
    path, no special backfill code needed)."""
    rows = [_row(ctr_48h=4.2, early_signal_at=None)]
    _executed, called = _run_writeback(monkeypatch, rows)
    assert called["early_signal"] is not None
    tenant_id, videos = called["early_signal"]
    assert tenant_id == TENANT
    assert videos == [{"internal_video_id": "internal-1", "ctr_48h": 4.2}]


def test_freshly_matured_this_sync_is_queued(monkeypatch):
    """ctr_48h is NULL in the DB but hours_since_publish >= 48, so
    _calculate_snapshots writes it THIS sync -- must still be queued using
    the freshly-computed value."""
    rows = [_row(
        ctr_48h=None,
        published_at=datetime.now(timezone.utc) - timedelta(hours=50),
        ctr_percent=3.0,
    )]
    executed, called = _run_writeback(monkeypatch, rows)
    assert called["early_signal"] is not None
    _tenant_id, videos = called["early_signal"]
    assert videos == [{"internal_video_id": "internal-1", "ctr_48h": 3.0}]
    query, _args = executed[0]
    assert "ctr_48h" in query  # the per-row UPDATE also wrote the snapshot


def test_already_classified_video_is_never_requeued(monkeypatch):
    rows = [_row(ctr_48h=4.2, early_signal_at=datetime.now(timezone.utc) - timedelta(days=1))]
    _executed, called = _run_writeback(monkeypatch, rows)
    assert called["early_signal"] is None  # mature -- never touched again


def test_not_yet_matured_video_is_never_queued(monkeypatch):
    """No ctr_48h in the DB and not yet 48h since publish -- nothing to
    classify against yet."""
    rows = [_row(
        ctr_48h=None,
        published_at=datetime.now(timezone.utc) - timedelta(hours=10),
    )]
    _executed, called = _run_writeback(monkeypatch, rows)
    assert called["early_signal"] is None


def test_early_signal_failure_never_breaks_the_sync(monkeypatch):
    async def boom(tenant_id, videos):
        raise RuntimeError("early_warning blew up")

    rows = [_row(ctr_48h=4.2, early_signal_at=None)]
    executed, called = _run_writeback(monkeypatch, rows, run_early_signal=boom)
    assert called["early_signal"] is not None  # it was invoked (and raised internally)
    assert len(executed) == 1  # the per-row UPDATE still ran


def test_no_pending_early_signal_never_invokes_the_classifier(monkeypatch):
    rows = [_row(ctr_48h=None, published_at=datetime.now(timezone.utc) - timedelta(hours=1))]
    _executed, called = _run_writeback(monkeypatch, rows)
    assert called["early_signal"] is None


def test_multiple_videos_batched_into_one_classifier_call(monkeypatch):
    rows = [
        _row(internal_id="internal-1", ctr_48h=4.2, early_signal_at=None),
        _row(internal_id="internal-2", ctr_48h=3.9, early_signal_at=None),
        _row(internal_id="internal-3", ctr_48h=5.0,
             early_signal_at=datetime.now(timezone.utc)),  # already classified
    ]
    _executed, called = _run_writeback(monkeypatch, rows)
    _tenant_id, videos = called["early_signal"]
    assert videos == [
        {"internal_video_id": "internal-1", "ctr_48h": 4.2},
        {"internal_video_id": "internal-2", "ctr_48h": 3.9},
    ]


def test_both_flywheels_fire_independently_for_the_same_video(monkeypatch):
    """A video that clears BOTH the C56 pattern-flywheel bar (ctr +
    impressions>=1000) and the C58 early-signal bar (ctr_48h present) in
    the same sync must queue for both -- they are independent triggers."""
    rows = [_row(ctr_48h=4.2, early_signal_at=None, ctr_percent=5.0, impressions=2000,
                  launch_pattern_analyzed_at=None)]
    _executed, called = _run_writeback(monkeypatch, rows)
    assert called["launch"] is not None
    assert called["early_signal"] is not None
