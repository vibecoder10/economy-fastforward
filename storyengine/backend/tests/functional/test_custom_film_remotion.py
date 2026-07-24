from __future__ import annotations

import copy
import json
import sys
import types
from pathlib import Path

import pytest

import custom_film_compositor as compositor
import custom_film_contract as contract
import custom_film_remotion as remotion


def _manifest(*, engine: str = "remotion") -> dict:
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
        "assembly_version": compositor.ASSEMBLY_VERSION,
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

    async def load_inputs(_tenant_id, _video_id):
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
