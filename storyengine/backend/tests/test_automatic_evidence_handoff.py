"""Source ingestion through real assessment validation/compiler, with model calls mocked."""
import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import httpx
import pipeline_executor as pe
from factual_source_recapture import recapture_sources, validated_source_urls
from factual_machine_summary import _eligible_candidates
from research_claim_assessment import assess_verified_package, current_assessment
from dvsu_research_handoff import package_brief, merge_research_sources, supplement_missing_research

MACHINE = 'SS-1 USS Holland'
TITLE = 'Every US Submarine Class Ever Built'
URL = 'https://www.govinfo.gov/content/pkg/GPO-CRECB-1901-pt4-v34/pdf/GPO-CRECB-1901-pt4-v34-2.pdf#page=77'
MUSEUM = 'https://navalunderseamuseum.org/undersea-pioneers2/'
FIXTURES = Path(__file__).parent/'fixtures'


def capture_pair():
    ex = object.__new__(pe.PipelineExecutor)
    museum = pe._html_to_visible_text((FIXTURES/'holland-source-section.html').read_text(), preserve_sections=True)
    page = (FIXTURES/'holland-congress-page77.txt').read_text()
    ex._fetch_source_text = AsyncMock(side_effect=lambda _, url: page if url == URL else museum)
    result = asyncio.run(recapture_sources(ex, TITLE, MACHINE, [URL, MUSEUM]))
    return ex, result


def assessment_response(package, *, identity=True):
    candidates = _eligible_candidates(MACHINE, package, TITLE, include_identity_pending=True)
    context = next(r for r in candidates.values() if r['identity_requires_review'])
    anchor = next(r for r in candidates.values() if not r['identity_requires_review'] and 'training submarine' in r['text'])
    claims = []
    for claim, role in [
        ('Admiral Dewey endorsed Holland-type boats for harbor and coast defense.', 'intended_role'),
        ('Holland combined dual propulsion and separate ballast systems.', 'design'),
        ('Holland served at the U.S. Naval Academy as a training submarine.', 'actual_use'),
        ('Improved Holland-type submarines became the Navy’s A-class.', 'outcome'),
    ]:
        refs = [anchor] + ([context] if role == 'intended_role' else [])
        row = {'claim': claim, 'scope': 'Holland in 1900; proposed role remains attributed' if role == 'intended_role' else MACHINE,
               'narrative_roles': [role], 'status': 'supported', 'reason': 'Supported by supplied text.',
               'evidence': [{'excerpt_id': r['excerpt_id'], 'quote': r['text']} for r in refs], 'counterevidence': []}
        if role == 'intended_role' and identity:
            row['identity_reviews'] = [{'excerpt_id': context['excerpt_id'], 'status': 'same_machine',
                'anchor_excerpt_id': anchor['excerpt_id'], 'reason': 'Contemporary 1901 reference to Navy acquisition of Holland matches the museum’s SS 1 identity and 1900 purchase.'}]
        claims.append(row)
    return {'claims': claims}


def test_capture_through_assessment_and_compiler_requires_identity_review():
    ex, package = capture_pair()
    pending = _eligible_candidates(MACHINE, package, TITLE, include_identity_pending=True)
    contextual = {key for key,r in pending.items() if r['identity_requires_review']}
    assert contextual
    assert not contextual.intersection(_eligible_candidates(MACHINE, package, TITLE))
    assert all('#page=77' in r['locator'] for r in pending.values() if r['source_url'] == URL)
    bad = SimpleNamespace(generate=AsyncMock(return_value=json.dumps(assessment_response(package, identity=False))))
    assert asyncio.run(assess_verified_package(MACHINE, package, bad, TITLE))['status'] == 'needs_review'
    client = SimpleNamespace(generate=AsyncMock(return_value=json.dumps(assessment_response(package))))
    assessment = asyncio.run(assess_verified_package(MACHINE, package, client, TITLE))
    assert assessment['status'] == 'assessed'
    package['claim_assessment'] = assessment
    assert current_assessment(MACHINE, package, TITLE)
    assert contextual.intersection(_eligible_candidates(MACHINE, package, TITLE))
    brief = package_brief(MACHINE, package, TITLE)
    assert brief['ready'] and brief['missing_fields'] == []
    assert len(json.dumps(brief).encode()) < 6000
    assert 'source_url' not in json.dumps(brief)
    stale = copy.deepcopy(package)
    stale['candidate_excerpts'][0]['text'] += ' changed'
    assert current_assessment(MACHINE, stale, TITLE) is None
    assert not contextual.intersection(_eligible_candidates(MACHINE, stale, TITLE))
    client.generate.assert_awaited_once()


def test_context_only_package_cannot_become_eligible():
    _, package = capture_pair()
    package['candidate_excerpts'] = [r for r in package['candidate_excerpts'] if r['source_url'] == URL]
    assert _eligible_candidates(MACHINE, package, TITLE, include_identity_pending=True) == {}


def test_original_archive_preserved_with_new_page_locator():
    _, package = capture_pair()
    old = {'machine': MACHINE, 'sources': [], 'candidate_excerpts': []}
    merged, _, added = merge_research_sources(old, package)
    assert old == {'machine': MACHINE, 'sources': [], 'candidate_excerpts': []}
    assert added > 0
    assert '#page=77' in merged['candidate_excerpts'][0]['locator']


def test_known_source_recovery_does_not_discover_or_request_secrets(monkeypatch):
    ex, sources = capture_pair()
    old = {'machine': MACHINE, 'sources': [], 'candidate_excerpts': []}
    ex._gather_verified_machine_source_package = AsyncMock(side_effect=AssertionError('paid search forbidden'))
    monkeypatch.setattr('dvsu_research_handoff.package_brief', lambda *a: {'missing_fields':['intended_role']})
    monkeypatch.setattr(pe, 'get_secret', AsyncMock(side_effect=AssertionError('secret access forbidden')))
    result = asyncio.run(supplement_missing_research(ex,TITLE,MACHINE,
        {'_dvsu_known_sources':{'machine':MACHINE,'urls':[URL,MUSEUM]}},old,'holland'))
    assert result['source_recapture']['paid_search_calls'] == 0
    assert result['source_recapture']['added_excerpt_count'] > 0
    ex._gather_verified_machine_source_package.assert_not_called()


@pytest.mark.parametrize('urls', [['http://127.0.0.1/a'], ['https://example.com']*7, 'https://example.com'])
def test_recapture_rejects_invalid_sources_before_fetch(urls):
    with pytest.raises(ValueError): validated_source_urls(urls)


def test_real_pdf_fetch_reads_page77_without_a_model(monkeypatch):
    pdf = Path(__file__).parents[2]/'docs/holland-brief-2026-09-16/congress-1901.pdf'
    if not pdf.exists(): pytest.skip('Original captured Congressional PDF is local evidence, not a repository asset')
    ex = object.__new__(pe.PipelineExecutor)
    client = SimpleNamespace(get=AsyncMock(return_value=httpx.Response(200,content=pdf.read_bytes(),headers={'content-type':'application/pdf'})))
    text = asyncio.run(ex._fetch_source_text(client,URL))
    assert 'harbor and coast defense' in text
    assert 'U. S. S. Holland' in text
    assert '1901.' in text


def test_captured_evidence_reaches_real_writer_and_review_protocol_without_large_context():
    import factual_machine_summary as summary
    _, package = capture_pair()
    assessor = SimpleNamespace(generate=AsyncMock(return_value=json.dumps(assessment_response(package))))
    package['claim_assessment'] = asyncio.run(assess_verified_package(MACHINE, package, assessor, TITLE))
    brief = package_brief(MACHINE, package, TITLE)
    paragraph = ('Admiral Dewey endorsed SS-1 USS Holland for coast and harbor defense; '
        'the design combined dual propulsion, separate ballast systems and a hydrodynamic hull; '
        'in service, Holland also became a classroom at the Naval Academy, where she served as a training submarine; '
        'improved Holland-type boats followed as the A-class; '
        'that gives the boat a significance beyond its proposed defensive role: it was a submarine the Navy could use to train people, '
        'as well as a design to improve; Holland helped connect the promise of underwater operations with the practical work of building a submarine force.')
    calls = []
    async def generate(**kwargs):
        calls.append(kwargs)
        if 'DVsU documentary writer' in kwargs['system_prompt']:
            return json.dumps({'paragraph':paragraph,'claim_map':[{'sentence':paragraph,'fact_ids':[f['fact_id'] for f in brief['facts']]}]})
        return json.dumps({'passed':True,'issues':[],'editorial_review':{'version':1,'passed':True,'issues':[],
            'checks':dict.fromkeys(['design_intent','actual_use','consequence','gap_or_supported_substitute','verdict','spoken_style'],True)}})
    result = asyncio.run(summary.generate_factual_machine_summary(MACHINE, package, SimpleNamespace(generate=generate), subject_context=TITLE))
    assert result['passed'] and result['factual_passed'], result
    assert 80 <= result['word_count'] <= 110
    assert len(calls) == 2
    assert URL not in calls[0]['prompt'] and 'officersastothegreat' not in calls[0]['prompt']
    assert len(calls[0]['prompt'].encode()) < 10000
    assert URL in calls[1]['prompt']


def test_research_route_forwards_only_valid_known_source_urls(monkeypatch):
    import routes.pipeline as route
    calls = []
    class Executor:
        def __init__(self, tenant): pass
        async def run_one_machine_research(self, video, machine, source_urls=None):
            calls.append((video,machine,source_urls))
            return {'status':'completed'}
    monkeypatch.setattr(route,'PipelineExecutor',Executor)
    result = asyncio.run(route.run_one_machine_research('video',route.MachineResearchRequest(
        machine=MACHINE,confirmed_paid_run=True,source_urls=[URL]),tenant_id='tenant'))
    assert result['status']=='completed' and calls == [('video',MACHINE,[URL])]
    with pytest.raises(route.HTTPException):
        asyncio.run(route.run_one_machine_research('video',route.MachineResearchRequest(
            machine=MACHINE,confirmed_paid_run=True,source_urls=['http://127.0.0.1']),tenant_id='tenant'))
    assert len(calls)==1


def test_saved_assessment_replays_with_materialized_identity_quote_without_new_call():
    from research_claim_assessment import _failed
    _, package = capture_pair()
    raw = assessment_response(package)
    first = raw['claims'][0]
    anchor_id = first['identity_reviews'][0]['anchor_excerpt_id']
    for row in first['evidence']:
        if row['excerpt_id'] == anchor_id:
            row['quote'] = 'USS Holland spent most of her ten years in service at the U.S. Naval Academy as a training submarine.'
    package['claim_assessment'] = _failed(MACHINE,TITLE,'Old strict anchor quote check failed',package,json.dumps(raw))
    client = SimpleNamespace(generate=AsyncMock(side_effect=AssertionError('Must reuse paid assessment')))
    assessment = asyncio.run(assess_verified_package(MACHINE,package,client,TITLE))
    assert assessment['status']=='assessed'
    client.generate.assert_not_called()
    assert any('USS Holland (SS 1)' in r['quote'] for r in assessment['claims'][0]['evidence'])
    package['claim_assessment'] = assessment
    assert current_assessment(MACHINE,package,TITLE) == assessment
