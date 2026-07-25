"""Concrete section production runner for Custom Film sections.

The runtime consumer owns Custom Film interpretation.  This module receives
only resolved :class:`SectionStageAdapter` values and converts them into the
existing shared script, narration, imagery, motion, clip, and quality seams.
Provider-facing code therefore never branches on a ``custom_film`` mode.

The seam object is injectable so tests can prove the exact request without
calling a provider.  The default seam uses tenant-owned clients initialized by
``PipelineExecutor`` and the same lower-level production functions as the
legacy video-wide wrappers.
"""

from __future__ import annotations

import copy
import json
import re
import uuid
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any, Awaitable, Callable, Mapping, Protocol

from custom_film_contract import (
    CustomFilmContractError,
    canonical_caption_card,
    canonical_hash,
)
from custom_film_provider_operations import (
    RECONCILIATION_IDEMPOTENCY,
    RECONCILIATION_NONE,
    RECONCILIATION_QUERY,
    ProviderOperationRecord,
    ProviderOperationSpec,
    mark_submitted,
)
import custom_film_provider_operations as provider_operations
from custom_film_section_runtime import SectionStageAdapter


SUPPORTED_PRODUCTION_STAGES = frozenset(
    {"script", "voice", "pictures", "motion", "clips", "quality"}
)
_LOCAL_PROVIDER = "storyengine-local"
_TEXT_PROVIDER = "tenant-text-generation"
_VOICE_PROVIDER = "tenant-voice-generation"
_IMAGE_PROVIDER = "tenant-image-generation"
_MOTION_PROVIDER = "tenant-motion-planning"
_CLIP_PROVIDER = "tenant-clip-generation"


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return copy.deepcopy(value)


def _exact_scene_ids(values: tuple[str, ...], *, required: bool) -> tuple[str, ...]:
    if (
        (required and not values)
        or any(not isinstance(value, str) or not value.strip() for value in values)
        or len(set(values)) != len(values)
    ):
        raise CustomFilmContractError(
            "Custom Film section scene assignments are invalid; "
            "no provider work was started"
        )
    return tuple(value.strip() for value in values)


def _allocate_integer(total: int, count: int) -> tuple[int, ...]:
    if type(total) is not int or total < 0 or type(count) is not int or count < 1:
        raise CustomFilmContractError("Custom Film media allocation is invalid")
    base, remainder = divmod(total, count)
    values = tuple(base + (1 if index < remainder else 0) for index in range(count))
    if any(value < 1 for value in values) or sum(values) != total:
        raise CustomFilmContractError(
            "Custom Film approved media count cannot cover every assigned scene"
        )
    return values


def _allocate_seconds(exact_seconds: int, count: int) -> tuple[Decimal, ...]:
    total_ms = exact_seconds * 1000
    allocations = _allocate_integer(total_ms, count)
    values = tuple(Decimal(value) / Decimal(1000) for value in allocations)
    if sum(values, Decimal(0)) != Decimal(exact_seconds):
        raise CustomFilmContractError("Custom Film clip timing does not reconcile")
    return values


def _duration_ms(value: Any, *, label: str) -> int:
    try:
        milliseconds = Decimal(str(value)) * Decimal(1000)
    except Exception as exc:
        raise CustomFilmContractError(
            f"Custom Film {label} duration is invalid"
        ) from exc
    if milliseconds <= 0 or milliseconds != milliseconds.to_integral_value():
        raise CustomFilmContractError(
            f"Custom Film {label} duration must use exact milliseconds"
        )
    return int(milliseconds)


def _timing_transform(actual_ms: int, target_ms: int) -> dict[str, Any]:
    if actual_ms == target_ms:
        return {
            "mode": "none",
            "source_duration_ms": actual_ms,
            "output_duration_ms": target_ms,
        }
    if actual_ms > target_ms:
        return {
            "mode": "trim",
            "source_duration_ms": actual_ms,
            "trim_start_ms": 0,
            "trim_end_ms": target_ms,
            "output_duration_ms": target_ms,
        }
    repeat_count = (target_ms + actual_ms - 1) // actual_ms
    final_repeat_ms = target_ms - ((repeat_count - 1) * actual_ms)
    return {
        "mode": "repeat_then_trim",
        "source_duration_ms": actual_ms,
        "repeat_count": repeat_count,
        "final_repeat_duration_ms": final_repeat_ms,
        "output_duration_ms": target_ms,
    }


def _exact_motion_result(
    result: Any,
    asset_ids: tuple[str, ...],
) -> dict[str, str]:
    artifacts = result.get("artifacts") if isinstance(result, Mapping) else None
    if (
        not isinstance(result, Mapping)
        or result.get("written") != len(asset_ids)
        or tuple(result.get("asset_ids") or ()) != asset_ids
        or not isinstance(artifacts, list)
        or len(artifacts) != len(asset_ids)
    ):
        raise CustomFilmContractError(
            "Custom Film section motion prompts did not complete"
        )
    values = {
        str(row.get("asset_id") or ""): str(row.get("video_prompt") or "")
        for row in artifacts
        if isinstance(row, Mapping)
    }
    if set(values) != set(asset_ids) or any(not values[asset_id] for asset_id in asset_ids):
        raise CustomFilmContractError(
            "Custom Film motion result did not match exact requested assets"
        )
    return values


def _exact_clip_result(
    result: Any,
    asset_ids: tuple[str, ...],
) -> dict[str, Mapping[str, Any]]:
    artifacts = result.get("generated_artifacts") if isinstance(result, Mapping) else None
    generated_ids = (
        list(result.get("generated_asset_ids") or ())
        if isinstance(result, Mapping)
        else []
    )
    if (
        not isinstance(result, Mapping)
        or result.get("status") != "completed"
        or tuple(result.get("requested_asset_ids") or ()) != asset_ids
        or len(generated_ids) != len(asset_ids)
        or len(set(generated_ids)) != len(generated_ids)
        or set(generated_ids) != set(asset_ids)
        or result.get("clips_generated") != len(asset_ids)
        or result.get("clips_failed") != 0
        or result.get("clips_blocked") != 0
        or result.get("clips_in_progress_elsewhere") != 0
        or not isinstance(artifacts, list)
        or len(artifacts) != len(asset_ids)
    ):
        raise CustomFilmContractError("Custom Film section clips did not complete")
    values = {
        str(row.get("asset_id") or ""): row
        for row in artifacts
        if isinstance(row, Mapping)
    }
    artifact_ids = [
        str(row.get("asset_id") or "")
        for row in artifacts
        if isinstance(row, Mapping)
    ]
    if (
        len(artifact_ids) != len(asset_ids)
        or len(set(artifact_ids)) != len(artifact_ids)
        or set(values) != set(asset_ids)
    ):
        raise CustomFilmContractError(
            "Custom Film clip result did not match exact requested assets"
        )
    for asset_id in asset_ids:
        raw_duration = values[asset_id].get("duration_seconds")
        _duration_ms(raw_duration, label="provider clip")
    return values


def _assert_current_provider_artifacts(
    stage: str,
    rows: list[dict[str, Any]],
    asset_ids: tuple[str, ...],
    returned: Mapping[str, Any],
) -> None:
    if tuple(str(row.get("id") or "") for row in rows) != asset_ids:
        raise CustomFilmContractError(
            f"Custom Film {stage} current asset IDs changed"
        )
    if stage == "motion":
        changed = any(
            str(row.get("video_prompt") or "") != str(returned.get(str(row["id"])) or "")
            for row in rows
        )
    else:
        changed = any(
            str(row.get("video_clip_url") or "")
            != str(returned.get(str(row["id"]), {}).get("video_clip_url") or "")
            or str(row.get("model_used") or "")
            != str(returned.get(str(row["id"]), {}).get("provider_model") or "")
            or row.get("video_duration") is None
            or _duration_ms(
                row.get("video_duration"),
                label="current provider clip",
            )
            != _duration_ms(
                returned.get(str(row["id"]), {}).get("duration_seconds"),
                label="returned provider clip",
            )
            for row in rows
        )
    if changed:
        raise CustomFilmContractError(
            f"Custom Film {stage} artifacts changed concurrently"
        )


@dataclass(frozen=True)
class SectionProductionRequest:
    operation_id: str
    runtime_hash: str
    plan_id: str
    video_id: str
    section_id: str
    order_index: int
    stage: str
    exact_seconds: int
    role: str
    purpose: str
    scene_ids: tuple[str, ...]
    asset_ids: tuple[str, ...]
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
    estimated_media: Mapping[str, Any]
    expected_still_images: int
    expected_animation_clips: int
    story_arc: tuple[Mapping[str, Any], ...] = ()

    def payload(self) -> dict[str, Any]:
        values = {
            "operation_id": self.operation_id,
            "runtime_hash": self.runtime_hash,
            "plan_id": self.plan_id,
            "video_id": self.video_id,
            "section_id": self.section_id,
            "order_index": self.order_index,
            "stage": self.stage,
            "exact_seconds": self.exact_seconds,
            "role": self.role,
            "purpose": self.purpose,
            "scene_ids": list(self.scene_ids),
            "asset_ids": list(self.asset_ids),
            "render_mode": self.render_mode,
            "script_profile": self.script_profile,
            "visual_profile": self.visual_profile,
            "dialogue_audio": self.dialogue_audio,
            "image_density": _plain(self.image_density),
            "language": _plain(self.language),
            "dubbing": _plain(self.dubbing),
            "animation": _plain(self.animation),
            "segmentation": _plain(self.segmentation),
            "camera": _plain(self.camera),
            "quality_laws": list(self.quality_laws),
            "image_source": self.image_source,
            "estimated_media": _plain(self.estimated_media),
            "expected_still_images": self.expected_still_images,
            "expected_animation_clips": self.expected_animation_clips,
        }
        if self.stage == "script":
            values["story_arc"] = _plain(self.story_arc)
        return values


@dataclass(frozen=True)
class SectionProductionResult:
    result: Mapping[str, Any]
    provider_operation_id: str | None = None


SubmittedCallback = Callable[[str], Awaitable[None]]


class SectionProductionSeams(Protocol):
    def operation_metadata(
        self, request: SectionProductionRequest
    ) -> tuple[str, str]: ...

    async def submit(
        self,
        request: SectionProductionRequest,
        *,
        on_submitted: SubmittedCallback,
    ) -> SectionProductionResult | Mapping[str, Any]: ...

    async def query(
        self,
        request: SectionProductionRequest,
        provider_operation_id: str,
    ) -> SectionProductionResult | Mapping[str, Any]: ...


def _request(
    adapter: SectionStageAdapter,
    scene_ids: tuple[str, ...],
    operation_id: str,
    *,
    asset_ids: tuple[str, ...] = (),
) -> SectionProductionRequest:
    if adapter.stage not in SUPPORTED_PRODUCTION_STAGES:
        raise CustomFilmContractError(
            f"Custom Film {adapter.stage} production runner belongs to the "
            "next runtime chunk; no provider work was started"
        )
    if type(adapter.duration_seconds) is not int or adapter.duration_seconds < 1:
        raise CustomFilmContractError(
            "Custom Film section runtime must be an exact positive integer"
        )
    if not adapter.role.strip() or not adapter.purpose.strip():
        raise CustomFilmContractError(
            "Custom Film section purpose is missing; no provider work was started"
        )
    if (
        not adapter.script_profile.strip()
        or not adapter.visual_profile.strip()
        or not adapter.quality_laws
        or adapter.image_source != "generate"
    ):
        raise CustomFilmContractError(
            "Custom Film section production contract is missing or unsupported; "
            "no provider work was started"
        )
    animated = bool(adapter.animation.get("enabled"))
    animation_mode = str(adapter.animation.get("mode") or "")
    density_mode = str(adapter.image_density.get("mode") or "")
    camera_mode = str(adapter.camera.get("mode") or "")
    visual_contract_valid = (
        (
            adapter.render_mode == "static_docu"
            and not animated
            and animation_mode == "ken_burns"
            and density_mode == "per_item"
            and camera_mode == "three_complementary_views"
        )
        or (
            adapter.render_mode == "coverage"
            and animated
            and animation_mode == "grok_native"
            and density_mode in {"dialogue_shape", "visual_cue"}
            and camera_mode in {"dialogue_coverage", "investigative_coverage"}
        )
    )
    if not visual_contract_valid:
        raise CustomFilmContractError(
            "Unsupported Custom Film imagery, animation, density, or camera "
            "combination; no provider work was started"
        )
    if adapter.stage in {"motion", "clips"} and not animated:
        raise CustomFilmContractError(
            "Static Custom Film sections cannot schedule motion or clips"
        )
    language_mode = str(adapter.language.get("mode") or "")
    dubbing_enabled = bool(adapter.dubbing.get("enabled"))
    dubbing_mode = str(adapter.dubbing.get("mode") or "")
    segmentation_mode = str(adapter.segmentation.get("mode") or "")
    if language_mode == "bilingual":
        behavior_valid = (
            adapter.dialogue_audio == "voice_over"
            and dubbing_enabled
            and dubbing_mode == "speech_to_speech"
            and segmentation_mode == "speaker_turn"
        )
    elif language_mode == "simple_single_language":
        behavior_valid = (
            adapter.dialogue_audio == "grok_native"
            and not dubbing_enabled
            and dubbing_mode == "none"
            and segmentation_mode == "speaker_turn"
        )
    elif language_mode == "narrator":
        behavior_valid = (
            adapter.dialogue_audio == "voice_over"
            and not dubbing_enabled
            and dubbing_mode == "none"
        )
    else:
        behavior_valid = False
    if not behavior_valid:
        raise CustomFilmContractError(
            "Unsupported Custom Film language, dubbing, dialogue-audio, or "
            "segmentation combination; no provider work was started"
        )
    scenes = _exact_scene_ids(
        scene_ids,
        required=adapter.stage != "script",
    )
    if adapter.stage == "script" and scenes:
        raise CustomFilmContractError(
            "Custom Film script stage cannot reuse stale scene assignments"
        )
    assets = _exact_scene_ids(asset_ids, required=False)
    still_images = adapter.estimated_media.get("still_images")
    animation_clips = adapter.estimated_media.get("animation_clips")
    if (
        type(still_images) is not int
        or still_images < 1
        or type(animation_clips) is not int
        or animation_clips < 0
        or (animated and animation_clips != still_images)
        or (not animated and animation_clips != 0)
    ):
        raise CustomFilmContractError(
            "Custom Film approved media counts are invalid"
        )
    return SectionProductionRequest(
        operation_id=operation_id,
        runtime_hash=adapter.runtime_hash,
        plan_id=adapter.plan_id,
        video_id=adapter.video_id,
        section_id=adapter.section_id,
        order_index=adapter.order_index,
        stage=adapter.stage,
        exact_seconds=adapter.duration_seconds,
        role=adapter.role,
        purpose=adapter.purpose,
        scene_ids=scenes,
        asset_ids=assets,
        render_mode=adapter.render_mode,
        script_profile=adapter.script_profile,
        visual_profile=adapter.visual_profile,
        dialogue_audio=adapter.dialogue_audio,
        image_density=adapter.image_density,
        language=adapter.language,
        dubbing=adapter.dubbing,
        animation=adapter.animation,
        segmentation=adapter.segmentation,
        camera=adapter.camera,
        quality_laws=adapter.quality_laws,
        image_source=adapter.image_source,
        estimated_media=adapter.estimated_media,
        expected_still_images=still_images,
        expected_animation_clips=animation_clips,
        story_arc=adapter.story_arc if adapter.stage == "script" else (),
    )


def _coerce_result(
    value: SectionProductionResult | Mapping[str, Any],
) -> SectionProductionResult:
    if isinstance(value, SectionProductionResult):
        result = value
    elif isinstance(value, Mapping):
        result = SectionProductionResult(result=value)
    else:
        raise CustomFilmContractError(
            "Custom Film production seam returned no durable result"
        )
    if not isinstance(result.result, Mapping):
        raise CustomFilmContractError(
            "Custom Film production seam returned an invalid result"
        )
    provider_operation_id = (
        str(result.provider_operation_id or "").strip() or None
    )
    return SectionProductionResult(
        result=copy.deepcopy(dict(result.result)),
        provider_operation_id=provider_operation_id,
    )


class CustomFilmProductionRunner:
    """Operation-aware runner installed in the real Custom Film worker."""

    def __init__(
        self,
        tenant_id: str,
        *,
        seams: SectionProductionSeams | None = None,
        journal: Any = None,
    ):
        if not str(tenant_id or "").strip():
            raise CustomFilmContractError("Custom Film tenant identity is missing")
        self.tenant_id = str(tenant_id)
        self.seams = seams or SharedSectionProductionSeams(self.tenant_id)
        self.journal = journal or provider_operations

    def operation_spec(
        self,
        adapter: SectionStageAdapter,
        scene_ids: tuple[str, ...],
        operation_id: str,
    ) -> ProviderOperationSpec:
        request = _request(adapter, scene_ids, operation_id)
        if request.stage in {"voice", "pictures", "motion", "clips"}:
            return ProviderOperationSpec(
                provider=f"storyengine-section-{request.stage}",
                request_hash=canonical_hash(request.payload()),
                reconciliation_mode=RECONCILIATION_IDEMPOTENCY,
            )
        provider, reconciliation_mode = self.seams.operation_metadata(request)
        return ProviderOperationSpec(
            provider=str(provider or "").strip(),
            request_hash=canonical_hash(request.payload()),
            reconciliation_mode=reconciliation_mode,
        )

    async def __call__(
        self,
        adapter: SectionStageAdapter,
        scene_ids: tuple[str, ...],
        operation_id: str,
    ) -> Mapping[str, Any]:
        request = _request(adapter, scene_ids, operation_id)
        if request.stage == "voice":
            return await self._run_voice_children(adapter, request)
        if request.stage in {"pictures", "motion", "clips"}:
            return await self._run_media_children(adapter, request)
        submitted_ids: list[str] = []

        async def _submitted(provider_operation_id: str) -> None:
            value = str(provider_operation_id or "").strip()
            if not value:
                raise CustomFilmContractError(
                    "Custom Film provider task identity is missing"
                )
            await mark_submitted(operation_id, value)
            submitted_ids.append(value)

        result = _coerce_result(
            await self.seams.submit(request, on_submitted=_submitted)
        )
        if result.provider_operation_id:
            if (
                submitted_ids
                and submitted_ids[-1] != result.provider_operation_id
            ):
                raise CustomFilmContractError(
                    "Custom Film provider task identity changed"
                )
            if not submitted_ids:
                await _submitted(result.provider_operation_id)
        return copy.deepcopy(dict(result.result))

    async def _load_optional_child(self, operation_id: str):
        try:
            return await self.journal.load_operation(operation_id)
        except CustomFilmContractError as exc:
            if "state is missing" in str(exc):
                return None
            raise

    async def _call_child_seam(
        self,
        request: SectionProductionRequest,
        *,
        query_task_id: str | None = None,
    ) -> SectionProductionResult:
        submitted_ids: list[str] = []

        async def _submitted(provider_operation_id: str) -> None:
            value = str(provider_operation_id or "").strip()
            if not value:
                raise CustomFilmContractError(
                    "Custom Film provider task identity is missing"
                )
            await self.journal.mark_submitted(request.operation_id, value)
            submitted_ids.append(value)

        if query_task_id:
            result = _coerce_result(
                await self.seams.query(request, query_task_id)
            )
        else:
            result = _coerce_result(
                await self.seams.submit(request, on_submitted=_submitted)
            )
        if result.provider_operation_id:
            if (
                submitted_ids
                and submitted_ids[-1] != result.provider_operation_id
            ):
                raise CustomFilmContractError(
                    "Custom Film child provider task identity changed"
                )
            if not submitted_ids and not query_task_id:
                await _submitted(result.provider_operation_id)
        return result

    async def _run_voice_children(
        self,
        adapter: SectionStageAdapter,
        parent_request: SectionProductionRequest,
    ) -> Mapping[str, Any]:
        """Run one durable provider operation per assigned scene.

        Children are strictly sequential.  Each request identity/result is
        durable before the next child can be created, so a parent retry only
        returns a completed child, queries its recorded provider task, retries
        a declared-idempotent local child, or fails closed.
        """
        parent = await self.journal.load_operation(parent_request.operation_id)
        if (
            parent.runtime_hash != parent_request.runtime_hash
            or parent.video_id != parent_request.video_id
            or parent.stage_key != adapter.stage_key
        ):
            raise CustomFilmContractError(
                "Custom Film parent voice operation identity changed"
            )
        child_results: list[dict[str, Any]] = []
        for scene_index, scene_id in enumerate(parent_request.scene_ids):
            child_operation_id = "custom-film-op:" + canonical_hash(
                {
                    "parent_operation_id": parent_request.operation_id,
                    "scene_id": scene_id,
                }
            )
            child_request = replace(
                parent_request,
                operation_id=child_operation_id,
                scene_ids=(scene_id,),
            )
            provider, mode = self.seams.operation_metadata(child_request)
            spec = ProviderOperationSpec(
                provider=str(provider or "").strip(),
                request_hash=canonical_hash(child_request.payload()),
                reconciliation_mode=mode,
            )
            existing = await self._load_optional_child(child_operation_id)
            child_stage_key = (
                f"{adapter.stage_key}:scene:{scene_index}:"
                f"{canonical_hash({'scene_id': scene_id})[:12]}"
            )
            record = await self.journal.prepare_operation(
                tenant_id=self.tenant_id,
                video_id=parent_request.video_id,
                runtime_job_id=parent.runtime_job_id,
                runtime_hash=parent_request.runtime_hash,
                stage_key=child_stage_key,
                operation_id=child_operation_id,
                spec=spec,
            )
            if record.state == "completed":
                if record.result is None:
                    raise CustomFilmContractError(
                        "Custom Film completed child voice operation has no result"
                    )
                child_results.append(
                    {
                        "scene_id": scene_id,
                        "operation_id": child_operation_id,
                        "result": copy.deepcopy(dict(record.result)),
                    }
                )
                continue
            result: SectionProductionResult | None = None
            if existing is not None:
                checkpoint = getattr(self.seams, "checkpoint", None)
                if (
                    record.state in {"prepared", "submitted"}
                    and callable(checkpoint)
                ):
                    recovered = await checkpoint(child_request)
                    if recovered is not None:
                        recovered_result = copy.deepcopy(
                            dict(_coerce_result(recovered).result)
                        )
                        artifact_url = str(
                            recovered_result.get("artifact_url") or ""
                        ).strip()
                        recovered_result.setdefault(
                            "scene_ids", list(child_request.scene_ids)
                        )
                        recovered_result.setdefault(
                            "voiced_scene_ids", list(child_request.scene_ids)
                        )
                        recovered_result.setdefault(
                            "voice_behavior",
                            (
                                "narration_plus_clip_speech_to_speech"
                                if bool(child_request.dubbing.get("enabled"))
                                else "narration"
                            ),
                        )
                        recovered_result.setdefault(
                            "language", _plain(child_request.language)
                        )
                        recovered_result.setdefault(
                            "dubbing", _plain(child_request.dubbing)
                        )
                        recovered_result.setdefault(
                            "dialogue_audio", child_request.dialogue_audio
                        )
                        recovered_result.setdefault(
                            "exact_seconds", child_request.exact_seconds
                        )
                        recovered_result.setdefault("total_chars", 0)
                        if artifact_url:
                            recovered_result.setdefault(
                                "artifacts",
                                [
                                    {
                                        "scene_id": scene_id,
                                        "artifact_id": recovered_result.get(
                                            "artifact_id"
                                        ),
                                        "artifact_url": artifact_url,
                                        "reused": True,
                                    }
                                ],
                            )
                        else:
                            recovered_result.setdefault("artifacts", [])
                        result = SectionProductionResult(recovered_result)
                if result is None:
                    try:
                        action = self.journal.reconciliation_action(record)
                    except CustomFilmContractError as exc:
                        await self.journal.mark_reconciliation_required(
                            child_operation_id,
                            str(exc),
                        )
                        raise
                    if action == "query_provider":
                        result = await self._call_child_seam(
                            child_request,
                            query_task_id=str(record.provider_operation_id),
                        )
                    elif action == "retry_same_operation":
                        result = await self._call_child_seam(child_request)
            else:
                result = await self._call_child_seam(child_request)
            if result is None:
                raise CustomFilmContractError(
                    "Custom Film child voice reconciliation did not resolve"
                )
            result_object = copy.deepcopy(dict(result.result))
            await self.journal.mark_completed(
                child_operation_id,
                result_object,
            )
            child_results.append(
                {
                    "scene_id": scene_id,
                    "operation_id": child_operation_id,
                    "result": result_object,
                }
            )
        return {
            "scene_ids": list(parent_request.scene_ids),
            "child_operations": child_results,
            "exact_seconds": parent_request.exact_seconds,
            "language": _plain(parent_request.language),
            "dubbing": _plain(parent_request.dubbing),
            "dialogue_audio": parent_request.dialogue_audio,
        }

    async def _run_media_children(
        self,
        adapter: SectionStageAdapter,
        parent_request: SectionProductionRequest,
    ) -> Mapping[str, Any]:
        """Run one durable operation per assigned scene for media stages.

        The shared seams are scene-scoped and must report a provider task
        before polling whenever the provider exposes one.  A restart returns
        a completed child, queries that exact task, retries only a seam that
        explicitly declares idempotency, or stops closed.
        """
        parent = await self.journal.load_operation(parent_request.operation_id)
        if (
            parent.runtime_hash != parent_request.runtime_hash
            or parent.video_id != parent_request.video_id
            or parent.stage_key != adapter.stage_key
        ):
            raise CustomFilmContractError(
                "Custom Film parent media operation identity changed"
            )
        child_results: list[dict[str, Any]] = []
        still_allocations = _allocate_integer(
            parent_request.expected_still_images,
            len(parent_request.scene_ids),
        )
        clip_allocations = (
            _allocate_integer(
                parent_request.expected_animation_clips,
                len(parent_request.scene_ids),
            )
            if parent_request.expected_animation_clips
            else (0,) * len(parent_request.scene_ids)
        )
        for scene_index, scene_id in enumerate(parent_request.scene_ids):
            child_operation_id = "custom-film-op:" + canonical_hash(
                {
                    "parent_operation_id": parent_request.operation_id,
                    "stage": parent_request.stage,
                    "scene_id": scene_id,
                }
            )
            child_request = replace(
                parent_request,
                operation_id=child_operation_id,
                scene_ids=(scene_id,),
                expected_still_images=still_allocations[scene_index],
                expected_animation_clips=clip_allocations[scene_index],
            )
            provider, mode = self.seams.operation_metadata(child_request)
            spec = ProviderOperationSpec(
                provider=str(provider or "").strip(),
                request_hash=canonical_hash(child_request.payload()),
                reconciliation_mode=mode,
            )
            existing = await self._load_optional_child(child_operation_id)
            child_stage_key = (
                f"{adapter.stage_key}:scene:{scene_index}:"
                f"{canonical_hash({'scene_id': scene_id})[:12]}"
            )
            record = await self.journal.prepare_operation(
                tenant_id=self.tenant_id,
                video_id=parent_request.video_id,
                runtime_job_id=parent.runtime_job_id,
                runtime_hash=parent_request.runtime_hash,
                stage_key=child_stage_key,
                operation_id=child_operation_id,
                spec=spec,
            )
            if record.state == "completed":
                if record.result is None:
                    raise CustomFilmContractError(
                        "Custom Film completed media child has no result"
                    )
                result_object = copy.deepcopy(dict(record.result))
            else:
                result: SectionProductionResult | None = None
                if existing is not None:
                    checkpoint = getattr(self.seams, "checkpoint", None)
                    if callable(checkpoint):
                        recovered = await checkpoint(child_request)
                        if recovered is not None:
                            result = _coerce_result(recovered)
                    if result is None:
                        try:
                            action = self.journal.reconciliation_action(record)
                        except CustomFilmContractError as exc:
                            await self.journal.mark_reconciliation_required(
                                child_operation_id,
                                str(exc),
                            )
                            raise
                        if action == "query_provider":
                            result = await self._call_child_seam(
                                child_request,
                                query_task_id=str(record.provider_operation_id),
                            )
                        elif action == "retry_same_operation":
                            result = await self._call_child_seam(child_request)
                else:
                    result = await self._call_child_seam(child_request)
                if result is None:
                    raise CustomFilmContractError(
                        "Custom Film media child reconciliation did not resolve"
                    )
                result_object = copy.deepcopy(dict(result.result))
                stable_assets = result_object.get("artifacts")
                if not isinstance(stable_assets, list) or not stable_assets:
                    raise CustomFilmContractError(
                        "Custom Film media child returned no durable artifacts"
                    )
                for artifact in stable_assets:
                    if (
                        not isinstance(artifact, Mapping)
                        or not str(artifact.get("artifact_id") or "").strip()
                        or not str(artifact.get("artifact_url") or "").strip()
                    ):
                        raise CustomFilmContractError(
                            "Custom Film media artifact identity is incomplete"
                        )
                await self.journal.mark_completed(
                    child_operation_id,
                    result_object,
                )
            child_results.append(
                {
                    "scene_id": scene_id,
                    "operation_id": child_operation_id,
                    "result": result_object,
                }
            )
        return {
            "scene_ids": list(parent_request.scene_ids),
            "stage": parent_request.stage,
            "child_operations": child_results,
            "exact_seconds": parent_request.exact_seconds,
            "render_mode": parent_request.render_mode,
            "visual_profile": parent_request.visual_profile,
            "image_density": _plain(parent_request.image_density),
            "animation": _plain(parent_request.animation),
            "camera": _plain(parent_request.camera),
            "quality_laws": list(parent_request.quality_laws),
        }

    async def reconcile(
        self,
        adapter: SectionStageAdapter,
        scene_ids: tuple[str, ...],
        operation_id: str,
        operation_record: ProviderOperationRecord,
    ) -> Mapping[str, Any]:
        request = _request(adapter, scene_ids, operation_id)
        if operation_record.operation_id != operation_id:
            raise CustomFilmContractError(
                "Custom Film provider reconciliation identity changed"
            )
        provider_operation_id = str(
            operation_record.provider_operation_id or ""
        ).strip()
        if not provider_operation_id:
            raise CustomFilmContractError(
                "Custom Film provider task identity is missing"
            )
        result = _coerce_result(
            await self.seams.query(request, provider_operation_id)
        )
        if (
            result.provider_operation_id
            and result.provider_operation_id != provider_operation_id
        ):
            raise CustomFilmContractError(
                "Custom Film provider reconciliation returned a different task"
            )
        return copy.deepcopy(dict(result.result))


class _ExactSectionConfig:
    """The existing script seam's config contract, bound to exact seconds."""

    SPEAKING_RATE_WPS = 2.5

    def __init__(self, exact_seconds: int):
        self.total_seconds = exact_seconds
        self.video_length_minutes = exact_seconds / 60
        self.clip_duration_seconds = 10
        self.total_clips = max(1, (exact_seconds + 9) // 10)
        self.words_per_clip = 25
        self.total_script_words = max(1, round(exact_seconds * self.SPEAKING_RATE_WPS))
        tolerance = max(5, round(self.total_script_words * 0.1))
        self.script_min_words = max(1, self.total_script_words - tolerance)
        self.script_max_words = self.total_script_words + tolerance
        self.act_count = 1
        self.clips_per_act = self.total_clips
        self.scenes_per_act = 1


_SCRIPT_REPAIR_ATTEMPTS = 2
_SCRIPT_CONVERGENCE_PASSES = 2
_SCRIPT_GROUNDING_STOPWORDS = frozenset(
    {
        "about",
        "and",
        "after",
        "again",
        "against",
        "also",
        "among",
        "as",
        "at",
        "because",
        "before",
        "being",
        "between",
        "but",
        "by",
        "bring",
        "carry",
        "clear",
        "conclusion",
        "evidence",
        "film",
        "for",
        "from",
        "give",
        "he",
        "if",
        "into",
        "is",
        "it",
        "not",
        "of",
        "on",
        "or",
        "leave",
        "main",
        "make",
        "present",
        "reason",
        "section",
        "she",
        "show",
        "strongest",
        "takeaway",
        "that",
        "the",
        "their",
        "there",
        "these",
        "they",
        "this",
        "through",
        "to",
        "understand",
        "watching",
        "we",
        "what",
        "when",
        "where",
        "which",
        "while",
        "with",
        "within",
    }
)
_SCRIPT_MARKER_PATTERN = re.compile(r"\[(?:ACT|SCENE)\b[^\]]*\]", re.IGNORECASE)
_SCRIPT_ACT_MARKER_PATTERN = re.compile(
    r"^\[ACT (?P<number>\d+) — "
    r"(?P<title>[\w][\w &'’,:!?-]{0,78})"
    r" \| (?P<start>\d+:\d{2}) - (?P<end>\d+:\d{2})"
    r" \| ~(?P<words>\d+) words\]\r?$",
    re.MULTILINE,
)
_SCRIPT_MARKDOWN_HEADING_PATTERN = re.compile(
    r"^\s{0,3}#{1,6}\s+(?P<body>.*)$"
)
_SCRIPT_EMPHASIS_LINE_PATTERN = re.compile(
    r"^\s*(?:\*\*|__)(?P<body>.+?)(?:\*\*|__)\s*$"
)
_SCRIPT_FENCE_PATTERN = re.compile(r"^\s*```[A-Za-z0-9_-]*\s*$")
_SCRIPT_SETEXT_PATTERN = re.compile(r"^\s*(?:=+|-+)\s*$")
_SCRIPT_HORIZONTAL_RULE_PATTERN = re.compile(
    r"^\s*(?:(?:-\s*){3,}|(?:\*\s*){3,}|(?:_\s*){3,})$"
)
_SCRIPT_ALL_CAPS_HEADING_PATTERN = re.compile(
    r"^\s*[A-Z][A-Z0-9'’ -]{2,80}\s*$"
)
_SCRIPT_NUMBER_PATTERN = re.compile(
    r"(?<![\w])(?:18|19|20)\d{2}(?![\w])|(?<![\w])\d+(?:\.\d+)?%?(?![\w])"
)
_SCRIPT_NUMBER_WORDS = frozenset(
    {
        "zero",
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "eleven",
        "twelve",
        "thirteen",
        "fourteen",
        "fifteen",
        "sixteen",
        "seventeen",
        "eighteen",
        "nineteen",
        "twenty",
        "thirty",
        "forty",
        "fifty",
        "sixty",
        "seventy",
        "eighty",
        "ninety",
        "hundred",
        "thousand",
        "million",
        "billion",
        "trillion",
        "first",
        "second",
        "third",
        "fourth",
        "fifth",
        "sixth",
        "seventh",
        "eighth",
        "ninth",
        "tenth",
        "eleventh",
        "twelfth",
        "thirteenth",
        "fourteenth",
        "fifteenth",
        "sixteenth",
        "seventeenth",
        "eighteenth",
        "nineteenth",
        "twentieth",
        "thirtieth",
        "fortieth",
        "fiftieth",
        "sixtieth",
        "seventieth",
        "eightieth",
        "ninetieth",
        "hundredth",
        "thousandth",
        "millionth",
        "billionth",
        "trillionth",
    }
)
_SCRIPT_WORD_PATTERN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'-]*")
_SCRIPT_NAMED_TOKEN_PATTERN = re.compile(
    r"\b(?:[A-Z]{2,5}|[A-Z][a-z]{2,})\b"
)


def _script_word_count(script_text: str) -> int:
    return len(_SCRIPT_WORD_PATTERN.findall(_script_spoken_prose(script_text)))


def _script_number_word_anchors(text: str) -> set[str]:
    anchors: set[str] = set()
    for token in _SCRIPT_WORD_PATTERN.findall(text):
        for part in re.split(r"[-']", token.casefold()):
            if part in _SCRIPT_NUMBER_WORDS:
                anchors.add(part)
    return anchors


def _script_spoken_prose(script_text: str) -> str:
    """Remove generated document chrome while preserving spoken paragraphs."""

    without_markers = _SCRIPT_MARKER_PATTERN.sub("", script_text)
    lines = without_markers.splitlines()
    spoken: list[str] = []
    in_fence = False
    for raw_line in lines:
        if _SCRIPT_FENCE_PATTERN.fullmatch(raw_line):
            in_fence = not in_fence
            spoken.append("")
            continue
        line = raw_line.replace("`", "")
        markdown_heading = _SCRIPT_MARKDOWN_HEADING_PATTERN.match(line)
        if markdown_heading:
            line = markdown_heading.group("body")
        emphasis = _SCRIPT_EMPHASIS_LINE_PATTERN.fullmatch(line)
        if emphasis:
            line = emphasis.group("body")
        stripped = line.strip()
        if (
            not stripped
            or _SCRIPT_SETEXT_PATTERN.fullmatch(line)
            or (
                not in_fence
                and _SCRIPT_ALL_CAPS_HEADING_PATTERN.fullmatch(line)
            )
        ):
            spoken.append("")
            continue
        spoken.append(line)
    return "\n".join(spoken)


def _script_role_structure_law(role: str) -> str:
    """Return film-agnostic craft constraints without authorizing facts."""

    normalized = role.strip().casefold().replace("-", "_").replace(" ", "_")
    laws = {
        "opening": (
            "Open immediately on the clearest visible disruption, tension, or "
            "question authorized by this section. Establish the through-line "
            "and stakes quickly, escalate curiosity through distinct visual "
            "beats, and end on an open handoff without revealing the answer early."
        ),
        "evidence": (
            "Open on the strongest concrete visible proof authorized by this "
            "section. Escalate across distinct approved evidence types so each "
            "beat raises confidence or stakes instead of listing or repeating. "
            "End on an earned reveal, question, or handoff to the next section."
        ),
        "case_study": (
            "Open inside the most concrete approved moment, subject, or event. "
            "Escalate from observation through discovery to consequence using "
            "distinct visual beats, then end on an earned insight or handoff."
        ),
        "resolution": (
            "Open on the decisive approved action or change. Show the causal "
            "resolution in ordered visible beats with escalating confirmation, "
            "then end by proving the result and handing off cleanly."
        ),
        "closing": (
            "Open on the earned payoff. Synthesize the approved through-line "
            "without a list or generic recap, introduce no new claims, and land "
            "on one decisive visible final image and takeaway."
        ),
    }
    return laws.get(
        normalized,
        (
            "Open on the strongest concrete visible beat authorized by this "
            "section. Develop distinct beats in a clear escalating causal order, "
            "avoid list-like repetition, and end on an earned transition."
        ),
    )


def _script_story_arc_guidance(
    story_arc: tuple[Mapping[str, Any], ...],
    *,
    current_order_index: int,
) -> str:
    if not story_arc:
        return ""
    lines = [
        "=== APPROVED STORY ARC (STRUCTURE ONLY — NOT A FACTUAL SOURCE) ===",
        (
            "Use this ordered arc only for continuity, non-duplication, "
            "escalation, and the handoff between sections. Other sections' "
            "purposes do not authorize any subject, person, place, organization, "
            "event, date, number, example, or case study in this section."
        ),
    ]
    for item in story_arc:
        order_index = int(item.get("order_index", -1))
        current = " [CURRENT SECTION]" if order_index == current_order_index else ""
        lines.append(
            f"SECTION {order_index + 1}{current} — "
            f"ROLE: {str(item.get('role') or '')}; "
            f"PURPOSE: {str(item.get('purpose') or '')}"
        )
    lines.append("=== END APPROVED STORY ARC ===")
    return "\n".join(lines)


def _script_approved_contract(
    *,
    role: str,
    purpose: str,
    exact_seconds: int,
    config: _ExactSectionConfig,
) -> str:
    """One exclusive grounding/timing block shared by write and repair."""

    end_timestamp = f"{exact_seconds // 60}:{exact_seconds % 60:02d}"
    exact_marker = (
        "[ACT 1 — <SHORT SECTION TITLE> | "
        f"0:00 - {end_timestamp} | ~{config.total_script_words} words]"
    )
    return "\n".join(
        (
            "=== EXCLUSIVE APPROVED SECTION CONTRACT ===",
            f"APPROVED ROLE: {role}",
            f"APPROVED PURPOSE: {purpose}",
            f"EXACT SPOKEN DURATION: {exact_seconds} seconds",
            (
                "EXACT SPOKEN WORD BAND: "
                f"{config.script_min_words}-{config.script_max_words} words "
                f"(target {config.total_script_words})"
            ),
            (
                "GROUNDING LAW: The approved role and purpose above are the "
                "only source for the section's subject, people, places, "
                "organizations, events, dates, numbers, examples, and case "
                "studies. They may describe a real or fictional topic; do not "
                "assume either and do not add adjacent material."
            ),
            (
                f"OUTPUT FORMAT LAW: Return exactly {config.act_count} act "
                "using the shared marker grammar on its own line. For this "
                f"section the required marker grammar is: {exact_marker} "
                "Replace only <SHORT SECTION TITLE> with a short title; keep "
                "the brackets, ACT number, separators, timestamps, and target "
                "word annotation exactly as shown."
            ),
            (
                "Do not replace the bracketed marker with ACT/END prose. Do "
                "not add SCRIPT, END, notes, analysis, Markdown headings, or "
                "any wrapper before or after the marked spoken section. The "
                "marker is document structure, not spoken narration."
            ),
            (
                "VISUAL-STORY REPAIR LAW: Keep the approved focus explicit. "
                "Every narrative beat must name a concrete visible subject "
                "and show relevant action, evidence, environment, behavior, "
                "or observable change tied directly to the approved purpose. "
                "Replace abstract summary, generic stakes, promises, and "
                "non-visual filler with filmable shots or actions, without "
                "inventing any unapproved fact, name, date, number, example, "
                "or adjacent topic."
            ),
            (
                "ROLE-AWARE STRUCTURE LAW: "
                + _script_role_structure_law(role)
            ),
            "=== END EXCLUSIVE APPROVED SECTION CONTRACT ===",
        )
    )


def _script_output_format_issues(
    script_text: str,
    *,
    config: _ExactSectionConfig,
) -> list[str]:
    matches = list(_SCRIPT_ACT_MARKER_PATTERN.finditer(script_text))
    if len(matches) != config.act_count:
        return [
            "script must contain exactly "
            f"{config.act_count} shared bracketed ACT marker"
        ]
    expected_end = f"{config.total_seconds // 60}:{config.total_seconds % 60:02d}"
    marker = matches[0]
    leading_whitespace = len(script_text) - len(script_text.lstrip())
    if marker.start() != leading_whitespace:
        return [
            "canonical ACT marker must be the first non-whitespace content; "
            "remove every planning note, heading, separator, emphasis block, "
            "or prose prefix before it"
        ]
    if (
        int(marker.group("number")) != 1
        or marker.group("title") == "<SHORT SECTION TITLE>"
        or marker.group("start") != "0:00"
        or marker.group("end") != expected_end
        or int(marker.group("words")) != config.total_script_words
    ):
        return [
            "script ACT marker changed the required number, title, "
            "timestamps, or target-word annotation"
        ]
    trailing_lines = [
        line for line in script_text[marker.end() :].splitlines() if line.strip()
    ]
    if trailing_lines:
        terminal = trailing_lines[-1]
        if (
            _SCRIPT_FENCE_PATTERN.fullmatch(terminal)
            or _SCRIPT_HORIZONTAL_RULE_PATTERN.fullmatch(terminal)
            or re.fullmatch(
                r"\s*(?:END|SCRIPT\s+END|END\s+SCRIPT)\s*[.!]?\s*",
                terminal,
                re.IGNORECASE,
            )
        ):
            return [
                "script has trailing document chrome after narration; remove "
                "the terminal fence, horizontal rule, or END wrapper"
            ]
    outside_marker = _SCRIPT_ACT_MARKER_PATTERN.sub("", script_text)
    if re.search(r"(?im)^\s*(?:ACT\s+\d+|END)\b", outside_marker):
        return ["script contains an ACT/END wrapper outside the required marker"]
    return []


def _script_grounding_issues(
    script_text: str,
    *,
    approved_context: str,
    config: _ExactSectionConfig,
    generator_validation: Any,
) -> list[str]:
    """Deterministic, provider-independent guard before a script is persisted.

    The shared generator deliberately treats its validation report as advisory.
    Custom Film cannot: voice and imagery immediately follow this stage, so the
    exact approved section timing and grounding must fail closed here.
    """

    issues: list[str] = []
    format_issues = _script_output_format_issues(script_text, config=config)
    if format_issues:
        return format_issues
    word_count = _script_word_count(script_text)
    if not config.script_min_words <= word_count <= config.script_max_words:
        issues.append(
            "spoken word count "
            f"{word_count} is outside the approved section range "
            f"{config.script_min_words}-{config.script_max_words}"
        )

    if isinstance(generator_validation, Mapping):
        validation_issues = generator_validation.get("issues")
        if generator_validation.get("valid") is False:
            if isinstance(validation_issues, list):
                actionable = [
                    str(issue)
                    for issue in validation_issues
                    if not str(issue).startswith(
                        ("Script too short:", "Script too long:")
                    )
                ]
                if actionable:
                    issues.append("; ".join(actionable[:4]))
            else:
                issues.append("shared script validation failed")

    approved_words = {
        word.casefold()
        for word in _SCRIPT_WORD_PATTERN.findall(approved_context)
        if len(word) >= 4 and word.casefold() not in _SCRIPT_GROUNDING_STOPWORDS
    }
    script_words = {
        word.casefold() for word in _SCRIPT_WORD_PATTERN.findall(script_text)
    }
    if approved_words and not approved_words.intersection(script_words):
        issues.append("script does not retain a distinctive approved focus term")

    prose = _script_spoken_prose(script_text)
    approved_numbers = set(_SCRIPT_NUMBER_PATTERN.findall(approved_context))
    unsupported_numbers = sorted(
        set(_SCRIPT_NUMBER_PATTERN.findall(prose)) - approved_numbers
    )
    if unsupported_numbers:
        issues.append(
            "script introduces number/date anchors absent from the approved "
            "section: " + ", ".join(unsupported_numbers[:6])
        )
    approved_number_words = _script_number_word_anchors(approved_context)
    unsupported_number_words = sorted(
        _script_number_word_anchors(prose) - approved_number_words
    )
    if unsupported_number_words:
        issues.append(
            "script introduces number-word anchors absent from the approved "
            "section: " + ", ".join(unsupported_number_words[:6])
        )

    approved_casefold = approved_context.casefold()
    unsupported_named: list[str] = []
    for match in _SCRIPT_NAMED_TOKEN_PATTERN.finditer(prose):
        token = match.group(0)
        before = prose[: match.start()]
        line_start = before.rfind("\n") + 1
        if not before[line_start:].strip():
            continue
        trimmed_before = before.rstrip()
        if not trimmed_before or trimmed_before[-1:] in ".!?":
            continue
        if token.casefold() in approved_casefold:
            continue
        if token in {"I"} or token.casefold() in _SCRIPT_GROUNDING_STOPWORDS:
            continue
        unsupported_named.append(token)
    if unsupported_named:
        issues.append(
            "script introduces named anchors absent from the approved section: "
            + ", ".join(sorted(set(unsupported_named))[:6])
        )
    return issues


def _validated_early_quality_result(
    value: Any,
    *,
    original_scenes: list[dict[str, Any]],
) -> tuple[Any, list[dict[str, Any]], int]:
    """Accept only one internally consistent, unambiguous critic pass."""

    failure_prefix = (
        "Custom Film section script failed visual-story quality before "
        "voice or imagery: "
    )

    def fail(detail: str) -> None:
        raise CustomFilmContractError(failure_prefix + detail)

    expected_keys = {
        "scenes",
        "critique",
        "needs_review",
        "edit_rounds",
        "regenerated",
        "changed",
    }
    if not isinstance(value, Mapping) or set(value) != expected_keys:
        fail("quality orchestration result shape is invalid")
    if type(value["needs_review"]) is not bool:
        fail("quality review flag is invalid")
    if type(value["regenerated"]) is not bool or value["regenerated"]:
        fail("quality regeneration flag is invalid")
    edit_rounds = value["edit_rounds"]
    if (
        type(edit_rounds) is not int
        or edit_rounds < 0
        or edit_rounds > _SCRIPT_REPAIR_ATTEMPTS
    ):
        fail("quality edit-round count is invalid")
    if type(value["changed"]) is not bool:
        fail("quality changed flag is invalid")

    raw_scenes = value["scenes"]
    if (
        not isinstance(raw_scenes, list)
        or len(raw_scenes) != 1
        or not isinstance(raw_scenes[0], Mapping)
        or set(raw_scenes[0]) != {"scene", "text"}
        or raw_scenes[0].get("scene") != 1
        or not isinstance(raw_scenes[0].get("text"), str)
        or not raw_scenes[0]["text"].strip()
    ):
        fail("quality edit changed or invalidated scene assignments")
    scenes = [
        {"scene": 1, "text": str(raw_scenes[0]["text"]).strip()}
    ]
    if value["changed"] != (scenes != original_scenes):
        fail("quality changed flag contradicts the returned script")

    grade = value["critique"]
    required_grade_fields = (
        "verdict",
        "score",
        "failing_gates",
        "violations",
        "rule_verdicts",
        "needs_revision",
    )
    if any(not hasattr(grade, field) for field in required_grade_fields):
        fail("quality critique result shape is invalid")
    verdict = getattr(grade, "verdict")
    score = getattr(grade, "score")
    failing_gates = getattr(grade, "failing_gates")
    violations = getattr(grade, "violations")
    rule_verdicts = getattr(grade, "rule_verdicts")
    needs_revision = getattr(grade, "needs_revision")
    if (
        not isinstance(verdict, str)
        or type(score) is not int
        or not 0 <= score <= 100
        or not isinstance(failing_gates, list)
        or any(not isinstance(item, str) for item in failing_gates)
        or not isinstance(violations, list)
        or any(not isinstance(item, str) for item in violations)
        or not isinstance(rule_verdicts, list)
        or type(needs_revision) is not bool
    ):
        fail("quality critique result fields are invalid")
    for rule_verdict in rule_verdicts:
        if (
            not hasattr(rule_verdict, "rule")
            or not isinstance(rule_verdict.rule, str)
            or not hasattr(rule_verdict, "passed")
            or type(rule_verdict.passed) is not bool
        ):
            fail("quality rule verdict shape is invalid")
        if not rule_verdict.passed:
            fail(f"quality rule failed: {rule_verdict.rule or 'unnamed rule'}")
    if (
        verdict.strip().casefold() != "pass"
        or value["needs_review"]
        or needs_revision
        or failing_gates
        or violations
    ):
        named = [
            verdict,
            *failing_gates,
            *violations,
        ]
        fail(
            "critic did not return an unambiguous pass"
            + (": " + "; ".join(dict.fromkeys(named)) if named else "")
        )
    return grade, scenes, edit_rounds


class SharedSectionProductionSeams:
    """Default bridge into StoryEngine's existing shared production code."""

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self._executor = None

    def operation_metadata(
        self, request: SectionProductionRequest
    ) -> tuple[str, str]:
        if request.stage == "voice" and request.dialogue_audio == "grok_native":
            return _LOCAL_PROVIDER, RECONCILIATION_IDEMPOTENCY
        if request.stage == "script":
            return _TEXT_PROVIDER, RECONCILIATION_NONE
        if request.stage == "quality":
            return _TEXT_PROVIDER, RECONCILIATION_NONE
        if request.stage == "pictures":
            return _IMAGE_PROVIDER, RECONCILIATION_NONE
        if request.stage == "motion":
            return _MOTION_PROVIDER, RECONCILIATION_NONE
        if request.stage == "clips":
            return _CLIP_PROVIDER, RECONCILIATION_NONE
        return _VOICE_PROVIDER, RECONCILIATION_QUERY

    async def _ready_executor(self):
        if self._executor is None:
            from pipeline_executor import PipelineExecutor

            self._executor = PipelineExecutor(self.tenant_id)
        await self._executor._ensure_initialized()
        return self._executor

    async def submit(
        self,
        request: SectionProductionRequest,
        *,
        on_submitted: SubmittedCallback,
    ) -> SectionProductionResult:
        if request.stage == "script":
            return SectionProductionResult(await self._script(request))
        if request.stage == "voice":
            return SectionProductionResult(
                await self._voice(request, on_submitted=on_submitted)
            )
        if request.stage == "quality":
            return SectionProductionResult(await self._quality(request))
        if request.stage == "pictures":
            return SectionProductionResult(await self._pictures(request))
        if request.stage == "motion":
            return SectionProductionResult(await self._motion(request))
        if request.stage == "clips":
            return SectionProductionResult(await self._clips(request))
        raise CustomFilmContractError(
            "Unsupported Custom Film production stage"
        )

    async def query(
        self,
        request: SectionProductionRequest,
        provider_operation_id: str,
    ) -> SectionProductionResult:
        if request.stage == "voice":
            return SectionProductionResult(
                await self._voice(
                    request,
                    provider_operation_id=provider_operation_id,
                ),
                provider_operation_id,
            )
        raise CustomFilmContractError(
            "This Custom Film provider has no query reconciliation seam"
        )

    async def checkpoint(
        self,
        request: SectionProductionRequest,
    ) -> SectionProductionResult | None:
        if request.stage == "voice" and request.dialogue_audio != "grok_native":
            recovered = await self._voice_artifact_checkpoint(request)
        elif request.stage in {"pictures", "motion", "clips"}:
            recovered = await self._media_artifact_checkpoint(request)
        else:
            recovered = None
        return (
            SectionProductionResult(recovered)
            if recovered is not None
            else None
        )

    async def _scene_number(self, request: SectionProductionRequest) -> int:
        rows = await self._scene_rows(request)
        if len(rows) != 1 or type(rows[0].get("scene")) is not int:
            raise CustomFilmContractError(
                "Custom Film media child must own one numbered scene"
            )
        return int(rows[0]["scene"])

    async def _raw_asset_rows(
        self,
        request: SectionProductionRequest,
    ) -> list[dict[str, Any]]:
        scene = await self._scene_number(request)
        import database

        pool = await database.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, image_url, drive_image_url, video_prompt, caption,
                          video_clip_url, generation_method, image_model,
                          model_used, status, motion_gate_status,
                          duration_seconds, assigned_video_duration,
                          video_duration
                   FROM assets
                   WHERE tenant_id = $1::uuid AND video_id = $2::uuid
                     AND scene = $3
                   ORDER BY image_index, id""",
                self.tenant_id,
                request.video_id,
                scene,
            )
        return [dict(row) for row in rows]

    @staticmethod
    def _artifact_url(request: SectionProductionRequest, row: Mapping[str, Any]) -> str:
        if request.stage == "pictures":
            return str(row.get("drive_image_url") or row.get("image_url") or "").strip()
        if request.stage == "motion":
            prompt = str(row.get("video_prompt") or "").strip()
            return (
                "motion-prompt:"
                + canonical_hash(
                    {
                        "asset_id": str(row.get("id") or ""),
                        "prompt": prompt,
                        "camera": _plain(request.camera),
                    }
                )
                if prompt
                else ""
            )
        return str(row.get("video_clip_url") or "").strip()

    @staticmethod
    def _asset_provider_model(
        stage: str,
        row: Mapping[str, Any],
    ) -> str:
        if stage == "pictures":
            return str(row.get("image_model") or row.get("model_used") or "").strip()
        if stage == "clips":
            return str(row.get("model_used") or "").strip()
        return ""

    @staticmethod
    def _expected_generation_method(request: SectionProductionRequest) -> str:
        return "static_docu" if request.render_mode == "static_docu" else "coverage"

    @staticmethod
    def _section_contract_hash(
        request: SectionProductionRequest,
        *,
        stage: str | None = None,
    ) -> str:
        payload = request.payload()
        payload.pop("operation_id", None)
        payload.pop("asset_ids", None)
        payload.pop("expected_still_images", None)
        payload.pop("expected_animation_clips", None)
        payload["stage"] = stage or request.stage
        return canonical_hash(payload)

    def _artifact_identity_hash(
        self,
        request: SectionProductionRequest,
        row: Mapping[str, Any],
        *,
        stage: str,
        request_hash: str,
        provider_model: str,
        actual_duration_ms: int | None = None,
        assigned_duration_ms: int | None = None,
        timing_transform: Mapping[str, Any] | None = None,
    ) -> str:
        if stage == "pictures":
            caption_card = canonical_caption_card(row.get("caption"))
            artifact = {
                "image_url": str(row.get("image_url") or "").strip(),
                "drive_image_url": str(row.get("drive_image_url") or "").strip(),
                "caption_card": caption_card,
                "caption_hash": canonical_hash({"caption_card": caption_card}),
            }
        elif stage == "motion":
            artifact = {"video_prompt": str(row.get("video_prompt") or "").strip()}
        else:
            artifact = {
                "video_clip_url": str(row.get("video_clip_url") or "").strip(),
                "actual_duration_ms": actual_duration_ms,
                "assigned_duration_ms": assigned_duration_ms,
                "timing_transform": _plain(timing_transform),
            }
        return canonical_hash(
            {
                "stage": stage,
                "asset_id": str(row.get("id") or row.get("asset_id") or ""),
                "artifact": artifact,
                "provider_model": provider_model,
                "generation_method": str(
                    row.get("generation_method") or ""
                ).strip(),
                "camera": _plain(request.camera),
                "request_hash": request_hash,
                "section_contract_hash": self._section_contract_hash(
                    request,
                    stage=stage,
                ),
            }
        )

    def _completed_provenance_is_exact(
        self,
        request: SectionProductionRequest,
        row: Mapping[str, Any],
        *,
        stage: str,
    ) -> bool:
        stored_hash = str(row.get("provenance_artifact_hash") or "")
        stored_model = str(row.get("provenance_provider_model") or "")
        stored_request_hash = str(row.get("provenance_request_hash") or "")
        stored_generation_method = str(
            row.get("provenance_generation_method") or ""
        )
        current_generation_method = str(row.get("generation_method") or "")
        if (
            not stored_hash
            or not stored_model
            or not stored_request_hash
            or stored_generation_method != current_generation_method
            or current_generation_method
            != self._expected_generation_method(request)
        ):
            return False
        current_model = self._asset_provider_model(stage, row)
        if stage in {"pictures", "clips"} and (
            not current_model or current_model != stored_model
        ):
            return False
        actual_duration_ms = row.get("actual_duration_ms")
        assigned_duration_ms = row.get("assigned_duration_ms")
        timing_transform = row.get("timing_transform")
        if stage == "clips" and (
            type(actual_duration_ms) is not int
            or type(assigned_duration_ms) is not int
            or not isinstance(timing_transform, Mapping)
            or row.get("video_duration") is None
            or row.get("duration_seconds") is None
            or row.get("assigned_video_duration") is None
            or _duration_ms(row["video_duration"], label="current provider clip")
            != actual_duration_ms
            or _duration_ms(row["duration_seconds"], label="current target")
            != assigned_duration_ms
            or _duration_ms(row["assigned_video_duration"], label="current assignment")
            != assigned_duration_ms
            or dict(timing_transform)
            != _timing_transform(actual_duration_ms, assigned_duration_ms)
        ):
            return False
        return stored_hash == self._artifact_identity_hash(
            request,
            row,
            stage=stage,
            request_hash=stored_request_hash,
            provider_model=stored_model,
            actual_duration_ms=actual_duration_ms,
            assigned_duration_ms=assigned_duration_ms,
            timing_transform=timing_transform,
        )

    async def _record_media_provenance(
        self,
        request: SectionProductionRequest,
        rows: list[dict[str, Any]],
    ) -> None:
        if request.stage != "pictures":
            raise CustomFilmContractError(
                "Only picture provenance may complete without submission"
            )
        expected = request.expected_still_images
        if len(rows) != expected:
            raise CustomFilmContractError(
                f"Custom Film {request.stage} count does not match the approved estimate"
            )
        request_hash = canonical_hash(request.payload())
        prepared_rows: list[tuple[dict[str, Any], str, str, str]] = []
        for row in rows:
            asset_id = str(row.get("id") or "")
            artifact_url = self._artifact_url(request, row)
            if not asset_id or not artifact_url:
                raise CustomFilmContractError(
                    f"Custom Film {request.stage} artifact is incomplete"
                )
            if request.stage == "pictures" and (
                str(row.get("status") or "") != "done"
                or not str(row.get("image_url") or "").strip()
            ):
                raise CustomFilmContractError(
                    "Custom Film picture is not a genuinely generated image"
                )
            if request.stage == "motion" and (
                str(row.get("motion_gate_status") or "") == "blocked"
                or not str(row.get("video_prompt") or "").strip()
            ):
                raise CustomFilmContractError(
                    "Custom Film motion prompt is missing or blocked"
                )
            provider_model = self._asset_provider_model(request.stage, row)
            if not provider_model:
                raise CustomFilmContractError(
                    f"Custom Film {request.stage} provider model is missing"
                )
            identity_hash = self._artifact_identity_hash(
                request,
                row,
                stage=request.stage,
                request_hash=request_hash,
                provider_model=provider_model,
            )
            prepared_rows.append((row, asset_id, provider_model, identity_hash))
        import database

        pool = await database.get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                for row, asset_id, provider_model, identity_hash in prepared_rows:
                    inserted = await conn.execute(
                        """INSERT INTO custom_film_asset_provenance
                             (tenant_id, video_id, asset_id, plan_id, section_id,
                              runtime_hash, stage, operation_id, request_hash,
                              section_contract_hash, generation_method,
                              provider_model, status,
                              artifact_url_hash, completed_at)
                           VALUES
                             ($1::uuid, $2::uuid, $3::uuid, $4::uuid, $5::uuid,
                              $6, $7, $8, $9, $10, $11, $12, 'completed',
                              $13, now())
                           ON CONFLICT
                             (tenant_id, video_id, asset_id, runtime_hash, stage)
                           DO NOTHING""",
                        self.tenant_id,
                        request.video_id,
                        asset_id,
                        request.plan_id,
                        request.section_id,
                        request.runtime_hash,
                        request.stage,
                        request.operation_id,
                        request_hash,
                        self._section_contract_hash(request),
                        str(row.get("generation_method") or ""),
                        provider_model,
                        identity_hash,
                    )
                    if not str(inserted).endswith(" 1"):
                        raise CustomFilmContractError(
                            "Custom Film artifact provenance was already claimed"
                        )

    async def _prepare_media_provenance(
        self,
        request: SectionProductionRequest,
        rows: list[dict[str, Any]],
        *,
        provider_models: Mapping[str, str] | None = None,
        durations: Mapping[str, Decimal] | None = None,
    ) -> None:
        expected = (
            request.expected_still_images
            if request.stage == "motion"
            else request.expected_animation_clips
        )
        if (
            request.stage not in {"motion", "clips"}
            or len(rows) != expected
        ):
            raise CustomFilmContractError(
                f"Custom Film {request.stage} claim is invalid"
            )
        expected_ids = tuple(request.asset_ids)
        row_ids = tuple(str(row.get("id") or "") for row in rows)
        if row_ids != expected_ids:
            raise CustomFilmContractError(
                f"Custom Film {request.stage} claim asset IDs changed"
            )
        target_field = "video_prompt" if request.stage == "motion" else "video_clip_url"
        if any(str(row.get(target_field) or "").strip() for row in rows):
            raise CustomFilmContractError(
                f"Custom Film {request.stage} found unexplained pre-existing artifacts"
            )
        request_hash = canonical_hash(request.payload())
        import database

        pool = await database.get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                for row in rows:
                    asset_id = str(row["id"])
                    assigned_duration = (
                        durations.get(asset_id) if durations is not None else None
                    )
                    assigned_duration_ms = (
                        _duration_ms(assigned_duration, label="assigned clip")
                        if assigned_duration is not None
                        else None
                    )
                    provider_model = str(
                        (provider_models or {}).get(asset_id) or ""
                    ).strip() or None
                    inserted = await conn.execute(
                        """INSERT INTO custom_film_asset_provenance
                             (tenant_id, video_id, asset_id, plan_id, section_id,
                              runtime_hash, stage, operation_id, request_hash,
                              section_contract_hash, generation_method,
                              provider_model, status, assigned_duration_ms)
                           SELECT
                             $1::uuid, $2::uuid, a.id, $4::uuid, $5::uuid,
                             $6, $7, $8, $9, $10, a.generation_method,
                             $11, 'prepared', $12
                           FROM assets a
                           WHERE a.tenant_id = $1::uuid AND a.video_id = $2::uuid
                             AND a.id = $3::uuid
                             AND CASE WHEN $7 = 'motion'
                               THEN NULLIF(trim(a.video_prompt), '') IS NULL
                               ELSE NULLIF(trim(a.video_clip_url), '') IS NULL
                             END
                           ON CONFLICT
                             (tenant_id, video_id, asset_id, runtime_hash, stage)
                           DO NOTHING""",
                        self.tenant_id,
                        request.video_id,
                        asset_id,
                        request.plan_id,
                        request.section_id,
                        request.runtime_hash,
                        request.stage,
                        request.operation_id,
                        request_hash,
                        self._section_contract_hash(request),
                        provider_model,
                        assigned_duration_ms,
                    )
                    if not str(inserted).endswith(" 1"):
                        raise CustomFilmContractError(
                            f"Custom Film {request.stage} asset is already claimed or changed"
                        )
                submitted = await conn.execute(
                    """UPDATE custom_film_asset_provenance
                       SET status = 'submitted', updated_at = now()
                       WHERE tenant_id = $1::uuid AND video_id = $2::uuid
                         AND runtime_hash = $3 AND stage = $4
                         AND operation_id = $5 AND request_hash = $6
                         AND asset_id = ANY($7::uuid[]) AND status = 'prepared'""",
                    self.tenant_id,
                    request.video_id,
                    request.runtime_hash,
                    request.stage,
                    request.operation_id,
                    request_hash,
                    list(expected_ids),
                )
                if not str(submitted).endswith(f" {expected}"):
                    raise CustomFilmContractError(
                        f"Custom Film {request.stage} claims could not be submitted"
                    )

    async def _complete_media_provenance(
        self,
        request: SectionProductionRequest,
        rows: list[dict[str, Any]],
        *,
        provider_models: Mapping[str, str],
        durations: Mapping[str, Decimal] | None = None,
        actual_durations: Mapping[str, Any] | None = None,
    ) -> None:
        request_hash = canonical_hash(request.payload())
        if tuple(str(row.get("id") or "") for row in rows) != request.asset_ids:
            raise CustomFilmContractError(
                f"Custom Film {request.stage} provider result asset IDs changed"
            )
        import database

        pool = await database.get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                for row in rows:
                    asset_id = str(row["id"])
                    provider_model = str(
                        provider_models.get(asset_id) or ""
                    ).strip()
                    if not provider_model:
                        raise CustomFilmContractError(
                            f"Custom Film {request.stage} provider model is missing"
                        )
                    assigned_duration = (
                        durations.get(asset_id) if durations is not None else None
                    )
                    actual_duration = (
                        actual_durations.get(asset_id)
                        if actual_durations is not None
                        else None
                    )
                    assigned_duration_ms = (
                        _duration_ms(assigned_duration, label="assigned clip")
                        if assigned_duration is not None
                        else None
                    )
                    actual_duration_ms = (
                        _duration_ms(actual_duration, label="provider clip")
                        if actual_duration is not None
                        else None
                    )
                    timing_transform = (
                        _timing_transform(actual_duration_ms, assigned_duration_ms)
                        if actual_duration_ms is not None
                        and assigned_duration_ms is not None
                        else None
                    )
                    if request.stage == "clips" and (
                        assigned_duration_ms is None
                        or actual_duration_ms is None
                        or row.get("video_duration") is None
                        or row.get("duration_seconds") is None
                        or row.get("assigned_video_duration") is None
                        or _duration_ms(
                            row["video_duration"],
                            label="current provider clip",
                        )
                        != actual_duration_ms
                        or _duration_ms(row["duration_seconds"], label="current target")
                        != assigned_duration_ms
                        or _duration_ms(
                            row["assigned_video_duration"],
                            label="current assignment",
                        )
                        != assigned_duration_ms
                    ):
                        raise CustomFilmContractError(
                            "Custom Film clip duration allocation changed"
                        )
                    identity_hash = self._artifact_identity_hash(
                        request,
                        row,
                        stage=request.stage,
                        request_hash=request_hash,
                        provider_model=provider_model,
                        actual_duration_ms=actual_duration_ms,
                        assigned_duration_ms=assigned_duration_ms,
                        timing_transform=timing_transform,
                    )
                    updated = await conn.execute(
                        """UPDATE custom_film_asset_provenance
                           SET status = 'completed', artifact_url_hash = $8,
                               provider_model = $9,
                               actual_duration_ms = $10,
                               assigned_duration_ms = $11,
                               timing_transform = $12::jsonb,
                               completed_at = now(), updated_at = now()
                           WHERE tenant_id = $1::uuid AND video_id = $2::uuid
                             AND asset_id = $3::uuid AND runtime_hash = $4
                             AND stage = $5 AND operation_id = $6
                             AND request_hash = $7 AND status = 'submitted'""",
                        self.tenant_id,
                        request.video_id,
                        asset_id,
                        request.runtime_hash,
                        request.stage,
                        request.operation_id,
                        request_hash,
                        identity_hash,
                        provider_model,
                        actual_duration_ms,
                        assigned_duration_ms,
                        (
                            json.dumps(timing_transform, sort_keys=True)
                            if timing_transform is not None
                            else None
                        ),
                    )
                    if not str(updated).endswith(" 1"):
                        raise CustomFilmContractError(
                            f"Custom Film {request.stage} provenance completion changed"
                        )

    async def _section_completed_rows(
        self,
        request: SectionProductionRequest,
        *,
        stage: str,
        expected: int,
    ) -> list[dict[str, Any]]:
        scene = await self._scene_number(request)
        contract_hash = self._section_contract_hash(request, stage=stage)
        import database

        pool = await database.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT a.id, a.image_url, a.drive_image_url, a.video_prompt,
                          a.caption,
                          a.video_clip_url, a.generation_method, a.image_model,
                          a.model_used, a.status, a.motion_gate_status,
                          a.duration_seconds, a.assigned_video_duration,
                          a.video_duration, p.actual_duration_ms,
                          p.assigned_duration_ms, p.timing_transform,
                          p.artifact_url_hash AS provenance_artifact_hash,
                          p.provider_model AS provenance_provider_model,
                          p.request_hash AS provenance_request_hash,
                          p.generation_method AS provenance_generation_method
                   FROM custom_film_asset_provenance p
                   JOIN assets a
                     ON (a.tenant_id, a.video_id, a.id)
                      = (p.tenant_id, p.video_id, p.asset_id)
                   WHERE p.tenant_id = $1::uuid AND p.video_id = $2::uuid
                     AND p.plan_id = $3::uuid AND p.section_id = $4::uuid
                     AND p.runtime_hash = $5 AND p.stage = $6
                     AND p.section_contract_hash = $7
                     AND p.status = 'completed' AND a.scene = $8
                   ORDER BY a.image_index, a.id""",
                self.tenant_id,
                request.video_id,
                request.plan_id,
                request.section_id,
                request.runtime_hash,
                stage,
                contract_hash,
                scene,
            )
        values = [dict(row) for row in rows]
        if len(values) != expected:
            raise CustomFilmContractError(
                f"Custom Film {stage} provenance/count is incomplete"
            )
        if any(
            not self._completed_provenance_is_exact(request, row, stage=stage)
            for row in values
        ):
            raise CustomFilmContractError(
                f"Custom Film {stage} artifact provenance was tampered"
            )
        return values

    async def _provenance_rows(
        self,
        request: SectionProductionRequest,
    ) -> list[dict[str, Any]]:
        scene = await self._scene_number(request)
        request_hash = canonical_hash(request.payload())
        expected = (
            request.expected_still_images
            if request.stage in {"pictures", "motion"}
            else request.expected_animation_clips
        )
        import database

        pool = await database.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT a.id, a.image_url, a.drive_image_url, a.video_prompt,
                          a.caption,
                          a.video_clip_url, a.generation_method, a.image_model,
                          a.model_used, a.status, a.motion_gate_status,
                          a.duration_seconds, a.assigned_video_duration,
                          a.video_duration, p.actual_duration_ms,
                          p.assigned_duration_ms, p.timing_transform,
                          p.artifact_url_hash AS provenance_artifact_hash,
                          p.provider_model AS provenance_provider_model,
                          p.request_hash AS provenance_request_hash,
                          p.generation_method AS provenance_generation_method
                   FROM custom_film_asset_provenance p
                   JOIN assets a
                     ON (a.tenant_id, a.video_id, a.id)
                      = (p.tenant_id, p.video_id, p.asset_id)
                   WHERE p.tenant_id = $1::uuid AND p.video_id = $2::uuid
                     AND p.plan_id = $3::uuid AND p.section_id = $4::uuid
                     AND p.runtime_hash = $5 AND p.stage = $6
                     AND p.operation_id = $7 AND p.request_hash = $8
                     AND p.status = 'completed' AND a.scene = $9
                   ORDER BY a.image_index, a.id""",
                self.tenant_id,
                request.video_id,
                request.plan_id,
                request.section_id,
                request.runtime_hash,
                request.stage,
                request.operation_id,
                request_hash,
                scene,
            )
        values = [dict(row) for row in rows]
        if len(values) != expected:
            return []
        if request.asset_ids and tuple(str(row["id"]) for row in values) != request.asset_ids:
            return []
        if any(
            not self._completed_provenance_is_exact(
                request,
                row,
                stage=request.stage,
            )
            for row in values
        ):
            return []
        return values

    async def _media_artifact_checkpoint(
        self,
        request: SectionProductionRequest,
    ) -> dict[str, Any] | None:
        rows = await self._provenance_rows(request)
        artifacts: list[dict[str, Any]] = []
        for row in rows:
            url = self._artifact_url(request, row)
            if not url:
                return None
            if request.stage == "pictures" and (
                str(row.get("status") or "") != "done"
                or not str(row.get("image_url") or "").strip()
            ):
                return None
            if request.stage == "motion" and (
                str(row.get("motion_gate_status") or "") == "blocked"
                or not str(row.get("video_prompt") or "").strip()
            ):
                return None
            artifact = {
                "artifact_id": str(row.get("id") or ""),
                "artifact_url": url,
                "generation_method": str(
                    row.get("generation_method") or ""
                ),
                "reused": True,
                "actual_duration_ms": row.get("actual_duration_ms"),
                "assigned_duration_ms": row.get("assigned_duration_ms"),
                "timing_transform": _plain(row.get("timing_transform")),
                "timing_status": (
                    "exact"
                    if request.stage != "clips"
                    or row.get("actual_duration_ms")
                    == row.get("assigned_duration_ms")
                    else "needs_compositor"
                ),
            }
            if request.stage == "pictures":
                caption_card = canonical_caption_card(row.get("caption"))
                artifact["caption_card"] = caption_card
                artifact["caption_hash"] = canonical_hash(
                    {"caption_card": caption_card}
                )
            artifacts.append(artifact)
        if not artifacts:
            return None
        return {
            "scene_ids": list(request.scene_ids),
            "stage": request.stage,
            "artifacts": artifacts,
            "exact_seconds": request.exact_seconds,
            "render_mode": request.render_mode,
            "visual_profile": request.visual_profile,
            "image_density": _plain(request.image_density),
            "animation": _plain(request.animation),
            "camera": _plain(request.camera),
            "quality_laws": list(request.quality_laws),
            "reused_artifacts": True,
            "timing_status": (
                "needs_compositor"
                if request.stage == "clips"
                and any(
                    row.get("actual_duration_ms") != row.get("assigned_duration_ms")
                    for row in rows
                )
                else "exact"
            ),
        }

    async def _pictures(self, request: SectionProductionRequest) -> dict[str, Any]:
        scene = await self._scene_number(request)
        contract = request.payload()
        before_asset_ids = {
            str(row.get("id") or "")
            for row in await self._raw_asset_rows(request)
            if row.get("id")
        }
        if request.render_mode == "static_docu":
            from static_docu import generate_static_images_for_video

            result = await generate_static_images_for_video(
                request.video_id,
                self.tenant_id,
                only_scenes={scene},
                section_contract=contract,
            )
        else:
            from scripts.coverage_to_app import (
                CUSTOM_FILM_AUXILIARY_IMAGE_POLICY,
                generate_coverage_for_video,
            )

            # Enrich only the paid coverage sub-contract. Keeping this law out
            # of request.payload() preserves the durable operation request hash
            # for an interrupted child while forbidding any new auxiliary draw.
            contract["auxiliary_image_policy"] = copy.deepcopy(
                CUSTOM_FILM_AUXILIARY_IMAGE_POLICY
            )
            result = await generate_coverage_for_video(
                request.video_id,
                self.tenant_id,
                only_scenes={scene},
                section_contract=contract,
            )
        if not isinstance(result, Mapping) or result.get("status") != "completed":
            raise CustomFilmContractError(
                "Custom Film section pictures did not complete"
            )
        rows = await self._raw_asset_rows(request)
        expected_method = "static_docu" if request.render_mode == "static_docu" else "coverage"
        rows = [
            row
            for row in rows
            if str(row.get("id") or "") not in before_asset_ids
            if str(row.get("generation_method") or "") == expected_method
            and str(row.get("status") or "") == "done"
            and str(row.get("image_url") or "").strip()
        ]
        await self._record_media_provenance(request, rows)
        checkpoint = await self._media_artifact_checkpoint(request)
        if checkpoint is None:
            raise CustomFilmContractError(
                "Custom Film section pictures have no durable artifacts"
            )
        return checkpoint

    async def _motion(self, request: SectionProductionRequest) -> dict[str, Any]:
        scene = await self._scene_number(request)
        executor = await self._ready_executor()
        client = getattr(executor._pipeline, "anthropic", None)
        if client is None:
            raise CustomFilmContractError(
                "Tenant text-generation key is unavailable"
            )
        from scripts.coverage_to_app import _write_motion_prompts
        from shared.channel_profile import claude_model_for_direct_client

        picture_request = replace(request, stage="pictures")
        picture_rows = await self._section_completed_rows(
            picture_request,
            stage="pictures",
            expected=request.expected_still_images,
        )
        asset_ids = tuple(str(row["id"]) for row in picture_rows)
        request = replace(request, asset_ids=asset_ids)
        rows = await self._raw_asset_rows(request)
        rows_by_id = {str(row["id"]): row for row in rows}
        exact_rows = [rows_by_id[asset_id] for asset_id in asset_ids if asset_id in rows_by_id]
        provider_model = claude_model_for_direct_client(client)
        provider_models = {asset_id: provider_model for asset_id in asset_ids}
        await self._prepare_media_provenance(
            request,
            exact_rows,
            provider_models=provider_models,
        )
        written = await _write_motion_prompts(
            request.video_id,
            self.tenant_id,
            scene,
            client,
            model=provider_model,
            section_contract=request.payload(),
            asset_ids=list(asset_ids),
        )
        returned_prompts = _exact_motion_result(written, asset_ids)
        rows = await self._raw_asset_rows(request)
        rows_by_id = {str(row["id"]): row for row in rows}
        exact_rows = [rows_by_id[asset_id] for asset_id in asset_ids if asset_id in rows_by_id]
        _assert_current_provider_artifacts(
            "motion",
            exact_rows,
            asset_ids,
            returned_prompts,
        )
        await self._complete_media_provenance(
            request,
            exact_rows,
            provider_models=provider_models,
        )
        checkpoint = await self._media_artifact_checkpoint(request)
        if checkpoint is None:
            raise CustomFilmContractError(
                "Custom Film section motion prompts have no durable artifacts"
            )
        return checkpoint

    async def _clips(self, request: SectionProductionRequest) -> dict[str, Any]:
        scene = await self._scene_number(request)
        picture_request = replace(request, stage="pictures")
        picture_rows = await self._section_completed_rows(
            picture_request,
            stage="pictures",
            expected=request.expected_still_images,
        )
        asset_ids = tuple(str(row["id"]) for row in picture_rows)
        if len(asset_ids) != request.expected_animation_clips:
            raise CustomFilmContractError(
                "Custom Film approved clip count does not match picture assets"
            )
        request = replace(request, asset_ids=asset_ids)
        motion_request = replace(request, stage="motion")
        motion_rows = await self._section_completed_rows(
            motion_request,
            stage="motion",
            expected=request.expected_still_images,
        )
        if tuple(str(row["id"]) for row in motion_rows) != asset_ids:
            raise CustomFilmContractError(
                "Custom Film clip inputs do not match exact motion assets"
            )
        durations = _allocate_seconds(request.exact_seconds, len(asset_ids))
        duration_by_id = dict(zip(asset_ids, durations))
        import database

        pool = await database.get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                for asset_id, duration in duration_by_id.items():
                    updated = await conn.execute(
                        """UPDATE assets
                           SET duration_seconds = $4,
                               assigned_video_duration = $4,
                               updated_at = now()
                           WHERE tenant_id = $1::uuid AND video_id = $2::uuid
                             AND id = $3::uuid""",
                        self.tenant_id,
                        request.video_id,
                        asset_id,
                        duration,
                    )
                    if not str(updated).endswith(" 1"):
                        raise CustomFilmContractError(
                            "Custom Film clip timing could not be persisted"
                        )
        rows = await self._raw_asset_rows(request)
        rows_by_id = {str(row["id"]): row for row in rows}
        exact_rows = [rows_by_id[asset_id] for asset_id in asset_ids if asset_id in rows_by_id]
        await self._prepare_media_provenance(
            request,
            exact_rows,
            durations=duration_by_id,
        )
        executor = await self._ready_executor()
        result = await executor.run_clip_generation(
            request.video_id,
            asset_ids=list(asset_ids),
            section_contract=request.payload(),
        )
        returned = _exact_clip_result(result, asset_ids)
        rows = await self._raw_asset_rows(request)
        rows_by_id = {str(row["id"]): row for row in rows}
        exact_rows = [rows_by_id[asset_id] for asset_id in asset_ids if asset_id in rows_by_id]
        provider_models = {
            asset_id: str(returned.get(asset_id, {}).get("provider_model") or "")
            for asset_id in asset_ids
        }
        actual_durations = {
            asset_id: returned.get(asset_id, {}).get("duration_seconds")
            for asset_id in asset_ids
        }
        _assert_current_provider_artifacts(
            "clips",
            exact_rows,
            asset_ids,
            returned,
        )
        await self._complete_media_provenance(
            request,
            exact_rows,
            provider_models=provider_models,
            durations=duration_by_id,
            actual_durations=actual_durations,
        )
        checkpoint = await self._media_artifact_checkpoint(request)
        if checkpoint is None:
            raise CustomFilmContractError(
                "Custom Film section clips have no durable artifacts"
            )
        return checkpoint

    async def _script(self, request: SectionProductionRequest) -> dict[str, Any]:
        executor = await self._ready_executor()
        video = await executor._get_video(request.video_id)
        if not video:
            raise CustomFilmContractError("Custom Film video not found")
        client = getattr(executor._pipeline, "anthropic", None)
        if client is None:
            raise CustomFilmContractError(
                "Tenant text-generation key is unavailable"
            )
        from script.brief_translator.script_generator import (
            generate_script,
            validate_script,
        )
        from shared.profiles.script import load_script_profile

        profile = load_script_profile(request.script_profile)
        video_title = str(
            video.get("video_title") or video.get("headline") or "Untitled"
        )
        approved_context = f"{request.role}\n{request.purpose}"
        config = _ExactSectionConfig(request.exact_seconds)
        approved_contract = _script_approved_contract(
            role=request.role,
            purpose=request.purpose,
            exact_seconds=request.exact_seconds,
            config=config,
        )
        story_arc_guidance = _script_story_arc_guidance(
            request.story_arc,
            current_order_index=request.order_index,
        )
        role_structure_law = _script_role_structure_law(request.role)
        brief = {
            "headline": request.purpose,
            "thesis": request.purpose,
            "executive_hook": f"{request.role}: {request.purpose}",
            "writer_guidance": (
                f"Write only section {request.order_index + 1}. Its role is "
                f"'{request.role}' and its exact purpose is: {request.purpose}. "
                f"The spoken result must fit exactly {request.exact_seconds} seconds.\n"
                + approved_contract
                + "\n"
                + (story_arc_guidance + "\n" if story_arc_guidance else "")
                + f"Language mode is '{request.language.get('mode')}', dialogue "
                f"audio is '{request.dialogue_audio}', and dubbing mode is "
                f"'{request.dubbing.get('mode')}'. "
                + (
                    "Write explicit bilingual speaker turns whose performed "
                    "audio can be voice-locked with speech-to-speech. "
                    if request.language.get("mode") == "bilingual"
                    else (
                        "Write single-language speaker turns for native in-clip "
                        "performance; do not add a separate narrator track. "
                        if request.language.get("mode")
                        == "simple_single_language"
                        else "Write this section as narrator-led voice-over. "
                    )
                )
                + "The approved quality laws are: "
                + ", ".join(request.quality_laws)
                + "."
            ),
        }
        generated = await generate_script(
            client,
            brief,
            config=config,
            profile=profile,
        )
        script_text = str(generated.get("script") or "").strip()
        if not script_text:
            raise CustomFilmContractError(
                "Custom Film script provider returned no section script"
            )
        import script_quality

        async def repair_deterministic_issues(
            current_text: str,
            current_issues: list[str],
        ) -> tuple[str, list[str], int, dict[str, Any]]:
            rounds = 0
            validation: dict[str, Any] = (
                generated.get("validation")
                if isinstance(generated.get("validation"), dict)
                else {}
            )
            while current_issues and rounds < _SCRIPT_REPAIR_ATTEMPTS:
                edited = await script_quality.edit_draft_with_violations(
                    [{"scene": 1, "text": current_text}],
                    [
                        *current_issues,
                        (
                            "EDIT CONSTRAINTS — these remain mandatory on every "
                            "repair:\n" + approved_contract
                        ),
                    ],
                    client=client,
                )
                rounds += 1
                if not edited:
                    break
                current_text = str(edited[0].get("text") or "").strip()
                validation = validate_script(
                    current_text,
                    config=config,
                    profile=profile,
                )
                current_issues = _script_grounding_issues(
                    current_text,
                    approved_context=approved_context,
                    config=config,
                    generator_validation=validation,
                )
            return current_text, current_issues, rounds, validation

        deterministic_issues = _script_grounding_issues(
            script_text,
            approved_context=approved_context,
            config=config,
            generator_validation=generated.get("validation"),
        )
        (
            script_text,
            deterministic_issues,
            deterministic_edit_rounds,
            final_validation,
        ) = await repair_deterministic_issues(
            script_text,
            deterministic_issues,
        )
        if deterministic_issues:
            raise CustomFilmContractError(
                "Custom Film section script failed approved timing/grounding "
                "before voice or imagery: " + "; ".join(deterministic_issues)
            )

        rules_text = "\n".join(
            (
                "approved_purpose_grounding: The script must stay entirely "
                f"within this approved section context: {approved_context}. "
                "Reject any unrelated person, place, organization, event, date, "
                "number, case study, conspiracy, or adjacent topic.",
                "visual_story_readiness: The script must tell a coherent, "
                "specific visual story. Each beat must provide concrete action, "
                "evidence, environment, character behavior, or an observable "
                "change that the approved stills or clips can show; reject generic "
                "exposition, disconnected claims, and non-visual filler.",
                "role_structure_quality: Apply this film-agnostic structural "
                f"law for the approved '{request.role}' role: "
                f"{role_structure_law} The ordered story arc may guide continuity "
                "and handoff only; it cannot authorize facts from another section.",
            )
        )
        grade = None
        quality_edit_rounds = 0
        quality_passes = 0
        converged = False
        for _ in range(_SCRIPT_CONVERGENCE_PASSES):
            critic_input_scenes = [{"scene": 1, "text": script_text}]
            quality_result = await script_quality.run_critique_and_edit(
                self.tenant_id,
                request.video_id,
                critic_input_scenes,
                client=client,
                niche=request.role,
                title=request.purpose,
                hook=f"{request.role}: {request.purpose}",
                rules_text=rules_text,
                severity_by_rule={
                    "approved_purpose_grounding": "hard_gate",
                    "visual_story_readiness": "hard_gate",
                    "role_structure_quality": "hard_gate",
                },
                max_edit_rounds=_SCRIPT_REPAIR_ATTEMPTS,
                edit_constraints=[
                    (
                        "EDIT CONSTRAINTS — these remain mandatory on every "
                        "repair:\n" + approved_contract
                    )
                ],
            )
            grade, final_scenes, edit_rounds = _validated_early_quality_result(
                quality_result,
                original_scenes=critic_input_scenes,
            )
            quality_passes += 1
            quality_edit_rounds += edit_rounds
            script_text = str(final_scenes[0].get("text") or "").strip()
            final_validation = validate_script(
                script_text,
                config=config,
                profile=profile,
            )
            final_issues = _script_grounding_issues(
                script_text,
                approved_context=approved_context,
                config=config,
                generator_validation=final_validation,
            )
            if not final_issues:
                converged = True
                break
            (
                script_text,
                final_issues,
                repair_rounds,
                final_validation,
            ) = await repair_deterministic_issues(
                script_text,
                final_issues,
            )
            deterministic_edit_rounds += repair_rounds
            if final_issues:
                raise CustomFilmContractError(
                    "Custom Film section script failed visual-story quality "
                    "before voice or imagery: "
                    + "; ".join(dict.fromkeys(final_issues))
                )
        if not converged or grade is None:
            raise CustomFilmContractError(
                "Custom Film section script quality gates did not converge "
                "before voice or imagery"
            )
        scene_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{request.operation_id}:section-script:0",
            )
        )
        pool = await __import__("database").get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO scripts
                     (id, tenant_id, video_id, scene, scene_text, title,
                      script_status, voice_id, script_validation)
                   VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6,
                           'Create', $7, $8)
                   ON CONFLICT (id) DO UPDATE
                     SET scene_text = EXCLUDED.scene_text,
                         script_validation = EXCLUDED.script_validation,
                         updated_at = now()
                   WHERE scripts.tenant_id = EXCLUDED.tenant_id
                     AND scripts.video_id = EXCLUDED.video_id
                   RETURNING id""",
                scene_id,
                self.tenant_id,
                request.video_id,
                request.order_index + 1,
                script_text,
                video_title,
                "1SM7GgM6IMuvQlz2BwM3",
                json.dumps(
                    {
                        "custom_film": {
                            "runtime_hash": request.runtime_hash,
                            "section_id": request.section_id,
                            "exact_seconds": request.exact_seconds,
                            "script_profile": request.script_profile,
                            "preflight": {
                                "verdict": grade.verdict,
                                "score": grade.score,
                                "deterministic_edit_rounds": (
                                    deterministic_edit_rounds
                                ),
                                "quality_edit_rounds": quality_edit_rounds,
                                "quality_passes": quality_passes,
                            },
                        },
                        "shared_validation": final_validation,
                    },
                    sort_keys=True,
                ),
            )
            if not row or str(row.get("id") or "") != scene_id:
                raise CustomFilmContractError(
                    "Custom Film section script could not be durably saved"
                )
            await conn.execute(
                """UPDATE videos v
                   SET script = assembled.script, updated_at = now()
                   FROM (
                     SELECT video_id,
                            string_agg(scene_text, E'\\n\\n' ORDER BY scene) AS script
                     FROM scripts
                     WHERE tenant_id = $1::uuid AND video_id = $2::uuid
                     GROUP BY video_id
                   ) assembled
                   WHERE v.tenant_id = $1::uuid AND v.id = assembled.video_id""",
                self.tenant_id,
                request.video_id,
            )
        return {
            "scene_ids": [scene_id],
            "scene_text_hashes": [
                {
                    "scene_id": scene_id,
                    "scene_text_hash": canonical_hash(
                        {"scene_id": scene_id, "scene_text": script_text}
                    ),
                }
            ],
            "exact_seconds": request.exact_seconds,
            "script_profile": request.script_profile,
            "role": request.role,
            "purpose": request.purpose,
            "quality_verdict": grade.verdict,
            "quality_score": grade.score,
        }

    async def _scene_rows(
        self, request: SectionProductionRequest
    ) -> list[dict[str, Any]]:
        import database

        pool = await database.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, scene, scene_text, voice_id, voice_status,
                          voice_over_url
                   FROM scripts
                   WHERE tenant_id = $1::uuid AND video_id = $2::uuid
                     AND id = ANY($3::uuid[])
                   ORDER BY scene""",
                self.tenant_id,
                request.video_id,
                list(request.scene_ids),
            )
        ordered = [dict(row) for row in rows]
        if tuple(str(row.get("id") or "") for row in ordered) != request.scene_ids:
            raise CustomFilmContractError(
                "Custom Film section assignments are missing or reordered; "
                "no provider work was started"
            )
        return ordered

    @staticmethod
    def _voice_artifact_identity(
        request: SectionProductionRequest,
        scene_id: str,
    ) -> tuple[str, str, str]:
        artifact_hash = canonical_hash(
            {
                "operation_id": request.operation_id,
                "scene_id": scene_id,
                "runtime_hash": request.runtime_hash,
            }
        )
        return (
            artifact_hash,
            f"custom-film-voice:{artifact_hash}",
            f"custom-film-voice-{artifact_hash}.mp3",
        )

    async def _checkpoint_voice_row(
        self,
        request: SectionProductionRequest,
        scene_id: str,
        persistent_url: str,
        artifact_status: str,
    ) -> None:
        import database

        pool = await database.get_pool()
        async with pool.acquire() as conn:
            updated = await conn.execute(
                """UPDATE scripts
                   SET voice_over_url = $4, voice_status = $5,
                       script_status = 'Finished', updated_at = now()
                   WHERE tenant_id = $1::uuid AND video_id = $2::uuid
                     AND id = $3::uuid
                     AND (
                       voice_status IS NULL
                       OR voice_status = $5
                     )""",
                self.tenant_id,
                request.video_id,
                scene_id,
                persistent_url,
                artifact_status,
            )
        if not str(updated).endswith(" 1"):
            raise CustomFilmContractError(
                "Custom Film section voice artifact identity changed"
            )

    async def _voice_artifact_checkpoint(
        self,
        request: SectionProductionRequest,
    ) -> dict[str, Any] | None:
        rows = await self._scene_rows(request)
        if len(rows) != 1:
            raise CustomFilmContractError(
                "Custom Film child voice operation must own exactly one scene"
            )
        row = rows[0]
        scene_id = str(row["id"])
        artifact_hash, artifact_status, filename = (
            self._voice_artifact_identity(request, scene_id)
        )
        if (
            str(row.get("voice_status") or "") == artifact_status
            and str(row.get("voice_over_url") or "").strip()
        ):
            return {
                "scene_ids": [scene_id],
                "voiced_scene_ids": [scene_id],
                "artifact_id": artifact_hash,
                "artifact_url": str(row["voice_over_url"]),
                "reused_artifact": True,
                "exact_seconds": request.exact_seconds,
            }
        executor = await self._ready_executor()
        folder = executor._pipeline.google.get_or_create_folder(
            f"custom-film-{request.video_id}"
        )
        existing = executor._pipeline.google.search_file(filename, folder["id"])
        if not existing or not existing.get("id"):
            return None
        persistent_url = (
            f"https://drive.google.com/uc?id={existing['id']}&export=download"
        )
        await self._checkpoint_voice_row(
            request,
            scene_id,
            persistent_url,
            artifact_status,
        )
        return {
            "scene_ids": [scene_id],
            "voiced_scene_ids": [scene_id],
            "artifact_id": artifact_hash,
            "artifact_url": persistent_url,
            "reused_artifact": True,
            "exact_seconds": request.exact_seconds,
        }

    async def _voice(
        self,
        request: SectionProductionRequest,
        *,
        on_submitted: SubmittedCallback | None = None,
        provider_operation_id: str | None = None,
    ) -> dict[str, Any]:
        rows = await self._scene_rows(request)
        if request.dialogue_audio == "grok_native":
            return {
                "scene_ids": list(request.scene_ids),
                "voice_behavior": "performed_in_clip",
                "language": _plain(request.language),
                "dubbing": _plain(request.dubbing),
                "exact_seconds": request.exact_seconds,
            }
        executor = await self._ready_executor()
        voice_client = getattr(executor._pipeline, "elevenlabs", None)
        if voice_client is None:
            raise CustomFilmContractError("Tenant voice key is unavailable")
        from voice.run import narration_text

        dialogue_mode = (
            "character_dialogue"
            if str(request.segmentation.get("mode") or "") == "speaker_turn"
            else ""
        )
        voiced: list[str] = []
        artifacts: list[dict[str, Any]] = []
        total_chars = 0
        if len(rows) != 1:
            raise CustomFilmContractError(
                "Custom Film child voice operation must own exactly one scene"
            )
        for row in rows:
            artifact_hash, artifact_status, filename = (
                self._voice_artifact_identity(request, str(row["id"]))
            )
            if (
                str(row.get("voice_status") or "") == artifact_status
                and str(row.get("voice_over_url") or "").strip()
            ):
                voiced.append(str(row["id"]))
                artifacts.append(
                    {
                        "scene_id": str(row["id"]),
                        "artifact_id": artifact_hash,
                        "artifact_url": str(row["voice_over_url"]),
                        "reused": True,
                    }
                )
                continue
            text = narration_text(str(row.get("scene_text") or ""), dialogue_mode)
            if not text:
                continue
            if provider_operation_id:
                queried = await voice_client.query_task(provider_operation_id)
                audio_content = queried.get("audio_content")
            else:
                audio_path = await voice_client.generate_and_wait(
                    text,
                    str(row.get("voice_id") or "") or None,
                    task_id_callback=on_submitted,
                )
                if not audio_path:
                    raise CustomFilmContractError(
                        "Custom Film voice provider returned no audio"
                    )
                audio_content = await voice_client.download_audio(audio_path)
            if not audio_content:
                raise CustomFilmContractError(
                    "Custom Film voice provider returned no audio"
                )
            folder = executor._pipeline.google.get_or_create_folder(
                f"custom-film-{request.video_id}"
            )
            existing = executor._pipeline.google.search_file(
                filename,
                folder["id"],
            )
            uploaded = existing or executor._pipeline.google.upload_audio(
                audio_content, filename, folder["id"]
            )
            if not uploaded or not uploaded.get("id"):
                raise CustomFilmContractError(
                    "Custom Film section voice could not be durably stored"
                )
            persistent_url = (
                f"https://drive.google.com/uc?id={uploaded['id']}&export=download"
            )
            await self._checkpoint_voice_row(
                request,
                str(row["id"]),
                persistent_url,
                artifact_status,
            )
            voiced.append(str(row["id"]))
            artifacts.append(
                {
                    "scene_id": str(row["id"]),
                    "artifact_id": artifact_hash,
                    "artifact_url": persistent_url,
                    "reused": bool(existing),
                }
            )
            total_chars += len(text)
        return {
            "scene_ids": list(request.scene_ids),
            "voiced_scene_ids": voiced,
            "voice_behavior": (
                "narration_plus_clip_speech_to_speech"
                if bool(request.dubbing.get("enabled"))
                else "narration"
            ),
            "language": _plain(request.language),
            "dubbing": _plain(request.dubbing),
            "dialogue_audio": request.dialogue_audio,
            "exact_seconds": request.exact_seconds,
            "total_chars": total_chars,
            "artifacts": artifacts,
        }

    async def _quality(self, request: SectionProductionRequest) -> dict[str, Any]:
        rows = await self._scene_rows(request)
        timing_evidence = await self._quality_media_preflight(request)
        executor = await self._ready_executor()
        client = getattr(executor._pipeline, "anthropic", None)
        if client is None:
            raise CustomFilmContractError(
                "Tenant text-generation key is unavailable"
            )
        import script_quality

        script_text = "\n\n".join(str(row.get("scene_text") or "") for row in rows)
        rules_text = "\n".join(
            f"{law}: This approved section must satisfy {law.replace('_', ' ')}."
            for law in request.quality_laws
        )
        severity = {law: "hard_gate" for law in request.quality_laws}
        grade = await script_quality.critique_script(
            self.tenant_id,
            request.video_id,
            {
                "script": script_text,
                "title": request.purpose,
                "niche": request.role,
            },
            rules_text=rules_text,
            severity_by_rule=severity,
            client=client,
        )
        if "grade unavailable - failed open" in grade.failing_gates:
            raise CustomFilmContractError(
                "Custom Film section quality laws could not be evaluated"
            )
        if grade.needs_revision:
            raise CustomFilmContractError(
                "Custom Film section failed approved quality laws: "
                + "; ".join(grade.violations)
            )
        return {
            "scene_ids": list(request.scene_ids),
            "quality_laws": list(request.quality_laws),
            "verdict": grade.verdict,
            "score": grade.score,
            "exact_seconds": request.exact_seconds,
            **timing_evidence,
        }

    async def _quality_media_preflight(
        self,
        request: SectionProductionRequest,
    ) -> dict[str, Any]:
        required_stages = ["pictures"]
        if bool(request.animation.get("enabled")):
            required_stages.extend(("motion", "clips"))
        import database

        pool = await database.get_pool()
        stage_assets: dict[str, tuple[str, ...]] = {}
        assigned_duration_ms = 0
        timing_transforms: list[dict[str, Any]] = []
        async with pool.acquire() as conn:
            for stage in required_stages:
                rows = await conn.fetch(
                    """SELECT p.asset_id, p.actual_duration_ms,
                              p.assigned_duration_ms, p.timing_transform,
                              a.image_url, a.status, a.video_prompt, a.caption,
                              a.drive_image_url, a.motion_gate_status,
                              a.video_clip_url, a.image_model, a.model_used,
                              a.duration_seconds, a.assigned_video_duration,
                              a.video_duration,
                              a.generation_method,
                              p.artifact_url_hash AS provenance_artifact_hash,
                              p.provider_model AS provenance_provider_model,
                              p.request_hash AS provenance_request_hash,
                              p.generation_method AS provenance_generation_method
                       FROM custom_film_asset_provenance p
                       JOIN assets a
                         ON (a.tenant_id, a.video_id, a.id)
                          = (p.tenant_id, p.video_id, p.asset_id)
                       WHERE p.tenant_id = $1::uuid
                         AND p.video_id = $2::uuid
                         AND p.plan_id = $3::uuid
                         AND p.section_id = $4::uuid
                         AND p.runtime_hash = $5
                         AND p.stage = $6
                         AND p.section_contract_hash = $7
                         AND p.status = 'completed'
                       ORDER BY p.asset_id""",
                    self.tenant_id,
                    request.video_id,
                    request.plan_id,
                    request.section_id,
                    request.runtime_hash,
                    stage,
                    self._section_contract_hash(request, stage=stage),
                )
                values = [dict(row) for row in rows]
                expected = (
                    request.expected_animation_clips
                    if stage == "clips"
                    else request.expected_still_images
                )
                if len(values) != expected:
                    raise CustomFilmContractError(
                        f"Custom Film quality preflight found incomplete {stage}"
                    )
                if any(
                    not self._completed_provenance_is_exact(
                        request,
                        row,
                        stage=stage,
                    )
                    for row in values
                ):
                    raise CustomFilmContractError(
                        f"Custom Film quality preflight found tampered {stage}"
                    )
                if stage == "pictures" and any(
                    str(row.get("status") or "") != "done"
                    or not str(row.get("image_url") or "").strip()
                    for row in values
                ):
                    raise CustomFilmContractError(
                        "Custom Film quality preflight found invalid pictures"
                    )
                if stage == "motion" and any(
                    str(row.get("motion_gate_status") or "") == "blocked"
                    or not str(row.get("video_prompt") or "").strip()
                    for row in values
                ):
                    raise CustomFilmContractError(
                        "Custom Film quality preflight found invalid motion"
                    )
                if stage == "clips":
                    if any(
                        not str(row.get("video_clip_url") or "").strip()
                        or row.get("actual_duration_ms") is None
                        or row.get("assigned_duration_ms") is None
                        or not isinstance(row.get("timing_transform"), Mapping)
                        for row in values
                    ):
                        raise CustomFilmContractError(
                            "Custom Film quality preflight found invalid clips"
                        )
                    assigned_duration_ms = sum(
                        int(row["assigned_duration_ms"]) for row in values
                    )
                    timing_transforms = [
                        {
                            "asset_id": str(row["asset_id"]),
                            "actual_duration_ms": int(row["actual_duration_ms"]),
                            "assigned_duration_ms": int(row["assigned_duration_ms"]),
                            "transform": _plain(row["timing_transform"]),
                        }
                        for row in values
                    ]
                stage_assets[stage] = tuple(str(row["asset_id"]) for row in values)
        picture_assets = stage_assets["pictures"]
        if any(stage_assets[stage] != picture_assets for stage in required_stages[1:]):
            raise CustomFilmContractError(
                "Custom Film media stages do not own the same approved asset set"
            )
        if "clips" in required_stages and assigned_duration_ms != (
            request.exact_seconds * 1000
        ):
            raise CustomFilmContractError(
                "Custom Film clip timing does not equal exact section seconds"
            )
        timing_status = (
            "needs_compositor"
            if any(
                row["actual_duration_ms"] != row["assigned_duration_ms"]
                for row in timing_transforms
            )
            else "exact"
        )
        return {
            "timing_status": timing_status,
            "timing_transforms": timing_transforms,
        }
