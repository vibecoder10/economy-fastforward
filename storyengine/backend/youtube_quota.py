"""Fail-soft tracking for YouTube's project-wide daily quota buckets.

All tenants use the same Google Cloud project, so these counters are global.
YouTube resets them at midnight Pacific time. The current API separates
``videos.insert`` and ``search.list`` into daily call buckets while ordinary
Data API methods continue to consume the general units bucket.

The database is bookkeeping, not the authority: YouTube still enforces its
own limits. Tracker read/write failures are logged and never block work.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

from database import execute, fetch_one

logger = logging.getLogger(__name__)

_PACIFIC = ZoneInfo("America/Los_Angeles")

DEFAULT_GENERAL_LIMIT = 10_000
DEFAULT_GENERAL_CEILING = 9_000
DEFAULT_VIDEO_UPLOAD_LIMIT = 100
DEFAULT_SEARCH_CALL_LIMIT = 100

# General-bucket costs only. videos.insert and search.list have dedicated
# call-count buckets and deliberately do not appear here.
UNIT_COSTS: dict[str, int] = {
    "thumbnails.set": 50,
    "videos.update": 50,
    "videos.list": 1,
    "channels.list": 1,
    "playlistItems.list": 1,
}


def _env_int(name: str, default: int, *, legacy_name: str | None = None) -> int:
    raw = os.getenv(name)
    if raw is None and legacy_name:
        raw = os.getenv(legacy_name)
    try:
        value = int(raw) if raw is not None else default
        return value if value >= 0 else default
    except (TypeError, ValueError):
        return default


def _general_limit() -> int:
    return _env_int("YOUTUBE_GENERAL_DAILY_LIMIT", DEFAULT_GENERAL_LIMIT)


def _configured_ceiling() -> int:
    return _env_int(
        "YOUTUBE_GENERAL_QUOTA_CEILING",
        DEFAULT_GENERAL_CEILING,
        legacy_name="YOUTUBE_DAILY_QUOTA_CEILING",
    )


def _ceiling() -> int:
    """Effective ceiling can never exceed the configured project limit."""
    return min(_configured_ceiling(), _general_limit())


def _video_upload_limit() -> int:
    return _env_int("YOUTUBE_VIDEO_UPLOAD_DAILY_LIMIT", DEFAULT_VIDEO_UPLOAD_LIMIT)


def _search_call_limit() -> int:
    return _env_int("YOUTUBE_SEARCH_DAILY_LIMIT", DEFAULT_SEARCH_CALL_LIMIT)


def _pt_today() -> date:
    """Return the asyncpg-compatible DATE key for today's Pacific day."""
    return datetime.now(_PACIFIC).date()


def upload_cost(has_thumbnail: bool) -> int:
    """Backward-compatible helper: upload's general units (thumbnail only)."""
    return UNIT_COSTS["thumbnails.set"] if has_thumbnail else 0


def _bucket(used: int, limit: int) -> dict:
    return {"used": used, "limit": limit, "remaining": max(limit - used, 0)}


def _status(day: date, general_used: int, upload_used: int, search_used: int) -> dict:
    general_ceiling = _ceiling()
    general = _bucket(general_used, general_ceiling)
    general["project_limit"] = _general_limit()
    general["configured_ceiling"] = _configured_ceiling()
    uploads = _bucket(upload_used, _video_upload_limit())
    searches = _bucket(search_used, _search_call_limit())
    return {
        "date_pt": day.isoformat(),
        "general": general,
        "video_uploads": uploads,
        "search_calls": searches,
        "units_used": general_used,
        "ceiling": general_ceiling,
        "remaining": general["remaining"],
    }


async def get_quota_status() -> dict:
    """Return all three daily buckets, with legacy top-level general fields."""
    day = _pt_today()
    try:
        row = await fetch_one(
            """SELECT units_used, video_uploads_used, search_calls_used
               FROM youtube_quota_usage
               WHERE day = $1""",
            day,
        )
        general_used = int(row["units_used"]) if row else 0
        upload_used = int(row["video_uploads_used"]) if row else 0
        search_used = int(row["search_calls_used"]) if row else 0
    except Exception as e:  # noqa: BLE001 - quota tracking must remain fail-soft
        logger.warning("youtube_quota: status read failed, assuming 0 used: %s", e)
        general_used = upload_used = search_used = 0
    return _status(day, general_used, upload_used, search_used)


async def record_quota_usage(
    *,
    general_units: int = 0,
    video_uploads: int = 0,
    search_calls: int = 0,
    operation: str,
) -> None:
    """Atomically add usage to today's independent counters, fail-soft."""
    if general_units <= 0 and video_uploads <= 0 and search_calls <= 0:
        return
    day = _pt_today()
    general_units = max(general_units, 0)
    video_uploads = max(video_uploads, 0)
    search_calls = max(search_calls, 0)
    try:
        await execute(
            """INSERT INTO youtube_quota_usage
                 (day, units_used, video_uploads_used, search_calls_used, updated_at)
               VALUES ($1, $2, $3, $4, now())
               ON CONFLICT (day) DO UPDATE SET
                 units_used = youtube_quota_usage.units_used + EXCLUDED.units_used,
                 video_uploads_used = youtube_quota_usage.video_uploads_used
                   + EXCLUDED.video_uploads_used,
                 search_calls_used = youtube_quota_usage.search_calls_used
                   + EXCLUDED.search_calls_used,
                 updated_at = now()""",
            day,
            general_units,
            video_uploads,
            search_calls,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "youtube_quota: failed to record general=%d uploads=%d searches=%d for %s: %s",
            general_units,
            video_uploads,
            search_calls,
            operation,
            e,
        )


async def record_units(units: int, operation: str) -> None:
    """Backward-compatible general-bucket recorder."""
    await record_quota_usage(general_units=units, operation=operation)


async def record_video_upload(*, thumbnail_succeeded: bool) -> None:
    await record_quota_usage(
        general_units=upload_cost(thumbnail_succeeded),
        video_uploads=1,
        operation="videos.insert"
        + ("+thumbnails.set" if thumbnail_succeeded else ""),
    )


async def record_search_call(operation: str = "search.list") -> None:
    await record_quota_usage(search_calls=1, operation=operation)


async def reserve_search_call() -> tuple[bool, dict]:
    """Atomically reserve one search.list call before it reaches YouTube."""
    day = _pt_today()
    try:
        row = await fetch_one(
            """INSERT INTO youtube_quota_usage
                 (day, units_used, video_uploads_used, search_calls_used, updated_at)
               SELECT $1, 0, 0, 1, now()
               WHERE 1 <= $2
               ON CONFLICT (day) DO UPDATE SET
                 search_calls_used = youtube_quota_usage.search_calls_used + 1,
                 updated_at = now()
               WHERE youtube_quota_usage.search_calls_used + 1 <= $2
               RETURNING units_used, video_uploads_used, search_calls_used""",
            day,
            _search_call_limit(),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("youtube_quota: search reservation failed open: %s", e)
        return True, _status(day, 0, 0, 0)
    if row:
        return True, _status(
            day,
            int(row["units_used"]),
            int(row["video_uploads_used"]),
            int(row["search_calls_used"]),
        )
    status = await get_quota_status()
    status["exhausted_buckets"] = ["search_calls"]
    status["exhausted_bucket"] = "search_calls"
    return False, status


async def reserve_upload(has_thumbnail: bool) -> tuple[bool, dict]:
    """Atomically reserve one upload call and optional thumbnail units.

    PostgreSQL serializes conflicting upserts on the daily row. The WHERE
    clause makes the limit check and increment one indivisible operation.
    A tracker outage remains fail-soft and returns an untracked reservation.
    """
    day = _pt_today()
    general_units = upload_cost(has_thumbnail)
    try:
        row = await fetch_one(
            """INSERT INTO youtube_quota_usage
                 (day, units_used, video_uploads_used, search_calls_used, updated_at)
               SELECT $1::date, $2::integer, 1, 0, now()
               WHERE $2::integer <= $3::integer AND 1 <= $4::integer
               ON CONFLICT (day) DO UPDATE SET
                 units_used = youtube_quota_usage.units_used + EXCLUDED.units_used,
                 video_uploads_used = youtube_quota_usage.video_uploads_used + 1,
                 updated_at = now()
               WHERE youtube_quota_usage.units_used + EXCLUDED.units_used <= $3::integer
                 AND youtube_quota_usage.video_uploads_used + 1 <= $4::integer
               RETURNING units_used, video_uploads_used, search_calls_used""",
            day,
            general_units,
            _ceiling(),
            _video_upload_limit(),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("youtube_quota: upload reservation failed open: %s", e)
        status = _status(day, 0, 0, 0)
        status["reservation"] = {
            "tracked": False,
            "day": day,
            "general_units": general_units,
            "video_uploads": 1,
            "released": False,
        }
        return True, status

    if row:
        status = _status(
            day,
            int(row["units_used"]),
            int(row["video_uploads_used"]),
            int(row["search_calls_used"]),
        )
        status["reservation"] = {
            "tracked": True,
            "day": day,
            "general_units": general_units,
            "video_uploads": 1,
            "released": False,
        }
        return True, status

    status = await get_quota_status()
    exhausted = []
    if status["units_used"] + general_units > status["ceiling"]:
        exhausted.append("general")
    if status["video_uploads"]["used"] + 1 > status["video_uploads"]["limit"]:
        exhausted.append("video_uploads")
    status["exhausted_buckets"] = exhausted
    status["exhausted_bucket"] = exhausted[0] if exhausted else "video_uploads"
    return False, status


async def release_upload_reservation(
    reservation: dict | None,
    *,
    release_upload: bool,
    release_general: bool,
) -> None:
    """Release unused reserved capacity once, never decrementing below zero."""
    if not reservation or not reservation.get("tracked") or reservation.get("released"):
        return
    upload_delta = 1 if release_upload else 0
    general_delta = (
        int(reservation.get("general_units", 0)) if release_general else 0
    )
    if upload_delta == 0 and general_delta == 0:
        reservation["released"] = True
        return
    try:
        await execute(
            """UPDATE youtube_quota_usage SET
                 units_used = GREATEST(units_used - $2, 0),
                 video_uploads_used = GREATEST(video_uploads_used - $3, 0),
                 updated_at = now()
               WHERE day = $1""",
            reservation["day"],
            general_delta,
            upload_delta,
        )
        reservation["released"] = True
    except Exception as e:  # noqa: BLE001
        # Conservative leak is safer than double-spending a daily bucket.
        logger.warning("youtube_quota: failed to release upload reservation: %s", e)


async def check_quota_available(
    units_needed: int = 0,
    *,
    video_uploads_needed: int = 0,
    search_calls_needed: int = 0,
) -> tuple[bool, dict]:
    """Check each requested bucket independently and name any refusal bucket."""
    status = await get_quota_status()
    exhausted: list[str] = []
    if status["units_used"] + units_needed > status["ceiling"]:
        exhausted.append("general")
    if (
        status["video_uploads"]["used"] + video_uploads_needed
        > status["video_uploads"]["limit"]
    ):
        exhausted.append("video_uploads")
    if (
        status["search_calls"]["used"] + search_calls_needed
        > status["search_calls"]["limit"]
    ):
        exhausted.append("search_calls")
    result = dict(status)
    result["exhausted_buckets"] = exhausted
    result["exhausted_bucket"] = exhausted[0] if exhausted else None
    return not exhausted, result


def quota_exceeded_message(status: dict) -> str:
    """Return a precise refusal naming the first exhausted bucket."""
    bucket_name = status.get("exhausted_bucket")
    if bucket_name == "video_uploads":
        bucket = status["video_uploads"]
        label = "video upload"
    elif bucket_name == "search_calls":
        bucket = status["search_calls"]
        label = "YouTube search"
    else:
        bucket = status.get("general", {
            "used": status.get("units_used", 0),
            "limit": status.get("ceiling", _ceiling()),
        })
        label = "general API unit"
    return (
        f"YouTube {label} quota is exhausted for today "
        f"({bucket['used']}/{bucket['limit']} used) — "
        "resets at midnight Pacific time. Try again after the reset."
    )
