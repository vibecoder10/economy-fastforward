"""Conformance + unit locks for the DVsU research-card referee.

Local/no-spend. Pins the exact verdicts of
`pipeline_executor._research_card_contract_warnings` on three real prod cards
(Boeing XB-15, Douglas XB-19, Boeing B-17), plus targeted unit tests on the
helpers it composes: the Anton slot-role map, the per-field Tier-4 gate, the
citation normalizer's idempotency, the spoken-word counter, and the
visual_identity / timeframe / engineering_thesis word minimums.

The three cleaned fixtures under tests/fixtures/ are the committed golden
inputs; the ordered warning lists below are the referee's current exact output
(pinned so any silent behavior change trips a test). conftest.py already puts
the backend root on sys.path, so `import pipeline_executor as pe` works with no
sys.path hack.
"""
import copy
import json
import os

import pipeline_executor as pe

# ---------------------------------------------------------------------------
# fixture loading
# ---------------------------------------------------------------------------
_FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_fixture(name):
    with open(os.path.join(_FIXTURES, name), encoding="utf-8") as fh:
        return json.load(fh)


# packages.json maps XB15/XB19/B17 -> package dict (already fully parsed, but
# tolerate a stray JSON-string value just in case).
_PACKAGES = _load_fixture("packages.json")


def _package_for(key):
    val = _PACKAGES[key]
    return json.loads(val) if isinstance(val, str) else val


# Each card fixture is the FULL DB row: row["card"] + row["machine_name"].
_CARD_XB15 = _load_fixture("card_xb15.json")
_CARD_XB19 = _load_fixture("card_xb19.json")
_CARD_B17 = _load_fixture("card_b17.json")

# fixture row, its package key -> used by the idempotency sweep.
_ALL_FIXTURES = (
    ("XB15", _CARD_XB15),
    ("XB19", _CARD_XB19),
    ("B17", _CARD_B17),
)


# ---------------------------------------------------------------------------
# (A) conformance: exact referee verdicts with require_source_package=True
# ---------------------------------------------------------------------------

# A clean real card: its timeframe + visual_identity words all appear in its
# evidence segments, so the referee returns an EMPTY warning list (passes).
_GOLDEN_XB19 = []

# Scope-change ruling: the timeframe words "flew"/"December" DO appear in an
# (uncited) evidence segment, so the old timeframe grounding warning is CLEARED.
# The visual_identity words and the number "four" appear in NO segment, so only
# those two visual_identity warnings remain.
_GOLDEN_XB15 = [
    "visual_identity contains detail(s) not grounded in evidence segments: mid, wing, monoplane, retractable, landing, gear",
    "visual_identity introduced unsupported numerical detail(s): four",
]

# Fails across multiple families: empty thesis, ungrounded visual/timeframe,
# bad segment kinds, and a slot-map mismatch.
_GOLDEN_B17 = [
    "missing/weak engineering_thesis",
    "visual_identity must be specific to the locked machine",
    "visual_identity contains detail(s) not grounded in evidence segments: engine, all, metal, construction",
    "visual_identity introduced unsupported numerical detail(s): four",
    "timeframe must be specific to the locked machine",
    "timeframe contains detail(s) not grounded in evidence segments: entered",
    "timeframe introduced unsupported numerical detail(s): 1937",
    "evidence segment B17-E2 has unsupported Anton slot kind: timeframe",
    "evidence segment B17-E4 has unsupported Anton slot kind: visual_identity",
    "evidence segment B17-E1 maps original_problem to raw excerpt S2-E3 hinted for engineering_decision",
]


def test_conformance_xb19_passes_clean():
    """Douglas XB-19: a clean real card -> zero warnings."""
    row = _CARD_XB19
    warnings = pe._research_card_contract_warnings(
        row["machine_name"], row["card"], _package_for("XB19"), require_source_package=True
    )
    assert warnings == _GOLDEN_XB19


def test_conformance_xb15_two_visual_identity_warnings():
    """Boeing XB-15: exactly the two visual_identity warnings, NO timeframe warning."""
    row = _CARD_XB15
    warnings = pe._research_card_contract_warnings(
        row["machine_name"], row["card"], _package_for("XB15"), require_source_package=True
    )
    assert warnings == _GOLDEN_XB15


def test_conformance_b17_fails_across_families():
    """Boeing B-17: fails across thesis / visual / timeframe / segment-kind / slot-map."""
    row = _CARD_B17
    warnings = pe._research_card_contract_warnings(
        row["machine_name"], row["card"], _package_for("B17"), require_source_package=True
    )
    assert warnings == _GOLDEN_B17


# ---------------------------------------------------------------------------
# (B) idempotency + read-only: referee twice == once; caller card unmutated
# ---------------------------------------------------------------------------

def test_referee_is_idempotent_on_normalized_card():
    """Grading a card, then grading its already-normalized form, is identical.

    The referee normalizes citations on an internal deep copy before grading,
    so running it on a pre-normalized card must yield the byte-identical
    verdict (the normalizer is idempotent)."""
    for key, row in _ALL_FIXTURES:
        machine = row["machine_name"]
        package = _package_for(key)
        first = pe._research_card_contract_warnings(
            machine, row["card"], package, require_source_package=True
        )
        norm = pe._normalize_card_field_citations(copy.deepcopy(row["card"]), machine)
        second = pe._research_card_contract_warnings(
            machine, norm, package, require_source_package=True
        )
        assert first == second, f"{key}: referee not idempotent on normalized card"


def test_referee_does_not_mutate_caller_card():
    """The referee is read-only: the caller's stored card is unchanged."""
    for key, row in _ALL_FIXTURES:
        card = row["card"]
        before = json.dumps(card, sort_keys=True)
        pe._research_card_contract_warnings(
            row["machine_name"], card, _package_for(key), require_source_package=True
        )
        after = json.dumps(card, sort_keys=True)
        assert before == after, f"{key}: referee mutated the caller's card"


# ---------------------------------------------------------------------------
# (C) unit match resolves from machine_name alone
# ---------------------------------------------------------------------------

def test_unit_match_resolves_from_machine_name_only():
    """A card with no unit/machine/name/designation but a machine_name still
    matches the locked machine (no unit-mismatch warning)."""
    card = copy.deepcopy(_CARD_XB15["card"])
    for key in ("unit", "machine", "name", "designation"):
        card.pop(key, None)
    card["machine_name"] = "Boeing XB-15"
    # Isolate the unit check: no package, so package-dependent warnings can't
    # confound the assertion.
    warnings = pe._research_card_contract_warnings(
        "Boeing XB-15", card, None, require_source_package=False
    )
    assert not any(
        "card unit does not match locked machine" in w for w in warnings
    ), warnings


# ---------------------------------------------------------------------------
# (D) memorable-kind coercion
# ---------------------------------------------------------------------------

def test_memorable_fact_kind_coercion():
    """surprising_fact and retention_fact both fold into the memorable_fact slot."""
    for kind in ("memorable_fact", "surprising_fact", "retention_fact"):
        assert pe._anton_slot_role_for_kind(kind) == "memorable_fact"


# ---------------------------------------------------------------------------
# (E) per-field Tier-4 gate operator (>= 4, only over resolvable tiers)
# ---------------------------------------------------------------------------
# NOTE on operators: the per-field gate below blocks when EVERY resolvable
# cited tier is >= 4. The separate selected-evidence gate inside
# _research_card_contract_warnings ("evidence_segments cite no Tier 1-2
# source") blocks only when every resolvable tier is > 2 -- a different
# threshold. That selected-evidence gate is NOT triggered for XB-19, which
# passes clean in test_conformance_xb19_passes_clean above.

def test_tier_gate_blocks_when_all_resolvable_tiers_are_4():
    evidence_by_id = {
        "e1": {"source_url": "http://x", "source_tier": 4},
        "e2": {"source_url": "http://y", "source_tier": 4},
    }
    assert pe._cited_evidence_tier_warning("visual_identity", ["e1", "e2"], evidence_by_id)


def test_tier_gate_passes_when_one_tier_is_below_4():
    # [3, 4] -> not ALL >= 4 -> does not block.
    evidence_by_id = {
        "e1": {"source_url": "http://x", "source_tier": 3},
        "e2": {"source_url": "http://y", "source_tier": 4},
    }
    assert pe._cited_evidence_tier_warning("visual_identity", ["e1", "e2"], evidence_by_id) == []


def test_tier_gate_ignores_unresolvable_ids():
    # e2 has no source_url so it is unresolvable and excluded; only e1 (tier 4)
    # counts -> the single resolvable tier is >= 4 -> blocks.
    evidence_by_id = {
        "e1": {"source_url": "http://x", "source_tier": 4},
        "e2": {"source_tier": 4},  # no source_url -> not resolvable
    }
    assert pe._cited_evidence_tier_warning("visual_identity", ["e1", "e2"], evidence_by_id)


def test_source_tier_number_resolves_explicit_tier():
    """Confirm how _source_tier_number reads the fixtures used above."""
    assert pe._source_tier_number({"source_url": "http://x", "source_tier": 4}) == 4
    assert pe._source_tier_number({"source_url": "http://x", "source_tier": 3}) == 3


# ---------------------------------------------------------------------------
# (F) word-count boundaries for the field minimums
# ---------------------------------------------------------------------------

def test_spoken_word_count_treats_designations_as_one_token():
    """B-52 and hyphenated tokens count as a single spoken word."""
    assert pe._spoken_word_count("B-52") == 1
    assert pe._spoken_word_count("top-secret") == 1


def test_timeframe_min_is_five_spoken_words():
    machine = "Boeing XB-15"
    # 4 spoken words -> early-return exactly the missing/weak timeframe warning.
    four = pe._timeframe_warnings(machine, "served during the war", [], [])
    assert four == ["missing/weak timeframe"]
    # 5 spoken words -> that gate passes (other warnings appear with evidence=[],
    # but the missing/weak string must be gone).
    five = pe._timeframe_warnings(machine, "served during World War Two", [], [])
    assert "missing/weak timeframe" not in five


def test_visual_identity_min_is_eight_spoken_words():
    machine = "Boeing XB-15"
    # 7 spoken words -> early-return exactly the missing/weak visual_identity warning.
    seven = pe._visual_identity_warnings(machine, "a big silver plane with four engines", [], [])
    assert seven == ["missing/weak visual_identity"]
    # 8 spoken words -> that gate passes; the missing/weak string must be gone.
    eight = pe._visual_identity_warnings(machine, "a big silver plane with four large engines", [], [])
    assert "missing/weak visual_identity" not in eight


# ---------------------------------------------------------------------------
# (G) engineering_thesis is graded by a 4-spoken-word minimum
# ---------------------------------------------------------------------------

def test_engineering_thesis_word_minimum():
    """Start from the passing XB-19 card and vary only the thesis length."""
    row = _CARD_XB19
    machine = row["machine_name"]
    package = _package_for("XB19")

    three_word = copy.deepcopy(row["card"])
    three_word["engineering_thesis"] = "Too short thesis"  # 3 spoken words
    warnings = pe._research_card_contract_warnings(
        machine, three_word, package, require_source_package=True
    )
    assert "missing/weak engineering_thesis" in warnings

    four_word = copy.deepcopy(row["card"])
    four_word["engineering_thesis"] = "A clear engineering thesis"  # 4 spoken words
    warnings = pe._research_card_contract_warnings(
        machine, four_word, package, require_source_package=True
    )
    assert "missing/weak engineering_thesis" not in warnings
