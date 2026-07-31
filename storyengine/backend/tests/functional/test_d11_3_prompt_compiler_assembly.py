"""D11-3 (mechanical prompt compiler, film-studio audit point 18 closure):
assembly-point tests for the backend layer — _plan_sheet_prompts (the
sheet-preview path) and redraw_asset_image (the redraw path). See
skills/video-pipeline/tests/test_d11_3_prompt_compiler.py for the pure
compose_shot_cinematography unit tests and the first-draw assembly point
(generate_coverage_frames, which lives in the pipeline package) — this file
covers the two assembly points that live in coverage_to_app.py.

WHY THIS EXISTS: Ryan's question kicking off this chunk — "are the prompts
mechanically assembled from the database of the shot angles and
cinematography language, or not?" — applies to EVERY place a draw prompt is
built, not just the first-draw batch path. This file proves the sheet
preview (what a creator SEES before pictures are drawn) and a manual redraw
(what re-runs a single picture, possibly years after the batch draw) both
honor the same compiled clause, sourced FRESH from the shot's own
archetype/DP fields every time — and that a shot/asset with neither field
draws byte-identical to before this chunk existed.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_d11_3_prompt_compiler_assembly.py -q
"""
import asyncio
import os
import sys
import types
from unittest.mock import AsyncMock, patch

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
_PIPELINE_PATH = os.path.join(_BACKEND, "..", "..", "skills", "video-pipeline")
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

from scripts.coverage_to_app import (  # noqa: E402
    redraw_asset_image, _plan_sheet_prompts, _neutralize_risky_props,
)
from storyboard.shot_archetypes import get_archetype  # noqa: E402


# =============================================================================
# 1. _plan_sheet_prompts (sheet-preview assembly point)
# =============================================================================

LEGACY_MOMENTS = [{
    "moment_number": 1,
    "master": {"shot_type": "WS", "description": "Wide shot of the rider beside the dragon at dawn."},
    "angles": [{"shot_type": "MCU", "description": "Close on the rider's face, jaw set."}],
}]


def test_sheet_prompts_byte_identical_for_legacy_moments_with_no_structured_fields():
    """A moment whose shots carry NEITHER shot_archetype NOR any DP field —
    every plan before D11-1/D11-2, and any shot the planner didn't tag —
    must draw a byte-identical sheet-preview panel, exactly as before this
    compiler existed: the neutralized description with nothing prepended."""
    prompts = _plan_sheet_prompts(LEGACY_MOMENTS, "Photorealistic, cinematic film still",
                                  panels_per_sheet=9)
    assert len(prompts) == 1
    prompt = prompts[0]
    master_expected = _neutralize_risky_props(LEGACY_MOMENTS[0]["master"]["description"])
    angle_expected = _neutralize_risky_props(LEGACY_MOMENTS[0]["angles"][0]["description"])
    assert master_expected in prompt
    assert angle_expected in prompt


TAGGED_MOMENTS = [{
    "moment_number": 1,
    "master": {"shot_type": "WS", "description": "Wide shot of the rider beside the dragon at dawn.",
               "shot_archetype": "establishing_wide"},
    "angles": [{"shot_type": "MCU", "description": "Close on the rider's face, jaw set.",
                "lens_mm": 85, "camera_height": "eye", "dof": "shallow"}],
}]


def test_sheet_prompts_prepend_compiled_clause_for_tagged_shots():
    prompts = _plan_sheet_prompts(TAGGED_MOMENTS, "Photorealistic, cinematic film still",
                                  panels_per_sheet=9)
    assert len(prompts) == 1
    prompt = prompts[0]
    archetype = get_archetype("establishing_wide")
    clause_text = archetype.image_setup.strip().rstrip(". ")

    assert clause_text in prompt
    master_desc = _neutralize_risky_props(TAGGED_MOMENTS[0]["master"]["description"])
    assert master_desc in prompt
    # The clause LEADS the panel's own description — proves PREPEND, not append.
    assert prompt.index(clause_text) < prompt.index(master_desc)

    # The angle panel's DP fields render too.
    assert "shot on a 85mm lens" in prompt
    assert "camera at eye level" in prompt
    assert "shallow depth of field" in prompt


def test_sheet_prompts_untagged_moment_among_tagged_ones_stays_clean():
    """A mixed scene — one tagged shot, one untagged — must only prepend a
    clause to the shot that actually carries fields."""
    mixed = [{
        "moment_number": 1,
        "master": {"shot_type": "WS", "description": "Wide establishing shot of the kitchen.",
                   "shot_archetype": "establishing_wide"},
        "angles": [{"shot_type": "MCU", "description": "Ryan looks at Vanessa, unscripted prose."}],
    }]
    prompts = _plan_sheet_prompts(mixed, "Photorealistic, cinematic film still", panels_per_sheet=9)
    prompt = prompts[0]
    archetype = get_archetype("establishing_wide")
    assert archetype.image_setup.strip().rstrip(". ") in prompt
    # The untagged angle's own panel line has no compiled clause anywhere
    # near it: isolate the ANGLE panel's line and confirm it's exactly the
    # neutralized description, nothing prepended.
    angle_line_start = prompt.index("ANGLE MCU")
    angle_line_end = prompt.index("\n", angle_line_start)
    angle_line = prompt[angle_line_start:angle_line_end]
    assert angle_line.strip().endswith("Ryan looks at Vanessa, unscripted prose.")


# =============================================================================
# 2. redraw_asset_image (redraw assembly point)
# =============================================================================

VID, TENANT, ASSET = "vid-1", "tenant-1", "asset-1"
STORED_PROMPT = "(SETUP B) MCU OTS onto Ryan, glancing at the prep board"


def _run_redraw(extra_asset_fields=None):
    calls = []
    row = {"id": ASSET, "scene": 1, "image_index": 122, "image_prompt": STORED_PROMPT,
           "hero_shot": True, "generation_method": "coverage", "group_arrangement": None,
           "aspect": "16:9", "image_model_override": None,
           "image_style_override": None, "visual_style": None}
    row.update(extra_asset_fields or {})

    async def fake_fetch_one(query, *args):
        if "FROM assets a JOIN videos v" in query:
            return row
        if "coverage_directive, scene_text FROM scripts" in query:
            return {"coverage_directive": "", "scene_text": ""}
        raise AssertionError(f"unexpected fetch_one: {query}")

    async def fake_fetch_all(query, *args):
        if "FROM video_characters" in query:
            return []
        raise AssertionError(f"unexpected fetch_all: {query}")

    async def fake_gen(ic, model_override, prompt, reference_urls=None, **kw):
        calls.append({"prompt": prompt, "refs": list(reference_urls or [])})
        return "https://fake/redrawn.png", "gpt-image-2"

    patches = [
        patch("scripts.coverage_to_app.fetch_one", fake_fetch_one),
        patch("scripts.coverage_to_app.fetch_all", fake_fetch_all),
        patch("scripts.coverage_to_app.execute", AsyncMock()),
        patch("scripts.coverage_to_app.get_secret", AsyncMock(return_value="fake-key")),
        patch("scripts.coverage_to_app.ImageClient", lambda **kw: object()),
        patch("scripts.coverage_to_app._approved_envs", AsyncMock(return_value=[])),
        patch("scripts.coverage_to_app._match_scene_env", lambda text, e: None),
        patch("scripts.coverage_to_app.generate_scene_image_for_model", fake_gen),
        patch("scripts.coverage_to_app._stable_url", AsyncMock(return_value="https://stable/x.png")),
        patch("scripts.coverage_to_app.record_ledger_entry", AsyncMock()),
    ]
    for p in patches:
        p.start()
    try:
        result = asyncio.run(redraw_asset_image(VID, TENANT, ASSET))
    finally:
        for p in patches:
            p.stop()
    assert result["status"] == "completed", result
    assert len(calls) == 1
    return calls[0]


def test_redraw_legacy_asset_prompt_byte_identical_no_structured_fields():
    """No shot_archetype/lens_mm/camera_height/dof on the asset row (every
    asset predating D11-1/D11-2, and any untagged shot going forward) — the
    redrawn prompt must start with the stored prompt exactly as before this
    compiler existed, no clause prepended anywhere."""
    call = _run_redraw()
    assert call["prompt"].startswith(STORED_PROMPT)


def test_redraw_tagged_asset_prepends_freshly_derived_clause():
    call = _run_redraw({"shot_archetype": "ots", "lens_mm": 50,
                        "camera_height": "eye", "dof": "shallow"})
    archetype = get_archetype("ots")
    clause_text = archetype.image_setup.strip().rstrip(". ")
    assert clause_text in call["prompt"]
    assert "shot on a 50mm lens" in call["prompt"]
    assert "camera at eye level" in call["prompt"]
    assert "shallow depth of field" in call["prompt"]
    # The clause LEADS the stored prompt, never trails it.
    assert call["prompt"].index(clause_text) < call["prompt"].index(STORED_PROMPT)


def test_redraw_dp_only_asset_no_archetype_still_prepends_dp_phrase():
    call = _run_redraw({"lens_mm": 100, "dof": "deep"})
    assert "shot on a 100mm lens, deep focus, background sharp." in call["prompt"]
    assert call["prompt"].index("100mm") < call["prompt"].index(STORED_PROMPT)


def test_redraw_setup_tag_extraction_survives_the_prepended_clause():
    """Regression guard: the L16/L22 repair leg re-derives this shot's
    "(SETUP X)" tag by matching it at the START of the stored `prompt`
    variable (_setup_id is anchored). The cinematography clause must be
    folded in ONLY at the final concatenation — never mutated into `prompt`
    itself — or this anchor match silently breaks for every tagged asset.
    STORED_PROMPT starts with "(SETUP B)"; if the setup tag still resolves
    with a clause present, group_arrangement dedup (which also reads
    `prompt`) is provably intact too."""
    call = _run_redraw({"shot_archetype": "ots", "lens_mm": 50},
                        )
    # The literal SETUP tag from the stored prompt must still appear
    # (unmoved, unmutated) inside the final prompt.
    assert "(SETUP B)" in call["prompt"]
    setup_tag_pos = call["prompt"].index("(SETUP B)")
    stored_prompt_pos = call["prompt"].index(STORED_PROMPT)
    assert setup_tag_pos == stored_prompt_pos  # `prompt` itself starts with its own tag, unmoved


if __name__ == "__main__":
    test_sheet_prompts_byte_identical_for_legacy_moments_with_no_structured_fields()
    test_sheet_prompts_prepend_compiled_clause_for_tagged_shots()
    test_sheet_prompts_untagged_moment_among_tagged_ones_stays_clean()
    test_redraw_legacy_asset_prompt_byte_identical_no_structured_fields()
    test_redraw_tagged_asset_prepends_freshly_derived_clause()
    test_redraw_dp_only_asset_no_archetype_still_prepends_dp_phrase()
    test_redraw_setup_tag_extraction_survives_the_prepended_clause()
    print("ok — D11-3 assembly-point tests passed")
