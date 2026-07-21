"""Redraw gets the SAME treatment as the batch draw (Ryan, 2026-07-21):
style stated FIRST, _STYLE_LOCK appended, cast + LOCKED-LOCATION env refs
attached. assets.image_prompt stores only the composition, so a bare redraw
carried no style pressure and drifted semi-realistic on cd5d2883's scene-1
redraws — this pins the wrapper so that can't regress.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_redraw_style_parity.py -q
"""
import asyncio
import os
import sys
import types
from unittest.mock import AsyncMock, patch

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
_PIPELINE_PATH = os.path.join(_BACKEND, "..", "..", "skills", "video-pipeline")
sys.path.insert(0, os.path.abspath(_BACKEND))
sys.path.insert(0, os.path.abspath(_PIPELINE_PATH))


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


async def _boom(*a, **k):
    raise AssertionError("pure tests must not touch runtime services")


_stub("database", fetch_one=_boom, fetch_all=_boom, execute=_boom)
_stub("storage", upload_bytes=_boom)
_stub("vault", get_secret=_boom)
_stub("kie_unified", get_text_client_for_tenant=_boom)

from scripts.coverage_to_app import redraw_asset_image, _STYLE_LOCK  # noqa: E402

VID, TENANT, ASSET = "vid-1", "tenant-1", "asset-1"
STORED_PROMPT = "(SETUP B) MCU OTS onto Ryan, glancing at the prep board"
STYLE = ("3D animated CGI comedy style. Fully animated 3D cartoon, "
         "NOT photorealistic, NOT live-action, NOT a real photograph.")
ENV = {"name": "Home kitchen", "description": "vintage kitchen, yellow fridge",
       "reference_url": "https://fake/env.png"}


def _run(style=STYLE, envs=None):
    calls = []

    async def fake_fetch_one(query, *args):
        if "FROM assets a JOIN videos v" in query:
            return {"id": ASSET, "scene": 1, "image_index": 122, "image_prompt": STORED_PROMPT,
                    "aspect": "16:9", "image_model_override": None,
                    "image_style_override": style, "visual_style": None}
        if "coverage_directive, scene_text FROM scripts" in query:
            return {"coverage_directive": "vintage kitchen plan", "scene_text": "kitchen scene"}
        raise AssertionError(f"unexpected fetch_one: {query}")

    async def fake_fetch_all(query, *args):
        if "FROM video_characters" in query:
            return [{"reference_url": "https://fake/cast-a.png"}]
        raise AssertionError(f"unexpected fetch_all: {query}")

    async def fake_gen(ic, model_override, prompt, reference_urls=None, **kw):
        calls.append({"prompt": prompt, "refs": list(reference_urls or [])})
        return "https://fake/redrawn.png", "gpt-image-2"

    patches = [
        patch("scripts.coverage_to_app.fetch_one", fake_fetch_one),
        patch("scripts.coverage_to_app.fetch_all", fake_fetch_all),
        patch("scripts.coverage_to_app.execute", AsyncMock()),
        patch("scripts.coverage_to_app.get_secret", AsyncMock(return_value="fake-key")),
        patch("scripts.coverage_to_app.ImageClient", lambda **kw: object()),
        patch("scripts.coverage_to_app._approved_envs", AsyncMock(return_value=envs or [])),
        patch("scripts.coverage_to_app._match_scene_env", lambda text, e: (e[0] if e else None)),
        patch("scripts.coverage_to_app.generate_scene_image_for_model", fake_gen),
        patch("scripts.coverage_to_app._stable_url", AsyncMock(return_value="https://stable/x.png")),
        patch("scripts.coverage_to_app.record_ledger_entry", AsyncMock()),
    ]
    for p in patches:
        p.start()
    try:
        result = asyncio.run(redraw_asset_image(VID, TENANT, ASSET))
    finally:
        for p in patches:
            p.stop()
    assert result["status"] == "completed", result
    assert len(calls) == 1
    return calls[0]


def test_style_goes_first_and_style_lock_is_appended():
    call = _run(envs=[ENV])
    assert call["prompt"].startswith("ART STYLE")
    assert "NOT photorealistic" in call["prompt"][:400]     # the channel style, up front
    assert call["prompt"].index("ART STYLE") < call["prompt"].index(STORED_PROMPT)
    assert _STYLE_LOCK in call["prompt"]                    # same suffix as the batch path


def test_env_ref_rides_last_with_locked_location_note():
    call = _run(envs=[ENV])
    assert call["refs"] == ["https://fake/cast-a.png", "https://fake/env.png"]
    assert "LOCKED LOCATION" in call["prompt"]


def test_no_style_no_env_still_draws_with_style_lock():
    call = _run(style=None, envs=[])
    assert not call["prompt"].startswith("ART STYLE")
    assert call["prompt"].startswith(STORED_PROMPT)
    assert _STYLE_LOCK in call["prompt"]
    assert call["refs"] == ["https://fake/cast-a.png"]
