"""A superseded ARQ Run All retry cannot reclaim or mutate the pipeline."""

import os
import sys
import types

import pytest

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _BACKEND)

import worker  # noqa: E402


VIDEO = "video-1"
TENANT = "tenant-1"


class _Calls:
    def __init__(self):
        self.claim_checks = []
        self.claim_acquires = []
        self.claim_releases = []
        self.executes = []
        self.persists = []
        self.steps = 0


async def _invoke(monkeypatch, latest, *, attempt=4):
    calls = _Calls()
    job_id = f"autobuild:{VIDEO}:{attempt}"

    async def fetch_one(query, *_args):
        if "ORDER BY attempt DESC" in query:
            return latest
        if "status IN ('completed', 'failed', 'cancelled')" in query:
            return {"status": "completed", "message": "done", "error_message": None}
        return None

    async def execute(query, *args):
        calls.executes.append((query, args))
        return "UPDATE 1"

    async def is_claim_owner(*args):
        calls.claim_checks.append(args)
        return True

    async def acquire(*args, **kwargs):
        calls.claim_acquires.append((args, kwargs))
        return True

    async def release_owned(*args):
        calls.claim_releases.append(args)

    async def release(*args):
        calls.claim_releases.append(args)

    async def persist(*args, **kwargs):
        calls.persists.append((args, kwargs))

    def make_step(*_args, **_kwargs):
        async def step():
            calls.steps += 1
        return step

    database = types.ModuleType("database")
    database.fetch_one = fetch_one
    database.execute = execute
    claims = types.ModuleType("generation_claims")
    claims.is_claim_owner = is_claim_owner
    claims.acquire = acquire
    claims.release_owned = release_owned
    claims.release = release
    actions = types.ModuleType("actions")
    actions.make_autobuild_step = make_step
    task_store = types.ModuleType("task_store")
    task_store.db_persist_task = persist

    monkeypatch.setitem(sys.modules, "database", database)
    monkeypatch.setitem(sys.modules, "generation_claims", claims)
    monkeypatch.setitem(sys.modules, "actions", actions)
    monkeypatch.setitem(sys.modules, "task_store", task_store)

    result = await worker.arq_run_autobuild(
        {"job_try": 2}, VIDEO, TENANT, attempt,
        target="finish", start_msg="Building", claim_owner=f"owner-{attempt}",
    )
    return result, calls, job_id


@pytest.mark.asyncio
@pytest.mark.parametrize("newer_status", ["completed", "failed", "running"])
async def test_older_retry_noops_when_newer_attempt_is_authoritative(monkeypatch, newer_status):
    result, calls, _job_id = await _invoke(monkeypatch, {
        "job_id": f"autobuild:{VIDEO}:5",
        "attempt": 5,
        "status": newer_status,
        "message": "newer task",
        "error_message": "newer error" if newer_status == "failed" else None,
    })

    assert result["status"] == "cancelled"
    assert result["superseded"] is True
    assert calls.claim_checks == []
    assert calls.claim_acquires == []
    assert calls.claim_releases == []
    assert calls.executes == []
    assert calls.persists == []
    assert calls.steps == 0


@pytest.mark.asyncio
async def test_exact_current_job_is_allowed_to_run(monkeypatch):
    result, calls, job_id = await _invoke(monkeypatch, {
        "job_id": f"autobuild:{VIDEO}:4",
        "attempt": 4,
        "status": "pending",
        "message": "queued",
        "error_message": None,
    })

    assert result["status"] == "completed"
    assert calls.claim_checks
    assert len(calls.executes) == 1
    assert calls.executes[0][1][2] == job_id
    assert calls.steps == 1


@pytest.mark.asyncio
async def test_missing_authoritative_task_row_fails_closed(monkeypatch):
    result, calls, _job_id = await _invoke(monkeypatch, None)

    assert result["status"] == "cancelled"
    assert result["superseded"] is True
    assert calls.claim_checks == []
    assert calls.executes == []
    assert calls.persists == []
    assert calls.steps == 0


@pytest.mark.asyncio
async def test_exact_terminal_job_returns_without_reclaiming_or_rewriting(monkeypatch):
    result, calls, _job_id = await _invoke(monkeypatch, {
        "job_id": f"autobuild:{VIDEO}:4",
        "attempt": 4,
        "status": "completed",
        "message": "already done",
        "error_message": None,
    })

    assert result["status"] == "completed"
    assert result["message"] == "already done"
    assert calls.claim_checks == []
    assert calls.executes == []
    assert calls.persists == []
    assert calls.steps == 0
