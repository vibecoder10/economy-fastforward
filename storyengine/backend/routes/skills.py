"""Skills routes — exposes the pipeline skill registry to the frontend.

Lists available skills, their metadata, costs, and configuration options.
Filters by tenant's configured API keys to show only runnable skills.
"""

import sys
import os
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth import get_tenant_id
from vault import list_secrets

# Add pipeline root to sys.path so we can import skill_registry
_pipeline_root = Path(__file__).parent.parent.parent.parent / "skills" / "video-pipeline"
if str(_pipeline_root) not in sys.path:
    sys.path.insert(0, str(_pipeline_root))

from shared.skill_registry import get_registry, SkillManifest

router = APIRouter(prefix="/api/skills", tags=["skills"])


# --- Response Models ---

class SkillCost(BaseModel):
    per_run: float = 0.0
    per_video: float = 0.0
    unit: str = "USD"


class SkillParam(BaseModel):
    name: str
    type: str = "string"
    default: Optional[str] = None
    description: str = ""


class SkillResponse(BaseModel):
    skill_id: str
    name: str
    type: str
    description: str
    pipeline_stage: bool
    required_status: Optional[str]
    output_status: Optional[str]
    cost_estimate: SkillCost
    dependencies: List[str]
    configurable_params: List[SkillParam]
    available: bool = True  # False if tenant lacks required API keys


class SkillsSummary(BaseModel):
    total_skills: int
    available_skills: int
    pipeline_skills: int
    estimated_pipeline_cost: float
    skills: List[SkillResponse]


def _manifest_to_response(m: SkillManifest, available: bool = True) -> SkillResponse:
    """Convert a SkillManifest to an API response."""
    params = []
    for name, config in m.configurable_params.items():
        if isinstance(config, dict):
            params.append(SkillParam(
                name=name,
                type=config.get("type", "string"),
                default=str(config.get("default", "")) if config.get("default") is not None else None,
                description=config.get("description", ""),
            ))

    return SkillResponse(
        skill_id=m.skill_id,
        name=m.name,
        type=m.type,
        description=m.description,
        pipeline_stage=m.pipeline_stage,
        required_status=m.required_status,
        output_status=m.output_status,
        cost_estimate=SkillCost(
            per_run=m.cost_estimate.per_run,
            per_video=m.cost_estimate.per_video,
            unit=m.cost_estimate.unit,
        ),
        dependencies=m.dependencies,
        configurable_params=params,
        available=available,
    )


@router.get("", response_model=SkillsSummary)
async def list_skills(tenant_id: str = Depends(get_tenant_id)):
    """List all skills with availability based on tenant's configured API keys."""
    registry = get_registry(_pipeline_root)

    # Get tenant's configured API keys
    try:
        tenant_secrets = await list_secrets(tenant_id)
        configured_keys = [s["name"] for s in tenant_secrets if s.get("configured")]
    except Exception:
        configured_keys = []

    skills = []
    available_count = 0

    for manifest in registry.get_pipeline_order():
        # Check if tenant has all required keys
        available = all(k in configured_keys for k in manifest.required_keys)
        if available:
            available_count += 1
        skills.append(_manifest_to_response(manifest, available))

    # Add non-pipeline skills (data gathering, etc.)
    for manifest in registry.list_skills():
        if not manifest.pipeline_stage:
            available = all(k in configured_keys for k in manifest.required_keys)
            if available:
                available_count += 1
            skills.append(_manifest_to_response(manifest, available))

    return SkillsSummary(
        total_skills=registry.skill_count,
        available_skills=available_count,
        pipeline_skills=len(registry.get_pipeline_skills()),
        estimated_pipeline_cost=registry.get_total_pipeline_cost(),
        skills=skills,
    )


@router.get("/{skill_id}", response_model=SkillResponse)
async def get_skill(skill_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Get details for a specific skill."""
    registry = get_registry(_pipeline_root)
    manifest = registry.get_skill(skill_id)

    if not manifest:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")

    # Check availability
    try:
        tenant_secrets = await list_secrets(tenant_id)
        configured_keys = [s["name"] for s in tenant_secrets if s.get("configured")]
    except Exception:
        configured_keys = []

    available = all(k in configured_keys for k in manifest.required_keys)
    return _manifest_to_response(manifest, available)


@router.get("/pipeline/order", response_model=List[SkillResponse])
async def get_pipeline_order(tenant_id: str = Depends(get_tenant_id)):
    """Get pipeline skills in execution order."""
    registry = get_registry(_pipeline_root)
    return [_manifest_to_response(m) for m in registry.get_pipeline_order()]


@router.get("/pipeline/cost")
async def get_pipeline_cost(tenant_id: str = Depends(get_tenant_id)):
    """Get estimated cost breakdown for a full pipeline run."""
    registry = get_registry(_pipeline_root)

    breakdown = []
    total = 0.0
    for m in registry.get_pipeline_order():
        cost = m.estimated_cost
        total += cost
        breakdown.append({
            "skill_id": m.skill_id,
            "name": m.name,
            "cost": cost,
        })

    return {
        "total_estimated_cost": total,
        "currency": "USD",
        "breakdown": breakdown,
    }
