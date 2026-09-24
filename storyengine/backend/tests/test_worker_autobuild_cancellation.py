"""FIX 2 regression: an arq-timeout kill of Run All must end cleanly.

arq's own timeout wraps the job coroutine in asyncio.wait_for; on expiry it
cancels the job's task, which delivers asyncio.CancelledError into
arq_run_autobuild while it awaits the chainer's step(). CancelledError is a
BaseException (not Exception) since Python 3.8, so the plain
`except Exception` around that await used to miss it entirely — the
background_tasks row for the build stayed 'running' forever, which blocks
production_queue's lane (see routes/queue.py's _reconcile_queue_items and
_claim_next, both of which gate on that row leaving pending/running).

This proves: a CancelledError raised from the chainer's step() persists a
'failed' background_tasks row (via an AWAITED task_store.db_persist_task
call, not the chainer's own fire-and-forget _set_task_status), releases the
"main" generation claim, and still propagates the cancellation (never
swallowed) — so the queue is free to advance to the next title.
"""
from __future__ import annotations

import asyncio
import sys
import types

import pytest

import worker


def _install(monkeypatch, *, step_raises):
    """Wire worker.arq_run_autobuild's local imports to fakes, mirroring
    tests/test_worker_source_failures.py's sys.modules injection pattern."""
    calls = {"persist": [], "released": [], "db_execute": [], "step_called": False}

    async def step():
        calls["step_called"] = True
        raise step_raises

    class _Actions:
        @staticmethod
        def make_autobuild_step(tenant_id, video_id, *, target, start_msg,
                                 delivery_mode, expected_channel_id):
            return step

    async def db_persist_task(tenant_id, video_id, task_type, status,
                               message=None, error=None, job_id=None, attempt=1,
                               **kwargs):
        calls["persist"].append({
            "tenant_id": tenant_id, "video_id": video_id, "task_type": task_type,
            "status": status, "message": message, "error": error,
            "job_id": job_id, "attempt": attempt,
        })

    store = types.ModuleType("task_store")
    store.db_persist_task = db_persist_task

    class _GenerationClaims:
        @staticmethod
        async def is_claim_owner(tenant_id, video_id, stage, claim_owner):
            return True

        @staticmethod
        async def acquire(tenant_id, video_id, stage, claimed_by):
            return True

        @staticmethod
        async def release_owned(tenant_id, video_id, stage, claim_owner):
            calls["released"].append((tenant_id, video_id, stage, claim_owner))

        @staticmethod
        async def release(tenant_id, video_id, stage):
            calls["released"].append((tenant_id, video_id, stage, None))

    job_id = "autobuild:video-1:1"

    async def fetch_one(query, *args):
        calls["db_execute"].append(("fetch_one", query, args))
        if "FROM background_tasks WHERE tenant_id" in query and "ORDER BY attempt DESC" in query:
            return {
                "job_id": job_id, "attempt": 1, "status": "running",
                "message": None, "error_message": None,
            }
        return None

    async def execute(query, *args):
        calls["db_execute"].append(("execute", query, args))
        return "UPDATE 1"

    db = types.ModuleType("database")
    db.execute = execute
    db.fetch_one = fetch_one

    monkeypatch.setitem(sys.modules, "actions", _Actions())
    monkeypatch.setitem(sys.modules, "generation_claims", _GenerationClaims())
    monkeypatch.setitem(sys.modules, "task_store", store)
    monkeypatch.setitem(sys.modules, "database", db)
    return calls, job_id


@pytest.mark.asyncio
async def test_arq_timeout_cancellation_persists_failed_and_releases_claim(monkeypatch):
    calls, job_id = _install(monkeypatch, step_raises=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await worker.arq_run_autobuild(
            {}, "video-1", "tenant-1", 1, "finish", "Building…",
            "claim-owner-1",
        )

    assert calls["step_called"] is True
    # The cancellation-branch persist call, not the queued 'running' one.
    failed_calls = [c for c in calls["persist"] if c["status"] == "failed"]
    assert len(failed_calls) == 1
    assert failed_calls[0]["task_type"] == "autobuild"
    assert failed_calls[0]["job_id"] == job_id
    assert failed_calls[0]["error"] == (
        "Build ran past its time limit; completed work is saved."
    )
    assert calls["released"] == [("tenant-1", "video-1", "main", "claim-owner-1")]


@pytest.mark.asyncio
async def test_ordinary_exception_still_persists_failed_and_releases_claim(monkeypatch):
    """Unchanged existing behavior: a normal exception from step() (not a
    cancellation) takes the sibling `except Exception` branch, byte-identical
    to before this fix."""
    calls, job_id = _install(monkeypatch, step_raises=RuntimeError("boom"))

    with pytest.raises(RuntimeError, match="boom"):
        await worker.arq_run_autobuild(
            {}, "video-1", "tenant-1", 1, "finish", "Building…",
            "claim-owner-1",
        )

    failed_calls = [c for c in calls["persist"] if c["status"] == "failed"]
    assert len(failed_calls) == 1
    assert failed_calls[0]["error"] == "boom"
    assert calls["released"] == [("tenant-1", "video-1", "main", "claim-owner-1")]
