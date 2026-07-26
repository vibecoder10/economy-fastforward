from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from custom_film_contract import CustomFilmContractError
from custom_film_director_provider import (
    DIRECTOR_MODEL,
    ProductionSingleAttemptTextClient,
)
from kie_unified import AnthropicDirectClient, KieClaudeClient


RATES = {
    "anthropic": {
        "input_nusd_per_token": 3_000,
        "output_nusd_per_token": 15_000,
    },
    "kie": {
        "input_nusd_per_token": 850,
        "output_nusd_per_token": 4_275,
    },
}


def _operation(unit_max_cents: int = 72) -> dict:
    return {
        "operation_id": "film-bible",
        "unit_max_cents": unit_max_cents,
    }


@pytest.mark.asyncio
async def test_kie_adapter_issues_one_request_and_records_exact_usage_cost(
    monkeypatch,
):
    client = KieClaudeClient("test-key")
    calls = []

    async def create_message_async(**kwargs):
        calls.append(kwargs)
        return {
            "id": "msg-kie-1",
            "model": DIRECTOR_MODEL,
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": '{"ok":true}'}],
            "usage": {"input_tokens": 100, "output_tokens": 200},
        }

    monkeypatch.setattr(client, "create_message_async", create_message_async)
    result = await ProductionSingleAttemptTextClient(
        client,
        rates=RATES,
    ).execute_once(
        operation=_operation(),
        prompt="Build the film bible.",
        system_prompt="Return strict JSON.",
        max_tokens=6_000,
    )

    assert len(calls) == 1
    assert calls[0] == {
        "model": DIRECTOR_MODEL,
        "max_tokens": 6_000,
        "temperature": 0,
        "messages": [{"role": "user", "content": "Build the film bible."}],
        "system": "Return strict JSON.",
    }
    assert result == {
        "request_id": "msg-kie-1",
        "model": DIRECTOR_MODEL,
        "attempt_count": 1,
        "input_tokens": 100,
        "output_tokens": 200,
        "actual_cost_nusd": 940_000,
        "actual_cost_cents": 1,
        "finish_reason": "stop",
        "text": '{"ok":true}',
    }


@pytest.mark.asyncio
async def test_price_book_shortfall_stops_before_kie_request(monkeypatch):
    client = KieClaudeClient("test-key")
    calls = 0

    async def create_message_async(**_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("price failure crossed the provider boundary")

    monkeypatch.setattr(client, "create_message_async", create_message_async)
    with pytest.raises(
        CustomFilmContractError,
        match="price book does not cover",
    ):
        await ProductionSingleAttemptTextClient(
            client,
            rates=RATES,
        ).execute_once(
            operation=_operation(unit_max_cents=1),
            prompt="Build the film bible.",
            system_prompt="Return strict JSON.",
            max_tokens=6_000,
        )
    assert calls == 0


@pytest.mark.asyncio
async def test_incomplete_kie_receipt_is_not_retried(monkeypatch):
    client = KieClaudeClient("test-key")
    calls = 0

    async def create_message_async(**_kwargs):
        nonlocal calls
        calls += 1
        return {
            "id": "msg-kie-1",
            "model": DIRECTOR_MODEL,
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": '{"ok":true}'}],
        }

    monkeypatch.setattr(client, "create_message_async", create_message_async)
    with pytest.raises(
        CustomFilmContractError,
        match="provider usage is incomplete",
    ):
        await ProductionSingleAttemptTextClient(
            client,
            rates=RATES,
        ).execute_once(
            operation=_operation(),
            prompt="Build the film bible.",
            system_prompt="Return strict JSON.",
            max_tokens=6_000,
        )
    assert calls == 1


@pytest.mark.asyncio
async def test_anthropic_adapter_forces_zero_retry_and_closes_client(
    monkeypatch,
):
    direct = AnthropicDirectClient.__new__(AnthropicDirectClient)
    direct.api_key = "test-key"
    calls = []
    lifecycle = []

    class FakeMessages:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                id="msg-anthropic-1",
                model=DIRECTOR_MODEL,
                stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text='{"ok":true}')],
                usage=SimpleNamespace(input_tokens=10, output_tokens=20),
            )

    class FakeAnthropic:
        def __init__(self, *, api_key, max_retries):
            assert api_key == "test-key"
            assert max_retries == 0
            self.messages = FakeMessages()

        def __enter__(self):
            lifecycle.append("open")
            return self

        def __exit__(self, *_args):
            lifecycle.append("close")

    monkeypatch.setitem(
        sys.modules,
        "anthropic",
        SimpleNamespace(Anthropic=FakeAnthropic),
    )
    result = await ProductionSingleAttemptTextClient(
        direct,
        rates=RATES,
    ).execute_once(
        operation=_operation(),
        prompt="Build the film bible.",
        system_prompt="Return strict JSON.",
        max_tokens=6_000,
    )

    assert len(calls) == 1
    assert lifecycle == ["open", "close"]
    assert result["attempt_count"] == 1
    assert result["finish_reason"] == "stop"
    assert result["actual_cost_nusd"] == 330_000
    assert result["actual_cost_cents"] == 1
