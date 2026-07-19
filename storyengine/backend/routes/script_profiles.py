"""GET /api/script-profiles — catalog of the editorial-voice engines in
shared.profiles.script (checklist §2.3, chunk C24 — "script-voice profiles
not user-selectable today").

Source of truth is the Python registry itself, read server-side — same
"never hand-copy a registry into the frontend" posture as GET /api/models
(routes/model_registry.py), GET /api/camera-presets, and GET
/api/style-presets. No new DB table (unlike style_presets, migration 096):
shared.profiles.script/*.py is a small, durable, code-reviewed registry (3
profiles today), not tenant-editable data — same "no new DB table"
rationale camera_presets.py's own docstring gives for camera_moves.py.

Writing a pick is POST /api/videos (create_video's script_profile field) or
PATCH /api/videos/{id} (the generic update path, routes/videos.py's
_resolve_script_profile validates both the same way) — this route is
read-only.
"""
import sys
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth import get_tenant_id

# shared.profiles.script lives in the pipeline package, not the SaaS backend
# (same sys.path pattern as routes/camera_presets.py / routes/model_registry.py).
_PIPELINE_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "skills" / "video-pipeline"
if str(_PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_ROOT))

from shared.profiles.script import list_profiles, load_script_profile  # noqa: E402

router = APIRouter(prefix="/api/script-profiles", tags=["script-profiles"])


class ScriptProfileResponse(BaseModel):
    id: str
    display_name: str
    description: str
    best_for: list[str]
    is_default: bool


class ScriptProfilesResponse(BaseModel):
    profiles: list[ScriptProfileResponse]


@router.get("", response_model=ScriptProfilesResponse)
async def list_script_profiles(tenant_id=Depends(get_tenant_id)):
    """The editorial-voice catalog for the New Video "Advanced" select and
    the Script tab's voice picker. Global catalog data, not tenant-scoped —
    auth is required anyway (every route in this app does), same posture as
    GET /api/camera-presets. Copy is pulled verbatim from each profile's own
    template_metadata (display_name/description/best_for) — nothing
    invented here."""
    from shared.profiles.script import DEFAULT_PROFILE_ID

    profiles = []
    for profile_id in list_profiles():
        profile = load_script_profile(profile_id)
        if not profile:
            continue  # a registered id failed to load — skip, don't 500
        meta = profile.template_metadata
        profiles.append(ScriptProfileResponse(
            id=profile.profile_id,
            display_name=(meta.display_name if meta and meta.display_name else profile.profile_name),
            description=(meta.description if meta and meta.description else profile.description),
            best_for=list(meta.best_for) if meta else [],
            is_default=(profile.profile_id == DEFAULT_PROFILE_ID),
        ))
    # Default first (neutral_v1), then registration order for the rest.
    profiles.sort(key=lambda p: not p.is_default)
    return ScriptProfilesResponse(profiles=profiles)
