"""Durable, single-machine preview job persistence and worker execution."""
from __future__ import annotations

import json
import logging

import generation_claims
from database import get_pool
from error_utils import USER_FACING_PREFIX, humanize_error
from factual_source_search import SourceDiscoveryError
from task_store import db_persist_task

logger = logging.getLogger(__name__)


def _row(row):
    if not row:
        return None
    data = dict(row)
    if isinstance(data.get("result"), str):
        data["result"] = json.loads(data["result"])
    return data


def _source_discovery_failure(error: SourceDiscoveryError, machine: str) -> tuple[str, dict]:
    """Return bounded, UI-safe details without retaining provider responses."""
    safe_error = humanize_error(error)
    raw_code = getattr(error, "code", None) or getattr(error, "failure_code", None)
    failure_code = raw_code if isinstance(raw_code, str) and raw_code.replace("_", "").isalnum() else "source_discovery_failed"
    raw_attempts = getattr(error, "attempts", 0)
    attempts = raw_attempts if isinstance(raw_attempts, int) and not isinstance(raw_attempts, bool) else 0
    raw_next = getattr(error, "next_action", None)
    next_action = raw_next[len(USER_FACING_PREFIX):] if isinstance(raw_next, str) and raw_next.startswith(USER_FACING_PREFIX) else raw_next
    stage = getattr(error, "stage", None)
    error_machine = getattr(error, "machine", None)
    provider_operation_failed = getattr(error, "provider_operation_failed", None)
    details = {
        "stage": stage if isinstance(stage, str) and stage else "research",
        "machine": error_machine if isinstance(error_machine, str) and error_machine else machine,
        "failure_code": failure_code[:80],
        "retryable": getattr(error, "retryable", True) if isinstance(getattr(error, "retryable", True), bool) else True,
        "attempts": max(0, min(attempts, 4)),
        "saved_progress": getattr(error, "saved_progress", False) if isinstance(getattr(error, "saved_progress", False), bool) else False,
        "next_action": next_action if isinstance(next_action, str) and next_action else "resume",
    }
    if isinstance(provider_operation_failed, bool):
        details["provider_operation_failed"] = provider_operation_failed
    return safe_error, details


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
                              message=f"Preparing preview for {job['machine']}", job_id=f"machine-preview:{job_id}",
                              required=True)
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
    except SourceDiscoveryError as exc:
        safe_error, details = _source_discovery_failure(exc, job["machine"])
        logger.info("machine preview source discovery stopped id=%s code=%s", job_id, details["failure_code"])
        result = {"status": "failed", "error": safe_error, **details}
        pool = await get_pool()
        async with pool.acquire() as conn:
            updated = await conn.execute(
                "UPDATE machine_preview_jobs SET status='failed', result=$2::jsonb, error=$3, updated_at=now() "
                "WHERE id=$1 AND status='running'", job_id, json.dumps(result), safe_error,
            )
        if updated.endswith(" 0"):
            raise
        await db_persist_task(job["tenant_id"], job["video_id"], "machine_preview", "failed",
                              error=safe_error, job_id=f"machine-preview:{job_id}")
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
