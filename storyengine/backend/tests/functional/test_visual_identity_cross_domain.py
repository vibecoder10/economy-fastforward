"""_visual_identity_warnings must accept every DVsU machine domain.

WHY THIS EXISTS (2026-07-30): the "concrete visible machine features" check
inside _visual_identity_warnings listed only aircraft anatomy (wing,
fuselage, cockpit...). An honest, sourced description of a Majestic-class
carrier — flight deck, island, funnel — failed the check because a ship has
none of those aircraft words to name. The DVsU channel covers ships,
helicopters, armor and ground vehicles; the vocabulary now carries each
domain's visible anatomy. Found live by the research simulator's Argus card,
which was rejected for naming a "perfectly clear flying deck from stem to
stern" - about as concrete as a visible feature gets.

No network. No DB. Pure function.

Run:
    cd storyengine/backend && ./venv/bin/python -m pytest \
        tests/functional/test_visual_identity_cross_domain.py -q
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


_FEATURE_WARNING = "visual_identity must include concrete visible machine features"


def _warnings(machine, text):
    evidence = [
        {
            "evidence_id": "vi1",
            "kind": "visual_identity",
            "claim": text,
            "source_excerpt": text,
            "source_excerpt_id": "S1-E1",
            "source_url": "https://example.test/src",
            "source_title": "src",
            "locator": "S1-E1",
            "numeric_tokens": [],
            "confidence": "high",
        }
    ]
    return pe._visual_identity_warnings(machine, text, evidence, ["vi1"])


def test_ship_features_pass_the_concrete_feature_check():
    w = _warnings(
        "HMS Argus (I49) Argus",
        "HMS Argus (I49) shows a perfectly clear flying deck from stem to stern, "
        "smoke ducts aft, two hinged wireless masts, and wind-breaking palisades amidships.",
    )
    assert _FEATURE_WARNING not in w


def test_carrier_island_and_funnel_pass():
    w = _warnings(
        "Improved Light Fleet Carriers Majestic class",
        "Majestic class hulls carry an angled flight deck, a starboard island "
        "with a single funnel, and a lattice mast over the superstructure.",
    )
    assert _FEATURE_WARNING not in w


def test_helicopter_rotor_passes():
    w = _warnings(
        "Westland Wessex HAS.1 Wessex",
        "The Wessex shows a humped nose over twin main rotor blades and a tailboom "
        "drooping to the rotor guard.",
    )
    assert _FEATURE_WARNING not in w


def test_tank_track_and_turret_pass():
    w = _warnings(
        "M4 Sherman M4",
        "The M4 shows a cast rounded turret, a short 75mm barrel, and rubber-block "
        "tracks over a raised rear engine deck.",
    )
    assert _FEATURE_WARNING not in w


def test_aircraft_vocabulary_still_passes_unchanged():
    w = _warnings(
        "Boeing B-52 Stratofortress B-52",
        "The B-52 shows eight podded engines under swept wings and a towering tail fin.",
    )
    assert _FEATURE_WARNING not in w


def test_featureless_text_still_fails():
    w = _warnings(
        "HMS Argus (I49) Argus",
        "HMS Argus (I49) appears large and grey and impressive in historical photographs "
        "of the period and is easy to identify at any distance.",
    )
    assert _FEATURE_WARNING in w


def test_unmistakable_next_to_ship_feature_is_not_generic():
    w = _warnings(
        "HMS Argus (I49) Argus",
        "HMS Argus (I49) is unmistakable for its full-length flush flight deck with no island.",
    )
    assert not any("generic" in x for x in w)
