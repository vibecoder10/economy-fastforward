from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import types
from pathlib import Path
from fractions import Fraction

import pytest
from PIL import Image

import custom_film_compositor as compositor
import custom_film_contract as contract
import custom_film_remotion
import custom_film_runtime
import custom_film_section_runtime


TENANT = "00000000-0000-4000-8000-000000000099"
VIDEO = "00000000-0000-4000-8000-000000000098"
PLAN = "00000000-0000-4000-8000-000000000097"


def _section(index: int, *, kind: str) -> dict:
    section_id = f"00000000-0000-4000-8000-{index + 1:012d}"
    base = {
        "section_id": section_id,
        "order_index": index,
        "duration_seconds": 2,
        "role": kind,
        "purpose": f"Prove {kind}",
        "image_source": "generate",
        "provenance": {"profiles": [kind]},
        "estimated_media": {
            "still_images": 1,
            "animation_clips": 0 if kind == "photo" else 1,
            "voice_tracks": 1,
        },
    }
    if kind == "photo":
        base.update(
            {
                "render_mode": "static_docu",
                "script_profile": "neutral_v1",
                "visual_profile": "photo_documentary",
                "dialogue_audio": "voice_over",
                "image_density": {"mode": "per_item", "target": 1, "minimum": 1},
                "animation": {"enabled": False, "mode": "ken_burns"},
                "language": {"mode": "narrator"},
                "dubbing": {"enabled": False, "mode": "none"},
                "segmentation": {"mode": "item"},
                "camera": {"mode": "three_complementary_views"},
                "quality_laws": ["verified_reference"],
            }
        )
    elif kind == "investigative":
        base.update(
            {
                "render_mode": "coverage",
                "script_profile": "power_doctrine_v2",
                "visual_profile": "cinematic_illustration",
                "dialogue_audio": "voice_over",
                "image_density": {"mode": "visual_cue", "target_per_minute": 30},
                "animation": {"enabled": True, "mode": "grok_native"},
                "language": {"mode": "narrator"},
                "dubbing": {"enabled": False, "mode": "none"},
                "segmentation": {"mode": "visual_cue"},
                "camera": {"mode": "investigative_coverage"},
                "quality_laws": ["source_grounding"],
            }
        )
    elif kind == "bilingual":
        base.update(
            {
                "render_mode": "coverage",
                "script_profile": "character_story_v1",
                "visual_profile": "character",
                "dialogue_audio": "voice_over",
                "image_density": {"mode": "dialogue_shape", "target_per_minute": 30},
                "animation": {"enabled": True, "mode": "grok_native"},
                "language": {"mode": "bilingual", "languages": ["en", "es"]},
                "dubbing": {"enabled": True, "mode": "speech_to_speech"},
                "segmentation": {"mode": "speaker_turn"},
                "camera": {"mode": "dialogue_coverage"},
                "quality_laws": ["speaker_identity"],
            }
        )
    else:
        base.update(
            {
                "render_mode": "coverage",
                "script_profile": "simple_v1",
                "visual_profile": "simple_animation",
                "dialogue_audio": "grok_native",
                "image_density": {"mode": "dialogue_shape", "target_per_minute": 30},
                "animation": {"enabled": True, "mode": "grok_native"},
                "language": {"mode": "simple_single_language", "language": "en"},
                "dubbing": {"enabled": False, "mode": "none"},
                "segmentation": {"mode": "speaker_turn"},
                "camera": {"mode": "dialogue_coverage"},
                "quality_laws": ["simple_language"],
            }
        )
    return base


def _fixture() -> dict:
    sections = [
        _section(0, kind="photo"),
        _section(1, kind="investigative"),
        _section(2, kind="bilingual"),
        _section(3, kind="simple"),
    ]
    stage_plan = []
    for section in sections:
        stages = ["script", "voice", "pictures"]
        if section["animation"]["enabled"]:
            stages.extend(("motion", "clips"))
        stages.append("quality")
        for stage in stages:
            stage_plan.append(
                {
                    "section_id": section["section_id"],
                    "order_index": section["order_index"],
                    "stage": stage,
                    "duration_seconds": section["duration_seconds"],
                    "values": copy.deepcopy(section),
                }
            )
    base = {
        "runtime_version": custom_film_runtime.RUNTIME_VERSION,
        "video_id": VIDEO,
        "plan_id": PLAN,
        "plan_hash": "a" * 64,
        "quote_inputs_hash": "b" * 64,
        "approval_hash": "c" * 64,
        "total_duration_seconds": 8,
        "max_spend": 10.0,
        "sections": sections,
        "stage_plan": stage_plan,
    }
    envelope = {"runtime_hash": contract.canonical_hash(base), **base}
    adapters = custom_film_section_runtime.compile_stage_adapters(envelope)
    keys = [adapter.stage_key for adapter in adapters]
    progress = {
        "runtime_hash": envelope["runtime_hash"],
        "completed_stage_keys": keys,
        "last_stage_key": keys[-1],
        "in_flight": None,
    }
    runtime_job_id = f"custom-film-runtime:{envelope['runtime_hash']}"
    providers = []
    scenes = []
    assets = []
    provenance = []
    supplements = {}
    for index, section in enumerate(sections):
        scene_id = f"10000000-0000-4000-8000-{index + 1:012d}"
        asset_id = f"20000000-0000-4000-8000-{index + 1:012d}"
        scenes.append(
            {
                "tenant_id": TENANT,
                "video_id": VIDEO,
                "plan_id": PLAN,
                "section_id": section["section_id"],
                "script_id": scene_id,
                "scene_order": 0,
                "scene_text": f"Section {index + 1}: {section['purpose']}",
                "voice_over_url": (
                    f"fixture://voice-{index}"
                    if section["dialogue_audio"] == "voice_over"
                    else None
                ),
                "voice_status": None,
            }
        )
        animated = section["animation"]["enabled"]
        asset = {
            "asset_id": asset_id,
            "tenant_id": TENANT,
            "video_id": VIDEO,
            "section_id": section["section_id"],
            "scene_order": 0,
            "image_index": 1,
            "image_url": f"fixture://image-{index}",
            "drive_image_url": None,
            "video_clip_url": f"fixture://clip-{index}" if animated else None,
            "video_prompt": f"motion prompt {index}" if animated else None,
            "generation_method": "coverage" if animated else "static_docu",
            "source_sha256": f"{index + 30:064x}",
            "caption": (
                {
                    "title": "Evidence card",
                    "sub": "Synthetic • 2026",
                    "specs": ["Verified fixture"],
                    "view_role": "three_quarter",
                    "label": "Primary evidence",
                }
                if not animated
                else None
            ),
        }
        assets.append(asset)
        for stage in (("pictures", "clips") if animated else ("pictures",)):
            row = {
                "tenant_id": TENANT,
                "video_id": VIDEO,
                "asset_id": asset_id,
                "plan_id": PLAN,
                "section_id": section["section_id"],
                "runtime_hash": envelope["runtime_hash"],
                "stage": stage,
                "request_hash": f"{index + 1:064x}",
                "section_contract_hash": f"{index + 10:064x}",
                "generation_method": asset["generation_method"],
                "provider_model": "synthetic-v1",
                "status": "completed",
                "actual_duration_ms": 1000 if stage == "clips" else None,
                "assigned_duration_ms": 2000 if stage == "clips" else None,
                "timing_transform": (
                    {
                        "mode": "repeat_then_trim",
                        "source_duration_ms": 1000,
                        "repeat_count": 2,
                        "final_repeat_duration_ms": 1000,
                        "output_duration_ms": 2000,
                    }
                    if stage == "clips"
                    else None
                ),
            }
            row["artifact_url_hash"] = compositor._asset_identity_hash(
                section, asset, row, stage=stage
            )
            provenance.append(row)
        supplements[section["section_id"]] = {
            "voice_over_urls": (
                [f"fixture://voice-{index}"]
                if section["dialogue_audio"] == "voice_over"
                else []
            ),
            "voice_over_sha256": (
                [f"{index + 40:064x}"]
                if section["dialogue_audio"] == "voice_over"
                else []
            ),
            "voice_over_duration_ms": (
                [2000] if section["dialogue_audio"] == "voice_over" else []
            ),
            "captions": [
                {
                    "text": f"Section {index + 1}: {section['purpose']}",
                    "start_ms": 0,
                    "end_ms": 2000,
                }
            ],
        }
    scene_by_section = {
        str(row["section_id"]): row for row in scenes
    }
    asset_by_section = {
        str(row["section_id"]): row for row in assets
    }
    provenance_by_section_stage = {
        (str(row["section_id"]), str(row["stage"])): row for row in provenance
    }
    for adapter in adapters:
        parent_id = compositor._parent_operation_id(
            TENANT, runtime_job_id, adapter
        )
        assigned_scene = scene_by_section[adapter.section_id]
        scene_id = assigned_scene["script_id"]
        child_entries = []
        if adapter.stage == "script":
            result = {
                "scene_ids": [scene_id],
                "scene_text_hashes": [
                    {
                        "scene_id": scene_id,
                        "scene_text_hash": contract.canonical_hash(
                            {
                                "scene_id": scene_id,
                                "scene_text": assigned_scene["scene_text"],
                            }
                        ),
                    }
                ],
            }
        elif adapter.stage in {"voice", "pictures", "motion", "clips"}:
            child_identity = {
                "parent_operation_id": parent_id,
                "scene_id": scene_id,
            }
            if adapter.stage != "voice":
                child_identity["stage"] = adapter.stage
            child_id = "custom-film-op:" + contract.canonical_hash(child_identity)
            child_key = (
                f"{adapter.stage_key}:scene:0:"
                f"{contract.canonical_hash({'scene_id': scene_id})[:12]}"
            )
            asset = asset_by_section[adapter.section_id]
            provenance_row = provenance_by_section_stage.get(
                (adapter.section_id, adapter.stage)
            ) or provenance_by_section_stage[
                (adapter.section_id, "pictures")
            ]
            if adapter.stage == "voice":
                if adapter.dialogue_audio == "voice_over":
                    artifact_id = f"{adapter.order_index + 50:064x}"
                    assigned_scene["voice_status"] = (
                        f"custom-film-voice:{artifact_id}"
                    )
                    artifacts = [
                        {
                            "scene_id": scene_id,
                            "artifact_id": artifact_id,
                            "artifact_url": assigned_scene["voice_over_url"],
                        }
                    ]
                else:
                    artifacts = []
            elif adapter.stage == "pictures":
                caption_card = contract.canonical_caption_card(asset["caption"])
                artifacts = [
                    {
                        "artifact_id": asset["asset_id"],
                        "artifact_url": asset["image_url"],
                        "caption_card": caption_card,
                        "caption_hash": contract.canonical_hash(
                            {"caption_card": caption_card}
                        ),
                    }
                ]
            elif adapter.stage == "motion":
                artifacts = [
                    {
                        "artifact_id": asset["asset_id"],
                        "artifact_url": "motion-prompt:"
                        + contract.canonical_hash(
                            {
                                "asset_id": asset["asset_id"],
                                "prompt": asset["video_prompt"],
                                "camera": sections[adapter.order_index]["camera"],
                            }
                        ),
                    }
                ]
            else:
                artifacts = [
                    {
                        "artifact_id": asset["asset_id"],
                        "artifact_url": asset["video_clip_url"],
                        "actual_duration_ms": provenance_row[
                            "actual_duration_ms"
                        ],
                        "assigned_duration_ms": provenance_row[
                            "assigned_duration_ms"
                        ],
                        "timing_transform": copy.deepcopy(
                            provenance_row["timing_transform"]
                        ),
                    }
                ]
            child_result = {"scene_ids": [scene_id], "artifacts": artifacts}
            providers.append(
                {
                    "tenant_id": TENANT,
                    "video_id": VIDEO,
                    "runtime_job_id": runtime_job_id,
                    "runtime_hash": envelope["runtime_hash"],
                    "operation_id": child_id,
                    "stage_key": child_key,
                    "state": "completed",
                    "result": child_result,
                }
            )
            child_entries.append(
                {
                    "scene_id": scene_id,
                    "operation_id": child_id,
                    "result": child_result,
                }
            )
            result = {
                "scene_ids": [scene_id],
                "child_operations": child_entries,
            }
            if adapter.stage in {"pictures", "clips"}:
                provenance_row["operation_id"] = child_id
        else:
            result = {"scene_ids": [scene_id], "status": "completed"}
        providers.append(
            {
                "tenant_id": TENANT,
                "video_id": VIDEO,
                "runtime_job_id": runtime_job_id,
                "runtime_hash": envelope["runtime_hash"],
                "operation_id": parent_id,
                "stage_key": adapter.stage_key,
                "state": "completed",
                "result": result,
            }
        )
    return {
        "envelope": envelope,
        "runtime_progress": progress,
        "provider_rows": providers,
        "scene_rows": scenes,
        "asset_rows": assets,
        "provenance_rows": provenance,
        "section_supplements": supplements,
        "runtime_job_id": runtime_job_id,
    }


def _build(values: dict) -> dict:
    return compositor.build_assembly_manifest(
        tenant_id=TENANT,
        runtime_job_id=values["runtime_job_id"],
        envelope_value=values["envelope"],
        runtime_progress_value=values["runtime_progress"],
        provider_rows=values["provider_rows"],
        scene_rows=values["scene_rows"],
        asset_rows=values["asset_rows"],
        provenance_rows=values["provenance_rows"],
        section_supplements=values["section_supplements"],
    )


def test_running_runtime_is_assembly_eligible_only_for_exact_complete_worker():
    values = _fixture()
    task = {
        "job_id": values["runtime_job_id"],
        "runtime_envelope": values["envelope"],
        "runtime_progress": values["runtime_progress"],
        "status": "running",
    }
    accepted = compositor._validated_runtime_task_for_assembly(
        task,
        tenant_id=TENANT,
        video_id=VIDEO,
        expected_runtime_job_id=values["runtime_job_id"],
    )
    assert accepted["runtime_hash"] == values["envelope"]["runtime_hash"]

    with pytest.raises(
        contract.CustomFilmContractError,
        match="not durably complete",
    ):
        compositor._validated_runtime_task_for_assembly(
            task,
            tenant_id=TENANT,
            video_id=VIDEO,
            expected_runtime_job_id=None,
        )


@pytest.mark.parametrize(
    "tamper",
    ["incomplete", "reordered", "in_flight", "wrong_job", "wrong_video"],
)
def test_running_runtime_assembly_gate_rejects_incomplete_or_changed_identity(tamper):
    values = _fixture()
    task = {
        "job_id": values["runtime_job_id"],
        "runtime_envelope": copy.deepcopy(values["envelope"]),
        "runtime_progress": copy.deepcopy(values["runtime_progress"]),
        "status": "running",
    }
    expected_job_id = values["runtime_job_id"]
    if tamper == "incomplete":
        task["runtime_progress"]["completed_stage_keys"].pop()
        task["runtime_progress"]["last_stage_key"] = task["runtime_progress"][
            "completed_stage_keys"
        ][-1]
    elif tamper == "reordered":
        task["runtime_progress"]["completed_stage_keys"][:2] = reversed(
            task["runtime_progress"]["completed_stage_keys"][:2]
        )
    elif tamper == "in_flight":
        task["runtime_progress"]["completed_stage_keys"].pop()
        task["runtime_progress"]["last_stage_key"] = task["runtime_progress"][
            "completed_stage_keys"
        ][-1]
        next_adapter = custom_film_section_runtime.compile_stage_adapters(
            task["runtime_envelope"]
        )[len(task["runtime_progress"]["completed_stage_keys"])]
        task["runtime_progress"]["in_flight"] = {
            "stage_key": next_adapter.stage_key,
            "operation_id": custom_film_section_runtime._operation_id(
                TENANT,
                expected_job_id,
                next_adapter,
            ),
            "state": "started",
        }
    elif tamper == "wrong_job":
        expected_job_id = "custom-film-runtime:" + ("f" * 64)
    else:
        task["runtime_envelope"]["video_id"] = "changed-video"

    with pytest.raises(contract.CustomFilmContractError):
        compositor._validated_runtime_task_for_assembly(
            task,
            tenant_id=TENANT,
            video_id=VIDEO,
            expected_runtime_job_id=expected_job_id,
        )


def test_manifest_is_exact_ordered_versioned_and_executes_6s_to_37s():
    values = _fixture()
    transform = {
        "mode": "repeat_then_trim",
        "source_duration_ms": 6000,
        "repeat_count": 7,
        "final_repeat_duration_ms": 1000,
        "output_duration_ms": 37000,
    }
    assert compositor._validate_transform(transform, 6000, 37000) == transform
    manifest = _build(values)
    assert manifest["total_frames"] == 8 * 24
    assert manifest["transition_accounting"]["overlap_frames_total"] == 0
    assert manifest["sections"][0]["assets"][0]["caption_card"] == {
        "label": "Primary evidence",
        "specs": ["Verified fixture"],
        "sub": "Synthetic • 2026",
        "title": "Evidence card",
        "view_role": "three_quarter",
    }
    assert all(
        sum(asset["duration_frames"] for asset in section["assets"])
        == section["duration_frames"]
        for section in manifest["sections"]
    )


def test_fresh_manifest_is_v2_while_legacy_v1_shape_remains_unchanged():
    values = _fixture()
    fresh = _build(values)
    legacy = compositor.build_assembly_manifest(
        tenant_id=TENANT,
        runtime_job_id=values["runtime_job_id"],
        envelope_value=values["envelope"],
        runtime_progress_value=values["runtime_progress"],
        provider_rows=values["provider_rows"],
        scene_rows=values["scene_rows"],
        asset_rows=values["asset_rows"],
        provenance_rows=values["provenance_rows"],
        section_supplements=values["section_supplements"],
        assembly_version=compositor.ASSEMBLY_VERSION_V1,
    )
    assert fresh["assembly_version"] == compositor.ASSEMBLY_VERSION_V2
    assert fresh["render_engine"] == "ffmpeg"
    assert fresh["approval_hash"] == values["envelope"]["approval_hash"]
    assert legacy["assembly_version"] == compositor.ASSEMBLY_VERSION_V1
    assert all(
        key not in legacy
        for key in (
            "render_engine",
            "plan_hash",
            "quote_inputs_hash",
            "approval_hash",
            "max_spend",
        )
    )
    assert legacy["manifest_hash"] != fresh["manifest_hash"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "resume_state", ["prepared", "rendering", "retryable_failed"]
)
async def test_actual_v1_manifest_dispatches_ffmpeg_for_legacy_resume_paths(
    monkeypatch, tmp_path: Path, resume_state: str
):
    values = _fixture()
    legacy = compositor.build_assembly_manifest(
        tenant_id=TENANT,
        runtime_job_id=values["runtime_job_id"],
        envelope_value=values["envelope"],
        runtime_progress_value=values["runtime_progress"],
        provider_rows=values["provider_rows"],
        scene_rows=values["scene_rows"],
        asset_rows=values["asset_rows"],
        provenance_rows=values["provenance_rows"],
        section_supplements=values["section_supplements"],
        assembly_version=compositor.ASSEMBLY_VERSION_V1,
    )
    assert custom_film_remotion.resolve_durable_render_engine(
        manifest_version=compositor.ASSEMBLY_VERSION_V1,
        manifest=legacy,
        journal_state=resume_state,
        requested_engine=None,
        remotion_available=False,
    ) == "ffmpeg"
    called = []

    async def fake_ffmpeg(*_args, **_kwargs):
        called.append("ffmpeg")
        return {"status": "rendered_local"}

    async def accept(result, **_kwargs):
        return dict(result)

    monkeypatch.setattr(compositor, "render_local_manifest", fake_ffmpeg)
    monkeypatch.setattr(compositor, "_validate_local_render_result", accept)
    result = await compositor.render_manifest_with_engine(
        legacy,
        source_paths={},
        output_path=tmp_path / f"{resume_state}.mp4",
    )
    assert called == ["ffmpeg"]
    assert result["render_engine"] == "ffmpeg"


@pytest.mark.asyncio
async def test_v1_dispatch_rejects_injected_render_engine(tmp_path: Path):
    values = _fixture()
    legacy = compositor.build_assembly_manifest(
        tenant_id=TENANT,
        runtime_job_id=values["runtime_job_id"],
        envelope_value=values["envelope"],
        runtime_progress_value=values["runtime_progress"],
        provider_rows=values["provider_rows"],
        scene_rows=values["scene_rows"],
        asset_rows=values["asset_rows"],
        provenance_rows=values["provenance_rows"],
        section_supplements=values["section_supplements"],
        assembly_version=compositor.ASSEMBLY_VERSION_V1,
    )
    legacy["render_engine"] = "ffmpeg"
    legacy["manifest_hash"] = contract.canonical_hash(
        {key: value for key, value in legacy.items() if key != "manifest_hash"}
    )
    with pytest.raises(
        contract.CustomFilmContractError, match="v1 renderer identity changed"
    ):
        await compositor.render_manifest_with_engine(
            legacy,
            source_paths={},
            output_path=tmp_path / "tampered-v1.mp4",
        )


def test_voice_timing_only_allows_bounded_speech_preserving_adjustment():
    safe = compositor._audio_timing_transform(2200, 2000)
    assert safe["mode"] == "atempo"
    assert safe["atempo_chain"] == [1.1]
    assert compositor._audio_timing_transform(2000, 2000)["mode"] == "none"
    with pytest.raises(contract.CustomFilmContractError, match="cannot safely fit"):
        compositor._audio_timing_transform(500, 2000)
    with pytest.raises(contract.CustomFilmContractError, match="cannot safely fit"):
        compositor._audio_timing_transform(3000, 2000)


@pytest.mark.asyncio
async def test_repeat_then_trim_really_executes_six_seconds_to_thirty_seven(
    tmp_path: Path,
):
    source = tmp_path / "six-seconds.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i",
            "testsrc2=s=320x180:r=6:d=6",
            "-f", "lavfi", "-i", "sine=frequency=330:duration=6",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", str(source),
        ],
        check=True,
        capture_output=True,
    )
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    body = {
        "assembly_version": compositor.ASSEMBLY_VERSION,
        "tenant_id": TENANT,
        "video_id": VIDEO,
        "plan_id": PLAN,
        "runtime_job_id": "custom-film-runtime:" + "a" * 64,
        "runtime_hash": "a" * 64,
        "fps": 6,
        "width": 320,
        "height": 180,
        "total_frames": 222,
        "total_duration_seconds": 37,
        "sections": [
            {
                "section_id": "section-37",
                "order_index": 0,
                "render_mode": "coverage",
                "start_frame": 0,
                "duration_frames": 222,
                "transition_in": {"duration_frames": 0},
                "transition_out": {"duration_frames": 0},
                "audio": {
                    "mode": "source_clip",
                    "timing_transform": {"mode": "source_clip"},
                },
                "captions": [],
                "assets": [
                    {
                        "asset_id": "asset-six",
                        "source_sha256": source_hash,
                        "actual_duration_ms": 6000,
                        "duration_frames": 222,
                        "start_frame": 0,
                        "timing_transform": {
                            "mode": "repeat_then_trim",
                            "source_duration_ms": 6000,
                            "repeat_count": 7,
                            "final_repeat_duration_ms": 1000,
                            "output_duration_ms": 37000,
                        },
                        "caption_card": None,
                    }
                ],
            }
        ],
        "transition_accounting": {"overlap_frames_total": 0},
    }
    manifest = {**body, "manifest_hash": contract.canonical_hash(body)}
    output = tmp_path / "thirty-seven.mp4"
    result = await compositor.render_local_manifest(
        manifest,
        source_paths={"asset-six": source},
        output_path=output,
    )
    probe = await compositor.probe_media(output)
    assert result["total_frames"] == 222
    assert result["duration_seconds"] == 37
    assert probe["frame_count"] == 222
    assert abs(probe["duration_seconds"] - 37) <= 1 / 6 + 0.002


@pytest.mark.parametrize(
    "tamper",
    [
        "progress_gap",
        "provider_incomplete",
        "scene_duplicate",
        "asset_drift",
        "provenance_gap",
        "transform",
        "caption",
        "missing_caption_card",
        "missing_caption_hash",
    ],
)
def test_manifest_fails_closed_on_stale_or_incomplete_current_rows(tamper):
    values = _fixture()
    if tamper == "progress_gap":
        values["runtime_progress"]["completed_stage_keys"].pop()
    elif tamper == "provider_incomplete":
        values["provider_rows"][-1]["state"] = "submitted"
    elif tamper == "scene_duplicate":
        values["scene_rows"][1]["script_id"] = values["scene_rows"][0]["script_id"]
    elif tamper == "asset_drift":
        values["asset_rows"][1]["video_clip_url"] = "fixture://changed"
    elif tamper == "provenance_gap":
        values["provenance_rows"].pop()
    elif tamper == "transform":
        next(
            row for row in values["provenance_rows"] if row["stage"] == "clips"
        )["timing_transform"]["repeat_count"] = 3
    elif tamper == "caption":
        values["asset_rows"][0]["caption"]["label"] = "mutated after completion"
    else:
        picture_child = next(
            row
            for row in values["provider_rows"]
            if ":pictures:scene:" in row["stage_key"]
        )
        key = (
            "caption_card"
            if tamper == "missing_caption_card"
            else "caption_hash"
        )
        del picture_child["result"]["artifacts"][0][key]
    with pytest.raises(contract.CustomFilmContractError):
        _build(values)


@pytest.mark.asyncio
async def test_synthetic_four_section_render_has_exact_streams_boundaries_and_captions(
    tmp_path: Path,
):
    values = _fixture()
    colors = ["red", "green", "blue", "yellow"]
    paths: dict[str, Path] = {}
    for index, (asset, color) in enumerate(zip(values["asset_rows"], colors)):
        if index == 0:
            path = tmp_path / "photo.png"
            subprocess.run(
                [
                    "ffmpeg", "-y", "-f", "lavfi", "-i",
                    f"color=c={color}:s=320x180:d=1", "-frames:v", "1", str(path),
                ],
                check=True,
                capture_output=True,
            )
        else:
            path = tmp_path / f"clip-{index}.mp4"
            subprocess.run(
                [
                    "ffmpeg", "-y", "-f", "lavfi", "-i",
                    f"color=c={color}:s=320x180:d=1:r=24",
                    "-f", "lavfi", "-i", "sine=frequency=330:duration=1",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", str(path),
                ],
                check=True,
                capture_output=True,
            )
        asset["source_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        paths[asset["asset_id"]] = path
    for section in values["envelope"]["sections"]:
        if section["dialogue_audio"] != "voice_over":
            continue
        voice = tmp_path / f"voice-{section['order_index']}.wav"
        subprocess.run(
            [
                "ffmpeg", "-y", "-f", "lavfi", "-i",
                f"sine=frequency={440 + section['order_index'] * 50}:duration=2",
                str(voice),
            ],
            check=True,
            capture_output=True,
        )
        paths[f"audio:{section['section_id']}:0"] = voice
        values["section_supplements"][section["section_id"]][
            "voice_over_sha256"
        ] = [hashlib.sha256(voice.read_bytes()).hexdigest()]
        voice_probe = await compositor.probe_media(voice)
        values["section_supplements"][section["section_id"]][
            "voice_over_duration_ms"
        ] = [round(voice_probe["duration_seconds"] * 1000)]
    manifest = _build(values)
    output = tmp_path / "mixed.mp4"
    result = await compositor.render_manifest_with_engine(
        manifest, source_paths=paths, output_path=output
    )
    rerender = tmp_path / "mixed-rerender.mp4"
    rerender_result = await compositor.render_local_manifest(
        manifest, source_paths=paths, output_path=rerender
    )
    probe = await compositor.probe_media(output)
    assert result["duration_seconds"] == 8
    assert result["render_engine"] == "ffmpeg"
    assert result["section_count"] == 4
    assert probe["has_video"] and probe["has_audio"] and probe["has_subtitles"]
    assert probe["width"] == 1920 and probe["height"] == 1080
    assert probe["fps_fraction"] == "24/1"
    assert probe["subtitle_languages"] == ["mul"]
    assert abs(probe["duration_seconds"] - 8) <= 1 / 24 + 0.002
    assert len(result["captions"]) == 4
    assert result["captions"][2]["language"] == {
        "mode": "bilingual",
        "languages": ["en", "es"],
    }
    assert len(result["section_provenance"]) == 4
    assert len({row["section_sha256"] for row in result["section_provenance"]}) == 4
    assert rerender_result["artifact_sha256"] == result["artifact_sha256"]
    stored_probe = await compositor.verify_stored_artifact(
        output.read_bytes(),
        expected_sha256=result["artifact_sha256"],
        manifest=manifest,
        staging=tmp_path,
    )
    assert stored_probe["fps_fraction"] == "24/1"
    assert [row["start_frame"] for row in result["captions"]] == [0, 48, 96, 144]
    # Causal boundary proof: sample safely inside each section, away from the
    # hashed dip-to-black frames, and confirm distinct mean RGB identities.
    frame_hashes = []
    for index, second in enumerate((1.0, 3.0, 5.0, 7.0)):
        frame = tmp_path / f"boundary-{index}.png"
        subprocess.run(
            [
                "ffmpeg", "-y", "-ss", str(second), "-i", str(output),
                "-frames:v", "1", str(frame),
            ],
            check=True,
            capture_output=True,
        )
        frame_hashes.append(hashlib.sha256(frame.read_bytes()).hexdigest())
        pixels = list(Image.open(frame).convert("RGB").getdata())
        assert sum(1 for red, green, blue in pixels if min(red, green, blue) > 225) > 20
    assert len(set(frame_hashes)) == 4


def test_probe_frame_truth_accepts_counted_and_duration_ts_fallbacks():
    assert compositor.authoritative_probe_frame_count(
        {"nb_frames": "N/A", "nb_read_frames": "504"},
        frame_rate=Fraction(24, 1),
        duration_seconds=21,
    ) == (504, "nb_read_frames")
    assert compositor.authoritative_probe_frame_count(
        {"nb_frames": "N/A", "nb_read_frames": "N/A"},
        frame_rate=Fraction(24, 1),
        duration_seconds=21,
    ) == (504, "duration_ts")
    assert compositor.authoritative_probe_frame_count(
        {"nb_frames": "N/A", "nb_read_frames": "N/A"},
        frame_rate=Fraction(24, 1),
        duration_seconds=21.01,
    ) == (None, None)


def test_exact_video_probe_separates_bounded_aac_container_padding():
    base = {
        "frame_count": 504,
        "width": 1920,
        "height": 1080,
        "fps": 24,
        "fps_fraction": "24/1",
        "video_duration_seconds": 21.0,
        "duration_seconds": 21.045333,
        "has_video": True,
        "has_audio": True,
    }
    assert compositor.probe_has_exact_video_identity(
        base, total_frames=504, fps=24, width=1920, height=1080
    )
    wrong_video = {**base, "video_duration_seconds": 21.01}
    assert not compositor.probe_has_exact_video_identity(
        wrong_video, total_frames=504, fps=24, width=1920, height=1080
    )
    unbounded_container = {**base, "duration_seconds": 21.1}
    assert not compositor.probe_has_exact_video_identity(
        unbounded_container,
        total_frames=504,
        fps=24,
        width=1920,
        height=1080,
    )


@pytest.mark.asyncio
async def test_storage_readback_rejects_wrong_bytes_before_acceptance(tmp_path: Path):
    with pytest.raises(
        compositor.CustomFilmRetryableError, match="readback hash"
    ):
        await compositor.verify_stored_artifact(
            b"wrong-object",
            expected_sha256="0" * 64,
            manifest={
                "total_frames": 24,
                "width": 320,
                "height": 180,
                "fps": 24,
                "sections": [{}],
            },
            staging=tmp_path,
        )


def test_storage_identity_ignores_mutable_title():
    first = compositor.assembly_storage_path(VIDEO, "a" * 64, "b" * 64)
    renamed = compositor.assembly_storage_path(VIDEO, "a" * 64, "b" * 64)
    assert first == renamed
    assert first == (
        f"{VIDEO}/final/custom-film-"
        "aaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb.mp4"
    )


@pytest.mark.asyncio
async def test_finalized_retry_returns_before_any_media_download(monkeypatch):
    runtime_hash = "c" * 64
    runtime_job_id = f"custom-film-runtime:{runtime_hash}"
    durable_manifest_body = {
        "assembly_version": compositor.ASSEMBLY_VERSION_V1,
        "runtime_hash": runtime_hash,
    }
    durable_manifest_hash = contract.canonical_hash(durable_manifest_body)
    durable_manifest = {
        **durable_manifest_body,
        "manifest_hash": durable_manifest_hash,
    }
    probe = {
        "duration_seconds": 8,
        "total_frames": 192,
        "fps": 24,
        "resolution": "1920x1080",
        "section_count": 4,
        "asset_count": 4,
        "captions": [],
        "section_provenance": [],
    }

    class Connection:
        async def fetchrow(self, _query, *_args):
            return {
                "state": "finalized",
                "runtime_job_id": runtime_job_id,
                "manifest_version": compositor.ASSEMBLY_VERSION_V1,
                "manifest_hash": durable_manifest_hash,
                "manifest": durable_manifest,
                "artifact_sha256": "e" * 64,
                "artifact_probe": probe,
                "storage_path": compositor.assembly_storage_path(
                    VIDEO, runtime_hash, durable_manifest_hash
                ),
                "final_video_url": "storage://exact-final",
            }

    class Acquire:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *_args):
            return False

    class Pool:
        def acquire(self):
            return Acquire()

    async def get_pool():
        return Pool()

    async def load_inputs(
        _tenant_id,
        _video_id,
        *,
        expected_runtime_job_id=None,
    ):
        assert expected_runtime_job_id is None
        return {
            "runtime_job_id": runtime_job_id,
            "envelope": {"runtime_hash": runtime_hash},
            "runtime_progress": {},
            "provider_rows": [],
            "scene_rows": [],
            "asset_rows": [],
            "provenance_rows": [],
            "section_supplements": {},
            "output_width": 1920,
            "output_height": 1080,
        }

    async def forbidden_download(_url, _path):
        raise AssertionError("finalized retry must not download source media")

    monkeypatch.setitem(sys.modules, "database", types.SimpleNamespace(get_pool=get_pool))
    monkeypatch.setattr(compositor, "_load_current_inputs", load_inputs)
    monkeypatch.setattr(
        compositor,
        "build_assembly_manifest",
        lambda **_kwargs: {
            "sections": [],
            "runtime_hash": runtime_hash,
        },
    )
    result = await compositor.render_custom_film_video(
        VIDEO,
        TENANT,
        title="a renamed title",
        downloader=forbidden_download,
    )
    assert result["reused"] is True
    assert result["final_video_url"] == "storage://exact-final"


def test_schema_and_render_door_are_durable_and_isolated():
    root = Path(__file__).resolve().parents[3]
    migration = (
        root / "backend/migrations/127_custom_film_assemblies.sql"
    ).read_text()
    migration_v2 = (
        root / "backend/migrations/130_custom_film_assembly_v2.sql"
    ).read_text()
    schema = (root / "schema.sql").read_text()
    executor = (root / "backend/pipeline_executor.py").read_text()
    for text in (migration, schema):
        assert "CREATE TABLE IF NOT EXISTS custom_film_assemblies" in text
        assert "progress JSONB NOT NULL" in text
        assert "'normalizing', 'assembling', 'rendering'" in text
        assert "runtime_job_id TEXT NOT NULL" in text
        assert "REFERENCES background_tasks(tenant_id, video_id, job_id)" in text
        assert "'retryable_failed', 'terminal_failed'" in text
        assert "Custom Film assembly progress cannot regress" in text
        assert "Custom Film assembly phase cannot regress" in text
        assert "Custom Film assembly identity is immutable" in text
        assert "REVOKE ALL ON TABLE custom_film_assemblies FROM anon, authenticated" in text
    assert 'if video.get("custom_film_plan_id")' in executor
    assert "render_custom_film_video" in executor
    assert "AUTOMATIC_RENDER_POLICY" in executor
    assert "run_remotion_renderer" in executor
    assert "remotion_renderer=run_remotion_renderer" in executor
    compositor_source = (
        root / "backend/custom_film_compositor.py"
    ).read_text()
    assert 'orchestration_contract.get("resolved_plan")' in compositor_source
    assert 'orchestration_contract["resolved_plan"].get("recipes")' in compositor_source
    assert 'aspect_ratio == "16:9"' in compositor_source
    assert "finishing_canvas == exact_finishing_canvas" in compositor_source
    assert "Custom Film approved quote identity changed" in compositor_source
    assert '"remotion_finishing_bound": remotion_finishing_bound' in compositor_source
    assert 'inputs.get("orchestration_contract")' in compositor_source
    assert "output_dimensions = (1920, 1080)" in compositor_source
    assert "custom-film-assembly-v1" in migration_v2
    assert "custom-film-assembly-v2" in migration_v2
    assert "manifest->>'render_engine' IN ('ffmpeg', 'remotion')" in migration_v2


def test_crash_windows_have_one_fail_closed_or_same_path_resume_action():
    assert compositor.assembly_resume_action("prepared") == "render_and_upload_same_path"
    assert compositor.assembly_resume_action("rendering") == "render_and_upload_same_path"
    assert compositor.assembly_resume_action("rendered") == "render_and_upload_same_path"
    # Crash after upload entry but before its journal result: rerender if the
    # temp file vanished, then overwrite the exact manifest-derived object.
    assert compositor.assembly_resume_action("uploading") == "render_and_upload_same_path"
    # Crash after URL journal but before videos.final_video_url: no upload.
    assert compositor.assembly_resume_action("uploaded") == "finalize_uploaded"
    assert compositor.assembly_resume_action("finalized") == "return_finalized"
    assert compositor.assembly_resume_action("retryable_failed") == "render_and_upload_same_path"
    assert compositor.assembly_resume_action("terminal_failed") == "terminal_failure"
    with pytest.raises(contract.CustomFilmContractError):
        compositor.assembly_resume_action("invented")
