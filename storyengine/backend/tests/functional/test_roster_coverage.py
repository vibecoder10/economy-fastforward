import asyncio
import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "skills/video-pipeline"))
from roster_coverage import audit_roster_coverage, coverage_is_current


@pytest.fixture(autouse=True)
def no_external_fetch(monkeypatch):
    monkeypatch.setattr("roster_sources.fetch_scope_sources", AsyncMock(return_value=[]))


def _review(**overrides):
    value = {"passed": True, "scope": "British carrier designs including exports",
             "findings": [], "summary": "Complete against indexes",
             "sources": [{"url": "https://museum.example/carriers", "supports": "Class index"},
                         {"url": "https://navy.example/history", "supports": "Escort conversions"}]}
    return {**value, **overrides}


def _payload():
    return {"unit_roster": [{"name": "Argus"}], "roster_contract": "CONFIRMED"}


def test_current_review_reused_but_title_scope_and_roster_changes_reopen():
    client = SimpleNamespace(generate=AsyncMock(return_value=json.dumps(_review())))
    payload = _payload()
    assert asyncio.run(audit_roster_coverage(client, "Every British carrier", payload))["passed"]
    assert asyncio.run(audit_roster_coverage(client, "Every British carrier", payload))["passed"]
    client.generate.assert_awaited_once()
    assert not coverage_is_current("Every American carrier", payload)
    for key, value in [("unit_roster", [{"name": "Hermes"}]), ("roster_contract", "Fleet only")]:
        changed = copy.deepcopy(payload)
        changed[key] = value
        assert not coverage_is_current("Every British carrier", changed)


@pytest.mark.parametrize("review", [
    _review(passed="true"), _review(sources=[]), _review(findings=None),
    _review(findings=[{"candidate": "Activity", "problem": "Missing escort"}]),
    _review(sources=[{"url": "file:///etc/passwd", "supports": "invalid"}]),
    _review(sources=[{"url": "https://en.wikipedia.org/wiki/HMS_Argus", "supports": "lead"},
                     {"url": "https://naval-encyclopedia.com/carriers", "supports": "lead"}]),
])
def test_unverified_or_missing_candidates_cannot_be_claimed_complete(review):
    client = SimpleNamespace(generate=AsyncMock(return_value=json.dumps(review)))
    audit = asyncio.run(audit_roster_coverage(client, "Every British carrier", _payload()))
    assert not audit["passed"]
    assert audit["findings"]


def test_invalid_review_is_not_a_pass():
    client = SimpleNamespace(generate=AsyncMock(return_value="not json"))
    with pytest.raises(ValueError, match="invalid JSON"):
        asyncio.run(audit_roster_coverage(client, "Every British carrier", _payload()))


def test_gateway_without_search_does_not_claim_independent_verification():
    client = SimpleNamespace(_gateway_mode=True, generate=AsyncMock())
    with pytest.raises(ValueError, match="cannot execute web search"):
        asyncio.run(audit_roster_coverage(client, "Every British carrier", _payload()))
    client.generate.assert_not_awaited()


@pytest.mark.parametrize("conforms", [None, False, "true"])
def test_positive_review_cannot_accept_unconfirmed_locked_scope(conforms):
    client = SimpleNamespace(generate=AsyncMock(return_value=json.dumps(_review(scope_conforms=conforms))))
    audit = asyncio.run(audit_roster_coverage(client, "Every British Aircraft Carrier Class Ever Built", _payload()))
    assert not audit["passed"]


def test_locked_policy_reaches_review_and_invalidates_old_cached_pass():
    from roster_coverage import title_scope_policy
    title = "Every British Aircraft Carrier Class Ever Built (2026)"
    payload = _payload()
    payload["independent_coverage_audit"] = {"version": 2, "passed": True}
    client = SimpleNamespace(generate=AsyncMock(return_value=json.dumps(_review(scope_conforms=True))))
    audit = asyncio.run(audit_roster_coverage(client, title, payload))
    assert audit["passed"]
    policy = title_scope_policy(title)
    assert policy == payload["inclusion_policy"] == audit["scope_policy"]
    assert policy in client.generate.call_args.kwargs["prompt"]
    assert coverage_is_current(title, payload)


@pytest.mark.parametrize("title", ["Every Royal Navy Aircraft Carrier Ever Operated", "Every British Seaplane Carrier", "British Aircraft Carriers Never Built", "Every US Aircraft Carrier"])
def test_other_title_scopes_are_not_replaced_with_british_design_default(title):
    from roster_coverage import title_scope_policy
    assert title_scope_policy(title) == ""



def test_retrieved_evidence_reaches_reviewer_and_is_saved(monkeypatch):
    packet = [{"url": "https://archive.example/classes", "available": True, "excerpt": "Two ships; separate one-off class."}]
    monkeypatch.setattr("roster_sources.fetch_scope_sources", AsyncMock(return_value=packet))
    payload = _payload()
    client = SimpleNamespace(generate=AsyncMock(return_value=json.dumps(_review(scope_conforms=True))))
    asyncio.run(audit_roster_coverage(client, "Every British Aircraft Carrier Class Ever Built", payload))
    assert payload["coverage_source_packet"] == packet
    assert json.dumps(packet) in client.generate.call_args.kwargs["prompt"]


def test_bomber_review_uses_role_boundary_without_carrier_evidence(monkeypatch):
    from roster_coverage import title_scope_policy
    title = 'Every US Strategic Bomber Ever Built (2026)'
    payload = _payload()
    fetch = AsyncMock(return_value=[])
    monkeypatch.setattr('roster_sources.fetch_scope_sources', fetch)
    async def review(**kwargs):
        prompt = kwargs['prompt']
        assert 'not merely a strategic mission' in prompt
        assert 'Merely being a bomber' in prompt
        from orchestrator.pipeline_constants import Models
        assert kwargs['model'] == Models.CLAUDE_OPUS
        assert 'bomber-derived airframe' in prompt
        assert 'British carrier source leads' not in prompt
        return json.dumps(_review(scope='US strategic bombing aircraft', scope_conforms=True))
    client = SimpleNamespace(generate=AsyncMock(side_effect=review))
    audit = asyncio.run(audit_roster_coverage(client, title, payload))
    assert audit['passed']
    assert audit['scope_policy'] == title_scope_policy(title)
    fetch.assert_not_awaited()
