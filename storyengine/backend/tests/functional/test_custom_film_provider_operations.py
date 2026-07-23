from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import custom_film_provider_operations as operations
import custom_film_runtime
import routes.chat as chat
from custom_film_contract import CustomFilmContractError


OPERATION_ID = "custom-film-op:" + ("a" * 64)
RUNTIME_HASH = "b" * 64
RUNTIME_JOB_ID = "custom-film-runtime:" + RUNTIME_HASH
REQUEST_HASH = "c" * 64


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *_args):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _Acquire(self.conn)


class _OperationConnection:
    def __init__(self):
        self.rows: dict[str, dict] = {}

    async def execute(self, sql, *args):
        if "INSERT INTO custom_film_provider_operations" in sql:
            (
                tenant_id,
                video_id,
                runtime_job_id,
                runtime_hash,
                stage_key,
                operation_id,
                provider,
                request_hash,
                mode,
            ) = args
            self.rows.setdefault(
                operation_id,
                {
                    "tenant_id": tenant_id,
                    "video_id": video_id,
                    "runtime_job_id": runtime_job_id,
                    "runtime_hash": runtime_hash,
                    "stage_key": stage_key,
                    "operation_id": operation_id,
                    "provider": provider,
                    "request_hash": request_hash,
                    "reconciliation_mode": mode,
                    "state": "prepared",
                    "provider_operation_id": None,
                    "result": None,
                },
            )
            return "INSERT 0 1"
        if "SET state = 'submitted'" in sql:
            operation_id, provider_operation_id = args
            row = self.rows[operation_id]
            if row["state"] not in {"prepared", "submitted"}:
                return "UPDATE 0"
            if row["provider_operation_id"] not in {None, provider_operation_id}:
                return "UPDATE 0"
            row["state"] = "submitted"
            row["provider_operation_id"] = provider_operation_id
            return "UPDATE 1"
        if "SET state = 'completed'" in sql:
            operation_id, result_json = args
            row = self.rows[operation_id]
            result = json.loads(result_json)
            if row["state"] not in {"prepared", "submitted", "completed"}:
                return "UPDATE 0"
            if row["result"] is not None and row["result"] != result:
                return "UPDATE 0"
            row["state"] = "completed"
            row["result"] = result
            return "UPDATE 1"
        if "SET state = 'reconciliation_required'" in sql:
            operation_id, detail = args
            row = self.rows[operation_id]
            if row["state"] not in {
                "prepared",
                "submitted",
                "reconciliation_required",
            }:
                return "UPDATE 0"
            row["state"] = "reconciliation_required"
            row["reconciliation_detail"] = detail
            return "UPDATE 1"
        raise AssertionError(sql)

    async def fetchrow(self, sql, operation_id):
        assert "FROM custom_film_provider_operations" in sql
        row = self.rows.get(operation_id)
        return copy.deepcopy(row) if row else None


def _spec(mode=operations.RECONCILIATION_QUERY):
    return operations.ProviderOperationSpec(
        provider="kie.ai",
        request_hash=REQUEST_HASH,
        reconciliation_mode=mode,
    )


async def _prepare(monkeypatch, conn, spec=None):
    async def pool():
        return _Pool(conn)

    monkeypatch.setattr(operations.database, "get_pool", pool)
    return await operations.prepare_operation(
        tenant_id="tenant-1",
        video_id="video-1",
        runtime_job_id=RUNTIME_JOB_ID,
        runtime_hash=RUNTIME_HASH,
        stage_key="0:section-1:pictures",
        operation_id=OPERATION_ID,
        spec=spec or _spec(),
    )


@pytest.mark.asyncio
async def test_prepare_is_idempotent_but_rejects_request_or_provider_drift(
    monkeypatch,
):
    conn = _OperationConnection()
    first = await _prepare(monkeypatch, conn)
    second = await _prepare(monkeypatch, conn)
    assert second == first
    with pytest.raises(
        CustomFilmContractError,
        match="operation identity changed",
    ):
        await operations.prepare_operation(
            tenant_id="tenant-1",
            video_id="video-1",
            runtime_job_id=RUNTIME_JOB_ID,
            runtime_hash=RUNTIME_HASH,
            stage_key="0:section-1:pictures",
            operation_id=OPERATION_ID,
            spec=operations.ProviderOperationSpec(
                provider="different-provider",
                request_hash="d" * 64,
                reconciliation_mode=operations.RECONCILIATION_IDEMPOTENCY,
            ),
        )


@pytest.mark.asyncio
async def test_query_reconciliation_requires_durable_provider_task_id(monkeypatch):
    conn = _OperationConnection()
    record = await _prepare(monkeypatch, conn)
    with pytest.raises(CustomFilmContractError, match="task identity"):
        operations.reconciliation_action(record)
    submitted = await operations.mark_submitted(OPERATION_ID, "provider-task-1")
    assert operations.reconciliation_action(submitted) == "query_provider"
    with pytest.raises(CustomFilmContractError, match="identity changed"):
        await operations.mark_submitted(OPERATION_ID, "provider-task-2")


@pytest.mark.asyncio
async def test_idempotent_provider_retries_only_the_same_operation(monkeypatch):
    conn = _OperationConnection()
    record = await _prepare(
        monkeypatch,
        conn,
        _spec(operations.RECONCILIATION_IDEMPOTENCY),
    )
    assert operations.reconciliation_action(record) == "retry_same_operation"
    assert record.operation_id == OPERATION_ID
    assert record.request_hash == REQUEST_HASH


@pytest.mark.asyncio
async def test_opaque_provider_and_missing_journal_fail_closed(monkeypatch):
    conn = _OperationConnection()
    record = await _prepare(
        monkeypatch,
        conn,
        _spec(operations.RECONCILIATION_NONE),
    )
    with pytest.raises(CustomFilmContractError, match="cannot query or deduplicate"):
        operations.reconciliation_action(record)
    with pytest.raises(CustomFilmContractError, match="state is missing"):
        await operations.load_operation("custom-film-op:" + ("f" * 64))
    await operations.mark_reconciliation_required(
        OPERATION_ID,
        "Provider has no query or idempotency support",
    )
    blocked = await operations.load_operation(OPERATION_ID)
    assert blocked.state == "reconciliation_required"
    assert blocked.reconciliation_detail == (
        "Provider has no query or idempotency support"
    )


@pytest.mark.asyncio
async def test_completed_result_is_immutable_and_reused_without_provider_call(
    monkeypatch,
):
    conn = _OperationConnection()
    await _prepare(monkeypatch, conn)
    await operations.mark_completed(OPERATION_ID, {"asset_ids": ["asset-1"]})
    record = await operations.load_operation(OPERATION_ID)
    assert operations.reconciliation_action(record) == "return_completed"
    assert record.result == {"asset_ids": ["asset-1"]}
    await operations.mark_completed(OPERATION_ID, {"asset_ids": ["asset-1"]})
    with pytest.raises(CustomFilmContractError, match="result changed"):
        await operations.mark_completed(OPERATION_ID, {"asset_ids": ["asset-2"]})


@pytest.mark.asyncio
async def test_reserved_runtime_is_immediately_enqueued_once_with_exact_identity(
    monkeypatch,
):
    scheduled = {
        "scheduled": False,
        "job_id": RUNTIME_JOB_ID,
        "video_id": "video-1",
        "envelope": {"runtime_hash": RUNTIME_HASH},
    }

    async def load(*_args):
        return copy.deepcopy(scheduled)

    updates = []

    async def execute(*args):
        updates.append(args)
        return "UPDATE 1"

    class Arq:
        def __init__(self):
            self.calls = []
            self.seen = set()

        async def enqueue_job(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            job_id = kwargs["_job_id"]
            if job_id in self.seen:
                return None
            self.seen.add(job_id)
            return object()

    monkeypatch.setattr(
        custom_film_runtime,
        "load_exact_runtime_schedule",
        load,
    )
    monkeypatch.setattr(chat, "execute", execute)
    state = {
        "pending_custom_film_plan": {
            "status": "start_ready",
            "start_intent_hash": "e" * 64,
            "quote_inputs": {"requested_duration_seconds": 30},
        }
    }
    arq = Arq()
    first = await chat._schedule_reserved_custom_film_runtime(
        "conversation-1",
        "tenant-1",
        state,
        "video-1",
        arq_pool=arq,
    )
    second = await chat._schedule_reserved_custom_film_runtime(
        "conversation-1",
        "tenant-1",
        state,
        "video-1",
        arq_pool=arq,
    )
    expected_worker_id = f"custom-film-worker:{RUNTIME_JOB_ID}:1"
    assert first["queue_enqueued"] is True
    assert second["queue_enqueued"] is False
    assert first["queue_job_id"] == second["queue_job_id"] == expected_worker_id
    assert [call[1]["_job_id"] for call in arq.calls] == [
        expected_worker_id,
        expected_worker_id,
    ]
    assert all(call[0][0] == "arq_run_custom_film_runtime" for call in arq.calls)
    assert all(call[1]["runtime_job_id"] == RUNTIME_JOB_ID for call in arq.calls)
    assert len(updates) == 2


def test_migration_125_and_fresh_schema_match_operation_journal_contract():
    root = Path(__file__).parents[3]
    migration = (
        root / "backend/migrations/125_custom_film_provider_operations.sql"
    ).read_text()
    schema = (root / "schema.sql").read_text()
    for token in (
        "CREATE TABLE IF NOT EXISTS custom_film_provider_operations",
        "operation_id TEXT PRIMARY KEY",
        "provider_operation_id TEXT",
        "reconciliation_detail TEXT",
        "request_hash TEXT NOT NULL",
        "'provider_query', 'provider_idempotency', 'none'",
        "UNIQUE (tenant_id, video_id, runtime_job_id, stage_key)",
        "REVOKE ALL",
    ):
        assert token in migration
        assert token in schema
