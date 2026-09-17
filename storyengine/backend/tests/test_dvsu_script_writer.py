"""Focused offline contracts for the compiled DVsU script writer."""

import json

import pytest

import factual_machine_summary as summary
from test_script_compiler_integration import PARAGRAPH


MACHINE = "SS-1 USS Holland"
URL = "https://museum.example/uss-holland"


class FakeClient:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        # Mock protocol receipt only; this fixture does not judge historical truth.
        if "REVIEW PACKET:\n" in kwargs.get("prompt", ""):
            parsed = json.loads(response) if isinstance(response, str) else response
            packet = json.loads(kwargs["prompt"].split("REVIEW PACKET:\n", 1)[1])
            if isinstance(parsed, dict) and "editorial_review" in parsed:
                parsed.setdefault("support_audit", [{"sentence": row["sentence"], "supported": True,
                    "explanation": "Synthetic fixture support.", "unsupported_claims": []}
                    for row in packet["draft_with_locked_provenance"]["claim_map"]])
                return json.dumps(parsed)
        return response


def _package(text):
    return {
        "machine": MACHINE,
        "sources": [{"source_id": "S1", "title": "Museum", "url": URL}],
        "candidate_excerpts": [{
            "excerpt_id": "E1", "source_id": "S1", "source_title": "Museum", "source_tier": 1,
            "source_url": URL, "locator": "E1", "source_capture_method": "fetched_page", "text": text,
        }],
    }


def _packet(text):
    return {"compiler_version": 2, "prompt_rules_version": 2, "machine": MACHINE,
            "subject_context": "American submarines", "outline": [], "current_briefing": "", "model": "",
            "packet_fingerprint": "packet", "source_fingerprint": "source", "facts": [{
                "fact_id": "F1", "assessment_claim_id": "C1", "category": "purpose", "claim": text,
                "scope": "purpose", "narrative_roles": ["intended_role", "design", "actual_use", "outcome"], "evidence": [{"excerpt_id": "E1", "quote": text, "source_url": URL,
                    "source_id": "S1", "source_title": "Museum", "locator": "E1", "source_capture_method": "fetched_page"}],
            }], "excluded_claims": []}


def _editorial(*, passed=True, issues=None, checks=None):
    return {"version": 1, "passed": passed, "issues": list(issues or []), "checks": checks or {
        "design_intent": True, "actual_use": True, "consequence": True,
        "gap_or_supported_substitute": True, "verdict": True, "spoken_style": True,
    }}


def _raw(text):
    return {"paragraph": text, "claim_map": [
        {"sentence": sentence, "fact_ids": ["F1"]} for sentence in summary._sentences(text)
    ]}


@pytest.mark.asyncio
async def test_missing_compact_brief_stops_before_any_provider_call(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(summary, "build_dvsu_brief", lambda _packet: {"ready": False, "missing_fields": ["actual_use"]})
    monkeypatch.setattr(summary, "brief_warnings", lambda _brief: ["Targeted research required: actual_use."])

    result = await summary.generate_factual_machine_summary(
        MACHINE, _package("SS-1 USS Holland was designed for naval service."), client, script_packet=_packet("SS-1 USS Holland was designed for naval service."),
    )

    assert result["passed"] is False
    assert result["warnings"] == ["Targeted research required: actual_use."]
    assert client.calls == []


@pytest.mark.asyncio
async def test_compiled_script_below_hard_floor_never_reaches_referee(monkeypatch):
    text = ("SS-1 USS Holland " + "served " * 58).strip()
    packet = _packet(text)
    monkeypatch.setattr(summary, "compile_script_packet", lambda *args, **kwargs: packet)
    client = FakeClient()
    raw = {"paragraph": text, "claim_map": [{"sentence": text, "fact_ids": ["F1"]}]}

    result = await summary.review_existing_factual_summary(MACHINE, _package(text), client, raw,
        claim_assessment={}, script_packet=packet)

    assert result["passed"] is False
    assert any("80-word hard floor" in warning for warning in result["warnings"])
    assert client.calls == []


@pytest.mark.asyncio
async def test_compiled_script_requires_factual_and_separate_editorial_receipts(monkeypatch):
    text = PARAGRAPH
    packet = _packet(text)
    monkeypatch.setattr(summary, "compile_script_packet", lambda *args, **kwargs: packet)
    raw = _raw(text)
    client = FakeClient(json.dumps({"passed": True, "issues": [], "editorial_review": _editorial()}))

    result = await summary.review_existing_factual_summary(MACHINE, _package(text), client, raw,
        claim_assessment={}, script_packet=packet)

    assert result["passed"] is True
    assert result["editorial_review_version"] == 1
    assert result["editorial_review"]["checks"]["verdict"] is True
    assert "editorial_review" in client.calls[0]["prompt"]


@pytest.mark.asyncio
async def test_factual_pass_editorial_failure_is_rejected_without_sentence_pruning(monkeypatch):
    text = PARAGRAPH
    packet = _packet(text)
    monkeypatch.setattr(summary, "compile_script_packet", lambda *args, **kwargs: packet)
    raw = _raw(text)
    client = FakeClient(json.dumps({"passed": True, "issues": [], "editorial_review": _editorial(
        passed=False, issues=["The verdict is not sharp enough."],
        checks={**_editorial()["checks"], "verdict": False},
    )}))

    result = await summary.review_existing_factual_summary(MACHINE, _package(text), client, raw,
        allow_sentence_removal=True, claim_assessment={}, script_packet=packet)

    assert result["passed"] is False
    assert result["warnings"] == ["Editorial review: The verdict is not sharp enough."]
    assert result["paragraph"] == text
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_missing_editorial_audit_fails_closed(monkeypatch):
    text = PARAGRAPH
    packet = _packet(text)
    monkeypatch.setattr(summary, "compile_script_packet", lambda *args, **kwargs: packet)
    raw = _raw(text)
    client = FakeClient(json.dumps({"passed": True, "issues": []}))

    result = await summary.review_existing_factual_summary(MACHINE, _package(text), client, raw,
        claim_assessment={}, script_packet=packet)

    assert result["passed"] is False
    assert result["passed"] is False
    assert any("missing" in warning for warning in result["warnings"])


@pytest.mark.asyncio
async def test_compiled_long_closing_is_rejected_before_referee(monkeypatch):
    sentences = (
        "Admiral Dewey attributed great value to submarines for harbor and coast defense based on favorable Navy officer reports, and SS-1 USS Holland embodied that potential.",
        "Her hull incorporated dual propulsion systems, a hydrodynamic shape, and separate ballast systems, while her interior space formed one contiguous compartment.",
        "A reloadable bow torpedo tube carried three torpedoes; a pneumatic dynamite gun was fitted but later removed.",
        "Holland spent most of her ten years in service at the Naval Academy as a training submarine.",
        "Her commissioning in 1900 established the U.S. Submarine Force, an agreement gave Vickers a license to manufacture Holland-class submarines using Electric Boat patents, and seven improved A-class boats followed.",
    )
    text = " ".join(sentences)
    closing = sentences[-1]
    packet = _packet(text)
    monkeypatch.setattr(summary, "compile_script_packet", lambda *args, **kwargs: packet)
    client = FakeClient()

    raw = {"paragraph": text, "claim_map": [{"sentence": sentence, "fact_ids": ["F1"]} for sentence in sentences]}
    result = await summary.review_existing_factual_summary(MACHINE, _package(text), client, raw,
        claim_assessment={}, script_packet=packet)

    assert result["passed"] is False
    assert result["word_count"] == 110
    assert result["paragraph"] == text
    assert result["claim_map"][-1]["sentence"] == closing
    assert result["warnings"] == ["DVSU concluding verdict exceeds 18 words; rewrite the closing sentence without truncating or dropping it."]
    assert client.calls == []


def test_packet_staleness_starts_fresh_but_factual_repair_keeps_prior_draft():
    stale = summary._script_writer_prompt({"machine": MACHINE}, ["Script packet does not match the current script packet."], "OLD PARAGRAPH")
    repair = summary._script_writer_prompt({"machine": MACHINE}, ["Remove unsupported detail."], "OLD PARAGRAPH")

    assert "Start fresh from the DVSU BRIEF" in stale
    assert "OLD PARAGRAPH" not in stale
    assert "Previous draft to repair:\nOLD PARAGRAPH" in repair


def test_support_audit_rejects_global_pass_with_unsupported_causal_clause():
    sentence = "An officer endorsed the vessel, and it was built to prove him right."
    draft = {"claim_map": [{"sentence": sentence}]}
    audit = {"passed": True, "support_audit": [{"sentence": sentence, "supported": True,
        "explanation": "Endorsement is sourced but design motive is not.",
        "unsupported_claims": ["Built to prove him right is an invented motive."]}]}
    assert "invented motive" in summary._support_audit_warnings(audit, draft)[0]
    audit["support_audit"][0]["unsupported_claims"] = []
    audit["support_audit"][0]["supported"] = False
    assert summary._support_audit_warnings(audit, draft)


def test_support_audit_requires_ordered_complete_receipt():
    draft = {"claim_map": [{"sentence": "First."}, {"sentence": "Second."}]}
    rows = [{"sentence": sentence, "supported": True, "explanation": "Explicitly quoted.",
             "unsupported_claims": []} for sentence in ["First.", "Second."]]
    assert summary._support_audit_warnings({"support_audit": rows}, draft) == []
    for bad in [None, [], rows[:1], rows[::-1], [rows[0], rows[0]]]:
        assert summary._support_audit_warnings({"support_audit": bad}, draft)
    rows[0]["explanation"] = ""
    assert summary._support_audit_warnings({"support_audit": rows}, draft)
