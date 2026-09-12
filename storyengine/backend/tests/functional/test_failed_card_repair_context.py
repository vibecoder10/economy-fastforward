"""Failed compact cards are repair input, never trustworthy production cards."""

import os
import sys

import pytest

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _BACKEND)

import pipeline_executor as pe  # noqa: E402


TENANT = "tenant-repair"
VIDEO = "video-repair"
ROSTER = ["I49 HMS Argus", "47 HMS Furious"]


def _video():
    return {
        "id": VIDEO,
        "render_mode": "static_docu",
        "research_payload": {
            "unit_roster": list(ROSTER),
            "unit_research_cards": [],
            "machine_raw_source_packages": {},
        },
    }


def _failed_row(**overrides):
    row = {
        "machine_name": "I49 HMS Argus",
        "roster_index": 1,
        "card": {
            "unit": "I49 HMS Argus",
            "evidence_segments": [{"evidence_id": "S1-E1"}],
        },
        "validation": {"passed": False, "warnings": ["missing required Anton slots for: tradeoff"]},
    }
    row.update(overrides)
    return row


async def _context_with_row(monkeypatch, row):
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = TENANT
    queries = []

    async def get_video(_video_id):
        return _video()

    async def trustworthy_loader(_video_id, payload, _roster, target_machine=None):
        # This is the production loader's intentional result for validation=false:
        # it retains no card in the trusted payload.
        assert target_machine == "I49 HMS Argus"
        return dict(payload, unit_research_cards=[])

    async def fake_fetch_one(query, *args):
        queries.append((query, args))
        return row

    monkeypatch.setattr(executor, "_get_video", get_video)
    monkeypatch.setattr(executor, "_load_machine_research_cards", trustworthy_loader)
    monkeypatch.setattr(pe, "_machine_documentary_hold_roster", lambda _row: list(ROSTER))
    monkeypatch.setattr(pe, "fetch_one", fake_fetch_one)

    context = await executor._load_machine_repair_context(VIDEO, "I49 HMS Argus")
    return context, queries


@pytest.mark.asyncio
async def test_repair_context_recovers_exact_failed_compact_card(monkeypatch):
    row = _failed_row()
    context, queries = await _context_with_row(monkeypatch, row)

    assert context["machine"] == "I49 HMS Argus"
    assert context["roster_index"] == 1
    assert context["card"] == row["card"]
    assert context["card"] is not row["card"], "repair must receive its own mutable copy"
    assert len(queries) == 1
    query, args = queries[0]
    assert "machine_research_cards" in query
    assert "tenant_id" in query and "video_id" in query and "roster_index" in query
    assert args == (TENANT, VIDEO, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "row",
    [
        _failed_row(machine_name="47 HMS Furious"),
        _failed_row(card={"unit": "47 HMS Furious", "evidence_segments": []}),
        _failed_row(roster_index=2),
        _failed_row(card="not-a-card"),
    ],
    ids=["wrong-row-name", "wrong-card-identity", "wrong-slot", "non-dict-card"],
)
async def test_repair_context_rejects_mismatched_failed_row(monkeypatch, row):
    context, _queries = await _context_with_row(monkeypatch, row)

    assert context["machine"] == "I49 HMS Argus"
    assert context["card"] is None


@pytest.mark.asyncio
async def test_ordinary_loader_still_excludes_failed_compact_card(monkeypatch):
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = TENANT
    row = _failed_row()
    calls = []

    async def fake_fetch_all(query, *args):
        calls.append((query, args))
        return [row]

    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)
    payload = _video()["research_payload"]

    hydrated = await executor._load_machine_research_cards(
        VIDEO, payload, list(ROSTER), target_machine="I49 HMS Argus",
    )

    assert calls[0][1] == (TENANT, VIDEO, 1)
    assert hydrated["unit_research_cards"] == []
    dropped = hydrated["_dropped_failed_research_card_validations"]
    assert dropped[pe._normalized_unit_code("I49 HMS Argus")]["warnings"] == [
        "missing required Anton slots for: tradeoff"
    ]
