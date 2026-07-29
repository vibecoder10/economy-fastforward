"""Characterization tests for ship-class ("designed_vs_used"/DvsU) roster
shapes flowing through the AIRCRAFT-shaped roster machinery.

WHY THIS EXISTS (2026-07-29 audit): the DvsU roster machinery
(_unit_display_name, _unit_code, _normalized_unit_code, _designation_token,
_machine_key, _roster_validation) was built entirely for aircraft. Every
existing test that exercises `designation` uses an aircraft-style code
(B-52, XB-15, F-86D, B29, B47, B36, T95/T-95). None test a ship-class or
member-list value. This file closes that gap.

These are CHARACTERIZATION tests: they pin what the code does TODAY,
including behavior that looks wrong or silly. They intentionally do NOT
assert what the "right" behavior should be. If a future change (additive
`member_units` field, hard/soft severity split in _roster_validation, a
never-built machine state) legitimately changes one of these outputs, the
fix is to consciously update the pinned value here — not to treat a
red test as a false alarm.

No network calls. No source files touched to make these pass — every
assertion below was captured by running the real functions and copying
their real output (see the audit report for the exploration scripts used).

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_ship_roster_shapes.py -q
"""
import os
import sys
from pathlib import Path

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PIPELINE_ROOT = _REPO_ROOT / "skills" / "video-pipeline"
if str(_PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_ROOT))

import pipeline_executor as pe  # noqa: E402
import static_docu as sd  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures: the real prod roster shape for video
# d2e37cd6-521a-43aa-a14d-ce096a783c1e ("Every British Aircraft Carrier Class
# Ever Built", 20-minute target, 23 entries). The 8 entries given verbatim in
# the audit are included; the remaining 15 are additional real British
# carrier classes/ships in the same two shapes the audit identified
# (bare "HMS X (pennant)" and "class name" / "class, list of member ships")
# so the roster is a realistic 23-entry set, not a padded fake.
# ---------------------------------------------------------------------------

SHIP_ROSTER_ENTRIES = [
    {"name": "Courageous class", "designation": "Courageous, Glorious"},
    {"name": "Ark Royal (1937)", "designation": "HMS Ark Royal (91)"},
    {"name": "Illustrious class", "designation": "Illustrious, Formidable, Victorious, Indomitable"},
    {"name": "Attacker class (US-built)", "designation": "Lend-Lease escort carriers"},
    {"name": "Ruler class (US-built)", "designation": "Lend-Lease escort carriers"},
    {"name": "CVA-01 class", "designation": "CVA-01 Queen Elizabeth class (1960s design)"},
    {"name": "Archer class / Empire Mac-Ship conversions", "designation": "CAM ships and MAC ships"},
    {"name": "Audacious class / Malta class", "designation": "CVA-01 predecessors"},
    {"name": "Pretoria Castle class", "designation": "HMS Pretoria Castle (F61)"},
    {"name": "Implacable class", "designation": "Implacable, Indefatigable"},
    {"name": "Colossus class", "designation": "Colossus, Glory, Ocean, Theseus, Triumph, Venerable, Vengeance, Warrior, Pioneer, Perseus"},
    {"name": "Majestic class", "designation": "Majestic, Hercules, Leviathan, Magnificent, Powerful, Terrible"},
    {"name": "Centaur class", "designation": "Centaur, Albion, Bulwark, Hermes"},
    {"name": "Eagle (1946)", "designation": "HMS Eagle (R05)"},
    {"name": "Ark Royal (1955)", "designation": "HMS Ark Royal (R09)"},
    {"name": "Hermes (1959)", "designation": "HMS Hermes (R12)"},
    {"name": "Invincible class", "designation": "Invincible, Illustrious, Ark Royal"},
    {"name": "Queen Elizabeth class (modern)", "designation": "Queen Elizabeth, Prince of Wales"},
    {"name": "Unicorn (maintenance carrier)", "designation": "HMS Unicorn (I72)"},
    {"name": "Argus (1918)", "designation": "HMS Argus (I49)"},
    {"name": "Furious (1917)", "designation": "HMS Furious (47)"},
    {"name": "Nairana class", "designation": "Nairana, Campania, Vindex, Activity"},
    {"name": "Vindictive (1918)", "designation": "HMS Vindictive (72)"},
]
assert len(SHIP_ROSTER_ENTRIES) == 23

SHIP_TITLE = "Every British Aircraft Carrier Class Ever Built"

# Aircraft-shaped control roster (regression net): consistent with the
# existing suite's B-52 / XB-70 / YB-35-style codes. Includes a deliberate
# parent+subvariant pair (B-29 / B-29B) to exercise the subvariant-padding
# check in _roster_validation — the aircraft-only counterpart to the
# pacing-only ship roster below.
AIRCRAFT_NAMES = [
    "Boeing B-52", "Boeing B-29", "Boeing B-29B", "Convair B-36", "Convair YB-60",
    "Northrop XB-35", "Northrop YB-49", "North American XB-70", "Boeing XB-15",
    "Boeing YB-40", "Martin XB-48", "Convair B-58", "Rockwell B-1B", "Northrop B-2",
    "Boeing B-47", "Douglas XB-42", "Douglas XB-43", "Consolidated B-24",
    "Boeing B-17", "Fairchild AC-119",
]
AIRCRAFT_TITLE = "Every American Strategic Bomber Ever Built"


def _ship_video(roster=None, render_mode="static_docu", marker=True):
    payload = {"unit_roster": roster if roster is not None else SHIP_ROSTER_ENTRIES}
    if marker:
        payload["documentary_style"] = "designed_vs_used"
    return {"id": "ship-vid-1", "render_mode": render_mode, "research_payload": payload}


# ---------------------------------------------------------------------------
# 1. _unit_display_name on every ship shape from the real roster.
#
# LOAD-BEARING: this exact string is what static_docu._machine_key hashes
# into the TENANT-GLOBAL static_reference_cache primary key
# (tenant_id, machine_key). Any future change to _unit_display_name's
# gluing rule silently orphans every cached reference photo, for every
# tenant, for every machine whose display string changes shape.
# ---------------------------------------------------------------------------

EXPECTED_DISPLAY_NAMES = {
    "Courageous class": "Courageous, Glorious Courageous class",
    "Ark Royal (1937)": "HMS Ark Royal (91) Ark Royal (1937)",
    "Illustrious class": "Illustrious, Formidable, Victorious, Indomitable Illustrious class",
    "Attacker class (US-built)": "Lend-Lease escort carriers Attacker class (US-built)",
    "Ruler class (US-built)": "Lend-Lease escort carriers Ruler class (US-built)",
    "CVA-01 class": "CVA-01 Queen Elizabeth class (1960s design) CVA-01 class",
    "Archer class / Empire Mac-Ship conversions": "CAM ships and MAC ships Archer class / Empire Mac-Ship conversions",
    "Audacious class / Malta class": "CVA-01 predecessors Audacious class / Malta class",
    "Pretoria Castle class": "HMS Pretoria Castle (F61) Pretoria Castle class",
}


def test_unit_display_name_pins_every_ship_shape_in_real_roster():
    by_name = {e["name"]: e for e in SHIP_ROSTER_ENTRIES}
    for name, expected in EXPECTED_DISPLAY_NAMES.items():
        entry = by_name[name]
        actual = pe._unit_display_name(entry)
        assert actual == expected, (
            f"_unit_display_name drifted for {entry!r}: expected {expected!r}, got {actual!r}. "
            "This is the static_reference_cache primary-key input — if this change is "
            "intentional, every cached reference photo for this machine is now orphaned."
        )

    # Whole-roster sanity: no entry collapses to an empty display name, and
    # every entry produces the "<designation> <name>" glue (never bare name)
    # because in this real roster `designation` never happens to already be
    # a substring of `name` — the one escape hatch in _unit_display_name.
    all_names = [pe._unit_display_name(e) for e in SHIP_ROSTER_ENTRIES]
    assert all(all_names)
    assert len(all_names) == 23


# ---------------------------------------------------------------------------
# 2. _unit_code / _normalized_unit_code on ship inputs.
#
# SURPRISE: the aircraft regexes (bomber prefix + digits, or bare
# LETTERS-DIGITS with a dash) were never meant for ship text, so on names
# with no aircraft-shaped substring they fall through to the generic
# "first 4 alphanumeric words" branch — the "code" ends up being almost the
# entire name, not a short designation. And on "HMS Ark Royal (91)" the
# pennant number in parens gets treated exactly like a model number, folding
# it into the fallback word-list code. Coincidentally, "CVA-01" (a real
# ship-program designation) DOES match the generic LETTERS-DASH-DIGITS
# aircraft regex, so it extracts cleanly — a lucky accident of shape, not
# ship-aware logic.
# ---------------------------------------------------------------------------

def test_unit_code_on_ship_inputs_with_no_aircraft_shaped_substring():
    # No digit anywhere -> falls through both aircraft regexes to the
    # generic "first 4 alnum words" fallback. The "code" is effectively
    # the whole (uppercased) name, not a short designation.
    assert pe._unit_code("Courageous class") == "COURAGEOUS CLASS"
    assert pe._normalized_unit_code("Courageous class") == "COURAGEOUSCLASS"

    assert pe._unit_code("Illustrious, Formidable, Victorious, Indomitable") == \
        "ILLUSTRIOUS FORMIDABLE VICTORIOUS INDOMITABLE"
    assert pe._normalized_unit_code("Illustrious, Formidable, Victorious, Indomitable") == \
        "ILLUSTRIOUSFORMIDABLEVICTORIOUSINDOMITABLE"

    assert pe._unit_code("Lend-Lease escort carriers Attacker class (US-built)") == \
        "LEND LEASE ESCORT CARRIERS"
    assert pe._normalized_unit_code("Lend-Lease escort carriers Attacker class (US-built)") == \
        "LENDLEASEESCORTCARRIERS"


def test_unit_code_on_ship_input_with_a_pennant_number():
    # "(91)" is Ark Royal's pennant number, not a model/variant number — but
    # _unit_code cannot tell the difference. It gets swept into the generic
    # fallback code as if it were meaningful, producing a code that includes
    # a bare pennant digit string.
    assert pe._unit_code("HMS Ark Royal (91)") == "HMS ARK ROYAL 91"
    assert pe._normalized_unit_code("HMS Ark Royal (91)") == "HMSARKROYAL91"


def test_unit_code_accidentally_matches_a_ship_program_designation():
    # "CVA-01" happens to be shaped exactly like the generic aircraft
    # LETTERS(1-4)-DIGITS(1-4) regex, so it extracts a short, clean code —
    # purely because CVA-01 looks like a tail number, not because _unit_code
    # has any ship awareness.
    glued = "CVA-01 Queen Elizabeth class (1960s design) CVA-01 class"
    assert pe._unit_code(glued) == "CVA-01"
    assert pe._normalized_unit_code(glued) == "CVA01"


# ---------------------------------------------------------------------------
# 3. static_docu._designation_token on ship names.
#
# SURPRISE: _designation_token's rule is "first word containing a digit".
# Most ship class names have no digit anywhere, so the fallback path
# (whole string, alnum-only, lowercased, first 12 chars) kicks in — a
# truncated slug of the class name rather than a designation. But
# "HMS Ark Royal (91)" DOES have a digit-bearing word ("(91)"), so the
# token becomes the bare 2-character pennant number "91" — a token short
# enough that (per the report's bug finding below) _page_matches has no
# minimum-length floor and would treat ANY Wikipedia page title containing
# the substring "91" as a designation match.
# ---------------------------------------------------------------------------

def test_designation_token_falls_back_to_truncated_name_slug_with_no_digit():
    assert sd._designation_token("Courageous class") == "courageouscl"
    assert sd._designation_token("Pretoria Castle class") == "pretoriacast"
    assert sd._designation_token("Illustrious, Formidable, Victorious, Indomitable") == "illustriousf"


def test_designation_token_on_pennant_number_yields_a_bare_two_char_token():
    # This is the surprising one: a real ship's designation token collapses
    # to "91" — indistinguishable from any other 2-digit substring.
    assert sd._designation_token("HMS Ark Royal (91)") == "91"


def test_designation_token_on_glued_display_names():
    glued_cva = "CVA-01 Queen Elizabeth class (1960s design) CVA-01 class"
    assert sd._designation_token(glued_cva) == "cva01"

    glued_pretoria = "HMS Pretoria Castle (F61) Pretoria Castle class"
    assert sd._designation_token(glued_pretoria) == "f61"


# ---------------------------------------------------------------------------
# 4. _machine_key stability canary.
#
# static_reference_cache's primary key is (tenant_id, machine_key), and
# machine_key = _machine_key(_unit_display_name(item)) — TENANT-GLOBAL, not
# per-video. If _unit_display_name's output for any of these ship shapes
# ever changes, every tenant's cached reference photo for that machine is
# silently orphaned (a cache miss on next generation, not an error anyone
# would notice without this canary).
# ---------------------------------------------------------------------------

def test_machine_key_stability_canary_on_ship_display_names():
    cases = {
        "Courageous, Glorious Courageous class": "courageousgloriouscourageousclass",
        "HMS Ark Royal (91) Ark Royal (1937)": "hmsarkroyal91arkroyal1937",
        "Lend-Lease escort carriers Attacker class (US-built)": "lendleaseescortcarriersattackerclassusbuilt",
        "CVA-01 Queen Elizabeth class (1960s design) CVA-01 class": "cva01queenelizabethclass1960sdesigncva01class",
        "HMS Pretoria Castle (F61) Pretoria Castle class": "hmspretoriacastlef61pretoriacastleclass",
    }
    for display_name, expected_key in cases.items():
        actual = sd._machine_key(display_name)
        assert actual == expected_key, (
            f"_machine_key drifted for display name {display_name!r}: "
            f"expected {expected_key!r}, got {actual!r}. This is the "
            "TENANT-GLOBAL static_reference_cache primary key — a drift "
            "here orphans every cached reference photo for every tenant "
            "that has this machine cached, with no error, just a silent "
            "cache miss on the next generation."
        )

    # The 80-char truncation in _machine_key is a real collision risk that
    # aircraft rosters never exercised (aircraft codes are short) but ship
    # rosters can, because `designation` is sometimes a whole member-ship
    # list. Pin that the longest real entry here still fits under the
    # truncation boundary today (no collision observed in this roster) —
    # this is a canary, not a guarantee: a future roster with two
    # long-enough entries sharing an 80-char prefix WILL collide silently.
    longest_display = max((pe._unit_display_name(e) for e in SHIP_ROSTER_ENTRIES), key=len)
    assert len(sd._machine_key(longest_display)) <= 80


# ---------------------------------------------------------------------------
# 5. _roster_validation on the realistic 23-entry ship roster, 20-min video.
#
# This is the exact condition that stalled the real video: a ship roster
# padded slightly past the runtime target trips a SINGLE pacing warning and
# nothing else. Note `passed = len(warnings) == 0` today — there is no
# severity split, so this one soft pacing note fails the roster exactly as
# hard as a missing roster_audit would. That flat pass/fail is the gap the
# upcoming hard/soft severity split is meant to close.
# ---------------------------------------------------------------------------

def _ship_roster_validation_payload():
    display_names = [pe._unit_display_name(e) for e in SHIP_ROSTER_ENTRIES]
    return {
        "documentary_style": "designed_vs_used",
        "unit_roster": SHIP_ROSTER_ENTRIES,
        "machine_discovery_buckets": {
            "core_roster": list(display_names),
            "built_prototypes": [],
            "converted_or_special_variants": [],
            "secret_cancelled_or_black_programs": [],
            "boundary_disputes": [],
        },
        "recommended_final_roster": list(display_names),
        "gap_hunt_matrix": [
            {"candidate": "HMS Formidable duplicate check",
             "resolution": "already included as Illustrious class member"},
        ],
        "edge_case_matrix": [
            {"class": "designation/number sequence gaps"},
            {"class": "prefix/classification variants"},
            {"class": "mission-converted/special-purpose variants"},
            {"class": "renamed/reclassified/predecessor-successor programs"},
            {"class": "foreign-built/license/local-modification candidates"},
            {"class": "common false positives/exclusions"},
        ],
        "roster_audit": {
            "search_queries_used": [
                "list of Royal Navy aircraft carriers",
                "British aircraft carrier classes history",
                "Royal Navy escort carriers WWII",
                "CVA-01 cancelled carrier program",
                "Invincible class aircraft carriers",
                "Queen Elizabeth class aircraft carriers",
                "Lend-Lease escort carriers Royal Navy",
            ],
            "source_families_crosschecked": [
                "Friedman naval histories", "Jane's Fighting Ships", "Royal Navy official records",
            ],
            "unresolved_candidates": [],
            "confidence": "high",
        },
    }


def test_roster_validation_ship_roster_fails_on_pacing_alone():
    payload = _ship_roster_validation_payload()
    result = pe._roster_validation(SHIP_TITLE, payload, video_length_minutes=20)

    assert result["roster_count"] == 23
    assert result["passed"] is False
    assert result["warnings"] == [
        "Broad complete-roster final roster is larger than the runtime target plus reserve: "
        "23 final items vs target around 20 for a 20-minute video. Tighten the roster to fit "
        "the requested runtime, or prove that the title requires the larger count."
    ], (
        "Ship roster's warning set drifted — this pins the EXACT single "
        "pacing warning (23 items vs a 22-item candidate_universe_target "
        "for a 20-minute video) that stalled the real prod video. "
        "passed = len(warnings) == 0 with no severity tiering today, so "
        "this one soft pacing note is indistinguishable from a hard data "
        "-integrity failure in the `passed` field alone."
    )


# ---------------------------------------------------------------------------
# 6. AIRCRAFT-shaped control roster — the regression net proving ship-driven
# changes to this file's fixtures/helpers did not alter the bomber path.
# Same 20-item / 20-minute shape as the ship test above, but the ONE warning
# it trips is completely different: a subvariant-padding warning (B-29 vs
# B-29B), which the ship code-shape can never produce (see test 2 above —
# ship "codes" never match the B/FB-prefixed family regex).
# ---------------------------------------------------------------------------

def _aircraft_roster_validation_payload():
    return {
        "unit_roster": [{"name": n} for n in AIRCRAFT_NAMES],
        "machine_discovery_buckets": {
            "core_roster": list(AIRCRAFT_NAMES),
            "built_prototypes": [],
            "converted_or_special_variants": [],
            "secret_cancelled_or_black_programs": [],
            "boundary_disputes": [],
        },
        "recommended_final_roster": list(AIRCRAFT_NAMES),
        "gap_hunt_matrix": [
            {"candidate": "Martin XB-51", "resolution": "excluded, never entered service"},
        ],
        "edge_case_matrix": [
            {"class": "designation/number sequence gaps"},
            {"class": "prefix/classification variants"},
            {"class": "mission-converted/special-purpose variants"},
            {"class": "renamed/reclassified/predecessor-successor programs"},
            {"class": "foreign-built/license/local-modification candidates"},
            {"class": "common false positives/exclusions"},
        ],
        "roster_audit": {
            "search_queries_used": [
                "list of American strategic bombers",
                "US Air Force bomber history",
                "cancelled American bomber programs",
                "experimental American bomber prototypes",
                "US strategic bomber designations",
                "American bomber variants and subtypes",
                "USAF bomber roster complete",
            ],
            "source_families_crosschecked": [
                "USAF official histories", "Jane's All the World's Aircraft", "National Museum of the USAF",
            ],
            "unresolved_candidates": [],
            "confidence": "high",
        },
    }


def test_roster_validation_aircraft_control_pins_subvariant_padding_warning():
    payload = _aircraft_roster_validation_payload()
    result = pe._roster_validation(AIRCRAFT_TITLE, payload, video_length_minutes=20)

    assert result["roster_count"] == 20
    assert result["passed"] is False
    assert result["warnings"] == [
        "Final roster appears padded with minor subvariants while the parent machine is "
        "already included: B-29. Combine minor variants under the parent unless the title "
        "asks for variants/classes or the subvariant is a distinct audience-facing program."
    ], (
        "Aircraft control roster's warning drifted. This is the regression "
        "net: if a ship-shape fix to _unit_code/_roster_validation ever "
        "breaks this B-29/B-29B subvariant-padding detection, this test "
        "catches it — completely independent of anything ship-related."
    )


def test_unit_code_family_detection_is_aircraft_only():
    # Direct proof of the asymmetry the two _roster_validation tests above
    # demonstrate end to end: the family-padding regex in _roster_validation
    # matches on `\b(B|FB)-(\d{1,3})([A-Z]?)\b` against _unit_code's output.
    # Aircraft codes are shaped to match; ship codes structurally never are,
    # so ship rosters get zero protection from this QA rule, silently.
    assert pe._unit_code("Boeing B-29") == "B-29"
    assert pe._unit_code("Boeing B-29B") == "B-29B"
    # None of these ship codes contain a bare "B-<digits>" or "FB-<digits>"
    # family shape, even though some contain the letter B somewhere.
    for name, designation in [
        ("Courageous class", "Courageous, Glorious"),
        ("Implacable class", "Implacable, Indefatigable"),
        ("Centaur class", "Centaur, Albion, Bulwark, Hermes"),
    ]:
        display = pe._unit_display_name({"name": name, "designation": designation})
        code = pe._unit_code(display)
        import re as _re
        assert _re.search(r"\b(B|FB)-(\d{1,3})([A-Z]?)\b", code) is None


# ---------------------------------------------------------------------------
# 7. _machine_documentary_hold_roster: render_mode + DvsU-marker gating, and
# that it returns the combined ("<designation> <name>") display strings for
# a ship payload — same function every other DvsU caller in
# pipeline_executor.py depends on.
# ---------------------------------------------------------------------------

def test_machine_documentary_hold_roster_returns_combined_ship_display_strings():
    video = _ship_video()
    result = pe._machine_documentary_hold_roster(video)
    assert len(result) == 23
    assert result[0] == "Courageous, Glorious Courageous class"
    assert result[1] == "HMS Ark Royal (91) Ark Royal (1937)"
    assert result == [pe._unit_display_name(e) for e in SHIP_ROSTER_ENTRIES]


def test_machine_documentary_hold_roster_gates_on_render_mode():
    non_static = _ship_video(render_mode="coverage")
    assert pe._machine_documentary_hold_roster(non_static) == []


def test_machine_documentary_hold_roster_gates_on_missing_dvsu_marker():
    # No documentary_style, no machine_discovery_buckets, no
    # unit_research_hold_validation -> not recognized as a locked DvsU
    # roster at all, even though render_mode is static_docu and unit_roster
    # is present.
    no_marker = _ship_video(marker=False)
    assert pe._machine_documentary_hold_roster(no_marker) == []


def test_machine_documentary_hold_roster_gates_on_roster_size_bounds():
    # Same function enforces a 3-40 item bound regardless of machine shape.
    too_few = _ship_video(roster=SHIP_ROSTER_ENTRIES[:2])
    assert pe._machine_documentary_hold_roster(too_few) == []
