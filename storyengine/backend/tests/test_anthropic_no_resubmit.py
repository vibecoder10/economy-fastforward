"""Single-submit client contract for journaled factual-script requests."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from anthropic import APIConnectionError, APIStatusError

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills" / "video-pipeline"))

from shared.clients.anthropic_client import AnthropicClient


class Response:
    def __init__(self, text=""):
        self.content = [type("Block", (), {"text": text})()] if text is not None else []


class Stream:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def get_final_message(self):
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class Messages:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.create_calls = []
        self.stream_calls = []

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response

    def stream(self, **kwargs):
        self.stream_calls.append(kwargs)
        return Stream(next(self.responses))


class SDK:
    def __init__(self, responses):
        self.messages = Messages(responses)
        self.options = []

    def with_options(self, **kwargs):
        self.options.append(kwargs)
        return self


def _client(responses, *, gateway=False):
    instance = object.__new__(AnthropicClient)
    instance._gateway_mode = gateway
    instance.client = SDK(responses)
    return instance


def _connection_error():
    return APIConnectionError(message="connection lost", request=httpx.Request("POST", "https://api.example/messages"))


def _status_error():
    response = httpx.Response(500, request=httpx.Request("POST", "https://api.example/messages"))
    return APIStatusError(message="upstream failed", response=response, body=None)


@pytest.mark.parametrize("failure", [_connection_error(), _status_error()])
def test_no_resubmit_makes_one_direct_request_for_transport_or_status_error(failure):
    client = _client([failure])

    with pytest.raises(type(failure)):
        asyncio.run(client.generate(prompt="one", no_resubmit=True))

    assert client.client.options == [{"max_retries": 0}]
    assert len(client.client.messages.create_calls) == 1


def test_no_resubmit_uses_one_gateway_stream_request_and_returns_text():
    client = _client([Response("saved response")], gateway=True)

    assert asyncio.run(client.generate(prompt="one", no_resubmit=True)) == "saved response"
    assert client.client.options == [{"max_retries": 0}]
    assert len(client.client.messages.stream_calls) == 1
    assert client.client.messages.create_calls == []


def test_no_resubmit_empty_response_fails_once_without_retry():
    client = _client([Response("")])

    with pytest.raises(RuntimeError, match="single no_resubmit attempt"):
        asyncio.run(client.generate(prompt="one", no_resubmit=True))

    assert len(client.client.messages.create_calls) == 1


def test_default_generate_keeps_empty_response_retry(monkeypatch):
    client = _client([Response(""), Response("recovered")])
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    assert asyncio.run(client.generate(prompt="one")) == "recovered"
    assert client.client.options == []
    assert len(client.client.messages.create_calls) == 2


def test_no_resubmit_refuses_continuation_mode_before_a_request():
    client = _client([Response("unused")])

    with pytest.raises(ValueError, match="complete_response"):
        asyncio.run(client.generate(prompt="one", no_resubmit=True, complete_response=True))

    assert client.client.messages.create_calls == []
