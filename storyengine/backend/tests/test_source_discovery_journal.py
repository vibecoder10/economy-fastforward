import copy
import json
import pytest
import source_discovery_journal as journal

@pytest.mark.asyncio
async def test_revision_compare_and_swap_blocks_duplicate_submission(monkeypatch):
    store = {'state': {}, 'revision': 0}
    async def query(sql, *args):
        assert 'tenant_id' in sql and 'video_id' in sql
        if sql.startswith('INSERT'):
            return copy.deepcopy(store)
        if args[4] != store['revision']: return None
        store.update(state=json.loads(args[3]), revision=store['revision'] + 1)
        return {'revision': store['revision']}
    monkeypatch.setattr(journal, 'fetch_one', query)
    first = await journal.SourceDiscoveryJournal.open('tenant','video','S1','Title',{})
    duplicate = await journal.SourceDiscoveryJournal.open('tenant','video','S1','Title',{})
    await first.checkpoint({'status':'submitted','attempts':1})
    with pytest.raises(RuntimeError, match='checkpoint conflict'):
        await duplicate.checkpoint({'status':'submitted','attempts':1})
    resumed = await journal.SourceDiscoveryJournal.open('tenant','video','S1','Title',{})
    assert resumed.state['status'] == 'submitted' and resumed.state['attempts'] == 1
    assert resumed.state['operation_id'] == first.operation_id


def test_operation_identity_is_tenant_video_machine_and_request_specific():
    base=['tenant','video','S1','Title',{'missing_fields':['design']}]
    keys={journal.operation_key(*base)}
    for index in range(4):
        other=base.copy();other[index]+='changed';keys.add(journal.operation_key(*other))
    other=base.copy();other[4]={'missing_fields':['actual_use']};keys.add(journal.operation_key(*other))
    assert len(keys)==6


@pytest.mark.asyncio
async def test_received_usage_is_reconciled_before_another_submission(monkeypatch):
    recorded = []
    async def query(sql, *args):
        if 'WITH added AS' in sql:
            recorded.append(args)
            return {'total_cost': 0.01}
        return {'revision': 1}
    monkeypatch.setattr(journal, 'fetch_one', query)
    op = journal.SourceDiscoveryJournal('tenant','video','op',{},0)
    await op.checkpoint({'status':'received','receipts':[{'request_id':'one','credits_consumed':1}],
                         'receipt':{'request_id':'two','credits_consumed':2}})
    assert [row[-1] for row in recorded] == ['one','two']
    assert all(row[:2] == ('tenant','video') for row in recorded)

@pytest.mark.asyncio
async def test_usage_checkpoint_failure_prevents_next_provider_call(monkeypatch):
    import factual_source_search as search
    from unittest.mock import AsyncMock
    from types import SimpleNamespace
    async def query(sql, *args):
        if 'WITH added AS' in sql: raise RuntimeError('database unavailable')
        return {'revision': 1}
    monkeypatch.setattr(journal, 'fetch_one', query)
    op = journal.SourceDiscoveryJournal('tenant','video','op',{},0)
    response=SimpleNamespace(status_code=200,json=lambda:{'id':'charged','credits_consumed':1,'choices':[{'message':{'content':'invalid'}}]})
    client=SimpleNamespace(post=AsyncMock(return_value=response))
    with pytest.raises(search.SourceDiscoveryError,match='checkpoint'):
        await search.discover_sources(client,'test','title','machine',operation_state=op.state,
            checkpoint=op.checkpoint,guard=AsyncMock(return_value=True))
    assert client.post.await_count == 1
