"""Early-warning launch classifier (checklist follow-up queue C58 — the
last P4.2 scout gap never chunked into C50-C56).

SaaS-side port of the CONCEPT in skills/video-pipeline/autopilot/monitoring/
early_warning.py (legacy `EarlyWarning.classify()` — fixed absolute CTR%
bands like "CTR < 2.5% = CRITICAL"). That legacy classifier is a fine
CONCEPT (tiered bands from a CTR read) but its thresholds are hardcoded
percentages that mean something different on every channel. This port
keeps the shape (a small number of tiers, evidence-backed, cheap to run)
but replaces the absolute thresholds with the SAME data-derived, per-
channel, evidence-attached law channel_patterns.py (C46e/C56) already
established: a video's early trajectory is only ever judged against ITS
OWN channel's history, never a hardcoded universal number.

Design (read-only signal, no auto-action — the classification here NEVER
trips the kill switch, never pauses anything, never touches spend; it
feeds human judgment + C56's flywheel, same as any other channel_patterns
evidence):

  - Metric: ctr_48h, the write-once snapshot routes/youtube_sync.py's
    `_calculate_snapshots()` already locks for EVERY video at the exact
    same 48-hours-post-publish milestone (see that function). Because
    every video's ctr_48h is captured at the identical maturity point,
    comparing one video's ctr_48h against the DISTRIBUTION of other
    videos' ctr_48h is maturity-matched BY CONSTRUCTION — not a same-day
    CTR mashing a brand-new video against a channel veteran's lifetime
    average (the honesty requirement design constraint 2 calls out).
    ctr_48h (not the raw current `ctr`/`impressions` a sync also writes)
    is deliberately used as the sole signal so no separate "is this really
    comparable" heuristic is needed.

  - Channel norm: the median of this SAME tenant's OTHER videos' ctr_48h
    values (channel_patterns.score_outlier_patterns' own median-based
    approach, reused at video granularity here too) — never a competitor
    number, never hardcoded.

  - Min cohort: channel_patterns.MIN_COHORT (5) — the SAME "need at least
    this many data points to trust a median" bar C56 already established.
    Fewer than that -> None (no classification). "Too little history"
    self-heals: the caller leaves early_signal_at unstamped in that case,
    so the SAME video is retried on a later sync once the channel has
    grown enough sibling launches to classify honestly, rather than
    silently guessing or giving up on it forever (checklist requirement:
    "never guess without data").

  - Bands: reuses channel_patterns.OUTLIER_THRESHOLD_PCT (30%) directly as
    the "underperforming" cutoff — this channel's OWN existing definition
    of "far enough from the median to call it an outlier", not a new
    invented number. "watch" is half that (15%) as an earlier heads-up
    band. Anything at or above -15% (including videos beating the median)
    is "ok" — this is a WARNING system, not a scorecard, so there is no
    separate "doing great" tier; "ok" covers "meeting or beating the
    channel norm".

  - "Young": a video is classified EXACTLY ONCE, the first sync where its
    ctr_48h is available (present in the DB) AND it hasn't been classified
    yet (early_signal_at IS NULL). Because ctr_48h is itself a write-once
    48h-milestone snapshot, this window is self-bounding: it can only ever
    open once per video (when ctr_48h first lands, whether that's THIS
    sync or, for a video whose ctr_48h was already set before this
    feature shipped, the first sync run with this code deployed — a
    natural backfill, no special-cased catch-up code needed) and it closes
    forever the moment classification succeeds (early_signal_at gets
    stamped). "Mature" videos (already classified) are never touched
    again by routes/youtube_sync.py's caller — see that module for the
    exact gating condition.

Evidence-jsonb discipline matches channel_patterns.py's evidence shape:
the stored evidence always carries the raw numbers (this video's ctr_48h,
the channel median), N (cohort_size), and the exact thresholds applied —
so a human or a future consumer can see precisely why a level was chosen,
without re-deriving it.
"""
from __future__ import annotations

import json
import logging
import statistics
from datetime import datetime, timezone
from typing import Optional

from database import execute, fetch_all
from channel_patterns import MIN_COHORT, OUTLIER_THRESHOLD_PCT

logger = logging.getLogger(__name__)

LEVELS = {"ok", "watch", "underperforming"}

# "watch" = half the channel's own outlier bar; "underperforming" = the
# SAME bar channel_patterns.py already uses to call something a real
# outlier. Reused directly — not a parallel number invented for this
# classifier.
WATCH_THRESHOLD_PCT = OUTLIER_THRESHOLD_PCT / 2.0          # 15.0
UNDERPERFORMING_THRESHOLD_PCT = OUTLIER_THRESHOLD_PCT       # 30.0


def classify_early_signal(
    video_ctr_48h: Optional[float],
    channel_ctr_48h_values: list[float],
    *,
    min_cohort: int = MIN_COHORT,
) -> Optional[dict]:
    """Pure: classify one video's ctr_48h against the channel's own
    ctr_48h distribution (every value already maturity-matched at the
    identical 48h milestone — see module docstring). Never raises.

    Returns None (never guesses) when ``video_ctr_48h`` isn't available yet,
    or fewer than ``min_cohort`` comparable values exist to trust a median.

    Otherwise returns ``{"level": "ok"|"watch"|"underperforming",
    "evidence": {...}}`` with the raw numbers, N, and thresholds applied.
    """
    if video_ctr_48h is None:
        return None
    values = [float(v) for v in (channel_ctr_48h_values or []) if v is not None]
    if len(values) < min_cohort:
        return None
    median = statistics.median(values)
    if median <= 0:
        return None

    delta_pct = ((video_ctr_48h - median) / median) * 100.0
    if delta_pct <= -UNDERPERFORMING_THRESHOLD_PCT:
        level = "underperforming"
    elif delta_pct <= -WATCH_THRESHOLD_PCT:
        level = "watch"
    else:
        level = "ok"

    return {
        "level": level,
        "evidence": {
            "metric": "ctr_48h",
            "maturity": "48h",
            "video_ctr_48h": round(video_ctr_48h, 3),
            "channel_median_ctr_48h": round(median, 3),
            "delta_pct": round(delta_pct, 1),
            "cohort_size": len(values),
            "watch_threshold_pct": WATCH_THRESHOLD_PCT,
            "underperforming_threshold_pct": UNDERPERFORMING_THRESHOLD_PCT,
        },
    }


async def _channel_ctr48_history(tenant_id: str) -> list[dict]:
    """This tenant's videos with a ctr_48h already locked — the channel's
    own historical norm at the exact maturity milestone this classifier
    compares against. Raw rows (id + ctr_48h) so the caller can exclude the
    video being classified from its own comparison set."""
    rows = await fetch_all(
        "SELECT id, ctr_48h FROM videos "
        "WHERE tenant_id = $1 AND ctr_48h IS NOT NULL AND deleted_at IS NULL",
        tenant_id,
    )
    return list(rows or [])


async def _notify_underperforming(tenant_id: str, internal_video_id: str, result: dict) -> None:
    """Best-effort ``bot_activity`` row — ONLY for the underperforming
    band (design constraint 1: surfaces once, not on every sync), and this
    only ever runs once per video since ``early_signal_at`` is write-once.
    Mirrors ``channel_patterns._notify_launch_pattern_proposed`` (C52's
    notify precedent, reused rather than a new mechanism). Never raises —
    a notify failure must never break the classification write it reports
    on."""
    ev = result.get("evidence") or {}
    try:
        await execute(
            """INSERT INTO bot_activity (tenant_id, bot_name, video_id, status, message)
               VALUES ($1, $2, $3, $4, $5)""",
            tenant_id, "early_warning", internal_video_id, "completed",
            (
                f"Early signal: underperforming — ctr_48h {ev.get('video_ctr_48h')}% vs "
                f"channel median {ev.get('channel_median_ctr_48h')}% "
                f"(n={ev.get('cohort_size')}, {ev.get('delta_pct')}% delta)."
            ),
        )
    except Exception:
        logger.warning(
            "early_warning: bot_activity notify failed for tenant=%s video=%s (best-effort)",
            tenant_id, internal_video_id, exc_info=True,
        )


async def run_early_signal_classification(tenant_id: str, videos: list[dict]) -> dict:
    """Called by ``routes/youtube_sync.py::_writeback_matched_videos`` for
    every video that is "young" per this feature's definition this sync
    (ctr_48h available, early_signal_at still NULL — see that caller for
    the exact gating condition and the module docstring above for why that
    window is self-bounding).

    ``videos``: ``[{"internal_video_id": <videos.id>, "ctr_48h": <float>},
    ...]``. For each, fetches this tenant's OTHER ctr_48h history once
    (shared across the whole batch — a channel's first sync after this
    feature ships can have several already-matured videos to classify at
    once) and classifies independently.

    Persists ``early_signal``/``early_signal_evidence``/``early_signal_at``
    ONLY when ``classify_early_signal`` returns a result. When it returns
    None because the channel's cohort is too thin, ``early_signal_at`` is
    deliberately left untouched so the SAME video is retried on a later
    sync (see module docstring — "too little history" self-heals). Never
    raises — a scoring/DB hiccup here must not break the analytics sync
    that calls it."""
    videos = [v for v in (videos or []) if isinstance(v, dict) and v.get("internal_video_id")]
    if not videos:
        return {"classified": 0}

    try:
        history = await _channel_ctr48_history(tenant_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("early_warning: history fetch failed for tenant=%s: %s", tenant_id, e)
        return {"classified": 0, "error": str(e)}

    classified = 0
    for v in videos:
        internal_id = str(v["internal_video_id"])
        raw_ctr = v.get("ctr_48h")
        others = [
            float(r["ctr_48h"]) for r in history
            if str(r.get("id")) != internal_id and r.get("ctr_48h") is not None
        ]
        try:
            video_ctr = float(raw_ctr) if raw_ctr is not None else None
            result = classify_early_signal(video_ctr, others)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "early_warning: classification failed for tenant=%s video=%s: %s",
                tenant_id, internal_id, e,
            )
            continue
        if result is None:
            continue  # too-thin cohort (or no ctr_48h yet) — retry on a later sync

        try:
            await execute(
                """UPDATE videos SET early_signal = $1, early_signal_evidence = $2::jsonb,
                          early_signal_at = $3
                   WHERE id = $4 AND tenant_id = $5""",
                result["level"], json.dumps(result["evidence"]),
                datetime.now(timezone.utc), internal_id, tenant_id,
            )
            classified += 1
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "early_warning: write failed for tenant=%s video=%s: %s",
                tenant_id, internal_id, e,
            )
            continue

        if result["level"] == "underperforming":
            await _notify_underperforming(tenant_id, internal_id, result)

    return {"classified": classified}
