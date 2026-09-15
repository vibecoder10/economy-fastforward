import asyncio
import json
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException
import routes.pipeline as route
import production_guide as guide


def setup(monkeypatch, **changed):
    video={'status':'idea_logged','render_mode':'static_docu','research_payload':{'unit_roster':['saved draft']},'has_scripts':False,**changed}
    monkeypatch.setattr(route,'_is_task_active',AsyncMock(return_value=False))
    monkeypatch.setattr(route.generation_claims,'acquire',AsyncMock(return_value=True))
    release=AsyncMock()
    monkeypatch.setattr(route.generation_claims,'release_owned',release)
    monkeypatch.setattr(route,'fetch_one',AsyncMock(return_value=video))
    write=AsyncMock(return_value='UPDATE 1')
    monkeypatch.setattr(route,'execute',write)
    return write,release


def test_pacing_save_preserves_payload_and_uses_exclusive_tenant_claim(monkeypatch):
    write,release=setup(monkeypatch)
    result=asyncio.run(route.save_roster_settings('v',route.RosterSettingsRequest(minutes_per_machine=2),'t'))
    assert result['minutes_per_machine']==2
    sql,raw,video,tenant=write.call_args.args
    assert 'jsonb_set' in sql and "'{roster_settings}'" in sql
    assert json.loads(raw)=={'minutes_per_machine':2}
    assert (video,tenant)==('v','t')
    assert route.generation_claims.acquire.call_args.args==('t','v','main')
    assert release.call_args.args[:3]==('t','v','main')


@pytest.mark.parametrize('value',[0,-1,float('nan'),float('inf')])
def test_invalid_pacing_has_no_db_write(monkeypatch,value):
    write,_=setup(monkeypatch)
    with pytest.raises(HTTPException) as err:
        asyncio.run(route.save_roster_settings('v',route.RosterSettingsRequest(minutes_per_machine=value),'t'))
    assert err.value.status_code==400
    write.assert_not_called()


@pytest.mark.parametrize('changed',[
    {'research_payload':{'roster_selection':{'status':'completed'}}},
    {'research_payload':{'unit_research_cards':[{'machine':'saved'}]}},
    {'has_scripts':True}, {'status':'ready_for_scripting'},
])
def test_pacing_cannot_rewrite_accepted_or_downstream_work(monkeypatch,changed):
    write,release=setup(monkeypatch,**changed)
    with pytest.raises(HTTPException) as err:
        asyncio.run(route.save_roster_settings('v',route.RosterSettingsRequest(minutes_per_machine=2),'t'))
    assert err.value.status_code==409
    write.assert_not_called()
    release.assert_awaited_once()


def test_guide_does_not_confuse_roster_with_detailed_research():
    payload={'roster_selection':{'status':'completed'},'research_phase':'roster_complete','unit_roster':['Holland'],'fact_sheet':'selection source'}
    assert guide._stage_snapshot('research',video={'research_payload':payload},summary={},active_task_types=set(),cast_rows=[],env_rows=[],missing_board_scenes=[],bible_characters=[],bible_locations=[],bible_present=False)[0]=='not_started'
    payload['research_phase']='unit_research'
    assert guide._stage_snapshot('research',video={'research_payload':payload},summary={},active_task_types=set(),cast_rows=[],env_rows=[],missing_board_scenes=[],bible_characters=[],bible_locations=[],bible_present=False)[0]=='in_progress'
    payload['unit_research_hold_validation']={'passed':True}
    assert guide._stage_snapshot('research',video={'research_payload':payload},summary={},active_task_types=set(),cast_rows=[],env_rows=[],missing_board_scenes=[],bible_characters=[],bible_locations=[],bible_present=False)[0]=='done'


def test_roster_failure_does_not_trigger_worker_retry(monkeypatch):
    import worker
    import pipeline_executor
    import task_store
    result={'status':'failed','error':'Selected identities need review','roster_selection_failed':True}
    ex=type('Executor',(),{'run_research':AsyncMock(return_value=result)})()
    monkeypatch.setattr(pipeline_executor,'PipelineExecutor',lambda tenant:ex)
    persist=AsyncMock()
    monkeypatch.setattr(task_store,'db_persist_task',persist)
    assert asyncio.run(worker._run_stage({'job_try':1},'research','run_research','v','t',1))==result
    assert persist.call_args.args[3]=='failed'
    ex.run_research.assert_awaited_once()


def test_roster_ready_worker_message_does_not_claim_detailed_research(monkeypatch):
    import worker
    import pipeline_executor
    import task_store
    ex=type('Executor',(),{'run_research':AsyncMock(return_value={'status':'roster_ready'})})()
    monkeypatch.setattr(pipeline_executor,'PipelineExecutor',lambda tenant:ex)
    persist=AsyncMock()
    monkeypatch.setattr(task_store,'db_persist_task',persist)
    asyncio.run(worker._run_stage({'job_try':1},'research','run_research','v','t',1))
    assert persist.call_args.args[3]=='completed'
    assert 'detailed research is next' in persist.call_args.kwargs['message']
