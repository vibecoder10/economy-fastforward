"""Contract tests for deterministic bounded script evidence packets."""
from __future__ import annotations

import copy

import pytest

from research_claim_assessment import _claims_fingerprint, assessment_fingerprint
import script_research_packet as compiler
from script_research_packet import (
    MAX_INPUT_TOKEN_UPPER_BOUND,
    ScriptPacketError,
    assert_request_budget,
    compile_script_packet,
    materialize_script_draft,
)


MACHINE = "USS Example (SS-1)"
URL = "https://example.test/uss-example"


def _package():
    return {"machine": MACHINE, "sources": [{"source_id": "S1", "url": URL}], "candidate_excerpts": [
        {"excerpt_id": "E1", "source_id": "S1", "source_url": URL, "source_title": "Record",
         "locator": "E1", "source_capture_method": "fetched_page", "source_tier": 1,
         "text": "USS Example (SS-1) was commissioned in 1901 and used diesel engines."},
        {"excerpt_id": "E2", "source_id": "S1", "source_url": URL, "source_title": "Record",
         "locator": "E2", "source_capture_method": "fetched_page", "source_tier": 2,
         "text": "USS Example (SS-1) was designed for coastal defense and was decommissioned in 1920."},
    ]}


def _assessment(package):
    claims = [
        {"id": "C1", "claim": "USS Example was commissioned in 1901.", "scope": "service", "status": "supported", "reason": "quoted",
         "evidence": [{"excerpt_id": "E1", "quote": "USS Example (SS-1) was commissioned in 1901"}], "counterevidence": []},
        {"id": "C2", "claim": "USS Example was designed for coastal defense.", "scope": "purpose", "status": "supported", "reason": "quoted",
         "evidence": [{"excerpt_id": "E2", "quote": "USS Example (SS-1) was designed for coastal defense"}], "counterevidence": []},
        {"id": "C3", "claim": "USS Example sank in battle.", "scope": "outcome", "status": "disputed", "reason": "conflict",
         "evidence": [{"excerpt_id": "E1", "quote": "USS Example (SS-1) was commissioned in 1901"}],
         "counterevidence": [{"excerpt_id": "E2", "quote": "USS Example (SS-1) was designed for coastal defense"}]},
    ]
    receipt = {"version": 1, "status": "assessed", "machine": MACHINE, "subject_context": "Submarines",
               "probability": None, "provenance_status": "captured", "method": "model_source_assessment",
               "calibration": "not_calibrated", "claims": claims}
    receipt["source_fingerprint"] = assessment_fingerprint(MACHINE, package, "Submarines")
    receipt["claims_fingerprint"] = _claims_fingerprint(claims)
    return receipt


def _packet():
    package = _package()
    return compile_script_packet(MACHINE, package, _assessment(package),
                                 {row["excerpt_id"]: row for row in package["candidate_excerpts"]},
                                 subject_context="Submarines", episode_outline=[{"scene": 1, "machine": MACHINE}],
                                 current_briefing={"paragraph": "A prior wording reference."}, model="model-a")


def test_packet_is_stable_and_selects_supported_categories_without_mutating_inputs():
    package = _package()
    assessment = _assessment(package)
    candidates = {row["excerpt_id"]: row for row in package["candidate_excerpts"]}
    original = copy.deepcopy((package, assessment, candidates))
    first = compile_script_packet(MACHINE, package, assessment, candidates, subject_context="Submarines")
    second = compile_script_packet(MACHINE, package, assessment, dict(reversed(list(candidates.items()))), subject_context="Submarines")
    assert first["packet_fingerprint"] == second["packet_fingerprint"]
    assert [row["category"] for row in first["facts"]] == ["purpose", "service"]
    assert first["excluded_claims"] == [{"assessment_claim_id": "C3", "status": "disputed", "reason_code": "assessment_disputed"}]
    assert (package, assessment, candidates) == original


def test_packet_rejects_forged_source_metadata_and_cross_machine_assessment():
    package = _package(); assessment = _assessment(package)
    candidates = {row["excerpt_id"]: dict(row) for row in package["candidate_excerpts"]}
    assessment["claims"][0]["evidence"][0]["source_url"] = "https://forged.test"
    with pytest.raises(ScriptPacketError, match="source URL"):
        compile_script_packet(MACHINE, package, assessment, candidates, subject_context="Submarines")
    with pytest.raises(ScriptPacketError, match="assessment"):
        compile_script_packet("Another machine", package, _assessment(package), candidates, subject_context="Submarines")


def test_full_fact_skip_failure_and_configuration_invalidation():
    package = _package()
    assessment = _assessment(package)
    # Force the highest-priority purpose fact over the byte cap. The following
    # service fact must still occupy the vacant slot.
    huge = "X" * 11000
    package["candidate_excerpts"][1]["text"] = huge
    assessment["claims"][1]["evidence"] = [{"excerpt_id": "E2", "quote": huge}]
    for excerpt_id in ("E3", "E4"):
        extra = copy.deepcopy(package["candidate_excerpts"][1]); extra["excerpt_id"] = excerpt_id; extra["locator"] = excerpt_id
        package["candidate_excerpts"].append(extra)
        assessment["claims"][1]["evidence"].append({"excerpt_id": excerpt_id, "quote": huge})
    candidates = {r["excerpt_id"]: r for r in package["candidate_excerpts"]}
    packet = compile_script_packet(MACHINE, package, assessment, candidates, subject_context="Submarines")
    assert [row["assessment_claim_id"] for row in packet["facts"]] == ["C1"]
    assert {row["reason_code"] for row in packet["excluded_claims"]} >= {"fact_exceeds_packet_limit", "assessment_disputed"}
    assert len(__import__("json").dumps(packet, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()) <= 32000
    # The packet includes model, source content, and outline in its fingerprint.
    package = _package()
    alternate = compile_script_packet(MACHINE, package, _assessment(package), {r["excerpt_id"]: r for r in package["candidate_excerpts"]},
                                      subject_context="Submarines", model="model-b")
    baseline = compile_script_packet(MACHINE, package, _assessment(package), {r["excerpt_id"]: r for r in package["candidate_excerpts"]}, subject_context="Submarines")
    assert baseline["packet_fingerprint"] != alternate["packet_fingerprint"]
    changed_source = copy.deepcopy(package); changed_source["sources"][0]["extra"] = "changed"
    assert baseline["packet_fingerprint"] != compile_script_packet(MACHINE, changed_source, _assessment(package), {r["excerpt_id"]: r for r in package["candidate_excerpts"]}, subject_context="Submarines")["packet_fingerprint"]
    assert baseline["packet_fingerprint"] != compile_script_packet(MACHINE, package, _assessment(package), {r["excerpt_id"]: r for r in package["candidate_excerpts"]}, subject_context="Submarines", episode_outline=[{"scene": 2, "machine": MACHINE}])["packet_fingerprint"]


def test_selection_limit_and_reordered_claim_evidence_lists_are_stable():
    package = _package(); assessment = _assessment(package)
    base = assessment["claims"][0]
    for number in range(4, 13):
        copied = copy.deepcopy(base); copied["id"] = f"C{number}"; copied["claim"] = f"USS Example served in {number}."; copied["scope"] = "service"
        assessment["claims"].append(copied)
    candidates = {r["excerpt_id"]: r for r in package["candidate_excerpts"]}
    packet = compile_script_packet(MACHINE, package, assessment, candidates, subject_context="Submarines")
    assert len(packet["facts"]) == 8
    assert sum(row["reason_code"] == "selection_limit" for row in packet["excluded_claims"]) == 3
    reordered = copy.deepcopy(assessment); reordered["claims"].reverse()
    assert packet["packet_fingerprint"] == compile_script_packet(MACHINE, package, reordered, candidates, subject_context="Submarines")["packet_fingerprint"]


def test_duplicate_facts_choose_lowest_claim_id_and_preserve_category_output_order():
    package = _package(); assessment = _assessment(package)
    duplicate = copy.deepcopy(assessment["claims"][0]); duplicate["id"] = "C0"
    assessment["claims"].append(duplicate)
    packet = compile_script_packet(MACHINE, package, assessment, {r["excerpt_id"]: r for r in package["candidate_excerpts"]}, subject_context="Submarines")
    assert [row["assessment_claim_id"] for row in packet["facts"] if row["category"] == "service"] == ["C0"]
    assert any(row["reason_code"] == "duplicate_fact" and row["assessment_claim_id"] == "C1" for row in packet["excluded_claims"])
    assert [row["category"] for row in packet["facts"]] == sorted([row["category"] for row in packet["facts"]], key=("identity", "purpose", "design", "service", "outcome", "other").index)


def test_tight_limit_fails_when_no_whole_fact_can_fit(monkeypatch):
    package = _package(); assessment = _assessment(package)
    monkeypatch.setattr(compiler, "MAX_PACKET_BYTES", 1000)
    with pytest.raises(ScriptPacketError, match="packet"):
        compile_script_packet(MACHINE, package, assessment, {r["excerpt_id"]: r for r in package["candidate_excerpts"]}, subject_context="Submarines")


def test_materialize_rebuilds_citations_and_rejects_unknown_fact_ids():
    packet = _packet()
    fact_ids = [row["fact_id"] for row in packet["facts"]]
    result = materialize_script_draft({"paragraph": "A sentence.", "claim_map": [
        {"sentence": "A sentence.", "fact_ids": fact_ids, "citations": [{"excerpt_id": "forged"}]},
    ]}, packet)
    assert {row["excerpt_id"] for row in result["claim_map"][0]["citations"]} == {"E1", "E2"}
    with pytest.raises(ScriptPacketError, match="fact ID"):
        materialize_script_draft({"claim_map": [{"sentence": "A.", "fact_ids": ["Fmissing"]}]}, packet)
    with pytest.raises(ScriptPacketError, match="fact ID"):
        materialize_script_draft({"claim_map": [{"sentence": "A.", "fact_ids": [{"nested": "bad"}]}]}, packet)
    with pytest.raises(ScriptPacketError, match="fact ID"):
        materialize_script_draft({"claim_map": [{"sentence": "A.", "fact_ids": []}]}, packet)


def test_quote_mismatch_fails_closed():
    package = _package(); assessment = _assessment(package)
    assessment["claims"][0]["evidence"][0]["quote"] = "not in source"
    with pytest.raises(ScriptPacketError, match="quote"):
        compile_script_packet(MACHINE, package, assessment, {r["excerpt_id"]: r for r in package["candidate_excerpts"]}, subject_context="Submarines")


def test_budget_is_conservative_and_fails_closed():
    receipt = assert_request_budget("hello", "system", 5)
    assert receipt["input_token_upper_bound"] == len(b"hellosystem") + 1024
    with pytest.raises(ScriptPacketError, match="budget"):
        assert_request_budget("x" * MAX_INPUT_TOKEN_UPPER_BOUND, "", 1)
