"""FIX 3(d): the shared vision QA transport (`static_docu._vision_qa_transport`)
must route through the agent relay when it's active, instead of the direct
Anthropic-then-Kie HTTP call. This transport replaced five near-identical
inline `_ask_once` closures inside `_vision_yes_no`, `_vision_confirms`,
`_render_matches_reference`, `_arbiter_confirms_render`, and
`_view_role_confirms` — each of those keeps its own prompt/max_tokens/
parsing/fail-open-closed verdict logic; only this one round-trip is shared.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/test_static_docu_vision_qa_transport.py -q
"""
from __future__ import annotations

import os
import sys

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.abspath(_BACKEND))
_PIPELINE = os.path.join(_BACKEND, "..", "..", "skills", "video-pipeline")
sys.path.insert(0, os.path.abspath(_PIPELINE))

import static_docu  # noqa: E402
import agent_relay  # noqa: E402
import agent_relay_client  # noqa: E402

# Force the real anthropic SDK to finish loading before any httpx monkeypatch
# — same reasoning as tests/functional/test_static_docu_c2f_vision_gate_fixes.py.
import shared.clients.image_client  # noqa: E402,F401


class _FakeResp:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code

    def json(self):
        return self._body


class _FakeImageResp:
    def __init__(self, content=b"\xff\xd8\xff" + b"0" * 32, status_code=200):
        self.content = content
        self.status_code = status_code
        self.headers = {"content-type": "image/jpeg"}


class _FakeHttpClient:
    def __init__(self, post_reply):
        self._post_reply = post_reply
        self.post_calls = []

    async def get(self, url, **kwargs):
        return _FakeImageResp()

    async def post(self, url, headers=None, json=None, **kwargs):
        self.post_calls.append((url, headers, json))
        return _FakeResp(self._post_reply)


class _ClientCM:
    def __init__(self, inner):
        self._inner = inner

    async def __aenter__(self):
        return self._inner

    async def __aexit__(self, *a):
        return False


@pytest.mark.asyncio
async def test_relay_inactive_uses_direct_http_transport(monkeypatch):
    async def _false(tenant_id):
        return False
    monkeypatch.setattr(agent_relay, "relay_active", _false)

    async def fake_get_secret(name, *a, **k):
        return "fake-anthropic-key" if name == "anthropic_api_key" else None
    monkeypatch.setattr("vault.get_secret", fake_get_secret)

    fake_client = _FakeHttpClient({"content": [{"type": "text", "text": "YES, matches"}]})
    monkeypatch.setattr(static_docu.httpx, "AsyncClient",
                        lambda *a, **k: _ClientCM(fake_client))

    result = await static_docu._vision_qa_transport(
        "tenant-1", ["https://example.com/photo.jpg"], "Is this a B-17?",
        max_tokens=80, log_label="test",
    )

    assert result == "yes, matches"
    assert len(fake_client.post_calls) == 1
    url, headers, body = fake_client.post_calls[0]
    assert url == "https://api.anthropic.com/v1/messages"
    assert body["max_tokens"] == 80


@pytest.mark.asyncio
async def test_relay_active_routes_to_agent_relay_with_image_urls_and_never_calls_http(monkeypatch):
    async def _true(tenant_id):
        return True
    monkeypatch.setattr(agent_relay, "relay_active", _true)

    captured = {}

    class _FakeAgentRelayClient:
        def __init__(self, tenant_id, video_id=None):
            captured["tenant_id"] = tenant_id
            captured["video_id"] = video_id

        async def generate(self, prompt, system_prompt="", model=None,
                            max_tokens=4096, temperature=1.0, **kwargs):
            captured["prompt"] = prompt
            captured["system_prompt"] = system_prompt
            captured["model"] = model
            captured["max_tokens"] = max_tokens
            captured["temperature"] = temperature
            return "YES, matches"

    monkeypatch.setattr(agent_relay_client, "AgentRelayClient", _FakeAgentRelayClient)

    def _boom(*a, **k):
        raise AssertionError("HTTP transport must not be used when the relay is active")
    monkeypatch.setattr(static_docu.httpx, "AsyncClient", _boom)

    result = await static_docu._vision_qa_transport(
        "tenant-1",
        ["https://example.com/ref.jpg", "https://example.com/render.jpg"],
        "Is this a B-17?", max_tokens=80, log_label="test",
    )

    assert result == "yes, matches"
    assert captured["tenant_id"] == "tenant-1"
    assert captured["model"] == "agent-vision"
    assert captured["temperature"] == 0.0
    assert captured["max_tokens"] == 80
    assert "https://example.com/ref.jpg" in captured["prompt"]
    assert "https://example.com/render.jpg" in captured["prompt"]
    assert "Is this a B-17?" in captured["prompt"]


@pytest.mark.asyncio
async def test_relay_timeout_returns_empty_string_for_callers_retry_loop(monkeypatch):
    async def _true(tenant_id):
        return True
    monkeypatch.setattr(agent_relay, "relay_active", _true)

    class _TimingOutClient:
        def __init__(self, tenant_id, video_id=None):
            pass

        async def generate(self, *a, **k):
            raise agent_relay_client.AgentRelayTimeout("no answer in time")

    monkeypatch.setattr(agent_relay_client, "AgentRelayClient", _TimingOutClient)

    result = await static_docu._vision_qa_transport(
        "tenant-1", ["https://example.com/ref.jpg"], "Is this a B-17?",
    )

    assert result == ""
