"""Supabase-native YouTube publishing: channel-agnostic SEO + per-tenant upload.

Replaces the legacy Airtable + shared-token path (skills/video-pipeline/upload),
which hardcoded the "Power Doctrine" geopolitics channel and a single shared
.youtube-token.json. Here:
  * SEO is driven ONLY by the video's own title + script and the tenant's real
    channel brand — no hardcoded niche, hashtags, or subscribe link.
  * Upload authenticates with the creator's OWN connected channel
    (channel_profiles.youtube_refresh_token), using the same GOOGLE_OAUTH_CLIENT_*
    that minted that token.
SEO output is stored on the videos table (seo_description / seo_tags / seo_hashtags).
"""
import asyncio
import json
import os
import re
import tempfile
from typing import Optional

from database import fetch_one, fetch_all, execute
from kie_unified import get_text_client_for_tenant
from youtube_quota import check_quota_available, quota_exceeded_message, record_units, upload_cost

# YouTube videoCategory ids. Education is our default — it fits ESL/explainer content
# far better than the old hardcoded "25" (News & Politics).
_CATEGORY_IDS = {
    "education": "27", "entertainment": "24", "howto": "26", "people": "22",
    "news": "25", "science": "28", "film": "1", "music": "10", "gaming": "20",
}
_DEFAULT_CATEGORY = "27"  # Education

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
    model = "claude-sonnet-4-6" if type(claude).__name__ == "AnthropicDirectClient" else None
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
                   description: Optional[str] = None, tags: Optional[list] = None) -> dict:
    """Persist creator-edited SEO so the upload uses exactly what they see on screen."""
    sets, vals = [], []
    if title is not None:
        vals.append(title[:100]); sets.append(f"video_title=${len(vals)}")
    if description is not None:
        vals.append(description); sets.append(f"seo_description=${len(vals)}")
    if tags is not None:
        clean = ",".join(str(t).strip().lower() for t in tags if str(t).strip())
        vals.append(clean); sets.append(f"seo_tags=${len(vals)}")
    if not sets:
        return {"status": "noop"}
    vals.extend([video_id, tenant_id])
    await execute(
        f"UPDATE videos SET {', '.join(sets)}, updated_at=now() "
        f"WHERE id=${len(vals)-1} AND tenant_id=${len(vals)}", *vals)
    return {"status": "saved"}


def _do_youtube_upload(refresh_token: str, video_path: str, thumb_path: Optional[str],
                       title: str, description: str, tags: list, category_id: str,
                       privacy: str, made_for_kids: bool) -> dict:
    """Blocking YouTube upload (googleapiclient is sync) — run via asyncio.to_thread.
    Uses the tenant's OWN refresh token + the OAuth app creds that minted it."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request as GoogleRequest
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("GOOGLE_OAUTH_CLIENT_ID/SECRET not configured")
    creds = Credentials(
        token=None, refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id, client_secret=client_secret,
        scopes=["https://www.googleapis.com/auth/youtube.upload"])
    creds.refresh(GoogleRequest())
    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)

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
        _status, resp = req.next_chunk()
    yt_id = resp["id"]
    if thumb_path and os.path.exists(thumb_path):
        try:
            youtube.thumbnails().set(
                videoId=yt_id,
                media_body=MediaFileUpload(thumb_path, mimetype="image/jpeg")).execute()
        except Exception:
            pass  # thumbnail is best-effort; the upload itself succeeded
    return {"youtube_video_id": yt_id,
            "youtube_url": f"https://www.youtube.com/watch?v={yt_id}"}


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
                                  made_for_kids: bool = False) -> dict:
    """Upload the rendered video to the tenant's OWN connected YouTube channel as an
    unlisted draft, using the stored SEO. Writes youtube_url/upload_status back."""
    v = await fetch_one(
        "SELECT video_title, final_video_url, thumbnail_url, seo_description, seo_tags, "
        "seo_category_id FROM videos WHERE id=$1 AND tenant_id=$2", video_id, tenant_id)
    if not v:
        return {"error": "video not found"}
    if not v["final_video_url"]:
        return {"error": "No rendered video to upload — render it first."}
    cp = await fetch_one(
        "SELECT youtube_refresh_token, youtube_channel_name FROM channel_profiles "
        "WHERE tenant_id=$1", tenant_id)
    if not (cp and cp["youtube_refresh_token"]):
        return {"error": "No YouTube channel connected. Connect one in Settings → first."}

    # Quota guard (checklist §3.4, C33): an upload is ~1,600-1,650 units out
    # of the shared 10,000/day Data API budget (one Google Cloud project
    # behind every tenant's OAuth token — see youtube_quota.py's module
    # docstring for why this check is GLOBAL, not per-tenant). Checked
    # BEFORE downloading the render/thumbnail so a blocked upload fails
    # fast instead of burning bandwidth on files it can't send. Fail-soft
    # by construction: check_quota_available() only ever returns ok=False
    # from a real counted total, never from a tracker error (that case
    # reads as "0 used" and passes through).
    est_cost = upload_cost(has_thumbnail=bool(v["thumbnail_url"]))
    quota_ok, quota_status = await check_quota_available(est_cost)
    if not quota_ok:
        return {"error": quota_exceeded_message(quota_status), "quota_exceeded": True}

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
    try:
        await _download_to_local(v["final_video_url"], vpath)
        thumb = None
        if v["thumbnail_url"]:
            try:
                await _download_to_local(v["thumbnail_url"], tpath)
                thumb = tpath
            except Exception:
                thumb = None
        result = await asyncio.to_thread(
            _do_youtube_upload, cp["youtube_refresh_token"], vpath, thumb,
            title, description, tags, category_id, privacy, made_for_kids)
        # Record ACTUAL spend (thumb may have failed to download and been
        # dropped above, so re-derive the real cost from what shipped rather
        # than the pre-flight estimate) after the upload succeeds — never
        # before, so a failed upload never falsely counts against the budget.
        await record_units(upload_cost(has_thumbnail=bool(thumb)), "videos.insert")
        await execute(
            "UPDATE videos SET youtube_video_id=$1, youtube_url=$2, upload_status='uploaded', "
            "upload_date=now(), status='uploaded_draft', updated_at=now() "
            "WHERE id=$3 AND tenant_id=$4",
            result["youtube_video_id"], result["youtube_url"], video_id, tenant_id)
        result["channel"] = cp["youtube_channel_name"]
        result["privacy"] = privacy
        return result
    finally:
        import shutil
        shutil.rmtree(workdir, ignore_errors=True)
