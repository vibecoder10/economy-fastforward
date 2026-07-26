"""Durable receipt and final-persistence seam for multipass direction.

Every claim commits before its caller may issue one external request. A claim
without a terminal event is reconciliation-required forever unless an operator
reconciles it outside this module. No production text adapter is defined here.
"""

from __future__ import annotations

import copy
import inspect
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

from custom_film_contract import (
    CustomFilmContractError,
    canonical_hash,
    canonical_json,
)
from custom_film_director import persist_director_contract
from custom_film_director_multipass import (
    MULTIPASS_EXECUTION_MODEL,
    validate_multipass_stage_contract,
)
from custom_film_director_multipass_executor import (
    InMemoryDirectorCallJournal,
    build_director_call_event,
    validate_multipass_execution_result,
)

PoolFactory = Callable[[], Awaitable[Any] | Any]
NANOUSD_PER_USD = Decimal("1000000000")


def _receipt_error(message: str) -> CustomFilmContractError:
    return CustomFilmContractError(
        f"{message}; no director call was started and no provider was called"
    )


def _uuid(value: Any, label: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _receipt_error(f"Custom Film {label} is invalid") from exc


def _json_value(value: Any, label: str) -> Any:
    if not isinstance(value, str):
        return copy.deepcopy(value)
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise _receipt_error(f"Custom Film stored {label} is invalid") from exc


def _event_sequence(event_kind: str) -> int:
    if event_kind == "attempt_started":
        return 0
    if event_kind in {"attempt_completed", "attempt_failed"}:
        return 1
    raise _receipt_error("Custom Film director event kind is invalid")


async def _default_pool_factory() -> Any:
    from database import get_pool

    return await get_pool()


class DurableDirectorCallJournal:
    """Database-backed implementation of the executor's receipt protocol."""

    def __init__(
        self,
        *,
        tenant_id: str,
        plan_id: str,
        video_id: str,
        schedule_id: str,
        authority_id: str,
        stage_contract: Mapping[str, Any],
        pool_factory: PoolFactory | None = None,
    ):
        self.tenant_id = _uuid(tenant_id, "tenant identity")
        self.plan_id = _uuid(plan_id, "plan identity")
        self.video_id = _uuid(video_id, "video identity")
        self.schedule_id = _uuid(schedule_id, "schedule identity")
        self.authority_id = _uuid(authority_id, "authority identity")
        self.stage_contract = validate_multipass_stage_contract(stage_contract)
        manifest = self.stage_contract["manifest"]
        if manifest["plan_id"] != self.plan_id:
            raise _receipt_error("Custom Film director plan identity changed")
        self.schedule = self.stage_contract["schedule"]
        self.operations = {
            row["operation_id"]: copy.deepcopy(row) for row in self.schedule["tasks"]
        }
        self.order_by_operation = {
            row["operation_id"]: row["order_index"] for row in self.schedule["tasks"]
        }
        self.pool_factory = pool_factory or _default_pool_factory
        self._event_cache: dict[str, list[dict[str, Any]]] = {}

    async def _pool(self) -> Any:
        value = self.pool_factory()
        return await value if inspect.isawaitable(value) else value

    def _authorized_operation(
        self,
        raw_operation: Mapping[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(raw_operation, Mapping):
            raise _receipt_error("Custom Film director operation is invalid")
        operation_id = str(raw_operation.get("operation_id") or "")
        expected = self.operations.get(operation_id)
        if expected is None or canonical_json(raw_operation) != canonical_json(
            expected
        ):
            raise _receipt_error("Custom Film director operation is not authorized")
        return copy.deepcopy(expected)

    async def _load_schedule(self, conn: Any) -> None:
        row = await conn.fetchrow(
            """SELECT id, authority_id, schedule, schedule_hash
               FROM custom_film_director_stage_schedules
               WHERE tenant_id = $1 AND id = $2 AND plan_id = $3
                 AND video_id = $4
               FOR SHARE""",
            self.tenant_id,
            self.schedule_id,
            self.plan_id,
            self.video_id,
        )
        if (
            not row
            or str(row["authority_id"]) != self.authority_id
            or str(row["schedule_hash"]) != self.schedule["schedule_hash"]
            or canonical_json(_json_value(row["schedule"], "director schedule"))
            != canonical_json(self.schedule)
        ):
            raise _receipt_error("Custom Film durable director schedule changed")

    async def _load_events(
        self,
        conn: Any,
        operation_id: str,
        *,
        lock: bool,
    ) -> list[dict[str, Any]]:
        suffix = " FOR UPDATE" if lock else ""
        rows = await conn.fetch(
            """SELECT event
               FROM custom_film_director_call_events
               WHERE tenant_id = $1 AND schedule_id = $2 AND operation_id = $3
               ORDER BY event_sequence"""
            + suffix,
            self.tenant_id,
            self.schedule_id,
            operation_id,
        )
        events = [_json_value(row["event"], "director call event") for row in rows]
        InMemoryDirectorCallJournal(events)
        self._event_cache[operation_id] = copy.deepcopy(events)
        return events

    async def _insert_event(
        self,
        conn: Any,
        operation: Mapping[str, Any],
        event: Mapping[str, Any],
    ) -> bool:
        stored = await conn.fetchrow(
            """INSERT INTO custom_film_director_call_events
                 (tenant_id, plan_id, video_id, schedule_id, authority_id,
                  operation_id, operation_kind, operation_order_index,
                  event_sequence, event_kind, input_hash, output_hash,
                  request_id, actual_cost_nusd, actual_cost_cents, event, event_hash)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
                       $12, $13, $14, $15, $16::jsonb, $17)
               ON CONFLICT DO NOTHING
               RETURNING id""",
            self.tenant_id,
            self.plan_id,
            self.video_id,
            self.schedule_id,
            self.authority_id,
            operation["operation_id"],
            operation["operation_kind"],
            operation["order_index"],
            _event_sequence(str(event["event_kind"])),
            event["event_kind"],
            event["input_hash"],
            event.get("output_hash"),
            event.get("request_id"),
            int(event.get("actual_cost_nusd") or 0),
            int(event.get("actual_cost_cents") or 0),
            canonical_json(event),
            event["event_hash"],
        )
        return bool(stored)

    def _claim_result(
        self,
        events: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        if len(events) == 1:
            return {
                "status": "reconciliation_required",
                "event": copy.deepcopy(dict(events[0])),
            }
        terminal = copy.deepcopy(dict(events[-1]))
        return {
            "status": (
                "completed"
                if terminal["event_kind"] == "attempt_completed"
                else "failed"
            ),
            "event": terminal,
        }

    async def claim(self, raw_operation: Mapping[str, Any]) -> Mapping[str, Any]:
        operation = self._authorized_operation(raw_operation)
        pool = await self._pool()
        async with pool.acquire() as conn, conn.transaction():
            await self._load_schedule(conn)
            events = await self._load_events(
                conn,
                operation["operation_id"],
                lock=True,
            )
            if events:
                return self._claim_result(events)
            started = build_director_call_event(
                operation,
                event_kind="attempt_started",
            )
            if await self._insert_event(conn, operation, started):
                self._event_cache[operation["operation_id"]] = [started]
                return {"status": "claimed", "event": copy.deepcopy(started)}
            events = await self._load_events(
                conn,
                operation["operation_id"],
                lock=True,
            )
            if not events:
                raise _receipt_error("Custom Film director claim was not stored")
            return self._claim_result(events)

    async def _terminal(
        self,
        raw_operation: Mapping[str, Any],
        result: Mapping[str, Any],
        *,
        event_kind: str,
        failure_code: str | None,
        output_payload: Mapping[str, Any] | None,
    ) -> Mapping[str, Any]:
        operation = self._authorized_operation(raw_operation)
        terminal = build_director_call_event(
            operation,
            event_kind=event_kind,
            result=result,
            output_payload=output_payload,
            failure_code=failure_code,
        )
        pool = await self._pool()
        async with pool.acquire() as conn, conn.transaction():
            await self._load_schedule(conn)
            events = await self._load_events(
                conn,
                operation["operation_id"],
                lock=True,
            )
            if not events or events[0]["event_kind"] != "attempt_started":
                raise _receipt_error(
                    "Custom Film director terminal receipt has no durable claim"
                )
            if len(events) == 2:
                if events[1]["event_hash"] != terminal["event_hash"]:
                    raise _receipt_error(
                        "Custom Film director terminal receipt replay changed"
                    )
                return copy.deepcopy(events[1])
            if await self._insert_event(conn, operation, terminal):
                self._event_cache[operation["operation_id"]] = [
                    copy.deepcopy(events[0]),
                    copy.deepcopy(terminal),
                ]
                return copy.deepcopy(terminal)
            events = await self._load_events(
                conn,
                operation["operation_id"],
                lock=True,
            )
            if len(events) != 2 or events[1]["event_hash"] != terminal["event_hash"]:
                raise _receipt_error(
                    "Custom Film director terminal receipt was not stored exactly"
                )
            return copy.deepcopy(events[1])

    async def complete(
        self,
        operation: Mapping[str, Any],
        result: Mapping[str, Any],
        output_payload: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return await self._terminal(
            operation,
            result,
            event_kind="attempt_completed",
            failure_code=None,
            output_payload=output_payload,
        )

    async def fail(
        self,
        operation: Mapping[str, Any],
        result: Mapping[str, Any],
        *,
        failure_code: str,
        output_payload: Mapping[str, Any] | None,
    ) -> Mapping[str, Any]:
        return await self._terminal(
            operation,
            result,
            event_kind="attempt_failed",
            failure_code=failure_code,
            output_payload=output_payload,
        )

    def events(self) -> Sequence[Mapping[str, Any]]:
        rows = [
            event
            for operation_events in self._event_cache.values()
            for event in operation_events
        ]
        return copy.deepcopy(
            sorted(
                rows,
                key=lambda row: (
                    self.order_by_operation[row["operation_id"]],
                    _event_sequence(row["event_kind"]),
                ),
            )
        )


def _execution_summary(
    execution: Mapping[str, Any],
) -> tuple[dict[str, Any], str]:
    event_hashes = [str(row["event_hash"]) for row in execution["receipt_events"]]
    receipt_manifest_hash = canonical_hash(event_hashes)
    actual_spend_nusd = sum(
        int(row.get("actual_cost_nusd") or 0)
        for row in execution["receipt_events"]
        if row.get("event_kind") in {"attempt_completed", "attempt_failed"}
    )
    summary = {
        "execution_model": MULTIPASS_EXECUTION_MODEL,
        "manifest_hash": execution["manifest_hash"],
        "authority_hash": execution["authority_hash"],
        "director_contract_hash": execution["director_contract_hash"],
        "execution_hash": execution["execution_hash"],
        "receipt_manifest_hash": receipt_manifest_hash,
        "receipt_event_hashes": event_hashes,
        "terminal_call_count": execution["terminal_call_count"],
        "actual_spend_cents": execution["actual_spend_cents"],
        "actual_spend_nusd": actual_spend_nusd,
    }
    return summary, receipt_manifest_hash


async def _persist_generation_ledger(
    conn: Any,
    *,
    tenant_id: str,
    video_id: str,
    events: Sequence[Mapping[str, Any]],
) -> None:
    """Atomically reconcile every terminal provider receipt into canonical spend."""
    terminals = [
        row
        for row in events
        if row.get("event_kind") in {"attempt_completed", "attempt_failed"}
    ]
    for event in terminals:
        request_id = str(event.get("request_id") or "")
        model = str(event.get("model") or "")
        actual_nusd = int(event.get("actual_cost_nusd") or 0)
        if not request_id or not model or actual_nusd < 0:
            raise _receipt_error("Custom Film director ledger receipt is incomplete")
        actual_usd = Decimal(actual_nusd) / NANOUSD_PER_USD
        await conn.execute(
            """INSERT INTO generation_ledger
                 (tenant_id, video_id, stage, model, units, unit_cost,
                  actual_cost, kie_task_id)
               VALUES ($1, $2, 'custom_film_director', $3, 1, $4, $4, $5)
               ON CONFLICT (video_id, stage, kie_task_id)
                 WHERE kie_task_id IS NOT NULL DO NOTHING""",
            tenant_id,
            video_id,
            model,
            actual_usd,
            request_id,
        )
        stored = await conn.fetchrow(
            """SELECT tenant_id, video_id, stage, model, units, unit_cost,
                      actual_cost, kie_task_id
               FROM generation_ledger
               WHERE tenant_id = $1 AND video_id = $2
                 AND stage = 'custom_film_director' AND kie_task_id = $3""",
            tenant_id,
            video_id,
            request_id,
        )
        if (
            not stored
            or str(stored["model"]) != model
            or Decimal(str(stored["units"])) != Decimal(1)
            or Decimal(str(stored["unit_cost"])) != actual_usd
            or Decimal(str(stored["actual_cost"])) != actual_usd
        ):
            raise _receipt_error("Custom Film director ledger receipt changed")
    await conn.execute(
        """UPDATE videos
           SET total_cost = (
             SELECT COALESCE(SUM(actual_cost), 0)
             FROM generation_ledger
             WHERE video_id = $1
           ), updated_at = now()
           WHERE tenant_id = $2 AND id = $1""",
        video_id,
        tenant_id,
    )


async def reconcile_director_generation_ledger(
    conn: Any,
    *,
    tenant_id: str,
    video_id: str,
    schedule_id: str,
) -> dict[str, int]:
    """Record every exact terminal receipt, including failed executions.

    A claimed operation without a terminal event remains explicitly
    reconciliation-required and is never guessed into spend.
    """
    normalized_tenant_id = _uuid(tenant_id, "tenant identity")
    normalized_video_id = _uuid(video_id, "video identity")
    normalized_schedule_id = _uuid(schedule_id, "schedule identity")
    receipt_rows = await conn.fetch(
        """SELECT event
           FROM custom_film_director_call_events
           WHERE tenant_id = $1 AND schedule_id = $2
           ORDER BY operation_order_index, event_sequence
           FOR SHARE""",
        normalized_tenant_id,
        normalized_schedule_id,
    )
    events = [_json_value(row["event"], "director call event") for row in receipt_rows]
    if events:
        InMemoryDirectorCallJournal(events)
    by_operation: dict[str, list[Mapping[str, Any]]] = {}
    for event in events:
        by_operation.setdefault(str(event["operation_id"]), []).append(event)
    unpaired_started_count = sum(
        1
        for operation_events in by_operation.values()
        if len(operation_events) == 1
        and operation_events[0].get("event_kind") == "attempt_started"
    )
    unreconciled_terminals = [
        event
        for event in events
        if event.get("event_kind") in {"attempt_completed", "attempt_failed"}
        and (
            str(event.get("request_id") or "") in {"", "unknown"}
            or str(event.get("model") or "") in {"", "unknown"}
        )
    ]
    ledger_events = [event for event in events if event not in unreconciled_terminals]
    await _persist_generation_ledger(
        conn,
        tenant_id=normalized_tenant_id,
        video_id=normalized_video_id,
        events=ledger_events,
    )
    terminals = [
        event
        for event in events
        if event.get("event_kind") in {"attempt_completed", "attempt_failed"}
    ]
    return {
        "terminal_call_count": len(terminals),
        "unpaired_started_count": unpaired_started_count,
        "reconciliation_required_count": (
            unpaired_started_count + len(unreconciled_terminals)
        ),
        "actual_spend_nusd": sum(
            int(event.get("actual_cost_nusd") or 0) for event in terminals
        ),
        "actual_spend_cents": sum(
            int(event.get("actual_cost_cents") or 0) for event in terminals
        ),
    }


async def persist_completed_director_execution(
    conn: Any,
    *,
    tenant_id: str,
    plan_id: str,
    video_id: str,
    schedule_id: str,
    authority_id: str,
    stage_contract: Mapping[str, Any],
    execution_result: Mapping[str, Any],
) -> dict[str, Any]:
    """Persist one reconciled execution and director contract in one transaction.

    The caller owns the surrounding transaction. Receipt claims and terminals
    must already be durable; this function only reads them and refuses drift.
    """
    normalized_tenant_id = _uuid(tenant_id, "tenant identity")
    normalized_plan_id = _uuid(plan_id, "plan identity")
    normalized_video_id = _uuid(video_id, "video identity")
    normalized_schedule_id = _uuid(schedule_id, "schedule identity")
    normalized_authority_id = _uuid(authority_id, "authority identity")
    approved = validate_multipass_stage_contract(stage_contract)
    execution = validate_multipass_execution_result(
        execution_result,
        stage_contract=approved,
    )
    if approved["manifest"]["plan_id"] != normalized_plan_id:
        raise _receipt_error("Custom Film director plan identity changed")
    schedule_row = await conn.fetchrow(
        """SELECT id, authority_id, schedule, schedule_hash
           FROM custom_film_director_stage_schedules
           WHERE tenant_id = $1 AND id = $2 AND plan_id = $3 AND video_id = $4
           FOR SHARE""",
        normalized_tenant_id,
        normalized_schedule_id,
        normalized_plan_id,
        normalized_video_id,
    )
    if (
        not schedule_row
        or str(schedule_row["authority_id"]) != normalized_authority_id
        or str(schedule_row["schedule_hash"]) != approved["schedule"]["schedule_hash"]
        or canonical_json(_json_value(schedule_row["schedule"], "director schedule"))
        != canonical_json(approved["schedule"])
    ):
        raise _receipt_error("Custom Film durable director schedule changed")

    receipt_rows = await conn.fetch(
        """SELECT event
           FROM custom_film_director_call_events
           WHERE tenant_id = $1 AND schedule_id = $2
           ORDER BY operation_order_index, event_sequence
           FOR SHARE""",
        normalized_tenant_id,
        normalized_schedule_id,
    )
    durable_events = [
        _json_value(row["event"], "director call event") for row in receipt_rows
    ]
    if canonical_json(durable_events) != canonical_json(execution["receipt_events"]):
        raise _receipt_error("Custom Film durable director receipts changed")
    InMemoryDirectorCallJournal(durable_events)
    await _persist_generation_ledger(
        conn,
        tenant_id=normalized_tenant_id,
        video_id=normalized_video_id,
        events=durable_events,
    )

    persisted = await persist_director_contract(
        conn,
        tenant_id=normalized_tenant_id,
        video_id=normalized_video_id,
        plan_id=normalized_plan_id,
        plan_hash=approved["manifest"]["plan_hash"],
        director_contract=execution["director_contract"],
    )
    summary, receipt_manifest_hash = _execution_summary(execution)
    stored = await conn.fetchrow(
        """INSERT INTO custom_film_director_executions
             (tenant_id, plan_id, video_id, schedule_id, authority_id,
              director_contract_id, execution_hash, receipt_manifest_hash,
              actual_spend_nusd, actual_spend_cents, execution)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb)
           ON CONFLICT DO NOTHING
           RETURNING id""",
        normalized_tenant_id,
        normalized_plan_id,
        normalized_video_id,
        normalized_schedule_id,
        normalized_authority_id,
        persisted["id"],
        execution["execution_hash"],
        receipt_manifest_hash,
        summary["actual_spend_nusd"],
        execution["actual_spend_cents"],
        canonical_json(summary),
    )
    if stored:
        return {
            "id": str(stored["id"]),
            "director_contract_id": persisted["id"],
            "director_revision": persisted["revision"],
            "execution_hash": execution["execution_hash"],
            "created": True,
        }
    existing = await conn.fetchrow(
        """SELECT id, director_contract_id, execution_hash,
                  receipt_manifest_hash, actual_spend_nusd,
                  actual_spend_cents, execution
           FROM custom_film_director_executions
           WHERE tenant_id = $1 AND schedule_id = $2""",
        normalized_tenant_id,
        normalized_schedule_id,
    )
    observed = (
        {
            "director_contract_id": str(existing["director_contract_id"]),
            "execution_hash": str(existing["execution_hash"]),
            "receipt_manifest_hash": str(existing["receipt_manifest_hash"]),
            "actual_spend_nusd": int(existing["actual_spend_nusd"]),
            "actual_spend_cents": int(existing["actual_spend_cents"]),
            "execution": _json_value(
                existing["execution"],
                "director execution",
            ),
        }
        if existing
        else None
    )
    expected = {
        "director_contract_id": persisted["id"],
        "execution_hash": execution["execution_hash"],
        "receipt_manifest_hash": receipt_manifest_hash,
        "actual_spend_nusd": summary["actual_spend_nusd"],
        "actual_spend_cents": execution["actual_spend_cents"],
        "execution": summary,
    }
    if canonical_json(observed) != canonical_json(expected):
        raise _receipt_error("Custom Film director execution replay changed")
    return {
        "id": str(existing["id"]),
        "director_contract_id": persisted["id"],
        "director_revision": persisted["revision"],
        "execution_hash": execution["execution_hash"],
        "created": False,
    }
