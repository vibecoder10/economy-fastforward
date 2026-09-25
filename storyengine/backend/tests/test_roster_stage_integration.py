"""Exercise real Roster persistence and stage boundaries without provider spend."""
import asyncio
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pipeline_executor as pe
import roster_coverage as coverage
import research.agent as research
from roster_selection import selection_fingerprint


@pytest.fixture
def stage(monkeypatch):
    initial={'machine_script_contract':'factual_machine_v1','machine_discovery_buckets':{},
             'unit_roster':[{'name':f'Candidate {i}'} for i in range(58)],
             'fact_sheet':'original retained facts','unit_roster_validation':{'passed':False},
             # pacing is not under test here: pin 1 min/machine (20 min = 20 machines)
             'roster_settings':{'minutes_per_machine':1}}
    video={'id':'v','status':'idea_logged','render_mode':'static_docu','video_length_minutes':20,
           'video_title':'Every US Submarine Class Ever Built (2026)','research_payload':initial}
    events=[]
    writes=[]
    ex=pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    ex.tenant_id='t'
    ex._get_video=AsyncMock(side_effect=lambda _:copy.deepcopy(video))
    ex._pipeline=SimpleNamespace(anthropic=object(),should_cancel=AsyncMock(return_value=False))
    ex._log_activity=AsyncMock(side_effect=lambda *a:events.append(('activity',a)))
    ex._run_unit_research_hold=AsyncMock(side_effect=AssertionError('Roster must end before unit research'))
    async def save(query,*args):
        assert args[-2:]==('v','t')
        payload=json.loads(args[0]);writes.append(payload)
        video['research_payload']=payload
        events.append(('save',payload.get('research_phase'),(payload.get('roster_selection') or {}).get('status')))
        return 'UPDATE 1'
    monkeypatch.setattr(pe,'execute',save)
    monkeypatch.setattr(pe,'fetch_one',AsyncMock(return_value={'has_saved_work':False}))
    # One named machine per class (9a29062a): every selected entry records its class_name.
    selected={'unit_roster':[{'name':f'Candidate {i}','class_name':f'Group {i}','status':'production','built_count':'1 submarine completed'} for i in range(20)],
              'recommended_final_roster':[f'Candidate {i}' for i in range(20)],'roster_contract':'CONFIRMED',
              'fact_sheet':'compact selected facts','machine_script_contract':'malicious replacement',
              'unit_research_cards':[{'machine':'invented'}]}
    discover=AsyncMock(return_value=selected)
    monkeypatch.setattr(research,'run_research',discover)
    async def audit(client,title,payload,**kwargs):
        assert kwargs['checkpoint_scope']=={'tenant_id':'t','video_id':'v'}
        assert len(video['research_payload']['unit_roster'])==20, 'draft must be durable before audit'
        assert (video['research_payload']['unit_roster_validation'])['passed'] is False
        events.append(('audit',))
        result={'version':coverage.SELECTION_AUDIT_VERSION,'fingerprint':selection_fingerprint(title,payload),
                'passed':True,'sources':[{'url':'https://history.navy.mil/a'},{'url':'https://archives.gov/b'}],'findings':[]}
        payload['independent_selection_audit']=result
        return result
    monkeypatch.setattr(coverage,'audit_roster_selection',audit)
    return ex,video,events,writes,discover,selected


def test_real_roster_stage_saves_twenty_and_stops_before_detail(stage):
    ex,video,events,writes,discover,_=stage
    result=asyncio.run(ex.run_roster_selection('v'))
    assert result['status']=='roster_ready',result
    saved=video['research_payload']
    assert len(saved['unit_roster'])==20
    assert saved['roster_selection']['status']=='completed'
    assert saved['research_phase']=='roster_complete'
    assert saved['unit_roster_validation']['passed'] is True
    assert saved['machine_script_contract']=='factual_machine_v1'
    assert not saved.get('unit_research_cards')
    assert len(saved['roster_selection_history'][0]['payload']['unit_roster'])==58
    assert saved['roster_selection_history'][0]['payload']['fact_sheet']=='original retained facts'
    assert discover.call_args.kwargs['checkpoint_scope']=={'tenant_id':'t','video_id':'v'}
    ex._run_unit_research_hold.assert_not_called()
    assert pe._machine_documentary_hold_roster(video)==[f'Candidate {i}' for i in range(20)]
    discover.reset_mock()
    again=asyncio.run(ex.run_roster_selection('v'))
    assert again['status']=='roster_ready'
    discover.assert_not_called()


def test_audit_failure_saves_false_verdict_and_stops_after_one_correction(stage,monkeypatch):
    ex,video,events,writes,discover,_=stage
    async def fail(client,title,payload,**kwargs):
        value={'passed':False,'findings':[{'candidate':'Candidate0','problem':'not distinct'}]}
        payload['independent_selection_audit']=value
        return value
    monkeypatch.setattr(coverage,'audit_roster_selection',fail)
    result=asyncio.run(ex.run_roster_selection('v'))
    assert result['status']=='failed'
    assert result['roster_selection_failed'] is True
    assert discover.await_count==2
    assert len(video['research_payload']['unit_roster'])==20
    assert video['research_payload']['unit_roster_validation']['passed'] is False
    ex._run_unit_research_hold.assert_not_called()


def test_audit_exception_keeps_pending_draft(stage,monkeypatch):
    ex,video,_,_,discover,_=stage
    monkeypatch.setattr(coverage,'audit_roster_selection',AsyncMock(side_effect=RuntimeError('provider stopped')))
    result=asyncio.run(ex.run_roster_selection('v'))
    assert result['status']=='failed'
    assert len(video['research_payload']['unit_roster'])==20
    assert video['research_payload']['unit_roster_validation']['passed'] is False
    assert discover.await_count==1


def test_no_save_means_no_audit_or_completion(stage,monkeypatch):
    ex,video,_,_,_,_=stage
    monkeypatch.setattr(pe,'execute',AsyncMock(return_value='UPDATE 0'))
    audit=AsyncMock()
    monkeypatch.setattr(coverage,'audit_roster_selection',audit)
    result=asyncio.run(ex.run_roster_selection('v'))
    assert result['status']=='failed'
    audit.assert_not_called()
    assert len(video['research_payload']['unit_roster'])==58


def test_fresh_selection_is_visible_and_detail_starts_only_on_separate_call(stage,monkeypatch):
    ex,video,events,_,discover,_=stage
    video['research_payload']={'machine_script_contract':'factual_machine_v1','roster_settings':{'minutes_per_machine':1}}
    assert asyncio.run(ex.run_roster_selection('v'))['status']=='roster_ready'
    assert len(pe._machine_documentary_hold_roster(video))==20
    assert video['research_payload']['research_phase']=='roster_complete'
    ex._ensure_initialized=AsyncMock()
    ex._install_cancel_support=AsyncMock()
    async def detail(video_id,title,payload,roster):
        assert roster==[f'Candidate {i}' for i in range(20)]
        assert video['research_payload']['research_phase']=='unit_research'
        payload['unit_research_hold_validation']={'passed':True}
        return payload
    ex._run_unit_research_hold=AsyncMock(side_effect=detail)
    monkeypatch.setattr('drive_workspace.sync_video_workspace_fail_soft',AsyncMock())
    # Runtime rosters need verified reference images before detail (cache-truth gate, DB-backed).
    monkeypatch.setattr('roster_images.roster_image_state',AsyncMock(return_value={'status':'completed'}))
    result=asyncio.run(ex.run_unit_research('v'))
    assert result['status']=='ready_for_scripting',result
    assert discover.await_count==1
    ex._run_unit_research_hold.assert_awaited_once()


def test_stale_runtime_with_detailed_work_is_not_promoted_as_legacy(stage):
    ex,video,_,_,discover,_=stage
    assert asyncio.run(ex.run_roster_selection('v'))['status']=='roster_ready'
    video['video_title']='Every British Tank Ever Built'
    video['research_payload']['unit_research_cards']=[{'machine':'Candidate0','facts':'saved'}]
    before=copy.deepcopy(video)
    discover.reset_mock()
    result=asyncio.run(ex.run_roster_selection('v'))
    assert result['status']=='failed'
    assert video==before
    discover.assert_not_called()


def test_legacy_acceptance_checks_current_gate_before_duration(stage,monkeypatch):
    ex,video,_,_,discover,_=stage
    video.pop('video_length_minutes')
    video['research_payload']['unit_roster_validation']={'passed':False,'warnings':['stale rejection']}
    monkeypatch.setattr(pe,'_live_roster_gate',lambda v,p:{'passed':True})
    result=asyncio.run(ex.run_roster_selection('v'))
    assert result['status']=='roster_ready'
    assert 'roster_selection' not in video['research_payload']
    assert video['research_payload']['research_phase']=='roster_complete'
    assert len(video['research_payload']['unit_roster'])==58
    discover.assert_not_called()


def test_script_gate_checks_ordered_paragraphs_not_literal_equality(stage):
    ex,video,_,_,_,_=stage
    assert asyncio.run(ex.run_roster_selection('v'))['status']=='roster_ready'
    paragraphs=[f'Candidate {i} entered service and this is its sourced documentary paragraph.' for i in range(20)]
    assert pe._roster_validation(video['video_title'],video['research_payload'],paragraphs)['passed'] is True
    paragraphs[0]=paragraphs[1]
    assert pe._roster_validation(video['video_title'],video['research_payload'],paragraphs)['passed'] is False


def test_live_gate_keeps_mixed_build_and_source_checks(stage):
    ex,video,_,_,_,_=stage
    assert asyncio.run(ex.run_roster_selection('v'))['status']=='roster_ready'
    assert pe._live_roster_gate(video,video['research_payload'])['passed'] is True
    video['research_payload']['unit_roster'][0]['built_count']='0 ships built'
    assert pe._live_roster_gate(video,video['research_payload'])['passed'] is False


def test_saved_surplus_candidates_are_bounded_then_audited_without_rediscovery(stage):
    from roster_selection import selection_settings
    ex,video,events,writes,discover,selected=stage
    saved=copy.deepcopy(selected)
    saved.pop('unit_research_cards')
    saved['unit_roster'].append({'name':'Surplus class','class_name':'Group 20','status':'production','built_count':'1 completed'})
    saved['recommended_final_roster'].append('Surplus class')
    saved['roster_selection']={'version':1,'settings':selection_settings(20,1),'status':'needs_review'}
    video['research_payload']=saved
    result=asyncio.run(ex.run_roster_selection('v'))
    assert result['status']=='roster_ready',result
    discover.assert_not_called()
    assert len(video['research_payload']['unit_roster'])==20
    assert video['research_payload']['roster_candidate_overflow'][0]['name']=='Surplus class'
    assert ('audit',) in events
    ex._run_unit_research_hold.assert_not_called()
