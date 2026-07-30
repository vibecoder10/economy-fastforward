"""Tests for chunk C5 (2026-07-29): never-built roster detection.

WHY THIS EXISTS: some static-docu roster entries are cancelled programs or
paper projects that were NEVER PHYSICALLY COMPLETED — no photograph can
ever exist because no hardware was ever built. The live example is
"CVA-01 class", the British carrier programme cancelled in 1966 before
being laid down. Before this chunk it sat in the exact same "missing,
paste a URL" bucket as a machine that just needs another search attempt —
misleading, because no amount of retrying will ever find CVA-01 a photo.

REVISION (2026-07-29, same day): the first cut of this file used a
status="cancelled" (bare) fixture that turned out not to match reality.
Pulling the REAL roster from prod (video d2e37cd6-521a-43aa-a14d-ce096a783c1e,
"Every British Aircraft Carrier Class Ever Built") via
`se db "select jsonb_pretty(research_payload->'unit_roster') from videos
where id='d2e37cd6-...'"` showed the researcher tags status LOOSELY: BOTH
CVA-01 class AND "Audacious class / Malta class" carry the IDENTICAL
status "cancelled-built" — status alone cannot tell them apart. built_count
is what separates them: CVA-01's says "0 ships built"; Audacious/Malta's
says "1 ship completed (Eagle R05), 3 cancelled on slips". The classifier
below was corrected to make built_count the primary decisive signal, with
status reduced to a coarse "does it mention cancelled at all" gate. See
REAL_BRITISH_CARRIER_ROSTER below — pulled verbatim from prod, not
reconstructed or invented.

This exercises:
  - pipeline_executor._roster_entry_never_built: two routes (bare-exact
    "cancelled" status; OR any cancellation-family status + an explicit
    zero-built assertion in built_count), each vetoed by a positive
    completed-count assertion or ANY "laid down" mention in built_count.
  - pipeline_executor._roster_status_built_count_contradicts /
    _roster_status_built_wording_but_zero_completed: the two soft
    repair-warning helpers in _roster_validation (contract-triangle law).
  - pipeline_executor._machine_documentary_hold_roster_entries carrying a
    `never_built` bool per entry (additive).
  - static_docu.prefetch_roster_references classifying BEFORE attempting
    any lookup, so a never-built machine never triggers a Wikimedia search
    or a paid vision call — it records REASON_NEVER_BUILT directly.

CONSERVATIVE BY DESIGN: a false "never built" verdict is worse than a
missed one (it permanently suppresses the retry affordance for a machine
whose photo may genuinely be findable). Under-detection is the correct
failure mode throughout.

No network calls. Every external lookup is monkeypatched.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_never_built_classification.py -q
"""
import os
import sys
import uuid
from pathlib import Path

import pytest

_BACKEND = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_BACKEND))

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PIPELINE_ROOT = _REPO_ROOT / "skills" / "video-pipeline"
if str(_PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_ROOT))

import pipeline_executor as pe  # noqa: E402
import static_docu as sd  # noqa: E402


# ---------------------------------------------------------------------------
# The REAL 23-entry roster for video d2e37cd6-521a-43aa-a14d-ce096a783c1e
# ("Every British Aircraft Carrier Class Ever Built"), pulled verbatim
# 2026-07-29 via:
#   cd storyengine && ./scripts/se.sh db \
#     "select research_payload->'unit_roster' from videos \
#      where id='d2e37cd6-521a-43aa-a14d-ce096a783c1e';"
# NOT reconstructed, NOT enriched, NOT invented — every field below is a
# direct copy of what the database actually holds today.
# ---------------------------------------------------------------------------

REAL_BRITISH_CARRIER_ROSTER = [
    {"name": "Argus", "role": "World's first true flat-deck aircraft carrier, converted from incomplete Italian liner", "years": "Laid down 1914 as liner, converted 1917-1918, commissioned September 1918 [NHHC 2024]", "bucket": "core_roster", "source": "[NHHC 2024]", "status": "production", "built_count": "1 ship converted [NHHC 2024]", "designation": "HMS Argus (I49)"},
    {"name": "Furious", "role": "Converted battlecruiser, first RN ship to launch and recover aircraft at sea, pioneered flush-deck configuration", "years": "Launched 1916 as battlecruiser, flight deck added 1917-1918, full flush deck conversion 1921-1925 [Brown 2012]", "bucket": "core_roster", "source": "[Brown 2012]", "status": "converted", "built_count": "1 ship converted from battlecruiser [Brown 2012]", "designation": "HMS Furious (47)"},
    {"name": "Hermes", "role": "World's first purpose-designed aircraft carrier laid down as such", "years": "Laid down January 1918, commissioned February 1924 [Friedman 1988]", "bucket": "core_roster", "source": "[Friedman 1988]", "status": "production", "built_count": "1 ship [Friedman 1988]", "designation": "HMS Hermes (95)"},
    {"name": "Eagle", "role": "Converted from incomplete Chilean battleship, large fleet carrier", "years": "Laid down 1913 as battleship, converted 1918-1924, commissioned April 1924 [Friedman 1988]", "bucket": "core_roster", "source": "[Friedman 1988]", "status": "converted", "built_count": "1 ship converted [Friedman 1988]", "designation": "HMS Eagle (1918)"},
    {"name": "Courageous class", "role": "Converted battlecruisers, first British fleet carriers with substantial aircraft capacity", "years": "Courageous commissioned 1928, Glorious commissioned 1930 as carriers [Brown 2012]", "bucket": "core_roster", "source": "[Brown 2012]", "status": "converted", "built_count": "2 ships converted from battlecruisers [Brown 2012]", "designation": "Courageous, Glorious"},
    {"name": "Ark Royal (1937)", "role": "First modern British fleet carrier with armored hangar and two-hangar design", "years": "Laid down 1935, commissioned November 1938 [Friedman 1988]", "bucket": "core_roster", "source": "[Friedman 1988]", "status": "production", "built_count": "1 ship [Friedman 1988]", "designation": "HMS Ark Royal (91)"},
    {"name": "Illustrious class", "role": "Armored fleet carriers, pioneered armored flight deck concept", "years": "Illustrious commissioned May 1940, Formidable November 1940, Victorious March 1941, Indomitable October 1941 [Friedman 1988]", "bucket": "core_roster", "source": "[Friedman 1988]", "status": "production", "built_count": "4 ships (Indomitable modified design) [Friedman 1988]", "designation": "Illustrious, Formidable, Victorious, Indomitable"},
    {"name": "Implacable class", "role": "Improved armored fleet carriers with increased aircraft capacity", "years": "Indefatigable commissioned May 1944, Implacable August 1944 [Friedman 1988]", "bucket": "core_roster", "source": "[Friedman 1988]", "status": "production", "built_count": "2 ships [Friedman 1988]", "designation": "Implacable, Indefatigable"},
    {"name": "Audacious class / Malta class", "role": "Large fleet carriers, four laid down 1942-1943, three cancelled on slips, one completed as HMS Eagle (1951)", "years": "Eagle (R05) laid down 1942, commissioned October 1951 (Audacious renamed) [Friedman 1988]", "bucket": "core_roster", "source": "[Friedman 1988]", "status": "cancelled-built", "built_count": "1 ship completed (Eagle R05), 3 cancelled on slips (Audacious renamed Eagle and completed, Africa, Eagle original cancelled, Malta, New Zealand, Gibraltar cancelled) [Friedman 1988]", "designation": "CVA-01 predecessors"},
    {"name": "Colossus class", "role": "Mass-production light fleet carriers for wartime construction", "years": "First (Colossus) commissioned December 1944, last (Vengeance) January 1945 [Hobbs 2015]", "bucket": "core_roster", "source": "[Hobbs 2015]", "status": "production", "built_count": "10 ships completed for RN service (8 wartime, 2 postwar) [Hobbs 2015]", "designation": "Light Fleet Carriers"},
    {"name": "Majestic class", "role": "Improved Colossus design, most completed postwar or sold incomplete", "years": "Laid down 1943-1945, Magnificent commissioned 1948, most completed 1950s for export [Hobbs 2015]", "bucket": "core_roster", "source": "[Hobbs 2015]", "status": "production", "built_count": "6 laid down, 1 completed for RN (Magnificent loaned to Canada), others sold or completed for foreign navies [Hobbs 2015]", "designation": "Improved Light Fleet Carriers"},
    {"name": "Centaur class", "role": "Intermediate fleet carriers, evolved from light fleet design with stronger structure", "years": "Centaur commissioned September 1953, Albion May 1954, Bulwark November 1954, Hermes November 1959 [Friedman 1988]", "bucket": "core_roster", "source": "[Friedman 1988]", "status": "production", "built_count": "4 ships [Friedman 1988]", "designation": "Centaur, Albion, Bulwark, Hermes (R12)"},
    {"name": "CVA-01 class", "role": "Large fleet carrier cancelled 1966, would have been first British angled-deck purpose-built carrier", "years": "Designed 1963-1966, construction planned 1966, cancelled by Defence White Paper February 1966 [Friedman 1988]", "bucket": "secret_cancelled_or_black_programs", "source": "[Friedman 1988]", "status": "cancelled-built", "built_count": "0 ships built, cancelled February 1966 before construction [Friedman 1988]", "designation": "CVA-01 Queen Elizabeth class (1960s design)"},
    {"name": "Invincible class", "role": "Through-deck cruisers/light STOVL carriers for Sea Harrier and helicopters", "years": "Invincible commissioned July 1980, Illustrious June 1982, Ark Royal November 1985 [Brown 2015]", "bucket": "core_roster", "source": "[Brown 2015]", "status": "production", "built_count": "3 ships [Brown 2015]", "designation": "Invincible, Illustrious, Ark Royal (R07)"},
    {"name": "Queen Elizabeth class", "role": "Large STOVL carriers for F-35B, largest warships built for Royal Navy", "years": "Queen Elizabeth commissioned December 2017, Prince of Wales commissioned December 2019 [Royal Navy 2024]", "bucket": "core_roster", "source": "[Royal Navy 2024]", "status": "production", "built_count": "2 ships [Royal Navy 2024]", "designation": "Queen Elizabeth, Prince of Wales"},
    {"name": "Archer class / Empire Mac-Ship conversions", "role": "Merchant Aircraft Carriers (MAC ships) - grain/oil tankers with flight decks for convoy ASW, civilian-crewed with RN flight crews", "years": "Conversions 1943-1944, operated until 1945 [Brown 2012]", "bucket": "converted_or_special_variants", "source": "[Brown 2012]", "status": "converted", "built_count": "19 grain ships and 6 tankers converted to MAC ships [Brown 2012]", "designation": "CAM ships and MAC ships"},
    {"name": "Activity class", "role": "Converted refrigerated cargo ship, used for training and ferry duties", "years": "Converted 1942, commissioned September 1942 [Hobbs 2015]", "bucket": "converted_or_special_variants", "source": "[Hobbs 2015]", "status": "converted", "built_count": "1 ship converted [Hobbs 2015]", "designation": "HMS Activity (D94)"},
    {"name": "Pretoria Castle class", "role": "Converted ocean liner, catapult-armed merchant (CAM) conversion for aircraft trials", "years": "Converted 1943, commissioned April 1943 as escort carrier [Hobbs 2015]", "bucket": "converted_or_special_variants", "source": "[Hobbs 2015]", "status": "converted", "built_count": "1 ship converted [Hobbs 2015]", "designation": "HMS Pretoria Castle (F61)"},
    {"name": "Nairana class", "role": "Converted merchant ships, escort carriers for convoy protection", "years": "Nairana commissioned December 1943, Vindex March 1943 [Hobbs 2015]", "bucket": "core_roster", "source": "[Hobbs 2015]", "status": "converted", "built_count": "2 ships converted [Hobbs 2015]", "designation": "Nairana, Vindex"},
    {"name": "Campania class", "role": "Converted passenger liner, escort carrier", "years": "Converted 1943, commissioned March 1944 [Hobbs 2015]", "bucket": "converted_or_special_variants", "source": "[Hobbs 2015]", "status": "converted", "built_count": "1 ship converted [Hobbs 2015]", "designation": "HMS Campania (D48)"},
    {"name": "Attacker class (US-built)", "role": "US-built Bogue-class escort carriers operated by Royal Navy under Lend-Lease", "years": "Transferred 1942-1943, returned to US 1946 [Hobbs 2015]", "bucket": "boundary_disputes", "source": "[Hobbs 2015]", "status": "production", "built_count": "Approximately 8 ships of Attacker group transferred [Hobbs 2015]", "designation": "Lend-Lease escort carriers"},
    {"name": "Ruler class (US-built)", "role": "US-built Casablanca-class escort carriers operated by Royal Navy under Lend-Lease", "years": "Transferred 1943-1944, returned to US 1946 [Hobbs 2015]", "bucket": "boundary_disputes", "source": "[Hobbs 2015]", "status": "production", "built_count": "Approximately 23 ships transferred [Hobbs 2015]", "designation": "Lend-Lease escort carriers"},
    {"name": "Unicorn", "role": "Aircraft maintenance carrier, light fleet carrier hull with repair facilities", "years": "Laid down 1939, commissioned March 1943 [Friedman 1988]", "bucket": "core_roster", "source": "[Friedman 1988]", "status": "production", "built_count": "1 ship [Friedman 1988]", "designation": "HMS Unicorn (I72)"},
]
assert len(REAL_BRITISH_CARRIER_ROSTER) == 23

# The two entries the coordinator specifically flagged, extracted for
# direct reference in the dedicated regression test below.
_REAL_CVA01 = next(e for e in REAL_BRITISH_CARRIER_ROSTER if e["name"] == "CVA-01 class")
_REAL_AUDACIOUS_MALTA = next(
    e for e in REAL_BRITISH_CARRIER_ROSTER if e["name"] == "Audacious class / Malta class"
)


# ---------------------------------------------------------------------------
# 1. The REAL 23-entry roster: verdict table. CVA-01 caught, all 22 others
#    refused — INCLUDING Audacious/Malta, which carries the exact SAME
#    status ("cancelled-built") as CVA-01. status alone cannot separate
#    them; only built_count does.
# ---------------------------------------------------------------------------

def test_never_built_verdict_table_over_real_23_ship_roster():
    verdicts = {item["name"]: pe._roster_entry_never_built(item) for item in REAL_BRITISH_CARRIER_ROSTER}

    never_built_names = [name for name, verdict in verdicts.items() if verdict]
    assert never_built_names == ["CVA-01 class"], (
        f"Expected ONLY CVA-01 class to classify as never-built; got {never_built_names}. "
        "Verdict table:\n" + "\n".join(f"  {name!r}: {v}" for name, v in verdicts.items())
    )

    for name, verdict in verdicts.items():
        if name == "CVA-01 class":
            continue
        assert verdict is False, f"{name!r} was wrongly classified never-built"

    # The trap, explicitly: identical status to CVA-01, must still refuse.
    assert _REAL_AUDACIOUS_MALTA["status"] == _REAL_CVA01["status"] == "cancelled-built"
    assert pe._roster_entry_never_built(_REAL_AUDACIOUS_MALTA) is False


def test_never_built_verdict_table_via_roster_entries_accessor():
    """Same table, exercised through the real accessor
    (_machine_documentary_hold_roster_entries) the prefetch sweep actually
    calls — proves the `never_built` key is wired end to end."""
    video = {
        "id": "ship-vid-1",
        "render_mode": "static_docu",
        "research_payload": {
            "documentary_style": "designed_vs_used",
            "unit_roster": REAL_BRITISH_CARRIER_ROSTER,
        },
    }
    entries = pe._machine_documentary_hold_roster_entries(video)
    assert len(entries) == 23
    never_built_flags = {e["name"]: e["never_built"] for e in entries}
    # The accessor's "name" is the glued display string (designation + bare
    # name — see pipeline_executor._unit_display_name) for entries where
    # designation isn't already a substring of name.
    true_names = [name for name, v in never_built_flags.items() if v]
    assert len(true_names) == 1
    assert "CVA-01" in true_names[0]


# ---------------------------------------------------------------------------
# 2. DEDICATED REGRESSION TEST: the two real prod entries, VERBATIM, exactly
#    as pasted by the coordinator and re-verified against the live database.
#    This exact miss (status alone looked decisive, was NOT) can never
#    silently recur — if either assertion below ever flips red, the
#    classifier regressed on real, previously-verified production data.
# ---------------------------------------------------------------------------

def test_real_cva01_entry_verbatim_classifies_never_built():
    entry = {
        "name": "CVA-01 class",
        "role": "Large fleet carrier cancelled 1966, would have been first British angled-deck purpose-built carrier",
        "years": "Designed 1963-1966, construction planned 1966, cancelled by Defence White Paper February 1966 [Friedman 1988]",
        "bucket": "secret_cancelled_or_black_programs",
        "source": "[Friedman 1988]",
        "status": "cancelled-built",
        "built_count": "0 ships built, cancelled February 1966 before construction [Friedman 1988]",
        "designation": "CVA-01 Queen Elizabeth class (1960s design)",
    }
    assert pe._roster_entry_never_built(entry) is True


def test_real_audacious_malta_entry_verbatim_refuses_despite_identical_status():
    entry = {
        "name": "Audacious class / Malta class",
        "role": "Large fleet carriers, four laid down 1942-1943, three cancelled on slips, one completed as HMS Eagle (1951)",
        "years": "Eagle (R05) laid down 1942, commissioned October 1951 (Audacious renamed) [Friedman 1988]",
        "bucket": "core_roster",
        "source": "[Friedman 1988]",
        "status": "cancelled-built",
        "built_count": "1 ship completed (Eagle R05), 3 cancelled on slips (Audacious renamed Eagle and completed, Africa, Eagle original cancelled, Malta, New Zealand, Gibraltar cancelled) [Friedman 1988]",
        "designation": "CVA-01 predecessors",
    }
    assert pe._roster_entry_never_built(entry) is False, (
        "Audacious/Malta must stay refused even though its status "
        "('cancelled-built') is IDENTICAL to CVA-01's — built_count is the "
        "field that must separate them ('1 ship completed' vs '0 ships built')"
    )


# ---------------------------------------------------------------------------
# 3. Aircraft-shaped entries, including the most important negative case:
#    a cancelled-but-flown prototype (XB-70 Valkyrie style) must NOT be
#    classified as never-built.
# ---------------------------------------------------------------------------

AIRCRAFT_STATUS_ROSTER = [
    {
        "name": "XB-70 Valkyrie",
        "designation": "North American XB-70",
        "status": "cancelled-built",
        "built_count": "2 prototypes built and flown",
    },
    {
        "name": "Avro Arrow",
        "designation": "Avro CF-105",
        "status": "built-prototype",
        "built_count": "5-6 prototypes built and flown, program cancelled 1959",
    },
    {
        "name": "TSR-2",
        "designation": "BAC TSR-2",
        "status": "cancelled-built",
        "built_count": "1 prototype built and flown, several more airframes in build",
    },
    {
        "name": "Boeing B-52",
        "designation": "B-52",
        "status": "production",
        "built_count": "744 aircraft",
    },
    # A genuine paper-only cancellation for contrast: real decisive positive
    # (Route A: bare "cancelled" status, no built_count at all).
    {
        "name": "Paperhawk Interceptor",
        "designation": "XF-99 Paperhawk",
        "status": "cancelled",
    },
    # Route B positive: cancelled-family status + explicit zero built_count.
    {
        "name": "Paperhawk II",
        "designation": "XF-99B Paperhawk II",
        "status": "cancelled-built",
        "built_count": "0 aircraft built, program cancelled before rollout",
    },
    # Contradiction trap: bare "cancelled" but built_count says otherwise —
    # must be refused (data inconsistency, not evidence).
    {
        "name": "Contradictory Bomber",
        "designation": "XB-00",
        "status": "cancelled",
        "built_count": "3 aircraft built before the program was cancelled",
    },
    # Missing status entirely — must be refused (never guess from absence).
    {
        "name": "No-Status Fighter",
        "designation": "YF-00",
    },
    # The laid-down-but-zero-completed hypothetical from requirement #4:
    # some physical hardware existed (a hull/airframe on the line) even
    # though the completed count is zero. Must be refused — under-detection
    # is correct here because a laid-down/partially-built unit MAY have
    # been photographed under construction.
    {
        "name": "Hypothetical Laid-Down Zero",
        "designation": "XB-01",
        "status": "cancelled-built",
        "built_count": "2 hulls laid down, 0 completed, program cancelled",
    },
]


def test_cancelled_but_flown_prototype_is_never_classified_never_built():
    """THE MOST IMPORTANT NEGATIVE CASE: a cancelled programme whose
    prototypes were actually built and flown (XB-70 Valkyrie shape) has
    real photographs and must never be told otherwise."""
    for name in ("XB-70 Valkyrie", "Avro Arrow", "TSR-2"):
        item = next(e for e in AIRCRAFT_STATUS_ROSTER if e["name"] == name)
        assert pe._roster_entry_never_built(item) is False, (
            f"{name} was wrongly classified never-built — it has status "
            f"{item['status']!r} and built_count {item.get('built_count')!r}, "
            "a cancelled-but-BUILT programme with real photographs."
        )


def test_aircraft_roster_verdict_table():
    verdicts = {item["name"]: pe._roster_entry_never_built(item) for item in AIRCRAFT_STATUS_ROSTER}
    assert verdicts == {
        "XB-70 Valkyrie": False,
        "Avro Arrow": False,
        "TSR-2": False,
        "Boeing B-52": False,
        "Paperhawk Interceptor": True,
        "Paperhawk II": True,
        "Contradictory Bomber": False,
        "No-Status Fighter": False,
        "Hypothetical Laid-Down Zero": False,
    }, verdicts


# ---------------------------------------------------------------------------
# 4. Non-dict / string roster items (older roster shape, or a fixture with
#    no status field) must always refuse — there is nothing to classify.
# ---------------------------------------------------------------------------

def test_string_roster_item_never_classified():
    assert pe._roster_entry_never_built("Boeing XB-15") is False
    assert pe._roster_entry_never_built(None) is False
    assert pe._roster_entry_never_built({}) is False


# ---------------------------------------------------------------------------
# 5. The two soft repair-warning helpers, and _roster_validation wiring.
# ---------------------------------------------------------------------------

def test_contradiction_helper_route_a_bare_cancelled_plus_veto():
    contradictory = {"status": "cancelled", "built_count": "3 aircraft built"}
    clean_cancelled = {"status": "cancelled"}
    cancelled_built = {"status": "cancelled-built", "built_count": "2 built"}

    assert pe._roster_status_built_count_contradicts(contradictory) is True
    assert pe._roster_entry_never_built(contradictory) is False

    assert pe._roster_status_built_count_contradicts(clean_cancelled) is False
    assert pe._roster_entry_never_built(clean_cancelled) is True

    # "cancelled-built" is not bare "cancelled" — not this contradiction,
    # it's simply a (correct, in this case) different status value.
    assert pe._roster_status_built_count_contradicts(cancelled_built) is False


def test_mislabel_helper_built_wording_but_zero_completed():
    """The exact real-world mislabeling verified in prod: status uses
    '-built' wording but built_count says zero were ever completed."""
    assert pe._roster_status_built_wording_but_zero_completed(_REAL_CVA01) is True
    assert pe._roster_status_built_wording_but_zero_completed(_REAL_AUDACIOUS_MALTA) is False

    built_prototype_zero = {"status": "built-prototype", "built_count": "0 built"}
    assert pe._roster_status_built_wording_but_zero_completed(built_prototype_zero) is True

    production_entry = {"status": "production", "built_count": "0 built"}
    assert pe._roster_status_built_wording_but_zero_completed(production_entry) is False, (
        "status must mention '-built'/'built-' wording for this helper to "
        "apply — 'production' doesn't, even with a (nonsensical) zero count"
    )


def test_roster_validation_flags_both_contradiction_families_as_soft_not_hard():
    """Both repair warnings must surface as SOFT (needs_review) — neither
    should ever block the video from advancing, since the classifier
    itself already handles the underlying data correctly either way; these
    are visibility for the next research pass, not new hard gates."""
    payload = {
        "unit_roster": [
            # Route A contradiction: bare "cancelled" + built_count veto.
            {"name": "Contradictory Bomber", "designation": "XB-00",
             "status": "cancelled", "built_count": "3 aircraft built before cancellation"},
            # Mislabeling: "-built" wording + zero completed (real shape).
            dict(_REAL_CVA01),
            # Clean, no warning expected.
            {"name": "Clean Cancelled", "designation": "XB-01", "status": "cancelled"},
            dict(_REAL_AUDACIOUS_MALTA),
        ],
        "machine_discovery_buckets": {"core_roster": [{"name": "x"}] * 20},
        "recommended_final_roster": ["a", "b", "c", "d"],
        "gap_hunt_matrix": [{"candidate": "x"}],
        "edge_case_matrix": [{"edge_case_class": "x"}],
    }
    result = pe._roster_validation("Some Non-Complete-Title Video", payload)
    joined = " ".join(result["warnings"]).lower()

    assert "contradictory bomber" in joined
    assert "cva-01 class" in joined
    assert "clean cancelled" not in joined
    assert "audacious class / malta class" not in joined

    soft_joined = " ".join(result["soft_warnings"]).lower()
    assert "contradictory bomber" in soft_joined
    assert "cva-01 class" in soft_joined
    hard_joined = " ".join(result["hard_warnings"]).lower()
    assert "contradictory bomber" not in hard_joined
    assert "cva-01 class" not in hard_joined
    assert result["needs_review"] is True


def test_roster_validation_silent_when_no_contradiction_or_mislabel():
    payload = {
        "unit_roster": [
            {"name": "Clean Cancelled", "designation": "XB-01", "status": "cancelled"},
            {"name": "Clean Built", "designation": "XB-02", "status": "production",
             "built_count": "10 aircraft"},
            dict(_REAL_AUDACIOUS_MALTA),  # cancelled-built, but count backs it up
        ],
    }
    result = pe._roster_validation("A Small Video", payload)
    joined = " ".join(result["warnings"]).lower()
    assert "built_count asserts real hardware" not in joined
    assert "zero units were ever completed" not in joined


# ---------------------------------------------------------------------------
# 6. static_docu.prefetch_roster_references: a never-built machine must be
#    classified BEFORE any lookup — no candidate-gather, no hosting, no
#    vision call — and recorded with REASON_NEVER_BUILT.
# ---------------------------------------------------------------------------

def _video_row(video_id, roster):
    return {
        "id": video_id,
        "render_mode": "static_docu",
        "research_payload": {
            "documentary_style": "designed_vs_used",
            "unit_roster": roster,
        },
    }


@pytest.mark.asyncio
async def test_never_built_machine_skips_the_entire_lookup_chain(monkeypatch):
    video_id, tenant_id = str(uuid.uuid4()), str(uuid.uuid4())
    roster = [
        {"name": "Boeing XB-15", "designation": "XB-15", "status": "production", "built_count": "1"},
        {"name": "Northrop XB-35", "designation": "XB-35", "status": "production", "built_count": "2"},
        dict(_REAL_CVA01),
    ]
    video_row = _video_row(video_id, roster)

    gather_calls = []
    miss_writes = []

    async def fake_fetch_one(query, *args):
        if "FROM videos" in query:
            return dict(video_row)
        if "FROM static_reference_cache" in query:
            return None  # nothing cached for any machine
        return None

    async def fake_execute(query, *args):
        if "INSERT INTO static_reference_misses" in query:
            miss_writes.append(args)
        return None

    async def fake_gather(machine_arg, aliases, query):
        gather_calls.append(machine_arg)
        return []  # the other two miss too, for symmetry — irrelevant to the assertion

    monkeypatch.setattr(sd, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(sd, "execute", fake_execute)
    monkeypatch.setattr(sd, "_gather_reference_candidates", fake_gather)

    result = await sd.prefetch_roster_references(video_id, tenant_id)

    assert result["status"] == "completed"
    assert result["roster_count"] == 3
    assert result["never_built"] == 1
    assert result["missed"] == 2  # the other two ran a real (if empty) search attempt
    assert result["verified"] == 0

    # THE MONEY ASSERTION: _gather_reference_candidates (and therefore the
    # whole hosting/vision chain downstream of it) must NEVER be called for
    # CVA-01 — this is the "saves money" half of the design.
    assert gather_calls == ["Boeing XB-15", "Northrop XB-35"], (
        "CVA-01 must never reach the candidate-gather step once classified "
        f"never-built; calls were: {gather_calls}"
    )

    never_built_writes = [w for w in miss_writes if w[4] == sd.REASON_NEVER_BUILT]
    assert len(never_built_writes) == 1
    tenant_arg, video_arg, mkey_arg, machine_arg, reason_arg, detail_arg = never_built_writes[0]
    assert tenant_arg == tenant_id
    assert video_arg == video_id
    assert "CVA-01" in machine_arg
    assert "never" in detail_arg.lower() and "built" in detail_arg.lower()


@pytest.mark.asyncio
async def test_audacious_malta_trap_is_not_skipped_by_prefetch(monkeypatch):
    """The trap entry must still go through the real lookup chain — it is
    NOT classified never-built, so it must reach _gather_reference_candidates
    exactly like any other machine with a findable photo."""
    video_id, tenant_id = str(uuid.uuid4()), str(uuid.uuid4())
    roster = [
        dict(_REAL_CVA01),
        dict(_REAL_AUDACIOUS_MALTA),
        {"name": "Boeing XB-15", "designation": "XB-15", "status": "production", "built_count": "1"},
    ]
    video_row = _video_row(video_id, roster)

    gather_calls = []

    async def fake_fetch_one(query, *args):
        if "FROM videos" in query:
            return dict(video_row)
        if "FROM static_reference_cache" in query:
            return None
        return None

    async def fake_execute(query, *args):
        return None

    async def fake_gather(machine_arg, aliases, query):
        gather_calls.append(machine_arg)
        return []

    monkeypatch.setattr(sd, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(sd, "execute", fake_execute)
    monkeypatch.setattr(sd, "_gather_reference_candidates", fake_gather)

    result = await sd.prefetch_roster_references(video_id, tenant_id)

    assert result["never_built"] == 1  # CVA-01 only
    assert any("Audacious" in name for name in gather_calls), (
        "Audacious/Malta must reach the real candidate-gather step — it is "
        "NOT never-built despite sharing CVA-01's status"
    )
    # Note: Audacious/Malta's OWN designation is "CVA-01 predecessors", so
    # its display name legitimately contains the substring "CVA-01" — check
    # for the CVA-01 class row's exact display name instead of a bare
    # substring.
    cva01_display_name = pe._unit_display_name(_REAL_CVA01)
    assert cva01_display_name not in gather_calls


@pytest.mark.asyncio
async def test_cached_photo_wins_over_never_built_classification(monkeypatch):
    """If a machine somehow already has a verified reference cached (e.g. an
    operator manually seeded a photo, or the classification is simply
    wrong for this tenant), the cache hit must win — never_built is only
    consulted for a machine with NO existing verified reference."""
    video_id, tenant_id = str(uuid.uuid4()), str(uuid.uuid4())
    roster = [
        dict(_REAL_CVA01),
        {"name": "Boeing XB-15", "designation": "XB-15", "status": "production", "built_count": "1"},
        {"name": "Northrop XB-35", "designation": "XB-35", "status": "production", "built_count": "2"},
    ]
    video_row = _video_row(video_id, roster)
    cva01_name = pe._unit_display_name(_REAL_CVA01)
    cva01_key = sd._machine_key(cva01_name)

    gather_calls = []
    miss_writes = []

    async def fake_fetch_one(query, *args):
        if "FROM videos" in query:
            return dict(video_row)
        if "FROM static_reference_cache" in query:
            if args and args[-1] == cva01_key:
                return {"hosted_url": "https://storage.example/manually-seeded-cva01.jpg"}
            return None  # the other two are unrelated to this assertion
        return None

    async def fake_execute(query, *args):
        if "DELETE FROM static_reference_misses" in query:
            miss_writes.append(("delete", args))
        if "INSERT INTO static_reference_misses" in query:
            miss_writes.append(("insert", args))
        return None

    async def fake_gather(machine_arg, aliases, query):
        gather_calls.append(machine_arg)
        return []

    monkeypatch.setattr(sd, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(sd, "execute", fake_execute)
    monkeypatch.setattr(sd, "_gather_reference_candidates", fake_gather)

    result = await sd.prefetch_roster_references(video_id, tenant_id)

    assert result["verified"] == 1  # CVA-01, from the cache — not the classifier
    assert result["never_built"] == 0, (
        "the cache hit must short-circuit BEFORE the never_built check, so a "
        "cached machine is never counted as a never_built skip"
    )
    assert cva01_name not in gather_calls, "cached machine must never reach the candidate-gather step"
    assert ("delete", (tenant_id, video_id, cva01_key)) in miss_writes


# ---------------------------------------------------------------------------
# 7. roster_repair_dashboard end-to-end: a never_built miss row must
#    surface retryable=False (pre-existing C8 wiring — this proves it now
#    receives a REAL never_built row, not just a hand-fed test fixture).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dashboard_marks_never_built_machine_not_retryable(monkeypatch):
    tenant_id, video_id = str(uuid.uuid4()), str(uuid.uuid4())
    cva01_display_name = pe._unit_display_name(_REAL_CVA01)
    roster = ["Boeing XB-15", "Northrop XB-35", cva01_display_name]
    video_row = {
        "id": video_id,
        "tenant_id": tenant_id,
        "render_mode": "static_docu",
        "research_payload": {"documentary_style": "designed_vs_used", "unit_roster": roster},
    }
    executor = pe.PipelineExecutor(tenant_id)

    async def fake_ensure_initialized():
        return None

    async def fake_get_video(vid):
        return dict(video_row)

    async def fake_load_cards(vid, payload, roster=None, target_machine=None):
        return payload

    monkeypatch.setattr(executor, "_ensure_initialized", fake_ensure_initialized)
    monkeypatch.setattr(executor, "_get_video", fake_get_video)
    monkeypatch.setattr(executor, "_load_machine_research_cards", fake_load_cards)

    cva01_key = sd._machine_key(cva01_display_name)

    async def fake_fetch_all(query, *args):
        if "FROM machine_research_cards" in query:
            return []
        if "FROM static_reference_cache" in query:
            return []
        if "FROM static_reference_misses" in query:
            return [{"machine_key": cva01_key, "reason_code": sd.REASON_NEVER_BUILT,
                     "reason_detail": "This machine was never actually built — no photo can ever exist."}]
        return []

    monkeypatch.setattr(pe, "fetch_all", fake_fetch_all)

    result = await executor.roster_repair_dashboard(video_id)
    units_by_machine = {u["machine"]: u for u in result["units"]}
    cva01_unit = units_by_machine[cva01_display_name]
    assert cva01_unit["reference"]["status"] == "missing"
    assert cva01_unit["reference"]["reason_code"] == "never_built"
    assert cva01_unit["reference"]["retryable"] is False
