"""Aggregate performance by creative CHOICE — style preset, render look, script
voice, dominant clip model (checklist §3.1/C30, the preset-performance loop
that's the moat: "which visual styles / models / presets actually earn views
on this channel").

One shared implementation, TWO callers:
  - routes/analytics.py::get_style_performance_endpoint (GET /api/analytics/by-style)
  - channel_briefs.py::_style_performance_brief (the copilot's channel_data tool,
    C15d pattern) — same numbers the UI panel shows (C31 wires the panel + the
    producer's citations), so the chat can never disagree with the dashboard.

Linkage decision (investigated for C30, see SYSTEM_STATE.md §C30): this reads
`videos` directly (views/ctr/avg_retention/last_analytics_sync), NEVER joins
`channel_videos`. `channel_videos` is the broader "everything on the YouTube
channel" mirror and a video published via StoryEngine's own upload flow does
NOT get a `channel_videos` row until the next `/api/youtube/sync` walk (capped
at 200 videos, requires channel-wide OAuth) — so requiring that join would
silently drop videos published since the last sync. `videos`' own performance
columns are written by that SAME sync job one step later
(youtube_sync.py::_writeback_matched_videos), so they're the same numbers,
available sooner and for every video unconditionally. This mirrors the
existing precedent in routes/analytics.py::get_framework_performance and
channel_briefs.py::_own_performance_brief, both of which already read
`videos` directly for the same reason.

Fail-soft per dimension: a broken/erroring query for one dimension (bad data,
transient DB hiccup) returns [] for THAT dimension only — the other three
still come back, and the endpoint never 500s just because one GROUP BY choked.

Honest NULL handling: `video_count` is every video with that choice set,
`synced_count` is the subset with real synced YouTube analytics
(`last_analytics_sync IS NOT NULL`) — the same flag `_own_performance_brief`
already uses as "has real data". Averages (`avg_ctr`, `avg_retention`) are
computed ONLY over the synced subset (SQL FILTER), so an unpublished or
not-yet-synced video is counted in `video_count` but never drags an average
toward zero pretending to be a real data point. `total_spend` is a real
ledger join (SUM(actual_cost) per video), never an estimate.
"""

from __future__ import annotations

import logging

from database import fetch_all

logger = logging.getLogger(__name__)

# Hide single-video "groups" — same anti-noise convention as
# routes/analytics.py::get_framework_performance's HAVING COUNT(*) >= 2.
MIN_SAMPLE = 2

# Column dimensions read straight off `videos`. Not user/caller-supplied —
# always one of these three literals — so building the column name into the
# SQL string below carries no injection risk.
_COLUMN_DIMENSIONS = {
    "by_style_preset": "style_preset_id",
    "by_render_style": "render_style",
    "by_script_profile": "script_profile",
}


def _row(dimension: str, r: dict) -> dict:
    ctr = r.get("avg_ctr")
    ret = r.get("avg_retention")
    spend = r.get("total_spend")
    return {
        "dimension": dimension,
        "choice": r["choice"],
        "video_count": int(r.get("video_count") or 0),
        "synced_count": int(r.get("synced_count") or 0),
        "avg_ctr": float(ctr) if ctr is not None else None,
        "avg_retention": float(ret) if ret is not None else None,
        "total_views": int(r.get("total_views") or 0),
        "total_spend": float(spend) if spend is not None else 0.0,
    }


async def _aggregate_column(tenant_id: str, dimension: str, column: str) -> list[dict]:
    try:
        rows = await fetch_all(
            f"""WITH spend AS (
                  SELECT video_id, SUM(actual_cost) AS spend
                  FROM generation_ledger WHERE tenant_id = $1 GROUP BY video_id
                )
                SELECT
                  v.{column} AS choice,
                  COUNT(*)::int AS video_count,
                  COUNT(*) FILTER (WHERE v.last_analytics_sync IS NOT NULL)::int AS synced_count,
                  ROUND(AVG(v.ctr) FILTER (WHERE v.last_analytics_sync IS NOT NULL)::numeric, 2) AS avg_ctr,
                  ROUND(AVG(v.avg_retention) FILTER (WHERE v.last_analytics_sync IS NOT NULL)::numeric, 2) AS avg_retention,
                  COALESCE(SUM(v.views), 0)::bigint AS total_views,
                  COALESCE(SUM(s.spend), 0)::numeric AS total_spend
                FROM videos v
                LEFT JOIN spend s ON s.video_id = v.id
                WHERE v.tenant_id = $1 AND v.deleted_at IS NULL
                  AND v.{column} IS NOT NULL AND v.{column} != ''
                GROUP BY v.{column}
                ORDER BY avg_ctr DESC NULLS LAST""",
            tenant_id,
        ) or []
    except Exception as e:  # noqa: BLE001 — one broken dimension must not sink the other three
        logger.warning("analytics_by_style: %s aggregation failed: %s", dimension, e)
        return []
    return [_row(dimension, r) for r in rows]


async def _aggregate_clip_model(tenant_id: str) -> list[dict]:
    """Groups by each video's DOMINANT clip model — the model that ran the most
    clips for that video (generation_ledger stage='clip', model=effective_model_id
    per pipeline_executor.py's clip loop). A mixed-routing video (some scenes on
    one model, some on another) is attributed to whichever model ran more of its
    clips, so its performance is counted exactly once, never split or double-
    counted across model buckets."""
    try:
        rows = await fetch_all(
            """WITH per_video_model AS (
                  SELECT video_id, model, COUNT(*) AS n
                  FROM generation_ledger
                  WHERE tenant_id = $1 AND stage = 'clip' AND model IS NOT NULL
                  GROUP BY video_id, model
                ),
                dominant AS (
                  SELECT video_id, model,
                         ROW_NUMBER() OVER (PARTITION BY video_id ORDER BY n DESC, model ASC) AS rn
                  FROM per_video_model
                ),
                spend AS (
                  SELECT video_id, SUM(actual_cost) AS spend
                  FROM generation_ledger WHERE tenant_id = $1 GROUP BY video_id
                )
                SELECT
                  d.model AS choice,
                  COUNT(*)::int AS video_count,
                  COUNT(*) FILTER (WHERE v.last_analytics_sync IS NOT NULL)::int AS synced_count,
                  ROUND(AVG(v.ctr) FILTER (WHERE v.last_analytics_sync IS NOT NULL)::numeric, 2) AS avg_ctr,
                  ROUND(AVG(v.avg_retention) FILTER (WHERE v.last_analytics_sync IS NOT NULL)::numeric, 2) AS avg_retention,
                  COALESCE(SUM(v.views), 0)::bigint AS total_views,
                  COALESCE(SUM(s.spend), 0)::numeric AS total_spend
                FROM videos v
                JOIN dominant d ON d.video_id = v.id AND d.rn = 1
                LEFT JOIN spend s ON s.video_id = v.id
                WHERE v.tenant_id = $1 AND v.deleted_at IS NULL
                GROUP BY d.model
                ORDER BY avg_ctr DESC NULLS LAST""",
            tenant_id,
        ) or []
    except Exception as e:  # noqa: BLE001
        logger.warning("analytics_by_style: by_clip_model aggregation failed: %s", e)
        return []
    return [_row("by_clip_model", r) for r in rows]


async def get_style_performance(tenant_id: str) -> dict:
    """The one aggregation both the endpoint and the copilot tool read.
    Always returns all four keys (possibly with empty lists) — never raises."""
    out: dict = {}
    for key, column in _COLUMN_DIMENSIONS.items():
        out[key] = await _aggregate_column(tenant_id, key, column)
    out["by_clip_model"] = await _aggregate_clip_model(tenant_id)
    return out
