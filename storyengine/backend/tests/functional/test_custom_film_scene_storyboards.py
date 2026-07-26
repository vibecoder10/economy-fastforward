from __future__ import annotations

import inspect
from pathlib import Path

import pytest

import custom_film_scene_storyboards as storyboards
import routes.custom_film_scene_control as routes


def exact_card(**changes):
    card = {
        "operation_type": "storyboard_images",
        "approval_status": "not_approved",
        "initial_calls": 5,
        "max_repair_calls": 0,
        "unit_max_cents": 5,
        "exact_incremental_max_cents": 25,
        "prior_completed_cumulative_spend_cents": 0,
        "new_exact_cumulative_ceiling_cents": 25,
        "shot_ids": [f"shot-{i}" for i in range(5)],
        "approval_card_hash": "a" * 64,
    }
    card.update(changes)
    return card


def test_exact_approval_law(monkeypatch):
    monkeypatch.setenv("CUSTOM_FILM_SCENE_STORYBOARD_EXECUTION_V1", "true")
    storyboards.validate_approval(exact_card(), amount_cents=25, card_hash="a" * 64)
    for change in (
        {"initial_calls": 4},
        {"max_repair_calls": 1},
        {"unit_max_cents": 4},
        {"exact_incremental_max_cents": 24},
        {"shot_ids": ["only-one"]},
    ):
        with pytest.raises(storyboards.StoryboardExecutionError):
            storyboards.validate_approval(
                exact_card(**change), amount_cents=25, card_hash="a" * 64
            )
    with pytest.raises(storyboards.StoryboardExecutionError):
        storyboards.validate_approval(exact_card(), amount_cents=24, card_hash="a" * 64)
    with pytest.raises(storyboards.StoryboardExecutionError):
        storyboards.validate_approval(exact_card(), amount_cents=25, card_hash="b" * 64)
    assert storyboards.SHOT_COUNT * storyboards.UNIT_CENTS == storyboards.MAX_CENTS == 25


def test_flag_fails_closed(monkeypatch):
    monkeypatch.delenv("CUSTOM_FILM_SCENE_STORYBOARD_EXECUTION_V1", raising=False)
    with pytest.raises(storyboards.StoryboardExecutionError):
        storyboards.validate_approval(exact_card(), amount_cents=25, card_hash="a" * 64)


def test_replay_never_creates_after_provider_identity_or_ambiguity():
    assert storyboards.replay_action("prepared", None) == "create_once"
    assert storyboards.replay_action("submitted", "kie-123") == "poll"
    assert storyboards.replay_action("completed", "kie-123") == "skip"
    assert storyboards.replay_action("reconciliation_required", None) == "stop"
    assert storyboards.replay_action("failed", None) == "stop"


@pytest.mark.asyncio
async def test_single_attempt_adapter_posts_once_on_ambiguous_create(monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self):
            raise httpx.TimeoutException("unknown create outcome")

    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None
        async def post(self, *args, **kwargs):
            calls.append((args, kwargs))
            return Response()

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: Client())
    provider = storyboards.KieSingleAttemptStoryboardProvider("tenant-key")
    with pytest.raises(storyboards.AmbiguousCreate):
        await provider.create({"model": storyboards.PROVIDER_MODEL, "input": {}})
    assert len(calls) == 1


def test_fixture_is_current_one_scene_five_shots_six_locks():
    root = Path(__file__).resolve().parents[3]
    fixture = storyboards.compile_below_the_forecast_fixture(
        root / "tasks/below-the-forecast-storyboard.md"
    )
    assert fixture["title"] == "Below the Forecast"
    assert len(fixture["locks"]) == 6
    assert fixture["scene"]["scene_number"] == 1
    assert len(fixture["scene"]["shot_ids"]) == 5
    assert [shot["order_index"] for shot in fixture["shots"]] == list(range(5))
    assert all("Cinematic photoreal 16:9" in shot["storyboard_prompt"] for shot in fixture["shots"])
    assert "nineteen-year-old sheltered heir" in fixture["locks"]["cast"]["lio_arden"].lower()
    draft = storyboards._below_the_forecast_director_draft(
        "11111111-1111-4111-8111-111111111111", fixture
    )
    compiled = storyboards.compile_director_contract(
        draft,
        plan_id="22222222-2222-4222-8222-222222222222",
        plan_hash="a" * 64,
        section_ids=["11111111-1111-4111-8111-111111111111"],
        total_frames=600,
        section_frame_counts={"11111111-1111-4111-8111-111111111111": 600},
        section_shot_counts={"11111111-1111-4111-8111-111111111111": 5},
        fps=24,
    )
    assert len(compiled["shots"]) == 5


def test_surface_has_only_storyboard_execution_and_no_downstream_paths():
    paths = [route.path for route in routes.router.routes]
    assert any(path.endswith("/storyboards/approve") for path in paths)
    combined = inspect.getsource(storyboards)
    for forbidden in ("nano-banana", "animation_approved", "audio_approved", "upload", "publish"):
        assert forbidden not in combined
    assert "max_tries=1" in (Path(storyboards.__file__).parent / "worker.py").read_text()


def test_migration_schema_parity_and_safety():
    root = Path(__file__).resolve().parents[3]
    migration = (root / "backend/migrations/138_custom_film_scene_storyboards.sql").read_text()
    schema = (root / "schema.sql").read_text()
    body = migration.split("BEGIN;\n\n", 1)[1].rsplit("\n\nCOMMIT;", 1)[0] + "\n"
    parity = schema.split("-- CUSTOM_FILM_SCENE_STORYBOARDS_BEGIN\n", 1)[1].split(
        "-- CUSTOM_FILM_SCENE_STORYBOARDS_END", 1
    )[0]
    assert parity == body
    assert "provider identity is write-once" in migration
    assert "Scene storyboard approval is immutable" in migration
    assert "state cannot regress" in migration
    assert "REVOKE ALL" in migration
    source = inspect.getsource(storyboards.execute_run)
    assert "ON CONFLICT (video_id,stage,kie_task_id)" in source
    assert "actual_cost,kie_task_id" in source
    assert "0.05,0.05" in source
