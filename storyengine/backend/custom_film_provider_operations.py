"""Durable provider-operation journal for Custom Film section stages.

The section runtime writes its stable ``operation_id`` before a stage may cross
the provider boundary.  This journal binds that identity to one immutable
provider request and records the provider's own task identity/result.  A
restart may query a known provider task or repeat an idempotent request with
the same operation ID; an opaque provider operation is never guessed or
blindly retried.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

import database
from custom_film_contract import CustomFilmContractError


RECONCILIATION_QUERY = "provider_query"
RECONCILIATION_IDEMPOTENCY = "provider_idempotency"
RECONCILIATION_NONE = "none"
RECONCILIATION_MODES = frozenset(
    {
        RECONCILIATION_QUERY,
        RECONCILIATION_IDEMPOTENCY,
        RECONCILIATION_NONE,
    }
)
OPERATION_STATES = frozenset(
    {
        "prepared",
        "submitted",
        "completed",
        "failed",
        "reconciliation_required",
    }
)
_OPERATION_ID_RE = re.compile(r"^custom-film-op:[0-9a-f]{64}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def _object(value: Any, name: str) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            value = None
    if not isinstance(value, Mapping):
        raise CustomFilmContractError(f"Custom Film provider {name} is invalid")
    return copy.deepcopy(dict(value))


def _updated_once(result: Any) -> bool:
    if isinstance(result, str):
        return result.rsplit(" ", 1)[-1] == "1"
    if isinstance(result, int):
        return result == 1
    return bool(result)


@dataclass(frozen=True)
class ProviderOperationSpec:
    """Immutable provider request identity chosen by a concrete stage seam."""

    provider: str
    request_hash: str
    reconciliation_mode: str

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise CustomFilmContractError("Custom Film provider name is missing")
        if not _HASH_RE.fullmatch(self.request_hash):
            raise CustomFilmContractError(
                "Custom Film provider request hash is invalid"
            )
        if self.reconciliation_mode not in RECONCILIATION_MODES:
            raise CustomFilmContractError(
                "Custom Film provider reconciliation mode is unsupported"
            )


@dataclass(frozen=True)
class ProviderOperationRecord:
    tenant_id: str
    video_id: str
    runtime_job_id: str
    runtime_hash: str
    stage_key: str
    operation_id: str
    provider: str
    request_hash: str
    reconciliation_mode: str
    state: str
    provider_operation_id: str | None
    result: Mapping[str, Any] | None
    reconciliation_detail: str | None


def _record(row: Mapping[str, Any]) -> ProviderOperationRecord:
    state = str(row.get("state") or "")
    mode = str(row.get("reconciliation_mode") or "")
    operation_id = str(row.get("operation_id") or "")
    runtime_hash = str(row.get("runtime_hash") or "")
    request_hash = str(row.get("request_hash") or "")
    if (
        state not in OPERATION_STATES
        or mode not in RECONCILIATION_MODES
        or not _OPERATION_ID_RE.fullmatch(operation_id)
        or not _HASH_RE.fullmatch(runtime_hash)
        or not _HASH_RE.fullmatch(request_hash)
    ):
        raise CustomFilmContractError(
            "Custom Film provider operation journal is invalid"
        )
    raw_result = row.get("result")
    result = None if raw_result is None else _object(raw_result, "result")
    return ProviderOperationRecord(
        tenant_id=str(row.get("tenant_id") or ""),
        video_id=str(row.get("video_id") or ""),
        runtime_job_id=str(row.get("runtime_job_id") or ""),
        runtime_hash=runtime_hash,
        stage_key=str(row.get("stage_key") or ""),
        operation_id=operation_id,
        provider=str(row.get("provider") or ""),
        request_hash=request_hash,
        reconciliation_mode=mode,
        state=state,
        provider_operation_id=(
            str(row["provider_operation_id"])
            if row.get("provider_operation_id") is not None
            else None
        ),
        result=result,
        reconciliation_detail=(
            str(row["reconciliation_detail"])
            if row.get("reconciliation_detail") is not None
            else None
        ),
    )


def _assert_exact(
    record: ProviderOperationRecord,
    *,
    tenant_id: str,
    video_id: str,
    runtime_job_id: str,
    runtime_hash: str,
    stage_key: str,
    operation_id: str,
    spec: ProviderOperationSpec,
) -> None:
    expected = (
        tenant_id,
        video_id,
        runtime_job_id,
        runtime_hash,
        stage_key,
        operation_id,
        spec.provider,
        spec.request_hash,
        spec.reconciliation_mode,
    )
    actual = (
        record.tenant_id,
        record.video_id,
        record.runtime_job_id,
        record.runtime_hash,
        record.stage_key,
        record.operation_id,
        record.provider,
        record.request_hash,
        record.reconciliation_mode,
    )
    if actual != expected:
        raise CustomFilmContractError(
            "Custom Film provider operation identity changed; no provider "
            "work was started"
        )


async def prepare_operation(
    *,
    tenant_id: str,
    video_id: str,
    runtime_job_id: str,
    runtime_hash: str,
    stage_key: str,
    operation_id: str,
    spec: ProviderOperationSpec,
) -> ProviderOperationRecord:
    """Insert or exactly reload the write-ahead provider operation."""
    if not _OPERATION_ID_RE.fullmatch(operation_id):
        raise CustomFilmContractError(
            "Custom Film provider operation ID is invalid"
        )
    if not _HASH_RE.fullmatch(runtime_hash):
        raise CustomFilmContractError(
            "Custom Film provider runtime hash is invalid"
        )
    if not stage_key or not runtime_job_id:
        raise CustomFilmContractError(
            "Custom Film provider operation identity is incomplete"
        )
    pool = await database.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO custom_film_provider_operations
                 (tenant_id, video_id, runtime_job_id, runtime_hash, stage_key,
                  operation_id, provider, request_hash, reconciliation_mode,
                  state)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'prepared')
               ON CONFLICT (operation_id) DO NOTHING""",
            tenant_id,
            video_id,
            runtime_job_id,
            runtime_hash,
            stage_key,
            operation_id,
            spec.provider,
            spec.request_hash,
            spec.reconciliation_mode,
        )
        row = await conn.fetchrow(
            """SELECT tenant_id, video_id, runtime_job_id, runtime_hash,
                      stage_key, operation_id, provider, request_hash,
                      reconciliation_mode, state, provider_operation_id, result,
                      reconciliation_detail
               FROM custom_film_provider_operations
               WHERE operation_id = $1""",
            operation_id,
        )
    if not row:
        raise CustomFilmContractError(
            "Custom Film provider operation could not be reserved"
        )
    record = _record(row)
    _assert_exact(
        record,
        tenant_id=tenant_id,
        video_id=video_id,
        runtime_job_id=runtime_job_id,
        runtime_hash=runtime_hash,
        stage_key=stage_key,
        operation_id=operation_id,
        spec=spec,
    )
    return record


async def load_operation(operation_id: str) -> ProviderOperationRecord:
    if not _OPERATION_ID_RE.fullmatch(operation_id):
        raise CustomFilmContractError(
            "Custom Film provider operation ID is invalid"
        )
    pool = await database.get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT tenant_id, video_id, runtime_job_id, runtime_hash,
                      stage_key, operation_id, provider, request_hash,
                      reconciliation_mode, state, provider_operation_id, result,
                      reconciliation_detail
               FROM custom_film_provider_operations
               WHERE operation_id = $1""",
            operation_id,
        )
    if not row:
        raise CustomFilmContractError(
            "Custom Film provider reconciliation state is missing; retry is blocked"
        )
    return _record(row)


async def mark_submitted(
    operation_id: str,
    provider_operation_id: str,
) -> ProviderOperationRecord:
    """Persist the provider query handle without allowing it to change."""
    provider_operation_id = str(provider_operation_id or "").strip()
    if not provider_operation_id:
        raise CustomFilmContractError(
            "Custom Film provider task identity is missing"
        )
    pool = await database.get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """UPDATE custom_film_provider_operations
               SET state = 'submitted', provider_operation_id = $2,
                   submitted_at = COALESCE(submitted_at, now()),
                   updated_at = now()
               WHERE operation_id = $1
                 AND state IN ('prepared', 'submitted')
                 AND (
                   provider_operation_id IS NULL
                   OR provider_operation_id = $2
                 )""",
            operation_id,
            provider_operation_id,
        )
    if not _updated_once(result):
        raise CustomFilmContractError(
            "Custom Film provider task identity changed; retry is blocked"
        )
    return await load_operation(operation_id)


async def mark_completed(
    operation_id: str,
    result_value: Mapping[str, Any] | None,
    *,
    conn: Any = None,
) -> None:
    """Record one durable result; optionally join the caller's checkpoint tx."""
    result_object = _object(result_value or {}, "result")

    async def _write(connection: Any) -> None:
        result = await connection.execute(
            """UPDATE custom_film_provider_operations
               SET state = 'completed', result = $2::jsonb,
                   completed_at = COALESCE(completed_at, now()),
                   updated_at = now()
               WHERE operation_id = $1
                 AND state IN ('prepared', 'submitted', 'completed')
                 AND (result IS NULL OR result = $2::jsonb)""",
            operation_id,
            json.dumps(result_object, sort_keys=True, separators=(",", ":")),
        )
        if not _updated_once(result):
            raise CustomFilmContractError(
                "Custom Film provider result changed; retry is blocked"
            )

    if conn is not None:
        await _write(conn)
        return
    pool = await database.get_pool()
    async with pool.acquire() as connection:
        await _write(connection)


async def mark_reconciliation_required(
    operation_id: str,
    detail: str,
) -> None:
    """Expose a controlled fail-closed state instead of leaving ambiguity."""
    detail = str(detail or "").strip()[:500]
    if not detail:
        detail = "Automatic provider reconciliation is blocked"
    pool = await database.get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """UPDATE custom_film_provider_operations
               SET state = 'reconciliation_required',
                   reconciliation_detail = $2,
                   updated_at = now()
               WHERE operation_id = $1
                 AND state IN ('prepared', 'submitted',
                               'reconciliation_required')""",
            operation_id,
            detail,
        )
    if not _updated_once(result):
        raise CustomFilmContractError(
            "Custom Film provider reconciliation state could not be recorded"
        )


def reconciliation_action(record: ProviderOperationRecord) -> str:
    """Return the only safe next action for an unresolved operation."""
    if record.state == "completed":
        return "return_completed"
    if record.state in {"failed", "reconciliation_required"}:
        raise CustomFilmContractError(
            "Custom Film provider operation requires manual reconciliation; "
            "automatic retry is blocked"
        )
    if record.reconciliation_mode == RECONCILIATION_IDEMPOTENCY:
        return "retry_same_operation"
    if record.reconciliation_mode == RECONCILIATION_QUERY:
        if not record.provider_operation_id:
            raise CustomFilmContractError(
                "Custom Film provider task identity was not durably recorded; "
                "automatic retry is blocked"
            )
        return "query_provider"
    raise CustomFilmContractError(
        "This provider cannot query or deduplicate the unresolved Custom Film "
        "operation; automatic retry is blocked"
    )
