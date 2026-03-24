"""Tests for BodyAgent — write/rewrite loop for Acts 2-5."""

import asyncio
import pytest
from unittest.mock import AsyncMock

from agents.body_agent import BodyAgent
from agents.body_manager import BodyManager
from agents.models import AgentInput, ScoreCard, ScoreDimension, Diagnosis
from agents.config import TierConfig, HookConfig, BodyConfig, WeaponsConfig, CTAConfig, QualityTier


def _make_input(**kwargs) -> AgentInput:
    defaults = {
        "research_payload": {
            "thesis": "China's $3.2T in US Treasuries is a weapon",
            "fact_sheet": "China holds $3.2T in US Treasuries as of 2026.",
            "character_dossier": "Zhang Wei, PBoC deputy director.",
        },
        "video_title": "China's $3T Dollar Trap",
        "thesis": "China holds leverage over US via Treasury holdings",
        "framework_angle": "Geopolitical power dynamics",
        "hook_script": "What happens when China calls in America's $3.2T debt?",
    }
    defaults.update(kwargs)
    return AgentInput(**defaults)


def _make_scorecard(aggregate: float, passed: bool = False) -> ScoreCard:
    return ScoreCard(
        dimensions=[
            ScoreDimension(name="promise_fulfillment", score=int(aggregate / 10), weight=0.30),
            ScoreDimension(name="micro_payoff_density", score=int(aggregate / 10), weight=0.25),
            ScoreDimension(name="character_consistency", score=int(aggregate / 10), weight=0.25),
            ScoreDimension(name="pacing", score=int(aggregate / 10), weight=0.20),
        ],
        aggregate=aggregate,
        passed=passed,
        gate_threshold=70,
    )


def _make_tier(max_iterations=2, min_score=70) -> TierConfig:
    return TierConfig(
        tier=QualityTier.STANDARD,
        hook=HookConfig(),
        body=BodyConfig(max_iterations=max_iterations, min_score=min_score),
        weapons=WeaponsConfig(),
        cta=CTAConfig(),
    )


def _run(coro):
    """Run an async function synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


SAMPLE_BODY = """ACT 2 — THE SETUP

Zhang Wei stared at the terminal in the PBoC trading room. The number
hadn't changed in three months: $3.2 trillion. That's how much of
America's debt sat in Chinese vaults.

ACT 3 — THE ESCALATION

But what Zhang knew — and Washington didn't — was that the real weapon
wasn't the bonds themselves. It was the threat of selling them.

ACT 4 — THE TURN

In March 2026, a single Bloomberg terminal flashed an anomaly that
nobody in the Federal Reserve had anticipated.

ACT 5 — THE IMPLICATIONS

The world Zhang Wei had known for twenty years was ending. And the new
one would be denominated in a currency that didn't yet exist."""


class TestBodyAgentLoop:
    """Test the write -> score -> diagnose -> rewrite loop."""

    def test_body_passes_on_first_try(self):
        mock_manager = AsyncMock(spec=BodyManager)
        mock_manager.score.return_value = _make_scorecard(85, passed=True)
        mock_claude = AsyncMock()
        mock_claude.generate.return_value = SAMPLE_BODY

        agent = BodyAgent(manager=mock_manager, claude_client=mock_claude)
        output = _run(agent.run_body(
            input=_make_input(),
            tier_config=_make_tier(),
            approved_hook="What happens when China calls in America's $3.2T debt?",
        ))

        assert output.passed is True
        assert output.total_iterations == 1
        assert "Zhang Wei" in output.final_draft

    def test_body_iterates_on_failure(self):
        mock_manager = AsyncMock(spec=BodyManager)
        mock_manager.score.side_effect = [
            _make_scorecard(55, passed=False),
            _make_scorecard(80, passed=True),
        ]
        mock_manager.diagnose.return_value = Diagnosis(
            failed_dimensions=["promise_fulfillment"],
            diagnosis="Act 3 drifts into NATO topics, losing the hook's China-debt promise",
            rewrite_guidance="Act 3 should pivot from trade deficit to Treasury holdings",
        )
        mock_claude = AsyncMock()
        mock_claude.generate.side_effect = [
            "ACT 2\nWeak first draft about NATO expansion.",
            SAMPLE_BODY,
        ]

        agent = BodyAgent(manager=mock_manager, claude_client=mock_claude)
        output = _run(agent.run_body(
            input=_make_input(),
            tier_config=_make_tier(max_iterations=3),
            approved_hook="What happens when China calls in America's $3.2T debt?",
        ))

        assert output.total_iterations == 2
        assert output.passed is True
        assert output.iterations[0].diagnosis is not None
        assert "promise_fulfillment" in output.iterations[0].diagnosis.failed_dimensions

    def test_body_respects_max_iterations(self):
        mock_manager = AsyncMock(spec=BodyManager)
        mock_manager.score.return_value = _make_scorecard(40, passed=False)
        mock_manager.diagnose.return_value = Diagnosis(
            failed_dimensions=["all"], diagnosis="Weak throughout", rewrite_guidance="Start over",
        )
        mock_claude = AsyncMock()
        mock_claude.generate.return_value = "A weak body draft."

        agent = BodyAgent(manager=mock_manager, claude_client=mock_claude)
        output = _run(agent.run_body(
            input=_make_input(),
            tier_config=_make_tier(max_iterations=2),
            approved_hook="Some hook",
        ))

        assert output.total_iterations == 2
        assert output.passed is False
