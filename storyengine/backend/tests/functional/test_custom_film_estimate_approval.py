from __future__ import annotations

import copy
import inspect
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks

import actions
import custom_film_contract as contract
import custom_film_planner as planner
from routes import chat


def test_m2_3_start_handler_has_no_runtime_or_create_video_seam():
    source = inspect.getsource(chat._handle_custom_film_approval_turn)
    for forbidden in (
        "create_video",
        "_make_autobuild_step",
        "background_tasks.add_task",
        "production_style_id",
    ):
        assert forbidden not in source
    assert "reserve_approved_start_intent" in source


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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("seconds", "expected_rows"),
    [(5, [2, 3]), (90, [36, 54])],
)
async def test_section_duration_allocation_reconciles_exact_runtime(
    seconds,
    expected_rows,
):
    quote = await actions.estimate_custom_film_plan(
        _plan(), total_duration_seconds=seconds
    )
    assert [row["duration_seconds"] for row in quote["sections"]] == expected_rows
    assert quote["totals"]["duration_seconds"] == seconds
    assert quote["requested_duration_seconds"] == seconds


def _pending(quote: dict) -> dict:
    quote = copy.deepcopy(quote)
    quote.setdefault("max_spend", quote["totals"]["estimated_cost"])
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
async def test_combined_yes_and_estimate_affecting_message_replans_first(
    monkeypatch,
):
    quote = await actions.estimate_custom_film_plan(
        _plan(), total_duration_seconds=90
    )
    calls = []

    async def load(*_args):
        return {
            "id": "conv",
            "video_id": None,
            "transcript": [],
            "state": {
                "mode": "custom_film",
                "pending_custom_film_plan": _pending(quote),
            },
        }

    async def hydrate(*_args):
        return None

    async def replan(
        _conversation_id,
        _tenant_id,
        _transcript,
        _state,
        user_message,
        _expected_state,
    ):
        calls.append(("replan", user_message))
        return chat.ChatTurnResponse(
            conversation_id="conv",
            assistant_text="replanned",
            phase="plan",
        )

    async def forbidden(*_args):
        raise AssertionError("approval ran before estimate-affecting edit")

    monkeypatch.setattr(chat, "_load_conversation", load)
    monkeypatch.setattr(chat, "_hydrate_creator_brief", hydrate)
    monkeypatch.setattr(chat, "_handle_custom_film_plan", replan)
    monkeypatch.setattr(chat, "_handle_custom_film_approval_turn", forbidden)
    response = await chat.chat_turn(
        chat.ChatTurnRequest(
            conversation_id="conv",
            message="make it 1.5 minutes and cap the budget at $12",
            selections={"custom_film_approval": "yes"},
        ),
        BackgroundTasks(),
        tenant_id="tenant",
    )
    assert response.assistant_text == "replanned"
    assert calls == [
        ("replan", "make it 1.5 minutes and cap the budget at $12")
    ]


class _AsyncContext:
    def __init__(self, value=None):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *_args):
        return False


class _IntentConnection:
    def __init__(self, state):
        self.state = copy.deepcopy(state)
        self.transcript = [{"role": "user", "content": "approve"}]
        self.video_id = None
        self.calls = []
        self.video_inserts = 0

    def transaction(self):
        return _AsyncContext()

    async def fetchrow(self, query, *args):
        self.calls.append(("fetchrow", query, args))
        if "FROM chat_conversations" in query:
            return {
                "id": "conv",
                "video_id": self.video_id,
                "transcript": copy.deepcopy(self.transcript),
                "state": copy.deepcopy(self.state),
            }
        if "INSERT INTO videos" in query:
            self.video_inserts += 1
            return {"id": "video-1"}
        raise AssertionError(query)

    async def execute(self, query, *args):
        self.calls.append(("execute", query, args))
        if "UPDATE chat_conversations" in query:
            import json

            self.state = json.loads(args[2])
            self.video_id = args[3]
            self.transcript = json.loads(args[4])
        return "OK"


class _IntentPool:
    def __init__(self, connection):
        self.connection = connection

    def acquire(self):
        return _AsyncContext(self.connection)


def _patch_intent_contract(monkeypatch, state):
    connection = _IntentConnection(state)

    async def pool():
        return _IntentPool(connection)

    monkeypatch.setattr(contract, "get_pool", pool)
    monkeypatch.setattr(
        contract,
        "revision_input_from_normalized_plan",
        lambda plan, _manifest: plan,
    )
    monkeypatch.setattr(
        contract,
        "normalize_plan",
        lambda plan, _manifest: plan,
    )
    return connection


@pytest.mark.asyncio
async def test_user_budget_cap_is_hashed_persisted_and_blocks_before_insert(
    monkeypatch,
):
    assert (
        chat._custom_film_requested_budget_cap(
            "Keep this Custom Film budget capped at $0.01"
        )
        == 0.01
    )
    quote = await actions.estimate_custom_film_plan(
        _plan(), total_duration_seconds=90
    )
    quote["max_spend"] = 0.01
    pending = _pending(quote)
    state = {"mode": "custom_film", "pending_custom_film_plan": pending}
    connection = _patch_intent_contract(monkeypatch, state)

    with pytest.raises(contract.CustomFilmContractError, match="Nothing was reserved"):
        await contract.reserve_approved_start_intent(
            "tenant",
            "conv",
            pending["approval_hash"],
            SimpleNamespace(version="test-v1"),
            confirmation_turn={"role": "assistant", "content": "held"},
        )
    assert connection.video_inserts == 0


@pytest.mark.asyncio
async def test_durable_intent_replay_converges_on_one_video_without_runtime(
    monkeypatch,
):
    quote = await actions.estimate_custom_film_plan(
        _plan(), total_duration_seconds=90
    )
    pending = _pending(quote)
    state = {"mode": "custom_film", "pending_custom_film_plan": pending}
    connection = _patch_intent_contract(monkeypatch, state)
    manifest = SimpleNamespace(version="test-v1")

    first = await contract.reserve_approved_start_intent(
        "tenant",
        "conv",
        pending["approval_hash"],
        manifest,
        confirmation_turn={"role": "assistant", "content": "held"},
    )
    # A second request may have loaded the pre-approval snapshot, but the
    # transaction re-reads the locked durable state and returns the first row.
    second = await contract.reserve_approved_start_intent(
        "tenant",
        "conv",
        pending["approval_hash"],
        manifest,
        confirmation_turn={"role": "assistant", "content": "held"},
    )
    assert first == {
        "video_id": "video-1",
        "created": True,
        "approval_hash": pending["approval_hash"],
        "max_spend": quote["totals"]["estimated_cost"],
        "duration_seconds": 90,
    }
    assert second["video_id"] == "video-1"
    assert second["created"] is False
    assert connection.video_inserts == 1
    assert connection.transcript == [
        {"role": "user", "content": "approve"},
        {"role": "assistant", "content": "held"},
    ]
    video_insert = next(
        call for call in connection.calls if "INSERT INTO videos" in call[1]
    )
    assert str(video_insert[2][2]) == "1.500000"
    assert float(video_insert[2][3]) == quote["totals"]["estimated_cost"]
    assert "production_style_id" not in video_insert[1]
    assert not any(
        token in call[1]
        for call in connection.calls
        for token in ("background_tasks", "Drive", "increment_usage")
    )


@pytest.mark.asyncio
async def test_reserve_commit_wins_over_stale_plan_cancel_and_control_writers(
    monkeypatch,
):
    """Exact causal race: reserve commits after three turns loaded old state."""
    quote = await actions.estimate_custom_film_plan(
        _plan(), total_duration_seconds=90
    )
    pending = _pending(quote)
    loaded_state = {"mode": "custom_film", "pending_custom_film_plan": pending}
    connection = _patch_intent_contract(monkeypatch, loaded_state)
    await contract.reserve_approved_start_intent(
        "tenant",
        "conv",
        pending["approval_hash"],
        SimpleNamespace(version="test-v1"),
        confirmation_turn={"role": "assistant", "content": "durably held"},
    )

    async def cas_after_reserve(query, *_args):
        assert "video_id IS NULL" in query
        assert "state = $6::jsonb" in query
        return None

    async def reload(_conversation_id, _tenant_id):
        return {
            "id": "conv",
            "video_id": connection.video_id,
            "transcript": copy.deepcopy(connection.transcript),
            "state": copy.deepcopy(connection.state),
            "phase": "created",
        }

    monkeypatch.setattr(chat, "fetch_one", cas_after_reserve)
    monkeypatch.setattr(chat, "_load_conversation", reload)

    # A planner completed from the pre-reservation snapshot and tries to save a
    # new unapproved plan. Its CAS must miss and converge to video-1.
    stale_planner_state = copy.deepcopy(loaded_state)
    stale_planner_state["pending_custom_film_plan"]["status"] = "planned_unapproved"
    stale_planner_state["pending_custom_film_plan"].pop("approval_hash", None)
    planner_result = await chat._persist_custom_film_cas(
        "conv",
        "tenant",
        [{"role": "assistant", "content": "stale replan"}],
        stale_planner_state,
        "plan",
        loaded_state,
    )
    assert planner_result is not None
    assert planner_result.video_id == "video-1"
    assert planner_result.phase == "created"

    # Selection-only control and cancellation loaded at the same old point are
    # guarded by the identical CAS and also converge instead of overwriting.
    control_result = await chat._handle_custom_film_control_turn(
        "conv", "tenant", [], copy.deepcopy(loaded_state), loaded_state
    )
    cancel_result = await chat._handle_custom_film_cancel_turn(
        "conv", "tenant", [], copy.deepcopy(loaded_state), loaded_state
    )
    assert control_result.video_id == "video-1"
    assert cancel_result.video_id == "video-1"
    assert connection.video_inserts == 1
    durable_pending = connection.state["pending_custom_film_plan"]
    assert durable_pending["status"] == "start_ready"
    assert durable_pending["video_id"] == "video-1"
    assert durable_pending["approval_hash"] == pending["approval_hash"]
    assert connection.video_id == "video-1"


@pytest.mark.asyncio
async def test_endpoint_reload_reconstructs_held_start_before_generic_copilot(
    monkeypatch,
):
    quote = await actions.estimate_custom_film_plan(
        _plan(), total_duration_seconds=90
    )
    pending = _pending(quote)
    pending.update(
        status="start_ready",
        start_intent_hash=pending["approval_hash"],
        video_id="video-1",
    )

    async def load(*_args):
        return {
            "id": "conv",
            "video_id": "video-1",
            "transcript": [{"role": "assistant", "content": "durably held"}],
            "state": {
                "mode": "custom_film",
                "pending_custom_film_plan": pending,
            },
            "phase": "created",
        }

    async def forbidden_copilot(*_args, **_kwargs):
        raise AssertionError("held M2-3 start escaped to generic copilot")

    monkeypatch.setattr(chat, "_load_conversation", load)
    monkeypatch.setattr(chat, "_handle_copilot", forbidden_copilot)
    response = await chat.chat_turn(
        chat.ChatTurnRequest(conversation_id="conv", message="what happened?"),
        BackgroundTasks(),
        tenant_id="tenant",
    )
    assert response.video_id == "video-1"
    assert response.phase == "created"
    assert "No generation has started" in response.assistant_text


@pytest.mark.asyncio
async def test_exact_approval_reserves_safe_intent_after_all_gates(monkeypatch):
    quote = await actions.estimate_custom_film_plan(
        _plan(), total_duration_seconds=90
    )
    state = {"mode": "custom_film", "pending_custom_film_plan": _pending(quote)}
    import vault
    from routes import billing
    order: list[str] = []

    async def key(*_args, **_kwargs):
        order.append("key")
        return "tenant-key"

    async def acquire_channel(*_args, **_kwargs):
        order.append("channel_claim")
        return True

    async def release_channel(*_args, **_kwargs):
        order.append("channel_release")

    async def manifest():
        order.append("manifest")
        return SimpleNamespace(version="test-v1")

    async def check_limit(*_args, **_kwargs):
        order.append("plan_limit")

    async def length_limit(*_args, **_kwargs):
        order.append("length_limit")

    captured = {}

    async def reserve(*_args, **kwargs):
        order.append("reserve")
        captured.update(kwargs)
        return {"video_id": "video-1", "created": True}

    async def forbidden_late_write(*_args, **_kwargs):
        raise AssertionError("approval must not perform a post-commit UPDATE")

    monkeypatch.setattr(vault, "get_required_tenant_secret", key)
    monkeypatch.setattr(chat.generation_claims, "acquire_channel", acquire_channel)
    monkeypatch.setattr(chat.generation_claims, "release_channel", release_channel)
    monkeypatch.setattr(billing, "check_plan_limits", check_limit)
    monkeypatch.setattr(billing, "enforce_video_length_cap", length_limit)
    monkeypatch.setattr(planner, "load_capability_manifest", manifest)
    monkeypatch.setattr(contract, "reserve_approved_start_intent", reserve)
    monkeypatch.setattr(chat, "execute", forbidden_late_write)

    bg = BackgroundTasks()
    response = await chat._handle_custom_film_approval_turn(
        "yes", "conv", "tenant", [], state, bg
    )
    assert response.video_id == "video-1"
    assert bg.tasks == []
    assert "No generation has started" in response.assistant_text
    assert captured["confirmation_turn"]["role"] == "assistant"
    assert "safely held" in captured["confirmation_turn"]["content"]
    assert order == [
        "key",
        "channel_claim",
        "plan_limit",
        "length_limit",
        "manifest",
        "reserve",
        "channel_release",
    ]
