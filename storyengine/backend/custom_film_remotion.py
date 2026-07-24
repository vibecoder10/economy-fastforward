"""Strict, provider-opaque Remotion props for approved Custom Film assemblies.

The assembly manifest remains the authority.  This module validates that
already-hashed object, removes transport URLs and provider implementation
details, and derives the only props shape accepted by the Remotion finishing
layer.  The derivative has its own canonical hash so Python and TypeScript can
independently reject drift before a render starts.
"""

from __future__ import annotations

import copy
import hashlib
import math
from typing import Any, Mapping, Sequence

from custom_film_contract import (
    CustomFilmContractError,
    canonical_hash,
    canonical_json,
)


REMOTION_PROPS_VERSION = "custom-film-remotion-props-v1"
EXPECTED_ASSEMBLY_VERSION = "custom-film-assembly-v2"
SUPPORTED_RENDER_ENGINES = frozenset({"ffmpeg", "remotion"})
PRE_JOURNAL_FALLBACK_POLICIES = frozenset({"forbid", "ffmpeg"})
RESUMABLE_JOURNAL_STATES = frozenset(
    {
        "prepared",
        "rendering",
        "rendered",
        "uploading",
        "uploaded",
        "retryable_failed",
        "finalized",
    }
)

_ASSEMBLY_KEYS = frozenset(
    {
        "assembly_version",
        "tenant_id",
        "video_id",
        "plan_id",
        "plan_hash",
        "quote_inputs_hash",
        "approval_hash",
        "max_spend",
        "runtime_hash",
        "runtime_job_id",
        "render_engine",
        "fps",
        "width",
        "height",
        "total_duration_seconds",
        "total_frames",
        "transition_accounting",
        "sections",
        "manifest_hash",
    }
)
_SECTION_KEYS = frozenset(
    {
        "section_id",
        "order_index",
        "role",
        "render_mode",
        "visual_profile",
        "dialogue_audio",
        "start_frame",
        "duration_frames",
        "transition_in",
        "transition_out",
        "scene_ids",
        "assets",
        "audio",
        "captions",
    }
)
_TRANSITION_KEYS = frozenset(
    {
        "type",
        "duration_frames",
        "overlap_frames",
        "accounting",
        "audio",
    }
)
_ASSET_KEYS = frozenset(
    {
        "asset_id",
        "source_url",
        "source_sha256",
        "actual_duration_ms",
        "assigned_duration_ms",
        "timing_transform",
        "camera",
        "provenance_hash",
        "caption_card",
        "caption_hash",
        "start_frame",
        "duration_frames",
    }
)
_AUDIO_KEYS = frozenset(
    {
        "mode",
        "source_urls",
        "source_sha256",
        "source_duration_ms",
        "timing_transform",
        "gain_db",
    }
)
_CAPTION_KEYS = frozenset(
    {
        "scene_id",
        "text",
        "language",
        "section_start_ms",
        "section_end_ms",
        "start_frame",
        "end_frame",
    }
)
_TIMING_TRANSFORM_KEYS = frozenset(
    {
        "mode",
        "source_duration_ms",
        "output_duration_ms",
        "trim_start_ms",
        "trim_end_ms",
        "repeat_count",
        "final_repeat_duration_ms",
        "atempo_chain",
        "caption_scale",
    }
)


def _strict_mapping(
    value: Any,
    label: str,
    *,
    keys: frozenset[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CustomFilmContractError(f"Custom Film {label} must be an object")
    result = copy.deepcopy(dict(value))
    if keys is not None:
        unknown = set(result) - keys
        if unknown:
            raise CustomFilmContractError(
                f"Custom Film {label} has unknown fields: {sorted(unknown)}"
            )
    return result


def _strict_sequence(value: Any, label: str) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise CustomFilmContractError(f"Custom Film {label} must be an array")
    return copy.deepcopy(list(value))


def _exact_int(value: Any, label: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise CustomFilmContractError(
            f"Custom Film {label} must be an exact integer of at least {minimum}"
        )
    return value


def _finite_number(value: Any, label: str, minimum: float = 0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CustomFilmContractError(f"Custom Film {label} must be a number")
    number = float(value)
    if not math.isfinite(number) or number < minimum:
        raise CustomFilmContractError(
            f"Custom Film {label} must be finite and at least {minimum}"
        )
    return number


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CustomFilmContractError(f"Custom Film {label} must be non-empty text")
    return value


def _hash(value: Any, label: str) -> str:
    digest = _text(value, label)
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise CustomFilmContractError(
            f"Custom Film {label} must be a lowercase SHA-256 digest"
        )
    return digest


def _normalize_remotion_json(value: Any) -> Any:
    """Normalize JSON numbers to the cross-language JS representation."""
    if isinstance(value, Mapping):
        return {
            str(key): _normalize_remotion_json(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_normalize_remotion_json(item) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CustomFilmContractError(
                "Custom Film Remotion props contain a non-finite number"
            )
        return int(value) if value.is_integer() else value
    return value


def canonical_remotion_json(value: Any) -> str:
    return canonical_json(_normalize_remotion_json(value))


def remotion_props_hash(value: Any) -> str:
    return hashlib.sha256(
        canonical_remotion_json(value).encode("utf-8")
    ).hexdigest()


def _validate_timing_transform(value: Any, label: str) -> dict[str, Any]:
    transform = _strict_mapping(value, label, keys=_TIMING_TRANSFORM_KEYS)
    mode = _text(transform.get("mode"), f"{label} mode")
    allowed_by_mode = {
        "none": (
            {"mode", "source_duration_ms", "output_duration_ms"},
            {
                "mode",
                "source_duration_ms",
                "output_duration_ms",
                "atempo_chain",
                "caption_scale",
            },
        ),
        "trim": ({
            "mode",
            "source_duration_ms",
            "output_duration_ms",
            "trim_start_ms",
            "trim_end_ms",
        },),
        "repeat_then_trim": ({
            "mode",
            "source_duration_ms",
            "output_duration_ms",
            "repeat_count",
            "final_repeat_duration_ms",
        },),
        "static_hold": ({"mode", "source_duration_ms", "output_duration_ms"},),
        "source_clip": ({
            "mode",
            "source_duration_ms",
            "output_duration_ms",
            "atempo_chain",
            "caption_scale",
        },),
        "atempo": ({
            "mode",
            "source_duration_ms",
            "output_duration_ms",
            "atempo_chain",
            "caption_scale",
        },),
        "pending_source_probe": ({
            "mode",
            "source_duration_ms",
            "output_duration_ms",
            "atempo_chain",
            "caption_scale",
        },),
    }
    allowed_shapes = allowed_by_mode.get(mode)
    if allowed_shapes is None or set(transform) not in allowed_shapes:
        raise CustomFilmContractError(
            f"Custom Film {label} shape does not match mode {mode}"
        )
    return transform


def resolve_render_engine(
    requested_engine: str | None,
    *,
    remotion_available: bool,
    pre_journal_fallback: str = "forbid",
) -> str:
    """Resolve the engine exactly once, before manifest hashing and journaling."""
    policy = str(pre_journal_fallback or "")
    if policy not in PRE_JOURNAL_FALLBACK_POLICIES:
        raise CustomFilmContractError(
            "Custom Film pre-journal render fallback policy is unsupported"
        )
    engine = "ffmpeg" if requested_engine is None else str(requested_engine)
    if engine not in SUPPORTED_RENDER_ENGINES:
        raise CustomFilmContractError("Custom Film render engine is unsupported")
    if engine == "remotion" and not remotion_available:
        if policy == "ffmpeg":
            return "ffmpeg"
        raise CustomFilmContractError(
            "Custom Film Remotion was selected but no renderer is available"
        )
    return engine


def resolve_durable_render_engine(
    *,
    manifest_version: str,
    manifest: Mapping[str, Any],
    journal_state: str,
    requested_engine: str | None,
    remotion_available: bool,
) -> str:
    """Let an immutable durable journal, never a retry default, select engine."""
    if journal_state not in RESUMABLE_JOURNAL_STATES:
        raise CustomFilmContractError(
            "Custom Film durable render state is unsupported for selection"
        )
    if manifest_version == "custom-film-assembly-v1":
        durable_engine = "ffmpeg"
        if "render_engine" in manifest:
            raise CustomFilmContractError(
                "Custom Film assembly v1 renderer identity changed"
            )
    elif manifest_version == EXPECTED_ASSEMBLY_VERSION:
        durable_engine = str(manifest.get("render_engine") or "")
        if durable_engine not in SUPPORTED_RENDER_ENGINES:
            raise CustomFilmContractError(
                "Custom Film assembly v2 renderer identity is missing"
            )
    else:
        raise CustomFilmContractError(
            "Custom Film durable assembly version is unsupported"
        )
    if requested_engine is not None and str(requested_engine) != durable_engine:
        raise CustomFilmContractError(
            "Custom Film retry render engine does not match its durable journal"
        )
    if durable_engine == "remotion" and not remotion_available:
        raise CustomFilmContractError(
            "Custom Film durable Remotion retry requires the Remotion renderer"
        )
    return durable_engine


def build_remotion_props(manifest_value: Any) -> dict[str, Any]:
    """Validate and derive provider-opaque props from one assembly manifest."""
    manifest = _strict_mapping(
        manifest_value, "assembly manifest", keys=_ASSEMBLY_KEYS
    )
    if set(manifest) != _ASSEMBLY_KEYS:
        missing = sorted(_ASSEMBLY_KEYS - set(manifest))
        raise CustomFilmContractError(
            f"Custom Film assembly manifest is missing fields: {missing}"
        )
    manifest_hash = _hash(manifest.pop("manifest_hash"), "assembly manifest hash")
    if canonical_hash(manifest) != manifest_hash:
        raise CustomFilmContractError("Custom Film assembly manifest hash changed")

    engine = _text(manifest["render_engine"], "render engine")
    if engine not in SUPPORTED_RENDER_ENGINES:
        raise CustomFilmContractError("Custom Film render engine is unsupported")
    fps = _exact_int(manifest["fps"], "assembly fps", 1)
    width = _exact_int(manifest["width"], "assembly width", 2)
    height = _exact_int(manifest["height"], "assembly height", 2)
    duration_seconds = _exact_int(
        manifest["total_duration_seconds"], "film seconds", 1
    )
    total_frames = _exact_int(manifest["total_frames"], "film frames", 1)
    if total_frames != duration_seconds * fps:
        raise CustomFilmContractError(
            "Custom Film duration and total frame identity changed"
        )
    if manifest["assembly_version"] != EXPECTED_ASSEMBLY_VERSION:
        raise CustomFilmContractError(
            "Custom Film assembly version is unsupported by Remotion"
        )
    runtime_hash = _hash(manifest["runtime_hash"], "runtime hash")
    if manifest["runtime_job_id"] != f"custom-film-runtime:{runtime_hash}":
        raise CustomFilmContractError(
            "Custom Film runtime job identity changed"
        )

    transition_accounting = _strict_mapping(
        manifest["transition_accounting"], "transition accounting"
    )
    if set(transition_accounting) != {
        "type",
        "duration_source",
        "overlap_frames_total",
        "duration_lives_inside_assigned_sections",
    }:
        raise CustomFilmContractError(
            "Custom Film transition accounting shape changed"
        )
    if (
        transition_accounting["overlap_frames_total"] != 0
        or transition_accounting["duration_lives_inside_assigned_sections"] is not True
    ):
        raise CustomFilmContractError(
            "Custom Film Remotion transitions must not change approved frames"
        )

    sections: list[dict[str, Any]] = []
    expected_start = 0
    section_values = _strict_sequence(manifest["sections"], "sections")
    if not section_values:
        raise CustomFilmContractError("Custom Film sections are empty")
    seen_assets: set[str] = set()
    for expected_order, section_value in enumerate(section_values):
        section = _strict_mapping(
            section_value, "section", keys=_SECTION_KEYS
        )
        if set(section) != _SECTION_KEYS:
            raise CustomFilmContractError("Custom Film section shape changed")
        order_index = _exact_int(section["order_index"], "section order")
        start_frame = _exact_int(section["start_frame"], "section start frame")
        section_frames = _exact_int(
            section["duration_frames"], "section frames", 1
        )
        if order_index != expected_order or start_frame != expected_start:
            raise CustomFilmContractError(
                "Custom Film Remotion section order or boundary changed"
            )
        section_id = _text(section["section_id"], "section identity")
        transitions: dict[str, dict[str, Any]] = {}
        for direction in ("transition_in", "transition_out"):
            transition = _strict_mapping(
                section[direction],
                f"section {direction}",
                keys=_TRANSITION_KEYS,
            )
            if set(transition) != _TRANSITION_KEYS:
                raise CustomFilmContractError(
                    f"Custom Film section {direction} shape changed"
                )
            duration_frames = _exact_int(
                transition["duration_frames"], f"section {direction} frames"
            )
            if (
                transition["overlap_frames"] != 0
                or transition["accounting"] != "inside_section"
                or duration_frames > section_frames
            ):
                raise CustomFilmContractError(
                    "Custom Film Remotion transition accounting changed"
                )
            transitions[direction] = transition

        assets: list[dict[str, Any]] = []
        expected_asset_start = 0
        asset_values = _strict_sequence(section["assets"], "section assets")
        if not asset_values:
            raise CustomFilmContractError("Custom Film section assets are empty")
        for asset_value in asset_values:
            asset = _strict_mapping(
                asset_value, "section asset", keys=_ASSET_KEYS
            )
            if set(asset) != _ASSET_KEYS:
                raise CustomFilmContractError("Custom Film asset shape changed")
            asset_start = _exact_int(asset["start_frame"], "asset start frame")
            asset_frames = _exact_int(asset["duration_frames"], "asset frames", 1)
            if asset_start != expected_asset_start:
                raise CustomFilmContractError(
                    "Custom Film Remotion asset order or boundary changed"
                )
            asset_id = _text(asset["asset_id"], "asset identity")
            if asset_id in seen_assets:
                raise CustomFilmContractError(
                    "Custom Film asset identity is duplicated"
                )
            seen_assets.add(asset_id)
            _text(asset["source_url"], "asset source URL")
            source_hash = _hash(asset["source_sha256"], "asset source hash")
            provenance_hash = _hash(
                asset["provenance_hash"], "asset provenance hash"
            )
            caption_hash = _hash(asset["caption_hash"], "asset caption hash")
            timing_transform = _validate_timing_transform(
                asset["timing_transform"], "asset timing transform"
            )
            camera = _strict_mapping(asset["camera"], "asset camera")
            caption_card = asset["caption_card"]
            if caption_card is not None:
                caption_card = _strict_mapping(caption_card, "asset caption card")
            if canonical_hash({"caption_card": caption_card}) != caption_hash:
                raise CustomFilmContractError(
                    "Custom Film asset caption hash changed"
                )
            assets.append(
                {
                    "asset_id": asset_id,
                    "source_key": asset_id,
                    "source_sha256": source_hash,
                    "provenance_hash": provenance_hash,
                    "caption_hash": caption_hash,
                    "caption_card": caption_card,
                    "actual_duration_ms": asset["actual_duration_ms"],
                    "assigned_duration_ms": asset["assigned_duration_ms"],
                    "start_frame": asset_start,
                    "duration_frames": asset_frames,
                    "timing_transform": timing_transform,
                    "camera": camera,
                }
            )
            expected_asset_start += asset_frames
        if expected_asset_start != section_frames:
            raise CustomFilmContractError(
                "Custom Film Remotion assets do not exactly fill their section"
            )

        audio = _strict_mapping(
            section["audio"], "section audio", keys=_AUDIO_KEYS
        )
        if set(audio) != _AUDIO_KEYS:
            raise CustomFilmContractError("Custom Film section audio shape changed")
        audio_hashes = [
            _hash(value, "audio source hash")
            for value in _strict_sequence(
                audio["source_sha256"], "audio source hashes"
            )
        ]
        audio_durations = [
            _exact_int(value, "audio source duration", 1)
            for value in _strict_sequence(
                audio["source_duration_ms"], "audio source durations"
            )
        ]
        source_urls = _strict_sequence(audio["source_urls"], "audio source URLs")
        for source_url in source_urls:
            _text(source_url, "audio source URL")
        if len(source_urls) != len(audio_hashes) or len(source_urls) != len(
            audio_durations
        ):
            raise CustomFilmContractError(
                "Custom Film section audio source identity is incomplete"
            )
        audio_sources = [
            {
                "source_key": f"audio:{section_id}:{index}",
                "source_sha256": digest,
                "source_duration_ms": audio_durations[index],
            }
            for index, digest in enumerate(audio_hashes)
        ]
        audio_transform = _validate_timing_transform(
            audio["timing_transform"], "audio timing transform"
        )

        captions: list[dict[str, Any]] = []
        last_caption_end = start_frame
        caption_values = _strict_sequence(
            section["captions"], "section captions"
        )
        if not caption_values:
            raise CustomFilmContractError("Custom Film section captions are empty")
        for caption_value in caption_values:
            caption = _strict_mapping(
                caption_value, "section caption", keys=_CAPTION_KEYS
            )
            if set(caption) != _CAPTION_KEYS:
                raise CustomFilmContractError("Custom Film caption shape changed")
            caption_start = _exact_int(
                caption["start_frame"], "caption start frame"
            )
            caption_end = _exact_int(caption["end_frame"], "caption end frame", 1)
            section_start_ms = _exact_int(
                caption["section_start_ms"], "caption section start milliseconds"
            )
            section_end_ms = _exact_int(
                caption["section_end_ms"], "caption section end milliseconds", 1
            )
            if (
                caption_start < start_frame
                or caption_start != last_caption_end
                or caption_end <= caption_start
                or caption_end > start_frame + section_frames
                or section_end_ms <= section_start_ms
                or caption_start
                != start_frame + (section_start_ms * fps // 1000)
                or caption_end != start_frame + (section_end_ms * fps // 1000)
            ):
                raise CustomFilmContractError(
                    "Custom Film caption timing or order changed"
                )
            language = _strict_mapping(caption["language"], "caption language")
            captions.append(
                {
                    **caption,
                    "language": language,
                }
            )
            last_caption_end = caption_end

        scene_ids = [
            _text(value, "scene identity")
            for value in _strict_sequence(section["scene_ids"], "scene identities")
        ]
        if not scene_ids or any(
            caption["scene_id"] not in scene_ids for caption in captions
        ):
            raise CustomFilmContractError(
                "Custom Film captions do not match assigned section scenes"
            )
        if last_caption_end != start_frame + section_frames:
            raise CustomFilmContractError(
                "Custom Film captions do not exactly fill their section"
            )
        sections.append(
            {
                "section_id": section_id,
                "order_index": order_index,
                "role": _text(section["role"], "section role"),
                "render_mode": _text(
                    section["render_mode"], "section render mode"
                ),
                "visual_profile": _text(
                    section["visual_profile"], "section visual profile"
                ),
                "dialogue_audio": _text(
                    section["dialogue_audio"], "section dialogue audio"
                ),
                "scene_ids": scene_ids,
                "start_frame": start_frame,
                "duration_frames": section_frames,
                **transitions,
                "assets": assets,
                "audio": {
                    "mode": _text(audio["mode"], "section audio mode"),
                    "sources": audio_sources,
                    "timing_transform": audio_transform,
                    "gain_db": _finite_number(
                        audio["gain_db"], "section audio gain", -120
                    ),
                },
                "captions": captions,
            }
        )
        expected_start += section_frames
    if expected_start != total_frames:
        raise CustomFilmContractError(
            "Custom Film Remotion sections do not exactly fill the film"
        )

    body = {
        "schema_version": REMOTION_PROPS_VERSION,
        "identity": {
            "assembly_version": _text(
                manifest["assembly_version"], "assembly version"
            ),
            "assembly_manifest_hash": manifest_hash,
            "tenant_id": _text(manifest["tenant_id"], "tenant identity"),
            "video_id": _text(manifest["video_id"], "video identity"),
            "plan_id": _text(manifest["plan_id"], "plan identity"),
            "plan_hash": _hash(manifest["plan_hash"], "plan hash"),
            "quote_inputs_hash": _hash(
                manifest["quote_inputs_hash"], "quote inputs hash"
            ),
            "approval_hash": _hash(
                manifest["approval_hash"], "approval hash"
            ),
            "runtime_hash": runtime_hash,
            "runtime_job_id": _text(
                manifest["runtime_job_id"], "runtime job identity"
            ),
            "max_spend": _finite_number(
                manifest["max_spend"], "approved spending cap"
            ),
            "render_engine": engine,
        },
        "video": {
            "fps": fps,
            "width": width,
            "height": height,
            "total_duration_seconds": duration_seconds,
            "total_frames": total_frames,
        },
        "transition_accounting": transition_accounting,
        "sections": sections,
    }
    return {**body, "props_hash": remotion_props_hash(body)}
