"""Approval and durable scheduling boundary for the Custom Film director loop.

New director films begin with a deterministic intake scaffold and one exact
script/director stage approval. The approval is persisted into the immutable
v2 multipass schedule before a separate worker may be enqueued. This module
never resolves a provider, invokes a model, creates media, renders, uploads, or
records spend.
"""

from __future__ import annotations

import copy
import json
import os
from collections.abc import Mapping
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4, uuid5

from custom_film_contract import (
    CapabilityManifest,
    CustomFilmContractError,
    canonical_hash,
    canonical_json,
    normalize_plan,
    plan_hash,
    revision_input_from_normalized_plan,
)
from custom_film_director_multipass import (
    MULTIPASS_EXECUTION_MODEL,
    OPERATION_TOKEN_LIMITS,
    PRICE_BOOK_KEYS,
    build_multipass_stage_contract,
    normalize_multipass_price_book,
    validate_multipass_stage_contract,
)
from custom_film_director_runtime import (
    persist_stage_authority,
    persist_stage_schedule,
)
from database import get_pool

DIRECTOR_EXECUTION_MODEL = MULTIPASS_EXECUTION_MODEL
DIRECTOR_ACTIVATION_ENV = "CUSTOM_FILM_DIRECTOR_V2"
DIRECTOR_PRICE_BOOK_ENV = "CUSTOM_FILM_DIRECTOR_PRICE_BOOK_JSON"
DIRECTOR_STAGE = "script_director"
DIRECTOR_SHOT_SECONDS = 6


def _activation_error(message: str) -> CustomFilmContractError:
    return CustomFilmContractError(
        f"{message}; no director task was started and no provider was called"
    )


def director_activation_enabled() -> bool:
    """Return whether new Custom Films use the staged director intake."""
    return os.getenv(DIRECTOR_ACTIVATION_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def configured_director_price_book() -> dict[str, int]:
    """Load the complete deployment-owned six-operation price book."""
    raw = os.getenv(DIRECTOR_PRICE_BOOK_ENV, "").strip()
    if not raw:
        raise _activation_error(
            "Custom Film director pricing is not configured in "
            f"{DIRECTOR_PRICE_BOOK_ENV}"
        )
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _activation_error(
            "Custom Film director price book is not valid JSON"
        ) from exc
    try:
        price_book = normalize_multipass_price_book(value)
        from custom_film_director_provider import (
            PROVIDER_RATE_KEYS,
            configured_token_rates,
            maximum_operation_cents,
        )

        rates = configured_token_rates()
        for operation_kind, max_tokens in OPERATION_TOKEN_LIMITS.items():
            required = max(
                maximum_operation_cents(
                    max_tokens=max_tokens,
                    provider=provider,
                    rates=rates,
                )
                for provider in PROVIDER_RATE_KEYS
            )
            if price_book[operation_kind] < required:
                raise _activation_error(
                    f"Custom Film director {operation_kind} price is below its "
                    "hard provider ceiling"
                )
        return price_book
    except CustomFilmContractError as exc:
        raise _activation_error("Custom Film director price book is invalid") from exc


def _whole_dollars(cents: int) -> str:
    return f"${cents / 100:.2f}"


def _request_text(value: Any) -> str:
    request = str(value or "").strip()
    if not request:
        raise _activation_error("Custom Film needs a story request")
    return request


def _uuid(value: Any, label: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _activation_error(f"Custom Film {label} is invalid") from exc


def _hash(value: Any, label: str) -> str:
    digest = str(value or "")
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise _activation_error(f"Custom Film {label} is invalid")
    return digest


def _parse_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise _activation_error("Custom Film durable state is invalid") from exc
    return copy.deepcopy(value)


def _director_scaffold_plan(
    user_request: str,
    manifest: CapabilityManifest,
    *,
    prospective_plan_id: str,
    total_duration_seconds: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if (
        not isinstance(total_duration_seconds, int)
        or not 5 <= total_duration_seconds <= 86_400
    ):
        raise _activation_error("Custom Film duration is invalid")
    investigative = manifest.profiles.get("animated_investigative_documentary")
    if not isinstance(investigative, Mapping):
        raise _activation_error("Custom Film director scaffold profile is unavailable")
    section_id = str(
        uuid5(
            UUID(prospective_plan_id),
            f"full-film:{canonical_hash(user_request)}:{total_duration_seconds}",
        )
    )
    shot_count = max(1, round(total_duration_seconds / DIRECTOR_SHOT_SECONDS))
    raw_plan = {
        "compatibility_version": manifest.version,
        "sections": [
            {
                "section_id": section_id,
                "role": "full_film",
                "purpose": (
                    "Create one coherent screenplay whose shot techniques are "
                    "selected beat by beat under a single film bible."
                ),
                "duration_weight": 1,
                "knobs": copy.deepcopy(investigative["knobs"]),
                "estimated_media": {
                    "still_images": shot_count,
                    "animation_clips": shot_count,
                    "voice_tracks": 0,
                    "duration_seconds": str(total_duration_seconds),
                },
            }
        ],
    }
    normalized_plan = normalize_plan(raw_plan, manifest)
    planning_inputs = {
        "contract_kind": "director_planning_scaffold",
        "forecast_only": True,
        "requested_duration_seconds": total_duration_seconds,
        "target_shot_seconds": DIRECTOR_SHOT_SECONDS,
        "totals": {
            "duration_seconds": total_duration_seconds,
            "planned_shots": shot_count,
        },
        "sections": [
            {
                "section_id": section_id,
                "order_index": 0,
                "duration_seconds": total_duration_seconds,
                "still_images": shot_count,
            }
        ],
    }
    return normalized_plan, planning_inputs


def build_director_intake(
    user_request: str,
    manifest: CapabilityManifest,
    *,
    total_duration_seconds: int,
    prior_cumulative_cents: int = 0,
    price_book: Mapping[str, Any] | None = None,
    director_pass_max_cents: int | None = None,
    prospective_plan_id: str | None = None,
) -> dict[str, Any]:
    """Build the complete pre-approval director intake without inference."""
    request = _request_text(user_request)
    if type(prior_cumulative_cents) is not int or prior_cumulative_cents < 0:
        raise _activation_error("Custom Film cumulative approval amount is invalid")
    # Temporary source-compatibility for callers/tests created during the held
    # v1 activation. Production never uses this branch: chat loads the complete
    # deployment-owned six-key book.
    if price_book is None and type(director_pass_max_cents) is int:
        price_book = {
            operation_kind: director_pass_max_cents
            for operation_kind in PRICE_BOOK_KEYS
        }
    if price_book is None:
        raise _activation_error("Custom Film director price book is missing")
    plan_id = _uuid(prospective_plan_id or uuid4(), "prospective plan identity")
    normalized_plan, planning_inputs = _director_scaffold_plan(
        request,
        manifest,
        prospective_plan_id=plan_id,
        total_duration_seconds=total_duration_seconds,
    )
    digest = plan_hash(normalized_plan)
    stage_contract = build_multipass_stage_contract(
        plan_id=plan_id,
        plan_hash=digest,
        quote_inputs=planning_inputs,
        prior_cumulative_cents=prior_cumulative_cents,
        price_book=price_book,
    )
    activation = {
        "activation_version": 2,
        "execution_model": DIRECTOR_EXECUTION_MODEL,
        "user_request": request,
        "prospective_plan_id": plan_id,
        "internal_plan": normalized_plan,
        "plan_hash": digest,
        "quote_inputs": planning_inputs,
        "stage_contract": stage_contract,
        "stage_quote": stage_contract["stage_quote"],
        "stage_authority": stage_contract["stage_authority"],
        "authority_hash": stage_contract["authority_hash"],
        "approval_hash": stage_contract["approval_hash"],
        "schedule": stage_contract["schedule"],
    }
    activation["activation_hash"] = canonical_hash(activation)
    return activation


def validate_director_intake(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the exact intake again at approval and transaction time."""
    if not isinstance(raw, Mapping):
        raise _activation_error("Custom Film director intake is invalid")
    activation = copy.deepcopy(dict(raw))
    claimed_activation_hash = _hash(
        activation.pop("activation_hash", None),
        "director activation hash",
    )
    if canonical_hash(activation) != claimed_activation_hash:
        raise _activation_error("Custom Film director intake changed")
    if activation.get("execution_model") != DIRECTOR_EXECUTION_MODEL:
        raise _activation_error("Custom Film director execution model changed")
    plan_id = _uuid(
        activation.get("prospective_plan_id"),
        "prospective plan identity",
    )
    internal_plan = activation.get("internal_plan")
    if not isinstance(internal_plan, Mapping) or plan_hash(
        internal_plan
    ) != activation.get("plan_hash"):
        raise _activation_error("Custom Film director plan changed")
    digest = _hash(activation.get("plan_hash"), "plan hash")
    stage_contract = validate_multipass_stage_contract(activation.get("stage_contract"))
    stage_quote = stage_contract["stage_quote"]
    expected_stage_contract = build_multipass_stage_contract(
        plan_id=plan_id,
        plan_hash=digest,
        quote_inputs=activation.get("quote_inputs"),
        prior_cumulative_cents=stage_quote["prior_cumulative_cents"],
        price_book=stage_quote["price_book_cents"],
    )
    if (
        stage_contract["manifest"]["plan_id"] != plan_id
        or stage_contract["manifest"]["plan_hash"] != digest
        or canonical_json(stage_contract) != canonical_json(expected_stage_contract)
        or canonical_json(activation.get("stage_quote"))
        != canonical_json(stage_contract["stage_quote"])
        or canonical_json(activation.get("stage_authority"))
        != canonical_json(stage_contract["stage_authority"])
        or activation.get("authority_hash") != stage_contract["authority_hash"]
        or activation.get("approval_hash") != stage_contract["approval_hash"]
        or canonical_json(activation.get("schedule"))
        != canonical_json(stage_contract["schedule"])
    ):
        raise _activation_error("Custom Film director stage contract changed")
    activation["activation_hash"] = claimed_activation_hash
    return activation


def director_approval_card(activation: Mapping[str, Any]) -> dict[str, Any]:
    """Return the creator-safe exact first-stage approval card."""
    validated = validate_director_intake(activation)
    quote = validated["stage_quote"]
    planning = validated["quote_inputs"]
    return {
        "id": "custom_film_approval",
        "label": "Approve screenplay and storyboard direction",
        "type": "single",
        "header": "Custom Film · Stage 1 of 6",
        "custom_film_director_stage": {
            "stage": "Script and director plan",
            "duration_seconds": planning["requested_duration_seconds"],
            "planned_shots": planning["totals"]["planned_shots"],
            "produces": (
                "complete screenplay, film bible, locked cast and environments, "
                "and synchronous progressive shot plan"
            ),
            "media_generation_included": False,
            "initial_model_calls": quote["initial_model_calls"],
            "maximum_model_calls": quote["maximum_model_calls"],
            "conditional_repair_calls": quote["conditional_repair_calls"],
            "prior_cumulative": _whole_dollars(quote["prior_cumulative_cents"]),
            "stage_maximum": _whole_dollars(quote["stage_max_cents"]),
            "exact_cumulative_ceiling": _whole_dollars(
                quote["approved_cumulative_cents"]
            ),
        },
        "approval_notice": (
            "This approval covers only the screenplay/director pass: one film bible, "
            "one complete shot outline, contiguous shot batches, and at most one "
            "paired repair for each initial call. It does not approve character "
            "images, environment images, storyboards, final pictures, animation, "
            "voices, or any helper generation. Each later paid stage needs a new "
            "exact cumulative approval."
        ),
        "options": [
            {
                "value": "yes",
                "label": (
                    "Approve Stage 1 · cumulative ceiling "
                    f"{_whole_dollars(quote['approved_cumulative_cents'])}"
                ),
            },
            {"value": "no", "label": "Keep editing"},
        ],
    }


def director_intake_text(activation: Mapping[str, Any]) -> str:
    """Explain the no-media first stage in plain language."""
    validated = validate_director_intake(activation)
    quote = validated["stage_quote"]
    planning = validated["quote_inputs"]
    return (
        "I have enough information to begin with the actual film-planning layer.\n\n"
        f"Stage 1 plans the complete {planning['requested_duration_seconds']}-second "
        f"story across about {planning['totals']['planned_shots']} ordered shots. "
        "It must produce the screenplay, back-and-forth dialogue, purposeful "
        "third-person exposition, silent action, one style lock, locked recurring "
        "characters and environments, exact shot-to-shot state progression, and "
        "the synchronous storyboard plan.\n\n"
        f"It begins with {quote['initial_model_calls']} calls and allows at most "
        f"{quote['maximum_model_calls']} only when paired repairs are needed. "
        f"This stage adds at most {_whole_dollars(quote['stage_max_cents'])}. "
        "The exact cumulative ceiling after this stage is "
        f"{_whole_dollars(quote['approved_cumulative_cents'])}. No imagery, "
        "animation, voice, rendering, upload, or other provider work is included."
    )


async def reserve_director_stage_intent(
    tenant_id: str,
    conversation_id: str,
    expected_approval_hash: str,
    manifest: CapabilityManifest,
    *,
    confirmation_turn: Mapping[str, Any],
) -> dict[str, Any]:
    """Atomically persist an approved but not-started director schedule."""
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        conversation = await conn.fetchrow(
            """SELECT id, video_id, transcript, state
                   FROM chat_conversations
                   WHERE id = $1 AND tenant_id = $2
                   FOR UPDATE""",
            conversation_id,
            tenant_id,
        )
        if not conversation:
            raise _activation_error("Custom Film conversation was not found")
        state = _parse_json(conversation["state"])
        transcript = _parse_json(conversation.get("transcript") or [])
        if not isinstance(state, dict) or not isinstance(transcript, list):
            raise _activation_error("Custom Film conversation state is invalid")
        pending = state.get("pending_custom_film_plan")
        if not isinstance(pending, Mapping):
            raise _activation_error("Custom Film director intake was not found")

        if (
            pending.get("status") == "director_stage_scheduled"
            and pending.get("approval_hash") == expected_approval_hash
            and pending.get("video_id")
        ):
            return {
                "video_id": str(pending["video_id"]),
                "plan_id": str(pending["prospective_plan_id"]),
                "approval_hash": expected_approval_hash,
                "schedule_hash": str(pending["director_schedule_hash"]),
                "director_job_id": str(pending.get("director_job_id") or ""),
                "created": False,
                "pending_custom_film_plan": copy.deepcopy(dict(pending)),
            }
        if conversation.get("video_id"):
            raise _activation_error(
                "This conversation is already attached to another video"
            )
        if pending.get("status") != "awaiting_director_approval":
            raise _activation_error(
                "This Custom Film no longer has a current director approval"
            )

        raw_activation = pending.get("director_activation")
        activation = validate_director_intake(raw_activation)
        if (
            pending.get("execution_model") != DIRECTOR_EXECUTION_MODEL
            or pending.get("approval_hash") != expected_approval_hash
            or activation["approval_hash"] != expected_approval_hash
            or pending.get("prospective_plan_id") != activation["prospective_plan_id"]
        ):
            raise _activation_error("This Custom Film director approval changed")
        raw_plan = revision_input_from_normalized_plan(
            activation["internal_plan"],
            manifest,
        )
        persisted_plan = normalize_plan(raw_plan, manifest)
        if plan_hash(persisted_plan) != activation["plan_hash"]:
            raise _activation_error(
                "Custom Film director plan changed before persistence"
            )

        duration_seconds = int(activation["quote_inputs"]["requested_duration_seconds"])
        stage_max_cents = int(activation["stage_quote"]["stage_max_cents"])
        video = await conn.fetchrow(
            """INSERT INTO videos
                     (tenant_id, video_title, status, source,
                      video_length_minutes, max_spend, writer_guidance)
                   VALUES ($1, $2, 'custom_film_ready', 'custom_film',
                           $3, $4, $5)
                   RETURNING id""",
            tenant_id,
            activation["user_request"][:200],
            (Decimal(duration_seconds) / Decimal(60)).quantize(Decimal("0.000001")),
            # videos.max_spend protects spend on this newly reserved row.
            # The exact cross-run cumulative amount remains in the stage
            # authority; historical completed spend is not fresh headroom.
            Decimal(stage_max_cents) / Decimal(100),
            (
                "Storyboard director v2: approved multipass script/director schedule "
                "is held and has not started."
            ),
        )
        if not video:
            raise _activation_error("Custom Film director video was not reserved")
        video_id = str(video["id"])
        plan_id = activation["prospective_plan_id"]
        quote_inputs_hash = canonical_hash(activation["quote_inputs"])
        await conn.execute(
            """INSERT INTO custom_film_plans
                     (id, tenant_id, video_id, revision, compatibility_version,
                      plan, plan_hash, quote_inputs, quote_inputs_hash,
                      approval_hash, approved_at)
                   VALUES ($1, $2, $3, 1, $4, $5::jsonb, $6, $7::jsonb,
                           $8, NULL, NULL)""",
            plan_id,
            tenant_id,
            video_id,
            manifest.version,
            canonical_json(persisted_plan),
            activation["plan_hash"],
            canonical_json(activation["quote_inputs"]),
            quote_inputs_hash,
        )
        for section in persisted_plan["sections"]:
            await conn.execute(
                """INSERT INTO custom_film_sections
                         (tenant_id, plan_id, video_id, section_id, order_index,
                          role, purpose, duration_units, knobs, provenance,
                          estimated_media)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8,
                               $9::jsonb, $10::jsonb, $11::jsonb)""",
                tenant_id,
                plan_id,
                video_id,
                section["section_id"],
                section["order_index"],
                section["role"],
                section["purpose"],
                section["duration_units"],
                canonical_json(section["knobs"]),
                canonical_json(section["provenance"]),
                canonical_json(section["estimated_media"]),
            )
        authority = await persist_stage_authority(
            conn,
            tenant_id=tenant_id,
            plan_id=plan_id,
            video_id=video_id,
            director_contract_id=None,
            approval_hash=expected_approval_hash,
            raw_authority=activation["stage_authority"],
            expected_stage=DIRECTOR_STAGE,
            expected_binding_hash=activation["plan_hash"],
            expected_upstream_gate_hash=activation["plan_hash"],
        )
        schedule = await persist_stage_schedule(
            conn,
            tenant_id=tenant_id,
            plan_id=plan_id,
            video_id=video_id,
            director_contract_id=None,
            authority_id=authority["id"],
            schedule=activation["schedule"],
        )
        director_job_id = f"custom-film-director:{schedule['schedule_hash']}"
        await conn.execute(
            """INSERT INTO background_tasks
                 (tenant_id, video_id, task_type, status, message, job_id,
                  attempt, started_at)
               VALUES ($1, $2, 'custom_film_director', 'pending',
                       'Preparing approved screenplay and storyboard direction',
                       $3, 1, now())
               ON CONFLICT (job_id) WHERE job_id IS NOT NULL DO NOTHING""",
            tenant_id,
            video_id,
            director_job_id,
        )
        await conn.execute(
            """UPDATE videos
                   SET custom_film_plan_id = $3,
                       custom_film_plan_revision = 1,
                       custom_film_plan_hash = $4,
                       custom_film_quote_inputs_hash = $5,
                       custom_film_approval_hash = NULL,
                       custom_film_approved_at = NULL,
                       updated_at = now()
                   WHERE tenant_id = $1 AND id = $2""",
            tenant_id,
            video_id,
            plan_id,
            activation["plan_hash"],
            quote_inputs_hash,
        )
        durable_pending = copy.deepcopy(dict(pending))
        durable_pending["status"] = "director_stage_scheduled"
        durable_pending["video_id"] = video_id
        durable_pending["stage_authority_id"] = authority["id"]
        durable_pending["director_schedule_id"] = schedule["id"]
        durable_pending["director_schedule_hash"] = schedule["schedule_hash"]
        durable_pending["director_job_id"] = director_job_id
        durable_pending["provider_calls_started"] = False
        durable_pending["spend_recorded_cents"] = 0
        state["pending_custom_film_plan"] = durable_pending
        accepted_turn = copy.deepcopy(dict(confirmation_turn))
        transcript.append(accepted_turn)
        await conn.execute(
            """UPDATE chat_conversations
                   SET state = $3::jsonb, video_id = $4, transcript = $5::jsonb,
                       phase = 'created', updated_at = now()
                   WHERE id = $1 AND tenant_id = $2""",
            conversation_id,
            tenant_id,
            canonical_json(state),
            video_id,
            canonical_json(transcript),
        )
        return {
            "video_id": video_id,
            "plan_id": plan_id,
            "approval_hash": expected_approval_hash,
            "schedule_hash": schedule["schedule_hash"],
            "director_job_id": director_job_id,
            "created": True,
            "pending_custom_film_plan": durable_pending,
            "confirmation_turn": accepted_turn,
        }
