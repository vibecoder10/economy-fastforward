"""Offline contract coverage for source-grounded research claim assessments."""

import json

import pytest

from factual_machine_summary import generate_factual_machine_summary
from research_claim_assessment import (
    assessment_fingerprint,
    assess_verified_package,
    current_assessment,
)


MACHINE = "USS Plunger (SS-2)"
CONTEXT = "Early United States submarines"
URL = "https://history.example/plunger"
QUOTE = "USS Plunger (SS-2) was commissioned in 1903."


class ScriptedClient:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _package():
    return {
        "machine": MACHINE,
        "sources": [{"source_id": "S1", "url": URL}],
        "candidate_excerpts": [{
            "excerpt_id": "S1-E1", "source_id": "S1", "source_title": "Naval history",
            "source_url": URL, "locator": "S1-E1", "source_capture_method": "fetched_page",
            "text": QUOTE,
        }],
    }


def _claims(extra=None):
    claims = [{"claim": "Plunger was commissioned in 1903.", "scope": "commissioning", "status": "supported",
               "reason": "The excerpt explicitly gives the commissioning date.",
               "evidence": [{"excerpt_id": "S1-E1", "quote": QUOTE}], "counterevidence": []}]
    if extra:
        claims.append(extra)
    return {"claims": claims}


@pytest.mark.asyncio
async def test_assessment_enriches_exact_quotes_and_reuses_current_receipt_without_provider_call():
    package = _package()
    client = ScriptedClient("```json\n" + json.dumps(_claims()) + "\n```")

    receipt = await assess_verified_package(MACHINE, package, client, CONTEXT)
    package["claim_assessment"] = receipt
    reused = await assess_verified_package(MACHINE, package, client, CONTEXT)

    assert receipt["status"] == "assessed"
    assert receipt["probability"] is None
    assert receipt["claims"][0]["evidence"][0]["source_url"] == URL
    assert reused == receipt
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_assessment_keeps_partial_scope_evidence_but_rejects_unknown_or_nonverbatim_quotes():
    package = _package()
    partial = {"claim": "Plunger had a later refit.", "scope": "later refit", "status": "insufficient",
               "reason": "The available commissioning excerpt does not establish a refit.",
               "evidence": [{"excerpt_id": "S1-E1", "quote": QUOTE}], "counterevidence": []}
    receipt = await assess_verified_package(MACHINE, package, ScriptedClient(json.dumps(_claims(partial))), CONTEXT)
    assert receipt["status"] == "assessed"
    assert receipt["claims"][1]["evidence"]

    invalid = _claims()
    invalid["claims"][0]["evidence"][0]["quote"] = "not in the excerpt"
    failed = await assess_verified_package(MACHINE, _package(), ScriptedClient(json.dumps(invalid)), CONTEXT)
    assert failed["status"] == "needs_review"
    assert failed["warnings"]
    assert failed["raw_response"] == json.dumps(invalid)
    assert failed["raw_response_truncated"] is False
    assert failed["source_fingerprint"] == assessment_fingerprint(MACHINE, _package(), CONTEXT)
    assert current_assessment(MACHINE, {**_package(), "claim_assessment": failed}, CONTEXT) is None

    oversized = "x" * 60001
    truncated = await assess_verified_package(MACHINE, _package(), ScriptedClient(oversized), CONTEXT)
    assert truncated["raw_response"] == oversized[:60000]
    assert truncated["raw_response_truncated"] is True


@pytest.mark.asyncio
async def test_assessment_receipt_detects_tampering_and_package_mutation():
    package = _package()
    receipt = await assess_verified_package(MACHINE, package, ScriptedClient(json.dumps(_claims())), CONTEXT)
    package["claim_assessment"] = receipt
    assert current_assessment(MACHINE, package, CONTEXT)

    package["claim_assessment"]["claims"][0]["evidence"][0]["source_url"] = "https://tampered.example"
    assert current_assessment(MACHINE, package, CONTEXT) is None

    package["claim_assessment"] = receipt
    package["claim_assessment"]["claims"][0]["claim"] = "Plunger was commissioned in 1904."
    assert current_assessment(MACHINE, package, CONTEXT) is None

    package["claim_assessment"] = receipt = await assess_verified_package(
        MACHINE, _package(), ScriptedClient(json.dumps(_claims())), CONTEXT)
    package["candidate_excerpts"][0]["text"] = "USS Plunger (SS-2) was commissioned in 1904."
    assert current_assessment(MACHINE, package, CONTEXT) is None


@pytest.mark.asyncio
async def test_research_writer_requires_current_supported_assessment_and_passes_constraints():
    package = _package()
    assessment = await assess_verified_package(MACHINE, package, ScriptedClient(json.dumps(_claims())), CONTEXT)
    package["claim_assessment"] = assessment
    sentence = "USS Plunger (SS-2) was commissioned in 1903."
    draft = json.dumps({"paragraph": sentence, "claim_map": [{"sentence": sentence, "citations": [{"excerpt_id": "S1-E1"}]}]})
    client = ScriptedClient(draft, json.dumps({"passed": True, "issues": []}))
    result = await generate_factual_machine_summary(MACHINE, package, client, subject_context=CONTEXT, purpose="research")

    assert result["passed"] is True
    assert "CLAIM ASSESSMENT" in client.calls[0]["prompt"]
    assert "claim_assessment_constraints_not_evidence" in client.calls[1]["prompt"]

    held = await generate_factual_machine_summary(MACHINE, _package(), client, subject_context=CONTEXT, purpose="research")
    assert held["passed"] is False
    assert "claim assessment" in held["warnings"][0].lower()


def test_assessment_fingerprint_excludes_only_the_saved_receipt():
    package = _package()
    before = assessment_fingerprint(MACHINE, package, CONTEXT)
    package["claim_assessment"] = {"status": "assessed"}
    assert assessment_fingerprint(MACHINE, package, CONTEXT) == before
