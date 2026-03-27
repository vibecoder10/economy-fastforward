"""Video CRUD + stage transitions."""

import json
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from auth import get_tenant_id
from models import (
    VideoSummary, VideoDetail, STAGE_ORDER, PIPELINE_STAGES,
    SceneTextUpdate, SceneToneUpdate, SegmentUpdate, StoryboardModeUpdate,
    CreateVideoRequest,
)
from database import fetch_all, fetch_one, execute
from typing import Optional, Any


def _parse_json_field(val: Any) -> Optional[dict]:
    """Parse a JSON field that might be string or dict.

    Handles double-encoded JSON (JSON string inside JSON string) which can happen
    when data is stored as text in PostgreSQL but was originally JSON.
    """
    if val is None:
        return None
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            result = json.loads(val)
            # Handle double-encoded JSON - if result is still a string, parse again
            if isinstance(result, str):
                result = json.loads(result)
            if isinstance(result, dict):
                return result
            return None
        except (json.JSONDecodeError, ValueError):
            return None
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


@router.post("", response_model=VideoSummary)
async def create_video(
    body: CreateVideoRequest,
    tenant_id: str = Depends(get_tenant_id),
):
    """Create a new video idea."""
    from routes.projects import _get_or_create_project

    project = await _get_or_create_project(tenant_id)
    project_id = str(project["id"])

    row = await fetch_one(
        """INSERT INTO videos (tenant_id, project_id, video_title, status, source, framework_angle, video_length_minutes, accent_color)
           VALUES ($1, $2, $3, 'idea_logged', $4, $5, $6, '#00D4AA')
           RETURNING id, video_title, status, thumbnail_url, accent_color, total_cost, views, ctr,
                     created_at::text, updated_at::text""",
        tenant_id, project_id, body.title.strip(), body.source_url, body.framework_angle,
        body.video_length_minutes,
    )

    return VideoSummary(
        id=str(row["id"]),
        video_title=row.get("video_title"),
        status=row.get("status"),
        thumbnail_url=row.get("thumbnail_url"),
        accent_color=row.get("accent_color", "#00D4AA"),
        total_cost=float(row.get("total_cost") or 0),
        views=row.get("views") or 0,
        ctr=float(row["ctr"]) if row.get("ctr") else None,
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


@router.get("/{video_id}", response_model=VideoDetail)
async def get_video(video_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Get full video detail."""
    r = await fetch_one(
        """SELECT id, video_title, status, airtable_record_id, headline, source,
                  framework_angle, thematic_framework, hook_script, past_context,
                  present_parallel, future_prediction, writer_guidance, thesis, executive_hook,
                  research_payload, original_dna, script, story_bible,
                  thumbnail_url, thumbnail_prompt, thumbnail_style_override,
                  accent_color, visual_style, image_style_override, image_model_override,
                  video_length_minutes, youtube_url, total_cost, views, ctr, avg_retention,
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
        image_model_override=r.get("image_model_override"),
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


@router.patch("/{video_id}")
async def update_video(video_id: str, body: dict, tenant_id: str = Depends(get_tenant_id)):
    """Update arbitrary video fields (revision_notes, etc.)."""
    video = await fetch_one(
        "SELECT id FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    allowed_fields = {"revision_notes", "video_title", "headline", "thumbnail_prompt", "thumbnail_style_override"}
    updates = []
    params = []
    idx = 1
    for key, val in body.items():
        if key in allowed_fields:
            updates.append(f"{key} = ${idx}")
            params.append(val)
            idx += 1
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    updates.append("updated_at = now()")
    params.append(video_id)
    query = f"UPDATE videos SET {', '.join(updates)} WHERE id = ${idx}"
    await execute(query, *params)
    return {"status": "updated", "video_id": video_id}


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
                  sound_prompt, sound_effect_url, sound_volume,
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
                  script_status, sources, storyboard_on_off, tone,
                  storyboard_1_url, storyboard_2_url, storyboard_3_url,
                  storyboard_prompts, storyboard_beat_count, storyboard_status,
                  created_at::text
           FROM scripts WHERE video_id = $1 AND tenant_id = $2
           ORDER BY scene NULLS FIRST, created_at""",
        video_id, tenant_id,
    )
    # Backfill scene numbers when null (Airtable imports don't always set them)
    for i, row in enumerate(rows):
        if row.get("scene") is None:
            row["scene"] = i + 1
    return rows


@router.get("/{video_id}/audio/{scene}")
async def get_scene_audio(video_id: str, scene: int, token: Optional[str] = None):
    """Proxy audio from Google Drive for browser playback.

    Google Drive download URLs use 303 redirects that some browsers
    block in Audio elements. This endpoint streams the audio directly.
    Uses query token since HTML Audio elements can't set Authorization headers.
    """
    import os
    # Simple auth: in dev mode accept dev-token; in prod would validate JWT
    tenant_id = os.getenv("DEV_TENANT_ID", "test-tenant")

    row = await fetch_one(
        "SELECT voice_over_url FROM scripts WHERE video_id = $1 AND tenant_id = $2 AND scene = $3 LIMIT 1",
        video_id, tenant_id, scene,
    )
    if not row or not row.get("voice_over_url"):
        raise HTTPException(status_code=404, detail="No voice audio for this scene")

    url = row["voice_over_url"]

    async def stream():
        async with httpx.AsyncClient(follow_redirects=True) as client:
            async with client.stream("GET", url, timeout=60.0) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes(8192):
                    yield chunk

    return StreamingResponse(stream(), media_type="audio/mpeg", headers={
        "Accept-Ranges": "bytes",
        "Cache-Control": "public, max-age=86400",
    })


@router.patch("/{video_id}/styles")
async def update_video_styles(
    video_id: str,
    visual_style: Optional[str] = None,
    accent_color: Optional[str] = None,
    image_model_override: Optional[str] = None,
    tenant_id: str = Depends(get_tenant_id),
):
    """Update video style override fields."""
    # Verify video exists and belongs to tenant
    video = await fetch_one(
        "SELECT id FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    # Build dynamic update query
    updates = []
    params = []
    param_idx = 1

    if visual_style is not None:
        updates.append(f"visual_style = ${param_idx}")
        params.append(visual_style)
        param_idx += 1

    if accent_color is not None:
        updates.append(f"accent_color = ${param_idx}")
        params.append(accent_color)
        param_idx += 1

    if image_model_override is not None:
        updates.append(f"image_model_override = ${param_idx}")
        params.append(image_model_override)
        param_idx += 1

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    # Add updated_at and video_id
    updates.append("updated_at = now()")
    params.append(video_id)

    query = f"UPDATE videos SET {', '.join(updates)} WHERE id = ${param_idx}"
    await execute(query, *params)

    return {
        "status": "updated",
        "video_id": video_id,
        "updated_fields": {
            "visual_style": visual_style,
            "accent_color": accent_color,
            "image_model_override": image_model_override,
        },
    }


@router.post("/{video_id}/accept-suggestion")
async def accept_suggestion(video_id: str, request: dict, tenant_id: str = Depends(get_tenant_id)):
    """Accept agent suggestions — copies selected suggested_* fields to current fields."""
    accept_fields = request.get("accept", [])  # ["script", "title", "thumbnail"]

    # Verify video exists and belongs to tenant
    video = await fetch_one(
        "SELECT id FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    # Build SET clauses dynamically based on what's being accepted
    set_clauses = []
    if "script" in accept_fields:
        set_clauses.append("script = suggested_script")
    if "title" in accept_fields:
        set_clauses.append("video_title = suggested_title")
    if "thumbnail" in accept_fields:
        set_clauses.append("thumbnail_prompt = suggested_thumbnail_prompt")

    if not set_clauses:
        raise HTTPException(status_code=400, detail="No fields specified to accept")

    # Also clear suggestion fields and set status
    set_clauses.extend([
        "suggested_script = NULL",
        "suggested_title = NULL",
        "suggested_thumbnail_prompt = NULL",
        "suggested_thumbnail_urls = NULL",
        "suggestion_source = NULL",
        "suggestion_scores = NULL",
        "suggestion_status = 'accepted'",
        "updated_at = NOW()",
    ])

    query = f"UPDATE videos SET {', '.join(set_clauses)} WHERE id = $1"
    await execute(query, video_id)

    return {"status": "ok", "video_id": video_id, "accepted": accept_fields}


@router.post("/{video_id}/reject-suggestion")
async def reject_suggestion(video_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Reject agent suggestions — clears all suggested_* fields."""
    # Verify video exists and belongs to tenant
    video = await fetch_one(
        "SELECT id FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    await execute("""
        UPDATE videos SET
            suggested_script = NULL,
            suggested_title = NULL,
            suggested_thumbnail_prompt = NULL,
            suggested_thumbnail_urls = NULL,
            suggestion_source = NULL,
            suggestion_scores = NULL,
            suggestion_status = 'rejected',
            updated_at = NOW()
        WHERE id = $1
    """, video_id)

    return {"status": "ok", "video_id": video_id}


@router.patch("/{video_id}/scenes/{scene}/text")
async def update_scene_text(
    video_id: str, scene: int, body: SceneTextUpdate, tenant_id: str = Depends(get_tenant_id)
):
    result = await execute(
        "UPDATE scripts SET scene_text = $1, updated_at = now() "
        "WHERE video_id = $2 AND scene = $3 AND tenant_id = $4",
        body.text, video_id, scene, tenant_id,
    )
    if not result or "UPDATE 0" in result:
        raise HTTPException(404, "Scene not found")
    return {"status": "updated", "scene": scene}


@router.patch("/{video_id}/scenes/{scene}/tone")
async def update_scene_tone(
    video_id: str, scene: int, body: SceneToneUpdate, tenant_id: str = Depends(get_tenant_id)
):
    valid_tones = {"serious", "conversational", "urgent", "concise"}
    if body.tone not in valid_tones:
        raise HTTPException(400, f"Invalid tone. Must be one of: {valid_tones}")
    await execute(
        "UPDATE scripts SET tone = $1, updated_at = now() "
        "WHERE video_id = $2 AND scene = $3 AND tenant_id = $4",
        body.tone, video_id, scene, tenant_id,
    )
    return {"status": "updated", "scene": scene, "tone": body.tone}


@router.get("/{video_id}/scenes/{scene}/segments")
async def get_scene_segments(
    video_id: str, scene: int, tenant_id: str = Depends(get_tenant_id)
):
    rows = await fetch_all(
        "SELECT id, image_index, sentence_text, shot_type, status, "
        "duration_seconds, image_prompt "
        "FROM assets WHERE video_id = $1 AND scene = $2 AND tenant_id = $3 "
        "ORDER BY image_index",
        video_id, scene, tenant_id,
    )
    segments = []
    cumulative_start = 0.0
    for row in rows:
        text = row.get("sentence_text") or ""
        word_count = len(text.split()) if text else 0
        # Use real duration from splitter if available, fall back to WPS estimate
        db_duration = row.get("duration_seconds")
        duration = float(db_duration) if db_duration is not None else round(word_count / 2.5, 1)
        segments.append({
            "id": str(row["id"]),
            "image_index": row.get("image_index"),
            "sentence_text": text,
            "shot_type": row.get("shot_type"),
            "status": row.get("status"),
            "word_count": word_count,
            "duration_seconds": duration,
            "cumulative_start": round(cumulative_start, 1),
            "image_prompt": row.get("image_prompt"),
        })
        cumulative_start += duration
    return {"scene": scene, "segments": segments}


@router.put("/{video_id}/scenes/{scene}/segments")
async def update_scene_segments(
    video_id: str, scene: int, body: SegmentUpdate, tenant_id: str = Depends(get_tenant_id)
):
    updated = 0
    for seg in body.segments:
        result = await execute(
            "UPDATE assets SET sentence_text = $1, updated_at = now() "
            "WHERE video_id = $2 AND scene = $3 AND image_index = $4 AND tenant_id = $5",
            seg["sentence_text"], video_id, scene, seg["image_index"], tenant_id,
        )
        if result and "UPDATE 1" in result:
            updated += 1
    return {"status": "updated", "scene": scene, "updated_count": updated}


@router.patch("/{video_id}/storyboard-mode")
async def update_storyboard_mode(
    video_id: str, body: StoryboardModeUpdate, tenant_id: str = Depends(get_tenant_id)
):
    value = "On" if body.enabled else "Off"
    await execute(
        "UPDATE scripts SET storyboard_on_off = $1, updated_at = now() "
        "WHERE video_id = $2 AND tenant_id = $3",
        value, video_id, tenant_id,
    )
    return {"status": "updated", "storyboard_mode": value}
