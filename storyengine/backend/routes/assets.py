"""Asset approval/rejection endpoints."""

import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from auth import get_tenant_id
from models import AssetApproval, BatchApproval
from database import fetch_one, fetch_all, execute

# shared.channel_profile lives in the pipeline package, not the SaaS backend
# (same sys.path pattern as routes/model_registry.py / actions.py).
_PIPELINE_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "skills" / "video-pipeline"
if str(_PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_ROOT))

from shared.channel_profile import MODEL_REGISTRY  # noqa: E402
from image_prompts.engine.camera_moves import get_move  # noqa: E402

router = APIRouter(prefix="/api/assets", tags=["assets"])


class VideoPromptUpdate(BaseModel):
    video_prompt: str


class ImagePromptUpdate(BaseModel):
    image_prompt: str


class ModelOverrideUpdate(BaseModel):
    # Pydantic warns on any field starting with "model_" (its own reserved
    # namespace for model_config/model_validate/etc) — this name matches the
    # DB column (assets.model_override, migration 090) on purpose, so opt
    # this one model out of that namespace check instead of renaming the field.
    model_config = {"protected_namespaces": ()}

    # A wired MODEL_REGISTRY id to force this scene's clip through, or None/
    # "" to clear the override and fall back to the router's own
    # recommendation (checklist §1.2/C14). Both the sheet's picks and its
    # "Use recommendation" clear button go through this one field.
    model_override: Optional[str] = None


class CameraPresetUpdate(BaseModel):
    # A camera_moves.py catalog id (e.g. "crash_zoom_in"), or None/"" to
    # clear the override back to Auto — camera_selector.py's earn-the-move
    # decides again (checklist §2.2/C23). Same door for both: the Scenes
    # chip's preset sheet AND the copilot's "use a crash zoom on scene 12"
    # write through this one field.
    camera_preset_id: Optional[str] = None


@router.patch("/{asset_id}/approve")
async def approve_asset(asset_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Approve a single asset."""
    asset = await fetch_one(
        "SELECT id FROM assets WHERE id = $1 AND tenant_id = $2",
        asset_id, tenant_id,
    )
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    await execute(
        "UPDATE assets SET status = 'approved' WHERE id = $1 AND tenant_id = $2",
        asset_id, tenant_id,
    )
    return {"status": "approved"}


@router.patch("/{asset_id}/reject")
async def reject_asset(asset_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Reject a single asset."""
    asset = await fetch_one(
        "SELECT id FROM assets WHERE id = $1 AND tenant_id = $2",
        asset_id, tenant_id,
    )
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    await execute(
        "UPDATE assets SET status = 'rejected' WHERE id = $1 AND tenant_id = $2",
        asset_id, tenant_id,
    )
    return {"status": "rejected"}


@router.patch("/{asset_id}/video-prompt")
async def update_video_prompt(
    asset_id: str, body: VideoPromptUpdate, tenant_id: str = Depends(get_tenant_id)
):
    """Edit a clip's motion prompt before animating (the box under each picture).
    The clip stage reads assets.video_prompt, so this override drives the next animate.

    Clears motion_gate_status (migration 118): a shot the automated motion
    writer BLOCKED (gate rejected it twice — video_prompt left NULL,
    motion_gate_status='blocked') is unblocked the moment a human saves their
    own prompt here — the manual edit IS the unblock, and run_clip_generation
    (pipeline_executor.py) reads motion_gate_status to decide whether to skip
    the row. A row that was never blocked has motion_gate_status already
    NULL, so this is a no-op for every existing save."""
    asset = await fetch_one(
        "SELECT id FROM assets WHERE id = $1 AND tenant_id = $2", asset_id, tenant_id,
    )
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    await execute(
        "UPDATE assets SET video_prompt = $1, motion_gate_status = NULL, updated_at = now() "
        "WHERE id = $2 AND tenant_id = $3",
        body.video_prompt.strip(), asset_id, tenant_id,
    )
    return {"status": "saved"}


@router.patch("/{asset_id}/image-prompt")
async def update_image_prompt(
    asset_id: str, body: ImagePromptUpdate, tenant_id: str = Depends(get_tenant_id)
):
    """Edit a picture's image prompt (the box under each picture). Redraw uses it to
    regenerate just that shot, anchored on the locked cast sheets."""
    asset = await fetch_one(
        "SELECT id FROM assets WHERE id = $1 AND tenant_id = $2", asset_id, tenant_id,
    )
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    await execute(
        "UPDATE assets SET image_prompt = $1, updated_at = now() WHERE id = $2 AND tenant_id = $3",
        body.image_prompt.strip(), asset_id, tenant_id,
    )
    return {"status": "saved"}


@router.patch("/{asset_id}/model-override")
async def update_model_override(
    asset_id: str, body: ModelOverrideUpdate, tenant_id: str = Depends(get_tenant_id)
):
    """Set or clear this scene's manual clip-model override (checklist
    §1.2/C14 — the Scenes workspace badge's one-tap override sheet).

    `resolve_clip_model()` (shared.model_router) already treats this column
    as its first-precedence `scene_override` argument (C13 wired the
    precedence, this endpoint is the first thing that ever writes a
    non-NULL value into it) — writing here is exactly what makes the next
    animate/quote honor the creator's pick over the router's own
    recommendation.

    An empty string or omitted value CLEARS the override (falls back to
    routed_model/video_model); any other value must name a WIRED registry
    model — the same gate run_clip_generation itself enforces, so this can
    never save a choice that would silently no-op at generation time."""
    asset = await fetch_one(
        "SELECT id FROM assets WHERE id = $1 AND tenant_id = $2", asset_id, tenant_id,
    )
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    value = (body.model_override or "").strip() or None
    if value is not None:
        profile = MODEL_REGISTRY.get(value)
        if not profile or not profile.wired:
            raise HTTPException(
                status_code=400,
                detail=f"'{value}' isn't an available clip model — pick one from the wired list.",
            )

    await execute(
        "UPDATE assets SET model_override = $1, updated_at = now() WHERE id = $2 AND tenant_id = $3",
        value, asset_id, tenant_id,
    )
    return {"status": "saved", "model_override": value}


@router.patch("/{asset_id}/camera-preset")
async def update_camera_preset(
    asset_id: str, body: CameraPresetUpdate, tenant_id: str = Depends(get_tenant_id)
):
    """Set or clear this shot's manual camera-move override (checklist §2.2/
    C23 — the Scenes workspace chip's tap-to-change preset sheet, and the
    copilot's "use a crash zoom on scene 12" — same write path, two doors).

    `run_clip_generation._one` (pipeline_executor.py) reads this column at
    CLIP-GENERATION time (not baked in earlier, same shape as model_override/
    migration 090): a non-NULL value's motion_prompt wins outright over the
    auto/"earned" motion composed from assets.camera_movement. An empty
    string or omitted value CLEARS the override (falls back to Auto —
    camera_selector.py decides again on the next animate).

    Any value must name a real camera_moves.py catalog id (the same catalog
    GET /api/camera-presets serves a curated subset of) — never a value
    that would silently no-op at generation time."""
    asset = await fetch_one(
        "SELECT id FROM assets WHERE id = $1 AND tenant_id = $2", asset_id, tenant_id,
    )
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    value = (body.camera_preset_id or "").strip() or None
    if value is not None and not get_move(value):
        raise HTTPException(
            status_code=400,
            detail=f"'{value}' isn't a known camera move — pick one from the preset list.",
        )

    await execute(
        "UPDATE assets SET camera_preset_id = $1, updated_at = now() WHERE id = $2 AND tenant_id = $3",
        value, asset_id, tenant_id,
    )
    return {"status": "saved", "camera_preset_id": value}


@router.post("/batch-approve")
async def batch_approve(body: BatchApproval, tenant_id: str = Depends(get_tenant_id)):
    """Approve or reject multiple assets."""
    if body.status not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="Status must be 'approved' or 'rejected'")

    count = 0
    for asset_id in body.asset_ids:
        result = await execute(
            "UPDATE assets SET status = $1 WHERE id = $2 AND tenant_id = $3",
            body.status, asset_id, tenant_id,
        )
        if result and "UPDATE 1" in result:
            count += 1

    return {"updated": count, "status": body.status}
