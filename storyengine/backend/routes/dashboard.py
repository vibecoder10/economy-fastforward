"""Dashboard summary endpoint."""

from fastapi import APIRouter, Depends
from auth import get_tenant_id
from models import DashboardSummary, VideoSummary, PIPELINE_STAGES
from database import fetch_all, fetch_one

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
async def get_summary(tenant_id: str = Depends(get_tenant_id)):
    """Aggregated stats for home screen."""

    # Active bots
    bots_running = await fetch_one(
        "SELECT COUNT(*) as count FROM bot_activity WHERE tenant_id = $1 AND status IN ('started', 'running')",
        tenant_id,
    )

    # Pending review - assets with pending status
    pending = await fetch_one(
        """SELECT COUNT(*) as count FROM assets
           WHERE tenant_id = $1 AND status = 'pending'""",
        tenant_id,
    )

    # Pipeline distribution
    distribution_rows = await fetch_all(
        "SELECT status, COUNT(*) as count FROM videos WHERE tenant_id = $1 GROUP BY status",
        tenant_id,
    )
    pipeline_dist = {row["status"]: row["count"] for row in distribution_rows}

    # Errors today
    errors = await fetch_one(
        """SELECT COUNT(*) as count FROM bot_activity
           WHERE tenant_id = $1 AND status = 'failed'
           AND created_at >= CURRENT_DATE""",
        tenant_id,
    )

    # Cost today
    cost_today = await fetch_one(
        """SELECT COALESCE(SUM(cost), 0) as total FROM bot_activity
           WHERE tenant_id = $1 AND created_at >= CURRENT_DATE""",
        tenant_id,
    )

    # Cost for last 7 days (sparkline)
    cost_week_rows = await fetch_all(
        """SELECT COALESCE(SUM(cost), 0) as daily_cost
           FROM bot_activity
           WHERE tenant_id = $1 AND created_at >= CURRENT_DATE - INTERVAL '7 days'
           GROUP BY DATE(created_at)
           ORDER BY DATE(created_at)""",
        tenant_id,
    )
    cost_week = [float(r["daily_cost"]) for r in cost_week_rows]

    # Latest video
    latest_row = await fetch_one(
        """SELECT id, video_title, status, thumbnail_url, accent_color, total_cost, views, ctr,
                  created_at::text, updated_at::text
           FROM videos WHERE tenant_id = $1
           ORDER BY updated_at DESC LIMIT 1""",
        tenant_id,
    )
    latest_video = None
    if latest_row:
        latest_video = VideoSummary(
            id=str(latest_row["id"]),
            video_title=latest_row.get("video_title"),
            status=latest_row.get("status"),
            thumbnail_url=latest_row.get("thumbnail_url"),
            accent_color=latest_row.get("accent_color", "#00D4AA"),
            total_cost=float(latest_row.get("total_cost") or 0),
            views=latest_row.get("views") or 0,
            ctr=float(latest_row["ctr"]) if latest_row.get("ctr") else None,
            created_at=latest_row.get("created_at"),
            updated_at=latest_row.get("updated_at"),
        )

    # Total videos
    total = await fetch_one(
        "SELECT COUNT(*) as count FROM videos WHERE tenant_id = $1",
        tenant_id,
    )

    return DashboardSummary(
        active_bots=bots_running["count"] if bots_running else 0,
        pending_review=pending["count"] if pending else 0,
        pipeline_distribution=pipeline_dist,
        cost_today=float(cost_today["total"]) if cost_today else 0,
        cost_week=cost_week,
        errors=errors["count"] if errors else 0,
        latest_video=latest_video,
        total_videos=total["count"] if total else 0,
    )
