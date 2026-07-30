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
import math
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


def _normalize_provenance_row(value: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize JSONB values returned by the unconfigured asyncpg pool.

    ``database.get_pool()`` intentionally uses asyncpg's default codecs, which
    return JSON/JSONB columns as strings.  Test doubles commonly return decoded
    dictionaries, so provenance verification must accept both representations
    while continuing to fail closed on malformed or non-object JSON.
    """
    row = dict(value)
    timing_transform = row.get("timing_transform")
    if isinstance(timing_transform, str):
        try:
            timing_transform = json.loads(timing_transform)
        except (json.JSONDecodeError, TypeError):
            timing_transform = None
    row["timing_transform"] = (
        dict(timing_transform)
        if isinstance(timing_transform, Mapping)
        else None
    )
    return row


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
        # Quality needs the same approved film-world, carry, and visual-plan
        # context used by the script gate. Keep it out of the serialized
        # non-script payload: runtime_hash already binds the immutable envelope,
        # so restoring this in-memory context does not churn operation or
        # provenance identities.
        story_arc=(
            adapter.story_arc
            if adapter.stage in {"script", "quality"}
            else ()
        ),
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


class _AVSectionConfig(_ExactSectionConfig):
    """Generator targets aligned with the deterministic sparse-speech gate."""

    def __init__(self, exact_seconds: int):
        super().__init__(exact_seconds)
        self.script_min_words = max(3, round(exact_seconds * 0.25))
        self.script_max_words = max(
            self.script_min_words,
            round(exact_seconds * 2.2),
        )
        self.total_script_words = round(
            (self.script_min_words + self.script_max_words) / 2
        )
        self.words_per_clip = max(
            1,
            round(self.total_script_words / self.total_clips),
        )


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
_SCRIPT_FENCE_PATTERN = re.compile(r"^\s*(?:`{3,}|~{3,})[^\r\n]*$")
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
_SCRIPT_GREEK_DESIGNATIONS = frozenset(
    {
        "alpha",
        "beta",
        "gamma",
        "delta",
        "epsilon",
        "zeta",
        "theta",
        "iota",
        "kappa",
        "lambda",
        "omicron",
        "sigma",
        "omega",
    }
)
_SCRIPT_NATO_DESIGNATIONS = frozenset(
    {
        "alfa",
        "alpha",
        "bravo",
        "charlie",
        "delta",
        "echo",
        "foxtrot",
        "golf",
        "hotel",
        "india",
        "juliett",
        "kilo",
        "lima",
        "mike",
        "november",
        "oscar",
        "papa",
        "quebec",
        "romeo",
        "sierra",
        "tango",
        "uniform",
        "victor",
        "whiskey",
        "x-ray",
        "xray",
        "yankee",
        "zulu",
    }
)
_SCRIPT_DESIGNATION_CONTEXT_WORDS = frozenset(
    {
        "branch",
        "channel",
        "circuit",
        "code",
        "designation",
        "identifier",
        "node",
        "panel",
        "phase",
        "sector",
        "sequence",
        "site",
        "station",
        "team",
        "unit",
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


def _script_designation_word_anchors(text: str) -> set[str]:
    words = [
        token.casefold()
        for token in _SCRIPT_WORD_PATTERN.findall(text)
    ]
    anchors = {
        word for word in words if word in _SCRIPT_GREEK_DESIGNATIONS
    }
    for index, word in enumerate(words):
        if word not in _SCRIPT_NATO_DESIGNATIONS:
            continue
        before = words[index - 1] if index else ""
        after = words[index + 1] if index + 1 < len(words) else ""
        if (
            before in _SCRIPT_DESIGNATION_CONTEXT_WORDS
            or after in _SCRIPT_DESIGNATION_CONTEXT_WORDS
        ):
            anchors.add(word)
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
            "Open on the first decisive approved action or decision. Resolve the "
            "approved problem through multiple dependent visible actions or "
            "decisions across distinct beats; every step must receive observable "
            "confirmation before the next step begins, and the chain must "
            "escalate toward the approved result. Convert concrete evidence or "
            "state earned in earlier approved sections into the actions that "
            "solve the problem. When the current purpose brings prior evidence "
            "to a conclusion, each distinct approved evidence type, object, or "
            "signal must visibly change a different decision or action; do not "
            "collapse them all into one map, interface, or explanation. "
            "Repeated console commands, repeated indicator "
            "changes, ordinal steps, or parallel operators performing the same "
            "action are list-like repetition, not escalation. Each middle beat "
            "must materially change the kind of work on screen: apply a distinct "
            "approved clue or state, force a visibly different decision or "
            "action, and show its consequence before continuing. Do not invent "
            "technical labels, component counts, sectors, geographic "
            "subdivisions, directional qualifiers, or obstacles merely to "
            "manufacture steps. Use unlabeled relative visual state when the "
            "approved world does not name the underlying geography or system. "
            "Specificity must come from performance, spatial behavior, light, "
            "sound, and observable state change, not from specializing a generic "
            "approved noun into an unapproved subtype, component, measurement, "
            "or technical mechanism. When the purpose names a filmable physical "
            "resolution action, show characters physically performing that "
            "literal action in at least one middle beat; maps, screens, commands, "
            "overlays, and indicators may guide or confirm it but cannot replace "
            "it. "
            "A single switch, button, command, automatic "
            "recovery, or montage must never resolve the whole problem. The "
            "final beat must visibly prove the approved result and hand off "
            "cleanly without a generic renewed threat."
        ),
        "closing": (
            "Open on the earned final story image. When the approved purpose "
            "authorizes planning, assembly, or production work, reveal it through "
            "concrete cinematic transformation or match cuts into the actual "
            "artifacts and work, then return to the completed work or final "
            "image. Land on one decisive visual payoff with sparse connective "
            "VO. Never use a list recap, literal framework or schema jargon, "
            "on-screen track tags, carry-state, beat, or section labels, abstract "
            "rotating diagrams, or narration explaining the story's structure "
            "unless those exact constructs are explicitly approved subject matter. "
            "Introduce no new factual claim or generic renewed threat."
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
            "escalation, and the handoff between sections. Factual authorization "
            "comes only from the separate approved section/shared-film-world "
            "contracts, never from this structural block by itself. Other "
            "sections' purposes do not authorize facts through this structural "
            "block."
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


def _script_approved_visual_plan_contract(
    story_arc: tuple[Mapping[str, Any], ...],
    *,
    current_order_index: int,
) -> str:
    """Expose already-approved orchestration as film grammar, not new facts."""

    current = next(
        (
            item
            for item in story_arc
            if int(item.get("order_index", -1)) == current_order_index
        ),
        None,
    )
    if current is None:
        return ""
    beats = current.get("approved_visual_beats")
    if not isinstance(beats, (list, tuple)) or not beats:
        return ""
    lines = [
        "=== APPROVED VISUAL BEAT PLAN ===",
        (
            "These plan-selected components are mandatory screen-language "
            "grounding for this section. Use them in order to shape cinematic "
            "coverage and transitions, while the approved purpose/shared world "
            "remain the only source of story facts. Translate component names "
            "into diegetic shots, match cuts, layered visual motifs, and "
            "observable action. Never speak, caption, diagram, or expose raw "
            "component names, capability identifiers, handoff tokens, or "
            "orchestration schema. A map, timeline, network, evidence, product, "
            "or title intent authorizes that visual form only; it does not "
            "authorize new locations, directional geography, dates, labels, "
            "quantities, technical components, or story facts. When those facts "
            "are absent, use unlabeled patterns, match cuts, and relative "
            "observable changes."
        ),
    ]
    for index, raw_beat in enumerate(beats, start=1):
        if not isinstance(raw_beat, Mapping):
            continue
        intents = ", ".join(
            str(value)
            for value in raw_beat.get("intents", ())
            if str(value).strip()
        )
        capabilities = ", ".join(
            str(value)
            for value in raw_beat.get("motion_capabilities", ())
            if str(value).strip()
        )
        lines.append(
            f"VISUAL PLAN BEAT {index}: "
            f"narrative function={str(raw_beat.get('narrative_function') or '')}; "
            f"presentation={str(raw_beat.get('presentation') or '')}; "
            f"visual intents={intents}; motion grammar={capabilities}; "
            f"transition={str(raw_beat.get('transition') or '')}; "
            f"handoff={str(raw_beat.get('handoff') or '')}"
        )
    lines.extend(
        (
            (
                "FIDELITY LAW: The screenplay may subdivide timing into more "
                "shots, but it must preserve this ordered visual progression. "
                "These are macro visual phases, never a one-to-one required "
                "count of timed screenplay beats. Layer their visual grammar "
                "across the actions; a map, timeline, overlay, transform, or "
                "signal pulse may clarify causal state but must never perform "
                "or replace the characters' decisive action. "
                "A generic substitute that ignores these approved components "
                "fails visual-story quality."
            ),
            "=== END APPROVED VISUAL BEAT PLAN ===",
        )
    )
    return "\n".join(lines)


def _script_shared_film_world_contract(
    story_arc: tuple[Mapping[str, Any], ...],
    *,
    current_order_index: int,
) -> tuple[str, str]:
    """Compile plan-authored facts into a shared world with ordered reveals."""

    if not story_arc:
        return "", ""
    ordered = sorted(
        story_arc,
        key=lambda item: int(item.get("order_index", -1)),
    )
    factual_context = "\n".join(
        str(item.get("purpose") or "").strip()
        for item in ordered
        if str(item.get("purpose") or "").strip()
    )
    lines = [
        "=== APPROVED SHARED FILM WORLD ===",
        (
            "The people, places, organizations, objects, signals, evidence, "
            "events, and explicit numeric/date facts named in the approved plan "
            "purposes below belong to the film's approved world. They may be "
            "reused for concrete cinematic continuity; add no adjacent fact."
        ),
    ]
    for item in ordered:
        order = int(item.get("order_index", -1))
        marker = " [CURRENT SECTION]" if order == current_order_index else ""
        lines.append(
            f"SECTION {order + 1}{marker} APPROVED PURPOSE: "
            f"{str(item.get('purpose') or '')}"
        )
    lines.extend(
        (
            (
                "PROGRESSION LAW: Shared-world existence is not permission to "
                "reveal a later section's discovery, outcome, explanation, or "
                "payoff early. Use only what the current approved purpose needs, "
                "avoid duplication, and carry concrete state forward."
            ),
            "=== END APPROVED SHARED FILM WORLD ===",
        )
    )
    return "\n".join(lines), factual_context


def _script_story_arc_continuity_law(
    story_arc: tuple[Mapping[str, Any], ...],
    *,
    current_order_index: int,
) -> str:
    """Turn the structure-only arc into an explicit ending obligation."""

    if not story_arc:
        return ""
    ordered_arc = sorted(
        story_arc,
        key=lambda item: int(item.get("order_index", -1)),
    )
    next_section = next(
        (
            item
            for item in ordered_arc
            if int(item.get("order_index", -1)) > current_order_index
        ),
        None,
    )
    if next_section is None:
        ending_law = (
            "CONTINUITY ENDING LAW: This is the final approved section. Land "
            "the earned final image or takeaway without a generic threat, new "
            "open loop, or new factual claim."
        )
    else:
        next_order = int(next_section.get("order_index", -1))
        next_role = str(next_section.get("role") or "")
        next_purpose = str(next_section.get("purpose") or "")
        ending_law = (
            "CONTINUITY ENDING LAW: End this current section with a clean "
            f"structural handoff toward SECTION {next_order + 1}, whose approved "
            f"ROLE is '{next_role}' and PURPOSE is '{next_purpose}'. Use that "
            "next purpose only as the direction of the handoff. Shared-world "
            "people, places, objects, and events may remain visibly continuous. "
            "Do not state, preview, duplicate, or prematurely resolve the later section's "
            "discovery, explanation, outcome, or payoff. Reject a generic threat, "
            "warning, or open loop that does not earn this handoff."
        )
    return ending_law


def _script_av_carry_binding(
    story_arc: tuple[Mapping[str, Any], ...],
    *,
    current_order_index: int,
) -> tuple[str, str, str]:
    """Derive identity-safe cross-section state from the hashed ordered plan."""

    ordered = sorted(
        story_arc,
        key=lambda item: int(item.get("order_index", -1)),
    )
    current_position = next(
        (
            index
            for index, item in enumerate(ordered)
            if int(item.get("order_index", -1)) == current_order_index
        ),
        None,
    )
    if current_position is None:
        return "", "", ""
    current_purpose = str(ordered[current_position].get("purpose") or "").strip()
    required_carry_in = (
        f"approved opening state — {current_purpose}"
        if current_position == 0
        else f"approved transition state — {current_purpose}"
    )
    if current_position + 1 < len(ordered):
        next_purpose = str(
            ordered[current_position + 1].get("purpose") or ""
        ).strip()
        required_carry_out = f"approved transition state — {next_purpose}"
    else:
        required_carry_out = f"approved final state — {current_purpose}"
    contract = "\n".join(
        (
            "=== APPROVED EXACT CARRY BINDING ===",
            f"REQUIRED FIRST CARRY-IN: {required_carry_in}",
            f"REQUIRED FINAL CARRY-OUT: {required_carry_out}",
            (
                "These exact phrases are structural continuity state derived "
                "from the approved ordered plan. Copy them verbatim. They do not "
                "authorize any new fact or early reveal."
            ),
            "=== END APPROVED EXACT CARRY BINDING ===",
        )
    )
    return contract, required_carry_in, required_carry_out


_AV_HEADER_PATTERN = re.compile(
    r"^\[AV SECTION — (?P<title>[^\]\n|]{1,80}) \| "
    r"0:00 - (?P<end>\d+:\d{2})\]\r?$"
)
_AV_BEAT_PATTERN = re.compile(
    r"^\[BEAT (?P<number>\d+) \| (?P<start>\d+:\d{2}) - "
    r"(?P<end>\d+:\d{2})\]\r?$"
)
_AV_DIALOGUE_PATTERN = re.compile(
    r"^DIALOGUE (?P<speaker>[A-Za-z][A-Za-z .'-]{0,40}) "
    r"\[(?P<language>[a-z]{2,8})(?: \| pair=(?P<pair>[A-Za-z0-9_-]+))?\]: "
    r"(?P<text>\S.*)$"
)
_AV_VO_PATTERN = re.compile(
    r"^VO \[(?P<language>[a-z]{2,8})\]: (?P<text>\S.*)$"
)
_AV_RELAXED_DIALOGUE_PATTERN = re.compile(
    r"^DIALOGUE (?P<speaker>[A-Za-z][A-Za-z .'-]{0,40}) "
    r"\[(?P<language>[^\]\n|]+)"
    r"(?: \| pair=(?P<pair>[A-Za-z0-9_-]+))?\]: (?P<text>\S.*)$"
)
_AV_RELAXED_VO_PATTERN = re.compile(
    r"^VO \[(?P<language>[^\]\n]+)\]: (?P<text>\S.*)$"
)
_AV_EMPTY_AUDIBLE_TEXTS = frozenset(
    {"-", "–", "—", "none", "n/a", "n-a", "silence", "[silence]"}
)
_AV_EMPTY_AUDIBLE_PREFIX_PATTERN = re.compile(
    r"^(?:VO(?: \[[^\]\n]+\])?|DIALOGUE(?: [^:\n]+)?)$",
    re.IGNORECASE,
)
_AV_TERMINAL_SEPARATOR_PATTERN = re.compile(r"^(?:-{3,}|—{3,}|–{3,})$")
_AV_ACTION_LEAK_PATTERN = re.compile(
    r"\b(?:camera|shot|close-up|wide shot|we see|"
    r"(?:she|he|they|[A-Z][a-z]+)\s+(?:sits|stands|walks|runs|looks|"
    r"turns|rewinds|opens|closes|moves|crosses|reaches|points|nods))\b",
    re.IGNORECASE,
)
_AV_LANGUAGE_NAME_TAGS = {
    "arabic": "ar",
    "chinese": "zh",
    "dutch": "nl",
    "english": "en",
    "french": "fr",
    "german": "de",
    "hindi": "hi",
    "italian": "it",
    "japanese": "ja",
    "korean": "ko",
    "mandarin": "zh",
    "polish": "pl",
    "portuguese": "pt",
    "russian": "ru",
    "spanish": "es",
    "swedish": "sv",
    "turkish": "tr",
}


def _av_timestamp_seconds(value: str) -> int:
    minutes, seconds = value.split(":", 1)
    parsed_minutes = int(minutes)
    parsed_seconds = int(seconds)
    if parsed_seconds >= 60:
        raise ValueError("seconds component is out of range")
    return parsed_minutes * 60 + parsed_seconds


def _canonical_av_language_tag(value: Any, *, default: str = "en") -> str:
    raw = str(value or "").strip().casefold().replace("_", "-")
    if not raw:
        return default
    if raw in _AV_LANGUAGE_NAME_TAGS:
        return _AV_LANGUAGE_NAME_TAGS[raw]
    primary = raw.split("-", 1)[0]
    if primary in _AV_LANGUAGE_NAME_TAGS:
        return _AV_LANGUAGE_NAME_TAGS[primary]
    if re.fullmatch(r"[a-z]{2,8}", primary):
        return primary
    return default


def _custom_film_av_language_labels(
    language: Mapping[str, Any],
) -> tuple[str, ...]:
    mode = str(language.get("mode") or "narrator")
    raw_languages = language.get("languages")
    if mode == "bilingual":
        if (
            isinstance(raw_languages, (list, tuple))
            and len(raw_languages) == 2
            and all(str(value).strip() for value in raw_languages)
        ):
            return tuple(
                _canonical_av_language_tag(value)
                for value in raw_languages
            )
        source = language.get("source_language") or language.get("source")
        target = language.get("target_language") or language.get("target")
        if source and target:
            pair = (
                _canonical_av_language_tag(source, default="source"),
                _canonical_av_language_tag(target, default="target"),
            )
            if pair[0] != pair[1]:
                return pair
        return "source", "target"
    if mode == "simple_single_language":
        configured = (
            language.get("language")
            or language.get("target_language")
            or language.get("target")
            or (
                raw_languages[0]
                if isinstance(raw_languages, (list, tuple)) and raw_languages
                else None
            )
        )
        return (_canonical_av_language_tag(configured),)
    configured = (
        language.get("target_language")
        or language.get("target")
        or language.get("language")
    )
    return (_canonical_av_language_tag(configured),)


def _custom_film_av_language_pair(
    language: Mapping[str, Any],
) -> tuple[str, str]:
    labels = _custom_film_av_language_labels(language)
    if len(labels) == 2:
        return labels[0], labels[1]
    return "source", "target"


def _canonicalize_custom_film_av_language_tags(
    text: str,
    *,
    canonical_languages: tuple[str, ...],
) -> tuple[str, int]:
    """Locally repair only known full-name labels to approved exact tags."""

    approved = set(canonical_languages)
    normalized_lines: list[str] = []
    changes = 0
    for line in text.splitlines():
        relaxed = (
            _AV_RELAXED_VO_PATTERN.fullmatch(line.strip())
            or _AV_RELAXED_DIALOGUE_PATTERN.fullmatch(line.strip())
        )
        if relaxed:
            raw_label = relaxed.group("language").strip()
            canonical = _AV_LANGUAGE_NAME_TAGS.get(raw_label.casefold())
            if canonical in approved and raw_label != canonical:
                label_start = line.find("[") + 1
                label_end = label_start + len(raw_label)
                line = line[:label_start] + canonical + line[label_end:]
                changes += 1
        normalized_lines.append(line)
    return "\n".join(normalized_lines), changes


def _is_custom_film_av_empty_audible_line(line: str) -> bool:
    prefix, separator, text = line.strip().partition(":")
    return bool(
        separator
        and _AV_EMPTY_AUDIBLE_PREFIX_PATTERN.fullmatch(prefix.strip())
        and text.strip().casefold() in _AV_EMPTY_AUDIBLE_TEXTS
    )


def _remove_custom_film_av_empty_audible_placeholders(
    text: str,
) -> tuple[str, int]:
    """Remove only exact semantically empty audible-track placeholders."""

    retained: list[str] = []
    removed = 0
    for line in text.splitlines():
        if _is_custom_film_av_empty_audible_line(line):
            removed += 1
            continue
        retained.append(line)
    return "\n".join(retained), removed


def _custom_film_av_contract(request: SectionProductionRequest) -> str:
    end = f"{request.exact_seconds // 60}:{request.exact_seconds % 60:02d}"
    minimum_spoken_words = max(3, round(request.exact_seconds * 0.25))
    maximum_spoken_words = max(
        minimum_spoken_words,
        round(request.exact_seconds * 2.2),
    )
    bilingual = str(request.language.get("mode") or "") == "bilingual"
    language_mode = str(request.language.get("mode") or "narrator")
    approved_labels = _custom_film_av_language_labels(request.language)
    approved_languages = _custom_film_av_language_pair(request.language)
    if bilingual:
        performed_tag_law = (
            "EXACT PERFORMED TAGS: "
            f"DIALOGUE <speaker> [{approved_languages[0]} | pair=<id>]: "
            "<performed words> and "
            f"DIALOGUE <same speaker> [{approved_languages[1]} | pair=<same id>]: "
            "<meaning-equivalent performed words>"
        )
        audible_template_law = (
            "PER-BEAT AUDIBLE TEMPLATE: When a beat contains performed speech, "
            "use only the two exact paired DIALOGUE tags above. Never emit VO."
        )
    elif language_mode == "simple_single_language":
        performed_tag_law = (
            "EXACT PERFORMED TAG: "
            f"DIALOGUE <speaker> [{approved_labels[0]}]: <performed words>"
        )
        audible_template_law = (
            "PER-BEAT AUDIBLE TEMPLATE: When a beat contains performed speech, "
            f"use only DIALOGUE <speaker> [{approved_labels[0]}]: <performed "
            "words>. Never emit VO or a translation pair ID."
        )
    else:
        performed_tag_law = (
            f"EXACT NARRATOR TAG: VO [{approved_labels[0]}]: "
            "<sparse connective narration>"
        )
        audible_template_law = (
            "PER-BEAT AUDIBLE TEMPLATE: When a beat needs sparse connective "
            f"narration, use only VO [{approved_labels[0]}]: <spoken words>. "
            "Never emit DIALOGUE."
        )
    return "\n".join(
        (
            "=== CUSTOM FILM COVERAGE AV SCREENPLAY CONTRACT ===",
            (
                "Return a believable audiovisual screenplay, never a narrator "
                "reading camera directions or character actions."
            ),
            f"HEADER: [AV SECTION — <SHORT TITLE> | 0:00 - {end}]",
            "For every contiguous timed beat use:",
            "[BEAT <N> | <M:SS> - <M:SS>]",
            "VISUAL: camera-visible action, environment, props, and transition",
            "SOUND: diegetic sound effects or ambience",
            audible_template_law,
            "CARRY-IN: concrete object, signal, evidence, or state entering the beat",
            "CARRY-OUT: concrete object, signal, evidence, or changed state leaving the beat",
            performed_tag_law,
            (
                "SILENT-BEAT LAW: Omit the entire audible-track line when a beat "
                "has no speech. Never emit dash, None, N/A, N-A, silence, or any "
                "other placeholder as VO or DIALOGUE text."
            ),
            (
                "TIMING LAW: Beats start at 0:00, are gapless/non-overlapping, "
                f"and end exactly at {end}. Spoken coverage is cinematic and "
                "sufficient, not wall-to-wall narration."
            ),
            (
                "CINEMATIC SPARSE SPOKEN BAND: "
                f"{minimum_spoken_words}-{maximum_spoken_words} total audible "
                "words across VO and dialogue. This is a ceiling/floor for the "
                "whole AV timeline, not a request to fill every second with VO."
            ),
            (
                "TRACK SEPARATION LAW: VISUAL, SOUND, timing, and carry text are "
                "never audible. VO and DIALOGUE contain spoken words only. "
                "Character actions belong in VISUAL, never third-person VO."
            ),
            (
                "BILINGUAL PERFORMANCE LAW: Require actual performed turns by "
                "the same on-screen speaker in exactly the two approved language "
                f"labels '{approved_languages[0]}' and "
                f"'{approved_languages[1]}'; every translation pair ID must "
                "occur once in each approved language for lip-sync-ready segments. "
                "No third language label is allowed."
                if bilingual
                else "LANGUAGE LAW: Use only the approved performed language mode."
            ),
            (
                "CAUSE-AND-EFFECT LAW: Every beat changes visible state; each "
                "CARRY-OUT must exactly match the next beat's CARRY-IN. The final "
                "carry must earn the next approved section handoff."
            ),
            (
                "NARRATOR OCCUPANCY LAW: In narrator mode, audible VO may appear "
                "in at most floor(60% of timed beats), with one audible beat "
                "allowed when the section has only one beat. Leave complete beats "
                "without any audible track so VISUAL and SOUND carry the action."
                if language_mode == "narrator"
                else "PERFORMANCE OCCUPANCY LAW: Follow the performed-dialogue "
                "contract; the narrator-only occupancy cap does not apply."
            ),
            "=== END CUSTOM FILM COVERAGE AV SCREENPLAY CONTRACT ===",
        )
    )


def _parse_custom_film_av_screenplay(
    text: str,
    *,
    exact_seconds: int,
    language_mode: str,
    approved_languages: tuple[str, str] | None = None,
    canonical_languages: tuple[str, ...] | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Parse the coverage-only AV DSL and fail closed on ambiguous tracks."""

    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    if not lines:
        return None, ["AV screenplay is empty"]
    header = _AV_HEADER_PATTERN.fullmatch(lines[0])
    if not header:
        return None, ["AV screenplay must begin with the canonical AV SECTION header"]
    try:
        if _av_timestamp_seconds(header.group("end")) != exact_seconds:
            return None, ["AV screenplay header duration is not exact"]
    except ValueError:
        return None, ["AV screenplay header timestamp is malformed"]

    beats: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    issues: list[str] = []
    for line in lines[1:]:
        beat_match = _AV_BEAT_PATTERN.fullmatch(line)
        if beat_match:
            if current is not None:
                beats.append(current)
            try:
                start = _av_timestamp_seconds(beat_match.group("start"))
                end = _av_timestamp_seconds(beat_match.group("end"))
            except ValueError:
                issues.append("AV beat timestamp is malformed")
                start = end = -1
            current = {
                "beat": int(beat_match.group("number")),
                "start_seconds": start,
                "end_seconds": end,
                "visual": None,
                "sound": None,
                "carry_in": None,
                "carry_out": None,
                "audible": [],
            }
            continue
        if _is_custom_film_av_empty_audible_line(line):
            issues.append(
                "AV audible placeholder text is forbidden; omit the entire VO "
                "or DIALOGUE line for a silent beat"
            )
            continue
        if _AV_TERMINAL_SEPARATOR_PATTERN.fullmatch(line):
            issues.append(
                "AV screenplay must not emit terminal separator lines"
            )
            continue
        if current is None:
            issues.append("AV screenplay contains content outside a timed beat")
            continue
        matched_field = False
        for prefix, key in (
            ("VISUAL: ", "visual"),
            ("SOUND: ", "sound"),
            ("CARRY-IN: ", "carry_in"),
            ("CARRY-OUT: ", "carry_out"),
        ):
            if line.startswith(prefix):
                if current[key] is not None:
                    issues.append(f"AV beat repeats {key}")
                current[key] = line[len(prefix) :].strip()
                matched_field = True
                break
        if matched_field:
            continue
        vo = _AV_VO_PATTERN.fullmatch(line)
        dialogue = _AV_DIALOGUE_PATTERN.fullmatch(line)
        relaxed_vo = _AV_RELAXED_VO_PATTERN.fullmatch(line)
        relaxed_dialogue = _AV_RELAXED_DIALOGUE_PATTERN.fullmatch(line)
        if vo:
            current["audible"].append(
                {
                    "type": "narration",
                    "language": vo.group("language"),
                    "text": vo.group("text").strip(),
                }
            )
        elif dialogue:
            current["audible"].append(
                {
                    "type": "dialogue",
                    "speaker": dialogue.group("speaker").strip(),
                    "language": dialogue.group("language"),
                    "translation_pair": dialogue.group("pair"),
                    "text": dialogue.group("text").strip(),
                }
            )
        elif relaxed_vo:
            label = relaxed_vo.group("language").strip()
            expected = tuple(
                canonical_languages
                or approved_languages
                or ("en",)
            )
            issues.append(
                f"noncanonical VO language label '{label}'; use exactly "
                + " or ".join(f"VO [{value}]:" for value in expected)
            )
            current["audible"].append(
                {
                    "type": "narration",
                    "language": label,
                    "text": relaxed_vo.group("text").strip(),
                }
            )
        elif relaxed_dialogue:
            label = relaxed_dialogue.group("language").strip()
            expected = tuple(
                canonical_languages
                or approved_languages
                or ("en",)
            )
            issues.append(
                f"noncanonical DIALOGUE language label '{label}'; use exactly "
                + " or ".join(
                    f"DIALOGUE <speaker> [{value}]:" for value in expected
                )
            )
            current["audible"].append(
                {
                    "type": "dialogue",
                    "speaker": relaxed_dialogue.group("speaker").strip(),
                    "language": label,
                    "translation_pair": relaxed_dialogue.group("pair"),
                    "text": relaxed_dialogue.group("text").strip(),
                }
            )
        else:
            issues.append("AV screenplay contains a malformed or unknown track tag")
    if current is not None:
        beats.append(current)
    if not beats:
        issues.append("AV screenplay contains no timed beats")

    audible_segments: list[dict[str, Any]] = []
    expected_start = 0
    prior_carry: str | None = None
    for index, beat in enumerate(beats, start=1):
        if beat["beat"] != index:
            issues.append("AV beat numbers must be contiguous from one")
        if beat["start_seconds"] != expected_start or beat["end_seconds"] <= expected_start:
            issues.append("AV beat timing must be contiguous and positive")
        expected_start = beat["end_seconds"]
        for required in ("visual", "sound", "carry_in", "carry_out"):
            if not beat[required]:
                issues.append(f"AV beat {index} is missing {required}")
        if (
            prior_carry is not None
            and str(beat["carry_in"]).strip() != prior_carry
        ):
            issues.append("AV beat carry-out must exactly match the next carry-in")
        prior_carry = str(beat["carry_out"] or "").strip()
        for segment in beat["audible"]:
            if _AV_ACTION_LEAK_PATTERN.search(segment["text"]):
                issues.append("visual/action direction leaked into an audible segment")
            if re.search(r"\b(?:VISUAL|SOUND|CARRY-(?:IN|OUT)|BEAT)\s*:", segment["text"]):
                issues.append("screenplay track tags leaked into an audible segment")
            audible_segments.append(
                {
                    **segment,
                    "start_seconds": beat["start_seconds"],
                    "end_seconds": beat["end_seconds"],
                }
            )
    if expected_start != exact_seconds:
        issues.append("AV beats do not end at the exact section duration")

    spoken_words = sum(
        len(_SCRIPT_WORD_PATTERN.findall(segment["text"]))
        for segment in audible_segments
    )
    if spoken_words < max(3, round(exact_seconds * 0.25)):
        issues.append("AV screenplay has insufficient cinematic spoken coverage")
    if spoken_words > round(exact_seconds * 2.2):
        issues.append("AV screenplay is action-heavy or wall-to-wall spoken narration")

    allowed_languages = tuple(
        language.casefold()
        for language in (
            canonical_languages
            or approved_languages
            or ("en",)
        )
    )
    observed_audible_languages = {
        str(segment.get("language") or "").casefold()
        for segment in audible_segments
    }
    if observed_audible_languages - set(allowed_languages):
        issues.append(
            "AV audible tracks must use only canonical language labels: "
            + ", ".join(allowed_languages)
        )
    narration_segments = [
        segment
        for segment in audible_segments
        if segment.get("type") == "narration"
    ]
    dialogue_segments = [
        segment
        for segment in audible_segments
        if segment.get("type") == "dialogue"
    ]
    if language_mode == "narrator" and dialogue_segments:
        issues.append(
            "narrator AV mode permits VO tracks only; replace DIALOGUE with "
            f"VO [{allowed_languages[0]}]: or move performed speech to an "
            "approved dialogue mode"
        )
    if language_mode == "simple_single_language":
        if narration_segments:
            issues.append(
                "simple single-language AV mode permits DIALOGUE tracks only; "
                f"use DIALOGUE <speaker> [{allowed_languages[0]}]:"
            )
        if any(segment.get("translation_pair") for segment in dialogue_segments):
            issues.append(
                "simple single-language DIALOGUE must not include a translation "
                "pair ID"
            )
    if language_mode == "bilingual" and narration_segments:
        issues.append(
            "bilingual AV mode permits paired DIALOGUE tracks only; remove VO "
            "and perform the approved two-language speaker turns"
        )
    if language_mode == "narrator" and beats:
        audible_beat_count = sum(bool(beat["audible"]) for beat in beats)
        maximum_audible_beats = max(1, math.floor(len(beats) * 0.6))
        if audible_beat_count > maximum_audible_beats:
            issues.append(
                "narrator AV occupancy is too high: use VO in at most "
                f"{maximum_audible_beats} of {len(beats)} timed beats and leave "
                "the remaining beats fully carried by VISUAL and SOUND"
            )

    if language_mode == "bilingual":
        if (
            len(allowed_languages) != 2
            or allowed_languages[0] == allowed_languages[1]
        ):
            issues.append("bilingual approved language contract is invalid")
        dialogue = [
            segment for segment in audible_segments if segment["type"] == "dialogue"
        ]
        speakers: dict[str, set[str]] = {}
        pairs: dict[str, list[tuple[str, str]]] = {}
        for segment in dialogue:
            speaker_identity = segment["speaker"].strip().casefold()
            language_identity = segment["language"].casefold()
            speakers.setdefault(speaker_identity, set()).add(
                language_identity
            )
            pair = str(segment.get("translation_pair") or "")
            if not pair:
                issues.append("bilingual dialogue turn is missing a translation pair")
            else:
                pairs.setdefault(pair, []).append(
                    (speaker_identity, language_identity)
                )
        observed_languages = {
            segment["language"].casefold() for segment in dialogue
        }
        if observed_languages != set(allowed_languages):
            issues.append(
                "bilingual dialogue must use exactly the two approved languages"
            )
        if not any(
            languages == set(allowed_languages)
            for languages in speakers.values()
        ):
            issues.append(
                "bilingual section requires one on-screen speaker performing in two languages"
            )
        for turns in pairs.values():
            turn_languages = [language for _speaker, language in turns]
            if (
                len(turns) != 2
                or set(turn_languages) != set(allowed_languages)
                or any(
                    turn_languages.count(language) != 1
                    for language in allowed_languages
                )
            ):
                issues.append(
                    "bilingual translation pairs must contain exactly both "
                    "approved languages"
                )
            if len({speaker for speaker, _language in turns}) != 1:
                issues.append(
                    "bilingual translation pair turns must use one exact speaker"
                )

    parsed_result = {
        "format": "custom_film_av_v1",
        "title": header.group("title").strip(),
        "exact_seconds": exact_seconds,
        "spoken_words": spoken_words,
        "beats": beats,
        "dialogue_segments": audible_segments,
        "visual_beats": [
            {
                "beat": beat["beat"],
                "start_seconds": beat["start_seconds"],
                "end_seconds": beat["end_seconds"],
                "visual": beat["visual"],
                "carry_in": beat["carry_in"],
                "carry_out": beat["carry_out"],
            }
            for beat in beats
        ],
        "sound_beats": [
            {
                "beat": beat["beat"],
                "start_seconds": beat["start_seconds"],
                "end_seconds": beat["end_seconds"],
                "sound": beat["sound"],
            }
            for beat in beats
        ],
    }
    if issues:
        unique_issues = list(dict.fromkeys(issues))
        reportable_issue_prefixes = (
            "AV audible placeholder text is forbidden;",
            "AV screenplay has insufficient cinematic spoken coverage",
            "AV screenplay must not emit terminal separator lines",
            "narrator AV occupancy is too high:",
        )
        if all(
            issue.startswith(reportable_issue_prefixes)
            for issue in unique_issues
        ):
            # These are semantic AV composition failures, not ambiguous track
            # structure. Preserve parsed visual tracks so the same validation
            # pass can also report grounding drift.
            return parsed_result, unique_issues
        return None, unique_issues
    return parsed_result, []


def _custom_film_av_narration_text(raw_segments: Any) -> str:
    if isinstance(raw_segments, str):
        try:
            raw_segments = json.loads(raw_segments)
        except ValueError:
            return ""
    if not isinstance(raw_segments, list):
        return ""
    return "\n\n".join(
        str(segment.get("text") or "").strip()
        for segment in raw_segments
        if isinstance(segment, Mapping)
        and segment.get("type") == "narration"
        and str(segment.get("text") or "").strip()
    )


def _custom_film_av_grounding_issues(
    parsed: Mapping[str, Any],
    *,
    approved_context: str,
) -> list[str]:
    factual_parts: list[str] = []
    for beat in parsed.get("beats") or []:
        if not isinstance(beat, Mapping):
            continue
        factual_parts.extend(
            str(beat.get(key) or "")
            for key in ("visual", "sound", "carry_in", "carry_out")
        )
        factual_parts.extend(
            str(segment.get("text") or "")
            for segment in beat.get("audible") or []
            if isinstance(segment, Mapping)
        )
    factual_text = "\n".join(factual_parts)
    issues: list[str] = []
    approved_numbers = set(_SCRIPT_NUMBER_PATTERN.findall(approved_context))
    unsupported_numbers = sorted(
        set(_SCRIPT_NUMBER_PATTERN.findall(factual_text)) - approved_numbers
    )
    if unsupported_numbers:
        issues.append(
            "AV screenplay introduces number/date anchors absent from the "
            "approved section: " + ", ".join(unsupported_numbers[:6])
        )
    unsupported_number_words = sorted(
        _script_number_word_anchors(factual_text)
        - _script_number_word_anchors(approved_context)
    )
    if unsupported_number_words:
        issues.append(
            "AV screenplay introduces number-word anchors absent from the "
            "approved section: " + ", ".join(unsupported_number_words[:6])
        )
    unsupported_designations = sorted(
        _script_designation_word_anchors(factual_text)
        - _script_designation_word_anchors(approved_context)
    )
    if unsupported_designations:
        issues.append(
            "AV screenplay introduces designation anchors absent from the "
            "approved section: " + ", ".join(unsupported_designations[:6])
        )
    approved_tokens = {
        token.casefold() for token in _SCRIPT_WORD_PATTERN.findall(approved_context)
    }
    unsupported_named: list[str] = []
    for match in _SCRIPT_NAMED_TOKEN_PATTERN.finditer(factual_text):
        token = match.group(0)
        before = factual_text[: match.start()]
        line_start = before.rfind("\n") + 1
        at_line_start = not before[line_start:].strip()
        trimmed_before = before.rstrip()
        at_sentence_start = not trimmed_before or trimmed_before[-1:] in ".!?"
        # Sentence-initial title case is grammatically ambiguous: ordinary
        # visual nouns capitalize there too. Defer those candidates to the
        # semantic hard critic. Acronyms/all-caps and non-initial title case
        # remain deterministic lexical gates.
        if (
            (at_line_start or at_sentence_start)
            and not token.isupper()
        ):
            continue
        if (
            token.casefold() not in approved_tokens
            and token not in {"I"}
            and token.casefold() not in _SCRIPT_GROUNDING_STOPWORDS
        ):
            unsupported_named.append(token)
    for segment in parsed.get("dialogue_segments") or []:
        if isinstance(segment, Mapping) and segment.get("type") == "dialogue":
            speaker = str(segment.get("speaker") or "").strip()
            if speaker and not re.search(
                rf"(?<!\w){re.escape(speaker)}(?!\w)",
                approved_context,
                re.IGNORECASE,
            ):
                unsupported_named.append(speaker)
    unsupported_named = sorted(set(unsupported_named))
    if unsupported_named:
        issues.append(
            "AV screenplay introduces named anchors absent from the approved "
            "section: " + ", ".join(unsupported_named[:6])
        )
    return issues


def _validate_custom_film_av_arc(
    parsed_sections: list[Mapping[str, Any]],
) -> list[str]:
    """Whole-film cause/effect proof used before any downstream media stage."""

    issues: list[str] = []
    previous_out: str | None = None
    for index, parsed in enumerate(parsed_sections, start=1):
        visual_beats = parsed.get("visual_beats") or []
        if not visual_beats:
            issues.append(f"AV section {index} has no visual beats")
            continue
        carry_in = str(visual_beats[0].get("carry_in") or "").strip()
        carry_out = str(visual_beats[-1].get("carry_out") or "").strip()
        if previous_out is not None and carry_in != previous_out:
            issues.append(
                f"AV section {index - 1} carry-out does not match section "
                f"{index} carry-in"
            )
        previous_out = carry_out
    return issues


def _script_approved_contract(
    *,
    role: str,
    purpose: str,
    exact_seconds: int,
    config: _ExactSectionConfig,
    av_screenplay: bool = False,
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
            (
                f"EXACT AV TIMELINE DURATION: {exact_seconds} seconds"
                if av_screenplay
                else f"EXACT SPOKEN DURATION: {exact_seconds} seconds"
            ),
            (
                (
                    "CINEMATIC SPARSE SPOKEN BAND: "
                    if av_screenplay
                    else "EXACT SPOKEN WORD BAND: "
                )
                + f"{config.script_min_words}-{config.script_max_words} words "
                f"(target {config.total_script_words})"
            ),
            (
                (
                    "GROUNDING LAW: The approved current purpose and the separate "
                    "approved shared-film-world contract are the only sources for "
                    "subjects, people, places, organizations, events, dates, "
                    "numbers, examples, and case studies. Shared-world facts must "
                    "still obey the ordered progression law; add no adjacent fact."
                )
                if av_screenplay
                else (
                    "GROUNDING LAW: The approved role and purpose above are the "
                    "only source for the section's subject, people, places, "
                    "organizations, events, dates, numbers, examples, and case "
                    "studies. They may describe a real or fictional topic; do not "
                    "assume either and do not add adjacent material."
                )
            ),
            (
                (
                    "OUTPUT FORMAT LAW: Follow the Custom Film coverage AV "
                    "screenplay contract below exactly. Do not emit an ACT "
                    "marker or narration-document wrapper."
                )
                if av_screenplay
                else (
                    f"OUTPUT FORMAT LAW: Return exactly {config.act_count} act "
                    "using the shared marker grammar on its own line. For this "
                    f"section the required marker grammar is: {exact_marker} "
                    "Replace only <SHORT SECTION TITLE> with a short title; keep "
                    "the brackets, ACT number, separators, timestamps, and target "
                    "word annotation exactly as shown."
                )
            ),
            (
                (
                    "Do not add SCRIPT, END, notes, analysis, Markdown headings, "
                    "or any wrapper around the canonical AV screenplay."
                )
                if av_screenplay
                else (
                    "Do not replace the bracketed marker with ACT/END prose. Do "
                    "not add SCRIPT, END, notes, analysis, Markdown headings, or "
                    "any wrapper before or after the marked spoken section. The "
                    "marker is document structure, not spoken narration."
                )
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
                "GROUNDING GRANULARITY LAW: Concrete does not mean more "
                "factually specific. Preserve the exact factual granularity of "
                "approved nouns. Do not turn a generic approved record, signal, "
                "location, object, network, piece of evidence, or event into a "
                "new subtype, named component, labeled geography, timestamp, "
                "measurement, specification, or mechanism. Make it cinematic "
                "through handling, blocking, reaction, lighting, sound, camera "
                "perspective, and visible before/after state."
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
        normalized_terminal = terminal.strip()
        for _ in range(2):
            heading = _SCRIPT_MARKDOWN_HEADING_PATTERN.fullmatch(
                normalized_terminal
            )
            if heading:
                normalized_terminal = heading.group("body").strip()
                continue
            emphasis = _SCRIPT_EMPHASIS_LINE_PATTERN.fullmatch(
                normalized_terminal
            )
            if emphasis:
                normalized_terminal = emphasis.group("body").strip()
                continue
            break
        if (
            _SCRIPT_FENCE_PATTERN.fullmatch(terminal)
            or _SCRIPT_FENCE_PATTERN.fullmatch(normalized_terminal)
            or _SCRIPT_HORIZONTAL_RULE_PATTERN.fullmatch(normalized_terminal)
            or re.fullmatch(
                r"\s*(?:END|SCRIPT\s+END|END\s+SCRIPT)\s*[.!]?\s*",
                normalized_terminal,
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
    unsupported_designations = sorted(
        _script_designation_word_anchors(prose)
        - _script_designation_word_anchors(approved_context)
    )
    if unsupported_designations:
        issues.append(
            "script introduces designation anchors absent from the approved "
            "section: " + ", ".join(unsupported_designations[:6])
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
        row = _normalize_provenance_row(row)
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
        values = [_normalize_provenance_row(row) for row in rows]
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
        values = [_normalize_provenance_row(row) for row in rows]
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
        from shared.channel_profile import (
            CLAUDE_MODELS,
            claude_model_for_direct_client,
        )

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
        # Kie's wrapped Claude client intentionally returns ``None`` from the
        # direct-client helper so the call can use its own default. Provenance,
        # however, must still name that default model explicitly.
        provider_model = (
            claude_model_for_direct_client(client)
            or CLAUDE_MODELS["kie"]["smart"]
        )
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
        av_screenplay_mode = (
            request.render_mode == "coverage"
            and bool(request.story_arc)
            and all(
                str(item.get("section_id") or "")
                and str(item.get("render_mode") or "")
                for item in request.story_arc
            )
        )
        config = (
            _AVSectionConfig(request.exact_seconds)
            if av_screenplay_mode
            else _ExactSectionConfig(request.exact_seconds)
        )
        canonical_av_languages = (
            _custom_film_av_language_labels(request.language)
            if av_screenplay_mode
            else ()
        )
        film_world_contract, film_world_context = (
            _script_shared_film_world_contract(
                request.story_arc,
                current_order_index=request.order_index,
            )
            if av_screenplay_mode
            else ("", "")
        )
        approved_grounding_context = "\n".join(
            part for part in (approved_context, film_world_context) if part
        )
        (
            carry_binding_contract,
            required_first_carry_in,
            required_final_carry_out,
        ) = (
            _script_av_carry_binding(
                request.story_arc,
                current_order_index=request.order_index,
            )
            if av_screenplay_mode
            else ("", "", "")
        )
        approved_contract = _script_approved_contract(
            role=request.role,
            purpose=request.purpose,
            exact_seconds=request.exact_seconds,
            config=config,
            av_screenplay=av_screenplay_mode,
        )
        av_contract = (
            _custom_film_av_contract(request) if av_screenplay_mode else ""
        )
        story_arc_guidance = _script_story_arc_guidance(
            request.story_arc,
            current_order_index=request.order_index,
        )
        approved_visual_plan_contract = _script_approved_visual_plan_contract(
            request.story_arc,
            current_order_index=request.order_index,
        )
        story_arc_ending_law = _script_story_arc_continuity_law(
            request.story_arc,
            current_order_index=request.order_index,
        )
        story_arc_continuity_rule = "\n".join(
            part
            for part in (story_arc_guidance, story_arc_ending_law)
            if part
        )
        role_structure_law = _script_role_structure_law(request.role)
        role_structure_contract = "\n".join(
            (
                "=== APPROVED ROLE STRUCTURE LAW ===",
                f"ROLE: {request.role}",
                role_structure_law,
                "=== END APPROVED ROLE STRUCTURE LAW ===",
            )
        )
        repair_context = "\n".join(
            part
            for part in (
                approved_contract,
                av_contract,
                film_world_contract,
                approved_visual_plan_contract,
                carry_binding_contract,
                role_structure_contract,
                story_arc_guidance,
                story_arc_ending_law,
            )
            if part
        )
        brief = {
            "headline": request.purpose,
            "thesis": request.purpose,
            "executive_hook": f"{request.role}: {request.purpose}",
            "writer_guidance": (
                f"Write only section {request.order_index + 1}. Its role is "
                f"'{request.role}' and its exact purpose is: {request.purpose}. "
                + (
                    f"The AV beat timeline must span exactly "
                    f"{request.exact_seconds} seconds; speech may remain sparse.\n"
                    if av_screenplay_mode
                    else (
                        f"The spoken result must fit exactly "
                        f"{request.exact_seconds} seconds.\n"
                    )
                )
                + approved_contract
                + "\n"
                + role_structure_contract
                + "\n"
                + (av_contract + "\n" if av_contract else "")
                + (film_world_contract + "\n" if film_world_contract else "")
                + (
                    approved_visual_plan_contract + "\n"
                    if approved_visual_plan_contract
                    else ""
                )
                + (
                    carry_binding_contract + "\n"
                    if carry_binding_contract
                    else ""
                )
                + (
                    story_arc_continuity_rule + "\n"
                    if story_arc_continuity_rule
                    else ""
                )
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
                        else (
                            "Use only sparse connective VO for information that "
                            "visuals and sound cannot carry. Do not invent "
                            "character dialogue in this narrator section; visual "
                            "action and sound must carry the scene. "
                            if av_screenplay_mode
                            else "Write this section as narrator-led voice-over. "
                        )
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
        language_tag_normalizations = 0
        audible_placeholder_removals = 0
        if av_screenplay_mode:
            script_text, audible_placeholder_removals = (
                _remove_custom_film_av_empty_audible_placeholders(script_text)
            )
            script_text, language_tag_normalizations = (
                _canonicalize_custom_film_av_language_tags(
                    script_text,
                    canonical_languages=canonical_av_languages,
                )
            )
        import script_quality

        def deterministic_validation(
            current_text: str,
            generator_validation: Any,
        ) -> tuple[list[str], dict[str, Any]]:
            if av_screenplay_mode:
                parsed, av_issues = _parse_custom_film_av_screenplay(
                    current_text,
                    exact_seconds=request.exact_seconds,
                    language_mode=str(request.language.get("mode") or ""),
                    approved_languages=(
                        _custom_film_av_language_pair(request.language)
                        if str(request.language.get("mode") or "") == "bilingual"
                        else None
                    ),
                    canonical_languages=canonical_av_languages,
                )
                if parsed is not None:
                    av_issues.extend(
                        _custom_film_av_grounding_issues(
                            parsed,
                            approved_context=approved_grounding_context,
                        )
                    )
                    visual_beats = parsed.get("visual_beats") or []
                    if visual_beats:
                        normalized_role = (
                            request.role.strip()
                            .casefold()
                            .replace("-", "_")
                            .replace(" ", "_")
                        )
                        if (
                            normalized_role == "resolution"
                            and request.exact_seconds >= 30
                            and len(visual_beats) < 4
                        ):
                            av_issues.append(
                                "AV resolution of 30 seconds or longer requires "
                                "at least four timed beats so decision, distinct "
                                "dependent actions, confirmations, and final "
                                "proof cannot collapse into macro visual phases"
                            )
                        if (
                            str(visual_beats[0].get("carry_in") or "").strip()
                            != required_first_carry_in
                        ):
                            av_issues.append(
                                "AV first CARRY-IN must exactly match the "
                                "approved carry binding"
                            )
                        if (
                            str(visual_beats[-1].get("carry_out") or "").strip()
                            != required_final_carry_out
                        ):
                            av_issues.append(
                                "AV final CARRY-OUT must exactly match the "
                                "approved carry binding"
                            )
                return av_issues, {
                    "valid": not av_issues,
                    "issues": av_issues,
                    "format": "custom_film_av_v1",
                    "parsed": parsed,
                }
            shared_validation = (
                generator_validation
                if isinstance(generator_validation, Mapping)
                else {}
            )
            return (
                _script_grounding_issues(
                    current_text,
                    approved_context=approved_context,
                    config=config,
                    generator_validation=shared_validation,
                ),
                dict(shared_validation),
            )

        async def repair_deterministic_issues(
            current_text: str,
            current_issues: list[str],
        ) -> tuple[str, list[str], int, dict[str, Any]]:
            nonlocal audible_placeholder_removals
            nonlocal language_tag_normalizations
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
                            "repair:\n" + repair_context
                        ),
                    ],
                    client=client,
                )
                rounds += 1
                if not edited:
                    break
                current_text = str(edited[0].get("text") or "").strip()
                if av_screenplay_mode:
                    current_text, removed = (
                        _remove_custom_film_av_empty_audible_placeholders(
                            current_text
                        )
                    )
                    audible_placeholder_removals += removed
                    current_text, normalized = (
                        _canonicalize_custom_film_av_language_tags(
                            current_text,
                            canonical_languages=canonical_av_languages,
                        )
                    )
                    language_tag_normalizations += normalized
                shared_validation = (
                    {}
                    if av_screenplay_mode
                    else validate_script(
                        current_text,
                        config=config,
                        profile=profile,
                    )
                )
                current_issues, validation = deterministic_validation(
                    current_text,
                    shared_validation,
                )
            return current_text, current_issues, rounds, validation

        deterministic_issues, initial_validation = deterministic_validation(
            script_text,
            generated.get("validation"),
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
        if not deterministic_edit_rounds:
            final_validation = initial_validation
        if deterministic_issues:
            raise CustomFilmContractError(
                "Custom Film section script failed approved timing/grounding "
                "before voice or imagery: " + "; ".join(deterministic_issues)
            )

        rules = [
            "approved_purpose_grounding: The script must stay entirely "
            f"within this approved section/shared-film-world context: "
            f"{approved_grounding_context}. "
            "Reject any unrelated person, place, organization, event, date, "
            "number, case study, conspiracy, or adjacent topic. Treat an "
            "unapproved sentence-initial title-case candidate as potential "
            "entity drift even though lexical validation cannot distinguish it "
            "from an ordinary capitalized visual noun. GROUNDING GRANULARITY "
            "LAW: Concrete does not mean more factually specific. Preserve the "
            "exact factual granularity of approved nouns; reject new subtypes, "
            "named components, labeled geography, timestamp, measurement, "
            "specification, or mechanism. Cinematic specificity must instead "
            "come from handling, blocking, reaction, light, sound, camera "
            "perspective, and visible before/after state.",
            "visual_story_readiness: The script must tell a coherent, "
            "specific visual story. Each beat must provide concrete action, "
            "evidence, environment, character behavior, or an observable "
            "change that the approved stills or clips can show; reject generic "
            "exposition, disconnected claims, and non-visual filler.",
            "role_structure_quality: Apply this film-agnostic structural "
            f"law for the approved '{request.role}' role: "
            f"{role_structure_law} The ordered story arc may guide continuity "
            "and handoff but is not itself a factual source. Explicitly "
            "plan-authored shared-film-world facts may persist across sections "
            "only under the progression and no-early-reveal law.",
        ]
        severity_by_rule = {
            "approved_purpose_grounding": "hard_gate",
            "visual_story_readiness": "hard_gate",
            "role_structure_quality": "hard_gate",
        }
        if story_arc_continuity_rule:
            rules.append(
                "story_arc_continuity: " + story_arc_continuity_rule
            )
            severity_by_rule["story_arc_continuity"] = "hard_gate"
        if approved_visual_plan_contract:
            rules.append(
                "approved_visual_plan_fidelity: Preserve the ordered "
                "plan-selected visual functions, presentations, intents, motion "
                "grammar, and transitions as cinematic coverage. Reject generic "
                "substitutes that ignore them and reject scripts that speak, "
                "caption, diagram, or expose their raw component names, "
                "capability identifiers, handoff tokens, or orchestration schema. "
                + approved_visual_plan_contract
            )
            severity_by_rule["approved_visual_plan_fidelity"] = "hard_gate"
        if av_screenplay_mode:
            rules.append(
                "shared_film_world_progression: Named facts explicitly present "
                "anywhere in the approved ordered plan may persist across "
                "sections, but this section must not reveal, explain, resolve, "
                "or duplicate a later section's discovery, outcome, or payoff. "
                "Reject premature reveals and repeated progression."
            )
            severity_by_rule["shared_film_world_progression"] = "hard_gate"
            rules.append(
                "av_screenplay_performance: The coverage section must play as "
                "a believable audiovisual scene. Audible VO/dialogue may contain "
                "spoken words only; visual action, camera, props, ambience, and "
                "transitions stay on their dedicated tracks. Reject third-person "
                "narration of character actions, malformed/gapped beat timing, "
                "action-heavy VO, weak performed dialogue, or disconnected beats."
            )
            severity_by_rule["av_screenplay_performance"] = "hard_gate"
            if str(request.language.get("mode") or "") == "bilingual":
                rules.append(
                    "bilingual_performance_fidelity: The same approved on-screen "
                    "speaker must perform meaning-equivalent turns in both "
                    "approved languages. Translation-paired lines must preserve "
                    "intent, facts, tone, and referents while remaining natural "
                    "and lip-sync-ready; reject labels without actual dialogue, "
                    "third-person narration of the speaker, or merely matching "
                    "pair IDs with divergent meaning."
                )
                severity_by_rule["bilingual_performance_fidelity"] = "hard_gate"
        rules_text = "\n".join(rules)
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
                severity_by_rule=severity_by_rule,
                strict_rule_ids=tuple(severity_by_rule),
                critic_max_tokens=1800,
                retry_invalid_critique=True,
                max_edit_rounds=_SCRIPT_REPAIR_ATTEMPTS,
                edit_constraints=[
                    (
                        "EDIT CONSTRAINTS — these remain mandatory on every "
                        "repair:\n" + repair_context
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
            if av_screenplay_mode:
                script_text, removed = (
                    _remove_custom_film_av_empty_audible_placeholders(
                        script_text
                    )
                )
                audible_placeholder_removals += removed
                script_text, normalized = (
                    _canonicalize_custom_film_av_language_tags(
                        script_text,
                        canonical_languages=canonical_av_languages,
                    )
                )
                language_tag_normalizations += normalized
            shared_validation = (
                {}
                if av_screenplay_mode
                else validate_script(
                    script_text,
                    config=config,
                    profile=profile,
                )
            )
            final_issues, final_validation = deterministic_validation(
                script_text,
                shared_validation,
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
        av_screenplay = (
            final_validation.get("parsed")
            if av_screenplay_mode and isinstance(final_validation, Mapping)
            else None
        )
        if av_screenplay_mode and not isinstance(av_screenplay, Mapping):
            raise CustomFilmContractError(
                "Custom Film AV screenplay was not deterministically parsed"
            )
        dialogue_segments = (
            list(av_screenplay.get("dialogue_segments") or [])
            if isinstance(av_screenplay, Mapping)
            else None
        )
        script_validation_payload = {
            "custom_film": {
                "runtime_hash": request.runtime_hash,
                "section_id": request.section_id,
                "exact_seconds": request.exact_seconds,
                "script_profile": request.script_profile,
                "preflight": {
                    "verdict": grade.verdict,
                    "score": grade.score,
                    "deterministic_edit_rounds": deterministic_edit_rounds,
                    "quality_edit_rounds": quality_edit_rounds,
                    "quality_passes": quality_passes,
                    "audible_placeholder_removals": (
                        audible_placeholder_removals
                    ),
                    "language_tag_normalizations": language_tag_normalizations,
                },
            },
            "shared_validation": final_validation,
            "av_screenplay": (
                {
                    "format": av_screenplay.get("format"),
                    "exact_seconds": av_screenplay.get("exact_seconds"),
                    "spoken_words": av_screenplay.get("spoken_words"),
                    "visual_beats": av_screenplay.get("visual_beats"),
                    "sound_beats": av_screenplay.get("sound_beats"),
                    "carry_out": (
                        av_screenplay.get("visual_beats") or [{}]
                    )[-1].get("carry_out"),
                    "carry_in": (
                        av_screenplay.get("visual_beats") or [{}]
                    )[0].get("carry_in"),
                }
                if isinstance(av_screenplay, Mapping)
                else None
            ),
        }
        scene_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{request.operation_id}:section-script:0",
            )
        )
        pool = await __import__("database").get_pool()
        async with pool.acquire() as conn:
            dialogue_mode_update: str | None = None
            coverage_arc = [
                item
                for item in request.story_arc
                if str(item.get("render_mode") or "coverage") == "coverage"
            ]
            if (
                av_screenplay_mode
                and coverage_arc
                and all(str(item.get("section_id") or "") for item in coverage_arc)
                and request.order_index
                == max(int(item.get("order_index", -1)) for item in coverage_arc)
            ):
                prior_section_ids = [
                    str(item["section_id"])
                    for item in coverage_arc
                    if str(item["section_id"]) != request.section_id
                ]
                screenplay_rows = await conn.fetch(
                    """SELECT css.section_id, s.script_validation
                       FROM custom_film_section_scenes css
                       JOIN scripts s
                         ON s.id = css.script_id
                        AND s.tenant_id = css.tenant_id
                        AND s.video_id = css.video_id
                       WHERE css.tenant_id = $1::uuid
                         AND css.video_id = $2::uuid
                         AND css.plan_id = $3::uuid
                         AND css.section_id = ANY($4::uuid[])
                       ORDER BY css.scene_order""",
                    self.tenant_id,
                    request.video_id,
                    request.plan_id,
                    prior_section_ids,
                )
                parsed_by_section: dict[str, Mapping[str, Any]] = {}
                for screenplay_row in screenplay_rows:
                    raw_validation = screenplay_row.get("script_validation")
                    if isinstance(raw_validation, str):
                        try:
                            raw_validation = json.loads(raw_validation)
                        except ValueError:
                            raw_validation = None
                    parsed = (
                        raw_validation.get("shared_validation", {}).get("parsed")
                        if isinstance(raw_validation, Mapping)
                        else None
                    )
                    custom_film_validation = (
                        raw_validation.get("custom_film", {})
                        if isinstance(raw_validation, Mapping)
                        else {}
                    )
                    row_section_id = str(
                        screenplay_row.get("section_id") or ""
                    )
                    if (
                        isinstance(parsed, Mapping)
                        and custom_film_validation.get("runtime_hash")
                        == request.runtime_hash
                        and custom_film_validation.get("section_id")
                        == row_section_id
                    ):
                        parsed_by_section[row_section_id] = parsed
                parsed_by_section[request.section_id] = av_screenplay
                ordered_parsed = [
                    parsed_by_section.get(str(item["section_id"]))
                    for item in sorted(
                        coverage_arc,
                        key=lambda value: int(value.get("order_index", -1)),
                    )
                ]
                if any(not isinstance(parsed, Mapping) for parsed in ordered_parsed):
                    raise CustomFilmContractError(
                        "Custom Film whole-arc AV screenplay barrier is "
                        "incomplete; no voice or imagery was started"
                    )
                arc_issues = _validate_custom_film_av_arc(ordered_parsed)
                if arc_issues:
                    raise CustomFilmContractError(
                        "Custom Film whole-arc AV screenplay failed continuity; "
                        "no voice or imagery was started: "
                        + "; ".join(arc_issues)
                    )
                dialogue_mode_update = (
                    "character_dialogue"
                    if any(
                        segment.get("type") == "dialogue"
                        for parsed in ordered_parsed
                        for segment in parsed.get("dialogue_segments") or []
                        if isinstance(segment, Mapping)
                    )
                    else "narration_only"
                )
            row = await conn.fetchrow(
                """INSERT INTO scripts
                     (id, tenant_id, video_id, scene, scene_text, title,
                      script_status, voice_id, script_validation,
                      dialogue_segments)
                   VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6,
                           'Create', $7, $8, $9::jsonb)
                   ON CONFLICT (id) DO UPDATE
                     SET scene_text = EXCLUDED.scene_text,
                         script_validation = EXCLUDED.script_validation,
                         dialogue_segments = EXCLUDED.dialogue_segments,
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
                json.dumps(script_validation_payload, sort_keys=True),
                (
                    json.dumps(dialogue_segments, sort_keys=True)
                    if dialogue_segments is not None
                    else None
                ),
            )
            if not row or str(row.get("id") or "") != scene_id:
                raise CustomFilmContractError(
                    "Custom Film section script could not be durably saved"
                )
            await conn.execute(
                """UPDATE videos v
                   SET script = assembled.script,
                       dialogue_mode = COALESCE($3, v.dialogue_mode),
                       updated_at = now()
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
                dialogue_mode_update,
            )
        # D7-2 (STORY-LAWS S6): this writes videos.script directly (Custom
        # Film's own section-script persistence, not routes/videos.py's
        # shared sync_video_script), so it needs its own call to the same
        # cast/environments staleness check.
        from routes.videos import _flag_stale_cast_and_environments
        await _flag_stale_cast_and_environments(request.video_id, self.tenant_id)
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
                          voice_over_url, dialogue_segments, script_validation
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
            if request.render_mode == "coverage" and row.get("dialogue_segments"):
                text = _custom_film_av_narration_text(
                    row.get("dialogue_segments")
                )
            else:
                text = narration_text(
                    str(row.get("scene_text") or ""),
                    dialogue_mode,
                )
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
            # generation_ledger (money-safety fix): this section's narration
            # already cost real ElevenLabs money the moment it was durably
            # checkpointed above — meter it the same per-character way
            # pipeline_executor.run_voice already does for the ordinary
            # narration path (stage="voice", model="elevenlabs"); this is the
            # same provider billed the same way, just Custom Film's own
            # durable-operation seam instead of run_voice's. No NEW spend-cap
            # check here — Custom Film already gates its ENTIRE film's
            # quoted cost against videos.max_spend up front, before
            # scheduling any section (custom_film_runtime.compile_runtime_plan,
            # custom_film_contract.py's approval-time budget_check) — adding a
            # second, incremental per-line refusal here would be a second
            # cap mechanism for this subsystem, not a reuse of the existing
            # one. This call only closes the ledger-visibility gap so
            # videos.total_cost reflects what Custom Film actually spent.
            from actions import VOICE_PRICE_PER_1K_CHARS
            from generation_ledger import record_ledger_entry
            per_char = VOICE_PRICE_PER_1K_CHARS / 1000
            await record_ledger_entry(
                tenant_id=self.tenant_id, video_id=request.video_id, stage="voice",
                model="elevenlabs", units=len(text), unit_cost=round(per_char, 6),
                actual_cost=round(len(text) * per_char, 2),
            )
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

    async def _quality_script_preflight(
        self,
        request: SectionProductionRequest,
        rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Revalidate durable prior strict AV evidence without a drifting critic.

        This late gate does not claim a new rendered semantic judgment. The
        strict contextual AV critic already ran before voice or imagery; here
        we prove that exact approved text still owns that validation and the
        current runtime's completed script operation.
        """

        if not rows:
            raise CustomFilmContractError(
                "Custom Film quality found no assigned screenplay"
            )
        expected_hashes = [
            {
                "scene_id": str(row["id"]),
                "scene_text_hash": canonical_hash(
                    {
                        "scene_id": str(row["id"]),
                        "scene_text": str(row.get("scene_text") or ""),
                    }
                ),
            }
            for row in rows
        ]
        import database

        pool = await database.get_pool()
        async with pool.acquire() as conn:
            operation_rows = await conn.fetch(
                """SELECT result
                   FROM custom_film_provider_operations
                   WHERE tenant_id = $1::uuid AND video_id = $2::uuid
                     AND runtime_job_id = $3 AND stage_key = $4
                     AND state = 'completed'""",
                self.tenant_id,
                request.video_id,
                f"custom-film-runtime:{request.runtime_hash}",
                f"{request.order_index}:{request.section_id}:script",
            )
        if len(operation_rows) != 1:
            raise CustomFilmContractError(
                "Custom Film quality found no exact completed script operation"
            )
        operation_result = operation_rows[0].get("result")
        if isinstance(operation_result, str):
            try:
                operation_result = json.loads(operation_result)
            except ValueError:
                operation_result = None
        if (
            not isinstance(operation_result, Mapping)
            or operation_result.get("scene_ids") != list(request.scene_ids)
            or operation_result.get("scene_text_hashes") != expected_hashes
        ):
            raise CustomFilmContractError(
                "Custom Film quality found changed screenplay evidence"
            )

        scores: list[int] = []
        validated_av_sections = 0
        for row in rows:
            validation = row.get("script_validation")
            if isinstance(validation, str):
                try:
                    validation = json.loads(validation)
                except ValueError:
                    validation = None
            custom = (
                validation.get("custom_film")
                if isinstance(validation, Mapping)
                else None
            )
            shared = (
                validation.get("shared_validation")
                if isinstance(validation, Mapping)
                else None
            )
            preflight = (
                custom.get("preflight")
                if isinstance(custom, Mapping)
                else None
            )
            if (
                not isinstance(custom, Mapping)
                or custom.get("section_id") != request.section_id
                or custom.get("exact_seconds") != request.exact_seconds
                or custom.get("script_profile") != request.script_profile
                or not isinstance(preflight, Mapping)
                or preflight.get("verdict") != "pass"
                or type(preflight.get("score")) is not int
                or not isinstance(shared, Mapping)
                or shared.get("valid") is not True
            ):
                raise CustomFilmContractError(
                    "Custom Film quality found unapproved screenplay validation"
                )
            scores.append(int(preflight["score"]))

            script_text = str(row.get("scene_text") or "")
            if request.render_mode == "coverage":
                parsed, issues = _parse_custom_film_av_screenplay(
                    script_text,
                    exact_seconds=request.exact_seconds,
                    language_mode=str(request.language.get("mode") or ""),
                    approved_languages=(
                        _custom_film_av_language_pair(request.language)
                        if str(request.language.get("mode") or "")
                        == "bilingual"
                        else None
                    ),
                    canonical_languages=_custom_film_av_language_labels(
                        request.language
                    ),
                )
                _world_contract, film_world_context = (
                    _script_shared_film_world_contract(
                        request.story_arc,
                        current_order_index=request.order_index,
                    )
                )
                approved_context = "\n".join(
                    part
                    for part in (
                        f"{request.role}\n{request.purpose}",
                        film_world_context,
                    )
                    if part
                )
                if isinstance(parsed, Mapping):
                    issues.extend(
                        _custom_film_av_grounding_issues(
                            parsed,
                            approved_context=approved_context,
                        )
                    )
                    (
                        _carry_contract,
                        required_carry_in,
                        required_carry_out,
                    ) = _script_av_carry_binding(
                        request.story_arc,
                        current_order_index=request.order_index,
                    )
                    visual_beats = parsed.get("visual_beats") or []
                    if (
                        not visual_beats
                        or str(visual_beats[0].get("carry_in") or "")
                        != required_carry_in
                        or str(visual_beats[-1].get("carry_out") or "")
                        != required_carry_out
                    ):
                        issues.append(
                            "AV screenplay carry binding changed after approval"
                        )
                stored_parsed = shared.get("parsed")
                if (
                    issues
                    or not isinstance(parsed, Mapping)
                    or not isinstance(stored_parsed, Mapping)
                    or _plain(parsed) != _plain(stored_parsed)
                ):
                    raise CustomFilmContractError(
                        "Custom Film quality found changed AV screenplay "
                        "grounding or structure"
                    )
                validated_av_sections += 1
            else:
                issues = _script_grounding_issues(
                    script_text,
                    approved_context=f"{request.role}\n{request.purpose}",
                    config=_ExactSectionConfig(request.exact_seconds),
                    generator_validation=shared,
                )
                if issues:
                    raise CustomFilmContractError(
                        "Custom Film quality found changed screenplay grounding"
                    )
        return {
            "script_validation": "durable_prior_strict_preflight_revalidated",
            "script_quality_score": min(scores),
            "validated_av_sections": validated_av_sections,
            "quality_evaluation": (
                "durable_prior_strict_av_preflight_and_exact_media_evidence"
            ),
        }

    async def _quality(self, request: SectionProductionRequest) -> dict[str, Any]:
        rows = await self._scene_rows(request)
        script_evidence = await self._quality_script_preflight(request, rows)
        timing_evidence = await self._quality_media_preflight(request)
        return {
            "scene_ids": list(request.scene_ids),
            "quality_laws": list(request.quality_laws),
            "verdict": "pass",
            "score": script_evidence["script_quality_score"],
            "exact_seconds": request.exact_seconds,
            **script_evidence,
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
                values = [_normalize_provenance_row(row) for row in rows]
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
