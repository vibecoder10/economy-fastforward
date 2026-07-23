"""No-spend render-contract tests for Anton's DvsU launch feedback."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import render_static  # noqa: E402


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
