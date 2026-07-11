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
import threading
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# --- Configuration ---

STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "google_drive")
SUPABASE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "assets")

# --- Google Drive backend (existing) ---

_google_client = None
_google_client_lock = threading.Lock()
_root_folder_id: Optional[str] = None
_folder_cache: dict[str, str] = {}


def _get_google_client():
    """Lazy-init GoogleClient singleton. Raises on missing credentials.

    Locked: concurrent first calls from the to_thread pool used to double-init
    (two clients, two root-folder lookups). The client itself is safe to share
    across threads now - its Drive/Docs services are per-thread inside
    GoogleClient (see the 2026-07-06 heap-corruption note there).
    """
    global _google_client, _root_folder_id
    if _google_client is not None:
        return _google_client

    with _google_client_lock:
        if _google_client is not None:
            return _google_client
        from shared.clients.google_client import GoogleClient
        client = GoogleClient.from_env()
        _root_folder_id = client.get_or_create_folder("StoryEngine Assets")["id"]
        # Keep workspaces and legacy media beneath one visible app-owned root.
        client.workspace_root_folder_id = _root_folder_id
        _google_client = client
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


def _split_storage_path(path: str) -> tuple[str, Optional[str], str]:
    """"video_id/subdir/file.png" -> (video_id, "subdir", "file.png")."""
    parts = path.split("/")
    if len(parts) >= 3:
        return parts[0], parts[1], "_".join(parts[2:])
    if len(parts) == 2:
        return parts[0], None, parts[1]
    return "unsorted", None, path


def _get_or_create_child_folder(client, parent_id: str, name: str) -> str:
    """Scoped child-folder lookup. GoogleClient.get_or_create_folder searches
    by name GLOBALLY, so a generic name like 'characters' would collide across
    videos — this constrains the search to the parent."""
    cache_key = f"{parent_id}/{name}"
    if cache_key in _folder_cache:
        return _folder_cache[cache_key]
    escaped = name.replace("'", "\\'")
    query = (
        f"name = '{escaped}' and "
        f"'{parent_id}' in parents and "
        f"mimeType = 'application/vnd.google-apps.folder' and "
        f"trashed = false"
    )
    results = client.drive_service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])
    folder_id = files[0]["id"] if files else client.create_folder(name, parent_id=parent_id)["id"]
    _folder_cache[cache_key] = folder_id
    return folder_id


async def _resolve_video_drive_folder(video_id: str) -> str:
    """The video's ASSET FOLDER on Drive — the same title-named folder the
    pipeline bots upload scene images/clips/voice into. Everything saved
    through this module (portraits, grids, panels, briefs) lands beside them
    instead of a hidden 'StoryEngine Assets/<uuid>' tree. Falls back to the
    legacy uuid folder when the video row can't be resolved."""
    cache_key = f"video:{video_id}"
    if cache_key in _folder_cache:
        return _folder_cache[cache_key]

    title = None
    persisted_folder_id = None
    try:
        from database import fetch_one
        row = await fetch_one(
            "SELECT video_title, drive_folder_id FROM videos WHERE id = $1", video_id
        )
        title = ((row or {}).get("video_title") or "").strip() or None
        persisted_folder_id = (row or {}).get("drive_folder_id") or None
    except Exception:
        title = None

    def _sync_resolve() -> str:
        client = _get_google_client()
        if persisted_folder_id:
            return persisted_folder_id
        if title:
            return client.get_or_create_folder(
                title,
                parent_id=(getattr(client, "workspace_root_folder_id", None)
                           or client.parent_folder_id),
            )["id"]
        return _get_video_folder(video_id)

    folder_id = await asyncio.to_thread(_sync_resolve)
    _folder_cache[cache_key] = folder_id
    return folder_id


def _sync_upload_drive(data: bytes, path: str, content_type: str) -> str:
    """Synchronous upload to Google Drive (legacy uuid-folder layout)."""
    video_id, filename = _path_to_filename(path)
    folder_id = _get_video_folder(video_id)
    return _sync_upload_drive_into(data, filename, content_type, folder_id, None)


def _sync_upload_drive_into(data: bytes, filename: str, content_type: str,
                            folder_id: str, subfolder: Optional[str]) -> str:
    """Upload into a specific Drive folder (optionally a named subfolder)."""
    client = _get_google_client()
    # Canonical workspace labels are user-facing; normalize the pipeline's
    # lower-case storage path segments into those folders.
    workspace_subfolder = (
        {"images": "Images", "final": "Final Video"}.get(subfolder, subfolder)
        if subfolder else None
    )
    target = (_get_or_create_child_folder(client, folder_id, workspace_subfolder)
              if workspace_subfolder else folder_id)

    result = client.upload_file(
        data, filename, target, mime_type=content_type
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

    # Drive only — Supabase stays lean (profile/operational data, no media
    # blobs). Drive's public links degrade into HTML interstitials, so
    # browsers and Kie consume Drive files through the backend media proxy
    # (/api/media/drive/{id}), which streams via the authorized Drive API.
    video_id, subdir, filename = _split_storage_path(path)
    folder_id = await _resolve_video_drive_folder(video_id)
    return await asyncio.to_thread(_sync_upload_drive_into, data, filename, ct, folder_id, subdir)


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
