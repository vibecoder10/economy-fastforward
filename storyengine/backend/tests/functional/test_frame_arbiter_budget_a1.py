"""D5 chunk A1 (FRAME-ARBITER-PLAN.md): the Frame Arbiter's pre-call spend
guard, backend/frame_arbiter_budget.py. Nothing calls this module in
production yet (A3/A5 will) — this is the guard's own unit-test proof,
independent of any caller.

DoC #3's test lives here: a cap-exceeding projected call is refused BEFORE
it ever fires — never audited after the fact. Style: real module imported
directly, database.py boundary monkeypatched at the module level
(``frame_arbiter_budget.fetch_one`` / ``.execute``) — same convention as
test_money_safety_gaps_c56.py / test_c36_budget_cap.py. No live DB, no
network, $0.

Non-vacuous / stash-proof: test_scene_cap_refuses_before_any_call and
test_video_cap_independently_enforced were re-run against a neutered copy
of arbiter_budget_check (cap checks short-circuited to `return None`,
mirroring the "confirmed via git stash" convention test_c36_budget_cap.py
documents) — both failed as expected, confirmed the guard was actually
being exercised, then reverted. See the chunk report for the exact
before/after pytest output.

Run: cd storyengine/backend && ./venv/bin/python -m pytest \
    tests/functional/test_frame_arbiter_budget_a1.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import frame_arbiter_budget as fab  # noqa: E402
import generation_ledger as ledger_mod  # noqa: E402

TENANT = "tenant-a1"
VIDEO = "video-a1"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _mock_spend(monkeypatch, scene_spend: dict, video_spend: float):
    """Fakes fab._frame_qa_spend's underlying fetch_one so scene=N returns
    scene_spend[N] and scene=None (the whole-video sum) returns
    video_spend — independent knobs, matching how the two caps are
    genuinely independent sums over generation_ledger."""
    async def fake_fetch_one(query, *args):
        if "AND scene = $4" in query:
            _, _, _, scene = args
            return {"spent": scene_spend.get(scene, 0.0)}
        return {"spent": video_spend}

    monkeypatch.setattr(fab, "fetch_one", fake_fetch_one)


# =============================================================================
# 1. Under-cap: allowed, both caps independently checked.
# =============================================================================

def test_under_both_caps_allowed(monkeypatch):
    _mock_spend(monkeypatch, scene_spend={1: 0.0}, video_spend=0.0)
    result = _run(fab.arbiter_budget_check(TENANT, VIDEO, 1, 0.10))
    assert result is None


def test_scene_none_still_checks_video_cap(monkeypatch):
    """scene=None (a video-level QA pass, no single scene to scope to)
    skips the scene check entirely but the video cap still always
    applies — the plan's DoC #3 doesn't carve out an unguarded path."""
    _mock_spend(monkeypatch, scene_spend={}, video_spend=0.49)
    result = _run(fab.arbiter_budget_check(TENANT, VIDEO, None, 0.10))
    assert result is not None
    assert result["scope"] == "video"


# =============================================================================
# 2. DoC #3's test: a cap-exceeding projected call is refused BEFORE it
#    fires, for EACH cap independently.
# =============================================================================

def test_scene_cap_refuses_before_any_call(monkeypatch):
    """Scene 3 already has $0.20 in frame_qa spend; a $0.10 quote would put
    it at $0.30, over the $0.25 scene cap — refused, even though the WHOLE
    video is nowhere near its $0.50 cap."""
    _mock_spend(monkeypatch, scene_spend={3: 0.20}, video_spend=0.20)
    called = {"fired": False}

    async def would_be_paid_call():
        called["fired"] = True

    breach = _run(fab.arbiter_budget_check(TENANT, VIDEO, 3, 0.10))
    assert breach is not None
    assert breach["scope"] == "scene"
    assert breach["scene"] == 3
    assert breach["cap"] == fab.FRAME_QA_SCENE_CAP
    assert breach["projected"] == pytest.approx(0.30)
    # The guard is checked BEFORE the paid call — a real caller (A3/A5)
    # never reaches its provider call when this is truthy. Simulate that
    # control flow here so a future caller that inverts the check (calls
    # first, checks after) would show up as a failure in ITS OWN test, not
    # silently pass this one.
    if breach:
        pass  # refused — the call below must never fire
    else:
        _run(would_be_paid_call())
    assert called["fired"] is False


def test_video_cap_independently_enforced(monkeypatch):
    """Every individual scene sits comfortably under the $0.25 scene cap,
    but the video's frame_qa total is $0.45 — a further $0.10 quote would
    push the VIDEO total to $0.55, over the $0.50 video cap. Proves the two
    caps are separate sums, not one derived from the other."""
    _mock_spend(monkeypatch, scene_spend={7: 0.05}, video_spend=0.45)
    breach = _run(fab.arbiter_budget_check(TENANT, VIDEO, 7, 0.10))
    assert breach is not None
    assert breach["scope"] == "video"
    assert breach["cap"] == fab.FRAME_QA_VIDEO_CAP
    assert breach["projected"] == pytest.approx(0.55)


def test_scene_breach_checked_before_video_breach(monkeypatch):
    """When BOTH caps would be breached by the same call, the scene breach
    (the tighter, cheaper-to-hit limit) is the one reported."""
    _mock_spend(monkeypatch, scene_spend={2: 0.24}, video_spend=0.49)
    breach = _run(fab.arbiter_budget_check(TENANT, VIDEO, 2, 0.10))
    assert breach is not None
    assert breach["scope"] == "scene"


# =============================================================================
# 3. arbiter_budget_refusal — the plain-English wrapper, same shape as
#    actions.budget_refusal.
# =============================================================================

def test_refusal_none_under_cap(monkeypatch):
    _mock_spend(monkeypatch, scene_spend={1: 0.0}, video_spend=0.0)
    assert _run(fab.arbiter_budget_refusal(TENANT, VIDEO, 1, 0.05)) is None


def test_refusal_message_over_scene_cap(monkeypatch, capsys):
    _mock_spend(monkeypatch, scene_spend={5: 0.20}, video_spend=0.20)
    msg = _run(fab.arbiter_budget_refusal(TENANT, VIDEO, 5, 0.10, "this redraw"))
    assert msg is not None
    assert "cap" in msg.lower()
    assert "this redraw" in msg
    # Refused, logged loudly (generation_ledger.py's DUPLICATE SKIPPED
    # convention) — not silent.
    captured = capsys.readouterr()
    assert "REFUSED" in captured.out


# =============================================================================
# 4. Ledger rows are written in the frame_qa shape (stage/scene/fingerprint).
# =============================================================================

def test_record_frame_qa_entry_writes_frame_qa_shape(monkeypatch):
    seen = {}

    async def fake_record_ledger_entry(**kwargs):
        seen.update(kwargs)

    monkeypatch.setattr(ledger_mod, "record_ledger_entry", fake_record_ledger_entry)
    # frame_arbiter_budget imports record_ledger_entry lazily inside the
    # function (avoids a hard import-order dependency) — patch the module
    # it actually resolves the name from.
    monkeypatch.setitem(sys.modules, "generation_ledger", ledger_mod)

    _run(fab.record_frame_qa_entry(
        tenant_id=TENANT, video_id=VIDEO, scene=4, model="claude-vision",
        units=1, unit_cost=0.03, actual_cost=0.03,
        fingerprint="axis_drift:frame_qa:MODEL_DEFECT",
    ))

    assert seen["stage"] == fab.FRAME_QA_STAGE
    assert seen["scene"] == 4
    assert seen["fingerprint"] == "axis_drift:frame_qa:MODEL_DEFECT"
    assert seen["tenant_id"] == TENANT
    assert seen["video_id"] == VIDEO
    assert seen["actual_cost"] == 0.03


def test_generation_ledger_insert_sql_carries_scene_and_fingerprint():
    """Static pin on generation_ledger.py's INSERT itself (not just the
    mock above) — the real SQL must name both new columns, or A1's ledger
    rows would silently drop them the moment the mock is removed."""
    src = open(os.path.join(_BACKEND, "generation_ledger.py")).read()
    assert "scene" in src.split("INSERT INTO generation_ledger")[1].split(")")[0]
    assert "fingerprint" in src.split("INSERT INTO generation_ledger")[1].split(")")[0]
