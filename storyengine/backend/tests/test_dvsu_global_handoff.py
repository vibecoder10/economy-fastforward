"""Offline checks for the selected-machine DVSU recovery boundary."""
import asyncio
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock

import dvsu_research_handoff as handoff
import pipeline_executor as executor
import pytest


MACHINE = "SS-2 USS Plunger"
TITLE = "Every US Submarine Class Ever Built"


def test_recovery_guard_stops_before_any_capture_or_discovery(monkeypatch):
    monkeypatch.setattr(handoff, "package_brief", lambda *_: {"ready": False, "missing_fields": ["design"]})
    ex = SimpleNamespace(_gather_verified_machine_source_package=AsyncMock())
    package = {"machine": MACHINE, "sources": [], "candidate_excerpts": []}
    with pytest.raises(handoff.RecoveryStopped, match="guard stopped"):
        asyncio.run(handoff.supplement_missing_research(
            ex, TITLE, MACHINE, {}, package, "SS2", guard=lambda _stage: False,
        ))
    ex._gather_verified_machine_source_package.assert_not_awaited()


def test_unchanged_discovery_started_receipt_never_repeats_search(monkeypatch):
    monkeypatch.setattr(handoff, "package_brief", lambda *_: {"ready": False, "missing_fields": ["actual_use"]})
    monkeypatch.setattr("research_claim_assessment.assessment_fingerprint", lambda *_: "same")
    ex = SimpleNamespace(_gather_verified_machine_source_package=AsyncMock())
    package = {"machine": MACHINE, "sources": [], "candidate_excerpts": [], "claim_assessment": {
        "dvsu_recovery": {"version": 1, "source_fingerprint": "same", "stage": "discovery_started", "missing_fields": ["actual_use"]},
    }}
    result = asyncio.run(handoff.supplement_missing_research(ex, TITLE, MACHINE, {}, package, "SS2"))
    assert result["claim_assessment"]["dvsu_recovery"]["stage"] == "discovery_started"
    ex._gather_verified_machine_source_package.assert_not_awaited()


def test_targeted_recovery_suppresses_alternate_discovery_wave():
    source = inspect.getsource(executor.PipelineExecutor._gather_verified_machine_source_package)
    assert "not payload.get('_dvsu_source_recovery')" in source


def test_ready_factual_preview_bypasses_research(monkeypatch):
    ex = object.__new__(executor.PipelineExecutor)
    video = {'research_payload': {'machine_script_contract': 'factual_100_v1'}}
    monkeypatch.setattr(executor, '_machine_documentary_hold_roster', lambda _: [MACHINE])
    monkeypatch.setattr(executor, '_locked_roster_item_for_machine', lambda _r, _m: MACHINE)
    ex._ensure_initialized = AsyncMock(); ex._install_cancel_support = AsyncMock(); ex._get_video = AsyncMock(return_value=video)
    ex._load_prompt_overrides = AsyncMock(); ex.check_machine_script_preview_readiness = AsyncMock(return_value={'ready': True})
    ex.run_one_machine_research = AsyncMock(side_effect=AssertionError('ready preview must not research'))
    ex._run_static_script_hold = AsyncMock(return_value={'status': 'completed'})
    assert asyncio.run(ex.run_machine_script_preview('video', MACHINE))['status'] == 'completed'
    ex.run_one_machine_research.assert_not_awaited()


@pytest.mark.parametrize('base_errors', [['identity package mismatch'], []])
def test_readiness_never_marks_evidence_gaps_preparable(monkeypatch, base_errors):
    ex = object.__new__(executor.PipelineExecutor)
    ex.tenant_id = 'tenant'; ex._ensure_initialized = AsyncMock(); ex._get_video = AsyncMock(return_value={
        'video_title': TITLE, 'research_payload': {'machine_script_contract': 'factual_100_v1'}})
    ex._load_machine_research_cards = AsyncMock(side_effect=lambda _id, payload, _roster, target_machine=None: payload)
    ex._update_machine_research_validation = AsyncMock()
    payload = {'machine_script_contract': 'factual_100_v1', 'unit_research_cards': [{'machine': MACHINE}],
               'machine_raw_source_packages': {'SS2': {'machine': MACHINE, 'claim_assessment': {'status': 'assessed'}}}}
    monkeypatch.setattr(executor, '_machine_documentary_hold_roster', lambda _: [MACHINE])
    monkeypatch.setattr(executor, '_locked_roster_item_for_machine', lambda _r, _m: MACHINE)
    monkeypatch.setattr(executor, 'enrich_research_payload_readiness', AsyncMock(return_value=payload))
    monkeypatch.setattr(executor, '_research_card_for_machine', lambda *_: {'machine': MACHINE})
    monkeypatch.setattr(executor, '_verified_source_package_for_machine', lambda *_: payload['machine_raw_source_packages']['SS2'])
    monkeypatch.setattr(executor, '_research_card_contract_warnings', lambda *_a, **_k: list(base_errors))
    monkeypatch.setattr(handoff, 'package_brief', lambda *_: {'ready': False, 'missing_fields': ['design']})
    monkeypatch.setattr('research_claim_assessment.current_assessment', lambda *_: {'status': 'assessed'})
    result = asyncio.run(ex.check_machine_script_preview_readiness('video', MACHINE))
    assert result['ready'] is False and result['preparable'] is False
    assert result['preparation_required'] is False


def test_recovery_keeps_recapture_and_discovery_and_orders_checkpoints(monkeypatch):
    monkeypatch.setattr(handoff, 'package_brief', lambda *_: {'ready': False, 'missing_fields': ['design']})
    monkeypatch.setattr('research_claim_assessment.assessment_fingerprint', lambda _m, package, _t: 'after' if package.get('candidate_excerpts') else 'before')
    monkeypatch.setattr('research_claim_assessment.current_assessment', lambda *_: {'status': 'assessed'})
    import factual_source_recapture
    captured = {'sources': [{'source_id': 'R', 'url': 'https://r.test'}], 'candidate_excerpts': [{'source_id': 'R', 'excerpt_id': 'R1', 'source_url': 'https://r.test', 'text': 'recapture'}]}
    monkeypatch.setattr(factual_source_recapture, 'recapture_sources', AsyncMock(return_value=captured))
    discovered = {'sources': [{'source_id': 'D', 'url': 'https://d.test'}], 'candidate_excerpts': [{'source_id': 'D', 'excerpt_id': 'D1', 'source_url': 'https://d.test', 'text': 'discovery'}]}
    ex = SimpleNamespace(_gather_verified_machine_source_package=AsyncMock(return_value=discovered))
    stages=[]
    async def checkpoint(package, stage): stages.append((stage, [r['text'] for r in package.get('candidate_excerpts', [])],
        ((package.get('claim_assessment') or {}).get('dvsu_recovery') or {}).get('source_fingerprint'))); return True
    async def assess(package, _stage): package['claim_assessment'] = {'status': 'assessed'}; return package
    result = asyncio.run(handoff.supplement_missing_research(ex, TITLE, MACHINE,
        {}, {'machine': MACHINE, 'sources': [{'url': 'https://old.test'}], 'candidate_excerpts': []}, 'SS2',
        assess=assess, checkpoint=checkpoint, guard=lambda _: True))
    assert {'recapture', 'discovery'} <= {row['text'] for row in result['candidate_excerpts']}
    assert [stage for stage, _, _ in stages][:2] == ['recapture_captured', 'recapture_assessment']
    assert next(fingerprint for stage, _, fingerprint in stages if stage == 'discovery_started') == 'after'


def test_invalid_assessment_is_checkpointed_before_stop(monkeypatch):
    monkeypatch.setattr(handoff, 'package_brief', lambda *_: {'ready': False, 'missing_fields': ['design']})
    monkeypatch.setattr('research_claim_assessment.current_assessment', lambda *_: None)
    import factual_source_recapture
    monkeypatch.setattr(factual_source_recapture, 'recapture_sources', AsyncMock(return_value={
        'sources': [{'source_id': 'R', 'url': 'https://r.test'}], 'candidate_excerpts': [{'source_id': 'R', 'excerpt_id': 'R1', 'source_url': 'https://r.test', 'text': 'recapture'}]}))
    stages=[]
    async def checkpoint(_package, stage): stages.append(stage); return True
    async def assess(package, _stage):
        package['claim_assessment'] = {'status': 'needs_review', 'diagnostics': {
            'rejected_claims': [{'index': 2, 'reason': 'quote_mismatch'}]}}
        return package
    ex=SimpleNamespace(_gather_verified_machine_source_package=AsyncMock())
    with pytest.raises(handoff.RecoveryStopped, match='invalid.*claim 2 was rejected: quote_mismatch'):
        asyncio.run(handoff.supplement_missing_research(ex, TITLE, MACHINE,
            {}, {'machine': MACHINE, 'sources': [{'url': 'https://old.test'}], 'candidate_excerpts': []}, 'SS2',
            assess=assess, checkpoint=checkpoint, guard=lambda _: True))
    assert stages == ['recapture_captured', 'recapture_assessment']
    ex._gather_verified_machine_source_package.assert_not_awaited()


def test_explicit_url_bypasses_completed_recovery_cache_without_discovery(monkeypatch):
    monkeypatch.setattr(handoff, 'package_brief', lambda *_: {'ready': False, 'missing_fields': ['design']})
    monkeypatch.setattr('research_claim_assessment.assessment_fingerprint', lambda *_: 'same')
    import factual_source_recapture
    supplement = {'sources': [{'source_id': 'N', 'url': 'https://new.example/citation'}],
                  'candidate_excerpts': [{'source_id': 'N', 'excerpt_id': 'N1',
                                          'source_url': 'https://new.example/citation', 'text': 'new exact quote'}]}
    recapture = AsyncMock(return_value=supplement)
    monkeypatch.setattr(factual_source_recapture, 'recapture_sources', recapture)
    old = {'machine': MACHINE, 'sources': [{'source_id': 'S1', 'url': 'https://old.example'}],
           'candidate_excerpts': [{'source_id': 'S1', 'excerpt_id': 'S1-E1', 'source_url': 'https://old.example', 'text': 'old exact quote'}],
           'claim_assessment': {'dvsu_recovery': {'version': 1, 'source_fingerprint': 'same',
                                                   'stage': 'discovery_completed', 'missing_fields': ['design']}}}
    ex = SimpleNamespace(_gather_verified_machine_source_package=AsyncMock())
    result = asyncio.run(handoff.supplement_missing_research(
        ex, TITLE, MACHINE, {'_dvsu_known_sources': {'machine': MACHINE, 'urls': ['https://new.example/citation']}},
        old, 'SS2'))
    recapture.assert_awaited_once()
    ex._gather_verified_machine_source_package.assert_not_awaited()
    assert result['candidate_excerpts'][0] == old['candidate_excerpts'][0]
    assert any(row['text'] == 'new exact quote' for row in result['candidate_excerpts'])
