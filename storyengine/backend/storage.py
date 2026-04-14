"""Storage backend for StoryEngine — Google Drive or Supabase Storage.

Supports two backends controlled by STORAGE_BACKEND env var:
  - "google_drive" (default): Uses Google Drive via pipeline's GoogleClient
  - "supabase": Uses Supabase Storage REST API with per-tenant isolation

Public API:
    upload_bytes(data, path, content_type, tenant_id) -> public URL
    download_bytes(url) -> bytes
    upload_from_url(source_url, path, content_type, tenant_id) -> public URL
    create_signed_url(path, tenant_id, expires_in) -> signed URL
"""

import asyncio
import os
import logging
import mimetypes
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# --- Configuration ---

STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "google_drive")
SUPABASE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "assets")

# --- Google Drive backend (existing) ---

_google_client = None
_root_folder_id: Optional[str] = None
_folder_cache: dict[str, str] = {}


def _get_google_client():
    """Lazy-init GoogleClient singleton. Raises on missing credentials."""
    global _google_client, _root_folder_id
    if _google_client is not None:
        return _google_client

    from shared.clients.google_client import GoogleClient
    _google_client = GoogleClient()

    root = _google_client.get_or_create_folder("StoryEngine Assets")
    _root_folder_id = root["id"]
    logger.info("Google Drive root folder: StoryEngine Assets (%s)", _root_folder_id)
    return _google_client


def _get_video_folder(video_id: str) -> str:
    """Get or create a Drive folder for a video under the root folder."""
    if video_id in _folder_cache:
        return _folder_cache[video_id]

    client = _get_google_client()
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
    """
    parts = path.split("/", 1)
    if len(parts) == 2:
        video_id = parts[0]
        filename = parts[1].replace("/", "_")
        return video_id, filename
    return "unsorted", path.replace("/", "_")


def _sync_upload_drive(data: bytes, path: str, content_type: str) -> str:
    """Synchronous upload to Google Drive. Returns public URL."""
    video_id, filename = _path_to_filename(path)
    folder_id = _get_video_folder(video_id)
    client = _get_google_client()

    result = client.upload_file(
        data, filename, folder_id, mime_type=content_type
    )
    file_id = result["id"]

    web_content_link = client.make_file_public(file_id)
    if web_content_link:
        return web_content_link

    return f"https://drive.google.com/uc?export=download&id={file_id}"


# --- Supabase Storage backend ---

def _supabase_headers() -> dict[str, str]:
    """Build auth headers for Supabase Storage REST API."""
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    return {
        "Authorization": f"Bearer {key}",
        "apikey": key,
    }


def _supabase_base_url() -> str:
    """Supabase Storage REST API base URL."""
    url = os.getenv("SUPABASE_URL", "")
    return f"{url}/storage/v1"


def _tenant_path(tenant_id: str, path: str) -> str:
    """Build tenant-scoped storage path: tenant_id/path."""
    return f"{tenant_id}/{path}"


async def _supabase_upload(data: bytes, path: str, content_type: str, tenant_id: str) -> str:
    """Upload bytes to Supabase Storage. Returns public URL."""
    full_path = _tenant_path(tenant_id, path)
    url = f"{_supabase_base_url()}/object/{SUPABASE_BUCKET}/{full_path}"

    headers = _supabase_headers()
    headers["Content-Type"] = content_type
    headers["x-upsert"] = "true"

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, content=data, headers=headers)
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Supabase Storage upload failed ({resp.status_code}): {resp.text}")

    # Return the public URL
    supabase_url = os.getenv("SUPABASE_URL", "")
    return f"{supabase_url}/storage/v1/object/public/{SUPABASE_BUCKET}/{full_path}"


async def create_signed_url(
    path: str,
    tenant_id: str,
    expires_in: int = 3600,
) -> str:
    """Create a signed URL for a Supabase Storage object.

    Args:
        path: Storage path (e.g. "video_id/grids/S1-B1.png").
        tenant_id: Tenant ID for scoping.
        expires_in: URL validity in seconds (default 1 hour).

    Returns:
        Signed URL string.

    Raises:
        RuntimeError: If backend is not supabase or API call fails.
    """
    if STORAGE_BACKEND != "supabase":
        raise RuntimeError("Signed URLs are only supported with supabase backend")

    full_path = _tenant_path(tenant_id, path)
    url = f"{_supabase_base_url()}/object/sign/{SUPABASE_BUCKET}/{full_path}"

    headers = _supabase_headers()
    headers["Content-Type"] = "application/json"

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json={"expiresIn": expires_in}, headers=headers)
        if resp.status_code != 200:
            raise RuntimeError(f"Supabase signed URL failed ({resp.status_code}): {resp.text}")
        data = resp.json()

    signed_path = data.get("signedURL", "")
    supabase_url = os.getenv("SUPABASE_URL", "")
    return f"{supabase_url}/storage/v1{signed_path}"


# --- Public API (backend-agnostic) ---

def _guess_content_type(path: str) -> str:
    ct, _ = mimetypes.guess_type(path)
    return ct or "application/octet-stream"


async def upload_bytes(
    data: bytes,
    path: str,
    content_type: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> str:
    """Upload bytes to storage and return a permanent public URL.

    Args:
        data: Raw file bytes.
        path: Storage path (e.g. "video_id/grids/S1-B1.png").
        content_type: MIME type. Auto-detected from path extension if not provided.
        tenant_id: Required for supabase backend (tenant isolation).

    Returns:
        Public URL string.
    """
    ct = content_type or _guess_content_type(path)

    if STORAGE_BACKEND == "supabase":
        if not tenant_id:
            raise ValueError("tenant_id is required for supabase storage backend")
        return await _supabase_upload(data, path, ct, tenant_id)

    return await asyncio.to_thread(_sync_upload_drive, data, path, ct)


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
    tenant_id: Optional[str] = None,
) -> str:
    """Download from a URL and upload to storage.

    Args:
        source_url: URL to download from.
        path: Storage path within the bucket.
        content_type: MIME type. Auto-detected from path extension if not provided.
        tenant_id: Required for supabase backend (tenant isolation).

    Returns:
        Permanent public URL.
    """
    data = await download_bytes(source_url)
    return await upload_bytes(data, path, content_type, tenant_id)
