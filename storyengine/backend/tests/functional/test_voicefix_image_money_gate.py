"""Tests for the voicefix money-gate (root cause #3): image generation must
never run on a video with unvoiced scenes.

Confirmed bypass, traced by reading the actual call paths (not guessed):

  actions.py ACTIONS["images"] = {"calls": [("run_coverage_images", True)]}
  claude_orchestrator.py skill_to_method = {"images": executor.run_coverage_images,
                                             "storyboard": executor.run_coverage_stage, ...}
  pipeline_executor.py's "ready_for_storyboards"/"ready_for_storyboard_images"/
  "ready_for_storyboard_extraction" status-map handlers -> self.run_coverage_stage

None of those three real entry points — the chat "images" verb, the MCP
`images` tool, or ClaudeOrchestrator's autonomous "images"/"storyboard" skill
dispatch — ever went through PipelineExecutor.run_images/run_prompts (the
OLD 3x3-grid path, which DOES have `_check_voice_exists`). run_coverage_images
and run_coverage_stage (the modern, single live image path that superseded
the grid handlers — see their own docstrings) called
scripts.coverage_to_app.generate_coverage_for_video directly, with NO voice
check anywhere in between. That gap is exactly how video 146242df (tenant
tgb29, 0/3 scenes voiced) got billed $1.50 of real image spend three times
after voice silently failed.

This file proves: (1) the gate now exists in both run_coverage_images and
run_coverage_stage, (2) it is skipped only for skip_voice videos, (3) a
single-scene targeted call only requires that ONE scene to be voiced, (4) a
multi-scene/full call requires every scene, and (5) the SAME gate is what
ClaudeOrchestrator.execute()'s "images"/"storyboard" skill dispatch hits —
i.e. the exact call path that let tgb29 through is now closed, not just the
direct method.

No live DB: pipeline_executor.fetch_one/fetch_all/execute are monkeypatched.
No paid generation: scripts.coverage_to_app.generate_coverage_for_video is
patched to an AsyncMock that RAISES if ever called on a blocked video (the
money-safety proof, same convention as test_c16b_coverage_skip_if_done.py
and test_sfx_guard_claude_orchestrator.py's run_sound_prompts boom).

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_voicefix_image_money_gate.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pipeline_executor as pe_mod  # noqa: E402
from pipeline_executor import PipelineExecutor  # noqa: E402
import claude_orchestrator as co_mod  # noqa: E402
from claude_orchestrator import ClaudeOrchestrator, Decision  # noqa: E402

TENANT = "tenant-voicefix"
VIDEO = "video-voicefix"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _video(status: str = "ready_for_storyboards", **extra) -> dict:
    row = {
        "id": VIDEO, "status": status, "tenant_id": TENANT, "video_title": "Voicefix Video",
        "render_mode": None, "skip_voice": False, "source": None,
        "project_id": None, "dialogue_mode": "",
    }
    row.update(extra)
    return row


def _scripts(voiced_scenes: set, total: int = 3) -> list[dict]:
    """scripts rows: voice_over_url set for scenes in voiced_scenes, NULL
    otherwise. No dialogue_segments (narration-only)."""
    return [
        {"voice_over_url": (f"https://drive/scene{i}.mp3" if i in voiced_scenes else None),
         "dialogue_segments": None, "scene": i}
        for i in range(1, total + 1)
    ]


def _patch_db(monkeypatch, video: dict, scripts: list[dict]):
    """fetch_one -> the video row. fetch_all -> the scripts rows, scoped to
    one scene when the query carries the scene filter this fix added.
    execute -> a no-op that records calls for assertions."""
    async def _fake_fetch_one(query, *args):
        return dict(video)

    async def _fake_fetch_all(query, *args):
        if "FROM scripts" in query:
            if "AND scene = $2" in query:
                scene = args[1]
                return [dict(s) for s in scripts if s["scene"] == scene]
            return [dict(s) for s in scripts]
        return []

    calls = []

    async def _fake_execute(query, *args):
        calls.append((query, args))
        return "OK"

    monkeypatch.setattr(pe_mod, "fetch_one", _fake_fetch_one)
    monkeypatch.setattr(pe_mod, "fetch_all", _fake_fetch_all)
    monkeypatch.setattr(pe_mod, "execute", _fake_execute)
    return calls


def _boom_coverage():
    """A generate_coverage_for_video that fails the test loudly if a blocked
    video ever reaches it — the money-safety proof."""
    return AsyncMock(side_effect=AssertionError(
        "generate_coverage_for_video must NEVER be called for a video with unvoiced scenes"))


# =============================================================================
# run_coverage_images — the direct method (actions.py ACTIONS["images"] /
# routes/pipeline.py run_coverage_images / MCP `images` tool all reach this)
# =============================================================================

def test_run_coverage_images_refuses_full_run_with_zero_voiced_scenes(monkeypatch):
    """Reproduces the tgb29 incident directly: 0/3 scenes voiced, full run
    (scene=None) — must refuse, never reach paid generation."""
    video = _video()
    scripts = _scripts(voiced_scenes=set())
    _patch_db(monkeypatch, video, scripts)

    executor = PipelineExecutor(TENANT)
    boom = _boom_coverage()
    with patch("scripts.coverage_to_app.generate_coverage_for_video", boom):
        result = _run(executor.run_coverage_images(VIDEO))

    assert result["status"] == "failed"
    assert "Voice generation must complete" in result["error"]
    assert "3/3 scenes" in result["error"]
    boom.assert_not_awaited()


def test_run_coverage_images_refuses_partial_voice(monkeypatch):
    """Partial voice (2 of 3 scenes) on a full run must still refuse — no
    silent partial spend."""
    video = _video()
    scripts = _scripts(voiced_scenes={1, 2})
    _patch_db(monkeypatch, video, scripts)

    executor = PipelineExecutor(TENANT)
    boom = _boom_coverage()
    with patch("scripts.coverage_to_app.generate_coverage_for_video", boom):
        result = _run(executor.run_coverage_images(VIDEO))

    assert result["status"] == "failed"
    assert "1/3 scenes" in result["error"]
    boom.assert_not_awaited()


def test_run_coverage_images_proceeds_when_fully_voiced(monkeypatch):
    """Regression: a properly voiced video must still draw images normally."""
    video = _video()
    scripts = _scripts(voiced_scenes={1, 2, 3})
    _patch_db(monkeypatch, video, scripts)

    executor = PipelineExecutor(TENANT)
    ok = AsyncMock(return_value={"status": "completed"})
    with patch("scripts.coverage_to_app.generate_coverage_for_video", ok):
        result = _run(executor.run_coverage_images(VIDEO))

    assert result == {"status": "completed"}
    ok.assert_awaited_once()


def test_run_coverage_images_skip_voice_flag_bypasses_gate(monkeypatch):
    """A video that explicitly opted out of AI narration (skip_voice=True)
    must not be blocked by a check that will never pass."""
    video = _video(skip_voice=True)
    scripts = _scripts(voiced_scenes=set())
    _patch_db(monkeypatch, video, scripts)

    executor = PipelineExecutor(TENANT)
    ok = AsyncMock(return_value={"status": "completed"})
    with patch("scripts.coverage_to_app.generate_coverage_for_video", ok):
        result = _run(executor.run_coverage_images(VIDEO))

    assert result == {"status": "completed"}
    ok.assert_awaited_once()


def test_run_coverage_images_targeted_scene_only_checks_that_scene(monkeypatch):
    """A single-scene redraw only needs THAT scene voiced — scene 2 is
    voiced even though scenes 1 and 3 are not."""
    video = _video()
    scripts = _scripts(voiced_scenes={2})
    _patch_db(monkeypatch, video, scripts)

    executor = PipelineExecutor(TENANT)
    ok = AsyncMock(return_value={"status": "completed"})
    with patch("scripts.coverage_to_app.generate_coverage_for_video", ok):
        result = _run(executor.run_coverage_images(VIDEO, scene=2))

    assert result == {"status": "completed"}
    ok.assert_awaited_once()


def test_run_coverage_images_targeted_scene_blocks_on_that_scenes_own_gap(monkeypatch):
    """A single-scene redraw of scene 1 (unvoiced) must still refuse, even
    though scene 2 happens to be voiced — this is the tgb29-shaped case: a
    targeted per-scene image regeneration must not be a loophole."""
    video = _video()
    scripts = _scripts(voiced_scenes={2})
    _patch_db(monkeypatch, video, scripts)

    executor = PipelineExecutor(TENANT)
    boom = _boom_coverage()
    with patch("scripts.coverage_to_app.generate_coverage_for_video", boom):
        result = _run(executor.run_coverage_images(VIDEO, scene=1))

    assert result["status"] == "failed"
    assert "scene 1" in result["error"]
    boom.assert_not_awaited()


# =============================================================================
# run_coverage_stage — the OTHER modern image-stage entry point (the
# "ready_for_storyboards"/"ready_for_storyboard_images"/
# "ready_for_storyboard_extraction" status-map handlers and
# ClaudeOrchestrator's "storyboard" skill dispatch call this directly, not
# through run_coverage_images — it needs its own copy of the gate)
# =============================================================================

def test_run_coverage_stage_refuses_with_zero_voiced_scenes(monkeypatch):
    video = _video()
    scripts = _scripts(voiced_scenes=set())
    calls = _patch_db(monkeypatch, video, scripts)

    executor = PipelineExecutor(TENANT)
    boom = _boom_coverage()
    with patch("scripts.coverage_to_app.generate_coverage_for_video", boom):
        result = _run(executor.run_coverage_stage(VIDEO))

    assert result["status"] == "failed"
    assert "Voice generation must complete" in result["error"]
    boom.assert_not_awaited()
    # The gate must fire BEFORE the environments/characters auto-approve
    # writes and the Story Bible call — no side effect of any kind on a
    # blocked video.
    assert not any("environments_approved_at" in c[0] for c in calls)


def test_run_coverage_stage_proceeds_when_fully_voiced(monkeypatch):
    video = _video()
    scripts = _scripts(voiced_scenes={1, 2, 3})
    _patch_db(monkeypatch, video, scripts)

    executor = PipelineExecutor(TENANT)
    ok = AsyncMock(return_value={"status": "completed"})
    with patch("scripts.coverage_to_app.generate_coverage_for_video", ok), \
         patch.object(PipelineExecutor, "run_story_bible", AsyncMock(return_value={})):
        result = _run(executor.run_coverage_stage(VIDEO))

    assert result["status"] == "ready_for_images"
    ok.assert_awaited_once()


# =============================================================================
# The actual bypassed call path: ClaudeOrchestrator.execute() dispatching
# skill_id="images"/"storyboard" straight to executor.run_coverage_images /
# run_coverage_stage. This is what proves the REAL entry point (not just the
# method in isolation) is closed.
# =============================================================================

def _patch_co_fetch_one(monkeypatch, video: dict):
    async def _fake_fetch_one(query, *args):
        return dict(video)
    monkeypatch.setattr(co_mod, "fetch_one", _fake_fetch_one)

    async def _fake_execute(query, *args):
        return "INSERT 0 1"
    monkeypatch.setattr(co_mod, "execute", _fake_execute)


def test_claude_orchestrator_images_dispatch_refuses_unvoiced_video(monkeypatch):
    """The exact confirmed bypass (claude_orchestrator.py skill_to_method
    "images" -> executor.run_coverage_images, no gate in between): a live
    PipelineExecutor now refuses on its own, so this real dispatch path
    never reaches paid generation."""
    video = _video(status="ready_for_images")
    scripts = _scripts(voiced_scenes=set())
    _patch_db(monkeypatch, video, scripts)
    _patch_co_fetch_one(monkeypatch, video)

    orch = ClaudeOrchestrator(TENANT)
    executor = PipelineExecutor(TENANT)
    boom = _boom_coverage()

    decision = Decision(action="invoke_skill", skill_id="images",
                        reasoning="test", confidence=0.95)
    with patch("scripts.coverage_to_app.generate_coverage_for_video", boom):
        result = _run(orch.execute(decision, VIDEO, executor=executor))

    assert result.success is False
    assert "Voice generation must complete" in (result.error or "")
    boom.assert_not_awaited()


def test_claude_orchestrator_storyboard_dispatch_refuses_unvoiced_video(monkeypatch):
    """Same proof for skill_id="storyboard" -> executor.run_coverage_stage."""
    video = _video(status="ready_for_storyboards")
    scripts = _scripts(voiced_scenes=set())
    _patch_db(monkeypatch, video, scripts)
    _patch_co_fetch_one(monkeypatch, video)

    orch = ClaudeOrchestrator(TENANT)
    executor = PipelineExecutor(TENANT)
    boom = _boom_coverage()

    decision = Decision(action="invoke_skill", skill_id="storyboard",
                        reasoning="test", confidence=0.95)
    with patch("scripts.coverage_to_app.generate_coverage_for_video", boom):
        result = _run(orch.execute(decision, VIDEO, executor=executor))

    assert result.success is False
    assert "Voice generation must complete" in (result.error or "")
    boom.assert_not_awaited()
