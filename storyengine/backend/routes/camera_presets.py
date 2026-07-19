"""GET /api/camera-presets — a curated, clickable subset of the 40+-move
camera catalog (skills/video-pipeline/image_prompts/engine/camera_moves.py),
for the Scenes tab's per-shot "camera move" chip + preset sheet (checklist
§2.2, C23; UX map §4).

Source of truth is the Python catalog itself, read server-side — same
"never hand-copy a registry into the frontend" posture as GET /api/models
(routes/model_registry.py) and GET /api/style-presets. No new DB table:
camera_moves.py is a durable, code-reviewed vocabulary (its own docstring
calls it that), not tenant-editable data, so a table would only add a sync
problem a style_presets-style table exists to solve for genuinely dynamic
data. Auth posture mirrors GET /api/models — any authenticated tenant reads
the same global list, no per-tenant filter.

The curated subset is deliberately small (~12 of the 46-seed/24-pruned
catalog): the ones a creator can recognize by name and reason about without
reading the whole cinematography glossary, spanning every purpose (Reveal /
Scale / Establish / Isolation / Payoff) and pace so the sheet reads as a
real choice, not a wall. `static_locked` is included on purpose — it's the
"force no movement" pick, distinct from clearing the override back to Auto
(NULL == let camera_selector.py's earn-the-move decide).

Writing a pick is PATCH /api/assets/{asset_id}/camera-preset
(routes/assets.py) — this route is read-only.
"""
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth import get_tenant_id

import sys
from pathlib import Path

# shared.channel_profile / image_prompts.engine live in the pipeline package,
# not the SaaS backend (same sys.path pattern as routes/model_registry.py).
_PIPELINE_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "skills" / "video-pipeline"
if str(_PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_ROOT))

from image_prompts.engine.camera_moves import get_move  # noqa: E402

router = APIRouter(prefix="/api/camera-presets", tags=["camera-presets"])

# The curated subset — ids into CAMERA_MOVES. Order is deliberate: reveals/
# pushes first (most common), specials/static last. Chosen for a diverse
# spread across camera_moves.py's own categories and `best_for` purposes so
# the preset sheet (grouped by purpose per the UX map) has something in
# every group. Keep in sync BY HAND if the catalog's ids ever change — this
# is the one place that decides "curated" vs "full catalog", by design.
CURATED_PRESET_IDS: list[str] = [
    "dolly_in",          # ISOLATION, PAYOFF — classic push-in
    "dolly_out",         # SCALE, REVEAL — pull back and widen
    "crash_zoom_in",     # ISOLATION, PAYOFF — punchline/shock
    "slow_zoom_in",      # ISOLATION — subtle tightening
    "pan_right",         # REVEAL — find something new
    "tilt_up_reveal",    # SCALE, REVEAL — what rises above
    "crane_up_reveal",   # SCALE, REVEAL, PAYOFF — rising establishing shot
    "drone_orbit",       # SCALE, ESTABLISH — wide aerial circle
    "orbit_right",       # ISOLATION, PAYOFF — arc around the subject
    "whip_pan",          # REVEAL, PAYOFF — fast cut to a second subject
    "handheld_follow",   # REVEAL — urgency, tracking a subject
    "static_locked",     # force NO movement (distinct from clearing to Auto)
]


class CameraPresetResponse(BaseModel):
    id: str
    name: str
    motion_prompt: str
    best_for: list[str]
    category: str
    # No image previews exist for camera moves (unlike style_presets, which
    # has preview_url) — `preview` is the catalog's own `image_setup` text,
    # the closest honest thing to a preview: what the still image needs to
    # look like for this move to land. Empty for static_locked (no
    # composition contract — see camera_moves.py's own comment on that row).
    preview: Optional[str] = None


class CameraPresetsResponse(BaseModel):
    presets: list[CameraPresetResponse]


@router.get("", response_model=CameraPresetsResponse)
async def list_camera_presets(tenant_id=Depends(get_tenant_id)):
    """The curated camera-move subset for the Scenes tab's chip/sheet.
    Global catalog data, not tenant-scoped — auth is required anyway (every
    route in this app does), same posture as GET /api/models."""
    presets = []
    for move_id in CURATED_PRESET_IDS:
        move = get_move(move_id)
        if not move:
            continue  # a curated id drifted from the catalog — skip, don't 500
        presets.append(CameraPresetResponse(
            id=move.id,
            name=move.name,
            motion_prompt=move.motion_prompt,
            best_for=list(move.best_for),
            category=move.category,
            preview=move.image_setup or None,
        ))
    return CameraPresetsResponse(presets=presets)
