from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import shutil
import sys
import types
import wave
from array import array
from pathlib import Path

import pytest
from PIL import Image

import custom_film_compositor as compositor
import custom_film_contract as contract
import custom_film_orchestration as orchestration
import custom_film_remotion as remotion


def _reference_orchestration_contract() -> dict:
    plan = orchestration.load_reference_semantic_plan()
    recipes = [
        orchestration.resolve_layered_recipe(cue) for cue in plan["cues"]
    ]
    semantic_input = {
        "capability_catalog_version": orchestration.CAPABILITY_CATALOG_VERSION,
        "compatibility_version": "test",
        "total_duration_seconds": 300,
        "sections": [],
    }
    resolved = {"fps": 24, "total_frames": 7200, "recipes": recipes}
    body = {
        "contract_version": orchestration.ORCHESTRATION_CONTRACT_VERSION,
        "decision_rules_version": orchestration.DECISION_RULES_VERSION,
        "semantic_input": semantic_input,
        "semantic_input_hash": contract.canonical_hash(semantic_input),
        "approved_beat_plan": None,
        "approved_beat_plan_hash": None,
        "resolved_plan": resolved,
        "resolved_plan_hash": contract.canonical_hash(resolved),
        "reference_compatible": True,
        "story_identity": orchestration.REFERENCE_STORY_IDENTITY,
        "signals_hash": contract.canonical_hash(
            [cue["signals"] for cue in plan["cues"]]
        ),
        "recipe_hash": contract.canonical_hash(recipes),
        "reference_plan_version": plan["version"],
    }
    return {**body, "contract_hash": contract.canonical_hash(body)}


def _generic_orchestration_contract(*, frames: int = 24) -> dict:
    recipe = orchestration.resolve_layered_recipe(
        {
            "id": "section-1:beat:0",
            "section_index": 0,
            "from": 0,
            "to": frames - 1,
            "narrative_function": "Plate the finished meal",
            "signals": {
                "media_kind": "video",
                "dialogue": False,
                "captions": False,
                "intents": ["culinary", "demonstration"],
                "energy": 2,
                "handoff": "pulse",
            },
        }
    )
    recipes = [recipe]
    semantic_input = {
        "capability_catalog_version": orchestration.CAPABILITY_CATALOG_VERSION,
        "compatibility_version": "test-generic",
        "total_duration_seconds": frames // 24,
        "sections": [],
    }
    resolved = {"fps": 24, "total_frames": frames, "recipes": recipes}
    body = {
        "contract_version": orchestration.ORCHESTRATION_CONTRACT_VERSION,
        "decision_rules_version": orchestration.DECISION_RULES_VERSION,
        "semantic_input": semantic_input,
        "semantic_input_hash": contract.canonical_hash(semantic_input),
        "approved_beat_plan": resolved,
        "approved_beat_plan_hash": contract.canonical_hash(resolved),
        "resolved_plan": resolved,
        "resolved_plan_hash": contract.canonical_hash(resolved),
        "reference_compatible": False,
        "story_identity": contract.canonical_hash(semantic_input),
        "signals_hash": contract.canonical_hash([recipe["signals"]]),
        "recipe_hash": contract.canonical_hash(recipes),
        "reference_plan_version": None,
    }
    return {**body, "contract_hash": contract.canonical_hash(body)}


def _manifest(
    *,
    engine: str = "remotion",
    version: str = compositor.ASSEMBLY_VERSION_V2,
) -> dict:
    caption_card = {
        "title": "Prueba • proof",
        "sub": "Mara",
        "specs": ["Señal verificada"],
    }
    section = {
        "section_id": "section-1",
        "order_index": 0,
        "role": "opening",
        "render_mode": "static_docu",
        "visual_profile": "photo_documentary",
        "dialogue_audio": "voice_over",
        "start_frame": 0,
        "duration_frames": 24,
        "transition_in": {
            "type": "none",
            "duration_frames": 0,
            "overlap_frames": 0,
            "accounting": "inside_section",
            "audio": "fade_in",
        },
        "transition_out": {
            "type": "none",
            "duration_frames": 0,
            "overlap_frames": 0,
            "accounting": "inside_section",
            "audio": "fade_out",
        },
        "scene_ids": ["scene-1"],
        "assets": [
            {
                "asset_id": "asset-1",
                "source_url": "fixture://asset-1",
                "source_sha256": "1" * 64,
                "actual_duration_ms": None,
                "assigned_duration_ms": None,
                "timing_transform": {
                    "mode": "static_hold",
                    "source_duration_ms": None,
                    "output_duration_ms": 1000,
                },
                "camera": {"mode": "three_complementary_views"},
                "provenance_hash": "2" * 64,
                "caption_card": caption_card,
                "caption_hash": contract.canonical_hash(
                    {"caption_card": caption_card}
                ),
                "start_frame": 0,
                "duration_frames": 24,
            }
        ],
        "audio": {
            "mode": "voice_over",
            "source_urls": ["fixture://voice-1"],
            "source_sha256": ["4" * 64],
            "source_duration_ms": [1000],
            "timing_transform": {
                "mode": "none",
                "source_duration_ms": 1000,
                "output_duration_ms": 1000,
                "atempo_chain": [],
                "caption_scale": 1.0,
            },
            "gain_db": 0,
        },
        "captions": [
            {
                "scene_id": "scene-1",
                "text": "Mara: Si puedes oírme.",
                "language": {
                    "mode": "bilingual",
                    "languages": ["es", "en"],
                },
                "section_start_ms": 0,
                "section_end_ms": 1000,
                "start_frame": 0,
                "end_frame": 24,
            }
        ],
    }
    body = {
        "assembly_version": version,
        "tenant_id": "tenant-1",
        "video_id": "video-1",
        "plan_id": "plan-1",
        "plan_hash": "5" * 64,
        "quote_inputs_hash": "6" * 64,
        "approval_hash": "7" * 64,
        "max_spend": 15.0,
        "runtime_hash": "8" * 64,
        "runtime_job_id": f"custom-film-runtime:{'8' * 64}",
        "render_engine": engine,
        "fps": 24,
        "width": 1920,
        "height": 1080,
        "total_duration_seconds": 1,
        "total_frames": 24,
        "transition_accounting": {
            "type": "dip_to_black_non_overlap",
            "duration_source": "min(half_second, quarter_section)",
            "overlap_frames_total": 0,
            "duration_lives_inside_assigned_sections": True,
        },
        "sections": [section],
    }
    if version == compositor.ASSEMBLY_VERSION_V3:
        body.update(
            {
                "renderer_contract_version": (
                    remotion.REMOTION_RENDERER_CONTRACT_VERSION
                ),
                "renderer_bundle_hash": remotion.renderer_bundle_hash(),
                "orchestration_contract": _reference_orchestration_contract(),
            }
        )
    return {**body, "manifest_hash": contract.canonical_hash(body)}


def _rehash(manifest: dict) -> dict:
    manifest = copy.deepcopy(manifest)
    manifest.pop("manifest_hash", None)
    return {**manifest, "manifest_hash": contract.canonical_hash(manifest)}


def test_remotion_props_are_strict_hashed_provider_opaque_and_unicode_safe():
    props = remotion.build_remotion_props(_manifest())
    assert props["schema_version"] == remotion.REMOTION_PROPS_VERSION
    assert props["identity"]["approval_hash"] == "7" * 64
    assert props["identity"]["max_spend"] == 15.0
    assert props["video"] == {
        "fps": 24,
        "width": 1920,
        "height": 1080,
        "total_duration_seconds": 1,
        "total_frames": 24,
    }
    assert props["sections"][0]["captions"][0]["text"] == (
        "Mara: Si puedes oírme."
    )
    serialized = contract.canonical_json(props)
    assert "source_url" not in serialized
    assert "provider" not in serialized
    assert "model" not in serialized
    body = dict(props)
    props_hash = body.pop("props_hash")
    assert props_hash == remotion.remotion_props_hash(body)


def _two_cue_manifest() -> dict:
    manifest = _manifest()
    manifest["total_duration_seconds"] = 54
    manifest["total_frames"] = 1296
    section = manifest["sections"][0]
    section["duration_frames"] = 1296
    section["assets"][0]["duration_frames"] = 1296
    section["assets"][0]["timing_transform"]["output_duration_ms"] = 54000
    section["audio"]["source_duration_ms"] = [10000]
    texts = ["First approved line.", "Second approved line."]
    cues = [
        {
            "segment_index": 0,
            "text_hash": contract.canonical_hash(
                {"segment_index": 0, "text": texts[0]}
            ),
            "source_start_ms": 0,
            "source_end_ms": 5000,
            "target_start_ms": 0,
            "target_end_ms": 5000,
        },
        {
            "segment_index": 1,
            "text_hash": contract.canonical_hash(
                {"segment_index": 1, "text": texts[1]}
            ),
            "source_start_ms": 5000,
            "source_end_ms": 10000,
            "target_start_ms": 27000,
            "target_end_ms": 32000,
        },
    ]
    section["audio"]["timing_transform"] = {
        "mode": "cue_schedule",
        "source_duration_ms": 10000,
        "output_duration_ms": 54000,
        "atempo_chain": [],
        "caption_scale": 1.0,
        "cues": cues,
    }
    language = section["captions"][0]["language"]
    section["captions"] = [
        {
            "scene_id": "scene-1",
            "text": texts[0],
            "language": language,
            "section_start_ms": 0,
            "section_end_ms": 5000,
            "start_frame": 0,
            "end_frame": 120,
        },
        {
            "scene_id": "scene-1",
            "text": texts[1],
            "language": language,
            "section_start_ms": 27000,
            "section_end_ms": 32000,
            "start_frame": 648,
            "end_frame": 768,
        },
    ]
    return _rehash(manifest)


def test_remotion_props_preserve_two_cue_schedule_and_caption_gap():
    props = remotion.build_remotion_props(_two_cue_manifest())

    transform = props["sections"][0]["audio"]["timing_transform"]
    assert transform["mode"] == "cue_schedule"
    assert [cue["target_start_ms"] for cue in transform["cues"]] == [0, 27000]
    assert [
        caption["start_frame"] for caption in props["sections"][0]["captions"]
    ] == [0, 648]


def test_remotion_props_reject_cue_text_or_frame_drift():
    manifest = _two_cue_manifest()
    manifest["sections"][0]["captions"][1]["text"] = "Changed."
    with pytest.raises(contract.CustomFilmContractError):
        remotion.build_remotion_props(_rehash(manifest))

    transform = copy.deepcopy(
        _two_cue_manifest()["sections"][0]["audio"]["timing_transform"]
    )
    transform["cues"][1]["source_start_ms"] = 5001
    with pytest.raises(
        contract.CustomFilmContractError, match="audio cue timing"
    ):
        remotion._validate_props_audio_transform(
            transform, output_duration_ms=54000
        )


def test_assembly_v3_binds_exact_renderer_and_rejects_bundle_drift(monkeypatch):
    manifest = _manifest(version=compositor.ASSEMBLY_VERSION_V3)
    props = remotion.build_remotion_props(manifest)
    assert props["identity"]["renderer_contract_version"] == (
        remotion.REMOTION_RENDERER_CONTRACT_VERSION
    )
    assert props["identity"]["renderer_bundle_hash"] == (
        remotion.renderer_bundle_hash()
    )
    monkeypatch.setattr(remotion, "renderer_bundle_hash", lambda: "f" * 64)
    with pytest.raises(
        contract.CustomFilmContractError, match="renderer identity changed"
    ):
        remotion.build_remotion_props(manifest)
    with pytest.raises(
        contract.CustomFilmContractError, match="renderer identity changed"
    ):
        remotion.resolve_durable_render_engine(
            manifest_version=compositor.ASSEMBLY_VERSION_V3,
            manifest=manifest,
            journal_state="prepared",
            requested_engine="remotion",
            remotion_available=True,
        )


def test_renderer_bundle_hash_binds_python_adapter(monkeypatch):
    original = remotion.renderer_bundle_hash()
    monkeypatch.setattr(remotion, "_renderer_adapter_hash", lambda: "f" * 64)

    assert remotion.renderer_bundle_hash() != original


def test_renderer_bundle_hash_binds_orchestration_adapter(monkeypatch):
    original = remotion.renderer_bundle_hash()
    monkeypatch.setattr(
        remotion, "_orchestration_adapter_hash", lambda: "f" * 64
    )

    assert remotion.renderer_bundle_hash() != original


def _flagship_runtime_envelope() -> dict:
    roles = ("opening", "evidence", "case_study", "explanation")
    durations = (45, 105, 90, 60)
    return {
        "runtime_version": "custom-film-runtime-v1",
        "runtime_hash": "8" * 64,
        "video_id": "video-1",
        "plan_id": "plan-1",
        "plan_hash": "5" * 64,
        "quote_inputs_hash": "6" * 64,
        "approval_hash": "7" * 64,
        "total_duration_seconds": 300,
        "max_spend": 15.0,
        "sections": [
            {
                "section_id": f"section-{index + 1}",
                "order_index": index,
                "role": role,
                "duration_seconds": duration,
            }
            for index, (role, duration) in enumerate(zip(roles, durations))
        ],
        "stage_plan": [],
    }


def test_shared_semantic_plan_resolves_layered_recipes_at_exact_frames():
    plan = remotion.load_showcase_motion_plan()
    assert plan["version"] == remotion.SHOWCASE_MOTION_PLAN_VERSION
    assert plan["cues"][0]["from"] == 0
    assert plan["cues"][-1]["to"] == 7199
    recipes = [
        orchestration.resolve_layered_recipe(cue) for cue in plan["cues"]
    ]
    primitives = {
        layer["primitive"]
        for recipe in recipes
        for layer in recipe["motionLayers"]
    }
    assert {
        "SignalPulse",
        "OutageMap",
        "EvidenceBoard",
        "IncidentTimeline",
        "RadioWaveform",
        "BilingualCaptions",
        "NetworkExplainer",
        "StoryEngineReveal",
        "MotionAudioSystem",
    }.issubset(primitives)
    approved = _reference_orchestration_contract()
    serialized_round_trip = json.loads(contract.canonical_json(approved))
    assert serialized_round_trip == approved
    durable_body = copy.deepcopy(serialized_round_trip)
    durable_hash = durable_body.pop("contract_hash")
    assert durable_hash == contract.canonical_hash(durable_body)
    assert serialized_round_trip["resolved_plan_hash"] == contract.canonical_hash(
        serialized_round_trip["resolved_plan"]
    )
    assert remotion.is_storyengine_showcase_runtime(
        _flagship_runtime_envelope()
    )
    assert remotion.automatic_render_engine_for_runtime(
        _flagship_runtime_envelope(),
        width=1920,
        height=1080,
        orchestration_contract=_reference_orchestration_contract(),
    ) == "remotion"
    assert remotion.automatic_render_engine_for_runtime(
        _flagship_runtime_envelope(),
        width=1920,
        height=1080,
    ) == "ffmpeg"


@pytest.mark.parametrize(
    ("mutation", "width", "height"),
    [
        ({"total_duration_seconds": 301}, 1920, 1080),
        ({"sections": []}, 1920, 1080),
        ({}, 1280, 720),
    ],
)
def test_automatic_renderer_keeps_non_showcase_films_on_ffmpeg(
    mutation, width, height
):
    envelope = _flagship_runtime_envelope()
    envelope.update(mutation)
    if mutation:
        assert not remotion.is_storyengine_showcase_runtime(envelope)
    assert remotion.automatic_render_engine_for_runtime(
        envelope,
        width=width,
        height=height,
        orchestration_contract=_reference_orchestration_contract(),
    ) == "ffmpeg"


def test_non_flagship_approved_beats_select_general_remotion_execution():
    envelope = {
        **_flagship_runtime_envelope(),
        "total_duration_seconds": 7,
        "sections": [
            {
                **_flagship_runtime_envelope()["sections"][0],
                "role": "demonstration",
                "duration_seconds": 7,
            }
        ],
    }
    approved = _generic_orchestration_contract(frames=168)
    assert approved["reference_compatible"] is False
    assert approved["resolved_plan"]["recipes"][0]["signals"]["intents"] == [
        "culinary",
        "demonstration",
    ]
    assert {
        layer["primitive"]
        for layer in approved["resolved_plan"]["recipes"][0]["motionLayers"]
    } == {"SignalPulse", "MediaKinetics", "MotionAudioSystem"}
    assert remotion.automatic_render_engine_for_runtime(
        envelope,
        width=1920,
        height=1080,
        orchestration_contract=approved,
    ) == "remotion"
    without_beats = copy.deepcopy(approved)
    without_beats["resolved_plan"] = None
    assert remotion.automatic_render_engine_for_runtime(
        envelope,
        width=1920,
        height=1080,
        orchestration_contract=without_beats,
    ) == "ffmpeg"
    manifest = _manifest(version=compositor.ASSEMBLY_VERSION_V3)
    manifest["orchestration_contract"] = _generic_orchestration_contract()
    manifest = _rehash(manifest)
    props = remotion.build_remotion_props(manifest)
    assert props["video"]["total_duration_seconds"] == 1
    assert props["orchestration"]["reference_compatible"] is False
    assert props["orchestration"]["resolved_plan"]["recipes"][0]["id"] == (
        "section-1:beat:0"
    )


def test_python_generated_props_match_the_tracked_typescript_parity_fixture():
    root = Path(__file__).resolve().parents[4]
    tracked = json.loads(
        (
            root
            / "remotion-video/test-fixtures/custom-film-remotion-props-v1.json"
        ).read_text(encoding="utf-8")
    )
    assert tracked == remotion.build_remotion_props(_manifest())
    unicode_parity = json.loads(
        (
            root
            / "remotion-video/test-fixtures/canonical-unicode-parity.json"
        ).read_text(encoding="utf-8")
    )
    assert remotion.canonical_remotion_json(
        unicode_parity["value"]
    ) == unicode_parity["canonical_json"]
    assert remotion.remotion_props_hash(
        unicode_parity["value"]
    ) == unicode_parity["sha256"]


@pytest.mark.parametrize(
    "tamper",
    [
        "unknown_top",
        "section_order",
        "section_gap",
        "source_hash",
        "caption_card",
        "caption_timing",
        "audio_hash",
        "overlap",
        "duration",
        "engine",
    ],
)
def test_remotion_props_reject_rehashed_semantic_tampering(tamper: str):
    manifest = _manifest()
    if tamper == "unknown_top":
        manifest["provider_model"] = "hidden-v1"
    elif tamper == "section_order":
        manifest["sections"][0]["order_index"] = 1
    elif tamper == "section_gap":
        manifest["sections"][0]["start_frame"] = 1
    elif tamper == "source_hash":
        manifest["sections"][0]["assets"][0]["source_sha256"] = "bad"
    elif tamper == "caption_card":
        manifest["sections"][0]["assets"][0]["caption_card"]["title"] = "changed"
    elif tamper == "caption_timing":
        manifest["sections"][0]["captions"][0]["end_frame"] = 23
    elif tamper == "audio_hash":
        manifest["sections"][0]["audio"]["source_sha256"][0] = "bad"
    elif tamper == "overlap":
        manifest["sections"][0]["transition_out"]["overlap_frames"] = 1
    elif tamper == "duration":
        manifest["total_frames"] = 25
    else:
        manifest["render_engine"] = "auto"
    with pytest.raises(contract.CustomFilmContractError):
        remotion.build_remotion_props(_rehash(manifest))


def test_engine_selection_is_explicit_and_only_falls_back_pre_journal():
    assert remotion.resolve_render_engine(
        None, remotion_available=False
    ) == "ffmpeg"
    assert remotion.resolve_render_engine(
        "remotion", remotion_available=True
    ) == "remotion"
    assert remotion.resolve_render_engine(
        "remotion",
        remotion_available=False,
        pre_journal_fallback="ffmpeg",
    ) == "ffmpeg"
    with pytest.raises(
        contract.CustomFilmContractError, match="no renderer"
    ):
        remotion.resolve_render_engine(
            "remotion", remotion_available=False
        )
    with pytest.raises(contract.CustomFilmContractError):
        remotion.resolve_render_engine(
            "remotion",
            remotion_available=False,
            pre_journal_fallback="automatic",
        )


@pytest.mark.parametrize(
    "state", ["prepared", "rendering", "retryable_failed", "finalized"]
)
def test_legacy_v1_journals_resume_with_original_ffmpeg_semantics(state: str):
    assert remotion.resolve_durable_render_engine(
        manifest_version=compositor.ASSEMBLY_VERSION_V1,
        manifest={"assembly_version": compositor.ASSEMBLY_VERSION_V1},
        journal_state=state,
        requested_engine=None,
        remotion_available=False,
    ) == "ffmpeg"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("requested_engine", "renderer_available", "expected_error"),
    [
        (None, False, "requires the Remotion renderer"),
        ("ffmpeg", True, "does not match its durable journal"),
        (None, True, "selected durable remotion"),
    ],
)
async def test_durable_v2_remotion_controls_retry_before_source_io(
    monkeypatch,
    requested_engine,
    renderer_available,
    expected_error,
):
    runtime_hash = "8" * 64
    durable_body = {
        "assembly_version": compositor.ASSEMBLY_VERSION_V2,
        "runtime_hash": runtime_hash,
        "render_engine": "remotion",
    }
    durable_hash = contract.canonical_hash(durable_body)
    durable = {**durable_body, "manifest_hash": durable_hash}
    touched_source_io = False

    class Connection:
        async def fetchrow(self, _query, *_args):
            return {
                "state": "prepared",
                "runtime_job_id": f"custom-film-runtime:{runtime_hash}",
                "manifest_version": compositor.ASSEMBLY_VERSION_V2,
                "manifest_hash": durable_hash,
                "manifest": durable,
                "artifact_sha256": None,
                "artifact_probe": None,
                "storage_path": "fixture/path.mp4",
                "final_video_url": None,
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
            "runtime_job_id": f"custom-film-runtime:{runtime_hash}",
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
        nonlocal touched_source_io
        touched_source_io = True
        raise AssertionError("retry selection must happen before source I/O")

    class SelectionReached(RuntimeError):
        pass

    def selected_build(**kwargs):
        assert kwargs["render_engine"] == "remotion"
        assert kwargs["assembly_version"] == compositor.ASSEMBLY_VERSION_V2
        raise SelectionReached("selected durable remotion")

    async def renderer(**_kwargs):
        raise AssertionError("rendering is outside this selection test")

    monkeypatch.setitem(
        sys.modules, "database", types.SimpleNamespace(get_pool=get_pool)
    )
    monkeypatch.setattr(compositor, "_load_current_inputs", load_inputs)
    monkeypatch.setattr(compositor, "build_assembly_manifest", selected_build)
    with pytest.raises(Exception, match=expected_error):
        await compositor.render_custom_film_video(
            "video-1",
            "tenant-1",
            downloader=forbidden_download,
            render_engine=requested_engine,
            remotion_renderer=renderer if renderer_available else None,
        )
    assert touched_source_io is False


@pytest.mark.asyncio
async def test_dispatch_defaults_to_ffmpeg_and_remotion_is_opt_in(
    monkeypatch, tmp_path: Path
):
    calls: list[str] = []
    expected = {"status": "rendered_local"}

    async def fake_ffmpeg(*_args, **_kwargs):
        calls.append("ffmpeg")
        return expected

    async def fake_remotion(**kwargs):
        calls.append("remotion")
        assert kwargs["remotion_props"]["identity"]["render_engine"] == "remotion"
        return expected

    async def accept(result, **_kwargs):
        return dict(result)

    monkeypatch.setattr(compositor, "render_local_manifest", fake_ffmpeg)
    monkeypatch.setattr(compositor, "_validate_local_render_result", accept)
    ffmpeg_result = await compositor.render_manifest_with_engine(
        _manifest(engine="ffmpeg"),
        source_paths={},
        output_path=tmp_path / "ffmpeg.mp4",
        remotion_renderer=fake_remotion,
    )
    remotion_result = await compositor.render_manifest_with_engine(
        _manifest(engine="remotion"),
        source_paths={},
        output_path=tmp_path / "remotion.mp4",
        remotion_renderer=fake_remotion,
    )
    assert calls == ["ffmpeg", "remotion"]
    assert ffmpeg_result["render_engine"] == "ffmpeg"
    assert remotion_result["render_engine"] == "remotion"


@pytest.mark.asyncio
async def test_selected_remotion_failure_never_silently_calls_ffmpeg(
    monkeypatch, tmp_path: Path
):
    async def forbidden_ffmpeg(*_args, **_kwargs):
        raise AssertionError("selected Remotion must never switch renderers")

    async def failed_remotion(**_kwargs):
        raise RuntimeError("synthetic Remotion failure")

    monkeypatch.setattr(compositor, "render_local_manifest", forbidden_ffmpeg)
    with pytest.raises(RuntimeError, match="synthetic Remotion failure"):
        await compositor.render_manifest_with_engine(
            _manifest(engine="remotion"),
            source_paths={},
            output_path=tmp_path / "failed.mp4",
            remotion_renderer=failed_remotion,
        )


def test_1080p_loader_canvas_and_exact_fps_comparison():
    assert compositor.custom_film_output_dimensions(
        "16:9", "1080p"
    ) == (1920, 1080)
    assert compositor._probe_has_exact_fps(
        {"fps_fraction": "24/1"}, 24
    )
    assert not compositor._probe_has_exact_fps(
        {"fps_fraction": "24000/1001"}, 24
    )
    with pytest.raises(contract.CustomFilmContractError):
        compositor.custom_film_output_dimensions("9:16", "1080p")


def _v3_props_for_sources(asset: Path, audio: Path) -> dict:
    manifest = _manifest(version=compositor.ASSEMBLY_VERSION_V3)
    manifest["orchestration_contract"] = _generic_orchestration_contract(
        frames=7200
    )
    manifest["total_duration_seconds"] = 300
    manifest["total_frames"] = 7200
    section = manifest["sections"][0]
    section["duration_frames"] = 7200
    section["assets"][0]["duration_frames"] = 7200
    section["assets"][0]["timing_transform"]["output_duration_ms"] = 300_000
    section["audio"]["source_duration_ms"] = [300_000]
    section["audio"]["timing_transform"] = {
        "mode": "none",
        "source_duration_ms": 300_000,
        "output_duration_ms": 300_000,
        "atempo_chain": [],
        "caption_scale": 1.0,
    }
    section["captions"][0]["section_end_ms"] = 300_000
    section["captions"][0]["end_frame"] = 7200
    manifest["sections"][0]["assets"][0]["source_sha256"] = hashlib.sha256(
        asset.read_bytes()
    ).hexdigest()
    manifest["sections"][0]["audio"]["source_sha256"] = [
        hashlib.sha256(audio.read_bytes()).hexdigest()
    ]
    return remotion.build_remotion_props(_rehash(manifest))


def _source_clip_props(video: Path, *, duration_seconds: int = 6) -> dict:
    manifest = _manifest()
    frames = duration_seconds * 24
    duration_ms = duration_seconds * 1000
    manifest["total_duration_seconds"] = duration_seconds
    manifest["total_frames"] = frames
    section = manifest["sections"][0]
    section["dialogue_audio"] = "grok_native"
    section["render_mode"] = "coverage"
    section["duration_frames"] = frames
    asset = section["assets"][0]
    asset["source_sha256"] = hashlib.sha256(video.read_bytes()).hexdigest()
    asset["actual_duration_ms"] = duration_ms
    asset["assigned_duration_ms"] = duration_ms
    asset["duration_frames"] = frames
    asset["timing_transform"] = {
        "mode": "none",
        "source_duration_ms": duration_ms,
        "output_duration_ms": duration_ms,
    }
    section["audio"] = {
        "mode": "source_clip",
        "source_urls": [],
        "source_sha256": [],
        "source_duration_ms": [],
        "timing_transform": {
            "mode": "source_clip",
            "source_duration_ms": duration_ms,
            "output_duration_ms": duration_ms,
            "atempo_chain": [],
            "caption_scale": 1.0,
        },
        "gain_db": -3.0,
    }
    section["captions"][0]["section_end_ms"] = duration_ms
    section["captions"][0]["end_frame"] = frames
    return remotion.build_remotion_props(_rehash(manifest))


async def _generate_native_source(
    path: Path,
    *,
    video_frames: int,
    audio_seconds: float | None,
    log_path: Path,
) -> None:
    command = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        (
            "color=c=0x0cb4a0:s=64x36:r=24:"
            f"d={video_frames / 24:.9f}"
        ),
    ]
    if audio_seconds is not None:
        command.extend(
            [
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=440:sample_rate=48000:duration={audio_seconds}",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
            ]
        )
    else:
        command.extend(["-map", "0:v:0", "-an"])
    command.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            "-threads",
            "1",
            str(path),
        ]
    )
    await remotion._run_local_command(
        command,
        cwd=path.parent,
        timeout_seconds=60,
        log_path=log_path,
    )


@pytest.mark.parametrize(
    "tamper",
    [
        "asset_unknown",
        "asset_timing",
        "audio_source",
        "caption_timing",
        "camera_provider",
    ],
)
def test_renderer_rejects_rehashed_nested_props_before_subprocess(
    tmp_path: Path, tamper: str
):
    asset = tmp_path / "asset.bin"
    audio = tmp_path / "audio.bin"
    asset.write_bytes(b"approved-image")
    audio.write_bytes(b"approved-audio")
    props = _v3_props_for_sources(asset, audio)
    if tamper == "asset_unknown":
        props["sections"][0]["assets"][0]["provider_model"] = "hidden"
    elif tamper == "asset_timing":
        props["sections"][0]["assets"][0]["timing_transform"][
            "output_duration_ms"
        ] -= 1
    elif tamper == "audio_source":
        props["sections"][0]["audio"]["sources"][0][
            "source_duration_ms"
        ] -= 1
    elif tamper == "caption_timing":
        props["sections"][0]["captions"][0]["end_frame"] -= 1
    else:
        props["sections"][0]["assets"][0]["camera"][
            "provider_model"
        ] = "hidden-v1"
    body = copy.deepcopy(props)
    del body["props_hash"]
    props["props_hash"] = remotion.remotion_props_hash(body)
    with pytest.raises(contract.CustomFilmContractError):
        remotion._validate_renderer_props(props)


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", ["missing", "extra", "hash"])
async def test_source_staging_fails_closed_for_key_or_hash_drift(
    monkeypatch, tmp_path: Path, tamper: str
):
    asset = tmp_path / "asset.bin"
    audio = tmp_path / "audio.bin"
    asset.write_bytes(b"approved-image")
    audio.write_bytes(b"approved-audio")
    props = _v3_props_for_sources(asset, audio)
    paths: dict[str, Path] = {
        "asset-1": asset,
        "audio:section-1:0": audio,
    }
    if tamper == "missing":
        del paths["asset-1"]
    elif tamper == "extra":
        paths["unknown"] = asset
    else:
        asset.write_bytes(b"changed")

    async def should_not_run(*_args, **_kwargs):
        raise AssertionError("invalid source identity must stop before ffmpeg")

    monkeypatch.setattr(remotion, "_run_local_command", should_not_run)
    with pytest.raises(contract.CustomFilmContractError):
        await remotion._stage_renderer_sources(
            props,
            paths,
            staging=tmp_path / "staging",
            log_path=tmp_path / "staging.log",
        )


@pytest.mark.asyncio
async def test_source_staging_matches_typescript_path_contract_and_rehashes(
    monkeypatch, tmp_path: Path
):
    asset = tmp_path / "asset.bin"
    audio = tmp_path / "audio.bin"
    asset.write_bytes(b"approved-image")
    audio.write_bytes(b"approved-audio")
    props = _v3_props_for_sources(asset, audio)

    async def fake_command(command, **_kwargs):
        destination = Path(command[-1])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(
            b"normalized-" + Path(command[command.index("-i") + 1]).read_bytes()
        )

    async def fake_probe(path):
        payload = Path(path).read_bytes()
        is_audio = b"audio" in payload
        return {
            "has_video": not is_audio,
            "has_audio": is_audio,
            "duration_seconds": 300.0,
            "video_duration_seconds": None if is_audio else 300.0,
            "audio_duration_seconds": 300.0 if is_audio else None,
        }

    monkeypatch.setattr(remotion, "_run_local_command", fake_command)
    monkeypatch.setattr(remotion, "_probe_renderer_media", fake_probe)
    staging = tmp_path / "staging"
    rows = await remotion._stage_renderer_sources(
        props,
        {"asset-1": asset, "audio:section-1:0": audio},
        staging=staging,
        log_path=tmp_path / "staging.log",
    )
    assert {
        row["source_key"] for row in rows
    } == {"asset-1", "audio:section-1:0"}
    for key, kind in (
        ("asset-1", "image"),
        ("audio:section-1:0", "audio"),
    ):
        expected = staging / "public" / (
            remotion.staged_local_path_for_source_key(key, kind)
        )
        assert expected.is_file()
        assert expected.name.startswith(hashlib.sha256(key.encode()).hexdigest())


@pytest.mark.asyncio
@pytest.mark.parametrize(("suffix", "format_name"), [(".png", "PNG"), (".jpg", "JPEG")])
async def test_real_still_image_staging_accepts_missing_duration_and_emits_png(
    tmp_path: Path, suffix: str, format_name: str
):
    image_path = tmp_path / f"still{suffix}"
    Image.new("RGB", (32, 18), (12, 180, 160)).save(
        image_path, format=format_name
    )
    audio_path = tmp_path / "narration.wav"
    with wave.open(str(audio_path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(48_000)
        target.writeframes(b"\x00\x00" * 48_000)
    manifest = _manifest(version=compositor.ASSEMBLY_VERSION_V3)
    manifest["sections"][0]["assets"][0][
        "source_sha256"
    ] = hashlib.sha256(image_path.read_bytes()).hexdigest()
    manifest["sections"][0]["audio"]["source_sha256"] = [
        hashlib.sha256(audio_path.read_bytes()).hexdigest()
    ]
    props = remotion.build_remotion_props(_rehash(manifest))
    staging = tmp_path / f"real-{format_name.lower()}"
    rows = await remotion._stage_renderer_sources(
        props,
        {
            "asset-1": image_path,
            "audio:section-1:0": audio_path,
        },
        staging=staging,
        log_path=tmp_path / f"{format_name.lower()}.log",
    )
    staged = staging / "public" / remotion.staged_local_path_for_source_key(
        "asset-1", "image"
    )
    assert staged.suffix == ".png"
    assert staged.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    probe = await remotion._probe_renderer_media(staged)
    assert probe["has_video"] is True
    assert probe["has_audio"] is False
    assert probe["duration_seconds"] is None
    assert rows[0]["source_sha256"] == hashlib.sha256(
        image_path.read_bytes()
    ).hexdigest()


@pytest.mark.asyncio
async def test_source_clip_native_audio_needs_no_separate_audio_source(
    monkeypatch, tmp_path: Path
):
    video = tmp_path / "source.mp4"
    audio = tmp_path / "unused-audio.bin"
    video.write_bytes(b"approved-video-with-native-audio")
    audio.write_bytes(b"unused")
    props = _v3_props_for_sources(video, audio)
    asset = props["sections"][0]["assets"][0]
    asset["timing_transform"] = {
        "mode": "none",
        "source_duration_ms": 300_000,
        "output_duration_ms": 300_000,
    }
    asset["actual_duration_ms"] = 300_000
    asset["assigned_duration_ms"] = 300_000
    props["sections"][0]["audio"]["mode"] = "source_clip"
    props["sections"][0]["audio"]["timing_transform"] = {
        "mode": "source_clip",
        "source_duration_ms": 300_000,
        "output_duration_ms": 300_000,
        "atempo_chain": [],
        "caption_scale": 1,
    }
    props["sections"][0]["audio"]["sources"] = []
    body = copy.deepcopy(props)
    del body["props_hash"]
    props["props_hash"] = remotion.remotion_props_hash(body)
    remotion._validate_renderer_props(props)

    async def fake_command(command, **_kwargs):
        destination = Path(command[-1])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"normalized-video")

    async def fake_probe(_path):
        return {
            "has_video": True,
            "has_audio": True,
            "duration_seconds": 300.0,
            "video_duration_seconds": 300.0,
            "audio_duration_seconds": 300.0,
            "video_frame_count": 7200,
            "video_avg_frame_rate": "24/1",
        }

    monkeypatch.setattr(remotion, "_run_local_command", fake_command)
    monkeypatch.setattr(remotion, "_probe_renderer_media", fake_probe)
    rows = await remotion._stage_renderer_sources(
        props,
        {"asset-1": video},
        staging=tmp_path / "source-clip-staging",
        log_path=tmp_path / "source-clip.log",
    )
    assert rows == [
        {
            "source_key": "asset-1",
            "kind": "video",
            "source_sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
            "staged_sha256": hashlib.sha256(b"normalized-video").hexdigest(),
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "probe_change",
    ["no_native_audio", "wrong_video_duration", "wrong_audio_type", "wrong_audio_duration"],
)
async def test_source_media_probe_rejects_type_duration_or_native_audio_drift(
    monkeypatch, tmp_path: Path, probe_change: str
):
    video = tmp_path / "source.mp4"
    unused_audio = tmp_path / "unused-audio.bin"
    video.write_bytes(b"approved-video")
    unused_audio.write_bytes(b"unused")
    props = _v3_props_for_sources(video, unused_audio)
    asset = props["sections"][0]["assets"][0]
    asset["actual_duration_ms"] = 300_000
    asset["assigned_duration_ms"] = 300_000
    asset["timing_transform"] = {
        "mode": "none",
        "source_duration_ms": 300_000,
        "output_duration_ms": 300_000,
    }
    if probe_change in {"no_native_audio", "wrong_video_duration"}:
        props["sections"][0]["audio"] = {
            "mode": "source_clip",
            "sources": [],
            "timing_transform": {
                "mode": "source_clip",
                "source_duration_ms": 300_000,
                "output_duration_ms": 300_000,
                "atempo_chain": [],
                "caption_scale": 1,
            },
            "gain_db": -3.0,
        }
        paths = {"asset-1": video}
    else:
        audio = tmp_path / "narration.wav"
        audio.write_bytes(b"approved-audio")
        props["sections"][0]["audio"]["sources"][0][
            "source_sha256"
        ] = hashlib.sha256(audio.read_bytes()).hexdigest()
        paths = {"asset-1": video, "audio:section-1:0": audio}
    body = copy.deepcopy(props)
    del body["props_hash"]
    props["props_hash"] = remotion.remotion_props_hash(body)
    remotion._validate_renderer_props(props)

    async def fake_probe(path):
        payload = Path(path).read_bytes()
        if b"audio" in payload:
            return {
                "has_video": probe_change == "wrong_audio_type",
                "has_audio": True,
                "duration_seconds": (
                    299.0
                    if probe_change == "wrong_audio_duration"
                    else 300.0
                ),
                "video_duration_seconds": (
                    300.0 if probe_change == "wrong_audio_type" else None
                ),
                "audio_duration_seconds": (
                    299.0
                    if probe_change == "wrong_audio_duration"
                    else 300.0
                ),
            }
        video_duration = (
            299.0 if probe_change == "wrong_video_duration" else 300.0
        )
        return {
            "has_video": True,
            "has_audio": probe_change != "no_native_audio",
            "duration_seconds": video_duration,
            "video_duration_seconds": video_duration,
            "audio_duration_seconds": (
                None if probe_change == "no_native_audio" else video_duration
            ),
        }

    commands: list[list[str]] = []

    async def fake_convert(command, **_kwargs):
        commands.append(list(command))
        destination = Path(command[-1])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"normalized-video")

    monkeypatch.setattr(remotion, "_probe_renderer_media", fake_probe)
    monkeypatch.setattr(remotion, "_run_local_command", fake_convert)
    with pytest.raises(contract.CustomFilmContractError):
        await remotion._stage_renderer_sources(
            props,
            paths,
            staging=tmp_path / "invalid-media",
            log_path=tmp_path / "invalid-media.log",
        )
    if probe_change in {"no_native_audio", "wrong_video_duration"}:
        assert commands == []
    else:
        assert len(commands) == 1


@pytest.mark.asyncio
async def test_media_probe_missing_executable_is_retryable(
    monkeypatch, tmp_path: Path
):
    async def missing_executable(*_args, **_kwargs):
        raise OSError("ffprobe missing")

    monkeypatch.setattr(
        remotion.asyncio, "create_subprocess_exec", missing_executable
    )
    with pytest.raises(compositor.CustomFilmRetryableError):
        await remotion._probe_renderer_media(tmp_path / "source.png")


@pytest.mark.asyncio
async def test_media_probe_broken_process_is_retryable(
    monkeypatch, tmp_path: Path
):
    class BrokenProcess:
        returncode = 2

        async def communicate(self):
            return b"", b"ffprobe internal process failure"

    async def broken_process(*_args, **_kwargs):
        return BrokenProcess()

    monkeypatch.setattr(
        remotion.asyncio, "create_subprocess_exec", broken_process
    )
    with pytest.raises(compositor.CustomFilmRetryableError):
        await remotion._probe_renderer_media(tmp_path / "source.png")


@pytest.mark.asyncio
async def test_media_probe_cancellation_terminates_and_waits(
    monkeypatch, tmp_path: Path
):
    started = asyncio.Event()

    class HangingProcess:
        returncode = None
        killed = False
        waited = False

        async def communicate(self):
            started.set()
            await asyncio.Event().wait()

        def kill(self):
            self.killed = True
            self.returncode = -9

        async def wait(self):
            self.waited = True
            return self.returncode

    process = HangingProcess()

    async def hanging_process(*_args, **_kwargs):
        return process

    monkeypatch.setattr(
        remotion.asyncio, "create_subprocess_exec", hanging_process
    )
    task = asyncio.create_task(
        remotion._probe_renderer_media(tmp_path / "source.mp4")
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.killed is True
    assert process.waited is True


@pytest.mark.asyncio
async def test_real_invalid_media_probe_is_terminal(tmp_path: Path):
    invalid = tmp_path / "not-media.bin"
    invalid.write_bytes(b"not a media container")
    with pytest.raises(contract.CustomFilmContractError):
        await remotion._probe_renderer_media(invalid)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("approved_seconds", "raw_video_frames", "raw_audio_seconds"),
    [
        (6, 145, 4.494),
        (15, 361, 14.292),
    ],
    ids=["diagnostic-6-second-clip", "diagnostic-15-second-clip"],
)
async def test_real_native_video_one_frame_tail_and_short_audio_normalize_exact(
    tmp_path: Path,
    approved_seconds: int,
    raw_video_frames: int,
    raw_audio_seconds: float,
):
    source = tmp_path / (
        f"raw-{raw_video_frames}-frames-with-{raw_audio_seconds}-audio.mp4"
    )
    log_path = tmp_path / "normalization.log"
    await _generate_native_source(
        source,
        video_frames=raw_video_frames,
        audio_seconds=raw_audio_seconds,
        log_path=log_path,
    )
    raw_probe = await remotion._probe_renderer_media(source)
    assert raw_probe["video_duration_seconds"] == pytest.approx(
        raw_video_frames / 24, abs=0.001
    )
    assert raw_probe["audio_duration_seconds"] == pytest.approx(
        raw_audio_seconds, abs=0.002
    )

    props = _source_clip_props(
        source, duration_seconds=approved_seconds
    )
    staging = tmp_path / "staging"
    rows = await remotion._stage_renderer_sources(
        props,
        {"asset-1": source},
        staging=staging,
        log_path=log_path,
    )
    staged = staging / "public" / remotion.staged_local_path_for_source_key(
        "asset-1", "video"
    )
    staged_probe = await remotion._probe_renderer_media(staged)
    assert staged_probe["video_frame_count"] == approved_seconds * 24
    assert staged_probe["video_avg_frame_rate"] == "24/1"
    assert staged_probe["video_duration_seconds"] == pytest.approx(
        approved_seconds,
        abs=remotion._STREAM_COVERAGE_TOLERANCE_SECONDS,
    )
    assert staged_probe["audio_duration_seconds"] is not None
    audio_delta = (
        float(staged_probe["audio_duration_seconds"]) - approved_seconds
    )
    assert -remotion._STREAM_COVERAGE_TOLERANCE_SECONDS <= audio_delta
    assert audio_delta <= remotion._AAC_PACKET_PADDING_SECONDS
    decoded = tmp_path / f"decoded-{approved_seconds}.wav"
    await remotion._run_local_command(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(staged),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "48000",
            "-c:a",
            "pcm_s16le",
            str(decoded),
        ],
        cwd=tmp_path,
        timeout_seconds=60,
        log_path=log_path,
    )
    with wave.open(str(decoded), "rb") as stream:
        samples = array("h", stream.readframes(stream.getnframes()))
    if sys.byteorder != "little":
        samples.byteswap()

    def mean_amplitude(start: float, end: float) -> float:
        window = samples[round(start * 48_000):round(end * 48_000)]
        return sum(abs(value) for value in window) / len(window)

    assert mean_amplitude(1.0, 1.25) > 100
    assert mean_amplitude(
        approved_seconds - 0.25, approved_seconds - 0.05
    ) < 20
    assert rows == [
        {
            "source_key": "asset-1",
            "kind": "video",
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "staged_sha256": hashlib.sha256(staged.read_bytes()).hexdigest(),
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("video_frames", "audio_seconds"),
    [
        (146, 4.5),
        (143, 4.5),
        (145, None),
        (145, 0.5),
        (145, 6.2),
    ],
    ids=[
        "more-than-one-frame-tail",
        "shorter-than-approved-video",
        "missing-native-audio",
        "tiny-native-audio",
        "overlong-native-audio",
    ],
)
async def test_real_native_video_raw_identity_mutations_fail_closed(
    tmp_path: Path,
    video_frames: int,
    audio_seconds: float | None,
):
    source = tmp_path / "invalid-native.mp4"
    log_path = tmp_path / "invalid-native.log"
    await _generate_native_source(
        source,
        video_frames=video_frames,
        audio_seconds=audio_seconds,
        log_path=log_path,
    )
    props = _source_clip_props(source)
    with pytest.raises(
        contract.CustomFilmContractError,
        match="approved source media identity changed",
    ):
        await remotion._stage_renderer_sources(
            props,
            {"asset-1": source},
            staging=tmp_path / "invalid-staging",
            log_path=log_path,
        )


@pytest.mark.asyncio
async def test_real_staged_probe_rejects_unnormalized_native_output(
    monkeypatch,
    tmp_path: Path,
):
    source = tmp_path / "valid-raw.mp4"
    log_path = tmp_path / "invalid-staged.log"
    await _generate_native_source(
        source,
        video_frames=145,
        audio_seconds=4.494,
        log_path=log_path,
    )
    props = _source_clip_props(source)

    async def emit_raw_instead_of_normalized(command, **_kwargs):
        raw = Path(command[command.index("-i") + 1])
        destination = Path(command[-1])
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(raw, destination)

    monkeypatch.setattr(
        remotion, "_run_local_command", emit_raw_instead_of_normalized
    )
    with pytest.raises(
        contract.CustomFilmContractError,
        match="staged media type changed",
    ):
        await remotion._stage_renderer_sources(
            props,
            {"asset-1": source},
            staging=tmp_path / "staged-mutation",
            log_path=log_path,
        )


@pytest.mark.asyncio
async def test_real_300_second_native_audio_staging_tolerates_aac_padding(
    tmp_path: Path,
):
    source = tmp_path / "native-source.mp4"
    log_path = tmp_path / "native-source.log"
    await remotion._run_local_command(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x0cb4a0:s=32x18:r=1:d=300",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=stereo",
            "-t",
            "300",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "32k",
            "-threads",
            "1",
            str(source),
        ],
        cwd=tmp_path,
        timeout_seconds=120,
        log_path=log_path,
    )
    unused_audio = tmp_path / "unused-audio.bin"
    unused_audio.write_bytes(b"unused")
    props = _v3_props_for_sources(source, unused_audio)
    asset = props["sections"][0]["assets"][0]
    asset["actual_duration_ms"] = 300_000
    asset["assigned_duration_ms"] = 300_000
    asset["timing_transform"] = {
        "mode": "none",
        "source_duration_ms": 300_000,
        "output_duration_ms": 300_000,
    }
    props["sections"][0]["audio"] = {
        "mode": "source_clip",
        "sources": [],
        "timing_transform": {
            "mode": "source_clip",
            "source_duration_ms": 300_000,
            "output_duration_ms": 300_000,
            "atempo_chain": [],
            "caption_scale": 1,
        },
        "gain_db": -3.0,
    }
    body = copy.deepcopy(props)
    del body["props_hash"]
    props["props_hash"] = remotion.remotion_props_hash(body)
    remotion._validate_renderer_props(props)
    staging = tmp_path / "native-staging"
    rows = await remotion._stage_renderer_sources(
        props,
        {"asset-1": source},
        staging=staging,
        log_path=log_path,
    )
    staged = staging / "public" / remotion.staged_local_path_for_source_key(
        "asset-1", "video"
    )
    probe = await remotion._probe_renderer_media(staged)
    assert probe["video_duration_seconds"] == pytest.approx(300.0, abs=0.001)
    assert probe["audio_duration_seconds"] is not None
    assert (
        float(probe["audio_duration_seconds"])
        + remotion._STREAM_COVERAGE_TOLERANCE_SECONDS
        >= float(probe["video_duration_seconds"])
    )
    assert (
        float(probe["audio_duration_seconds"])
        - float(probe["video_duration_seconds"])
        <= remotion._AAC_PACKET_PADDING_SECONDS
    )
    assert rows[0]["source_sha256"] == hashlib.sha256(
        source.read_bytes()
    ).hexdigest()


@pytest.mark.asyncio
async def test_local_command_timeout_kills_process_group(tmp_path: Path):
    with pytest.raises(
        compositor.CustomFilmRetryableError, match="timed out"
    ):
        await remotion._run_local_command(
            [
                sys.executable,
                "-c",
                "import time; time.sleep(30)",
            ],
            cwd=tmp_path,
            timeout_seconds=0.05,
            log_path=tmp_path / "timeout.log",
        )


@pytest.mark.asyncio
async def test_real_renderer_adapter_uses_pinned_cli_unicode_srt_and_cleans(
    monkeypatch, tmp_path: Path
):
    asset = tmp_path / "asset.bin"
    audio = tmp_path / "audio.bin"
    asset.write_bytes(b"approved-image")
    audio.write_bytes(b"approved-audio")
    props = _v3_props_for_sources(asset, audio)
    workdir = tmp_path / "private-render"
    captured: dict[str, object] = {"commands": [], "srt": ""}

    monkeypatch.setattr(
        remotion.tempfile,
        "mkdtemp",
        lambda **_kwargs: str(workdir),
    )

    async def fake_command(command, *, cwd, **_kwargs):
        captured["commands"].append(list(command))
        if command[0].endswith("node"):
            source_audio = (
                remotion._remotion_project_root() / "public/motion-audio"
            )
            target_audio = Path(cwd) / "public/motion-audio"
            target_audio.mkdir(parents=True, exist_ok=True)
            for source in source_audio.glob("*.wav"):
                shutil.copyfile(source, target_audio / source.name)
            return
        if command[0] == "ffmpeg":
            destination = Path(command[-1])
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.name == "normalized.mp4":
                assert command[command.index("-threads") + 1] == "1"
                assert command[command.index("-filter_threads") + 1] == "1"
                assert command[command.index("-filter_complex_threads") + 1] == "1"
                input_indexes = [
                    index for index, value in enumerate(command) if value == "-i"
                ]
                captured["srt"] = Path(
                    command[input_indexes[-1] + 1]
                ).read_text(encoding="utf-8")
                destination.write_bytes(b"deterministic-final")
            else:
                destination.write_bytes(b"normalized-source")
            return
        # Pinned Remotion CLI: output is the fifth positional argument.
        assert "npx" not in command
        assert command[0].endswith("node_modules/.bin/remotion")
        assert "--concurrency=1" in command
        assert "--gl=angle" in command
        remotion_output = Path(command[4])
        if "--sequence" in command:
            assert "--image-format=png" in command
            assert "--image-sequence-pattern=frame-[frame].[ext]" in command
            remotion_output.mkdir(parents=True, exist_ok=True)
            for frame in range(7200):
                (remotion_output / f"frame-{frame:04d}.png").write_bytes(
                    b"deterministic-png"
                )
        else:
            assert "--codec=wav" in command
            remotion_output.write_bytes(b"deterministic-wav")

    async def exact_probe(_path):
        return {
            "frame_count": 7200,
            "width": 1920,
            "height": 1080,
            "fps_fraction": "24/1",
            "has_video": True,
            "has_audio": True,
            "has_subtitles": True,
            "duration_seconds": 300.0,
        }

    async def source_probe(path):
        path = Path(path)
        payload = path.read_bytes()
        is_audio = path.suffix == ".wav" or b"audio" in payload
        return {
            "has_video": not is_audio,
            "has_audio": is_audio,
            "duration_seconds": 300.0,
            "video_duration_seconds": None if is_audio else 300.0,
            "audio_duration_seconds": 300.0 if is_audio else None,
        }

    monkeypatch.setattr(remotion, "_run_local_command", fake_command)
    monkeypatch.setattr(remotion, "_probe_renderer_media", source_probe)
    monkeypatch.setattr(
        remotion, "_validate_lossless_intermediates", lambda **_kwargs: None
    )
    monkeypatch.setattr(compositor, "probe_media", exact_probe)
    output = tmp_path / "final.mp4"
    progress: list[str] = []

    async def on_progress(message: str):
        progress.append(message)

    result = await remotion.run_remotion_renderer(
        remotion_props=props,
        source_paths={
            "asset-1": asset,
            "audio:section-1:0": audio,
        },
        output_path=output,
        on_progress=on_progress,
    )
    assert result["status"] == "rendered_local"
    assert result["artifact_sha256"] == hashlib.sha256(
        b"deterministic-final"
    ).hexdigest()
    assert result["captions"] == props["sections"][0]["captions"]
    assert "Mara: Si puedes oírme." in str(captured["srt"])
    assert output.read_bytes() == b"deterministic-final"
    assert not workdir.exists()
    assert progress and progress[-1].startswith("Rendering ")


def _write_valid_intermediate_fixture(
    root: Path,
    *,
    total_frames: int = 2,
    fps: int = 24,
    width: int = 16,
    height: int = 9,
) -> tuple[Path, Path]:
    frames = root / "raw-frames"
    frames.mkdir(parents=True)
    for frame in range(total_frames):
        Image.new("RGB", (width, height), (frame, 20, 30)).save(
            frames / f"frame-{frame:04d}.png"
        )
    audio = root / "raw-audio.wav"
    samples = total_frames * 48_000 // fps
    with wave.open(str(audio), "wb") as waveform:
        waveform.setnchannels(2)
        waveform.setsampwidth(2)
        waveform.setframerate(48_000)
        waveform.writeframes(b"\0" * samples * 4)
    return frames, audio


def test_intermediate_cache_identity_binds_props_renderer_and_sources(
    tmp_path: Path,
):
    asset = tmp_path / "asset.bin"
    audio = tmp_path / "audio.bin"
    asset.write_bytes(b"approved-image")
    audio.write_bytes(b"approved-audio")
    props = _v3_props_for_sources(asset, audio)
    baseline = remotion._intermediate_cache_identity(props)

    source_mutation = copy.deepcopy(props)
    source_mutation["sections"][0]["assets"][0]["source_sha256"] = "a" * 64
    renderer_mutation = copy.deepcopy(props)
    renderer_mutation["identity"]["renderer_bundle_hash"] = "b" * 64
    props_mutation = copy.deepcopy(props)
    props_mutation["props_hash"] = "c" * 64

    assert baseline["cache_key"] != remotion._intermediate_cache_identity(
        source_mutation
    )["cache_key"]
    assert baseline["cache_key"] != remotion._intermediate_cache_identity(
        renderer_mutation
    )["cache_key"]
    assert baseline["cache_key"] != remotion._intermediate_cache_identity(
        props_mutation
    )["cache_key"]
    assert "source_url" not in json.dumps(baseline)


def test_lossless_intermediate_validation_rejects_missing_corrupt_and_wrong_size(
    tmp_path: Path,
):
    frames, audio = _write_valid_intermediate_fixture(tmp_path)
    kwargs = {
        "raw_frames": frames,
        "raw_audio": audio,
        "total_frames": 2,
        "fps": 24,
        "width": 16,
        "height": 9,
    }
    remotion._validate_lossless_intermediates(**kwargs)

    missing = frames / "frame-0001.png"
    missing.unlink()
    with pytest.raises(contract.CustomFilmContractError, match="incomplete"):
        remotion._validate_lossless_intermediates(**kwargs)
    Image.new("RGB", (16, 9)).save(missing)

    missing.write_bytes(remotion._PNG_SIGNATURE + b"corrupt")
    with pytest.raises(
        contract.CustomFilmContractError, match="undecodable"
    ):
        remotion._validate_lossless_intermediates(**kwargs)
    Image.new("RGB", (17, 9)).save(missing)
    with pytest.raises(contract.CustomFilmContractError, match="dimensions"):
        remotion._validate_lossless_intermediates(**kwargs)


def test_intermediate_cache_rejects_stale_identity_and_truncated_wav(
    tmp_path: Path,
):
    frames, audio = _write_valid_intermediate_fixture(tmp_path)
    identity = {
        "cache_version": remotion._INTERMEDIATE_CACHE_VERSION,
        "props_hash": "a" * 64,
        "renderer_bundle_hash": "b" * 64,
        "sources": [],
        "cache_key": "c" * 64,
    }
    (tmp_path / "identity.json").write_text(
        remotion.canonical_remotion_json(identity)
    )
    with pytest.raises(contract.CustomFilmContractError, match="identity changed"):
        remotion._validate_intermediate_cache(
            cache_dir=tmp_path,
            identity={**identity, "props_hash": "d" * 64},
            total_frames=2,
            fps=24,
            width=16,
            height=9,
        )

    with audio.open("r+b") as stream:
        stream.truncate(audio.stat().st_size - 4)
    with pytest.raises(
        contract.CustomFilmContractError, match="WAV is (truncated|undecodable)"
    ):
        remotion._validate_lossless_intermediates(
            raw_frames=frames,
            raw_audio=audio,
            total_frames=2,
            fps=24,
            width=16,
            height=9,
        )


def test_intermediate_cache_rejects_valid_png_and_pcm_content_mutations(
    tmp_path: Path,
):
    identity = {
        "cache_version": remotion._INTERMEDIATE_CACHE_VERSION,
        "props_hash": "a" * 64,
        "renderer_bundle_hash": "b" * 64,
        "sources": [],
        "cache_key": "c" * 64,
    }

    png_cache = tmp_path / "png-cache"
    png_cache.mkdir()
    png_frames, png_audio = _write_valid_intermediate_fixture(png_cache)
    png_content = remotion._validate_lossless_intermediates(
        raw_frames=png_frames,
        raw_audio=png_audio,
        total_frames=2,
        fps=24,
        width=16,
        height=9,
    )
    remotion._write_private_canonical_json(
        png_cache / "identity.json", identity
    )
    remotion._write_private_canonical_json(
        png_cache / "content-manifest.json", png_content
    )
    remotion._validate_intermediate_cache(
        cache_dir=png_cache,
        identity=identity,
        total_frames=2,
        fps=24,
        width=16,
        height=9,
    )
    Image.new("RGB", (16, 9), (240, 12, 34)).save(
        png_frames / "frame-0001.png"
    )
    with pytest.raises(contract.CustomFilmContractError, match="content hash"):
        remotion._validate_intermediate_cache(
            cache_dir=png_cache,
            identity=identity,
            total_frames=2,
            fps=24,
            width=16,
            height=9,
        )

    wav_cache = tmp_path / "wav-cache"
    wav_cache.mkdir()
    wav_frames, wav_audio = _write_valid_intermediate_fixture(wav_cache)
    wav_content = remotion._validate_lossless_intermediates(
        raw_frames=wav_frames,
        raw_audio=wav_audio,
        total_frames=2,
        fps=24,
        width=16,
        height=9,
    )
    remotion._write_private_canonical_json(
        wav_cache / "identity.json", identity
    )
    remotion._write_private_canonical_json(
        wav_cache / "content-manifest.json", wav_content
    )
    wav_payload = bytearray(wav_audio.read_bytes())
    wav_payload[-1] ^= 1
    wav_audio.write_bytes(wav_payload)
    with pytest.raises(contract.CustomFilmContractError, match="content hash"):
        remotion._validate_intermediate_cache(
            cache_dir=wav_cache,
            identity=identity,
            total_frames=2,
            fps=24,
            width=16,
            height=9,
        )


def test_exact_probe_rejects_2496_frame_delivery_truncation():
    assert not compositor.probe_has_exact_video_identity(
        {
            "frame_count": 2496,
            "width": 1920,
            "height": 1080,
            "fps_fraction": "24/1",
            "duration_seconds": 104.0,
        },
        total_frames=7200,
        fps=24,
        width=1920,
        height=1080,
    )


@pytest.mark.asyncio
async def test_explicit_concat_delivery_preserves_every_frame(tmp_path: Path):
    total_frames = 24
    fps = 24
    width = 32
    height = 18
    frames, audio = _write_valid_intermediate_fixture(
        tmp_path,
        total_frames=total_frames,
        fps=fps,
        width=width,
        height=height,
    )
    # Chromium can emit opaque RGB and translucent RGBA PNGs in one approved
    # sequence. Delivery must preserve the timeline across that pixel-format
    # transition instead of rebuilding the filter graph and resetting audio.
    for frame in range(total_frames // 2, total_frames):
        Image.new("RGBA", (width, height), (frame, 20, 30, 225)).save(
            frames / f"frame-{frame:04d}.png"
        )
    concat = tmp_path / "frames.ffconcat"
    output = tmp_path / "delivery.mp4"
    remotion._write_frame_concat_manifest(
        raw_frames=frames,
        destination=concat,
        total_frames=total_frames,
        fps=fps,
    )
    await remotion._run_local_command(
        [
            "ffmpeg", "-y", "-threads", "1", "-filter_threads", "1",
            "-filter_complex_threads", "1", "-reinit_filter", "0",
            "-xerror", "-err_detect",
            "explode", "-f", "concat", "-safe", "0", "-i", str(concat),
            "-i", str(audio), "-filter_complex",
            (
                f"[0:v]fps={fps},scale={width}:{height},"
                f"trim=end_frame={total_frames},setpts=N/({fps}*TB)[v];"
                "[1:a]aresample=48000,apad,atrim=end_sample=48000,"
                "asetpts=N/SR/TB[a]"
            ),
            "-map", "[v]", "-map", "[a]", "-frames:v", str(total_frames),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-x264-params",
            "threads=1:lookahead_threads=1:sliced_threads=0",
            "-c:a", "aac", "-ar", "48000", "-ac", "2",
            "-map_metadata", "-1", str(output),
        ],
        cwd=tmp_path,
        timeout_seconds=60,
        log_path=tmp_path / "ffmpeg.log",
    )
    probe = await compositor.probe_media(output)
    assert compositor.probe_has_exact_video_identity(
        probe,
        total_frames=total_frames,
        fps=fps,
        width=width,
        height=height,
    )


@pytest.mark.asyncio
async def test_delivery_failure_reuses_verified_intermediates_on_cold_retry(
    monkeypatch, tmp_path: Path
):
    asset = tmp_path / "asset.bin"
    audio = tmp_path / "audio.bin"
    asset.write_bytes(b"approved-image")
    audio.write_bytes(b"approved-audio")
    props = _v3_props_for_sources(asset, audio)
    cache_root = tmp_path / "private-cache"
    delivery_attempts = 0
    sequence_captures = 0
    audio_captures = 0
    probe_frame_count = 7200

    async def fake_command(command, *, cwd, **_kwargs):
        nonlocal delivery_attempts, sequence_captures, audio_captures
        if command[0].endswith("node"):
            source_audio = (
                remotion._remotion_project_root() / "public/motion-audio"
            )
            target_audio = Path(cwd) / "public/motion-audio"
            target_audio.mkdir(parents=True, exist_ok=True)
            for source in source_audio.glob("*.wav"):
                shutil.copyfile(source, target_audio / source.name)
            return
        if command[0] == "ffmpeg":
            destination = Path(command[-1])
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.name == "normalized.mp4":
                delivery_attempts += 1
                if delivery_attempts == 1:
                    raise compositor.CustomFilmRetryableError(
                        "synthetic delivery interruption"
                    )
                destination.write_bytes(b"verified-delivery")
            else:
                destination.write_bytes(b"normalized-source")
            return
        remotion_output = Path(command[4])
        if "--sequence" in command:
            sequence_captures += 1
            assert remotion_output.parent.name.startswith("partial-")
            assert remotion_output.parent.suffix == ""
            remotion_output.mkdir(parents=True, exist_ok=True)
        else:
            audio_captures += 1
            remotion_output.write_bytes(b"lossless-audio")

    async def source_probe(path):
        path = Path(path)
        payload = path.read_bytes()
        is_audio = path.suffix == ".wav" or b"audio" in payload
        return {
            "has_video": not is_audio,
            "has_audio": is_audio,
            "duration_seconds": 300.0,
            "video_duration_seconds": None if is_audio else 300.0,
            "audio_duration_seconds": 300.0 if is_audio else None,
        }

    async def exact_probe(_path):
        return {
            "frame_count": probe_frame_count,
            "width": 1920,
            "height": 1080,
            "fps_fraction": "24/1",
            "has_video": True,
            "has_audio": True,
            "has_subtitles": True,
            "duration_seconds": probe_frame_count / 24,
        }

    monkeypatch.setattr(remotion, "_run_local_command", fake_command)
    monkeypatch.setattr(remotion, "_probe_renderer_media", source_probe)
    monkeypatch.setattr(
        remotion, "_validate_lossless_intermediates", lambda **_kwargs: None
    )
    monkeypatch.setattr(compositor, "probe_media", exact_probe)
    kwargs = {
        "remotion_props": props,
        "source_paths": {
            "asset-1": asset,
            "audio:section-1:0": audio,
        },
        "output_path": tmp_path / "final.mp4",
        "intermediate_cache_root": cache_root,
    }

    with pytest.raises(
        compositor.CustomFilmRetryableError,
        match="synthetic delivery interruption",
    ):
        await remotion.run_remotion_renderer(**kwargs)
    cache_entries = [
        path for path in cache_root.iterdir() if not path.name.startswith(".")
    ]
    assert len(cache_entries) == 1
    assert cache_root.stat().st_mode & 0o777 == 0o700
    assert cache_entries[0].stat().st_mode & 0o777 == 0o700
    assert (cache_entries[0] / "identity.json").is_file()
    assert (cache_entries[0] / "content-manifest.json").is_file()
    assert sequence_captures == 1
    assert audio_captures == 1

    result = await remotion.run_remotion_renderer(**kwargs)
    assert result["artifact_sha256"] == hashlib.sha256(
        b"verified-delivery"
    ).hexdigest()
    assert sequence_captures == 1
    assert audio_captures == 1
    assert not cache_entries[0].exists()

    probe_frame_count = 2496
    terminal_kwargs = {
        **kwargs,
        "output_path": tmp_path / "terminal-probe-failure.mp4",
    }
    with pytest.raises(
        contract.CustomFilmContractError, match="failed exact probe"
    ):
        await remotion.run_remotion_renderer(**terminal_kwargs)
    assert not [
        path for path in cache_root.iterdir() if not path.name.startswith(".")
    ]


def test_migration_131_and_fresh_schema_bind_renderer_implementation():
    root = Path(__file__).resolve().parents[3]
    migration = (
        root / "backend/migrations/131_custom_film_remotion_renderer_v3.sql"
    ).read_text()
    schema = (root / "schema.sql").read_text()
    for text in (migration, schema):
        assert "'custom-film-assembly-v3'" in text
        assert "manifest->>'render_engine' = 'remotion'" in text
        assert "custom-film-remotion-renderer-v1" in text
        assert "renderer_bundle_hash" in text
