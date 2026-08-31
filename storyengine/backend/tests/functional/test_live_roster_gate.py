"""The roster gate must be RECOMPUTED, never read back off the row.

WHY THIS EXISTS (2026-07-30): video d2e37cd6-521a-43aa-a14d-ce096a783c1e
("Every British Aircraft Carrier Class Ever Built") sat at idea_logged from
2026-07-27 onward. Its research_payload carried a stored
`unit_roster_validation` with `passed: false`, and its ONLY complaint was
roster pacing - 23 ships against a 20-minute runtime target.

The C4 severity split (2026-07-29) reclassified exactly that complaint from
fatal to soft, so the live rules score the same roster
`passed: true, needs_review: true`. But two gates read the STORED verdict:

  - pipeline_executor.run_unit_research (was line 9766) - the entry point for
    incremental per-machine research, i.e. the exact thing you would run to
    fill in the machines that are still missing.
  - the advance-to-scripting gate (was line 12730).

So a rule that no longer existed kept blocking the video, and the only way to
clear a stored verdict was to pay for a full research re-run that regenerates
the whole roster and orphans its verified reference photos.

These tests pin the fix: `_live_roster_gate` ignores the stored copy entirely.

No network. No DB. `_roster_validation` is a pure function.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_live_roster_gate.py -q
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


# The real 23-entry roster from the prod row, in the shape the payload stores.
CARRIER_ROSTER = [
    "HMS Argus (I49) Argus",
    "HMS Furious (47) Furious",
    "HMS Hermes (95) Hermes",
    "HMS Eagle (1918) Eagle",
    "Courageous, Glorious Courageous class",
    "HMS Ark Royal (91) Ark Royal (1937)",
    "Illustrious, Formidable, Victorious, Indomitable Illustrious class",
    "Implacable, Indefatigable Implacable class",
    "CVA-01 predecessors Audacious class / Malta class",
    "Light Fleet Carriers Colossus class",
    "Improved Light Fleet Carriers Majestic class",
    "Centaur, Albion, Bulwark, Hermes (R12) Centaur class",
    "CVA-01 Queen Elizabeth class (1960s design) CVA-01 class",
    "Invincible, Illustrious, Ark Royal (R07) Invincible class",
    "Queen Elizabeth, Prince of Wales Queen Elizabeth class",
    "CAM ships and MAC ships Archer class / Empire Mac-Ship conversions",
    "HMS Activity (D94) Activity class",
    "HMS Pretoria Castle (F61) Pretoria Castle class",
    "Nairana, Vindex Nairana class",
    "HMS Campania (D48) Campania class",
    "Lend-Lease escort carriers Attacker class (US-built)",
    "Lend-Lease escort carriers Ruler class (US-built)",
    "HMS Unicorn (I72) Unicorn",
]

# The stale verdict frozen on the real row: pre-severity-split shape. Note the
# absence of hard_warnings/soft_warnings/needs_review - that shape is itself
# the tell that these rules predate C4.
STALE_STORED_VERDICT = {
    "passed": False,
    "warnings": [
        "Broad complete-roster final roster is larger than the runtime target "
        "plus reserve: 23 final items vs target around 20 for a 20-minute "
        "video. Tighten the roster to fit the requested runtime, or prove that "
        "the title requires the larger count."
    ],
    "gaps": [],
    "roster": list(CARRIER_ROSTER),
    "roster_count": 23,
    "complete_title": True,
    "review_ready": False,
}


def _video(payload_extra=None):
    # The structural keys below are NOT padding: _roster_validation treats a
    # complete-roster payload missing any of them as a HARD failure (audit
    # proof, adversarial omission pass, edge-case classes, the discovery
    # buckets, and a recommendation whose count matches the roster). The real
    # prod row carries all of them, so a fixture without them would fail for
    # reasons that have nothing to do with what these tests are pinning.
    payload = {
        "unit_roster": list(CARRIER_ROSTER),
        "roster_contract": "Every British aircraft carrier class ever built.",
        "unit_roster_validation": dict(STALE_STORED_VERDICT),
        "roster_audit": {
            # A complete-roster title demands >=6 distinct discovery searches
            # and >=3 cross-checked source families, with high/medium
            # confidence and no unresolved candidates - all hard gates.
            "search_queries_used": [
                "list of Royal Navy aircraft carriers",
                "British aircraft carrier classes by era",
                "Royal Navy escort carriers WWII",
                "British light fleet carriers",
                "cancelled British carrier programmes",
                "Royal Navy seaplane and merchant carriers",
            ],
            "source_families_crosschecked": [
                "Naval histories",
                "Admiralty/official records",
                "Reference encyclopaedias",
            ],
            "unresolved_candidates": [],
            "confidence": "high",
            "excluded_candidates": [],
        },
        "gap_hunt_matrix": [{"candidate": "HMS Vindictive", "verdict": "excluded, cruiser conversion"}],
        "edge_case_matrix": [{"class": "seaplane carriers", "checked": True}],
        "machine_discovery_buckets": {
            "core_roster": list(CARRIER_ROSTER[:15]),
            "built_prototypes": [],
            "boundary_disputes": list(CARRIER_ROSTER[15:17]),
            "converted_or_special_variants": list(CARRIER_ROSTER[17:21]),
            "secret_cancelled_or_black_programs": list(CARRIER_ROSTER[21:]),
        },
        # Count must equal the roster, else the gate raises a separate
        # hard mismatch warning.
        "recommended_final_roster": list(CARRIER_ROSTER),
    }
    if payload_extra:
        payload.update(payload_extra)
    return {
        "video_title": "Every British Aircraft Carrier Class Ever Built",
        "video_length_minutes": 20,
        "research_payload": payload,
    }, payload


def test_stale_stored_rejection_does_not_survive_recomputation():
    """The headline case: stored passed=False, live verdict passes."""
    video, payload = _video()
    assert payload["unit_roster_validation"]["passed"] is False

    gate = pe._live_roster_gate(video, payload)

    assert gate["passed"] is True, (
        "the 23-ship roster's only complaint is pacing, which C4 made soft - "
        "a recomputed gate must not inherit the frozen rejection"
    )
    assert gate["needs_review"] is True, (
        "passing is not the same as clean: the pacing complaint must still "
        "surface as a soft flag for review"
    )
    assert gate["hard_warnings"] == []
    assert gate["soft_warnings"], "the pacing complaint must not vanish silently"


def test_recomputed_gate_ignores_the_stored_copy_entirely():
    """Even a stored verdict claiming success is not trusted."""
    video, payload = _video()
    payload["unit_roster_validation"] = {"passed": True, "warnings": []}
    trusting = pe._live_roster_gate(video, payload)

    video2, payload2 = _video()
    payload2["unit_roster_validation"] = {"passed": False, "warnings": ["anything"]}
    rejecting = pe._live_roster_gate(video2, payload2)

    assert trusting == rejecting, (
        "the stored copy is history, not input - two rows with identical "
        "rosters must score identically no matter what verdict is cached"
    )


def test_missing_stored_verdict_is_not_an_error():
    """A payload that never had a verdict recomputes the same way."""
    video, payload = _video()
    payload.pop("unit_roster_validation")
    gate = pe._live_roster_gate(video, payload)
    assert gate["passed"] is True
    assert gate["roster_count"] == 23


def test_runtime_is_taken_from_the_video_not_a_default():
    """The old fallback omitted video_length_minutes; pacing targets must
    follow this video's actual runtime, so a longer video accommodates the
    same roster without the soft flag."""
    short_video, short_payload = _video()
    short_gate = pe._live_roster_gate(short_video, short_payload)

    long_video, long_payload = _video()
    long_video["video_length_minutes"] = 30
    long_gate = pe._live_roster_gate(long_video, long_payload)

    assert short_gate["roster_pacing_targets"]["video_length_minutes"] == 20.0
    assert long_gate["roster_pacing_targets"]["video_length_minutes"] == 30.0
    assert (
        long_gate["roster_pacing_targets"]["expected_final_roster"]
        > short_gate["roster_pacing_targets"]["expected_final_roster"]
    ), "a longer runtime must raise the expected roster size"


def test_a_genuinely_broken_roster_still_fails():
    """The fix must not turn the gate into a rubber stamp."""
    video, payload = _video()
    payload["unit_roster"] = []
    gate = pe._live_roster_gate(video, payload)
    assert gate["passed"] is False, "an empty roster is a hard failure, not a nitpick"
    assert gate["hard_warnings"], "a hard failure must be reported as hard"


def test_ever_built_title_rejects_cancelled_and_unfinished_entries():
    """An "ever built" roster cannot redefine ordered or cancelled as built."""
    video, payload = _video()
    invalid = [
        {
            "name": "USS United States",
            "designation": "CVA-58",
            "status": "cancelled",
            "built_count": "0 ships built; keel laid for five days before cancellation",
        },
        {
            "name": "Gerald R. Ford-class",
            "designation": "CVN-78 through CVN-83",
            "status": "production",
            "built_count": "6 ships planned; later hulls are under construction or on order",
        },
    ]
    payload["unit_roster"].extend(invalid)
    payload["recommended_final_roster"] = list(payload["unit_roster"])
    payload["machine_discovery_buckets"]["core_roster"].extend(invalid)

    gate = pe._live_roster_gate(video, payload)

    assert gate["passed"] is False
    assert any(
        "not actually built" in warning
        and "CVA-58 USS United States" in warning
        and "CVN-78 through CVN-83 Gerald R. Ford-class" in warning
        for warning in gate["hard_warnings"]
    )
