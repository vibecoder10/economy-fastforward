"""Independent verifier-only adversarial checks for Custom Film M2-2.

These tests are intentionally separate from the engineer-authored suite. They
exercise contract edges that are load-bearing for accepting the M2-2 chunk.
"""

import asyncio
import copy
import importlib.util
import json
import re
from pathlib import Path

import pytest

import custom_film_contract as contract
import custom_film_planner as planner
import routes.chat as chat_route


_ENGINEER_TEST_PATH = Path(__file__).with_name("test_custom_film_planner.py")
_ENGINEER_TEST_SPEC = importlib.util.spec_from_file_location(
    "_m2_planner_fixture_source",
    _ENGINEER_TEST_PATH,
)
assert _ENGINEER_TEST_SPEC and _ENGINEER_TEST_SPEC.loader
_FIXTURES = importlib.util.module_from_spec(_ENGINEER_TEST_SPEC)
_ENGINEER_TEST_SPEC.loader.exec_module(_FIXTURES)


@pytest.fixture
def manifest():
    return contract.build_capability_manifest(_FIXTURES._profiles())


@pytest.mark.parametrize(
    ("user_request", "focus"),
    [
        ("Make a custom film about render_mode", "render_mode"),
        ("Make a custom film about render mode", "render mode"),
        (
            "Make a custom film about animated_investigative_documentary",
            "animated_investigative_documentary",
        ),
        ("Make a custom film about steel and animate it with Sora", "Sora"),
        ("Make a custom film about steel using OpenAI images", "OpenAI"),
        (
            "Make a custom film about steel with a zero-dollar cost estimate",
            "zero-dollar cost estimate",
        ),
        (
            "Make a custom film about steel using Sora",
            "steel using Sora",
        ),
        (
            "Make a custom film about steel via OpenAI",
            "steel via OpenAI",
        ),
        (
            "Make a custom film about steel powered by NebulaForge",
            "steel powered by NebulaForge",
        ),
        (
            "Make a custom film about steel through NebulaForge",
            "steel through NebulaForge",
        ),
        (
            "Make a custom film about steel using nebulaforge",
            "steel using nebulaforge",
        ),
    ],
)
def test_verifier_focus_cannot_smuggle_reserved_contract_provider_or_quote_language(
    manifest, user_request, focus
):
    proposal = _FIXTURES._proposal()
    proposal["sections"][0]["focus"] = focus
    with pytest.raises(planner.CustomFilmPlannerError):
        planner.compile_planner_proposal(
            user_request,
            proposal,
            manifest,
        )


@pytest.mark.parametrize(
    "focus",
    [
        "OpenAI partnership with Apple",
        "the history of Sora",
        "the economics of animation",
        "companies using OpenAI in classrooms",
        "artists using Sora for criticism",
        "movies powered by friendship",
        "journeys through Ancient Rome",
        "companies using recycled steel",
        "trade via the Silk Road",
    ],
)
def test_verifier_named_company_or_cost_topic_remains_valid_content(
    manifest, focus
):
    proposal = _FIXTURES._proposal()
    for section in proposal["sections"]:
        section["focus"] = focus
    compiled = planner.compile_planner_proposal(
        f"Make a custom film about {focus}",
        proposal,
        manifest,
    )
    assert compiled.planner_proposal["sections"][0]["focus"] == focus
    assert focus in compiled.display_plan["sections"][0]["purpose"]


def test_verifier_unknown_lowercase_content_cannot_change_executable_sources(
    manifest,
):
    focus = "steel using quartzworks"
    proposal = _FIXTURES._proposal()
    for section in proposal["sections"]:
        section["focus"] = focus
    compiled = planner.compile_planner_proposal(
        f"Make a custom film about {focus}",
        proposal,
        manifest,
    )
    baseline = planner.compile_planner_proposal(
        "Make a custom film about steel",
        _FIXTURES._proposal(),
        manifest,
    )
    assert focus in compiled.display_plan["sections"][0]["purpose"]
    assert [
        section["knobs"] for section in compiled.internal_plan["sections"]
    ] == [
        section["knobs"] for section in baseline.internal_plan["sections"]
    ]
    assert [
        (
            section["structure_source"],
            section["writing_source"],
            section["visual_source"],
        )
        for section in compiled.planner_proposal["sections"]
    ] == [
        (
            section["structure_source"],
            section["writing_source"],
            section["visual_source"],
        )
        for section in baseline.planner_proposal["sections"]
    ]
    assert "provider_id" not in json.dumps(compiled.internal_plan)


@pytest.mark.parametrize(
    "message",
    [
        "What is a custom film?",
        "Do not make a custom film; make a normal photo documentary.",
        "I don't want a custom film.",
        "We mixed styles in the last film; explain what happened.",
    ],
)
def test_verifier_intent_does_not_capture_questions_negations_or_past_tense(message):
    assert not planner.is_custom_film_intent(message)


@pytest.mark.parametrize(
    "message",
    [
        "Use a photo-documentary opening, an animated explanation, and a bilingual ending.",
        "Start with evidence stills, then switch to character animation section by section.",
    ],
)
def test_verifier_intent_accepts_natural_mixed_section_requests(message):
    assert planner.is_custom_film_intent(message)


def test_verifier_followup_compile_reuses_explicit_validated_ordered_ids(manifest):
    first = planner.compile_planner_proposal(
        "Make a custom film about steel",
        _FIXTURES._proposal(),
        manifest,
    )
    prior_ids = [
        section["section_id"] for section in first.internal_plan["sections"]
    ]
    revised = _FIXTURES._proposal()
    revised["sections"][1]["focus"] = "human"
    second = planner.compile_planner_proposal(
        "Make the second section more human",
        revised,
        manifest,
        prior_section_ids=prior_ids,
        prior_focuses=[
            section["focus"] for section in first.planner_proposal["sections"]
        ],
    )
    assert [
        section["section_id"] for section in second.internal_plan["sections"]
    ] == prior_ids

    with pytest.raises(planner.CustomFilmPlannerError):
        planner.compile_planner_proposal(
            "Make the second section more human",
            revised,
            manifest,
            prior_section_ids=[prior_ids[0], prior_ids[0]],
        )


def test_verifier_replan_prompt_carries_prior_proposal_but_not_private_ids(manifest):
    first = planner.compile_planner_proposal(
        "Make a custom film about steel",
        _FIXTURES._proposal(),
        manifest,
    )
    revised = _FIXTURES._proposal()
    revised["sections"][1]["focus"] = "human"
    client = _FIXTURES.FakePlannerClient(revised)
    prior_ids = [
        section["section_id"] for section in first.internal_plan["sections"]
    ]
    second = asyncio.run(
        planner.plan_custom_film(
            "Make the second section more human",
            manifest,
            client,
            prior_proposal=first.planner_proposal,
            prior_section_ids=prior_ids,
        )
    )
    prompt = client.calls[0]["prompt"]
    assert "CURRENT CONSTRAINED PLAN TO REVISE" in prompt
    assert '"focus":"steel"' in prompt
    assert all(section_id not in prompt for section_id in prior_ids)
    assert [
        section["section_id"] for section in second.internal_plan["sections"]
    ] == prior_ids


def test_verifier_custom_mode_followup_cannot_escape_to_generic_producer(monkeypatch):
    custom_calls = []

    async def fake_load(_conversation_id, _tenant_id):
        return {
            "id": "conversation-a",
            "transcript": [{"role": "assistant", "content": "{}"}],
            "state": {
                "mode": "custom_film",
                "pending_custom_film_plan": {"status": "planned_unapproved"},
            },
            "video_id": None,
        }

    async def fake_hydrate(*_args):
        return None

    async def no_cold_start(*_args, **_kwargs):
        return None

    async def fake_custom_handler(*args):
        custom_calls.append(args)
        return chat_route.ChatTurnResponse(
            conversation_id="conversation-a",
            assistant_text="updated safe plan",
            plan={"kind": "custom_film"},
            ready_to_create=False,
            phase="plan",
        )

    async def forbidden_generic_client(*_args, **_kwargs):
        raise AssertionError("Custom Film follow-up escaped to generic producer intake")

    monkeypatch.setattr(chat_route, "_load_conversation", fake_load)
    monkeypatch.setattr(chat_route, "_hydrate_creator_brief", fake_hydrate)
    monkeypatch.setattr(
        chat_route,
        "_handle_cold_start_competitor_followup",
        no_cold_start,
    )
    monkeypatch.setattr(chat_route, "_handle_custom_film_plan", fake_custom_handler)
    monkeypatch.setattr(
        chat_route,
        "_resolve_producer_client",
        forbidden_generic_client,
    )

    response = __import__("asyncio").run(
        chat_route.chat_turn(
            chat_route.ChatTurnRequest(
                conversation_id="conversation-a",
                message="Make the second section more visual",
            ),
            background_tasks=object(),
            tenant_id="tenant-a",
        )
    )
    assert response.plan == {"kind": "custom_film"}
    assert len(custom_calls) == 1


def test_verifier_success_and_failure_never_emit_legacy_plan_or_touch_paid_seams(
    monkeypatch, manifest
):
    first = planner.compile_planner_proposal(
        "Make a custom film about steel",
        _FIXTURES._proposal(),
        manifest,
    )
    prior_pending = {
        "internal_plan": first.internal_plan,
        "display_plan": first.display_plan,
        "planner_proposal": first.planner_proposal,
        "plan_hash": first.plan_hash,
        "recipe_signature": first.recipe_signature,
        "novelty": {"is_novel": True},
        "status": "planned_unapproved",
    }
    persisted = {}
    client = _FIXTURES.FakePlannerClient(_FIXTURES._proposal())

    async def fake_resolve(_tenant_id):
        return client

    async def fake_manifest():
        return manifest

    async def fake_novelty(*_args, **_kwargs):
        return planner.NoveltyResult(is_novel=True)

    async def capture_persist(_cid, _tid, transcript, state, phase, **_kwargs):
        persisted.update(
            transcript=copy.deepcopy(transcript),
            state=copy.deepcopy(state),
            phase=phase,
        )

    async def forbidden_async(*_args, **_kwargs):
        raise AssertionError("paid/approval/dispatch seam must not run")

    def forbidden_sync(*_args, **_kwargs):
        raise AssertionError("estimate/autobuild seam must not run")

    monkeypatch.setattr(chat_route, "_resolve_producer_client", fake_resolve)
    monkeypatch.setattr(planner, "load_capability_manifest", fake_manifest)
    monkeypatch.setattr(planner, "classify_plan_novelty", fake_novelty)
    monkeypatch.setattr(chat_route, "_persist", capture_persist)
    monkeypatch.setattr(chat_route, "_handle_approve", forbidden_async)
    monkeypatch.setattr(chat_route.generation_claims, "acquire", forbidden_async)
    monkeypatch.setattr(chat_route, "_estimate_plan_cost", forbidden_async)
    monkeypatch.setattr(chat_route, "_make_autobuild_step", forbidden_sync)

    state = {
        "mode": "custom_film",
        "pending_custom_film_plan": copy.deepcopy(prior_pending),
        "last_spec": {"title": "stale paid plan"},
        "pending_action": {"verb": "build"},
    }
    response = asyncio.run(
        chat_route._handle_custom_film_plan(
            "conversation-a",
            "tenant-a",
            [],
            state,
            "Make the second section more visual",
        )
    )
    assert response.plan is None
    assert response.ready_to_create is False
    assert "plan" not in json.loads(persisted["transcript"][-1]["content"])
    assert "last_spec" not in persisted["state"]
    assert "pending_action" not in persisted["state"]
    assert len(client.calls) == 1

    failing_client = _FIXTURES.FakePlannerClient({"sections": []})

    async def resolve_failure(_tenant_id):
        return failing_client

    monkeypatch.setattr(chat_route, "_resolve_producer_client", resolve_failure)
    failed_state = {
        "mode": "custom_film",
        "pending_custom_film_plan": copy.deepcopy(prior_pending),
        "last_spec": {"title": "stale paid plan"},
        "pending_action": {"verb": "build"},
    }
    failed = asyncio.run(
        chat_route._handle_custom_film_plan(
            "conversation-a",
            "tenant-a",
            [],
            failed_state,
            "Make the second section more visual",
        )
    )
    assert failed.plan is None
    assert failed.ready_to_create is False
    assert failed.phase == "plan"
    assert persisted["state"]["pending_custom_film_plan"] == prior_pending
    assert "plan" not in json.loads(persisted["transcript"][-1]["content"])
    assert "last_spec" not in persisted["state"]
    assert "pending_action" not in persisted["state"]


def test_verifier_custom_approve_with_selections_cannot_escape_to_generic_producer(
    monkeypatch,
):
    persisted = {}

    async def fake_load(_conversation_id, _tenant_id):
        return {
            "id": "conversation-a",
            "transcript": [{"role": "assistant", "content": "{}"}],
            "state": {
                "mode": "custom_film",
                "pending_custom_film_plan": {"status": "planned_unapproved"},
            },
            "video_id": None,
        }

    async def fake_hydrate(*_args):
        return None

    async def no_cold_start(*_args, **_kwargs):
        return None

    async def forbidden_generic_client(*_args, **_kwargs):
        raise AssertionError("approval-shaped Custom Film turn reached generic producer")

    async def capture_persist(_cid, _tid, transcript, state, phase, **_kwargs):
        persisted.update(
            transcript=copy.deepcopy(transcript),
            state=copy.deepcopy(state),
            phase=phase,
        )

    monkeypatch.setattr(chat_route, "_load_conversation", fake_load)
    monkeypatch.setattr(chat_route, "_hydrate_creator_brief", fake_hydrate)
    monkeypatch.setattr(
        chat_route,
        "_handle_cold_start_competitor_followup",
        no_cold_start,
    )
    monkeypatch.setattr(
        chat_route,
        "_resolve_producer_client",
        forbidden_generic_client,
    )
    monkeypatch.setattr(chat_route, "_persist", capture_persist)

    response = asyncio.run(
        chat_route.chat_turn(
            chat_route.ChatTurnRequest(
                conversation_id="conversation-a",
                approve=True,
                selections={"production_style": "photo_documentary"},
            ),
            background_tasks=object(),
            tenant_id="tenant-a",
        )
    )
    assert response.ready_to_create is False
    assert response.video_id is None
    assert response.plan is None
    assert persisted["phase"] == "plan"
    assert persisted["state"]["pending_custom_film_plan"] == {
        "status": "planned_unapproved"
    }


def test_verifier_explicit_cancel_exits_custom_mode(monkeypatch):
    persisted = {}

    async def fake_load(_conversation_id, _tenant_id):
        return {
            "id": "conversation-a",
            "transcript": [{"role": "assistant", "content": "{}"}],
            "state": {
                "mode": "custom_film",
                "pending_custom_film_plan": {"status": "planned_unapproved"},
            },
            "video_id": None,
        }

    async def fake_hydrate(*_args):
        return None

    async def no_cold_start(*_args, **_kwargs):
        return None

    async def no_client(_tenant_id):
        return None

    async def forbidden_custom(*_args, **_kwargs):
        raise AssertionError("explicit Custom Film exit invoked another custom replan")

    async def capture_persist(_cid, _tid, transcript, state, phase, **_kwargs):
        persisted.update(
            transcript=copy.deepcopy(transcript),
            state=copy.deepcopy(state),
            phase=phase,
        )

    monkeypatch.setattr(chat_route, "_load_conversation", fake_load)
    monkeypatch.setattr(chat_route, "_hydrate_creator_brief", fake_hydrate)
    monkeypatch.setattr(
        chat_route,
        "_handle_cold_start_competitor_followup",
        no_cold_start,
    )
    monkeypatch.setattr(chat_route, "_resolve_producer_client", no_client)
    monkeypatch.setattr(chat_route, "_handle_custom_film_plan", forbidden_custom)
    monkeypatch.setattr(chat_route, "_persist", capture_persist)

    response = asyncio.run(
        chat_route.chat_turn(
            chat_route.ChatTurnRequest(
                conversation_id="conversation-a",
                message="Cancel Custom Film; make a normal Photo Documentary instead.",
            ),
            background_tasks=object(),
            tenant_id="tenant-a",
        )
    )
    assert response.ready_to_create is False
    assert persisted["state"].get("mode") != "custom_film"
    assert "pending_custom_film_plan" not in persisted["state"]


def test_verifier_public_selector_remains_exactly_four():
    expected = {
        "bilingual_character_animation",
        "simple_language_animation",
        "photo_documentary",
        "animated_investigative_documentary",
    }
    assert set(contract.PUBLIC_PRODUCTION_STYLE_IDS) == expected

    frontend = Path(__file__).resolve().parents[3] / "frontend" / "src"
    api_text = (frontend / "lib" / "api.ts").read_text()
    selector_text = (
        frontend
        / "components"
        / "production"
        / "ProductionStyleSelector.tsx"
    ).read_text()
    block = re.search(
        r"export const PRODUCTION_STYLE_IDS = \[(.*?)\] as const",
        api_text,
        flags=re.DOTALL,
    )
    assert block is not None
    ids = set(re.findall(r'"([^"]+)"', block.group(1)))
    assert ids == expected
    assert "Custom Film" not in selector_text
    assert "Design Your Own" not in selector_text
