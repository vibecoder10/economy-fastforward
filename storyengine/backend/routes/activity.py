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
        # Accept 'running' as alias for 'started' (frontend sends 'running', pipeline writes 'started')
        if status == "running":
            status_filter = ('started', 'running')
        else:
            status_filter = (status,)
        rows = await fetch_all(
            """SELECT ba.id, ba.bot_name, ba.video_id, v.video_title,
                      ba.status, ba.message, ba.cost, ba.created_at::text
               FROM bot_activity ba
               LEFT JOIN videos v ON v.id = ba.video_id
               WHERE ba.tenant_id = $1 AND ba.status = ANY($2)
               ORDER BY ba.created_at DESC LIMIT $3 OFFSET $4""",
            tenant_id, list(status_filter), limit, offset,
        )
    else:
        rows = await fetch_all(
            """SELECT ba.id, ba.bot_name, ba.video_id, v.video_title,
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
        """SELECT COUNT(*) as count FROM bot_activity
           WHERE tenant_id = $1 AND status IN ('started', 'running')
           AND created_at >= NOW() - INTERVAL '30 minutes'
           AND NOT EXISTS (
               SELECT 1 FROM bot_activity ba2
               WHERE ba2.tenant_id = bot_activity.tenant_id
               AND ba2.video_id = bot_activity.video_id
               AND ba2.bot_name = bot_activity.bot_name
               AND ba2.status IN ('completed', 'failed')
               AND ba2.created_at > bot_activity.created_at
           )""",
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
    """SSE endpoint for real-time activity and stage_change events."""

    async def event_generator():
        last_id = None
        last_transition_id = None
        while True:
            # Poll for new activity entries
            if last_id:
                rows = await fetch_all(
                    """SELECT ba.id, ba.bot_name, ba.video_id, v.video_title,
                              ba.status, ba.message, ba.cost, ba.created_at::text
                       FROM bot_activity ba
                       LEFT JOIN videos v ON v.id = ba.video_id
                       WHERE ba.tenant_id = $1 AND ba.id > $2
                       ORDER BY ba.created_at DESC LIMIT 10""",
                    tenant_id, last_id,
                )
            else:
                rows = await fetch_all(
                    """SELECT ba.id, ba.bot_name, ba.video_id, v.video_title,
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
                yield f"event: activity\ndata: {json.dumps(entry)}\n\n"
                last_id = row["id"]

            # Poll for stage transitions
            if last_transition_id:
                transitions = await fetch_all(
                    """SELECT st.id, st.video_id, v.video_title,
                              st.from_status, st.to_status, st.triggered_by,
                              st.cost, st.duration_seconds, st.error_message,
                              st.created_at::text
                       FROM stage_transitions st
                       LEFT JOIN videos v ON v.id = st.video_id
                       WHERE st.tenant_id = $1 AND st.id > $2
                       ORDER BY st.created_at DESC LIMIT 10""",
                    tenant_id, last_transition_id,
                )
            else:
                transitions = await fetch_all(
                    """SELECT st.id, st.video_id, v.video_title,
                              st.from_status, st.to_status, st.triggered_by,
                              st.cost, st.duration_seconds, st.error_message,
                              st.created_at::text
                       FROM stage_transitions st
                       LEFT JOIN videos v ON v.id = st.video_id
                       WHERE st.tenant_id = $1
                       ORDER BY st.created_at DESC LIMIT 5""",
                    tenant_id,
                )

            for t in transitions:
                stage_event = {
                    "id": str(t["id"]),
                    "video_id": str(t["video_id"]) if t.get("video_id") else None,
                    "video_title": t.get("video_title"),
                    "from_status": t.get("from_status"),
                    "to_status": t.get("to_status"),
                    "triggered_by": t.get("triggered_by"),
                    "cost": float(t["cost"]) if t.get("cost") else None,
                    "duration_seconds": t.get("duration_seconds"),
                    "error_message": t.get("error_message"),
                    "created_at": t.get("created_at"),
                }
                yield f"event: stage_change\ndata: {json.dumps(stage_event)}\n\n"
                last_transition_id = t["id"]

            await asyncio.sleep(5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
