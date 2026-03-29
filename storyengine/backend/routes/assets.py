"""Asset approval/rejection endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from auth import get_tenant_id
from models import AssetApproval, BatchApproval
from database import fetch_one, fetch_all, execute

router = APIRouter(prefix="/api/assets", tags=["assets"])


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
        "UPDATE assets SET status = 'approved' WHERE id = $1",
        asset_id,
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
        "UPDATE assets SET status = 'rejected' WHERE id = $1",
        asset_id,
    )
    return {"status": "rejected"}


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


@router.post("/{asset_id}/promote-variant")
async def promote_variant(asset_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Promote a variant candidate into the primary asset slot for its scene/index."""
    variant = await fetch_one(
        """SELECT id, video_id, scene, image_index, image_url, drive_image_url, image_prompt,
                  shot_type, hero_shot, sentence_text, panel_position, generation_method
           FROM assets
           WHERE id = $1 AND tenant_id = $2""",
        asset_id, tenant_id,
    )
    if not variant:
        raise HTTPException(status_code=404, detail="Asset not found")

    if variant.get("generation_method") != "variant_candidate":
        raise HTTPException(status_code=400, detail="Only variant candidate assets can be promoted")

    base_asset = await fetch_one(
        """SELECT id
           FROM assets
           WHERE video_id = $1 AND tenant_id = $2 AND scene = $3 AND image_index = $4
             AND (generation_method IS NULL OR generation_method <> 'variant_candidate')
           ORDER BY created_at
           LIMIT 1""",
        variant["video_id"], tenant_id, variant["scene"], variant["image_index"],
    )
    if not base_asset:
        raise HTTPException(status_code=404, detail="Primary asset not found for this variant")

    await execute(
        """UPDATE assets
           SET image_url = $1,
               drive_image_url = $2,
               image_prompt = $3,
               shot_type = $4,
               hero_shot = $5,
               sentence_text = $6,
               status = 'Done',
               updated_at = now()
           WHERE id = $7 AND tenant_id = $8""",
        variant.get("image_url"),
        variant.get("drive_image_url"),
        variant.get("image_prompt"),
        variant.get("shot_type"),
        variant.get("hero_shot") or False,
        variant.get("sentence_text"),
        base_asset["id"],
        tenant_id,
    )

    await execute(
        """UPDATE assets
           SET status = 'promoted',
               generation_method = 'variant_promoted',
               updated_at = now()
           WHERE id = $1 AND tenant_id = $2""",
        asset_id, tenant_id,
    )

    return {
        "status": "promoted",
        "asset_id": str(base_asset["id"]),
        "variant_id": asset_id,
    }
