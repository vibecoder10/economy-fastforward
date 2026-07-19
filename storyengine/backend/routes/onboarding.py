"""Onboarding API — endpoints backing the chat-driven onboarding flow
(``routes/chat.py``'s ``_handle_onboarding`` step machine is the live caller
of most of these; the multi-step form below is preserved only behind
``/onboarding?manual=1``, see that page's own comment).

Steps:
  1. TOOLS    — API keys (delegates to vault)
  2. CHANNEL  — Channel info + optional YouTube connection
  3. STYLE    — Visual/editorial style generation (delegates to system_prompts)
  4. COMPETITORS — Add + scrape competitor channels

Endpoints:
  GET  /api/onboarding/status                   — Enhanced status with all steps
  POST /api/onboarding/channel                  — Save channel info
  POST /api/onboarding/connect-youtube          — Validate YouTube URL, import videos,
                                                    then (checklist C45) kick off the full
                                                    channel_dna.learn_channel pass
  POST /api/onboarding/competitors/analyze      — Add 1-3 competitor URLs + scrape
  GET  /api/onboarding/competitors/status       — Poll competitor analysis progress
  POST /api/onboarding/tutorial-complete        — Mark tutorial as done
  POST /api/onboarding/complete                 — Mark onboarding done

RETIRED (checklist C45 · P4.1f): the intelligence-report endpoints
(``POST``/``GET /api/onboarding/intelligence-report``,
``GET /api/onboarding/intelligence-report/status/{job_id}``) generated a
read-once report that nothing downstream ever consumed — no frontend caller,
no chat-flow step (confirmed by grep: the live onboarding step machine below
never dispatches to them; superseded before this chunk by
``_propose_modeling_angles``/``_generate_competitor_ideas`` at
``_finish_onboarding``). They now return 410 Gone pointing at
``channel_dna.learn_channel`` (Channel DNA) as the replacement — graceful
deprecation per the checklist's explicit ask, not a silent removal. The
``intelligence_reports`` DB table is left in place (data, no drop
migration) — retired-in-place, matching this repo's existing "don't drop
migrations" discipline. The generator itself (``_build_intelligence_report``
and its private helpers) is deleted below since nothing calls it anymore —
see this file's git history for the removed implementation.
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


# ── Models ───────────────────────────────────────────────────────


class ChannelSetup(BaseModel):
    channel_name: str
    niche: str
    target_audience: str = ""


class YouTubeConnect(BaseModel):
    channel_url: str


class CompetitorAnalyze(BaseModel):
    channel_urls: list[str]  # 1-3 YouTube channel URLs


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

    # Kick off async video import, then (checklist C45 · P4.1f) the full
    # Channel-DNA learn pass — sequenced in ONE background task
    # (_import_then_learn) so identity_builder always sees this import's
    # rows, and so learn_channel never re-scrapes the same channel a second
    # time via its own optional import step (own-channel mode: no
    # channel_url passed to learn_channel below).
    do_learn = await _has_usable_generation_key(tenant_id)
    background_tasks.add_task(
        _import_then_learn, tenant_id, body.channel_url, metadata["channel_name"], do_learn
    )

    return {
        "status": "ok",
        "channel_name": metadata["channel_name"],
        "channel_id": metadata["channel_id"],
        "subscriber_count": metadata["subscriber_count"],
        "video_count": metadata["video_count"],
        "import_status": "pending",
        # C45: tells the caller (routes/chat.py's onboarding "channel" step)
        # whether the Channel-DNA learn pass was actually scheduled, so its
        # ack can either state the cost or show the "add a key" hint —
        # never both, never neither.
        "dna_learning": "started" if do_learn else "needs_key",
    }


async def _has_usable_generation_key(tenant_id: str) -> bool:
    """True if this tenant already has a usable text-generation key (Claude
    or Kie.ai). Sibling check to ``routes.chat._has_generation_key`` (same
    two vault slots) — duplicated in full rather than imported, to avoid a
    chat.py <-> onboarding.py import cycle (chat.py already imports
    ``connect_youtube``/``analyze_competitors``/etc. from this module at
    call time). Used to decide whether it's worth firing the C45
    Channel-DNA learn pass right after import: a keyless tenant would just
    get a "failed: no credentials" learner result for free (identity_builder
    raises before any paid call), so skip scheduling the task entirely and
    surface the honest "add a key" hint instead — the C04 precedent of
    never blocking onboarding on a missing key."""
    from vault import get_secret
    for slot in ("anthropic_api_key", "kie_ai_api_key"):
        try:
            if await get_secret(slot, tenant_id):
                return True
        except Exception:  # noqa: BLE001 — a missing key is the common case, not an error
            pass
    return False


async def _import_then_learn(
    tenant_id: str, channel_url: str, channel_name: str, learn: bool
) -> None:
    """Background task (checklist C45 · P4.1f): import the channel's videos
    (unchanged behavior — same function, same signature), then kick off the
    full Channel-DNA learn pass (``channel_dna.learn_channel``) in
    "own-channel mode" (no ``channel_url``): learn_channel's own step-1
    import is skipped since this import already seeded ``channel_videos``,
    avoiding a second yt-dlp scrape of the same channel. Sequenced
    (awaited), never run concurrently with the import.

    ``learn`` is decided by the caller (``_has_usable_generation_key``)
    BEFORE scheduling this task — a keyless tenant never gets a background
    task scheduled for this at all.

    Claim-guarded by ``learn_channel``'s own
    ``generation_claims.acquire_channel`` — a second ``learn_channel`` call
    for this tenant (e.g. a "learn this channel" chat ask fired moments
    later) is safely refused as busy, not raced with this one."""
    await _import_channel_videos(tenant_id, channel_url, channel_name)
    if not learn:
        return
    from channel_dna import learn_channel
    try:
        await learn_channel(tenant_id)
    except Exception as e:  # noqa: BLE001 — background task, never raise past here
        logger.warning(
            "[Onboarding] Channel-DNA learn pass failed for tenant %s: %s", tenant_id[:8], e
        )


async def _import_channel_videos(
    tenant_id: str, channel_url: str, channel_name: str
) -> int:
    """Background: import user's own YouTube videos into channel_videos table.

    Returns the number of videos saved/updated (0 on "nothing found" or any
    error) — added for checklist C41 (channel_dna.py::learn_channel), which
    awaits this directly (not as a fire-and-forget background_tasks.add_task
    like connect_youtube below) and needs a count to put in its per-learner
    digest. The original background_tasks caller already discarded the
    return value, so this is purely additive."""
    from routes.niche import _list_channel_videos

    try:
        stubs = await asyncio.get_event_loop().run_in_executor(
            None, _list_channel_videos, channel_url, 50
        )
        if not stubs:
            logger.info("[Onboarding] No videos found for channel %s", channel_name)
            return 0

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
        return saved
    except Exception as e:
        logger.error("[Onboarding] Channel video import failed: %s", e)
        return 0


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


# ── Intelligence Report (RETIRED — checklist C45 · P4.1f) ────────
#
# _build_intelligence_report and its private helpers (_parse_report_json,
# _fallback_intelligence_report, _run_intelligence_report_job) generated a
# read-once report nothing downstream ever consumed — no frontend caller, no
# chat onboarding step (grep-confirmed: see module docstring above). Deleted
# outright rather than left as unreachable dead code (this repo's own
# "remove dead code" rule) — the implementation is in git history on this
# file if it's ever needed again. The three routes stay registered and
# return 410 Gone with a pointer at the replacement (channel_dna.learn_channel
# / "learn this channel" in chat) — graceful deprecation, not a silent
# removal, per the checklist's explicit instruction. `intelligence_reports`
# (the table these used to write) is left in place, untouched — retired,
# not dropped.

_INTELLIGENCE_REPORT_RETIRED_DETAIL = (
    "Retired endpoint. Intelligence reports have been replaced by Channel DNA "
    "learning — say \"learn this channel\" in chat, or POST /api/channel-dna/learn."
)


@router.post("/intelligence-report")
async def generate_intelligence_report(tenant_id: str = Depends(get_tenant_id)):
    raise HTTPException(status_code=410, detail=_INTELLIGENCE_REPORT_RETIRED_DETAIL)


@router.get("/intelligence-report/status/{job_id}")
async def get_intelligence_report_status(job_id: str, tenant_id: str = Depends(get_tenant_id)):
    raise HTTPException(status_code=410, detail=_INTELLIGENCE_REPORT_RETIRED_DETAIL)


@router.get("/intelligence-report")
async def get_intelligence_report(tenant_id: str = Depends(get_tenant_id)):
    raise HTTPException(status_code=410, detail=_INTELLIGENCE_REPORT_RETIRED_DETAIL)


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
