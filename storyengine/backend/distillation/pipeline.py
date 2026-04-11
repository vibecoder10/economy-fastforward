"""Distillation pipeline — orchestrates: raw data → summarize → embed → store.

Entry points:
  distill_competitor_transcript(tenant_id, competitor_video_id) — single record
  backfill_competitor_transcripts(tenant_id, batch_size) — bulk processing
"""

import json
import logging
from typing import Optional

from database import fetch_all, fetch_one, execute
from distillation.distiller import distill_transcript
from distillation.embeddings import generate_embedding, EMBEDDING_MODEL

logger = logging.getLogger("storyengine")


async def _get_api_keys(tenant_id: str) -> tuple[Optional[str], Optional[str]]:
    """Get Anthropic + OpenAI API keys for a tenant."""
    from vault import get_secret
    anthropic_key = await get_secret("anthropic_api_key", tenant_id)
    openai_key = await get_secret("openai_api_key", tenant_id)
    return anthropic_key, openai_key


async def distill_competitor_transcript(
    tenant_id: str,
    competitor_video_id: str,
) -> Optional[dict]:
    """Distill a single competitor video transcript into structured intelligence.

    Returns the created content_intelligence record, or None if:
    - No transcript available
    - Already distilled
    - API keys missing
    - Distillation fails
    """
    # Check if already distilled
    existing = await fetch_one(
        """SELECT id FROM content_intelligence
           WHERE tenant_id = $1 AND source_type = 'competitor_transcript' AND source_id = $2""",
        tenant_id, competitor_video_id,
    )
    if existing:
        return {"status": "already_distilled", "id": str(existing["id"])}

    # Fetch the competitor video
    row = await fetch_one(
        """SELECT id, title, channel, views, vph, duration_seconds, transcript
           FROM competitor_videos
           WHERE id = $1 AND tenant_id = $2""",
        competitor_video_id, tenant_id,
    )
    if not row or not row.get("transcript"):
        return None

    anthropic_key, openai_key = await _get_api_keys(tenant_id)
    if not anthropic_key or not openai_key:
        logger.warning("[Distill] Missing API keys for tenant %s", tenant_id[:8])
        return None

    transcript = row["transcript"]
    raw_char_count = len(transcript)

    # Step 1: LLM distillation → structured metadata
    result = await distill_transcript(
        title=row.get("title", ""),
        channel=row.get("channel", ""),
        views=row.get("views") or 0,
        vph=float(row.get("vph") or 0),
        duration_seconds=row.get("duration_seconds") or 0,
        transcript=transcript,
        api_key=anthropic_key,
    )
    if not result:
        logger.error("[Distill] LLM distillation failed for %s", competitor_video_id)
        return None

    # Step 2: Generate embedding from summary + key metadata
    embed_text = f"{row.get('title', '')}. {result['summary']}"
    # Include topic tags for richer semantic matching
    metadata = result["structured_metadata"]
    topics = metadata.get("content", {}).get("topic_tags", [])
    if topics:
        embed_text += f" Topics: {', '.join(topics)}"

    embedding = await generate_embedding(embed_text, openai_key)

    # Step 3: Store in content_intelligence table
    record = await fetch_one(
        """INSERT INTO content_intelligence (
            tenant_id, source_type, source_id, source_table,
            summary, structured_metadata, embedding,
            model_used, embedding_model, raw_char_count
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        ON CONFLICT (tenant_id, source_type, source_id) DO UPDATE SET
            summary = EXCLUDED.summary,
            structured_metadata = EXCLUDED.structured_metadata,
            embedding = EXCLUDED.embedding,
            model_used = EXCLUDED.model_used,
            raw_char_count = EXCLUDED.raw_char_count,
            created_at = now()
        RETURNING id""",
        tenant_id,
        "competitor_transcript",
        competitor_video_id,
        "competitor_videos",
        result["summary"],
        json.dumps(metadata),
        str(embedding) if embedding else None,
        result["model_used"],
        EMBEDDING_MODEL if embedding else None,
        raw_char_count,
    )

    # Mark source as distilled
    await execute(
        "UPDATE competitor_videos SET distilled_at = now() WHERE id = $1 AND tenant_id = $2",
        competitor_video_id, tenant_id,
    )

    logger.info(
        "[Distill] Competitor transcript %s: %d chars → %d byte summary + vector",
        competitor_video_id[:8],
        raw_char_count,
        len(result["summary"]),
    )

    return {
        "status": "distilled",
        "id": str(record["id"]) if record else None,
        "summary_length": len(result["summary"]),
        "raw_char_count": raw_char_count,
        "has_embedding": embedding is not None,
    }


async def backfill_competitor_transcripts(
    tenant_id: str,
    batch_size: int = 50,
) -> dict:
    """Process existing competitor transcripts that haven't been distilled yet.

    Returns summary of processing results.
    """
    # Find un-distilled transcripts
    rows = await fetch_all(
        """SELECT id FROM competitor_videos
           WHERE tenant_id = $1
             AND distilled_at IS NULL
             AND transcript IS NOT NULL
             AND transcript != ''
           ORDER BY vph DESC NULLS LAST
           LIMIT $2""",
        tenant_id, batch_size,
    )

    if not rows:
        return {"status": "no_pending", "processed": 0, "total_pending": 0}

    # Count total pending
    count_row = await fetch_one(
        """SELECT COUNT(*) as cnt FROM competitor_videos
           WHERE tenant_id = $1
             AND distilled_at IS NULL
             AND transcript IS NOT NULL
             AND transcript != ''""",
        tenant_id,
    )
    total_pending = (count_row or {}).get("cnt", 0)

    processed = 0
    failed = 0
    for row in rows:
        try:
            result = await distill_competitor_transcript(tenant_id, str(row["id"]))
            if result and result.get("status") == "distilled":
                processed += 1
            elif result and result.get("status") == "already_distilled":
                processed += 1  # Count as success
            else:
                failed += 1
        except Exception as e:
            logger.error("[Distill] Failed for %s: %s", str(row["id"])[:8], e)
            failed += 1

    return {
        "status": "completed",
        "processed": processed,
        "failed": failed,
        "total_pending": total_pending - processed,
        "batch_size": batch_size,
    }
