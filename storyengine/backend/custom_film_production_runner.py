"""Concrete Script/Voice/Quality production runner for Custom Film sections.

The runtime consumer owns Custom Film interpretation.  This module receives
only resolved :class:`SectionStageAdapter` values and converts them into the
existing shared script, narration, and script-quality seams.  Provider-facing
code therefore never branches on a ``custom_film`` mode.

The seam object is injectable so tests can prove the exact request without
calling a provider.  The default seam uses tenant-owned clients initialized by
``PipelineExecutor`` and the same lower-level production functions as the
legacy video-wide wrappers.
"""

from __future__ import annotations

import copy
import json
import uuid
from dataclasses import dataclass, replace
from typing import Any, Awaitable, Callable, Mapping, Protocol

from custom_film_contract import CustomFilmContractError, canonical_hash
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


SUPPORTED_PRODUCTION_STAGES = frozenset({"script", "voice", "quality"})
_LOCAL_PROVIDER = "storyengine-local"
_TEXT_PROVIDER = "tenant-text-generation"
_VOICE_PROVIDER = "tenant-voice-generation"


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
    script_profile: str
    dialogue_audio: str
    language: Mapping[str, Any]
    dubbing: Mapping[str, Any]
    segmentation: Mapping[str, Any]
    quality_laws: tuple[str, ...]

    def payload(self) -> dict[str, Any]:
        return {
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
            "script_profile": self.script_profile,
            "dialogue_audio": self.dialogue_audio,
            "language": _plain(self.language),
            "dubbing": _plain(self.dubbing),
            "segmentation": _plain(self.segmentation),
            "quality_laws": list(self.quality_laws),
        }


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
    if not adapter.script_profile.strip() or not adapter.quality_laws:
        raise CustomFilmContractError(
            "Custom Film section script or quality contract is missing; "
            "no provider work was started"
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
        required=adapter.stage in {"voice", "quality"},
    )
    if adapter.stage == "script" and scenes:
        raise CustomFilmContractError(
            "Custom Film script stage cannot reuse stale scene assignments"
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
        script_profile=adapter.script_profile,
        dialogue_audio=adapter.dialogue_audio,
        language=adapter.language,
        dubbing=adapter.dubbing,
        segmentation=adapter.segmentation,
        quality_laws=adapter.quality_laws,
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
        if request.stage == "voice":
            return ProviderOperationSpec(
                provider="storyengine-section-voice",
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
        if request.stage != "voice" or request.dialogue_audio == "grok_native":
            return None
        recovered = await self._voice_artifact_checkpoint(request)
        return (
            SectionProductionResult(recovered)
            if recovered is not None
            else None
        )

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
        from script.brief_translator.script_generator import generate_script
        from shared.profiles.script import load_script_profile

        profile = load_script_profile(request.script_profile)
        raw_research = video.get("research_payload") or {}
        if isinstance(raw_research, str):
            try:
                raw_research = json.loads(raw_research)
            except (json.JSONDecodeError, TypeError):
                raw_research = {}
        research = dict(raw_research) if isinstance(raw_research, Mapping) else {}
        title = str(video.get("video_title") or video.get("headline") or "Untitled")
        brief = {
            **research,
            "headline": title,
            "thesis": str(research.get("thesis") or request.purpose),
            "executive_hook": str(
                research.get("executive_hook")
                or f"{request.role}: {request.purpose}"
            ),
            "writer_guidance": (
                f"Write only section {request.order_index + 1}. Its role is "
                f"'{request.role}' and its exact purpose is: {request.purpose}. "
                f"The spoken result must fit exactly {request.exact_seconds} seconds. "
                f"Language mode is '{request.language.get('mode')}', dialogue "
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
            config=_ExactSectionConfig(request.exact_seconds),
            profile=profile,
        )
        script_text = str(generated.get("script") or "").strip()
        if not script_text:
            raise CustomFilmContractError(
                "Custom Film script provider returned no section script"
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
                title,
                "1SM7GgM6IMuvQlz2BwM3",
                json.dumps(
                    {
                        "custom_film": {
                            "runtime_hash": request.runtime_hash,
                            "section_id": request.section_id,
                            "exact_seconds": request.exact_seconds,
                            "script_profile": request.script_profile,
                        },
                        "shared_validation": generated.get("validation") or {},
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
            "exact_seconds": request.exact_seconds,
            "script_profile": request.script_profile,
            "role": request.role,
            "purpose": request.purpose,
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
        }
