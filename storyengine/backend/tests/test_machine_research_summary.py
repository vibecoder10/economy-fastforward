"""Offline contract tests for saved factual research briefings."""

from machine_research_summary import (
    RESEARCH_SUMMARY_VERSION,
    is_recoverable_research_error,
    research_summary_ready,
    saved_research_summary,
)
import factual_machine_research as factual
import pipeline_executor as pe
from factual_machine_summary import REVIEW_CONTEXT_VERSION, _writer_prompt
from research_claim_assessment import _claims_fingerprint, assessment_fingerprint


MACHINE = "I-49 HMS Argus"
CONTEXT = "Every British Aircraft Carrier Class Ever Built"


def _package(text="I-49 HMS Argus, an aircraft carrier, entered service in 1918."):
    return {
        "machine": MACHINE,
        "sources": [{"source_id": "S1", "url": "https://example.test/argus"}],
        "candidate_excerpts": [{
            "excerpt_id": "S1-E1",
            "source_id": "S1",
            "source_title": "Argus record",
            "source_url": "https://example.test/argus",
            "text": text,
            "locator": "S1-E1",
            "source_capture_method": "fetched_page",
        }],
    }


def _assessed(package):
    excerpt = package["candidate_excerpts"][0]
    claims = [{"id": "C1", "claim": "Argus entered service.", "scope": "service", "status": "supported",
               "reason": "The excerpt states it.", "evidence": [{"excerpt_id": "S1-E1", "quote": excerpt["text"],
               "source_url": excerpt["source_url"], "source_title": excerpt["source_title"], "locator": "S1-E1"}],
               "counterevidence": []}]
    package["claim_assessment"] = {
        "version": 1, "status": "assessed", "machine": MACHINE, "subject_context": CONTEXT,
        "probability": None, "provenance_status": "captured", "method": "model_source_assessment",
        "calibration": "not_calibrated", "source_fingerprint": assessment_fingerprint(MACHINE, package, CONTEXT),
        "claims_fingerprint": _claims_fingerprint(claims), "claims": claims,
    }
    return package


def _result():
    sentence = "I-49 HMS Argus entered service in 1918."
    return {
        "passed": True,
        "paragraph": sentence,
        "claim_map": [{"sentence": sentence, "citations": [{"excerpt_id": "S1-E1"}]}],
        "sources": [{"excerpt_id": "S1-E1", "source_url": "https://example.test/argus"}],
        "warnings": [],
        "review_context_version": REVIEW_CONTEXT_VERSION,
    }


def test_saved_summary_is_current_only_for_exact_package_and_context():
    package = _assessed(_package())
    summary = saved_research_summary(MACHINE, package, _result(), CONTEXT)

    assert summary["schema_version"] == RESEARCH_SUMMARY_VERSION
    assert research_summary_ready(MACHINE, package, summary, CONTEXT)
    assert not research_summary_ready(MACHINE, _package("I-49 HMS Argus entered service in 1919."), summary, CONTEXT)
    assert not research_summary_ready(MACHINE, package, summary, "Every British Carrier")


def test_excerpt_only_card_is_not_a_summary_and_failed_result_never_passes():
    package = _package()
    result = _result()
    result["passed"] = False
    result["warnings"] = ["Factual review: disputed date"]
    summary = saved_research_summary(MACHINE, package, result, CONTEXT)

    assert summary["passed"] is False
    assert summary["warnings"] == ["Factual review: disputed date"]
    assert not research_summary_ready(MACHINE, package, summary, CONTEXT)
    assert not research_summary_ready(MACHINE, package, {"evidence_segments": []}, CONTEXT)


def test_factual_card_with_saved_failed_summary_cannot_revalidate_as_passed():
    package = _package()
    package["candidate_excerpts"][0].update({
        "source_capture_method": "fetched_page",
        "source_id": "S1",
        "source_title": "Argus record",
        "locator": "S1-E1",
    })
    card = factual.build_factual_evidence_card(MACHINE, package)
    failed = _result()
    failed.update(passed=False, warnings=["Factual review: disputed date"])
    card["research_summary"] = saved_research_summary(MACHINE, package, failed, CONTEXT)

    warnings = pe._research_card_contract_warnings(
        MACHINE, card, package, factual_subject_context=CONTEXT,
    )
    assert any("summary is missing, failed, or stale" in warning for warning in warnings)

    legacy_card = factual.build_factual_evidence_card(MACHINE, package)
    assert pe._research_card_contract_warnings(MACHINE, legacy_card, package) == []


def test_writer_prompt_keeps_saved_briefing_as_context_not_evidence():
    prompt = _writer_prompt(
        MACHINE, [], [], purpose="research",
        research_briefings=[{"machine": MACHINE, "paragraph": "Prior briefing."}],
    )

    assert "factual research briefing" in prompt
    assert "context only, never evidence" in prompt
    assert "EVIDENCE:" in prompt


def test_recoverable_classifier_only_unwraps_known_source_transport_failure():
    from factual_source_search import SourceDiscoveryError

    timed_out = SourceDiscoveryError("source wave failed")
    timed_out.__cause__ = TimeoutError("gateway timeout")
    assert is_recoverable_research_error(timed_out)

    credits = SourceDiscoveryError("Kie credits exhausted")
    assert not is_recoverable_research_error(credits)
    assert not is_recoverable_research_error(RuntimeError("database connection refused"))
