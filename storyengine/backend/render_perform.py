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
# A scene that OPENS on a line gives its planned establishing shot ZERO clock
# (first speaking window starts at t=0). Rather than drop a paid frame and
# open the video mid-shout, shift the whole track by a short silent lead-in
# so the opening silent shot(s) get a visual beat first.
SCENE_LEADIN_SECONDS = float(os.getenv("PERFORM_SCENE_LEADIN", "1.6"))

# assigned_dialogue is written by coverage as: Speaker: "line"
_ASSIGNED_RE = re.compile(r'^\s*(?P<speaker>[^:"]{1,80}):\s*"(?P<line>.+)"\s*$', re.DOTALL)


# ── pure timeline math ────────────────────────────────────────────────────────

def build_segment_spans(segments: list, overrides: Optional[dict] = None) -> list[dict]:
    """Lay the segments end to end on one clock.

    Returns one span per segment: {index, type, speaker, text, audio_url,
    duration, start, end, audio_at}. Dialogue spans include the head/tail pads
    (audio_at = start + head); a segment with no audio or no duration gets a
    zero-length span so indexes stay aligned.

    overrides (migration 114 / STS voice-lock): {seg_index: {duration, head,
    carrier: True}} replaces a claimed dialogue span's TTS-mp3 clock math with
    the CLIP's measured speech timing — the carrying shot plays its own audio,
    so the clock must follow Grok's pace, not the unused mp3's.
    """
    spans: list[dict] = []
    t = 0.0
    for i, seg in enumerate(segments or []):
        ov = (overrides or {}).get(i)
        dur = float(ov["duration"] if ov else (seg.get("duration") or 0))
        url = seg.get("audio_url")
        is_dialogue = seg.get("type") == "dialogue"
        if (not url and not ov) or dur <= 0:
            spans.append({"index": i, "type": seg.get("type"), "speaker": seg.get("speaker"),
                          "text": seg.get("text") or "", "audio_url": None, "duration": 0.0,
                          "start": t, "end": t, "audio_at": t, "carrier": False})
            continue
        start = t
        head = (float(ov["head"]) if ov and ov.get("head") is not None
                else (DIALOGUE_HEAD_SECONDS if is_dialogue else 0.0))
        audio_at = start + head
        end = audio_at + dur + (DIALOGUE_TAIL_SECONDS if is_dialogue else 0.0)
        spans.append({"index": i, "type": seg.get("type"), "speaker": seg.get("speaker"),
                      "text": seg.get("text") or "", "audio_url": url, "duration": dur,
                      "start": round(start, 3), "end": round(end, 3),
                      "audio_at": round(audio_at, 3),
                      "carrier": bool(ov and ov.get("carrier"))})
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


_STOPWORDS = {"the", "and", "his", "her", "with", "into", "then", "that", "this",
              "them", "they", "from", "back", "over", "each", "very"}


def _overlap_score(shot: dict, span: dict) -> float:
    """Word overlap between a shot's planned content and a segment's text —
    how strongly this shot 'belongs' to that stretch of narration."""
    def words(t):
        return {w for w in re.findall(r"[a-záéíóúñü]{4,}", (t or "").lower())
                if w not in _STOPWORDS}
    sw = words(f'{shot.get("sentence_text") or ""} {shot.get("image_prompt") or ""}')
    gw = words(span.get("text"))
    return len(sw & gw) / (len(gw) ** 0.5) if gw else 0.0


def _align_shots_to_spans(block_shots: list, block_spans: list):
    """Order-preserving assignment of a narration block's shots to its audio
    segments: each shot covers ≥1 consecutive segment, every segment covered
    exactly once, maximizing content overlap (with a mild balance term so
    zero-overlap cases still split evenly). Returns [ [spans...] per shot ]
    or None when it can't apply. Cuts then land on segment boundaries — on
    sentence changes — instead of drifting mid-thought."""
    m, n = len(block_shots), len(block_spans)
    if m < 2 or n < m:
        return None
    total = sum(s["duration"] for s in block_spans) or 1.0
    target = total / m

    def gscore(si, j0, j1):  # shot si covering spans j0..j1 inclusive
        ov = sum(_overlap_score(block_shots[si], block_spans[j]) for j in range(j0, j1 + 1))
        dur = sum(block_spans[j]["duration"] for j in range(j0, j1 + 1))
        return ov - 0.2 * abs(dur - target) / target

    NEG = float("-inf")
    dp = [[NEG] * (n + 1) for _ in range(m + 1)]
    back = [[0] * (n + 1) for _ in range(m + 1)]
    dp[0][0] = 0.0
    for i in range(1, m + 1):
        for j in range(i, n - (m - i) + 1):
            for k in range(i - 1, j):
                if dp[i - 1][k] == NEG:
                    continue
                sc = dp[i - 1][k] + gscore(i - 1, k, j - 1)
                if sc > dp[i][j]:
                    dp[i][j], back[i][j] = sc, k
    if dp[m][n] == NEG:
        return None
    groups, j = [], n
    for i in range(m, 0, -1):
        k = back[i][j]
        groups.append(block_spans[k:j])
        j = k
    return list(reversed(groups))


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

    # STS voice-lock (migration 114): a speaking shot whose clip already
    # CARRIES its line replaces its claimed span's TTS clock math with the
    # clip's measured speech timing — Grok's pace, not the unused mp3's.
    # Its mp3 placement is dropped (the clip's own audio goes on the scene
    # track at the window start instead — see _assemble_scene_file).
    # SINGLE-SPAN shots only (adversarial review 2026-07-22): a carrier
    # claiming several spans plays ONE continuous take, but the span math
    # would interleave other placements/tail pads inside its window —
    # narration over the take's second line, then dead air (verified by
    # repro). Multi-span masters keep the overlay behavior instead.
    overrides: dict = {}
    for pos, idxs in speaking.items():
        shot = shots[pos]
        cs, ce = shot.get("clip_speech_start"), shot.get("clip_speech_end")
        if not (shot.get("carries_own_line") and len(idxs) == 1
                and cs is not None and ce is not None and float(ce) > float(cs)):
            continue
        overrides[idxs[0]] = {
            "duration": round(float(ce) - float(cs), 3),
            "head": round(float(cs), 3),
            "carrier": True,
        }
    if overrides:
        spans = build_segment_spans(segments, overrides)
        total = spans[-1]["end"] if spans else 0.0
        placements = [(s["audio_url"], s["audio_at"])
                      for s in spans if s["audio_url"] and not s.get("carrier")]

    # Scene opens on a line AND silent shots were planned before the first
    # speaking shot → give them a lead-in beat instead of dropping them.
    first_speaking_pos = min(speaking) if speaking else None
    if first_speaking_pos is not None and first_speaking_pos > 0:
        first_window_start = spans[min(speaking[first_speaking_pos])]["start"]
        if first_window_start < 0.05 and SCENE_LEADIN_SECONDS > 0:
            for s in spans:
                s["start"] = round(s["start"] + SCENE_LEADIN_SECONDS, 3)
                s["end"] = round(s["end"] + SCENE_LEADIN_SECONDS, 3)
                s["audio_at"] = round(s["audio_at"] + SCENE_LEADIN_SECONDS, 3)
            total = round(total + SCENE_LEADIN_SECONDS, 3)
            placements = [(s["audio_url"], s["audio_at"])
                          for s in spans if s["audio_url"] and not s.get("carrier")]

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
                        "speaking": True,
                        "carries": bool(span_by_index[idxs[0]].get("carrier")),
                        # span-clock anchor + claimed span, needed AFTER
                        # normalization to place carrier audio (or demote the
                        # carrier when normalization moved its window).
                        "track_at": start,
                        "claim_span": span_by_index[idxs[0]]})

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

    claimed_idxs = {i for idxs in speaking.values() for i in idxs}

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

        # CONTENT-ALIGNED cuts: the audio segments inside this block have exact
        # spans and texts, and the shots were planned in story order — align
        # shots to the segments they were planned FOR (order-preserving DP on
        # word overlap) and snap every cut to a segment boundary. The old
        # word-count pro-rata drifted long blocks out of sync (found live: the
        # clock close-up playing under the vocab recap). Falls back to
        # pro-rata when there are more shots than segments in the block.
        block_spans = [s for s in spans
                       if s["duration"] > 0 and s["index"] not in claimed_idxs
                       and s["start"] >= b_start - 0.05 and s["end"] <= b_end + 0.05]
        groups = (_align_shots_to_spans([shots[p] for p in keep], block_spans)
                  if 2 <= len(keep) <= len(block_spans) else None)
        if groups:
            t = b_start
            for k, (p, gspans) in enumerate(zip(keep, groups)):
                end = b_end if k == len(keep) - 1 else gspans[-1]["end"]
                entries.append({"shot": shots[p], "start": round(t, 3),
                                "end": round(end, 3), "speaking": False})
                t = end
        else:
            # C3 item 4: prefer coverage.py's stamped per-shot-type target
            # (assets.duration_seconds — wide/medium/closeup, silent shots
            # only) as this shot's WEIGHT in the split; a shot with no
            # stamp (legacy rows, non-coverage assets) falls back to the
            # original word-count weight unchanged. The block's TOTAL time
            # is still fixed by the narration audio (block, above) — this
            # only changes how that fixed budget is divided, so a wide
            # holds the frame longer than an insert without touching the
            # scene's overall runtime or the speaking-shot path at all.
            weights = [shots[p].get("duration_seconds")
                      or max(1, len((shots[p].get("sentence_text") or "").split()))
                      for p in keep]
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

    # A carrier's window must sit exactly where the span clock put it —
    # normalization pulls entries[0] to 0.0 and snaps starts/ends, and a
    # carrier whose window MOVED would play its audio against a shifted
    # mouth, or over leading narration (verified by repro, adversarial
    # review 2026-07-22). Demote any moved carrier back to overlay
    # behavior: un-mark it and restore its TTS line to the scene track.
    for e in entries:
        if not e.get("carries"):
            continue
        if abs(e["start"] - e.get("track_at", e["start"])) > 0.05:
            e["carries"] = False
            sp = e.get("claim_span") or {}
            if sp.get("audio_url"):
                placements.append((sp["audio_url"], sp.get("audio_at", e["start"])))
            warnings.append(
                "a voice-locked shot's window moved during normalization — "
                "its line plays from the TTS track instead")

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
    over a silent base. amix normalize=0 keeps each voice at its own level.
    A placement source may also be a local Path (a carrier clip's extracted
    audio — STS voice-lock) instead of a URL."""
    files: list[Path] = []
    for i, (url, _at) in enumerate(placements):
        if isinstance(url, Path):
            files.append(url)
            continue
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


# A window may outlast its clip by this much before we loop instead of
# freezing the last frame. Small overruns freeze briefly (reads as a held
# beat); big ones ping-pong so the shot stays alive (found live: 7.5s average
# windows on 6s clips left ~30% of a film frozen).
FREEZE_TOLERANCE_SECONDS = float(os.getenv("PERFORM_FREEZE_TOLERANCE", "1.0"))


async def _cut_shot(src: Path, duration: float, tw: int, th: int, out: Path,
                    allow_loop: bool = True) -> None:
    """Normalize a clip onto the canvas and hold it to EXACTLY `duration`:
    trimmed if long; if the window outlasts the clip beyond the tolerance the
    clip REPLAYS FORWARD with a short crossfade at each seam — a runner keeps
    running (the earlier ping-pong visibly reversed directional motion —
    Ryan caught his sprinter moonwalking at second nine). Sub-tolerance
    overruns freeze the last frame. Audio dropped — the scene track carries
    every voice. allow_loop=False (carrier shots whose audio plays ONCE on
    the track) forbids the replay path — a re-spoken mouth with no second
    voice reads as a glitch; those freeze instead."""
    import math

    normalize = (f"scale={tw}:{th}:force_original_aspect_ratio=decrease,"
                 f"pad={tw}:{th}:-1:-1:color=black,setsar=1,fps={_FPS},format=yuv420p")
    clip_dur = await _probe_duration(str(src))

    if allow_loop and clip_dur > 0.5 and duration > clip_dur + FREEZE_TOLERANCE_SECONDS:
        fade = min(0.5, clip_dur / 4)
        step = clip_dur - fade
        k = min(6, max(2, math.ceil((duration - clip_dur) / step) + 1))
        inputs: list[str] = []
        for _ in range(k):
            inputs += ["-i", str(src)]
        parts = [f"[{i}:v]{normalize}[v{i}]" for i in range(k)]
        prev = "v0"
        for i in range(1, k):
            offset = clip_dur + (i - 1) * step - fade
            parts.append(f"[{prev}][v{i}]xfade=transition=fade:"
                         f"duration={fade:.3f}:offset={offset:.3f}[x{i}]")
            prev = f"x{i}"
        # tpad backstops the rare window longer than the capped loop covers.
        parts.append(f"[{prev}]tpad=stop_mode=clone:stop_duration={duration:.3f},"
                     f"trim=duration={duration:.3f}[vout]")
        graph = ";".join(parts)
        async with _FFMPEG_SEM:
            rc, err = await _run_subprocess(
                ["ffmpeg", "-y", *inputs, "-filter_complex", graph,
                 "-map", "[vout]", "-an", *_X264, str(out)])
        if rc == 0 and out.exists() and out.stat().st_size > 0:
            return
        # Loop failed for any reason → fall through to the freeze path (never
        # fail a render over a nicety).

    vf = (f"{normalize},"
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
        "video_clip_url, video_duration, "
        "carries_own_line, clip_speech_start, clip_speech_end, duration_seconds FROM assets "
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

    used = {id(e["shot"]): e["shot"] for e in timeline["entries"]}
    clip_rows = list(used.values())
    paths = await _download_clips(clip_rows, sdir, on_progress)
    path_by_shot = {id(r): p for r, p in zip(clip_rows, paths)}

    # Carrier shots (STS voice-lock) play their OWN audio: extract it and
    # place it on the scene track at the shot's window start. Their TTS mp3s
    # were already dropped from placements by build_timeline.
    placements = list(timeline["placements"])
    for i, e in enumerate(timeline["entries"]):
        if not e.get("carries"):
            continue
        src = path_by_shot[id(e["shot"])]
        ca = sdir / f"carrier_{i:03d}.m4a"
        async with _FFMPEG_SEM:
            rc, err = await _run_subprocess(
                ["ffmpeg", "-y", "-i", str(src), "-vn", "-map", "0:a:0",
                 "-c:a", "aac", str(ca)])
        if rc != 0 or not ca.exists() or ca.stat().st_size == 0:
            # No extractable audio → this line has NO fallback mp3 on the
            # track (it was dropped) — fail loudly rather than ship silence.
            raise RuntimeError(
                f"scene {scene}: carrier shot audio extraction failed (rc={rc}): "
                f"{err[-300:]}")
        # track_at, not start: the span-clock anchor. Post-normalization
        # start equals it within tolerance (moved carriers were demoted).
        placements.append((ca, e.get("track_at", e["start"])))

    await _emit(on_progress, f"Scene {scene}: building the performance track "
                             f"({len(placements)} voices)…")
    track = await _build_scene_track(placements, timeline["total"], sdir)

    await _emit(on_progress, f"Scene {scene}: timing {len(timeline['entries'])} shots…")
    parts: list[Path] = []
    for i, e in enumerate(timeline["entries"]):
        part = sdir / f"part_{i:03d}.mp4"
        await _cut_shot(path_by_shot[id(e["shot"])], e["duration"], tw, th, part,
                        allow_loop=not e.get("carries"))
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
