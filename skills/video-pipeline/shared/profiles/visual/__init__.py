"""Visual Profile loader and registry.

Provides ``load_profile()`` — the single entry point for getting the
active visual identity profile at runtime.

Profile selection order:
1. Explicit ``profile_id`` argument (per-video override from Airtable)
2. ``VISUAL_PROFILE`` environment variable (per-channel default)
3. Fallback: ``"neutral_v1"`` (style-agnostic default; the channel's look is
   injected at build time). ``cinematic_illustration`` (the Power Doctrine
   look) is now an opt-in preset, not the default.

Usage::

    from shared.profiles.visual import load_profile

    profile = load_profile()              # uses env var or default
    profile = load_profile("clay_mannequin")  # explicit override
"""

from __future__ import annotations

import importlib
import os
from typing import Optional

from .schema import VisualProfile

# Registry of known profile module names
_PROFILE_MODULES: dict[str, str] = {
    "neutral_v1": "shared.profiles.visual.neutral_v1",
    "holographic_hud": "shared.profiles.visual.holographic_hud",
    "cinematic_dossier": "shared.profiles.visual.cinematic_dossier",
    "clay_mannequin": "shared.profiles.visual.clay_mannequin",
    "cinematic_illustration": "shared.profiles.visual.cinematic_illustration",
    # Legacy alias — old Airtable records may still have this value
    "mannequin_storytelling": "shared.profiles.visual.cinematic_illustration",
}

# Style-agnostic default. The Power Doctrine look (cinematic_illustration) is
# now an opt-in preset; an unset channel gets the neutral engine + its own look.
DEFAULT_PROFILE_ID = "neutral_v1"

# Module-level cache — one profile loaded per pipeline run
_profile_cache: dict[str, VisualProfile] = {}


def load_profile(profile_id: Optional[str] = None) -> Optional[VisualProfile]:
    """Load a visual profile by ID.

    Args:
        profile_id: Profile to load. If None, reads ``VISUAL_PROFILE``
            env var, then falls back to ``DEFAULT_PROFILE_ID`` (``"neutral_v1"``).

    Returns:
        The loaded ``VisualProfile``, or ``None`` if loading fails
        (callers should fall back to hardcoded defaults).
    """
    resolved_id = (
        profile_id
        or os.getenv("VISUAL_PROFILE", "").strip()
        or DEFAULT_PROFILE_ID
    )

    # Check cache first
    if resolved_id in _profile_cache:
        return _profile_cache[resolved_id]

    try:
        module_path = _PROFILE_MODULES.get(resolved_id)
        if not module_path:
            print(f"[visual_profiles] Unknown profile: {resolved_id}")
            return None

        mod = importlib.import_module(module_path)
        profile: VisualProfile = getattr(mod, "PROFILE", None)

        if profile is None:
            print(f"[visual_profiles] Module {module_path} has no PROFILE attribute")
            return None

        _profile_cache[resolved_id] = profile
        return profile

    except Exception as exc:
        print(f"[visual_profiles] Failed to load profile '{resolved_id}': {exc}")
        return None


def get_profile_or_default(profile_id: Optional[str] = None) -> Optional[VisualProfile]:
    """Load a profile, trying default if the requested one fails.

    Unlike ``load_profile()``, this tries the default profile as a
    secondary fallback when a specific profile_id fails to load.
    """
    profile = load_profile(profile_id)
    if profile is not None:
        return profile

    # If a specific profile was requested and failed, try default
    if profile_id and profile_id != DEFAULT_PROFILE_ID:
        return load_profile(DEFAULT_PROFILE_ID)

    return None


def clear_cache() -> None:
    """Clear the profile cache (useful for testing)."""
    _profile_cache.clear()


def list_profiles() -> list[str]:
    """Return all registered profile IDs."""
    return list(_PROFILE_MODULES.keys())


def register_profile(profile_id: str, module_path: str) -> None:
    """Register a new profile module at runtime."""
    _PROFILE_MODULES[profile_id] = module_path
    # Invalidate cache for this profile
    _profile_cache.pop(profile_id, None)


__all__ = [
    "load_profile",
    "get_profile_or_default",
    "clear_cache",
    "list_profiles",
    "register_profile",
    "VisualProfile",
    "DEFAULT_PROFILE_ID",
]
