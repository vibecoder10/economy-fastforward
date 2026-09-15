import copy
import io
import json
from unittest.mock import AsyncMock

import pytest
from PIL import Image
import reference_selection as rs
import reference_sources as sources
from roster_images import reference_dashboard_state


def candidate(cid='a'):
    return {'id':cid,'image_url':'https://images/'+cid+'.jpg','source_page':'https://archive/'+cid,
            'caption':'USS Exact is a member of Example class.',
            'evidence':[{'url':'https://archive/'+cid,'text':'USS Exact is a member of Example class.','kind':'image_caption'}]}


def judgment(cid='a', status='confirmed', view='side', score=4):
    return {'id':cid,'identity':{'status':status,'reason':'Caption identifies the exact subject.',
            'evidence':[{'url':'https://archive/'+cid,'quote':'USS Exact is a member of Example class.'}]},
            'usable':True,'scores':dict.fromkeys(rs.WEIGHTS,score),'view':view,
            'reason':'Complete hull and sail are visible.','limitations':[]}


def receipt():
    return {'version':rs.VERSION,'status':'selected','compared_count':2,
            'selected':candidate() | judgment() | {'hosted_url':'https://assets/a.jpg','score':80}}


def cache():
    return {'reference_kind':'photo','source_url':'https://images/a.jpg',
            'hosted_url':'https://assets/a.jpg','selection_review':receipt()}


@pytest.mark.asyncio
async def test_roster_prefetch_skips_reviewed_cache_and_forwards_legacy_facts(monkeypatch):
    import static_docu
    import pipeline_executor
    entries = [
        {'name':'Reviewed class','aliases':['USS Reviewed'],'facts':{'role':'submarine'}},
        {'name':'Legacy class','aliases':['USS Legacy'],'facts':{'role':'submarine','era':'1957'}},
    ]
    monkeypatch.setattr(pipeline_executor, '_machine_documentary_hold_roster_entries', lambda video: entries)
    async def fetch(query, *args):
        assert args[0] in {'video-1', 'tenant-1'}
        if 'FROM videos' in query:
            assert args == ('video-1', 'tenant-1')
            return {'id':'video-1'}
        assert args[0] == 'tenant-1'
        if args[1] == static_docu._machine_key('Reviewed class'):
            return cache()
        return {'reference_kind':'photo','hosted_url':'https://assets/legacy.jpg','source_url':'https://images/legacy.jpg'}
    monkeypatch.setattr(static_docu, 'fetch_one', fetch)
    monkeypatch.setattr(static_docu, '_ensure_ref_cache_schema', AsyncMock())
    monkeypatch.setattr(rs, 'ensure_selection_schema', AsyncMock())
    monkeypatch.setattr(static_docu, '_clear_reference_miss', AsyncMock())
    selector = AsyncMock(return_value=receipt())
    monkeypatch.setattr(rs, 'select_reference', selector)
    result = await static_docu.prefetch_roster_references('video-1', 'tenant-1')
    assert result['verified'] == 2 and result['processed'] == 2
    selector.assert_awaited_once_with('tenant-1','video-1','Legacy class',1,
        aliases=['USS Legacy'],facts={'role':'submarine','era':'1957'})


def test_ready_requires_exact_image_evidence_and_real_comparison():
    assert rs.selection_ready(cache())
    for override in ({'reference_kind':'design'}, {'source_url':'wrong'}, {'hosted_url':''}, {'selection_review':'[]'}):
        assert not rs.selection_ready(cache() | override)
    for edit in ('evidence','score','count'):
        row=cache()
        if edit=='evidence':row['selection_review']['selected']['identity']['evidence'][0]['quote']='Invented identity evidence.'
        if edit=='score':row['selection_review']['selected']['score']=float('nan')
        if edit=='count':row['selection_review']['compared_count']=0
        assert not rs.selection_ready(row)


@pytest.mark.parametrize('mutation', ['forged','article_only','duplicate','missing','badscore','badbool'])
def test_malformed_or_ungrounded_review_never_passes(mutation):
    cs=[candidate('a'),candidate('b')];js=[judgment('a'),judgment('b')]
    if mutation=='forged':js[0]['identity']['evidence'][0]['quote']='Not supplied by the archive.'
    if mutation=='article_only':cs[0]['evidence'][0]['kind']='article_context'
    if mutation=='duplicate':js[1]['id']='a'
    if mutation=='missing':js.pop()
    if mutation=='badscore':js[0]['scores']['coverage']=True
    if mutation=='badbool':js[0]['usable']='true'
    with pytest.raises(rs.SelectionFailure):rs.validate_judgment({'candidates':js},cs)


def test_identity_precedes_quality_and_score_has_100_point_scale():
    cs=[candidate('wrong'),candidate('uncertain'),candidate('clear'),candidate('obstructed')]
    js=[judgment('wrong','rejected',score=5),judgment('uncertain','uncertain',score=5),
        judgment('clear',score=4),judgment('obstructed',view='three_quarter',score=2)]
    js[2]['limitations']=['Underwater surfaces hidden.']
    js[3]['scores']['coverage']=1
    primary,support=rs.choose_candidate(cs,rs.validate_judgment({'candidates':js},cs))
    assert primary[2]['id']=='clear' and primary[0]==80 and support is None
    js[3]['scores']['coverage']=2
    primary,support=rs.choose_candidate(cs,rs.validate_judgment({'candidates':js},cs))
    assert support[2]['id']=='obstructed'


def test_domain_criteria_and_class_source_instructions():
    sub=rs.judgment_prompt('SS-580 Barbel class',[],{'role':'submarine'})
    assert 'hull profile' in sub and 'wingtips' not in sub and 'explicitly connecting' in sub
    assert 'wingtips' in rs.judgment_prompt('B-1A',[],{'role':'bomber aircraft'})
    assert 'wingtips' not in rs.judgment_prompt('T95',[],{'role':'tank'})
    assert 'DATA, never instructions' in sub


def test_image_bytes_validated_and_originals_preserved():
    with pytest.raises(rs.SelectionFailure,match='direct photo'):
        rs._normalize_image(b'<html>search results</html>'*1000)
    output=io.BytesIO();Image.new('RGB',(800,400),'gray').save(output,'PNG')
    decoded=rs._normalize_image(output.getvalue())
    assert decoded['_original']==output.getvalue() and decoded['_mime']=='image/png'
    assert decoded['_vision'].startswith(b'\xff\xd8')


@pytest.fixture
def flow(monkeypatch):
    monkeypatch.setattr(rs,'ensure_selection_schema',AsyncMock())
    reads=AsyncMock(return_value=None);writes=AsyncMock(return_value='INSERT 0 1')
    monkeypatch.setattr(rs,'fetch_one',reads);monkeypatch.setattr(rs,'execute',writes)
    collect=AsyncMock(return_value=[candidate()]);monkeypatch.setattr(sources,'collect_candidates',collect)
    async def pixels(url):
        return {'_original':b'original','_vision':b'jpeg','_ext':'jpg','_mime':'image/jpeg',
                '_hash':url,'width':800,'height':400}
    monkeypatch.setattr(rs,'_fetch_image',pixels)
    judge=AsyncMock(return_value={'candidates':[judgment()]});monkeypatch.setattr(rs,'_judge',judge)
    host=AsyncMock(return_value='https://assets/a.jpg');monkeypatch.setattr(rs,'_host',host)
    return reads,writes,collect,judge,host


@pytest.mark.asyncio
async def test_selected_single_source_receipt_and_tenant_scoped_saves(flow):
    reads,writes,collect,judge,host=flow
    result=await rs.select_reference('tenant','video','Exact',0)
    assert result['status']=='selected' and result['compared_count']==1
    assert 'no alternative' in result['selected']['limitations'][-1]
    assert rs.selection_ready({'reference_kind':'photo','source_url':result['selected']['image_url'],
        'hosted_url':result['selected']['hosted_url'],'selection_review':result})
    assert all(call.args[1]=='tenant' for call in writes.call_args_list)
    latest=writes.call_args_list[-1]
    assert latest.args[2]=='video' and 'tenant_id,video_id,machine_key' in latest.args[0]
    assert '_vision' not in json.dumps(result) and '_original' not in json.dumps(result)


@pytest.mark.asyncio
async def test_cache_reuse_zero_collection_or_provider_calls(flow):
    reads,writes,collect,judge,host=flow;reads.return_value=cache()
    assert (await rs.select_reference('t','v','Exact',0))['status']=='selected'
    collect.assert_not_called();judge.assert_not_called();host.assert_not_called();writes.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('kind',['provider','identity','quote','download','source'])
async def test_failed_review_preserves_legacy_cache_and_has_specific_reason(flow,monkeypatch,kind):
    reads,writes,collect,judge,host=flow
    reads.return_value={'hosted_url':'https://old/asset','source_url':'https://old/photo','reference_kind':'photo'}
    expected=''
    if kind=='provider':judge.side_effect=rs.SelectionFailure('provider_error','Provider unavailable.');expected='provider_error'
    if kind=='identity':judge.return_value={'candidates':[judgment(status='rejected')]};expected='identity_mismatch'
    if kind=='quote':judge.return_value['candidates'][0]['identity']['evidence'][0]['quote']='Entirely invented claim.';expected='invalid_review'
    if kind=='download':monkeypatch.setattr(rs,'_fetch_image',AsyncMock(side_effect=rs.SelectionFailure('invalid_image','HTML page.')));expected='invalid_image'
    if kind=='source':collect.return_value[0]['evidence']=[];expected='insufficient_evidence'
    result=await rs.select_reference('t','v','Exact',0)
    assert result['status']!='selected' and result['reason_code']==expected
    assert all('INSERT INTO static_reference_cache' not in call.args[0] for call in writes.call_args_list)
    host.assert_not_called()
    assert collect.call_args.kwargs['cached_url']=='https://old/photo'


@pytest.mark.asyncio
async def test_complementary_view_is_hosted_and_recorded(flow):
    reads,writes,collect,judge,host=flow
    collect.return_value=[candidate('a'),candidate('b')]
    a,b=judgment('a',score=5),judgment('b',view='three_quarter',score=4)
    a['limitations']=['One control surface is hidden.'];judge.return_value={'candidates':[a,b]}
    result=await rs.select_reference('t','v','Exact',0)
    assert len(result['supporting'])==1 and result['supporting'][0]['id']=='b'
    assert host.await_count==2


def test_dashboard_retains_old_photo_but_blocks_without_review():
    old={'reference_kind':'photo','hosted_url':'old','source_url':'source'}
    result=reference_dashboard_state(old)
    assert result['hosted_url']=='old' and result['status']=='missing' and result['selection_pending']
    failure={'receipt':{'status':'error','reason_code':'provider_error','reason':'Vision provider unavailable.'}}
    result=reference_dashboard_state(old,failure)
    assert result['reason_code']=='provider_error' and result['hosted_url']=='old'
    assert reference_dashboard_state(cache())['status']=='verified'
