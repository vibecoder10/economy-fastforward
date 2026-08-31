"""Roster-card removal keeps the locked and recommended rosters aligned."""

import asyncio
import json

import routes.pipeline as pipeline_route


def test_remove_roster_unit_from_payload_removes_matching_card_and_recommendation():
    remove_unit = getattr(pipeline_route, "_remove_roster_unit_from_payload", None)
    assert callable(remove_unit), "roster removal helper is missing"

    payload = {
        "unit_roster": [
            {"designation": "CVN-79", "name": "USS John F. Kennedy"},
            {"designation": "CVN-80", "name": "USS Enterprise"},
        ],
        "recommended_final_roster": [
            "USS John F. Kennedy (CVN-79)",
            "USS Enterprise (CVN-80)",
        ],
        "fact_sheet": "Existing research remains untouched.",
    }

    updated = remove_unit(payload, "CVN-80 USS Enterprise")

    assert updated["unit_roster"] == [
        {"designation": "CVN-79", "name": "USS John F. Kennedy"},
    ]
    assert updated["recommended_final_roster"] == ["USS John F. Kennedy (CVN-79)"]
    assert updated["fact_sheet"] == "Existing research remains untouched."
    assert payload["unit_roster"][1]["designation"] == "CVN-80"


def test_remove_roster_unit_route_persists_the_updated_payload_for_one_tenant(monkeypatch):
    remove_route = getattr(pipeline_route, "remove_roster_unit", None)
    request_model = getattr(pipeline_route, "RemoveRosterUnitRequest", None)
    assert callable(remove_route), "roster removal route is missing"
    assert request_model is not None, "roster removal request model is missing"

    payload = {
        "unit_roster": [
            {"designation": "CVN-79", "name": "USS John F. Kennedy"},
            {"designation": "CVN-80", "name": "USS Enterprise"},
        ],
        "recommended_final_roster": [
            "USS John F. Kennedy (CVN-79)",
            "USS Enterprise (CVN-80)",
        ],
    }
    writes = []

    async def fake_fetch_one(_query, video_id, tenant_id):
        assert video_id == "video-test"
        assert tenant_id == "tenant-test"
        return {"id": video_id, "render_mode": "static_docu", "research_payload": json.dumps(payload)}

    async def fake_execute(query, *args):
        writes.append((query, args))
        return "UPDATE 1"

    monkeypatch.setattr(pipeline_route, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(pipeline_route, "execute", fake_execute)

    result = asyncio.run(
        remove_route(
            "video-test",
            request_model(machine="CVN-80 USS Enterprise"),
            tenant_id="tenant-test",
        )
    )

    assert result == {"status": "removed", "machine": "CVN-80 USS Enterprise", "total": 1}
    assert len(writes) == 1
    query, args = writes[0]
    assert "WHERE id = $2 AND tenant_id = $3" in query
    saved = json.loads(args[0])
    assert [item["designation"] for item in saved["unit_roster"]] == ["CVN-79"]
    assert args[1:] == ("video-test", "tenant-test")
