"""Tests for D15-2 (loop-checklist chunk "persist the directive everywhere",
Ryan's "different storyboard every time" root cause).

Confirmed live by the D15-1 sweep: inside coverage_to_app.py's
generate_coverage_for_video, when a scene has no persisted/matching directive
(no saved row, or the script changed since the last plan), `directive` stays
None going into run_coverage() — which then plans one FRESH internally via
generate_coverage_directive (skills/video-pipeline/storyboard/coverage.py:
~4803-4808 — see D15-2's own test_run_coverage_exposes_the_directive_it_
planned_internally in skills/video-pipeline/tests/test_coverage.py for the
proof at that layer). That freshly-planned directive was never written back
to scripts.coverage_directive/coverage_directive_hash — so the NEXT call for
that exact same (unchanged) scene text found nothing to reuse and re-planned
from scratch, landing on a different shot list every single run. The sheet
path (generate_storyboard_sheet_for_scene, coverage_to_app.py:3119-3126)
already persisted correctly; this fix mirrors it into the PICTURES path.

This file proves, at the generate_coverage_for_video layer (the real caller
that owns the persist decision — the actual internal-LLM-call proof lives one
layer down, in skills/video-pipeline/tests/test_coverage.py):

  (a) A fresh plan (no saved row at all) persists the directive text
      run_coverage actually used, plus its hash, via the SAME hash function
      (_scene_text_hash) and UPDATE shape (coverage_directive/
      coverage_directive_hash + updated_at, keyed on the scripts row id) the
      sheet path already uses.
  (b) A SECOND call, now with that persisted directive present under a
      MATCHING hash, reuses it: run_coverage is invoked with directive_text
      equal to the persisted text (never None) — the C16b skip-if-done gate
      and the reuse branch both engage, and the fresh-plan persist does NOT
      fire again (no second coverage_directive UPDATE).
  (c) The stored-directive branch (a saved, hash-matching directive from the
      very first call) never re-writes it — no coverage_directive UPDATE at
      all when nothing was freshly planned.
  (d) A persist failure (execute() raises) is advisory only — the scene's
      frames still land and the run still reports "completed"; only a
      progress note mentions the miss.
  (e) Legacy behavior (a directive already exists and matches) is byte-
      identical to pre-D15-2: same result message, same run_coverage
      call shape, no extra DB writes.

No network, no real DB, no real LLM: same module-stub + FakeDB pattern as
tests/functional/test_c16b_coverage_skip_if_done.py (which this file
deliberately mirrors — D15-2 sits directly on top of C16b's skip-if-done
gate). run_coverage() is patched to a recording AsyncMock that returns its
own directive_text kwarg back out (mirroring the REAL run_coverage's new
D15-2 return-shape addition), so these tests exercise ONLY the caller-side
persist decision this chunk adds, never the real paid draw or the real
planner LLM.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_d15_2_directive_persist.py -q
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


# Placeholders at import time; every real test overrides fetch_one/fetch_all/
# execute/get_secret/get_text_client_for_tenant via patch("scripts.coverage_to_app.X", ...).
# A second import of this module (if test_c16b_coverage_skip_if_done.py already
# ran in the same session) is harmless — re-stubbing is idempotent.
_stub("database", fetch_one=_boom, fetch_all=_boom, execute=_boom)
_stub("storage", upload_bytes=_boom)
_stub("vault", get_secret=_boom)
_stub("kie_unified", get_text_client_for_tenant=_boom)

from scripts.coverage_to_app import (  # noqa: E402
    generate_coverage_for_video,
    _scene_text_hash,
)

VIDEO_ID = "22222222-2222-2222-2222-222222222222"
TENANT_ID = "tenant-d15-2"
SCRIPT_ROW_ID = "script-row-scene-1"

SCENE_TEXT = "The signal drops as the tower loses power in the storm."
SCENE_HASH = _scene_text_hash(SCENE_TEXT)

FRESH_DIRECTIVE = (
    "[MOMENT 1 | the tower loses power]\n"
    "- MASTER [WS]: Wide shot of the tower silhouette against the storm.\n"
    "- ANGLE [MCU]: Close on the operator's face lit by the failing panel.\n"
)


def _video_row():
    return {
        "id": VIDEO_ID, "tenant_id": TENANT_ID, "video_title": "Test Video",
        "aspect": "16:9", "image_style_override": None, "visual_style": None,
        "image_model_override": None, "render_style": None, "video_model": "grok-imagine",
        "dialogue_audio": "voice_over",
    }


def _saved_row(directive=None, hash_value=None):
    """Mirrors the SELECT generate_coverage_for_video issues after D15-2 added
    `id` to it — every test constructs the row it wants `saved` to resolve to."""
    return {
        "id": SCRIPT_ROW_ID,
        "coverage_directive": directive, "coverage_directive_hash": hash_value,
        "storyboard_1_url": None, "storyboard_2_url": None, "storyboard_3_url": None,
        "storyboard_4_url": None, "storyboard_5_url": None, "storyboard_prompts": None,
    }


class FakeDB:
    def __init__(self, saved_row, drawn_n=0, cast_ref="https://cast.png/x.png",
                 execute_raises=False):
        self.saved_row = saved_row
        self.drawn_n = drawn_n
        self.cast_ref = cast_ref
        self.execute_raises = execute_raises
        self.execute_calls: list[tuple] = []  # every (query, args) execute() saw

    async def fetch_one(self, query, *args):
        if "FROM videos WHERE id=$1" in query:
            return _video_row()
        if "coverage_directive_hash" in query and "FROM scripts" in query:
            return dict(self.saved_row) if self.saved_row else None
        if "FROM assets" in query and "generation_method='coverage'" in query:
            return {"n": self.drawn_n}
        raise AssertionError(f"unexpected fetch_one query: {query}")

    async def fetch_all(self, query, *args):
        # S7-B added "location, action" to this SELECT's column list —
        # match the shared WHERE clause tail so this fixture is robust to
        # the exact column list, same precedent test_d15_9_directive_gate.py
        # already set for S6-A's own column addition.
        if "FROM scripts WHERE video_id=$1 AND tenant_id=$2 AND scene IS NOT NULL " \
           "AND scene_text IS NOT NULL ORDER BY scene" in query:
            return [{"scene": 1, "scene_text": SCENE_TEXT}]
        if "FROM video_characters" in query:
            return [{"reference_url": self.cast_ref}] if self.cast_ref else []
        raise AssertionError(f"unexpected fetch_all query: {query}")

    async def execute(self, query, *args):
        self.execute_calls.append((query, args))
        if "coverage_directive" in query and self.execute_raises:
            raise RuntimeError("simulated DB write failure")
        return "OK"


def _fresh_run_coverage_output(**kwargs):
    """Mirrors the REAL run_coverage's D15-2 addition: out["directive_text"]
    echoes back exactly the directive_text this call was given, generating one
    (FRESH_DIRECTIVE) when the caller passed None — matching the real
    function's `if directive_text is None: directive_text = await
    generate_coverage_directive(...)` branch, without touching a real LLM."""
    used = kwargs.get("directive_text") or FRESH_DIRECTIVE
    return {
        "video_title": kwargs.get("video_title"),
        "cast_url": kwargs.get("cast_url"),
        "moments": [{
            "summary": "the tower loses power",
            "frames": [
                {"file": "master.png", "role": "master", "description": "wide shot", "shot_type": "WS"},
                {"file": "angle.png", "role": "angle", "description": "close shot", "shot_type": "MCU"},
            ],
            "speaker": None, "line": None,
        }],
        "moment_count": 1, "frame_count": 2,
        "directive_text": used,
    }


def _patch_noop_helpers():
    return [
        patch("scripts.coverage_to_app.get_secret", AsyncMock(return_value="fake-kie-key")),
        patch("scripts.coverage_to_app.get_text_client_for_tenant", AsyncMock(return_value=object())),
        patch("scripts.coverage_to_app.scene_aware_bible", AsyncMock(return_value=None)),
        patch("scripts.coverage_to_app._approved_envs", AsyncMock(return_value=[])),
        patch("scripts.coverage_to_app.store_scene", AsyncMock(return_value=2)),
        patch("scripts.coverage_to_app.set_scene_board", AsyncMock(return_value=True)),
        patch("scripts.coverage_to_app._write_motion_prompts", AsyncMock(return_value=0)),
        patch("scripts.coverage_to_app.populate_characters", AsyncMock(return_value=0)),
        patch("scripts.coverage_to_app._reconcile_moment_dialogue", lambda moments, text: None),
    ]


def _run(fakedb, **kwargs):
    run_coverage_mock = AsyncMock(side_effect=_fresh_run_coverage_output)
    patches = _patch_noop_helpers() + [
        patch("scripts.coverage_to_app.fetch_one", fakedb.fetch_one),
        patch("scripts.coverage_to_app.fetch_all", fakedb.fetch_all),
        patch("scripts.coverage_to_app.execute", fakedb.execute),
        patch("scripts.coverage_to_app.run_coverage", run_coverage_mock),
        patch("scripts.coverage_to_app.resolve_cast_url", AsyncMock(return_value="https://generated-cast.png")),
    ]
    for p in patches:
        p.start()
    try:
        result = asyncio.run(generate_coverage_for_video(VIDEO_ID, TENANT_ID, **kwargs))
    finally:
        for p in patches:
            p.stop()
    return result, run_coverage_mock


def _directive_update_calls(fakedb):
    return [c for c in fakedb.execute_calls if "coverage_directive=$1" in c[0]]


# ---------------------------------------------------------------------------
# (a) Fresh-plan branch persists directive + hash
# ---------------------------------------------------------------------------

def test_fresh_plan_persists_directive_and_hash():
    """The scripts row exists (script-writing already inserted it — every
    real target scene's row does) but its coverage_directive/hash are still
    NULL: never planned before. run_coverage plans fresh (directive_text=None
    in, FRESH_DIRECTIVE out) -> the caller must write that exact text back,
    hashed with the SAME _scene_text_hash the reuse gate reads."""
    fakedb = FakeDB(saved_row=_saved_row(directive=None, hash_value=None), drawn_n=0)
    result, run_coverage_mock = _run(fakedb)

    assert result["status"] == "completed"
    run_coverage_mock.assert_awaited_once()
    assert run_coverage_mock.await_args.kwargs["directive_text"] is None, (
        "no saved directive -> the caller must pass None, letting run_coverage plan fresh")

    updates = _directive_update_calls(fakedb)
    assert len(updates) == 1, f"expected exactly one directive persist, got {updates}"
    query, args = updates[0]
    assert "coverage_directive_hash=$2" in query
    assert "updated_at=now()" in query
    assert args[0] == FRESH_DIRECTIVE, "must persist the directive run_coverage ACTUALLY used"
    assert args[1] == SCENE_HASH, "must hash with the same _scene_text_hash the reuse gate reads"
    assert args[2] == SCRIPT_ROW_ID, "must target the scene's own scripts row"
    print("✅ test_fresh_plan_persists_directive_and_hash")


# ---------------------------------------------------------------------------
# (b) Second call with unchanged scene text reuses the stored plan
# ---------------------------------------------------------------------------

def test_second_call_reuses_persisted_directive_no_replan():
    """Simulates call #2: the DB now holds what call #1 (test above) would
    have written — a coverage_directive with a hash matching the CURRENT
    scene text. The C16b skip-if-done gate lets this draw (frames not yet at
    the expected count), but the directive itself must be REUSED — passed to
    run_coverage as directive_text (never None) — so run_coverage's own `if
    directive_text is None:` branch never fires and the real planner LLM is
    never called a second time for identical scene text. And since nothing
    was freshly planned, the fresh-plan persist must NOT fire again."""
    fakedb = FakeDB(
        saved_row=_saved_row(directive=FRESH_DIRECTIVE, hash_value=SCENE_HASH),
        drawn_n=0,  # incomplete -> C16b lets it redraw, but from the SAME plan
    )
    result, run_coverage_mock = _run(fakedb)

    assert result["status"] == "completed"
    run_coverage_mock.assert_awaited_once()
    assert run_coverage_mock.await_args.kwargs["directive_text"] == FRESH_DIRECTIVE, (
        "a matching-hash saved directive must be threaded straight through, "
        "never left None (which would trigger a second internal LLM plan)")

    assert _directive_update_calls(fakedb) == [], (
        "a REUSED directive must never be re-persisted")
    print("✅ test_second_call_reuses_persisted_directive_no_replan")


# ---------------------------------------------------------------------------
# (c) Stored-directive branch does not re-write
# ---------------------------------------------------------------------------

def test_stored_matching_directive_never_rewritten():
    """Same shape as (b) but scoped narrowly to the 'does it write' question,
    independent of skip-if-done timing — a hash-matching saved directive is
    the reuse branch (coverage_to_app.py ~:4946-4991); D15-2 must leave it
    completely alone."""
    fakedb = FakeDB(
        saved_row=_saved_row(directive=FRESH_DIRECTIVE, hash_value=SCENE_HASH),
        drawn_n=0,
    )
    _run(fakedb)
    assert fakedb.execute_calls == [] or _directive_update_calls(fakedb) == [], (
        "reused directive must produce zero coverage_directive writes")
    print("✅ test_stored_matching_directive_never_rewritten")


# ---------------------------------------------------------------------------
# (d) Persist failure does not fail the draw
# ---------------------------------------------------------------------------

def test_persist_failure_is_advisory_only():
    """The scene already drew successfully (paid, real frames) by the time
    the persist UPDATE runs — a DB hiccup on that write must never turn a
    successful draw into a reported failure. It may re-plan again next time
    (acceptable degradation), but this run must still complete."""
    fakedb = FakeDB(saved_row=_saved_row(directive=None, hash_value=None), drawn_n=0,
                     execute_raises=True)
    result, run_coverage_mock = _run(fakedb)

    assert result["status"] == "completed", (
        f"a persist failure must not fail an already-successful draw, got {result}")
    run_coverage_mock.assert_awaited_once()
    assert len(_directive_update_calls(fakedb)) == 1, "the persist must still have been ATTEMPTED"
    print("✅ test_persist_failure_is_advisory_only")


def test_missing_scripts_row_does_not_crash_the_draw():
    """Defensive edge case, not the normal path: `saved` itself comes back
    None (no scripts row at all for this scene — shouldn't happen in
    production since script-writing always inserts one, but the persist
    logic must degrade the same advisory way if it ever does, never a hard
    crash on an already-successful, already-paid-for draw)."""
    fakedb = FakeDB(saved_row=None, drawn_n=0)
    result, run_coverage_mock = _run(fakedb)

    assert result["status"] == "completed"
    run_coverage_mock.assert_awaited_once()
    assert _directive_update_calls(fakedb) == [], (
        "no scripts row id to target -> the advisory persist must no-op, not guess a target")
    print("✅ test_missing_scripts_row_does_not_crash_the_draw")


# ---------------------------------------------------------------------------
# (e) Legacy behavior byte-identical when a directive already exists
# ---------------------------------------------------------------------------

def test_legacy_behavior_unchanged_when_directive_already_exists():
    """Pre-D15-2 behavior for the already-planned, already-matching-hash case:
    same completed status, same message shape, same single run_coverage call
    anchored to the stored plan — D15-2 only ADDS a write for the fresh-plan
    case, it changes nothing for this one."""
    fakedb = FakeDB(
        saved_row=_saved_row(directive=FRESH_DIRECTIVE, hash_value=SCENE_HASH),
        drawn_n=0,
    )
    result, run_coverage_mock = _run(fakedb)

    assert result["status"] == "completed"
    assert result["message"] == "Coverage done: 2 frames across 1 scene(s)"
    run_coverage_mock.assert_awaited_once()
    assert run_coverage_mock.await_args.kwargs["directive_text"] == FRESH_DIRECTIVE
    assert _directive_update_calls(fakedb) == []
    print("✅ test_legacy_behavior_unchanged_when_directive_already_exists")


if __name__ == "__main__":
    test_fresh_plan_persists_directive_and_hash()
    test_second_call_reuses_persisted_directive_no_replan()
    test_stored_matching_directive_never_rewritten()
    test_persist_failure_is_advisory_only()
    test_missing_scripts_row_does_not_crash_the_draw()
    test_legacy_behavior_unchanged_when_directive_already_exists()
    print("\nAll D15-2 tests passed.")
