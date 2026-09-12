"""Provider stops preserve the tenant's list and only explicit recovery resumes it."""
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from queue_controls import provider_blocker, sync_provider_pause
from routes import queue


@pytest.mark.parametrize('error,provider', [
    ('Your credit balance is too low to access the Anthropic API.', 'Anthropic'),
    ('Anthropic/Claude key is out of credits; retry after adding funds', 'Anthropic'),
    ('ElevenLabs quota_exceeded', 'ElevenLabs'),
    ('Kie: insufficient credits', 'Kie'),
    ('authentication_error: invalid api key for Anthropic', 'Anthropic'),
    ('Google refresh token revoked: invalid_grant', 'YouTube'),
])
def test_shared_account_failures_are_classified(error, provider):
    assert provider_blocker(error)['provider'] == provider


@pytest.mark.parametrize('error', [
    'Roster coverage incomplete', 'Reference image has no verified source',
    'Anthropic 429 rate limit exceeded', 'connection timeout, please retry',
    'Weekly budget cap reached', 'YouTube daily quota limit reached',
])
def test_quality_transient_and_budget_failures_do_not_latch_provider_pause(error):
    assert provider_blocker(error) is None


@pytest.mark.asyncio
async def test_pause_survives_deletion_of_failed_queue_row():
    saved = None
    failures = [{'id': 'blocked-1', 'last_error': 'Anthropic credit balance is too low'}]
    class Conn:
        async def fetchrow(self, query, *args):
            nonlocal saved
            if query.startswith('SELECT'):
                return saved
            saved = {'tenant_id': args[0], 'paused': True, 'provider': args[1],
                     'reason': args[2], 'blocking_queue_id': args[3]}
            return saved
        async def fetch(self, query, *args):
            return failures
    conn = Conn()
    first = await sync_provider_pause(conn, 'tenant-1')
    failures.clear()
    second = await sync_provider_pause(conn, 'tenant-1')
    assert first == second and second['paused'] is True


@pytest.mark.asyncio
async def test_paused_claim_never_selects_a_candidate(monkeypatch):
    candidate = AsyncMock()
    class Conn:
        execute = AsyncMock()
        fetchrow = candidate
        def transaction(self): return self
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
    class Pool:
        def acquire(self): return Conn()
    monkeypatch.setattr(queue, 'get_pool', AsyncMock(return_value=Pool()))
    monkeypatch.setattr(queue, 'sync_provider_pause', AsyncMock(return_value={'paused': True}))
    assert await queue._claim_next('tenant-1') is None
    assert await queue._claim_item('tenant-1', 'item-1') is None
    candidate.assert_not_awaited()


@pytest.mark.asyncio
async def test_scheduler_reports_pause_before_dispatch_or_candidate_fallback(monkeypatch):
    monkeypatch.setattr(queue, '_reconcile_queue_items', AsyncMock())
    monkeypatch.setattr(queue, 'get_queue_pause', AsyncMock(return_value={'paused': True, 'reason': 'Add credits'}))
    claim = AsyncMock()
    monkeypatch.setattr(queue, '_claim_next', claim)
    result = await queue.auto_produce_next('tenant-1', arq_pool=object())
    assert result['status'] == 'paused'
    claim.assert_not_awaited()


@pytest.mark.asyncio
async def test_intake_still_saves_titles_but_never_claims_running_when_paused(monkeypatch):
    add = AsyncMock(return_value=2)
    monkeypatch.setattr(queue, 'add_queue_items', add)
    monkeypatch.setattr(queue, 'auto_produce_next', AsyncMock(return_value={
        'status': 'paused', 'message': 'Add credits', 'pause': {'paused': True}}))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(arq=object())))
    result = await queue.add_to_queue(queue.QueueAddRequest(items=[{'title':'one'}, {'title':'two'}],continuous=True), request, 'tenant-1')
    assert result['count'] == 2 and result['pause']['paused']
    assert 'launch' not in result
    assert result['message'] == 'Titles saved. Add credits'


@pytest.mark.asyncio
async def test_individual_retry_cannot_bypass_shared_pause(monkeypatch):
    monkeypatch.setattr(queue, 'get_queue_pause', AsyncMock(return_value={'paused': True}))
    mutation = AsyncMock()
    monkeypatch.setattr(queue, 'fetch_one', mutation)
    with pytest.raises(HTTPException) as error:
        await queue.patch_queue_item('item', queue.QueuePatch(status='queued'), 'tenant-1')
    assert error.value.status_code == 409
    mutation.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_worker_cannot_clear_pause(monkeypatch):
    resume = AsyncMock()
    monkeypatch.setattr(queue, '_resume_saved_item', resume)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(arq=None)))
    with pytest.raises(HTTPException) as error:
        await queue.resume_queue(request, 'tenant-1')
    assert error.value.status_code == 503
    resume.assert_not_awaited()


@pytest.mark.asyncio
async def test_resume_dispatches_the_reserved_saved_item(monkeypatch):
    item = {'id':'item', 'video_id':'saved-video', 'title':'Existing title'}
    monkeypatch.setattr(queue, '_reconcile_queue_items', AsyncMock())
    monkeypatch.setattr(queue, '_resume_saved_item', AsyncMock(return_value=item))
    monkeypatch.setattr(queue, 'get_queue_pause', AsyncMock(return_value={'paused': False}))
    monkeypatch.setattr('drain_mode.assert_accepting_new_work', AsyncMock())
    dispatch = AsyncMock(return_value={'status':'launched','video_id':'saved-video'})
    monkeypatch.setattr(queue, 'launch_queue_item', dispatch)
    pool = object()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(arq=pool)))
    result = await queue.resume_queue(request, 'tenant-1')
    dispatch.assert_awaited_once_with('tenant-1', item, arq_pool=pool)
    assert result['launch']['video_id'] == 'saved-video'


@pytest.mark.asyncio
async def test_shared_pause_blocks_autopilot_candidate_fallback(monkeypatch):
    import main, autopilot_dial, autopilot_launch
    monkeypatch.setattr(main, '_is_autopilot_enabled', AsyncMock(return_value=True))
    monkeypatch.setattr(autopilot_dial, 'get_autopilot_dial', AsyncMock(return_value=SimpleNamespace(
        kill_switch_tripped_at=None, dial_level='full_auto', weekly_budget_cap=100)))
    monkeypatch.setattr(autopilot_dial, 'check_weekly_budget', AsyncMock(return_value=(True,0,100)))
    monkeypatch.setattr(queue, 'auto_produce_next', AsyncMock(return_value={'status':'paused'}))
    candidate = AsyncMock()
    monkeypatch.setattr(autopilot_launch, 'auto_launch_best_candidate', candidate)
    result = await main._produce_for_tenant('tenant-1', arq_pool=object())
    assert result['status'] == 'paused'
    candidate.assert_not_awaited()
