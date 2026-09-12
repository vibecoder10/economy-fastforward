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

import json
import logging
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from auth import get_tenant_id
from database import execute, fetch_all, fetch_one, get_pool
from queue_controls import PROVIDER_ERROR_PATTERN, sync_provider_pause

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
    continuous: bool = False
    required_render_mode: Optional[str] = None
    delivery_mode: Literal["render_only", "youtube_unlisted"] = "render_only"


class QueuePatch(BaseModel):
    title: Optional[str] = None
    position: Optional[int] = None
    status: Optional[str] = None  # 'queued' | 'skipped'


# --- engine functions (shared by routes, chat ops, and the autopilot loop) ---

async def add_queue_items(
    tenant_id,
    items: list[dict[str, Any]],
    source_asset_id: Optional[str] = None,
    *,
    continuous: bool = False,
    required_render_mode: Optional[str] = None,
    delivery_mode: str = "render_only",
) -> int:
    """Append items (dicts with title / framework_angle / writer_guidance /
    user_script) to the end of the tenant's queue, preserving given order.
    Positions move in gaps of 10 so reorders are one-row updates."""
    if delivery_mode not in ("render_only", "youtube_unlisted"):
        raise HTTPException(status_code=422, detail="Unsupported queue delivery mode.")
    delivery_channel_id = None
    if delivery_mode == "youtube_unlisted":
        profile = await fetch_one(
            "SELECT youtube_channel_id, youtube_refresh_token FROM channel_profiles "
            "WHERE tenant_id=$1",
            tenant_id,
        )
        delivery_channel_id = str((profile or {}).get("youtube_channel_id") or "").strip()
        if not delivery_channel_id or not (profile or {}).get("youtube_refresh_token"):
            raise HTTPException(
                status_code=409,
                detail="Connect the destination YouTube channel before starting unlisted delivery.",
            )
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
        result = await execute(
            "INSERT INTO production_queue (tenant_id, position, title, framework_angle, "
            "writer_guidance, user_script, source_asset_id, item_key, continuous, "
            "required_render_mode, delivery_mode, delivery_channel_id) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, "
            "lower(regexp_replace(trim($8), '[[:space:]]+', ' ', 'g')), $9, $10, $11, $12) "
            "ON CONFLICT (tenant_id, item_key) WHERE item_key IS NOT NULL DO NOTHING",
            tenant_id, pos, title,
            (it.get("framework_angle") or None),
            (it.get("writer_guidance") or None),
            (it.get("user_script") or None),
            source_asset_id,
            title,
            continuous,
            required_render_mode,
            delivery_mode,
            delivery_channel_id,
        )
        if not str(result).endswith(" 0"):
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


@asynccontextmanager
async def _locked_queue_connection(tenant_id):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1::text, 0))", str(tenant_id)
            )
            yield conn


async def get_queue_pause(tenant_id) -> dict | None:
    async with _locked_queue_connection(tenant_id) as conn:
        return await sync_provider_pause(conn, tenant_id)


async def _claim_next(tenant_id) -> Optional[dict]:
    """Atomically claim the front item while serializing the tenant lane."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # A separate statement matters: after waiting for this lock,
            # READ COMMITTED gives the candidate statement a fresh snapshot.
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1::text, 0))",
                str(tenant_id),
            )
            control = await sync_provider_pause(conn, tenant_id)
            if control and control.get("paused"):
                return None
            return await conn.fetchrow(
                """WITH candidate AS (
               SELECT q.id FROM production_queue q
               WHERE q.tenant_id = $1 AND q.status = 'queued'
                 AND NOT EXISTS (
                     SELECT 1 FROM production_queue active
                     WHERE active.tenant_id = $1
                       AND active.status IN ('launched', 'dispatching', 'running')
                 )
                 AND NOT EXISTS (
                     SELECT 1 FROM videos v
                     WHERE v.tenant_id = $1
                       AND (v.source = 'queue' OR v.source LIKE 'autopilot%')
                       AND v.deleted_at IS NULL
                       AND NOT EXISTS (
                           SELECT 1 FROM production_queue managed
                           WHERE managed.tenant_id = v.tenant_id
                             AND managed.video_id = v.id
                       )
                       AND (
                           v.status NOT IN ('rendered', 'uploaded', 'uploaded_draft',
                                            'done', 'published', 'failed')
                           OR EXISTS (
                               SELECT 1 FROM generation_claims gc
                               WHERE gc.tenant_id = v.tenant_id AND gc.video_id = v.id
                           )
                           OR EXISTS (
                               SELECT 1 FROM background_tasks b
                               WHERE b.tenant_id = v.tenant_id AND b.video_id = v.id
                                 AND b.status IN ('pending', 'running')
                           )
                       )
                 )
               ORDER BY q.position, q.created_at LIMIT 1
               FOR UPDATE OF q SKIP LOCKED
           )
           UPDATE production_queue SET status = 'launched', launched_at = now(), updated_at = now()
           WHERE id = (SELECT id FROM candidate) RETURNING *""",
                tenant_id,
            )


async def _claim_item(tenant_id, item_id: str) -> Optional[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1::text, 0))",
                str(tenant_id),
            )
            control = await sync_provider_pause(conn, tenant_id)
            if control and control.get("paused"):
                return None
            return await conn.fetchrow(
                """WITH candidate AS (
               SELECT q.id FROM production_queue q
               WHERE q.id = $1 AND q.tenant_id = $2 AND q.status = 'queued'
                 AND NOT EXISTS (
                     SELECT 1 FROM production_queue active
                     WHERE active.tenant_id = $2
                       AND active.status IN ('launched', 'dispatching', 'running')
                 )
                 AND NOT EXISTS (
                     SELECT 1 FROM videos v
                     WHERE v.tenant_id = $2
                       AND (v.source = 'queue' OR v.source LIKE 'autopilot%')
                       AND v.deleted_at IS NULL
                       AND NOT EXISTS (
                           SELECT 1 FROM production_queue managed
                           WHERE managed.tenant_id = v.tenant_id
                             AND managed.video_id = v.id
                       )
                       AND (
                           v.status NOT IN ('rendered', 'uploaded', 'uploaded_draft',
                                            'done', 'published', 'failed')
                           OR EXISTS (
                               SELECT 1 FROM generation_claims gc
                               WHERE gc.tenant_id = v.tenant_id AND gc.video_id = v.id
                           )
                           OR EXISTS (
                               SELECT 1 FROM background_tasks b
                               WHERE b.tenant_id = v.tenant_id AND b.video_id = v.id
                                 AND b.status IN ('pending', 'running')
                           )
                       )
                 )
               FOR UPDATE OF q SKIP LOCKED
           )
           UPDATE production_queue SET status = 'launched', launched_at = now(), updated_at = now()
           WHERE id = (SELECT id FROM candidate) RETURNING *""",
                item_id, tenant_id,
            )


async def _unclaim(tenant_id, item_id) -> None:
    await execute(
        "UPDATE production_queue SET status = 'queued', launched_at = NULL, updated_at = now() "
        "WHERE id = $1 AND tenant_id = $2",
        item_id, tenant_id,
    )


async def _reconcile_queue_items(tenant_id: str) -> None:
    """Project exact video/task truth back onto queue lifecycle state."""
    async with _locked_queue_connection(tenant_id) as conn:
        await conn.execute(
            """UPDATE production_queue q
               SET status = 'completed', completed_at = now(), last_error = NULL,
                   updated_at = now()
               FROM videos v
               WHERE q.tenant_id = $1 AND q.tenant_id = v.tenant_id
                 AND q.video_id = v.id AND q.status IN ('dispatching', 'running', 'launched')
                 AND (
                     (q.delivery_mode = 'render_only'
                      AND v.status IN ('rendered', 'uploaded', 'uploaded_draft', 'done', 'published'))
                     OR
                     (q.delivery_mode = 'youtube_unlisted'
                      AND v.upload_status = 'uploaded'
                      AND v.queue_delivery_receipt->>'status' = 'verified'
                      AND v.queue_delivery_receipt->>'channel_id' = q.delivery_channel_id
                      AND v.queue_delivery_receipt->>'privacy' = 'unlisted')
                 )""",
            tenant_id,
        )
        await conn.execute(
            """WITH latest AS (
                   SELECT DISTINCT ON (tenant_id, video_id)
                          b.tenant_id, b.video_id, b.status, b.message, b.error_message
                   FROM background_tasks b
                   JOIN production_queue q ON q.tenant_id = b.tenant_id
                                          AND q.video_id = b.video_id
                   WHERE b.task_type = 'autobuild'
                     AND b.created_at >= q.launched_at
                   ORDER BY b.tenant_id, b.video_id, b.created_at DESC
               )
               UPDATE production_queue q
               SET status = CASE
                       WHEN t.status = 'failed' AND q.continuous AND q.attempt_count < 3
                        AND NOT (COALESCE(t.error_message, t.message, '') ~* $2)
                        AND COALESCE(t.error_message, t.message, '') ~*
                            '(timeout|timed out|temporar|unavailable|connection|worker|redis|interrupt|retry)'
                       THEN 'queued' ELSE 'failed' END,
                   last_error = COALESCE(t.error_message, t.message,
                       'Run All stopped before producing a rendered video'), updated_at = now()
               FROM latest t, videos v
               WHERE q.tenant_id = $1 AND q.status IN ('dispatching', 'running', 'launched')
                 AND t.tenant_id = q.tenant_id AND t.video_id = q.video_id
                 AND v.id = q.video_id AND v.tenant_id = q.tenant_id
                 AND t.status IN ('failed', 'completed', 'cancelled')
                 AND (
                     (q.delivery_mode = 'render_only'
                      AND v.status NOT IN ('rendered', 'uploaded', 'uploaded_draft', 'done', 'published'))
                     OR
                     (q.delivery_mode = 'youtube_unlisted'
                      AND NOT (
                          COALESCE(v.upload_status = 'uploaded', false)
                          AND COALESCE(v.queue_delivery_receipt->>'status' = 'verified', false)
                          AND COALESCE(
                              v.queue_delivery_receipt->>'channel_id' = q.delivery_channel_id, false
                          )
                          AND COALESCE(v.queue_delivery_receipt->>'privacy' = 'unlisted', false)
                      ))
                 )""",
            tenant_id, PROVIDER_ERROR_PATTERN,
        )
        # A process can die after reserving the video but before enqueueing. Make
        # that same linked video claimable again; never create a replacement.
        await conn.execute(
            """UPDATE production_queue q
               SET status = 'queued', last_error = 'Dispatch interrupted before queue acknowledgement',
                   updated_at = now()
               WHERE q.tenant_id = $1 AND q.status IN ('launched', 'dispatching')
                 AND q.updated_at < now() - interval '10 minutes'
                 AND NOT EXISTS (
                     SELECT 1 FROM background_tasks b
                     WHERE b.tenant_id = q.tenant_id AND b.video_id = q.video_id
                       AND b.task_type = 'autobuild' AND b.status IN ('pending', 'running')
                 )""",
            tenant_id,
        )
        await sync_provider_pause(conn, tenant_id)


async def _prepare_video(tenant_id: str, item: dict, *, via: str) -> tuple[str, bool]:
    """Atomically create/link one deterministic video, or reuse the saved one."""
    item_id = str(item["id"])
    if item.get("video_id"):
        return str(item["video_id"]), False

    from routes.projects import _get_or_create_project
    project = await _get_or_create_project(tenant_id)
    video_id = str(uuid.uuid4())
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            locked = await conn.fetchrow(
                "SELECT * FROM production_queue WHERE id = $1 AND tenant_id = $2 FOR UPDATE",
                item_id, tenant_id,
            )
            if not locked:
                raise ValueError("Queue item disappeared before launch")
            if locked.get("video_id"):
                return str(locked["video_id"]), False
            await conn.execute(
                """INSERT INTO videos (
                       id, tenant_id, project_id, video_title, status, headline, source,
                       framework_angle, writer_guidance, created_at
                   ) VALUES ($1, $2, $3, $4, 'idea_logged', $4, $5, $6, $7, now())""",
                video_id, tenant_id, str(project["id"]), item["title"], via,
                item.get("framework_angle"), item.get("writer_guidance"),
            )
            await conn.execute(
                "UPDATE production_queue SET video_id = $1, status = 'dispatching', "
                "updated_at = now() WHERE id = $2 AND tenant_id = $3",
                video_id, item_id, tenant_id,
            )
    return video_id, True


async def _dispatch_durable_autobuild(
    tenant_id: str, item: dict, video_id: str, arq_pool,
) -> None:
    """Reserve the main lane and reuse the strict durable Run All dispatcher."""
    import generation_claims
    from routes import pipeline

    item_id = str(item["id"])
    attempts = int(item.get("attempt_count") or 0)
    if attempts >= 3:
        await execute(
            "UPDATE production_queue SET status='failed', last_error=$3, updated_at=now() "
            "WHERE id=$1 AND tenant_id=$2",
            item_id, tenant_id, "Run All retry limit reached",
        )
        raise HTTPException(status_code=409, detail="Run All retry limit reached")
    claim_owner = f"production-queue:{item_id}:{uuid.uuid4()}"
    if not await generation_claims.acquire(
        tenant_id, video_id, "main", claimed_by=claim_owner
    ):
        await execute(
            "UPDATE production_queue SET status='queued', last_error=$3, updated_at=now() "
            "WHERE id=$1 AND tenant_id=$2",
            item_id, tenant_id, "This video already has work running",
        )
        raise HTTPException(status_code=409, detail="This video already has work running")
    try:
        await pipeline._enqueue_or_fallback(
            SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(arq=arq_pool))),
            SimpleNamespace(add_task=lambda *args, **kwargs: None),
            "autobuild", video_id, tenant_id, None,
            durable_only=True,
            target="finish",
            start_msg=f"Building {item['title']} to a completed render…",
            claim_owner=claim_owner,
            delivery_mode=str(item.get("delivery_mode") or "render_only"),
            expected_channel_id=item.get("delivery_channel_id"),
        )
        await execute(
            "UPDATE production_queue SET status='running', attempt_count=attempt_count+1, "
            "last_error=NULL, updated_at=now() WHERE id=$1 AND tenant_id=$2",
            item_id, tenant_id,
        )
    except Exception as exc:
        if not getattr(exc, "dispatch_uncertain", False):
            await generation_claims.release_owned(
                tenant_id, video_id, "main", claim_owner
            )
            await execute(
                "UPDATE production_queue SET status='queued', "
                "attempt_count=attempt_count+1, last_error=$3, updated_at=now() "
                "WHERE id=$1 AND tenant_id=$2",
                item_id, tenant_id, str(exc)[:1500],
            )
        raise


async def _resolve_launch_delivery(tenant_id: str, item: dict, *, via: str, dial) -> dict:
    """Resolve explicit delivery plus the narrow legacy C55 full-auto rule."""
    resolved = dict(item)
    delivery_mode = str(resolved.get("delivery_mode") or "render_only")
    legacy_full_auto = (
        via == "autopilot_queue"
        and not bool(resolved.get("continuous"))
        and delivery_mode == "render_only"
        and getattr(dial, "dial_level", None) == "full_auto"
        and getattr(dial, "weekly_budget_cap", None) is not None
    )
    if legacy_full_auto:
        delivery_mode = "youtube_unlisted"

    if delivery_mode == "youtube_unlisted":
        profile = await fetch_one(
            "SELECT youtube_channel_id, youtube_refresh_token FROM channel_profiles "
            "WHERE tenant_id=$1",
            tenant_id,
        )
        current_channel_id = str(
            (profile or {}).get("youtube_channel_id") or ""
        ).strip()
        expected_channel_id = str(resolved.get("delivery_channel_id") or "").strip()
        if legacy_full_auto:
            expected_channel_id = current_channel_id
        if (
            not expected_channel_id
            or current_channel_id != expected_channel_id
            or not (profile or {}).get("youtube_refresh_token")
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "The saved YouTube delivery channel is no longer connected. "
                    "Reconnect that channel before retrying."
                ),
            )
        resolved["delivery_mode"] = delivery_mode
        resolved["delivery_channel_id"] = expected_channel_id
        if legacy_full_auto:
            await execute(
                "UPDATE production_queue SET delivery_mode='youtube_unlisted', "
                "delivery_channel_id=$3, updated_at=now() WHERE id=$1 AND tenant_id=$2",
                str(resolved["id"]), tenant_id, expected_channel_id,
            )
    return resolved


async def launch_queue_item(tenant_id, item: dict, arq_pool=None, *, via: str = "queue") -> dict:
    """Create the video for a CLAIMED queue item and start the pipeline —
    the queue mirror of autopilot's launch_candidate (same video shape, same
    learnings guidance, same run_research -> run_next_step loop). On any
    failure before the pipeline starts, the item is un-claimed.

    `via` (C55, P4.2-f): the video's `source` value. Defaults to the
    pre-existing 'queue' (every human `/next/launch` and `/{item_id}/launch`
    click, unchanged). `auto_produce_next` below passes 'autopilot_queue'
    instead — the ONLY thing that tells an autopilot-drained queue launch
    apart from a manual one (both otherwise build an identical video row),
    which pipeline_executor.py's full-auto continuation gates on
    (`source` must start with 'autopilot'). Cadence/in-flight dedup queries
    here and in autopilot_launch.py already match `source LIKE 'autopilot%'`
    OR `source = 'queue'`, so this rename doesn't drop 'autopilot_queue' rows
    from either check.
    """
    from routes.billing import check_plan_limits, increment_usage
    import drain_mode
    from autopilot_dial import check_weekly_budget, get_autopilot_dial

    item_id = str(item["id"])
    if arq_pool is None:
        await _unclaim(tenant_id, item_id)
        raise HTTPException(
            status_code=503,
            detail="The durable worker queue is unavailable. Nothing was started.",
        )
    try:
        await drain_mode.assert_accepting_new_work()
        dial = await get_autopilot_dial(tenant_id)
        item = await _resolve_launch_delivery(tenant_id, item, via=via, dial=dial)
        if dial.kill_switch_tripped_at is not None:
            raise HTTPException(status_code=409, detail="Autopilot kill switch is active")
        ok, spent, cap = await check_weekly_budget(tenant_id)
        if not ok:
            raise HTTPException(
                status_code=409,
                detail=f"Weekly budget cap ${cap:.2f} reached (spent ${spent:.2f})",
            )
        if not item.get("video_id"):
            await check_plan_limits(tenant_id, "video")
    except Exception:
        await _unclaim(tenant_id, item_id)
        raise
    created = False
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

        video_id, created = await _prepare_video(tenant_id, item, via=via)
        if created:
            await increment_usage(tenant_id, "videos_created")
        required_mode = str(item.get("required_render_mode") or "").strip()
        if required_mode:
            if required_mode != "static_docu":
                raise ValueError(f"Unsupported required render mode: {required_mode}")
            await execute(
                "UPDATE videos SET render_mode='static_docu', updated_at=now() "
                "WHERE id=$1 AND tenant_id=$2",
                video_id, tenant_id,
            )
        if learnings_text:
            await execute(
                "UPDATE videos SET script_system_prompt=$1 WHERE id=$2 AND tenant_id=$3 "
                "AND script_system_prompt IS NULL",
                learnings_text, video_id, tenant_id,
            )
        # House script format + locked channel format + locked cast ride every
        # queued launch (all fail-soft inside).
        from routes.script_templates import apply_default_template
        await apply_default_template(tenant_id, video_id)
        from channel_format import apply_format_defaults
        await apply_format_defaults(tenant_id, video_id)
        from routes.characters import apply_locked_cast
        await apply_locked_cast(tenant_id, video_id)
        if required_mode:
            mode_row = await fetch_one(
                "SELECT render_mode FROM videos WHERE id=$1 AND tenant_id=$2",
                video_id, tenant_id,
            )
            actual_mode = str((mode_row or {}).get("render_mode") or "")
            if actual_mode != required_mode:
                raise ValueError(
                    f"Required render mode {required_mode!r} was not applied; got {actual_mode!r}"
                )
        # A queue item can carry the creator's own script — install it verbatim
        # now so run_script skips generation (script_source='user_supplied').
        if (item.get("user_script") or "").strip():
            from user_script import set_user_script
            await set_user_script(tenant_id, video_id, item["user_script"])
    except Exception as exc:
        await execute(
            "UPDATE production_queue SET status=$3, last_error=$4, updated_at=now() "
            "WHERE id=$1 AND tenant_id=$2",
            item_id, tenant_id, "queued" if not created else "failed", str(exc)[:1500],
        )
        raise
    await _dispatch_durable_autobuild(tenant_id, item, video_id, arq_pool)

    return {
        "status": "launched",
        "queue_id": item_id,
        "video_id": video_id,
        "video_title": item["title"],
        "continuous": bool(item.get("continuous")),
        "delivery_mode": str(item.get("delivery_mode") or "render_only"),
        "delivery_channel_id": item.get("delivery_channel_id"),
        "message": ("Video created and durable Run All queued" if created
                    else "Saved video resumed with durable Run All"),
    }


async def auto_produce_next(tenant_id, arq_pool=None) -> Optional[dict]:
    """One autopilot heartbeat for the queue: if the tenant has queued items,
    the production cadence says a new video is due, and nothing is already in
    flight, claim + launch the front of the queue. Returns launch info or None.
    Called by main.py:_auto_produce_queue for Autopilot-enabled tenants and
    explicitly continuous queues."""
    await _reconcile_queue_items(tenant_id)
    pause = await get_queue_pause(tenant_id)
    if pause and pause.get("paused"):
        return {"status": "paused", "message": pause["reason"], "pause": pause}
    has = await fetch_one(
        "SELECT id, continuous FROM production_queue WHERE tenant_id = $1 "
        "AND status = 'queued' ORDER BY position, created_at LIMIT 1",
        tenant_id,
    )
    if not has:
        return None

    cfg = await fetch_one(
        "SELECT production_interval_days FROM autopilot_config WHERE tenant_id = $1", tenant_id
    )
    interval = max(1, int((cfg or {}).get("production_interval_days") or 0) or 2)

    # One shared cadence across queue launches AND autopilot candidate launches.
    # Deleted videos don't count — deleting a launch means "that was wrong,
    # move on", not "wait out its slot".
    last = await fetch_one(
        """SELECT GREATEST(
               (SELECT MAX(launched_at) FROM production_queue WHERE tenant_id = $1),
               (SELECT MAX(created_at) FROM videos
                WHERE tenant_id = $1 AND (source = 'queue' OR source LIKE 'autopilot%')
                  AND deleted_at IS NULL)
           ) AS t""",
        tenant_id,
    )
    if not bool(has.get("continuous")) and last and last.get("t") is not None:
        due = await fetch_one(
            "SELECT (now() - $1::timestamptz) >= make_interval(days => $2) AS due",
            last["t"], interval,
        )
        if not (due and due["due"]):
            return None

    # Never stack builds: a non-terminal engine-launched video blocks the lane
    # (including ones parked at an approval gate — the creator must act first).
    inflight = await fetch_one(
        """SELECT 1 AS x WHERE EXISTS (
               SELECT 1 FROM production_queue q
               WHERE q.tenant_id = $1
                 AND q.status IN ('launched', 'dispatching', 'running')
           ) OR EXISTS (
               SELECT 1 FROM videos v
               WHERE v.tenant_id = $1
                 AND (v.source = 'queue' OR v.source LIKE 'autopilot%')
                 AND v.deleted_at IS NULL
                 AND NOT EXISTS (
                     SELECT 1 FROM production_queue managed
                     WHERE managed.tenant_id = v.tenant_id
                       AND managed.video_id = v.id
                 )
                 AND (
                     v.status NOT IN ('rendered', 'uploaded', 'uploaded_draft',
                                      'done', 'published', 'failed')
                     OR EXISTS (
                         SELECT 1 FROM generation_claims gc
                         WHERE gc.tenant_id = v.tenant_id AND gc.video_id = v.id
                     )
                     OR EXISTS (
                         SELECT 1 FROM background_tasks b
                         WHERE b.tenant_id = v.tenant_id AND b.video_id = v.id
                           AND b.status IN ('pending', 'running')
                     )
                 )
           )""",
        tenant_id,
    )
    if inflight:
        return None

    item = await _claim_next(tenant_id)
    if not item:
        return None
    return await launch_queue_item(
        tenant_id, item, arq_pool=arq_pool, via="autopilot_queue"
    )


# --- routes ------------------------------------------------------------------

@router.get("")
async def list_queue(tenant_id=Depends(get_tenant_id)):
    await _reconcile_queue_items(tenant_id)
    rows = await fetch_all(
        """SELECT id, position, title, framework_angle, status, video_id,
                  source_asset_id, launched_at, created_at, continuous,
                  required_render_mode, attempt_count, last_error, completed_at
                  , delivery_mode, delivery_channel_id
           FROM production_queue WHERE tenant_id = $1 AND status != 'skipped'
           ORDER BY status = 'queued' DESC, position, created_at""",
        tenant_id,
    )
    return {"items": [dict(r) for r in rows], "pause": await get_queue_pause(tenant_id)}


@router.post("")
async def add_to_queue(
    body: QueueAddRequest,
    request: Request,
    tenant_id=Depends(get_tenant_id),
):
    if not body.items:
        raise HTTPException(status_code=400, detail="No items to queue.")
    if body.required_render_mode not in (None, "static_docu"):
        raise HTTPException(status_code=422, detail="Unsupported required render mode.")
    n = await add_queue_items(
        tenant_id,
        [i.model_dump() for i in body.items],
        source_asset_id=body.source_asset_id,
        continuous=body.continuous,
        required_render_mode=body.required_render_mode,
        delivery_mode=body.delivery_mode,
    )
    if n == 0 and not any(i.title.strip() for i in body.items):
        raise HTTPException(status_code=400, detail="No usable titles in those items.")
    response = {"status": "queued", "count": n}
    if n == 0:
        response["message"] = "Those titles are already in this production queue."
    if body.continuous:
        queue_wakeup = getattr(request.app.state, "queue_wakeup", None)
        if queue_wakeup is not None:
            queue_wakeup.set()
        arq_pool = getattr(request.app.state, "arq", None)
        if arq_pool is None:
            message = (
                "Titles are saved; continuous production is waiting for the durable worker queue."
            )
            await execute(
                "UPDATE production_queue SET last_error=$2, updated_at=now() "
                "WHERE tenant_id=$1 AND continuous=true AND status='queued'",
                tenant_id, message,
            )
            response["message"] = message
        else:
            try:
                launch = await auto_produce_next(tenant_id, arq_pool=arq_pool)
                if launch and launch.get("status") == "paused":
                    response["message"] = "Titles saved. " + launch["message"]
                    response["pause"] = launch["pause"]
                elif launch:
                    response["launch"] = launch
            except Exception as exc:
                # Intake succeeded. A policy or availability gate blocks
                # dispatch, so preserve the queue and return its actionable
                # state rather than making the whole POST look rolled back.
                import drain_mode
                if not isinstance(exc, (HTTPException, drain_mode.DrainModeActive)):
                    raise
                detail = getattr(exc, "detail", None)
                if isinstance(detail, dict):
                    message = str(detail.get("message") or detail.get("error") or detail)
                else:
                    message = str(detail or exc)
                await execute(
                    "UPDATE production_queue SET last_error=$2, updated_at=now() "
                    "WHERE tenant_id=$1 AND continuous=true AND status='queued'",
                    tenant_id, message,
                )
                response["message"] = message
    return response


async def _resume_saved_item(tenant_id) -> Optional[dict]:
    """A single explicit recovery opens one new bounded retry window.

    Reserve the blocked video under the same lock as normal claims, so a
    scheduler wakeup or second Resume cannot jump ahead or duplicate it.
    """
    async with _locked_queue_connection(tenant_id) as conn:
        pause = await sync_provider_pause(conn, tenant_id)
        if not pause or not pause.get("paused"):
            return None
        active = await conn.fetchval(
            """SELECT EXISTS(SELECT 1 FROM production_queue WHERE tenant_id=$1
                 AND status IN ('launched','dispatching','running'))
               OR EXISTS (
                   SELECT 1 FROM videos v WHERE v.tenant_id=$1
                     AND (v.source='queue' OR v.source LIKE 'autopilot%')
                     AND v.deleted_at IS NULL
                     AND NOT EXISTS (SELECT 1 FROM production_queue managed
                         WHERE managed.tenant_id=v.tenant_id AND managed.video_id=v.id)
                     AND (v.status NOT IN ('rendered','uploaded','uploaded_draft','done','published','failed')
                         OR EXISTS (SELECT 1 FROM generation_claims gc
                             WHERE gc.tenant_id=v.tenant_id AND gc.video_id=v.id)
                         OR EXISTS (SELECT 1 FROM background_tasks b
                             WHERE b.tenant_id=v.tenant_id AND b.video_id=v.id
                               AND b.status IN ('pending','running')))
               )""", tenant_id
        )
        if active:
            raise HTTPException(status_code=409, detail="Production is still active; wait for it to stop before resuming.")
        item = await conn.fetchrow(
            """SELECT * FROM production_queue WHERE tenant_id=$1
                 AND (id=$2 AND status='failed' OR status='queued')
               ORDER BY (id=$2) DESC NULLS LAST, position, created_at
               LIMIT 1 FOR UPDATE""", tenant_id, pause.get("blocking_queue_id")
        )
        if item:
            busy = await conn.fetchval(
                """SELECT EXISTS(SELECT 1 FROM generation_claims
                       WHERE tenant_id=$1 AND video_id=$2)
                   OR EXISTS(SELECT 1 FROM background_tasks
                       WHERE tenant_id=$1 AND video_id=$2 AND status IN ('pending','running'))""",
                tenant_id, item.get("video_id"),
            )
            if busy:
                raise HTTPException(status_code=409, detail="This video still has active work; saved production remains paused.")
            item = await conn.fetchrow(
                """UPDATE production_queue SET status='launched', launched_at=now(),
                       attempt_count=0, last_error=NULL, completed_at=NULL, updated_at=now()
                   WHERE id=$1 AND tenant_id=$2 RETURNING *""", item["id"], tenant_id
            )
        await conn.execute(
            """UPDATE production_queue_controls SET paused=false, resumed_at=now(),
                   resume_count=resume_count+1, updated_at=now()
               WHERE tenant_id=$1""", tenant_id
        )
        return dict(item) if item else None


@router.post("/resume")
async def resume_queue(request: Request, tenant_id=Depends(get_tenant_id)):
    arq_pool = getattr(request.app.state, "arq", None)
    if arq_pool is None:
        raise HTTPException(status_code=503, detail="The durable worker queue is unavailable; production remains paused.")
    import drain_mode
    await drain_mode.assert_accepting_new_work()
    await _reconcile_queue_items(tenant_id)
    item = await _resume_saved_item(tenant_id)
    if item is None:
        return {"status": "resumed", "pause": await get_queue_pause(tenant_id)}
    launch = await launch_queue_item(tenant_id, item, arq_pool=arq_pool)
    wakeup = getattr(request.app.state, "queue_wakeup", None)
    if wakeup is not None:
        wakeup.set()
    return {"status": "running", "launch": launch, "pause": await get_queue_pause(tenant_id)}


@router.patch("/{item_id}")
async def patch_queue_item(item_id: str, body: QueuePatch, tenant_id=Depends(get_tenant_id)):
    pause = await get_queue_pause(tenant_id)
    if body.status == "queued" and pause and pause.get("paused"):
        raise HTTPException(status_code=409, detail="Production is paused. Fix the provider and use Resume for the list.")
    sets, params = [], []
    if body.title is not None and body.title.strip():
        normalized_title = body.title.strip()[:300]
        params.append(normalized_title); sets.append(f"title = ${len(params)}")
        params.append(normalized_title)
        sets.append(
            f"item_key = lower(regexp_replace(trim(${len(params)}), "
            "'[[:space:]]+', ' ', 'g'))"
        )
    if body.position is not None:
        params.append(int(body.position)); sets.append(f"position = ${len(params)}")
    if body.status in ("queued", "skipped"):
        params.append(body.status); sets.append(f"status = ${len(params)}")
        if body.status == "queued":
            # Explicit retry is a new bounded retry window; automatic retries
            # never call this route and retain their three-attempt cap.
            sets.extend(["attempt_count=0", "last_error=NULL", "completed_at=NULL"])
    if not sets:
        return {"status": "unchanged"}
    params += [item_id, tenant_id]
    try:
        row = await fetch_one(
            f"UPDATE production_queue SET {', '.join(sets)}, updated_at = now() "
            f"WHERE id = ${len(params) - 1} AND tenant_id = ${len(params)} "
            "AND status IN ('queued', 'failed') "
            "RETURNING id",
            *params,
        )
    except Exception as exc:
        if getattr(exc, "sqlstate", None) == "23505":
            raise HTTPException(
                status_code=409, detail="That title is already in this production queue."
            ) from exc
        raise
    if not row:
        raise HTTPException(status_code=404, detail="Queue item not found (or already launched).")
    return {"status": "ok"}


@router.delete("/{item_id}")
async def delete_queue_item(item_id: str, tenant_id=Depends(get_tenant_id)):
    # Persist any shared failure before deleting its source row.
    await get_queue_pause(tenant_id)
    await execute(
        "DELETE FROM production_queue WHERE id = $1 AND tenant_id = $2 "
        "AND status IN ('queued', 'failed', 'skipped', 'completed')",
        item_id, tenant_id,
    )
    return {"status": "deleted"}


@router.post("/next/launch")
async def launch_next(request: Request, tenant_id=Depends(get_tenant_id)):
    item = await _claim_next(tenant_id)
    if not item:
        raise HTTPException(status_code=404, detail="The queue is empty.")
    return await launch_queue_item(
        tenant_id, item, arq_pool=getattr(request.app.state, "arq", None)
    )


@router.post("/{item_id}/launch")
async def launch_item(item_id: str, request: Request, tenant_id=Depends(get_tenant_id)):
    item = await _claim_item(tenant_id, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found or already launched.")
    return await launch_queue_item(
        tenant_id, item, arq_pool=getattr(request.app.state, "arq", None)
    )
