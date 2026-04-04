"""Supabase Storage upload helper.

Uses the Supabase Storage REST API directly via httpx.
Requires env vars: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY.

Bucket: storyengine-assets (public-read, created on first upload).
"""

import os
import logging
import mimetypes
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

BUCKET = "storyengine-assets"
_bucket_ensured = False


def _get_config() -> tuple[str, str]:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set for storage"
        )
    return url.rstrip("/"), key


async def _ensure_bucket(client: httpx.AsyncClient, url: str, key: str) -> None:
    global _bucket_ensured
    if _bucket_ensured:
        return

    headers = {"apikey": key, "Authorization": f"Bearer {key}"}

    # Check if bucket exists
    resp = await client.get(f"{url}/storage/v1/bucket/{BUCKET}", headers=headers)
    if resp.status_code == 200:
        _bucket_ensured = True
        return

    # Create public bucket
    resp = await client.post(
        f"{url}/storage/v1/bucket",
        headers=headers,
        json={"id": BUCKET, "name": BUCKET, "public": True},
    )
    if resp.status_code in (200, 201):
        logger.info("Created Supabase Storage bucket: %s", BUCKET)
        _bucket_ensured = True
    elif resp.status_code == 409:
        # Already exists (race condition)
        _bucket_ensured = True
    else:
        raise RuntimeError(
            f"Failed to create bucket {BUCKET}: {resp.status_code} {resp.text}"
        )


def _guess_content_type(path: str) -> str:
    ct, _ = mimetypes.guess_type(path)
    return ct or "application/octet-stream"


async def upload_bytes(
    data: bytes,
    path: str,
    content_type: Optional[str] = None,
) -> str:
    """Upload bytes to Supabase Storage and return a permanent public URL.

    Args:
        data: Raw file bytes.
        path: Storage path within the bucket (e.g. "tenant_id/video_id/panel_01.png").
        content_type: MIME type. Auto-detected from path extension if not provided.

    Returns:
        Public URL string.
    """
    url, key = _get_config()
    ct = content_type or _guess_content_type(path)

    async with httpx.AsyncClient(timeout=60.0) as client:
        await _ensure_bucket(client, url, key)

        headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": ct,
            "x-upsert": "true",
        }

        resp = await client.post(
            f"{url}/storage/v1/object/{BUCKET}/{path}",
            headers=headers,
            content=data,
        )

        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"Storage upload failed: {resp.status_code} {resp.text}"
            )

    return f"{url}/storage/v1/object/public/{BUCKET}/{path}"


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
    """Download an image from a URL and upload it to Supabase Storage.

    Args:
        source_url: URL to download from (e.g. tempfile.aiquickdraw.com).
        path: Storage path within the bucket.
        content_type: MIME type. Auto-detected from path extension if not provided.

    Returns:
        Permanent public URL.
    """
    data = await download_bytes(source_url)
    return await upload_bytes(data, path, content_type)
