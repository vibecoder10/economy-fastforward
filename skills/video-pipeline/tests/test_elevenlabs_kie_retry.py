"""Tests for elevenlabs_client.py's Kie-gateway transient-failure retry
(voicefix root cause #2).

Confirmed live failure (video 686b4651, 2026-07-23, journalctl -u
storyengine-worker): all 6 scenes hit "Kie TTS task failed: internal error"
between 23:20:39 and 23:31:47 with NO retry at all, even though Kie's own
response carries a deterministic, zero-cost signature for this
(failCode "500", failMsg "Internal Error, Please try again later.",
creditsConsumed 0.0 — documented in
storyengine/backend/scripts/coverage_to_app.py's _sheet_transient_kie_error,
the proven pattern this reuses).

No real network: httpx is routed through a MockTransport, and asyncio.sleep
is patched to a no-op so the tests run instantly instead of waiting through
the real 3s poll / 5s retry delays.
"""
import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.clients.elevenlabs_client import (  # noqa: E402
    ElevenLabsClient,
    _is_transient_kie_tts_failure,
)

CREATE_PATH = "/api/v1/jobs/createTask"
RECORD_PATH = "/api/v1/jobs/recordInfo"
AUDIO_URL = "https://cdn.kie.example/audio-123.mp3"

TRANSIENT_FAIL = {
    "code": 200,
    "data": {
        "state": "fail",
        "failCode": "500",
        "failMsg": "Internal Error, Please try again later.",
        "creditsConsumed": 0.0,
    },
}
CONTENT_POLICY_FAIL = {
    "code": 200,
    "data": {
        "state": "fail",
        "failCode": "422",
        "failMsg": "CONTENT_POLICY_BLOCKED: the input was flagged as sensitive.",
        "creditsConsumed": 0.0,
    },
}
SUCCESS = {
    "code": 200,
    "data": {
        "state": "success",
        "resultJson": json.dumps({"resultUrls": [AUDIO_URL]}),
    },
}


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """The client sleeps 3s per poll and KIE_TRANSIENT_RETRY_DELAY_SECONDS
    (5s) per retry — patch both to no-ops so tests run instantly. This
    patches the real asyncio module (query_task's local `import asyncio as
    _asyncio` is the same module object), and monkeypatch auto-reverts it."""
    async def _fast_sleep(_seconds):
        return None
    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)


def _client_with(handler):
    """Patch httpx.AsyncClient globally to use a mock transport — same
    pattern as test_vision_client.py's _client_with."""
    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs.pop("transport", None)
        return real_async_client(transport=transport, **kwargs)

    return factory


def _make_client(monkeypatch, handler):
    monkeypatch.setattr(httpx, "AsyncClient", _client_with(handler))
    return ElevenLabsClient(api_key=None, voice_id="Wq15xSaY3gWvazBRaGEU")


def _kie_client(monkeypatch, handler, kie_key="fake-kie-key"):
    monkeypatch.setenv("KIE_AI_API_KEY", kie_key)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("WAVESPEED_API_KEY", raising=False)
    return _make_client(monkeypatch, handler)


def test_is_transient_kie_tts_failure_predicate():
    """The predicate itself: matches ONLY the exact zero-cost 500/"internal
    error" signature, never a real failure."""
    assert _is_transient_kie_tts_failure(
        {"failCode": "500", "failMsg": "Internal Error, Please try again later.", "creditsConsumed": 0.0})
    assert _is_transient_kie_tts_failure(
        {"failCode": "500", "failMsg": "internal error", "creditsConsumed": None})
    # Different failCode -> not transient (content/auth style failure).
    assert not _is_transient_kie_tts_failure(
        {"failCode": "422", "failMsg": "internal error", "creditsConsumed": 0.0})
    # Credits actually consumed -> never retry, even if failCode/message match.
    assert not _is_transient_kie_tts_failure(
        {"failCode": "500", "failMsg": "internal error", "creditsConsumed": 0.02})
    # Message doesn't mention "internal error" -> not the known transient class.
    assert not _is_transient_kie_tts_failure(
        {"failCode": "500", "failMsg": "gateway timeout", "creditsConsumed": 0.0})
    assert not _is_transient_kie_tts_failure(None)
    print("test_is_transient_kie_tts_failure_predicate OK")


def test_transient_failure_then_success_retries_and_recovers(monkeypatch):
    """Reproduces the confirmed live failure, but this time it recovers:
    task 1 fails with Kie's exact transient 500 signature; a brand NEW task
    (task 2) is created and succeeds. generate_and_wait must return audio,
    not None."""
    calls = {"create": 0, "record": 0}

    def handler(request):
        path = request.url.path
        if path == CREATE_PATH:
            calls["create"] += 1
            task_id = f"task-{calls['create']}"
            return httpx.Response(200, json={"code": 200, "data": {"taskId": task_id}})
        if path == RECORD_PATH:
            calls["record"] += 1
            task_id = request.url.params.get("taskId")
            if task_id == "task-1":
                return httpx.Response(200, json=TRANSIENT_FAIL)
            return httpx.Response(200, json=SUCCESS)
        if str(request.url) == AUDIO_URL:
            return httpx.Response(200, content=b"FAKE-AUDIO-BYTES")
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = _kie_client(monkeypatch, handler)
    fail_info: list = []
    result = asyncio.run(client.generate_voice("Some narration text.", fail_info_out=fail_info))

    assert result.get("audio_content") == b"FAKE-AUDIO-BYTES"
    assert calls["create"] == 2, "a transient failure must create a brand NEW task, not reuse the failed one"
    assert not fail_info, "no failure should be reported to the caller once a retry recovers"
    print("test_transient_failure_then_success_retries_and_recovers OK")


def test_transient_failure_exhausts_retries_then_fails_cleanly(monkeypatch):
    """Every attempt hits the transient signature — must retry exactly
    KIE_TRANSIENT_RETRY_ATTEMPTS times (a brand new task each time) and then
    fail cleanly, reporting the transient failure info to the caller."""
    calls = {"create": 0}

    def handler(request):
        path = request.url.path
        if path == CREATE_PATH:
            calls["create"] += 1
            return httpx.Response(200, json={"code": 200, "data": {"taskId": f"task-{calls['create']}"}})
        if path == RECORD_PATH:
            return httpx.Response(200, json=TRANSIENT_FAIL)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = _kie_client(monkeypatch, handler)
    fail_info: list = []
    audio_path = asyncio.run(client.generate_and_wait("Some narration text.", fail_info_out=fail_info))

    assert audio_path is None
    assert calls["create"] == ElevenLabsClient.KIE_TRANSIENT_RETRY_ATTEMPTS, (
        f"expected exactly {ElevenLabsClient.KIE_TRANSIENT_RETRY_ATTEMPTS} fresh tasks, got {calls['create']}"
    )
    assert fail_info, "the caller must be told why it failed"
    assert fail_info[-1]["failCode"] == "500"
    print("test_transient_failure_exhausts_retries_then_fails_cleanly OK")


def test_non_transient_failure_is_never_retried(monkeypatch):
    """A real content-policy / auth-style failure must fail IMMEDIATELY —
    exactly one task created, no retry, no wasted spend on a doomed retry."""
    calls = {"create": 0}

    def handler(request):
        path = request.url.path
        if path == CREATE_PATH:
            calls["create"] += 1
            return httpx.Response(200, json={"code": 200, "data": {"taskId": f"task-{calls['create']}"}})
        if path == RECORD_PATH:
            return httpx.Response(200, json=CONTENT_POLICY_FAIL)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = _kie_client(monkeypatch, handler)
    fail_info: list = []
    audio_path = asyncio.run(client.generate_and_wait("Some narration text.", fail_info_out=fail_info))

    assert audio_path is None
    assert calls["create"] == 1, "a non-transient failure must NEVER be retried"
    assert fail_info and fail_info[-1]["failCode"] == "422"
    print("test_non_transient_failure_is_never_retried OK")


def test_createtask_level_failure_is_never_retried(monkeypatch):
    """A createTask-level rejection unrelated to voice-roster fallback (e.g.
    an auth failure — no taskId, message doesn't mention roster range) must
    raise immediately, not retry."""
    calls = {"create": 0}

    def handler(request):
        path = request.url.path
        if path == CREATE_PATH:
            calls["create"] += 1
            return httpx.Response(200, json={"code": 401, "msg": "Unauthorized: invalid API key"})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = _kie_client(monkeypatch, handler)
    fail_info: list = []
    audio_path = asyncio.run(client.generate_and_wait("Some narration text.", fail_info_out=fail_info))

    assert audio_path is None
    assert calls["create"] == 1
    print("test_createtask_level_failure_is_never_retried OK")


if __name__ == "__main__":
    import types
    fake_monkeypatch_module = None  # pytest fixture only available under pytest runner
    print("Run this file with: python3 -m pytest test_elevenlabs_kie_retry.py -v")
