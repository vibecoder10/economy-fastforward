"""Fetch competitor channel videos via the official YouTube Data API v3.

Replaces yt-dlp scraping for metadata (views, publish dates, titles, etc.).
The official API is not bot-blocked on datacenter IPs and is free within quota.
Ordinary list calls consume the general-unit bucket. ``search.list`` uses
YouTube's separate daily search-call bucket. This module records each call
after it is issued; routes/youtube_sync.py has separate aggregation and does
not call this module, so the counters are not duplicated.

A single server-side API key (env YOUTUBE_API_KEY) reads PUBLIC data for every
tenant — competitor videos are public, so no per-user OAuth is needed.
"""
from __future__ import annotations

import re
from typing import Optional

import httpx

API_BASE = "https://www.googleapis.com/youtube/v3"


async def _record_general_call(operation: str) -> None:
    from youtube_quota import record_units

    await record_units(1, operation)


async def _reserve_search_call() -> None:
    from youtube_quota import quota_exceeded_message, reserve_search_call

    ok, status = await reserve_search_call()
    if not ok:
        raise RuntimeError(quota_exceeded_message(status))


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
        await _record_general_call("youtube_data_api.channels.list")
        items = r.json().get("items") if r.status_code == 200 else None
        if items:
            return items[0]["id"]

    m = re.search(r"/user/([\w.\-]+)", url)
    if m:
        r = await client.get(
            f"{API_BASE}/channels",
            params={"part": "id", "forUsername": m.group(1), "key": api_key},
        )
        await _record_general_call("youtube_data_api.channels.list")
        items = r.json().get("items") if r.status_code == 200 else None
        if items:
            return items[0]["id"]

    # Last resort: search by the /c/<name> segment (or trailing path / raw text).
    m = re.search(r"/c/([\w.\-]+)", url) or re.search(r"/([\w.\-]+)/?$", url)
    q = m.group(1) if m else url
    # Reserve atomically before invoking client.get. Once client.get begins,
    # retain the reservation even on an HTTP error because the request may
    # have reached YouTube and consumed the call bucket.
    await _reserve_search_call()
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
        await _record_general_call("youtube_data_api.videos.list")
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


async def fetch_live_video_ids(youtube_ids, api_key: str) -> set:
    """Return the subset of youtube_ids that STILL EXIST and are reachable on
    YouTube. Removed/deleted/private videos are simply absent from a videos.list
    response, so the returned set is the live ones. Batches 50 ids per call
    (part=id => 1 quota unit each).

    Fail-soft: on a missing key or any API error returns ALL input ids (treats them
    as live) so a hiccup never wrongly flags real videos as removed.
    """
    ids = [i for i in {(x or "").strip() for x in (youtube_ids or [])} if i]
    if not ids:
        return set()
    if not api_key:
        return set(ids)
    live: set = set()
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            for i in range(0, len(ids), 50):
                batch = ids[i : i + 50]
                r = await client.get(
                    f"{API_BASE}/videos",
                    params={"part": "id", "id": ",".join(batch), "key": api_key},
                )
                await _record_general_call("youtube_data_api.videos.list")
                r.raise_for_status()
                for v in r.json().get("items", []):
                    if v.get("id"):
                        live.add(v["id"])
    except Exception:  # noqa: BLE001 — never drop videos on an API hiccup
        return set(ids)
    return live


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
        await _record_general_call("youtube_data_api.channels.list")
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
            await _record_general_call("youtube_data_api.playlistItems.list")
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
            await _record_general_call("youtube_data_api.videos.list")
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
