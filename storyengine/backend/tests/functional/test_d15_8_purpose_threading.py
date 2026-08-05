"""D15-8: thread purpose_kind/shot_purpose into assemblers A (sheet) and C
(redraw) — closes D15-1's "purpose fields consumed by only 1 of 3
assemblers" finding.

BACKGROUND: assembler B (run_coverage/generate_coverage_frames,
storyboard/coverage.py) already threads purpose_kind/shot_purpose onto its
frame dicts so store_scene can persist them (D9-1's "one real stamping
site" — sheet previews create NO asset rows, by design, and redraw's own
UPDATE never touches these columns either, so DB persistence was never
actually a gap for A or C: A structurally has nothing to stamp, and C's
partial-column UPDATE has never erased what B originally stamped). B also
runs the D9-1 check_shot_purpose_present WARN gate on every real draw — a
pure, print-only "worth a human glance" signal for a shot the planner never
gave a stated reason to exist. THAT diagnostic signal was the real,
provable "1 of 3" gap: neither the free sheet-preview pass (A) nor a redraw
(C) ever consulted it, so a creator got zero purpose-awareness unless they
were on the real-draw door.

THIS CHUNK:
  1. generate_storyboard_sheet_for_scene (assembler A) now calls the SAME
     check_shot_purpose_present(moments) B calls, right where D12-3's
     rhythm-notes already read purpose_kind for the monotony signal.
  2. redraw_asset_image (assembler C) now SELECTs shot_type/purpose_kind/
     shot_purpose (it never fetched these columns at all before, unlike its
     sibling D9/D11/D6-2 fields) and threads them into the SAME check via a
     synthetic single-shot moment — reusing the function verbatim, never
     re-implementing its wording.

Both call sites are diagnostic-only (print + a discarded int count, mirror
of B's own fire-and-forget usage) — purpose text is proven here, for A and
C, to NEVER reach an actual image-generation prompt string, exactly the
rule-23 discipline test_d9_1_shot_purpose.py already proved for B.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_d15_8_purpose_threading.py -q
"""
import asyncio
import os
import sys
import types
from unittest.mock import AsyncMock, patch

import pytest

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


_stub("database", fetch_one=_boom, fetch_all=_boom, execute=_boom)
_stub("storage", upload_bytes=_boom)
_stub("vault", get_secret=_boom)
_stub("kie_unified", get_text_client_for_tenant=_boom)

import scripts.coverage_to_app as cta  # noqa: E402
from scripts.coverage_to_app import (  # noqa: E402
    generate_storyboard_sheet_for_scene,
    redraw_asset_image,
)
from storyboard.coverage import (  # noqa: E402
    check_shot_purpose_present as _real_check_shot_purpose_present,
)

VIDEO_ID = "33333333-3333-3333-3333-333333333333"
TENANT_ID = "tenant-1"
SCENE_TEXT = "Ryan pushes through the hatch into the corridor."

DIRECTIVE_NO_PURPOSE = (
    "[MOMENT 1 | Ryan pushes through the hatch]\n"
    "- MASTER [WS]: Wide shot of Ryan pushing through the pod's hatch into the corridor, "
    "harsh fluorescent light replacing the pod's blue glow.\n"
    "- ANGLE [MCU]: Close on Ryan's face as the door seals behind him.\n"
)

DIRECTIVE_WITH_PURPOSE = (
    "[MOMENT 1 | Ryan pushes through the hatch]\n"
    "- MASTER [WS]: Wide shot of Ryan pushing through the pod's hatch into the corridor, "
    "harsh fluorescent light replacing the pod's blue glow.\n"
    "PURPOSE: spatial | shows exactly how Ryan gets from the pod to the corridor\n"
    "- ANGLE [MCU]: Close on Ryan's face as the door seals behind him.\n"
    "PURPOSE: emotion | the audience needs to see relief break through the tension\n"
)


def _video_row():
    return {
        "id": VIDEO_ID, "tenant_id": TENANT_ID, "video_title": "Test Video",
        "aspect": "16:9", "image_style_override": None,
        "visual_style": None, "style_preset_id": None,
        "image_model_override": None, "render_style": None,
        "video_model": "grok-imagine", "dialogue_audio": "voice_over",
    }


def _run_sheet_plan(directive, check_patch=None):
    """Runs generate_storyboard_sheet_for_scene(plan_only=True) — a zero-
    network, zero-DB-write dry run (D3-59) — against `directive`. Returns
    (result, sheet_prompts_captured): sheet_prompts_captured is the REAL
    _plan_sheet_prompts output (spied, delegating to the real function) —
    the actual per-panel text the sheet preview would draw."""
    captured_prompts = []
    real_plan_sheet_prompts = cta._plan_sheet_prompts

    def _spy_plan_sheet_prompts(moments, style_dir, **kwargs):
        prompts = real_plan_sheet_prompts(moments, style_dir, **kwargs)
        captured_prompts.append(prompts)
        return prompts

    async def fetch_one(query, *args):
        if "FROM videos WHERE id=$1" in query:
            return _video_row()
        if "coverage_directive, coverage_directive_hash FROM scripts" in query:
            return {"id": "script-1", "coverage_directive": None, "coverage_directive_hash": None}
        raise AssertionError(f"unexpected fetch_one: {query}")

    async def fetch_all(query, *args):
        if "SELECT scene, scene_text FROM scripts" in query:
            return [{"scene": 1, "scene_text": SCENE_TEXT}]
        if "FROM video_characters" in query:
            return []
        raise AssertionError(f"unexpected fetch_all: {query}")

    patches = [
        patch("scripts.coverage_to_app.fetch_one", fetch_one),
        patch("scripts.coverage_to_app.fetch_all", fetch_all),
        patch("scripts.coverage_to_app.execute", AsyncMock()),
        patch("scripts.coverage_to_app.get_secret", AsyncMock(return_value="fake-kie-key")),
        patch("scripts.coverage_to_app.get_text_client_for_tenant", AsyncMock(return_value=object())),
        patch("scripts.coverage_to_app.claude_model_for_direct_client", lambda c: "fake-model"),
        patch("scripts.coverage_to_app.scene_aware_bible", AsyncMock(return_value=None)),
        patch("scripts.coverage_to_app._approved_envs", AsyncMock(return_value=[])),
        patch("scripts.coverage_to_app.generate_coverage_directive", AsyncMock(return_value=directive)),
        patch("scripts.coverage_to_app._plan_sheet_prompts", _spy_plan_sheet_prompts),
    ]
    if check_patch is not None:
        patches.append(patch("scripts.coverage_to_app.check_shot_purpose_present", check_patch))
    for p in patches:
        p.start()
    try:
        result = asyncio.run(
            generate_storyboard_sheet_for_scene(VIDEO_ID, TENANT_ID, scene=1, plan_only=True))
    finally:
        for p in patches:
            p.stop()
    return result, captured_prompts


# =============================================================================
# Assembler A — generate_storyboard_sheet_for_scene (the sheet composer)
# =============================================================================

def test_sheet_composer_warns_on_untagged_shots_same_wording_as_assembler_b(capsys):
    """Behavior + wiring: assembler A's sheet-preview pass now calls the
    SAME check_shot_purpose_present gate assembler B calls on every real
    draw. A directive with no PURPOSE: rows prints the IDENTICAL warn line
    B would print for the same shots — not a reinvented message."""
    result, _ = _run_sheet_plan(DIRECTIVE_NO_PURPOSE)
    assert result["status"] == "completed", result
    out = capsys.readouterr().out
    assert "shot-purpose check (D9-1): moment 1 (WS) carries no PURPOSE: line" in out
    assert "shot-purpose check (D9-1): moment 1 (MCU) carries no PURPOSE: line" in out


def test_sheet_composer_silent_for_the_two_authored_shots_when_tagged(capsys):
    """The parsed purpose_kind/shot_purpose from a tagged directive reaches
    the check correctly — the two authored shots never warn (floor-added
    filler shots, if any, are a separate/expected signal, not asserted
    against here)."""
    result, _ = _run_sheet_plan(DIRECTIVE_WITH_PURPOSE)
    assert result["status"] == "completed", result
    out = capsys.readouterr().out
    assert "moment 1 (WS) carries no PURPOSE" not in out
    assert "moment 1 (MCU) carries no PURPOSE" not in out


def test_sheet_composer_purpose_check_is_really_wired():
    """Guard-neuter: if the call site is ever removed/broken, this raises —
    proves the wiring is real, not vacuous (mirrors D15-6/D15-7's own
    wiring-spy discipline)."""
    def _boom_check(moments):
        raise AssertionError("SHEET PURPOSE CHECK BOOM")

    with pytest.raises(AssertionError, match="SHEET PURPOSE CHECK BOOM"):
        _run_sheet_plan(DIRECTIVE_NO_PURPOSE, check_patch=_boom_check)


def test_sheet_panel_prompts_byte_identical_regardless_of_the_check():
    """PURPOSE-ABSENT golden proof: the actual per-panel prompt TEXT sent to
    draw is byte-identical whether check_shot_purpose_present is wired in or
    stubbed to a no-op — it is a pure, print-only side channel that never
    touches `moments` or _plan_sheet_prompts's output."""
    _, prompts_with_check = _run_sheet_plan(DIRECTIVE_NO_PURPOSE)
    _, prompts_without_check = _run_sheet_plan(
        DIRECTIVE_NO_PURPOSE, check_patch=lambda moments: 0)
    assert prompts_with_check == prompts_without_check
    assert prompts_with_check and prompts_with_check[0], "sanity: panels were actually planned"


def test_sheet_panel_prompt_text_never_leaks_purpose_text():
    """Rule 23 (INSTRUCTIONS ARE NOT CAPTIONS): even with a directive that
    tags every shot with a PURPOSE: row, the parsed shot_purpose prose must
    never ride into the drawn panel prompt — assembler A never leaks it,
    matching B's planted-marker discipline (test_d9_1_shot_purpose.py)."""
    _, prompts = _run_sheet_plan(DIRECTIVE_WITH_PURPOSE)
    assert prompts and prompts[0], "sanity: panels were actually planned"
    full_text = "\n".join(prompts[0])
    assert "PURPOSE:" not in full_text
    assert "shows exactly how Ryan gets from the pod to the corridor" not in full_text
    assert "the audience needs to see relief break through the tension" not in full_text


# =============================================================================
# Assembler C — redraw_asset_image (the redraw composer)
# =============================================================================

def _run_redraw(purpose_kind=None, shot_purpose=None, shot_type="MCU", check_patch=None):
    draw_calls = []
    check_calls = []

    async def fake_fetch_one(query, *args):
        if "FROM assets a JOIN videos v" in query:
            return {"id": "asset-1", "scene": 1, "image_index": 122,
                     "image_prompt": "(SETUP B) MCU OTS onto Ryan, glancing at the prep board",
                     "hero_shot": True, "generation_method": "coverage",
                     "shot_type": shot_type, "purpose_kind": purpose_kind,
                     "shot_purpose": shot_purpose,
                     "aspect": "16:9", "image_model_override": None,
                     "image_style_override": None, "visual_style": None, "style_preset_id": None}
        if "coverage_directive, scene_text FROM scripts" in query:
            return {"coverage_directive": "vintage kitchen plan", "scene_text": "kitchen scene"}
        raise AssertionError(f"unexpected fetch_one: {query}")

    async def fake_fetch_all(query, *args):
        if "FROM video_characters" in query:
            return [{"reference_url": "https://fake/cast-a.png"}]
        raise AssertionError(f"unexpected fetch_all: {query}")

    async def fake_gen(ic, model_override, prompt, reference_urls=None, **kw):
        draw_calls.append({"prompt": prompt, "refs": list(reference_urls or [])})
        return "https://fake/redrawn.png", "gpt-image-2"

    def _spy_check(moments):
        check_calls.append(moments)
        return _real_check_shot_purpose_present(moments)

    patches = [
        patch("scripts.coverage_to_app.fetch_one", fake_fetch_one),
        patch("scripts.coverage_to_app.fetch_all", fake_fetch_all),
        patch("scripts.coverage_to_app.execute", AsyncMock()),
        patch("scripts.coverage_to_app.get_secret", AsyncMock(return_value="fake-key")),
        patch("scripts.coverage_to_app.ImageClient", lambda **kw: object()),
        patch("scripts.coverage_to_app._approved_envs", AsyncMock(return_value=[])),
        patch("scripts.coverage_to_app._match_scene_env", lambda text, e: (e[0] if e else None)),
        patch("scripts.coverage_to_app.generate_scene_image_for_model", fake_gen),
        patch("scripts.coverage_to_app._stable_url", AsyncMock(return_value="https://stable/x.png")),
        patch("scripts.coverage_to_app.record_ledger_entry", AsyncMock()),
        patch("scripts.coverage_to_app.check_shot_purpose_present", check_patch or _spy_check),
    ]
    for p in patches:
        p.start()
    try:
        result = asyncio.run(redraw_asset_image("vid-1", "tenant-1", "asset-1"))
    finally:
        for p in patches:
            p.stop()
    return result, draw_calls, check_calls


def test_redraw_selects_and_threads_purpose_fields_to_the_check(capsys):
    """Wiring: redraw's SELECT now fetches shot_type/purpose_kind/
    shot_purpose from its OWN asset row (previously not selected at all) and
    threads them, via a synthetic single-shot moment, into the SAME
    check_shot_purpose_present function B/A call — reused verbatim."""
    result, draw_calls, check_calls = _run_redraw(
        purpose_kind=None, shot_purpose=None, shot_type="MCU")
    assert result["status"] == "completed", result
    assert len(check_calls) == 1
    assert check_calls[0] == [{
        "moment_number": 122,
        "master": {"shot_type": "MCU", "purpose_kind": None, "shot_purpose": None},
        "angles": [],
    }]
    out = capsys.readouterr().out
    assert "shot-purpose check (D9-1): moment 122 (MCU) carries no PURPOSE: line" in out


def test_redraw_silent_when_asset_already_carries_a_stated_purpose(capsys):
    result, draw_calls, check_calls = _run_redraw(
        purpose_kind="spatial", shot_purpose="shows the corridor route", shot_type="MCU")
    assert result["status"] == "completed", result
    out = capsys.readouterr().out
    assert "shot-purpose check (D9-1)" not in out


def test_redraw_purpose_check_is_really_wired():
    """Guard-neuter: proves the redraw call site is real, not vacuous."""
    def _boom_check(moments):
        raise AssertionError("REDRAW PURPOSE CHECK BOOM")

    with pytest.raises(AssertionError, match="REDRAW PURPOSE CHECK BOOM"):
        _run_redraw(check_patch=_boom_check)


def test_redraw_prompt_text_byte_identical_regardless_of_purpose_presence():
    """PURPOSE-ABSENT/PRESENT golden proof: redraw's actual drawn prompt
    string is byte-identical whether purpose_kind/shot_purpose is NULL or
    set — the fields are selected and threaded to the presence check ONLY,
    never folded into `prompt` (rule 23, matching assembler B's own proven
    discipline, now proven here for assembler C too)."""
    _, calls_absent, _ = _run_redraw(purpose_kind=None, shot_purpose=None)
    _, calls_present, _ = _run_redraw(
        purpose_kind="spatial",
        shot_purpose="a planted marker nobody should ever see baked onto the picture")
    assert calls_absent and calls_present
    assert calls_absent[0]["prompt"] == calls_present[0]["prompt"]
    assert "planted marker" not in calls_present[0]["prompt"]


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(pytest.main([__file__, "-q"]))
