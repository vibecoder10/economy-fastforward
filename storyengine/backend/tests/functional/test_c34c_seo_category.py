"""Tests for C34c (checklist S10-6, docs/reports/2026-07-17-storyengine-agent-
audit-findings.md §S10): the YouTube category id computed by
`generate_and_store_seo()` was thrown away instead of persisted, so
`upload_video_to_youtube()` always shipped the hardcoded `_DEFAULT_CATEGORY`
("27" — Education) regardless of what the SEO pass determined the video's
real category to be.

Migration 102 adds `videos.seo_category_id`. This pins:

  1. `generate_and_store_seo()` writes the computed category into
     `seo_category_id` in the same UPDATE as the other SEO fields.
  2. `upload_video_to_youtube()` reads `seo_category_id` and passes it through
     to `_do_youtube_upload()` as the real `category_id` argument.
  3. Fallback: a video with no `seo_category_id` (SEO never generated, or
     predates migration 102) still uploads with `_DEFAULT_CATEGORY` ("27") —
     pure additive, backward-compatible change.

No network, no real DB — `database`'s three functions and `youtube_quota`'s
guard are monkeypatched directly on the `youtube_publish` module (mirrors the
pattern in test_c34a_upload_no_legacy_fallback.py / test_c33_youtube_quota.py).

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c34c_seo_category.py -q
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import youtube_publish  # noqa: E402

TENANT = "tenant-1"
VIDEO = "video-1"


# ---------------------------------------------------------------------------
# 1. generate_and_store_seo persists the computed category
# ---------------------------------------------------------------------------

class _FakeClaudeClient:
    def __init__(self, category="entertainment"):
        self._category = category

    async def generate(self, **kwargs):
        return json.dumps({
            "description": "A fun video about something specific.",
            "tags": ["tag1", "tag2"],
            "hashtags": ["fun", "video", "clip"],
            "category": self._category,
        })


def test_generate_and_store_seo_persists_category_id(monkeypatch):
    execute_calls = []

    async def fake_fetch_one(query, *args):
        if "FROM videos WHERE id" in query:
            return {"video_title": "A Fun Video"}
        if "FROM channel_profiles" in query:
            return {"channel_name": "Test Channel", "youtube_channel_name": None,
                     "niche": "entertainment", "target_audience": "general"}
        raise AssertionError(f"unexpected fetch_one query: {query}")

    async def fake_fetch_all(query, *args):
        return []

    async def fake_execute(query, *args):
        execute_calls.append((query, args))
        return "UPDATE 1"

    async def fake_get_text_client_for_tenant(tenant_id):
        return _FakeClaudeClient(category="entertainment")

    monkeypatch.setattr(youtube_publish, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(youtube_publish, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(youtube_publish, "execute", fake_execute)
    monkeypatch.setattr(youtube_publish, "get_text_client_for_tenant",
                         fake_get_text_client_for_tenant)

    result = asyncio.run(youtube_publish.generate_and_store_seo(VIDEO, TENANT))

    assert result["category_id"] == "24"  # entertainment -> YouTube category 24
    assert len(execute_calls) == 1
    query, args = execute_calls[0]
    assert "seo_category_id" in query
    assert "24" in args, f"expected the computed category '24' in the UPDATE args, got {args}"


def test_generate_and_store_seo_defaults_to_education_for_unknown_category(monkeypatch):
    execute_calls = []

    async def fake_fetch_one(query, *args):
        if "FROM videos WHERE id" in query:
            return {"video_title": "A Video"}
        if "FROM channel_profiles" in query:
            return None
        raise AssertionError(f"unexpected fetch_one query: {query}")

    async def fake_fetch_all(query, *args):
        return []

    async def fake_execute(query, *args):
        execute_calls.append((query, args))
        return "UPDATE 1"

    async def fake_get_text_client_for_tenant(tenant_id):
        return _FakeClaudeClient(category="not-a-real-category")

    monkeypatch.setattr(youtube_publish, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(youtube_publish, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(youtube_publish, "execute", fake_execute)
    monkeypatch.setattr(youtube_publish, "get_text_client_for_tenant",
                         fake_get_text_client_for_tenant)

    result = asyncio.run(youtube_publish.generate_and_store_seo(VIDEO, TENANT))

    assert result["category_id"] == youtube_publish._DEFAULT_CATEGORY == "27"
    query, args = execute_calls[0]
    assert "27" in args


# ---------------------------------------------------------------------------
# 2 + 3. upload_video_to_youtube passes the stored category through, with the
#        "27" fallback when it's absent
# ---------------------------------------------------------------------------

def _video_row(**over):
    base = {
        "video_title": "Test Video",
        "final_video_url": "https://drive.google.com/file/d/abc123/view",
        "thumbnail_url": None,
        "seo_description": "A description.",
        "seo_tags": "tag1,tag2",
        "seo_category_id": None,
    }
    base.update(over)
    return base


def _install_upload_plumbing(monkeypatch, video_row, captured):
    async def fake_fetch_one(query, *args):
        if "FROM videos WHERE id" in query:
            return video_row
        if "FROM channel_profiles" in query:
            return {"youtube_refresh_token": "fake-refresh-token",
                     "youtube_channel_name": "Test Channel"}
        raise AssertionError(f"unexpected fetch_one query: {query}")

    async def fake_execute(query, *args):
        return "UPDATE 1"

    async def fake_reserve_upload(*, has_thumbnail):
        return True, {"reservation": {"tracked": False}}

    async def fake_release_upload_reservation(
        reservation, *, release_upload, release_general
    ):
        return None

    async def fake_download_to_local(url, dest):
        # Real _do_youtube_upload is stubbed below and never touches the
        # filesystem, so this only needs to not raise.
        return None

    def fake_do_youtube_upload(refresh_token, video_path, thumb_path, title,
                                description, tags, category_id, privacy, made_for_kids):
        captured["category_id"] = category_id
        return {"youtube_video_id": "abc12345678",
                "youtube_url": "https://www.youtube.com/watch?v=abc12345678",
                "thumbnail_succeeded": False}

    monkeypatch.setattr(youtube_publish, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(youtube_publish, "execute", fake_execute)
    monkeypatch.setattr(youtube_publish, "reserve_upload", fake_reserve_upload)
    monkeypatch.setattr(
        youtube_publish,
        "release_upload_reservation",
        fake_release_upload_reservation,
    )
    monkeypatch.setattr(youtube_publish, "_download_to_local", fake_download_to_local)
    monkeypatch.setattr(youtube_publish, "_do_youtube_upload", fake_do_youtube_upload)


def test_upload_passes_through_the_computed_category(monkeypatch):
    captured = {}
    video_row = _video_row(seo_category_id="24")
    _install_upload_plumbing(monkeypatch, video_row, captured)

    result = asyncio.run(youtube_publish.upload_video_to_youtube(VIDEO, TENANT))

    assert captured["category_id"] == "24"
    assert result["youtube_video_id"] == "abc12345678"


def test_upload_falls_back_to_default_category_when_absent(monkeypatch):
    captured = {}
    video_row = _video_row(seo_category_id=None)
    _install_upload_plumbing(monkeypatch, video_row, captured)

    asyncio.run(youtube_publish.upload_video_to_youtube(VIDEO, TENANT))

    assert captured["category_id"] == youtube_publish._DEFAULT_CATEGORY == "27"


def test_upload_falls_back_to_default_category_when_blank_string(monkeypatch):
    """seo_category_id could round-trip as '' rather than NULL depending on
    the writer — both must fall back identically."""
    captured = {}
    video_row = _video_row(seo_category_id="")
    _install_upload_plumbing(monkeypatch, video_row, captured)

    asyncio.run(youtube_publish.upload_video_to_youtube(VIDEO, TENANT))

    assert captured["category_id"] == youtube_publish._DEFAULT_CATEGORY == "27"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
