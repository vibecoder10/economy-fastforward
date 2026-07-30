"""BOARD LAWS (storyengine/BOARD-LAWS.md) — the board-laws build lane's
acceptance test for the SHEET side of the prompt assembly
(scripts/coverage_to_app.py's _plan_sheet_prompts, the deterministic
composer that produces the text an image model actually draws from) and the
quality_rules board/image scope addition.

THE ACCEPTANCE TEST (test_end_to_end_multi_location_motion_scene_sheet_shape
below) runs a hand-authored directive — written to the SAME shape the new
_coverage_system_prompt rules ask the planner LLM to produce, modeled on the
approved acceptance target tasks/evidence/d3-64-fixes/
scene1_board_prompt_CORRECTED_v3.txt (multi-location pod/corridor + hatch +
BRIDGE run) — through the REAL deterministic pipeline (storyboard.coverage's
parsers -> _plan_sheet_prompts) and asserts the emitted sheet prompt text
satisfies each law's required element. It is honest about what an emitted
prompt satisfies vs a legacy single-location/dialogue fixture — see the
per-law assertions and this module's companion report.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_board_laws_sheet_and_quality_rules.py -q
"""
import os
import sys

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
_PIPELINE_PATH = os.path.join(_BACKEND, "..", "..", "..", "skills", "video-pipeline")
sys.path.insert(0, os.path.abspath(_BACKEND))
sys.path.insert(0, os.path.abspath(_PIPELINE_PATH))

from scripts.coverage_to_app import (  # noqa: E402
    _plan_sheet_prompts, _character_identity_line, _sheet_header,
)
from storyboard.coverage import (  # noqa: E402
    parse_coverage, parse_location_sets, parse_material_map, parse_set_dressing,
    parse_axis_line, parse_setups_line, scene_has_motion,
)
import quality_rules  # noqa: E402


# =============================================================================
# THE ACCEPTANCE TEST fixture — a directive in the NEW shape (multi-location,
# BRIDGE motion, material map), modeled on the approved acceptance target.
# =============================================================================

ACCEPTANCE_STYLE_DIRECTIVE = """\
[LOCSET | Pod | Nyla's glass bubble-pod: bed frame-LEFT, armchair CENTRE-RIGHT, a \
human-sized hatch set in the frame-LEFT curve, its sill flush with the catwalk outside. \
These props appear ONLY in Pod panels; never in Corridor panels.]
[LOCSET | Corridor | The underground warren catwalk: wet reflective floor plating, \
stacked glass pods receding into darkness. These props appear ONLY in Corridor panels; \
never in Pod panels.]
[MATERIAL | The pod is part clear glass at the front, part solid white shell at the rear \
and above; the boundary runs along the rib hub directly overhead.]
[AXIS | Nyla frame-LEFT looking frame-RIGHT; key light from screen-left. Holds in every \
shot unless the shot says NEUTRAL]
[SETUPS | A: WS two-shot outside the pod at bed height; F: WS low on the corridor \
catwalk, lens down the tunnel toward the vanishing point]

[MOMENT 1 | LOCATION: Pod | Nyla wakes on the bed]
- MASTER [WS]: (SETUP A) camera outside the pod at bed height, Nyla lies on the bed \
frame-left, eyes closed, occupying a tenth of the frame, three-quarter to the lens.

[MOMENT 2 | LOCATION: Pod | Nyla climbs through the hatch]
- MASTER [MS]: (SETUP A)(BRIDGE) Nyla climbs through the open human-sized hatch, exits \
frame-right and camera holds, one foot already down on the catwalk, to-lens.

[MOMENT 3 | LOCATION: Corridor | Nyla runs down the tunnel]
- MASTER [WS]: (SETUP F) camera low on the wet catwalk at floor height, Nyla small and \
running toward the frame-right vanishing point, the corridor's walls converging on it, \
past her near shoulder, face square to the lens.
"""

_CHARACTER_BIBLE = {
    "characters": [
        {"id": "Nyla", "costume": "shoulder-length black shaggy hair, charcoal grey bodysuit",
         "scenes_present": [1]},
    ],
}


def _build_acceptance_prompt():
    moments = parse_coverage(ACCEPTANCE_STYLE_DIRECTIVE)
    location_sets = parse_location_sets(ACCEPTANCE_STYLE_DIRECTIVE)
    prompts = _plan_sheet_prompts(
        moments, "Photorealistic, cinematic film still", panels_per_sheet=9,
        set_line=parse_set_dressing(ACCEPTANCE_STYLE_DIRECTIVE) or "",
        axis_line=parse_axis_line(ACCEPTANCE_STYLE_DIRECTIVE) or "",
        setups_line=parse_setups_line(ACCEPTANCE_STYLE_DIRECTIVE) or "",
        character_line=_character_identity_line(_CHARACTER_BIBLE, 1),
        location_sets=location_sets,
        material_line=parse_material_map(ACCEPTANCE_STYLE_DIRECTIVE) or "",
        motion_scene=scene_has_motion(moments, location_sets),
    )
    assert len(prompts) == 1, prompts
    return prompts[0]


def test_end_to_end_multi_location_motion_scene_sheet_shape():
    """The acceptance test. Runs the REAL deterministic pipeline
    (parse_coverage/parse_location_sets/parse_material_map/scene_has_motion
    -> _plan_sheet_prompts) on a fixture written in the new prompt-leg's
    required shape and asserts the FINAL emitted sheet-prompt text — what an
    image model would actually receive — satisfies each law's required
    element, matching the acceptance target's own structure
    (tasks/evidence/d3-64-fixes/scene1_board_prompt_CORRECTED_v3.txt)."""
    prompt = _build_acceptance_prompt()

    # L6 — CHARACTER stated once.
    assert "CHARACTER — stated once" in prompt
    assert "Nyla (shoulder-length black shaggy hair" in prompt

    # L3 — per-location SET blocks, each scoped, each forbidding cross-
    # contamination, instead of one blanket scene-wide FIXED SET line.
    assert "POD SET — applies ONLY to panels marked POD" in prompt
    assert "CORRIDOR SET — applies ONLY to panels marked CORRIDOR" in prompt
    assert "ONLY in Pod panels; never in" in prompt
    assert "FIXED SET — identical in EVERY panel" not in prompt  # replaced, not duplicated

    # L20 — material map, stated once.
    assert "MATERIAL MAP" in prompt
    assert "clear glass" in prompt and "solid white shell" in prompt

    # L4 — motion-capable CAMERA KIT wording, NOT the unconditional
    # "PLANTED... never move" text this exact scene shape used to get.
    assert "MOTION-CAPABLE" in prompt
    assert "PLANTED on the set and never move" not in prompt

    # Panel location tags (rides on L3): each panel names its location.
    assert "· POD" in prompt
    assert "· CORRIDOR" in prompt

    # L27 — the sheet header states what the caption strip may contain.
    assert "shows ONLY its number and shot type" in prompt or \
           "shows only its number and shot type" in prompt

    # Panel order preserved: Pod panels before the Corridor panel.
    pod_idx = prompt.index("· POD")
    corridor_idx = prompt.index("· CORRIDOR")
    assert pod_idx < corridor_idx


def test_legacy_single_location_scene_unaffected_by_new_params_when_absent():
    """Byte-compatibility control: a caller that never passes the new
    params (every caller before this chunk, and any single-location scene
    going forward) gets the ORIGINAL single-block shape — no CHARACTER
    block, no per-location blocks, no MOTION-CAPABLE wording, no location
    tags on panels."""
    moments = [{"moment_number": 1, "location": None,
               "master": {"shot_type": "WS", "description": "An establishing shot."},
               "angles": []}]
    prompts = _plan_sheet_prompts(
        moments, "Photorealistic, cinematic film still", panels_per_sheet=9,
        set_line="a plain kitchen", axis_line="", setups_line="A: WS establishing")
    prompt = prompts[0]
    assert "CHARACTER — stated once" not in prompt
    assert "SET — applies ONLY to panels marked" not in prompt
    assert "FIXED SET — identical in EVERY panel that shows the location: a plain kitchen" in prompt
    assert "MATERIAL MAP" not in prompt
    assert "MOTION-CAPABLE" not in prompt
    assert "PLANTED on the set and never move" in prompt
    assert "· " not in prompt.split("Draw these panels IN ORDER:")[0].split("[1]")[0]


def test_incoming_outgoing_placed_on_first_and_last_sheet_only():
    """L23-L26 rendering: INCOMING appears only on sheet 1, OUTGOING only on
    the last sheet. Force 2 sheets via a small panels_per_sheet cap."""
    moments = [
        {"moment_number": i, "location": None,
         "master": {"shot_type": "WS", "description": f"panel {i}"}, "angles": []}
        for i in range(1, 5)
    ]
    prompts = _plan_sheet_prompts(
        moments, "style", panels_per_sheet=2,
        set_line="", axis_line="", setups_line="",
        incoming={"description": "the previous scene's final panel", "relationship": "MATCH",
                  "instruction": "match its shape"},
        outgoing={"description": "her final panel here", "relationship": "CONTRAST"},
    )
    assert len(prompts) == 2
    assert "INCOMING —" in prompts[0]
    assert "OUTGOING —" not in prompts[0]
    assert "OUTGOING —" in prompts[1]
    assert "INCOMING —" not in prompts[1]


def test_sheet_header_states_caption_strip_contract_both_variants():
    for variant in ("primary", "fallback"):
        header = _sheet_header(1, 1, 9, "style", variant=variant)
        assert "only its" in header.lower() or "ONLY its" in header
        assert "number" in header and "shot type" in header


def test_character_identity_line_filters_by_scene_presence():
    bible = {"characters": [
        {"id": "Nyla", "costume": "black hair, grey bodysuit", "scenes_present": [1]},
        {"id": "GoldWoman", "costume": "gold gown", "scenes_present": [2]},
    ]}
    assert "Nyla" in _character_identity_line(bible, 1)
    assert "GoldWoman" not in _character_identity_line(bible, 1)
    assert _character_identity_line(None, 1) == ""
    assert _character_identity_line({"characters": []}, 1) == ""


# =============================================================================
# quality_rules board/image scope
# =============================================================================

def test_resolve_board_shape_is_its_own_axis():
    shape = quality_rules.resolve_board_shape()
    assert shape == {"board": True}
    assert "all" not in shape  # deliberate: see resolve_board_shape's docstring


def test_board_scoped_rule_matches_board_shape():
    assert quality_rules.rule_matches({"board": True}, quality_rules.resolve_board_shape())


def test_all_scoped_script_rule_does_not_leak_into_board_shape():
    """The core safety property: a tenant's pre-existing {"all": true}
    script rule (word floors, kill-phrase lists — everything authored
    before this scope existed) must NOT start matching board-stage
    resolution just because resolve_board_shape exists."""
    assert not quality_rules.rule_matches({"all": True}, quality_rules.resolve_board_shape())


def test_board_scoped_rule_does_not_leak_into_script_shape():
    """The reverse direction: a {"board": true} rule must not match a
    video's SCRIPT shape either — resolve_video_shape's dict has no "board"
    key at all, so a board-only rule never surfaces in script critique."""
    video_shape = quality_rules.resolve_video_shape({"render_mode": "static_docu"})
    assert "board" not in video_shape
    assert not quality_rules.rule_matches({"board": True}, video_shape)


def test_compose_rules_text_for_board_scope():
    rules = [{"rule_id": "BQ-1", "law": "Every hatch is human-sized.",
             "severity": "hard_gate", "applies_to": {"board": True}}]
    text, severity_by_rule = quality_rules.compose_rules_text(rules)
    assert "[BQ-1]" in text and "hatch is human-sized" in text
    assert severity_by_rule["BQ-1"] == "hard_gate"


if __name__ == "__main__":
    test_end_to_end_multi_location_motion_scene_sheet_shape()
    test_legacy_single_location_scene_unaffected_by_new_params_when_absent()
    test_incoming_outgoing_placed_on_first_and_last_sheet_only()
    test_sheet_header_states_caption_strip_contract_both_variants()
    test_character_identity_line_filters_by_scene_presence()
    test_resolve_board_shape_is_its_own_axis()
    test_board_scoped_rule_matches_board_shape()
    test_all_scoped_script_rule_does_not_leak_into_board_shape()
    test_board_scoped_rule_does_not_leak_into_script_shape()
    test_compose_rules_text_for_board_scope()
    print("ok — board laws (coverage_to_app.py sheet + quality_rules) self-checks passed")
