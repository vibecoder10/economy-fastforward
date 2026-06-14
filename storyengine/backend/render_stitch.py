"""Fast FFmpeg clip-stitch render.

For **grok_native** videos every clip already carries its own baked-in audio
(Grok voices the dialogue into the clip), so the "render" is just concatenating
the clips in scene/segment order. This bypasses Remotion entirely — no
``render_config.json``, no Whisper audio-sync, no muted-clip / narrator bug
(``Scene.tsx`` issues) — and is cheap enough to run many at once on one box:
clips from the same model share codec params, so the concat demuxer
**stream-copies** with ~zero CPU. A re-encode fallback handles the rare clip
whose params don't line up.

Designed to survive ~20 simultaneous renders on a small VPS:
  * each render works in its own ``tempfile`` dir (no shared ``public/`` like the
    Remotion path — that dir was a real collision hazard under concurrency);
  * a process-wide semaphore caps concurrent ffmpeg invocations so the
    re-encode fallback can never saturate the CPU;
  * downloads are I/O-bound and capped per-render;
  * ffmpeg runs via asyncio subprocess so it never blocks the event loop.

Public entry:
    await stitch_video(video_id, tenant_id, on_progress=None) -> dict
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
_FFMPEG_SEM = asyncio.Semaphore(int(os.getenv("STITCH_FFMPEG_CONCURRENCY", "3")))
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


async def _gather_clips(video_id: str) -> list[dict]:
    """Ordered (scene, image_index) clip rows that actually have a clip.

    video_id is a globally-unique UUID, so scoping by it alone is safe; the
    caller has already authorized the video against the tenant.
    """
    rows = await fetch_all(
        "SELECT scene, image_index, video_clip_url, video_duration "
        "FROM assets WHERE video_id = $1 AND video_clip_url IS NOT NULL "
        "ORDER BY scene, image_index",
        video_id,
    )
    return [dict(r) for r in rows]


async def _download_clips(
    clips: list[dict], workdir: Path, on_progress: ProgressCb
) -> list[Path]:
    """Download every clip to workdir/clip_NNN.mp4, preserving order."""
    gc = _google_client()
    sem = asyncio.Semaphore(_DOWNLOAD_CONCURRENCY)
    paths: list[Optional[Path]] = [None] * len(clips)
    done = 0
    lock = asyncio.Lock()

    async def _one(i: int, row: dict) -> None:
        nonlocal done
        url = row.get("video_clip_url") or ""
        file_id = _extract_drive_file_id(url)
        local = workdir / f"clip_{i:03d}.mp4"
        async with sem:
            if file_id:
                # Authorized Drive API download (retries internally).
                await asyncio.to_thread(gc.download_file_to_local, file_id, str(local))
            else:
                # Non-Drive URL (e.g. Supabase public) — stream the bytes.
                from storage import download_bytes
                data = await download_bytes(url)
                local.write_bytes(data)
        if not local.exists() or local.stat().st_size == 0:
            raise RuntimeError(
                f"clip S{row.get('scene')}.{row.get('image_index')} downloaded empty "
                f"({url[:80]})"
            )
        paths[i] = local
        async with lock:
            done += 1
            if done % 10 == 0 or done == len(clips):
                await _emit(on_progress, f"Downloaded {done}/{len(clips)} clips")

    await asyncio.gather(*(_one(i, r) for i, r in enumerate(clips)))
    return [p for p in paths if p is not None]


def _write_concat_list(paths: list[Path], list_path: Path) -> None:
    """ffmpeg concat-demuxer manifest (single-quote-escaped absolute paths)."""
    lines = []
    for p in paths:
        safe = str(p).replace("'", "'\\''")
        lines.append(f"file '{safe}'")
    list_path.write_text("\n".join(lines) + "\n")


async def _concat(paths: list[Path], list_path: Path, out_path: Path) -> str:
    """Concat clips into out_path. Try stream-copy first, then re-encode.

    Returns the method used ("copy" or "reencode"). Raises on total failure.
    """
    expected = 0.0
    for p in paths:  # rough expectation to validate the muxed output
        expected += await _probe_duration(str(p))

    async with _FFMPEG_SEM:
        # ── Fast path: stream copy (no transcode, ~zero CPU) ──────────────
        rc, err = await _run_subprocess([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_path),
            "-c", "copy", "-movflags", "+faststart", str(out_path),
        ])
        if rc == 0 and out_path.exists():
            got = await _probe_duration(str(out_path))
            # Accept if the muxed duration is within 5% of the sum of inputs.
            if got > 0 and (expected == 0 or got >= expected * 0.95):
                return "copy"

        # ── Fallback: re-encode through the demuxer (handles param drift /
        #    timestamp gaps the copy mux can't splice cleanly) ─────────────
        rc, err = await _run_subprocess([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_path),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-b:a", "192k",
            "-movflags", "+faststart", str(out_path),
        ])
        if rc == 0 and out_path.exists() and await _probe_duration(str(out_path)) > 0:
            return "reencode"

    raise RuntimeError(f"ffmpeg concat failed (rc={rc}): {err[-600:]}")


def _safe_filename(title: str, fallback: str) -> str:
    base = "".join(c if c.isalnum() or c in " -_" else "_" for c in (title or "")).strip()
    base = "_".join(base.split())[:80]
    return base or fallback


async def stitch_video(
    video_id: str,
    tenant_id: str,
    *,
    title: str = "",
    on_progress: ProgressCb = None,
) -> dict:
    """Stitch a video's existing clips into one mp4 and upload it.

    Returns {final_video_url, duration_seconds, clip_count, method}.
    Raises ValueError if there are no clips, RuntimeError on ffmpeg failure.
    """
    clips = await _gather_clips(video_id)
    if not clips:
        raise ValueError("No clips to stitch — animate the scenes first.")

    workdir = Path(tempfile.mkdtemp(prefix=f"stitch_{video_id[:8]}_"))
    try:
        await _emit(on_progress, f"Stitching {len(clips)} clips…")
        paths = await _download_clips(clips, workdir, on_progress)
        if len(paths) != len(clips):
            raise RuntimeError(
                f"only {len(paths)}/{len(clips)} clips downloaded — aborting "
                f"to avoid a video with gaps"
            )

        list_path = workdir / "concat.txt"
        out_path = workdir / "stitched.mp4"
        _write_concat_list(paths, list_path)

        await _emit(on_progress, "Joining clips with ffmpeg…")
        method = await _concat(paths, list_path, out_path)
        duration = await _probe_duration(str(out_path))

        data = out_path.read_bytes()
        fname = _safe_filename(title, "render") + ".mp4"
        await _emit(on_progress, f"Uploading final video ({len(data) // (1024*1024)}MB)…")
        url = await upload_bytes(
            data, f"{video_id}/final/{fname}", "video/mp4", tenant_id
        )

        return {
            "final_video_url": url,
            "duration_seconds": round(duration, 1),
            "clip_count": len(clips),
            "method": method,
            "size_bytes": len(data),
        }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
