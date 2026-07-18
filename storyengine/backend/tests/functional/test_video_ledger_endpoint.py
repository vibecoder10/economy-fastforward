"""GET /api/videos/{id}/ledger (checklist §0.3d / C10) — the read endpoint
backing the video-detail cost chip's drawer and the copilot's "how much has
this cost?" answer.

Locks:
- 404 when the video doesn't exist (or belongs to another tenant).
- `total_cost` in the response is read straight off the videos row (the
  generation_ledger rollup — see generation_ledger.py), NOT re-summed here,
  so the chip and the drawer can never disagree.
- `by_stage` groups actual_cost per stage, rounded to cents.
- `rows` carries every ledger row, in insertion order, with the fields the
  drawer needs (stage, model, units, unit_cost, actual_cost, kie_task_id,
  created_at) — tenant/video scoping trusted to the SQL WHERE clause (real
  DB, not re-tested here).
- A video with zero ledger rows still returns 200 with an empty list/dict,
  never a 500 — the "$0.00 actual" empty state the UI needs.

Calls the route function directly (bypassing FastAPI's Depends wiring, same
pattern as this suite already uses) with routes.videos.fetch_one/fetch_all
monkeypatched to an in-memory fixture — no live DB.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_video_ledger_endpoint.py -q
"""
import asyncio

import pytest
from fastapi import HTTPException

import routes.videos as videos_route

TENANT = "tenant-1"
VIDEO = "video-1"


_UNSET = object()


def _install_fake_db(monkeypatch, *, video=_UNSET, ledger_rows=None):
    video = {"id": VIDEO, "total_cost": 0} if video is _UNSET else video
    ledger_rows = ledger_rows or []

    async def fake_fetch_one(query, *args):
        assert "FROM videos" in query
        return video

    async def fake_fetch_all(query, *args):
        assert "FROM generation_ledger" in query
        return ledger_rows

    monkeypatch.setattr(videos_route, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(videos_route, "fetch_all", fake_fetch_all)


def test_404_when_video_missing(monkeypatch):
    _install_fake_db(monkeypatch, video=None)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(videos_route.get_video_ledger(VIDEO, tenant_id=TENANT))
    assert exc.value.status_code == 404


def test_empty_ledger_returns_zero_actual_not_500(monkeypatch):
    """The $0-spend video the UI must render without a broken empty state."""
    _install_fake_db(monkeypatch, video={"id": VIDEO, "total_cost": 0}, ledger_rows=[])
    result = asyncio.run(videos_route.get_video_ledger(VIDEO, tenant_id=TENANT))
    assert result.video_id == VIDEO
    assert result.total_cost == 0
    assert result.by_stage == {}
    assert result.rows == []


def test_total_cost_comes_from_videos_row_not_a_resum(monkeypatch):
    """Even if the ledger rows visible to this query summed to something else,
    the response's total_cost must be the videos.total_cost value verbatim —
    it's the same number the chip's "Actual" side reads, and they must never
    disagree."""
    _install_fake_db(
        monkeypatch,
        video={"id": VIDEO, "total_cost": 999.99},
        ledger_rows=[{
            "stage": "pictures", "model": "gpt-image-2", "units": 1, "unit_cost": 0.05,
            "actual_cost": 0.05, "kie_task_id": "t1", "created_at": "2026-07-18T00:00:00",
        }],
    )
    result = asyncio.run(videos_route.get_video_ledger(VIDEO, tenant_id=TENANT))
    assert result.total_cost == 999.99


def test_rows_grouped_and_summed_by_stage(monkeypatch):
    ledger_rows = [
        {"stage": "pictures", "model": "gpt-image-2", "units": 1, "unit_cost": 0.05,
         "actual_cost": 0.05, "kie_task_id": "t1", "created_at": "2026-07-18T00:00:01"},
        {"stage": "pictures", "model": "gpt-image-2", "units": 1, "unit_cost": 0.05,
         "actual_cost": 0.05, "kie_task_id": "t2", "created_at": "2026-07-18T00:00:02"},
        {"stage": "clips", "model": "grok-imagine", "units": 8, "unit_cost": 0.015,
         "actual_cost": 0.12, "kie_task_id": "t3", "created_at": "2026-07-18T00:00:03"},
        {"stage": "voice", "model": None, "units": 500, "unit_cost": 0.0003,
         "actual_cost": 0.15, "kie_task_id": None, "created_at": "2026-07-18T00:00:04"},
    ]
    _install_fake_db(
        monkeypatch,
        video={"id": VIDEO, "total_cost": 0.32},
        ledger_rows=ledger_rows,
    )
    result = asyncio.run(videos_route.get_video_ledger(VIDEO, tenant_id=TENANT))

    assert result.by_stage == {"pictures": 0.10, "clips": 0.12, "voice": 0.15}
    assert round(sum(result.by_stage.values()), 2) == 0.37  # not the same as total_cost (see below)
    # by_stage sums the ledger rows visible to this read; total_cost is the
    # videos-row rollup — this fixture intentionally sets them to differ
    # (0.32 vs 0.37) to prove the endpoint never silently substitutes one
    # for the other.
    assert result.total_cost == 0.32
    assert len(result.rows) == 4
    assert result.rows[0].stage == "pictures"
    assert result.rows[0].kie_task_id == "t1"
    assert result.rows[3].stage == "voice"
    assert result.rows[3].model is None


def test_unknown_stage_falls_back_to_other(monkeypatch):
    _install_fake_db(
        monkeypatch,
        video={"id": VIDEO, "total_cost": 0.02},
        ledger_rows=[{
            "stage": None, "model": None, "units": 1, "unit_cost": 0.02,
            "actual_cost": 0.02, "kie_task_id": None, "created_at": "2026-07-18T00:00:00",
        }],
    )
    result = asyncio.run(videos_route.get_video_ledger(VIDEO, tenant_id=TENANT))
    assert result.by_stage == {"other": 0.02}
    assert result.rows[0].stage == "other"
