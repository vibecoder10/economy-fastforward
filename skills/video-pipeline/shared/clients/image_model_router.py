"""Single source of truth for turning a video's `image_model_override`
("nano-banana-2" | "gpt-image-2" | "z-image" | None/"") into the ImageClient
call that actually draws the image — and for reporting back which model
ACTUALLY produced the pixels, so callers can persist the truth on the asset
row instead of assuming GPT (see storyengine-wiring-fix-checklist.md §0.1,
"the Pictures model select writes image_model_override, but the live path
ignores it").

Used by BOTH of the app's model-selecting call sites so there is exactly ONE
place that decides what an override means — no duplicated branching:
  - storyengine/backend/scripts/coverage_to_app.py
      (redo_characters, generate_storyboard_sheet_for_scene, redraw_asset_image)
  - storyengine/backend/pipeline_executor.py (PipelineExecutor.run_image_variants,
      the legacy Airtable-driven image-variant regen path)

Contract (Ryan's explicit rule): GPT Image 2 is ALWAYS the default (no
override, unrecognized override, or override == 'gpt-image-2') AND the
fallback when an EXPLICIT z-image / nano-banana-2 choice fails or comes back
empty. This mirrors ImageClient.generate_scene_image_gpt's own existing
GPT-then-nano content-policy ladder, which the default branch defers to
completely unchanged.
"""
from __future__ import annotations

from typing import Optional

from orchestrator.pipeline_constants import Models

# The 3 values the Pictures selector writes (ScenesWorkspaceTab.tsx L1121-1126).
VALID_IMAGE_MODELS = {"nano-banana-2", "gpt-image-2", Models.IMAGE_ZIMAGE}


def _urls(reference_urls) -> list:
    """Normalize a single URL / list / None into a clean list of truthy URLs."""
    if not reference_urls:
        return []
    if isinstance(reference_urls, (list, tuple)):
        return [r for r in reference_urls if r]
    return [reference_urls]


def _url_of(res) -> Optional[str]:
    if isinstance(res, dict):
        return res.get("url")
    return res or None


async def _gpt_default(image_client, prompt, refs, aspect_ratio, resolution, task_id_out=None):
    """The pre-existing default path, byte-for-byte: GPT Image 2 (image-to-image
    via generate_thumbnail_gpt2 when refs exist, else generate_scene_image_gpt's
    own text-to-image + content-policy-aware nano-banana-2 fallback)."""
    if refs:
        res = await image_client.generate_thumbnail_gpt2(
            prompt, refs, aspect_ratio, resolution=resolution, task_id_out=task_id_out)
        url = _url_of(res)
        return (url, "gpt-image-2") if url else (None, None)
    res = await image_client.generate_scene_image_gpt(
        prompt, None, aspect_ratio, resolution=resolution, task_id_out=task_id_out)
    url = _url_of(res)
    if not url:
        return None, None
    # generate_scene_image_gpt may itself have silently fallen back to
    # nano-banana-2 on a content-policy block — trust its own report if present.
    model_used = res.get("model", "gpt-image-2") if isinstance(res, dict) else "gpt-image-2"
    return url, model_used


async def generate_scene_image_for_model(
    image_client,
    model_override: Optional[str],
    prompt: str,
    reference_urls=None,
    aspect_ratio: str = "16:9",
    resolution: str = "2K",
    task_id_out: Optional[list] = None,
) -> tuple[Optional[str], Optional[str]]:
    """Draw ONE image honoring `model_override`. Returns (url, model_used) — the
    model actually reflected in `model_used` is what generated the pixels, which
    may differ from `model_override` when a fallback fired. Returns (None, None)
    if every attempt failed.

    - 'z-image': text-to-image only (Kie's z-image has no reference-image
      support, so cast/env reference urls are intentionally NOT sent to it —
      the caller's identity anchor is lost for this model, same as if the
      creator called it directly). Falls back to GPT Image 2 on failure.
    - 'nano-banana-2': reference-aware (generate_with_reference when refs are
      given, else the plain nano-banana-2 text-to-image call). Falls back to
      GPT Image 2 on failure.
    - None / '' / 'gpt-image-2' / any unrecognized value: the EXISTING default
      — see _gpt_default. Unchanged from pre-existing behavior.

    task_id_out: optional list the caller passes in to receive the Kie taskId
    of whichever attempt below succeeds (append, don't assign — same
    fresh-box-per-call pattern the clip path uses, see generate_video's
    docstring). Callers that write ONE generation_ledger row per ONE call to
    this function (redraw_asset_image, run_image_variants) can thread
    box[0] into record_ledger_entry's kie_task_id for real dedup protection
    (checklist C16c / migration 093). Batch callers that aggregate many
    images from many calls into a single ledger row should NOT pass this —
    a single task id can't honestly represent a batch (see migration 093's
    header for the full call-site audit).
    """
    refs = _urls(reference_urls)
    model = (model_override or "").strip()

    if model == Models.IMAGE_ZIMAGE:
        res = await image_client.generate_scene_image_zimage(
            prompt, aspect_ratio=aspect_ratio, task_id_out=task_id_out)
        url = _url_of(res)
        if url:
            return url, Models.IMAGE_ZIMAGE
        return await _gpt_default(image_client, prompt, refs, aspect_ratio, resolution, task_id_out)

    if model == "nano-banana-2":
        if refs:
            res = await image_client.generate_with_reference(
                prompt, refs, aspect_ratio=aspect_ratio, task_id_out=task_id_out)
        else:
            urls = await image_client.generate_and_wait(
                prompt, aspect_ratio, model=image_client.SCENE_MODEL, task_id_out=task_id_out)
            res = {"url": urls[0]} if urls else None
        url = _url_of(res)
        if url:
            return url, "nano-banana-2"
        return await _gpt_default(image_client, prompt, refs, aspect_ratio, resolution, task_id_out)

    # default / 'gpt-image-2' / unrecognized override
    return await _gpt_default(image_client, prompt, refs, aspect_ratio, resolution, task_id_out)
