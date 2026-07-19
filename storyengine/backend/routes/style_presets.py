"""GET /api/style-presets — catalog of the 5 rich Python visual-profile
engines (skills/video-pipeline/shared/profiles/visual/*.py), backed by the
`style_presets` table (migration 096, checklist §2.1 chunk C20).

Before this route existed, those 5 profiles (neutral_v1, holographic_hud,
cinematic_dossier, clay_mannequin, cinematic_illustration — each with its own
scene-type variety, camera/composition cycling, anti-clustering rules) were
invisible to users; the UI only offered 6 shallow hardcoded "look" presets
(frontend/src/lib/visual-presets.ts) that feed a completely different axis
(VISUAL_STYLE_DESCRIPTION, a free-text aesthetic overlay — see that table's
schema.sql comment and docs/reports/2026-07-17-storyengine-agent-audit-
findings.md §S9-5 for the full reconciliation note, left for C21).

This is a GLOBAL catalog, not tenant-scoped data — same posture as GET
/api/models (routes/model_registry.py): any authenticated tenant reads the
shared table, no per-tenant filter. Auth is required anyway (mirroring that
route) rather than left open, since every other route in this app requires
it and an unauthenticated style-catalog leak has no upside.

C21 (checklist §2.1 [U]) builds the gallery UI + chat LOOK card off this
endpoint and reconciles with the existing visual_styles CRUD (S9-5).
"""
import json
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth import get_tenant_id
from database import fetch_all

router = APIRouter(prefix="/api/style-presets", tags=["style-presets"])


def _parse_jsonb_list(value) -> list:
    """style_presets.tags/best_for are JSONB — asyncpg returns them as
    native Python lists via the default codec in this app (see database.py),
    but tolerate a raw JSON string too (mirrors routes/visual_styles.py's
    _parse_jsonb, same defensive reason: never trust the wire shape)."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, TypeError):
            return []
    return []


class StylePresetResponse(BaseModel):
    id: str
    display_name: str
    description: Optional[str] = None
    tags: list[str] = []
    best_for: list[str] = []
    cost_tier: Optional[str] = None
    preview_url: Optional[str] = None
    source: str = "python_profile"
    sort: int = 0


class StylePresetsResponse(BaseModel):
    presets: list[StylePresetResponse]


@router.get("", response_model=StylePresetsResponse)
async def list_style_presets(tenant_id: str = Depends(get_tenant_id)):
    """Active style presets, ordered for gallery display (sort, then id)."""
    rows = await fetch_all(
        """SELECT id, display_name, description, tags, best_for, cost_tier,
                  preview_url, source, sort
           FROM style_presets WHERE active = true ORDER BY sort, id"""
    )
    presets = [
        StylePresetResponse(
            id=r["id"],
            display_name=r["display_name"],
            description=r.get("description"),
            tags=_parse_jsonb_list(r.get("tags")),
            best_for=_parse_jsonb_list(r.get("best_for")),
            cost_tier=r.get("cost_tier"),
            preview_url=r.get("preview_url"),
            source=r.get("source") or "python_profile",
            sort=r.get("sort") or 0,
        )
        for r in rows
    ]
    return StylePresetsResponse(presets=presets)
