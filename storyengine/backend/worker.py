"""arq worker — pipeline stage handlers.

Run with:
    arq backend.worker.WorkerSettings
"""
from __future__ import annotations
import logging
import os
from arq.connections import RedisSettings
from arq.worker import func

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")


# -- shared startup/shutdown ---------------------------------------------------

async def on_startup(ctx: dict) -> None:
    """Initialize shared resources for all worker jobs."""
    from database import get_pool
    ctx["db"] = await get_pool()
    logger.info("arq worker started")


async def on_shutdown(ctx: dict) -> None:
    """Clean up shared resources."""
    if "db" in ctx:
        await ctx["db"].close()
    logger.info("arq worker shut down")


# -- shared stage runner -------------------------------------------------------

async def _run_stage(
    ctx: dict,
    stage: str,
    executor_method: str,
    video_id: str,
    tenant_id: str,
    attempt: int,
) -> dict:
    """Shared implementation for all stage handlers."""
    from pipeline_executor import PipelineExecutor
    from task_store import db_persist_task

    logger.info(
        "[%s] starting video=%s attempt=%d try=%d",
        stage, video_id, attempt, ctx["job_try"],
    )

    # Mark running in background_tasks table
    job_id = f"{stage}:{video_id}:{attempt}"
    await db_persist_task(
        tenant_id, video_id, stage, "running",
        message=f"{stage} running (attempt {attempt})",
        job_id=job_id, attempt=attempt,
    )

    try:
        executor = PipelineExecutor(tenant_id)
        method = getattr(executor, executor_method)
        result = await method(video_id)

        status = result.get("status", "unknown")
        if status == "failed":
            error_msg = result.get("error", "Stage returned failed status")
            await db_persist_task(
                tenant_id, video_id, stage, "failed",
                error=error_msg, job_id=job_id, attempt=attempt,
            )
            raise RuntimeError(error_msg)

        await db_persist_task(
            tenant_id, video_id, stage, "completed",
            message=f"{stage} complete (attempt {attempt})",
            job_id=job_id, attempt=attempt,
        )
        logger.info("[%s] completed video=%s", stage, video_id)
        return result or {"status": "completed"}

    except Exception as exc:
        error_msg = str(exc)
        logger.exception("[%s] failed video=%s: %s", stage, video_id, error_msg)
        await db_persist_task(
            tenant_id, video_id, stage, "failed",
            error=error_msg, job_id=job_id, attempt=attempt,
        )
        raise  # arq will retry up to max_tries


# -- individual stage handlers ------------------------------------------------

async def arq_run_script(ctx: dict, video_id: str, tenant_id: str, attempt: int) -> dict:
    return await _run_stage(ctx, "script", "run_script", video_id, tenant_id, attempt)


async def arq_run_voice(ctx: dict, video_id: str, tenant_id: str, attempt: int) -> dict:
    return await _run_stage(ctx, "voice", "run_voice", video_id, tenant_id, attempt)


async def arq_run_image_prompts(ctx: dict, video_id: str, tenant_id: str, attempt: int) -> dict:
    return await _run_stage(ctx, "image_prompts", "run_prompts", video_id, tenant_id, attempt)


async def arq_run_storyboards(ctx: dict, video_id: str, tenant_id: str, attempt: int) -> dict:
    return await _run_stage(ctx, "storyboards", "run_storyboard_prompts", video_id, tenant_id, attempt)


async def arq_run_images(ctx: dict, video_id: str, tenant_id: str, attempt: int) -> dict:
    return await _run_stage(ctx, "images", "run_images", video_id, tenant_id, attempt)


async def arq_run_sound_prompts(ctx: dict, video_id: str, tenant_id: str, attempt: int) -> dict:
    return await _run_stage(ctx, "sound_prompts", "run_sound_prompts", video_id, tenant_id, attempt)


async def arq_run_sound_effects(ctx: dict, video_id: str, tenant_id: str, attempt: int) -> dict:
    return await _run_stage(ctx, "sound_effects", "run_sound_effects", video_id, tenant_id, attempt)


async def arq_run_video_scripts(ctx: dict, video_id: str, tenant_id: str, attempt: int) -> dict:
    return await _run_stage(ctx, "video_scripts", "run_video_scripts", video_id, tenant_id, attempt)


async def arq_run_video_generation(ctx: dict, video_id: str, tenant_id: str, attempt: int) -> dict:
    return await _run_stage(ctx, "video_generation", "run_video_generation", video_id, tenant_id, attempt)


async def arq_run_thumbnail(ctx: dict, video_id: str, tenant_id: str, attempt: int) -> dict:
    return await _run_stage(ctx, "thumbnail", "run_thumbnail", video_id, tenant_id, attempt)


async def arq_run_render(ctx: dict, video_id: str, tenant_id: str, attempt: int) -> dict:
    return await _run_stage(ctx, "render", "run_render", video_id, tenant_id, attempt)


async def arq_run_upload(ctx: dict, video_id: str, tenant_id: str, attempt: int) -> dict:
    return await _run_stage(ctx, "upload", "run_upload", video_id, tenant_id, attempt)


# -- WorkerSettings -----------------------------------------------------------

_redis_host = REDIS_URL.replace("redis://", "").split(":")[0]
_redis_port_str = REDIS_URL.replace("redis://", "").split(":")[-1].split("/")[0]
_redis_port = int(_redis_port_str) if _redis_port_str.isdigit() else 6379


class WorkerSettings:
    on_startup = on_startup
    on_shutdown = on_shutdown

    redis_settings = RedisSettings(host=_redis_host, port=_redis_port)

    functions = [
        func(arq_run_script,           name="arq_run_script",           timeout=3600, max_tries=3),
        func(arq_run_voice,            name="arq_run_voice",            timeout=3600, max_tries=3),
        func(arq_run_image_prompts,    name="arq_run_image_prompts",    timeout=1800, max_tries=3),
        func(arq_run_storyboards,      name="arq_run_storyboards",      timeout=1800, max_tries=3),
        func(arq_run_images,           name="arq_run_images",           timeout=7200, max_tries=2),  # expensive
        func(arq_run_sound_prompts,    name="arq_run_sound_prompts",    timeout=1800, max_tries=3),
        func(arq_run_sound_effects,    name="arq_run_sound_effects",    timeout=1800, max_tries=3),
        func(arq_run_video_scripts,    name="arq_run_video_scripts",    timeout=1800, max_tries=3),
        func(arq_run_video_generation, name="arq_run_video_generation", timeout=7200, max_tries=2),  # expensive
        func(arq_run_thumbnail,        name="arq_run_thumbnail",        timeout=1800, max_tries=3),
        func(arq_run_render,           name="arq_run_render",           timeout=7200, max_tries=2),  # long render
        func(arq_run_upload,           name="arq_run_upload",           timeout=1800, max_tries=3),
    ]

    max_jobs = 5
    job_timeout = 3600
    keep_result = 86400       # 24h result retention
    health_check_interval = 300
