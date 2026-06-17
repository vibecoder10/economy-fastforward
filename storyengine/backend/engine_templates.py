"""Neutral engine-template scaffolds + SAFE identity substitution.

Phase 1 plumbing. The CRAFT (the "engine") lives in these templates; the
IDENTITY (voice + look + framing) is injected via safe_fill. These templates
are intentionally SHORT, NEUTRAL placeholders — Phase 2/3 will replace them
with the real, battle-tested craft. They must stay niche-agnostic: no
geopolitics, no "Power Doctrine", no "Economy FastForward".

The substitution is the load-bearing part. Real prompts in this repo carry
foreign braces — single placeholders like {HEADLINE}/{TOPIC} and JSON
fragments like {{x}} (see prompt_defaults.py). A plain str.format() would
raise KeyError or mangle those. safe_fill therefore replaces ONLY the known
identity placeholders and leaves every other brace byte-for-byte intact.
"""
from __future__ import annotations

import re
from typing import Dict

from identity import IdentityContext

# The identity slots the engine templates (and tenant overrides) may reference.
# `frameworks` is a list field — it is comma-joined when substituted.
_IDENTITY_KEYS = (
    "channel_name",
    "niche",
    "target_audience",
    "voice_style",
    "visual_style",
    "frameworks",
)

# Matches ONLY a single-brace placeholder whose name is one of the identity
# keys, e.g. {niche}. It will NOT match {HEADLINE} (unknown key) nor the
# inner {x} of a doubled {{x}} (that name isn't an identity key), so all
# foreign braces survive verbatim.
_PLACEHOLDER_RE = re.compile(r"\{(" + "|".join(_IDENTITY_KEYS) + r")\}")


# Neutral craft skeletons keyed by prompt_key. Each references the identity
# slots so the injected channel becomes the subject. PLACEHOLDER content —
# the real craft arrives in Phase 2/3.
ENGINE_TEMPLATES: Dict[str, str] = {
    "script": (
        "You write scripts for {channel_name}, a {niche} channel made for "
        "{target_audience}.\n"
        "Write in a {voice_style} voice. Open with a hook, deliver clear value, "
        "and close with a satisfying payoff.\n"
        "Stay focused on the {niche} topic and keep it useful for "
        "{target_audience}.\n"
        "Apply the channel's frameworks where they help: {frameworks}."
    ),
    "research": (
        "You research material for {channel_name}, a {niche} channel for "
        "{target_audience}.\n"
        "Gather accurate, well-sourced facts and angles relevant to the "
        "{niche} topic at hand.\n"
        "Surface what {target_audience} would find surprising, useful, or "
        "worth sharing, in a {voice_style} register."
    ),
    "thumbnail": (
        "You design thumbnail concepts for {channel_name}, a {niche} channel "
        "for {target_audience}.\n"
        "Render ideas in {visual_style}, with a single clear focal point and "
        "high readability at small sizes.\n"
        "The concept should signal the {niche} topic at a glance and feel "
        "{voice_style}."
    ),
    "video_motion": (
        "You direct the motion and pacing for {channel_name}, a {niche} "
        "channel for {target_audience}.\n"
        "Keep camera and animation choices consistent with a {visual_style} "
        "look and a {voice_style} feel.\n"
        "Use motion to support comprehension of the {niche} content, not to "
        "distract from it."
    ),
    "title": (
        "You write titles for {channel_name}, a {niche} channel for "
        "{target_audience}.\n"
        "Write {voice_style}, specific, click-worthy titles that honestly "
        "reflect the {niche} content.\n"
        "Avoid clickbait that {target_audience} would feel misled by."
    ),
}


def safe_fill(text: str, identity: IdentityContext) -> str:
    """Fill ONLY the known identity placeholders in `text`, leaving every
    other brace untouched.

    - {channel_name} {niche} {target_audience} {voice_style} {visual_style}
      are replaced with the identity values.
    - {frameworks} is replaced with the comma-joined frameworks list.
    - Any other brace — {HEADLINE}, {TOPIC}, or doubled {{x}} — is preserved
      verbatim. This never raises.
    """
    if not text:
        return text

    values = {
        "channel_name": identity.channel_name,
        "niche": identity.niche,
        "target_audience": identity.target_audience,
        "voice_style": identity.voice_style,
        "visual_style": identity.visual_style,
        "frameworks": ", ".join(identity.frameworks or []),
    }

    def _sub(match: "re.Match") -> str:
        key = match.group(1)
        return values.get(key, match.group(0))

    return _PLACEHOLDER_RE.sub(_sub, text)


def render(key: str, identity: IdentityContext) -> str:
    """Return the identity-filled neutral template for `key`.

    Unknown keys (e.g. sound_curation / sound_generation, which have no engine
    template) return "" — never raise.
    """
    template = ENGINE_TEMPLATES.get(key)
    if not template:
        return ""
    return safe_fill(template, identity)
