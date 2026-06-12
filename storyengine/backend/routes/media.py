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
       -- per-segment dialogue voices live inside the jsonb timeline;
       -- audio-driven lip-sync models fetch them through the proxy
       OR dialogue_segments::text LIKE $1
) OR EXISTS (
    SELECT 1 FROM videos
    WHERE thumbnail_url LIKE $1 OR character_reference_url LIKE $1
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
        fileId=file_id, fields="mimeType,md5Checksum,modifiedTime"
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

    etag = f'"{meta.get("md5Checksum") or meta.get("modifiedTime") or file_id}"'
    cache_headers = {"Cache-Control": "public, no-cache", "ETag": etag}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=cache_headers)

    try:
        data = await asyncio.to_thread(_download_via_drive_api, file_id)
    except Exception as e:
        logger.warning("[media] drive fetch failed for %s: %s", file_id, str(e)[:200])
        raise HTTPException(status_code=502, detail="Couldn't fetch this file right now.")

    return Response(
        content=data,
        media_type=meta.get("mimeType") or "application/octet-stream",
        headers=cache_headers,
    )
