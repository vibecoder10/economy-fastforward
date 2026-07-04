"""Owner-authenticated YouTube Data API helpers.

Shared by the channel-first analytics sync (routes/youtube_sync.py) and the
channel voice/my-videos features (routes/youtube_channel.py). All calls use the
tenant's own OAuth access token ("mine" scope), never an API key, so they see
unlisted/private videos and never hit the bot-block that plagues scraping.
"""
from __future__ import annotations

import httpx

from youtube_data_api import _parse_iso8601_duration


async def refresh_access_token(
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


async def fetch_channel_summary(
    client: httpx.AsyncClient, access_token: str
) -> dict | None:
    """One channels.list call: identity + lifetime stats + uploads playlist id."""
    resp = await client.get(
        "https://www.googleapis.com/youtube/v3/channels",
        params={"part": "snippet,statistics,contentDetails", "mine": "true"},
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15.0,
    )
    if resp.status_code != 200:
        return None
    items = resp.json().get("items", [])
    if not items:
        return None
    item = items[0]
    snippet = item.get("snippet", {})
    stats = item.get("statistics", {})
    return {
        "channel_id": item.get("id", ""),
        "title": snippet.get("title", ""),
        "thumbnail": snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
        "subscriber_count": int(stats.get("subscriberCount", 0) or 0),
        "total_views": int(stats.get("viewCount", 0) or 0),
        "video_count": int(stats.get("videoCount", 0) or 0),
        "uploads_playlist": item.get("contentDetails", {})
        .get("relatedPlaylists", {})
        .get("uploads"),
    }


async def fetch_uploads_playlist_id(
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


async def fetch_playlist_video_ids(
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


async def fetch_video_details(
    client: httpx.AsyncClient, access_token: str, video_ids: list[str]
) -> list[dict]:
    """Batch-fetch snippet + stats + duration + privacy for up to 50 IDs per call."""
    if not video_ids:
        return []
    videos: list[dict] = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i : i + 50]
        resp = await client.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={"part": "snippet,statistics,contentDetails,status", "id": ",".join(batch)},
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
                    "duration_seconds": _parse_iso8601_duration(
                        item.get("contentDetails", {}).get("duration", "")
                    ),
                    "privacy_status": item.get("status", {}).get("privacyStatus"),
                }
            )
    return videos
