"""Tests for D5 chunk A5 (storyengine/FRAME-ARBITER-PLAN.md): the Frame
Arbiter's auto-repair wiring, backend/arbiter_repair.py. BOARD-LEVEL ONLY —
the frames station is frozen pending D5-A3b-2 (tasks/loop-checklist.md).

$0 suite: every DB/network boundary is dependency-injected (is_frozen_fn,
budget_check, reroll_fn, record_finding_fn, ledger_write are keyword params
on repair_board_finding by design — same convention judge_frame/
judge_scene_batch/judge_board_sheet already use) or a stateful fake
standing in for the real Postgres row (same "fake DB enforces the real
constraint" convention test_d5_a2_arbiter_fingerprints.py's own
_fake_fetch_one uses — reused verbatim here via monkeypatching
arbiter_fingerprints.fetch_one directly, not a second reimplementation).
NO live DB, NO network, NO paid calls of any kind.

DoC #2's law (only MODEL_DEFECT ever triggers repair) and DoC #4's law
(the same fingerprint firing twice freezes auto-repair, files a root-cause
finding instead of a third redraw) are both proven here at the repair
layer — DoC #4 already has its A2-level proof in
test_d5_a2_arbiter_fingerprints.py; this file proves the SAME law holds
one layer up, through repair_board_finding's own decision ladder.

Non-vacuous / stash-proof (DoC "prove the guard is actually exercised"):
test_frozen_short_circuits_before_budget_check_order_matters and
test_frame_repair_disabled_by_default_raises were each re-run against a
neutered copy of the guard they check (freeze-check-first swapped to
budget-check-first in repair_board_finding; FRAME_REPAIR_ENABLED's guard
in repair_frame_finding commented out) — both failed as expected (the
neutered freeze-ordering test asserted budget_check was never called and
saw it called; the neutered frame-lock test expected a raise and got a
clean stub return instead), confirming the checks are real, then reverted.
See the chunk report for the exact before/after pytest output.

Run: cd storyengine/backend && ./venv/bin/python -m pytest \
    tests/functional/test_d5_a5_repair.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import arbiter_fingerprints as af  # noqa: E402
import arbiter_repair as ar  # noqa: E402
from frame_arbiter_budget import FRAME_QA_STAGE  # noqa: E402

TENANT = "tenant-a5"
VIDEO = "video-a5"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _finding(classification="MODEL_DEFECT", failure_class="set_bleed", rule_id=None,
             panel=1, sheet_index=1, description="wrong location drawn"):
    return {
        "classification": classification,
        "failure_class": failure_class,
        "rule_id": rule_id,
        "panel": panel,
        "sheet_index": sheet_index,
        "description": description,
        "decisive_prompt_fragment": "Bubble-Pod interior",
    }


async def _no_breach(*_a, **_k):
    return None


async def _always_frozen(*_a, **_k):
    return True


async def _never_frozen(*_a, **_k):
    return False


def _make_tracker():
    calls: list = []

    async def tracker(*args, **kwargs):
        calls.append((args, kwargs))
        return {"status": "done", "message": "ok"}

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


# =============================================================================
# TASTE_QUESTION / AUTHORING_DEFECT: never touch the re-roll path (DoC #2).
# =============================================================================

def test_taste_question_never_acts_no_reroll_no_record():
    reroll = _make_tracker()
    record = _make_sink()
    result = _run(ar.repair_board_finding(
        TENANT, VIDEO, 4, _finding(classification="TASTE_QUESTION"),
        is_frozen_fn=_never_frozen, budget_check=_no_breach,
        reroll_fn=reroll, record_finding_fn=record,
    ))
    assert result["action"] == "card"
    assert result["acted"] is False
    assert reroll.calls == []
    assert record.calls == []  # nothing wrong to remember, only a preference to ask about
    assert result["card"]["classification"] == "TASTE_QUESTION"


def test_authoring_defect_never_touches_reroll_but_files_finding():
    reroll = _make_tracker()
    record = _make_sink()
    result = _run(ar.repair_board_finding(
        TENANT, VIDEO, 4, _finding(classification="AUTHORING_DEFECT", failure_class="facing_law_violation"),
        is_frozen_fn=_never_frozen, budget_check=_no_breach,
        reroll_fn=reroll, record_finding_fn=record,
    ))
    assert result["action"] == "filed"
    assert result["acted"] is False
    assert reroll.calls == []  # never repairs — the spec, not the pixels, is the flaw
    assert len(record.calls) == 1
    assert record.calls[0]["classification"] == "AUTHORING_DEFECT"
    assert record.calls[0]["stage"] == FRAME_QA_STAGE


def test_ok_classification_does_nothing():
    reroll = _make_tracker()
    record = _make_sink()
    result = _run(ar.repair_board_finding(
        TENANT, VIDEO, 4, _finding(classification="OK"),
        is_frozen_fn=_never_frozen, budget_check=_no_breach,
        reroll_fn=reroll, record_finding_fn=record,
    ))
    assert result["acted"] is False
    assert result["action"] == "none"
    assert reroll.calls == []
    assert record.calls == []


# =============================================================================
# MODEL_DEFECT ladder ordering: FREEZE -> BUDGET -> ROLL -> RECORD.
# =============================================================================

def test_frozen_short_circuits_before_budget_check_order_matters():
    """A frozen class must not even consume budget quota — freeze is
    checked BEFORE the budget guard runs, not after. Non-vacuous / stash-
    proof: see module docstring for the neutered-copy re-run that proved
    this ordering assertion actually catches a regression."""
    budget = _make_tracker()
    reroll = _make_tracker()
    result = _run(ar.repair_board_finding(
        TENANT, VIDEO, 4, _finding(),
        is_frozen_fn=_always_frozen, budget_check=budget, reroll_fn=reroll,
    ))
    assert result["action"] == "frozen"
    assert result["acted"] is False
    assert budget.calls == []  # never even asked — no quota consumed
    assert reroll.calls == []
    assert result["fingerprint"] == "set_bleed"


def test_budget_refusal_short_circuits_the_reroll():
    async def breach(*_a, **_k):
        return {"scope": "scene", "cap": 0.25, "spent": 0.23, "quote": 0.05, "projected": 0.28, "message": "no"}

    reroll = _make_tracker()
    record = _make_sink()
    result = _run(ar.repair_board_finding(
        TENANT, VIDEO, 4, _finding(),
        is_frozen_fn=_never_frozen, budget_check=breach,
        reroll_fn=reroll, record_finding_fn=record,
    ))
    assert result["action"] == "budget_refused"
    assert result["acted"] is False
    assert reroll.calls == []
    assert record.calls == []  # a refused repair is not an occurrence of anything


def test_missing_sheet_index_refuses_before_the_ladder_even_starts():
    is_frozen_probe = _make_tracker()

    async def probe(*a, **k):
        is_frozen_probe.calls.append((a, k))
        return False

    finding = _finding()
    finding["sheet_index"] = None
    result = _run(ar.repair_board_finding(
        TENANT, VIDEO, 4, finding, is_frozen_fn=probe,
    ))
    assert result["action"] == "missing_sheet_index"
    assert result["acted"] is False
    assert is_frozen_probe.calls == []  # refused before even the freeze check


def test_reroll_failure_does_not_record_an_occurrence():
    async def failing_reroll(*_a, **_k):
        return {"status": "failed", "error": "no current plan"}

    record = _make_sink()
    result = _run(ar.repair_board_finding(
        TENANT, VIDEO, 4, _finding(),
        is_frozen_fn=_never_frozen, budget_check=_no_breach,
        reroll_fn=failing_reroll, record_finding_fn=record,
    ))
    assert result["action"] == "reroll_failed"
    assert result["acted"] is False
    assert record.calls == []


def test_successful_repair_ledgers_the_repair_spend():
    reroll = _make_tracker()
    ledger = _make_sink()
    record = _make_sink()
    result = _run(ar.repair_board_finding(
        TENANT, VIDEO, 4, _finding(rule_id="QL-9"),
        is_frozen_fn=_never_frozen, budget_check=_no_breach,
        reroll_fn=reroll, ledger_write=ledger, record_finding_fn=record,
    ))
    assert result["acted"] is True
    assert result["action"] == "repaired"
    assert len(reroll.calls) == 1
    ((rargs, rkwargs),) = reroll.calls
    assert rargs == (VIDEO, TENANT)
    assert rkwargs["scene"] == 4
    assert rkwargs["beat"] == 1  # the finding's own sheet_index
    assert len(ledger.calls) == 1
    assert ledger.calls[0]["actual_cost"] == ar.DEFAULT_BOARD_REPAIR_QUOTE
    assert ledger.calls[0]["fingerprint"] == "QL-9"  # rule_id wins fingerprint_key
    assert len(record.calls) == 1


# =============================================================================
# DoC #4 at the repair layer: repeat-repair freeze crosses on the 2nd
# occurrence, via a REAL is_frozen/record_finding pair backed by the exact
# ON-CONFLICT upsert semantics migrations/139 specifies (same stateful-fake
# convention test_d5_a2_arbiter_fingerprints.py already validated at the
# A2 layer — reused here via monkeypatching arbiter_fingerprints.fetch_one
# directly, so THIS test proves the real ratchet functions, not a
# hand-wavy substitute).
# =============================================================================

class _FakeUniqueViolation(Exception):
    pass


def _fp_key(rule_id, failure_class):
    rid = (rule_id or "").strip()
    return rid if rid else str(failure_class or "").strip()


@pytest.fixture
def fingerprint_rows(monkeypatch):
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
            fp_key = _fp_key(rule_id, failure_class)
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


def test_repeat_repair_freeze_crosses_on_the_second_occurrence(fingerprint_rows):
    reroll = _make_tracker()

    def _repair():
        return _run(ar.repair_board_finding(
            TENANT, VIDEO, 4, _finding(failure_class="set_bleed"),
            is_frozen_fn=af.is_frozen, budget_check=_no_breach,
            reroll_fn=reroll, ledger_write=_make_sink(), record_finding_fn=af.record_finding,
        ))

    first = _repair()
    assert first["acted"] is True
    assert first["action"] == "repaired"
    assert first["fingerprint_record"]["frozen"] is False
    assert len(reroll.calls) == 1

    second = _repair()
    assert second["acted"] is True  # not frozen going INTO this call — the 2nd occurrence still repairs
    assert second["action"] == "repaired"
    assert second["fingerprint_record"]["violation_count"] == 2
    assert second["fingerprint_record"]["frozen"] is True  # THIS record call is what crosses it
    assert second["fingerprint_record"]["crossed_threshold"] is True
    assert len(reroll.calls) == 2

    third = _repair()
    assert third["acted"] is False  # blocked at the freeze check — no third roll
    assert third["action"] == "frozen"
    assert len(reroll.calls) == 2  # unchanged — the reroll never fired a third time


def test_different_fingerprint_is_not_blocked_by_a_sibling_freeze(fingerprint_rows):
    reroll = _make_tracker()

    def _repair(failure_class):
        return _run(ar.repair_board_finding(
            TENANT, VIDEO, 4, _finding(failure_class=failure_class),
            is_frozen_fn=af.is_frozen, budget_check=_no_breach,
            reroll_fn=reroll, ledger_write=_make_sink(), record_finding_fn=af.record_finding,
        ))

    _repair("set_bleed")
    _repair("set_bleed")  # freezes set_bleed
    other = _repair("facing_law_violation")  # different fingerprint, same tenant/stage

    assert other["acted"] is True
    assert other["action"] == "repaired"
    assert len(reroll.calls) == 3


# =============================================================================
# Frame-level lock: FRAME_REPAIR_ENABLED=False makes frame repair
# unreachable by construction, not just by convention.
# =============================================================================

def test_shipped_default_is_frame_repair_disabled():
    assert ar.FRAME_REPAIR_ENABLED is False


def test_frame_repair_disabled_by_default_raises():
    with pytest.raises(RuntimeError, match="D5-A3b-2"):
        _run(ar.repair_frame_finding({"classification": "MODEL_DEFECT"}))


def test_frame_repair_stub_reachable_when_flag_flipped_in_test(monkeypatch):
    """Proves the STUB MECHANISM works (the gate, once open, actually lets
    a call through) — not a statement that frame repair is production-safe.
    monkeypatch auto-reverts FRAME_REPAIR_ENABLED to its module value after
    this test, so the shipped default is never actually mutated."""
    monkeypatch.setattr(ar, "FRAME_REPAIR_ENABLED", True)
    result = _run(ar.repair_frame_finding({"classification": "MODEL_DEFECT", "failure_class": "x"}))
    assert result["acted"] is False
    assert result["action"] == "frame_repair_stub_enabled_but_unimplemented"
    # the flag itself is untouched outside this test's monkeypatch scope
    assert ar.FRAME_REPAIR_ENABLED is True  # still patched within this test


def test_flag_is_false_again_after_the_flip_test(monkeypatch):
    """Runs independent of test ordering (stash-proof against a fixture
    leak): confirms the previous test's monkeypatch did not leave the
    module-level default mutated for any test that runs after it."""
    assert ar.FRAME_REPAIR_ENABLED is False
