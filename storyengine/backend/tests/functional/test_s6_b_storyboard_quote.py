"""S6-B (storyboard-quote honesty) — makes the storyboards QUOTE honest
(computed from the SAME workload math the job actually draws with), adds
per-scene readiness warnings BEFORE spend, and appends quoted-vs-actual to
the completion message.

Evidence incident this closes: tenant PocoAPoco video
d39892b2-0c85-4752-85d7-b61ca209342a was quoted $0.35 (a flat "1 board per
scene x 7 scenes" guess) but actually drew $1.10+ of boards — the old
estimate_cost math (actions.py's "storyboards" branch) had no connection
to the real per-scene board count generate_storyboard_sheet_for_scene
(scripts/coverage_to_app.py) computes via plan_moments_deterministic ->
sheet_chunk_sizes, capped at 5 boards/scene.

STASH-PROOF: every test here imports estimate_storyboard_workload /
storyboard_quote_warnings — neither exists before this chunk — so `git
stash` on the two source files (scripts/coverage_to_app.py, actions.py)
makes this whole file fail at COLLECTION (ImportError), the loudest
possible "before" failure.

Four groups, mirroring the chunk brief's own test list:
  1. Consistency — the estimator's exact board count matches the REAL job
     math two independent ways (sheet_chunk_sizes directly, and the actual
     _plan_sheet_prompts output length) — the money claim: quote math ==
     job math.
  2. estimate_cost's "storyboards" branch — upper bound for directive-less
     scenes, exact figure when every pending scene already has a fresh
     saved plan.
  3. Readiness warnings — a declared location with no environment
     reference, a declared location WITH one (containment tolerance, no
     warning), and no declared location at all.
  4. Completion message — a real (DB/network mocked) run of
     generate_storyboard_sheet_for_scene reports both the quoted figure and
     the actual spend.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_s6_b_storyboard_quote.py -q
"""
import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
_PIPELINE_PATH = os.path.join(_BACKEND, "..", "..", "..", "skills", "video-pipeline")
sys.path.insert(0, os.path.abspath(_BACKEND))
sys.path.insert(0, os.path.abspath(_PIPELINE_PATH))

import actions  # noqa: E402
import scripts.coverage_to_app as cta  # noqa: E402
from scripts.coverage_to_app import (  # noqa: E402
    estimate_storyboard_workload, generate_storyboard_sheet_for_scene,
    _plan_sheet_prompts, _scene_text_hash,
)
from storyboard.coverage import (  # noqa: E402
    plan_moments_deterministic, sheet_chunk_sizes, panels_per_sheet_for,
)

VIDEO_ID = "video-s6b"
TENANT_ID = "tenant-s6b"
SCENE = 1

SCENE_TEXT = "The door creaks open as someone steps into the quiet room."
SCENE_HASH = _scene_text_hash(SCENE_TEXT)

# Two moments: moment 1 (master + 1 angle = 2 shots), moment 2 (master only
# = 1 shot) — a small, deterministic fixture, same shape as the other
# S6-A/D15-9 directive fixtures in this suite.
DIRECTIVE = (
    "[MOMENT 1 | opening the door]\n"
    "- MASTER [WS]: Wide shot of the door creaking open in the dim hallway.\n"
    "- ANGLE [MCU]: Close on the hand turning the brass knob.\n"
    "[MOMENT 2 | stepping inside]\n"
    "- MASTER [WS]: Wide shot of someone stepping into the quiet room.\n"
)


def _run(coro):
    return asyncio.run(coro)


def _fake_fetch_one(*, directive=None, hash_value=None):
    """Query-aware fetch_one stub covering estimate_storyboard_workload's
    own video-row lookup AND _get_or_plan_directive's gate lookup — the
    SAME two query shapes every other FakeDB in this test suite handles."""
    async def fake(query, *args):
        if "FROM videos WHERE id=$1" in query:
            return {"id": VIDEO_ID, "tenant_id": TENANT_ID, "video_title": "T",
                    "aspect": "16:9", "image_style_override": None, "visual_style": None,
                    "style_preset_id": None, "render_style": None, "video_model": "grok-imagine",
                    "dialogue_audio": "voice_over", "production_style_snapshot": None}
        if "coverage_directive, coverage_directive_hash FROM scripts" in query:
            return {"id": "script-1", "coverage_directive": directive,
                    "coverage_directive_hash": hash_value}
        raise AssertionError(f"unexpected fetch_one: {query}")
    return fake


def _fake_fetch_all(*, scenes):
    async def fake(query, *args):
        if "FROM scripts WHERE video_id=$1 AND tenant_id=$2 AND scene IS NOT NULL " \
           "AND scene_text IS NOT NULL ORDER BY scene" in query:
            return scenes
        if "FROM video_characters" in query:
            return []
        raise AssertionError(f"unexpected fetch_all: {query}")
    return fake


# =============================================================================
# 1. Consistency — quote math == job math
# =============================================================================

def test_estimator_exact_board_count_matches_sheet_chunk_sizes_directly():
    """For a scene with a fresh saved directive, estimate_storyboard_
    workload's board count is computed the SAME way generate_storyboard_
    sheet_for_scene computes it: plan_moments_deterministic -> shot_count
    -> sheet_chunk_sizes(shot_count, panels_per_sheet_for(directive))."""
    scenes = [{"scene": SCENE, "scene_text": SCENE_TEXT, "location": None}]
    with patch.object(cta, "fetch_one", _fake_fetch_one(directive=DIRECTIVE, hash_value=SCENE_HASH)), \
         patch.object(cta, "fetch_all", _fake_fetch_all(scenes=scenes)), \
         patch.object(cta, "_approved_envs", AsyncMock(return_value=[])):
        workload = _run(estimate_storyboard_workload(VIDEO_ID, TENANT_ID, scene=SCENE))

    # Independently compute the SAME job math (not the estimator's own code
    # path) as the ground truth.
    _mm, _amin, _amax, _mframes = cta._coverage_shape(SCENE_TEXT, "voice_over", None)
    moments = plan_moments_deterministic(DIRECTIVE, _mm, _amax, max_frames=_mframes)
    shot_count = sum(1 + len(m.get("angles") or []) for m in moments)
    cap = panels_per_sheet_for(DIRECTIVE)
    expected_boards = min(len(sheet_chunk_sizes(shot_count, cap)), 5)

    assert len(workload["scenes"]) == 1
    entry = workload["scenes"][0]
    assert entry["exact"] is True
    assert entry["shot_count"] == shot_count
    assert entry["boards_min"] == entry["boards_max"] == expected_boards
    assert workload["boards_min"] == workload["boards_max"] == expected_boards
    assert workload["all_exact"] is True


def test_estimator_board_count_matches_real_plan_sheet_prompts_length():
    """Money claim: the estimator's board count isn't just internally
    consistent with sheet_chunk_sizes — it matches len(_plan_sheet_prompts
    (...)) on the SAME moments, the actual prompt list a real draw slices
    to [:5] and iterates over board-by-board. Quote math == job math."""
    _mm, _amin, _amax, _mframes = cta._coverage_shape(SCENE_TEXT, "voice_over", None)
    moments = plan_moments_deterministic(DIRECTIVE, _mm, _amax, max_frames=_mframes)
    cap = panels_per_sheet_for(DIRECTIVE)
    prompts = _plan_sheet_prompts(
        moments, "style", panels_per_sheet=cap, set_line="a plain set",
        axis_line="", setups_line="", location="")[:5]

    scenes = [{"scene": SCENE, "scene_text": SCENE_TEXT, "location": None}]
    with patch.object(cta, "fetch_one", _fake_fetch_one(directive=DIRECTIVE, hash_value=SCENE_HASH)), \
         patch.object(cta, "fetch_all", _fake_fetch_all(scenes=scenes)), \
         patch.object(cta, "_approved_envs", AsyncMock(return_value=[])):
        workload = _run(estimate_storyboard_workload(VIDEO_ID, TENANT_ID, scene=SCENE))

    assert workload["scenes"][0]["boards_max"] == len(prompts)


# =============================================================================
# 2. estimate_cost's "storyboards" branch — upper bound vs. exact
# =============================================================================

def test_estimate_cost_storyboards_directiveless_scenes_use_upper_bound():
    """No saved directive for ANY target scene -> cost is the honest UPPER
    bound (5 boards/scene, never a flat 1-board-per-scene guess), and the
    text says it's a range, not a precise count."""
    scenes = [{"scene": 1, "scene_text": "text one", "location": None},
              {"scene": 2, "scene_text": "text two", "location": None}]
    with patch.object(cta, "fetch_one", _fake_fetch_one(directive=None, hash_value=None)), \
         patch.object(cta, "fetch_all", _fake_fetch_all(scenes=scenes)), \
         patch.object(cta, "_approved_envs", AsyncMock(return_value=[])):
        summary = {"model": "grok-imagine", "scenes": 2}
        cost, text = _run(actions.estimate_cost(TENANT_ID, VIDEO_ID, "storyboards", None, summary))

    assert cost == round(2 * 5 * actions.PICTURE_COST, 2)
    assert cost > 2 * actions.PICTURE_COST, "must NOT be the old flat 1-board/scene guess"
    assert "max" in text.lower()


def test_estimate_cost_storyboards_all_exact_directives_gives_precise_quote():
    """Every pending scene already has a fresh saved directive -> the quote
    is the EXACT figure (no "max"/range language), derived from the SAME
    board math the draw itself uses."""
    scenes = [{"scene": SCENE, "scene_text": SCENE_TEXT, "location": None}]
    with patch.object(cta, "fetch_one", _fake_fetch_one(directive=DIRECTIVE, hash_value=SCENE_HASH)), \
         patch.object(cta, "fetch_all", _fake_fetch_all(scenes=scenes)), \
         patch.object(cta, "_approved_envs", AsyncMock(return_value=[])):
        summary = {"model": "grok-imagine", "scenes": 1}
        cost, text = _run(actions.estimate_cost(TENANT_ID, VIDEO_ID, "storyboards", None, summary))

    _mm, _amin, _amax, _mframes = cta._coverage_shape(SCENE_TEXT, "voice_over", None)
    moments = plan_moments_deterministic(DIRECTIVE, _mm, _amax, max_frames=_mframes)
    shot_count = sum(1 + len(m.get("angles") or []) for m in moments)
    cap = panels_per_sheet_for(DIRECTIVE)
    expected_boards = min(len(sheet_chunk_sizes(shot_count, cap)), 5)

    assert cost == round(expected_boards * actions.PICTURE_COST, 2)
    assert "max" not in text.lower()
    assert str(expected_boards) in text


def test_estimate_cost_storyboards_other_verbs_math_is_untouched():
    """Sanity: this chunk's estimate_cost changes are scoped to the
    "storyboards" branch — a completely unrelated verb's math is
    byte-identical to before (no accidental custom_text leakage)."""
    summary = {"model": "grok-imagine", "scenes": 3, "clips": 0}
    cost, text = _run(actions.estimate_cost(TENANT_ID, VIDEO_ID, "sound", None, summary))
    assert cost == actions.SOUND_COST_ESTIMATE
    assert text == f"~${actions.SOUND_COST_ESTIMATE:.2f}"


# =============================================================================
# 3. Readiness warnings — surfaced BEFORE spend
# =============================================================================

def test_readiness_warns_when_declared_location_has_no_environment_reference():
    """cd39892b2-style incident: a declared location with no matching
    approved environment reference means the board falls back to prose
    matching — warn, naming the scene and the location."""
    scenes = [{"scene": SCENE, "scene_text": SCENE_TEXT, "location": "the kitchen at home"}]
    envs = [{"name": "School classroom", "reference_url": "https://x/classroom.png"}]
    with patch.object(cta, "fetch_one", _fake_fetch_one(directive=None, hash_value=None)), \
         patch.object(cta, "fetch_all", _fake_fetch_all(scenes=scenes)), \
         patch.object(cta, "_approved_envs", AsyncMock(return_value=envs)):
        warnings = _run(actions.storyboard_quote_warnings(TENANT_ID, VIDEO_ID, None))

    assert len(warnings) == 1
    assert f"Scene {SCENE}" in warnings[0]
    assert "the kitchen at home" in warnings[0]
    assert "environment reference" in warnings[0]
    assert "—" not in warnings[0], "no em dashes in user-visible warning text"


def test_readiness_no_warning_when_environment_covers_location_via_containment():
    """The same declared location, but an approved environment named
    'Kitchen at home' WITH a reference_url now exists — containment
    tolerance (leading-article difference) means this scene is covered,
    no warning."""
    scenes = [{"scene": SCENE, "scene_text": SCENE_TEXT, "location": "the kitchen at home"}]
    envs = [{"name": "Kitchen at home", "reference_url": "https://x/kitchen.png"}]
    with patch.object(cta, "fetch_one", _fake_fetch_one(directive=None, hash_value=None)), \
         patch.object(cta, "fetch_all", _fake_fetch_all(scenes=scenes)), \
         patch.object(cta, "_approved_envs", AsyncMock(return_value=envs)):
        warnings = _run(actions.storyboard_quote_warnings(TENANT_ID, VIDEO_ID, None))

    assert warnings == []


def test_readiness_warns_when_scene_has_no_declared_location():
    """A NULL scripts.location (every legacy scene, or one never written
    through the S3/S5 gate) gets its own, distinct warning."""
    scenes = [{"scene": SCENE, "scene_text": SCENE_TEXT, "location": None}]
    with patch.object(cta, "fetch_one", _fake_fetch_one(directive=None, hash_value=None)), \
         patch.object(cta, "fetch_all", _fake_fetch_all(scenes=scenes)), \
         patch.object(cta, "_approved_envs", AsyncMock(return_value=[])):
        warnings = _run(actions.storyboard_quote_warnings(TENANT_ID, VIDEO_ID, None))

    assert warnings == [f"Scene {SCENE} has no declared location."]


def test_readiness_no_warnings_when_nothing_to_flag():
    """A scene with a declared location AND a covering environment
    reference -> empty list (never an empty-but-truthy placeholder)."""
    scenes = [{"scene": SCENE, "scene_text": SCENE_TEXT, "location": "the kitchen at home"}]
    envs = [{"name": "The Kitchen At Home", "reference_url": "https://x/kitchen.png"}]
    with patch.object(cta, "fetch_one", _fake_fetch_one(directive=None, hash_value=None)), \
         patch.object(cta, "fetch_all", _fake_fetch_all(scenes=scenes)), \
         patch.object(cta, "_approved_envs", AsyncMock(return_value=envs)):
        warnings = _run(actions.storyboard_quote_warnings(TENANT_ID, VIDEO_ID, None))

    assert warnings == []


# =============================================================================
# 4. Completion message — "Quoted $X, actual $Y"
# =============================================================================

class _S6BFakeDB:
    """Same convention as test_d15_9_directive_gate.py's _beat_redo_fakedb:
    records nothing, serves canned fetch_one/fetch_all rows. No real DB."""

    def __init__(self, scenes, directive, hash_value):
        self._scenes = scenes
        self._directive = directive
        self._hash = hash_value

    async def fetch_one(self, query, *args):
        if "FROM videos WHERE id=$1" in query:
            return {"id": VIDEO_ID, "tenant_id": TENANT_ID, "video_title": "T",
                    "aspect": "16:9", "image_style_override": None, "visual_style": None,
                    "style_preset_id": None, "render_style": None, "video_model": "grok-imagine",
                    "dialogue_audio": "voice_over", "production_style_snapshot": None}
        if "coverage_directive, coverage_directive_hash FROM scripts" in query:
            return {"id": "script-1", "coverage_directive": self._directive,
                    "coverage_directive_hash": self._hash}
        raise AssertionError(f"unexpected fetch_one: {query}")

    async def fetch_all(self, query, *args):
        if "FROM scripts WHERE video_id=$1 AND tenant_id=$2 AND scene IS NOT NULL " \
           "AND scene_text IS NOT NULL ORDER BY scene" in query:
            return self._scenes
        if "FROM video_characters" in query:
            return []
        raise AssertionError(f"unexpected fetch_all: {query}")

    async def execute(self, query, *args):
        return "OK"


def test_completion_message_reports_quoted_and_actual_cost():
    """P8: the completion message names both the quoted figure (computed
    at run start from the SAME estimator, for the whole scene) and the
    actual spend (accumulated as boards genuinely land) — proving a
    creator can see the gap the PocoAPoco incident hid. A per-board redo
    (beat=1) on a 2-board scene quotes the WHOLE scene (2 boards) but only
    draws 1, so the two numbers provably differ — not a vacuous "always
    equal" check."""
    scenes = [{"scene": SCENE, "scene_text": SCENE_TEXT, "location": None}]
    fakedb = _S6BFakeDB(scenes, DIRECTIVE, SCENE_HASH)
    board_count = 2
    fake_prompts = [f"board {i} prompt" for i in range(1, board_count + 1)]
    fake_sizes = [1] * board_count
    image_client = AsyncMock(return_value=("https://fake-storage.example/board.png", "gpt-image-2"))

    with patch.object(cta, "fetch_one", fakedb.fetch_one), \
         patch.object(cta, "fetch_all", fakedb.fetch_all), \
         patch.object(cta, "execute", fakedb.execute), \
         patch.object(cta, "get_secret", AsyncMock(return_value="fake-kie-key")), \
         patch.object(cta, "get_text_client_for_tenant", AsyncMock(return_value=object())), \
         patch.object(cta, "claude_model_for_direct_client", lambda c: "fake-model"), \
         patch.object(cta, "scene_aware_bible", AsyncMock(return_value=None)), \
         patch.object(cta, "_approved_envs", AsyncMock(return_value=[])), \
         patch.object(cta, "generate_scene_image_for_model", image_client), \
         patch.object(cta, "_stable_url", AsyncMock(return_value="https://stable/final.png")), \
         patch.object(cta, "record_ledger_entry", AsyncMock(return_value=None)), \
         patch.object(cta, "_plan_sheet_prompts", lambda *a, **k: list(fake_prompts)), \
         patch.object(cta, "sheet_chunk_sizes", lambda *a, **k: list(fake_sizes)):
        result = _run(generate_storyboard_sheet_for_scene(
            VIDEO_ID, TENANT_ID, scene=SCENE, beat=1))

    assert result["status"] == "completed", result
    assert "Quoted $" in result["message"]
    assert "actual $" in result["message"]

    from actions import picture_price_for
    sheet_price = picture_price_for("gpt-image-2")
    quoted = round(board_count * sheet_price, 2)
    actual = round(1 * sheet_price, 2)
    assert quoted != actual, "sanity: the fixture must exercise a genuine quote/actual gap"
    assert f"Quoted ${quoted:.2f}, actual ${actual:.2f}." in result["message"]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
