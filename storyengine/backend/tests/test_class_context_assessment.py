"""Contracts for the bounded class-context narrative-role follow-up."""

import asyncio
import json

from class_context_assessment import assess_class_context_gap
from research_claim_assessment import _assessed_receipt, _eligible, _validated_claims, assess_verified_package
from script_research_packet import assert_request_budget


MACHINE = "SS-2 USS Plunger"
CONTEXT = "Early United States submarines"
URL = "https://example.test/a-class"
ANCHOR = "USS Plunger (SS-2) was used in training before retirement."
CLASS_CONTEXT = "\n\n".join((
    '"A" submarines (1903)',
    "Ships No Name Yard No Builder SS2 Plunger, A1",
    "Technical data Machinery used gasoline engines and electric motors.",
    "Project history These submarines were intended for port defense.",
))


class Client:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _package(*, include_class=True, include_anchor=True, irrelevant=False):
    excerpts = []
    if include_class:
        excerpts.append({"excerpt_id": "S1-E1", "source_id": "S1", "source_title": "A class",
                         "source_url": URL, "locator": "S1-E1", "source_capture_method": "fetched_page",
                         "text": CLASS_CONTEXT})
    if include_anchor:
        excerpts.append({"excerpt_id": "S2-E1", "source_id": "S2", "source_title": "Plunger record",
                         "source_url": "https://example.test/plunger", "locator": "S2-E1",
                         "source_capture_method": "fetched_page", "text": ANCHOR})
    if irrelevant:
        excerpts.append({"excerpt_id": "S9-E9", "source_id": "S9", "source_title": "Archived",
                         "source_url": "https://example.test/archive", "locator": "S9-E9",
                         "source_capture_method": "fetched_page", "text": "IRRELEVANT_ARCHIVED_RAW_CONTEXT"})
    return {"machine": MACHINE,
            "sources": [{"source_id": item["source_id"], "url": item["source_url"]} for item in excerpts],
            "candidate_excerpts": excerpts}


def _claim(claim, roles, quote=ANCHOR, *, scope="machine"):
    return {"claim": claim, "scope": scope, "status": "supported", "reason": "The cited source states it.",
            "narrative_roles": roles, "evidence": [{"excerpt_id": "S2-E1", "quote": quote}],
            "counterevidence": []}


def _current(package, *, include_intended=False):
    claims = [
        _claim("USS Plunger (SS-2) used gasoline engines and electric motors.", ["design"]),
        _claim("USS Plunger (SS-2) was used in training.", ["actual_use"]),
        _claim("USS Plunger (SS-2) was retired.", ["outcome"]),
    ]
    if include_intended:
        claims.append(_claim("USS Plunger (SS-2) had an attributed purpose.", ["intended_role"]))
    normalized = _validated_claims(claims, _eligible(MACHINE, package, CONTEXT))
    assert normalized
    receipt = _assessed_receipt(MACHINE, package, CONTEXT, normalized)
    receipt.update({"narrative_contract_version": 1, "recovery": {"preserved": True}})
    return receipt


def _current_with_twelve_claims(package):
    claims = [
        _claim(f"USS Plunger (SS-2) design fact {index}.", ["design"])
        for index in range(12)
    ]
    normalized = _validated_claims(claims, _eligible(MACHINE, package, CONTEXT))
    assert normalized
    receipt = _assessed_receipt(MACHINE, package, CONTEXT, normalized)
    receipt["narrative_contract_version"] = 1
    return receipt


def _focused_claim(*, role="intended_role", quote="Project history These submarines were intended for port defense.",
                   review=True, claim_text="The A class was intended for port defense."):
    item = {"claim": claim_text, "scope": "class", "status": "supported",
            "reason": "The project history states the class purpose.", "narrative_roles": [role],
            "evidence": [{"excerpt_id": "S1-E1", "quote": quote}, {"excerpt_id": "S2-E1", "quote": ANCHOR}],
            "counterevidence": []}
    if review:
        item["identity_reviews"] = [{"excerpt_id": "S1-E1", "status": "same_machine",
            "anchor_excerpt_id": "S2-E1", "reason": "The same claim cites USS Plunger (SS-2)."}]
    return json.dumps({"claims": [item]})


def test_focused_class_assessment_adds_only_reviewed_missing_role_and_preserves_receipt_metadata():
    package = _package(irrelevant=True)
    package["claim_assessment"] = _current(package)
    client = Client(_focused_claim())

    result = asyncio.run(assess_verified_package(MACHINE, package, client, CONTEXT, require_narrative_roles=True))
    package["claim_assessment"] = result
    reused = asyncio.run(assess_verified_package(MACHINE, package, client, CONTEXT, require_narrative_roles=True))

    assert len(client.calls) == 1
    assert result["recovery"] == {"preserved": True}
    assert result["class_context_review"]["status"] == "completed"
    assert [claim["narrative_roles"] for claim in result["claims"]] == [["design"], ["actual_use"], ["outcome"], ["intended_role"]]
    assert reused == result
    prompt = client.calls[0]["prompt"]
    assert "FOCUSED CLASS-CONTEXT" in prompt
    assert "IRRELEVANT_ARCHIVED_RAW_CONTEXT" not in prompt
    assert_request_budget(prompt, client.calls[0]["system_prompt"], client.calls[0]["max_tokens"])
    assert client.calls[0]["max_tokens"] == 1800


def test_no_class_gap_or_anchor_never_calls_provider():
    no_class = _package(include_class=False)
    no_class["claim_assessment"] = _current(no_class)
    no_gap = _package()
    no_gap["claim_assessment"] = _current(no_gap, include_intended=True)
    for package in (no_class, no_gap):
        client = Client()
        assert asyncio.run(assess_verified_package(MACHINE, package, client, CONTEXT, require_narrative_roles=True)) == package["claim_assessment"]
        assert client.calls == []
    no_anchor = _package(include_anchor=False)
    client = Client()
    assert asyncio.run(assess_class_context_gap(
        MACHINE, no_anchor, _current(_package()), client, CONTEXT,
        _eligible(MACHINE, no_anchor, CONTEXT),
    )).get("class_context_review") is None
    assert client.calls == []


def test_invalid_or_nonclass_focused_output_preserves_old_claims_and_marks_fingerprint_once():
    for response in (
        _focused_claim(quote="not an exact quote"),
        _focused_claim(role="actual_use"),
        _focused_claim(review=False),
        _focused_claim(claim_text="The A class was a submarine class."),
    ):
        package = _package()
        original = _current(package)
        package["claim_assessment"] = original
        client = Client(response)
        result = asyncio.run(assess_verified_package(MACHINE, package, client, CONTEXT, require_narrative_roles=True))
        package["claim_assessment"] = result
        retry = asyncio.run(assess_verified_package(MACHINE, package, client, CONTEXT, require_narrative_roles=True))
        assert result["claims"] == original["claims"]
        assert result["class_context_review"]["status"] == "completed_failure"
        assert retry == result
        assert len(client.calls) == 1


def test_fresh_assessment_remains_the_normal_full_assessment_path():
    package = _package(include_class=False)
    raw = json.dumps({"claims": [_claim("USS Plunger (SS-2) was used in training.", ["actual_use"])]})
    client = Client(raw)
    result = asyncio.run(assess_verified_package(MACHINE, package, client, CONTEXT, require_narrative_roles=True))
    assert result["status"] == "assessed"
    assert len(client.calls) == 1
    assert client.calls[0]["max_tokens"] == 4500
    assert "FOCUSED CLASS-CONTEXT" not in client.calls[0]["prompt"]


def test_completed_class_review_can_preserve_twelve_old_claims_and_add_a_purpose_claim():
    package = _package()
    package["claim_assessment"] = _current_with_twelve_claims(package)
    client = Client(_focused_claim())

    result = asyncio.run(assess_verified_package(MACHINE, package, client, CONTEXT, require_narrative_roles=True))

    assert len(result["claims"]) == 13
    assert result["claims"][:12] == package["claim_assessment"]["claims"]
    assert result["claims"][-1]["narrative_roles"] == ["intended_role"]
    assert result["class_context_review"]["status"] == "completed"


def test_focused_assessment_accepts_the_existing_dict_response_form():
    package = _package()
    package["claim_assessment"] = _current(package)
    client = Client(json.loads(_focused_claim()))

    result = asyncio.run(assess_verified_package(MACHINE, package, client, CONTEXT, require_narrative_roles=True))

    assert result["class_context_review"]["status"] == "completed"
    assert len(client.calls) == 1
