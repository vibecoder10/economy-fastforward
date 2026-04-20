"""Functional test: prove /api/intelligence/distill-url — the WelcomeQuest
step-2 hook endpoint — handles every failure mode without either a) crashing
the onboarding funnel or b) leaking a raw exception string to the user.

This is the FIRST thing a new signup does after they paste in a YouTube URL:
the distillation response is what sells them on the product. If it breaks
silently, the funnel dies silently — hence the focus on:

  - video-ID extraction across url formats (watch?v=, youtu.be/, shorts/)
  - invalid / unrecognizable URLs → 400, with no stack trace leaking
  - yt-dlp failure → 502 with humanized copy (not "HTTPSConnectionPool...")
  - yt-dlp returns None → 404 "Video not found"
  - distillation failure AFTER video is already scraped → partial result,
    status "scraped_but_distillation_failed", video still stored
  - idempotency: same URL twice → second call returns "already_distilled"
    WITHOUT re-running yt-dlp (expensive + rate-limited)

Runs in isolation — mocks the database layer, yt-dlp extraction, and
distillation so the test is fast and has no external dependencies.
"""
import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import HTTPException
from routes.intelligence import (
    distill_from_url,
    _extract_video_id_from_url,
    DistillURLRequest,
)


TENANT = "00000000-0000-0000-0000-000000000001"
VALID_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
VIDEO_ID = "dQw4w9WgXcQ"


# ───────────────────────── helpers ─────────────────────────

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _fake_ytdlp_info(video_id: str = VIDEO_ID, with_transcript: bool = True) -> dict:
    """Shape matches what routes.niche._extract_video_info returns."""
    return {
        "video_id": video_id,
        "title": "Never Gonna Give You Up",
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "channel": "Rick Astley",
        "channel_url": "https://www.youtube.com/@RickAstleyYT",
        "views": 1_500_000_000,
        "vph": 0.0,
        "hours_old": 0.0,
        "published_at": "2009-10-25T06:57:33Z",
        "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
        "transcript": "never gonna give you up never gonna let you down" if with_transcript else "",
        "duration_seconds": 212,
        "description": "The official video",
        "likes": 18_000_000,
        "comment_count": 2_500_000,
        "channel_subscriber_count": 4_000_000,
        "like_ratio": 0.012,
        "comment_ratio": 0.0016,
        "views_per_sub_ratio": 375.0,
        "published_day_of_week": "Sunday",
        "published_hour": 6,
        "has_chapters": False,
        "chapter_count": 0,
        "chapter_titles": None,
        "tags": ["music", "80s"],
    }


# ───────────────────────── video-id extractor ─────────────────────────

def test_extract_video_id_standard_watch_url():
    assert _extract_video_id_from_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    print("✅ test_extract_video_id_standard_watch_url")


def test_extract_video_id_short_url():
    assert _extract_video_id_from_url("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    print("✅ test_extract_video_id_short_url")


def test_extract_video_id_shorts_url():
    assert _extract_video_id_from_url("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    print("✅ test_extract_video_id_shorts_url")


def test_extract_video_id_embed_url():
    assert _extract_video_id_from_url("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    print("✅ test_extract_video_id_embed_url")


def test_extract_video_id_with_extra_params():
    assert _extract_video_id_from_url(
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL123&t=42"
    ) == "dQw4w9WgXcQ"
    print("✅ test_extract_video_id_with_extra_params")


def test_extract_video_id_returns_none_for_garbage():
    # Ordinary URL without a YouTube pattern.
    assert _extract_video_id_from_url("https://example.com/foo/bar") is None
    # Empty string.
    assert _extract_video_id_from_url("") is None
    # Non-URL text.
    assert _extract_video_id_from_url("paste your url here") is None
    print("✅ test_extract_video_id_returns_none_for_garbage")


# ───────────────────────── endpoint error paths ─────────────────────────

def test_distill_invalid_url_returns_400():
    """Funnel safety: bad paste → 400, not a 500 that kills the onboarding step."""
    body = DistillURLRequest(url="not a youtube url")
    try:
        _run(distill_from_url(body, tenant_id=TENANT))
    except HTTPException as e:
        assert e.status_code == 400, f"expected 400 for invalid URL, got {e.status_code}"
        assert "video id" in (e.detail or "").lower()
        print("✅ test_distill_invalid_url_returns_400")
        return
    raise AssertionError("expected HTTPException(400) for invalid URL")


def test_distill_ytdlp_failure_returns_humanized_502():
    """yt-dlp raising must surface as a 502 with humanized copy, no raw leak."""
    body = DistillURLRequest(url=VALID_URL)

    raw_err = "HTTPSConnectionPool(host='www.youtube.com', port=443): Max retries exceeded"

    async def _fake_fetch_one(q, *args):
        # No existing distillation row.
        return None

    def _raise_ytdlp(video_id):
        raise RuntimeError(raw_err)

    with patch("routes.intelligence.fetch_one", new=AsyncMock(side_effect=_fake_fetch_one)), \
         patch("routes.niche._extract_video_info", side_effect=_raise_ytdlp):
        try:
            _run(distill_from_url(body, tenant_id=TENANT))
        except HTTPException as e:
            assert e.status_code == 502, f"expected 502, got {e.status_code}"
            detail = e.detail or ""
            # The raw connection-pool string must never reach the user.
            assert "HTTPSConnectionPool" not in detail
            assert "www.youtube.com" not in detail
            # And the humanized context copy must lead.
            assert "youtube" in detail.lower() or "couldn't" in detail.lower()
            print("✅ test_distill_ytdlp_failure_returns_humanized_502")
            return
    raise AssertionError("expected HTTPException(502) on yt-dlp failure")


def test_distill_ytdlp_returns_none_returns_404():
    """yt-dlp returning None (video unavailable/private) → 404, not 500."""
    body = DistillURLRequest(url=VALID_URL)

    with patch("routes.intelligence.fetch_one", new=AsyncMock(return_value=None)), \
         patch("routes.niche._extract_video_info", return_value=None):
        try:
            _run(distill_from_url(body, tenant_id=TENANT))
        except HTTPException as e:
            assert e.status_code == 404, f"expected 404, got {e.status_code}"
            assert "not found" in (e.detail or "").lower() or "unavailable" in (e.detail or "").lower()
            print("✅ test_distill_ytdlp_returns_none_returns_404")
            return
    raise AssertionError("expected HTTPException(404) when yt-dlp returns None")


# ───────────────────────── happy path + idempotency ─────────────────────────

def test_distill_idempotent_second_call_skips_ytdlp():
    """Second POST with the same URL returns cached result WITHOUT calling yt-dlp.

    If this ever regresses we silently re-pay yt-dlp's cost on every
    WelcomeQuest step-2 retry, and hammer YouTube's rate limits.
    """
    body = DistillURLRequest(url=VALID_URL)
    existing_row = {
        "id": "11111111-1111-1111-1111-111111111111",
        "title": "Never Gonna Give You Up",
        "distilled_at": "2026-04-19T00:00:00Z",
        "summary": "The hook that never quits.",
        "structured_metadata": {"hooks": ["surprise"], "topics": ["music"]},
    }

    ytdlp_spy = MagicMock(return_value=_fake_ytdlp_info())

    with patch("routes.intelligence.fetch_one", new=AsyncMock(return_value=existing_row)), \
         patch("routes.niche._extract_video_info", ytdlp_spy):
        result = _run(distill_from_url(body, tenant_id=TENANT))

    assert result["status"] == "already_distilled"
    assert result["video_id"] == VIDEO_ID
    assert result["dna"] == {"hooks": ["surprise"], "topics": ["music"]}
    assert result["summary"] == "The hook that never quits."
    # Most important assertion: yt-dlp must not have been invoked.
    assert ytdlp_spy.call_count == 0, "yt-dlp was re-invoked on an already-distilled video"
    print("✅ test_distill_idempotent_second_call_skips_ytdlp")


def test_distill_idempotent_handles_stringified_metadata():
    """DB may return structured_metadata as a JSON string — endpoint must parse it."""
    body = DistillURLRequest(url=VALID_URL)
    existing_row = {
        "id": "11111111-1111-1111-1111-111111111111",
        "title": "Never Gonna Give You Up",
        "distilled_at": "2026-04-19T00:00:00Z",
        "summary": "Test.",
        "structured_metadata": '{"hooks": ["surprise"], "topics": ["music"]}',
    }

    with patch("routes.intelligence.fetch_one", new=AsyncMock(return_value=existing_row)):
        result = _run(distill_from_url(body, tenant_id=TENANT))

    assert result["status"] == "already_distilled"
    assert result["dna"] == {"hooks": ["surprise"], "topics": ["music"]}
    print("✅ test_distill_idempotent_handles_stringified_metadata")


def test_distill_distillation_failure_returns_partial():
    """If yt-dlp succeeds but distillation fails, we must return the partial
    video record so the video isn't re-scraped on retry, and status must
    clearly signal the partial state.
    """
    body = DistillURLRequest(url=VALID_URL)

    # Sequence of fetch_one calls inside the endpoint:
    # 1. Check existing distillation → None
    # 2. Check existing competitor_videos row → None (insert path)
    # 3. INSERT ... RETURNING id → row with id
    fetch_one_responses = [
        None,
        None,
        {"id": "22222222-2222-2222-2222-222222222222"},
    ]
    fetch_one_spy = AsyncMock(side_effect=fetch_one_responses)

    async def _fake_execute(*args, **kwargs):
        return None

    def _fake_extract(video_id):
        return _fake_ytdlp_info(video_id)

    async def _distill_fails(tenant_id, cv_id):
        raise RuntimeError("OpenAI rate limit")

    with patch("routes.intelligence.fetch_one", fetch_one_spy), \
         patch("routes.intelligence.execute", new=AsyncMock(side_effect=_fake_execute)), \
         patch("routes.niche._extract_video_info", side_effect=_fake_extract), \
         patch("distillation.pipeline.distill_competitor_video", side_effect=_distill_fails):
        result = _run(distill_from_url(body, tenant_id=TENANT))

    assert result["status"] == "scraped_but_distillation_failed"
    assert result["video_id"] == VIDEO_ID
    assert result["has_transcript"] is True
    assert "OpenAI rate limit" in result.get("error", "")
    print("✅ test_distill_distillation_failure_returns_partial")


# ───────────────────────── runner ─────────────────────────

TESTS = [
    test_extract_video_id_standard_watch_url,
    test_extract_video_id_short_url,
    test_extract_video_id_shorts_url,
    test_extract_video_id_embed_url,
    test_extract_video_id_with_extra_params,
    test_extract_video_id_returns_none_for_garbage,
    test_distill_invalid_url_returns_400,
    test_distill_ytdlp_failure_returns_humanized_502,
    test_distill_ytdlp_returns_none_returns_404,
    test_distill_idempotent_second_call_skips_ytdlp,
    test_distill_idempotent_handles_stringified_metadata,
    test_distill_distillation_failure_returns_partial,
]


def main() -> int:
    # Get a fresh event loop for the _run helper.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    failed = 0
    for t in TESTS:
        try:
            t()
        except AssertionError as e:
            print(f"❌ {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ {t.__name__}: {type(e).__name__}: {e}")
            failed += 1

    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
