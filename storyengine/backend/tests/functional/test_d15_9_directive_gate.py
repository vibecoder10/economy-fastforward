"""D15-9 (closes the D15 ONE ROAD series): ONE _get_or_plan_directive helper
replacing the duplicated hash-gate blocks — D15-1's "duplicated hash-gate
blocks" finding. Before this chunk, generate_storyboard_sheet_for_scene's
per-board redo branch (assembler A, beat != None) and generate_coverage_
for_video's whole reuse gate (assembler B) each carried their own hand-copied
"fetch the scene's saved scripts row, then decide whether coverage_directive
is still fresh relative to scene_text" block (D15-2's own docstring calls
this out: "mirrors the sheet path's own persist"). scripts.coverage_to_app.
_get_or_plan_directive is now the ONE place that predicate is evaluated —
both call sites, and by extension D7-3 staleness (routes/videos.py's
_clear_scene_downstream, which nulls exactly the coverage_directive_hash
column this helper reads) and D8/D9 judging (frame_arbiter_hook.py, which
reads storyboard_prompts — a downstream artifact ONLY assembler A ever
writes, so it already agreed with A's plan before and after this chunk),
now see ONE verdict for a given scene.

DOCUMENTED EXCEPTION: assembler A's MAIN plan-the-scene branch (beat is
None) deliberately does NOT call this gate — confirmed live
(ScenesWorkspaceTab.tsx's "Regenerate storyboard" button, tooltip "after
changing the cast, environments, or script") that a re-plan must be able to
reflect a cast/environment change even though coverage_directive_hash is
scoped to scene TEXT only. Wiring reuse into that branch would silently
freeze that button's own documented use case — a real behavior change, not
a safe convergence, so it was left alone. See _get_or_plan_directive's own
docstring for the same note at the source.

This file proves:
  (1) _get_or_plan_directive's freshness predicate across the golden
      4-state matrix (no row / blank directive / hash mismatch / hash
      match), and that its `extra_columns` param reproduces each real
      caller's ORIGINAL exact SQL text byte-for-byte — so every pre-existing
      test pinned to that text (test_d15_2/_3/_7/_8, test_c16b,
      test_c25a_fix7, test_d10_3a, test_d3_59, test_d6_1b) keeps matching
      with zero changes (independently re-run, still green — see the D15-9
      chunk report for the exact command).
  (2) Wiring-spy: both real call sites actually delegate to the helper
      (fails if either reverts to its own inline fetch_one + hash compare).
  (3) Guard-neuter: swapping in a neutered helper (always reports "not
      fresh") turns the SAME behavioral assertions red with real
      AssertionErrors — proving (2) isn't vacuous.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_d15_9_directive_gate.py -q
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
    _get_or_plan_directive,
    _scene_text_hash,
)

VIDEO_ID = "44444444-4444-4444-4444-444444444444"
TENANT_ID = "tenant-d15-9"
SCRIPT_ROW_ID = "script-row-d15-9"
SCENE = 1

SCENE_TEXT = "The elevator stalls between floors as the lights flicker out."
SCENE_HASH = _scene_text_hash(SCENE_TEXT)
STALE_HASH = "deadbeef" * 5

DIRECTIVE = (
    "[MOMENT 1 | the elevator stalls]\n"
    "- MASTER [WS]: Wide shot of the stalled elevator car, red emergency light glowing.\n"
    "- ANGLE [MCU]: Close on a hand pressing the call button in the dark.\n"
)


def _video_row(**extra):
    row = {
        "id": VIDEO_ID, "tenant_id": TENANT_ID, "video_title": "D15-9 Video",
        "aspect": "16:9", "image_style_override": None, "visual_style": None,
        "style_preset_id": None, "image_model_override": None, "render_style": None,
        "video_model": "grok-imagine", "dialogue_audio": "voice_over",
    }
    row.update(extra)
    return row


def _saved_row(directive=None, hash_value=None, boards=False):
    row = {"id": SCRIPT_ROW_ID, "coverage_directive": directive, "coverage_directive_hash": hash_value}
    if boards:
        row.update({
            "storyboard_prompts": "--- BEAT 1 ---\nboard 1 prompt",
            "storyboard_1_url": "https://boards/1.png", "storyboard_2_url": None,
            "storyboard_3_url": None, "storyboard_4_url": None, "storyboard_5_url": None,
        })
    else:
        row.update({
            "storyboard_prompts": None, "storyboard_1_url": None, "storyboard_2_url": None,
            "storyboard_3_url": None, "storyboard_4_url": None, "storyboard_5_url": None,
        })
    return row


# =============================================================================
# (1) _get_or_plan_directive — golden 4-state matrix + SQL-text exactness
# =============================================================================

EXPECTED_A_SQL = (
    "SELECT id, coverage_directive, coverage_directive_hash FROM scripts "
    "WHERE video_id=$1 AND tenant_id=$2 AND scene=$3"
)
EXPECTED_B_EXTRA_COLUMNS = (
    ", storyboard_prompts, storyboard_1_url, storyboard_2_url, "
    "storyboard_3_url, storyboard_4_url, storyboard_5_url"
)
EXPECTED_B_SQL = (
    "SELECT id, coverage_directive, coverage_directive_hash, storyboard_prompts, "
    "storyboard_1_url, storyboard_2_url, storyboard_3_url, storyboard_4_url, "
    "storyboard_5_url FROM scripts WHERE video_id=$1 AND tenant_id=$2 AND scene=$3"
)


def test_default_extra_columns_reproduces_assembler_a_sql_byte_for_byte():
    """extra_columns="" (assembler A's beat-redo call) must emit the EXACT
    original 3-column SELECT text every pre-existing A-side test mock is
    pinned to (see the module docstring's file list)."""
    seen = {}

    async def fetch_one(query, *args):
        seen["query"] = query
        seen["args"] = args
        return _saved_row(directive=DIRECTIVE, hash_value=SCENE_HASH)

    with patch("scripts.coverage_to_app.fetch_one", fetch_one):
        result = asyncio.run(_get_or_plan_directive(VIDEO_ID, TENANT_ID, SCENE, SCENE_TEXT))

    assert seen["query"] == EXPECTED_A_SQL, seen["query"]
    assert seen["args"] == (VIDEO_ID, TENANT_ID, SCENE)
    assert result["directive"] == DIRECTIVE
    assert result["is_reused"] is True


def test_boards_extra_columns_reproduces_assembler_b_sql_byte_for_byte():
    """extra_columns=<board-anchor columns> (assembler B's whole-gate call)
    must emit the EXACT original 9-column SELECT text every pre-existing
    B-side test mock is pinned to."""
    seen = {}

    async def fetch_one(query, *args):
        seen["query"] = query
        return _saved_row(directive=None, hash_value=None, boards=True)

    with patch("scripts.coverage_to_app.fetch_one", fetch_one):
        asyncio.run(_get_or_plan_directive(
            VIDEO_ID, TENANT_ID, SCENE, SCENE_TEXT, extra_columns=EXPECTED_B_EXTRA_COLUMNS))

    assert seen["query"] == EXPECTED_B_SQL, seen["query"]


def test_no_row_is_not_fresh():
    async def fetch_one(query, *args):
        return None

    with patch("scripts.coverage_to_app.fetch_one", fetch_one):
        result = asyncio.run(_get_or_plan_directive(VIDEO_ID, TENANT_ID, SCENE, SCENE_TEXT))
    assert result == {"row": None, "directive": None, "is_reused": False}


def test_blank_directive_is_not_fresh():
    async def fetch_one(query, *args):
        return _saved_row(directive="   ", hash_value=SCENE_HASH)

    with patch("scripts.coverage_to_app.fetch_one", fetch_one):
        result = asyncio.run(_get_or_plan_directive(VIDEO_ID, TENANT_ID, SCENE, SCENE_TEXT))
    assert result["directive"] is None
    assert result["is_reused"] is False
    assert result["row"] is not None, "row is returned even when its plan isn't fresh"


def test_hash_mismatch_is_not_fresh():
    """The D7-3 staleness case: a script edit nulled (or never matched) the
    hash pointer — _clear_scene_downstream's exact mechanism."""
    async def fetch_one(query, *args):
        return _saved_row(directive=DIRECTIVE, hash_value=STALE_HASH)

    with patch("scripts.coverage_to_app.fetch_one", fetch_one):
        result = asyncio.run(_get_or_plan_directive(VIDEO_ID, TENANT_ID, SCENE, SCENE_TEXT))
    assert result["directive"] is None
    assert result["is_reused"] is False


def test_matching_hash_is_fresh_and_reused():
    async def fetch_one(query, *args):
        return _saved_row(directive=DIRECTIVE, hash_value=SCENE_HASH)

    with patch("scripts.coverage_to_app.fetch_one", fetch_one):
        result = asyncio.run(_get_or_plan_directive(VIDEO_ID, TENANT_ID, SCENE, SCENE_TEXT))
    assert result["directive"] == DIRECTIVE
    assert result["is_reused"] is True


# =============================================================================
# (2) + (3) Wiring-spy + guard-neuter — assembler A (beat-redo branch)
# =============================================================================

def _make_get_or_plan_spy(*, neutered=False):
    """Delegates to the REAL _get_or_plan_directive (proving a signature
    regression would raise TypeError here, not silently pass) while
    recording every call. neutered=True post-processes the real result to
    always report "not fresh" — same row, directive/is_reused wiped — the
    guard-neuter shape: the DB truly holds a fresh plan, but the gate lies
    about it, so any caller that actually depends on the real verdict must
    now behave differently (and, if that different behavior is wrong, fail
    loudly)."""
    calls = []
    real = cta._get_or_plan_directive

    async def spy(vid, tenant, sc, scene_text, **kwargs):
        calls.append((vid, tenant, sc, scene_text, kwargs.get("extra_columns", "")))
        result = await real(vid, tenant, sc, scene_text, **kwargs)
        if neutered:
            return {"row": result["row"], "directive": None, "is_reused": False}
        return result

    return spy, calls


def _beat_redo_fakedb():
    class FakeDB:
        execute_calls: list = []

        async def fetch_one(self, query, *args):
            if "FROM videos WHERE id=$1" in query:
                return _video_row()
            if "coverage_directive, coverage_directive_hash FROM scripts" in query:
                return _saved_row(directive=DIRECTIVE, hash_value=SCENE_HASH)
            raise AssertionError(f"unexpected fetch_one: {query}")

        async def fetch_all(self, query, *args):
            # S6-A added a "location" column to this SELECT's column list
            # (scripts.location, migration 144) — match the shared WHERE
            # clause tail so this fixture is robust to the exact column list.
            if "FROM scripts WHERE video_id=$1 AND tenant_id=$2 AND scene IS NOT NULL " \
               "AND scene_text IS NOT NULL ORDER BY scene" in query:
                return [{"scene": SCENE, "scene_text": SCENE_TEXT, "location": None}]
            if "FROM video_characters" in query:
                return []
            raise AssertionError(f"unexpected fetch_all: {query}")

        async def execute(self, query, *args):
            self.execute_calls.append((query, args))
            return "OK"

    return FakeDB()


def _beat_redo_patches(fakedb, get_or_plan_fn, *, image_client_mock, board_count=2):
    fake_prompts = [f"board {i} prompt" for i in range(1, board_count + 1)]
    fake_sizes = [1] * board_count
    return [
        patch("scripts.coverage_to_app.fetch_one", fakedb.fetch_one),
        patch("scripts.coverage_to_app.fetch_all", fakedb.fetch_all),
        patch("scripts.coverage_to_app.execute", fakedb.execute),
        patch("scripts.coverage_to_app.get_secret", AsyncMock(return_value="fake-kie-key")),
        patch("scripts.coverage_to_app.get_text_client_for_tenant", AsyncMock(return_value=object())),
        patch("scripts.coverage_to_app.claude_model_for_direct_client", lambda c: "fake-model"),
        patch("scripts.coverage_to_app.scene_aware_bible", AsyncMock(return_value=None)),
        patch("scripts.coverage_to_app._approved_envs", AsyncMock(return_value=[])),
        patch("scripts.coverage_to_app._get_or_plan_directive", get_or_plan_fn),
        patch("scripts.coverage_to_app.generate_scene_image_for_model", image_client_mock),
        patch("scripts.coverage_to_app._stable_url", AsyncMock(return_value="https://stable/final.png")),
        patch("scripts.coverage_to_app.record_ledger_entry", AsyncMock(return_value=None)),
        patch("scripts.coverage_to_app._plan_sheet_prompts", lambda *a, **k: list(fake_prompts)),
        patch("scripts.coverage_to_app.sheet_chunk_sizes", lambda *a, **k: list(fake_sizes)),
    ]


def test_beat_redo_delegates_to_get_or_plan_directive_and_draws():
    """Wiring-spy (GREEN): a real, hash-matching saved plan -> the beat-redo
    branch calls _get_or_plan_directive (not its own inline fetch_one+hash
    compare) with (vid, tenant, scene, scene_text) and draws the requested
    board from the reused directive."""
    fakedb = _beat_redo_fakedb()
    spy, calls = _make_get_or_plan_spy()
    image_client = AsyncMock(return_value=("https://fake-storage.example/board.png", "gpt-image-2"))
    patches = _beat_redo_patches(fakedb, spy, image_client_mock=image_client)
    for p in patches:
        p.start()
    try:
        result = asyncio.run(generate_storyboard_sheet_for_scene(
            VIDEO_ID, TENANT_ID, scene=SCENE, beat=2))
    finally:
        for p in patches:
            p.stop()

    assert result["status"] == "completed", result
    assert calls == [(VIDEO_ID, TENANT_ID, SCENE, SCENE_TEXT, "")], (
        "generate_storyboard_sheet_for_scene must call _get_or_plan_directive "
        "with no extra_columns (its original 3-column SELECT shape)")
    image_client.assert_awaited_once()


def test_beat_redo_guard_neuter_turns_red():
    """Guard-neuter (RED): the SAME fresh, hash-matching saved plan as above,
    but the gate is neutered to always report "not fresh". The per-board
    redo branch must refuse (its documented "never re-plan" contract has no
    fresh-plan fallback), so the correct-behavior assertion above
    (status == "completed") now fails for real — proving that assertion
    actually depends on _get_or_plan_directive's real verdict, not a vacuous
    pass."""
    fakedb = _beat_redo_fakedb()
    spy, calls = _make_get_or_plan_spy(neutered=True)
    image_client = AsyncMock(
        side_effect=AssertionError("a neutered/stale gate must never reach the paid draw"))
    patches = _beat_redo_patches(fakedb, spy, image_client_mock=image_client)
    for p in patches:
        p.start()
    try:
        result = asyncio.run(generate_storyboard_sheet_for_scene(
            VIDEO_ID, TENANT_ID, scene=SCENE, beat=2))
    finally:
        for p in patches:
            p.stop()

    assert calls == [(VIDEO_ID, TENANT_ID, SCENE, SCENE_TEXT, "")]
    image_client.assert_not_awaited()
    with pytest.raises(AssertionError):
        assert result["status"] == "completed", result
    assert result["status"] == "failed"
    assert "no current plan" in result["error"]


# =============================================================================
# (2) + (3) Wiring-spy + guard-neuter — assembler B (whole reuse gate)
# =============================================================================

def _coverage_fakedb(saved_row):
    class FakeDB:
        async def fetch_one(self, query, *args):
            if "FROM videos WHERE id=$1" in query:
                return _video_row()
            if "coverage_directive_hash" in query and "FROM scripts" in query:
                return dict(saved_row) if saved_row else None
            if "FROM assets" in query and "generation_method='coverage'" in query:
                return {"n": 0}
            raise AssertionError(f"unexpected fetch_one: {query}")

        async def fetch_all(self, query, *args):
            # S6-A added a "location" column to this SELECT's column list
            # (scripts.location, migration 144) — match the shared WHERE
            # clause tail so this fixture is robust to the exact column list.
            if "FROM scripts WHERE video_id=$1 AND tenant_id=$2 AND scene IS NOT NULL " \
               "AND scene_text IS NOT NULL ORDER BY scene" in query:
                return [{"scene": SCENE, "scene_text": SCENE_TEXT, "location": None}]
            if "FROM video_characters" in query:
                return [{"reference_url": "https://cast.png/x.png"}]
            raise AssertionError(f"unexpected fetch_all: {query}")

        async def execute(self, query, *args):
            return "OK"

    return FakeDB()


def _fresh_run_coverage_output(**kwargs):
    used = kwargs.get("directive_text") or DIRECTIVE
    return {
        "moments": [{
            "summary": "the elevator stalls", "speaker": None, "line": None,
            "frames": [
                {"file": "master.png", "role": "master", "description": "wide shot", "shot_type": "WS"},
            ],
        }],
        "directive_text": used,
    }


def _coverage_patches(fakedb, get_or_plan_fn):
    run_coverage_mock = AsyncMock(side_effect=_fresh_run_coverage_output)
    patches = [
        patch("scripts.coverage_to_app.fetch_one", fakedb.fetch_one),
        patch("scripts.coverage_to_app.fetch_all", fakedb.fetch_all),
        patch("scripts.coverage_to_app.execute", fakedb.execute),
        patch("scripts.coverage_to_app.get_secret", AsyncMock(return_value="fake-kie-key")),
        patch("scripts.coverage_to_app.get_text_client_for_tenant", AsyncMock(return_value=object())),
        patch("scripts.coverage_to_app.scene_aware_bible", AsyncMock(return_value=None)),
        patch("scripts.coverage_to_app._approved_envs", AsyncMock(return_value=[])),
        patch("scripts.coverage_to_app._get_or_plan_directive", get_or_plan_fn),
        patch("scripts.coverage_to_app.run_coverage", run_coverage_mock),
        patch("scripts.coverage_to_app.resolve_cast_url", AsyncMock(return_value="https://generated-cast.png")),
        patch("scripts.coverage_to_app.store_scene", AsyncMock(return_value=1)),
        patch("scripts.coverage_to_app.set_scene_board", AsyncMock(return_value=True)),
        patch("scripts.coverage_to_app._write_motion_prompts", AsyncMock(return_value=0)),
        patch("scripts.coverage_to_app.populate_characters", AsyncMock(return_value=0)),
        patch("scripts.coverage_to_app._reconcile_moment_dialogue", lambda moments, text: None),
    ]
    return patches, run_coverage_mock


def test_coverage_for_video_delegates_to_get_or_plan_directive_and_reuses():
    """Wiring-spy (GREEN): a real, hash-matching saved plan -> generate_
    coverage_for_video calls _get_or_plan_directive (not its own inline
    fetch_one+hash compare) with the board-anchor extra_columns, and threads
    the REUSED directive straight into run_coverage (never None)."""
    saved = _saved_row(directive=DIRECTIVE, hash_value=SCENE_HASH, boards=True)
    fakedb = _coverage_fakedb(saved)
    spy, calls = _make_get_or_plan_spy()
    patches, run_coverage_mock = _coverage_patches(fakedb, spy)
    for p in patches:
        p.start()
    try:
        result = asyncio.run(generate_coverage_for_video(VIDEO_ID, TENANT_ID))
    finally:
        for p in patches:
            p.stop()

    assert result["status"] == "completed", result
    assert calls == [(VIDEO_ID, TENANT_ID, SCENE, SCENE_TEXT, EXPECTED_B_EXTRA_COLUMNS)], (
        "generate_coverage_for_video must call _get_or_plan_directive with "
        "its board-anchor extra_columns")
    run_coverage_mock.assert_awaited_once()
    assert run_coverage_mock.await_args.kwargs["directive_text"] == DIRECTIVE, (
        "a fresh, matching-hash saved directive must be REUSED, never re-planned")
    assert run_coverage_mock.await_args.kwargs["board_urls"] == ["https://boards/1.png"], (
        "board anchoring must come off the SAME row the gate fetched")


def test_coverage_for_video_guard_neuter_turns_red():
    """Guard-neuter (RED): the SAME fresh, hash-matching saved plan as above,
    but the gate is neutered to always report "not fresh". The reuse
    assertion above (directive_text == DIRECTIVE, board anchoring present)
    now fails for real: run_coverage gets directive_text=None (a wasted
    re-plan of an unchanged scene) and no board anchor — proving the GREEN
    test actually depends on the real gate, not a vacuous pass."""
    saved = _saved_row(directive=DIRECTIVE, hash_value=SCENE_HASH, boards=True)
    fakedb = _coverage_fakedb(saved)
    spy, calls = _make_get_or_plan_spy(neutered=True)
    patches, run_coverage_mock = _coverage_patches(fakedb, spy)
    for p in patches:
        p.start()
    try:
        result = asyncio.run(generate_coverage_for_video(VIDEO_ID, TENANT_ID))
    finally:
        for p in patches:
            p.stop()

    assert result["status"] == "completed", result
    assert calls == [(VIDEO_ID, TENANT_ID, SCENE, SCENE_TEXT, EXPECTED_B_EXTRA_COLUMNS)]
    run_coverage_mock.assert_awaited_once()
    with pytest.raises(AssertionError):
        assert run_coverage_mock.await_args.kwargs["directive_text"] == DIRECTIVE
    assert run_coverage_mock.await_args.kwargs["directive_text"] is None
    with pytest.raises(AssertionError):
        assert run_coverage_mock.await_args.kwargs["board_urls"] == ["https://boards/1.png"]
    assert run_coverage_mock.await_args.kwargs["board_urls"] is None


if __name__ == "__main__":
    test_default_extra_columns_reproduces_assembler_a_sql_byte_for_byte()
    test_boards_extra_columns_reproduces_assembler_b_sql_byte_for_byte()
    test_no_row_is_not_fresh()
    test_blank_directive_is_not_fresh()
    test_hash_mismatch_is_not_fresh()
    test_matching_hash_is_fresh_and_reused()
    test_beat_redo_delegates_to_get_or_plan_directive_and_draws()
    test_beat_redo_guard_neuter_turns_red()
    test_coverage_for_video_delegates_to_get_or_plan_directive_and_reuses()
    test_coverage_for_video_guard_neuter_turns_red()
    print("\nAll D15-9 tests passed.")
