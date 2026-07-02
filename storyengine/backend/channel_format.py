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

logger = logging.getLogger(__name__)

FORMAT_FIELDS = ("style", "motion", "segmentation", "on_camera")


def _identity(row) -> dict:
    ci = (row or {}).get("channel_identity")
    if isinstance(ci, str):
        try:
            ci = json.loads(ci)
        except (ValueError, TypeError):
            ci = {}
    return ci if isinstance(ci, dict) else {}


async def get_channel_format(tenant_id) -> tuple[dict, bool]:
    """(visual_format, locked)."""
    row = await fetch_one(
        "SELECT channel_identity FROM channel_profiles WHERE tenant_id = $1", tenant_id
    )
    ci = _identity(row)
    fmt = ci.get("visual_format")
    return (fmt if isinstance(fmt, dict) else {}), bool(ci.get("format_locked"))


async def set_channel_format(tenant_id, fields: dict[str, Any]) -> dict:
    """Merge the given format fields into visual_format and lock it. Returns
    the merged visual_format."""
    fmt, _ = await get_channel_format(tenant_id)
    for k in FORMAT_FIELDS:
        if fields.get(k) is not None and str(fields[k]).strip():
            fmt[k] = str(fields[k]).strip()[:200]
    payload = json.dumps({"visual_format": fmt, "format_locked": True})
    await execute(
        """INSERT INTO channel_profiles (tenant_id, channel_identity)
           VALUES ($1, $2::jsonb)
           ON CONFLICT (tenant_id) DO UPDATE SET channel_identity =
               COALESCE(channel_profiles.channel_identity, '{}'::jsonb) || $2::jsonb,
               updated_at = now()""",
        tenant_id, payload,
    )
    return fmt


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


async def apply_format_defaults(tenant_id, video_id: str) -> bool:
    """Default a fresh video's visual_style from the LOCKED channel format when
    the creator didn't choose one. Fail-soft; never blocks creation."""
    try:
        fmt, locked = await get_channel_format(tenant_id)
        if not locked:
            return False
        preset = style_preset_for_format(fmt)
        if not preset:
            return False
        await execute(
            """UPDATE videos SET visual_style = $1, updated_at = now()
               WHERE id = $2 AND tenant_id = $3
                 AND visual_style IS NULL AND image_style_override IS NULL""",
            preset, video_id, tenant_id,
        )
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("channel_format: defaults failed for %s: %s", video_id, e)
        return False
