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
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from database import fetch_one

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
    return _decode_row(row)
