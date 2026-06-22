"""Review/approval queue endpoint."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from auth import get_tenant_id
from models import PendingReview
from database import fetch_all, fetch_one, execute

router = APIRouter(prefix="/api/review", tags=["review"])


class RejectRequest(BaseModel):
    reason: Optional[str] = None


class BulkApproveRequest(BaseModel):
    script_ids: List[str]


@router.get("/pending", response_model=PendingReview)
async def get_pending(tenant_id: str = Depends(get_tenant_id)):
    """All items needing human review — scripts, storyboards, thumbnails, images."""

    # Scripts pending: videos in ready_for_voice status (script needs approval)
    scripts = await fetch_all(
        """SELECT v.id, v.video_title, v.status, v.script,
                  LENGTH(v.script) as char_count
           FROM videos v
           WHERE v.tenant_id = $1
           AND v.status = 'ready_for_voice'
           AND v.script IS NOT NULL
           ORDER BY v.updated_at DESC""",
        tenant_id,
    )
    script_items = [
        {
            "video_id": str(s["id"]),
            "title": s["video_title"],
            "word_count": len(s["script"].split()) if s.get("script") else 0,
            "type": "script",
        }
        for s in scripts
    ]

    # Storyboard grids pending — from scripts table (storyboard_1/2/3_url)
    storyboards = await fetch_all(
        """SELECT s.id, s.video_id, s.storyboard_1_url, s.storyboard_2_url,
                  s.storyboard_3_url, s.scene, s.storyboard_status,
                  v.video_title
           FROM scripts s
           JOIN videos v ON v.id = s.video_id
           WHERE s.tenant_id = $1
           AND s.storyboard_on_off = 'On'
           AND s.storyboard_status IS NOT NULL
           AND s.storyboard_status NOT IN ('approved', 'rejected')
           AND s.storyboard_1_url IS NOT NULL
           ORDER BY s.created_at DESC""",
        tenant_id,
    )
    storyboard_items = [
        {
            "script_id": str(s["id"]),
            "video_id": str(s["video_id"]),
            "title": s["video_title"],
            "storyboard_1_url": s.get("storyboard_1_url"),
            "storyboard_2_url": s.get("storyboard_2_url"),
            "storyboard_3_url": s.get("storyboard_3_url"),
            "scene": s.get("scene"),
            "type": "storyboard",
        }
        for s in storyboards
    ]

    # Thumbnails pending — from videos table
    thumbnails = await fetch_all(
        """SELECT v.id, v.video_title, v.thumbnail_url, v.thumbnail_prompt
           FROM videos v
           WHERE v.tenant_id = $1
           AND v.status = 'ready_for_thumbnail'
           AND v.thumbnail_url IS NOT NULL
           ORDER BY v.updated_at DESC""",
        tenant_id,
    )
    thumbnail_items = [
        {
            "video_id": str(s["id"]),
            "title": s["video_title"],
            "url": s["thumbnail_url"],
            "prompt": s.get("thumbnail_prompt"),
            "type": "thumbnail",
        }
        for s in thumbnails
    ]

    # Images pending — from assets table
    images = await fetch_all(
        """SELECT a.id, a.video_id, a.image_url, a.scene, a.image_index, a.image_prompt,
                  v.video_title
           FROM assets a
           JOIN videos v ON v.id = a.video_id
           WHERE a.tenant_id = $1 AND a.status = 'pending'
           ORDER BY a.scene, a.image_index""",
        tenant_id,
    )
    image_items = [
        {
            "asset_id": str(s["id"]),
            "video_id": str(s["video_id"]),
            "title": s["video_title"],
            "url": s["image_url"],
            "scene": s.get("scene"),
            "image_index": s.get("image_index"),
            "prompt": s.get("image_prompt"),
            "type": "image",
        }
        for s in images
    ]

    return PendingReview(
        scripts=script_items,
        storyboards=storyboard_items,
        thumbnails=thumbnail_items,
        images=image_items,
    )


@router.post("/storyboard/{script_id}/approve")
async def approve_storyboard(script_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Approve a storyboard — sets storyboard_status to 'approved'."""
    row = await fetch_one(
        "SELECT id FROM scripts WHERE id = $1 AND tenant_id = $2",
        script_id, tenant_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Script not found")

    await execute(
        "UPDATE scripts SET storyboard_status = 'approved', updated_at = now() WHERE id = $1 AND tenant_id = $2",
        script_id, tenant_id,
    )
    return {"status": "approved", "script_id": script_id}


@router.post("/storyboard/{script_id}/reject")
async def reject_storyboard(
    script_id: str,
    body: RejectRequest = RejectRequest(),
    tenant_id: str = Depends(get_tenant_id),
):
    """Reject a storyboard — sets storyboard_status to 'rejected' and clears grids."""
    row = await fetch_one(
        "SELECT id FROM scripts WHERE id = $1 AND tenant_id = $2",
        script_id, tenant_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Script not found")

    await execute(
        """UPDATE scripts SET
             storyboard_status = 'rejected',
             storyboard_1_url = NULL,
             storyboard_2_url = NULL,
             storyboard_3_url = NULL,
             storyboard_4_url = NULL,
             storyboard_5_url = NULL,
             updated_at = now()
           WHERE id = $1 AND tenant_id = $2""",
        script_id, tenant_id,
    )
    return {"status": "rejected", "script_id": script_id}


@router.post("/storyboard/approve-all")
async def approve_all_storyboards(
    body: BulkApproveRequest,
    tenant_id: str = Depends(get_tenant_id),
):
    """Bulk-approve multiple storyboards."""
    approved = []
    for script_id in body.script_ids:
        row = await fetch_one(
            "SELECT id FROM scripts WHERE id = $1 AND tenant_id = $2",
            script_id, tenant_id,
        )
        if row:
            await execute(
                "UPDATE scripts SET storyboard_status = 'approved', updated_at = now() WHERE id = $1 AND tenant_id = $2",
                script_id, tenant_id,
            )
            approved.append(script_id)
    return {"status": "approved", "approved_count": len(approved), "script_ids": approved}
