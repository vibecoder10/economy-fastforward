"""Parse autopilot_program.md into typed configuration."""

import re
from pathlib import Path
from pydantic import BaseModel, field_validator
from typing import Optional


class WeightsConfig(BaseModel):
    """Confidence scoring weights (must sum to 1.0).

    channel_momentum and retention_patterns default to 0.0: their scorers
    (ConfidenceScorer._score_channel_momentum / _score_retention_patterns)
    are unimplemented placeholders that always return a neutral 50.0, so a
    non-zero weight here would let fake data influence real production
    decisions. See autopilot_program.md's "Confidence Scoring Weights"
    section comment and C32 (docs/reports/2026-07-17-storyengine-agent-audit-findings.md
    §3.2) for the full rationale before re-enabling either weight.
    """
    competitor_vph: float = 0.37
    topic_channel_fit: float = 0.30
    timing_freshness: float = 0.24
    channel_momentum: float = 0.00
    retention_patterns: float = 0.00
    title_formula: float = 0.09

    @field_validator('*', mode='before')
    @classmethod
    def coerce_float(cls, v):
        return float(v) if v is not None else 0.0


class ThresholdsConfig(BaseModel):
    """Decision thresholds."""
    min_confidence_score: int = 60
    min_competitor_vph: int = 50
    max_idea_age_days: int = 7
    ctr_success_threshold: float = 4.0
    ctr_failure_threshold: float = 2.5
    early_warning_hours: int = 6


class AutopilotConfig(BaseModel):
    """Full autopilot configuration."""
    videos_per_month: int = 15
    production_interval_days: int = 2
    weights: WeightsConfig = WeightsConfig()
    thresholds: ThresholdsConfig = ThresholdsConfig()


def _extract_yaml_block(content: str, section_name: str) -> dict:
    """Extract key-value pairs from a markdown section.

    Handles both flat and nested YAML-style blocks.
    """
    # Find section
    pattern = rf"##\s+{re.escape(section_name)}\s*\n(.*?)(?=\n##|\Z)"
    match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
    if not match:
        return {}

    section_content = match.group(1)
    result = {}
    current_nested = None
    nested_dict = {}

    for line in section_content.split('\n'):
        line = line.strip()
        if not line or line.startswith('#') or line.startswith('---'):
            continue

        # Check for nested block start (e.g., "weights:")
        if line.endswith(':') and ':' not in line[:-1]:
            if current_nested and nested_dict:
                result[current_nested] = nested_dict
            current_nested = line[:-1].strip()
            nested_dict = {}
            continue

        # Parse key: value
        if ':' in line:
            key, value = line.split(':', 1)
            key = key.strip()
            value = value.strip()

            # Try to parse as number
            try:
                if '.' in value:
                    value = float(value)
                else:
                    value = int(value)
            except ValueError:
                pass

            if current_nested:
                nested_dict[key] = value
            else:
                result[key] = value

    # Don't forget last nested block
    if current_nested and nested_dict:
        result[current_nested] = nested_dict

    return result


def parse_config(content: str) -> AutopilotConfig:
    """Parse autopilot_program.md content into config object.

    Args:
        content: Raw markdown content of autopilot_program.md

    Returns:
        AutopilotConfig with all settings
    """
    # Extract sections
    cadence = _extract_yaml_block(content, "Cadence")
    weights_section = _extract_yaml_block(content, "Confidence Scoring Weights")
    thresholds_section = _extract_yaml_block(content, "Thresholds")

    # Build config
    weights_data = weights_section.get("weights", {})
    thresholds_data = thresholds_section.get("thresholds", {})

    return AutopilotConfig(
        videos_per_month=cadence.get("videos_per_month", 15),
        production_interval_days=cadence.get("production_interval_days", 2),
        weights=WeightsConfig(**weights_data) if weights_data else WeightsConfig(),
        thresholds=ThresholdsConfig(**thresholds_data) if thresholds_data else ThresholdsConfig(),
    )


def load_config(config_path: Optional[Path] = None) -> AutopilotConfig:
    """Load config from autopilot_program.md file.

    Args:
        config_path: Path to config file. Defaults to autopilot/autopilot_program.md

    Returns:
        AutopilotConfig
    """
    if config_path is None:
        config_path = Path(__file__).parent.parent / "autopilot_program.md"

    if not config_path.exists():
        # Return defaults if no config file
        return AutopilotConfig()

    content = config_path.read_text()
    return parse_config(content)
