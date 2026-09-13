"""Focused contract tests for durable /pipeline/build Run All dispatch."""
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock

import pytest
from fastapi import BackgroundTasks, HTTPException

from job_queue import enqueue_stage
from routes import pipeline
import worker


def _request(arq_pool):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(arq=arq_pool)))


@pytest.fixture(autouse=True)
def _clear_route_marker(monkeypatch):
    pipeline._running_tasks.clear()
    monkeypatch.setattr(
        pipeline.drain_mode,
        "assert_accepting_new_work",
        AsyncMock(return_value=None),
    )
    yield
    pipeline._running_tasks.clear()


@pytest.mark.asyncio
async def test_autobuild_queue_identity_forwards_resume_target():
    pool = SimpleNamespace(enqueue_job=AsyncMock(return_value=object()))

    job_id = await enqueue_stage(
        pool,
        "autobuild",
        "video-1",
        "tenant-1",
        4,
        target="finish",
        start_msg="Finishing the video…",
        claim_owner="pipeline:build:finish:claim-1",
    )

    assert job_id == "autobuild:video-1:4"
    pool.enqueue_job.assert_awaited_once_with(
        "arq_run_autobuild",
        "video-1",
        "tenant-1",
        4,
        _job_id="autobuild:video-1:4",
        target="finish",
        start_msg="Finishing the video…",
        claim_owner="pipeline:build:finish:claim-1",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("delivery,channel", [("public", "channel"), ("youtube_unlisted", None)])
async def test_invalid_delivery_cannot_enter_worker_queue(delivery, channel):
    pool = SimpleNamespace(enqueue_job=AsyncMock())
    with pytest.raises(ValueError, match="saved YouTube channel identity"):
        await enqueue_stage(pool, "autobuild", "video", "tenant", target="finish",
                            claim_owner="owner", delivery_mode=delivery, expected_channel_id=channel)
    pool.enqueue_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_build_refuses_when_durable_queue_is_unavailable(monkeypatch):
    async def fetch_video(query, *args):
        return {"id": "video-1", "status": "approved"}

    acquire = AsyncMock(return_value=True)
    monkeypatch.setattr(pipeline, "fetch_one", fetch_video)
    monkeypatch.setattr(pipeline, "_is_task_active", AsyncMock(return_value=False))
    monkeypatch.setattr(pipeline.generation_claims, "acquire", acquire)

    with pytest.raises(HTTPException) as exc_info:
        await pipeline.run_build(
            "video-1",
            _request(None),
            BackgroundTasks(),
            pipeline.BuildRequest(target="finish"),
            "tenant-1",
        )

    assert exc_info.value.status_code == 503
    assert "nothing was started" in exc_info.value.detail.lower()
    acquire.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_build_reserves_once_and_releases_exact_claim_on_enqueue_failure(monkeypatch):
    async def fetch_video(query, *args):
        return {"id": "video-1", "status": "approved"}

    monkeypatch.setattr(pipeline, "fetch_one", fetch_video)
    monkeypatch.setattr(pipeline, "_is_task_active", AsyncMock(return_value=False))
    monkeypatch.setattr(
        pipeline.generation_claims, "acquire", AsyncMock(return_value=True)
    )
    release_owned = AsyncMock()
    monkeypatch.setattr(pipeline.generation_claims, "release_owned", release_owned)
    monkeypatch.setattr(
        pipeline,
        "enqueue_stage",
        AsyncMock(side_effect=ConnectionError("redis disappeared")),
    )
    status = AsyncMock(return_value=pipeline.JobStatus.not_found)
    monkeypatch.setattr(
        pipeline, "Job", lambda *args, **kwargs: SimpleNamespace(status=status)
    )

    with pytest.raises(HTTPException) as exc_info:
        await pipeline.run_build(
            "video-1",
            _request(object()),
            BackgroundTasks(),
            pipeline.BuildRequest(target="pictures"),
            "tenant-1",
        )

    assert exc_info.value.status_code == 503
    release_owned.assert_awaited_once()
    tenant, video, lane, owner = release_owned.await_args.args
    assert (tenant, video, lane) == ("tenant-1", "video-1", "main")
    assert owner.startswith("pipeline:build:pictures:")


@pytest.mark.asyncio
async def test_run_build_lost_ack_keeps_claim_when_exact_job_cannot_be_reconciled(monkeypatch):
    async def fetch_video(query, *args):
        if "MAX(attempt)" in query:
            return {"n": 0}
        return {"id": "video-1", "status": "approved"}

    monkeypatch.setattr(pipeline, "fetch_one", fetch_video)
    monkeypatch.setattr(pipeline, "_is_task_active", AsyncMock(return_value=False))
    monkeypatch.setattr(
        pipeline.generation_claims, "acquire", AsyncMock(return_value=True)
    )
    release_owned = AsyncMock()
    monkeypatch.setattr(pipeline.generation_claims, "release_owned", release_owned)
    monkeypatch.setattr(
        pipeline, "enqueue_stage", AsyncMock(side_effect=TimeoutError("lost ack"))
    )
    status = AsyncMock(side_effect=ConnectionError("status unavailable"))
    monkeypatch.setattr(
        pipeline, "Job", lambda *args, **kwargs: SimpleNamespace(status=status)
    )

    with pytest.raises(HTTPException) as exc_info:
        await pipeline.run_build(
            "video-1",
            _request(object()),
            BackgroundTasks(),
            pipeline.BuildRequest(target="finish"),
            "tenant-1",
        )

    assert exc_info.value.status_code == 503
    assert "kept the run all reservation" in exc_info.value.detail.lower()
    release_owned.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_build_duplicate_claim_is_refused_without_enqueue(monkeypatch):
    async def fetch_video(query, *args):
        return {"id": "video-1", "status": "approved"}

    monkeypatch.setattr(pipeline, "fetch_one", fetch_video)
    monkeypatch.setattr(pipeline, "_is_task_active", AsyncMock(return_value=False))
    monkeypatch.setattr(
        pipeline.generation_claims, "acquire", AsyncMock(return_value=False)
    )
    enqueue = AsyncMock()
    monkeypatch.setattr(pipeline, "enqueue_stage", enqueue)

    with pytest.raises(HTTPException) as exc_info:
        await pipeline.run_build(
            "video-1",
            _request(object()),
            BackgroundTasks(),
            pipeline.BuildRequest(target="finish"),
            "tenant-1",
        )

    assert exc_info.value.status_code == 409
    enqueue.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_build_enqueues_finish_target_and_persists_pending(monkeypatch):
    async def fetch_video(query, *args):
        if "MAX(attempt)" in query:
            return {"n": 2}
        return {"id": "video-1", "status": "approved"}

    enqueue = AsyncMock(return_value="autobuild:video-1:3")
    persist = AsyncMock()
    release_owned = AsyncMock()
    monkeypatch.setattr(pipeline, "fetch_one", fetch_video)
    monkeypatch.setattr(pipeline, "_is_task_active", AsyncMock(return_value=False))
    monkeypatch.setattr(
        pipeline.generation_claims, "acquire", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(pipeline.generation_claims, "release_owned", release_owned)
    monkeypatch.setattr(pipeline, "enqueue_stage", enqueue)
    monkeypatch.setattr(pipeline, "db_persist_task", persist)
    background = BackgroundTasks()

    response = await pipeline.run_build(
        "video-1",
        _request(object()),
        background,
        pipeline.BuildRequest(target="finish"),
        "tenant-1",
    )

    assert response.status == "running"
    assert response.video_id == "video-1"
    assert background.tasks == []
    args = enqueue.await_args.args
    kwargs = enqueue.await_args.kwargs
    assert args[:5] == (ANY, "autobuild", "video-1", "tenant-1", 3)
    assert kwargs["target"] == "finish"
    assert kwargs["start_msg"].startswith("Finishing the video")
    assert kwargs["claim_owner"].startswith("pipeline:build:finish:")
    persisted_args = persist.await_args.args
    assert persisted_args[:4] == ("tenant-1", "video-1", "autobuild", "pending")
    release_owned.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("delivery", ["render_only", "youtube_unlisted"])
async def test_worker_resumes_same_target_without_overwriting_inner_terminal_status(monkeypatch, delivery):
    calls = []

    async def run_step():
        calls.append("ran")

    def make_step(tenant_id, video_id, *, target, start_msg, delivery_mode, expected_channel_id):
        assert delivery_mode == delivery
        assert expected_channel_id == ("channel" if delivery == "youtube_unlisted" else None)
        calls.append((tenant_id, video_id, target, start_msg))
        return run_step

    persist = AsyncMock()
    execute = AsyncMock(return_value="UPDATE 1")
    fetch_terminal = AsyncMock(side_effect=[
        {
            "job_id": "autobuild:video-1:2",
            "attempt": 2,
            "status": "running",
            "message": "Finishing the video…",
            "error_message": None,
        },
        {
            "status": "failed",
            "message": None,
            "error_message": "inner build failed",
        },
    ])
    monkeypatch.setattr(worker, "make_job_id", lambda *args: "autobuild:video-1:2")
    monkeypatch.setattr("actions.make_autobuild_step", make_step)
    monkeypatch.setattr("generation_claims.is_claim_owner", AsyncMock(return_value=True))
    monkeypatch.setattr("generation_claims.acquire", AsyncMock())
    monkeypatch.setattr("task_store.db_persist_task", persist)
    monkeypatch.setattr("database.execute", execute)
    monkeypatch.setattr("database.fetch_one", fetch_terminal)

    result = await worker.arq_run_autobuild(
        {"job_try": 1},
        "video-1",
        "tenant-1",
        2,
        "finish",
        "Finishing the video…",
        "pipeline:build:finish:claim-1",
        delivery_mode=delivery,
        expected_channel_id="channel" if delivery == "youtube_unlisted" else None,
    )

    assert result == {
        "status": "failed",
        "message": None,
        "error": "inner build failed",
        "target": "finish",
    }
    assert calls == [
        ("tenant-1", "video-1", "finish", "Finishing the video…"),
        "ran",
    ]
    assert persist.await_args_list == []
    assert "status = 'running'" in execute.await_args.args[0]


def test_worker_registers_bounded_autobuild_retry_and_timeout():
    registered = {item.name: item for item in worker.WorkerSettings.functions}
    autobuild = registered["arq_run_autobuild"]

    assert autobuild.coroutine is worker.arq_run_autobuild
    assert autobuild.timeout_s == 7200
    assert autobuild.max_tries == 3


@pytest.mark.asyncio
async def test_api_restart_preserves_queue_owned_autobuild_rows(monkeypatch):
    execute = AsyncMock(return_value="UPDATE 0")
    monkeypatch.setattr(pipeline, "execute", execute)

    assert await pipeline.recover_stale_tasks() == 0

    query = execute.await_args.args[0]
    assert "status = 'running'" in query
    assert "task_type <> 'autobuild'" in query


@pytest.mark.asyncio
async def test_worker_retry_reopens_exact_failed_job_before_resuming(monkeypatch):
    async def run_step():
        return None

    monkeypatch.setattr(
        "actions.make_autobuild_step", lambda *args, **kwargs: run_step
    )
    monkeypatch.setattr(
        "generation_claims.is_claim_owner", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        "generation_claims.acquire", AsyncMock(return_value=True)
    )
    execute = AsyncMock(return_value="UPDATE 1")
    monkeypatch.setattr("database.execute", execute)
    monkeypatch.setattr("database.fetch_one", AsyncMock(side_effect=[
        {
            "job_id": "autobuild:video-1:3",
            "attempt": 3,
            "status": "failed",
            "message": None,
            "error_message": "worker interrupted",
        },
        {"status": "completed", "message": "rendered", "error_message": None},
    ]))
    persist = AsyncMock()
    monkeypatch.setattr("task_store.db_persist_task", persist)

    result = await worker.arq_run_autobuild(
        {"job_try": 2},
        "video-1",
        "tenant-1",
        3,
        "finish",
        "Finishing the video…",
        "pipeline:build:finish:claim-1",
    )

    assert result["status"] == "completed"
    assert "'failed'" in execute.await_args.args[0]
    assert persist.await_args_list == []


@pytest.mark.asyncio
async def test_cold_poll_keeps_autobuild_failure_after_reference_sweep(monkeypatch):
    """Execute the route's selection SQL, rather than mocking its chosen row."""
    import sqlite3
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE background_tasks (video_id TEXT, tenant_id TEXT, status TEXT, message TEXT, error_message TEXT, task_type TEXT, created_at TEXT)')
    db.executemany('INSERT INTO background_tasks VALUES (?,?,?,?,?,?,?)', [
        ('video', 'tenant', 'failed', 'A-5 coverage unresolved', 'Research requires source correction', 'autobuild', '2026-09-13T04:07:43'),
        ('video', 'tenant', 'completed', '23 verified, 1 missed', None, 'roster_prefetch', '2026-09-13T04:08:00'),
        ('video', 'other', 'running', 'Other tenant', None, 'autobuild', '2026-09-13T05:00:00'),
    ])
    async def fetch(query, *args):
        row = db.execute(query, args).fetchone()
        return dict(row) if row else None
    monkeypatch.setattr(pipeline, 'fetch_one', fetch)
    try:
        result = await pipeline.get_task_status('video', 'tenant')
        assert result['status'] == 'failed'
        assert result['task_type'] == 'autobuild'
        assert result['message'] == 'A-5 coverage unresolved'
        db.execute("INSERT INTO background_tasks VALUES ('video','tenant','running','Resumed',NULL,'autobuild','2026-09-13T05:01:00')")
        monkeypatch.setattr(pipeline.generation_claims, 'get_claimed_by', AsyncMock(return_value=None))
        assert (await pipeline.get_task_status('video', 'tenant'))['status'] == 'running'
    finally:
        db.close()


@pytest.mark.asyncio
async def test_autobuild_terminal_write_does_not_finish_reference_job(monkeypatch):
    import sqlite3
    db = sqlite3.connect(':memory:')
    db.create_function('now', 0, lambda: '2026-09-13T05:00:00')
    db.execute('CREATE TABLE background_tasks (video_id TEXT, tenant_id TEXT, status TEXT, message TEXT, error_message TEXT, task_type TEXT, completed_at TEXT)')
    db.executemany('INSERT INTO background_tasks VALUES (?,?,?,?,?,?,?)', [
        ('video','tenant','running','Build',None,'autobuild',None),
        ('video','tenant','running','References',None,'roster_prefetch',None),
        ('video','other','running','Other',None,'autobuild',None),
    ])
    async def execute(query, *args):
        db.execute(query, args)
        return 'UPDATE 1'
    monkeypatch.setattr(pipeline, 'execute', execute)
    try:
        await pipeline._db_persist_task('tenant','video','pipeline','failed',message='Coverage failure',error='Coverage failure')
        assert db.execute('SELECT status FROM background_tasks ORDER BY rowid').fetchall() == [('failed',),('running',),('running',)]
    finally:
        db.close()
