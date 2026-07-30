"""D6-2 (storyengine/tasks/loop-checklist.md, PHASE D6): the decisive test —
does a SINGLE-SHOT REDRAW of an asset generated BEFORE this chunk landed
still carry BOARD-LAWS.md L11/L12/L15/L16/L17/L19/L22? This is the exact
failure class that cost $0.20 on 2026-07-29 (BOARD LAWS FOLLOW-UP A): a law
with only a PROMPT leg evaporates the moment a shot is redrawn, because
redraw_asset_image reuses assets.image_prompt VERBATIM as its base prompt.

L11/L12/L15/L19 are proven by BAKED-STAMP survival: STORED_PROMPT below
already carries the exact tail text run_coverage's build-time repair legs
(apply_nested_frame_content_lock / apply_population_lock / apply_attention_
orientation_lock / apply_pov_diegetic_lock) would have written, and the
test asserts that text is still present, byte-identical, in the redrawn
prompt.

L16/L22 are proven by FRESH RE-DERIVATION on a row that predates migration
143 — STORED_PROMPT deliberately carries NO reverse-background stamp and no
baked arrangement text, simulating a legacy asset row. The test asserts
redraw_asset_image computes and appends both fresh, from the scene's own
coverage_directive (parse_reverse_setup_pairs) and the asset's own
group_arrangement column — proving the repair heals even a row that never
got a build-time stamp, not just one that already had it.

L17 rides inside the SAME group_arrangement text (BOARD-LAWS.md rule 18
always pairs L17+L22 — apply_group_arrangement_lock repairs both together),
so its survival is covered by the L22 assertion.

L18 is DELIBERATELY not asserted here — this chunk gives it a new GATE but
no repair leg (see coverage.py's check_discovery_object_unremarked
docstring and the D6-2 commit message for why).

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_d6_2_repair_stamps.py -q
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

from scripts.coverage_to_app import redraw_asset_image  # noqa: E402

VID, TENANT, ASSET = "vid-1", "tenant-1", "asset-1"

# A LEGACY row (predates migration 143 / this chunk): (SETUP G) with NO
# reverse-background stamp, but WITH the L11/L12/L15/L19 baked tails a
# build-time run_coverage from BEFORE this chunk's L16/L22 fresh-rederivation
# would still have produced for those four laws (they were already
# baked-stamp-capable). This is deliberately the WORST case for L16/L22 (no
# prior stamp at all) and the PROVEN case for L11/L12/L15/L19 (stamp already
# present, must merely survive).
NESTED_FRAME_TAIL = (
    "Nested-frame content lock: the screen in this panel shows the SAME content "
    "established elsewhere in this scene — matching this scene's own screen content: "
    "\"the giant screen glows with the underground warren's live feed\"")
POPULATION_TAIL = (
    "Population lock: the background population's look is fixed for this whole scene, "
    "matching how it was established elsewhere: \"five elites in dark robes, hoods up, "
    "slouched\"")
ATTENTION_TAIL = (
    "Attention-vs-orientation lock: if this is a shift of ATTENTION rather than a full "
    "re-stage, state explicitly what stays FIXED (chair, hips, feet, the direction already "
    "established) and what MOVES (head, shoulders, gaze) — a partial turn must never read "
    "as the whole body and chair re-staging.")
POV_TAIL = (
    "Diegetic POV lock: this is a NEUTRAL setup occupying the in-story device's own "
    "position — the eyes go DIRECTLY into camera with no three-quarter softening, no "
    "flinch, no glance-away, and the device's own housing (lens casing, mirror frame) is "
    "never visible from inside itself.")

STORED_PROMPT = (
    f"(SETUP G) MCU on Old Man, three-quarter to camera, delivering his line. "
    f"{NESTED_FRAME_TAIL}. {POPULATION_TAIL}. {ATTENTION_TAIL} {POV_TAIL}"
)

COVERAGE_DIRECTIVE = (
    "[SETUPS | A: WS establishing the row from behind and above; B: MS on Gold Woman at "
    "seated eye height; G: MS reverse on Old Man, the matched reverse of B]"
)

# The CANONICAL arrangement computed and persisted at build time (migration
# 143's assets.group_arrangement) — deliberately NOT present anywhere in
# STORED_PROMPT, simulating a legacy row that predates the column.
GROUP_ARRANGEMENT = ("Old Man nearest camera at the frame-right end, then Gold Woman "
                     "toward frame-left")


def _run(image_prompt=STORED_PROMPT, coverage_directive=COVERAGE_DIRECTIVE,
        group_arrangement=GROUP_ARRANGEMENT):
    calls = []

    async def fake_fetch_one(query, *args):
        if "FROM assets a JOIN videos v" in query:
            return {"id": ASSET, "scene": 2, "image_index": 108, "image_prompt": image_prompt,
                    "hero_shot": False, "generation_method": "coverage",
                    "aspect": "16:9", "image_model_override": None,
                    "image_style_override": None, "visual_style": None,
                    "group_arrangement": group_arrangement}
        if "coverage_directive, scene_text FROM scripts" in query:
            return {"coverage_directive": coverage_directive, "scene_text": "the hall scene"}
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
    return calls[0]["prompt"]


# =============================================================================
# THE DECISIVE TEST — every one of the seven laws survives a single-shot
# redraw of a row that predates this chunk.
# =============================================================================

def test_redraw_inherits_all_seven_repaired_laws():
    prompt = _run()

    # L11 (NESTED FRAMES) — baked stamp, must survive byte-identical.
    assert NESTED_FRAME_TAIL in prompt, "L11 nested-frame content lock did not survive redraw"

    # L12 (SPECIFY THE POPULATION) — baked stamp, must survive byte-identical.
    assert POPULATION_TAIL in prompt, "L12 population lock did not survive redraw"

    # L15 (SEPARATE ATTENTION FROM ORIENTATION) — baked stamp, must survive.
    assert ATTENTION_TAIL in prompt, "L15 attention-orientation lock did not survive redraw"

    # L19 (DIEGETIC CAMERA POV) — baked stamp, must survive.
    assert POV_TAIL in prompt, "L19 diegetic-POV lock did not survive redraw"

    # L16 (A REVERSE ANGLE CHANGES THE BACKGROUND) — FRESH re-derivation:
    # this row NEVER had a reverse-background stamp baked in (STORED_PROMPT
    # carries none), yet the redraw computes it fresh from the scene's own
    # coverage_directive because this shot's SETUP G is stated there as the
    # matched reverse of SETUP B.
    assert "matched reverse of SETUP B" in prompt, "L16 reverse-background lock was not re-derived at redraw"
    assert "SETUP G is the matched reverse" in prompt

    # L17 + L22 (LOCK THE HEADCOUNT + STATE GROUP ARRANGEMENT PER CAMERA
    # POSITION) — FRESH re-derivation from the canonical assets.
    # group_arrangement column (migration 143), never baked into the stored
    # prompt either.
    assert GROUP_ARRANGEMENT in prompt, "L17/L22 group arrangement was not re-derived at redraw"

    # L18 is deliberately NOT asserted — no repair leg exists for it.


def test_redraw_does_not_double_stamp_when_build_time_already_baked_it():
    """If a FUTURE build-time redraw's stored prompt ALREADY carries the
    reverse-background reminder (post-migration-143 rows will), the fresh
    re-derivation at redraw time must not stamp it a second time."""
    already_stamped = (
        STORED_PROMPT + ". Reverse-angle background lock (computed): this camera SETUP G "
        "is the matched reverse of SETUP B. Whatever sits behind the subject in SETUP B "
        "must NOT reappear behind them here.")
    prompt = _run(image_prompt=already_stamped)
    assert prompt.count("matched reverse of SETUP B") == 1


def test_redraw_null_safe_with_no_setup_tag_and_no_canonical_arrangement():
    """NULL-SAFETY: a shot with no "(SETUP X)" tag at all (a legacy/NEUTRAL
    insert) and no group_arrangement column value must still redraw cleanly
    — no exception, no crash, the L16/L22 fresh-rederivation block simply
    adds nothing."""
    prompt = _run(
        image_prompt="A quiet insert on the props, no people, no setup tag at all.",
        coverage_directive=COVERAGE_DIRECTIVE,
        group_arrangement=None,
    )
    assert "matched reverse of SETUP" not in prompt
    assert "Group arrangement (canonical)" not in prompt
    assert prompt.startswith("A quiet insert on the props")


def test_redraw_null_safe_with_no_coverage_directive_row_at_all():
    """NULL-SAFETY: the scripts row itself missing/empty (a scene whose
    directive was never persisted) must not crash the redraw — fail-soft,
    exactly like the existing env-lock block."""
    prompt = _run(coverage_directive="", group_arrangement=None)
    assert "matched reverse of SETUP" not in prompt
    assert prompt.startswith(STORED_PROMPT[:40])


if __name__ == "__main__":
    test_redraw_inherits_all_seven_repaired_laws()
    test_redraw_does_not_double_stamp_when_build_time_already_baked_it()
    test_redraw_null_safe_with_no_setup_tag_and_no_canonical_arrangement()
    test_redraw_null_safe_with_no_coverage_directive_row_at_all()
    print("ok — D6-2 repair-stamp redraw tests passed")
