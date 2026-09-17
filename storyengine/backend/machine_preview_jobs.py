"""Durable, single-machine preview job persistence and worker execution."""
from __future__ import annotations

import json
import logging

import generation_claims
from database import get_pool
from task_store import db_persist_task

logger = logging.getLogger(__name__)


def _row(row):
    if not row:
        return None
    data = dict(row)
    if isinstance(data.get("result"), str):
        data["result"] = json.loads(data["result"])
    return data


async def get_job(tenant_id: str, video_id: str, job_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return _row(await conn.fetchrow(
            "SELECT id, tenant_id, video_id, machine, status, result, error, created_at, updated_at "
            "FROM machine_preview_jobs WHERE id=$1 AND tenant_id=$2 AND video_id=$3",
            job_id, tenant_id, video_id,
        ))


async def run_job(job_id: str) -> dict:
    """Run at most once: guarded pending->running transition is the work claim."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE machine_preview_jobs SET status='running', updated_at=now() "
            "WHERE id=$1 AND status='pending' RETURNING id, tenant_id, video_id, machine",
            job_id,
        )
    if not row:
        return {"status": "ignored", "job_id": job_id}
    job = dict(row)
    job["id"] = str(job["id"])
    job["tenant_id"] = str(job["tenant_id"])
    job["video_id"] = str(job["video_id"])
    owner = f"machine-preview:{job_id}"
    try:
        await db_persist_task(job["tenant_id"], job["video_id"], "machine_preview", "running",
                              message=f"Preparing preview for {job['machine']}", job_id=f"machine-preview:{job_id}")
        pool = await get_pool()
        async with pool.acquire() as conn:
            claim = await conn.fetchrow(
                "SELECT 1 FROM generation_claims WHERE tenant_id=$1 AND video_id=$2 "
                "AND stage='main' AND claimed_by=$3",
                job["tenant_id"], job["video_id"], owner,
            )
        if not claim:
            raise RuntimeError("Preview job no longer owns its generation claim")
        from cancel_registry import is_cancel_requested
        if await is_cancel_requested(job["tenant_id"], job["video_id"]):
            result, status, error = {"status": "cancelled"}, "cancelled", "Cancelled before preview work started"
        else:
            from pipeline_executor import PipelineExecutor
            result = await PipelineExecutor(job["tenant_id"]).run_machine_script_preview(job["video_id"], job["machine"])
            status = str(result.get("status") or "failed")
            preview = result.get("preview") if isinstance(result, dict) else None
            if status == "completed" and isinstance(preview, dict) and preview.get("passed") is not True:
                status = "needs_review"
            if status not in {"completed", "needs_review", "cancelled"} or not preview and status == "completed":
                status = "failed"
            if await is_cancel_requested(job["tenant_id"], job["video_id"]):
                status = "cancelled"
            if isinstance(result, dict) and status != result.get("status"):
                result = {**result, "status": status}
            error = str(result.get("error") or "") or None
        pool = await get_pool()
        async with pool.acquire() as conn:
            updated = await conn.execute(
                "UPDATE machine_preview_jobs SET status=$2, result=$3::jsonb, error=$4, updated_at=now() "
                "WHERE id=$1 AND status='running'", job_id, status, json.dumps(result), error,
            )
        if updated.endswith(" 0"):
            raise RuntimeError("Preview job terminal state was not persisted")
        activity_status = "failed" if status == "needs_review" else status
        activity_error = error or ("Preview needs review" if status == "needs_review" else None)
        await db_persist_task(job["tenant_id"], job["video_id"], "machine_preview", activity_status,
                              message=f"Preview {status}", error=activity_error, job_id=f"machine-preview:{job_id}")
        return result
    except Exception as exc:
        logger.exception("machine preview job failed id=%s", job_id)
        pool = await get_pool()
        async with pool.acquire() as conn:
            updated = await conn.execute(
                "UPDATE machine_preview_jobs SET status='failed', error=$2, updated_at=now() "
                "WHERE id=$1 AND status='running'", job_id, str(exc),
            )
        if updated.endswith(" 0"):
            raise
        await db_persist_task(job["tenant_id"], job["video_id"], "machine_preview", "failed",
                              error=str(exc), job_id=f"machine-preview:{job_id}")
        return {"status": "failed", "error": str(exc)}
    finally:
        # Terminal persistence is required before this exact-owner release.
        pool = await get_pool()
        async with pool.acquire() as conn:
            terminal = await conn.fetchval(
                "SELECT status IN ('completed','needs_review','failed','cancelled') FROM machine_preview_jobs WHERE id=$1", job_id)
        if terminal:
            await generation_claims.release_owned(job["tenant_id"], job["video_id"], "main", owner)
