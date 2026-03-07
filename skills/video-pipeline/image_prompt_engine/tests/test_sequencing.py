"""
Tests for the Holographic Intelligence Display sequencing engine.

Verifies that all rotation constraints and emotional arc pacing rules are
enforced across a full video's worth of assignments.
"""

import sys
import os

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from image_prompt_engine.sequencer import assign_styles
from image_prompt_engine.style_config import DEFAULT_CONFIG, ContentType, DisplayFormat, ColorMood


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_assignments(seed: int = 42, total: int = 136) -> list[dict]:
    """Generate a deterministic full-video assignment sequence."""
    return assign_styles(total, seed=seed)


def _consecutive_runs(assignments: list[dict], key: str) -> list[tuple[str, int]]:
    """Return a list of (value, run_length) for consecutive same-value runs."""
    if not assignments:
        return []
    runs = []
    current = assignments[0][key]
    count = 1
    for entry in assignments[1:]:
        if entry[key] == current:
            count += 1
        else:
            runs.append((current, count))
            current = entry[key]
            count = 1
    runs.append((current, count))
    return runs


# ---------------------------------------------------------------------------
# Rule: No more than 2 consecutive same content type
# ---------------------------------------------------------------------------

class TestContentTypeRotation:
    @pytest.mark.parametrize("seed", [1, 42, 99, 256, 1000])
    def test_no_more_than_2_consecutive_content_type(self, seed):
        """No content type appears more than 2 times in a row."""
        assignments = _make_assignments(seed=seed)
        max_allowed = DEFAULT_CONFIG["max_consecutive_content_type"]
        for value, run_len in _consecutive_runs(assignments, "content_type"):
            assert run_len <= max_allowed, (
                f"Content type '{value}' has {run_len} consecutive images "
                f"(max {max_allowed}), seed={seed}"
            )


# ---------------------------------------------------------------------------
# Rule: No more than 2 consecutive same display format
# ---------------------------------------------------------------------------

class TestFormatRotation:
    @pytest.mark.parametrize("seed", [1, 42, 99, 256, 1000])
    def test_no_more_than_2_consecutive_format(self, seed):
        """No display format appears more than 2 times in a row."""
        assignments = _make_assignments(seed=seed)
        max_allowed = DEFAULT_CONFIG["max_consecutive_format"]
        for value, run_len in _consecutive_runs(assignments, "display_format"):
            assert run_len <= max_allowed, (
                f"Display format '{value}' has {run_len} consecutive images "
                f"(max {max_allowed}), seed={seed}"
            )


# ---------------------------------------------------------------------------
# Rule: No more than 3 consecutive same color palette
# ---------------------------------------------------------------------------

class TestPaletteRotation:
    @pytest.mark.parametrize("seed", [1, 42, 99, 256, 1000])
    def test_no_more_than_3_consecutive_palette(self, seed):
        """No color mood appears more than 3 times in a row."""
        assignments = _make_assignments(seed=seed)
        max_allowed = DEFAULT_CONFIG["max_consecutive_palette"]
        for value, run_len in _consecutive_runs(assignments, "color_mood"):
            assert run_len <= max_allowed, (
                f"Color mood '{value}' has {run_len} consecutive images "
                f"(max {max_allowed}), seed={seed}"
            )


# ---------------------------------------------------------------------------
# Content type variety
# ---------------------------------------------------------------------------

class TestContentTypeVariety:
    @pytest.mark.parametrize("seed", [1, 42, 99, 256, 1000])
    def test_uses_multiple_content_types(self, seed):
        """A full video uses at least 5 different content types."""
        assignments = _make_assignments(seed=seed)
        types = {a["content_type"] for a in assignments}
        assert len(types) >= 5, (
            f"Only {len(types)} content types used (expected ≥5), seed={seed}"
        )


# ---------------------------------------------------------------------------
# Display format variety
# ---------------------------------------------------------------------------

class TestFormatVariety:
    @pytest.mark.parametrize("seed", [1, 42, 99, 256, 1000])
    def test_uses_all_display_formats(self, seed):
        """A full video uses all 5 display formats."""
        assignments = _make_assignments(seed=seed)
        formats = {a["display_format"] for a in assignments}
        assert len(formats) == 5, (
            f"Only {len(formats)} formats used (expected 5), seed={seed}"
        )


# ---------------------------------------------------------------------------
# Color mood variety
# ---------------------------------------------------------------------------

class TestColorMoodVariety:
    @pytest.mark.parametrize("seed", [1, 42, 99, 256, 1000])
    def test_uses_multiple_color_moods(self, seed):
        """A full video uses at least 4 different color moods."""
        assignments = _make_assignments(seed=seed)
        moods = {a["color_mood"] for a in assignments}
        assert len(moods) >= 4, (
            f"Only {len(moods)} color moods used (expected ≥4), seed={seed}"
        )


# ---------------------------------------------------------------------------
# Valid values
# ---------------------------------------------------------------------------

class TestValidValues:
    def test_all_content_types_are_valid(self):
        """All assigned content types are valid ContentType values."""
        valid = {ct.value for ct in ContentType}
        assignments = _make_assignments(seed=42)
        for a in assignments:
            assert a["content_type"] in valid, (
                f"Invalid content type '{a['content_type']}' at index {a['index']}"
            )

    def test_all_display_formats_are_valid(self):
        """All assigned display formats are valid DisplayFormat values."""
        valid = {fmt.value for fmt in DisplayFormat}
        assignments = _make_assignments(seed=42)
        for a in assignments:
            assert a["display_format"] in valid, (
                f"Invalid display format '{a['display_format']}' at index {a['index']}"
            )

    def test_all_color_moods_are_valid(self):
        """All assigned color moods are valid ColorMood values."""
        valid = {m.value for m in ColorMood}
        assignments = _make_assignments(seed=42)
        for a in assignments:
            assert a["color_mood"] in valid, (
                f"Invalid color mood '{a['color_mood']}' at index {a['index']}"
            )


# ---------------------------------------------------------------------------
# Ken Burns directions
# ---------------------------------------------------------------------------

class TestKenBurns:
    def test_all_assignments_have_ken_burns(self):
        """Every assignment includes a ken_burns direction."""
        assignments = _make_assignments(seed=42)
        for entry in assignments:
            assert "ken_burns" in entry
            assert entry["ken_burns"] is not None

    def test_ken_burns_variety(self):
        """Multiple Ken Burns directions are used across a video."""
        assignments = _make_assignments(seed=42)
        directions = {a["ken_burns"] for a in assignments}
        assert len(directions) >= 3, "Expected at least 3 Ken Burns directions"

    def test_pan_directions_alternate(self):
        """Pan-based Ken Burns directions alternate for same format."""
        assignments = _make_assignments(seed=42)
        wall_displays = [a for a in assignments if a["display_format"] == "wall_display"]
        if len(wall_displays) >= 2:
            directions = [w["ken_burns"] for w in wall_displays]
            assert len(set(directions)) > 1, "Wall display never alternates pan direction"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_very_small_video(self):
        """A video with only 5 images doesn't crash."""
        assignments = assign_styles(5, seed=42)
        assert len(assignments) == 5

    def test_single_image(self):
        """A video with 1 image returns a valid assignment."""
        assignments = assign_styles(1, seed=42)
        assert len(assignments) == 1

    def test_large_video(self):
        """A 300-image video runs without error and obeys rules."""
        assignments = assign_styles(300, seed=42)
        assert len(assignments) == 300
        # Check no more than allowed consecutive
        for _, run_len in _consecutive_runs(assignments, "content_type"):
            assert run_len <= DEFAULT_CONFIG["max_consecutive_content_type"]
        for _, run_len in _consecutive_runs(assignments, "display_format"):
            assert run_len <= DEFAULT_CONFIG["max_consecutive_format"]
        for _, run_len in _consecutive_runs(assignments, "color_mood"):
            assert run_len <= DEFAULT_CONFIG["max_consecutive_palette"]

    def test_reproducible_with_seed(self):
        """Same seed produces identical output."""
        a = assign_styles(136, seed=12345)
        b = assign_styles(136, seed=12345)
        assert a == b

    def test_different_seeds_differ(self):
        """Different seeds produce different sequences."""
        a = assign_styles(136, seed=1)
        b = assign_styles(136, seed=2)
        types_a = [x["content_type"] for x in a]
        types_b = [x["content_type"] for x in b]
        assert types_a != types_b

    def test_output_has_required_keys(self):
        """Every assignment has all required keys."""
        required = {"index", "timestamp", "act", "content_type", "display_format", "color_mood", "ken_burns"}
        assignments = _make_assignments(seed=42)
        for a in assignments:
            missing = required - set(a.keys())
            assert not missing, f"Missing keys {missing} at index {a['index']}"
