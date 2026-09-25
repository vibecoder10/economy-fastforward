"""Independent acceptance checks for the saved-roster image boundary."""
import asyncio
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import pipeline_executor as pe
import roster_images as ri
import static_docu as sd


@pytest.fixture
def gather(monkeypatch):
    monkeypatch.setattr(ri, "ensure_selection_schema", AsyncMock())
    names = [f"Class {index}" for index in range(20)]
    payload = {"unit_roster": [{"name": name} for name in names],
               "recommended_final_roster": names[:], "research_phase": "unit_research",
               "roster_selection": {"version": 1, "status": "completed", "settings": {"duration_minutes": 20, "minutes_per_machine": 1}},
               "unit_research_cards": [{"machine": names[0], "evidence": "saved paid work"}],
               "roster_selection_history": [{"payload": {"unit_roster": list(range(58))}}]}
    video = {"id": "v", "tenant_id": "t", "render_mode": "static_docu", "status": "idea_logged", "research_payload": payload}
    cache, writes, reads = {}, [], []
    async def fetch_rows(query, tenant, keys):
        assert tenant == "t"
        assert "tenant_id=$1" in query and "ANY($2::text[])" in query
        reads.append(keys)
        return [cache[key] for key in keys if key in cache]
    actual_state = ri.roster_image_state
    async def state(current, tenant):
        return await actual_state(current, tenant, fetch_rows=fetch_rows)
    monkeypatch.setattr(ri, "roster_image_state", state)
    async def save(query, serialized, vid, tenant):
        assert (vid, tenant) == ("v", "t")
        assert "jsonb_set" in query and "'{roster_images}'" in query
        receipt = json.loads(serialized)
        writes.append(receipt)
        video["research_payload"]["roster_images"] = receipt
        return "UPDATE 1"
    monkeypatch.setattr(pe, "execute", save)
    monkeypatch.setattr(pe, "_live_roster_gate", lambda *_: {"passed": True})
    ex = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    ex.tenant_id = "t"
    ex._ensure_initialized = AsyncMock()
    ex._install_cancel_support = AsyncMock()
    ex._get_video = AsyncMock(side_effect=lambda _: copy.deepcopy(video))
    ex._log_activity = AsyncMock()
    ex._pipeline = SimpleNamespace(should_cancel=AsyncMock(return_value=False))
    ex._run_unit_research_hold = AsyncMock(side_effect=AssertionError("Image stage must not research"))
    finder = AsyncMock(side_effect=AssertionError("Finder call was not expected"))
    monkeypatch.setattr(sd, "prefetch_roster_references", finder)
    def add_photo(name, **overrides):
        key = sd._machine_key(name)
        cache[key] = {"machine_key": key, "reference_kind": "photo", "hosted_url": "https://assets.example/" + key,
                      "source_url": "https://archive.example/" + key, **overrides}
        row = cache[key]
        quote = "The source caption identifies " + name
        row["selection_review"] = {"version": 1, "status": "selected", "compared_count": 2,
            "selected": {"image_url": "https://archive.example/" + key,
                "hosted_url": "https://assets.example/" + key, "score": 80,
                "evidence": [{"url": "https://archive.example/" + key, "text": quote, "kind": "image_caption"}],
                "identity": {"status": "confirmed", "evidence": [{"url": "https://archive.example/" + key, "quote": quote}]}}}
    return SimpleNamespace(ex=ex, video=video, names=names, cache=cache, writes=writes, reads=reads,
                           finder=finder, add_photo=add_photo, state=state)


def test_cached_twenty_end_gather_without_finder_or_research(gather):
    for name in gather.names:
        gather.add_photo(name)
    before = copy.deepcopy(gather.video["research_payload"])
    result = asyncio.run(gather.ex.run_roster_image_gather("v"))
    assert result["status"] == "images_ready", result
    assert result["roster_images"]["verified"] == 20
    gather.finder.assert_not_called()
    gather.ex._run_unit_research_hold.assert_not_called()
    for key, value in before.items():
        assert gather.video["research_payload"][key] == value
    assert len(gather.reads[0]) == 20


@pytest.mark.parametrize("count,expected", [(19, "needs_review"), (20, "images_ready")])
def test_gather_saved_twenty_requires_every_verified_photo(gather, count, expected):
    async def finder(vid, tenant, *, should_cancel, on_progress):
        assert (vid, tenant) == ("v", "t")
        for index, name in enumerate(gather.names[:count]):
            gather.add_photo(name)
            await on_progress(index + 1, 20, name, "verified")
        return {"status": "completed", "verified": count, "missed": 20 - count}
    gather.finder.side_effect = finder
    result = asyncio.run(gather.ex.run_roster_image_gather("v"))
    assert result["status"] == expected, result
    assert result["roster_images"]["verified"] == count
    assert len(result["roster_images"]["missing"]) == 20 - count
    assert gather.finder.await_count == 1
    assert len(gather.video["research_payload"]["unit_research_cards"]) == 1
    assert len(gather.video["research_payload"]["roster_selection_history"][0]["payload"]["unit_roster"]) == 58
    gather.ex._run_unit_research_hold.assert_not_called()


def test_cancel_receipt_keeps_newly_saved_image_count(gather):
    async def finder(*args, **kwargs):
        gather.add_photo(gather.names[0])
        await kwargs["on_progress"](1, 20, gather.names[0], "verified")
        return {"status": "cancelled"}
    gather.finder.side_effect = finder
    result = asyncio.run(gather.ex.run_roster_image_gather("v"))
    assert result["status"] == "cancelled"
    assert result["roster_images"]["verified"] == 1
    assert len(gather.cache) == 1
    assert gather.video["research_payload"]["research_phase"] == "unit_research"


def test_photo_kind_and_provenance_are_required(gather):
    for name in gather.names:
        gather.add_photo(name)
    gather.add_photo(gather.names[0], source_url="")
    gather.add_photo(gather.names[1], hosted_url="  ")
    gather.add_photo(gather.names[2], reference_kind="design")
    result = asyncio.run(gather.state(gather.video, "t"))
    assert result["verified"] == 17
    assert result["missing"] == gather.names[:3]


def test_roster_change_during_gather_cannot_complete(gather):
    async def finder(*args, **kwargs):
        for name in gather.names:
            gather.add_photo(name)
        gather.video["research_payload"]["unit_roster"][-1]["name"] = "Changed class"
        return {"status": "completed"}
    gather.finder.side_effect = finder
    result = asyncio.run(gather.ex.run_roster_image_gather("v"))
    assert result["status"] == "needs_review"
    assert gather.video["research_payload"]["roster_images"]["status"] == "needs_review"


def test_spare_swapped_in_by_the_gather_itself_can_complete(gather):
    """The gather's own spare swap re-baselines the roster (2026-09-25)."""
    from roster_images import roster_fingerprint

    async def finder(*args, **kwargs):
        gather.video["research_payload"]["unit_roster"][-1]["name"] = "Spare class"
        names = gather.names[:-1] + ["Spare class"]
        for name in names:
            gather.add_photo(name)
        return {"status": "completed", "roster_fingerprint": roster_fingerprint(names)}
    gather.finder.side_effect = finder
    result = asyncio.run(gather.ex.run_roster_image_gather("v"))
    assert result["status"] == "images_ready", result


def test_initial_save_failure_stops_before_finder(gather, monkeypatch):
    monkeypatch.setattr(pe, "execute", AsyncMock(return_value="UPDATE 0"))
    result = asyncio.run(gather.ex.run_roster_image_gather("v"))
    assert result["status"] == "failed"
    gather.finder.assert_not_called()


def test_provider_exception_sets_failed_receipt(gather):
    gather.finder.side_effect = RuntimeError("bounded image service failure")
    result = asyncio.run(gather.ex.run_roster_image_gather("v"))
    assert result["status"] == "failed"
    assert gather.video["research_payload"]["roster_images"]["status"] == "failed"


def test_direct_runtime_research_requires_images_before_provider_work(gather):
    result = asyncio.run(gather.ex.run_unit_research("v"))
    assert result["status"] == "needs_review", result
    assert result["image_gather_failed"]
    gather.ex._run_unit_research_hold.assert_not_called()
    assert gather.writes == []


@pytest.mark.parametrize("gather_status", ["images_ready", "needs_review"])
def test_run_all_orders_roster_gather_then_research(monkeypatch, gather_status):
    import actions
    import generation_claims
    import routes.pipeline as routes

    events, statuses = [], []
    video = {"status": "idea_logged", "render_mode": "static_docu", "research_payload": {}, "max_spend": None}
    class Executor:
        async def _get_video(self, _):
            return copy.deepcopy(video)
        async def run_research(self, _):
            events.append("roster")
            video["research_payload"] = {"roster_selection": {"version": 1, "status": "completed"},
                                         "unit_roster": [f"Class {i}" for i in range(20)], "research_phase": "roster_complete"}
            return {"status": "roster_ready"}
        async def run_roster_image_gather(self, _):
            events.append("gather")
            video["research_payload"]["roster_images"] = {"status": "completed" if gather_status == "images_ready" else "needs_review"}
            return {"status": gather_status, "message": "Image result"}
        async def run_unit_research(self, _):
            events.append("research")
            return {"status": "ready_for_scripting"}
    monkeypatch.setattr(pe, "PipelineExecutor", lambda _: Executor())
    monkeypatch.setattr(actions, "_factual_script_recheck_needed", lambda _: False)
    monkeypatch.setattr(actions, "_static_image_coverage_missing", AsyncMock(return_value=False))
    monkeypatch.setattr(actions, "_factual_image_recheck_needed", AsyncMock(return_value=False))
    async def image_state(*_):
        return {"status": "completed" if video["research_payload"].get("roster_images", {}).get("status") == "completed" else "pending"}
    monkeypatch.setattr(ri, "roster_image_state", image_state)
    async def fetch_one(query, *_):
        if "pipeline_stages" in query:
            return {"pipeline_stages": ["research"]}
        if "SELECT status FROM videos" in query:
            return {"status": video["status"]}
        return None
    async def execute(query, *args):
        if "UPDATE videos SET status" in query:
            video["status"] = args[0]
        return "UPDATE 1"
    monkeypatch.setattr(actions, "fetch_one", fetch_one)
    monkeypatch.setattr(actions, "execute", execute)
    monkeypatch.setattr(routes, "_set_task_status", lambda _, status, message, **kwargs: statuses.append((status, message)))
    monkeypatch.setattr(routes, "_clear_task_status", lambda *args: None)
    monkeypatch.setattr(generation_claims, "release", AsyncMock())
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    asyncio.run(actions.make_autobuild_step("t", "v", target="pictures")())
    assert events == (["roster", "gather", "research"] if gather_status == "images_ready" else ["roster", "gather"]), (events, statuses)
    assert not any("without advancing" in str(message) for _, message in statuses)
