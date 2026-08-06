"""S7-B (STORY-LAWS.md S7 — scripts.action, migration 154, the parallel S7-A
lane's ACTION: header parser in backend/story_laws.py) — the CONSUMER side:
threading the script's own authored stage direction into the LIVE storyboard
planner (scripts/coverage_to_app.py's generate_storyboard_sheet_for_scene /
_get_or_plan_directive / _scene_text_hash), plus the WARN-only presence check
(storyboard/coverage.py's check_stage_direction_presence).

STASH-PROOF: every test below imports check_stage_direction_presence, which
does not exist before this chunk — `git stash` on the two source files
(scripts/coverage_to_app.py, storyboard/coverage.py) makes this whole file
fail at COLLECTION (ImportError), the loudest possible "before" failure.

Three groups:
  1. _scene_text_hash — byte-identity with no action, and a real change
     when action is present (the DIRECTIVE HASH PIN).
  2. _get_or_plan_directive — the SAME hash-gate helper both real callers
     (SHEET path, FRAME path) share, now action-aware: a saved plan whose
     hash predates an authored action reads as stale; a saved plan whose
     hash already accounts for it reads as fresh.
  3. generate_storyboard_sheet_for_scene (the SHEET path, end to end,
     plan_only=True so the drawing machinery never engages) — the
     completion-message stage-direction warning suffix appears when the
     (fake) plan drops the authored action and is absent when the plan
     stages it, and is absent entirely for a legacy scene with no action
     (byte-identical to before this chunk).

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_s7_b_stage_directions.py -q
"""
import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
_PIPELINE_PATH = os.path.join(_BACKEND, "..", "..", "..", "skills", "video-pipeline")
sys.path.insert(0, os.path.abspath(_BACKEND))
sys.path.insert(0, os.path.abspath(_PIPELINE_PATH))

import scripts.coverage_to_app as cta  # noqa: E402
from scripts.coverage_to_app import (  # noqa: E402
    _scene_text_hash, _get_or_plan_directive, generate_storyboard_sheet_for_scene,
)
from storyboard.coverage import check_stage_direction_presence  # noqa: E402

VIDEO_ID = "video-s7b"
TENANT_ID = "tenant-s7b"
SCENE = 1

SCENE_TEXT = "Ryan greets Vanessa in the kitchen as morning light comes through the window."
# Deliberately no overlap with the "drops" fixture's own wording below (no
# shared character names either) so a content-word match can only happen
# when a shot description genuinely stages this direction.
ACTION_TEXT = "A stray cat leaps onto the windowsill."


def _run(coro):
    return asyncio.run(coro)


# =============================================================================
# 1. _scene_text_hash — the DIRECTIVE HASH PIN
# =============================================================================

def test_hash_byte_identical_with_no_action_arg():
    """A caller that never passes `action` at all (every call site before
    this chunk) gets the exact hash it always got."""
    assert _scene_text_hash(SCENE_TEXT) == _scene_text_hash(SCENE_TEXT)


def test_hash_byte_identical_when_action_is_none():
    assert _scene_text_hash(SCENE_TEXT, None) == _scene_text_hash(SCENE_TEXT)


def test_hash_byte_identical_when_action_is_blank_string():
    assert _scene_text_hash(SCENE_TEXT, "   ") == _scene_text_hash(SCENE_TEXT)


def test_hash_changes_when_action_present():
    with_action = _scene_text_hash(SCENE_TEXT, ACTION_TEXT)
    without_action = _scene_text_hash(SCENE_TEXT)
    assert with_action != without_action, (
        "an authored action must change the hash so a plan saved before it "
        "existed reads as stale")


def test_hash_deterministic_for_the_same_action():
    assert _scene_text_hash(SCENE_TEXT, ACTION_TEXT) == _scene_text_hash(SCENE_TEXT, ACTION_TEXT)


def test_hash_differs_for_different_actions():
    a = _scene_text_hash(SCENE_TEXT, "Ryan waves.")
    b = _scene_text_hash(SCENE_TEXT, "Vanessa laughs.")
    assert a != b


# =============================================================================
# 2. _get_or_plan_directive — action folded into the SAME freshness gate
# =============================================================================

def _gate_fetch_one(*, saved_hash):
    async def fake(query, *args):
        if "coverage_directive, coverage_directive_hash" in query and "FROM scripts" in query:
            return {"id": "script-1", "coverage_directive": "[MOMENT 1 | x]\n- MASTER [WS]: a.\n",
                    "coverage_directive_hash": saved_hash}
        raise AssertionError(f"unexpected fetch_one: {query}")
    return fake


def test_get_or_plan_directive_stale_when_saved_hash_predates_the_action():
    """The saved plan was hashed BEFORE the script had an authored action
    (hash == _scene_text_hash(scene_text) alone). A caller that now passes
    the authored action must see it as STALE — the composed hash no longer
    matches — so the scene gets replanned with the DECLARED STAGE
    DIRECTIONS block instead of silently reusing an outdated plan."""
    saved_hash = _scene_text_hash(SCENE_TEXT)  # planned before the action existed
    with patch.object(cta, "fetch_one", _gate_fetch_one(saved_hash=saved_hash)):
        gate = _run(_get_or_plan_directive(VIDEO_ID, TENANT_ID, SCENE, SCENE_TEXT,
                                           action=ACTION_TEXT))
    assert gate["directive"] is None
    assert gate["is_reused"] is False


def test_get_or_plan_directive_fresh_when_saved_hash_already_includes_the_same_action():
    saved_hash = _scene_text_hash(SCENE_TEXT, ACTION_TEXT)  # planned WITH the action
    with patch.object(cta, "fetch_one", _gate_fetch_one(saved_hash=saved_hash)):
        gate = _run(_get_or_plan_directive(VIDEO_ID, TENANT_ID, SCENE, SCENE_TEXT,
                                           action=ACTION_TEXT))
    assert gate["directive"] is not None
    assert gate["is_reused"] is True


def test_get_or_plan_directive_no_action_kwarg_is_byte_identical_to_before():
    """A caller that omits `action` entirely (every pre-S7-B call site)
    still reuses a plan hashed the old (scene_text-only) way — the default
    changes nothing for it."""
    saved_hash = _scene_text_hash(SCENE_TEXT)
    with patch.object(cta, "fetch_one", _gate_fetch_one(saved_hash=saved_hash)):
        gate = _run(_get_or_plan_directive(VIDEO_ID, TENANT_ID, SCENE, SCENE_TEXT))
    assert gate["directive"] is not None
    assert gate["is_reused"] is True


def test_get_or_plan_directive_empty_action_same_as_none():
    saved_hash = _scene_text_hash(SCENE_TEXT)
    with patch.object(cta, "fetch_one", _gate_fetch_one(saved_hash=saved_hash)):
        gate = _run(_get_or_plan_directive(VIDEO_ID, TENANT_ID, SCENE, SCENE_TEXT, action=""))
    assert gate["is_reused"] is True


# =============================================================================
# 3. generate_storyboard_sheet_for_scene — end-to-end completion suffix
# =============================================================================

def _video_row():
    return {
        "id": VIDEO_ID, "tenant_id": TENANT_ID, "video_title": "Test Video",
        "aspect": "16:9", "image_style_override": None, "visual_style": None,
        "style_preset_id": None, "render_style": None, "video_model": "grok-imagine",
        "dialogue_audio": "voice_over", "production_style_snapshot": None,
    }


class _FakeDB:
    """No saved plan for any scene (coverage_directive/hash both None) — every
    scene is unconditionally freshly planned, so generate_coverage_directive
    (mocked below) always runs and its canned return value is what
    plan_moments_deterministic parses."""

    def __init__(self, scene_row):
        self.scene_row = scene_row

    async def fetch_one(self, query, *args):
        if "FROM videos WHERE id=$1" in query:
            return _video_row()
        if "coverage_directive, coverage_directive_hash" in query and "FROM scripts" in query:
            return {"id": "script-1", "coverage_directive": None, "coverage_directive_hash": None}
        raise AssertionError(f"unexpected fetch_one: {query}")

    async def fetch_all(self, query, *args):
        if "FROM scripts WHERE video_id=$1 AND tenant_id=$2 AND scene IS NOT NULL " \
           "AND scene_text IS NOT NULL ORDER BY scene" in query:
            return [self.scene_row]
        if "FROM video_characters" in query:
            return []
        raise AssertionError(f"unexpected fetch_all: {query}")

    async def execute(self, query, *args):
        return "OK"


# Deliberately NO mention of the authored action's content words ("stray",
# "cat", "leaps", "windowsill") anywhere in the shot description — the "plan
# drops the directed action" fixture.
DIRECTIVE_DROPS_ACTION = (
    "[MOMENT 1 | Ryan greets Vanessa]\n"
    "- MASTER [WS]: Wide shot of Ryan smiling warmly at Vanessa across the kitchen island.\n"
)

# The shot description explicitly stages the authored action — the "plan
# stages the directed action" fixture.
DIRECTIVE_STAGES_ACTION = (
    "[MOMENT 1 | Ryan greets Vanessa]\n"
    "- MASTER [WS]: Wide shot of a stray cat leaping onto the sunlit windowsill behind them.\n"
)


def _run_sheet(scene_row, directive_text, *, plan_only=True):
    directive_calls = []

    async def fake_generate_directive(*args, **kwargs):
        directive_calls.append(kwargs)
        return directive_text

    fakedb = _FakeDB(scene_row)
    fake_prompts = ["board 1 prompt"]
    patches = [
        patch.object(cta, "fetch_one", fakedb.fetch_one),
        patch.object(cta, "fetch_all", fakedb.fetch_all),
        patch.object(cta, "execute", fakedb.execute),
        patch.object(cta, "get_secret", AsyncMock(return_value="fake-kie-key")),
        patch.object(cta, "get_text_client_for_tenant", AsyncMock(return_value=object())),
        patch.object(cta, "claude_model_for_direct_client", lambda c: "fake-model"),
        patch.object(cta, "scene_aware_bible", AsyncMock(return_value=None)),
        patch.object(cta, "_approved_envs", AsyncMock(return_value=[])),
        patch.object(cta, "generate_coverage_directive", fake_generate_directive),
        patch.object(cta, "_plan_sheet_prompts", lambda *a, **k: list(fake_prompts)),
        patch.object(cta, "sheet_chunk_sizes", lambda *a, **k: [1]),
        # plan_only=False path only: drawing machinery, never reached when
        # plan_only=True but harmless to have patched either way.
        patch.object(cta, "generate_scene_image_for_model",
                     AsyncMock(return_value=("https://fake/board.png", "gpt-image-2"))),
        patch.object(cta, "_stable_url", AsyncMock(return_value="https://stable/final.png")),
        patch.object(cta, "record_ledger_entry", AsyncMock(return_value=None)),
    ]
    for p in patches:
        p.start()
    try:
        result = _run(generate_storyboard_sheet_for_scene(
            VIDEO_ID, TENANT_ID, scene=SCENE, plan_only=plan_only))
    finally:
        for p in patches:
            p.stop()
    return result, directive_calls


def test_stage_direction_warning_suffix_present_when_plan_drops_the_action():
    scene_row = {"scene": SCENE, "scene_text": SCENE_TEXT, "location": None, "action": ACTION_TEXT}
    result, calls = _run_sheet(scene_row, DIRECTIVE_DROPS_ACTION)
    assert result["status"] == "completed", result
    assert "1 stage-direction warning(s) — see logs" in result["message"], result["message"]
    # generate_coverage_directive received the authored action, so the
    # DECLARED STAGE DIRECTIONS block genuinely reached the planner.
    assert calls[0]["action"] == ACTION_TEXT


def test_stage_direction_warning_suffix_absent_when_plan_stages_the_action():
    scene_row = {"scene": SCENE, "scene_text": SCENE_TEXT, "location": None, "action": ACTION_TEXT}
    result, calls = _run_sheet(scene_row, DIRECTIVE_STAGES_ACTION)
    assert result["status"] == "completed", result
    assert "stage-direction warning" not in result["message"], result["message"]
    assert calls[0]["action"] == ACTION_TEXT


def test_stage_direction_warning_suffix_absent_for_legacy_scene_with_no_action():
    """A scene with no authored ACTION (action=None, every scene before
    migration 154, and any scene the creator never authors one for) never
    triggers the check — no suffix, exactly as if this chunk never
    existed."""
    scene_row = {"scene": SCENE, "scene_text": SCENE_TEXT, "location": None, "action": None}
    result, calls = _run_sheet(scene_row, DIRECTIVE_DROPS_ACTION)
    assert result["status"] == "completed", result
    assert "stage-direction warning" not in result["message"], result["message"]
    assert calls[0]["action"] is None


def test_stage_direction_warning_suffix_absent_when_action_column_missing_entirely():
    """A scene row fetched before migration 154 ships has no "action" key at
    all (dict.get returns None) — must not raise, must behave exactly like
    the explicit-None case above."""
    scene_row = {"scene": SCENE, "scene_text": SCENE_TEXT, "location": None}
    result, calls = _run_sheet(scene_row, DIRECTIVE_DROPS_ACTION)
    assert result["status"] == "completed", result
    assert "stage-direction warning" not in result["message"], result["message"]


# =============================================================================
# check_stage_direction_presence — imported here too so this file alone is
# STASH-PROOF even if the skills-side test file is skipped for some reason.
# =============================================================================

def test_check_stage_direction_presence_none_action_is_zero():
    assert check_stage_direction_presence(None, []) == 0
    assert check_stage_direction_presence("", []) == 0


def test_check_stage_direction_presence_warns_when_dropped():
    moments = [{
        "props": [], "angles": [],
        "master": {"description": "Wide shot of Ryan smiling warmly at Vanessa."},
    }]
    assert check_stage_direction_presence(ACTION_TEXT, moments) == 1


def test_check_stage_direction_presence_zero_when_staged():
    moments = [{
        "props": [], "angles": [],
        "master": {"description": "Wide shot of a stray cat leaping onto the windowsill."},
    }]
    assert check_stage_direction_presence(ACTION_TEXT, moments) == 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
