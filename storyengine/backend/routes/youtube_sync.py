"""YouTube Analytics sync — pulls CTR, views, impressions into videos table.

Uses Google OAuth2 (credentials from vault) to query:
1. YouTube Data API v3 — views, likes, comments, publish date
2. YouTube Analytics API v2 — avg view duration, retention, watch time

Impressions/CTR come from the YouTube Data API v3 (statistics part)
combined with Analytics API when available.

This closes the learning feedback loop:
Pipeline uploads → YouTube publishes → This sync pulls metrics →
Learning extraction detects patterns → Discovery uses patterns
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from auth import get_tenant_id
from database import fetch_all, fetch_one, execute, safe_column

router = APIRouter(prefix="/api/youtube", tags=["youtube-sync"])

# In-memory sync status per tenant
_sync_tasks: dict[str, dict] = {}

MAX_RETRIES = 2
RETRY_DELAY = 3.0  # seconds


def _classify_error(e: Exception) -> str:
    """Classify an error into a category for the status response."""
    msg = str(e).lower()
    if "401" in msg or "403" in msg or "unauthorized" in msg or "forbidden" in msg:
        return "auth"
    if "429" in msg or "rate" in msg or "quota" in msg:
        return "rate_limit"
    if "timeout" in msg or "timed out" in msg:
        return "timeout"
    if "connect" in msg or "network" in msg or "dns" in msg:
        return "network"
    if "404" in msg or "not found" in msg:
        return "not_found"
    if "500" in msg or "502" in msg or "503" in msg or "504" in msg:
        return "api"
    return "unknown"


def _is_retryable(error_type: str) -> bool:
    """Check if an error type is worth retrying."""
    return error_type in ("timeout", "network", "api", "rate_limit")


@router.post("/sync")
async def trigger_sync(
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Trigger YouTube metrics sync for all uploaded videos."""
    if _sync_tasks.get(tenant_id, {}).get("running"):
        return {"status": "already_running", "message": "Sync already in progress"}

    _sync_tasks[tenant_id] = {"running": True, "started": datetime.now(timezone.utc).isoformat()}
    background_tasks.add_task(_run_sync, tenant_id)
    return {"status": "started", "message": "YouTube metrics sync started"}


@router.get("/sync/status")
async def sync_status(tenant_id: str = Depends(get_tenant_id)):
    """Check sync task status."""
    task = _sync_tasks.get(tenant_id, {})
    return {
        "is_running": task.get("running", False),
        "videos_synced": task.get("videos_synced", 0),
        "videos_total": task.get("videos_total", 0),
        "videos_failed": task.get("videos_failed", 0),
        "videos_retried": task.get("videos_retried", 0),
        "errors": task.get("errors", []),
        "error": task.get("error"),
        "error_type": task.get("error_type"),
        "last_run": task.get("finished"),
    }


async def _run_sync(tenant_id: str):
    """Background task: sync YouTube metrics to videos table."""
    try:
        import os
        import httpx
        from vault import get_secret

        # Try YouTube OAuth token from channel_profiles first (per-user OAuth flow)
        yt_row = await fetch_one(
            "SELECT youtube_refresh_token FROM channel_profiles WHERE tenant_id = $1",
            tenant_id,
        )
        yt_refresh = yt_row.get("youtube_refresh_token") if yt_row else None

        if yt_refresh:
            # Use YouTube OAuth token with global OAuth client credentials
            client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
            client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
            refresh_token = yt_refresh
        else:
            # Fallback: legacy vault-based credentials
            client_id = await get_secret("google_client_id", tenant_id)
            client_secret = await get_secret("google_client_secret", tenant_id)
            refresh_token = await get_secret("google_refresh_token", tenant_id)

        if not all([client_id, client_secret, refresh_token]):
            _sync_tasks[tenant_id] = {
                "running": False,
                "error": "YouTube not connected. Go to Settings to connect your YouTube channel.",
                "error_type": "auth",
            }
            return

        # Get access token via refresh
        access_token = await _refresh_access_token(client_id, client_secret, refresh_token)
        if not access_token:
            _sync_tasks[tenant_id] = {"running": False, "error": "Failed to refresh Google access token"}
            return

        # Get all uploaded videos with youtube_video_id or youtube_url
        videos = await fetch_all(
            """SELECT id, youtube_video_id, youtube_url, upload_date,
                      views_24h, views_48h, views_7d, views_30d,
                      ctr_48h, retention_48h
               FROM videos
               WHERE tenant_id = $1
                 AND (youtube_video_id IS NOT NULL OR youtube_url IS NOT NULL)""",
            tenant_id,
        )

        if not videos:
            _sync_tasks[tenant_id] = {"running": False, "videos_synced": 0, "videos_total": 0,
                                       "finished": datetime.now(timezone.utc).isoformat()}
            return

        _sync_tasks[tenant_id]["videos_total"] = len(videos)
        synced = 0
        failed = 0
        errors = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            for video in videos:
                try:
                    video_id = video.get("youtube_video_id")
                    if not video_id and video.get("youtube_url"):
                        video_id = _extract_video_id(video["youtube_url"])

                    if not video_id:
                        continue

                    # Fetch stats from YouTube Data API (with retry for transient errors)
                    stats = await _fetch_with_retry(
                        _fetch_video_stats, client, access_token, video_id
                    )
                    if not stats:
                        failed += 1
                        errors.append({
                            "video_id": str(video.get("id")),
                            "error_type": "stats_unavailable",
                            "message": "Could not fetch video stats",
                        })
                        _sync_tasks[tenant_id]["videos_failed"] = failed
                        continue

                    # Fetch analytics from YouTube Analytics API
                    upload_date = video.get("upload_date")
                    if not upload_date and stats.get("published_at"):
                        upload_date = stats["published_at"]

                    analytics = await _fetch_with_retry(
                        _fetch_video_analytics, client, access_token, video_id, upload_date
                    )

                    # Build update fields
                    update_fields = {
                        "views": stats.get("views", 0),
                        "likes": stats.get("likes", 0),
                        "comments": stats.get("comments", 0),
                        "last_analytics_sync": datetime.now(timezone.utc).isoformat(),
                    }

                    if not video.get("youtube_video_id"):
                        update_fields["youtube_video_id"] = video_id

                    if stats.get("published_at") and not video.get("upload_date"):
                        update_fields["upload_date"] = stats["published_at"]

                    if analytics:
                        if analytics.get("avg_view_duration") is not None:
                            update_fields["avg_view_duration_seconds"] = analytics["avg_view_duration"]
                        if analytics.get("avg_retention") is not None:
                            update_fields["avg_retention"] = analytics["avg_retention"]
                        if analytics.get("watch_time_hours") is not None:
                            update_fields["watch_time_hours"] = analytics["watch_time_hours"]
                        if analytics.get("subscribers_gained") is not None:
                            update_fields["subscribers_gained"] = analytics["subscribers_gained"]
                        if analytics.get("impressions") is not None:
                            update_fields["impressions"] = analytics["impressions"]
                        if analytics.get("ctr") is not None:
                            update_fields["ctr"] = analytics["ctr"]

                    # Calculate snapshots (write-once fields)
                    snapshots = _calculate_snapshots(video, stats, analytics, upload_date)
                    update_fields.update(snapshots)

                    # Build dynamic UPDATE query
                    set_parts = []
                    values = []
                    for i, (key, val) in enumerate(update_fields.items(), start=1):
                        set_parts.append(f"{safe_column(key)} = ${i}")
                        values.append(val)

                    values.append(str(video["id"]))
                    param_idx = len(values)

                    # SECURITY: column names from hardcoded update_fields dict keys + safe_column(), values use $N params
                    await execute(
                        f"UPDATE videos SET {', '.join(set_parts)} WHERE id = ${param_idx}",
                        *values,
                    )

                    synced += 1
                    _sync_tasks[tenant_id]["videos_synced"] = synced

                except Exception as e:
                    error_type = _classify_error(e)
                    failed += 1
                    errors.append({
                        "video_id": str(video.get("id")),
                        "error_type": error_type,
                        "message": str(e)[:200],
                    })
                    _sync_tasks[tenant_id]["videos_failed"] = failed
                    print(f"[YouTubeSync] Error syncing video {video.get('id')} ({error_type}): {e}")
                    continue

        _sync_tasks[tenant_id] = {
            "running": False,
            "videos_synced": synced,
            "videos_total": len(videos),
            "videos_failed": failed,
            "errors": errors[-10:],  # Keep last 10 errors
            "finished": datetime.now(timezone.utc).isoformat(),
        }
        print(f"[YouTubeSync] Synced {synced}/{len(videos)} videos ({failed} failed) for tenant {tenant_id}")

    except Exception as e:
        error_type = _classify_error(e)
        print(f"[YouTubeSync] Error ({error_type}): {e}")
        _sync_tasks[tenant_id] = {"running": False, "error": str(e), "error_type": error_type}


async def _fetch_with_retry(fn, *args, retries: int = MAX_RETRIES):
    """Call fn with retry logic for transient errors."""
    last_error = None
    for attempt in range(1 + retries):
        try:
            result = await fn(*args)
            return result
        except Exception as e:
            last_error = e
            error_type = _classify_error(e)
            if not _is_retryable(error_type) or attempt >= retries:
                raise
            await asyncio.sleep(RETRY_DELAY * (attempt + 1))
    raise last_error


async def _refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> str | None:
    """Refresh OAuth2 access token using refresh token."""
    import httpx
    try:
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
            if resp.status_code == 200:
                return resp.json().get("access_token")
            print(f"[YouTubeSync] Token refresh failed: {resp.status_code} {resp.text}")
            return None
    except Exception as e:
        print(f"[YouTubeSync] Token refresh error: {e}")
        return None


async def _fetch_video_stats(client, access_token: str, video_id: str) -> dict | None:
    """Fetch lifetime stats from YouTube Data API v3."""
    try:
        resp = await client.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={"part": "statistics,snippet", "id": video_id},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if resp.status_code != 200:
            return None

        items = resp.json().get("items", [])
        if not items:
            return None

        item = items[0]
        stats = item.get("statistics", {})
        published_at = item.get("snippet", {}).get("publishedAt")

        return {
            "views": int(stats.get("viewCount", 0)),
            "likes": int(stats.get("likeCount", 0)),
            "comments": int(stats.get("commentCount", 0)),
            "published_at": published_at,
        }
    except Exception as e:
        print(f"[YouTubeSync] Stats fetch failed for {video_id}: {e}")
        return None


async def _fetch_video_analytics(
    client, access_token: str, video_id: str, upload_date
) -> dict | None:
    """Fetch analytics from YouTube Analytics API v2.

    Returns avg_view_duration, avg_retention, watch_time_hours,
    subscribers_gained, impressions, and CTR.
    """
    try:
        if upload_date:
            if isinstance(upload_date, datetime):
                start_date = upload_date.strftime("%Y-%m-%d")
            else:
                start_date = str(upload_date)[:10]
        else:
            start_date = "2024-01-01"

        end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Fetch watch metrics
        resp = await client.get(
            "https://youtubeanalytics.googleapis.com/v2/reports",
            params={
                "ids": "channel==MINE",
                "startDate": start_date,
                "endDate": end_date,
                "metrics": "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained",
                "filters": f"video=={video_id}",
            },
            headers={"Authorization": f"Bearer {access_token}"},
        )

        result = {}
        if resp.status_code == 200:
            rows = resp.json().get("rows", [])
            if rows and rows[0]:
                row = rows[0]
                result["avg_view_duration"] = round(row[2], 1)
                result["avg_retention"] = round(row[3], 1)
                result["watch_time_hours"] = round(row[1] / 60, 2)
                result["subscribers_gained"] = int(row[4])

        # Fetch impressions/CTR (separate query — different metric group)
        resp2 = await client.get(
            "https://youtubeanalytics.googleapis.com/v2/reports",
            params={
                "ids": "channel==MINE",
                "startDate": start_date,
                "endDate": end_date,
                "metrics": "impressions,impressionClickThroughRate",
                "filters": f"video=={video_id}",
            },
            headers={"Authorization": f"Bearer {access_token}"},
        )

        if resp2.status_code == 200:
            rows2 = resp2.json().get("rows", [])
            if rows2 and rows2[0]:
                result["impressions"] = int(rows2[0][0])
                result["ctr"] = round(rows2[0][1] * 100, 2)  # Convert decimal to percentage

        return result if result else None

    except Exception as e:
        print(f"[YouTubeSync] Analytics fetch failed for {video_id}: {e}")
        return None


def _extract_video_id(url: str) -> str | None:
    """Extract YouTube video ID from URL."""
    import re
    match = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})", url or "")
    return match.group(1) if match else None


def _calculate_snapshots(video: dict, stats: dict, analytics: dict | None, upload_date) -> dict:
    """Calculate time-bucketed snapshot fields (write-once).

    These preserve the metric value at specific milestones (24h, 48h, 7d, 30d).
    Only writes if the field is currently NULL and the time threshold has passed.
    """
    snapshots = {}

    if not upload_date:
        return snapshots

    try:
        if isinstance(upload_date, str):
            upload_dt = datetime.fromisoformat(upload_date.replace("Z", "+00:00"))
        elif isinstance(upload_date, datetime):
            upload_dt = upload_date if upload_date.tzinfo else upload_date.replace(tzinfo=timezone.utc)
        else:
            return snapshots
    except (ValueError, TypeError):
        return snapshots

    hours_since = (datetime.now(timezone.utc) - upload_dt).total_seconds() / 3600

    views = stats.get("views", 0)

    # Views snapshots
    if hours_since >= 24 and video.get("views_24h") is None:
        snapshots["views_24h"] = views
    if hours_since >= 48 and video.get("views_48h") is None:
        snapshots["views_48h"] = views
    if hours_since >= 168 and video.get("views_7d") is None:  # 7 days
        snapshots["views_7d"] = views
    if hours_since >= 720 and video.get("views_30d") is None:  # 30 days
        snapshots["views_30d"] = views

    # CTR snapshot at 48h
    if hours_since >= 48 and video.get("ctr_48h") is None and analytics:
        ctr = analytics.get("ctr")
        if ctr is not None:
            snapshots["ctr_48h"] = ctr

    # Retention snapshot at 48h
    if hours_since >= 48 and video.get("retention_48h") is None and analytics:
        retention = analytics.get("avg_retention")
        if retention is not None:
            snapshots["retention_48h"] = retention

    return snapshots
