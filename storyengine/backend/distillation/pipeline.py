"""Distillation pipeline — orchestrates: raw data → summarize → embed → store.

Full video DNA extraction:
  1. Claude Haiku: transcript → title_dna, hook_dna, content_dna, retention_dna, villain_dna, etc.
  2. Gemini Vision: thumbnail → face, text, colors, composition, clickbait signals
  3. OpenAI: summary + metadata → 1536-dim vector embedding
  4. Store everything in content_intelligence table

Entry points:
  distill_competitor_video(tenant_id, competitor_video_id) — single record (full DNA)
  backfill_competitor_transcripts(tenant_id, batch_size) — bulk processing
"""

import json
import logging
from typing import Optional

from database import fetch_all, fetch_one, execute
from distillation.distiller import distill_full_video_dna
from distillation.embeddings import generate_embedding, EMBEDDING_MODEL

logger = logging.getLogger("storyengine")

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


async def _get_api_keys(tenant_id: str) -> dict:
    """Get all API keys needed for distillation."""
    from vault import get_secret
    return {
        "anthropic": await get_secret("anthropic_api_key", tenant_id),
        "openai": await get_secret("openai_api_key", tenant_id),
        "gemini": await get_secret("gemini_api_key", tenant_id),
    }


async def distill_competitor_video(
    tenant_id: str,
    competitor_video_id: str,
) -> Optional[dict]:
    """Distill a single competitor video into full structured DNA.

    Extracts:
    - Title DNA (structure, curiosity gap, power words)
    - Hook DNA (type, opening line, first open loop)
    - Content DNA (topics, entities, tone, timeliness)
    - Structure DNA (arc, pacing)
    - Retention DNA (first 5 min, open loops, payoff quality)
    - Villain DNA (type, reveal position, stakes)
    - Engagement signals (comment bait, share trigger)
    - Thumbnail DNA (face, text, colors, composition) via Gemini Vision
    - Vector embedding for semantic search
    """
    # Check if already distilled
    existing = await fetch_one(
        """SELECT id FROM content_intelligence
           WHERE tenant_id = $1 AND source_type = 'competitor_transcript' AND source_id = $2""",
        tenant_id, competitor_video_id,
    )
    if existing:
        return {"status": "already_distilled", "id": str(existing["id"])}

    # Fetch the competitor video with ALL fields
    row = await fetch_one(
        """SELECT id, title, channel, views, vph, duration_seconds, transcript,
                  likes, comment_count, channel_subscriber_count,
                  like_ratio, comment_ratio, views_per_sub_ratio,
                  published_day_of_week, published_hour,
                  has_chapters, chapter_count, chapter_titles,
                  tags, description, thumbnail_url
           FROM competitor_videos
           WHERE id = $1 AND tenant_id = $2""",
        competitor_video_id, tenant_id,
    )
    if not row:
        return None

    transcript = row.get("transcript") or ""
    has_transcript = bool(transcript.strip())

    keys = await _get_api_keys(tenant_id)
    if not keys["anthropic"] or not keys["openai"]:
        logger.warning("[Distill] Missing Anthropic/OpenAI keys for tenant %s", tenant_id[:8])
        return None

    raw_char_count = len(transcript)
    metadata = {}
    summary = ""

    # ── Step 1: LLM distillation (transcript → full DNA) ─────────
    if has_transcript:
        day_name = DAY_NAMES[row["published_day_of_week"]] if row.get("published_day_of_week") is not None else "Unknown"

        result = await distill_full_video_dna(
            title=row.get("title", ""),
            channel=row.get("channel", ""),
            views=row.get("views") or 0,
            vph=float(row.get("vph") or 0),
            duration_seconds=row.get("duration_seconds") or 0,
            transcript=transcript,
            api_key=keys["anthropic"],
            likes=row.get("likes") or 0,
            comment_count=row.get("comment_count") or 0,
            channel_subs=row.get("channel_subscriber_count") or 0,
            like_ratio=float(row.get("like_ratio") or 0),
            views_per_sub_ratio=float(row.get("views_per_sub_ratio") or 0),
            published_day=day_name,
            published_hour=row.get("published_hour"),
            has_chapters=row.get("has_chapters", False),
            description=row.get("description", ""),
            tags=row.get("tags", ""),
        )

        if result:
            metadata = result["structured_metadata"]
            summary = result["summary"]
        else:
            logger.error("[Distill] LLM distillation failed for %s", competitor_video_id[:8])

    # ── Step 2: Gemini thumbnail analysis ─────────────────────────
    thumbnail_url = row.get("thumbnail_url")
    if thumbnail_url and keys.get("gemini"):
        try:
            from distillation.thumbnail_analyzer import analyze_thumbnail
            thumb_dna = await analyze_thumbnail(
                thumbnail_url=thumbnail_url,
                title=row.get("title", ""),
                api_key=keys["gemini"],
            )
            if thumb_dna:
                metadata["thumbnail_dna"] = thumb_dna
                # Mark thumbnail as analyzed
                await execute(
                    "UPDATE competitor_videos SET thumbnail_analyzed_at = now() WHERE id = $1 AND tenant_id = $2",
                    competitor_video_id, tenant_id,
                )
        except Exception as e:
            logger.warning("[Distill] Thumbnail analysis failed for %s: %s", competitor_video_id[:8], e)
    elif thumbnail_url and not keys.get("gemini"):
        logger.info("[Distill] Skipping thumbnail analysis — no Gemini key for tenant %s", tenant_id[:8])

    # ── Step 3: Add raw performance context to metadata ───────────
    metadata["performance"] = {
        "views": row.get("views") or 0,
        "vph": float(row.get("vph") or 0),
        "likes": row.get("likes") or 0,
        "comment_count": row.get("comment_count") or 0,
        "like_ratio": float(row.get("like_ratio") or 0) if row.get("like_ratio") else None,
        "comment_ratio": float(row.get("comment_ratio") or 0) if row.get("comment_ratio") else None,
        "views_per_sub_ratio": float(row.get("views_per_sub_ratio") or 0) if row.get("views_per_sub_ratio") else None,
        "duration_seconds": row.get("duration_seconds") or 0,
        "channel_subscriber_count": row.get("channel_subscriber_count") or 0,
    }
    metadata["timing"] = {
        "published_day_of_week": row.get("published_day_of_week"),
        "published_hour": row.get("published_hour"),
        "has_chapters": row.get("has_chapters", False),
        "chapter_count": row.get("chapter_count") or 0,
    }

    # If no transcript but we got thumbnail DNA, still save what we have
    if not summary and not has_transcript:
        if metadata.get("thumbnail_dna"):
            summary = f"No transcript available. Thumbnail analysis for: {row.get('title', 'Unknown')}"
        else:
            return None  # Nothing to save

    # ── Step 4: Generate vector embedding ─────────────────────────
    # Build rich embedding text from all DNA components
    embed_parts = [row.get("title", "")]
    if summary:
        embed_parts.append(summary)
    topics = (metadata.get("content_dna") or {}).get("topic_tags", [])
    if topics:
        embed_parts.append(f"Topics: {', '.join(topics)}")
    tone = (metadata.get("content_dna") or {}).get("tone")
    if tone:
        embed_parts.append(f"Tone: {tone}")
    hook_type = (metadata.get("hook_dna") or {}).get("type")
    if hook_type:
        embed_parts.append(f"Hook: {hook_type}")

    embed_text = ". ".join(embed_parts)
    embedding = await generate_embedding(embed_text, keys["openai"])

    # ── Step 5: Store in content_intelligence ─────────────────────
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
        summary,
        json.dumps(metadata),
        str(embedding) if embedding else None,
        "haiku+gemini",
        EMBEDDING_MODEL if embedding else None,
        raw_char_count,
    )

    # Mark source as distilled
    await execute(
        "UPDATE competitor_videos SET distilled_at = now() WHERE id = $1 AND tenant_id = $2",
        competitor_video_id, tenant_id,
    )

    has_thumb = "thumbnail_dna" in metadata
    logger.info(
        "[Distill] Video %s: %d chars → %d byte summary + vector + %s",
        competitor_video_id[:8],
        raw_char_count,
        len(summary),
        "thumbnail" if has_thumb else "no thumbnail",
    )

    return {
        "status": "distilled",
        "id": str(record["id"]) if record else None,
        "summary_length": len(summary),
        "raw_char_count": raw_char_count,
        "has_embedding": embedding is not None,
        "has_thumbnail_dna": has_thumb,
        "dna_keys": list(metadata.keys()),
    }


# Keep old name as alias for backwards compat with niche.py auto-distill
distill_competitor_transcript = distill_competitor_video


async def backfill_competitor_transcripts(
    tenant_id: str,
    batch_size: int = 50,
) -> dict:
    """Process existing competitor videos that haven't been distilled yet.

    Processes videos with transcripts first (richest data), then videos
    with only thumbnails (still valuable for visual DNA).
    """
    # Find un-distilled videos (prioritize those with transcripts)
    rows = await fetch_all(
        """SELECT id FROM competitor_videos
           WHERE tenant_id = $1
             AND distilled_at IS NULL
             AND (
               (transcript IS NOT NULL AND transcript != '')
               OR thumbnail_url IS NOT NULL
             )
           ORDER BY
             CASE WHEN transcript IS NOT NULL AND transcript != '' THEN 0 ELSE 1 END,
             vph DESC NULLS LAST
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
             AND (
               (transcript IS NOT NULL AND transcript != '')
               OR thumbnail_url IS NOT NULL
             )""",
        tenant_id,
    )
    total_pending = (count_row or {}).get("cnt", 0)

    processed = 0
    failed = 0
    for row in rows:
        try:
            result = await distill_competitor_video(tenant_id, str(row["id"]))
            if result and result.get("status") in ("distilled", "already_distilled"):
                processed += 1
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
