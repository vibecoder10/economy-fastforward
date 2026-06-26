"""Drive media proxy — serve Drive-hosted assets reliably without Supabase copies.

Google Drive's public links (uc?export=download, lh3 CDN) unpredictably degrade
into HTML interstitials, breaking <img> tags and Kie image ingestion. The
AUTHORIZED Drive API never does — so this endpoint streams the file bytes
through the backend, like the existing audio proxy does for voice tracks.

Security: the proxy only serves file ids that appear in OUR database columns
(asset images, character portraits, storyboard grids, thumbnails). Without
that allowlist, a public proxy over an OAuth'd Drive would expose the entire
account. Allowed ids are cached in memory; responses carry a content-checksum
ETag so browsers revalidate cheaply (304) instead of re-streaming 74 images
per visit — and immediately see new pixels when a file is replaced in place.
"""

import asyncio
import io
import logging
import re
import time

from fastapi import APIRouter, HTTPException, Request, Response

from database import fetch_one

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/media", tags=["media"])

_FILE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,80}$")

# file_id -> (allowed: bool, checked_at)
_allow_cache: dict[str, tuple[bool, float]] = {}
_ALLOW_TTL = 3600.0

_ALLOWLIST_SQL = """
SELECT 1 WHERE EXISTS (
    SELECT 1 FROM assets
    WHERE image_url LIKE $1 OR drive_image_url LIKE $1 OR video_clip_url LIKE $1
) OR EXISTS (
    SELECT 1 FROM video_characters WHERE reference_url LIKE $1
) OR EXISTS (
    SELECT 1 FROM scripts
    WHERE storyboard_1_url LIKE $1 OR storyboard_2_url LIKE $1
       OR storyboard_3_url LIKE $1 OR storyboard_4_url LIKE $1
       OR storyboard_5_url LIKE $1 OR voice_over_url LIKE $1
       OR scene_video_url LIKE $1   -- per-scene stitched preview (Drive → proxy)
       -- per-segment dialogue voices live inside the jsonb timeline;
       -- audio-driven lip-sync models fetch them through the proxy
       OR dialogue_segments::text LIKE $1
) OR EXISTS (
    SELECT 1 FROM videos
    WHERE thumbnail_url LIKE $1 OR character_reference_url LIKE $1
       OR final_video_url LIKE $1
) OR EXISTS (
    SELECT 1 FROM video_environments WHERE reference_url LIKE $1
)
"""


async def _is_allowed(file_id: str) -> bool:
    cached = _allow_cache.get(file_id)
    if cached and time.time() - cached[1] < _ALLOW_TTL:
        return cached[0]
    row = await fetch_one(_ALLOWLIST_SQL, f"%{file_id}%")
    allowed = bool(row)
    _allow_cache[file_id] = (allowed, time.time())
    return allowed


def _drive_service():
    import sys
    from pathlib import Path
    pipeline_path = Path(__file__).resolve().parents[3] / "skills" / "video-pipeline"
    if str(pipeline_path) not in sys.path:
        sys.path.insert(0, str(pipeline_path))
    from shared.clients.google_client import GoogleClient
    return GoogleClient().drive_service


def _fetch_drive_meta(file_id: str) -> dict:
    return _drive_service().files().get(
        fileId=file_id, fields="mimeType,md5Checksum,modifiedTime,size"
    ).execute()


def _download_via_drive_api(file_id: str) -> bytes:
    """Authorized Drive download — immune to public-link interstitials."""
    from googleapiclient.http import MediaIoBaseDownload

    svc = _drive_service()
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, svc.files().get_media(fileId=file_id))
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


def _download_range(file_id: str, start: int, end: int) -> bytes:
    """Authorized Drive download of a byte range (inclusive). Lets the
    <video> element stream/seek the final render without pulling the whole
    file first. Drive honors the Range header and returns 206; if it ever
    ignores it the caller slices defensively."""
    svc = _drive_service()
    req = svc.files().get_media(fileId=file_id)
    req.headers["Range"] = f"bytes={start}-{end}"
    return req.execute()


@router.get("/drive/{file_id}")
async def serve_drive_file(file_id: str, request: Request):
    if not _FILE_ID_RE.match(file_id):
        raise HTTPException(status_code=400, detail="Invalid file id")
    if not await _is_allowed(file_id):
        raise HTTPException(status_code=404, detail="Not found")

    # Drive files are REPLACED IN PLACE on regeneration (same file id, new
    # pixels) — a long max-age made browsers show yesterday's image for a day.
    # ETag = content checksum: browsers revalidate every use, get a tiny 304
    # while unchanged, and refetch the moment the content actually changes.
    try:
        meta = await asyncio.to_thread(_fetch_drive_meta, file_id)
    except Exception as e:
        logger.warning("[media] drive meta failed for %s: %s", file_id, str(e)[:200])
        raise HTTPException(status_code=502, detail="Couldn't fetch this file right now.")

    mime = meta.get("mimeType") or "application/octet-stream"
    etag = f'"{meta.get("md5Checksum") or meta.get("modifiedTime") or file_id}"'
    try:
        total = int(meta.get("size") or 0)
    except (TypeError, ValueError):
        total = 0
    # Accept-Ranges lets <video> stream/seek the final render. Images keep
    # working through the plain full-body path below.
    base_headers = {"Cache-Control": "public, no-cache", "ETag": etag,
                    "Accept-Ranges": "bytes"}
    range_header = request.headers.get("range")

    if not range_header and request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=base_headers)

    # ── Ranged request (video scrubbing) → 206 Partial Content ──────────
    if range_header and total > 0:
        m = re.match(r"bytes=(\d+)-(\d*)", range_header.strip())
        if m:
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else total - 1
            end = min(end, total - 1)
            if start > end or start >= total:
                return Response(status_code=416,
                                headers={**base_headers,
                                         "Content-Range": f"bytes */{total}"})
            try:
                data = await asyncio.to_thread(_download_range, file_id, start, end)
            except Exception as e:
                logger.warning("[media] drive range fetch failed for %s: %s",
                               file_id, str(e)[:200])
                raise HTTPException(status_code=502,
                                    detail="Couldn't fetch this file right now.")
            if len(data) > (end - start + 1):  # Drive ignored Range — slice
                data = data[start:end + 1]
            return Response(
                content=data, status_code=206, media_type=mime,
                headers={**base_headers,
                         "Content-Range": f"bytes {start}-{end}/{total}",
                         "Content-Length": str(len(data))},
            )

    # ── Full body (images, or a client that didn't ask for a range) ─────
    try:
        data = await asyncio.to_thread(_download_via_drive_api, file_id)
    except Exception as e:
        logger.warning("[media] drive fetch failed for %s: %s", file_id, str(e)[:200])
        raise HTTPException(status_code=502, detail="Couldn't fetch this file right now.")

    return Response(
        content=data, media_type=mime,
        headers={**base_headers, "Content-Length": str(len(data))},
    )
