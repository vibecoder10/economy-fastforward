"""Per-channel pattern CRUD + confirm/retire (checklist C46e, OR-6 EXPANDED).

Thin tenant-scoped HTTP shape over ``channel_patterns.py`` (migration 106).
Mirrors ``routes/quality_rules.py``'s own precedent exactly: no UI beyond the
chat digest card this chunk also wires (routes/chat.py's
``_handle_dna_digest_action`` "confirm_pattern"/"retire_pattern" actions
already call the SAME module functions directly, same-process, no HTTP
round-trip needed there). This route exists for:
  - C47's MCP setup surface to pick up ("read/write channel patterns"
    alongside quality rules / system prompts / channel DNA).
  - A future settings page.
  - Any external caller (including the launch-time P4.2 flywheel, once
    built) that isn't already inside the backend process.

All writes go through ``channel_patterns.py``'s CRUD functions — this file
is just the HTTP shape around them, never a second implementation.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_tenant_id
import channel_patterns

router = APIRouter(prefix="/api/channel-patterns", tags=["channel-patterns"])


class CreatePatternRequest(BaseModel):
    pattern: str
    polarity: str = "anti"
    evidence: Optional[dict] = None


class UpdatePatternRequest(BaseModel):
    pattern: Optional[str] = None
    polarity: Optional[str] = None
    evidence: Optional[dict] = None


class ConfirmRetireRequest(BaseModel):
    confirmed_by: Optional[str] = None


@router.get("")
async def list_patterns(
    polarity: Optional[str] = None, status: Optional[str] = None, tenant_id=Depends(get_tenant_id)
):
    rows = await channel_patterns.list_patterns(tenant_id, polarity=polarity, status=status)
    return {"patterns": rows}


@router.post("")
async def create_pattern(body: CreatePatternRequest, tenant_id=Depends(get_tenant_id)):
    if not body.pattern.strip():
        raise HTTPException(status_code=400, detail="pattern is required.")
    if body.polarity not in channel_patterns.POLARITIES:
        raise HTTPException(
            status_code=400,
            detail=f"polarity must be one of {sorted(channel_patterns.POLARITIES)}",
        )
    row = await channel_patterns.create_pattern(
        tenant_id,
        pattern=body.pattern.strip(),
        polarity=body.polarity,
        evidence=body.evidence,
        source="manual",
        status="proposed",
    )
    return {"pattern": row}


@router.patch("/{id}")
async def update_pattern(id: str, body: UpdatePatternRequest, tenant_id=Depends(get_tenant_id)):
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")
    if "polarity" in updates and updates["polarity"] not in channel_patterns.POLARITIES:
        raise HTTPException(
            status_code=400,
            detail=f"polarity must be one of {sorted(channel_patterns.POLARITIES)}",
        )
    row = await channel_patterns.update_pattern(tenant_id, id, updates)
    if row is None:
        raise HTTPException(status_code=404, detail="Pattern not found.")
    return {"pattern": row}


@router.post("/{id}/confirm")
async def confirm_pattern(id: str, body: ConfirmRetireRequest, tenant_id=Depends(get_tenant_id)):
    row = await channel_patterns.confirm_pattern(tenant_id, id, confirmed_by=body.confirmed_by)
    if row is None:
        raise HTTPException(status_code=404, detail="Pattern not found.")
    return {"pattern": row}


@router.post("/{id}/retire")
async def retire_pattern(id: str, body: ConfirmRetireRequest, tenant_id=Depends(get_tenant_id)):
    row = await channel_patterns.retire_pattern(tenant_id, id, confirmed_by=body.confirmed_by)
    if row is None:
        raise HTTPException(status_code=404, detail="Pattern not found.")
    return {"pattern": row}
