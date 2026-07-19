"""Tests for checklist C51 (P4.2-b) — the candidate auto-launch loop.

Covers autopilot_launch.auto_launch_best_candidate's money-safety invariants:
  1. kill-switch-tripped tenant is skipped outright (no scoring, no proposal).
  2. disabled tenant is skipped.
  3. propose_only records a proposal and PROVABLY never calls launch_candidate.
  4. auto_draft calls the EXISTING launch_candidate path exactly once.
  5. below-threshold candidate -> no proposal, no launch.
  6. dedup: a candidate with an undecided proposal is skipped in favor of the
     next qualifying candidate (or None if none qualify).
  7. cadence: not-due -> no action even though everything else would qualify.
  8. in-flight: a non-terminal engine-launched video blocks the lane.

Same monkeypatch-module-level-function convention as tests/test_channel_
patterns.py / tests/test_autopilot_dial_route.py — no real DB, no sys.modules
stubbing needed (autopilot_launch.py, routes/autopilot.py, and
autopilot_proposals.py are all import-safe with no live DB at import time).

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/test_c51_candidate_auto_launch.py -q
"""
import asyncio
import os

import pytest

import autopilot_launch
import autopilot_proposals
import routes.autopilot as autopilot_route
from autopilot_dial import AutopilotDial
from routes.autopilot import CompetitorCandidate, ConfidenceBreakdown

TENANT = "tenant-c51"


def _candidate(id_="cand-1", confidence=75.0, modeled=False):
    return CompetitorCandidate(
        id=id_, title=f"Title for {id_}", source="SomeChannel", confidence=confidence,
        confidence_breakdown=ConfidenceBreakdown(total_score=confidence), modeled=modeled,
    )


def _patch_dial(monkeypatch, dial):
    async def fake(tenant_id):
        return dial
    monkeypatch.setattr(autopilot_launch, "get_autopilot_dial", fake)


def _patch_fetch_one(monkeypatch, *, enabled=True, interval_days=2, thresholds=None,
                      last_action_t=None, due=True, in_flight=False):
    """Dispatches autopilot_launch.fetch_one calls by recognizable query
    substrings, mirroring the config/due/in-flight queries the module
    actually issues."""
    thresholds = thresholds if thresholds is not None else {}
    calls = []

    async def fake_fetch_one(query, *args):
        calls.append((query, args))
        if "FROM autopilot_config" in query:
            return {"enabled": enabled, "production_interval_days": interval_days, "thresholds": thresholds}
        if "GREATEST(" in query:
            return {"t": last_action_t}
        if "make_interval" in query:
            return {"due": due}
        if "FROM videos" in query and "NOT IN" in query:
            return {"x": 1} if in_flight else None
        return None

    monkeypatch.setattr(autopilot_launch, "fetch_one", fake_fetch_one)
    return calls


def _patch_get_candidates(monkeypatch, candidates):
    async def fake_get_candidates(*, limit, min_vph, include_modeled, tenant_id):
        return candidates
    monkeypatch.setattr(autopilot_route, "get_candidates", fake_get_candidates)


def _patch_no_active_proposals(monkeypatch):
    async def fake(tenant_id, candidate_id):
        return False
    monkeypatch.setattr(autopilot_proposals, "has_active_proposal", fake)


def _patch_budget(monkeypatch, *, ok=True, spent=0.0, cap=None):
    """checklist C54 (P4.2-e) added a pre-launch budget re-check on the
    auto_draft/full_auto branch — every test that reaches that branch must
    patch this or it falls through to a real (missing) DB connection."""
    calls = []

    async def fake_check_weekly_budget(tenant_id):
        calls.append(tenant_id)
        return ok, spent, cap

    monkeypatch.setattr(autopilot_launch, "check_weekly_budget", fake_check_weekly_budget)
    return calls


def _patch_trip_kill_switch(monkeypatch):
    calls = []

    async def fake_trip(tenant_id, reason):
        calls.append((tenant_id, reason))
        return True

    monkeypatch.setattr(autopilot_launch, "trip_kill_switch", fake_trip)
    return calls


def _patch_create_proposal(monkeypatch):
    created = []

    async def fake(tenant_id, *, candidate_id, video_title, confidence_score, confidence_breakdown=None):
        row = {"id": f"proposal-{len(created) + 1}", "tenant_id": tenant_id,
               "candidate_id": candidate_id, "video_title": video_title,
               "confidence_score": confidence_score, "confidence_breakdown": confidence_breakdown,
               "status": "proposed", "decided_at": None, "decided_by": None,
               "video_id": None, "created_at": None}
        created.append(row)
        return row

    monkeypatch.setattr(autopilot_proposals, "create_proposal", fake)
    return created


# ---------------------------------------------------------------------------
# Invariant 1: kill switch tripped -> tenant skipped outright, no scoring.
# ---------------------------------------------------------------------------

def test_kill_switch_tripped_skips_before_any_scoring(monkeypatch):
    import datetime as dt
    _patch_dial(monkeypatch, AutopilotDial(dial_level="propose_only",
                                            kill_switch_tripped_at=dt.datetime.now(dt.timezone.utc)))

    scored = {"called": False}

    async def fake_fetch_one(query, *args):
        scored["called"] = True
        return None
    monkeypatch.setattr(autopilot_launch, "fetch_one", fake_fetch_one)

    result = asyncio.run(autopilot_launch.auto_launch_best_candidate(TENANT))
    assert result is None
    # Not even the autopilot_config row is read once the kill switch is tripped.
    assert scored["called"] is False


# ---------------------------------------------------------------------------
# Invariant: disabled tenant -> skipped.
# ---------------------------------------------------------------------------

def test_disabled_tenant_is_skipped(monkeypatch):
    _patch_dial(monkeypatch, AutopilotDial(dial_level="propose_only"))
    _patch_fetch_one(monkeypatch, enabled=False)
    _patch_get_candidates(monkeypatch, [_candidate()])

    result = asyncio.run(autopilot_launch.auto_launch_best_candidate(TENANT))
    assert result is None


# ---------------------------------------------------------------------------
# Invariant 7: cadence — not due yet blocks the whole cycle.
# ---------------------------------------------------------------------------

def test_not_due_yet_blocks_the_cycle(monkeypatch):
    _patch_dial(monkeypatch, AutopilotDial(dial_level="propose_only"))
    _patch_fetch_one(monkeypatch, due=False, last_action_t="2026-07-19T00:00:00")
    _patch_get_candidates(monkeypatch, [_candidate(confidence=99.0)])
    _patch_no_active_proposals(monkeypatch)
    created = _patch_create_proposal(monkeypatch)

    result = asyncio.run(autopilot_launch.auto_launch_best_candidate(TENANT))
    assert result is None
    assert created == []


# ---------------------------------------------------------------------------
# Invariant 8: something already in flight blocks the cycle.
# ---------------------------------------------------------------------------

def test_in_flight_video_blocks_the_cycle(monkeypatch):
    _patch_dial(monkeypatch, AutopilotDial(dial_level="propose_only"))
    _patch_fetch_one(monkeypatch, in_flight=True)
    _patch_get_candidates(monkeypatch, [_candidate(confidence=99.0)])
    _patch_no_active_proposals(monkeypatch)
    created = _patch_create_proposal(monkeypatch)

    result = asyncio.run(autopilot_launch.auto_launch_best_candidate(TENANT))
    assert result is None
    assert created == []


# ---------------------------------------------------------------------------
# Invariant 5: below-threshold candidate -> no proposal.
# ---------------------------------------------------------------------------

def test_below_confidence_threshold_produces_no_proposal(monkeypatch):
    _patch_dial(monkeypatch, AutopilotDial(dial_level="propose_only"))
    _patch_fetch_one(monkeypatch, thresholds={"min_confidence_score": 60})
    _patch_get_candidates(monkeypatch, [_candidate(confidence=40.0)])
    _patch_no_active_proposals(monkeypatch)
    created = _patch_create_proposal(monkeypatch)

    result = asyncio.run(autopilot_launch.auto_launch_best_candidate(TENANT))
    assert result is None
    assert created == []


# ---------------------------------------------------------------------------
# Invariant 2/3: propose_only records a proposal and NEVER calls launch_candidate.
# ---------------------------------------------------------------------------

def test_propose_only_records_proposal_and_never_launches(monkeypatch):
    _patch_dial(monkeypatch, AutopilotDial(dial_level="propose_only"))
    _patch_fetch_one(monkeypatch, thresholds={"min_confidence_score": 60})
    _patch_get_candidates(monkeypatch, [_candidate(id_="cand-9", confidence=80.0)])
    _patch_no_active_proposals(monkeypatch)
    created = _patch_create_proposal(monkeypatch)

    launch_calls = []

    async def fake_launch_candidate(candidate_id, background_tasks, tenant_id):
        launch_calls.append((candidate_id, tenant_id))
        raise AssertionError("launch_candidate must NEVER be called in propose_only mode")

    monkeypatch.setattr(autopilot_route, "launch_candidate", fake_launch_candidate)

    result = asyncio.run(autopilot_launch.auto_launch_best_candidate(TENANT))

    assert result["status"] == "proposed"
    assert result["candidate_id"] == "cand-9"
    assert len(created) == 1
    assert created[0]["candidate_id"] == "cand-9"
    assert launch_calls == []  # structurally never reached


# ---------------------------------------------------------------------------
# Invariant 4: auto_draft calls the EXISTING launch_candidate path once.
# ---------------------------------------------------------------------------

def test_auto_draft_calls_existing_launch_candidate_once(monkeypatch):
    _patch_dial(monkeypatch, AutopilotDial(dial_level="auto_draft"))
    _patch_fetch_one(monkeypatch, thresholds={"min_confidence_score": 60})
    _patch_get_candidates(monkeypatch, [_candidate(id_="cand-7", confidence=80.0)])
    _patch_no_active_proposals(monkeypatch)
    _patch_budget(monkeypatch, ok=True)
    created = _patch_create_proposal(monkeypatch)

    launch_calls = []

    async def fake_launch_candidate(candidate_id, background_tasks, tenant_id):
        launch_calls.append((candidate_id, tenant_id))
        return {"status": "launched", "candidate_id": candidate_id, "video_id": "v-1",
                "video_title": "x", "message": "ok"}

    monkeypatch.setattr(autopilot_route, "launch_candidate", fake_launch_candidate)

    result = asyncio.run(autopilot_launch.auto_launch_best_candidate(TENANT))

    assert result["status"] == "launched"
    assert launch_calls == [("cand-7", TENANT)]
    assert created == []  # auto_draft never writes a proposal row


def test_full_auto_is_treated_as_auto_draft_this_chunk(monkeypatch):
    _patch_dial(monkeypatch, AutopilotDial(dial_level="full_auto"))
    _patch_fetch_one(monkeypatch, thresholds={"min_confidence_score": 60})
    _patch_get_candidates(monkeypatch, [_candidate(id_="cand-5", confidence=80.0)])
    _patch_no_active_proposals(monkeypatch)
    _patch_budget(monkeypatch, ok=True)

    launch_calls = []

    async def fake_launch_candidate(candidate_id, background_tasks, tenant_id):
        launch_calls.append(candidate_id)
        return {"status": "launched", "candidate_id": candidate_id, "video_id": "v-1",
                "video_title": "x", "message": "ok"}

    monkeypatch.setattr(autopilot_route, "launch_candidate", fake_launch_candidate)

    result = asyncio.run(autopilot_launch.auto_launch_best_candidate(TENANT))
    assert result["status"] == "launched"
    assert launch_calls == ["cand-5"]


# ---------------------------------------------------------------------------
# C54 (P4.2-e): auto_draft's own pre-launch budget re-check — a breach trips
# the kill switch and returns None WITHOUT ever calling launch_candidate.
# ---------------------------------------------------------------------------

def test_auto_draft_budget_breach_trips_kill_switch_and_skips_launch(monkeypatch):
    _patch_dial(monkeypatch, AutopilotDial(dial_level="auto_draft"))
    _patch_fetch_one(monkeypatch, thresholds={"min_confidence_score": 60})
    _patch_get_candidates(monkeypatch, [_candidate(id_="cand-8", confidence=80.0)])
    _patch_no_active_proposals(monkeypatch)
    _patch_budget(monkeypatch, ok=False, spent=50.0, cap=40.0)
    trip_calls = _patch_trip_kill_switch(monkeypatch)

    launch_calls = []

    async def fake_launch_candidate(candidate_id, background_tasks, tenant_id):
        launch_calls.append(candidate_id)
        raise AssertionError("launch_candidate must NEVER be called on a budget breach")

    monkeypatch.setattr(autopilot_route, "launch_candidate", fake_launch_candidate)

    result = asyncio.run(autopilot_launch.auto_launch_best_candidate(TENANT))

    assert result is None
    assert launch_calls == []
    assert len(trip_calls) == 1
    assert trip_calls[0][0] == TENANT
    assert "40.00" in trip_calls[0][1] and "50.00" in trip_calls[0][1]


def test_propose_only_never_reaches_the_budget_check(monkeypatch):
    """propose_only must be structurally free — the budget check function is
    never even called on this branch (it's imported/called only inside the
    auto_draft branch code path, after the propose_only branch's early
    return)."""
    _patch_dial(monkeypatch, AutopilotDial(dial_level="propose_only"))
    _patch_fetch_one(monkeypatch, thresholds={"min_confidence_score": 60})
    _patch_get_candidates(monkeypatch, [_candidate(id_="cand-9", confidence=80.0)])
    _patch_no_active_proposals(monkeypatch)
    created = _patch_create_proposal(monkeypatch)

    async def fake_check_weekly_budget(tenant_id):
        raise AssertionError("check_weekly_budget must NEVER be called in propose_only mode")

    monkeypatch.setattr(autopilot_launch, "check_weekly_budget", fake_check_weekly_budget)

    result = asyncio.run(autopilot_launch.auto_launch_best_candidate(TENANT))
    assert result["status"] == "proposed"
    assert len(created) == 1


# ---------------------------------------------------------------------------
# Invariant 6: dedup — a candidate with an active proposal is skipped in
# favor of the next qualifying one.
# ---------------------------------------------------------------------------

def test_dedup_skips_candidate_with_active_proposal_picks_next(monkeypatch):
    _patch_dial(monkeypatch, AutopilotDial(dial_level="propose_only"))
    _patch_fetch_one(monkeypatch, thresholds={"min_confidence_score": 60})
    _patch_get_candidates(monkeypatch, [
        _candidate(id_="cand-top", confidence=90.0),
        _candidate(id_="cand-second", confidence=70.0),
    ])

    async def fake_has_active(tenant_id, candidate_id):
        return candidate_id == "cand-top"

    monkeypatch.setattr(autopilot_proposals, "has_active_proposal", fake_has_active)
    created = _patch_create_proposal(monkeypatch)

    result = asyncio.run(autopilot_launch.auto_launch_best_candidate(TENANT))
    assert result["candidate_id"] == "cand-second"
    assert len(created) == 1
    assert created[0]["candidate_id"] == "cand-second"


def test_dedup_all_candidates_have_active_proposals_yields_none(monkeypatch):
    _patch_dial(monkeypatch, AutopilotDial(dial_level="propose_only"))
    _patch_fetch_one(monkeypatch, thresholds={"min_confidence_score": 60})
    _patch_get_candidates(monkeypatch, [_candidate(id_="cand-only", confidence=90.0)])

    async def fake_has_active(tenant_id, candidate_id):
        return True

    monkeypatch.setattr(autopilot_proposals, "has_active_proposal", fake_has_active)
    created = _patch_create_proposal(monkeypatch)

    result = asyncio.run(autopilot_launch.auto_launch_best_candidate(TENANT))
    assert result is None
    assert created == []


# ---------------------------------------------------------------------------
# autopilot_proposals CRUD (small module, direct coverage)
# ---------------------------------------------------------------------------

def test_create_proposal_inserts_and_decodes_breakdown(monkeypatch):
    captured = {}

    async def fake_fetch_one(query, *args):
        captured["query"] = query
        captured["args"] = args
        return {"id": "p1", "tenant_id": args[0], "candidate_id": args[1],
                "video_title": args[2], "confidence_score": args[3],
                "confidence_breakdown": args[4], "status": "proposed",
                "decided_at": None, "decided_by": None, "video_id": None, "created_at": None}

    monkeypatch.setattr(autopilot_proposals, "fetch_one", fake_fetch_one)
    row = asyncio.run(autopilot_proposals.create_proposal(
        "t1", candidate_id="c1", video_title="Title", confidence_score=80.0,
        confidence_breakdown={"total_score": 80.0},
    ))
    assert row["status"] == "proposed"
    assert "::jsonb" in captured["query"]
    # confidence_breakdown was JSON-serialized before binding
    assert captured["args"][4] == '{"total_score": 80.0}'


def test_has_active_proposal_true_when_row_found(monkeypatch):
    async def fake_fetch_one(query, *args):
        assert "status = 'proposed'" in query
        return {"x": 1}

    monkeypatch.setattr(autopilot_proposals, "fetch_one", fake_fetch_one)
    assert asyncio.run(autopilot_proposals.has_active_proposal("t1", "c1")) is True


def test_has_active_proposal_false_when_no_row(monkeypatch):
    async def fake_fetch_one(query, *args):
        return None

    monkeypatch.setattr(autopilot_proposals, "fetch_one", fake_fetch_one)
    assert asyncio.run(autopilot_proposals.has_active_proposal("t1", "c1")) is False


# ---------------------------------------------------------------------------
# main.py wiring — the fallback call exists in source (source-presence check
# rather than a full app import, to keep this test light; the function-level
# behavior above is exercised directly). checklist C54 (P4.2-e) extracted the
# per-tenant tick into `_produce_for_tenant` so the kill-switch/budget gate
# covers BOTH the queue-drain and candidate-fallback paths — the fallback
# call itself now lives there, not inline in `_auto_produce_queue`.
# ---------------------------------------------------------------------------

def _main_py_source() -> str:
    main_path = os.path.join(os.path.dirname(__file__), "..", "main.py")
    with open(main_path) as f:
        return f.read()


def test_main_py_wires_the_candidate_fallback_into_produce_for_tenant():
    source = _main_py_source()
    start = source.index("async def _produce_for_tenant")
    end = source.index("\nasync def _auto_produce_queue", start + 10)
    body = source[start:end]
    assert "from autopilot_launch import auto_launch_best_candidate" in body
    assert "auto_launch_best_candidate(tenant_id)" in body
    # C54: the same per-tenant tick also gates on the kill switch/budget
    # BEFORE either the queue drain or the candidate fallback runs.
    assert "get_autopilot_dial" in body
    assert "check_weekly_budget" in body
    assert "trip_kill_switch" in body
    assert "from routes.queue import auto_produce_next" in body


def test_main_py_auto_produce_queue_loop_calls_the_extracted_helper():
    source = _main_py_source()
    start = source.index("async def _auto_produce_queue")
    end = source.index("\nasync def ", start + 10)
    body = source[start:end]
    assert "_produce_for_tenant(tenant_id)" in body
