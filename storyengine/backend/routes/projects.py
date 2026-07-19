"""Project routes — CRUD for project settings (replaces channel_profile).

A project represents a channel (e.g., "Power Doctrine"). Each account
can have multiple projects. The UI currently shows only the first project.
"""

import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_tenant_id
from database import fetch_one, fetch_all, execute, safe_column

router = APIRouter(prefix="/api/projects", tags=["projects"])

DEV_ACCOUNT_ID = "00000000-0000-0000-0000-000000000001"


# --- Models ---

class ProjectRead(BaseModel):
    """Full project data returned to frontend."""
    id: str
    name: str = ""
    niche: str = ""
    target_audience: str = ""
    visual_style: str = "neutral_v1"
    visual_profile_json: Optional[dict] = None
    accent_color: str = "#00D4AA"
    custom_accent_color: Optional[str] = None
    frameworks: list[str] = []
    character_references: list[dict] = []


class ProjectUpdate(BaseModel):
    """Partial update for project settings."""
    name: Optional[str] = None
    niche: Optional[str] = None
    target_audience: Optional[str] = None
    visual_style: Optional[str] = None
    visual_profile_json: Optional[dict] = None
    accent_color: Optional[str] = None
    custom_accent_color: Optional[str] = None
    frameworks: Optional[list[str]] = None
    character_references: Optional[list[dict]] = None


# --- Helpers ---

def _parse_jsonb(value, default=None):
    """Parse a JSONB value that might be a string or already parsed."""
    if value is None:
        return default if default is not None else None
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return default if default is not None else None
    return default if default is not None else None


def _row_to_project(row: dict) -> ProjectRead:
    """Convert a database row to a ProjectRead model."""
    return ProjectRead(
        id=str(row["id"]),
        name=row.get("name") or "",
        niche=row.get("niche") or "",
        target_audience=row.get("target_audience") or "",
        visual_style=row.get("visual_style") or "neutral_v1",
        visual_profile_json=_parse_jsonb(row.get("visual_profile_json")),
        accent_color=row.get("accent_color") or "#00D4AA",
        custom_accent_color=row.get("custom_accent_color"),
        frameworks=_parse_jsonb(row.get("frameworks"), []),
        character_references=_parse_jsonb(row.get("character_references"), []),
    )


async def _get_or_create_project(tenant_id: str) -> dict:
    """Get the current project for a tenant, or create one.

    This is the getCurrentProject() helper from the spec.
    Returns the first project linked to this tenant.
    """
    row = await fetch_one(
        """SELECT id, name, niche, target_audience, visual_style,
                  visual_profile_json, accent_color, custom_accent_color,
                  frameworks, character_references
           FROM projects WHERE tenant_id = $1 LIMIT 1""",
        tenant_id,
    )

    if row:
        return row

    # Auto-create a default project for this tenant
    await execute(
        """INSERT INTO projects (account_id, tenant_id, name)
           VALUES ($1, $2, 'My Channel')""",
        DEV_ACCOUNT_ID,
        tenant_id,
    )

    row = await fetch_one(
        """SELECT id, name, niche, target_audience, visual_style,
                  visual_profile_json, accent_color, custom_accent_color,
                  frameworks, character_references
           FROM projects WHERE tenant_id = $1 LIMIT 1""",
        tenant_id,
    )
    return row


# --- Endpoints ---

@router.get("/current", response_model=ProjectRead)
async def get_current_project(tenant_id: str = Depends(get_tenant_id)):
    """Get the current project for this user.

    Returns the first project linked to the user's tenant.
    Auto-creates a default project if none exists.
    """
    row = await _get_or_create_project(tenant_id)
    return _row_to_project(row)


@router.put("/current", response_model=ProjectRead)
async def update_current_project(
    update: ProjectUpdate,
    tenant_id: str = Depends(get_tenant_id),
):
    """Update the current project (partial update).

    Only updates fields that are provided (non-None).
    """
    row = await _get_or_create_project(tenant_id)
    project_id = str(row["id"])

    # Build dynamic SET clause
    sets = []
    params = []
    param_idx = 1  # $1 is project_id

    field_map = {
        "name": update.name,
        "niche": update.niche,
        "target_audience": update.target_audience,
        "visual_style": update.visual_style,
        "accent_color": update.accent_color,
        "custom_accent_color": update.custom_accent_color,
    }

    for col, val in field_map.items():
        if val is not None:
            param_idx += 1
            sets.append(f"{safe_column(col)} = ${param_idx}")
            params.append(val)

    # JSONB fields need explicit cast
    jsonb_fields = {
        "visual_profile_json": update.visual_profile_json,
        "frameworks": update.frameworks,
        "character_references": update.character_references,
    }

    for col, val in jsonb_fields.items():
        if val is not None:
            param_idx += 1
            sets.append(f"{safe_column(col)} = ${param_idx}::jsonb")
            params.append(json.dumps(val))

    if sets:
        sets.append("updated_at = now()")
        # SECURITY: column names from hardcoded dict keys + safe_column(), values use $N params
        query = f"UPDATE projects SET {', '.join(sets)} WHERE id = $1 AND tenant_id = ${param_idx + 1}"
        await execute(query, project_id, *params, tenant_id)

    # Return updated project
    updated = await fetch_one(
        """SELECT id, name, niche, target_audience, visual_style,
                  visual_profile_json, accent_color, custom_accent_color,
                  frameworks, character_references
           FROM projects WHERE id = $1""",
        project_id,
    )
    return _row_to_project(updated)


# --- Backward compat: channel-profile endpoints redirect to projects ---

@router.get("/channel-profile", response_model=ProjectRead)
async def get_channel_profile_compat(tenant_id: str = Depends(get_tenant_id)):
    """Backward-compatible endpoint for channel profile reads."""
    return await get_current_project(tenant_id)


# --- Channel cast (locked brand identity) -------------------------------------

def _cast_refs(row) -> list:
    val = (row or {}).get("character_references")
    if isinstance(val, str):
        try:
            val = json.loads(val)
        except (json.JSONDecodeError, ValueError):
            val = []
    return [c for c in (val or []) if isinstance(c, dict) and c.get("reference_url")]


@router.get("/current/cast")
async def get_channel_cast(tenant_id: str = Depends(get_tenant_id)):
    """The project's saved cast + whether it's locked as the channel identity."""
    row = await _get_or_create_project(tenant_id)
    full = await fetch_one(
        "SELECT character_references, cast_locked FROM projects WHERE id = $1 AND tenant_id = $2",
        str(row["id"]), tenant_id,
    )
    return {
        "characters": _cast_refs(full),
        "cast_locked": bool((full or {}).get("cast_locked")),
    }


class CastLockRequest(BaseModel):
    # Optional new images to add before locking: [{"url": ..., "name": optional}]
    images: Optional[list[dict]] = None


@router.post("/current/cast/lock")
async def lock_channel_cast(
    body: Optional[CastLockRequest] = None,
    tenant_id: str = Depends(get_tenant_id),
):
    """Lock the saved cast as the channel's identity: every new video
    auto-uses these characters and skips generation. With `images`, they're
    vision-described and merged into the saved cast first."""
    if body and body.images:
        from routes.characters import lock_project_cast
        try:
            merged = await lock_project_cast(tenant_id, body.images)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"status": "locked", "characters": merged}
    row = await _get_or_create_project(tenant_id)
    full = await fetch_one(
        "SELECT character_references FROM projects WHERE id = $1 AND tenant_id = $2",
        str(row["id"]), tenant_id,
    )
    if not _cast_refs(full):
        raise HTTPException(status_code=400, detail="No saved characters to lock — add character sheets first.")
    await execute(
        "UPDATE projects SET cast_locked = true, updated_at = now() WHERE id = $1 AND tenant_id = $2",
        str(row["id"]), tenant_id,
    )
    return {"status": "locked", "characters": _cast_refs(full)}


@router.delete("/current/cast/lock")
async def unlock_channel_cast(tenant_id: str = Depends(get_tenant_id)):
    row = await _get_or_create_project(tenant_id)
    await execute(
        "UPDATE projects SET cast_locked = false, updated_at = now() WHERE id = $1 AND tenant_id = $2",
        str(row["id"]), tenant_id,
    )
    return {"status": "unlocked"}


async def _save_cast_refs(tenant_id, project_id: str, refs: list) -> None:
    await execute(
        "UPDATE projects SET character_references = $1, updated_at = now() "
        "WHERE id = $2 AND tenant_id = $3",
        json.dumps(refs), project_id, tenant_id,
    )


async def _channel_style_dna(tenant_id) -> str:
    """The channel's current look sentence for new cast members: locked
    channel format first, else the most recent video's style, mapped onto the
    canonical preset looks. Empty string when there's no signal."""
    preset = None
    try:
        from channel_format import get_channel_format, style_preset_for_format
        fmt, locked = await get_channel_format(tenant_id)
        if locked:
            preset = style_preset_for_format(fmt)
    except Exception:  # noqa: BLE001
        preset = None
    if not preset:
        row = await fetch_one(
            """SELECT visual_style FROM videos
               WHERE tenant_id = $1 AND deleted_at IS NULL
                 AND visual_style IS NOT NULL AND btrim(visual_style) <> ''
               ORDER BY created_at DESC LIMIT 1""",
            tenant_id,
        )
        if row and row.get("visual_style"):
            from routes.videos import _normalize_style_preset
            preset = _normalize_style_preset(row["visual_style"])
    if not preset:
        return ""
    from channel_format import STYLE_DESCRIPTIONS
    return (STYLE_DESCRIPTIONS.get(preset) or {}).get("look", "")


class CastGenerateRequest(BaseModel):
    name: str
    description: str
    always: bool = True


@router.post("/current/cast/generate")
async def generate_channel_cast_member(
    body: CastGenerateRequest,
    tenant_id: str = Depends(get_tenant_id),
):
    """Generate a character model sheet in the channel's style and add it to
    the saved cast (~$0.05). The cast lock state is left as-is, so a locked
    cast stays locked and the new member rides every future video (or only
    the picker when always=false)."""
    name = (body.name or "").strip()[:120]
    desc = (body.description or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Give the character a name.")
    if not desc:
        raise HTTPException(status_code=400, detail="Describe how the character looks.")

    from vault import get_secret
    api_key = await get_secret("kie_ai_api_key", str(tenant_id))
    if not api_key:
        raise HTTPException(status_code=400, detail="Add your Kie.ai API key in Settings → Keys first.")

    project = await _get_or_create_project(tenant_id)
    project_id = str(project["id"])
    style_dna = await _channel_style_dna(tenant_id)

    from routes.characters import _generate_portrait
    try:
        temp_url = await _generate_portrait(api_key, desc, style_dna, name=name)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Character generation failed: {str(e)[:200]}")

    url = temp_url
    try:
        import uuid as _uuid
        from storage import upload_from_url
        url = await upload_from_url(
            temp_url, f"{project_id}/cast/{_uuid.uuid4().hex}.png", "image/png", str(tenant_id)
        )
    except Exception:  # noqa: BLE001 - keep the temp URL rather than fail
        pass

    full = await fetch_one(
        "SELECT character_references FROM projects WHERE id = $1 AND tenant_id = $2",
        project_id, tenant_id,
    )
    refs = _cast_refs(full)
    refs = [c for c in refs if c.get("name") != name]
    refs.append({
        "name": name,
        "description": desc[:1000],
        "reference_url": url,
        "always": bool(body.always),
    })
    await _save_cast_refs(tenant_id, project_id, refs)
    return {"status": "added", "characters": refs}


class CastMemberUpdate(BaseModel):
    always: Optional[bool] = None
    new_name: Optional[str] = None


@router.patch("/current/cast/{name}")
async def update_channel_cast_member(
    name: str,
    body: CastMemberUpdate,
    tenant_id: str = Depends(get_tenant_id),
):
    """Update a saved cast member: rename, or flip `always` (auto-attach to
    every new video vs optional via the Use Saved Cast picker)."""
    project = await _get_or_create_project(tenant_id)
    project_id = str(project["id"])
    full = await fetch_one(
        "SELECT character_references FROM projects WHERE id = $1 AND tenant_id = $2",
        project_id, tenant_id,
    )
    refs = _cast_refs(full)
    target = next((c for c in refs if c.get("name") == name), None)
    if not target:
        raise HTTPException(status_code=404, detail=f"No saved character named '{name}'.")
    if body.always is not None:
        target["always"] = bool(body.always)
    if body.new_name and body.new_name.strip():
        target["name"] = body.new_name.strip()[:120]
    await _save_cast_refs(tenant_id, project_id, refs)
    return {"status": "updated", "characters": refs}


@router.delete("/current/cast/{name}")
async def delete_channel_cast_member(name: str, tenant_id: str = Depends(get_tenant_id)):
    """Remove a character from the saved cast (existing videos keep theirs)."""
    project = await _get_or_create_project(tenant_id)
    project_id = str(project["id"])
    full = await fetch_one(
        "SELECT character_references FROM projects WHERE id = $1 AND tenant_id = $2",
        project_id, tenant_id,
    )
    refs = _cast_refs(full)
    kept = [c for c in refs if c.get("name") != name]
    if len(kept) == len(refs):
        raise HTTPException(status_code=404, detail=f"No saved character named '{name}'.")
    await _save_cast_refs(tenant_id, project_id, kept)
    return {"status": "deleted", "characters": kept}
