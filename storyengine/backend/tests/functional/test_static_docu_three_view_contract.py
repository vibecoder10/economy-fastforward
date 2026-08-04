"""No-spend regression tests for Anton's three-view static-docu contract."""

import asyncio
import json
import os
import sys

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

import actions  # noqa: E402
from static_docu_contract import STATIC_VIEWS_MINIMUM, STATIC_VIEWS_TARGET  # noqa: E402
from test_static_docu_qa_park import _pipeline_env  # noqa: E402


@pytest.mark.asyncio
async def test_three_view_plan_is_ready_when_two_verified_views_survive(monkeypatch):
    """One failed view must not waste two already-verified complementary views."""
    import static_docu
    import shared.clients.image_client as image_client_module

    env = _pipeline_env(
        monkeypatch,
        verdicts=[True, True],
        gen_urls=[
            "https://kie.example/three-quarter.png",
            "https://kie.example/side-profile.png",
            None,
        ],
        isolate_single_view=False,
        docu_module=static_docu,
        image_client_module=image_client_module,
    )

    result = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"]
    )

    assert result["status"] == "completed"
    assert result["views_generated"] == STATIC_VIEWS_MINIMUM == 2
    assert result["segments_ready"] == result["segments_total"] == 1
    assert len(env["gen_prompts"]) == STATIC_VIEWS_TARGET == 3

    prompts = "\n".join(env["gen_prompts"]).lower()
    # 2026-08-03 fix: genuinely ROTATED camera geometry per view, not three
    # near-identical three-quarter crops (the live HMS Argus defect).
    assert "front three-quarter" in prompts
    assert "true side-on profile" in prompts
    assert "this view is meant to be a pure side-on profile" in prompts
    assert "top-down planform" in prompts
    assert "high above the machine" in prompts

    rows = sorted(env["assets"].values(), key=lambda row: row["image_index"])
    assert [row["image_index"] for row in rows] == [1, 2]
    captions = [json.loads(row["caption"]) for row in rows]
    assert [cap["view_role"] for cap in captions] == [
        "three_quarter",
        "side_profile",
    ]
    assert all(cap["target_views"] == 3 for cap in captions)
    assert all(cap["minimum_views"] == 2 for cap in captions)
    assert all(cap["specs"] == ["Wingspan 149 ft"] for cap in captions)


@pytest.mark.asyncio
async def test_one_verified_view_does_not_clear_the_two_view_gate(monkeypatch):
    import static_docu
    import shared.clients.image_client as image_client_module

    env = _pipeline_env(
        monkeypatch,
        verdicts=[True],
        gen_urls=[
            "https://kie.example/three-quarter.png",
            None,
            None,
        ],
        isolate_single_view=False,
        docu_module=static_docu,
        image_client_module=image_client_module,
    )

    result = await static_docu.generate_static_images_for_video(
        env["video_id"], env["tenant_id"]
    )

    assert result["status"] == "failed"
    assert f"{STATIC_VIEWS_MINIMUM} verified views" in result["error"]
    assert len(env["assets"]) == 1


def _summary(*, render_mode: str, scenes: int = 4) -> dict:
    return {
        "model": "grok-imagine",
        "status": "idea_logged",
        "scenes": scenes,
        "pics": 0,
        "render_mode": render_mode,
    }


def test_static_docu_picture_quote_prices_three_views_per_unit():
    cost, _ = asyncio.run(
        actions.estimate_cost(
            "tenant", "video", "images", None,
            _summary(render_mode="static_docu"),
        )
    )
    assert cost == pytest.approx(4 * STATIC_VIEWS_TARGET * actions.PICTURE_COST)

    one_cost, _ = asyncio.run(
        actions.estimate_cost(
            "tenant", "video", "images", 2,
            _summary(render_mode="static_docu"),
        )
    )
    assert one_cost == pytest.approx(STATIC_VIEWS_TARGET * actions.PICTURE_COST)


def test_static_docu_build_quote_uses_three_not_regular_six():
    static_cost, _ = asyncio.run(
        actions.estimate_cost(
            "tenant", "video", "build", None,
            _summary(render_mode="static_docu", scenes=3),
        )
    )
    regular_cost, _ = asyncio.run(
        actions.estimate_cost(
            "tenant", "video", "build", None,
            _summary(render_mode="cinematic", scenes=3),
        )
    )
    assert static_cost == pytest.approx(3 * 3 * actions.PICTURE_COST)
    assert regular_cost == pytest.approx(3 * 6 * actions.PICTURE_COST)
