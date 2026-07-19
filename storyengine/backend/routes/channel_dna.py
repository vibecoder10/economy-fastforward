"""Thin HTTP door onto ``channel_dna.learn_channel`` (checklist C42 · P4.1c).

The chat front door (``routes/chat.py``'s ``_handle_learn_channel``) calls the
SAME ``learn_channel`` function this route calls — one implementation, two
doors — so C45 (onboarding hookup) and a future MCP tool can reuse this
without a second orchestration path. Learning takes 1-2 minutes (Firecrawl
scrapes + several Claude calls), so ``POST /learn`` acks immediately and runs
in the background exactly like the chat door does; ``GET /status`` polls the
digest that ``channel_dna._persist_last_run`` stashed on
``channel_profiles.channel_identity["_last_run"]``.

Not yet wired to an MCP tool this chunk — ``routes/mcp.py``'s tool calls are
synchronous request/response (see ``_call_create_video``'s BackgroundTasks
plumbing for the closest precedent), and a tool that blocks for 1-2 minutes
is a different reliability shape than the existing read-only/create-video
tools; deferred rather than rushed. Flagged in C42's SYSTEM_STATE.md entry.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel

from auth import get_tenant_id
from channel_dna import _current_identity, is_learning, learn_channel

router = APIRouter(prefix="/api/channel-dna", tags=["channel-dna"])


class LearnChannelRequest(BaseModel):
    channel_url: Optional[str] = None
    example_script_text: Optional[str] = None
    reference_video_url: Optional[str] = None


class LearnChannelResponse(BaseModel):
    started: bool
    busy: bool
    message: str


@router.post("/learn", response_model=LearnChannelResponse)
async def start_learn_channel(
    body: LearnChannelRequest,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
) -> LearnChannelResponse:
    """Ack-now, same UX the chat door uses: this only reports whether a run
    STARTED, never the outcome (poll ``GET /status`` for that). Checks
    ``is_learning`` first purely to give a friendlier immediate message than
    waiting for the background task to hit the claim and silently no-op —
    the real money-safety gate is still ``generation_claims.acquire_channel``
    inside ``learn_channel`` itself, not this pre-check."""
    tenant = str(tenant_id)
    if await is_learning(tenant):
        return LearnChannelResponse(
            started=False, busy=True,
            message="Already learning this channel's DNA — check GET /status in a moment.",
        )

    async def _job() -> None:
        await learn_channel(
            tenant,
            channel_url=body.channel_url,
            example_script_text=body.example_script_text,
            reference_video_url=body.reference_video_url,
        )

    background_tasks.add_task(_job)
    return LearnChannelResponse(
        started=True, busy=False,
        message="Learning started — roughly $0.10-0.30 of your API budget, takes a couple of minutes.",
    )


class DnaStatusResponse(BaseModel):
    learning: bool
    ok: Optional[bool] = None
    at: Optional[str] = None
    learners: dict[str, Any] = {}
    identity: dict[str, Any] = {}


@router.get("/status", response_model=DnaStatusResponse)
async def get_learn_channel_status(tenant_id: str = Depends(get_tenant_id)) -> DnaStatusResponse:
    """The last run's digest, reusing the exact ``_last_run`` envelope key
    ``channel_dna._persist_last_run`` writes — no second read path, no
    second shape to keep in sync with the chat door's card builder."""
    tenant = str(tenant_id)
    learning = await is_learning(tenant)
    identity = await _current_identity(tenant)
    run = identity.get("_last_run") if isinstance(identity.get("_last_run"), dict) else {}
    return DnaStatusResponse(
        learning=learning,
        ok=run.get("ok"),
        at=run.get("at"),
        learners=run.get("learners") or {},
        identity=identity,
    )
