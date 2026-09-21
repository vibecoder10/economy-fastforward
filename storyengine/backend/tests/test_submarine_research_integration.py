"""Real research hold; provider and storage boundaries are offline fakes.

DVSU v2 (65545d8e) replaced the factual per-machine source capture, claim
assessment and provider-written summary with Call 3: six targeted searches
whose packet is adapted mechanically into the package/card
(dvsu_research_v2.py). These tests drive the real hold through that path with a
fake provider client.
"""
import asyncio, copy, json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pytest
import pipeline_executor as pe
import dvsu_research_v2 as v2
from machine_research_summary import research_summary_ready
MACHINE='SSN-571 USS Nautilus'
TITLE='Every US Submarine Class Ever Built (2026)'
KEY='SSN571'

def slot(answer, url, quote):
    return json.dumps({'answer':answer,'source_url':url,'quote':quote})

def six_slot_responses():
    return [
        slot('The Navy needed a boat that could stay submerged.','https://history.test/problem','USS Nautilus (SSN-571) was built to stay submerged.'),
        slot('Nautilus used nuclear propulsion.','https://history.test/design','USS Nautilus (SSN-571) used a nuclear reactor.'),
        slot('Reactor shielding added weight and cost.','https://history.test/tradeoff','USS Nautilus (SSN-571) carried heavy shielding.'),
        json.dumps({'candidates':[
            {'fact':'Nautilus reached the North Pole in 1958.','source_url':'https://history.test/outcome1','quote':'USS Nautilus (SSN-571) reached the North Pole in 1958.'},
            {'fact':'Nautilus was preserved as a museum.','source_url':'https://history.test/outcome2','quote':'USS Nautilus (SSN-571) is a museum ship.'}]}),
        slot('The boat was christened by a First Lady.','https://history.test/surprise','USS Nautilus (SSN-571) was christened in 1954.'),
        slot('It is now a museum rather than a warship.','https://history.test/contrast','USS Nautilus (SSN-571) was decommissioned in 1980.'),
    ]

class Client:
    """Queued provider responses; every generate() call is one paid search."""
    def __init__(self, *responses):
        self.responses=list(responses); self.calls=[]
    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)

def setup_case(checkpoint=None):
    client=Client(*six_slot_responses())
    payload={'machine_script_contract':'factual_100_v1','machine_discovery_buckets':{},'unit_roster':[MACHINE],
             'shared_context':['A shared fact.'],'unit_research_cards':[],'machine_raw_source_packages':{}}
    video={'id':'video','status':'idea_logged','video_title':TITLE,'render_mode':'static_docu','max_spend':None,'total_cost':0}
    ex=pe.PipelineExecutor.__new__(pe.PipelineExecutor);ex.tenant_id='tenant'
    ex._pipeline=SimpleNamespace(anthropic=client,should_cancel=AsyncMock(return_value=False))
    ex._get_video=AsyncMock(side_effect=lambda _v:dict(video,research_payload=copy.deepcopy(payload)))
    ex._load_machine_research_cards=AsyncMock(side_effect=lambda _v,p,_r,**kw:p)
    ex._checkpoint_machine_raw_source_package=AsyncMock(side_effect=checkpoint,return_value='UPDATE 1')
    ex._checkpoint_one_machine_research_result=AsyncMock(return_value='UPDATE 1')
    ex._upsert_machine_research_card=AsyncMock();ex._log_activity=AsyncMock()
    ex._gather_verified_machine_source_package=AsyncMock(side_effect=AssertionError('unexpected rediscovery'))
    return ex,payload,client

@pytest.fixture(autouse=True)
def offline_boundaries(monkeypatch):
    monkeypatch.setattr('cancel_registry.is_cancel_requested',AsyncMock(return_value=False))
    # Call 3 exports its packet to Google Drive fail-soft; never reach a real account from a test.
    monkeypatch.setattr(v2,'export_machine_packet_to_drive_fail_soft',AsyncMock(return_value=None))

def run_case(ex,payload):
    return asyncio.run(ex._run_unit_research_hold('video',TITLE,payload,[MACHINE],target_machine=MACHINE))

def test_actual_hold_persists_assessment_and_current_briefing_then_reuses_without_model():
    ex,payload,client=setup_case();original=copy.deepcopy(payload['unit_roster'])
    result=run_case(ex,payload);package=result['machine_raw_source_packages'][KEY];card=result['unit_research_cards'][0]
    assert package['claim_assessment']['status']=='assessed'
    assert card['claim_assessment']==package['claim_assessment']
    assert research_summary_ready(MACHINE,package,card['research_summary'],TITLE)
    assert result['unit_roster']==original
    ex._checkpoint_machine_raw_source_package.assert_awaited_once()
    assert len(client.calls)==6
    assert result['unit_research_hold_validation']['passed']
    run_case(ex,result)
    assert len(client.calls)==6, 'a current saved briefing must be reused without another provider call'
    ex._gather_verified_machine_source_package.assert_not_awaited()

def test_incomplete_packet_is_retained_for_review_and_cannot_revalidate_as_ready():
    ex,payload,client=setup_case()
    async def packet(*args,**kwargs):
        value=await real_packet(*args,**kwargs)
        value['trade_off']=None
        return value
    real_packet=v2.run_machine_research_packet
    with patch.object(v2,'run_machine_research_packet',packet):
        result=run_case(ex,payload)
    validation=result['unit_research_hold_validation']
    package=result['machine_raw_source_packages'][KEY];card=result['unit_research_cards'][0]
    assert not validation['passed']
    assert 'trade_off' in str(validation)
    assert card['research_summary']['passed'] is False
    assert not research_summary_ready(MACHINE,package,card['research_summary'],TITLE)
    assert len(client.calls)==6

def test_package_checkpoint_refusal_stops_before_card_is_saved():
    ex,payload,client=setup_case(checkpoint=['UPDATE 0']);result=run_case(ex,payload)
    assert not result['unit_research_hold_validation']['passed']
    assert 'checkpoint refused' in str(result['unit_research_hold_validation'])
    assert result['unit_research_cards']==[]
    ex._checkpoint_one_machine_research_result.assert_not_awaited();ex._upsert_machine_research_card.assert_not_awaited()

# The old "conflict-only assessment keeps both sources and holds the briefing"
# test was removed with the claim-assessment step it exercised: v2 Call 3 gets one
# sourced answer per slot and builds the assessment mechanically (every claim
# supported), so there is no disputed-claim state left to hold on.

def test_full_roster_completion_clears_last_child_target_marker():
    ex,payload,client=setup_case()
    payload=run_case(ex,payload)
    assert payload['unit_research_hold_validation']['target_machine']==MACHINE
    ex._ensure_initialized=AsyncMock();ex._install_cancel_support=AsyncMock()
    ex._pipeline.should_cancel=AsyncMock(return_value=False)
    ex._get_video=AsyncMock(return_value={'id':'video','status':'idea_logged','render_mode':'static_docu','video_title':TITLE,'research_payload':payload})
    ex._run_unit_research_hold=AsyncMock(return_value=payload)
    execute=AsyncMock(return_value='UPDATE 1')
    with patch.object(pe,'_live_roster_gate',return_value={'passed':True}), patch.object(pe,'execute',execute), patch('drive_workspace.sync_video_workspace_fail_soft',new=AsyncMock()):
        result=asyncio.run(ex.run_unit_research('video'))
    assert result['status']=='ready_for_scripting',result
    saved=json.loads(execute.call_args_list[-1].args[1])
    assert saved['unit_research_hold_validation']['passed']
    assert 'target_machine' not in saved['unit_research_hold_validation']
    assert 'target_machine_passed' not in saved['unit_research_hold_validation']
    assert len(client.calls)==6
