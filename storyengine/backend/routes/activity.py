"""Bot activity log + stats."""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from auth import get_tenant_id
from models import ActivityEntry, ActivityStats
from database import fetch_all, fetch_one
from typing import Optional
import asyncio
import json

router = APIRouter(prefix="/api/activity", tags=["activity"])


@router.get("", response_model=list[ActivityEntry])
async def list_activity(
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=100),
    offset: int = Query(0),
    tenant_id: str = Depends(get_tenant_id),
):
    """Bot activity log, newest first."""
    if status:
        rows = await fetch_all(
            """SELECT ba.id, ba.bot_name, ba.video_id, v.title as video_title,
                      ba.status, ba.message, ba.cost, ba.created_at::text
               FROM bot_activity ba
               LEFT JOIN videos v ON v.id = ba.video_id
               WHERE ba.tenant_id = $1 AND ba.status = $2
               ORDER BY ba.created_at DESC LIMIT $3 OFFSET $4""",
            tenant_id, status, limit, offset,
        )
    else:
        rows = await fetch_all(
            """SELECT ba.id, ba.bot_name, ba.video_id, v.title as video_title,
                      ba.status, ba.message, ba.cost, ba.created_at::text
               FROM bot_activity ba
               LEFT JOIN videos v ON v.id = ba.video_id
               WHERE ba.tenant_id = $1
               ORDER BY ba.created_at DESC LIMIT $2 OFFSET $3""",
            tenant_id, limit, offset,
        )

    return [
        ActivityEntry(
            id=str(r["id"]),
            bot_name=r["bot_name"],
            video_id=str(r["video_id"]) if r.get("video_id") else None,
            video_title=r.get("video_title"),
            status=r["status"],
            message=r.get("message"),
            cost=float(r.get("cost", 0)),
            created_at=r.get("created_at"),
        )
        for r in rows
    ]


@router.get("/stats", response_model=ActivityStats)
async def get_stats(tenant_id: str = Depends(get_tenant_id)):
    """Running bots count, errors today, cost today."""
    running = await fetch_one(
        "SELECT COUNT(*) as count FROM bot_activity WHERE tenant_id = $1 AND status IN ('started', 'running')",
        tenant_id,
    )
    errors = await fetch_one(
        """SELECT COUNT(*) as count FROM bot_activity
           WHERE tenant_id = $1 AND status = 'failed' AND created_at >= CURRENT_DATE""",
        tenant_id,
    )
    cost = await fetch_one(
        """SELECT COALESCE(SUM(cost), 0) as total FROM bot_activity
           WHERE tenant_id = $1 AND created_at >= CURRENT_DATE""",
        tenant_id,
    )

    return ActivityStats(
        bots_running=running["count"] if running else 0,
        errors_today=errors["count"] if errors else 0,
        cost_today=float(cost["total"]) if cost else 0,
    )


@router.get("/stream")
async def activity_stream(tenant_id: str = Depends(get_tenant_id)):
    """SSE endpoint for real-time activity updates."""

    async def event_generator():
        last_id = None
        while True:
            # Poll for new activity entries
            if last_id:
                rows = await fetch_all(
                    """SELECT ba.id, ba.bot_name, ba.video_id, v.title as video_title,
                              ba.status, ba.message, ba.cost, ba.created_at::text
                       FROM bot_activity ba
                       LEFT JOIN videos v ON v.id = ba.video_id
                       WHERE ba.tenant_id = $1 AND ba.id > $2
                       ORDER BY ba.created_at DESC LIMIT 10""",
                    tenant_id, last_id,
                )
            else:
                rows = await fetch_all(
                    """SELECT ba.id, ba.bot_name, ba.video_id, v.title as video_title,
                              ba.status, ba.message, ba.cost, ba.created_at::text
                       FROM bot_activity ba
                       LEFT JOIN videos v ON v.id = ba.video_id
                       WHERE ba.tenant_id = $1
                       ORDER BY ba.created_at DESC LIMIT 5""",
                    tenant_id,
                )

            for row in rows:
                entry = {
                    "id": str(row["id"]),
                    "bot_name": row["bot_name"],
                    "video_id": str(row["video_id"]) if row.get("video_id") else None,
                    "video_title": row.get("video_title"),
                    "status": row["status"],
                    "message": row.get("message"),
                    "cost": float(row.get("cost", 0)),
                    "created_at": row.get("created_at"),
                }
                yield f"data: {json.dumps(entry)}\n\n"
                last_id = row["id"]

            await asyncio.sleep(5)  # Poll every 5 seconds

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
