"""Unit locks for the roster orchestrator's surgical repair verbs.

Local/no-spend. Everything here is the DETERMINISTIC layer: excerpt lookup,
the promoted-segment builder, the cheapest-first action classifier, the
review-list merge, and the hold-validation update. The one integration-shaped
test replays the XB-19 select-miss (the golden conformance fixture's only
warning) and proves a code-only promote_excerpt clears the referee - the
whole point of the verb.

LAW FREEZE check: these tests assert repairs make the EXISTING referee pass;
no new gate behavior is pinned here.
"""
import copy
import json
import os

import pipeline_executor as pe

_FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_fixture(name):
    with open(os.path.join(_FIXTURES, name), encoding="utf-8") as fh:
        return json.load(fh)


_PACKAGES = _load_fixture("packages.json")


def _package_for(key):
    val = _PACKAGES[key]
    package = json.loads(val) if isinstance(val, str) else val
    return pe._verified_machine_source_package_with_anton_metadata(
        copy.deepcopy(package), _MACHINES[key]
    )


_MACHINES = {"XB15": "Boeing XB-15", "XB19": "Douglas XB-19", "B17": "Boeing B-17"}

_CARD_XB19 = _load_fixture("card_xb19.json")


def _xb19_card():
    return copy.deepcopy(_CARD_XB19["card"])


# ---------------------------------------------------------------------------
# excerpt lookup + promoted segment builder
# ---------------------------------------------------------------------------

def test_find_candidate_excerpt_by_id_and_locator():
    package = _package_for("XB19")
    by_id = pe._find_candidate_excerpt(package, "S3-E3")
    assert by_id is not None and by_id["excerpt_id"] == "S3-E3"
    by_locator = pe._find_candidate_excerpt(package, by_id["locator"])
    assert by_locator is by_id
    assert pe._find_candidate_excerpt(package, "S99-E9") is None
    assert pe._find_candidate_excerpt(None, "S3-E3") is None


def test_promoted_segment_is_grounded_by_construction():
    package = _package_for("XB19")
    candidate = pe._find_candidate_excerpt(package, "S3-E3")
    segment = pe._promoted_evidence_segment(candidate, "reality", _MACHINES["XB19"], set())
    # claim IS the excerpt: the word/number grounding gates cannot fire on it.
    assert segment["claim"] == segment["source_excerpt"]
    assert segment["source_excerpt_id"] == "S3-E3"
    assert segment["source_url"] == candidate["source_url"]
    assert segment["locator"] == candidate["locator"]
    assert segment["kind"] == "reality"
    assert segment["evidence_id"] == "EP-S3-E3"


def test_promoted_segment_evidence_id_dedupes():
    package = _package_for("XB19")
    candidate = pe._find_candidate_excerpt(package, "S3-E3")
    segment = pe._promoted_evidence_segment(
        candidate, "reality", _MACHINES["XB19"], {"EP-S3-E3", "EP-S3-E3-2"}
    )
    assert segment["evidence_id"] == "EP-S3-E3-3"


def test_promote_precheck_rejects_bad_promotions():
    package = _package_for("XB19")
    candidate = pe._find_candidate_excerpt(package, "S3-E3")
    machine = _MACHINES["XB19"]
    assert pe._promote_excerpt_precheck_error(None, "reality", machine)
    assert "unsupported" in pe._promote_excerpt_precheck_error(candidate, "spec", machine)
    # required-slot promotion must respect the excerpt's slot hints
    hinted = dict(candidate)
    hinted["anton_slot_hints"] = ["original_problem"]
    assert "slot-hint" in pe._promote_excerpt_precheck_error(hinted, "reality", machine)
    # a matching hint passes
    assert pe._promote_excerpt_precheck_error(candidate, "reality", machine) == ""
    untraceable = dict(candidate)
    untraceable["source_capture_method"] = ""
    assert "traceable" in pe._promote_excerpt_precheck_error(untraceable, "reality", machine)


# ---------------------------------------------------------------------------
# the XB-19 select-miss: a code-only promote clears the referee
# ---------------------------------------------------------------------------

def test_promote_excerpt_clears_the_select_miss_class():
    machine = _MACHINES["XB19"]
    package = _package_for("XB19")
    card = _xb19_card()
    before = pe._blocking_warnings(
        pe._research_card_contract_warnings(machine, card, package, require_source_package=True)
    )
    assert any(w.startswith("no designed-vs-used gap found") for w in before)

    # replay repair_promote_excerpt's deterministic card surgery
    candidate = pe._find_candidate_excerpt(package, "S3-E3")
    assert pe._promote_excerpt_precheck_error(candidate, "reality", machine) == ""
    existing_ids = {s.get("evidence_id") for s in card["evidence_segments"]}
    segment = pe._promoted_evidence_segment(candidate, "reality", machine, existing_ids)
    card["evidence_segments"].append(segment)
    card["actual_outcome"] = segment["claim"]
    card.pop("deliberately_bare", None)
    card.pop("gap_hunt_summary", None)
    notes = card.get("source_notes") if isinstance(card.get("source_notes"), list) else []
    if segment["source_url"] not in notes:
        card["source_notes"] = list(notes) + [segment["source_url"]]
    card = pe._normalize_card_field_citations(card, machine)
    pe._stamp_card_segment_provenance(card, package)

    after = pe._blocking_warnings(
        pe._research_card_contract_warnings(machine, card, package, require_source_package=True)
    )
    assert after == []


# ---------------------------------------------------------------------------
# action classifier: cheapest verb first
# ---------------------------------------------------------------------------

def test_classifier_picks_free_promote_for_select_miss():
    machine = _MACHINES["XB19"]
    actions = pe._classify_repair_actions(machine, _xb19_card(), _package_for("XB19"))
    assert actions, "select-miss card must produce a repair plan"
    first = actions[0]
    assert first["verb"] == "promote_excerpt"
    assert first["kind"] == "reality"
    assert first["excerpt_id"] in {"S3-E3", "S4-E1", "S4-E3"}
    # the free verb must outrank every paid one
    assert pe._REPAIR_VERB_EST_COST_USD[first["verb"]] == 0.0


def test_classifier_full_rerun_only_when_no_package():
    actions = pe._classify_repair_actions("Boeing XB-15", _xb19_card(), None)
    assert [a["verb"] for a in actions] == ["full_rerun"]


def test_classifier_empty_plan_for_passing_card():
    machine = _MACHINES["XB19"]
    package = _package_for("XB19")
    card = _xb19_card()
    candidate = pe._find_candidate_excerpt(package, "S3-E3")
    segment = pe._promoted_evidence_segment(candidate, "reality", machine, set())
    card["evidence_segments"].append(segment)
    card["actual_outcome"] = segment["claim"]
    card = pe._normalize_card_field_citations(card, machine)
    pe._stamp_card_segment_provenance(card, package)
    assert pe._classify_repair_actions(machine, card, package) == []


def test_classifier_cardless_machine_ends_in_full_rerun():
    actions = pe._classify_repair_actions(_MACHINES["XB19"], None, _package_for("XB19"))
    assert actions[-1]["verb"] == "full_rerun"
    assert all(a["verb"] in pe._REPAIR_VERB_EST_COST_USD for a in actions)


def test_repair_action_key_distinguishes_actions():
    a = {"verb": "promote_excerpt", "excerpt_id": "S3-E3", "kind": "reality"}
    b = {"verb": "promote_excerpt", "excerpt_id": "S4-E1", "kind": "reality"}
    assert pe._repair_action_key(a) != pe._repair_action_key(b)
    assert pe._repair_action_key(a) == pe._repair_action_key(dict(a))


# ---------------------------------------------------------------------------
# segment surgery plan (rekind_segments)
# ---------------------------------------------------------------------------

_CARD_B17 = _load_fixture("card_b17.json")


def test_surgery_plan_blocks_unbackfillable_beat_and_routes_to_fetch():
    machine = _MACHINES["B17"]
    package = _package_for("B17")
    card = copy.deepcopy(_CARD_B17["card"])
    plan = pe._segment_surgery_plan(card, package, machine)
    # the golden B-17 card's original_problem cites an excerpt hinted for a
    # different beat, and the package has no promotable replacement: the plan
    # must refuse the re-kind (never break required coverage) and report it
    blocked_roles = {b["role"] for b in plan["blocked"]}
    assert "original_problem" in blocked_roles
    assert all(r["new_kind"] != r["old_kind"] for r in plan["rekinds"])
    actions = pe._classify_repair_actions(machine, card, package)
    fetches = [a for a in actions if a["verb"] == "targeted_fetch"]
    assert any(a.get("focus") == "slot:original_problem" for a in fetches)


def test_surgery_plan_empty_for_passing_card():
    machine = _MACHINES["XB19"]
    package = _package_for("XB19")
    plan = pe._segment_surgery_plan(_xb19_card(), package, machine)
    assert plan["rekinds"] == [] and plan["promotes"] == []


# ---------------------------------------------------------------------------
# review-list merge + hold validation update
# ---------------------------------------------------------------------------

def test_merge_card_replaces_only_the_target():
    other = {"unit": "Boeing B-17", "marker": "keep"}
    stale = {"unit": "Douglas XB-19", "marker": "stale"}
    fresh = {"unit": "Douglas XB-19", "marker": "fresh"}
    merged = pe._merge_card_into_review_cards([other, stale], fresh, "Douglas XB-19")
    assert merged == [other, fresh]
    # missing target appends
    appended = pe._merge_card_into_review_cards([other], fresh, "Douglas XB-19")
    assert appended == [other, fresh]


def test_hold_validation_unit_verdict_update():
    payload = {
        "unit_research_hold_validation": {
            "passed": False,
            "units": [
                {"machine": "Boeing B-17", "passed": True, "warnings": []},
                {"machine": "Douglas XB-19", "passed": False, "warnings": ["old"]},
            ],
        }
    }
    updated = pe._hold_validation_with_unit_verdict(payload, "Douglas XB-19", [])
    assert updated["passed"] is True
    assert updated["target_machine_passed"] is True
    xb19 = [u for u in updated["units"] if u["machine"] == "Douglas XB-19"][0]
    assert xb19["passed"] is True and xb19["warnings"] == []
    # a failing verdict flips overall passed back off
    updated = pe._hold_validation_with_unit_verdict(payload, "Douglas XB-19", ["still bad"])
    assert updated["passed"] is False


# ---------------------------------------------------------------------------
# timeframe promotable rows mirror the prompt hints
# ---------------------------------------------------------------------------

def test_timeframe_promotable_rows_match_hints():
    machine = _MACHINES["XB19"]
    package = _package_for("XB19")
    card = _xb19_card()
    rows = pe._timeframe_promotable_excerpts(card, package)
    hints = pe._timeframe_repair_hints(card, package)
    assert len(rows) == len(hints)
    for row, hint in zip(rows, hints):
        assert row["excerpt_id"] in hint
        for key in row["covered"]:
            assert key in hint


# ---------------------------------------------------------------------------
# formatter shows enforced conversion-signal excerpts (the XB-15 trap fix)
# ---------------------------------------------------------------------------

def test_formatter_shows_enforced_conversion_signal_rows():
    machine = "Boeing XB-15"
    signal_row = {
        "excerpt_id": "S1-E1",
        "source_id": "S1",
        "source_title": "XB-15 history",
        "source_url": "https://example.org/xb15",
        "source_tier": 2,
        "source_tier_label": "Tier 2 museum/authoritative secondary",
        "source_capture_method": "fetched_page",
        "source_variant_selection": {"selected_capture_method": "fetched_page"},
        "locator": "S1-E1; query=test",
        "text": "The sole example was redesignated XC-105 and converted for cargo duties.",
        "text_hash": "hash1",
    }
    package = {
        "passed": True,
        "machine": machine,
        "machine_key": "XB15",
        "candidate_excerpts": [signal_row] + [
            {
                "excerpt_id": f"S2-E{i}",
                "source_id": "S2",
                "source_title": "XB-15 fact sheet",
                "source_url": "https://example.org/facts",
                "source_tier": 1,
                "source_tier_label": "Tier 1 primary/official",
                "source_capture_method": "fetched_page",
                "source_variant_selection": {"selected_capture_method": "fetched_page"},
                "locator": f"S2-E{i}; query=test",
                "text": f"The Boeing XB-15 was a large experimental bomber, detail {i}.",
                "text_hash": f"hash2{i}",
            }
            for i in range(1, 7)
        ],
        "sources": [],
    }
    signals = pe._package_conversion_signals(package, machine)
    assert any(s.get("enforce") and s.get("excerpt_id") == "S1-E1" for s in signals)
    formatted = pe._format_verified_machine_source_package(package, machine)
    # before the fix the cross-designation (XC-105) hid this row from the model
    # while the gap gate ordered the model to select it
    assert "S1-E1" in formatted
    assert "XC-105" in formatted
