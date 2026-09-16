import asyncio
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pipeline_executor as pe
import factual_machine_pipeline as fp
import factual_machine_summary as fs


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
    ex._run_unit_research_hold=None
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
    writer=AsyncMock(return_value={'passed':True,'paragraph':'HMS Argus served as an aircraft carrier.','word_count':8,
                                   'review_context_version':fs.REVIEW_CONTEXT_VERSION,
                                   'subject_context':video['video_title'],
                                   'warnings':[],'claim_map':[],'sources':[]})
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


def test_script_writer_receives_only_current_saved_research_briefing_and_compact_outline(state):
    ex,video,machine,package,writer=state
    from machine_research_summary import saved_research_summary
    from research_claim_assessment import _claims_fingerprint, assessment_fingerprint
    quote = 'I49 HMS Argus was an aircraft carrier commissioned with a full flight deck.'
    package.update({
        'sources': [{'source_id': 'S1', 'url': 'https://example.test/argus'}],
        'candidate_excerpts': [{'excerpt_id': 'S1', 'source_id': 'S1', 'source_title': 'Argus carrier record',
            'source_url': 'https://example.test/argus', 'locator': 'S1', 'source_capture_method': 'fetched_page',
            'text': quote}],
    })
    claims = [{'id': 'C1', 'claim': 'Argus had a flight deck.', 'scope': 'configuration', 'status': 'supported',
        'reason': 'The excerpt says so.', 'evidence': [{'excerpt_id': 'S1', 'quote': quote,
        'source_url': 'https://example.test/argus', 'source_title': 'Argus carrier record', 'locator': 'S1'}],
        'counterevidence': []}]
    package['claim_assessment'] = {
        'version': 1, 'status': 'assessed', 'machine': machine, 'subject_context': video['video_title'],
        'probability': None, 'provenance_status': 'captured', 'method': 'model_source_assessment',
        'calibration': 'not_calibrated', 'source_fingerprint': assessment_fingerprint(machine, package, video['video_title']),
        'claims_fingerprint': _claims_fingerprint(claims), 'claims': claims,
    }
    summary=saved_research_summary(machine,package,{
        'passed':True, 'paragraph':'Argus was commissioned with a full flight deck.',
        'claim_map':[{'sentence':'Argus was commissioned with a full flight deck.','citations':[{'excerpt_id':'S1'}]}],
        'sources':[{'excerpt_id':'S1','source_url':'https://example.test/argus'}],
        'review_context_version':fs.REVIEW_CONTEXT_VERSION,
    },video['video_title'])
    video['research_payload']['unit_research_cards']=[{'machine':machine,'research_summary':summary}]
    asyncio.run(fp.run_factual_script_hold(ex,'video',video,[machine]))
    kwargs=writer.await_args.kwargs
    assert 'research_briefings' not in kwargs
    assert kwargs['episode_outline'] == [{'machine':machine, 'scene':1}]
    assert kwargs['current_briefing'] == summary['paragraph']


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
    reviewer=AsyncMock(return_value={**saved,'review_context_version':fs.REVIEW_CONTEXT_VERSION,
                                     'subject_context':video['video_title']})
    monkeypatch.setattr(fs,'review_existing_factual_summary',reviewer)
    result=asyncio.run(fp.run_factual_script_hold(ex,'video',video,[machine]))
    assert result['status']=='completed'
    assert writer.await_count==1
    reviewer.assert_awaited_once()
    assert video['script_validation']['machine_script_blocks'][machine]['review_context_version']==fs.REVIEW_CONTEXT_VERSION


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


def test_restart_reviews_persisted_failed_short_draft_then_attempts_expansion(state, monkeypatch):
    ex,video,machine,package,writer=state
    failed={'passed':False,'paragraph':'HMS Argus served as an aircraft carrier.','warnings':['former word limit'],'word_count':8}
    writer.return_value=failed
    assert asyncio.run(fp.run_factual_script_hold(ex,'video',video,[machine]))['status']=='needs_review'
    checkpoint=copy.deepcopy(ex._checkpoint_machine_script_preview.await_args.args[2])
    checkpoint.pop('length_target_attempted',None)
    video['research_payload']['machine_script_previews']={pe._verified_source_cache_key(machine):checkpoint}
    # New pipeline object, with only the database checkpoint retained.
    ex._pipeline=SimpleNamespace(anthropic=object(),should_cancel=AsyncMock(return_value=False))
    import factual_machine_summary as fs
    reviewer=AsyncMock(return_value={**failed,'passed':True,'warnings':[],
                                     'review_context_version':fs.REVIEW_CONTEXT_VERSION,
                                     'subject_context':video['video_title']})
    monkeypatch.setattr(fs,'review_existing_factual_summary',reviewer)
    writer.reset_mock()
    writer.return_value={**failed,'passed':True,'warnings':[],
                         'review_context_version':fs.REVIEW_CONTEXT_VERSION,
                         'subject_context':video['video_title']}
    result=asyncio.run(fp.run_factual_script_hold(ex,'video',video,[machine]))
    assert result['status']=='completed'
    writer.assert_awaited_once()
    reviewer.assert_awaited_once()
    assert reviewer.await_args.args[3]['paragraph']==failed['paragraph']
    assert writer.await_args.kwargs['previous_summary']['passed'] is True


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


def test_readiness_rejects_changed_title_and_stale_review_context(state):
    _ex,video,machine,package,_writer=state
    fingerprint=fp.source_fingerprint(machine,package)
    block={'passed':True,'paragraph':'Approved prose.','machine':machine,'scene':1,
           'machine_script_contract':fp.CONTRACT,'source_fingerprint':fingerprint,
           'review_context_version':fs.REVIEW_CONTEXT_VERSION,
           'subject_context':video['video_title']}
    video['script_validation']={'machine_script_blocks':{machine:block}}
    assert fp.factual_script_readiness(video,[machine]) is True
    video['video_title']='Every British Aircraft Carrier Class Ever Built'
    assert fp.factual_script_readiness(video,[machine]) is False
    block['subject_context']=video['video_title']
    block['review_context_version']=fs.REVIEW_CONTEXT_VERSION-1
    assert fp.factual_script_readiness(video,[machine]) is False


def test_claim_assessment_change_invalidates_script_fingerprint(state):
    _ex, video, machine, package, _writer = state
    fingerprint = fp.source_fingerprint(machine, package)
    block = {'passed': True, 'paragraph': 'Approved prose.', 'machine': machine, 'scene': 1,
             'machine_script_contract': fp.CONTRACT, 'source_fingerprint': fingerprint,
             'review_context_version': fs.REVIEW_CONTEXT_VERSION, 'subject_context': video['video_title']}
    video['script_validation'] = {'machine_script_blocks': {machine: block}}
    assert fp.factual_script_readiness(video, [machine]) is True

    package['claim_assessment'] = {'version': 1, 'status': 'assessed', 'claims': []}
    assert fp.source_fingerprint(machine, package) != fingerprint
    assert fp.factual_script_readiness(video, [machine]) is False


def test_changed_title_rechecks_large_saved_prose_without_fresh_generation(state, monkeypatch):
    ex,video,machine,package,writer=state
    paragraph=' '.join(['supported']*80)
    fingerprint=fp.source_fingerprint(machine,package)
    video['script_validation']={'machine_script_blocks':{machine:{
        'passed':True,'paragraph':paragraph,'word_count':80,'machine':machine,'scene':1,
        'machine_script_contract':fp.CONTRACT,'source_fingerprint':fingerprint,
        'review_context_version':fs.REVIEW_CONTEXT_VERSION,'subject_context':'Old battleship title',
        'claim_map':[],'sources':[],'saved':True,
    }}}
    video['video_title']='Every British Aircraft Carrier Class Ever Built'
    reviewer=AsyncMock(return_value={
        'passed':True,'paragraph':paragraph,'word_count':80,'warnings':[],
        'claim_map':[],'sources':[],'review_context_version':fs.REVIEW_CONTEXT_VERSION,
        'subject_context':video['video_title'],
    })
    monkeypatch.setattr(fs,'review_existing_factual_summary',reviewer)
    result=asyncio.run(fp.run_factual_script_hold(ex,'video',video,[machine]))
    assert result['status']=='completed'
    reviewer.assert_awaited_once()
    writer.assert_not_awaited()
    assert reviewer.await_args.kwargs['subject_context']==video['video_title']


def test_stale_reviewed_wrong_type_draft_cannot_bypass_current_reviewer(state, monkeypatch):
    ex,video,machine,package,writer=state
    stale='HMS Majestic was an 1890s pre-dreadnought battleship.'
    fingerprint=fp.source_fingerprint(machine,package)
    video['script_validation']={'machine_script_blocks':{machine:{
        'passed':True,'paragraph':stale,'word_count':8,'machine':machine,'scene':1,
        'machine_script_contract':fp.CONTRACT,'source_fingerprint':fingerprint,
        'review_context_version':fs.REVIEW_CONTEXT_VERSION-1,
        'subject_context':video['video_title'],'claim_map':[],'sources':[],'saved':True,
    }}}
    rejected={'passed':False,'paragraph':stale,'word_count':8,
              'warnings':['wrong type for carrier topic'],'claim_map':[],'sources':[],
              'review_context_version':fs.REVIEW_CONTEXT_VERSION,
              'subject_context':video['video_title']}
    reviewer=AsyncMock(return_value=rejected)
    corrected={**rejected,'passed':True,'paragraph':'HMS Majestic served in the carrier context.',
               'warnings':[],'word_count':7}
    writer.return_value=corrected
    monkeypatch.setattr(fs,'review_existing_factual_summary',reviewer)
    result=asyncio.run(fp.run_factual_script_hold(ex,'video',video,[machine]))
    assert result['status']=='completed'
    reviewer.assert_awaited_once()
    writer.assert_awaited_once()
    assert writer.await_args.kwargs['previous_summary']==rejected


def test_short_reviewed_draft_gets_one_length_attempt_per_source_and_title(state, monkeypatch):
    ex,video,machine,package,writer=state
    fingerprint=fp.source_fingerprint(machine,package)
    short={'passed':True,'paragraph':'HMS Argus served as an aircraft carrier.','word_count':8,
           'warnings':[],'claim_map':[],'sources':[],'machine':machine,'scene':1,
           'machine_script_contract':fp.CONTRACT,'source_fingerprint':fingerprint,
           'review_context_version':fs.REVIEW_CONTEXT_VERSION,
           'subject_context':video['video_title'],'saved':True}
    video['script_validation']={'machine_script_blocks':{machine:short}}
    expanded={**short,'paragraph':'Still concise but factually approved.','word_count':5}
    writer.return_value=expanded
    first=asyncio.run(fp.run_factual_script_hold(ex,'video',video,[machine]))
    assert first['status']=='completed'
    assert writer.await_count==1
    saved=video['script_validation']['machine_script_blocks'][machine]
    assert saved['length_target_attempted'] is True
    second=asyncio.run(fp.run_factual_script_hold(ex,'video',video,[machine]))
    assert second['status']=='completed'
    assert writer.await_count==1


def test_review_metadata_upgrade_preserves_existing_voice_when_prose_is_unchanged(state, monkeypatch):
    ex,video,machine,package,writer=state
    paragraph=' '.join(['supported']*80)
    fingerprint=fp.source_fingerprint(machine,package)
    video['script_validation']={'machine_script_blocks':{machine:{
        'passed':True,'paragraph':paragraph,'word_count':80,'machine':machine,'scene':1,
        'machine_script_contract':fp.CONTRACT,'source_fingerprint':fingerprint,
        'review_context_version':fs.REVIEW_CONTEXT_VERSION-1,
        'subject_context':video['video_title'],'claim_map':[],'sources':[],'saved':True,
    }}}
    reviewer=AsyncMock(return_value={
        'passed':True,'paragraph':paragraph,'word_count':80,'warnings':[],
        'claim_map':[],'sources':[],'review_context_version':fs.REVIEW_CONTEXT_VERSION,
        'subject_context':video['video_title'],
    })
    monkeypatch.setattr(fs,'review_existing_factual_summary',reviewer)
    pe.fetch_all.return_value=[{'scene':1,'scene_text':paragraph,'voice_id':'voice-1','voice_over_url':'saved.mp3','voice_status':'Done'}]

    async def persist(query,*args):
        if 'SET script_validation = $1' in query:
            video['script_validation']=json.loads(args[0])
        return 'UPDATE 1'

    monkeypatch.setattr(pe,'execute',AsyncMock(side_effect=persist))
    result=asyncio.run(fp.run_factual_script_hold(ex,'video',video,[machine]))
    assert result['status']=='completed'
    writer.assert_not_awaited()
    ex._save_machine_script_block.assert_not_awaited()
    assert video['script_validation']['machine_script_blocks'][machine]['review_context_version']==fs.REVIEW_CONTEXT_VERSION


def _install_source_packages(monkeypatch, video, machine, packages):
    key=pe._verified_source_cache_key(machine)
    video['research_payload']={
        'machine_script_contract':fp.CONTRACT,
        'machine_raw_source_packages':{key:packages['target'],'OTHER':packages['other']},
    }

    def package_for(payload, requested_machine):
        return (payload.get('machine_raw_source_packages') or {}).get(pe._verified_source_cache_key(requested_machine))

    monkeypatch.setattr(pe,'_verified_source_package_for_machine',package_for)
    monkeypatch.setattr(fs,'_eligible_candidates',lambda _machine,package,_context: {
        f'E{index}':{'source_url':url} for index,url in enumerate(package.get('typed_urls') or [],1)
    })
    return key


def test_old_single_typed_source_refreshes_before_writer_and_uses_new_fingerprint(state, monkeypatch):
    ex,video,machine,_package,writer=state
    video['video_title']='Every British Aircraft Carrier Class Ever Built'
    old={'search_queries':['HMS Argus history'],'typed_urls':['https://old.example/argus']}
    refreshed={'search_queries':['HMS Argus aircraft carrier history'],
               'typed_urls':['https://new.example/argus','https://archive.example/argus']}
    other={'machine':'Other','search_queries':['Other history']}
    key=_install_source_packages(monkeypatch,video,machine,{'target':old,'other':other})
    original_payload=video['research_payload']

    async def refresh(_video_id,title,payload,roster,target_machine=None):
        assert title==video['video_title']
        assert roster==[machine] and target_machine==machine
        assert payload is not original_payload
        assert key not in payload['machine_raw_source_packages']
        payload['machine_raw_source_packages'][key]=refreshed
        video['research_payload']=copy.deepcopy(payload)
        return payload

    ex._run_unit_research_hold=AsyncMock(side_effect=refresh)
    result=asyncio.run(fp.run_factual_script_hold(ex,'video',video,[machine]))
    assert result['status']=='completed'
    ex._run_unit_research_hold.assert_awaited_once()
    assert writer.await_args.args[1]==refreshed
    saved=video['script_validation']['machine_script_blocks'][machine]
    assert saved['source_fingerprint']==fp.source_fingerprint(machine,refreshed)


def test_already_carrier_scoped_thin_package_does_not_refresh_again(state, monkeypatch):
    ex,video,machine,_package,writer=state
    video['video_title']='Every British Aircraft Carrier Class Ever Built'
    scoped={'search_queries':['HMS Argus aircraft carrier history','HMS Argus aircraft carrier archives'],
            'typed_urls':['https://only.example/argus']}
    other={'machine':'Other'}
    _install_source_packages(monkeypatch,video,machine,{'target':scoped,'other':other})
    ex._run_unit_research_hold=AsyncMock()
    result=asyncio.run(fp.run_factual_script_hold(ex,'video',video,[machine]))
    assert result['status']=='completed'
    ex._run_unit_research_hold.assert_not_awaited()
    assert writer.await_args.args[1]==scoped


def test_source_refresh_copy_preserves_other_machine_package(state, monkeypatch):
    ex,video,machine,_package,_writer=state
    video['video_title']='Every British Aircraft Carrier Class Ever Built'
    old={'search_queries':['HMS Argus specifications'],'typed_urls':['https://old.example/argus']}
    refreshed={'search_queries':['HMS Argus aircraft carrier specifications'],
               'typed_urls':['https://new.example/argus','https://archive.example/argus']}
    other={'machine':'HMS Courageous','marker':'must survive'}
    key=_install_source_packages(monkeypatch,video,machine,{'target':old,'other':other})

    async def refresh(_video_id,_title,payload,_roster,target_machine=None):
        assert payload['machine_raw_source_packages']['OTHER']==other
        payload['machine_raw_source_packages'][key]=refreshed
        video['research_payload']=copy.deepcopy(payload)
        return payload

    ex._run_unit_research_hold=AsyncMock(side_effect=refresh)
    asyncio.run(fp.run_factual_script_hold(ex,'video',video,[machine]))
    assert video['research_payload']['machine_raw_source_packages']['OTHER']==other
