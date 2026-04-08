"""Tenant-level system prompt defaults CRUD."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from auth import get_tenant_id
from database import fetch_all, fetch_one, execute
from prompt_defaults import PROMPT_DEFAULTS

router = APIRouter(prefix="/api/system-prompts", tags=["system-prompts"])

PROMPT_META = {
    "script": {"label": "Script", "description": "Channel voice and structural rules for narration"},
    "thumbnail": {"label": "Thumbnail", "description": "Visual director instructions for thumbnail template variables"},
    "video_motion": {"label": "Video Motion", "description": "Cinematographer instructions for AI video generation"},
    "sound_curation": {"label": "Sound Curation", "description": "Decides which images get sound effects"},
    "sound_generation": {"label": "Sound Generation", "description": "Generates sound effect descriptions"},
    "research": {"label": "Research", "description": "Research analyst persona and instructions"},
}


class PromptUpdate(BaseModel):
    prompt_text: str


@router.get("")
async def list_prompts(tenant_id: str = Depends(get_tenant_id)):
    """List all system prompts with their current values (custom or default)."""
    rows = await fetch_all(
        "SELECT prompt_key, prompt_text FROM tenant_prompt_defaults WHERE tenant_id = $1",
        tenant_id,
    )
    overrides = {r["prompt_key"]: r["prompt_text"] for r in rows}

    result = []
    for key, default_text in PROMPT_DEFAULTS.items():
        meta = PROMPT_META.get(key, {"label": key, "description": ""})
        is_custom = key in overrides
        result.append({
            "key": key,
            "label": meta["label"],
            "description": meta["description"],
            "prompt": overrides[key] if is_custom else default_text,
            "is_custom": is_custom,
        })
    return result


@router.put("/{key}")
async def upsert_prompt(key: str, body: PromptUpdate, tenant_id: str = Depends(get_tenant_id)):
    """Save a custom prompt override for this tenant."""
    if key not in PROMPT_DEFAULTS:
        raise HTTPException(status_code=404, detail=f"Unknown prompt key: {key}")
    await execute(
        """INSERT INTO tenant_prompt_defaults (tenant_id, prompt_key, prompt_text, updated_at)
           VALUES ($1, $2, $3, now())
           ON CONFLICT (tenant_id, prompt_key)
           DO UPDATE SET prompt_text = $3, updated_at = now()""",
        tenant_id, key, body.prompt_text,
    )
    return {"status": "saved", "key": key}


@router.delete("/{key}")
async def reset_prompt(key: str, tenant_id: str = Depends(get_tenant_id)):
    """Delete custom override, reverting to pipeline default."""
    if key not in PROMPT_DEFAULTS:
        raise HTTPException(status_code=404, detail=f"Unknown prompt key: {key}")
    await execute(
        "DELETE FROM tenant_prompt_defaults WHERE tenant_id = $1 AND prompt_key = $2",
        tenant_id, key,
    )
    return {"status": "reset", "key": key, "prompt": PROMPT_DEFAULTS[key]}
