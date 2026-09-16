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
        return self.responses.pop(0)


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
    text = PARAGRAPH.replace(". ", "; ")
    packet = _packet(text)
    monkeypatch.setattr(summary, "compile_script_packet", lambda *args, **kwargs: packet)
    raw = {"paragraph": text, "claim_map": [{"sentence": text, "fact_ids": ["F1"]}]}
    client = FakeClient(json.dumps({"passed": True, "issues": [], "editorial_review": _editorial()}))

    result = await summary.review_existing_factual_summary(MACHINE, _package(text), client, raw,
        claim_assessment={}, script_packet=packet)

    assert result["passed"] is True
    assert result["editorial_review_version"] == 1
    assert result["editorial_review"]["checks"]["verdict"] is True
    assert "editorial_review" in client.calls[0]["prompt"]


@pytest.mark.asyncio
async def test_factual_pass_editorial_failure_is_rejected_without_sentence_pruning(monkeypatch):
    text = PARAGRAPH.replace(". ", "; ")
    packet = _packet(text)
    monkeypatch.setattr(summary, "compile_script_packet", lambda *args, **kwargs: packet)
    raw = {"paragraph": text, "claim_map": [{"sentence": text, "fact_ids": ["F1"]}]}
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
    text = PARAGRAPH.replace(". ", "; ")
    packet = _packet(text)
    monkeypatch.setattr(summary, "compile_script_packet", lambda *args, **kwargs: packet)
    raw = {"paragraph": text, "claim_map": [{"sentence": text, "fact_ids": ["F1"]}]}
    client = FakeClient(json.dumps({"passed": True, "issues": []}))

    result = await summary.review_existing_factual_summary(MACHINE, _package(text), client, raw,
        claim_assessment={}, script_packet=packet)

    assert result["passed"] is False
    assert result["warnings"] == ["Editorial review is missing or invalid."]
