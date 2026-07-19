"""GET /api/style-descriptions — the six-entry style-DESCRIPTION vocabulary
(channel_format.STYLE_DESCRIPTIONS: pixar_3d/flat_2d/realistic/anime/
watercolor/comic), the ONE source shared by:
  - routes/chat.py's reference-video vision classifier
    (_detect_reference_style_preset / _annotate_style_recommendation) —
    classifies a modeled reference video's ANIMATION MEDIUM;
  - the chat producer's "style" LOOK card options;
  - the New Video "Style description" grid (frontend/src/app/pipeline/page.tsx).

This is a DIFFERENT axis from GET /api/style-presets (routes/style_presets.py
— the 5-row structural "Look Engine" catalog backed by a real DB table). This
data is a static Python dict, not a DB table (nothing to seed/migrate) — same
thin-read-only-view posture as GET /api/models (routes/model_registry.py)
over shared.channel_profile.MODEL_REGISTRY.

Checklist §C21b: replaces the two hardcoded copies of this vocabulary that
used to drift independently — producer_prompt.VISUAL_PRESETS (backend) and
frontend/src/lib/visual-presets.ts (frontend) — both deleted.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth import get_tenant_id
from channel_format import STYLE_DESCRIPTIONS

router = APIRouter(prefix="/api/style-descriptions", tags=["style-descriptions"])


class StyleDescriptionResponse(BaseModel):
    id: str
    label: str
    look: str


class StyleDescriptionsResponse(BaseModel):
    descriptions: list[StyleDescriptionResponse]


@router.get("", response_model=StyleDescriptionsResponse)
async def list_style_descriptions(tenant_id: str = Depends(get_tenant_id)):
    """The six style-description ids, in STYLE_DESCRIPTIONS's fixed literal
    order (pixar_3d/flat_2d/realistic/anime/watercolor/comic) — matches the
    frontend grids' expected layout, same as before this endpoint existed."""
    return StyleDescriptionsResponse(descriptions=[
        StyleDescriptionResponse(id=pid, label=v["label"], look=v["look"])
        for pid, v in STYLE_DESCRIPTIONS.items()
    ])
