"""Tests for D8-3 (chunk A7, storyengine/FRAME-ARBITER-PLAN.md): the Review
feed's Findings tab backend endpoint, GET /api/review/findings.

Updated by D8-3b (chunk 3b): the endpoint now ALSO reads the per-instance
`arbiter_findings` table (migration 146) — the gap D8-3 itself documented
in get_findings' own docstring ("no per-instance findings table to query
yet"). This file's fake_fetch_all dispatcher now handles a THIRD query
branch; the two original branches (fingerprints, ledger spend) are
unchanged.

Same stub pattern as test_c15b_show_and_approve_scene.py: stub `database`
before importing routes.review (its `from database import fetch_all,
fetch_one, execute` binds those names as module-level attributes on
routes.review itself — tests monkeypatch them there directly, no live DB,
no network).

Proves the endpoint reads the three REAL, persisted tables (A2's
arbiter_fingerprints, A1's generation_ledger frame_qa-stage rows, D8-3b's
arbiter_findings per-instance rows), scopes all three to tenant_id, and
shapes the rows exactly per backend/models.py's ArbiterFinding/ArbiterSpend/
ArbiterFindingInstance field names — a field-name mismatch here is exactly
the "StoryEngine wiring failure" this project's own CLAUDE.md calls out by
name (frontend/src/lib/api.ts's types are copied verbatim from these
models).

Each test asserts `hasattr(review, "get_findings")` first so a stash of this
chunk's implementation fails LOUDLY with a real AssertionError (not a bare
AttributeError from Python's own attribute lookup) — the explicit stash-proof
this chunk's report requires.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_d8_3_review_findings.py -q
"""
import asyncio
import os
import sys
import types
from datetime import datetime, timezone

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


async def _boom(*a, **k):
    raise AssertionError("pure tests must not touch runtime services")


_stub("database", fetch_one=_boom, fetch_all=_boom, execute=_boom)

import routes.review as review  # noqa: E402

TENANT = "tenant-1"


def _fingerprint_row(**over):
    base = {
        "id": "fp-1",
        "rule_id": "rule-5g",
        "stage": "frame_qa",
        "failure_class": "duplicate_setup",
        "fingerprint_key": "rule-5g",
        "classification": "MODEL_DEFECT",
        "violation_count": 2,
        "frozen": True,
        "first_seen_at": datetime(2026, 7, 29, tzinfo=timezone.utc),
        "last_seen_at": datetime(2026, 7, 30, tzinfo=timezone.utc),
    }
    base.update(over)
    return base


def _spend_row(**over):
    base = {
        "video_id": "video-1",
        "scene": 4,
        "video_title": "Test Video",
        "qa_passes": 3,
        "total_cost": 0.15,
        "last_judged_at": datetime(2026, 7, 30, tzinfo=timezone.utc),
    }
    base.update(over)
    return base


def _instance_row(**over):
    base = {
        "id": "inst-1",
        "video_id": "video-1",
        "video_title": "Test Video",
        "scene": 4,
        "station": "board",
        "reference": "panel 1",
        "label": "M1 WS",
        "image_url": "https://x/sheet-1.png",
        "classification": "MODEL_DEFECT",
        "failure_class": "set_bleed",
        "rule_id": None,
        "fingerprint_key": "set_bleed",
        "rubric_level": "hard_gate",
        "decisive_prompt_fragment": None,
        "description": "wrong location drawn",
        "new_vs_previous": "FIRST_PANEL",
        "cost": 0.02,
        "created_at": datetime(2026, 7, 30, tzinfo=timezone.utc),
    }
    base.update(over)
    return base


def test_findings_endpoint_shapes_fingerprints_and_ledger_spend(monkeypatch):
    """The three real tables (A2 fingerprints, A1 ledger, D8-3b per-instance
    arbiter_findings) all get read, scoped to tenant_id, and shaped into the
    exact ArbiterFinding/ArbiterSpend/ArbiterFindingInstance field names — a
    mismatch here would silently break the frontend, exactly the
    StoryEngine wiring failure this project's CLAUDE.md warns about."""
    assert hasattr(review, "get_findings"), "D8-3: GET /api/review/findings must exist"

    calls = []

    async def fake_fetch_all(query, *args):
        calls.append((query, args))
        if "arbiter_fingerprints" in query:
            assert args == (TENANT,), "fingerprints query must scope to tenant_id"
            return [_fingerprint_row()]
        if "generation_ledger" in query:
            assert args == (TENANT,), "ledger query must scope to tenant_id"
            assert "stage = 'frame_qa'" in query, "must filter to the frame_qa stage only"
            return [_spend_row()]
        if "arbiter_findings" in query:
            assert args == (TENANT, 200), "per-instance query must scope to tenant_id + the limit"
            return [_instance_row()]
        raise AssertionError(f"unexpected query: {query}")

    monkeypatch.setattr(review, "fetch_all", fake_fetch_all)

    result = asyncio.run(review.get_findings(tenant_id=TENANT))

    assert len(calls) == 3

    assert len(result.findings) == 1
    f = result.findings[0]
    assert f.id == "fp-1"
    assert f.rule_id == "rule-5g"
    assert f.stage == "frame_qa"
    assert f.failure_class == "duplicate_setup"
    assert f.fingerprint_key == "rule-5g"
    assert f.classification == "MODEL_DEFECT"
    assert f.violation_count == 2
    assert f.frozen is True
    assert f.first_seen_at == "2026-07-29T00:00:00+00:00"
    assert f.last_seen_at == "2026-07-30T00:00:00+00:00"

    assert len(result.spend) == 1
    s = result.spend[0]
    assert s.video_id == "video-1"
    assert s.video_title == "Test Video"
    assert s.scene == 4
    assert s.qa_passes == 3
    assert s.total_cost == 0.15
    assert s.last_judged_at == "2026-07-30T00:00:00+00:00"

    assert len(result.instances) == 1
    i = result.instances[0]
    assert i.id == "inst-1"
    assert i.video_id == "video-1"
    assert i.video_title == "Test Video"
    assert i.scene == 4
    assert i.station == "board"
    assert i.reference == "panel 1"
    assert i.label == "M1 WS"
    assert i.image_url == "https://x/sheet-1.png"
    assert i.classification == "MODEL_DEFECT"
    assert i.failure_class == "set_bleed"
    assert i.rule_id is None
    assert i.fingerprint_key == "set_bleed"
    assert i.rubric_level == "hard_gate"
    assert i.description == "wrong location drawn"
    assert i.new_vs_previous == "FIRST_PANEL"
    assert i.cost == 0.02
    assert i.created_at == "2026-07-30T00:00:00+00:00"


def test_findings_endpoint_empty_when_nothing_judged_yet(monkeypatch):
    """No fingerprints, no ledger rows, no per-instance rows (today's real
    prod state — D8-2's first live run hasn't happened yet) -> empty lists,
    not an error. This is the exact shape the frontend's EmptyState branch
    is built against."""
    assert hasattr(review, "get_findings"), "D8-3: GET /api/review/findings must exist"

    async def fake_fetch_all(query, *args):
        return []

    monkeypatch.setattr(review, "fetch_all", fake_fetch_all)

    result = asyncio.run(review.get_findings(tenant_id=TENANT))
    assert result.findings == []
    assert result.spend == []
    assert result.instances == []


def test_findings_endpoint_scopes_all_queries_to_tenant(monkeypatch):
    """A different tenant's fingerprint/ledger/instance rows must never leak
    in — all three queries are parameterized on tenant_id, never
    string-interpolated."""
    assert hasattr(review, "get_findings"), "D8-3: GET /api/review/findings must exist"

    seen_args = []

    async def fake_fetch_all(query, *args):
        seen_args.append(args)
        return []

    monkeypatch.setattr(review, "fetch_all", fake_fetch_all)

    asyncio.run(review.get_findings(tenant_id="tenant-other"))
    assert seen_args == [("tenant-other",), ("tenant-other",), ("tenant-other", 200)]
