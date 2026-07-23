"""Persistent job queue — thin wrapper over arq pool stored on app.state."""
from __future__ import annotations
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from arq import ArqRedis

logger = logging.getLogger(__name__)

# Stage -> arq function name map (must match worker.py handler names)
_STAGE_HANDLERS: dict[str, str] = {
    "research":         "arq_run_research",
    "script":           "arq_run_script",
    "voice":            "arq_run_voice",
    "image_prompts":    "arq_run_image_prompts",
    "storyboards":      "arq_run_storyboards",
    "images":           "arq_run_images",
    "sound_prompts":    "arq_run_sound_prompts",
    "sound_effects":    "arq_run_sound_effects",
    "video_scripts":    "arq_run_video_scripts",
    "video_generation": "arq_run_video_generation",
    "thumbnail":        "arq_run_thumbnail",
    "render":           "arq_run_render",
    "upload":           "arq_run_upload",
    "custom_film_runtime": "arq_run_custom_film_runtime",
}


def make_job_id(stage: str, video_id: str, attempt: int) -> str:
    """Idempotency key: prevents double-billing on retry."""
    return f"{stage}:{video_id}:{attempt}"


async def enqueue_stage(
    arq_pool: "ArqRedis",
    stage: str,
    video_id: str,
    tenant_id: str,
    attempt: int = 1,
    **stage_kwargs,
) -> str | None:
    """Enqueue a pipeline stage. Returns job_id or None if already queued.

    `**stage_kwargs` (C16d, S7-3) is forwarded as extra kwargs on the arq job
    (e.g. thumbnail's `force`) — arq passes *args/**kwargs straight through
    to the worker function, so the matching `arq_run_*` handler in worker.py
    must declare a same-named parameter to receive it. Stages that pass
    nothing behave exactly as before.
    """
    handler = _STAGE_HANDLERS.get(stage)
    if not handler:
        raise ValueError(f"Unknown stage: {stage!r}. Valid: {list(_STAGE_HANDLERS)}")
    if stage == "custom_film_runtime" and not stage_kwargs.get("runtime_job_id"):
        raise ValueError("custom_film_runtime requires its durable runtime_job_id")

    job_id = make_job_id(stage, video_id, attempt)
    job = await arq_pool.enqueue_job(
        handler,
        video_id,
        tenant_id,
        attempt,
        _job_id=job_id,
        _job_timeout=7200,  # 2h max per stage (render can be long)
        **stage_kwargs,
    )
    if job is None:
        logger.info("Stage %s for %s already queued (attempt=%d)", stage, video_id, attempt)
        return None

    logger.info("Enqueued %s for video %s — job_id=%s", stage, video_id, job_id)
    return job_id
