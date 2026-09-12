import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pipeline_executor as pe
import factual_machine_pipeline as fp


@pytest.fixture
def state(monkeypatch):
    machine='I49 HMS Argus'
    package={'machine':machine,'candidate_excerpts':[]}
    video={'video_title':'British carriers','max_spend':None,'status':'ready_for_scripting',
           'research_payload':{'machine_script_contract':fp.CONTRACT}, 'script_validation':{}}
    ex=SimpleNamespace(tenant_id='tenant',_pipeline=SimpleNamespace(anthropic=object(),should_cancel=AsyncMock(return_value=False)))
    ex._get_video=AsyncMock(side_effect=lambda _:copy.deepcopy(video))
    ex._log_activity=AsyncMock()
    ex._log_transition=AsyncMock()
    ex._skip_disabled_next=lambda _video,status:status
    ex._checkpoint_machine_script_preview=AsyncMock(return_value='UPDATE 1')
    ex._db_write_missed=pe.PipelineExecutor._db_write_missed
    async def save(**kwargs):
        block={**kwargs['script_block'],'saved':True}
        video['script_validation']={'machine_script_blocks':{machine:block},'script_hold':{'passed':True,'completed_count':1}}
        video['script']=block['paragraph'];video['status']='ready_for_voice'
        return block
    ex._save_machine_script_block=AsyncMock(side_effect=save)
    monkeypatch.setattr(pe,'fetch_all',AsyncMock(return_value=[]))
    monkeypatch.setattr(pe,'execute',AsyncMock(return_value='UPDATE 1'))
    monkeypatch.setattr(pe,'_machine_documentary_hold_roster',lambda _: [machine])
    monkeypatch.setattr(pe,'_verified_source_package_for_machine',lambda *_:package)
    import factual_machine_summary as fs
    writer=AsyncMock(return_value={'passed':True,'paragraph':'HMS Argus served as an aircraft carrier.','word_count':8,'review_context_version':2,'warnings':[],'claim_map':[],'sources':[]})
    monkeypatch.setattr(fs,'generate_factual_machine_summary',writer)
    return ex,video,machine,package,writer


def test_saved_factual_section_resumes_without_another_model_call(state):
    ex,video,machine,package,writer=state
    result=asyncio.run(fp.run_factual_script_hold(ex,'video',video,[machine]))
    assert result['status']=='completed'
    assert result['new_status']=='ready_for_voice'
    again=asyncio.run(fp.run_factual_script_hold(ex,'video',video,[machine]))
    assert again['status']=='completed'
    assert writer.await_count==1
    assert ex._save_machine_script_block.await_count==1
    assert ex._save_machine_script_block.await_args.kwargs['advance_status'] is False


def test_changed_sources_invalidate_saved_summary(state):
    ex,video,machine,package,writer=state
    asyncio.run(fp.run_factual_script_hold(ex,'video',video,[machine]))
    package['revision']=2
    asyncio.run(fp.run_factual_script_hold(ex,'video',video,[machine]))
    assert writer.await_count==2


def test_rejected_claim_is_checkpointed_but_never_saved_as_script(state):
    ex,video,machine,package,writer=state
    writer.return_value={'passed':False,'paragraph':'Wrong claim.','warnings':['wrong machine']}
    result=asyncio.run(fp.run_factual_script_hold(ex,'video',video,[machine]))
    assert result['status']=='needs_review'
    ex._save_machine_script_block.assert_not_awaited()
    ex._checkpoint_machine_script_preview.assert_awaited_once()


def test_cancel_and_budget_stop_before_generation(state):
    ex,video,machine,package,writer=state
    ex._pipeline.should_cancel.return_value=True
    assert asyncio.run(fp.run_factual_script_hold(ex,'video',video,[machine]))['status']=='cancelled'
    ex._pipeline.should_cancel.return_value=False
    video['max_spend']=0
    assert asyncio.run(fp.run_factual_script_hold(ex,'video',video,[machine]))['status']=='paused'
    writer.assert_not_awaited()


def test_wrong_target_and_failed_save_readback_stop(state):
    ex,video,machine,package,writer=state
    assert asyncio.run(fp.run_factual_script_hold(ex,'video',video,[machine],'HMS Other'))['status']=='failed'
    writer.assert_not_awaited()
    ex._save_machine_script_block.side_effect=None
    ex._save_machine_script_block.return_value={}
    result=asyncio.run(fp.run_factual_script_hold(ex,'video',video,[machine]))
    assert result['status']=='failed'
    assert 'verified' in result['error']


def test_saved_summary_review_upgrade_does_not_rewrite_passed_prose(state, monkeypatch):
    ex,video,machine,package,writer=state
    asyncio.run(fp.run_factual_script_hold(ex,'video',video,[machine]))
    saved=video['script_validation']['machine_script_blocks'][machine]
    saved.pop('review_context_version')
    import factual_machine_summary as fs
    reviewer=AsyncMock(return_value={**saved,'review_context_version':2})
    monkeypatch.setattr(fs,'review_existing_factual_summary',reviewer)
    result=asyncio.run(fp.run_factual_script_hold(ex,'video',video,[machine]))
    assert result['status']=='completed'
    assert writer.await_count==1
    reviewer.assert_awaited_once()
    assert video['script_validation']['machine_script_blocks'][machine]['review_context_version']==2


def test_rejected_old_pass_cannot_release_voice(state, monkeypatch):
    ex,video,machine,package,writer=state
    asyncio.run(fp.run_factual_script_hold(ex,'video',video,[machine]))
    video['status']='ready_for_scripting'
    video['script_validation']['machine_script_blocks'][machine].pop('review_context_version')
    import factual_machine_summary as fs
    failed={'passed':False,'paragraph':'Wrong claim.','warnings':['source disagreement']}
    monkeypatch.setattr(fs,'review_existing_factual_summary',AsyncMock(return_value=failed))
    writer.return_value=failed
    pe.execute.reset_mock()
    result=asyncio.run(fp.run_factual_script_hold(ex,'video',video,[machine]))
    assert result['status']=='needs_review'
    assert video['status']=='ready_for_scripting'
    pe.execute.assert_not_awaited()


def test_restart_reviews_persisted_failed_draft_without_rewriting(state, monkeypatch):
    ex,video,machine,package,writer=state
    failed={'passed':False,'paragraph':'HMS Argus served as an aircraft carrier.','warnings':['former word limit'],'word_count':8}
    writer.return_value=failed
    assert asyncio.run(fp.run_factual_script_hold(ex,'video',video,[machine]))['status']=='needs_review'
    checkpoint=copy.deepcopy(ex._checkpoint_machine_script_preview.await_args.args[2])
    video['research_payload']['machine_script_previews']={pe._verified_source_cache_key(machine):checkpoint}
    # New pipeline object, with only the database checkpoint retained.
    ex._pipeline=SimpleNamespace(anthropic=object(),should_cancel=AsyncMock(return_value=False))
    import factual_machine_summary as fs
    reviewer=AsyncMock(return_value={**failed,'passed':True,'warnings':[],'review_context_version':2})
    monkeypatch.setattr(fs,'review_existing_factual_summary',reviewer)
    writer.reset_mock()
    result=asyncio.run(fp.run_factual_script_hold(ex,'video',video,[machine]))
    assert result['status']=='completed'
    writer.assert_not_awaited()
    reviewer.assert_awaited_once()
    assert reviewer.await_args.args[3]['paragraph']==failed['paragraph']


def test_failed_checkpoint_from_changed_sources_is_not_reused(state, monkeypatch):
    ex,video,machine,package,writer=state
    failed={'passed':False,'paragraph':'HMS Argus served as an aircraft carrier.','warnings':['source conflict']}
    writer.return_value=failed
    asyncio.run(fp.run_factual_script_hold(ex,'video',video,[machine]))
    checkpoint=copy.deepcopy(ex._checkpoint_machine_script_preview.await_args.args[2])
    video['research_payload']['machine_script_previews']={pe._verified_source_cache_key(machine):checkpoint}
    package['revision']=2
    import factual_machine_summary as fs
    reviewer=AsyncMock()
    monkeypatch.setattr(fs,'review_existing_factual_summary',reviewer)
    asyncio.run(fp.run_factual_script_hold(ex,'video',video,[machine]))
    reviewer.assert_not_awaited()
    assert writer.await_count==2
