"""Worker source failures stop at the adapter boundary without ARQ replay."""
from __future__ import annotations

import sys
import types

import pytest

import worker
from error_utils import user_facing
from factual_source_search import SourceDiscoveryError


def _install(monkeypatch, method, persist):
    created = []

    class Executor:
        def __init__(self, _tenant):
            created.append(True)

        async def run_research(self, _video):
            return await method()

    pipeline = types.ModuleType("pipeline_executor")
    pipeline.PipelineExecutor = Executor
    store = types.ModuleType("task_store")
    store.db_persist_task = persist
    monkeypatch.setitem(sys.modules, "pipeline_executor", pipeline)
    monkeypatch.setitem(sys.modules, "task_store", store)
    return created


@pytest.mark.asyncio
async def test_required_start_failure_prevents_executor_dispatch(monkeypatch):
    persisted = []

    async def persist(*args, **kwargs):
        persisted.append((args, kwargs))
        if kwargs.get("required"):
            raise RuntimeError("task ownership unavailable")

    async def method():
        raise AssertionError("executor must not run")

    created = _install(monkeypatch, method, persist)
    with pytest.raises(RuntimeError, match="task ownership unavailable"):
        await worker._run_stage({"job_try": 1}, "research", "run_research", "video", "tenant", 1)
    assert created == []
    assert persisted[0][1]["required"] is True


@pytest.mark.asyncio
async def test_typed_source_error_is_humanized_persisted_and_not_retried(monkeypatch):
    persisted = []

    async def persist(*args, **kwargs):
        persisted.append((args, kwargs))

    error = SourceDiscoveryError(
        user_facing("Saved source search can resume."), code="malformed",
        retryable=True, attempts=2, next_action="review", machine="S1",
    )

    async def method():
        raise error

    created = _install(monkeypatch, method, persist)
    result = await worker._run_stage({"job_try": 1}, "research", "run_research", "video", "tenant", 1)

    assert created == [True]
    assert result == {
        "status": "failed", "error": "Saved source search can resume.",
        "source_search_failed": True, "failure_code": "malformed", "retryable": True,
        "attempts": 2, "next_action": "review", "stage": "research", "machine": "S1",
    }
    assert [call[0][3] for call in persisted] == ["running", "failed"]
    assert persisted[0][1]["required"] is True
    assert "[[user-facing]]" not in persisted[-1][1]["error"]


@pytest.mark.asyncio
async def test_source_failed_result_stops_without_arq_exception(monkeypatch):
    persisted = []

    async def persist(*args, **kwargs):
        persisted.append((args, kwargs))

    async def method():
        return {
            "status": "failed", "source_search_failed": True,
            "error": user_facing("Source response is saved for retry."),
            "code": "checkpoint", "retryable": False, "attempts": 4,
            "next_action": user_facing("reconcile"), "stage": "script",
            "provider_operation_failed": True,
        }

    _install(monkeypatch, method, persist)
    result = await worker._run_stage({"job_try": 1}, "research", "run_research", "video", "tenant", 1)

    assert result["source_search_failed"] is True
    assert result["failure_code"] == "checkpoint"
    assert result["retryable"] is False
    assert result["next_action"] == "reconcile"
    assert result["stage"] == "script"
    assert result["provider_operation_failed"] is True
    assert [call[0][3] for call in persisted] == ["running", "failed"]


@pytest.mark.asyncio
async def test_paused_result_is_retained_without_false_completion_claim(monkeypatch):
    persisted = []

    async def persist(*args, **kwargs):
        persisted.append((args, kwargs))

    async def method():
        return {"status": "paused", "message": "Budget pause"}

    _install(monkeypatch, method, persist)
    result = await worker._run_stage({"job_try": 1}, "research", "run_research", "video", "tenant", 1)

    assert result == {"status": "paused", "message": "Budget pause", "paused": True}
    assert [call[0][3] for call in persisted] == ["running", "completed"]
    assert persisted[-1][1]["message"] == "Budget pause"
