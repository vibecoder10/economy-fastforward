"""Tests for audio_sync.ken_burns_calculator — per-scene Ken Burns parameters."""

import pytest

from audio_sync.ken_burns_calculator import (
    calculate_ken_burns,
    assign_ken_burns,
)
from audio_sync.config import KEN_BURNS_BASE_DURATION


class TestCalculateKenBurns:
    def test_wide_composition_zooms_in(self):
        kb = calculate_ken_burns("wide", 11.0, scene_index=0)
        assert kb["direction"] == "slow_zoom_in"
        assert kb["start_scale"] == 1.0
        assert kb["end_scale"] == 1.15

    def test_closeup_composition_zooms_out(self):
        kb = calculate_ken_burns("closeup", 11.0, scene_index=0)
        assert kb["direction"] == "slow_zoom_out"
        assert kb["start_scale"] == 1.15
        assert kb["end_scale"] == 1.0

    def test_medium_alternates_pan_direction(self):
        kb_even = calculate_ken_burns("medium", 11.0, scene_index=0)
        kb_odd = calculate_ken_burns("medium", 11.0, scene_index=1)
        # Even index alternates
        assert kb_even["direction"] == "slow_pan_left"
        assert kb_odd["direction"] == "slow_pan_right"

    def test_speed_multiplier_for_long_scene(self):
        kb = calculate_ken_burns("wide", 16.0, scene_index=0)
        expected = round(KEN_BURNS_BASE_DURATION / 16.0, 3)
        assert kb["speed_multiplier"] == expected

    def test_speed_multiplier_for_short_scene(self):
        """Short scenes (< 3s) are clamped to min_display_seconds."""
        kb = calculate_ken_burns("wide", 2.0, scene_index=0)
        expected = round(KEN_BURNS_BASE_DURATION / 3.0, 3)
        assert kb["speed_multiplier"] == expected

    def test_unknown_composition_defaults_to_zoom_in(self):
        kb = calculate_ken_burns("unknown_type", 11.0, scene_index=0)
        assert kb["direction"] == "slow_zoom_in"

    def test_low_angle_tilts_up(self):
        kb = calculate_ken_burns("low_angle", 11.0, scene_index=0)
        assert kb["direction"] == "slow_tilt_up"


class TestAssignKenBurns:
    def test_assigns_to_all_scenes(self):
        scenes = [
            {"scene_number": 1, "composition": "wide", "display_duration": 8.0},
            {"scene_number": 2, "composition": "closeup", "display_duration": 12.0},
        ]
        result = assign_ken_burns(scenes)
        for s in result:
            assert "ken_burns" in s
            assert "direction" in s["ken_burns"]
            assert "speed_multiplier" in s["ken_burns"]

    def test_composition_hint_fallback(self):
        """Should also read 'composition_hint' if 'composition' is missing."""
        scenes = [
            {"scene_number": 1, "composition_hint": "environmental", "display_duration": 10.0},
        ]
        result = assign_ken_burns(scenes)
        assert result[0]["ken_burns"]["direction"] in ("slow_pan_left", "slow_pan_right")
