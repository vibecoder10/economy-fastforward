"""G2: repair-loop convergence regression locks.

_run_unit_research_hold's per-machine repair loop (backend/pipeline_executor.py)
previously handed the model raw referee warning strings and burned a paid
repair round on failure shapes a human coordinator was fixing by hand this
week on the DVsU research simulator (tasks/evidence/dvsu-research-simulator/
STATE.md): drifted citation ids/locators after a package rebuild, and
single-word grounding misses that are really just an inflection swap or a
stray filler word.

These tests prove, offline and free (no anthropic/tavily calls - the fake
Anthropic client raises if called more times than expected):
1. A FREE deterministic pre-repair pass (pure string/dict ops) runs before
   each paid repair round and can fully resolve a card with zero paid rounds
   spent (the "convergence-shaped" case).
2. When a real paid repair round IS needed, the repair prompt now carries
   NAMED, per-failure fixes (which segment, which row to re-cite) instead of
   only the referee's raw warning strings.
3. A bracketed pennant embedded in a class-style machine's own display name
   (e.g. "(D48)") is no longer misread as an unsupported foreign designation
   inside why_this_unit_deserves_a_paragraph.
"""

import asyncio
import copy
import json
from unittest import mock

import pipeline_executor as pe

MACHINE = "Boeing XB-15"


def _segment(evidence_id: str, kind: str, claim: str, index: int) -> dict:
    return {
        "evidence_id": evidence_id,
        "kind": kind,
        "claim": claim,
        "source_excerpt": claim,
        "source_url": f"https://airandspace.si.edu/test/{kind}",
        "source_title": "Test source",
        "locator": f"S{index}-E1",
        "numeric_tokens": [],
        "confidence": "high",
    }


def _base_segments() -> list[dict]:
    rows = [
        ("E-PROBLEM", "original_problem",
         "Original problem claim grounded in the supplied source requiring a longer range bomber."),
        ("E-DECISION", "engineering_decision",
         "Engineering decision claim grounded in the supplied source with wing, engine, tail, nose, "
         "and fuselage features."),
        ("E-TRADEOFF", "tradeoff",
         "Tradeoff claim grounded in the supplied source about weight and speed."),
        ("E-REALITY", "reality",
         "Reality claim shows it was scrapped after limited squadron service during the Cold War era."),
        ("E-MEMORABLE", "memorable_fact", "Memorable fact claim grounded in the supplied source."),
        ("E-ROLE", "role_category", "Role category claim grounded in the supplied source about heavy bombers."),
    ]
    return [_segment(eid, kind, claim, i) for i, (eid, kind, claim) in enumerate(rows, start=1)]


def _base_package(segments: list[dict]) -> dict:
    return {
        "passed": True,
        "machine": MACHINE,
        "machine_key": pe._normalized_unit_code(MACHINE),
        "candidate_excerpts": [
            {
                "excerpt_id": f"S{index}-E1",
                "source_id": f"S{index}",
                "source_title": seg["source_title"],
                "source_url": seg["source_url"],
                "locator": seg["locator"],
                "text": f"{MACHINE} {seg['source_excerpt']}",
                "text_hash": "test",
                "source_capture_method": "fetched_page",
                "source_variant_selection": {
                    "selected_capture_method": "fetched_page",
                    "selected_variant": {
                        "source_capture_method": "fetched_page",
                        "covered_slot_count": 4,
                        "distinct_slot_excerpt_count": 4,
                    },
                    "evaluated_variants": [{"source_capture_method": "fetched_page", "covered_slot_count": 4}],
                    "selection_rule": "highest Anton-slot coverage; fetched_page wins exact ties",
                },
            }
            for index, seg in enumerate(segments, start=1)
        ],
    }


def _base_card(segments: list[dict]) -> dict:
    return {
        "unit": MACHINE,
        "engineering_thesis": (
            f"{MACHINE} mattered because its bomber range decision exposed power tradeoffs in service."
        ),
        "why_this_unit_deserves_a_paragraph": (
            f"{MACHINE} deserves a paragraph because its range problem exposed a tradeoff between "
            "bomber size, power, and service reality."
        ),
        "surprising_fact": "Memorable fact claim grounded in the supplied source.",
        "source_notes": ["xb15-source"],
        "timeframe": f"{MACHINE} documented through its Cold War service period.",
        "timeframe_evidence_ids": ["E-REALITY"],
        "visual_identity": f"{MACHINE} identified by its wing, engine, tail, nose, and fuselage features.",
        "visual_identity_evidence_ids": ["E-DECISION"],
        "evidence_segments": copy.deepcopy(segments),
    }


class _FakeAnthropic:
    """Records every prompt; raises past `max_calls` so a test proves exactly
    how many paid rounds the repair loop actually spent."""

    def __init__(self, response: dict, max_calls: int = 1):
        self.response = response
        self.max_calls = max_calls
        self.calls = 0
        self.prompts: list[str] = []

    async def generate(self, **kwargs):
        self.calls += 1
        self.prompts.append(kwargs["prompt"])
        if self.calls > self.max_calls:
            raise AssertionError(
                f"expected at most {self.max_calls} anthropic call(s), got a {self.calls}th - "
                "the free pre-repair pass should have converged this fixture without it"
            )
        return json.dumps(self.response)


def _run_hold(card: dict, package: dict, *, max_calls: int = 1) -> tuple[dict, _FakeAnthropic]:
    fake_anthropic = _FakeAnthropic(card, max_calls=max_calls)
    executor = pe.PipelineExecutor.__new__(pe.PipelineExecutor)
    executor.tenant_id = "tenant-test"
    executor.__dict__["_pipeline"] = type("FakePipeline", (), {"anthropic": fake_anthropic})()

    async def fake_execute(_query, *_args, **_kwargs):
        return None

    async def fake_fetch_all(*_args, **_kwargs):
        return []

    async def fake_log(*_args, **_kwargs):
        return None

    async def fake_gather(_title, _machine, _payload):
        return package

    with mock.patch.object(pe, "execute", fake_execute), mock.patch.object(pe, "fetch_all", fake_fetch_all):
        executor._log_activity = fake_log
        executor._gather_verified_machine_source_package = fake_gather
        payload = {"unit_roster": [MACHINE], "unit_research_cards": [], "machine_raw_source_packages": {}}
        result = asyncio.run(
            executor._run_unit_research_hold(
                "video-test", "Designed vs Used", payload, [MACHINE], target_machine=MACHINE,
            )
        )
    return result, fake_anthropic


def test_baseline_fixture_passes_referee_cleanly():
    """Sanity check: the shared fixture is genuinely clean before any test
    perturbs it, so a failure below is the perturbation's fault, not the
    fixture's."""
    segments = _base_segments()
    package = pe._verified_machine_source_package_with_anton_metadata(_base_package(segments), MACHINE)
    card = _base_card(segments)
    assert pe._research_card_contract_warnings(MACHINE, card, package, require_source_package=True) == []


def test_free_pass_reanchors_drifted_citation_by_excerpt_text():
    """A package rebuild renumbers/drops rows and strands a segment's
    source_excerpt_id/locator/source_url on stale identity even though its
    source_excerpt TEXT still exists verbatim in the package. The free
    pre-repair pass re-anchors it by TEXT (ported from tasks/evidence/
    dvsu-research-simulator/reanchor_card.py) with zero model calls."""
    segments = _base_segments()
    package = _base_package(segments)
    card = _base_card(segments)
    reality = next(s for s in card["evidence_segments"] if s["evidence_id"] == "E-REALITY")
    reality["locator"] = "STALE-LOC-99"
    reality["source_excerpt_id"] = "STALE-99"
    reality["source_url"] = "https://stale.example/gone"

    result, fake_anthropic = _run_hold(card, package, max_calls=1)

    assert fake_anthropic.calls == 1, "re-anchoring alone must not spend a paid repair round"
    assert result["unit_research_hold_validation"]["passed"] is True
    fixed = next(
        s for s in result["unit_research_cards"][0]["evidence_segments"] if s["evidence_id"] == "E-REALITY"
    )
    assert fixed["locator"] == "S4-E1"
    assert fixed["source_excerpt_id"] == "S4-E1"
    assert fixed["source_url"] == "https://airandspace.si.edu/test/reality"


def test_free_pass_fixes_inflection_mismatch_spent_to_spending():
    """'spent' vs the excerpt's own 'spending' is exactly the shape a human
    coordinator hand-fixed this week: _grounding_stem's suffix-stripping
    never bridges an irregular pair like this, so the free pass uses a
    shared-prefix heuristic instead and swaps the field's word for the
    excerpt's own inflection."""
    segments = _base_segments()
    for seg in segments:
        if seg["evidence_id"] == "E-REALITY":
            seg["claim"] += " Development spending consumed most of the program budget."
            seg["source_excerpt"] = seg["claim"]
    package = _base_package(segments)
    card = _base_card(segments)
    card["timeframe"] = f"{MACHINE} documented spent through its Cold War service period."

    result, fake_anthropic = _run_hold(card, package, max_calls=1)

    assert fake_anthropic.calls == 1, "an inflection swap alone must not spend a paid repair round"
    assert result["unit_research_hold_validation"]["passed"] is True
    assert result["unit_research_cards"][0]["timeframe"] == (
        f"{MACHINE} documented spending through its Cold War service period."
    )


def test_free_pass_drops_stray_filler_word():
    """A second, distinct inflection-repair shape: models keep adding filler
    words ('seen'/'ship'/'plus'/'toward'/'towards') that never appear in any
    excerpt. The free pass drops the stray word outright rather than
    spending a paid round asking the model to remove it."""
    segments = _base_segments()
    package = _base_package(segments)
    card = _base_card(segments)
    card["visual_identity"] = f"{MACHINE} identified by its wing, engine, tail, nose, seen fuselage features."

    result, fake_anthropic = _run_hold(card, package, max_calls=1)

    assert fake_anthropic.calls == 1, "dropping one stray filler word must not spend a paid repair round"
    assert result["unit_research_hold_validation"]["passed"] is True
    assert "seen" not in result["unit_research_cards"][0]["visual_identity"].lower()


def test_convergence_shaped_drifted_locator_plus_inflection_zero_model_rounds():
    """The combined shape named in the chunk spec: ONE card fixture carrying
    BOTH a drifted citation and one inflection failure gets FULLY repaired
    by the free pre-repair pass alone - zero paid repair rounds consumed."""
    segments = _base_segments()
    for seg in segments:
        if seg["evidence_id"] == "E-REALITY":
            seg["claim"] += " Development spending consumed most of the program budget."
            seg["source_excerpt"] = seg["claim"]
    package = _base_package(segments)
    card = _base_card(segments)
    card["timeframe"] = f"{MACHINE} documented spent through its Cold War service period."
    reality = next(s for s in card["evidence_segments"] if s["evidence_id"] == "E-REALITY")
    reality["locator"] = "STALE-LOC-99"
    reality["source_excerpt_id"] = "STALE-99"
    reality["source_url"] = "https://stale.example/gone"

    result, fake_anthropic = _run_hold(card, package, max_calls=1)

    assert fake_anthropic.calls == 1, "both problems together must still converge with zero paid repair rounds"
    assert result["unit_research_hold_validation"]["passed"] is True
    assert result["unit_research_hold_validation"]["target_machine_passed"] is True
    fixed_card = result["unit_research_cards"][0]
    fixed_segment = next(s for s in fixed_card["evidence_segments"] if s["evidence_id"] == "E-REALITY")
    assert fixed_segment["locator"] == "S4-E1"
    assert "spending" in fixed_card["timeframe"]


def test_structured_repair_feedback_names_segment_and_hinted_row():
    """When the free pass genuinely cannot resolve a warning (a required
    Anton beat has no segment at all), the repair prompt must carry a NAMED
    fix - which beat, which Tier 1-3 package row to cite - not just the raw
    referee warning string."""
    segments = _base_segments()
    package = _base_package(segments)
    card = _base_card(segments)
    card["evidence_segments"] = [s for s in card["evidence_segments"] if s["kind"] != "tradeoff"]

    result, fake_anthropic = _run_hold(card, package, max_calls=3)

    assert fake_anthropic.calls == 3  # initial draft + 2 repair rounds (the fake never fixes itself)
    initial_prompt, repair_prompt = fake_anthropic.prompts[0], fake_anthropic.prompts[1]
    assert "NAMED FIX" not in initial_prompt
    assert "Warnings: evidence_segments missing required Anton slots for: tradeoff" in repair_prompt
    assert "NAMED FIX - missing required beat 'tradeoff': add a NEW evidence segment citing excerpt S3-E1" in (
        repair_prompt
    )
    assert "Tier 2" in repair_prompt or "Tier 1" in repair_prompt
    # Still fails (the fake keeps returning the same broken card) - that's
    # expected; this test is about prompt CONTENT, not final convergence.
    assert result["unit_research_hold_validation"]["passed"] is False


def test_structured_repair_feedback_states_specificity_and_apostrophe_rules():
    """Field-level contract rules (last-token / first-4-token specificity,
    apostrophe tokenization) must be named explicitly in the repair prompt
    whenever the corresponding warning fires, matching the hand-fixes this
    week (tasks/evidence/dvsu-research-simulator/STATE.md)."""
    segments = _base_segments()
    package = _base_package(segments)
    card = _base_card(segments)
    # Drop the specificity anchor: no first-4-tokens open, no last-token hit.
    card["timeframe"] = "Documented service through the Cold War era."
    card["evidence_segments"] = [s for s in card["evidence_segments"] if s["kind"] != "tradeoff"]

    result, fake_anthropic = _run_hold(card, package, max_calls=3)

    repair_prompt = fake_anthropic.prompts[1]
    assert "timeframe must be specific to 'Boeing XB-15'" in repair_prompt
    assert "first four tokens" in repair_prompt
    assert "last word" in repair_prompt


# ---------------------------------------------------------------------------
# G14, 2026-07-31 (Ryan's ruling, decisions.md): the research referee's
# Tier 1-2 source requirement drops from HARD BLOCK to advisory note -
# Wikipedia-grade (Tier 3-4) sources may carry a card. The anti-hallucination
# core (excerpt-verbatim-in-fetched-text grounding) stays untouched. These
# three tests are the end-to-end (real _run_unit_research_hold, fake
# Anthropic client, zero paid calls) proof for the three load-bearing claims:
# card writing proceeds and a correctly-grounded card PASSES with an advisory
# note; a fabricated claim still FAILS; the automated repair loop no longer
# spends a paid round chasing the now-dead tier rule.
# ---------------------------------------------------------------------------

_DUKE_OF_YORK_SOURCE_URLS = (
    "https://www.thisdayinaviation.com/tag/boeing-xb-15",  # Tier 3 reference/secondary
    "https://en.wikipedia.org/wiki/Boeing_XB-15",           # Tier 4 caution/general (Wikipedia)
)


def test_g14_zero_tier_one_two_source_package_still_writes_and_passes_with_advisory():
    """Duke-of-York-shaped fixture: zero Tier 1-2 sources anywhere, only
    on-topic Tier 3/4 excerpts with verbatim-matchable text. Before G14 this
    package failed BEFORE the LLM was ever called ("Verified source package
    needs at least one Tier 1-2 primary/authoritative source before Claude
    can write a card."). Card writing must now proceed on the first attempt
    (zero repair rounds) and the card must PASS, carrying an advisory note."""
    segments = _base_segments()
    for index, seg in enumerate(segments):
        seg["source_url"] = _DUKE_OF_YORK_SOURCE_URLS[index % 2]
    package = _base_package(segments)
    card = _base_card(segments)

    result, fake_anthropic = _run_hold(card, package, max_calls=1)

    assert fake_anthropic.calls == 1, (
        "card writing must proceed on the first attempt - the pre-card Tier "
        "1-2 hard block must no longer stop the writer before the LLM call"
    )
    validation = result["unit_research_hold_validation"]
    assert validation["passed"] is True
    assert validation["target_machine_passed"] is True
    unit = validation["units"][0]
    assert unit["passed"] is True
    assert any(
        "tier_floor_advisory" in w or "caution_only_sources_advisory" in w
        for w in unit["warnings"]
    ), "a correctly-grounded Tier 3-4-only card must still carry a visible advisory note"
    assert all(str(w).startswith(pe._ADVISORY_PREFIX) for w in unit["warnings"]), (
        "every warning surviving on this clean Tier 3-4 fixture must be advisory-only"
    )


def test_g14_fabricated_excerpt_still_fails_even_with_tier_floor_advisory():
    """THE anti-hallucination guard: a card claiming source text that was
    never fetched must still FAIL end-to-end, tier floor demoted or not.
    Same zero-Tier-1-2 package as above (so every tier warning present is
    advisory-only noise), but one segment's source_excerpt is invented and
    points at a locator/excerpt_id that exists nowhere in the verified
    package - _clamp_card_excerpts_to_verified_sources cannot silently heal
    it by matching locator or text, so the referee's verbatim-in-fetched-text
    check is the only thing standing between this claim and the card - and
    it must hold."""
    segments = _base_segments()
    for index, seg in enumerate(segments):
        seg["source_url"] = _DUKE_OF_YORK_SOURCE_URLS[index % 2]
    package = _base_package(segments)
    card = _base_card(segments)
    for seg in card["evidence_segments"]:
        if seg["evidence_id"] == "E-TRADEOFF":
            seg["claim"] = "Tradeoff claim states exactly 47 units were built in 1962, a number never fetched."
            seg["source_excerpt"] = seg["claim"]
            seg["locator"] = "FABRICATED-LOCATOR-99"
            seg["source_excerpt_id"] = "FABRICATED-99"

    result, fake_anthropic = _run_hold(card, package, max_calls=3)

    validation = result["unit_research_hold_validation"]
    assert validation["passed"] is False
    unit = validation["units"][0]
    assert unit["passed"] is False
    assert any(
        "E-TRADEOFF" in w and "not found in verified fetched source text" in w
        for w in unit["warnings"]
    )
    # This is a genuinely BLOCKING failure, not an advisory note.
    assert pe._blocking_warnings(unit["warnings"]) != []


def test_clamp_canonicalizes_mismatched_excerpt_identity_from_verified_locator():
    """A model can copy the right verified row but return the wrong row id.
    Canonical provenance is deterministic bookkeeping and must be corrected
    before a paid repair is considered."""
    segments = _base_segments()
    package = pe._verified_machine_source_package_with_anton_metadata(_base_package(segments), MACHINE)
    card = _base_card(segments)
    problem = card["evidence_segments"][0]
    problem["source_excerpt_id"] = "STALE-99"

    pe._clamp_card_excerpts_to_verified_sources(card, package)

    assert problem["source_excerpt_id"] == "S1-E1"
    assert problem["locator"] == "S1-E1"


def test_free_conformance_repairs_duplicate_required_slot_sources_without_model_call():
    """When two required beats cite the same raw row, select the package's
    already-verified distinct assignment instead of paying the model to reshuffle ids."""
    segments = _base_segments()
    package = pe._verified_machine_source_package_with_anton_metadata(_base_package(segments), MACHINE)
    card = _base_card(segments)
    decision = card["evidence_segments"][1]
    problem = card["evidence_segments"][0]
    decision.update({
        "source_excerpt": problem["source_excerpt"],
        "source_excerpt_id": "S1-E1",
        "source_url": problem["source_url"],
        "source_title": problem["source_title"],
        "locator": "S1-E1",
    })
    assert any(
        "distinct raw source excerpts" in warning
        for warning in pe._research_card_contract_warnings(
            MACHINE, card, package, require_source_package=True,
        )
    )

    pe._conform_card_to_verified_package(card, package, MACHINE)

    assert pe._blocking_warnings(
        pe._research_card_contract_warnings(MACHINE, card, package, require_source_package=True)
    ) == []


def test_auto_repair_persists_free_conformance_before_any_paid_action():
    """The orchestrator must save deterministic fixes into the compact card row.

    Otherwise the dashboard reloads the stale row and every later run sees the
    same failure, even though the in-memory payload was already corrected.
    """
    segments = _base_segments()
    package = pe._verified_machine_source_package_with_anton_metadata(_base_package(segments), MACHINE)
    stale_card = _base_card(segments)
    stale_card["evidence_segments"][1].update({
        "source_excerpt": stale_card["evidence_segments"][0]["source_excerpt"],
        "source_excerpt_id": "S1-E1",
        "source_url": stale_card["evidence_segments"][0]["source_url"],
        "source_title": stale_card["evidence_segments"][0]["source_title"],
        "locator": "S1-E1",
    })
    state = {"card": stale_card, "persisted": []}
    executor = pe.PipelineExecutor("tenant-test")
    executor._initialized = True

    async def load_context(_video_id, _machine):
        return {
            "payload": {"unit_research_cards": [copy.deepcopy(state["card"])]},
            "roster": [MACHINE],
            "machine": MACHINE,
            "code": pe._normalized_unit_code(MACHINE),
            "snapshot": "[]",
            "package": copy.deepcopy(package),
            "card": copy.deepcopy(state["card"]),
            "roster_index": 1,
        }

    async def persist(_video_id, _ctx, card, warnings, verb):
        state["card"] = copy.deepcopy(card)
        state["persisted"].append((verb, list(warnings)))
        return ""

    async def forbidden_paid_action(*_args, **_kwargs):
        raise AssertionError("free conformance should clear this card before any repair action")

    async def enrich(_tenant_id, _video_id, payload):
        return payload

    executor._load_machine_repair_context = load_context
    executor._persist_repaired_card = persist
    executor._execute_repair_action = forbidden_paid_action
    with mock.patch.object(pe, "enrich_research_payload_readiness", side_effect=enrich):
        result = asyncio.run(executor.repair_machine_auto("video-test", MACHINE))

    assert result["passed"] is True
    assert result["est_spend_usd"] == 0.0
    assert result["actions"] == [{
        "verb": "conform_verified_package",
        "status": "completed",
        "detail": "",
        "est_cost_usd": 0.0,
    }]
    assert state["persisted"] == [("conform_verified_package", [])]


def test_auto_repair_syncs_an_already_passing_payload_card_to_dashboard_row():
    """A passing payload card is not enough when the compact dashboard row is stale."""
    segments = _base_segments()
    package = pe._verified_machine_source_package_with_anton_metadata(_base_package(segments), MACHINE)
    card = _base_card(segments)
    pe._conform_card_to_verified_package(card, package, MACHINE)
    pe._stamp_card_segment_provenance(card, package)
    state = {"persisted": []}
    executor = pe.PipelineExecutor("tenant-test")
    executor._initialized = True

    async def load_context(_video_id, _machine):
        return {
            "payload": {"unit_research_cards": [copy.deepcopy(card)]},
            "roster": [MACHINE],
            "machine": MACHINE,
            "code": pe._normalized_unit_code(MACHINE),
            "snapshot": "[]",
            "package": copy.deepcopy(package),
            "card": copy.deepcopy(card),
            "roster_index": 1,
        }

    async def persist(_video_id, _ctx, _card, warnings, verb):
        state["persisted"].append((verb, list(warnings)))
        return ""

    async def enrich(_tenant_id, _video_id, payload):
        return payload

    executor._load_machine_repair_context = load_context
    executor._persist_repaired_card = persist
    with mock.patch.object(pe, "enrich_research_payload_readiness", side_effect=enrich):
        result = asyncio.run(executor.repair_machine_auto("video-test", MACHINE))

    assert result["passed"] is True
    assert result["est_spend_usd"] == 0.0
    assert result["actions"] == [{
        "verb": "sync_verified_card",
        "status": "completed",
        "detail": "",
        "est_cost_usd": 0.0,
    }]
    assert state["persisted"] == [("sync_verified_card", [])]


def test_free_conformance_rebuilds_weak_ship_visual_identity_from_grounded_feature():
    """A source-backed photo caption with only a date/view is not enough for
    the image brief; reuse a concrete feature already present in verified card evidence."""
    machine = "CV-1 USS Langley"
    segments = _base_segments()
    for segment in segments:
        segment["claim"] = segment["claim"].replace(MACHINE, machine)
        segment["source_excerpt"] = segment["source_excerpt"].replace(MACHINE, machine)
    segments[1]["claim"] = "The hull of CV-1 USS Langley had previously served as USS Jupiter."
    segments[1]["source_excerpt"] = segments[1]["claim"]
    package = _base_package(segments)
    package["machine"] = machine
    package["machine_key"] = pe._normalized_unit_code(machine)
    package = pe._verified_machine_source_package_with_anton_metadata(package, machine)
    card = _base_card(segments)
    card["unit"] = machine
    card["visual_identity"] = "CV-1 USS Langley during conversion at Norfolk Navy Yard in May 1921."
    card["visual_identity_evidence_ids"] = ["E-DECISION"]

    pe._conform_card_to_verified_package(card, package, machine)

    assert "hull" in card["visual_identity"].lower()
    assert card["visual_identity_evidence_ids"] == ["E-DECISION"]
    warnings = pe._research_card_contract_warnings(machine, card, package, require_source_package=True)
    assert pe._VISUAL_IDENTITY_CONTENT_RULE not in warnings


def test_free_conformance_promotes_an_unselected_verified_visual_excerpt():
    machine = "CV-67 USS John F. Kennedy"
    segments = _base_segments()
    for segment in segments:
        segment["claim"] = segment["claim"].replace(MACHINE, machine)
        segment["source_excerpt"] = segment["source_excerpt"].replace(MACHINE, machine)
    segments[1]["claim"] = segments[1]["source_excerpt"] = (
        f"{machine} used a conventional propulsion configuration."
    )
    package = _base_package(segments)
    package["machine"] = machine
    package["machine_key"] = pe._normalized_unit_code(machine)
    visual_row = copy.deepcopy(package["candidate_excerpts"][0])
    visual_row.update({
        "excerpt_id": "S9-E1",
        "source_id": "S9",
        "locator": "S9-E1",
        "text": f"{machine} underway with aircraft visible across the flight deck.",
        "source_url": "https://example.org/cv67-photo",
        "source_tier": 1,
    })
    package["candidate_excerpts"].append(visual_row)
    package = pe._verified_machine_source_package_with_anton_metadata(package, machine)
    card = _base_card(segments)
    card["unit"] = machine
    card["visual_identity"] = f"{machine} was a conventionally powered aircraft carrier."
    card["visual_identity_evidence_ids"] = ["E-DECISION"]

    pe._conform_card_to_verified_package(card, package, machine)

    assert "flight deck" in card["visual_identity"].lower()
    visual_id = card["visual_identity_evidence_ids"][0]
    promoted = next(row for row in card["evidence_segments"] if row["evidence_id"] == visual_id)
    assert promoted["source_excerpt_id"] == "S9-E1"
    assert promoted["promoted_from_package"] is True


def test_carrier_elevators_are_recognized_as_visible_machine_features():
    assert pe._VISUAL_IDENTITY_FEATURE_PATTERN.search(
        "CV-3 USS Saratoga had two hydraulically powered elevators on her centerline."
    )


def test_g14_structured_repair_feedback_demotes_tier_four_only_to_optional_improvement():
    """The G2 structured repair feedback used to name 'required beats never
    on Tier-4 rows' as a must-fix NAMED FIX rule - G14 demotes it to a
    preference hint so paid repair rounds stop chasing a dead rule. Forces a
    REAL repair round via a genuine, non-tier problem (a missing required
    beat) so the prompt can be inspected, while a SEPARATE required beat
    (reality) sits on a Tier-4-only source with no better alternative in the
    package - the old must-fix language for that beat must be gone."""
    segments = _base_segments()
    package = _base_package(segments)  # default Tier 2 (airandspace.si.edu) elsewhere
    for seg in segments:
        if seg["evidence_id"] == "E-REALITY":
            seg["source_url"] = "https://en.wikipedia.org/wiki/Boeing_XB-15"
    for item in package["candidate_excerpts"]:
        if item["excerpt_id"] == "S4-E1":  # E-REALITY's own package row
            item["source_url"] = "https://en.wikipedia.org/wiki/Boeing_XB-15"
    card = _base_card(segments)
    card["evidence_segments"] = [s for s in card["evidence_segments"] if s["kind"] != "tradeoff"]

    result, fake_anthropic = _run_hold(card, package, max_calls=3)

    assert fake_anthropic.calls >= 2, "the missing tradeoff slot must still force a real paid repair round"
    repair_prompt = fake_anthropic.prompts[1]
    # The "Warnings:" summary line only carries BLOCKING warnings now.
    assert "Warnings: evidence_segments missing required Anton slots for: tradeoff" in repair_prompt
    assert "tier_floor_advisory" not in repair_prompt.split("\n")[0]
    # Genuine, non-tier fix: still a must-fix NAMED FIX directive.
    assert "NAMED FIX - missing required beat 'tradeoff'" in repair_prompt
    # The tier-floor-only required beat: no longer a NAMED FIX anywhere in the prompt.
    assert "NAMED FIX - required beat 'reality'" not in repair_prompt
    assert not any(
        line.startswith("NAMED FIX") and "reality" in line
        for line in repair_prompt.split("\n")
    )
    # It still surfaces - as an explicitly optional, non-blocking improvement.
    assert "OPTIONAL IMPROVEMENT (not required to pass) - required beat 'reality'" in repair_prompt
    assert result["unit_research_hold_validation"]["passed"] is False  # the real (tradeoff) gap is still unfixed


def test_d48_style_pennant_no_longer_flagged_as_unsupported_designation():
    """G2 (D48) fix: a class-style machine's OWN display name often carries a
    bracketed pennant ("HMS Illustrious (D48) ... class"). _unit_code has no
    hyphenated designation to latch onto for these names and falls back to a
    4-token glob that concatenates the whole name into one blob code, so a
    bare SET-membership check against that single blob code used to miss the
    embedded pennant entirely and flag it as an unsupported designation
    inside why_this_unit_deserves_a_paragraph."""
    machine = "HMS Illustrious (D48) Illustrious class"
    package = {
        "passed": True,
        "candidate_excerpts": [
            {
                "excerpt_id": f"S{i}-E1", "source_url": "https://x", "locator": f"S{i}-E1",
                "text": f"filler excerpt {i} text", "source_title": "T",
            }
            for i in range(1, 6)
        ] + [{
            "excerpt_id": "S1-E1", "source_url": "https://x", "locator": "S1-E1",
            "text": "test claim", "source_title": "T", "source_capture_method": "fetched_page",
        }],
    }
    card = {
        "unit": machine,
        "why_this_unit_deserves_a_paragraph": (
            "HMS Illustrious (D48) proves how an armoured flight deck decision traded aircraft "
            "capacity for survivability that no other roster machine repeats."
        ),
        "evidence_segments": [
            {
                "evidence_id": "E1", "kind": "original_problem", "claim": "test claim",
                "source_excerpt": "test claim", "source_url": "https://x", "locator": "S1-E1",
                "numeric_tokens": [],
            },
        ],
    }
    warnings = pe._validate_card_against_verified_sources(card, package)
    assert not any("unsupported designation" in warning for warning in warnings), warnings
