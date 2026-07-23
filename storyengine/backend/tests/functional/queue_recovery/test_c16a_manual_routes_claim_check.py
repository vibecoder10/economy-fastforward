"""C16a (S7-6 MED, docs/reports/2026-07-17-storyengine-agent-audit-findings.md
§S7-6): the manual routes/pipeline.py (+ videos.py/environments.py/
characters.py) endpoints' `_is_task_active` gate now consults the SAME
generation_claims DB table chat's dispatch acquires — not just the
restart-fragile in-process `_running_tasks`/`_side_lanes` dicts.

This pins:

  1. `_is_task_active` is now `async def` — every one of its ~35 call sites
     across routes/pipeline.py, videos.py, environments.py, characters.py
     was updated to `await` it (a static regression lock for that: no bare
     `if _is_task_active(` — i.e. an unawaited call — remains anywhere).
  2. When the in-process dict/lanes are CLEAR, `_is_task_active` consults
     `generation_claims.is_blocked()` and returns whatever it says — so a
     claim held by chat's autobuild (which C16a's own commit gates) blocks
     a manual click too.
  3. When the in-process dict/lanes ALREADY say busy, the DB is not even
     consulted (fast path unchanged, no unnecessary DB round-trip on the
     hot "someone's already using the dict" path).

Reuses this directory's conftest.py heavy-mock fixture (stubs asyncpg/
database/error_utils/status_map/... and evicts routes.pipeline after each
test so module-level _running_tasks/_side_lanes state never leaks between
tests).

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/queue_recovery/test_c16a_manual_routes_claim_check.py -q
"""
import re
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import routes.pipeline as pipeline


@pytest.fixture(autouse=True)
def _normal_drain_state():
    """These claim-lane tests isolate _is_task_active; drain is normal."""
    with patch.object(
        pipeline.drain_mode,
        "assert_accepting_new_work",
        new=AsyncMock(return_value=None),
    ):
        yield


# --- 1. static regression lock: no unawaited _is_task_active( call sites ---

def test_no_unawaited_is_task_active_call_sites():
    """Every call site of the form `if _is_task_active(` (missing `await`)
    would silently pass a coroutine object as truthy — ALWAYS true, wedging
    every manual route as permanently 'busy'. None may remain."""
    backend_root = Path(__file__).resolve().parents[3]
    offenders = []
    for rel in ("routes/pipeline.py", "routes/videos.py", "routes/environments.py", "routes/characters.py"):
        text = (backend_root / rel).read_text()
        for m in re.finditer(r"if\s+_is_task_active\(", text):
            offenders.append(f"{rel}: {text[:m.start()].count(chr(10)) + 1}")
    assert offenders == [], f"unawaited _is_task_active( call sites found: {offenders}"
    print("✅ test_no_unawaited_is_task_active_call_sites")


def test_is_task_active_is_async():
    import inspect
    assert inspect.iscoroutinefunction(pipeline._is_task_active), (
        "_is_task_active must be async — it now consults the DB claims table"
    )
    print("✅ test_is_task_active_is_async")


# --- 2. DB consultation when the in-process dict is clear -------------------

@pytest.mark.asyncio
async def test_consults_db_when_in_process_dict_is_clear_and_db_says_busy():
    with patch("generation_claims.is_blocked", new=AsyncMock(return_value=True)) as mock_blocked:
        result = await pipeline._is_task_active("video-db1", "tenant-db1", lane="main")
    assert result is True, "a DB-held claim (e.g. from chat) must make a manual route see 'busy' too"
    mock_blocked.assert_awaited_once_with("tenant-db1", "video-db1", "main")
    print("✅ test_consults_db_when_in_process_dict_is_clear_and_db_says_busy")


@pytest.mark.asyncio
async def test_consults_db_when_in_process_dict_is_clear_and_db_says_free():
    with patch("generation_claims.is_blocked", new=AsyncMock(return_value=False)) as mock_blocked:
        result = await pipeline._is_task_active("video-db2", "tenant-db2", lane="voice")
    assert result is False
    mock_blocked.assert_awaited_once_with("tenant-db2", "video-db2", "voice")
    print("✅ test_consults_db_when_in_process_dict_is_clear_and_db_says_free")


# --- 3. in-process dict busy short-circuits before ever touching the DB ----

@pytest.mark.asyncio
async def test_dict_busy_main_short_circuits_without_touching_db():
    key = ("tenant-db3", "video-db3")
    pipeline._running_tasks[key] = {
        "status": "running", "message": None, "error": None,
        "lane": "main", "started_at": time.time(),
    }
    try:
        with patch("generation_claims.is_blocked", new=AsyncMock(return_value=False)) as mock_blocked:
            result = await pipeline._is_task_active("video-db3", "tenant-db3", lane="main")
        assert result is True, "an in-process 'main' running task must report busy"
        mock_blocked.assert_not_awaited()
    finally:
        pipeline._running_tasks.pop(key, None)
    print("✅ test_dict_busy_main_short_circuits_without_touching_db")


@pytest.mark.asyncio
async def test_dict_busy_side_lane_short_circuits_without_touching_db():
    key = ("tenant-db4", "video-db4")
    pipeline._side_lanes[key] = {"voice": time.time()}
    try:
        with patch("generation_claims.is_blocked", new=AsyncMock(return_value=False)) as mock_blocked:
            result = await pipeline._is_task_active("video-db4", "tenant-db4", lane="voice")
        assert result is True, "an in-process side-lane entry must report busy without a DB round-trip"
        mock_blocked.assert_not_awaited()
    finally:
        pipeline._side_lanes.pop(key, None)
    print("✅ test_dict_busy_side_lane_short_circuits_without_touching_db")


if __name__ == "__main__":
    import pytest as _pytest
    raise SystemExit(_pytest.main([__file__, "-q"]))
