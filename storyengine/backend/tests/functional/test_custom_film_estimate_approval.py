from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks

import actions
import custom_film_contract as contract
import custom_film_planner as planner
from routes import chat


def _plan() -> dict:
    return {
        "schema_version": 1,
        "compatibility_version": "test-v1",
        "sections": [
            {
                "section_id": "00000000-0000-0000-0000-000000000001",
                "order_index": 0,
                "role": "opening_hook",
                "purpose": "Open the story",
                "duration_units": 400_000,
                "knobs": {
                    "image_density": {"mode": "per_item", "target": 3},
                    "animation": {"enabled": False},
                    "dubbing": {"enabled": False},
                },
                "provenance": {},
                "estimated_media": {},
            },
            {
                "section_id": "00000000-0000-0000-0000-000000000002",
                "order_index": 1,
                "role": "resolution",
                "purpose": "Resolve the story",
                "duration_units": 600_000,
                "knobs": {
                    "image_density": {
                        "mode": "visual_cue",
                        "target_per_minute": 10,
                    },
                    "animation": {"enabled": True},
                    "dubbing": {"enabled": True},
                },
                "provenance": {},
                "estimated_media": {},
            },
        ],
    }


@pytest.mark.asyncio
async def test_section_bom_reconciles_and_prices_only_through_shared_estimator(
    monkeypatch,
):
    calls: list[tuple[str, dict]] = []
    original = actions.estimate_cost

    async def wrapped(tenant, video, verb, scene, summary):
        calls.append((verb, copy.deepcopy(summary)))
        return await original(tenant, video, verb, scene, summary)

    monkeypatch.setattr(actions, "estimate_cost", wrapped)
    quote = await actions.estimate_custom_film_plan(
        _plan(), total_duration_seconds=300
    )

    assert [row["still_images"] for row in quote["sections"]] == [6, 30]
    assert [row["animation_clips"] for row in quote["sections"]] == [0, 30]
    assert [row["voice_tracks"] for row in quote["sections"]] == [1, 2]
    assert quote["totals"]["still_images"] == sum(
        row["still_images"] for row in quote["sections"]
    )
    assert quote["totals"]["animation_clips"] == sum(
        row["animation_clips"] for row in quote["sections"]
    )
    assert quote["totals"]["voice_tracks"] == sum(
        row["voice_tracks"] for row in quote["sections"]
    )
    assert quote["totals"]["estimated_cost"] == round(
        sum(row["estimated_cost"] for row in quote["sections"]), 2
    )
    assert [verb for verb, _summary in calls] == [
        "custom_film_section",
        "custom_film_section",
    ]
    assert quote["totals"]["provider_capabilities"] == {
        "image_generation": 36,
        "clip_generation": 30,
        "voice_generation": 3,
    }


def _pending(quote: dict) -> dict:
    plan = _plan()
    digest = contract.plan_hash(plan)
    binding = contract.approval_binding_hash(digest, quote)
    return {
        "internal_plan": plan,
        "display_plan": {"kind": "custom_film"},
        "planner_proposal": {
            "sections": [
                {
                    "focus": "A safe test film",
                    "structure_source": "photo_documentary",
                }
            ]
        },
        "plan_hash": digest,
        "quote_inputs": quote,
        "approval_hash": binding,
        "status": "awaiting_approval",
    }


@pytest.mark.asyncio
async def test_changed_quote_hash_stops_before_key_claim_create_or_schedule(
    monkeypatch,
):
    quote = await actions.estimate_custom_film_plan(
        _plan(), total_duration_seconds=300
    )
    pending = _pending(quote)
    pending["quote_inputs"]["requested_duration_seconds"] = 301
    state = {"mode": "custom_film", "pending_custom_film_plan": pending}
    async def fake_persist(*_args, **_kwargs):
        return None

    async def should_not_run(*_args, **_kwargs):
        raise AssertionError("stale approval crossed a pre-spend gate")

    import vault
    monkeypatch.setattr(chat, "_persist", fake_persist)
    monkeypatch.setattr(vault, "get_required_tenant_secret", should_not_run)
    response = await chat._handle_custom_film_approval_turn(
        "yes", "conv", "tenant", [], state, BackgroundTasks()
    )

    assert "changed" in response.assistant_text.lower()
    assert state["pending_custom_film_plan"]["status"] == "stale"
    assert "approval_hash" not in state["pending_custom_film_plan"]


@pytest.mark.asyncio
async def test_missing_tenant_key_stops_before_claim_or_schedule(monkeypatch):
    quote = await actions.estimate_custom_film_plan(
        _plan(), total_duration_seconds=300
    )
    state = {
        "mode": "custom_film",
        "pending_custom_film_plan": _pending(quote),
    }
    import vault

    async def missing(*_args, **_kwargs):
        raise RuntimeError("Add your Kie.ai key in Settings → API Keys before generating.")

    async def fake_persist(*_args, **_kwargs):
        return None

    monkeypatch.setattr(vault, "get_required_tenant_secret", missing)
    monkeypatch.setattr(chat, "_persist", fake_persist)
    monkeypatch.setattr(
        chat.generation_claims,
        "acquire_channel",
        lambda *_a, **_k: pytest.fail("claim must be after key"),
    )
    bg = BackgroundTasks()
    response = await chat._handle_custom_film_approval_turn(
        "yes", "conv", "tenant", [], state, bg
    )
    assert "Kie.ai key" in response.assistant_text
    assert bg.tasks == []


@pytest.mark.asyncio
async def test_any_failed_revision_clears_the_previous_exact_approval(monkeypatch):
    quote = await actions.estimate_custom_film_plan(
        _plan(), total_duration_seconds=300
    )
    state = {
        "mode": "custom_film",
        "pending_custom_film_plan": _pending(quote),
    }
    persisted = {}

    async def client(_tenant):
        return object()

    async def manifest():
        return SimpleNamespace(version="test-v1")

    async def fail_plan(*_args, **_kwargs):
        raise planner.CustomFilmPlannerError(planner.PLANNER_FAILURE_MESSAGE)

    async def persist(_cid, _tid, _transcript, current, _phase):
        persisted.update(copy.deepcopy(current))

    monkeypatch.setattr(chat, "_resolve_producer_client", client)
    monkeypatch.setattr(planner, "load_capability_manifest", manifest)
    monkeypatch.setattr(planner, "plan_custom_film", fail_plan)
    monkeypatch.setattr(chat, "_persist", persist)

    response = await chat._handle_custom_film_plan(
        "conv", "tenant", [], state, "make section two longer"
    )
    pending = persisted["pending_custom_film_plan"]
    assert response.phase == "plan"
    assert pending["status"] == "planned_unapproved"
    assert "approval_hash" not in pending


@pytest.mark.asyncio
async def test_budget_cap_stops_after_claim_but_before_create_and_schedule(
    monkeypatch,
):
    quote = await actions.estimate_custom_film_plan(
        _plan(), total_duration_seconds=300
    )
    state = {
        "mode": "custom_film",
        "custom_film_budget_cap": 0.01,
        "pending_custom_film_plan": _pending(quote),
    }
    import vault
    order: list[str] = []

    async def key(*_args, **_kwargs):
        order.append("key")
        return "tenant-key"

    async def claim(*_args, **_kwargs):
        order.append("claim")
        return True

    async def release(*_args, **_kwargs):
        order.append("release")

    async def fake_persist(*_args, **_kwargs):
        return None

    monkeypatch.setattr(vault, "get_required_tenant_secret", key)
    monkeypatch.setattr(chat.generation_claims, "acquire_channel", claim)
    monkeypatch.setattr(chat.generation_claims, "release_channel", release)
    monkeypatch.setattr(chat, "_persist", fake_persist)
    bg = BackgroundTasks()
    response = await chat._handle_custom_film_approval_turn(
        "yes", "conv", "tenant", [], state, bg
    )
    assert order == ["key", "claim", "release"]
    assert "Nothing was scheduled" in response.assistant_text
    assert bg.tasks == []


@pytest.mark.asyncio
async def test_exact_approval_schedules_once_after_all_gates(monkeypatch):
    quote = await actions.estimate_custom_film_plan(
        _plan(), total_duration_seconds=300
    )
    state = {
        "mode": "custom_film",
        "pending_custom_film_plan": _pending(quote),
    }
    import vault
    from routes import videos
    order: list[str] = []

    async def key(*_args, **_kwargs):
        order.append("key")
        return "tenant-key"

    async def acquire_channel(*_args, **_kwargs):
        order.append("channel_claim")
        return True

    async def release_channel(*_args, **_kwargs):
        order.append("channel_release")

    async def create_video(*_args, **_kwargs):
        order.append("create")
        return SimpleNamespace(id="video-1")

    async def manifest():
        order.append("manifest")
        return SimpleNamespace(version="test-v1")

    async def create_revision(*_args, **_kwargs):
        order.append("revision")
        return {}

    async def approve(*_args, **_kwargs):
        order.append("approve")
        return {}

    async def acquire(*_args, **_kwargs):
        order.append("main_claim")
        return True

    async def consume(*_args, **_kwargs):
        order.append("consume")
        return True

    async def persist(*_args, **_kwargs):
        order.append("persist")

    async def release(*_args, **_kwargs):
        order.append("main_release")

    def build(*_args, **_kwargs):
        order.append("build_factory")

        async def step():
            return None

        return step

    monkeypatch.setattr(vault, "get_required_tenant_secret", key)
    monkeypatch.setattr(chat.generation_claims, "acquire_channel", acquire_channel)
    monkeypatch.setattr(chat.generation_claims, "release_channel", release_channel)
    monkeypatch.setattr(chat.generation_claims, "acquire", acquire)
    monkeypatch.setattr(chat.generation_claims, "release", release)
    monkeypatch.setattr(videos, "create_video", create_video)
    monkeypatch.setattr(planner, "load_capability_manifest", manifest)
    monkeypatch.setattr(contract, "create_plan_revision", create_revision)
    monkeypatch.setattr(
        contract,
        "revision_input_from_normalized_plan",
        lambda plan, _manifest: plan,
    )
    monkeypatch.setattr(contract, "approve_current_plan", approve)
    monkeypatch.setattr(contract, "consume_current_plan_approval", consume)
    monkeypatch.setattr(chat, "_make_autobuild_step", build)
    monkeypatch.setattr(chat, "_persist", persist)

    bg = BackgroundTasks()
    response = await chat._handle_custom_film_approval_turn(
        "yes", "conv", "tenant", [], state, bg
    )
    assert response.video_id == "video-1"
    assert len(bg.tasks) == 1
    assert order == [
        "key",
        "channel_claim",
        "create",
        "manifest",
        "revision",
        "approve",
        "main_claim",
        "consume",
        "build_factory",
        "persist",
        "channel_release",
    ]
    replay = await chat._handle_custom_film_approval_turn(
        "yes", "conv", "tenant", [], state, bg
    )
    assert "unapproved plan" in replay.assistant_text
    assert len(bg.tasks) == 1
