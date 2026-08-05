"""D15-3 (closes D15-1's "one road" gap): proves backend/routes/pipeline.py's
POST /storyboard-images/{video_id} and POST /coverage-images/{video_id} now
dispatch through PipelineExecutor.run_storyboard_sheet / run_coverage_images
instead of importing and calling scripts.coverage_to_app's
generate_storyboard_sheet_for_scene / generate_coverage_for_video directly —
the same wrappers chat's "storyboards"/"images" verbs (actions.py), the MCP
tools, and ClaudeOrchestrator's autonomous dispatch already go through.

Proves, with NO live DB and NO paid calls:

  (a) Source-level: the direct generate_* functions are no longer imported
      or called anywhere in either route function's source, and
      PipelineExecutor IS referenced — a static, unambiguous check that
      can't be fooled by a code path that only sometimes takes the new
      route (grep-on-source, not behavior-on-one-input).
  (b) Live dispatch: calling each route directly (FastAPI dependency
      injection bypassed — fetch_one/PipelineExecutor/_is_task_active are
      monkeypatched at the routes.pipeline module boundary) shows the
      captured background task calls PipelineExecutor(tenant_id).
      run_storyboard_sheet(...)/.run_coverage_images(...) with EVERY
      parameter the route received (scene, beat, plan_only, and a live
      progress callable) — not a subset.
  (c) Response-shape parity: whatever dict the executor mock returns
      becomes the task's terminal status/message/error exactly (success
      and failure shapes) via the SAME _set_task_status mapping code this
      chunk did not touch — proving the swap from a direct call's return
      value to the executor's return value is transparent to the poller.
  (d) Background-task semantics preserved: the route returns its "running"
      PipelineResponse BEFORE the draw call ever runs (the captured
      background task is invoked separately, after asserting the response) —
      a button that used to return fast still returns fast.
  (e) Missing-video (404): the executor is never constructed at all — the
      existing fetch_one-then-404 gate still runs first, unchanged.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_d15_3_route_dispatch.py -q
"""
from __future__ import annotations

import asyncio
import inspect
import os
import sys
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import routes.pipeline as rp  # noqa: E402

TENANT = "tenant-d15-3-route"
VIDEO = "video-d15-3-route"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _video_row(**extra) -> dict:
    row = {"id": VIDEO, "status": "ready_for_images"}
    row.update(extra)
    return row


class _FakeBackgroundTasks:
    """Stands in for FastAPI's BackgroundTasks: captures the callable passed
    to add_task without running it — same as the real thing (which runs
    tasks AFTER the response is sent), so a test can assert the route
    returned its response BEFORE the draw ever starts."""

    def __init__(self):
        self.tasks: list = []

    def add_task(self, fn, *args, **kwargs):
        self.tasks.append((fn, args, kwargs))


class _FakeExecutor:
    """Stands in for PipelineExecutor(tenant_id) — records the tenant_id it
    was constructed with and exposes run_storyboard_sheet/run_coverage_images
    as AsyncMocks so a test can assert exact call kwargs and control the
    returned dict. The route constructs this INSIDE the background task (not
    before), so a test that needs a non-default return value must set the
    class-level `next_*_result` BEFORE running the captured task, not after —
    __init__ reads it at construction time."""

    instances: list = []
    next_storyboard_result: dict = {"status": "completed", "message": "ok"}
    next_coverage_result: dict = {"status": "completed", "message": "ok"}

    def __init__(self, tenant_id):
        self.tenant_id = tenant_id
        self.run_storyboard_sheet = AsyncMock(return_value=dict(_FakeExecutor.next_storyboard_result))
        self.run_coverage_images = AsyncMock(return_value=dict(_FakeExecutor.next_coverage_result))
        _FakeExecutor.instances.append(self)


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    _FakeExecutor.instances.clear()
    _FakeExecutor.next_storyboard_result = {"status": "completed", "message": "ok"}
    _FakeExecutor.next_coverage_result = {"status": "completed", "message": "ok"}
    rp._running_tasks.clear()
    monkeypatch.setattr(rp, "PipelineExecutor", _FakeExecutor)
    monkeypatch.setattr(rp, "_is_task_active", AsyncMock(return_value=False))
    monkeypatch.setattr(rp, "_db_persist_task", AsyncMock(return_value=None))
    # Every route's _run() closure ends with `finally: await asyncio.sleep(30);
    # _clear_task_status(...)` (the real 30s the UI status pill lingers for).
    # A test that awaits the closure to completion would otherwise burn a
    # real 30s AND have the entry it wants to assert on wiped out from under
    # it by the clear — patch both so _running_tasks[key] reflects the
    # terminal status right after the closure returns, the same way the real
    # process's in-memory state looks for the ~30s window a real poller
    # would actually read it in.
    monkeypatch.setattr(rp.asyncio, "sleep", AsyncMock(return_value=None))
    monkeypatch.setattr(rp, "_clear_task_status", lambda *a, **k: None)
    yield


# =============================================================================
# (a) Source-level: direct function calls are gone, PipelineExecutor is used.
# =============================================================================

def test_storyboard_images_route_source_no_longer_calls_the_direct_function():
    # Code-shape check, not a bare substring match — the route's own D15-3
    # comments legitimately NAME generate_storyboard_sheet_for_scene in prose
    # (explaining what used to happen), so this checks for the actual import
    # statement and call expression, not any mention of the identifier.
    src = inspect.getsource(rp.run_storyboard_images)
    assert "from scripts.coverage_to_app import generate_storyboard_sheet_for_scene" not in src
    assert "generate_storyboard_sheet_for_scene(" not in src
    assert "PipelineExecutor" in src and "executor.run_storyboard_sheet(" in src


def test_coverage_images_route_source_no_longer_calls_the_direct_function():
    src = inspect.getsource(rp.run_coverage_images)
    assert "from scripts.coverage_to_app import generate_coverage_for_video" not in src
    assert "generate_coverage_for_video(" not in src
    assert "PipelineExecutor" in src and "executor.run_coverage_images(" in src


# =============================================================================
# (b)+(c)+(d) Live dispatch, response-shape parity, fast return.
# =============================================================================

def test_storyboard_images_route_dispatches_through_executor_with_every_param(monkeypatch):
    async def _fake_fetch_one(query, *args):
        return _video_row()

    monkeypatch.setattr(rp, "fetch_one", _fake_fetch_one)

    bg = _FakeBackgroundTasks()
    response = _run(rp.run_storyboard_images(
        VIDEO, bg, scene=3, beat=2, plan_only=False, tenant_id=TENANT))

    # (d) fast return: the response came back before the draw call ran.
    assert response.status == "running"
    assert len(bg.tasks) == 1
    assert len(_FakeExecutor.instances) == 0, "the executor must be constructed INSIDE the background task, not before"

    fn, args, kwargs = bg.tasks[0]
    _run(fn(*args, **kwargs))

    assert len(_FakeExecutor.instances) == 1
    executor = _FakeExecutor.instances[0]
    assert executor.tenant_id == TENANT
    executor.run_storyboard_sheet.assert_awaited_once()
    call = executor.run_storyboard_sheet.await_args
    assert call.args == (VIDEO,)
    assert call.kwargs["scene"] == 3
    assert call.kwargs["beat"] == 2
    assert call.kwargs["plan_only"] is False
    assert callable(call.kwargs["progress"])

    # (c) response-shape parity: the mock's dict became the terminal status.
    entry = rp._running_tasks[(TENANT, VIDEO)]
    assert entry["status"] == "completed"
    assert entry["message"] == "ok"


def test_storyboard_images_route_plan_only_and_beat_both_reach_the_executor(monkeypatch):
    """The two live UI buttons this chunk was most at risk of silently
    breaking (ScenesWorkspaceTab.tsx:861 plan_only, :875 beat) — proves both
    still reach the executor with their param preserved, not silently
    dropped or routed around it."""
    async def _fake_fetch_one(query, *args):
        return _video_row()

    monkeypatch.setattr(rp, "fetch_one", _fake_fetch_one)

    bg = _FakeBackgroundTasks()
    _run(rp.run_storyboard_images(VIDEO, bg, scene=5, plan_only=True, tenant_id=TENANT))
    fn, args, kwargs = bg.tasks[0]
    _run(fn(*args, **kwargs))
    executor = _FakeExecutor.instances[-1]
    call = executor.run_storyboard_sheet.await_args
    assert call.kwargs["plan_only"] is True
    assert call.kwargs["beat"] is None


def test_coverage_images_route_dispatches_through_executor_with_progress(monkeypatch):
    async def _fake_fetch_one(query, *args):
        return _video_row()

    monkeypatch.setattr(rp, "fetch_one", _fake_fetch_one)

    bg = _FakeBackgroundTasks()
    response = _run(rp.run_coverage_images(VIDEO, bg, scene=4, tenant_id=TENANT))

    assert response.status == "running"
    assert len(_FakeExecutor.instances) == 0

    fn, args, kwargs = bg.tasks[0]
    _run(fn(*args, **kwargs))

    executor = _FakeExecutor.instances[0]
    assert executor.tenant_id == TENANT
    executor.run_coverage_images.assert_awaited_once()
    call = executor.run_coverage_images.await_args
    assert call.args == (VIDEO,)
    assert call.kwargs["scene"] == 4
    assert callable(call.kwargs["progress"])

    entry = rp._running_tasks[(TENANT, VIDEO)]
    assert entry["status"] == "completed"


def test_coverage_images_route_failure_result_shape_flows_through_unchanged(monkeypatch):
    """The executor's failure dict (e.g. the voicefix money gate this chunk
    NEWLY closes for this button — see report) maps to a failed task status
    exactly like the old direct call's failure dict always did — the
    _set_task_status mapping code is untouched by this chunk.

    The mocked error is wrapped with error_utils.user_facing(), matching what
    the REAL pipeline_executor.py::run_coverage_images now returns for this
    exact gate (this chunk's D15-3 fix, made after discovering — via this
    very test, before the fix — that an UNMARKED message gets flattened to
    the generic "Something went wrong" fallback by _set_task_status's
    humanize_error() funnel). This test proves the route+_set_task_status
    path preserves a user_facing-marked message end to end; it is not
    re-testing humanize_error's own funnel behavior for an unmarked string,
    which is pre-existing, unrelated to this chunk, and unchanged."""
    async def _fake_fetch_one(query, *args):
        return _video_row()

    monkeypatch.setattr(rp, "fetch_one", _fake_fetch_one)
    from error_utils import user_facing
    _FakeExecutor.next_coverage_result = {
        "status": "failed",
        "error": user_facing(
            "Voice generation must complete before image generation. Missing voice for scene 1."),
    }

    bg = _FakeBackgroundTasks()
    _run(rp.run_coverage_images(VIDEO, bg, scene=1, tenant_id=TENANT))
    fn, args, kwargs = bg.tasks[0]

    _run(fn(*args, **kwargs))

    entry = rp._running_tasks[(TENANT, VIDEO)]
    assert entry["status"] == "failed"
    assert "Missing voice for scene 1" in entry["error"]
    assert "[[user-facing]]" not in entry["error"], "the marker prefix itself must never leak to the UI"


# =============================================================================
# (e) Missing video: 404 before the executor is ever touched.
# =============================================================================

def test_storyboard_images_route_404s_before_constructing_the_executor(monkeypatch):
    async def _fake_fetch_one(query, *args):
        return None

    monkeypatch.setattr(rp, "fetch_one", _fake_fetch_one)

    bg = _FakeBackgroundTasks()
    with pytest.raises(HTTPException) as exc_info:
        _run(rp.run_storyboard_images(VIDEO, bg, tenant_id=TENANT))
    assert exc_info.value.status_code == 404
    assert bg.tasks == []
    assert _FakeExecutor.instances == []


def test_coverage_images_route_404s_before_constructing_the_executor(monkeypatch):
    async def _fake_fetch_one(query, *args):
        return None

    monkeypatch.setattr(rp, "fetch_one", _fake_fetch_one)

    bg = _FakeBackgroundTasks()
    with pytest.raises(HTTPException) as exc_info:
        _run(rp.run_coverage_images(VIDEO, bg, tenant_id=TENANT))
    assert exc_info.value.status_code == 404
    assert bg.tasks == []
    assert _FakeExecutor.instances == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
