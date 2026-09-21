import json
from pathlib import Path

import httpx
import pytest

import reference_judgment as rj
from reference_selection import validate_judgment


def _candidate():
    return {
        "id": "c1", "image_url": "https://images.example/c1.jpg",
        "evidence": [{"kind": "image_caption", "url": "https://source.example/one",
                      "text": "The USS Example is shown during sea trials in 1964."}],
    }


def _result(*, quote="The USS Example is shown during sea trials in 1964.", score=4):
    return {"candidates": [{"id": "c1", "identity": {
        "status": "confirmed", "reason": "The caption names the vessel.",
        "evidence": [{"url": "https://source.example/one", "quote": quote}]},
        "usable": True, "scores": {name: score for name in
        ("coverage", "features", "sharpness", "unobstructed", "perspective")},
        "view": "side", "reason": "Clear side profile.", "limitations": []}]}


class Response:
    def __init__(self, status_code, body):
        self.status_code, self.body = status_code, body
        self.text = body if isinstance(body, str) else json.dumps(body)

    def json(self):
        if isinstance(self.body, str):
            raise ValueError("not json")
        return self.body


class Client:
    def __init__(self, responses, calls):
        self.responses, self.calls = responses, calls

    async def __aenter__(self): return self
    async def __aexit__(self, *_): return None
    async def post(self, url, *, headers, json):
        self.calls.append({"url": url, "headers": headers, "json": json})
        response = self.responses.pop(0)
        if isinstance(response, Exception): raise response
        return response


@pytest.fixture
def review_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("REFERENCE_REVIEW_DIR", str(tmp_path / "reviews"))
    return tmp_path / "reviews"


def _install(monkeypatch, responses):
    calls = []
    monkeypatch.setattr(rj.httpx, "AsyncClient", lambda **_: Client(responses, calls))
    return calls


async def _request(**overrides):
    values = {"tenant_id": "tenant-a", "machine": "USS Example", "candidates": [_candidate()],
              "content": [{"type": "text", "text": "facts"}, {"type": "image", "source": {"data": "VERYPRIVATEPIXELS"}}],
              "provider": "anthropic", "url": "https://provider.example/messages",
              "headers": {"x-api-key": "top-secret"}, "model": "claude-test", "video_id": "video-a"}
    values.update(overrides)
    return await rj.request_judgment(**values)


def _complete(result=None):
    return Response(200, {"stop_reason": "end_turn", "content": [
        {"type": "text", "text": json.dumps(result or _result())}]})


@pytest.mark.asyncio
async def test_direct_anthropic_schema_is_forced_and_uncertain_evidence_is_not_a_retry(monkeypatch, review_dir):
    calls = _install(monkeypatch, [_complete(_result(quote="not in source"))])
    result = await _request()
    payload = calls[0]["json"]
    schema = payload["output_config"]["format"]["schema"]
    assert payload["max_tokens"] == 8000 and schema["additionalProperties"] is False
    assert schema["properties"]["candidates"]["items"]["properties"]["id"]["enum"] == ["c1"]
    assert validate_judgment(result, [_candidate()])["c1"]["identity"]["status"] == "uncertain"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_malformed_text_recovers_with_second_larger_request(monkeypatch, review_dir):
    calls = _install(monkeypatch, [Response(200, {"content": [{"type": "text", "text": "not json"}]}),
                                  _complete()])
    assert await _request() == _result()
    assert [call["json"]["max_tokens"] for call in calls] == [8000, 16000]
    assert calls[1]["json"]["messages"][0]["content"][-1]["text"] == rj._CORRECTION


@pytest.mark.asyncio
async def test_malformed_scores_recovers(monkeypatch, review_dir):
    bad = _result(score=6)
    calls = _install(monkeypatch, [Response(200, {"content": [{"type": "text", "text": json.dumps(bad)}]}),
                                  _complete()])
    await _request()
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_max_tokens_doubles_budget(monkeypatch, review_dir):
    calls = _install(monkeypatch, [Response(200, {"stop_reason": "max_tokens", "content": []}), _complete()])
    await _request()
    assert [call["json"]["max_tokens"] for call in calls] == [8000, 16000]


@pytest.mark.asyncio
async def test_complete_checkpoint_replays_without_provider_call(monkeypatch, review_dir):
    calls = _install(monkeypatch, [_complete()])
    assert await _request() == _result()
    assert await _request() == _result()
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_scope_isolation_and_checkpoint_excludes_headers_and_pixels(monkeypatch, review_dir):
    calls = _install(monkeypatch, [_complete(), _complete()])
    await _request(video_id="video-a")
    await _request(video_id="video-b")
    checkpoints = list(review_dir.glob("*.json"))
    assert len(calls) == 2 and len(checkpoints) == 2
    saved = "\n".join(item.read_text() for item in checkpoints)
    assert "top-secret" not in saved and "VERYPRIVATEPIXELS" not in saved
    assert (review_dir.stat().st_mode & 0o777) == 0o700
    assert all((item.stat().st_mode & 0o777) == 0o600 for item in checkpoints)


@pytest.mark.asyncio
async def test_two_persisted_attempts_bound_a_restart(monkeypatch, review_dir):
    calls = _install(monkeypatch, [Response(200, {"content": [{"type": "text", "text": "bad"}]}),
                                  Response(200, {"content": [{"type": "text", "text": "still bad"}]})])
    with pytest.raises(Exception): await _request()
    with pytest.raises(Exception): await _request()
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [Response(200, {"stop_reason": "refusal", "content": []}), Response(401, {"error": "bad key"})])
async def test_refusal_and_401_stop_after_one_call(monkeypatch, review_dir, response):
    calls = _install(monkeypatch, [response])
    with pytest.raises(Exception): await _request()
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_503_retries_once_after_delay(monkeypatch, review_dir):
    calls, sleeps = _install(monkeypatch, [Response(503, {"error": "temporary"}),
                                           _complete()]), []
    async def sleep(seconds): sleeps.append(seconds)
    monkeypatch.setattr(rj.asyncio, "sleep", sleep)
    await _request()
    assert len(calls) == 2 and sleeps == [1]


@pytest.mark.asyncio
async def test_kie_forces_named_tool_and_parses_only_matching_tool(monkeypatch, review_dir):
    calls = _install(monkeypatch, [Response(200, {"stop_reason": "tool_use", "content": [{"type": "text", "text": "ignore"},
        {"type": "tool_use", "name": "submit_reference_review", "input": _result()}]})])
    assert await _request(provider="kie") == _result()
    payload = calls[0]["json"]
    assert payload["tool_choice"] == {"type": "tool", "name": "submit_reference_review"}
    assert payload["tools"][0]["input_schema"]["additionalProperties"] is False


def test_default_review_root_is_stable_app_data(monkeypatch):
    monkeypatch.delenv("REFERENCE_REVIEW_DIR", raising=False)
    assert rj._review_root() == Path(rj.__file__).resolve().parents[1] / "data" / "reference-reviews"


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [Response(200, {"stop_reason": "refusal", "content": []}), Response(401, {"error": "bad key"})])
async def test_terminal_checkpoint_replay_never_calls_provider(monkeypatch, review_dir, response):
    calls = _install(monkeypatch, [response])
    with pytest.raises(Exception):
        await _request()
    with pytest.raises(Exception):
        await _request()
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_incomplete_end_turn_recovers_without_acceptance(monkeypatch, review_dir):
    calls = _install(monkeypatch, [Response(200, {"stop_reason": "pause_turn", "content": [{"type": "text", "text": json.dumps(_result())}]}),
                                  _complete()])
    assert await _request() == _result()
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_resumed_invalid_response_adds_correction(monkeypatch, review_dir):
    content = [{"type": "text", "text": "facts"}, {"type": "image", "source": {"data": "VERYPRIVATEPIXELS"}}]
    schema = rj.judgment_schema(["c1"])
    path = rj._checkpoint_path("tenant-a", "video-a", "USS Example", "anthropic", "claude-test", schema, content)
    rj._write_checkpoint(path, {"version": 1, "status": "pending", "attempts": [
        {"number": 1, "status": "invalid_response", "max_tokens": 8000}]})
    calls = _install(monkeypatch, [_complete()])
    assert await _request(content=content) == _result()
    assert calls[0]["json"]["max_tokens"] == 16000
    assert calls[0]["json"]["messages"][0]["content"][-1]["text"] == rj._CORRECTION


def _luna(result=None, *, status="completed", parts=None):
    return Response(200, {"status": status, "output": [
        {"type": "reasoning", "summary": []},
        {"type": "message", "content": parts if parts is not None else
         [{"type": "output_text", "text": json.dumps(result or _result())}]}]})


@pytest.mark.asyncio
async def test_luna_uses_schema_bound_text_format_and_parses_output_text(monkeypatch, review_dir):
    calls = _install(monkeypatch, [_luna()])
    assert await _request(provider="kie_luna", model=rj.KIE_LUNA_MODEL) == _result()
    payload = calls[0]["json"]
    fmt = payload["text"]["format"]
    assert (payload["model"], payload["max_output_tokens"], payload["stream"]) == ("gpt-5-6-luna", 8000, False)
    assert fmt["type"] == "json_schema" and fmt["strict"] is True and fmt["schema"]["additionalProperties"] is False
    assert fmt["schema"]["properties"]["candidates"]["items"]["properties"]["id"]["enum"] == ["c1"]
    assert "Codex" not in payload["instructions"] and "tools" not in payload and "messages" not in payload
    assert payload["input"][0]["content"][0]["type"] == "text"  # caller-built parts pass through untouched


@pytest.mark.asyncio
async def test_luna_gateway_failure_in_a_200_body_is_retried_as_a_server_error(monkeypatch, review_dir):
    calls = _install(monkeypatch, [Response(200, {"code": 500, "msg": "Network error, please try again later."}), _luna()])
    sleeps = []

    async def no_sleep(seconds): sleeps.append(seconds)
    monkeypatch.setattr(rj.asyncio, "sleep", no_sleep)
    assert await _request(provider="kie_luna") == _result()
    assert len(calls) == 2 and sleeps == [1]
    assert "correction" not in json.dumps(calls[1]["json"]).lower() and rj._CORRECTION not in json.dumps(calls[1]["json"])


@pytest.mark.asyncio
async def test_luna_gateway_failure_twice_is_a_terminal_provider_error(monkeypatch, review_dir):
    _install(monkeypatch, [Response(200, {"code": 500, "msg": "down"}), Response(200, {"code": 500, "msg": "down"})])

    async def no_sleep(seconds): return None
    monkeypatch.setattr(rj.asyncio, "sleep", no_sleep)
    with pytest.raises(Exception) as caught:
        await _request(provider="kie_luna")
    assert getattr(caught.value, "code", None) == "provider_error" and "HTTP 500" in caught.value.reason


@pytest.mark.asyncio
async def test_luna_incomplete_output_recovers_with_larger_budget_and_correction(monkeypatch, review_dir):
    calls = _install(monkeypatch, [_luna(status="incomplete", parts=[]), _luna()])
    assert await _request(provider="kie_luna") == _result()
    assert [call["json"]["max_output_tokens"] for call in calls] == [8000, 16000]
    assert calls[1]["json"]["input"][0]["content"][-1]["text"] == rj._CORRECTION


@pytest.mark.asyncio
async def test_luna_refusal_is_terminal_and_never_retried(monkeypatch, review_dir):
    calls = _install(monkeypatch, [_luna(parts=[{"type": "refusal", "refusal": "no"}])])
    with pytest.raises(Exception) as caught:
        await _request(provider="kie_luna")
    assert getattr(caught.value, "code", None) == "invalid_review" and len(calls) == 1


def _judge_setup(monkeypatch, secrets, env=None):
    import reference_selection as rs
    import vault
    captured = {}

    async def get_secret(name, tenant_id=None, user_id=None): return secrets.get(name)

    async def request_judgment(tenant_id, machine, candidates, content, provider, url, headers, model, *, video_id=None):
        captured.update(provider=provider, url=url, headers=headers, model=model, content=content)
        return {"candidates": []}
    monkeypatch.setattr(vault, "get_secret", get_secret)
    monkeypatch.setattr(rj, "request_judgment", request_judgment)
    monkeypatch.delenv("REFERENCE_JUDGE_PROVIDER", raising=False)
    for key, value in (env or {}).items():
        monkeypatch.setenv(key, value)
    candidate = dict(_candidate(), _vision=b"\xff\xd8pixels")
    return rs, candidate, captured


@pytest.mark.asyncio
async def test_judge_without_anthropic_key_uses_luna_with_responses_format_parts(monkeypatch):
    rs, candidate, seen = _judge_setup(monkeypatch, {"kie_ai_api_key": "kie-secret"})
    await rs._judge("tenant-a", "USS Example", [candidate], {}, video_id="video-a")
    assert (seen["provider"], seen["model"], seen["url"]) == ("kie_luna", "gpt-5-6-luna", "https://api.kie.ai/codex/v1/responses")
    assert seen["headers"] == {"Authorization": "Bearer kie-secret", "Content-Type": "application/json"}
    kinds = [part["type"] for part in seen["content"]]
    assert set(kinds) == {"input_text", "input_image"} and kinds.count("input_image") == 1
    image = next(part for part in seen["content"] if part["type"] == "input_image")
    assert image["image_url"].startswith("data:image/jpeg;base64,")


@pytest.mark.asyncio
async def test_judge_keeps_direct_anthropic_when_the_workspace_has_a_key(monkeypatch):
    rs, candidate, seen = _judge_setup(monkeypatch, {"anthropic_api_key": "sk-ant", "kie_ai_api_key": "kie-secret"})
    await rs._judge("tenant-a", "USS Example", [candidate], {}, video_id="video-a")
    assert seen["provider"] == "anthropic" and seen["headers"]["x-api-key"] == "sk-ant"
    assert {part["type"] for part in seen["content"]} == {"text", "image"}


@pytest.mark.asyncio
async def test_judge_env_switch_returns_to_kie_claude(monkeypatch):
    rs, candidate, seen = _judge_setup(monkeypatch, {"kie_ai_api_key": "kie-secret"},
                                       {"REFERENCE_JUDGE_PROVIDER": "kie_claude"})
    await rs._judge("tenant-a", "USS Example", [candidate], {}, video_id="video-a")
    assert seen["provider"] == "kie" and seen["url"].endswith("/claude/v1/messages")
    assert {part["type"] for part in seen["content"]} == {"text", "image"}


@pytest.mark.asyncio
async def test_judge_with_no_keys_fails_closed(monkeypatch):
    rs, candidate, _ = _judge_setup(monkeypatch, {})
    with pytest.raises(Exception) as caught:
        await rs._judge("tenant-a", "USS Example", [candidate], {}, video_id="video-a")
    assert getattr(caught.value, "code", None) == "provider_error"
