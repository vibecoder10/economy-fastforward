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
    visual_style: str = "cinematic_illustration"
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
        visual_style=row.get("visual_style") or "cinematic_illustration",
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
