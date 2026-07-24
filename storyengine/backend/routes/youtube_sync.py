"""YouTube channel sync — imports the tenant's real channel into StoryEngine.

Channel-first: instead of only refreshing videos we uploaded through the app,
this walks the connected channel's uploads playlist and mirrors EVERY video on
the channel into `channel_videos`, with stats from two Google APIs:

1. YouTube Data API v3 — title, thumbnail, publish date, duration, privacy,
   lifetime views/likes/comments.
2. YouTube Analytics API v2 — impressions, CTR, average view duration,
   retention, watch time, subscribers gained (bulk, one query per metric group)
   plus a day-by-day channel timeseries into `channel_analytics_daily`.

Channel videos that match an internal production row (by youtube_video_id, or
by exact normalized title) get linked via channel_videos.video_id, and their
metrics are written back to `videos` so the learning loop keeps working.

Called from the Analytics page Sync button and the daily auto-sync in main.py.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, BackgroundTasks
from auth import get_tenant_id
from database import fetch_all, fetch_one, execute, safe_column

router = APIRouter(prefix="/api/youtube", tags=["youtube-sync"])

# In-memory sync status per tenant
_sync_tasks: dict[str, dict] = {}

MAX_RETRIES = 2
RETRY_DELAY = 3.0  # seconds
MAX_CHANNEL_VIDEOS = 200  # uploads playlist import cap (quota guard)
DAILY_TIMESERIES_DAYS = 90

# Per-launch pattern flywheel (checklist C56, P4.2-g): "matured enough to
# analyze" reuses the EXACT bar routes/learning_extraction.py::extract_
# learnings() already established as the SaaS-native learnings loop's
# maturity gate (ctr populated AND impressions >= this), rather than
# inventing a new time-based threshold.
LAUNCH_ANALYSIS_MIN_IMPRESSIONS = 1000


def _classify_error(e: Exception) -> str:
    """Classify an error into a category for the status response."""
    msg = str(e).lower()
    if "401" in msg or "403" in msg or "unauthorized" in msg or "forbidden" in msg:
        return "auth"
    if "429" in msg or "rate" in msg or "quota" in msg:
        return "rate_limit"
    if "timeout" in msg or "timed out" in msg:
        return "timeout"
    if "connect" in msg or "network" in msg or "dns" in msg:
        return "network"
    if "404" in msg or "not found" in msg:
        return "not_found"
    if "500" in msg or "502" in msg or "503" in msg or "504" in msg:
        return "api"
    return "unknown"


def _is_retryable(error_type: str) -> bool:
    """Check if an error type is worth retrying."""
    return error_type in ("timeout", "network", "api", "rate_limit")


@router.post("/sync")
async def trigger_sync(
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Trigger a channel-first YouTube sync."""
    if _sync_tasks.get(tenant_id, {}).get("running"):
        return {"status": "already_running", "message": "Sync already in progress"}

    _sync_tasks[tenant_id] = {"running": True, "started": datetime.now(timezone.utc).isoformat()}
    background_tasks.add_task(_run_sync, tenant_id)
    return {"status": "started", "message": "YouTube channel sync started"}


@router.get("/sync/status")
async def sync_status(tenant_id: str = Depends(get_tenant_id)):
    """Check sync task status."""
    task = _sync_tasks.get(tenant_id, {})
    return {
        "is_running": task.get("running", False),
        "videos_synced": task.get("videos_synced", 0),
        "videos_total": task.get("videos_total", 0),
        "videos_failed": task.get("videos_failed", 0),
        "videos_retried": task.get("videos_retried", 0),
        "matched_internal": task.get("matched_internal", 0),
        "channel_synced": task.get("channel_synced", False),
        "errors": task.get("errors", []),
        "error": task.get("error"),
        "error_type": task.get("error_type"),
        "last_run": task.get("finished"),
    }


def _parse_ts(value) -> datetime | None:
    """ISO string (or datetime) -> tz-aware datetime, else None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


async def _run_sync(tenant_id: str):
    """Background task: mirror the connected YouTube channel into the DB."""
    try:
        import os
        import httpx
        from vault import get_secret
        from youtube_owner_api import (
            fetch_channel_summary,
            fetch_playlist_video_ids,
            fetch_video_details,
            refresh_access_token,
        )

        # Try YouTube OAuth token from channel_profiles first (per-user OAuth flow)
        yt_row = await fetch_one(
            "SELECT youtube_refresh_token FROM channel_profiles WHERE tenant_id = $1",
            tenant_id,
        )
        yt_refresh = yt_row.get("youtube_refresh_token") if yt_row else None

        if yt_refresh:
            client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
            client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
            refresh_token = yt_refresh
        else:
            # Fallback: legacy vault-based credentials
            client_id = await get_secret("google_client_id", tenant_id)
            client_secret = await get_secret("google_client_secret", tenant_id)
            refresh_token = await get_secret("google_refresh_token", tenant_id)

        if not all([client_id, client_secret, refresh_token]):
            _sync_tasks[tenant_id] = {
                "running": False,
                "error": "YouTube not connected. Go to Settings to connect your YouTube channel.",
                "error_type": "auth",
            }
            return

        access_token = await refresh_access_token(client_id, client_secret, refresh_token)
        if not access_token:
            _sync_tasks[tenant_id] = {
                "running": False,
                "error": "Google sign-in expired. Re-connect YouTube in Settings.",
                "error_type": "auth",
            }
            return

        synced = 0
        failed = 0
        errors: list[dict] = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            # 1. Channel identity + lifetime stats -> channel_profiles
            summary = await _fetch_with_retry(fetch_channel_summary, client, access_token)
            if not summary:
                _sync_tasks[tenant_id] = {
                    "running": False,
                    "error": "Couldn't read your YouTube channel. Try re-connecting in Settings.",
                    "error_type": "api",
                }
                return

            await execute(
                """UPDATE channel_profiles SET
                     youtube_subscriber_count = $1,
                     youtube_channel_total_views = $2,
                     youtube_channel_video_count = $3,
                     youtube_channel_thumbnail = $4,
                     youtube_stats_synced_at = now(),
                     youtube_channel_id = COALESCE(youtube_channel_id, $5),
                     youtube_channel_name = COALESCE(youtube_channel_name, $6)
                   WHERE tenant_id = $7""",
                summary["subscriber_count"], summary["total_views"], summary["video_count"],
                summary["thumbnail"], summary["channel_id"], summary["title"], tenant_id,
            )

            # 2. Enumerate the uploads playlist and fetch details
            details: list[dict] = []
            video_ids: list[str] = []
            if summary.get("uploads_playlist"):
                video_ids = await _fetch_with_retry(
                    fetch_playlist_video_ids, client, access_token,
                    summary["uploads_playlist"], MAX_CHANNEL_VIDEOS,
                )
                details = await _fetch_with_retry(
                    fetch_video_details, client, access_token, video_ids
                )

            _sync_tasks[tenant_id]["videos_total"] = len(details)

            # Quota bookkeeping: record general Data API units this sync
            # actually spent — 1/channels.list call (step 1
            # above) + 1/playlistItems.list page (50 ids each) +
            # 1/videos.list batch (50 ids each), per Google's published
            # per-call cost (youtube_quota.UNIT_COSTS). This sync path never
            # calls videos.insert/search.list, so it's cheap (single digits
            # to low tens of units/tenant/day) and is recorded for an
            # honest running total, not gated. Uploads have a separate daily
            # videos.insert bucket and are gated in youtube_publish.py.
            import math
            from youtube_quota import record_units
            list_units = 1  # channels.list (step 1, fetch_channel_summary)
            if video_ids:
                list_units += math.ceil(len(video_ids) / 50)
            if details:
                list_units += math.ceil(len(details) / 50)
            await record_units(list_units, "channels.list+playlistItems.list+videos.list (sync)")

            # 3. Mirror into channel_videos (video_id = the YouTube video id;
            # table shared with onboarding intelligence, which owns transcripts)
            for d in details:
                try:
                    await execute(
                        """INSERT INTO channel_videos
                             (tenant_id, video_id, title, thumbnail_url, published_at,
                              duration_seconds, privacy_status, view_count, like_count,
                              comment_count, last_synced_at, updated_at)
                           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10, now(), now())
                           ON CONFLICT (tenant_id, video_id) DO UPDATE SET
                             title = EXCLUDED.title,
                             thumbnail_url = EXCLUDED.thumbnail_url,
                             published_at = EXCLUDED.published_at,
                             duration_seconds = EXCLUDED.duration_seconds,
                             privacy_status = EXCLUDED.privacy_status,
                             view_count = EXCLUDED.view_count,
                             like_count = EXCLUDED.like_count,
                             comment_count = EXCLUDED.comment_count,
                             last_synced_at = now(),
                             updated_at = now()""",
                        tenant_id, d["video_id"], d["title"], d["thumbnail"],
                        _parse_ts(d["published_at"]), d["duration_seconds"],
                        d["privacy_status"], d["views"], d["likes"], d["comments"],
                    )
                    synced += 1
                    _sync_tasks[tenant_id]["videos_synced"] = synced
                except Exception as e:
                    error_type = _classify_error(e)
                    failed += 1
                    errors.append({
                        "video_id": d.get("video_id", ""),
                        "error_type": error_type,
                        "message": str(e)[:200],
                    })
                    _sync_tasks[tenant_id]["videos_failed"] = failed
                    print(f"[YouTubeSync] Upsert failed for {d.get('video_id')} ({error_type}): {e}")

            # 4. Link channel videos to internal production rows
            matched = await _match_internal_videos(tenant_id)
            _sync_tasks[tenant_id]["matched_internal"] = matched

            # 5. Bulk per-video Analytics metrics (CTR, retention, AVD, watch time)
            try:
                per_video = await _fetch_with_retry(
                    _fetch_bulk_video_analytics, client, access_token
                )
                for vid, m in per_video.items():
                    sets = []
                    values = []
                    for col in ("impressions", "ctr_percent", "avg_view_duration_seconds",
                                "avg_retention", "watch_time_hours", "subscribers_gained"):
                        if m.get(col) is not None:
                            values.append(m[col])
                            sets.append(f"{safe_column(col)} = ${len(values)}")
                    if not sets:
                        continue
                    values.append(tenant_id)
                    values.append(vid)
                    await execute(
                        f"UPDATE channel_videos SET {', '.join(sets)}, updated_at = now() "
                        f"WHERE tenant_id = ${len(values) - 1} AND video_id = ${len(values)}",
                        *values,
                    )
            except Exception as e:
                error_type = _classify_error(e)
                errors.append({"video_id": "", "error_type": error_type,
                               "message": f"Analytics metrics: {str(e)[:180]}"})
                print(f"[YouTubeSync] Bulk analytics failed ({error_type}): {e}")

            # 6. Write matched videos' metrics back to `videos` (learning loop)
            try:
                await _writeback_matched_videos(tenant_id)
            except Exception as e:
                error_type = _classify_error(e)
                errors.append({"video_id": "", "error_type": error_type,
                               "message": f"Internal writeback: {str(e)[:180]}"})
                print(f"[YouTubeSync] Writeback failed ({error_type}): {e}")

            # 7. Channel-level daily timeseries -> channel_analytics_daily
            channel_synced = False
            try:
                days = await _fetch_with_retry(_fetch_channel_daily, client, access_token)
                for day in days:
                    await execute(
                        """INSERT INTO channel_analytics_daily
                             (tenant_id, date, views, impressions, ctr, watch_time_minutes,
                              avg_view_duration_seconds, subscribers_gained, subscribers_lost)
                           VALUES ($1, $2::date, $3, $4, $5, $6, $7, $8, $9)
                           ON CONFLICT (tenant_id, date) DO UPDATE SET
                             views = EXCLUDED.views,
                             impressions = EXCLUDED.impressions,
                             ctr = EXCLUDED.ctr,
                             watch_time_minutes = EXCLUDED.watch_time_minutes,
                             avg_view_duration_seconds = EXCLUDED.avg_view_duration_seconds,
                             subscribers_gained = EXCLUDED.subscribers_gained,
                             subscribers_lost = EXCLUDED.subscribers_lost""",
                        tenant_id, day["date"], day.get("views", 0), day.get("impressions"),
                        day.get("ctr"), day.get("watch_time_minutes"),
                        day.get("avg_view_duration_seconds"), day.get("subscribers_gained"),
                        day.get("subscribers_lost"),
                    )
                channel_synced = True
            except Exception as e:
                error_type = _classify_error(e)
                errors.append({"video_id": "", "error_type": error_type,
                               "message": f"Daily timeseries: {str(e)[:180]}"})
                print(f"[YouTubeSync] Daily timeseries failed ({error_type}): {e}")

        _sync_tasks[tenant_id] = {
            "running": False,
            "videos_synced": synced,
            "videos_total": len(details),
            "videos_failed": failed,
            "matched_internal": matched,
            "channel_synced": channel_synced,
            "errors": errors[-10:],
            "finished": datetime.now(timezone.utc).isoformat(),
        }
        print(f"[YouTubeSync] Channel sync: {synced}/{len(details)} videos, "
              f"{matched} matched internal, daily={channel_synced} for tenant {tenant_id}")

    except Exception as e:
        error_type = _classify_error(e)
        print(f"[YouTubeSync] Error ({error_type}): {e}")
        _sync_tasks[tenant_id] = {"running": False, "error": str(e), "error_type": error_type}


async def _match_internal_videos(tenant_id: str) -> int:
    """Link channel_videos rows to internal production rows.

    Pass 1: by youtube_video_id (set by the in-app upload flow).
    Pass 2: exact normalized-title match against finished internal videos that
    were never linked (covers manual uploads via YouTube Studio). No fuzzy
    matching — a wrong link would poison the learning loop.
    """
    await execute(
        """UPDATE channel_videos cv SET internal_video_id = v.id
           FROM videos v
           WHERE cv.tenant_id = $1 AND cv.internal_video_id IS NULL
             AND v.tenant_id = $1
             AND v.youtube_video_id = cv.video_id""",
        tenant_id,
    )
    await execute(
        """UPDATE channel_videos cv SET internal_video_id = v.id
           FROM videos v
           WHERE cv.tenant_id = $1 AND cv.internal_video_id IS NULL
             AND v.tenant_id = $1
             AND v.youtube_video_id IS NULL
             AND v.status IN ('done', 'uploaded_draft')
             AND length(regexp_replace(lower(cv.title), '[^a-z0-9]+', '', 'g')) > 0
             AND regexp_replace(lower(v.video_title), '[^a-z0-9]+', '', 'g')
                 = regexp_replace(lower(cv.title), '[^a-z0-9]+', '', 'g')""",
        tenant_id,
    )
    # Backfill the internal row so the rest of the app knows it's live
    await execute(
        """UPDATE videos v SET
             youtube_video_id = cv.video_id,
             youtube_url = 'https://youtu.be/' || cv.video_id,
             upload_date = COALESCE(v.upload_date, cv.published_at),
             updated_at = now()
           FROM channel_videos cv
           WHERE cv.tenant_id = $1 AND v.tenant_id = $1
             AND cv.internal_video_id = v.id AND v.youtube_video_id IS NULL""",
        tenant_id,
    )
    row = await fetch_one(
        "SELECT COUNT(*)::int AS n FROM channel_videos WHERE tenant_id = $1 AND internal_video_id IS NOT NULL",
        tenant_id,
    )
    return row["n"] if row else 0


async def _writeback_matched_videos(tenant_id: str):
    """Copy synced channel metrics onto linked `videos` rows, fill the
    write-once 24h/48h/7d/30d snapshot columns the learning loop reads,
    (checklist C56, P4.2-g) trigger the per-launch pattern flywheel for any
    video whose analytics just matured this sync pass, and (checklist
    follow-up queue C58) classify any "young" video's early trajectory via
    the early-warning launch classifier."""
    rows = await fetch_all(
        """SELECT cv.internal_video_id AS internal_id, cv.published_at,
                  cv.view_count, cv.like_count, cv.comment_count,
                  cv.impressions, cv.ctr_percent, cv.avg_view_duration_seconds,
                  cv.avg_retention AS cv_retention, cv.watch_time_hours, cv.subscribers_gained,
                  cv.video_id AS cv_video_id,
                  v.upload_date, v.views_24h, v.views_48h, v.views_7d, v.views_30d,
                  v.ctr_48h, v.retention_48h, v.launch_pattern_analyzed_at,
                  v.early_signal_at
           FROM channel_videos cv
           JOIN videos v ON v.id = cv.internal_video_id
           WHERE cv.tenant_id = $1""",
        tenant_id,
    )
    pending_launch_analysis: list[dict] = []
    # C58: videos that are "young" this sync — ctr_48h available (either
    # already set from a prior sync, or just landing in this sync's
    # `snapshots` below) and never classified yet (early_signal_at IS
    # NULL). See early_warning.py's module docstring for why this window
    # only ever opens once per video and closes forever once classified.
    pending_early_signal: list[dict] = []
    for r in rows:
        upload_date = r["upload_date"] or r["published_at"]
        update_fields: dict = {
            "views": r["view_count"] or 0,
            "likes": r["like_count"] or 0,
            "comments": r["comment_count"] or 0,
            "last_analytics_sync": datetime.now(timezone.utc),
        }
        if r["avg_view_duration_seconds"] is not None:
            update_fields["avg_view_duration_seconds"] = r["avg_view_duration_seconds"]
        if r["cv_retention"] is not None:
            update_fields["avg_retention"] = r["cv_retention"]
        if r["watch_time_hours"] is not None:
            update_fields["watch_time_hours"] = r["watch_time_hours"]
        if r["subscribers_gained"] is not None:
            update_fields["subscribers_gained"] = r["subscribers_gained"]
        if r["impressions"] is not None:
            update_fields["impressions"] = r["impressions"]
        if r["ctr_percent"] is not None:
            update_fields["ctr"] = r["ctr_percent"]

        analytics = {"ctr": r["ctr_percent"], "avg_retention": r["cv_retention"]}
        snapshots = _calculate_snapshots(
            dict(r), {"views": r["view_count"] or 0}, analytics, upload_date
        )
        update_fields.update(snapshots)

        # Per-launch pattern flywheel trigger (checklist C56, P4.2-g): queue
        # this video for launch analysis the first time it clears the
        # maturity bar (ctr populated + impressions >= LAUNCH_ANALYSIS_MIN_
        # IMPRESSIONS) and hasn't been analyzed yet (write-once marker,
        # migration 110) — actual analysis runs ONCE for the whole batch
        # after this loop (see below), not per-row.
        if (
            r["ctr_percent"] is not None
            and (r["impressions"] or 0) >= LAUNCH_ANALYSIS_MIN_IMPRESSIONS
            and r.get("launch_pattern_analyzed_at") is None
            and r.get("cv_video_id")
        ):
            update_fields["launch_pattern_analyzed_at"] = datetime.now(timezone.utc)
            pending_launch_analysis.append({
                "youtube_video_id": r["cv_video_id"],
                "internal_video_id": r["internal_id"],
            })

        # C58 early-warning trigger: the effective ctr_48h AFTER this
        # UPDATE is either already in the DB (r["ctr_48h"]) or landing
        # THIS sync (update_fields["ctr_48h"], written by _calculate_
        # snapshots above once hours_since >= 48). If either is present
        # and this video has never been classified (early_signal_at IS
        # NULL), queue it — classification itself decides whether the
        # channel has enough history to actually score it (early_warning.
        # run_early_signal_classification leaves the marker unstamped, and
        # so this video queued again next sync, when the cohort's too thin
        # — never guessed).
        effective_ctr_48h = r["ctr_48h"] if r["ctr_48h"] is not None else update_fields.get("ctr_48h")
        if effective_ctr_48h is not None and r.get("early_signal_at") is None:
            pending_early_signal.append({
                "internal_video_id": r["internal_id"],
                "ctr_48h": effective_ctr_48h,
            })

        set_parts = []
        values = []
        for key, val in update_fields.items():
            values.append(val)
            set_parts.append(f"{safe_column(key)} = ${len(values)}")
        values.append(r["internal_id"])
        # SECURITY: column names come from the hardcoded dict keys + safe_column()
        await execute(
            f"UPDATE videos SET {', '.join(set_parts)} WHERE id = ${len(values)}",
            *values,
        )

    if pending_launch_analysis:
        try:
            from channel_patterns import run_launch_pattern_analysis
            await run_launch_pattern_analysis(tenant_id, pending_launch_analysis)
        except Exception as e:
            # Fail-soft (checklist C56 requirement): a scoring/DB hiccup in
            # the pattern flywheel must never break the analytics sync that
            # triggers it. The marker was already written per-row above
            # (unconditionally, before this call), so a permanent failure
            # here doesn't retry forever either.
            print(f"[YouTubeSync] Launch pattern analysis failed for tenant {tenant_id}: {e}")

    if pending_early_signal:
        try:
            from early_warning import run_early_signal_classification
            await run_early_signal_classification(tenant_id, pending_early_signal)
        except Exception as e:
            # Fail-soft (checklist C58 requirement): a classifier/DB hiccup
            # must never break the analytics sync that triggers it. Unlike
            # the launch-pattern marker above, early_signal_at is written
            # (or deliberately left NULL) INSIDE run_early_signal_
            # classification itself, so a failure here just means this
            # video's classification is retried next sync — never a stuck
            # half-written state.
            print(f"[YouTubeSync] Early-signal classification failed for tenant {tenant_id}: {e}")


async def _fetch_bulk_video_analytics(client, access_token: str) -> dict[str, dict]:
    """Per-video Analytics metrics for the whole channel in two API calls.

    Returns {youtube_video_id: {impressions, ctr_percent, avg_view_duration_seconds,
    avg_retention, watch_time_hours, subscribers_gained}} — keys match
    channel_videos column names.
    """
    end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    base = {
        "ids": "channel==MINE",
        "startDate": "2015-01-01",
        "endDate": end_date,
        "dimensions": "video",
        "maxResults": 200,
    }
    out: dict[str, dict] = {}

    resp = await client.get(
        "https://youtubeanalytics.googleapis.com/v2/reports",
        params={**base,
                "metrics": "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained",
                "sort": "-views"},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if resp.status_code == 200:
        for row in resp.json().get("rows", []) or []:
            out.setdefault(row[0], {}).update({
                "watch_time_hours": round(row[2] / 60, 2),
                "avg_view_duration_seconds": int(round(row[3])),  # column is INTEGER
                "avg_retention": round(row[4], 1),
                "subscribers_gained": int(row[5]),
            })
    else:
        raise RuntimeError(f"Analytics API {resp.status_code}: {resp.text[:150]}")

    resp2 = await client.get(
        "https://youtubeanalytics.googleapis.com/v2/reports",
        params={**base, "metrics": "impressions,impressionClickThroughRate",
                "sort": "-impressions"},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if resp2.status_code == 200:
        for row in resp2.json().get("rows", []) or []:
            out.setdefault(row[0], {}).update({
                "impressions": int(row[1]),
                "ctr_percent": round(row[2] * 100, 2),  # decimal -> percent
            })
    # Impressions metrics can lag or be unavailable; watch metrics alone are fine.

    return out


async def _fetch_channel_daily(client, access_token: str) -> list[dict]:
    """Channel-level day-by-day metrics for the last DAILY_TIMESERIES_DAYS."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=DAILY_TIMESERIES_DAYS)
    base = {
        "ids": "channel==MINE",
        "startDate": start.strftime("%Y-%m-%d"),
        "endDate": end.strftime("%Y-%m-%d"),
        "dimensions": "day",
    }
    days: dict[str, dict] = {}

    resp = await client.get(
        "https://youtubeanalytics.googleapis.com/v2/reports",
        params={**base,
                "metrics": "views,estimatedMinutesWatched,averageViewDuration,subscribersGained,subscribersLost"},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if resp.status_code == 200:
        for row in resp.json().get("rows", []) or []:
            days[row[0]] = {
                "date": row[0],
                "views": int(row[1]),
                "watch_time_minutes": round(row[2], 1),
                "avg_view_duration_seconds": round(row[3], 1),
                "subscribers_gained": int(row[4]),
                "subscribers_lost": int(row[5]),
            }
    else:
        raise RuntimeError(f"Analytics API {resp.status_code}: {resp.text[:150]}")

    resp2 = await client.get(
        "https://youtubeanalytics.googleapis.com/v2/reports",
        params={**base, "metrics": "impressions,impressionClickThroughRate"},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if resp2.status_code == 200:
        for row in resp2.json().get("rows", []) or []:
            days.setdefault(row[0], {"date": row[0]}).update({
                "impressions": int(row[1]),
                "ctr": round(row[2] * 100, 2),
            })

    return list(days.values())


async def _fetch_with_retry(fn, *args, retries: int = MAX_RETRIES):
    """Call fn with retry logic for transient errors."""
    last_error = None
    for attempt in range(1 + retries):
        try:
            result = await fn(*args)
            return result
        except Exception as e:
            last_error = e
            error_type = _classify_error(e)
            if not _is_retryable(error_type) or attempt >= retries:
                raise
            await asyncio.sleep(RETRY_DELAY * (attempt + 1))
    raise last_error


def _extract_video_id(url: str) -> str | None:
    """Extract YouTube video ID from URL."""
    import re
    match = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})", url or "")
    return match.group(1) if match else None


def _calculate_snapshots(video: dict, stats: dict, analytics: dict | None, upload_date) -> dict:
    """Calculate time-bucketed snapshot fields (write-once).

    These preserve the metric value at specific milestones (24h, 48h, 7d, 30d).
    Only writes if the field is currently NULL and the time threshold has passed.
    """
    snapshots = {}

    if not upload_date:
        return snapshots

    try:
        if isinstance(upload_date, str):
            upload_dt = datetime.fromisoformat(upload_date.replace("Z", "+00:00"))
        elif isinstance(upload_date, datetime):
            upload_dt = upload_date if upload_date.tzinfo else upload_date.replace(tzinfo=timezone.utc)
        else:
            return snapshots
    except (ValueError, TypeError):
        return snapshots

    hours_since = (datetime.now(timezone.utc) - upload_dt).total_seconds() / 3600

    views = stats.get("views", 0)

    # Views snapshots
    if hours_since >= 24 and video.get("views_24h") is None:
        snapshots["views_24h"] = views
    if hours_since >= 48 and video.get("views_48h") is None:
        snapshots["views_48h"] = views
    if hours_since >= 168 and video.get("views_7d") is None:  # 7 days
        snapshots["views_7d"] = views
    if hours_since >= 720 and video.get("views_30d") is None:  # 30 days
        snapshots["views_30d"] = views

    # CTR snapshot at 48h
    if hours_since >= 48 and video.get("ctr_48h") is None and analytics:
        ctr = analytics.get("ctr")
        if ctr is not None:
            snapshots["ctr_48h"] = ctr

    # Retention snapshot at 48h
    if hours_since >= 48 and video.get("retention_48h") is None and analytics:
        retention = analytics.get("avg_retention")
        if retention is not None:
            snapshots["retention_48h"] = retention

    return snapshots
