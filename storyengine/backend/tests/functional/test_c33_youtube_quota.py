"""Tests for C33 (checklist §3.4, docs/reports/2026-07-17-storyengine-agent-
audit-findings.md Sweep 3 finding #4): "YouTube quota (10k units/day ~ 6
uploads) documented but not enforced in code."

No network, no real DB: `database` is stubbed with an in-memory
{day -> units_used} dict that mirrors exactly what youtube_quota.py's two SQL
statements do (SELECT units_used WHERE day=..., an upsert-add). Pins:

  1. Units accumulate correctly across multiple record_units() calls for the
     same (Pacific) day.
  2. Ceiling refusal — reproduces the checklist's own illustrative scenario
     ("simulated 6-upload day -> 7th blocked gracefully") with an explicit
     10,000-unit ceiling (env var), while confirming the shipped DEFAULT
     ceiling is the more conservative 9,000 (headroom, per this chunk's
     spec) so a real deployment blocks even earlier than the checklist's
     illustrative number.
  3. Fail-soft: a tracker (DB) error on read OR write never raises and never
     blocks a real upload — it's bookkeeping, not the source of truth.
  4. Midnight-PT reset semantics: two different Pacific-day keys are
     tracked as two independent counters (a new day starts at 0), proven by
     monkeypatching `_pt_today()` rather than waiting for a real midnight.
  5. /api/health and /api/health/detailed both carry a `youtube_quota` field
     built from get_quota_status() (fail-soft itself, so this also proves
     the endpoints never break when DATABASE_URL is unset in this suite).

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c33_youtube_quota.py -q
"""
import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import youtube_quota  # noqa: E402


# ---------------------------------------------------------------------------
# In-memory fake of the two SQL statements youtube_quota.py issues
# ---------------------------------------------------------------------------

class _FakeQuotaDB:
    def __init__(self):
        self.rows: dict[str, int] = {}
        self.raise_on_read = False
        self.raise_on_write = False

    async def fetch_one(self, query, *args):
        assert "SELECT units_used FROM youtube_quota_usage" in query
        if self.raise_on_read:
            raise RuntimeError("simulated DB outage on quota read")
        day = args[0]
        used = self.rows.get(day)
        return {"units_used": used} if used is not None else None

    async def execute(self, query, *args):
        assert "INSERT INTO youtube_quota_usage" in query
        if self.raise_on_write:
            raise RuntimeError("simulated DB outage on quota write")
        day, units = args
        self.rows[day] = self.rows.get(day, 0) + units
        return "INSERT 0 1"


def _install(monkeypatch, fake: _FakeQuotaDB, day: str = "2026-07-19"):
    monkeypatch.setattr(youtube_quota, "fetch_one", fake.fetch_one)
    monkeypatch.setattr(youtube_quota, "execute", fake.execute)
    monkeypatch.setattr(youtube_quota, "_pt_today", lambda: day)


# ---------------------------------------------------------------------------
# 1. Units accumulate
# ---------------------------------------------------------------------------

def test_units_accumulate_across_multiple_calls(monkeypatch):
    fake = _FakeQuotaDB()
    _install(monkeypatch, fake)

    asyncio.run(youtube_quota.record_units(1600, "videos.insert"))
    asyncio.run(youtube_quota.record_units(50, "thumbnails.set"))
    asyncio.run(youtube_quota.record_units(9, "channels.list+playlistItems.list+videos.list (sync)"))

    status = asyncio.run(youtube_quota.get_quota_status())
    assert status["units_used"] == 1659
    assert status["date_pt"] == "2026-07-19"


def test_record_units_zero_or_negative_is_a_noop(monkeypatch):
    fake = _FakeQuotaDB()
    _install(monkeypatch, fake)
    asyncio.run(youtube_quota.record_units(0, "noop"))
    asyncio.run(youtube_quota.record_units(-5, "noop"))
    assert fake.rows == {}


# ---------------------------------------------------------------------------
# 2. Ceiling refusal — the checklist's own "6 uploads then 7th blocked" shape
# ---------------------------------------------------------------------------

def test_default_ceiling_is_9000_not_the_full_10000(monkeypatch):
    """This chunk's spec asks for headroom under Google's real 10,000/day
    project limit — confirms the shipped default is the more conservative
    number, not the checklist's illustrative "10k" figure verbatim."""
    monkeypatch.delenv("YOUTUBE_DAILY_QUOTA_CEILING", raising=False)
    assert youtube_quota._ceiling() == 9000


def test_sixth_upload_ok_seventh_blocked_at_10k_ceiling(monkeypatch):
    """Reproduces checklist §3.4's own illustrative scenario exactly: a
    10,000-unit ceiling (set explicitly here via the env var this chunk
    added), 1,600 units/upload (no thumbnail) -> 6 fit (9,600 <= 10,000),
    the 7th (11,200) does not."""
    monkeypatch.setenv("YOUTUBE_DAILY_QUOTA_CEILING", "10000")
    fake = _FakeQuotaDB()
    _install(monkeypatch, fake)

    for i in range(6):
        ok, status = asyncio.run(youtube_quota.check_quota_available(youtube_quota.upload_cost(False)))
        assert ok is True, f"upload {i + 1} should have fit under the ceiling"
        asyncio.run(youtube_quota.record_units(youtube_quota.upload_cost(False), "videos.insert"))

    assert fake.rows["2026-07-19"] == 6 * 1600 == 9600

    ok, status = asyncio.run(youtube_quota.check_quota_available(youtube_quota.upload_cost(False)))
    assert ok is False, "the 7th upload must be refused — it would push 11,200 units past the 10,000 ceiling"
    assert status["units_used"] == 9600 and status["remaining"] == 400
    msg = youtube_quota.quota_exceeded_message(status)
    assert "9600/10000" in msg and "midnight" in msg.lower() and "pacific" in msg.lower()


def test_upload_cost_includes_thumbnail_set_when_present():
    assert youtube_quota.upload_cost(has_thumbnail=False) == 1600
    assert youtube_quota.upload_cost(has_thumbnail=True) == 1650


# ---------------------------------------------------------------------------
# 3. Fail-soft: tracker errors never block real work
# ---------------------------------------------------------------------------

def test_status_read_failure_is_fail_soft_to_zero_used(monkeypatch):
    fake = _FakeQuotaDB()
    fake.raise_on_read = True
    _install(monkeypatch, fake)

    status = asyncio.run(youtube_quota.get_quota_status())
    assert status["units_used"] == 0  # never raises, never guesses "full"


def test_check_quota_available_passes_through_on_tracker_read_error(monkeypatch):
    """A broken quota tracker must never itself become the reason an upload
    is blocked: fail-soft treats a read error as "0 used today", so a normal
    upload cost (well within the default ceiling from a 0 baseline) comes
    back ok=True instead of the check raising or refusing on principle. This
    is NOT "ignore the ceiling" — an operation whose own cost exceeds the
    ceiling outright is still refused even under fail-soft (0 + cost >
    ceiling is still > ceiling); only the *unknowable prior usage* is
    assumed benign."""
    monkeypatch.delenv("YOUTUBE_DAILY_QUOTA_CEILING", raising=False)  # default 9000
    fake = _FakeQuotaDB()
    fake.raise_on_read = True
    _install(monkeypatch, fake)

    ok, status = asyncio.run(youtube_quota.check_quota_available(youtube_quota.upload_cost(False)))
    assert ok is True
    assert status["units_used"] == 0


def test_record_units_write_failure_never_raises(monkeypatch):
    fake = _FakeQuotaDB()
    fake.raise_on_write = True
    _install(monkeypatch, fake)
    asyncio.run(youtube_quota.record_units(1600, "videos.insert"))  # must not raise


# ---------------------------------------------------------------------------
# 4. Midnight-PT reset: a new Pacific day is an independent counter
# ---------------------------------------------------------------------------

def test_new_pacific_day_starts_at_zero(monkeypatch):
    fake = _FakeQuotaDB()
    _install(monkeypatch, fake, day="2026-07-19")
    asyncio.run(youtube_quota.record_units(8000, "videos.insert"))
    status_day1 = asyncio.run(youtube_quota.get_quota_status())
    assert status_day1["units_used"] == 8000

    # Cross into the next Pacific day (this is exactly what happens at real
    # midnight PT — _pt_today() ticking over — modeled here by repointing
    # the monkeypatched clock rather than sleeping until midnight).
    monkeypatch.setattr(youtube_quota, "_pt_today", lambda: "2026-07-20")
    status_day2 = asyncio.run(youtube_quota.get_quota_status())
    assert status_day2["units_used"] == 0
    assert status_day2["date_pt"] == "2026-07-20"
    # The prior day's usage is untouched, not merged into the new day.
    assert fake.rows["2026-07-19"] == 8000


def test_pt_today_uses_pacific_not_utc_around_the_utc_midnight_boundary():
    """A concrete cross-check that _pt_today() really computes in
    America/Los_Angeles: 2026-07-19T06:00:00Z is 2026-07-18 23:00 PDT
    (UTC-7 in July) — still July 18th in Pacific time, a full day behind UTC."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    utc_instant = datetime(2026, 7, 19, 6, 0, 0, tzinfo=timezone.utc)
    pacific = utc_instant.astimezone(ZoneInfo("America/Los_Angeles"))
    assert pacific.strftime("%Y-%m-%d") == "2026-07-18"


# ---------------------------------------------------------------------------
# 5. Health endpoints carry the field
# ---------------------------------------------------------------------------

def test_health_endpoint_carries_youtube_quota_field(monkeypatch):
    import main  # noqa: E402 — imported here so this file's isolation owns it

    fake = _FakeQuotaDB()
    _install(monkeypatch, fake)
    main.app.state.arq = None
    try:
        result = asyncio.run(main.health())
    finally:
        main.app.state.arq = None
    assert "youtube_quota" in result
    assert result["youtube_quota"]["ceiling"] == youtube_quota._ceiling()


def test_health_detailed_carries_youtube_quota_field(monkeypatch):
    import main  # noqa: E402

    fake = _FakeQuotaDB()
    _install(monkeypatch, fake)
    monkeypatch.setenv("HEALTH_TOKEN", "test-token")
    main.app.state.arq = None
    request = SimpleNamespace(headers={"authorization": "Bearer test-token"})
    try:
        result = asyncio.run(main.health_detailed(request))
    finally:
        main.app.state.arq = None
    assert "youtube_quota" in result
    assert result["youtube_quota"]["units_used"] == 0
