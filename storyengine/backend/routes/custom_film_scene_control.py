"""Authenticated HTTP surface for deterministic Custom Film Scene Control."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from auth import get_tenant_id
import custom_film_scene_control as control
from database import get_pool


router = APIRouter(
    prefix="/api/custom-film/{video_id}/scene-control",
    tags=["custom-film-scene-control"],
)


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FilmLockRequest(_StrictRequest):
    payload: Any


class CreateSceneRequest(_StrictRequest):
    scene_contract: dict[str, Any]


class ReviseSceneRequest(_StrictRequest):
    expected_revision_hash: str
    changed_gate: Literal[
        "plan", "storyboard", "imagery", "animation", "audio", "assembly"
    ]
    scene_contract: dict[str, Any] | None = None
    artifact_hash: str | None = None


class TransitionSceneRequest(_StrictRequest):
    expected_revision_hash: str
    target_state: Literal[
        "plan_approved",
        "storyboard_approved",
        "imagery_approved",
        "animation_approved",
        "audio_approved",
        "assembled",
        "accepted",
    ]
    evidence_hash: str


class QuoteOperationRequest(_StrictRequest):
    expected_revision_hash: str
    operation_type: Literal[
        "storyboard_images",
        "final_imagery",
        "animate_shot",
        "dialogue_audio",
        "assemble_scene",
    ]
    shot_id: UUID | None = None


class ApproveStoryboardRequest(_StrictRequest):
    expected_revision_hash: str
    approval_card_hash: str
    exact_cumulative_amount_cents: int


def _http_error(exc: control.SceneControlError) -> HTTPException:
    status = 404 if isinstance(exc, control.SceneControlNotFound) else 409
    return HTTPException(status_code=status, detail=str(exc))


@router.get("")
async def get_scene_control(
    video_id: UUID,
    tenant_id: str = Depends(get_tenant_id),
):
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            return await control.read_scene_control(
                conn,
                tenant_id=str(tenant_id),
                video_id=str(video_id),
            )
    except control.SceneControlError as exc:
        raise _http_error(exc) from exc


@router.put("/film-locks/{lock_kind}")
async def put_film_lock(
    video_id: UUID,
    lock_kind: str,
    body: FilmLockRequest,
    tenant_id: str = Depends(get_tenant_id),
):
    try:
        pool = await get_pool()
        async with pool.acquire() as conn, conn.transaction():
            return await control.approve_film_lock(
                conn,
                tenant_id=str(tenant_id),
                video_id=str(video_id),
                lock_kind=lock_kind,
                payload=body.payload,
            )
    except control.SceneControlError as exc:
        raise _http_error(exc) from exc


@router.post("/scenes")
async def post_scene(
    video_id: UUID,
    body: CreateSceneRequest,
    tenant_id: str = Depends(get_tenant_id),
):
    try:
        pool = await get_pool()
        async with pool.acquire() as conn, conn.transaction():
            return await control.create_scene(
                conn,
                tenant_id=str(tenant_id),
                video_id=str(video_id),
                raw_scene_contract=body.scene_contract,
            )
    except control.SceneControlError as exc:
        raise _http_error(exc) from exc


@router.put("/scenes/{scene_id}/revision")
async def put_scene_revision(
    video_id: UUID,
    scene_id: UUID,
    body: ReviseSceneRequest,
    tenant_id: str = Depends(get_tenant_id),
):
    try:
        pool = await get_pool()
        async with pool.acquire() as conn, conn.transaction():
            return await control.revise_scene(
                conn,
                tenant_id=str(tenant_id),
                video_id=str(video_id),
                scene_id=str(scene_id),
                expected_revision_hash=body.expected_revision_hash,
                changed_gate=body.changed_gate,
                raw_scene_contract=body.scene_contract,
                artifact_hash=body.artifact_hash,
            )
    except control.SceneControlError as exc:
        raise _http_error(exc) from exc


@router.post("/scenes/{scene_id}/transition")
async def post_scene_transition(
    video_id: UUID,
    scene_id: UUID,
    body: TransitionSceneRequest,
    tenant_id: str = Depends(get_tenant_id),
):
    try:
        pool = await get_pool()
        async with pool.acquire() as conn, conn.transaction():
            return await control.transition_scene(
                conn,
                tenant_id=str(tenant_id),
                video_id=str(video_id),
                scene_id=str(scene_id),
                expected_revision_hash=body.expected_revision_hash,
                target_state=body.target_state,
                evidence_hash=body.evidence_hash,
            )
    except control.SceneControlError as exc:
        raise _http_error(exc) from exc


@router.post("/scenes/{scene_id}/operations/quote")
async def post_operation_quote(
    video_id: UUID,
    scene_id: UUID,
    body: QuoteOperationRequest,
    tenant_id: str = Depends(get_tenant_id),
):
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            return await control.quote_scene_operation(
                conn,
                tenant_id=str(tenant_id),
                video_id=str(video_id),
                scene_id=str(scene_id),
                expected_revision_hash=body.expected_revision_hash,
                operation_type=body.operation_type,
                shot_id=str(body.shot_id) if body.shot_id else None,
            )
    except control.SceneControlError as exc:
        raise _http_error(exc) from exc


@router.post("/scenes/{scene_id}/storyboards/approve")
async def post_storyboard_approval(
    video_id: UUID,
    scene_id: UUID,
    body: ApproveStoryboardRequest,
    request: Request,
    tenant_id: str = Depends(get_tenant_id),
):
    import custom_film_scene_storyboards as storyboards
    try:
        pool = await get_pool()
        async with pool.acquire() as conn, conn.transaction():
            reserved = await storyboards.approve_storyboards(
                conn,
                tenant_id=str(tenant_id),
                video_id=str(video_id),
                scene_id=str(scene_id),
                expected_revision_hash=body.expected_revision_hash,
                approval_card_hash=body.approval_card_hash,
                exact_cumulative_amount_cents=body.exact_cumulative_amount_cents,
            )
        # Queue only after the approval transaction commits.
        arq_pool = getattr(request.app.state, "arq", None)
        if arq_pool is None:
            raise storyboards.StoryboardExecutionError(
                "The exact approval is saved, but the worker queue is unavailable"
            )
        from job_queue import enqueue_stage
        queued = await enqueue_stage(
            arq_pool, "scene_storyboards", str(video_id), str(tenant_id), 1,
            schedule_id=reserved["schedule_id"],
        )
        return {**reserved, "queue_enqueued": queued is not None}
    except control.SceneControlError as exc:
        raise _http_error(exc) from exc
