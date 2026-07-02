"""Agent Pipeline routes — quality-gated script generation.

Exposes the multi-agent pipeline to the frontend: trigger runs,
get paper trails, update config, view aggregate stats.
"""

import sys
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel

from auth import get_tenant_id
from database import fetch_one, fetch_all, execute
from error_utils import humanize_error

# Add pipeline root to sys.path
_pipeline_root = Path(__file__).parent.parent.parent.parent / "skills" / "video-pipeline"
if str(_pipeline_root) not in sys.path:
    sys.path.insert(0, str(_pipeline_root))

router = APIRouter(prefix="/api/agents", tags=["agents"])


# --- In-memory task tracking ---
# Keyed by (tenant_id, video_id) to prevent cross-tenant task state leaks
# (SEC-SSE-001). Previously keyed by video_id alone, so two tenants who
# happened to process videos with the same id would see each other's state.
_running_tasks: dict[tuple[str, str], dict] = {}


def _set_task(video_id: str, status: str, message: str = "", *, tenant_id: str):
    _running_tasks[(tenant_id, video_id)] = {"status": status, "message": message}


def _get_task(video_id: str, tenant_id: str) -> Optional[dict]:
    return _running_tasks.get((tenant_id, video_id))


def _clear_task(video_id: str, tenant_id: str):
    _running_tasks.pop((tenant_id, video_id), None)


# --- Request/Response Models ---

class RunAgentRequest(BaseModel):
    quality_tier: str = "standard"
    brand_voice: Optional[str] = None


class AgentVideoSummary(BaseModel):
    video_id: str
    video_title: str
    tier: Optional[str] = None
    hook_score: Optional[float] = None
    body_score: Optional[float] = None
    weapons_pass_rate: Optional[float] = None
    total_cost: Optional[float] = None
    status: str = "pending"


class AgentConfigUpdate(BaseModel):
    default_tier: Optional[str] = None
    hook_min_score: Optional[int] = None
    body_min_score: Optional[int] = None
    weapons_min_novelty: Optional[int] = None
    weapons_min_intensity: Optional[int] = None
    brand_voice: Optional[str] = None


# --- Routes ---

@router.post("/videos/{video_id}/run")
async def run_agent_pipeline(
    video_id: str,
    request: RunAgentRequest,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
):
    """Trigger the agent quality pipeline for a video."""
    # DEPRECATED (PARITY-PLAN Phase 4, 2026-07-01): a legacy door around the
    # confirm-card cost gating; no frontend caller. The copilot chat + the
    # shared action layer replaced it. Delete this raise to restore.
    raise HTTPException(
        status_code=410,
        detail="Retired endpoint. Use the co-pilot chat (POST /api/chat) or POST /api/pipeline/build.",
    )
    # Check video exists
    video = await fetch_one(
        "SELECT * FROM videos WHERE id = $1 AND tenant_id = $2",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    # Check not already running
    existing = _get_task(video_id, tenant_id)
    if existing and existing["status"] == "running":
        return {"status": "already_running", "video_id": video_id}

    _set_task(video_id, "running", "Agent pipeline starting...", tenant_id=tenant_id)

    async def _run():
        try:
            from agents.pipeline import AgentPipeline
            from agents.config import QualityTier

            pipeline = AgentPipeline(tier=request.quality_tier)

            # Load research payload from video
            research = video.get("research_payload") or {}

            output = await pipeline.run(
                research_payload=research,
                video_title=video.get("video_title", ""),
                thesis=video.get("thesis"),
                framework_angle=video.get("framework_angle"),
                brand_voice=request.brand_voice,
            )

            # Store results
            await execute(
                """UPDATE videos SET
                    agent_paper_trail = $1,
                    agent_hook_score = $2,
                    agent_body_score = $3,
                    agent_tier = $4,
                    agent_cost = $5,
                    updated_at = now()
                WHERE id = $6""",
                output.to_paper_trail(),
                output.hook.final_scores.aggregate,
                output.body.final_scores.aggregate if output.body else None,
                output.tier,
                output.total_cost,
                video_id,
            )

            # Log activity
            await execute(
                """INSERT INTO bot_activity (tenant_id, bot_name, video_id, status, message, cost)
                   VALUES ($1, $2, $3, $4, $5, $6)""",
                tenant_id, "Agent Pipeline", video_id, "completed",
                f"Tier: {output.tier}, Hook: {output.hook.final_scores.aggregate:.0f}/100, "
                f"Iterations: {output.total_iterations}",
                output.total_cost,
            )

            _set_task(video_id, "completed", f"Hook: {output.hook.final_scores.aggregate:.0f}/100", tenant_id=tenant_id)

        except Exception as e:
            friendly = humanize_error(e, context="The agent pipeline hit an error")
            _set_task(video_id, "failed", friendly, tenant_id=tenant_id)
            await execute(
                """INSERT INTO bot_activity (tenant_id, bot_name, video_id, status, message)
                   VALUES ($1, $2, $3, $4, $5)""",
                tenant_id, "Agent Pipeline", video_id, "failed", friendly,
            )

    background_tasks.add_task(_run)
    return {"status": "started", "video_id": video_id, "tier": request.quality_tier}


@router.get("/videos/{video_id}")
async def get_agent_results(
    video_id: str,
    tenant_id: str = Depends(get_tenant_id),
):
    """Get full paper trail for a video's agent pipeline run."""
    video = await fetch_one(
        """SELECT id, video_title, agent_paper_trail, agent_hook_score,
                  agent_body_score, agent_tier, agent_cost
           FROM videos WHERE id = $1 AND tenant_id = $2""",
        video_id, tenant_id,
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    return {
        "video_id": str(video["id"]),
        "video_title": video["video_title"],
        "tier": video.get("agent_tier"),
        "hook_score": video.get("agent_hook_score"),
        "body_score": video.get("agent_body_score"),
        "cost": video.get("agent_cost"),
        "paper_trail": video.get("agent_paper_trail"),
    }


@router.get("/videos/{video_id}/task")
async def get_task_status(
    video_id: str,
    tenant_id: str = Depends(get_tenant_id),
):
    """Poll background task status."""
    task = _get_task(video_id, tenant_id)
    if not task:
        return {"status": "idle"}
    return task


@router.get("/videos")
async def list_agent_videos(
    tenant_id: str = Depends(get_tenant_id),
):
    """List videos with their agent quality scores."""
    rows = await fetch_all(
        """SELECT id, video_title, agent_tier, agent_hook_score,
                  agent_body_score, agent_cost, status
           FROM videos
           WHERE tenant_id = $1 AND agent_tier IS NOT NULL
           ORDER BY created_at DESC
           LIMIT 50""",
        tenant_id,
    )

    return [
        {
            "video_id": str(r["id"]),
            "video_title": r["video_title"],
            "tier": r.get("agent_tier"),
            "hook_score": r.get("agent_hook_score"),
            "body_score": r.get("agent_body_score"),
            "cost": r.get("agent_cost"),
            "status": r.get("status"),
        }
        for r in (rows or [])
    ]


@router.get("/stats")
async def get_agent_stats(
    tenant_id: str = Depends(get_tenant_id),
):
    """Aggregate stats for agent pipeline runs."""
    row = await fetch_one(
        """SELECT
            COUNT(*) as total_scripts,
            AVG(agent_hook_score) as avg_hook_score,
            AVG(agent_body_score) as avg_body_score,
            AVG(agent_cost) as avg_cost,
            SUM(agent_cost) as total_cost
           FROM videos
           WHERE tenant_id = $1 AND agent_tier IS NOT NULL""",
        tenant_id,
    )

    return {
        "total_scripts": row["total_scripts"] if row else 0,
        "avg_hook_score": round(float(row["avg_hook_score"] or 0), 1) if row else 0,
        "avg_body_score": round(float(row["avg_body_score"] or 0), 1) if row else 0,
        "avg_cost": round(float(row["avg_cost"] or 0), 2) if row else 0,
        "total_cost": round(float(row["total_cost"] or 0), 2) if row else 0,
    }
