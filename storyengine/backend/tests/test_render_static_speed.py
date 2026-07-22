"""Chunk C7 — static-docu render speed (2026-07-22).

Part A: dynamic Remotion concurrency (cores-1, floor 3, REMOTION_CONCURRENCY
override) + faster encoder settings (crf 20, x264-preset veryfast).

Part B: a pure-ffmpeg alternative render engine for the same static_docu
format (render_static_ffmpeg.py) — engine selection, per-scene ffmpeg command
construction (zoompan Ken Burns), and the join plan (xfade+acrossfade
fade-through-black chain / concat-demuxer fallback for hard cuts).

All tests here are structural/stubbed: they assert on constructed command
lists and filter-graph strings, never actually invoke ffmpeg/remotion/Chrome.
Real ffmpeg execution was verified manually during development (real
zoompan renders + real xfade joins, frame-sampled) — see the chunk report.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import render_static  # noqa: E402
import render_static_ffmpeg as rsf  # noqa: E402


# ---------------------------------------------------------------------------
# Part A: Remotion concurrency + encoder flags
# ---------------------------------------------------------------------------

def test_remotion_concurrency_defaults_to_cores_minus_one(monkeypatch):
    monkeypatch.delenv("REMOTION_CONCURRENCY", raising=False)
    monkeypatch.setattr(render_static.os, "cpu_count", lambda: 8)
    assert render_static._remotion_concurrency() == 7


def test_remotion_concurrency_floors_at_three_on_small_boxes(monkeypatch):
    monkeypatch.delenv("REMOTION_CONCURRENCY", raising=False)
    monkeypatch.setattr(render_static.os, "cpu_count", lambda: 2)
    assert render_static._remotion_concurrency() == 3


def test_remotion_concurrency_env_override_wins(monkeypatch):
    monkeypatch.setenv("REMOTION_CONCURRENCY", "5")
    monkeypatch.setattr(render_static.os, "cpu_count", lambda: 16)
    assert render_static._remotion_concurrency() == 5


def test_remotion_concurrency_ignores_garbage_override(monkeypatch):
    monkeypatch.setenv("REMOTION_CONCURRENCY", "not-a-number")
    monkeypatch.setattr(render_static.os, "cpu_count", lambda: 8)
    assert render_static._remotion_concurrency() == 7


@pytest.mark.asyncio
async def test_run_remotion_command_has_dynamic_concurrency_and_fast_encode(monkeypatch, tmp_path):
    monkeypatch.delenv("REMOTION_CONCURRENCY", raising=False)
    monkeypatch.setattr(render_static.os, "cpu_count", lambda: 6)

    captured = {}

    class FakeStdout:
        async def readline(self):
            return b""

    class FakeProc:
        stdout = FakeStdout()

        async def wait(self):
            return 0

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        captured["cmd"] = cmd
        return FakeProc()

    monkeypatch.setattr(render_static.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    out_file = tmp_path / "out.mp4"
    out_file.write_bytes(b"fake")
    await render_static._run_remotion(tmp_path, tmp_path / "props.json", out_file, None)

    cmd = captured["cmd"]
    assert "--concurrency=5" in cmd  # cores(6) - 1
    assert "--crf=20" in cmd
    assert "--x264-preset=veryfast" in cmd


# ---------------------------------------------------------------------------
# Part B: engine selection
# ---------------------------------------------------------------------------

def test_render_engine_defaults_to_remotion(monkeypatch):
    monkeypatch.delenv("STATIC_RENDER_ENGINE", raising=False)
    assert rsf.render_engine() == "remotion"


def test_render_engine_selects_ffmpeg(monkeypatch):
    monkeypatch.setenv("STATIC_RENDER_ENGINE", "ffmpeg")
    assert rsf.render_engine() == "ffmpeg"


def test_render_engine_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("STATIC_RENDER_ENGINE", "FFmpeg")
    assert rsf.render_engine() == "ffmpeg"


def test_render_engine_falls_back_on_unrecognized_value(monkeypatch):
    monkeypatch.setenv("STATIC_RENDER_ENGINE", "some-typo")
    assert rsf.render_engine() == "remotion"


def test_ffmpeg_concurrency_default_cores_minus_one(monkeypatch):
    monkeypatch.delenv("FFMPEG_RENDER_CONCURRENCY", raising=False)
    monkeypatch.setattr(rsf.os, "cpu_count", lambda: 10)
    assert rsf.ffmpeg_concurrency() == 9


def test_ffmpeg_concurrency_floors_at_three(monkeypatch):
    monkeypatch.delenv("FFMPEG_RENDER_CONCURRENCY", raising=False)
    monkeypatch.setattr(rsf.os, "cpu_count", lambda: 1)
    assert rsf.ffmpeg_concurrency() == 3


def test_ffmpeg_concurrency_env_override(monkeypatch):
    monkeypatch.setenv("FFMPEG_RENDER_CONCURRENCY", "4")
    monkeypatch.setattr(rsf.os, "cpu_count", lambda: 32)
    assert rsf.ffmpeg_concurrency() == 4


# ---------------------------------------------------------------------------
# Part B: scene duration (SCENE_END_BUFFER_SECONDS parity with Main.tsx)
# ---------------------------------------------------------------------------

def test_scene_clip_duration_adds_trailing_buffer():
    scene = {"display_duration": 5.5}
    assert rsf.scene_clip_duration(scene) == pytest.approx(6.5)


def test_scene_clip_duration_handles_missing_duration():
    assert rsf.scene_clip_duration({}) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Part B: zoompan filter construction (Ken Burns)
# ---------------------------------------------------------------------------

def test_zoompan_filter_has_expected_structure():
    kb = {
        "direction": "slow_zoom_in", "start_scale": 1.02, "end_scale": 1.15,
        "speed_multiplier": 1.375,
    }
    f = rsf.build_zoompan_filter(kb, duration_s=8.0, fps=24, width=1920, height=1080)
    assert f.startswith("zoompan=")
    assert "d=1" in f
    assert "s=1920x1080" in f
    assert "fps=24" in f
    assert "1.02" in f and "1.15" in f
    assert "1.375" in f
    # breathing wobble present
    assert "sin(on*(0.08))" in f
    # frames_n = round(8.0*24) = 192, denom = 191
    assert "/191" in f


def test_zoompan_filter_never_emits_ambiguous_double_minus():
    """A negative end offset (pan preset) used to format as '-(-40.0)' =>
    literal '--40.0' in the expression string. Every literal must be
    parenthesized so this never appears."""
    kb = {
        "direction": "slow_pan_left", "start_scale": 1.08, "end_scale": 1.08,
        "start_x_offset": 40, "end_x_offset": -40, "speed_multiplier": 1.0,
    }
    f = rsf.build_zoompan_filter(kb, duration_s=5.0, fps=24)
    assert "--" not in f


def test_zoompan_filter_clamps_crop_window_in_bounds():
    kb = {"direction": "slow_tilt_up", "start_scale": 1.08, "end_scale": 1.08,
          "start_y_offset": 30, "end_y_offset": -30, "speed_multiplier": 1.0}
    f = rsf.build_zoompan_filter(kb, duration_s=4.0)
    assert "max(0,min(" in f  # both x and y expressions are clamped


def test_zoompan_filter_defaults_when_ken_burns_sparse():
    """A ken_burns dict missing scale/offset keys (e.g. a bare direction with
    no floor applied yet) must not raise — defaults to a static (scale=1,
    no pan) shot rather than crashing the render."""
    f = rsf.build_zoompan_filter({}, duration_s=3.0)
    assert "zoompan=" in f


# ---------------------------------------------------------------------------
# Part B: per-scene ffmpeg command construction
# ---------------------------------------------------------------------------

def test_build_scene_command_structure(tmp_path):
    kb = {"start_scale": 1.02, "end_scale": 1.15, "speed_multiplier": 1.0}
    cmd = rsf.build_scene_command(
        tmp_path / "img.png", tmp_path / "aud.mp3", tmp_path / "out.mp4",
        kb, duration_s=6.0,
    )
    assert cmd[0] == "ffmpeg"
    assert "-loop" in cmd and cmd[cmd.index("-loop") + 1] == "1"
    assert str(tmp_path / "img.png") in cmd
    assert str(tmp_path / "aud.mp3") in cmd
    assert "-t" in cmd and cmd[cmd.index("-t") + 1] == "6.000"
    assert "-r" in cmd and cmd[cmd.index("-r") + 1] == "24"
    assert "-af" in cmd and cmd[cmd.index("-af") + 1] == "apad"
    assert "-c:v" in cmd and cmd[cmd.index("-c:v") + 1] == "libx264"
    assert "-preset" in cmd and cmd[cmd.index("-preset") + 1] == "veryfast"
    assert "-crf" in cmd and cmd[cmd.index("-crf") + 1] == "20"
    assert "-pix_fmt" in cmd and cmd[cmd.index("-pix_fmt") + 1] == "yuv420p"
    assert str(tmp_path / "out.mp4") == cmd[-1]
    # exactly one -filter_complex, and it references zoompan
    assert cmd.count("-filter_complex") == 1
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "zoompan=" in fc
    assert "[0:v]scale=1920:1080" in fc


def test_build_scene_command_uses_scene_resolution(tmp_path):
    kb = {"start_scale": 1.0, "end_scale": 1.0, "speed_multiplier": 1.0}
    cmd = rsf.build_scene_command(
        tmp_path / "img.png", tmp_path / "aud.mp3", tmp_path / "out.mp4",
        kb, duration_s=4.0, width=1080, height=1920,
    )
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "1080:1920" in fc
    assert "s=1080x1920" in fc


# ---------------------------------------------------------------------------
# Part B: transition plan (mirrors assign_transitions' output)
# ---------------------------------------------------------------------------

def _sample_scenes():
    return [
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


def test_transition_plan_maps_crossfade_and_dip_to_fade_style():
    plan = rsf.build_transition_plan(_sample_scenes())
    assert len(plan["joins"]) == 2
    assert plan["joins"][0] == {"from": 0, "to": 1, "style": "fade", "duration": 0.4}
    assert plan["joins"][1] == {"from": 1, "to": 2, "style": "fade", "duration": 1.5}
    assert plan["lead_in_duration"] == pytest.approx(1.0)
    assert plan["lead_out_duration"] == pytest.approx(1.0)


def test_transition_plan_maps_cut_type_distinctly():
    scenes = _sample_scenes()
    scenes[0]["transition_out"] = {"type": "cut", "duration": 0.0}
    plan = rsf.build_transition_plan(scenes)
    assert plan["joins"][0]["style"] == "cut"
    assert plan["joins"][1]["style"] == "fade"


def test_transition_plan_empty_scenes():
    plan = rsf.build_transition_plan([])
    assert plan["joins"] == []


def test_group_by_cuts_single_group_when_no_cuts():
    scenes = _sample_scenes()
    plan = rsf.build_transition_plan(scenes)
    groups = rsf.group_by_cuts(plan, len(scenes))
    assert groups == [[0, 1, 2]]


def test_group_by_cuts_splits_on_cut_boundary():
    scenes = _sample_scenes()
    scenes[0]["transition_out"] = {"type": "cut", "duration": 0.0}
    plan = rsf.build_transition_plan(scenes)
    groups = rsf.group_by_cuts(plan, len(scenes))
    assert groups == [[0], [1, 2]]


def test_group_by_cuts_all_cuts_makes_singleton_groups():
    scenes = _sample_scenes()
    scenes[0]["transition_out"] = {"type": "cut", "duration": 0.0}
    scenes[1]["transition_out"] = {"type": "cut", "duration": 0.0}
    plan = rsf.build_transition_plan(scenes)
    groups = rsf.group_by_cuts(plan, len(scenes))
    assert groups == [[0], [1], [2]]


# ---------------------------------------------------------------------------
# Part B: join filter_complex (xfade + acrossfade chain, fadeblack transition)
# ---------------------------------------------------------------------------

def test_join_filter_complex_uses_fadeblack_never_dissolve_or_plain_fade():
    scenes = _sample_scenes()
    plan = rsf.build_transition_plan(scenes)
    durations = [rsf.scene_clip_duration(s) for s in scenes]
    joins_by_from = {j["from"]: j for j in plan["joins"]}
    fc, v, a = rsf.build_group_join_filter_complex(
        [0, 1, 2], durations, joins_by_from,
        apply_lead_in=True, lead_in_duration=plan["lead_in_duration"],
        apply_lead_out=True, lead_out_duration=plan["lead_out_duration"],
    )
    assert fc.count("xfade=transition=fadeblack") == 2  # N-1 joins for 3 scenes
    assert "dissolve" not in fc
    assert "transition=fade:" not in fc  # never the plain (dissolve-like) fade
    assert fc.count("acrossfade") == 2
    assert v == "vout" and a == "aout"
    assert "fade=t=in:st=0:d=1.000" in fc
    assert "afade=t=in:st=0:d=1.000" in fc


def test_join_filter_complex_offsets_match_cumulative_duration_minus_transition():
    scenes = _sample_scenes()
    plan = rsf.build_transition_plan(scenes)
    durations = [rsf.scene_clip_duration(s) for s in scenes]  # [6.0, 9.0, 7.0]
    joins_by_from = {j["from"]: j for j in plan["joins"]}
    fc, _, _ = rsf.build_group_join_filter_complex(
        [0, 1, 2], durations, joins_by_from,
        apply_lead_in=False, lead_in_duration=0.0,
        apply_lead_out=False, lead_out_duration=0.0,
    )
    # First join: offset = duration[0] - join_duration = 6.0 - 0.4 = 5.6
    assert "offset=5.600" in fc
    # Second join: running = 6.0 + 9.0 - 0.4 = 14.6; offset = 14.6 - 1.5 = 13.1
    assert "offset=13.100" in fc


def test_join_filter_complex_single_scene_group_applies_only_lead_fades():
    fc, v, a = rsf.build_group_join_filter_complex(
        [0], [5.0], {},
        apply_lead_in=True, lead_in_duration=1.0,
        apply_lead_out=True, lead_out_duration=1.0,
    )
    assert "xfade" not in fc
    assert "acrossfade" not in fc
    assert "fade=t=in:st=0:d=1.000" in fc
    assert "fade=t=out:st=4.000:d=1.000" in fc  # 5.0 - 1.0
    assert v == "vout" and a == "aout"


def test_join_filter_complex_no_lead_fades_when_not_first_or_last_group():
    fc, v, a = rsf.build_group_join_filter_complex(
        [1], [5.0], {},
        apply_lead_in=False, lead_in_duration=1.0,
        apply_lead_out=False, lead_out_duration=1.0,
    )
    assert "fade=" not in fc
    assert v == "0:v" and a == "0:a"
