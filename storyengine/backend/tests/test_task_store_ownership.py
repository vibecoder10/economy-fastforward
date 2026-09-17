"""Ownership boundaries for background task persistence."""
from __future__ import annotations

import pytest

import task_store


@pytest.mark.asyncio
async def test_terminal_update_carries_full_owner_tuple_and_null_job_is_not_wildcard(monkeypatch):
    calls = []

    async def execute(query, *args):
        calls.append((query, args))
        return "UPDATE 1"

    monkeypatch.setattr(task_store, "execute", execute)
    await task_store.db_persist_task(
        "tenant-a", "video-a", "machine_preview", "failed",
        error="safe error", job_id=None,
    )

    query, args = calls[0]
    assert "tenant_id = $4 AND video_id = $5 AND task_type = $6" in query
    assert "($7 IS NULL AND job_id IS NULL) OR job_id = $7" in query
    assert args[3:] == ("tenant-a", "video-a", "machine_preview", None)


@pytest.mark.asyncio
async def test_pending_and_running_lookup_are_isolated_by_tenant_video_type_and_job(monkeypatch):
    lookups = []
    inserts = []

    async def fetch_one(query, *args):
        lookups.append((query, args))
        return None

    async def execute(query, *args):
        inserts.append((query, args))
        return "INSERT 0 1"

    monkeypatch.setattr(task_store, "fetch_one", fetch_one)
    monkeypatch.setattr(task_store, "execute", execute)
    await task_store.db_persist_task("tenant-a", "video-a", "script", "running", job_id="job-a")
    await task_store.db_persist_task("tenant-b", "video-a", "thumbnail", "pending", job_id="job-b")

    assert [args for _query, args in lookups] == [
        ("tenant-a", "video-a", "script", "job-a"),
        ("tenant-b", "video-a", "thumbnail", "job-b"),
    ]
    assert all("tenant_id = $1 AND video_id = $2 AND task_type = $3" in query for query, _args in lookups)
    assert [args[:3] for _query, args in inserts] == [
        ("tenant-a", "video-a", "script"),
        ("tenant-b", "video-a", "thumbnail"),
    ]


@pytest.mark.asyncio
async def test_running_message_update_rechecks_the_full_owner_tuple(monkeypatch):
    updates = []

    async def fetch_one(*_args):
        return {"id": "only-the-owned-row"}

    async def execute(query, *args):
        updates.append((query, args))
        return "UPDATE 1"

    monkeypatch.setattr(task_store, "fetch_one", fetch_one)
    monkeypatch.setattr(task_store, "execute", execute)
    await task_store.db_persist_task(
        "tenant-a", "video-a", "script", "running", message="working", job_id="job-a",
    )

    query, args = updates[0]
    assert "SET status = 'running'" in query
    assert "tenant_id = $3 AND video_id = $4 AND task_type = $5" in query
    assert "($6 IS NULL AND job_id IS NULL) OR job_id = $6" in query
    assert args == ("working", "only-the-owned-row", "tenant-a", "video-a", "script", "job-a")


@pytest.mark.asyncio
async def test_running_promotes_exact_pending_task_instead_of_inserting(monkeypatch):
    writes = []

    async def fetch_one(*_args):
        return {"id": "pending-owned-row"}

    async def execute(query, *args):
        writes.append((query, args))
        return "UPDATE 1"

    monkeypatch.setattr(task_store, "fetch_one", fetch_one)
    monkeypatch.setattr(task_store, "execute", execute)
    await task_store.db_persist_task(
        "tenant", "video", "research", "running", job_id="research:video:1", required=True,
    )

    assert len(writes) == 1
    assert "SET status = 'running'" in writes[0][0]
    assert "INSERT INTO" not in writes[0][0]


@pytest.mark.asyncio
async def test_required_insert_conflict_without_exact_owner_raises(monkeypatch):
    async def fetch_one(*_args):
        return None

    async def execute(*_args):
        return "INSERT 0 0"

    monkeypatch.setattr(task_store, "fetch_one", fetch_one)
    monkeypatch.setattr(task_store, "execute", execute)
    with pytest.raises(RuntimeError, match="Required task start insert did not persist"):
        await task_store.db_persist_task(
            "tenant-a", "video-a", "research", "running", job_id="colliding-job", required=True,
        )


@pytest.mark.asyncio
async def test_required_persistence_failure_raises_but_default_remains_best_effort(monkeypatch):
    async def execute(*_args):
        raise RuntimeError("database unavailable")

    async def fetch_one(*_args):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(task_store, "execute", execute)
    monkeypatch.setattr(task_store, "fetch_one", fetch_one)
    await task_store.db_persist_task("tenant", "video", "script", "failed")
    with pytest.raises(RuntimeError, match="database unavailable"):
        await task_store.db_persist_task(
            "tenant", "video", "machine_preview", "running", required=True,
        )
