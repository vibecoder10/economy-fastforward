"""FIX 3(a/b/c): background/worker text-LLM calls must route through the
agent relay when it's active, instead of silently spending the tenant's Kie
key. get_pipeline_text_client (kie_unified.py) is the one helper the three
background-only call sites (render_static.py's music mood, static_docu.py's
subject planning, and generate_and_store_seo when its background callers pass
allow_relay=True) now go through. The inline POST /{video_id}/generate-seo
route keeps the direct client, where a relay wait could hang the response.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PIPELINE = Path(__file__).resolve().parents[3] / "skills" / "video-pipeline"
if str(_PIPELINE) not in sys.path:
    sys.path.insert(0, str(_PIPELINE))

import agent_relay  # noqa: E402
import kie_unified  # noqa: E402
from agent_relay_client import AgentRelayClient  # noqa: E402


@pytest.mark.asyncio
async def test_relay_active_returns_agent_relay_client(monkeypatch):
    async def _true(tenant_id):
        return True
    monkeypatch.setattr(agent_relay, "relay_active", _true)

    client = await kie_unified.get_pipeline_text_client("tenant-1", "video-1")

    assert isinstance(client, AgentRelayClient)
    assert client.tenant_id == "tenant-1"
    assert client.video_id == "video-1"


@pytest.mark.asyncio
async def test_relay_inactive_falls_back_to_direct_client(monkeypatch):
    async def _false(tenant_id):
        return False
    monkeypatch.setattr(agent_relay, "relay_active", _false)

    sentinel = object()

    async def fake_get_text_client_for_tenant(tenant_id):
        assert tenant_id == "tenant-2"
        return sentinel
    monkeypatch.setattr(kie_unified, "get_text_client_for_tenant", fake_get_text_client_for_tenant)

    client = await kie_unified.get_pipeline_text_client("tenant-2")

    assert client is sentinel


@pytest.mark.asyncio
async def test_relay_active_without_video_id_scopes_tenant_only(monkeypatch):
    async def _true(tenant_id):
        return True
    monkeypatch.setattr(agent_relay, "relay_active", _true)

    client = await kie_unified.get_pipeline_text_client("tenant-3")

    assert isinstance(client, AgentRelayClient)
    assert client.video_id is None


class _FakeSeoClient:
    async def generate(self, **kwargs):
        return '{"description": "d", "tags": ["t"], "hashtags": ["h"], "category": "education"}'


@pytest.mark.parametrize("allow_relay, expected", [(True, "pipeline"), (False, "direct")])
@pytest.mark.asyncio
async def test_seo_uses_pipeline_client_only_when_allowed(monkeypatch, allow_relay, expected):
    import youtube_publish
    used = []

    async def _fetch_one(query, *args):
        if "FROM videos" in query:
            return {"video_title": "T"}
        return None

    async def _fetch_all(query, *args):
        return []

    async def _execute(query, *args):
        return "UPDATE 1"

    async def _pipeline(tenant_id, video_id=None):
        used.append("pipeline")
        return _FakeSeoClient()

    async def _direct(tenant_id):
        used.append("direct")
        return _FakeSeoClient()

    monkeypatch.setattr(youtube_publish, "fetch_one", _fetch_one)
    monkeypatch.setattr(youtube_publish, "fetch_all", _fetch_all)
    monkeypatch.setattr(youtube_publish, "execute", _execute)
    monkeypatch.setattr(youtube_publish, "get_pipeline_text_client", _pipeline)
    monkeypatch.setattr(youtube_publish, "get_text_client_for_tenant", _direct)

    await youtube_publish.generate_and_store_seo("v", "t", allow_relay=allow_relay)
    assert used == [expected]
