"""Stash-proof test for UX-2 (2026-07-30): the AUTOMATIC roster reference
sweep must report live progress the same way the MANUAL "Re-check missing"
button does.

Fresh-eyes audit finding (commit f615772a gave the manual recheck path a
climbing "N/23 verified so far" + spinner, but that path was never really
broken): the automatic sweep dispatched from run_research/
accept_submitted_research (static_docu.py's dispatch_roster_prefetch ->
_run_tracked_roster_prefetch) only ever wrote ONE static message
("Sweeping roster reference photos") at the very start of a background_tasks
row, and one final summary at the very end. Nothing climbed in between for
the whole ~10-minute sweep, and the frontend's `bridgeIsRosterSweep` check
(RosterStagePanel.tsx) matched only the literal substring "machine
reference" — a phrase only the MANUAL path's message ever contained. A user
watching an auto-dispatched sweep saw no spinner and every missing card sat
on the frozen "missing + paste a URL" form the whole time — exactly the
frozen-panel incident the feature exists to prevent, just reached via the
path that actually matters.

Fix (see static_docu.py's UX-2 note above _run_tracked_roster_prefetch, and
routes/pipeline.py's UX-2 notes near _set_task_status/_get_task_status_async/
get_task_status):
  1. _run_tracked_roster_prefetch now runs a progress side-car
     (_report_tracked_prefetch_progress) that republishes "Sweeping machine
     references — N/Y verified so far" onto the SAME background_tasks row
     it registered, every ~5s — mirroring recheck_roster_references' own
     side-car, but writing directly to that task_id's row rather than
     through _set_task_status/_db_persist_task (deliberately off-limits per
     the C12 note in static_docu.py — see 4031bc02).
  2. Both the manual recheck and the automatic sweep now tag their task
     status with a structured task_type="roster_prefetch" field, threaded
     through _get_task_status_async's DB fallback and GET /task/{video_id},
     so the frontend can detect "a roster sweep is running" off a
     structured field instead of only ever string-matching `message`.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_static_docu_roster_auto_sweep_progress.py -q
"""
import asyncio
import os
import sys
import uuid
from pathlib import Path

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PIPELINE_ROOT = _REPO_ROOT / "skills" / "video-pipeline"
if str(_PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_ROOT))

import static_docu  # noqa: E402


@pytest.mark.asyncio
async def test_auto_sweep_publishes_climbing_progress_on_its_own_task_row(monkeypatch):
    """Without the fix: _run_tracked_roster_prefetch never runs a progress
    side-car at all, so no "UPDATE background_tasks SET message=..." call
    for a climbing count ever happens mid-sweep — only the opening INSERT
    and the final close-out UPDATE. With the fix: at least one progress
    update lands on the SAME task_id row while the sweep is still running,
    carrying an honest N/Y count."""
    video_id, tenant_id = str(uuid.uuid4()), str(uuid.uuid4())
    fake_task_id = str(uuid.uuid4())
    roster = ["Boeing XB-15", "Northrop XB-35", "Convair YB-60"]
    video_row = {
        "id": video_id,
        "render_mode": "static_docu",
        "research_payload": {"documentary_style": "designed_vs_used", "unit_roster": roster},
    }

    inserted = []
    progress_updates = []
    closeout_updates = []

    async def fake_fetch_one(query, *args):
        if "INSERT INTO background_tasks" in query:
            inserted.append(args)
            return {"id": fake_task_id}
        if "FROM videos" in query:
            return dict(video_row)
        return None

    async def fake_fetch_all(query, *args):
        if "FROM static_reference_cache" in query:
            return []  # nothing verified yet in this test's short window
        return []

    async def fake_execute(query, *args):
        # The progress side-car's UPDATE binds 2 params (message, task_id);
        # the final close-out binds 3 (status, message, task_id) — both
        # queries contain "status=" as text (the side-car's WHERE clause has
        # "status='running'"), so arg count is the reliable discriminator,
        # not a substring of the SQL text.
        if "UPDATE background_tasks" not in query:
            return None
        if len(args) == 2:
            progress_updates.append(args)
        elif len(args) == 3:
            closeout_updates.append(args)
        return None

    real_sleep = asyncio.sleep

    async def fast_sleep(_seconds):
        # Keep the side-car's internal 5s cadence from actually taking 5s in
        # a test, while still performing a REAL suspend so the event loop
        # can hand control back and forth between the sweep and the
        # side-car (a no-op stub with no await would starve the loop).
        await real_sleep(0)

    async def fake_prefetch(vid, tid):
        assert vid == video_id and tid == tenant_id
        # Give the progress side-car several real event-loop turns to run
        # before the "sweep" finishes — a real sweep takes ~10 minutes
        # (serial, Wikimedia-throttled); this stands in for that window.
        for _ in range(5):
            await real_sleep(0.01)
        return {"status": "completed", "roster_count": 3, "verified": 0, "missed": 3}

    monkeypatch.setattr(static_docu, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(static_docu, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(static_docu, "execute", fake_execute)
    monkeypatch.setattr(static_docu, "prefetch_roster_references", fake_prefetch)
    monkeypatch.setattr(asyncio, "sleep", fast_sleep)

    await static_docu._run_tracked_roster_prefetch(video_id, tenant_id)

    assert len(inserted) == 1, "the sweep must still register its background_tasks row"
    assert len(closeout_updates) == 1, "the sweep must still close its row out on completion"

    # THE bug this test pins: before the fix, this list is always empty —
    # _run_tracked_roster_prefetch had no progress side-car at all, so
    # nothing but the opening INSERT and the final close-out ever touched
    # the row for the whole sweep.
    assert progress_updates, (
        "the automatic sweep must publish at least one progress update "
        "mid-sweep, exactly like the manual recheck path already does"
    )
    assert any("0/3 verified so far" in msg for (msg, _task_id) in progress_updates), (
        f"expected an honest N/Y climbing count in a progress message, got: {progress_updates}"
    )
    # UX-2's other half: the message must still carry the same
    # "machine reference" phrasing the frontend's substring fallback keys
    # off of, so a rollback of the task_type plumbing alone wouldn't
    # silently reopen the bug.
    assert all("machine reference" in msg.lower() for (msg, _task_id) in progress_updates)


@pytest.mark.asyncio
async def test_auto_sweep_task_type_is_visible_through_the_db_fallback_status_read(monkeypatch):
    """The frontend's GET /task/{video_id} poll (routes/pipeline.py's
    get_task_status -> _get_task_status_async) must be able to see the
    automatic sweep's task_type — this is the structured signal
    RosterStagePanel.tsx now keys off of instead of a brittle substring
    match on `message`. Simulates exactly the real shape: no in-memory
    _running_tasks entry for this video (the auto sweep never touches
    that dict — see the C12 note), only a background_tasks row."""
    import importlib

    pipeline_routes = importlib.import_module("routes.pipeline")

    video_id, tenant_id = str(uuid.uuid4()), str(uuid.uuid4())

    # No in-memory entry for this (tenant, video) — mirrors reality: the
    # auto sweep never writes into _running_tasks.
    pipeline_routes._running_tasks.pop((tenant_id, video_id), None)

    async def fake_fetch_one(query, *args):
        if "FROM background_tasks" in query:
            return {
                "status": "running",
                "message": "Sweeping machine references — 4/23 verified so far",
                "error_message": None,
                "task_type": "roster_prefetch",
            }
        return None

    monkeypatch.setattr(pipeline_routes, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(pipeline_routes._time, "time", lambda: 150.0)

    task = await pipeline_routes._get_task_status_async(video_id, tenant_id)

    assert task is not None
    assert task["status"] == "running"
    assert task["task_type"] == "roster_prefetch"


@pytest.mark.asyncio
async def test_queue_terminal_row_clears_stale_in_memory_running_status(monkeypatch):
    import importlib

    pipeline_routes = importlib.import_module("routes.pipeline")
    video_id, tenant_id = "vid-terminal", "tenant-terminal"
    key = (tenant_id, video_id)
    pipeline_routes._running_tasks[key] = {
        "status": "running",
        "message": "Script generation in progress",
        "error": None,
        "lane": "main",
        "task_type": "pipeline",
        "queue_dispatched": True,
        "started_at": 100.0,
    }

    async def fake_fetch_one(query, *args):
        if "completed_at >= to_timestamp" in query:
            assert args == (video_id, tenant_id, 100.0)
            return {"status": "completed", "completed_at": "later"}
        if "status IN ('pending', 'running')" in query:
            return None
        raise AssertionError(query)

    monkeypatch.setattr(pipeline_routes, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(pipeline_routes._time, "time", lambda: 150.0)

    task = await pipeline_routes._get_task_status_async(video_id, tenant_id)

    assert task is None
    assert key not in pipeline_routes._running_tasks


@pytest.mark.asyncio
async def test_terminal_queue_row_unblocks_next_stage_without_restart(monkeypatch):
    import importlib
    from unittest.mock import AsyncMock

    pipeline_routes = importlib.import_module("routes.pipeline")
    video_id, tenant_id = "vid-next", "tenant-next"
    key = (tenant_id, video_id)
    pipeline_routes._running_tasks[key] = {
        "status": "running",
        "message": "Script generation in progress",
        "error": None,
        "lane": "main",
        "task_type": "pipeline",
        "queue_dispatched": True,
        "started_at": 200.0,
    }

    async def fake_fetch_one(query, *args):
        assert "completed_at >= to_timestamp" in query
        return {"status": "failed", "completed_at": "later"}

    monkeypatch.setattr(pipeline_routes, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(pipeline_routes._time, "time", lambda: 250.0)
    monkeypatch.setattr(
        pipeline_routes.generation_claims,
        "is_blocked",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        pipeline_routes.drain_mode,
        "assert_accepting_new_work",
        AsyncMock(return_value=None),
    )

    assert await pipeline_routes._is_task_active(video_id, tenant_id) is False
    assert key not in pipeline_routes._running_tasks


def test_new_run_gets_a_fresh_in_memory_start_time(monkeypatch):
    import importlib

    pipeline_routes = importlib.import_module("routes.pipeline")
    video_id, tenant_id = "vid-fresh", "tenant-fresh"
    key = (tenant_id, video_id)
    pipeline_routes._running_tasks[key] = {
        "status": "failed",
        "message": "old run failed",
        "error": "old run failed",
        "lane": "main",
        "task_type": "pipeline",
        "started_at": 10.0,
    }
    monkeypatch.setattr(pipeline_routes._time, "time", lambda: 20.0)

    pipeline_routes._set_task_status(
        video_id,
        "running",
        "new run",
        tenant_id=tenant_id,
    )

    assert pipeline_routes._running_tasks[key]["started_at"] == 20.0
