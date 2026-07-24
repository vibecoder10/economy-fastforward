"""Quota instrumentation for public YouTube Data API helpers."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import youtube_data_api  # noqa: E402


class _Response:
    status_code = 200

    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body

    def raise_for_status(self):
        return None


class _Client:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    async def get(self, url, **kwargs):
        self.calls.append(url)
        return _Response(next(self.responses))


def test_search_fallback_records_search_bucket_not_general(monkeypatch):
    general = []
    reservations = []

    async def record_general(operation):
        general.append(operation)

    async def reserve_search():
        reservations.append("search.list")

    monkeypatch.setattr(youtube_data_api, "_record_general_call", record_general)
    monkeypatch.setattr(youtube_data_api, "_reserve_search_call", reserve_search)
    client = _Client([{"items": [{"id": {"channelId": "UC123"}}]}])
    channel_id = asyncio.run(
        youtube_data_api._resolve_channel_id(
            "https://youtube.com/c/example", "api-key", client
        )
    )
    assert channel_id == "UC123"
    assert reservations == ["search.list"]
    assert general == []


def test_handle_resolution_records_general_channels_list(monkeypatch):
    general = []
    reservations = []

    async def record_general(operation):
        general.append(operation)

    async def reserve_search():
        reservations.append("search.list")

    monkeypatch.setattr(youtube_data_api, "_record_general_call", record_general)
    monkeypatch.setattr(youtube_data_api, "_reserve_search_call", reserve_search)
    client = _Client([{"items": [{"id": "UC456"}]}])
    channel_id = asyncio.run(
        youtube_data_api._resolve_channel_id(
            "https://youtube.com/@example", "api-key", client
        )
    )
    assert channel_id == "UC456"
    assert general == ["youtube_data_api.channels.list"]
    assert reservations == []


def test_100th_search_calls_youtube_and_101st_is_blocked_before_wire(monkeypatch):
    used = 99

    async def reserve_search():
        nonlocal used
        if used >= 100:
            raise RuntimeError(
                "YouTube search quota is exhausted for today "
                "(100/100 used) — resets at midnight Pacific time."
            )
        used += 1

    monkeypatch.setattr(youtube_data_api, "_reserve_search_call", reserve_search)
    client = _Client([{"items": [{"id": {"channelId": "UC100"}}]}])
    first = asyncio.run(
        youtube_data_api._resolve_channel_id(
            "https://youtube.com/c/allowed", "api-key", client
        )
    )
    assert first == "UC100"
    assert len(client.calls) == 1

    try:
        asyncio.run(
            youtube_data_api._resolve_channel_id(
                "https://youtube.com/c/blocked", "api-key", client
            )
        )
        assert False, "101st search must be refused"
    except RuntimeError as exc:
        assert "search quota" in str(exc)
        assert "midnight Pacific" in str(exc)
    assert len(client.calls) == 1
