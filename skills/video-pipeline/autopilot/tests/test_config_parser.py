"""Tests for autopilot config parser."""

import pytest
from pathlib import Path
from autopilot.core.config_parser import AutopilotConfig, parse_config


SAMPLE_CONFIG = """# Autopilot Program

## Mission

Your mission: **Maximize click-through rate for this YouTube channel.**

---

## Cadence

videos_per_month: 15
production_interval_days: 2

---

## Confidence Scoring Weights

weights:
  competitor_vph: 0.30
  topic_channel_fit: 0.25
  timing_freshness: 0.20
  channel_momentum: 0.10
  retention_patterns: 0.08
  title_formula: 0.07

---

## Thresholds

thresholds:
  min_confidence_score: 60
  min_competitor_vph: 50
  max_idea_age_days: 7
  ctr_success_threshold: 4.0
  ctr_failure_threshold: 2.5
  early_warning_hours: 6
"""


class TestConfigParser:
    """Test suite for config parsing."""

    def test_parse_cadence(self):
        """Should extract cadence settings."""
        config = parse_config(SAMPLE_CONFIG)
        assert config.videos_per_month == 15
        assert config.production_interval_days == 2

    def test_parse_weights(self):
        """Should extract confidence scoring weights."""
        config = parse_config(SAMPLE_CONFIG)
        assert config.weights.competitor_vph == 0.30
        assert config.weights.topic_channel_fit == 0.25
        assert config.weights.timing_freshness == 0.20
        assert config.weights.channel_momentum == 0.10
        assert config.weights.retention_patterns == 0.08
        assert config.weights.title_formula == 0.07

    def test_weights_sum_to_one(self):
        """Weights should sum to 1.0."""
        config = parse_config(SAMPLE_CONFIG)
        total = (
            config.weights.competitor_vph +
            config.weights.topic_channel_fit +
            config.weights.timing_freshness +
            config.weights.channel_momentum +
            config.weights.retention_patterns +
            config.weights.title_formula
        )
        assert abs(total - 1.0) < 0.01

    def test_parse_thresholds(self):
        """Should extract threshold settings."""
        config = parse_config(SAMPLE_CONFIG)
        assert config.thresholds.min_confidence_score == 60
        assert config.thresholds.min_competitor_vph == 50
        assert config.thresholds.max_idea_age_days == 7
        assert config.thresholds.ctr_success_threshold == 4.0
        assert config.thresholds.ctr_failure_threshold == 2.5
        assert config.thresholds.early_warning_hours == 6
