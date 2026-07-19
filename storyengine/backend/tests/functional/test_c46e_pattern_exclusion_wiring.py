"""Wiring tests for checklist C46e item 2 (OR-6 EXPANDED — the exclusion
half of the per-channel pattern capability).

Covers what tests/test_channel_patterns.py (pure resolver + CRUD unit tests)
can't: identity_builder.py's `_ranked_videos` — the REAL style-seed picker
OR-6's motivating example (MostHated-Warships) is about — actually calling
`channel_patterns.confirmed_anti_video_ids` and filtering its result out of
the ranked candidate pool before slicing to `top_n + 4`.

Local/no-spend: every DB call is a fake fetch_all; channel_patterns itself
is monkeypatched at the module-attribute level channel_patterns.
confirmed_anti_video_ids is imported from, matching test_c41_channel_dna.py's
established convention for a lazily-imported sibling module.
"""

import asyncio
import os
import sys

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import identity_builder  # noqa: E402
import channel_patterns  # noqa: E402


def _videos_rows():
    return [
        {"video_id": "yt-1", "title": "Strong Video", "view_count": 100, "thumbnail_url": None, "duration_seconds": 600},
        {"video_id": "yt-2", "title": "Weak Anti-Pattern Video", "view_count": 90, "thumbnail_url": None, "duration_seconds": 600},
        {"video_id": "yt-3", "title": "Medium Video", "view_count": 50, "thumbnail_url": None, "duration_seconds": 600},
    ]


def test_ranked_videos_excludes_confirmed_anti_video(monkeypatch):
    async def fake_fetch_all(query, tenant_id):
        return _videos_rows()

    async def fake_excluded(tenant_id):
        return {"yt-2"}

    monkeypatch.setattr(identity_builder, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(channel_patterns, "confirmed_anti_video_ids", fake_excluded)

    rows = asyncio.run(identity_builder._ranked_videos("tenant-1", limit=10))

    ids = [r["video_id"] for r in rows]
    assert "yt-2" not in ids
    assert set(ids) == {"yt-1", "yt-3"}


def test_ranked_videos_keeps_everything_when_nothing_confirmed(monkeypatch):
    async def fake_fetch_all(query, tenant_id):
        return _videos_rows()

    async def fake_excluded(tenant_id):
        return set()

    monkeypatch.setattr(identity_builder, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(channel_patterns, "confirmed_anti_video_ids", fake_excluded)

    rows = asyncio.run(identity_builder._ranked_videos("tenant-1", limit=10))

    assert {r["video_id"] for r in rows} == {"yt-1", "yt-2", "yt-3"}


def test_ranked_videos_still_ranks_by_view_count_after_exclusion(monkeypatch):
    async def fake_fetch_all(query, tenant_id):
        return _videos_rows()

    async def fake_excluded(tenant_id):
        return {"yt-2"}

    monkeypatch.setattr(identity_builder, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(channel_patterns, "confirmed_anti_video_ids", fake_excluded)

    rows = asyncio.run(identity_builder._ranked_videos("tenant-1", limit=10))

    assert [r["video_id"] for r in rows] == ["yt-1", "yt-3"]  # 100 views, then 50


def test_ranked_videos_respects_limit_after_exclusion(monkeypatch):
    async def fake_fetch_all(query, tenant_id):
        return _videos_rows()

    async def fake_excluded(tenant_id):
        return {"yt-2"}

    monkeypatch.setattr(identity_builder, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(channel_patterns, "confirmed_anti_video_ids", fake_excluded)

    rows = asyncio.run(identity_builder._ranked_videos("tenant-1", limit=1))

    assert len(rows) == 1
    assert rows[0]["video_id"] == "yt-1"
