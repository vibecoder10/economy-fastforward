"""Analytics endpoints — aggregate performance data across videos."""

from fastapi import APIRouter, Depends
from database import fetch_all, fetch_one
from auth import get_tenant_id

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/overview")
async def get_overview(tenant_id: str = Depends(get_tenant_id)):
    row = await fetch_one(
        """SELECT
             COUNT(*)::int AS total_videos,
             COALESCE(SUM(views), 0)::bigint AS total_views,
             ROUND(AVG(ctr)::numeric, 2) AS avg_ctr,
             ROUND(AVG(avg_retention)::numeric, 2) AS avg_retention,
             COUNT(*) FILTER (WHERE status = 'done')::int AS published_videos
           FROM videos
           WHERE tenant_id = $1
             AND status NOT IN ('idea_logged')""",
        tenant_id,
    )
    return {
        "total_videos": row["total_videos"] if row else 0,
        "total_views": int(row["total_views"]) if row else 0,
        "avg_ctr": float(row["avg_ctr"]) if row and row["avg_ctr"] else None,
        "avg_retention": float(row["avg_retention"]) if row and row["avg_retention"] else None,
        "published_videos": row["published_videos"] if row else 0,
    }


@router.get("/ctr-timeline")
async def get_ctr_timeline(
    limit: int = 50,
    tenant_id: str = Depends(get_tenant_id),
):
    rows = await fetch_all(
        """SELECT video_title, ctr, views, upload_date, created_at
           FROM videos
           WHERE tenant_id = $1 AND ctr IS NOT NULL
           ORDER BY COALESCE(upload_date, created_at) ASC
           LIMIT $2""",
        tenant_id,
        limit,
    )
    return [
        {
            "video_title": r["video_title"],
            "ctr": float(r["ctr"]) if r["ctr"] else None,
            "views": r["views"] or 0,
            "date": str(r["upload_date"] or r["created_at"] or ""),
        }
        for r in rows
    ]


@router.get("/framework-performance")
async def get_framework_performance(tenant_id: str = Depends(get_tenant_id)):
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
           ORDER BY avg_ctr DESC NULLS LAST""",
        tenant_id,
    )
    return [
        {
            "framework": r["framework_angle"],
            "video_count": r["video_count"],
            "avg_ctr": float(r["avg_ctr"]) if r["avg_ctr"] else None,
            "avg_retention": float(r["avg_retention"]) if r["avg_retention"] else None,
            "total_views": int(r["total_views"]),
        }
        for r in rows
    ]


@router.get("/topic-performance")
async def get_topic_performance(tenant_id: str = Depends(get_tenant_id)):
    """Performance breakdown by framework/topic across our videos."""
    rows = await fetch_all(
        """SELECT
             framework_angle AS topic,
             COUNT(*)::int AS video_count,
             ROUND(AVG(ctr)::numeric, 2) AS avg_ctr,
             ROUND(AVG(avg_retention)::numeric, 2) AS avg_retention,
             COALESCE(SUM(views), 0)::bigint AS total_views
           FROM videos
           WHERE tenant_id = $1
             AND framework_angle IS NOT NULL
             AND framework_angle != ''
             AND status NOT IN ('idea_logged')
           GROUP BY framework_angle
           ORDER BY video_count DESC, avg_ctr DESC NULLS LAST""",
        tenant_id,
    )
    return [
        {
            "topic": r["topic"],
            "video_count": r["video_count"],
            "avg_ctr": float(r["avg_ctr"]) if r["avg_ctr"] else None,
            "avg_retention": float(r["avg_retention"]) if r["avg_retention"] else None,
            "total_views": int(r["total_views"]),
        }
        for r in rows
    ]


@router.get("/competitor-benchmark")
async def get_competitor_benchmark(tenant_id: str = Depends(get_tenant_id)):
    """Compare our channel CTR/views against competitor averages."""
    # Our stats
    our = await fetch_one(
        """SELECT
             ROUND(AVG(ctr)::numeric, 2) AS avg_ctr,
             ROUND(AVG(avg_retention)::numeric, 2) AS avg_retention,
             COALESCE(SUM(views), 0)::bigint AS total_views,
             COUNT(*) FILTER (WHERE ctr IS NOT NULL)::int AS videos_with_ctr
           FROM videos
           WHERE tenant_id = $1 AND status NOT IN ('idea_logged')""",
        tenant_id,
    )
    # Competitor channel averages (VPH as proxy for performance)
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
        "channel_avg_ctr": float(our["avg_ctr"]) if our and our["avg_ctr"] else None,
        "channel_avg_retention": float(our["avg_retention"]) if our and our["avg_retention"] else None,
        "channel_total_views": int(our["total_views"]) if our else 0,
        "channel_videos_with_ctr": our["videos_with_ctr"] if our else 0,
        "competitors": [
            {
                "channel": r["channel"],
                "video_count": r["video_count"],
                "avg_vph": float(r["avg_vph"]) if r["avg_vph"] else None,
                "total_views": int(r["total_views"]),
            }
            for r in competitors
        ],
    }
