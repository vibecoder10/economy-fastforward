"""Supabase-native YouTube publishing: channel-agnostic SEO + per-tenant upload.

Replaces the legacy Airtable + shared-token path (skills/video-pipeline/upload),
which hardcoded the "Power Doctrine" geopolitics channel and a single shared
.youtube-token.json. Here:
  * SEO is driven ONLY by the video's own title + script and the tenant's real
    channel brand — no hardcoded niche, hashtags, or subscribe link.
  * Upload authenticates with the creator's OWN connected channel
    (channel_profiles.youtube_refresh_token), using the dedicated YouTube OAuth
    client (or the legacy shared Google OAuth pair during migration).
SEO output is stored on the videos table (seo_description / seo_tags / seo_hashtags).
"""
import asyncio
import json
import os
import re
import tempfile
import time
import uuid
from typing import Optional

from PIL import Image

from database import fetch_one, fetch_all, execute
from kie_unified import get_text_client_for_tenant
from youtube_quota import (
    quota_exceeded_message,
    release_upload_reservation,
    reserve_thumbnail,
    reserve_upload,
)
from youtube_oauth_config import get_youtube_oauth_credentials
# Single Claude tier source (checklist §3.4 / C35) — see shared.channel_profile.
from actions import claude_model_for_direct_client

# YouTube videoCategory ids. Education is our default — it fits ESL/explainer content
# far better than the old hardcoded "25" (News & Politics).
_CATEGORY_IDS = {
    "education": "27", "entertainment": "24", "howto": "26", "people": "22",
    "news": "25", "science": "28", "film": "1", "music": "10", "gaming": "20",
}
_DEFAULT_CATEGORY = "27"  # Education
_YOUTUBE_THUMBNAIL_MAX_BYTES = 2_000_000
_THUMBNAIL_RETRY_DELAYS = (0.25, 0.5)
_VALID_PRIVACY_STATUSES = {"private", "unlisted", "public"}

_SEO_SYSTEM = (
    "You are a YouTube SEO specialist. Write metadata for ONE specific video, driven "
    "only by that video's real title and script and its actual audience. Never assume a "
    "niche, brand, or topic that is not in the content. Output ONLY valid JSON."
)


def _seo_prompt(channel: str, niche: str, audience: str, title: str, script: str) -> str:
    ctx = []
    if channel:
        ctx.append(f'Channel: "{channel}"')
    if niche:
        ctx.append(f"Niche: {niche}")
    if audience:
        ctx.append(f"Audience: {audience}")
    ctx_block = ("\n".join(ctx) + "\n\n") if ctx else ""
    return (
        f"{ctx_block}VIDEO TITLE: {title}\n\nSCRIPT (excerpt):\n{script[:3500]}\n\n"
        "Write metadata that matches THIS video's real topic and audience:\n"
        "- description: 3-5 short sentences. The first sentence is a hook that front-loads "
        "the main keyword; then say what the viewer will learn or watch, in plain language "
        "that fits the video. No keyword stuffing, no emoji spam.\n"
        "- tags: 12-15 lowercase YouTube tags, every one genuinely relevant to this video "
        "(mix broad and specific).\n"
        "- hashtags: exactly 3 relevant words (no # prefix).\n"
        "- category: one of education, entertainment, howto, people, news, science.\n\n"
        'Respond with ONLY JSON: {"description":"...","tags":["..."],'
        '"hashtags":["a","b","c"],"category":"education"}'
    )


def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        text = m.group(0)
    return json.loads(text)


async def generate_and_store_seo(video_id: str, tenant_id: str) -> dict:
    """Generate channel-appropriate SEO from the video's own content and store it on
    the videos row. Returns {description, tags, hashtags, category_id, channel}."""
    v = await fetch_one(
        "SELECT video_title FROM videos WHERE id=$1 AND tenant_id=$2", video_id, tenant_id)
    if not v:
        return {"error": "video not found"}
    title = v["video_title"] or "Untitled"
    scenes = await fetch_all(
        "SELECT scene_text FROM scripts WHERE video_id=$1 AND tenant_id=$2 "
        "AND scene_text IS NOT NULL ORDER BY scene", video_id, tenant_id)
    script = "\n".join((s["scene_text"] or "") for s in scenes)[:4000]

    cp = await fetch_one(
        "SELECT channel_name, youtube_channel_name, niche, target_audience "
        "FROM channel_profiles WHERE tenant_id=$1", tenant_id)
    channel = ((cp and (cp["channel_name"] or cp["youtube_channel_name"])) or "").strip()
    niche = ((cp and cp["niche"]) or "").strip()
    audience = ((cp and cp["target_audience"]) or "").strip()

    claude = await get_text_client_for_tenant(tenant_id)
    model = claude_model_for_direct_client(claude)
    kwargs = dict(prompt=_seo_prompt(channel, niche, audience, title, script),
                  system_prompt=_SEO_SYSTEM, max_tokens=900, temperature=0.5)
    if model:
        kwargs["model"] = model
    raw = await claude.generate(**kwargs)
    data = _parse_json(raw)

    body = (data.get("description") or "").strip()
    tags = [str(t).strip().lower() for t in (data.get("tags") or []) if str(t).strip()][:15]
    hashtags = [re.sub(r"[^A-Za-z0-9]", "", str(h)) for h in (data.get("hashtags") or []) if str(h).strip()]
    hashtags = [h for h in hashtags if h][:3]
    category = _CATEGORY_IDS.get(str(data.get("category", "")).strip().lower(), _DEFAULT_CATEGORY)

    parts = [body]
    if channel:
        parts.append(f"\nSubscribe for more from {channel}.")
    if hashtags:
        parts.append("\n" + " ".join("#" + h for h in hashtags))
    description = "\n".join(p for p in parts if p).strip()
    hashtag_str = " ".join("#" + h for h in hashtags)

    await execute(
        "UPDATE videos SET seo_description=$1, seo_tags=$2, seo_hashtags=$3, "
        "seo_category_id=$4, updated_at=now() WHERE id=$5 AND tenant_id=$6",
        description, ",".join(tags), hashtag_str, category, video_id, tenant_id)
    return {"description": description, "tags": tags, "hashtags": hashtags,
            "category_id": category, "channel": channel}


async def save_seo(video_id: str, tenant_id: str, *, title: Optional[str] = None,
                   description: Optional[str] = None, tags: Optional[list] = None,
                   category_id: Optional[str] = None) -> dict:
    """Persist creator-edited SEO so the upload uses exactly what they see on screen.

    category_id (C49, checklist "pre-publish: read/edit ... category" — this
    field previously had NO post-generate write path at all, only
    generate_and_store_seo()'s own computed value; same "extend the existing
    allowlist" precedent as C47's style_preset_id on update_video). Accepts
    either a raw YouTube videoCategory id ("27") or one of the same friendly
    names generate_and_store_seo() itself resolves via _CATEGORY_IDS
    ("education", "howto", ...) so a creator/agent doesn't need to know the
    numeric ids YouTube uses internally.
    """
    sets, vals = [], []
    if title is not None:
        vals.append(title[:100]); sets.append(f"video_title=${len(vals)}")
    if description is not None:
        vals.append(description); sets.append(f"seo_description=${len(vals)}")
    if tags is not None:
        clean = ",".join(str(t).strip().lower() for t in tags if str(t).strip())
        vals.append(clean); sets.append(f"seo_tags=${len(vals)}")
    if category_id is not None:
        resolved = _CATEGORY_IDS.get(str(category_id).strip().lower(), str(category_id).strip())
        vals.append(resolved); sets.append(f"seo_category_id=${len(vals)}")
    if not sets:
        return {"status": "noop"}
    vals.extend([video_id, tenant_id])
    await execute(
        f"UPDATE videos SET {', '.join(sets)}, updated_at=now() "
        f"WHERE id=${len(vals)-1} AND tenant_id=${len(vals)}", *vals)
    return {"status": "saved"}


class YouTubeUploadAttemptError(RuntimeError):
    """Upload failure annotated with whether videos.insert reached the wire."""

    def __init__(self, message: str, *, video_insert_attempted: bool):
        super().__init__(message)
        self.video_insert_attempted = video_insert_attempted


def _youtube_upload_result(
    yt_id: str,
    thumbnail_succeeded: bool,
    thumbnail_error: Optional[str] = None,
) -> dict:
    """Pure result seam used by the blocking SDK adapter and unit tests."""
    return {
        "youtube_video_id": yt_id,
        "youtube_url": f"https://www.youtube.com/watch?v={yt_id}",
        "thumbnail_succeeded": thumbnail_succeeded,
        "thumbnail_error": thumbnail_error,
    }


def _normalize_thumbnail(source: str, destination: str) -> None:
    """Write a real RGB JPEG that stays below YouTube's 2 MB limit."""
    with Image.open(source) as opened:
        image = opened.convert("RGB")

    quality = 92
    while True:
        image.save(destination, format="JPEG", quality=quality, optimize=True)
        if os.path.getsize(destination) < _YOUTUBE_THUMBNAIL_MAX_BYTES:
            return
        if quality > 55:
            quality -= 8
            continue
        width, height = image.size
        if width <= 320 or height <= 180:
            raise RuntimeError("could not compress thumbnail below YouTube's 2 MB limit")
        image = image.resize(
            (max(320, int(width * 0.85)), max(180, int(height * 0.85))),
            Image.Resampling.LANCZOS,
        )
        quality = 85


def _transient_youtube_error(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "resp", None), "status", None)
    return status in {408, 429, 500, 502, 503, 504} or isinstance(
        exc, (ConnectionError, TimeoutError)
    )


def _set_youtube_thumbnail(
    youtube,
    youtube_video_id: str,
    thumb_path: str,
    media_factory,
    *,
    sleep=time.sleep,
) -> dict:
    """Apply one normalized thumbnail, retrying only transient failures."""
    attempts = len(_THUMBNAIL_RETRY_DELAYS) + 1
    for attempt in range(attempts):
        try:
            youtube.thumbnails().set(
                videoId=youtube_video_id,
                media_body=media_factory(thumb_path, mimetype="image/jpeg"),
            ).execute()
            return {"thumbnail_succeeded": True, "thumbnail_error": None}
        except Exception as exc:  # google client exposes several exception types
            if attempt < attempts - 1 and _transient_youtube_error(exc):
                sleep(_THUMBNAIL_RETRY_DELAYS[attempt])
                continue
            return {
                "thumbnail_succeeded": False,
                "thumbnail_error": (
                    f"Thumbnail was not applied to YouTube video {youtube_video_id}: {exc}. "
                    "The video draft was saved; retry Upload to apply the thumbnail."
                ),
            }


def _build_youtube_client(refresh_token: str):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request as GoogleRequest
    from googleapiclient.discovery import build

    oauth = get_youtube_oauth_credentials()
    if oauth.missing_env:
        raise RuntimeError("YouTube OAuth client credentials not configured")
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=oauth.client_id,
        client_secret=oauth.client_secret,
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    creds.refresh(GoogleRequest())
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def _do_youtube_thumbnail(
    refresh_token: str, youtube_video_id: str, thumb_path: str
) -> dict:
    from googleapiclient.http import MediaFileUpload

    youtube = _build_youtube_client(refresh_token)
    return _set_youtube_thumbnail(
        youtube, youtube_video_id, thumb_path, MediaFileUpload
    )


def _do_youtube_upload_impl(
    refresh_token: str,
    video_path: str,
    thumb_path: Optional[str],
    title: str,
    description: str,
    tags: list,
    category_id: str,
    privacy: str,
    made_for_kids: bool,
    attempt_state: dict,
) -> dict:
    """Blocking YouTube upload (googleapiclient is sync) — run via asyncio.to_thread.
    Uses the tenant's OWN refresh token + the OAuth app creds that minted it."""
    from googleapiclient.http import MediaFileUpload

    youtube = _build_youtube_client(refresh_token)

    body = {
        "snippet": {"title": title, "description": description, "tags": tags,
                    "categoryId": category_id},
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": made_for_kids},
    }
    media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True,
                            chunksize=8 * 1024 * 1024)
    req = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        # next_chunk performs the resumable videos.insert HTTP request.
        attempt_state["video_insert_attempted"] = True
        _status, resp = req.next_chunk()
    yt_id = resp["id"]
    if thumb_path and os.path.exists(thumb_path):
        thumbnail = _set_youtube_thumbnail(
            youtube, yt_id, thumb_path, MediaFileUpload
        )
        return _youtube_upload_result(
            yt_id, thumbnail["thumbnail_succeeded"], thumbnail["thumbnail_error"]
        )
    return _youtube_upload_result(yt_id, False)


def _do_youtube_upload(refresh_token: str, video_path: str, thumb_path: Optional[str],
                       title: str, description: str, tags: list, category_id: str,
                       privacy: str, made_for_kids: bool) -> dict:
    """Blocking adapter with precise videos.insert attempt semantics."""
    attempt_state = {"video_insert_attempted": False}
    try:
        return _do_youtube_upload_impl(
            refresh_token,
            video_path,
            thumb_path,
            title,
            description,
            tags,
            category_id,
            privacy,
            made_for_kids,
            attempt_state,
        )
    except Exception as exc:
        raise YouTubeUploadAttemptError(
            str(exc),
            video_insert_attempted=attempt_state["video_insert_attempted"],
        ) from exc


def _do_youtube_video_insert(
    refresh_token: str,
    video_path: str,
    title: str,
    description: str,
    tags: list,
    category_id: str,
    privacy: str,
    made_for_kids: bool,
) -> dict:
    """Create one YouTube video and return its ID before thumbnail work.

    Queue delivery uses this smaller seam so the provider ID can be committed
    immediately. Once that ID is saved, every resume takes the existing-video
    path and cannot issue a second ``videos.insert``.
    """
    from googleapiclient.http import MediaFileUpload

    attempted = False
    try:
        youtube = _build_youtube_client(refresh_token)
        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": made_for_kids,
            },
        }
        media = MediaFileUpload(
            video_path,
            mimetype="video/mp4",
            resumable=True,
            chunksize=8 * 1024 * 1024,
        )
        request = youtube.videos().insert(
            part="snippet,status", body=body, media_body=media
        )
        response = None
        while response is None:
            attempted = True
            _status, response = request.next_chunk()
        return _youtube_upload_result(response["id"], False)
    except Exception as exc:
        raise YouTubeUploadAttemptError(
            str(exc), video_insert_attempted=attempted
        ) from exc


async def _verify_expected_owner_channel(
    refresh_token: str, expected_channel_id: str
) -> dict:
    """Resolve the OAuth owner's live channel and require the saved exact ID."""
    import httpx

    from youtube_oauth_config import get_youtube_oauth_credentials
    from youtube_owner_api import fetch_channel_summary, refresh_access_token

    oauth = get_youtube_oauth_credentials()
    if oauth.missing_env:
        return {"error": "YouTube OAuth client credentials not configured"}
    token = await refresh_access_token(
        oauth.client_id, oauth.client_secret, refresh_token
    )
    if not token:
        return {"error": "Could not verify the connected YouTube channel owner."}
    async with httpx.AsyncClient(timeout=15.0) as client:
        summary = await fetch_channel_summary(client, token)
    live_id = str((summary or {}).get("channel_id") or "").strip()
    if not live_id:
        return {"error": "The connected account did not return a YouTube channel."}
    if live_id != expected_channel_id:
        return {
            "error": "Connected YouTube channel does not match the delivery target.",
            "actual_channel_id": live_id,
        }
    return {"channel_id": live_id}


async def _download_to_local(url: str, dest: str) -> None:
    """Download a Drive (or Supabase) URL to a local path, reusing the proven
    authorized Drive path from render_stitch."""
    from render_stitch import _google_client, _extract_drive_file_id
    file_id = _extract_drive_file_id(url)
    if file_id:
        gc = _google_client()
        await asyncio.to_thread(gc.download_file_to_local, file_id, dest)
    else:
        from storage import download_bytes
        with open(dest, "wb") as f:
            f.write(await download_bytes(url))
    if not os.path.exists(dest) or os.path.getsize(dest) == 0:
        raise RuntimeError(f"downloaded empty from {url[:80]}")


async def upload_video_to_youtube(video_id: str, tenant_id: str, *,
                                  privacy: str = "unlisted",
                                  made_for_kids: bool = False,
                                  force_new_upload: bool = False,
                                  expected_channel_id: Optional[str] = None) -> dict:
    """Upload the rendered video to the tenant's OWN connected YouTube channel as an
    unlisted draft, using the stored SEO. Writes youtube_url/upload_status back."""
    privacy = str(privacy or "").strip().lower()
    if privacy not in _VALID_PRIVACY_STATUSES:
        return {"error": f"Unsupported YouTube privacy status: {privacy!r}"}
    expected_channel_id = str(expected_channel_id or "").strip() or None
    if expected_channel_id and privacy != "unlisted":
        return {
            "error": "Automatic queue delivery only supports unlisted uploads.",
            "blocked": True,
        }

    v = await fetch_one(
        "SELECT video_title, final_video_url, thumbnail_url, seo_description, seo_tags, "
        "seo_category_id, youtube_video_id, youtube_url, upload_status, "
        "queue_delivery_receipt "
        "FROM videos WHERE id=$1 AND tenant_id=$2", video_id, tenant_id)
    if not v:
        return {"error": "video not found"}
    saved_id = (v.get("youtube_video_id") or "").strip()
    saved_url = (v.get("youtube_url") or "").strip()
    retry_existing = bool(saved_id) and not force_new_upload
    if (
        expected_channel_id
        and not retry_existing
        and not force_new_upload
        and v.get("upload_status") in {"insert_in_flight", "insert_uncertain"}
    ):
        return {
            "error": (
                "A prior YouTube insert may have reached the provider without a saved "
                "video ID. Reconcile that attempt before retrying."
            ),
            "blocked": True,
            "insert_uncertain": True,
        }
    if not v["final_video_url"] and not retry_existing:
        return {"error": "No rendered video to upload — render it first."}
    cp = await fetch_one(
        "SELECT youtube_refresh_token, youtube_channel_name, youtube_channel_id "
        "FROM channel_profiles "
        "WHERE tenant_id=$1", tenant_id)
    if not (cp and cp["youtube_refresh_token"]):
        return {"error": "No YouTube channel connected. Connect one in Settings → first."}
    if expected_channel_id:
        saved_channel_id = str(cp.get("youtube_channel_id") or "").strip()
        if saved_channel_id != expected_channel_id:
            return {
                "error": "Saved YouTube channel does not match the delivery target.",
                "blocked": True,
            }
        owner = await _verify_expected_owner_channel(
            cp["youtube_refresh_token"], expected_channel_id
        )
        if owner.get("error"):
            return {**owner, "blocked": True}

    # PostgreSQL reserves exactly the call(s) this path will make. A retry of
    # an existing video's thumbnail never consumes or depends on upload quota.
    if retry_existing:
        quota_ok, quota_status = await reserve_thumbnail()
    else:
        quota_ok, quota_status = await reserve_upload(
            has_thumbnail=bool(v["thumbnail_url"])
        )
    if not quota_ok:
        return {"error": quota_exceeded_message(quota_status), "quota_exceeded": True}
    reservation = quota_status.get("reservation")

    title = (v["video_title"] or "Untitled")[:100]
    description = v["seo_description"] or title
    tags = [t.strip() for t in (v["seo_tags"] or "").split(",") if t.strip()]
    # C34c/S10-6: use the category the SEO pass actually computed for THIS
    # video's real content; only fall back to Education when SEO was never
    # generated (or predates migration 102) for this video.
    category_id = (v["seo_category_id"] or "").strip() or _DEFAULT_CATEGORY

    workdir = tempfile.mkdtemp(prefix=f"ytup_{video_id[:8]}_")
    vpath = os.path.join(workdir, "final.mp4")
    tpath = os.path.join(workdir, "thumb.jpg")
    release_upload = True
    release_general = bool(v["thumbnail_url"])
    try:
        thumb = None
        thumbnail_error = None
        if v["thumbnail_url"]:
            try:
                await _download_to_local(v["thumbnail_url"], tpath)
                normalized_path = os.path.join(workdir, "thumb-normalized.jpg")
                await asyncio.to_thread(_normalize_thumbnail, tpath, normalized_path)
                thumb = normalized_path
            except Exception as exc:
                thumbnail_error = (
                    f"Thumbnail source could not be prepared: {exc}. "
                    "The video draft was saved; retry Upload to apply the thumbnail."
                )

        if retry_existing:
            if not thumb:
                result = _youtube_upload_result(saved_id, False, thumbnail_error)
            else:
                thumbnail = await asyncio.to_thread(
                    _do_youtube_thumbnail,
                    cp["youtube_refresh_token"],
                    saved_id,
                    thumb,
                )
                result = _youtube_upload_result(
                    saved_id,
                    thumbnail["thumbnail_succeeded"],
                    thumbnail["thumbnail_error"],
                )
            release_upload = False
        else:
            await _download_to_local(v["final_video_url"], vpath)
            try:
                if expected_channel_id:
                    attempt_id = str(uuid.uuid4())
                    claim = await execute(
                        "UPDATE videos SET upload_status='insert_in_flight', "
                        "queue_delivery_receipt=$1::jsonb, updated_at=now() "
                        "WHERE id=$2 AND tenant_id=$3 "
                        "AND youtube_video_id IS NULL "
                        "AND COALESCE(upload_status, '') NOT IN "
                        "('insert_in_flight', 'insert_uncertain')",
                        json.dumps({
                            "status": "insert_in_flight",
                            "attempt_id": attempt_id,
                            "channel_id": expected_channel_id,
                            "privacy": "unlisted",
                        }),
                        video_id,
                        tenant_id,
                    )
                    if str(claim).endswith(" 0"):
                        return {
                            "error": "Another or uncertain YouTube insert already owns this video.",
                            "blocked": True,
                            "insert_uncertain": True,
                        }
                    result = await asyncio.to_thread(
                        _do_youtube_video_insert,
                        cp["youtube_refresh_token"],
                        vpath,
                        title,
                        description,
                        tags,
                        category_id,
                        privacy,
                        made_for_kids,
                    )
                    # The provider has consumed the upload even if the next
                    # database checkpoint fails. Never refund that quota slot.
                    release_upload = False
                    # This write intentionally precedes thumbnail work. A retry
                    # after this point can only repair the existing provider ID.
                    await execute(
                        "UPDATE videos SET youtube_video_id=$1, youtube_url=$2, "
                        "upload_status='video_created', queue_delivery_receipt=$3::jsonb, "
                        "upload_date=now(), status='uploaded_draft', updated_at=now() "
                        "WHERE id=$4 AND tenant_id=$5",
                        result["youtube_video_id"],
                        result["youtube_url"],
                        json.dumps({
                            "status": "video_created",
                            "attempt_id": attempt_id,
                            "channel_id": expected_channel_id,
                            "privacy": "unlisted",
                            "youtube_video_id": result["youtube_video_id"],
                        }),
                        video_id,
                        tenant_id,
                    )
                    if thumb:
                        thumbnail = await asyncio.to_thread(
                            _do_youtube_thumbnail,
                            cp["youtube_refresh_token"],
                            result["youtube_video_id"],
                            thumb,
                        )
                        result.update(thumbnail)
                else:
                    result = await asyncio.to_thread(
                        _do_youtube_upload, cp["youtube_refresh_token"], vpath, thumb,
                        title, description, tags, category_id, privacy, made_for_kids)
            except YouTubeUploadAttemptError as exc:
                # An attempted videos.insert consumes the reserved upload call even
                # when YouTube rejects/fails it. No thumbnail call succeeded.
                release_upload = not exc.video_insert_attempted
                if expected_channel_id:
                    marker_status = (
                        "insert_uncertain"
                        if exc.video_insert_attempted
                        else "insert_not_attempted"
                    )
                    upload_status = (
                        "insert_uncertain" if exc.video_insert_attempted else None
                    )
                    await execute(
                        "UPDATE videos SET upload_status=$1, "
                        "queue_delivery_receipt=$2::jsonb, updated_at=now() "
                        "WHERE id=$3 AND tenant_id=$4 AND youtube_video_id IS NULL",
                        upload_status,
                        json.dumps({
                            "status": marker_status,
                            "attempt_id": attempt_id,
                            "channel_id": expected_channel_id,
                            "privacy": "unlisted",
                            "error": str(exc)[:1000],
                        }),
                        video_id,
                        tenant_id,
                    )
                raise
            release_upload = False
            if thumbnail_error and not result.get("thumbnail_error"):
                result["thumbnail_error"] = thumbnail_error
        if (
            v["thumbnail_url"]
            and not result.get("thumbnail_succeeded")
            and not result.get("thumbnail_error")
        ):
            result["thumbnail_error"] = (
                f"Thumbnail was not applied to YouTube video {result['youtube_video_id']}. "
                "The video draft was saved; retry Upload to apply the thumbnail."
            )
        release_general = not bool(result.get("thumbnail_succeeded"))
        upload_status = (
            "uploaded"
            if result.get("thumbnail_succeeded") or not v["thumbnail_url"]
            else "thumbnail_failed"
        )
        persisted_url = saved_url if retry_existing and saved_url else result["youtube_url"]
        await execute(
            "UPDATE videos SET youtube_video_id=$1, youtube_url=$2, upload_status=$3, "
            "upload_date=now(), status='uploaded_draft', updated_at=now() "
            "WHERE id=$4 AND tenant_id=$5",
            result["youtube_video_id"], persisted_url, upload_status,
            video_id, tenant_id)
        result["channel"] = cp["youtube_channel_name"]
        result["privacy"] = privacy
        if result.get("thumbnail_error"):
            result["partial_error"] = result["thumbnail_error"]
        return result
    finally:
        import shutil
        shutil.rmtree(workdir, ignore_errors=True)
        await release_upload_reservation(
            reservation,
            release_upload=release_upload,
            release_general=release_general,
        )
