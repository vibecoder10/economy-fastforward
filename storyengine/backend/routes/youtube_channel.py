"""User's own YouTube channel endpoints.

Distinct from youtube_sync.py (metrics for videos already in our DB) and
niche.py (competitor channel scraping). This file handles fetching the
AUTHENTICATED USER's own channel videos — needed for Flow B onboarding
(detect existing-channel users, learn their voice from top performers).

Endpoints:
    GET /api/youtube/my-videos — user's top-performing videos from their
        connected YouTube channel. Uses their OAuth refresh token. Returns
        title, views, published_at, thumbnail, video_id for up to N videos.
"""
from __future__ import annotations

import os
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from auth import get_tenant_id
from database import fetch_one

router = APIRouter(prefix="/api/youtube", tags=["youtube-channel"])


async def _refresh_access_token(
    client_id: str, client_secret: str, refresh_token: str
) -> str | None:
    """Exchange a refresh token for a short-lived access token."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
    if resp.status_code != 200:
        return None
    return resp.json().get("access_token")


async def _fetch_uploads_playlist_id(
    client: httpx.AsyncClient, access_token: str
) -> str | None:
    """Every YouTube channel has an 'uploads' playlist that contains every
    video the channel has posted. We find it via the channels endpoint's
    contentDetails.relatedPlaylists.uploads field."""
    resp = await client.get(
        "https://www.googleapis.com/youtube/v3/channels",
        params={"part": "contentDetails", "mine": "true"},
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15.0,
    )
    if resp.status_code != 200:
        return None
    items = resp.json().get("items", [])
    if not items:
        return None
    return items[0].get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")


async def _fetch_playlist_video_ids(
    client: httpx.AsyncClient, access_token: str, playlist_id: str, max_videos: int = 50
) -> list[str]:
    """Walk the uploads playlist (paginated, 50 per page) to collect video IDs.
    We cap at max_videos to keep quota usage bounded."""
    ids: list[str] = []
    page_token: str | None = None
    while len(ids) < max_videos:
        params = {
            "part": "contentDetails",
            "playlistId": playlist_id,
            "maxResults": min(50, max_videos - len(ids)),
        }
        if page_token:
            params["pageToken"] = page_token
        resp = await client.get(
            "https://www.googleapis.com/youtube/v3/playlistItems",
            params=params,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15.0,
        )
        if resp.status_code != 200:
            break
        body = resp.json()
        for item in body.get("items", []):
            vid = item.get("contentDetails", {}).get("videoId")
            if vid:
                ids.append(vid)
        page_token = body.get("nextPageToken")
        if not page_token:
            break
    return ids


async def _fetch_video_details(
    client: httpx.AsyncClient, access_token: str, video_ids: list[str]
) -> list[dict]:
    """Batch-fetch title + stats for up to 50 video IDs per call."""
    if not video_ids:
        return []
    videos: list[dict] = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i : i + 50]
        resp = await client.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={"part": "snippet,statistics", "id": ",".join(batch)},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15.0,
        )
        if resp.status_code != 200:
            continue
        for item in resp.json().get("items", []):
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            thumb = snippet.get("thumbnails", {}).get("medium", {}).get("url", "")
            videos.append(
                {
                    "video_id": item.get("id", ""),
                    "title": snippet.get("title", ""),
                    "description": snippet.get("description", ""),
                    "published_at": snippet.get("publishedAt", ""),
                    "thumbnail": thumb,
                    "views": int(stats.get("viewCount", 0) or 0),
                    "likes": int(stats.get("likeCount", 0) or 0),
                    "comments": int(stats.get("commentCount", 0) or 0),
                }
            )
    return videos


@router.get("/my-videos")
async def my_videos(
    limit: int = Query(10, ge=1, le=50),
    sort: str = Query("views", pattern="^(views|recent)$"),
    tenant_id: str = Depends(get_tenant_id),
):
    """Fetch the authenticated user's own channel videos, ranked.

    Use cases:
        - Onboarding Flow B: detect existing-channel users + show their
          top performers so we can offer to auto-learn their voice.
        - Future: pick videos to analyze for voice / style / performance
          patterns without scraping.

    Returns:
        { videos: [...], channel_id: "...", total_scanned: int }
        Each video: { video_id, title, description, published_at, thumbnail,
                      views, likes, comments }

    Errors:
        404 when the user hasn't connected YouTube (no refresh_token on
            channel_profiles) — frontend should treat as "no existing channel"
            and skip the voice-learn step.
        503 when Google OAuth isn't configured on this environment.
        502 when YouTube API calls fail (quota, auth) — frontend should
            degrade gracefully, not block onboarding.
    """
    row = await fetch_one(
        "SELECT youtube_refresh_token, youtube_channel_id FROM channel_profiles WHERE tenant_id = $1",
        tenant_id,
    )
    refresh_token = row.get("youtube_refresh_token") if row else None
    if not refresh_token:
        raise HTTPException(status_code=404, detail="YouTube not connected")

    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(status_code=503, detail="Google OAuth not configured")

    access_token = await _refresh_access_token(client_id, client_secret, refresh_token)
    if not access_token:
        raise HTTPException(
            status_code=502,
            detail="Could not refresh YouTube access. Reconnect YouTube in Settings.",
        )

    async with httpx.AsyncClient(timeout=30.0) as client:
        uploads_playlist = await _fetch_uploads_playlist_id(client, access_token)
        if not uploads_playlist:
            raise HTTPException(
                status_code=502, detail="Could not locate your YouTube uploads playlist"
            )

        # Scan up to 50 of the user's most recent uploads, then rank. 50 is a
        # good balance: enough signal to find top performers, cheap in quota.
        video_ids = await _fetch_playlist_video_ids(
            client, access_token, uploads_playlist, max_videos=50
        )
        if not video_ids:
            return {
                "videos": [],
                "channel_id": row.get("youtube_channel_id", "") if row else "",
                "total_scanned": 0,
            }

        videos = await _fetch_video_details(client, access_token, video_ids)

    if sort == "views":
        videos.sort(key=lambda v: v["views"], reverse=True)
    else:  # recent
        videos.sort(key=lambda v: v["published_at"], reverse=True)

    return {
        "videos": videos[:limit],
        "channel_id": row.get("youtube_channel_id", "") if row else "",
        "total_scanned": len(videos),
    }
