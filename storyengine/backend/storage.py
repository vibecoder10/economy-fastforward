"""Google Drive storage backend for StoryEngine.

Replaces Supabase Storage. All assets (grids, panels, images, thumbnails)
are uploaded to Google Drive under a "StoryEngine Assets" folder, organized
by video_id subfolders.

Uses the pipeline's GoogleClient (sync) wrapped in asyncio.to_thread().
Falls back to env vars for Google OAuth credentials.

Public API (unchanged from Supabase version):
    upload_bytes(data, path, content_type) -> public URL
    download_bytes(url) -> bytes
    upload_from_url(source_url, path, content_type) -> public URL
"""

import asyncio
import os
import logging
import mimetypes
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Lazy-initialized Google Drive client and folder cache
_google_client = None
_root_folder_id: Optional[str] = None
_folder_cache: dict[str, str] = {}  # video_id -> drive folder ID


def _get_google_client():
    """Lazy-init GoogleClient singleton. Raises on missing credentials."""
    global _google_client, _root_folder_id
    if _google_client is not None:
        return _google_client

    from shared.clients.google_client import GoogleClient
    _google_client = GoogleClient()

    # Create/find the root "StoryEngine Assets" folder
    root = _google_client.get_or_create_folder("StoryEngine Assets")
    _root_folder_id = root["id"]
    logger.info("Google Drive root folder: StoryEngine Assets (%s)", _root_folder_id)
    return _google_client


def _get_video_folder(video_id: str) -> str:
    """Get or create a Drive folder for a video under the root folder.

    Uses parent-scoped search to avoid collisions with other Drive folders.
    Results are cached for the lifetime of the process.
    """
    if video_id in _folder_cache:
        return _folder_cache[video_id]

    client = _get_google_client()

    # Search within the root folder specifically (not global search)
    escaped = video_id.replace("'", "\\'")
    query = (
        f"name = '{escaped}' and "
        f"'{_root_folder_id}' in parents and "
        f"mimeType = 'application/vnd.google-apps.folder' and "
        f"trashed = false"
    )
    results = client.drive_service.files().list(
        q=query, fields="files(id, name)"
    ).execute()
    files = results.get("files", [])

    if files:
        folder_id = files[0]["id"]
    else:
        folder = client.create_folder(video_id, parent_id=_root_folder_id)
        folder_id = folder["id"]

    _folder_cache[video_id] = folder_id
    return folder_id


def _path_to_filename(path: str) -> tuple[str, str]:
    """Convert a storage path to (video_id, filename).

    Input:  "abc-123/grids/S1-B1.png"
    Output: ("abc-123", "grids_S1-B1.png")

    Input:  "abc-123/extracted/S1-B1-P0.png"
    Output: ("abc-123", "extracted_S1-B1-P0.png")
    """
    parts = path.split("/", 1)
    if len(parts) == 2:
        video_id = parts[0]
        # Replace remaining slashes with underscores for flat folder structure
        filename = parts[1].replace("/", "_")
        return video_id, filename
    # Fallback: no video_id prefix
    return "unsorted", path.replace("/", "_")


def _sync_upload(data: bytes, path: str, content_type: str) -> str:
    """Synchronous upload to Google Drive. Returns public URL."""
    video_id, filename = _path_to_filename(path)
    folder_id = _get_video_folder(video_id)
    client = _get_google_client()

    result = client.upload_file(
        data, filename, folder_id, mime_type=content_type
    )
    file_id = result["id"]

    # Make public and get direct URL
    web_content_link = client.make_file_public(file_id)
    if web_content_link:
        return web_content_link

    # Fallback: construct URL manually
    return f"https://drive.google.com/uc?export=download&id={file_id}"


def _guess_content_type(path: str) -> str:
    ct, _ = mimetypes.guess_type(path)
    return ct or "application/octet-stream"


async def upload_bytes(
    data: bytes,
    path: str,
    content_type: Optional[str] = None,
) -> str:
    """Upload bytes to Google Drive and return a permanent public URL.

    Args:
        data: Raw file bytes.
        path: Storage path (e.g. "video_id/grids/S1-B1.png").
        content_type: MIME type. Auto-detected from path extension if not provided.

    Returns:
        Public URL string (Google Drive direct download link).
    """
    ct = content_type or _guess_content_type(path)
    return await asyncio.to_thread(_sync_upload, data, path, ct)


async def download_bytes(url: str) -> bytes:
    """Download raw bytes from any URL (tempfile, Drive, Supabase, etc.)."""
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        resp = await client.get(url)
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to download {url}: {resp.status_code}")
        return resp.content


async def upload_from_url(
    source_url: str,
    path: str,
    content_type: Optional[str] = None,
) -> str:
    """Download from a URL and upload to Google Drive.

    Args:
        source_url: URL to download from (e.g. tempfile.aiquickdraw.com).
        path: Storage path within the bucket.
        content_type: MIME type. Auto-detected from path extension if not provided.

    Returns:
        Permanent public URL (Google Drive).
    """
    data = await download_bytes(source_url)
    return await upload_bytes(data, path, content_type)
