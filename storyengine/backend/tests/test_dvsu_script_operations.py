import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
import dvsu_script_operations as ops

@pytest.fixture
def env(monkeypatch):
    rows={}
    async def query(sql,*args):
        key=args[:3]
        if sql.startswith('SELECT'): return copy.deepcopy(rows.get(key))
        if sql.startswith('INSERT'):
            if key in rows: return None
            rows[key]={'status':'submitted','response':None}
            return {'operation_id':args[2]}
        if sql.startswith('UPDATE'):
            rows[key]={'status':'received','response':args[3]}
            return {'operation_id':args[2]}
        raise AssertionError(sql)
    monkeypatch.setattr(ops,'fetch_one',query)
    client=SimpleNamespace(generate=AsyncMock(return_value='{"paragraph":"saved raw response"}'))
    guard=AsyncMock(return_value=True)
    def proxy(tenant='tenant',fingerprint='fp'):
        return ops.DurableScriptClient(client,tenant,'video','S1',fingerprint,guard)
    return rows,client,guard,proxy

@pytest.mark.asyncio
async def test_completed_response_replayed_before_any_parse_or_provider(env):
    rows,client,guard,proxy=env
    first=await proxy().generate(prompt='writer',max_tokens=900)
    assert await proxy().generate(prompt='writer',max_tokens=900)==first
    client.generate.assert_awaited_once_with(prompt='writer',max_tokens=900,no_resubmit=True)
    assert guard.await_count==1
    assert len(rows)==1

@pytest.mark.asyncio
async def test_uncertain_submission_never_repeated_on_restart(env):
    rows,client,guard,proxy=env
    client.generate.side_effect=TimeoutError('uncertain')
    for _ in range(2):
        with pytest.raises(ops.ScriptOperationError) as e:
            await proxy().generate(prompt='writer')
        assert e.value.next_action=='reconcile' and e.value.stage=='script'
    assert client.generate.await_count==1
    assert list(rows.values())[0]['status']=='submitted'

@pytest.mark.asyncio
async def test_guard_and_tenant_input_identity(env):
    rows,client,guard,proxy=env
    guard.return_value=False
    with pytest.raises(ops.ScriptOperationError): await proxy().generate(prompt='writer')
    assert not rows and client.generate.await_count==0
    guard.return_value=True
    await proxy().generate(prompt='writer')
    await proxy(tenant='other').generate(prompt='writer')
    await proxy(fingerprint='changed').generate(prompt='writer')
    assert len(rows)==3 and client.generate.await_count==3

@pytest.mark.asyncio
@pytest.mark.parametrize("db_raises", [False, True])
async def test_failed_response_save_keeps_submitted_uncertain(monkeypatch, db_raises):
    calls=[]
    async def query(sql,*args):
        calls.append(sql)
        if sql.startswith('SELECT'): return None
        if sql.startswith('INSERT'): return {'operation_id':'key'}
        if db_raises: raise RuntimeError('database unavailable after paid response')
        return None
    monkeypatch.setattr(ops,'fetch_one',query)
    client=SimpleNamespace(generate=AsyncMock(return_value='paid response'))
    with pytest.raises(ops.ScriptOperationError,match='checkpointed'):
        await ops.DurableScriptClient(client,'t','v','S1','fp',AsyncMock(return_value=True)).generate(prompt='x')
    assert client.generate.await_count==1
