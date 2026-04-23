"""Shared task persistence helpers — used by both routes and worker.

Extracted from routes/pipeline.py to avoid circular imports when
worker.py needs to update background_tasks rows.
"""

import logging
from typing import Optional

from database import fetch_one, execute

logger = logging.getLogger(__name__)


async def db_persist_task(
    tenant_id: str,
    video_id: str,
    task_type: str,
    status: str,
    message: Optional[str] = None,
    error: Optional[str] = None,
    job_id: Optional[str] = None,
    attempt: int = 1,
) -> None:
    """Persist task state to the background_tasks table.

    - 'running': upserts (SELECT existing running row, UPDATE or INSERT)
    - 'pending': inserts a new row, skipping if a pending row with same job_id exists
    - 'completed'/'failed': updates all matching running/pending rows to terminal state

    All failures are swallowed — persistence is best-effort.
    """
    try:
        if status == "running":
            existing = await fetch_one(
                "SELECT id FROM background_tasks "
                "WHERE video_id = $1 AND status = 'running' LIMIT 1",
                video_id,
            )
            if existing:
                await execute(
                    "UPDATE background_tasks SET message = $1 WHERE id = $2",
                    message, existing["id"],
                )
            else:
                await execute(
                    "INSERT INTO background_tasks "
                    "(tenant_id, video_id, task_type, status, message, job_id, attempt, started_at) "
                    "VALUES ($1, $2, $3, 'running', $4, $5, $6, now())",
                    tenant_id, video_id, task_type, message, job_id, attempt,
                )
        elif status == "pending":
            existing = await fetch_one(
                "SELECT id FROM background_tasks WHERE job_id = $1 AND status = 'pending' LIMIT 1",
                job_id,
            )
            if not existing:
                await execute(
                    "INSERT INTO background_tasks "
                    "(tenant_id, video_id, task_type, status, message, job_id, attempt, started_at) "
                    "VALUES ($1, $2, $3, 'pending', $4, $5, $6, now())",
                    tenant_id, video_id, task_type, message, job_id, attempt,
                )
        elif status in ("completed", "failed"):
            await execute(
                "UPDATE background_tasks "
                "SET status = $1, message = $2, error_message = $3, completed_at = now() "
                "WHERE video_id = $4 AND status IN ('running', 'pending')",
                status, message, error, video_id,
            )
    except Exception as exc:
        logger.warning(
            "db_persist_task failed (best-effort): video=%s stage=%s status=%s: %s",
            video_id, task_type, status, exc,
        )
