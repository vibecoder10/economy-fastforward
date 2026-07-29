"""D3-59 (2026-07-28): plan_only must be a TRUE dry run.

Bug (found by reading generate_storyboard_sheet_for_scene, not guessed): the
STREAMING CONTRACT persist step —

    UPDATE scripts SET coverage_directive=$1, coverage_directive_hash=$2,
    storyboard_prompts=$3, storyboard_beat_count=$4, storyboard_1_url=NULL,
    storyboard_2_url=NULL, storyboard_3_url=NULL, storyboard_4_url=NULL,
    storyboard_5_url=NULL, storyboard_errors=NULL, updated_at=now() WHERE id=$5

ran unconditionally for every beat=None call, BEFORE the plan_only check.
That means a "zero-spend" plan_only=True call nulled the pointers to
already-drawn, already-paid-for board images — exactly the destructive
behavior a dry run must never have.

The fix wraps that single UPDATE in `if not plan_only:` — plan_only now
persists NOTHING (no coverage_directive overwrite, no storyboard URL
nulling, no storyboard_errors reset). The non-plan_only path is untouched:
same query text, same argument order, same columns.

These tests prove both halves with a spy on `execute` (records every call,
no real DB):
  - plan_only=True  -> execute is NEVER called at all (zero DB writes).
  - plan_only=False -> execute IS called, and the STREAMING CONTRACT
    UPDATE fires with the exact same column list/arg order as before this
    fix (byte-identical non-plan_only behavior).

generate_scene_image_for_model is mocked to land on the first attempt so
the board-draw loop succeeds without hitting the BUILD 2 sweep path (which
sleeps 90s per sweep — no test should ever trigger that for free).

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_d3_59_plan_only_dry_run.py -q
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


# Placeholders at import time; every real test overrides via patch(...).
_stub("database", fetch_one=_boom, fetch_all=_boom, execute=_boom)
_stub("storage", upload_bytes=_boom)
_stub("vault", get_secret=_boom)
_stub("kie_unified", get_text_client_for_tenant=_boom)

from scripts.coverage_to_app import (  # noqa: E402
    generate_storyboard_sheet_for_scene, _scene_text_hash,
)

VIDEO_ID = "686b4651-0000-0000-0000-000000000001"
TENANT_ID = "tenant-1"
SCRIPT_ID = "script-1"

# Same non-dialogue scene text test_c16b / test_c25a_fix7 use — _coverage_shape()
# deterministically returns (3, 2, 3, None) for it, and this directive format is
# proven to parse.
SCENE_TEXT = "The city lights flicker as rain falls onto empty streets."
DIRECTIVE = (
    "[MOMENT 1 | rain falls on empty streets]\n"
    "- MASTER [WS]: Wide shot of rain-soaked streets, neon reflections shimmering.\n"
    "- ANGLE [MCU]: Close on droplets streaking down a window pane.\n"
)


def _video_row():
    return {
        "id": VIDEO_ID, "tenant_id": TENANT_ID, "video_title": "Test Video",
        "aspect": "16:9", "image_style_override": None, "visual_style": None,
        "image_model_override": None, "render_style": None,
        "video_model": "grok-imagine", "dialogue_audio": "voice_over",
    }


class SpyDB:
    """Records every execute() call (query + args) and every fetch. No real
    DB behind it — good enough to prove call counts and exact query/arg
    shape, which is all these tests need."""

    def __init__(self):
        self.execute_calls: list = []

    async def fetch_one(self, query, *args):
        if "FROM videos WHERE id=$1" in query:
            return _video_row()
        if "coverage_directive, coverage_directive_hash FROM scripts" in query:
            return {"id": SCRIPT_ID, "coverage_directive": None,
                    "coverage_directive_hash": None}
        raise AssertionError(f"unexpected fetch_one query: {query}")

    async def fetch_all(self, query, *args):
        if "SELECT scene, scene_text FROM scripts" in query:
            return [{"scene": 1, "scene_text": SCENE_TEXT}]
        if "FROM video_characters" in query:
            return []
        raise AssertionError(f"unexpected fetch_all query: {query}")

    async def execute(self, query, *args):
        self.execute_calls.append((query, args))
        return "OK"


def _patches(spy):
    return [
        patch("scripts.coverage_to_app.fetch_one", spy.fetch_one),
        patch("scripts.coverage_to_app.fetch_all", spy.fetch_all),
        patch("scripts.coverage_to_app.execute", spy.execute),
        patch("scripts.coverage_to_app.get_secret", AsyncMock(return_value="fake-kie-key")),
        patch("scripts.coverage_to_app.get_text_client_for_tenant", AsyncMock(return_value=object())),
        patch("scripts.coverage_to_app.claude_model_for_direct_client", lambda c: "fake-model"),
        patch("scripts.coverage_to_app.scene_aware_bible", AsyncMock(return_value=None)),
        patch("scripts.coverage_to_app._approved_envs", AsyncMock(return_value=[])),
        patch("scripts.coverage_to_app.generate_coverage_directive", AsyncMock(return_value=DIRECTIVE)),
        patch("scripts.coverage_to_app.generate_scene_image_for_model",
              AsyncMock(return_value=("https://fake-storage.example/board.png", "gpt-image-2"))),
        patch("scripts.coverage_to_app._stable_url", AsyncMock(return_value="https://stable/final.png")),
        patch("scripts.coverage_to_app.record_ledger_entry", AsyncMock(return_value=None)),
    ]


def test_plan_only_true_makes_zero_db_writes():
    """The whole point of D3-59: a plan_only=True call must never call
    execute() — no coverage_directive overwrite, no storyboard URL nulling,
    no storyboard_errors reset, no ledger write. Nothing at all."""
    spy = SpyDB()
    patches = _patches(spy)
    for p in patches:
        p.start()
    try:
        result = asyncio.run(
            generate_storyboard_sheet_for_scene(VIDEO_ID, TENANT_ID, scene=1, plan_only=True))
    finally:
        for p in patches:
            p.stop()

    assert result["status"] == "completed", result
    assert "nothing drawn" in result["message"]
    assert spy.execute_calls == [], (
        f"plan_only=True must make ZERO DB writes — got {len(spy.execute_calls)}: "
        f"{[q for q, _ in spy.execute_calls]}")


def test_plan_only_false_still_persists_the_streaming_contract_update():
    """Non-plan_only behavior must be byte-identical to before this fix: the
    STREAMING CONTRACT UPDATE still fires, with the same column list and the
    same positional args (directive, hash, blocks, board_count, script_id)."""
    spy = SpyDB()
    patches = _patches(spy)
    for p in patches:
        p.start()
    try:
        result = asyncio.run(
            generate_storyboard_sheet_for_scene(VIDEO_ID, TENANT_ID, scene=1, plan_only=False))
    finally:
        for p in patches:
            p.stop()

    assert result["status"] == "completed", result

    streaming_contract_calls = [
        (q, a) for q, a in spy.execute_calls
        if "storyboard_1_url=NULL" in q and "storyboard_errors=NULL" in q
    ]
    assert len(streaming_contract_calls) == 1, (
        f"expected exactly one STREAMING CONTRACT UPDATE, got "
        f"{len(streaming_contract_calls)}: {spy.execute_calls}")
    query, args = streaming_contract_calls[0]
    assert query == (
        "UPDATE scripts SET coverage_directive=$1, coverage_directive_hash=$2, "
        "storyboard_prompts=$3, storyboard_beat_count=$4, storyboard_1_url=NULL, "
        "storyboard_2_url=NULL, storyboard_3_url=NULL, storyboard_4_url=NULL, "
        "storyboard_5_url=NULL, storyboard_errors=NULL, updated_at=now() WHERE id=$5"
    )
    expected_hash = _scene_text_hash(SCENE_TEXT)
    assert args[0] == DIRECTIVE
    assert args[1] == expected_hash
    assert isinstance(args[2], str) and "BEAT 1" in args[2]  # blocks
    assert args[3] == 1  # one board's worth of prompts for this DIRECTIVE
    assert args[4] == SCRIPT_ID

    # At least one DB write happened (the draw path is fully exercised, not
    # skipped) — proves this test isn't accidentally taking the plan_only
    # short-circuit.
    assert spy.execute_calls, "plan_only=False must still write to the DB"


if __name__ == "__main__":
    test_plan_only_true_makes_zero_db_writes()
    test_plan_only_false_still_persists_the_streaming_contract_update()
    print("OK")
