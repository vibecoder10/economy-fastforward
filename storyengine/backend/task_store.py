"""Shared task persistence helpers — used by both routes and worker.

Extracted from routes/pipeline.py to avoid circular imports when
worker.py needs to update background_tasks rows.
"""

import logging
from typing import Optional

from database import fetch_one, execute

logger = logging.getLogger(__name__)


def _write_landed(result) -> bool:
    """Interpret asyncpg's command tag without treating a conflict as success."""
    return str(result or "").rsplit(" ", 1)[-1] not in {"", "0"}


async def db_persist_task(
    tenant_id: str,
    video_id: str,
    task_type: str,
    status: str,
    message: Optional[str] = None,
    error: Optional[str] = None,
    job_id: Optional[str] = None,
    attempt: int = 1,
    *,
    required: bool = False,
) -> None:
    """Persist task state to the background_tasks table.

    - 'running': promotes an exact pending/running row, or inserts one
    - 'pending': inserts a new row, skipping if a pending row with same job_id exists
    - 'completed'/'failed': updates only the exact operation to terminal state

    All failures are swallowed by default — persistence is best-effort.  Callers
    which must durably record a work claim may pass ``required=True``.
    """
    try:
        if status == "running":
            existing = await fetch_one(
                "SELECT id FROM background_tasks "
                "WHERE tenant_id = $1 AND video_id = $2 AND task_type = $3 "
                "AND (($4 IS NULL AND job_id IS NULL) OR job_id = $4) "
                "AND status IN ('pending', 'running') LIMIT 1",
                tenant_id, video_id, task_type, job_id,
            )
            if existing:
                updated = await execute(
                    "UPDATE background_tasks SET status = 'running', message = $1 "
                    "WHERE id = $2 AND tenant_id = $3 AND video_id = $4 AND task_type = $5 "
                    "AND (($6 IS NULL AND job_id IS NULL) OR job_id = $6) "
                    "AND status IN ('pending', 'running')",
                    message, existing["id"], tenant_id, video_id, task_type, job_id,
                )
                if required and not _write_landed(updated):
                    verified = await fetch_one(
                        "SELECT id FROM background_tasks "
                        "WHERE tenant_id = $1 AND video_id = $2 AND task_type = $3 "
                        "AND (($4 IS NULL AND job_id IS NULL) OR job_id = $4) "
                        "AND status = 'running' LIMIT 1",
                        tenant_id, video_id, task_type, job_id,
                    )
                    if not verified:
                        raise RuntimeError("Required task start update did not persist")
                return
        elif status == "pending":
            existing = await fetch_one(
                "SELECT id FROM background_tasks "
                "WHERE tenant_id = $1 AND video_id = $2 AND task_type = $3 "
                "AND (($4 IS NULL AND job_id IS NULL) OR job_id = $4) "
                "AND status = 'pending' LIMIT 1",
                tenant_id, video_id, task_type, job_id,
            )
            if existing:
                return
        elif status in ("completed", "failed", "cancelled"):
            await execute(
                "UPDATE background_tasks "
                "SET status = $1, message = $2, error_message = $3, completed_at = now() "
                "WHERE tenant_id = $4 AND video_id = $5 AND task_type = $6 "
                "AND (($7 IS NULL AND job_id IS NULL) OR job_id = $7) "
                "AND (status IN ('running', 'pending') "
                "      OR (status = 'cancelled' AND completed_at IS NULL))",
                status, message, error, tenant_id, video_id, task_type, job_id,
            )
            return

        # C16d (S7-8): migration 094's partial UNIQUE index on (job_id) WHERE
        # job_id IS NOT NULL is the DB-level backstop behind the pending-branch
        # check-then-insert above — two concurrent calls for the SAME job_id
        # can both pass the SELECT before either INSERTs (TOCTOU race); ON
        # CONFLICT DO NOTHING makes the loser a silent no-op instead of a
        # duplicate row, with zero change to the NULL-job_id (in-process
        # fallback) path, which never conflicts.
        inserted = await execute(
            "INSERT INTO background_tasks "
            "(tenant_id, video_id, task_type, status, message, job_id, attempt, started_at) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, now()) "
            "ON CONFLICT (job_id) WHERE job_id IS NOT NULL DO NOTHING",
            tenant_id, video_id, task_type, status, message, job_id, attempt,
        )
        if required and not _write_landed(inserted):
            verified = await fetch_one(
                "SELECT id FROM background_tasks "
                "WHERE tenant_id = $1 AND video_id = $2 AND task_type = $3 "
                "AND (($4 IS NULL AND job_id IS NULL) OR job_id = $4) "
                "AND status = 'running' LIMIT 1",
                tenant_id, video_id, task_type, job_id,
            )
            if not verified:
                raise RuntimeError("Required task start insert did not persist")
    except Exception as exc:
        logger.warning(
            "db_persist_task failed (best-effort): video=%s stage=%s status=%s: %s",
            video_id, task_type, status, exc,
        )
        if required:
            raise
