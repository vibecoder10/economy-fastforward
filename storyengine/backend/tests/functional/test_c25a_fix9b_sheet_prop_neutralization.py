"""C25a-fix9b (2026-07-20, Ryan's ruling — tasks/decisions.md "NO nano-banana
fallback": GPT Image 2 only, fix the PROMPT STRUCTURE, no model fallbacks).

Root cause (live bisection, video cd5d2883-427e-4bfb-854d-8849d025d444, scene
2): OpenAI's content filter on gpt-image-2-image-to-image scores ACCUMULATED
risky-prop density across a whole sheet prompt. Sheet 1 passed live naming a
chef's knife ONCE (FIXED SET); sheet 2 400'd (failCode 400, creditsConsumed
0.0 — Kie/OpenAI reject before any generation, so a repro costs nothing)
because the SAME builder re-named the prop in CAMERA KIT's insert setup
("cutting board, knife") and again in nearly every panel brief ("knife",
"chopping motion", "cutting board") — our own boilerplate repetition, not the
creator's spoken lines.

Fix: scripts/coverage_to_app.py's _neutralize_risky_props() + the explicit
_RISKY_PROP_PATTERNS dictionary, wired into _plan_sheet_prompts so:
  - FIXED SET (set_line) is the ONE place a risky prop may be named plainly —
    NEVER passed through the pass.
  - CAPTION text (the verbatim spoken script) is NEVER passed through the
    pass — built straight from m["line"]/m["speaker"], concatenated onto the
    panel line AFTER neutralization already ran on the description alone.
  - AXIS/SCREEN-DIRECTION, panel numbering/order, SETUP letters, and
    character names/wardrobe are never touched (not in the pass's scope).
  - Every OTHER builder-authored segment (CAMERA KIT / setups_line, every
    panel brief's master+angle description) IS neutralized every time.

Pre-flight proof against the REAL gpt-image-2-image-to-image endpoint
(2026-07-20, tenant 44ecc95a-80f3-4261-8294-f963c03af2bd, same video/scene):
  - iter1 (the actual shipped design: FIXED SET named once, builder text
    elsewhere neutralized, captions untouched) — FAILED, failCode 400,
    creditsConsumed 0.0 (free).
  - iter2 (diagnostic: FIXED SET ALSO neutralized on top of iter1) — FAILED
    identically, free — proves FIXED SET's single mention was never the
    remaining trigger.
  - iter4 (diagnostic ONLY, NOT shippable: captions' knife/cut/cuchillo/
    cortar vocabulary also neutralized on top of iter2) — SUCCEEDED
    (taskId 550b012a5cc99a5cd831a628f02818ee, ~$0.05).
  This isolates the surviving trigger honestly: scene 2's CAPTIONS are a
  Spanish-vocabulary cooking lesson that repeats "knife"/"cuchillo" and
  "cut"/"cortar" across 6 of 9 panels — protected, verbatim, spoken-script
  content this fix must never touch and therefore cannot eliminate. The
  shipped fix removes 100% of the BUILDER's contribution to the density (the
  part this chunk owns); sheet 2 specifically still 400s on caption density
  alone, which is out of scope by explicit product law.

UPDATE (2026-07-21, honest boundary correction): iter2 above proved FIXED
SET's single mention was never THAT scene's remaining trigger, but a
DIFFERENT live scene the same night (a staged kitchen knife in FIXED SET)
got that single mention drawn into 30+ panels — the drawer paints whatever
FIXED SET stages into every panel showing the location, once is still every
panel. fix9b's single-naming exemption for FIXED SET was reasoned for the
PICTURES path's philosophy (name the real prop once, draw it once); a SHEET
is a throwaway preview that never feeds final art, so that exemption no
longer applies here. FIXED SET (set_line) and the sheet's LOCKED LOCATION
env description now ALSO run through _neutralize_risky_props — see
_plan_sheet_prompts's set_block and generate_storyboard_sheet_for_scene's
env_block in scripts/coverage_to_app.py. The PICTURES path (run_coverage) is
UNTOUCHED and keeps naming its real props plainly.
test_fixed_set_keeps_single_canonical_knife_mention below is renamed/updated
to pin this new behavior instead of the old exemption.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_c25a_fix9b_sheet_prop_neutralization.py -q
"""
import os
import subprocess
import sys

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
_PIPELINE_PATH = os.path.join(_BACKEND, "..", "..", "..", "skills", "video-pipeline")
sys.path.insert(0, os.path.abspath(_BACKEND))
sys.path.insert(0, os.path.abspath(_PIPELINE_PATH))

from scripts.coverage_to_app import (  # noqa: E402
    _neutralize_risky_props, _plan_sheet_prompts, _RISKY_PROP_PATTERNS,
)

# ---------------------------------------------------------------------------
# Prod-shaped fixture, modeled directly on the real failing shape (video
# cd5d2883 scene 2): a FIXED SET that names the knife once, a CAMERA KIT
# insert setup that historically re-named it, and panel briefs that repeat
# it — with a caption carrying the same word as VERBATIM spoken dialogue.
# ---------------------------------------------------------------------------
SET_LINE = ("Home Kitchen: vintage kitchen, wooden island center-frame with a "
            "cutting board and a chef's knife on it — fixed, nothing added or removed.")
AXIS_LINE = "Ryan frame-LEFT looking frame-RIGHT; Vanessa frame-RIGHT looking frame-LEFT."
SETUPS_LINE = ("A: WS two-shot at the island; E: INSERT low-angle on island props — "
               "cutting board, knife, potatoes, eggs, no people, NEUTRAL.")
MOMENTS = [
    {
        "moment_number": 7,
        "master": {
            "shot_type": "MCU OTS",
            "description": ("Ryan reaching toward the knife on the cutting board with a "
                             "skeptical squint."),
        },
        "angles": [
            {
                "shot_type": "INSERT",
                "description": ("NEUTRAL insert on the chef's knife resting on the cutting "
                                 "board beside a potato, golden light glinting off the blade."),
            },
            {
                "shot_type": "MCU",
                "description": "Vanessa making a slow chopping motion with her hand over the island.",
            },
        ],
        "speaker": "Ryan",
        "line": 'Do I peel with a knife? Wait, what\'s knife again?',
    },
]


def _build_prompt():
    prompts = _plan_sheet_prompts(
        MOMENTS, "Photorealistic, cinematic film still", panels_per_sheet=9,
        set_line=SET_LINE, axis_line=AXIS_LINE, setups_line=SETUPS_LINE,
    )
    assert len(prompts) == 1, prompts
    return prompts[0]


def _fixed_set_block(prompt: str) -> str:
    start = prompt.index("FIXED SET")
    end = prompt.index("SCREEN-DIRECTION LOCK")
    return prompt[start:end]


def _camera_kit_block(prompt: str) -> str:
    start = prompt.index("CAMERA KIT")
    end = prompt.index("Draw these panels IN ORDER:")
    return prompt[start:end]


def _panel_briefs_block(prompt: str) -> str:
    start = prompt.index("Draw these panels IN ORDER:")
    end = prompt.index("CONSTRAINTS:")
    return prompt[start:end]


# ---------------------------------------------------------------------------
# 1. UPDATED 2026-07-21: FIXED SET is now ALSO neutralized for sheet
#    previews (see the module docstring's UPDATE paragraph). This replaces
#    the original single-naming-exemption pin.
# ---------------------------------------------------------------------------

def test_fixed_set_is_now_also_neutralized_for_sheet_previews():
    prompt = _build_prompt()
    fixed_set = _fixed_set_block(prompt)
    assert "knife" not in fixed_set.lower(), fixed_set
    assert "the utensils" in fixed_set
    assert "the prep board" in fixed_set


# ---------------------------------------------------------------------------
# 2. Everywhere else builder-authored: zero risky-noun mentions.
# ---------------------------------------------------------------------------

def test_camera_kit_is_fully_neutralized():
    prompt = _build_prompt()
    camera_kit = _camera_kit_block(prompt)
    for term in ("knife", "cutting board", "chopping", "blade"):
        assert term not in camera_kit.lower(), (term, camera_kit)
    assert "the prep board" in camera_kit
    assert "the utensils" in camera_kit


def test_panel_brief_descriptions_are_fully_neutralized():
    prompt = _build_prompt()
    briefs = _panel_briefs_block(prompt)
    # Strip caption spans before asserting — captions legitimately carry the
    # word "knife" as spoken dialogue (product law) and must not be scanned
    # here; the boundary test below checks captions separately.
    import re
    non_caption = re.sub(r'CAPTION:.*?(?=\n\[|\Z)', '', briefs, flags=re.DOTALL)
    for term in ("knife", "cutting board", "chopping", "blade"):
        assert term not in non_caption.lower(), (term, non_caption)
    assert "the utensils" in non_caption
    assert "the prep board" in non_caption
    assert "a slicing-prep gesture" in non_caption


# ---------------------------------------------------------------------------
# 3. Boundary (updated by C25a-fix14, Ryan 2026-07-20): the verbatim spoken
#    line is NO LONGER baked into the sheet IMAGE at all. fix9b left one open
#    gap — a sheet could still 400 on OpenAI's content filter from CAPTION
#    density alone (protected dialogue we can't reword). Since the sheet is a
#    preview and the spoken lines live in the saved plan (they drive the real
#    pictures + voice), captions were dropped from the image prompt entirely.
#    So the spoken line and any "CAPTION" label must be ABSENT; the panel
#    itself (number + shot type + neutralized brief) is still present.
# ---------------------------------------------------------------------------

def test_spoken_line_is_not_baked_into_the_sheet():
    prompt = _build_prompt()
    assert "CAPTION" not in prompt, prompt
    assert "Do I peel with" not in prompt, prompt  # the spoken line is gone
    assert "[1] M7 MCU OTS" in prompt  # the panel is still there, text-free


def test_neutralize_risky_props_never_called_on_caption_field_directly():
    # Documents the boundary at the unit level: running the pass on the raw
    # caption line WOULD alter it (proving the function is not caption-safe by
    # itself). Under C25a-fix14 captions never reach the sheet image at all, so
    # the pass is never handed one — this keeps that guarantee explicit.
    raw_caption = "Do I peel with a knife?"
    assert _neutralize_risky_props(raw_caption) != raw_caption


# ---------------------------------------------------------------------------
# 4. Protected sections: AXIS line, panel numbering/order, SETUP letters —
#    untouched.
# ---------------------------------------------------------------------------

def test_axis_line_untouched():
    prompt = _build_prompt()
    assert AXIS_LINE in prompt, prompt


def test_panel_numbering_and_setup_letters_preserved():
    prompt = _build_prompt()
    assert "[1] M7 MCU OTS" in prompt
    assert "[2] M7 ANGLE INSERT" in prompt
    assert "[3] M7 ANGLE MCU" in prompt


# ---------------------------------------------------------------------------
# 5. Under-threshold text (nothing in the dictionary matches) passes through
#    byte-identical.
# ---------------------------------------------------------------------------

def test_neutralize_passthrough_when_nothing_matches():
    clean = "Ryan smiles warmly across the island at Vanessa, holding a bowl of eggs."
    assert _neutralize_risky_props(clean) == clean


def test_neutralize_passthrough_none_and_empty():
    assert _neutralize_risky_props(None) is None
    assert _neutralize_risky_props("") == ""


# ---------------------------------------------------------------------------
# 6. Regression: no doubled articles (a real bug caught and fixed during
#    this chunk before the pre-flight probe).
# ---------------------------------------------------------------------------

def test_no_doubled_article_on_bare_article_plus_noun():
    assert _neutralize_risky_props("the knife") == "the utensils"
    assert _neutralize_risky_props("a chef's knife") == "the utensils"
    assert _neutralize_risky_props("the cutting board") == "the prep board"
    assert "the the" not in _neutralize_risky_props("reaching for the knife on the cutting board")


def test_no_doubled_article_with_intervening_adjective():
    out = _neutralize_risky_props("making a slow chopping motion with her hand")
    assert out == "making a slicing-prep gesture with her hand", out
    assert "a slow a" not in out


# ---------------------------------------------------------------------------
# 7. The dictionary itself is inspectable / append-only in one place (design
#    requirement: future words get added to _RISKY_PROP_PATTERNS, nowhere else).
# ---------------------------------------------------------------------------

def test_dictionary_is_a_flat_ordered_pattern_replacement_list():
    assert isinstance(_RISKY_PROP_PATTERNS, list)
    assert len(_RISKY_PROP_PATTERNS) >= 10
    for pattern, replacement in _RISKY_PROP_PATTERNS:
        assert hasattr(pattern, "sub"), pattern  # a compiled regex
        assert isinstance(replacement, str) and replacement


# ---------------------------------------------------------------------------
# 8. py_compile guard — the module must always import/compile clean.
# ---------------------------------------------------------------------------

def test_coverage_to_app_compiles():
    target = os.path.abspath(os.path.join(_BACKEND, "scripts", "coverage_to_app.py"))
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", target], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


if __name__ == "__main__":
    test_fixed_set_is_now_also_neutralized_for_sheet_previews()
    test_camera_kit_is_fully_neutralized()
    test_panel_brief_descriptions_are_fully_neutralized()
    test_spoken_line_is_not_baked_into_the_sheet()
    test_neutralize_risky_props_never_called_on_caption_field_directly()
    test_axis_line_untouched()
    test_panel_numbering_and_setup_letters_preserved()
    test_neutralize_passthrough_when_nothing_matches()
    test_neutralize_passthrough_none_and_empty()
    test_no_doubled_article_on_bare_article_plus_noun()
    test_no_doubled_article_with_intervening_adjective()
    test_dictionary_is_a_flat_ordered_pattern_replacement_list()
    test_coverage_to_app_compiles()
    print("\nAll C25a-fix9b sheet-prop-neutralization tests passed.")
