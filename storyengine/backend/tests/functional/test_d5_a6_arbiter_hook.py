"""Tests for D5 chunk A6 (storyengine/FRAME-ARBITER-PLAN.md): the flag-gated
single-scene wiring, backend/frame_arbiter_hook.py + its call site in
pipeline_executor.PipelineExecutor.run_storyboard_sheet + the env-configurable
budget cap in frame_arbiter_budget.py.

$0 suite: every DB/network boundary is dependency-injected (fetch_sheets,
judge_fn, repair_fn, rejudge_fn are keyword params on
run_after_storyboard_sheet, same convention judge_frame/judge_scene_batch/
judge_board_sheet/repair_board_finding already use) or monkeypatched at the
module level (database.fetch_one/fetch_all via arbiter_fingerprints.py's/
frame_arbiter_budget.py's own boundary, arbiter_repair._default_board_reroll).
NO live DB, NO network, NO paid calls of any kind.

Proves the four things this chunk's brief requires, each in its own section:
  (a) flag off = zero arbiter calls, byte-identical behavior
  (b) flag on for the scoped video/scene = judge invoked, ledger row written
  (c) repeat fingerprint = freeze, no second spend
  (d) redraw sub-flag off = repair ladder never reaches the redraw leg

Non-vacuous / stash-proof: test_scene_is_in_scope_false_when_flag_disabled
and test_redraw_subflag_off_never_invokes_the_real_reroll were each re-run
against a neutered copy of the guard they check (scene_is_in_scope's
`if scene is None or not arbiter_enabled(): return False` short-circuit
commented out so it fell through to the video/scene string compare
unconditionally; frame_arbiter_hook's `reroll = None if redraw_enabled()
else _redraw_refused_reroll` line hardcoded to `reroll = None`) — both
failed as expected (the neutered scope test found itself in-scope with the
flag off and proceeded to call the DB-touching tracker that should never
fire; the neutered redraw test saw arbiter_repair._default_board_reroll's
tracker actually invoked), confirming the checks are real, then reverted.

Run: cd storyengine/backend && ./venv/bin/python -m pytest \
    tests/functional/test_d5_a6_arbiter_hook.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import arbiter_fingerprints as af  # noqa: E402
import arbiter_repair as ar  # noqa: E402
import frame_arbiter as fa  # noqa: E402
import frame_arbiter_budget as fab  # noqa: E402
import frame_arbiter_hook as hook  # noqa: E402
import pipeline_executor as pe_mod  # noqa: E402
from pipeline_executor import PipelineExecutor  # noqa: E402

TENANT = "tenant-a6"
VIDEO = "video-a6"
SCENE = 4


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _set_scope(monkeypatch, *, enabled=True, video=VIDEO, scene=SCENE, redraw=None):
    if enabled:
        monkeypatch.setenv("FRAME_ARBITER_A6_ENABLED", "true")
    else:
        monkeypatch.delenv("FRAME_ARBITER_A6_ENABLED", raising=False)
    if video is not None:
        monkeypatch.setenv("FRAME_ARBITER_A6_VIDEO_ID", video)
    else:
        monkeypatch.delenv("FRAME_ARBITER_A6_VIDEO_ID", raising=False)
    if scene is not None:
        monkeypatch.setenv("FRAME_ARBITER_A6_SCENE", str(scene))
    else:
        monkeypatch.delenv("FRAME_ARBITER_A6_SCENE", raising=False)
    if redraw is True:
        monkeypatch.setenv("FRAME_ARBITER_A6_REDRAW_ENABLED", "true")
    elif redraw is False:
        monkeypatch.setenv("FRAME_ARBITER_A6_REDRAW_ENABLED", "false")
    else:
        monkeypatch.delenv("FRAME_ARBITER_A6_REDRAW_ENABLED", raising=False)


def _make_tracker(result=None):
    calls: list = []

    async def tracker(*args, **kwargs):
        calls.append((args, kwargs))
        return result if result is not None else {"status": "completed", "message": "ok"}

    tracker.calls = calls
    return tracker


def _make_sink():
    calls: list = []

    async def sink(*args, **kwargs):
        merged = dict(kwargs)
        if args:
            merged["_positional"] = args
        calls.append(merged)
        return {"crossed_threshold": False, "violation_count": 1, "frozen": False}

    sink.calls = calls
    return sink


# One-panel board spec, minimal but real enough for
# frame_arbiter._parse_sheet_panels to parse (no "--- BEAT n ---" wrapper
# needed — that split is a no-op when the marker is absent, see the
# function's own re.split behavior). Self-describes its OWN sheet_index so
# multiple synthetic sheets in one test never collide on "sheet 1 of N".
def _one_panel_spec(sheet_index: int = 1) -> str:
    return (
        f"This is storyboard sheet {sheet_index} of 5 for an animated scene: a grid of 1 panel.\n"
        "FIXED SET — identical in every panel: a plain interior room.\n\n"
        "[1] M1 WS — (SETUP A) Wide shot of the room, a character stands center frame.\n"
    )


_ONE_PANEL_SPEC = _one_panel_spec(1)


def _sheet(sheet_index=1, spec_text=None):
    return {
        "image_url": f"https://x/sheet-{sheet_index}.png",
        "sheet_index": sheet_index,
        "spec_text": spec_text if spec_text is not None else _one_panel_spec(sheet_index),
    }


async def _fake_download(_url):
    return ("image/jpeg", "ZmFrZQ==")  # base64("fake")


def _panel_reply(classification, failure_class, description="wrong location drawn", rule_id=None):
    return (
        "===PANEL 1===\n"
        "NEW_VS_PREVIOUS: FIRST_PANEL\n"
        f"CLASSIFICATION: {classification}\n"
        f"FAILURE_CLASS: {failure_class or 'NONE'}\n"
        f"RULE_ID: {rule_id or 'NONE'}\n"
        "RUBRIC_LEVEL: hard_gate\n"
        "DECISIVE_FRAGMENT: NONE\n"
        f"DESCRIPTION: {description}\n"
    )


def _scripted_vision(script: list):
    """Returns a call_vision-shaped fake that replies with script[call_index]
    = (classification, failure_class) on each successive call. Raises
    IndexError (a loud test bug, not a silent pass) if called more times
    than scripted."""
    calls: list = []

    async def _vision(tenant_id, content, **kwargs):
        idx = len(calls)
        calls.append((tenant_id, kwargs))
        cls, fclass = script[idx]
        return {
            "content": [{"type": "text", "text": _panel_reply(cls, fclass)}],
            "usage": {"input_tokens": 500, "output_tokens": 80},
        }

    _vision.calls = calls
    return _vision


async def _no_breach(*_a, **_k):
    return None


# =============================================================================
# scene_is_in_scope — the whole "ONE scene of ONE video" law lives here.
# =============================================================================

def test_scene_is_in_scope_false_when_flag_disabled(monkeypatch):
    _set_scope(monkeypatch, enabled=False)
    assert hook.scene_is_in_scope(VIDEO, SCENE) is False


def test_scene_is_in_scope_false_with_no_target_configured(monkeypatch):
    _set_scope(monkeypatch, enabled=True, video=None, scene=None)
    assert hook.scene_is_in_scope(VIDEO, SCENE) is False


def test_scene_is_in_scope_false_for_wrong_video(monkeypatch):
    _set_scope(monkeypatch, enabled=True, video=VIDEO, scene=SCENE)
    assert hook.scene_is_in_scope("some-other-video", SCENE) is False


def test_scene_is_in_scope_false_for_wrong_scene(monkeypatch):
    _set_scope(monkeypatch, enabled=True, video=VIDEO, scene=SCENE)
    assert hook.scene_is_in_scope(VIDEO, SCENE + 1) is False


def test_scene_is_in_scope_false_when_scene_is_none():
    assert hook.scene_is_in_scope(VIDEO, None) is False


def test_scene_is_in_scope_true_for_the_exact_configured_pair(monkeypatch):
    _set_scope(monkeypatch, enabled=True, video=VIDEO, scene=SCENE)
    assert hook.scene_is_in_scope(VIDEO, SCENE) is True


# =============================================================================
# (a) flag off = zero arbiter calls, byte-identical behavior.
# =============================================================================

def test_hook_returns_none_and_touches_nothing_when_out_of_scope(monkeypatch):
    _set_scope(monkeypatch, enabled=False)
    fetch_probe = _make_tracker()
    judge_probe = _make_tracker()
    result = _run(hook.run_after_storyboard_sheet(
        TENANT, VIDEO, SCENE, fetch_sheets=fetch_probe, judge_fn=judge_probe,
    ))
    assert result is None
    assert fetch_probe.calls == []
    assert judge_probe.calls == []


def test_run_storyboard_sheet_flag_off_result_unchanged_and_hook_makes_no_db_call(monkeypatch):
    """The real call site (pipeline_executor.PipelineExecutor.
    run_storyboard_sheet): with the flag off, the returned dict is
    byte-identical to what generate_storyboard_sheet_for_scene itself
    returned — no "frame_arbiter" key, nothing added — and the hook's own
    DB read (fetch_all) never fires."""
    _set_scope(monkeypatch, enabled=False)

    async def _fake_fetch_one(query, *args):
        return {"render_mode": None}

    monkeypatch.setattr(pe_mod, "fetch_one", _fake_fetch_one)

    async def _boom_fetch_all(*_a, **_k):
        raise AssertionError("frame_arbiter_hook must not touch the DB when the flag is off")

    monkeypatch.setattr(hook, "fetch_all", _boom_fetch_all)

    executor = PipelineExecutor(TENANT)
    sheet_result = {"status": "completed", "message": "Storyboard ready for 1 scene(s) — 1 planned shot(s)."}
    with patch(
        "scripts.coverage_to_app.generate_storyboard_sheet_for_scene",
        AsyncMock(return_value=dict(sheet_result)),
    ):
        result = _run(executor.run_storyboard_sheet(VIDEO, scene=SCENE))

    assert result == sheet_result
    assert "frame_arbiter" not in result


# =============================================================================
# (b) flag on for the scoped video/scene = judge invoked, ledger row written.
# =============================================================================

def test_hook_judges_every_drawn_sheet_and_writes_a_ledger_row_when_in_scope(monkeypatch):
    _set_scope(monkeypatch, enabled=True, video=VIDEO, scene=SCENE)

    sheets = [_sheet(sheet_index=1), _sheet(sheet_index=2)]

    async def fetch_sheets(tenant_id, video_id, scene):
        assert (tenant_id, video_id, scene) == (TENANT, VIDEO, SCENE)
        return sheets

    ledger = _make_sink()
    vision = _scripted_vision([("OK", None), ("OK", None)])  # one call per sheet, both clean

    async def judge_fn(tenant_id, video_id, scene, sheet):
        return await fa.judge_board_sheet(
            tenant_id, video_id, scene, sheet,
            download_image=_fake_download, call_vision=vision,
            budget_check=_no_breach, ledger_write=ledger, record_finding_fn=af.record_finding,
        )

    repair_probe = _make_tracker()  # must never fire — no MODEL_DEFECT in this scenario

    result = _run(hook.run_after_storyboard_sheet(
        TENANT, VIDEO, SCENE, fetch_sheets=fetch_sheets, judge_fn=judge_fn, repair_fn=repair_probe,
    ))

    assert result["scene"] == SCENE
    assert len(result["sheets"]) == 2
    assert len(vision.calls) == 2  # one judge call per drawn sheet
    assert len(ledger.calls) == 2  # a real ledger row per judge call, verdict or not
    assert {c["video_id"] for c in ledger.calls} == {VIDEO}
    assert {c["scene"] for c in ledger.calls} == {SCENE}
    assert ledger.calls[0]["model"] == fa.VISION_MODEL
    assert repair_probe.calls == []  # OK verdicts never trigger a repair attempt


# =============================================================================
# (c) repeat fingerprint = freeze, no second spend.
# =============================================================================

@pytest.fixture
def fingerprint_rows(monkeypatch):
    """Same fake-fetch_one-enforces-the-real-ON-CONFLICT-semantics convention
    tests/functional/test_d5_a5_repair.py's own fixture uses — reused here
    (not reimplemented from scratch) so this integration test exercises the
    REAL arbiter_fingerprints.record_finding/is_frozen, not a stand-in."""
    rows: list = []

    def _find(tenant_id, fp_key, stage, failure_class):
        return next(
            (r for r in rows if r["tenant_id"] == tenant_id and r["fingerprint_key"] == fp_key
             and r["stage"] == stage and r["failure_class"] == failure_class),
            None,
        )

    async def fake_fetch_one(query: str, *args):
        if "INSERT INTO arbiter_fingerprints" in query:
            tenant_id, rule_id, stage, failure_class, classification = args
            fp_key = (rule_id or failure_class or "").strip() or failure_class
            existing = _find(tenant_id, fp_key, stage, failure_class)
            if existing is not None:
                existing["violation_count"] += 1
                existing["classification"] = classification
                existing["frozen"] = existing["violation_count"] >= af.FREEZE_THRESHOLD
                row = dict(existing)
                row["crossed_threshold"] = existing["violation_count"] == af.FREEZE_THRESHOLD
                return row
            new_row = {
                "tenant_id": tenant_id, "rule_id": rule_id, "stage": stage,
                "failure_class": failure_class, "fingerprint_key": fp_key,
                "classification": classification, "violation_count": 1, "frozen": False,
                "root_cause_finding_id": None,
            }
            rows.append(new_row)
            row = dict(new_row)
            row["crossed_threshold"] = False
            return row
        if "SELECT frozen FROM arbiter_fingerprints" in query:
            tenant_id, fp_key, stage, failure_class = args
            existing = _find(tenant_id, fp_key, stage, failure_class)
            return {"frozen": existing["frozen"]} if existing else None
        raise AssertionError(f"unexpected query: {query!r}")

    monkeypatch.setattr(af, "fetch_one", fake_fetch_one)
    return rows


def test_repeat_fingerprint_freezes_and_blocks_the_second_spend(monkeypatch, fingerprint_rows):
    _set_scope(monkeypatch, enabled=True, video=VIDEO, scene=SCENE)

    sheet = _sheet()

    async def fetch_sheets(tenant_id, video_id, scene):
        return [sheet]

    # 3 vision calls total across the two hook invocations below: round 1's
    # initial judge (strike 1), round 1's post-repair rejudge (strike 2 —
    # THIS is what crosses the freeze, per arbiter_repair.py's own RULING),
    # round 2's judge (a later landing event that finds the SAME defect
    # again, this time already frozen).
    vision = _scripted_vision([
        ("MODEL_DEFECT", "set_bleed"),
        ("MODEL_DEFECT", "set_bleed"),
        ("MODEL_DEFECT", "set_bleed"),
    ])

    async def judge_fn(tenant_id, video_id, scene, sheet_arg):
        return await fa.judge_board_sheet(
            tenant_id, video_id, scene, sheet_arg,
            download_image=_fake_download, call_vision=vision,
            budget_check=_no_breach, ledger_write=_make_sink(), record_finding_fn=af.record_finding,
        )

    reroll_tracker = _make_tracker({"status": "completed"})

    async def repair_fn(tenant_id, video_id, scene, finding, *, sheet_index, reroll_fn):
        # Ignores the hook's own reroll_fn choice on purpose — this test's
        # job is the freeze/spend mechanics, not the redraw sub-flag
        # routing (see test_redraw_subflag_off_never_invokes_the_real_reroll
        # for that proof) — always resolves to a real, trackable "success".
        return await ar.repair_board_finding(
            tenant_id, video_id, scene, finding, sheet_index=sheet_index,
            is_frozen_fn=af.is_frozen, budget_check=_no_breach,
            reroll_fn=reroll_tracker, ledger_write=_make_sink(),
        )

    # --- Round 1: first landing. Judge finds MODEL_DEFECT, repair rolls,
    # rejudge still finds it — freeze crosses on THIS second judgment. ---
    result1 = _run(hook.run_after_storyboard_sheet(
        TENANT, VIDEO, SCENE, fetch_sheets=fetch_sheets, judge_fn=judge_fn,
        repair_fn=repair_fn, rejudge_fn=ar.rejudge_board_after_repair,
    ))
    repair1 = result1["sheets"][0]["repair"]
    assert repair1["acted"] is True
    assert len(reroll_tracker.calls) == 1
    assert "rejudge" in repair1
    assert repair1["rejudge"]["findings"][0]["classification"] == "MODEL_DEFECT"
    assert _run(af.is_frozen(TENANT, rule_id=None, stage=fab.FRAME_QA_STAGE, failure_class="set_bleed")) is True

    # --- Round 2: a later landing for the same scene finds the SAME
    # fingerprint again. Now frozen — the repair ladder refuses at the
    # freeze check, before budget or the reroll. No second spend. ---
    result2 = _run(hook.run_after_storyboard_sheet(
        TENANT, VIDEO, SCENE, fetch_sheets=fetch_sheets, judge_fn=judge_fn,
        repair_fn=repair_fn, rejudge_fn=ar.rejudge_board_after_repair,
    ))
    repair2 = result2["sheets"][0]["repair"]
    assert repair2["acted"] is False
    assert repair2["action"] == "frozen"
    assert "rejudge" not in repair2  # a refused repair is never re-judged
    assert len(reroll_tracker.calls) == 1  # UNCHANGED — no second spend
    assert len(vision.calls) == 3  # exactly the 3 scripted judge/rejudge calls, nothing extra


# =============================================================================
# (d) redraw sub-flag off = repair ladder never reaches the redraw leg.
# =============================================================================

async def _not_frozen_fetch_one(query, *args):
    if "SELECT frozen FROM arbiter_fingerprints" in query:
        return {"frozen": False}
    raise AssertionError(f"unexpected arbiter_fingerprints query in this test: {query!r}")


async def _zero_spend_fetch_one(query, *args):
    return {"spent": 0.0}


def test_redraw_subflag_off_never_invokes_the_real_reroll(monkeypatch):
    """Uses the REAL default repair_fn (arbiter_repair.repair_board_finding,
    the hook's own default) end-to-end — only the true DB boundaries
    (arbiter_fingerprints.fetch_one, frame_arbiter_budget.fetch_one) and the
    real paid reroll (arbiter_repair._default_board_reroll) are patched.
    Proves the actual production default-argument wiring, not a stand-in."""
    monkeypatch.setattr(af, "fetch_one", _not_frozen_fetch_one)
    monkeypatch.setattr(fab, "fetch_one", _zero_spend_fetch_one)
    real_reroll_tracker = _make_tracker({"status": "completed"})
    monkeypatch.setattr(ar, "_default_board_reroll", real_reroll_tracker)
    _set_scope(monkeypatch, enabled=True, video=VIDEO, scene=SCENE, redraw=False)

    sheet = _sheet()

    async def fetch_sheets(tenant_id, video_id, scene):
        return [sheet]

    async def judge_fn(tenant_id, video_id, scene, sheet_arg):
        return {
            "skipped": False,
            "sheet_index": 1,
            "findings": [{
                "skipped": False, "panel": 1, "classification": "MODEL_DEFECT",
                "failure_class": "set_bleed", "rule_id": None, "description": "x",
            }],
        }

    result = _run(hook.run_after_storyboard_sheet(
        TENANT, VIDEO, SCENE, fetch_sheets=fetch_sheets, judge_fn=judge_fn,
    ))

    repair = result["sheets"][0]["repair"]
    assert repair["acted"] is False
    assert repair["action"] == "reroll_failed"
    assert "rejudge" not in repair  # a refused repair is never re-judged
    assert real_reroll_tracker.calls == []  # the real, paid reroll is never invoked


def test_redraw_subflag_on_does_reach_the_real_reroll(monkeypatch):
    """Sibling proof: with the sub-flag ON, the SAME wiring resolves
    reroll_fn to None, which repair_board_finding's own
    `reroll_fn or _default_board_reroll` then dispatches to the real
    function — confirming the off-case above is a real gate, not a
    tautology that never calls anything either way."""
    monkeypatch.setattr(af, "fetch_one", _not_frozen_fetch_one)
    monkeypatch.setattr(fab, "fetch_one", _zero_spend_fetch_one)
    real_reroll_tracker = _make_tracker({"status": "completed"})
    monkeypatch.setattr(ar, "_default_board_reroll", real_reroll_tracker)
    _set_scope(monkeypatch, enabled=True, video=VIDEO, scene=SCENE, redraw=True)

    sheet = _sheet()

    async def fetch_sheets(tenant_id, video_id, scene):
        return [sheet]

    async def judge_fn(tenant_id, video_id, scene, sheet_arg):
        return {
            "skipped": False,
            "sheet_index": 1,
            "findings": [{
                "skipped": False, "panel": 1, "classification": "MODEL_DEFECT",
                "failure_class": "set_bleed", "rule_id": None, "description": "x",
            }],
        }

    async def rejudge_fn(tenant_id, video_id, scene, sheet_arg, **kwargs):
        return {"skipped": False, "sheet_index": 1, "findings": [
            {"skipped": False, "panel": 1, "classification": "OK", "failure_class": None,
             "rule_id": None, "description": "fixed"},
        ]}

    result = _run(hook.run_after_storyboard_sheet(
        TENANT, VIDEO, SCENE, fetch_sheets=fetch_sheets, judge_fn=judge_fn, rejudge_fn=rejudge_fn,
    ))

    repair = result["sheets"][0]["repair"]
    assert repair["acted"] is True
    assert len(real_reroll_tracker.calls) == 1


# =============================================================================
# The wiring call site itself: pipeline_executor.PipelineExecutor.
# run_storyboard_sheet merges the hook's result in when it fires, and a
# hook exception never breaks the storyboard stage.
# =============================================================================

def test_run_storyboard_sheet_flag_on_merges_hook_result_into_response(monkeypatch):
    async def _fake_fetch_one(query, *args):
        return {"render_mode": None}

    monkeypatch.setattr(pe_mod, "fetch_one", _fake_fetch_one)

    async def fake_hook(tenant_id, video_id, scene):
        assert (tenant_id, video_id, scene) == (TENANT, VIDEO, SCENE)
        return {"scene": scene, "sheets": [{"beat": 1, "judged": {"skipped": True}, "repair": None}]}

    monkeypatch.setattr(hook, "run_after_storyboard_sheet", fake_hook)

    executor = PipelineExecutor(TENANT)
    sheet_result = {"status": "completed", "message": "ok"}
    with patch(
        "scripts.coverage_to_app.generate_storyboard_sheet_for_scene",
        AsyncMock(return_value=dict(sheet_result)),
    ):
        result = _run(executor.run_storyboard_sheet(VIDEO, scene=SCENE))

    assert result["status"] == "completed"
    assert result["frame_arbiter"]["scene"] == SCENE


def test_run_storyboard_sheet_hook_exception_does_not_fail_the_stage(monkeypatch):
    async def _fake_fetch_one(query, *args):
        return {"render_mode": None}

    monkeypatch.setattr(pe_mod, "fetch_one", _fake_fetch_one)

    async def raising_hook(tenant_id, video_id, scene):
        raise RuntimeError("boom — simulated arbiter failure")

    monkeypatch.setattr(hook, "run_after_storyboard_sheet", raising_hook)

    executor = PipelineExecutor(TENANT)
    sheet_result = {"status": "completed", "message": "ok"}
    with patch(
        "scripts.coverage_to_app.generate_storyboard_sheet_for_scene",
        AsyncMock(return_value=dict(sheet_result)),
    ):
        result = _run(executor.run_storyboard_sheet(VIDEO, scene=SCENE))

    assert result["status"] == "completed"  # the storyboard stage itself still succeeds
    assert "frame_arbiter" not in result


def test_run_storyboard_sheet_never_arbitrates_a_failed_draw(monkeypatch):
    """No fresh pixels landed — nothing to judge. The hook must not even be
    imported/called on a failed sheet draw."""
    async def _fake_fetch_one(query, *args):
        return {"render_mode": None}

    monkeypatch.setattr(pe_mod, "fetch_one", _fake_fetch_one)

    async def _boom_hook(*_a, **_k):
        raise AssertionError("must not arbitrate a failed storyboard draw")

    monkeypatch.setattr(hook, "run_after_storyboard_sheet", _boom_hook)

    executor = PipelineExecutor(TENANT)
    failed_result = {"status": "failed", "error": "no scenes with text"}
    with patch(
        "scripts.coverage_to_app.generate_storyboard_sheet_for_scene",
        AsyncMock(return_value=dict(failed_result)),
    ):
        result = _run(executor.run_storyboard_sheet(VIDEO, scene=SCENE))

    assert result == failed_result


def test_run_storyboard_sheet_never_arbitrates_the_bulk_scene_none_path(monkeypatch):
    """scene=None is a bulk/multi-scene draw, never in A6's scope by
    construction (scene_is_in_scope requires a real scene number) — the
    hook must not even be called."""
    async def _fake_fetch_one(query, *args):
        return {"render_mode": None}

    monkeypatch.setattr(pe_mod, "fetch_one", _fake_fetch_one)

    async def _boom_hook(*_a, **_k):
        raise AssertionError("must not arbitrate a bulk (scene=None) draw")

    monkeypatch.setattr(hook, "run_after_storyboard_sheet", _boom_hook)

    executor = PipelineExecutor(TENANT)
    sheet_result = {"status": "completed", "message": "ok"}
    with patch(
        "scripts.coverage_to_app.generate_storyboard_sheet_for_scene",
        AsyncMock(return_value=dict(sheet_result)),
    ):
        result = _run(executor.run_storyboard_sheet(VIDEO, scene=None))

    assert result == sheet_result


# =============================================================================
# Budget cap is config, not a constant buried in code (Ryan's ruling).
# =============================================================================

def test_scene_cap_reads_the_module_constant_with_no_env_override(monkeypatch):
    monkeypatch.delenv("FRAME_QA_SCENE_CAP", raising=False)
    assert fab._scene_cap(TENANT) == fab.FRAME_QA_SCENE_CAP


def test_video_cap_reads_the_module_constant_with_no_env_override(monkeypatch):
    monkeypatch.delenv("FRAME_QA_VIDEO_CAP", raising=False)
    assert fab._video_cap(TENANT) == fab.FRAME_QA_VIDEO_CAP


def test_scene_cap_env_override_takes_effect(monkeypatch):
    monkeypatch.setenv("FRAME_QA_SCENE_CAP", "0.10")
    assert fab._scene_cap(TENANT) == pytest.approx(0.10)


def test_video_cap_env_override_takes_effect(monkeypatch):
    monkeypatch.setenv("FRAME_QA_VIDEO_CAP", "0.15")
    assert fab._video_cap(TENANT) == pytest.approx(0.15)


def test_env_override_flows_through_arbiter_budget_check(monkeypatch):
    """Not just that _scene_cap/_video_cap read the env — the LIVE guard
    that judge_board_sheet/repair_board_finding actually call before every
    paid action reflects the override too."""
    monkeypatch.setenv("FRAME_QA_VIDEO_CAP", "0.05")

    async def fake_fetch_one(query, *args):
        return {"spent": 0.04}

    monkeypatch.setattr(fab, "fetch_one", fake_fetch_one)
    breach = _run(fab.arbiter_budget_check(TENANT, VIDEO, None, 0.02))
    assert breach is not None
    assert breach["cap"] == pytest.approx(0.05)


def test_malformed_env_override_falls_back_to_the_constant(monkeypatch):
    monkeypatch.setenv("FRAME_QA_SCENE_CAP", "not-a-number")
    assert fab._scene_cap(TENANT) == fab.FRAME_QA_SCENE_CAP
