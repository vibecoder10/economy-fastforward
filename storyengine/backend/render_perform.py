"""Performance-track assembler — the final render for character-dialogue videos.

A hybrid dialogue video (``videos.dialogue_mode = 'character_dialogue'`` with
``dialogue_audio = 'voice_over'``) has three finished pieces and, until now,
nothing joining them: per-segment audio in ``scripts.dialogue_segments``
(narrator teaching + each character line, voiced by dialogue_voice.py), and
lip-synced speaking clips whose line was muxed in at generation time
(clip_dialogue.mux_voice, ``DIALOGUE_VOICE_LEAD_SECONDS`` of lead-in).

The assembler builds ONE audio track per scene by laying the segments end to
end in story order (narrator seg -> Marco line -> narrator seg -> ...), then
times every shot to its segment's span on that clock:

  * a SPEAKING shot's window covers exactly its line(s) — the mouth matches
    because the talking clip was generated FROM that same audio, and the
    dialogue head-pad here equals the mux lead-in there;
  * NARRATION shots subdivide the narrator time between two speaking windows
    proportionally to their sentence word counts (same idea as the legacy
    Whisper sync, but the clock is the known per-segment durations — no
    transcription pass).

Every clip plays MUTED (Ryan's call): the assembled track carries every voice,
and the speaking clips' baked-in copy of the line must not double it.

The timeline math is pure (``build_timeline``) so it's unit-testable; the
ffmpeg work reuses render_stitch's plumbing and encode parameters. Each shot
is cut/held to its window in its own encode, the scene is joined stream-copy,
and the scene track is muxed over it — so all render paths (per-scene preview,
final render) share one implementation.

Public entries:
    await assemble_scene(video_id, tenant_id, scene, ...) -> dict
    await render_performance_video(video_id, tenant_id, ...) -> dict
"""

import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from database import fetch_all
from storage import upload_bytes, download_bytes
from clip_dialogue import DIALOGUE_VOICE_LEAD_SECONDS, download_voice, norm
from render_stitch import (
    ProgressCb,
    _FFMPEG_SEM,
    _choose_target,
    _download_clips,
    _emit,
    _probe_duration,
    _run_subprocess,
    _safe_filename,
)

# The head-pad a dialogue segment gets on the assembled clock. MUST mirror the
# lead clip_dialogue.mux_voice gave the line inside the speaking clip — the
# window starts when the clip does, so equal pads keep mouth and track aligned.
DIALOGUE_HEAD_SECONDS = DIALOGUE_VOICE_LEAD_SECONDS
# A beat after a line before the narrator comes back in.
DIALOGUE_TAIL_SECONDS = float(os.getenv("PERFORM_DIALOGUE_TAIL", "0.25"))
# A narration shot shorter than this reads as a glitch — drop shots from an
# over-crowded narration block instead of machine-gunning them.
MIN_SHOT_SECONDS = float(os.getenv("PERFORM_MIN_SHOT", "0.8"))

# assigned_dialogue is written by coverage as: Speaker: "line"
_ASSIGNED_RE = re.compile(r'^\s*(?P<speaker>[^:"]{1,80}):\s*"(?P<line>.+)"\s*$', re.DOTALL)


# ── pure timeline math ────────────────────────────────────────────────────────

def build_segment_spans(segments: list) -> list[dict]:
    """Lay the segments end to end on one clock.

    Returns one span per segment: {index, type, speaker, text, audio_url,
    duration, start, end, audio_at}. Dialogue spans include the head/tail pads
    (audio_at = start + head); a segment with no audio or no duration gets a
    zero-length span so indexes stay aligned.
    """
    spans: list[dict] = []
    t = 0.0
    for i, seg in enumerate(segments or []):
        dur = float(seg.get("duration") or 0)
        url = seg.get("audio_url")
        is_dialogue = seg.get("type") == "dialogue"
        if not url or dur <= 0:
            spans.append({"index": i, "type": seg.get("type"), "speaker": seg.get("speaker"),
                          "text": seg.get("text") or "", "audio_url": None, "duration": 0.0,
                          "start": t, "end": t, "audio_at": t})
            continue
        start = t
        audio_at = start + (DIALOGUE_HEAD_SECONDS if is_dialogue else 0.0)
        end = audio_at + dur + (DIALOGUE_TAIL_SECONDS if is_dialogue else 0.0)
        spans.append({"index": i, "type": seg.get("type"), "speaker": seg.get("speaker"),
                      "text": seg.get("text") or "", "audio_url": url, "duration": dur,
                      "start": round(start, 3), "end": round(end, 3),
                      "audio_at": round(audio_at, 3)})
        t = end
    return spans


def _line_matches_span(line_text: str, span: dict) -> bool:
    """A claimed line covers a dialogue span when either text contains the
    other, or any 3+ word sentence of the span appears in the line (a coverage
    master can carry several merged turns in one assigned line)."""
    lt, st = norm(line_text), norm(span.get("text"))
    if not lt or not st:
        return False
    if st in lt or lt in st:
        return True
    for sent in re.split(r"[.!?…]+", span.get("text") or ""):
        ns = norm(sent)
        if ns and len(ns.split()) >= 3 and ns in lt:
            return True
    return False


def match_speaking_shots(shots: list, spans: list) -> dict:
    """shot list-position -> ordered dialogue span indexes it performs.

    Pass 1 claims via assets.assigned_dialogue (coverage writes the exact
    spoken line onto the master frame — migration 065); pass 2 falls back to
    sentence_text containment for pre-065 rows. hero_shot rows claim first so
    an angle cutaway that shares the moment summary never steals the master's
    line. Each span is claimed once.
    """
    dialogue_spans = [s for s in spans if s["type"] == "dialogue" and s["duration"] > 0]
    claimed: set[int] = set()
    result: dict[int, list[int]] = {}

    def _claim(pos: int, line_text: str, speaker: Optional[str]) -> None:
        got = []
        for sp in dialogue_spans:
            if sp["index"] in claimed:
                continue
            if speaker and norm(speaker) and norm(sp.get("speaker")) != norm(speaker):
                continue
            if _line_matches_span(line_text, sp):
                got.append(sp["index"])
                claimed.add(sp["index"])
        if got:
            result.setdefault(pos, []).extend(got)

    ordered = sorted(range(len(shots)),
                     key=lambda p: (not shots[p].get("hero_shot"), p))
    for pos in ordered:
        assigned = (shots[pos].get("assigned_dialogue") or "").strip()
        m = _ASSIGNED_RE.match(assigned)
        if m:
            _claim(pos, m.group("line"), m.group("speaker"))
    for pos in ordered:
        if pos in result or (shots[pos].get("assigned_dialogue") or "").strip():
            continue
        text = shots[pos].get("sentence_text") or ""
        if text:
            _claim(pos, text, None)
    return {pos: sorted(idxs) for pos, idxs in result.items()}


def build_timeline(segments: list, shots: list) -> dict:
    """The scene's performance timeline.

    segments: scripts.dialogue_segments (ordered). shots: the scene's assets
    rows WITH clips, ordered by image_index — each needs sentence_text,
    assigned_dialogue, hero_shot.

    Returns {entries, placements, total, warnings}:
      entries    — ordered [{shot, start, end, duration, speaking}]
      placements — [(audio_url, audio_at)] for the scene track
      total      — scene length in seconds (== the assembled track's length)
    """
    warnings: list[str] = []
    spans = build_segment_spans(segments)
    total = spans[-1]["end"] if spans else 0.0
    placements = [(s["audio_url"], s["audio_at"]) for s in spans if s["audio_url"]]
    if not placements or total <= 0:
        return {"entries": [], "placements": [], "total": 0.0,
                "warnings": ["no voiced segments — run the voiceover step first"]}

    speaking = match_speaking_shots(shots, spans)
    span_by_index = {s["index"]: s for s in spans}

    unclaimed = [s for s in spans if s["type"] == "dialogue" and s["duration"] > 0
                 and not any(s["index"] in idxs for idxs in speaking.values())]
    for s in unclaimed:
        warnings.append(
            f"line '{(s.get('text') or '')[:40]}' has no speaking clip — "
            "it plays over narration shots")

    entries: list[dict] = []

    # Speaking windows span the shot's first claimed line to its last — a
    # merged same-speaker master covers any narration between its turns too
    # (known format follow-up; the mouth is doing both lines back to back).
    for pos, idxs in speaking.items():
        start = span_by_index[idxs[0]]["start"]
        end = span_by_index[idxs[-1]]["end"]
        entries.append({"shot": shots[pos], "start": start, "end": end,
                        "speaking": True})

    # Narration blocks: consecutive non-speaking shots between two speaking
    # shots (in list order) share the clock between those windows.
    windows_by_pos = {pos: (span_by_index[idxs[0]]["start"], span_by_index[idxs[-1]]["end"])
                      for pos, idxs in speaking.items()}
    speaking_positions = sorted(windows_by_pos)
    if speaking_positions != sorted(speaking_positions, key=lambda p: windows_by_pos[p][0]):
        warnings.append("speaking shots out of story order — timeline follows the audio order")

    blocks: list[tuple[float, float, list[int]]] = []
    run: list[int] = []
    prev_end = 0.0
    for pos in range(len(shots)):
        if pos in windows_by_pos:
            next_start = windows_by_pos[pos][0]
            if run or next_start > prev_end + 0.01:
                blocks.append((prev_end, next_start, run))
            prev_end = windows_by_pos[pos][1]
            run = []
        else:
            run.append(pos)
    if run or total > prev_end + 0.01:
        blocks.append((prev_end, total, run))

    for b_start, b_end, positions in blocks:
        block = b_end - b_start
        if not positions:
            continue  # gap with no shots — the neighbor window stretches over it
        if block <= 0.05:
            warnings.append(
                f"{len(positions)} narration shot(s) fall between adjacent lines "
                "with no narration time — dropped")
            continue
        keep = positions
        max_fit = max(1, int(block / MIN_SHOT_SECONDS))
        if len(keep) > max_fit:
            warnings.append(
                f"narration block of {block:.1f}s can't fit {len(keep)} shots — "
                f"keeping the first {max_fit}")
            keep = keep[:max_fit]
        weights = [max(1, len((shots[p].get("sentence_text") or "").split())) for p in keep]
        wsum = float(sum(weights))
        t = b_start
        acc = 0.0
        for k, p in enumerate(keep):
            acc += weights[k]
            end = b_end if k == len(keep) - 1 else b_start + block * (acc / wsum)
            entries.append({"shot": shots[p], "start": round(t, 3),
                            "end": round(end, 3), "speaking": False})
            t = end

    entries.sort(key=lambda e: e["start"])
    if not entries:
        return {"entries": [], "placements": placements, "total": total,
                "warnings": warnings + ["no shots matched the timeline"]}

    # Normalize to one gapless monotonic strip covering [0, total]: stretch
    # into gaps (a frozen last frame beats black), shrink overlaps. An entry
    # squeezed to nothing is dropped and the strip re-normalized, so the video
    # length always equals the track length exactly.
    while True:
        entries[0]["start"] = 0.0
        for i in range(len(entries) - 1):
            entries[i]["end"] = entries[i + 1]["start"]
        entries[-1]["end"] = total
        kept = [e for e in entries if e["end"] - e["start"] > 0.05]
        if len(kept) == len(entries) or not kept:
            entries = kept
            break
        entries = kept
    for e in entries:
        e["duration"] = round(e["end"] - e["start"], 3)

    return {"entries": entries, "placements": placements, "total": round(total, 3),
            "warnings": warnings}


# ── ffmpeg assembly ───────────────────────────────────────────────────────────

_X264 = ["-c:v", "libx264", "-preset", os.getenv("STITCH_X264_PRESET", "veryfast"),
         "-crf", os.getenv("STITCH_X264_CRF", "20"), "-pix_fmt", "yuv420p",
         "-video_track_timescale", "24000"]
_FPS = os.getenv("STITCH_FPS", "24")


async def _download_audio(url: str, dest: Path) -> None:
    data = await download_voice(url)
    if data is None:
        data = await download_bytes(url)
    if not data:
        raise RuntimeError(f"segment audio downloaded empty: {url[:100]}")
    dest.write_bytes(data)


async def _build_scene_track(placements: list, total: float, workdir: Path) -> Path:
    """One audio file for the scene: every segment MP3 at its placed offset
    over a silent base. amix normalize=0 keeps each voice at its own level."""
    files: list[Path] = []
    for i, (url, _at) in enumerate(placements):
        p = workdir / f"seg_{i:03d}.mp3"
        await _download_audio(url, p)
        files.append(p)

    out = workdir / "scene_track.m4a"
    inputs: list[str] = []
    parts: list[str] = []
    labels: list[str] = []
    for i, (p, (_url, at)) in enumerate(zip(files, placements)):
        inputs += ["-i", str(p)]
        ms = int(round(max(0.0, at) * 1000))
        parts.append(f"[{i}:a]aresample=48000,"
                     f"aformat=sample_fmts=fltp:channel_layouts=stereo,"
                     f"adelay={ms}:all=1[s{i}]")
        labels.append(f"[s{i}]")
    n = len(files)
    parts.append(
        f"anullsrc=r=48000:cl=stereo:d={total:.3f}[base];"
        + "[base]" + "".join(labels)
        + f"amix=inputs={n + 1}:duration=first:normalize=0[a]"
    )
    script = workdir / "track_graph.txt"
    script.write_text(";".join(parts))
    async with _FFMPEG_SEM:
        rc, err = await _run_subprocess(
            ["ffmpeg", "-y", *inputs, "-filter_complex_script", str(script),
             "-map", "[a]", "-c:a", "aac", "-ar", "48000", "-b:a", "192k", str(out)])
    if rc != 0 or not out.exists() or await _probe_duration(str(out)) <= 0:
        raise RuntimeError(f"scene track build failed (rc={rc}): {err[-400:]}")
    return out


async def _cut_shot(src: Path, duration: float, tw: int, th: int, out: Path) -> None:
    """Normalize a clip onto the canvas and hold it to EXACTLY `duration`:
    trimmed if long, last frame frozen (tpad clone) if short. Audio dropped —
    the scene track carries every voice."""
    vf = (f"scale={tw}:{th}:force_original_aspect_ratio=decrease,"
          f"pad={tw}:{th}:-1:-1:color=black,setsar=1,fps={_FPS},format=yuv420p,"
          f"tpad=stop_mode=clone:stop_duration={duration:.3f},"
          f"trim=duration={duration:.3f}")
    async with _FFMPEG_SEM:
        rc, err = await _run_subprocess(
            ["ffmpeg", "-y", "-i", str(src), "-vf", vf, "-an", *_X264, str(out)])
    if rc != 0 or not out.exists() or out.stat().st_size == 0:
        raise RuntimeError(f"shot cut failed (rc={rc}): {err[-400:]}")


async def _concat_copy(parts: list[Path], out: Path, workdir: Path) -> None:
    """Join identically-encoded parts stream-copy via the concat demuxer."""
    lst = workdir / f"{out.stem}_list.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in parts))
    async with _FFMPEG_SEM:
        rc, err = await _run_subprocess(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
             "-c", "copy", "-movflags", "+faststart", str(out)])
    if rc != 0 or not out.exists() or await _probe_duration(str(out)) <= 0:
        raise RuntimeError(f"concat failed (rc={rc}): {err[-400:]}")


async def _load_scene_inputs(video_id: str, tenant_id, scene: int) -> tuple[list, list]:
    """(segments, shots-with-clips) for one scene, or raises with a clear next
    step. Shots are ordered by image_index — the story order coverage wrote."""
    seg_row = await fetch_all(
        "SELECT dialogue_segments FROM scripts "
        "WHERE video_id = $1 AND tenant_id = $2 AND scene = $3",
        video_id, tenant_id, scene)
    raw = seg_row[0].get("dialogue_segments") if seg_row else None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = None
    if not raw:
        raise ValueError(
            f"Scene {scene} has no dialogue segments — create the voiceover first.")
    missing = [s for s in raw if (s.get("text") or "").strip()
               and not (s.get("audio_url") and s.get("duration"))]
    if missing:
        raise ValueError(
            f"Scene {scene} has {len(missing)} unvoiced segment(s) — "
            "create the voiceover first.")

    shots = await fetch_all(
        "SELECT id, scene, image_index, sentence_text, assigned_dialogue, hero_shot, "
        "video_clip_url, video_duration FROM assets "
        "WHERE video_id = $1 AND tenant_id = $2 AND scene = $3 "
        "AND video_clip_url IS NOT NULL ORDER BY image_index",
        video_id, tenant_id, scene)
    if not shots:
        raise ValueError(f"No clips in scene {scene} — animate it first.")
    return raw, [dict(r) for r in shots]


async def _assemble_scene_file(
    video_id: str, tenant_id, scene: int, tw: int, th: int,
    workdir: Path, on_progress: ProgressCb,
) -> tuple[Path, dict]:
    """Build one scene's assembled mp4 (video from timed muted shots + the
    scene performance track) inside workdir. Returns (path, timeline)."""
    segments, shots = await _load_scene_inputs(video_id, tenant_id, scene)
    timeline = build_timeline(segments, shots)
    if not timeline["entries"]:
        raise ValueError(
            f"Scene {scene}: {'; '.join(timeline['warnings']) or 'empty timeline'}")
    for w in timeline["warnings"]:
        await _emit(on_progress, f"Scene {scene}: {w}")

    sdir = workdir / f"scene_{scene}"
    sdir.mkdir(parents=True, exist_ok=True)

    await _emit(on_progress, f"Scene {scene}: building the performance track "
                             f"({len(timeline['placements'])} voices)…")
    track = await _build_scene_track(timeline["placements"], timeline["total"], sdir)

    used = {id(e["shot"]): e["shot"] for e in timeline["entries"]}
    clip_rows = list(used.values())
    paths = await _download_clips(clip_rows, sdir, on_progress)
    path_by_shot = {id(r): p for r, p in zip(clip_rows, paths)}

    await _emit(on_progress, f"Scene {scene}: timing {len(timeline['entries'])} shots…")
    parts: list[Path] = []
    for i, e in enumerate(timeline["entries"]):
        part = sdir / f"part_{i:03d}.mp4"
        await _cut_shot(path_by_shot[id(e["shot"])], e["duration"], tw, th, part)
        parts.append(part)

    silent = sdir / "scene_silent.mp4"
    await _concat_copy(parts, silent, sdir)

    out = sdir / f"scene_{scene}.mp4"
    async with _FFMPEG_SEM:
        rc, err = await _run_subprocess(
            ["ffmpeg", "-y", "-i", str(silent), "-i", str(track),
             "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac",
             "-b:a", "192k", "-movflags", "+faststart", str(out)])
    if rc != 0 or not out.exists() or await _probe_duration(str(out)) <= 0:
        raise RuntimeError(f"scene {scene} audio mux failed (rc={rc}): {err[-400:]}")
    return out, timeline


async def _video_canvas(video_id: str, tenant_id, orientation: str,
                        workdir: Path) -> tuple[int, int, str]:
    """One canvas for the whole video, picked from the first clip of each
    scene (probing every clip means downloading every clip twice)."""
    rows = await fetch_all(
        "SELECT DISTINCT ON (scene) scene, image_index, video_clip_url, video_duration "
        "FROM assets WHERE video_id = $1 AND tenant_id = $2 "
        "AND video_clip_url IS NOT NULL ORDER BY scene, image_index",
        video_id, tenant_id)
    if not rows:
        raise ValueError("No clips to assemble — animate the scenes first.")
    probe_dir = workdir / "probe"
    probe_dir.mkdir(parents=True, exist_ok=True)
    paths = await _download_clips([dict(r) for r in rows], probe_dir, None)
    return await _choose_target(paths, orientation)


async def assemble_scene(
    video_id: str, tenant_id, scene: int, *,
    orientation: str = "auto", on_progress: ProgressCb = None,
) -> dict:
    """Assemble ONE scene (the per-scene preview) and upload it to the scene's
    stable path. Returns {scene_video_url, duration_seconds, shots, warnings}."""
    workdir = Path(tempfile.mkdtemp(prefix=f"perform_{video_id[:8]}_"))
    try:
        tw, th, orient = await _video_canvas(video_id, tenant_id, orientation, workdir)
        out, timeline = await _assemble_scene_file(
            video_id, tenant_id, scene, tw, th, workdir, on_progress)
        data = out.read_bytes()
        url = await upload_bytes(
            data, f"{video_id}/scenes/S{scene:02d}.mp4", "video/mp4", tenant_id)
        return {"scene_video_url": url,
                "duration_seconds": round(await _probe_duration(str(out)), 1),
                "shots": len(timeline["entries"]),
                "resolution": f"{tw}x{th}", "orientation": orient,
                "warnings": timeline["warnings"]}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


async def render_performance_video(
    video_id: str, tenant_id, *,
    title: str = "", orientation: str = "auto", on_progress: ProgressCb = None,
) -> dict:
    """Assemble every scene and join them into the final video.

    Same result shape as render_stitch.stitch_video so the caller
    (pipeline_executor) treats both paths alike."""
    scene_rows = await fetch_all(
        "SELECT DISTINCT scene FROM assets WHERE video_id = $1 AND tenant_id = $2 "
        "AND video_clip_url IS NOT NULL AND scene IS NOT NULL ORDER BY scene",
        video_id, tenant_id)
    scenes = [r["scene"] for r in scene_rows]
    if not scenes:
        raise ValueError("No clips to assemble — animate the scenes first.")

    workdir = Path(tempfile.mkdtemp(prefix=f"perform_{video_id[:8]}_"))
    try:
        tw, th, orient = await _video_canvas(video_id, tenant_id, orientation, workdir)
        await _emit(on_progress,
                    f"Assembling {len(scenes)} scene(s) on a {tw}x{th} canvas…")
        scene_files: list[Path] = []
        warnings: list[str] = []
        shot_count = 0
        for sc in scenes:
            f, timeline = await _assemble_scene_file(
                video_id, tenant_id, sc, tw, th, workdir, on_progress)
            scene_files.append(f)
            warnings.extend(f"S{sc}: {w}" for w in timeline["warnings"])
            shot_count += len(timeline["entries"])

        final = workdir / "final.mp4"
        await _concat_copy(scene_files, final, workdir)
        duration = await _probe_duration(str(final))

        data = final.read_bytes()
        storage_path = f"{video_id}/final/{_safe_filename(title, 'render')}.mp4"
        await _emit(on_progress,
                    f"Uploading final video ({len(data) // (1024 * 1024)}MB)…")
        url = await upload_bytes(data, storage_path, "video/mp4", tenant_id)

        return {"final_video_url": url,
                "duration_seconds": round(duration, 1),
                "clip_count": shot_count,
                "scene_count": len(scenes),
                "method": "performance_track",
                "resolution": f"{tw}x{th}",
                "orientation": orient,
                "size_bytes": len(data),
                "warnings": warnings}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
