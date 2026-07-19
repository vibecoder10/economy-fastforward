"""Analytics endpoints — real channel performance from the YouTube sync.

Everything here reads the channel mirror (channel_videos +
channel_analytics_daily, filled by routes/youtube_sync.py) rather than the
production pipeline rows in `videos`, so the page reflects what is actually
live on the tenant's YouTube channel.
"""

from fastapi import APIRouter, Depends, Query
from database import fetch_all, fetch_one
from auth import get_tenant_id
from analytics_by_style import get_style_performance
from models import StylePerformanceResponse
from own_vph import compute_own_vph

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _f(v) -> float | None:
    return float(v) if v is not None else None


@router.get("/overview")
async def get_overview(tenant_id: str = Depends(get_tenant_id)):
    """Channel identity + headline KPIs. `connected: false` when no channel."""
    profile = await fetch_one(
        """SELECT youtube_channel_id, youtube_channel_name, youtube_channel_thumbnail,
                  youtube_subscriber_count, youtube_channel_total_views,
                  youtube_channel_video_count, youtube_stats_synced_at,
                  youtube_refresh_token
           FROM channel_profiles WHERE tenant_id = $1""",
        tenant_id,
    )
    connected = bool(profile and profile["youtube_refresh_token"])

    lifetime = await fetch_one(
        """SELECT
             COUNT(*) FILTER (WHERE COALESCE(privacy_status, 'public') = 'public')::int AS published_videos,
             COALESCE(SUM(view_count) FILTER (WHERE COALESCE(privacy_status, 'public') = 'public'), 0)::bigint AS total_views,
             ROUND(AVG(ctr_percent) FILTER (WHERE COALESCE(privacy_status, 'public') = 'public')::numeric, 2) AS avg_ctr,
             ROUND(AVG(avg_view_duration_seconds) FILTER (WHERE COALESCE(privacy_status, 'public') = 'public')::numeric, 1) AS avg_view_duration_seconds,
             ROUND(AVG(avg_retention) FILTER (WHERE COALESCE(privacy_status, 'public') = 'public')::numeric, 1) AS avg_retention
           FROM channel_videos
           WHERE tenant_id = $1""",
        tenant_id,
    )

    last28 = await fetch_one(
        """SELECT
             COALESCE(SUM(views), 0)::bigint AS views_28d,
             ROUND((COALESCE(SUM(watch_time_minutes), 0) / 60)::numeric, 1) AS watch_time_hours_28d,
             COALESCE(SUM(subscribers_gained), 0)::int
               - COALESCE(SUM(subscribers_lost), 0)::int AS subscribers_gained_28d,
             ROUND(AVG(ctr)::numeric, 2) AS avg_ctr_28d
           FROM channel_analytics_daily
           WHERE tenant_id = $1 AND date >= CURRENT_DATE - 28""",
        tenant_id,
    )

    return {
        "connected": connected,
        "channel": {
            "channel_id": profile["youtube_channel_id"] if profile else None,
            "name": profile["youtube_channel_name"] if profile else None,
            "thumbnail": profile["youtube_channel_thumbnail"] if profile else None,
            "subscribers": int(profile["youtube_subscriber_count"] or 0) if profile else 0,
            "total_views": int(profile["youtube_channel_total_views"] or 0) if profile else 0,
            "video_count": int(profile["youtube_channel_video_count"] or 0) if profile else 0,
            "last_synced": str(profile["youtube_stats_synced_at"]) if profile and profile["youtube_stats_synced_at"] else None,
        } if connected else None,
        "published_videos": lifetime["published_videos"] if lifetime else 0,
        "total_views": int(lifetime["total_views"]) if lifetime else 0,
        "avg_ctr": _f(lifetime["avg_ctr"]) if lifetime else None,
        "avg_view_duration_seconds": _f(lifetime["avg_view_duration_seconds"]) if lifetime else None,
        "avg_retention": _f(lifetime["avg_retention"]) if lifetime else None,
        "views_28d": int(last28["views_28d"]) if last28 else 0,
        "watch_time_hours_28d": _f(last28["watch_time_hours_28d"]) if last28 else 0,
        "subscribers_gained_28d": last28["subscribers_gained_28d"] if last28 else 0,
        "avg_ctr_28d": _f(last28["avg_ctr_28d"]) if last28 else None,
    }


@router.get("/timeline")
async def get_timeline(
    days: int = Query(default=28, ge=7, le=365),
    tenant_id: str = Depends(get_tenant_id),
):
    """Channel-level daily timeseries for the chart."""
    rows = await fetch_all(
        """SELECT date, views, impressions, ctr, watch_time_minutes,
                  avg_view_duration_seconds, subscribers_gained
           FROM channel_analytics_daily
           WHERE tenant_id = $1 AND date >= CURRENT_DATE - $2::int
           ORDER BY date ASC""",
        tenant_id,
        days,
    )
    return [
        {
            "date": str(r["date"]),
            "views": r["views"] or 0,
            "impressions": int(r["impressions"]) if r["impressions"] is not None else None,
            "ctr": _f(r["ctr"]),
            "watch_time_minutes": _f(r["watch_time_minutes"]),
            "subscribers_gained": r["subscribers_gained"],
        }
        for r in rows
    ]


@router.get("/videos")
async def get_channel_videos(
    limit: int = Query(default=50, ge=1, le=200),
    tenant_id: str = Depends(get_tenant_id),
):
    """Videos actually on the channel, newest first (YouTube Studio style)."""
    rows = await fetch_all(
        """SELECT id, video_id, internal_video_id, title, thumbnail_url, published_at,
                  duration_seconds, privacy_status, view_count, like_count, comment_count,
                  impressions, ctr_percent, avg_view_duration_seconds, avg_retention,
                  last_synced_at
           FROM channel_videos
           WHERE tenant_id = $1
           ORDER BY published_at DESC NULLS LAST
           LIMIT $2""",
        tenant_id,
        limit,
    )
    return [
        {
            "id": str(r["id"]),
            "youtube_video_id": r["video_id"],
            "internal_video_id": str(r["internal_video_id"]) if r["internal_video_id"] else None,
            "title": r["title"],
            "thumbnail_url": r["thumbnail_url"],
            "published_at": str(r["published_at"]) if r["published_at"] else None,
            "duration_seconds": r["duration_seconds"],
            "privacy_status": r["privacy_status"],
            "views": int(r["view_count"] or 0),
            "likes": r["like_count"] or 0,
            "comments": r["comment_count"] or 0,
            "impressions": int(r["impressions"]) if r["impressions"] is not None else None,
            "ctr": _f(r["ctr_percent"]),
            "avg_view_duration_seconds": _f(r["avg_view_duration_seconds"]),
            "avg_view_percentage": _f(r["avg_retention"]),
            # C33: views-per-hour, derived at read time (own_vph.compute_own_vph),
            # the same math the competitor side already uses — see checklist §3.4.
            "vph": compute_own_vph(r["view_count"], r["published_at"]),
            "watch_url": f"https://youtu.be/{r['video_id']}",
            "last_synced_at": str(r["last_synced_at"]) if r["last_synced_at"] else None,
        }
        for r in rows
    ]


@router.get("/framework-performance")
async def get_framework_performance(tenant_id: str = Depends(get_tenant_id)):
    """Framework angles with enough real data to compare (2+ videos, views > 0).

    Returns [] until the channel has genuine per-framework performance, so the
    UI section stays hidden instead of showing 1-video groups with 0 views.
    """
    rows = await fetch_all(
        """SELECT
             framework_angle,
             COUNT(*)::int AS video_count,
             ROUND(AVG(ctr)::numeric, 2) AS avg_ctr,
             ROUND(AVG(avg_retention)::numeric, 2) AS avg_retention,
             COALESCE(SUM(views), 0)::bigint AS total_views
           FROM videos
           WHERE tenant_id = $1
             AND framework_angle IS NOT NULL
             AND framework_angle != ''
           GROUP BY framework_angle
           HAVING COUNT(*) >= 2 AND COALESCE(SUM(views), 0) > 0
           ORDER BY avg_ctr DESC NULLS LAST""",
        tenant_id,
    )
    return [
        {
            "framework": r["framework_angle"],
            "video_count": r["video_count"],
            "avg_ctr": _f(r["avg_ctr"]),
            "avg_retention": _f(r["avg_retention"]),
            "total_views": int(r["total_views"]),
        }
        for r in rows
    ]


@router.get("/by-style", response_model=StylePerformanceResponse)
async def get_by_style_performance(tenant_id: str = Depends(get_tenant_id)):
    """Performance grouped by the creative CHOICE that produced it — visual style
    preset, render look, script voice, and each video's dominant clip model
    (checklist §3.1/C30: the preset-performance loop — "which visual styles /
    models / presets actually earn views on this channel"). Reads `videos`
    directly (never `channel_videos` — see analytics_by_style.py's header for
    why); tenant-scoped, fail-soft per dimension, spend joined from
    generation_ledger. C31 builds the "by style" UI panel + producer citations
    on top of this same aggregation — the copilot's channel_data tool
    (channel_briefs._style_performance_brief) reads the SAME function, so the
    chat and this endpoint can never disagree.
    """
    return await get_style_performance(tenant_id)


@router.get("/competitor-benchmark")
async def get_competitor_benchmark(tenant_id: str = Depends(get_tenant_id)):
    """Compare our channel CTR/views against competitor averages."""
    our = await fetch_one(
        """SELECT
             ROUND(AVG(ctr_percent)::numeric, 2) AS avg_ctr,
             ROUND(AVG(avg_retention)::numeric, 2) AS avg_retention,
             COALESCE(SUM(view_count) FILTER (WHERE COALESCE(privacy_status, 'public') = 'public'), 0)::bigint AS total_views,
             COUNT(*) FILTER (WHERE ctr_percent IS NOT NULL)::int AS videos_with_ctr
           FROM channel_videos
           WHERE tenant_id = $1""",
        tenant_id,
    )
    competitors = await fetch_all(
        """SELECT
             channel,
             COUNT(*)::int AS video_count,
             ROUND(AVG(vph)::numeric, 1) AS avg_vph,
             COALESCE(SUM(views), 0)::bigint AS total_views
           FROM competitor_videos
           WHERE tenant_id = $1 AND channel IS NOT NULL
           GROUP BY channel
           ORDER BY avg_vph DESC NULLS LAST""",
        tenant_id,
    )
    return {
        "channel_avg_ctr": _f(our["avg_ctr"]) if our else None,
        "channel_avg_retention": _f(our["avg_retention"]) if our else None,
        "channel_total_views": int(our["total_views"]) if our else 0,
        "channel_videos_with_ctr": our["videos_with_ctr"] if our else 0,
        "competitors": [
            {
                "channel": r["channel"],
                "video_count": r["video_count"],
                "avg_vph": _f(r["avg_vph"]),
                "total_views": int(r["total_views"]),
            }
            for r in competitors
        ],
    }
