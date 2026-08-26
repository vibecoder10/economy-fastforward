"""Channel-level audio configuration read from ``channel_identity``."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from urllib.parse import urlparse

from database import fetch_one


@dataclass(frozen=True)
class FixedMusicBedConfig:
    asset_url: str
    file_name: str
    volume: float
    trim_before_seconds: float = 0.0
    loop: bool = True


def _parse_identity(raw) -> dict:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return {}
    return raw if isinstance(raw, dict) else {}


def _durable_url(value) -> str | None:
    url = value.strip() if isinstance(value, str) else ""
    parsed = urlparse(url)
    if not url or parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return url


async def get_fixed_music_bed_config(tenant_id: str) -> FixedMusicBedConfig | None:
    row = await fetch_one(
        "SELECT channel_identity FROM channel_profiles WHERE tenant_id = $1",
        tenant_id,
    )
    identity = _parse_identity((row or {}).get("channel_identity"))
    raw = identity.get("music_bed")
    if not isinstance(raw, dict) or raw.get("mode") != "fixed_full_video":
        return None

    asset_url = _durable_url(raw.get("asset_url"))
    file_name_raw = raw.get("file_name")
    file_name = file_name_raw.strip() if isinstance(file_name_raw, str) else ""
    if (
        asset_url is None
        or not file_name
        or file_name in {".", ".."}
        or "/" in file_name
        or "\\" in file_name
    ):
        return None

    volume_raw = raw.get("volume")
    if isinstance(volume_raw, bool) or not isinstance(volume_raw, (int, float)):
        return None
    volume = float(volume_raw)
    if not math.isfinite(volume) or not 0.0 <= volume <= 1.0:
        return None

    trim_raw = raw.get("trim_before_seconds", 0.0)
    if isinstance(trim_raw, bool) or not isinstance(trim_raw, (int, float)):
        return None
    trim_before_seconds = float(trim_raw)
    loop = raw.get("loop", True)
    if (
        not math.isfinite(trim_before_seconds)
        or trim_before_seconds < 0.0
        or not isinstance(loop, bool)
    ):
        return None
    return FixedMusicBedConfig(
        asset_url=asset_url,
        file_name=file_name,
        volume=volume,
        trim_before_seconds=trim_before_seconds,
        loop=loop,
    )
