import sys
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import pipeline_executor as pe


def _classifier_actions(monkeypatch, package_error: str) -> list[dict]:
    package = {"candidate_excerpts": []}
    card = {"evidence_segments": [{"evidence_id": "E1"}]}

    monkeypatch.setattr(pe, "_verified_machine_source_package_ready", lambda _package: True)
    monkeypatch.setattr(
        pe,
        "_verified_machine_source_package_quality_errors",
        lambda _package, _machine: [package_error],
    )
    monkeypatch.setattr(
        pe,
        "_verified_machine_source_package_identity_errors",
        lambda _package, _machine: [],
    )
    monkeypatch.setattr(
        pe,
        "_research_card_contract_warnings",
        lambda *_args, **_kwargs: [
            "evidence segment E1 claim numbers absent from source_excerpt: 1918"
        ],
    )
    monkeypatch.setattr(pe, "_package_conversion_signals", lambda *_args: [])
    monkeypatch.setattr(pe, "_timeframe_promotable_excerpts", lambda *_args: [])
    monkeypatch.setattr(
        pe,
        "_segment_surgery_plan",
        lambda *_args: {"rekinds": [], "promotes": [], "blocked": []},
    )

    return pe._classify_repair_actions("94 HMS Eagle (1918)", card, package)


def test_advisory_package_gap_does_not_trigger_paid_targeted_fetch(monkeypatch):
    actions = _classifier_actions(
        monkeypatch,
        "advisory: [tier_floor_advisory] Verified source package needs at least one Tier 1-2 source",
    )

    assert all(action["verb"] != "targeted_fetch" for action in actions)
    assert actions == [{
        "verb": "full_rerun",
        "reason": (
            "no surgical verb applies: evidence segment E1 claim numbers absent "
            "from source_excerpt: 1918"
        ),
    }]


def test_genuine_package_gap_still_triggers_targeted_fetch(monkeypatch):
    actions = _classifier_actions(
        monkeypatch,
        "Verified source package has fewer than six traceable exact excerpts",
    )

    assert actions == [{
        "verb": "targeted_fetch",
        "focus": "slots",
        "reason": (
            "package gaps: Verified source package has fewer than six traceable exact excerpts"
        ),
    }]


def test_comparison_ship_conversion_is_not_forced_into_locked_ship_story():
    package = {'candidate_excerpts': [{
        'excerpt_id': 'S1-E1',
        'text': 'The previous carrier was HMS Glorious, converted from a battlecruiser.',
        'anton_slot_hints': ['engineering_decision', 'reality'],
    }]}
    signal = pe._package_conversion_signals(package, '91 Ark Royal (1938)')[0]
    assert signal['enforce'] is False
    assert pe._package_conversion_signals(package, 'HMS Glorious')[0]['enforce'] is True


def test_planned_conversion_does_not_assert_actual_use():
    package = {'candidate_excerpts': [{
        'excerpt_id': 'S1-E1',
        'text': 'Pretoria Castle was purchased outright for conversion to an escort carrier.',
        'anton_slot_hints': ['engineering_decision', 'original_problem'],
    }]}
    assert pe._package_conversion_signals(package, 'F61 HMS Pretoria Castle')[0]['enforce'] is False
    package['candidate_excerpts'][0].update(
        text='She was converted and served as a trials and training carrier.',
        anton_slot_hints=['engineering_decision', 'reality'],
    )
    assert pe._package_conversion_signals(package, 'F61 HMS Pretoria Castle')[0]['enforce'] is True
