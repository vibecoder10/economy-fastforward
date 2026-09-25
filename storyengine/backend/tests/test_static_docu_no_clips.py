"""A static documentary never animates: no motion scripts, no paid clips.

2026-09-25: a calendar-queue DvsU video (render_mode='static_docu') had no
stage plan, so its build ran motion scripts and 59 paid Grok Imagine clips.
The guard now lives inside run_video_scripts / run_video_generation (every
caller hits it) and in run_next_step, keyed on render_path_needs_clips, and
returns before _ensure_initialized (no vault keys, no provider call).

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/test_static_docu_no_clips.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pipeline_executor as pe_mod  # noqa: E402
from pipeline_executor import PipelineExecutor  # noqa: E402

TENANT = "tenant-static-clips"
VIDEO = "video-static-clips"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _static_video(status: str, **extra) -> dict:
    row = {
        "id": VIDEO, "status": status, "tenant_id": TENANT,
        "custom_film_plan_id": None, "render_mode": "static_docu",
        "dialogue_audio": None, "dialogue_mode": "narration_only",
        "pipeline_stages": None,  # the queue bug: no plan at all
    }
    row.update(extra)
    return row


def _patch(monkeypatch, ex: PipelineExecutor, video: dict):
    async def _fake_fetch_one(query, *args):
        return dict(video)

    writes = []

    async def _fake_execute(query, *args):
        writes.append((query, args))
        return "UPDATE 1"

    async def _boom():
        raise AssertionError("a static video must never initialize clip generation")

    monkeypatch.setattr(pe_mod, "fetch_one", _fake_fetch_one)
    monkeypatch.setattr(pe_mod, "execute", _fake_execute)
    monkeypatch.setattr(ex, "_ensure_initialized", _boom)
    return writes


def test_run_video_generation_skips_static_video_without_plan(monkeypatch):
    ex = PipelineExecutor(TENANT)
    _patch(monkeypatch, ex, _static_video("ready_for_video_generation"))

    result = _run(ex.run_video_generation(VIDEO))

    assert result["skipped_stage"] == "video"
    assert result["status"] == "ready_for_thumbnail"
    assert ex._pipeline is None


def test_run_video_scripts_skips_straight_past_clip_generation(monkeypatch):
    ex = PipelineExecutor(TENANT)
    _patch(monkeypatch, ex, _static_video("ready_for_video_scripts"))

    result = _run(ex.run_video_scripts(VIDEO))

    assert result["skipped_stage"] == "video"
    assert result["status"] == "ready_for_thumbnail"


def test_static_plan_is_honored_after_the_skip(monkeypatch):
    ex = PipelineExecutor(TENANT)
    plan = '["research", "script", "voice", "images", "render", "upload"]'
    _patch(monkeypatch, ex, _static_video("ready_for_video_generation", pipeline_stages=plan))

    result = _run(ex.run_video_generation(VIDEO))

    # thumbnail is off in this plan, so the skip lands on render
    assert result["status"] == "ready_to_render"


def test_queue_launch_stamps_the_static_plan():
    src = open(os.path.join(os.path.dirname(__file__), "..", "routes", "queue.py")).read()
    assert "static_mode_for_tenant" in src
    assert "pipeline_stages=COALESCE(pipeline_stages, $3::jsonb)" in src
    assert "static_stage_plan(None)" in src
