"""Public production-style catalog and per-video snapshot helpers.

``style_presets`` and ``visual_styles`` describe how generated pictures look.
This module owns the higher-level production shape: render mode, editorial
profile, coverage density, animation, language, dubbing, segmentation, camera
grammar, quality laws, the structural visual profile, and the future
image-source choice.

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
        "visual_profile",
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


def runtime_values(profile: dict[str, Any]) -> dict[str, str]:
    """Translate named profile dimensions onto the existing runtime seams.

    This deliberately branches on dimension values, not public profile IDs.
    Milestone 2's Custom Film composer can therefore reuse the same mapping
    for a validated per-section contract without teaching the runtime about
    another branded preset.
    """
    normalized = normalize_profile_row(profile)
    if normalized is None:
        raise ValueError("Invalid production-style profile")
    knobs = normalized["knobs"]
    render_mode = str(knobs["render_mode"] or "").strip()
    if render_mode not in {"coverage", "static_docu"}:
        raise ValueError(f"Unsupported production render mode: {render_mode!r}")
    script_profile = str(knobs["script_profile"] or "").strip()
    if not script_profile:
        raise ValueError("Production style has no script profile")
    visual_profile = str(knobs["visual_profile"] or "").strip()
    if not visual_profile:
        raise ValueError("Production style has no visual profile")

    animation = knobs.get("animation") if isinstance(knobs.get("animation"), dict) else {}
    dubbing = knobs.get("dubbing") if isinstance(knobs.get("dubbing"), dict) else {}
    segmentation = (
        knobs.get("segmentation")
        if isinstance(knobs.get("segmentation"), dict)
        else {}
    )
    # Existing audio modes:
    # - voice_over: narrator/per-segment ElevenLabs audio, including the
    #   speech-to-speech voice lock used by bilingual character animation.
    # - grok_native: performed single-language dialogue stays in the clips.
    dialogue_audio = "voice_over"
    if (
        bool(animation.get("enabled"))
        and str(segmentation.get("mode") or "") == "speaker_turn"
        and str(dubbing.get("mode") or "") == "none"
    ):
        dialogue_audio = "grok_native"
    return {
        "render_mode": render_mode,
        "script_profile": script_profile,
        "visual_profile": visual_profile,
        "dialogue_audio": dialogue_audio,
    }


def merge_script_guidance(
    existing: Optional[str],
    profile: dict[str, Any],
) -> Optional[str]:
    """Append the script-facing parts of a production profile.

    The snapshot remains the machine source of truth; this text is the seam
    the existing script engine already consumes. It names production
    behavior, never the private channel that originally proved the format.
    """
    normalized = normalize_profile_row(profile)
    if normalized is None:
        raise ValueError("Invalid production-style profile")
    knobs = normalized["knobs"]
    language = knobs.get("language") if isinstance(knobs.get("language"), dict) else {}
    segmentation = (
        knobs.get("segmentation")
        if isinstance(knobs.get("segmentation"), dict)
        else {}
    )
    density = (
        knobs.get("image_density")
        if isinstance(knobs.get("image_density"), dict)
        else {}
    )
    directives: list[str] = []
    language_mode = str(language.get("mode") or "")
    if language_mode == "bilingual":
        directives.append(
            "Write this as performed character dialogue that naturally teaches or "
            "contrasts two languages. Honor any language pair in the topic or creator "
            "guidance; when none is given, use English and Spanish. Keep translations "
            "clear in context instead of repeating every sentence mechanically."
        )
    elif language_mode == "simple_single_language":
        directives.append(
            "Write this as performed character dialogue in one clear target language. "
            "Use short, concrete, beginner-friendly sentences and make meaning obvious "
            "from the action; do not add a second-language translation track."
        )

    segmentation_mode = str(segmentation.get("mode") or "")
    if segmentation_mode == "item":
        directives.append(
            "Organize the narration item by item, with one clearly identified subject "
            "per section and only source-grounded facts that its still images can prove."
        )
    elif segmentation_mode == "visual_cue" or str(density.get("mode") or "") == "visual_cue":
        directives.append(
            "Write concrete investigative narration with one dominant visual idea per "
            "sentence or meaningful clause so the picture plan can illustrate each cue."
        )

    if not directives:
        return (existing or "").strip() or None
    block = "PRODUCTION STYLE:\n- " + "\n- ".join(directives)
    return "\n\n".join(part for part in ((existing or "").strip(), block) if part)
