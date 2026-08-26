"""No-spend render-contract tests for Anton's DvsU launch feedback."""

import json
import importlib
import importlib.util
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import render_static  # noqa: E402


def _channel_audio():
    spec = importlib.util.find_spec("channel_audio")
    assert spec is not None, "channel_audio module must define the fixed music-bed contract"
    module = importlib.import_module("channel_audio")
    assert hasattr(module, "FixedMusicBedConfig")
    return module


@pytest.mark.asyncio
async def test_gather_segments_keeps_three_ordered_static_views_under_one_voice(monkeypatch):
    async def fake_fetch_all(query, *args):
        if "FROM scripts" in query:
            return [{
                "scene": 4,
                "scene_text": "The B-52 entered service in 1955.",
                "voice_over_url": "voice.mp3",
                "voice_duration_seconds": 12.0,
            }]
        return [
            {
                "scene": 4, "image_index": 1, "image_url": "three-quarter.png",
                "generation_method": "static_docu", "hero_shot": True,
                "caption": json.dumps({
                    "title": "B-52 Stratofortress",
                    "sub": "USAF • 1955–present",
                    "specs": ["Wingspan 185 ft"],
                    "view_role": "three_quarter",
                }),
            },
            {
                "scene": 4, "image_index": 2, "image_url": "top.png",
                "generation_method": "static_docu", "hero_shot": False,
                "caption": json.dumps({"view_role": "top_oblique"}),
            },
            {
                "scene": 4, "image_index": 3, "image_url": "detail.png",
                "generation_method": "static_docu", "hero_shot": False,
                "caption": json.dumps({"view_role": "engineering_detail"}),
            },
            {
                "scene": 4, "image_index": 9, "image_url": "coverage.png",
                "generation_method": "coverage", "hero_shot": False,
                "caption": None,
            },
        ]

    monkeypatch.setattr(render_static, "fetch_all", fake_fetch_all)
    segments = await render_static._gather_segments("video", "tenant")

    assert len(segments) == 1
    assert segments[0]["voice_url"] == "voice.mp3"
    assert [img["image_url"] for img in segments[0]["images"]] == [
        "three-quarter.png", "top.png", "detail.png",
    ]
    assert segments[0]["caption"]["title"] == "B-52 Stratofortress"


def _multi_view_segment():
    caption = {
        "title": "B-52 Stratofortress",
        "sub": "USAF • 1955–present",
        "specs": ["Wingspan 185 ft", "Maximum speed 650 mph"],
    }
    return {
        "scene": 4,
        "scene_text": "B-52 narration",
        "voice_url": "voice.mp3",
        "voice_duration": 12.0,
        "duration": 12.0,
        "image_url": "three-quarter.png",
        "caption": caption,
        "images": [
            {
                "image_url": "three-quarter.png", "source_index": 1,
                "caption": {**caption, "view_role": "three_quarter"},
            },
            {
                "image_url": "top.png", "source_index": 2,
                "caption": {**caption, "view_role": "top_oblique"},
            },
            {
                "image_url": "detail.png", "source_index": 3,
                "caption": {**caption, "view_role": "engineering_detail"},
            },
        ],
    }


def test_render_config_rotates_three_views_without_restarting_the_title_or_voice():
    rc = render_static._build_render_config("video", [_multi_view_segment()])
    scenes = rc["scenes"]

    assert len(scenes) == 3
    assert [scene["scene_number"] for scene in scenes] == [4, 4, 4]
    assert [scene["image_index"] for scene in scenes] == [1, 2, 3]
    assert [scene["image_path"] for scene in scenes] == [
        "Scene_04_01.png", "Scene_04_02.png", "Scene_04_03.png",
    ]
    assert sum(scene["display_duration"] for scene in scenes) == pytest.approx(12.0)
    assert {scene["narration_start"] for scene in scenes} == {0.0}
    assert {scene["narration_end"] for scene in scenes} == {12.0}

    assert scenes[0]["caption_title"] == "B-52 Stratofortress"
    assert scenes[0]["caption_specs"] == [
        "Wingspan 185 ft", "Maximum speed 650 mph",
    ]
    assert scenes[1]["caption_title"] == scenes[2]["caption_title"] == ""
    assert scenes[1]["caption_specs"] == scenes[2]["caption_specs"] == []


def test_render_config_alternates_only_smooth_push_in_and_pull_out():
    rc = render_static._build_render_config("video", [_multi_view_segment()])
    moves = [scene["ken_burns"] for scene in rc["scenes"]]

    assert [move["direction"] for move in moves] == [
        "slow_push_in", "slow_pull_out", "slow_push_in",
    ]
    for move in moves:
        assert move["motion_curve"] == "cinematic_smoothstep"
        assert move["speed_multiplier"] == 1.0
        assert move["disable_breathe"] is True
        assert move["start_x_offset"] == move["end_x_offset"] == 0
        assert move["start_y_offset"] == move["end_y_offset"] == 0
    assert moves[0]["start_scale"] < moves[0]["end_scale"]
    assert moves[1]["start_scale"] > moves[1]["end_scale"]


def test_multiview_or_title_card_never_silently_uses_legacy_ffmpeg_path():
    rc = render_static._build_render_config("video", [_multi_view_segment()])
    assert render_static._requires_remotion(rc) is True

    legacy = {
        "scenes": [{
            "scene_number": 1,
            "caption_title": "",
        }]
    }
    assert render_static._requires_remotion(legacy) is False


@pytest.mark.asyncio
async def test_fixed_channel_music_returns_one_full_video_bed_and_skips_mood_classification(
    monkeypatch, tmp_path,
):
    channel_audio = _channel_audio()
    calibrated_volume = 0.018
    config = channel_audio.FixedMusicBedConfig(
        asset_url=(
            "https://storage.test/dvsu-channel/channel-assets/"
            "light_music-lonely-piano-189659.mp3"
        ),
        file_name="light_music-lonely-piano-189659.mp3",
        volume=calibrated_volume,
    )
    classify_calls = []
    download_calls = []
    normalize_calls = []

    async def fake_get_config(tenant_id):
        assert tenant_id == "tenant-dvsu"
        return config

    async def fake_download(url, dest, gc):
        download_calls.append((url, dest))
        dest.write_bytes(b"staged music")

    async def fake_normalize(path):
        normalize_calls.append(path)

    async def fake_get_text_client(tenant_id):
        classify_calls.append(tenant_id)
        raise AssertionError("fixed music must not classify moods")

    monkeypatch.setattr(channel_audio, "get_fixed_music_bed_config", fake_get_config)
    monkeypatch.setattr(render_static, "_download_to", fake_download)
    monkeypatch.setattr(render_static, "_normalize_audio", fake_normalize)
    import kie_unified
    monkeypatch.setattr(kie_unified, "get_text_client_for_tenant", fake_get_text_client)

    public_dir = tmp_path / "isolated-public"
    public_dir.mkdir()
    beds = await render_static._select_music_beds(
        "tenant-dvsu",
        [{"scene": 1, "scene_text": "A strategic opening."}],
        {"scenes": [{"scene_number": 1, "act": 1}]},
        public_dir,
    )

    assert beds == [{
        "scope": "video",
        "file": "light_music-lonely-piano-189659.mp3",
        "volume": calibrated_volume,
        "trim_before_seconds": 0.0,
        "loop": True,
    }]
    assert classify_calls == []
    assert download_calls == [(config.asset_url, public_dir / "music" / config.file_name)]
    assert normalize_calls == [public_dir / "music" / config.file_name]


@pytest.mark.asyncio
async def test_absent_fixed_channel_music_keeps_legacy_per_act_selection(monkeypatch, tmp_path):
    channel_audio = _channel_audio()

    async def fake_get_config(tenant_id):
        return None

    class FakeTextClient:
        async def generate(self, **kwargs):
            return '{"1": "tension"}'

    async def fake_get_text_client(tenant_id):
        return FakeTextClient()

    async def fake_normalize(path):
        return None

    music_library = tmp_path / "library"
    music_library.mkdir()
    (music_library / "tension_old-track.mp3").write_bytes(b"legacy music")
    monkeypatch.setattr(channel_audio, "get_fixed_music_bed_config", fake_get_config)
    monkeypatch.setattr(render_static, "_MUSIC_LIB_DIR", music_library)
    monkeypatch.setattr(render_static, "_normalize_audio", fake_normalize)
    import kie_unified
    monkeypatch.setattr(kie_unified, "get_text_client_for_tenant", fake_get_text_client)

    public_dir = tmp_path / "isolated-public"
    public_dir.mkdir()
    beds = await render_static._select_music_beds(
        "tenant-legacy",
        [{"scene": 1, "scene_text": "A tense opening."}],
        {"scenes": [{"scene_number": 1, "act": 1}]},
        public_dir,
    )

    assert beds == [{
        "act": 1,
        "file": "tension_old-track.mp3",
        "mood": "tension",
        "volume": 0.03,
    }]
