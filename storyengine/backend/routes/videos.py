"""Video CRUD + stage transitions."""

import asyncio
import json
import logging
import re
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from auth import get_tenant_id
from models import (
    VideoSummary, VideoDetail, STAGE_ORDER, PIPELINE_STAGES,
    SceneTextUpdate, SceneToneUpdate, SegmentUpdate, StoryboardModeUpdate,
    CreateVideoRequest,
)
from database import fetch_all, fetch_one, execute, safe_column
from error_utils import humanize_error
from status_map import get_next_status_supabase
from prompt_defaults import VIDEO_MOTION_SYSTEM_PROMPT, SCRIPT_SYSTEM_PROMPT, THUMBNAIL_SYSTEM_PROMPT, SOUND_CURATION_SYSTEM_PROMPT, SOUND_GENERATION_SYSTEM_PROMPT, RESEARCH_SYSTEM_PROMPT
from typing import Optional, Any


def _parse_script_validation(val: Any) -> Optional[str]:
    """Parse script_validation, converting plain-text format to JSON if needed.

    The pipeline stores script_validation as plain text like:
        Editorial validation: PASSED
        [PASS] number_density: 49/19 specific numbers found
        [FAIL] framework_density: 22% framework density

    The frontend expects JSON: {"passed": bool, "checks": [{name, passed, detail}]}
    This function converts the plain text to JSON string so the frontend can parse it.
    If the value is already valid JSON, it passes through unchanged.
    """
    if val is None:
        return None
    if not isinstance(val, str):
        return None
    val = val.strip()
    if not val:
        return None

    # If it's already valid JSON with the expected structure, return as-is
    try:
        parsed = json.loads(val)
        if isinstance(parsed, dict) and "checks" in parsed:
            return val
    except (json.JSONDecodeError, ValueError):
        pass

    # Parse the plain text format
    lines = val.split("\n")
    if not lines:
        return None

    # First line: "Editorial validation: PASSED" or "Editorial validation: FAILED"
    overall_passed = "PASSED" in lines[0].upper() if lines[0] else True

    checks = []
    for line in lines[1:]:
        line = line.strip()
        # Match "[PASS] name: detail" or "[FAIL] name: detail"
        m = re.match(r"\[(PASS|FAIL)\]\s+(\w+):\s*(.*)", line)
        if m:
            checks.append({
                "name": m.group(2),
                "passed": m.group(1) == "PASS",
                "detail": m.group(3),
                "advisory": False,
            })

    if not checks:
        return None

    result = {
        "passed": overall_passed,
        "checks": checks,
        "advisory_warnings": [],
    }
    return json.dumps(result)


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
logger = logging.getLogger(__name__)


def _next_stage(current: str) -> Optional[str]:
    """Get the next pipeline stage.

    Uses the full 18-stage pipeline order from status_map, not the
    abbreviated 10-stage PIPELINE_STAGES used for UI display dots.
    This ensures intermediate statuses (researching, scripting, etc.)
    can still advance correctly.
    """
    return get_next_status_supabase(current)


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
               FROM videos WHERE tenant_id = $1 AND status = $2 AND deleted_at IS NULL
               ORDER BY updated_at DESC LIMIT $3 OFFSET $4""",
            tenant_id, status, limit, offset,
        )
    else:
        rows = await fetch_all(
            """SELECT id, video_title, status, thumbnail_url, accent_color, total_cost, views, ctr,
                      created_at::text, updated_at::text
               FROM videos WHERE tenant_id = $1 AND deleted_at IS NULL
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
            characters_approved_at=r.get("characters_approved_at"),
        story_locked_at=r.get("story_locked_at"),
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
    from routes.billing import check_plan_limits, increment_usage
    await check_plan_limits(tenant_id, "video")

    from routes.projects import _get_or_create_project

    project = await _get_or_create_project(tenant_id)
    project_id = str(project["id"])

    row = await fetch_one(
        """INSERT INTO videos (tenant_id, project_id, video_title, status, source, framework_angle, video_length_minutes, writer_guidance, visual_style, accent_color)
           VALUES ($1, $2, $3, 'idea_logged', $4, $5, $6, $7, $8, COALESCE($9, '#00D4AA'))
           RETURNING id, video_title, status, thumbnail_url, accent_color, total_cost, views, ctr,
                     created_at::text, updated_at::text""",
        tenant_id, project_id, body.title.strip(), body.source_url, body.framework_angle,
        body.video_length_minutes, body.writer_guidance, body.visual_style, body.accent_color,
    )

    await increment_usage(tenant_id, "videos_created")

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
                  research_payload, original_dna, script, script_validation, story_bible,
                  thumbnail_url, thumbnail_prompt, thumbnail_style_override,
                  accent_color, visual_style, image_style_override, image_model_override, video_model,
                  video_length_minutes, youtube_url, final_video_url, total_cost, views, ctr, avg_retention,
                  impressions, likes, comments, performance_verdict,
                  source_views, source_channel, source_urls,
                  views_24h, views_48h, views_7d, views_30d,
                  ctr_12h, ctr_24h, ctr_48h, retention_48h,
                  post_mortem_48h, post_mortem_7d,
                  agent_paper_trail, agent_hook_score, agent_body_score, agent_tier, agent_cost,
                  suggested_thumbnail_prompt, suggested_thumbnail_urls,
                  suggested_script, suggested_title, suggestion_source,
                  suggestion_scores, suggestion_status,
                  video_motion_system_prompt,
                  script_system_prompt, thumbnail_system_prompt, sound_system_prompt,
                  characters_approved_at::text, story_locked_at::text,
                  created_at::text, updated_at::text
           FROM videos WHERE id = $1 AND tenant_id = $2 AND deleted_at IS NULL""",
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
        script_validation=_parse_script_validation(r.get("script_validation")),
        story_bible=r.get("story_bible"),
        thumbnail_url=r.get("thumbnail_url"),
        thumbnail_prompt=r.get("thumbnail_prompt"),
        thumbnail_style_override=r.get("thumbnail_style_override"),
        accent_color=r.get("accent_color", "#00D4AA"),
        visual_style=r.get("visual_style"),
        image_style_override=r.get("image_style_override"),
        image_model_override=r.get("image_model_override"),
        video_model=r.get("video_model"),
        video_length_minutes=float(r["video_length_minutes"]) if r.get("video_length_minutes") else None,
        youtube_url=r.get("youtube_url"),
        final_video_url=r.get("final_video_url"),
        total_cost=float(r.get("total_cost") or 0),
        views=r.get("views") or 0,
        ctr=float(r["ctr"]) if r.get("ctr") else None,
        avg_retention=float(r["avg_retention"]) if r.get("avg_retention") else None,
        impressions=r.get("impressions") or 0,
        likes=r.get("likes") or 0,
        comments=r.get("comments") or 0,
        performance_verdict=r.get("performance_verdict"),
        source_views=r.get("source_views"),
        source_channel=r.get("source_channel"),
        source_urls=r.get("source_urls"),
        views_24h=r.get("views_24h"),
        views_48h=r.get("views_48h"),
        views_7d=r.get("views_7d"),
        views_30d=r.get("views_30d"),
        ctr_12h=float(r["ctr_12h"]) if r.get("ctr_12h") else None,
        ctr_24h=float(r["ctr_24h"]) if r.get("ctr_24h") else None,
        ctr_48h=float(r["ctr_48h"]) if r.get("ctr_48h") else None,
        retention_48h=float(r["retention_48h"]) if r.get("retention_48h") else None,
        post_mortem_48h=r.get("post_mortem_48h"),
        post_mortem_7d=r.get("post_mortem_7d"),
        agent_paper_trail=_parse_json_field(r.get("agent_paper_trail")),
        agent_hook_score=float(r["agent_hook_score"]) if r.get("agent_hook_score") else None,
        agent_body_score=float(r["agent_body_score"]) if r.get("agent_body_score") else None,
        agent_tier=r.get("agent_tier"),
        agent_cost=float(r["agent_cost"]) if r.get("agent_cost") else None,
        suggested_thumbnail_prompt=r.get("suggested_thumbnail_prompt"),
        suggested_thumbnail_urls=_parse_json_field(r.get("suggested_thumbnail_urls")),
        suggested_script=r.get("suggested_script"),
        suggested_title=r.get("suggested_title"),
        suggestion_source=r.get("suggestion_source"),
        suggestion_scores=_parse_json_field(r.get("suggestion_scores")),
        suggestion_status=r.get("suggestion_status"),
        video_motion_system_prompt=r.get("video_motion_system_prompt"),
        script_system_prompt=r.get("script_system_prompt"),
        thumbnail_system_prompt=r.get("thumbnail_system_prompt"),
        sound_system_prompt=r.get("sound_system_prompt"),
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

    allowed_fields = {"revision_notes", "video_title", "headline", "thumbnail_prompt", "thumbnail_style_override", "video_motion_system_prompt", "script_system_prompt", "thumbnail_system_prompt", "sound_system_prompt"}
    updates = []
    params = []
    idx = 1
    for key, val in body.items():
        if key in allowed_fields:
            updates.append(f"{safe_column(key)} = ${idx}")
            params.append(val)
            idx += 1
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    updates.append("updated_at = now()")
    params.append(video_id)
    idx += 1
    params.append(tenant_id)
    # SECURITY: column names filtered through allowed_fields allowlist + safe_column(), values use $N params
    query = f"UPDATE videos SET {', '.join(updates)} WHERE id = ${idx - 1} AND tenant_id = ${idx}"
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
        "UPDATE videos SET status = $1, updated_at = now() WHERE id = $2 AND tenant_id = $3",
        next_status, video_id, tenant_id,
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


@router.delete("/{video_id}")
async def delete_video(video_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Soft-delete a video by setting deleted_at timestamp."""
    video = await fetch_one(
        "SELECT id FROM videos WHERE id = $1 AND tenant_id = $2 AND deleted_at IS NULL",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    await execute(
        "UPDATE videos SET deleted_at = now(), updated_at = now() WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    return {"status": "deleted", "video_id": video_id}


@router.get("/{video_id}/assets")
async def get_video_assets(video_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Get all assets for a video."""
    rows = await fetch_all(
        """SELECT id, video_id, scene, image_index, image_url, image_prompt,
                  status, shot_type, hero_shot, sentence_text, video_clip_url,
                  video_prompt, sound_prompt, sound_effect_url, sound_volume,
                  duration_seconds,
                  created_at::text
           FROM assets WHERE video_id = $1 AND tenant_id = $2
             AND (generation_method IS NULL OR generation_method <> 'variant_candidate')
           ORDER BY scene, image_index""",
        video_id, tenant_id,
    )
    return rows


@router.get("/{video_id}/assets/variants")
async def get_video_asset_variants(
    video_id: str,
    scene: int = Query(...),
    index: int = Query(...),
    tenant_id: str = Depends(get_tenant_id),
):
    """Get variant candidate assets for a specific scene/index."""
    rows = await fetch_all(
        """SELECT id, video_id, scene, image_index, image_url, drive_image_url, image_prompt,
                  status, shot_type, hero_shot, sentence_text, panel_position,
                  generation_method, created_at::text
           FROM assets
           WHERE video_id = $1 AND tenant_id = $2 AND scene = $3 AND image_index = $4
             AND generation_method = 'variant_candidate'
           ORDER BY panel_position, created_at""",
        video_id, tenant_id, scene, index,
    )
    return rows


@router.get("/{video_id}/script")
async def get_video_script(video_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Get full script for a video."""
    rows = await fetch_all(
        """SELECT id, video_id, scene, scene_text, voice_over_url, voice_status,
                  script_status, sources, storyboard_on_off, tone,
                  storyboard_1_url, storyboard_2_url, storyboard_3_url,
                  storyboard_4_url, storyboard_5_url,
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


@router.post("/{video_id}/audio-token")
async def create_audio_token(video_id: str, tenant_id=Depends(get_tenant_id)):
    """Generate a short-lived token for audio playback.

    Returns a 5-minute JWT scoped to this video_id + tenant_id.
    Use this token in ?token= query param for audio endpoints instead
    of exposing the full session JWT in URLs.
    """
    import os
    import jwt as pyjwt
    from datetime import datetime, timedelta, timezone

    session_secret = os.getenv("SESSION_SECRET")
    if not session_secret:
        raise HTTPException(status_code=500, detail="SESSION_SECRET not configured")

    audio_token = pyjwt.encode(
        {
            "purpose": "audio",
            "video_id": video_id,
            "tenant_id": str(tenant_id),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
            "iss": "storyengine",
        },
        session_secret,
        algorithm="HS256",
    )
    return {"token": audio_token}


@router.get("/{video_id}/audio/{scene}")
async def get_scene_audio(video_id: str, scene: int, token: Optional[str] = None):
    """Proxy audio from Google Drive for browser playback.

    Google Drive download URLs use 303 redirects that some browsers
    block in Audio elements. This endpoint streams the audio directly.
    Accepts a short-lived audio token (from POST /audio-token) in ?token= param.
    """
    import os
    import jwt as pyjwt

    # Validate token — required for tenant isolation
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Dev token: only when DEV_MODE=true and DEV_TOKEN env var is set
    dev_token = os.getenv("DEV_TOKEN")
    if dev_token and token == dev_token and os.getenv("DEV_MODE") == "true":
        tenant_id = os.getenv("DEV_TENANT_ID", "test-tenant")
    else:
        # Validate JWT (short-lived audio token or session JWT)
        session_secret = os.getenv("SESSION_SECRET")
        if not session_secret:
            raise HTTPException(status_code=401, detail="Invalid token")
        try:
            payload = pyjwt.decode(token, session_secret, algorithms=["HS256"])
            # Short-lived audio token: verify purpose and video_id scope
            if payload.get("purpose") == "audio":
                if payload.get("video_id") != video_id:
                    raise HTTPException(status_code=403, detail="Token not valid for this video")
                tenant_id = payload.get("tenant_id")
            else:
                tenant_id = payload.get("tenant_id")
            if not tenant_id:
                raise HTTPException(status_code=401, detail="Invalid token: no tenant")
        except pyjwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expired")
        except pyjwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Invalid token")

    row = await fetch_one(
        "SELECT voice_over_url FROM scripts WHERE video_id = $1 AND tenant_id = $2 AND scene = $3 LIMIT 1",
        video_id, tenant_id, scene,
    )
    if not row or not row.get("voice_over_url"):
        raise HTTPException(status_code=404, detail="No voice audio for this scene")

    url = row["voice_over_url"]

    # Drive public links degrade into HTML interstitials (the bytes say
    # 200 audio/mpeg but contain an HTML page — players sit at 0:00/0:00).
    # Same fix as the image proxy: authorized Drive API download.
    file_id = _drive_file_id(url)
    if file_id:
        from routes.media import _download_via_drive_api
        try:
            data = await asyncio.to_thread(_download_via_drive_api, file_id)
        except Exception as e:
            logger.warning("[audio] drive fetch failed for %s: %s", file_id, str(e)[:200])
            raise HTTPException(status_code=502, detail="Couldn't fetch the audio right now.")
        return Response(content=data, media_type="audio/mpeg", headers={
            "Accept-Ranges": "bytes",
            "Cache-Control": "public, max-age=3600",
        })

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
    video_model: Optional[str] = None,
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

    if video_model is not None:
        updates.append(f"video_model = ${param_idx}")
        params.append(video_model)
        param_idx += 1

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    # Add updated_at and video_id + tenant_id
    updates.append("updated_at = now()")
    params.append(video_id)
    params.append(tenant_id)

    # SECURITY: column names are hardcoded per-field conditionals, values use $N params
    query = f"UPDATE videos SET {', '.join(updates)} WHERE id = ${param_idx} AND tenant_id = ${param_idx + 1}"
    await execute(query, *params)

    return {
        "status": "updated",
        "video_id": video_id,
        "updated_fields": {
            "visual_style": visual_style,
            "accent_color": accent_color,
            "image_model_override": image_model_override,
            "video_model": video_model,
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

    # SECURITY: SET clauses are fully hardcoded strings (column = column or NULL/literal), no user input in clause text
    query = f"UPDATE videos SET {', '.join(set_clauses)} WHERE id = $1 AND tenant_id = $2"
    await execute(query, video_id, tenant_id)

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
        WHERE id = $1 AND tenant_id = $2
    """, video_id, tenant_id)

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
        "AND (generation_method IS NULL OR generation_method <> 'variant_candidate') "
        "ORDER BY image_index",
        video_id, scene, tenant_id,
    )
    segments = []
    cumulative_start = 0.0
    for row in rows:
        text = row.get("sentence_text") or ""
        word_count = len(text.split()) if text else 0
        db_duration = row.get("duration_seconds")
        duration = round(float(db_duration), 1) if db_duration is not None else round(word_count / 2.5, 1)
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
            "WHERE video_id = $2 AND scene = $3 AND image_index = $4 AND tenant_id = $5 "
            "AND (generation_method IS NULL OR generation_method <> 'variant_candidate')",
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


@router.post("/{video_id}/lock-story")
async def lock_story(video_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Lock the storyboard: the explicit, reviewed moment before image spend.

    Requires at least one storyboard grid to exist — you can't lock a story
    you haven't seen. Unlocked again via /unlock-story while iterating.
    """
    video = await fetch_one(
        "SELECT id FROM videos WHERE id = $1 AND tenant_id = $2 AND deleted_at IS NULL",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    grids = await fetch_one(
        "SELECT count(*) AS c FROM scripts WHERE video_id = $1 AND tenant_id = $2 "
        "AND (storyboard_1_url IS NOT NULL OR storyboard_2_url IS NOT NULL OR storyboard_3_url IS NOT NULL)",
        video_id, tenant_id,
    )
    if not grids or int(grids.get("c") or 0) == 0:
        raise HTTPException(
            status_code=400,
            detail="Generate storyboard grids first — locking means you've reviewed the boards.",
        )

    await execute(
        "UPDATE videos SET story_locked_at = now(), updated_at = now() "
        "WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    return {"status": "locked"}


@router.post("/{video_id}/unlock-story")
async def unlock_story(video_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Unlock to keep iterating on boards (does not delete anything)."""
    await execute(
        "UPDATE videos SET story_locked_at = NULL, updated_at = now() "
        "WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    return {"status": "unlocked"}


@router.delete("/{video_id}/storyboards")
async def clear_all_storyboards(
    video_id: str,
    tenant_id: str = Depends(get_tenant_id),
):
    """Clear all storyboard prompt/image fields and restore original image prompts."""
    result = await execute(
        """UPDATE scripts
           SET storyboard_prompts = NULL,
               storyboard_beat_count = NULL,
               storyboard_status = NULL,
               storyboard_1_url = NULL,
               storyboard_2_url = NULL,
               storyboard_3_url = NULL,
               storyboard_4_url = NULL,
               storyboard_5_url = NULL,
               updated_at = now()
           WHERE video_id = $1 AND tenant_id = $2""",
        video_id,
        tenant_id,
    )
    # Restore original image prompts (undo storyboard enrichment)
    await execute(
        """UPDATE assets
           SET image_prompt = original_image_prompt,
               updated_at = now()
           WHERE video_id = $1 AND tenant_id = $2
             AND original_image_prompt IS NOT NULL
             AND original_image_prompt != ''""",
        video_id,
        tenant_id,
    )
    return {"status": "cleared", "scope": "all", "video_id": video_id, "result": result}


@router.delete("/{video_id}/storyboards/{scene}")
async def clear_scene_storyboard(
    video_id: str,
    scene: int,
    tenant_id: str = Depends(get_tenant_id),
):
    """Clear storyboard prompt/image fields for a single scene and restore original prompts."""
    result = await execute(
        """UPDATE scripts
           SET storyboard_prompts = NULL,
               storyboard_beat_count = NULL,
               storyboard_status = NULL,
               storyboard_1_url = NULL,
               storyboard_2_url = NULL,
               storyboard_3_url = NULL,
               storyboard_4_url = NULL,
               storyboard_5_url = NULL,
               updated_at = now()
           WHERE video_id = $1 AND scene = $2 AND tenant_id = $3""",
        video_id,
        scene,
        tenant_id,
    )
    if not result or "UPDATE 0" in result:
        raise HTTPException(status_code=404, detail="Scene not found")
    # Restore original image prompts for this scene
    await execute(
        """UPDATE assets
           SET image_prompt = original_image_prompt,
               updated_at = now()
           WHERE video_id = $1 AND scene = $2 AND tenant_id = $3
             AND original_image_prompt IS NOT NULL
             AND original_image_prompt != ''""",
        video_id,
        scene,
        tenant_id,
    )
    return {"status": "cleared", "scope": "scene", "video_id": video_id, "scene": scene}


def _drive_file_id(url: str | None) -> str | None:
    if not url:
        return None
    m = re.search(r"[?&]id=([\w-]+)", url) or re.search(r"/d/([\w-]+)", url)
    return m.group(1) if m else None


def _trash_drive_file(file_id: str) -> None:
    """Move a Drive file to trash (recoverable for 30 days)."""
    import sys
    from pathlib import Path
    pipeline_path = Path(__file__).resolve().parents[3] / "skills" / "video-pipeline"
    if str(pipeline_path) not in sys.path:
        sys.path.insert(0, str(pipeline_path))
    from shared.clients.google_client import GoogleClient
    GoogleClient().drive_service.files().update(
        fileId=file_id, body={"trashed": True}
    ).execute()


@router.delete("/{video_id}/storyboards/{scene}/{beat}")
async def clear_storyboard_slot(
    video_id: str,
    scene: int,
    beat: int,
    tenant_id: str = Depends(get_tenant_id),
):
    """Remove ONE storyboard grid image — prompts and the other boards stay.

    The whole-scene clear wipes prompts too (full redo); this is the X button
    for "just this picture is wrong". The Drive copy is trashed so the folder
    matches what's on screen, and regeneration only fills the empty slot
    (the bot skips beats that already have grids).
    """
    if beat < 1 or beat > 5:
        raise HTTPException(status_code=400, detail="Beat must be 1-5")

    col = f"storyboard_{beat}_url"
    row = await fetch_one(
        f"SELECT id, {col} AS url FROM scripts WHERE video_id = $1 AND scene = $2 AND tenant_id = $3",
        video_id, scene, tenant_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Scene not found")
    if not row.get("url"):
        raise HTTPException(status_code=404, detail="No storyboard image in that slot")

    # Only downgrade the scene status when the removed slot is one of the
    # ACTIVE beats — clearing a stray out-of-range slot shouldn't un-complete
    # a scene whose real boards are all still there.
    await execute(
        f"""UPDATE scripts
            SET {col} = NULL,
                storyboard_status = CASE WHEN storyboard_status = 'grids_generated'
                                          AND $2::int <= COALESCE(storyboard_beat_count, 1)
                                         THEN 'prompts_ready' ELSE storyboard_status END,
                updated_at = now()
            WHERE id = $1""",
        row["id"], beat,
    )

    file_id = _drive_file_id(row["url"])
    if file_id:
        try:
            await asyncio.to_thread(_trash_drive_file, file_id)
        except Exception as e:
            logger.warning("[storyboard] couldn't trash Drive file %s: %s", file_id, str(e)[:200])

    return {"status": "cleared", "scope": "slot", "scene": scene, "beat": beat}


@router.delete("/{video_id}/extracted-panels")
async def clear_all_extracted_panels(
    video_id: str,
    tenant_id: str = Depends(get_tenant_id),
):
    """Clear all extracted panel images, preserving segment rows."""
    result = await execute(
        """UPDATE assets
           SET image_url = NULL, status = 'pending',
               generation_method = NULL, updated_at = now()
           WHERE video_id = $1 AND tenant_id = $2
             AND generation_method = 'storyboard_extract'
             AND image_url IS NOT NULL""",
        video_id,
        tenant_id,
    )
    cleared = int(result.split()[-1]) if result else 0
    return {"status": "cleared", "cleared_count": cleared, "video_id": video_id}


@router.delete("/{video_id}/extracted-panels/{asset_id}")
async def clear_extracted_panel(
    video_id: str,
    asset_id: str,
    tenant_id: str = Depends(get_tenant_id),
):
    """Clear a single extracted panel image, preserving the segment row."""
    result = await execute(
        """UPDATE assets
           SET image_url = NULL, status = 'pending',
               generation_method = NULL, updated_at = now()
           WHERE id = $1 AND video_id = $2 AND tenant_id = $3""",
        asset_id,
        video_id,
        tenant_id,
    )
    if not result or "UPDATE 0" in result:
        raise HTTPException(status_code=404, detail="Asset not found")
    return {"status": "cleared", "asset_id": asset_id}


@router.post("/{video_id}/storyboard-grid-upload")
async def upload_storyboard_grid(
    video_id: str,
    scene: int = Form(...),
    beat: int = Form(...),
    file: UploadFile = File(...),
    tenant_id: str = Depends(get_tenant_id),
):
    """Upload a manually-created storyboard grid image.

    Saves to Google Drive and updates the scripts table.
    Used when API generation fails (e.g. content policy blocks).
    """
    from storage import upload_bytes

    # Verify scene exists
    script = await fetch_one(
        "SELECT id FROM scripts WHERE video_id = $1 AND scene = $2 AND tenant_id = $3",
        video_id, scene, tenant_id,
    )
    if not script:
        raise HTTPException(status_code=404, detail=f"Scene {scene} not found")

    if beat < 1 or beat > 5:
        raise HTTPException(status_code=400, detail="Beat must be 1-5")

    # Read file and upload to storage. Same Drive subfolder + filename the
    # storyboard bot uses, so a manual upload REPLACES the bot's grid in
    # place instead of orphaning it in a separate "grids" folder.
    data = await file.read()
    path = f"{video_id}/storyboard/S{scene}-B{beat}.png"
    perm_url = await upload_bytes(data, path, content_type=file.content_type or "image/png")

    # SECURITY: column name built from validated integer (1-5 only, checked above).
    # Values use parameterized $1/$2 — no injection risk.
    assert 1 <= beat <= 5, "beat validated above"
    col = f"storyboard_{beat}_url"
    await execute(
        f"UPDATE scripts SET {col} = $1, updated_at = now() WHERE id = $2",
        perm_url, script["id"],
    )

    # Check if all beats now have grids → set status to grids_generated
    updated = await fetch_one(
        """SELECT storyboard_beat_count,
                  storyboard_1_url, storyboard_2_url, storyboard_3_url,
                  storyboard_4_url, storyboard_5_url
           FROM scripts WHERE id = $1""",
        script["id"],
    )
    beat_count = int(updated.get("storyboard_beat_count") or 1)
    all_present = all(
        updated.get(f"storyboard_{i}_url")
        for i in range(1, beat_count + 1)
    )
    if all_present:
        await execute(
            "UPDATE scripts SET storyboard_status = 'grids_generated', updated_at = now() WHERE id = $1",
            script["id"],
        )

    return {"status": "uploaded", "url": perm_url, "scene": scene, "beat": beat, "all_grids_complete": all_present}


@router.post("/{video_id}/script/tag-dialogue")
async def tag_dialogue(video_id: str, tenant_id=Depends(get_tenant_id)):
    """Run the dialogue intelligence pass: detect whether this script performs
    character dialogue, tag every scene's performance timeline, and cast a
    stable voice per character. Idempotent; runs automatically after the
    script stage for new videos — this endpoint is the manual/retro trigger."""
    from dialogue_intelligence import tag_video_dialogue, cast_character_voices
    try:
        result = await tag_video_dialogue(video_id, tenant_id)
        if result.get("dialogue_mode") == "character_dialogue":
            result["voices"] = await cast_character_voices(video_id, tenant_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{video_id}/dialogue-map")
async def get_dialogue_map(video_id: str, tenant_id=Depends(get_tenant_id)):
    """Per-scene dialogue timeline for UI badges (💬 who speaks where).

    Returns scenes with their dialogue_segments (text/speaker/duration only —
    audio URLs stay server-side; the animatic fetches audio via the proxy).
    """
    import json as _json
    video = await fetch_one(
        "SELECT dialogue_mode FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    if (video.get("dialogue_mode") or "") != "character_dialogue":
        return {"dialogue_mode": video.get("dialogue_mode"), "scenes": []}
    rows = await fetch_all(
        "SELECT scene, dialogue_segments FROM scripts WHERE video_id = $1 AND tenant_id = $2 ORDER BY scene",
        video_id, tenant_id,
    )
    scenes = []
    for r in rows:
        raw = r.get("dialogue_segments")
        if isinstance(raw, str):
            try:
                raw = _json.loads(raw)
            except ValueError:
                raw = None
        if not raw:
            continue
        scenes.append({
            "scene": r["scene"],
            "segments": [
                {"type": s.get("type"), "speaker": s.get("speaker"),
                 "text": s.get("text"), "duration": s.get("duration"),
                 "voiced": bool(s.get("audio_url"))}
                for s in raw
            ],
        })
    return {"dialogue_mode": "character_dialogue", "scenes": scenes}


@router.delete("/{video_id}/clips/{asset_id}")
async def delete_clip(video_id: str, asset_id: str, tenant_id=Depends(get_tenant_id)):
    """Remove ONE clip (the card's hover-X): clears video_clip_url so the card
    returns to its still picture, and trashes the Drive copy so the folder
    matches the screen. The picture and motion prompt are untouched."""
    row = await fetch_one(
        "SELECT video_clip_url FROM assets WHERE id = $1 AND video_id = $2 AND tenant_id = $3",
        asset_id, video_id, tenant_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Clip not found")
    url = row.get("video_clip_url") or ""
    # SECURITY: tenant ownership verified above; id+tenant repeated in WHERE
    await execute(
        "UPDATE assets SET video_clip_url = NULL, video_duration = NULL, updated_at = now() "
        "WHERE id = $1 AND tenant_id = $2",
        asset_id, tenant_id,
    )
    m = re.search(r"[?&]id=([\w-]+)", url) or re.search(r"/d/([\w-]+)", url)
    if m:
        try:
            from routes.media import _drive_service
            _drive_service().files().update(fileId=m.group(1), body={"trashed": True}).execute()
        except Exception as e:
            logger.warning("clip Drive trash failed for %s: %s", asset_id, str(e)[:120])
    return {"status": "deleted", "asset_id": asset_id}


@router.get("/defaults/video-motion-prompt")
async def get_default_video_motion_prompt():
    """Return the default video motion system prompt template."""
    return {"prompt": VIDEO_MOTION_SYSTEM_PROMPT}


@router.get("/defaults/script-prompt")
async def get_default_script_prompt():
    """Return the default script system prompt template."""
    return {"prompt": SCRIPT_SYSTEM_PROMPT}


@router.get("/defaults/thumbnail-prompt")
async def get_default_thumbnail_prompt():
    """Return the default thumbnail system prompt template."""
    return {"prompt": THUMBNAIL_SYSTEM_PROMPT}


@router.get("/defaults/sound-curation-prompt")
async def get_default_sound_curation_prompt():
    """Return the default sound curation system prompt."""
    return {"prompt": SOUND_CURATION_SYSTEM_PROMPT}


@router.get("/defaults/sound-generation-prompt")
async def get_default_sound_generation_prompt():
    """Return the default sound generation system prompt."""
    return {"prompt": SOUND_GENERATION_SYSTEM_PROMPT}


@router.get("/defaults/research-prompt")
async def get_default_research_prompt():
    """Return the default research system prompt."""
    return {"prompt": RESEARCH_SYSTEM_PROMPT}


from pydantic import BaseModel as _BaseModel


class SuggestTitlesRequest(_BaseModel):
    topic: str
    context: Optional[str] = None
    count: int = 5


@router.post("/suggest-titles")
async def suggest_titles(
    body: SuggestTitlesRequest,
    tenant_id: str = Depends(get_tenant_id),
):
    """Generate AI title suggestions for a given topic using Claude."""
    from routes.billing import increment_usage
    from vault import get_secret

    topic = body.topic.strip()
    if not topic:
        raise HTTPException(status_code=400, detail="Topic is required")

    api_key = await get_secret("anthropic_api_key", tenant_id)
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="Anthropic API key not configured. Add it in Settings.",
        )

    channel_name, channel_niche = "", ""
    try:
        profile = await fetch_one(
            "SELECT channel_name, niche FROM channel_profiles WHERE tenant_id = $1",
            tenant_id,
        )
        if profile:
            channel_name = profile.get("channel_name", "")
            channel_niche = profile.get("niche", "")
    except Exception:
        pass

    channel_ctx = ""
    if channel_name or channel_niche:
        channel_ctx = f"\nChannel: {channel_name}. Niche: {channel_niche}."

    prompt = (
        f"Generate {body.count} compelling YouTube video title options for this topic."
        f"{channel_ctx}\n\nTopic: {topic}\n"
        + (f"Additional context: {body.context}\n" if body.context else "")
        + "\nRules:\n"
        "- Each title should use a different angle or hook structure\n"
        "- Titles should be 8-12 words, curiosity-driven\n"
        "- Include power words, numbers, or tension where natural\n"
        "- No clickbait that cannot be delivered on\n\n"
        'Return ONLY a JSON array of strings. Example: ["Title One", "Title Two"]'
    )

    import httpx as _httpx

    try:
        async with _httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 1024,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )

        if resp.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=humanize_error(
                    f"Claude {resp.status_code}",
                    context="We couldn't generate title ideas",
                ),
            )

        data = resp.json()
        text = data.get("content", [{}])[0].get("text", "[]")

        titles = json.loads(text)
        if not isinstance(titles, list):
            titles = [text]

        await increment_usage(tenant_id, "api_calls")

        return {"titles": titles[: body.count], "topic": topic}

    except json.JSONDecodeError:
        raise HTTPException(
            status_code=502, detail="Failed to parse title suggestions"
        )
    except _httpx.TimeoutException:
        raise HTTPException(
            status_code=504, detail="AI request timed out. Try again."
        )


@router.get("/{video_id}/export-manifest")
async def get_export_manifest(video_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Return all downloadable assets for a video as a manifest."""
    try:
        video = await fetch_one(
            """SELECT id, video_title, status, final_video_url, thumbnail_url,
                      drive_folder_link, youtube_url
               FROM videos WHERE id = $1 AND tenant_id = $2""",
            video_id, tenant_id,
        )
    except Exception:
        raise HTTPException(status_code=404, detail="Video not found")
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    assets_rows = await fetch_all(
        """SELECT scene, image_index, image_url, video_clip_url, sound_effect_url
           FROM assets WHERE video_id = $1 AND tenant_id = $2
           ORDER BY scene, image_index""",
        video_id, tenant_id,
    )

    scripts_rows = await fetch_all(
        """SELECT scene, voice_over_url
           FROM scripts WHERE video_id = $1 AND tenant_id = $2
           ORDER BY scene""",
        video_id, tenant_id,
    )

    return {
        "video_id": str(video["id"]),
        "video_title": video["video_title"],
        "status": video["status"],
        "final_video_url": video["final_video_url"],
        "thumbnail_url": video["thumbnail_url"],
        "drive_folder_link": video["drive_folder_link"],
        "youtube_url": video["youtube_url"],
        "assets": [
            {
                "scene": a["scene"],
                "image_index": a["image_index"],
                "image_url": a["image_url"],
                "video_clip_url": a["video_clip_url"],
                "sound_effect_url": a["sound_effect_url"],
            }
            for a in assets_rows
        ],
        "voice_tracks": [
            {"scene": s["scene"], "voice_over_url": s["voice_over_url"]}
            for s in scripts_rows
        ],
    }
