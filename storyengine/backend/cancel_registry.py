"""Cooperative cancellation for pipeline stages.

A Stop request must reach a generation loop that may be running in THIS
process (BackgroundTasks) or in the arq worker process. Two layers:

- In-memory flag (fast path, same process). TTL'd so a stale flag can never
  block future runs after a crash.
- background_tasks row with status='cancelled' AND completed_at IS NULL
  (cross-process path — the arq worker sees it on its next between-items
  check). When the cancelled run finishes winding down, the terminal task
  write sets completed_at, consuming the request. A new stage run clears any
  leftover un-consumed request first, so Stop never bleeds into a resume.

Semantics everywhere: finish the in-flight item, keep all completed (paid)
work, stop starting new items. Clicking the stage again resumes — existing
resume logic only fills what's missing.
"""

import time

from database import execute, fetch_one

_flags: dict[tuple[str, str], float] = {}
_FLAG_TTL_SECONDS = 4 * 3600


def _key(tenant_id, video_id) -> tuple[str, str]:
    return (str(tenant_id), str(video_id))


def request_local(tenant_id, video_id) -> None:
    """Set the in-memory cancel flag (same-process fast path)."""
    _flags[_key(tenant_id, video_id)] = time.time()


def is_requested_local(tenant_id, video_id) -> bool:
    ts = _flags.get(_key(tenant_id, video_id))
    return bool(ts and time.time() - ts < _FLAG_TTL_SECONDS)


def clear_local(tenant_id, video_id) -> None:
    _flags.pop(_key(tenant_id, video_id), None)


async def request_cancel(tenant_id, video_id, set_local: bool = True) -> bool:
    """Record a cancel request. Returns True if a running background_tasks row
    existed to mark. set_local=False skips the in-memory flag (used when the
    caller can't confirm an in-process task is live — avoids planting a stale
    cancel for the next run)."""
    if set_local:
        request_local(tenant_id, video_id)
    result = await execute(
        "UPDATE background_tasks SET status = 'cancelled', "
        "message = 'Stop requested — finishing the current item' "
        "WHERE video_id = $1 AND tenant_id = $2 AND status = 'running'",
        str(video_id), str(tenant_id),
    )
    try:
        return int(result.split()[-1]) > 0
    except Exception:
        return False


async def is_cancel_requested(tenant_id, video_id) -> bool:
    """Checked by generation loops between paid items."""
    if is_requested_local(tenant_id, video_id):
        return True
    row = await fetch_one(
        "SELECT 1 FROM background_tasks "
        "WHERE video_id = $1 AND tenant_id = $2 "
        "AND status = 'cancelled' AND completed_at IS NULL LIMIT 1",
        str(video_id), str(tenant_id),
    )
    return bool(row)


async def reset_for_new_run(tenant_id, video_id) -> None:
    """Consume any leftover cancel request before a fresh stage run starts."""
    clear_local(tenant_id, video_id)
    await execute(
        "UPDATE background_tasks SET completed_at = now() "
        "WHERE video_id = $1 AND tenant_id = $2 "
        "AND status = 'cancelled' AND completed_at IS NULL",
        str(video_id), str(tenant_id),
    )
