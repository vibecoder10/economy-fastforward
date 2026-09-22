"""Offline SS-105 replay coverage: previews consume saved evidence only."""
from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pipeline_executor as executor
from dvsu_research_handoff import package_brief, package_brief_warnings
from factual_machine_summary import _eligible_candidates
from research_claim_assessment import current_assessment
from script_research_packet import compile_script_packet


DOCS = Path(__file__).resolve().parents[2] / "docs" / "dvsu-run-all-reliability"


def _replay_fixture():
    return json.loads((DOCS / "replay-fixtures.json").read_text())


def _fixture():
    saved = _replay_fixture()
    package = next(package for package in saved["machine_raw_source_packages"].values()
                   if package["machine"] == "SS-105 USS S-1")
    card = saved["ss105_research_card"]
    title = saved["title"]
    payload = {
        "machine_script_contract": "factual_100_v1",
        "unit_research_cards": [card],
        "machine_raw_source_packages": {"SS105": package},
    }
    return package["machine"], title, package, payload


def test_ss105_saved_package_is_current_and_compiles_without_a_provider():
    machine, title, package, _payload = _fixture()
    assessment = current_assessment(machine, package, title)
    assert assessment and assessment["status"] == "assessed"
    assert package_brief(machine, package, title)["ready"] is True
    assert package_brief_warnings(machine, package, title) == []
    packet = compile_script_packet(machine, package, assessment, _eligible_candidates(machine, package, title),
                                   subject_context=title, episode_outline=[{"scene": 1, "machine": machine}],
                                   current_briefing="", model="offline-test")
    assert packet["machine"] == machine
    assert packet["facts"]


def test_ss105_mutated_citation_rejects_the_stale_assessment():
    machine, title, package, _payload = _fixture()
    broken = copy.deepcopy(package)
    broken["claim_assessment"]["claims"][0]["evidence"][0]["quote"] = "citation no longer matches"
    assert current_assessment(machine, broken, title) is None
    assert package_brief(machine, broken, title)["ready"] is False


def test_baseline_twenty_machine_readiness_is_offline_and_reports_every_saved_gap(monkeypatch):
    saved = _replay_fixture()
    roster = saved["roster"]
    packages = saved["machine_raw_source_packages"]
    results = []
    for machine in roster:
        package = next(package for package in packages.values() if package["machine"] == machine)
        assessment = current_assessment(machine, package, saved["title"])
        ready = bool(assessment and package_brief(machine, package, saved["title"])["ready"]
                     and not package_brief_warnings(machine, package, saved["title"]))
        results.append(ready)

    assert len(results) == 20
    assert sum(results) == 20
    assert sum(not ready for ready in results) == 0
