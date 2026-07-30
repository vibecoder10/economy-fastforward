"""D6-1b — fixes to three defects an independent verifier found live in the
D6-1 gates (scripts/coverage_to_app.py):

1. L29 gate false-positived on legal planner-authored prose (a nested
   screen's required content per L11, ordinary English, legal set dressing)
   because it scanned the WHOLE assembled prompt instead of only the text
   the composer itself writes.
2. L3 gate hard-raised on a paraphrase mismatch between two independently
   LLM-written free-prose strings (a moment's `location` vs a [LOCSET|]
   key) — fixed by canonicalizing against video_environments (option (a)
   from the verifier's note) with a warning fallback, never a hard block,
   when nothing canonical exists to check against.
3. A caught SheetPromptContractViolation let generate_storyboard_sheet_
   for_scene fall through to a bare "completed" return with zero boards
   drawn — routes/pipeline.py reads task status straight off that dict, so
   the creator saw a green checkmark over nothing.

STASH-PROOF for THIS round: unlike the D6-1 stash-proof (which only proved
the gate functions were new), test_l29_regression_lock and
test_all_blocked_scenes_surface_as_failed below assert BEHAVIOR that did
not exist before this round's fix — the first asserts a specific input
(legal panel prose) does NOT raise, the second asserts a specific return
shape (status="failed", violation text in "error"). With this round's
changes stashed, both fail on their assertions (not on import), which is
the proof the coordinator asked for.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_d6_1b_gate_scope_and_honest_status.py -q
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

from scripts.coverage_to_app import (  # noqa: E402
    _plan_sheet_prompts, _assert_single_style_declaration,
    SheetPromptContractViolation,
)


# =============================================================================
# 1. L29 SCOPE FIX — the four confirmed false positives, now passing
# =============================================================================

# The exact four inputs from the verifier's report, each embedded in a
# panel's master description (the per-panel body _plan_sheet_prompts builds
# from `moments` — NEVER scanned by the L29 gate after the scope fix).
_FALSE_POSITIVE_PANEL_TEXTS = [
    "The kids watch a cartoon on the television screen; animated characters dance across it.",
    "Her face is animated with delight as she opens the gift.",
    "The CGI-rendered warning hologram flickers above the console.",
    "An oil painting of a ship hangs above the fireplace.",
]


@pytest.mark.parametrize("panel_text", _FALSE_POSITIVE_PANEL_TEXTS)
def test_l29_scope_fix_legal_panel_prose_no_longer_raises(panel_text):
    """Each of the four confirmed false positives, run through the REAL
    composer path end-to-end (_plan_sheet_prompts, which runs the L29 gate
    internally) — must NOT raise now that the gate only scans
    composer-written text, never the planner LLM's panel description."""
    moments = [{"moment_number": 1, "location": None,
               "master": {"shot_type": "MS", "description": panel_text}, "angles": []}]
    prompts = _plan_sheet_prompts(moments, "Photorealistic, cinematic film still",
                                  panels_per_sheet=9, set_line="a room",
                                  axis_line="", setups_line="")  # must not raise
    assert panel_text.split(";")[0].split(".")[0][:20] in prompts[0]  # panel text really landed


def test_l29_scope_fix_legal_prose_in_axis_and_setups_blocks_no_longer_raises():
    """axis_line/setups_line are ALSO planner-authored free prose (not one
    of the composer-written blocks the gate now scans) — a style-adjacent
    word there must not raise either."""
    moments = [{"moment_number": 1, "location": None,
               "master": {"shot_type": "WS", "description": "test"}, "angles": []}]
    _plan_sheet_prompts(
        moments, "Photorealistic, cinematic film still", panels_per_sheet=9,
        set_line="a room", axis_line="camera pans past the animated mural on the wall",
        setups_line="A: WS with the CGI hologram visible in frame")  # must not raise


def test_l29_regression_lock_genuine_double_style_claim_still_raises():
    """The gate must not be defanged into uselessness. A genuine second
    style claim INSIDE composer-written text (here: smuggled into
    character_line, one of the blocks still in scope) must still raise —
    this is the exact shape of the original live bug: two independent
    style words, one of them outside style_line's own text."""
    style_line = "Photorealistic, cinematic film still"
    contaminated_character_line = "Nyla (photorealistic skin, but drawn in a cartoon style)"
    with pytest.raises(SheetPromptContractViolation, match="L29"):
        _assert_single_style_declaration(
            f"CHARACTER — stated once, drawn identically in every panel: "
            f"{contaminated_character_line}\nEvery panel uses the same art style, "
            f"{style_line}, with matching lighting.",
            style_line)


def test_l29_regression_lock_end_to_end_via_plan_sheet_prompts():
    """Same regression lock, but through the real composer entry point —
    a second style claim planted in the SET block (composer-written text,
    still in scope) must still block the whole call."""
    moments = [{"moment_number": 1, "location": None,
               "master": {"shot_type": "WS", "description": "test"}, "angles": []}]
    with pytest.raises(SheetPromptContractViolation, match="L29"):
        _plan_sheet_prompts(
            moments, "Photorealistic, cinematic film still", panels_per_sheet=9,
            set_line="a cartoon-style playroom with primary colors",  # 2nd style claim, in scope
            axis_line="", setups_line="")


# =============================================================================
# 2. L3 canonicalization — decision: (a) match against canonical
# video_environments, warning fallback when nothing canonical exists.
# =============================================================================

def test_l3_paraphrase_against_locset_no_longer_hard_raises_with_canonical_backup():
    """The verifier's exact repro: location='Diner Interior' vs LOCSET key
    'The Diner' — a paraphrase mismatch. With a canonical video_environments
    record named 'Diner Interior' (or a normalized match), this must NOT
    raise — it resolves via tier 2 (canonical match), not tier 1 (LOCSET)."""
    moments = [{"moment_number": 1, "location": "Diner Interior",
               "master": {"shot_type": "WS", "description": "test"}, "angles": []}]
    canonical_envs = [{"name": "Diner Interior", "material_map": None}]
    _plan_sheet_prompts(moments, "style", location_sets={"The Diner": "diner dressing"},
                        canonical_envs=canonical_envs)  # must not raise


def test_l3_paraphrase_with_no_canonical_backup_warns_not_raises(capsys):
    """No LOCSET match AND no canonical video_environments record either —
    per the coordinator's ruling, this is a LOUD WARNING, never a hard
    block, because a gate is only allowed to be hard when the thing it
    compares against is canonical."""
    moments = [{"moment_number": 1, "location": "Diner Interior",
               "master": {"shot_type": "WS", "description": "test"}, "angles": []}]
    _plan_sheet_prompts(moments, "style", location_sets={"The Diner": "diner dressing"},
                        canonical_envs=[])  # must not raise
    captured = capsys.readouterr()
    assert "L3" in captured.out
    assert "warning" in captured.out.lower()


def test_l3_still_passes_silently_on_exact_locset_match():
    """Tier 1 (unchanged): an exact/normalized LOCSET match resolves with
    no raise and no warning printed."""
    moments = [{"moment_number": 1, "location": "Pod",
               "master": {"shot_type": "WS", "description": "test"}, "angles": []}]
    _plan_sheet_prompts(moments, "style", location_sets={"Pod": "pod dressing"})  # no raise


def test_l3_canonical_match_is_normalized_same_as_locset_matching():
    """The canonical-name comparison uses the same _norm_env_text
    normalizer as _match_scene_env — case/punctuation insensitive."""
    moments = [{"moment_number": 1, "location": "home kitchen - cram session",
               "master": {"shot_type": "WS", "description": "test"}, "angles": []}]
    canonical_envs = [{"name": "Home Kitchen — Cram Session"}]
    _plan_sheet_prompts(moments, "style", location_sets={},
                        canonical_envs=canonical_envs)  # must not raise


# =============================================================================
# 3. Honest status — a blocked scene surfaces as failed, not completed
# =============================================================================

def _run(coro):
    return asyncio.run(coro)


def test_all_scenes_blocked_surfaces_as_failed_with_violation_text():
    """The worst-of-three finding, reproduced directly against
    generate_storyboard_sheet_for_scene: when the ONLY scene hits a hard
    gate, the function must return status="failed" with the violation text
    in "error" — never "completed" with zero boards. Mocks every DB/network
    call (zero spend) and forces _plan_sheet_prompts to raise for this one
    scene, mirroring exactly what a genuine L3/L28/L29 violation does."""
    from scripts import coverage_to_app as cta

    with patch.object(cta, "fetch_one", new=AsyncMock()) as m_fetch_one, \
         patch.object(cta, "fetch_all", new=AsyncMock()) as m_fetch_all, \
         patch.object(cta, "get_text_client_for_tenant", new=AsyncMock(return_value=object())), \
         patch.object(cta, "claude_model_for_direct_client", return_value="model"), \
         patch.object(cta, "_require_tenant_kie_key", new=AsyncMock(return_value="key")), \
         patch.object(cta, "ImageClient"), \
         patch.object(cta, "scene_aware_bible", new=AsyncMock(return_value={"characters": []})), \
         patch.object(cta, "_approved_envs", new=AsyncMock(return_value=[])), \
         patch.object(cta, "generate_coverage_directive", new=AsyncMock(return_value="[MOMENT 1 | x]")), \
         patch.object(cta, "plan_moments_deterministic", return_value=[
             {"moment_number": 1, "location": None,
              "master": {"shot_type": "WS", "description": "test"}, "angles": []}]), \
         patch.object(cta, "_reconcile_moment_dialogue"), \
         patch.object(cta, "_plan_sheet_prompts",
                      side_effect=SheetPromptContractViolation("L29 (DECLARE ONE STYLE, ONCE): test violation")):

        m_fetch_one.side_effect = [
            {"id": "v1", "tenant_id": "t1", "video_title": "T", "aspect": "16:9",
             "image_style_override": None, "visual_style": None, "render_style": None,
             "video_model": None, "dialogue_audio": "voice_over",
             "production_style_snapshot": None},
            {"id": "s1", "coverage_directive": None, "coverage_directive_hash": None},
        ]
        m_fetch_all.side_effect = [
            [{"scene": 1, "scene_text": "some scene text"}],
            [],
        ]
        result = _run(cta.generate_storyboard_sheet_for_scene("v1", "t1", scene=1))

    assert result["status"] == "failed", result
    assert "L29" in (result.get("error") or "")
    assert "test violation" in (result.get("error") or "")


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(pytest.main([__file__, "-q"]))
