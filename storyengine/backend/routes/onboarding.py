"""Onboarding API — unified endpoints for the 5-step onboarding flow.

Steps:
  1. TOOLS    — API keys (delegates to vault)
  2. CHANNEL  — Channel info + optional YouTube connection
  3. STYLE    — Visual/editorial style generation (delegates to system_prompts)
  4. COMPETITORS — Add + scrape competitor channels
  5. INTELLIGENCE — Generate cross-comparison report

Endpoints:
  GET  /api/onboarding/status                   — Enhanced status with all steps
  POST /api/onboarding/channel                  — Save channel info
  POST /api/onboarding/connect-youtube          — Validate YouTube URL, import videos
  POST /api/onboarding/competitors/analyze      — Add 1-3 competitor URLs + scrape
  GET  /api/onboarding/competitors/status       — Poll competitor analysis progress
  POST /api/onboarding/intelligence-report      — Generate intelligence report via Claude
  GET  /api/onboarding/intelligence-report      — Get latest report
  POST /api/onboarding/tutorial-complete        — Mark tutorial as done
  POST /api/onboarding/complete                 — Mark onboarding done
"""

import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from auth import get_tenant_id
from database import fetch_all, fetch_one, execute

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])
logger = logging.getLogger("storyengine")

# In-memory tracking for background competitor analysis
_analyze_jobs: dict[str, dict] = {}
_report_jobs: dict[str, dict] = {}


# ── Models ───────────────────────────────────────────────────────


class ChannelSetup(BaseModel):
    channel_name: str
    niche: str
    target_audience: str = ""


class YouTubeConnect(BaseModel):
    channel_url: str


class CompetitorAnalyze(BaseModel):
    channel_urls: list[str]  # 1-3 YouTube channel URLs


class IntelligenceReportRequest(BaseModel):
    pass  # Uses tenant context, no body needed


# ── Status ───────────────────────────────────────────────────────


@router.get("/status")
async def get_onboarding_status(tenant_id: str = Depends(get_tenant_id)):
    """Enhanced onboarding status with all 5 steps + tutorial."""
    from vault import get_secret_status

    # Channel profile
    cp = await fetch_one(
        """SELECT channel_name, niche, target_audience, style_description,
                  youtube_channel_id, youtube_channel_name, youtube_refresh_token,
                  competitors_added, intelligence_generated, tutorial_completed,
                  onboarding_completed_at, creator_brief
           FROM channel_profiles WHERE tenant_id = $1""",
        tenant_id,
    )

    # API keys status
    required_keys = [
        "kie_ai_api_key",
    ]
    configured_count = 0
    key_statuses = {}
    for key_name in required_keys:
        status = await get_secret_status(key_name, tenant_id)
        is_configured = bool(status.get("configured"))
        key_statuses[key_name] = is_configured
        if is_configured:
            configured_count += 1

    # Optional direct-provider overrides and extras.
    for key_name in [
        "anthropic_api_key",
        "elevenlabs_api_key",
        "elevenlabs_voice_id",
        "openai_api_key",
        "gemini_api_key",
    ]:
        status = await get_secret_status(key_name, tenant_id)
        key_statuses[key_name] = bool(status.get("configured"))

    # Channel configured?
    channel_configured = bool(cp and cp.get("channel_name"))

    # Style generated?
    style_generated = bool(cp and cp.get("style_description"))
    if not style_generated:
        prompt_row = await fetch_one(
            "SELECT id FROM tenant_prompt_defaults WHERE tenant_id = $1 LIMIT 1",
            tenant_id,
        )
        style_generated = bool(prompt_row)

    # YouTube connected?
    youtube_connected = bool(cp and cp.get("youtube_refresh_token"))

    # Competitors added?
    competitors_added = bool(cp and cp.get("competitors_added"))
    if not competitors_added:
        ch_count = await fetch_one(
            "SELECT count(*) as cnt FROM competitor_channels WHERE tenant_id = $1",
            tenant_id,
        )
        competitors_added = (ch_count or {}).get("cnt", 0) > 0

    # Intelligence generated?
    intelligence_generated = bool(cp and cp.get("intelligence_generated"))
    if not intelligence_generated:
        report = await fetch_one(
            "SELECT id FROM intelligence_reports WHERE tenant_id = $1 LIMIT 1",
            tenant_id,
        )
        intelligence_generated = bool(report)

    # Tutorial completed?
    tutorial_completed = bool(cp and cp.get("tutorial_completed"))

    # First video created?
    vid = await fetch_one(
        "SELECT COUNT(*) as count FROM videos WHERE tenant_id = $1", tenant_id
    )
    first_video_created = (vid["count"] if vid else 0) > 0

    # Display name
    account_row = await fetch_one(
        """SELECT a.display_name FROM accounts a
           JOIN memberships m ON m.user_id = a.id
           WHERE m.tenant_id = $1 LIMIT 1""",
        tenant_id,
    )
    display_name = (account_row.get("display_name") or "") if account_row else ""

    # Completion: Kie.ai generation key, channel, and style are core.
    completed = bool(
        configured_count == len(required_keys)
        and channel_configured
        and style_generated
    )

    # Progress: 5 steps
    steps_done = 0
    if configured_count == len(required_keys):
        steps_done += 1
    if channel_configured:
        steps_done += 1
    if style_generated:
        steps_done += 1
    if competitors_added:
        steps_done += 1
    if intelligence_generated:
        steps_done += 1
    percent = round(steps_done / 5 * 100)

    # Durable creator brief from chat onboarding (intent/goals/niche_angle/...).
    # asyncpg may hand JSONB back as a str or an already-parsed dict.
    brief_raw = cp.get("creator_brief") if cp else None
    if isinstance(brief_raw, str):
        try:
            brief_raw = json.loads(brief_raw)
        except (json.JSONDecodeError, ValueError):
            brief_raw = {}
    creator_brief = brief_raw if isinstance(brief_raw, dict) else {}

    return {
        "completed": completed,
        "steps": {
            "api_keys": {
                "configured": configured_count,
                "required": len(required_keys),
                "details": key_statuses,
            },
            "channel_configured": channel_configured,
            "style_generated": style_generated,
            "youtube_connected": youtube_connected,
            "competitors_added": competitors_added,
            "intelligence_generated": intelligence_generated,
            "tutorial_completed": tutorial_completed,
            "first_video_created": first_video_created,
        },
        "percent_complete": percent,
        "display_name": display_name,
        "channel_name": (cp.get("channel_name") or "") if cp else "",
        "youtube_channel_name": (cp.get("youtube_channel_name") or "") if cp else "",
        "niche": (cp.get("niche") or "") if cp else "",
        "creator_brief": creator_brief,
    }


# ── Channel ──────────────────────────────────────────────────────


@router.post("/channel")
async def save_channel(body: ChannelSetup, tenant_id: str = Depends(get_tenant_id)):
    """Save channel info (upsert channel_profiles)."""
    existing = await fetch_one(
        "SELECT id FROM channel_profiles WHERE tenant_id = $1", tenant_id
    )
    if existing:
        await execute(
            """UPDATE channel_profiles
               SET channel_name = $2, niche = $3, target_audience = $4, updated_at = now()
               WHERE tenant_id = $1""",
            tenant_id, body.channel_name, body.niche, body.target_audience,
        )
    else:
        await execute(
            """INSERT INTO channel_profiles (tenant_id, channel_name, niche, target_audience)
               VALUES ($1, $2, $3, $4)""",
            tenant_id, body.channel_name, body.niche, body.target_audience,
        )
    return {"status": "ok", "channel_name": body.channel_name}


# ── YouTube Connection ───────────────────────────────────────────


def _extract_channel_id_from_url(url: str) -> Optional[str]:
    """Extract YouTube channel identifier from various URL formats.

    Handles: @handle, /channel/UCXXX, /c/name, /@handle
    Returns the raw identifier (handle or channel ID).
    """
    url = url.strip().rstrip("/")

    # @handle format: youtube.com/@PowerDoctrine
    match = re.search(r"youtube\.com/@([\w.-]+)", url)
    if match:
        return f"@{match.group(1)}"

    # /channel/UCXXX format
    match = re.search(r"youtube\.com/channel/(UC[\w-]+)", url)
    if match:
        return match.group(1)

    # /c/name format
    match = re.search(r"youtube\.com/c/([\w.-]+)", url)
    if match:
        return match.group(1)

    # Bare handle: @PowerDoctrine (no URL)
    if url.startswith("@"):
        return url

    return None


def _extract_channel_metadata(channel_url: str) -> Optional[dict]:
    """Extract channel metadata via yt-dlp (sync — run in thread pool).

    Returns { channel_name, channel_id, subscriber_count, video_count, channel_url }
    """
    import yt_dlp

    # Normalize URL
    url = channel_url.strip().rstrip("/")
    if not url.startswith("http"):
        if url.startswith("@"):
            url = f"https://www.youtube.com/{url}"
        else:
            url = f"https://www.youtube.com/@{url}"

    opts = {
        "extract_flat": "in_playlist",
        "playlistend": 1,  # Just need channel metadata, not all videos
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
    }

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            result = ydl.extract_info(url + "/videos", download=False)
    except Exception as e:
        logger.warning("[Onboarding] yt-dlp channel extract failed for %s: %s", url, e)
        return None

    if not result:
        return None

    return {
        "channel_name": result.get("channel") or result.get("uploader") or "",
        "channel_id": result.get("channel_id") or result.get("uploader_id") or "",
        "subscriber_count": result.get("channel_follower_count") or 0,
        "video_count": len(result.get("entries") or []),  # Approximate from flat extraction
        "channel_url": result.get("channel_url") or result.get("uploader_url") or url,
    }


@router.post("/connect-youtube")
async def connect_youtube(
    body: YouTubeConnect,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Validate a YouTube channel URL and extract channel info.

    Kicks off async video import into channel_videos table.
    Does NOT require YouTube OAuth — uses public yt-dlp scraping.
    For full analytics (CTR, retention), use the YouTube OAuth flow in /api/auth/youtube/.
    """
    identifier = _extract_channel_id_from_url(body.channel_url)
    if not identifier:
        raise HTTPException(
            status_code=400,
            detail="Could not parse YouTube channel URL. Use format: youtube.com/@ChannelName",
        )

    # Extract channel metadata via yt-dlp (blocking — run in thread)
    metadata = await asyncio.get_event_loop().run_in_executor(
        None, _extract_channel_metadata, body.channel_url
    )
    if not metadata or not metadata.get("channel_name"):
        raise HTTPException(
            status_code=404,
            detail="Channel not found. Check the URL and try again.",
        )

    # Save channel info to channel_profiles
    await execute(
        """UPDATE channel_profiles
           SET youtube_channel_id = $2, youtube_channel_name = $3, updated_at = now()
           WHERE tenant_id = $1""",
        tenant_id, metadata["channel_id"], metadata["channel_name"],
    )

    # Kick off async video import
    background_tasks.add_task(
        _import_channel_videos, tenant_id, body.channel_url, metadata["channel_name"]
    )

    return {
        "status": "ok",
        "channel_name": metadata["channel_name"],
        "channel_id": metadata["channel_id"],
        "subscriber_count": metadata["subscriber_count"],
        "video_count": metadata["video_count"],
        "import_status": "pending",
    }


async def _import_channel_videos(
    tenant_id: str, channel_url: str, channel_name: str
):
    """Background: import user's own YouTube videos into channel_videos table."""
    from routes.niche import _list_channel_videos

    try:
        stubs = await asyncio.get_event_loop().run_in_executor(
            None, _list_channel_videos, channel_url, 50
        )
        if not stubs:
            logger.info("[Onboarding] No videos found for channel %s", channel_name)
            return

        saved = 0
        for stub in stubs:
            try:
                await execute(
                    """INSERT INTO channel_videos
                       (tenant_id, video_id, title, published_at, view_count,
                        duration_seconds, thumbnail_url, metadata)
                       VALUES ($1, $2, $3, $4::timestamptz, $5, $6, $7, $8::jsonb)
                       ON CONFLICT (tenant_id, video_id) DO UPDATE SET
                         title = EXCLUDED.title,
                         view_count = EXCLUDED.view_count,
                         thumbnail_url = EXCLUDED.thumbnail_url""",
                    tenant_id,
                    stub["id"],
                    stub["title"],
                    stub.get("published_at"),
                    stub.get("view_count", 0),
                    stub.get("duration", 0),
                    stub.get("thumbnail"),
                    json.dumps({"channel": channel_name, "url": stub.get("url", "")}),
                )
                saved += 1
            except Exception as e:
                logger.warning("[Onboarding] Failed to save channel video %s: %s", stub.get("id"), e)

        logger.info("[Onboarding] Imported %d/%d videos for %s", saved, len(stubs), channel_name)
    except Exception as e:
        logger.error("[Onboarding] Channel video import failed: %s", e)


# ── Competitor Analysis ──────────────────────────────────────────


@router.post("/competitors/analyze")
async def analyze_competitors(
    body: CompetitorAnalyze,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Accept 1-3 competitor channel URLs, add them, and scrape top videos.

    Returns a job_id for progress polling.
    """
    urls = [u.strip() for u in body.channel_urls if u.strip()]
    if not urls:
        raise HTTPException(status_code=400, detail="At least 1 channel URL required")
    if len(urls) > 3:
        raise HTTPException(status_code=400, detail="Maximum 3 competitor channels")

    job_id = str(uuid.uuid4())[:8]
    _analyze_jobs[job_id] = {
        "tenant_id": tenant_id,
        "status": "starting",
        "channels_total": len(urls),
        "channels_complete": 0,
        "current_channel": None,
        "channel_results": {},
        "intelligence_ready": False,
        "error": None,
    }

    background_tasks.add_task(_run_competitor_analysis, job_id, tenant_id, urls)

    return {"status": "started", "job_id": job_id, "channels": len(urls)}


@router.get("/competitors/status/{job_id}")
async def competitor_analyze_status(job_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Poll competitor analysis progress."""
    job = _analyze_jobs.get(job_id)
    if not job or job.get("tenant_id") != tenant_id:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "status": job["status"],
        "channels_total": job["channels_total"],
        "channels_complete": job["channels_complete"],
        "current_channel": job.get("current_channel"),
        "channel_results": job.get("channel_results", {}),
        "intelligence_ready": job.get("intelligence_ready", False),
        "error": job.get("error"),
    }


async def _run_competitor_analysis(job_id: str, tenant_id: str, urls: list[str]):
    """Background: resolve channel URLs, add to competitor_channels, scrape videos."""
    from routes.niche import _list_channel_videos, _extract_video_info, _calculate_vph, _fetch_publish_dates

    job = _analyze_jobs[job_id]
    job["status"] = "processing"

    for i, url in enumerate(urls):
        channel_label = url.split("/")[-1] or f"Channel {i + 1}"
        job["current_channel"] = channel_label

        try:
            # Step 1: Extract channel metadata
            metadata = await asyncio.get_event_loop().run_in_executor(
                None, _extract_channel_metadata, url
            )
            if not metadata or not metadata.get("channel_name"):
                job["channel_results"][channel_label] = {
                    "status": "failed",
                    "error": "Channel not found",
                }
                continue

            channel_name = metadata["channel_name"]
            job["current_channel"] = channel_name

            # Step 2: Add to competitor_channels (upsert)
            existing = await fetch_one(
                "SELECT id FROM competitor_channels WHERE tenant_id = $1 AND channel_url = $2",
                tenant_id, metadata["channel_url"],
            )
            if existing:
                channel_db_id = str(existing["id"])
                await execute(
                    """UPDATE competitor_channels
                       SET channel_name = $3, subscriber_count = $4, video_count = $5,
                           youtube_channel_id = $6, last_scraped = now()
                       WHERE id = $1 AND tenant_id = $2""",
                    channel_db_id, tenant_id, channel_name,
                    metadata.get("subscriber_count"), metadata.get("video_count"),
                    metadata.get("channel_id"),
                )
            else:
                new_row = await fetch_one(
                    """INSERT INTO competitor_channels
                       (tenant_id, channel_name, channel_url, youtube_channel_id,
                        subscriber_count, video_count, active, last_scraped)
                       VALUES ($1, $2, $3, $4, $5, $6, true, now())
                       RETURNING id""",
                    tenant_id, channel_name, metadata["channel_url"],
                    metadata.get("channel_id"),
                    metadata.get("subscriber_count"), metadata.get("video_count"),
                )
                channel_db_id = str(new_row["id"]) if new_row else None

            # Step 3: Scrape top 50 videos. Prefer the official YouTube Data API
            # (real views/dates, not bot-blocked on our IP) so onboarding doesn't
            # seed views=0 rows; fall back to yt-dlp + HTML dates only without a key.
            api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
            stubs = None
            if api_key:
                try:
                    from youtube_data_api import fetch_channel_videos
                    stubs = await fetch_channel_videos(metadata["channel_url"], api_key, 50)
                except Exception as e:  # noqa: BLE001
                    logger.warning("[Onboarding] YouTube Data API channel fetch failed for %s: %s", url, e)
                    stubs = None
            if not stubs:
                if not api_key:
                    logger.warning("[Onboarding] No YOUTUBE_API_KEY — falling back to yt-dlp "
                                   "(often bot-blocked here); competitor numbers may be missing.")
                stubs = await asyncio.get_event_loop().run_in_executor(
                    None, _list_channel_videos, metadata["channel_url"], 50
                )
                # Step 3.5: Fetch publish dates for stubs missing them (yt-dlp path only)
                if stubs:
                    await _fetch_publish_dates(stubs)

            saved = 0
            saved_refs = []
            now = datetime.now(timezone.utc)
            for stub in (stubs or []):
                try:
                    vph = 0.0
                    hours_old = 168.0  # Default 1 week
                    views = stub.get("view_count", 0)
                    if not views or views <= 0:
                        # Don't seed a zero-view row — it fails the home/discovery
                        # views>0 filter and would block a future real upsert.
                        continue
                    if stub.get("published_at"):
                        vph, hours_old = _calculate_vph(views, stub["published_at"], now)

                    await execute(
                        """INSERT INTO competitor_videos
                           (tenant_id, video_id, title, url, channel, channel_url,
                            views, vph, hours_old, published_date, scrape_date,
                            thumbnail_url, duration_seconds, description)
                           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, now(),
                                   $11, $12, $13)
                           ON CONFLICT (tenant_id, video_id) DO UPDATE SET
                             views = EXCLUDED.views, vph = EXCLUDED.vph,
                             hours_old = EXCLUDED.hours_old, scrape_date = now()""",
                        tenant_id,
                        stub["id"],
                        stub["title"],
                        stub.get("url", ""),
                        channel_name,
                        metadata["channel_url"],
                        views,
                        round(vph, 1),
                        round(hours_old, 1),
                        stub.get("published_at"),
                        stub.get("thumbnail"),
                        stub.get("duration", 0),
                        (stub.get("description") or "")[:2000],
                    )
                    saved += 1
                    saved_refs.append({
                        "id": stub["id"],
                        "views": views,
                        "vph": vph,
                        "published_at": stub.get("published_at"),
                    })
                except Exception as e:
                    logger.warning("[Onboarding] Video save failed: %s", e)

            # Step 4: Enrich/distill the strongest couple of references so the
            # first recommendation can use real hook/script/thumbnail DNA.
            distilled = 0
            top_refs = sorted(
                saved_refs,
                key=lambda item: (
                    1 if item.get("published_at") else 0,
                    float(item.get("vph") or 0),
                    int(item.get("views") or 0),
                ),
                reverse=True,
            )[:2]
            for ref in top_refs:
                try:
                    job["current_channel"] = f"Analyzing reference: {channel_name}"
                    info = await asyncio.get_event_loop().run_in_executor(
                        None, _extract_video_info, ref["id"]
                    )
                    if not info:
                        continue
                    if not info.get("channel"):
                        info["channel"] = channel_name
                    if not info.get("channel_url"):
                        info["channel_url"] = metadata["channel_url"]

                    vph, hours_old = _calculate_vph(
                        info.get("views", 0), info.get("published_at", ""), now
                    )
                    info["vph"] = round(vph, 1)
                    info["hours_old"] = round(hours_old, 1)
                    pub_date = None
                    if info.get("published_at"):
                        try:
                            pub_date = datetime.strptime(str(info["published_at"])[:10], "%Y-%m-%d").date()
                        except (TypeError, ValueError):
                            pub_date = None

                    row = await fetch_one(
                        "SELECT id FROM competitor_videos WHERE tenant_id = $1 AND video_id = $2",
                        tenant_id, info.get("video_id") or ref["id"],
                    )
                    if not row:
                        continue

                    await execute(
                        """UPDATE competitor_videos SET
                             title = COALESCE($3, title),
                             url = COALESCE($4, url),
                             channel = COALESCE($5, channel),
                             channel_url = COALESCE($6, channel_url),
                             views = $7,
                             vph = $8,
                             hours_old = $9,
                             thumbnail_url = COALESCE($10, thumbnail_url),
                             transcript = COALESCE($11, transcript),
                             duration_seconds = COALESCE($12, duration_seconds),
                             description = COALESCE($13, description),
                             likes = COALESCE($14, likes),
                             comment_count = COALESCE($15, comment_count),
                             channel_subscriber_count = COALESCE($16, channel_subscriber_count),
                             like_ratio = COALESCE($17, like_ratio),
                             comment_ratio = COALESCE($18, comment_ratio),
                             views_per_sub_ratio = COALESCE($19, views_per_sub_ratio),
                             published_day_of_week = COALESCE($20, published_day_of_week),
                             published_hour = COALESCE($21, published_hour),
                             has_chapters = COALESCE($22, has_chapters),
                             chapter_count = COALESCE($23, chapter_count),
                             chapter_titles = COALESCE($24, chapter_titles),
                             tags = COALESCE($25, tags),
                             published_date = COALESCE($26, published_date),
                             scrape_date = now()
                           WHERE id = $1 AND tenant_id = $2""",
                        row["id"],
                        tenant_id,
                        info.get("title"),
                        info.get("url"),
                        info.get("channel"),
                        info.get("channel_url"),
                        info.get("views", 0),
                        info.get("vph", 0),
                        info.get("hours_old", 0),
                        info.get("thumbnail_url"),
                        info.get("transcript"),
                        info.get("duration_seconds") or None,
                        info.get("description"),
                        info.get("likes") or None,
                        info.get("comment_count") or None,
                        info.get("channel_subscriber_count") or None,
                        info.get("like_ratio"),
                        info.get("comment_ratio"),
                        info.get("views_per_sub_ratio"),
                        info.get("published_day_of_week"),
                        info.get("published_hour"),
                        info.get("has_chapters"),
                        info.get("chapter_count") or None,
                        info.get("chapter_titles"),
                        info.get("tags"),
                        pub_date,
                    )

                    try:
                        from distillation.pipeline import distill_competitor_video
                        result = await distill_competitor_video(tenant_id, str(row["id"]))
                        if result:
                            distilled += 1
                    except Exception as exc:
                        logger.warning("[Onboarding] Reference distillation failed for %s: %s", ref["id"], exc)
                except Exception as exc:
                    logger.warning("[Onboarding] Reference enrichment failed for %s: %s", ref.get("id"), exc)

            job["channel_results"][channel_name] = {
                "status": "done",
                "subscriber_count": metadata.get("subscriber_count", 0),
                "videos_found": len(stubs or []),
                "videos_saved": saved,
                "videos_distilled": distilled,
            }
            job["channels_complete"] = i + 1

        except Exception as e:
            logger.error("[Onboarding] Competitor analysis failed for %s: %s", url, e)
            job["channel_results"][channel_label] = {
                "status": "failed",
                "error": str(e),
            }
            job["channels_complete"] = i + 1

    # Mark competitors_added on channel_profiles
    await execute(
        "UPDATE channel_profiles SET competitors_added = true, updated_at = now() WHERE tenant_id = $1",
        tenant_id,
    )

    job["status"] = "complete"
    job["current_channel"] = None
    job["intelligence_ready"] = True
    logger.info("[Onboarding] Competitor analysis complete for tenant %s", tenant_id[:8])


# ── Intelligence Report ──────────────────────────────────────────


def _parse_report_json(raw_text: str) -> dict:
    """Parse model JSON even when the provider wraps it in markdown."""
    decoder = json.JSONDecoder()
    text = (raw_text or "").strip()
    candidates = [text]

    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if fence_match:
        candidates.insert(0, fence_match.group(1).strip())

    for candidate in candidates:
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        start = candidate.find("{")
        while start != -1:
            try:
                parsed, _ = decoder.raw_decode(candidate[start:])
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                start = candidate.find("{", start + 1)
                continue
            start = candidate.find("{", start + 1)

    raise ValueError("AI provider returned malformed JSON")


def _fallback_intelligence_report(cp: dict, comp_videos: list[dict], channels: list[dict]) -> dict:
    """Return usable recommendations when the AI provider sends malformed JSON."""
    niche = cp.get("niche") or "this niche"
    top_sources = [
        v.get("title")
        for v in comp_videos[:5]
        if v.get("title")
    ]
    competitor_names = [c.get("channel_name") for c in channels[:3] if c.get("channel_name")]
    source_titles = top_sources[:2]

    return {
        "title_ideas": [
            {
                "title": f"The Hidden Shift Changing {niche}",
                "pattern": "Hidden Shift Reveal",
                "reasoning": "Top competitor videos in this scrape lean on curiosity, stakes, and a specific change viewers feel they need to understand.",
                "source_titles": source_titles,
                "hook_direction": "Open with a sharp before/after contrast and state what most people are missing.",
                "thumbnail_direction": "Use one dominant subject, a high-contrast background, and three words or fewer that create tension.",
                "script_structure": "Start with the surprising claim, prove it with 3 evidence blocks, then close with what happens next.",
                "visual_prompt_direction": "Prompt for clean documentary-style visuals, clear symbolic contrast, maps/data shots where useful, and cinematic closeups.",
                "modeling_notes": "Borrow the title structure and pacing, but use original claims, evidence, and visual metaphors.",
            },
            {
                "title": f"Why Everyone Is Wrong About {niche}",
                "pattern": "Contrarian Correction",
                "reasoning": "The strongest competitor titles create a gap between the viewer's current belief and the story's promised reveal.",
                "source_titles": top_sources[2:4] or source_titles,
                "hook_direction": "Name the common belief, then immediately show the contradiction.",
                "thumbnail_direction": "Split the frame between the accepted story and the hidden reality.",
                "script_structure": "Frame the myth, unpack why it spread, reveal the deeper mechanism, and end with consequences.",
                "visual_prompt_direction": "Use side-by-side contrasts, annotation-style overlays, and deliberate visual reveals.",
                "modeling_notes": "Use competitor-style curiosity while keeping the thesis grounded in your own research.",
            },
            {
                "title": f"The One {niche} Signal No One Is Watching",
                "pattern": "Single Critical Signal",
                "reasoning": "High-performing videos often make a broad trend feel concrete by anchoring it to one overlooked signal.",
                "source_titles": top_sources[4:5] or source_titles,
                "hook_direction": "Show the signal first, then explain why it changes the whole story.",
                "thumbnail_direction": "Feature the signal as the main object with one directional cue or warning mark.",
                "script_structure": "Introduce the signal, connect it to the bigger trend, compare alternatives, and give the viewer a clear takeaway.",
                "visual_prompt_direction": "Prioritize object-focused shots, charts, headlines, and slow push-ins on the key evidence.",
                "modeling_notes": "Model the narrow-focus strategy, not the competitor's exact subject.",
            },
        ],
        "thumbnail_insights": [
            {
                "pattern": "One clear focal point plus tension text",
                "reasoning": "This gives non-technical viewers an immediate reason to click without decoding a crowded frame.",
            },
            {
                "pattern": "Documentary contrast: visible proof versus hidden force",
                "reasoning": "Competitor packaging tends to work best when the thumbnail implies a story underneath the obvious story.",
            },
        ],
        "hook_ideas": [
            {
                "strategy": "Open with the overlooked signal",
                "reasoning": "A concrete signal creates curiosity faster than a broad topic introduction.",
            },
            {
                "strategy": "Challenge the default explanation",
                "reasoning": "A contrarian setup creates an open loop the rest of the script can pay off.",
            },
        ],
        "creation_guidance": {
            "research_plan": "Gather the strongest 3-5 facts, charts, quotes, or events that prove the chosen angle and separate signal from speculation.",
            "script_plan": "Use a curiosity hook, 3 evidence-driven chapters, and a final implication section.",
            "visual_plan": "Mix cinematic B-roll, data overlays, headline pulls, maps or diagrams, and visual contrast between old belief and new reality.",
            "thumbnail_plan": "One main object or person, high contrast, minimal text, and an obvious tension cue.",
            "modeling_next_step": "match structure",
        },
        "channel_analysis": {
            "best_pattern": "Specific-stakes explainers",
            "weakest_area": "Needs more packaged contrast between the obvious story and the hidden mechanism.",
            "quick_win": "Choose one overlooked signal and build the whole video around it.",
            "opportunity": (
                f"Use competitor patterns from {', '.join(competitor_names)} with a more research-heavy, creator-owned angle."
                if competitor_names
                else "Use competitor patterns with a more research-heavy, creator-owned angle."
            ),
        },
    }


async def _build_intelligence_report(tenant_id: str):
    """Generate an intelligence report by cross-comparing competitor data.

    Uses the configured text-generation provider to analyze competitor videos and generate:
    - Title ideas (3-5) with pattern citations
    - Thumbnail insights (2-3 patterns)
    - Hook ideas (2-3 strategies)
    - Channel analysis (if user's YouTube is connected)
    """
    from kie_unified import MissingGenerationKeyError, get_text_client_for_tenant

    # Gather data
    cp = await fetch_one(
        """SELECT channel_name, niche, target_audience, style_description,
                  youtube_channel_name
           FROM channel_profiles WHERE tenant_id = $1""",
        tenant_id,
    )
    if not cp:
        raise HTTPException(status_code=400, detail="Channel profile not set up yet.")

    # Top competitor videos across two useful cuts:
    # - all-time/top-performing by views
    # - recent/top-performing by VPH from roughly the past week
    # Include distilled DNA when available so recommendations can explain hooks,
    # thumbnails, structure, and how to recreate the pattern with our tools.
    comp_videos = await fetch_all(
        """WITH ranked AS (
             SELECT
               cv.id, cv.title, cv.url, cv.channel, cv.views, cv.vph, cv.hours_old,
               cv.published_date, cv.thumbnail_url, cv.duration_seconds, cv.likes,
               cv.description,
               ci.summary AS distilled_summary,
               ci.structured_metadata AS distilled_metadata,
               ROW_NUMBER() OVER (ORDER BY cv.views DESC NULLS LAST) AS views_rank,
               ROW_NUMBER() OVER (
                 ORDER BY CASE WHEN cv.hours_old <= 168 THEN cv.vph ELSE NULL END DESC NULLS LAST,
                          cv.views DESC NULLS LAST
               ) AS recent_rank
             FROM competitor_videos cv
             LEFT JOIN content_intelligence ci
               ON ci.source_id = cv.id
              AND ci.tenant_id = cv.tenant_id
              AND ci.source_type = 'competitor_transcript'
             WHERE cv.tenant_id = $1 AND cv.title IS NOT NULL
           )
           SELECT *
           FROM ranked
           WHERE views_rank <= 25 OR recent_rank <= 15
           ORDER BY
             CASE WHEN recent_rank <= 30 THEN 0 ELSE 1 END,
             COALESCE(vph, 0) DESC,
             views DESC NULLS LAST
           LIMIT 40""",
        tenant_id,
    )
    if not comp_videos or len(comp_videos) < 3:
        raise HTTPException(
            status_code=400,
            detail="Need at least 3 competitor videos to generate a report. Run competitor analysis first.",
        )

    # User's own videos (if available)
    user_videos = await fetch_all(
        """SELECT title, view_count, published_at, thumbnail_url, duration_seconds
           FROM channel_videos
           WHERE tenant_id = $1
           ORDER BY view_count DESC NULLS LAST
           LIMIT 50""",
        tenant_id,
    )

    # Competitor channel info
    channels = await fetch_all(
        """SELECT channel_name, subscriber_count, video_count
           FROM competitor_channels
           WHERE tenant_id = $1 AND active = true""",
        tenant_id,
    )

    def _safe_metadata(value):
        if not value:
            return {}
        if isinstance(value, dict):
            return value
        try:
            return json.loads(value)
        except Exception:
            return {}

    def _compact_video_entry(v):
        metadata = _safe_metadata(v.get("distilled_metadata"))
        hook = metadata.get("hook_dna") or metadata.get("hook") or {}
        title_dna = metadata.get("title_dna") or metadata.get("title") or {}
        thumbnail = metadata.get("thumbnail_dna") or metadata.get("thumbnail") or {}
        content = metadata.get("content_dna") or metadata.get("content") or {}
        structure = metadata.get("structure_dna") or metadata.get("structure") or {}
        retention = metadata.get("retention_dna") or metadata.get("retention") or {}

        entry = {
            "title": v.get("title", ""),
            "channel": v.get("channel", ""),
            "url": v.get("url", ""),
            "views": v.get("views", 0),
            "vph": float(v["vph"]) if v.get("vph") else 0,
            "hours_old": float(v["hours_old"]) if v.get("hours_old") else None,
            "published": str(v.get("published_date", "")),
            "thumbnail_url": v.get("thumbnail_url"),
            "duration_seconds": v.get("duration_seconds") or 0,
        }
        if v.get("distilled_summary"):
            entry["summary"] = v.get("distilled_summary")
        if v.get("description"):
            entry["description_hint"] = (v.get("description") or "")[:350]
        if title_dna:
            entry["title_dna"] = {
                "structure": title_dna.get("structure"),
                "curiosity_gap": title_dna.get("curiosity_gap"),
                "power_words": title_dna.get("power_words"),
            }
        if hook:
            entry["hook_dna"] = {
                "type": hook.get("type"),
                "opening_line": hook.get("opening_line"),
                "open_loop": hook.get("first_open_loop") or hook.get("open_loop"),
            }
        if thumbnail:
            entry["thumbnail_dna"] = {
                "overall_style": thumbnail.get("overall_style"),
                "layout": (thumbnail.get("composition") or {}).get("layout"),
                "face_present": thumbnail.get("face_present"),
                "face_emotion": thumbnail.get("face_emotion"),
                "text": thumbnail.get("text") or thumbnail.get("visible_text"),
                "colors": thumbnail.get("colors") or thumbnail.get("dominant_colors"),
            }
        if content:
            entry["content_dna"] = {
                "tone": content.get("tone"),
                "topic_tags": content.get("topic_tags"),
                "entities": content.get("entities"),
            }
        if structure:
            entry["structure_dna"] = structure
        if retention:
            entry["retention_dna"] = {
                "first_hook_seconds": retention.get("first_hook_seconds"),
                "open_loops": retention.get("open_loops"),
                "payoff_quality": retention.get("payoff_quality"),
            }
        return entry

    # Build Claude prompt
    comp_data = json.dumps(
        [_compact_video_entry(v) for v in comp_videos],
        indent=None,
    )

    user_data = ""
    if user_videos:
        user_data = json.dumps(
            [
                {
                    "title": v.get("title", ""),
                    "views": v.get("view_count", 0),
                    "published": str(v.get("published_at", "")),
                }
                for v in user_videos
            ],
            indent=None,
        )

    channel_info = ""
    if channels:
        channel_info = ", ".join(
            f"{c.get('channel_name', '?')} ({c.get('subscriber_count', 0):,} subs, {c.get('video_count', 0)} videos)"
            for c in channels
        )

    user_section = ""
    if user_data:
        user_section = f"""
User's channel data (their own videos — analyze these for performance patterns):
{user_data}

For channel_analysis, identify:
- Their best-performing title pattern
- Their weakest area (gap in content or style)
- One specific quick-win recommendation
- An opportunity based on trending competitor topics they haven't covered
"""

    system_prompt = f"""You are a YouTube growth strategist analyzing competitive data for a channel in the {cp.get('niche', 'general')} niche.

Channel: {cp.get('channel_name', 'New Channel')}
Audience: {cp.get('target_audience', 'Not specified')}
Style: {cp.get('style_description', 'Not specified')}
Competitors analyzed: {channel_info}

Competitor video data (top videos by views):
{comp_data}
{user_section}
Analyze patterns and generate a JSON report. Return ONLY valid JSON (no markdown, no backticks):

{{
  "title_ideas": [
    {{
      "title": "Specific video title idea",
      "pattern": "Pattern name (e.g., Hidden Actor Reveal, Specific Number + Stakes)",
      "reasoning": "Why this should work based on the data",
      "source_titles": ["Competitor title this was modeled from"],
      "hook_direction": "How the first 15 seconds should open",
      "thumbnail_direction": "Concrete thumbnail concept and visual composition",
      "script_structure": "How the story should be structured",
      "visual_prompt_direction": "What the image/video generation prompts should emphasize",
      "modeling_notes": "How closely to borrow the pattern without copying"
    }}
  ],
  "thumbnail_insights": [
    {{
      "pattern": "Description of the thumbnail pattern",
      "reasoning": "Why it works in this niche"
    }}
  ],
  "hook_ideas": [
    {{
      "strategy": "Opening hook strategy",
      "reasoning": "Based on what top performers do"
    }}
  ],
  "creation_guidance": {{
    "research_plan": "What research evidence the script should gather",
    "script_plan": "Narrative structure and pacing to use",
    "visual_plan": "Visual language, scene types, and shot rhythm to prompt",
    "thumbnail_plan": "Thumbnail composition, text, emotion, and contrast",
    "modeling_next_step": "Recommended modeling mode: loose inspiration, match structure, visual rhythm, or close reference"
  }},
  "channel_analysis": {{"best_pattern": "...", "weakest_area": "...", "quick_win": "...", "opportunity": "..."}}
}}

Generate:
- 3-5 title_ideas based on gaps and proven patterns. Be SPECIFIC — real title text, not templates.
- Each title idea must include practical creation guidance for hook, thumbnail, script structure, visual prompt direction, and modeling notes.
- 2-3 thumbnail_insights about composition patterns that drive clicks in this niche.
- 2-3 hook_ideas for script openings based on top-performing competitor content.
- creation_guidance must explain how StoryEngine should create this kind of video using research, script, image, video, and thumbnail tools.
- channel_analysis ONLY if user channel data was provided above. Otherwise set to null."""

    try:
        text_client = await get_text_client_for_tenant(tenant_id)
        raw_text = await text_client.generate(
            system_prompt,
            max_tokens=6500,
            temperature=0.5,
        )
    except MissingGenerationKeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("[Intelligence] AI request failed: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to reach AI generation API")

    # Parse response
    try:
        report = _parse_report_json(raw_text)
    except ValueError:
        logger.error("[Intelligence] Failed to parse AI response: %s", raw_text[:500])
        report = _fallback_intelligence_report(cp, comp_videos, channels or [])

    # Save to database
    await execute(
        """INSERT INTO intelligence_reports
           (tenant_id, report_type, title_ideas, thumbnail_insights,
            hook_ideas, channel_analysis, creation_guidance,
            competitors_analyzed, videos_analyzed)
           VALUES ($1, 'onboarding', $2::jsonb, $3::jsonb, $4::jsonb, $5::jsonb, $6::jsonb, $7, $8)""",
        tenant_id,
        json.dumps(report.get("title_ideas", [])),
        json.dumps(report.get("thumbnail_insights", [])),
        json.dumps(report.get("hook_ideas", [])),
        json.dumps(report.get("channel_analysis")),
        json.dumps(report.get("creation_guidance")),
        len(channels or []),
        len(comp_videos or []),
    )

    # Mark intelligence_generated
    await execute(
        "UPDATE channel_profiles SET intelligence_generated = true, updated_at = now() WHERE tenant_id = $1",
        tenant_id,
    )

    return {
        "status": "generated",
        "report": report,
        "competitors_analyzed": len(channels or []),
        "videos_analyzed": len(comp_videos or []),
    }


async def _run_intelligence_report_job(job_id: str, tenant_id: str):
    job = _report_jobs.get(job_id)
    if not job:
        return

    job["status"] = "running"
    job["error"] = None
    try:
        result = await _build_intelligence_report(tenant_id)
        job.update({
            "status": "complete",
            "report": result.get("report"),
            "competitors_analyzed": result.get("competitors_analyzed", 0),
            "videos_analyzed": result.get("videos_analyzed", 0),
            "error": None,
        })
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "Intelligence report generation failed."
        job.update({"status": "failed", "error": detail})
        logger.error("[Intelligence] Report job %s failed: %s", job_id, detail)
    except Exception as exc:
        job.update({"status": "failed", "error": "Intelligence report generation failed."})
        logger.exception("[Intelligence] Report job %s failed: %s", job_id, exc)


@router.post("/intelligence-report")
async def generate_intelligence_report(tenant_id: str = Depends(get_tenant_id)):
    """Start intelligence report generation and return immediately."""
    for existing_id, existing in _report_jobs.items():
        if existing.get("tenant_id") == tenant_id and existing.get("status") in {"starting", "running"}:
            return {
                "status": existing.get("status"),
                "job_id": existing_id,
                "report": None,
                "competitors_analyzed": 0,
                "videos_analyzed": 0,
            }

    job_id = str(uuid.uuid4())[:8]
    _report_jobs[job_id] = {
        "tenant_id": tenant_id,
        "status": "starting",
        "report": None,
        "competitors_analyzed": 0,
        "videos_analyzed": 0,
        "error": None,
    }
    asyncio.create_task(_run_intelligence_report_job(job_id, tenant_id))
    return {
        "status": "started",
        "job_id": job_id,
        "report": None,
        "competitors_analyzed": 0,
        "videos_analyzed": 0,
    }


@router.get("/intelligence-report/status/{job_id}")
async def get_intelligence_report_status(job_id: str, tenant_id: str = Depends(get_tenant_id)):
    job = _report_jobs.get(job_id)
    if not job or job.get("tenant_id") != tenant_id:
        raise HTTPException(status_code=404, detail="Report job not found")

    return {
        "status": job.get("status"),
        "job_id": job_id,
        "report": job.get("report"),
        "competitors_analyzed": job.get("competitors_analyzed", 0),
        "videos_analyzed": job.get("videos_analyzed", 0),
        "error": job.get("error"),
    }


@router.get("/intelligence-report")
async def get_intelligence_report(tenant_id: str = Depends(get_tenant_id)):
    """Get the latest intelligence report for this tenant."""
    row = await fetch_one(
        """SELECT id, report_type, title_ideas, thumbnail_insights,
                  hook_ideas, channel_analysis, creation_guidance, competitors_analyzed,
                  videos_analyzed, created_at
           FROM intelligence_reports
           WHERE tenant_id = $1
           ORDER BY created_at DESC
           LIMIT 1""",
        tenant_id,
    )
    if not row:
        return {"status": "not_generated", "report": None}

    return {
        "status": "ok",
        "report": {
            "title_ideas": row.get("title_ideas") or [],
            "thumbnail_insights": row.get("thumbnail_insights") or [],
            "hook_ideas": row.get("hook_ideas") or [],
            "channel_analysis": row.get("channel_analysis"),
            "creation_guidance": row.get("creation_guidance"),
        },
        "competitors_analyzed": row.get("competitors_analyzed", 0),
        "videos_analyzed": row.get("videos_analyzed", 0),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
    }


# ── Completion ───────────────────────────────────────────────────


@router.post("/tutorial-complete")
async def mark_tutorial_complete(tenant_id: str = Depends(get_tenant_id)):
    """Mark the dashboard tutorial as completed."""
    await execute(
        "UPDATE channel_profiles SET tutorial_completed = true, updated_at = now() WHERE tenant_id = $1",
        tenant_id,
    )
    return {"status": "ok"}


@router.post("/complete")
async def complete_onboarding(tenant_id: str = Depends(get_tenant_id)):
    """Mark onboarding as completed."""
    await execute(
        """UPDATE channel_profiles
           SET onboarding_completed_at = now(), updated_at = now()
           WHERE tenant_id = $1""",
        tenant_id,
    )
    return {"completed": True}
