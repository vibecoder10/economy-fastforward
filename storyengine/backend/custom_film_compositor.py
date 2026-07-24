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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Sequence

from custom_film_contract import CustomFilmContractError, canonical_hash
from custom_film_section_runtime import compile_stage_adapters


ASSEMBLY_VERSION = "custom-film-assembly-v1"
DEFAULT_FPS = 24
SUPPORTED_TRANSFORMS = frozenset({"none", "trim", "repeat_then_trim"})
ProgressCallback = Callable[[str], Awaitable[None]]


def assembly_resume_action(state: str) -> str:
    """Return the only safe restart action for a durable assembly state."""
    if state == "finalized":
        return "return_finalized"
    if state == "uploaded":
        return "finalize_uploaded"
    if state in {"prepared", "rendering", "rendered", "uploading"}:
        # rendered/uploading may have lost their process-local temp file.  The
        # immutable manifest is rerendered and the same hash-derived storage
        # path is reused; no second object identity can be minted.
        return "render_and_upload_same_path"
    if state == "failed":
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


def _asset_identity_hash(
    section: Mapping[str, Any],
    asset: Mapping[str, Any],
    provenance: Mapping[str, Any],
    *,
    stage: str,
) -> str:
    if stage == "pictures":
        artifact = {
            "image_url": str(asset.get("image_url") or "").strip(),
            "drive_image_url": str(asset.get("drive_image_url") or "").strip(),
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
    provider_rows: Sequence[Mapping[str, Any]],
    *,
    tenant_id: str,
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
    providers = _rows(provider_rows, "provider operations")
    by_key: dict[str, dict[str, Any]] = {}
    for row in providers:
        key = str(row.get("stage_key") or "")
        if not key or key in by_key:
            raise CustomFilmContractError(
                "Custom Film provider operations have a gap or duplicate"
            )
        if (
            str(row.get("tenant_id") or "") != tenant_id
            or str(row.get("video_id") or "") != str(envelope["video_id"])
            or str(row.get("runtime_hash") or "") != str(envelope["runtime_hash"])
            or row.get("state") != "completed"
            or not isinstance(row.get("result"), Mapping)
        ):
            raise CustomFilmContractError(
                "Custom Film provider operation is incomplete or stale"
            )
        by_key[key] = row
    if list(by_key) != expected_keys:
        raise CustomFilmContractError(
            "Custom Film provider operations are missing, duplicated, or out of order"
        )


def build_assembly_manifest(
    *,
    tenant_id: str,
    envelope_value: Any,
    runtime_progress_value: Any,
    provider_rows: Sequence[Mapping[str, Any]],
    scene_rows: Sequence[Mapping[str, Any]],
    asset_rows: Sequence[Mapping[str, Any]],
    provenance_rows: Sequence[Mapping[str, Any]],
    section_supplements: Mapping[str, Mapping[str, Any]] | None = None,
    require_source_hashes: bool = True,
    fps: int = DEFAULT_FPS,
    width: int = 1920,
    height: int = 1080,
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
    _validate_progress(
        envelope, runtime_progress_value, provider_rows, tenant_id=tenant_id
    )
    fps = _exact_int(fps, "assembly fps", 1)
    width = _exact_int(width, "assembly width", 2)
    height = _exact_int(height, "assembly height", 2)
    if width % 2 or height % 2:
        raise CustomFilmContractError("Custom Film output dimensions must be even")

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

        raw_captions = supplement.get("captions") or []
        captions: list[dict[str, Any]] = []
        for caption in raw_captions:
            value = _mapping(caption, "caption")
            start_ms = _exact_int(value.get("start_ms"), "caption start")
            end_ms = _exact_int(value.get("end_ms"), "caption end", 1)
            if end_ms <= start_ms or end_ms > duration_seconds * 1000:
                raise CustomFilmContractError("Custom Film caption timing is invalid")
            captions.append(
                {
                    "text": str(value.get("text") or "").strip(),
                    "start_frame": film_frame + (start_ms * fps // 1000),
                    "end_frame": film_frame + (end_ms * fps // 1000),
                }
            )
        if any(not caption["text"] for caption in captions):
            raise CustomFilmContractError("Custom Film caption text is empty")

        transition_frames = min(max(1, fps // 2), max(1, section_frames // 4))
        voice_urls = list(supplement.get("voice_over_urls") or [])
        voice_hashes = list(supplement.get("voice_over_sha256") or [])
        if section["dialogue_audio"] == "voice_over" and (
            len(voice_urls) != len(scenes_by_section[section_id])
            or (
                require_source_hashes
                and (
                    len(voice_hashes) != len(voice_urls)
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
                    "gain_db": 0,
                },
                "captions": captions,
            }
        )
        film_frame += section_frames

    if film_frame != int(envelope["total_duration_seconds"]) * fps:
        raise CustomFilmContractError("Custom Film total film frames drifted")
    body = {
        "assembly_version": ASSEMBLY_VERSION,
        "tenant_id": tenant_id,
        "video_id": str(envelope["video_id"]),
        "plan_id": str(envelope["plan_id"]),
        "runtime_hash": str(envelope["runtime_hash"]),
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
        "format=duration:stream=codec_type,width,height",
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
    return {
        "duration_seconds": float(data["format"]["duration"]),
        "width": video.get("width"),
        "height": video.get("height"),
        "has_video": bool(video),
        "has_audio": any(row.get("codec_type") == "audio" for row in streams),
        "has_subtitles": any(
            row.get("codec_type") == "subtitle" for row in streams
        ),
    }


def _srt_timestamp(frame: int, fps: int) -> str:
    milliseconds = round(frame * 1000 / fps)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


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
                if len(audio_hashes) != len(audio_paths) or any(
                    hashlib.sha256(path.read_bytes()).hexdigest() != expected
                    for path, expected in zip(audio_paths, audio_hashes)
                ):
                    raise CustomFilmContractError(
                        "Custom Film narration source hash changed"
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
                    f"aresample=48000,apad,atrim=duration={section_seconds:.9f},"
                    "asetpts=N/SR/TB"
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
            await _run(
                [
                    "ffmpeg", "-y", "-i", str(rendered), "-i", str(srt),
                    "-map", "0:v", "-map", "0:a", "-map", "1:0",
                    "-c:v", "copy", "-c:a", "copy", "-c:s", "mov_text",
                    "-metadata:s:s:0", "language=eng", str(captioned),
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
                """SELECT runtime_envelope, runtime_progress, status
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
            output_dimensions = {
                ("16:9", "720p"): (1280, 720),
                ("9:16", "720p"): (720, 1280),
                ("16:9", "480p"): (854, 480),
                ("9:16", "480p"): (480, 854),
            }.get((aspect_ratio, resolution))
            if output_dimensions is None:
                raise CustomFilmContractError(
                    "Custom Film output aspect ratio or resolution is unsupported"
                )
            providers_raw = await conn.fetch(
                """SELECT tenant_id::text, video_id::text, runtime_hash,
                          stage_key, state, result
                   FROM custom_film_provider_operations
                   WHERE tenant_id = $1::uuid AND video_id = $2::uuid
                     AND runtime_hash = $3""",
                tenant_id,
                video_id,
                envelope["runtime_hash"],
            )
            providers_by_key = {
                str(row["stage_key"]): dict(row) for row in providers_raw
            }
            expected_keys = [
                adapter.stage_key for adapter in compile_stage_adapters(envelope)
            ]
            if set(providers_by_key) != set(expected_keys):
                raise CustomFilmContractError(
                    "Custom Film provider operation journal has a gap"
                )
            providers = [providers_by_key[key] for key in expected_keys]
            scene_records = await conn.fetch(
                """SELECT ss.tenant_id::text, ss.plan_id::text,
                          ss.video_id::text, ss.section_id::text,
                          ss.script_id::text, ss.scene_order,
                          s.scene, s.scene_text, s.voice_over_url
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
                caption_text = "\n".join(
                    str(row.get("scene_text") or "").strip()
                    for row in values
                    if str(row.get("scene_text") or "").strip()
                )
                captions = (
                    [
                        {
                            "text": caption_text,
                            "start_ms": 0,
                            "end_ms": int(section["duration_seconds"]) * 1000,
                        }
                    ]
                    if caption_text
                    else []
                )
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
                    "captions": captions,
                }
            asset_records = await conn.fetch(
                """SELECT DISTINCT ON (a.id)
                          a.id::text AS asset_id, a.tenant_id::text,
                          a.video_id::text, p.section_id::text,
                          ss.scene_order, a.image_index, a.image_url,
                          a.drive_image_url, a.video_clip_url,
                          a.generation_method
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
                     AND p.stage IN ('pictures', 'clips')
                   ORDER BY a.id, p.section_id, ss.scene_order, a.image_index""",
                tenant_id,
                video_id,
                envelope["runtime_hash"],
            )
            provenance_records = await conn.fetch(
                """SELECT tenant_id::text, video_id::text, asset_id::text,
                          plan_id::text, section_id::text, runtime_hash, stage,
                          request_hash, section_contract_hash, generation_method,
                          provider_model, status, artifact_url_hash,
                          actual_duration_ms, assigned_duration_ms,
                          timing_transform
                   FROM custom_film_asset_provenance
                   WHERE tenant_id = $1::uuid AND video_id = $2::uuid
                     AND runtime_hash = $3
                     AND stage IN ('pictures', 'clips')
                   ORDER BY section_id, stage, asset_id""",
                tenant_id,
                video_id,
                envelope["runtime_hash"],
            )
    return {
        "envelope": envelope,
        "runtime_progress": task["runtime_progress"],
        "provider_rows": providers,
        "scene_rows": scene_rows,
        "asset_rows": [dict(row) for row in asset_records],
        "provenance_rows": [dict(row) for row in provenance_records],
        "section_supplements": section_supplements,
        "output_width": output_dimensions[0],
        "output_height": output_dimensions[1],
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


async def render_custom_film_video(
    video_id: str,
    tenant_id: str,
    *,
    title: str = "",
    on_progress: ProgressCallback | None = None,
    downloader: Callable[[str, Path], Awaitable[None]] | None = None,
    uploader: Callable[[bytes, str, str], Awaitable[str]] | None = None,
) -> dict[str, Any]:
    """Production render door with durable render/upload reconciliation.

    The storage key is derived from the immutable runtime and manifest.  A
    crash after upload but before journaling therefore retries the same object
    identity instead of creating a second upload.
    """
    import database

    download = downloader or _default_download
    upload = uploader or _default_upload
    inputs = await _load_current_inputs(tenant_id, video_id)
    preliminary = build_assembly_manifest(
        tenant_id=tenant_id,
        envelope_value=inputs["envelope"],
        runtime_progress_value=inputs["runtime_progress"],
        provider_rows=inputs["provider_rows"],
        scene_rows=inputs["scene_rows"],
        asset_rows=inputs["asset_rows"],
        provenance_rows=inputs["provenance_rows"],
        section_supplements=inputs["section_supplements"],
        require_source_hashes=False,
        width=inputs["output_width"],
        height=inputs["output_height"],
    )
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
                source_paths[key] = path
        manifest = build_assembly_manifest(
            tenant_id=tenant_id,
            envelope_value=inputs["envelope"],
            runtime_progress_value=inputs["runtime_progress"],
            provider_rows=inputs["provider_rows"],
            scene_rows=inputs["scene_rows"],
            asset_rows=inputs["asset_rows"],
            provenance_rows=inputs["provenance_rows"],
            section_supplements=inputs["section_supplements"],
            width=inputs["output_width"],
            height=inputs["output_height"],
        )
        manifest_hash = manifest["manifest_hash"]
        runtime_hash = manifest["runtime_hash"]
        safe_title = "".join(
            char if char.isalnum() or char in "-_" else "_"
            for char in (title or "custom-film")
        )[:80]
        storage_path = (
            f"{video_id}/final/{safe_title}-{manifest_hash[:16]}.mp4"
        )
        pool = await database.get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """INSERT INTO custom_film_assemblies
                         (tenant_id, video_id, runtime_hash, manifest_version,
                          manifest_hash, manifest, progress, storage_path)
                       VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6::jsonb,
                               $7::jsonb, $8)
                       ON CONFLICT (tenant_id, video_id, runtime_hash)
                       DO NOTHING""",
                    tenant_id,
                    video_id,
                    runtime_hash,
                    ASSEMBLY_VERSION,
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
                              artifact_probe, storage_path, final_video_url
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
                        **_mapping(journal["artifact_probe"], "artifact probe"),
                        "manifest_hash": manifest_hash,
                        "reused": True,
                    }
                if state in {"prepared", "rendering"}:
                    await conn.execute(
                        """UPDATE custom_film_assemblies
                           SET state = 'rendering',
                               progress = $4::jsonb,
                               render_started_at = COALESCE(render_started_at, now()),
                               updated_at = now()
                           WHERE tenant_id = $1::uuid AND video_id = $2::uuid
                             AND runtime_hash = $3""",
                        tenant_id, video_id, runtime_hash,
                        json.dumps(
                            {
                                "phase": "normalizing",
                                "completed_sections": 0,
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
            completed_sections = 0
            phase = "normalizing"
            if message.startswith("Rendering "):
                phase = "rendering"
                completed_sections = len(manifest["sections"])
            elif message.startswith("Assembling section "):
                phase = "assembling"
                try:
                    completed_sections = int(message.split()[2].split("/")[0])
                except (ValueError, IndexError):
                    completed_sections = 0
            elif message.startswith("Assembling sections "):
                phase = "assembling"
            elif message.startswith("Normalizing section "):
                try:
                    completed_sections = max(
                        0, int(message.split()[2].split("/")[0]) - 1
                    )
                except (ValueError, IndexError):
                    completed_sections = 0
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

        rendered = await render_local_manifest(
            manifest,
            source_paths=source_paths,
            output_path=output,
            on_progress=_durable_progress,
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
            "manifest_hash": manifest_hash,
            "artifact_sha256": rendered["artifact_sha256"],
            "method": "custom_film_exact_assembly_v1",
            **probe,
        }
    finally:
        shutil.rmtree(staging, ignore_errors=True)
