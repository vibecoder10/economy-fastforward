"""Dashboard summary, calendar, and onboarding endpoints."""

from collections import defaultdict
from datetime import date as date_type
from fastapi import APIRouter, Depends, Query
from auth import get_tenant_id
from models import DashboardSummary, VideoSummary, PIPELINE_STAGES
from database import fetch_all, fetch_one
from vault import get_secret_status

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

    # Avg CTR and total views
    agg = await fetch_one(
        """SELECT AVG(ctr) as avg_ctr, COALESCE(SUM(views), 0) as total_views
           FROM videos WHERE tenant_id = $1 AND ctr IS NOT NULL""",
        tenant_id,
    )

    # Videos this week
    week = await fetch_one(
        """SELECT COUNT(*) as count FROM videos
           WHERE tenant_id = $1 AND created_at >= CURRENT_DATE - INTERVAL '7 days'""",
        tenant_id,
    )

    # Recent videos (last 5)
    recent_rows = await fetch_all(
        """SELECT id, video_title, status, thumbnail_url, accent_color, total_cost, views, ctr,
                  created_at::text, updated_at::text
           FROM videos WHERE tenant_id = $1
           ORDER BY updated_at DESC LIMIT 5""",
        tenant_id,
    )
    recent_videos = [
        VideoSummary(
            id=str(r["id"]),
            video_title=r.get("video_title"),
            status=r.get("status"),
            thumbnail_url=r.get("thumbnail_url"),
            accent_color=r.get("accent_color", "#00D4AA"),
            total_cost=float(r.get("total_cost") or 0),
            views=r.get("views") or 0,
            ctr=float(r["ctr"]) if r.get("ctr") else None,
            created_at=r.get("created_at"),
            updated_at=r.get("updated_at"),
        )
        for r in recent_rows
    ]

    return DashboardSummary(
        active_bots=bots_running["count"] if bots_running else 0,
        pending_review=pending["count"] if pending else 0,
        pipeline_distribution=pipeline_dist,
        cost_today=float(cost_today["total"]) if cost_today else 0,
        cost_week=cost_week,
        errors=errors["count"] if errors else 0,
        latest_video=latest_video,
        total_videos=total["count"] if total else 0,
        avg_ctr=round(float(agg["avg_ctr"]), 2) if agg and agg.get("avg_ctr") else None,
        total_views=int(agg["total_views"]) if agg else 0,
        videos_this_week=week["count"] if week else 0,
        recent_videos=recent_videos,
    )


@router.get("/calendar")
async def get_calendar(
    start: str = Query(..., description="Start date YYYY-MM-DD"),
    end: str = Query(..., description="End date YYYY-MM-DD"),
    tenant_id: str = Depends(get_tenant_id),
):
    """Videos grouped by date for calendar view."""
    rows = await fetch_all(
        """SELECT id, video_title, status, thumbnail_url, accent_color,
                  DATE(COALESCE(upload_date, created_at))::text as calendar_date
           FROM videos
           WHERE tenant_id = $1
             AND DATE(COALESCE(upload_date, created_at)) BETWEEN $2::date AND $3::date
           ORDER BY COALESCE(upload_date, created_at)""",
        tenant_id, date_type.fromisoformat(start), date_type.fromisoformat(end),
    )
    grouped: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        grouped[r["calendar_date"]].append({
            "id": str(r["id"]),
            "video_title": r.get("video_title"),
            "status": r.get("status"),
            "thumbnail_url": r.get("thumbnail_url"),
            "accent_color": r.get("accent_color"),
        })
    return grouped


@router.get("/onboarding/status")
async def get_onboarding_status(tenant_id: str = Depends(get_tenant_id)):
    """Rich onboarding status with per-step detail."""
    # Step 1: channel configured?
    # Try with onboarding columns first; fall back to base columns if migration 035 hasn't run
    try:
        cp = await fetch_one(
            "SELECT channel_name, user_type, style_description FROM channel_profiles WHERE tenant_id = $1",
            tenant_id,
        )
    except Exception:
        cp = await fetch_one(
            "SELECT channel_name FROM channel_profiles WHERE tenant_id = $1",
            tenant_id,
        )
    channel_configured = bool(cp and cp.get("channel_name"))
    user_type = (cp.get("user_type") or "new_creator") if cp else "new_creator"

    # Step 2: count configured API keys (5 required)
    required_keys = [
        "anthropic_api_key",
        "elevenlabs_api_key",
        "elevenlabs_voice_id",
        "kie_ai_api_key",
        "openai_api_key",
    ]
    configured_count = 0
    for key_name in required_keys:
        status = await get_secret_status(key_name, tenant_id)
        if status.get("configured"):
            configured_count += 1

    # Step 3: style generated?
    style_generated = bool(cp and cp.get("style_description"))
    if not style_generated:
        prompt_row = await fetch_one(
            "SELECT id FROM tenant_prompt_defaults WHERE tenant_id = $1 LIMIT 1",
            tenant_id,
        )
        style_generated = bool(prompt_row)

    # Step 4: first video created?
    vid = await fetch_one(
        "SELECT COUNT(*) as count FROM videos WHERE tenant_id = $1",
        tenant_id,
    )
    first_video_created = (vid["count"] if vid else 0) > 0

    # Step 5: display name from accounts via memberships
    account_row = await fetch_one(
        """SELECT a.display_name FROM accounts a
           JOIN memberships m ON m.user_id = a.id
           WHERE m.tenant_id = $1 LIMIT 1""",
        tenant_id,
    )
    display_name = (account_row.get("display_name") or "") if account_row else ""

    # Calculate percent complete (5 steps)
    done = 1  # account_created always true
    if channel_configured:
        done += 1
    if configured_count == 5:
        done += 1
    if style_generated:
        done += 1
    if first_video_created:
        done += 1
    percent = round(done / 5 * 100)

    return {
        "completed": done == 5,
        "steps": {
            "account_created": True,
            "channel_configured": channel_configured,
            "api_keys": {"configured": configured_count, "required": 5},
            "style_generated": style_generated,
            "first_video_created": first_video_created,
        },
        "percent_complete": percent,
        "user_type": user_type,
        "display_name": display_name,
    }
