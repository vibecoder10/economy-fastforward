"""Public production-style catalog and per-video snapshot helpers.

``style_presets`` and ``visual_styles`` describe how generated pictures look.
This module owns the higher-level production shape: render mode, editorial
profile, coverage density, animation, language, dubbing, segmentation, camera
grammar, quality laws, and the future image-source choice.

The catalog is global and public to authenticated tenants. A selected row is
snapshotted onto the video at creation so later catalog edits affect new videos
without silently changing an in-flight or completed production.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Optional

from database import fetch_all, fetch_one


PUBLIC_PRODUCTION_STYLE_IDS = frozenset(
    {
        "bilingual_character_animation",
        "simple_language_animation",
        "photo_documentary",
        "animated_investigative_documentary",
    }
)

REQUIRED_KNOB_KEYS = frozenset(
    {
        "render_mode",
        "script_profile",
        "image_density",
        "animation",
        "language",
        "dubbing",
        "segmentation",
        "camera",
        "quality_laws",
        "image_source",
    }
)


def parse_jsonb_object(value: Any) -> dict[str, Any]:
    """Normalize asyncpg JSONB values while failing closed to an empty object."""
    if isinstance(value, dict):
        return copy.deepcopy(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
        return copy.deepcopy(parsed) if isinstance(parsed, dict) else {}
    return {}


def normalize_profile_row(row: Any) -> Optional[dict[str, Any]]:
    """Return one validated public catalog row, or ``None`` when malformed."""
    if not isinstance(row, dict):
        try:
            row = dict(row)
        except (TypeError, ValueError):
            return None
    style_id = str(row.get("id") or "").strip()
    if style_id not in PUBLIC_PRODUCTION_STYLE_IDS:
        return None
    knobs = parse_jsonb_object(row.get("knobs"))
    if not REQUIRED_KNOB_KEYS.issubset(knobs):
        return None
    estimate = parse_jsonb_object(row.get("estimate"))
    return {
        "id": style_id,
        "version": int(row.get("version") or 1),
        "label": str(row.get("label") or "").strip(),
        "description": str(row.get("description") or "").strip(),
        "knobs": knobs,
        "estimate": estimate,
        "requires_byok": bool(row.get("requires_byok", True)),
        "sort": int(row.get("sort") or 0),
    }


async def list_public_profiles() -> list[dict[str, Any]]:
    """List active public profiles in their stable creation-card order."""
    rows = await fetch_all(
        """SELECT id, version, label, description, knobs, estimate,
                  requires_byok, sort
           FROM production_style_profiles
           WHERE public = true AND active = true
           ORDER BY sort, id"""
    )
    profiles = [normalize_profile_row(row) for row in rows]
    return [profile for profile in profiles if profile is not None]


async def get_public_profile(style_id: str) -> Optional[dict[str, Any]]:
    """Resolve one active public profile without consulting tenant-owned rows."""
    normalized_id = str(style_id or "").strip()
    if normalized_id not in PUBLIC_PRODUCTION_STYLE_IDS:
        return None
    row = await fetch_one(
        """SELECT id, version, label, description, knobs, estimate,
                  requires_byok, sort
           FROM production_style_profiles
           WHERE id = $1 AND public = true AND active = true""",
        normalized_id,
    )
    return normalize_profile_row(row) if row else None


def snapshot_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Create the immutable JSONB payload persisted on a video."""
    normalized = normalize_profile_row(profile)
    if normalized is None:
        raise ValueError("Invalid production-style profile")
    if not normalized["requires_byok"]:
        raise ValueError("Public production styles must require BYOK")
    return copy.deepcopy(normalized)
