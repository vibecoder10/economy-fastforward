from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

import custom_film_compositor as compositor
import custom_film_contract as contract
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
    providers = [
        {
            "tenant_id": TENANT,
            "video_id": VIDEO,
            "runtime_hash": envelope["runtime_hash"],
            "stage_key": key,
            "state": "completed",
            "result": {"status": "completed", "stage_key": key},
        }
        for key in keys
    ]
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
            "generation_method": "coverage" if animated else "static_docu",
            "source_sha256": f"{index + 30:064x}",
        }
        assets.append(asset)
        stage = "clips" if animated else "pictures"
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
            "actual_duration_ms": 1000 if animated else None,
            "assigned_duration_ms": 2000 if animated else None,
            "timing_transform": (
                {
                    "mode": "repeat_then_trim",
                    "source_duration_ms": 1000,
                    "repeat_count": 2,
                    "final_repeat_duration_ms": 1000,
                    "output_duration_ms": 2000,
                }
                if animated
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
            "captions": [
                {
                    "text": f"Section {index + 1}: {section['purpose']}",
                    "start_ms": 0,
                    "end_ms": 2000,
                }
            ],
        }
    return {
        "envelope": envelope,
        "runtime_progress": progress,
        "provider_rows": providers,
        "scene_rows": scenes,
        "asset_rows": assets,
        "provenance_rows": provenance,
        "section_supplements": supplements,
    }


def _build(values: dict) -> dict:
    return compositor.build_assembly_manifest(
        tenant_id=TENANT,
        envelope_value=values["envelope"],
        runtime_progress_value=values["runtime_progress"],
        provider_rows=values["provider_rows"],
        scene_rows=values["scene_rows"],
        asset_rows=values["asset_rows"],
        provenance_rows=values["provenance_rows"],
        section_supplements=values["section_supplements"],
    )


def test_manifest_is_exact_ordered_versioned_and_executes_6s_to_37s():
    values = _fixture()
    values["envelope"]["sections"][1]["duration_seconds"] = 37
    for work in values["envelope"]["stage_plan"]:
        if work["section_id"] == values["envelope"]["sections"][1]["section_id"]:
            work["duration_seconds"] = 37
            work["values"]["duration_seconds"] = 37
    values["envelope"]["total_duration_seconds"] = 43
    base = copy.deepcopy(values["envelope"])
    base.pop("runtime_hash")
    values["envelope"]["runtime_hash"] = contract.canonical_hash(base)
    values["runtime_progress"]["runtime_hash"] = values["envelope"]["runtime_hash"]
    for provider in values["provider_rows"]:
        provider["runtime_hash"] = values["envelope"]["runtime_hash"]
    for provenance in values["provenance_rows"]:
        provenance["runtime_hash"] = values["envelope"]["runtime_hash"]
    row = values["provenance_rows"][1]
    row["actual_duration_ms"] = 6000
    row["assigned_duration_ms"] = 37000
    row["timing_transform"] = {
        "mode": "repeat_then_trim",
        "source_duration_ms": 6000,
        "repeat_count": 7,
        "final_repeat_duration_ms": 1000,
        "output_duration_ms": 37000,
    }
    row["artifact_url_hash"] = compositor._asset_identity_hash(
        values["envelope"]["sections"][1],
        values["asset_rows"][1],
        row,
        stage="clips",
    )
    values["section_supplements"][values["envelope"]["sections"][1]["section_id"]][
        "captions"
    ][0]["end_ms"] = 37000
    manifest = _build(values)
    assert manifest["total_frames"] == 43 * 24
    assert manifest["sections"][1]["assets"][0]["actual_duration_ms"] == 6000
    assert manifest["sections"][1]["assets"][0]["assigned_duration_ms"] == 37000
    assert manifest["sections"][1]["assets"][0]["timing_transform"]["repeat_count"] == 7
    assert manifest["transition_accounting"]["overlap_frames_total"] == 0
    assert all(
        sum(asset["duration_frames"] for asset in section["assets"])
        == section["duration_frames"]
        for section in manifest["sections"]
    )


@pytest.mark.parametrize(
    "tamper",
    [
        "progress_gap",
        "provider_incomplete",
        "scene_duplicate",
        "asset_drift",
        "provenance_gap",
        "transform",
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
    else:
        values["provenance_rows"][1]["timing_transform"]["repeat_count"] = 3
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
    manifest = _build(values)
    output = tmp_path / "mixed.mp4"
    result = await compositor.render_local_manifest(
        manifest, source_paths=paths, output_path=output
    )
    rerender = tmp_path / "mixed-rerender.mp4"
    rerender_result = await compositor.render_local_manifest(
        manifest, source_paths=paths, output_path=rerender
    )
    probe = await compositor.probe_media(output)
    assert result["duration_seconds"] == 8
    assert result["section_count"] == 4
    assert probe["has_video"] and probe["has_audio"]
    assert probe["width"] == 1920 and probe["height"] == 1080
    assert abs(probe["duration_seconds"] - 8) <= 1 / 24 + 0.002
    assert len(result["captions"]) == 4
    assert len(result["section_provenance"]) == 4
    assert len({row["section_sha256"] for row in result["section_provenance"]}) == 4
    assert rerender_result["artifact_sha256"] == result["artifact_sha256"]
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
    assert len(set(frame_hashes)) == 4


def test_schema_and_render_door_are_durable_and_isolated():
    root = Path(__file__).resolve().parents[3]
    migration = (
        root / "backend/migrations/127_custom_film_assemblies.sql"
    ).read_text()
    schema = (root / "schema.sql").read_text()
    executor = (root / "backend/pipeline_executor.py").read_text()
    for text in (migration, schema):
        assert "CREATE TABLE IF NOT EXISTS custom_film_assemblies" in text
        assert "progress JSONB NOT NULL" in text
        assert "'normalizing', 'assembling', 'rendering'" in text
        assert "Custom Film assembly identity is immutable" in text
        assert "REVOKE ALL ON TABLE custom_film_assemblies FROM anon, authenticated" in text
    assert 'if video.get("custom_film_plan_id")' in executor
    assert "render_custom_film_video" in executor


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
    assert compositor.assembly_resume_action("failed") == "terminal_failure"
    with pytest.raises(contract.CustomFilmContractError):
        compositor.assembly_resume_action("invented")
