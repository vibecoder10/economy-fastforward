"""Pipeline trigger routes - Execute pipeline stages from the web UI.

All pipeline operations run as background tasks so the API responds immediately.
The frontend can poll for status or use the activity feed to track progress.

Task tracking uses a dual-layer approach:
- In-memory dict for fast real-time progress (sync-compatible with progress callbacks)
- Database table (background_tasks) for persistence across restarts and task history
"""

import asyncio
import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from auth import get_tenant_id
from database import fetch_one, fetch_all, execute
from pipeline_executor import PipelineExecutor
from status_map import to_supabase, to_pipeline, get_next_status_supabase, is_at_or_past_stage

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


# --- Request/Response Models ---

class CreateIdeaRequest(BaseModel):
    """Request to create a new video idea."""
    topic: str
    source: str = "storyengine"


class PipelineResponse(BaseModel):
    """Response from pipeline operations."""
    video_id: Optional[str] = None
    status: str
    message: Optional[str] = None
    error: Optional[str] = None


class PipelineStatus(BaseModel):
    """Current pipeline status for a video."""
    video_id: str
    status: str
    status_display: str
    next_action: Optional[str] = None
    airtable_synced: bool = False


# --- Background Task Tracking (dual-layer: dict + DB) ---
import time as _time

_running_tasks: dict[str, dict] = {}

# Tasks older than 10 minutes are considered stale (server restart, crash, etc.)
_STALE_TASK_SECONDS = 600


async def _db_persist_task(
    tenant_id: str,
    video_id: str,
    task_type: str,
    status: str,
    message: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """Persist task state to the background_tasks table.

    Uses upsert: one active row per video_id (status in running/pending).
    Completed/failed rows are kept for history.
    """
    try:
        if status == "running":
            # Insert new task (or update if one is already running for this video)
            existing = await fetch_one(
                "SELECT id FROM background_tasks "
                "WHERE video_id = $1 AND status = 'running' LIMIT 1",
                video_id,
            )
            if existing:
                await execute(
                    "UPDATE background_tasks SET message = $1 WHERE id = $2",
                    message, existing["id"],
                )
            else:
                await execute(
                    "INSERT INTO background_tasks "
                    "(tenant_id, video_id, task_type, status, message, started_at) "
                    "VALUES ($1, $2, $3, 'running', $4, now())",
                    tenant_id, video_id, task_type, message,
                )
        elif status in ("completed", "failed"):
            await execute(
                "UPDATE background_tasks "
                "SET status = $1, message = $2, error_message = $3, completed_at = now() "
                "WHERE video_id = $4 AND status = 'running'",
                status, message, error, video_id,
            )
    except Exception:
        pass  # DB persistence is best-effort; dict is the real-time source


async def recover_stale_tasks() -> int:
    """Mark any tasks stuck in 'running' as failed. Called on server startup."""
    try:
        result = await execute(
            "UPDATE background_tasks SET status = 'failed', "
            "error_message = 'Server restarted — task interrupted', "
            "completed_at = now() "
            "WHERE status = 'running'"
        )
        # asyncpg returns "UPDATE N" string
        count = int(result.split()[-1]) if result else 0
        return count
    except Exception:
        return 0


def _set_task_status(
    video_id: str,
    status: str,
    message: Optional[str] = None,
    error: Optional[str] = None,
    *,
    tenant_id: Optional[str] = None,
    task_type: str = "pipeline",
):
    """Update task status in dict. Fire-and-forget DB persistence for key transitions.

    Normalizes status to: running | completed | failed
    """
    # Normalize: anything not running/failed is completed
    if status not in ("running", "failed"):
        normalized = "completed"
    else:
        normalized = status
    resolved_error = error
    resolved_message = message
    if normalized == "failed" and not resolved_error:
        resolved_error = message
    _running_tasks[video_id] = {
        "status": normalized,
        "message": resolved_message,
        "error": resolved_error,
        "started_at": _running_tasks.get(video_id, {}).get("started_at", _time.time()),
    }

    # Persist key transitions to DB (fire-and-forget)
    if tenant_id and normalized in ("running", "completed", "failed"):
        try:
            asyncio.get_running_loop().create_task(
                _db_persist_task(
                    str(tenant_id), video_id, task_type,
                    normalized, resolved_message, resolved_error,
                )
            )
        except RuntimeError:
            pass  # No event loop — skip DB write


def _get_task_status(video_id: str) -> Optional[dict]:
    """Get task status for a video. Auto-clears stale tasks."""
    task = _running_tasks.get(video_id)
    if not task:
        return None
    # Auto-clear stale tasks (older than 10 minutes and still "running")
    if task["status"] == "running" and _time.time() - task.get("started_at", 0) > _STALE_TASK_SECONDS:
        _running_tasks.pop(video_id, None)
        return None
    return task


def _clear_task_status(video_id: str):
    """Clear task status after completion (dict only — DB row stays for history)."""
    _running_tasks.pop(video_id, None)


# --- Endpoints ---

@router.post("/create-idea", response_model=PipelineResponse)
async def create_idea(
    request: CreateIdeaRequest,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Create a new video idea.

    Creates the video record and optionally triggers research in the background.
    """
    from routes.billing import check_plan_limits, increment_usage
    await check_plan_limits(tenant_id, "video")

    executor = PipelineExecutor(tenant_id)

    # Create synchronously so we can return the video_id
    result = await executor.create_idea(request.topic, request.source)

    if result.get("video_id"):
        await increment_usage(tenant_id, "videos_created")

    return PipelineResponse(
        video_id=result.get("video_id"),
        status=result.get("status", "unknown"),
        message=result.get("message"),
        error=result.get("error"),
    )


@router.post("/research/{video_id}", response_model=PipelineResponse)
async def run_research(
    video_id: str,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Run research agent on a video idea.

    Runs in background. Poll /status/{video_id} or check activity feed.
    """
    # Check video exists
    video = await fetch_one(
        "SELECT id, status FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    # Check not already running
    if _get_task_status(video_id):
        raise HTTPException(status_code=409, detail="Task already running for this video")

    _set_task_status(video_id, "running", "Research in progress", tenant_id=tenant_id)

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_research(video_id)
            _set_task_status(video_id, result.get("status", "unknown"), result.get("error"), tenant_id=tenant_id)

            # Auto-cascade: keep advancing through pipeline steps
            if result.get("status") != "failed":
                terminal = {"rendered", "uploaded", "uploaded_draft", "done", "published"}
                for _ in range(20):  # Safety limit
                    video = await fetch_one("SELECT status FROM videos WHERE id = $1", video_id)
                    status = (video or {}).get("status", "")
                    if status in terminal:
                        break
                    _set_task_status(video_id, "running", f"Running: {status}")
                    step_result = await executor.run_next_step(video_id)
                    step_status = step_result.get("status", "")
                    if step_status == "failed":
                        _set_task_status(video_id, "failed", step_result.get("error"), tenant_id=tenant_id)
                        break
                    if step_status in ("needs_approval", "idle"):
                        _set_task_status(video_id, "completed", step_result.get("message", "Waiting for approval"))
                        break
                    _set_task_status(video_id, step_status)
        except Exception as e:
            _set_task_status(video_id, "failed", str(e), tenant_id=tenant_id)
        finally:
            # Clear after a delay so frontend can poll final status
            await asyncio.sleep(30)
            _clear_task_status(video_id)

    background_tasks.add_task(_run)

    return PipelineResponse(
        video_id=video_id,
        status="running",
        message="Research started — pipeline will auto-advance through all steps",
    )


@router.post("/script/{video_id}", response_model=PipelineResponse)
async def run_script(
    video_id: str,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Generate script for a video.

    Video must be at 'ready_for_scripting' status.
    """
    video = await fetch_one(
        "SELECT id, status FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    if not is_at_or_past_stage(video["status"], "ready_for_scripting"):
        raise HTTPException(
            status_code=400,
            detail=f"Video not ready for scripting (status: {video['status']})",
        )

    if _get_task_status(video_id):
        raise HTTPException(status_code=409, detail="Task already running")

    _set_task_status(video_id, "running", "Script generation in progress", tenant_id=tenant_id)

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_script(video_id)
            _set_task_status(video_id, result.get("status", "unknown"), result.get("error"), tenant_id=tenant_id)
        except Exception as e:
            _set_task_status(video_id, "failed", str(e), tenant_id=tenant_id)
        finally:
            await asyncio.sleep(30)
            _clear_task_status(video_id)

    background_tasks.add_task(_run)

    return PipelineResponse(video_id=video_id, status="running", message="Script generation started")


@router.post("/voice/{video_id}", response_model=PipelineResponse)
async def run_voice(
    video_id: str,
    background_tasks: BackgroundTasks,
    scene: Optional[int] = None,
    tenant_id: str = Depends(get_tenant_id),
):
    """Generate voice narration for a video.

    Video must be at 'ready_for_voice' status unless scene is specified
    (targeted single-scene regen bypasses status gate).
    """
    video = await fetch_one(
        "SELECT id, status FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    if scene is None and not is_at_or_past_stage(video["status"], "ready_for_voice"):
        raise HTTPException(
            status_code=400,
            detail=f"Video not ready for voice (status: {video['status']})",
        )

    if _get_task_status(video_id):
        raise HTTPException(status_code=409, detail="Task already running")

    _set_task_status(video_id, "running", "Voice generation in progress", tenant_id=tenant_id)

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_voice(video_id, scene=scene)
            _set_task_status(video_id, result.get("status", "unknown"), result.get("error"), tenant_id=tenant_id)
        except Exception as e:
            _set_task_status(video_id, "failed", str(e), tenant_id=tenant_id)
        finally:
            await asyncio.sleep(30)
            _clear_task_status(video_id)

    background_tasks.add_task(_run)

    msg = f"Voice generation started (scene {scene})" if scene else "Voice generation started"
    return PipelineResponse(video_id=video_id, status="running", message=msg)


@router.post("/split/{video_id}", response_model=PipelineResponse)
async def run_split(
    video_id: str,
    tenant_id: str = Depends(get_tenant_id),
):
    """Split scene text into timed sentence segments using the deterministic splitter.

    Runs synchronously (fast, no API calls). Creates asset records with
    sentence_text, duration_seconds, and timing for each segment.

    Requires voice to be generated first (uses voice duration for WPS calculation).
    """
    video = await fetch_one(
        "SELECT id, status FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    if not is_at_or_past_stage(video["status"], "ready_for_voice"):
        raise HTTPException(
            status_code=400,
            detail=f"Video not ready for splitting (needs voice first, status: {video['status']})",
        )

    try:
        executor = PipelineExecutor(tenant_id)
        result = await executor.run_split(video_id)
        if result.get("status") == "failed":
            raise HTTPException(status_code=500, detail=result.get("error", "Split failed"))
        return PipelineResponse(
            video_id=video_id,
            status="completed",
            message=f"Split {result.get('total_segments', 0)} segments across {result.get('scenes_split', 0)} scenes",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/prompts/{video_id}", response_model=PipelineResponse)
async def run_prompts(
    video_id: str,
    background_tasks: BackgroundTasks,
    scene: Optional[int] = None,
    index: Optional[int] = None,
    tenant_id: str = Depends(get_tenant_id),
):
    """Generate image prompts for a video.

    Video must be at 'ready_for_image_prompts' status unless scene is specified
    (targeted single-scene or single-segment regen bypasses status gate).
    """
    video = await fetch_one(
        "SELECT id, status FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    if scene is None and not is_at_or_past_stage(video["status"], "ready_for_image_prompts"):
        raise HTTPException(
            status_code=400,
            detail=f"Video not ready for prompts (status: {video['status']})",
        )

    if _get_task_status(video_id):
        raise HTTPException(status_code=409, detail="Task already running")

    _set_task_status(video_id, "running", "Prompt generation in progress", tenant_id=tenant_id)

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_prompts(video_id, scene=scene, index=index)
            _set_task_status(video_id, result.get("status", "unknown"), result.get("error"), tenant_id=tenant_id)
        except Exception as e:
            _set_task_status(video_id, "failed", str(e), tenant_id=tenant_id)
        finally:
            await asyncio.sleep(30)
            _clear_task_status(video_id)

    background_tasks.add_task(_run)

    if scene is not None and index is not None:
        msg = f"Generating prompt for scene {scene} segment {index}"
    elif scene is not None:
        msg = f"Generating prompts for scene {scene}"
    else:
        msg = "Prompt generation started"
    return PipelineResponse(video_id=video_id, status="running", message=msg)


@router.post("/storyboards/{video_id}", response_model=PipelineResponse)
async def run_storyboards(
    video_id: str,
    background_tasks: BackgroundTasks,
    scene: Optional[int] = None,
    tenant_id: str = Depends(get_tenant_id),
):
    """Generate storyboard prompts for a video.

    Args:
        scene: If set, only generate prompts for this scene (per-scene mode).
    """
    video = await fetch_one(
        "SELECT id, status FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    # Per-scene generation bypasses status gate (like targeted image regen)
    if scene is None and not is_at_or_past_stage(video["status"], "ready_for_storyboards"):
        raise HTTPException(
            status_code=400,
            detail=f"Video not ready for storyboards (status: {video['status']})",
        )

    if _get_task_status(video_id):
        raise HTTPException(status_code=409, detail="Task already running")

    scene_label = f" Scene {scene}" if scene else ""
    _set_task_status(video_id, "running", f"Generating storyboard prompts{scene_label}...", tenant_id=tenant_id)

    def progress_callback(msg: str):
        _set_task_status(video_id, "running", msg)

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_storyboard_prompts(
                video_id, scene=scene, progress_callback=progress_callback
            )
            _set_task_status(
                video_id,
                result.get("status", "unknown"),
                result.get("message") or result.get("error"),
                result.get("error"),
                tenant_id=tenant_id,
            )
        except Exception as e:
            _set_task_status(video_id, "failed", str(e), str(e), tenant_id=tenant_id)
        finally:
            await asyncio.sleep(30)
            _clear_task_status(video_id)

    background_tasks.add_task(_run)

    return PipelineResponse(video_id=video_id, status="running", message=f"Storyboard generation started{scene_label}")


@router.post("/story-bible/{video_id}", response_model=PipelineResponse)
async def run_story_bible(
    video_id: str,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Generate a Story Bible for a video."""
    video = await fetch_one(
        "SELECT id, status FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    if _get_task_status(video_id):
        raise HTTPException(status_code=409, detail="Task already running")

    _set_task_status(video_id, "running", "Story Bible generation in progress", tenant_id=tenant_id)

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_story_bible(video_id)
            _set_task_status(
                video_id,
                result.get("status", "unknown"),
                result.get("message") or "Story Bible generated",
                result.get("error"),
                tenant_id=tenant_id,
            )
        except Exception as e:
            _set_task_status(video_id, "failed", str(e), str(e), tenant_id=tenant_id)
        finally:
            await asyncio.sleep(30)
            _clear_task_status(video_id)

    background_tasks.add_task(_run)

    return PipelineResponse(video_id=video_id, status="running", message="Story Bible generation started")


@router.post("/storyboard-images/{video_id}", response_model=PipelineResponse)
async def run_storyboard_images(
    video_id: str,
    background_tasks: BackgroundTasks,
    scene: Optional[int] = None,
    tenant_id: str = Depends(get_tenant_id),
):
    """Generate storyboard images for a video.

    Relaxed status gate: allows manual triggering from UI as long as voice
    has been generated (storyboard prompts need image prompts which need voice).

    Args:
        scene: If set, only generate images for this scene (per-scene mode).
    """
    video = await fetch_one(
        "SELECT id, status FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    # Per-scene generation bypasses status gate
    if scene is None and not is_at_or_past_stage(video["status"], "ready_for_image_prompts"):
        raise HTTPException(
            status_code=400,
            detail=f"Video not ready for storyboard images — voice must be generated first (status: {video['status']})",
        )

    if _get_task_status(video_id):
        raise HTTPException(status_code=409, detail="Task already running")

    scene_label = f" Scene {scene}" if scene else ""
    _set_task_status(video_id, "running", f"Generating storyboard images{scene_label}...", tenant_id=tenant_id)

    def progress_callback(msg: str):
        _set_task_status(video_id, "running", msg)

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_storyboard_images(
                video_id, scene=scene, progress_callback=progress_callback
            )
            _set_task_status(
                video_id,
                result.get("status", "unknown"),
                result.get("message") or result.get("error"),
                result.get("error"),
                tenant_id=tenant_id,
            )
        except Exception as e:
            _set_task_status(video_id, "failed", str(e), str(e), tenant_id=tenant_id)
        finally:
            await asyncio.sleep(30)
            _clear_task_status(video_id)

    background_tasks.add_task(_run)

    return PipelineResponse(video_id=video_id, status="running", message=f"Storyboard image generation started{scene_label}")


@router.post("/storyboard-extract/{video_id}", response_model=PipelineResponse)
async def run_storyboard_extract(
    video_id: str,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Extract frames from storyboard grids."""
    video = await fetch_one(
        "SELECT id, status FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    if not is_at_or_past_stage(video["status"], "ready_for_storyboard_extraction"):
        raise HTTPException(
            status_code=400,
            detail=f"Video not ready for storyboard extraction (status: {video['status']})",
        )

    if _get_task_status(video_id):
        raise HTTPException(status_code=409, detail="Task already running")

    _set_task_status(video_id, "running", "Storyboard extraction in progress", tenant_id=tenant_id)

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)

            async def _progress(msg: str):
                _set_task_status(video_id, "running", msg)

            result = await executor.run_storyboard_extract(video_id, progress_callback=_progress)
            _set_task_status(
                video_id,
                result.get("status", "unknown"),
                result.get("message") or result.get("error"),
                result.get("error"),
                tenant_id=tenant_id,
            )
        except Exception as e:
            _set_task_status(video_id, "failed", str(e), str(e), tenant_id=tenant_id)
        finally:
            await asyncio.sleep(30)
            _clear_task_status(video_id)

    background_tasks.add_task(_run)

    return PipelineResponse(video_id=video_id, status="running", message="Storyboard extraction started")


@router.post("/upscale-panels/{video_id}", response_model=PipelineResponse)
async def run_upscale_panels(
    video_id: str,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Upscale extracted panels that haven't been upscaled yet. Removes KF labels."""
    video = await fetch_one(
        "SELECT id, status FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    if _get_task_status(video_id):
        raise HTTPException(status_code=409, detail="Task already running")

    _set_task_status(video_id, "running", "Panel upscaling in progress", tenant_id=tenant_id)

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)

            async def _progress(msg: str):
                _set_task_status(video_id, "running", msg)

            result = await executor.run_upscale_panels(video_id, progress_callback=_progress)
            _set_task_status(
                video_id,
                result.get("status", "unknown"),
                result.get("message") or result.get("error"),
                result.get("error"),
                tenant_id=tenant_id,
            )
        except Exception as e:
            _set_task_status(video_id, "failed", str(e), str(e), tenant_id=tenant_id)
        finally:
            await asyncio.sleep(30)
            _clear_task_status(video_id)

    background_tasks.add_task(_run)

    return PipelineResponse(video_id=video_id, status="running", message="Panel upscaling started")


@router.post("/images/{video_id}", response_model=PipelineResponse)
async def run_images(
    video_id: str,
    background_tasks: BackgroundTasks,
    scene: Optional[int] = None,
    index: Optional[int] = None,
    variants: Optional[int] = None,
    tenant_id: str = Depends(get_tenant_id),
):
    """Generate images for a video.

    When scene/index are specified, performs targeted single-image regen
    and bypasses the status gate.
    """
    video = await fetch_one(
        "SELECT id, status FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    if variants is not None and variants > 1 and (scene is None or index is None):
        raise HTTPException(
            status_code=400,
            detail="Image variants require both scene and index.",
        )

    if scene is None and not is_at_or_past_stage(video["status"], "ready_for_images"):
        raise HTTPException(
            status_code=400,
            detail=f"Video not ready for images (status: {video['status']})",
        )

    if _get_task_status(video_id):
        raise HTTPException(status_code=409, detail="Task already running")

    _set_task_status(video_id, "running", "Image generation in progress", tenant_id=tenant_id)

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            if variants is not None and variants > 1:
                result = await executor.run_image_variants(video_id, scene=scene, index=index, variants=variants)
            else:
                result = await executor.run_images(video_id, scene=scene, index=index)
            _set_task_status(video_id, result.get("status", "unknown"), result.get("error"), tenant_id=tenant_id)
        except Exception as e:
            _set_task_status(video_id, "failed", str(e), tenant_id=tenant_id)
        finally:
            await asyncio.sleep(30)
            _clear_task_status(video_id)

    background_tasks.add_task(_run)

    if variants is not None and variants > 1 and scene is not None and index is not None:
        msg = f"Generating {variants} image variants for scene {scene} segment {index}"
    elif scene is not None and index is not None:
        msg = f"Generating image for scene {scene} segment {index}"
    elif scene is not None:
        msg = f"Generating images for scene {scene}"
    else:
        msg = "Image generation started"

    return PipelineResponse(video_id=video_id, status="running", message=msg)


@router.post("/sound-prompts/{video_id}", response_model=PipelineResponse)
async def run_sound_prompts(
    video_id: str,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Generate sound design prompts for a video."""
    video = await fetch_one(
        "SELECT id, status FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    if not is_at_or_past_stage(video["status"], "ready_for_sound_design"):
        raise HTTPException(
            status_code=400,
            detail=f"Video not ready for sound design (status: {video['status']})",
        )

    if _get_task_status(video_id):
        raise HTTPException(status_code=409, detail="Task already running")

    _set_task_status(video_id, "running", "Sound prompt generation in progress", tenant_id=tenant_id)

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_sound_prompts(video_id)
            _set_task_status(video_id, result.get("status", "unknown"), result.get("error"), tenant_id=tenant_id)
        except Exception as e:
            _set_task_status(video_id, "failed", str(e), tenant_id=tenant_id)
        finally:
            await asyncio.sleep(30)
            _clear_task_status(video_id)

    background_tasks.add_task(_run)

    return PipelineResponse(video_id=video_id, status="running", message="Sound prompt generation started")


@router.post("/sound-effects/{video_id}", response_model=PipelineResponse)
async def run_sound_effects(
    video_id: str,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Generate sound effects for a video."""
    video = await fetch_one(
        "SELECT id, status FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    if not is_at_or_past_stage(video["status"], "ready_for_sound_effects"):
        raise HTTPException(
            status_code=400,
            detail=f"Video not ready for sound effects (status: {video['status']})",
        )

    if _get_task_status(video_id):
        raise HTTPException(status_code=409, detail="Task already running")

    _set_task_status(video_id, "running", "Sound effects generation in progress", tenant_id=tenant_id)

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_sound_effects(video_id)
            _set_task_status(video_id, result.get("status", "unknown"), result.get("error"), tenant_id=tenant_id)
        except Exception as e:
            _set_task_status(video_id, "failed", str(e), tenant_id=tenant_id)
        finally:
            await asyncio.sleep(30)
            _clear_task_status(video_id)

    background_tasks.add_task(_run)

    return PipelineResponse(video_id=video_id, status="running", message="Sound effects generation started")


@router.post("/video-scripts/{video_id}", response_model=PipelineResponse)
async def run_video_scripts(
    video_id: str,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Generate video motion scripts for a video."""
    video = await fetch_one(
        "SELECT id, status FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    status = video.get("status") or ""
    if status and not is_at_or_past_stage(status, "ready_for_images"):
        raise HTTPException(
            status_code=400,
            detail=f"Video not ready for video scripts — needs images first (status: {status})",
        )

    if _get_task_status(video_id):
        raise HTTPException(status_code=409, detail="Task already running")

    _set_task_status(video_id, "running", "Video script generation in progress", tenant_id=tenant_id)

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_video_scripts(video_id)
            _set_task_status(video_id, result.get("status", "unknown"), result.get("error"), tenant_id=tenant_id)
        except Exception as e:
            _set_task_status(video_id, "failed", str(e), tenant_id=tenant_id)
        finally:
            await asyncio.sleep(30)
            _clear_task_status(video_id)

    background_tasks.add_task(_run)

    return PipelineResponse(video_id=video_id, status="running", message="Video script generation started")


@router.post("/video-generation/{video_id}", response_model=PipelineResponse)
async def run_video_generation(
    video_id: str,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Generate video clips for a video."""
    video = await fetch_one(
        "SELECT id, status FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    status = video.get("status") or ""
    if status and not is_at_or_past_stage(status, "ready_for_video_generation"):
        raise HTTPException(
            status_code=400,
            detail=f"Video not ready for video generation (status: {status})",
        )

    if _get_task_status(video_id):
        raise HTTPException(status_code=409, detail="Task already running")

    _set_task_status(video_id, "running", "Video clip generation in progress", tenant_id=tenant_id)

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_video_generation(video_id)
            _set_task_status(video_id, result.get("status", "unknown"), result.get("error"), tenant_id=tenant_id)
        except Exception as e:
            _set_task_status(video_id, "failed", str(e), tenant_id=tenant_id)
        finally:
            await asyncio.sleep(30)
            _clear_task_status(video_id)

    background_tasks.add_task(_run)

    return PipelineResponse(video_id=video_id, status="running", message="Video clip generation started")


@router.post("/thumbnail/{video_id}", response_model=PipelineResponse)
async def run_thumbnail(
    video_id: str,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Generate thumbnail for a video.

    Reads thumbnail_prompt, thumbnail_text, and thumbnail_style_override
    from the video record so the pipeline bot uses the configured settings
    and any autopilot-generated patterns.
    """
    video = await fetch_one(
        """SELECT id, status, thumbnail_prompt, thumbnail_text,
                  thumbnail_style_override, video_title
           FROM videos WHERE id = $1 AND tenant_id = $2""",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    status = video.get("status") or ""
    if status and not is_at_or_past_stage(status, "ready_for_voice"):
        raise HTTPException(
            status_code=400,
            detail=f"Video not ready for thumbnail — needs at least a script (status: {status})",
        )

    if _get_task_status(video_id):
        raise HTTPException(status_code=409, detail="Task already running")

    _set_task_status(video_id, "running", "Thumbnail generation in progress", tenant_id=tenant_id)

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_thumbnail(video_id)
            _set_task_status(video_id, result.get("status", "unknown"), result.get("error"), tenant_id=tenant_id)
        except Exception as e:
            _set_task_status(video_id, "failed", str(e), tenant_id=tenant_id)
        finally:
            await asyncio.sleep(30)
            _clear_task_status(video_id)

    background_tasks.add_task(_run)

    return PipelineResponse(video_id=video_id, status="running", message="Thumbnail generation started")


@router.post("/render/{video_id}", response_model=PipelineResponse)
async def run_render(
    video_id: str,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Render final video."""
    from routes.billing import check_plan_limits
    await check_plan_limits(tenant_id, "render")

    video = await fetch_one(
        "SELECT id, status FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    if not is_at_or_past_stage(video["status"], "ready_to_render"):
        raise HTTPException(
            status_code=400,
            detail=f"Video not ready to render (status: {video['status']})",
        )

    if _get_task_status(video_id):
        raise HTTPException(status_code=409, detail="Task already running")

    _set_task_status(video_id, "running", "Rendering in progress", tenant_id=tenant_id)

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_render(video_id)
            _set_task_status(video_id, result.get("status", "unknown"), result.get("error"), tenant_id=tenant_id)
        except Exception as e:
            _set_task_status(video_id, "failed", str(e), tenant_id=tenant_id)
        finally:
            await asyncio.sleep(30)
            _clear_task_status(video_id)

    background_tasks.add_task(_run)

    return PipelineResponse(video_id=video_id, status="running", message="Render started")


@router.post("/upload/{video_id}", response_model=PipelineResponse)
async def run_upload(
    video_id: str,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Upload video to YouTube as unlisted draft."""
    video = await fetch_one(
        "SELECT id, status FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    if not is_at_or_past_stage(video["status"], "rendered"):
        raise HTTPException(
            status_code=400,
            detail=f"Video not ready for upload (status: {video['status']})",
        )

    if _get_task_status(video_id):
        raise HTTPException(status_code=409, detail="Task already running")

    _set_task_status(video_id, "running", "Upload in progress", tenant_id=tenant_id)

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_upload(video_id)
            _set_task_status(video_id, result.get("status", "unknown"), result.get("error"), tenant_id=tenant_id)
        except Exception as e:
            _set_task_status(video_id, "failed", str(e), tenant_id=tenant_id)
        finally:
            await asyncio.sleep(30)
            _clear_task_status(video_id)

    background_tasks.add_task(_run)

    return PipelineResponse(video_id=video_id, status="running", message="Upload started")


@router.post("/run-next/{video_id}", response_model=PipelineResponse)
async def run_next_step(
    video_id: str,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Run the next pipeline step for a video.

    Automatically determines what step to run based on current status.
    """
    video = await fetch_one(
        "SELECT id, status FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    if _get_task_status(video_id):
        raise HTTPException(status_code=409, detail="Task already running")

    _set_task_status(video_id, "running", "Running next step", tenant_id=tenant_id)

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_next_step(video_id)
            _set_task_status(video_id, result.get("status", "unknown"), result.get("error") or result.get("message"), tenant_id=tenant_id)
        except Exception as e:
            _set_task_status(video_id, "failed", str(e), tenant_id=tenant_id)
        finally:
            await asyncio.sleep(30)
            _clear_task_status(video_id)

    background_tasks.add_task(_run)

    return PipelineResponse(video_id=video_id, status="running", message="Next step started")


@router.get("/status/{video_id}", response_model=PipelineStatus)
async def get_pipeline_status(
    video_id: str,
    tenant_id: str = Depends(get_tenant_id),
):
    """Get current pipeline status for a video.

    Returns both the current status and what action is available next.
    """
    video = await fetch_one(
        "SELECT id, status, airtable_record_id FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    status = video["status"]

    # Check if a task is running
    task_status = _get_task_status(video_id)
    if task_status and task_status["status"] == "running":
        return PipelineStatus(
            video_id=video_id,
            status="running",
            status_display="Running...",
            next_action=None,
            airtable_synced=bool(video.get("airtable_record_id")),
        )

    # Map status to next action
    next_actions = {
        "idea_logged": "Research",
        "approved": "Research",
        "ready_for_scripting": "Generate Script",
        "ready_for_voice": "Generate Voice",
        "ready_for_image_prompts": "Generate Prompts",
        "ready_for_images": "Generate Images",
        "ready_for_thumbnail": "Generate Thumbnail",
        "done": "Render",
        "ready_to_render": "Render",
        "rendered": "Upload",
    }

    # Convert status for display
    display_map = {
        "idea_logged": "Idea Logged",
        "ready_for_scripting": "Ready for Scripting",
        "ready_for_voice": "Ready for Voice",
        "ready_for_image_prompts": "Ready for Prompts",
        "ready_for_images": "Ready for Images",
        "ready_for_thumbnail": "Ready for Thumbnail",
        "done": "Production Done",
        "ready_to_render": "Ready to Render",
        "rendered": "Rendered",
        "uploaded_draft": "Draft Uploaded",
    }

    return PipelineStatus(
        video_id=video_id,
        status=status,
        status_display=display_map.get(status, status),
        next_action=next_actions.get(status),
        airtable_synced=bool(video.get("airtable_record_id")),
    )


@router.get("/task/{video_id}")
async def get_task_status(
    video_id: str,
    tenant_id: str = Depends(get_tenant_id),
):
    """Get background task status for a video.

    Used for polling while a stage is running.
    """
    task = _get_task_status(video_id)
    if not task:
        return {"status": "idle", "message": None, "error": None}
    return {
        "status": task["status"],
        "message": task.get("message"),
        "error": task.get("error"),
    }


@router.post("/generate-video-prompts/{video_id}", response_model=PipelineResponse)
async def generate_video_prompts(
    video_id: str,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Generate video clip prompts for a video's assets.

    Reads each asset's image_prompt and generates a corresponding
    video_clip_prompt optimized for motion/animation.
    """
    video = await fetch_one(
        "SELECT id, status FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    if _get_task_status(video_id):
        raise HTTPException(status_code=409, detail="Task already running")

    _set_task_status(video_id, "running", "Video clip prompt generation in progress", tenant_id=tenant_id)

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_video_scripts(video_id)
            _set_task_status(video_id, result.get("status", "unknown"), result.get("error"), tenant_id=tenant_id)
        except Exception as e:
            _set_task_status(video_id, "failed", str(e), tenant_id=tenant_id)
        finally:
            await asyncio.sleep(30)
            _clear_task_status(video_id)

    background_tasks.add_task(_run)

    return PipelineResponse(video_id=video_id, status="running", message="Video clip prompt generation started")


@router.get("/task/{video_id}/clear")
async def clear_task_status(
    video_id: str,
    tenant_id: str = Depends(get_tenant_id),
):
    """Clear stale task status for a video.

    Used when a 409 is returned but the task is actually dead.
    """
    _clear_task_status(video_id)
    return {"status": "cleared"}


# --- Claude Orchestration ---

class OrchestrateRequest(BaseModel):
    """Request for Claude-driven orchestration."""
    video_id: str
    user_intent: Optional[str] = None


@router.post("/orchestrate")
async def orchestrate(
    request: OrchestrateRequest,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Ask Claude to decide and execute the next pipeline step.

    If Claude orchestration is disabled for this tenant, falls back to
    status-based routing. If confidence is low, returns alternatives
    for user approval instead of auto-executing.
    """
    executor = PipelineExecutor(tenant_id)

    async def _run():
        _set_task_status(request.video_id, "running", "Claude is deciding...", tenant_id=tenant_id)
        try:
            result = await executor.run_next_step(
                request.video_id,
                user_intent=request.user_intent,
            )
            status = "completed" if result.get("status") != "failed" else "failed"
            _set_task_status(request.video_id, status, result.get("message"), tenant_id=tenant_id)
        except Exception as e:
            _set_task_status(request.video_id, "failed", str(e), tenant_id=tenant_id)

    background_tasks.add_task(_run)
    return {"status": "started", "video_id": request.video_id}


@router.post("/orchestrate/decide")
async def orchestrate_decide_only(
    request: OrchestrateRequest,
    tenant_id: str = Depends(get_tenant_id),
):
    """Ask Claude what it would do, without executing.

    Returns the decision with reasoning, alternatives, and cost estimate.
    Useful for the chat UI to show Claude's thinking before user confirms.
    """
    try:
        from claude_orchestrator import ClaudeOrchestrator

        orchestrator = ClaudeOrchestrator(tenant_id)
        decision = await orchestrator.decide(
            request.video_id,
            user_intent=request.user_intent,
        )
        return decision.model_dump()
    except Exception as e:
        return {
            "action": "skip",
            "reasoning": f"Orchestrator error: {e}",
            "confidence": 0.0,
        }


# --- Reset Pipeline ---

class ResetRequest(BaseModel):
    """Request to reset a video's pipeline stage."""
    reset_to: str = "ready_for_scripting"  # Which status to reset to


@router.post("/reset/{video_id}")
async def reset_pipeline(
    video_id: str,
    request: ResetRequest,
    tenant_id: str = Depends(get_tenant_id),
):
    """Reset a video's pipeline — delete downstream data and set status back.

    reset_to options:
    - "ready_for_scripting" — delete scripts + assets, keep research
    - "ready_for_voice" — delete voice audio, keep scripts
    - "ready_for_images" — delete images, keep prompts
    """
    video = await fetch_one(
        "SELECT id, status FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    reset_to = request.reset_to
    deleted = {"scripts": 0, "assets": 0}

    if reset_to == "ready_for_scripting":
        # Delete all scripts and assets for this video
        result = await execute(
            "DELETE FROM scripts WHERE video_id = $1 AND tenant_id = $2",
            video_id, tenant_id,
        )
        deleted["scripts"] = int(result.split()[-1]) if result else 0

        result = await execute(
            "DELETE FROM assets WHERE video_id = $1 AND tenant_id = $2",
            video_id, tenant_id,
        )
        deleted["assets"] = int(result.split()[-1]) if result else 0

        # Clear script field on video
        await execute(
            "UPDATE videos SET script = NULL, status = $1 WHERE id = $2 AND tenant_id = $3",
            reset_to, video_id, tenant_id,
        )

    elif reset_to == "ready_for_voice":
        # Clear voice URLs from scripts
        await execute(
            "UPDATE scripts SET voice_over_url = NULL, voice_status = 'Create' WHERE video_id = $1 AND tenant_id = $2",
            video_id, tenant_id,
        )
        await execute(
            "UPDATE videos SET status = $1 WHERE id = $2 AND tenant_id = $3",
            reset_to, video_id, tenant_id,
        )

    elif reset_to in ("ready_for_image_prompts", "ready_for_images"):
        # Delete assets (images)
        result = await execute(
            "DELETE FROM assets WHERE video_id = $1 AND tenant_id = $2",
            video_id, tenant_id,
        )
        deleted["assets"] = int(result.split()[-1]) if result else 0

        await execute(
            "UPDATE videos SET status = $1 WHERE id = $2 AND tenant_id = $3",
            reset_to, video_id, tenant_id,
        )

    else:
        # Just update status
        await execute(
            "UPDATE videos SET status = $1 WHERE id = $2 AND tenant_id = $3",
            reset_to, video_id, tenant_id,
        )

    return {
        "status": "reset",
        "video_id": video_id,
        "reset_to": reset_to,
        "deleted": deleted,
    }


# --- Pipeline SSE Stream ---

@router.get("/stream")
async def pipeline_stream(
    video_id: Optional[str] = Query(None),
    tenant_id: str = Depends(get_tenant_id),
):
    """SSE endpoint for real-time pipeline progress.

    Two event types:
    - stage_change: video moved to a new pipeline stage (from stage_transitions)
    - task_progress: background task status update (running/completed/failed)

    Query params:
    - video_id: filter for a specific video (optional, omit for all videos)
    - token: auth token for EventSource (can't set Authorization header)

    Frontend connects via: new EventSource('/api/pipeline/stream?token=X&video_id=Y')
    """
    async def event_generator():
        last_transition_at = None  # datetime from asyncpg (not string)
        last_task_snapshot: dict[str, str] = {}

        while True:
            # 1. Poll stage transitions (cursor by created_at, not UUID)
            if last_transition_at:
                if video_id:
                    transitions = await fetch_all(
                        """SELECT st.video_id, v.video_title, v.status AS current_status,
                                  st.from_status, st.to_status, st.triggered_by,
                                  st.cost, st.duration_seconds, st.error_message,
                                  st.created_at
                           FROM stage_transitions st
                           LEFT JOIN videos v ON v.id = st.video_id
                           WHERE st.tenant_id = $1 AND st.video_id = $2
                             AND st.created_at > $3
                           ORDER BY st.created_at ASC LIMIT 10""",
                        tenant_id, video_id, last_transition_at,
                    )
                else:
                    transitions = await fetch_all(
                        """SELECT st.video_id, v.video_title, v.status AS current_status,
                                  st.from_status, st.to_status, st.triggered_by,
                                  st.cost, st.duration_seconds, st.error_message,
                                  st.created_at
                           FROM stage_transitions st
                           LEFT JOIN videos v ON v.id = st.video_id
                           WHERE st.tenant_id = $1
                             AND st.created_at > $2
                           ORDER BY st.created_at ASC LIMIT 10""",
                        tenant_id, last_transition_at,
                    )
            else:
                # Initial: fetch most recent to establish cursor
                if video_id:
                    transitions = await fetch_all(
                        """SELECT st.video_id, v.video_title, v.status AS current_status,
                                  st.from_status, st.to_status, st.triggered_by,
                                  st.cost, st.duration_seconds, st.error_message,
                                  st.created_at
                           FROM stage_transitions st
                           LEFT JOIN videos v ON v.id = st.video_id
                           WHERE st.tenant_id = $1 AND st.video_id = $2
                           ORDER BY st.created_at DESC LIMIT 1""",
                        tenant_id, video_id,
                    )
                else:
                    transitions = await fetch_all(
                        """SELECT st.video_id, v.video_title, v.status AS current_status,
                                  st.from_status, st.to_status, st.triggered_by,
                                  st.cost, st.duration_seconds, st.error_message,
                                  st.created_at
                           FROM stage_transitions st
                           LEFT JOIN videos v ON v.id = st.video_id
                           WHERE st.tenant_id = $1
                           ORDER BY st.created_at DESC LIMIT 5""",
                        tenant_id,
                    )

            for t in transitions:
                created_at = t.get("created_at")
                event = {
                    "video_id": str(t["video_id"]) if t.get("video_id") else None,
                    "video_title": t.get("video_title"),
                    "current_status": t.get("current_status"),
                    "from_status": t.get("from_status"),
                    "to_status": t.get("to_status"),
                    "triggered_by": t.get("triggered_by"),
                    "cost": float(t["cost"]) if t.get("cost") else None,
                    "duration_seconds": t.get("duration_seconds"),
                    "error_message": t.get("error_message"),
                    "created_at": created_at.isoformat() if created_at else None,
                }
                yield f"event: stage_change\ndata: {json.dumps(event)}\n\n"
                last_transition_at = created_at

            # 2. Poll task progress (from in-memory _running_tasks)
            if video_id:
                task = _get_task_status(video_id)
                task_key = json.dumps(task, sort_keys=True, default=str) if task else "idle"
                if task_key != last_task_snapshot.get(video_id):
                    event = {
                        "video_id": video_id,
                        "status": task["status"] if task else "idle",
                        "message": task.get("message") if task else None,
                        "error": task.get("error") if task else None,
                    }
                    yield f"event: task_progress\ndata: {json.dumps(event)}\n\n"
                    last_task_snapshot[video_id] = task_key
            else:
                for vid, task in list(_running_tasks.items()):
                    task_key = json.dumps(task, sort_keys=True, default=str)
                    if task_key != last_task_snapshot.get(vid):
                        event = {
                            "video_id": vid,
                            "status": task.get("status", "idle"),
                            "message": task.get("message"),
                            "error": task.get("error"),
                        }
                        yield f"event: task_progress\ndata: {json.dumps(event)}\n\n"
                        last_task_snapshot[vid] = task_key

            yield ": heartbeat\n\n"
            await asyncio.sleep(3)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
