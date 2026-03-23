"""Video CRUD + stage transitions."""

import json
from fastapi import APIRouter, Depends, HTTPException, Query
from auth import get_tenant_id
from models import VideoSummary, VideoDetail, STAGE_ORDER, PIPELINE_STAGES
from database import fetch_all, fetch_one, execute
from typing import Optional, Any


def _parse_json_field(val: Any) -> Optional[dict]:
    """Parse a JSON field that might be string or dict."""
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"_parse_json_field called with type={type(val)}, val[:100]={str(val)[:100] if val else None}")

    if val is None:
        logger.info("Returning None (input was None)")
        return None
    if isinstance(val, dict):
        logger.info("Returning dict (input was already dict)")
        return val
    if isinstance(val, str):
        try:
            result = json.loads(val)
            logger.info(f"Parsed string to dict, result type={type(result)}")
            return result
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"JSON parse failed: {e}")
            return None
    logger.info(f"Returning None (input was unexpected type: {type(val)})")
    return None

router = APIRouter(prefix="/api/videos", tags=["videos"])


def _next_stage(current: str) -> Optional[str]:
    """Get the next pipeline stage."""
    keys = [s["key"] for s in PIPELINE_STAGES]
    try:
        idx = keys.index(current)
        return keys[idx + 1] if idx + 1 < len(keys) else None
    except ValueError:
        return None


@router.get("", response_model=list[VideoSummary])
async def list_videos(
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=100),
    offset: int = Query(0),
    tenant_id: str = Depends(get_tenant_id),
):
    """List videos with optional status filter."""
    if status:
        rows = await fetch_all(
            """SELECT id, video_title, status, thumbnail_url, accent_color, total_cost, views, ctr,
                      created_at::text, updated_at::text
               FROM videos WHERE tenant_id = $1 AND status = $2
               ORDER BY updated_at DESC LIMIT $3 OFFSET $4""",
            tenant_id, status, limit, offset,
        )
    else:
        rows = await fetch_all(
            """SELECT id, video_title, status, thumbnail_url, accent_color, total_cost, views, ctr,
                      created_at::text, updated_at::text
               FROM videos WHERE tenant_id = $1
               ORDER BY updated_at DESC LIMIT $2 OFFSET $3""",
            tenant_id, limit, offset,
        )

    return [
        VideoSummary(
            id=str(r["id"]),
            video_title=r.get("video_title"),
            status=r.get("status"),
            thumbnail_url=r.get("thumbnail_url"),
            accent_color=r.get("accent_color", "#00D4AA"),
            total_cost=float(r.get("total_cost") or 0),
            views=r.get("views") or 0,
            ctr=float(r["ctr"]) if r.get("ctr") else None,
            created_at=r.get("created_at"),
            updated_at=r.get("updated_at"),
        )
        for r in rows
    ]


@router.get("/{video_id}", response_model=VideoDetail)
async def get_video(video_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Get full video detail."""
    r = await fetch_one(
        """SELECT id, video_title, status, airtable_record_id, headline, source,
                  framework_angle, thematic_framework, hook_script, past_context,
                  present_parallel, future_prediction, writer_guidance, thesis, executive_hook,
                  research_payload, original_dna, script, story_bible,
                  thumbnail_url, thumbnail_prompt, thumbnail_style_override,
                  accent_color, visual_style, image_style_override, video_length_minutes,
                  youtube_url, total_cost, views, ctr, avg_retention,
                  impressions, likes, comments, performance_verdict,
                  created_at::text, updated_at::text
           FROM videos WHERE id = $1 AND tenant_id = $2""",
        video_id, tenant_id,
    )
    if not r:
        raise HTTPException(status_code=404, detail="Video not found")

    return VideoDetail(
        id=str(r["id"]),
        video_title=r.get("video_title"),
        status=r.get("status"),
        airtable_record_id=r.get("airtable_record_id"),
        headline=r.get("headline"),
        source=r.get("source"),
        framework_angle=r.get("framework_angle"),
        thematic_framework=r.get("thematic_framework"),
        hook_script=r.get("hook_script"),
        past_context=r.get("past_context"),
        present_parallel=r.get("present_parallel"),
        future_prediction=r.get("future_prediction"),
        writer_guidance=r.get("writer_guidance"),
        thesis=r.get("thesis"),
        executive_hook=r.get("executive_hook"),
        research_payload=_parse_json_field(r.get("research_payload")),
        original_dna=_parse_json_field(r.get("original_dna")),
        script=r.get("script"),
        story_bible=r.get("story_bible"),
        thumbnail_url=r.get("thumbnail_url"),
        thumbnail_prompt=r.get("thumbnail_prompt"),
        thumbnail_style_override=r.get("thumbnail_style_override"),
        accent_color=r.get("accent_color", "#00D4AA"),
        visual_style=r.get("visual_style"),
        image_style_override=r.get("image_style_override"),
        video_length_minutes=float(r["video_length_minutes"]) if r.get("video_length_minutes") else None,
        youtube_url=r.get("youtube_url"),
        total_cost=float(r.get("total_cost") or 0),
        views=r.get("views") or 0,
        ctr=float(r["ctr"]) if r.get("ctr") else None,
        avg_retention=float(r["avg_retention"]) if r.get("avg_retention") else None,
        impressions=r.get("impressions") or 0,
        likes=r.get("likes") or 0,
        comments=r.get("comments") or 0,
        performance_verdict=r.get("performance_verdict"),
        created_at=r.get("created_at"),
        updated_at=r.get("updated_at"),
    )


@router.patch("/{video_id}/advance")
async def advance_video(video_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Move video to the next pipeline stage."""
    video = await fetch_one(
        "SELECT id, status FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    next_status = _next_stage(video["status"])
    if not next_status:
        raise HTTPException(status_code=400, detail="Video is already at final stage")

    await execute(
        "UPDATE videos SET status = $1, updated_at = now() WHERE id = $2",
        next_status, video_id,
    )

    # Log transition
    await execute(
        """INSERT INTO stage_transitions (video_id, tenant_id, from_status, to_status, triggered_by)
           VALUES ($1, $2, $3, $4, 'user')""",
        video_id, tenant_id, video["status"], next_status,
    )

    return {"status": next_status, "previous": video["status"]}


@router.patch("/{video_id}/reject")
async def reject_video(video_id: str, reason: Optional[str] = None, tenant_id: str = Depends(get_tenant_id)):
    """Flag/reject a video."""
    video = await fetch_one(
        "SELECT id, status FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    # Log transition with error
    await execute(
        """INSERT INTO stage_transitions (video_id, tenant_id, from_status, to_status, triggered_by, error_message)
           VALUES ($1, $2, $3, 'rejected', 'user', $4)""",
        video_id, tenant_id, video["status"], reason,
    )

    return {"status": "rejected", "previous": video["status"]}


@router.get("/{video_id}/assets")
async def get_video_assets(video_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Get all assets for a video."""
    rows = await fetch_all(
        """SELECT id, video_id, scene, image_index, image_url, image_prompt,
                  status, shot_type, hero_shot, sentence_text, video_clip_url,
                  created_at::text
           FROM assets WHERE video_id = $1 AND tenant_id = $2
           ORDER BY scene, image_index""",
        video_id, tenant_id,
    )
    return rows


@router.get("/{video_id}/script")
async def get_video_script(video_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Get full script for a video."""
    rows = await fetch_all(
        """SELECT id, video_id, scene, scene_text, voice_over_url, voice_status,
                  script_status, sources, storyboard_on_off,
                  created_at::text
           FROM scripts WHERE video_id = $1 AND tenant_id = $2
           ORDER BY scene""",
        video_id, tenant_id,
    )
    return rows
