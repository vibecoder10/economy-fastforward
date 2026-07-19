"""Tests for C18 (checklist §1.3 [U], tasks/storyengine-copilot-ux-map.md §2):
the CLICKABLE door for C17's draft_pass/finalize verbs + the scene-scoped
approve verb (C15b shipped it chat-only).

Three layers, mirroring test_c17_draft_pass_and_finalize.py's / test_c14_
model_override_and_render_style.py's patterns (real `actions`/`routes.pipeline`
modules, DB boundaries monkeypatched — no live DB, no network, no paid calls):

1. `routes.pipeline.run_draft_pass` / `run_finalize` — thin routes that call
   `actions.RUNNERS[verb]` DIRECTLY (the same runner chat's confirm flow
   calls) — two doors, one dispatch. Tenant-scoped 404; a claim-denied runner
   reply (`actions._ALREADY_WORKING_REPLY`, returned WITHOUT scheduling a
   background task) becomes an HTTP 409; every other non-scheduling reply
   (already drafted, nothing approved, no draft tier) is a graceful 200
   `status="skipped"` — never a raised error for a plain "nothing to do".
   Scheduling is detected by diffing `background_tasks.tasks`, never by
   string-matching the runner's free-form chat reply.
2. `routes.pipeline.approve_scene_route` — the clickable door for the
   scene-scoped free `approve_scene` verb; calls the SAME runner
   (`actions.RUNNERS["approve_scene"]`) chat's "approve scene N" already
   uses, tenant-scoped, scene passed through untouched.
3. `routes.pipeline.list_video_actions` — additive `breakdown` field per
   action (actions.cost_breakdown), present for draft_pass/finalize/animate/
   build, `None` for every other verb (an old frontend build simply never
   reads the key).

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c18_guided_actions_ui.py -q
"""
import asyncio
import os
import sys

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
_PIPELINE_PATH = os.path.join(_BACKEND, "..", "..", "skills", "video-pipeline")
sys.path.insert(0, os.path.abspath(_BACKEND))
sys.path.insert(0, os.path.abspath(_PIPELINE_PATH))

from fastapi import HTTPException
from starlette.background import BackgroundTasks

import actions  # noqa: E402
import routes.pipeline as pipeline_route  # noqa: E402

TENANT = "tenant-1"
OTHER_TENANT = "tenant-2"
VIDEO = "video-1"


def _summary(**over):
    base = {
        "title": "T", "status": "ready_for_video_generation", "length_min": 5,
        "model": "grok-imagine", "scenes": 3, "boards": 3, "voiced": 3,
        "max_scene": 3, "pics": 3, "clips": 0, "cast": 0, "spent": 0.0,
        "render_style": None,
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# 1. POST /actions/{video_id}/draft-pass and /finalize
# ---------------------------------------------------------------------------

def test_draft_pass_route_404s_for_unknown_or_other_tenant_video(monkeypatch):
    seen = {}

    async def fake_fetch_one(query, *args):
        seen["query"], seen["args"] = query, args
        return None
    monkeypatch.setattr(pipeline_route, "fetch_one", fake_fetch_one)

    async def boom(*a, **k):
        raise AssertionError("must not dispatch a runner for a video that doesn't resolve")
    monkeypatch.setitem(actions.RUNNERS, "draft_pass", boom)

    try:
        asyncio.run(pipeline_route.run_draft_pass(VIDEO, BackgroundTasks(), tenant_id=OTHER_TENANT))
        raise AssertionError("expected HTTPException")
    except HTTPException as e:
        assert e.status_code == 404
    assert seen["args"] == (VIDEO, OTHER_TENANT)
    assert "tenant_id" in seen["query"]


def test_draft_pass_route_dispatches_through_the_same_runner_chat_uses(monkeypatch):
    """The route must call actions.RUNNERS['draft_pass'] — NOT reimplement
    any claim/dedupe/dispatch logic itself. Scheduling is detected by the
    runner actually calling background_tasks.add_task."""
    async def fake_fetch_one(query, *args):
        return {"id": VIDEO}
    monkeypatch.setattr(pipeline_route, "fetch_one", fake_fetch_one)

    calls = []

    async def fake_runner(tenant_id, video_id, background_tasks, pending):
        calls.append((tenant_id, video_id, pending))
        background_tasks.add_task(lambda: None)
        return "On it — drafting all 3 scene(s) on the cheap model…"
    monkeypatch.setitem(actions.RUNNERS, "draft_pass", fake_runner)

    result = asyncio.run(pipeline_route.run_draft_pass(VIDEO, BackgroundTasks(), tenant_id=TENANT))

    assert calls == [(TENANT, VIDEO, {})]
    assert result.status == "running"
    assert result.video_id == VIDEO
    assert "drafting" in result.message.lower()


def test_finalize_route_translates_already_working_reply_to_409(monkeypatch):
    async def fake_fetch_one(query, *args):
        return {"id": VIDEO}
    monkeypatch.setattr(pipeline_route, "fetch_one", fake_fetch_one)

    async def busy_runner(tenant_id, video_id, background_tasks, pending):
        return actions._ALREADY_WORKING_REPLY  # no add_task call — claim was denied
    monkeypatch.setitem(actions.RUNNERS, "finalize", busy_runner)

    try:
        asyncio.run(pipeline_route.run_finalize(VIDEO, BackgroundTasks(), tenant_id=TENANT))
        raise AssertionError("expected HTTPException")
    except HTTPException as e:
        assert e.status_code == 409
        assert e.detail == actions._ALREADY_WORKING_REPLY


def test_finalize_route_nothing_to_finalize_is_a_graceful_skip_not_an_error(monkeypatch):
    """'Nothing approved yet' / 'already finalized' etc. are valid runner
    replies that never call add_task but are NOT the busy sentinel — these
    must come back as a plain 200 the button can toast, never a raised
    error (a real user just hasn't approved anything yet)."""
    async def fake_fetch_one(query, *args):
        return {"id": VIDEO}
    monkeypatch.setattr(pipeline_route, "fetch_one", fake_fetch_one)

    async def nothing_runner(tenant_id, video_id, background_tasks, pending):
        return 'Nothing\'s approved yet — say "approve scene 3" (or a few) and I\'ll finalize just those.'
    monkeypatch.setitem(actions.RUNNERS, "finalize", nothing_runner)

    result = asyncio.run(pipeline_route.run_finalize(VIDEO, BackgroundTasks(), tenant_id=TENANT))
    assert result.status == "skipped"
    assert "approved yet" in result.message


# ---------------------------------------------------------------------------
# 2. POST /actions/{video_id}/approve-scene
# ---------------------------------------------------------------------------

def test_approve_scene_route_404s_for_unknown_or_other_tenant_video(monkeypatch):
    async def fake_fetch_one(query, *args):
        return None
    monkeypatch.setattr(pipeline_route, "fetch_one", fake_fetch_one)

    async def boom(*a, **k):
        raise AssertionError("must not write when the video doesn't resolve for this tenant")
    monkeypatch.setitem(actions.RUNNERS, "approve_scene", boom)

    body = pipeline_route.ApproveSceneRequest(scene=2)
    try:
        asyncio.run(pipeline_route.approve_scene_route(VIDEO, body, tenant_id=OTHER_TENANT))
        raise AssertionError("expected HTTPException")
    except HTTPException as e:
        assert e.status_code == 404


def test_approve_scene_route_calls_the_same_runner_chat_uses_with_the_named_scene(monkeypatch):
    async def fake_fetch_one(query, *args):
        return {"id": VIDEO}
    monkeypatch.setattr(pipeline_route, "fetch_one", fake_fetch_one)

    calls = []

    async def fake_runner(tenant_id, video_id, background_tasks, pending):
        calls.append((tenant_id, video_id, background_tasks, pending))
        return "Scene 4 approved ✓ — 6 shots locked in. This is free and reversible any time."
    monkeypatch.setitem(actions.RUNNERS, "approve_scene", fake_runner)

    body = pipeline_route.ApproveSceneRequest(scene=4)
    result = asyncio.run(pipeline_route.approve_scene_route(VIDEO, body, tenant_id=TENANT))

    assert calls[0][0] == TENANT and calls[0][1] == VIDEO and calls[0][3] == {"scene": 4}
    assert calls[0][2] is None, "approve_scene never schedules background work — no BackgroundTasks needed"
    assert result == {"scene": 4, "message": "Scene 4 approved ✓ — 6 shots locked in. This is free and reversible any time."}


# ---------------------------------------------------------------------------
# 3. GET /actions/{video_id} — additive `breakdown` field
# ---------------------------------------------------------------------------

def test_list_video_actions_carries_breakdown_for_draft_pass_and_none_elsewhere(monkeypatch):
    async def fake_video_summary(tenant_id, video_id):
        return _summary()
    monkeypatch.setattr(actions, "video_summary", fake_video_summary)

    async def fake_routed_clip_rows(tenant_id, video_id, scene, video_model, only_scenes=None):
        return [{"scene": 1, "routed_model": "grok-imagine", "model_override": None, "routing_reason": None}]
    monkeypatch.setattr(actions, "_routed_clip_rows", fake_routed_clip_rows)

    async def fake_approved_scenes(tenant_id, video_id):
        return []
    monkeypatch.setattr(actions, "_approved_scenes", fake_approved_scenes)

    # estimate_cost's "voice"/"characters" branches hit fetch_one directly
    # (unrelated to this test's subject) — stub it so the loop over every
    # ACTIONS verb doesn't need a live DB.
    async def fake_fetch_one(query, *args):
        return {"chars": 0, "n": 0}
    monkeypatch.setattr(actions, "fetch_one", fake_fetch_one)

    result = asyncio.run(pipeline_route.list_video_actions(VIDEO, tenant_id=TENANT))
    by_verb = {a["verb"]: a for a in result["actions"]}

    assert by_verb["draft_pass"]["breakdown"] is not None
    assert by_verb["draft_pass"]["breakdown"]["scene_count"] == 1
    # A verb cost_breakdown never itemizes (e.g. the free approve_scene verb
    # itself) must carry breakdown=None, not an empty/garbage dict — an old
    # frontend build reading this key sees exactly what it saw before C18.
    assert by_verb["approve_scene"]["breakdown"] is None
    assert by_verb["script"]["breakdown"] is None
