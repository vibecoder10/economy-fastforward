"""Niche selection + competitor channel management + scraping via yt-dlp."""

import asyncio
import re
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
    """Trigger scraping of all active competitor channels via yt-dlp.

    Extracts video metadata, thumbnails, and transcripts. No API key needed.
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


# --- yt-dlp helpers (synchronous — called via asyncio.to_thread) ---


def _normalize_channel_url(url: str) -> str:
    """Normalize YouTube channel URL to /videos tab for yt-dlp playlist extraction."""
    url = url.rstrip("/")
    # Strip existing tab paths (/videos, /shorts, /streams, /featured, etc.)
    url = re.sub(r"/(videos|shorts|streams|featured|playlists|community|about)$", "", url)
    return url + "/videos"


def _list_channel_videos(channel_url: str, max_results: int = 20) -> list[dict]:
    """List recent videos from a YouTube channel using yt-dlp flat extraction.

    Returns list of {id, title, url} without downloading full video info.
    """
    import yt_dlp

    normalized = _normalize_channel_url(channel_url)
    opts = {
        "extract_flat": "in_playlist",
        "playlistend": max_results,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
    }

    with yt_dlp.YoutubeDL(opts) as ydl:
        result = ydl.extract_info(normalized, download=False)

    if not result or "entries" not in result:
        return []

    videos = []
    for entry in result["entries"]:
        if not entry:
            continue
        vid = entry.get("id") or entry.get("url", "").split("v=")[-1]
        if vid and entry.get("title"):
            videos.append({
                "id": vid,
                "title": entry["title"],
                "url": f"https://www.youtube.com/watch?v={vid}",
            })
    return videos


def _extract_video_info(video_id: str) -> Optional[dict]:
    """Extract full metadata + transcript for a single video via yt-dlp."""
    import yt_dlp

    url = f"https://www.youtube.com/watch?v={video_id}"
    opts = {
        "skip_download": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["en"],
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
    }

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        print(f"[yt-dlp] Error extracting {video_id}: {e}")
        return None

    if not info:
        return None

    # Best thumbnail (prefer maxresdefault)
    thumbnail_url = None
    thumbnails = info.get("thumbnails") or []
    for thumb in sorted(thumbnails, key=lambda t: t.get("width", 0) * t.get("height", 0), reverse=True):
        if thumb.get("url"):
            thumbnail_url = thumb["url"]
            break
    if not thumbnail_url:
        thumbnail_url = info.get("thumbnail")

    # Extract transcript from automatic captions
    transcript = _extract_transcript(info)

    # Published date
    upload_date = info.get("upload_date") or ""  # YYYYMMDD format
    published_at = ""
    if upload_date and len(upload_date) == 8:
        published_at = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"

    return {
        "video_id": info.get("id") or video_id,
        "title": info.get("title") or "",
        "url": url,
        "views": info.get("view_count") or 0,
        "likes": info.get("like_count") or 0,
        "channel": info.get("channel") or info.get("uploader") or "",
        "channel_url": info.get("channel_url") or info.get("uploader_url") or "",
        "published_at": published_at,
        "thumbnail_url": thumbnail_url,
        "transcript": transcript,
        "duration_seconds": info.get("duration") or 0,
        "description": (info.get("description") or "")[:2000],  # Cap at 2000 chars
    }


def _extract_transcript(info: dict) -> Optional[str]:
    """Extract auto-generated English transcript text from yt-dlp info dict."""
    auto_captions = info.get("automatic_captions") or {}
    captions = info.get("subtitles") or {}

    # Prefer manual English subs, fallback to auto-generated
    en_subs = captions.get("en") or auto_captions.get("en") or []
    if not en_subs:
        return None

    # Prefer json3 format (structured with timestamps), fallback to vtt
    sub_entry = None
    for fmt in ["json3", "vtt", "srv3", "ttml"]:
        for entry in en_subs:
            if entry.get("ext") == fmt:
                sub_entry = entry
                break
        if sub_entry:
            break

    if not sub_entry or not sub_entry.get("url"):
        return None

    # Fetch subtitle content
    try:
        import httpx

        resp = httpx.get(sub_entry["url"], timeout=15.0)
        if resp.status_code != 200:
            return None

        if sub_entry.get("ext") == "json3":
            return _parse_json3_transcript(resp.text)
        else:
            return _parse_vtt_transcript(resp.text)
    except Exception as e:
        print(f"[yt-dlp] Transcript fetch failed: {e}")
        return None


def _parse_json3_transcript(raw: str) -> Optional[str]:
    """Parse json3 subtitle format into plain text."""
    import json

    try:
        data = json.loads(raw)
        events = data.get("events") or []
        words = []
        for event in events:
            segs = event.get("segs") or []
            for seg in segs:
                text = seg.get("utf8", "").strip()
                if text and text != "\n":
                    words.append(text)
        transcript = " ".join(words).strip()
        return transcript if transcript else None
    except (json.JSONDecodeError, KeyError):
        return None


def _parse_vtt_transcript(raw: str) -> Optional[str]:
    """Parse VTT subtitle format into plain text (strip timestamps + tags)."""
    lines = raw.split("\n")
    text_lines = []
    for line in lines:
        line = line.strip()
        # Skip VTT headers, timestamps, empty lines
        if not line or line.startswith("WEBVTT") or line.startswith("NOTE") or "-->" in line:
            continue
        if re.match(r"^\d+$", line):
            continue
        # Strip HTML-like tags
        clean = re.sub(r"<[^>]+>", "", line).strip()
        if clean:
            text_lines.append(clean)

    # Deduplicate consecutive identical lines (VTT repeats)
    deduped = []
    for line in text_lines:
        if not deduped or line != deduped[-1]:
            deduped.append(line)

    transcript = " ".join(deduped).strip()
    return transcript if transcript else None


async def _run_scrape(tenant_id: str):
    """Background task: scrape YouTube channels via yt-dlp and save to Supabase."""
    try:
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
        print(f"[Scrape] Scraping {len(channel_urls)} channels via yt-dlp for tenant {tenant_id}")

        # Phase 1: List recent videos from each channel (flat extraction — fast)
        all_video_stubs = []
        channel_map = {}  # video_id → channel info
        for ch in channels:
            url = ch.get("channel_url")
            if not url:
                continue
            try:
                stubs = await asyncio.to_thread(_list_channel_videos, url, 20)
                for stub in stubs:
                    stub["channel_name"] = ch.get("channel_name", "")
                    stub["channel_url"] = url
                    channel_map[stub["id"]] = ch
                all_video_stubs.extend(stubs)
                print(f"[Scrape] {ch.get('channel_name')}: {len(stubs)} videos listed")
            except Exception as e:
                print(f"[Scrape] Error listing {ch.get('channel_name')}: {e}")

        if not all_video_stubs:
            _scrape_tasks[tenant_id] = {"running": False, "error": "No videos found from any channel."}
            return

        _scrape_tasks[tenant_id] = {
            **_scrape_tasks.get(tenant_id, {}),
            "videos_found": len(all_video_stubs),
        }
        print(f"[Scrape] Phase 1 done: {len(all_video_stubs)} video stubs. Extracting metadata...")

        # Phase 2: Extract full metadata for each video (runs in thread pool)
        now = datetime.now(timezone.utc)
        videos = []
        for i, stub in enumerate(all_video_stubs):
            try:
                info = await asyncio.to_thread(_extract_video_info, stub["id"])
                if not info:
                    continue

                # Fill in channel info from Phase 1 if yt-dlp didn't return it
                if not info.get("channel"):
                    info["channel"] = stub.get("channel_name", "")
                if not info.get("channel_url"):
                    info["channel_url"] = stub.get("channel_url", "")

                # Calculate VPH
                vph, hours_old = _calculate_vph(info.get("views", 0), info.get("published_at", ""), now)
                info["vph"] = round(vph, 1)
                info["hours_old"] = round(hours_old, 1)
                videos.append(info)
            except Exception as e:
                print(f"[Scrape] Error extracting {stub['id']}: {e}")

            # Progress update every 10 videos
            if (i + 1) % 10 == 0:
                _scrape_tasks[tenant_id] = {
                    **_scrape_tasks.get(tenant_id, {}),
                    "videos_found": len(all_video_stubs),
                    "videos_saved": len(videos),
                }

        print(f"[Scrape] Phase 2 done: {len(videos)} videos extracted with metadata")

        # Phase 3: Upsert into Supabase
        existing = await fetch_all(
            "SELECT video_id FROM competitor_videos WHERE tenant_id = $1",
            tenant_id,
        )
        existing_ids = {r["video_id"] for r in existing}

        saved = 0
        for video in videos:
            try:
                await execute(
                    """INSERT INTO competitor_videos (
                        tenant_id, video_id, title, url, channel, channel_url,
                        views, vph, hours_old, published_date, scrape_date,
                        thumbnail_url, transcript, duration_seconds, description, likes
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::date, now(),
                              $11, $12, $13, $14, $15)
                    ON CONFLICT (tenant_id, video_id) DO UPDATE SET
                        views = EXCLUDED.views,
                        vph = EXCLUDED.vph,
                        hours_old = EXCLUDED.hours_old,
                        scrape_date = now(),
                        thumbnail_url = COALESCE(EXCLUDED.thumbnail_url, competitor_videos.thumbnail_url),
                        transcript = COALESCE(EXCLUDED.transcript, competitor_videos.transcript),
                        duration_seconds = COALESCE(EXCLUDED.duration_seconds, competitor_videos.duration_seconds),
                        description = COALESCE(EXCLUDED.description, competitor_videos.description),
                        likes = COALESCE(EXCLUDED.likes, competitor_videos.likes)""",
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
                    video.get("thumbnail_url"),
                    video.get("transcript"),
                    video.get("duration_seconds") or None,
                    video.get("description"),
                    video.get("likes") or None,
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
        with_transcripts = sum(1 for v in videos if v.get("transcript"))
        print(f"[Scrape] Done: {saved} saved ({new_count} new, {saved - new_count} updated), {with_transcripts} with transcripts")

        _scrape_tasks[tenant_id] = {
            "running": False,
            "videos_found": len(all_video_stubs),
            "videos_saved": saved,
            "new_videos": new_count,
            "with_transcripts": with_transcripts,
            "finished": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        print(f"[Scrape] Error: {e}")
        _scrape_tasks[tenant_id] = {"running": False, "error": str(e)}


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
