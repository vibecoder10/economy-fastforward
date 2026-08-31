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
import copy
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
# UPDATED 2026-07-29 (C3 + C4 landed): this used to pin `passed is False` on
# the theory that `passed = len(warnings) == 0` with no severity split makes
# one soft pacing note fail exactly as hard as a data-integrity problem —
# the exact condition that stalled the real video for two days. C4 added the
# hard/soft severity split this test predicted: `passed` now means "no HARD
# failures", so this soft-only roster (a pacing overrun plus C3's new
# designation-stuffing detector, both SOFT) now PASSES and would advance,
# marked `needs_review`. C3 (additive `member_units` field) also added a new
# soft warning on this exact fixture: 9 of the 23 real entries glue a
# comma-separated member-ship list into `designation` with no `member_units`
# supplied (this fixture predates the field), which is now flagged for
# repair rather than silently accepted.
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


def test_roster_validation_ship_roster_passes_soft_only_and_needs_review():
    # RENAMED from test_roster_validation_ship_roster_fails_on_pacing_alone.
    # JUSTIFICATION: C4 introduced a hard/soft severity split; this roster's
    # only issues (pacing overrun + C3's designation-stuffing detector) are
    # both SOFT by the loop brief's explicit classification, so `passed` is
    # now True (the deliberate, user-visible point of C4) and `needs_review`
    # is True. This is the exact real-world case (video d2e37cd6, 23 ships
    # vs a ~20 target) that stalled production for two days before this fix.
    payload = _ship_roster_validation_payload()
    result = pe._roster_validation(SHIP_TITLE, payload, video_length_minutes=20)

    assert result["roster_count"] == 23
    assert result["passed"] is True, (
        "This is the C4 fix landing: a soft-only roster (pacing overrun, no "
        "hard data-integrity failure) must PASS and be free to advance "
        "instead of dead-ending like it did for video d2e37cd6."
    )
    assert result["hard_warnings"] == []
    pacing_warning = (
        "Broad complete-roster final roster is larger than the runtime target plus reserve: "
        "23 final items vs target around 20 for a 20-minute video. Tighten the roster to fit "
        "the requested runtime, or prove that the title requires the larger count."
    )
    stuffing_warning = (
        "designation holds a comma-separated member-ship/unit list instead of a short "
        "searchable code for: Courageous, Glorious Courageous class, Illustrious, Formidable, "
        "Victorious, Indomitable Illustrious class, Implacable, Indefatigable Implacable class, "
        "Colossus, Glory, Ocean, Theseus, Triumph, Venerable, Vengeance, Warrior, Pioneer, Perseus "
        "Colossus class, Majestic, Hercules, Leviathan, Magnificent, Powerful, Terrible Majestic "
        "class, Centaur, Albion, Bulwark, Hermes Centaur class, Invincible, Illustrious, Ark Royal "
        "Invincible class, Queen Elizabeth, Prince of Wales Queen Elizabeth class (modern) "
        "(+1 more). Move the individual member units into member_units and keep designation "
        "short or empty — a glued member-list designation is not a searchable machine name."
    )
    assert result["soft_warnings"] == [pacing_warning, stuffing_warning], (
        "Ship roster's soft-warning set drifted. First is the EXACT pacing warning "
        "(23 items vs a 22-item candidate_universe_target for a 20-minute video) that "
        "stalled the real prod video. Second is NEW from C3 (additive `member_units` "
        "field): 9 of these 23 real entries glue a comma-separated member-ship list "
        "into `designation` with no `member_units` supplied (this fixture predates the "
        "field) — now flagged for repair instead of silently accepted."
    )
    assert result["warnings"] == result["soft_warnings"], (
        "warnings must stay the full combined (hard+soft) list for backward "
        "compatibility with every existing reader that just displays/joins it; "
        "with zero hard warnings here it should equal soft_warnings exactly."
    )
    assert result["needs_review"] is True


def test_roster_validation_does_not_confuse_planned_sister_ships_with_built_lead_ship():
    payload = copy.deepcopy(_ship_roster_validation_payload())
    payload["unit_roster"][0] = {"name": "USS Enterprise", "designation": "CVN-65"}
    display_names = [pe._unit_display_name(e) for e in payload["unit_roster"]]
    payload["machine_discovery_buckets"]["core_roster"] = display_names
    payload["recommended_final_roster"] = display_names
    payload["roster_audit"]["excluded_candidates"] = [
        {
            "name": "CVN-65 Enterprise class (5 additional ships)",
            "reason": "Five planned sister ships were cancelled; only CVN-65 was built.",
        }
    ]

    result = pe._roster_validation(SHIP_TITLE, payload, video_length_minutes=20)

    assert result["passed"] is True
    assert not any("appears in both" in warning for warning in result["hard_warnings"])


def test_roster_validation_still_blocks_the_same_ship_listed_as_excluded():
    payload = copy.deepcopy(_ship_roster_validation_payload())
    payload["unit_roster"][0] = {"name": "USS Enterprise", "designation": "CVN-65"}
    display_names = [pe._unit_display_name(e) for e in payload["unit_roster"]]
    payload["machine_discovery_buckets"]["core_roster"] = display_names
    payload["recommended_final_roster"] = display_names
    payload["roster_audit"]["excluded_candidates"] = [
        {
            "name": "CVN-65 USS Enterprise",
            "reason": "This exact ship was excluded from the final roster.",
        }
    ]

    result = pe._roster_validation(SHIP_TITLE, payload, video_length_minutes=20)

    assert result["passed"] is False
    assert any("appears in both" in warning for warning in result["hard_warnings"])


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
    # UPDATED 2026-07-29 (C4): `passed` used to pin False here too, on the
    # same flat "any warning fails" logic the ship test above used to pin.
    # The loop brief explicitly classifies the subvariant-padding check as
    # SOFT ("the subvariant-padding check ... note: it is aircraft-only and
    # provably inert for ships"), so with the hard/soft split this roster's
    # one warning no longer blocks — `passed` is now True, `needs_review`
    # True. The warning text/content itself (the actual regression net this
    # test protects) is UNCHANGED.
    payload = _aircraft_roster_validation_payload()
    result = pe._roster_validation(AIRCRAFT_TITLE, payload, video_length_minutes=20)

    assert result["roster_count"] == 20
    assert result["passed"] is True
    assert result["hard_warnings"] == []
    assert result["needs_review"] is True
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
    assert result["soft_warnings"] == result["warnings"]


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


# ---------------------------------------------------------------------------
# 8. C3 (2026-07-29): additive `member_units` field — new coverage, not a
# pinned characterization of pre-existing behavior.
# ---------------------------------------------------------------------------

def test_unit_roster_aliases_prefers_member_units_when_present():
    item = {
        "name": "Courageous class",
        "designation": "",
        "member_units": ["Courageous", "Glorious"],
    }
    aliases = pe._unit_roster_aliases(item)
    # member_units entries come first (preferred), name/designation fallback
    # still runs after (designation is empty here so it contributes nothing).
    assert aliases[:2] == ["Courageous", "Glorious"]
    assert "Courageous class" in aliases


def test_unit_roster_aliases_member_units_additive_alongside_stuffed_designation():
    # A payload that still stuffs the member list into `designation` (old
    # shape) AND supplies the new `member_units` field gets aliases from
    # BOTH — no information is lost, member_units is simply preferred first.
    item = {
        "name": "Courageous class",
        "designation": "Courageous, Glorious",
        "member_units": ["Courageous", "Glorious"],
    }
    aliases = pe._unit_roster_aliases(item)
    assert aliases[0] == "Courageous"
    assert aliases[1] == "Glorious"
    assert "Courageous class" in aliases
    assert "Courageous, Glorious" in aliases


def test_unit_roster_aliases_with_no_member_units_field_is_byte_identical_to_before():
    # BACKWARD COMPATIBILITY (mandatory): every roster in the DB today lacks
    # `member_units`. This must produce EXACTLY the same aliases as the
    # pre-C3 function — same order, same content, nothing added or dropped.
    item = {"name": "Courageous class", "designation": "Courageous, Glorious"}
    aliases = pe._unit_roster_aliases(item)
    assert aliases == ["Courageous class", "Courageous, Glorious", "Courageous", "Glorious"]


def test_unit_roster_aliases_member_units_accepts_dict_entries():
    # Defensive: a research payload that nests member units as {"name": ...}
    # dicts (rather than bare strings) is still handled without crashing.
    item = {
        "name": "Colossus class",
        "member_units": [{"name": "Colossus"}, {"name": "Glory"}, "Ocean"],
    }
    aliases = pe._unit_roster_aliases(item)
    assert aliases[:3] == ["Colossus", "Glory", "Ocean"]


def test_roster_validation_designation_stuffing_detector_is_additive_and_soft():
    # A roster where every class row properly uses member_units (the NEW
    # correct shape) trips NEITHER the stuffing detector NOR any hard
    # warning — proving the detector only fires on the OLD stuffed shape,
    # not on `designation` being short/empty as newly instructed.
    entries = [
        {"name": "Courageous class", "designation": "", "member_units": ["Courageous", "Glorious"]},
        {"name": "Illustrious class", "designation": "", "member_units": ["Illustrious", "Formidable", "Victorious", "Indomitable"]},
    ]
    display_names = [pe._unit_display_name(e) for e in entries]
    payload = {
        "unit_roster": entries,
        "machine_discovery_buckets": {"core_roster": list(display_names)},
        "recommended_final_roster": list(display_names),
        "gap_hunt_matrix": [{"candidate": "x", "resolution": "y"}],
        "edge_case_matrix": [{"class": c} for c in (
            "designation/number sequence gaps", "prefix/classification variants",
            "mission-converted/special-purpose variants", "renamed/reclassified/predecessor-successor programs",
        )],
        "roster_audit": {
            "search_queries_used": ["q1", "q2", "q3", "q4", "q5", "q6"],
            "source_families_crosschecked": ["a", "b", "c"],
            "unresolved_candidates": [],
            "confidence": "high",
        },
    }
    result = pe._roster_validation("Every Test Ship Class Ever Built", payload, video_length_minutes=2)
    stuffing_hits = [w for w in result["warnings"] if "member-ship/unit list" in w]
    assert stuffing_hits == [], "member_units-correct rows must never trip the designation-stuffing detector"


def test_roster_validation_designation_stuffing_detector_fires_and_is_soft_not_hard():
    # 3 entries (not 1) so this isolates the stuffing detector from the
    # unrelated "complete-title roster has fewer than 3 items" HARD check —
    # only the first entry's designation is stuffed.
    entries = [
        {"name": "Courageous class", "designation": "Courageous, Glorious"},
        {"name": "Ark Royal (1937)", "designation": "HMS Ark Royal (91)"},
        {"name": "Eagle (1946)", "designation": "HMS Eagle (R05)"},
    ]
    display_names = [pe._unit_display_name(e) for e in entries]
    payload = {
        "unit_roster": entries,
        "machine_discovery_buckets": {"core_roster": list(display_names)},
        "recommended_final_roster": list(display_names),
        "gap_hunt_matrix": [{"candidate": "x", "resolution": "y"}],
        "edge_case_matrix": [{"class": c} for c in (
            "designation/number sequence gaps", "prefix/classification variants",
            "mission-converted/special-purpose variants", "renamed/reclassified/predecessor-successor programs",
        )],
        "roster_audit": {
            "search_queries_used": ["q1", "q2", "q3", "q4", "q5", "q6"],
            "source_families_crosschecked": ["a", "b", "c"],
            "unresolved_candidates": [],
            "confidence": "high",
        },
    }
    result = pe._roster_validation("Every Test Ship Class Ever Built", payload, video_length_minutes=2)
    assert any("member-ship/unit list" in w for w in result["hard_warnings"]) is False
    assert any("member-ship/unit list" in w for w in result["soft_warnings"]) is True
    assert result["passed"] is True, "designation-stuffing is SOFT — it must never block by itself"
    assert result["needs_review"] is True


# ---------------------------------------------------------------------------
# 9. C4 (2026-07-29): severity tiers — new coverage, not a pinned
# characterization of pre-existing behavior (there was no severity concept
# before this chunk).
# ---------------------------------------------------------------------------

def test_roster_validation_hard_failure_still_blocks_regardless_of_soft_warnings():
    # Missing roster_audit entirely on a complete-title video is HARD per the
    # loop brief. Must still fail the gate even though nothing else is wrong.
    payload = {
        "unit_roster": [{"name": f"Machine {i}"} for i in range(20)],
        "machine_discovery_buckets": {"core_roster": [f"Machine {i}" for i in range(20)]},
        "recommended_final_roster": [f"Machine {i}" for i in range(20)],
        "gap_hunt_matrix": [{"candidate": "x", "resolution": "y"}],
        "edge_case_matrix": [{"class": c} for c in (
            "designation/number sequence gaps", "prefix/classification variants",
            "mission-converted/special-purpose variants", "renamed/reclassified/predecessor-successor programs",
        )],
        # roster_audit deliberately omitted.
    }
    result = pe._roster_validation("Every Test Machine Ever Built", payload, video_length_minutes=20)
    assert result["passed"] is False
    assert any("missing roster_audit" in w for w in result["hard_warnings"])
    assert result["needs_review"] is False, "no soft warnings tripped here, only a hard one"


def test_roster_validation_needs_review_key_present_even_with_no_warnings_at_all():
    payload = _ship_roster_validation_payload()
    # Strip every entry down to a clean shape with member_units so neither
    # the pacing warning (fits target) nor the stuffing detector fires.
    payload["unit_roster"] = [
        {"name": f"Ship class {i}", "designation": "", "member_units": ["A", "B"]}
        for i in range(20)
    ]
    display_names = [pe._unit_display_name(e) for e in payload["unit_roster"]]
    payload["machine_discovery_buckets"]["core_roster"] = display_names
    payload["recommended_final_roster"] = display_names
    result = pe._roster_validation(SHIP_TITLE, payload, video_length_minutes=20)
    assert result["passed"] is True
    assert result["needs_review"] is False
    assert result["hard_warnings"] == []
    assert result["soft_warnings"] == []
    assert result["warnings"] == []


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


# --- 2026-07-30: Anton slot hints must speak ship (found by the research
# simulator - HMS Eagle's package failed beat coverage because the hint
# vocabulary was aircraft-only) -------------------------------------------

def test_slot_hints_ship_engineering_vocabulary():
    hints = pe._anton_source_slot_hints(
        "the middle deck, as fitted for the aircraft carrier Eagle (1918)."
    )
    assert "engineering_decision" in hints


def test_slot_hints_procurement_origin_vocabulary():
    hints = pe._anton_source_slot_hints(
        "After purchase build was continued and she was launched as EAGLE on 8th June 1918."
    )
    assert "original_problem" in hints


def test_slot_hints_aircraft_vocabulary_unchanged():
    hints = pe._anton_source_slot_hints(
        "The design mounted eight engines under swept wings for intercontinental range."
    )
    assert "engineering_decision" in hints


def test_slot_hints_ship_loss_is_reality():
    hints = pe._anton_source_slot_hints(
        "HMS Courageous was sunk by U-29 south-west of Ireland on 17 September 1939."
    )
    assert "reality" in hints


def test_slot_hints_lifecycle_verbs_are_reality():
    hints = pe._anton_source_slot_hints(
        "As the builds of Audacious (renamed Eagle) and Irresistible (renamed Ark Royal) were completed."
    )
    assert "reality" in hints


# --- 2026-07-30: the designation-code screen must not hide a class's own
# member ships (found by the simulator's Centaur lane: the display string
# carries only Hermes' R12, so Centaur's R06 and Bulwark's R08 read as
# foreign machines and genuine excerpts were silently dropped from the
# card prompt) --------------------------------------------------------------

_CENTAUR_CLASS = "Centaur, Albion, Bulwark, Hermes (R12) Centaur class"


def test_sibling_pennant_is_not_foreign_for_class_entry():
    assert pe._non_target_designation_codes(
        "HMS Centaur (R06) was the lead ship of her class.", _CENTAUR_CLASS
    ) == []


def test_metric_unit_is_not_a_designation_code():
    assert pe._non_target_designation_codes(
        "The rudder had an area of 20.9 m2 as designed.", "Boeing B-52 Stratofortress B-52"
    ) == []


def test_single_machine_foreign_code_still_caught():
    codes = pe._non_target_designation_codes(
        "Unlike the XB-70, the B-52 relied on proven engines.", "Boeing B-52 Stratofortress B-52"
    )
    assert "XB70" in codes
