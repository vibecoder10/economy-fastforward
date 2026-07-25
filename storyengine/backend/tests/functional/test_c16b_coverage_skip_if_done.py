"""Tests for C16b (checklist §Phase 1 "C16b · S7-2 fix: scene-level skip-if-done
+ scene allowlist in coverage image generation",
docs/reports/2026-07-17-storyengine-agent-audit-findings.md §S7-2 CRITICAL).

Before this fix, scripts/coverage_to_app.py::generate_coverage_for_video called
the PAID run_coverage() for every scene with script text on EVERY invocation —
only the directive TEXT was cached (coverage_directive_hash); a second click of
"Generate all pictures", or an autobuild retry that revisits the image phase,
re-billed every scene from scratch. Contrast: clip generation already skips via
`video_url IS NULL` (supabase_adapter.py), voice (voice/run.py) and sound
(sound_bot.py) both skip-if-done.

This pins the fix:

  1. Skip-if-done (the default, scene=None/only_scenes=None): a scene whose
     saved coverage_directive_hash matches the CURRENT script hash AND whose
     `assets` row count (generation_method='coverage', image_url AND
     drive_image_url both set) is >= the frame count parse_coverage()+
     enforce_shot_budget() would produce from THAT SAME saved directive under
     today's shape params (_expected_coverage_frame_count — the new helper) is
     left alone: run_coverage() is never called for it, and the run's summary
     message counts it as skipped.
  2. An INCOMPLETE scene (drawn row count under the expected count — e.g. a
     prior crash or content-policy skip left fewer rows than planned) still
     regenerates — proves the completeness rule can't false-positive-skip a
     half-drawn scene.
  3. A HASH-MISMATCH scene (script changed since the plan) still regenerates
     regardless of how many rows already exist — the pre-existing re-plan gate
     is untouched.
  4. The explicit `scene=N` single-scene param (the existing per-scene
     "regenerate scene N" button/verb) FORCES that scene to redraw even when
     it would otherwise skip — an explicit ask always wins.
  5. The new `only_scenes` allowlist (finalize's future entry point) narrows
     `targets` to exactly those scenes AND forces them, regardless of
     skip-if-done state; every other scene is never touched (never even
     queried) — proven by the fake DB raising on the scripts-hash lookup for
     any scene number outside a test's `saved_by_scene` map, which we assert
     doesn't happen for the untouched scenes.
  6. render_style/video_model_id NameError fix: this call path referenced
     `render_style`/`video_model_id` at the run_coverage() call site, but the
     `v` row here never SELECTed those two columns (they were only fetched in
     the neighboring generate_storyboard_sheet_for_scene) — every real
     invocation crashed with NameError before this fix (introduced by C13b,
     8f923f3). test_render_style_and_video_model_id_no_longer_raise pins it.

No network, no real DB: `database`/`vault`/`kie_unified`/`storage` are stubbed
at import time (mirrors tests/functional/test_scene_model_routing.py's module-
stub pattern); the heavier per-scene helpers this function calls but that
C16b does not touch (scene_aware_bible, _approved_envs, store_scene,
set_scene_board, _write_motion_prompts, populate_characters,
_reconcile_moment_dialogue) are patched to no-ops per test so each test
exercises ONLY the skip/allowlist/force decision this chunk adds.
run_coverage() (the paid call) is patched to a recording AsyncMock — the
`run_coverage.assert_*` calls are the money-safety proof.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c16b_coverage_skip_if_done.py -q
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
_stub("database", fetch_one=_boom, fetch_all=_boom, execute=_boom)
_stub("storage", upload_bytes=_boom)
_stub("vault", get_secret=_boom)
_stub("kie_unified", get_text_client_for_tenant=_boom)

from scripts.coverage_to_app import (  # noqa: E402
    CUSTOM_FILM_AUXILIARY_IMAGE_POLICY,
    generate_coverage_for_video,
    _scene_text_hash,
    _expected_coverage_frame_count,
)

VIDEO_ID = "11111111-1111-1111-1111-111111111111"
TENANT_ID = "tenant-1"

# Non-dialogue scene text -> _coverage_shape() deterministically returns
# (3, 2, 3, None) for EVERY scene below (turns < 2 branch), so every scene's
# expected frame count comes from the SAME directive under the SAME params.
SCENE_TEXT = "The city lights flicker as rain falls onto empty streets."

# One master + one angle -> enforce_shot_budget(max_moments=3, angles_max=3,
# max_frames=None) leaves both untouched -> expected frame count == 2.
DIRECTIVE = (
    "[MOMENT 1 | rain falls on empty streets]\n"
    "- MASTER [WS]: Wide shot of rain-soaked streets, neon reflections shimmering.\n"
    "- ANGLE [MCU]: Close on droplets streaking down a window pane.\n"
)
SCENE_HASH = _scene_text_hash(SCENE_TEXT)


def _video_row():
    return {
        "id": VIDEO_ID, "tenant_id": TENANT_ID, "video_title": "Test Video",
        "aspect": "16:9", "image_style_override": None, "visual_style": None,
        "image_model_override": None, "render_style": None, "video_model": "grok-imagine",
        "dialogue_audio": "voice_over",
    }


def _saved_row(hash_value=SCENE_HASH, directive=DIRECTIVE):
    return {
        "coverage_directive": directive, "coverage_directive_hash": hash_value,
        "storyboard_1_url": None, "storyboard_2_url": None, "storyboard_3_url": None,
        "storyboard_4_url": None, "storyboard_5_url": None,
    }


class FakeDB:
    """Dispatches the exact query shapes generate_coverage_for_video issues.
    saved_by_scene / drawn_by_scene are keyed by scene number; a scene number
    absent from BOTH maps must never be queried at all (proves untouched
    scenes under an allowlist/scene filter are skipped before any DB hit)."""

    def __init__(self, scenes, saved_by_scene, drawn_by_scene, cast_ref="https://cast.png/x.png"):
        self.scenes = scenes
        self.saved_by_scene = saved_by_scene
        self.drawn_by_scene = drawn_by_scene
        self.cast_ref = cast_ref
        self.scene_queries: list[int] = []  # every scene number the "saved" or "drawn" query touched

    async def fetch_one(self, query, *args):
        if "FROM videos WHERE id=$1" in query:
            return _video_row()
        if "coverage_directive_hash" in query and "FROM scripts" in query:
            sc = args[2]
            self.scene_queries.append(sc)
            row = self.saved_by_scene.get(sc)
            return dict(row) if row else None
        if "FROM assets" in query and "generation_method='coverage'" in query:
            sc = args[2]
            self.scene_queries.append(sc)
            return {"n": self.drawn_by_scene.get(sc, 0)}
        raise AssertionError(f"unexpected fetch_one query: {query}")

    async def fetch_all(self, query, *args):
        if "SELECT scene, scene_text FROM scripts" in query:
            return [dict(s) for s in self.scenes]
        if "FROM video_characters" in query:
            return [{"reference_url": self.cast_ref}] if self.cast_ref else []
        raise AssertionError(f"unexpected fetch_all query: {query}")

    async def execute(self, query, *args):
        return "OK"


def _scenes(numbers):
    return [{"scene": n, "scene_text": SCENE_TEXT} for n in numbers]


def _patch_noop_helpers(motion_mock=None, populate_mock=None):
    """Every per-scene helper C16b does not touch, patched to harmless no-ops
    so each test exercises ONLY the skip/allowlist/force decision."""
    return [
        patch("scripts.coverage_to_app.get_secret", AsyncMock(return_value="fake-kie-key")),
        patch("scripts.coverage_to_app.get_text_client_for_tenant", AsyncMock(return_value=object())),
        patch("scripts.coverage_to_app.scene_aware_bible", AsyncMock(return_value=None)),
        patch("scripts.coverage_to_app._approved_envs", AsyncMock(return_value=[])),
        patch("scripts.coverage_to_app.store_scene", AsyncMock(return_value=2)),
        patch("scripts.coverage_to_app.set_scene_board", AsyncMock(return_value=True)),
        patch(
            "scripts.coverage_to_app._write_motion_prompts",
            motion_mock or AsyncMock(return_value=0),
        ),
        patch(
            "scripts.coverage_to_app.populate_characters",
            populate_mock or AsyncMock(return_value=0),
        ),
        patch("scripts.coverage_to_app._reconcile_moment_dialogue", lambda moments, text: None),
    ]


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


def _run(fakedb, **kwargs):
    run_coverage_mock = AsyncMock(side_effect=_fresh_run_coverage_output)
    motion_mock = AsyncMock(return_value=0)
    populate_mock = AsyncMock(return_value=0)
    cast_mock = AsyncMock(return_value="https://generated-cast.png")
    patches = _patch_noop_helpers(motion_mock, populate_mock) + [
        patch("scripts.coverage_to_app.fetch_one", fakedb.fetch_one),
        patch("scripts.coverage_to_app.fetch_all", fakedb.fetch_all),
        patch("scripts.coverage_to_app.execute", fakedb.execute),
        patch("scripts.coverage_to_app.run_coverage", run_coverage_mock),
        patch("scripts.coverage_to_app.resolve_cast_url", cast_mock),
    ]
    for p in patches:
        p.start()
    try:
        result = asyncio.run(generate_coverage_for_video(VIDEO_ID, TENANT_ID, **kwargs))
    finally:
        for p in patches:
            p.stop()
    run_coverage_mock.inline_motion_mock = motion_mock
    run_coverage_mock.populate_mock = populate_mock
    run_coverage_mock.cast_mock = cast_mock
    return result, run_coverage_mock


def _called_scenes(run_coverage_mock) -> list:
    return [c.kwargs["beat_scenes"][0] for c in run_coverage_mock.await_args_list]


def test_custom_film_coverage_defers_motion_to_exact_motion_stage():
    fakedb = FakeDB(
        scenes=_scenes([1]),
        saved_by_scene={1: None},
        drawn_by_scene={1: 0},
    )
    section_contract = {
        "render_mode": "coverage",
        "image_source": "generate",
        "expected_still_images": 2,
        "expected_animation_clips": 2,
        "image_density": {"mode": "visual_cue", "target_per_minute": 2},
        "animation": {"enabled": True, "mode": "grok_native"},
        "camera": {"mode": "investigative_coverage"},
        "visual_profile": "neutral_v1",
        "exact_seconds": 7,
        "auxiliary_image_policy": dict(CUSTOM_FILM_AUXILIARY_IMAGE_POLICY),
    }

    result, coverage = _run(fakedb, section_contract=section_contract)

    assert result["status"] == "completed"
    coverage.assert_awaited_once()
    assert coverage.await_args.kwargs["max_moments"] == 2
    assert coverage.await_args.kwargs["angles_min"] == 0
    assert coverage.await_args.kwargs["angles_max"] == 0
    assert coverage.await_args.kwargs["max_frames"] == 2
    coverage.inline_motion_mock.assert_not_awaited()


def test_custom_film_coverage_forbids_unquoted_auxiliary_images():
    fakedb = FakeDB(
        scenes=_scenes([1]),
        saved_by_scene={1: None},
        drawn_by_scene={1: 0},
        cast_ref=None,
    )
    section_contract = {
        "render_mode": "coverage",
        "image_source": "generate",
        "expected_still_images": 2,
        "expected_animation_clips": 2,
        "image_density": {"mode": "visual_cue", "target_per_minute": 2},
        "animation": {"enabled": True, "mode": "grok_native"},
        "camera": {"mode": "investigative_coverage"},
        "visual_profile": "neutral_v1",
        "exact_seconds": 7,
        "auxiliary_image_policy": dict(CUSTOM_FILM_AUXILIARY_IMAGE_POLICY),
    }

    result, coverage = _run(fakedb, section_contract=section_contract)

    assert result["status"] == "completed"
    coverage.assert_awaited_once()
    assert coverage.await_args.kwargs["cast_url"] == []
    assert coverage.await_args.kwargs["allow_auto_cast_generation"] is False
    assert result["message"] == "Coverage done: 2 frames across 1 scene(s)"
    coverage.cast_mock.assert_not_awaited()
    coverage.populate_mock.assert_not_awaited()


def test_custom_film_auxiliary_image_policy_is_fail_closed():
    fakedb = FakeDB(
        scenes=_scenes([1]),
        saved_by_scene={1: None},
        drawn_by_scene={1: 0},
        cast_ref=None,
    )
    bad_contract = {
        "render_mode": "coverage",
        "image_source": "generate",
        "expected_still_images": 2,
        "expected_animation_clips": 2,
        "image_density": {"mode": "visual_cue", "target_per_minute": 2},
        "animation": {"enabled": True, "mode": "grok_native"},
        "camera": {"mode": "investigative_coverage"},
        "visual_profile": "neutral_v1",
        "exact_seconds": 7,
        "auxiliary_image_policy": {
            "auto_cast_generation": "allowed",
            "auto_character_population": "forbidden",
        },
    }

    try:
        _run(fakedb, section_contract=bad_contract)
    except ValueError as exc:
        assert str(exc) == "Unsupported coverage section production contract"
    else:
        raise AssertionError("mutated auxiliary image policy must fail closed")


def test_legacy_coverage_keeps_auto_cast_and_character_population():
    fakedb = FakeDB(
        scenes=_scenes([1]),
        saved_by_scene={1: None},
        drawn_by_scene={1: 0},
        cast_ref=None,
    )

    result, coverage = _run(fakedb)

    assert result["status"] == "completed"
    coverage.cast_mock.assert_awaited_once()
    coverage.populate_mock.assert_awaited_once()
    assert (
        "allow_auto_cast_generation"
        not in coverage.await_args.kwargs
    )


# ---------------------------------------------------------------------------
# 1. Default call (scene=None, only_scenes=None): skip-if-done
# ---------------------------------------------------------------------------

def test_complete_scene_under_matching_hash_is_skipped_run_coverage_not_called():
    fakedb = FakeDB(
        scenes=_scenes([1, 2, 3]),
        saved_by_scene={1: _saved_row(), 2: _saved_row(), 3: _saved_row()},
        drawn_by_scene={1: 2, 2: 1, 3: 2},  # scene 1 & 3 complete (>=2), scene 2 incomplete (1<2)
    )
    result, run_coverage_mock = _run(fakedb)
    assert result["status"] == "completed"
    called = _called_scenes(run_coverage_mock)
    assert called == [2], f"only the incomplete scene should draw, got {called}"
    assert result["message"] == "Coverage done: 2 frames across 1 scene(s) (2 scene(s) already done, skipped)", (
        result["message"])
    print("✅ test_complete_scene_under_matching_hash_is_skipped_run_coverage_not_called")


def test_incomplete_scene_regenerates():
    """A scene with a matching hash but fewer drawn frames than the directive
    would produce (a crash/content-policy skip mid-draw) must NOT read as
    done — this is the false-positive-skip guard."""
    fakedb = FakeDB(
        scenes=_scenes([1]),
        saved_by_scene={1: _saved_row()},
        drawn_by_scene={1: 1},  # only 1 of the expected 2 frames on record
    )
    result, run_coverage_mock = _run(fakedb)
    assert _called_scenes(run_coverage_mock) == [1]
    assert "skipped" not in result["message"]
    print("✅ test_incomplete_scene_regenerates")


def test_zero_drawn_frames_regenerates():
    fakedb = FakeDB(
        scenes=_scenes([1]),
        saved_by_scene={1: _saved_row()},
        drawn_by_scene={1: 0},
    )
    result, run_coverage_mock = _run(fakedb)
    assert _called_scenes(run_coverage_mock) == [1]
    print("✅ test_zero_drawn_frames_regenerates")


def test_hash_mismatch_regenerates_even_with_full_frame_count():
    """A changed script invalidates the plan (pre-existing behavior) even
    when the OLD frame count happens to look "complete" by row count alone —
    hash mismatch always wins over the row-count check."""
    fakedb = FakeDB(
        scenes=_scenes([1]),
        saved_by_scene={1: _saved_row(hash_value="stale-hash-does-not-match-current-script")},
        drawn_by_scene={1: 2},  # would look complete by row count alone
    )
    result, run_coverage_mock = _run(fakedb)
    assert _called_scenes(run_coverage_mock) == [1]
    assert "skipped" not in result["message"]
    print("✅ test_hash_mismatch_regenerates_even_with_full_frame_count")


def test_no_saved_directive_regenerates():
    """A scene that was never planned (no storyboard gate run) has nothing to
    skip against — must always draw."""
    fakedb = FakeDB(scenes=_scenes([1]), saved_by_scene={}, drawn_by_scene={})
    result, run_coverage_mock = _run(fakedb)
    assert _called_scenes(run_coverage_mock) == [1]
    print("✅ test_no_saved_directive_regenerates")


# ---------------------------------------------------------------------------
# 2. Explicit `scene=N` param forces that scene regardless of completeness
# ---------------------------------------------------------------------------

def test_explicit_scene_param_forces_regeneration_of_a_complete_scene():
    """The existing per-scene 'regenerate scene N' button/verb
    (routes/pipeline.py::run_coverage_images(scene=N)) must still fully
    redraw on request — an explicit ask always overrides skip-if-done."""
    fakedb = FakeDB(
        scenes=_scenes([1, 2]),
        saved_by_scene={1: _saved_row(), 2: _saved_row()},
        drawn_by_scene={1: 2, 2: 2},  # both look complete
    )
    result, run_coverage_mock = _run(fakedb, scene=1)
    assert _called_scenes(run_coverage_mock) == [1]
    assert "skipped" not in result["message"]
    # scene 2 was never even a target (scene=1 narrows `targets`) — never queried.
    assert 2 not in fakedb.scene_queries
    print("✅ test_explicit_scene_param_forces_regeneration_of_a_complete_scene")


# ---------------------------------------------------------------------------
# 3. only_scenes allowlist: forces named scenes, leaves everything else untouched
# ---------------------------------------------------------------------------

def test_only_scenes_allowlist_forces_named_scene_and_skips_the_rest_untouched():
    """finalize's future entry point: only_scenes=[1] must (a) force scene 1
    to redraw even though it looks complete+matching, and (b) never even
    query scenes 2/3 — they are untouched, not merely skipped."""
    fakedb = FakeDB(
        scenes=_scenes([1, 2, 3]),
        saved_by_scene={1: _saved_row(), 2: _saved_row(), 3: _saved_row()},
        drawn_by_scene={1: 2, 2: 2, 3: 2},  # all look complete
    )
    result, run_coverage_mock = _run(fakedb, only_scenes=[1])
    assert _called_scenes(run_coverage_mock) == [1]
    assert "skipped" not in result["message"]
    assert 2 not in fakedb.scene_queries and 3 not in fakedb.scene_queries, (
        "scenes outside the allowlist must never be queried at all")
    print("✅ test_only_scenes_allowlist_forces_named_scene_and_skips_the_rest_untouched")


def test_only_scenes_allowlist_multiple_scenes():
    fakedb = FakeDB(
        scenes=_scenes([1, 2, 3]),
        saved_by_scene={1: _saved_row(), 2: _saved_row(), 3: _saved_row()},
        drawn_by_scene={1: 2, 2: 2, 3: 2},
    )
    result, run_coverage_mock = _run(fakedb, only_scenes=[1, 3])
    assert sorted(_called_scenes(run_coverage_mock)) == [1, 3]
    assert 2 not in fakedb.scene_queries
    print("✅ test_only_scenes_allowlist_multiple_scenes")


# ---------------------------------------------------------------------------
# 4. Summary message counts skipped scenes
# ---------------------------------------------------------------------------

def test_summary_message_counts_skipped_and_processed_scenes():
    fakedb = FakeDB(
        scenes=_scenes([1, 2]),
        saved_by_scene={1: _saved_row(), 2: _saved_row()},
        drawn_by_scene={1: 2, 2: 0},
    )
    result, run_coverage_mock = _run(fakedb)
    assert result["message"] == "Coverage done: 2 frames across 1 scene(s) (1 scene(s) already done, skipped)"
    print("✅ test_summary_message_counts_skipped_and_processed_scenes")


def test_summary_message_omits_skip_note_when_nothing_skipped():
    fakedb = FakeDB(
        scenes=_scenes([1]),
        saved_by_scene={1: _saved_row()},
        drawn_by_scene={1: 0},
    )
    result, run_coverage_mock = _run(fakedb)
    assert "skipped" not in result["message"]
    assert result["message"] == "Coverage done: 2 frames across 1 scene(s)"
    print("✅ test_summary_message_omits_skip_note_when_nothing_skipped")


# ---------------------------------------------------------------------------
# 5. _expected_coverage_frame_count: the new helper, pure unit tests
# ---------------------------------------------------------------------------

def test_expected_coverage_frame_count_matches_directive_shape():
    assert _expected_coverage_frame_count(DIRECTIVE, 3, 3, None) == 2


def test_expected_coverage_frame_count_zero_for_unparseable_directive():
    assert _expected_coverage_frame_count("not a real directive at all", 3, 3, None) == 0


def test_expected_coverage_frame_count_respects_angle_trim():
    directive = (
        "[MOMENT 1 | x]\n"
        "- MASTER [WS]: a.\n"
        "- ANGLE [MCU]: b.\n"
        "- ANGLE [CU]: c.\n"
        "- ANGLE [INSERT]: d.\n"
    )
    # angles_max=1 trims 3 angles -> 1; total = master + 1 angle = 2.
    assert _expected_coverage_frame_count(directive, 3, 1, None) == 2


# ---------------------------------------------------------------------------
# 6. render_style/video_model_id NameError fix
# ---------------------------------------------------------------------------

def test_render_style_and_video_model_id_no_longer_raise():
    """Incidental fix found while building C16b: this call path referenced
    render_style/video_model_id at the run_coverage() call site without ever
    SELECTing them onto `v` — every real invocation raised NameError as soon
    as it reached a scene that needed to draw (introduced by C13b, 8f923f3).
    A scene that regenerates (not skipped) is required to actually reach
    that line; this pins that it no longer crashes."""
    fakedb = FakeDB(scenes=_scenes([1]), saved_by_scene={}, drawn_by_scene={})
    result, run_coverage_mock = _run(fakedb)
    assert result["status"] == "completed"
    call = run_coverage_mock.await_args_list[0]
    assert call.kwargs["render_style"] is None  # from _video_row()'s render_style=None
    assert call.kwargs["video_model_id"] == "grok-imagine"  # from _video_row()'s video_model
    print("✅ test_render_style_and_video_model_id_no_longer_raise")


if __name__ == "__main__":
    test_complete_scene_under_matching_hash_is_skipped_run_coverage_not_called()
    test_incomplete_scene_regenerates()
    test_zero_drawn_frames_regenerates()
    test_hash_mismatch_regenerates_even_with_full_frame_count()
    test_no_saved_directive_regenerates()
    test_explicit_scene_param_forces_regeneration_of_a_complete_scene()
    test_only_scenes_allowlist_forces_named_scene_and_skips_the_rest_untouched()
    test_only_scenes_allowlist_multiple_scenes()
    test_summary_message_counts_skipped_and_processed_scenes()
    test_summary_message_omits_skip_note_when_nothing_skipped()
    test_expected_coverage_frame_count_matches_directive_shape()
    test_expected_coverage_frame_count_zero_for_unparseable_directive()
    test_expected_coverage_frame_count_respects_angle_trim()
    test_render_style_and_video_model_id_no_longer_raise()
    print("\nAll C16b tests passed.")
