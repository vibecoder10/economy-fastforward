"""Deterministic, tenant-bound Scene Control for Custom Film.

This module owns film-foundation locks, scene revision heads, explicit gate
transitions, downstream invalidation, later-scene locking, and read-only exact
operation quote cards. It intentionally has no provider adapter, approval
execution, queue, outbox, generation-claim, or ledger-write seam.
"""

from __future__ import annotations

import copy
import json
import os
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from custom_film_contract import canonical_hash, canonical_json
from custom_film_director import compile_director_contract, persist_director_contract


SCENE_CONTROL_NAMESPACE = UUID("93c8b4d9-0de4-4b32-9f04-6a67b6574d28")
SYNTHETIC_FIXTURE_NAMESPACE = UUID("50bd1f6d-89b6-442c-ad1b-fd7dc1810c74")
SCENE_CONTROL_VERSION = 1
SYNTHETIC_VIDEO_TITLE = "[SYNTHETIC] Scene Control Proof"
SYNTHETIC_VIDEO_STATUS = "custom_film_directed"
SYNTHETIC_VIDEO_SOURCE = "custom_film_scene_control_synthetic"
SYNTHETIC_VIDEO_GUIDANCE = (
    "Synthetic deterministic Scene Control proof; no provider work."
)
SYNTHETIC_SHOT_MEDIA_URLS = (
    "/scene-control-proof/shot-1-establish-key.mp4",
    "/scene-control-proof/shot-2-signal-exchange.mp4",
    "/scene-control-proof/shot-3-silent-alarm.mp4",
    "/scene-control-proof/shot-4-breaker-exchange.mp4",
    "/scene-control-proof/shot-5-breaker-payoff.mp4",
)
SYNTHETIC_ASSEMBLY_MEDIA_URL = (
    "/scene-control-proof/director-scene-control-proof.mp4"
)

LOCK_KINDS = (
    "story",
    "dialogue",
    "style",
    "cast",
    "environments",
    "techniques",
)
SCENE_STATES = (
    "draft",
    "plan_approved",
    "storyboard_approved",
    "imagery_approved",
    "animation_approved",
    "audio_approved",
    "assembled",
    "accepted",
)
NEXT_STATE = dict(zip(SCENE_STATES, SCENE_STATES[1:]))
REWIND_STATE = {
    "plan": "draft",
    "storyboard": "plan_approved",
    "imagery": "storyboard_approved",
    "animation": "imagery_approved",
    "audio": "animation_approved",
    "assembly": "audio_approved",
}
TRANSITION_ARTIFACT_GATE = {
    "storyboard_approved": "storyboard",
    "imagery_approved": "imagery",
    "animation_approved": "animation",
    "audio_approved": "audio",
    "assembled": "assembly",
    "accepted": "assembly",
}
OPERATION_RULES = {
    "storyboard_images": {
        "required_state": "plan_approved",
        "provider_operation": "storyboard_image",
        "scope": "scene",
        "unit_env": "CUSTOM_FILM_SCENE_STORYBOARD_IMAGE_MAX_CENTS",
        # Canonical GPT Image 2 storyboard ceiling: $0.05 per image.
        "default_unit_cents": 5,
        "included": ["storyboard imagery"],
    },
    "final_imagery": {
        "required_state": "storyboard_approved",
        "provider_operation": "final_picture",
        "scope": "scene",
        "unit_env": "CUSTOM_FILM_SCENE_FINAL_IMAGE_MAX_CENTS",
        "default_unit_cents": None,
        "included": ["final imagery"],
    },
    "animate_shot": {
        "required_state": "imagery_approved",
        "provider_operation": "animation_clip",
        "scope": "shot",
        "unit_env": "CUSTOM_FILM_SCENE_ANIMATION_MAX_CENTS",
        "default_unit_cents": None,
        "included": ["animation"],
    },
    "dialogue_audio": {
        "required_state": "animation_approved",
        "provider_operation": "voice_line",
        "scope": "scene",
        "unit_env": "CUSTOM_FILM_SCENE_VOICE_LINE_MAX_CENTS",
        "default_unit_cents": None,
        "included": ["dialogue audio"],
    },
    "assemble_scene": {
        "required_state": "audio_approved",
        "provider_operation": "remotion_assembly",
        "scope": "scene",
        "unit_env": None,
        "default_unit_cents": 0,
        "included": ["deterministic Remotion assembly"],
    },
}
ALL_MEDIA = {
    "storyboard imagery",
    "final imagery",
    "animation",
    "dialogue audio",
    "deterministic Remotion assembly",
}


class SceneControlError(ValueError):
    """Fail-closed domain error suitable for a creator-facing 409."""


class SceneControlNotFound(SceneControlError):
    """Tenant-owned Custom Film or scene was not found."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DialogueTurn(_StrictModel):
    speaker_id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=600)
    performance_intent: str = Field(min_length=2, max_length=300)
    timing: str = Field(min_length=1, max_length=120)


class SceneContract(_StrictModel):
    scene_number: int = Field(ge=1, le=10_000)
    purpose: str = Field(min_length=10, max_length=1_000)
    target_duration_frames: int = Field(ge=1, le=216_000)
    story_time: str = Field(min_length=2, max_length=300)
    opening_state: str = Field(min_length=5, max_length=2_000)
    state_change: str = Field(min_length=5, max_length=2_000)
    character_ids: tuple[str, ...] = Field(min_length=1, max_length=40)
    environment_id: str = Field(min_length=1, max_length=100)
    active_prop_ids: tuple[str, ...] = Field(default=(), max_length=40)
    continuity_in: str = Field(min_length=2, max_length=2_000)
    continuity_out: str = Field(min_length=2, max_length=2_000)
    dialogue_turns: tuple[DialogueTurn, ...] = Field(default=(), max_length=100)
    silent_action_beats: tuple[str, ...] = Field(default=(), max_length=40)
    shot_ids: tuple[UUID, ...] = Field(min_length=1, max_length=200)

    @field_validator(
        "character_ids",
        "active_prop_ids",
        "silent_action_beats",
        "shot_ids",
    )
    @classmethod
    def unique_values(cls, value: tuple[Any, ...]) -> tuple[Any, ...]:
        if len(value) != len(set(value)):
            raise ValueError("Scene Control lists cannot contain duplicates")
        return value

    @model_validator(mode="after")
    def contains_progression(self) -> "SceneContract":
        if self.opening_state == self.state_change:
            raise ValueError("A scene must change state")
        return self


class SceneArtifactShot(_StrictModel):
    shot_id: UUID
    kind: Literal["video"]
    url: str
    start_frame: int = Field(ge=0)
    end_frame: int = Field(ge=0)
    sha256: str

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        if value not in SYNTHETIC_SHOT_MEDIA_URLS:
            raise ValueError("shot artifact URL is not allowlisted")
        return value

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        return _digest(value, "shot artifact hash")

    @model_validator(mode="after")
    def validate_frames(self) -> "SceneArtifactShot":
        if self.end_frame < self.start_frame:
            raise ValueError("shot artifact frame range is invalid")
        return self


class SceneArtifactAssembly(_StrictModel):
    kind: Literal["video"]
    url: str
    duration_frames: int = Field(ge=1)
    sha256: str

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        if value != SYNTHETIC_ASSEMBLY_MEDIA_URL:
            raise ValueError("assembly artifact URL is not allowlisted")
        return value

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        return _digest(value, "assembly artifact hash")


class SceneArtifactManifest(_StrictModel):
    version: Literal[1]
    synthetic: Literal[True]
    shots: tuple[SceneArtifactShot, ...] = Field(min_length=1, max_length=200)
    assembly: SceneArtifactAssembly


def scene_control_enabled() -> bool:
    return os.getenv("CUSTOM_FILM_SCENE_CONTROL_V1", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _json_value(value: Any, label: str) -> Any:
    if not isinstance(value, str):
        return copy.deepcopy(value)
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise SceneControlError(f"Stored {label} is invalid") from exc


def _uuid(value: Any, label: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise SceneControlError(f"{label} is invalid") from exc


def _digest(value: Any, label: str) -> str:
    digest = str(value or "")
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise SceneControlError(f"{label} is invalid")
    return digest


def compile_scene_contract(raw: Mapping[str, Any]) -> dict[str, Any]:
    try:
        parsed = SceneContract.model_validate(raw)
    except (ValueError, TypeError) as exc:
        raise SceneControlError(f"Scene contract is invalid: {exc}") from exc
    return parsed.model_dump(mode="json")


def compile_lock_set(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    latest: dict[str, dict[str, Any]] = {}
    for raw in rows:
        row = dict(raw)
        kind = str(row.get("lock_kind") or "")
        if kind not in LOCK_KINDS:
            raise SceneControlError("Film lock kind is invalid")
        normalized = {
            "lock_kind": kind,
            "revision": int(row["revision"]),
            "content_hash": _digest(row["content_hash"], "film lock hash"),
            "approval_hash": _digest(row["approval_hash"], "film lock approval hash"),
        }
        if "payload" in row:
            normalized["payload"] = _json_value(row["payload"], "film lock payload")
        if "synthetic" in row:
            normalized["synthetic"] = bool(row["synthetic"])
        if "approved_at" in row:
            normalized["approved_at"] = row["approved_at"]
        current = latest.get(kind)
        if current is None or normalized["revision"] > current["revision"]:
            latest[kind] = normalized
    missing = set(LOCK_KINDS) - set(latest)
    ordered = [latest[kind] for kind in LOCK_KINDS if kind in latest]
    hash_locks = [
        {
            key: row[key]
            for key in ("lock_kind", "revision", "content_hash", "approval_hash")
        }
        for row in ordered
    ]
    hash_payload = {
        "lock_version": SCENE_CONTROL_VERSION,
        "complete": not missing,
        "missing": sorted(missing),
        "locks": hash_locks,
    }
    payload = {**hash_payload, "locks": ordered}
    payload["film_lock_set_hash"] = canonical_hash(hash_payload)
    return payload


def compile_artifact_manifest(
    raw_manifest: Mapping[str, Any] | None,
    *,
    scene_contract: Mapping[str, Any],
) -> dict[str, Any]:
    if not raw_manifest:
        return {}
    contract = compile_scene_contract(scene_contract)
    try:
        manifest = SceneArtifactManifest.model_validate(raw_manifest)
    except (ValueError, TypeError) as exc:
        raise SceneControlError(f"Scene artifact manifest is invalid: {exc}") from exc
    payload = manifest.model_dump(mode="json")
    if [row["shot_id"] for row in payload["shots"]] != contract["shot_ids"]:
        raise SceneControlError(
            "Scene artifact manifest shots do not match the scene contract"
        )
    if payload["assembly"]["duration_frames"] != contract[
        "target_duration_frames"
    ]:
        raise SceneControlError(
            "Scene artifact assembly duration does not match the scene contract"
        )
    return payload


def compile_scene_revision(
    scene_contract: Mapping[str, Any],
    *,
    film_lock_set_hash: str,
    revision: int,
    artifact_hashes: Mapping[str, str] | None = None,
    artifact_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if type(revision) is not int or revision < 1:
        raise SceneControlError("Scene revision is invalid")
    contract = compile_scene_contract(scene_contract)
    artifacts = dict(artifact_hashes or {})
    unknown = set(artifacts) - set(REWIND_STATE)
    if unknown:
        raise SceneControlError("Scene artifact gate is invalid")
    for gate, digest in artifacts.items():
        artifacts[gate] = _digest(digest, f"{gate} artifact hash")
    payload = {
        "revision_version": SCENE_CONTROL_VERSION,
        "revision": revision,
        "film_lock_set_hash": _digest(film_lock_set_hash, "film lock set hash"),
        "scene_contract": contract,
        "artifact_hashes": {key: artifacts[key] for key in sorted(artifacts)},
        "artifact_manifest": compile_artifact_manifest(
            artifact_manifest,
            scene_contract=contract,
        ),
    }
    payload["revision_hash"] = canonical_hash(payload)
    return payload


def validate_transition(current_state: str, target_state: str) -> None:
    if current_state not in SCENE_STATES or target_state not in SCENE_STATES:
        raise SceneControlError("Scene state is invalid")
    if NEXT_STATE.get(current_state) != target_state:
        raise SceneControlError(
            f"Scene cannot move directly from {current_state} to {target_state}"
        )


def required_transition_evidence(
    scene: Mapping[str, Any],
    target_state: str,
) -> str:
    """Return the only evidence hash permitted for the requested gate."""
    if target_state == "plan_approved":
        return _digest(str(scene.get("revision_hash") or ""), "scene revision hash")
    artifact_gate = TRANSITION_ARTIFACT_GATE.get(target_state)
    if artifact_gate is None:
        raise SceneControlError("Scene transition evidence target is invalid")
    artifacts = scene.get("artifact_hashes")
    if not isinstance(artifacts, Mapping):
        raise SceneControlError("Scene artifact hashes are invalid")
    artifact_hash = artifacts.get(artifact_gate)
    if not artifact_hash:
        raise SceneControlError(
            f"{artifact_gate} artifact hash is required before {target_state}"
        )
    return _digest(str(artifact_hash), f"{artifact_gate} artifact hash")


def invalidated_states(current_state: str, changed_gate: str) -> list[str]:
    rewind = REWIND_STATE.get(changed_gate)
    if rewind is None:
        raise SceneControlError("Scene revision gate is invalid")
    if current_state not in SCENE_STATES:
        raise SceneControlError("Scene state is invalid")
    if current_state == "accepted":
        raise SceneControlError("An accepted scene is immutable")
    current_index = SCENE_STATES.index(current_state)
    rewind_index = SCENE_STATES.index(rewind)
    if current_index <= rewind_index:
        return []
    return list(SCENE_STATES[rewind_index + 1 : current_index + 1])


def derive_scene_access(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[list[str], str | None]:
    """Derive accepted/current/locked rail access from ordered scene states."""
    access: list[str] = []
    earlier_accepted = True
    current_scene_id: str | None = None
    for row in rows:
        state = str(row.get("state") or "")
        if state not in SCENE_STATES:
            raise SceneControlError("Scene state is invalid")
        value = (
            "accepted"
            if state == "accepted"
            else ("current" if earlier_accepted else "locked")
        )
        access.append(value)
        if value == "current" and current_scene_id is None:
            current_scene_id = str(row.get("id") or row.get("scene_id") or "")
        earlier_accepted = earlier_accepted and state == "accepted"
    return access, current_scene_id


def conservative_usd_to_cents(actual_cost: Any) -> int:
    """Convert ledger USD to cents without ever understating prior spend."""
    try:
        value = Decimal(str(0 if actual_cost is None else actual_cost))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise SceneControlError("Completed generation spend is invalid") from exc
    if not value.is_finite() or value < 0:
        raise SceneControlError("Completed generation spend must be nonnegative")
    return int(
        (value * Decimal(100)).to_integral_value(rounding=ROUND_CEILING)
    )


def _price_cents(rule: Mapping[str, Any]) -> int:
    env_name = rule.get("unit_env")
    raw = os.getenv(str(env_name)) if env_name else None
    if raw is None or not raw.strip():
        default = rule.get("default_unit_cents")
        if default is None:
            raise SceneControlError(
                f"{env_name} is required before this paid operation can be quoted"
            )
        return int(default)
    try:
        value = int(raw)
    except ValueError as exc:
        raise SceneControlError(f"{env_name} must be exact integer cents") from exc
    if value < 0:
        raise SceneControlError(f"{env_name} cannot be negative")
    return value


def compile_operation_quote(
    *,
    video_id: str,
    scene_id: str,
    scene_number: int,
    scene_revision_hash: str,
    operation_type: str,
    shot_ids: Sequence[str],
    dialogue_line_count: int,
    prior_completed_cumulative_cents: int,
    requested_shot_id: str | None = None,
) -> dict[str, Any]:
    rule = OPERATION_RULES.get(operation_type)
    if rule is None:
        raise SceneControlError("Scene operation type is unsupported")
    exact_shots = [_uuid(value, "shot identity") for value in shot_ids]
    requested = _uuid(requested_shot_id, "shot identity") if requested_shot_id else None
    if rule["scope"] == "shot":
        if requested is None or requested not in exact_shots:
            raise SceneControlError("This operation needs one shot in the current scene")
        scoped_shots = [requested]
        initial_calls = 1
    elif requested is not None:
        raise SceneControlError("This scene operation cannot carry a shot override")
    else:
        scoped_shots = exact_shots
        if operation_type in {"storyboard_images", "final_imagery"}:
            initial_calls = len(exact_shots)
        elif operation_type == "dialogue_audio":
            initial_calls = dialogue_line_count
        else:
            initial_calls = 1
    if initial_calls < 1:
        raise SceneControlError("This scene operation has no work to quote")
    if (
        type(prior_completed_cumulative_cents) is not int
        or prior_completed_cumulative_cents < 0
    ):
        raise SceneControlError("Prior completed cumulative spend is invalid")
    unit_max_cents = _price_cents(rule)
    incremental = initial_calls * unit_max_cents
    included = list(rule["included"])
    card = {
        "quote_version": SCENE_CONTROL_VERSION,
        "video_id": _uuid(video_id, "video identity"),
        "scene_id": _uuid(scene_id, "scene identity"),
        "scene_number": scene_number,
        "shot_ids": scoped_shots,
        "scene_revision_hash": _digest(
            scene_revision_hash,
            "scene revision hash",
        ),
        "operation_type": operation_type,
        "provider_operation": rule["provider_operation"],
        "deterministic": operation_type == "assemble_scene",
        "initial_calls": initial_calls,
        "max_repair_calls": 0,
        "unit_max_cents": unit_max_cents,
        "exact_incremental_max_cents": incremental,
        "prior_completed_cumulative_spend_cents": prior_completed_cumulative_cents,
        "new_exact_cumulative_ceiling_cents": (
            prior_completed_cumulative_cents + incremental
        ),
        "included_media": included,
        "explicitly_unapproved": sorted(ALL_MEDIA - set(included)),
        "approval_status": "not_approved",
    }
    card["approval_card_hash"] = canonical_hash(card)
    return card


async def _load_director(
    conn: Any,
    tenant_id: str,
    video_id: str,
) -> dict[str, Any]:
    row = await conn.fetchrow(
        """SELECT id, plan_id, video_id, director_contract, contract_hash
           FROM custom_film_director_contracts
           WHERE tenant_id = $1 AND video_id = $2
           ORDER BY revision DESC
           LIMIT 1""",
        tenant_id,
        video_id,
    )
    if not row:
        raise SceneControlNotFound("Custom Film director was not found")
    return {
        "id": str(row["id"]),
        "plan_id": str(row["plan_id"]),
        "video_id": str(row["video_id"]),
        "contract": _json_value(row["director_contract"], "director contract"),
        "contract_hash": str(row["contract_hash"]),
    }


async def _lock_rows(
    conn: Any,
    tenant_id: str,
    director_contract_id: str,
) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """SELECT DISTINCT ON (lock_kind)
                  lock_kind, revision, payload, content_hash, approval_hash,
                  synthetic, approved_at
           FROM custom_film_film_locks
           WHERE tenant_id = $1 AND director_contract_id = $2
           ORDER BY lock_kind, revision DESC""",
        tenant_id,
        director_contract_id,
    )
    return [dict(row) for row in rows]


async def _scene_row(
    conn: Any,
    tenant_id: str,
    video_id: str,
    scene_id: str,
    *,
    lock: bool,
) -> dict[str, Any]:
    suffix = " FOR UPDATE" if lock else ""
    row = await conn.fetchrow(
        """SELECT id, tenant_id, plan_id, video_id, director_contract_id,
                  scene_number, scene_contract, revision, revision_hash,
                  film_lock_set_hash, artifact_hashes, artifact_manifest, state,
                  accepted_revision_hash, synthetic, created_at, updated_at
           FROM custom_film_scene_controls
           WHERE tenant_id = $1 AND video_id = $2 AND id = $3"""
        + suffix,
        tenant_id,
        video_id,
        scene_id,
    )
    if not row:
        raise SceneControlNotFound("Scene Control scene was not found")
    result = dict(row)
    result["id"] = str(result["id"])
    result["plan_id"] = str(result["plan_id"])
    result["video_id"] = str(result["video_id"])
    result["director_contract_id"] = str(result["director_contract_id"])
    result["scene_contract"] = _json_value(result["scene_contract"], "scene contract")
    result["artifact_hashes"] = _json_value(
        result.get("artifact_hashes") or {},
        "scene artifact hashes",
    )
    result["artifact_manifest"] = compile_artifact_manifest(
        _json_value(
            result.get("artifact_manifest") or {},
            "scene artifact manifest",
        ),
        scene_contract=result["scene_contract"],
    )
    return result


async def _assert_scene_accessible(
    conn: Any,
    tenant_id: str,
    video_id: str,
    scene_number: int,
) -> None:
    blocking = await conn.fetchval(
        """SELECT COUNT(*)
           FROM custom_film_scene_controls
           WHERE tenant_id = $1 AND video_id = $2
             AND scene_number < $3 AND state <> 'accepted'""",
        tenant_id,
        video_id,
        scene_number,
    )
    if int(blocking or 0) > 0:
        raise SceneControlError("A later scene remains locked until earlier scenes are accepted")


async def _validate_scene_shots(
    conn: Any,
    *,
    tenant_id: str,
    director_contract_id: str,
    scene_contract: Mapping[str, Any],
    excluding_scene_id: str | None = None,
) -> list[dict[str, Any]]:
    contract = compile_scene_contract(scene_contract)
    shot_ids = [str(value) for value in contract["shot_ids"]]
    rows = await conn.fetch(
        """SELECT shot_id, order_index, duration_frames, shot_contract
           FROM custom_film_shots
           WHERE tenant_id = $1 AND director_contract_id = $2
             AND shot_id = ANY($3::uuid[])
           ORDER BY order_index""",
        tenant_id,
        director_contract_id,
        shot_ids,
    )
    observed = [str(row["shot_id"]) for row in rows]
    if observed != shot_ids:
        raise SceneControlError(
            "Scene shots must be an exact synchronous slice of the director contract"
        )
    if sum(int(row["duration_frames"]) for row in rows) != int(
        contract["target_duration_frames"]
    ):
        raise SceneControlError("Scene shot durations do not match its target duration")
    overlap = await conn.fetchval(
        """SELECT COUNT(*)
           FROM custom_film_scene_controls
           WHERE tenant_id = $1 AND director_contract_id = $2
             AND ($4::uuid IS NULL OR id <> $4)
             AND EXISTS (
               SELECT 1
               FROM jsonb_array_elements_text(scene_contract->'shot_ids') existing
               WHERE existing.value = ANY($3::text[])
             )""",
        tenant_id,
        director_contract_id,
        shot_ids,
        excluding_scene_id,
    )
    if int(overlap or 0) > 0:
        raise SceneControlError("A director shot can belong to only one scene")
    return [
        {
            **dict(row),
            "shot_id": str(row["shot_id"]),
            "shot_contract": _json_value(row["shot_contract"], "shot contract"),
        }
        for row in rows
    ]


def _event_payload(
    *,
    scene_id: str,
    revision_hash: str,
    event_kind: str,
    from_state: str,
    to_state: str,
    evidence_hash: str,
    invalidated: Sequence[str] = (),
) -> dict[str, Any]:
    event = {
        "event_version": SCENE_CONTROL_VERSION,
        "scene_id": scene_id,
        "revision_hash": revision_hash,
        "event_kind": event_kind,
        "from_state": from_state,
        "to_state": to_state,
        "evidence_hash": evidence_hash,
        "invalidated_states": list(invalidated),
    }
    event["event_hash"] = canonical_hash(event)
    return event


async def _insert_event(
    conn: Any,
    *,
    tenant_id: str,
    scene: Mapping[str, Any],
    event: Mapping[str, Any],
) -> None:
    await conn.execute(
        """INSERT INTO custom_film_scene_events
             (tenant_id, plan_id, video_id, director_contract_id, scene_id,
              revision_hash, event_kind, from_state, to_state, evidence_hash,
              invalidated_states, event, event_hash)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                   $11::jsonb, $12::jsonb, $13)
           ON CONFLICT (tenant_id, event_hash) DO NOTHING""",
        tenant_id,
        scene["plan_id"],
        scene["video_id"],
        scene["director_contract_id"],
        scene["id"],
        event["revision_hash"],
        event["event_kind"],
        event["from_state"],
        event["to_state"],
        event["evidence_hash"],
        canonical_json(event["invalidated_states"]),
        canonical_json(event),
        event["event_hash"],
    )


async def approve_film_lock(
    conn: Any,
    *,
    tenant_id: str,
    video_id: str,
    lock_kind: str,
    payload: Any,
    synthetic: bool = False,
) -> dict[str, Any]:
    if lock_kind not in LOCK_KINDS:
        raise SceneControlError("Film lock kind is unsupported")
    director = await _load_director(conn, tenant_id, video_id)
    if payload is None or payload == {} or payload == [] or payload == "":
        raise SceneControlError("Film lock payload cannot be empty")
    await conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
        f"custom-film-scene-control:{tenant_id}:{video_id}",
    )
    accepted = await conn.fetchval(
        """SELECT COUNT(*) FROM custom_film_scene_controls
           WHERE tenant_id = $1 AND video_id = $2 AND state = 'accepted'""",
        tenant_id,
        video_id,
    )
    content_hash = canonical_hash(payload)
    existing = await conn.fetchrow(
        """SELECT id, revision, content_hash, approval_hash
           FROM custom_film_film_locks
           WHERE tenant_id = $1 AND director_contract_id = $2
             AND lock_kind = $3
           ORDER BY revision DESC
           LIMIT 1
           FOR UPDATE""",
        tenant_id,
        director["id"],
        lock_kind,
    )
    if existing and str(existing["content_hash"]) == content_hash:
        return {
            "id": str(existing["id"]),
            "lock_kind": lock_kind,
            "revision": int(existing["revision"]),
            "content_hash": content_hash,
            "approval_hash": str(existing["approval_hash"]),
            "created": False,
        }
    if int(accepted or 0) > 0:
        raise SceneControlError("Film locks cannot change after a scene is accepted")
    revision = int(existing["revision"]) + 1 if existing else 1
    approval_payload = {
        "lock_version": SCENE_CONTROL_VERSION,
        "director_contract_hash": director["contract_hash"],
        "lock_kind": lock_kind,
        "revision": revision,
        "content_hash": content_hash,
    }
    approval_hash = canonical_hash(approval_payload)
    lock_id = str(uuid4())
    await conn.execute(
        """INSERT INTO custom_film_film_locks
             (id, tenant_id, plan_id, video_id, director_contract_id,
              lock_kind, revision, payload, content_hash, approval_hash,
              synthetic)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $10, $11)""",
        lock_id,
        tenant_id,
        director["plan_id"],
        video_id,
        director["id"],
        lock_kind,
        revision,
        canonical_json(payload),
        content_hash,
        approval_hash,
        synthetic,
    )
    lock_set = compile_lock_set(await _lock_rows(conn, tenant_id, director["id"]))
    scenes = await conn.fetch(
        """SELECT id FROM custom_film_scene_controls
           WHERE tenant_id = $1 AND video_id = $2
           ORDER BY scene_number
           FOR UPDATE""",
        tenant_id,
        video_id,
    )
    for scene_ref in scenes:
        scene = await _scene_row(
            conn,
            tenant_id,
            video_id,
            str(scene_ref["id"]),
            lock=False,
        )
        invalidated = invalidated_states(str(scene["state"]), "plan")
        revision_payload = compile_scene_revision(
            scene["scene_contract"],
            film_lock_set_hash=lock_set["film_lock_set_hash"],
            revision=int(scene["revision"]) + 1,
        )
        event = _event_payload(
            scene_id=scene["id"],
            revision_hash=revision_payload["revision_hash"],
            event_kind="film_lock_invalidated",
            from_state=str(scene["state"]),
            to_state="draft",
            evidence_hash=approval_hash,
            invalidated=invalidated,
        )
        await _insert_event(conn, tenant_id=tenant_id, scene=scene, event=event)
        await conn.execute(
            """UPDATE custom_film_scene_controls
               SET revision = $4, revision_hash = $5,
                   film_lock_set_hash = $6, artifact_hashes = '{}'::jsonb,
                   artifact_manifest = '{}'::jsonb,
                   state = 'draft', updated_at = now()
               WHERE tenant_id = $1 AND video_id = $2 AND id = $3
                 AND state <> 'accepted'""",
            tenant_id,
            video_id,
            scene["id"],
            revision_payload["revision"],
            revision_payload["revision_hash"],
            revision_payload["film_lock_set_hash"],
        )
    return {
        "id": lock_id,
        "lock_kind": lock_kind,
        "revision": revision,
        "content_hash": content_hash,
        "approval_hash": approval_hash,
        "film_lock_set_hash": lock_set["film_lock_set_hash"],
        "film_locks_complete": lock_set["complete"],
        "created": True,
    }


async def create_scene(
    conn: Any,
    *,
    tenant_id: str,
    video_id: str,
    raw_scene_contract: Mapping[str, Any],
    artifact_manifest: Mapping[str, Any] | None = None,
    synthetic: bool = False,
) -> dict[str, Any]:
    director = await _load_director(conn, tenant_id, video_id)
    contract = compile_scene_contract(raw_scene_contract)
    compiled_artifact_manifest = compile_artifact_manifest(
        artifact_manifest,
        scene_contract=contract,
    )
    await conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
        f"custom-film-scene-control:{tenant_id}:{video_id}",
    )
    existing = await conn.fetchrow(
        """SELECT id, scene_contract, revision, revision_hash,
                  film_lock_set_hash, artifact_manifest, state, synthetic
           FROM custom_film_scene_controls
           WHERE tenant_id = $1 AND director_contract_id = $2
             AND scene_number = $3""",
        tenant_id,
        director["id"],
        contract["scene_number"],
    )
    if existing:
        if canonical_json(
            _json_value(existing["scene_contract"], "scene contract")
        ) != canonical_json(contract):
            raise SceneControlError("Scene number already has a different contract")
        stored_artifact_manifest = compile_artifact_manifest(
            _json_value(
                existing.get("artifact_manifest") or {},
                "scene artifact manifest",
            ),
            scene_contract=contract,
        )
        if canonical_json(stored_artifact_manifest) != canonical_json(
            compiled_artifact_manifest
        ):
            raise SceneControlError(
                "Scene number already has a different artifact manifest"
            )
        return {
            "scene_id": str(existing["id"]),
            "scene_number": contract["scene_number"],
            "state": str(existing["state"]),
            "revision": int(existing["revision"]),
            "revision_hash": str(existing["revision_hash"]),
            "film_lock_set_hash": str(existing["film_lock_set_hash"]),
            "created": False,
            "synthetic": bool(existing.get("synthetic")),
        }
    current_max = await conn.fetchval(
        """SELECT MAX(scene_number)
           FROM custom_film_scene_controls
           WHERE tenant_id = $1 AND director_contract_id = $2""",
        tenant_id,
        director["id"],
    )
    next_scene_number = int(current_max or 0) + 1
    if int(contract["scene_number"]) != next_scene_number:
        raise SceneControlError(
            f"Next scene number must be exactly {next_scene_number}"
        )
    await _validate_scene_shots(
        conn,
        tenant_id=tenant_id,
        director_contract_id=director["id"],
        scene_contract=contract,
    )
    lock_set = compile_lock_set(await _lock_rows(conn, tenant_id, director["id"]))
    revision = compile_scene_revision(
        contract,
        film_lock_set_hash=lock_set["film_lock_set_hash"],
        revision=1,
        artifact_manifest=compiled_artifact_manifest,
    )
    scene_id = str(
        uuid5(
            SCENE_CONTROL_NAMESPACE,
            f"{tenant_id}:{director['id']}:{contract['scene_number']}",
        )
    )
    stored = await conn.fetchrow(
        """INSERT INTO custom_film_scene_controls
             (id, tenant_id, plan_id, video_id, director_contract_id,
              scene_number, scene_contract, revision, revision_hash,
              film_lock_set_hash, artifact_hashes, artifact_manifest,
              state, synthetic)
           VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, 1, $8, $9,
                   '{}'::jsonb, $10::jsonb, 'draft', $11)
           ON CONFLICT (tenant_id, director_contract_id, scene_number)
           DO NOTHING
           RETURNING id""",
        scene_id,
        tenant_id,
        director["plan_id"],
        video_id,
        director["id"],
        contract["scene_number"],
        canonical_json(contract),
        revision["revision_hash"],
        revision["film_lock_set_hash"],
        canonical_json(compiled_artifact_manifest),
        synthetic,
    )
    if not stored:
        conflicting = await conn.fetchrow(
            """SELECT id, scene_contract, revision_hash
               FROM custom_film_scene_controls
               WHERE tenant_id = $1 AND director_contract_id = $2
                 AND scene_number = $3""",
            tenant_id,
            director["id"],
            contract["scene_number"],
        )
        if (
            not conflicting
            or canonical_json(
                _json_value(conflicting["scene_contract"], "scene contract")
            )
            != canonical_json(contract)
            or str(conflicting["revision_hash"]) != revision["revision_hash"]
        ):
            raise SceneControlError("Scene number already has a different contract")
        scene_id = str(conflicting["id"])
    event = _event_payload(
        scene_id=scene_id,
        revision_hash=revision["revision_hash"],
        event_kind="scene_created",
        from_state="draft",
        to_state="draft",
        evidence_hash=canonical_hash(contract),
    )
    scene = {
        "id": scene_id,
        "plan_id": director["plan_id"],
        "video_id": video_id,
        "director_contract_id": director["id"],
    }
    await _insert_event(conn, tenant_id=tenant_id, scene=scene, event=event)
    return {
        "scene_id": scene_id,
        "scene_number": contract["scene_number"],
        "state": "draft",
        "revision": 1,
        "revision_hash": revision["revision_hash"],
        "film_lock_set_hash": revision["film_lock_set_hash"],
        "created": bool(stored),
        "synthetic": synthetic,
    }


async def revise_scene(
    conn: Any,
    *,
    tenant_id: str,
    video_id: str,
    scene_id: str,
    expected_revision_hash: str,
    changed_gate: str,
    raw_scene_contract: Mapping[str, Any] | None = None,
    artifact_hash: str | None = None,
) -> dict[str, Any]:
    scene = await _scene_row(conn, tenant_id, video_id, scene_id, lock=True)
    await _assert_scene_accessible(
        conn,
        tenant_id,
        video_id,
        int(scene["scene_number"]),
    )
    if scene["revision_hash"] != _digest(expected_revision_hash, "expected revision hash"):
        raise SceneControlError("Scene revision changed; reload before editing")
    invalidated = invalidated_states(str(scene["state"]), changed_gate)
    contract = (
        compile_scene_contract(raw_scene_contract)
        if raw_scene_contract is not None
        else scene["scene_contract"]
    )
    if int(contract["scene_number"]) != int(scene["scene_number"]):
        raise SceneControlError("Scene number is immutable")
    await _validate_scene_shots(
        conn,
        tenant_id=tenant_id,
        director_contract_id=scene["director_contract_id"],
        scene_contract=contract,
        excluding_scene_id=scene["id"],
    )
    artifacts = dict(scene["artifact_hashes"])
    changed_index = list(REWIND_STATE).index(changed_gate)
    for later_gate in list(REWIND_STATE)[changed_index:]:
        artifacts.pop(later_gate, None)
    if artifact_hash is not None:
        artifacts[changed_gate] = _digest(artifact_hash, f"{changed_gate} artifact hash")
    artifact_manifest = (
        scene["artifact_manifest"]
        if canonical_json(contract) == canonical_json(scene["scene_contract"])
        else {}
    )
    revision = compile_scene_revision(
        contract,
        film_lock_set_hash=scene["film_lock_set_hash"],
        revision=int(scene["revision"]) + 1,
        artifact_hashes=artifacts,
        artifact_manifest=artifact_manifest,
    )
    new_state = REWIND_STATE[changed_gate]
    event = _event_payload(
        scene_id=scene["id"],
        revision_hash=revision["revision_hash"],
        event_kind="scene_revised",
        from_state=str(scene["state"]),
        to_state=new_state,
        evidence_hash=artifact_hash or canonical_hash(contract),
        invalidated=invalidated,
    )
    await _insert_event(conn, tenant_id=tenant_id, scene=scene, event=event)
    updated = await conn.execute(
        """UPDATE custom_film_scene_controls
           SET scene_contract = $5::jsonb, revision = $6, revision_hash = $7,
               artifact_hashes = $8::jsonb, artifact_manifest = $9::jsonb,
               state = $10, updated_at = now()
           WHERE tenant_id = $1 AND video_id = $2 AND id = $3
             AND revision_hash = $4 AND state <> 'accepted'""",
        tenant_id,
        video_id,
        scene["id"],
        expected_revision_hash,
        canonical_json(contract),
        revision["revision"],
        revision["revision_hash"],
        canonical_json(revision["artifact_hashes"]),
        canonical_json(revision["artifact_manifest"]),
        new_state,
    )
    if isinstance(updated, str) and not updated.endswith(" 1"):
        raise SceneControlError("Scene revision compare-and-set failed")
    return {
        "scene_id": scene["id"],
        "state": new_state,
        "revision": revision["revision"],
        "revision_hash": revision["revision_hash"],
        "invalidated_states": invalidated,
    }


async def transition_scene(
    conn: Any,
    *,
    tenant_id: str,
    video_id: str,
    scene_id: str,
    expected_revision_hash: str,
    target_state: str,
    evidence_hash: str,
) -> dict[str, Any]:
    scene = await _scene_row(conn, tenant_id, video_id, scene_id, lock=True)
    await _assert_scene_accessible(
        conn,
        tenant_id,
        video_id,
        int(scene["scene_number"]),
    )
    expected = _digest(expected_revision_hash, "expected revision hash")
    evidence = _digest(evidence_hash, "gate evidence hash")
    if scene["revision_hash"] != expected:
        raise SceneControlError("Scene revision changed; reload before approving")
    validate_transition(str(scene["state"]), target_state)
    required_evidence = required_transition_evidence(scene, target_state)
    if evidence != required_evidence:
        raise SceneControlError(
            f"Gate evidence does not match the required hash for {target_state}"
        )
    event = _event_payload(
        scene_id=scene["id"],
        revision_hash=expected,
        event_kind=("scene_accepted" if target_state == "accepted" else "gate_approved"),
        from_state=str(scene["state"]),
        to_state=target_state,
        evidence_hash=evidence,
    )
    await _insert_event(conn, tenant_id=tenant_id, scene=scene, event=event)
    updated = await conn.execute(
        """UPDATE custom_film_scene_controls
           SET state = $5,
               accepted_revision_hash = CASE WHEN $5 = 'accepted' THEN $4 ELSE NULL END,
               updated_at = now()
           WHERE tenant_id = $1 AND video_id = $2 AND id = $3
             AND revision_hash = $4 AND state = $6""",
        tenant_id,
        video_id,
        scene["id"],
        expected,
        target_state,
        scene["state"],
    )
    if isinstance(updated, str) and not updated.endswith(" 1"):
        raise SceneControlError("Scene transition compare-and-set failed")
    return {
        "scene_id": scene["id"],
        "scene_number": int(scene["scene_number"]),
        "state": target_state,
        "revision_hash": expected,
        "event_hash": event["event_hash"],
        "next_scene_unlocked": target_state == "accepted",
    }


async def _read_scene_shot_models(
    conn: Any,
    *,
    tenant_id: str,
    director_contract_id: str,
    scene_rows: Sequence[Mapping[str, Any]],
) -> list[list[dict[str, Any]]]:
    contracts = [
        compile_scene_contract(
            _json_value(row["scene_contract"], "scene contract")
        )
        for row in scene_rows
    ]
    requested_ids = [
        str(shot_id)
        for contract in contracts
        for shot_id in contract["shot_ids"]
    ]
    if not requested_ids:
        return [[] for _ in contracts]
    rows = await conn.fetch(
        """SELECT shot_id, order_index, duration_frames, shot_contract
           FROM custom_film_shots
           WHERE tenant_id = $1 AND director_contract_id = $2
             AND shot_id = ANY($3::uuid[])
           ORDER BY order_index""",
        tenant_id,
        director_contract_id,
        requested_ids,
    )
    by_id: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        shot_id = str(row["shot_id"])
        if shot_id in by_id:
            raise SceneControlError("Scene shot read model contains duplicate shots")
        by_id[shot_id] = row
    if set(by_id) != set(requested_ids) or len(requested_ids) != len(set(requested_ids)):
        raise SceneControlError("Scene shot read model does not match scene contracts")

    scene_models: list[list[dict[str, Any]]] = []
    for contract in contracts:
        ordered_rows = [by_id[str(shot_id)] for shot_id in contract["shot_ids"]]
        order_indexes = [int(row["order_index"]) for row in ordered_rows]
        if order_indexes != sorted(order_indexes) or len(order_indexes) != len(
            set(order_indexes)
        ):
            raise SceneControlError(
                "Scene shot read model is not in synchronous director order"
            )
        if sum(int(row["duration_frames"]) for row in ordered_rows) != int(
            contract["target_duration_frames"]
        ):
            raise SceneControlError(
                "Scene shot read model duration does not match scene contract"
            )
        scene_models.append(
            [
                {
                    "shot_id": str(row["shot_id"]),
                    "order_index": int(row["order_index"]),
                    "duration_frames": int(row["duration_frames"]),
                    "shot_contract": _json_value(
                        row["shot_contract"],
                        "shot contract",
                    ),
                }
                for row in ordered_rows
            ]
        )
    return scene_models


async def read_scene_control(
    conn: Any,
    *,
    tenant_id: str,
    video_id: str,
) -> dict[str, Any]:
    director = await _load_director(conn, tenant_id, video_id)
    lock_set = compile_lock_set(await _lock_rows(conn, tenant_id, director["id"]))
    rows = await conn.fetch(
        """SELECT id, scene_number, scene_contract, revision, revision_hash,
                  film_lock_set_hash, artifact_hashes, artifact_manifest, state,
                  accepted_revision_hash, synthetic
           FROM custom_film_scene_controls
           WHERE tenant_id = $1 AND video_id = $2
             AND director_contract_id = $3
           ORDER BY scene_number""",
        tenant_id,
        video_id,
        director["id"],
    )
    scene_shot_models = await _read_scene_shot_models(
        conn,
        tenant_id=tenant_id,
        director_contract_id=director["id"],
        scene_rows=rows,
    )
    scenes: list[dict[str, Any]] = []
    access_values, current_scene_id = derive_scene_access(rows)
    for row, access, shots in zip(rows, access_values, scene_shot_models):
        state = str(row["state"])
        scene_id = str(row["id"])
        scenes.append(
            {
                "scene_id": scene_id,
                "scene_number": int(row["scene_number"]),
                "scene_contract": _json_value(row["scene_contract"], "scene contract"),
                "revision": int(row["revision"]),
                "revision_hash": str(row["revision_hash"]),
                "film_lock_set_hash": str(row["film_lock_set_hash"]),
                "artifact_hashes": _json_value(
                    row.get("artifact_hashes") or {},
                    "scene artifact hashes",
                ),
                "artifact_manifest": compile_artifact_manifest(
                    _json_value(
                        row.get("artifact_manifest") or {},
                        "scene artifact manifest",
                    ),
                    scene_contract=_json_value(
                        row["scene_contract"],
                        "scene contract",
                    ),
                ),
                "state": state,
                "accepted_revision_hash": row.get("accepted_revision_hash"),
                "access": access,
                "shots": shots,
                "synthetic": bool(row.get("synthetic")),
            }
        )
    return {
        "control_version": SCENE_CONTROL_VERSION,
        "video_id": director["video_id"],
        "director_contract_id": director["id"],
        "director_contract_hash": director["contract_hash"],
        "film_locks": lock_set,
        "current_scene_id": current_scene_id,
        "scenes": scenes,
    }


async def quote_scene_operation(
    conn: Any,
    *,
    tenant_id: str,
    video_id: str,
    scene_id: str,
    expected_revision_hash: str,
    operation_type: str,
    shot_id: str | None = None,
) -> dict[str, Any]:
    scene = await _scene_row(conn, tenant_id, video_id, scene_id, lock=False)
    await _assert_scene_accessible(
        conn,
        tenant_id,
        video_id,
        int(scene["scene_number"]),
    )
    expected = _digest(expected_revision_hash, "expected revision hash")
    if scene["revision_hash"] != expected:
        raise SceneControlError("Scene revision changed; reload before quoting")
    rule = OPERATION_RULES.get(operation_type)
    if rule is None:
        raise SceneControlError("Scene operation type is unsupported")
    if scene["state"] != rule["required_state"]:
        raise SceneControlError(
            f"{operation_type} requires scene state {rule['required_state']}"
        )
    lock_set = compile_lock_set(
        await _lock_rows(conn, tenant_id, scene["director_contract_id"])
    )
    if not lock_set["complete"] or lock_set["film_lock_set_hash"] != scene[
        "film_lock_set_hash"
    ]:
        raise SceneControlError("All current film foundations must be locked first")
    contract = compile_scene_contract(scene["scene_contract"])
    shot_rows = await conn.fetch(
        """SELECT shot_id, shot_contract
           FROM custom_film_shots
           WHERE tenant_id = $1 AND director_contract_id = $2
             AND shot_id = ANY($3::uuid[])""",
        tenant_id,
        scene["director_contract_id"],
        contract["shot_ids"],
    )
    dialogue_count = sum(
        len(_json_value(row["shot_contract"], "shot contract").get("spoken_lines") or [])
        for row in shot_rows
    )
    actual_cost = await conn.fetchval(
        """SELECT COALESCE(SUM(actual_cost), 0)
           FROM generation_ledger
           WHERE tenant_id = $1 AND video_id = $2""",
        tenant_id,
        video_id,
    )
    prior_cents = conservative_usd_to_cents(actual_cost)
    return compile_operation_quote(
        video_id=video_id,
        scene_id=scene["id"],
        scene_number=int(scene["scene_number"]),
        scene_revision_hash=expected,
        operation_type=operation_type,
        shot_ids=[str(value) for value in contract["shot_ids"]],
        dialogue_line_count=dialogue_count,
        prior_completed_cumulative_cents=prior_cents,
        requested_shot_id=shot_id,
    )


def synthetic_scene_contract(
    shot_rows: Sequence[Mapping[str, Any]],
    *,
    scene_number: int = 1,
    pilot: bool = True,
) -> dict[str, Any]:
    """Build a deterministic local fixture from four to six existing shots."""
    minimum = 4 if pilot else 1
    if not minimum <= len(shot_rows) <= 6:
        raise SceneControlError("Synthetic proof needs four to six shots")
    normalized = [
        {
            **dict(row),
            "shot_id": _uuid(row["shot_id"], "shot identity"),
            "shot_contract": _json_value(row["shot_contract"], "shot contract"),
        }
        for row in shot_rows
    ]
    contracts = [row["shot_contract"] for row in normalized]
    dialogue_turns = [
        {
            "speaker_id": line["speaker_id"],
            "text": line["text"],
            "performance_intent": (line.get("delivery") or "natural").split(
                "; frames ",
                1,
            )[0],
            "timing": (
                f"frames {(line.get('delivery') or '').split('; frames ', 1)[1]}"
                if "; frames " in (line.get("delivery") or "")
                else f"shot {shot.get('shot_key', index + 1)}"
            ),
        }
        for index, shot in enumerate(contracts)
        for line in shot.get("spoken_lines") or []
    ]
    silent = [
        beat
        for shot in contracts
        if shot.get("performance_mode") == "silent_action"
        for beat in (shot.get("action_beats") or [])
    ]
    first = contracts[0]
    last = contracts[-1]
    characters = list(
        dict.fromkeys(
            character_id
            for shot in contracts
            for character_id in shot.get("character_ids") or []
        )
    )
    environments = {
        str(shot.get("environment_id") or "") for shot in contracts
    }
    if len(environments) != 1:
        raise SceneControlError("Synthetic one-scene proof needs one environment")
    return compile_scene_contract(
        {
            "scene_number": scene_number,
            "purpose": (
                (
                    "Detect and isolate an internal relay intrusion, then "
                    "recover the paper trace that unlocks Scene 2."
                )
                if pilot
                else (
                    "Carry the recovered paper trace out of the relay room "
                    "to begin the next scene."
                )
            ),
            "target_duration_frames": sum(
                int(row["duration_frames"]) for row in normalized
            ),
            "story_time": (
                "continuous 18-second present-time beat"
                if pilot
                else "immediately after the 18-second relay-room beat"
            ),
            "opening_state": first["opening_state"]["story_facts"][0],
            "state_change": last["closing_state"]["story_facts"][0],
            "character_ids": characters,
            "environment_id": next(iter(environments)),
            "active_prop_ids": list(
                dict.fromkeys(
                    prop_id
                    for shot in contracts
                    for prop_id in shot.get("active_prop_ids") or []
                )
            ),
            "continuity_in": (
                "Same relay-room geography throughout, Mara screen-left at "
                "the console and Elias screen-right at the breaker until "
                "action motivates movement."
            ),
            "continuity_out": (
                "Elias throws the breaker, the relay collapses, and the "
                "console releases a paper trace to Mara."
                if pilot
                else "Mara carries the single paper trace into Scene 2."
            ),
            "dialogue_turns": dialogue_turns,
            "silent_action_beats": silent,
            "shot_ids": [row["shot_id"] for row in normalized],
        }
    )


def load_synthetic_control_manifest() -> dict[str, Any]:
    path = (
        Path(__file__).resolve().parents[2]
        / "remotion-video/src/custom-film/scene-control-proof-control-manifest.json"
    )
    try:
        manifest = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SceneControlError(
            "Synthetic Remotion control manifest is unavailable"
        ) from exc
    for key in (
        "asset_evidence",
        "director_contract",
        "storyboard_gate",
        "picture_gate",
        "visual_gate",
        "admission",
    ):
        entry = manifest.get(key)
        if (
            not isinstance(entry, Mapping)
            or canonical_hash(entry.get("payload")) != entry.get("sha256")
        ):
            raise SceneControlError(
                f"Synthetic Remotion {key} hash does not match its payload"
            )
    manifest_body = {
        key: value
        for key, value in manifest.items()
        if key != "manifest_sha256"
    }
    if canonical_hash(manifest_body) != manifest.get("manifest_sha256"):
        raise SceneControlError("Synthetic Remotion manifest hash is invalid")
    return manifest


def synthetic_scene_artifact_manifest(
    shot_rows: Sequence[Mapping[str, Any]],
    *,
    scene_contract: Mapping[str, Any],
) -> dict[str, Any]:
    contract = compile_scene_contract(scene_contract)
    if len(shot_rows) != 5 or len(contract["shot_ids"]) != 5:
        raise SceneControlError(
            "Synthetic Scene 1 artifact manifest requires exactly five shots"
        )
    control_manifest = load_synthetic_control_manifest()
    evidence = control_manifest["asset_evidence"]["payload"]
    clips = evidence.get("clips")
    assembly = evidence.get("assembly")
    if not isinstance(clips, list) or len(clips) != 5:
        raise SceneControlError("Synthetic shot evidence is invalid")
    if (
        not isinstance(assembly, list)
        or len(assembly) != 4
        or assembly[0] != "director-scene-control-proof.mp4"
        or int(assembly[2]) != int(contract["target_duration_frames"])
    ):
        raise SceneControlError("Synthetic assembly evidence is invalid")
    shots: list[dict[str, Any]] = []
    for index, (row, clip) in enumerate(zip(shot_rows, clips)):
        shot_contract = _json_value(row["shot_contract"], "shot contract")
        if (
            not isinstance(clip, list)
            or len(clip) != 2
            or clip[0] != f"scene_control_shot_{index + 1}"
        ):
            raise SceneControlError("Synthetic clip evidence identity is invalid")
        shots.append(
            {
                "shot_id": str(row["shot_id"]),
                "kind": "video",
                "url": SYNTHETIC_SHOT_MEDIA_URLS[index],
                "start_frame": int(shot_contract["start_frame"]),
                "end_frame": int(shot_contract["end_frame"]),
                "sha256": _digest(clip[1], "synthetic clip hash"),
            }
        )
    return compile_artifact_manifest(
        {
            "version": 1,
            "synthetic": True,
            "shots": shots,
            "assembly": {
                "kind": "video",
                "url": SYNTHETIC_ASSEMBLY_MEDIA_URL,
                "duration_frames": int(assembly[2]),
                "sha256": _digest(assembly[1], "synthetic assembly hash"),
            },
        },
        scene_contract=contract,
    )


def synthetic_director_draft(section_id: str) -> dict[str, Any]:
    """Return the canonical M9 proof plus one short locked-Scene-2 shot."""
    section = _uuid(section_id, "section identity")
    mara = "scene_control_character_mara"
    elias = "scene_control_character_elias"
    environment = "scene_control_environment_relay_room"
    opening_texts = (
        "Mara stands left of the relay console; Elias watches from the breaker wall.",
        "The amber key is seated and the relay line glows turquoise between Mara and Elias.",
        "Mara and Elias face the live turquoise relay line.",
        "The red relay line is active; Elias is nearest the breaker wall.",
        "Elias has reached the breaker; Mara remains beside the overloaded console.",
        "Mara holds the recovered paper trace as Elias opens the relay-room exit.",
    )
    closing_texts = (
        "Mara reaches the console and inserts the amber key while Elias holds position.",
        "Mara identifies the signal as internal; Elias realizes the intruder can detect them.",
        "The line expands red across the console and both characters recoil toward the center.",
        "Mara orders the transmitter killed as Elias reaches the breaker and reveals he anticipated her.",
        "Elias throws the breaker, the relay collapses, and the console releases a paper trace to Mara.",
        "Mara and Elias leave the relay room carrying the paper trace into Scene 2.",
    )
    progression = (
        "Establishes both recurring characters, the relay-room geography, and the key that starts the conflict.",
        "Turns the unexplained signal into an immediate threat with shared character knowledge.",
        "Uses an intentional dialogue-free reaction beat to make the threat visible before the decision.",
        "Converts discovery into a decisive coordinated action while preserving screen direction.",
        "Pays off the key and breaker setup, resolves the immediate threat, and creates the evidence that drives the next scene.",
        "Carries the recovered paper trace out of the relay room to begin the next scene.",
    )

    def state(
        facts: Sequence[str],
        *,
        mara_position: str,
        elias_position: str,
        relay_state: str,
        paper_trace: str,
    ) -> dict[str, Any]:
        return {
            "story_facts": list(facts),
            "character_positions": {
                mara: mara_position,
                elias: elias_position,
            },
            "prop_states": {
                "amber_relay_key": relay_state,
                "relay_console_line": relay_state,
                "breaker": relay_state,
                "paper_trace": paper_trace,
            },
            "emotional_state": {
                mara: "controlled and alert",
                elias: "contained urgency",
            },
        }

    # Continuous boundaries carry both the preceding closing sentence and the
    # following opening sentence, preserving the exact Remotion wording while
    # satisfying the director's frame-contiguous state law.
    states = (
        state(
            [opening_texts[0]],
            mara_position="screen-left at the relay console",
            elias_position="screen-right at the breaker wall",
            relay_state="amber key not yet seated; relay dark",
            paper_trace="inside console",
        ),
        state(
            [closing_texts[0], opening_texts[1]],
            mara_position="screen-left at the relay console",
            elias_position="screen-right at the breaker wall",
            relay_state="amber key seated; relay turquoise",
            paper_trace="inside console",
        ),
        state(
            [closing_texts[1], opening_texts[2]],
            mara_position="screen-left facing the turquoise line",
            elias_position="screen-right facing the turquoise line",
            relay_state="turquoise line active",
            paper_trace="inside console",
        ),
        state(
            [closing_texts[2], opening_texts[3]],
            mara_position="recoiling toward center from screen-left",
            elias_position="nearest the breaker at screen-right",
            relay_state="relay line expanded red",
            paper_trace="inside console",
        ),
        state(
            [closing_texts[3], opening_texts[4]],
            mara_position="beside overloaded console at screen-left",
            elias_position="at breaker wall screen-right",
            relay_state="red relay active; breaker grasped",
            paper_trace="inside console",
        ),
        state(
            [closing_texts[4], opening_texts[5]],
            mara_position="screen-left holding paper trace",
            elias_position="screen-right beside thrown breaker",
            relay_state="breaker off; relay collapsed",
            paper_trace="released to Mara",
        ),
        state(
            [closing_texts[5]],
            mara_position="at relay-room exit with paper trace",
            elias_position="holding exit open",
            relay_state="breaker off; relay collapsed",
            paper_trace="carried by Mara",
        ),
    )
    shot_specs = (
        ("establish_relay_room", 72, "cinematic_action", "silent_action", "opening"),
        ("signal_exchange", 96, "poco_dialogue", "dialogue", "location_cut"),
        ("silent_alarm_beat", 72, "cinematic_action", "silent_action", "continuous"),
        ("breaker_exchange", 96, "poco_dialogue", "dialogue", "continuous"),
        ("breaker_payoff", 96, "cinematic_action", "silent_action", "time_cut"),
        ("trace_departure", 48, "cinematic_action", "silent_action", "continuous"),
    )
    dialogue = {
        1: [
            {
                "speaker_id": mara,
                "kind": "dialogue",
                "text": "The signal is inside.",
                "language": "English",
                "delivery": "controlled discovery; frames 78-118",
                "addressee_id": elias,
            },
            {
                "speaker_id": elias,
                "kind": "dialogue",
                "text": "Then it knows we're here.",
                "language": "English",
                "delivery": "low urgent realization; frames 120-164",
                "addressee_id": mara,
            },
        ],
        3: [
            {
                "speaker_id": mara,
                "kind": "dialogue",
                "text": "Kill the transmitter.",
                "language": "English",
                "delivery": "clipped command; frames 246-286",
                "addressee_id": elias,
            },
            {
                "speaker_id": elias,
                "kind": "dialogue",
                "text": "Already did.",
                "language": "English",
                "delivery": "calm confirmation; frames 288-332",
                "addressee_id": mara,
            },
        ],
    }
    action_beats = (
        ["Mara inserts the amber key while Elias holds at the breaker wall."],
        ["Mara identifies the internal signal; Elias realizes it can detect them."],
        ["The turquoise relay expands red and both characters recoil in silence."],
        ["Mara orders the shutdown as Elias reaches the breaker."],
        ["Elias throws the breaker; the relay collapses; the paper trace reaches Mara."],
        ["Mara and Elias carry the paper trace through the relay-room exit."],
    )
    shots = []
    for index, (key, frames, technique, performance, transition) in enumerate(
        shot_specs
    ):
        shots.append(
            {
                "shot_key": key,
                "section_id": section,
                "duration_frames": frames,
                "technique": technique,
                "performance_mode": performance,
                "narrative_purpose": progression[index],
                "caused_by": [] if index == 0 else [shot_specs[index - 1][0]],
                "progression_kinds": (
                    ["story", "information", "emotion"]
                    if performance == "dialogue"
                    else ["story", "action", "spatial"]
                ),
                "story_value": progression[index],
                "opening_state": states[index],
                "action_beats": action_beats[index],
                "closing_state": states[index + 1],
                "transition_from_previous": transition,
                "continuity_bridge": (
                    None
                    if transition in {"opening", "continuous"}
                    else (
                        "The relay-room geography remains fixed across the "
                        f"{transition.replace('_', ' ')}."
                    )
                ),
                "environment_id": environment,
                "character_ids": [mara, elias],
                "active_prop_ids": [
                    "amber_relay_key",
                    "relay_console_line",
                    "breaker",
                    "paper_trace",
                ],
                "screen_direction": (
                    "Mara remains screen-left at the console and Elias screen-right "
                    "at the breaker until motivated action moves them."
                ),
                "shot_size": "grounded relay-room two-shot with readable hands",
                "camera_move": "restrained motivated push toward the changed state",
                "spoken_lines": dialogue.get(index, []),
                "storyboard_composition": (
                    "Exact relay-room geography, locked characters, amber key, "
                    "relay line, breaker, and paper trace remain readable."
                ),
                "final_picture_intent": (
                    "Photoreal relay-room opening frame preserving Mara, Elias, "
                    "console, breaker wall, props, and exact screen direction."
                ),
                "motion_intent": progression[index],
                "ambient_sound": "low relay-room electrical ambience",
                "score_intent": "restrained pulse that drops at the breaker payoff",
                "sfx_cues": action_beats[index],
                "caption_mode": "dialogue" if performance == "dialogue" else "none",
            }
        )
    return {
        "film_bible": {
            "title": "Scene Control Relay-Room Proof",
            "logline": (
                "Mara and Elias detect and isolate an internal relay intrusion, "
                "then recover the paper trace that unlocks Scene 2."
            ),
            "throughline": (
                "An amber key reveals an internal signal; a breaker shutdown "
                "turns the threat into physical evidence for the next scene."
            ),
            "central_question": "Can Mara and Elias isolate the intrusion before it locates them?",
            "beginning_state": opening_texts[0],
            "ending_state": closing_texts[5],
            "visual_motif": "turquoise relay light turning red around an amber key",
            "timeline_law": "Scene 1 is one continuous 18-second present-time beat.",
            "geography_law": (
                "Same relay-room geography throughout: Mara screen-left at the "
                "console and Elias screen-right at the breaker until action moves them."
            ),
            "narrator_mode": "none",
            "narrator_character_id": None,
            "narrator_voice_lock": None,
            "style": {
                "medium": "cinematic photoreal live action",
                "rendering_approach": "grounded practical relay-room production design",
                "palette": ["turquoise relay light", "alarm red", "amber key"],
                "texture": "brushed metal, paper trace, practical electrical glow",
                "lens_language": "readable wides, controlled dialogue singles, payoff insert",
                "lighting_law": "turquoise relay light expands red before breaker blackout",
                "aspect_ratio": "16:9",
                "negative_constraints": ["illustration", "identity drift", "geography drift"],
            },
            "characters": [
                {
                    "character_id": mara,
                    "display_name": "Mara",
                    "story_role": "operator who detects and commands isolation of the intrusion",
                    "identity_prompt": "Mara, a focused relay operator in the canonical proof",
                    "face_body_lock": "Mara's face, proportions, and screen-left silhouette remain fixed",
                    "wardrobe_lock": "dark relay-room field jacket with amber key at the console",
                    "voice_lock": "controlled discovery becoming a clipped command",
                    "performance_law": "precise console work followed by decisive command",
                    "forbidden_drift": ["different identity", "wardrobe change", "screen-side swap"],
                },
                {
                    "character_id": elias,
                    "display_name": "Elias",
                    "story_role": "breaker operator who anticipates and completes the shutdown",
                    "identity_prompt": "Elias, a contained relay technician in the canonical proof",
                    "face_body_lock": "Elias's face, proportions, and screen-right silhouette remain fixed",
                    "wardrobe_lock": "dark breaker-wall technician clothing with work gloves",
                    "voice_lock": "low urgent realization followed by calm confirmation",
                    "performance_law": "contained reaction followed by economical breaker action",
                    "forbidden_drift": ["different identity", "wardrobe change", "screen-side swap"],
                },
            ],
            "environments": [
                {
                    "environment_id": environment,
                    "display_name": "Relay Room",
                    "story_function": "single geography where intrusion becomes physical evidence",
                    "identity_prompt": "industrial relay room with console left and breaker wall right",
                    "architecture_lock": "relay console screen-left, breaker wall screen-right, exit behind",
                    "lighting_time_weather_lock": "turquoise internal light expands red before blackout",
                    "geography_lock": "Mara at console left; Elias at breaker right until motivated movement",
                    "palette_lock": "turquoise, alarm red, amber key, dark brushed metal",
                    "props": [
                        {
                            "prop_id": "amber_relay_key",
                            "description": "amber key inserted by Mara",
                            "home_position": "Mara's hand then relay console",
                            "continuity_law": "one key, fixed amber material and scale",
                        },
                        {
                            "prop_id": "relay_console_line",
                            "description": "relay line that changes turquoise to red",
                            "home_position": "relay console screen-left",
                            "continuity_law": "turquoise before threat, red during overload, dark after breaker",
                        },
                        {
                            "prop_id": "breaker",
                            "description": "shutdown breaker operated by Elias",
                            "home_position": "breaker wall screen-right",
                            "continuity_law": "up before payoff and thrown once by Elias",
                        },
                        {
                            "prop_id": "paper_trace",
                            "description": "paper evidence released by the console",
                            "home_position": "inside console until payoff, then Mara's hand",
                            "continuity_law": "single trace persists into Scene 2",
                        },
                    ],
                }
            ],
        },
        "shots": shots,
    }


async def ensure_synthetic_director_fixture(
    conn: Any,
    *,
    tenant_id: str,
    video_id: str | None = None,
) -> dict[str, Any]:
    """Create the tagged deterministic video/plan/director baseline if absent."""
    normalized_tenant = _uuid(tenant_id, "tenant identity")
    normalized_video = (
        _uuid(video_id, "video identity")
        if video_id is not None
        else str(
            uuid5(
                SYNTHETIC_FIXTURE_NAMESPACE,
                f"{normalized_tenant}:scene-control-video",
            )
        )
    )
    plan_id = str(
        uuid5(SYNTHETIC_FIXTURE_NAMESPACE, f"{normalized_video}:plan")
    )
    section_id = str(
        uuid5(SYNTHETIC_FIXTURE_NAMESPACE, f"{normalized_video}:section")
    )
    plan_payload = {
        "synthetic": True,
        "purpose": "deterministic_scene_control_proof",
        "sections": [
            {
                "section_id": section_id,
                "order_index": 0,
                "role": "synthetic_scene_control",
                "duration_units": 20,
            }
        ],
    }
    plan_hash = canonical_hash(plan_payload)
    quote_inputs = {
        "synthetic": True,
        "provider_calls": 0,
        "requested_duration_seconds": 20,
    }
    quote_hash = canonical_hash(quote_inputs)
    draft = synthetic_director_draft(section_id)
    compiled = compile_director_contract(
        draft,
        plan_id=plan_id,
        plan_hash=plan_hash,
        section_ids=[section_id],
        total_frames=480,
        section_frame_counts={section_id: 480},
        section_shot_counts={section_id: 6},
        fps=24,
    )

    async def existing_fixture() -> dict[str, Any] | None:
        video_row = await conn.fetchrow(
            """SELECT id, tenant_id, video_title, status, source, max_spend,
                      writer_guidance, custom_film_plan_id,
                      custom_film_plan_revision, custom_film_plan_hash,
                      custom_film_quote_inputs_hash
               FROM videos
               WHERE id = $1""",
            normalized_video,
        )
        if not video_row:
            return None
        expected_video_fields = {
            "tenant_id": normalized_tenant,
            "video_title": SYNTHETIC_VIDEO_TITLE,
            "status": SYNTHETIC_VIDEO_STATUS,
            "source": SYNTHETIC_VIDEO_SOURCE,
            "writer_guidance": SYNTHETIC_VIDEO_GUIDANCE,
        }
        try:
            zero_spend = (
                Decimal(str(video_row.get("max_spend"))) == Decimal("0")
            )
        except InvalidOperation:
            zero_spend = False
        if any(
            str(video_row.get(key) or "") != expected
            for key, expected in expected_video_fields.items()
        ) or not zero_spend:
            raise SceneControlError(
                "Refusing to attach synthetic Scene Control data to an existing video"
            )
        expected_video_bindings = {
            "custom_film_plan_id": plan_id,
            "custom_film_plan_revision": 1,
            "custom_film_plan_hash": plan_hash,
            "custom_film_quote_inputs_hash": quote_hash,
        }
        if any(
            str(video_row.get(key) or "") != str(expected)
            for key, expected in expected_video_bindings.items()
        ):
            raise SceneControlError(
                "Existing synthetic video does not match its deterministic plan"
            )
        plan_row = await conn.fetchrow(
            """SELECT id, revision, compatibility_version, plan, plan_hash,
                      quote_inputs, quote_inputs_hash
               FROM custom_film_plans
               WHERE tenant_id = $1 AND video_id = $2 AND id = $3
                 AND revision = 1""",
            normalized_tenant,
            normalized_video,
            plan_id,
        )
        if (
            not plan_row
            or str(plan_row["compatibility_version"]) != "scene-control-synthetic-v1"
            or str(plan_row["plan_hash"]) != plan_hash
            or str(plan_row["quote_inputs_hash"]) != quote_hash
            or canonical_json(_json_value(plan_row["plan"], "synthetic plan"))
            != canonical_json(plan_payload)
            or canonical_json(
                _json_value(plan_row["quote_inputs"], "synthetic quote inputs")
            )
            != canonical_json(quote_inputs)
        ):
            raise SceneControlError(
                "Existing synthetic video plan is not the deterministic fixture"
            )
        director_row = await conn.fetchrow(
            """SELECT id, plan_id, revision, plan_hash, director_contract,
                      contract_hash
               FROM custom_film_director_contracts
               WHERE tenant_id = $1 AND video_id = $2
               ORDER BY revision DESC LIMIT 1""",
            normalized_tenant,
            normalized_video,
        )
        if (
            not director_row
            or str(director_row["plan_id"]) != plan_id
            or int(director_row["revision"]) != 1
            or str(director_row["plan_hash"]) != plan_hash
            or str(director_row["contract_hash"]) != compiled["contract_hash"]
            or canonical_json(
                _json_value(
                    director_row["director_contract"],
                    "synthetic director contract",
                )
            )
            != canonical_json(compiled)
        ):
            raise SceneControlError(
                "Existing synthetic video director is not the deterministic fixture"
            )
        return {
            "video_id": normalized_video,
            "director_contract_id": str(director_row["id"]),
            "created": False,
        }

    existing = await existing_fixture()
    if existing:
        return existing
    await conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
        f"custom-film-scene-control-seed:{normalized_tenant}:{normalized_video}",
    )
    existing = await existing_fixture()
    if existing:
        return existing
    video = await conn.fetchrow(
        """INSERT INTO videos
             (id, tenant_id, video_title, status, source,
              video_length_minutes, max_spend, writer_guidance)
           VALUES ($1, $2, $3, $4, $5, 0.333333, 0, $6)
           RETURNING id""",
        normalized_video,
        normalized_tenant,
        SYNTHETIC_VIDEO_TITLE,
        SYNTHETIC_VIDEO_STATUS,
        SYNTHETIC_VIDEO_SOURCE,
        SYNTHETIC_VIDEO_GUIDANCE,
    )
    if not video:
        raise SceneControlError("Synthetic Scene Control video creation failed")
    await conn.execute(
        """INSERT INTO custom_film_plans
             (id, tenant_id, video_id, revision, compatibility_version,
              plan, plan_hash, quote_inputs, quote_inputs_hash)
           VALUES ($1, $2, $3, 1, 'scene-control-synthetic-v1',
                   $4::jsonb, $5, $6::jsonb, $7)
           ON CONFLICT (tenant_id, video_id, revision) DO NOTHING""",
        plan_id,
        normalized_tenant,
        normalized_video,
        canonical_json(plan_payload),
        plan_hash,
        canonical_json(quote_inputs),
        quote_hash,
    )
    await conn.execute(
        """INSERT INTO custom_film_sections
             (tenant_id, plan_id, video_id, section_id, order_index, role,
              purpose, duration_units, knobs, provenance, estimated_media)
           VALUES ($1, $2, $3, $4, 0, 'synthetic_scene_control',
                   'Deterministic local Scene Control proof', 20,
                   '{}'::jsonb, $5::jsonb, $6::jsonb)
           ON CONFLICT (tenant_id, plan_id, section_id) DO NOTHING""",
        normalized_tenant,
        plan_id,
        normalized_video,
        section_id,
        canonical_json({"source": "operator_cli", "synthetic": True}),
        canonical_json({"provider_calls": 0, "shots": 6}),
    )
    persisted = await persist_director_contract(
        conn,
        tenant_id=normalized_tenant,
        video_id=normalized_video,
        plan_id=plan_id,
        plan_hash=plan_hash,
        director_contract=compiled,
    )
    await conn.execute(
        """UPDATE videos
           SET custom_film_plan_id = $3, custom_film_plan_revision = 1,
               custom_film_plan_hash = $4, custom_film_quote_inputs_hash = $5,
               updated_at = now()
           WHERE tenant_id = $1 AND id = $2""",
        normalized_tenant,
        normalized_video,
        plan_id,
        plan_hash,
        quote_hash,
    )
    return {
        "video_id": normalized_video,
        "director_contract_id": persisted["id"],
        "created": bool(video) or persisted["created"],
    }


async def seed_synthetic_one_scene(
    conn: Any,
    *,
    tenant_id: str,
    video_id: str | None = None,
) -> dict[str, Any]:
    """Idempotently seed film locks and one synthetic scene; never generate."""
    fixture = await ensure_synthetic_director_fixture(
        conn,
        tenant_id=tenant_id,
        video_id=video_id,
    )
    video_id = fixture["video_id"]
    director = await _load_director(conn, tenant_id, video_id)
    bible = director["contract"]["film_bible"]
    payloads = {
        "story": {
            key: bible[key]
            for key in (
                "title",
                "logline",
                "throughline",
                "central_question",
                "beginning_state",
                "ending_state",
                "timeline_law",
                "geography_law",
            )
        },
        "dialogue": {
            "narrator_mode": bible["narrator_mode"],
            "narrator_character_id": bible.get("narrator_character_id"),
            "narrator_voice_lock": bible.get("narrator_voice_lock"),
            "speaker_voices": {
                row["character_id"]: row["voice_lock"]
                for row in bible["characters"]
            },
        },
        "style": bible["style"],
        "cast": bible["characters"],
        "environments": bible["environments"],
        "techniques": {
            "allowed": sorted(
                {shot["technique"] for shot in director["contract"]["shots"]}
            ),
            "film_identity_override": False,
        },
    }
    lock_results = []
    for kind in LOCK_KINDS:
        lock_results.append(
            await approve_film_lock(
                conn,
                tenant_id=tenant_id,
                video_id=video_id,
                lock_kind=kind,
                payload=payloads[kind],
                synthetic=True,
            )
        )
    shots = await conn.fetch(
        """SELECT shot_id, duration_frames, shot_contract
           FROM custom_film_shots
           WHERE tenant_id = $1 AND director_contract_id = $2
           ORDER BY order_index
           LIMIT 10""",
        tenant_id,
        director["id"],
    )
    if len(shots) < 5:
        raise SceneControlError(
            "Director contract needs at least five shots to seed Scene 1 and locked Scene 2"
        )
    scene_one_rows = shots[: min(6, len(shots) - 1)]
    scene_two_rows = shots[len(scene_one_rows) : min(len(shots), len(scene_one_rows) + 6)]
    scene_one_contract = synthetic_scene_contract(scene_one_rows)
    scene_one = await create_scene(
        conn,
        tenant_id=tenant_id,
        video_id=video_id,
        raw_scene_contract=scene_one_contract,
        artifact_manifest=synthetic_scene_artifact_manifest(
            scene_one_rows,
            scene_contract=scene_one_contract,
        ),
        synthetic=True,
    )
    scene_two = await create_scene(
        conn,
        tenant_id=tenant_id,
        video_id=video_id,
        raw_scene_contract=synthetic_scene_contract(
            scene_two_rows,
            scene_number=2,
            pilot=False,
        ),
        synthetic=True,
    )
    snapshot = await read_scene_control(
        conn,
        tenant_id=tenant_id,
        video_id=video_id,
    )
    return {
        "synthetic": True,
        "provider_calls_started": False,
        "ledger_writes": 0,
        "video_id": video_id,
        "director_fixture_created": fixture["created"],
        "locks": lock_results,
        "scenes": [scene_one, scene_two],
        "control": snapshot,
    }
