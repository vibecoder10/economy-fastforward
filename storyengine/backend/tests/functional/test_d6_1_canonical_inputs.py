"""D6-1 (BOARD-PLANNER-ARCHITECTURE.md, BOARD-LAWS.md L3/L6/L20/L28/L29) —
canonical cast/style/set inputs inserted VERBATIM, plus the two live law
violations this chunk fixes in the sheet composer
(scripts/coverage_to_app.py's _sheet_header / _plan_sheet_prompts).

STASH-PROOF: every test in the two "LIVE BUG" sections below imports
SheetPromptContractViolation / _assert_single_style_declaration /
_assert_no_unattached_claims — none of which exist before D6-1 — so `git
stash` on this branch makes this whole file fail at COLLECTION (ImportError),
which is the loudest possible "before" failure. The bug-reproduction tests
additionally prove the gates catch the EXACT text shape the real 2026-07-30
proof run emitted, independent of whether _sheet_header itself is fixed.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_d6_1_canonical_inputs.py -q
"""
import os
import sys

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
_PIPELINE_PATH = os.path.join(_BACKEND, "..", "..", "..", "skills", "video-pipeline")
sys.path.insert(0, os.path.abspath(_BACKEND))
sys.path.insert(0, os.path.abspath(_PIPELINE_PATH))

from scripts.coverage_to_app import (  # noqa: E402
    _plan_sheet_prompts, _sheet_header, _resolve_style,
    _canonical_material_line, _assert_single_style_declaration,
    _assert_no_unattached_claims, SheetPromptContractViolation,
)


# =============================================================================
# LIVE BUG 1 — L29 (DECLARE ONE STYLE, ONCE)
# =============================================================================

def test_l29_gate_reproduces_the_live_bug():
    """The EXACT shape the 2026-07-30 proof run emitted: a header claiming
    'for an animated scene' while the resolved style_line says something
    else entirely (BOARD-LAWS.md L29's own provenance). The gate must
    raise — this is the mechanical guarantee behind the prose fix."""
    bad_text = (
        "This is storyboard sheet 1 of 1 for an animated scene: a grid of 9 "
        "panels... Every panel uses the same art style, Photorealistic, "
        "cinematic film still, with matching lighting..."
    )
    with pytest.raises(SheetPromptContractViolation, match="L29"):
        _assert_single_style_declaration(bad_text, "Photorealistic, cinematic film still")


def test_l29_gate_passes_a_single_clean_declaration():
    good_text = (
        "This is storyboard sheet 1 of 1: a grid of 9 panels... Every panel "
        "uses the same art style, Photorealistic, cinematic film still, "
        "with matching lighting..."
    )
    _assert_single_style_declaration(good_text, "Photorealistic, cinematic film still")  # no raise


def test_l29_gate_allows_style_line_that_legitimately_says_animated():
    """A style_line that itself says 'animated' is fine — it's still ONE
    declaration, in the right place; the gate counts surplus occurrences,
    not the word itself."""
    style = "a 2D animated cartoon style"
    text = f"Every panel uses the same art style, {style}, consistently."
    _assert_single_style_declaration(text, style)  # no raise


def test_sheet_header_primary_no_longer_claims_animated_scene():
    """_sheet_header's own fix: the standalone 'for an animated scene'
    clause is gone outright — style_line is the ONLY place a style word
    appears."""
    header = _sheet_header(1, 1, 9, "Photorealistic, cinematic film still", variant="primary")
    assert "for an animated scene" not in header
    assert "Photorealistic, cinematic film still" in header


def test_plan_sheet_prompts_end_to_end_passes_l29_gate():
    """The real composer path: a scene whose style resolves to photoreal
    must not carry an 'animated' claim anywhere in the assembled prompt —
    proven by the fact that _plan_sheet_prompts (which runs the L29 gate
    internally) does not raise."""
    moments = [{"moment_number": 1, "location": None,
               "master": {"shot_type": "WS", "description": "An establishing shot."},
               "angles": []}]
    prompts = _plan_sheet_prompts(moments, "Photorealistic, cinematic film still",
                                  panels_per_sheet=9, set_line="a kitchen",
                                  axis_line="", setups_line="")
    assert "animated" not in prompts[0].lower()


# =============================================================================
# LIVE BUG 2 — L28 (NEVER ASSERT AN INPUT THAT IS NOT ATTACHED)
# =============================================================================

def test_l28_gate_reproduces_the_live_bug():
    """The exact claim BOARD-LAWS.md L28's provenance quotes verbatim,
    emitted while cast_refs was []. The gate must raise."""
    bad_text = ("Draw every character consistently across every panel, matching "
               "their appearance to the attached reference images.")
    with pytest.raises(SheetPromptContractViolation, match="L28"):
        _assert_no_unattached_claims(bad_text, cast_refs=False)


def test_l28_gate_passes_when_refs_genuinely_attached():
    text = ("Draw every character consistently across every panel, matching "
           "their appearance to the attached reference images.")
    _assert_no_unattached_claims(text, cast_refs=True)  # no raise


def test_l28_gate_checks_the_env_claim_too():
    bad_text = "every panel's background is this EXACT location as shown in the FINAL reference image"
    with pytest.raises(SheetPromptContractViolation, match="L28"):
        _assert_no_unattached_claims(bad_text, env_ref=False)
    _assert_no_unattached_claims(bad_text, env_ref=True)  # no raise


@pytest.mark.parametrize("variant", ["primary", "fallback"])
def test_sheet_header_omits_ref_claim_when_no_cast_refs(variant):
    header = _sheet_header(1, 1, 9, "style", variant=variant, has_cast_refs=False)
    assert "attached reference imag" not in header.lower()
    # Points at the CHARACTER block instead of claiming an absent input.
    assert "CHARACTER block" in header


@pytest.mark.parametrize("variant", ["primary", "fallback"])
def test_sheet_header_states_ref_claim_when_cast_refs_present(variant):
    header = _sheet_header(1, 1, 9, "style", variant=variant, has_cast_refs=True)
    assert "attached reference imag" in header.lower()


def test_plan_sheet_prompts_end_to_end_omits_claim_with_no_cast_refs():
    """The real composer path with has_cast_refs left at its default
    (False, the safe direction) — the assembled prompt must not claim
    attached references anywhere."""
    moments = [{"moment_number": 1, "location": None,
               "master": {"shot_type": "WS", "description": "An establishing shot."},
               "angles": []}]
    prompts = _plan_sheet_prompts(moments, "style", panels_per_sheet=9,
                                  set_line="a kitchen", axis_line="", setups_line="")
    assert "attached reference imag" not in prompts[0].lower()


# =============================================================================
# L3 gate — every panel location must have a canonical set entry
# =============================================================================

def test_l3_gate_raises_when_panel_location_has_no_matching_locset():
    moments = [{"moment_number": 1, "location": "Corridor",
               "master": {"shot_type": "WS", "description": "test"}, "angles": []}]
    with pytest.raises(SheetPromptContractViolation, match="L3"):
        _plan_sheet_prompts(moments, "style", location_sets={"Pod": "pod set text"})


def test_l3_gate_passes_when_every_location_matches():
    moments = [{"moment_number": 1, "location": "Pod",
               "master": {"shot_type": "WS", "description": "test"}, "angles": []}]
    _plan_sheet_prompts(moments, "style", location_sets={"Pod": "pod set text"})  # no raise


def test_l3_gate_is_case_and_punctuation_insensitive():
    """Matches _match_scene_env's own normalization — 'Home Kitchen' should
    match 'home kitchen' without a false-positive gate failure."""
    moments = [{"moment_number": 1, "location": "home kitchen",
               "master": {"shot_type": "WS", "description": "test"}, "angles": []}]
    _plan_sheet_prompts(moments, "style", location_sets={"Home Kitchen": "text"})  # no raise


# =============================================================================
# L20 — canonical material map wins over the planner LLM's own line
# =============================================================================

def test_canonical_material_line_single_location_from_matched_env():
    envs = [{"name": "Pod", "material_map": "glass front, solid rear"}]
    assert _canonical_material_line(envs, {}, envs[0]) == "glass front, solid rear"


def test_canonical_material_line_empty_when_nothing_canonical():
    assert _canonical_material_line([], {}, None) == ""
    assert _canonical_material_line([{"name": "Pod", "material_map": None}], {},
                                    {"name": "Pod", "material_map": None}) == ""


def test_canonical_material_line_multi_location_joins_only_authored_ones():
    envs = [
        {"name": "Pod", "material_map": "glass front, solid rear"},
        {"name": "Corridor", "material_map": ""},  # not authored yet
    ]
    location_sets = {"Pod": "pod dressing", "Corridor": "corridor dressing"}
    result = _canonical_material_line(envs, location_sets, None)
    assert "POD: glass front, solid rear" in result
    assert "CORRIDOR" not in result  # honest omission, not a fabricated clause


def test_canonical_material_line_name_matching_is_normalized():
    envs = [{"name": "Home Kitchen — Cram Session", "material_map": "wood counters"}]
    location_sets = {"home kitchen - cram session": "text"}
    result = _canonical_material_line(envs, location_sets, None)
    assert "wood counters" in result


def test_plan_sheet_prompts_material_block_uses_canonical_text_when_passed():
    """Composer-level proof: whatever the caller resolves as material_line
    (canonical or LLM-fallback) is inserted VERBATIM into the MATERIAL MAP
    block — no paraphrase."""
    moments = [{"moment_number": 1, "location": None,
               "master": {"shot_type": "WS", "description": "test"}, "angles": []}]
    prompts = _plan_sheet_prompts(
        moments, "style", panels_per_sheet=9, set_line="a set",
        axis_line="", setups_line="",
        material_line="THE CANONICAL SENTENCE, VERBATIM")
    assert "THE CANONICAL SENTENCE, VERBATIM" in prompts[0]


# =============================================================================
# _resolve_style precedence contract (L29's source of truth)
# =============================================================================

def test_resolve_style_image_style_override_wins_over_visual_style():
    _profile_a, style_a = _resolve_style("Claymation, stop-motion texture", "Photoreal")
    assert style_a is not None
    assert "claymation" in style_a.lower() or "clay" in style_a.lower()


def test_resolve_style_falls_back_to_visual_style_when_override_blank():
    _profile_b, style_b = _resolve_style("", "Photoreal")
    assert style_b is not None


def test_resolve_style_none_when_neither_set():
    _profile_c, style_c = _resolve_style(None, None)
    assert style_c is None


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(pytest.main([__file__, "-q"]))
