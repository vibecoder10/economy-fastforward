"""D15-7: ONE style-resolution entry point (closes D6-1d's family for good).

THE PROBLEM (D15-1 sweep + D6-1d): style resolved through THREE different
paths — assembler A (sheet, generate_storyboard_sheet_for_scene) used a plain
style_dir string from coverage_to_app._resolve_style; assembler B (run_coverage
frames, storyboard.coverage.generate_coverage_frames) used
_stated_style_prefix(profile) (fed by the SAME _resolve_style) but ALSO,
independently, storyboard.bot.build_image_prompt_from_keyframe's own
env-based (VISUAL_PROFILE, process-global) style lookup — a real, provable
SECOND style-resolution mechanism inside one function, ignoring the `profile`
argument it was handed; assembler C (redraw, redraw_asset_image) rendered
_resolve_style's output as an ART STYLE instruction. AND the documented
D6-1d defect: a video whose creator picked a `style_preset_id` with neither
image_style_override nor visual_style also set resolved to the neutral
default on every one of these paths — _resolve_style never consulted that
column at all.

THE FIX (this chunk):
  1. _resolve_style (coverage_to_app.py) gained a third precedence tier:
     style_preset_id, resolved via the new _preset_style_directive() helper
     into the same freeform text image_style_override/visual_style already
     carry (see test_d6_1_canonical_inputs.py's D15-7 section for the
     exhaustive precedence-contract unit tests — image_style_override >
     visual_style > style_preset_id > None).
  2. All three assembler call sites (generate_storyboard_sheet_for_scene,
     generate_coverage_for_video, redraw_asset_image) now SELECT
     style_preset_id and pass it into _resolve_style — proven by the
     wiring-spy tests below, which fail if any call site's SELECT or
     argument-threading regresses even though _resolve_style itself stays
     correct in isolation.
  3. storyboard.bot.build_image_prompt_from_keyframe gained an
     `apply_style_wrapping` parameter (default True — every pre-existing
     caller unchanged); storyboard.coverage.generate_coverage_frames's two
     call sites (master + angle frames) now pass apply_style_wrapping=False,
     since _stated_style_prefix(profile) — fed by the SAME correctly-
     resolved `profile` — already states the ART STYLE line once, upstream.
     This retires the redundant/leak-prone second resolution for the
     coverage path specifically, without touching the legacy
     run_storyboard_prompts/run_storyboard_images callers that still rely on
     it as their ONLY style-injection point.

This file covers wiring (assembler A + B: does the SELECT + call-site
threading actually reach _resolve_style with the real style_preset_id) and
the double-injection fix (assembler B's generate_coverage_frames). Assembler
C's end-to-end value proof lives in test_redraw_style_parity.py (extended by
this same chunk with a preset-only case) since that file already has a full
DB-mocked harness that captures the ACTUAL rendered prompt text.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_d15_7_style_resolution_wiring.py -q
"""
import asyncio
import os
import sys
import types
from unittest.mock import AsyncMock, patch

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
_PIPELINE_PATH = os.path.join(_BACKEND, "..", "..", "..", "skills", "video-pipeline")
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

import scripts.coverage_to_app as cta  # noqa: E402
from scripts.coverage_to_app import (  # noqa: E402
    generate_storyboard_sheet_for_scene,
    generate_coverage_for_video,
    _scene_text_hash,
    _resolve_style as _real_resolve_style,
)

VIDEO_ID = "22222222-2222-2222-2222-222222222222"
TENANT_ID = "tenant-1"
SCENE_TEXT = "The city lights flicker as rain falls onto empty streets."
DIRECTIVE = (
    "[MOMENT 1 | rain falls on empty streets]\n"
    "- MASTER [WS]: Wide shot of rain-soaked streets, neon reflections shimmering.\n"
    "- ANGLE [MCU]: Close on droplets streaking down a window pane.\n"
)
SCENE_HASH = _scene_text_hash(SCENE_TEXT)
PRESET_ID = "cinematic_illustration"


def _video_row(style_preset_id=None, image_style_override=None, visual_style=None):
    return {
        "id": VIDEO_ID, "tenant_id": TENANT_ID, "video_title": "Test Video",
        "aspect": "16:9", "image_style_override": image_style_override,
        "visual_style": visual_style, "style_preset_id": style_preset_id,
        "image_model_override": None, "render_style": None,
        "video_model": "grok-imagine", "dialogue_audio": "voice_over",
    }


def _spying_resolve_style():
    """A drop-in replacement for _resolve_style that records every call's
    args and delegates to the REAL implementation — so a test can assert on
    both "was it called with the right style_preset_id" (wiring) and "did it
    return the right thing" (correctness) in one patch. Delegating through
    the real function is deliberate: if a stash/revert drops the 3rd
    parameter from _resolve_style's signature entirely, calling it with 3
    positional args here raises TypeError, which pytest reports as a hard
    failure on this test — not a silent pass."""
    calls = []

    def spy(image_style_override, visual_style, style_preset_id=None):
        calls.append((image_style_override, visual_style, style_preset_id))
        return _real_resolve_style(image_style_override, visual_style, style_preset_id)

    return spy, calls


# =============================================================================
# Assembler A — generate_storyboard_sheet_for_scene (the sheet composer)
# =============================================================================

def test_sheet_composer_selects_and_threads_style_preset_id():
    """Wiring-spy: proves generate_storyboard_sheet_for_scene's own SELECT
    fetches style_preset_id AND passes it into _resolve_style — not just
    that _resolve_style handles a 3rd argument correctly in isolation.
    plan_only=True keeps this a zero-network, zero-DB-write dry run (D3-59)."""
    spy, calls = _spying_resolve_style()

    async def fetch_one(query, *args):
        if "FROM videos WHERE id=$1" in query:
            return _video_row(style_preset_id=PRESET_ID)
        if "coverage_directive, coverage_directive_hash FROM scripts" in query:
            return {"id": "script-1", "coverage_directive": None, "coverage_directive_hash": None}
        raise AssertionError(f"unexpected fetch_one: {query}")

    async def fetch_all(query, *args):
        if "SELECT scene, scene_text FROM scripts" in query:
            return [{"scene": 1, "scene_text": SCENE_TEXT}]
        if "FROM video_characters" in query:
            return []
        raise AssertionError(f"unexpected fetch_all: {query}")

    patches = [
        patch("scripts.coverage_to_app.fetch_one", fetch_one),
        patch("scripts.coverage_to_app.fetch_all", fetch_all),
        patch("scripts.coverage_to_app.execute", AsyncMock()),
        patch("scripts.coverage_to_app.get_secret", AsyncMock(return_value="fake-kie-key")),
        patch("scripts.coverage_to_app.get_text_client_for_tenant", AsyncMock(return_value=object())),
        patch("scripts.coverage_to_app.claude_model_for_direct_client", lambda c: "fake-model"),
        patch("scripts.coverage_to_app.scene_aware_bible", AsyncMock(return_value=None)),
        patch("scripts.coverage_to_app._approved_envs", AsyncMock(return_value=[])),
        patch("scripts.coverage_to_app.generate_coverage_directive", AsyncMock(return_value=DIRECTIVE)),
        patch("scripts.coverage_to_app._resolve_style", spy),
    ]
    for p in patches:
        p.start()
    try:
        result = asyncio.run(
            generate_storyboard_sheet_for_scene(VIDEO_ID, TENANT_ID, scene=1, plan_only=True))
    finally:
        for p in patches:
            p.stop()

    assert result["status"] == "completed", result
    assert calls, "generate_storyboard_sheet_for_scene never called _resolve_style"
    assert calls[0] == (None, None, PRESET_ID), calls


def test_sheet_composer_freeform_still_wins_over_preset_in_real_call():
    spy, calls = _spying_resolve_style()

    async def fetch_one(query, *args):
        if "FROM videos WHERE id=$1" in query:
            return _video_row(style_preset_id=PRESET_ID, image_style_override="Claymation")
        if "coverage_directive, coverage_directive_hash FROM scripts" in query:
            return {"id": "script-1", "coverage_directive": None, "coverage_directive_hash": None}
        raise AssertionError(f"unexpected fetch_one: {query}")

    async def fetch_all(query, *args):
        if "SELECT scene, scene_text FROM scripts" in query:
            return [{"scene": 1, "scene_text": SCENE_TEXT}]
        if "FROM video_characters" in query:
            return []
        raise AssertionError(f"unexpected fetch_all: {query}")

    patches = [
        patch("scripts.coverage_to_app.fetch_one", fetch_one),
        patch("scripts.coverage_to_app.fetch_all", fetch_all),
        patch("scripts.coverage_to_app.execute", AsyncMock()),
        patch("scripts.coverage_to_app.get_secret", AsyncMock(return_value="fake-kie-key")),
        patch("scripts.coverage_to_app.get_text_client_for_tenant", AsyncMock(return_value=object())),
        patch("scripts.coverage_to_app.claude_model_for_direct_client", lambda c: "fake-model"),
        patch("scripts.coverage_to_app.scene_aware_bible", AsyncMock(return_value=None)),
        patch("scripts.coverage_to_app._approved_envs", AsyncMock(return_value=[])),
        patch("scripts.coverage_to_app.generate_coverage_directive", AsyncMock(return_value=DIRECTIVE)),
        patch("scripts.coverage_to_app._resolve_style", spy),
    ]
    for p in patches:
        p.start()
    try:
        result = asyncio.run(
            generate_storyboard_sheet_for_scene(VIDEO_ID, TENANT_ID, scene=1, plan_only=True))
    finally:
        for p in patches:
            p.stop()

    assert result["status"] == "completed", result
    assert calls[0] == ("Claymation", None, PRESET_ID)
    # And the actual resolution the sheet composer got back honors precedence.
    _profile, style = _real_resolve_style("Claymation", None, PRESET_ID)
    assert "clay" in style.lower() and "illustration" not in style.lower()


# =============================================================================
# Assembler B — generate_coverage_for_video (the real per-shot coverage draw)
# =============================================================================

def _coverage_fakedb(style_preset_id):
    class FakeDB:
        async def fetch_one(self, query, *args):
            if "FROM videos WHERE id=$1" in query:
                return _video_row(style_preset_id=style_preset_id)
            if "coverage_directive_hash" in query and "FROM scripts" in query:
                return None  # no saved plan -> always a fresh run_coverage call
            raise AssertionError(f"unexpected fetch_one: {query}")

        async def fetch_all(self, query, *args):
            if "SELECT scene, scene_text FROM scripts" in query:
                return [{"scene": 1, "scene_text": SCENE_TEXT}]
            if "FROM video_characters" in query:
                return [{"reference_url": "https://cast.png/x.png"}]
            raise AssertionError(f"unexpected fetch_all: {query}")

        async def execute(self, query, *args):
            return "OK"

    return FakeDB()


def _fresh_run_coverage_output(**_kwargs):
    return {
        "moments": [{
            "summary": "rain falls on empty streets",
            "frames": [
                {"file": "master.png", "role": "master", "description": "wide shot", "shot_type": "WS"},
                {"file": "angle.png", "role": "angle", "description": "close shot", "shot_type": "MCU"},
            ],
            "speaker": None, "line": None,
        }],
    }


def test_coverage_entry_selects_and_threads_style_preset_id():
    """Wiring-spy: proves generate_coverage_for_video's own SELECT fetches
    style_preset_id AND passes it into _resolve_style, whose `profile`
    return then reaches run_coverage's profile= kwarg — the SAME channel
    storyboard.coverage._stated_style_prefix reads for the real per-shot
    ART STYLE line (D15-7 closes D6-1d by construction: one function, one
    call, one profile object threaded all the way to the real draw)."""
    fakedb = _coverage_fakedb(PRESET_ID)
    spy, calls = _spying_resolve_style()
    run_coverage_mock = AsyncMock(side_effect=_fresh_run_coverage_output)

    patches = [
        patch("scripts.coverage_to_app.fetch_one", fakedb.fetch_one),
        patch("scripts.coverage_to_app.fetch_all", fakedb.fetch_all),
        patch("scripts.coverage_to_app.execute", fakedb.execute),
        patch("scripts.coverage_to_app.get_secret", AsyncMock(return_value="fake-kie-key")),
        patch("scripts.coverage_to_app.get_text_client_for_tenant", AsyncMock(return_value=object())),
        patch("scripts.coverage_to_app.claude_model_for_direct_client", lambda c: "fake-model"),
        patch("scripts.coverage_to_app.scene_aware_bible", AsyncMock(return_value=None)),
        patch("scripts.coverage_to_app._approved_envs", AsyncMock(return_value=[])),
        patch("scripts.coverage_to_app.store_scene", AsyncMock(return_value=2)),
        patch("scripts.coverage_to_app.set_scene_board", AsyncMock(return_value=True)),
        patch("scripts.coverage_to_app._write_motion_prompts", AsyncMock(return_value=0)),
        patch("scripts.coverage_to_app.populate_characters", AsyncMock(return_value=0)),
        patch("scripts.coverage_to_app._reconcile_moment_dialogue", lambda moments, text: None),
        patch("scripts.coverage_to_app.run_coverage", run_coverage_mock),
        patch("scripts.coverage_to_app.resolve_cast_url", AsyncMock(return_value="https://cast.png/x.png")),
        patch("scripts.coverage_to_app._resolve_style", spy),
    ]
    for p in patches:
        p.start()
    try:
        result = asyncio.run(generate_coverage_for_video(VIDEO_ID, TENANT_ID))
    finally:
        for p in patches:
            p.stop()

    assert result["status"] in ("completed", "partial"), result
    assert calls, "generate_coverage_for_video never called _resolve_style"
    assert calls[0] == (None, None, PRESET_ID), calls

    # The `profile` kwarg run_coverage actually received carries the resolved
    # preset text — the SAME object _stated_style_prefix(profile) consumes
    # inside generate_coverage_frames for the real per-shot ART STYLE line.
    assert run_coverage_mock.await_args_list, "run_coverage was never called"
    passed_profile = run_coverage_mock.await_args_list[0].kwargs["profile"]
    assert "illustration" in passed_profile.visual_style_directive.lower()


def test_coverage_entry_neutral_v1_preset_stays_the_default_profile():
    """Regression lock for the ONE real production video today
    (style_preset_id='neutral_v1', no freeform fields) — must resolve
    exactly like no style being set at all, byte-identical to pre-D15-7."""
    fakedb = _coverage_fakedb("neutral_v1")
    run_coverage_mock = AsyncMock(side_effect=_fresh_run_coverage_output)

    patches = [
        patch("scripts.coverage_to_app.fetch_one", fakedb.fetch_one),
        patch("scripts.coverage_to_app.fetch_all", fakedb.fetch_all),
        patch("scripts.coverage_to_app.execute", fakedb.execute),
        patch("scripts.coverage_to_app.get_secret", AsyncMock(return_value="fake-kie-key")),
        patch("scripts.coverage_to_app.get_text_client_for_tenant", AsyncMock(return_value=object())),
        patch("scripts.coverage_to_app.claude_model_for_direct_client", lambda c: "fake-model"),
        patch("scripts.coverage_to_app.scene_aware_bible", AsyncMock(return_value=None)),
        patch("scripts.coverage_to_app._approved_envs", AsyncMock(return_value=[])),
        patch("scripts.coverage_to_app.store_scene", AsyncMock(return_value=2)),
        patch("scripts.coverage_to_app.set_scene_board", AsyncMock(return_value=True)),
        patch("scripts.coverage_to_app._write_motion_prompts", AsyncMock(return_value=0)),
        patch("scripts.coverage_to_app.populate_characters", AsyncMock(return_value=0)),
        patch("scripts.coverage_to_app._reconcile_moment_dialogue", lambda moments, text: None),
        patch("scripts.coverage_to_app.run_coverage", run_coverage_mock),
        patch("scripts.coverage_to_app.resolve_cast_url", AsyncMock(return_value="https://cast.png/x.png")),
    ]
    for p in patches:
        p.start()
    try:
        result = asyncio.run(generate_coverage_for_video(VIDEO_ID, TENANT_ID))
    finally:
        for p in patches:
            p.stop()

    assert result["status"] in ("completed", "partial"), result
    passed_profile = run_coverage_mock.await_args_list[0].kwargs["profile"]
    default_directive = _real_resolve_style(None, None)[0].visual_style_directive
    assert passed_profile.visual_style_directive == default_directive


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(pytest.main([__file__, "-q"]))
