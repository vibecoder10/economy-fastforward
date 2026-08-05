"""D15-4: backend/arbiter_repair.py's ``_default_board_reroll`` — the ONLY
remaining direct caller of a storyboard/coverage draw function alongside
D15-3's route fix — used to call ``scripts.coverage_to_app.
generate_storyboard_sheet_for_scene`` directly, bypassing
``PipelineExecutor.run_storyboard_sheet`` (pipeline_executor.py), the
judged-road wrapper D15-1/D15-3 made every OTHER caller (actions.py verbs,
claude_orchestrator.py's skill dispatch, the MCP tool, routes/pipeline.py's
buttons) converge on.

This caller is special: it is the Frame Arbiter's OWN repair action (A5,
storyengine/FRAME-ARBITER-PLAN.md), fired by ``frame_arbiter_hook.
run_after_storyboard_sheet`` — which is itself invoked FROM INSIDE
``run_storyboard_sheet`` after a plain (non-beat-scoped) draw. Routing the
repair's own reroll back through the SAME wrapper is only safe if that
wrapper's hook-firing guard structurally cannot re-invoke the hook for a
beat-scoped call — otherwise a MODEL_DEFECT repair could trigger a second
judgment, which could trigger a second repair, looping.

D15-4 chunk brief's own instruction: "route it through if the guard
provably prevents self-looping (add a test proving a beat-scoped repair
call through the executor never re-fires the hook)". That guard, read
directly off pipeline_executor.py's ``run_storyboard_sheet`` (the ``if
(scene is not None and beat is None and not plan_only and ...)`` condition
immediately after the ``generate_storyboard_sheet_for_scene`` call), only
ever fires the hook when ``beat is None``. ``_default_board_reroll``'s own
signature requires ``beat: int`` (never Optional, never defaulted to
None — see its docstring) and ``repair_board_finding`` refuses to call it
at all without a resolvable ``sheet_index`` to pass as ``beat``. So a call
through this path can never present ``beat=None`` to the wrapper, and the
hook can never fire from it.

This file proves that directly (not just by reading the guard), the same
call-tracking approach test_d15_3_wrapper_param_forwarding.py's own
beat-scoped test uses: the hook call is wrapped in a try/except inside
run_storyboard_sheet (advisory contract — must never break the storyboard
stage itself), so a boom-on-call assertion would get silently swallowed by
that except clause. An AsyncMock call-count assertion is not fooled by
that.

Covers, with NO live DB, NO network, NO paid calls (every DB/network/paid
boundary monkeypatched or mocked, same convention as
test_d15_3_wrapper_param_forwarding.py and test_d5_a5_repair.py):

  (1) Argument fidelity — ``_default_board_reroll`` reaches
      ``generate_storyboard_sheet_for_scene`` (through the wrapper) with
      EXACTLY the same (video_id, tenant_id, scene, beat, plan_only=False,
      progress) shape it passed when calling that function directly,
      before this chunk.
  (2) LOOP-GUARD PROOF (non-negotiable per the chunk brief) — with the D5/A6
      arbiter flag ON and scoped to the exact (video, scene) under test (the
      condition under which the hook WOULD fire for a plain call — see
      test_d15_3_wrapper_param_forwarding.py's own
      test_arbiter_hook_still_fires_for_the_plain_full_scene_call_when_flag_
      is_scoped_in), a beat-scoped call through ``_default_board_reroll``
      does NOT invoke ``frame_arbiter_hook.run_after_storyboard_sheet``.
  (3) Byte-identical result handling — ``repair_board_finding``'s own
      "reroll succeeded" / "reroll failed" branching (it reads only
      ``reroll_result.get("status")``) behaves identically whether the
      reroll came from the OLD direct call or the NEW wrapper call, proven
      end-to-end through ``repair_board_finding`` using the REAL default
      reroll (no ``reroll_fn`` injected) — the one path
      tests/functional/test_d5_a5_repair.py never exercises (every test
      there injects its own ``reroll_fn``).

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_d15_4_arbiter_repair_routing.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import arbiter_repair as ar  # noqa: E402
import pipeline_executor as pe_mod  # noqa: E402
import frame_arbiter_hook as hook  # noqa: E402

TENANT = "tenant-d15-4"
VIDEO = "video-d15-4"
SCENE = 4
BEAT = 2


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _video_row(**extra) -> dict:
    row = {
        "id": VIDEO, "tenant_id": TENANT, "video_title": "D15-4 Video",
        "aspect": "16:9", "image_style_override": None, "visual_style": None,
        "image_model_override": None, "render_style": None,
        "video_model": "grok-imagine", "dialogue_audio": "voice_over",
        "render_mode": None, "skip_voice": True, "status": "ready_for_images",
    }
    row.update(extra)
    return row


def _finding(classification="MODEL_DEFECT", failure_class="set_bleed", rule_id=None,
             panel=1, sheet_index=BEAT, description="wrong location drawn"):
    return {
        "classification": classification,
        "failure_class": failure_class,
        "rule_id": rule_id,
        "panel": panel,
        "sheet_index": sheet_index,
        "description": description,
        "decisive_prompt_fragment": "Bubble-Pod interior",
    }


def _set_arbiter_scope(monkeypatch, *, enabled=True, video=VIDEO, scene=SCENE):
    if enabled:
        monkeypatch.setenv("FRAME_ARBITER_A6_ENABLED", "true")
    else:
        monkeypatch.delenv("FRAME_ARBITER_A6_ENABLED", raising=False)
    monkeypatch.setenv("FRAME_ARBITER_A6_VIDEO_ID", video)
    monkeypatch.setenv("FRAME_ARBITER_A6_SCENE", str(scene))
    monkeypatch.delenv("FRAME_ARBITER_A6_REDRAW_ENABLED", raising=False)


# =============================================================================
# (1) Argument fidelity — same shape reaches the underlying function through
# the wrapper as reached it via the old direct call.
# =============================================================================

def test_default_board_reroll_forwards_args_through_the_executor_unchanged(monkeypatch):
    monkeypatch.delenv("FRAME_ARBITER_A6_ENABLED", raising=False)

    async def _fake_fetch_one(query, *args):
        return _video_row()

    monkeypatch.setattr(pe_mod, "fetch_one", _fake_fetch_one)

    underlying = AsyncMock(return_value={"status": "completed", "message": "board 2 is up"})
    seen_progress: list = []
    with patch("scripts.coverage_to_app.generate_storyboard_sheet_for_scene", underlying):
        result = _run(ar._default_board_reroll(
            VIDEO, TENANT, scene=SCENE, beat=BEAT, progress=seen_progress.append,
        ))

    underlying.assert_awaited_once_with(
        VIDEO, TENANT, scene=SCENE, beat=BEAT, plan_only=False, progress=seen_progress.append)
    assert result == {"status": "completed", "message": "board 2 is up"}


def test_default_board_reroll_never_passes_beat_none_to_the_wrapper(monkeypatch):
    """Sanity check on the loop-guard's own precondition: beat is ALWAYS a
    real int here, never None — the exact property the wrapper's hook guard
    (``beat is None``) depends on to stay closed for this caller."""
    monkeypatch.delenv("FRAME_ARBITER_A6_ENABLED", raising=False)

    async def _fake_fetch_one(query, *args):
        return _video_row()

    monkeypatch.setattr(pe_mod, "fetch_one", _fake_fetch_one)

    underlying = AsyncMock(return_value={"status": "completed", "message": "ok"})
    with patch("scripts.coverage_to_app.generate_storyboard_sheet_for_scene", underlying):
        _run(ar._default_board_reroll(VIDEO, TENANT, scene=SCENE, beat=BEAT))

    _args, kwargs = underlying.await_args
    assert kwargs["beat"] is not None
    assert kwargs["beat"] == BEAT


# =============================================================================
# (2) LOOP-GUARD PROOF — flag scoped IN for this exact (video, scene); the
# beat-scoped reroll must not re-fire the hook that would otherwise judge it.
# =============================================================================

def test_default_board_reroll_never_refires_the_hook_even_when_flag_is_scoped_in(monkeypatch):
    _set_arbiter_scope(monkeypatch, enabled=True, video=VIDEO, scene=SCENE)

    async def _fake_fetch_one(query, *args):
        return _video_row()

    monkeypatch.setattr(pe_mod, "fetch_one", _fake_fetch_one)

    hook_call = AsyncMock(return_value={"scene": SCENE, "sheets": []})
    monkeypatch.setattr(hook, "run_after_storyboard_sheet", hook_call)

    underlying = AsyncMock(return_value={"status": "completed", "message": "board 2 is up"})
    with patch("scripts.coverage_to_app.generate_storyboard_sheet_for_scene", underlying):
        result = _run(ar._default_board_reroll(VIDEO, TENANT, scene=SCENE, beat=BEAT))

    hook_call.assert_not_awaited()
    assert "frame_arbiter" not in result


def test_control_plain_call_through_the_same_wrapper_WOULD_have_fired_the_hook(monkeypatch):
    """Control for the test above: proves the flag scope + video/scene setup
    used here really is the condition under which the hook fires (so the
    beat-scoped test isn't passing merely because the hook is unreachable
    for some unrelated reason, e.g. a scope mismatch). Calls
    PipelineExecutor.run_storyboard_sheet directly with beat=None (the shape
    NO repair call ever produces) under the identical env scope and confirms
    the hook DOES fire here."""
    _set_arbiter_scope(monkeypatch, enabled=True, video=VIDEO, scene=SCENE)

    async def _fake_fetch_one(query, *args):
        return _video_row()

    monkeypatch.setattr(pe_mod, "fetch_one", _fake_fetch_one)

    hook_call = AsyncMock(return_value={"scene": SCENE, "sheets": []})
    monkeypatch.setattr(hook, "run_after_storyboard_sheet", hook_call)

    underlying = AsyncMock(return_value={"status": "completed", "message": "sheet ready"})
    from pipeline_executor import PipelineExecutor
    with patch("scripts.coverage_to_app.generate_storyboard_sheet_for_scene", underlying):
        result = _run(PipelineExecutor(TENANT).run_storyboard_sheet(VIDEO, scene=SCENE))

    hook_call.assert_awaited_once_with(TENANT, VIDEO, SCENE)
    assert result["frame_arbiter"] == {"scene": SCENE, "sheets": []}


# =============================================================================
# (3) Byte-identical result handling — repair_board_finding's ladder, driven
# through the REAL default reroll_fn (no injection), reads only `.get(
# "status")` off the result and behaves the same for success and failure.
# =============================================================================

async def _no_breach(*_a, **_k):
    return None


async def _never_frozen(*_a, **_k):
    return False


def _make_sink():
    calls: list = []

    async def sink(*args, **kwargs):
        calls.append(kwargs)
        return {"crossed_threshold": False, "violation_count": 1, "frozen": False}

    sink.calls = calls
    return sink


def test_repair_board_finding_end_to_end_success_through_the_real_default_reroll(monkeypatch):
    """No reroll_fn injected — this exercises ar._default_board_reroll for
    real, through the executor, the one path test_d5_a5_repair.py never
    reaches (every test there injects its own reroll_fn)."""
    monkeypatch.delenv("FRAME_ARBITER_A6_ENABLED", raising=False)

    async def _fake_fetch_one(query, *args):
        return _video_row()

    monkeypatch.setattr(pe_mod, "fetch_one", _fake_fetch_one)

    underlying = AsyncMock(return_value={"status": "completed", "message": "board 2 is up"})
    ledger = _make_sink()
    with patch("scripts.coverage_to_app.generate_storyboard_sheet_for_scene", underlying):
        result = _run(ar.repair_board_finding(
            TENANT, VIDEO, SCENE, _finding(rule_id="QL-9"),
            is_frozen_fn=_never_frozen, budget_check=_no_breach, ledger_write=ledger,
        ))

    assert result["acted"] is True
    assert result["action"] == "repaired"
    assert result["reroll_result"] == {"status": "completed", "message": "board 2 is up"}
    assert len(ledger.calls) == 1


def test_repair_board_finding_end_to_end_failure_through_the_real_default_reroll(monkeypatch):
    """Same real (non-injected) reroll path, but the underlying draw call
    reports failure — repair_board_finding must take its pre-existing
    'reroll_failed' branch (no ledger write, acted: False) exactly as it did
    when the old direct call failed."""
    monkeypatch.delenv("FRAME_ARBITER_A6_ENABLED", raising=False)

    async def _fake_fetch_one(query, *args):
        return _video_row()

    monkeypatch.setattr(pe_mod, "fetch_one", _fake_fetch_one)

    underlying = AsyncMock(return_value={"status": "failed", "error": "no current plan"})
    ledger = _make_sink()
    with patch("scripts.coverage_to_app.generate_storyboard_sheet_for_scene", underlying):
        result = _run(ar.repair_board_finding(
            TENANT, VIDEO, SCENE, _finding(rule_id="QL-9"),
            is_frozen_fn=_never_frozen, budget_check=_no_breach, ledger_write=ledger,
        ))

    assert result["acted"] is False
    assert result["action"] == "reroll_failed"
    assert result["reroll_result"] == {"status": "failed", "error": "no current plan"}
    assert ledger.calls == []


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
