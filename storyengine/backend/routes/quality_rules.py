"""Per-channel quality-rules CRUD (checklist C46b).

Thin tenant-scoped CRUD over the `quality_rules` table (migration 105).
No UI this chunk (per the checklist's own spec) — this exists for:
  - C47's MCP setup surface to pick up ("read/write quality rules" alongside
    system prompts / script templates / channel DNA).
  - chat.py's `draft_quality_rules` confirm handler (routes/chat.py), which
    calls `quality_rules.bulk_create_rules` directly rather than through
    this route (same-process call, no need to round-trip HTTP).
  - A future settings page.

All writes go through `quality_rules.py`'s CRUD functions — this file is
just the HTTP shape around them, never a second implementation.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_tenant_id
import quality_rules

router = APIRouter(prefix="/api/quality-rules", tags=["quality-rules"])


class CreateRuleRequest(BaseModel):
    rule_id: str
    law: str
    severity: str = "guidance"
    evidence: Optional[str] = None
    applies_to: Optional[dict] = None


class UpdateRuleRequest(BaseModel):
    law: Optional[str] = None
    evidence: Optional[str] = None
    severity: Optional[str] = None
    applies_to: Optional[dict] = None
    active: Optional[bool] = None


@router.get("")
async def list_rules(active_only: bool = False, tenant_id=Depends(get_tenant_id)):
    rows = await quality_rules.list_all_rules(tenant_id, active_only=active_only)
    return {"rules": rows}


@router.post("")
async def create_rule(body: CreateRuleRequest, tenant_id=Depends(get_tenant_id)):
    if not body.rule_id.strip() or not body.law.strip():
        raise HTTPException(status_code=400, detail="rule_id and law are required.")
    if body.severity not in quality_rules.SEVERITIES:
        raise HTTPException(
            status_code=400,
            detail=f"severity must be one of {sorted(quality_rules.SEVERITIES)}",
        )
    row = await quality_rules.create_rule(
        tenant_id,
        rule_id=body.rule_id.strip(),
        law=body.law.strip(),
        severity=body.severity,
        evidence=body.evidence,
        applies_to=body.applies_to,
        source="chat",
    )
    return {"rule": row}


@router.patch("/{id}")
async def update_rule(id: str, body: UpdateRuleRequest, tenant_id=Depends(get_tenant_id)):
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")
    if "severity" in updates and updates["severity"] not in quality_rules.SEVERITIES:
        raise HTTPException(
            status_code=400,
            detail=f"severity must be one of {sorted(quality_rules.SEVERITIES)}",
        )
    row = await quality_rules.update_rule(tenant_id, id, updates)
    if row is None:
        raise HTTPException(status_code=404, detail="Rule not found.")
    return {"rule": row}


@router.delete("/{id}")
async def deactivate_rule(id: str, tenant_id=Depends(get_tenant_id)):
    ok = await quality_rules.deactivate_rule(tenant_id, id)
    if not ok:
        raise HTTPException(status_code=404, detail="Rule not found.")
    return {"status": "deactivated"}
