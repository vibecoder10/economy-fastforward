from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import custom_film_provider_operations as operations
import custom_film_runtime
import main
import routes.chat as chat
import routes.pipeline as pipeline_route
from custom_film_contract import CustomFilmContractError


OPERATION_ID = "custom-film-op:" + ("a" * 64)
RUNTIME_HASH = "b" * 64
RUNTIME_JOB_ID = "custom-film-runtime:" + RUNTIME_HASH
DIRECTOR_HASH = "d" * 64
DIRECTOR_JOB_ID = "custom-film-director:" + DIRECTOR_HASH
DIRECTOR_SCHEDULE_ID = "33333333-3333-4333-8333-333333333333"
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


@pytest.mark.asyncio
@pytest.mark.parametrize("queue_failure", ["unavailable", "exception"])
async def test_committed_runtime_remains_held_and_recoverable_when_enqueue_fails(
    monkeypatch,
    queue_failure,
):
    scheduled = {
        "scheduled": True,
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

    class BrokenArq:
        async def enqueue_job(self, *_args, **_kwargs):
            raise ConnectionError("redis unavailable after commit")

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
    with pytest.raises(
        CustomFilmContractError,
        match="safely saved",
    ):
        await chat._schedule_reserved_custom_film_runtime(
            "conversation-1",
            "tenant-1",
            state,
            "video-1",
            arq_pool=None if queue_failure == "unavailable" else BrokenArq(),
        )
    assert state["pending_custom_film_plan"]["runtime_job_id"] == RUNTIME_JOB_ID
    assert len(updates) == 1


@pytest.mark.asyncio
async def test_pending_outbox_dispatches_on_startup_and_duplicate_pass_converges(
    monkeypatch,
):
    rows = [
        {
            "tenant_id": "tenant-1",
            "video_id": "video-1",
            "job_id": RUNTIME_JOB_ID,
            "attempt": 1,
        }
    ]

    async def fetch(sql):
        assert "status = 'pending'" in sql
        return copy.deepcopy(rows)

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

    monkeypatch.setattr(main, "fetch_all", fetch)
    arq = Arq()
    app = type("App", (), {"state": type("State", (), {"arq": arq})()})()
    assert await main._dispatch_pending_custom_film_runtime(app) == 1
    assert await main._dispatch_pending_custom_film_runtime(app) == 1
    expected_worker_id = f"custom-film-worker:{RUNTIME_JOB_ID}:1"
    assert [call[1]["_job_id"] for call in arq.calls] == [
        expected_worker_id,
        expected_worker_id,
    ]
    assert all(call[1]["runtime_job_id"] == RUNTIME_JOB_ID for call in arq.calls)
    assert "await _dispatch_pending_custom_film_runtime(app)" in (
        Path(main.__file__).read_text()
    )


@pytest.mark.asyncio
async def test_pending_director_outbox_dispatches_with_exact_schedule_identity(
    monkeypatch,
):
    rows = [
        {
            "tenant_id": "tenant-1",
            "video_id": "video-1",
            "job_id": DIRECTOR_JOB_ID,
            "attempt": 1,
            "schedule_id": DIRECTOR_SCHEDULE_ID,
        }
    ]

    async def fetch(sql):
        assert "custom_film_director_stage_schedules" in sql
        assert "b.status = 'pending'" in sql
        return copy.deepcopy(rows)

    class Arq:
        def __init__(self):
            self.calls = []

        async def enqueue_job(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return object()

    monkeypatch.setattr(main, "fetch_all", fetch)
    arq = Arq()
    app = type("App", (), {"state": type("State", (), {"arq": arq})()})()
    assert await main._dispatch_pending_custom_film_director(app) == 1
    assert await main._dispatch_pending_custom_film_director(app) == 1
    expected_worker_id = f"custom-film-worker:{DIRECTOR_JOB_ID}:1"
    assert [call[1]["_job_id"] for call in arq.calls] == [
        expected_worker_id,
        expected_worker_id,
    ]
    assert all(
        call[1]["director_job_id"] == DIRECTOR_JOB_ID
        and call[1]["schedule_id"] == DIRECTOR_SCHEDULE_ID
        for call in arq.calls
    )
    source = Path(main.__file__).read_text()
    assert "await _dispatch_pending_custom_film_director(app)" in source


@pytest.mark.asyncio
async def test_interrupted_director_recovers_with_exact_schedule_and_new_job_key(
    monkeypatch,
):
    async def recover():
        return 1

    async def fetch(sql):
        assert "director_schedule_id" in sql
        return [
            {
                "tenant_id": "tenant-1",
                "video_id": "video-1",
                "task_type": "custom_film_director",
                "job_id": DIRECTOR_JOB_ID,
                "attempt": 1,
                "director_schedule_id": DIRECTOR_SCHEDULE_ID,
            }
        ]

    updates = []

    async def execute(sql, *args):
        updates.append((sql, args))
        return "UPDATE 1"

    class Arq:
        def __init__(self):
            self.calls = []

        async def enqueue_job(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return object()

    monkeypatch.setattr(main, "recover_stale_tasks", recover)
    monkeypatch.setattr(main, "fetch_all", fetch)
    monkeypatch.setattr(main, "execute", execute)
    arq = Arq()
    app = type("App", (), {"state": type("State", (), {"arq": arq})()})()

    assert await main._recover_stale_tasks_to_queue(app) == 1
    assert len(updates) == 1
    assert "SET status = 'pending', attempt = $4" in updates[0][0]
    assert updates[0][1][-1] == 2
    assert len(arq.calls) == 1
    args, kwargs = arq.calls[0]
    assert args == (
        "arq_run_custom_film_director",
        "video-1",
        "tenant-1",
        2,
    )
    assert kwargs == {
        "_job_id": f"custom-film-worker:{DIRECTOR_JOB_ID}:2",
        "schedule_id": DIRECTOR_SCHEDULE_ID,
        "director_job_id": DIRECTOR_JOB_ID,
    }


@pytest.mark.asyncio
async def test_periodic_reaper_preserves_pending_custom_film_outbox(monkeypatch):
    calls = []

    async def execute(sql, *args):
        calls.append((sql, args))
        return "UPDATE 0"

    monkeypatch.setattr(pipeline_route, "execute", execute)
    assert await pipeline_route.reap_stale_running_tasks(180) == 0
    assert len(calls) == 1
    assert "task_type IN ('custom_film_runtime', 'custom_film_director')" in calls[0][0]


def _operation_row(**updates):
    row = {
        "tenant_id": "tenant-1",
        "video_id": "video-1",
        "runtime_job_id": RUNTIME_JOB_ID,
        "runtime_hash": RUNTIME_HASH,
        "stage_key": "0:section-1:pictures",
        "operation_id": OPERATION_ID,
        "provider": "kie.ai",
        "request_hash": REQUEST_HASH,
        "reconciliation_mode": operations.RECONCILIATION_QUERY,
        "state": "prepared",
        "provider_operation_id": None,
        "result": None,
        "reconciliation_detail": None,
    }
    row.update(updates)
    return row


def test_local_db_contract_rejects_cross_tenant_video_and_runtime_task_binding():
    row = _operation_row()
    operations.validate_operation_binding(
        row,
        video_identity=("tenant-1", "video-1"),
        task_identity=("tenant-1", "video-1", RUNTIME_JOB_ID),
    )
    with pytest.raises(CustomFilmContractError, match="tenant video"):
        operations.validate_operation_binding(
            row,
            video_identity=("tenant-2", "video-1"),
            task_identity=("tenant-1", "video-1", RUNTIME_JOB_ID),
        )
    with pytest.raises(CustomFilmContractError, match="runtime task"):
        operations.validate_operation_binding(
            row,
            video_identity=("tenant-1", "video-1"),
            task_identity=("tenant-1", "video-1", "custom-film-runtime:" + "f" * 64),
        )


@pytest.mark.parametrize(
    ("previous", "current", "message"),
    [
        (
            _operation_row(),
            _operation_row(tenant_id="tenant-2"),
            "identity is immutable",
        ),
        (
            _operation_row(
                state="submitted",
                provider_operation_id="provider-task-1",
            ),
            _operation_row(
                state="submitted",
                provider_operation_id="provider-task-2",
            ),
            "task identity is write-once",
        ),
        (
            _operation_row(state="completed", result={"asset": "one"}),
            _operation_row(state="completed", result={"asset": "two"}),
            "result is write-once",
        ),
        (
            _operation_row(state="completed", result={"asset": "one"}),
            _operation_row(
                state="submitted",
                result={"asset": "one"},
            ),
            "state cannot regress",
        ),
        (
            _operation_row(state="failed"),
            _operation_row(
                state="failed",
                provider_operation_id="late-provider-task",
            ),
            "terminal provider operation is immutable",
        ),
    ],
)
def test_local_db_trigger_model_rejects_tamper_rewrite_and_terminal_regression(
    previous,
    current,
    message,
):
    with pytest.raises(CustomFilmContractError, match=message):
        operations.validate_operation_transition(previous, current)


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
        "background_tasks_tenant_video_job_uidx",
        "FOREIGN KEY (tenant_id, video_id)",
        "REFERENCES videos(tenant_id, id)",
        "FOREIGN KEY (tenant_id, video_id, runtime_job_id)",
        "REFERENCES background_tasks(tenant_id, video_id, job_id)",
        "protect_custom_film_provider_operation",
        "provider task identity is write-once",
        "provider result is write-once",
        "terminal provider operation is immutable",
        "operation state cannot regress",
        "REVOKE ALL",
    ):
        assert token in migration
        assert token in schema
    for exact_column in (
        "tenant_id UUID NOT NULL,",
        "video_id UUID NOT NULL,",
    ):
        assert exact_column in migration
        provider_schema = schema.split(
            "CREATE TABLE IF NOT EXISTS custom_film_provider_operations",
            1,
        )[1].split(");", 1)[0]
        assert exact_column in provider_schema


def test_generation_claims_fresh_schema_retains_migration_092_foreign_keys():
    root = Path(__file__).parents[3]
    migration = (root / "backend/migrations/092_generation_claims.sql").read_text()
    schema = (root / "schema.sql").read_text()
    migration_table = migration.split(
        "CREATE TABLE IF NOT EXISTS generation_claims",
        1,
    )[1].split(");", 1)[0]
    schema_table = schema.split(
        "CREATE TABLE IF NOT EXISTS generation_claims",
        1,
    )[1].split(");", 1)[0]
    for exact_column in (
        "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE",
        "video_id UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE",
    ):
        assert exact_column in migration_table
        assert exact_column in schema_table
