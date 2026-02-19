"""Tests for audio_sync.transition_engine — transition type selection."""

import pytest

from audio_sync.transition_engine import (
    determine_transition,
    assign_transitions,
)
from audio_sync.config import CROSSFADE_DURATION, STYLE_CHANGE_FADE, ACT_TRANSITION_BLACK


class TestDetermineTransition:
    def test_same_style_same_act_crossfade(self):
        cur = {"style": "dossier", "act": 1}
        nxt = {"style": "dossier", "act": 1}
        t = determine_transition(cur, nxt)
        assert t["type"] == "crossfade"
        assert t["duration"] == CROSSFADE_DURATION

    def test_style_change_longer_crossfade(self):
        cur = {"style": "dossier", "act": 2}
        nxt = {"style": "echo", "act": 2}
        t = determine_transition(cur, nxt)
        assert t["type"] == "crossfade"
        assert t["duration"] == STYLE_CHANGE_FADE

    def test_act_change_dip_to_black(self):
        cur = {"style": "dossier", "act": 1}
        nxt = {"style": "dossier", "act": 2}
        t = determine_transition(cur, nxt)
        assert t["type"] == "dip_to_black"
        assert t["duration"] == ACT_TRANSITION_BLACK

    def test_last_scene_fade_to_black(self):
        cur = {"style": "dossier", "act": 6}
        t = determine_transition(cur, None)
        assert t["type"] == "fade_to_black"

    def test_visual_style_field_supported(self):
        """The pipeline may use 'visual_style' instead of 'style'."""
        cur = {"visual_style": "schema", "parent_act": 3}
        nxt = {"visual_style": "echo", "parent_act": 3}
        t = determine_transition(cur, nxt)
        assert t["type"] == "crossfade"
        assert t["duration"] == STYLE_CHANGE_FADE


class TestAssignTransitions:
    def test_first_scene_fades_from_black(self):
        scenes = [
            {"scene_number": 1, "style": "dossier", "act": 1},
            {"scene_number": 2, "style": "dossier", "act": 1},
        ]
        result = assign_transitions(scenes)
        assert result[0]["transition_in"]["type"] == "fade_from_black"

    def test_all_scenes_get_both_transitions(self):
        scenes = [
            {"scene_number": 1, "style": "dossier", "act": 1},
            {"scene_number": 2, "style": "dossier", "act": 1},
            {"scene_number": 3, "style": "echo", "act": 2},
        ]
        result = assign_transitions(scenes)
        for s in result:
            assert "transition_in" in s
            assert "transition_out" in s

    def test_transition_in_mirrors_previous_out(self):
        scenes = [
            {"scene_number": 1, "style": "dossier", "act": 1},
            {"scene_number": 2, "style": "dossier", "act": 2},
        ]
        result = assign_transitions(scenes)
        assert result[1]["transition_in"]["type"] == result[0]["transition_out"]["type"]
