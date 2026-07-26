"""Fail-closed stage schedules for the Custom Film director loop.

This module turns one approved stage authority into a deterministic set of
work items. It does not select a provider, call a provider, write an artifact,
consume an authority, or spend money.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from custom_film_contract import (
    CustomFilmContractError,
    canonical_hash,
    canonical_json,
)
from custom_film_director import (
    THIRD_PERSON_NARRATOR_ID,
    build_remotion_admission,
    compile_stage_authority,
    validate_director_contract,
)

DIRECTOR_OPERATION_PREFIX = "custom-film-director-op:"

REQUIRED_OPERATION_KINDS: dict[str, tuple[str, ...]] = {
    "script_director": ("director_plan",),
    "references": ("character_reference", "environment_reference"),
    "storyboards": ("storyboard_image",),
    "final_pictures": ("final_picture",),
    "animation_voice": ("animation_clip", "voice_line"),
    "assembly": ("remotion_assembly",),
}


def _runtime_error(message: str) -> CustomFilmContractError:
    return CustomFilmContractError(
        f"{message}; no stage task was started and no provider was called"
    )


def _validate_hash(value: Any, label: str) -> str:
    digest = str(value or "")
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise _runtime_error(f"Custom Film {label} is invalid")
    return digest


def _json_value(value: Any, label: str) -> Any:
    if not isinstance(value, str):
        return copy.deepcopy(value)
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise _runtime_error(f"Custom Film stored {label} is invalid") from exc


def _verified_gate(
    raw_gate: Mapping[str, Any] | None,
    *,
    hash_field: str,
    director_contract_hash: str,
) -> tuple[dict[str, Any], str]:
    if not isinstance(raw_gate, Mapping):
        raise _runtime_error(f"Custom Film {hash_field} is missing")
    payload = copy.deepcopy(dict(raw_gate))
    claimed_hash = _validate_hash(payload.pop(hash_field, None), hash_field)
    if (
        canonical_hash(payload) != claimed_hash
        or payload.get("director_contract_hash") != director_contract_hash
    ):
        raise _runtime_error(f"Custom Film {hash_field} changed")
    return payload, claimed_hash


def _approval_map(
    gate: Mapping[str, Any],
    *,
    list_field: str,
    identity_fields: Sequence[str],
) -> dict[tuple[str, ...], dict[str, Any]]:
    rows = gate.get(list_field)
    if not isinstance(rows, list):
        raise _runtime_error(f"Custom Film {list_field} evidence is invalid")
    result: dict[tuple[str, ...], dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise _runtime_error(f"Custom Film {list_field} evidence is invalid")
        row = copy.deepcopy(dict(raw))
        identity = tuple(str(row.get(field) or "") for field in identity_fields)
        if any(not value for value in identity) or identity in result:
            raise _runtime_error(f"Custom Film {list_field} identities are invalid")
        result[identity] = row
    return result


def expected_stage_bom(
    director_contract: Mapping[str, Any],
    stage: str,
) -> dict[str, int]:
    """Return the minimum exact work counts implied by the director contract."""
    director = validate_director_contract(director_contract)
    shots = director["shots"]
    if stage == "references":
        return {
            "character_reference": len(director["film_bible"]["characters"]),
            "environment_reference": len(director["film_bible"]["environments"]),
        }
    if stage == "storyboards":
        return {"storyboard_image": len(shots)}
    if stage == "final_pictures":
        return {"final_picture": len(shots)}
    if stage == "animation_voice":
        return {
            "animation_clip": len(shots),
            "voice_line": sum(len(shot["spoken_lines"]) for shot in shots),
        }
    if stage == "assembly":
        return {"remotion_assembly": 1}
    raise _runtime_error("Custom Film director stage is unsupported")


def _reconcile_authority_bom(
    authority: Mapping[str, Any],
    *,
    stage: str,
    required_counts: Mapping[str, int],
) -> dict[str, dict[str, Any]]:
    operations = authority.get("operations")
    if not isinstance(operations, list):
        raise _runtime_error("Custom Film stage bill of materials is invalid")
    by_kind = {
        str(operation.get("operation_kind") or ""): copy.deepcopy(operation)
        for operation in operations
        if isinstance(operation, Mapping)
    }
    if len(by_kind) != len(operations):
        raise _runtime_error("Custom Film stage bill of materials is duplicated")

    for kind, expected_count in required_counts.items():
        operation = by_kind.get(kind)
        if expected_count == 0:
            if operation is not None and int(operation.get("count") or 0) != 0:
                raise _runtime_error(f"Custom Film {kind} count changed")
            continue
        if (
            operation is None
            or operation.get("helper_operation") is not False
            or operation.get("count") != expected_count
        ):
            raise _runtime_error(f"Custom Film {kind} count changed")

    required_kinds = set(REQUIRED_OPERATION_KINDS[stage])
    for kind, operation in by_kind.items():
        count = operation.get("count")
        if type(count) is not int or count < 1:
            if kind in required_counts and required_counts[kind] == 0 and count == 0:
                continue
            raise _runtime_error(f"Custom Film {kind} has no schedulable work")
        if kind not in required_kinds and operation.get("helper_operation") is not True:
            raise _runtime_error(
                f"Custom Film unplanned operation {kind} is not identified as helper work"
            )
    if stage == "assembly":
        assembly = by_kind.get("remotion_assembly")
        if assembly is None or assembly.get("unit_max_cents") != 0:
            raise _runtime_error("Custom Film deterministic assembly cannot carry provider spend")
    return by_kind


def _stage_task(
    *,
    stage: str,
    binding_hash: str,
    operation: Mapping[str, Any],
    subject_kind: str,
    subject_id: str,
    order_index: int,
    input_payload: Mapping[str, Any],
) -> dict[str, Any]:
    payload = copy.deepcopy(dict(input_payload))
    input_hash = canonical_hash(payload)
    identity = {
        "stage": stage,
        "binding_hash": binding_hash,
        "operation_kind": operation["operation_kind"],
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "order_index": order_index,
        "input_hash": input_hash,
    }
    return {
        "operation_id": DIRECTOR_OPERATION_PREFIX + canonical_hash(identity),
        **identity,
        "unit_max_cents": int(operation["unit_max_cents"]),
        "helper_operation": bool(operation["helper_operation"]),
        "input_payload": payload,
        "status": "authorized_not_started",
    }


def _helper_tasks(
    *,
    stage: str,
    binding_hash: str,
    operations: Mapping[str, Mapping[str, Any]],
    start_order: int,
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    order_index = start_order
    required = set(REQUIRED_OPERATION_KINDS[stage])
    for operation_kind in sorted(set(operations) - required):
        operation = operations[operation_kind]
        for helper_index in range(int(operation["count"])):
            tasks.append(
                _stage_task(
                    stage=stage,
                    binding_hash=binding_hash,
                    operation=operation,
                    subject_kind="helper",
                    subject_id=f"{operation_kind}:{helper_index + 1}",
                    order_index=order_index,
                    input_payload={
                        "stage": stage,
                        "operation_kind": operation_kind,
                        "helper_index": helper_index + 1,
                        "stage_binding_hash": binding_hash,
                    },
                )
            )
            order_index += 1
    return tasks


def _finalize_schedule(
    *,
    stage: str,
    binding_hash: str,
    upstream_gate_hash: str,
    authority: Mapping[str, Any],
    tasks: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    task_rows = [copy.deepcopy(dict(task)) for task in tasks]
    operation_ids = [str(task["operation_id"]) for task in task_rows]
    if not task_rows or len(operation_ids) != len(set(operation_ids)):
        raise _runtime_error("Custom Film stage task identities are invalid")
    if sum(int(task["unit_max_cents"]) for task in task_rows) != int(
        authority["stage_max_cents"]
    ):
        raise _runtime_error("Custom Film stage tasks do not reconcile to its authority")
    schedule = {
        "schedule_version": 1,
        "stage": stage,
        "stage_binding_hash": binding_hash,
        "upstream_gate_hash": upstream_gate_hash,
        "authority_hash": authority["authority_hash"],
        "quote_hash": authority["quote_hash"],
        "prior_cumulative_cents": authority["prior_cumulative_cents"],
        "approved_cumulative_cents": authority["approved_cumulative_cents"],
        "stage_max_cents": authority["stage_max_cents"],
        "task_count": len(task_rows),
        "tasks": task_rows,
        "provider_calls_started": False,
        "spend_recorded_cents": 0,
    }
    schedule["schedule_hash"] = canonical_hash(schedule)
    return schedule


def validate_stage_schedule(raw_schedule: Mapping[str, Any]) -> dict[str, Any]:
    """Validate an immutable, not-started schedule before persistence."""
    if not isinstance(raw_schedule, Mapping):
        raise _runtime_error("Custom Film director schedule is invalid")
    schedule = copy.deepcopy(dict(raw_schedule))
    claimed_hash = _validate_hash(
        schedule.pop("schedule_hash", None),
        "director schedule hash",
    )
    if canonical_hash(schedule) != claimed_hash:
        raise _runtime_error("Custom Film director schedule changed")
    tasks = schedule.get("tasks")
    if (
        not isinstance(tasks, list)
        or schedule.get("task_count") != len(tasks)
        or not tasks
    ):
        raise _runtime_error("Custom Film director schedule tasks are invalid")
    operation_ids: list[str] = []
    task_max_cents = 0
    for task in tasks:
        if not isinstance(task, Mapping):
            raise _runtime_error("Custom Film director schedule task is invalid")
        operation_id = str(task.get("operation_id") or "")
        if not operation_id.startswith(DIRECTOR_OPERATION_PREFIX):
            raise _runtime_error("Custom Film director operation identity is invalid")
        _validate_hash(
            operation_id.removeprefix(DIRECTOR_OPERATION_PREFIX),
            "director operation identity",
        )
        input_payload = task.get("input_payload")
        if (
            not isinstance(input_payload, Mapping)
            or canonical_hash(input_payload) != task.get("input_hash")
            or task.get("status") != "authorized_not_started"
        ):
            raise _runtime_error("Custom Film director task input changed")
        identity = {
            "stage": task.get("stage"),
            "binding_hash": task.get("binding_hash"),
            "operation_kind": task.get("operation_kind"),
            "subject_kind": task.get("subject_kind"),
            "subject_id": task.get("subject_id"),
            "order_index": task.get("order_index"),
            "input_hash": task.get("input_hash"),
        }
        if operation_id != DIRECTOR_OPERATION_PREFIX + canonical_hash(identity):
            raise _runtime_error("Custom Film director operation identity changed")
        unit_max_cents = task.get("unit_max_cents")
        if type(unit_max_cents) is not int or unit_max_cents < 0:
            raise _runtime_error("Custom Film director task ceiling is invalid")
        operation_ids.append(operation_id)
        task_max_cents += unit_max_cents
    if (
        len(operation_ids) != len(set(operation_ids))
        or task_max_cents != schedule.get("stage_max_cents")
        or schedule.get("provider_calls_started") is not False
        or schedule.get("spend_recorded_cents") != 0
    ):
        raise _runtime_error("Custom Film director schedule reconciliation failed")
    schedule["schedule_hash"] = claimed_hash
    return schedule


async def persist_stage_authority(
    conn: Any,
    *,
    tenant_id: str,
    plan_id: str,
    video_id: str,
    director_contract_id: str | None,
    approval_hash: str,
    raw_authority: Mapping[str, Any],
    expected_stage: str,
    expected_binding_hash: str,
    expected_upstream_gate_hash: str,
) -> dict[str, Any]:
    """Persist one exact user-approved cumulative authority.

    The caller owns the surrounding transaction. Replaying the identical
    authority converges on the existing row; any identity, quote, amount, BOM,
    or hash drift fails before a schedule or provider operation can exist.
    """
    try:
        normalized_tenant_id = str(UUID(str(tenant_id)))
        normalized_plan_id = str(UUID(str(plan_id)))
        normalized_video_id = str(UUID(str(video_id)))
        normalized_director_id = (
            str(UUID(str(director_contract_id)))
            if director_contract_id is not None
            else None
        )
    except (TypeError, ValueError, AttributeError) as exc:
        raise _runtime_error("Custom Film stage authority identity is invalid") from exc
    normalized_approval_hash = _validate_hash(
        approval_hash,
        "stage approval hash",
    )
    authority = compile_stage_authority(
        raw_authority,
        expected_stage=expected_stage,
        expected_binding_hash=expected_binding_hash,
        expected_upstream_gate_hash=expected_upstream_gate_hash,
    )
    stored = await conn.fetchrow(
        """INSERT INTO custom_film_stage_authorities
             (tenant_id, plan_id, video_id, director_contract_id, stage,
              stage_binding_hash, upstream_gate_hash, quote_hash, approval_hash,
              prior_cumulative_cents, approved_cumulative_cents,
              bill_of_materials, authority, authority_hash)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
                   $12::jsonb, $13::jsonb, $14)
           ON CONFLICT DO NOTHING
           RETURNING id""",
        normalized_tenant_id,
        normalized_plan_id,
        normalized_video_id,
        normalized_director_id,
        authority["stage"],
        authority["stage_binding_hash"],
        authority["upstream_gate_hash"],
        authority["quote_hash"],
        normalized_approval_hash,
        authority["prior_cumulative_cents"],
        authority["approved_cumulative_cents"],
        canonical_json(authority["operations"]),
        canonical_json(authority),
        authority["authority_hash"],
    )
    if stored:
        return {
            "id": str(stored["id"]),
            "authority_hash": authority["authority_hash"],
            "approval_hash": normalized_approval_hash,
            "created": True,
        }

    existing = await conn.fetchrow(
        """SELECT id, plan_id, video_id, director_contract_id, stage,
                  stage_binding_hash, upstream_gate_hash, quote_hash,
                  approval_hash, prior_cumulative_cents,
                  approved_cumulative_cents, bill_of_materials, authority,
                  authority_hash
           FROM custom_film_stage_authorities
           WHERE tenant_id = $1 AND approval_hash = $2""",
        normalized_tenant_id,
        normalized_approval_hash,
    )
    if not existing:
        raise _runtime_error("Custom Film stage authority was not stored")

    row_director_id = (
        str(existing["director_contract_id"])
        if existing.get("director_contract_id") is not None
        else None
    )
    observed = {
        "plan_id": str(existing["plan_id"]),
        "video_id": str(existing["video_id"]),
        "director_contract_id": row_director_id,
        "stage": str(existing["stage"]),
        "stage_binding_hash": str(existing["stage_binding_hash"]),
        "upstream_gate_hash": str(existing["upstream_gate_hash"]),
        "quote_hash": str(existing["quote_hash"]),
        "approval_hash": str(existing["approval_hash"]),
        "prior_cumulative_cents": int(existing["prior_cumulative_cents"]),
        "approved_cumulative_cents": int(existing["approved_cumulative_cents"]),
        "bill_of_materials": _json_value(
            existing["bill_of_materials"],
            "stage bill of materials",
        ),
        "authority": _json_value(existing["authority"], "stage authority"),
        "authority_hash": str(existing["authority_hash"]),
    }
    expected = {
        "plan_id": normalized_plan_id,
        "video_id": normalized_video_id,
        "director_contract_id": normalized_director_id,
        "stage": authority["stage"],
        "stage_binding_hash": authority["stage_binding_hash"],
        "upstream_gate_hash": authority["upstream_gate_hash"],
        "quote_hash": authority["quote_hash"],
        "approval_hash": normalized_approval_hash,
        "prior_cumulative_cents": authority["prior_cumulative_cents"],
        "approved_cumulative_cents": authority["approved_cumulative_cents"],
        "bill_of_materials": authority["operations"],
        "authority": authority,
        "authority_hash": authority["authority_hash"],
    }
    if canonical_json(observed) != canonical_json(expected):
        raise _runtime_error("Custom Film stage authority replay changed")
    return {
        "id": str(existing["id"]),
        "authority_hash": authority["authority_hash"],
        "approval_hash": normalized_approval_hash,
        "created": False,
    }


async def persist_stage_schedule(
    conn: Any,
    *,
    tenant_id: str,
    plan_id: str,
    video_id: str,
    director_contract_id: str | None,
    authority_id: str,
    schedule: Mapping[str, Any],
) -> dict[str, Any]:
    """Consume one authority into one immutable schedule inside a transaction.

    The caller must provide a transaction-scoped connection. The authority row
    is locked before insert and may transition from unconsumed to exactly this
    schedule hash once. Replaying the same schedule converges on the stored row.
    """
    try:
        normalized_tenant_id = str(UUID(str(tenant_id)))
        normalized_plan_id = str(UUID(str(plan_id)))
        normalized_video_id = str(UUID(str(video_id)))
        normalized_authority_id = str(UUID(str(authority_id)))
        normalized_director_id = (
            str(UUID(str(director_contract_id)))
            if director_contract_id is not None
            else None
        )
    except (TypeError, ValueError, AttributeError) as exc:
        raise _runtime_error("Custom Film stage persistence identity is invalid") from exc
    validated = validate_stage_schedule(schedule)
    authority = await conn.fetchrow(
        """SELECT id, plan_id, video_id, director_contract_id, stage,
                  stage_binding_hash, upstream_gate_hash, quote_hash,
                  prior_cumulative_cents, approved_cumulative_cents,
                  authority_hash, consumed_at, consumed_by
           FROM custom_film_stage_authorities
           WHERE tenant_id = $1 AND id = $2
           FOR UPDATE""",
        normalized_tenant_id,
        normalized_authority_id,
    )
    if not authority:
        raise _runtime_error("Custom Film stage authority was not found")
    row_director_id = (
        str(authority["director_contract_id"])
        if authority.get("director_contract_id") is not None
        else None
    )
    expected = {
        "plan_id": normalized_plan_id,
        "video_id": normalized_video_id,
        "director_contract_id": normalized_director_id,
        "stage": validated["stage"],
        "stage_binding_hash": validated["stage_binding_hash"],
        "upstream_gate_hash": validated["upstream_gate_hash"],
        "quote_hash": validated["quote_hash"],
        "prior_cumulative_cents": validated["prior_cumulative_cents"],
        "approved_cumulative_cents": validated["approved_cumulative_cents"],
        "authority_hash": validated["authority_hash"],
    }
    observed = {
        "plan_id": str(authority["plan_id"]),
        "video_id": str(authority["video_id"]),
        "director_contract_id": row_director_id,
        "stage": str(authority["stage"]),
        "stage_binding_hash": str(authority["stage_binding_hash"]),
        "upstream_gate_hash": str(authority["upstream_gate_hash"]),
        "quote_hash": str(authority["quote_hash"]),
        "prior_cumulative_cents": int(authority["prior_cumulative_cents"]),
        "approved_cumulative_cents": int(authority["approved_cumulative_cents"]),
        "authority_hash": str(authority["authority_hash"]),
    }
    if observed != expected:
        raise _runtime_error("Custom Film stage authority changed before scheduling")

    if authority.get("consumed_at") is not None:
        if str(authority.get("consumed_by") or "") != validated["schedule_hash"]:
            raise _runtime_error(
                "Custom Film stage authority was already consumed by another schedule"
            )
        stored = await conn.fetchrow(
            """SELECT id, schedule_hash, task_count
               FROM custom_film_director_stage_schedules
               WHERE tenant_id = $1 AND authority_id = $2""",
            normalized_tenant_id,
            normalized_authority_id,
        )
        if (
            not stored
            or str(stored["schedule_hash"]) != validated["schedule_hash"]
            or int(stored["task_count"]) != validated["task_count"]
        ):
            raise _runtime_error("Custom Film stored stage schedule is inconsistent")
        return {
            "id": str(stored["id"]),
            "schedule_hash": validated["schedule_hash"],
            "task_count": validated["task_count"],
            "created": False,
        }

    stored = await conn.fetchrow(
        """INSERT INTO custom_film_director_stage_schedules
             (tenant_id, plan_id, video_id, director_contract_id, authority_id,
              stage, stage_binding_hash, upstream_gate_hash, authority_hash,
              schedule, schedule_hash, task_count)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11, $12)
           RETURNING id""",
        normalized_tenant_id,
        normalized_plan_id,
        normalized_video_id,
        normalized_director_id,
        normalized_authority_id,
        validated["stage"],
        validated["stage_binding_hash"],
        validated["upstream_gate_hash"],
        validated["authority_hash"],
        canonical_json(validated),
        validated["schedule_hash"],
        validated["task_count"],
    )
    if not stored:
        raise _runtime_error("Custom Film stage schedule was not stored")
    updated = await conn.execute(
        """UPDATE custom_film_stage_authorities
           SET consumed_at = now(), consumed_by = $3
           WHERE tenant_id = $1 AND id = $2 AND consumed_at IS NULL""",
        normalized_tenant_id,
        normalized_authority_id,
        validated["schedule_hash"],
    )
    if isinstance(updated, str) and not updated.endswith(" 1"):
        raise _runtime_error("Custom Film stage authority was not consumed")
    if not isinstance(updated, str) and not updated:
        raise _runtime_error("Custom Film stage authority was not consumed")
    return {
        "id": str(stored["id"]),
        "schedule_hash": validated["schedule_hash"],
        "task_count": validated["task_count"],
        "created": True,
    }


def compile_script_director_schedule(
    *,
    plan_id: str,
    plan_hash: str,
    raw_authority: Mapping[str, Any],
) -> dict[str, Any]:
    """Schedule the paid director pass before a director contract exists."""
    try:
        normalized_plan_id = str(UUID(str(plan_id)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _runtime_error("Custom Film prospective plan identity is invalid") from exc
    binding_hash = _validate_hash(plan_hash, "plan hash")
    authority = compile_stage_authority(
        raw_authority,
        expected_stage="script_director",
        expected_binding_hash=binding_hash,
        expected_upstream_gate_hash=binding_hash,
    )
    operations = _reconcile_authority_bom(
        authority,
        stage="script_director",
        required_counts={"director_plan": 1},
    )
    task = _stage_task(
        stage="script_director",
        binding_hash=binding_hash,
        operation=operations["director_plan"],
        subject_kind="plan",
        subject_id=normalized_plan_id,
        order_index=0,
        input_payload={
            "plan_id": normalized_plan_id,
            "plan_hash": binding_hash,
            "required_output": "film_bible_and_progressive_shot_contract",
        },
    )
    tasks = [task]
    tasks.extend(
        _helper_tasks(
            stage="script_director",
            binding_hash=binding_hash,
            operations=operations,
            start_order=len(tasks),
        )
    )
    return _finalize_schedule(
        stage="script_director",
        binding_hash=binding_hash,
        upstream_gate_hash=binding_hash,
        authority=authority,
        tasks=tasks,
    )


def _voice_lock(
    film_bible: Mapping[str, Any],
    speaker_id: str,
) -> str:
    if speaker_id == THIRD_PERSON_NARRATOR_ID:
        voice = film_bible.get("narrator_voice_lock")
        if film_bible.get("narrator_mode") != "third_person" or not voice:
            raise _runtime_error("Custom Film third-person narrator voice is not locked")
        return str(voice)
    characters = {
        str(character["character_id"]): character
        for character in film_bible["characters"]
    }
    character = characters.get(speaker_id)
    if character is None:
        raise _runtime_error("Custom Film spoken line has no locked speaker")
    return str(character["voice_lock"])


def compile_director_stage_schedule(
    director_contract: Mapping[str, Any],
    raw_authority: Mapping[str, Any],
    *,
    reference_gate: Mapping[str, Any] | None = None,
    storyboard_gate: Mapping[str, Any] | None = None,
    picture_gate: Mapping[str, Any] | None = None,
    visual_gate: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile one exact post-director stage without starting any work."""
    director = validate_director_contract(director_contract)
    stage = str(raw_authority.get("stage") or "")
    if stage == "script_director":
        raise _runtime_error(
            "Custom Film script direction must use its pre-contract scheduler"
        )
    required_counts = expected_stage_bom(director, stage)
    binding_hash = director["contract_hash"]

    gate_payload: dict[str, Any]
    if stage == "references":
        gate_payload = {}
        upstream_hash = binding_hash
    elif stage == "storyboards":
        gate_payload, upstream_hash = _verified_gate(
            reference_gate,
            hash_field="reference_gate_hash",
            director_contract_hash=binding_hash,
        )
    elif stage == "final_pictures":
        gate_payload, upstream_hash = _verified_gate(
            storyboard_gate,
            hash_field="storyboard_gate_hash",
            director_contract_hash=binding_hash,
        )
    elif stage == "animation_voice":
        gate_payload, upstream_hash = _verified_gate(
            picture_gate,
            hash_field="picture_gate_hash",
            director_contract_hash=binding_hash,
        )
    elif stage == "assembly":
        gate_payload, upstream_hash = _verified_gate(
            visual_gate,
            hash_field="visual_gate_hash",
            director_contract_hash=binding_hash,
        )
    else:
        raise _runtime_error("Custom Film director stage is unsupported")

    authority = compile_stage_authority(
        raw_authority,
        expected_stage=stage,
        expected_binding_hash=binding_hash,
        expected_upstream_gate_hash=upstream_hash,
    )
    operations = _reconcile_authority_bom(
        authority,
        stage=stage,
        required_counts=required_counts,
    )
    tasks: list[dict[str, Any]] = []

    if stage == "references":
        style = director["film_bible"]["style"]
        for lock_kind, operation_kind, rows, identity_field in (
            (
                "character",
                "character_reference",
                director["film_bible"]["characters"],
                "character_id",
            ),
            (
                "environment",
                "environment_reference",
                director["film_bible"]["environments"],
                "environment_id",
            ),
        ):
            for row in rows:
                lock_id = str(row[identity_field])
                tasks.append(
                    _stage_task(
                        stage=stage,
                        binding_hash=binding_hash,
                        operation=operations[operation_kind],
                        subject_kind=lock_kind,
                        subject_id=lock_id,
                        order_index=len(tasks),
                        input_payload={
                            "director_contract_hash": binding_hash,
                            "lock_kind": lock_kind,
                            "lock_id": lock_id,
                            "style_lock": style,
                            "identity_lock": row,
                        },
                    )
                )
    elif stage == "storyboards":
        references = _approval_map(
            gate_payload,
            list_field="approvals",
            identity_fields=("lock_kind", "lock_id"),
        )
        artifacts = [
            {
                "lock_kind": identity[0],
                "lock_id": identity[1],
                "reference_artifact_id": row["reference_artifact_id"],
            }
            for identity, row in sorted(references.items())
        ]
        for shot in director["shots"]:
            tasks.append(
                _stage_task(
                    stage=stage,
                    binding_hash=binding_hash,
                    operation=operations["storyboard_image"],
                    subject_kind="shot",
                    subject_id=str(shot["shot_id"]),
                    order_index=len(tasks),
                    input_payload={
                        "director_contract_hash": binding_hash,
                        "reference_gate_hash": upstream_hash,
                        "shot_id": shot["shot_id"],
                        "shot_key": shot["shot_key"],
                        "storyboard_prompt": shot["storyboard_prompt"],
                        "lock_reference_artifacts": artifacts,
                    },
                )
            )
    elif stage == "final_pictures":
        storyboards = _approval_map(
            gate_payload,
            list_field="approvals",
            identity_fields=("shot_id",),
        )
        for shot in director["shots"]:
            review = storyboards.get((str(shot["shot_id"]),))
            if review is None:
                raise _runtime_error("Custom Film approved storyboard set is incomplete")
            tasks.append(
                _stage_task(
                    stage=stage,
                    binding_hash=binding_hash,
                    operation=operations["final_picture"],
                    subject_kind="shot",
                    subject_id=str(shot["shot_id"]),
                    order_index=len(tasks),
                    input_payload={
                        "director_contract_hash": binding_hash,
                        "storyboard_gate_hash": upstream_hash,
                        "shot_id": shot["shot_id"],
                        "storyboard_artifact_id": review["storyboard_artifact_id"],
                        "final_picture_prompt": shot["final_picture_prompt"],
                    },
                )
            )
    elif stage == "animation_voice":
        pictures = _approval_map(
            gate_payload,
            list_field="approvals",
            identity_fields=("shot_id",),
        )
        for shot in director["shots"]:
            review = pictures.get((str(shot["shot_id"]),))
            if review is None:
                raise _runtime_error("Custom Film approved final-picture set is incomplete")
            tasks.append(
                _stage_task(
                    stage=stage,
                    binding_hash=binding_hash,
                    operation=operations["animation_clip"],
                    subject_kind="shot",
                    subject_id=str(shot["shot_id"]),
                    order_index=len(tasks),
                    input_payload={
                        "director_contract_hash": binding_hash,
                        "picture_gate_hash": upstream_hash,
                        "shot_id": shot["shot_id"],
                        "final_picture_artifact_id": review[
                            "final_picture_artifact_id"
                        ],
                        "duration_frames": shot["duration_frames"],
                        "motion_prompt": shot["motion_prompt"],
                        "performance_mode": shot["performance_mode"],
                        "ambient_sound": shot["ambient_sound"],
                        "score_intent": shot["score_intent"],
                        "sfx_cues": shot["sfx_cues"],
                    },
                )
            )
            for line_index, line in enumerate(shot["spoken_lines"]):
                tasks.append(
                    _stage_task(
                        stage=stage,
                        binding_hash=binding_hash,
                        operation=operations["voice_line"],
                        subject_kind="spoken_line",
                        subject_id=f"{shot['shot_id']}:{line_index + 1}",
                        order_index=len(tasks),
                        input_payload={
                            "director_contract_hash": binding_hash,
                            "picture_gate_hash": upstream_hash,
                            "shot_id": shot["shot_id"],
                            "line_index": line_index,
                            "speaker_id": line["speaker_id"],
                            "voice_lock": _voice_lock(
                                director["film_bible"],
                                str(line["speaker_id"]),
                            ),
                            "text": line["text"],
                            "language": line["language"],
                            "delivery": line["delivery"],
                            "addressee_id": line["addressee_id"],
                            "caption_mode": shot["caption_mode"],
                        },
                    )
                )
    else:
        admission = build_remotion_admission(
            director,
            storyboard_gate=storyboard_gate,
            picture_gate=picture_gate,
            visual_gate=visual_gate,
        )
        tasks.append(
            _stage_task(
                stage=stage,
                binding_hash=binding_hash,
                operation=operations["remotion_assembly"],
                subject_kind="film",
                subject_id=str(director["plan_id"]),
                order_index=0,
                input_payload={
                    "director_contract_hash": binding_hash,
                    "visual_gate_hash": upstream_hash,
                    "remotion_admission": admission,
                    "layer_requirements": [
                        "verified_motion_clips",
                        "dialogue_and_narration_audio",
                        "ambient_score_and_sfx",
                        "measured_captions",
                        "transitions",
                    ],
                },
            )
        )

    tasks.extend(
        _helper_tasks(
            stage=stage,
            binding_hash=binding_hash,
            operations=operations,
            start_order=len(tasks),
        )
    )
    return _finalize_schedule(
        stage=stage,
        binding_hash=binding_hash,
        upstream_gate_hash=upstream_hash,
        authority=authority,
        tasks=tasks,
    )
