"""Visual styles routes — CRUD for visual styles and their characters.

Each project has multiple visual styles (4 defaults + user-created).
Only one style per project can be active at a time.
Characters belong to a specific style and cascade-delete with it.
"""

import asyncio
import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_tenant_id
from database import fetch_one, fetch_all, execute
from error_utils import humanize_error
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


# =============================================================
# IMPORTANT: Non-parameterized routes MUST come BEFORE /{style_id}
# routes to avoid FastAPI matching "characters" as a style_id.
# =============================================================

# --- Character generation (Kie.ai) — must be before /{style_id} routes ---

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

    # Prefer prompt_prefix (new detailed schema) over assembling from parts
    prompt_prefix = profile.get("prompt_prefix", "")
    if not prompt_prefix:
        # Fallback: assemble from individual fields (old schema)
        lighting = profile.get("lighting", "")
        mood = profile.get("mood", "")
        texture = profile.get("texture", "")
        prompt_prefix = f"{lighting}. {mood}. {texture}."

    full_prompt = f"{prompt_prefix.rstrip('.')}. {req.prompt.strip()}. No text, no watermarks."

    # Call Kie.ai API — correct format per image_client.py
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=10)) as client:
            # Create task
            create_resp = await client.post(
                "https://api.kie.ai/api/v1/jobs/createTask",
                json={
                    "model": "nano-banana-2",
                    "input": {
                        "prompt": full_prompt,
                        "aspect_ratio": "1:1",
                        "output_format": "png",
                    },
                },
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
            if create_resp.status_code != 200:
                raise HTTPException(
                    status_code=502,
                    detail=humanize_error(
                        f"Kie.ai {create_resp.status_code}: {create_resp.text[:300]}",
                        context="We couldn't start character generation",
                    ),
                )

            task_data = create_resp.json()
            data = task_data.get("data", {})
            task_id = data.get("task_id") or data.get("taskId") or task_data.get("task_id") or task_data.get("taskId")

            if not task_id:
                raise HTTPException(
                    status_code=500,
                    detail=humanize_error(
                        f"No task_id in response: {json.dumps(task_data)[:300]}",
                        context="Character generation didn't start correctly",
                    ),
                )

            # Poll for completion — correct endpoint: /jobs/recordInfo?taskId=xxx
            # 5s interval, 60 attempts (5 minutes)
            for attempt in range(60):
                await asyncio.sleep(5)
                status_resp = await client.get(
                    "https://api.kie.ai/api/v1/jobs/recordInfo",
                    params={"taskId": task_id},
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                if status_resp.status_code != 200:
                    continue  # Transient error, keep polling

                status_data = status_resp.json()
                data = status_data.get("data", {})
                task_status = data.get("status")
                task_state = data.get("state")

                # Check for failure (status=3 or state contains "fail")
                if (task_status == 3
                    or str(task_status).lower() in ("failed", "failure", "error")
                    or str(task_state).lower() in ("fail", "failed", "failure", "error")):
                    error_msg = data.get("errorMessage") or data.get("error") or "Unknown error"
                    raise HTTPException(
                        status_code=500,
                        detail=humanize_error(error_msg, context="We couldn't generate your character image"),
                    )

                # Check for completion — extract from resultJson.resultUrls
                result_json = data.get("resultJson")
                if result_json:
                    if isinstance(result_json, str):
                        result_json = json.loads(result_json)
                    result_urls = result_json.get("resultUrls", [])
                    if result_urls:
                        return {"status": "ok", "image_url": result_urls[0], "prompt": full_prompt}

            raise HTTPException(status_code=504, detail="Generation timed out after 5 minutes")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=humanize_error(e, context="We couldn't generate your character image"),
        )


# --- Image analysis (Gemini Vision) — must be before /{style_id} routes ---

class AnalyzeImageRequest(BaseModel):
    image_data: str  # base64 data URL or URL

@router.post("/analyze-image")
async def analyze_image(
    req: AnalyzeImageRequest,
    tenant_id: str = Depends(get_tenant_id),
):
    """Analyze a reference image using Gemini Vision to extract visual style profile."""
    import httpx
    from vault import get_secret

    api_key = await get_secret("gemini_api_key", tenant_id)
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="Gemini API key not configured. Go to Settings → API Keys to add it.",
        )

    # Build the Gemini request
    prompt = """Describe EXACTLY what you see in this specific image. Do not use generic descriptions. Every field must reference specific visual elements visible in the image.

Analyze this image and extract a detailed visual style profile as JSON. Return ONLY valid JSON with these exact fields:

{
  "style_name_suggestion": "A short descriptive name for this visual style",
  "art_medium": "The specific art medium or technique used",
  "rendering_style": "How the image is rendered (brushstrokes, gradients, etc.)",
  "line_work": "Description of outlines, edges, and line quality",
  "color_palette": {
    "primary": "#hex",
    "secondary": "#hex",
    "accent": "#hex",
    "highlight": "#hex",
    "shadow": "#hex",
    "palette_description": "Describe the overall color feel"
  },
  "lighting": "Describe the light sources, direction, and quality",
  "shadow_style": "How shadows are rendered",
  "composition": "Layout and framing description",
  "texture": "Surface textures, grain, effects",
  "character_rendering": "How people/figures are depicted",
  "background_style": "Background treatment and detail level",
  "mood": "Emotional tone and atmosphere",
  "era_influence": "Historical or cultural aesthetic influence",
  "unique_elements": ["element1", "element2", "element3"],
  "prompt_prefix": "A single sentence that captures the complete visual style for use as an image generation prompt prefix. Include medium, lighting, color palette, texture, and composition."
}"""

    # Prepare the image content
    image_parts = []
    if req.image_data.startswith("data:"):
        # Base64 data URL
        header, b64data = req.image_data.split(",", 1)
        mime_type = header.split(":")[1].split(";")[0]
        image_parts.append({
            "inline_data": {
                "mime_type": mime_type,
                "data": b64data,
            }
        })
    else:
        # URL
        image_parts.append({
            "file_data": {
                "mime_type": "image/jpeg",
                "file_uri": req.image_data,
            }
        })

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}",
                json={
                    "contents": [{
                        "parts": [
                            {"text": prompt},
                            *image_parts,
                        ]
                    }],
                    "generationConfig": {
                        "temperature": 0.3,
                        "maxOutputTokens": 2048,
                    }
                },
            )

            if resp.status_code != 200:
                raise HTTPException(
                    status_code=502,
                    detail=humanize_error(
                        f"Gemini {resp.status_code}: {resp.text[:300]}",
                        context="We couldn't analyze that image",
                    ),
                )

            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]

            # Parse JSON from response (handle markdown fences)
            import re
            text = text.strip()
            text = re.sub(r'^```json?\s*', '', text)
            text = re.sub(r'\s*```$', '', text)
            text = text.strip()

            result = json.loads(text)
            return {"status": "ok", "profile": result}

    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=500,
            detail=humanize_error(e, context="We couldn't read the image analysis response"),
        )
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=humanize_error(e, context="We couldn't analyze that image"),
        )


# --- List + Create (non-parameterized) ---

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


# --- Parameterized routes (/{style_id}) ---

@router.put("/{style_id}/activate", response_model=list[VisualStyleRead])
async def activate_visual_style(
    style_id: str,
    tenant_id: str = Depends(get_tenant_id),
):
    """Set a style as active. Deactivates all others for this project."""
    project_id = await _get_project_id(tenant_id)

    style = await fetch_one(
        "SELECT id FROM visual_styles WHERE id = $1 AND project_id = $2",
        style_id, project_id,
    )
    if not style:
        raise HTTPException(status_code=404, detail="Style not found")

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
        first_default = await fetch_one(
            "SELECT id FROM visual_styles WHERE project_id = $1 AND is_default = true ORDER BY created_at LIMIT 1",
            project_id,
        )
        if first_default:
            await execute(
                "UPDATE visual_styles SET is_active = true, updated_at = now() WHERE id = $1",
                str(first_default["id"]),
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

    style = await fetch_one(
        "SELECT id FROM visual_styles WHERE id = $1 AND project_id = $2",
        style_id, project_id,
    )
    if not style:
        raise HTTPException(status_code=404, detail="Style not found")

    await execute(
        "DELETE FROM style_characters WHERE id = $1 AND visual_style_id = $2",
        character_id, style_id,
    )

    return {"status": "ok"}
