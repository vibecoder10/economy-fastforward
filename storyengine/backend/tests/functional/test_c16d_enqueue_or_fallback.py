"""Tests for C16d (checklist §S7-4 HIGH fix, docs/reports/2026-07-17-
storyengine-agent-audit-findings.md §S7): routes/pipeline.py's
_enqueue_or_fallback no longer hardcodes attempt=1, and no longer silently
no-ops when arq refuses a duplicate enqueue.

Before this fix:
  - `attempt = 1` on every call meant arq's job_id (f"{stage}:{video_id}:1")
    collided with itself for 24h (WorkerSettings.keep_result=86400) on every
    legitimate SECOND run of the same stage — a real retry or an explicit
    Regenerate silently no-op'd (enqueue_stage returned None, and the
    `if job_id:` branch just fell through to `return` with nothing
    persisted and no error raised — the caller got a 200 "running" response
    for a job that was never actually queued).
  - Fix (a): attempt is derived from MAX(attempt) already recorded for this
    (video_id, stage) in background_tasks + 1 — the same source main.py's
    restart-recovery already reads.
  - Fix (b): when enqueue_stage STILL returns None after that (a genuine
    concurrent duplicate, the residual race the attempt fix can't close),
    _enqueue_or_fallback now raises the same 409 "Task already running"
    HTTPException the `_is_task_active` gates already use elsewhere, instead
    of silently returning.

Also pins: `**stage_kwargs` (S7-3's `force` for the thumbnail stage) reaches
enqueue_stage, and the pre-existing degraded-queue fallback (arq pool absent,
or enqueue raises a genuine connection-style Exception) is unchanged — it
must NOT be swallowed by the new 409 path (only the deliberate dedup-hit
HTTPException skips the BackgroundTasks fallback).

Stub set mirrors tests/functional/test_cross_tenant_task_isolation.py so this
file imports routes.pipeline without a real DB/vault/pipeline_executor.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c16d_enqueue_or_fallback.py -q
"""
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, __import__("os").path.dirname(
    __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))))

for stub_mod in ("database", "auth"):
    if stub_mod not in sys.modules:
        m = types.ModuleType(stub_mod)
        if stub_mod == "database":
            async def _noop(*a, **kw):
                return None
            m.fetch_one = _noop
            m.fetch_all = _noop
            m.execute = _noop
        if stub_mod == "auth":
            async def _get_tenant_id(*a, **kw):
                return "stub"
            m.get_tenant_id = _get_tenant_id
        sys.modules[stub_mod] = m

if "pipeline_executor" not in sys.modules:
    pe = types.ModuleType("pipeline_executor")

    class _Stub:
        def __init__(self, *a, **kw):
            pass

    pe.PipelineExecutor = _Stub
    sys.modules["pipeline_executor"] = pe

from fastapi import HTTPException  # noqa: E402

from routes import pipeline as pipeline_mod  # noqa: E402


def _fake_request(arq_pool):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(arq=arq_pool)))


class _FakeBackgroundTasks:
    def __init__(self):
        self.tasks = []

    def add_task(self, fn, *a, **kw):
        self.tasks.append((fn, a, kw))


@pytest.mark.asyncio
async def test_attempt_derived_from_prior_background_tasks_rows(monkeypatch):
    """2 prior rows recorded for (video, stage) -> the next enqueue uses
    attempt=3, not the old hardcoded 1."""
    captured = {}

    async def fake_fetch_one(query, *args):
        assert "MAX(attempt)" in query
        assert args == ("vid1", "tenant1", "thumbnail")
        return {"n": 2}

    async def fake_enqueue_stage(pool, stage, video_id, tenant_id, attempt, **kwargs):
        captured["attempt"] = attempt
        captured["kwargs"] = kwargs
        return "thumbnail:vid1:3"

    persisted = []

    async def fake_db_persist_task(*a, **kw):
        persisted.append((a, kw))

    monkeypatch.setattr(pipeline_mod, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(pipeline_mod, "enqueue_stage", fake_enqueue_stage)
    monkeypatch.setattr(pipeline_mod, "db_persist_task", fake_db_persist_task)

    bg = _FakeBackgroundTasks()
    request = _fake_request(arq_pool=object())

    await pipeline_mod._enqueue_or_fallback(
        request, bg, "thumbnail", "vid1", "tenant1", AsyncMock(), force=True)

    assert captured["attempt"] == 3
    assert captured["kwargs"] == {"force": True}, "stage_kwargs (S7-3's force) must reach enqueue_stage"
    assert len(persisted) == 1, "a successful enqueue must still persist the pending row"
    assert bg.tasks == [], "arq succeeded — must not ALSO run the in-process fallback"


@pytest.mark.asyncio
async def test_attempt_defaults_to_one_with_no_prior_rows(monkeypatch):
    """No background_tasks history at all -> attempt=1, same as before."""
    captured = {}

    async def fake_fetch_one(query, *args):
        return {"n": 0}

    async def fake_enqueue_stage(pool, stage, video_id, tenant_id, attempt, **kwargs):
        captured["attempt"] = attempt
        return "script:vid1:1"

    monkeypatch.setattr(pipeline_mod, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(pipeline_mod, "enqueue_stage", fake_enqueue_stage)
    monkeypatch.setattr(pipeline_mod, "db_persist_task", AsyncMock())

    await pipeline_mod._enqueue_or_fallback(
        _fake_request(object()), _FakeBackgroundTasks(), "script", "vid1", "tenant1", AsyncMock())

    assert captured["attempt"] == 1


@pytest.mark.asyncio
async def test_dedup_hit_raises_honest_409_not_silent_success(monkeypatch):
    """enqueue_stage returns None (arq's own job_id dedup refused a genuine
    concurrent duplicate) -> the caller must see an honest 409, not a
    silent 200 with nothing queued and no error."""
    async def fake_fetch_one(query, *args):
        return {"n": 0}

    async def fake_enqueue_stage(*a, **kw):
        return None  # arq refused — a job with this exact key already exists

    persisted = []

    async def fake_db_persist_task(*a, **kw):
        persisted.append((a, kw))

    monkeypatch.setattr(pipeline_mod, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(pipeline_mod, "enqueue_stage", fake_enqueue_stage)
    monkeypatch.setattr(pipeline_mod, "db_persist_task", fake_db_persist_task)

    bg = _FakeBackgroundTasks()
    with pytest.raises(HTTPException) as exc_info:
        await pipeline_mod._enqueue_or_fallback(
            _fake_request(object()), bg, "thumbnail", "vid1", "tenant1", AsyncMock())

    assert exc_info.value.status_code == 409
    assert "already running" in exc_info.value.detail.lower()
    assert persisted == [], "a refused enqueue must not persist a fake pending row"
    assert bg.tasks == [], (
        "the dedup-hit HTTPException must not fall through to the in-process "
        "fallback — that would create a REAL duplicate run alongside whatever "
        "arq already has queued/running under that job_id")


@pytest.mark.asyncio
async def test_generic_arq_failure_still_falls_back_to_background_tasks(monkeypatch):
    """Pre-existing degraded-queue behavior (S7-7) must survive: a genuine
    connection-style exception from enqueue_stage (Redis down mid-request)
    still falls back to BackgroundTasks — only the deliberate dedup-hit
    HTTPException skips the fallback."""
    async def fake_fetch_one(query, *args):
        return {"n": 0}

    async def fake_enqueue_stage(*a, **kw):
        raise ConnectionError("redis unreachable")

    monkeypatch.setattr(pipeline_mod, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(pipeline_mod, "enqueue_stage", fake_enqueue_stage)
    monkeypatch.setattr(pipeline_mod, "db_persist_task", AsyncMock())

    bg = _FakeBackgroundTasks()
    fallback = AsyncMock()
    await pipeline_mod._enqueue_or_fallback(
        _fake_request(object()), bg, "thumbnail", "vid1", "tenant1", fallback)

    assert len(bg.tasks) == 1 and bg.tasks[0][0] is fallback


@pytest.mark.asyncio
async def test_no_arq_pool_falls_back_without_querying_attempt(monkeypatch):
    """No arq pool configured at all (the common prod state today, per the
    live background_tasks scan: 0 of 468 rows carry a job_id) -> straight to
    BackgroundTasks, no attempt lookup, no enqueue_stage call."""
    async def _boom(*a, **kw):
        raise AssertionError("must not query attempt history when arq isn't even configured")

    monkeypatch.setattr(pipeline_mod, "fetch_one", _boom)
    monkeypatch.setattr(pipeline_mod, "enqueue_stage", _boom)

    bg = _FakeBackgroundTasks()
    fallback = AsyncMock()
    await pipeline_mod._enqueue_or_fallback(
        _fake_request(arq_pool=None), bg, "thumbnail", "vid1", "tenant1", fallback)

    assert len(bg.tasks) == 1 and bg.tasks[0][0] is fallback


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
