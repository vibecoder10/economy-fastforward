"""Restart-safe Custom Film section consumer and shared stage adapters.

This module is the only runtime boundary allowed to interpret a persisted
Custom Film envelope.  Stage implementations receive resolved section values;
they never inspect ``custom_film`` mode or public profile IDs themselves.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Protocol

import database
import generation_claims
from custom_film_contract import CustomFilmContractError
from custom_film_runtime import RUNTIME_VERSION, validate_runtime_envelope


SUPPORTED_STAGES = frozenset(
    {"script", "voice", "pictures", "motion", "clips", "quality"}
)


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

    @property
    def stage_key(self) -> str:
        return f"{self.order_index}:{self.section_id}:{self.stage}"

    def provider_values(self) -> dict[str, Any]:
        """Return a detached payload safe to hand to a stage/provider seam."""
        return {
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


class SectionStageRunner(Protocol):
    async def __call__(
        self,
        adapter: SectionStageAdapter,
        scene_ids: tuple[str, ...],
    ) -> Mapping[str, Any] | None: ...


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
    expected_plan: list[tuple[str, int, str, int]] = []
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
        expected_plan.extend(
            (section_id, order_index, stage, duration_seconds) for stage in stages
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
    if actual_plan != expected_plan:
        raise CustomFilmContractError("Custom Film runtime stage plan is stale")

    adapters: list[SectionStageAdapter] = []
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
) -> dict[str, Any]:
    """Consume one exact schedule under the main execution claim.

    Progress and scene assignments are committed after each successful stage,
    so a worker restart resumes at the first incomplete work item.  The runner
    is the provider boundary: the complete envelope and every assignment are
    validated before it is called.
    """
    runner = stage_runner or _unsupported_runner
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
            progress = _object(
                row.get("runtime_progress") or {}, "runtime progress"
            )
            if progress and str(progress.get("runtime_hash") or "") != envelope["runtime_hash"]:
                raise CustomFilmContractError("Custom Film runtime progress is stale")
            completed = {
                str(value)
                for value in progress.get("completed_stage_keys", [])
                if str(value)
            }
            valid_keys = {adapter.stage_key for adapter in adapters}
            if not completed.issubset(valid_keys):
                raise CustomFilmContractError("Custom Film runtime progress is invalid")
            await conn.execute(
                """UPDATE background_tasks
                   SET status = 'running', message = 'Running approved section runtime',
                       error_message = NULL, completed_at = NULL
                   WHERE tenant_id = $1 AND video_id = $2 AND job_id = $3""",
                tenant_id,
                video_id,
                job_id,
            )

        for adapter in adapters:
            if adapter.stage_key in completed:
                continue
            async with pool.acquire() as conn:
                scene_ids = (
                    ()
                    if adapter.stage == "script"
                    else await _load_assignments(conn, tenant_id, adapter)
                )
            result = await runner(adapter, scene_ids)
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
                    completed.add(adapter.stage_key)
                    durable_progress = {
                        "runtime_hash": envelope["runtime_hash"],
                        "completed_stage_keys": sorted(completed),
                        "last_stage_key": adapter.stage_key,
                    }
                    await conn.execute(
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

        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE background_tasks
                   SET status = 'completed',
                       message = 'Approved section runtime complete',
                       completed_at = now()
                   WHERE tenant_id = $1 AND video_id = $2 AND job_id = $3""",
                tenant_id,
                video_id,
                job_id,
            )
        return {
            "status": "completed",
            "job_id": job_id,
            "runtime_hash": envelope["runtime_hash"],
            "completed_stage_keys": sorted(completed),
        }
    except Exception as exc:
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
                        str(exc),
                    )
            except Exception:
                pass
        raise
    finally:
        await generation_claims.release(tenant_id, video_id, "main")
