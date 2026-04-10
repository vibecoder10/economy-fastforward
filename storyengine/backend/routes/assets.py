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
