"""Content Intelligence API — semantic search, backfill, and distilled insights.

Endpoints:
  POST /api/intelligence/backfill          — Process existing transcripts
  GET  /api/intelligence/search            — Semantic similarity search
  GET  /api/intelligence/stats             — Distillation progress stats
  GET  /api/intelligence/{source_id}       — Get distilled intelligence for a source
  GET  /api/intelligence/insights/topics   — Top topics across distilled content
  GET  /api/intelligence/insights/hooks    — Hook pattern distribution
"""

import json
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
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
                ON ci.source_id = cv.id AND ci.source_table = 'competitor_videos'
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
            ROUND(AVG((
                SELECT cv.vph FROM competitor_videos cv WHERE cv.id = ci.source_id
            ))::numeric, 1) as avg_vph
        FROM content_intelligence ci,
             jsonb_array_elements_text(ci.structured_metadata->'content'->'topic_tags') as tag
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
            ci.structured_metadata->'hook'->>'type' as hook_type,
            COUNT(*) as count,
            ROUND(AVG((
                SELECT cv.vph FROM competitor_videos cv WHERE cv.id = ci.source_id
            ))::numeric, 1) as avg_vph
        FROM content_intelligence ci
        WHERE ci.tenant_id = $1
          AND ci.source_type = 'competitor_transcript'
          AND ci.structured_metadata->'hook'->>'type' IS NOT NULL
        GROUP BY ci.structured_metadata->'hook'->>'type'
        ORDER BY avg_vph DESC NULLS LAST""",
        tenant_id,
    )

    return {"hooks": [dict(r) for r in (rows or [])]}
