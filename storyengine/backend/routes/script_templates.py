"""The channel's house script format ("remember how this script is built").

The creator drops an example script and says "write mine like this" — one
model call distills the FORMAT (hook shape, segment structure, transitions,
pacing, recurring devices, sign-off — never the topic) into imperative writing
instructions, saved as the tenant's single house template. Uploading a new
example replaces it. At video creation/launch the template is prepended to
videos.script_system_prompt, which rides the existing prompt precedence chain
(per-video > tenant defaults > engine templates), so EVERY pathway — chat,
queue, autopilot, UI — writes scripts in the house format with zero
pipeline_executor changes.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from auth import get_tenant_id
from database import execute, fetch_all, fetch_one

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/script-templates", tags=["script-templates"])

ANALYZER_PROMPT = """You are a script-format analyst for a video studio. Below is an example script a creator provided. Extract HOW it is built — never WHAT it is about.

Write imperative instructions (for a script writer) covering, where present:
- Hook: how the opening works (shape, length, what it promises)
- Structure: the segments/beats and their order (e.g. intro -> spec rundown -> field test -> verdict)
- Transitions: how it moves between segments
- Pacing: sentence rhythm, paragraph length, information density
- Recurring devices: catchphrases, question patterns, callbacks, humor style
- Voice/tone: how it sounds when read aloud
- Sign-off: how it ends

Rules: NO topic content from the example (no product names, no facts). Under 300 words. Output ONLY the instructions, no preamble.

EXAMPLE SCRIPT:
"""


async def analyze_and_save_template(
    tenant_id, text: str, name: str, source_asset_id: Optional[str] = None
) -> dict:
    """Distill the format from an example script and save it as THE house
    template (replaces any existing one). Returns the saved row as a dict.
    Raises ValueError when the example or the analysis is unusable."""
    text = (text or "").strip()
    if len(text.split()) < 40:
        raise ValueError("That example is too short to learn a format from — give me a full script.")

    from kie_unified import get_text_client_for_tenant
    client = await get_text_client_for_tenant(tenant_id)
    # Direct-API tenants need a real model id — the KIE default env value can
    # be stale for the direct endpoint (same guard as youtube_publish.py).
    kwargs = {"model": "claude-sonnet-4-6"} if type(client).__name__ == "AnthropicDirectClient" else {}
    structure = (await client.generate(
        prompt=ANALYZER_PROMPT + text[:24000],
        max_tokens=1200,
        temperature=0.3,
        **kwargs,
    ) or "").strip()
    if len(structure.split()) < 20:
        raise ValueError("I couldn't distill a usable format from that example.")

    # One house template per channel: replace, don't accumulate.
    await execute("DELETE FROM script_templates WHERE tenant_id = $1", tenant_id)
    row = await fetch_one(
        """INSERT INTO script_templates (tenant_id, name, structure, example_excerpt, source_asset_id)
           VALUES ($1, $2, $3, $4, $5) RETURNING id, name, structure, created_at""",
        tenant_id, (name or "House format").strip()[:120], structure, text[:800], source_asset_id,
    )
    return dict(row)


async def apply_default_template(tenant_id, video_id: str) -> bool:
    """Prepend the house template's format instructions to this video's
    script_system_prompt (creating it when empty). Fail-soft: returns False
    when there's no template or on any error — never blocks a launch."""
    try:
        tpl = await fetch_one(
            "SELECT structure FROM script_templates WHERE tenant_id = $1 AND is_default "
            "ORDER BY created_at DESC LIMIT 1",
            tenant_id,
        )
        if not tpl or not (tpl.get("structure") or "").strip():
            return False
        block = "## The channel's house script format (follow this)\n" + tpl["structure"]
        await execute(
            """UPDATE videos SET script_system_prompt =
                   $1 || COALESCE(E'\n\n' || script_system_prompt, ''), updated_at = now()
               WHERE id = $2 AND tenant_id = $3""",
            block, video_id, tenant_id,
        )
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("script_templates: apply failed for %s: %s", video_id, e)
        return False


# --- routes ------------------------------------------------------------------

@router.get("")
async def list_templates(tenant_id=Depends(get_tenant_id)):
    rows = await fetch_all(
        "SELECT id, name, structure, example_excerpt, is_default, created_at "
        "FROM script_templates WHERE tenant_id = $1 ORDER BY created_at DESC",
        tenant_id,
    )
    return {"templates": [dict(r) for r in rows]}


@router.post("/analyze")
async def analyze_template(body: dict, tenant_id=Depends(get_tenant_id)):
    """{"text": "...", "name": "..."} or {"asset_id": "...", "name": "..."}."""
    text = str((body or {}).get("text") or "").strip()
    asset_id = str((body or {}).get("asset_id") or "").strip() or None
    if not text and asset_id:
        row = await fetch_one(
            "SELECT parsed_text FROM chat_assets WHERE id = $1 AND tenant_id = $2",
            asset_id, tenant_id,
        )
        text = ((row or {}).get("parsed_text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="No script text to analyze.")
    try:
        tpl = await analyze_and_save_template(
            tenant_id, text, str((body or {}).get("name") or ""), asset_id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "saved", "template": tpl}


@router.delete("/{template_id}")
async def delete_template(template_id: str, tenant_id=Depends(get_tenant_id)):
    await execute(
        "DELETE FROM script_templates WHERE id = $1 AND tenant_id = $2", template_id, tenant_id
    )
    return {"status": "deleted"}
