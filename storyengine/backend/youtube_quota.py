"""YouTube Data API v3 daily quota guard (checklist §3.4, C33).

**Scope decision — GLOBAL, not per-tenant.** YouTube's 10,000-units/day quota
is billed against a Google Cloud PROJECT, not against an end-user's channel.
Every tenant's OAuth token in this app is minted from the SAME OAuth client
(one `GOOGLE_OAUTH_CLIENT_ID`/`GOOGLE_OAUTH_CLIENT_SECRET` env-var pair —
see youtube_publish.py, routes/youtube_sync.py, routes/google_auth.py: all
read the same two env vars, none read a per-tenant client id/secret), which
means every tenant's Data API calls draw from the ONE project's quota pool.
A per-tenant counter would under-count the real shared risk (tenant A could
exhaust the pool while tenant B's counter still reads "plenty left"). So the
counter below is keyed by day only, no tenant_id — it tracks the one number
that actually determines whether the next call gets a 403.

**Unit costs** — from Google's published YouTube Data API v3 quota-cost
table (https://developers.google.com/youtube/v3/determine_quota_cost),
cross-checked against youtube_data_api.py's header comment (already documents
channels.list/playlistItems.list/videos.list = 1 unit each, search.list =
100 — that comment predates this file and is reused here, not re-guessed):
  - videos.insert       1600   (the upload itself)
  - thumbnails.set        50   (custom thumbnail set right after upload)
  - videos.update         50   (unused today, listed for completeness)
  - search.list           100   (channel-id resolution fallback)
  - videos.list             1
  - channels.list            1
  - playlistItems.list       1
Note: YouTube Analytics API (`youtubeanalytics.googleapis.com`, used by
youtube_sync.py's per-video/day metrics) draws from a SEPARATE quota system,
not this 10,000/day Data-API pool — so Analytics report calls are
deliberately NOT counted here.

**Storage** — smallest correct: a dedicated one-row-per-day table
(migration 101), not a reuse of `generation_ledger` (migration 087).
generation_ledger is shaped for a different question ("what did THIS VIDEO
cost in dollars") — `video_id` is NOT NULL and the money column is a USD
`actual_cost`. Forcing a video-less, cross-tenant, non-dollar API-unit
counter through it would need nullable-video hacks and unit/dollar
confusion; a 3-column table is simpler and correct on its own terms.

**Reset semantics** — YouTube's quota resets at midnight PACIFIC TIME, not
UTC. The "day" key is computed in `America/Los_Angeles`, so a call made at
11pm PT and one at 1am PT the same UTC calendar day land in different
buckets (correctly, since Google would allow both), while calls either side
of PT midnight land in different buckets too (correctly refused/allowed).

**Fail-soft** — this is bookkeeping, not the source of truth (YouTube's own
403 always wins if we're wrong). Any DB error while reading/writing the
counter is logged and treated as "quota available" — a tracker outage must
never block real uploads.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from database import fetch_one, execute

logger = logging.getLogger(__name__)

_PACIFIC = ZoneInfo("America/Los_Angeles")

# Default ceiling leaves ~1,000 units of headroom under Google's real
# 10,000/day project limit (buffer for the daily sync's list calls,
# search.list fallbacks, and any manual API exploration) — configurable
# because a tenant on a project with a raised quota should be able to too.
DEFAULT_CEILING = 9000

# Per Google's published quota-cost table (see module docstring). Keys are
# the YouTube Data API v3 method names used as `operation` by callers.
UNIT_COSTS: dict[str, int] = {
    "videos.insert": 1600,
    "thumbnails.set": 50,
    "videos.update": 50,
    "search.list": 100,
    "videos.list": 1,
    "channels.list": 1,
    "playlistItems.list": 1,
}


def _ceiling() -> int:
    try:
        return int(os.getenv("YOUTUBE_DAILY_QUOTA_CEILING", DEFAULT_CEILING))
    except (TypeError, ValueError):
        return DEFAULT_CEILING


def _pt_today() -> str:
    """Today's date key in Pacific time — YYYY-MM-DD, matching YouTube's
    actual midnight-PT reset instead of UTC midnight."""
    return datetime.now(_PACIFIC).strftime("%Y-%m-%d")


def upload_cost(has_thumbnail: bool) -> int:
    """Real unit cost of one upload_video_to_youtube() call."""
    cost = UNIT_COSTS["videos.insert"]
    if has_thumbnail:
        cost += UNIT_COSTS["thumbnails.set"]
    return cost


async def get_quota_status() -> dict:
    """Today's (Pacific) usage vs. the configured ceiling.

    Fail-soft: a DB error is logged and reported as if 0 units were used
    today (i.e. "plenty of quota left") — this endpoint/check must never
    itself become the reason an upload is blocked.
    """
    ceiling = _ceiling()
    day = _pt_today()
    try:
        row = await fetch_one(
            "SELECT units_used FROM youtube_quota_usage WHERE day = $1::date", day
        )
        used = int(row["units_used"]) if row else 0
    except Exception as e:  # noqa: BLE001 — bookkeeping must never raise
        logger.warning("youtube_quota: status read failed, assuming 0 used: %s", e)
        used = 0
    return {
        "date_pt": day,
        "units_used": used,
        "ceiling": ceiling,
        "remaining": max(ceiling - used, 0),
    }


async def record_units(units: int, operation: str) -> None:
    """Add `units` to today's (Pacific) running total. Fail-soft: swallow
    and log — a failed write must never surface as an upload failure after
    the upload itself already succeeded."""
    if units <= 0:
        return
    day = _pt_today()
    try:
        await execute(
            """INSERT INTO youtube_quota_usage (day, units_used, updated_at)
               VALUES ($1::date, $2, now())
               ON CONFLICT (day) DO UPDATE SET
                 units_used = youtube_quota_usage.units_used + EXCLUDED.units_used,
                 updated_at = now()""",
            day, units,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("youtube_quota: failed to record %d units for %s: %s", units, operation, e)


async def check_quota_available(units_needed: int) -> tuple[bool, dict]:
    """Would spending `units_needed` more units today exceed the ceiling?

    Returns (ok, status). Fail-soft: if the status read itself errors,
    `get_quota_status()` already reports "0 used" so this naturally comes
    back ok=True — a tracker outage allows the call through rather than
    blocking real work over a bookkeeping failure.
    """
    status = await get_quota_status()
    ok = (status["units_used"] + units_needed) <= status["ceiling"]
    return ok, status


def quota_exceeded_message(status: dict) -> str:
    """Human-readable refusal, for callers that surface it as a card/error
    instead of letting YouTube's raw 403 leak through."""
    return (
        f"YouTube upload quota is exhausted for today "
        f"({status['units_used']}/{status['ceiling']} units used) — "
        f"resets at midnight Pacific time. Try again after the reset."
    )
