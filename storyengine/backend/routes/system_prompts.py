"""Tenant-level system prompt defaults CRUD."""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from auth import get_tenant_id
from database import fetch_all, fetch_one, execute
from error_utils import humanize_error
from prompt_defaults import PROMPT_DEFAULTS, META_PROMPT_TEMPLATE
# Single Claude tier source (checklist §3.4 / C35) — see shared.channel_profile.
from actions import CLAUDE_MODELS
# Provenance envelope (checklist C40/C43): this endpoint's style_description
# write used to be a blind `UPDATE ... SET style_description = $2` — the
# SAME column identity_builder.build_channel_identity writes (COALESCE) and
# stamps into channel_identity._sources. A manual "generate my prompts"
# here could silently overwrite a DNA-learned voice with no record of who
# did it or when. Stamping through the shared helper doesn't change the
# precedence (a later identity_builder rebuild still COALESCEs and this
# route still always wins its own column write) — it only makes the
# overwrite VISIBLE in the next channel-DNA digest instead of silent.
from channel_dna_meta import coerce_identity, stamp_identity_write

logger = logging.getLogger(__name__)

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


class StyleGenerateRequest(BaseModel):
    style_description: str
    channel_name: Optional[str] = None
    niche: Optional[str] = None
    target_audience: Optional[str] = None


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


PROMPT_KEYS = ["script", "thumbnail", "video_motion", "sound_curation", "sound_generation", "research"]


@router.post("/generate")
async def generate_prompts(body: StyleGenerateRequest, tenant_id: str = Depends(get_tenant_id)):
    """Generate all 6 system prompts from a plain-English style description using Claude."""
    from vault import get_secret

    api_key = await get_secret("anthropic_api_key", tenant_id)
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="Anthropic API key required. Configure it in Settings > API Keys.",
        )

    # Build the meta-prompt with default templates
    meta_prompt = META_PROMPT_TEMPLATE.format(
        channel_name=body.channel_name or "Not specified",
        niche=body.niche or "Not specified",
        target_audience=body.target_audience or "Not specified",
        style_description=body.style_description,
        script_template=PROMPT_DEFAULTS["script"],
        thumbnail_template=PROMPT_DEFAULTS["thumbnail"],
        video_motion_template=PROMPT_DEFAULTS["video_motion"],
        sound_curation_template=PROMPT_DEFAULTS["sound_curation"],
        sound_generation_template=PROMPT_DEFAULTS["sound_generation"],
        research_template=PROMPT_DEFAULTS["research"],
    )

    # Call Claude API
    import httpx

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": CLAUDE_MODELS["anthropic"]["smart"],
                    "max_tokens": 8000,
                    "messages": [{"role": "user", "content": meta_prompt}],
                },
            )

        if resp.status_code != 200:
            logger.error("Claude API error %s: %s", resp.status_code, resp.text[:500])
            raise HTTPException(
                status_code=502,
                detail=humanize_error(
                    f"Claude {resp.status_code}",
                    context="We couldn't generate your style prompts",
                ),
            )

        data = resp.json()
        raw_text = data["content"][0]["text"]
    except httpx.HTTPError as exc:
        logger.error("Claude API request failed: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to reach Claude API")

    # Parse Claude's JSON response
    try:
        generated = json.loads(raw_text)
    except json.JSONDecodeError:
        logger.error("Failed to parse Claude response as JSON: %s", raw_text[:500])
        raise HTTPException(
            status_code=502,
            detail="Claude returned malformed JSON. Try again.",
        )

    # Validate all 6 keys are present
    missing = [k for k in PROMPT_KEYS if k not in generated]
    if missing:
        raise HTTPException(
            status_code=502,
            detail=f"Claude response missing prompt keys: {', '.join(missing)}",
        )

    summary = generated.pop("summary", "Custom style generated successfully.")

    # Save all 6 prompts via upsert
    for key in PROMPT_KEYS:
        await execute(
            """INSERT INTO tenant_prompt_defaults (tenant_id, prompt_key, prompt_text, updated_at)
               VALUES ($1, $2, $3, now())
               ON CONFLICT (tenant_id, prompt_key)
               DO UPDATE SET prompt_text = $3, updated_at = now()""",
            tenant_id, key, generated[key],
        )

    # Save style_description to channel_profiles, AND stamp the same value
    # into channel_identity's provenance envelope (learner="system_prompts")
    # so a later DNA digest shows this manual override instead of it being
    # a silent, unattributed overwrite of whatever identity_builder learned.
    row = await fetch_one(
        "SELECT channel_identity FROM channel_profiles WHERE tenant_id = $1", tenant_id
    )
    current = coerce_identity((row or {}).get("channel_identity"))
    merged = stamp_identity_write(
        current, {"style_description": body.style_description}, learner="system_prompts"
    )
    await execute(
        "UPDATE channel_profiles SET style_description = $2, channel_identity = $3::jsonb "
        "WHERE tenant_id = $1",
        tenant_id, body.style_description, json.dumps(merged),
    )

    return {
        "status": "generated",
        "summary": summary,
        "prompts": {
            key: {
                "key": key,
                "label": PROMPT_META[key]["label"],
                "prompt": generated[key],
            }
            for key in PROMPT_KEYS
        },
    }
