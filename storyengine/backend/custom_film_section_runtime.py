"""Restart-safe Custom Film section consumer and shared stage adapters.

This module is the only runtime boundary allowed to interpret a persisted
Custom Film envelope.  Stage implementations receive resolved section values;
they never inspect ``custom_film`` mode or public profile IDs themselves.
"""

from __future__ import annotations

import copy
import inspect
import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Protocol

import database
import generation_claims
from custom_film_contract import CustomFilmContractError
from custom_film_runtime import (
    RUNTIME_VERSION,
    SCRIPTS_FIRST_AV_EXECUTION_MODEL,
    validate_runtime_envelope,
)
from error_utils import humanize_error


SUPPORTED_STAGES = frozenset(
    {"script", "voice", "pictures", "motion", "clips", "quality"}
)


def _updated_once(result: Any) -> bool:
    if isinstance(result, str):
        return result.rsplit(" ", 1)[-1] == "1"
    if isinstance(result, int):
        return result == 1
    return bool(result)


def _object(value: Any, name: str) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            value = None
    if not isinstance(value, Mapping):
        raise CustomFilmContractError(f"Custom Film {name} is invalid")
    return copy.deepcopy(dict(value))


def _exact_int(value: Any, name: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise CustomFilmContractError(
            f"Custom Film {name} must be an exact integer of at least {minimum}"
        )
    return value


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze(item) for key, item in value.items()}
        )
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
class SectionStageAdapter:
    """Immutable, provider-ready values for exactly one section stage."""

    runtime_hash: str
    plan_id: str
    video_id: str
    section_id: str
    order_index: int
    stage: str
    duration_seconds: int
    role: str
    purpose: str
    render_mode: str
    script_profile: str
    visual_profile: str
    dialogue_audio: str
    image_density: Mapping[str, Any]
    language: Mapping[str, Any]
    dubbing: Mapping[str, Any]
    animation: Mapping[str, Any]
    segmentation: Mapping[str, Any]
    camera: Mapping[str, Any]
    quality_laws: tuple[str, ...]
    image_source: str
    provenance: Mapping[str, Any]
    estimated_media: Mapping[str, Any]
    story_arc: tuple[Mapping[str, Any], ...] = ()

    @property
    def stage_key(self) -> str:
        return f"{self.order_index}:{self.section_id}:{self.stage}"

    def provider_values(self) -> dict[str, Any]:
        """Return a detached payload safe to hand to a stage/provider seam."""
        values = {
            "runtime_hash": self.runtime_hash,
            "plan_id": self.plan_id,
            "video_id": self.video_id,
            "section_id": self.section_id,
            "order_index": self.order_index,
            "stage": self.stage,
            "duration_seconds": self.duration_seconds,
            "role": self.role,
            "purpose": self.purpose,
            "render_mode": self.render_mode,
            "script_profile": self.script_profile,
            "visual_profile": self.visual_profile,
            "dialogue_audio": self.dialogue_audio,
            "image_density": _thaw(self.image_density),
            "language": _thaw(self.language),
            "dubbing": _thaw(self.dubbing),
            "animation": _thaw(self.animation),
            "segmentation": _thaw(self.segmentation),
            "camera": _thaw(self.camera),
            "quality_laws": list(self.quality_laws),
            "image_source": self.image_source,
            "provenance": _thaw(self.provenance),
            "estimated_media": _thaw(self.estimated_media),
        }
        if self.stage == "script":
            values["story_arc"] = _thaw(self.story_arc)
        return values


class SectionStageRunner(Protocol):
    async def __call__(
        self,
        adapter: SectionStageAdapter,
        scene_ids: tuple[str, ...],
        operation_id: str,
    ) -> Mapping[str, Any] | None: ...


class ReconciliationStageRunner(SectionStageRunner, Protocol):
    """Concrete production seam with a pure request identity and reconciler."""

    def operation_spec(
        self,
        adapter: SectionStageAdapter,
        scene_ids: tuple[str, ...],
        operation_id: str,
    ) -> Any: ...

    async def reconcile(
        self,
        adapter: SectionStageAdapter,
        scene_ids: tuple[str, ...],
        operation_id: str,
        operation_record: Any,
    ) -> Mapping[str, Any] | None: ...


class RuntimeFinalizer(Protocol):
    """Finish one fully checkpointed runtime without changing its identity."""

    async def __call__(
        self,
        tenant_id: str,
        video_id: str,
        runtime_job_id: str,
        envelope: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...


class CustomFilmReconciliationRequired(CustomFilmContractError):
    """An operation crossed the write-ahead boundary without a durable result."""


def _operation_id(
    tenant_id: str,
    job_id: str,
    adapter: SectionStageAdapter,
) -> str:
    from custom_film_contract import canonical_hash

    return "custom-film-op:" + canonical_hash(
        {
            "tenant_id": tenant_id,
            "video_id": adapter.video_id,
            "job_id": job_id,
            "runtime_hash": adapter.runtime_hash,
            "stage_key": adapter.stage_key,
        }
    )


async def _resolve_value(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _validated_progress(
    value: Any,
    *,
    runtime_hash: str,
    ordered_stage_keys: tuple[str, ...],
    operation_ids: Mapping[str, str],
) -> tuple[list[str], dict[str, str] | None]:
    progress = _object(value or {}, "runtime progress")
    if not progress:
        return [], None
    if set(progress) != {
        "runtime_hash",
        "completed_stage_keys",
        "last_stage_key",
        "in_flight",
    }:
        raise CustomFilmContractError("Custom Film runtime progress shape is invalid")
    if str(progress.get("runtime_hash") or "") != runtime_hash:
        raise CustomFilmContractError("Custom Film runtime progress is stale")
    raw_completed = progress.get("completed_stage_keys")
    if not isinstance(raw_completed, list) or any(
        not isinstance(value, str) for value in raw_completed
    ):
        raise CustomFilmContractError("Custom Film runtime progress is invalid")
    completed = list(raw_completed)
    if completed != list(ordered_stage_keys[: len(completed)]):
        raise CustomFilmContractError(
            "Custom Film runtime progress is not an exact ordered prefix"
        )
    expected_last = completed[-1] if completed else None
    if progress.get("last_stage_key") != expected_last:
        raise CustomFilmContractError(
            "Custom Film runtime last-stage checkpoint is inconsistent"
        )
    raw_in_flight = progress.get("in_flight")
    if raw_in_flight is None:
        return completed, None
    in_flight = _object(raw_in_flight, "runtime in-flight operation")
    if len(completed) >= len(ordered_stage_keys):
        raise CustomFilmContractError(
            "Custom Film runtime has an operation after its completed stage plan"
        )
    expected_stage_key = ordered_stage_keys[len(completed)]
    expected_operation_id = operation_ids[expected_stage_key]
    if (
        str(in_flight.get("stage_key") or "") != expected_stage_key
        or str(in_flight.get("operation_id") or "") != expected_operation_id
        or in_flight.get("state") != "started"
    ):
        raise CustomFilmContractError(
            "Custom Film runtime in-flight operation is invalid"
        )
    return completed, {
        "stage_key": expected_stage_key,
        "operation_id": expected_operation_id,
        "state": "started",
    }


def validate_complete_runtime_progress(
    *,
    tenant_id: str,
    runtime_job_id: str,
    envelope_value: Any,
    progress_value: Any,
) -> tuple[str, ...]:
    """Prove every exact stage is durable and no provider operation is in flight."""
    envelope = validate_runtime_envelope(envelope_value)
    adapters = compile_stage_adapters(envelope)
    ordered_stage_keys = tuple(adapter.stage_key for adapter in adapters)
    operation_ids = {
        adapter.stage_key: _operation_id(tenant_id, runtime_job_id, adapter)
        for adapter in adapters
    }
    completed, in_flight = _validated_progress(
        progress_value,
        runtime_hash=envelope["runtime_hash"],
        ordered_stage_keys=ordered_stage_keys,
        operation_ids=operation_ids,
    )
    if in_flight is not None or tuple(completed) != ordered_stage_keys:
        raise CustomFilmContractError(
            "Custom Film section runtime is not durably complete"
        )
    return ordered_stage_keys


def _validate_section_modes(section: Mapping[str, Any]) -> None:
    render_mode = str(section.get("render_mode") or "")
    dialogue_audio = str(section.get("dialogue_audio") or "")
    image_source = str(section.get("image_source") or "")
    animation = _object(section.get("animation"), "section animation")
    language = _object(section.get("language"), "section language")
    dubbing = _object(section.get("dubbing"), "section dubbing")
    segmentation = _object(section.get("segmentation"), "section segmentation")

    if render_mode not in {"coverage", "static_docu"}:
        raise CustomFilmContractError("Unsupported Custom Film render mode")
    if image_source != "generate":
        raise CustomFilmContractError("Unsupported Custom Film image source")
    if dialogue_audio not in {"voice_over", "grok_native"}:
        raise CustomFilmContractError("Unsupported Custom Film dialogue audio")

    animated = bool(animation.get("enabled"))
    language_mode = str(language.get("mode") or "")
    dubbing_enabled = bool(dubbing.get("enabled"))
    dubbing_mode = str(dubbing.get("mode") or "")
    segmentation_mode = str(segmentation.get("mode") or "")
    if render_mode == "static_docu" and animated:
        raise CustomFilmContractError(
            "Static Custom Film sections cannot schedule animation"
        )
    if language_mode == "bilingual":
        if (
            not animated
            or not dubbing_enabled
            or dubbing_mode != "speech_to_speech"
            or dialogue_audio != "voice_over"
            or segmentation_mode != "speaker_turn"
        ):
            raise CustomFilmContractError(
                "Unsupported bilingual Custom Film section combination"
            )
    elif language_mode == "simple_single_language":
        if (
            not animated
            or dubbing_enabled
            or dubbing_mode != "none"
            or dialogue_audio != "grok_native"
            or segmentation_mode != "speaker_turn"
        ):
            raise CustomFilmContractError(
                "Unsupported simple-language Custom Film section combination"
            )
    elif language_mode == "narrator":
        if dubbing_enabled or dubbing_mode != "none" or dialogue_audio != "voice_over":
            raise CustomFilmContractError(
                "Unsupported narrator Custom Film section combination"
            )
    else:
        raise CustomFilmContractError("Unsupported Custom Film language mode")


def compile_stage_adapters(envelope_value: Any) -> tuple[SectionStageAdapter, ...]:
    """Validate the entire durable schedule before any stage/provider work."""
    envelope = validate_runtime_envelope(envelope_value)
    if envelope.get("runtime_version") != RUNTIME_VERSION:
        raise CustomFilmContractError("Custom Film runtime version is unsupported")
    video_id = str(envelope.get("video_id") or "")
    plan_id = str(envelope.get("plan_id") or "")
    runtime_hash = str(envelope.get("runtime_hash") or "")
    sections_value = envelope.get("sections")
    stage_plan_value = envelope.get("stage_plan")
    if not video_id or not plan_id or not runtime_hash:
        raise CustomFilmContractError("Custom Film runtime identity is incomplete")
    if not isinstance(sections_value, list) or not isinstance(stage_plan_value, list):
        raise CustomFilmContractError("Custom Film runtime schedule is incomplete")

    sections_by_id: dict[str, dict[str, Any]] = {}
    expected_by_section: list[list[tuple[str, int, str, int]]] = []
    total_seconds = 0
    for expected_index, raw_section in enumerate(sections_value):
        section = _object(raw_section, "runtime section")
        section_id = str(section.get("section_id") or "")
        if not section_id or section_id in sections_by_id:
            raise CustomFilmContractError(
                "Custom Film runtime has missing or duplicate section IDs"
            )
        order_index = _exact_int(section.get("order_index"), "section order")
        if order_index != expected_index:
            raise CustomFilmContractError("Custom Film section order is stale")
        duration_seconds = _exact_int(
            section.get("duration_seconds"), "section runtime", minimum=1
        )
        if not str(section.get("script_profile") or ""):
            raise CustomFilmContractError("Custom Film section script profile is missing")
        if not str(section.get("visual_profile") or ""):
            raise CustomFilmContractError("Custom Film section visual profile is missing")
        for field in (
            "image_density",
            "language",
            "dubbing",
            "animation",
            "segmentation",
            "camera",
            "provenance",
            "estimated_media",
        ):
            _object(section.get(field), f"section {field.replace('_', ' ')}")
        laws = section.get("quality_laws")
        if (
            not isinstance(laws, list)
            or not laws
            or any(not str(law).strip() for law in laws)
        ):
            raise CustomFilmContractError("Custom Film section quality laws are missing")
        _validate_section_modes(section)
        animated = bool(_object(section["animation"], "section animation").get("enabled"))
        stages = ["script", "voice", "pictures"]
        if animated:
            stages.extend(("motion", "clips"))
        stages.append("quality")
        expected_by_section.append(
            [
                (section_id, order_index, stage, duration_seconds)
                for stage in stages
            ]
        )
        total_seconds += duration_seconds
        sections_by_id[section_id] = section

    if total_seconds != _exact_int(
        envelope.get("total_duration_seconds"), "film runtime", minimum=1
    ):
        raise CustomFilmContractError(
            "Custom Film exact section runtimes do not reconcile"
        )

    actual_plan: list[tuple[str, int, str, int]] = []
    for raw_work in stage_plan_value:
        work = _object(raw_work, "runtime work item")
        stage = str(work.get("stage") or "")
        if stage not in SUPPORTED_STAGES:
            raise CustomFilmContractError("Unsupported Custom Film runtime stage")
        section_id = str(work.get("section_id") or "")
        order_index = _exact_int(work.get("order_index"), "work section order")
        duration_seconds = _exact_int(
            work.get("duration_seconds"), "work runtime", minimum=1
        )
        section = sections_by_id.get(section_id)
        if (
            section is None
            or order_index != section["order_index"]
            or duration_seconds != section["duration_seconds"]
            or _object(work.get("values"), "work values") != section
        ):
            raise CustomFilmContractError(
                "Custom Film runtime work item does not match its section"
            )
        actual_plan.append((section_id, order_index, stage, duration_seconds))
    legacy_expected_plan = [
        item for section_plan in expected_by_section for item in section_plan
    ]
    scripts_first_expected_plan = [
        section_plan[0] for section_plan in expected_by_section
    ] + [
        item
        for section_plan in expected_by_section
        for item in section_plan[1:]
    ]
    if actual_plan not in (legacy_expected_plan, scripts_first_expected_plan):
        raise CustomFilmContractError("Custom Film runtime stage plan is stale")
    scripts_first_schedule = (
        envelope.get("execution_model")
        == SCRIPTS_FIRST_AV_EXECUTION_MODEL
    )
    if scripts_first_schedule and actual_plan != scripts_first_expected_plan:
        raise CustomFilmContractError(
            "Custom Film scripts-first execution model has a stale stage plan"
        )

    adapters: list[SectionStageAdapter] = []
    story_arc = tuple(
        _freeze(
            (
                {
                    "order_index": int(section["order_index"]),
                    "section_id": str(section.get("section_id") or ""),
                    "role": str(section.get("role") or ""),
                    "purpose": str(section.get("purpose") or ""),
                    "render_mode": str(section.get("render_mode") or ""),
                }
                if scripts_first_schedule
                else {
                    "order_index": int(section["order_index"]),
                    "role": str(section.get("role") or ""),
                    "purpose": str(section.get("purpose") or ""),
                }
            )
        )
        for section in sorted(
            sections_by_id.values(),
            key=lambda value: int(value["order_index"]),
        )
    )
    for section_id, order_index, stage, duration_seconds in actual_plan:
        section = sections_by_id[section_id]
        adapters.append(
            SectionStageAdapter(
                runtime_hash=runtime_hash,
                plan_id=plan_id,
                video_id=video_id,
                section_id=section_id,
                order_index=order_index,
                stage=stage,
                duration_seconds=duration_seconds,
                role=str(section.get("role") or ""),
                purpose=str(section.get("purpose") or ""),
                render_mode=str(section["render_mode"]),
                script_profile=str(section["script_profile"]),
                visual_profile=str(section["visual_profile"]),
                dialogue_audio=str(section["dialogue_audio"]),
                image_density=_freeze(section["image_density"]),
                language=_freeze(section["language"]),
                dubbing=_freeze(section["dubbing"]),
                animation=_freeze(section["animation"]),
                segmentation=_freeze(section["segmentation"]),
                camera=_freeze(section["camera"]),
                quality_laws=tuple(str(law) for law in section["quality_laws"]),
                image_source=str(section["image_source"]),
                provenance=_freeze(section["provenance"]),
                estimated_media=_freeze(section["estimated_media"]),
                story_arc=story_arc if stage == "script" else (),
            )
        )
    return tuple(adapters)


async def _load_assignments(
    conn: Any,
    tenant_id: str,
    adapter: SectionStageAdapter,
) -> tuple[str, ...]:
    rows = await conn.fetch(
        """SELECT script_id
           FROM custom_film_section_scenes
           WHERE tenant_id = $1 AND plan_id = $2 AND video_id = $3
             AND section_id = $4
           ORDER BY scene_order""",
        tenant_id,
        adapter.plan_id,
        adapter.video_id,
        adapter.section_id,
    )
    scene_ids = tuple(str(row["script_id"]) for row in rows)
    if not scene_ids:
        raise CustomFilmContractError(
            "Custom Film scene assignment is missing; no provider work was started"
        )
    return scene_ids


async def _replace_assignments(
    conn: Any,
    tenant_id: str,
    adapter: SectionStageAdapter,
    scene_ids: tuple[str, ...],
) -> None:
    if not scene_ids or any(not scene_id for scene_id in scene_ids):
        raise CustomFilmContractError(
            "Custom Film script stage returned no stable scene assignments"
        )
    if len(set(scene_ids)) != len(scene_ids):
        raise CustomFilmContractError(
            "Custom Film script stage returned duplicate scene assignments"
        )
    await conn.execute(
        """DELETE FROM custom_film_section_scenes
           WHERE tenant_id = $1 AND plan_id = $2 AND video_id = $3
             AND section_id = $4""",
        tenant_id,
        adapter.plan_id,
        adapter.video_id,
        adapter.section_id,
    )
    for scene_order, script_id in enumerate(scene_ids):
        await conn.execute(
            """INSERT INTO custom_film_section_scenes
                 (tenant_id, plan_id, video_id, section_id, script_id, scene_order)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            tenant_id,
            adapter.plan_id,
            adapter.video_id,
            adapter.section_id,
            script_id,
            scene_order,
        )


async def _unsupported_runner(
    adapter: SectionStageAdapter,
    _scene_ids: tuple[str, ...],
    _operation_id_value: str,
) -> Mapping[str, Any] | None:
    raise CustomFilmContractError(
        f"Custom Film {adapter.stage} production adapter is not installed; "
        "no provider work was started"
    )


async def consume_runtime_schedule(
    tenant_id: str,
    video_id: str,
    job_id: str,
    *,
    stage_runner: SectionStageRunner | None = None,
    finalizer: RuntimeFinalizer | None = None,
    attempt: int = 1,
) -> dict[str, Any]:
    """Consume one exact schedule under the main execution claim.

    Progress and scene assignments are committed after each successful stage,
    so a worker restart resumes at the first incomplete work item.  The runner
    is the provider boundary: the complete envelope and every assignment are
    validated before it is called.
    """
    runner = stage_runner or _unsupported_runner
    operation_aware = callable(getattr(runner, "operation_spec", None)) and callable(
        getattr(runner, "reconcile", None)
    )
    claimed = await generation_claims.acquire(
        tenant_id,
        video_id,
        "main",
        claimed_by=f"worker:{job_id}",
    )
    if not claimed:
        raise CustomFilmContractError(
            "Custom Film execution claim is already held; no provider work was started"
        )
    pool = None
    try:
        pool = await database.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT job_id, runtime_envelope, runtime_progress, status
                   FROM background_tasks
                   WHERE tenant_id = $1 AND video_id = $2
                     AND task_type = 'custom_film_runtime' AND job_id = $3
                   FOR UPDATE""",
                tenant_id,
                video_id,
                job_id,
            )
            if not row:
                raise CustomFilmContractError("Custom Film runtime job not found")
            envelope = validate_runtime_envelope(row["runtime_envelope"])
            if str(envelope.get("video_id") or "") != video_id:
                raise CustomFilmContractError("Custom Film runtime video mismatch")
            expected_job_id = f"custom-film-runtime:{envelope['runtime_hash']}"
            if job_id != expected_job_id or str(row["job_id"]) != expected_job_id:
                raise CustomFilmContractError("Custom Film runtime job identity is invalid")
            adapters = compile_stage_adapters(envelope)
            ordered_stage_keys = tuple(adapter.stage_key for adapter in adapters)
            operation_ids = {
                adapter.stage_key: _operation_id(tenant_id, job_id, adapter)
                for adapter in adapters
            }
            completed, in_flight = _validated_progress(
                row.get("runtime_progress"),
                runtime_hash=envelope["runtime_hash"],
                ordered_stage_keys=ordered_stage_keys,
                operation_ids=operation_ids,
            )
            if in_flight is not None and not operation_aware:
                raise CustomFilmReconciliationRequired(
                    "A Custom Film section operation may have reached its provider "
                    "before the restart. Reconciliation is required; it was not run again."
                )
            running_result = await conn.execute(
                """UPDATE background_tasks
                   SET status = 'running', message = 'Running approved section runtime',
                       error_message = NULL, completed_at = NULL, attempt = $4
                   WHERE tenant_id = $1 AND video_id = $2 AND job_id = $3""",
                tenant_id,
                video_id,
                job_id,
                attempt,
            )
            if not _updated_once(running_result):
                raise CustomFilmContractError(
                    "Custom Film runtime job could not be claimed for execution"
                )

        for adapter in adapters:
            if adapter.stage_key in completed:
                continue
            operation_id = operation_ids[adapter.stage_key]
            async with pool.acquire() as conn:
                scene_ids = (
                    ()
                    if adapter.stage == "script"
                    else await _load_assignments(conn, tenant_id, adapter)
                )
            operation_record = None
            if operation_aware:
                import custom_film_provider_operations as provider_operations

                spec = await _resolve_value(
                    runner.operation_spec(adapter, scene_ids, operation_id)
                )
                if not isinstance(
                    spec, provider_operations.ProviderOperationSpec
                ):
                    raise CustomFilmContractError(
                        "Custom Film provider operation specification is invalid"
                    )
                operation_record = await provider_operations.prepare_operation(
                    tenant_id=tenant_id,
                    video_id=video_id,
                    runtime_job_id=job_id,
                    runtime_hash=envelope["runtime_hash"],
                    stage_key=adapter.stage_key,
                    operation_id=operation_id,
                    spec=spec,
                )

            resuming_in_flight = (
                in_flight is not None
                and in_flight["stage_key"] == adapter.stage_key
                and in_flight["operation_id"] == operation_id
            )
            if not resuming_in_flight:
                async with pool.acquire() as conn:
                    write_ahead = {
                        "runtime_hash": envelope["runtime_hash"],
                        "completed_stage_keys": list(completed),
                        "last_stage_key": completed[-1] if completed else None,
                        "in_flight": {
                            "stage_key": adapter.stage_key,
                            "operation_id": operation_id,
                            "state": "started",
                        },
                    }
                    write_ahead_result = await conn.execute(
                        """UPDATE background_tasks
                           SET runtime_progress = $4::jsonb,
                               message = $5
                           WHERE tenant_id = $1 AND video_id = $2 AND job_id = $3""",
                        tenant_id,
                        video_id,
                        job_id,
                        json.dumps(
                            write_ahead,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        f"Started section stage {adapter.stage_key}",
                    )
                    if not _updated_once(write_ahead_result):
                        raise CustomFilmContractError(
                            "Custom Film stage operation could not be reserved"
                        )

            if resuming_in_flight:
                import custom_film_provider_operations as provider_operations

                try:
                    action = provider_operations.reconciliation_action(
                        operation_record
                    )
                except CustomFilmContractError as exc:
                    await provider_operations.mark_reconciliation_required(
                        operation_id,
                        str(exc),
                    )
                    raise
                if action == "return_completed":
                    result = operation_record.result
                elif action == "query_provider":
                    result = await runner.reconcile(
                        adapter,
                        scene_ids,
                        operation_id,
                        operation_record,
                    )
                elif action == "retry_same_operation":
                    result = await runner(adapter, scene_ids, operation_id)
                else:  # pragma: no cover - reconciliation_action is exhaustive
                    raise CustomFilmReconciliationRequired(
                        "Custom Film provider reconciliation did not resolve"
                    )
            else:
                result = await runner(adapter, scene_ids, operation_id)
            if operation_aware and not isinstance(result, Mapping):
                raise CustomFilmContractError(
                    "Custom Film provider operation did not return a durable result"
                )
            result_object = _object(result or {}, "stage result")
            if adapter.stage == "script":
                raw_scene_ids = result_object.get("scene_ids")
                if not isinstance(raw_scene_ids, list):
                    raise CustomFilmContractError(
                        "Custom Film script stage did not return stable scene IDs"
                    )
                scene_ids = tuple(str(value or "") for value in raw_scene_ids)
            async with pool.acquire() as conn:
                async with conn.transaction():
                    if adapter.stage == "script":
                        await _replace_assignments(
                            conn, tenant_id, adapter, scene_ids
                        )
                    if operation_aware:
                        import custom_film_provider_operations as provider_operations

                        await provider_operations.mark_completed(
                            operation_id,
                            result_object,
                            conn=conn,
                        )
                    completed.append(adapter.stage_key)
                    durable_progress = {
                        "runtime_hash": envelope["runtime_hash"],
                        "completed_stage_keys": list(completed),
                        "last_stage_key": adapter.stage_key,
                        "in_flight": None,
                    }
                    progress_result = await conn.execute(
                        """UPDATE background_tasks
                           SET runtime_progress = $4::jsonb,
                               message = $5
                           WHERE tenant_id = $1 AND video_id = $2 AND job_id = $3""",
                        tenant_id,
                        video_id,
                        job_id,
                        json.dumps(
                            durable_progress,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        f"Completed section stage {adapter.stage_key}",
                    )
                    if not _updated_once(progress_result):
                        raise CustomFilmContractError(
                            "Custom Film stage result could not be checkpointed"
                        )
            in_flight = None

        finalization_result: dict[str, Any] | None = None
        if finalizer is not None:
            validate_complete_runtime_progress(
                tenant_id=tenant_id,
                runtime_job_id=job_id,
                envelope_value=envelope,
                progress_value={
                    "runtime_hash": envelope["runtime_hash"],
                    "completed_stage_keys": list(completed),
                    "last_stage_key": completed[-1] if completed else None,
                    "in_flight": None,
                },
            )
            raw_finalization = await finalizer(
                tenant_id,
                video_id,
                job_id,
                copy.deepcopy(envelope),
            )
            if not isinstance(raw_finalization, Mapping):
                raise CustomFilmContractError(
                    "Custom Film finalizer returned no durable artifact result"
                )
            finalization_result = copy.deepcopy(dict(raw_finalization))

        async with pool.acquire() as conn:
            completed_result = await conn.execute(
                """UPDATE background_tasks
                   SET status = 'completed',
                       message = $4,
                       completed_at = now()
                   WHERE tenant_id = $1 AND video_id = $2 AND job_id = $3""",
                tenant_id,
                video_id,
                job_id,
                (
                    "Approved Custom Film rendered"
                    if finalization_result is not None
                    else "Approved section runtime complete"
                ),
            )
            if not _updated_once(completed_result):
                raise CustomFilmContractError(
                    "Custom Film runtime completion could not be checkpointed"
                )
        response = {
            "status": "completed",
            "job_id": job_id,
            "runtime_hash": envelope["runtime_hash"],
            "completed_stage_keys": list(completed),
        }
        if finalization_result is not None:
            response["finalization"] = finalization_result
        return response
    except Exception as exc:
        persisted_error = (
            str(exc)
            if isinstance(exc, CustomFilmReconciliationRequired)
            else humanize_error(
                exc,
                context="Custom Film section runtime stopped",
            )
        )
        if pool is not None:
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """UPDATE background_tasks
                           SET status = 'failed', error_message = $4,
                               message = 'Approved section runtime stopped',
                               completed_at = now()
                           WHERE tenant_id = $1 AND video_id = $2 AND job_id = $3""",
                        tenant_id,
                        video_id,
                        job_id,
                        persisted_error,
                    )
            except Exception:
                pass
        raise
    finally:
        await generation_claims.release(tenant_id, video_id, "main")
