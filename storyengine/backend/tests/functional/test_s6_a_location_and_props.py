"""S6-A (STORY-LAWS.md S6 — "the script is the origin of truth", BOARD-LAWS.md
L30) — the LIVE storyboard planner (scripts/coverage_to_app.py's
generate_storyboard_sheet_for_scene / _plan_sheet_prompts) now consumes the
script's own canonical scripts.location column, and the SAME single planning
call extracts named physical props/actions from the beat's dialogue into the
shot plan (storyboard/coverage.py's parse_coverage, rule 30, [PROPS|...]).

STASH-PROOF: every test below imports at least one of
_assert_scene_location_declared / check_prop_action_presence, neither of
which exists before this chunk — `git stash` on the two source files makes
this whole file fail at COLLECTION (ImportError) or at call time
(AttributeError), the loudest possible "before" failure.

Evidence incident modeled throughout (STORY-LAWS.md S6-A status entry):
tenant PocoAPoco video d39892b2-0c85-4752-85d7-b61ca209342a, scene 1 — the
script's stated location was "the kitchen at home"; the assembled board
prompt never contained the word "kitchen", and the board drew the bedroom.
Scene 5's water bottle and the "Dos boletos" tickets prop appeared in 0
panels — the props side of this same incident.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_s6_a_location_and_props.py -q
"""
import os
import sys

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
_PIPELINE_PATH = os.path.join(_BACKEND, "..", "..", "..", "skills", "video-pipeline")
sys.path.insert(0, os.path.abspath(_BACKEND))
sys.path.insert(0, os.path.abspath(_PIPELINE_PATH))

from scripts.coverage_to_app import (  # noqa: E402
    _plan_sheet_prompts, _match_scene_env, _assert_scene_location_declared,
    SheetPromptContractViolation,
)
from storyboard.coverage import parse_coverage, check_prop_action_presence  # noqa: E402


# =============================================================================
# L30 — _assert_scene_location_declared, the unit-level gate
# =============================================================================

def test_l30_assert_raises_when_location_missing_from_gate_text():
    with pytest.raises(SheetPromptContractViolation, match="L30"):
        _assert_scene_location_declared(
            "FIXED SET — identical in EVERY panel that shows the location: wooden "
            "counters, a fridge in the corner, sage cabinetry.",
            "the kitchen at home")


def test_l30_assert_passes_when_location_present_verbatim():
    _assert_scene_location_declared(
        "FIXED SET — identical in EVERY panel that shows the location: the kitchen "
        "at home, wooden counters, a fridge in the corner.",
        "the kitchen at home")  # no raise


def test_l30_assert_tolerates_leading_article_mismatch():
    """A header that drops the script's leading 'the' ('kitchen at home'
    instead of 'the kitchen at home') is still the same place — per the
    task spec's explicit tolerance, this must not raise."""
    _assert_scene_location_declared(
        "FIXED SET — identical in EVERY panel: kitchen at home, wooden counters.",
        "the kitchen at home")  # no raise


def test_l30_assert_exempt_when_location_none_or_empty():
    """NULL/empty scripts.location (every legacy video) — the gate is a
    no-op, never raises regardless of what the gate text says."""
    _assert_scene_location_declared("nothing about any room here at all", None)
    _assert_scene_location_declared("nothing about any room here at all", "")


# =============================================================================
# L30 — end to end through _plan_sheet_prompts (the kitchen regression)
# =============================================================================

def test_kitchen_regression_single_location_injection_makes_the_gate_pass():
    """The exact incident this chunk fixes: a scene whose script declares
    'the kitchen at home' but whose planner-authored set_line never says
    so. _plan_sheet_prompts must inject the location into the FIXED SET
    block before the L30 gate runs, so the assembled prompt's gate text
    ends up naming it and the gate passes (no raise) — never silently
    drawing a location-less board."""
    moments = [{"moment_number": 1, "location": None,
               "master": {"shot_type": "WS", "description": "Ryan stands at the island."},
               "angles": []}]
    prompts = _plan_sheet_prompts(
        moments, "style", panels_per_sheet=9,
        set_line="wooden counters, a fridge in the corner, sage cabinetry",  # never says "kitchen"
        axis_line="", setups_line="",
        location="the kitchen at home")
    assert "kitchen" in prompts[0].lower(), \
        f"FAIL: the assembled prompt never names the script's declared location: {prompts[0]!r}"


def test_kitchen_regression_raises_when_multi_location_plan_never_names_it():
    """Multi-location path (location_sets non-empty): the single-location
    injection is deliberately SKIPPED (a LOCSET header is expected to name
    its own location), so a plan whose LOCSET headers never mention the
    script's declared location must hard-block — the 'assembled WITHOUT
    it' case, reached through the real composer rather than the bare
    assert."""
    moments = [{"moment_number": 1, "location": "Bedroom",
               "master": {"shot_type": "WS", "description": "test"}, "angles": []}]
    with pytest.raises(SheetPromptContractViolation, match="L30"):
        _plan_sheet_prompts(
            moments, "style", panels_per_sheet=9, set_line="",
            axis_line="", setups_line="",
            location_sets={"Bedroom": "a bed, a nightstand"},
            location="the kitchen at home")


def test_location_none_never_raises_l30_byte_identical_to_before():
    """None/"" location (every legacy video) — _plan_sheet_prompts must
    behave exactly as it did before this chunk existed: no injection, no
    gate, nothing to raise."""
    moments = [{"moment_number": 1, "location": None,
               "master": {"shot_type": "WS", "description": "test"}, "angles": []}]
    _plan_sheet_prompts(moments, "style", panels_per_sheet=9, set_line="a plain set",
                        axis_line="", setups_line="", location=None)  # no raise
    _plan_sheet_prompts(moments, "style", panels_per_sheet=9, set_line="a plain set",
                        axis_line="", setups_line="", location="")  # no raise


# =============================================================================
# _match_scene_env — scripts.location preference over prose phrase-scoring
# =============================================================================

def test_match_scene_env_prefers_canonical_location_over_prose_score():
    """cd5d2883-style incident, modeled: the scene's OWN prose would
    mis-lock to the classroom under the existing word-count fallback (the
    word 'classroom' repeats three times, nothing named 'kitchen'), but
    the script's own canonical scripts.location must win outright, before
    the phrase-scoring chain even runs."""
    envs = [
        {"name": "Kitchen at home"},
        {"name": "School classroom"},
    ]
    scene_text = "In the classroom, you use a knife. classroom classroom."
    matched = _match_scene_env(scene_text, envs, location="the kitchen at home")
    assert matched["name"] == "Kitchen at home", \
        f"FAIL: location preference didn't override prose scoring: {matched!r}"


def test_match_scene_env_control_same_text_without_location_mislocks():
    """Control proving the fixture above genuinely reproduces the mis-lock
    the location preference now prevents: WITHOUT a location hint, the
    existing prose chain locks to the classroom."""
    envs = [
        {"name": "Kitchen at home"},
        {"name": "School classroom"},
    ]
    scene_text = "In the classroom, you use a knife. classroom classroom."
    matched = _match_scene_env(scene_text, envs)
    assert matched["name"] == "School classroom", \
        "sanity: fixture must reproduce the mis-lock this chunk prevents"


def test_match_scene_env_exact_normalized_location_match():
    envs = [{"name": "The Kitchen At Home"}, {"name": "School classroom"}]
    matched = _match_scene_env("irrelevant scene text", envs, location="the kitchen at home")
    assert matched["name"] == "The Kitchen At Home"


def test_match_scene_env_location_containment_leading_article():
    """Exact match fails on a leading-article difference ('the kitchen at
    home' vs 'Kitchen at home'); containment either way must still catch
    it — this is the documented reason the preference checks containment
    as a second pass, not just equality."""
    envs = [{"name": "Kitchen at home"}, {"name": "School classroom"}]
    matched = _match_scene_env("irrelevant scene text", envs, location="the kitchen at home")
    assert matched["name"] == "Kitchen at home"


# =============================================================================
# Props extraction — parse_coverage's [PROPS | ...] parsing + the WARN check
# =============================================================================

PROPS_DIRECTIVE_ECHOED = """\
[SET | the kitchen at home: a wooden island, a fridge in the corner]
[AXIS | Ryan frame-LEFT looking frame-RIGHT; key light from screen-left. Holds in every \
shot unless the shot says NEUTRAL]
[SETUPS | A: WS two-shot at the island]

[MOMENT 1 | Ryan hands over the tickets]
LINE: Ryan | "Here, two tickets — Dos boletos."
[PROPS | two tickets, Dos boletos]
- MASTER [MS]: (SETUP A) Ryan holds up two tickets marked Dos boletos toward Vanessa \
across the island.

[MOMENT 2 | Vanessa salutes the trash can]
[PROPS | saluting the trash can]
- MASTER [WS]: (SETUP A) Vanessa stands at attention, saluting the trash can beside \
the counter.
"""

PROPS_DIRECTIVE_MISSING = """\
[SET | the kitchen at home: a wooden island]
[AXIS | Ryan frame-LEFT looking frame-RIGHT; key light from screen-left. Holds in every \
shot unless the shot says NEUTRAL]
[SETUPS | A: WS two-shot at the island]

[MOMENT 1 | Ryan hands over the tickets]
LINE: Ryan | "Here, two tickets — Dos boletos."
[PROPS | two tickets, Dos boletos]
- MASTER [MS]: (SETUP A) Ryan smiles warmly at Vanessa across the island.

[MOMENT 2 | Vanessa salutes the trash can]
[PROPS | saluting the trash can]
- MASTER [WS]: (SETUP A) Vanessa stands at attention near the counter.
"""


def test_parse_coverage_populates_moment_props():
    moments = parse_coverage(PROPS_DIRECTIVE_ECHOED)
    assert len(moments) == 2
    assert moments[0]["props"] == ["two tickets", "Dos boletos"]
    assert moments[1]["props"] == ["saluting the trash can"]


def test_parse_coverage_props_empty_list_for_legacy_plan():
    """Byte-compatibility: a plan with no [PROPS|...] row at all parses to
    props=[] for every moment — never None, never a KeyError for a caller
    that does moment.get('props') or []."""
    legacy = "[MOMENT 1 | x]\n- MASTER [WS]: a plain establishing shot.\n"
    moments = parse_coverage(legacy)
    assert moments[0]["props"] == []


def test_check_prop_action_presence_zero_when_every_prop_is_drawn():
    moments = parse_coverage(PROPS_DIRECTIVE_ECHOED)
    assert check_prop_action_presence(moments) == 0


def test_check_prop_action_presence_warns_when_props_never_drawn():
    """The scene5-water-bottle / Dos-boletos-tickets incident, modeled: all
    three extracted props/actions are named by the planner's own
    [PROPS|...] lines but never appear in any shot description — 3
    distinct warnings ('two tickets', 'Dos boletos', 'saluting the trash
    can')."""
    moments = parse_coverage(PROPS_DIRECTIVE_MISSING)
    assert check_prop_action_presence(moments) == 3


def test_check_prop_action_presence_never_raises_on_missing_props():
    """WARN-only, never a gate: even a scene entirely missing every
    extracted prop must return an int, never raise."""
    moments = parse_coverage(PROPS_DIRECTIVE_MISSING)
    result = check_prop_action_presence(moments)
    assert isinstance(result, int)


def test_check_prop_action_presence_zero_for_legacy_plan_with_no_props():
    legacy = "[MOMENT 1 | x]\n- MASTER [WS]: a plain establishing shot.\n"
    moments = parse_coverage(legacy)
    assert check_prop_action_presence(moments) == 0


def test_check_prop_action_presence_scene_wide_not_moment_by_moment():
    """A prop introduced in one moment's [PROPS|...] line may legitimately
    be drawn in a NEIGHBORING moment's shot instead of its own — the check
    must look scene-wide, not per-moment."""
    directive = """\
[MOMENT 1 | Ryan mentions the tickets]
LINE: Ryan | "I have two tickets."
[PROPS | two tickets]
- MASTER [MS]: Ryan looks at Vanessa, smiling.

[MOMENT 2 | the tickets appear]
- MASTER [WS]: An insert on the two tickets resting on the counter.
"""
    moments = parse_coverage(directive)
    assert check_prop_action_presence(moments) == 0
