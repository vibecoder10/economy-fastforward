"""Tests for CTAAgent — write/rewrite loop and empowerment rule."""

import asyncio
import pytest
from unittest.mock import AsyncMock

from agents.cta_agent import CTAAgent
from agents.cta_manager import CTAManager
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


def _make_cta_scorecard(aggregate: float, passed: bool = False) -> ScoreCard:
    return ScoreCard(
        dimensions=[
            ScoreDimension(name="actionability", score=int(aggregate / 10), weight=0.35),
            ScoreDimension(name="empowerment", score=int(aggregate / 10), weight=0.35),
            ScoreDimension(name="data_grounding", score=int(aggregate / 10), weight=0.30),
        ],
        aggregate=aggregate,
        passed=passed,
        gate_threshold=60,
    )


def _make_tier(variants=1, min_score=60) -> TierConfig:
    return TierConfig(
        tier=QualityTier.STANDARD,
        hook=HookConfig(), body=BodyConfig(), weapons=WeaponsConfig(),
        cta=CTAConfig(enabled=True, variants=variants, min_score=min_score),
    )


def _run(coro):
    """Run an async function synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


class TestCTAAgentLoop:
    """Test the write -> score -> diagnose -> rewrite loop."""

    def test_cta_passes_gate(self):
        """CTA that scores above threshold should pass on first try."""
        mock_manager = AsyncMock(spec=CTAManager)
        mock_manager.score.return_value = _make_cta_scorecard(75, passed=True)
        mock_claude = AsyncMock()
        mock_claude.generate.return_value = (
            "Now you know the three signals Beijing watches before making its move. "
            "Track the Treasury auction calendar, watch the yuan-dollar spread, "
            "and you'll see the next chapter before the headlines catch up."
        )

        agent = CTAAgent(manager=mock_manager, claude_client=mock_claude)
        output = _run(agent.run(
            input=_make_input(), tier=_make_tier(), max_iterations=3, min_score=60,
        ))

        assert output.passed is True
        assert output.total_iterations == 1
        assert "signals" in output.final_draft

    def test_cta_must_be_empowering(self):
        """CTA prompt must include the empowerment rule."""
        mock_manager = AsyncMock(spec=CTAManager)
        mock_manager.score.return_value = _make_cta_scorecard(75, passed=True)
        mock_claude = AsyncMock()
        mock_claude.generate.return_value = "An empowering CTA."

        agent = CTAAgent(manager=mock_manager, claude_client=mock_claude)
        _run(agent.run(
            input=_make_input(), tier=_make_tier(), max_iterations=1, min_score=50,
        ))

        call_args = mock_claude.generate.call_args
        prompt = call_args.kwargs.get("prompt", call_args.args[0] if call_args.args else "")
        assert "EMPOWERMENT" in prompt
        assert "armed" in prompt.lower() or "ARMED" in prompt

    def test_cta_respects_max_iterations(self):
        """Should stop after max_iterations even if never passing."""
        mock_manager = AsyncMock(spec=CTAManager)
        mock_manager.score.return_value = _make_cta_scorecard(30, passed=False)
        mock_manager.diagnose.return_value = Diagnosis(
            failed_dimensions=["empowerment"],
            diagnosis="Ends on doom",
            rewrite_guidance="Replace doom with empowerment",
        )
        mock_claude = AsyncMock()
        mock_claude.generate.return_value = "A weak CTA."

        agent = CTAAgent(manager=mock_manager, claude_client=mock_claude)
        output = _run(agent.run(
            input=_make_input(), tier=_make_tier(), max_iterations=2, min_score=60,
        ))

        assert output.total_iterations == 2
        assert output.passed is False

    def test_cta_iterates_on_failure(self):
        """Should iterate when first draft fails, pass on second."""
        mock_manager = AsyncMock(spec=CTAManager)
        mock_manager.score.side_effect = [
            _make_cta_scorecard(45, passed=False),
            _make_cta_scorecard(70, passed=True),
        ]
        mock_manager.diagnose.return_value = Diagnosis(
            failed_dimensions=["actionability"],
            diagnosis="No specific steps",
            rewrite_guidance="Add concrete actions the viewer can take",
        )
        mock_claude = AsyncMock()
        mock_claude.generate.side_effect = [
            "The economy is changing.",
            "Track the three signals we covered and you'll see it coming.",
        ]

        agent = CTAAgent(manager=mock_manager, claude_client=mock_claude)
        output = _run(agent.run(
            input=_make_input(), tier=_make_tier(), max_iterations=3, min_score=60,
        ))

        assert output.total_iterations == 2
        assert output.passed is True
        assert output.iterations[0].diagnosis is not None


class TestCTAAgentVariants:

    def test_generates_n_variants(self):
        """Should generate N variants and pick the best."""
        mock_manager = AsyncMock(spec=CTAManager)
        mock_manager.score.side_effect = [
            _make_cta_scorecard(60, passed=True),
            _make_cta_scorecard(80, passed=True),
        ]
        mock_claude = AsyncMock()
        mock_claude.generate.side_effect = ["CTA A", "CTA B (best)"]

        agent = CTAAgent(manager=mock_manager, claude_client=mock_claude)
        tier = _make_tier(variants=2, min_score=50)
        output = _run(agent.run_with_variants(input=_make_input(), tier_config=tier))

        assert output.final_draft == "CTA B (best)"
        assert output.final_scores.aggregate == 80
        assert len(output.variants) == 2


class TestCTAAgentContext:

    def test_ammunition_injected(self):
        """CTA ammunition should appear in the prompt."""
        mock_manager = AsyncMock(spec=CTAManager)
        mock_manager.score.return_value = _make_cta_scorecard(75, passed=True)
        mock_claude = AsyncMock()
        mock_claude.generate.return_value = "A CTA."

        agent = CTAAgent(manager=mock_manager, claude_client=mock_claude)
        input_data = _make_input(
            ammunition={"cta_ammunition": ["Watch the yuan-dollar spread for signals"]}
        )
        _run(agent.run(
            input=input_data, tier=_make_tier(), max_iterations=1, min_score=50,
        ))

        call_args = mock_claude.generate.call_args
        prompt = call_args.kwargs.get("prompt", call_args.args[0] if call_args.args else "")
        assert "yuan-dollar" in prompt
