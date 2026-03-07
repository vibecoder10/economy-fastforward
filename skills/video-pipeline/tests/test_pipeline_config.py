"""Tests for pipeline_config.py — VideoConfig and derived values."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline_config import VideoConfig, ACT_TEMPLATES, get_act_word_targets


class TestVideoConfigBasics:
    """Input validation and basic instantiation."""

    def test_default_config(self):
        config = VideoConfig()
        assert config.video_length_minutes == 10
        assert config.clip_duration_seconds == 10

    def test_minimum_length(self):
        config = VideoConfig(video_length_minutes=3, clip_duration_seconds=6)
        assert config.total_seconds == 180
        assert config.total_clips == 30

    def test_maximum_length(self):
        config = VideoConfig(video_length_minutes=30, clip_duration_seconds=10)
        assert config.total_seconds == 1800
        assert config.total_clips == 180

    def test_invalid_length_too_short(self):
        with pytest.raises(ValueError, match="Minimum"):
            VideoConfig(video_length_minutes=2)

    def test_invalid_length_too_long(self):
        with pytest.raises(ValueError, match="Maximum"):
            VideoConfig(video_length_minutes=31)

    def test_invalid_clip_duration(self):
        with pytest.raises(ValueError, match="Clip duration"):
            VideoConfig(video_length_minutes=10, clip_duration_seconds=8)

    def test_clip_duration_6(self):
        config = VideoConfig(video_length_minutes=10, clip_duration_seconds=6)
        assert config.words_per_clip == 15
        assert config.total_clips == 100

    def test_clip_duration_10(self):
        config = VideoConfig(video_length_minutes=10, clip_duration_seconds=10)
        assert config.words_per_clip == 25
        assert config.total_clips == 60


class TestReferenceConfigurations:
    """Verify all reference configurations from the PRD."""

    def test_5min_6s(self):
        config = VideoConfig(5, 6)
        assert config.total_clips == 50
        assert config.total_script_words == 750
        assert config.act_count == 3

    def test_5min_10s(self):
        config = VideoConfig(5, 10)
        assert config.total_clips == 30
        assert config.total_script_words == 750
        assert config.act_count == 3

    def test_10min_6s(self):
        config = VideoConfig(10, 6)
        assert config.total_clips == 100
        assert config.total_script_words == 1500
        assert config.act_count == 5

    def test_10min_10s(self):
        config = VideoConfig(10, 10)
        assert config.total_clips == 60
        assert config.total_script_words == 1500
        assert config.act_count == 5

    def test_15min_10s(self):
        config = VideoConfig(15, 10)
        assert config.total_clips == 90
        assert config.total_script_words == 2250
        assert config.act_count == 6

    def test_20min_10s(self):
        config = VideoConfig(20, 10)
        assert config.total_clips == 120
        assert config.total_script_words == 3000
        assert config.act_count == 6


class TestDerivedValues:
    """Computed values are consistent."""

    def test_script_word_bounds(self):
        config = VideoConfig(10, 10)
        assert config.script_min_words == int(1500 * 0.9)
        assert config.script_max_words == int(1500 * 1.1)
        assert config.script_min_words < config.total_script_words < config.script_max_words

    def test_segment_word_tolerance(self):
        config = VideoConfig(10, 10)
        assert config.segment_min_words == 22  # 25 - 3
        assert config.segment_max_words == 28  # 25 + 3

    def test_act_count_scaling(self):
        """Act count increases with video length."""
        assert VideoConfig(3).act_count == 3
        assert VideoConfig(5).act_count == 3
        assert VideoConfig(6).act_count == 3
        assert VideoConfig(8).act_count == 4
        assert VideoConfig(10).act_count == 5
        assert VideoConfig(12).act_count == 6
        assert VideoConfig(20).act_count == 6

    def test_intensity_distribution(self):
        config = VideoConfig(10, 10)
        total = config.high_movement_clips + config.medium_movement_clips + config.low_movement_clips
        assert total == config.total_clips
        assert config.high_movement_clips >= 3

    def test_cost_estimates_positive(self):
        config = VideoConfig(10, 10)
        assert config.image_cost > 0
        assert config.animation_cost > 0
        assert config.total_estimated_cost > config.image_cost


class TestSerialization:
    """to_dict, summary, from_airtable_record."""

    def test_to_dict(self):
        config = VideoConfig(10, 10)
        d = config.to_dict()
        assert d["video_length_minutes"] == 10
        assert d["clip_duration_seconds"] == 10
        assert d["total_clips"] == 60
        assert "estimated_cost" in d

    def test_summary(self):
        config = VideoConfig(10, 10)
        s = config.summary()
        assert "10min" in s
        assert "60" in s  # total clips

    def test_from_airtable_record_with_values(self):
        record = {"fields": {"Video Length (min)": 15, "Clip Duration (s)": "10"}}
        config = VideoConfig.from_airtable_record(record)
        assert config.video_length_minutes == 15
        assert config.clip_duration_seconds == 10

    def test_from_airtable_record_empty_fields(self):
        """Empty Airtable fields should use defaults."""
        record = {"fields": {}}
        config = VideoConfig.from_airtable_record(record)
        assert config.video_length_minutes == 10
        assert config.clip_duration_seconds == 10

    def test_from_airtable_flat_dict(self):
        """Record without 'fields' wrapper."""
        record = {"Video Length (min)": 5, "Clip Duration (s)": 6}
        config = VideoConfig.from_airtable_record(record)
        assert config.video_length_minutes == 5
        assert config.clip_duration_seconds == 6


class TestActTemplates:
    """ACT_TEMPLATES structure and get_act_word_targets."""

    def test_all_template_counts_exist(self):
        for act_count in (3, 4, 5, 6):
            assert act_count in ACT_TEMPLATES
            assert len(ACT_TEMPLATES[act_count]) == act_count

    def test_percentages_sum_to_one(self):
        for act_count, templates in ACT_TEMPLATES.items():
            total_pct = sum(t["pct"] for t in templates)
            assert abs(total_pct - 1.0) < 0.01, f"Act count {act_count}: pct sum = {total_pct}"

    def test_get_act_word_targets(self):
        config = VideoConfig(10, 10)
        targets = get_act_word_targets(config)
        assert len(targets) == config.act_count
        total_words = sum(t["word_target"] for t in targets)
        # Should be close to total_script_words (rounding may cause small diff)
        assert abs(total_words - config.total_script_words) < config.act_count

    def test_every_act_has_name_and_purpose(self):
        for act_count, templates in ACT_TEMPLATES.items():
            for t in templates:
                assert "name" in t and t["name"]
                assert "purpose" in t and t["purpose"]
                assert "pct" in t and t["pct"] > 0
