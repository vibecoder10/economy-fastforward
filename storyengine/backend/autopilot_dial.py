"""Typed read accessor for the autopilot dial columns (checklist C50,
P4.2-a — migration 107 added these columns to ``autopilot_config``; this
module is the ONLY read surface for them so C51-C56 (the tenant autopilot
P4.2 builds on top) import one thing instead of five raw column reads
scattered across callers).

This chunk is READ-ONLY by design (see migration 107's header for the full
semantics). No writer lives here yet:
  - ``dial_level`` writes land in C52/C54.
  - ``weekly_spend_reset_at`` maintenance lands in C54.
  - kill-switch trip/re-enable writes land in whichever chunk builds the
    trip condition (budget breach / repeated failures) — not this one.

Kill switch vs. `enabled` — DISTINCT, do not conflate (repeated from the
migration header since this is the accessor callers will actually read):
``enabled`` is the human on/off switch (``POST /api/autopilot/toggle``).
The kill switch is an AUTOMATIC trip recorded by the system and requires an
EXPLICIT human re-enable (clearing ``kill_switch_tripped_at``) — tripping it
never mutates ``enabled``, and toggling ``enabled`` never clears it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from database import fetch_one

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
