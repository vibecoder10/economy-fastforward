"""Regression coverage for compact factual research writer/referee prompts."""
import asyncio
import copy
from unittest.mock import AsyncMock

import dvsu_research_handoff as handoff
import factual_machine_summary as summary
import pipeline_executor as executor
from script_research_packet import assert_request_budget


MACHINE = "SS-2 USS Plunger"
TITLE = "Every US Submarine Class Ever Built (2026)"
SUMMARY_GAP = "factual research summary is missing, failed, or stale for the current sources/context"


def _assessment():
    """Small current ledger with the same archival shape as the live receipt."""
    return {
        "status": "assessed",
        "machine": MACHINE,
        "claims": [
            {"id": "C1", "claim": "USS Plunger (SS-2) was a submarine torpedo boat.",
             "scope": "machine", "status": "supported", "narrative_roles": ["intended_role"],
             "evidence": [{"excerpt_id": "S2-E1", "quote": "submarine torpedo boat"}],
             "counterevidence": []},
            {"id": "C2", "claim": "The evidence records a later service event.",
             "scope": "service", "status": "disputed", "narrative_roles": ["actual_use"],
             "evidence": [{"excerpt_id": "S2-E2", "quote": "service event"}],
             "counterevidence": [{"excerpt_id": "S2-E3", "quote": "different event"}]},
        ],
        "previous_assessment": {"history_sentinel": "ARCHIVED-HISTORY-MUST-NOT-REACH-PROMPT" * 5000},
        "raw_response": "raw history must not reach a prompt",
        "source_fingerprint": "archival metadata must not reach a prompt",
    }


def _evidence():
    return [
        {"excerpt_id": "S2-E1", "source_id": "S2", "source_title": "Archive", "source_url": "https://example.test/one", "locator": "S2-E1", "text": "USS Plunger (SS-2) was a submarine torpedo boat."},
        {"excerpt_id": "S2-E2", "source_id": "S2", "source_title": "Archive", "source_url": "https://example.test/two", "locator": "S2-E2", "text": "The vessel recorded a service event."},
        {"excerpt_id": "S2-E3", "source_id": "S3", "source_title": "Archive", "source_url": "https://example.test/three", "locator": "S2-E3", "text": "A different event is documented."},
    ]


def test_research_writer_and_referee_fit_budget_without_archival_receipt():
    assessment = _assessment()
    evidence = _evidence()
    writer = summary._writer_prompt(MACHINE, evidence, [], subject_context=TITLE,
                                    purpose="research", claim_assessment=assessment)
    reviewer = summary._review_prompt(
        MACHINE,
        {"paragraph": f"{MACHINE} is covered by the supplied evidence.", "claim_map": []},
        evidence,
        TITLE,
        assessment,
    )

    assert assert_request_budget(writer, "writer", 900)["input_token_upper_bound"] <= 48000
    assert assert_request_budget(reviewer, "reviewer", 900)["input_token_upper_bound"] <= 48000
    assert "previous_assessment" not in writer
    assert "previous_assessment" not in reviewer
    assert "raw_response" not in writer
    assert "raw_response" not in reviewer
    assert '"quote"' not in writer.split("EVIDENCE:\n", 1)[0]


def test_archived_history_has_no_prompt_effect_but_current_constraints_do():
    assessment = _assessment()
    evidence = _evidence()
    baseline = summary._writer_prompt(MACHINE, evidence, [], subject_context=TITLE,
                                      purpose="research", claim_assessment=assessment)

    archived = copy.deepcopy(assessment)
    archived["previous_assessment"] = {"history_sentinel": "different archival history" * 5000}
    with_history = summary._writer_prompt(MACHINE, evidence, [], subject_context=TITLE,
                                          purpose="research", claim_assessment=archived)
    assert with_history == baseline
    assert "ARCHIVED-HISTORY-MUST-NOT-REACH-PROMPT" not in with_history

    changed = copy.deepcopy(assessment)
    changed["claims"][0]["status"] = "disputed"
    changed["claims"][0]["claim"] = "Changed current claim constraint."
    current_change = summary._writer_prompt(MACHINE, evidence, [], subject_context=TITLE,
                                            purpose="research", claim_assessment=changed)
    assert current_change != baseline
    assert "Changed current claim constraint." in current_change
    assert '"status": "disputed"' in current_change


def test_empty_budget_failure_starts_fresh_without_invalid_repair_instruction():
    prompt = summary._writer_prompt(
        MACHINE, [], ["Script request exceeds the conservative model input budget."],
        prior_draft="", subject_context=TITLE, purpose="research", claim_assessment={"claims": []},
    )
    assert "stopped before a draft was produced" in prompt
    assert "there is no previous draft to preserve or repair" in prompt
    assert "Previous draft to repair" not in prompt


def _readiness_executor(monkeypatch, base_warnings, assessment):
    ex = object.__new__(executor.PipelineExecutor)
    ex.tenant_id = "tenant"
    ex._ensure_initialized = AsyncMock()
    ex._get_video = AsyncMock(return_value={
        "video_title": TITLE,
        "research_payload": {"machine_script_contract": "factual_100_v1"},
    })
    ex._load_machine_research_cards = AsyncMock(side_effect=lambda _id, payload, _roster, target_machine=None: payload)
    ex._update_machine_research_validation = AsyncMock()
    payload = {
        "machine_script_contract": "factual_100_v1",
        "unit_research_cards": [{"machine": MACHINE}],
        "machine_raw_source_packages": {"SS2": {"machine": MACHINE, "claim_assessment": {"status": "assessed"}}},
    }
    monkeypatch.setattr(executor, "_machine_documentary_hold_roster", lambda _: [MACHINE])
    monkeypatch.setattr(executor, "_locked_roster_item_for_machine", lambda _r, _m: MACHINE)
    monkeypatch.setattr(executor, "enrich_research_payload_readiness", AsyncMock(return_value=payload))
    monkeypatch.setattr(executor, "_research_card_for_machine", lambda *_: {"machine": MACHINE})
    monkeypatch.setattr(executor, "_verified_source_package_for_machine", lambda *_: payload["machine_raw_source_packages"]["SS2"])
    monkeypatch.setattr(executor, "_research_card_contract_warnings", lambda *_a, **_k: list(base_warnings))
    monkeypatch.setattr(handoff, "package_brief", lambda *_: {"ready": True, "missing_fields": []})
    monkeypatch.setattr(handoff, "package_brief_warnings", lambda *_: [])
    monkeypatch.setattr("research_claim_assessment.current_assessment", lambda *_: assessment)
    return ex


def test_readiness_allows_only_current_assessed_summary_gap_to_prepare(monkeypatch):
    ex = _readiness_executor(monkeypatch, [SUMMARY_GAP], {"status": "assessed"})
    result = asyncio.run(ex.check_machine_script_preview_readiness("video", MACHINE))
    assert result["ready"] is False
    assert result["preparable"] is True
    assert result["preparation_required"] is True


def test_readiness_keeps_other_failure_or_invalid_assessment_blocked(monkeypatch):
    ex = _readiness_executor(monkeypatch, [SUMMARY_GAP, "identity package mismatch"], {"status": "assessed"})
    blocked = asyncio.run(ex.check_machine_script_preview_readiness("video", MACHINE))
    assert blocked["preparable"] is False

    ex = _readiness_executor(monkeypatch, [SUMMARY_GAP], None)
    invalid = asyncio.run(ex.check_machine_script_preview_readiness("video", MACHINE))
    assert invalid["preparable"] is False
