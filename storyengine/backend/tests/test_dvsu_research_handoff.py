"""Coverage and append-only recovery contracts; no live providers."""
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import dvsu_research_handoff as handoff
from dvsu_script_brief import build_dvsu_brief, brief_warnings
from research_claim_assessment import _assessed_receipt, _validated_claims, _prompt, assessment_fingerprint
from test_script_compiler_integration import _package, MACHINE, SUBJECT


def test_legacy_assessment_shape_and_explicit_role_validation():
    package = _package()
    candidates = {row['excerpt_id']: row for row in package['candidate_excerpts']}
    claims = package['claim_assessment']['claims']
    assert _validated_claims(claims, candidates) == claims
    bad = copy.deepcopy(claims)
    bad[0]['narrative_roles'] = ['imagined_reversal']
    assert _validated_claims(bad, candidates) is None
    bad[0]['narrative_roles'] = ['outcome', 'outcome']
    assert _validated_claims(bad, candidates) is None
    prompt = _prompt(MACHINE, candidates, SUBJECT)
    for field in ('intended_role', 'design', 'actual_use', 'outcome'):
        assert field in prompt
    assert 'commissioning date alone is not actual_use' in prompt


def test_merge_preserves_original_rows_and_remaps_colliding_ids():
    original = _package()
    before = copy.deepcopy(original)
    supplement = {'sources': [{'source_id': 'N1', 'url': 'https://new.example/history'}],
                  'candidate_excerpts': [{'source_id': 'N1', 'excerpt_id': 'E1',
                      'source_url': 'https://new.example/history', 'text': 'Exact new source text.', 'locator': 'p4'}]}
    merged, _, count = handoff.merge_research_sources(original, supplement)
    assert count == 1 and original == before
    assert merged['sources'][:len(original['sources'])] == original['sources']
    assert merged['candidate_excerpts'][:-1] == original['candidate_excerpts']
    last = merged['candidate_excerpts'][-1]
    assert last['source_id'] != 'N1' and last['excerpt_id'] != 'E1'
    assert last['text'] == supplement['candidate_excerpts'][0]['text']
    assert last['source_id'] == merged['sources'][-1]['source_id']
    assert merged['prior_claim_assessments'][-1] == original['claim_assessment']
    assert 'claim_assessment' not in merged


@pytest.mark.asyncio
async def test_complete_brief_reuses_without_gather():
    ex = SimpleNamespace(_gather_verified_machine_source_package=AsyncMock())
    package = _package()
    assert handoff.package_brief(MACHINE, package, SUBJECT)['ready']
    result = await handoff.supplement_missing_research(ex, SUBJECT, MACHINE, {}, package, 'SS1')
    assert result is package
    ex._gather_verified_machine_source_package.assert_not_awaited()


@pytest.mark.asyncio
async def test_gap_recovery_one_gather_preserves_other_machine_and_original(monkeypatch):
    monkeypatch.setattr(handoff, 'package_brief', lambda *a: {'ready': False, 'missing_fields': ['actual_use']})
    package = _package()
    payload = {'machine_raw_source_packages': {'SS1': package, 'SS2': {'keep': True}}}
    before = copy.deepcopy(payload)
    supplement = {'sources': [{'source_id': 'N1', 'url': 'https://new.example/history'}],
        'candidate_excerpts': [{'source_id': 'N1', 'excerpt_id': 'E1', 'source_url': 'https://new.example/history',
            'text': 'Holland served as a training vessel.'}]}
    ex = SimpleNamespace(_fetch_source_text=AsyncMock(return_value=""), _gather_verified_machine_source_package=AsyncMock(return_value=supplement))
    result = await handoff.supplement_missing_research(ex, SUBJECT, MACHINE, payload, package, 'SS1')
    ex._gather_verified_machine_source_package.assert_awaited_once()
    gather_payload = ex._gather_verified_machine_source_package.await_args.args[2]
    assert 'SS1' not in gather_payload['machine_raw_source_packages']
    assert gather_payload['machine_raw_source_packages']['SS2'] == {'keep': True}
    assert gather_payload['_dvsu_source_recovery']['missing_fields'] == ['actual_use']
    assert payload == before
    assert result['candidate_excerpts'][:-1] == package['candidate_excerpts']


@pytest.mark.asyncio
async def test_empty_supplement_preserves_original_evidence(monkeypatch):
    monkeypatch.setattr(handoff, 'package_brief', lambda *a: {'ready': False, 'missing_fields': ['actual_use']})
    package = _package()
    ex = SimpleNamespace(_fetch_source_text=AsyncMock(return_value=''), _gather_verified_machine_source_package=AsyncMock(return_value={'sources': [], 'candidate_excerpts': []}))
    result = await handoff.supplement_missing_research(ex, SUBJECT, MACHINE, {}, package, 'SS1')
    assert result['sources'] == package['sources']
    assert result['candidate_excerpts'] == package['candidate_excerpts']
    ex._gather_verified_machine_source_package.assert_awaited_once()


def test_intended_training_role_is_advisory_and_unknown_blockers_fail_closed():
    brief = build_dvsu_brief({'machine': MACHINE, 'facts': [{'fact_id': 'F1',
        'claim': 'Holland was intended for training.', 'scope': 'purpose'}]})
    assert brief['ready'] is True
    assert 'actual_use' in brief['missing_narrative_roles']
    assert brief_warnings({'ready': False, 'missing_fields': ['current_claim_assessment']})

@pytest.mark.asyncio
async def test_stale_real_packet_stops_writer_without_provider_calls():
    from factual_machine_summary import generate_factual_machine_summary
    from research_claim_assessment import _assessed_receipt
    package = _package()
    claims = [c for c in package['claim_assessment']['claims'] if c['scope'] != 'synthetic narrative protocol fixture']
    package['claim_assessment'] = _assessed_receipt(MACHINE, package, SUBJECT, claims)
    package['claim_assessment']['source_fingerprint'] = 'stale-receipt'
    client = SimpleNamespace(generate=AsyncMock(side_effect=AssertionError('Incomplete research must not spend on writing')))
    result = await generate_factual_machine_summary(MACHINE, package, client, subject_context=SUBJECT)
    assert result['passed'] is False
    assert any('stale' in w for w in result['warnings'])
    client.generate.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('recovery_stage', ['discovery_started', 'discovery_completed'])
async def test_explicit_recapture_carries_discovery_receipt_to_new_assessment_and_then_stops_recovery(monkeypatch, recovery_stage):
    monkeypatch.setattr(handoff, 'package_brief', lambda *_: {'ready': False, 'missing_fields': ['design']})
    import factual_source_recapture

    package = _package()
    old_assessment = copy.deepcopy(package['claim_assessment'])
    package['claim_assessment']['dvsu_recovery'] = {
        'version': 1,
        'source_fingerprint': assessment_fingerprint(MACHINE, package, SUBJECT),
        'stage': recovery_stage,
        'missing_fields': ['actual_use'],
    }
    historical_assessment = copy.deepcopy(package['claim_assessment'])
    captured = {
        'sources': [
            {'source_id': 'R1', 'url': 'https://source.example/one'},
            {'source_id': 'R2', 'url': 'https://source.example/two'},
        ],
        'candidate_excerpts': [
            {'source_id': 'R1', 'excerpt_id': 'R1-E1', 'source_url': 'https://source.example/one', 'text': 'First new exact citation.'},
            {'source_id': 'R2', 'excerpt_id': 'R2-E1', 'source_url': 'https://source.example/two', 'text': 'Second new exact citation.'},
        ],
    }
    recapture = AsyncMock(return_value=captured)
    monkeypatch.setattr(factual_source_recapture, 'recapture_sources', recapture)
    ex = SimpleNamespace(_gather_verified_machine_source_package=AsyncMock())
    checkpoints = []
    assessments = []

    async def assess(working, stage):
        assessments.append(stage)
        refreshed = copy.deepcopy(working)
        refreshed['claim_assessment'] = _assessed_receipt(
            MACHINE, refreshed, SUBJECT, old_assessment['claims'],
        )
        return refreshed

    async def checkpoint(working, stage):
        checkpoints.append((stage, copy.deepcopy(working)))
        return True

    payload = {'_dvsu_known_sources': {
        'machine': MACHINE,
        'urls': ['https://source.example/one', 'https://source.example/two'],
    }}
    result = await handoff.supplement_missing_research(
        ex, SUBJECT, MACHINE, payload, package, 'SS1', assess=assess, checkpoint=checkpoint,
        guard=lambda _: True,
    )

    recapture.assert_awaited_once()
    assert set(recapture.await_args.args[3]) >= {'https://source.example/one', 'https://source.example/two'}
    ex._gather_verified_machine_source_package.assert_not_awaited()
    assert assessments == ['recapture_assessment']
    assessed_checkpoint = next(working for stage, working in checkpoints if stage == 'recapture_assessment')
    carried = assessed_checkpoint['claim_assessment']['dvsu_recovery']
    assert carried == {
        'version': 1,
        'source_fingerprint': assessment_fingerprint(MACHINE, assessed_checkpoint, SUBJECT),
        'stage': recovery_stage,
        'missing_fields': ['design'],
    }
    assert result['prior_claim_assessments'][-1] == historical_assessment

    retry = await handoff.supplement_missing_research(
        ex, SUBJECT, MACHINE, {}, result, 'SS1', assess=assess, checkpoint=checkpoint,
        guard=lambda _: True,
    )
    assert retry is result
    recapture.assert_awaited_once()
    ex._gather_verified_machine_source_package.assert_not_awaited()
    assert assessments == ['recapture_assessment']
