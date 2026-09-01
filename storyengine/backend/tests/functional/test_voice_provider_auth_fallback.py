"""A stale direct ElevenLabs key must not block a tenant's valid Kie voice path."""

import os
import sys
from pathlib import Path

import httpx
import pytest


_REPO_ROOT = Path(__file__).resolve().parents[4]
_PIPELINE_ROOT = _REPO_ROOT / "skills" / "video-pipeline"
if str(_PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_ROOT))

from shared.clients.elevenlabs_client import ElevenLabsClient  # noqa: E402


@pytest.mark.asyncio
async def test_direct_auth_rejection_falls_back_to_configured_kie(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "stale-direct-key")
    monkeypatch.setenv("KIE_AI_API_KEY", "working-kie-key")
    client = ElevenLabsClient(voice_id="direct-only-voice")

    request = httpx.Request("POST", "https://api.elevenlabs.io/v1/text-to-speech/voice")
    response = httpx.Response(401, request=request)

    class RejectingHttpClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return response

    seen = {}

    async def fake_kie(text, voice, stability, similarity_boost, **kwargs):
        seen.update(text=text, voice=voice, key=client.api_key, kwargs=kwargs)
        return {"audio_content": b"voice", "content_type": "audio/mpeg"}

    monkeypatch.setattr(httpx, "AsyncClient", RejectingHttpClient)
    monkeypatch.setattr(client, "_generate_via_kie", fake_kie)

    result = await client.generate_voice("hello")

    assert result["audio_content"] == b"voice"
    assert client._kie_mode is True
    assert seen["key"] == "working-kie-key"
    assert seen["voice"] == client.KIE_FALLBACK_VOICE


@pytest.mark.asyncio
async def test_direct_auth_rejection_without_kie_still_fails(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "stale-direct-key")
    monkeypatch.delenv("KIE_AI_API_KEY", raising=False)
    client = ElevenLabsClient(voice_id="voice")

    request = httpx.Request("POST", "https://api.elevenlabs.io/v1/text-to-speech/voice")
    response = httpx.Response(401, request=request)

    class RejectingHttpClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return response

    monkeypatch.setattr(httpx, "AsyncClient", RejectingHttpClient)

    with pytest.raises(httpx.HTTPStatusError):
        await client.generate_voice("hello")
