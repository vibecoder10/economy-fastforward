from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import factual_machine_research as factual
import pipeline_executor as pipeline


SUBMARINES = [
    "SS-1 USS Holland", "SS-2 USS Plunger", "SS-105 USS S-1",
    "SS-163 USS Barracuda", "SS-212 USS Gato", "SS-285 USS Balao",
    "SS-417 USS Tench", "SS-563 USS Tang", "AGSS-569 USS Albacore",
    "SS-580 USS Barbel", "SSN-571 USS Nautilus", "SSN-585 USS Skipjack",
    "SSN-593 USS Thresher", "SSN-637 USS Sturgeon",
    "SSN-688 USS Los Angeles", "SSN-21 USS Seawolf", "SSN-774 USS Virginia",
    "SSBN-598 USS George Washington", "SSBN-608 USS Ethan Allen",
    "SSBN-616 USS Lafayette",
]


def _candidate(text):
    return {
        "excerpt_id": "e1", "locator": "p1", "text": text,
        "source_url": "https://history.example/source", "source_capture_method": "fetched_page",
    }


def test_all_accepted_named_submarines_require_name_and_exact_hull():
    for target in SUBMARINES:
        parsed = factual.named_submarine_target(target)
        assert parsed is not None, target
        text = f"USS {parsed['name']} ({parsed['prefix']} {parsed['number']}) was commissioned by the Navy."
        assert factual.candidate_mentions_machine(text, target), target


def test_named_submarine_display_separators_resolve_canonical_identity_and_slot():
    canonical = "SS-1 USS Holland"
    separators = [" ", " - ", " – ", " — "]
    for target in SUBMARINES:
        for separator in separators:
            label = target.replace(" USS", f"{separator}USS", 1)
            assert factual.named_submarine_target(label) is not None, label
            assert pipeline._locked_roster_item_for_machine(SUBMARINES, label) == target
            assert pipeline._roster_index_for_identity(SUBMARINES, label) == SUBMARINES.index(target) + 1

    display_labels = [canonical, "SS-1 - USS Holland", "SS-1 – USS Holland", "SS-1 — USS Holland"]
    for label in display_labels:
        parsed = factual.named_submarine_target(label)
        assert parsed is not None, label
        assert parsed["prefix"] == "SS"
        assert parsed["number"] == "1"
        assert parsed["name"] == "Holland"
        assert pipeline._locked_roster_item_for_machine([canonical], label) == canonical
        assert pipeline._roster_index_for_identity([canonical], label) == 1


def test_named_submarine_roster_rejects_wrong_or_incomplete_identity_labels():
    roster = ["SS-1 USS Holland"]
    for label in ("SS-2 USS Holland", "SS-1 USS Plunger", "SS-999 USS Unknown"):
        assert pipeline._locked_roster_item_for_machine(roster, label) is None
        assert pipeline._roster_index_for_identity(roster, label) is None
    for label in ("SS-1 Holland", "SS-1", "SS-1 USS Holland class"):
        assert factual.named_submarine_target(label) is None


def test_named_submarine_rejects_wrong_hull_even_with_exact_name():
    assert not factual.candidate_mentions_machine("USS Tang (SS-306) was underway.", "SS-563 USS Tang")
    assert not factual.candidate_mentions_machine("USS Seawolf (SSN-575) was underway.", "SSN-21 USS Seawolf")
    assert not factual.candidate_mentions_machine("USS S-1 (SS-2) was underway.", "SS-105 USS S-1")
    assert factual.candidate_mentions_machine("USS Albacore (SS-569) was a research submarine.", "AGSS-569 USS Albacore")


def test_named_submarine_card_captures_unassessed_claim_assessment():
    package = {"candidate_excerpts": [_candidate("USS Nautilus (SSN-571) was commissioned in 1954.")],
               "claim_assessment": {"status": "needs_review", "conflicts": ["date disagreement"]}}
    card = factual.build_factual_evidence_card("SSN-571 USS Nautilus", package)
    assert card["confidence"] == "unassessed"
    assert card["provenance_status"] == "captured"
    assert card["claim_assessment"] == package["claim_assessment"]
    assert card["evidence_segments"][0]["confidence"] == "unassessed"
    assert card["evidence_segments"][0]["provenance_status"] == "captured"


def test_named_submarine_joins_refuse_stale_class_cards_and_packages():
    target = "SS-212 USS Gato"
    stale = "SS-212 USS Gato class"
    payload = {"unit_research_cards": [{"unit": stale, "marker": "stale"}]}
    assert pipeline._research_card_for_machine(payload, target) is None
    payload["unit_research_cards"].append({"unit": target, "marker": "current"})
    assert pipeline._research_card_for_machine(payload, target)["marker"] == "current"

    stale_package = {"machine": stale, "candidate_excerpts": []}
    assert pipeline._verified_source_package_for_machine(
        {"machine_raw_source_packages": {"SS-212 USS Gato": stale_package}}, target
    ) is None
    current_package = {"machine": target, "candidate_excerpts": []}
    assert pipeline._verified_source_package_for_machine(
        {"machine_raw_source_packages": {"SS212": current_package}}, target
    ) is current_package


def test_named_submarine_roster_slot_refuses_stale_class_but_tolerates_punctuation():
    roster = ["SS-212 USS Gato"]
    assert pipeline._roster_index_for_identity(roster, "SS-212 USS Gato class") is None
    assert pipeline._roster_index_for_identity(roster, "SS 212 USS Gato") == 1
    assert pipeline._locked_roster_item_for_machine(roster, "SS-212 USS Gato class") is None


def test_generic_aircraft_and_class_identity_behavior_remains_available():
    assert factual.candidate_mentions_machine("The B-52 Stratofortress entered service.", "B-52 Stratofortress")
    assert factual.candidate_mentions_machine("The Gato-class submarine served in the Pacific.", "SS-212 through SS-284 Gato class")
    assert pipeline._roster_index_for_identity(["B-52 Stratofortress"], "B-52") == 1


@pytest.mark.asyncio
async def test_machine_script_preview_accepts_em_dash_display_label_without_production_save():
    canonical = "SS-1 USS Holland"
    video = {
        "render_mode": "static_docu",
        "research_payload": {
            "documentary_style": "machine_documentary",
            "unit_roster": [{"designation": "SS-1", "name": "USS Holland"}],
        },
    }
    hold = AsyncMock(return_value={"status": "completed", "preview": {"machine": canonical}})
    executor = SimpleNamespace(
        tenant_id="tenant-test",
        _ensure_initialized=AsyncMock(),
        _get_video=AsyncMock(return_value=video),
        _load_prompt_overrides=AsyncMock(),
        _run_static_script_hold=hold,
    )

    result = await pipeline.PipelineExecutor.run_machine_script_preview(
        executor, "video-test", "SS-1 — USS Holland"
    )

    assert result["status"] == "completed"
    executor._ensure_initialized.assert_awaited_once_with()
    executor._get_video.assert_awaited_once_with("video-test")
    executor._load_prompt_overrides.assert_awaited_once_with(video)
    hold.assert_awaited_once_with("video-test", video, [canonical], target_machine=canonical)
    assert hold.await_args.kwargs.get("save_target_script") is None


@pytest.mark.asyncio
async def test_machine_script_preview_rejects_wrong_named_submarine_without_hold():
    canonical = "SS-1 USS Holland"
    video = {
        "render_mode": "static_docu",
        "research_payload": {
            "documentary_style": "machine_documentary",
            "unit_roster": [{"designation": "SS-1", "name": "USS Holland"}],
        },
    }
    hold = AsyncMock()
    executor = SimpleNamespace(
        tenant_id="tenant-test",
        _ensure_initialized=AsyncMock(),
        _get_video=AsyncMock(return_value=video),
        _load_prompt_overrides=AsyncMock(),
        _run_static_script_hold=hold,
    )

    result = await pipeline.PipelineExecutor.run_machine_script_preview(
        executor, "video-test", "SS-1 — USS Plunger"
    )

    assert result == {
        "status": "failed",
        "error": "Machine is not in the locked roster: SS-1 — USS Plunger",
    }
    hold.assert_not_awaited()
