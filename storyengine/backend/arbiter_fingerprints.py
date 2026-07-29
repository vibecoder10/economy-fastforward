"""Frame Arbiter learning-ratchet memory (D5 mission, chunk A2).

storyengine/FRAME-ARBITER-PLAN.md's whole point: a judge that looks at
every new frame is only safe if it REMEMBERS. Without this table, the same
recurring model defect gets redrawn forever — an unbounded spend loop
Ryan's ruling explicitly forbids. This module is the data layer for that
memory: nothing in the product calls it yet (A3's judge call and A5's
auto-repair wiring will) — this chunk is schema + upsert/read helpers +
tests only, mirroring quality_rules.py's own CRUD layering (a pure
key-computation function, then thin DB-touching functions, nothing else).

Fingerprint law (verbatim from the plan — do not reinterpret): fingerprint
= (rule_id or failure_class, stage, failure_class), computed identically
every time, no free text in the key. `fingerprint_key()` below and the
`arbiter_fingerprints` table's own GENERATED ALWAYS AS column
(migrations/139_arbiter_fingerprints.sql) compute this the exact same way
(COALESCE(rule_id, failure_class)) — the Python copy exists only so a
caller can filter reads without a second round trip, never as a
second source of truth that could drift from the DB's.

Precedent this deliberately does NOT copy: migrations/118_motion_gate_
status.sql's motion_gate_status freezes one SHOT after two attempts on
that shot. record_finding's freeze is per-CLASS, across every scene and
video for the tenant, forever — there is no unfreeze path in this chunk.

Precedent this DOES copy: quality_rules.py's create_rule upsert — INSERT
... ON CONFLICT (unique key) DO UPDATE, so a repeat occurrence edits the
SAME row in place instead of accumulating duplicates.
"""

from __future__ import annotations

from typing import Any, Optional

from database import fetch_one

# DoC #2's three-way bucket. Only MODEL_DEFECT may ever reach redraw_shot
# (A5, not built here). Unlike quality_rules.create_rule's severity, which
# silently falls back to "guidance" on an unrecognized value, an invalid
# classification here is REJECTED, not coerced — a wrong bucket can
# misdirect real spend (an AUTHORING_DEFECT quietly becoming a MODEL_DEFECT
# would trigger a redraw that should never fire), so this fails loud.
CLASSIFICATIONS = {"MODEL_DEFECT", "AUTHORING_DEFECT", "TASTE_QUESTION"}

# The exact violation_count at which a fingerprint freezes (DoC #4:
# "the same fingerprint firing twice freezes auto-repair for that class").
FREEZE_THRESHOLD = 2

_SELECT_COLS = (
    "id, tenant_id, rule_id, stage, failure_class, fingerprint_key, "
    "classification, violation_count, frozen, root_cause_finding_id, "
    "first_seen_at, last_seen_at"
)


def fingerprint_key(rule_id: Optional[str], failure_class: str) -> str:
    """Pure, deterministic fingerprint-key computation — no DB, no network,
    no free text: rule_id when present, else failure_class. Computed the
    identical way every time (the plan's own words), matching the table's
    GENERATED ALWAYS AS COALESCE(rule_id, failure_class) column exactly."""
    rid = (rule_id or "").strip()
    if rid:
        return rid
    return str(failure_class or "").strip()


def _decode_row(row: Optional[dict]) -> Optional[dict]:
    if row is None:
        return None
    return dict(row)


def _require_stage_and_class(stage: str, failure_class: str) -> tuple[str, str]:
    stage = str(stage or "").strip()
    failure_class = str(failure_class or "").strip()
    if not stage:
        raise ValueError("stage is required")
    if not failure_class:
        raise ValueError("failure_class is required")
    return stage, failure_class


async def record_finding(
    tenant_id: Any,
    *,
    rule_id: Optional[str],
    stage: str,
    failure_class: str,
    classification: str,
) -> dict:
    """Record one occurrence of a fingerprint (first or repeat). Mirrors
    quality_rules.py's create_rule ON CONFLICT pattern: INSERT ... ON
    CONFLICT (tenant_id, fingerprint_key, stage, failure_class) DO UPDATE,
    so a second call for the SAME fingerprint edits the same row
    (violation_count += 1) instead of inserting a duplicate.

    Returns the row (dict) plus a `crossed_threshold` key: True ONLY on the
    exact occurrence where violation_count becomes FREEZE_THRESHOLD (2) —
    the one moment auto-repair freezes for that class (DoC #4). A 3rd, 4th,
    ... occurrence keeps `frozen: True` but `crossed_threshold: False` —
    already frozen is not a NEW crossing event.

    Raises ValueError for a missing stage/failure_class or an
    unrecognized classification — never silently coerced (see module
    docstring: this value can misdirect real spend, unlike quality_rules'
    softer severity fallback)."""
    if classification not in CLASSIFICATIONS:
        raise ValueError(
            f"invalid classification: {classification!r} (must be one of {sorted(CLASSIFICATIONS)})"
        )
    stage, failure_class = _require_stage_and_class(stage, failure_class)
    rule_id_val = (str(rule_id).strip() or None) if rule_id else None

    row = await fetch_one(
        f"""INSERT INTO arbiter_fingerprints (tenant_id, rule_id, stage, failure_class, classification)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (tenant_id, fingerprint_key, stage, failure_class) DO UPDATE SET
              violation_count = arbiter_fingerprints.violation_count + 1,
              classification = EXCLUDED.classification,
              last_seen_at = now(),
              frozen = (arbiter_fingerprints.violation_count + 1) >= {FREEZE_THRESHOLD}
            RETURNING {_SELECT_COLS}, (violation_count = {FREEZE_THRESHOLD}) AS crossed_threshold""",
        tenant_id, rule_id_val, stage, failure_class, classification,
    )
    return _decode_row(row)


async def is_frozen(
    tenant_id: Any,
    *,
    rule_id: Optional[str] = None,
    stage: str,
    failure_class: str,
) -> bool:
    """Read helper: has THIS exact fingerprint (rule_id-or-failure_class +
    stage + failure_class) crossed the freeze threshold? False for any
    fingerprint never recorded (fail-open on auto-repair eligibility for an
    unseen failure — the freeze only ever engages from real repeat
    evidence, never a default)."""
    stage, failure_class = _require_stage_and_class(stage, failure_class)
    row = await fetch_one(
        "SELECT frozen FROM arbiter_fingerprints WHERE tenant_id = $1 "
        "AND fingerprint_key = $2 AND stage = $3 AND failure_class = $4",
        tenant_id, fingerprint_key(rule_id, failure_class), stage, failure_class,
    )
    return bool(row and row.get("frozen"))


async def set_root_cause(
    tenant_id: Any,
    *,
    rule_id: Optional[str] = None,
    stage: str,
    failure_class: str,
    finding_id: Any,
) -> Optional[dict]:
    """Point an already-recorded fingerprint at the root-cause finding its
    freeze event filed. Schema-only plumbing for this chunk — nothing
    calls this yet; A5 will, once it actually files that finding on the
    crossed_threshold occurrence."""
    stage, failure_class = _require_stage_and_class(stage, failure_class)
    row = await fetch_one(
        f"""UPDATE arbiter_fingerprints SET root_cause_finding_id = $5
            WHERE tenant_id = $1 AND fingerprint_key = $2 AND stage = $3 AND failure_class = $4
            RETURNING {_SELECT_COLS}""",
        tenant_id, fingerprint_key(rule_id, failure_class), stage, failure_class, finding_id,
    )
    return _decode_row(row)
