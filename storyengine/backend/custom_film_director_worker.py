"""Durable production worker for one approved multipass director stage."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from typing import Any

from custom_film_contract import CustomFilmContractError, canonical_json
from custom_film_director_activation import (
    DIRECTOR_EXECUTION_MODEL,
    validate_director_intake,
)
from custom_film_director_multipass_executor import execute_multipass_director
from custom_film_director_provider import ProductionSingleAttemptTextClient
from custom_film_director_receipts import (
    DurableDirectorCallJournal,
    persist_completed_director_execution,
)
from database import get_pool
from kie_unified import get_text_client_for_tenant


def _worker_error(message: str) -> CustomFilmContractError:
    return CustomFilmContractError(
        f"{message}; no additional director attempt was started"
    )


def _object(value: Any, label: str) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise _worker_error(f"Custom Film stored {label} is invalid") from exc
    if not isinstance(value, Mapping):
        raise _worker_error(f"Custom Film stored {label} is invalid")
    return copy.deepcopy(dict(value))


async def run_reserved_director_stage(
    *,
    tenant_id: str,
    video_id: str,
    schedule_id: str,
    director_job_id: str,
) -> dict[str, Any]:
    """Execute and persist exactly the approved Stage 1 schedule."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        conversation = await conn.fetchrow(
            """SELECT id, state
               FROM chat_conversations
               WHERE tenant_id = $1 AND video_id = $2
               ORDER BY updated_at DESC
               LIMIT 1""",
            tenant_id,
            video_id,
        )
        if not conversation:
            raise _worker_error("Custom Film director conversation was not found")
        state = _object(conversation["state"], "conversation state")
        pending = state.get("pending_custom_film_plan")
        if (
            not isinstance(pending, Mapping)
            or pending.get("execution_model") != DIRECTOR_EXECUTION_MODEL
            or str(pending.get("video_id") or "") != video_id
            or str(pending.get("director_schedule_id") or "") != schedule_id
            or str(pending.get("director_job_id") or "") != director_job_id
        ):
            raise _worker_error("Custom Film director worker binding changed")
        activation = validate_director_intake(pending.get("director_activation"))
        authority_id = str(pending.get("stage_authority_id") or "")
        plan_id = activation["prospective_plan_id"]

        existing = await conn.fetchrow(
            """SELECT id, director_contract_id, execution_hash,
                      actual_spend_nusd, actual_spend_cents
               FROM custom_film_director_executions
               WHERE tenant_id = $1 AND schedule_id = $2""",
            tenant_id,
            schedule_id,
        )
        if existing:
            return {
                "status": "completed",
                "created": False,
                "execution_id": str(existing["id"]),
                "director_contract_id": str(existing["director_contract_id"]),
                "execution_hash": str(existing["execution_hash"]),
                "actual_spend_nusd": int(existing["actual_spend_nusd"]),
                "actual_spend_cents": int(existing["actual_spend_cents"]),
            }

    resolved_client = await get_text_client_for_tenant(tenant_id)
    journal = DurableDirectorCallJournal(
        tenant_id=tenant_id,
        plan_id=plan_id,
        video_id=video_id,
        schedule_id=schedule_id,
        authority_id=authority_id,
        stage_contract=activation["stage_contract"],
    )
    execution = await execute_multipass_director(
        stage_contract=activation["stage_contract"],
        user_request=activation["user_request"],
        client=ProductionSingleAttemptTextClient(resolved_client),
        journal=journal,
    )

    async with pool.acquire() as conn, conn.transaction():
        persisted = await persist_completed_director_execution(
            conn,
            tenant_id=tenant_id,
            plan_id=plan_id,
            video_id=video_id,
            schedule_id=schedule_id,
            authority_id=authority_id,
            stage_contract=activation["stage_contract"],
            execution_result=execution,
        )
        latest = await conn.fetchrow(
            """SELECT state
               FROM chat_conversations
               WHERE tenant_id = $1 AND id = $2 AND video_id = $3
               FOR UPDATE""",
            tenant_id,
            str(conversation["id"]),
            video_id,
        )
        if not latest:
            raise _worker_error("Custom Film director conversation changed")
        latest_state = _object(latest["state"], "conversation state")
        latest_pending = latest_state.get("pending_custom_film_plan")
        if (
            not isinstance(latest_pending, dict)
            or str(latest_pending.get("director_job_id") or "") != director_job_id
            or str(latest_pending.get("director_schedule_id") or "") != schedule_id
        ):
            raise _worker_error("Custom Film director completion binding changed")
        latest_pending["status"] = "director_stage_completed"
        latest_pending["director_contract_id"] = persisted["director_contract_id"]
        latest_pending["director_execution_id"] = persisted["id"]
        latest_pending["director_execution_hash"] = persisted["execution_hash"]
        latest_pending["spend_recorded_cents"] = execution["actual_spend_cents"]
        latest_pending["provider_calls_started"] = execution["terminal_call_count"] > 0
        await conn.execute(
            """UPDATE chat_conversations
               SET state = $3::jsonb, updated_at = now()
               WHERE tenant_id = $1 AND id = $2 AND video_id = $4""",
            tenant_id,
            str(conversation["id"]),
            canonical_json(latest_state),
            video_id,
        )
        await conn.execute(
            """UPDATE videos
               SET status = 'custom_film_directed', updated_at = now()
               WHERE tenant_id = $1 AND id = $2""",
            tenant_id,
            video_id,
        )
    return {
        "status": "completed",
        "created": persisted["created"],
        "execution_id": persisted["id"],
        "director_contract_id": persisted["director_contract_id"],
        "execution_hash": persisted["execution_hash"],
        "actual_spend_cents": execution["actual_spend_cents"],
    }
