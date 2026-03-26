"""Visual styles routes — CRUD for visual styles and their characters.

Each project has multiple visual styles (4 defaults + user-created).
Only one style per project can be active at a time.
Characters belong to a specific style and cascade-delete with it.
"""

import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_tenant_id
from database import fetch_one, fetch_all, execute
from routes.projects import _get_or_create_project

router = APIRouter(prefix="/api/visual-styles", tags=["visual-styles"])


# --- Models ---

class StyleCharacterRead(BaseModel):
    id: str
    name: str
    image_url: str
    sort_order: int = 0

class VisualStyleRead(BaseModel):
    id: str
    name: str
    style_profile: dict
    reference_image_url: Optional[str] = None
    is_active: bool = False
    is_default: bool = False
    characters: list[StyleCharacterRead] = []

class CreateStyleRequest(BaseModel):
    name: str
    style_profile: dict
    reference_image_url: Optional[str] = None

class CreateCharacterRequest(BaseModel):
    name: str
    image_url: str

class GenerateCharacterRequest(BaseModel):
    prompt: str
    style_id: str


# --- Helpers ---

def _parse_jsonb(value, default=None):
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return default
    return default


async def _get_project_id(tenant_id: str) -> str:
    """Get the current project ID for a tenant."""
    row = await _get_or_create_project(tenant_id)
    return str(row["id"])


async def _list_styles_with_characters(project_id: str) -> list[VisualStyleRead]:
    """Fetch all styles for a project with their characters."""
    styles = await fetch_all(
        """SELECT id, name, style_profile, reference_image_url, is_active, is_default, created_at
           FROM visual_styles WHERE project_id = $1
           ORDER BY
             is_active DESC,
             is_default ASC,
             created_at DESC""",
        project_id,
    )

    result = []
    for s in styles:
        chars = await fetch_all(
            """SELECT id, name, image_url, sort_order
               FROM style_characters WHERE visual_style_id = $1
               ORDER BY sort_order, created_at""",
            str(s["id"]),
        )
        result.append(VisualStyleRead(
            id=str(s["id"]),
            name=s["name"],
            style_profile=_parse_jsonb(s["style_profile"], {}),
            reference_image_url=s.get("reference_image_url"),
            is_active=s["is_active"],
            is_default=s["is_default"],
            characters=[
                StyleCharacterRead(
                    id=str(c["id"]),
                    name=c["name"],
                    image_url=c["image_url"],
                    sort_order=c.get("sort_order", 0),
                )
                for c in chars
            ],
        ))

    return result


# --- Endpoints ---

@router.get("", response_model=list[VisualStyleRead])
async def list_visual_styles(tenant_id: str = Depends(get_tenant_id)):
    """List all visual styles for the current project with characters."""
    project_id = await _get_project_id(tenant_id)
    return await _list_styles_with_characters(project_id)


@router.post("", response_model=VisualStyleRead)
async def create_visual_style(
    req: CreateStyleRequest,
    tenant_id: str = Depends(get_tenant_id),
):
    """Create a new visual style from the AI generator."""
    project_id = await _get_project_id(tenant_id)

    if not req.name or not req.name.strip():
        raise HTTPException(status_code=400, detail="Style name is required")

    style_json = json.dumps(req.style_profile)

    row = await fetch_one(
        """INSERT INTO visual_styles (project_id, name, style_profile, reference_image_url, is_active, is_default)
           VALUES ($1, $2, $3::jsonb, $4, false, false)
           RETURNING id, name, style_profile, reference_image_url, is_active, is_default""",
        project_id,
        req.name.strip(),
        style_json,
        req.reference_image_url,
    )

    return VisualStyleRead(
        id=str(row["id"]),
        name=row["name"],
        style_profile=_parse_jsonb(row["style_profile"], {}),
        reference_image_url=row.get("reference_image_url"),
        is_active=row["is_active"],
        is_default=row["is_default"],
        characters=[],
    )


@router.put("/{style_id}/activate", response_model=list[VisualStyleRead])
async def activate_visual_style(
    style_id: str,
    tenant_id: str = Depends(get_tenant_id),
):
    """Set a style as active. Deactivates all others for this project."""
    project_id = await _get_project_id(tenant_id)

    # Verify style belongs to this project
    style = await fetch_one(
        "SELECT id FROM visual_styles WHERE id = $1 AND project_id = $2",
        style_id, project_id,
    )
    if not style:
        raise HTTPException(status_code=404, detail="Style not found")

    # Deactivate all, then activate the selected one
    await execute(
        "UPDATE visual_styles SET is_active = false, updated_at = now() WHERE project_id = $1",
        project_id,
    )
    await execute(
        "UPDATE visual_styles SET is_active = true, updated_at = now() WHERE id = $1",
        style_id,
    )

    return await _list_styles_with_characters(project_id)


@router.delete("/{style_id}")
async def delete_visual_style(
    style_id: str,
    tenant_id: str = Depends(get_tenant_id),
):
    """Delete a user-created style. Cannot delete default styles."""
    project_id = await _get_project_id(tenant_id)

    style = await fetch_one(
        "SELECT id, is_default, is_active FROM visual_styles WHERE id = $1 AND project_id = $2",
        style_id, project_id,
    )
    if not style:
        raise HTTPException(status_code=404, detail="Style not found")
    if style["is_default"]:
        raise HTTPException(status_code=403, detail="Cannot delete default styles")

    # If deleting the active style, activate the first default
    if style["is_active"]:
        await execute(
            """UPDATE visual_styles SET is_active = true, updated_at = now()
               WHERE project_id = $1 AND is_default = true
               ORDER BY created_at LIMIT 1""",
            project_id,
        )

    # Cascade deletes characters via FK
    await execute("DELETE FROM visual_styles WHERE id = $1", style_id)

    return {"status": "ok"}


# --- Character endpoints ---

@router.post("/{style_id}/characters", response_model=StyleCharacterRead)
async def create_character(
    style_id: str,
    req: CreateCharacterRequest,
    tenant_id: str = Depends(get_tenant_id),
):
    """Create a character for a visual style."""
    project_id = await _get_project_id(tenant_id)

    # Verify style belongs to project
    style = await fetch_one(
        "SELECT id FROM visual_styles WHERE id = $1 AND project_id = $2",
        style_id, project_id,
    )
    if not style:
        raise HTTPException(status_code=404, detail="Style not found")

    if not req.name or not req.name.strip():
        raise HTTPException(status_code=400, detail="Character name is required")
    if not req.image_url or not req.image_url.strip():
        raise HTTPException(status_code=400, detail="Character image is required")

    # Get next sort order
    max_order = await fetch_one(
        "SELECT COALESCE(MAX(sort_order), -1) as max_order FROM style_characters WHERE visual_style_id = $1",
        style_id,
    )
    next_order = (max_order["max_order"] or 0) + 1

    row = await fetch_one(
        """INSERT INTO style_characters (visual_style_id, name, image_url, sort_order)
           VALUES ($1, $2, $3, $4)
           RETURNING id, name, image_url, sort_order""",
        style_id,
        req.name.strip(),
        req.image_url.strip(),
        next_order,
    )

    return StyleCharacterRead(
        id=str(row["id"]),
        name=row["name"],
        image_url=row["image_url"],
        sort_order=row["sort_order"],
    )


@router.delete("/{style_id}/characters/{character_id}")
async def delete_character(
    style_id: str,
    character_id: str,
    tenant_id: str = Depends(get_tenant_id),
):
    """Delete a character from a style."""
    project_id = await _get_project_id(tenant_id)

    # Verify style belongs to project
    style = await fetch_one(
        "SELECT id FROM visual_styles WHERE id = $1 AND project_id = $2",
        style_id, project_id,
    )
    if not style:
        raise HTTPException(status_code=404, detail="Style not found")

    result = await execute(
        "DELETE FROM style_characters WHERE id = $1 AND visual_style_id = $2",
        character_id, style_id,
    )

    return {"status": "ok"}


# --- Character generation (Kie.ai) ---

@router.post("/characters/generate")
async def generate_character(
    req: GenerateCharacterRequest,
    tenant_id: str = Depends(get_tenant_id),
):
    """Generate a character image using Kie.ai Nano Banana 2.

    Assembles a prompt from the user's description + the active style's profile.
    Uses the user's own Kie.ai API key from Vault.
    """
    import httpx
    from vault import get_secret

    project_id = await _get_project_id(tenant_id)

    # Get the style's profile for context
    style = await fetch_one(
        "SELECT id, style_profile FROM visual_styles WHERE id = $1 AND project_id = $2",
        req.style_id, project_id,
    )
    if not style:
        raise HTTPException(status_code=404, detail="Style not found")

    # Get Kie.ai API key
    api_key = await get_secret("kie_ai_api_key", tenant_id)
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="Kie.ai API key not configured. Go to Settings → API Keys to add it.",
        )

    # Build prompt from style context + user description
    profile = _parse_jsonb(style["style_profile"], {})
    lighting = profile.get("lighting", "")
    mood = profile.get("mood", "")
    texture = profile.get("texture", "")

    full_prompt = f"{lighting}. {mood}. {req.prompt.strip()}. {texture}. No text, no watermarks."

    # Call Kie.ai API
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            # Create task
            create_resp = await client.post(
                "https://api.kie.ai/api/v1/jobs/createTask",
                json={
                    "model": "nano-banana-2",
                    "prompt": full_prompt,
                    "aspect_ratio": "1:1",
                },
                headers={"Authorization": f"Bearer {api_key}"},
            )
            create_resp.raise_for_status()
            task_data = create_resp.json()
            task_id = task_data.get("data", {}).get("task_id") or task_data.get("task_id")

            if not task_id:
                raise HTTPException(status_code=500, detail="Failed to create generation task")

            # Poll for completion (up to 60s)
            import asyncio
            for _ in range(30):
                await asyncio.sleep(2)
                status_resp = await client.get(
                    f"https://api.kie.ai/api/v1/jobs/getTaskStatus/{task_id}",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                status_resp.raise_for_status()
                status_data = status_resp.json()
                task_status = status_data.get("data", {}).get("status", 0)

                if task_status == 2:  # Success
                    image_url = status_data.get("data", {}).get("output", [None])[0]
                    if image_url:
                        return {"status": "ok", "image_url": image_url, "prompt": full_prompt}
                    raise HTTPException(status_code=500, detail="Generation succeeded but no image URL returned")
                elif task_status == 3:  # Failed
                    raise HTTPException(status_code=500, detail="Image generation failed")

            raise HTTPException(status_code=504, detail="Generation timed out after 60s")

    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Kie.ai API error: {str(e)}")
