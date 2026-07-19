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
from actions import CLAUDE_MODELS


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
    # C35: this used to pin its own stale "claude-sonnet-4-20250514" id,
    # which 404s on the live API (confirmed live — see
    # producer_prompt.py's note) — now reads the same single Claude tier
    # source (shared.channel_profile.CLAUDE_MODELS) every other direct-
    # Anthropic call site uses.
    assert body["model"] == CLAUDE_MODELS["anthropic"]["smart"]
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


async def test_transcript_replaces_description_in_prompt():
    """When a video has a `transcript` field, the prompt must include the
    transcript body (prefixed 'TRANSCRIPT:') and NOT the description. This
    is the Cycle 12 upgrade — richer voice signal from actual spoken content."""
    videos = [
        {
            "video_id": "t1",
            "title": "Hook test",
            "description": "boilerplate description that should NOT appear when a transcript exists",
            "views": 500_000,
            "transcript": "Listen up folks, here's the deal. The dollar is cooked and I'm gonna break down exactly why in the next 60 seconds so buckle up.",
        },
        {
            "video_id": "t2",
            "title": "No transcript fallback",
            "description": "this description SHOULD appear because no transcript",
            "views": 300_000,
            # no transcript field
        },
    ]
    fake_client = FakeAnthropicClient({
        "content": [{"type": "text", "text": "Style guidance."}]
    })

    import routes.youtube_channel as mod
    original = mod.httpx.AsyncClient
    mod.httpx.AsyncClient = lambda **kw: fake_client
    try:
        await _claude_summarize_voice(
            api_key="fake-key", channel_name="Test", videos=videos
        )
    finally:
        mod.httpx.AsyncClient = original

    prompt_text = fake_client.calls[0]["body"]["messages"][0]["content"]

    # Transcript video: TRANSCRIPT: line present, spoken content present,
    # description string must NOT appear.
    assert "TRANSCRIPT:" in prompt_text, "prompt must label transcripts"
    assert "Listen up folks" in prompt_text, "transcript body missing"
    assert "boilerplate description" not in prompt_text, (
        "description leaked into prompt even though transcript was present"
    )

    # Fallback video: DESCRIPTION: line present with the description body.
    assert "DESCRIPTION:" in prompt_text
    assert "this description SHOULD appear" in prompt_text
    print("✅ test_transcript_replaces_description_in_prompt")


async def test_prompt_template_mentions_transcripts():
    """The prompt constant must instruct Claude that transcripts are the
    PRIMARY voice signal when available. Regression guard."""
    lowered = VOICE_LEARN_PROMPT.lower()
    assert "transcript" in lowered, "prompt must reference transcripts"
    assert "primary" in lowered or "prefer" in lowered, (
        "prompt must tell Claude to prefer transcripts over descriptions"
    )
    print("✅ test_prompt_template_mentions_transcripts")


async def test_transcript_fetcher_handles_failures_silently():
    """_fetch_transcripts_for_videos must attach `transcript` to every video
    (possibly None) without raising, even when yt-dlp fails on some."""
    from routes.youtube_channel import _fetch_transcripts_for_videos
    import routes.youtube_channel as mod

    videos = [
        {"video_id": "good", "title": "ok", "views": 100},
        {"video_id": "bad", "title": "boom", "views": 50},
        {"video_id": None, "title": "no id", "views": 10},
    ]

    call_count = {"n": 0}

    def fake_extract(vid):
        call_count["n"] += 1
        if vid == "good":
            return {"transcript": "  Hello world this is the transcript body.  "}
        if vid == "bad":
            raise RuntimeError("simulated yt-dlp crash")
        return None

    import routes.niche as niche_mod
    original = niche_mod._extract_video_info
    niche_mod._extract_video_info = fake_extract
    try:
        await _fetch_transcripts_for_videos(videos)
    finally:
        niche_mod._extract_video_info = original

    # Every video got a `transcript` key
    for v in videos:
        assert "transcript" in v, f"missing transcript key on {v['video_id']}"

    # Success case: trimmed, non-None
    good = next(v for v in videos if v["video_id"] == "good")
    assert good["transcript"] == "Hello world this is the transcript body."

    # Failure case: None, no crash
    bad = next(v for v in videos if v["video_id"] == "bad")
    assert bad["transcript"] is None

    # Missing video_id: None, yt-dlp not called for it
    no_id = next(v for v in videos if v["video_id"] is None)
    assert no_id["transcript"] is None

    print("✅ test_transcript_fetcher_handles_failures_silently")


async def test_transcript_char_cap_enforced():
    """Transcripts past TRANSCRIPT_CHAR_CAP must be truncated with an
    ellipsis so a 30-minute podcast doesn't blow out the Claude context."""
    from routes.youtube_channel import (
        _fetch_transcripts_for_videos,
        TRANSCRIPT_CHAR_CAP,
    )
    import routes.niche as niche_mod

    huge = "A" * (TRANSCRIPT_CHAR_CAP + 5000)

    def fake_extract(vid):
        return {"transcript": huge}

    videos = [{"video_id": "long", "title": "long video", "views": 1}]
    original = niche_mod._extract_video_info
    niche_mod._extract_video_info = fake_extract
    try:
        await _fetch_transcripts_for_videos(videos)
    finally:
        niche_mod._extract_video_info = original

    out = videos[0]["transcript"]
    assert out.endswith("...")
    # Original was capped at TRANSCRIPT_CHAR_CAP + "..." length
    assert len(out) == TRANSCRIPT_CHAR_CAP + 3
    print("✅ test_transcript_char_cap_enforced")


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
    await test_prompt_template_mentions_transcripts()
    await test_prompt_shape_includes_all_videos(None)
    await test_transcript_replaces_description_in_prompt()
    await test_transcript_fetcher_handles_failures_silently()
    await test_transcript_char_cap_enforced()
    await test_live_anthropic_contract()
    print("\nAll tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
