"""The creator's own production queue ("queue these titles").

An ordered list of videos the creator has decided to make — typically a CSV of
title ideas dropped into the chat. The calendar surfaces queued items as the
FIRST slots; Autopilot drains the queue in order BEFORE falling back to its
scored competitor candidates (main.py:_auto_produce_queue); any item is also
one-click buildable here. Launching mirrors autopilot's launch_candidate
(same video shape, same pipeline loop) so a queued video is a first-class
citizen of the engine, not a special case.

Concurrency: claiming an item is a single UPDATE with FOR UPDATE SKIP LOCKED,
so a manual Build and the autopilot cycle can never launch the same row twice.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from auth import get_tenant_id
from database import execute, fetch_all, fetch_one

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/queue", tags=["queue"])

# Statuses that mean "this video is no longer occupying the production lane".
# needs-approval pauses do NOT count as terminal — a parked video is still
# in flight (the queue waits; see the locked-cast phase for the real unblock).
TERMINAL_STATUSES = ("rendered", "uploaded", "uploaded_draft", "done", "published", "failed")


class QueueItemIn(BaseModel):
    title: str
    framework_angle: Optional[str] = None
    writer_guidance: Optional[str] = None


class QueueAddRequest(BaseModel):
    items: list[QueueItemIn]
    source_asset_id: Optional[str] = None


class QueuePatch(BaseModel):
    title: Optional[str] = None
    position: Optional[int] = None
    status: Optional[str] = None  # 'queued' | 'skipped'


# --- engine functions (shared by routes, chat ops, and the autopilot loop) ---

async def add_queue_items(
    tenant_id, items: list[dict[str, Any]], source_asset_id: Optional[str] = None
) -> int:
    """Append items (dicts with title / framework_angle / writer_guidance /
    user_script) to the end of the tenant's queue, preserving given order.
    Positions move in gaps of 10 so reorders are one-row updates."""
    base = await fetch_one(
        "SELECT COALESCE(MAX(position), 0) AS p FROM production_queue WHERE tenant_id = $1",
        tenant_id,
    )
    pos = int(base["p"])
    count = 0
    for it in items:
        title = str(it.get("title") or "").strip()[:300]
        if not title:
            continue
        pos += 10
        await execute(
            "INSERT INTO production_queue (tenant_id, position, title, framework_angle, "
            "writer_guidance, user_script, source_asset_id) VALUES ($1, $2, $3, $4, $5, $6, $7)",
            tenant_id, pos, title,
            (it.get("framework_angle") or None),
            (it.get("writer_guidance") or None),
            (it.get("user_script") or None),
            source_asset_id,
        )
        count += 1
    return count


async def queue_titles_from_asset(
    tenant_id, asset_id: str, column: Optional[str] = None
) -> tuple[int, Optional[str]]:
    """Queue every title from an uploaded CSV chat asset. Returns
    (queued_count, error_message). Refuses to guess when the CSV's title
    column is ambiguous and no explicit column was given — bad titles become
    produced videos, which costs real money."""
    row = await fetch_one(
        "SELECT id, kind, parsed FROM chat_assets WHERE id = $1 AND tenant_id = $2",
        asset_id, tenant_id,
    )
    if not row:
        return 0, "I can't find that uploaded file anymore — drop it in again?"
    parsed = row.get("parsed")
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except (json.JSONDecodeError, ValueError):
            parsed = None
    if row["kind"] != "csv" or not isinstance(parsed, dict) or not parsed.get("rows"):
        return 0, "That file doesn't look like a CSV with rows I can queue."
    col = (column or "").strip() or parsed.get("title_column")
    headers = parsed.get("headers") or []
    if col not in headers:
        col = None
    if not col or (parsed.get("ambiguous") and not (column or "").strip()):
        return 0, (
            "I don't want to guess which column holds the titles — the file has: "
            + ", ".join(headers)
            + ". Which one should I queue?"
        )
    titles = [str(r.get(col) or "").strip() for r in parsed["rows"]]
    titles = [t for t in titles if t]
    if not titles:
        return 0, f"The '{col}' column is empty — nothing to queue."
    n = await add_queue_items(tenant_id, [{"title": t} for t in titles], source_asset_id=asset_id)
    await execute(
        "UPDATE chat_assets SET status = 'filed', filed_as = 'queue' WHERE id = $1 AND tenant_id = $2",
        asset_id, tenant_id,
    )
    return n, None


async def _claim_next(tenant_id) -> Optional[dict]:
    """Atomically claim the front of the queue (position order)."""
    return await fetch_one(
        """UPDATE production_queue SET status = 'launched', launched_at = now(), updated_at = now()
           WHERE id = (SELECT id FROM production_queue
                       WHERE tenant_id = $1 AND status = 'queued'
                       ORDER BY position, created_at LIMIT 1
                       FOR UPDATE SKIP LOCKED)
           RETURNING *""",
        tenant_id,
    )


async def _claim_item(tenant_id, item_id: str) -> Optional[dict]:
    return await fetch_one(
        """UPDATE production_queue SET status = 'launched', launched_at = now(), updated_at = now()
           WHERE id = (SELECT id FROM production_queue
                       WHERE id = $1 AND tenant_id = $2 AND status = 'queued'
                       FOR UPDATE SKIP LOCKED)
           RETURNING *""",
        item_id, tenant_id,
    )


async def _unclaim(tenant_id, item_id) -> None:
    await execute(
        "UPDATE production_queue SET status = 'queued', launched_at = NULL, updated_at = now() "
        "WHERE id = $1 AND tenant_id = $2",
        item_id, tenant_id,
    )


async def launch_queue_item(tenant_id, item: dict, background_tasks=None) -> dict:
    """Create the video for a CLAIMED queue item and start the pipeline —
    the queue mirror of autopilot's launch_candidate (same video shape, same
    learnings guidance, same run_research -> run_next_step loop). On any
    failure before the pipeline starts, the item is un-claimed."""
    item_id = str(item["id"])
    try:
        # Proven channel patterns ride into the script stage, same as autopilot.
        learnings_text = ""
        try:
            lr = await fetch_all(
                """SELECT category, pattern, avg_ctr FROM learnings
                   WHERE tenant_id = $1 AND active = true AND confidence >= 55
                   ORDER BY confidence DESC LIMIT 10""",
                tenant_id,
            )
            lines = [f"- [{r['category']}] {r['pattern']} (CTR: {float(r['avg_ctr']):.1f}%)"
                     for r in lr if r.get("avg_ctr")]
            if lines:
                learnings_text = "## Channel Learnings\nProven patterns from your channel:\n" + "\n".join(lines)
        except Exception:  # noqa: BLE001
            pass

        from routes.projects import _get_or_create_project
        project = await _get_or_create_project(tenant_id)

        result = await fetch_one(
            """INSERT INTO videos (
                tenant_id, project_id, video_title, status, headline, source,
                framework_angle, writer_guidance, script_system_prompt, created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, now())
            RETURNING id""",
            tenant_id, str(project["id"]), item["title"], "idea_logged",
            item["title"], "queue",
            item.get("framework_angle"), item.get("writer_guidance"),
            learnings_text or None,
        )
        video_id = str(result["id"])
        await execute(
            "UPDATE production_queue SET video_id = $1, updated_at = now() "
            "WHERE id = $2 AND tenant_id = $3",
            video_id, item_id, tenant_id,
        )
    except Exception:
        await _unclaim(tenant_id, item_id)
        raise

    async def _run_full_pipeline():
        from pipeline_executor import PipelineExecutor
        executor = PipelineExecutor(tenant_id)
        res = await executor.run_research(video_id)
        if res.get("status") == "failed":
            return
        for _ in range(20):
            video = await fetch_one("SELECT status FROM videos WHERE id = $1", video_id)
            status = (video or {}).get("status", "")
            if status in TERMINAL_STATUSES:
                break
            step_result = await executor.run_next_step(video_id)
            if step_result.get("status", "") in ("failed", "needs_approval", "idle"):
                break

    if background_tasks is not None:
        background_tasks.add_task(_run_full_pipeline)
    else:
        asyncio.create_task(_run_full_pipeline())

    return {
        "status": "launched",
        "queue_id": item_id,
        "video_id": video_id,
        "video_title": item["title"],
        "message": "Video created and pipeline started",
    }


async def auto_produce_next(tenant_id) -> Optional[dict]:
    """One autopilot heartbeat for the queue: if the tenant has queued items,
    the production cadence says a new video is due, and nothing is already in
    flight, claim + launch the front of the queue. Returns launch info or None.
    Called by main.py:_auto_produce_queue for autopilot-enabled tenants only."""
    has = await fetch_one(
        "SELECT 1 AS x FROM production_queue WHERE tenant_id = $1 AND status = 'queued' LIMIT 1",
        tenant_id,
    )
    if not has:
        return None

    cfg = await fetch_one(
        "SELECT production_interval_days FROM autopilot_config WHERE tenant_id = $1", tenant_id
    )
    interval = max(1, int((cfg or {}).get("production_interval_days") or 0) or 2)

    # One shared cadence across queue launches AND autopilot candidate launches.
    last = await fetch_one(
        """SELECT GREATEST(
               (SELECT MAX(launched_at) FROM production_queue WHERE tenant_id = $1),
               (SELECT MAX(created_at) FROM videos
                WHERE tenant_id = $1 AND (source = 'queue' OR source LIKE 'autopilot%'))
           ) AS t""",
        tenant_id,
    )
    if last and last.get("t") is not None:
        due = await fetch_one(
            "SELECT (now() - $1::timestamptz) >= make_interval(days => $2) AS due",
            last["t"], interval,
        )
        if not (due and due["due"]):
            return None

    # Never stack builds: a non-terminal engine-launched video blocks the lane
    # (including ones parked at an approval gate — the creator must act first).
    inflight = await fetch_one(
        """SELECT 1 AS x FROM videos
           WHERE tenant_id = $1 AND (source = 'queue' OR source LIKE 'autopilot%')
             AND status NOT IN ({}) AND created_at > now() - interval '7 days'
           LIMIT 1""".format(", ".join(f"'{s}'" for s in TERMINAL_STATUSES)),
        tenant_id,
    )
    if inflight:
        return None

    item = await _claim_next(tenant_id)
    if not item:
        return None
    return await launch_queue_item(tenant_id, item)


# --- routes ------------------------------------------------------------------

@router.get("")
async def list_queue(tenant_id=Depends(get_tenant_id)):
    rows = await fetch_all(
        """SELECT id, position, title, framework_angle, status, video_id,
                  source_asset_id, launched_at, created_at
           FROM production_queue WHERE tenant_id = $1 AND status != 'skipped'
           ORDER BY status = 'queued' DESC, position, created_at""",
        tenant_id,
    )
    return {"items": [dict(r) for r in rows]}


@router.post("")
async def add_to_queue(body: QueueAddRequest, tenant_id=Depends(get_tenant_id)):
    if not body.items:
        raise HTTPException(status_code=400, detail="No items to queue.")
    n = await add_queue_items(
        tenant_id, [i.model_dump() for i in body.items], source_asset_id=body.source_asset_id
    )
    if n == 0:
        raise HTTPException(status_code=400, detail="No usable titles in those items.")
    return {"status": "queued", "count": n}


@router.patch("/{item_id}")
async def patch_queue_item(item_id: str, body: QueuePatch, tenant_id=Depends(get_tenant_id)):
    sets, params = [], []
    if body.title is not None and body.title.strip():
        params.append(body.title.strip()[:300]); sets.append(f"title = ${len(params)}")
    if body.position is not None:
        params.append(int(body.position)); sets.append(f"position = ${len(params)}")
    if body.status in ("queued", "skipped"):
        params.append(body.status); sets.append(f"status = ${len(params)}")
    if not sets:
        return {"status": "unchanged"}
    params += [item_id, tenant_id]
    row = await fetch_one(
        f"UPDATE production_queue SET {', '.join(sets)}, updated_at = now() "
        f"WHERE id = ${len(params) - 1} AND tenant_id = ${len(params)} AND status != 'launched' "
        "RETURNING id",
        *params,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Queue item not found (or already launched).")
    return {"status": "ok"}


@router.delete("/{item_id}")
async def delete_queue_item(item_id: str, tenant_id=Depends(get_tenant_id)):
    await execute(
        "DELETE FROM production_queue WHERE id = $1 AND tenant_id = $2 AND status != 'launched'",
        item_id, tenant_id,
    )
    return {"status": "deleted"}


@router.post("/next/launch")
async def launch_next(background_tasks: BackgroundTasks, tenant_id=Depends(get_tenant_id)):
    item = await _claim_next(tenant_id)
    if not item:
        raise HTTPException(status_code=404, detail="The queue is empty.")
    return await launch_queue_item(tenant_id, item, background_tasks)


@router.post("/{item_id}/launch")
async def launch_item(item_id: str, background_tasks: BackgroundTasks, tenant_id=Depends(get_tenant_id)):
    item = await _claim_item(tenant_id, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found or already launched.")
    return await launch_queue_item(tenant_id, item, background_tasks)
