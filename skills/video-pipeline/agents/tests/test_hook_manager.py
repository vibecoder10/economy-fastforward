"""Tests for HookManager — scoring and gating logic."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from agents.hook_manager import HookManager
from agents.models import AgentInput, ScoreCard, ScoreDimension
from agents.config import DEFAULT_HOOK_WEIGHTS


class TestScoreCardCalculation:
    """Test ScoreCard aggregate calculation."""

    def test_perfect_scores(self):
        dimensions = [
            ScoreDimension(name="data_backing", score=10, weight=0.25),
            ScoreDimension(name="curiosity_gap", score=10, weight=0.25),
            ScoreDimension(name="emotional_trigger", score=10, weight=0.20),
            ScoreDimension(name="specificity", score=10, weight=0.20),
            ScoreDimension(name="time_constraint", score=10, weight=0.10),
        ]
        card = ScoreCard(dimensions=dimensions)
        assert abs(card.aggregate - 100.0) < 0.01

    def test_mixed_scores(self):
        dimensions = [
            ScoreDimension(name="data_backing", score=8, weight=0.25),
            ScoreDimension(name="curiosity_gap", score=6, weight=0.25),
            ScoreDimension(name="emotional_trigger", score=7, weight=0.20),
            ScoreDimension(name="specificity", score=9, weight=0.20),
            ScoreDimension(name="time_constraint", score=10, weight=0.10),
        ]
        card = ScoreCard(dimensions=dimensions)
        # (8*0.25 + 6*0.25 + 7*0.20 + 9*0.20 + 10*0.10) / 1.0 * 10
        expected = (2.0 + 1.5 + 1.4 + 1.8 + 1.0) / 1.0 * 10
        assert abs(card.aggregate - expected) < 0.1

    def test_gate_passes(self):
        dimensions = [
            ScoreDimension(name="d1", score=8, weight=0.5),
            ScoreDimension(name="d2", score=8, weight=0.5),
        ]
        card = ScoreCard(dimensions=dimensions, gate_threshold=70)
        card.passed = card.aggregate >= 70
        assert card.passed is True

    def test_gate_fails(self):
        dimensions = [
            ScoreDimension(name="d1", score=5, weight=0.5),
            ScoreDimension(name="d2", score=5, weight=0.5),
        ]
        card = ScoreCard(dimensions=dimensions, gate_threshold=70)
        card.passed = card.aggregate >= 70
        assert card.passed is False


class TestHookManagerParsing:
    """Test score response parsing."""

    def test_parse_valid_json(self):
        manager = HookManager()
        response = '''{
            "data_backing": {"score": 8, "reasoning": "Specific $3.2T claim"},
            "curiosity_gap": {"score": 9, "reasoning": "Strong tension"},
            "emotional_trigger": {"score": 7, "reasoning": "Fear of economic collapse"},
            "specificity": {"score": 8, "reasoning": "Aircraft carrier scene"},
            "time_constraint": {"score": 10, "reasoning": "68 words"}
        }'''
        card = manager._parse_scores(response)
        assert len(card.dimensions) == 5
        assert card.dimensions[0].score == 8
        assert card.dimensions[0].name == "data_backing"
        assert card.aggregate > 0

    def test_parse_json_with_fences(self):
        manager = HookManager()
        response = '```json\n{"data_backing": {"score": 7, "reasoning": "ok"}, "curiosity_gap": {"score": 7, "reasoning": "ok"}, "emotional_trigger": {"score": 7, "reasoning": "ok"}, "specificity": {"score": 7, "reasoning": "ok"}, "time_constraint": {"score": 7, "reasoning": "ok"}}\n```'
        card = manager._parse_scores(response)
        assert len(card.dimensions) == 5
        assert all(d.score == 7 for d in card.dimensions)

    def test_parse_invalid_json_returns_neutral(self):
        manager = HookManager()
        card = manager._parse_scores("this is not json")
        assert len(card.dimensions) == 5
        assert all(d.score == 5 for d in card.dimensions)

    def test_scores_clamped_to_range(self):
        manager = HookManager()
        response = '{"data_backing": {"score": 15, "reasoning": ""}, "curiosity_gap": {"score": -3, "reasoning": ""}, "emotional_trigger": {"score": 7, "reasoning": ""}, "specificity": {"score": 7, "reasoning": ""}, "time_constraint": {"score": 7, "reasoning": ""}}'
        card = manager._parse_scores(response)
        assert card.dimensions[0].score == 10  # Clamped to max
        assert card.dimensions[1].score == 0   # Clamped to min


class TestHookManagerWeights:
    """Test custom weight configuration."""

    def test_custom_weights(self):
        custom = {
            "data_backing": 0.40,
            "curiosity_gap": 0.30,
            "emotional_trigger": 0.10,
            "specificity": 0.10,
            "time_constraint": 0.10,
        }
        manager = HookManager(weights=custom)
        assert manager.weights["data_backing"] == 0.40

    def test_default_weights_sum_to_one(self):
        total = sum(DEFAULT_HOOK_WEIGHTS.values())
        assert abs(total - 1.0) < 0.01


class TestHookManagerGating:
    """Test gate pass/fail logic."""

    def test_passes_gate(self):
        manager = HookManager()
        card = ScoreCard(
            dimensions=[ScoreDimension(name="d", score=8, weight=1.0)],
        )
        assert manager.passes_gate(card, min_score=70) is True

    def test_fails_gate(self):
        manager = HookManager()
        card = ScoreCard(
            dimensions=[ScoreDimension(name="d", score=5, weight=1.0)],
        )
        assert manager.passes_gate(card, min_score=70) is False

    def test_exact_threshold_passes(self):
        manager = HookManager()
        card = ScoreCard(
            dimensions=[ScoreDimension(name="d", score=7, weight=1.0)],
        )
        assert manager.passes_gate(card, min_score=70) is True
