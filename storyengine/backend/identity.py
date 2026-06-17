"""IdentityContext — the single, channel-specific identity injected into
the generation engine.

StoryEngine historically fused two things in its prompts: the universal
CRAFT (the "engine") and a hardcoded geopolitics IDENTITY (the old
"Power Doctrine"). This module is Phase 1 of separating them: it builds one
neutral, per-tenant identity object — voice + look + framing — that the
prompt-resolution seam injects into either a tenant override OR a neutral
engine template.

Nothing here is geopolitics-specific. The all-empty fallback is deliberately
generic and safe (never blank, never "Power Doctrine"), so a tenant with no
profile still gets coherent, on-brand-agnostic generation.

Precedence mirrors routes/videos.py (suggest_titles): `projects` is the
source of truth the Profile UI edits; `channel_profiles` is the legacy
onboarding fallback.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from database import fetch_one

_logger = logging.getLogger(__name__)

# Neutral, niche-agnostic defaults. These must NEVER be geopolitics / Power
# Doctrine and must never be blank — a keyless tenant still gets coherent text.
_DEFAULT_CHANNEL_NAME = "this channel"
_DEFAULT_NICHE = "general educational content"
_DEFAULT_AUDIENCE = "a general audience"
_DEFAULT_VOICE = "clear, engaging, and natural"
_DEFAULT_VISUAL = "a clean, consistent illustrated style"


@dataclass
class IdentityContext:
    """The swappable IDENTITY of a channel: who it is, who it's for, and how
    it sounds + looks. Filled into the (universal) engine prompts at runtime.
    """
    channel_name: str
    niche: str
    target_audience: str
    voice_style: str
    visual_style: str
    frameworks: List[str] = field(default_factory=list)


def _clean(value) -> str:
    """Return a stripped string, or '' for None / non-strings / blanks.

    Empty strings (and whitespace-only) are treated as MISSING so they fall
    through to the neutral default instead of producing blank-and-broken
    prompts.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        return ""
    return value.strip()


def _first_nonempty(*candidates: object, default: str) -> str:
    """Return the first candidate that is a non-empty string (post-strip),
    else the neutral default."""
    for c in candidates:
        cleaned = _clean(c)
        if cleaned:
            return cleaned
    return default


def _clean_frameworks(value) -> List[str]:
    """Coerce a frameworks value into a list of non-empty strings.

    Accepts a list (the expected shape) and filters out blanks. Anything else
    (None, str, etc.) yields an empty list — be permissive, never raise.
    """
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for item in value:
        cleaned = _clean(item)
        if cleaned:
            out.append(cleaned)
    return out


def build_identity_context_from_rows(
    project: Optional[dict],
    profile: Optional[dict],
    video: Optional[dict],
) -> IdentityContext:
    """Pure builder (no DB). Combine a projects row, a channel_profiles row,
    and a video row into one IdentityContext.

    Precedence (matches routes/videos.py — projects is the source of truth the
    Profile UI edits; channel_profiles is the legacy fallback):
      - channel_name:    project.name  -> profile.channel_name     -> "this channel"
      - niche:           project.niche -> profile.niche            -> "general educational content"
      - target_audience: profile.target_audience                  -> "a general audience"
      - voice_style:     profile.style_description                 -> "clear, engaging, and natural"
      - visual_style:    video.image_style_override -> profile.style_description
                                                       -> "a clean, consistent illustrated style"
      - frameworks:      profile.frameworks (list)                 -> []

    Empty strings are treated as missing. The all-empty result is safe and
    generic, never geopolitics, never blank.
    """
    project = project or {}
    profile = profile or {}
    video = video or {}

    channel_name = _first_nonempty(
        project.get("name"),
        profile.get("channel_name"),
        default=_DEFAULT_CHANNEL_NAME,
    )
    niche = _first_nonempty(
        project.get("niche"),
        profile.get("niche"),
        default=_DEFAULT_NICHE,
    )
    target_audience = _first_nonempty(
        profile.get("target_audience"),
        default=_DEFAULT_AUDIENCE,
    )
    voice_style = _first_nonempty(
        profile.get("style_description"),
        default=_DEFAULT_VOICE,
    )
    visual_style = _first_nonempty(
        video.get("image_style_override"),
        profile.get("style_description"),
        default=_DEFAULT_VISUAL,
    )
    frameworks = _clean_frameworks(profile.get("frameworks"))

    return IdentityContext(
        channel_name=channel_name,
        niche=niche,
        target_audience=target_audience,
        voice_style=voice_style,
        visual_style=visual_style,
        frameworks=frameworks,
    )


async def build_identity_context(
    tenant_id: str,
    video: Optional[dict],
) -> IdentityContext:
    """Fetch the tenant's projects + channel_profiles rows and build the
    IdentityContext. Defensive: any failure yields the neutral fallback so
    generation never crashes on identity resolution.
    """
    project = None
    profile = None
    try:
        project = await fetch_one(
            "SELECT name, niche FROM projects WHERE tenant_id = $1 LIMIT 1",
            tenant_id,
        )
        profile = await fetch_one(
            "SELECT channel_name, niche, target_audience, style_description, frameworks "
            "FROM channel_profiles WHERE tenant_id = $1",
            tenant_id,
        )
    except Exception as e:  # noqa: BLE001 — never let identity lookup break a run
        _logger.warning("build_identity_context: DB lookup failed, using neutral fallback: %s", e)
        project = None
        profile = None

    return build_identity_context_from_rows(project=project, profile=profile, video=video)
