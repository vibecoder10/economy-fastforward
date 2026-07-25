"""Immutable Custom Film section runtime and exactly-once scheduling door."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from custom_film_contract import (
    CustomFilmContractError,
    approval_binding_hash,
    canonical_hash,
    plan_hash,
)
from database import get_pool
from production_styles import runtime_values_from_knobs


RUNTIME_VERSION = "custom-film-runtime-v1"
SCRIPTS_FIRST_AV_EXECUTION_MODEL = "scripts_first_av_v1"


def _object(value: Any, name: str) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            value = None
    if not isinstance(value, Mapping):
        raise CustomFilmContractError(f"Custom Film {name} is invalid")
    return copy.deepcopy(dict(value))


def _updated_once(result: Any) -> bool:
    if isinstance(result, str):
        return result.rsplit(" ", 1)[-1] == "1"
    if isinstance(result, int):
        return result == 1
    return bool(result)


def _exact_int(value: Any, name: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise CustomFilmContractError(
            f"Custom Film {name} must be an exact integer of at least {minimum}"
        )
    return value


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return copy.deepcopy(value)


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return copy.deepcopy(value)


@dataclass(frozen=True)
class RuntimeSection:
    section_id: str
    order_index: int
    duration_seconds: int
    role: str
    purpose: str
    render_mode: str
    script_profile: str
    visual_profile: str
    dialogue_audio: str
    image_density: Mapping[str, Any]
    animation: Mapping[str, Any]
    language: Mapping[str, Any]
    dubbing: Mapping[str, Any]
    segmentation: Mapping[str, Any]
    camera: Mapping[str, Any]
    quality_laws: tuple[str, ...]
    image_source: str
    provenance: Mapping[str, Any]
    estimated_media: Mapping[str, Any]

    def stage_values(self) -> dict[str, Any]:
        return {
            "section_id": self.section_id,
            "order_index": self.order_index,
            "duration_seconds": self.duration_seconds,
            "role": self.role,
            "purpose": self.purpose,
            "render_mode": self.render_mode,
            "script_profile": self.script_profile,
            "visual_profile": self.visual_profile,
            "dialogue_audio": self.dialogue_audio,
            "image_density": _thaw(self.image_density),
            "animation": _thaw(self.animation),
            "language": _thaw(self.language),
            "dubbing": _thaw(self.dubbing),
            "segmentation": _thaw(self.segmentation),
            "camera": _thaw(self.camera),
            "quality_laws": list(self.quality_laws),
            "image_source": self.image_source,
            "provenance": _thaw(self.provenance),
            "estimated_media": _thaw(self.estimated_media),
        }


@dataclass(frozen=True)
class RuntimePlan:
    video_id: str
    plan_id: str
    plan_hash: str
    quote_inputs_hash: str
    approval_hash: str
    total_duration_seconds: int
    max_spend: float
    sections: tuple[RuntimeSection, ...]

    @property
    def runtime_hash(self) -> str:
        return canonical_hash(self._envelope_base())

    def stage_plan(self) -> tuple[dict[str, Any], ...]:
        scripts: list[dict[str, Any]] = []
        downstream: list[dict[str, Any]] = []
        for section in self.sections:
            stages = ["script", "voice", "pictures"]
            if bool(section.animation.get("enabled")):
                stages.extend(("motion", "clips"))
            stages.append("quality")
            for stage in stages:
                item = {
                    "section_id": section.section_id,
                    "order_index": section.order_index,
                    "stage": stage,
                    "duration_seconds": section.duration_seconds,
                    "values": section.stage_values(),
                }
                (scripts if stage == "script" else downstream).append(item)
        # New schedules establish a whole-film screenplay barrier: every
        # script must pass before any voice, imagery, motion, or clip work.
        return tuple((*scripts, *downstream))

    def envelope(self) -> dict[str, Any]:
        return {"runtime_hash": self.runtime_hash, **self._envelope_base()}

    def _envelope_base(self) -> dict[str, Any]:
        return {
            "runtime_version": RUNTIME_VERSION,
            "execution_model": SCRIPTS_FIRST_AV_EXECUTION_MODEL,
            "video_id": self.video_id,
            "plan_id": self.plan_id,
            "plan_hash": self.plan_hash,
            "quote_inputs_hash": self.quote_inputs_hash,
            "approval_hash": self.approval_hash,
            "total_duration_seconds": self.total_duration_seconds,
            "max_spend": self.max_spend,
            "sections": [section.stage_values() for section in self.sections],
            "stage_plan": list(self.stage_plan()),
        }


def compile_runtime_plan(
    *,
    video_id: str,
    plan_id: str,
    normalized_plan: Mapping[str, Any],
    quote_inputs: Mapping[str, Any],
    expected_plan_hash: str,
    expected_quote_inputs_hash: str,
    expected_approval_hash: str,
    max_spend: float,
) -> RuntimePlan:
    """Compile only the exact still-approved plan into immutable stage values."""
    plan = _object(normalized_plan, "plan")
    quote = _object(quote_inputs, "estimate")
    actual_plan_hash = plan_hash(plan)
    actual_quote_hash = canonical_hash(quote)
    actual_approval = approval_binding_hash(actual_plan_hash, quote)
    if (
        actual_plan_hash != str(expected_plan_hash)
        or actual_quote_hash != str(expected_quote_inputs_hash)
        or actual_approval != str(expected_approval_hash)
    ):
        raise CustomFilmContractError(
            "This Custom Film plan or estimate changed. Review and approve it again."
        )

    plan_sections = plan.get("sections")
    quote_sections = quote.get("sections")
    if not isinstance(plan_sections, list) or not isinstance(quote_sections, list):
        raise CustomFilmContractError("Custom Film sections are incomplete")
    if len(plan_sections) != len(quote_sections) or not plan_sections:
        raise CustomFilmContractError("Custom Film plan and estimate sections differ")
    quote_by_id = {
        str(row.get("section_id") or ""): row
        for row in quote_sections
        if isinstance(row, Mapping)
    }
    if len(quote_by_id) != len(quote_sections):
        raise CustomFilmContractError("Custom Film estimate has duplicate section IDs")

    sections: list[RuntimeSection] = []
    for expected_index, section_value in enumerate(plan_sections):
        section = _object(section_value, "section")
        section_id = str(section.get("section_id") or "")
        quote_row = quote_by_id.get(section_id)
        if not isinstance(quote_row, Mapping):
            raise CustomFilmContractError(
                "Custom Film estimate does not match the approved sections"
            )
        if _exact_int(section.get("order_index"), "section order") != expected_index or _exact_int(
            quote_row.get("order_index"), "estimate section order"
        ) != expected_index:
            raise CustomFilmContractError("Custom Film section order changed")
        duration_seconds = _exact_int(
            quote_row.get("duration_seconds"), "section runtime", minimum=1
        )
        knobs = _object(section.get("knobs"), "section knobs")
        resolved = runtime_values_from_knobs(knobs)
        image_source = str(knobs.get("image_source") or "")
        if image_source != "generate":
            raise CustomFilmContractError("Unsupported Custom Film image source")
        animation = _object(knobs.get("animation"), "animation")
        if resolved["render_mode"] == "static_docu" and bool(
            animation.get("enabled")
        ):
            raise CustomFilmContractError(
                "Static Custom Film sections cannot schedule animated clips"
            )
        estimated_media = {
            "still_images": _exact_int(
                quote_row.get("still_images"), "still-image count"
            ),
            "animation_clips": _exact_int(
                quote_row.get("animation_clips"), "animation-clip count"
            ),
            "voice_tracks": _exact_int(
                quote_row.get("voice_tracks"), "voice-track count"
            ),
        }
        if bool(animation.get("enabled")) != bool(
            estimated_media["animation_clips"]
        ):
            raise CustomFilmContractError(
                "Custom Film animation does not match the approved estimate"
            )
        sections.append(
            RuntimeSection(
                section_id=section_id,
                order_index=expected_index,
                duration_seconds=duration_seconds,
                role=str(section.get("role") or ""),
                purpose=str(section.get("purpose") or ""),
                render_mode=resolved["render_mode"],
                script_profile=resolved["script_profile"],
                visual_profile=resolved["visual_profile"],
                dialogue_audio=resolved["dialogue_audio"],
                image_density=_freeze(_object(knobs.get("image_density"), "image density")),
                animation=_freeze(animation),
                language=_freeze(_object(knobs.get("language"), "language")),
                dubbing=_freeze(_object(knobs.get("dubbing"), "dubbing")),
                segmentation=_freeze(_object(knobs.get("segmentation"), "segmentation")),
                camera=_freeze(_object(knobs.get("camera"), "camera")),
                quality_laws=tuple(
                    str(value)
                    for value in (
                        knobs.get("quality_laws")
                        if isinstance(knobs.get("quality_laws"), list)
                        else []
                    )
                    if str(value)
                ),
                image_source=image_source,
                provenance=_freeze(_object(section.get("provenance"), "provenance")),
                estimated_media=_freeze(estimated_media),
            )
        )

    total_seconds = _exact_int(
        quote.get("requested_duration_seconds"), "total runtime", minimum=1
    )
    if sum(s.duration_seconds for s in sections) != total_seconds:
        raise CustomFilmContractError(
            "Custom Film exact section runtimes do not reconcile"
        )
    quoted_total = float(
        _object(quote.get("totals"), "estimate totals").get("estimated_cost") or 0
    )
    if max_spend < quoted_total:
        raise CustomFilmContractError(
            "This Custom Film exceeds its current spending cap. Nothing was scheduled."
        )
    return RuntimePlan(
        video_id=str(video_id),
        plan_id=str(plan_id),
        plan_hash=actual_plan_hash,
        quote_inputs_hash=actual_quote_hash,
        approval_hash=actual_approval,
        total_duration_seconds=total_seconds,
        max_spend=float(max_spend),
        sections=tuple(sections),
    )


async def consume_approval_and_schedule(
    tenant_id: str,
    video_id: str,
    expected_approval_hash: str,
) -> dict[str, Any]:
    """Atomically recompile, consume exact approval, and insert one durable task."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """SELECT v.custom_film_plan_id, v.custom_film_plan_hash,
                          v.custom_film_quote_inputs_hash,
                          v.custom_film_approval_hash, v.max_spend,
                          p.plan, p.plan_hash, p.quote_inputs,
                          p.quote_inputs_hash, p.approval_hash
                   FROM videos v
                   JOIN custom_film_plans p
                     ON p.id = v.custom_film_plan_id
                    AND p.tenant_id = v.tenant_id
                    AND p.video_id = v.id
                   WHERE v.tenant_id = $1 AND v.id = $2
                     AND v.deleted_at IS NULL
                   FOR UPDATE OF v, p""",
                tenant_id,
                video_id,
            )
            if not row:
                raise CustomFilmContractError("Current Custom Film plan not found")
            runtime = compile_runtime_plan(
                video_id=video_id,
                plan_id=str(row["custom_film_plan_id"]),
                normalized_plan=_object(row["plan"], "plan"),
                quote_inputs=_object(row["quote_inputs"], "estimate"),
                expected_plan_hash=str(row["plan_hash"]),
                expected_quote_inputs_hash=str(row["quote_inputs_hash"]),
                expected_approval_hash=expected_approval_hash,
                max_spend=float(row["max_spend"]),
            )
            if (
                str(row["custom_film_plan_hash"]) != runtime.plan_hash
                or str(row["custom_film_quote_inputs_hash"])
                != runtime.quote_inputs_hash
            ):
                raise CustomFilmContractError(
                    "This Custom Film plan pointer changed. Review it again."
                )
            job_id = f"custom-film-runtime:{runtime.runtime_hash}"
            approvals_current = (
                str(row.get("custom_film_approval_hash") or "")
                == expected_approval_hash
                and str(row.get("approval_hash") or "") == expected_approval_hash
            )
            if not approvals_current:
                existing = await conn.fetchrow(
                    """SELECT job_id, runtime_envelope
                       FROM background_tasks
                       WHERE tenant_id = $1 AND video_id = $2
                         AND task_type = 'custom_film_runtime'
                         AND job_id = $3
                         AND runtime_envelope->>'approval_hash' = $4
                         AND runtime_envelope->>'runtime_hash' = $5""",
                    tenant_id,
                    video_id,
                    job_id,
                    expected_approval_hash,
                    runtime.runtime_hash,
                )
                if existing:
                    envelope = validate_runtime_envelope(existing["runtime_envelope"])
                    return {
                        "scheduled": False,
                        "job_id": str(existing["job_id"]),
                        "video_id": video_id,
                        "envelope": envelope,
                    }
                raise CustomFilmContractError(
                    "This Custom Film approval is stale or was already used."
                )
            envelope = runtime.envelope()
            inserted = await conn.fetchrow(
                """INSERT INTO background_tasks
                     (tenant_id, video_id, task_type, status, message, job_id,
                      attempt, started_at, runtime_envelope)
                   VALUES ($1, $2, 'custom_film_runtime', 'pending',
                           'Preparing approved section runtime', $3, 1, now(),
                           $4::jsonb)
                   ON CONFLICT (job_id) WHERE job_id IS NOT NULL DO NOTHING
                   RETURNING id""",
                tenant_id,
                video_id,
                job_id,
                json.dumps(envelope, sort_keys=True, separators=(",", ":")),
            )
            if inserted:
                plan_result = await conn.execute(
                    """UPDATE custom_film_plans
                       SET approval_hash = NULL, approved_at = NULL
                       WHERE tenant_id = $1 AND id = $2 AND approval_hash = $3""",
                    tenant_id,
                    runtime.plan_id,
                    expected_approval_hash,
                )
                result = await conn.execute(
                    """UPDATE videos
                       SET custom_film_approval_hash = NULL,
                           custom_film_approved_at = NULL,
                           status = 'ready_for_scripting',
                           updated_at = now()
                       WHERE tenant_id = $1 AND id = $2
                         AND custom_film_approval_hash = $3""",
                    tenant_id,
                    video_id,
                    expected_approval_hash,
                )
                if not _updated_once(plan_result) or not _updated_once(result):
                    raise CustomFilmContractError(
                        "Custom Film approval could not be consumed"
                    )
            return {
                "scheduled": bool(inserted),
                "job_id": job_id,
                "video_id": video_id,
                "runtime": runtime,
                "envelope": envelope,
            }


def validate_runtime_envelope(value: Any) -> dict[str, Any]:
    """Validate a durable envelope before a restarted worker consumes it."""
    envelope = _object(value, "runtime envelope")
    if envelope.get("runtime_version") != RUNTIME_VERSION:
        raise CustomFilmContractError("Custom Film runtime version is unsupported")
    runtime_hash = str(envelope.get("runtime_hash") or "")
    base = dict(envelope)
    base.pop("runtime_hash", None)
    if canonical_hash(base) != runtime_hash:
        raise CustomFilmContractError("Custom Film runtime envelope hash is invalid")
    stage_plan = envelope.get("stage_plan")
    sections = envelope.get("sections")
    if not isinstance(stage_plan, list) or not isinstance(sections, list) or not sections:
        raise CustomFilmContractError("Custom Film runtime envelope is incomplete")
    return envelope


async def load_exact_runtime_schedule(
    tenant_id: str,
    video_id: str,
    expected_approval_hash: str,
) -> dict[str, Any] | None:
    """Load only the durable job for this exact reserved approval identity."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT job_id, runtime_envelope
               FROM background_tasks
               WHERE tenant_id = $1 AND video_id = $2
                 AND task_type = 'custom_film_runtime'
                 AND runtime_envelope->>'approval_hash' = $3""",
            tenant_id,
            video_id,
            expected_approval_hash,
        )
    if not row:
        return None
    envelope = validate_runtime_envelope(row["runtime_envelope"])
    expected_job = f"custom-film-runtime:{envelope['runtime_hash']}"
    if str(row["job_id"]) != expected_job:
        raise CustomFilmContractError("Custom Film runtime job identity is invalid")
    return {"job_id": expected_job, "envelope": envelope}
