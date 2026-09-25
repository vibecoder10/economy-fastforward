"""A longer video gets more machines, not longer paragraphs.

Measured 2026-09-25: one DvsU v2 paragraph (~117 words) is ~52 s of narration,
so a 20-minute video needs 23 machines, not 20.

Run: cd storyengine/backend && ./venv/bin/python -m pytest tests/test_roster_pacing_default.py -q
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from roster_selection import (  # noqa: E402
    DEFAULT_MINUTES_PER_MACHINE, configured_pacing, selection_settings, selection_target,
)


def test_new_20_minute_video_gets_23_machines():
    assert configured_pacing({}) == DEFAULT_MINUTES_PER_MACHINE
    assert selection_target(20, configured_pacing({})) == 23


def test_creator_setting_wins():
    payload = {"roster_settings": {"minutes_per_machine": 2},
               "roster_selection": {"settings": {"minutes_per_machine": 1}}}
    assert configured_pacing(payload) == 2


def test_saved_roster_keeps_its_own_pace():
    # An old roster picked at 1 min/machine must still read as current,
    # or the pre-research gate blocks it ("inputs changed").
    stored = selection_settings(20, 1)
    payload = {"roster_selection": {"settings": stored}}
    assert selection_settings(20, configured_pacing(payload)) == stored
