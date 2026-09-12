"""Run All must expose an incomplete stage rather than report completion."""
import asyncio
import sys
import types
from unittest.mock import AsyncMock, patch

import actions


def _build(*, thumbnail_result=None, saved_thumbnail=None, step_result=None):
    video = {"status": "ready_for_thumbnail", "render_mode": "static_docu", "thumbnail_url": None}
    statuses = []
    advances = []
    calls = []

    class Executor:
        async def _get_video(self, _id):
            return dict(video)

        async def run_next_step(self, _id):
            calls.append(video["status"])
            return step_result or {"status": "needs_approval"}

        async def run_thumbnail(self, _id):
            if isinstance(thumbnail_result, Exception):
                raise thumbnail_result
            video["thumbnail_url"] = saved_thumbnail
            return thumbnail_result or {"status": "completed"}

    async def fetch(query, *_args):
        if "FROM scripts" in query:
            return None
        return {"status": video["status"], "pipeline_stages": None}

    async def execute(query, *args):
        if "UPDATE videos SET status=" in query:
            advances.append(args[0])
            video["status"] = "complete"
        return "UPDATE 1"

    pe = types.ModuleType("pipeline_executor")
    pe.PipelineExecutor = lambda _tenant: Executor()
    route = types.ModuleType("routes.pipeline")
    route._set_task_status = lambda _id, status, msg, **_kw: statuses.append((status, msg))
    route._clear_task_status = lambda *_a: None
    claims = types.ModuleType("generation_claims")
    claims.release = AsyncMock()
    with patch.dict(sys.modules, {"pipeline_executor": pe, "routes.pipeline": route, "generation_claims": claims}), \
         patch.object(actions, "fetch_one", fetch), patch.object(actions, "execute", execute), \
         patch("asyncio.sleep", AsyncMock()):
        asyncio.run(actions.make_autobuild_step("tenant", "video", target="finish")())
    return statuses, advances, calls


def test_failed_thumbnail_cannot_advance_to_render():
    statuses, advances, _ = _build(thumbnail_result={"status": "failed", "error": "Provider unavailable"})
    assert statuses[-1] == ("failed", "Provider unavailable")
    assert advances == []


def test_success_without_persisted_thumbnail_cannot_advance():
    statuses, advances, _ = _build()
    assert statuses[-1][0] == "failed"
    assert "saved image" in statuses[-1][1]
    assert advances == []


def test_thumbnail_exception_is_visible():
    statuses, advances, _ = _build(thumbnail_result=RuntimeError("timeout"))
    assert statuses[-1] == ("failed", "Thumbnail failed: timeout")
    assert advances == []


def test_saved_thumbnail_allows_advancement():
    _statuses, advances, _calls = _build(saved_thumbnail="https://example.test/thumb.jpg")
    assert advances


def test_review_failure_keeps_the_actual_reason():
    statuses, advances, calls = _build(step_result={"status": "needs_review", "message": "Wrong carrier identity"})
    assert statuses[-1] == ("failed", "Wrong carrier identity")
    assert advances == []
    assert len(calls) == 1


def test_no_progress_is_failure_not_completion():
    statuses, advances, calls = _build(step_result={"status": "completed"})
    assert statuses[-1][0] == "failed"
    assert "without advancing" in statuses[-1][1]
    assert advances == []
    assert len(calls) == 1
