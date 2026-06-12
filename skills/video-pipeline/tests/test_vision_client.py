"""Unit tests for shared.clients.vision_client — the provider-chained vision
helper. No network: httpx is routed through a MockTransport.

The chain contract under test: Kie Gemini first (with prompt_tokens
ingestion proof), Kie Claude gateway second, direct Anthropic last, and a
loud VisionUnavailable when nothing saw the image.
"""
import asyncio
import json

import httpx
import pytest

from shared.clients import vision_client as vc

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64

GEMINI_OK = {
    "choices": [{"message": {"role": "assistant", "content": "A red circle on blue."},
                 "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 1109, "completion_tokens": 13},
}
GEMINI_BLIND = {  # text-only token count = image was dropped
    "choices": [{"message": {"role": "assistant", "content": "I cannot see any image."},
                 "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 60, "completion_tokens": 8},
}
CLAUDE_OK = {
    "content": [{"type": "text", "text": "Claude saw "}, {"type": "text", "text": "a red circle."}],
    "usage": {"input_tokens": 897, "output_tokens": 20},
    "stop_reason": "end_turn",
}


def _client_with(handler):
    """Patch vision_client's httpx.AsyncClient to use a mock transport."""
    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def factory(**kwargs):
        kwargs.pop("transport", None)
        return real_async_client(transport=transport, **kwargs)

    return factory


def _run(coro):
    return asyncio.run(coro)


def test_gemini_primary_wins(monkeypatch):
    hits = []

    def handler(request):
        hits.append(request.url.path)
        assert "gemini-2.5-flash" in str(request.url)
        body = json.loads(request.content)
        # images must travel as data URLs, never provider-fetched URLs
        image_parts = [p for p in body["messages"][0]["content"] if p["type"] == "image_url"]
        assert image_parts and image_parts[0]["image_url"]["url"].startswith("data:image/png;base64,")
        return httpx.Response(200, json=GEMINI_OK)

    monkeypatch.setattr(vc.httpx, "AsyncClient", _client_with(handler))
    text = _run(vc.vision_call("what is this?", [PNG], kie_key="k"))
    assert text == "A red circle on blue."
    assert len(hits) == 1, "claude must not be hit when gemini succeeds"


def test_blind_gemini_falls_back_to_claude(monkeypatch):
    hits = []

    def handler(request):
        hits.append(request.url.path)
        if "gemini" in str(request.url):
            return httpx.Response(200, json=GEMINI_BLIND)
        return httpx.Response(200, text=json.dumps(CLAUDE_OK))  # Kie omits Content-Type

    monkeypatch.setattr(vc.httpx, "AsyncClient", _client_with(handler))
    text = _run(vc.vision_call("what is this?", [PNG], kie_key="k"))
    # multi-block replies are joined, not truncated to content[0]
    assert text == "Claude saw \na red circle."
    assert len(hits) == 2, hits


def test_gemini_500_falls_back_to_claude(monkeypatch):
    def handler(request):
        if "gemini" in str(request.url):
            return httpx.Response(500, text="upstream exploded")
        return httpx.Response(200, text=json.dumps(CLAUDE_OK))

    monkeypatch.setattr(vc.httpx, "AsyncClient", _client_with(handler))
    text = _run(vc.vision_call("what is this?", [PNG], kie_key="k"))
    assert "red circle" in text


def test_all_providers_failing_raises(monkeypatch):
    def handler(request):
        if "gemini" in str(request.url):
            return httpx.Response(500)
        # gateway-style 200-with-error-body (no "content" key)
        return httpx.Response(200, text=json.dumps({"code": 401, "msg": "bad key"}))

    monkeypatch.setattr(vc.httpx, "AsyncClient", _client_with(handler))
    with pytest.raises(vc.VisionUnavailable) as e:
        _run(vc.vision_call("what is this?", [PNG], kie_key="k"))
    assert "kie-gemini" in str(e.value) and "kie-claude" in str(e.value)


def test_anthropic_used_when_only_anthropic_key(monkeypatch):
    hits = []

    def handler(request):
        hits.append(str(request.url))
        assert request.headers.get("x-api-key") == "sk-ant-x"
        return httpx.Response(200, json=CLAUDE_OK)

    monkeypatch.setattr(vc.httpx, "AsyncClient", _client_with(handler))
    text = _run(vc.vision_call("what is this?", [PNG], anthropic_key="sk-ant-x"))
    assert "red circle" in text
    assert hits == [vc.ANTHROPIC_API_URL]


def test_url_images_are_downloaded_and_html_rejected(monkeypatch):
    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, text="<!DOCTYPE html><html>Drive interstitial</html>")
        raise AssertionError("no provider call should happen for an HTML 'image'")

    monkeypatch.setattr(vc.httpx, "AsyncClient", _client_with(handler))
    with pytest.raises(vc.VisionUnavailable) as e:
        _run(vc.vision_call("what?", ["https://drive.example/x.png"], kie_key="k"))
    assert "HTML" in str(e.value)


def test_media_type_sniffing_and_multi_image(monkeypatch):
    def handler(request):
        body = json.loads(request.content)
        urls = [p["image_url"]["url"] for p in body["messages"][0]["content"]
                if p["type"] == "image_url"]
        assert len(urls) == 2
        assert urls[0].startswith("data:image/png")
        assert urls[1].startswith("data:image/jpeg")
        return httpx.Response(200, json={
            "choices": GEMINI_OK["choices"],
            # two images: ingestion floor scales per image
            "usage": {"prompt_tokens": 2200, "completion_tokens": 13},
        })

    monkeypatch.setattr(vc.httpx, "AsyncClient", _client_with(handler))
    text = _run(vc.vision_call("compare these", [PNG, JPEG], kie_key="k"))
    assert text


def test_no_keys_raises():
    with pytest.raises(vc.VisionUnavailable):
        _run(vc.vision_call("what?", [PNG]))


def test_requires_an_image():
    with pytest.raises(ValueError):
        _run(vc.vision_call("no image", [], kie_key="k"))
