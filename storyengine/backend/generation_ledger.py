"""generation_ledger: single source of truth for actual paid-generation spend.

Checklist §0.3 (tasks/storyengine-wiring-fix-checklist.md, C07/P0.3a): the
cost counter was wrong — price estimates were duplicated across 3 places
(actions.py, next-action.ts, this module's callers) and `videos.total_cost`
was never rolled up from real spend; it just sat at its DEFAULT 0 forever
(confirmed live: no INSERT/UPDATE anywhere in the codebase ever wrote a
non-zero value into it before this module existed).

This is deliberately the ONLY write path into `videos.total_cost`. Every
paid-generation call site (clips first — C07; images/voice/thumbnail/sound
in C08) calls `record_ledger_entry()` once per completed unit of spend. The
row is the receipt; `total_cost` is always a straight recompute of
`SUM(generation_ledger.actual_cost)` for that video — never an incremental
`+=`, so a retry (which does NOT re-insert a completed clip's row, since
retries only touch assets that still lack `video_clip_url`) can't double-bill,
and a re-run of this function for a video that already has ledger rows just
recomputes the same-or-larger true sum.

Pre-existing `stage_transitions.cost` and `bot_activity.cost` columns are
NOT touched by this module and are NOT deprecated by it — they're still
written (always with cost=0 in the coordinator/orchestrator, and via
`PipelineExecutor._log_activity(..., cost=cost)` in the clip/other bots,
which passes the SAME resolved cost as an informational activity-feed
number). Those columns feed `/api/activity` and `/api/dashboard` "spend"
tiles today; generation_ledger doesn't replace that read path in C07 — it's
noted here as a known follow-up (see report) rather than silently
double-counted or torn out.

FAIL-SOFT BY DESIGN: this function must never raise. A clip (or, from C08
on, an image/voice/thumbnail/sound asset) that finished generating has
already cost real money — losing its ledger row is a bookkeeping miss;
failing the caller and losing the finished asset would be a disaster. Every
call site can therefore `await record_ledger_entry(...)` unguarded.
"""
from typing import Optional

from database import execute


async def record_ledger_entry(
    tenant_id: str,
    video_id: str,
    stage: str,
    model: Optional[str],
    units: float,
    unit_cost: float,
    actual_cost: float,
    kie_task_id: Optional[str] = None,
) -> None:
    """Write one generation_ledger row, then recompute videos.total_cost as
    SUM(actual_cost) over every ledger row for this video.

    Recompute-not-increment is the whole point: it makes this function safe
    to call an unbounded number of times per video (one per clip/image/etc.)
    without ever double-counting, and self-healing if a row is ever added or
    corrected out of band.
    """
    try:
        await execute(
            """INSERT INTO generation_ledger
               (tenant_id, video_id, stage, model, units, unit_cost, actual_cost, kie_task_id)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
            tenant_id, video_id, stage, model, units, unit_cost, actual_cost, kie_task_id,
        )
        await execute(
            """UPDATE videos SET total_cost = (
                   SELECT COALESCE(SUM(actual_cost), 0) FROM generation_ledger
                   WHERE video_id = $1
               ) WHERE id = $1""",
            video_id,
        )
    except Exception as e:
        # Never propagate — see module docstring. The caller's paid-generation
        # result must stand even when this bookkeeping step fails.
        print(f"[generation_ledger] write/rollup failed (video={video_id} "
              f"stage={stage} model={model}): {type(e).__name__}: {str(e)[:200]}",
              flush=True)
