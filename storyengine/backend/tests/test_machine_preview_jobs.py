import sys
import types
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest


class _Connection:
    def __init__(self, job, claim=True):
        self.job = job
        self.claim = claim

    async def fetchrow(self, query, *args):
        if "SET status='running'" in query:
            if self.job["status"] != "pending":
                return None
            self.job["status"] = "running"
            return {key: self.job[key] for key in ("id", "tenant_id", "video_id", "machine")}
        if "FROM generation_claims" in query:
            return {"ok": True} if self.claim else None
        return None

    async def fetchval(self, query, *args):
        return self.job["status"] in {"completed", "needs_review", "failed", "cancelled"}

    async def execute(self, query, *args):
        if "machine_preview_jobs SET status=$2" in query:
            self.job["status"] = args[1]
            self.job["result"] = args[2]
            self.job["error"] = args[3]
            return "UPDATE 1"
        if "SET status='failed'" in query:
            self.job["status"] = "failed"
            self.job["error"] = args[1]
            return "UPDATE 1"
        return "UPDATE 1"


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    @asynccontextmanager
    async def acquire(self):
        yield self.conn


class _RouteConnection:
    """Small asyncpg-shaped connection for exercising the actual route."""
    def __init__(self, video=True):
        self.video = video
        self.queries = []

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def fetchrow(self, query, *args):
        self.queries.append((query, args))
        if "SELECT id FROM videos" in query:
            return {"id": args[0]} if self.video else None
        return None

    async def execute(self, query, *args):
        self.queries.append((query, args))
        return "INSERT 0 1"


class _QueueRequest:
    def __init__(self, arq):
        self.app = types.SimpleNamespace(state=types.SimpleNamespace(arq=arq))


def _job_request(pipeline, machine="SS-2 USS Plunger", request_id=None):
    return pipeline.MachineScriptPreviewJobRequest(
        machine=machine,
        confirmed_paid_run=True,
        request_id=request_id or uuid.uuid4(),
    )


def _ready_executor():
    class Executor:
        def __init__(self, _tenant):
            pass

        async def check_machine_script_preview_readiness(self, _video_id, _machine):
            return {"ready": True, "status": "completed"}
    return Executor


async def _false():
    return False


@pytest.mark.asyncio
async def test_run_job_maps_unpassed_preview_to_needs_review_and_releases_exact_claim(monkeypatch):
    import machine_preview_jobs as jobs
    state = {"id": "job-1", "tenant_id": "tenant-1", "video_id": "video-1", "machine": "SS-2 USS Plunger", "status": "pending"}
    async def get_pool(): return _Pool(_Connection(state))
    monkeypatch.setattr(jobs, "get_pool", get_pool)
    activity = []
    async def persist(*args, **kwargs): activity.append((args, kwargs))
    monkeypatch.setattr(jobs, "db_persist_task", persist)
    released = []
    async def release(*args): released.append(args)
    monkeypatch.setattr(jobs.generation_claims, "release_owned", release)
    monkeypatch.setitem(sys.modules, "cancel_registry", types.SimpleNamespace(is_cancel_requested=lambda *_: _false()))
    class Executor:
        def __init__(self, tenant): assert tenant == "tenant-1"
        async def run_machine_script_preview(self, video_id, machine):
            assert (video_id, machine) == ("video-1", "SS-2 USS Plunger")
            return {"status": "completed", "preview": {"passed": False}, "warnings": ["editorial"]}
    monkeypatch.setitem(sys.modules, "pipeline_executor", types.SimpleNamespace(PipelineExecutor=Executor))
    result = await jobs.run_job("job-1")
    assert result["status"] == "needs_review"
    assert state["status"] == "needs_review"
    assert [args[3] for args, _ in activity] == ["running", "failed"]
    assert released == [("tenant-1", "video-1", "main", "machine-preview:job-1")]


@pytest.mark.asyncio
async def test_run_job_nonpending_duplicate_does_not_call_executor(monkeypatch):
    import machine_preview_jobs as jobs
    state = {"id": "job-2", "tenant_id": "tenant-1", "video_id": "video-1", "machine": "SS-2 USS Plunger", "status": "running"}
    async def get_pool(): return _Pool(_Connection(state))
    monkeypatch.setattr(jobs, "get_pool", get_pool)
    assert await jobs.run_job("job-2") == {"status": "ignored", "job_id": "job-2"}


@pytest.mark.asyncio
async def test_run_job_provider_failure_is_terminal_and_does_not_retry(monkeypatch):
    import machine_preview_jobs as jobs
    state = {"id": "job-3", "tenant_id": "tenant-1", "video_id": "video-1", "machine": "SS-2 USS Plunger", "status": "pending"}
    async def get_pool(): return _Pool(_Connection(state))
    monkeypatch.setattr(jobs, "get_pool", get_pool)
    async def persist(*_args, **_kwargs): pass
    monkeypatch.setattr(jobs, "db_persist_task", persist)
    released = []
    async def release(*args): released.append(args)
    monkeypatch.setattr(jobs.generation_claims, "release_owned", release)
    monkeypatch.setitem(sys.modules, "cancel_registry", types.SimpleNamespace(is_cancel_requested=lambda *_: _false()))
    class Executor:
        def __init__(self, _tenant): pass
        async def run_machine_script_preview(self, *_args): raise RuntimeError("provider failed")
    monkeypatch.setitem(sys.modules, "pipeline_executor", types.SimpleNamespace(PipelineExecutor=Executor))
    result = await jobs.run_job("job-3")
    assert result == {"status": "failed", "error": "provider failed"}
    assert state["status"] == "failed"
    assert released == [("tenant-1", "video-1", "main", "machine-preview:job-3")]


@pytest.mark.asyncio
async def test_run_job_required_start_persistence_failure_prevents_executor(monkeypatch):
    import machine_preview_jobs as jobs
    state = {"id": "job-persist", "tenant_id": "tenant-1", "video_id": "video-1", "machine": "SS-2 USS Plunger", "status": "pending"}
    async def get_pool(): return _Pool(_Connection(state))
    monkeypatch.setattr(jobs, "get_pool", get_pool)
    persisted = []
    async def persist(*args, **kwargs):
        persisted.append((args, kwargs))
        if kwargs.get("required"):
            raise RuntimeError("activity database unavailable")
    monkeypatch.setattr(jobs, "db_persist_task", persist)
    monkeypatch.setattr(jobs.generation_claims, "release_owned", AsyncMock())
    class Executor:
        def __init__(self, _tenant):
            raise AssertionError("executor must not start before durable activity persistence")
    monkeypatch.setitem(sys.modules, "pipeline_executor", types.SimpleNamespace(PipelineExecutor=Executor))

    result = await jobs.run_job("job-persist")
    assert result == {"status": "failed", "error": "activity database unavailable"}
    assert state["status"] == "failed"
    assert persisted[0][1]["required"] is True


@pytest.mark.asyncio
async def test_run_job_source_error_is_ui_safe_and_records_bounded_details(monkeypatch):
    from error_utils import user_facing
    from factual_source_search import SourceDiscoveryError
    import machine_preview_jobs as jobs
    state = {"id": "job-source", "tenant_id": "tenant-1", "video_id": "video-1", "machine": "SS-2 USS Plunger", "status": "pending"}
    async def get_pool(): return _Pool(_Connection(state))
    monkeypatch.setattr(jobs, "get_pool", get_pool)
    monkeypatch.setattr(jobs, "db_persist_task", AsyncMock())
    monkeypatch.setattr(jobs.generation_claims, "release_owned", AsyncMock())
    monkeypatch.setitem(sys.modules, "cancel_registry", types.SimpleNamespace(is_cancel_requested=lambda *_: _false()))
    error = SourceDiscoveryError(
        user_facing("Saved research needs a retry."), code="malformed",
        retryable=True, attempts=2, next_action="review", machine="S1",
    )
    class Executor:
        def __init__(self, _tenant): pass
        async def run_machine_script_preview(self, *_args):
            raise error
    monkeypatch.setitem(sys.modules, "pipeline_executor", types.SimpleNamespace(PipelineExecutor=Executor))

    result = await jobs.run_job("job-source")
    assert result["status"] == "failed"
    assert "[[user-facing]]" not in result["error"]
    assert result["error"] == "Saved research needs a retry."
    assert {key: result[key] for key in ("stage", "machine", "failure_code", "retryable", "attempts", "saved_progress", "next_action")} == {
        "stage": "research", "machine": "S1", "failure_code": "malformed",
        "retryable": True, "attempts": 2, "saved_progress": False,
        "next_action": "review",
    }
    assert "[[user-facing]]" not in state["error"]


@pytest.mark.asyncio
async def test_run_job_does_not_release_claim_when_terminal_persistence_fails(monkeypatch):
    import machine_preview_jobs as jobs

    class TerminalWriteFailure(_Connection):
        async def execute(self, query, *args):
            if "machine_preview_jobs SET status" in query:
                return "UPDATE 0"
            if "SET status='failed'" in query:
                return "UPDATE 0"
            return await super().execute(query, *args)

    state = {"id": "job-terminal-failure", "tenant_id": "tenant-1", "video_id": "video-1", "machine": "SS-2 USS Plunger", "status": "pending"}
    async def get_pool(): return _Pool(TerminalWriteFailure(state))
    monkeypatch.setattr(jobs, "get_pool", get_pool)
    monkeypatch.setattr(jobs, "db_persist_task", AsyncMock())
    released = []
    async def release(*args): released.append(args)
    monkeypatch.setattr(jobs.generation_claims, "release_owned", release)
    monkeypatch.setitem(sys.modules, "cancel_registry", types.SimpleNamespace(is_cancel_requested=lambda *_: _false()))
    class Executor:
        def __init__(self, _tenant): pass
        async def run_machine_script_preview(self, *_args):
            return {"status": "completed", "preview": {"passed": True}}
    monkeypatch.setitem(sys.modules, "pipeline_executor", types.SimpleNamespace(PipelineExecutor=Executor))

    with pytest.raises(RuntimeError, match="terminal state was not persisted"):
        await jobs.run_job("job-terminal-failure")
    assert state["status"] == "running"
    assert released == []


@pytest.mark.asyncio
async def test_create_route_same_id_returns_existing_without_enqueue(monkeypatch):
    from routes import pipeline
    import machine_preview_jobs as jobs

    request_id = uuid.uuid4()
    existing = {"id": str(request_id), "machine": "SS-2 USS Plunger", "status": "pending"}
    monkeypatch.setattr(jobs, "get_job", AsyncMock(return_value=existing))
    monkeypatch.setattr(pipeline, "PipelineExecutor", _ready_executor())
    queue = types.SimpleNamespace(enqueue_job=AsyncMock())

    result = await pipeline.create_machine_script_preview_job(
        "video-1", _job_request(pipeline, request_id=request_id), _QueueRequest(queue), "tenant-1",
    )
    assert result is existing
    queue.enqueue_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_route_same_id_bound_to_other_machine_conflicts(monkeypatch):
    from fastapi import HTTPException
    from routes import pipeline
    import machine_preview_jobs as jobs

    request_id = uuid.uuid4()
    monkeypatch.setattr(jobs, "get_job", AsyncMock(return_value={"id": str(request_id), "machine": "SS-1 USS Holland", "status": "pending"}))
    with pytest.raises(HTTPException) as exc:
        await pipeline.create_machine_script_preview_job(
            "video-1", _job_request(pipeline, request_id=request_id), _QueueRequest(None), "tenant-1",
        )
    assert exc.value.status_code == 409
    assert "another machine" in exc.value.detail


@pytest.mark.asyncio
async def test_get_route_is_tenant_scoped_and_returns_404(monkeypatch):
    from fastapi import HTTPException
    from routes import pipeline
    import machine_preview_jobs as jobs

    get_job = AsyncMock(return_value=None)
    monkeypatch.setattr(jobs, "get_job", get_job)
    request_id = uuid.uuid4()
    with pytest.raises(HTTPException) as exc:
        await pipeline.get_machine_script_preview_job("video-1", request_id, "other-tenant")
    assert exc.value.status_code == 404
    get_job.assert_awaited_once_with("other-tenant", "video-1", str(request_id))


@pytest.mark.asyncio
async def test_create_route_without_queue_never_reserves_or_enqueues(monkeypatch):
    from routes import pipeline
    import machine_preview_jobs as jobs

    monkeypatch.setattr(jobs, "get_job", AsyncMock(return_value=None))
    monkeypatch.setattr(pipeline, "PipelineExecutor", _ready_executor())
    acquire = AsyncMock(return_value=True)
    monkeypatch.setattr(pipeline.generation_claims, "acquire_conn", acquire)
    pool = AsyncMock()
    monkeypatch.setattr(pipeline, "get_pool", pool)

    response = await pipeline.create_machine_script_preview_job(
        "video-1", _job_request(pipeline), _QueueRequest(None), "tenant-1",
    )
    assert response.status_code == 503
    assert b'"code":"preview_not_started"' in response.body
    acquire.assert_not_awaited()
    pool.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_route_uncertain_enqueue_retains_main_claim(monkeypatch):
    from fastapi import HTTPException
    from routes import pipeline
    import machine_preview_jobs as jobs

    request_id = uuid.uuid4()
    monkeypatch.setattr(jobs, "get_job", AsyncMock(return_value=None))
    monkeypatch.setattr(pipeline, "PipelineExecutor", _ready_executor())
    conn = _RouteConnection()
    async def get_pool(): return _Pool(conn)
    monkeypatch.setattr(pipeline, "get_pool", get_pool)
    acquired = []
    async def acquire_conn(*args, **kwargs):
        acquired.append((args, kwargs))
        return True
    monkeypatch.setattr(pipeline.generation_claims, "acquire_conn", acquire_conn)
    released = []
    async def release(*args): released.append(args)
    monkeypatch.setattr(pipeline.generation_claims, "release_owned", release)
    queue = types.SimpleNamespace(enqueue_job=AsyncMock(side_effect=RuntimeError("lost acknowledgement")))

    class DurableJob:
        def __init__(self, *_args):
            pass
        async def status(self):
            return object()
    monkeypatch.setattr(pipeline, "Job", DurableJob)

    with pytest.raises(HTTPException) as exc:
        await pipeline.create_machine_script_preview_job(
            "video-1", _job_request(pipeline, request_id=request_id), _QueueRequest(queue), "tenant-1",
        )
    assert exc.value.status_code == 503
    assert "acknowledgement is uncertain" in exc.value.detail
    assert len(acquired) == 1
    assert released == []
    queue.enqueue_job.assert_awaited_once_with(
        "arq_run_machine_script_preview", str(request_id), _job_id=f"machine-preview:{request_id}",
    )
