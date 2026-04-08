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
            body.niche_category,
            body.sub_niche,
            tenant_id,
        )
    else:
        await execute(
            """INSERT INTO autopilot_config (tenant_id, niche_category, sub_niche)
               VALUES ($1, $2, $3)""",
            tenant_id,
            body.niche_category,
            body.sub_niche,
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
        tenant_id,
        body.channel_name,
        body.channel_url,
        body.category,
    )
    return {"status": "ok", "channel_name": body.channel_name}


@router.delete("/channels/{channel_id}")
async def remove_channel(channel_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Remove a competitor channel and its associated videos (cascade)."""
    # Look up the channel to get URL/name for cascade delete
    channel = await fetch_one(
        "SELECT channel_url, channel_name FROM competitor_channels WHERE id = $1 AND tenant_id = $2",
        channel_id,
        tenant_id,
    )
    if channel:
        # Delete associated competitor_videos + cascade to discovery_ideas
        ch_url = channel.get("channel_url", "")
        ch_name = channel.get("channel_name", "")
        if ch_url:
            # Nullify discovery_ideas FK before deleting videos
            await execute(
                """UPDATE discovery_ideas SET competitor_video_id = NULL
                   WHERE tenant_id = $1 AND competitor_video_id IN (
                     SELECT id FROM competitor_videos WHERE tenant_id = $1 AND channel_url = $2
                   )""",
                tenant_id,
                ch_url,
            )
            await execute(
                "DELETE FROM competitor_videos WHERE tenant_id = $1 AND channel_url = $2",
                tenant_id,
                ch_url,
            )
        elif ch_name:
            await execute(
                """UPDATE discovery_ideas SET competitor_video_id = NULL
                   WHERE tenant_id = $1 AND competitor_video_id IN (
                     SELECT id FROM competitor_videos WHERE tenant_id = $1 AND channel = $2
                   )""",
                tenant_id,
                ch_name,
            )
            await execute(
                "DELETE FROM competitor_videos WHERE tenant_id = $1 AND channel = $2",
                tenant_id,
                ch_name,
            )
    await execute(
        "DELETE FROM competitor_channels WHERE id = $1 AND tenant_id = $2",
        channel_id,
        tenant_id,
    )
    return {"status": "ok"}


# --- Competitor Videos (paginated) ---

# SECURITY: whitelist-only sort mapping — user input mapped to hardcoded SQL, no injection risk
_SORT_MAP = {
    "vph_desc": "vph DESC",
    "vph_asc": "vph ASC",
    "views_desc": "views DESC",
    "views_asc": "views ASC",
    "published_desc": "published_date DESC NULLS LAST",
    "published_asc": "published_date ASC NULLS LAST",
    "scrape_desc": "scrape_date DESC NULLS LAST",
}


@router.get("/videos")
async def list_videos(
    limit: int = 50,
    offset: int = 0,
    channel: Optional[str] = None,
    min_vph: Optional[float] = None,
    sort: str = "vph_desc",
    tenant_id: str = Depends(get_tenant_id),
):
    """List competitor videos with pagination, filters, and sort."""
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    order = _SORT_MAP.get(sort, "vph DESC")

    conditions = ["tenant_id = $1"]
    params: list = [tenant_id]
    idx = 2

    if channel:
        conditions.append(f"channel = ${idx}")
        params.append(channel)
        idx += 1

    if min_vph is not None and min_vph > 0:
        conditions.append(f"vph >= ${idx}")
        params.append(min_vph)
        idx += 1

    where = " AND ".join(conditions)

    # Total count
    count_row = await fetch_one(
        f"SELECT count(*) as cnt FROM competitor_videos WHERE {where}",
        *params,
    )
    total = (count_row or {}).get("cnt", 0)

    # Fetch page
    params.extend([limit, offset])
    rows = await fetch_all(
        f"""SELECT id, video_id, title, url, channel, channel_url, views, vph,
                   hours_old, published_date, scrape_date, thumbnail_url,
                   duration_seconds, likes, description
            FROM competitor_videos
            WHERE {where}
            ORDER BY {order}
            LIMIT ${idx} OFFSET ${idx + 1}""",
        *params,
    )

    # Distinct channels for filter dropdown
    ch_rows = await fetch_all(
        "SELECT DISTINCT channel FROM competitor_videos WHERE tenant_id = $1 AND channel IS NOT NULL ORDER BY channel",
        tenant_id,
    )
    channels_list = [r["channel"] for r in (ch_rows or []) if r.get("channel")]

    return {
        "videos": rows or [],
        "total": total,
        "limit": limit,
        "offset": offset,
        "channels": channels_list,
    }


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

    _scrape_tasks[tenant_id] = {
        "running": True,
        "started": datetime.now(timezone.utc).isoformat(),
    }
    background_tasks.add_task(_run_scrape, tenant_id)
    return {"status": "started", "message": "Scraping competitor channels..."}


@router.get("/scrape/status")
async def scrape_status(tenant_id: str = Depends(get_tenant_id)):
    """Check scrape task status with per-channel progress."""
    task = _scrape_tasks.get(tenant_id, {})
    return {
        "is_running": task.get("running", False),
        "videos_found": task.get("videos_found", 0),
        "videos_saved": task.get("videos_saved", 0),
        "channels_total": task.get("channels_total", 0),
        "channels_done": task.get("channels_done", 0),
        "current_channel": task.get("current_channel"),
        "channel_progress": task.get("channel_progress", {}),
        "error": task.get("error"),
        "last_run": task.get("finished"),
    }


@router.post("/scrape/cancel")
async def cancel_scrape(tenant_id: str = Depends(get_tenant_id)):
    """Cancel a running scrape task."""
    task = _scrape_tasks.get(tenant_id, {})
    if not task.get("running"):
        return {"status": "not_running", "message": "No scrape in progress"}
    _scrape_tasks[tenant_id]["cancelled"] = True
    return {"status": "cancelling", "message": "Scrape cancellation requested"}


# --- yt-dlp helpers (synchronous — called via asyncio.to_thread) ---


def _normalize_channel_url(url: str) -> str:
    """Normalize YouTube channel URL to /videos tab for yt-dlp playlist extraction."""
    url = url.rstrip("/")
    # Strip existing tab paths (/videos, /shorts, /streams, /featured, etc.)
    url = re.sub(
        r"/(videos|shorts|streams|featured|playlists|community|about)$", "", url
    )
    return url + "/videos"


def _list_channel_videos(channel_url: str, max_results: int = 20) -> list[dict]:
    """List recent videos from a YouTube channel using yt-dlp flat extraction.

    Returns list of dicts with basic metadata. Flat extraction is fast and
    returns enough data to save even without Phase 2 enrichment.
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
            # Try to get publish date from flat extraction
            upload_date = entry.get("upload_date")  # YYYYMMDD format
            timestamp = entry.get("timestamp")  # Unix timestamp
            release_timestamp = entry.get("release_timestamp")

            published_at = None
            if upload_date and len(str(upload_date)) == 8:
                try:
                    published_at = (
                        f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"
                    )
                except (IndexError, TypeError):
                    pass
            elif timestamp:
                try:
                    published_at = datetime.fromtimestamp(
                        int(timestamp), tz=timezone.utc
                    ).isoformat()
                except (ValueError, TypeError, OSError):
                    pass
            elif release_timestamp:
                try:
                    published_at = datetime.fromtimestamp(
                        int(release_timestamp), tz=timezone.utc
                    ).isoformat()
                except (ValueError, TypeError, OSError):
                    pass

            videos.append(
                {
                    "id": vid,
                    "title": entry["title"],
                    "url": f"https://www.youtube.com/watch?v={vid}",
                    # Flat extraction often includes these fields
                    "view_count": entry.get("view_count") or 0,
                    "duration": entry.get("duration") or 0,
                    "description": (entry.get("description") or "")[:2000],
                    "thumbnail": entry.get("thumbnails", [{}])[-1].get("url")
                    if entry.get("thumbnails")
                    else None,
                    "published_at": published_at,
                }
            )
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
    for thumb in sorted(
        thumbnails,
        key=lambda t: t.get("width", 0) * t.get("height", 0),
        reverse=True,
    ):
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
        if (
            not line
            or line.startswith("WEBVTT")
            or line.startswith("NOTE")
            or "-->" in line
        ):
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


async def _fetch_publish_dates(stubs: list[dict]) -> int:
    """Fetch publish dates from YouTube HTML for stubs missing published_at.

    YouTube flat extraction doesn't return upload_date, so videos default to
    168h estimated age, making old high-view videos look artificially "hot."
    This lightweight fetch extracts the real date from HTML meta tags.

    Returns the number of dates successfully fetched.
    """
    import httpx

    need_dates = [s for s in stubs if not s.get("published_at")]
    if not need_dates:
        return 0

    # Regex patterns for date extraction from YouTube HTML
    # YouTube pages include: <meta itemprop="datePublished" content="YYYY-MM-DD">
    # and also: "publishDate":"YYYY-MM-DD" or "uploadDate":"YYYY-MM-DD" in JSON-LD
    date_patterns = [
        re.compile(
            r'itemprop="(?:datePublished|uploadDate)"\s+content="(\d{4}-\d{2}-\d{2})'
        ),
        re.compile(r'"(?:publishDate|uploadDate)"\s*:\s*"(\d{4}-\d{2}-\d{2})'),
    ]

    fetched = 0
    batch_size = 10

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(10.0),
        headers={"User-Agent": "Mozilla/5.0 (compatible; bot)"},
        follow_redirects=True,
    ) as client:
        for batch_start in range(0, len(need_dates), batch_size):
            batch = need_dates[batch_start : batch_start + batch_size]

            for stub in batch:
                try:
                    url = f"https://www.youtube.com/watch?v={stub['id']}"
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        continue

                    html = resp.text
                    for pattern in date_patterns:
                        match = pattern.search(html)
                        if match:
                            stub["published_at"] = match.group(1)
                            fetched += 1
                            break

                    # Small delay between individual requests within a batch
                    await asyncio.sleep(0.3)
                except Exception as e:
                    print(
                        f"[Scrape] Phase 1.5: failed to fetch date for {stub.get('id')}: {e}"
                    )

            # Delay between batches to avoid rate limiting
            if batch_start + batch_size < len(need_dates):
                await asyncio.sleep(1.0)

    return fetched


async def _run_scrape(tenant_id: str, max_videos_per_channel: int = 20):
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
            _scrape_tasks[tenant_id] = {
                "running": False,
                "error": "No active channels. Add channels first.",
            }
            return

        channel_urls = [c["channel_url"] for c in channels if c.get("channel_url")]
        print(
            f"[Scrape] Scraping {len(channel_urls)} channels via yt-dlp for tenant {tenant_id}"
        )

        # T4: Track per-channel progress
        _scrape_tasks[tenant_id]["channels_total"] = len(channels)
        _scrape_tasks[tenant_id]["channels_done"] = 0
        _scrape_tasks[tenant_id]["channel_progress"] = {}

        # Phase 1: List recent videos from each channel (flat extraction — fast)
        all_video_stubs = []
        channel_map = {}  # video_id -> channel info
        for ch_idx, ch in enumerate(channels):
            # Check cancellation
            if _scrape_tasks.get(tenant_id, {}).get("cancelled"):
                print(f"[Scrape] Cancelled by user after {ch_idx} channels")
                _scrape_tasks[tenant_id] = {
                    "running": False,
                    "videos_found": len(all_video_stubs),
                    "videos_saved": 0,
                    "finished": datetime.now(timezone.utc).isoformat(),
                    "error": "Cancelled by user",
                }
                return

            url = ch.get("channel_url")
            if not url:
                continue
            ch_name = ch.get("channel_name", url)
            _scrape_tasks[tenant_id]["current_channel"] = ch_name
            try:
                stubs = await asyncio.to_thread(
                    _list_channel_videos, url, max_videos_per_channel
                )
                for stub in stubs:
                    stub["channel_name"] = ch.get("channel_name", "")
                    stub["channel_url"] = url
                    channel_map[stub["id"]] = ch
                all_video_stubs.extend(stubs)
                _scrape_tasks[tenant_id]["channel_progress"][ch_name] = len(stubs)
                _scrape_tasks[tenant_id]["channels_done"] = ch_idx + 1
                print(f"[Scrape] {ch_name}: {len(stubs)} videos listed")
            except Exception as e:
                _scrape_tasks[tenant_id]["channel_progress"][ch_name] = -1
                _scrape_tasks[tenant_id]["channels_done"] = ch_idx + 1
                print(f"[Scrape] Error listing {ch_name}: {e}")

        if not all_video_stubs:
            _scrape_tasks[tenant_id] = {
                "running": False,
                "error": "No videos found from any channel.",
            }
            return

        _scrape_tasks[tenant_id] = {
            **_scrape_tasks.get(tenant_id, {}),
            "videos_found": len(all_video_stubs),
        }
        print(f"[Scrape] Phase 1 done: {len(all_video_stubs)} video stubs.")

        # Phase 1.5: Fetch publish dates for stubs missing them (flat extraction doesn't return dates)
        missing_dates = sum(1 for s in all_video_stubs if not s.get("published_at"))
        if missing_dates > 0:
            print(
                f"[Scrape] Phase 1.5: {missing_dates}/{len(all_video_stubs)} stubs missing publish dates, fetching..."
            )
            dates_fetched = await _fetch_publish_dates(all_video_stubs)
            print(
                f"[Scrape] Phase 1.5: fetched {dates_fetched} publish dates from {len(all_video_stubs)} videos"
            )
        else:
            print("[Scrape] Phase 1.5: all stubs have publish dates, skipping")

        # Check cancellation before Phase 2
        if _scrape_tasks.get(tenant_id, {}).get("cancelled"):
            print("[Scrape] Cancelled by user before Phase 2")
            _scrape_tasks[tenant_id] = {
                "running": False,
                "videos_found": len(all_video_stubs),
                "videos_saved": 0,
                "finished": datetime.now(timezone.utc).isoformat(),
                "error": "Cancelled by user",
            }
            return

        print("[Scrape] Extracting metadata...")

        # Phase 2: Enrich with full metadata (best-effort, falls back to Phase 1 data)
        now = datetime.now(timezone.utc)
        videos = []
        enriched_count = 0
        for i, stub in enumerate(all_video_stubs):
            # Check cancellation periodically
            if i % 5 == 0 and _scrape_tasks.get(tenant_id, {}).get("cancelled"):
                print(f"[Scrape] Cancelled by user during Phase 2 at video {i}")
                break

            try:
                info = await asyncio.to_thread(_extract_video_info, stub["id"])
            except Exception as e:
                print(f"[Scrape] Error extracting {stub['id']}: {e}")
                info = None

            if info:
                enriched_count += 1
                # Fill in channel info from Phase 1 if yt-dlp didn't return it
                if not info.get("channel"):
                    info["channel"] = stub.get("channel_name", "")
                if not info.get("channel_url"):
                    info["channel_url"] = stub.get("channel_url", "")
            else:
                # Fallback: use Phase 1 stub data so we still save the video
                info = {
                    "video_id": stub["id"],
                    "title": stub.get("title", ""),
                    "url": stub.get(
                        "url", f"https://www.youtube.com/watch?v={stub['id']}"
                    ),
                    "views": stub.get("view_count", 0),
                    "likes": 0,
                    "channel": stub.get("channel_name", ""),
                    "channel_url": stub.get("channel_url", ""),
                    "published_at": stub.get("published_at"),
                    "thumbnail_url": stub.get("thumbnail"),
                    "transcript": None,
                    "duration_seconds": stub.get("duration", 0),
                    "description": stub.get("description", ""),
                }

            # Calculate VPH
            vph, hours_old = _calculate_vph(
                info.get("views", 0), info.get("published_at", ""), now
            )
            info["vph"] = round(vph, 1)
            info["hours_old"] = round(hours_old, 1)
            videos.append(info)

            # Progress update every 10 videos
            if (i + 1) % 10 == 0:
                _scrape_tasks[tenant_id] = {
                    **_scrape_tasks.get(tenant_id, {}),
                    "videos_found": len(all_video_stubs),
                    "videos_saved": len(videos),
                }

        with_dates = sum(1 for v in videos if v.get("published_at"))
        print(
            f"[Scrape] Phase 2 done: {len(videos)} videos ({enriched_count} enriched, {len(videos) - enriched_count} from stubs, {with_dates} with publish dates)"
        )

        # Phase 3: Upsert into Supabase
        existing = await fetch_all(
            "SELECT video_id FROM competitor_videos WHERE tenant_id = $1",
            tenant_id,
        )
        existing_ids = {r["video_id"] for r in existing}

        saved = 0
        for video in videos:
            vid = video.get("video_id", "")
            try:
                # Parse published_at into a date string for Postgres, or None
                pub_date = None
                if video.get("published_at"):
                    try:
                        pa = video["published_at"]
                        if "T" in str(pa):
                            pub_date = datetime.fromisoformat(
                                str(pa).replace("Z", "+00:00")
                            ).date()
                        elif isinstance(pa, str) and len(pa) >= 10:
                            pub_date = datetime.strptime(
                                pa[:10], "%Y-%m-%d"
                            ).date()
                    except (ValueError, TypeError):
                        pub_date = None

                if vid in existing_ids:
                    # UPDATE existing record
                    await execute(
                        """UPDATE competitor_videos SET
                            views = $1, vph = $2, hours_old = $3, scrape_date = now(),
                            thumbnail_url = COALESCE($4, thumbnail_url),
                            transcript = COALESCE($5, transcript),
                            duration_seconds = COALESCE($6, duration_seconds),
                            description = COALESCE($7, description),
                            likes = COALESCE($8, likes)
                        WHERE tenant_id = $9 AND video_id = $10""",
                        video.get("views", 0),
                        video.get("vph", 0),
                        video.get("hours_old", 0),
                        video.get("thumbnail_url"),
                        video.get("transcript"),
                        video.get("duration_seconds") or None,
                        video.get("description"),
                        video.get("likes") or None,
                        tenant_id,
                        vid,
                    )
                else:
                    # INSERT new record
                    await execute(
                        """INSERT INTO competitor_videos (
                            tenant_id, video_id, title, url, channel, channel_url,
                            views, vph, hours_old, published_date, scrape_date,
                            thumbnail_url, transcript, duration_seconds, description, likes
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, now(),
                                  $11, $12, $13, $14, $15)""",
                        tenant_id,
                        vid,
                        video.get("title", ""),
                        video.get("url", ""),
                        video.get("channel", ""),
                        video.get("channel_url", ""),
                        video.get("views", 0),
                        video.get("vph", 0),
                        video.get("hours_old", 0),
                        pub_date,
                        video.get("thumbnail_url"),
                        video.get("transcript"),
                        video.get("duration_seconds") or None,
                        video.get("description"),
                        video.get("likes") or None,
                    )
                saved += 1
                # Update progress every 20 saves
                if saved % 20 == 0:
                    _scrape_tasks[tenant_id] = {
                        **_scrape_tasks.get(tenant_id, {}),
                        "videos_saved": saved,
                    }
            except Exception as e:
                print(f"[Scrape] Error saving video {vid}: {e}")
                # Log first few failures with full detail to aid debugging
                if saved == 0:
                    import traceback

                    traceback.print_exc()

        # Update last_scraped on channels + fix missing names from yt-dlp data
        for ch in channels:
            try:
                # Try to fill in missing channel_name from scraped video data
                ch_name = ch.get("channel_name")
                if not ch_name or ch_name == "None":
                    ch_url = ch.get("channel_url", "")
                    for v in videos:
                        if v.get("channel_url") == ch_url and v.get("channel"):
                            ch_name = v["channel"]
                            break
                    if not ch_name or ch_name == "None":
                        # Extract from URL as last resort: /@ChannelName -> ChannelName
                        match = re.search(r"/@([^/]+)", ch_url)
                        if match:
                            ch_name = match.group(1)

                if (
                    ch_name
                    and ch_name != "None"
                    and ch_name != ch.get("channel_name")
                ):
                    await execute(
                        "UPDATE competitor_channels SET channel_name = $1, last_scraped = now() WHERE id = $2",
                        ch_name,
                        str(ch["id"]),
                    )
                else:
                    await execute(
                        "UPDATE competitor_channels SET last_scraped = now() WHERE id = $1",
                        str(ch["id"]),
                    )
            except Exception:
                pass

        new_count = sum(1 for v in videos if v["video_id"] not in existing_ids)
        with_transcripts = sum(1 for v in videos if v.get("transcript"))
        print(
            f"[Scrape] Done: {saved} saved ({new_count} new, {saved - new_count} updated), {with_transcripts} with transcripts"
        )

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


def _calculate_vph(
    views: int, published_at: str, now: datetime
) -> tuple[float, float]:
    """Calculate views per hour since upload.

    When published_at is missing (stub data), estimate assuming video is ~7 days old.
    This produces a reasonable VPH for high-view videos from flat extraction.
    """
    if not published_at:
        if views and views > 0:
            estimated_hours = 168.0  # ~7 days
            return views / estimated_hours, estimated_hours
        return 0.0, 0.0
    try:
        if "T" in published_at:
            published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        else:
            published = datetime.strptime(published_at, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )

        hours_since = (now - published).total_seconds() / 3600
        if hours_since <= 0:
            return 0.0, 0.0
        return views / hours_since, hours_since
    except (ValueError, TypeError):
        return 0.0, 0.0
