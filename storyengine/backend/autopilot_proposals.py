"""Autopilot candidate proposals store (checklist C51, P4.2-b).

Backs propose_only dial-level dry runs: ``autopilot_launch.auto_launch_
best_candidate`` scores ``competitor_videos`` and, in propose_only mode,
records ONE row here per scored-and-selected candidate instead of creating a
video or calling ``routes.autopilot.launch_candidate`` — see that module's
docstring for the full behavior contract. Writing a proposal never causes
spend; only a human (C52's UI/chat surface) accepting one does that, by
calling the EXISTING ``launch_candidate`` path.

Row lifecycle: 'proposed' (this chunk's only writer sets this) ->
'accepted' | 'dismissed' (a human decision, C52's job) -> a candidate never
gets re-proposed while its proposal is still 'proposed'
(``has_active_proposal`` is the dedup guard ``auto_launch_best_candidate``
consults before ever writing a new row for the same competitor video).
'expired' is reserved for a future housekeeping sweep — no writer sets it
yet.

C52 (P4.2-c) adds the read/decide surface on top: ``list_proposals``/
``get_proposal`` (reads), ``mark_decided`` (the ONLY writer of the
'proposed' -> 'accepted'/'dismissed' transition — an atomic
``WHERE status = 'proposed'`` UPDATE so two concurrent decisions on the
same row can't both "win"; the caller in ``routes/autopilot.py`` is
responsible for calling the EXISTING ``launch_candidate`` path itself
before ever calling ``mark_decided(status="accepted", ...)`` — this module
never launches anything, it only records the decision). ``create_proposal``
also drops one ``bot_activity`` row per proposal (best-effort, C52 item 3)
so a new propose_only pick shows up wherever the existing activity feed
already surfaces background events — no new notification table.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from database import execute, fetch_all, fetch_one

logger = logging.getLogger(__name__)

STATUSES = {"proposed", "accepted", "dismissed", "expired"}

_SELECT_COLS = (
    "id, tenant_id, candidate_id, video_title, confidence_score, "
    "confidence_breakdown, status, decided_at, decided_by, video_id, created_at"
)


def _decode_row(row: Optional[dict]) -> Optional[dict]:
    if not row:
        return None
    row = dict(row)
    breakdown = row.get("confidence_breakdown")
    if isinstance(breakdown, str) and breakdown.strip():
        try:
            row["confidence_breakdown"] = json.loads(breakdown)
        except (json.JSONDecodeError, ValueError):
            row["confidence_breakdown"] = None
    return row


async def has_active_proposal(tenant_id: str, candidate_id: str) -> bool:
    """True if this competitor_videos row already has an undecided
    ('proposed') row for this tenant — the dedup guard
    ``autopilot_launch.auto_launch_best_candidate`` consults before ever
    writing a new proposal for the same candidate (invariant: never
    re-propose the same candidate while an undecided proposal exists)."""
    row = await fetch_one(
        "SELECT 1 AS x FROM autopilot_proposals "
        "WHERE tenant_id = $1 AND candidate_id = $2 AND status = 'proposed'",
        tenant_id, candidate_id,
    )
    return row is not None


async def create_proposal(
    tenant_id: str,
    *,
    candidate_id: str,
    video_title: str,
    confidence_score: float,
    confidence_breakdown: Optional[dict] = None,
) -> dict:
    """Record a propose_only dry-run pick. Never touches ``videos`` or
    ``competitor_videos`` — structurally the only thing this function can
    do is INSERT into ``autopilot_proposals``."""
    row = await fetch_one(
        f"""INSERT INTO autopilot_proposals
                (tenant_id, candidate_id, video_title, confidence_score, confidence_breakdown)
            VALUES ($1, $2, $3, $4, $5::jsonb)
            RETURNING {_SELECT_COLS}""",
        tenant_id, candidate_id, video_title, confidence_score,
        json.dumps(confidence_breakdown) if isinstance(confidence_breakdown, dict) else None,
    )
    decoded = _decode_row(row)
    if decoded:
        await _notify_proposal_created(tenant_id, decoded)
    return decoded


async def _notify_proposal_created(tenant_id: str, proposal: dict) -> None:
    """Drop one ``bot_activity`` row so this proposal shows up wherever the
    existing activity feed (GET /api/activity, the dashboard's running-bots
    widget) already surfaces background events — reusing that table is the
    entire "notify" mechanism for C52, no new infra. video_id is NULL (no
    video exists yet for a proposal) — bot_activity.video_id is nullable,
    same as the existing settings.py api_key_audit rows. Best-effort: a
    notify failure must never fail proposal creation."""
    try:
        await execute(
            """INSERT INTO bot_activity (tenant_id, bot_name, status, message)
               VALUES ($1, $2, $3, $4)""",
            tenant_id, "autopilot_proposal", "completed",
            f"New candidate proposed: {proposal.get('video_title', 'Untitled')} "
            f"(confidence {float(proposal.get('confidence_score') or 0):.0f})",
        )
    except Exception:
        logger.warning("bot_activity notify failed for proposal %s (best-effort)",
                        proposal.get("id"), exc_info=True)


async def list_proposals(tenant_id: str, *, status: Optional[str] = None, limit: int = 50) -> list[dict]:
    """Proposals for a tenant, newest first. ``status=None`` returns every
    status; otherwise filters to that exact status (default caller passes
    'proposed' — see routes.autopilot.list_autopilot_proposals)."""
    if status:
        rows = await fetch_all(
            f"""SELECT {_SELECT_COLS} FROM autopilot_proposals
                WHERE tenant_id = $1 AND status = $2
                ORDER BY created_at DESC LIMIT $3""",
            tenant_id, status, limit,
        )
    else:
        rows = await fetch_all(
            f"""SELECT {_SELECT_COLS} FROM autopilot_proposals
                WHERE tenant_id = $1
                ORDER BY created_at DESC LIMIT $2""",
            tenant_id, limit,
        )
    return [_decode_row(r) for r in rows]


async def count_pending(tenant_id: str) -> int:
    """Count of undecided ('proposed') rows — backs the summary badge."""
    row = await fetch_one(
        "SELECT COUNT(*) AS c FROM autopilot_proposals WHERE tenant_id = $1 AND status = 'proposed'",
        tenant_id,
    )
    return int(row["c"]) if row else 0


async def get_proposal(tenant_id: str, proposal_id: str) -> Optional[dict]:
    """Fetch one proposal, tenant-scoped. None if it doesn't exist or
    belongs to a different tenant (never distinguishes the two — same
    404-either-way posture every other tenant-scoped lookup in this repo
    takes)."""
    row = await fetch_one(
        f"SELECT {_SELECT_COLS} FROM autopilot_proposals WHERE tenant_id = $1 AND id = $2",
        tenant_id, proposal_id,
    )
    return _decode_row(row)


async def mark_decided(
    tenant_id: str,
    proposal_id: str,
    *,
    status: str,
    decided_by: str,
    video_id: Optional[str] = None,
) -> Optional[dict]:
    """Atomically transition a 'proposed' row to 'accepted' or 'dismissed'.
    The ``WHERE status = 'proposed'`` guard makes this safe against a
    concurrent double-decide — two requests racing to decide the same row
    can't both succeed; only the first writer's UPDATE matches a row and the
    loser gets None back (the caller treats that as "already decided").
    This function NEVER launches anything — the caller (routes.autopilot's
    accept_proposal) is responsible for calling launch_candidate itself
    BEFORE calling this with status='accepted', so a failed launch never
    reaches this write and the proposal stays 'proposed'."""
    row = await fetch_one(
        f"""UPDATE autopilot_proposals
            SET status = $1, decided_at = now(), decided_by = $2, video_id = $3
            WHERE tenant_id = $4 AND id = $5 AND status = 'proposed'
            RETURNING {_SELECT_COLS}""",
        status, decided_by, video_id, tenant_id, proposal_id,
    )
    return _decode_row(row)
