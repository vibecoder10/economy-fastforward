"""Tests for D5 chunk A5 (storyengine/FRAME-ARBITER-PLAN.md): the Frame
Arbiter's auto-repair wiring, backend/arbiter_repair.py. BOARD-LEVEL ONLY —
the frames station is frozen pending D5-A3b-2 (tasks/loop-checklist.md).

$0 suite: every DB/network boundary is dependency-injected (is_frozen_fn,
budget_check, reroll_fn, ledger_write are keyword params on
repair_board_finding by design — same convention judge_frame/
judge_scene_batch/judge_board_sheet already use) or a stateful fake
standing in for the real Postgres row (same "fake DB enforces the real
constraint" convention test_d5_a2_arbiter_fingerprints.py's own
_fake_fetch_one uses — reused verbatim here via monkeypatching
arbiter_fingerprints.fetch_one directly, not a second reimplementation).
NO live DB, NO network, NO paid calls of any kind.

RULING (see arbiter_repair.py's module docstring): fingerprint occurrences
are recorded at JUDGMENT TIME ONLY — repair_board_finding never calls
record_finding, for any classification. DoC #4's law (the same fingerprint
firing twice freezes auto-repair) is proven here through the CORRECT
sequence: a judge-time record_finding call (modeling what
judge_board_sheet does at judgment time) is strike one; repair_board_
finding acts on it (rolls, records nothing); a second judge-time
record_finding call (modeling either a post-repair rejudge_board_after_
repair still finding the same fingerprint, or the fingerprint recurring in
some later judgment) is strike two and crosses the freeze; a THIRD repair
attempt for that fingerprint is what actually gets turned away, at the
freeze check, before budget. The happy path (rejudge passes) is proven
too: no second record_finding call ever fires, so the fingerprint stays
at one occurrence, unfrozen.

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

def test_taste_question_never_acts_no_reroll():
    reroll = _make_tracker()
    result = _run(ar.repair_board_finding(
        TENANT, VIDEO, 4, _finding(classification="TASTE_QUESTION"),
        is_frozen_fn=_never_frozen, budget_check=_no_breach, reroll_fn=reroll,
    ))
    assert result["action"] == "card"
    assert result["acted"] is False
    assert reroll.calls == []
    assert result["card"]["classification"] == "TASTE_QUESTION"


def test_authoring_defect_never_touches_reroll_and_never_records():
    """Already recorded by judge_board_sheet at judgment time — this
    module writes nothing, ever (RULING, module docstring)."""
    reroll = _make_tracker()
    result = _run(ar.repair_board_finding(
        TENANT, VIDEO, 4, _finding(classification="AUTHORING_DEFECT", failure_class="facing_law_violation"),
        is_frozen_fn=_never_frozen, budget_check=_no_breach, reroll_fn=reroll,
    ))
    assert result["action"] == "no_repair"
    assert result["reason"] == "authoring_defect"
    assert result["acted"] is False
    assert reroll.calls == []  # never repairs — the spec, not the pixels, is the flaw


def test_ok_classification_does_nothing():
    reroll = _make_tracker()
    result = _run(ar.repair_board_finding(
        TENANT, VIDEO, 4, _finding(classification="OK"),
        is_frozen_fn=_never_frozen, budget_check=_no_breach, reroll_fn=reroll,
    ))
    assert result["acted"] is False
    assert result["action"] == "none"
    assert reroll.calls == []


# =============================================================================
# MODEL_DEFECT ladder ordering: FREEZE -> BUDGET -> ROLL. No record step —
# repair_board_finding never writes to the fingerprint ratchet (RULING).
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
    result = _run(ar.repair_board_finding(
        TENANT, VIDEO, 4, _finding(),
        is_frozen_fn=_never_frozen, budget_check=breach, reroll_fn=reroll,
    ))
    assert result["action"] == "budget_refused"
    assert result["acted"] is False
    assert reroll.calls == []


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


def test_reroll_failure_is_reported_and_nothing_else_happens():
    async def failing_reroll(*_a, **_k):
        return {"status": "failed", "error": "no current plan"}

    result = _run(ar.repair_board_finding(
        TENANT, VIDEO, 4, _finding(),
        is_frozen_fn=_never_frozen, budget_check=_no_breach, reroll_fn=failing_reroll,
    ))
    assert result["action"] == "reroll_failed"
    assert result["acted"] is False


def test_successful_repair_ledgers_the_spend_and_never_records_a_finding():
    reroll = _make_tracker()
    ledger = _make_sink()
    result = _run(ar.repair_board_finding(
        TENANT, VIDEO, 4, _finding(rule_id="QL-9"),
        is_frozen_fn=_never_frozen, budget_check=_no_breach,
        reroll_fn=reroll, ledger_write=ledger,
    ))
    assert result["acted"] is True
    assert result["action"] == "repaired"
    assert "fingerprint_record" not in result  # this module never writes the ratchet
    assert len(reroll.calls) == 1
    ((rargs, rkwargs),) = reroll.calls
    assert rargs == (VIDEO, TENANT)
    assert rkwargs["scene"] == 4
    assert rkwargs["beat"] == 1  # the finding's own sheet_index
    assert len(ledger.calls) == 1  # money spent still ledgers — a separate axis from the ratchet
    assert ledger.calls[0]["actual_cost"] == ar.DEFAULT_BOARD_REPAIR_QUOTE
    assert ledger.calls[0]["fingerprint"] == "QL-9"  # rule_id wins fingerprint_key


# =============================================================================
# DoC #4 at the repair layer, CORRECTED semantics (RULING): fingerprint
# occurrences are recorded at judgment time only. Each test below models
# judge_board_sheet's own record_finding call DIRECTLY (via the real
# af.record_finding, backed by a stateful fake that mirrors migrations/139's
# exact ON-CONFLICT upsert semantics — same convention
# test_d5_a2_arbiter_fingerprints.py already validated at the A2 layer) to
# stand in for "a judgment happened", interleaved with real
# ar.repair_board_finding calls (is_frozen_fn=af.is_frozen, real) to prove
# repair never itself moves the ratchet, only reads it.
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


async def _judgment(failure_class="set_bleed", classification="MODEL_DEFECT", rule_id=None):
    """Stands in for judge_board_sheet's own record_finding call at
    judgment time — the ONLY writer of fingerprint occurrences."""
    return await af.record_finding(
        TENANT, rule_id=rule_id, stage=FRAME_QA_STAGE,
        failure_class=failure_class, classification=classification,
    )


def _repair(reroll, sheet_index=1, budget_check=_no_breach, scene=4):
    return _run(ar.repair_board_finding(
        TENANT, VIDEO, scene, _finding(failure_class="set_bleed", sheet_index=sheet_index),
        is_frozen_fn=af.is_frozen, budget_check=budget_check,
        reroll_fn=reroll, ledger_write=_make_sink(),
    ))


def test_repeat_repair_freeze_crosses_via_rejudge_not_via_repair_itself(fingerprint_rows):
    """The corrected sequence: judge finds the defect (strike 1) -> repair
    rolls, recording nothing -> post-repair re-judge still fails (strike 2,
    freeze crosses HERE, not inside repair) -> a later repair attempt for
    the same fingerprint is blocked at the freeze check, before budget."""
    reroll = _make_tracker()

    strike1 = _run(_judgment())
    assert strike1["violation_count"] == 1
    assert strike1["frozen"] is False

    repaired = _repair(reroll)
    assert repaired["acted"] is True
    assert repaired["action"] == "repaired"
    assert "fingerprint_record" not in repaired  # repair itself writes nothing
    assert len(reroll.calls) == 1
    # Still only one occurrence on the books — the repair did not record.
    assert _run(af.is_frozen(TENANT, rule_id=None, stage=FRAME_QA_STAGE, failure_class="set_bleed")) is False

    # Post-repair re-judge (rejudge_board_after_repair's own job, modeled
    # here as the judgment it would trigger): STILL FAILING, same fingerprint.
    strike2 = _run(_judgment())
    assert strike2["violation_count"] == 2
    assert strike2["frozen"] is True  # THIS judgment is what crosses it
    assert strike2["crossed_threshold"] is True

    # A later repair attempt (e.g. another sheet hitting the same class)
    # never reaches budget or the reroll — turned away at the freeze check.
    budget_probe = _make_tracker()
    blocked = _repair(reroll, sheet_index=2, budget_check=budget_probe, scene=5)
    assert blocked["acted"] is False
    assert blocked["action"] == "frozen"
    assert budget_probe.calls == []  # no quota consumed
    assert len(reroll.calls) == 1  # unchanged — no third roll


def test_repair_happy_path_rejudge_passes_no_second_strike(fingerprint_rows):
    """The rejudge coming back clean means judge_board_sheet never calls
    record_finding again (OK isn't one of A2's three defect buckets) — the
    fingerprint stays at one occurrence, unfrozen, and a later finding of
    the SAME class is free to repair again."""
    reroll = _make_tracker()

    strike1 = _run(_judgment())
    assert strike1["violation_count"] == 1

    repaired = _repair(reroll)
    assert repaired["acted"] is True

    # Re-judge PASSES this time — no record_finding call fires at all (OK
    # verdicts never reach the ratchet), so nothing changes here. Modeled
    # by simply NOT calling _judgment() again.
    row = next(r for r in fingerprint_rows if r["failure_class"] == "set_bleed")
    assert row["violation_count"] == 1
    assert row["frozen"] is False
    assert _run(af.is_frozen(TENANT, rule_id=None, stage=FRAME_QA_STAGE, failure_class="set_bleed")) is False

    # A later finding of the same class is still free to repair — the
    # ratchet never crossed.
    again = _repair(reroll, sheet_index=3, scene=6)
    assert again["acted"] is True
    assert again["action"] == "repaired"
    assert len(reroll.calls) == 2


def test_different_fingerprint_is_not_blocked_by_a_sibling_freeze(fingerprint_rows):
    reroll = _make_tracker()

    # Freeze set_bleed via two judge-time occurrences (no repair involved
    # in crossing it — matches the RULING).
    _run(_judgment(failure_class="set_bleed"))
    _run(_judgment(failure_class="set_bleed"))
    assert _run(af.is_frozen(TENANT, rule_id=None, stage=FRAME_QA_STAGE, failure_class="set_bleed")) is True

    # A DIFFERENT fingerprint (facing_law_violation), only ever judged
    # once, is untouched by set_bleed's freeze.
    _run(_judgment(failure_class="facing_law_violation"))
    other = _run(ar.repair_board_finding(
        TENANT, VIDEO, 4, _finding(failure_class="facing_law_violation", sheet_index=1),
        is_frozen_fn=af.is_frozen, budget_check=_no_breach,
        reroll_fn=reroll, ledger_write=_make_sink(),
    ))

    assert other["acted"] is True
    assert other["action"] == "repaired"
    assert len(reroll.calls) == 1


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
