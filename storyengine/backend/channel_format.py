"""Channel format lock ("we make animated ESL dialogue videos — lock that in").

The channel's KIND of video lives in channel_profiles.channel_identity.
visual_format ({style, motion, segmentation, on_camera}, written by the
identity builder or set/locked from chat). This module reads it, merges chat
edits into it, and turns it into creation defaults — so a bare-title video
(chat, queue, autopilot) comes out in the channel's format instead of a
generic one. static_docu.py consumes the same field for held-image channels.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from database import execute, fetch_one
# Provenance envelope (checklist C40) — read-modify-write through this so an
# identity_builder rebuild (or another writer) can never clobber this
# module's visual_format/format_locked, and the edit itself gets a
# _sources/_history stamp.
from channel_dna_meta import coerce_identity, stamp_identity_write

logger = logging.getLogger(__name__)

FORMAT_FIELDS = ("style", "motion", "segmentation", "on_camera")


def _identity(row) -> dict:
    return coerce_identity((row or {}).get("channel_identity"))


async def get_channel_format(tenant_id) -> tuple[dict, bool]:
    """(visual_format, locked)."""
    row = await fetch_one(
        "SELECT channel_identity FROM channel_profiles WHERE tenant_id = $1", tenant_id
    )
    ci = _identity(row)
    fmt = ci.get("visual_format")
    return (fmt if isinstance(fmt, dict) else {}), bool(ci.get("format_locked"))


async def get_channel_tone(tenant_id) -> Optional[str]:
    """LAW 3 (video f00ea79a scene 1): a single tone hint that reaches every
    delivery instruction (motion-writer + speaking_prompt), read from the
    SAME field identity_builder.build_channel_identity already writes —
    channel_identity.voice_tone ("short phrase for the narration voice").
    No new field invented: a channel that hasn't been learned yet (or was
    learned before voice_tone existed) simply has none, and this no-ops —
    callers must never invent a tone when this returns None.

    Best-effort like the rest of this module's reads: a tone hint is pure
    enrichment, so a DB hiccup here must never break clip generation — it
    just no-ops the same as "no tone set" (mirrors _write_motion_prompts'
    own "leaves video_prompt NULL on failure" contract just above)."""
    try:
        row = await fetch_one(
            "SELECT channel_identity FROM channel_profiles WHERE tenant_id = $1", tenant_id
        )
    except Exception as e:  # noqa: BLE001 — enrichment lookup must fail soft
        logger.warning("get_channel_tone: lookup failed for tenant %s: %s", tenant_id, e)
        return None
    ci = _identity(row)
    tone = ci.get("voice_tone")
    if isinstance(tone, str) and tone.strip():
        return tone.strip()[:200]
    logger.info("get_channel_tone: no voice_tone set for tenant %s — no-op", tenant_id)
    return None


async def set_channel_format(tenant_id, fields: dict[str, Any]) -> dict:
    """Merge the given format fields into visual_format and lock it. Returns
    the merged visual_format."""
    row = await fetch_one(
        "SELECT channel_identity FROM channel_profiles WHERE tenant_id = $1", tenant_id
    )
    current = _identity(row)
    fmt = dict(current.get("visual_format") or {})
    for k in FORMAT_FIELDS:
        if fields.get(k) is not None and str(fields[k]).strip():
            fmt[k] = str(fields[k]).strip()[:200]
    merged = stamp_identity_write(
        current, {"visual_format": fmt, "format_locked": True}, learner="channel_format"
    )
    await execute(
        """INSERT INTO channel_profiles (tenant_id, channel_identity)
           VALUES ($1, $2::jsonb)
           ON CONFLICT (tenant_id) DO UPDATE SET channel_identity = $2::jsonb,
               updated_at = now()""",
        tenant_id, json.dumps(merged),
    )
    return fmt


# The six "style description" ids — a free-text AESTHETIC OVERLAY axis
# (image_style_override / visual_style_label), completely separate from the
# 5-row `style_presets` DB table's STRUCTURAL ENGINE axis (holographic_hud,
# clay_mannequin, ...; see routes/style_presets.py + docs/reports/2026-07-17-
# storyengine-agent-audit-findings.md §S9-5 for the full axis split).
#
# Checklist §C21b: formerly duplicated in TWO places — producer_prompt.
# VISUAL_PRESETS (backend) and frontend/src/lib/visual-presets.ts (frontend);
# both deleted. This dict is now the ONE source for:
#   - routes/chat.py's reference-video vision classifier
#     (_detect_reference_style_preset / _annotate_style_recommendation) —
#     answers "what animation MEDIUM does this reference look like", a
#     different question than "which style_presets ENGINE renders the scenes"
#     with no valid mapping onto that other axis;
#   - routes/chat.py's _spec_to_create_request (id -> image_style_override /
#     visual_style_label mapping for the chat LOOK card's pick);
#   - routes/projects.py's _channel_style_dna (cast-generation look sentence);
#   - GET /api/style-descriptions (routes/style_descriptions.py), read by
#     both frontend doors (New Video's "Style description" grid + the chat
#     LOOK card) instead of either one hardcoding its own copy.
STYLE_DESCRIPTIONS: dict[str, dict[str, str]] = {
    # pixar_3d's look rewritten 2026-07-21: the old wording ("subsurface skin,
    # shallow depth of field") read as photoreal render cues — on video
    # cd5d2883 it let nano-banana-2 storyboards drift fully live-action. The
    # look now names the cartoon medium for every element and bans
    # photorealism outright (the wording proven on El Mercado 65a8021e, whose
    # boards held the 3D-cartoon style on every panel).
    "pixar_3d":   {"label": "3D Animated", "look": "Soft 3D animated cartoon CG, stylized cartoon characters with warm expressive faces, rounded forms, clean bright saturated colors, smooth cartoon shading, warm cinematic light. Environments, props and food are stylized 3D cartoon too. Fully animated 3D cartoon, NOT photorealistic, NOT live-action, NOT a real photograph"},
    "flat_2d":    {"label": "2D flat",    "look": "Clean 2D flat vector animation, bold flat colors, simple shapes, crisp outlines, minimal shading"},
    "realistic":  {"label": "Realistic",  "look": "Photorealistic cinematic photography, natural lighting, real textures, shallow depth of field"},
    "anime":      {"label": "Anime",      "look": "Modern anime cel-shaded illustration, expressive faces, clean linework, soft gradient shading"},
    "watercolor": {"label": "Watercolor", "look": "Warm hand-painted watercolor storybook art, soft edges, textured paper, gentle palette"},
    "comic":      {"label": "Comic",      "look": "Bold graphic-novel illustration, inked outlines, halftone shading, dynamic high-contrast color"},
}


def look_for_visual_style(value: Optional[str]) -> Optional[str]:
    """Resolve a stored videos.visual_style that EXACTLY names one of the six
    preset ids above (what apply_format_defaults writes for format-locked
    channels) or a preset's display label onto that preset's full look
    sentence. Freeform prose returns None and must pass through untouched:
    no fuzzy matching here, unlike style_preset_for_format — a creator's own
    wording always beats a canned sentence, and a contains-match ("cinematic
    noir" → realistic) would silently overwrite it (S6-C follow-up)."""
    v = (value or "").strip().lower()
    if not v:
        return None
    entry = STYLE_DESCRIPTIONS.get(v.replace(" ", "_").replace("-", "_"))
    if entry:
        return entry["look"]
    for meta in STYLE_DESCRIPTIONS.values():
        if v == meta["label"].lower():
            return meta["look"]
    return None


def style_preset_for_format(fmt: dict) -> Optional[str]:
    """Map the format's free-text style onto a renderable visual preset id
    (the same six the chat's style card offers). None when unmappable."""
    s = (fmt.get("style") or "").lower()
    if not s:
        return None
    if "anime" in s:
        return "anime"
    if "watercolor" in s or "storybook" in s:
        return "watercolor"
    if "comic" in s:
        return "comic"
    if "2d" in s or "flat" in s:
        return "flat_2d"
    if "3d" in s or "pixar" in s or "animat" in s or "cartoon" in s:
        return "pixar_3d"
    if "live" in s or "real" in s or "footage" in s or "cinematic" in s:
        return "realistic"
    return None


# C13b (checklist §C13b): the six canonical preset ids split cleanly into
# "realistic" (one preset, photoreal/live-action) and everything else
# (illustrated/stylized looks) — no third bucket exists in this vocabulary.
_ANIMATED_PRESETS = {"pixar_3d", "flat_2d", "anime", "watercolor", "comic"}


def render_style_for_preset(preset: Optional[str]) -> Optional[str]:
    """Map one of the six canonical visual-style preset ids (the same ones
    style_preset_for_format/routes.videos._normalize_style_preset resolve
    to) onto a videos.render_style value: 'realistic' for the literal
    'realistic' preset, 'animated' for the other five. None only when
    ``preset`` itself is None/unrecognized — auto-derivation must never
    guess past an ambiguous preset (checklist §C13b: "if ambiguous, don't
    derive — leave NULL")."""
    if preset == "realistic":
        return "realistic"
    if preset in _ANIMATED_PRESETS:
        return "animated"
    return None


async def apply_format_defaults(tenant_id, video_id: str) -> bool:
    """Default a fresh video's visual_style from the LOCKED channel format when
    the creator didn't choose one. Fail-soft; never blocks creation.

    C13b: also auto-derives render_style from the SAME resolved preset —
    the channel format's style is unambiguous by construction here (style_
    preset_for_format already returned early if it wasn't), so this is a
    safe, no-new-inference reuse of that result, not a second guess."""
    try:
        fmt, locked = await get_channel_format(tenant_id)
        if not locked:
            return False
        preset = style_preset_for_format(fmt)
        if not preset:
            return False
        await execute(
            """UPDATE videos SET visual_style = $1,
                   render_style = COALESCE(render_style, $2), updated_at = now()
               WHERE id = $3 AND tenant_id = $4
                 AND visual_style IS NULL AND image_style_override IS NULL""",
            preset, render_style_for_preset(preset), video_id, tenant_id,
        )
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("channel_format: defaults failed for %s: %s", video_id, e)
        return False
