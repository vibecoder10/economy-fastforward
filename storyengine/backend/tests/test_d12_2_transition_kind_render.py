"""D12-2 — distinct render treatments per per-shot transition_kind
(migration 148, assets.transition_kind, harvested D9-6).

Before this chunk, transition_engine.determine_transition only looked at
act/style; render_static_ffmpeg.build_transition_plan only knew "cut" vs
"fade" (fadeblack). Every one of the 6 kinds the planner already emits
(opening/continuous/time_cut/location_cut/montage/memory) collapsed onto the
same generic quick crossfade at render time.

This file proves, no real ffmpeg/Remotion involved (structural assertions on
constructed dicts/filtergraph strings only — same style as
test_render_static_speed.py Part B):

  1. render_static._gather_segments / _build_render_config thread
     assets.transition_kind from the DB row into the render_config scene
     dicts transition_engine.determine_transition reads (the "how does
     transition_kind reach the render config" trace this chunk had to prove).
  2. render_static_ffmpeg.build_transition_plan / group_by_cuts /
     build_group_join_filter_complex honor the two new treatment shapes
     ("cut" reused; "dissolve" new — a true cross-dissolve xfade, distinct
     from the fade-through-black "fade" style every prior type used).
  3. Absent/NULL transition_kind is byte-identical to pre-D12-2 output at
     every layer — the decisive backward-compat proof.

Run: cd storyengine/backend && ./venv/bin/python -m pytest \
    tests/test_d12_2_transition_kind_render.py -q
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PIPELINE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "skills", "video-pipeline",
)
if _PIPELINE_PATH not in sys.path:
    sys.path.insert(0, _PIPELINE_PATH)

import render_static  # noqa: E402
import render_static_ffmpeg as rsf  # noqa: E402
from render.audio_sync.transition_engine import determine_transition  # noqa: E402
from render.audio_sync.config import (  # noqa: E402
    CROSSFADE_DURATION,
    HARD_CUT_DURATION,
    LOCATION_CUT_FADE,
    MONTAGE_FADE,
    MEMORY_DISSOLVE,
)


# ---------------------------------------------------------------------------
# 1. The threading trace: assets row -> _gather_segments -> _build_render_config
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gather_segments_threads_transition_kind_from_assets_row(monkeypatch):
    async def fake_fetch_all(query, *args):
        if "FROM scripts" in query:
            return [{
                "scene": 4,
                "scene_text": "The B-52 entered service in 1955.",
                "voice_over_url": "voice.mp3",
                "voice_duration_seconds": 12.0,
            }]
        assert "transition_kind" in query, (
            "the assets SELECT must fetch transition_kind (migration 148) "
            "or there is nothing to thread"
        )
        return [
            {
                "scene": 4, "image_index": 1, "image_url": "three-quarter.png",
                "generation_method": "static_docu", "hero_shot": True,
                "caption": None, "transition_kind": "location_cut",
            },
            {
                "scene": 4, "image_index": 2, "image_url": "top.png",
                "generation_method": "static_docu", "hero_shot": False,
                "caption": None, "transition_kind": None,
            },
        ]

    monkeypatch.setattr(render_static, "fetch_all", fake_fetch_all)
    segments = await render_static._gather_segments("video", "tenant")

    assert segments[0]["images"][0]["transition_kind"] == "location_cut"
    assert segments[0]["images"][1]["transition_kind"] is None


@pytest.mark.asyncio
async def test_gather_segments_transition_kind_absent_column_defaults_to_none(monkeypatch):
    """A row shaped like a pre-migration-148 fetch (no transition_kind key
    at all) must not raise — .get() tolerates it and yields None."""
    async def fake_fetch_all(query, *args):
        if "FROM scripts" in query:
            return [{
                "scene": 1, "scene_text": "x", "voice_over_url": "v.mp3",
                "voice_duration_seconds": 5.0,
            }]
        return [{
            "scene": 1, "image_index": 1, "image_url": "img.png",
            "generation_method": "static_docu", "hero_shot": True,
            "caption": None,
        }]

    monkeypatch.setattr(render_static, "fetch_all", fake_fetch_all)
    segments = await render_static._gather_segments("video", "tenant")
    assert segments[0]["images"][0]["transition_kind"] is None


def _two_scene_segments(second_scene_kind):
    """Seven one-image narration scenes, only the SECOND of which carries a
    transition_kind. _build_render_config's own "act" field is a bucketing
    formula over the total scene count (``min(6, position*6//scene_count+1)``
    — see its ken_burns/act comment), not an authored value; with only two
    total segments that bucketing itself puts scene 1 and scene 2 in
    DIFFERENT acts, so the act-boundary rule would win regardless of kind —
    a fixture artifact, not what this test wants to exercise. Seven segments
    keeps positions 0 and 1 in the SAME bucket (verified: 6//7 == 0) so the
    boundary under test (scenes[0] -> scenes[1]) is governed by kind, same
    style throughout ("static_docu" is hardcoded for every entry). Trailing
    padding scenes exist only so scene_count comes out to 7; nothing asserts
    on them."""
    def _scene(n, kind=None):
        return {
            "scene": n, "scene_text": f"scene {n}", "duration": 5.0,
            "image_url": f"s{n}.png", "caption": None,
            "images": [{"image_url": f"s{n}.png", "source_index": 1,
                        "caption": None, "transition_kind": kind}],
        }

    return [
        _scene(1, None),
        _scene(2, second_scene_kind),
        *[_scene(n) for n in range(3, 8)],
    ]


def test_build_render_config_threads_transition_kind_into_scene_dicts():
    segments = _two_scene_segments("memory")
    rc = render_static._build_render_config("video", segments)
    kinds = [s.get("transition_kind") for s in rc["scenes"]]
    assert kinds[0] is None
    assert kinds[1] == "memory"
    assert all(k is None for k in kinds[2:])


def test_build_render_config_produces_distinct_boundary_treatment_from_kind():
    """End-to-end through the real render_config builder (not a hand-built
    scene dict): a scene tagged "memory" produces a dissolve at the boundary
    leading into it, exactly matching determine_transition's own mapping."""
    segments = _two_scene_segments("memory")
    rc = render_static._build_render_config("video", segments)
    assert rc["scenes"][0]["transition_out"] == {
        "type": "dissolve", "duration": MEMORY_DISSOLVE,
    }


@pytest.mark.parametrize("kind,expected", [
    ("continuous", {"type": "cut", "duration": HARD_CUT_DURATION}),
    ("time_cut", {"type": "cut", "duration": HARD_CUT_DURATION}),
    ("location_cut", {"type": "crossfade", "duration": LOCATION_CUT_FADE}),
    ("montage", {"type": "crossfade", "duration": MONTAGE_FADE}),
    ("memory", {"type": "dissolve", "duration": MEMORY_DISSOLVE}),
])
def test_build_render_config_every_kind_reaches_the_boundary_treatment(kind, expected):
    segments = _two_scene_segments(kind)
    rc = render_static._build_render_config("video", segments)
    assert rc["scenes"][0]["transition_out"] == expected


def test_build_render_config_backward_compat_no_kind_anywhere():
    """The decisive byte-identical proof at the render_config layer: a scene
    list where no image carries transition_kind produces the exact plan
    _build_render_config produced before D12-2 existed (generic quick
    crossfade at every same-act, same-style boundary)."""
    segments = _two_scene_segments(None)
    rc = render_static._build_render_config("video", segments)
    assert rc["scenes"][0]["transition_out"] == {
        "type": "crossfade", "duration": CROSSFADE_DURATION,
    }


# ---------------------------------------------------------------------------
# 2. render_static_ffmpeg honors the new treatment names
# ---------------------------------------------------------------------------

def _scenes_for_kind(transition_type, duration):
    return [
        {"scene_number": 1, "display_duration": 5.0,
         "transition_in": {"type": "fade_from_black", "duration": 1.0},
         "transition_out": {"type": transition_type, "duration": duration}},
        {"scene_number": 2, "display_duration": 6.0,
         "transition_in": {"type": transition_type, "duration": duration},
         "transition_out": {"type": "fade_to_black", "duration": 1.0}},
    ]


def test_build_transition_plan_maps_dissolve_type_to_dissolve_style():
    scenes = _scenes_for_kind("dissolve", MEMORY_DISSOLVE)
    plan = rsf.build_transition_plan(scenes)
    assert plan["joins"] == [
        {"from": 0, "to": 1, "style": "dissolve", "duration": MEMORY_DISSOLVE},
    ]


def test_build_transition_plan_kind_cut_type_still_maps_to_cut_style():
    scenes = _scenes_for_kind("cut", HARD_CUT_DURATION)
    plan = rsf.build_transition_plan(scenes)
    assert plan["joins"][0]["style"] == "cut"
    assert plan["joins"][0]["duration"] == HARD_CUT_DURATION


def test_build_transition_plan_kind_crossfade_durations_pass_through():
    for kind_duration in (LOCATION_CUT_FADE, MONTAGE_FADE):
        scenes = _scenes_for_kind("crossfade", kind_duration)
        plan = rsf.build_transition_plan(scenes)
        assert plan["joins"][0] == {
            "from": 0, "to": 1, "style": "fade", "duration": kind_duration,
        }


def test_dissolve_style_does_not_split_the_fade_group():
    """A dissolve boundary joins like any fade — only "cut" starts a new
    concat-demuxer group."""
    scenes = _scenes_for_kind("dissolve", MEMORY_DISSOLVE)
    plan = rsf.build_transition_plan(scenes)
    groups = rsf.group_by_cuts(plan, len(scenes))
    assert groups == [[0, 1]]


def test_join_filter_complex_dissolve_uses_true_cross_dissolve_not_fadeblack():
    scenes = _scenes_for_kind("dissolve", MEMORY_DISSOLVE)
    plan = rsf.build_transition_plan(scenes)
    durations = [rsf.scene_clip_duration(s) for s in scenes]
    joins_by_from = {j["from"]: j for j in plan["joins"]}
    fc, v, a = rsf.build_group_join_filter_complex(
        [0, 1], durations, joins_by_from,
        apply_lead_in=True, lead_in_duration=plan["lead_in_duration"],
        apply_lead_out=True, lead_out_duration=plan["lead_out_duration"],
    )
    assert f"xfade=transition=fade:duration={MEMORY_DISSOLVE:.3f}" in fc
    assert "fadeblack" not in fc
    assert fc.count("acrossfade") == 1
    assert v == "vout" and a == "aout"


def test_join_filter_complex_mixed_fade_and_dissolve_in_one_group():
    """Three scenes: boundary 0->1 is a plain crossfade (location_cut, still
    fadeblack), boundary 1->2 is a dissolve (memory). Both are non-cut so
    they share one group, but each boundary keeps its OWN xfade transition
    name — proving the per-join style lookup, not a single group-wide mode."""
    scenes = [
        {"scene_number": 1, "display_duration": 5.0,
         "transition_in": {"type": "fade_from_black", "duration": 1.0},
         "transition_out": {"type": "crossfade", "duration": LOCATION_CUT_FADE}},
        {"scene_number": 2, "display_duration": 5.0,
         "transition_in": {"type": "crossfade", "duration": LOCATION_CUT_FADE},
         "transition_out": {"type": "dissolve", "duration": MEMORY_DISSOLVE}},
        {"scene_number": 3, "display_duration": 5.0,
         "transition_in": {"type": "dissolve", "duration": MEMORY_DISSOLVE},
         "transition_out": {"type": "fade_to_black", "duration": 1.0}},
    ]
    plan = rsf.build_transition_plan(scenes)
    groups = rsf.group_by_cuts(plan, len(scenes))
    assert groups == [[0, 1, 2]]

    durations = [rsf.scene_clip_duration(s) for s in scenes]
    joins_by_from = {j["from"]: j for j in plan["joins"]}
    fc, _, _ = rsf.build_group_join_filter_complex(
        [0, 1, 2], durations, joins_by_from,
        apply_lead_in=False, lead_in_duration=0.0,
        apply_lead_out=False, lead_out_duration=0.0,
    )
    assert f"xfade=transition=fadeblack:duration={LOCATION_CUT_FADE:.3f}" in fc
    assert f"xfade=transition=fade:duration={MEMORY_DISSOLVE:.3f}" in fc
    assert fc.count("acrossfade") == 2


def test_hard_cut_kind_still_splits_into_concat_demuxer_groups():
    """continuous/time_cut route through the SAME "cut" style the module
    already had forward-compat support for — group_by_cuts must still split
    on it exactly as before."""
    scenes = [
        {"scene_number": 1, "display_duration": 5.0,
         "transition_in": {"type": "fade_from_black", "duration": 1.0},
         "transition_out": {"type": "cut", "duration": HARD_CUT_DURATION}},
        {"scene_number": 2, "display_duration": 5.0,
         "transition_in": {"type": "cut", "duration": HARD_CUT_DURATION},
         "transition_out": {"type": "fade_to_black", "duration": 1.0}},
    ]
    plan = rsf.build_transition_plan(scenes)
    groups = rsf.group_by_cuts(plan, len(scenes))
    assert groups == [[0], [1]]


# ---------------------------------------------------------------------------
# 3. End-to-end: determine_transition's kind output -> build_transition_plan
#    -> group_by_cuts -> filter construction, for all five recognized kinds.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind", [
    "continuous", "time_cut", "location_cut", "montage", "memory",
])
def test_end_to_end_kind_to_ffmpeg_treatment_never_raises_and_is_distinct(kind):
    cur = {"style": "static_docu", "act": 1}
    nxt = {"style": "static_docu", "act": 1, "transition_kind": kind}
    t = determine_transition(cur, nxt)

    scenes = [
        {"scene_number": 1, "display_duration": 5.0,
         "transition_in": {"type": "fade_from_black", "duration": 1.0},
         "transition_out": t},
        {"scene_number": 2, "display_duration": 5.0,
         "transition_in": t,
         "transition_out": {"type": "fade_to_black", "duration": 1.0}},
    ]
    plan = rsf.build_transition_plan(scenes)
    groups = rsf.group_by_cuts(plan, len(scenes))

    if t["type"] == "cut":
        assert groups == [[0], [1]]
    else:
        assert groups == [[0, 1]]
        durations = [rsf.scene_clip_duration(s) for s in scenes]
        joins_by_from = {j["from"]: j for j in plan["joins"]}
        fc, _, _ = rsf.build_group_join_filter_complex(
            [0, 1], durations, joins_by_from,
            apply_lead_in=False, lead_in_duration=0.0,
            apply_lead_out=False, lead_out_duration=0.0,
        )
        expected_xfade = "fade" if t["type"] == "dissolve" else "fadeblack"
        assert f"xfade=transition={expected_xfade}:duration={t['duration']:.3f}" in fc


# ---------------------------------------------------------------------------
# Backward compat: the pre-D12-2 fixture from test_render_static_speed.py
# must still produce identical joins (no kind involved anywhere in it).
# ---------------------------------------------------------------------------

def test_pre_existing_sample_scenes_plan_unchanged():
    scenes = [
        {"scene_number": 1, "display_duration": 5.0,
         "transition_in": {"type": "fade_from_black", "duration": 1.0},
         "transition_out": {"type": "crossfade", "duration": 0.4}},
        {"scene_number": 2, "display_duration": 8.0,
         "transition_in": {"type": "crossfade", "duration": 0.4},
         "transition_out": {"type": "dip_to_black", "duration": 1.5}},
        {"scene_number": 3, "display_duration": 6.0,
         "transition_in": {"type": "dip_to_black", "duration": 1.5},
         "transition_out": {"type": "fade_to_black", "duration": 1.0}},
    ]
    plan = rsf.build_transition_plan(scenes)
    assert plan["joins"][0] == {"from": 0, "to": 1, "style": "fade", "duration": 0.4}
    assert plan["joins"][1] == {"from": 1, "to": 2, "style": "fade", "duration": 1.5}

    durations = [rsf.scene_clip_duration(s) for s in scenes]
    joins_by_from = {j["from"]: j for j in plan["joins"]}
    fc, _, _ = rsf.build_group_join_filter_complex(
        [0, 1, 2], durations, joins_by_from,
        apply_lead_in=True, lead_in_duration=plan["lead_in_duration"],
        apply_lead_out=True, lead_out_duration=plan["lead_out_duration"],
    )
    assert fc.count("xfade=transition=fadeblack") == 2
    assert "xfade=transition=fade:" not in fc  # never the true dissolve here
    assert "dissolve" not in fc
