"""Tests for the compact, evidence-free DVSU writer brief."""
from __future__ import annotations

import copy
import json

import pytest

import dvsu_script_brief as brief_module
from dvsu_script_brief import build_dvsu_brief, brief_warnings


def _packet():
    return {
        "machine": "USS Example",
        "subject_context": "Submarines",
        "facts": [
            {"fact_id": "F4", "claim": "USS Example was retired in 1920.", "scope": "outcome", "narrative_roles": ["outcome"]},
            {"fact_id": "F2", "claim": "USS Example used diesel engines.", "scope": "design"},
            {"fact_id": "F1", "claim": "USS Example was designed for coastal defense.", "scope": "purpose"},
            {"fact_id": "F3", "claim": "USS Example served as a training vessel.", "scope": "service"},
        ],
    }


def test_complete_brief_is_stable_compact_and_hides_evidence():
    packet = _packet()
    original = copy.deepcopy(packet)
    result = build_dvsu_brief(packet)
    assert result["ready"] is True
    assert result["missing_fields"] == []
    assert result["fields"] == {
        "intended_role": ["F1"], "design": ["F2"], "actual_use": ["F3"], "outcome": ["F4"],
    }
    assert [fact["fact_id"] for fact in result["facts"]] == ["F1", "F2", "F3", "F4"]
    encoded = json.dumps(result, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert "quote" not in encoded and "source_url" not in encoded and "narrative_roles" not in encoded
    assert packet == original


def test_explicit_roles_win_and_invalid_roles_do_not_create_historical_coverage():
    packet = _packet()
    packet["facts"][1]["narrative_roles"] = ["outcome", "not_a_role"]
    packet["facts"][2]["narrative_roles"] = ["design"]
    result = build_dvsu_brief(packet)
    assert result["fields"]["design"] == ["F1"]
    assert result["fields"]["outcome"] == ["F2", "F4"]
    assert "F2" not in result["fields"]["design"]


def test_incomplete_and_disputed_style_input_requests_exact_targeted_research():
    packet = _packet()
    packet["facts"] = packet["facts"][1:3]
    result = build_dvsu_brief(packet)
    assert result["ready"] is False
    assert result["missing_fields"] == ["actual_use", "outcome"]
    assert brief_warnings(result) == [
        "Missing actual_use evidence; request targeted research for actual_use.",
        "Missing outcome evidence; request targeted research for outcome.",
    ]


def test_budget_overflow_does_not_truncate_facts(monkeypatch):
    packet = _packet()
    packet["facts"][0]["claim"] = "x" * 300
    monkeypatch.setattr(brief_module, "MAX_BRIEF_BYTES", 100)
    result = build_dvsu_brief(packet)
    assert result["ready"] is False
    assert result["missing_fields"] == ["compact_brief_budget"]
    assert len(result["facts"]) == 4
    assert "byte budget" in brief_warnings(result)[0]


def test_brief_requires_selected_fact_shape():
    with pytest.raises(ValueError, match="machine"):
        build_dvsu_brief({"facts": []})
    with pytest.raises(ValueError, match="fact IDs"):
        build_dvsu_brief({"machine": "USS Example", "facts": [
            {"fact_id": "F1", "claim": "A.", "scope": "x"},
            {"fact_id": "F1", "claim": "B.", "scope": "x"},
        ]})
