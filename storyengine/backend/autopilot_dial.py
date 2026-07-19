"""Typed read accessor + budget/kill-switch writers for the autopilot dial
columns (checklist C50, P4.2-a added the columns + read-only accessor; C54,
P4.2-e adds the FIRST writers on top of it — this module stays the ONE home
for the dial so C51-C56 import one thing instead of five raw column reads/
writes scattered across callers).

Kill switch vs. `enabled` — DISTINCT, do not conflate (repeated from the
migration header since this is the accessor callers will actually read):
``enabled`` is the human on/off switch (``POST /api/autopilot/toggle``).
The kill switch is an AUTOMATIC trip recorded by the system and requires an
EXPLICIT human re-enable (clearing ``kill_switch_tripped_at``) — tripping it
never mutates ``enabled``, and toggling ``enabled`` never clears it.

C54 (P4.2-e) — per-tenant weekly budget ceiling:
  - ``get_weekly_spend`` sums ``generation_ledger.actual_cost`` (NOT
    ``videos.total_cost``) since ``weekly_spend_reset_at``. Why the ledger
    and not ``total_cost``: ``total_cost`` (generation_ledger.py's
    recompute-by-SUM target) is a per-VIDEO CUMULATIVE lifetime rollup with
    no "since when" axis — it never resets, so a windowed "spend since X"
    query can't be built from it (summing it would just always answer
    "all-time spend across every video ever made", not "this week"). The
    ledger itself carries ``created_at`` per paid unit AND already has a
    ``(tenant_id, created_at)`` index built for exactly this tenant-spend-
    over-a-date-range query (migration 087's header names this use case
    directly).
  - The rolling window is maintained by an atomic upsert (see
    ``_ensure_reset_window``): NULL or >7-days-old rolls forward to now().
    The ``WHERE`` guard folded into ``ON CONFLICT ... DO UPDATE`` makes two
    concurrent callers race safely — only one performs the actual update
    (holding the row lock for the ``tenant_id`` unique key), the other's
    conflicting statement re-evaluates the guard once the first commits and
    finds it already rolled, so it becomes a no-op rather than a second
    roll-forward.
  - ``trip_kill_switch``/``clear_kill_switch`` are the FIRST kill-switch
    writers. Trip is idempotent — a second trip (e.g. two callers detecting
    the same breach in the same tick) never overwrites the FIRST recorded
    reason. Neither writer ever touches ``enabled``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from database import execute, fetch_one

logger = logging.getLogger(__name__)

DIAL_LEVELS = ("propose_only", "auto_draft", "full_auto")
_DEFAULT_DIAL_LEVEL = "propose_only"


@dataclass
class AutopilotDial:
    """The autopilot dial's current settings for one tenant. Every field
    defaults exactly to what a missing (or pre-migration-107) row means
    today: propose-only, no budget cap, no reset window, not tripped."""

    dial_level: str = _DEFAULT_DIAL_LEVEL
    weekly_budget_cap: Optional[float] = None
    weekly_spend_reset_at: Optional[datetime] = None
    kill_switch_tripped_at: Optional[datetime] = None
    kill_switch_reason: Optional[str] = None


async def get_autopilot_dial(tenant_id: str) -> AutopilotDial:
    """Fetch the dial settings for a tenant, defaulting sanely when the
    ``autopilot_config`` row doesn't exist yet (a tenant that has never
    touched autopilot settings) — same "no row = safe defaults" convention
    ``main.py::_get_autopilot_config`` and ``routes/autopilot.py`` already
    use for the pre-existing columns on this table."""
    row = await fetch_one(
        """SELECT dial_level, weekly_budget_cap, weekly_spend_reset_at,
                  kill_switch_tripped_at, kill_switch_reason
           FROM autopilot_config WHERE tenant_id = $1""",
        tenant_id,
    )
    if not row:
        return AutopilotDial()
    return AutopilotDial(
        dial_level=row.get("dial_level") or _DEFAULT_DIAL_LEVEL,
        weekly_budget_cap=(
            float(row["weekly_budget_cap"]) if row.get("weekly_budget_cap") is not None else None
        ),
        weekly_spend_reset_at=row.get("weekly_spend_reset_at"),
        kill_switch_tripped_at=row.get("kill_switch_tripped_at"),
        kill_switch_reason=row.get("kill_switch_reason"),
    )


def _rows_affected(command_status: object) -> int:
    """asyncpg's ``execute()`` returns a command-tag string like
    ``"UPDATE 1"`` or ``"INSERT 0 1"`` — the trailing integer is the row
    count. Used to tell "this call actually changed the row" apart from
    "the WHERE guard made it a no-op" for the upserts below."""
    try:
        return int(str(command_status).strip().split()[-1])
    except (ValueError, IndexError):
        return 0


async def _ensure_reset_window(tenant_id: str) -> None:
    """Atomically roll ``weekly_spend_reset_at`` forward to now() when it's
    NULL (no row yet, or a row that's never had a window) or more than 7
    days old. See the module docstring for why the ``WHERE`` guard folded
    into ``ON CONFLICT ... DO UPDATE`` is race-safe for concurrent callers."""
    await execute(
        """INSERT INTO autopilot_config (tenant_id, weekly_spend_reset_at)
           VALUES ($1, now())
           ON CONFLICT (tenant_id) DO UPDATE
           SET weekly_spend_reset_at = now()
           WHERE autopilot_config.weekly_spend_reset_at IS NULL
              OR autopilot_config.weekly_spend_reset_at < now() - interval '7 days'""",
        tenant_id,
    )


async def get_weekly_spend(tenant_id: str) -> float:
    """Real spend in the CURRENT weekly window: rolls the window forward
    first (idempotent no-op if it's already current), then sums
    ``generation_ledger.actual_cost`` for this tenant since whatever
    ``weekly_spend_reset_at`` is now. See the module docstring for why the
    ledger — not ``videos.total_cost`` — is the sum target."""
    await _ensure_reset_window(tenant_id)
    row = await fetch_one(
        """SELECT COALESCE(SUM(gl.actual_cost), 0) AS spent
           FROM generation_ledger gl
           JOIN autopilot_config ac ON ac.tenant_id = gl.tenant_id
           WHERE gl.tenant_id = $1 AND gl.created_at >= ac.weekly_spend_reset_at""",
        tenant_id,
    )
    return float(row["spent"]) if row else 0.0


async def check_weekly_budget(tenant_id: str) -> tuple[bool, float, Optional[float]]:
    """(ok, spent, cap). ``cap`` is None when the tenant hasn't set one —
    always ok in that case (today's behavior for every existing tenant,
    same "additive, opt-in, no ceiling until set" posture as migration
    103's ``videos.max_spend``). Breach is ``spent >= cap`` (exact-boundary
    inclusive — reaching the cap trips it, not just exceeding it)."""
    dial = await get_autopilot_dial(tenant_id)
    cap = dial.weekly_budget_cap
    spent = await get_weekly_spend(tenant_id)
    if cap is None:
        return True, spent, None
    return spent < cap, spent, cap


async def _notify_kill_switch_tripped(tenant_id: str, reason: str) -> None:
    """Drop one ``bot_activity`` row so a trip is LOUD, never a silent
    pause — same best-effort reuse of the existing activity-feed table as
    ``autopilot_proposals._notify_proposal_created`` (C52). Best-effort: a
    notify failure must never fail the trip itself."""
    try:
        await execute(
            """INSERT INTO bot_activity (tenant_id, bot_name, status, message)
               VALUES ($1, $2, $3, $4)""",
            tenant_id, "autopilot_kill_switch", "failed",
            f"Autopilot kill switch tripped: {reason}",
        )
    except Exception:
        logger.warning(
            "bot_activity notify failed for kill-switch trip (tenant=%s)",
            tenant_id[:8], exc_info=True,
        )


async def trip_kill_switch(tenant_id: str, reason: str) -> bool:
    """Stamp ``kill_switch_tripped_at``/``kill_switch_reason`` — ONLY if not
    already tripped, so a second trip in the same tick (loop-level check +
    autopilot_launch.py's own defense-in-depth check both firing) can't
    clobber the FIRST recorded reason. Never touches ``enabled``. Returns
    True iff THIS call actually tripped it (used to gate the notify so a
    no-op second trip doesn't send a duplicate bot_activity row)."""
    status = await execute(
        """INSERT INTO autopilot_config (tenant_id, kill_switch_tripped_at, kill_switch_reason)
           VALUES ($1, now(), $2)
           ON CONFLICT (tenant_id) DO UPDATE
           SET kill_switch_tripped_at = now(), kill_switch_reason = $2
           WHERE autopilot_config.kill_switch_tripped_at IS NULL""",
        tenant_id, reason,
    )
    tripped_now = _rows_affected(status) > 0
    if tripped_now:
        await _notify_kill_switch_tripped(tenant_id, reason)
    return tripped_now


async def clear_kill_switch(tenant_id: str) -> None:
    """The ONLY clearer — called exclusively from the explicit human route
    (``POST /api/autopilot/kill-switch/reset`` and its MCP mirror). Clears
    both columns unconditionally; never called automatically."""
    await execute(
        """INSERT INTO autopilot_config (tenant_id, kill_switch_tripped_at, kill_switch_reason)
           VALUES ($1, NULL, NULL)
           ON CONFLICT (tenant_id) DO UPDATE
           SET kill_switch_tripped_at = NULL, kill_switch_reason = NULL""",
        tenant_id,
    )
