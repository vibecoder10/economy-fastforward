"""arq worker — pipeline stage handlers.

Run with:
    arq backend.worker.WorkerSettings
"""

from __future__ import annotations
import logging
import os
from urllib.parse import urlparse as _urlparse
from arq.connections import RedisSettings
from arq.worker import func
from job_queue import make_job_id
from error_utils import is_kie_block, humanize_error

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")


def _terminal_failure(error_msg: str) -> bool:
    """A failure that retrying can't fix — skip arq retries (and the wasted
    upstream spend). Today that's a blocked / out-of-credit Kie key."""
    return is_kie_block(error_msg)


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
    **method_kwargs,
) -> dict:
    """Shared implementation for all stage handlers.

    `**method_kwargs` (C16d, S7-3) forwards stage-specific args (e.g.
    thumbnail's `force`) to the executor method — passed straight through
    from the matching `arq_run_*` handler below.
    """
    from pipeline_executor import PipelineExecutor
    from task_store import db_persist_task

    logger.info(
        "[%s] starting video=%s attempt=%d try=%d",
        stage,
        video_id,
        attempt,
        ctx["job_try"],
    )

    # Mark running in background_tasks table
    job_id = make_job_id(stage, video_id, attempt)
    await db_persist_task(
        tenant_id,
        video_id,
        stage,
        "running",
        message=f"{stage} running (attempt {attempt})",
        job_id=job_id,
        attempt=attempt,
    )

    try:
        executor = PipelineExecutor(tenant_id)
        method = getattr(executor, executor_method)
        result = await method(video_id, **method_kwargs)

        status = result.get("status", "unknown")
        if status == "cancelled":
            await db_persist_task(
                tenant_id,
                video_id,
                stage,
                "cancelled",
                message=result.get("error") or "Stopped by user — completed work kept",
                job_id=job_id,
                attempt=attempt,
            )
            logger.info("[%s] cancelled by user video=%s", stage, video_id)
            return result
        if status == "failed":
            error_msg = result.get("error", "Stage returned failed status")
            if _terminal_failure(error_msg):
                # A blocked / out-of-credit Kie key can't be fixed by retrying —
                # persist an actionable message and stop (no arq retry, no budget burn).
                await db_persist_task(
                    tenant_id,
                    video_id,
                    stage,
                    "failed",
                    error=humanize_error(error_msg),
                    job_id=job_id,
                    attempt=attempt,
                )
                logger.warning(
                    "[%s] terminal failure (no retry) video=%s: %s",
                    stage,
                    video_id,
                    error_msg,
                )
                return result
            await db_persist_task(
                tenant_id,
                video_id,
                stage,
                "failed",
                error=error_msg,
                job_id=job_id,
                attempt=attempt,
            )
            raise RuntimeError(error_msg)

        await db_persist_task(
            tenant_id,
            video_id,
            stage,
            "completed",
            message=f"{stage} complete (attempt {attempt})",
            job_id=job_id,
            attempt=attempt,
        )
        logger.info("[%s] completed video=%s", stage, video_id)
        return result or {"status": "completed"}

    except Exception as exc:
        error_msg = str(exc)
        logger.exception("[%s] failed video=%s: %s", stage, video_id, error_msg)
        if _terminal_failure(error_msg):
            # Terminal (blocked Kie key) — persist actionable copy, don't retry.
            await db_persist_task(
                tenant_id,
                video_id,
                stage,
                "failed",
                error=humanize_error(error_msg),
                job_id=job_id,
                attempt=attempt,
            )
            return {"status": "failed", "error": humanize_error(error_msg)}
        await db_persist_task(
            tenant_id,
            video_id,
            stage,
            "failed",
            error=error_msg,
            job_id=job_id,
            attempt=attempt,
        )
        raise  # arq will retry up to max_tries


# -- individual stage handlers ------------------------------------------------


async def arq_run_research(
    ctx: dict, video_id: str, tenant_id: str, attempt: int
) -> dict:
    return await _run_stage(
        ctx, "research", "run_research", video_id, tenant_id, attempt
    )


async def arq_run_script(
    ctx: dict, video_id: str, tenant_id: str, attempt: int
) -> dict:
    return await _run_stage(ctx, "script", "run_script", video_id, tenant_id, attempt)


async def arq_run_voice(ctx: dict, video_id: str, tenant_id: str, attempt: int) -> dict:
    return await _run_stage(ctx, "voice", "run_voice", video_id, tenant_id, attempt)


async def arq_run_image_prompts(
    ctx: dict, video_id: str, tenant_id: str, attempt: int
) -> dict:
    return await _run_stage(
        ctx, "image_prompts", "run_prompts", video_id, tenant_id, attempt
    )


async def arq_run_storyboards(
    ctx: dict, video_id: str, tenant_id: str, attempt: int
) -> dict:
    return await _run_stage(
        ctx, "storyboards", "run_storyboard_prompts", video_id, tenant_id, attempt
    )


async def arq_run_images(
    ctx: dict, video_id: str, tenant_id: str, attempt: int
) -> dict:
    return await _run_stage(ctx, "images", "run_images", video_id, tenant_id, attempt)


async def arq_run_sound_prompts(
    ctx: dict, video_id: str, tenant_id: str, attempt: int
) -> dict:
    return await _run_stage(
        ctx, "sound_prompts", "run_sound_prompts", video_id, tenant_id, attempt
    )


async def arq_run_sound_effects(
    ctx: dict, video_id: str, tenant_id: str, attempt: int
) -> dict:
    return await _run_stage(
        ctx, "sound_effects", "run_sound_effects", video_id, tenant_id, attempt
    )


async def arq_run_video_scripts(
    ctx: dict, video_id: str, tenant_id: str, attempt: int
) -> dict:
    return await _run_stage(
        ctx, "video_scripts", "run_video_scripts", video_id, tenant_id, attempt
    )


async def arq_run_video_generation(
    ctx: dict, video_id: str, tenant_id: str, attempt: int
) -> dict:
    return await _run_stage(
        ctx, "video_generation", "run_video_generation", video_id, tenant_id, attempt
    )


async def arq_run_thumbnail(
    ctx: dict, video_id: str, tenant_id: str, attempt: int, force: bool = False
) -> dict:
    return await _run_stage(
        ctx, "thumbnail", "run_thumbnail", video_id, tenant_id, attempt, force=force
    )


async def arq_run_render(
    ctx: dict, video_id: str, tenant_id: str, attempt: int
) -> dict:
    return await _run_stage(ctx, "render", "run_render", video_id, tenant_id, attempt)


async def arq_run_upload(
    ctx: dict, video_id: str, tenant_id: str, attempt: int, force: bool = False
) -> dict:
    return await _run_stage(
        ctx, "upload", "run_upload", video_id, tenant_id, attempt, force=force
    )


async def arq_run_custom_film_runtime(
    ctx: dict,
    video_id: str,
    tenant_id: str,
    attempt: int,
    runtime_job_id: str,
) -> dict:
    """Consume the durable section schedule through operation-aware seams."""
    from custom_film_contract import CustomFilmContractError
    from custom_film_production_runner import CustomFilmProductionRunner
    from custom_film_section_runtime import consume_runtime_schedule
    from pipeline_executor import PipelineExecutor

    async def _finalize(
        finalizer_tenant_id: str,
        finalizer_video_id: str,
        finalizer_runtime_job_id: str,
        envelope,
    ) -> dict:
        if (
            finalizer_tenant_id != tenant_id
            or finalizer_video_id != video_id
            or finalizer_runtime_job_id != runtime_job_id
            or str(envelope.get("video_id") or "") != video_id
            or str(envelope.get("runtime_hash") or "")
            != runtime_job_id.removeprefix("custom-film-runtime:")
        ):
            raise CustomFilmContractError(
                "Custom Film finalizer runtime identity changed"
            )
        result = await PipelineExecutor(tenant_id).run_render(
            video_id,
            custom_film_runtime_job_id=runtime_job_id,
        )
        if (
            not isinstance(result, dict)
            or result.get("status") != "rendered"
            or not str(result.get("final_video_url") or "").strip()
            or result.get("render_engine") not in {"ffmpeg", "remotion"}
        ):
            raise CustomFilmContractError(
                "Custom Film finalizer returned no exact final artifact"
            )
        return result

    return await consume_runtime_schedule(
        tenant_id,
        video_id,
        runtime_job_id,
        stage_runner=CustomFilmProductionRunner(tenant_id),
        finalizer=_finalize,
        attempt=attempt,
    )


async def arq_run_custom_film_director(
    ctx: dict,
    video_id: str,
    tenant_id: str,
    attempt: int,
    schedule_id: str,
    director_job_id: str,
) -> dict:
    """Run one durable v2 director schedule with no worker-level retry."""
    from custom_film_director_worker import run_reserved_director_stage
    from database import execute
    import drain_mode

    await execute(
        """UPDATE background_tasks
           SET status = 'running', message = 'Writing screenplay and storyboard',
               error_message = NULL, started_at = now()
           WHERE tenant_id = $1 AND video_id = $2 AND job_id = $3
             AND status IN ('pending', 'running')""",
        tenant_id,
        video_id,
        director_job_id,
    )
    try:
        result = await run_reserved_director_stage(
            tenant_id=tenant_id,
            video_id=video_id,
            schedule_id=schedule_id,
            director_job_id=director_job_id,
        )
    except drain_mode.DrainModeActive as exc:
        # No provider call crossed the drain boundary. Preserve the durable
        # outbox and advance its queue identity so the post-drain dispatcher
        # can resume it without colliding with this completed Redis job key.
        await execute(
            """UPDATE background_tasks
               SET status = 'pending',
                   message = 'Waiting for safe deployment to finish',
                   error_message = NULL, completed_at = NULL,
                   attempt = $4
               WHERE tenant_id = $1 AND video_id = $2 AND job_id = $3""",
            tenant_id,
            video_id,
            director_job_id,
            attempt + 1,
        )
        return {
            "status": "deferred",
            "error": exc.message,
            "retryable": True,
        }
    except Exception as exc:  # receipt journal decides whether replay is safe
        message = humanize_error(str(exc))
        await execute(
            """UPDATE background_tasks
               SET status = 'failed', message = NULL, error_message = $4,
                   completed_at = now()
               WHERE tenant_id = $1 AND video_id = $2 AND job_id = $3""",
            tenant_id,
            video_id,
            director_job_id,
            message,
        )
        logger.exception(
            "[custom_film_director] stopped video=%s schedule=%s",
            video_id,
            schedule_id,
        )
        return {"status": "failed", "error": message}
    await execute(
        """UPDATE background_tasks
           SET status = 'completed', message = 'Screenplay and storyboard complete',
               error_message = NULL, completed_at = now()
           WHERE tenant_id = $1 AND video_id = $2 AND job_id = $3""",
        tenant_id,
        video_id,
        director_job_id,
    )
    return result


async def arq_run_scene_storyboards(
    ctx: dict, video_id: str, tenant_id: str, attempt: int, schedule_id: str
) -> dict:
    """Consume one exact five-shot schedule; ARQ itself never retries it."""
    from custom_film_scene_storyboards import execute_run
    return await execute_run(schedule_id)


# -- WorkerSettings -----------------------------------------------------------

_parsed = _urlparse(REDIS_URL)
_redis_host = _parsed.hostname or "localhost"
_redis_port = _parsed.port or 6379


class WorkerSettings:
    on_startup = on_startup
    on_shutdown = on_shutdown

    redis_settings = RedisSettings(host=_redis_host, port=_redis_port)

    functions = [
        func(arq_run_research, name="arq_run_research", timeout=3600, max_tries=3),
        func(arq_run_script, name="arq_run_script", timeout=3600, max_tries=3),
        func(arq_run_voice, name="arq_run_voice", timeout=3600, max_tries=3),
        func(
            arq_run_image_prompts,
            name="arq_run_image_prompts",
            timeout=1800,
            max_tries=3,
        ),
        func(
            arq_run_storyboards, name="arq_run_storyboards", timeout=1800, max_tries=3
        ),
        func(
            arq_run_images, name="arq_run_images", timeout=7200, max_tries=2
        ),  # expensive
        func(
            arq_run_sound_prompts,
            name="arq_run_sound_prompts",
            timeout=1800,
            max_tries=3,
        ),
        func(
            arq_run_sound_effects,
            name="arq_run_sound_effects",
            timeout=1800,
            max_tries=3,
        ),
        func(
            arq_run_video_scripts,
            name="arq_run_video_scripts",
            timeout=1800,
            max_tries=3,
        ),
        func(
            arq_run_video_generation,
            name="arq_run_video_generation",
            timeout=7200,
            max_tries=2,
        ),  # expensive
        func(arq_run_thumbnail, name="arq_run_thumbnail", timeout=1800, max_tries=3),
        func(
            arq_run_render, name="arq_run_render", timeout=7200, max_tries=2
        ),  # long render
        func(arq_run_upload, name="arq_run_upload", timeout=1800, max_tries=3),
        func(
            arq_run_custom_film_runtime,
            name="arq_run_custom_film_runtime",
            timeout=7200,
            max_tries=3,
        ),
        func(
            arq_run_custom_film_director,
            name="arq_run_custom_film_director",
            timeout=7200,
            max_tries=1,
        ),
        func(
            arq_run_scene_storyboards,
            name="arq_run_scene_storyboards",
            timeout=7200,
            max_tries=1,
        ),
    ]

    max_jobs = 5
    job_timeout = 3600
    keep_result = 86400  # 24h result retention
    health_check_interval = 300
