"""Pipeline trigger routes - Execute pipeline stages from the web UI.

All pipeline operations run as background tasks so the API responds immediately.
The frontend can poll for status or use the activity feed to track progress.
"""

import asyncio
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel

from auth import get_tenant_id
from database import fetch_one
from pipeline_executor import PipelineExecutor
from status_map import to_supabase, to_pipeline, get_next_status_supabase

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


# --- Background Task Tracking ---
# Maps video_id -> task info
_running_tasks: dict[str, dict] = {}


def _set_task_status(video_id: str, status: str, message: Optional[str] = None):
    """Update task status for polling."""
    _running_tasks[video_id] = {
        "status": status,
        "message": message,
    }


def _get_task_status(video_id: str) -> Optional[dict]:
    """Get task status for a video."""
    return _running_tasks.get(video_id)


def _clear_task_status(video_id: str):
    """Clear task status after completion."""
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
    executor = PipelineExecutor(tenant_id)

    # Create synchronously so we can return the video_id
    result = await executor.create_idea(request.topic, request.source)

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

    _set_task_status(video_id, "running", "Research in progress")

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_research(video_id)
            _set_task_status(video_id, result.get("status", "unknown"), result.get("error"))
        except Exception as e:
            _set_task_status(video_id, "failed", str(e))
        finally:
            # Clear after a delay so frontend can poll final status
            await asyncio.sleep(30)
            _clear_task_status(video_id)

    background_tasks.add_task(_run)

    return PipelineResponse(
        video_id=video_id,
        status="running",
        message="Research started",
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

    if video["status"] != "ready_for_scripting":
        raise HTTPException(
            status_code=400,
            detail=f"Video not ready for scripting (status: {video['status']})",
        )

    if _get_task_status(video_id):
        raise HTTPException(status_code=409, detail="Task already running")

    _set_task_status(video_id, "running", "Script generation in progress")

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_script(video_id)
            _set_task_status(video_id, result.get("status", "unknown"), result.get("error"))
        except Exception as e:
            _set_task_status(video_id, "failed", str(e))
        finally:
            await asyncio.sleep(30)
            _clear_task_status(video_id)

    background_tasks.add_task(_run)

    return PipelineResponse(video_id=video_id, status="running", message="Script generation started")


@router.post("/voice/{video_id}", response_model=PipelineResponse)
async def run_voice(
    video_id: str,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Generate voice narration for a video.

    Video must be at 'ready_for_voice' status.
    """
    video = await fetch_one(
        "SELECT id, status FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    if video["status"] != "ready_for_voice":
        raise HTTPException(
            status_code=400,
            detail=f"Video not ready for voice (status: {video['status']})",
        )

    if _get_task_status(video_id):
        raise HTTPException(status_code=409, detail="Task already running")

    _set_task_status(video_id, "running", "Voice generation in progress")

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_voice(video_id)
            _set_task_status(video_id, result.get("status", "unknown"), result.get("error"))
        except Exception as e:
            _set_task_status(video_id, "failed", str(e))
        finally:
            await asyncio.sleep(30)
            _clear_task_status(video_id)

    background_tasks.add_task(_run)

    return PipelineResponse(video_id=video_id, status="running", message="Voice generation started")


@router.post("/prompts/{video_id}", response_model=PipelineResponse)
async def run_prompts(
    video_id: str,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Generate image prompts for a video."""
    video = await fetch_one(
        "SELECT id, status FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    if video["status"] != "ready_for_image_prompts":
        raise HTTPException(
            status_code=400,
            detail=f"Video not ready for prompts (status: {video['status']})",
        )

    if _get_task_status(video_id):
        raise HTTPException(status_code=409, detail="Task already running")

    _set_task_status(video_id, "running", "Prompt generation in progress")

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_prompts(video_id)
            _set_task_status(video_id, result.get("status", "unknown"), result.get("error"))
        except Exception as e:
            _set_task_status(video_id, "failed", str(e))
        finally:
            await asyncio.sleep(30)
            _clear_task_status(video_id)

    background_tasks.add_task(_run)

    return PipelineResponse(video_id=video_id, status="running", message="Prompt generation started")


@router.post("/storyboards/{video_id}", response_model=PipelineResponse)
async def run_storyboards(
    video_id: str,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Generate storyboard prompts for a video."""
    video = await fetch_one(
        "SELECT id, status FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    if video["status"] != "ready_for_storyboards":
        raise HTTPException(
            status_code=400,
            detail=f"Video not ready for storyboards (status: {video['status']})",
        )

    if _get_task_status(video_id):
        raise HTTPException(status_code=409, detail="Task already running")

    _set_task_status(video_id, "running", "Storyboard generation in progress")

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_storyboard_prompts(video_id)
            _set_task_status(video_id, result.get("status", "unknown"), result.get("error"))
        except Exception as e:
            _set_task_status(video_id, "failed", str(e))
        finally:
            await asyncio.sleep(30)
            _clear_task_status(video_id)

    background_tasks.add_task(_run)

    return PipelineResponse(video_id=video_id, status="running", message="Storyboard generation started")


@router.post("/storyboard-images/{video_id}", response_model=PipelineResponse)
async def run_storyboard_images(
    video_id: str,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Generate storyboard images for a video."""
    video = await fetch_one(
        "SELECT id, status FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    if video["status"] != "ready_for_storyboard_images":
        raise HTTPException(
            status_code=400,
            detail=f"Video not ready for storyboard images (status: {video['status']})",
        )

    if _get_task_status(video_id):
        raise HTTPException(status_code=409, detail="Task already running")

    _set_task_status(video_id, "running", "Storyboard image generation in progress")

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_storyboard_images(video_id)
            _set_task_status(video_id, result.get("status", "unknown"), result.get("error"))
        except Exception as e:
            _set_task_status(video_id, "failed", str(e))
        finally:
            await asyncio.sleep(30)
            _clear_task_status(video_id)

    background_tasks.add_task(_run)

    return PipelineResponse(video_id=video_id, status="running", message="Storyboard image generation started")


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

    if video["status"] != "ready_for_storyboard_extraction":
        raise HTTPException(
            status_code=400,
            detail=f"Video not ready for storyboard extraction (status: {video['status']})",
        )

    if _get_task_status(video_id):
        raise HTTPException(status_code=409, detail="Task already running")

    _set_task_status(video_id, "running", "Storyboard extraction in progress")

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_storyboard_extract(video_id)
            _set_task_status(video_id, result.get("status", "unknown"), result.get("error"))
        except Exception as e:
            _set_task_status(video_id, "failed", str(e))
        finally:
            await asyncio.sleep(30)
            _clear_task_status(video_id)

    background_tasks.add_task(_run)

    return PipelineResponse(video_id=video_id, status="running", message="Storyboard extraction started")


@router.post("/images/{video_id}", response_model=PipelineResponse)
async def run_images(
    video_id: str,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Generate images for a video."""
    video = await fetch_one(
        "SELECT id, status FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    if video["status"] != "ready_for_images":
        raise HTTPException(
            status_code=400,
            detail=f"Video not ready for images (status: {video['status']})",
        )

    if _get_task_status(video_id):
        raise HTTPException(status_code=409, detail="Task already running")

    _set_task_status(video_id, "running", "Image generation in progress")

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_images(video_id)
            _set_task_status(video_id, result.get("status", "unknown"), result.get("error"))
        except Exception as e:
            _set_task_status(video_id, "failed", str(e))
        finally:
            await asyncio.sleep(30)
            _clear_task_status(video_id)

    background_tasks.add_task(_run)

    return PipelineResponse(video_id=video_id, status="running", message="Image generation started")


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

    if video["status"] != "ready_for_sound_design":
        raise HTTPException(
            status_code=400,
            detail=f"Video not ready for sound design (status: {video['status']})",
        )

    if _get_task_status(video_id):
        raise HTTPException(status_code=409, detail="Task already running")

    _set_task_status(video_id, "running", "Sound prompt generation in progress")

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_sound_prompts(video_id)
            _set_task_status(video_id, result.get("status", "unknown"), result.get("error"))
        except Exception as e:
            _set_task_status(video_id, "failed", str(e))
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

    if video["status"] != "ready_for_sound_effects":
        raise HTTPException(
            status_code=400,
            detail=f"Video not ready for sound effects (status: {video['status']})",
        )

    if _get_task_status(video_id):
        raise HTTPException(status_code=409, detail="Task already running")

    _set_task_status(video_id, "running", "Sound effects generation in progress")

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_sound_effects(video_id)
            _set_task_status(video_id, result.get("status", "unknown"), result.get("error"))
        except Exception as e:
            _set_task_status(video_id, "failed", str(e))
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

    if video["status"] != "ready_for_video_scripts":
        raise HTTPException(
            status_code=400,
            detail=f"Video not ready for video scripts (status: {video['status']})",
        )

    if _get_task_status(video_id):
        raise HTTPException(status_code=409, detail="Task already running")

    _set_task_status(video_id, "running", "Video script generation in progress")

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_video_scripts(video_id)
            _set_task_status(video_id, result.get("status", "unknown"), result.get("error"))
        except Exception as e:
            _set_task_status(video_id, "failed", str(e))
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

    if video["status"] != "ready_for_video_generation":
        raise HTTPException(
            status_code=400,
            detail=f"Video not ready for video generation (status: {video['status']})",
        )

    if _get_task_status(video_id):
        raise HTTPException(status_code=409, detail="Task already running")

    _set_task_status(video_id, "running", "Video clip generation in progress")

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_video_generation(video_id)
            _set_task_status(video_id, result.get("status", "unknown"), result.get("error"))
        except Exception as e:
            _set_task_status(video_id, "failed", str(e))
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
    """Generate thumbnail for a video."""
    video = await fetch_one(
        "SELECT id, status FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    if video["status"] != "ready_for_thumbnail":
        raise HTTPException(
            status_code=400,
            detail=f"Video not ready for thumbnail (status: {video['status']})",
        )

    if _get_task_status(video_id):
        raise HTTPException(status_code=409, detail="Task already running")

    _set_task_status(video_id, "running", "Thumbnail generation in progress")

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_thumbnail(video_id)
            _set_task_status(video_id, result.get("status", "unknown"), result.get("error"))
        except Exception as e:
            _set_task_status(video_id, "failed", str(e))
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
    video = await fetch_one(
        "SELECT id, status FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    if video["status"] != "ready_to_render":
        raise HTTPException(
            status_code=400,
            detail=f"Video not ready to render (status: {video['status']})",
        )

    if _get_task_status(video_id):
        raise HTTPException(status_code=409, detail="Task already running")

    _set_task_status(video_id, "running", "Rendering in progress")

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_render(video_id)
            _set_task_status(video_id, result.get("status", "unknown"), result.get("error"))
        except Exception as e:
            _set_task_status(video_id, "failed", str(e))
        finally:
            await asyncio.sleep(30)
            _clear_task_status(video_id)

    background_tasks.add_task(_run)

    return PipelineResponse(video_id=video_id, status="running", message="Render started")


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

    _set_task_status(video_id, "running", "Running next step")

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_next_step(video_id)
            _set_task_status(video_id, result.get("status", "unknown"), result.get("error") or result.get("message"))
        except Exception as e:
            _set_task_status(video_id, "failed", str(e))
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
        return {"status": "idle", "message": None}
    return task
