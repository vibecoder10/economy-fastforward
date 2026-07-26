from __future__ import annotations

import copy
import json

import pytest

import custom_film_director_worker as director_worker
from custom_film_director_activation import DIRECTOR_EXECUTION_MODEL


TENANT_ID = "11111111-1111-4111-8111-111111111111"
VIDEO_ID = "22222222-2222-4222-8222-222222222222"
PLAN_ID = "33333333-3333-4333-8333-333333333333"
SCHEDULE_ID = "44444444-4444-4444-8444-444444444444"
AUTHORITY_ID = "55555555-5555-4555-8555-555555555555"
CONVERSATION_ID = "66666666-6666-4666-8666-666666666666"
DIRECTOR_JOB_ID = f"custom-film-director:{'a' * 64}"


class _Context:
    def __init__(self, value=None):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *_args):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _Context(self.conn)


class _Connection:
    def __init__(self, state, *, existing=None):
        self.state = copy.deepcopy(state)
        self.existing = existing
        self.updates = []

    def transaction(self):
        return _Context()

    async def fetchrow(self, query, *args):
        if "FROM chat_conversations" in query and "ORDER BY updated_at" in query:
            return {"id": CONVERSATION_ID, "state": copy.deepcopy(self.state)}
        if "FROM custom_film_director_executions" in query:
            return copy.deepcopy(self.existing)
        if "FROM chat_conversations" in query and "FOR UPDATE" in query:
            return {"state": copy.deepcopy(self.state)}
        raise AssertionError(query)

    async def execute(self, query, *args):
        self.updates.append((query, args))
        if "UPDATE chat_conversations" in query:
            self.state = json.loads(args[2])
        return "UPDATE 1"


def _state():
    return {
        "mode": "custom_film",
        "pending_custom_film_plan": {
            "execution_model": DIRECTOR_EXECUTION_MODEL,
            "status": "director_stage_scheduled",
            "video_id": VIDEO_ID,
            "director_schedule_id": SCHEDULE_ID,
            "director_job_id": DIRECTOR_JOB_ID,
            "stage_authority_id": AUTHORITY_ID,
            "director_activation": {"stored": "activation"},
        },
    }


@pytest.mark.asyncio
async def test_worker_executes_exact_binding_and_commits_completion(monkeypatch):
    conn = _Connection(_state())
    calls = []
    activation = {
        "prospective_plan_id": PLAN_ID,
        "user_request": "A courier exposes a hidden route.",
        "stage_contract": {"immutable": "stage"},
    }
    execution = {
        "actual_spend_cents": 42,
        "terminal_call_count": 9,
    }

    async def get_pool():
        return _Pool(conn)

    def validate(raw):
        calls.append(("validate", copy.deepcopy(raw)))
        return copy.deepcopy(activation)

    async def resolve(tenant_id):
        calls.append(("resolve", tenant_id))
        return object()

    class Journal:
        def __init__(self, **kwargs):
            calls.append(("journal", copy.deepcopy(kwargs)))

    def adapt(client):
        calls.append(("adapt", client))
        return "one-request-adapter"

    async def execute_director(**kwargs):
        calls.append(("execute", copy.deepcopy(kwargs)))
        return copy.deepcopy(execution)

    async def persist(_conn, **kwargs):
        calls.append(("persist", copy.deepcopy(kwargs)))
        return {
            "id": "execution-1",
            "director_contract_id": "contract-1",
            "execution_hash": "b" * 64,
            "created": True,
        }

    monkeypatch.setattr(director_worker, "get_pool", get_pool)
    monkeypatch.setattr(director_worker, "validate_director_intake", validate)
    monkeypatch.setattr(director_worker, "get_text_client_for_tenant", resolve)
    monkeypatch.setattr(director_worker, "DurableDirectorCallJournal", Journal)
    monkeypatch.setattr(
        director_worker,
        "ProductionSingleAttemptTextClient",
        adapt,
    )
    monkeypatch.setattr(
        director_worker,
        "execute_multipass_director",
        execute_director,
    )
    monkeypatch.setattr(
        director_worker,
        "persist_completed_director_execution",
        persist,
    )

    result = await director_worker.run_reserved_director_stage(
        tenant_id=TENANT_ID,
        video_id=VIDEO_ID,
        schedule_id=SCHEDULE_ID,
        director_job_id=DIRECTOR_JOB_ID,
    )

    assert result == {
        "status": "completed",
        "created": True,
        "execution_id": "execution-1",
        "director_contract_id": "contract-1",
        "execution_hash": "b" * 64,
        "actual_spend_cents": 42,
    }
    pending = conn.state["pending_custom_film_plan"]
    assert pending["status"] == "director_stage_completed"
    assert pending["provider_calls_started"] is True
    assert pending["spend_recorded_cents"] == 42
    assert pending["director_contract_id"] == "contract-1"
    execute_call = next(value for name, value in calls if name == "execute")
    assert execute_call["stage_contract"] == {"immutable": "stage"}
    assert execute_call["user_request"] == "A courier exposes a hidden route."
    assert execute_call["client"] == "one-request-adapter"
    assert isinstance(execute_call["journal"], Journal)
    assert any("status = 'custom_film_directed'" in sql for sql, _ in conn.updates)


@pytest.mark.asyncio
async def test_worker_replay_returns_existing_execution_without_provider(
    monkeypatch,
):
    existing = {
        "id": "execution-1",
        "director_contract_id": "contract-1",
        "execution_hash": "b" * 64,
        "actual_spend_nusd": 123_000,
        "actual_spend_cents": 1,
    }
    conn = _Connection(_state(), existing=existing)

    async def get_pool():
        return _Pool(conn)

    def validate(_raw):
        return {
            "prospective_plan_id": PLAN_ID,
            "stage_contract": {"immutable": "stage"},
        }

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("completed worker replay reached the provider")

    monkeypatch.setattr(director_worker, "get_pool", get_pool)
    monkeypatch.setattr(director_worker, "validate_director_intake", validate)
    monkeypatch.setattr(
        director_worker,
        "get_text_client_for_tenant",
        forbidden,
    )

    result = await director_worker.run_reserved_director_stage(
        tenant_id=TENANT_ID,
        video_id=VIDEO_ID,
        schedule_id=SCHEDULE_ID,
        director_job_id=DIRECTOR_JOB_ID,
    )

    assert result == {
        "status": "completed",
        "created": False,
        "execution_id": "execution-1",
        "director_contract_id": "contract-1",
        "execution_hash": "b" * 64,
        "actual_spend_nusd": 123_000,
        "actual_spend_cents": 1,
    }
