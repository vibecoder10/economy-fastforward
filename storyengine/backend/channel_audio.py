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


def _durable_url(value) -> str:
    url = value.strip() if isinstance(value, str) else ""
    parsed = urlparse(url)
    if not url or parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("fixed music bed requires a durable asset_url")
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
    file_name = raw.get("file_name")
    if not isinstance(file_name, str) or not file_name.strip():
        raise ValueError("fixed music bed requires a file_name")

    try:
        volume = float(raw.get("volume"))
    except (TypeError, ValueError) as exc:
        raise ValueError("fixed music bed volume must be between 0 and 1") from exc
    if not math.isfinite(volume) or not 0.0 <= volume <= 1.0:
        raise ValueError("fixed music bed volume must be between 0 and 1")

    trim_before_seconds = float(raw.get("trim_before_seconds", 0.0))
    return FixedMusicBedConfig(
        asset_url=asset_url,
        file_name=file_name.strip(),
        volume=volume,
        trim_before_seconds=trim_before_seconds,
        loop=bool(raw.get("loop", True)),
    )
