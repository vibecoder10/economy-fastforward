"""Strict, provider-opaque Remotion props for approved Custom Film assemblies.

The assembly manifest remains the authority.  This module validates that
already-hashed object, removes transport URLs and provider implementation
details, and derives the only props shape accepted by the Remotion finishing
layer.  The derivative has its own canonical hash so Python and TypeScript can
independently reject drift before a render starts.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import math
import os
import shutil
import signal
import tempfile
import wave
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Sequence

from custom_film_contract import (
    CustomFilmContractError,
    canonical_hash,
    canonical_json,
)


REMOTION_PROPS_VERSION = "custom-film-remotion-props-v1"
LEGACY_ASSEMBLY_VERSION = "custom-film-assembly-v2"
EXPECTED_ASSEMBLY_VERSION = "custom-film-assembly-v3"
REMOTION_RENDERER_CONTRACT_VERSION = "custom-film-remotion-renderer-v1"
REMOTION_COMPOSITION_ID = "StoryEngineCustomFilmShowcase"
SHOWCASE_MOTION_PLAN_VERSION = "storyengine-layered-orchestration-v1"
AUTOMATIC_RENDER_POLICY = "showcase_auto"
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
_ASSEMBLY_V3_KEYS = _ASSEMBLY_KEYS | frozenset(
    {
        "renderer_contract_version",
        "renderer_bundle_hash",
        "orchestration_contract",
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
        "cues",
    }
)
_PROPS_IDENTITY_V3_KEYS = frozenset(
    {
        "assembly_version",
        "assembly_manifest_hash",
        "tenant_id",
        "video_id",
        "plan_id",
        "plan_hash",
        "quote_inputs_hash",
        "approval_hash",
        "runtime_hash",
        "runtime_job_id",
        "max_spend",
        "render_engine",
        "renderer_contract_version",
        "renderer_bundle_hash",
    }
)
_PROPS_VIDEO_KEYS = frozenset(
    {"fps", "width", "height", "total_duration_seconds", "total_frames"}
)
_PROPS_TRANSITION_ACCOUNTING_KEYS = frozenset(
    {
        "type",
        "duration_source",
        "overlap_frames_total",
        "duration_lives_inside_assigned_sections",
    }
)
_PROPS_ASSET_KEYS = frozenset(
    {
        "asset_id",
        "source_key",
        "source_sha256",
        "provenance_hash",
        "caption_hash",
        "caption_card",
        "actual_duration_ms",
        "assigned_duration_ms",
        "start_frame",
        "duration_frames",
        "timing_transform",
        "camera",
    }
)
_PROPS_AUDIO_KEYS = frozenset(
    {"mode", "sources", "timing_transform", "gain_db"}
)
_PROPS_AUDIO_SOURCE_KEYS = frozenset(
    {"source_key", "source_sha256", "source_duration_ms"}
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


def _assert_provider_opaque(value: Any) -> None:
    forbidden = {
        "api_key",
        "endpoint",
        "model",
        "model_id",
        "provider",
        "provider_id",
        "provider_model",
        "source_url",
        "source_urls",
        "token",
    }
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in forbidden:
                raise CustomFilmContractError(
                    "Custom Film Remotion props expose provider internals"
                )
            _assert_provider_opaque(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            _assert_provider_opaque(item)


def canonical_remotion_json(value: Any) -> str:
    return canonical_json(_normalize_remotion_json(value))


def remotion_props_hash(value: Any) -> str:
    return hashlib.sha256(
        canonical_remotion_json(value).encode("utf-8")
    ).hexdigest()


def _remotion_project_root() -> Path:
    return Path(__file__).resolve().parents[2] / "remotion-video"


def load_showcase_motion_plan(
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Load the semantic reference and independently resolve every recipe."""
    if project_root is not None:
        root = project_root.resolve()
        expected = (
            root / "src/showcase/orchestration-plan-v1.json"
        ).resolve()
        if expected != (
            _remotion_project_root()
            / "src/showcase/orchestration-plan-v1.json"
        ).resolve():
            try:
                value = json.loads(expected.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise CustomFilmContractError(
                    "StoryEngine orchestration reference is unavailable"
                ) from exc
            from custom_film_orchestration import (
                load_reference_semantic_plan,
            )
            canonical = load_reference_semantic_plan()
            if value != canonical:
                raise CustomFilmContractError(
                    "StoryEngine orchestration reference changed"
                )
            return value
    from custom_film_orchestration import (
        load_reference_semantic_plan,
        resolve_layered_recipe,
    )
    plan = load_reference_semantic_plan()
    recipes = [resolve_layered_recipe(cue) for cue in plan["cues"]]
    if any(len(recipe["motionLayers"]) < 2 for recipe in recipes):
        raise CustomFilmContractError(
            "StoryEngine orchestration recipe is not layered"
        )
    return plan


def is_storyengine_showcase_runtime(
    envelope_value: Mapping[str, Any],
) -> bool:
    """Match only the exact immutable four-act flagship runtime contract."""
    plan = load_showcase_motion_plan()
    envelope = _strict_mapping(envelope_value, "runtime envelope")
    sections = _strict_sequence(envelope.get("sections"), "runtime sections")
    planned_sections = _strict_sequence(
        plan["sections"], "showcase motion sections"
    )
    if (
        _exact_int(
            envelope.get("total_duration_seconds"),
            "runtime duration",
            1,
        )
        * plan["fps"]
        != plan["total_frames"]
        or len(sections) != len(planned_sections)
    ):
        return False
    for runtime_value, planned_value in zip(sections, planned_sections):
        runtime = _strict_mapping(runtime_value, "runtime section")
        planned = _strict_mapping(planned_value, "showcase motion section")
        if (
            str(runtime.get("role") or "") != str(planned.get("role") or "")
            or _exact_int(
                runtime.get("duration_seconds"),
                "runtime section duration",
                1,
            )
            * plan["fps"]
            != _exact_int(
                planned.get("duration_frames"),
                "showcase section frames",
                1,
            )
        ):
            return False
    return True


def automatic_render_engine_for_runtime(
    envelope_value: Mapping[str, Any],
    *,
    width: int,
    height: int,
    orchestration_contract: Mapping[str, Any] | None = None,
) -> str:
    """Select Remotion for an exact executable approved beat contract.

    The outage showcase remains a stress-test fixture, not product authority.
    Legacy plans without approved beats keep the established FFmpeg fallback.
    """
    envelope = _strict_mapping(envelope_value, "runtime envelope")
    runtime_sections = _strict_sequence(
        envelope.get("sections"), "runtime sections"
    )
    if not isinstance(orchestration_contract, Mapping):
        return "ffmpeg"
    total_seconds = envelope.get("total_duration_seconds")
    resolved = orchestration_contract.get("resolved_plan")
    fps = resolved.get("fps") if isinstance(resolved, Mapping) else None
    if width != 1920 or height != 1080:
        return "ffmpeg"
    try:
        from custom_film_orchestration import (
            validate_executable_orchestration,
        )
        validate_executable_orchestration(
            orchestration_contract,
            total_duration_seconds=int(total_seconds),
            section_duration_seconds=[
                int(
                    _strict_mapping(
                        section, "runtime section"
                    )["duration_seconds"]
                )
                for section in runtime_sections
            ],
            fps=int(fps),
        )
    except (CustomFilmContractError, KeyError, TypeError, ValueError):
        return "ffmpeg"
    return "remotion"


def _renderer_adapter_hash() -> str:
    """Hash the exact Python staging and normalization adapter."""
    return hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest()


def _orchestration_adapter_hash() -> str:
    """Hash the exact approval-time semantic compiler implementation."""
    path = Path(__file__).resolve().with_name("custom_film_orchestration.py")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def renderer_bundle_hash(project_root: Path | None = None) -> str:
    """Hash the deterministic renderer implementation used by assembly v3.

    Generated motion audio and local font bytes are included alongside their
    source/configuration so the journal binds the exact runtime payload.
    Custom Film section assets remain independently bound by approved hashes.
    """
    root = (project_root or _remotion_project_root()).resolve()
    anchors = [
        root / "package.json",
        root / "package-lock.json",
        root / "remotion.config.ts",
        root / "src/index.ts",
        root / "src/Root.tsx",
        root / "scripts/generate-motion-audio.mjs",
        root / "public/motion-audio/signal-pulse.wav",
        root / "public/motion-audio/silence-drop.wav",
        root / "public/motion-audio/data-click.wav",
        root / "public/motion-audio/transition-envelope.wav",
        root / "public/motion-audio/music-bed.wav",
        root / "node_modules/@fontsource/noto-sans/latin-ext-400.css",
        root / "node_modules/@fontsource/noto-sans/latin-ext-600.css",
        root / "node_modules/@fontsource/noto-sans/latin-ext-700.css",
    ]
    sources: list[Path] = []
    for folder in ("src/custom-film", "src/motion-library", "src/showcase"):
        sources.extend(
            path for path in (root / folder).rglob("*") if path.is_file()
        )
    sources.extend(
        path
        for path in (root / "public/motion-audio").glob("*.wav")
        if path.is_file()
    )
    font_files = [
        path
        for path in (
            root / "node_modules/@fontsource/noto-sans/files"
        ).glob("*.woff2")
        if path.is_file()
    ]
    if not font_files:
        raise CustomFilmContractError(
            "Custom Film Remotion local font assets are missing"
        )
    sources.extend(font_files)
    paths = sorted({*anchors, *sources}, key=lambda path: path.as_posix())
    if not paths or any(not path.is_file() for path in paths):
        raise CustomFilmContractError(
            "Custom Film Remotion renderer implementation is incomplete"
        )
    records = [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in paths
    ]
    return canonical_hash(
        {
            "renderer_contract_version": REMOTION_RENDERER_CONTRACT_VERSION,
            "adapter_sha256": _renderer_adapter_hash(),
            "orchestration_adapter_sha256": _orchestration_adapter_hash(),
            "files": records,
        }
    )


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
        "cue_schedule": ({
            "mode",
            "source_duration_ms",
            "output_duration_ms",
            "atempo_chain",
            "caption_scale",
            "cues",
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
    elif manifest_version in {
        LEGACY_ASSEMBLY_VERSION,
        EXPECTED_ASSEMBLY_VERSION,
    }:
        durable_engine = str(manifest.get("render_engine") or "")
        if durable_engine not in SUPPORTED_RENDER_ENGINES:
            raise CustomFilmContractError(
                "Custom Film assembly renderer identity is missing"
            )
        if manifest_version == EXPECTED_ASSEMBLY_VERSION:
            if durable_engine != "remotion":
                raise CustomFilmContractError(
                    "Custom Film assembly v3 is reserved for Remotion"
                )
            if (
                manifest.get("renderer_contract_version")
                != REMOTION_RENDERER_CONTRACT_VERSION
                or _hash(
                    manifest.get("renderer_bundle_hash"),
                    "renderer bundle hash",
                )
                != renderer_bundle_hash()
            ):
                raise CustomFilmContractError(
                    "Custom Film durable Remotion renderer identity changed"
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
    raw_manifest = _strict_mapping(manifest_value, "assembly manifest")
    version = str(raw_manifest.get("assembly_version") or "")
    expected_keys = (
        _ASSEMBLY_V3_KEYS
        if version == EXPECTED_ASSEMBLY_VERSION
        else _ASSEMBLY_KEYS
    )
    manifest = _strict_mapping(
        raw_manifest, "assembly manifest", keys=expected_keys
    )
    if set(manifest) != expected_keys:
        missing = sorted(expected_keys - set(manifest))
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
    if manifest["assembly_version"] not in {
        LEGACY_ASSEMBLY_VERSION,
        EXPECTED_ASSEMBLY_VERSION,
    }:
        raise CustomFilmContractError(
            "Custom Film assembly version is unsupported by Remotion"
        )
    renderer_identity: dict[str, Any] = {}
    orchestration_contract: dict[str, Any] | None = None
    if manifest["assembly_version"] == EXPECTED_ASSEMBLY_VERSION:
        if engine != "remotion":
            raise CustomFilmContractError(
                "Custom Film assembly v3 is reserved for Remotion"
            )
        contract_version = _text(
            manifest["renderer_contract_version"],
            "renderer contract version",
        )
        bundle_hash = _hash(
            manifest["renderer_bundle_hash"], "renderer bundle hash"
        )
        if (
            contract_version != REMOTION_RENDERER_CONTRACT_VERSION
            or bundle_hash != renderer_bundle_hash()
        ):
            raise CustomFilmContractError(
                "Custom Film Remotion renderer identity changed"
            )
        renderer_identity = {
            "renderer_contract_version": contract_version,
            "renderer_bundle_hash": bundle_hash,
        }
        orchestration_contract = copy.deepcopy(
            _strict_mapping(
                manifest["orchestration_contract"],
                "approved orchestration contract",
            )
        )
        contract_body = copy.deepcopy(orchestration_contract)
        contract_hash = _hash(
            contract_body.pop("contract_hash", None),
            "orchestration contract hash",
        )
        resolved_plan = _strict_mapping(
            orchestration_contract.get("resolved_plan"),
            "approved resolved orchestration plan",
        )
        recipes = _strict_sequence(
            resolved_plan.get("recipes"),
            "approved resolved orchestration recipes",
        )
        recipe_hash = canonical_hash(recipes)
        if (
            canonical_hash(contract_body) != contract_hash
            or orchestration_contract.get("contract_version")
            != SHOWCASE_MOTION_PLAN_VERSION
            or orchestration_contract.get("decision_rules_version")
            != "storyengine-layered-recipe-rules-v1"
            or orchestration_contract.get("recipe_hash") != recipe_hash
            or orchestration_contract.get("resolved_plan_hash")
            != canonical_hash(resolved_plan)
        ):
            raise CustomFilmContractError(
                "Custom Film Remotion orchestration identity changed"
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
                or (
                    audio_transform["mode"] != "cue_schedule"
                    and caption_start != last_caption_end
                )
                or (
                    audio_transform["mode"] == "cue_schedule"
                    and caption_start < last_caption_end
                )
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
        expected_caption_end = start_frame + section_frames
        if audio_transform["mode"] == "cue_schedule":
            cues = audio_transform["cues"]
            if len(captions) != len(cues) or any(
                caption["section_start_ms"] != cue["target_start_ms"]
                or caption["section_end_ms"] != cue["target_end_ms"]
                or canonical_hash(
                    {
                        "segment_index": index,
                        "text": caption["text"],
                    }
                )
                != cue["text_hash"]
                for index, (caption, cue) in enumerate(zip(captions, cues))
            ):
                raise CustomFilmContractError(
                    "Custom Film captions changed their cue schedule"
                )
            expected_caption_end = start_frame + (
                cues[-1]["target_end_ms"] * fps // 1000
            )
        if last_caption_end != expected_caption_end:
            raise CustomFilmContractError(
                "Custom Film captions do not match approved audio"
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
            **renderer_identity,
        },
        "video": {
            "fps": fps,
            "width": width,
            "height": height,
            "total_duration_seconds": duration_seconds,
            "total_frames": total_frames,
        },
        "transition_accounting": transition_accounting,
        "orchestration": orchestration_contract,
        "sections": sections,
    }
    return {**body, "props_hash": remotion_props_hash(body)}


ProgressCallback = Callable[[str], Awaitable[None]]
_PROCESS_LOG_LIMIT = 16_384
_DEFAULT_RENDER_TIMEOUT_SECONDS = 7_200
_AAC_PACKET_PADDING_SECONDS = (1024 / 48_000) + 0.002
_STREAM_COVERAGE_TOLERANCE_SECONDS = 0.002
_INTERMEDIATE_CACHE_VERSION = "custom-film-remotion-intermediates-v1"
_INTERMEDIATE_CONTENT_MANIFEST_VERSION = (
    "custom-film-remotion-intermediate-content-v1"
)
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def staged_local_path_for_source_key(source_key: str, kind: str) -> str:
    """Mirror showcase/manifest.ts exactly; never accept a caller path."""
    extensions = {"image": "png", "video": "mp4", "audio": "wav"}
    if kind not in extensions:
        raise CustomFilmContractError(
            "Custom Film Remotion staged source kind is unsupported"
        )
    digest = hashlib.sha256(source_key.encode("utf-8")).hexdigest()
    return f"custom-film-sources/{kind}/{digest}.{extensions[kind]}"


def _renderer_source_specs(
    props: Mapping[str, Any],
) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for section in props["sections"]:
        source_clip = section["audio"]["mode"] == "source_clip"
        for asset in section["assets"]:
            key = _text(asset["source_key"], "Remotion asset source key")
            kind = (
                "image"
                if asset["timing_transform"]["mode"] == "static_hold"
                else "video"
            )
            digest = _hash(
                asset["source_sha256"], "Remotion asset source hash"
            )
            if key in seen:
                raise CustomFilmContractError(
                    "Custom Film Remotion source key is duplicated"
                )
            seen.add(key)
            specs.append(
                {
                    "source_key": key,
                    "kind": kind,
                    "sha256": digest,
                    "source_duration_ms": (
                        None
                        if kind == "image"
                        else _exact_int(
                            asset["timing_transform"]["source_duration_ms"],
                            "Remotion video source duration",
                            1,
                        )
                    ),
                    "requires_native_audio": source_clip,
                }
            )
        for source in section["audio"]["sources"]:
            key = _text(source["source_key"], "Remotion audio source key")
            digest = _hash(
                source["source_sha256"], "Remotion audio source hash"
            )
            if key in seen:
                raise CustomFilmContractError(
                    "Custom Film Remotion source key is duplicated"
                )
            seen.add(key)
            specs.append(
                {
                    "source_key": key,
                    "kind": "audio",
                    "sha256": digest,
                    "source_duration_ms": _exact_int(
                        source["source_duration_ms"],
                        "Remotion audio source duration",
                        1,
                    ),
                    "requires_native_audio": False,
                }
            )
    return specs


def _intermediate_cache_identity(
    props: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind reusable lossless intermediates without persisting source paths."""
    sources = sorted(
        (
            {
                "kind": spec["kind"],
                "sha256": spec["sha256"],
                "source_key": spec["source_key"],
            }
            for spec in _renderer_source_specs(props)
        ),
        key=lambda item: (item["source_key"], item["kind"]),
    )
    body = {
        "cache_version": _INTERMEDIATE_CACHE_VERSION,
        "props_hash": props["props_hash"],
        "renderer_bundle_hash": props["identity"]["renderer_bundle_hash"],
        "sources": sources,
    }
    return {**body, "cache_key": canonical_hash(body)}


def _private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_private_canonical_json(path: Path, value: Any) -> None:
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    temporary.write_text(
        canonical_remotion_json(value),
        encoding="utf-8",
        newline="\n",
    )
    temporary.chmod(0o600)
    os.replace(temporary, path)


def _validate_lossless_intermediates(
    *,
    raw_frames: Path,
    raw_audio: Path,
    total_frames: int,
    fps: int,
    width: int,
    height: int,
) -> dict[str, Any]:
    """Decode every approved frame and the complete PCM delivery waveform."""
    from PIL import Image, UnidentifiedImageError

    expected_names = [
        f"frame-{frame:04d}.png" for frame in range(total_frames)
    ]
    if not raw_frames.is_dir():
        raise CustomFilmContractError(
            "Custom Film Remotion intermediate frame directory is missing"
        )
    actual_names = {
        path.name for path in raw_frames.iterdir() if path.suffix == ".png"
    }
    if actual_names != set(expected_names):
        raise CustomFilmContractError(
            "Custom Film Remotion intermediate frame sequence is incomplete"
        )
    ordered_frame_hashes: list[dict[str, Any]] = []
    for name in expected_names:
        frame_path = raw_frames / name
        try:
            with frame_path.open("rb") as stream:
                if stream.read(len(_PNG_SIGNATURE)) != _PNG_SIGNATURE:
                    raise CustomFilmContractError(
                        f"Custom Film Remotion intermediate PNG signature "
                        f"changed: {name}"
                    )
            with Image.open(frame_path) as image:
                if image.format != "PNG" or image.size != (width, height):
                    raise CustomFilmContractError(
                        f"Custom Film Remotion intermediate PNG dimensions "
                        f"changed: {name}"
                    )
                image.verify()
            ordered_frame_hashes.append(
                {"name": name, "sha256": _sha256_path(frame_path)}
            )
        except (OSError, UnidentifiedImageError) as exc:
            raise CustomFilmContractError(
                f"Custom Film Remotion intermediate PNG is undecodable: {name}"
            ) from exc

    expected_samples = total_frames * 48_000 // fps
    try:
        with wave.open(str(raw_audio), "rb") as waveform:
            audio_identity = (
                waveform.getnchannels(),
                waveform.getsampwidth(),
                waveform.getframerate(),
                waveform.getnframes(),
                waveform.getcomptype(),
            )
            expected_identity = (2, 2, 48_000, expected_samples, "NONE")
            if audio_identity != expected_identity:
                raise CustomFilmContractError(
                    "Custom Film Remotion intermediate WAV identity changed"
                )
            remaining = expected_samples
            while remaining:
                chunk_frames = min(remaining, 48_000)
                payload = waveform.readframes(chunk_frames)
                expected_bytes = chunk_frames * 2 * 2
                if len(payload) != expected_bytes:
                    raise CustomFilmContractError(
                        "Custom Film Remotion intermediate WAV is truncated"
                    )
                remaining -= chunk_frames
            if waveform.readframes(1):
                raise CustomFilmContractError(
                    "Custom Film Remotion intermediate WAV has excess samples"
                )
    except (EOFError, OSError, wave.Error) as exc:
        raise CustomFilmContractError(
            "Custom Film Remotion intermediate WAV is undecodable"
        ) from exc
    return {
        "manifest_version": _INTERMEDIATE_CONTENT_MANIFEST_VERSION,
        "total_frames": total_frames,
        "frames": ordered_frame_hashes,
        "audio": {
            "name": raw_audio.name,
            "sha256": _sha256_path(raw_audio),
        },
    }


def _validate_intermediate_cache(
    *,
    cache_dir: Path,
    identity: Mapping[str, Any],
    total_frames: int,
    fps: int,
    width: int,
    height: int,
) -> None:
    identity_path = cache_dir / "identity.json"
    try:
        cached_identity = json.loads(identity_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CustomFilmContractError(
            "Custom Film Remotion intermediate cache identity is invalid"
        ) from exc
    if cached_identity != dict(identity):
        raise CustomFilmContractError(
            "Custom Film Remotion intermediate cache identity changed"
        )
    content_path = cache_dir / "content-manifest.json"
    try:
        cached_content = json.loads(content_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CustomFilmContractError(
            "Custom Film Remotion intermediate content manifest is invalid"
        ) from exc
    actual_content = _validate_lossless_intermediates(
        raw_frames=cache_dir / "raw-frames",
        raw_audio=cache_dir / "raw-audio.wav",
        total_frames=total_frames,
        fps=fps,
        width=width,
        height=height,
    )
    if cached_content != actual_content:
        raise CustomFilmContractError(
            "Custom Film Remotion intermediate content hash changed"
        )


def _ffconcat_quote(path: Path) -> str:
    return "'" + str(path.resolve()).replace("'", "'\\''") + "'"


def _write_frame_concat_manifest(
    *,
    raw_frames: Path,
    destination: Path,
    total_frames: int,
    fps: int,
) -> None:
    duration = f"{1 / fps:.12f}"
    lines = ["ffconcat version 1.0"]
    for frame in range(total_frames):
        lines.extend(
            [
                f"file {_ffconcat_quote(raw_frames / f'frame-{frame:04d}.png')}",
                f"duration {duration}",
            ]
        )
    # The concat demuxer applies the final duration only when a following file
    # establishes its end timestamp. The video filter trims this repeated frame.
    lines.append(
        f"file {_ffconcat_quote(raw_frames / f'frame-{total_frames - 1:04d}.png')}"
    )
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _validate_props_asset_transform(
    value: Any, *, output_duration_ms: int
) -> dict[str, Any]:
    transform = _strict_mapping(
        value, "Remotion asset timing transform", keys=_TIMING_TRANSFORM_KEYS
    )
    mode = _text(transform.get("mode"), "Remotion asset timing mode")
    shapes = {
        "none": {
            "mode",
            "source_duration_ms",
            "output_duration_ms",
        },
        "trim": {
            "mode",
            "source_duration_ms",
            "output_duration_ms",
            "trim_start_ms",
            "trim_end_ms",
        },
        "repeat_then_trim": {
            "mode",
            "source_duration_ms",
            "output_duration_ms",
            "repeat_count",
            "final_repeat_duration_ms",
        },
        "static_hold": {
            "mode",
            "source_duration_ms",
            "output_duration_ms",
        },
    }
    if mode not in shapes or set(transform) != shapes[mode]:
        raise CustomFilmContractError(
            "Custom Film Remotion asset timing shape changed"
        )
    if transform["output_duration_ms"] != output_duration_ms:
        raise CustomFilmContractError(
            "Custom Film Remotion asset output duration changed"
        )
    if mode == "static_hold":
        if transform["source_duration_ms"] is not None:
            raise CustomFilmContractError(
                "Custom Film Remotion still source duration changed"
            )
    else:
        source_duration_ms = _exact_int(
            transform["source_duration_ms"],
            "Remotion asset source duration",
            1,
        )
        if mode == "none" and source_duration_ms != output_duration_ms:
            raise CustomFilmContractError(
                "Custom Film Remotion untransformed asset timing changed"
            )
    if mode == "trim":
        trim_start = _exact_int(
            transform["trim_start_ms"], "Remotion trim start"
        )
        trim_end = _exact_int(
            transform["trim_end_ms"], "Remotion trim end", 1
        )
        if (
            source_duration_ms < output_duration_ms
            or trim_start != 0
            or trim_end != output_duration_ms
        ):
            raise CustomFilmContractError(
                "Custom Film Remotion trim duration changed"
            )
    elif mode == "repeat_then_trim":
        repeat_count = _exact_int(
            transform["repeat_count"], "Remotion repeat count", 1
        )
        final_repeat = _exact_int(
            transform["final_repeat_duration_ms"],
            "Remotion final repeat duration",
            1,
        )
        expected_repeats = (
            output_duration_ms + source_duration_ms - 1
        ) // source_duration_ms
        if (
            source_duration_ms >= output_duration_ms
            or repeat_count != expected_repeats
            or final_repeat
            != output_duration_ms
            - ((repeat_count - 1) * source_duration_ms)
        ):
            raise CustomFilmContractError(
                "Custom Film Remotion repeat timing changed"
            )
    return transform


def _validate_props_audio_transform(
    value: Any, *, output_duration_ms: int
) -> dict[str, Any]:
    transform = _strict_mapping(
        value, "Remotion audio timing transform", keys=_TIMING_TRANSFORM_KEYS
    )
    mode = _text(transform.get("mode"), "Remotion audio timing mode")
    expected = {
        "mode",
        "source_duration_ms",
        "output_duration_ms",
        "atempo_chain",
        "caption_scale",
    }
    if mode == "cue_schedule":
        expected.add("cues")
    if (
        mode not in {"none", "source_clip", "atempo", "cue_schedule"}
        or set(transform) != expected
    ):
        raise CustomFilmContractError(
            "Custom Film Remotion audio timing shape changed"
        )
    source_ms = _exact_int(
        transform["source_duration_ms"], "Remotion audio source duration", 1
    )
    if transform["output_duration_ms"] != output_duration_ms:
        raise CustomFilmContractError(
            "Custom Film Remotion audio output duration changed"
        )
    factors = [
        _finite_number(value, "Remotion atempo factor", 0.5)
        for value in _strict_sequence(
            transform["atempo_chain"], "Remotion atempo chain"
        )
    ]
    if any(value > 2 for value in factors):
        raise CustomFilmContractError(
            "Custom Film Remotion atempo factor is unsupported"
        )
    scale = _finite_number(
        transform["caption_scale"], "Remotion caption scale", 0.000001
    )
    approximately = lambda left, right: abs(left - right) <= (
        1e-7 * max(1, abs(left), abs(right))
    )
    if mode == "cue_schedule":
        if factors or not approximately(scale, 1):
            raise CustomFilmContractError(
                "Custom Film Remotion cue schedule rate changed"
            )
        cues = _strict_sequence(transform["cues"], "Remotion audio cues")
        previous_source_end = 0
        previous_target_end = 0
        for index, cue_value in enumerate(cues):
            cue = _strict_mapping(cue_value, "Remotion audio cue")
            if set(cue) != {
                "segment_index",
                "text_hash",
                "source_start_ms",
                "source_end_ms",
                "target_start_ms",
                "target_end_ms",
            }:
                raise CustomFilmContractError(
                    "Custom Film Remotion audio cue shape changed"
                )
            source_start = _exact_int(
                cue["source_start_ms"], "Remotion cue source start"
            )
            source_end = _exact_int(
                cue["source_end_ms"], "Remotion cue source end", 1
            )
            target_start = _exact_int(
                cue["target_start_ms"], "Remotion cue target start"
            )
            target_end = _exact_int(
                cue["target_end_ms"], "Remotion cue target end", 1
            )
            _hash(cue["text_hash"], "Remotion cue text hash")
            if (
                cue["segment_index"] != index
                or source_start < previous_source_end
                or source_end <= source_start
                or source_end > source_ms
                or target_start < previous_target_end
                or target_end <= target_start
                or target_end > output_duration_ms
                or target_end - target_start != source_end - source_start
            ):
                raise CustomFilmContractError(
                    "Custom Film Remotion audio cue timing changed"
                )
            previous_source_end = source_end
            previous_target_end = target_end
        if len(cues) < 2:
            raise CustomFilmContractError(
                "Custom Film Remotion cue schedule is incomplete"
            )
        return transform
    rate = math.prod(factors)
    expected_rate = source_ms / output_duration_ms
    if not approximately(rate, expected_rate) or not approximately(
        scale, 1 / expected_rate
    ):
        raise CustomFilmContractError(
            "Custom Film Remotion audio timing transform changed"
        )
    if mode == "none" and (factors or source_ms != output_duration_ms):
        raise CustomFilmContractError(
            "Custom Film Remotion untransformed audio timing changed"
        )
    if mode == "atempo" and not factors:
        raise CustomFilmContractError(
            "Custom Film Remotion atempo timing is incomplete"
        )
    return transform


def _validate_renderer_props(value: Any) -> dict[str, Any]:
    props = _strict_mapping(value, "Remotion renderer props")
    if set(props) != {
        "schema_version",
        "identity",
        "video",
        "transition_accounting",
        "orchestration",
        "sections",
        "props_hash",
    }:
        raise CustomFilmContractError(
            "Custom Film Remotion renderer props shape changed"
        )
    props_hash = _hash(props["props_hash"], "Remotion props hash")
    body = copy.deepcopy(props)
    del body["props_hash"]
    if remotion_props_hash(body) != props_hash:
        raise CustomFilmContractError("Custom Film Remotion props hash changed")
    if props["schema_version"] != REMOTION_PROPS_VERSION:
        raise CustomFilmContractError(
            "Custom Film Remotion props version is unsupported"
        )
    _assert_provider_opaque(props)
    identity = _strict_mapping(
        props["identity"],
        "Remotion props identity",
        keys=_PROPS_IDENTITY_V3_KEYS,
    )
    if set(identity) != _PROPS_IDENTITY_V3_KEYS:
        raise CustomFilmContractError(
            "Custom Film Remotion renderer identity is incomplete"
        )
    orchestration = _strict_mapping(
        props["orchestration"],
        "Remotion orchestration contract",
    )
    orchestration_body = copy.deepcopy(orchestration)
    orchestration_hash = _hash(
        orchestration_body.pop("contract_hash", None),
        "Remotion orchestration contract hash",
    )
    resolved_plan = _strict_mapping(
        orchestration.get("resolved_plan"),
        "Remotion approved resolved plan",
    )
    recipes = _strict_sequence(
        resolved_plan.get("recipes"),
        "Remotion approved recipes",
    )
    if (
        canonical_hash(orchestration_body) != orchestration_hash
        or orchestration.get("semantic_input_hash")
        != canonical_hash(
            _strict_mapping(
                orchestration.get("semantic_input"),
                "Remotion orchestration semantic input",
            )
        )
        or orchestration.get("resolved_plan_hash")
        != canonical_hash(resolved_plan)
        or orchestration.get("recipe_hash") != canonical_hash(recipes)
    ):
        raise CustomFilmContractError(
            "Custom Film Remotion orchestration contract changed"
        )
    for key in ("tenant_id", "video_id", "plan_id", "runtime_job_id"):
        _text(identity[key], f"Remotion identity {key}")
    for key in (
        "assembly_manifest_hash",
        "plan_hash",
        "quote_inputs_hash",
        "approval_hash",
        "runtime_hash",
        "renderer_bundle_hash",
    ):
        _hash(identity[key], f"Remotion identity {key}")
    _finite_number(identity["max_spend"], "Remotion max spend")
    if (
        identity.get("assembly_version") != EXPECTED_ASSEMBLY_VERSION
        or identity.get("render_engine") != "remotion"
        or identity.get("renderer_contract_version")
        != REMOTION_RENDERER_CONTRACT_VERSION
        or _hash(
            identity.get("renderer_bundle_hash"), "renderer bundle hash"
        )
        != renderer_bundle_hash()
    ):
        raise CustomFilmContractError(
            "Custom Film Remotion renderer identity changed"
        )
    video = _strict_mapping(
        props["video"], "Remotion video contract", keys=_PROPS_VIDEO_KEYS
    )
    if set(video) != _PROPS_VIDEO_KEYS:
        raise CustomFilmContractError(
            "Custom Film Remotion video contract is incomplete"
        )
    fps = _exact_int(video.get("fps"), "Remotion fps", 1)
    frames = _exact_int(video.get("total_frames"), "Remotion frames", 1)
    seconds = _exact_int(
        video.get("total_duration_seconds"), "Remotion seconds", 1
    )
    _exact_int(video.get("width"), "Remotion width", 2)
    _exact_int(video.get("height"), "Remotion height", 2)
    if frames != fps * seconds:
        raise CustomFilmContractError(
            "Custom Film Remotion duration identity changed"
        )
    if (
        resolved_plan.get("fps") != fps
        or resolved_plan.get("total_frames") != frames
    ):
        raise CustomFilmContractError(
            "Custom Film Remotion resolved plan changed its approved video timing"
        )
    transition_accounting = _strict_mapping(
        props["transition_accounting"],
        "Remotion transition accounting",
        keys=_PROPS_TRANSITION_ACCOUNTING_KEYS,
    )
    if (
        set(transition_accounting) != _PROPS_TRANSITION_ACCOUNTING_KEYS
        or not _text(
            transition_accounting["type"], "Remotion transition type"
        )
        or not _text(
            transition_accounting["duration_source"],
            "Remotion transition duration source",
        )
        or transition_accounting["overlap_frames_total"] != 0
        or transition_accounting[
            "duration_lives_inside_assigned_sections"
        ]
        is not True
    ):
        raise CustomFilmContractError(
            "Custom Film Remotion transition accounting changed"
        )
    sections = _strict_sequence(props["sections"], "Remotion sections")
    if not sections:
        raise CustomFilmContractError("Custom Film Remotion sections are empty")
    film_frame = 0
    for order_index, section_value in enumerate(sections):
        section = _strict_mapping(
            section_value, "Remotion section", keys=_SECTION_KEYS
        )
        if set(section) != _SECTION_KEYS:
            raise CustomFilmContractError(
                "Custom Film Remotion section shape changed"
            )
        section_id = _text(section["section_id"], "Remotion section id")
        section_start = _exact_int(
            section["start_frame"], "Remotion section start"
        )
        section_frames = _exact_int(
            section["duration_frames"], "Remotion section frames", 1
        )
        if (
            section["order_index"] != order_index
            or section_start != film_frame
        ):
            raise CustomFilmContractError(
                "Custom Film Remotion section order changed"
            )
        for key in ("role", "render_mode", "visual_profile", "dialogue_audio"):
            _text(section[key], f"Remotion section {key}")
        scene_ids = [
            _text(scene_id, "Remotion scene id")
            for scene_id in _strict_sequence(
                section["scene_ids"], "Remotion scene ids"
            )
        ]
        if not scene_ids:
            raise CustomFilmContractError(
                "Custom Film Remotion scene identities are empty"
            )
        for key in ("transition_in", "transition_out"):
            transition = _strict_mapping(
                section[key], f"Remotion {key}", keys=_TRANSITION_KEYS
            )
            if (
                set(transition) != _TRANSITION_KEYS
                or not _text(transition["type"], f"Remotion {key} type")
                or not _text(transition["audio"], f"Remotion {key} audio")
                or _exact_int(
                    transition["duration_frames"],
                    f"Remotion {key} frames",
                )
                > section_frames
                or transition["overlap_frames"] != 0
                or transition["accounting"] != "inside_section"
            ):
                raise CustomFilmContractError(
                    "Custom Film Remotion section transition changed"
                )
        assets = _strict_sequence(section["assets"], "Remotion assets")
        if not assets:
            raise CustomFilmContractError(
                "Custom Film Remotion section assets are empty"
            )
        asset_frame = 0
        for asset_value in assets:
            asset = _strict_mapping(
                asset_value, "Remotion asset", keys=_PROPS_ASSET_KEYS
            )
            if set(asset) != _PROPS_ASSET_KEYS:
                raise CustomFilmContractError(
                    "Custom Film Remotion asset shape changed"
                )
            for key in ("asset_id", "source_key"):
                _text(asset[key], f"Remotion asset {key}")
            for key in ("source_sha256", "provenance_hash", "caption_hash"):
                _hash(asset[key], f"Remotion asset {key}")
            if asset["caption_card"] is not None:
                _strict_mapping(asset["caption_card"], "Remotion caption card")
            for key in ("actual_duration_ms", "assigned_duration_ms"):
                if asset[key] is not None:
                    _exact_int(asset[key], f"Remotion asset {key}", 1)
            start = _exact_int(asset["start_frame"], "Remotion asset start")
            duration = _exact_int(
                asset["duration_frames"], "Remotion asset frames", 1
            )
            if start != asset_frame:
                raise CustomFilmContractError(
                    "Custom Film Remotion asset order changed"
                )
            transform_value = _strict_mapping(
                asset["timing_transform"],
                "Remotion asset timing transform",
            )
            transform_mode = transform_value.get("mode")
            expected_output_ms = (
                duration * 1000 // fps
                if transform_mode == "static_hold"
                else _exact_int(
                    asset["assigned_duration_ms"],
                    "Remotion assigned asset duration",
                    1,
                )
            )
            transform = _validate_props_asset_transform(
                asset["timing_transform"],
                output_duration_ms=expected_output_ms,
            )
            if transform_mode == "static_hold" and (
                asset["actual_duration_ms"] is not None
                or asset["assigned_duration_ms"] is not None
            ):
                raise CustomFilmContractError(
                    "Custom Film Remotion still duration identity changed"
                )
            if transform_mode != "static_hold" and asset[
                "actual_duration_ms"
            ] != transform["source_duration_ms"]:
                raise CustomFilmContractError(
                    "Custom Film Remotion asset source duration changed"
                )
            _strict_mapping(asset["camera"], "Remotion asset camera")
            asset_frame += duration
        if asset_frame != section_frames:
            raise CustomFilmContractError(
                "Custom Film Remotion assets do not fill their section"
            )
        audio = _strict_mapping(
            section["audio"], "Remotion audio", keys=_PROPS_AUDIO_KEYS
        )
        if set(audio) != _PROPS_AUDIO_KEYS:
            raise CustomFilmContractError(
                "Custom Film Remotion audio shape changed"
            )
        audio_mode = _text(audio["mode"], "Remotion audio mode")
        sources = _strict_sequence(audio["sources"], "Remotion audio sources")
        source_duration_ms = 0
        for source_value in sources:
            source = _strict_mapping(
                source_value,
                "Remotion audio source",
                keys=_PROPS_AUDIO_SOURCE_KEYS,
            )
            if set(source) != _PROPS_AUDIO_SOURCE_KEYS:
                raise CustomFilmContractError(
                    "Custom Film Remotion audio source shape changed"
                )
            _text(source["source_key"], "Remotion audio source key")
            _hash(source["source_sha256"], "Remotion audio source hash")
            source_duration_ms += _exact_int(
                source["source_duration_ms"],
                "Remotion audio source duration",
                1,
            )
        section_output_ms = section_frames * 1000
        if section_output_ms % fps:
            raise CustomFilmContractError(
                "Custom Film Remotion section duration is not frame exact"
            )
        audio_transform = _validate_props_audio_transform(
            audio["timing_transform"],
            output_duration_ms=section_output_ms // fps,
        )
        if audio_transform["mode"] == "cue_schedule" and any(
            cue[key] * fps % 1000
            for cue in audio_transform["cues"]
            for key in (
                "source_start_ms",
                "source_end_ms",
                "target_start_ms",
                "target_end_ms",
            )
        ):
            raise CustomFilmContractError(
                "Custom Film Remotion audio cue is not frame exact"
            )
        source_clip = audio_mode == "source_clip"
        if source_clip != (audio_transform["mode"] == "source_clip"):
            raise CustomFilmContractError(
                "Custom Film Remotion audio mode and timing disagree"
            )
        if source_clip:
            if sources or any(
                asset["timing_transform"]["mode"] == "static_hold"
                for asset in assets
            ):
                raise CustomFilmContractError(
                    "Custom Film Remotion source_clip media changed"
                )
        elif (
            not sources
            or source_duration_ms != audio_transform["source_duration_ms"]
        ):
            raise CustomFilmContractError(
                "Custom Film Remotion narration source timing changed"
            )
        _finite_number(audio["gain_db"], "Remotion audio gain", -120)
        captions = _strict_sequence(
            section["captions"], "Remotion captions"
        )
        if not captions:
            raise CustomFilmContractError(
                "Custom Film Remotion captions are empty"
            )
        caption_end = section_start
        for caption_value in captions:
            caption = _strict_mapping(
                caption_value, "Remotion caption", keys=_CAPTION_KEYS
            )
            if set(caption) != _CAPTION_KEYS:
                raise CustomFilmContractError(
                    "Custom Film Remotion caption shape changed"
                )
            scene_id = _text(caption["scene_id"], "Remotion caption scene")
            _text(caption["text"], "Remotion caption text")
            _strict_mapping(caption["language"], "Remotion caption language")
            section_start_ms = _exact_int(
                caption["section_start_ms"],
                "Remotion caption section start",
            )
            section_end_ms = _exact_int(
                caption["section_end_ms"], "Remotion caption section end", 1
            )
            start = _exact_int(
                caption["start_frame"], "Remotion caption start"
            )
            end = _exact_int(
                caption["end_frame"], "Remotion caption end", 1
            )
            if (
                scene_id not in scene_ids
                or (
                    audio_transform["mode"] != "cue_schedule"
                    and start != caption_end
                )
                or (
                    audio_transform["mode"] == "cue_schedule"
                    and start < caption_end
                )
                or end <= start
                or end > section_start + section_frames
                or start != section_start + section_start_ms * fps // 1000
                or end != section_start + section_end_ms * fps // 1000
            ):
                raise CustomFilmContractError(
                    "Custom Film Remotion caption timing changed"
                )
            caption_end = end
        expected_caption_end = section_start + section_frames
        if audio_transform["mode"] == "cue_schedule":
            cues = audio_transform["cues"]
            if len(captions) != len(cues) or any(
                caption["section_start_ms"] != cue["target_start_ms"]
                or caption["section_end_ms"] != cue["target_end_ms"]
                or canonical_hash(
                    {
                        "segment_index": index,
                        "text": caption["text"],
                    }
                )
                != cue["text_hash"]
                for index, (caption, cue) in enumerate(zip(captions, cues))
            ):
                raise CustomFilmContractError(
                    "Custom Film Remotion captions changed cue schedule"
                )
            expected_caption_end = section_start + (
                cues[-1]["target_end_ms"] * fps // 1000
            )
        if caption_end != expected_caption_end:
            raise CustomFilmContractError(
                "Custom Film Remotion captions do not match approved audio"
            )
        film_frame += section_frames
    if film_frame != frames:
        raise CustomFilmContractError(
            "Custom Film Remotion sections do not fill the film"
        )
    from custom_film_orchestration import validate_executable_orchestration
    validate_executable_orchestration(
        orchestration,
        total_duration_seconds=seconds,
        section_duration_seconds=[
            int(section["duration_frames"]) // fps for section in sections
        ],
        fps=fps,
    )
    _renderer_source_specs(props)
    return props


def _srt_timestamp(frame: int, fps: int) -> str:
    milliseconds = round(frame * 1000 / fps)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def _write_approved_srt(props: Mapping[str, Any], path: Path) -> list[dict[str, Any]]:
    captions = [
        copy.deepcopy(caption)
        for section in props["sections"]
        for caption in section["captions"]
    ]
    captions.sort(key=lambda caption: int(caption["start_frame"]))
    entries: list[str] = []
    for index, caption in enumerate(captions, start=1):
        start = _exact_int(caption["start_frame"], "caption start frame")
        end = _exact_int(caption["end_frame"], "caption end frame", 1)
        if end <= start:
            raise CustomFilmContractError(
                "Custom Film Remotion caption timing changed"
            )
        text = _text(caption["text"], "caption text").replace("\r", "")
        entries.append(
            f"{index}\n{_srt_timestamp(start, props['video']['fps'])} --> "
            f"{_srt_timestamp(end, props['video']['fps'])}\n{text}\n"
        )
    if not entries:
        raise CustomFilmContractError(
            "Custom Film Remotion approved captions are missing"
        )
    path.write_text("\n".join(entries), encoding="utf-8", newline="\n")
    return captions


def _subtitle_language(props: Mapping[str, Any]) -> str:
    languages: set[str] = set()
    mixed = False
    for section in props["sections"]:
        for caption in section["captions"]:
            language = caption.get("language")
            if not isinstance(language, Mapping):
                continue
            if language.get("mode") == "bilingual":
                mixed = True
            declared = language.get("languages")
            if isinstance(declared, list):
                languages.update(
                    str(value).strip().lower()
                    for value in declared
                    if str(value).strip()
                )
            single = str(language.get("language") or "").strip().lower()
            if single:
                languages.add(single)
    return "mul" if mixed or len(languages) > 1 else next(iter(languages), "und")


async def _run_local_command(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout_seconds: float,
    log_path: Path,
) -> None:
    """Run without a shell/network helper and retain only a bounded log tail."""
    if not command or any(not isinstance(part, str) for part in command):
        raise CustomFilmContractError(
            "Custom Film Remotion local command is invalid"
        )
    with log_path.open("ab") as log:
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(cwd),
                stdout=log,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as exc:
            from custom_film_compositor import CustomFilmRetryableError

            raise CustomFilmRetryableError(
                "Custom Film Remotion local executable is unavailable"
            ) from exc
        try:
            await asyncio.wait_for(process.wait(), timeout=timeout_seconds)
        except asyncio.TimeoutError as exc:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                await asyncio.wait_for(process.wait(), timeout=5)
            except (ProcessLookupError, asyncio.TimeoutError):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await process.wait()
            from custom_film_compositor import CustomFilmRetryableError

            raise CustomFilmRetryableError(
                "Custom Film Remotion local render timed out"
            ) from exc
        except asyncio.CancelledError:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await process.wait()
            raise
    if process.returncode:
        # The bounded log is intentionally ephemeral. It may contain local
        # paths, so no part of it crosses the durable/user-facing error seam.
        with log_path.open("rb") as log:
            log.seek(0, os.SEEK_END)
            log.seek(max(0, log.tell() - _PROCESS_LOG_LIMIT))
            log.read(_PROCESS_LOG_LIMIT)
        from custom_film_compositor import CustomFilmRetryableError

        raise CustomFilmRetryableError(
            "Custom Film Remotion local command failed"
        )


async def _probe_renderer_media(path: Path) -> Mapping[str, Any]:
    from custom_film_compositor import CustomFilmRetryableError

    process: asyncio.subprocess.Process | None = None
    try:
        process = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            (
                "format=duration:"
                "stream=codec_type,duration,duration_ts,time_base,"
                "nb_frames,avg_frame_rate"
            ),
            "-of",
            "json",
            str(path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=30
        )
    except OSError as exc:
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()
        raise CustomFilmRetryableError(
            "Custom Film Remotion media probe is unavailable"
        ) from exc
    except asyncio.CancelledError:
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()
        raise
    except asyncio.TimeoutError as exc:
        try:
            process.kill()
            await process.wait()
        except (OSError, ProcessLookupError):
            pass
        raise CustomFilmRetryableError(
            "Custom Film Remotion media probe timed out"
        ) from exc
    if process.returncode:
        detail = stderr.decode("utf-8", errors="replace").lower()
        invalid_markers = (
            "invalid data found",
            "moov atom not found",
            "could not find codec parameters",
            "unknown format",
        )
        if any(marker in detail for marker in invalid_markers):
            raise CustomFilmContractError(
                "Custom Film Remotion approved source media is invalid"
            )
        raise CustomFilmRetryableError(
            "Custom Film Remotion media probe process failed"
        )
    try:
        payload = json.loads(stdout)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise CustomFilmRetryableError(
            "Custom Film Remotion media probe returned invalid output"
        ) from exc
    if not isinstance(payload, Mapping):
        raise CustomFilmRetryableError(
            "Custom Film Remotion media probe returned invalid output"
        )
    streams = payload.get("streams")
    if not isinstance(streams, list):
        streams = []
    stream_types = {
        stream.get("codec_type")
        for stream in streams
        if isinstance(stream, Mapping)
    }

    def stream_duration(kind: str) -> float | None:
        for stream in streams:
            if (
                not isinstance(stream, Mapping)
                or stream.get("codec_type") != kind
            ):
                continue
            raw_duration = stream.get("duration")
            if raw_duration not in (None, "", "N/A"):
                try:
                    result = float(raw_duration)
                except (TypeError, ValueError) as exc:
                    raise CustomFilmRetryableError(
                        "Custom Film Remotion media probe returned invalid duration"
                    ) from exc
                if not math.isfinite(result) or result < 0:
                    raise CustomFilmRetryableError(
                        "Custom Film Remotion media probe returned invalid duration"
                    )
                return result
            duration_ts = stream.get("duration_ts")
            time_base = stream.get("time_base")
            if duration_ts not in (None, "", "N/A") and time_base not in (
                None,
                "",
                "N/A",
            ):
                try:
                    numerator, denominator = str(time_base).split("/", 1)
                    result = (
                        int(duration_ts) * int(numerator) / int(denominator)
                    )
                except (TypeError, ValueError, ZeroDivisionError) as exc:
                    raise CustomFilmRetryableError(
                        "Custom Film Remotion media probe returned invalid duration"
                    ) from exc
                if not math.isfinite(result) or result < 0:
                    raise CustomFilmRetryableError(
                        "Custom Film Remotion media probe returned invalid duration"
                    )
                return result
        return None
    duration: float | None = None
    format_value = payload.get("format")
    if isinstance(format_value, Mapping) and format_value.get("duration") not in (
        None,
        "",
        "N/A",
    ):
        try:
            candidate = float(format_value["duration"])
        except (TypeError, ValueError) as exc:
            raise CustomFilmRetryableError(
                "Custom Film Remotion media probe returned invalid duration"
            ) from exc
        if not math.isfinite(candidate) or candidate < 0:
            raise CustomFilmRetryableError(
                "Custom Film Remotion media probe returned invalid duration"
            )
        duration = candidate
    return {
        "has_video": "video" in stream_types,
        "has_audio": "audio" in stream_types,
        "duration_seconds": duration,
        "video_duration_seconds": stream_duration("video"),
        "audio_duration_seconds": stream_duration("audio"),
    }


async def _stage_renderer_sources(
    props: Mapping[str, Any],
    source_paths: Mapping[str, Path | str],
    *,
    staging: Path,
    log_path: Path,
) -> list[dict[str, Any]]:
    def native_audio_covers_video(probe: Mapping[str, Any]) -> bool:
        video_duration = probe.get("video_duration_seconds")
        audio_duration = probe.get("audio_duration_seconds")
        if video_duration is None or audio_duration is None:
            return False
        video_seconds = float(video_duration)
        audio_seconds = float(audio_duration)
        return (
            audio_seconds + _STREAM_COVERAGE_TOLERANCE_SECONDS
            >= video_seconds
            and audio_seconds - video_seconds <= _AAC_PACKET_PADDING_SECONDS
        )

    specs = _renderer_source_specs(props)
    expected = {spec["source_key"] for spec in specs}
    actual = {str(key) for key in source_paths}
    if actual != expected:
        raise CustomFilmContractError(
            "Custom Film Remotion source keys are missing or unknown"
        )
    raw_dir = staging / "raw"
    public_dir = staging / "public"
    raw_dir.mkdir(parents=True)
    provenance: list[dict[str, Any]] = []
    for spec in specs:
        key = spec["source_key"]
        source = Path(source_paths[key])
        if not source.is_file() or source.stat().st_size == 0:
            raise CustomFilmContractError(
                "Custom Film Remotion approved source is missing"
            )
        raw = raw_dir / hashlib.sha256(key.encode("utf-8")).hexdigest()
        shutil.copyfile(source, raw)
        raw_hash = hashlib.sha256(raw.read_bytes()).hexdigest()
        if raw_hash != spec["sha256"]:
            raise CustomFilmContractError(
                "Custom Film Remotion approved source hash changed"
            )
        raw_probe = await _probe_renderer_media(raw)
        if spec["kind"] == "image":
            valid_raw = (
                bool(raw_probe["has_video"])
                and not bool(raw_probe["has_audio"])
            )
        elif spec["kind"] == "audio":
            raw_duration = raw_probe.get("audio_duration_seconds")
            valid_raw = (
                bool(raw_probe["has_audio"])
                and not bool(raw_probe["has_video"])
                and raw_duration is not None
                and round(float(raw_duration) * 1000)
                == spec["source_duration_ms"]
            )
        else:
            raw_duration = raw_probe.get("video_duration_seconds")
            valid_raw = (
                bool(raw_probe["has_video"])
                and raw_duration is not None
                and round(float(raw_duration) * 1000)
                == spec["source_duration_ms"]
                and (
                    not spec["requires_native_audio"]
                    or (
                        bool(raw_probe["has_audio"])
                        and native_audio_covers_video(raw_probe)
                    )
                )
            )
        if not valid_raw:
            raise CustomFilmContractError(
                "Custom Film Remotion approved source media identity changed"
            )
        relative = Path(staged_local_path_for_source_key(key, spec["kind"]))
        staged = public_dir / relative
        staged.parent.mkdir(parents=True, exist_ok=True)
        if spec["kind"] == "image":
            command = [
                "ffmpeg", "-y", "-i", str(raw), "-frames:v", "1",
                "-c:v", "png", "-map_metadata", "-1", str(staged),
            ]
        elif spec["kind"] == "audio":
            command = [
                "ffmpeg", "-y", "-i", str(raw), "-map", "0:a:0",
                "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2",
                "-map_metadata", "-1", str(staged),
            ]
        else:
            command = ["ffmpeg", "-y", "-i", str(raw), "-map", "0:v:0"]
            if spec["requires_native_audio"]:
                approved_samples = spec["source_duration_ms"] * 48
                command.extend(
                    [
                        "-map",
                        "0:a:0",
                        "-af",
                        (
                            f"aresample=48000,atrim=end_sample={approved_samples},"
                            "asetpts=N/SR/TB"
                        ),
                    ]
                )
            else:
                command.extend(["-map", "0:a?"])
            command.extend(
                [
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000",
                    "-ac", "2", "-map_metadata", "-1", str(staged),
                ]
            )
        await _run_local_command(
            command,
            cwd=staging,
            timeout_seconds=600,
            log_path=log_path,
        )
        if not staged.is_file() or staged.stat().st_size == 0:
            raise CustomFilmContractError(
                "Custom Film Remotion staged source is empty"
            )
        staged_probe = await _probe_renderer_media(staged)
        if spec["kind"] == "image":
            valid_staged = (
                bool(staged_probe["has_video"])
                and not bool(staged_probe["has_audio"])
            )
        elif spec["kind"] == "audio":
            staged_duration = staged_probe.get("audio_duration_seconds")
            valid_staged = (
                bool(staged_probe["has_audio"])
                and not bool(staged_probe["has_video"])
                and staged_duration is not None
                and round(float(staged_duration) * 1000)
                == spec["source_duration_ms"]
            )
        else:
            staged_duration = staged_probe.get("video_duration_seconds")
            valid_staged = (
                bool(staged_probe["has_video"])
                and staged_duration is not None
                and round(float(staged_duration) * 1000)
                == spec["source_duration_ms"]
                and (
                    not spec["requires_native_audio"]
                    or (
                        bool(staged_probe["has_audio"])
                        and native_audio_covers_video(staged_probe)
                    )
                )
            )
        if not valid_staged:
            raise CustomFilmContractError(
                "Custom Film Remotion staged media type changed"
            )
        provenance.append(
            {
                "source_key": key,
                "kind": spec["kind"],
                "source_sha256": raw_hash,
                "staged_sha256": hashlib.sha256(
                    staged.read_bytes()
                ).hexdigest(),
            }
        )
    return provenance


async def run_remotion_renderer(
    *,
    remotion_props: Mapping[str, Any],
    source_paths: Mapping[str, Path | str],
    output_path: Path,
    on_progress: ProgressCallback | None = None,
    timeout_seconds: float = _DEFAULT_RENDER_TIMEOUT_SECONDS,
    intermediate_cache_root: Path | None = None,
) -> Mapping[str, Any]:
    """Render one already-journaled assembly-v3 identity locally."""
    from custom_film_compositor import (
        CustomFilmRetryableError,
        probe_media,
        probe_has_exact_video_identity,
    )

    props = _validate_renderer_props(remotion_props)
    project = _remotion_project_root()
    cli = project / "node_modules/.bin/remotion"
    entry = project / "src/index.ts"
    node = shutil.which("node")
    browser_candidates = [
        os.getenv("REMOTION_BROWSER_EXECUTABLE", ""),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/snap/bin/chromium",
    ]
    browser = next(
        (Path(value) for value in browser_candidates if value and Path(value).is_file()),
        None,
    )
    if not cli.is_file() or not entry.is_file() or not node or browser is None:
        raise CustomFilmRetryableError(
            "Custom Film Remotion local runtime is unavailable"
        )
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        raise CustomFilmContractError(
            "Custom Film Remotion output path must be new"
        )
    frames = int(props["video"]["total_frames"])
    fps = int(props["video"]["fps"])
    width = int(props["video"]["width"])
    height = int(props["video"]["height"])
    cache_identity = _intermediate_cache_identity(props)
    cache_root = (
        Path(intermediate_cache_root)
        if intermediate_cache_root is not None
        # Remotion treats a leading dot in any image-sequence destination path
        # component as an extension. Privacy comes from mode 0700, not hiding
        # the cache directory name.
        else output_path.parent / "custom-film-remotion-cache"
    )
    _private_directory(cache_root)
    cache_dir = cache_root / cache_identity["cache_key"]
    # Remotion rejects image-sequence output directories when any destination
    # path component looks like it has a file extension. Keep the private
    # in-progress directory extension-free.
    cache_partial = cache_root / (
        f"partial-{cache_identity['cache_key']}-{os.getpid()}"
    )
    workdir = Path(tempfile.mkdtemp(prefix="custom_film_remotion_"))
    log_path = workdir / "renderer.log"
    # Remotion's video encoders produced tiny cross-run pixel drift even when
    # independent PNG captures of every tested browser frame were byte-identical.
    # Keep frame capture and audio capture lossless and separate; the pinned,
    # single-thread normalization pass below is the only delivery encoder.
    raw_frames = cache_dir / "raw-frames"
    raw_audio = cache_dir / "raw-audio.wav"
    normalized = workdir / "normalized.mp4"
    props_path = workdir / "props.json"
    captions_path = workdir / "captions.srt"
    concat_path = workdir / "frames.ffconcat"
    succeeded = False
    retain_cache_on_failure = False
    try:
        if on_progress:
            await on_progress("Normalizing section 1/1, approved Remotion sources")
        provenance = await _stage_renderer_sources(
            props, source_paths, staging=workdir, log_path=log_path
        )
        await _run_local_command(
            [node, str(project / "scripts/generate-motion-audio.mjs")],
            cwd=workdir,
            timeout_seconds=120,
            log_path=log_path,
        )
        expected_motion_audio = project / "public/motion-audio"
        staged_motion_audio = workdir / "public/motion-audio"
        expected_audio_files = sorted(expected_motion_audio.glob("*.wav"))
        if not expected_audio_files or any(
            not (staged_motion_audio / source.name).is_file()
            or hashlib.sha256(source.read_bytes()).hexdigest()
            != hashlib.sha256(
                (staged_motion_audio / source.name).read_bytes()
            ).hexdigest()
            for source in expected_audio_files
        ):
            raise CustomFilmContractError(
                "Custom Film Remotion motion-audio fixtures changed"
            )
        props_path.write_text(
            canonical_remotion_json(props), encoding="utf-8", newline="\n"
        )
        captions = _write_approved_srt(props, captions_path)
        if on_progress:
            await on_progress(
                f"Rendering {len(props['sections'])}/"
                f"{len(props['sections'])} approved sections"
            )
        if cache_dir.exists():
            _validate_intermediate_cache(
                cache_dir=cache_dir,
                identity=cache_identity,
                total_frames=frames,
                fps=fps,
                width=width,
                height=height,
            )
            if on_progress:
                await on_progress(
                    "Reusing verified lossless Remotion intermediates"
                )
        else:
            if cache_partial.exists():
                shutil.rmtree(cache_partial)
            _private_directory(cache_partial)
            capture_frames = cache_partial / "raw-frames"
            capture_audio = cache_partial / "raw-audio.wav"
            frame_command = [
                str(cli), "render", str(entry), REMOTION_COMPOSITION_ID,
                str(capture_frames), f"--props={props_path}",
                f"--public-dir={workdir / 'public'}", "--sequence",
                "--image-format=png",
                "--image-sequence-pattern=frame-[frame].[ext]",
                "--concurrency=1", "--gl=angle",
                f"--browser-executable={browser}",
            ]
            await _run_local_command(
                frame_command,
                cwd=project,
                timeout_seconds=timeout_seconds,
                log_path=log_path,
            )
            audio_command = [
                str(cli), "render", str(entry), REMOTION_COMPOSITION_ID,
                str(capture_audio), f"--props={props_path}",
                f"--public-dir={workdir / 'public'}", "--codec=wav",
                "--concurrency=1", "--gl=angle",
                f"--browser-executable={browser}",
            ]
            await _run_local_command(
                audio_command,
                cwd=project,
                timeout_seconds=timeout_seconds,
                log_path=log_path,
            )
            content_manifest = _validate_lossless_intermediates(
                raw_frames=capture_frames,
                raw_audio=capture_audio,
                total_frames=frames,
                fps=fps,
                width=width,
                height=height,
            )
            _write_private_canonical_json(
                cache_partial / "identity.json", cache_identity
            )
            _write_private_canonical_json(
                cache_partial / "content-manifest.json",
                content_manifest,
            )
            os.replace(cache_partial, cache_dir)
            raw_frames = cache_dir / "raw-frames"
            raw_audio = cache_dir / "raw-audio.wav"
        _write_frame_concat_manifest(
            raw_frames=raw_frames,
            destination=concat_path,
            total_frames=frames,
            fps=fps,
        )
        samples = frames * 48_000 // fps
        language = _subtitle_language(props)
        try:
            await _run_local_command(
                [
                "ffmpeg", "-y", "-threads", "1",
                "-filter_threads", "1", "-filter_complex_threads", "1",
                "-reinit_filter", "0",
                "-xerror", "-err_detect", "explode",
                    "-f", "concat", "-safe", "0", "-i",
                    str(concat_path), "-i",
                    str(raw_audio), "-i", str(captions_path), "-filter_complex",
                    (
                        f"[0:v]fps={fps},scale={width}:{height},"
                        f"trim=end_frame={frames},setpts=N/({fps}*TB)[v];"
                        f"[1:a]aresample=48000,apad,atrim=end_sample={samples},"
                        "asetpts=N/SR/TB[a]"
                    ),
                    "-map", "[v]", "-map", "[a]", "-map", "2:0",
                    "-frames:v", str(frames), "-c:v", "libx264",
                    "-preset", "veryfast", "-crf", "18", "-pix_fmt",
                    "yuv420p", "-x264-params",
                    "threads=1:lookahead_threads=1:sliced_threads=0",
                    "-c:a", "aac", "-ar", "48000", "-ac", "2",
                    "-c:s", "mov_text", "-metadata:s:s:0",
                    f"language={language}", "-map_metadata", "-1",
                    "-map_chapters", "-1", str(normalized),
                ],
                cwd=workdir,
                timeout_seconds=timeout_seconds,
                log_path=log_path,
            )
            probe = await probe_media(normalized)
        except CustomFilmRetryableError:
            # Only a downstream error explicitly classified as retryable may
            # preserve expensive verified intermediates for a cold retry.
            retain_cache_on_failure = True
            raise
        expected_seconds = frames / fps
        if (
            not probe["has_video"]
            or not probe["has_audio"]
            or not probe["has_subtitles"]
            or not probe_has_exact_video_identity(
                probe,
                total_frames=frames,
                fps=fps,
                width=width,
                height=height,
            )
        ):
            raise CustomFilmContractError(
                "Custom Film Remotion normalized artifact failed exact probe: "
                + canonical_remotion_json(
                    {
                        "actual": {
                            "duration_seconds": probe["duration_seconds"],
                            "fps_fraction": probe.get("fps_fraction"),
                            "frame_count": probe["frame_count"],
                            "has_audio": probe["has_audio"],
                            "has_subtitles": probe["has_subtitles"],
                            "has_video": probe["has_video"],
                            "height": probe["height"],
                            "width": probe["width"],
                        },
                        "expected": {
                            "duration_seconds": expected_seconds,
                            "fps": fps,
                            "frame_count": frames,
                            "height": height,
                            "width": width,
                        },
                    }
                )
            )
        atomic = output_path.with_name(f".{output_path.name}.remotion-partial")
        shutil.copyfile(normalized, atomic)
        os.replace(atomic, output_path)
        artifact_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()
        section_provenance = [
            {
                "section_id": section["section_id"],
                "order_index": section["order_index"],
                "start_frame": section["start_frame"],
                "duration_frames": section["duration_frames"],
                "section_sha256": canonical_hash(
                    {
                        "props_hash": props["props_hash"],
                        "section": section,
                    }
                ),
            }
            for section in props["sections"]
        ]
        result = {
            "status": "rendered_local",
            "manifest_hash": props["identity"]["assembly_manifest_hash"],
            "props_hash": props["props_hash"],
            "renderer_bundle_hash": props["identity"]["renderer_bundle_hash"],
            "artifact_sha256": artifact_hash,
            "duration_seconds": expected_seconds,
            "total_frames": frames,
            "fps": fps,
            "resolution": f"{width}x{height}",
            "section_count": len(props["sections"]),
            "asset_count": sum(
                len(section["assets"]) for section in props["sections"]
            ),
            "captions": captions,
            "provenance": provenance,
            "section_provenance": section_provenance,
            "output_path": str(output_path),
        }
        succeeded = True
        shutil.rmtree(cache_dir)
        return result
    finally:
        partial = output_path.with_name(f".{output_path.name}.remotion-partial")
        if partial.exists():
            partial.unlink()
        if not succeeded and output_path.exists():
            output_path.unlink()
        if cache_partial.exists():
            shutil.rmtree(cache_partial, ignore_errors=True)
        if (
            cache_dir.exists()
            and not succeeded
            and not retain_cache_on_failure
        ):
            # Contract/probe failures are terminal for this captured identity.
            shutil.rmtree(cache_dir, ignore_errors=True)
        shutil.rmtree(workdir, ignore_errors=True)
