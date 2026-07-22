"""Drive media proxy — serve Drive-hosted assets reliably without Supabase copies.

Google Drive's public links (uc?export=download, lh3 CDN) unpredictably degrade
into HTML interstitials, breaking <img> tags and Kie image ingestion. The
AUTHORIZED Drive API never does — so this endpoint streams the file bytes
through the backend, like the existing audio proxy does for voice tracks.

Security (C25a, tasks/storyengine-wiring-fix-checklist.md §S5-1 BLOCKER):
the proxy requires a tenant-scoped token AND the file id must appear in OUR
database columns *for that tenant* (asset images, character portraits,
storyboard grids, thumbnails). Before C25a the allowlist checked file ids
across the WHOLE database with no tenant clause and the route had no auth
dependency at all — a leaked/guessed 33-44 char Drive id served ANY tenant's
file to ANYONE. `<img>`/`<video>` tags can't send an Authorization header, so
auth travels the same way this codebase already trusts it to for SSE
(`auth.verify_token`'s own docstring: "Also accepts token via query_params
?token=") and for audio playback (`routes/videos.py::create_audio_token` /
`_audio_token_tenant`): a JWT in `?token=`, decoded with SESSION_SECRET,
carrying (or resolving to) a `tenant_id` claim. Two token shapes are valid:
  1. The user's own full session JWT (30 days) — what the browser already
     holds in localStorage for every fetch() call; the frontend reuses it
     unchanged for `<img src>`/`<video src>` (see frontend/src/lib/utils.ts
     `withMediaAuth`). This JWT's `tenant_id` claim is fixed at login (the
     account's HOME tenant) and `<img>`/`<video>` can't send the
     `X-Active-Tenant` header normal API calls use to switch client
     workspaces — so C25a-fix12 expands authorization to every tenant the
     account (`sub` claim) has a `memberships` row for, not just the claimed
     one (`_authorized_tenant_ids`). Fixes: an operator viewing a CLIENT
     channel got 404s on every freshly-drawn asset because the allowlist ran
     against their home tenant instead.
  2. A short-lived (`purpose: "media"`) token this module mints for backend
     code that fetches its OWN proxy over plain HTTP (routes/characters.py
     cast-sheet vision, routes/environments.py vision rewrite,
     pipeline_executor.py's talking-clip path) — those call sites already
     have `tenant_id` in scope and have no live user JWT to forward. This
     shape stays scoped to exactly the one tenant it was minted for.
Allowed ids are cached in memory PER AUTHORIZED-TENANT-SET (never leaked
across an unrelated set of tenants); responses carry a content-checksum ETag
so browsers revalidate cheaply (304)
instead of re-streaming 74 images per visit — and immediately see new pixels
when a file is replaced in place.
"""

import asyncio
import io
import logging
import os
import re
import threading
import time
import uuid as _uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt as pyjwt
from fastapi import APIRouter, HTTPException, Request, Response

from database import fetch_all, fetch_one

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/media", tags=["media"])

_FILE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,80}$")

# (file_id, sorted tuple of authorized tenant_id strings) -> (allowed, checked_at)
_allow_cache: dict[tuple[str, tuple[str, ...]], tuple[bool, float]] = {}
_ALLOW_TTL = 3600.0

# 2026-07-20 MCP go-live incident: the browser requested a freshly-drawn
# storyboard file milliseconds BEFORE its DB row landed (the write and the
# <img> request raced). The first lookup correctly missed and cached a
# NEGATIVE verdict for the full _ALLOW_TTL (1 hour) — every retry then
# 404'd straight out of memory (3-4ms) instead of re-querying a DB that, a
# moment later, plainly allowed the file. A negative result is a "not yet"
# far more often than a real attack, so it gets a much shorter TTL: still
# long enough to blunt a 404-hammering retry loop, short enough that a
# same-second write shows up almost immediately. Positive verdicts keep the
# long TTL — a file that's allowed today stays allowed.
_NEGATIVE_ALLOW_TTL = 10.0

# $2 is a uuid[] (ANY(...)) — see _authorized_tenant_ids: a browser session
# JWT authorizes every workspace the ACCOUNT has a membership in (C25a-fix12),
# not just the one tenant_id baked into the 30-day token at login.
_ALLOWLIST_SQL = """
SELECT 1 WHERE EXISTS (
    SELECT 1 FROM assets
    WHERE tenant_id = ANY($2::uuid[]) AND (image_url LIKE $1 OR drive_image_url LIKE $1 OR video_clip_url LIKE $1)
) OR EXISTS (
    SELECT 1 FROM video_characters WHERE tenant_id = ANY($2::uuid[]) AND reference_url LIKE $1
) OR EXISTS (
    SELECT 1 FROM scripts
    WHERE tenant_id = ANY($2::uuid[]) AND (
       storyboard_1_url LIKE $1 OR storyboard_2_url LIKE $1
       OR storyboard_3_url LIKE $1 OR storyboard_4_url LIKE $1
       OR storyboard_5_url LIKE $1 OR voice_over_url LIKE $1
       OR scene_video_url LIKE $1   -- per-scene stitched preview (Drive → proxy)
       -- per-segment dialogue voices live inside the jsonb timeline;
       -- audio-driven lip-sync models fetch them through the proxy
       OR dialogue_segments::text LIKE $1
    )
) OR EXISTS (
    SELECT 1 FROM videos
    WHERE tenant_id = ANY($2::uuid[]) AND (
       thumbnail_url LIKE $1 OR character_reference_url LIKE $1
       OR final_video_url LIKE $1
    )
) OR EXISTS (
    SELECT 1 FROM video_environments WHERE tenant_id = ANY($2::uuid[]) AND reference_url LIKE $1
) OR EXISTS (
    -- files dropped into the chat (character sheets need vision + cast-sheet
    -- fetches BEFORE any video_characters row exists)
    SELECT 1 FROM chat_assets WHERE tenant_id = ANY($2::uuid[]) AND storage_url LIKE $1
) OR EXISTS (
    -- the locked channel cast on the project (referenced by every new video)
    SELECT 1 FROM projects WHERE tenant_id = ANY($2::uuid[]) AND character_references::text LIKE $1
) OR EXISTS (
    -- roster reference photos (static_docu.py's machine-consistency cache) —
    -- the Roster tab's dashboard (pipeline_executor.py::roster_repair_
    -- dashboard) hands the browser this hosted_url straight from the cache,
    -- same Drive->proxy conversion (toDisplayImageUrl) every other card uses.
    -- Missing here meant every "verified" roster card's photo 401'd through
    -- the proxy despite the frontend already building the right URL shape.
    SELECT 1 FROM static_reference_cache WHERE tenant_id = ANY($2::uuid[]) AND hosted_url LIKE $1
)
"""


async def _is_allowed(file_id: str, tenant_ids) -> bool:
    """`tenant_ids`: every workspace this request is authorized to read media
    from (see _authorized_tenant_ids) — usually one, but a browser session
    JWT expands to the account's full membership set. Allowed if the file
    belongs to ANY tenant in the set."""
    ids = sorted({_uuid.UUID(str(t)) for t in tenant_ids}, key=str)
    if not ids:
        return False
    cache_key = (file_id, tuple(str(t) for t in ids))
    cached = _allow_cache.get(cache_key)
    if cached:
        was_allowed, checked_at = cached
        ttl = _ALLOW_TTL if was_allowed else _NEGATIVE_ALLOW_TTL
        if time.time() - checked_at < ttl:
            return was_allowed
    row = await fetch_one(_ALLOWLIST_SQL, f"%{file_id}%", ids)
    allowed = bool(row)
    _allow_cache[cache_key] = (allowed, time.time())
    return allowed


def mint_media_token(tenant_id, minutes: int = 60) -> str:
    """Short-lived token for backend code that fetches the media proxy over
    plain HTTP for a KNOWN tenant (no live user session to forward — e.g. cast
    sheet vision, environment vision rewrite, talking-clip generation). 60
    minutes covers the slowest caller (talking-video generation, whose own
    deadline env var TALKING_CLIP_DEADLINE defaults to 1200s) with margin.
    Never persist a URL carrying this token — mint fresh at the call site."""
    secret = os.getenv("SESSION_SECRET")
    if not secret:
        raise RuntimeError("SESSION_SECRET not configured")
    return pyjwt.encode(
        {
            "purpose": "media",
            "tenant_id": str(tenant_id),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=minutes),
            "iss": "storyengine",
        },
        secret,
        algorithm="HS256",
    )


def _decode_media_payload(token: Optional[str]) -> dict:
    """Decode + validate a media token (?token= — `<img>`/`<video>` can't
    send headers) into its JWT payload. Accepts either a short-lived
    `purpose: media` token from `mint_media_token()` or a full session JWT
    (same one the browser already uses for every other request — same
    precedent as `auth.verify_token`'s SSE query-param path). Dev token only
    when DEV_MODE=true. Raises 401 like a FastAPI auth dependency would.
    DB-FREE by design: every caller must finish this (auth) before touching
    the database (the allowlist, or — C25a-fix12 — the memberships table)."""
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    dev_token = os.getenv("DEV_TOKEN")
    if dev_token and token == dev_token and os.getenv("DEV_MODE") == "true":
        return {"tenant_id": os.getenv("DEV_TENANT_ID") or "00000000-0000-0000-0000-000000000000"}

    secret = os.getenv("SESSION_SECRET")
    if not secret:
        raise HTTPException(status_code=401, detail="Invalid token")
    try:
        payload = pyjwt.decode(token, secret, algorithms=["HS256"])
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    if not payload.get("tenant_id"):
        raise HTTPException(status_code=401, detail="Invalid token: no tenant")
    return payload


def _media_token_tenant(token: Optional[str]) -> _uuid.UUID:
    """Resolve a media token to the ONE tenant it claims (the JWT's own
    `tenant_id` — home tenant for a session JWT, the exact tenant for a
    backend-minted `purpose: media` token). Kept for the backend-minted-token
    shape and as the fail-safe tenant `_authorized_tenant_ids` always
    includes. Do NOT use this alone to authorize a browser <img>/<video>
    request against a client workspace — it only ever sees the token's own
    claim, never the account's other memberships; use
    `_authorized_tenant_ids` for that (C25a-fix12)."""
    payload = _decode_media_payload(token)
    try:
        return _uuid.UUID(str(payload["tenant_id"]))
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid token: bad tenant")


async def _authorized_tenant_ids(token: Optional[str]) -> list:
    """C25a-fix12: every workspace this media request may read from.

    Prod evidence (2026-07-20): an account's session JWT carries only the
    tenant_id it had at login (the account's HOME tenant, fixed for the
    token's 30-day life — see routes/google_auth.py's `_create_session_jwt`).
    `<img>`/`<video>` tags can't send the `X-Active-Tenant` header normal
    fetchApi() calls use to switch client workspaces, so every asset in a
    CLIENT channel (tenant 44ecc95a "PocoAPoco", operated by an account whose
    JWT tenant_id is ee93e6d1 "Slow English") 404'd — the allowlist ran
    against the wrong tenant and missed every time.

    Fix: a backend-minted `purpose: media` token (`mint_media_token`) is
    already tenant-scoped by construction (the caller — pipeline_executor.py,
    characters.py, environments.py, the Kie fetch path — always holds the
    correct tenant_id in scope when it mints) — return exactly that one
    tenant, unchanged from before this fix.

    A browser session JWT instead authorizes EVERY tenant the account
    (`sub` claim) has a `memberships` row for — one extra query, same pattern
    as auth.py's `_user_has_membership`/`get_tenant_id` memberships lookups —
    unioned with the JWT's own claimed tenant as a fail-safe (never narrows
    what a pre-fix12 token already had access to, e.g. if a membership read
    ever comes back empty for a legitimately logged-in account)."""
    payload = _decode_media_payload(token)
    claimed = _uuid.UUID(str(payload["tenant_id"]))

    if payload.get("purpose") == "media":
        return [claimed]

    account_id = payload.get("sub")
    if not account_id:
        # Dev token (no `sub` claim) or a stray token missing it — nothing
        # to expand against.
        return [claimed]

    rows = await fetch_all(
        "SELECT tenant_id FROM memberships WHERE user_id = $1", account_id,
    )
    tenant_ids = {claimed}
    for row in rows or []:
        try:
            tenant_ids.add(_uuid.UUID(str(row["tenant_id"])))
        except (ValueError, TypeError):
            continue
    return list(tenant_ids)


_google_client = None
_google_client_lock = threading.Lock()


def _drive_service():
    """Drive service for the calling thread.

    One GoogleClient is shared (so the OAuth token refreshes once, not per
    request - a fresh client per request added a token POST and a discovery
    build to every proxy hit). The service it hands back is PER-THREAD:
    sharing one googleapiclient service (= one httplib2/SSL connection)
    across to_thread workers corrupted the heap and crashed the backend
    twice on 2026-07-06.
    """
    global _google_client
    if _google_client is None:
        with _google_client_lock:
            if _google_client is None:
                import sys
                from pathlib import Path
                pipeline_path = Path(__file__).resolve().parents[3] / "skills" / "video-pipeline"
                if str(pipeline_path) not in sys.path:
                    sys.path.insert(0, str(pipeline_path))
                from shared.clients.google_client import GoogleClient
                # strict_folder: backend's shared app-owned Drive identity —
                # see google_client.py's DEFAULT_PARENT_FOLDER_ID docstring.
                _google_client = GoogleClient(strict_folder=True)
    return _google_client.drive_service


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
async def serve_drive_file(file_id: str, request: Request, token: Optional[str] = None):
    # Optional extension suffix (…/drive/<id>.png): some Kie model validators
    # (InfiniteTalk) reject URLs without a recognizable file type — the suffix
    # is cosmetic, the id alone addresses the file.
    import re as _re
    file_id = _re.sub(r"\.(png|jpe?g|webp|gif|mp3|mp4|wav|m4a)$", "", file_id, flags=_re.I)
    if not _FILE_ID_RE.match(file_id):
        raise HTTPException(status_code=400, detail="Invalid file id")
    tenant_ids = await _authorized_tenant_ids(token)
    if not await _is_allowed(file_id, tenant_ids):
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
