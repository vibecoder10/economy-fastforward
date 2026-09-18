"""Unit tests for dvsu_research_v2 (DVSU research pipeline v2, Call 3) and for
pipeline_executor._run_unit_research_hold's factual_100_v1 single-machine
wiring to it.

Mocking pattern mirrors tests/test_dvsu_roster_v2.py: a trivial hand-rolled
client with an async ``generate(self, **kwargs)`` that captures kwargs and
returns queued JSON strings - never a mock of the Anthropic SDK itself.
"""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import dvsu_research_v2 as v2

MACHINE = "USS Nautilus SSN-571"
TITLE = "The Submarine That Changed Naval Warfare"


class _Client:
    """Captures every generate() call's kwargs; returns queued responses in order."""

    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


def _slot_response(answer, url, quote):
    return json.dumps({"answer": answer, "source_url": url, "quote": quote})


def _six_slot_responses():
    return [
        _slot_response("Problem answer.", "https://example.navy.mil/problem", "Problem quote."),
        _slot_response("Design answer.", "https://example.navy.mil/design", "Design quote."),
        _slot_response("Trade-off answer.", "https://example.navy.mil/tradeoff", "Trade-off quote."),
        json.dumps({"candidates": [
            {"fact": "Outcome one.", "source_url": "https://example.navy.mil/outcome1", "quote": "Outcome quote one."},
            {"fact": "Outcome two.", "source_url": "https://example.navy.mil/outcome2", "quote": "Outcome quote two."},
        ]}),
        _slot_response("Surprising answer.", "https://example.navy.mil/surprise", "Surprising quote."),
        _slot_response("Contrast answer.", "https://example.navy.mil/contrast", "Contrast quote."),
    ]


# ---------------------------------------------------------------------------
# Call 3 - six separate targeted searches, never one combined broad search
# ---------------------------------------------------------------------------

def test_call3_makes_exactly_six_separate_calls_not_one_combined():
    """The single most important behavioral assertion per DESIGN.md's first
    locked rule: six discrete client.generate() calls, one per question slot."""
    client = _Client(*_six_slot_responses())
    packet = asyncio.run(v2.run_machine_research_packet(
        client, MACHINE, 1, TITLE, ["shared fact one", "shared fact two"], checkpoint_scope=None,
    ))
    assert len(client.calls) == 6
    # Every call is its own request - no call's prompt asks for more than one slot.
    prompts = [call["prompt"] for call in client.calls]
    assert len(set(prompts)) == 6
    for call in client.calls:
        assert call["system_prompt"] == v2.CALL3_SYSTEM_PROMPT
        assert call["tools"] == [{"type": "web_search_20250305", "name": "web_search", "max_uses": v2.CALL3_SEARCH_BUDGET_PER_SLOT}]
    # Shared context is folded into every slot's prompt as background, never
    # re-discovered.
    for call in client.calls:
        assert "shared fact one" in call["prompt"]
        assert "shared fact two" in call["prompt"]
    assert packet["machine"] == MACHINE
    assert packet["act_number"] == 1
    assert packet["problem"] == {"answer": "Problem answer.", "source_url": "https://example.navy.mil/problem", "quote": "Problem quote."}
    assert packet["design"]["answer"] == "Design answer."
    assert packet["trade_off"]["answer"] == "Trade-off answer."
    assert len(packet["outcome_candidates"]) == 2
    assert packet["outcome_candidates"][0]["fact"] == "Outcome one."
    assert packet["surprising_fact"]["answer"] == "Surprising answer."
    assert packet["contrast"]["answer"] == "Contrast answer."


def test_call3_gateway_mode_guard_raises_without_calling_generate():
    client = _Client()
    client._gateway_mode = True

    async def _boom(**kwargs):
        raise AssertionError("generate() must not be called when _gateway_mode is True")
    client.generate = _boom  # type: ignore[assignment]
    with pytest.raises(ValueError):
        asyncio.run(v2.run_machine_research_packet(client, MACHINE, 1, TITLE, [], checkpoint_scope=None))


def test_call3_raises_when_a_required_slot_has_no_usable_answer():
    responses = _six_slot_responses()
    responses[0] = "not json at all"  # problem slot fails to parse
    client = _Client(*responses)
    with pytest.raises(ValueError):
        asyncio.run(v2.run_machine_research_packet(client, MACHINE, 1, TITLE, [], checkpoint_scope=None))


def test_call3_raises_when_outcome_search_returns_no_candidates():
    responses = _six_slot_responses()
    responses[3] = json.dumps({"candidates": []})
    client = _Client(*responses)
    with pytest.raises(ValueError):
        asyncio.run(v2.run_machine_research_packet(client, MACHINE, 1, TITLE, [], checkpoint_scope=None))


def test_call3_outcome_normalizes_to_at_most_four_candidates():
    responses = _six_slot_responses()
    responses[3] = json.dumps({"candidates": [
        {"fact": f"Outcome {i}.", "source_url": f"https://example.navy.mil/o{i}", "quote": f"Quote {i}."}
        for i in range(6)
    ]})
    client = _Client(*responses)
    packet = asyncio.run(v2.run_machine_research_packet(client, MACHINE, 1, TITLE, [], checkpoint_scope=None))
    assert len(packet["outcome_candidates"]) == 4


def _example_packet(machine=MACHINE):
    return {
        "machine": machine, "act_number": 1,
        "problem": {"answer": "The Navy needed a submarine that could stay submerged indefinitely.",
                    "source_url": "https://example.navy.mil/nautilus-problem",
                    "quote": "The Navy needed a boat that never had to surface to recharge."},
        "design": {"answer": "Nautilus used a pressurized-water nuclear reactor for propulsion.",
                   "source_url": "https://example.navy.mil/nautilus-design",
                   "quote": "The S2W reactor drove steam turbines directly connected to the propeller shaft."},
        "trade_off": {"answer": "The reactor shielding made the hull heavier and more expensive to build.",
                      "source_url": "https://example.navy.mil/nautilus-tradeoff",
                      "quote": "Radiation shielding around the reactor compartment added significant weight."},
        "outcome_candidates": [
            {"fact": "Nautilus traveled under the North Pole in 1958.",
             "source_url": "https://example.navy.mil/nautilus-outcome1",
             "quote": "USS Nautilus became the first vessel to reach the geographic North Pole."},
            {"fact": "Nautilus set a submerged-transit record.",
             "source_url": "https://example.navy.mil/nautilus-outcome2",
             "quote": "Nautilus traveled more than 1,300 nautical miles while fully submerged."},
        ],
        "surprising_fact": {"answer": "Mamie Eisenhower christened the submarine in 1954.",
                             "source_url": "https://example.navy.mil/nautilus-surprise",
                             "quote": "Mrs. Eisenhower broke the traditional bottle of champagne across the bow."},
        "contrast": {"answer": "Nautilus is now a museum ship rather than an active warship.",
                     "source_url": "https://example.navy.mil/nautilus-contrast",
                     "quote": "The submarine was decommissioned and is preserved at the Submarine Force Museum."},
    }


# ---------------------------------------------------------------------------
# Legacy-shape adapter - the three gates the bulk coordinator checks for
# "already done": factual_card_contract_warnings, research_summary_ready,
# dvsu_research_handoff.package_brief_warnings.
# ---------------------------------------------------------------------------

def test_adapt_packet_builds_card_passing_all_three_legacy_gates():
    from factual_machine_research import factual_card_contract_warnings, factual_package_contract_warnings
    from machine_research_summary import research_summary_ready
    from dvsu_research_handoff import package_brief_warnings
    from research_claim_assessment import current_assessment, has_supported_claim

    out = v2.adapt_packet_to_factual_card(MACHINE, 1, _example_packet(), 1, TITLE)
    package, card = out["package"], out["card"]

    assert factual_package_contract_warnings(MACHINE, package) == []
    assert factual_card_contract_warnings(MACHINE, card, package) == []
    assert research_summary_ready(MACHINE, package, card["research_summary"], TITLE) is True
    assert package_brief_warnings(MACHINE, package, TITLE) == []
    assert card["script_brief_readiness"] == {"passed": True, "warnings": []}
    assessment = current_assessment(MACHINE, package, TITLE)
    assert assessment is not None and has_supported_claim(assessment)
    # 5 single-answer slots + 2 outcome candidates = 7 supported claims/sources.
    assert len(package["candidate_excerpts"]) == 7
    assert len(assessment["claims"]) == 7


@pytest.mark.parametrize("machine", [
    "USS Nautilus SSN-571",       # name-first display, generic identity matcher
    "SSN-571 USS Nautilus",       # hull-first, strict named-submarine matcher
    "Boeing B-29 Superfortress",  # aircraft designation matcher
    "Ajax class",                 # class-label matcher
    "HMS Devastation",            # named-ship matcher
])
def test_adapt_packet_passes_gates_across_roster_identity_formats(machine):
    """The candidate-text prefix design must not depend on one identity shape."""
    from factual_machine_research import factual_card_contract_warnings
    from machine_research_summary import research_summary_ready
    from dvsu_research_handoff import package_brief_warnings

    out = v2.adapt_packet_to_factual_card(machine, 1, _example_packet(machine), 1, TITLE)
    package, card = out["package"], out["card"]
    assert factual_card_contract_warnings(machine, card, package) == []
    assert research_summary_ready(machine, package, card["research_summary"], TITLE) is True
    assert package_brief_warnings(machine, package, TITLE) == []


def test_adapt_packet_missing_slot_produces_failed_summary_naming_the_gap():
    packet = _example_packet()
    packet["trade_off"] = None
    out = v2.adapt_packet_to_factual_card(MACHINE, 1, packet, 1, TITLE)
    summary = out["card"]["research_summary"]
    assert summary["passed"] is False
    assert any("trade_off" in warning for warning in summary["warnings"])


def test_mechanical_paragraph_is_a_concatenation_never_an_llm_call():
    """adapt_packet_to_factual_card is synchronous and takes no client - it
    cannot make a provider call. The research_summary paragraph must be built
    only from the packet's own slot answers, in order."""
    import inspect
    assert not inspect.iscoroutinefunction(v2.adapt_packet_to_factual_card)
    out = v2.adapt_packet_to_factual_card(MACHINE, 1, _example_packet(), 1, TITLE)
    paragraph = out["card"]["research_summary"]["paragraph"]
    packet = _example_packet()
    for slot in ("problem", "design", "trade_off", "surprising_fact", "contrast"):
        assert packet[slot]["answer"].rstrip(".") in paragraph
    for candidate in packet["outcome_candidates"]:
        assert candidate["fact"].rstrip(".") in paragraph


def test_adapt_packet_return_shape_and_readiness_field_not_set():
    """card['readiness'] is populated later by a separate enrichment pass
    (pipeline_executor's machine_research_cards.validation readback) - not by
    this adapter. See the module docstring / implementation report."""
    out = v2.adapt_packet_to_factual_card(MACHINE, 1, _example_packet(), 3, TITLE)
    assert set(out.keys()) == {"package", "card"}
    assert "readiness" not in out["card"]
    assert out["card"]["locked_roster_index"] == 3


# ---------------------------------------------------------------------------
# Drive export is fail-soft (mirrors dvsu_roster_v2.py's own test)
# ---------------------------------------------------------------------------

def test_drive_export_fail_soft_swallows_google_client_construction_failure():
    result = asyncio.run(v2.export_machine_packet_to_drive_fail_soft(TITLE, _example_packet()))
    assert result is None


# ---------------------------------------------------------------------------
# pipeline_executor._run_unit_research_hold single-machine wiring
# ---------------------------------------------------------------------------

@pytest.fixture
def hold_case(monkeypatch):
    import pipeline_executor as pe

    monkeypatch.setattr("cancel_registry.is_cancel_requested", AsyncMock(return_value=False))

    def _make(roster=(MACHINE,), payload_extra=None):
        roster = list(roster)
        payload = {
            "machine_script_contract": "factual_100_v1",
            "machine_discovery_buckets": {},  # static-docu "machine marker" (see _static_docu_locked_unit_roster)
            "unit_roster": [{"machine": machine, "act_number": 1} for machine in roster],
            "shared_context": ["A shared cross-cutting fact."],
            "unit_research_cards": [],
            "machine_raw_source_packages": {},
        }
        if payload_extra:
            payload.update(payload_extra)
        video = {
            "id": "v", "status": "idea_logged", "video_title": TITLE, "render_mode": "static_docu",
            "research_payload": payload, "max_spend": None, "total_cost": 0,
        }
        ex = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
        ex.tenant_id = "t"
        ex._get_video = AsyncMock(side_effect=lambda _vid: dict(video, research_payload=dict(payload)))
        ex._pipeline = SimpleNamespace(anthropic=None, should_cancel=AsyncMock(return_value=False))
        ex._load_machine_research_cards = AsyncMock(side_effect=lambda _v, p, _r, **kw: p)
        ex._checkpoint_machine_raw_source_package = AsyncMock(return_value="UPDATE 1")
        ex._checkpoint_one_machine_research_result = AsyncMock(return_value="UPDATE 1")
        ex._upsert_machine_research_card = AsyncMock()
        ex._log_activity = AsyncMock()
        ex._gather_verified_machine_source_package = AsyncMock(
            side_effect=AssertionError("legacy source capture must not run on the Call 3 path"))
        return ex, payload, video
    return _make


def test_hold_uses_call3_path_and_never_calls_legacy_research_functions(hold_case, monkeypatch):
    import pipeline_executor as pe
    import factual_source_search
    import research_claim_assessment as rca
    import factual_machine_summary as fms

    async def _must_not_be_called(*a, **k):
        raise AssertionError("legacy factual research function must not run on the Call 3 path")
    monkeypatch.setattr(rca, "assess_verified_package", _must_not_be_called)
    monkeypatch.setattr(fms, "generate_factual_machine_summary", _must_not_be_called)

    ledger_calls = []
    async def _record(*a, **k):
        ledger_calls.append((a, k))
    monkeypatch.setattr("generation_ledger.record_ledger_entry", _record)

    ex, payload, video = hold_case()
    client = _Client(*_six_slot_responses())
    ex._pipeline.anthropic = client

    result = asyncio.run(ex._run_unit_research_hold("v", TITLE, payload, [MACHINE], target_machine=MACHINE))

    # (a) the new path was used: exactly six generate() calls, none of them
    # the old factual_source_search discovery machinery.
    assert len(client.calls) == 6
    assert not hasattr(factual_source_search, "_called_marker")

    # (b) the legacy functions were never called (monkeypatch-raise traps
    # above did not fire) and no Kie/Tavily ledger entry was recorded (Call 3
    # has nothing to ledger - see pipeline_executor.py's comment at this
    # call site).
    assert ledger_calls == []

    # (c) the resulting card passes all three gates the bulk coordinator
    # checks for "already done".
    assert result["unit_research_hold_validation"]["passed"] is True
    card = result["unit_research_cards"][0]
    package = result["machine_raw_source_packages"][pe._verified_source_cache_key(MACHINE)]
    from factual_machine_research import factual_card_contract_warnings
    from machine_research_summary import research_summary_ready
    from dvsu_research_handoff import package_brief_warnings
    assert factual_card_contract_warnings(MACHINE, card, package) == []
    assert research_summary_ready(MACHINE, package, card["research_summary"], TITLE) is True
    assert package_brief_warnings(MACHINE, package, TITLE) == []

    ex._upsert_machine_research_card.assert_awaited_once()
    ex._checkpoint_one_machine_research_result.assert_awaited_once()


def test_hold_skips_call3_without_spend_when_already_complete(hold_case, monkeypatch):
    """A direct single-machine re-run must not re-pay for Call 3 when the
    saved card is already fully current (mirrors the bulk coordinator's own
    no-spend pre-check, applied here for a direct single-machine call)."""
    import pipeline_executor as pe

    ex, payload, video = hold_case()
    client = _Client(*_six_slot_responses())
    ex._pipeline.anthropic = client

    first = asyncio.run(ex._run_unit_research_hold("v", TITLE, payload, [MACHINE], target_machine=MACHINE))
    assert len(client.calls) == 6

    second = asyncio.run(ex._run_unit_research_hold("v", TITLE, first, [MACHINE], target_machine=MACHINE))
    assert len(client.calls) == 6  # unchanged - no new generate() calls
    assert second["unit_research_hold_validation"]["passed"] is True
