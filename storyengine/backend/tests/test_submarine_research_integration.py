"""Real research hold; provider and storage boundaries are offline fakes."""
import asyncio, copy, json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pipeline_executor as pe
import factual_machine_summary as summaries
from machine_research_summary import research_summary_ready
MACHINE='SSN-571 USS Nautilus'
TITLE='Every US Submarine Class Ever Built (2026)'
TEXT='USS Nautilus (SSN-571) was commissioned in 1954.'

def setup_case(raw=None, checkpoint=None):
    package={'machine':MACHINE,'candidate_excerpts':[{'excerpt_id':'E1','source_id':'S1','text':TEXT,'source_url':'https://history.test/nautilus','source_title':'Nautilus history','source_capture_method':'fetched_page','locator':'p1'}]}
    if raw is None:
        raw=json.dumps({'claims':[{'claim':'Nautilus was commissioned in 1954.','scope':'SSN-571 commissioning','status':'supported','reason':'Explicit date.','evidence':[{'excerpt_id':'E1','quote':TEXT}],'counterevidence':[]}]})
    client=SimpleNamespace(generate=AsyncMock(return_value=raw))
    payload={'machine_script_contract':'factual_100_v1','unit_roster':[MACHINE],'unit_research_cards':[],'machine_raw_source_packages':{'SSN571':package}}
    ex=pe.PipelineExecutor.__new__(pe.PipelineExecutor);ex.tenant_id='tenant';ex._pipeline=SimpleNamespace(anthropic=client)
    ex._load_machine_research_cards=AsyncMock(side_effect=lambda _v,p,_r,**kw:p)
    ex._checkpoint_machine_raw_source_package=AsyncMock(side_effect=checkpoint,return_value='UPDATE 1')
    ex._checkpoint_one_machine_research_result=AsyncMock(return_value='UPDATE 1')
    ex._upsert_machine_research_card=AsyncMock();ex._log_activity=AsyncMock()
    ex._gather_verified_machine_source_package=AsyncMock(side_effect=AssertionError('unexpected rediscovery'))
    sentence=MACHINE+' was commissioned in 1954.'
    writer=AsyncMock(return_value={'paragraph':sentence,'claim_map':[{'sentence':sentence,'citations':[{'excerpt_id':'E1'}]}],'sources':[{'excerpt_id':'E1','source_url':'https://history.test/nautilus','quote':TEXT}],'passed':True,'warnings':[],'review_context_version':summaries.REVIEW_CONTEXT_VERSION})
    return ex,payload,client,writer

def run_case(ex,payload,writer):
    with patch.object(summaries,'generate_factual_machine_summary',writer):
        return asyncio.run(ex._run_unit_research_hold('video',TITLE,payload,[MACHINE],target_machine=MACHINE))

def test_actual_hold_persists_assessment_and_current_briefing_then_reuses_without_model():
    ex,payload,client,writer=setup_case();original=copy.deepcopy(payload['unit_roster'])
    result=run_case(ex,payload,writer);package=result['machine_raw_source_packages']['SSN571'];card=result['unit_research_cards'][0]
    assert package['claim_assessment']['status']=='assessed'
    assert card['claim_assessment']==package['claim_assessment']
    assert research_summary_ready(MACHINE,package,card['research_summary'],TITLE)
    assert result['unit_roster']==original
    assert ex._checkpoint_machine_raw_source_package.await_count==2
    assert client.generate.await_count==1 and writer.await_count==1
    assert result['unit_research_hold_validation']['passed']
    run_case(ex,result,writer)
    assert client.generate.await_count==1 and writer.await_count==1
    ex._gather_verified_machine_source_package.assert_not_awaited()

def test_invalid_assessment_retained_and_cannot_revalidate_as_ready():
    ex,payload,client,writer=setup_case('not json');result=run_case(ex,payload,writer)
    package=result['machine_raw_source_packages']['SSN571'];card=result['unit_research_cards'][0]
    assert package['claim_assessment']['status']=='needs_review'
    assert not result['unit_research_hold_validation']['passed']
    assert pe._research_card_contract_warnings(MACHINE,card,package,factual_subject_context=TITLE)
    assert client.generate.await_count==1
    writer.assert_not_awaited()

def test_assessment_checkpoint_refusal_stops_before_briefing():
    ex,payload,client,writer=setup_case(checkpoint=['UPDATE 1','UPDATE 0']);result=run_case(ex,payload,writer)
    assert not result['unit_research_hold_validation']['passed']
    assert 'checkpoint refused' in str(result['unit_research_hold_validation'])
    writer.assert_not_awaited();ex._checkpoint_one_machine_research_result.assert_not_awaited()

def test_conflict_only_assessment_keeps_both_sources_and_holds_briefing():
    other=TEXT.replace('1954','1955')
    raw=json.dumps({'claims':[{'claim':'Commissioning year is disputed.','scope':'SSN-571 commissioning','status':'disputed','reason':'Different dates for same event.','evidence':[{'excerpt_id':'E1','quote':TEXT}],'counterevidence':[{'excerpt_id':'E2','quote':other}]}]})
    ex,payload,client,writer=setup_case(raw);package=payload['machine_raw_source_packages']['SSN571']
    package['candidate_excerpts'].append(dict(package['candidate_excerpts'][0],excerpt_id='E2',text=other,source_id='S2',source_url='https://other.test/nautilus'))
    result=run_case(ex,payload,writer);claim=result['unit_research_cards'][0]['claim_assessment']['claims'][0]
    assert claim['evidence'][0]['quote']==TEXT and claim['counterevidence'][0]['quote']==other
    assert not result['unit_research_hold_validation']['passed']
    assert 'no supported claims' in str(result['unit_research_hold_validation'])
    writer.assert_not_awaited()
