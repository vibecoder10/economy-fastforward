"""Offline replay coverage for the real DVsU Run All coordinator.

The coordinator is ``actions.make_autobuild_step`` itself.  The fake only
replaces its database, queue UI, and provider boundaries; status routing,
review checkpoints, and loop control remain production code.
"""
from __future__ import annotations

import asyncio
import sys
import types

import pytest

import actions
from static_docu_contract import STATIC_VIEW_PLANS


TENANT = "tenant-replay"
VIDEO = "video-replay"


class ReplayExecutor:
    def __init__(self, state, calls):
        self.state = state
        self.calls = calls

    async def _get_video(self, video_id):
        assert video_id == VIDEO
        return dict(self.state)

    async def run_research(self, _video_id):
        self.calls.append("roster")
        self.state["research_payload"] = {
            "roster_selection": {"version": 1, "status": "completed"},
            "research_phase": "roster_complete",
        }
        return {"status": "roster_ready"}

    async def run_roster_image_gather(self, _video_id):
        self.calls.append("roster_images")
        return {"status": "images_ready"}

    async def run_unit_research(self, _video_id):
        self.calls.append("research")
        return {"status": "ready_for_scripting"}

    async def run_script(self, _video_id, **_kwargs):
        self.calls.append("script")
        scripted = self.state.get("script_result")
        if scripted:
            return dict(scripted)
        self.state["status"] = "ready_for_voice"
        return {"status": "completed"}

    async def run_voice(self, _video_id, **_kwargs):
        self.calls.append("voice")
        return {"status": "completed"}

    async def run_thumbnail(self, _video_id):
        self.calls.append("thumbnail")
        self.state["thumbnail_url"] = "https://saved.example/thumbnail.png"
        return {"status": "completed"}

    async def run_next_step(self, _video_id):
        status = self.state["status"]
        if status in {"ready_for_voice", "ready_for_images", "ready_for_thumbnail"}:
            return {"status": "needs_approval"}
        if status == "ready_to_render":
            self.calls.append("render")
            self.state["status"] = "rendered"
            return {"status": "completed"}
        raise AssertionError(f"unexpected coordinator dispatch at {status}")


async def _run_replay(monkeypatch, state, *, target="finish"):
    calls, task_statuses = [], []
    executor = ReplayExecutor(state, calls)

    async def fetch_one(query, *_args):
        if "pipeline_stages" in query:
            return {"pipeline_stages": state["pipeline_stages"]}
        if "SELECT status FROM videos" in query:
            return {"status": state["status"]}
        if "production_queue" in query:
            return None
        if "max_spend, total_cost" in query:
            return dict(state)
        if "voice_over_url IS NULL" in query:
            return None
        return None

    async def execute(query, *args):
        if query.startswith("UPDATE videos SET status="):
            state["status"] = args[0]
        return "UPDATE 1"

    async def fetch_all(_query, *_args):
        # Once a static image stage is complete, its saved three-view coverage
        # is what lets the real downstream recheck continue to thumbnail/render.
        return [
            {"scene": 1, "image_url": f"https://saved.example/{plan['role']}.png",
             "caption": {"view_role": plan["role"]}}
            for plan in STATIC_VIEW_PLANS
        ]

    async def static_images(_video_id, _tenant_id, **_kwargs):
        calls.append("images")
        return {"status": "completed"}

    async def roster_image_state(_video, _tenant):
        return {"status": "completed"}

    async def release(*_args):
        calls.append("release")

    async def fast_sleep(*_args, **_kwargs):
        return None

    pipeline_module = types.ModuleType("pipeline_executor")
    pipeline_module.PipelineExecutor = lambda _tenant: executor
    route_module = types.ModuleType("routes.pipeline")
    route_module._set_task_status = lambda _video, status, message, **_kwargs: task_statuses.append((status, message))
    route_module._clear_task_status = lambda *_args, **_kwargs: None
    claims_module = types.ModuleType("generation_claims")
    claims_module.release = release
    static_module = types.ModuleType("static_docu")
    static_module.generate_static_images_for_video = static_images
    roster_module = types.ModuleType("roster_images")
    roster_module.roster_image_state = roster_image_state

    monkeypatch.setattr(actions, "fetch_one", fetch_one)
    monkeypatch.setattr(actions, "execute", execute)
    monkeypatch.setattr(actions, "fetch_all", fetch_all)
    monkeypatch.setitem(sys.modules, "pipeline_executor", pipeline_module)
    monkeypatch.setitem(sys.modules, "routes.pipeline", route_module)
    monkeypatch.setitem(sys.modules, "generation_claims", claims_module)
    monkeypatch.setitem(sys.modules, "static_docu", static_module)
    monkeypatch.setitem(sys.modules, "roster_images", roster_module)
    monkeypatch.setattr(asyncio, "sleep", fast_sleep)

    await actions.make_autobuild_step(TENANT, VIDEO, target=target)()
    return calls, task_statuses


def _state(**overrides):
    state = {
        "id": VIDEO,
        "tenant_id": TENANT,
        "status": "idea_logged",
        "render_mode": "static_docu",
        "pipeline_stages": ["research", "script", "voice", "images", "thumbnail", "render"],
        "research_payload": {},
        "thumbnail_url": None,
        "script_result": None,
        "max_spend": None,
        "total_cost": 0,
    }
    state.update(overrides)
    return state


@pytest.mark.asyncio
async def test_static_docu_finish_replays_real_coordinator_in_order_without_upload(monkeypatch):
    state = _state()
    calls, task_statuses = await _run_replay(monkeypatch, state)

    assert calls == ["roster", "research", "script", "voice", "images", "thumbnail", "render", "release"]
    assert state["status"] == "rendered"
    assert task_statuses[-1][0] == "completed"
    assert "upload" not in calls


@pytest.mark.asyncio
async def test_resumed_rendered_static_docu_skips_all_provider_methods(monkeypatch):
    state = _state(status="rendered", research_payload={"already": "saved"}, thumbnail_url="https://saved.example/t.png")
    calls, task_statuses = await _run_replay(monkeypatch, state)

    assert calls == ["release"]
    assert task_statuses[-1][0] == "completed"


@pytest.mark.asyncio
async def test_budget_stop_does_not_start_provider_work(monkeypatch):
    budget_state = _state(max_spend=1, total_cost=1)
    budget_calls, budget_statuses = await _run_replay(monkeypatch, budget_state)
    assert budget_calls == ["release"]
    assert "cap" in budget_statuses[-1][1]


@pytest.mark.asyncio
@pytest.mark.parametrize("script_result, terminal_status", [
    ({"status": "needs_review", "message": "partial script"}, "needs_review"),
    ({"status": "cancelled", "message": "cancelled script"}, "cancelled"),
])
async def test_partial_or_cancelled_script_stops_before_voice(monkeypatch, script_result, terminal_status):
    partial_state = _state(status="ready_for_scripting", script_result=script_result)
    calls, statuses = await _run_replay(monkeypatch, partial_state, target="finish")
    assert "voice" not in calls
    assert calls == ["script", "release"]
    assert statuses[-1][0] == terminal_status


@pytest.mark.asyncio
async def test_research_target_runs_roster_and_research_then_stops_before_the_script(monkeypatch):
    state = _state()
    calls, task_statuses = await _run_replay(monkeypatch, state, target="research")

    assert calls == ["roster", "research", "release"]
    assert state["status"] == "ready_for_scripting"
    assert task_statuses[-1] == ("completed", actions.RESEARCH_READY_MSG)


@pytest.mark.asyncio
async def test_research_target_on_a_video_already_past_research_starts_no_provider_work(monkeypatch):
    state = _state(status="ready_for_voice", research_payload={"already": "saved"})
    calls, task_statuses = await _run_replay(monkeypatch, state, target="research")

    assert calls == ["release"]
    assert task_statuses[-1] == ("completed", actions.RESEARCH_READY_MSG)


def test_every_layer_accepts_the_same_run_all_targets():
    import inspect
    import job_queue
    import worker

    assert actions.AUTOBUILD_TARGETS == ("research", "pictures", "finish")
    assert '{"research", "pictures", "finish"}' in inspect.getsource(job_queue)
    assert '{"research", "pictures", "finish"}' in inspect.getsource(worker)
