import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills" / "video-pipeline"))

from shared import research_response
from shared.clients.anthropic_client import AnthropicClient, WEB_SEARCH_TOOL


class Block:
    def __init__(self, text=None, **data):
        self.text = text
        self._data = {"type": "text", "text": text} if text is not None else data

    def model_dump(self, **_kwargs):
        return self._data


class Response:
    def __init__(self, reason, *blocks):
        self.stop_reason = reason
        self.content = list(blocks)
        self.id = "resp-test"
        self.model = "model-test"
        self.usage = {"output_tokens": 1}


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
        self.calls = []

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        return Stream(next(self.responses))


def client(responses):
    instance = object.__new__(AnthropicClient)
    instance._gateway_mode = False
    instance.client = type("SDK", (), {"messages": Messages(responses)})()
    return instance


def run(instance, **kwargs):
    return asyncio.run(instance.generate(prompt="research", model="test-model", max_tokens=9, temperature=0, **kwargs))


def test_two_max_token_pages_assemble_exactly_without_newline():
    prefix = '{"fact_sheet":"The source text was cut mid-'
    suffix = 'sentence.","unit_roster":["Holland class"]}'
    instance = client([Response("max_tokens", Block(prefix)), Response("end_turn", Block(suffix))])
    assembled = run(instance, complete_response=True)
    assert assembled == prefix + suffix
    assert json.loads(assembled)["unit_roster"] == ["Holland class"]
    assert len(instance.client.messages.calls) == 2
    continuation = instance.client.messages.calls[1]
    assert "tools" not in continuation
    assert continuation["messages"][-1]["role"] == "user"
    assert "missing suffix" in continuation["messages"][-1]["content"]


def test_pause_turn_preserves_tool_blocks_and_tools_without_a_user_nudge():
    instance = client([
        Response("pause_turn", Block("prefix"), Block(type="server_tool_use", id="tool-1", name="web_search", input={"query": "x"})),
        Response("end_turn", Block("suffix")),
    ])
    assert run(instance, complete_response=True, tools=[WEB_SEARCH_TOOL]) == "prefixsuffix"
    continuation = instance.client.messages.calls[1]
    assert continuation["tools"] == [WEB_SEARCH_TOOL]
    assert continuation["messages"][-1]["role"] == "assistant"
    assert any(block.get("type") == "server_tool_use" for block in continuation["messages"][-1]["content"])


def test_end_turn_needs_one_call():
    instance = client([Response("end_turn", Block("done"))])
    assert run(instance, complete_response=True) == "done"
    assert len(instance.client.messages.calls) == 1


def test_complete_checkpoint_replays_without_call(tmp_path):
    path = tmp_path / "checkpoint.json"
    first = client([Response("end_turn", Block("done"))])
    assert run(first, complete_response=True, checkpoint_path=path) == "done"
    resumed = client([])
    assert run(resumed, complete_response=True, checkpoint_path=path) == "done"
    assert resumed.client.messages.calls == []
    assert os.stat(path).st_mode & 0o777 == 0o600


def test_interrupted_continuation_resumes_saved_prefix(tmp_path):
    path = tmp_path / "checkpoint.json"
    first = client([Response("max_tokens", Block("pre")), RuntimeError("upstream down")])
    with pytest.raises(RuntimeError, match="upstream down"):
        run(first, complete_response=True, checkpoint_path=path)
    resumed = client([Response("end_turn", Block("fix"))])
    assert run(resumed, complete_response=True, checkpoint_path=path) == "prefix"
    assert len(resumed.client.messages.calls) == 1


def test_persisted_limit_and_terminal_reason_fail_before_new_call(tmp_path):
    path = tmp_path / "checkpoint.json"
    fingerprint = research_response.request_fingerprint(
        prompt="research", system_prompt="", model="test-model", tools=None, max_tokens=9, temperature=0,
    )
    responses = [{"stop_reason": "max_tokens", "content": [{"type": "text", "text": "x"}], "text": "x"}] * 4
    research_response.save(path, fingerprint, responses)
    exhausted = client([])
    with pytest.raises(RuntimeError, match="continuation limit"):
        run(exhausted, complete_response=True, checkpoint_path=path)
    assert exhausted.client.messages.calls == []

    research_response.save(path, fingerprint, [{"stop_reason": "refusal", "content": [], "text": ""}])
    refused = client([])
    with pytest.raises(RuntimeError, match="refusal"):
        run(refused, complete_response=True, checkpoint_path=path)
    assert refused.client.messages.calls == []


def test_checkpoint_scope_and_corruption_do_not_reuse_or_rediscover(tmp_path):
    fp = "f" * 64
    path_a = research_response.checkpoint_path({"tenant_id": "a", "video_id": "same"}, fp)
    assert path_a != research_response.checkpoint_path({"tenant_id": "b", "video_id": "same"}, fp)
    assert path_a != research_response.checkpoint_path({"tenant_id": "a", "video_id": "other"}, fp)
    path = tmp_path / "checkpoint.json"
    path.write_text("not-json")
    instance = client([])
    with pytest.raises(RuntimeError, match="unreadable"):
        run(instance, complete_response=True, checkpoint_path=path)
    assert instance.client.messages.calls == []

    research_response.save(path, "a" * 64, [])
    mismatch = client([])
    with pytest.raises(RuntimeError, match="does not match"):
        run(mismatch, complete_response=True, checkpoint_path=path)
    assert mismatch.client.messages.calls == []


def test_streamed_sdk_fields_are_removed_when_resuming_saved_checkpoint(tmp_path):
    from anthropic.types.parsed_message import ParsedTextBlock
    from shared.clients.anthropic_client import _serialize_content

    block = ParsedTextBlock(type="text", text="pre", parsed_output=None)
    response = Response("max_tokens", block)
    content = _serialize_content(response)
    assert "parsed_output" in content[0]
    content.append({"type": "server_tool_use", "id": "tool-1", "name": "web_search",
                    "input": {"parsed_output": "legitimate input"}, "__json_buf": "sdk-only"})
    path = tmp_path / "checkpoint.json"
    fingerprint = research_response.request_fingerprint(
        prompt="research", system_prompt="", model="test-model", tools=None, max_tokens=9, temperature=0,
    )
    research_response.save(path, fingerprint, [
        {"stop_reason": "max_tokens", "content": content, "text": "pre"},
    ])
    resumed = client([Response("end_turn", Block("fix"))])
    assert run(resumed, complete_response=True, checkpoint_path=path) == "prefix"
    assert len(resumed.client.messages.calls) == 1
    sent = resumed.client.messages.calls[0]["messages"][1]["content"]
    assert "parsed_output" not in sent[0]
    assert "__json_buf" not in sent[1]
    assert sent[1]["input"] == {"parsed_output": "legitimate input"}
    saved = json.loads(path.read_text())["responses"][0]["content"]
    assert "parsed_output" in saved[0]
    assert saved[1]["__json_buf"] == "sdk-only"
