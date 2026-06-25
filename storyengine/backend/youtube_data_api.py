"""Fetch competitor channel videos via the official YouTube Data API v3.

Replaces yt-dlp scraping for metadata (views, publish dates, titles, etc.).
The official API is not bot-blocked on datacenter IPs and is free within quota.
Cost per channel refresh ≈ 3 units (channels.list + playlistItems.list +
videos.list), or ≈ 103 if a search.list fallback is needed to resolve the
channel id. Default project quota is 10,000 units/day (≈ 3,000 refreshes).

A single server-side API key (env YOUTUBE_API_KEY) reads PUBLIC data for every
tenant — competitor videos are public, so no per-user OAuth is needed.
"""
from __future__ import annotations

import re
from typing import Optional

import httpx

API_BASE = "https://www.googleapis.com/youtube/v3"


def _parse_iso8601_duration(s: str) -> int:
    """PT#H#M#S -> total seconds."""
    if not s:
        return 0
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s)
    if not m:
        return 0
    h, mi, se = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + se


async def _resolve_channel_id(
    channel_url: str, api_key: str, client: httpx.AsyncClient
) -> Optional[str]:
    """Resolve a channel URL/handle to a UC… channel id."""
    url = (channel_url or "").strip()

    m = re.search(r"/channel/(UC[\w-]+)", url)
    if m:
        return m.group(1)

    m = re.search(r"@([\w.\-]+)", url)
    if m:
        r = await client.get(
            f"{API_BASE}/channels",
            params={"part": "id", "forHandle": m.group(1), "key": api_key},
        )
        items = r.json().get("items") if r.status_code == 200 else None
        if items:
            return items[0]["id"]

    m = re.search(r"/user/([\w.\-]+)", url)
    if m:
        r = await client.get(
            f"{API_BASE}/channels",
            params={"part": "id", "forUsername": m.group(1), "key": api_key},
        )
        items = r.json().get("items") if r.status_code == 200 else None
        if items:
            return items[0]["id"]

    # Last resort: search by the /c/<name> segment (or trailing path / raw text).
    m = re.search(r"/c/([\w.\-]+)", url) or re.search(r"/([\w.\-]+)/?$", url)
    q = m.group(1) if m else url
    r = await client.get(
        f"{API_BASE}/search",
        params={"part": "id", "q": q, "type": "channel", "maxResults": 1, "key": api_key},
    )
    items = r.json().get("items") if r.status_code == 200 else None
    if items:
        return items[0]["id"].get("channelId")
    return None


async def fetch_single_video(youtube_id: str, api_key: str) -> Optional[dict]:
    """Fetch ONE video's public metadata via the YouTube Data API.

    Returns a dict whose keys match routes.niche._extract_video_info (the yt-dlp
    path) so it is a drop-in for the modeling extract step: video_id, title, url,
    views, likes, comment_count, channel, channel_url, published_at, thumbnail_url,
    duration_seconds, description. Transcript is NOT returned (the API has none —
    Supadata supplies it). Returns None if the video is not found.

    Unlike yt-dlp, this is not bot-blocked on datacenter IPs, so it returns real
    views/duration instead of the zeros that poison competitor_videos.
    """
    yid = (youtube_id or "").strip()
    if not yid:
        return None
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(
            f"{API_BASE}/videos",
            params={"part": "snippet,statistics,contentDetails", "id": yid, "key": api_key},
        )
        r.raise_for_status()
        items = r.json().get("items") or []
        if not items:
            return None
        v = items[0]
        sn = v.get("snippet", {})
        st = v.get("statistics", {})
        cd = v.get("contentDetails", {})
        thumbs = sn.get("thumbnails", {})
        thumb = (
            thumbs.get("maxres")
            or thumbs.get("high")
            or thumbs.get("medium")
            or thumbs.get("default")
            or {}
        ).get("url")
        cid = sn.get("channelId", "")
        return {
            "video_id": v["id"],
            "title": sn.get("title", ""),
            "url": f"https://www.youtube.com/watch?v={v['id']}",
            "views": int(st.get("viewCount", 0) or 0),
            "likes": int(st.get("likeCount", 0) or 0),
            "comment_count": int(st.get("commentCount", 0) or 0),
            "channel": sn.get("channelTitle", ""),
            "channel_url": f"https://www.youtube.com/channel/{cid}" if cid else "",
            "published_at": (sn.get("publishedAt") or "")[:10],
            "thumbnail_url": thumb,
            "transcript": None,
            "duration_seconds": _parse_iso8601_duration(cd.get("duration", "")),
            "description": (sn.get("description") or "")[:2000],
        }


async def fetch_channel_videos(
    channel_url: str, api_key: str, max_results: int = 30
) -> list[dict]:
    """Return fully-populated video stub dicts for a channel.

    Keys match what _run_scrape's Phase 2 consumes: id, title, url, view_count,
    like_count, comment_count, duration (seconds), description, thumbnail,
    published_at (ISO 8601), channel_name.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        channel_id = await _resolve_channel_id(channel_url, api_key, client)
        if not channel_id:
            raise RuntimeError(f"Could not resolve a channel id from {channel_url!r}")

        r = await client.get(
            f"{API_BASE}/channels",
            params={"part": "contentDetails,snippet", "id": channel_id, "key": api_key},
        )
        r.raise_for_status()
        items = r.json().get("items") or []
        if not items:
            raise RuntimeError(f"Channel not found: {channel_id}")
        ch = items[0]
        uploads = ch["contentDetails"]["relatedPlaylists"]["uploads"]
        channel_name = ch["snippet"]["title"]

        # Recent upload video ids
        video_ids: list[str] = []
        page: Optional[str] = None
        while len(video_ids) < max_results:
            params = {
                "part": "contentDetails",
                "playlistId": uploads,
                "maxResults": min(50, max_results - len(video_ids)),
                "key": api_key,
            }
            if page:
                params["pageToken"] = page
            r = await client.get(f"{API_BASE}/playlistItems", params=params)
            r.raise_for_status()
            data = r.json()
            for it in data.get("items", []):
                vid = it.get("contentDetails", {}).get("videoId")
                if vid:
                    video_ids.append(vid)
            page = data.get("nextPageToken")
            if not page:
                break

        if not video_ids:
            return []

        out: list[dict] = []
        for i in range(0, len(video_ids), 50):
            batch = video_ids[i : i + 50]
            r = await client.get(
                f"{API_BASE}/videos",
                params={
                    "part": "snippet,statistics,contentDetails",
                    "id": ",".join(batch),
                    "key": api_key,
                },
            )
            r.raise_for_status()
            for v in r.json().get("items", []):
                sn = v.get("snippet", {})
                st = v.get("statistics", {})
                cd = v.get("contentDetails", {})
                thumbs = sn.get("thumbnails", {})
                thumb = (
                    thumbs.get("maxres")
                    or thumbs.get("high")
                    or thumbs.get("medium")
                    or thumbs.get("default")
                    or {}
                ).get("url")
                out.append(
                    {
                        "id": v["id"],
                        "title": sn.get("title", ""),
                        "url": f"https://www.youtube.com/watch?v={v['id']}",
                        "view_count": int(st.get("viewCount", 0) or 0),
                        "like_count": int(st.get("likeCount", 0) or 0),
                        "comment_count": int(st.get("commentCount", 0) or 0),
                        "duration": _parse_iso8601_duration(cd.get("duration", "")),
                        "description": (sn.get("description") or "")[:2000],
                        "thumbnail": thumb,
                        "published_at": sn.get("publishedAt"),
                        "channel_name": sn.get("channelTitle", channel_name),
                    }
                )
        return out
