import copy
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest


SPEC = importlib.util.spec_from_file_location(
    "representative_roster_prepare", Path(__file__).with_name("representative-roster-prepare.py")
)
prepare = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(prepare)


def _payload():
    return {
        "unit_roster": [{"name": f"Boat {index}", "designation": f"SS-{index}"} for index in range(20)],
        "recommended_final_roster": [f"Boat {index}" for index in range(20)],
        "roster_selection_history": [{"payload": {"unit_roster": [{"name": "Old 58"}]}}],
        "roster_selection": {"version": 1, "settings": {"target_count": 20}, "status": "completed", "independent_audit": {"passed": True}},
        "unit_research_cards": [{"machine": "Boat 0"}],
        "machine_raw_source_packages": {"BOAT0": {"source": "saved"}},
        "machine_script_previews": {"BOAT0": {"text": "saved"}},
        "roster_images": {"status": "completed"},
        "independent_selection_audit": {"passed": True},
        "machine_script_contract": "factual_machine_v1",
        "unrelated": {"keep": True},
    }


def test_prepare_preserves_full_evidence_and_clears_only_derived_state():
    original = _payload()
    before = copy.deepcopy(original)
    rows = [{"id": UUID("12345678-1234-5678-1234-567812345678"), "machine_name": "Boat 0", "created_at": datetime(2026, 9, 16, tzinfo=timezone.utc)}]

    result = prepare.prepare_payload(original, rows, datetime(2026, 9, 16, tzinfo=timezone.utc))

    assert original == before
    assert result["unit_roster"] == before["unit_roster"]
    assert result["recommended_final_roster"] == before["recommended_final_roster"]
    assert result["machine_script_contract"] == "factual_machine_v1"
    assert result["unrelated"] == {"keep": True}
    assert len(result["roster_selection_history"]) == 2
    archive = result["roster_selection_history"][-1]
    assert archive["marker"] == prepare.ARCHIVE_MARKER
    assert archive["payload"] == {key: value for key, value in before.items() if key != "roster_selection_history"}
    assert archive["compact_machine_research_cards"][0]["created_at"] == "2026-09-16T00:00:00+00:00"
    assert archive["compact_machine_research_cards"][0]["id"] == "12345678-1234-5678-1234-567812345678"
    for field in prepare.DERIVED_FIELDS | {"independent_selection_audit"}:
        assert field not in result
    assert result["roster_selection"]["status"] == "needs_review"
    assert result["roster_selection"]["version"] == 1
    assert result["roster_selection"]["settings"] == {"target_count": 20}
    assert "independent_audit" not in result["roster_selection"]
    assert result["unit_roster_validation"]["passed"] is False


def test_prepare_refuses_the_archive_marker_on_repeat():
    prepared = prepare.prepare_payload(_payload(), [], "2026-09-16T00:00:00+00:00")
    with pytest.raises(ValueError, match="archive marker"):
        prepare.prepare_payload(prepared, [], "2026-09-16T00:00:01+00:00")


def test_live_legacy_range_fixture_is_eligible_but_individual_roster_is_refused():
    fixture = json.loads(Path(__file__).with_name("representative-roster-before-rerun-full.json").read_text())
    video = fixture["video"]
    assert prepare._assert_video_is_eligible(video)["unit_roster"][0]["name"] == "Holland class"

    individual = copy.deepcopy(video)
    individual["research_payload"]["unit_roster"] = [
        {"name": f"Named Boat {index}", "designation": f"SS-{index}"} for index in range(20)
    ]
    with pytest.raises(RuntimeError, match="legacy range roster"):
        prepare._assert_video_is_eligible(individual)
