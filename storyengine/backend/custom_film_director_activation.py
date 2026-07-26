"""No-provider activation boundary for the Custom Film director loop.

New director films begin with a deterministic intake scaffold and one exact
script/director stage approval. The approval may be persisted into an immutable
schedule, but this module never resolves a provider, invokes a model, creates
media, enqueues work, renders, uploads, or records spend.
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
from custom_film_director import compile_stage_authority
from custom_film_director_runtime import (
    compile_script_director_schedule,
    persist_stage_authority,
    persist_stage_schedule,
)
from database import get_pool

DIRECTOR_EXECUTION_MODEL = "storyboard_director_v1"
DIRECTOR_ACTIVATION_ENV = "CUSTOM_FILM_DIRECTOR_V1"
DIRECTOR_PASS_MAX_CENTS_ENV = "CUSTOM_FILM_DIRECTOR_PASS_MAX_CENTS"
DIRECTOR_STAGE = "script_director"
DIRECTOR_STAGE_CALL_ALLOWANCE = 2
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


def configured_director_pass_max_cents() -> int:
    """Load the deployment-owned exact ceiling without inventing a price."""
    raw = os.getenv(DIRECTOR_PASS_MAX_CENTS_ENV, "").strip()
    if not raw:
        raise _activation_error(
            f"Custom Film director pricing is not configured in "
            f"{DIRECTOR_PASS_MAX_CENTS_ENV}"
        )
    try:
        cents = int(raw)
    except ValueError as exc:
        raise _activation_error(
            "Custom Film director pricing is not a whole-cent amount"
        ) from exc
    if cents < 1 or cents > 100_000_000:
        raise _activation_error("Custom Film director pricing is outside safe bounds")
    return cents


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
    director_pass_max_cents: int,
    prospective_plan_id: str | None = None,
) -> dict[str, Any]:
    """Build the complete pre-approval director intake without inference."""
    request = _request_text(user_request)
    if (
        type(prior_cumulative_cents) is not int
        or prior_cumulative_cents < 0
        or type(director_pass_max_cents) is not int
        or director_pass_max_cents < 1
    ):
        raise _activation_error("Custom Film cumulative approval amount is invalid")
    plan_id = _uuid(prospective_plan_id or uuid4(), "prospective plan identity")
    normalized_plan, planning_inputs = _director_scaffold_plan(
        request,
        manifest,
        prospective_plan_id=plan_id,
        total_duration_seconds=total_duration_seconds,
    )
    digest = plan_hash(normalized_plan)
    stage_quote = {
        "quote_version": 1,
        "stage": DIRECTOR_STAGE,
        "plan_id": plan_id,
        "plan_hash": digest,
        "output": (
            "complete screenplay, film bible, locked cast and environments, "
            "and synchronous progressive shot plan"
        ),
        "provider_scope": "tenant_owned_text_client",
        "maximum_model_calls": DIRECTOR_STAGE_CALL_ALLOWANCE,
        "media_generation_included": False,
        "prior_cumulative_cents": prior_cumulative_cents,
        "stage_max_cents": director_pass_max_cents,
        "approved_cumulative_cents": (prior_cumulative_cents + director_pass_max_cents),
    }
    quote_hash = canonical_hash(stage_quote)
    raw_authority = {
        "stage": DIRECTOR_STAGE,
        "stage_binding_hash": digest,
        "upstream_gate_hash": digest,
        "quote_hash": quote_hash,
        "prior_cumulative_cents": prior_cumulative_cents,
        "approved_cumulative_cents": (prior_cumulative_cents + director_pass_max_cents),
        "operations": [
            {
                "operation_kind": "director_plan",
                "count": 1,
                "unit_max_cents": director_pass_max_cents,
                "helper_operation": False,
            }
        ],
    }
    authority = compile_stage_authority(
        raw_authority,
        expected_stage=DIRECTOR_STAGE,
        expected_binding_hash=digest,
        expected_upstream_gate_hash=digest,
    )
    approval_hash = canonical_hash(
        {
            "action": "approve_custom_film_script_director_stage",
            "plan_id": plan_id,
            "authority_hash": authority["authority_hash"],
        }
    )
    schedule = compile_script_director_schedule(
        plan_id=plan_id,
        plan_hash=digest,
        raw_authority=raw_authority,
    )
    activation = {
        "activation_version": 1,
        "execution_model": DIRECTOR_EXECUTION_MODEL,
        "user_request": request,
        "prospective_plan_id": plan_id,
        "internal_plan": normalized_plan,
        "plan_hash": digest,
        "quote_inputs": planning_inputs,
        "stage_quote": stage_quote,
        "stage_authority": raw_authority,
        "authority_hash": authority["authority_hash"],
        "approval_hash": approval_hash,
        "schedule": schedule,
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
    raw_authority = activation.get("stage_authority")
    if not isinstance(raw_authority, Mapping):
        raise _activation_error("Custom Film director authority is missing")
    authority = compile_stage_authority(
        raw_authority,
        expected_stage=DIRECTOR_STAGE,
        expected_binding_hash=digest,
        expected_upstream_gate_hash=digest,
    )
    if authority["authority_hash"] != activation.get("authority_hash"):
        raise _activation_error("Custom Film director authority changed")
    stage_quote = activation.get("stage_quote")
    if (
        not isinstance(stage_quote, Mapping)
        or canonical_hash(stage_quote) != authority["quote_hash"]
        or stage_quote.get("plan_id") != plan_id
        or stage_quote.get("plan_hash") != digest
        or stage_quote.get("media_generation_included") is not False
    ):
        raise _activation_error("Custom Film director quote changed")
    expected_approval_hash = canonical_hash(
        {
            "action": "approve_custom_film_script_director_stage",
            "plan_id": plan_id,
            "authority_hash": authority["authority_hash"],
        }
    )
    if activation.get("approval_hash") != expected_approval_hash:
        raise _activation_error("Custom Film director approval changed")
    expected_schedule = compile_script_director_schedule(
        plan_id=plan_id,
        plan_hash=digest,
        raw_authority=raw_authority,
    )
    if canonical_json(activation.get("schedule")) != canonical_json(expected_schedule):
        raise _activation_error("Custom Film director schedule changed")
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
            "produces": quote["output"],
            "media_generation_included": False,
            "prior_cumulative": _whole_dollars(quote["prior_cumulative_cents"]),
            "stage_maximum": _whole_dollars(quote["stage_max_cents"]),
            "exact_cumulative_ceiling": _whole_dollars(
                quote["approved_cumulative_cents"]
            ),
        },
        "approval_notice": (
            "This approval covers only the screenplay/director pass, including "
            "one bounded repair. It does not approve character images, environment "
            "images, storyboards, final pictures, animation, voices, or any helper "
            "generation. Each later paid stage needs a new exact cumulative approval."
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
                "Storyboard director v1: approved script/director schedule "
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
            "created": True,
            "pending_custom_film_plan": durable_pending,
            "confirmation_turn": accepted_turn,
        }
