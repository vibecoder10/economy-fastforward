"""Channel-level fixed music-bed contract tests."""

import importlib
import importlib.util
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _channel_audio():
    spec = importlib.util.find_spec("channel_audio")
    assert spec is not None, "channel_audio module must define the fixed music-bed contract"
    module = importlib.import_module("channel_audio")
    assert hasattr(module, "get_fixed_music_bed_config")
    assert hasattr(module, "FixedMusicBedConfig")
    return module


def _identity(**music_bed_overrides):
    music_bed = {
        "mode": "fixed_full_video",
        "asset_url": (
            "https://storage.test/dvsu-channel/channel-assets/"
            "light_music-lonely-piano-189659.mp3"
        ),
        "file_name": "light_music-lonely-piano-189659.mp3",
        "volume": 0.018,
        "trim_before_seconds": 0,
        "loop": True,
    }
    music_bed.update(music_bed_overrides)
    return {"music_bed": music_bed}


@pytest.mark.asyncio
async def test_reads_fixed_full_video_music_bed_from_channel_identity(monkeypatch):
    channel_audio = _channel_audio()

    async def fake_fetch_one(query, *args):
        assert "channel_profiles" in query
        assert args == ("tenant-dvsu",)
        return {"channel_identity": json.dumps(_identity())}

    monkeypatch.setattr(channel_audio, "fetch_one", fake_fetch_one)

    result = await channel_audio.get_fixed_music_bed_config("tenant-dvsu")

    assert result == channel_audio.FixedMusicBedConfig(
        asset_url=(
            "https://storage.test/dvsu-channel/channel-assets/"
            "light_music-lonely-piano-189659.mp3"
        ),
        file_name="light_music-lonely-piano-189659.mp3",
        volume=0.018,
        trim_before_seconds=0.0,
        loop=True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "channel_identity",
    [
        None,
        {},
        {"music_bed": {"mode": "per_act"}},
        "not-json",
    ],
)
async def test_returns_none_without_a_fixed_music_bed(monkeypatch, channel_identity):
    channel_audio = _channel_audio()

    async def fake_fetch_one(query, *args):
        return {"channel_identity": channel_identity}

    monkeypatch.setattr(channel_audio, "fetch_one", fake_fetch_one)

    assert await channel_audio.get_fixed_music_bed_config("tenant-legacy") is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"asset_url": ""},
        {"file_name": ""},
        {"volume": -0.001},
        {"volume": 1.001},
    ],
)
async def test_rejects_incomplete_or_out_of_range_fixed_music_bed(monkeypatch, overrides):
    channel_audio = _channel_audio()

    async def fake_fetch_one(query, *args):
        return {"channel_identity": _identity(**overrides)}

    monkeypatch.setattr(channel_audio, "fetch_one", fake_fetch_one)

    with pytest.raises(ValueError):
        await channel_audio.get_fixed_music_bed_config("tenant-dvsu")
