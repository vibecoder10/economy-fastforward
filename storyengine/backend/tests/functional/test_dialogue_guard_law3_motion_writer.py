"""LAW 3c (video f00ea79a scene 1): scripts/coverage_to_app.py's
_write_motion_prompts() must thread the channel's tone hint
(channel_identity.voice_tone, via channel_format.get_channel_tone) into the
motion-writer's USER message when one is on file, and leave the message
byte-identical to before this law when none is set.

Split into its own file (rather than living alongside
test_dialogue_guard_laws.py's pipeline_executor-based LAW 1/2 tests): it
needs sys.modules stubs for database/storage/vault/kie_unified to import
scripts.coverage_to_app cheaply (same reasoning and pattern as
tests/functional/test_motion_prompt_presence_gate.py), and tests/conftest.py
isolates each test FILE's module-level stubs to that file alone — stubbing
`vault` here would otherwise leak into another file's real-vault-dependent
tests if they shared a module.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_dialogue_guard_law3_motion_writer.py -q
"""
import asyncio
import os
import sys
import types
from unittest.mock import AsyncMock, patch

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


# Placeholders at import time — every real test overrides fetch_one/fetch_all/
# execute via patch("scripts.coverage_to_app.X", ...) (mirrors
# test_motion_prompt_presence_gate.py's pattern).
_stub("database", fetch_one=_boom, fetch_all=_boom, execute=_boom)
_stub("storage", upload_bytes=_boom)
_stub("vault", get_secret=_boom)
_stub("kie_unified", get_text_client_for_tenant=_boom)

from scripts.coverage_to_app import _write_motion_prompts  # noqa: E402
import channel_format  # noqa: E402

VIDEO_ID = "11111111-1111-1111-1111-111111111111"
TENANT_ID = "tenant-1"
SCENE = 1

_ROW = {
    "id": "asset-1", "shot_type": "MS", "image_prompt": "Ryan in the kitchen, Vanessa beside him",
    "sentence_text": "Ryan smiles at the surprise.",
    "assigned_dialogue": None, "camera_movement": None,
}


def _run_write_motion_prompts_with_tone(tone):
    captured = []

    async def fake_generate(**kw):
        captured.append(kw.get("prompt"))
        return "1. Camera holds steady on Ryan, framing a quiet reaction."

    claude = AsyncMock()
    claude.generate = AsyncMock(side_effect=fake_generate)

    fetch_all_mock = AsyncMock(return_value=[dict(_ROW)])
    fetch_one_mock = AsyncMock(return_value={"scene_text": "A quiet family moment."})
    execute_mock = AsyncMock(return_value="OK")

    with patch("scripts.coverage_to_app.fetch_all", fetch_all_mock), \
         patch("scripts.coverage_to_app.fetch_one", fetch_one_mock), \
         patch("scripts.coverage_to_app.execute", execute_mock), \
         patch("channel_format.get_channel_tone", AsyncMock(return_value=tone)):
        asyncio.run(_write_motion_prompts(VIDEO_ID, TENANT_ID, SCENE, claude))

    assert captured, "claude.generate must have been called with the user prompt"
    return captured[0]


def test_motion_writer_user_message_includes_tone_when_set():
    user_msg = _run_write_motion_prompts_with_tone("playful and comedic")
    assert ('CHANNEL TONE: playful and comedic — all performance and delivery '
            'directions must match this tone.') in user_msg


def test_motion_writer_user_message_unchanged_when_tone_absent():
    user_msg = _run_write_motion_prompts_with_tone(None)
    assert "CHANNEL TONE" not in user_msg
