"""Tests for chunk C2g (2026-07-21): `_vision_confirms` (static_docu.py) can
never verify a first-time hosted candidate because it hands the model a URL-
source image reference the model API can't fetch.

PROVEN live: `_vision_confirms` built `"url": _kie_fetchable_url(image_url)`
WITHOUT tenant_id -> unsigned media-proxy URL -> 401. Even a signed proxy URL
404s: routes/media.py's `_ALLOWLIST_SQL` only matches file ids already present
in assets/video_characters/scripts/videos — a freshly `_host_reference`d
candidate exists only in storage (and later static_reference_cache, which
isn't allowlisted), so the proxy refuses it at verification time. Anthropic
then returns a 400 error body ("Unable to download the file"); `_ask_once`
used to ignore the HTTP status, read empty content, retry once, then C2f's
fail-closed -> False. Net effect: EVERY untrusted/first-time candidate was
silently rejected.

Fix: `_vision_confirms` now downloads the candidate image itself and sends
it inline as base64 (the same self-fetch pattern `_host_reference` already
uses), for BOTH the direct-Anthropic and Kie-gateway branches — confirmed
live that Kie's Claude gateway already accepts this exact base64 block shape
elsewhere (shared/clients/vision_client.py's `_claude_blocks`).

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_static_docu_c2g_vision_download_fix.py -q
"""
import base64
import os
import sys

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import static_docu  # noqa: E402

# Pre-import for the same reason test_static_docu_c2f_vision_gate_fixes.py
# does: anthropic's _base_client.py subclasses httpx.AsyncClient at MODULE
# IMPORT time, so it must finish loading before any test monkeypatches
# httpx.AsyncClient to a fake callable.
import shared.clients.image_client  # noqa: E402,F401

from test_static_docu_c2f_vision_gate_fixes import (  # noqa: E402
    _FakeHttpClient,
    _FakeImageResp,
    _FakeResp,
    _anthropic_body,
    _install_vision_fakes,
)

_FAKE_JPEG = b"\xff\xd8\xff" + b"1" * 64  # valid JPEG magic bytes, arbitrary body


# ---------------------------------------------------------------------------
# 1. Happy path: base64 is what actually gets sent to the model, with the
#    right media_type derived from the download's Content-Type.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sends_base64_image_source_not_url(monkeypatch):
    fake_client = _install_vision_fakes(
        monkeypatch,
        [_anthropic_body("YES, this is the requested aircraft")],
        get_replies=[_FakeImageResp(content=_FAKE_JPEG, content_type="image/jpeg")],
    )
    captured = {}
    orig_post = fake_client.post

    async def spy_post(url, headers=None, json=None, **kwargs):
        captured["json"] = json
        return await orig_post(url, headers=headers, json=json, **kwargs)

    monkeypatch.setattr(fake_client, "post", spy_post)

    result = await static_docu._vision_confirms(
        "tenant-1", "https://example.com/xb15.jpg", "Boeing XB-15",
        trusted_source=False)

    assert result is True
    content = captured["json"]["messages"][0]["content"]
    image_block = next(b for b in content if b["type"] == "image")
    assert image_block["source"]["type"] == "base64"
    assert image_block["source"]["media_type"] == "image/jpeg"
    assert image_block["source"]["data"] == base64.b64encode(_FAKE_JPEG).decode("ascii")
    # No URL-source anywhere — the old bug's exact shape must be gone.
    assert image_block["source"].get("type") != "url"


@pytest.mark.asyncio
async def test_media_type_follows_download_content_type(monkeypatch):
    png_bytes = b"\x89PNG" + b"2" * 40
    fake_client = _install_vision_fakes(
        monkeypatch,
        [_anthropic_body("YES, confirmed")],
        get_replies=[_FakeImageResp(content=png_bytes, content_type="image/png")],
    )
    captured = {}
    orig_post = fake_client.post

    async def spy_post(url, headers=None, json=None, **kwargs):
        captured["json"] = json
        return await orig_post(url, headers=headers, json=json, **kwargs)

    monkeypatch.setattr(fake_client, "post", spy_post)

    result = await static_docu._vision_confirms(
        "tenant-1", "https://example.com/xb15.png", "Boeing XB-15",
        trusted_source=False)

    assert result is True
    image_block = next(b for b in captured["json"]["messages"][0]["content"]
                       if b["type"] == "image")
    assert image_block["source"]["media_type"] == "image/png"
    assert image_block["source"]["data"] == base64.b64encode(png_bytes).decode("ascii")


# ---------------------------------------------------------------------------
# 2. Download 404 -> retry -> False. Model is never even reached on either
#    attempt (the actual live bug: an unfetchable proxy URL).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_download_404_retries_then_fails_closed(monkeypatch):
    fake_client = _install_vision_fakes(
        monkeypatch,
        [],  # no model replies scripted — must never be consumed
        get_replies=[
            _FakeImageResp(status_code=404, content=b""),
            _FakeImageResp(status_code=404, content=b""),
        ],
    )
    result = await static_docu._vision_confirms(
        "tenant-1", "https://storyengine.dev/api/media/drive/abc.png",
        "Boeing XB-15", trusted_source=False)
    assert result is False
    assert fake_client.get_calls == 2
    assert fake_client.calls == 0, "model API must never be called on a download failure"


@pytest.mark.asyncio
async def test_download_exception_retries_then_fails_closed(monkeypatch):
    fake_client = _install_vision_fakes(
        monkeypatch,
        [],
        get_replies=[RuntimeError("connection reset"), RuntimeError("connection reset")],
    )
    result = await static_docu._vision_confirms(
        "tenant-1", "https://example.com/photo.jpg", "Boeing XB-15",
        trusted_source=False)
    assert result is False
    assert fake_client.get_calls == 2
    assert fake_client.calls == 0


# ---------------------------------------------------------------------------
# 3. Oversize payload -> False, without ever calling the model.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_oversize_download_fails_without_calling_model(monkeypatch):
    oversize = b"\xff\xd8\xff" + b"0" * 4_600_000  # > 4.5MB guard
    fake_client = _install_vision_fakes(
        monkeypatch,
        [],  # model must never be invoked
        get_replies=[
            _FakeImageResp(content=oversize),
            _FakeImageResp(content=oversize),
        ],
    )
    result = await static_docu._vision_confirms(
        "tenant-1", "https://example.com/huge.jpg", "Boeing XB-15",
        trusted_source=False)
    assert result is False
    assert fake_client.calls == 0, "an oversize download must never reach the model API"


# ---------------------------------------------------------------------------
# 4. Model API non-200 counts as a failed attempt (not parsed as an empty-
#    but-successful reply) -> retry -> False.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_model_api_non_200_counts_as_failed_attempt(monkeypatch):
    fake_client = _install_vision_fakes(monkeypatch, [
        _FakeResp({"type": "error", "error": {"message": "bad request"}}, status_code=400),
        _FakeResp({"type": "error", "error": {"message": "bad request"}}, status_code=400),
    ])
    result = await static_docu._vision_confirms(
        "tenant-1", "https://example.com/photo.jpg", "Boeing XB-15",
        trusted_source=False)
    assert result is False
    assert fake_client.calls == 2, "must retry exactly once on a non-200 model response"


@pytest.mark.asyncio
async def test_model_api_non_200_then_200_accepts_second_attempt(monkeypatch):
    fake_client = _install_vision_fakes(monkeypatch, [
        _FakeResp({"error": "nope"}, status_code=400),
        _anthropic_body("YES, this is the requested aircraft"),
    ])
    result = await static_docu._vision_confirms(
        "tenant-1", "https://example.com/photo.jpg", "Boeing XB-15",
        trusted_source=False)
    assert result is True
    assert fake_client.calls == 2


# ---------------------------------------------------------------------------
# 5. Happy path end-to-end, download succeeds and model says YES -> True.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_happy_path_yes_returns_true(monkeypatch):
    _install_vision_fakes(monkeypatch, [
        _anthropic_body("YES, this is consistent with the Boeing XB-15"),
    ])
    result = await static_docu._vision_confirms(
        "tenant-1", "https://storyengine.dev/api/media/drive/abc.png?token=xyz",
        "Boeing XB-15", trusted_source=False)
    assert result is True
