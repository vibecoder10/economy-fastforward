"""Tests for HookAgent — write/rewrite loop and variant generation."""

import asyncio
import pytest
from unittest.mock import AsyncMock

from agents.hook_agent import HookAgent
from agents.hook_manager import HookManager
from agents.models import AgentInput, ScoreCard, ScoreDimension, Diagnosis
from agents.config import TierConfig, HookConfig, BodyConfig, WeaponsConfig, CTAConfig, QualityTier


def _make_input(**kwargs) -> AgentInput:
    defaults = {
        "research_payload": {"thesis": "China's $3.2T in US Treasuries is a weapon"},
        "video_title": "China's $3T Dollar Trap",
        "thesis": "China holds leverage over US via Treasury holdings",
        "framework_angle": "Geopolitical power dynamics",
    }
    defaults.update(kwargs)
    return AgentInput(**defaults)


def _make_scorecard(aggregate: float, passed: bool = False) -> ScoreCard:
    return ScoreCard(
        dimensions=[
            ScoreDimension(name="data_backing", score=int(aggregate / 10), weight=0.25),
            ScoreDimension(name="curiosity_gap", score=int(aggregate / 10), weight=0.25),
            ScoreDimension(name="emotional_trigger", score=int(aggregate / 10), weight=0.20),
            ScoreDimension(name="specificity", score=int(aggregate / 10), weight=0.20),
            ScoreDimension(name="time_constraint", score=int(aggregate / 10), weight=0.10),
        ],
        aggregate=aggregate,
        passed=passed,
        gate_threshold=70,
    )


def _make_tier(variants=1, max_iterations=3, min_score=70) -> TierConfig:
    return TierConfig(
        tier=QualityTier.STANDARD,
        hook=HookConfig(variants=variants, max_iterations=max_iterations, min_score=min_score),
        body=BodyConfig(), weapons=WeaponsConfig(), cta=CTAConfig(),
    )


def _run(coro):
    """Run an async function synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


class TestHookAgentLoop:
    """Test the write → score → diagnose → rewrite loop."""

    def test_passes_on_first_try(self):
        mock_manager = AsyncMock(spec=HookManager)
        mock_manager.score.return_value = _make_scorecard(85, passed=True)
        mock_claude = AsyncMock()
        mock_claude.generate.return_value = "The captain knows what's anchored behind him..."

        agent = HookAgent(manager=mock_manager, claude_client=mock_claude)
        output = _run(agent.run(input=_make_input(), tier=_make_tier(), max_iterations=3, min_score=70))

        assert output.passed is True
        assert output.total_iterations == 1
        assert "captain" in output.final_draft

    def test_iterates_on_failure(self):
        mock_manager = AsyncMock(spec=HookManager)
        mock_manager.score.side_effect = [
            _make_scorecard(55, passed=False),
            _make_scorecard(80, passed=True),
        ]
        mock_manager.diagnose.return_value = Diagnosis(
            failed_dimensions=["curiosity_gap"],
            diagnosis="States conclusion instead of raising question",
            rewrite_guidance="End with tension",
        )
        mock_claude = AsyncMock()
        mock_claude.generate.side_effect = [
            "China holds $3.2 trillion in US debt.",
            "What happens when China calls in America's $3.2T debt?",
        ]

        agent = HookAgent(manager=mock_manager, claude_client=mock_claude)
        output = _run(agent.run(input=_make_input(), tier=_make_tier(), max_iterations=3, min_score=70))

        assert output.total_iterations == 2
        assert output.passed is True
        assert output.iterations[0].diagnosis is not None
        assert "curiosity_gap" in output.iterations[0].diagnosis.failed_dimensions

    def test_respects_max_iterations(self):
        mock_manager = AsyncMock(spec=HookManager)
        mock_manager.score.return_value = _make_scorecard(40, passed=False)
        mock_manager.diagnose.return_value = Diagnosis(
            failed_dimensions=["all"], diagnosis="Weak", rewrite_guidance="Try harder",
        )
        mock_claude = AsyncMock()
        mock_claude.generate.return_value = "A weak hook."

        agent = HookAgent(manager=mock_manager, claude_client=mock_claude)
        output = _run(agent.run(input=_make_input(), tier=_make_tier(max_iterations=2), max_iterations=2, min_score=70))

        assert output.total_iterations == 2
        assert output.passed is False

    def test_returns_best_draft_on_failure(self):
        mock_manager = AsyncMock(spec=HookManager)
        mock_manager.score.side_effect = [
            _make_scorecard(40, passed=False),
            _make_scorecard(60, passed=False),
        ]
        mock_manager.diagnose.return_value = Diagnosis(
            failed_dimensions=["data_backing"], diagnosis="No data", rewrite_guidance="Add numbers",
        )
        mock_claude = AsyncMock()
        mock_claude.generate.side_effect = ["Draft 1 weak", "Draft 2 stronger"]

        agent = HookAgent(manager=mock_manager, claude_client=mock_claude)
        output = _run(agent.run(input=_make_input(), tier=_make_tier(max_iterations=2), max_iterations=2, min_score=70))

        assert output.final_draft == "Draft 2 stronger"
        assert output.final_scores.aggregate == 60


class TestHookAgentVariants:

    def test_generates_n_variants(self):
        mock_manager = AsyncMock(spec=HookManager)
        mock_manager.score.side_effect = [
            _make_scorecard(70, passed=True),
            _make_scorecard(85, passed=True),
            _make_scorecard(75, passed=True),
        ]
        mock_claude = AsyncMock()
        mock_claude.generate.side_effect = ["Hook A", "Hook B (best)", "Hook C"]

        agent = HookAgent(manager=mock_manager, claude_client=mock_claude)
        tier = _make_tier(variants=3, max_iterations=1, min_score=60)
        output = _run(agent.run_with_variants(input=_make_input(), tier_config=tier))

        assert output.final_draft == "Hook B (best)"
        assert output.final_scores.aggregate == 85
        assert len(output.variants) == 3


class TestHookAgentContext:

    def test_proven_patterns_injected(self):
        mock_manager = AsyncMock(spec=HookManager)
        mock_manager.score.return_value = _make_scorecard(80, passed=True)
        mock_claude = AsyncMock()
        mock_claude.generate.return_value = "A hook"

        agent = HookAgent(manager=mock_manager, claude_client=mock_claude)
        input_data = _make_input(
            proven_patterns=["Question format hooks avg 5.2% CTR"],
            anti_patterns=["Abstract openings lose 40% in first 10s"],
        )
        _run(agent.run(input=input_data, tier=_make_tier(max_iterations=1), max_iterations=1, min_score=50))

        call_args = mock_claude.generate.call_args
        prompt = call_args.kwargs.get("prompt", call_args.args[0] if call_args.args else "")
        assert "Question format" in prompt
        assert "Abstract openings" in prompt

    def test_ammunition_injected(self):
        mock_manager = AsyncMock(spec=HookManager)
        mock_manager.score.return_value = _make_scorecard(80, passed=True)
        mock_claude = AsyncMock()
        mock_claude.generate.return_value = "A hook"

        agent = HookAgent(manager=mock_manager, claude_client=mock_claude)
        input_data = _make_input(ammunition={"hook_ammunition": ["$3.2T in US Treasuries"]})
        _run(agent.run(input=input_data, tier=_make_tier(max_iterations=1), max_iterations=1, min_score=50))

        call_args = mock_claude.generate.call_args
        prompt = call_args.kwargs.get("prompt", call_args.args[0] if call_args.args else "")
        assert "$3.2T" in prompt


class TestPaperTrail:

    def test_paper_trail_complete(self):
        mock_manager = AsyncMock(spec=HookManager)
        mock_manager.score.side_effect = [
            _make_scorecard(50, passed=False),
            _make_scorecard(65, passed=False),
            _make_scorecard(80, passed=True),
        ]
        mock_manager.diagnose.return_value = Diagnosis(
            failed_dimensions=["data_backing"], diagnosis="Needs data", rewrite_guidance="Add numbers",
        )
        mock_claude = AsyncMock()
        mock_claude.generate.side_effect = ["V1", "V2", "V3"]

        agent = HookAgent(manager=mock_manager, claude_client=mock_claude)
        output = _run(agent.run(input=_make_input(), tier=_make_tier(), max_iterations=3, min_score=70))

        assert output.total_iterations == 3
        assert len(output.iterations) == 3

        trail = output.to_dict()
        assert len(trail["iterations"]) == 3
        assert trail["iterations"][0]["draft"] == "V1"
        assert trail["iterations"][0]["diagnosis"] is not None
        assert trail["passed"] is True
        assert trail["cost_usd"] > 0
