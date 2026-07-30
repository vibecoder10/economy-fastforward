"""Review/approval queue endpoint."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from auth import get_tenant_id
from models import PendingReview, ArbiterFindings
from database import fetch_all, fetch_one, execute

# D8 chunk 3b: the Findings tab's own natural read bound — arbiter_findings
# is an append-only per-instance log (one row per judged frame/panel, every
# time a scene's board sheet lands), so an unscoped SELECT would grow
# unbounded over the video's lifetime. Most-recent-first, capped, mirrors
# the "recent activity feed" shape the rest of this endpoint's two other
# lists already are (both are already naturally small: one row per CLASS of
# defect, one row per video/scene aggregate).
_FINDING_INSTANCES_LIMIT = 200

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


@router.get("/findings", response_model=ArbiterFindings)
async def get_findings(tenant_id: str = Depends(get_tenant_id)):
    """Frame Arbiter findings feed (D5 chunk A7, storyengine/FRAME-ARBITER-
    PLAN.md; per-instance rows added D8 chunk 3b). A3/A3b's judge calls
    (frame_arbiter.judge_frame / judge_scene_batch / judge_board_sheet)
    return per-frame/per-panel finding dicts (image reference, description,
    classification) — D8-3 found that, at the time, those only ever lived
    in the HTTP response of the call that produced them: frame_arbiter_hook.
    run_after_storyboard_sheet attached that dict to run_storyboard_sheet's
    own return value, which task_store.db_persist_task never persisted (a
    status + a message STRING only, no JSON payload). D8-3b closed that gap
    (migrations/146_arbiter_findings.sql + frame_arbiter_hook.py's own write
    call, see that module) — this endpoint now reports THREE real,
    persisted things:
      * A2's `arbiter_fingerprints` (migration 139) — one row per CLASS of
        defect for this tenant (rule_id/failure_class + stage), carrying
        the learning-ratchet's classification, violation_count, and
        frozen (freeze-after-second-strike) state.
      * A1's `generation_ledger` frame_qa-stage rows (migration 140) —
        real QA-pass spend, grouped per video/scene. NOT joinable to a
        specific fingerprint: judge_board_sheet's own ledger writes always
        leave `fingerprint` NULL (a sheet's panels can carry different
        fingerprints in one call, so the row-level tag is left unset —
        see that function's comment).
      * D8-3b's `arbiter_findings` (migration 146) — the per-INSTANCE rows
        themselves: one row per judged frame/panel, the actual thing the
        two aggregates above summarize. Most-recent-first, capped at
        _FINDING_INSTANCES_LIMIT (an append-only log with no natural upper
        bound otherwise).

    No live per-instance rows exist on prod yet as of this chunk (D8-2's
    first live run is parked on Ryan's deploy window, and this chunk must
    land BEFORE it so that run's findings are kept) — see
    tasks/deferred-verification.md for the one-step recipe to sanity-check
    this shape once it does.
    """
    fingerprints = await fetch_all(
        """SELECT id, rule_id, stage, failure_class, fingerprint_key,
                  classification, violation_count, frozen,
                  first_seen_at, last_seen_at
           FROM arbiter_fingerprints
           WHERE tenant_id = $1
           ORDER BY last_seen_at DESC""",
        tenant_id,
    )
    finding_items = [
        {
            "id": str(f["id"]),
            "rule_id": f.get("rule_id"),
            "stage": f["stage"],
            "failure_class": f["failure_class"],
            "fingerprint_key": f["fingerprint_key"],
            "classification": f["classification"],
            "violation_count": f["violation_count"],
            "frozen": f["frozen"],
            "first_seen_at": f["first_seen_at"].isoformat() if f.get("first_seen_at") else None,
            "last_seen_at": f["last_seen_at"].isoformat() if f.get("last_seen_at") else None,
        }
        for f in fingerprints
    ]

    spend_rows = await fetch_all(
        """SELECT g.video_id, g.scene, v.video_title,
                  COUNT(*) AS qa_passes, SUM(g.actual_cost) AS total_cost,
                  MAX(g.created_at) AS last_judged_at
           FROM generation_ledger g
           JOIN videos v ON v.id = g.video_id
           WHERE g.tenant_id = $1 AND g.stage = 'frame_qa'
           GROUP BY g.video_id, g.scene, v.video_title
           ORDER BY last_judged_at DESC""",
        tenant_id,
    )
    spend_items = [
        {
            "video_id": str(s["video_id"]),
            "video_title": s.get("video_title"),
            "scene": s.get("scene"),
            "qa_passes": s["qa_passes"],
            "total_cost": float(s["total_cost"] or 0),
            "last_judged_at": s["last_judged_at"].isoformat() if s.get("last_judged_at") else None,
        }
        for s in spend_rows
    ]

    instance_rows = await fetch_all(
        """SELECT f.id, f.video_id, v.video_title, f.scene, f.station,
                  f.reference, f.label, f.image_url, f.classification,
                  f.failure_class, f.rule_id, f.fingerprint_key,
                  f.rubric_level, f.decisive_prompt_fragment, f.description,
                  f.new_vs_previous, f.cost, f.created_at
           FROM arbiter_findings f
           JOIN videos v ON v.id = f.video_id
           WHERE f.tenant_id = $1
           ORDER BY f.created_at DESC
           LIMIT $2""",
        tenant_id, _FINDING_INSTANCES_LIMIT,
    )
    instance_items = [
        {
            "id": str(r["id"]),
            "video_id": str(r["video_id"]),
            "video_title": r.get("video_title"),
            "scene": r.get("scene"),
            "station": r["station"],
            "reference": r["reference"],
            "label": r.get("label"),
            "image_url": r.get("image_url"),
            "classification": r["classification"],
            "failure_class": r.get("failure_class"),
            "rule_id": r.get("rule_id"),
            "fingerprint_key": r.get("fingerprint_key"),
            "rubric_level": r.get("rubric_level"),
            "decisive_prompt_fragment": r.get("decisive_prompt_fragment"),
            "description": r.get("description"),
            "new_vs_previous": r.get("new_vs_previous"),
            "cost": float(r["cost"]) if r.get("cost") is not None else None,
            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        }
        for r in instance_rows
    ]

    return ArbiterFindings(findings=finding_items, spend=spend_items, instances=instance_items)


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
