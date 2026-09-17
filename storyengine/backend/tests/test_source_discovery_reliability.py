"""Durable, offline contracts for the Kie factual-source adapter."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

import factual_source_search as search


def _response(content, status=200, **extra):
    data = {"id": "receipt-1", "credits_consumed": 0.1,
            "choices": [{"message": {"content": content}}]}
    data.update(extra)
    return httpx.Response(status, json=data)


def _hooks(saved):
    async def checkpoint(snapshot):
        saved.append(snapshot)
        return True

    async def guard(_snapshot):
        return True

    return checkpoint, guard


def test_checkpointed_response_restarts_by_parsing_locally_without_resubmit():
    state = {"status": "received", "attempts": 1,
             "receipt": {"request_id": "old", "credits_consumed": 0.1, "usage": {"x": 1}, "body_truncated": False},
             "response_content": json.dumps([{"title": "Archive", "exact_source_url": "https://archive.example/page"}])}
    saved = []
    checkpoint, guard = _hooks(saved)
    client = SimpleNamespace(post=AsyncMock())

    leads, receipt = asyncio.run(search.discover_sources(client, "secret", "Title", "Machine", operation_state=state,
                                                          checkpoint=checkpoint, guard=guard))

    assert [lead["url"] for lead in leads] == ["https://archive.example/page"]
    assert receipt["request_id"] == "old"
    assert state["status"] == "completed" and client.post.await_count == 0
    assert [snapshot["status"] for snapshot in saved[-2:]] == ["parsed", "completed"]


def test_submitted_restart_requires_reconciliation_without_call():
    state = {"status": "submitted", "attempts": 1}
    client = SimpleNamespace(post=AsyncMock())
    checkpoint, guard = _hooks([])
    with pytest.raises(search.SourceDiscoveryError) as raised:
        asyncio.run(search.discover_sources(client, "secret", "Title", "Machine", operation_state=state,
                                             checkpoint=checkpoint, guard=guard))
    assert raised.value.code == "reconciliation_required"
    assert raised.value.next_action == "reconcile" and client.post.await_count == 0


def test_failed_checkpoint_prevents_provider_call():
    async def checkpoint(_state):
        return False

    async def guard(_state):
        return True

    client = SimpleNamespace(post=AsyncMock())
    with pytest.raises(search.SourceDiscoveryError) as raised:
        asyncio.run(search.discover_sources(client, "secret", "Title", "Machine", operation_state={},
                                             checkpoint=checkpoint, guard=guard))
    assert raised.value.code == "checkpoint" and client.post.await_count == 0


def test_durable_transient_retries_are_checkpointed_and_limited_to_three_calls():
    saved = []
    checkpoint, guard = _hooks(saved)
    client = SimpleNamespace(post=AsyncMock(side_effect=[
        _response("", 503), _response("", 429),
        _response(json.dumps([{"title": "Archive", "exact_source_url": "https://archive.example/page"}])),
    ]))
    state = {}
    leads, receipt = asyncio.run(search.discover_sources(client, "secret", "Title", "Machine", operation_state=state,
                                                          checkpoint=checkpoint, guard=guard))
    assert len(leads) == 1 and receipt["operation"]["attempts"] == 3
    assert state["transient_attempts"] == 2 and client.post.await_count == 3
    assert "submitted" in [snapshot["status"] for snapshot in saved]


def test_one_malformed_retry_then_typed_failure_and_no_unsafe_prose_urls():
    saved = []
    checkpoint, guard = _hooks(saved)
    client = SimpleNamespace(post=AsyncMock(side_effect=[
        _response("Here is https://archive.example/not-json"),
        _response("not json again"),
    ]))
    with pytest.raises(search.SourceDiscoveryError) as raised:
        asyncio.run(search.discover_sources(client, "secret", "Title", "Machine", operation_state={},
                                             checkpoint=checkpoint, guard=guard))
    assert raised.value.code == "malformed"
    assert raised.value.retryable is False and raised.value.next_action == "review" and raised.value.attempts == 2
    assert client.post.await_count == 2


def test_transport_after_submission_is_reconciliation_not_retry():
    saved = []
    checkpoint, guard = _hooks(saved)
    client = SimpleNamespace(post=AsyncMock(side_effect=httpx.ReadTimeout("late")))
    state = {}
    with pytest.raises(search.SourceDiscoveryError) as raised:
        asyncio.run(search.discover_sources(client, "secret", "Title", "Machine", operation_state=state,
                                             checkpoint=checkpoint, guard=guard))
    assert raised.value.code == "transport_uncertain"
    assert state["status"] == "reconciliation_required" and client.post.await_count == 1


def test_preconnect_failure_can_retry_without_reconciliation():
    saved = []
    checkpoint, guard = _hooks(saved)
    client = SimpleNamespace(post=AsyncMock(side_effect=[
        httpx.ConnectError("not connected"),
        _response(json.dumps([{"title": "Archive", "exact_source_url": "https://archive.example/page"}])),
    ]))
    state = {}
    leads, _receipt = asyncio.run(search.discover_sources(client, "secret", "Title", "Machine", operation_state=state,
                                                           checkpoint=checkpoint, guard=guard))
    assert len(leads) == 1 and client.post.await_count == 2
    assert state["transient_attempts"] == 1 and state["status"] == "completed"


@pytest.mark.parametrize("status, code", [(401, "account_auth"), (402, "account_credits")])
def test_received_account_failure_replays_without_http(status, code):
    state = {"status": "received", "attempts": 1,
             "receipt": {"status_code": status, "provider_code": None, "provider_message": "", "body": "", "body_truncated": False}}
    saved = []
    checkpoint, guard = _hooks(saved)
    client = SimpleNamespace(post=AsyncMock())
    with pytest.raises(search.SourceDiscoveryError) as raised:
        asyncio.run(search.discover_sources(client, "secret", "Title", "Machine", operation_state=state,
                                             checkpoint=checkpoint, guard=guard))
    assert raised.value.code == code and raised.value.retryable is False
    assert state["status"] == "error" and client.post.await_count == 0


def test_received_transient_replays_once_with_prior_receipt_history():
    state = {"status": "received", "attempts": 1, "transient_attempts": 0,
             "receipt": {"status_code": 429, "provider_code": None, "provider_message": "", "body": "", "body_truncated": False, "credits_consumed": 0.2},
             "receipts": [{"status_code": 429, "credits_consumed": 0.2}]}
    saved = []
    checkpoint, guard = _hooks(saved)
    client = SimpleNamespace(post=AsyncMock(return_value=_response(json.dumps([
        {"title": "Archive", "exact_source_url": "https://archive.example/page"}
    ]))))
    _leads, receipt = asyncio.run(search.discover_sources(client, "secret", "Title", "Machine", operation_state=state,
                                                           checkpoint=checkpoint, guard=guard))
    assert client.post.await_count == 1 and receipt["operation"]["attempts"] == 2
    assert [item["status_code"] for item in receipt["operation"]["receipts"]] == [429, 200]


def test_parsed_state_returns_saved_leads_without_http():
    state = {"status": "parsed", "attempts": 1, "leads": [{"url": "https://archive.example/page", "title": "Archive"}],
             "metadata": {"request_id": "saved"}}
    checkpoint, guard = _hooks([])
    client = SimpleNamespace(post=AsyncMock())
    leads, receipt = asyncio.run(search.discover_sources(client, "secret", "Title", "Machine", operation_state=state,
                                                          checkpoint=checkpoint, guard=guard))
    assert leads == state["leads"] and receipt["request_id"] == "saved"
    assert state["status"] == "completed" and client.post.await_count == 0


def test_malformed_retry_limit_replays_terminal_error_without_third_call():
    state = {"status": "received", "attempts": 2, "malformed_attempts": 1,
             "receipt": {"status_code": 200, "body": "still not json", "body_truncated": False}}
    checkpoint, guard = _hooks([])
    client = SimpleNamespace(post=AsyncMock())
    with pytest.raises(search.SourceDiscoveryError) as raised:
        asyncio.run(search.discover_sources(client, "secret", "Title", "Machine", operation_state=state,
                                             checkpoint=checkpoint, guard=guard))
    assert raised.value.code == "malformed" and state["status"] == "error"
    assert client.post.await_count == 0


def test_truncated_response_is_replayable_and_never_stores_key():
    saved = []
    checkpoint, guard = _hooks(saved)
    client = SimpleNamespace(post=AsyncMock(return_value=_response("[" + "x" * 24_100)))
    state = {}
    with pytest.raises(search.SourceDiscoveryError) as raised:
        asyncio.run(search.discover_sources(client, "super-secret-key", "Title", "Machine", operation_state=state,
                                             checkpoint=checkpoint, guard=guard))
    assert raised.value.code == "truncated" and state["status"] == "error"
    assert all("super-secret-key" not in json.dumps(snapshot) for snapshot in saved)


def test_length_finish_reason_is_truncated_and_receipt_describes_shape():
    saved = []
    checkpoint, guard = _hooks(saved)
    client = SimpleNamespace(post=AsyncMock(return_value=httpx.Response(200, json={
        "id": "receipt-1", "credits_consumed": 0.1,
        "choices": [{"finish_reason": "length", "message": {"content": "[]"}}],
    })))
    with pytest.raises(search.SourceDiscoveryError) as raised:
        asyncio.run(search.discover_sources(client, "secret", "Title", "Machine", operation_state={}, checkpoint=checkpoint, guard=guard))
    receipt = raised.value.receipt
    assert raised.value.code == "truncated" and receipt["finish_reason"] == "length"
    assert receipt["response_shape"] == {"top_level_keys": ["id", "credits_consumed", "choices"], "content_type": "text"}


def test_received_http400_replays_terminal_error_without_parsing_body():
    state = {"status": "received", "attempts": 1,
             "receipt": {"status_code": 400, "provider_code": 400, "provider_message": "bad request",
                         "body": json.dumps([{"exact_source_url": "https://archive.example/should-not-parse"}]), "body_truncated": False}}
    checkpoint, guard = _hooks([])
    client = SimpleNamespace(post=AsyncMock())
    with pytest.raises(search.SourceDiscoveryError) as raised:
        asyncio.run(search.discover_sources(client, "secret", "Title", "Machine", operation_state=state, checkpoint=checkpoint, guard=guard))
    assert raised.value.code == "http_error" and state["status"] == "error" and client.post.await_count == 0


def test_checkpoint_failure_after_response_requires_reconciliation_message():
    calls = 0
    async def checkpoint(_state):
        nonlocal calls
        calls += 1
        return calls != 2  # submitted succeeds; received fails

    async def guard(_state):
        return True

    client = SimpleNamespace(post=AsyncMock(return_value=_response(json.dumps([
        {"title": "Archive", "exact_source_url": "https://archive.example/page"}
    ]))))
    with pytest.raises(search.SourceDiscoveryError) as raised:
        asyncio.run(search.discover_sources(client, "secret", "Title", "Machine", operation_state={}, checkpoint=checkpoint, guard=guard))
    assert raised.value.code == "checkpoint"
    assert "must be reconciled" in str(raised.value) and client.post.await_count == 1
