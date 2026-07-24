"""Regression tests for StoryEngine's granular YouTube quota guard.

No network and no real database. The fake intentionally requires
``datetime.date`` parameters to match asyncpg's DATE codec.
"""
import asyncio
import os
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import youtube_quota  # noqa: E402


class _FakeQuotaDB:
    def __init__(self):
        self.rows: dict[date, dict[str, int]] = {}
        self.raise_on_read = False
        self.raise_on_write = False
        self.seen_days: list[date] = []
        self.lock = asyncio.Lock()

    async def fetch_one(self, query, *args):
        assert "video_uploads_used" in query and "search_calls_used" in query
        if self.raise_on_read:
            raise RuntimeError("simulated quota read outage")
        if "INSERT INTO youtube_quota_usage" in query:
            if len(args) == 2:
                day, search_limit = args
                assert type(day) is date
                async with self.lock:
                    row = self.rows.setdefault(
                        day,
                        {"units_used": 0, "video_uploads_used": 0, "search_calls_used": 0},
                    )
                    if row["search_calls_used"] + 1 > search_limit:
                        return None
                    row["search_calls_used"] += 1
                    return dict(row)
            day, general, general_ceiling, upload_limit = args
            assert type(day) is date
            async with self.lock:
                row = self.rows.setdefault(
                    day,
                    {"units_used": 0, "video_uploads_used": 0, "search_calls_used": 0},
                )
                if (
                    row["units_used"] + general > general_ceiling
                    or row["video_uploads_used"] + 1 > upload_limit
                ):
                    return None
                row["units_used"] += general
                row["video_uploads_used"] += 1
                return dict(row)
        day = args[0]
        assert type(day) is date
        self.seen_days.append(day)
        return self.rows.get(day)

    async def execute(self, query, *args):
        if self.raise_on_write:
            raise RuntimeError("simulated quota write outage")
        if "UPDATE youtube_quota_usage SET" in query:
            day, general, uploads = args
            row = self.rows[day]
            row["units_used"] = max(row["units_used"] - general, 0)
            row["video_uploads_used"] = max(
                row["video_uploads_used"] - uploads, 0
            )
            return "UPDATE 1"
        assert "INSERT INTO youtube_quota_usage" in query
        day, general, uploads, searches = args
        assert type(day) is date
        self.seen_days.append(day)
        row = self.rows.setdefault(
            day,
            {"units_used": 0, "video_uploads_used": 0, "search_calls_used": 0},
        )
        row["units_used"] += general
        row["video_uploads_used"] += uploads
        row["search_calls_used"] += searches
        return "INSERT 0 1"


def _install(monkeypatch, fake: _FakeQuotaDB, day: date = date(2026, 7, 19)):
    monkeypatch.setattr(youtube_quota, "fetch_one", fake.fetch_one)
    monkeypatch.setattr(youtube_quota, "execute", fake.execute)
    monkeypatch.setattr(youtube_quota, "_pt_today", lambda: day)


def _record_upload(monkeypatch, fake: _FakeQuotaDB, *, thumbnail=False):
    _install(monkeypatch, fake)
    asyncio.run(youtube_quota.record_video_upload(thumbnail_succeeded=thumbnail))


def test_date_parameter_is_date_but_api_json_is_iso_string(monkeypatch):
    fake = _FakeQuotaDB()
    _install(monkeypatch, fake)
    asyncio.run(youtube_quota.record_units(1, "videos.list"))
    status = asyncio.run(youtube_quota.get_quota_status())
    assert fake.seen_days and all(type(day) is date for day in fake.seen_days)
    assert status["date_pt"] == "2026-07-19"
    assert isinstance(status["date_pt"], str)


def test_independent_buckets_and_backward_compatible_general_fields(monkeypatch):
    fake = _FakeQuotaDB()
    _install(monkeypatch, fake)
    asyncio.run(youtube_quota.record_units(7, "list calls"))
    asyncio.run(youtube_quota.record_video_upload(thumbnail_succeeded=True))
    asyncio.run(youtube_quota.record_search_call())

    status = asyncio.run(youtube_quota.get_quota_status())
    assert status["units_used"] == 57
    assert status["ceiling"] == status["general"]["limit"] == 9000
    assert status["remaining"] == 8943
    assert status["general"]["project_limit"] == 10_000
    assert status["video_uploads"]["used"] == 1
    assert status["search_calls"]["used"] == 1


def test_default_limits_and_env_overrides(monkeypatch):
    for name in (
        "YOUTUBE_GENERAL_DAILY_LIMIT",
        "YOUTUBE_GENERAL_QUOTA_CEILING",
        "YOUTUBE_DAILY_QUOTA_CEILING",
        "YOUTUBE_VIDEO_UPLOAD_DAILY_LIMIT",
        "YOUTUBE_SEARCH_DAILY_LIMIT",
    ):
        monkeypatch.delenv(name, raising=False)
    assert youtube_quota._general_limit() == 10_000
    assert youtube_quota._ceiling() == 9_000
    assert youtube_quota._video_upload_limit() == 100
    assert youtube_quota._search_call_limit() == 100

    monkeypatch.setenv("YOUTUBE_GENERAL_DAILY_LIMIT", "12000")
    monkeypatch.setenv("YOUTUBE_GENERAL_QUOTA_CEILING", "11000")
    monkeypatch.setenv("YOUTUBE_VIDEO_UPLOAD_DAILY_LIMIT", "150")
    monkeypatch.setenv("YOUTUBE_SEARCH_DAILY_LIMIT", "125")
    assert youtube_quota._general_limit() == 12_000
    assert youtube_quota._ceiling() == 11_000
    assert youtube_quota._video_upload_limit() == 150
    assert youtube_quota._search_call_limit() == 125


def test_general_ceiling_is_clamped_to_lower_project_limit(monkeypatch):
    monkeypatch.setenv("YOUTUBE_GENERAL_DAILY_LIMIT", "8000")
    monkeypatch.setenv("YOUTUBE_GENERAL_QUOTA_CEILING", "9000")
    assert youtube_quota._configured_ceiling() == 9000
    assert youtube_quota._ceiling() == 8000
    fake = _FakeQuotaDB()
    _install(monkeypatch, fake)
    asyncio.run(youtube_quota.record_units(7990, "fixture"))
    ok, status = asyncio.run(youtube_quota.check_quota_available(11))
    assert ok is False
    assert status["ceiling"] == status["general"]["limit"] == 8000
    assert status["general"]["configured_ceiling"] == 9000


def test_100th_upload_allowed_and_101st_blocked(monkeypatch):
    fake = _FakeQuotaDB()
    _install(monkeypatch, fake)
    fake.rows[date(2026, 7, 19)] = {
        "units_used": 0,
        "video_uploads_used": 99,
        "search_calls_used": 0,
    }
    ok, _ = asyncio.run(youtube_quota.reserve_upload(False))
    assert ok is True
    ok, status = asyncio.run(youtube_quota.reserve_upload(False))
    assert ok is False
    assert status["exhausted_bucket"] == "video_uploads"
    assert status["video_uploads"] == {"used": 100, "limit": 100, "remaining": 0}
    msg = youtube_quota.quota_exceeded_message(status)
    assert "video upload quota" in msg
    assert "100/100" in msg
    assert "midnight Pacific" in msg


def test_search_exhaustion_does_not_block_upload_bucket(monkeypatch):
    fake = _FakeQuotaDB()
    _install(monkeypatch, fake)
    for _ in range(100):
        asyncio.run(youtube_quota.record_search_call())

    upload_ok, _ = asyncio.run(
        youtube_quota.check_quota_available(video_uploads_needed=1)
    )
    search_ok, status = asyncio.run(
        youtube_quota.check_quota_available(search_calls_needed=1)
    )
    assert upload_ok is True
    assert search_ok is False
    assert status["exhausted_bucket"] == "search_calls"
    assert "YouTube search quota" in youtube_quota.quota_exceeded_message(status)


def test_general_exhaustion_does_not_block_upload_without_thumbnail(monkeypatch):
    fake = _FakeQuotaDB()
    _install(monkeypatch, fake)
    asyncio.run(youtube_quota.record_units(9000, "list calls"))
    upload_ok, _ = asyncio.run(
        youtube_quota.check_quota_available(0, video_uploads_needed=1)
    )
    thumbnail_ok, status = asyncio.run(
        youtube_quota.check_quota_available(50, video_uploads_needed=1)
    )
    assert upload_ok is True
    assert thumbnail_ok is False
    assert status["exhausted_bucket"] == "general"
    assert "general API unit quota" in youtube_quota.quota_exceeded_message(status)


def test_thumbnail_general_units_record_only_when_succeeded(monkeypatch):
    fake = _FakeQuotaDB()
    _install(monkeypatch, fake)
    asyncio.run(youtube_quota.record_video_upload(thumbnail_succeeded=False))
    asyncio.run(youtube_quota.record_video_upload(thumbnail_succeeded=True))
    row = fake.rows[date(2026, 7, 19)]
    assert row == {
        "units_used": 50,
        "video_uploads_used": 2,
        "search_calls_used": 0,
    }


def test_concurrent_upload_reservations_at_99_allow_exactly_one(monkeypatch):
    fake = _FakeQuotaDB()
    _install(monkeypatch, fake)
    fake.rows[date(2026, 7, 19)] = {
        "units_used": 0,
        "video_uploads_used": 99,
        "search_calls_used": 0,
    }

    async def race():
        return await asyncio.gather(
            youtube_quota.reserve_upload(False),
            youtube_quota.reserve_upload(False),
        )

    results = asyncio.run(race())
    assert sorted(ok for ok, _ in results) == [False, True]
    assert fake.rows[date(2026, 7, 19)]["video_uploads_used"] == 100


def test_concurrent_search_reservations_at_99_allow_exactly_one(monkeypatch):
    fake = _FakeQuotaDB()
    _install(monkeypatch, fake)
    fake.rows[date(2026, 7, 19)] = {
        "units_used": 0,
        "video_uploads_used": 0,
        "search_calls_used": 99,
    }

    async def race():
        return await asyncio.gather(
            youtube_quota.reserve_search_call(),
            youtube_quota.reserve_search_call(),
        )

    results = asyncio.run(race())
    assert sorted(ok for ok, _ in results) == [False, True]
    assert fake.rows[date(2026, 7, 19)]["search_calls_used"] == 100


def test_release_reservation_is_once_only_and_cannot_underflow(monkeypatch):
    fake = _FakeQuotaDB()
    _install(monkeypatch, fake)
    ok, status = asyncio.run(youtube_quota.reserve_upload(True))
    assert ok is True
    reservation = status["reservation"]
    asyncio.run(
        youtube_quota.release_upload_reservation(
            reservation, release_upload=True, release_general=True
        )
    )
    asyncio.run(
        youtube_quota.release_upload_reservation(
            reservation, release_upload=True, release_general=True
        )
    )
    assert fake.rows[date(2026, 7, 19)]["units_used"] == 0
    assert fake.rows[date(2026, 7, 19)]["video_uploads_used"] == 0


def test_read_and_write_failures_are_soft(monkeypatch):
    fake = _FakeQuotaDB()
    fake.raise_on_read = True
    _install(monkeypatch, fake)
    ok, status = asyncio.run(
        youtube_quota.check_quota_available(50, video_uploads_needed=1)
    )
    assert ok is True
    assert status["units_used"] == 0

    fake.raise_on_write = True
    asyncio.run(youtube_quota.record_video_upload(thumbnail_succeeded=True))
    asyncio.run(youtube_quota.record_search_call())


def test_new_pacific_day_resets_all_buckets(monkeypatch):
    fake = _FakeQuotaDB()
    _install(monkeypatch, fake, date(2026, 7, 19))
    asyncio.run(
        youtube_quota.record_quota_usage(
            general_units=100, video_uploads=2, search_calls=3, operation="fixture"
        )
    )
    monkeypatch.setattr(youtube_quota, "_pt_today", lambda: date(2026, 7, 20))
    status = asyncio.run(youtube_quota.get_quota_status())
    assert status["date_pt"] == "2026-07-20"
    assert status["units_used"] == 0
    assert status["video_uploads"]["used"] == 0
    assert status["search_calls"]["used"] == 0


def test_pt_today_returns_date_in_pacific_timezone():
    assert type(youtube_quota._pt_today()) is date


def test_health_endpoints_keep_top_level_general_fields(monkeypatch):
    import main

    fake = _FakeQuotaDB()
    _install(monkeypatch, fake)
    main.app.state.arq = None
    health = asyncio.run(main.health())
    assert health["youtube_quota"]["units_used"] == 0
    assert health["youtube_quota"]["ceiling"] == 9000
    assert health["youtube_quota"]["video_uploads"]["limit"] == 100

    monkeypatch.setenv("HEALTH_TOKEN", "test-token")
    request = SimpleNamespace(headers={"authorization": "Bearer test-token"})
    detailed = asyncio.run(main.health_detailed(request))
    assert detailed["youtube_quota"]["search_calls"]["limit"] == 100


def test_migration_129_is_additive_idempotent_and_fresh_schema_matches():
    backend = Path(__file__).resolve().parents[2]
    migration = (backend / "migrations/129_youtube_granular_quota.sql").read_text()
    schema = (backend.parent / "schema.sql").read_text()
    assert "ADD COLUMN IF NOT EXISTS video_uploads_used" in migration
    assert "ADD COLUMN IF NOT EXISTS search_calls_used" in migration
    assert "UPDATE youtube_quota_usage" not in migration
    assert "DROP " not in migration
    assert "video_uploads_used INTEGER NOT NULL DEFAULT 0" in schema
    assert "search_calls_used INTEGER NOT NULL DEFAULT 0" in schema
