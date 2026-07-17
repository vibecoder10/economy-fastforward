"""GET /api/models — single source of truth for which video-generation models
are actually selectable, read straight off shared.channel_profile.MODEL_REGISTRY
(skills/video-pipeline).

Before this route existed, the Scenes clip-model dropdown hand-copied a
WIRED_MODELS constant on the frontend (frontend/src/components/production/
ScenesWorkspaceTab.tsx) that had to be kept in sync by hand with a SEPARATE
hardcoded `wired` set inside pipeline_executor.run_clip_generation's gate.
They drifted: the dropdown offered Kling 3.0 Pro / Runway Gen-4 Turbo /
Hailuo 2.3, all of which the gate rejected with "isn't available yet".

Both now read `ModelProfile.wired` off the SAME registry entry — this route
is a thin, read-only view of it, nothing more. See
tasks/storyengine-wiring-fix-checklist.md §0.2.

Keep this endpoint's shape stable-but-extensible: a later chunk (C11/P1.1)
adds best_for/tier/cost_per_clip fields, read straight off the same
registry entries. Don't build that out here.
"""
import sys
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth import get_tenant_id

# Same sys.path pattern as routes/skills.py — the video-model registry lives
# in the shared pipeline package, not duplicated into the SaaS backend.
_pipeline_root = Path(__file__).parent.parent.parent.parent / "skills" / "video-pipeline"
if str(_pipeline_root) not in sys.path:
    sys.path.insert(0, str(_pipeline_root))

from shared.channel_profile import MODEL_REGISTRY, DEFAULT_VIDEO_MODEL  # noqa: E402

router = APIRouter(prefix="/api/models", tags=["models"])


class VideoModelResponse(BaseModel):
    id: str
    name: str
    kind: str = "video"  # only video models exist in MODEL_REGISTRY today
    wired: bool


class ModelsResponse(BaseModel):
    models: list[VideoModelResponse]
    default_video_model: str


@router.get("", response_model=ModelsResponse)
async def list_models(tenant_id=Depends(get_tenant_id)):
    """All video-generation models the registry knows about. `wired` is true
    only for models with a live generation path — exactly the same flag
    pipeline_executor's gate checks, read from the same registry entry."""
    models = [
        VideoModelResponse(
            id=profile.model_id,
            name=profile.display_name,
            kind="video",
            wired=profile.wired,
        )
        for profile in MODEL_REGISTRY.values()
    ]
    return ModelsResponse(models=models, default_video_model=DEFAULT_VIDEO_MODEL)
