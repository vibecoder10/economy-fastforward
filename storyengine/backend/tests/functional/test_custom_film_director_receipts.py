import copy
import json
from uuid import uuid4

import custom_film_director_multipass as multipass
import custom_film_director_receipts as receipts
import pytest

TENANT_ID = str(uuid4())
PLAN_ID = str(uuid4())
VIDEO_ID = str(uuid4())
SCHEDULE_ID = str(uuid4())
AUTHORITY_ID = str(uuid4())
SECTION_ID = str(uuid4())
PLAN_HASH = "d" * 64


def _stage_contract():
    return multipass.build_multipass_stage_contract(
        plan_id=PLAN_ID,
        plan_hash=PLAN_HASH,
        quote_inputs={
            "requested_duration_seconds": 300,
            "target_shot_seconds": 6,
            "totals": {
                "duration_seconds": 300,
                "planned_shots": 50,
            },
            "sections": [
                {
                    "section_id": SECTION_ID,
                    "order_index": 0,
                    "duration_seconds": 300,
                    "still_images": 50,
                }
            ],
        },
        prior_cumulative_cents=857,
        price_book={key: 2 for key in multipass.PRICE_BOOK_KEYS},
    )


class _Context:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeReceiptDatabase:
    def __init__(self, stage_contract):
        self.stage_contract = copy.deepcopy(stage_contract)
        self.events = []
        self.executions = []
        self.ledger = []
        self.conn = FakeReceiptConnection(self)

    def acquire(self):
        return _Context(self.conn)


class FakeReceiptConnection:
    def __init__(self, state):
        self.state = state

    def transaction(self):
        return _Context(self)

    async def fetchrow(self, query, *args):
        if "FROM custom_film_director_stage_schedules" in query:
            return {
                "id": SCHEDULE_ID,
                "authority_id": AUTHORITY_ID,
                "schedule": copy.deepcopy(self.state.stage_contract["schedule"]),
                "schedule_hash": self.state.stage_contract["schedule"]["schedule_hash"],
            }
        if "INSERT INTO custom_film_director_call_events" in query:
            operation_id = args[5]
            event_sequence = args[8]
            existing = next(
                (
                    row
                    for row in self.state.events
                    if row["operation_id"] == operation_id
                    and row["event_sequence"] == event_sequence
                ),
                None,
            )
            if existing:
                return None
            event = json.loads(args[15])
            self.state.events.append(
                {
                    "id": str(uuid4()),
                    "operation_id": operation_id,
                    "operation_order_index": args[7],
                    "event_sequence": event_sequence,
                    "event": event,
                }
            )
            return {"id": self.state.events[-1]["id"]}
        if "INSERT INTO custom_film_director_executions" in query:
            schedule_id = args[3]
            if any(row["schedule_id"] == schedule_id for row in self.state.executions):
                return None
            row = {
                "id": str(uuid4()),
                "schedule_id": schedule_id,
                "director_contract_id": args[5],
                "execution_hash": args[6],
                "receipt_manifest_hash": args[7],
                "actual_spend_nusd": args[8],
                "actual_spend_cents": args[9],
                "execution": json.loads(args[10]),
            }
            self.state.executions.append(row)
            return {"id": row["id"]}
        if "FROM custom_film_director_executions" in query:
            row = next(
                (
                    value
                    for value in self.state.executions
                    if value["schedule_id"] == args[1]
                ),
                None,
            )
            return copy.deepcopy(row)
        if "FROM generation_ledger" in query:
            row = next(
                (
                    value
                    for value in self.state.ledger
                    if value["tenant_id"] == args[0]
                    and value["video_id"] == args[1]
                    and value["kie_task_id"] == args[2]
                ),
                None,
            )
            return copy.deepcopy(row)
        raise AssertionError(f"Unexpected fetchrow SQL: {query}")

    async def fetch(self, query, *args):
        if "FROM custom_film_director_call_events" not in query:
            raise AssertionError(f"Unexpected fetch SQL: {query}")
        rows = self.state.events
        if "operation_id = $3" in query:
            rows = [row for row in rows if row["operation_id"] == args[2]]
        rows = sorted(
            rows,
            key=lambda row: (
                row["operation_order_index"],
                row["event_sequence"],
            ),
        )
        return [{"event": copy.deepcopy(row["event"])} for row in rows]

    async def execute(self, query, *args):
        if "INSERT INTO generation_ledger" in query:
            if not any(
                row["video_id"] == args[1] and row["kie_task_id"] == args[4]
                for row in self.state.ledger
            ):
                self.state.ledger.append(
                    {
                        "tenant_id": args[0],
                        "video_id": args[1],
                        "stage": "custom_film_director",
                        "model": args[2],
                        "units": 1,
                        "unit_cost": args[3],
                        "actual_cost": args[3],
                        "kie_task_id": args[4],
                    }
                )
            return "INSERT 0 1"
        if "UPDATE videos" in query:
            return "UPDATE 1"
        raise AssertionError(f"Unexpected execute SQL: {query}")


def _journal(database, stage_contract=None):
    return receipts.DurableDirectorCallJournal(
        tenant_id=TENANT_ID,
        plan_id=PLAN_ID,
        video_id=VIDEO_ID,
        schedule_id=SCHEDULE_ID,
        authority_id=AUTHORITY_ID,
        stage_contract=stage_contract or database.stage_contract,
        pool_factory=lambda: database,
    )


def _result():
    return {
        "request_id": "request-1",
        "model": "fake-single-attempt",
        "attempt_count": 1,
        "input_tokens": 100,
        "output_tokens": 200,
        "actual_cost_cents": 1,
        "finish_reason": "stop",
        "text": "{}",
    }


@pytest.mark.asyncio
async def test_durable_claim_commits_before_attempt_and_ambiguous_replay_stops():
    contract = _stage_contract()
    database = FakeReceiptDatabase(contract)
    operation = contract["schedule"]["tasks"][0]
    first = _journal(database)

    claimed = await first.claim(operation)

    assert claimed["status"] == "claimed"
    assert [row["event"]["event_kind"] for row in database.events] == [
        "attempt_started"
    ]

    resumed = _journal(database)
    blocked = await resumed.claim(operation)
    assert blocked["status"] == "reconciliation_required"
    assert len(database.events) == 1


@pytest.mark.asyncio
async def test_durable_terminal_receipt_is_append_only_and_replay_idempotent():
    contract = _stage_contract()
    database = FakeReceiptDatabase(contract)
    operation = contract["schedule"]["tasks"][0]
    journal = _journal(database)
    await journal.claim(operation)

    completed = await journal.complete(
        operation,
        _result(),
        {"film_bible": {"title": "Stored partial"}},
    )
    replay = await journal.complete(
        operation,
        _result(),
        {"film_bible": {"title": "Stored partial"}},
    )

    assert completed == replay
    assert [row["event"]["event_kind"] for row in database.events] == [
        "attempt_started",
        "attempt_completed",
    ]
    resumed = _journal(database)
    claim = await resumed.claim(operation)
    assert claim["status"] == "completed"
    assert claim["event"]["output_payload"] == {
        "film_bible": {"title": "Stored partial"}
    }

    with pytest.raises(Exception, match="terminal receipt replay changed"):
        await journal.complete(
            operation,
            {**_result(), "actual_cost_cents": 2},
            {"film_bible": {"title": "Stored partial"}},
        )


@pytest.mark.asyncio
async def test_durable_journal_refuses_unapproved_operation_or_schedule_drift():
    contract = _stage_contract()
    database = FakeReceiptDatabase(contract)
    operation = copy.deepcopy(contract["schedule"]["tasks"][0])
    operation["unit_max_cents"] = 99

    with pytest.raises(Exception, match="operation is not authorized"):
        await _journal(database).claim(operation)
    assert database.events == []

    database.stage_contract["schedule"]["schedule_hash"] = "e" * 64
    with pytest.raises(Exception, match="durable director schedule changed"):
        await _journal(database, contract).claim(contract["schedule"]["tasks"][0])
    assert database.events == []


@pytest.mark.asyncio
async def test_durable_failure_replays_as_failed_without_second_claim():
    contract = _stage_contract()
    database = FakeReceiptDatabase(contract)
    operation = contract["schedule"]["tasks"][0]
    journal = _journal(database)
    await journal.claim(operation)
    await journal.fail(
        operation,
        _result(),
        failure_code="validation_failure",
        output_payload={"invalid": "candidate"},
    )

    resumed = _journal(database)
    claim = await resumed.claim(operation)

    assert claim["status"] == "failed"
    assert claim["event"]["failure_code"] == "validation_failure"
    assert len(database.events) == 2


@pytest.mark.asyncio
async def test_final_execution_and_director_contract_persist_once(
    monkeypatch,
):
    contract = _stage_contract()
    database = FakeReceiptDatabase(contract)
    operation = contract["schedule"]["tasks"][0]
    journal = _journal(database)
    await journal.claim(operation)
    await journal.complete(
        operation,
        _result(),
        {"film_bible": {"title": "Stored partial"}},
    )
    durable_events = list(journal.events())
    execution = {
        "manifest_hash": contract["manifest"]["manifest_hash"],
        "authority_hash": contract["authority_hash"],
        "director_contract": {
            "plan_id": PLAN_ID,
            "plan_hash": PLAN_HASH,
        },
        "director_contract_hash": "f" * 64,
        "execution_hash": "1" * 64,
        "receipt_events": durable_events,
        "terminal_call_count": 1,
        "actual_spend_cents": 1,
    }
    persisted_calls = []

    monkeypatch.setattr(
        receipts,
        "validate_multipass_execution_result",
        lambda raw, *, stage_contract: copy.deepcopy(raw),
    )

    stable_director_id = str(uuid4())

    async def stable_persist_director_contract(conn, **kwargs):
        persisted_calls.append(copy.deepcopy(kwargs))
        return {
            "id": stable_director_id,
            "revision": 1,
            "created": not bool(database.executions),
            "contract": kwargs["director_contract"],
        }

    monkeypatch.setattr(
        receipts,
        "persist_director_contract",
        stable_persist_director_contract,
    )

    first = await receipts.persist_completed_director_execution(
        database.conn,
        tenant_id=TENANT_ID,
        plan_id=PLAN_ID,
        video_id=VIDEO_ID,
        schedule_id=SCHEDULE_ID,
        authority_id=AUTHORITY_ID,
        stage_contract=contract,
        execution_result=execution,
    )
    replay = await receipts.persist_completed_director_execution(
        database.conn,
        tenant_id=TENANT_ID,
        plan_id=PLAN_ID,
        video_id=VIDEO_ID,
        schedule_id=SCHEDULE_ID,
        authority_id=AUTHORITY_ID,
        stage_contract=contract,
        execution_result=execution,
    )

    assert first["created"] is True
    assert replay["created"] is False
    assert first["director_contract_id"] == replay["director_contract_id"]
    assert len(database.executions) == 1
    assert len(persisted_calls) == 2
    assert persisted_calls[0]["plan_hash"] == PLAN_HASH


@pytest.mark.asyncio
async def test_final_persistence_refuses_receipt_drift_before_contract_write(
    monkeypatch,
):
    contract = _stage_contract()
    database = FakeReceiptDatabase(contract)
    operation = contract["schedule"]["tasks"][0]
    journal = _journal(database)
    await journal.claim(operation)
    await journal.complete(operation, _result(), {"partial": "stored"})
    execution = {
        "manifest_hash": contract["manifest"]["manifest_hash"],
        "authority_hash": contract["authority_hash"],
        "director_contract": {"plan_id": PLAN_ID, "plan_hash": PLAN_HASH},
        "director_contract_hash": "f" * 64,
        "execution_hash": "1" * 64,
        "receipt_events": list(journal.events()),
        "terminal_call_count": 1,
        "actual_spend_cents": 1,
    }
    execution["receipt_events"][1]["actual_cost_cents"] = 2
    writes = []
    monkeypatch.setattr(
        receipts,
        "validate_multipass_execution_result",
        lambda raw, *, stage_contract: copy.deepcopy(raw),
    )

    async def forbidden_persist(*args, **kwargs):
        writes.append((args, kwargs))
        raise AssertionError("director persistence must not run")

    monkeypatch.setattr(
        receipts,
        "persist_director_contract",
        forbidden_persist,
    )

    with pytest.raises(Exception, match="durable director receipts changed"):
        await receipts.persist_completed_director_execution(
            database.conn,
            tenant_id=TENANT_ID,
            plan_id=PLAN_ID,
            video_id=VIDEO_ID,
            schedule_id=SCHEDULE_ID,
            authority_id=AUTHORITY_ID,
            stage_contract=contract,
            execution_result=execution,
        )
    assert writes == []
