"""D15-5 (ONE canonical shot-context builder) — golden proof.

Before this chunk, the material-map / environment-locks canonical-
precedence logic existed as two hand-maintained copies:

  * assembler A (SHEET path, $0.05 board-sheet PREVIEW):
    scripts.coverage_to_app._canonical_material_line / _env_locks_text /
    _canonical_environment_locks_line
  * assembler B (FRAME path, the real per-shot draw prompts):
    storyboard.coverage.canonical_material_line / _env_locks_text /
    canonical_environment_locks_line

Both now delegate to storyboard.shot_context (see its module docstring for
the full reconciliation — the ONE genuine semantic difference found between
the two prior copies, and why it was resolved the way it was).

GOLDEN VALUES below were captured from the ORIGINAL, pre-refactor bodies of
BOTH assemblers (a scratch script run against the unmodified worktree,
before shot_context.py existed or either file was touched) and confirmed
byte-identical between A and B on every case — zero mismatches. After the
refactor, this file proves the SAME golden values still come out of: (1)
the shared shot_context functions directly, (2) assembler A's thin-alias
call sites, and (3) assembler B's thin-alias call sites (via storyboard.
coverage, imported through this file's own sys.path bootstrap).

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_d15_5_shot_context_goldens.py -q
"""
import os
import sys

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
_PIPELINE_PATH = os.path.join(_BACKEND, "..", "..", "..", "skills", "video-pipeline")
sys.path.insert(0, os.path.abspath(_BACKEND))
sys.path.insert(0, os.path.abspath(_PIPELINE_PATH))

import scripts.coverage_to_app as coverage_to_app  # noqa: E402
import storyboard.coverage as storyboard_coverage  # noqa: E402
import storyboard.shot_context as shot_context  # noqa: E402


# =============================================================================
# Fixture matrix (identical across all three call surfaces below)
# =============================================================================

ENVS_SINGLE_MATERIAL = [
    {"name": "Elite Viewing Hall", "material_map": "glass front, solid rear"},
]
ENVS_SINGLE_NULL_MATERIAL = [
    {"name": "Pod", "material_map": None},
]
ENVS_MULTI_MATERIAL_PARTIAL = [
    {"name": "Pod", "material_map": "glass front, solid rear"},
    {"name": "Corridor", "material_map": ""},  # not authored yet
]
ENVS_MULTI_LEADING_ARTICLE = [
    {"name": "Pod", "material_map": "POD MATERIAL: clear glass front, solid white rear"},
    {"name": "Elite Viewing Hall", "material_map": "HALL MATERIAL: solid ornamental walls"},
]
ENVS_NORMALIZED_DASH = [
    {"name": "Home Kitchen — Cram Session", "material_map": "wood counters"},
]

ENVS_SINGLE_LOCKS_FULL = [
    {"name": "Elite Viewing Hall", "architecture_lock": "curved amphitheater, 12 rows",
     "lighting_time_weather_lock": "dim, screen-glow only", "palette_lock": "black and gold"},
]
ENVS_SINGLE_LOCKS_NULL = [
    {"name": "Pod", "architecture_lock": None, "lighting_time_weather_lock": None, "palette_lock": None},
]
ENVS_MULTI_LOCKS_PARTIAL = [
    {"name": "Pod", "architecture_lock": "pod structure.", "lighting_time_weather_lock": None,
     "palette_lock": None},
    {"name": "Elite Viewing Hall", "architecture_lock": "hall structure.",
     "lighting_time_weather_lock": "hall light.", "palette_lock": None},
    {"name": "Corridor", "architecture_lock": None, "lighting_time_weather_lock": None,
     "palette_lock": None},
]
ENVS_MULTI_LOCKS_LEADING_ARTICLE = [
    {"name": "Pod", "architecture_lock": "POD ARCH: hexagonal glass cell",
     "lighting_time_weather_lock": None, "palette_lock": None},
    {"name": "Elite Viewing Hall", "architecture_lock": "HALL ARCH: curved amphitheater",
     "lighting_time_weather_lock": None, "palette_lock": None},
]
ENVS_MATERIAL_AND_LOCKS_TOGETHER = [
    {"name": "Pod", "material_map": "glass front, solid rear",
     "architecture_lock": "hexagonal cell", "lighting_time_weather_lock": "blue up-light",
     "palette_lock": "cold blue"},
]

LEADING_ARTICLE_LOCSET = {
    "The Elite Viewing Hall": "black ornamental walls with gold accents",
    "Pod": "the sealed glass bubble-pod",
}

# (args tuple, golden material_line, golden environment_locks_line-relevant fields live separately)
MATERIAL_CASES = [
    ("material_single_matched", (ENVS_SINGLE_MATERIAL, {}, ENVS_SINGLE_MATERIAL[0]),
     "glass front, solid rear"),
    ("material_no_matched_env", ([], {}, None), ""),
    ("material_single_null", (ENVS_SINGLE_NULL_MATERIAL, {}, ENVS_SINGLE_NULL_MATERIAL[0]), ""),
    ("material_multi_partial",
     (ENVS_MULTI_MATERIAL_PARTIAL, {"Pod": "pod dressing", "Corridor": "corridor dressing"}, None),
     "POD: glass front, solid rear"),
    ("material_normalized_dash",
     (ENVS_NORMALIZED_DASH, {"home kitchen - cram session": "text"}, None),
     "HOME KITCHEN - CRAM SESSION: wood counters"),
    ("material_leading_article", (ENVS_MULTI_LEADING_ARTICLE, LEADING_ARTICLE_LOCSET, None),
     "THE ELITE VIEWING HALL: HALL MATERIAL: solid ornamental walls "
     "POD: POD MATERIAL: clear glass front, solid white rear"),
    ("material_locset_no_match", (ENVS_SINGLE_MATERIAL, {"Some Unrelated Room": "text"}, None), ""),
    ("material_none_envs", (None, {"Pod": "..."}, None), ""),  # B's pinned None-safety contract
    ("combined_material",
     (ENVS_MATERIAL_AND_LOCKS_TOGETHER, {}, ENVS_MATERIAL_AND_LOCKS_TOGETHER[0]),
     "glass front, solid rear"),
]

LOCKS_TEXT_CASES = [
    ("locks_text_all_present", (ENVS_SINGLE_LOCKS_FULL[0],),
     "curved amphitheater, 12 rows; dim, screen-glow only; black and gold"),
    ("locks_text_partial",
     ({"architecture_lock": "structure facts.", "lighting_time_weather_lock": None,
       "palette_lock": None},), "structure facts."),
    ("locks_text_none", ({},), ""),
]

LOCKS_LINE_CASES = [
    ("locks_single_matched", (ENVS_SINGLE_LOCKS_FULL, {}, ENVS_SINGLE_LOCKS_FULL[0]),
     "curved amphitheater, 12 rows; dim, screen-glow only; black and gold"),
    ("locks_single_null", (ENVS_SINGLE_LOCKS_NULL, {}, ENVS_SINGLE_LOCKS_NULL[0]), ""),
    ("locks_no_matched", ([], {}, None), ""),
    ("locks_multi_partial",
     (ENVS_MULTI_LOCKS_PARTIAL,
      {"Pod": "pod set text", "Elite Viewing Hall": "hall set text", "Corridor": "corridor set text"},
      None),
     "POD: pod structure. ELITE VIEWING HALL: hall structure.; hall light."),
    ("locks_multi_all_null",
     ([{"name": "Pod", "architecture_lock": None, "lighting_time_weather_lock": None,
        "palette_lock": None}], {"Pod": "pod set text"}, None), ""),
    ("locks_leading_article", (ENVS_MULTI_LOCKS_LEADING_ARTICLE, LEADING_ARTICLE_LOCSET, None),
     "THE ELITE VIEWING HALL: HALL ARCH: curved amphitheater "
     "POD: POD ARCH: hexagonal glass cell"),
    ("locks_none_envs", (None, {"Pod": "..."}, None), ""),  # B's pinned None-safety contract
    ("combined_locks",
     (ENVS_MATERIAL_AND_LOCKS_TOGETHER, {}, ENVS_MATERIAL_AND_LOCKS_TOGETHER[0]),
     "hexagonal cell; blue up-light; cold blue"),
]


# =============================================================================
# 1. The shared module directly — both modes must agree (mode is inert today)
# =============================================================================

@pytest.mark.parametrize("name,args,golden", MATERIAL_CASES, ids=[c[0] for c in MATERIAL_CASES])
def test_shot_context_canonical_material_line_sheet_mode(name, args, golden):
    assert shot_context.canonical_material_line(*args, mode="sheet") == golden


@pytest.mark.parametrize("name,args,golden", MATERIAL_CASES, ids=[c[0] for c in MATERIAL_CASES])
def test_shot_context_canonical_material_line_frame_mode(name, args, golden):
    assert shot_context.canonical_material_line(*args, mode="frame") == golden


@pytest.mark.parametrize("name,args,golden", LOCKS_TEXT_CASES, ids=[c[0] for c in LOCKS_TEXT_CASES])
def test_shot_context_env_locks_text(name, args, golden):
    assert shot_context.env_locks_text(*args) == golden


@pytest.mark.parametrize("name,args,golden", LOCKS_LINE_CASES, ids=[c[0] for c in LOCKS_LINE_CASES])
def test_shot_context_canonical_environment_locks_line_sheet_mode(name, args, golden):
    assert shot_context.canonical_environment_locks_line(*args, mode="sheet") == golden


@pytest.mark.parametrize("name,args,golden", LOCKS_LINE_CASES, ids=[c[0] for c in LOCKS_LINE_CASES])
def test_shot_context_canonical_environment_locks_line_frame_mode(name, args, golden):
    assert shot_context.canonical_environment_locks_line(*args, mode="frame") == golden


def test_shot_context_invalid_mode_raises():
    with pytest.raises(ValueError, match="mode"):
        shot_context.canonical_material_line([], {}, None, mode="bogus")
    with pytest.raises(ValueError, match="mode"):
        shot_context.canonical_environment_locks_line([], {}, None, mode="bogus")


# =============================================================================
# 2. Assembler A's thin-alias call sites (scripts.coverage_to_app, SHEET path)
#    — proves the delegation is actually wired, not just that shot_context
#    works in isolation. A's original contract never receives envs=None at
#    any real call site, so the two None-envs cases are B-only (below).
# =============================================================================

@pytest.mark.parametrize("name,args,golden", MATERIAL_CASES, ids=[c[0] for c in MATERIAL_CASES])
def test_coverage_to_app_canonical_material_line_matches_golden(name, args, golden):
    # Reconciliation note (see shot_context's module docstring): assembler
    # A's ORIGINAL contract never received envs=None at any real call site
    # (`_approved_envs` always returns a list, `[]` on failure) and its bare
    # `for e in envs` would have raised TypeError on None — but now that A
    # delegates to the None-safe shared builder, the None case is simply
    # ALSO correct (a strict widening, never exercised in production either
    # way). Asserted here, not skipped, to prove the widening actually
    # landed rather than merely being claimed.
    assert coverage_to_app._canonical_material_line(*args) == golden


@pytest.mark.parametrize("name,args,golden", LOCKS_TEXT_CASES, ids=[c[0] for c in LOCKS_TEXT_CASES])
def test_coverage_to_app_env_locks_text_matches_golden(name, args, golden):
    assert coverage_to_app._env_locks_text(*args) == golden


@pytest.mark.parametrize("name,args,golden", LOCKS_LINE_CASES, ids=[c[0] for c in LOCKS_LINE_CASES])
def test_coverage_to_app_canonical_environment_locks_line_matches_golden(name, args, golden):
    # See the None-envs note on test_coverage_to_app_canonical_material_
    # line_matches_golden just above — same reconciliation, one clause over.
    assert coverage_to_app._canonical_environment_locks_line(*args) == golden


# =============================================================================
# 3. Assembler B's thin-alias call sites (storyboard.coverage, FRAME path)
# =============================================================================

@pytest.mark.parametrize("name,args,golden", MATERIAL_CASES, ids=[c[0] for c in MATERIAL_CASES])
def test_storyboard_coverage_canonical_material_line_matches_golden(name, args, golden):
    assert storyboard_coverage.canonical_material_line(*args) == golden


@pytest.mark.parametrize("name,args,golden", LOCKS_TEXT_CASES, ids=[c[0] for c in LOCKS_TEXT_CASES])
def test_storyboard_coverage_env_locks_text_matches_golden(name, args, golden):
    assert storyboard_coverage._env_locks_text(*args) == golden


@pytest.mark.parametrize("name,args,golden", LOCKS_LINE_CASES, ids=[c[0] for c in LOCKS_LINE_CASES])
def test_storyboard_coverage_canonical_environment_locks_line_matches_golden(name, args, golden):
    assert storyboard_coverage.canonical_environment_locks_line(*args) == golden


# =============================================================================
# 4. Cross-assembler agreement — A and B must produce the SAME string for
#    every case both can run (the actual anti-drift guarantee this chunk
#    exists to make structural instead of hand-maintained).
# =============================================================================

@pytest.mark.parametrize("name,args,golden", MATERIAL_CASES, ids=[c[0] for c in MATERIAL_CASES])
def test_a_and_b_agree_on_material_line(name, args, golden):
    b_result = storyboard_coverage.canonical_material_line(*args)
    assert b_result == golden
    assert coverage_to_app._canonical_material_line(*args) == b_result


@pytest.mark.parametrize("name,args,golden", LOCKS_LINE_CASES, ids=[c[0] for c in LOCKS_LINE_CASES])
def test_a_and_b_agree_on_environment_locks_line(name, args, golden):
    b_result = storyboard_coverage.canonical_environment_locks_line(*args)
    assert b_result == golden
    assert coverage_to_app._canonical_environment_locks_line(*args) == b_result


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
