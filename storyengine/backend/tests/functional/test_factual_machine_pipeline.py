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
    ex.check_machine_script_preview_readiness=AsyncMock(return_value={'ready':True})
    ex.run_one_machine_research=AsyncMock(return_value={'status':'completed'})
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


def _enable_assessed_batch(monkeypatch, ex, video, machine, package):
    """Make the fixture an assessed factual package without provider work."""
    package['claim_assessment'] = {'status': 'assessed'}
    monkeypatch.setattr(fp, '_expected_script_packet', lambda *_args: {
        'compiler_version': 'test-compiler', 'packet_fingerprint': 'test-packet',
    })
    monkeypatch.setattr(fp, 'script_editorial_ready', lambda _block: True)
    monkeypatch.setattr(fp, 'factual_script_readiness', lambda _video, _roster: True)
    # The real compiled writer persists these cache-identity fields; retain
    # them in the isolated mock so the save readback stays meaningful.
    from factual_machine_summary import generate_factual_machine_summary
    generate_factual_machine_summary.return_value = {
        **generate_factual_machine_summary.return_value,
        'compiler_version': 'test-compiler', 'packet_fingerprint': 'test-packet',
    }
    ex.check_machine_script_preview_readiness = AsyncMock(return_value={'ready': True})
    ex.run_one_machine_research = AsyncMock(return_value={'status': 'completed'})


def test_assessed_batch_checks_ready_cache_without_writer_or_preparation(state, monkeypatch):
    ex, video, machine, package, writer = state
    _enable_assessed_batch(monkeypatch, ex, video, machine, package)
    video['script_validation'] = {'machine_script_blocks': {machine: {
        'passed': True, 'paragraph': ' '.join(['approved'] * 80), 'machine': machine,
        'scene': 1, 'machine_script_contract': fp.CONTRACT,
        'source_fingerprint': fp.source_fingerprint(machine, package),
        'review_context_version': fs.REVIEW_CONTEXT_VERSION,
        'subject_context': video['video_title'], 'compiler_version': 'test-compiler',
        'packet_fingerprint': 'test-packet', 'saved': True,
    }}}

    result = asyncio.run(fp.run_factual_script_hold(ex, 'video', video, [machine]))

    assert result['status'] == 'completed'
    ex.check_machine_script_preview_readiness.assert_awaited_once_with('video', machine)
    ex.run_one_machine_research.assert_not_awaited()
    writer.assert_not_awaited()


def test_assessed_batch_prepares_only_preparable_machine_then_writes(state, monkeypatch):
    ex, video, machine, package, writer = state
    _enable_assessed_batch(monkeypatch, ex, video, machine, package)
    ex.check_machine_script_preview_readiness.side_effect = [
        {'ready': False, 'preparable': True}, {'ready': True},
    ]

    result = asyncio.run(fp.run_factual_script_hold(ex, 'video', video, [machine]))

    assert result['status'] == 'completed'
    ex.run_one_machine_research.assert_awaited_once_with('video', machine)
    assert ex.check_machine_script_preview_readiness.await_count == 2
    writer.assert_awaited_once()


def test_assessed_batch_compiles_from_payload_reloaded_after_ready_preflight(state, monkeypatch):
    ex, video, machine, package, writer = state
    _enable_assessed_batch(monkeypatch, ex, video, machine, package)
    fresh_package = {**package, 'revision': 'fresh-after-readiness'}
    video['research_payload']['source_package'] = package
    monkeypatch.setattr(
        pe, '_verified_source_package_for_machine',
        lambda payload, _machine: payload['source_package'],
    )
    seen_packets = []

    def packet(_machine, source_package, *_args):
        seen_packets.append(source_package)
        return {'compiler_version': 'test-compiler', 'packet_fingerprint': 'test-packet'}

    monkeypatch.setattr(fp, '_expected_script_packet', packet)

    async def ready(*_args):
        video['research_payload']['source_package'] = fresh_package
        return {'ready': True}

    ex.check_machine_script_preview_readiness.side_effect = ready
    result = asyncio.run(fp.run_factual_script_hold(ex, 'video', video, [machine]))

    assert result['status'] == 'completed'
    assert seen_packets and seen_packets[-1]['revision'] == 'fresh-after-readiness'
    assert writer.await_args.args[1]['revision'] == 'fresh-after-readiness'


def test_assessed_batch_hard_readiness_failure_continues_without_writer(state, monkeypatch):
    ex, video, machine, package, writer = state
    _enable_assessed_batch(monkeypatch, ex, video, machine, package)
    ex.check_machine_script_preview_readiness.return_value = {
        'ready': False, 'preparable': False, 'summary': 'source identity is unresolved',
    }

    result = asyncio.run(fp.run_factual_script_hold(ex, 'video', video, [machine]))

    assert result['status'] == 'needs_review'
    assert machine in result['error']
    ex.run_one_machine_research.assert_not_awaited()
    writer.assert_not_awaited()


def test_assessed_batch_keeps_later_machine_after_one_hard_readiness_failure(state, monkeypatch):
    ex, video, machine, package, writer = state
    other = 'HMS Courageous'
    package['claim_assessment'] = {'status': 'assessed'}
    other_package = {'machine': other, 'candidate_excerpts': []}
    video['research_payload']['packages'] = {machine: package, other: other_package}
    monkeypatch.setattr(
        pe, '_verified_source_package_for_machine',
        lambda payload, requested: payload['packages'][requested],
    )
    monkeypatch.setattr(pe, '_machine_documentary_hold_roster', lambda _video: [machine, other])
    ex.check_machine_script_preview_readiness = AsyncMock(return_value={
        'ready': False, 'preparable': False, 'summary': 'source identity is unresolved',
    })

    async def save(**kwargs):
        block = {**kwargs['script_block'], 'saved': True}
        blocks = video['script_validation'].setdefault('machine_script_blocks', {})
        blocks[kwargs['script_block']['machine']] = block
        return block

    ex._save_machine_script_block = AsyncMock(side_effect=save)
    result = asyncio.run(fp.run_factual_script_hold(ex, 'video', video, [machine, other]))

    assert result['status'] == 'needs_review'
    assert machine in result['error']
    ex.check_machine_script_preview_readiness.assert_awaited_once_with('video', machine)
    assert writer.await_count == 1
    assert writer.await_args.args[0] == other
    assert other in video['script_validation']['machine_script_blocks']


def test_assessed_full_batch_reuses_a_prepares_only_b_and_skips_hard_blocked_c(state, monkeypatch):
    ex, video, machine, package, writer = state
    second, third = 'HMS Courageous', 'HMS Glorious'
    _enable_assessed_batch(monkeypatch, ex, video, machine, package)
    second_package = {'machine': second, 'candidate_excerpts': [], 'claim_assessment': {'status': 'assessed'}}
    third_package = {'machine': third, 'candidate_excerpts': [], 'claim_assessment': {'status': 'assessed'}}
    video['research_payload']['packages'] = {
        machine: package, second: second_package, third: third_package,
    }
    monkeypatch.setattr(
        pe, '_verified_source_package_for_machine',
        lambda payload, requested: payload['packages'][requested],
    )
    monkeypatch.setattr(pe, '_machine_documentary_hold_roster', lambda _video: [machine, second, third])
    cached_a = ' '.join(['cached-A'] * 80)
    video['script_validation'] = {'machine_script_blocks': {machine: {
        'passed': True, 'paragraph': cached_a, 'machine': machine, 'scene': 1,
        'machine_script_contract': fp.CONTRACT,
        'source_fingerprint': fp.source_fingerprint(machine, package),
        'review_context_version': fs.REVIEW_CONTEXT_VERSION,
        'subject_context': video['video_title'], 'compiler_version': 'test-compiler',
        'packet_fingerprint': 'test-packet', 'saved': True,
    }}}
    readiness = {
        machine: [{'ready': True}],
        second: [{'ready': False, 'preparable': True}, {'ready': True}],
        third: [{'ready': False, 'preparable': False, 'summary': 'source identity is unresolved'}],
    }

    async def check(_video_id, requested):
        return readiness[requested].pop(0)

    async def save(**kwargs):
        block = {**kwargs['script_block'], 'saved': True}
        video['script_validation'].setdefault('machine_script_blocks', {})[block['machine']] = block
        return block

    ex.check_machine_script_preview_readiness.side_effect = check
    ex._save_machine_script_block = AsyncMock(side_effect=save)
    result = asyncio.run(fp.run_factual_script_hold(ex, 'video', video, [machine, second, third]))

    assert result['status'] == 'needs_review'
    ex.run_one_machine_research.assert_awaited_once_with('video', second)
    assert writer.await_count == 1
    assert writer.await_args.args[0] == second
    assert video['script_validation']['machine_script_blocks'][machine]['paragraph'] == cached_a
    assert third in result['error']


def test_assessed_batch_post_preparation_gate_blocks_writer(state, monkeypatch):
    ex, video, machine, package, writer = state
    _enable_assessed_batch(monkeypatch, ex, video, machine, package)
    ex.check_machine_script_preview_readiness.side_effect = [
        {'ready': False, 'preparable': True},
        {'ready': False, 'preparable': False, 'summary': 'summary remains stale'},
    ]

    result = asyncio.run(fp.run_factual_script_hold(ex, 'video', video, [machine]))

    assert result['status'] == 'needs_review'
    ex.run_one_machine_research.assert_awaited_once_with('video', machine)
    writer.assert_not_awaited()


@pytest.mark.parametrize(
    ('prepared', 'mutate', 'expected'),
    [
        ({'status': 'cancelled'}, None, 'cancelled'),
        ({'status': 'paused'}, None, 'paused'),
        ({'status': 'completed'}, lambda video, machine: video.update({'max_spend': 0}), 'paused'),
    ],
)
def test_assessed_batch_stops_after_preparation_on_cancel_or_budget(state, monkeypatch, prepared, mutate, expected):
    ex, video, machine, package, writer = state
    _enable_assessed_batch(monkeypatch, ex, video, machine, package)
    ex.check_machine_script_preview_readiness.side_effect = [
        {'ready': False, 'preparable': True}, {'ready': True},
    ]

    async def prepare(*_args):
        if mutate:
            mutate(video, machine)
        return prepared

    ex.run_one_machine_research.side_effect = prepare
    result = asyncio.run(fp.run_factual_script_hold(ex, 'video', video, [machine]))

    assert result['status'] == expected
    writer.assert_not_awaited()


def test_assessed_batch_stops_when_roster_drifts_during_preparation(state, monkeypatch):
    ex, video, machine, package, writer = state
    _enable_assessed_batch(monkeypatch, ex, video, machine, package)
    monkeypatch.setattr(
        pe, '_machine_documentary_hold_roster',
        lambda row: ['Other machine'] if row.get('drift') else [machine],
    )
    ex.check_machine_script_preview_readiness.side_effect = [
        {'ready': False, 'preparable': True}, {'ready': True},
    ]

    async def prepare(*_args):
        video['drift'] = True
        return {'status': 'completed'}

    ex.run_one_machine_research.side_effect = prepare
    result = asyncio.run(fp.run_factual_script_hold(ex, 'video', video, [machine]))

    assert result['status'] == 'failed'
    assert 'roster changed' in result['error']
    writer.assert_not_awaited()
