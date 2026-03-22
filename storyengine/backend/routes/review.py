"""Review/approval queue endpoint."""

from fastapi import APIRouter, Depends
from auth import get_tenant_id
from models import PendingReview
from database import fetch_all

router = APIRouter(prefix="/api/review", tags=["review"])


@router.get("/pending", response_model=PendingReview)
async def get_pending(tenant_id: str = Depends(get_tenant_id)):
    """All items needing human review — scripts, storyboards, thumbnails, images."""

    # Scripts pending: videos in ready_for_voice status (script needs approval)
    scripts = await fetch_all(
        """SELECT v.id, v.title, v.status, v.script,
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
            "title": s["title"],
            "word_count": len(s["script"].split()) if s.get("script") else 0,
            "type": "script",
        }
        for s in scripts
    ]

    # Storyboard grids pending
    storyboards = await fetch_all(
        """SELECT a.id, a.video_id, a.url, a.scene_number, a.metadata,
                  v.title as video_title
           FROM assets a
           JOIN videos v ON v.id = a.video_id
           WHERE a.tenant_id = $1 AND a.asset_type = 'storyboard_grid' AND a.status = 'pending'
           ORDER BY a.created_at DESC""",
        tenant_id,
    )
    storyboard_items = [
        {
            "asset_id": str(s["id"]),
            "video_id": str(s["video_id"]),
            "title": s["video_title"],
            "url": s["url"],
            "scene_number": s.get("scene_number"),
            "type": "storyboard",
        }
        for s in storyboards
    ]

    # Thumbnails pending
    thumbnails = await fetch_all(
        """SELECT a.id, a.video_id, a.url, a.prompt, a.metadata,
                  v.title as video_title
           FROM assets a
           JOIN videos v ON v.id = a.video_id
           WHERE a.tenant_id = $1 AND a.asset_type = 'thumbnail' AND a.status = 'pending'
           ORDER BY a.created_at DESC""",
        tenant_id,
    )
    thumbnail_items = [
        {
            "asset_id": str(s["id"]),
            "video_id": str(s["video_id"]),
            "title": s["video_title"],
            "url": s["url"],
            "prompt": s.get("prompt"),
            "type": "thumbnail",
        }
        for s in thumbnails
    ]

    # Images pending
    images = await fetch_all(
        """SELECT a.id, a.video_id, a.url, a.scene_number, a.image_index, a.prompt,
                  v.title as video_title
           FROM assets a
           JOIN videos v ON v.id = a.video_id
           WHERE a.tenant_id = $1 AND a.asset_type = 'image' AND a.status = 'pending'
           ORDER BY a.scene_number, a.image_index""",
        tenant_id,
    )
    image_items = [
        {
            "asset_id": str(s["id"]),
            "video_id": str(s["video_id"]),
            "title": s["video_title"],
            "url": s["url"],
            "scene_number": s.get("scene_number"),
            "image_index": s.get("image_index"),
            "prompt": s.get("prompt"),
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
