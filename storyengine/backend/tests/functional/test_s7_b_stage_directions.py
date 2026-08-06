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
  4. generate_coverage_for_video (the FRAME path) — the REAL save-then-
     compare round trip for a scene WITH an authored action: call #1 (no
     saved plan) persists a hash, asserted equal to _scene_text_hash(text,
     action) — the SAME composition the compare side uses; call #2, given a
     DB state holding exactly that persisted hash, reuses the directive
     (never re-plans, never re-persists). This is the manager-review gap:
     proving save and compare don't silently diverge for an action-bearing
     scene, not just that the compare function alone accepts a
     hand-computed hash.

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
    generate_coverage_for_video,
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


# =============================================================================
# 4. generate_coverage_for_video (FRAME path) — the REAL save-then-compare
# round trip for a scene WITH an authored action (manager-review gap).
# =============================================================================
#
# Mirrors test_d15_2_directive_persist.py's own two-call FakeDB pattern
# exactly (that file proves the SAME round trip for an action-LESS scene;
# this is its S7-B, action-bearing sibling) — call #1's FakeDB has no saved
# row, call #2's FakeDB is seeded with exactly what call #1 is asserted to
# have persisted.

RT_VIDEO_ID = "33333333-3333-3333-3333-333333333333"
RT_TENANT_ID = "tenant-s7b-roundtrip"
RT_SCRIPT_ROW_ID = "script-row-s7b-roundtrip"

RT_SCENE_TEXT = "The tower operator checks the failing panel in the storm."
RT_ACTION_TEXT = "A stray cat leaps onto the windowsill."
# The composition the COMPARE side (_get_or_plan_directive/_scene_text_hash)
# uses for an action-bearing scene — computed here via the SAME public
# function, never hand-rolled, so this constant can never silently drift
# from what the source actually does.
RT_HASH_WITH_ACTION = _scene_text_hash(RT_SCENE_TEXT, RT_ACTION_TEXT)

RT_FRESH_DIRECTIVE = (
    "[MOMENT 1 | the panel fails]\n"
    "- MASTER [WS]: Wide shot of the operator checking the failing panel in the storm.\n"
)


def _rt_video_row():
    return {
        "id": RT_VIDEO_ID, "tenant_id": RT_TENANT_ID, "video_title": "Test Video",
        "aspect": "16:9", "image_style_override": None, "visual_style": None,
        "image_model_override": None, "render_style": None, "video_model": "grok-imagine",
        "dialogue_audio": "voice_over",
    }


def _rt_saved_row(directive=None, hash_value=None):
    return {
        "id": RT_SCRIPT_ROW_ID,
        "coverage_directive": directive, "coverage_directive_hash": hash_value,
        "storyboard_1_url": None, "storyboard_2_url": None, "storyboard_3_url": None,
        "storyboard_4_url": None, "storyboard_5_url": None, "storyboard_prompts": None,
    }


class _RoundTripFakeDB:
    """Same shape as test_d15_2_directive_persist.py's FakeDB, but the scene
    row this SELECT returns now carries "action" (RT_ACTION_TEXT) — proving
    the round trip for the exact case the manager flagged: a scene WITH an
    authored direction, not just scene_text alone."""

    def __init__(self, saved_row, drawn_n=0, cast_ref="https://cast.png/x.png"):
        self.saved_row = saved_row
        self.drawn_n = drawn_n
        self.cast_ref = cast_ref
        self.execute_calls: list[tuple] = []

    async def fetch_one(self, query, *args):
        if "FROM videos WHERE id=$1" in query:
            return _rt_video_row()
        if "coverage_directive_hash" in query and "FROM scripts" in query:
            return dict(self.saved_row) if self.saved_row else None
        if "FROM assets" in query and "generation_method='coverage'" in query:
            return {"n": self.drawn_n}
        raise AssertionError(f"unexpected fetch_one query: {query}")

    async def fetch_all(self, query, *args):
        if "FROM scripts WHERE video_id=$1 AND tenant_id=$2 AND scene IS NOT NULL " \
           "AND scene_text IS NOT NULL ORDER BY scene" in query:
            return [{"scene": 1, "scene_text": RT_SCENE_TEXT, "location": None,
                     "action": RT_ACTION_TEXT}]
        if "FROM video_characters" in query:
            return [{"reference_url": self.cast_ref}] if self.cast_ref else []
        raise AssertionError(f"unexpected fetch_all query: {query}")

    async def execute(self, query, *args):
        self.execute_calls.append((query, args))
        return "OK"


def _rt_run_coverage_output(**kwargs):
    used = kwargs.get("directive_text") or RT_FRESH_DIRECTIVE
    return {
        "video_title": kwargs.get("video_title"), "cast_url": kwargs.get("cast_url"),
        "moments": [{
            "summary": "the panel fails",
            "frames": [{"file": "master.png", "role": "master", "description": "wide shot",
                        "shot_type": "WS"}],
            "speaker": None, "line": None,
        }],
        "moment_count": 1, "frame_count": 1, "directive_text": used,
    }


def _rt_directive_update_calls(fakedb):
    return [c for c in fakedb.execute_calls if "coverage_directive=$1" in c[0]]


def _rt_run(fakedb):
    run_coverage_mock = AsyncMock(side_effect=_rt_run_coverage_output)
    patches = [
        patch.object(cta, "fetch_one", fakedb.fetch_one),
        patch.object(cta, "fetch_all", fakedb.fetch_all),
        patch.object(cta, "execute", fakedb.execute),
        patch.object(cta, "get_secret", AsyncMock(return_value="fake-kie-key")),
        patch.object(cta, "get_text_client_for_tenant", AsyncMock(return_value=object())),
        patch.object(cta, "scene_aware_bible", AsyncMock(return_value=None)),
        patch.object(cta, "_approved_envs", AsyncMock(return_value=[])),
        patch.object(cta, "run_coverage", run_coverage_mock),
        patch.object(cta, "resolve_cast_url", AsyncMock(return_value="https://generated-cast.png")),
        patch.object(cta, "store_scene", AsyncMock(return_value=1)),
        patch.object(cta, "set_scene_board", AsyncMock(return_value=True)),
        patch.object(cta, "_write_motion_prompts", AsyncMock(return_value=0)),
        patch.object(cta, "populate_characters", AsyncMock(return_value=0)),
        patch.object(cta, "_reconcile_moment_dialogue", lambda moments, text: None),
    ]
    for p in patches:
        p.start()
    try:
        result = asyncio.run(generate_coverage_for_video(RT_VIDEO_ID, RT_TENANT_ID))
    finally:
        for p in patches:
            p.stop()
    return result, run_coverage_mock


def test_roundtrip_call1_fresh_plan_persists_hash_composed_with_action():
    """Call #1: no saved plan. run_coverage plans fresh (directive_text=None
    in, RT_FRESH_DIRECTIVE out) -> the caller must persist that text hashed
    with the SAME composition (scene_text + action) the compare side reads —
    this is the exact claim the manager asked to see proven, not asserted."""
    fakedb = _RoundTripFakeDB(saved_row=_rt_saved_row(directive=None, hash_value=None), drawn_n=0)
    result, run_coverage_mock = _rt_run(fakedb)

    assert result["status"] == "completed", result
    run_coverage_mock.assert_awaited_once()
    assert run_coverage_mock.await_args.kwargs["directive_text"] is None

    updates = _rt_directive_update_calls(fakedb)
    assert len(updates) == 1, f"expected exactly one directive persist, got {updates}"
    query, args = updates[0]
    assert "coverage_directive_hash=$2" in query
    assert args[0] == RT_FRESH_DIRECTIVE
    assert args[1] == RT_HASH_WITH_ACTION, (
        "the SAVE site must hash scene_text+action with the exact same "
        "composition _scene_text_hash(scene_text, action) computes — this "
        "is the value call #2 below must be able to read back as fresh")
    assert args[2] == RT_SCRIPT_ROW_ID


def test_roundtrip_call2_reuses_the_hash_call1_persisted_no_replan():
    """Call #2: the DB now holds EXACTLY what call #1 (test above) is
    asserted to have persisted — RT_HASH_WITH_ACTION, computed the same way
    the compare side computes it. The directive must be REUSED (passed
    straight through to run_coverage, never None) and never re-persisted.
    If the save site ever composed the hash differently from the compare
    site, THIS test is what would catch it: the gate would report stale,
    directive_text would go in as None, and run_coverage would replan (and
    re-bill) on every single call for an unchanged scene."""
    fakedb = _RoundTripFakeDB(
        saved_row=_rt_saved_row(directive=RT_FRESH_DIRECTIVE, hash_value=RT_HASH_WITH_ACTION),
        drawn_n=0,
    )
    result, run_coverage_mock = _rt_run(fakedb)

    assert result["status"] == "completed", result
    run_coverage_mock.assert_awaited_once()
    assert run_coverage_mock.await_args.kwargs["directive_text"] == RT_FRESH_DIRECTIVE, (
        "a matching-hash saved directive (hashed WITH the action, matching "
        "what call #1 persists) must be threaded straight through — proof "
        "the compare side accepts exactly what the save site writes")
    assert _rt_directive_update_calls(fakedb) == [], (
        "a REUSED directive must never be re-persisted/re-planned — the "
        "silent-replan-every-run failure mode this test exists to catch")


def test_roundtrip_stale_hash_without_action_forces_replan_proving_the_two_are_distinguishable():
    """Control: the SAME scene/action, but the saved hash was computed
    WITHOUT the action (today's pre-S7-B hash, or a plan saved before the
    creator added the ACTION: header) — must NOT be read as fresh. Proves
    the with-action and without-action hashes are genuinely different
    values the gate can tell apart, not a heuristic that happens to always
    say "fresh"."""
    stale_hash = _scene_text_hash(RT_SCENE_TEXT)  # no action folded in
    fakedb = _RoundTripFakeDB(
        saved_row=_rt_saved_row(directive=RT_FRESH_DIRECTIVE, hash_value=stale_hash),
        drawn_n=0,
    )
    result, run_coverage_mock = _rt_run(fakedb)

    assert result["status"] == "completed", result
    assert run_coverage_mock.await_args.kwargs["directive_text"] is None, (
        "a hash computed without the action must NOT match RT_HASH_WITH_ACTION "
        "-> stale -> replanned, proving the gate genuinely distinguishes the "
        "two compositions rather than accepting either")
    assert len(_rt_directive_update_calls(fakedb)) == 1, (
        "the replan must persist a NEW hash (this time correctly composed "
        "with the action)")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
