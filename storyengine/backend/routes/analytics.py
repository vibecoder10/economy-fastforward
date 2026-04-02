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
