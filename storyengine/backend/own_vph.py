"""Views-per-hour for the tenant's OWN videos (checklist §3.4, C33).

Competitor VPH has existed since the very first scraper
(skills/video-pipeline/competitor_scraper/scraper.py::calculate_vph, and its
StoryEngine-side sibling routes/niche.py::_calculate_vph, both already used
to rank `competitor_videos`) — but the tenant's own published videos never
got the same number, so "what should I make next" (competitor VPH) and "how
is my own channel doing" (raw view counts, no velocity) were never
comparable — docs/reports/2026-07-17-storyengine-agent-audit-findings.md
Sweep 3 finding #5: "VPH computed for competitors only, never for own
videos — scorecards compare apples to oranges."

This wraps `routes.niche._calculate_vph` (the same math, not a rewrite) —
reuse over duplication, per the checklist's own instruction. It is imported
lazily inside the function to avoid a module-load-order dependency between
`routes.niche` and this module's callers (channel_briefs.py, analytics.py,
analytics_by_style.py) — the same lazy-import discipline channel_briefs.py
already documents for its own circular-import avoidance.

Derived at READ TIME, not stored: every caller already has `views` (or
`view_count`) and a publish timestamp (`videos.upload_date` or
`channel_videos.published_at`) in hand from the query it already runs, so a
stored column would just be a second copy of numbers already present — the
"smallest correct" fix is a shared formula, not a new column + a backfill +
a sync-time write path to keep in sync.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

# Below this many elapsed hours, VPH is not reported (None) rather than a
# wildly extrapolated number from a near-zero denominator. One hour is well
# inside the "within 24h of publish" window the checklist expects VPH to be
# visible by, while still guarding the first few post-publish minutes where
# a handful of views would otherwise read as tens of thousands per hour.
MIN_HOURS_FOR_VPH = 1.0


def compute_own_vph(views: Optional[int], published_at) -> Optional[float]:
    """Views-per-hour for one of the tenant's own videos.

    `published_at` is whatever the caller's row has for "when did this go
    live" — a `datetime` (asyncpg returns TIMESTAMPTZ columns as tz-aware
    datetimes), an ISO string, or None.

    Returns None in the cases where a number would be a dishonest answer:
      - unpublished (`published_at` is None/empty): there IS no velocity yet.
      - published less than an hour ago, or a clock-skew timestamp in the
        future (hours_since < MIN_HOURS): dividing by a near-zero
        denominator doesn't just risk a literal divide-by-zero, it produces
        a wildly extrapolated, meaningless number (e.g. 500 views 90 seconds
        after publish reads as "20,000/hr") — worse than the unpublished
        case, because it LOOKS like a real answer. None until there's
        enough elapsed time for the rate to mean anything.
    A real, non-negative VPH is returned in every other case, rounded to 2
    decimals to match the competitor-side VPH's display precision.
    """
    if not published_at:
        return None
    from routes.niche import _calculate_vph  # lazy: avoid load-order coupling

    ts = published_at.isoformat() if isinstance(published_at, datetime) else str(published_at)
    vph, hours_since = _calculate_vph(int(views or 0), ts, datetime.now(timezone.utc))
    if hours_since < MIN_HOURS_FOR_VPH:
        return None
    return round(vph, 2)
