"""Tests for chunk C2h (2026-07-22): post-generation vision QA rejected 100%
of our own static-docu renders.

PROVEN live: 6 scenes, 12 generations (both the initial render and its one
retry, per scene), all 12 rejected. `generate_static_images_for_video`
renders a deliberately clean WHITE-STUDIO product-style image of the
machine (image-to-image from a verified reference), then calls
`_vision_confirms` to check the OUTPUT. `_vision_confirms`'s question ("is
this a real photograph... not a sketch/diagram/blueprint/scale model") is
right for judging a candidate REFERENCE photo, but wrong for judging OUR OWN
RENDER: a pristine studio render of a museum-condition aircraft reads as
CGI/render/model to the vision model -> NO -> hard-reject, every time, by
design of the very prompt that generated it.

Fix: `_render_matches_reference` (static_docu.py) replaces `_vision_confirms`
at BOTH post-generation QA call sites in `_one_scene` (initial check + the
one-retry check). It sends TWO images in one message (reference photo
FIRST, our render SECOND) and asks only whether they show the SAME aircraft
type/configuration — livery/markings/background/style differences, and the
render simply LOOKING like a clean render, are explicitly told to be fine.
No "real photograph" requirement, no flat-media/scale-model hard-rejects for
the render. The only hard-reject left is the render itself being reported
empty/blank/not-an-aircraft.

`_vision_confirms` is UNCHANGED for every other call site (candidate
reference-photo verification in `_one_scene`, `_prefetch_one_machine`,
`seed_reference_from_url`) — those genuinely judge real photos, where the
old wording is correct.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_static_docu_c2h_render_qa.py -q
"""
import base64
import os
import sys

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import static_docu  # noqa: E402

# Pre-import for the same reason the C2f/C2g test files do: anthropic's
# _base_client.py subclasses httpx.AsyncClient at MODULE IMPORT time, so it
# must finish loading before any test monkeypatches httpx.AsyncClient to a
# fake callable.
import shared.clients.image_client  # noqa: E402,F401

from test_static_docu_c2f_vision_gate_fixes import (  # noqa: E402
    _FakeHttpClient,
    _FakeImageResp,
    _FakeResp,
    _anthropic_body,
    _install_vision_fakes,
)

_FAKE_REF_JPEG = b"\xff\xd8\xff" + b"R" * 40   # arbitrary "reference photo" bytes
_FAKE_RENDER_PNG = b"\x89PNG" + b"D" * 40      # arbitrary "our render" bytes


# ---------------------------------------------------------------------------
# 1. Two-image payload: reference FIRST, render SECOND, both base64 — this
#    is the whole structural fix (C2f/C2g's single-image URL/base64 shape
#    can't express "compare against a second image" at all).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_two_image_payload_order_reference_then_render(monkeypatch):
    fake_client = _install_vision_fakes(
        monkeypatch,
        [_anthropic_body("YES, same aircraft type and configuration")],
        get_replies=[
            _FakeImageResp(content=_FAKE_REF_JPEG, content_type="image/jpeg"),
            _FakeImageResp(content=_FAKE_RENDER_PNG, content_type="image/png"),
        ],
    )
    captured = {}
    orig_post = fake_client.post

    async def spy_post(url, headers=None, json=None, **kwargs):
        captured["json"] = json
        return await orig_post(url, headers=headers, json=json, **kwargs)

    monkeypatch.setattr(fake_client, "post", spy_post)

    result = await static_docu._render_matches_reference(
        "tenant-1", "https://example.com/render.png",
        "https://example.com/reference.jpg", "Boeing XB-15")

    assert result is True
    content = captured["json"]["messages"][0]["content"]
    assert content[0]["type"] == "text"
    image_blocks = [b for b in content if b["type"] == "image"]
    assert len(image_blocks) == 2

    ref_block, render_block = image_blocks
    assert ref_block["source"]["type"] == "base64"
    assert ref_block["source"]["media_type"] == "image/jpeg"
    assert ref_block["source"]["data"] == base64.b64encode(_FAKE_REF_JPEG).decode("ascii")

    assert render_block["source"]["type"] == "base64"
    assert render_block["source"]["media_type"] == "image/png"
    assert render_block["source"]["data"] == base64.b64encode(_FAKE_RENDER_PNG).decode("ascii")

    # Prompt must name image 1 as the reference and image 2 as our render.
    assert "image 1" in content[0]["text"].lower()
    assert "image 2" in content[0]["text"].lower()


# ---------------------------------------------------------------------------
# 2. YES (same aircraft) -> True.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_yes_same_aircraft_returns_true(monkeypatch):
    _install_vision_fakes(monkeypatch, [
        _anthropic_body("YES, same overall shape, wing form and tail configuration"),
    ])
    result = await static_docu._render_matches_reference(
        "tenant-1", "https://example.com/render.png",
        "https://example.com/reference.jpg", "Boeing XB-15")
    assert result is True


# ---------------------------------------------------------------------------
# 3. NO (different aircraft type/variant) -> False.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_different_aircraft_returns_false(monkeypatch):
    _install_vision_fakes(monkeypatch, [
        _anthropic_body("NO, image 2 shows a four-engine bomber, a different "
                        "aircraft type than image 1"),
    ])
    result = await static_docu._render_matches_reference(
        "tenant-1", "https://example.com/render.png",
        "https://example.com/reference.jpg", "Boeing XB-15")
    assert result is False


# ---------------------------------------------------------------------------
# 4. Render-ness must NOT reject — the whole point of C2h. A reply that
#    correctly notes image 2 is a rendered/illustrated image (which it always
#    is, by design of _STUDIO_PROMPT) must still pass when it's the same
#    aircraft, unlike _vision_confirms's flat-media hard-reject.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_render_ness_does_not_trigger_rejection(monkeypatch):
    _install_vision_fakes(monkeypatch, [
        _anthropic_body(
            "YES, this is a rendered image / clean studio illustration, but "
            "it shows the same aircraft type and configuration as image 1"),
    ])
    result = await static_docu._render_matches_reference(
        "tenant-1", "https://example.com/render.png",
        "https://example.com/reference.jpg", "Boeing XB-15")
    assert result is True, (
        "the render simply LOOKING like a render must never be a rejection "
        "reason — that is the entire C2h bug")


# ---------------------------------------------------------------------------
# 5. Hard reject: render reported empty/blank/not-an-aircraft overrides even
#    a YES-first-word reply.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_render_hard_rejected_even_on_yes(monkeypatch):
    _install_vision_fakes(monkeypatch, [
        _anthropic_body("YES, but image 2 appears empty, with no aircraft visible"),
    ])
    result = await static_docu._render_matches_reference(
        "tenant-1", "https://example.com/render.png",
        "https://example.com/reference.jpg", "Boeing XB-15")
    assert result is False


@pytest.mark.asyncio
async def test_blank_render_hard_rejected(monkeypatch):
    _install_vision_fakes(monkeypatch, [
        _anthropic_body("NO, image 2 is blank"),
    ])
    result = await static_docu._render_matches_reference(
        "tenant-1", "https://example.com/render.png",
        "https://example.com/reference.jpg", "Boeing XB-15")
    assert result is False


# ---------------------------------------------------------------------------
# 6. Transport failure fails CLOSED: retry once, then rejected — same
#    contract as _vision_confirms (C2f/C2g).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_transport_exception_retries_once_then_fails_closed(monkeypatch):
    fake_client = _install_vision_fakes(monkeypatch, [], get_replies=[
        RuntimeError("connection reset"),  # attempt 1: ref download fails
        _FakeImageResp(content=_FAKE_RENDER_PNG),  # attempt 1: render download (still tried)
        RuntimeError("connection reset"),  # attempt 2: ref download fails
        _FakeImageResp(content=_FAKE_RENDER_PNG),  # attempt 2: render download
    ])
    result = await static_docu._render_matches_reference(
        "tenant-1", "https://example.com/render.png",
        "https://example.com/reference.jpg", "Boeing XB-15")
    assert result is False
    assert fake_client.get_calls == 4, "must retry exactly once (2 download attempts x 2 images)"
    assert fake_client.calls == 0, "model API must never be called when a download fails"


@pytest.mark.asyncio
async def test_model_api_non_200_retries_then_fails_closed(monkeypatch):
    fake_client = _install_vision_fakes(monkeypatch, [
        _FakeResp({"error": "nope"}, status_code=400),
        _FakeResp({"error": "nope"}, status_code=400),
    ])
    result = await static_docu._render_matches_reference(
        "tenant-1", "https://example.com/render.png",
        "https://example.com/reference.jpg", "Boeing XB-15")
    assert result is False
    assert fake_client.calls == 2, "must retry exactly once on a non-200 model response"


@pytest.mark.asyncio
async def test_transport_succeeds_on_retry(monkeypatch):
    fake_client = _install_vision_fakes(monkeypatch, [
        {"type": "error", "error": {}},  # attempt 1: empty/unusable reply
        _anthropic_body("YES, same aircraft"),  # attempt 2: succeeds
    ])
    result = await static_docu._render_matches_reference(
        "tenant-1", "https://example.com/render.png",
        "https://example.com/reference.jpg", "Boeing XB-15")
    assert result is True
    assert fake_client.calls == 2


# ---------------------------------------------------------------------------
# 7. Keyless carve-out unchanged: no provider key on the tenant fails OPEN
#    (config gap, not a transport symptom) — same as _vision_confirms.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_provider_key_fails_open(monkeypatch):
    _install_vision_fakes(monkeypatch, [], anthropic_key=None)

    import vault

    async def fake_get_secret(name, *a, **k):
        return None  # neither anthropic_api_key nor kie_ai_api_key configured

    monkeypatch.setattr(vault, "get_secret", fake_get_secret)

    result = await static_docu._render_matches_reference(
        "tenant-1", "https://example.com/render.png",
        "https://example.com/reference.jpg", "Boeing XB-15")
    assert result is True


# ---------------------------------------------------------------------------
# 8. Aliases are surfaced in the prompt (same convention as _vision_confirms).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_aliases_included_in_prompt(monkeypatch):
    fake_client = _install_vision_fakes(monkeypatch, [
        _anthropic_body("YES, same aircraft"),
    ])
    captured = {}
    orig_post = fake_client.post

    async def spy_post(url, headers=None, json=None, **kwargs):
        captured["json"] = json
        return await orig_post(url, headers=headers, json=json, **kwargs)

    monkeypatch.setattr(fake_client, "post", spy_post)

    await static_docu._render_matches_reference(
        "tenant-1", "https://example.com/render.png",
        "https://example.com/reference.jpg", "Douglas XB-42 Mixmaster",
        aliases=["XB-42"])

    text = captured["json"]["messages"][0]["content"][0]["text"]
    assert "XB-42" in text
