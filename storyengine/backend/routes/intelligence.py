"""Content Intelligence API — semantic search, backfill, and distilled insights.

Endpoints:
  POST /api/intelligence/backfill          — Process existing transcripts
  POST /api/intelligence/distill-url       — Scrape + distill a single YouTube URL
  GET  /api/intelligence/search            — Semantic similarity search
  GET  /api/intelligence/stats             — Distillation progress stats
  GET  /api/intelligence/{source_id}       — Get distilled intelligence for a source
  GET  /api/intelligence/insights/topics   — Top topics across distilled content
  GET  /api/intelligence/insights/hooks    — Hook pattern distribution
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
from auth import get_tenant_id
from database import fetch_all, fetch_one, execute

router = APIRouter(prefix="/api/intelligence", tags=["intelligence"])
logger = logging.getLogger("storyengine")

# Track backfill progress per tenant
_backfill_tasks: dict[str, dict] = {}


# ── Backfill ──────────────────────────────────────────────────────

@router.post("/backfill")
async def trigger_backfill(
    background_tasks: BackgroundTasks,
    batch_size: int = Query(default=50, le=200),
    tenant_id: str = Depends(get_tenant_id),
):
    """Trigger background distillation of existing competitor transcripts."""
    if _backfill_tasks.get(tenant_id, {}).get("running"):
        return {"status": "already_running", **_backfill_tasks[tenant_id]}

    _backfill_tasks[tenant_id] = {"running": True, "processed": 0, "failed": 0}
    background_tasks.add_task(_run_backfill, tenant_id, batch_size)
    return {"status": "started", "batch_size": batch_size}


async def _run_backfill(tenant_id: str, batch_size: int):
    """Background task for bulk distillation."""
    try:
        from distillation.pipeline import backfill_competitor_transcripts
        result = await backfill_competitor_transcripts(tenant_id, batch_size)
        _backfill_tasks[tenant_id] = {"running": False, **result}
        logger.info("[Intelligence] Backfill complete for %s: %s", tenant_id[:8], result)
    except Exception as e:
        _backfill_tasks[tenant_id] = {"running": False, "error": str(e)}
        logger.error("[Intelligence] Backfill failed for %s: %s", tenant_id[:8], e)


@router.get("/backfill/status")
async def get_backfill_status(tenant_id: str = Depends(get_tenant_id)):
    """Check backfill progress."""
    return _backfill_tasks.get(tenant_id, {"running": False, "status": "idle"})


# ── Distill Single URL ──────────────────────────────────────────


class DistillURLRequest(BaseModel):
    url: str


def _extract_video_id_from_url(url: str) -> Optional[str]:
    """Extract YouTube video ID from various URL formats."""
    patterns = [
        r"(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})",
        r"(?:embed/)([a-zA-Z0-9_-]{11})",
        r"(?:shorts/)([a-zA-Z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


@router.post("/distill-url")
async def distill_from_url(
    body: DistillURLRequest,
    tenant_id: str = Depends(get_tenant_id),
):
    """Scrape a single YouTube URL via yt-dlp, store it, and distill full DNA.

    End-to-end: URL → yt-dlp extract → competitor_videos INSERT → distillation → DNA result.
    """
    video_id = _extract_video_id_from_url(body.url)
    if not video_id:
        raise HTTPException(status_code=400, detail="Could not extract video ID from URL")

    # Check if already distilled
    existing = await fetch_one(
        """SELECT cv.id, cv.title, cv.distilled_at,
                  ci.summary, ci.structured_metadata
           FROM competitor_videos cv
           LEFT JOIN content_intelligence ci
               ON ci.source_id = cv.id AND ci.tenant_id = cv.tenant_id
               AND ci.source_type = 'competitor_transcript'
           WHERE cv.video_id = $1 AND cv.tenant_id = $2""",
        video_id, tenant_id,
    )
    if existing and existing.get("distilled_at"):
        metadata = existing.get("structured_metadata")
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        return {
            "status": "already_distilled",
            "video_id": video_id,
            "title": existing.get("title"),
            "summary": existing.get("summary"),
            "dna": metadata,
        }

    # Step 1: yt-dlp extraction (sync, run in thread pool)
    logger.info("[Distill-URL] Extracting %s via yt-dlp...", video_id)
    from routes.niche import _extract_video_info, _calculate_vph
    try:
        info = await asyncio.get_event_loop().run_in_executor(
            None, _extract_video_info, video_id
        )
    except Exception as e:
        logger.error("[Distill-URL] yt-dlp failed for %s: %s", video_id, e)
        raise HTTPException(status_code=502, detail=f"yt-dlp extraction failed: {e}")

    if not info:
        raise HTTPException(status_code=404, detail="Video not found or unavailable")

    # Calculate VPH
    now = datetime.now(timezone.utc)
    vph, hours_old = _calculate_vph(info.get("views", 0), info.get("published_at", ""), now)
    info["vph"] = round(vph, 1)
    info["hours_old"] = round(hours_old, 1)

    # Step 2: Upsert into competitor_videos
    pub_date = info.get("published_at") or None
    vid = info.get("video_id", video_id)

    existing_row = await fetch_one(
        "SELECT id FROM competitor_videos WHERE video_id = $1 AND tenant_id = $2",
        vid, tenant_id,
    )

    if existing_row:
        # Update existing record with fresh data
        await execute(
            """UPDATE competitor_videos SET
                title = $3, views = $4, vph = $5, hours_old = $6,
                thumbnail_url = $7, transcript = $8, duration_seconds = $9,
                description = $10, likes = $11, comment_count = $12,
                channel_subscriber_count = $13, like_ratio = $14,
                comment_ratio = $15, views_per_sub_ratio = $16,
                published_day_of_week = $17, published_hour = $18,
                has_chapters = $19, chapter_count = $20,
                chapter_titles = $21, tags = $22, scrape_date = now()
            WHERE video_id = $1 AND tenant_id = $2""",
            vid, tenant_id,
            info.get("title", ""),
            info.get("views", 0),
            info.get("vph", 0),
            info.get("hours_old", 0),
            info.get("thumbnail_url"),
            info.get("transcript"),
            info.get("duration_seconds"),
            info.get("description"),
            info.get("likes"),
            info.get("comment_count"),
            info.get("channel_subscriber_count"),
            info.get("like_ratio"),
            info.get("comment_ratio"),
            info.get("views_per_sub_ratio"),
            info.get("published_day_of_week"),
            info.get("published_hour"),
            info.get("has_chapters"),
            info.get("chapter_count"),
            info.get("chapter_titles"),
            info.get("tags"),
        )
        cv_id = str(existing_row["id"])
    else:
        # Insert new record
        new_row = await fetch_one(
            """INSERT INTO competitor_videos (
                tenant_id, video_id, title, url, channel, channel_url,
                views, vph, hours_old, published_date, scrape_date,
                thumbnail_url, transcript, duration_seconds, description, likes,
                comment_count, channel_subscriber_count,
                like_ratio, comment_ratio, views_per_sub_ratio,
                published_day_of_week, published_hour,
                has_chapters, chapter_count, chapter_titles, tags
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, now(),
                      $11, $12, $13, $14, $15,
                      $16, $17, $18, $19, $20, $21, $22,
                      $23, $24, $25, $26)
            RETURNING id""",
            tenant_id,
            vid,
            info.get("title", ""),
            info.get("url", ""),
            info.get("channel", ""),
            info.get("channel_url", ""),
            info.get("views", 0),
            info.get("vph", 0),
            info.get("hours_old", 0),
            pub_date,
            info.get("thumbnail_url"),
            info.get("transcript"),
            info.get("duration_seconds"),
            info.get("description"),
            info.get("likes"),
            info.get("comment_count"),
            info.get("channel_subscriber_count"),
            info.get("like_ratio"),
            info.get("comment_ratio"),
            info.get("views_per_sub_ratio"),
            info.get("published_day_of_week"),
            info.get("published_hour"),
            info.get("has_chapters"),
            info.get("chapter_count"),
            info.get("chapter_titles"),
            info.get("tags"),
        )
        cv_id = str(new_row["id"]) if new_row else None

    if not cv_id:
        raise HTTPException(status_code=500, detail="Failed to store video record")

    has_transcript = bool((info.get("transcript") or "").strip())
    transcript_chars = len(info.get("transcript") or "")

    logger.info(
        "[Distill-URL] Stored %s (%s) — %d views, %.1f VPH, %s transcript (%d chars)",
        vid, info.get("title", "")[:40], info.get("views", 0), vph,
        "has" if has_transcript else "no", transcript_chars,
    )

    # Step 3: Run distillation
    from distillation.pipeline import distill_competitor_video
    try:
        result = await distill_competitor_video(tenant_id, cv_id)
    except Exception as e:
        logger.error("[Distill-URL] Distillation failed for %s: %s", cv_id[:8], e)
        # Return partial result — at least the video is stored
        return {
            "status": "scraped_but_distillation_failed",
            "video_id": vid,
            "title": info.get("title"),
            "channel": info.get("channel"),
            "views": info.get("views"),
            "vph": info.get("vph"),
            "has_transcript": has_transcript,
            "transcript_chars": transcript_chars,
            "error": str(e),
        }

    # Step 4: Fetch the full DNA to return
    intelligence = await fetch_one(
        """SELECT summary, structured_metadata
           FROM content_intelligence
           WHERE source_id = $1 AND tenant_id = $2
             AND source_type = 'competitor_transcript'""",
        cv_id, tenant_id,
    )

    dna = None
    summary = None
    if intelligence:
        dna = intelligence.get("structured_metadata")
        if isinstance(dna, str):
            dna = json.loads(dna)
        summary = intelligence.get("summary")

    return {
        "status": "distilled",
        "video_id": vid,
        "title": info.get("title"),
        "channel": info.get("channel"),
        "views": info.get("views"),
        "vph": info.get("vph"),
        "has_transcript": has_transcript,
        "transcript_chars": transcript_chars,
        "summary": summary,
        "dna": dna,
        "distillation_result": result,
    }


# ── Semantic Search ───────────────────────────────────────────────

@router.get("/search")
async def semantic_search(
    q: str = Query(..., min_length=2, max_length=500),
    source_type: Optional[str] = Query(default=None),
    limit: int = Query(default=20, le=100),
    tenant_id: str = Depends(get_tenant_id),
):
    """Find semantically similar content using vector search.

    Generates an embedding for the query, then finds nearest neighbors
    in the content_intelligence table.
    """
    from vault import get_secret
    openai_key = await get_secret("openai_api_key", tenant_id)
    if not openai_key:
        raise HTTPException(status_code=400, detail="OpenAI API key not configured")

    from distillation.embeddings import generate_embedding
    query_embedding = await generate_embedding(q, openai_key)
    if not query_embedding:
        raise HTTPException(status_code=500, detail="Failed to generate query embedding")

    # Build query with optional source_type filter
    type_filter = "AND ci.source_type = $3" if source_type else ""
    params = [tenant_id, str(query_embedding), limit]
    if source_type:
        params = [tenant_id, str(query_embedding), source_type, limit]

    rows = await fetch_all(
        f"""SELECT
                ci.id,
                ci.source_type,
                ci.source_id,
                ci.summary,
                ci.structured_metadata,
                ci.raw_char_count,
                ci.created_at,
                1 - (ci.embedding <=> $2::vector) as similarity,
                cv.title as source_title,
                cv.vph as source_vph,
                cv.channel as source_channel,
                cv.url as source_url,
                cv.thumbnail_url as source_thumbnail_url
            FROM content_intelligence ci
            LEFT JOIN competitor_videos cv
                ON ci.source_id = cv.id AND ci.tenant_id = cv.tenant_id
            WHERE ci.tenant_id = $1
              AND ci.embedding IS NOT NULL
              {type_filter}
            ORDER BY ci.embedding <=> $2::vector
            LIMIT ${len(params)}""",
        *params,
    )

    return {
        "query": q,
        "results": [
            {
                "id": str(r["id"]),
                "source_type": r["source_type"],
                "source_id": str(r["source_id"]),
                "summary": r["summary"],
                "metadata": r["structured_metadata"] if isinstance(r["structured_metadata"], dict) else json.loads(r["structured_metadata"]),
                "similarity": round(float(r["similarity"]), 4) if r.get("similarity") else None,
                "source_title": r.get("source_title"),
                "source_vph": float(r["source_vph"]) if r.get("source_vph") else None,
                "source_channel": r.get("source_channel"),
                "source_url": r.get("source_url"),
                "source_thumbnail_url": r.get("source_thumbnail_url"),
                "raw_char_count": r.get("raw_char_count"),
            }
            for r in (rows or [])
        ],
        "count": len(rows or []),
    }


# ── Single Record Lookup ─────────────────────────────────────────

@router.get("/record/{source_id}")
async def get_intelligence(
    source_id: str,
    tenant_id: str = Depends(get_tenant_id),
):
    """Get distilled intelligence for a specific source record."""
    row = await fetch_one(
        """SELECT id, source_type, source_id, summary, structured_metadata,
                  model_used, embedding_model, raw_char_count, created_at
           FROM content_intelligence
           WHERE source_id = $1 AND tenant_id = $2""",
        source_id, tenant_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="No intelligence record found")

    metadata = row["structured_metadata"]
    if isinstance(metadata, str):
        metadata = json.loads(metadata)

    return {
        "id": str(row["id"]),
        "source_type": row["source_type"],
        "summary": row["summary"],
        "metadata": metadata,
        "model_used": row.get("model_used"),
        "embedding_model": row.get("embedding_model"),
        "raw_char_count": row.get("raw_char_count"),
        "created_at": str(row["created_at"]) if row.get("created_at") else None,
    }


# ── Stats ─────────────────────────────────────────────────────────

@router.get("/stats")
async def get_intelligence_stats(tenant_id: str = Depends(get_tenant_id)):
    """Get distillation progress and storage savings stats."""
    # Count distilled vs total
    stats = await fetch_one(
        """SELECT
            (SELECT COUNT(*) FROM content_intelligence WHERE tenant_id = $1) as distilled_count,
            (SELECT COUNT(*) FROM competitor_videos
             WHERE tenant_id = $1 AND transcript IS NOT NULL AND transcript != '') as total_with_transcript,
            (SELECT COUNT(*) FROM competitor_videos
             WHERE tenant_id = $1 AND distilled_at IS NULL
               AND transcript IS NOT NULL AND transcript != '') as pending_count,
            (SELECT COALESCE(SUM(raw_char_count), 0) FROM content_intelligence WHERE tenant_id = $1) as total_raw_chars,
            (SELECT COALESCE(SUM(LENGTH(summary)), 0) FROM content_intelligence WHERE tenant_id = $1) as total_summary_chars
        """,
        tenant_id,
    )

    distilled = int(stats.get("distilled_count", 0)) if stats else 0
    total = int(stats.get("total_with_transcript", 0)) if stats else 0
    pending = int(stats.get("pending_count", 0)) if stats else 0
    raw_chars = int(stats.get("total_raw_chars", 0)) if stats else 0
    summary_chars = int(stats.get("total_summary_chars", 0)) if stats else 0

    return {
        "distilled": distilled,
        "total_with_transcript": total,
        "pending": pending,
        "progress_pct": round(distilled / total * 100, 1) if total > 0 else 0,
        "raw_bytes_processed": raw_chars,
        "distilled_bytes": summary_chars,
        "compression_ratio": round(raw_chars / summary_chars, 1) if summary_chars > 0 else 0,
        "estimated_savings_mb": round((raw_chars - summary_chars) / 1_000_000, 2),
    }


# ── Aggregated Insights ──────────────────────────────────────────

@router.get("/insights/topics")
async def get_topic_insights(
    limit: int = Query(default=20, le=100),
    tenant_id: str = Depends(get_tenant_id),
):
    """Aggregate topic distribution across all distilled content."""
    rows = await fetch_all(
        """SELECT
            tag as topic,
            COUNT(*) as count,
            ROUND(AVG(cv.vph)::numeric, 1) as avg_vph
        FROM content_intelligence ci
        JOIN competitor_videos cv ON cv.id = ci.source_id AND cv.tenant_id = ci.tenant_id,
             jsonb_array_elements_text(
                 COALESCE(ci.structured_metadata->'content_dna'->'topic_tags',
                          ci.structured_metadata->'content'->'topic_tags')
             ) as tag
        WHERE ci.tenant_id = $1
          AND ci.source_type = 'competitor_transcript'
        GROUP BY tag
        ORDER BY count DESC
        LIMIT $2""",
        tenant_id, limit,
    )

    return {"topics": [dict(r) for r in (rows or [])]}


@router.get("/insights/hooks")
async def get_hook_insights(
    tenant_id: str = Depends(get_tenant_id),
):
    """Aggregate hook pattern distribution with performance correlation."""
    rows = await fetch_all(
        """SELECT
            COALESCE(
                ci.structured_metadata->'hook_dna'->>'type',
                ci.structured_metadata->'hook'->>'type'
            ) as hook_type,
            COUNT(*) as count,
            ROUND(AVG(cv.vph)::numeric, 1) as avg_vph,
            ROUND(AVG(cv.like_ratio)::numeric, 5) as avg_like_ratio
        FROM content_intelligence ci
        JOIN competitor_videos cv ON cv.id = ci.source_id AND cv.tenant_id = ci.tenant_id
        WHERE ci.tenant_id = $1
          AND ci.source_type = 'competitor_transcript'
          AND COALESCE(
                ci.structured_metadata->'hook_dna'->>'type',
                ci.structured_metadata->'hook'->>'type'
              ) IS NOT NULL
        GROUP BY hook_type
        ORDER BY avg_vph DESC NULLS LAST""",
        tenant_id,
    )

    return {"hooks": [dict(r) for r in (rows or [])]}


@router.get("/insights/thumbnails")
async def get_thumbnail_insights(
    tenant_id: str = Depends(get_tenant_id),
):
    """Aggregate thumbnail visual patterns with performance correlation."""
    # Composition layout breakdown
    layouts = await fetch_all(
        """SELECT
            ci.structured_metadata->'thumbnail_dna'->'composition'->>'layout' as layout,
            COUNT(*) as count,
            ROUND(AVG(cv.vph)::numeric, 1) as avg_vph
        FROM content_intelligence ci
        JOIN competitor_videos cv ON cv.id = ci.source_id AND cv.tenant_id = ci.tenant_id
        WHERE ci.tenant_id = $1
          AND ci.source_type = 'competitor_transcript'
          AND ci.structured_metadata->'thumbnail_dna'->'composition'->>'layout' IS NOT NULL
        GROUP BY layout
        ORDER BY avg_vph DESC NULLS LAST""",
        tenant_id,
    )

    # Face emotion breakdown
    emotions = await fetch_all(
        """SELECT
            ci.structured_metadata->'thumbnail_dna'->>'face_emotion' as emotion,
            COUNT(*) as count,
            ROUND(AVG(cv.vph)::numeric, 1) as avg_vph
        FROM content_intelligence ci
        JOIN competitor_videos cv ON cv.id = ci.source_id AND cv.tenant_id = ci.tenant_id
        WHERE ci.tenant_id = $1
          AND ci.source_type = 'competitor_transcript'
          AND ci.structured_metadata->'thumbnail_dna'->>'face_emotion' IS NOT NULL
          AND ci.structured_metadata->'thumbnail_dna'->>'face_emotion' != 'none'
        GROUP BY emotion
        ORDER BY avg_vph DESC NULLS LAST""",
        tenant_id,
    )

    # Face present vs not
    face_stats = await fetch_all(
        """SELECT
            (ci.structured_metadata->'thumbnail_dna'->>'face_present')::boolean as face_present,
            COUNT(*) as count,
            ROUND(AVG(cv.vph)::numeric, 1) as avg_vph
        FROM content_intelligence ci
        JOIN competitor_videos cv ON cv.id = ci.source_id AND cv.tenant_id = ci.tenant_id
        WHERE ci.tenant_id = $1
          AND ci.source_type = 'competitor_transcript'
          AND ci.structured_metadata->'thumbnail_dna'->>'face_present' IS NOT NULL
        GROUP BY face_present
        ORDER BY avg_vph DESC NULLS LAST""",
        tenant_id,
    )

    # Overall style breakdown
    styles = await fetch_all(
        """SELECT
            ci.structured_metadata->'thumbnail_dna'->>'overall_style' as style,
            COUNT(*) as count,
            ROUND(AVG(cv.vph)::numeric, 1) as avg_vph
        FROM content_intelligence ci
        JOIN competitor_videos cv ON cv.id = ci.source_id AND cv.tenant_id = ci.tenant_id
        WHERE ci.tenant_id = $1
          AND ci.source_type = 'competitor_transcript'
          AND ci.structured_metadata->'thumbnail_dna'->>'overall_style' IS NOT NULL
        GROUP BY style
        ORDER BY avg_vph DESC NULLS LAST""",
        tenant_id,
    )

    return {
        "layouts": [dict(r) for r in (layouts or [])],
        "face_emotions": [dict(r) for r in (emotions or [])],
        "face_present": [dict(r) for r in (face_stats or [])],
        "styles": [dict(r) for r in (styles or [])],
    }


@router.get("/insights/timing")
async def get_timing_insights(
    tenant_id: str = Depends(get_tenant_id),
):
    """Analyze best publish days and hours based on competitor performance."""
    # Best days
    days = await fetch_all(
        """SELECT
            published_day_of_week as day,
            COUNT(*) as count,
            ROUND(AVG(vph)::numeric, 1) as avg_vph,
            ROUND(AVG(like_ratio)::numeric, 5) as avg_like_ratio
        FROM competitor_videos
        WHERE tenant_id = $1
          AND published_day_of_week IS NOT NULL
          AND vph > 0
        GROUP BY published_day_of_week
        ORDER BY published_day_of_week""",
        tenant_id,
    )

    # Best hours
    hours = await fetch_all(
        """SELECT
            published_hour as hour,
            COUNT(*) as count,
            ROUND(AVG(vph)::numeric, 1) as avg_vph
        FROM competitor_videos
        WHERE tenant_id = $1
          AND published_hour IS NOT NULL
          AND vph > 0
        GROUP BY published_hour
        ORDER BY published_hour""",
        tenant_id,
    )

    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    return {
        "by_day": [
            {**dict(r), "day_name": day_names[r["day"]] if r.get("day") is not None else "Unknown"}
            for r in (days or [])
        ],
        "by_hour": [dict(r) for r in (hours or [])],
    }


@router.get("/insights/virality")
async def get_virality_insights(
    limit: int = Query(default=20, le=100),
    tenant_id: str = Depends(get_tenant_id),
):
    """Find videos that went viral (high views_per_sub_ratio) and their DNA."""
    rows = await fetch_all(
        """SELECT
            cv.id, cv.title, cv.channel, cv.views, cv.vph,
            cv.views_per_sub_ratio, cv.channel_subscriber_count,
            cv.like_ratio, cv.comment_ratio, cv.thumbnail_url,
            ci.summary,
            ci.structured_metadata->'hook_dna'->>'type' as hook_type,
            ci.structured_metadata->'content_dna'->>'tone' as tone,
            ci.structured_metadata->'thumbnail_dna'->'composition'->>'layout' as thumb_layout,
            ci.structured_metadata->'title_dna'->>'structure' as title_structure
        FROM competitor_videos cv
        LEFT JOIN content_intelligence ci
            ON ci.source_id = cv.id AND ci.tenant_id = cv.tenant_id
            AND ci.source_type = 'competitor_transcript'
        WHERE cv.tenant_id = $1
          AND cv.views_per_sub_ratio IS NOT NULL
          AND cv.views_per_sub_ratio > 1.0
        ORDER BY cv.views_per_sub_ratio DESC
        LIMIT $2""",
        tenant_id, limit,
    )

    return {
        "viral_videos": [dict(r) for r in (rows or [])],
        "count": len(rows or []),
    }
