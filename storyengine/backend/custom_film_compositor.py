"""Exact, restart-safe compositor for approved Custom Film section output.

This module is the single boundary which knows that a render is a Custom Film.
It converts the immutable section runtime and M2-4 artifact provenance into a
versioned assembly manifest, normalizes each source without changing its
recorded raw identity, and joins the normalized sections into one exact-length
artifact.  Provider callers remain profile-agnostic.

The renderer intentionally uses deterministic FFmpeg cuts (zero overlap).
Transition duration is therefore explicit and cannot steal section frames.
Source clip audio is muted unless the immutable section contract calls for
``grok_native`` dialogue; voice-over sections use their one assigned narration
track.  This prevents the common clip-audio-plus-narrator double mix.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import shutil
import tempfile
import textwrap
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Sequence

from custom_film_contract import (
    CustomFilmContractError,
    canonical_caption_card,
    canonical_hash,
)
from custom_film_section_runtime import compile_stage_adapters
from error_utils import humanize_error


ASSEMBLY_VERSION_V1 = "custom-film-assembly-v1"
ASSEMBLY_VERSION_V2 = "custom-film-assembly-v2"
ASSEMBLY_VERSION_V3 = "custom-film-assembly-v3"
# Compatibility default for direct callers; production selects v3 only when
# Remotion is explicitly requested before journaling.
ASSEMBLY_VERSION = ASSEMBLY_VERSION_V2
DEFAULT_FPS = 24
SUPPORTED_TRANSFORMS = frozenset({"none", "trim", "repeat_then_trim"})
ProgressCallback = Callable[[str], Awaitable[None]]
RemotionRenderer = Callable[..., Awaitable[Mapping[str, Any]]]


class CustomFilmRetryableError(RuntimeError):
    """Transport/process/storage failure safe to retry under the same identity."""


def assembly_storage_path(
    video_id: str, runtime_hash: str, manifest_hash: str
) -> str:
    """Immutable object identity; mutable presentation fields never participate."""
    return (
        f"{video_id}/final/custom-film-"
        f"{runtime_hash[:16]}-{manifest_hash[:16]}.mp4"
    )


def assembly_resume_action(state: str) -> str:
    """Return the only safe restart action for a durable assembly state."""
    if state == "finalized":
        return "return_finalized"
    if state == "uploaded":
        return "finalize_uploaded"
    if state in {
        "prepared", "rendering", "rendered", "uploading", "retryable_failed"
    }:
        # rendered/uploading may have lost their process-local temp file.  The
        # immutable manifest is rerendered and the same hash-derived storage
        # path is reused; no second object identity can be minted.
        return "render_and_upload_same_path"
    if state == "terminal_failed":
        return "terminal_failure"
    raise CustomFilmContractError("Custom Film assembly state is unsupported")


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            value = None
    if not isinstance(value, Mapping):
        raise CustomFilmContractError(f"Custom Film {label} is invalid")
    return copy.deepcopy(dict(value))


def _rows(values: Sequence[Mapping[str, Any]], label: str) -> list[dict[str, Any]]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise CustomFilmContractError(f"Custom Film {label} is invalid")
    return [_mapping(value, label) for value in values]


def _exact_int(value: Any, label: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise CustomFilmContractError(
            f"Custom Film {label} must be an exact integer of at least {minimum}"
        )
    return value


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _validate_transform(
    transform_value: Any, actual_ms: int, target_ms: int
) -> dict[str, Any]:
    transform = _mapping(transform_value, "timing transform")
    mode = str(transform.get("mode") or "")
    if mode not in SUPPORTED_TRANSFORMS:
        raise CustomFilmContractError("Custom Film timing transform is unsupported")
    if (
        transform.get("source_duration_ms") != actual_ms
        or transform.get("output_duration_ms") != target_ms
    ):
        raise CustomFilmContractError(
            "Custom Film timing transform does not match raw and assigned duration"
        )
    if actual_ms == target_ms:
        expected = {
            "mode": "none",
            "source_duration_ms": actual_ms,
            "output_duration_ms": target_ms,
        }
    elif actual_ms > target_ms:
        expected = {
            "mode": "trim",
            "source_duration_ms": actual_ms,
            "trim_start_ms": 0,
            "trim_end_ms": target_ms,
            "output_duration_ms": target_ms,
        }
    else:
        repeats = (target_ms + actual_ms - 1) // actual_ms
        expected = {
            "mode": "repeat_then_trim",
            "source_duration_ms": actual_ms,
            "repeat_count": repeats,
            "final_repeat_duration_ms": target_ms - ((repeats - 1) * actual_ms),
            "output_duration_ms": target_ms,
        }
    if transform != expected:
        raise CustomFilmContractError(
            "Custom Film timing transform is not the deterministic accepted recipe"
        )
    return transform


def _audio_timing_transform(source_ms: int, target_ms: int) -> dict[str, Any]:
    source_ms = _exact_int(source_ms, "voice source duration", 1)
    target_ms = _exact_int(target_ms, "voice target duration", 1)
    if source_ms == target_ms:
        return {
            "mode": "none",
            "source_duration_ms": source_ms,
            "output_duration_ms": target_ms,
            "atempo_chain": [],
            "caption_scale": 1.0,
        }
    playback_rate = source_ms / target_ms
    # Speech remains intelligible only inside this narrow, explicit policy.
    # Large gaps must be repaired upstream, never padded or spoken-word trimmed.
    if playback_rate < 0.8 or playback_rate > 1.25:
        raise CustomFilmContractError(
            "Custom Film narration duration cannot safely fit its approved section"
        )
    return {
        "mode": "atempo",
        "source_duration_ms": source_ms,
        "output_duration_ms": target_ms,
        "atempo_chain": [round(playback_rate, 9)],
        "caption_scale": round(target_ms / source_ms, 9),
    }


def _allocate_integer(total: int, count: int) -> list[int]:
    """Allocate an exact integer total in stable order without rounding drift."""
    total = _exact_int(total, "allocation total", 1)
    count = _exact_int(count, "allocation count", 1)
    return [
        ((index + 1) * total // count) - (index * total // count)
        for index in range(count)
    ]


def _asset_identity_hash(
    section: Mapping[str, Any],
    asset: Mapping[str, Any],
    provenance: Mapping[str, Any],
    *,
    stage: str,
) -> str:
    if stage == "pictures":
        caption_card = canonical_caption_card(asset.get("caption"))
        artifact = {
            "image_url": str(asset.get("image_url") or "").strip(),
            "drive_image_url": str(asset.get("drive_image_url") or "").strip(),
            "caption_card": caption_card,
            "caption_hash": canonical_hash({"caption_card": caption_card}),
        }
    else:
        artifact = {
            "video_clip_url": str(asset.get("video_clip_url") or "").strip(),
            "actual_duration_ms": provenance.get("actual_duration_ms"),
            "assigned_duration_ms": provenance.get("assigned_duration_ms"),
            "timing_transform": _mapping(
                provenance.get("timing_transform"), "timing transform"
            ),
        }
    return canonical_hash(
        {
            "stage": stage,
            "asset_id": str(asset.get("asset_id") or asset.get("id") or ""),
            "artifact": artifact,
            "provider_model": str(provenance.get("provider_model") or ""),
            "generation_method": str(asset.get("generation_method") or ""),
            "camera": _mapping(section.get("camera"), "section camera"),
            "request_hash": str(provenance.get("request_hash") or ""),
            "section_contract_hash": str(
                provenance.get("section_contract_hash") or ""
            ),
        }
    )


def _validate_progress(
    envelope: Mapping[str, Any],
    runtime_progress_value: Any,
) -> None:
    adapters = compile_stage_adapters(envelope)
    expected_keys = [adapter.stage_key for adapter in adapters]
    progress = _mapping(runtime_progress_value, "runtime progress")
    if (
        progress.get("runtime_hash") != envelope["runtime_hash"]
        or progress.get("completed_stage_keys") != expected_keys
        or progress.get("last_stage_key") != expected_keys[-1]
        or progress.get("in_flight") is not None
    ):
        raise CustomFilmContractError(
            "Custom Film section runtime is not an exact completed ordered prefix"
        )


def _parent_operation_id(
    tenant_id: str,
    runtime_job_id: str,
    adapter: Any,
) -> str:
    return "custom-film-op:" + canonical_hash(
        {
            "tenant_id": tenant_id,
            "video_id": adapter.video_id,
            "job_id": runtime_job_id,
            "runtime_hash": adapter.runtime_hash,
            "stage_key": adapter.stage_key,
        }
    )


def _validate_operation_graph(
    *,
    tenant_id: str,
    runtime_job_id: str,
    envelope: Mapping[str, Any],
    provider_rows: Sequence[Mapping[str, Any]],
    scenes_by_section: Mapping[str, list[str]],
) -> dict[str, dict[str, Any]]:
    adapters = compile_stage_adapters(envelope)
    providers = _rows(provider_rows, "provider operations")
    actual_by_id: dict[str, dict[str, Any]] = {}
    for row in providers:
        operation_id = str(row.get("operation_id") or "")
        if not operation_id or operation_id in actual_by_id:
            raise CustomFilmContractError(
                "Custom Film provider operations have a missing or duplicate identity"
            )
        if (
            str(row.get("tenant_id") or "") != tenant_id
            or str(row.get("video_id") or "") != str(envelope["video_id"])
            or str(row.get("runtime_job_id") or "") != runtime_job_id
            or str(row.get("runtime_hash") or "") != str(envelope["runtime_hash"])
            or row.get("state") != "completed"
            or not isinstance(row.get("result"), Mapping)
        ):
            raise CustomFilmContractError(
                "Custom Film provider operation is incomplete or stale"
            )
        actual_by_id[operation_id] = row

    expected: dict[str, dict[str, Any]] = {}
    parents: dict[str, dict[str, Any]] = {}
    child_stages = {"voice", "pictures", "motion", "clips"}
    for adapter in adapters:
        parent_id = _parent_operation_id(tenant_id, runtime_job_id, adapter)
        parent_meta = {
            "kind": "parent",
            "operation_id": parent_id,
            "stage_key": adapter.stage_key,
            "section_id": adapter.section_id,
            "stage": adapter.stage,
            "scene_id": None,
        }
        expected[parent_id] = parent_meta
        parents[adapter.stage_key] = actual_by_id.get(parent_id) or {}
        scene_ids = scenes_by_section.get(adapter.section_id, [])
        if adapter.stage == "script":
            scene_ids = []
        elif not scene_ids:
            raise CustomFilmContractError(
                "Custom Film provider graph has no assigned section scenes"
            )
        if adapter.stage in child_stages:
            for scene_index, scene_id in enumerate(scene_ids):
                identity = {
                    "parent_operation_id": parent_id,
                    "scene_id": scene_id,
                }
                if adapter.stage != "voice":
                    identity["stage"] = adapter.stage
                child_id = "custom-film-op:" + canonical_hash(identity)
                child_key = (
                    f"{adapter.stage_key}:scene:{scene_index}:"
                    f"{canonical_hash({'scene_id': scene_id})[:12]}"
                )
                expected[child_id] = {
                    "kind": "child",
                    "operation_id": child_id,
                    "parent_operation_id": parent_id,
                    "stage_key": child_key,
                    "section_id": adapter.section_id,
                    "stage": adapter.stage,
                    "scene_id": scene_id,
                    "scene_index": scene_index,
                }
    if set(actual_by_id) != set(expected):
        raise CustomFilmContractError(
            "Custom Film provider graph has missing or unknown parent/child operations"
        )
    for operation_id, meta in expected.items():
        row = actual_by_id[operation_id]
        if str(row.get("stage_key") or "") != meta["stage_key"]:
            raise CustomFilmContractError(
                "Custom Film provider operation stage identity changed"
            )
    for adapter in adapters:
        parent_id = _parent_operation_id(tenant_id, runtime_job_id, adapter)
        parent_row = actual_by_id[parent_id]
        result = _mapping(parent_row["result"], "parent provider result")
        assigned = scenes_by_section.get(adapter.section_id, [])
        if adapter.stage == "script":
            if result.get("scene_ids") != assigned:
                raise CustomFilmContractError(
                    "Custom Film script result no longer owns assigned scenes"
                )
            continue
        if adapter.stage not in child_stages:
            continue
        child_entries = result.get("child_operations")
        if not isinstance(child_entries, list) or len(child_entries) != len(assigned):
            raise CustomFilmContractError(
                "Custom Film parent result has incomplete child operations"
            )
        for scene_index, (scene_id, entry_value) in enumerate(
            zip(assigned, child_entries)
        ):
            entry = _mapping(entry_value, "parent child result")
            identity = {"parent_operation_id": parent_id, "scene_id": scene_id}
            if adapter.stage != "voice":
                identity["stage"] = adapter.stage
            child_id = "custom-film-op:" + canonical_hash(identity)
            child_row = actual_by_id[child_id]
            if (
                entry.get("scene_id") != scene_id
                or entry.get("operation_id") != child_id
                or entry.get("result") != child_row.get("result")
            ):
                raise CustomFilmContractError(
                    "Custom Film parent result does not exactly bind its child"
                )
    return actual_by_id


def build_assembly_manifest(
    *,
    tenant_id: str,
    envelope_value: Any,
    runtime_progress_value: Any,
    provider_rows: Sequence[Mapping[str, Any]],
    scene_rows: Sequence[Mapping[str, Any]],
    asset_rows: Sequence[Mapping[str, Any]],
    provenance_rows: Sequence[Mapping[str, Any]],
    runtime_job_id: str,
    section_supplements: Mapping[str, Mapping[str, Any]] | None = None,
    require_source_hashes: bool = True,
    fps: int = DEFAULT_FPS,
    width: int = 1920,
    height: int = 1080,
    render_engine: str = "ffmpeg",
    assembly_version: str = ASSEMBLY_VERSION,
) -> dict[str, Any]:
    """Build an immutable JSON-safe exact-frame assembly manifest.

    All inputs are current rows read in one repeatable-read transaction by the
    production loader.  The function is pure so adversarial fixtures can prove
    every fail-closed law without a live database or provider.
    """
    tenant_id = str(tenant_id or "").strip()
    if not tenant_id:
        raise CustomFilmContractError("Custom Film tenant identity is missing")
    envelope = _mapping(envelope_value, "runtime envelope")
    compile_stage_adapters(envelope)  # complete structural + hash validation
    runtime_job_id = str(runtime_job_id or "").strip()
    if runtime_job_id != f"custom-film-runtime:{envelope['runtime_hash']}":
        raise CustomFilmContractError("Custom Film runtime job identity changed")
    _validate_progress(envelope, runtime_progress_value)
    fps = _exact_int(fps, "assembly fps", 1)
    width = _exact_int(width, "assembly width", 2)
    height = _exact_int(height, "assembly height", 2)
    if width % 2 or height % 2:
        raise CustomFilmContractError("Custom Film output dimensions must be even")
    from custom_film_remotion import SUPPORTED_RENDER_ENGINES

    if render_engine not in SUPPORTED_RENDER_ENGINES:
        raise CustomFilmContractError("Custom Film render engine is unsupported")
    if assembly_version not in {
        ASSEMBLY_VERSION_V1,
        ASSEMBLY_VERSION_V2,
        ASSEMBLY_VERSION_V3,
    }:
        raise CustomFilmContractError("Custom Film assembly version is unsupported")
    if assembly_version == ASSEMBLY_VERSION_V1 and render_engine != "ffmpeg":
        raise CustomFilmContractError(
            "Custom Film assembly v1 only supports its original FFmpeg renderer"
        )
    if assembly_version == ASSEMBLY_VERSION_V3 and render_engine != "remotion":
        raise CustomFilmContractError(
            "Custom Film assembly v3 is reserved for Remotion"
        )

    scenes = _rows(scene_rows, "section scenes")
    assets = _rows(asset_rows, "assets")
    provenance = _rows(provenance_rows, "asset provenance")
    supplements = {
        str(key): _mapping(value, "section supplement")
        for key, value in (section_supplements or {}).items()
    }
    scene_ids: set[str] = set()
    scenes_by_section: dict[str, list[str]] = {}
    last_scene_order: dict[str, int] = {}
    for row in scenes:
        if (
            str(row.get("tenant_id") or "") != tenant_id
            or str(row.get("video_id") or "") != str(envelope["video_id"])
            or str(row.get("plan_id") or "") != str(envelope["plan_id"])
        ):
            raise CustomFilmContractError("Custom Film scene assignment is stale")
        section_id = str(row.get("section_id") or "")
        script_id = str(row.get("script_id") or "")
        order = _exact_int(row.get("scene_order"), "scene order")
        if (
            not section_id
            or not script_id
            or script_id in scene_ids
            or order != last_scene_order.get(section_id, -1) + 1
        ):
            raise CustomFilmContractError(
                "Custom Film scene assignments are missing, duplicated, or out of order"
            )
        scene_ids.add(script_id)
        last_scene_order[section_id] = order
        scenes_by_section.setdefault(section_id, []).append(script_id)
    operations_by_id = _validate_operation_graph(
        tenant_id=tenant_id,
        runtime_job_id=runtime_job_id,
        envelope=envelope,
        provider_rows=provider_rows,
        scenes_by_section=scenes_by_section,
    )
    adapters_by_stage = {
        (adapter.section_id, adapter.stage): adapter
        for adapter in compile_stage_adapters(envelope)
    }
    scene_rows_by_id = {
        str(row["script_id"]): row for row in scenes
    }

    assets_by_id: dict[str, dict[str, Any]] = {}
    for asset in assets:
        asset_id = str(asset.get("asset_id") or asset.get("id") or "")
        if (
            not asset_id
            or asset_id in assets_by_id
            or str(asset.get("tenant_id") or "") != tenant_id
            or str(asset.get("video_id") or "") != str(envelope["video_id"])
        ):
            raise CustomFilmContractError("Custom Film current assets are stale")
        assets_by_id[asset_id] = asset

    provenance_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in provenance:
        key = (str(row.get("asset_id") or ""), str(row.get("stage") or ""))
        if (
            not key[0]
            or key in provenance_by_key
            or str(row.get("tenant_id") or "") != tenant_id
            or str(row.get("video_id") or "") != str(envelope["video_id"])
            or str(row.get("plan_id") or "") != str(envelope["plan_id"])
            or str(row.get("runtime_hash") or "") != str(envelope["runtime_hash"])
            or row.get("status") != "completed"
        ):
            raise CustomFilmContractError(
                "Custom Film asset provenance is incomplete or stale"
            )
        provenance_by_key[key] = row

    manifest_sections: list[dict[str, Any]] = []
    film_frame = 0
    seen_assets: set[str] = set()
    sections_value = envelope["sections"]
    for order_index, section_value in enumerate(sections_value):
        section = _mapping(section_value, "runtime section")
        section_id = str(section.get("section_id") or "")
        if (
            section.get("order_index") != order_index
            or section_id not in scenes_by_section
        ):
            raise CustomFilmContractError(
                "Custom Film section scene assignments have a gap"
            )
        supplement = supplements.get(section_id, {})
        assigned_scene_ids = scenes_by_section[section_id]
        script_adapter = adapters_by_stage[(section_id, "script")]
        script_parent_id = _parent_operation_id(
            tenant_id, runtime_job_id, script_adapter
        )
        script_result = _mapping(
            operations_by_id[script_parent_id]["result"],
            "script provider result",
        )
        expected_text_hashes = [
            {
                "scene_id": scene_id,
                "scene_text_hash": canonical_hash(
                    {
                        "scene_id": scene_id,
                        "scene_text": str(
                            scene_rows_by_id[scene_id].get("scene_text") or ""
                        ),
                    }
                ),
            }
            for scene_id in assigned_scene_ids
        ]
        if (
            script_result.get("scene_ids") != assigned_scene_ids
            or script_result.get("scene_text_hashes") != expected_text_hashes
            or any(
                not str(scene_rows_by_id[scene_id].get("scene_text") or "").strip()
                for scene_id in assigned_scene_ids
            )
        ):
            raise CustomFilmContractError(
                "Custom Film current script text drifted from its completed operation"
            )
        voice_adapter = adapters_by_stage[(section_id, "voice")]
        voice_parent_id = _parent_operation_id(
            tenant_id, runtime_job_id, voice_adapter
        )
        if section["dialogue_audio"] == "voice_over":
            supplement_voice_urls = list(
                supplement.get("voice_over_urls") or []
            )
            if len(supplement_voice_urls) != len(assigned_scene_ids):
                raise CustomFilmContractError(
                    "Custom Film exact voice-over inputs are incomplete"
                )
            for scene_index, scene_id in enumerate(assigned_scene_ids):
                voice_child_id = "custom-film-op:" + canonical_hash(
                    {
                        "parent_operation_id": voice_parent_id,
                        "scene_id": scene_id,
                    }
                )
                voice_result = _mapping(
                    operations_by_id[voice_child_id]["result"],
                    "voice child result",
                )
                artifacts = voice_result.get("artifacts")
                if not isinstance(artifacts, list) or len(artifacts) != 1:
                    raise CustomFilmContractError(
                        "Custom Film voice child has incomplete artifacts"
                    )
                artifact = _mapping(artifacts[0], "voice artifact")
                current_scene = scene_rows_by_id[scene_id]
                artifact_id = str(artifact.get("artifact_id") or "")
                if (
                    artifact.get("scene_id") != scene_id
                    or artifact.get("artifact_url")
                    != current_scene.get("voice_over_url")
                    or str(current_scene.get("voice_status") or "")
                    != f"custom-film-voice:{artifact_id}"
                    or supplement_voice_urls[scene_index]
                    != current_scene.get("voice_over_url")
                ):
                    raise CustomFilmContractError(
                        "Custom Film current voice artifact drifted from its child operation"
                    )
        duration_seconds = _exact_int(
            section.get("duration_seconds"), "section seconds", 1
        )
        section_frames = duration_seconds * fps
        animated = bool(_mapping(section["animation"], "animation").get("enabled"))
        required_stage = "clips" if animated else "pictures"
        section_provenance = [
            row
            for (asset_id, stage), row in provenance_by_key.items()
            if stage == required_stage and str(row.get("section_id") or "") == section_id
        ]
        section_provenance.sort(
            key=lambda row: (
                _exact_int(
                    assets_by_id.get(str(row["asset_id"]), {}).get("scene_order"),
                    "asset scene order",
                ),
                _exact_int(
                    assets_by_id.get(str(row["asset_id"]), {}).get("image_index"),
                    "asset image order",
                ),
                str(row["asset_id"]),
            )
        )
        expected_count = _exact_int(
            _mapping(section["estimated_media"], "estimated media").get(
                "animation_clips" if animated else "still_images"
            ),
            "approved media count",
            1,
        )
        if len(section_provenance) != expected_count:
            raise CustomFilmContractError(
                "Custom Film section media count does not match approval"
            )

        manifest_assets: list[dict[str, Any]] = []
        assigned_frames = 0
        seen_asset_slots: set[tuple[int, int]] = set()
        for row in section_provenance:
            asset_id = str(row["asset_id"])
            asset = assets_by_id.get(asset_id)
            if asset is None or asset_id in seen_assets:
                raise CustomFilmContractError(
                    "Custom Film asset is missing, duplicated, or reused across sections"
                )
            source_sha256 = str(asset.get("source_sha256") or "")
            if require_source_hashes and (
                len(source_sha256) != 64
                or any(char not in "0123456789abcdef" for char in source_sha256)
            ):
                raise CustomFilmContractError(
                    "Custom Film exact downloaded source hash is missing"
                )
            if str(asset.get("section_id") or "") != section_id:
                raise CustomFilmContractError("Custom Film asset section ownership drifted")
            asset_slot = (
                _exact_int(asset.get("scene_order"), "asset scene order"),
                _exact_int(asset.get("image_index"), "asset image order"),
            )
            if asset_slot in seen_asset_slots:
                raise CustomFilmContractError(
                    "Custom Film section media order has a duplicate slot"
                )
            seen_asset_slots.add(asset_slot)
            if asset_slot[0] >= len(assigned_scene_ids):
                raise CustomFilmContractError(
                    "Custom Film asset points outside assigned section scenes"
                )
            owning_scene_id = assigned_scene_ids[asset_slot[0]]
            caption_card = canonical_caption_card(asset.get("caption"))
            caption_hash = canonical_hash({"caption_card": caption_card})
            picture_adapter = adapters_by_stage[(section_id, "pictures")]
            picture_parent_id = _parent_operation_id(
                tenant_id, runtime_job_id, picture_adapter
            )
            picture_child_id = "custom-film-op:" + canonical_hash(
                {
                    "parent_operation_id": picture_parent_id,
                    "stage": "pictures",
                    "scene_id": owning_scene_id,
                }
            )
            picture_result = _mapping(
                operations_by_id[picture_child_id]["result"],
                "picture child result",
            )
            picture_artifacts = picture_result.get("artifacts")
            if not isinstance(picture_artifacts, list):
                raise CustomFilmContractError(
                    "Custom Film picture child has no durable artifacts"
                )
            exact_picture_artifacts = [
                _mapping(value, "picture artifact")
                for value in picture_artifacts
                if isinstance(value, Mapping)
                and str(value.get("artifact_id") or "") == asset_id
            ]
            exact_picture = (
                exact_picture_artifacts[0]
                if len(exact_picture_artifacts) == 1
                else {}
            )
            stored_card = exact_picture.get("caption_card")
            stored_caption_hash = exact_picture.get("caption_hash")
            if (
                "caption_card" not in exact_picture
                or "caption_hash" not in exact_picture
                or (stored_card is not None and not isinstance(stored_card, Mapping))
                or not isinstance(stored_caption_hash, str)
                or len(stored_caption_hash) != 64
                or stored_card != caption_card
                or stored_caption_hash != caption_hash
            ):
                raise CustomFilmContractError(
                    "Custom Film current caption card drifted from its picture operation"
                )
            picture_provenance = provenance_by_key.get((asset_id, "pictures"))
            if (
                picture_provenance is None
                or str(picture_provenance.get("operation_id") or "")
                != picture_child_id
                or str(picture_provenance.get("artifact_url_hash") or "")
                != _asset_identity_hash(
                    section,
                    asset,
                    picture_provenance,
                    stage="pictures",
                )
            ):
                raise CustomFilmContractError(
                    "Custom Film caption card drifted from picture provenance"
                )
            media_adapter = adapters_by_stage[(section_id, required_stage)]
            media_parent_id = _parent_operation_id(
                tenant_id, runtime_job_id, media_adapter
            )
            media_child_id = "custom-film-op:" + canonical_hash(
                {
                    "parent_operation_id": media_parent_id,
                    "stage": required_stage,
                    "scene_id": owning_scene_id,
                }
            )
            if str(row.get("operation_id") or "") != media_child_id:
                raise CustomFilmContractError(
                    "Custom Film asset provenance does not belong to its exact child"
                )
            if (
                str(row.get("artifact_url_hash") or "")
                != _asset_identity_hash(
                    section, asset, row, stage=required_stage
                )
            ):
                raise CustomFilmContractError(
                    "Custom Film current asset no longer matches its provenance hash"
                )
            seen_assets.add(asset_id)
            if animated:
                actual_ms = _exact_int(
                    row.get("actual_duration_ms"), "raw clip duration", 1
                )
                target_ms = _exact_int(
                    row.get("assigned_duration_ms"), "assigned clip duration", 1
                )
                if target_ms % (1000 // fps if 1000 % fps == 0 else 1):
                    # Exact integer section seconds are the authority.  Individual
                    # millisecond allocations are converted with a cumulative
                    # boundary below, avoiding per-asset rounding drift.
                    pass
                transform = _validate_transform(
                    row.get("timing_transform"), actual_ms, target_ms
                )
            else:
                actual_ms = None
                target_ms = 0
                transform = {
                    "mode": "static_hold",
                    "source_duration_ms": None,
                    "output_duration_ms": None,
                }
            source_url = str(
                asset.get("video_clip_url")
                if animated
                else asset.get("drive_image_url") or asset.get("image_url")
                or ""
            ).strip()
            if not source_url:
                raise CustomFilmContractError(
                    "Custom Film current media source is missing"
                )
            media_child_result = _mapping(
                operations_by_id[media_child_id]["result"],
                "media child result",
            )
            child_artifacts = media_child_result.get("artifacts")
            if not isinstance(child_artifacts, list):
                raise CustomFilmContractError(
                    "Custom Film media child has no durable artifacts"
                )
            exact_child_artifacts = [
                _mapping(value, "media artifact")
                for value in child_artifacts
                if isinstance(value, Mapping)
                and str(value.get("artifact_id") or "") == asset_id
            ]
            if len(exact_child_artifacts) != 1:
                raise CustomFilmContractError(
                    "Custom Film child result does not own its exact asset"
                )
            child_artifact = exact_child_artifacts[0]
            if child_artifact.get("artifact_url") != source_url:
                raise CustomFilmContractError(
                    "Custom Film child artifact URL changed"
                )
            if animated and (
                child_artifact.get("actual_duration_ms") not in (None, actual_ms)
                or child_artifact.get("assigned_duration_ms") not in (
                    None, target_ms
                )
                or child_artifact.get("timing_transform") not in (
                    None, transform
                )
            ):
                raise CustomFilmContractError(
                    "Custom Film child clip timing changed"
                )
            manifest_assets.append(
                {
                    "asset_id": asset_id,
                    "source_url": source_url,
                    "source_sha256": source_sha256 or None,
                    "actual_duration_ms": actual_ms,
                    "assigned_duration_ms": target_ms if animated else None,
                    "timing_transform": transform,
                    "camera": _mapping(section["camera"], "section camera"),
                    "provenance_hash": str(row["artifact_url_hash"]),
                        "caption_card": caption_card,
                        "caption_hash": caption_hash,
                }
            )

        # Derive exact frame boundaries cumulatively.  This is what prevents
        # three 333ms-style allocations from losing a frame independently.
        if animated:
            elapsed_ms = 0
            for index, item in enumerate(manifest_assets):
                start = (elapsed_ms * fps) // 1000
                elapsed_ms += int(item["assigned_duration_ms"])
                end = (
                    section_frames
                    if index == len(manifest_assets) - 1
                    else (elapsed_ms * fps) // 1000
                )
                if end <= start:
                    raise CustomFilmContractError(
                        "Custom Film media allocation is shorter than one frame"
                    )
                item["start_frame"] = start
                item["duration_frames"] = end - start
                assigned_frames += end - start
            if elapsed_ms != duration_seconds * 1000:
                raise CustomFilmContractError(
                    "Custom Film assigned clip durations do not equal section seconds"
                )
        else:
            count = len(manifest_assets)
            for index, item in enumerate(manifest_assets):
                start = (index * section_frames) // count
                end = ((index + 1) * section_frames) // count
                item["start_frame"] = start
                item["duration_frames"] = end - start
                item["timing_transform"]["output_duration_ms"] = (
                    (end - start) * 1000 // fps
                )
                assigned_frames += end - start
        if assigned_frames != section_frames:
            raise CustomFilmContractError(
                "Custom Film normalized assets do not exactly fill their section"
            )

        transition_frames = min(max(1, fps // 2), max(1, section_frames // 4))
        voice_urls = list(supplement.get("voice_over_urls") or [])
        voice_hashes = list(supplement.get("voice_over_sha256") or [])
        voice_durations = list(
            supplement.get("voice_over_duration_ms") or []
        )
        if section["dialogue_audio"] == "voice_over" and (
            len(voice_urls) != len(scenes_by_section[section_id])
            or (
                require_source_hashes
                and (
                    len(voice_hashes) != len(voice_urls)
                    or len(voice_durations) != len(voice_urls)
                    or any(
                        not isinstance(value, str)
                        or len(value) != 64
                        or any(char not in "0123456789abcdef" for char in value)
                        for value in voice_hashes
                    )
                )
            )
        ):
            raise CustomFilmContractError(
                "Custom Film exact voice-over inputs are incomplete"
            )
        if section["dialogue_audio"] == "voice_over":
            if require_source_hashes:
                source_voice_ms = sum(
                    _exact_int(value, "voice source duration", 1)
                    for value in voice_durations
                )
                audio_transform = _audio_timing_transform(
                    source_voice_ms, duration_seconds * 1000
                )
                caption_source_durations = voice_durations
            else:
                audio_transform = {
                    "mode": "pending_source_probe",
                    "source_duration_ms": None,
                    "output_duration_ms": duration_seconds * 1000,
                    "atempo_chain": [],
                    "caption_scale": None,
                }
                caption_source_durations = _allocate_integer(
                    duration_seconds * 1000, len(assigned_scene_ids)
                )
        else:
            audio_transform = {
                "mode": "source_clip",
                "source_duration_ms": duration_seconds * 1000,
                "output_duration_ms": duration_seconds * 1000,
                "atempo_chain": [],
                "caption_scale": 1.0,
            }
            caption_source_durations = _allocate_integer(
                duration_seconds * 1000, len(assigned_scene_ids)
            )
        captions: list[dict[str, Any]] = []
        source_elapsed_ms = 0
        target_ms = duration_seconds * 1000
        source_total_ms = sum(caption_source_durations)
        for scene_index, (scene_id, source_scene_ms) in enumerate(
            zip(assigned_scene_ids, caption_source_durations)
        ):
            start_ms = (
                source_elapsed_ms * target_ms // source_total_ms
            )
            source_elapsed_ms += int(source_scene_ms)
            end_ms = (
                target_ms
                if scene_index == len(assigned_scene_ids) - 1
                else source_elapsed_ms * target_ms // source_total_ms
            )
            captions.append(
                {
                    "scene_id": scene_id,
                    "text": str(
                        scene_rows_by_id[scene_id].get("scene_text") or ""
                    ).strip(),
                        "language": copy.deepcopy(
                            _mapping(section["language"], "section language")
                        ),
                    "section_start_ms": start_ms,
                    "section_end_ms": end_ms,
                    "start_frame": film_frame + (start_ms * fps // 1000),
                    "end_frame": film_frame + (end_ms * fps // 1000),
                }
            )
        if any(
            not caption["text"]
            or caption["end_frame"] <= caption["start_frame"]
            for caption in captions
        ):
            raise CustomFilmContractError("Custom Film caption timing or text is invalid")
        manifest_sections.append(
            {
                "section_id": section_id,
                "order_index": order_index,
                "role": str(section.get("role") or ""),
                "render_mode": str(section["render_mode"]),
                "visual_profile": str(section["visual_profile"]),
                "dialogue_audio": str(section["dialogue_audio"]),
                "start_frame": film_frame,
                "duration_frames": section_frames,
                "transition_in": {
                    "type": "dip_from_black" if order_index else "none",
                    "duration_frames": transition_frames if order_index else 0,
                    "overlap_frames": 0,
                    "accounting": "inside_section",
                    "audio": "fade_in",
                },
                "transition_out": {
                    "type": (
                        "dip_to_black"
                        if order_index < len(sections_value) - 1
                        else "none"
                    ),
                    "duration_frames": (
                        transition_frames
                        if order_index < len(sections_value) - 1
                        else 0
                    ),
                    "overlap_frames": 0,
                    "accounting": "inside_section",
                    "audio": "fade_out",
                },
                "scene_ids": scenes_by_section[section_id],
                "assets": manifest_assets,
                "audio": {
                    "mode": (
                        "source_clip"
                        if section["dialogue_audio"] == "grok_native"
                        else "voice_over"
                    ),
                    "source_urls": voice_urls,
                    "source_sha256": voice_hashes,
                    "source_duration_ms": voice_durations,
                    "timing_transform": audio_transform,
                    "gain_db": 0,
                },
                "captions": captions,
            }
        )
        film_frame += section_frames

    if film_frame != int(envelope["total_duration_seconds"]) * fps:
        raise CustomFilmContractError("Custom Film total film frames drifted")
    body = {
        "assembly_version": assembly_version,
        "tenant_id": tenant_id,
        "video_id": str(envelope["video_id"]),
        "plan_id": str(envelope["plan_id"]),
        "runtime_hash": str(envelope["runtime_hash"]),
        "runtime_job_id": runtime_job_id,
        "fps": fps,
        "width": width,
        "height": height,
        "total_duration_seconds": int(envelope["total_duration_seconds"]),
        "total_frames": film_frame,
        "transition_accounting": {
            "type": "dip_to_black_non_overlap",
            "duration_source": "min(half_second, quarter_section)",
            "overlap_frames_total": 0,
            "duration_lives_inside_assigned_sections": True,
        },
        "sections": manifest_sections,
    }
    if assembly_version in {ASSEMBLY_VERSION_V2, ASSEMBLY_VERSION_V3}:
        body.update(
            {
                "plan_hash": str(envelope["plan_hash"]),
                "quote_inputs_hash": str(envelope["quote_inputs_hash"]),
                "approval_hash": str(envelope["approval_hash"]),
                "max_spend": envelope["max_spend"],
                "render_engine": render_engine,
            }
        )
    if assembly_version == ASSEMBLY_VERSION_V3:
        from custom_film_remotion import (
            REMOTION_RENDERER_CONTRACT_VERSION,
            renderer_bundle_hash,
        )

        body.update(
            {
                "renderer_contract_version": (
                    REMOTION_RENDERER_CONTRACT_VERSION
                ),
                "renderer_bundle_hash": renderer_bundle_hash(),
            }
        )
    body["manifest_hash"] = canonical_hash(body)
    return body


async def _run(command: list[str]) -> None:
    if command and command[0] == "ffmpeg":
        command = [*command[:-1], "-map_metadata", "-1", command[-1]]
    proc = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _stdout, stderr = await proc.communicate()
    if proc.returncode:
        raise RuntimeError(
            f"Custom Film compositor command failed: "
            f"{stderr.decode(errors='replace')[-1200:]}"
        )


async def probe_media(path: Path) -> dict[str, Any]:
    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        (
            "format=duration:"
            "stream=codec_type,width,height,nb_frames,avg_frame_rate,r_frame_rate:"
            "stream_tags=language"
        ),
        "-of",
        "json",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode:
        raise RuntimeError(stderr.decode(errors="replace"))
    data = json.loads(stdout)
    streams = data.get("streams") or []
    video = next((row for row in streams if row.get("codec_type") == "video"), {})
    raw_rate = str(
        video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/0"
    )
    try:
        frame_rate = Fraction(raw_rate)
    except (ValueError, ZeroDivisionError):
        frame_rate = Fraction(0, 1)
    if frame_rate <= 0:
        fallback_rate = str(video.get("r_frame_rate") or "0/0")
        try:
            frame_rate = Fraction(fallback_rate)
        except (ValueError, ZeroDivisionError):
            frame_rate = Fraction(0, 1)
    return {
        "duration_seconds": float(data["format"]["duration"]),
        "width": video.get("width"),
        "height": video.get("height"),
        "frame_count": (
            int(video["nb_frames"])
            if str(video.get("nb_frames") or "").isdigit()
            else None
        ),
        "fps": (
            frame_rate.numerator
            if frame_rate.denominator == 1
            else float(frame_rate)
        ) if frame_rate > 0 else None,
        "fps_fraction": (
            f"{frame_rate.numerator}/{frame_rate.denominator}"
            if frame_rate > 0
            else None
        ),
        "has_video": bool(video),
        "has_audio": any(row.get("codec_type") == "audio" for row in streams),
        "has_subtitles": any(
            row.get("codec_type") == "subtitle" for row in streams
        ),
        "subtitle_languages": [
            str((row.get("tags") or {}).get("language") or "und")
            for row in streams
            if row.get("codec_type") == "subtitle"
        ],
    }


def _probe_has_exact_fps(probe: Mapping[str, Any], expected_fps: int) -> bool:
    """Compare the probed rational frame rate without float tolerance."""
    value = probe.get("fps_fraction")
    if not isinstance(value, str):
        return False
    try:
        return Fraction(value) == Fraction(expected_fps, 1)
    except (ValueError, ZeroDivisionError):
        return False


def _srt_timestamp(frame: int, fps: int) -> str:
    milliseconds = round(frame * 1000 / fps)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def _subtitle_language_metadata(captions: Sequence[Mapping[str, Any]]) -> str:
    languages: set[str] = set()
    mixed = False
    for caption in captions:
        language = _mapping(caption.get("language"), "caption language")
        mode = str(language.get("mode") or "")
        declared = language.get("languages")
        if mode == "bilingual":
            mixed = True
        if isinstance(declared, list):
            languages.update(
                str(value).strip().lower()
                for value in declared
                if str(value).strip()
            )
        single = str(language.get("language") or "").strip().lower()
        if single:
            languages.add(single)
    if mixed or len(languages) > 1:
        return "mul"
    # Do not guess ISO-639 metadata from narrator/profile modes.
    return next(iter(languages), "und")


def _write_visible_overlay(
    path: Path,
    *,
    text: str,
    width: int,
    height: int,
    card: bool,
) -> None:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    font_size = max(18, width // (34 if card else 30))
    # Pillow's bitmap fallback renders common creator punctuation (notably the
    # bullet used by evidence-card subtitles) as a missing-glyph box. Require a
    # Unicode-capable system font so burned-in production text never silently
    # claims to be readable when it is not.
    font = None
    for font_source in (
        "DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ):
        try:
            font = ImageFont.truetype(font_source, size=font_size)
            break
        except OSError:
            continue
    if font is None:
        raise CustomFilmContractError(
            "Custom Film cannot burn readable captions because no Unicode font "
            "is available"
        )
    max_chars = max(18, width // max(10, font_size // 2))
    lines = textwrap.wrap(text, width=max_chars)[:4 if card else 3]
    rendered_text = "\n".join(lines)
    bbox = draw.multiline_textbbox(
        (0, 0), rendered_text, font=font, spacing=font_size // 4,
        align="left" if card else "center",
    )
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    padding = max(16, font_size // 2)
    if card:
        left = width // 18
        top = height // 14
    else:
        left = max(padding, (width - text_w) // 2)
        top = height - text_h - padding * 3
    panel = (
        left - padding,
        top - padding,
        min(width - padding, left + text_w + padding),
        min(height - padding, top + text_h + padding),
    )
    draw.rounded_rectangle(
        panel,
        radius=max(8, font_size // 3),
        fill=(0, 0, 0, 210),
        outline=(255, 255, 255, 90),
        width=max(1, width // 640),
    )
    draw.multiline_text(
        (left, top),
        rendered_text,
        font=font,
        fill=(255, 255, 255, 255),
        spacing=font_size // 4,
        align="left" if card else "center",
        stroke_width=max(1, font_size // 20),
        stroke_fill=(0, 0, 0, 255),
    )
    image.save(path)


async def render_local_manifest(
    manifest_value: Any,
    *,
    source_paths: Mapping[str, Path | str],
    output_path: Path,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Render a manifest using only explicitly supplied local source paths."""
    manifest = _mapping(manifest_value, "assembly manifest")
    manifest_hash = str(manifest.pop("manifest_hash", ""))
    if manifest_hash != canonical_hash(manifest):
        raise CustomFilmContractError("Custom Film assembly manifest hash changed")
    manifest["manifest_hash"] = manifest_hash
    fps = _exact_int(manifest.get("fps"), "assembly fps", 1)
    width = _exact_int(manifest.get("width"), "assembly width", 2)
    height = _exact_int(manifest.get("height"), "assembly height", 2)
    total_frames = _exact_int(manifest.get("total_frames"), "film frames", 1)
    workdir = Path(tempfile.mkdtemp(prefix="custom_film_assembly_"))
    normalized: list[Path] = []
    section_slices: list[tuple[int, int]] = []
    provenance: list[dict[str, Any]] = []
    try:
        asset_number = 0
        for section in manifest["sections"]:
            section_start_index = len(normalized)
            section_assets = section["assets"]
            for section_asset_index, asset in enumerate(section_assets):
                asset_id = str(asset["asset_id"])
                source = Path(source_paths.get(asset_id, ""))
                if not source.is_file() or source.stat().st_size == 0:
                    raise CustomFilmContractError(
                        f"Custom Film local source is missing for asset {asset_id}"
                    )
                expected_source_hash = asset.get("source_sha256")
                actual_source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
                if expected_source_hash and actual_source_hash != expected_source_hash:
                    raise CustomFilmContractError(
                        f"Custom Film downloaded source hash changed for asset {asset_id}"
                    )
                if section["render_mode"] != "static_docu":
                    raw_probe = await probe_media(source)
                    actual_duration_ms = round(
                        float(raw_probe["duration_seconds"]) * 1000
                    )
                    if (
                        not raw_probe["has_video"]
                        or actual_duration_ms
                        != int(asset["actual_duration_ms"])
                    ):
                        raise CustomFilmContractError(
                            "Custom Film raw clip duration or stream no longer "
                            "matches accepted provenance"
                        )
                frames = int(asset["duration_frames"])
                seconds = frames / fps
                fade_in_frames = (
                    int(section["transition_in"]["duration_frames"])
                    if section_asset_index == 0
                    else 0
                )
                fade_out_frames = (
                    int(section["transition_out"]["duration_frames"])
                    if section_asset_index == len(section_assets) - 1
                    else 0
                )
                video_fades = ""
                audio_fades = ""
                if fade_in_frames:
                    video_fades += (
                        f",fade=t=in:st=0:d={fade_in_frames / fps:.9f}:color=black"
                    )
                    audio_fades += (
                        f",afade=t=in:st=0:d={fade_in_frames / fps:.9f}"
                    )
                if fade_out_frames:
                    fade_out_start = max(0, (frames - fade_out_frames) / fps)
                    video_fades += (
                        f",fade=t=out:st={fade_out_start:.9f}:"
                        f"d={fade_out_frames / fps:.9f}:color=black"
                    )
                    audio_fades += (
                        f",afade=t=out:st={fade_out_start:.9f}:"
                        f"d={fade_out_frames / fps:.9f}"
                    )
                out = workdir / f"normalized_{asset_number:04d}.mp4"
                asset_number += 1
                if section["render_mode"] == "static_docu":
                    zoom = (
                        f"zoompan=z='min(zoom+0.0005,1.08)':"
                        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                        f"d={frames}:s={width}x{height}:fps={fps}"
                    )
                    command = [
                        "ffmpeg", "-y", "-loop", "1", "-i", str(source),
                        "-f", "lavfi", "-i",
                        f"anullsrc=channel_layout=stereo:sample_rate=48000",
                        "-filter_complex",
                        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
                        f"crop={width}:{height},{zoom},trim=end_frame={frames},"
                        f"setpts=N/({fps}*TB){video_fades}[v];"
                        f"[1:a]atrim=duration={seconds:.9f},asetpts=N/SR/TB"
                        f"{audio_fades}[a]",
                        "-map", "[v]", "-map", "[a]", "-t", f"{seconds:.9f}",
                        "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast",
                        "-crf", "18", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-ar", "48000", "-ac", "2",
                        "-shortest", str(out),
                    ]
                else:
                    transform = asset["timing_transform"]
                    loop_args = (
                        ["-stream_loop", "-1"]
                        if transform["mode"] == "repeat_then_trim"
                        else []
                    )
                    source_audio = section["audio"]["mode"] == "source_clip"
                    command = [
                        "ffmpeg", "-y", *loop_args, "-i", str(source),
                        "-f", "lavfi", "-i",
                        "anullsrc=channel_layout=stereo:sample_rate=48000",
                        "-filter_complex",
                        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
                        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,"
                        f"fps={fps},trim=end_frame={frames},setpts=N/({fps}*TB)"
                        f"{video_fades}[v];"
                        + (
                            f"[0:a]aresample=48000,apad,atrim=duration={seconds:.9f},"
                            f"asetpts=N/SR/TB{audio_fades}[a]"
                            if source_audio
                            else f"[1:a]atrim=duration={seconds:.9f},"
                            f"asetpts=N/SR/TB{audio_fades}[a]"
                        ),
                        "-map", "[v]", "-map", "[a]", "-t", f"{seconds:.9f}",
                        "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast",
                        "-crf", "18", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-ar", "48000", "-ac", "2",
                        "-shortest", str(out),
                    ]
                if on_progress:
                    await on_progress(
                        f"Normalizing section {section['order_index'] + 1}/"
                        f"{len(manifest['sections'])}, asset "
                        f"{len(normalized) + 1}"
                    )
                await _run(command)
                probe = await probe_media(out)
                if (
                    probe["width"] != width
                    or probe["height"] != height
                    or not _probe_has_exact_fps(probe, fps)
                    or abs(probe["duration_seconds"] - seconds) > (1 / fps + 0.002)
                ):
                    raise CustomFilmContractError(
                        "Custom Film normalized artifact failed exact media probe"
                    )
                normalized.append(out)
                provenance.append(
                    {
                        "asset_id": asset_id,
                        "source_sha256": actual_source_hash,
                        "source_duration_ms": asset.get("actual_duration_ms"),
                        "timing_transform": copy.deepcopy(asset["timing_transform"]),
                        "normalized_frames": frames,
                        "normalized_sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
                    }
                )
            section_slices.append((section_start_index, len(normalized)))
        section_outputs: list[Path] = []
        section_provenance: list[dict[str, Any]] = []
        if on_progress:
            await on_progress(
                f"Assembling sections 0/{len(manifest['sections'])}"
            )
        for section, (start_index, end_index) in zip(
            manifest["sections"], section_slices
        ):
            section_list = workdir / f"section_{section['order_index']:03d}.txt"
            section_list.write_text(
                "".join(
                    f"file '{path.as_posix()}'\n"
                    for path in normalized[start_index:end_index]
                ),
                encoding="utf-8",
            )
            silent_section = workdir / (
                f"section_{section['order_index']:03d}_visual.mp4"
            )
            await _run(
                [
                    "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(section_list), "-c:v", "libx264",
                    "-preset", "veryfast", "-crf", "18",
                    "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-ar", "48000", "-ac", "2", "-r", str(fps),
                    "-frames:v", str(section["duration_frames"]),
                    str(silent_section),
                ]
            )
            if section["audio"]["mode"] == "voice_over":
                urls = list(section["audio"].get("source_urls") or [])
                audio_paths = [
                    Path(source_paths.get(
                        f"audio:{section['section_id']}:{index}", ""
                    ))
                    for index in range(len(urls))
                ]
                if not audio_paths or any(
                    not path.is_file() or path.stat().st_size == 0
                    for path in audio_paths
                ):
                    raise CustomFilmContractError(
                        "Custom Film voice-over section has no exact local narration"
                    )
                audio_hashes = list(section["audio"].get("source_sha256") or [])
                audio_durations = list(
                    section["audio"].get("source_duration_ms") or []
                )
                if len(audio_hashes) != len(audio_paths) or any(
                    hashlib.sha256(path.read_bytes()).hexdigest() != expected
                    for path, expected in zip(audio_paths, audio_hashes)
                ):
                    raise CustomFilmContractError(
                        "Custom Film narration source hash changed"
                    )
                if len(audio_durations) != len(audio_paths):
                    raise CustomFilmContractError(
                        "Custom Film narration duration evidence is incomplete"
                    )
                for audio_path, expected_duration_ms in zip(
                    audio_paths, audio_durations
                ):
                    audio_probe = await probe_media(audio_path)
                    if (
                        not audio_probe["has_audio"]
                        or audio_probe["has_video"]
                        or round(audio_probe["duration_seconds"] * 1000)
                        != int(expected_duration_ms)
                    ):
                        raise CustomFilmContractError(
                            "Custom Film narration stream or duration changed"
                        )
                section_seconds = section["duration_frames"] / fps
                voiced_section = workdir / (
                    f"section_{section['order_index']:03d}_voiced.mp4"
                )
                command = ["ffmpeg", "-y", "-i", str(silent_section)]
                for audio_path in audio_paths:
                    command.extend(["-i", str(audio_path)])
                labels = "".join(f"[{index + 1}:a]" for index in range(len(audio_paths)))
                transition_in_seconds = (
                    section["transition_in"]["duration_frames"] / fps
                )
                transition_out_seconds = (
                    section["transition_out"]["duration_frames"] / fps
                )
                audio_filter = (
                    f"{labels}concat=n={len(audio_paths)}:v=0:a=1,"
                    "aresample=48000"
                )
                timing_transform = section["audio"]["timing_transform"]
                for atempo in timing_transform.get("atempo_chain") or []:
                    audio_filter += f",atempo={float(atempo):.9f}"
                audio_filter += (
                    f",atrim=duration={section_seconds:.9f},asetpts=N/SR/TB"
                )
                if transition_in_seconds:
                    audio_filter += (
                        f",afade=t=in:st=0:d={transition_in_seconds:.9f}"
                    )
                if transition_out_seconds:
                    audio_filter += (
                        f",afade=t=out:st="
                        f"{max(0, section_seconds-transition_out_seconds):.9f}:"
                        f"d={transition_out_seconds:.9f}"
                    )
                audio_filter += "[section_audio]"
                command.extend(
                    [
                        "-filter_complex", audio_filter,
                        "-map", "0:v", "-map", "[section_audio]",
                        "-c:v", "copy", "-c:a", "aac", "-ar", "48000",
                        "-ac", "2", "-t", f"{section_seconds:.9f}",
                        str(voiced_section),
                    ]
                )
                await _run(command)
                section_outputs.append(voiced_section)
            else:
                section_outputs.append(silent_section)
            section_output = section_outputs[-1]
            section_provenance.append(
                {
                    "section_id": section["section_id"],
                    "order_index": section["order_index"],
                    "start_frame": section["start_frame"],
                    "duration_frames": section["duration_frames"],
                    "section_sha256": hashlib.sha256(
                        section_output.read_bytes()
                    ).hexdigest(),
                }
            )
            if on_progress:
                await on_progress(
                    f"Assembling section {section['order_index'] + 1}/"
                    f"{len(manifest['sections'])}"
                )
        concat_file = workdir / "concat.txt"
        concat_file.write_text(
            "".join(f"file '{path.as_posix()}'\n" for path in section_outputs),
            encoding="utf-8",
        )
        rendered = workdir / "film.mp4"
        if on_progress:
            await on_progress(
                f"Rendering {len(manifest['sections'])}/"
                f"{len(manifest['sections'])} approved sections"
            )
        await _run(
            [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", str(concat_file), "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac",
                "-ar", "48000", "-ac", "2", "-r", str(fps),
                "-vf",
                f"fps={fps},tpad=stop_mode=clone:stop_duration=1,"
                f"trim=end_frame={total_frames},setpts=N/({fps}*TB)",
                "-frames:v", str(total_frames), str(rendered),
            ]
        )
        captions = [
            caption
            for section in manifest["sections"]
            for caption in section.get("captions", [])
        ]
        final_source = rendered
        if captions:
            visible_entries: list[dict[str, Any]] = [
                {
                    "text": caption["text"],
                    "start_frame": caption["start_frame"],
                    "end_frame": caption["end_frame"],
                    "card": False,
                }
                for caption in captions
            ]
            for section in manifest["sections"]:
                for asset in section["assets"]:
                    card = asset.get("caption_card")
                    if not isinstance(card, Mapping):
                        continue
                    card_text = "\n".join(
                        [
                            str(card.get("title") or "").strip(),
                            str(card.get("sub") or "").strip(),
                            *[
                                str(value).strip()
                                for value in (card.get("specs") or [])
                                if str(value).strip()
                            ],
                        ]
                    ).strip()
                    if card_text:
                        visible_entries.append(
                            {
                                "text": card_text,
                                "start_frame": section["start_frame"]
                                + asset["start_frame"],
                                "end_frame": section["start_frame"]
                                + asset["start_frame"]
                                + asset["duration_frames"],
                                "card": True,
                            }
                        )
            overlay_paths: list[Path] = []
            for index, entry in enumerate(visible_entries):
                overlay = workdir / f"overlay_{index:04d}.png"
                _write_visible_overlay(
                    overlay,
                    text=entry["text"],
                    width=width,
                    height=height,
                    card=bool(entry["card"]),
                )
                overlay_paths.append(overlay)
            burned = workdir / "film_visible_captions.mp4"
            overlay_command = ["ffmpeg", "-y", "-i", str(rendered)]
            for overlay in overlay_paths:
                overlay_command.extend(["-loop", "1", "-i", str(overlay)])
            filters: list[str] = []
            previous = "[0:v]"
            for index, entry in enumerate(visible_entries, 1):
                output_label = f"[captioned_{index}]"
                filters.append(
                    f"{previous}[{index}:v]overlay=0:0:"
                    f"enable='between(n,{entry['start_frame']},"
                    f"{entry['end_frame'] - 1})'{output_label}"
                )
                previous = output_label
            overlay_command.extend(
                [
                    "-filter_complex", ";".join(filters),
                    "-map", previous, "-map", "0:a",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                    "-pix_fmt", "yuv420p", "-c:a", "copy",
                    "-frames:v", str(total_frames), str(burned),
                ]
            )
            await _run(overlay_command)
            srt = workdir / "captions.srt"
            srt.write_text(
                "\n".join(
                    f"{index}\n{_srt_timestamp(caption['start_frame'], fps)} --> "
                    f"{_srt_timestamp(caption['end_frame'], fps)}\n"
                    f"{caption['text']}\n"
                    for index, caption in enumerate(captions, 1)
                ),
                encoding="utf-8",
            )
            captioned = workdir / "film_captioned.mp4"
            subtitle_language = _subtitle_language_metadata(captions)
            await _run(
                [
                    "ffmpeg", "-y", "-i", str(burned), "-i", str(srt),
                    "-map", "0:v", "-map", "0:a", "-map", "1:0",
                    "-c:v", "copy", "-c:a", "copy", "-c:s", "mov_text",
                    "-metadata:s:s:0", f"language={subtitle_language}",
                    str(captioned),
                ]
            )
            final_source = captioned
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(final_source, output_path)
        probe = await probe_media(output_path)
        expected_seconds = total_frames / fps
        if (
            not probe["has_video"]
            or not probe["has_audio"]
            or probe["width"] != width
            or probe["height"] != height
            or probe["frame_count"] != total_frames
            or not _probe_has_exact_fps(probe, fps)
            or abs(probe["duration_seconds"] - expected_seconds) > (1 / fps + 0.002)
        ):
            raise CustomFilmContractError(
                "Custom Film final artifact failed exact duration/stream probe"
            )
        artifact_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()
        return {
            "status": "rendered_local",
            "manifest_hash": manifest_hash,
            "artifact_sha256": artifact_hash,
            "duration_seconds": expected_seconds,
            "total_frames": total_frames,
            "fps": fps,
            "resolution": f"{width}x{height}",
            "section_count": len(manifest["sections"]),
            "asset_count": len(normalized),
            "captions": captions,
            "provenance": provenance,
            "section_provenance": section_provenance,
            "output_path": str(output_path),
        }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


async def _validate_local_render_result(
    result_value: Any,
    *,
    manifest: Mapping[str, Any],
    output_path: Path,
) -> dict[str, Any]:
    """Require an alternate renderer to satisfy the FFmpeg result contract."""
    if not isinstance(result_value, Mapping):
        raise CustomFilmContractError(
            "Custom Film local renderer returned an invalid result"
        )
    result = copy.deepcopy(dict(result_value))
    required = {
        "status",
        "manifest_hash",
        "artifact_sha256",
        "duration_seconds",
        "total_frames",
        "fps",
        "resolution",
        "section_count",
        "asset_count",
        "captions",
        "provenance",
        "section_provenance",
        "output_path",
    }
    if not required.issubset(result):
        raise CustomFilmContractError(
            "Custom Film local renderer result contract is incomplete"
        )
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise CustomFilmContractError(
            "Custom Film local renderer produced no artifact"
        )
    expected_seconds = int(manifest["total_frames"]) / int(manifest["fps"])
    expected_resolution = f"{manifest['width']}x{manifest['height']}"
    expected_captions = [
        caption
        for section in manifest["sections"]
        for caption in section.get("captions", [])
    ]
    expected_asset_count = sum(
        len(section["assets"]) for section in manifest["sections"]
    )
    actual_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()
    try:
        result_path_matches = Path(str(result["output_path"])).resolve() == (
            output_path.resolve()
        )
    except (OSError, RuntimeError):
        result_path_matches = False
    if (
        result["status"] != "rendered_local"
        or result["manifest_hash"] != manifest["manifest_hash"]
        or result["artifact_sha256"] != actual_hash
        or result["duration_seconds"] != expected_seconds
        or result["total_frames"] != manifest["total_frames"]
        or result["fps"] != manifest["fps"]
        or result["resolution"] != expected_resolution
        or result["section_count"] != len(manifest["sections"])
        or result["asset_count"] != expected_asset_count
        or result["captions"] != expected_captions
        or not isinstance(result["provenance"], list)
        or not isinstance(result["section_provenance"], list)
        or not result_path_matches
    ):
        raise CustomFilmContractError(
            "Custom Film local renderer result changed the approved contract"
        )
    probe = await probe_media(output_path)
    if (
        probe["frame_count"] != manifest["total_frames"]
        or probe["width"] != manifest["width"]
        or probe["height"] != manifest["height"]
        or not _probe_has_exact_fps(probe, int(manifest["fps"]))
        or not probe["has_video"]
        or not probe["has_audio"]
        or (
            bool(expected_captions)
            and not probe["has_subtitles"]
        )
        or abs(probe["duration_seconds"] - expected_seconds)
        > (1 / int(manifest["fps"]) + 0.002)
    ):
        raise CustomFilmContractError(
            "Custom Film local renderer artifact failed exact media probe"
        )
    return result


async def render_manifest_with_engine(
    manifest_value: Any,
    *,
    source_paths: Mapping[str, Path | str],
    output_path: Path,
    on_progress: ProgressCallback | None = None,
    remotion_renderer: RemotionRenderer | None = None,
) -> dict[str, Any]:
    """Dispatch one already-selected, hash-bound local render engine.

    There is deliberately no fallback here.  Engine fallback is only legal in
    ``resolve_render_engine`` before the assembly manifest is hashed/journaled.
    """
    manifest = _mapping(manifest_value, "assembly manifest")
    manifest_hash = str(manifest.pop("manifest_hash", ""))
    if manifest_hash != canonical_hash(manifest):
        raise CustomFilmContractError("Custom Film assembly manifest hash changed")
    manifest["manifest_hash"] = manifest_hash
    assembly_version = str(manifest.get("assembly_version") or "")
    if assembly_version == ASSEMBLY_VERSION_V1:
        if "render_engine" in manifest:
            raise CustomFilmContractError(
                "Custom Film assembly v1 renderer identity changed"
            )
        engine = "ffmpeg"
    elif assembly_version in {ASSEMBLY_VERSION_V2, ASSEMBLY_VERSION_V3}:
        engine = str(manifest.get("render_engine") or "")
    else:
        raise CustomFilmContractError("Custom Film assembly version is unsupported")
    if engine == "ffmpeg":
        result = await render_local_manifest(
            manifest,
            source_paths=source_paths,
            output_path=output_path,
            on_progress=on_progress,
        )
    elif engine == "remotion":
        if remotion_renderer is None:
            raise CustomFilmContractError(
                "Custom Film Remotion was selected but no renderer is available"
            )
        from custom_film_remotion import build_remotion_props

        remotion_props = build_remotion_props(manifest)
        result = await remotion_renderer(
            remotion_props=remotion_props,
            source_paths=source_paths,
            output_path=output_path,
            on_progress=on_progress,
        )
    else:
        raise CustomFilmContractError("Custom Film render engine is unsupported")
    validated = await _validate_local_render_result(
        result, manifest=manifest, output_path=output_path
    )
    validated["render_engine"] = engine
    return validated


def custom_film_output_dimensions(
    aspect_ratio: str, resolution: str
) -> tuple[int, int]:
    """Return the exact supported Custom Film canvas or fail closed."""
    output_dimensions = {
        ("16:9", "1080p"): (1920, 1080),
        ("16:9", "720p"): (1280, 720),
        ("9:16", "720p"): (720, 1280),
        ("16:9", "480p"): (854, 480),
        ("9:16", "480p"): (480, 854),
    }.get((str(aspect_ratio), str(resolution)))
    if output_dimensions is None:
        raise CustomFilmContractError(
            "Custom Film output aspect ratio or resolution is unsupported"
        )
    return output_dimensions


async def _load_current_inputs(
    tenant_id: str, video_id: str
) -> dict[str, Any]:
    """Read every assembly input in one repeatable-read snapshot."""
    import database

    pool = await database.get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            video = await conn.fetchrow(
                """SELECT custom_film_plan_id::text, custom_film_plan_hash,
                          aspect_ratio, video_resolution
                   FROM videos
                   WHERE tenant_id = $1::uuid AND id = $2::uuid""",
                tenant_id,
                video_id,
            )
            if not video or not str(video.get("custom_film_plan_id") or ""):
                raise CustomFilmContractError(
                    "Custom Film current video plan pointer is missing"
                )
            task = await conn.fetchrow(
                """SELECT job_id, runtime_envelope, runtime_progress, status
                   FROM background_tasks
                   WHERE tenant_id = $1::uuid AND video_id = $2::uuid
                     AND task_type = 'custom_film_runtime'
                   ORDER BY created_at DESC
                   LIMIT 1""",
                tenant_id,
                video_id,
            )
            if not task or task.get("status") != "completed":
                raise CustomFilmContractError(
                    "Custom Film section runtime is not durably complete"
                )
            envelope = _mapping(task["runtime_envelope"], "runtime envelope")
            if str(envelope.get("video_id") or "") != video_id:
                raise CustomFilmContractError("Custom Film runtime identity changed")
            if (
                str(video.get("custom_film_plan_id") or "")
                != str(envelope.get("plan_id") or "")
                or str(video.get("custom_film_plan_hash") or "")
                != str(envelope.get("plan_hash") or "")
            ):
                raise CustomFilmContractError(
                    "Custom Film current video no longer points at this runtime plan"
                )
            aspect_ratio = str(video.get("aspect_ratio") or "")
            resolution = str(video.get("video_resolution") or "")
            output_dimensions = custom_film_output_dimensions(
                aspect_ratio, resolution
            )
            plan_record = await conn.fetchrow(
                """SELECT quote_inputs, quote_inputs_hash
                   FROM custom_film_plans
                   WHERE tenant_id = $1::uuid AND video_id = $2::uuid
                     AND id = $3::uuid""",
                tenant_id,
                video_id,
                envelope["plan_id"],
            )
            if not plan_record:
                raise CustomFilmContractError(
                    "Custom Film approved quote is missing"
                )
            quote_inputs = _mapping(
                plan_record["quote_inputs"],
                "approved quote inputs",
            )
            quote_inputs_hash = canonical_hash(quote_inputs)
            if (
                quote_inputs_hash
                != str(plan_record.get("quote_inputs_hash") or "")
                or quote_inputs_hash
                != str(envelope.get("quote_inputs_hash") or "")
            ):
                raise CustomFilmContractError(
                    "Custom Film approved quote identity changed"
                )
            finishing_canvas = quote_inputs.get("finishing_canvas")
            exact_finishing_canvas = {
                "engine": "remotion",
                "motion_plan_version": "storyengine-showcase-motion-plan-v1",
                "aspect_ratio": "16:9",
                "width": 1920,
                "height": 1080,
                "fps": 24,
            }
            # Source clips keep their approved generation tier (normally
            # 720p). Only a separately approved and hash-bound delivery canvas
            # may promote the exact flagship to 1080p Remotion finishing.
            from custom_film_remotion import is_storyengine_showcase_runtime

            if (
                aspect_ratio == "16:9"
                and finishing_canvas == exact_finishing_canvas
                and is_storyengine_showcase_runtime(envelope)
            ):
                output_dimensions = (1920, 1080)
                remotion_finishing_bound = True
            else:
                remotion_finishing_bound = False
            providers_raw = await conn.fetch(
                """SELECT tenant_id::text, video_id::text, runtime_job_id,
                          runtime_hash, stage_key, operation_id, state, result
                   FROM custom_film_provider_operations
                   WHERE tenant_id = $1::uuid AND video_id = $2::uuid
                     AND runtime_hash = $3""",
                tenant_id,
                video_id,
                envelope["runtime_hash"],
            )
            providers = [dict(row) for row in providers_raw]
            scene_records = await conn.fetch(
                """SELECT ss.tenant_id::text, ss.plan_id::text,
                          ss.video_id::text, ss.section_id::text,
                          ss.script_id::text, ss.scene_order,
                          s.scene, s.scene_text, s.script_validation,
                          s.voice_status, s.voice_over_url
                   FROM custom_film_section_scenes ss
                   JOIN scripts s
                     ON (s.tenant_id, s.video_id, s.id)
                      = (ss.tenant_id, ss.video_id, ss.script_id)
                   WHERE ss.tenant_id = $1::uuid
                     AND ss.video_id = $2::uuid
                     AND ss.plan_id = $3::uuid
                   ORDER BY ss.section_id, ss.scene_order""",
                tenant_id,
                video_id,
                envelope["plan_id"],
            )
            scene_rows = [dict(row) for row in scene_records]
            scenes_by_section: dict[str, list[dict[str, Any]]] = {}
            for row in scene_rows:
                scenes_by_section.setdefault(str(row["section_id"]), []).append(row)
            section_supplements: dict[str, dict[str, Any]] = {}
            for section in envelope["sections"]:
                values = scenes_by_section.get(str(section["section_id"]), [])
                voice_over_urls = [
                    str(row["voice_over_url"])
                    for row in values
                    if str(row.get("voice_over_url") or "").strip()
                ]
                if (
                    section["dialogue_audio"] == "voice_over"
                    and len(voice_over_urls) != len(values)
                ):
                    raise CustomFilmContractError(
                        "Custom Film current narration artifacts are incomplete"
                    )
                section_supplements[str(section["section_id"])] = {
                    "voice_over_urls": voice_over_urls,
                    "voice_over_sha256": [],
                    "voice_over_duration_ms": [],
                }
            asset_records = await conn.fetch(
                """SELECT DISTINCT ON (a.id)
                          a.id::text AS asset_id, a.tenant_id::text,
                          a.video_id::text, p.section_id::text,
                          ss.scene_order, a.image_index, a.image_url,
                          a.drive_image_url, a.video_prompt, a.video_clip_url,
                          a.generation_method, a.caption
                   FROM custom_film_asset_provenance p
                   JOIN assets a
                     ON (a.tenant_id, a.video_id, a.id)
                      = (p.tenant_id, p.video_id, p.asset_id)
                   JOIN custom_film_section_scenes ss
                     ON ss.tenant_id = p.tenant_id
                    AND ss.video_id = p.video_id
                    AND ss.plan_id = p.plan_id
                    AND ss.section_id = p.section_id
                   JOIN scripts s
                     ON (s.tenant_id, s.video_id, s.id)
                      = (ss.tenant_id, ss.video_id, ss.script_id)
                    AND s.scene = a.scene
                   WHERE p.tenant_id = $1::uuid
                     AND p.video_id = $2::uuid
                     AND p.runtime_hash = $3
                     AND p.stage IN ('pictures', 'motion', 'clips')
                   ORDER BY a.id, p.section_id, ss.scene_order, a.image_index""",
                tenant_id,
                video_id,
                envelope["runtime_hash"],
            )
            provenance_records = await conn.fetch(
                """SELECT tenant_id::text, video_id::text, asset_id::text,
                          plan_id::text, section_id::text, runtime_hash, stage,
                          operation_id, request_hash, section_contract_hash,
                          generation_method,
                          provider_model, status, artifact_url_hash,
                          actual_duration_ms, assigned_duration_ms,
                          timing_transform
                   FROM custom_film_asset_provenance
                   WHERE tenant_id = $1::uuid AND video_id = $2::uuid
                     AND runtime_hash = $3
                     AND stage IN ('pictures', 'motion', 'clips')
                   ORDER BY section_id, stage, asset_id""",
                tenant_id,
                video_id,
                envelope["runtime_hash"],
            )
    return {
        "envelope": envelope,
        "runtime_progress": task["runtime_progress"],
        "runtime_job_id": str(task["job_id"]),
        "provider_rows": providers,
        "scene_rows": scene_rows,
        "asset_rows": [dict(row) for row in asset_records],
        "provenance_rows": [dict(row) for row in provenance_records],
        "section_supplements": section_supplements,
        "output_width": output_dimensions[0],
        "output_height": output_dimensions[1],
        "remotion_finishing_bound": remotion_finishing_bound,
    }


async def _default_download(url: str, path: Path) -> None:
    from render_stitch import _extract_drive_file_id, _google_client

    file_id = _extract_drive_file_id(url)
    if file_id:
        client = _google_client()
        await asyncio.to_thread(client.download_file_to_local, file_id, str(path))
    else:
        from storage import download_bytes

        path.write_bytes(await download_bytes(url))


async def _default_upload(
    data: bytes, storage_path: str, tenant_id: str
) -> str:
    from storage import upload_bytes

    return await upload_bytes(data, storage_path, "video/mp4", tenant_id)


async def _default_readback(url: str) -> bytes:
    workdir = Path(tempfile.mkdtemp(prefix="custom_film_readback_"))
    try:
        path = workdir / "readback.mp4"
        await _default_download(url, path)
        return path.read_bytes()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


async def verify_stored_artifact(
    stored_bytes: bytes,
    *,
    expected_sha256: str,
    manifest: Mapping[str, Any],
    staging: Path,
) -> dict[str, Any]:
    """Prove the uploaded object is the exact rendered, playable artifact."""
    if (
        not stored_bytes
        or hashlib.sha256(stored_bytes).hexdigest() != expected_sha256
    ):
        raise CustomFilmRetryableError(
            "Custom Film stored artifact readback hash does not match"
        )
    readback_path = staging / "stored-readback.mp4"
    readback_path.write_bytes(stored_bytes)
    stored_probe = await probe_media(readback_path)
    if (
        stored_probe["frame_count"] != manifest["total_frames"]
        or stored_probe["width"] != manifest["width"]
        or stored_probe["height"] != manifest["height"]
        or not _probe_has_exact_fps(stored_probe, int(manifest["fps"]))
        or not stored_probe["has_video"]
        or not stored_probe["has_audio"]
        or (bool(manifest["sections"]) and not stored_probe["has_subtitles"])
        or abs(
            stored_probe["duration_seconds"]
            - manifest["total_frames"] / manifest["fps"]
        ) > (1 / manifest["fps"] + 0.002)
    ):
        raise CustomFilmRetryableError(
            "Custom Film stored artifact readback media probe does not match"
        )
    return stored_probe


async def render_custom_film_video(
    video_id: str,
    tenant_id: str,
    *,
    title: str = "",
    on_progress: ProgressCallback | None = None,
    downloader: Callable[[str, Path], Awaitable[None]] | None = None,
    uploader: Callable[[bytes, str, str], Awaitable[str]] | None = None,
    storage_reader: Callable[[str], Awaitable[bytes]] | None = None,
    render_engine: str | None = None,
    remotion_renderer: RemotionRenderer | None = None,
    pre_journal_fallback: str = "forbid",
) -> dict[str, Any]:
    """Production render door with durable render/upload reconciliation.

    The storage key is derived from the immutable runtime and manifest.  A
    crash after upload but before journaling therefore retries the same object
    identity instead of creating a second upload.
    """
    import database
    from custom_film_remotion import (
        AUTOMATIC_RENDER_POLICY,
        automatic_render_engine_for_runtime,
        resolve_durable_render_engine,
        resolve_render_engine,
    )

    download = downloader or _default_download
    upload = uploader or _default_upload
    readback = storage_reader or _default_readback
    inputs = await _load_current_inputs(tenant_id, video_id)
    pool = await database.get_pool()
    runtime_hash = str(inputs["envelope"]["runtime_hash"])
    runtime_job_id = str(inputs["runtime_job_id"])
    automatic_policy = render_engine == AUTOMATIC_RENDER_POLICY
    # A durable journal owns renderer selection on every retry.  Read and
    # validate it before any source media I/O so a default caller cannot
    # reinterpret a Remotion assembly as FFmpeg.
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            """SELECT state, runtime_job_id, manifest_version, manifest_hash,
                      artifact_sha256, manifest, artifact_probe, storage_path,
                      final_video_url
               FROM custom_film_assemblies
               WHERE tenant_id = $1::uuid AND video_id = $2::uuid
                 AND runtime_hash = $3""",
            tenant_id,
            video_id,
            runtime_hash,
        )
    durable_manifest: dict[str, Any] | None = None
    durable_manifest_hash = ""
    if existing:
        if str(existing["state"]) == "terminal_failed":
            raise CustomFilmContractError(
                "Custom Film assembly is terminally failed; a new approved "
                "runtime is required"
            )
        durable_manifest = _mapping(
            existing.get("manifest"), "durable assembly manifest"
        )
        durable_manifest_hash = str(durable_manifest.pop("manifest_hash", ""))
        if (
            str(existing["runtime_job_id"]) != runtime_job_id
            or durable_manifest_hash != str(existing["manifest_hash"] or "")
            or canonical_hash(durable_manifest) != durable_manifest_hash
            or str(durable_manifest.get("assembly_version") or "")
            != str(existing["manifest_version"] or "")
            or str(durable_manifest.get("runtime_hash") or "") != runtime_hash
        ):
            raise CustomFilmContractError(
                "Custom Film durable assembly identity is incomplete"
            )
        selected_render_engine = resolve_durable_render_engine(
            manifest_version=str(existing["manifest_version"]),
            manifest=durable_manifest,
            journal_state=str(existing["state"]),
            requested_engine=None if automatic_policy else render_engine,
            remotion_available=remotion_renderer is not None,
        )
        selected_assembly_version = str(existing["manifest_version"])
    else:
        requested_engine = (
            automatic_render_engine_for_runtime(
                inputs["envelope"],
                width=inputs["output_width"],
                height=inputs["output_height"],
                remotion_finishing_bound=bool(
                    inputs.get("remotion_finishing_bound")
                ),
            )
            if automatic_policy
            else render_engine
        )
        selected_render_engine = resolve_render_engine(
            requested_engine,
            remotion_available=remotion_renderer is not None,
            pre_journal_fallback=pre_journal_fallback,
        )
        selected_assembly_version = (
            ASSEMBLY_VERSION_V3
            if selected_render_engine == "remotion"
            else ASSEMBLY_VERSION_V2
        )
    preliminary = build_assembly_manifest(
        tenant_id=tenant_id,
        envelope_value=inputs["envelope"],
        runtime_job_id=inputs["runtime_job_id"],
        runtime_progress_value=inputs["runtime_progress"],
        provider_rows=inputs["provider_rows"],
        scene_rows=inputs["scene_rows"],
        asset_rows=inputs["asset_rows"],
        provenance_rows=inputs["provenance_rows"],
        section_supplements=inputs["section_supplements"],
        require_source_hashes=False,
        width=inputs["output_width"],
        height=inputs["output_height"],
        render_engine=selected_render_engine,
        assembly_version=selected_assembly_version,
    )
    if existing and str(existing["state"]) == "finalized":
        if (
            not str(existing["artifact_sha256"] or "")
            or str(existing["storage_path"] or "")
            != assembly_storage_path(
                video_id, runtime_hash, durable_manifest_hash
            )
            or not str(existing["final_video_url"] or "")
            or not isinstance(existing["artifact_probe"], Mapping)
        ):
            raise CustomFilmContractError(
                "Custom Film finalized assembly identity is incomplete"
            )
        return {
            "status": "rendered",
            "video_id": video_id,
            "final_video_url": str(existing["final_video_url"]),
            "render_engine": selected_render_engine,
            **_mapping(existing["artifact_probe"], "artifact probe"),
            "manifest_hash": durable_manifest_hash,
            "artifact_sha256": str(existing["artifact_sha256"]),
            "reused": True,
        }
    staging = Path(tempfile.mkdtemp(prefix=f"custom_film_{video_id[:8]}_"))
    try:
        source_paths: dict[str, Path] = {}
        for asset in [
            asset
            for section in preliminary["sections"]
            for asset in section["assets"]
        ]:
            path = staging / f"asset_{asset['asset_id']}"
            await download(str(asset["source_url"]), path)
            if not path.is_file() or path.stat().st_size == 0:
                raise CustomFilmContractError(
                    "Custom Film source download was empty"
                )
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            source_paths[str(asset["asset_id"])] = path
            for current in inputs["asset_rows"]:
                if str(current["asset_id"]) == str(asset["asset_id"]):
                    current["source_sha256"] = digest
        for section in inputs["envelope"]["sections"]:
            supplement = inputs["section_supplements"][str(section["section_id"])]
            for index, url in enumerate(supplement.get("voice_over_urls") or []):
                key = f"audio:{section['section_id']}:{index}"
                path = staging / f"{key.replace(':', '_')}.mp3"
                await download(str(url), path)
                if not path.is_file() or path.stat().st_size == 0:
                    raise CustomFilmContractError(
                        "Custom Film narration download was empty"
                    )
                supplement["voice_over_sha256"].append(
                    hashlib.sha256(path.read_bytes()).hexdigest()
                )
                voice_probe = await probe_media(path)
                if not voice_probe["has_audio"] or voice_probe["has_video"]:
                    raise CustomFilmContractError(
                        "Custom Film narration source has an invalid stream"
                    )
                supplement["voice_over_duration_ms"].append(
                    round(float(voice_probe["duration_seconds"]) * 1000)
                )
                source_paths[key] = path
        manifest = build_assembly_manifest(
            tenant_id=tenant_id,
            envelope_value=inputs["envelope"],
            runtime_job_id=inputs["runtime_job_id"],
            runtime_progress_value=inputs["runtime_progress"],
            provider_rows=inputs["provider_rows"],
            scene_rows=inputs["scene_rows"],
            asset_rows=inputs["asset_rows"],
            provenance_rows=inputs["provenance_rows"],
            section_supplements=inputs["section_supplements"],
            width=inputs["output_width"],
            height=inputs["output_height"],
            render_engine=selected_render_engine,
            assembly_version=selected_assembly_version,
        )
        manifest_hash = manifest["manifest_hash"]
        runtime_hash = manifest["runtime_hash"]
        storage_path = assembly_storage_path(video_id, runtime_hash, manifest_hash)
        journal_ready = False
        last_completed_sections = 0
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """INSERT INTO custom_film_assemblies
                         (tenant_id, video_id, runtime_job_id, runtime_hash, manifest_version,
                          manifest_hash, manifest, progress, storage_path)
                       VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7::jsonb,
                               $8::jsonb, $9)
                       ON CONFLICT (tenant_id, video_id, runtime_hash)
                       DO NOTHING""",
                    tenant_id,
                    video_id,
                    runtime_job_id,
                    runtime_hash,
                    manifest["assembly_version"],
                    manifest_hash,
                    json.dumps(manifest, sort_keys=True, separators=(",", ":")),
                    json.dumps(
                        {
                            "phase": "prepared",
                            "completed_sections": 0,
                            "total_sections": len(manifest["sections"]),
                        },
                        sort_keys=True,
                    ),
                    storage_path,
                )
                journal = await conn.fetchrow(
                    """SELECT state, manifest_hash, artifact_sha256,
                              artifact_probe, storage_path, final_video_url,
                              runtime_job_id, progress
                       FROM custom_film_assemblies
                       WHERE tenant_id = $1::uuid AND video_id = $2::uuid
                         AND runtime_hash = $3
                       FOR UPDATE""",
                    tenant_id,
                    video_id,
                    runtime_hash,
                )
                if not journal or str(journal["manifest_hash"]) != manifest_hash:
                    raise CustomFilmContractError(
                        "Custom Film durable assembly manifest changed"
                    )
                if str(journal["runtime_job_id"]) != runtime_job_id:
                    raise CustomFilmContractError(
                        "Custom Film durable runtime job identity changed"
                    )
                journal_ready = True
                persisted_progress = _mapping(journal["progress"], "assembly progress")
                last_completed_sections = _exact_int(
                    persisted_progress.get("completed_sections"),
                    "completed assembly sections",
                )
                storage_path = str(journal.get("storage_path") or "")
                if not storage_path:
                    raise CustomFilmContractError(
                        "Custom Film durable storage path is missing"
                    )
                state = str(journal["state"])
                resume_action = assembly_resume_action(state)
                if resume_action == "terminal_failure":
                    raise CustomFilmContractError(
                        "Custom Film assembly is terminally failed; a new approved "
                        "runtime is required"
                    )
                if resume_action == "return_finalized":
                    return {
                        "status": "rendered",
                        "video_id": video_id,
                        "final_video_url": str(journal["final_video_url"]),
                        "render_engine": selected_render_engine,
                        **_mapping(journal["artifact_probe"], "artifact probe"),
                        "manifest_hash": manifest_hash,
                        "reused": True,
                    }
                if resume_action == "finalize_uploaded":
                    await conn.execute(
                        """UPDATE videos
                           SET final_video_url = $3, status = 'rendered',
                               updated_at = now()
                           WHERE tenant_id = $1::uuid AND id = $2::uuid""",
                        tenant_id, video_id, journal["final_video_url"],
                    )
                    await conn.execute(
                        """UPDATE custom_film_assemblies
                           SET state = 'finalized', finalized_at = now(),
                               progress = $4::jsonb,
                               updated_at = now()
                           WHERE tenant_id = $1::uuid AND video_id = $2::uuid
                             AND runtime_hash = $3 AND state = 'uploaded'""",
                        tenant_id, video_id, runtime_hash,
                        json.dumps(
                            {
                                "phase": "finalized",
                                "completed_sections": len(manifest["sections"]),
                                "total_sections": len(manifest["sections"]),
                            },
                            sort_keys=True,
                        ),
                    )
                    return {
                        "status": "rendered",
                        "video_id": video_id,
                        "final_video_url": str(journal["final_video_url"]),
                        "render_engine": selected_render_engine,
                        **_mapping(journal["artifact_probe"], "artifact probe"),
                        "manifest_hash": manifest_hash,
                        "reused": True,
                    }
                if state in {"prepared", "rendering", "retryable_failed"}:
                    await conn.execute(
                        """UPDATE custom_film_assemblies
                           SET state = 'rendering',
                               progress = $4::jsonb,
                               failure_detail = NULL, failure_kind = NULL,
                               retry_count = retry_count
                                 + CASE WHEN state = 'retryable_failed' THEN 1 ELSE 0 END,
                               render_started_at = COALESCE(render_started_at, now()),
                               updated_at = now()
                           WHERE tenant_id = $1::uuid AND video_id = $2::uuid
                             AND runtime_hash = $3""",
                        tenant_id, video_id, runtime_hash,
                        json.dumps(
                            {
                                "phase": "normalizing",
                                "completed_sections": last_completed_sections,
                                "total_sections": len(manifest["sections"]),
                            },
                            sort_keys=True,
                        ),
                    )
        if on_progress:
            await on_progress(
                f"Assembling 0/{len(manifest['sections'])} approved sections"
            )
        output = staging / "custom-film.mp4"
        async def _durable_progress(message: str) -> None:
            nonlocal last_completed_sections
            completed_sections = last_completed_sections
            phase = "normalizing"
            if message.startswith("Rendering "):
                phase = "rendering"
                completed_sections = len(manifest["sections"])
            elif message.startswith("Assembling section "):
                phase = "assembling"
                try:
                    completed_sections = int(message.split()[2].split("/")[0])
                except (ValueError, IndexError):
                    completed_sections = last_completed_sections
            elif message.startswith("Assembling sections "):
                phase = "assembling"
            elif message.startswith("Normalizing section "):
                try:
                    completed_sections = max(
                        0, int(message.split()[2].split("/")[0]) - 1
                    )
                except (ValueError, IndexError):
                    completed_sections = last_completed_sections
            completed_sections = max(last_completed_sections, completed_sections)
            last_completed_sections = completed_sections
            async with pool.acquire() as progress_conn:
                await progress_conn.execute(
                    """UPDATE custom_film_assemblies
                       SET progress = $4::jsonb, updated_at = now()
                       WHERE tenant_id = $1::uuid AND video_id = $2::uuid
                         AND runtime_hash = $3 AND state = 'rendering'""",
                    tenant_id, video_id, runtime_hash,
                    json.dumps(
                        {
                            "phase": phase,
                            "completed_sections": completed_sections,
                            "total_sections": len(manifest["sections"]),
                        },
                        sort_keys=True,
                    ),
                )
            if on_progress:
                await on_progress(message)

        rendered = await render_manifest_with_engine(
            manifest,
            source_paths=source_paths,
            output_path=output,
            on_progress=_durable_progress,
            remotion_renderer=remotion_renderer,
        )
        probe = {
            key: rendered[key]
            for key in (
                "duration_seconds", "total_frames", "fps", "resolution",
                "section_count", "asset_count", "captions",
                "section_provenance",
            )
        }
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """SELECT state, artifact_sha256, final_video_url
                       FROM custom_film_assemblies
                       WHERE tenant_id = $1::uuid AND video_id = $2::uuid
                         AND runtime_hash = $3
                       FOR UPDATE""",
                    tenant_id, video_id, runtime_hash,
                )
                if row["state"] in {"rendering", "prepared"}:
                    await conn.execute(
                        """UPDATE custom_film_assemblies
                           SET state = 'rendered', artifact_sha256 = $4,
                               artifact_probe = $5::jsonb, rendered_at = now(),
                               progress = $6::jsonb,
                               updated_at = now()
                           WHERE tenant_id = $1::uuid AND video_id = $2::uuid
                             AND runtime_hash = $3""",
                        tenant_id, video_id, runtime_hash,
                        rendered["artifact_sha256"],
                        json.dumps(probe, sort_keys=True),
                        json.dumps(
                            {
                                "phase": "rendering",
                                "completed_sections": len(manifest["sections"]),
                                "total_sections": len(manifest["sections"]),
                            },
                            sort_keys=True,
                        ),
                    )
                elif str(row.get("artifact_sha256") or "") != rendered["artifact_sha256"]:
                    raise CustomFilmContractError(
                        "Custom Film deterministic rerender changed artifact bytes"
                    )
                await conn.execute(
                    """UPDATE custom_film_assemblies
                       SET state = 'uploading',
                           progress = $4::jsonb,
                           upload_started_at = COALESCE(upload_started_at, now()),
                           updated_at = now()
                       WHERE tenant_id = $1::uuid AND video_id = $2::uuid
                         AND runtime_hash = $3 AND state = 'rendered'""",
                    tenant_id, video_id, runtime_hash,
                    json.dumps(
                        {
                            "phase": "uploading",
                            "completed_sections": len(manifest["sections"]),
                            "total_sections": len(manifest["sections"]),
                        },
                        sort_keys=True,
                    ),
                )
        final_url = await upload(output.read_bytes(), storage_path, tenant_id)
        if not str(final_url or "").strip():
            raise CustomFilmContractError(
                "Custom Film storage seam returned no durable URL"
            )
        stored_bytes = await readback(str(final_url))
        await verify_stored_artifact(
            stored_bytes,
            expected_sha256=rendered["artifact_sha256"],
            manifest=manifest,
            staging=staging,
        )
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """SELECT state, final_video_url
                       FROM custom_film_assemblies
                       WHERE tenant_id = $1::uuid AND video_id = $2::uuid
                         AND runtime_hash = $3
                       FOR UPDATE""",
                    tenant_id, video_id, runtime_hash,
                )
                if row["state"] == "uploading":
                    await conn.execute(
                        """UPDATE custom_film_assemblies
                           SET state = 'uploaded', final_video_url = $4,
                               uploaded_at = now(), updated_at = now()
                           WHERE tenant_id = $1::uuid AND video_id = $2::uuid
                             AND runtime_hash = $3""",
                        tenant_id, video_id, runtime_hash, final_url,
                    )
                elif str(row.get("final_video_url") or "") != str(final_url):
                    raise CustomFilmContractError(
                        "Custom Film storage result changed on retry"
                    )
                await conn.execute(
                    """UPDATE videos
                       SET final_video_url = $3, status = 'rendered',
                           updated_at = now()
                       WHERE tenant_id = $1::uuid AND id = $2::uuid""",
                    tenant_id, video_id, final_url,
                )
                await conn.execute(
                    """UPDATE custom_film_assemblies
                       SET state = 'finalized', finalized_at = now(),
                           progress = $4::jsonb,
                           updated_at = now()
                       WHERE tenant_id = $1::uuid AND video_id = $2::uuid
                         AND runtime_hash = $3 AND state = 'uploaded'""",
                    tenant_id, video_id, runtime_hash,
                    json.dumps(
                        {
                            "phase": "finalized",
                            "completed_sections": len(manifest["sections"]),
                            "total_sections": len(manifest["sections"]),
                        },
                        sort_keys=True,
                    ),
                )
        return {
            "status": "rendered",
            "video_id": video_id,
            "final_video_url": str(final_url),
            "render_engine": selected_render_engine,
            "manifest_hash": manifest_hash,
            "artifact_sha256": rendered["artifact_sha256"],
            "method": f"custom_film_{selected_render_engine}_assembly",
            **probe,
        }
    except Exception as exc:
        if "journal_ready" in locals() and journal_ready:
            retryable = isinstance(
                exc, (CustomFilmRetryableError, OSError, asyncio.SubprocessError)
            ) or not isinstance(exc, CustomFilmContractError)
            failure_state = "retryable_failed" if retryable else "terminal_failed"
            failure_kind = "retryable" if retryable else "terminal"
            safe_detail = humanize_error(
                exc, context="Custom Film assembly could not be completed"
            )
            try:
                async with pool.acquire() as failure_conn:
                    await failure_conn.execute(
                        """UPDATE custom_film_assemblies
                           SET state = $4, failure_kind = $5,
                               failure_detail = $6,
                               progress = $7::jsonb, updated_at = now()
                           WHERE tenant_id = $1::uuid AND video_id = $2::uuid
                             AND runtime_hash = $3
                             AND state NOT IN ('finalized', 'terminal_failed')""",
                        tenant_id,
                        video_id,
                        runtime_hash,
                        failure_state,
                        failure_kind,
                        safe_detail,
                        json.dumps(
                            {
                                "phase": failure_state,
                                "completed_sections": last_completed_sections,
                                "total_sections": len(inputs["envelope"]["sections"]),
                            },
                            sort_keys=True,
                        ),
                    )
            except Exception:
                # Preserve the original failure; the worker-level retry/reaper
                # still observes it if the database itself is unavailable.
                pass
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
