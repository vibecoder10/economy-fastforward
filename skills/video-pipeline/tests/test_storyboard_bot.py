"""Tests for storyboard bot: model profiles, duration binning, grid grouping, panel extraction."""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.channel_profile import (
    DEFAULT_VIDEO_MODEL,
    GROK_IMAGINE,
    MODEL_REGISTRY,
    VEO_31_FAST,
    load_model_profile,
)
from storyboard.bot import (
    _make_segment,
    assign_clip_durations,
    calculate_grid_count,
    calculate_video_cost,
    extract_contact_sheet_prompt,
    group_segments_into_grids,
    parse_keyframe_metadata,
    segment_script_into_beats,
)


# =============================================================================
# Model Profile Tests
# =============================================================================


class TestModelProfile:
    def test_registry_has_all_models(self):
        assert len(MODEL_REGISTRY) == 7
        assert "grok-imagine" in MODEL_REGISTRY
        assert "seedance-2-fast" in MODEL_REGISTRY
        assert "veo-3.1-fast" in MODEL_REGISTRY
        assert "veo-3.1-quality" in MODEL_REGISTRY
        assert "kling-3.0-pro" in MODEL_REGISTRY
        assert "runway-gen4-turbo" in MODEL_REGISTRY
        assert "hailuo-2.3-standard" in MODEL_REGISTRY

    def test_wired_flag_matches_live_generation_path(self):
        # Single source of truth for the Scenes clip-model dropdown (GET
        # /api/models) AND pipeline_executor's gate — see
        # tasks/storyengine-wiring-fix-checklist.md §0.2.
        wired_ids = {m for m, p in MODEL_REGISTRY.items() if p.wired}
        assert wired_ids == {"grok-imagine", "seedance-2-fast", "veo-3.1-fast", "veo-3.1-quality"}

    def test_default_model_is_grok(self):
        assert DEFAULT_VIDEO_MODEL == "grok-imagine"

    def test_load_model_profile_default(self):
        profile = load_model_profile()
        assert profile.model_id == "grok-imagine"
        assert profile.display_name == "Grok Imagine"

    def test_load_model_profile_override(self):
        profile = load_model_profile({"Video Model": "veo-3.1-fast"})
        assert profile.model_id == "veo-3.1-fast"

    def test_load_model_profile_invalid_falls_back(self):
        profile = load_model_profile({"Video Model": "nonexistent-model"})
        assert profile.model_id == "grok-imagine"

    def test_load_model_profile_none_record(self):
        profile = load_model_profile(None)
        assert profile.model_id == "grok-imagine"

    def test_grok_durations(self):
        assert GROK_IMAGINE.durations == [6, 10, 15]
        assert GROK_IMAGINE.preferred_max == 10
        assert GROK_IMAGINE.allow_max_override is True

    def test_veo_fixed_duration(self):
        assert VEO_31_FAST.durations == [8]
        assert VEO_31_FAST.allow_max_override is False

    def test_all_models_have_costs(self):
        for model_id, model in MODEL_REGISTRY.items():
            for d in model.durations:
                assert d in model.cost_per_clip, (
                    f"{model_id} missing cost for {d}s"
                )


# =============================================================================
# Duration Binning Tests
# =============================================================================


class TestAssignClipDurations:
    def test_grok_basic_assignment(self):
        segments = [
            _make_segment("Short clip.", 12),           # 4.8s -> 6s
            _make_segment("Medium clip with words.", 20),  # 8.0s -> 10s
            _make_segment("Long clip. " * 5, 35),       # 14.0s -> 15s
        ]
        result = assign_clip_durations(segments, GROK_IMAGINE)
        assert result[0]["assigned_duration"] == 6
        assert result[1]["assigned_duration"] == 10
        assert result[2]["assigned_duration"] == 15

    def test_veo_fixed_8s(self):
        segments = [
            _make_segment("Five seconds.", 12),
            _make_segment("Eight seconds.", 20),
        ]
        result = assign_clip_durations(segments, VEO_31_FAST)
        assert all(s["assigned_duration"] == 8 for s in result)

    def test_merge_short_segments(self):
        """Segments below 60% of min duration merge with previous."""
        segments = [
            _make_segment("Normal sentence here.", 15),  # 6s -> 6s
            _make_segment("Tiny.", 2),                    # 0.8s < 3.6s, merges
        ]
        result = assign_clip_durations(segments, GROK_IMAGINE)
        assert len(result) == 1  # Merged into one
        assert result[0]["word_count"] == 17

    def test_first_short_segment_standalone(self):
        """First segment can't merge left, so it stays standalone."""
        segments = [
            _make_segment("Hi.", 2),  # 0.8s but nothing to merge with
        ]
        result = assign_clip_durations(segments, GROK_IMAGINE)
        assert len(result) == 1
        assert result[0]["assigned_duration"] == 6

    def test_split_long_segments(self):
        """Segments exceeding max duration are split at sentence boundaries."""
        # 10 sentences × ~8 words each = ~80 words = 32s > 15s max
        long_text = ". ".join(
            f"This is sentence number {i} with extra words" for i in range(10)
        ) + "."
        word_count = len(long_text.split())
        segments = [_make_segment(long_text, word_count)]
        result = assign_clip_durations(segments, GROK_IMAGINE)
        assert len(result) >= 2
        assert all(s["assigned_duration"] <= 15 for s in result)

    def test_preferred_max_avoids_15s(self):
        """11s spoken should get 15s (allow_max_override) not split."""
        segments = [
            _make_segment("Eleven second sentence with enough words.", 28),  # 11.2s
        ]
        result = assign_clip_durations(segments, GROK_IMAGINE)
        # 11.2s > 10s preferred_max but <= 15s with override
        assert result[0]["assigned_duration"] == 15

    def test_cost_assigned(self):
        segments = [_make_segment("Normal.", 15)]
        result = assign_clip_durations(segments, GROK_IMAGINE)
        # C09a: 6s tier priced at Kie's published $0.015/s (720p) rate = 0.09,
        # not the prior unsourced 0.10.
        assert result[0]["estimated_cost"] == 0.09  # 6s tier


# =============================================================================
# Video Cost Calculation Tests
# =============================================================================


class TestCalculateVideoCost:
    def test_basic_cost(self):
        segments = [
            {"assigned_duration": 6, "estimated_cost": 0.10},
            {"assigned_duration": 6, "estimated_cost": 0.10},
            {"assigned_duration": 10, "estimated_cost": 0.15},
        ]
        cost = calculate_video_cost(segments, GROK_IMAGINE)
        assert cost["total_clips"] == 3
        assert abs(cost["total_cost"] - 0.35) < 0.01
        assert cost["by_duration"][6]["count"] == 2
        assert cost["by_duration"][10]["count"] == 1

    def test_total_duration(self):
        segments = [
            {"assigned_duration": 6, "estimated_cost": 0.10},
            {"assigned_duration": 10, "estimated_cost": 0.15},
        ]
        cost = calculate_video_cost(segments, GROK_IMAGINE)
        assert cost["total_duration_seconds"] == 16


# =============================================================================
# Grid Grouping Tests
# =============================================================================


class TestGroupSegmentsIntoGrids:
    def test_exact_multiple(self):
        segments = list(range(18))
        grids = group_segments_into_grids(segments)
        assert len(grids) == 2
        assert grids[0]["panel_count"] == 9
        assert grids[0]["black_panels"] == 0

    def test_remainder(self):
        segments = list(range(23))
        grids = group_segments_into_grids(segments)
        assert len(grids) == 3
        assert grids[2]["panel_count"] == 5
        assert grids[2]["black_panels"] == 4

    def test_single_grid(self):
        segments = list(range(7))
        grids = group_segments_into_grids(segments)
        assert len(grids) == 1
        assert grids[0]["panel_count"] == 7

    def test_empty(self):
        grids = group_segments_into_grids([])
        assert len(grids) == 0


# =============================================================================
# Blank Panel Detection Tests
# =============================================================================


class TestIsBlankPanel:
    def test_black_panel(self):
        from PIL import Image
        from storyboard.bot import is_blank_panel

        # Pure black image
        img = Image.new("RGB", (100, 100), (0, 0, 0))
        assert is_blank_panel(img) is True

    def test_non_black_panel(self):
        from PIL import Image
        from storyboard.bot import is_blank_panel

        img = Image.new("RGB", (100, 100), (128, 128, 128))
        assert is_blank_panel(img) is False

    def test_near_black_panel(self):
        from PIL import Image
        from storyboard.bot import is_blank_panel

        img = Image.new("RGB", (100, 100), (10, 10, 10))
        assert is_blank_panel(img) is True  # Mean 10 < threshold 15


# =============================================================================
# Panel Extraction Tests
# =============================================================================


class TestExtractPanels:
    def test_extract_9_panels(self):
        """Full 3x3 grid with all panels colored."""
        from PIL import Image
        from storyboard.bot import extract_panels

        # Create a 300x300 grid with 9 colored panels (100x100 each)
        img = Image.new("RGB", (300, 300), (0, 0, 0))
        colors = [
            (255, 0, 0), (0, 255, 0), (0, 0, 255),
            (255, 255, 0), (255, 0, 255), (0, 255, 255),
            (128, 0, 0), (0, 128, 0), (0, 0, 128),
        ]
        for idx, color in enumerate(colors):
            row, col = idx // 3, idx % 3
            for x in range(col * 100, (col + 1) * 100):
                for y in range(row * 100, (row + 1) * 100):
                    img.putpixel((x, y), color)

        with tempfile.TemporaryDirectory() as tmpdir:
            grid_path = os.path.join(tmpdir, "grid.png")
            img.save(grid_path)
            panels = extract_panels(grid_path, tmpdir, 1, 9)
            assert len(panels) == 9
            assert all(os.path.exists(p) for p in panels)

    def test_extract_with_black_panels(self):
        """Grid with 5 colored panels and 4 black."""
        from PIL import Image
        from storyboard.bot import extract_panels

        img = Image.new("RGB", (300, 300), (0, 0, 0))  # All black
        # Fill first 5 panels with color
        for idx in range(5):
            row, col = idx // 3, idx % 3
            for x in range(col * 100 + 5, (col + 1) * 100 - 5):
                for y in range(row * 100 + 5, (row + 1) * 100 - 5):
                    img.putpixel((x, y), (200, 100, 50))

        with tempfile.TemporaryDirectory() as tmpdir:
            grid_path = os.path.join(tmpdir, "grid.png")
            img.save(grid_path)
            panels = extract_panels(grid_path, tmpdir, 1, 5)
            assert len(panels) == 5


# =============================================================================
# Keyframe Parser Tests
# =============================================================================


class TestParseKeyframeMetadata:
    def test_parse_two_keyframes(self):
        text = """
## KEYFRAMES
[KF1 | ELS | 2.5]
- Composition: Wide shot of war room
- Action/beat: Strategic meeting begins
- Camera: Eye level, static
- Lens/DoF: 24mm, deep, full room
- Lighting & grade: Cool blue ambient
- Sound/atmos: Air conditioning hum

[KF2 | MCU | 1.5]
- Composition: Close-up of leader
- Action/beat: Leader reviews documents
- Camera: Slight low angle, static
- Lens/DoF: 85mm, shallow, face
- Lighting & grade: Warm key from window
- Sound/atmos: Paper rustling
"""
        kfs = parse_keyframe_metadata(text)
        assert len(kfs) == 2
        assert kfs[0]["shot_type"] == "ELS"
        assert kfs[0]["duration_seconds"] == 2.5
        assert "Wide shot" in kfs[0]["composition"]
        assert kfs[1]["shot_type"] == "MCU"
        assert "Leader reviews" in kfs[1]["action_beat"]

    def test_empty_text(self):
        kfs = parse_keyframe_metadata("No keyframes here")
        assert kfs == []


# =============================================================================
# Contact Sheet Prompt Extraction Tests
# =============================================================================


class TestExtractContactSheetPrompt:
    def test_basic_extraction(self):
        text = """
## KEYFRAMES
Some keyframes...

## CONTACT SHEET PROMPT
Cinematic illustration in muted tones. A 3x3 grid showing...
"""
        result = extract_contact_sheet_prompt(text)
        assert "Cinematic illustration" in result
        assert "3x3 grid" in result

    def test_missing_section_raises(self):
        with pytest.raises(ValueError):
            extract_contact_sheet_prompt("No contact sheet here")


# =============================================================================
# Grid Count Calculator Tests
# =============================================================================


class TestCalculateGridCount:
    def test_12_min_video(self):
        result = calculate_grid_count(12, 10)
        assert result["grid_count"] == 8
        assert result["total_panels"] == 72

    def test_5_min_video(self):
        result = calculate_grid_count(5, 10)
        assert result["grid_count"] == 4

    def test_cost_calculation(self):
        result = calculate_grid_count(12, 10)
        assert abs(result["total_cost"] - 4.08) < 0.01


# =============================================================================
# Beat Segmentation Tests
# =============================================================================


class TestSegmentScriptIntoBeats:
    def test_basic_segmentation(self):
        records = [
            {"Scene": i, "Scene text": "word " * 30}
            for i in range(1, 11)
        ]
        beats = segment_script_into_beats(records)
        assert len(beats) >= 2
        assert all(b["word_count"] > 0 for b in beats)

    def test_single_scene(self):
        records = [{"Scene": 1, "Scene text": "Short scene."}]
        beats = segment_script_into_beats(records)
        assert len(beats) == 1

    def test_scene_boundary_respected(self):
        records = [
            {"Scene": 1, "Scene text": "word " * 80},
            {"Scene": 2, "Scene text": "word " * 80},
        ]
        beats = segment_script_into_beats(records)
        # Each scene is 80 words = 32s. Two scenes = 64s > 40s target.
        # Should split into 2 beats.
        assert len(beats) == 2
