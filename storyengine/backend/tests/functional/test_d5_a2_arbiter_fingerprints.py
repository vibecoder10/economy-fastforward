"""Tests for D5 chunk A2 (storyengine/FRAME-ARBITER-PLAN.md): the Frame
Arbiter's learning-ratchet memory table + helpers (arbiter_fingerprints.py,
migrations/139_arbiter_fingerprints.sql).

Local/no-spend, no live DB: the fake `fetch_one` below re-implements the
EXACT upsert semantics migrations/139's ON CONFLICT (tenant_id,
fingerprint_key, stage, failure_class) DO UPDATE clause specifies —
dedupe on the same fingerprint, +1 violation_count, freeze from
violation_count==2 onward — same fake-DB-enforces-the-real-constraint
convention as tests/functional/test_c16d_task_store_job_id_conflict.py and
tests/functional/test_generation_ledger.py. If a future edit to
arbiter_fingerprints.record_finding's SQL drops the ON CONFLICT clause (or
renames the fingerprint columns it targets), the fake raises
_FakeUniqueViolation on the second call instead of silently deduping —
this suite would then fail loudly instead of passing on broken code.

DoC #4's proof this file is the unit-level half of ("the same fingerprint
firing twice freezes auto-repair for that class ... proven by a scripted
repeat-failure test"):
  - test_second_occurrence_same_fingerprint_crosses_threshold_and_freezes
  - test_third_occurrence_stays_frozen_without_recrossing
  - test_different_fingerprint_same_stage_does_not_inherit_freeze

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_d5_a2_arbiter_fingerprints.py -q
"""

import asyncio
import os
import sys
import types

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

TENANT = "tenant-1"

ROWS: list[dict] = []


class _FakeUniqueViolation(Exception):
    """Mirrors what real Postgres raises for a duplicate INSERT against
    arbiter_fingerprints' UNIQUE (tenant_id, fingerprint_key, stage,
    failure_class) constraint when the app's own ON CONFLICT clause isn't
    the thing catching it."""


def _fp_key(rule_id, failure_class):
    rid = (rule_id or "").strip()
    return rid if rid else str(failure_class or "").strip()


def _find(tenant_id, fp_key, stage, failure_class):
    return next(
        (r for r in ROWS
         if r["tenant_id"] == tenant_id and r["fingerprint_key"] == fp_key
         and r["stage"] == stage and r["failure_class"] == failure_class),
        None,
    )


async def _fake_fetch_one(query: str, *args):
    if "INSERT INTO arbiter_fingerprints" in query:
        tenant_id, rule_id, stage, failure_class, classification = args
        fp_key = _fp_key(rule_id, failure_class)
        existing = _find(tenant_id, fp_key, stage, failure_class)
        has_on_conflict = (
            "ON CONFLICT" in query
            and "fingerprint_key" in query.split("ON CONFLICT", 1)[1].split("DO UPDATE", 1)[0]
        )
        if existing is not None:
            if not has_on_conflict:
                raise _FakeUniqueViolation(
                    "duplicate key value violates unique constraint "
                    "\"arbiter_fingerprints_tenant_id_fingerprint_key_stage_failure_class_key\""
                )
            existing["violation_count"] += 1
            existing["classification"] = classification
            existing["last_seen_at"] = f"t{existing['violation_count']}"
            existing["frozen"] = existing["violation_count"] >= 2
            row = dict(existing)
            row["crossed_threshold"] = existing["violation_count"] == 2
            return row
        new_row = {
            "id": f"row-{len(ROWS)}", "tenant_id": tenant_id, "rule_id": rule_id,
            "stage": stage, "failure_class": failure_class, "fingerprint_key": fp_key,
            "classification": classification, "violation_count": 1, "frozen": False,
            "root_cause_finding_id": None, "first_seen_at": "t1", "last_seen_at": "t1",
        }
        ROWS.append(new_row)
        row = dict(new_row)
        row["crossed_threshold"] = False
        return row

    if "SELECT frozen FROM arbiter_fingerprints" in query:
        tenant_id, fp_key, stage, failure_class = args
        existing = _find(tenant_id, fp_key, stage, failure_class)
        return {"frozen": existing["frozen"]} if existing else None

    if "UPDATE arbiter_fingerprints SET root_cause_finding_id" in query:
        tenant_id, fp_key, stage, failure_class, finding_id = args
        existing = _find(tenant_id, fp_key, stage, failure_class)
        if existing is None:
            return None
        existing["root_cause_finding_id"] = finding_id
        return dict(existing)

    raise AssertionError(f"unexpected query in fake fetch_one: {query!r}")


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


_stub("database", fetch_one=_fake_fetch_one)

import arbiter_fingerprints as af  # noqa: E402


def _reset():
    ROWS.clear()


def _record(**overrides):
    kwargs = dict(
        rule_id=None, stage="frame_qa", failure_class="continuity_drift",
        classification="MODEL_DEFECT",
    )
    kwargs.update(overrides)
    return asyncio.run(af.record_finding(TENANT, **kwargs))


# ---------------------------------------------------------------------------
# fingerprint_key — pure function, no DB.
# ---------------------------------------------------------------------------

def test_fingerprint_key_prefers_rule_id_over_failure_class():
    assert af.fingerprint_key("QL-12", "hype_words") == "QL-12"


def test_fingerprint_key_falls_back_to_failure_class_when_rule_id_absent():
    assert af.fingerprint_key(None, "hype_words") == "hype_words"
    assert af.fingerprint_key("", "hype_words") == "hype_words"
    assert af.fingerprint_key("   ", "hype_words") == "hype_words"


def test_fingerprint_key_computed_identically_across_repeated_calls():
    # "computed identically every time" (the plan's own law) — same inputs,
    # same output, no hidden state.
    assert af.fingerprint_key("QL-1", "x") == af.fingerprint_key("QL-1", "x")


# ---------------------------------------------------------------------------
# record_finding — first occurrence.
# ---------------------------------------------------------------------------

def test_first_occurrence_records_without_freeze():
    _reset()
    row = _record()
    assert row["violation_count"] == 1
    assert row["frozen"] is False
    assert row["crossed_threshold"] is False
    assert row["classification"] == "MODEL_DEFECT"
    assert row["fingerprint_key"] == "continuity_drift"


def test_classification_stored_and_returned_for_each_bucket():
    for classification in sorted(af.CLASSIFICATIONS):
        _reset()
        row = _record(failure_class=f"class-{classification}", classification=classification)
        assert row["classification"] == classification


# ---------------------------------------------------------------------------
# record_finding — the 2-strikes freeze law (DoC #4), stash-proof.
# ---------------------------------------------------------------------------

def test_second_occurrence_same_fingerprint_crosses_threshold_and_freezes():
    _reset()
    first = _record()
    second = _record()

    assert first["frozen"] is False
    assert second["violation_count"] == 2
    assert second["frozen"] is True
    assert second["crossed_threshold"] is True

    assert asyncio.run(af.is_frozen(
        TENANT, rule_id=None, stage="frame_qa", failure_class="continuity_drift",
    )) is True
    # Dedupe, not a duplicate row.
    assert len(ROWS) == 1


def test_third_occurrence_stays_frozen_without_recrossing():
    _reset()
    _record()
    _record()
    third = _record()

    assert third["violation_count"] == 3
    assert third["frozen"] is True
    assert third["crossed_threshold"] is False  # already frozen, not a NEW crossing


def test_different_fingerprint_same_stage_does_not_inherit_freeze():
    _reset()
    _record()  # 1st occurrence of "continuity_drift"
    _record()  # 2nd occurrence -> freezes "continuity_drift"

    other = _record(failure_class="style_drift")  # different failure_class, same stage

    assert other["frozen"] is False
    assert other["crossed_threshold"] is False
    assert asyncio.run(af.is_frozen(
        TENANT, rule_id=None, stage="frame_qa", failure_class="style_drift",
    )) is False
    # The original fingerprint's freeze is untouched by the sibling record.
    assert asyncio.run(af.is_frozen(
        TENANT, rule_id=None, stage="frame_qa", failure_class="continuity_drift",
    )) is True


def test_two_rule_ids_sharing_a_failure_class_are_separate_fingerprints():
    _reset()
    a = _record(rule_id="QL-1", failure_class="continuity_drift", classification="AUTHORING_DEFECT")
    b = _record(rule_id="QL-2", failure_class="continuity_drift", classification="AUTHORING_DEFECT")

    assert a["violation_count"] == 1
    assert b["violation_count"] == 1
    assert len(ROWS) == 2  # rule_id disambiguates within the same stage+failure_class


def test_different_stage_same_failure_class_is_a_separate_fingerprint():
    _reset()
    _record(stage="frame_qa")
    _record(stage="frame_qa")  # freezes frame_qa/continuity_drift

    other_stage = _record(stage="storyboard_qa")
    assert other_stage["frozen"] is False
    assert other_stage["crossed_threshold"] is False


# ---------------------------------------------------------------------------
# Validation — fails loud, never silently coerced (unlike quality_rules'
# severity fallback: a wrong classification here can misdirect real spend).
# ---------------------------------------------------------------------------

def test_invalid_classification_rejected_before_any_db_call(monkeypatch):
    async def boom(*_a, **_k):
        raise AssertionError("must not touch the DB on an invalid classification")

    monkeypatch.setattr(af, "fetch_one", boom)
    with pytest.raises(ValueError):
        asyncio.run(af.record_finding(
            TENANT, rule_id=None, stage="frame_qa", failure_class="x",
            classification="NOT_A_REAL_BUCKET",
        ))


def test_missing_stage_or_failure_class_rejected():
    with pytest.raises(ValueError):
        asyncio.run(af.record_finding(
            TENANT, rule_id=None, stage="", failure_class="x", classification="MODEL_DEFECT",
        ))
    with pytest.raises(ValueError):
        asyncio.run(af.record_finding(
            TENANT, rule_id=None, stage="frame_qa", failure_class="", classification="MODEL_DEFECT",
        ))


# ---------------------------------------------------------------------------
# is_frozen — read helper.
# ---------------------------------------------------------------------------

def test_is_frozen_false_for_a_fingerprint_never_recorded():
    _reset()
    assert asyncio.run(af.is_frozen(
        TENANT, rule_id=None, stage="frame_qa", failure_class="never_seen",
    )) is False


def test_is_frozen_uses_rule_id_when_present():
    _reset()
    _record(rule_id="QL-9", failure_class="continuity_drift")
    _record(rule_id="QL-9", failure_class="continuity_drift")
    assert asyncio.run(af.is_frozen(
        TENANT, rule_id="QL-9", stage="frame_qa", failure_class="continuity_drift",
    )) is True
    # No rule_id -> falls back to failure_class as the key -> different bucket, not frozen.
    assert asyncio.run(af.is_frozen(
        TENANT, rule_id=None, stage="frame_qa", failure_class="continuity_drift",
    )) is False


# ---------------------------------------------------------------------------
# set_root_cause — schema-only plumbing for A5, exercised here so the
# pointer field isn't dead code with zero test coverage.
# ---------------------------------------------------------------------------

def test_set_root_cause_points_at_the_filed_finding():
    _reset()
    _record()
    _record()  # freezes it
    updated = asyncio.run(af.set_root_cause(
        TENANT, rule_id=None, stage="frame_qa", failure_class="continuity_drift",
        finding_id="finding-123",
    ))
    assert updated["root_cause_finding_id"] == "finding-123"


def test_set_root_cause_no_op_for_unknown_fingerprint():
    _reset()
    assert asyncio.run(af.set_root_cause(
        TENANT, rule_id=None, stage="frame_qa", failure_class="never_seen",
        finding_id="finding-123",
    )) is None
