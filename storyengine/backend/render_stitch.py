"""Fast FFmpeg clip-stitch render.

For **grok_native** videos every clip already carries its own baked-in audio
(Grok voices the dialogue into the clip), so the "render" is just concatenating
the clips in scene/segment order. This bypasses Remotion entirely — no
``render_config.json``, no Whisper audio-sync, no muted-clip / narrator bug
(``Scene.tsx`` issues).

Clips can differ in size/orientation (e.g. a landscape intro + many portrait
body clips), so the concat **normalizes** every clip onto one uniform canvas
(scale-to-fit + pad, never stretch) and joins them in a single H.264 encode via
the ffmpeg ``concat`` filter — see ``_concat``. One encode gives a consistent
parameter set (strict players like QuickTime don't freeze) and rebuilt
timestamps (audio and video can't drift). ~75s for a ~9-min video, ~2GB RAM.

Designed to survive ~20 simultaneous renders on a small VPS:
  * each render works in its own ``tempfile`` dir (no shared ``public/`` like the
    Remotion path — that dir was a real collision hazard under concurrency);
  * a process-wide semaphore (``_FFMPEG_SEM``) caps concurrent ffmpeg encodes so
    a burst queues instead of exhausting CPU **or RAM** (each encode is ~2GB);
  * downloads are I/O-bound and capped per-render;
  * ffmpeg runs via asyncio subprocess so it never blocks the event loop.

Public entry:
    await stitch_video(video_id, tenant_id, orientation="auto", on_progress=None) -> dict
"""

import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from typing import Awaitable, Callable, Optional

from database import fetch_all
from storage import upload_bytes

# Cap concurrent ffmpeg *processes* across the whole backend. Stream-copy is
# nearly free, but the re-encode fallback is CPU-heavy and the box is small
# (4 cores) — this is the safety valve so 20 simultaneous renders queue instead
# of melting the CPU. Tunable via env without a code change.
_FFMPEG_SEM = asyncio.Semaphore(int(os.getenv("STITCH_FFMPEG_CONCURRENCY", "2")))
# Per-render parallel Drive downloads (I/O-bound; the Drive client retries).
_DOWNLOAD_CONCURRENCY = int(os.getenv("STITCH_DOWNLOAD_CONCURRENCY", "6"))

ProgressCb = Optional[Callable[[str], Awaitable[None]]]


def _extract_drive_file_id(url: str) -> Optional[str]:
    """Pull the Drive file id out of any of the URL shapes we store."""
    if not url:
        return None
    try:
        if "/file/d/" in url:
            return url.split("/file/d/")[1].split("/")[0]
        if "id=" in url:
            return url.split("id=")[1].split("&")[0]
        if "/open?id=" in url:
            return url.split("/open?id=")[1].split("&")[0]
    except (IndexError, AttributeError):
        return None
    return None


def _google_client():
    """Authorized Drive client (immune to public-link interstitials).

    The backend process already adds skills/video-pipeline to sys.path; insert
    defensively so this module also imports cleanly from a standalone script.
    """
    import sys

    pipeline_path = Path(__file__).resolve().parents[2] / "skills" / "video-pipeline"
    if str(pipeline_path) not in sys.path:
        sys.path.insert(0, str(pipeline_path))
    from shared.clients.google_client import GoogleClient

    return GoogleClient()


async def _emit(on_progress: ProgressCb, msg: str) -> None:
    if on_progress is None:
        return
    try:
        await on_progress(msg)
    except Exception:
        pass  # progress is best-effort; never fail a render on a log hiccup


async def _run_subprocess(cmd: list[str]) -> tuple[int, str]:
    """Run a command without blocking the event loop. Returns (rc, stderr tail)."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    tail = (stderr or b"").decode("utf-8", "replace")[-2000:]
    return proc.returncode, tail


async def _probe_duration(path: str) -> float:
    """Total media duration in seconds via ffprobe (0.0 if it can't be read)."""
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", path,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    try:
        return float((out or b"").decode().strip())
    except (ValueError, AttributeError):
        return 0.0


async def _gather_clips(video_id: str, scene: Optional[int] = None) -> list[dict]:
    """Ordered (scene, image_index) clip rows that actually have a clip.

    video_id is a globally-unique UUID, so scoping by it alone is safe; the
    caller has already authorized the video against the tenant. Pass `scene` to
    stitch a single scene (ordered by image_index within it).
    """
    if scene is None:
        rows = await fetch_all(
            "SELECT scene, image_index, video_clip_url, video_duration "
            "FROM assets WHERE video_id = $1 AND video_clip_url IS NOT NULL "
            "ORDER BY scene, image_index",
            video_id,
        )
    else:
        rows = await fetch_all(
            "SELECT scene, image_index, video_clip_url, video_duration "
            "FROM assets WHERE video_id = $1 AND scene = $2 AND video_clip_url IS NOT NULL "
            "ORDER BY image_index",
            video_id, scene,
        )
    return [dict(r) for r in rows]


async def _download_clips(
    clips: list[dict], workdir: Path, on_progress: ProgressCb
) -> list[Path]:
    """Download every clip to workdir/clip_NNN.mp4, preserving order.

    Concurrency uses a **worker pool where each worker owns its own
    GoogleClient**. The Drive client is built on httplib2, which is NOT
    thread-safe — sharing one connection across concurrent downloads corrupts
    it ("'NoneType' object has no attribute 'read'"). Each worker downloads
    sequentially on its own connection, so N workers = N safe parallel streams.
    """
    paths: list[Optional[Path]] = [None] * len(clips)
    queue: asyncio.Queue[tuple[int, dict]] = asyncio.Queue()
    for i, row in enumerate(clips):
        queue.put_nowait((i, row))

    n_workers = max(1, min(_DOWNLOAD_CONCURRENCY, len(clips)))
    done = 0
    lock = asyncio.Lock()
    first_error: Optional[Exception] = None

    async def _worker() -> None:
        nonlocal done, first_error
        gc = _google_client()  # one connection per worker — never shared
        while first_error is None:
            try:
                i, row = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            url = row.get("video_clip_url") or ""
            local = workdir / f"clip_{i:03d}.mp4"
            try:
                file_id = _extract_drive_file_id(url)
                if file_id:
                    await asyncio.to_thread(gc.download_file_to_local, file_id, str(local))
                else:
                    # Non-Drive URL (e.g. Supabase public) — stream the bytes.
                    from storage import download_bytes
                    local.write_bytes(await download_bytes(url))
                if not local.exists() or local.stat().st_size == 0:
                    raise RuntimeError(
                        f"clip S{row.get('scene')}.{row.get('image_index')} "
                        f"downloaded empty ({url[:80]})"
                    )
                paths[i] = local
                async with lock:
                    done += 1
                    if done % 10 == 0 or done == len(clips):
                        await _emit(on_progress, f"Downloaded {done}/{len(clips)} clips")
            except Exception as e:  # stop the pool cleanly on first failure
                first_error = e
                return

    await asyncio.gather(*(_worker() for _ in range(n_workers)))
    if first_error is not None:
        raise first_error
    return [p for p in paths if p is not None]


def _even(n: float) -> int:
    """Nearest even int — H.264 needs even dimensions."""
    i = int(round(n))
    return i - (i % 2)


async def _probe_wh(path: str) -> tuple[int, int]:
    """(width, height) of the first real video stream (skips attached_pic)."""
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", path,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    try:
        w, h = (out or b"").decode().strip().split("x")[:2]
        return int(w), int(h)
    except (ValueError, AttributeError):
        return 0, 0


async def _choose_target(paths: list[Path], orientation: str) -> tuple[int, int, str]:
    """Pick one uniform output canvas for clips that may differ in size.

    Clips can be a MIX of orientations (e.g. one landscape intro + many portrait
    body clips). Locking the canvas to the first clip stretches all the others —
    so we scale+pad every clip onto a single canvas instead. The canvas matches
    the MAJORITY clip's aspect (so most clips fill it with no bars); the odd ones
    out get letter/pillar-boxed, never distorted. `orientation` forces a shape:
    'auto' follows the majority, 'portrait'/'landscape' override it. Env
    STITCH_TARGET_W/H wins over everything.
    """
    whs = [wh for wh in [await _probe_wh(str(p)) for p in paths] if wh[0] and wh[1]]
    if not whs:
        return 1920, 1080, "landscape"
    from collections import Counter
    mw, mh = Counter(whs).most_common(1)[0][0]
    maj_portrait = mh > mw
    o = orientation if orientation in ("portrait", "landscape") else (
        "portrait" if maj_portrait else "landscape")

    if o == "portrait":
        tw, th = (_even(mw * 1080 / mh), 1080) if maj_portrait else (1080, 1920)
    else:
        tw, th = (1920, _even(mh * 1920 / mw)) if not maj_portrait else (1920, 1080)

    tw = int(os.getenv("STITCH_TARGET_W") or tw)
    th = int(os.getenv("STITCH_TARGET_H") or th)
    return _even(tw), _even(th), o


async def _concat(paths: list[Path], out_path: Path, tw: int, th: int) -> str:
    """Normalize every clip onto a tw×th canvas and join them in ONE encode.

    Uses the ffmpeg `concat` *filter* (not the demuxer): each input is scaled to
    fit (aspect preserved), padded to the exact canvas (so mixed-orientation
    clips are letter/pillar-boxed, never stretched), forced to a constant frame
    rate + uniform SAR, and its audio resampled to a common rate — then all
    segments are concatenated. One encode = one consistent H.264 parameter set
    (so strict players like QuickTime don't freeze) and rebuilt timestamps (so
    audio and video can't drift). The malformed source timestamps + per-clip
    SPS/PPS + mjpeg attached-pic tracks are all discarded in the process.

    Returns "reencode". Raises on failure.
    """
    preset = os.getenv("STITCH_X264_PRESET", "veryfast")
    crf = os.getenv("STITCH_X264_CRF", "20")
    fps = os.getenv("STITCH_FPS", "24")

    inputs: list[str] = []
    pre: list[str] = []
    labels: list[str] = []
    for i, p in enumerate(paths):
        inputs += ["-i", str(p)]
        pre.append(
            f"[{i}:v]scale={tw}:{th}:force_original_aspect_ratio=decrease,"
            f"pad={tw}:{th}:-1:-1:color=black,setsar=1,fps={fps},format=yuv420p[v{i}];"
            f"[{i}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a{i}]"
        )
        labels.append(f"[v{i}][a{i}]")
    filtergraph = (";".join(pre) + ";" + "".join(labels)
                   + f"concat=n={len(paths)}:v=1:a=1[v][a]")
    # The graph is huge for many clips — pass it as a script file, not argv.
    script = out_path.parent / "filtergraph.txt"
    script.write_text(filtergraph)

    cmd = ["ffmpeg", "-y", *inputs,
           "-filter_complex_script", str(script),
           "-map", "[v]", "-map", "[a]",
           "-c:v", "libx264", "-preset", preset, "-crf", crf,
           "-pix_fmt", "yuv420p", "-video_track_timescale", "24000",
           "-c:a", "aac", "-ar", "48000", "-b:a", "192k",
           "-movflags", "+faststart", str(out_path)]

    async with _FFMPEG_SEM:
        rc, err = await _run_subprocess(cmd)

    if rc == 0 and out_path.exists() and await _probe_duration(str(out_path)) > 0:
        return "reencode"
    raise RuntimeError(f"ffmpeg concat re-encode failed (rc={rc}): {err[-600:]}")


def _safe_filename(title: str, fallback: str) -> str:
    base = "".join(c if c.isalnum() or c in " -_" else "_" for c in (title or "")).strip()
    base = "_".join(base.split())[:80]
    return base or fallback


async def stitch_video(
    video_id: str,
    tenant_id: str,
    *,
    title: str = "",
    orientation: str = "auto",
    scene: Optional[int] = None,
    on_progress: ProgressCb = None,
) -> dict:
    """Stitch a video's existing clips into one uploaded mp4.

    Pass `scene` to stitch just that scene (stored under scenes/, for the
    per-scene preview); omit it to stitch the whole video (the final render).
    orientation: 'auto' (follow the majority of clips), 'portrait', or
    'landscape'. Returns {final_video_url, duration_seconds, clip_count, method,
    resolution, orientation}. Raises ValueError if there are no clips,
    RuntimeError on ffmpeg failure.
    """
    clips = await _gather_clips(video_id, scene)
    if not clips:
        raise ValueError(
            f"No clips in scene {scene} to stitch — animate it first." if scene is not None
            else "No clips to stitch — animate the scenes first.")

    workdir = Path(tempfile.mkdtemp(prefix=f"stitch_{video_id[:8]}_"))
    try:
        await _emit(on_progress, f"Stitching {len(clips)} clips…")
        paths = await _download_clips(clips, workdir, on_progress)
        if len(paths) != len(clips):
            raise RuntimeError(
                f"only {len(paths)}/{len(clips)} clips downloaded — aborting "
                f"to avoid a video with gaps"
            )

        out_path = workdir / "stitched.mp4"
        tw, th, orient = await _choose_target(paths, orientation)
        await _emit(on_progress,
                    f"Normalizing {len(paths)} clips to {tw}x{th} ({orient}) & joining…")
        method = await _concat(paths, out_path, tw, th)
        duration = await _probe_duration(str(out_path))

        data = out_path.read_bytes()
        # Per-scene stitches overwrite a stable path (so a re-stitch replaces it);
        # the full render keeps a titled filename under final/.
        storage_path = (f"{video_id}/scenes/S{scene:02d}.mp4" if scene is not None
                        else f"{video_id}/final/{_safe_filename(title, 'render')}.mp4")
        await _emit(on_progress, f"Uploading {'scene ' + str(scene) if scene is not None else 'final'} video ({len(data) // (1024*1024)}MB)…")
        url = await upload_bytes(data, storage_path, "video/mp4", tenant_id)

        return {
            "final_video_url": url,
            "duration_seconds": round(duration, 1),
            "clip_count": len(clips),
            "method": method,
            "resolution": f"{tw}x{th}",
            "orientation": orient,
            "size_bytes": len(data),
        }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
