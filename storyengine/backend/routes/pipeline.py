"""Pipeline trigger routes - Execute pipeline stages from the web UI.

All pipeline operations run as background tasks so the API responds immediately.
The frontend can poll for status or use the activity feed to track progress.

Task tracking uses a dual-layer approach:
- In-memory dict for fast real-time progress (sync-compatible with progress callbacks)
- Database table (background_tasks) for persistence across restarts and task history
"""

import asyncio
import json
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

from auth import get_tenant_id
from database import fetch_one, fetch_all, execute
from error_utils import humanize_error, USER_FACING_PREFIX
from pipeline_executor import PipelineExecutor
from status_map import to_supabase, to_pipeline, get_next_status_supabase, is_at_or_past_stage, stage_enabled_in_plan, friendly_state
from job_queue import enqueue_stage
from task_store import db_persist_task
import actions

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


class MachineScriptPreviewRequest(BaseModel):
    machine: str


class MachineScriptBlockRequest(BaseModel):
    machine: str


class MachineResearchRequest(BaseModel):
    machine: str


class PipelineStatus(BaseModel):
    """Current pipeline status for a video."""
    video_id: str
    status: str
    status_display: str
    next_action: Optional[str] = None
    airtable_synced: bool = False


# --- Pipeline Readiness Check ---

PIPELINE_REQUIRED_KEYS = [
    {"key": "kie_ai_api_key", "label": "Kie.ai", "reason": "Images, video, voice narration, and Claude (scripts, research, analysis)", "url": "https://kie.ai"},
]

PIPELINE_OPTIONAL_KEYS = [
    {"key": "anthropic_api_key", "label": "Anthropic (Claude)", "reason": "Claude runs through your Kie.ai key — add only for direct Anthropic access", "url": "https://console.anthropic.com"},
    {"key": "elevenlabs_api_key", "label": "ElevenLabs API Key", "reason": "Voice runs through your Kie.ai key — add for custom/cloned ElevenLabs voices", "url": "https://elevenlabs.io"},
    {"key": "elevenlabs_voice_id", "label": "ElevenLabs Voice ID", "reason": "Custom voice selection — Kie voice roster is used otherwise", "url": "https://elevenlabs.io"},
    {"key": "openai_api_key", "label": "OpenAI (Whisper)", "reason": "Audio transcription for captions — pipeline still runs without it", "url": "https://platform.openai.com"},
    {"key": "gemini_api_key", "label": "Gemini", "reason": "Thumbnail analysis — skipped without this", "url": "https://aistudio.google.com"},
]


@router.get("/readiness")
async def check_pipeline_readiness(tenant_id: str = Depends(get_tenant_id)):
    """Check if tenant has all required API keys for pipeline execution."""
    from vault import get_secret_status

    missing = []
    configured = []

    for key_info in PIPELINE_REQUIRED_KEYS:
        status = await get_secret_status(key_info["key"], tenant_id)
        if status.get("configured"):
            configured.append(key_info["key"])
        else:
            missing.append(key_info)

    warnings = []
    for key_info in PIPELINE_OPTIONAL_KEYS:
        status = await get_secret_status(key_info["key"], tenant_id)
        if not status.get("configured"):
            warnings.append(key_info)

    return {
        "ready": len(missing) == 0,
        "missing_keys": missing,
        "configured_keys": configured,
        "warnings": warnings,
    }


# --- Background Task Tracking (dual-layer: dict + DB) ---
import time as _time

_running_tasks: dict[tuple[str, str], dict] = {}

# --- parallel side lanes ------------------------------------------------------
# Voice, characters, environments and thumbnail are independent of each other
# (none reads another's output), so they may run AT THE SAME TIME on one
# video. Everything else - script, storyboards, images, clips, render, the
# build/run-next orchestrators - is the exclusive "main" lane: it is upstream
# (script feeds voice) or downstream (storyboards need approved cast +
# environments) of the side lanes, so main blocks while ANY lane is active,
# and every side lane blocks while main is active.
import contextvars as _contextvars

_task_lane: "_contextvars.ContextVar[str]" = _contextvars.ContextVar("task_lane", default="main")
_side_lanes: dict[tuple[str, str], dict[str, float]] = {}


def _lane_begin(video_id: str, tenant_id: str, lane: str) -> None:
    """Mark a side-lane task as in flight (and tag this context's status
    writes with the lane so displays/clears don't cross wires)."""
    _task_lane.set(lane)
    _side_lanes.setdefault((tenant_id, video_id), {})[lane] = _time.time()


def _lane_finish(video_id: str, tenant_id: str, lane: str) -> None:
    lanes = _side_lanes.get((tenant_id, video_id))
    if lanes:
        lanes.pop(lane, None)
        if not lanes:
            _side_lanes.pop((tenant_id, video_id), None)

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
        elif status in ("completed", "failed", "cancelled"):
            # 'cancelled' also closes the marker row the cancel endpoint wrote
            # (status='cancelled', completed_at NULL) — setting completed_at
            # consumes the cancel request so future runs start clean.
            await execute(
                "UPDATE background_tasks "
                "SET status = $1, message = $2, error_message = $3, completed_at = now() "
                "WHERE video_id = $4 AND (status = 'running' "
                "      OR (status = 'cancelled' AND completed_at IS NULL))",
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


# Stale threshold (minutes) for the periodic reaper. Must exceed the longest
# arq job timeout (7200s = 2h for images/render) — a live job is killed by arq
# at 2h, so anything still 'running'/'pending' past 3h is a true zombie left by
# a dead worker process, which would otherwise block a 1-job-plan tenant forever.
STALE_TASK_THRESHOLD_MIN = 180


async def reap_stale_running_tasks(max_age_minutes: int = STALE_TASK_THRESHOLD_MIN) -> int:
    """Fail tasks stuck 'running'/'pending' past the threshold (periodic).

    recover_stale_tasks() only runs at API startup; if a WORKER process dies
    mid-stage, its background_tasks row stays 'running' and — on free/starter
    plans (concurrent_jobs=1) — blocks ALL further generation for that tenant
    until the API restarts. This runs on a timer so the tenant auto-unblocks.
    """
    try:
        result = await execute(
            "UPDATE background_tasks SET status = 'failed', "
            "error_message = 'Timed out — the worker didn''t finish this stage. Run it again.', "
            "completed_at = now() "
            "WHERE status IN ('running', 'pending') "
            "  AND started_at < now() - make_interval(mins => $1)",
            max_age_minutes,
        )
        count = int(result.split()[-1]) if result else 0
        if count:
            logger.warning("[reaper] failed %d stale task(s) older than %dmin", count, max_age_minutes)
        return count
    except Exception:
        return 0


def _set_task_status(
    video_id: str,
    status: str,
    message: Optional[str] = None,
    error: Optional[str] = None,
    *,
    tenant_id: str,
    task_type: str = "pipeline",
):
    """Update task status in dict. Fire-and-forget DB persistence for key transitions.

    Keyed by (tenant_id, video_id) to prevent cross-tenant task state leaks
    (SEC-SSE-001). tenant_id is now required; a missing tenant is a program
    bug, not a recoverable runtime state.

    Normalizes status to: running | completed | failed
    ('cancelled' reads as completed to pollers — the message tells the story —
    but persists as 'cancelled' in background_tasks for history.)
    """
    db_status = None
    # Normalize: anything not running/failed is completed
    if status == "cancelled":
        normalized = "completed"
        db_status = "cancelled"
        if not message:
            message = "Stopped — completed work was kept. Run the stage again to resume."
    elif status not in ("running", "failed"):
        normalized = "completed"
    else:
        normalized = status
    resolved_error = error
    resolved_message = message
    # user_facing() markers are consumed by humanize_error on the error path;
    # strip them from the message path too so the raw marker never shows.
    if resolved_message and resolved_message.startswith(USER_FACING_PREFIX):
        resolved_message = resolved_message[len(USER_FACING_PREFIX):]
    if normalized == "failed" and not resolved_error:
        resolved_error = resolved_message
    # Humanize failure errors at the write boundary so raw str(e) from
    # ~15 call sites never reaches the UI via /task-status polling.
    # The raw error is logged to WARNING with a [humanize_error] prefix
    # inside humanize_error() for dev debugging.
    if normalized == "failed" and resolved_error:
        resolved_error = humanize_error(resolved_error)
    key = (tenant_id, video_id)
    previous = _running_tasks.get(key)
    _running_tasks[key] = {
        "status": normalized,
        "message": resolved_message,
        "error": resolved_error,
        "lane": _task_lane.get(),
        "started_at": (previous or {}).get("started_at", _time.time()),
    }

    # A run is STARTING (no live entry before): consume any stale cancel
    # request now, at the chokepoint every stage passes through. Doing this in
    # the executor raced with real Stop requests that arrived in the seconds
    # between task start and executor arm-up (live-test find: the cancel was
    # eaten and 74 images generated anyway).
    if normalized == "running" and (not previous or previous.get("status") != "running"):
        try:
            from cancel_registry import reset_for_new_run
            asyncio.get_running_loop().create_task(reset_for_new_run(tenant_id, video_id))
        except RuntimeError:
            pass

    # Persist key transitions to DB (fire-and-forget)
    if normalized in ("running", "completed", "failed"):
        try:
            asyncio.get_running_loop().create_task(
                _db_persist_task(
                    str(tenant_id), video_id, task_type,
                    db_status or normalized, resolved_message, resolved_error,
                )
            )
        except RuntimeError:
            pass  # No event loop — skip DB write


def _get_task_status(video_id: str, tenant_id: str) -> Optional[dict]:
    """Get task status for a video within a tenant. Auto-clears stale tasks.

    Sync-only: returns None for queue-dispatched jobs (no in-memory entry).
    Use _get_task_status_async for DB fallback when Redis/arq is in use.
    """
    key = (tenant_id, video_id)
    task = _running_tasks.get(key)
    if task:
        # Auto-clear stale tasks (older than 10 minutes and still "running")
        if task["status"] == "running" and _time.time() - task.get("started_at", 0) > _STALE_TASK_SECONDS:
            _running_tasks.pop(key, None)
            return None
        return task
    return None


def _is_task_active(video_id: str, tenant_id: str, lane: str = "main") -> bool:
    """True only while a task is actually in flight IN A CONFLICTING LANE.

    Start-guards must use THIS, not _get_task_status truthiness:
    completed/failed entries linger ~30s for the UI pill, and
    truthiness-guards were 409-ing follow-up actions.

    lane="main" (default, exclusive): blocked while main is running OR any
    side lane is active. Side lanes (voice/characters/environments/thumbnail):
    blocked only by themselves or by main - so voice can run while
    environments generate."""
    now = _time.time()
    lanes = _side_lanes.get((tenant_id, video_id), {})
    for l, t0 in list(lanes.items()):
        if now - t0 > _STALE_TASK_SECONDS:
            lanes.pop(l, None)  # a killed worker must never wedge the video
    task = _get_task_status(video_id, tenant_id)
    main_running = bool(
        task and task.get("status") in ("running", "pending")
        and task.get("lane", "main") == "main"
    )
    if lane == "main":
        return main_running or bool(lanes)
    return (lane in lanes) or main_running


async def _get_task_status_async(video_id: str, tenant_id: str) -> Optional[dict]:
    """Async version: check in-memory dict first, then DB for queue jobs."""
    task = _get_task_status(video_id, tenant_id)
    if task:
        return task

    # Check background_tasks table for queue-dispatched jobs
    row = await fetch_one(
        "SELECT status, message, error_message FROM background_tasks "
        "WHERE video_id = $1 AND tenant_id = $2 AND status IN ('pending', 'running') "
        "ORDER BY created_at DESC LIMIT 1",
        video_id, tenant_id,
    )
    if row:
        return {
            "status": row["status"],
            "message": row.get("message"),
            "error": row.get("error_message"),
        }
    return None


def _clear_task_status(video_id: str, tenant_id: str):
    """Clear task status after completion (dict only — DB row stays for history).

    Never clears a RUNNING entry: each task's deferred 30s cleanup would
    otherwise wipe a newer task that started in the meantime (live-test find —
    the poller went blind mid-generation).
    """
    entry = _running_tasks.get((tenant_id, video_id))
    if entry and entry.get("lane", "main") != _task_lane.get():
        # Another lane's status is on display - leave it alone.
        return
    if entry and entry.get("status") == "running":
        return
    _running_tasks.pop((tenant_id, video_id), None)


# Human-readable names for the optional stages a creator can switch off at
# creation. Used when refusing a manual trigger for a turned-off stage.
_STAGE_LABELS = {
    "research": "Research",
    "voice": "AI voice-over",
    "sound": "Sound design",
    "video": "Video clips",
    "thumbnail": "Thumbnail",
    "render": "Final render",
    "upload": "YouTube upload",
}


def _require_stage_enabled(video: dict, stage: str):
    """Refuse a manual trigger for a stage the creator turned OFF for this video.

    The per-video stage plan (pipeline_stages) is the source of truth for which
    steps run. The status-advance chokepoint already reroutes the pipeline AROUND
    disabled stages, and the UI hides their tabs — but a direct POST to a stage's
    trigger endpoint would still run the bot and persist an artifact (burning
    credits on a step the creator switched off). This is the defense-in-depth
    gate at the endpoint. Full-pipeline videos (no plan) are never affected.

    The video row must include the `pipeline_stages` column.
    """
    if not stage_enabled_in_plan(stage, video.get("pipeline_stages")):
        label = _STAGE_LABELS.get(stage, stage)
        raise HTTPException(
            status_code=400,
            detail=f"{label} is turned off for this video — it was switched off when the video was created.",
        )


def _get_arq_pool(request: Request):
    """Get arq pool from app state, or None if not connected."""
    return getattr(request.app.state, "arq", None)


async def _enqueue_or_fallback(
    request: Request,
    background_tasks: BackgroundTasks,
    stage: str,
    video_id: str,
    tenant_id: str,
    fallback_fn,
):
    """Enqueue to arq queue if available, otherwise fall back to BackgroundTasks."""
    arq_pool = _get_arq_pool(request)
    if arq_pool:
        try:
            attempt = 1
            job_id = await enqueue_stage(arq_pool, stage, video_id, tenant_id, attempt)
            if job_id:
                await db_persist_task(
                    tenant_id, video_id, stage, "pending",
                    message=f"{stage} queued — job_id={job_id}",
                    job_id=job_id, attempt=attempt,
                )
            return
        except Exception as e:
            logger.warning(
                "arq enqueue failed for %s/%s, falling back to BackgroundTasks: %s",
                stage, video_id, e,
            )
            # fall through to BackgroundTasks below
    # Redis not available or enqueue failed — fall back to in-process BackgroundTasks
    background_tasks.add_task(fallback_fn)


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
    request: Request,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Run research agent on a video idea.

    Runs in background via arq queue (falls back to BackgroundTasks if Redis unavailable).
    Poll /status/{video_id} or check activity feed.
    """
    video = await fetch_one(
        "SELECT id, status, pipeline_stages FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    _require_stage_enabled(video, "research")

    if _is_task_active(video_id, tenant_id):
        raise HTTPException(status_code=409, detail="Task already running for this video")

    _set_task_status(video_id, "running", "Research in progress", tenant_id=tenant_id)

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_research(video_id)
            _set_task_status(video_id, result.get("status", "unknown"), result.get("error"), tenant_id=tenant_id)
        except Exception as e:
            logger.exception("[research] fallback task failed video=%s: %s", video_id, e)
            _set_task_status(video_id, "failed", str(e), tenant_id=tenant_id)
        finally:
            await asyncio.sleep(30)
            _clear_task_status(video_id, tenant_id)

    await _enqueue_or_fallback(request, background_tasks, "research", video_id, tenant_id, _run)

    return PipelineResponse(
        video_id=video_id,
        status="running",
        message="Research started",
    )


@router.post("/script/{video_id}", response_model=PipelineResponse)
async def run_script(
    video_id: str,
    request: Request,
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

    if _is_task_active(video_id, tenant_id):
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
            _clear_task_status(video_id, tenant_id)

    await _enqueue_or_fallback(request, background_tasks, "script", video_id, tenant_id, _run)

    return PipelineResponse(video_id=video_id, status="running", message="Script generation started")


@router.post("/machine-script-preview/{video_id}")
async def run_machine_script_preview(
    video_id: str,
    body: MachineScriptPreviewRequest,
    tenant_id: str = Depends(get_tenant_id),
):
    """Generate one isolated machine paragraph; never mutates production script rows or video status."""
    machine = body.machine.strip()
    if not machine:
        raise HTTPException(status_code=400, detail="machine is required")
    executor = PipelineExecutor(tenant_id)
    try:
        result = await executor.run_machine_script_preview(video_id, machine)
    except Exception as e:
        raise HTTPException(status_code=400, detail=humanize_error(e)) from e
    if result.get("status") == "failed":
        raise HTTPException(status_code=400, detail=result.get("error") or "Preview generation failed")
    return result


@router.post("/machine-script-block/{video_id}")
async def run_machine_script_block(
    video_id: str,
    body: MachineScriptBlockRequest,
    tenant_id: str = Depends(get_tenant_id),
):
    """Generate one machine paragraph and save it as the real script scene when it passes."""
    machine = body.machine.strip()
    if not machine:
        raise HTTPException(status_code=400, detail="machine is required")
    executor = PipelineExecutor(tenant_id)
    try:
        result = await executor.run_machine_script_block(video_id, machine)
    except Exception as e:
        raise HTTPException(status_code=400, detail=humanize_error(e)) from e
    if result.get("status") == "failed":
        raise HTTPException(status_code=400, detail=result.get("error") or "Machine script block generation failed")
    return result


@router.post("/machine-research-one/{video_id}")
async def run_one_machine_research(
    video_id: str,
    body: MachineResearchRequest,
    tenant_id: str = Depends(get_tenant_id),
):
    """Research one locked machine and save its compact card without advancing the full queue."""
    machine = body.machine.strip()
    if not machine:
        raise HTTPException(status_code=400, detail="machine is required")
    executor = PipelineExecutor(tenant_id)
    result = await executor.run_one_machine_research(video_id, machine)
    if result.get("status") == "failed":
        raise HTTPException(status_code=400, detail=result.get("error") or "Machine research failed")
    return result


@router.post("/machine-research/{video_id}", response_model=PipelineResponse)
async def run_machine_research(
    video_id: str,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Research the existing locked machine roster without rerunning roster discovery."""
    video = await fetch_one(
        "SELECT id, research_payload FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    if _is_task_active(video_id, tenant_id):
        raise HTTPException(status_code=409, detail="Task already running for this video")

    _set_task_status(video_id, "running", "Researching locked machines", tenant_id=tenant_id)

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_unit_research(video_id)
            _set_task_status(
                video_id,
                result.get("status", "unknown"),
                result.get("message") or result.get("error"),
                tenant_id=tenant_id,
            )
        except Exception as e:
            logger.exception("[machine-research] task failed video=%s: %s", video_id, e)
            _set_task_status(video_id, "failed", str(e), tenant_id=tenant_id)
        finally:
            await asyncio.sleep(30)
            _clear_task_status(video_id, tenant_id)

    background_tasks.add_task(_run)
    return PipelineResponse(video_id=video_id, status="running", message="Machine research started")


@router.post("/voice/{video_id}", response_model=PipelineResponse)
async def run_voice(
    video_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    scene: Optional[int] = None,
    tenant_id: str = Depends(get_tenant_id),
):
    """Generate voice narration for a video.

    Video must be at 'ready_for_voice' status unless scene is specified
    (targeted single-scene regen bypasses status gate).
    """
    video = await fetch_one(
        "SELECT id, status, pipeline_stages FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    _require_stage_enabled(video, "voice")

    if scene is None and not is_at_or_past_stage(video["status"], "ready_for_voice"):
        raise HTTPException(
            status_code=400,
            detail=f"Video not ready for voice (status: {video['status']})",
        )

    if _is_task_active(video_id, tenant_id, lane="voice"):
        raise HTTPException(status_code=409, detail="Task already running")

    _lane_begin(video_id, tenant_id, "voice")
    _set_task_status(video_id, "running", "Voice generation in progress", tenant_id=tenant_id)

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_voice(video_id, scene=scene)
            _set_task_status(video_id, result.get("status", "unknown"), result.get("error"), tenant_id=tenant_id)
        except Exception as e:
            _set_task_status(video_id, "failed", str(e), tenant_id=tenant_id)
        finally:
            _lane_finish(video_id, tenant_id, "voice")
            await asyncio.sleep(30)
            _clear_task_status(video_id, tenant_id)

    if scene is not None:
        # Targeted single-scene regen — keep in-process
        background_tasks.add_task(_run)
    else:
        await _enqueue_or_fallback(request, background_tasks, "voice", video_id, tenant_id, _run)

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
        raise HTTPException(
            status_code=500,
            detail=humanize_error(e, context="We couldn't split the scenes"),
        )


@router.post("/prompts/{video_id}", response_model=PipelineResponse)
async def run_prompts(
    video_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    scene: Optional[int] = None,
    index: Optional[int] = None,
    tenant_id: str = Depends(get_tenant_id),
):
    """Generate image prompts for a video.

    Video must be at 'ready_for_image_prompts' status unless scene is specified
    (targeted single-scene or single-segment regen bypasses status gate).
    """
    # DEPRECATED (Phase 0 unify, 2026-06-29): the old 3x3 grid path is retired.
    # Image/storyboard generation now runs through the unified coverage pipeline
    # (run_coverage_stage). Delete this raise to restore the old path.
    raise HTTPException(
        status_code=410,
        detail="Retired endpoint. Image prompts now run through the unified coverage pipeline (Scenes tab).",
    )
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

    if _is_task_active(video_id, tenant_id):
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
            _clear_task_status(video_id, tenant_id)

    if scene is not None:
        # Targeted regen — keep in-process
        background_tasks.add_task(_run)
    else:
        await _enqueue_or_fallback(request, background_tasks, "image_prompts", video_id, tenant_id, _run)

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
    request: Request,
    background_tasks: BackgroundTasks,
    scene: Optional[int] = None,
    tenant_id: str = Depends(get_tenant_id),
):
    """Generate storyboard prompts for a video.

    Args:
        scene: If set, only generate prompts for this scene (per-scene mode).
    """
    # DEPRECATED (Phase 0 unify, 2026-06-29): retired in favor of the unified
    # coverage pipeline. Delete this raise to restore the old grid path.
    raise HTTPException(
        status_code=410,
        detail="Retired endpoint. Storyboards now run through the unified coverage pipeline (Scenes tab).",
    )
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

    if _is_task_active(video_id, tenant_id):
        raise HTTPException(status_code=409, detail="Task already running")

    scene_label = f" Scene {scene}" if scene else ""
    _set_task_status(video_id, "running", f"Generating storyboard prompts{scene_label}...", tenant_id=tenant_id)

    def progress_callback(msg: str):
        _set_task_status(video_id, "running", msg, tenant_id=tenant_id)

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
            _clear_task_status(video_id, tenant_id)

    if scene is not None:
        # Targeted per-scene — keep in-process (needs progress_callback)
        background_tasks.add_task(_run)
    else:
        await _enqueue_or_fallback(request, background_tasks, "storyboards", video_id, tenant_id, _run)

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

    if _is_task_active(video_id, tenant_id):
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
            _clear_task_status(video_id, tenant_id)

    background_tasks.add_task(_run)

    return PipelineResponse(video_id=video_id, status="running", message="Story Bible generation started")


@router.post("/storyboard-images/{video_id}", response_model=PipelineResponse)
async def run_storyboard_images(
    video_id: str,
    background_tasks: BackgroundTasks,
    scene: Optional[int] = None,
    beat: Optional[int] = None,
    plan_only: bool = False,
    tenant_id: str = Depends(get_tenant_id),
):
    """Generate storyboard images for a video.

    Relaxed status gate: allows manual triggering from UI as long as voice
    has been generated (storyboard prompts need image prompts which need voice).

    Args:
        scene: If set, only generate images for this scene (per-scene mode).
        beat: If set (requires scene), redraw ONLY that board slot (1-5) from
            the scene's saved plan — never re-plans the scene.
        plan_only: Plan the shots and persist the board placeholders, draw
            NOTHING — the creator reviews the plan, then draws board by board.
    """
    if beat is not None and (scene is None or not 1 <= beat <= 5):
        raise HTTPException(status_code=400,
                            detail="beat needs a scene and must be between 1 and 5")
    if plan_only and beat is not None:
        raise HTTPException(status_code=400, detail="plan_only and beat are mutually exclusive")
    # NOTE: this route was retired in the Phase-0 unify (2026-06-29), then
    # REWIRED to the one-sheet storyboard preview below — but the deprecation
    # raise was left in, making the new body unreachable ("Retired endpoint"
    # toast on the Scenes tab, found live 2026-07-02). Removed.
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

    if _is_task_active(video_id, tenant_id):
        raise HTTPException(status_code=409, detail="Task already running")

    scene_label = f" Scene {scene}" if scene else ""
    _set_task_status(video_id, "running", f"Generating storyboard images{scene_label}...", tenant_id=tenant_id)

    def progress_callback(msg: str):
        _set_task_status(video_id, "running", msg, tenant_id=tenant_id)

    async def _run():
        try:
            # Storyboard = ONE GPT Image 2 image (the whole sheet) — a cheap, fast preview of the
            # story direction. The real per-shot images come later (generate_coverage_for_video).
            from scripts.coverage_to_app import generate_storyboard_sheet_for_scene
            result = await generate_storyboard_sheet_for_scene(
                video_id, tenant_id, scene=scene, beat=beat, plan_only=plan_only,
                progress=progress_callback
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
            _clear_task_status(video_id, tenant_id)

    background_tasks.add_task(_run)

    return PipelineResponse(video_id=video_id, status="running", message=f"Coverage generation started{scene_label}")


@router.post("/coverage-images/{video_id}", response_model=PipelineResponse)
async def run_coverage_images(
    video_id: str,
    background_tasks: BackgroundTasks,
    scene: Optional[int] = None,
    tenant_id: str = Depends(get_tenant_id),
):
    """Generate the REAL per-shot coverage images for a scene (master + matched angles),
    anchored on the locked cast. This is the step AFTER the cheap one-image storyboard
    preview: the storyboard answers 'do I like the direction?', this draws the actual pictures.

    Args:
        scene: If set, only generate coverage for this scene (per-scene mode).
    """
    video = await fetch_one(
        "SELECT id, status FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    # Per-scene generation bypasses the status gate (same relaxed rule as storyboard-images).
    if scene is None and not is_at_or_past_stage(video["status"], "ready_for_image_prompts"):
        raise HTTPException(
            status_code=400,
            detail=f"Video not ready for scene images — voice must be generated first (status: {video['status']})",
        )

    if _is_task_active(video_id, tenant_id):
        raise HTTPException(status_code=409, detail="Task already running")

    scene_label = f" Scene {scene}" if scene else ""
    _set_task_status(video_id, "running", f"Generating scene images{scene_label}...", tenant_id=tenant_id)

    def progress_callback(msg: str):
        _set_task_status(video_id, "running", msg, tenant_id=tenant_id)

    async def _run():
        try:
            # The real per-shot coverage frames (master + matched angles), stored as scene assets.
            from scripts.coverage_to_app import generate_coverage_for_video
            result = await generate_coverage_for_video(
                video_id, tenant_id, scene=scene, progress=progress_callback
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
            _clear_task_status(video_id, tenant_id)

    background_tasks.add_task(_run)

    return PipelineResponse(video_id=video_id, status="running", message=f"Scene image generation started{scene_label}")


@router.post("/stitch-scene/{video_id}", response_model=PipelineResponse)
async def run_stitch_scene(
    video_id: str,
    background_tasks: BackgroundTasks,
    scene: int,
    tenant_id: str = Depends(get_tenant_id),
):
    """FFmpeg-concat one scene's animated clips into a single video so the creator
    can watch the whole scene. Stored on scripts.scene_video_url; re-stitch replaces
    it in place. The final render concats these per-scene stitches."""
    video = await fetch_one(
        "SELECT id FROM videos WHERE id = $1 AND tenant_id = $2", video_id, tenant_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    if _is_task_active(video_id, tenant_id):
        raise HTTPException(status_code=409, detail="Task already running")

    _set_task_status(video_id, "running", f"Stitching Scene {scene}...", tenant_id=tenant_id)

    def progress_callback(msg: str):
        _set_task_status(video_id, "running", msg, tenant_id=tenant_id)

    async def _run():
        try:
            from render_stitch import stitch_video

            async def _p(msg: str):
                progress_callback(msg)

            res = await stitch_video(video_id, tenant_id, scene=scene, on_progress=_p)
            await execute(
                "UPDATE scripts SET scene_video_url = $1, updated_at = now() "
                "WHERE video_id = $2 AND scene = $3 AND tenant_id = $4",
                res["final_video_url"], video_id, scene, tenant_id,
            )
            _set_task_status(
                video_id, "completed",
                f"Scene {scene} stitched — {res['duration_seconds']}s, {res['clip_count']} clips",
                tenant_id=tenant_id,
            )
        except Exception as e:
            _set_task_status(video_id, "failed", str(e), str(e), tenant_id=tenant_id)
        finally:
            await asyncio.sleep(15)
            _clear_task_status(video_id, tenant_id)

    background_tasks.add_task(_run)
    return PipelineResponse(video_id=video_id, status="running", message=f"Stitching Scene {scene}")


@router.post("/redraw-image/{video_id}", response_model=PipelineResponse)
async def run_redraw_image(
    video_id: str,
    background_tasks: BackgroundTasks,
    asset_id: str,
    tenant_id: str = Depends(get_tenant_id),
):
    """Redraw ONE picture from its (edited) image_prompt, anchored on the locked cast
    sheets. Clears the picture's stale clip. GPT Image 2."""
    video = await fetch_one(
        "SELECT id FROM videos WHERE id = $1 AND tenant_id = $2", video_id, tenant_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    if _is_task_active(video_id, tenant_id):
        raise HTTPException(status_code=409, detail="Task already running")

    _set_task_status(video_id, "running", "Redrawing picture...", tenant_id=tenant_id)

    def progress_callback(msg: str):
        _set_task_status(video_id, "running", msg, tenant_id=tenant_id)

    async def _run():
        try:
            from scripts.coverage_to_app import redraw_asset_image
            result = await redraw_asset_image(video_id, tenant_id, asset_id, progress=progress_callback)
            _set_task_status(
                video_id, result.get("status", "unknown"),
                result.get("message") or result.get("error"), result.get("error"),
                tenant_id=tenant_id,
            )
        except Exception as e:
            _set_task_status(video_id, "failed", str(e), str(e), tenant_id=tenant_id)
        finally:
            await asyncio.sleep(15)
            _clear_task_status(video_id, tenant_id)

    background_tasks.add_task(_run)
    return PipelineResponse(video_id=video_id, status="running", message="Redrawing picture")


@router.post("/storyboard-extract/{video_id}", response_model=PipelineResponse)
async def run_storyboard_extract(
    video_id: str,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Extract frames from storyboard grids."""
    # DEPRECATED (Phase 0 unify, 2026-06-29): retired in favor of the unified
    # coverage pipeline. Delete this raise to restore the old grid path.
    raise HTTPException(
        status_code=410,
        detail="Retired endpoint. Frame extraction now runs through the unified coverage pipeline (Scenes tab).",
    )
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

    if _is_task_active(video_id, tenant_id):
        raise HTTPException(status_code=409, detail="Task already running")

    _set_task_status(video_id, "running", "Storyboard extraction in progress", tenant_id=tenant_id)

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)

            async def _progress(msg: str):
                _set_task_status(video_id, "running", msg, tenant_id=tenant_id)

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
            _clear_task_status(video_id, tenant_id)

    background_tasks.add_task(_run)

    return PipelineResponse(video_id=video_id, status="running", message="Storyboard extraction started")


@router.post("/dialogue-voice/{video_id}", response_model=PipelineResponse)
async def run_dialogue_voice(
    video_id: str,
    background_tasks: BackgroundTasks,
    scene: Optional[int] = None,
    tenant_id: str = Depends(get_tenant_id),
):
    """Synthesize per-segment voices for a dialogue-mode video.

    Walks scripts.dialogue_segments: narrator voice for narration entries,
    the character's cast voice for dialogue lines. Resume-safe (already-voiced
    segments are skipped). Narration-only videos complete as a no-op.

    Args:
        scene: If set, only voice this scene's segments (taste-test mode).
    """
    video = await fetch_one(
        "SELECT id, status, pipeline_stages FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    _require_stage_enabled(video, "voice")

    if not is_at_or_past_stage(video["status"], "ready_for_voice"):
        raise HTTPException(
            status_code=400,
            detail=f"Video needs a script before voices can be made (status: {video['status']})",
        )

    if _is_task_active(video_id, tenant_id, lane="voice"):
        raise HTTPException(status_code=409, detail="Task already running")

    scene_label = f" (scene {scene})" if scene else ""
    _lane_begin(video_id, tenant_id, "voice")
    _set_task_status(video_id, "running", f"Voicing dialogue segments{scene_label}...", tenant_id=tenant_id)

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)

            async def _progress(msg: str):
                _set_task_status(video_id, "running", msg, tenant_id=tenant_id)

            result = await executor.run_dialogue_voice(
                video_id, scene=scene, progress_callback=_progress
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
            _lane_finish(video_id, tenant_id, "voice")
            await asyncio.sleep(30)
            _clear_task_status(video_id, tenant_id)

    background_tasks.add_task(_run)

    return PipelineResponse(video_id=video_id, status="running", message=f"Dialogue voice synthesis started{scene_label}")


@router.post("/clip/{video_id}", response_model=PipelineResponse)
async def run_clip(
    video_id: str,
    background_tasks: BackgroundTasks,
    asset_id: Optional[str] = None,
    scene: Optional[int] = None,
    force: bool = False,
    tenant_id: str = Depends(get_tenant_id),
):
    """Animate final pictures into motion clips.

    The trust ladder's single entry point: asset_id = tap one card,
    scene = Animate this scene, neither = Animate everything.
    force=true regenerates a card that already has a clip (Redo).
    """
    video = await fetch_one(
        "SELECT id, status, pipeline_stages FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    _require_stage_enabled(video, "video")

    # Relaxed gate (the lessons pattern): finals can exist from extraction onward —
    # the executor itself only animates assets that HAVE a picture. A TARGETED animate
    # (one card via asset_id, or one scene) only needs that picture to exist, so it
    # bypasses the global status gate — same as the other per-scene stage gates. The
    # status check applies only to "animate everything" (coverage leaves the status at
    # ready_for_image_prompts even though the pictures exist).
    if asset_id is None and scene is None and not is_at_or_past_stage(video["status"], "ready_for_images"):
        raise HTTPException(
            status_code=400,
            detail=f"Final pictures must exist before clips (status: {video['status']})",
        )

    if _is_task_active(video_id, tenant_id):
        raise HTTPException(status_code=409, detail="Task already running")

    label = "Animating a clip" if asset_id else f"Animating scene {scene}" if scene is not None else "Animating all clips"
    _set_task_status(video_id, "running", f"{label}...", tenant_id=tenant_id)

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)

            async def _progress(msg: str):
                _set_task_status(video_id, "running", msg, tenant_id=tenant_id)

            result = await executor.run_clip_generation(
                video_id, asset_id=asset_id, scene=scene, force=force,
                progress_callback=_progress,
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
            _clear_task_status(video_id, tenant_id)

    background_tasks.add_task(_run)

    return PipelineResponse(video_id=video_id, status="running", message=f"{label} started")


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

    if _is_task_active(video_id, tenant_id):
        raise HTTPException(status_code=409, detail="Task already running")

    _set_task_status(video_id, "running", "Panel upscaling in progress", tenant_id=tenant_id)

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)

            async def _progress(msg: str):
                _set_task_status(video_id, "running", msg, tenant_id=tenant_id)

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
            _clear_task_status(video_id, tenant_id)

    background_tasks.add_task(_run)

    return PipelineResponse(video_id=video_id, status="running", message="Panel upscaling started")


@router.post("/images/{video_id}", response_model=PipelineResponse)
async def run_images(
    video_id: str,
    request: Request,
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
    # DEPRECATED (Phase 0 unify, 2026-06-29): the old grid image path is retired.
    # Image generation now runs through the unified coverage pipeline
    # (run_coverage_stage). Delete this raise to restore the old path.
    raise HTTPException(
        status_code=410,
        detail="Retired endpoint. Image generation now runs through the unified coverage pipeline (Scenes tab).",
    )
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

    if _is_task_active(video_id, tenant_id):
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
            _clear_task_status(video_id, tenant_id)

    if scene is not None or (variants is not None and variants > 1):
        # Targeted regen or variant generation — keep in-process
        background_tasks.add_task(_run)
    else:
        await _enqueue_or_fallback(request, background_tasks, "images", video_id, tenant_id, _run)

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
    request: Request,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Generate sound design prompts for a video."""
    video = await fetch_one(
        "SELECT id, status, pipeline_stages FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    _require_stage_enabled(video, "sound")

    if not is_at_or_past_stage(video["status"], "ready_for_sound_design"):
        raise HTTPException(
            status_code=400,
            detail=f"Video not ready for sound design (status: {video['status']})",
        )

    if _is_task_active(video_id, tenant_id):
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
            _clear_task_status(video_id, tenant_id)

    await _enqueue_or_fallback(request, background_tasks, "sound_prompts", video_id, tenant_id, _run)

    return PipelineResponse(video_id=video_id, status="running", message="Sound prompt generation started")


@router.post("/sound-effects/{video_id}", response_model=PipelineResponse)
async def run_sound_effects(
    video_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Generate sound effects for a video."""
    video = await fetch_one(
        "SELECT id, status, pipeline_stages FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    _require_stage_enabled(video, "sound")

    if not is_at_or_past_stage(video["status"], "ready_for_sound_effects"):
        raise HTTPException(
            status_code=400,
            detail=f"Video not ready for sound effects (status: {video['status']})",
        )

    if _is_task_active(video_id, tenant_id):
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
            _clear_task_status(video_id, tenant_id)

    await _enqueue_or_fallback(request, background_tasks, "sound_effects", video_id, tenant_id, _run)

    return PipelineResponse(video_id=video_id, status="running", message="Sound effects generation started")


@router.post("/video-scripts/{video_id}", response_model=PipelineResponse)
async def run_video_scripts(
    video_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Generate video motion scripts for a video."""
    video = await fetch_one(
        "SELECT id, status, pipeline_stages FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    _require_stage_enabled(video, "video")

    status = video.get("status") or ""
    if status and not is_at_or_past_stage(status, "ready_for_images"):
        raise HTTPException(
            status_code=400,
            detail=f"Video not ready for video scripts — needs images first (status: {status})",
        )

    if _is_task_active(video_id, tenant_id):
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
            _clear_task_status(video_id, tenant_id)

    await _enqueue_or_fallback(request, background_tasks, "video_scripts", video_id, tenant_id, _run)

    return PipelineResponse(video_id=video_id, status="running", message="Video script generation started")


@router.post("/video-generation/{video_id}", response_model=PipelineResponse)
async def run_video_generation(
    video_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Generate video clips for a video."""
    video = await fetch_one(
        "SELECT id, status, pipeline_stages FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    _require_stage_enabled(video, "video")

    status = video.get("status") or ""
    if status and not is_at_or_past_stage(status, "ready_for_video_generation"):
        raise HTTPException(
            status_code=400,
            detail=f"Video not ready for video generation (status: {status})",
        )

    if _is_task_active(video_id, tenant_id):
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
            _clear_task_status(video_id, tenant_id)

    await _enqueue_or_fallback(request, background_tasks, "video_generation", video_id, tenant_id, _run)

    return PipelineResponse(video_id=video_id, status="running", message="Video clip generation started")


@router.post("/thumbnail/{video_id}", response_model=PipelineResponse)
async def run_thumbnail(
    video_id: str,
    request: Request,
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
                  thumbnail_style_override, video_title, pipeline_stages
           FROM videos WHERE id = $1 AND tenant_id = $2""",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    _require_stage_enabled(video, "thumbnail")

    status = video.get("status") or ""
    if status and not is_at_or_past_stage(status, "ready_for_voice"):
        raise HTTPException(
            status_code=400,
            detail=f"Video not ready for thumbnail — needs at least a script (status: {status})",
        )

    if _is_task_active(video_id, tenant_id, lane="thumbnail"):
        raise HTTPException(status_code=409, detail="Task already running")

    _lane_begin(video_id, tenant_id, "thumbnail")
    _set_task_status(video_id, "running", "Thumbnail generation in progress", tenant_id=tenant_id)

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_thumbnail(video_id)
            _set_task_status(video_id, result.get("status", "unknown"), result.get("error"), tenant_id=tenant_id)
        except Exception as e:
            _set_task_status(video_id, "failed", str(e), tenant_id=tenant_id)
        finally:
            _lane_finish(video_id, tenant_id, "thumbnail")
            await asyncio.sleep(30)
            _clear_task_status(video_id, tenant_id)

    await _enqueue_or_fallback(request, background_tasks, "thumbnail", video_id, tenant_id, _run)

    return PipelineResponse(video_id=video_id, status="running", message="Thumbnail generation started")


@router.post("/render/{video_id}", response_model=PipelineResponse)
async def run_render(
    video_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    orientation: str = "auto",
    tenant_id: str = Depends(get_tenant_id),
):
    """Render final video. `orientation` (grok_native stitch only):
    auto|portrait|landscape — 'auto' follows the majority of the clips."""
    if orientation not in ("auto", "portrait", "landscape"):
        orientation = "auto"
    from routes.billing import check_plan_limits
    await check_plan_limits(tenant_id, "render")

    video = await fetch_one(
        "SELECT id, status, pipeline_stages, render_mode FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    _require_stage_enabled(video, "render")

    # Render whatever's been generated: a stitch only needs clips to exist. Allow it
    # once the video is at/past ready_to_render OR any clips have been generated (so a
    # partially-animated video can be stitched into a final from the clips it has).
    # Static documentaries have no clips ever — they need images + narration instead.
    if not is_at_or_past_stage(video["status"], "ready_to_render"):
        if (video.get("render_mode") or "") == "static_docu":
            ready = await fetch_one(
                "SELECT (SELECT count(*) FROM assets WHERE video_id=$1 AND tenant_id=$2 "
                "        AND image_url IS NOT NULL) AS imgs, "
                "       (SELECT count(*) FROM scripts WHERE video_id=$1 AND tenant_id=$2 "
                "        AND voice_over_url IS NOT NULL) AS voiced",
                video_id, tenant_id,
            )
            if not (ready and ready["imgs"] > 0 and ready["voiced"] > 0):
                raise HTTPException(
                    status_code=400,
                    detail=f"Static render needs the images and the voiceover first (status: {video['status']})",
                )
        else:
            clip_row = await fetch_one(
                "SELECT count(*) AS n FROM assets "
                "WHERE video_id = $1 AND tenant_id = $2 AND video_clip_url IS NOT NULL",
                video_id, tenant_id,
            )
            if not (clip_row and clip_row["n"] > 0):
                raise HTTPException(
                    status_code=400,
                    detail=f"No clips generated yet to stitch (status: {video['status']})",
                )

    if _is_task_active(video_id, tenant_id):
        raise HTTPException(status_code=409, detail="Task already running")

    _set_task_status(video_id, "running", "Rendering in progress", tenant_id=tenant_id)

    async def _run():
        try:
            executor = PipelineExecutor(tenant_id)
            result = await executor.run_render(video_id, orientation)
            _set_task_status(video_id, result.get("status", "unknown"), result.get("error"), tenant_id=tenant_id)
        except Exception as e:
            _set_task_status(video_id, "failed", str(e), tenant_id=tenant_id)
        finally:
            await asyncio.sleep(30)
            _clear_task_status(video_id, tenant_id)

    await _enqueue_or_fallback(request, background_tasks, "render", video_id, tenant_id, _run)

    return PipelineResponse(video_id=video_id, status="running", message="Render started")


@router.post("/upload/{video_id}", response_model=PipelineResponse)
async def run_upload(
    video_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Upload video to YouTube as unlisted draft."""
    video = await fetch_one(
        "SELECT id, status, pipeline_stages FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    _require_stage_enabled(video, "upload")

    if not is_at_or_past_stage(video["status"], "rendered"):
        raise HTTPException(
            status_code=400,
            detail=f"Video not ready for upload (status: {video['status']})",
        )

    if _is_task_active(video_id, tenant_id):
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
            _clear_task_status(video_id, tenant_id)

    await _enqueue_or_fallback(request, background_tasks, "upload", video_id, tenant_id, _run)

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

    if _is_task_active(video_id, tenant_id):
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
            _clear_task_status(video_id, tenant_id)

    background_tasks.add_task(_run)

    return PipelineResponse(video_id=video_id, status="running", message="Next step started")


class BuildRequest(BaseModel):
    """Auto-build target: 'pictures' stops at the pictures-review checkpoint,
    'finish' runs the rest (voice, clips, thumbnail, render)."""
    target: str = "pictures"


@router.post("/build/{video_id}", response_model=PipelineResponse)
async def run_build(
    video_id: str,
    background_tasks: BackgroundTasks,
    body: Optional[BuildRequest] = None,
    tenant_id: str = Depends(get_tenant_id),
):
    """Auto-build the pipeline to a checkpoint — the exact chainer chat's
    "build it" / "finish it" uses (actions.make_autobuild_step), now callable
    from a button. PARITY-PLAN Phase 1."""
    target = (body.target if body else "pictures") or "pictures"
    if target not in ("pictures", "finish"):
        raise HTTPException(status_code=400, detail="target must be 'pictures' or 'finish'")

    video = await fetch_one(
        "SELECT id, status FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    if _is_task_active(video_id, tenant_id):
        raise HTTPException(status_code=409, detail="Task already running")

    msg = ("Building to the pictures checkpoint (research, script, pictures)"
           if target == "pictures" else "Finishing the video (voice, clips, thumbnail, render)")
    background_tasks.add_task(actions.make_autobuild_step(
        tenant_id, video_id, target=target, start_msg=f"{msg}…"))
    return PipelineResponse(video_id=video_id, status="running", message=msg)


@router.get("/actions/{video_id}")
async def list_video_actions(
    video_id: str,
    tenant_id: str = Depends(get_tenant_id),
):
    """What can run on this video right now — every verb with its label, real
    server-computed cost, and the plain-English reason it's blocked (or null).
    One source of truth: chat's confirm cards and the page's buttons/Est. Cost
    should both read THIS instead of keeping their own price tables."""
    summary = await actions.video_summary(tenant_id, video_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Video not found")

    out = []
    for verb, cfg in actions.ACTIONS.items():
        blocked = actions.blocked_reason(verb, summary)
        cost, cost_text = await actions.estimate_cost(tenant_id, video_id, verb, None, summary)
        out.append({
            "verb": verb,
            "label": cfg["label"],
            "paid": bool(cfg.get("paid")),
            "needs": cfg.get("needs"),
            "accepts_edit": bool(cfg.get("edit")),
            "blocked": blocked,          # null = runnable now
            "cost": cost,
            "cost_text": cost_text,
        })
    # The build meta-verb's next checkpoint, so a UI button can label itself.
    build_target = "pictures" if summary["status"] in actions.BUILD_TO_PICTURES else "finish"
    return {
        "video_id": video_id, "summary": summary, "build_target": build_target, "actions": out,
        # The raw price table so the frontend never keeps its own copy.
        "prices": {"clip": actions.CLIP_COST, "picture": actions.PICTURE_COST},
    }


class ImprovePromptRequest(BaseModel):
    """Ask the prompt studio for a stronger prompt. Nothing is applied — the
    UI puts the result in the edit box for the creator to review and save."""
    surface: str  # image | motion | thumbnail | script
    current: Optional[str] = None
    direction: Optional[str] = None


@router.post("/improve-prompt/{video_id}")
async def improve_prompt(
    video_id: str,
    body: ImprovePromptRequest,
    tenant_id: str = Depends(get_tenant_id),
):
    """The prompt studio's rewrite, callable from a button (PARITY-PLAN Phase 3).
    Same model-aware rewriter chat uses; returns the proposed prompt text only."""
    if body.surface not in ("image", "motion", "thumbnail", "script"):
        raise HTTPException(status_code=400, detail="surface must be image, motion, thumbnail, or script")
    video = await fetch_one(
        "SELECT id, video_model FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    try:
        from kie_unified import get_text_client_for_tenant
        client = await get_text_client_for_tenant(tenant_id)
    except Exception:  # noqa: BLE001
        client = None
    if client is None:
        raise HTTPException(status_code=400, detail="Add a Kie.ai or Anthropic key in Settings first.")
    model = "claude-sonnet-4-6" if type(client).__name__ == "AnthropicDirectClient" else None
    from routes.chat import _rewrite_prompt
    text = await _rewrite_prompt(
        client, model, body.surface, (body.current or "").strip(),
        (body.direction or "").strip(), video.get("video_model") or "grok-imagine",
    )
    if not text:
        raise HTTPException(status_code=502, detail="Couldn't write a stronger prompt — try again.")
    return {"prompt": text}


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
    task_status = _get_task_status(video_id, tenant_id)
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


@router.post("/cancel/{video_id}")
async def cancel_pipeline_task(
    video_id: str,
    tenant_id: str = Depends(get_tenant_id),
):
    """Stop a running generation for this video.

    Cooperative: the in-flight item finishes, queued items are skipped, all
    completed (paid) work is kept. Running the stage again resumes — the
    existing resume logic only generates what's missing.
    """
    video = await fetch_one(
        "SELECT id FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    from cancel_registry import request_cancel, request_local
    task = _get_task_status(video_id, tenant_id)
    in_memory_running = bool(task and task.get("status") == "running")
    # request_cancel only flips DB rows that are 'running'; the local flag is
    # set only when we know a task is live — flagging when nothing runs would
    # plant a stale cancel for the next run.
    marked_db = await request_cancel(tenant_id, video_id, set_local=in_memory_running)

    if not in_memory_running and not marked_db:
        return {"status": "not_running", "message": "Nothing is running for this video."}

    return {
        "status": "cancelling",
        "message": "Stopping — the current item will finish, then generation halts. Completed work is kept.",
    }


@router.get("/task/{video_id}")
async def get_task_status(
    video_id: str,
    tenant_id: str = Depends(get_tenant_id),
):
    """Get background task status for a video.

    Used for polling while a stage is running.
    Checks in-memory dict first, then DB for queue-dispatched jobs.
    """
    task = await _get_task_status_async(video_id, tenant_id)
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
        "SELECT id, status, pipeline_stages FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    _require_stage_enabled(video, "video")

    if _is_task_active(video_id, tenant_id):
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
            _clear_task_status(video_id, tenant_id)

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
    _clear_task_status(video_id, tenant_id)
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
    # DEPRECATED (PARITY-PLAN Phase 4, 2026-07-01): the legacy orchestrator is a
    # fourth door that bypasses the confirm-card cost gating. The copilot chat
    # (POST /api/chat) + the shared action layer (actions.py) replaced it.
    # Delete this raise to restore the old path.
    raise HTTPException(
        status_code=410,
        detail="Retired endpoint. Use the co-pilot chat (POST /api/chat) or POST /api/pipeline/build.",
    )
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
    # DEPRECATED (PARITY-PLAN Phase 4, 2026-07-01): superseded by the copilot
    # chat + GET /api/pipeline/actions (what can run, costs, blocked reasons).
    # Delete this raise to restore the old path.
    raise HTTPException(
        status_code=410,
        detail="Retired endpoint. Use GET /api/pipeline/actions/{video_id} or the co-pilot chat.",
    )
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
            "reasoning": humanize_error(e, context="The orchestrator hit a snag planning your next step"),
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
                    "friendly": friendly_state(t.get("current_status") or t.get("to_status") or ""),
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

            # 2. Poll task progress (from in-memory _running_tasks).
            # Every path MUST filter by tenant_id — _running_tasks is keyed by
            # (tenant_id, video_id) and iterating without a tenant filter used
            # to leak other tenants' task state (SEC-SSE-001).
            if video_id:
                task = _get_task_status(video_id, tenant_id)
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
                for (tid, vid), task in list(_running_tasks.items()):
                    if tid != tenant_id:
                        continue
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
