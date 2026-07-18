"""agent_brain._tool_cost — the copilot's "how much has this cost?" read
(checklist §0.3d / C10 conversational door).

Locks:
- Reads generation_ledger (the SAME table routes/videos.py::get_video_ledger
  reads for the UI drawer) and groups actual_cost by stage, largest first.
- No spend yet -> a plain "no spend" answer that still quotes what's next,
  never a crash or an empty string.
- Some spend -> "Actual spend so far $X.XX: stage $a, stage $b…" plus a
  "Finishing adds ~$Y" tail sourced from actions.estimate_cost("build", ...),
  the same estimator the build confirm card uses — never a second price table.
- Finishing-adds tail is omitted when there's nothing left to spend.

Calls the module function directly with agent_brain.fetch_all and
actions.estimate_cost monkeypatched — no live DB, no LLM call (this tool is
pure data lookup + formatting, not part of the model loop).

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/functional/test_agent_brain_cost_tool.py -q
"""
import asyncio

import agent_brain
import actions

TENANT = "tenant-1"
VIDEO = "video-1"
SUMMARY = {"status": "ready_for_video_generation", "model": "grok-imagine", "pics": 10, "scenes": 5}


def test_no_spend_yet_reports_next_step(monkeypatch):
    async def fake_fetch_all(query, *args):
        return []

    async def fake_estimate(tenant_id, video_id, verb, scene, summary):
        return 1.20, "~$1.20"

    monkeypatch.setattr(agent_brain, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(actions, "estimate_cost", fake_estimate)

    result = asyncio.run(agent_brain._tool_cost(TENANT, VIDEO, SUMMARY))
    assert result == "No spend recorded yet — nothing paid has run. Next step: ~$1.20."


def test_spend_grouped_by_stage_with_finishing_tail(monkeypatch):
    rows = [
        {"stage": "pictures", "actual_cost": 2.40},
        {"stage": "pictures", "actual_cost": 0.0},  # no-op row shouldn't break rounding
        {"stage": "clips", "actual_cost": 3.90},
        {"stage": "voice", "actual_cost": 0.55},
    ]

    async def fake_fetch_all(query, *args):
        assert "generation_ledger" in query
        return rows

    async def fake_estimate(tenant_id, video_id, verb, scene, summary):
        assert verb == "build"
        return 0.45, "~$0.45"

    monkeypatch.setattr(agent_brain, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(actions, "estimate_cost", fake_estimate)

    result = asyncio.run(agent_brain._tool_cost(TENANT, VIDEO, SUMMARY))
    assert result == (
        "Actual spend so far $6.85: clips $3.90, pictures $2.40, voice $0.55. "
        "Finishing adds ~$0.45."
    )


def test_no_finishing_tail_when_nothing_left_to_spend(monkeypatch):
    async def fake_fetch_all(query, *args):
        return [{"stage": "render", "actual_cost": 0.0}]

    async def fake_estimate(tenant_id, video_id, verb, scene, summary):
        return 0.0, "no extra cost"

    monkeypatch.setattr(agent_brain, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(actions, "estimate_cost", fake_estimate)

    result = asyncio.run(agent_brain._tool_cost(TENANT, VIDEO, SUMMARY))
    assert result == "Actual spend so far $0.00: render $0.00."


def test_finishing_tail_itemizes_when_cost_breakdown_available(monkeypatch):
    """C15: when actions.cost_breakdown can cheaply produce an itemization
    for the same "build" quote, the finishing-adds tail names it — same
    numbers as the confirm card, not a re-derived estimate. A real (un-
    monkeypatched) actions.cost_breakdown call would just raise (no
    DATABASE_URL in this test env) and get caught fail-soft, so this test
    monkeypatches it directly to prove the itemization path fires."""
    rows = [{"stage": "pictures", "actual_cost": 2.40}]

    async def fake_fetch_all(query, *args):
        return rows

    async def fake_estimate(tenant_id, video_id, verb, scene, summary):
        return 0.45, "~$0.45"

    async def fake_cost_breakdown(tenant_id, video_id, verb, scene, summary):
        assert verb == "build" and scene is None
        return {
            "lines": [
                {"model_id": "grok-imagine", "display_name": "Grok Imagine", "tier": "draft",
                 "count": 3, "subtotal": 0.45},
            ],
            "total": 0.45, "all_premium_total": 3.75, "hero_scenes": [],
        }

    monkeypatch.setattr(agent_brain, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(actions, "estimate_cost", fake_estimate)
    monkeypatch.setattr(actions, "cost_breakdown", fake_cost_breakdown)

    result = asyncio.run(agent_brain._tool_cost(TENANT, VIDEO, SUMMARY))
    assert result == (
        "Actual spend so far $2.40: pictures $2.40. "
        "Finishing adds ~$0.45 (3×Grok Imagine $0.45)."
    )


def test_finishing_tail_falls_back_soft_when_cost_breakdown_errors(monkeypatch):
    """A broken/erroring cost_breakdown must never break the read — the
    plain "Finishing adds ~$X" tail still lands with no itemization."""
    async def fake_fetch_all(query, *args):
        return [{"stage": "pictures", "actual_cost": 2.40}]

    async def fake_estimate(tenant_id, video_id, verb, scene, summary):
        return 0.45, "~$0.45"

    async def fake_cost_breakdown(tenant_id, video_id, verb, scene, summary):
        raise RuntimeError("simulated DB outage")

    monkeypatch.setattr(agent_brain, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(actions, "estimate_cost", fake_estimate)
    monkeypatch.setattr(actions, "cost_breakdown", fake_cost_breakdown)

    result = asyncio.run(agent_brain._tool_cost(TENANT, VIDEO, SUMMARY))
    assert result == "Actual spend so far $2.40: pictures $2.40. Finishing adds ~$0.45."


def test_cost_tool_reachable_via_run_tool_dispatch(monkeypatch):
    async def fake_fetch_all(query, *args):
        return []

    async def fake_estimate(tenant_id, video_id, verb, scene, summary):
        return 0.0, "no extra cost"

    monkeypatch.setattr(agent_brain, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(actions, "estimate_cost", fake_estimate)

    result = asyncio.run(agent_brain._run_tool("cost", {}, TENANT, VIDEO, SUMMARY))
    assert "No spend recorded yet" in result
