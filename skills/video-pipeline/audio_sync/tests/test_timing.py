"""Tests for audio_sync.timing_adjuster — display time rules."""

import pytest

from audio_sync.timing_adjuster import (
    apply_pre_roll,
    apply_post_hold,
    enforce_minimum_display,
    enforce_maximum_display,
    enforce_max_image_duration,
    resolve_overlaps,
    compute_display_durations,
    adjust_timing,
)


# ---------------------------------------------------------------------------
# Pre-roll
# ---------------------------------------------------------------------------

class TestPreRoll:
    def test_standard_pre_roll(self):
        scenes = [{"start_time": 5.0, "end_time": 10.0}]
        result = apply_pre_roll(scenes, pre_roll=0.3)
        assert result[0]["display_start"] == 4.7

    def test_pre_roll_clamped_to_zero(self):
        scenes = [{"start_time": 0.1, "end_time": 5.0}]
        result = apply_pre_roll(scenes, pre_roll=0.3)
        assert result[0]["display_start"] == 0.0

    def test_none_start_time(self):
        scenes = [{"start_time": None, "end_time": None}]
        result = apply_pre_roll(scenes, pre_roll=0.3)
        assert result[0]["display_start"] == 0.0


# ---------------------------------------------------------------------------
# Post-hold
# ---------------------------------------------------------------------------

class TestPostHold:
    def test_standard_post_hold(self):
        scenes = [
            {"start_time": 0.0, "end_time": 5.0, "display_start": 0.0},
            {"start_time": 6.0, "end_time": 10.0, "display_start": 5.7},
        ]
        result = apply_post_hold(scenes, post_hold=0.5)
        assert result[0]["display_end"] == 5.5

    def test_post_hold_clamped_by_next_scene(self):
        scenes = [
            {"start_time": 0.0, "end_time": 5.0, "display_start": 0.0},
            {"start_time": 5.1, "end_time": 10.0, "display_start": 4.8},
        ]
        result = apply_post_hold(scenes, post_hold=0.5)
        # 5.0 + 0.5 = 5.5 > 4.8 (next display_start), so clamp to 4.8
        assert result[0]["display_end"] == 4.8

    def test_last_scene_uses_full_post_hold(self):
        scenes = [
            {"start_time": 10.0, "end_time": 15.0, "display_start": 9.7},
        ]
        result = apply_post_hold(scenes, post_hold=0.5)
        assert result[0]["display_end"] == 15.5


# ---------------------------------------------------------------------------
# Minimum display
# ---------------------------------------------------------------------------

class TestMinimumDisplay:
    def test_short_scene_extended(self):
        scenes = [
            {"display_start": 0.0, "display_end": 1.0},
            {"display_start": 2.0, "display_end": 8.0},
        ]
        result = enforce_minimum_display(scenes, min_seconds=3.0)
        assert result[0]["display_end"] == 3.0

    def test_already_long_enough(self):
        scenes = [
            {"display_start": 0.0, "display_end": 5.0},
        ]
        result = enforce_minimum_display(scenes, min_seconds=3.0)
        assert result[0]["display_end"] == 5.0

    def test_extension_shifts_next_scene(self):
        scenes = [
            {"display_start": 0.0, "display_end": 1.0},
            {"display_start": 1.5, "display_end": 8.0},
        ]
        result = enforce_minimum_display(scenes, min_seconds=3.0)
        # Scene 1 extended to 3.0, which pushes scene 2 start to 3.0
        assert result[0]["display_end"] == 3.0
        assert result[1]["display_start"] == 3.0


# ---------------------------------------------------------------------------
# Maximum display
# ---------------------------------------------------------------------------

class TestMaximumDisplay:
    def test_long_scene_clamped(self):
        scenes = [
            {"display_start": 0.0, "display_end": 25.0},
        ]
        result = enforce_maximum_display(scenes, max_seconds=18.0)
        assert result[0]["display_end"] == 18.0

    def test_normal_scene_unchanged(self):
        scenes = [
            {"display_start": 0.0, "display_end": 10.0},
        ]
        result = enforce_maximum_display(scenes, max_seconds=18.0)
        assert result[0]["display_end"] == 10.0


# ---------------------------------------------------------------------------
# Overlap resolution
# ---------------------------------------------------------------------------

class TestResolveOverlaps:
    def test_overlapping_scenes_fixed(self):
        scenes = [
            {"display_start": 0.0, "display_end": 6.0},
            {"display_start": 5.0, "display_end": 10.0},
        ]
        result = resolve_overlaps(scenes)
        assert result[1]["display_start"] == 6.0

    def test_no_overlap_unchanged(self):
        scenes = [
            {"display_start": 0.0, "display_end": 5.0},
            {"display_start": 5.0, "display_end": 10.0},
        ]
        result = resolve_overlaps(scenes)
        assert result[1]["display_start"] == 5.0


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

class TestAdjustTiming:
    def test_full_pipeline(self):
        scenes = [
            {"scene_number": 1, "start_time": 0.5, "end_time": 5.0},
            {"scene_number": 2, "start_time": 5.2, "end_time": 12.0},
            {"scene_number": 3, "start_time": 12.5, "end_time": 14.0},
        ]
        result = adjust_timing(scenes)

        # All scenes should have display_start, display_end, display_duration
        for s in result:
            assert "display_start" in s
            assert "display_end" in s
            assert "display_duration" in s
            assert s["display_duration"] >= 3.0  # minimum
            assert s["display_duration"] <= 18.0  # maximum

        # No overlaps
        for i in range(len(result) - 1):
            assert result[i]["display_end"] <= result[i + 1]["display_start"] + 0.001


# ---------------------------------------------------------------------------
# Per-image max duration enforcement
# ---------------------------------------------------------------------------

class TestEnforceMaxImageDuration:
    def test_no_outliers_unchanged(self):
        """Images within the cap are left untouched."""
        scene = [
            {"duration": 8.0, "display_start": 0.0, "display_end": 8.0},
            {"duration": 10.0, "display_start": 8.0, "display_end": 18.0},
            {"duration": 7.0, "display_start": 18.0, "display_end": 25.0},
        ]
        result = enforce_max_image_duration(scene, max_seconds=15.0)
        assert result[0]["duration"] == 8.0
        assert result[1]["duration"] == 10.0
        assert result[2]["duration"] == 7.0

    def test_outlier_triggers_even_redistribution(self):
        """One 47s image among 5 causes even split of total time."""
        scene = [
            {"duration": 47.5, "display_start": 0.0, "display_end": 47.5},
            {"duration": 60.8, "display_start": 47.5, "display_end": 108.3},
            {"duration": 3.8, "display_start": 108.3, "display_end": 112.1},
            {"duration": 7.4, "display_start": 112.1, "display_end": 119.5},
            {"duration": 8.4, "display_start": 119.5, "display_end": 127.9},
        ]
        result = enforce_max_image_duration(scene, max_seconds=15.0)
        # Total was 127.9s, evenly = 25.58 → capped at 15s each
        for entry in result:
            assert entry["duration"] <= 15.0
            assert entry["duration"] >= 1.0

        # All images get the same duration
        durations = [e["duration"] for e in result]
        assert len(set(durations)) == 1

    def test_display_start_end_are_sequential(self):
        """After redistribution, display_start/end form a contiguous timeline."""
        scene = [
            {"duration": 30.0, "display_start": 5.0, "display_end": 35.0},
            {"duration": 5.0, "display_start": 35.0, "display_end": 40.0},
            {"duration": 5.0, "display_start": 40.0, "display_end": 45.0},
        ]
        result = enforce_max_image_duration(scene, max_seconds=15.0)
        # Should start at original scene start (5.0)
        assert result[0]["display_start"] == 5.0
        # Each entry's end == next entry's start
        for i in range(len(result) - 1):
            assert abs(result[i]["display_end"] - result[i + 1]["display_start"]) < 0.01

    def test_empty_list_returns_empty(self):
        assert enforce_max_image_duration([]) == []

    def test_single_image_capped(self):
        """A lone image over the cap gets clamped."""
        scene = [
            {"duration": 25.0, "display_start": 0.0, "display_end": 25.0},
        ]
        result = enforce_max_image_duration(scene, max_seconds=15.0)
        assert result[0]["duration"] == 15.0

    def test_even_split_within_cap_not_capped(self):
        """When even split is under max, images keep the even duration."""
        scene = [
            {"duration": 20.0, "display_start": 0.0, "display_end": 20.0},
            {"duration": 4.0, "display_start": 20.0, "display_end": 24.0},
        ]
        result = enforce_max_image_duration(scene, max_seconds=15.0)
        # Total 24s / 2 = 12s each → under 15s cap, so 12s
        assert result[0]["duration"] == 12.0
        assert result[1]["duration"] == 12.0
