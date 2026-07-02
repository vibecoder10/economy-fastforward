"""Static-image documentary render (Remotion).

For **static_docu** videos (``videos.render_mode = 'static_docu'``) the final
video is the original Power Doctrine format: one generated image per narration
segment, HELD for the whole segment with a slow Ken Burns pan, over the
per-scene voiceover. No animated clips, no captions, no Whisper — the segment
duration IS the narration mp3's duration, so timing comes from
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
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

from database import fetch_all
from storage import upload_bytes, download_bytes
from render_stitch import (
    ProgressCb,
    _emit,
    _extract_drive_file_id,
    _google_client,
    _probe_duration,
    _run_subprocess,
)

_REMOTION_DIR = Path(__file__).resolve().parents[2] / "remotion-video"
_PIPELINE_PATH = Path(__file__).resolve().parents[2] / "skills" / "video-pipeline"
if str(_PIPELINE_PATH) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_PATH))

# One Remotion render at a time — a render is CPU-bound across ~3 chrome
# workers and the box is small; a second static render queues instead of
# fighting for cores. Env-tunable like the stitch semaphore.
_REMOTION_SEM = asyncio.Semaphore(int(os.getenv("STATIC_RENDER_CONCURRENCY", "1")))

# Rotate composition hints so assign_ken_burns varies the pan direction from
# image to image (its direction map keys off the composition).
_COMPOSITION_CYCLE = ["wide", "environmental", "medium", "wide", "overhead", "medium"]


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
    """One entry per scene: narration mp3 + the single image that holds it.

    Image preference: static_docu asset (this mode's generator) -> coverage
    master/hero frame -> any image for the scene (lowest index).
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
        "SELECT scene, image_index, image_url, generation_method, hero_shot, caption "
        "FROM assets WHERE video_id=$1 AND tenant_id=$2 AND image_url IS NOT NULL "
        "ORDER BY scene, image_index",
        video_id, tenant_id,
    )
    by_scene: dict[int, list[dict]] = {}
    for row in images:
        by_scene.setdefault(row["scene"], []).append(row)

    def _pick(scene: int):
        rows = by_scene.get(scene) or []
        for r in rows:
            if r.get("generation_method") == "static_docu":
                return r
        for r in rows:
            if r.get("hero_shot"):
                return r
        return rows[0] if rows else None

    segments = []
    missing = []
    for s in scenes:
        img = _pick(s["scene"])
        if not img:
            missing.append(str(s["scene"]))
            continue
        caption = img.get("caption")
        if isinstance(caption, str):
            try:
                caption = json.loads(caption)
            except (ValueError, TypeError):
                caption = None
        segments.append({
            "scene": s["scene"],
            "scene_text": s.get("scene_text") or "",
            "voice_url": s["voice_over_url"],
            "voice_duration": float(s["voice_duration_seconds"] or 0),
            "image_url": img["image_url"],
            "caption": caption if isinstance(caption, dict) else None,
        })
    if missing:
        raise RuntimeError(
            f"Scene(s) {', '.join(missing)} have no image yet — generate the "
            "pictures first."
        )
    return segments


def _build_render_config(video_id: str, segments: list[dict]) -> dict:
    """The renderConfig the Remotion composition reads (embedded in --props).

    One entry per scene, image held for the narration's full duration. Ken
    Burns + transitions come from the proven legacy calculators (pure, no
    Airtable).
    """
    from render.audio_sync.ken_burns_calculator import assign_ken_burns
    from render.audio_sync.transition_engine import assign_transitions

    n = len(segments)
    scenes = []
    cursor = 0.0
    for i, seg in enumerate(segments):
        dur = round(seg["duration"], 4)
        cap = seg.get("caption") or {}
        scenes.append({
            "scene_number": seg["scene"],
            "image_path": f"Scene_{seg['scene']:02d}_01.png",
            "image_index": 1,
            "display_start": round(cursor, 4),
            "display_end": round(cursor + dur, 4),
            "display_duration": dur,
            "narration_start": round(cursor, 4),
            "narration_end": round(cursor + dur, 4),
            "style": "",
            "composition": _COMPOSITION_CYCLE[i % len(_COMPOSITION_CYCLE)],
            # 6-act split — drives dip-to-black transitions at act boundaries
            # (the format's "music swell" beats) via the transition engine.
            "act": min(6, (i * 6) // max(n, 1) + 1),
            "type": "image",
            # Fixed text overlay (Scene.tsx) — never moves with the pan.
            "caption_title": cap.get("title") or "",
            "caption_sub": cap.get("sub") or "",
        })
        cursor += dur
    assign_ken_burns(scenes)
    assign_transitions(scenes)
    # Coverage guarantee: the legacy pan presets translate at scale 1.0, which
    # exposes black canvas at the frame edge (Scene.tsx also adds a ±3px
    # "breathing" wobble). Make sure every image is zoomed enough that the pan
    # never runs off the picture: scale s covers ~(s-1)*960px of horizontal
    # travel; offsets are scaled by the transform too, so 1.08 comfortably
    # covers the ±40px presets + breathing.
    for s in scenes:
        kb = s.get("ken_burns") or {}
        has_pan = any(kb.get(k) for k in (
            "start_x_offset", "end_x_offset", "start_y_offset", "end_y_offset"))
        floor = 1.08 if has_pan else 1.02
        kb["start_scale"] = max(float(kb.get("start_scale") or 1.0), floor)
        kb["end_scale"] = max(float(kb.get("end_scale") or 1.0), floor)
        s["ken_burns"] = kb
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
    """Per-act background music from the local library (mood-tagged files like
    'tension_dark_horizon_1.mp3'). One Claude call classifies each act's mood;
    a deterministic fallback alternates moods if that fails. Chosen tracks are
    copied into this render's isolated public dir. Never raises — a render
    without music beats no render."""
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
                kwargs["model"] = "claude-haiku-4-5"
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


async def _run_remotion(public_dir: Path, props_file: Path, out_file: Path,
                        on_progress: ProgressCb) -> None:
    cmd = [
        "npx", "remotion", "render", "Main", str(out_file),
        "--props", str(props_file),
        "--public-dir", str(public_dir),
        "--concurrency=3",
        "--gl=swangle",
        "--timeout=180000",
        # Default encode gave ~1GB per 9 min; crf 23 is visually equivalent
        # for held images + slow pans at a fraction of the size.
        "--crf=23",
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
        await _emit(on_progress, f"Downloading {len(segments)} segment assets")
        for seg in segments:
            voice_path = public_dir / f"Scene {seg['scene']}.mp3"
            await _download_to(seg["voice_url"], voice_path, gc)
            await _normalize_audio(voice_path)
            await _download_to(
                seg["image_url"], public_dir / f"Scene_{seg['scene']:02d}_01.png", gc)

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
        async with _REMOTION_SEM:
            await _emit(on_progress, "Rendering the documentary (Remotion)")
            await _run_remotion(public_dir, props_file, out_file, on_progress)

        await _emit(on_progress, "Uploading the final video")
        data = out_file.read_bytes()
        safe = _safe_filename(title, video_id[:8])
        # Unique name per render: re-using one filename REPLACED the Drive file
        # in place, so anyone streaming the video mid-upload got a corrupted
        # "robotic" stream (heard live). A new file per render swaps the URL
        # atomically instead.
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
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
