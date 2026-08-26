"""Static-image documentary render (Remotion).

For **static_docu** videos (``videos.render_mode = 'static_docu'``) the final
video is Anton's DvsU format: two or three complementary images per aircraft,
rotated under one narration segment with alternating slow push-in/pull-out
motion and one fixed identifying title card. No animated clips or Whisper —
the segment duration IS the narration mp3's duration, so timing comes from
``scripts.voice_duration_seconds`` (ffprobe fallback) instead of a
transcription pass.

Reuses the proven pieces, builds nothing new:
  * the existing ``remotion-video`` Main composition (Ken Burns + transitions
    + narrator audio are already implemented in Scene.tsx);
  * the pure legacy helpers ``assign_ken_burns`` / ``assign_transitions`` from
    skills/video-pipeline (no Airtable coupling);
  * ``render_stitch``'s download/probe/upload plumbing.

Isolation mirrors render_stitch: each render stages its assets into its own
temp dir and passes it to Remotion via ``--public-dir``, so concurrent renders
never collide on the shared ``remotion-video/public`` folder (the old bug).

Public entry:
    await render_static_video(video_id, tenant_id, title="", on_progress=None) -> dict
"""

import asyncio
import json
import logging
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

from database import fetch_all
from storage import upload_bytes, download_bytes
from story_laws import strip_scene_stage_headers
from render_stitch import (
    ProgressCb,
    _emit,
    _extract_drive_file_id,
    _google_client,
    _probe_duration,
    _run_subprocess,
)
import render_static_ffmpeg
import channel_audio

logger = logging.getLogger(__name__)

_REMOTION_DIR = Path(__file__).resolve().parents[2] / "remotion-video"
_PIPELINE_PATH = Path(__file__).resolve().parents[2] / "skills" / "video-pipeline"
if str(_PIPELINE_PATH) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_PATH))

# Single Claude tier source (checklist §3.4 / C35) — see shared.channel_profile.
from shared.channel_profile import CLAUDE_MODELS  # noqa: E402

# One Remotion render at a time — a render is CPU-bound across ~3 chrome
# workers and the box is small; a second static render queues instead of
# fighting for cores. Env-tunable like the stitch semaphore.
_REMOTION_SEM = asyncio.Semaphore(int(os.getenv("STATIC_RENDER_CONCURRENCY", "1")))

# Anton's title-card overlay is part of the channel format. It remains
# env-disableable for an exceptional legacy render, but the safe/default path
# now follows the DvsU standard instead of silently suppressing it.
DRAW_CAPTIONS = os.getenv("STATIC_DRAW_CAPTIONS", "1") != "0"

_VIEW_COMPOSITIONS = {
    # Keyed by static_docu_contract.STATIC_VIEW_PLANS role (2026-08-03 fix:
    # genuinely rotated camera angles replaced the old three_quarter/
    # top_oblique/engineering_detail roster). Unmapped/legacy roles fall back
    # to "wide" below — harmless, since get_composition_direction_map() maps
    # both "wide" and "overhead" to the same slow_zoom_in Ken Burns motion.
    "three_quarter": "wide",
    "side_profile": "wide",
    "top_planform": "overhead",
}


def _safe_filename(title: str, fallback: str) -> str:
    clean = re.sub(r"[^\w\s-]", "", title or "")
    clean = re.sub(r"[-\s]+", "_", clean).strip("_")
    return (clean or fallback)[:50]


async def _download_to(url: str, dest: Path, gc) -> None:
    """Fetch a stored asset URL (Drive link, storage path, or plain http)."""
    file_id = _extract_drive_file_id(url)
    if file_id:
        await asyncio.to_thread(gc.download_file_to_local, file_id, str(dest))
    else:
        dest.write_bytes(await download_bytes(url))
    if not dest.exists() or dest.stat().st_size == 0:
        raise RuntimeError(f"asset downloaded empty: {url[:100]}")


async def _normalize_audio(path: Path) -> None:
    """Re-encode any staged audio to 48kHz stereo mp3 IN PLACE.

    Every audio input must share ONE sample rate/layout: the TTS narration is
    44.1kHz mono while the music library is 48kHz stereo, and Remotion's media
    engine mixing the two produced pitched-up 'robotic gibberish' narration
    (heard live on DVU v2). Uniform inputs mean no in-engine resampling."""
    tmp = path.with_suffix(".norm.mp3")
    rc, err = await _run_subprocess([
        "ffmpeg", "-y", "-i", str(path),
        "-ar", "48000", "-ac", "2", "-b:a", "192k", str(tmp),
    ])
    if rc != 0 or not tmp.exists() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"audio normalize failed for {path.name}: {err[-300:]}")
    tmp.replace(path)


async def _gather_segments(video_id: str, tenant_id: str) -> list[dict]:
    """One entry per narration scene with its ordered 1–3 image set.

    New DvsU rows contribute all available static-docu views (up to three).
    Legacy projects remain renderable: when no static-docu row exists, fall
    back to the coverage hero/first image exactly as before.
    """
    scenes = await fetch_all(
        "SELECT scene, scene_text, voice_over_url, voice_duration_seconds FROM scripts "
        "WHERE video_id=$1 AND tenant_id=$2 AND scene IS NOT NULL "
        "AND voice_over_url IS NOT NULL ORDER BY scene",
        video_id, tenant_id,
    )
    if not scenes:
        raise RuntimeError(
            "No narration found — run the voice step first (static renders "
            "put the voiceover under the images)."
        )
    images = await fetch_all(
        "SELECT scene, image_index, image_url, generation_method, hero_shot, caption, "
        "transition_kind "
        "FROM assets WHERE video_id=$1 AND tenant_id=$2 AND image_url IS NOT NULL "
        "ORDER BY scene, image_index",
        video_id, tenant_id,
    )
    by_scene: dict[int, list[dict]] = {}
    for row in images:
        by_scene.setdefault(row["scene"], []).append(row)

    def _parse_caption(raw):
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (ValueError, TypeError):
                return None
        return raw if isinstance(raw, dict) else None

    def _pick_many(scene: int) -> list[dict]:
        rows = by_scene.get(scene) or []
        static_rows = [
            r for r in rows if r.get("generation_method") == "static_docu"
        ][:3]
        if static_rows:
            return static_rows
        for r in rows:
            if r.get("hero_shot"):
                return [r]
        return rows[:1]

    segments = []
    missing = []
    for s in scenes:
        picked = _pick_many(s["scene"])
        if not picked:
            missing.append(str(s["scene"]))
            continue
        images = [
            {
                "image_url": img["image_url"],
                "source_index": int(img.get("image_index") or local_index),
                "caption": _parse_caption(img.get("caption")),
                # D12-2: migration 148's per-shot cut-type signal, threaded
                # through so _build_render_config can hand it to
                # transition_engine.determine_transition. NULL for every row
                # written before that migration and any shot the planner
                # didn't tag — determine_transition's default (quick
                # crossfade) is unaffected by a NULL/absent value here.
                "transition_kind": img.get("transition_kind"),
            }
            for local_index, img in enumerate(picked, start=1)
        ]
        caption = next(
            (img["caption"] for img in images if img.get("caption")), None
        )
        segments.append({
            "scene": s["scene"],
            # Storage keeps leading LOCATION:/ACTION: stage headers verbatim
            # (S7-A); the voice step strips them before synthesis (S7-C), so
            # everything render-side that consumes this text (today the
            # music-mood pass; any future caption use) must see the same
            # header-free text the narration was actually made from.
            "scene_text": strip_scene_stage_headers(s.get("scene_text")),
            "voice_url": s["voice_over_url"],
            "voice_duration": float(s["voice_duration_seconds"] or 0),
            # image_url stays for old tests/callers; images is authoritative.
            "image_url": images[0]["image_url"],
            "images": images,
            "caption": caption,
        })
    if missing:
        raise RuntimeError(
            f"Scene(s) {', '.join(missing)} have no image yet — generate the "
            "pictures first."
        )
    return segments


def _images_for_segment(segment: dict) -> list[dict]:
    """Normalized image list with a one-image legacy fallback."""
    images = segment.get("images")
    if isinstance(images, list) and images:
        return [img for img in images if isinstance(img, dict) and img.get("image_url")]
    if segment.get("image_url"):
        return [{
            "image_url": segment["image_url"],
            "source_index": 1,
            "caption": segment.get("caption"),
        }]
    return []


def _build_render_config(video_id: str, segments: list[dict]) -> dict:
    """The renderConfig the Remotion composition reads (embedded in --props).

    One render entry per image, grouped under its narration scene. Audio still
    plays once per scene; the image entries divide that scene's hold evenly.
    Motion alternates a slow cinematic push-in/pull-out and is eased over the
    full hold (never finishes early).
    """
    from render.audio_sync.transition_engine import assign_transitions

    scene_count = len(segments)
    scenes = []
    cursor = 0.0
    motion_index = 0
    for scene_position, seg in enumerate(segments):
        duration = round(float(seg["duration"]), 4)
        images = _images_for_segment(seg)
        if not images:
            continue
        cap = (seg.get("caption") or {}) if DRAW_CAPTIONS else {}
        scene_start = cursor
        part = duration / len(images)
        elapsed = 0.0
        for local_index, image in enumerate(images, start=1):
            # Put rounding residue into the final view so the parts sum to the
            # exact narration duration and audio never drifts.
            view_duration = (
                round(duration - elapsed, 4)
                if local_index == len(images)
                else round(part, 4)
            )
            view_start = round(scene_start + elapsed, 4)
            view_end = round(view_start + view_duration, 4)
            image_cap = (image.get("caption") or cap) if DRAW_CAPTIONS else {}
            role = (image_cap or {}).get("view_role") or ""
            push_in = motion_index % 2 == 0
            scenes.append({
                "scene_number": seg["scene"],
                "image_path": f"Scene_{seg['scene']:02d}_{local_index:02d}.png",
                "image_index": local_index,
                "source_image_index": image.get("source_index") or local_index,
                # D12-2: read by transition_engine.determine_transition (via
                # assign_transitions below) to pick this boundary's
                # treatment when this image is the INCOMING shot of a cut.
                # None for every pre-migration-148 asset row — falls through
                # to determine_transition's existing default unchanged.
                "transition_kind": image.get("transition_kind"),
                "display_start": view_start,
                "display_end": view_end,
                "display_duration": view_duration,
                # Narration spans the whole aircraft scene and is played once
                # by Scene.tsx, not restarted for each image entry.
                "narration_start": round(scene_start, 4),
                "narration_end": round(scene_start + duration, 4),
                "style": "static_docu",
                "composition": _VIEW_COMPOSITIONS.get(role, "wide"),
                "act": min(
                    6,
                    (scene_position * 6) // max(scene_count, 1) + 1,
                ),
                "type": "image",
                # Only the first image carries the metadata. Scene.tsx lifts
                # it outside the image sequences and animates one card for the
                # whole aircraft, so it never repeats at image changes.
                "caption_title": (
                    (image_cap or {}).get("title") or ""
                    if local_index == 1 else ""
                ),
                "caption_sub": (
                    (image_cap or {}).get("sub") or ""
                    if local_index == 1 else ""
                ),
                "caption_specs": (
                    list((image_cap or {}).get("specs") or [])[:2]
                    if local_index == 1 else []
                ),
                "ken_burns": {
                    "direction": (
                        "slow_push_in" if push_in else "slow_pull_out"
                    ),
                    "start_scale": 1.025 if push_in else 1.085,
                    "end_scale": 1.085 if push_in else 1.025,
                    "start_x_offset": 0,
                    "end_x_offset": 0,
                    "start_y_offset": 0,
                    "end_y_offset": 0,
                    "speed_multiplier": 1.0,
                    "motion_curve": "cinematic_smoothstep",
                    "disable_breathe": True,
                },
            })
            elapsed = round(elapsed + view_duration, 4)
            motion_index += 1
        cursor = round(scene_start + duration, 4)

    assign_transitions(scenes)
    return {
        "video_id": video_id,
        "audio_path": "",
        "total_duration_seconds": round(cursor, 4),
        "fps": 24,
        "resolution": {"width": 1920, "height": 1080},
        "scenes": scenes,
    }


_MUSIC_LIB_DIR = _REMOTION_DIR / "public" / "music"


async def _select_music_beds(tenant_id: str, segments: list[dict],
                             rc: dict, public_dir: Path) -> list[dict]:
    """Use a fixed channel bed when configured, else select per-act music.

    Legacy selection uses the local library (mood-tagged files like
    'tension_dark_horizon_1.mp3'). One Claude call classifies each act's mood;
    a deterministic fallback alternates moods if that fails. Chosen tracks are
    copied into this render's isolated public dir. Invalid fixed configuration
    raises instead of silently changing the channel's configured gain."""
    fixed = await channel_audio.get_fixed_music_bed_config(tenant_id)
    if fixed is not None:
        music_dir = public_dir / "music"
        music_dir.mkdir(exist_ok=True)
        staged = music_dir / fixed.file_name
        if not staged.exists():
            gc = _google_client() if _extract_drive_file_id(fixed.asset_url) else None
            await _download_to(fixed.asset_url, staged, gc)
            await _normalize_audio(staged)
        return [{
            "scope": "video",
            "file": fixed.file_name,
            "volume": fixed.volume,
            "trim_before_seconds": fixed.trim_before_seconds,
            "loop": fixed.loop,
        }]

    try:
        tracks = [p.name for p in _MUSIC_LIB_DIR.glob("*.mp3")]
        moods_available = sorted({t.split("_")[0] for t in tracks})
        if not tracks:
            return []

        # Act -> combined narration text (for mood classification).
        act_text: dict[int, str] = {}
        act_of_scene = {s["scene_number"]: s["act"] for s in rc["scenes"]}
        for seg in segments:
            act = act_of_scene.get(seg["scene"], 1)
            act_text[act] = (act_text.get(act, "") + "\n" + (seg.get("scene_text") or ""))[:2500]

        moods: dict[int, str] = {}
        try:
            from kie_unified import get_text_client_for_tenant
            client = await get_text_client_for_tenant(tenant_id)
            listing = "\n\n".join(f"[act {a}] {t[:900]}" for a, t in sorted(act_text.items()))
            kwargs = {"prompt": (
                "Classify the MOOD of each act of this documentary narration. "
                f"Choose one of {moods_available} per act. Reply with a JSON "
                'object only, e.g. {"1": "tension", "2": "strategic"}.\n\n' + listing),
                "max_tokens": 300}
            if type(client).__name__ == "AnthropicDirectClient":
                kwargs["model"] = CLAUDE_MODELS["anthropic"]["fast"]
            raw = await client.generate(**kwargs)
            m = re.search(r"\{.*\}", raw or "", re.DOTALL)
            if m:
                moods = {int(k): str(v).lower() for k, v in json.loads(m.group(0)).items()}
        except Exception:  # noqa: BLE001 — deterministic fallback below
            pass

        music_dir = public_dir / "music"
        music_dir.mkdir(exist_ok=True)
        beds = []
        for i, act in enumerate(sorted(act_text.keys())):
            mood = moods.get(act) or moods_available[i % len(moods_available)]
            candidates = [t for t in tracks if t.startswith(mood)] or tracks
            track = candidates[act % len(candidates)]  # deterministic variety
            if not (music_dir / track).exists():
                shutil.copy2(_MUSIC_LIB_DIR / track, music_dir / track)
                await _normalize_audio(music_dir / track)
            beds.append({"act": act, "file": track, "mood": mood, "volume": 0.03})
        return beds
    except Exception:  # noqa: BLE001
        return []


def _remotion_concurrency() -> int:
    """Chrome-worker concurrency for the Remotion render.

    Was hardcoded at 3 regardless of box size. ``REMOTION_CONCURRENCY`` is an
    explicit override (matches the existing ``STATIC_RENDER_CONCURRENCY``
    naming, which instead governs how many *whole renders* run at once);
    absent that, use every core but one so the render doesn't starve the
    rest of the backend process, with 3 as a floor to never regress below
    the old fixed value on small boxes.
    """
    override = os.getenv("REMOTION_CONCURRENCY")
    if override:
        try:
            n = int(override)
            if n > 0:
                return n
        except ValueError:
            pass
    cores = os.cpu_count() or 3
    return max(3, cores - 1)


async def _run_remotion(public_dir: Path, props_file: Path, out_file: Path,
                        on_progress: ProgressCb) -> None:
    cmd = [
        "npx", "remotion", "render", "Main", str(out_file),
        "--props", str(props_file),
        "--public-dir", str(public_dir),
        f"--concurrency={_remotion_concurrency()}",
        "--gl=swangle",
        "--timeout=180000",
        # Default encode gave ~1GB per 9 min; crf 20 + a fast x264 preset
        # cuts encode time sharply while staying visually lossless-enough
        # for held images + slow pans.
        "--crf=20",
        "--x264-preset=veryfast",
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=str(_REMOTION_DIR),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    last_pct = -20
    tail: list[str] = []
    assert proc.stdout is not None
    while True:
        line_b = await proc.stdout.readline()
        if not line_b:
            break
        line = line_b.decode("utf-8", "replace").strip()
        if line:
            tail.append(line)
            tail = tail[-30:]
        m = re.search(r"Rendered\s+(\d+)/(\d+)", line)
        if m and int(m.group(2)) > 0:
            pct = int(int(m.group(1)) / int(m.group(2)) * 100)
            if pct >= last_pct + 20:
                last_pct = pct
                await _emit(on_progress, f"Rendering… {pct}%")
    rc = await proc.wait()
    if rc != 0:
        detail = "\n".join(tail[-8:])
        raise RuntimeError(f"Remotion render failed (exit {rc}):\n{detail}")
    if not out_file.exists() or out_file.stat().st_size == 0:
        raise RuntimeError("Remotion finished but produced no output file")


def _requires_remotion(rc: dict) -> bool:
    """Does this config use DvsU features the legacy FFmpeg path cannot draw?

    FFmpeg's optional speed experiment still assumes one image/audio pair per
    scene and has no title-card compositor. Never silently drop multi-view
    rotation or overlays merely because an environment flag selected it.
    """
    scenes = rc.get("scenes") or []
    scene_numbers = [scene.get("scene_number") for scene in scenes]
    return (
        len(scene_numbers) != len(set(scene_numbers))
        or any(scene.get("caption_title") for scene in scenes)
    )


async def render_static_video(
    video_id: str,
    tenant_id: str,
    *,
    title: str = "",
    on_progress: ProgressCb = None,
) -> dict:
    """Render a static-documentary video and upload the final mp4.

    Returns {final_video_url, duration_seconds, scene_count, resolution,
    method} or raises RuntimeError with a user-explainable message.
    """
    await _emit(on_progress, "Collecting narration and images")
    segments = await _gather_segments(video_id, tenant_id)

    workdir = Path(tempfile.mkdtemp(prefix=f"static_{video_id[:8]}_"))
    public_dir = workdir / "public"
    public_dir.mkdir()
    try:
        gc = _google_client()
        image_count = sum(len(_images_for_segment(seg)) for seg in segments)
        await _emit(
            on_progress,
            f"Downloading {len(segments)} narration tracks and {image_count} images",
        )
        for seg in segments:
            voice_path = public_dir / f"Scene {seg['scene']}.mp3"
            await _download_to(seg["voice_url"], voice_path, gc)
            await _normalize_audio(voice_path)
            for local_index, image in enumerate(
                _images_for_segment(seg), start=1
            ):
                await _download_to(
                    image["image_url"],
                    public_dir / f"Scene_{seg['scene']:02d}_{local_index:02d}.png",
                    gc,
                )

        # Segment duration = the narration's real length. Trust the stored
        # figure only when it matches the file (stale rows happen); ffprobe is
        # the source of truth.
        for seg in segments:
            probed = await _probe_duration(str(public_dir / f"Scene {seg['scene']}.mp3"))
            stored = seg["voice_duration"]
            seg["duration"] = probed if probed > 0 else stored
            if seg["duration"] <= 0:
                raise RuntimeError(f"Scene {seg['scene']}: narration has no readable duration")

        rc = _build_render_config(video_id, segments)
        beds = await _select_music_beds(tenant_id, segments, rc, public_dir)
        if beds:
            rc["music_beds"] = beds
            await _emit(on_progress, f"Music: {len(beds)} act beds selected")
        props_file = workdir / "props.json"
        props_file.write_text(json.dumps({"renderConfig": rc}))

        out_file = workdir / "out.mp4"
        engine = render_static_ffmpeg.render_engine()
        if engine == "ffmpeg" and _requires_remotion(rc):
            engine = "remotion"
            await _emit(
                on_progress,
                "Using the DvsU compositor for multi-view motion and title cards",
            )
        async with _REMOTION_SEM:
            if engine == "ffmpeg":
                await _emit(on_progress, "Rendering the documentary (ffmpeg engine)")
                await render_static_ffmpeg.render_static_ffmpeg_video(
                    rc, public_dir, workdir, out_file, on_progress)
            else:
                await _emit(on_progress, "Rendering the documentary (Remotion)")
                await _run_remotion(public_dir, props_file, out_file, on_progress)

        # Salvage guard: the render itself (the expensive ~1hr+ part) is done
        # once out_file exists. If anything past this point raises (upload
        # 404, DB write failure, etc.) the `finally` below still wipes workdir
        # — which used to silently delete the only copy of a finished MP4
        # (2026-07-22 incident: a bad Drive parent folder 404'd the upload and
        # the render was lost). Move the finished file to a persistent path
        # before re-raising so a failed post-render step never destroys
        # otherwise-good render output.
        try:
            await _emit(on_progress, "Uploading the final video")
            data = out_file.read_bytes()
            safe = _safe_filename(title, video_id[:8])
            # Unique name per render: re-using one filename REPLACED the Drive
            # file in place, so anyone streaming the video mid-upload got a
            # corrupted "robotic" stream (heard live). A new file per render
            # swaps the URL atomically instead.
            import uuid as _uuid
            url = await upload_bytes(
                data, f"{video_id}/final/{safe}_{_uuid.uuid4().hex[:6]}.mp4",
                "video/mp4", tenant_id)
            duration = await _probe_duration(str(out_file))
            return {
                "final_video_url": url,
                "duration_seconds": duration or rc["total_duration_seconds"],
                "scene_count": len(segments),
                "resolution": "1920x1080",
                "method": "remotion_static",
            }
        except Exception:
            if out_file.exists() and out_file.stat().st_size > 0:
                salvage_dir = Path.home() / "render_salvage"
                os.makedirs(salvage_dir, exist_ok=True)
                salvage_path = salvage_dir / f"{video_id}.mp4"
                shutil.move(str(out_file), str(salvage_path))
                logger.warning(
                    "render_static_video(%s): post-render step failed — "
                    "salvaged finished MP4 to %s before workdir cleanup",
                    video_id, salvage_path,
                )
            raise
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
