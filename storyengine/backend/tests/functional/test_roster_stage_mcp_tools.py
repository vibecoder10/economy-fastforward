"""MCP tools for the static-documentary steps between Roster and a finished Research stage:

  * gather_roster_images - PAID (workspace vision key), quote-gated, background.
  * research_machine     - FREE, only when the agent LLM relay is on, background.

No live DB, no network, no provider calls: every boundary is patched.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_roster_stage_mcp_tools.py -q
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _BACKEND)

os.environ.setdefault("SESSION_SECRET", "test-secret-only-for-roster-stage-tools")

import actions  # noqa: E402
import confirm_tokens  # noqa: E402
import routes.mcp as mcp_mod  # noqa: E402
import routes.pipeline as pipeline_routes  # noqa: E402
from fastapi import HTTPException  # noqa: E402

VIDEO = "v1"
TENANT = "t1"
ROSTER = ["USS Holland (SS-1)", "F-class", "Ohio class"]


class _Bg:
    def __init__(self):
        self.calls = []

    def add_task(self, fn, *a, **k):
        self.calls.append((fn, a, k))


class _ConfirmStore:
    def __init__(self):
        self.rows: list[dict] = []


def _patch_confirm(store: _ConfirmStore):
    async def _execute(query, *args):
        if "INSERT INTO mcp_confirm_tokens" in query:
            tenant_id, video_id, verb, phash, token_hash, ttl_secs = args
            store.rows.append({"tenant_id": tenant_id, "video_id": video_id, "verb": verb, "params_hash": phash,
                               "token_hash": token_hash, "used_at": None,
                               "expires_at": datetime.now(timezone.utc) + timedelta(seconds=ttl_secs)})
            return "INSERT 0 1"
        if "UPDATE mcp_confirm_tokens SET used_at" in query:
            token_hash, tenant_id, video_id, verb, phash = args
            now = datetime.now(timezone.utc)
            for r in store.rows:
                if (r["token_hash"] == token_hash and r["tenant_id"] == tenant_id and r["video_id"] == video_id
                        and r["verb"] == verb and r["params_hash"] == phash and r["used_at"] is None
                        and r["expires_at"] > now):
                    r["used_at"] = now
                    return "UPDATE 1"
            return "UPDATE 0"
        raise AssertionError(f"unexpected query: {query!r}")
    return patch.object(confirm_tokens, "execute", _execute)


def _payload(result: dict) -> dict:
    return json.loads(result["content"][0]["text"])


def _image_state(total: int, verified: int) -> dict:
    return {"total": total, "verified": verified, "status": "completed" if total and verified >= total else "not_started"}


def _patch_gather_video(total: int, verified: int):
    import pipeline_executor
    import roster_images
    return (
        patch.object(pipeline_executor.PipelineExecutor, "_get_video", AsyncMock(return_value={"id": VIDEO})),
        patch.object(roster_images, "roster_image_state", AsyncMock(return_value=_image_state(total, verified))),
    )


# ---------------------------------------------------------------------------
# gather_roster_images
# ---------------------------------------------------------------------------

async def test_gather_quotes_only_the_missing_machines_and_starts_nothing_until_confirmed():
    store, bg = _ConfirmStore(), _Bg()
    start = AsyncMock(return_value={"status": "started", "video_id": VIDEO, "message": "started"})
    p_video, p_state = _patch_gather_video(total=20, verified=15)
    with p_video, p_state, _patch_confirm(store), patch.object(pipeline_routes, "start_roster_images_in_process", start):
        quote = _payload(await mcp_mod._call_gather_roster_images(TENANT, {"video_id": VIDEO}, bg, "agent"))
        assert quote["status"] == "quote"
        assert quote["cost"] == round(5 * actions.ROSTER_IMAGE_CHECK_COST, 2)
        start.assert_not_awaited()

        confirmed = await mcp_mod._call_gather_roster_images(
            TENANT, {"video_id": VIDEO, "confirm_token": quote["confirm_token"]}, bg, "agent")
    assert confirmed["isError"] is False
    start.assert_awaited_once_with(VIDEO, TENANT, bg)


async def test_gather_token_is_single_use():
    store, bg = _ConfirmStore(), _Bg()
    start = AsyncMock(return_value={"status": "started", "video_id": VIDEO, "message": "started"})
    p_video, p_state = _patch_gather_video(total=4, verified=0)
    with p_video, p_state, _patch_confirm(store), patch.object(pipeline_routes, "start_roster_images_in_process", start):
        token = _payload(await mcp_mod._call_gather_roster_images(TENANT, {"video_id": VIDEO}, bg, "agent"))["confirm_token"]
        args = {"video_id": VIDEO, "confirm_token": token}
        assert (await mcp_mod._call_gather_roster_images(TENANT, args, bg, "agent"))["isError"] is False
        replay = await mcp_mod._call_gather_roster_images(TENANT, args, bg, "agent")
    assert replay["isError"] is True
    assert start.await_count == 1


async def test_gather_is_a_noop_without_a_quote_when_every_image_is_verified():
    p_video, p_state = _patch_gather_video(total=20, verified=20)
    with p_video, p_state, \
         patch.object(confirm_tokens, "create", AsyncMock(side_effect=AssertionError("nothing to buy"))):
        result = await mcp_mod._call_gather_roster_images(TENANT, {"video_id": VIDEO}, _Bg(), "agent")
    assert _payload(result)["status"] == "already_done"


async def test_gather_refuses_when_there_is_no_saved_roster_yet():
    p_video, p_state = _patch_gather_video(total=0, verified=0)
    with p_video, p_state, \
         patch.object(confirm_tokens, "create", AsyncMock(side_effect=AssertionError("must not quote"))):
        result = await mcp_mod._call_gather_roster_images(TENANT, {"video_id": VIDEO}, _Bg(), "agent")
    assert result["isError"] is True


async def test_gather_reports_a_busy_video_as_an_error_result_not_a_crash():
    store, bg = _ConfirmStore(), _Bg()
    start = AsyncMock(side_effect=HTTPException(status_code=409, detail="Task already running for this video"))
    p_video, p_state = _patch_gather_video(total=2, verified=0)
    with p_video, p_state, _patch_confirm(store), patch.object(pipeline_routes, "start_roster_images_in_process", start):
        token = _payload(await mcp_mod._call_gather_roster_images(TENANT, {"video_id": VIDEO}, bg, "agent"))["confirm_token"]
        result = await mcp_mod._call_gather_roster_images(TENANT, {"video_id": VIDEO, "confirm_token": token}, bg, "agent")
    assert result["isError"] is True
    assert "already running" in result["content"][0]["text"]


async def test_gather_start_runs_the_same_job_as_the_route_and_reports_terminal_status():
    """The in-process door must set 'running', queue the real job, and the job must end in completed/failed."""
    bg = _Bg()
    statuses = []
    fake_exec = MagicMock()
    fake_exec.run_roster_image_gather = AsyncMock(return_value={"status": "images_ready", "message": "All verified"})
    with patch.object(pipeline_routes, "_roster_images_preflight", AsyncMock()), \
         patch.object(pipeline_routes, "_set_task_status", lambda *a, **k: statuses.append((a[1], k.get("task_type")))), \
         patch.object(pipeline_routes, "_clear_task_status", lambda *a, **k: None), \
         patch.object(pipeline_routes, "PipelineExecutor", lambda tenant_id: fake_exec), \
         patch.object(pipeline_routes.asyncio, "sleep", AsyncMock()):
        resp = await pipeline_routes.start_roster_images_in_process(VIDEO, TENANT, bg)
        assert resp["status"] == "started"
        assert statuses == [("running", "roster_images")]
        assert len(bg.calls) == 1
        await bg.calls[0][0]()
    assert statuses[-1] == ("completed", "roster_images")
    fake_exec.run_roster_image_gather.assert_awaited_once_with(VIDEO)


# ---------------------------------------------------------------------------
# research_machine
# ---------------------------------------------------------------------------

def _patch_research_env(*, relay: bool = True, active: bool = False, roster=None):
    import agent_relay
    import pipeline_executor
    return [
        patch.object(pipeline_routes.drain_mode, "assert_accepting_new_work", AsyncMock()),
        patch.object(agent_relay, "relay_enabled", AsyncMock(return_value=relay)),
        patch.object(pipeline_executor.PipelineExecutor, "_get_video", AsyncMock(return_value={"id": VIDEO})),
        patch.object(pipeline_executor, "_machine_documentary_hold_roster", lambda video: list(ROSTER if roster is None else roster)),
        patch.object(pipeline_routes, "_is_task_active", AsyncMock(return_value=active)),
    ]


def _enter(patches):
    from contextlib import ExitStack
    stack = ExitStack()
    for p in patches:
        stack.enter_context(p)
    return stack


async def test_research_machine_is_refused_when_the_relay_is_off_because_it_would_spend_keys():
    bg = _Bg()
    with _enter(_patch_research_env(relay=False)), \
         patch.object(pipeline_routes, "_set_task_status", MagicMock()) as set_status:
        result = await mcp_mod._call_research_machine(TENANT, {"video_id": VIDEO, "machine": ROSTER[0]}, bg, "agent")
    assert result["isError"] is True
    assert "relay is off" in result["content"][0]["text"]
    assert bg.calls == []
    set_status.assert_not_called()


async def test_research_machine_rejects_a_machine_not_on_the_locked_roster_and_lists_valid_names():
    bg = _Bg()
    with _enter(_patch_research_env()), patch.object(pipeline_routes, "_set_task_status", MagicMock()) as set_status:
        result = await mcp_mod._call_research_machine(TENANT, {"video_id": VIDEO, "machine": "Nautilus"}, bg, "agent")
    text = result["content"][0]["text"]
    assert result["isError"] is True
    assert "not in the locked roster" in text
    assert all(name in text for name in ROSTER)
    assert bg.calls == []
    set_status.assert_not_called()


async def test_research_machine_requires_both_arguments():
    for args in ({"video_id": VIDEO}, {"machine": "F-class"}, {"video_id": VIDEO, "machine": "  "}):
        result = await mcp_mod._call_research_machine(TENANT, args, _Bg(), "agent")
        assert result["isError"] is True


async def test_research_machine_will_not_start_over_a_running_task():
    bg = _Bg()
    with _enter(_patch_research_env(active=True)), patch.object(pipeline_routes, "_set_task_status", MagicMock()) as set_status:
        result = await mcp_mod._call_research_machine(TENANT, {"video_id": VIDEO, "machine": ROSTER[1]}, bg, "agent")
    assert result["isError"] is True
    assert "already running" in result["content"][0]["text"]
    assert bg.calls == []
    set_status.assert_not_called()


async def test_research_machine_starts_in_background_and_tells_the_agent_what_to_do_next():
    bg = _Bg()
    statuses = []
    with _enter(_patch_research_env()), \
         patch.object(pipeline_routes, "_set_task_status", lambda *a, **k: statuses.append((a[1], k.get("task_type"), a[2] if len(a) > 2 else None))):
        # a case-insensitive / loosely typed name resolves to the locked roster spelling
        result = await mcp_mod._call_research_machine(TENANT, {"video_id": VIDEO, "machine": " uss holland (ss-1) "}, bg, "agent")
    body = _payload(result)
    assert result["isError"] is False
    assert body["status"] == "started"
    assert body["machine"] == "USS Holland (SS-1)"
    assert "list_pending_llm_requests" in body["next"] and "answer_llm_request" in body["next"]
    assert len(bg.calls) == 1
    assert statuses[0][:2] == ("running", "machine_research")
    assert "USS Holland (SS-1)" in statuses[0][2]


async def test_research_machine_job_reports_completed_or_failed_and_clears_the_status():
    async def _run_job(run_result=None, raises=None):
        bg = _Bg()
        statuses, cleared = [], []
        fake_exec = MagicMock()
        fake_exec.run_one_machine_research = AsyncMock(return_value=run_result, side_effect=raises)
        with _enter(_patch_research_env()), \
             patch.object(pipeline_routes, "_set_task_status", lambda *a, **k: statuses.append((a[1], a[2] if len(a) > 2 else None))), \
             patch.object(pipeline_routes, "_clear_task_status", lambda *a, **k: cleared.append(True)), \
             patch.object(pipeline_routes, "PipelineExecutor", lambda tenant_id: fake_exec), \
             patch.object(pipeline_routes.asyncio, "sleep", AsyncMock()):
            fake_exec._get_video = AsyncMock(return_value={"id": VIDEO})
            await pipeline_routes.start_machine_research_in_process(VIDEO, TENANT, ROSTER[2], bg)
            await bg.calls[0][0]()
        fake_exec.run_one_machine_research.assert_awaited_once_with(VIDEO, ROSTER[2])
        return statuses, cleared

    statuses, cleared = await _run_job(run_result={"status": "completed"})
    assert statuses[-1][0] == "completed" and ROSTER[2] in statuses[-1][1]
    assert cleared == [True]

    statuses, cleared = await _run_job(run_result={"status": "failed", "error": "gate refused"})
    assert statuses[-1] == ("failed", "gate refused")
    assert cleared == [True]

    statuses, cleared = await _run_job(raises=RuntimeError("boom"))
    assert statuses[-1][0] == "failed"
    assert cleared == [True]


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------

def test_both_tools_are_registered_with_the_right_money_shape():
    tools = {t["name"]: t for t in mcp_mod.TOOLS}
    gather, research = tools["gather_roster_images"], tools["research_machine"]
    assert "confirm_token" in gather["inputSchema"]["properties"] and "PAID" in gather["description"]
    assert "confirm_token" not in research["inputSchema"]["properties"]
    assert research["inputSchema"]["required"] == ["video_id", "machine"]
    assert set(mcp_mod._ROSTER_STAGE_HANDLERS) == {"gather_roster_images", "research_machine"}


# ---------------------------------------------------------------------------
# production guide names the tools
# ---------------------------------------------------------------------------

def test_guide_names_the_tool_for_the_static_steps_that_only_had_buttons():
    import production_guide as pg

    gather = pg._with_tool_hint({"stage": "image_gather", "action": "start", "reason": "Gather images hasn't started."}, True)
    assert gather["tool"] == "gather_roster_images" and "quotes the vision cost" in gather["reason"]
    research = pg._with_tool_hint({"stage": "research", "action": "start", "reason": "Research hasn't started."}, True)
    assert research["tool"] == "research_machine" and "once per locked roster machine" in research["reason"]


def test_guide_adds_no_tool_hint_for_animated_videos_waiting_steps_or_other_stages():
    import production_guide as pg

    step = {"stage": "image_gather", "action": "start", "reason": "r"}
    assert pg._with_tool_hint(step, False) == step                                        # animated format
    waiting = {"stage": "research", "action": "wait", "reason": "r"}
    assert pg._with_tool_hint(waiting, True) == waiting                                    # already running
    script = {"stage": "script", "action": "start", "reason": "r"}
    assert pg._with_tool_hint(script, True) == script                                      # no static-only tool
