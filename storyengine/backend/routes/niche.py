"""Niche selection + competitor channel management + scraping."""

import asyncio
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel
from database import fetch_one, fetch_all, execute
from auth import get_tenant_id

router = APIRouter(prefix="/api/niche", tags=["niche"])

# Scrape status tracking (in-memory, per-tenant)
_scrape_tasks: dict[str, dict] = {}


class NicheSetup(BaseModel):
    niche_category: str
    sub_niche: str


class ChannelAdd(BaseModel):
    channel_url: str
    channel_name: str
    category: Optional[str] = None


@router.get("/config")
async def get_niche_config(tenant_id: str = Depends(get_tenant_id)):
    """Get current niche configuration."""
    row = await fetch_one(
        "SELECT niche_category, sub_niche FROM autopilot_config WHERE tenant_id = $1",
        tenant_id,
    )
    if not row:
        return {"niche_category": None, "sub_niche": None, "has_channels": False}

    channel_count = await fetch_one(
        "SELECT count(*) as cnt FROM competitor_channels WHERE tenant_id = $1",
        tenant_id,
    )
    return {
        "niche_category": row.get("niche_category"),
        "sub_niche": row.get("sub_niche"),
        "has_channels": (channel_count or {}).get("cnt", 0) > 0,
    }


@router.post("/setup")
async def setup_niche(body: NicheSetup, tenant_id: str = Depends(get_tenant_id)):
    """Save niche category and sub-niche."""
    existing = await fetch_one(
        "SELECT id FROM autopilot_config WHERE tenant_id = $1", tenant_id
    )
    if existing:
        await execute(
            """UPDATE autopilot_config
               SET niche_category = $1, sub_niche = $2, updated_at = NOW()
               WHERE tenant_id = $3""",
            body.niche_category, body.sub_niche, tenant_id,
        )
    else:
        await execute(
            """INSERT INTO autopilot_config (tenant_id, niche_category, sub_niche)
               VALUES ($1, $2, $3)""",
            tenant_id, body.niche_category, body.sub_niche,
        )
    return {"status": "ok"}


@router.get("/channels")
async def list_channels(tenant_id: str = Depends(get_tenant_id)):
    """List competitor channels."""
    rows = await fetch_all(
        """SELECT id, channel_name, channel_url, category, active, last_scraped
           FROM competitor_channels
           WHERE tenant_id = $1
           ORDER BY channel_name""",
        tenant_id,
    )
    return rows or []


@router.post("/channels")
async def add_channel(body: ChannelAdd, tenant_id: str = Depends(get_tenant_id)):
    """Add a competitor channel."""
    await execute(
        """INSERT INTO competitor_channels (tenant_id, channel_name, channel_url, category, active)
           VALUES ($1, $2, $3, $4, true)""",
        tenant_id, body.channel_name, body.channel_url, body.category,
    )
    return {"status": "ok", "channel_name": body.channel_name}


@router.delete("/channels/{channel_id}")
async def remove_channel(channel_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Remove a competitor channel."""
    await execute(
        "DELETE FROM competitor_channels WHERE id = $1 AND tenant_id = $2",
        channel_id, tenant_id,
    )
    return {"status": "ok"}


# --- Competitor Scraping ---


@router.post("/scrape")
async def scrape_channels(
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Trigger scraping of all active competitor channels.

    Calls Apify YouTube scraper, calculates VPH, and inserts into
    competitor_videos table with proper tenant_id.
    """
    if _scrape_tasks.get(tenant_id, {}).get("running"):
        return {"status": "already_running", "message": "Scrape already in progress"}

    _scrape_tasks[tenant_id] = {"running": True, "started": datetime.now(timezone.utc).isoformat()}
    background_tasks.add_task(_run_scrape, tenant_id)
    return {"status": "started", "message": "Scraping competitor channels..."}


@router.get("/scrape/status")
async def scrape_status(tenant_id: str = Depends(get_tenant_id)):
    """Check scrape task status."""
    task = _scrape_tasks.get(tenant_id, {})
    return {
        "is_running": task.get("running", False),
        "videos_found": task.get("videos_found", 0),
        "videos_saved": task.get("videos_saved", 0),
        "error": task.get("error"),
        "last_run": task.get("finished"),
    }


async def _run_scrape(tenant_id: str):
    """Background task: scrape YouTube channels and save to Supabase."""
    try:
        from vault import get_secret

        api_key = await get_secret("apify_api_key", tenant_id)
        if not api_key:
            _scrape_tasks[tenant_id] = {"running": False, "error": "No Apify API key configured. Add it in Settings > Keys."}
            return

        # Get active channels
        channels = await fetch_all(
            """SELECT id, channel_name, channel_url, category
               FROM competitor_channels
               WHERE tenant_id = $1 AND active = true""",
            tenant_id,
        )
        if not channels:
            _scrape_tasks[tenant_id] = {"running": False, "error": "No active channels. Add channels first."}
            return

        channel_urls = [c["channel_url"] for c in channels if c.get("channel_url")]
        print(f"[Scrape] Scraping {len(channel_urls)} channels for tenant {tenant_id}")

        # Call Apify YouTube scraper via REST API (no SDK dependency needed)
        import httpx

        async with httpx.AsyncClient(timeout=120.0) as client:
            # Start actor run
            run_resp = await client.post(
                "https://api.apify.com/v2/acts/streamers~youtube-scraper/runs",
                params={"token": api_key},
                json={
                    "startUrls": [{"url": url} for url in channel_urls],
                    "maxResults": 20 * len(channel_urls),
                    "maxResultsShorts": 0,
                    "maxResultStreams": 0,
                },
            )
            if run_resp.status_code != 201:
                _scrape_tasks[tenant_id] = {"running": False, "error": f"Apify API error: {run_resp.status_code}"}
                return

            run_data = run_resp.json().get("data", {})
            run_id = run_data.get("id")
            dataset_id = run_data.get("defaultDatasetId")

            if not run_id:
                _scrape_tasks[tenant_id] = {"running": False, "error": "Failed to start Apify run"}
                return

            # Poll for completion (max 5 minutes)
            for _ in range(60):
                await asyncio.sleep(5)
                status_resp = await client.get(
                    f"https://api.apify.com/v2/actor-runs/{run_id}",
                    params={"token": api_key},
                )
                status = status_resp.json().get("data", {}).get("status")
                if status == "SUCCEEDED":
                    break
                if status in ("FAILED", "ABORTED", "TIMED-OUT"):
                    _scrape_tasks[tenant_id] = {"running": False, "error": f"Apify run {status}"}
                    return
            else:
                _scrape_tasks[tenant_id] = {"running": False, "error": "Apify run timed out"}
                return

            # Fetch results from dataset
            items_resp = await client.get(
                f"https://api.apify.com/v2/datasets/{dataset_id}/items",
                params={"token": api_key, "format": "json"},
            )
            items = items_resp.json() if items_resp.status_code == 200 else []

        # Normalize and calculate VPH
        now = datetime.now(timezone.utc)
        videos = []
        for item in items:
            video = _normalize_apify_item(item)
            if not video:
                continue

            # Calculate VPH
            vph, hours_old = _calculate_vph(video.get("views", 0), video.get("published_at", ""), now)
            video["vph"] = round(vph, 1)
            video["hours_old"] = round(hours_old, 1)
            videos.append(video)

        _scrape_tasks[tenant_id] = {**_scrape_tasks.get(tenant_id, {}), "videos_found": len(videos)}
        print(f"[Scrape] Found {len(videos)} videos, inserting into Supabase...")

        # Get existing video_ids for this tenant to count new vs updated
        existing = await fetch_all(
            "SELECT video_id FROM competitor_videos WHERE tenant_id = $1",
            tenant_id,
        )
        existing_ids = {r["video_id"] for r in existing}

        # Insert/update videos in Supabase
        saved = 0
        for video in videos:
            try:
                await execute(
                    """INSERT INTO competitor_videos (
                        tenant_id, video_id, title, url, channel, channel_url,
                        views, vph, hours_old, published_date, scrape_date
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::timestamptz, now())
                    ON CONFLICT (tenant_id, video_id) DO UPDATE SET
                        views = EXCLUDED.views,
                        vph = EXCLUDED.vph,
                        hours_old = EXCLUDED.hours_old,
                        scrape_date = now()""",
                    tenant_id,
                    video["video_id"],
                    video["title"],
                    video["url"],
                    video["channel"],
                    video.get("channel_url", ""),
                    video["views"],
                    video["vph"],
                    video["hours_old"],
                    video.get("published_at") or None,
                )
                saved += 1
            except Exception as e:
                print(f"[Scrape] Error saving video {video.get('video_id')}: {e}")

        # Update last_scraped on channels
        for ch in channels:
            try:
                await execute(
                    "UPDATE competitor_channels SET last_scraped = now() WHERE id = $1",
                    str(ch["id"]),
                )
            except Exception:
                pass

        new_count = sum(1 for v in videos if v["video_id"] not in existing_ids)
        print(f"[Scrape] Done: {saved} saved ({new_count} new, {saved - new_count} updated)")

        _scrape_tasks[tenant_id] = {
            "running": False,
            "videos_found": len(videos),
            "videos_saved": saved,
            "new_videos": new_count,
            "finished": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        print(f"[Scrape] Error: {e}")
        _scrape_tasks[tenant_id] = {"running": False, "error": str(e)}


def _normalize_apify_item(raw: dict) -> Optional[dict]:
    """Normalize Apify YouTube scraper output to standard format."""
    video_id = raw.get("id") or raw.get("videoId") or raw.get("video_id")
    title = raw.get("title") or raw.get("name") or ""

    if not video_id or not title:
        return None

    views_raw = raw.get("viewCount") or raw.get("views") or raw.get("view_count") or 0
    views = _parse_count(views_raw)

    return {
        "video_id": video_id,
        "title": title,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "views": views,
        "channel": raw.get("channelName") or raw.get("channel") or "",
        "channel_url": raw.get("channelUrl") or "",
        "published_at": (
            raw.get("publishedAt") or raw.get("uploadDate") or
            raw.get("date") or raw.get("datePublished") or
            raw.get("publishDate") or raw.get("uploadedAt") or ""
        ),
    }


def _parse_count(raw) -> int:
    """Parse view/like counts that may be strings like '1.2M' or ints."""
    if isinstance(raw, (int, float)):
        return int(raw)
    if not isinstance(raw, str):
        return 0
    raw = raw.strip().replace(",", "").replace(" views", "").replace(" likes", "")
    try:
        if raw.endswith("K"):
            return int(float(raw[:-1]) * 1_000)
        if raw.endswith("M"):
            return int(float(raw[:-1]) * 1_000_000)
        if raw.endswith("B"):
            return int(float(raw[:-1]) * 1_000_000_000)
        return int(float(raw))
    except (ValueError, TypeError):
        return 0


def _calculate_vph(views: int, published_at: str, now: datetime) -> tuple[float, float]:
    """Calculate views per hour since upload."""
    if not published_at:
        return 0.0, 0.0
    try:
        if "T" in published_at:
            published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        else:
            published = datetime.strptime(published_at, "%Y-%m-%d").replace(tzinfo=timezone.utc)

        hours_since = (now - published).total_seconds() / 3600
        if hours_since <= 0:
            return 0.0, 0.0
        return views / hours_since, hours_since
    except (ValueError, TypeError):
        return 0.0, 0.0
