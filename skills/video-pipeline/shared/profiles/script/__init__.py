"""Script Profile loader and registry.

Provides ``load_script_profile()`` — the single entry point for getting
the active editorial voice profile at runtime.

Profile selection order:
1. Explicit ``profile_id`` argument (per-video override from Airtable)
2. ``SCRIPT_PROFILE`` environment variable (per-channel default)
3. Fallback: ``"neutral_v1"`` (universal craft, no built-in identity).
   Power Doctrine is now OPT-IN via SCRIPT_PROFILE=power_doctrine_v2 or an
   explicit profile_id argument.

Usage::

    from script_profiles import load_script_profile

    profile = load_script_profile()                        # env var or default
    profile = load_script_profile("power_doctrine_v1")     # explicit override
"""

from __future__ import annotations

import importlib
import os
from typing import Optional

from .schema import ScriptProfile

# Registry of known profile module names
_PROFILE_MODULES: dict[str, str] = {
    "neutral_v1": "shared.profiles.script.neutral_v1",
    "power_doctrine_v2": "shared.profiles.script.power_doctrine_v2",
    "power_doctrine_v1": "shared.profiles.script.power_doctrine_v1",
}

# Neutral universal craft is the default. Power Doctrine is opt-in
# (SCRIPT_PROFILE=power_doctrine_v2 or an explicit profile_id argument).
DEFAULT_PROFILE_ID = "neutral_v1"

# Module-level cache — one profile loaded per pipeline run
_profile_cache: dict[str, ScriptProfile] = {}


def load_script_profile(profile_id: Optional[str] = None) -> Optional[ScriptProfile]:
    """Load a script profile by ID.

    Args:
        profile_id: Profile to load. If None, reads ``SCRIPT_PROFILE``
            env var, then falls back to ``"neutral_v1"``.

    Returns:
        The loaded ``ScriptProfile``, or ``None`` if loading fails
        (callers should fall back to hardcoded defaults).
    """
    resolved_id = (
        profile_id
        or os.getenv("SCRIPT_PROFILE", "").strip()
        or DEFAULT_PROFILE_ID
    )

    # Check cache first
    if resolved_id in _profile_cache:
        return _profile_cache[resolved_id]

    try:
        module_path = _PROFILE_MODULES.get(resolved_id)
        if not module_path:
            print(f"[script_profiles] Unknown profile: {resolved_id}")
            return None

        mod = importlib.import_module(module_path)
        profile: ScriptProfile = getattr(mod, "PROFILE", None)

        if profile is None:
            print(f"[script_profiles] Module {module_path} has no PROFILE attribute")
            return None

        _profile_cache[resolved_id] = profile
        return profile

    except Exception as exc:
        print(f"[script_profiles] Failed to load profile '{resolved_id}': {exc}")
        return None


def get_profile_or_default(
    profile_id: Optional[str] = None,
) -> Optional[ScriptProfile]:
    """Load a profile, trying default if the requested one fails."""
    profile = load_script_profile(profile_id)
    if profile is not None:
        return profile

    if profile_id and profile_id != DEFAULT_PROFILE_ID:
        return load_script_profile(DEFAULT_PROFILE_ID)

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
    _profile_cache.pop(profile_id, None)


__all__ = [
    "load_script_profile",
    "get_profile_or_default",
    "clear_cache",
    "list_profiles",
    "register_profile",
    "ScriptProfile",
    "DEFAULT_PROFILE_ID",
]
