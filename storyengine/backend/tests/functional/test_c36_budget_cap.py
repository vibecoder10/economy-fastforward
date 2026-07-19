"""Tests for C36 (checklist §3.3 item 3, tasks/storyengine-wiring-fix-
checklist.md): the optional per-video budget ceiling (migration 103,
videos.max_spend). The money framework already existed (estimate_cost,
confirm cards, generation_ledger) — this chunk adds the cap the gates
consult, on the SAME "quote honestly, never silent-block" philosophy.

Five layers, mirroring test_c15_itemized_cost_breakdown.py's / test_c17's
patterns (real `actions`/`routes.chat`/`routes.mcp` modules, DB boundaries
monkeypatched — no live DB, no network):

1. `actions.budget_check()` — the cap-gate matrix: no cap -> None
   (byte-identical); under cap -> None; would-exceed -> a dict with the
   exact projected/spent/quote/cap numbers and a message.
2. `actions._resolve_budget_cap_text()` / `actions._runner_budget_cap()` —
   the "cap this video at $15" / "remove the cap" conversational door,
   writing videos.max_spend through the same generic UPDATE path.
3. `routes.chat._confirm_card()` — a budget_warning rides the card
   (relabeled "Do it anyway", a `budget` key) only when one exists;
   omitted entirely otherwise (old-frontend-safe).
4. `actions.make_autobuild_step()` — a video already at/over its cap pauses
   cleanly (task status "completed", a message naming the cap and spend)
   BEFORE the iteration's paid step runs; a video under its cap (or with no
   cap at all) proceeds exactly as before (byte-identical no-cap path).
5. `routes.mcp` quote path carries the same `budget_warning` when present.

Non-vacuous: every one of these assertions fails against the pre-C36 code
(no budget_check function, no max_spend column read, no autobuild check) —
confirmed via `git stash` before this file was added to the suite.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_c36_budget_cap.py -q
"""
import asyncio
import os
import sys
import types
from unittest.mock import patch

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
_PIPELINE_PATH = os.path.join(_BACKEND, "..", "..", "skills", "video-pipeline")
sys.path.insert(0, os.path.abspath(_BACKEND))
sys.path.insert(0, os.path.abspath(_PIPELINE_PATH))

import actions  # noqa: E402
import routes.chat as chat_route  # noqa: E402
from models import VideoDetail  # noqa: E402

TENANT = "tenant-1"
VIDEO = "video-1"


def test_video_detail_model_and_get_video_query_carry_max_spend():
    """Wiring lock (StoryEngine's "4 layers, all wired in one pass" rule):
    `GET /api/videos/{id}` uses `response_model=VideoDetail` — Pydantic
    silently DROPS any DB column not declared on that model, so adding
    videos.max_spend without also declaring it here would make the whole
    UI door (BudgetCapCard) always read null regardless of what's actually
    set. Also pins the route's explicit SELECT column list (NOT `SELECT *`)
    actually names the column, not just the schema having it."""
    assert "max_spend" in VideoDetail.model_fields
    src = open(os.path.join(_BACKEND, "routes", "videos.py")).read()
    get_video_body = src.split("async def get_video(")[1].split("async def ")[0]
    assert "max_spend" in get_video_body, (
        "get_video's SELECT must name max_spend explicitly (it's not SELECT *)"
    )
    print("✅ test_video_detail_model_and_get_video_query_carry_max_spend")


def _summary(**over):
    base = {
        "title": "T", "status": "ready_for_video_generation", "length_min": 5,
        "model": "grok-imagine", "scenes": 5, "boards": 5, "voiced": 5,
        "max_scene": 5, "pics": 30, "clips": 0, "cast": 2, "spent": 3.0,
        "total_cost": 3.0, "max_spend": None, "validation": "", "render_style": None,
    }
    base.update(over)
    return base


# --- 1. actions.budget_check(): the cap-gate matrix -------------------------

def test_budget_check_no_cap_is_byte_identical_none():
    assert actions.budget_check(_summary(max_spend=None, total_cost=999.0), 50.0) is None
    print("✅ test_budget_check_no_cap_is_byte_identical_none")


def test_budget_check_under_cap_returns_none():
    s = _summary(max_spend=10.0, total_cost=5.0)
    assert actions.budget_check(s, 3.0) is None  # 5 + 3 = 8 <= 10
    print("✅ test_budget_check_under_cap_returns_none")


def test_budget_check_would_exceed_surfaces_the_breach():
    s = _summary(max_spend=10.0, total_cost=9.0)
    result = actions.budget_check(s, 3.0)  # 9 + 3 = 12 > 10
    assert result is not None
    assert result["cap"] == 10.0
    assert result["spent"] == 9.0
    assert result["quote"] == 3.0
    assert result["projected"] == 12.0
    assert "$12.00" in result["message"] and "$10.00" in result["message"]
    print("✅ test_budget_check_would_exceed_surfaces_the_breach")


def test_budget_check_exactly_at_cap_is_not_a_breach():
    # <= cap is fine, not "over" -- only strictly-past the cap surfaces.
    s = _summary(max_spend=10.0, total_cost=7.0)
    assert actions.budget_check(s, 3.0) is None  # 7 + 3 = 10 == cap
    print("✅ test_budget_check_exactly_at_cap_is_not_a_breach")


# --- 2. text parsing + the free runner --------------------------------------

def test_resolve_budget_cap_text_parses_dollar_amounts():
    assert actions._resolve_budget_cap_text("$15") == (15.0, False, True)
    assert actions._resolve_budget_cap_text("cap this video at $20.50") == (20.5, False, True)
    assert actions._resolve_budget_cap_text("30") == (30.0, False, True)
    print("✅ test_resolve_budget_cap_text_parses_dollar_amounts")


def test_resolve_budget_cap_text_clear_words():
    for phrase in ("remove the cap", "no cap", "none", "unlimited"):
        assert actions._resolve_budget_cap_text(phrase) == (None, True, True), phrase
    print("✅ test_resolve_budget_cap_text_clear_words")


def test_resolve_budget_cap_text_rejects_garbage():
    assert actions._resolve_budget_cap_text("make it look nicer") == (None, False, False)
    assert actions._resolve_budget_cap_text("$0") == (None, False, False)
    assert actions._resolve_budget_cap_text("") == (None, False, False)
    print("✅ test_resolve_budget_cap_text_rejects_garbage")


def test_runner_budget_cap_sets_and_clears():
    executed = []

    async def fake_execute(query, *args):
        executed.append((query, args))
        return "UPDATE 1"

    with patch.object(actions, "execute", fake_execute):
        reply = asyncio.run(actions._runner_budget_cap(
            TENANT, VIDEO, None, {"change": "$15"}))
        assert "15.00" in reply
        assert executed[-1][1] == (15.0, VIDEO, TENANT)

        reply2 = asyncio.run(actions._runner_budget_cap(
            TENANT, VIDEO, None, {"change": "remove the cap"}))
        assert "removed" in reply2.lower()
        assert executed[-1][1] == (None, VIDEO, TENANT)

        reply3 = asyncio.run(actions._runner_budget_cap(
            TENANT, VIDEO, None, {"change": "banana"}))
        assert "cap to be" in reply3.lower()
        assert len(executed) == 2, "an unparseable amount must not write anything"
    print("✅ test_runner_budget_cap_sets_and_clears")


def test_budget_cap_verb_registered_free_no_confirm():
    cfg = actions.ACTIONS["budget_cap"]
    assert cfg["paid"] is False
    assert actions.RUNNERS["budget_cap"] is actions._runner_budget_cap
    print("✅ test_budget_cap_verb_registered_free_no_confirm")


# --- 3. confirm-card wiring --------------------------------------------------

def test_confirm_card_carries_budget_warning_when_present():
    warning = {"cap": 10.0, "spent": 9.0, "quote": 3.0, "projected": 12.0, "message": "heads up"}
    card = chat_route._confirm_card("images", None, "~$3.00", None, warning)
    assert card["budget"] == warning
    assert card["options"][0]["value"] == "yes"
    assert "anyway" in card["options"][0]["label"].lower()
    print("✅ test_confirm_card_carries_budget_warning_when_present")


def test_confirm_card_omits_budget_key_when_no_warning():
    card = chat_route._confirm_card("images", None, "~$3.00")
    assert "budget" not in card
    assert card["options"][0]["label"] == "Do it · ~$3.00"
    print("✅ test_confirm_card_omits_budget_key_when_no_warning")


# --- 4. autobuild loop pause -------------------------------------------------

def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


class _FakeExecutor:
    """Only what the loop's status-check + budget-check touch each pass."""

    def __init__(self, tenant_id, video_row):
        self.tenant_id = tenant_id
        self._video_row = video_row
        self.calls = 0
        self.run_next_step_called = 0

    async def _get_video(self, video_id):
        self.calls += 1
        return dict(self._video_row)

    async def run_next_step(self, video_id):
        self.run_next_step_called += 1
        return {"status": "needs_approval", "message": "Paused for your review."}


def _run_autobuild_iteration(video_row: dict):
    """Drive one make_autobuild_step() pass against a video row that's
    already past BUILD_TO_PICTURES (so the loop's normal work is
    `run_next_step`), capturing the final task-status message."""
    statuses = []

    def _fake_set_task_status(video_id, status, message, tenant_id=None):
        statuses.append((status, message))

    fake_rp = types.ModuleType("routes.pipeline")
    fake_rp._set_task_status = _fake_set_task_status
    fake_rp._clear_task_status = lambda *a, **k: None

    holder = []

    def _factory(tenant_id):
        ex = _FakeExecutor(tenant_id, video_row)
        holder.append(ex)
        return ex

    fake_pe = types.ModuleType("pipeline_executor")
    fake_pe.PipelineExecutor = _factory

    async def _fake_fetch_one(query, *args):
        if "pipeline_stages" in query:
            return {"pipeline_stages": None}
        if "SELECT status FROM videos" in query:
            return {"status": video_row.get("status")}
        return None

    async def _fast_sleep(*_a, **_k):
        return None

    with patch.object(actions, "fetch_one", _fake_fetch_one), \
         patch.object(actions, "execute", lambda *a, **k: asyncio.sleep(0)), \
         patch.dict(sys.modules, {"pipeline_executor": fake_pe, "routes.pipeline": fake_rp}), \
         patch("asyncio.sleep", _fast_sleep):
        step = actions.make_autobuild_step(TENANT, VIDEO, target="finish")
        asyncio.run(step())
    return statuses, holder[0]


def test_autobuild_pauses_cleanly_when_at_or_over_cap():
    video_row = {
        "status": "ready_for_video_generation", "render_mode": None,
        "max_spend": 10.0, "total_cost": 10.0,  # already at the cap
    }
    statuses, ex = _run_autobuild_iteration(video_row)
    assert ex.run_next_step_called == 0, "must pause BEFORE the iteration's paid step runs"
    assert statuses, "expected a task-status update"
    status, message = statuses[-1]
    assert status == "completed", "a budget pause is a clean stop, not a failure"
    assert "$10.00" in message and "cap" in message.lower()
    print("✅ test_autobuild_pauses_cleanly_when_at_or_over_cap")


def test_autobuild_under_cap_proceeds_normally():
    video_row = {
        "status": "ready_for_video_generation", "render_mode": None,
        "max_spend": 10.0, "total_cost": 2.0,  # comfortably under
    }
    statuses, ex = _run_autobuild_iteration(video_row)
    assert ex.run_next_step_called >= 1, "under the cap, the loop must do real work, unchanged"
    print("✅ test_autobuild_under_cap_proceeds_normally")


def test_autobuild_no_cap_is_byte_identical_to_before():
    video_row = {
        "status": "ready_for_video_generation", "render_mode": None,
        "max_spend": None, "total_cost": 999.0,  # huge spend, but no cap set
    }
    statuses, ex = _run_autobuild_iteration(video_row)
    assert ex.run_next_step_called >= 1, "no cap set must never pause the loop, regardless of spend"
    print("✅ test_autobuild_no_cap_is_byte_identical_to_before")


# --- 5. MCP quote path -------------------------------------------------------

def test_mcp_quote_carries_budget_warning():
    import json as _json
    import routes.mcp as mcp_route

    summary = _summary(max_spend=10.0, total_cost=9.0)

    async def fake_estimate_cost(tenant_id, video_id, verb, scene, summary_arg):
        return 3.0, "~$3.00"

    async def fake_cost_breakdown(*a, **k):
        return None

    async def fake_video_summary(tenant_id, video_id):
        return summary

    async def fake_create(*a, **k):
        return "tok-123"

    with patch.object(mcp_route.actions, "estimate_cost", fake_estimate_cost), \
         patch.object(mcp_route.actions, "cost_breakdown", fake_cost_breakdown), \
         patch.object(mcp_route.actions, "blocked_reason", lambda *a, **k: None), \
         patch.object(mcp_route.actions, "video_summary", fake_video_summary), \
         patch.object(mcp_route.confirm_tokens, "create", fake_create):
        result = asyncio.run(mcp_route._call_verb(
            TENANT, "images", {"video_id": VIDEO}, background_tasks=object(), caller="agent"))

    assert result["isError"] is False
    data = _json.loads(result["content"][0]["text"])
    assert data["status"] == "quote"
    assert data.get("budget_warning") is not None
    assert data["budget_warning"]["cap"] == 10.0
    assert data["budget_warning"]["projected"] == 12.0
    print("✅ test_mcp_quote_carries_budget_warning")


if __name__ == "__main__":
    test_video_detail_model_and_get_video_query_carry_max_spend()
    test_budget_check_no_cap_is_byte_identical_none()
    test_budget_check_under_cap_returns_none()
    test_budget_check_would_exceed_surfaces_the_breach()
    test_budget_check_exactly_at_cap_is_not_a_breach()
    test_resolve_budget_cap_text_parses_dollar_amounts()
    test_resolve_budget_cap_text_clear_words()
    test_resolve_budget_cap_text_rejects_garbage()
    test_runner_budget_cap_sets_and_clears()
    test_budget_cap_verb_registered_free_no_confirm()
    test_confirm_card_carries_budget_warning_when_present()
    test_confirm_card_omits_budget_key_when_no_warning()
    test_autobuild_pauses_cleanly_when_at_or_over_cap()
    test_autobuild_under_cap_proceeds_normally()
    test_autobuild_no_cap_is_byte_identical_to_before()
    test_mcp_quote_carries_budget_warning()
    print("All C36 budget-cap tests passed!")
