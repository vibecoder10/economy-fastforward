"""Deterministic Stage 1 contract for multi-pass Custom Film direction.

This module plans and prices text operations only. It cannot resolve
credentials, invoke a model, write a database row, enqueue work, or spend.
"""

from __future__ import annotations

import copy
from collections import Counter
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from custom_film_contract import (
    CustomFilmContractError,
    canonical_hash,
    canonical_json,
)
from custom_film_director import compile_stage_authority
from custom_film_director_runtime import validate_stage_schedule

MULTIPASS_EXECUTION_MODEL = "storyboard_director_multipass_v2"
MULTIPASS_MANIFEST_VERSION = 2
MULTIPASS_QUOTE_VERSION = 2
MULTIPASS_SCHEDULE_VERSION = 2
DIRECTOR_STAGE = "script_director"
DIRECTOR_OPERATION_PREFIX = "custom-film-director-op:"
MAX_PROVIDER_OUTPUT_TOKENS = 8_192
MAX_SHOTS_PER_BATCH = 8

INITIAL_OPERATION_KINDS = (
    "film_bible",
    "shot_outline",
    "shot_batch",
)
REPAIR_OPERATION_KINDS = (
    "film_bible_repair",
    "shot_outline_repair",
    "shot_batch_repair",
)
PRICE_BOOK_KEYS = INITIAL_OPERATION_KINDS + REPAIR_OPERATION_KINDS
OPERATION_TOKEN_LIMITS = {
    "film_bible": 6_000,
    "film_bible_repair": 6_000,
    "shot_outline": 7_000,
    "shot_outline_repair": 7_000,
    "shot_batch": 8_000,
    "shot_batch_repair": 8_000,
}


def _multipass_error(message: str) -> CustomFilmContractError:
    return CustomFilmContractError(
        f"{message}; no director operation was started and no provider was called"
    )


def _uuid(value: Any, label: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _multipass_error(f"Custom Film {label} is invalid") from exc


def _hash(value: Any, label: str) -> str:
    digest = str(value or "")
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise _multipass_error(f"Custom Film {label} is invalid")
    return digest


def _exact_positive_int(value: Any, label: str, *, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise _multipass_error(f"Custom Film {label} is invalid")
    return value


def _exact_nonnegative_int(value: Any, label: str, *, maximum: int) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise _multipass_error(f"Custom Film {label} is invalid")
    return value


def normalize_multipass_price_book(raw: Mapping[str, Any]) -> dict[str, int]:
    """Validate the complete deployment-owned per-operation price book."""
    if not isinstance(raw, Mapping) or set(raw) != set(PRICE_BOOK_KEYS):
        raise _multipass_error("Custom Film director price book is incomplete")
    return {
        key: _exact_positive_int(
            raw[key],
            f"{key} price",
            maximum=100_000_000,
        )
        for key in PRICE_BOOK_KEYS
    }


def _planning_contract(
    raw_quote_inputs: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(raw_quote_inputs, Mapping):
        raise _multipass_error("Custom Film director planning inputs are invalid")
    requested_seconds = _exact_positive_int(
        raw_quote_inputs.get("requested_duration_seconds"),
        "requested duration",
        maximum=86_400,
    )
    target_shot_seconds = _exact_positive_int(
        raw_quote_inputs.get("target_shot_seconds"),
        "target shot duration",
        maximum=3_600,
    )
    totals = raw_quote_inputs.get("totals")
    sections = raw_quote_inputs.get("sections")
    if not isinstance(totals, Mapping) or not isinstance(sections, list) or not sections:
        raise _multipass_error("Custom Film director planning inputs are incomplete")
    duration_seconds = _exact_positive_int(
        totals.get("duration_seconds"),
        "planned duration",
        maximum=86_400,
    )
    planned_shots = _exact_positive_int(
        totals.get("planned_shots"),
        "planned shot count",
        maximum=2_000,
    )
    if duration_seconds != requested_seconds:
        raise _multipass_error("Custom Film director duration changed")
    if max(1, round(requested_seconds / target_shot_seconds)) != planned_shots:
        raise _multipass_error("Custom Film director shot forecast changed")

    normalized_sections: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for expected_index, raw_section in enumerate(sections):
        if not isinstance(raw_section, Mapping):
            raise _multipass_error("Custom Film director section is invalid")
        section_id = _uuid(raw_section.get("section_id"), "section identity")
        if section_id in seen_ids or raw_section.get("order_index") != expected_index:
            raise _multipass_error("Custom Film director section order changed")
        seen_ids.add(section_id)
        section_shot_value = (
            raw_section.get("planned_shots")
            if "planned_shots" in raw_section
            else raw_section.get("still_images")
        )
        normalized_sections.append(
            {
                "section_id": section_id,
                "order_index": expected_index,
                "duration_seconds": _exact_positive_int(
                    raw_section.get("duration_seconds"),
                    "section duration",
                    maximum=86_400,
                ),
                "planned_shots": _exact_positive_int(
                    section_shot_value,
                    "section shot count",
                    maximum=2_000,
                ),
            }
        )
    if (
        sum(section["duration_seconds"] for section in normalized_sections)
        != duration_seconds
        or sum(section["planned_shots"] for section in normalized_sections)
        != planned_shots
    ):
        raise _multipass_error("Custom Film director sections do not reconcile")
    return {
        "requested_duration_seconds": requested_seconds,
        "target_shot_seconds": target_shot_seconds,
        "totals": {
            "duration_seconds": duration_seconds,
            "planned_shots": planned_shots,
        },
        "sections": normalized_sections,
    }


def _operation(
    *,
    plan_id: str,
    plan_hash: str,
    order_index: int,
    operation_kind: str,
    subject_id: str,
    result_slot_id: str,
    dependencies: list[str],
    planning_contract_hash: str,
    shot_start_index: int | None = None,
    shot_end_index: int | None = None,
    conditional: bool = False,
    repairs_operation_id: str | None = None,
) -> dict[str, Any]:
    max_tokens = OPERATION_TOKEN_LIMITS[operation_kind]
    payload = {
        "execution_model": MULTIPASS_EXECUTION_MODEL,
        "manifest_version": MULTIPASS_MANIFEST_VERSION,
        "plan_id": plan_id,
        "plan_hash": plan_hash,
        "planning_contract_hash": planning_contract_hash,
        "operation_kind": operation_kind,
        "result_slot_id": result_slot_id,
        "depends_on_result_slots": dependencies,
        "shot_start_index": shot_start_index,
        "shot_end_index": shot_end_index,
        "conditional": conditional,
        "repairs_operation_id": repairs_operation_id,
        "max_tokens": max_tokens,
    }
    input_hash = canonical_hash(payload)
    identity = {
        "stage": DIRECTOR_STAGE,
        "binding_hash": plan_hash,
        "operation_kind": operation_kind,
        "subject_kind": "director_plan_phase",
        "subject_id": subject_id,
        "order_index": order_index,
        "input_hash": input_hash,
    }
    operation_id = DIRECTOR_OPERATION_PREFIX + canonical_hash(identity)
    return {
        "operation_id": operation_id,
        **identity,
        "result_slot_id": result_slot_id,
        "depends_on_result_slots": dependencies,
        "shot_start_index": shot_start_index,
        "shot_end_index": shot_end_index,
        "conditional": conditional,
        "repairs_operation_id": repairs_operation_id,
        "max_tokens": max_tokens,
        "input_payload": payload,
    }


def _operation_pair(
    *,
    operations: list[dict[str, Any]],
    plan_id: str,
    plan_hash: str,
    initial_kind: str,
    repair_kind: str,
    subject_id: str,
    result_slot_id: str,
    dependencies: list[str],
    planning_contract_hash: str,
    shot_start_index: int | None = None,
    shot_end_index: int | None = None,
) -> None:
    initial = _operation(
        plan_id=plan_id,
        plan_hash=plan_hash,
        order_index=len(operations),
        operation_kind=initial_kind,
        subject_id=subject_id,
        result_slot_id=result_slot_id,
        dependencies=dependencies,
        planning_contract_hash=planning_contract_hash,
        shot_start_index=shot_start_index,
        shot_end_index=shot_end_index,
    )
    operations.append(initial)
    operations.append(
        _operation(
            plan_id=plan_id,
            plan_hash=plan_hash,
            order_index=len(operations),
            operation_kind=repair_kind,
            subject_id=f"{subject_id}:repair",
            result_slot_id=result_slot_id,
            dependencies=dependencies,
            planning_contract_hash=planning_contract_hash,
            shot_start_index=shot_start_index,
            shot_end_index=shot_end_index,
            conditional=True,
            repairs_operation_id=initial["operation_id"],
        )
    )


def build_multipass_manifest(
    *,
    plan_id: str,
    plan_hash: str,
    quote_inputs: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the immutable maximum-call graph for one director pass."""
    normalized_plan_id = _uuid(plan_id, "prospective plan identity")
    normalized_plan_hash = _hash(plan_hash, "plan hash")
    planning = _planning_contract(quote_inputs)
    planning_hash = canonical_hash(planning)
    total_shots = planning["totals"]["planned_shots"]
    operations: list[dict[str, Any]] = []

    _operation_pair(
        operations=operations,
        plan_id=normalized_plan_id,
        plan_hash=normalized_plan_hash,
        initial_kind="film_bible",
        repair_kind="film_bible_repair",
        subject_id="film_bible",
        result_slot_id="film_bible",
        dependencies=[],
        planning_contract_hash=planning_hash,
    )
    _operation_pair(
        operations=operations,
        plan_id=normalized_plan_id,
        plan_hash=normalized_plan_hash,
        initial_kind="shot_outline",
        repair_kind="shot_outline_repair",
        subject_id="shot_outline",
        result_slot_id="shot_outline",
        dependencies=["film_bible"],
        planning_contract_hash=planning_hash,
        shot_start_index=0,
        shot_end_index=total_shots - 1,
    )

    previous_batch_slot: str | None = None
    for start_index in range(0, total_shots, MAX_SHOTS_PER_BATCH):
        end_index = min(start_index + MAX_SHOTS_PER_BATCH, total_shots) - 1
        result_slot = f"shot_batch:{start_index:04d}-{end_index:04d}"
        dependencies = ["film_bible", "shot_outline"]
        if previous_batch_slot is not None:
            dependencies.append(previous_batch_slot)
        _operation_pair(
            operations=operations,
            plan_id=normalized_plan_id,
            plan_hash=normalized_plan_hash,
            initial_kind="shot_batch",
            repair_kind="shot_batch_repair",
            subject_id=result_slot,
            result_slot_id=result_slot,
            dependencies=dependencies,
            planning_contract_hash=planning_hash,
            shot_start_index=start_index,
            shot_end_index=end_index,
        )
        previous_batch_slot = result_slot

    manifest = {
        "manifest_version": MULTIPASS_MANIFEST_VERSION,
        "execution_model": MULTIPASS_EXECUTION_MODEL,
        "stage": DIRECTOR_STAGE,
        "plan_id": normalized_plan_id,
        "plan_hash": normalized_plan_hash,
        "planning_contract": planning,
        "planning_contract_hash": planning_hash,
        "max_shots_per_batch": MAX_SHOTS_PER_BATCH,
        "maximum_model_calls": len(operations),
        "initial_model_calls": sum(
            operation["conditional"] is False for operation in operations
        ),
        "conditional_repair_calls": sum(
            operation["conditional"] is True for operation in operations
        ),
        "operations": operations,
    }
    manifest["manifest_hash"] = canonical_hash(manifest)
    return manifest


def validate_multipass_manifest(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Rebuild a manifest and refuse any changed call, range, or dependency."""
    if not isinstance(raw, Mapping):
        raise _multipass_error("Custom Film director manifest is invalid")
    manifest = copy.deepcopy(dict(raw))
    claimed_hash = _hash(
        manifest.pop("manifest_hash", None),
        "director manifest hash",
    )
    if canonical_hash(manifest) != claimed_hash:
        raise _multipass_error("Custom Film director manifest changed")
    if (
        manifest.get("manifest_version") != MULTIPASS_MANIFEST_VERSION
        or manifest.get("execution_model") != MULTIPASS_EXECUTION_MODEL
        or manifest.get("stage") != DIRECTOR_STAGE
    ):
        raise _multipass_error("Custom Film director execution model changed")
    expected = build_multipass_manifest(
        plan_id=manifest.get("plan_id"),
        plan_hash=manifest.get("plan_hash"),
        quote_inputs=manifest.get("planning_contract"),
    )
    observed = {**manifest, "manifest_hash": claimed_hash}
    if canonical_json(observed) != canonical_json(expected):
        raise _multipass_error("Custom Film director manifest no longer reconciles")
    return observed


def _build_stage_contract(
    *,
    manifest: Mapping[str, Any],
    prior_cumulative_cents: int,
    price_book: Mapping[str, Any],
) -> dict[str, Any]:
    validated_manifest = validate_multipass_manifest(manifest)
    prior_cents = _exact_nonnegative_int(
        prior_cumulative_cents,
        "prior cumulative amount",
        maximum=100_000_000_000,
    )
    prices = normalize_multipass_price_book(price_book)
    counts = Counter(
        operation["operation_kind"]
        for operation in validated_manifest["operations"]
    )
    line_items = [
        {
            "operation_kind": operation_kind,
            "count": counts[operation_kind],
            "unit_max_cents": prices[operation_kind],
            "subtotal_max_cents": (
                counts[operation_kind] * prices[operation_kind]
            ),
            "conditional_repair": operation_kind in REPAIR_OPERATION_KINDS,
        }
        for operation_kind in PRICE_BOOK_KEYS
    ]
    stage_max_cents = sum(row["subtotal_max_cents"] for row in line_items)
    quote = {
        "quote_version": MULTIPASS_QUOTE_VERSION,
        "execution_model": MULTIPASS_EXECUTION_MODEL,
        "stage": DIRECTOR_STAGE,
        "plan_id": validated_manifest["plan_id"],
        "plan_hash": validated_manifest["plan_hash"],
        "manifest_hash": validated_manifest["manifest_hash"],
        "maximum_model_calls": validated_manifest["maximum_model_calls"],
        "initial_model_calls": validated_manifest["initial_model_calls"],
        "conditional_repair_calls": validated_manifest[
            "conditional_repair_calls"
        ],
        "price_book_cents": prices,
        "line_items": line_items,
        "media_generation_included": False,
        "prior_cumulative_cents": prior_cents,
        "stage_max_cents": stage_max_cents,
        "approved_cumulative_cents": prior_cents + stage_max_cents,
    }
    quote_hash = canonical_hash(quote)
    raw_authority = {
        "stage": DIRECTOR_STAGE,
        "stage_binding_hash": validated_manifest["plan_hash"],
        "upstream_gate_hash": validated_manifest["plan_hash"],
        "quote_hash": quote_hash,
        "prior_cumulative_cents": prior_cents,
        "approved_cumulative_cents": prior_cents + stage_max_cents,
        "operations": [
            {
                "operation_kind": row["operation_kind"],
                "count": row["count"],
                "unit_max_cents": row["unit_max_cents"],
                "helper_operation": False,
            }
            for row in line_items
        ],
    }
    authority = compile_stage_authority(
        raw_authority,
        expected_stage=DIRECTOR_STAGE,
        expected_binding_hash=validated_manifest["plan_hash"],
        expected_upstream_gate_hash=validated_manifest["plan_hash"],
    )
    if authority["stage_max_cents"] != stage_max_cents:
        raise _multipass_error("Custom Film director quote no longer reconciles")

    tasks: list[dict[str, Any]] = []
    for operation in validated_manifest["operations"]:
        task = copy.deepcopy(operation)
        task["unit_max_cents"] = prices[operation["operation_kind"]]
        task["helper_operation"] = False
        task["status"] = "authorized_not_started"
        tasks.append(task)
    schedule = {
        "schedule_version": MULTIPASS_SCHEDULE_VERSION,
        "execution_model": MULTIPASS_EXECUTION_MODEL,
        "manifest_hash": validated_manifest["manifest_hash"],
        "stage": DIRECTOR_STAGE,
        "stage_binding_hash": validated_manifest["plan_hash"],
        "upstream_gate_hash": validated_manifest["plan_hash"],
        "authority_hash": authority["authority_hash"],
        "quote_hash": quote_hash,
        "prior_cumulative_cents": prior_cents,
        "approved_cumulative_cents": prior_cents + stage_max_cents,
        "stage_max_cents": stage_max_cents,
        "task_count": len(tasks),
        "tasks": tasks,
        "provider_calls_started": False,
        "spend_recorded_cents": 0,
    }
    schedule["schedule_hash"] = canonical_hash(schedule)
    validate_stage_schedule(schedule)

    approval_hash = canonical_hash(
        {
            "action": "approve_custom_film_multipass_director_stage",
            "execution_model": MULTIPASS_EXECUTION_MODEL,
            "plan_id": validated_manifest["plan_id"],
            "manifest_hash": validated_manifest["manifest_hash"],
            "authority_hash": authority["authority_hash"],
        }
    )
    contract = {
        "activation_version": 2,
        "execution_model": MULTIPASS_EXECUTION_MODEL,
        "manifest": validated_manifest,
        "stage_quote": quote,
        "quote_hash": quote_hash,
        "stage_authority": raw_authority,
        "authority_hash": authority["authority_hash"],
        "approval_hash": approval_hash,
        "schedule": schedule,
    }
    contract["activation_hash"] = canonical_hash(contract)
    return contract


def build_multipass_stage_contract(
    *,
    plan_id: str,
    plan_hash: str,
    quote_inputs: Mapping[str, Any],
    prior_cumulative_cents: int,
    price_book: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the exact Stage 1 quote, authority, and zero-call schedule."""
    manifest = build_multipass_manifest(
        plan_id=plan_id,
        plan_hash=plan_hash,
        quote_inputs=quote_inputs,
    )
    return _build_stage_contract(
        manifest=manifest,
        prior_cumulative_cents=prior_cumulative_cents,
        price_book=price_book,
    )


def validate_multipass_stage_contract(
    raw: Mapping[str, Any],
) -> dict[str, Any]:
    """Recompute the complete v2 contract and reject v1 or drifted approval."""
    if not isinstance(raw, Mapping):
        raise _multipass_error("Custom Film director activation is invalid")
    contract = copy.deepcopy(dict(raw))
    claimed_hash = _hash(
        contract.pop("activation_hash", None),
        "director activation hash",
    )
    if canonical_hash(contract) != claimed_hash:
        raise _multipass_error("Custom Film director activation changed")
    if (
        contract.get("activation_version") != 2
        or contract.get("execution_model") != MULTIPASS_EXECUTION_MODEL
    ):
        raise _multipass_error("Custom Film director activation version changed")
    manifest = validate_multipass_manifest(contract.get("manifest"))
    quote = contract.get("stage_quote")
    if not isinstance(quote, Mapping):
        raise _multipass_error("Custom Film director quote is invalid")
    expected = _build_stage_contract(
        manifest=manifest,
        prior_cumulative_cents=quote.get("prior_cumulative_cents"),
        price_book=quote.get("price_book_cents"),
    )
    observed = {**contract, "activation_hash": claimed_hash}
    if canonical_json(observed) != canonical_json(expected):
        raise _multipass_error("Custom Film director activation no longer reconciles")
    return observed
