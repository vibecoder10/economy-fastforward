"""Pure-FFmpeg static-documentary render engine (Chunk C7 Part B).

An alternative to render_static.py's Remotion pipeline for the exact same
static_docu format: one still image per scene, held for the narration's
length with a slow Ken Burns pan/zoom, joined by the same transition grammar
Scene.tsx implements. This module does NOT recompute the motion/transition
math — it reads the same ``rc`` (renderConfig) dict render_static.py already
builds via ``_build_render_config`` (ken_burns + transitions + durations), so
the two engines share one source of truth and only differ in how frames get
drawn.

Spec extracted 2026-07-22 from remotion-video/src/Scene.tsx, Main.tsx, and
skills/video-pipeline/render/audio_sync/{ken_burns_calculator,
transition_engine,config}.py:

  * Ken Burns motion: Scene.tsx's DynamicImage applies CSS
    ``transform: scale(s) translate(tx, ty)``. Because CSS composes those
    functions right-to-left on the point (translate happens in local space,
    then the whole thing is scaled), the on-screen pixel displacement is
    ``s * (tx, ty)`` — the offsets in KEN_BURNS_PRESETS (±40 pan, ±30 tilt)
    are defined in *base* 1920x1080 canvas units and get magnified by
    whatever zoom is active that instant. A ±3px / ±1.8px "breathing" wobble
    (``sin(frame * 0.08)``) rides on top of the pan for the entire shot.
      progress(t) = min(t / duration * speed_multiplier, 1)
      speed_multiplier = 11.0 / max(duration, 3.0)   (KEN_BURNS_BASE_DURATION
                                                        / MIN_DISPLAY_SECONDS)
      scale(t)  = start_scale + (end_scale - start_scale) * progress(t)
      tx(t)     = start_x + (end_x - start_x) * progress(t) + 3*sin(f*0.08)
      ty(t)     = start_y + (end_y - start_y) * progress(t) + 1.8*sin(f*0.08)
    render_static._build_render_config already applies the coverage-guarantee
    scale floor (1.08 for pan/tilt scenes, 1.02 for pure-zoom scenes) directly
    onto the ken_burns dict this module reads, so no floor logic is
    duplicated here.

  * Scene timing: Main.tsx places every scene's Sequence back-to-back with
    ZERO overlap (``cumulativeFrames`` is a running total, never reduced for
    a neighbor) and pads every scene's Sequence duration by
    ``SCENE_END_BUFFER_SECONDS = 1`` beyond the render_config
    ``display_duration`` ("Buffer after last spoken word to let audio trail
    off naturally"). So each scene's real on-screen/audio window is
    ``narration_duration + 1.0s``, not narration_duration alone.

  * Transitions: because scenes never overlap in time, there is NEVER a
    moment where two scene images render simultaneously — DynamicImage's own
    opacity curve just fades this image out to the black AbsoluteFill
    background over its transition_out duration, and the next scene
    independently fades in from black over its transition_in duration. So
    "crossfade" (0.4s, same-act) and "dip_to_black" (1.5s, act boundary) are
    the SAME shape (fade through black) and differ ONLY in duration. ffmpeg's
    ``xfade=transition=fadeblack`` (fade-through-black — a DISTINCT named
    xfade transition from plain ``fade``, which is a true cross-dissolve/
    alpha blend and was verified NOT to match here: a red/blue test render
    with ``fade`` produced a visible purple blend frame mid-transition,
    confirming it mixes both clips rather than going through black) is the
    exact match for every one of those types. The first scene fades in from
    black over 1.0s, the last fades to black over 1.0s (Scene.tsx's
    ``fade_from_black`` / ``fade_to_black`` transition types — same
    fade-through-black shape too). A ``cut`` transition type (instant, no
    fade) joins at that boundary via the concat demuxer (stream copy, no
    re-encode) instead of xfade.

    D12-2 adds two more distinct treatments, driven by transition_engine's
    per-shot transition_kind (migration 148) instead of act/style alone:
    ``crossfade`` is now also used (with its own duration) for the
    location_cut and montage kinds — no new join style, the existing
    fade-through-black xfade already covers it, distinguished only by
    duration. ``dissolve`` (the memory kind) IS a new join style: unlike
    every type above, this one genuinely uses plain ``xfade=transition=fade``
    (the true cross-dissolve ruled out for the act/style-only types above) —
    intentional this time, reserved for the one kind that wants a soft blend
    rather than a dip through black. This only affects the ffmpeg engine
    (``STATIC_RENDER_ENGINE=ffmpeg``); Scene.tsx has no true cross-dissolve
    compositing, so on the default Remotion engine a ``dissolve`` type still
    renders as a longer fade-through-black (duration-driven, same as every
    non-cut type) — see Scene.tsx's transInType/transOutType handling.

Engine selection: STATIC_RENDER_ENGINE env var, "remotion" (default) or
"ffmpeg". Concurrency for the parallel per-scene renders: FFMPEG_RENDER_CONCURRENCY
env override, else max(3, cpu_count - 1).
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from pathlib import Path
from typing import Any

from render_stitch import ProgressCb, _emit, _run_subprocess

logger = logging.getLogger(__name__)

# Mirrors Main.tsx's SCENE_END_BUFFER_SECONDS — see module docstring.
SCENE_END_BUFFER_SECONDS = 1.0

# Mirrors Scene.tsx's DynamicImage breathing wobble:
#   const breathe = Math.sin(localFrame * 0.08) * 3;
#   translateX += breathe; translateY += breathe * 0.6;
_BREATHE_FREQ = 0.08
_BREATHE_AMPLITUDE_X = 3.0
_BREATHE_AMPLITUDE_Y = 1.8

_DEFAULT_FPS = 24
_DEFAULT_WIDTH = 1920
_DEFAULT_HEIGHT = 1080
_DEFAULT_CRF = 20
_DEFAULT_PRESET = "veryfast"

# D12-2: join "style" (build_transition_plan's output) -> the xfade
# `transition=` name used to render it. Anything not listed here (i.e. every
# style except "dissolve") uses "fadeblack" — see build_transition_plan and
# build_group_join_filter_complex.
_XFADE_TRANSITION_BY_STYLE = {"dissolve": "fade"}
_DEFAULT_XFADE_TRANSITION = "fadeblack"


def render_engine() -> str:
    """Which engine drives this render: 'remotion' (default) or 'ffmpeg'."""
    value = (os.getenv("STATIC_RENDER_ENGINE") or "remotion").strip().lower()
    return "ffmpeg" if value == "ffmpeg" else "remotion"


def ffmpeg_concurrency() -> int:
    """How many scene segments render in parallel. Same override pattern as
    render_static._remotion_concurrency, separate env var since this bounds
    ffmpeg worker processes rather than Remotion's internal Chrome workers."""
    override = os.getenv("FFMPEG_RENDER_CONCURRENCY")
    if override:
        try:
            n = int(override)
            if n > 0:
                return n
        except ValueError:
            pass
    cores = os.cpu_count() or 3
    return max(3, cores - 1)


# ---------------------------------------------------------------------------
# Pure builders — no I/O, no subprocess. Directly unit-testable.
# ---------------------------------------------------------------------------

def scene_clip_duration(scene: dict[str, Any]) -> float:
    """This scene's real on-screen window: narration length + the trailing
    buffer Main.tsx pads every scene with."""
    return float(scene.get("display_duration") or 0.0) + SCENE_END_BUFFER_SECONDS


def build_zoompan_filter(
    ken_burns: dict[str, Any],
    duration_s: float,
    fps: int = _DEFAULT_FPS,
    width: int = _DEFAULT_WIDTH,
    height: int = _DEFAULT_HEIGHT,
) -> str:
    """The zoompan filter fragment implementing one scene's Ken Burns move.

    Input to this filter must already be a `width`x`height` "cover" image
    (see build_scene_command) — that IS the base 1920x1080 canvas the
    ken_burns offsets are defined against, so the crop-window math below
    needs no extra unit conversion.
    """
    start_scale = float(ken_burns.get("start_scale") or 1.0)
    end_scale = float(ken_burns.get("end_scale") or start_scale)
    start_x = float(ken_burns.get("start_x_offset") or 0.0)
    end_x = float(ken_burns.get("end_x_offset") or 0.0)
    start_y = float(ken_burns.get("start_y_offset") or 0.0)
    end_y = float(ken_burns.get("end_y_offset") or 0.0)
    speed = float(ken_burns.get("speed_multiplier") or 1.0)

    frames_n = max(1, round(duration_s * fps))
    denom = max(frames_n - 1, 1)
    progress = f"min((on/{denom})*({speed}),1)"

    # Every injected literal is parenthesized — without it, a negative
    # offset (e.g. end_x=-40) formats as "...-(-40.0)" => the literal text
    # "--40.0", which is ambiguous to read even though ffmpeg's expression
    # parser does accept it as double unary-minus.
    z_expr = f"({start_scale})+(({end_scale})-({start_scale}))*{progress}"
    tx_expr = (
        f"({start_x})+(({end_x})-({start_x}))*{progress}"
        f"+({_BREATHE_AMPLITUDE_X})*sin(on*({_BREATHE_FREQ}))"
    )
    ty_expr = (
        f"({start_y})+(({end_y})-({start_y}))*{progress}"
        f"+({_BREATHE_AMPLITUDE_Y})*sin(on*({_BREATHE_FREQ}))"
    )

    # Crop-window top-left in the base canvas: center the crop_w/crop_h
    # window, then shift it OPPOSITE the image's translate direction (a
    # positive image-translate reveals the base image's other side), and
    # clamp so the window never samples outside the base canvas (the
    # overscan / "no black edges" guarantee — belt-and-suspenders on top of
    # render_static's scale floor, which already keeps this in range).
    x_expr = f"max(0,min({width}/2-({width}/zoom/2)-({tx_expr}),{width}-{width}/zoom))"
    y_expr = f"max(0,min({height}/2-({height}/zoom/2)-({ty_expr}),{height}-{height}/zoom))"

    return f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':d=1:s={width}x{height}:fps={fps}"


def build_scene_command(
    image_path: Path,
    audio_path: Path,
    out_path: Path,
    ken_burns: dict[str, Any],
    duration_s: float,
    fps: int = _DEFAULT_FPS,
    width: int = _DEFAULT_WIDTH,
    height: int = _DEFAULT_HEIGHT,
    crf: int = _DEFAULT_CRF,
    preset: str = _DEFAULT_PRESET,
) -> list[str]:
    """Full ffmpeg argv rendering ONE scene segment: still + Ken Burns pan
    over its narration audio, padded to duration_s (narration + the 1s
    trailing buffer) with silence so the tail holds instead of getting cut."""
    zoompan = build_zoompan_filter(ken_burns, duration_s, fps=fps, width=width, height=height)
    filter_complex = (
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},{zoompan}[v]"
    )
    return [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(image_path),
        "-i", str(audio_path),
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "1:a",
        "-af", "apad",
        "-t", f"{duration_s:.3f}",
        "-r", str(fps),
        "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        str(out_path),
    ]


def build_transition_plan(scenes: list[dict[str, Any]]) -> dict[str, Any]:
    """One JOIN spec per consecutive scene pair (N-1 total), plus the
    lead-in (first scene) / lead-out (last scene) fade durations.

    Reads the transition_in/transition_out already assigned by
    assign_transitions (skills/video-pipeline) onto each scene — this
    function does not re-derive transition choice, only translates it into
    an ffmpeg join style ("cut" — concat demuxer, no filter edge; "fade" —
    fade-through-black xfade, D12-2's location_cut/montage kinds included,
    distinguished only by duration; "dissolve" — D12-2's memory kind, a true
    cross-dissolve xfade instead of fade-through-black).
    """
    if not scenes:
        return {"joins": [], "lead_in_duration": 0.0, "lead_out_duration": 0.0}

    joins = []
    for i in range(len(scenes) - 1):
        t = scenes[i].get("transition_out") or {}
        ttype = t.get("type", "crossfade")
        if ttype == "cut":
            style = "cut"
        elif ttype == "dissolve":
            style = "dissolve"
        else:
            style = "fade"
        # D12-2: `or 0.4` would silently discard an explicit 0.0 (falsy in
        # Python) — that used to be harmless because no type ever legitimately
        # carried a zero duration, but HARD_CUT_DURATION now does (continuous/
        # time_cut). Explicit None-check preserves it.
        raw_duration = t.get("duration")
        duration = float(raw_duration) if raw_duration is not None else 0.4
        joins.append({"from": i, "to": i + 1, "style": style, "duration": duration})

    lead_in = scenes[0].get("transition_in") or {}
    lead_out = scenes[-1].get("transition_out") or {}
    return {
        "joins": joins,
        "lead_in_duration": float(lead_in.get("duration") or 1.0),
        "lead_out_duration": float(lead_out.get("duration") or 1.0),
    }


def group_by_cuts(plan: dict[str, Any], n_scenes: int) -> list[list[int]]:
    """Partition scene indices into runs connected only by fade joins — a
    'cut' join starts a new group (its two sides get concat-demuxer'd
    together with a stream-copy hard cut instead of an xfade)."""
    if n_scenes <= 0:
        return []
    groups: list[list[int]] = [[0]]
    for join in plan["joins"]:
        if join["style"] == "cut":
            groups.append([join["to"]])
        else:
            groups[-1].append(join["to"])
    return groups


def build_group_join_filter_complex(
    group_indices: list[int],
    durations: list[float],
    joins_by_from: dict[int, dict[str, Any]],
    apply_lead_in: bool,
    lead_in_duration: float,
    apply_lead_out: bool,
    lead_out_duration: float,
) -> tuple[str, str, str]:
    """Build the filter_complex chaining xfade (video) + acrossfade (audio)
    across one group of scenes (all joined by "fade" or "dissolve" style —
    no "cut" joins inside a group; see build_transition_plan/group_by_cuts).
    Each boundary's xfade `transition=` name follows its own join's style
    (D12-2: fadeblack for "fade", true cross-dissolve for "dissolve" — see
    _XFADE_TRANSITION_BY_STYLE); acrossfade is unchanged either way — a
    longer duration alone is what makes the memory kind's audio crossfade
    "gentle". Returns (filter_complex_string, final_video_label, final_audio_label).

    `durations` is indexed by POSITION WITHIN THE GROUP (durations[0] is the
    duration of group_indices[0], etc.) — the caller passes only the group's
    own segment files as ffmpeg inputs (input 0..len(group_indices)-1).
    """
    n = len(group_indices)
    if n == 0:
        raise ValueError("empty group")

    filters: list[str] = []
    if n == 1:
        cur_v, cur_a = "0:v", "0:a"
        running_duration = durations[0]
    else:
        cur_v, cur_a = "0:v", "0:a"
        running_duration = durations[0]
        for pos in range(n - 1):
            scene_idx = group_indices[pos]
            join = joins_by_from[scene_idx]
            d = join["duration"]
            xfade_transition = _XFADE_TRANSITION_BY_STYLE.get(
                join.get("style"), _DEFAULT_XFADE_TRANSITION
            )
            offset = max(0.0, running_duration - d)
            out_v, out_a = f"v{pos}", f"a{pos}"
            filters.append(
                f"[{cur_v}][{pos + 1}:v]xfade=transition={xfade_transition}:duration={d:.3f}:"
                f"offset={offset:.3f}[{out_v}]"
            )
            filters.append(f"[{cur_a}][{pos + 1}:a]acrossfade=d={d:.3f}[{out_a}]")
            cur_v, cur_a = out_v, out_a
            running_duration = running_duration + durations[pos + 1] - d

    final_v, final_a = cur_v, cur_a
    if apply_lead_in or apply_lead_out:
        video_fade_parts = []
        if apply_lead_in:
            video_fade_parts.append(f"fade=t=in:st=0:d={lead_in_duration:.3f}")
        if apply_lead_out:
            fade_start = max(0.0, running_duration - lead_out_duration)
            video_fade_parts.append(f"fade=t=out:st={fade_start:.3f}:d={lead_out_duration:.3f}")
        filters.append(f"[{final_v}]{','.join(video_fade_parts)}[vout]")
        final_v = "vout"
        # Audio fade mirrors the video fade-through-black so narration doesn't
        # hard-cut against silence at the very start/end of the whole video.
        audio_fade_parts = []
        if apply_lead_in:
            audio_fade_parts.append(f"afade=t=in:st=0:d={lead_in_duration:.3f}")
        if apply_lead_out:
            fade_start = max(0.0, running_duration - lead_out_duration)
            audio_fade_parts.append(f"afade=t=out:st={fade_start:.3f}:d={lead_out_duration:.3f}")
        filters.append(f"[{final_a}]{','.join(audio_fade_parts)}[aout]")
        final_a = "aout"

    return ";".join(filters), final_v, final_a


# ---------------------------------------------------------------------------
# Async orchestration — real subprocess execution.
# ---------------------------------------------------------------------------

async def _render_one_scene(
    scene: dict[str, Any], public_dir: Path, segdir: Path, sem: asyncio.Semaphore,
    fps: int, width: int, height: int,
) -> Path:
    image_path = public_dir / scene["image_path"]
    audio_path = public_dir / f"Scene {scene['scene_number']}.mp3"
    out_path = segdir / f"seg_{scene['scene_number']:04d}.mp4"
    duration_s = scene_clip_duration(scene)
    cmd = build_scene_command(
        image_path, audio_path, out_path, scene.get("ken_burns") or {}, duration_s,
        fps=fps, width=width, height=height,
    )
    async with sem:
        rc, err = await _run_subprocess(cmd)
    if rc != 0 or not out_path.exists() or out_path.stat().st_size == 0:
        raise RuntimeError(
            f"ffmpeg scene render failed for scene {scene['scene_number']} "
            f"(exit {rc}): {err[-600:]}"
        )
    return out_path


async def _join_group(
    group_indices: list[int], scene_files: list[Path], durations: list[float],
    plan: dict[str, Any], out_path: Path, is_first_group: bool, is_last_group: bool,
    fps: int,
) -> None:
    joins_by_from = {j["from"]: j for j in plan["joins"]}
    filter_complex, v_label, a_label = build_group_join_filter_complex(
        group_indices,
        durations,
        joins_by_from,
        apply_lead_in=is_first_group,
        lead_in_duration=plan["lead_in_duration"],
        apply_lead_out=is_last_group,
        lead_out_duration=plan["lead_out_duration"],
    )
    cmd = ["ffmpeg", "-y"]
    for p in scene_files:
        cmd += ["-i", str(p)]
    cmd += [
        "-filter_complex", filter_complex,
        "-map", f"[{v_label}]", "-map", f"[{a_label}]",
        "-r", str(fps),
        "-c:v", "libx264", "-preset", _DEFAULT_PRESET, "-crf", str(_DEFAULT_CRF),
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        str(out_path),
    ]
    rc, err = await _run_subprocess(cmd)
    if rc != 0 or not out_path.exists() or out_path.stat().st_size == 0:
        raise RuntimeError(f"ffmpeg group join failed (exit {rc}): {err[-600:]}")


async def _concat_groups(group_files: list[Path], out_path: Path, workdir: Path) -> None:
    if len(group_files) == 1:
        shutil.move(str(group_files[0]), str(out_path))
        return
    list_file = workdir / "concat_list.txt"
    list_file.write_text(
        "\n".join(f"file '{p.resolve()}'" for p in group_files) + "\n"
    )
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-c", "copy", str(out_path),
    ]
    rc, err = await _run_subprocess(cmd)
    if rc != 0 or not out_path.exists() or out_path.stat().st_size == 0:
        raise RuntimeError(f"ffmpeg concat-groups failed (exit {rc}): {err[-600:]}")


async def render_static_ffmpeg_video(
    rc: dict[str, Any], public_dir: Path, workdir: Path, out_file: Path,
    on_progress: ProgressCb = None,
) -> None:
    """Render the whole static-documentary video via the pure-ffmpeg engine.

    Mirrors _run_remotion's contract: writes the finished mp4 to out_file,
    raises RuntimeError with a user-explainable message on failure.
    """
    scenes = rc.get("scenes") or []
    if not scenes:
        raise RuntimeError("render_static_ffmpeg_video: renderConfig has no scenes")
    fps = int(rc.get("fps") or _DEFAULT_FPS)
    resolution = rc.get("resolution") or {}
    width = int(resolution.get("width") or _DEFAULT_WIDTH)
    height = int(resolution.get("height") or _DEFAULT_HEIGHT)

    segdir = workdir / "segments"
    segdir.mkdir(exist_ok=True)

    sem = asyncio.Semaphore(ffmpeg_concurrency())
    await _emit(on_progress, f"Rendering {len(scenes)} scene segments (ffmpeg, parallel)")
    scene_files = await asyncio.gather(*[
        _render_one_scene(scene, public_dir, segdir, sem, fps, width, height)
        for scene in scenes
    ])
    durations = [scene_clip_duration(s) for s in scenes]

    plan = build_transition_plan(scenes)
    groups = group_by_cuts(plan, len(scenes))

    await _emit(on_progress, f"Joining {len(groups)} segment group(s)")
    group_files: list[Path] = []
    for gi, group in enumerate(groups):
        group_files_in = [scene_files[i] for i in group]
        group_durations = [durations[i] for i in group]
        group_out = segdir / f"group_{gi:03d}.mp4"
        await _join_group(
            group, group_files_in, group_durations, plan, group_out,
            is_first_group=(gi == 0), is_last_group=(gi == len(groups) - 1),
            fps=fps,
        )
        group_files.append(group_out)

    await _emit(on_progress, "Concatenating segment groups")
    await _concat_groups(group_files, out_file, workdir)

    if not out_file.exists() or out_file.stat().st_size == 0:
        raise RuntimeError("ffmpeg engine finished but produced no output file")
