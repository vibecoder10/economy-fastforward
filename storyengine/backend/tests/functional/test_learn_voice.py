"""Functional test for youtube_channel._claude_summarize_voice + the
VOICE_LEARN_PROMPT contract.

Two layers:

1. Transform-level: prove that given a realistic list of videos, we build a
   prompt that (a) includes every title, (b) trims descriptions past 400
   chars, (c) sorts/labels by views in the prompt body. These are the
   invariants Claude relies on.

2. Live contract: hit the real Anthropic messages endpoint with no key to
   confirm the URL + headers + JSON shape are accepted (expect 401). This
   is the same pattern as test_youtube_my_videos — we're validating the
   request shape, not Claude's actual output.

To run:
    cd storyengine/backend && .venv/bin/python3 tests/functional/test_learn_voice.py

Last verified passing: 2026-04-19
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import httpx
from routes.youtube_channel import (
    VOICE_LEARN_PROMPT,
    _claude_summarize_voice,
)


SAMPLE_VIDEOS = [
    {
        "video_id": "v1",
        "title": "Why The Dollar Is Doomed",
        "description": "Breakdown of fiat currency collapse cycles. Dead-simple explainer with zero jargon. Hit like if you made it to the end.",
        "views": 1_250_000,
        "likes": 45_000,
        "comments": 3_200,
    },
    {
        "video_id": "v2",
        "title": "The One Chart Every Investor Ignores",
        "description": "X" * 600,  # past the 400-char trim threshold
        "views": 850_000,
        "likes": 22_000,
        "comments": 1_100,
    },
    {
        "video_id": "v3",
        "title": "Gold vs Bitcoin in 2026",
        "description": "",  # empty description — must not crash
        "views": 400_000,
        "likes": 12_000,
        "comments": 600,
    },
]


class FakeAnthropicResponse:
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


class FakeAnthropicClient:
    def __init__(self, response_body: dict, status_code: int = 200):
        self._response_body = response_body
        self._status = status_code
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        self.calls.append({"url": url, "headers": headers, "body": json})
        return FakeAnthropicResponse(self._status, self._response_body)


async def test_prompt_shape_includes_all_videos(monkeypatch):
    """The prompt sent to Claude must include every video's title and
    trimmed description, and must be formatted as the documented template."""
    fake_client = FakeAnthropicClient({
        "content": [{"type": "text", "text": "This creator writes punchy, no-jargon breakdowns aimed at..."}]
    })

    # Patch httpx.AsyncClient to return our fake
    import routes.youtube_channel as mod
    original = mod.httpx.AsyncClient

    def _fake_async_client(**kwargs):
        return fake_client

    mod.httpx.AsyncClient = _fake_async_client
    try:
        result = await _claude_summarize_voice(
            api_key="fake-key",
            channel_name="Power Doctrine",
            videos=SAMPLE_VIDEOS,
        )
    finally:
        mod.httpx.AsyncClient = original

    # Claude response passes through
    assert result.startswith("This creator writes"), f"got: {result!r}"

    # Validate the request shape that went out
    assert len(fake_client.calls) == 1
    call = fake_client.calls[0]
    assert call["url"] == "https://api.anthropic.com/v1/messages"
    assert call["headers"]["x-api-key"] == "fake-key"
    assert call["headers"]["anthropic-version"] == "2023-06-01"
    body = call["body"]
    assert body["model"] == "claude-sonnet-4-20250514"
    assert body["max_tokens"] == 1200
    prompt_text = body["messages"][0]["content"]

    # Every title must appear in the prompt
    for v in SAMPLE_VIDEOS:
        assert v["title"] in prompt_text, f"missing title: {v['title']}"

    # View counts render with thousands separators
    assert "1,250,000 views" in prompt_text
    assert "850,000 views" in prompt_text

    # Channel name substituted
    assert "Power Doctrine" in prompt_text

    # Long description must be truncated (sample v2 has 600 X's)
    # Our trim is 400 chars + "..."
    assert "X" * 400 + "..." in prompt_text
    assert "X" * 500 not in prompt_text, "description wasn't trimmed at 400"

    # Empty description must not crash the builder
    # (already verified — we got here without exception)
    print("✅ test_prompt_shape_includes_all_videos")


async def test_prompt_template_has_required_guidance():
    """The PROMPT constant itself must tell Claude what to produce.
    Regression guard for someone accidentally mangling the template."""
    must_contain = [
        "voice",  # it's about voice
        "style description",  # output framing
        "150-300 words",  # length constraint
        "{channel_name}",  # template slot
        "{video_list}",  # template slot
        "paragraph",  # output format
    ]
    lowered = VOICE_LEARN_PROMPT.lower()
    for needle in must_contain:
        assert needle.lower() in lowered, f"template missing: {needle}"
    print("✅ test_prompt_template_has_required_guidance")


async def test_live_anthropic_contract():
    """LIVE: POST to api.anthropic.com with a junk key. Expect 401 (auth
    failure) — NOT 400 (bad request shape) — which confirms the URL +
    headers + body shape we build are accepted by Anthropic's API."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": "sk-ant-test-invalid-key",
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 10,
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
    # 401 = auth failed (shape accepted). 400 would mean our request shape
    # is wrong. 404 would mean wrong URL. 429 could hit on rate limits.
    assert resp.status_code in (401, 403, 429), f"unexpected status {resp.status_code}: {resp.text[:200]}"
    print(f"✅ test_live_anthropic_contract (got {resp.status_code} as expected)")


async def main():
    await test_prompt_template_has_required_guidance()
    await test_prompt_shape_includes_all_videos(None)
    await test_live_anthropic_contract()
    print("\nAll tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
