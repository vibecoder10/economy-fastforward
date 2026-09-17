"""Offline migration contracts for narrative-role DVSU assessments."""

import copy
import json

import pytest

from research_claim_assessment import (
    NARRATIVE_CONTRACT_VERSION,
    _assessed_receipt,
    _eligible,
    _validated_claims,
    assess_verified_package,
)


MACHINE = "USS Plunger (SS-2)"
CONTEXT = "Early United States submarines"
QUOTE = "USS Plunger (SS-2) was commissioned in 1903."


class Client:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _package():
    return {"machine": MACHINE, "sources": [{"source_id": "S1", "url": "https://example.test/plunger"}],
            "candidate_excerpts": [{"excerpt_id": "S1-E1", "source_id": "S1", "source_title": "History",
                "source_url": "https://example.test/plunger", "locator": "S1-E1",
                "source_capture_method": "fetched_page", "text": QUOTE}]}


def _claim(*, roles=None, quote=QUOTE):
    claim = {"claim": "Plunger was commissioned in 1903.", "scope": "commissioning", "status": "supported",
             "reason": "The excerpt explicitly gives the date.",
             "evidence": [{"excerpt_id": "S1-E1", "quote": quote}], "counterevidence": []}
    if roles is not None:
        claim["narrative_roles"] = roles
    return claim


def _current_receipt(package, claim):
    claims = _validated_claims([claim], _eligible(MACHINE, package, CONTEXT))
    assert claims is not None
    return _assessed_receipt(MACHINE, package, CONTEXT, claims)


@pytest.mark.asyncio
async def test_narrative_mode_reassesses_legacy_once_and_preserves_prior_receipt():
    package = _package()
    legacy = _current_receipt(package, _claim())
    package["claim_assessment"] = legacy
    client = Client(json.dumps({"claims": [_claim(roles=[])]}))

    migrated = await assess_verified_package(MACHINE, package, client, CONTEXT, require_narrative_roles=True)
    package["claim_assessment"] = migrated
    reused = await assess_verified_package(MACHINE, package, client, CONTEXT, require_narrative_roles=True)

    assert migrated["narrative_contract_version"] == 1
    assert migrated["previous_assessment"] == legacy
    assert migrated["claims"][0]["narrative_roles"] == []
    assert reused == migrated
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_narrative_failed_attempt_is_reused_but_changed_evidence_retries():
    package = _package()
    bad = json.dumps({"claims": [_claim(roles=[], quote="not in immutable excerpt")]})
    client = Client(bad)
    failed = await assess_verified_package(MACHINE, package, client, CONTEXT, require_narrative_roles=True)
    package["claim_assessment"] = failed

    cached = await assess_verified_package(MACHINE, package, client, CONTEXT, require_narrative_roles=True)
    changed = copy.deepcopy(package)
    changed["candidate_excerpts"][0]["text"] = "USS Plunger (SS-2) was commissioned in 1904."
    changed_client = Client(json.dumps({"claims": [_claim(roles=[], quote=changed["candidate_excerpts"][0]["text"])]}))
    retried = await assess_verified_package(MACHINE, changed, changed_client, CONTEXT, require_narrative_roles=True)

    assert failed["status"] == "needs_review"
    assert failed["narrative_contract_version"] == 1
    assert cached == failed
    assert len(client.calls) == 1
    assert retried["status"] == "assessed"
    assert len(changed_client.calls) == 1


@pytest.mark.asyncio
async def test_narrative_mode_rejects_missing_roles_without_retrying_the_same_attempt():
    package = _package()
    client = Client(json.dumps({"claims": [_claim()]}))
    failed = await assess_verified_package(MACHINE, package, client, CONTEXT, require_narrative_roles=True)
    package["claim_assessment"] = failed
    cached = await assess_verified_package(MACHINE, package, client, CONTEXT, require_narrative_roles=True)

    assert failed["status"] == "needs_review"
    assert failed["narrative_contract_version"] == 1
    assert "narrative roles" in failed["warnings"][0].lower()
    assert cached == failed
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_matching_truncated_or_dict_narrative_failure_is_reused_without_provider_call():
    for response in ("x" * 60001, {"claims": [_claim(roles=[], quote="not in immutable excerpt")]}):
        package = _package()
        initial = Client(response)
        failed = await assess_verified_package(MACHINE, package, initial, CONTEXT, require_narrative_roles=True)
        package["claim_assessment"] = failed
        cached_client = Client()

        cached = await assess_verified_package(MACHINE, package, cached_client, CONTEXT, require_narrative_roles=True)

        assert failed["narrative_contract_version"] == NARRATIVE_CONTRACT_VERSION
        assert cached == failed
        assert len(initial.calls) == 1
        assert cached_client.calls == []


@pytest.mark.asyncio
async def test_matching_narrative_failure_replays_valid_explicit_roles_without_provider_call():
    package = _package()
    saved = {"version": 1, "status": "needs_review", "machine": MACHINE, "subject_context": CONTEXT,
             "source_fingerprint": _current_receipt(package, _claim())["source_fingerprint"],
             "raw_response": json.dumps({"claims": [_claim(roles=[])]}), "raw_response_truncated": False,
             "narrative_contract_version": NARRATIVE_CONTRACT_VERSION}
    package["claim_assessment"] = saved
    client = Client()

    replayed = await assess_verified_package(MACHINE, package, client, CONTEXT, require_narrative_roles=True)

    assert replayed["status"] == "assessed"
    assert replayed["claims"][0]["narrative_roles"] == []
    assert replayed["narrative_contract_version"] == NARRATIVE_CONTRACT_VERSION
    assert client.calls == []


@pytest.mark.asyncio
async def test_role_tagged_current_receipt_and_default_callers_do_not_spend():
    package = _package()
    holland_style = _current_receipt(package, _claim(roles=[]))
    package["claim_assessment"] = holland_style
    client = Client()

    narrative = await assess_verified_package(MACHINE, package, client, CONTEXT, require_narrative_roles=True)
    default = await assess_verified_package(MACHINE, package, client, CONTEXT)

    assert narrative == holland_style
    assert default == holland_style
    assert client.calls == []
