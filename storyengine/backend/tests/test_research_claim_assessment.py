"""Offline contract coverage for source-grounded research claim assessments."""

import json
import copy
from pathlib import Path

import pytest

from factual_machine_summary import generate_factual_machine_summary
from research_claim_assessment import (
    _assessed_receipt,
    _partition_claim_response,
    _replay_failed_assessment,
    _validated_claims,
    _quote_rows,
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


def _holland_package():
    machine = "SS-1 USS Holland"
    text = "Navy’s first submarine, USS Holland (SS 1)."
    return machine, {
        "machine": machine,
        "sources": [{"source_id": "S1", "url": "https://museum.example/holland"}],
        "candidate_excerpts": [{"excerpt_id": "S1-E1", "source_id": "S1", "source_title": "Museum record",
            "source_url": "https://museum.example/holland", "locator": "S1-E1",
            "source_capture_method": "fetched_page", "text": text}],
    }


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
async def test_saved_holland_raw_response_replays_curly_apostrophe_quote_without_provider():
    machine, package = _holland_package()
    context = "Every US Submarine Class Ever Built (2026)"
    raw = json.dumps({"claims": [{"claim": "USS Holland was the Navy's first submarine.", "scope": "machine",
        "status": "supported", "reason": "The excerpt identifies it.",
        "evidence": [{"excerpt_id": "S1-E1", "quote": "Navy's first submarine, USS Holland (SS 1)"}],
        "counterevidence": []}]})
    package["claim_assessment"] = {"version": 1, "status": "needs_review", "machine": machine,
        "subject_context": context, "source_fingerprint": assessment_fingerprint(machine, package, context),
        "raw_response": raw, "raw_response_truncated": False}
    client = ScriptedClient()

    replayed = await assess_verified_package(machine, package, client, context)

    assert replayed["status"] == "assessed"
    assert replayed["claims"][0]["evidence"][0]["quote"] == "Navy’s first submarine, USS Holland (SS 1)"
    assert client.calls == []

    package["candidate_excerpts"][0]["text"] = "Navy’s second submarine, USS Holland (SS 1)."
    stale = await assess_verified_package(machine, package, None, context)
    assert stale["status"] == "needs_review"
    assert "client" in stale["warnings"][0].lower()


def test_typography_recovery_preserves_source_slice_and_rejects_substantive_or_ambiguous_matches():
    source = "Navy’s first submarine; Navy’s first submarine."
    candidates = {"S1-E1": {"text": source, "source_url": URL, "source_title": "Source", "locator": "S1-E1"}}
    assert _quote_rows([{"excerpt_id": "S1-E1", "quote": "Navy's first submarine;"}], candidates)[0]["quote"] == "Navy’s first submarine;"
    assert _quote_rows([{"excerpt_id": "S1-E1", "quote": "Navy's second submarine;"}], candidates) is None
    assert _quote_rows([{"excerpt_id": "S1-E1", "quote": "Navy's first submarine"}], candidates) is None


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


@pytest.mark.asyncio
async def test_saved_ss105_response_replays_eight_valid_claims_without_provider():
    snapshot = Path(__file__).parent / "fixtures/ss105-failed-assessment-response.json"
    package = json.loads(snapshot.read_text())
    machine = package["machine"]
    context = package["claim_assessment"]["subject_context"]
    package["claim_assessment"]["source_fingerprint"] = assessment_fingerprint(machine, package, context)
    original = copy.deepcopy(package)
    client = ScriptedClient()

    replayed = await assess_verified_package(machine, package, client, context)

    assert replayed["status"] == "assessed"
    assert replayed["diagnostics"]["accepted_claim_count"] == 8
    assert len(replayed["claims"]) == 8
    assert all("modified in 1922" not in claim["claim"] for claim in replayed["claims"])
    assert replayed["diagnostics"]["rejected_claims"] == [{"index": 2, "reason": "quote_mismatch"}]
    assert current_assessment(machine, package, context) == replayed
    assert current_assessment(machine, package, context) == replayed
    assert package == original
    assert client.calls == []


@pytest.mark.asyncio
async def test_partition_rejects_whole_malformed_response_and_never_retries_exact_saved_failure():
    package = _package()
    malformed = {"claims": _claims()["claims"] * 13}
    package["claim_assessment"] = {"version": 1, "status": "needs_review", "machine": MACHINE,
        "subject_context": CONTEXT, "source_fingerprint": assessment_fingerprint(MACHINE, package, CONTEXT),
        "raw_response": json.dumps(malformed), "raw_response_truncated": False}
    client = ScriptedClient(json.dumps(_claims()))

    assert _replay_failed_assessment(MACHINE, package, CONTEXT) is None
    assert current_assessment(MACHINE, package, CONTEXT) is None
    assert await assess_verified_package(MACHINE, package, client, CONTEXT) == package["claim_assessment"]
    assert client.calls == []


def test_partition_drops_bad_identity_and_counterevidence_rows_without_relaxing_validator():
    package = _package()
    candidates = {row["excerpt_id"]: row for row in package["candidate_excerpts"]}
    bad_identity = _claims()["claims"][0] | {"identity_reviews": [{"excerpt_id": "S1-E1", "status": "same_machine",
        "anchor_excerpt_id": "S1-E1", "reason": "not applicable"}]}
    bad_counter = _claims()["claims"][0] | {"status": "disputed", "counterevidence": [{"excerpt_id": "S1-E1", "quote": QUOTE}]}
    accepted, diagnostics = _partition_claim_response({"claims": [bad_identity, bad_counter]}, candidates)

    assert accepted == []
    assert [row["reason"] for row in diagnostics["rejected_claims"]] == ["claim_contract", "claim_contract"]


def test_prior_supported_claim_is_retained_only_with_current_exact_evidence_and_integrity():
    package = _package()
    candidates = {row["excerpt_id"]: row for row in package["candidate_excerpts"]}
    prior_claims = _validated_claims(_claims()["claims"], candidates)
    prior = _assessed_receipt(MACHINE, package, CONTEXT, prior_claims)
    invalid = _claims()["claims"][0] | {"evidence": [{"excerpt_id": "S1-E1", "quote": "altered quote"}]}
    package["prior_claim_assessments"] = [prior]
    package["claim_assessment"] = {"version": 1, "status": "needs_review", "machine": MACHINE,
        "subject_context": CONTEXT, "source_fingerprint": assessment_fingerprint(MACHINE, package, CONTEXT),
        "raw_response": json.dumps({"claims": [invalid]}), "raw_response_truncated": False}

    recovered = _replay_failed_assessment(MACHINE, package, CONTEXT)
    assert recovered and recovered["claims"] == prior_claims

    prior["claims_fingerprint"] = "tampered"
    package["claim_assessment"]["source_fingerprint"] = assessment_fingerprint(MACHINE, package, CONTEXT)
    assert _replay_failed_assessment(MACHINE, package, CONTEXT) is None

    package["candidate_excerpts"][0]["text"] = "USS Plunger (SS-2) was commissioned in 1904."
    assert _replay_failed_assessment(MACHINE, package, CONTEXT) is None


@pytest.mark.asyncio
async def test_fresh_partition_retains_latest_intact_prior_supported_claims_after_new_rows():
    package = _package()
    candidates = {row["excerpt_id"]: row for row in package["candidate_excerpts"]}
    prior_claims = _validated_claims(_claims()["claims"], candidates)
    package["prior_claim_assessments"] = [_assessed_receipt(MACHINE, package, CONTEXT, prior_claims)]
    fresh = _claims()["claims"][0] | {"claim": "Plunger's record gives a 1903 commissioning."}

    receipt = await assess_verified_package(MACHINE, package, ScriptedClient(json.dumps({"claims": [fresh]})), CONTEXT)

    assert [claim["claim"] for claim in receipt["claims"]] == [fresh["claim"], prior_claims[0]["claim"]]


@pytest.mark.asyncio
async def test_malformed_fresh_response_cannot_promote_valid_prior_claims():
    package = _package()
    candidates = {row["excerpt_id"]: row for row in package["candidate_excerpts"]}
    prior_claims = _validated_claims(_claims()["claims"], candidates)
    package["prior_claim_assessments"] = [_assessed_receipt(MACHINE, package, CONTEXT, prior_claims)]
    client = ScriptedClient(json.dumps({"claims": _claims()["claims"] * 13}))

    receipt = await assess_verified_package(MACHINE, package, client, CONTEXT)

    assert receipt["status"] == "needs_review"
    assert receipt["claims"] == []
    assert client.calls


@pytest.mark.parametrize("case", ["wrong_machine", "wrong_context", "truncated", "stale_source"])
def test_exact_failed_replay_rejects_wrong_binding_or_stale_capture(case):
    fixture = Path(__file__).parent / "fixtures/ss105-failed-assessment-response.json"
    package = json.loads(fixture.read_text())
    machine, context = package["machine"], package["claim_assessment"]["subject_context"]
    package["claim_assessment"]["source_fingerprint"] = assessment_fingerprint(machine, package, context)
    if case == "wrong_machine":
        machine = "SS-999 USS Other"
    elif case == "wrong_context":
        context = "Different documentary"
    elif case == "truncated":
        package["claim_assessment"]["raw_response_truncated"] = True
    else:
        package["candidate_excerpts"][0]["text"] += " changed"

    assert _replay_failed_assessment(machine, package, context) is None
