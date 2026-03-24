"""Base classes for all quality agents and managers.

Every agent follows the Write → Score → Diagnose → Rewrite loop.
Every manager scores on N dimensions and gates passage.

The autoresearch pattern (Karpathy): each iteration is an experiment.
If the score improves, keep the approach. If not, diagnose and try different.
The learning compounds across videos via autopilot memory.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from agents.models import (
    AgentInput,
    AgentOutput,
    Diagnosis,
    Iteration,
    ScoreCard,
)
from agents.config import TierConfig


class BaseAgent(ABC):
    """Write → Diagnose → Rewrite loop until manager approves.

    Subclasses implement write() and diagnose(). The run() loop
    handles iteration, scoring, and paper trail automatically.
    """

    name: str = "BaseAgent"

    def __init__(self, manager: BaseManager):
        self.manager = manager

    async def run(
        self,
        input: AgentInput,
        tier: TierConfig,
        max_iterations: int = 3,
        min_score: int = 70,
    ) -> AgentOutput:
        """Run the agent loop: write → score → diagnose → rewrite.

        Args:
            input: Research payload and context
            tier: Quality tier configuration
            max_iterations: Max rewrite cycles
            min_score: Minimum aggregate score to pass gate

        Returns:
            AgentOutput with final draft, scores, and full paper trail
        """
        iterations: List[Iteration] = []
        best_draft = ""
        best_scores = None
        cost = 0.0

        for i in range(max_iterations):
            # Write (or rewrite with diagnosis context)
            if i == 0:
                draft = await self.write(input)
            else:
                draft = await self.rewrite(input, iterations[-1])

            cost += self._estimate_call_cost()

            # Score
            scores = await self.manager.score(draft, input)
            scores.gate_threshold = min_score
            scores.passed = scores.aggregate >= min_score
            cost += self._estimate_call_cost()

            # Track best
            if best_scores is None or scores.aggregate > best_scores.aggregate:
                best_draft = draft
                best_scores = scores

            # Diagnose if failed
            diagnosis = None
            if not scores.passed and i < max_iterations - 1:
                diagnosis = await self.manager.diagnose(draft, scores, input)

            iteration = Iteration(
                iteration_number=i + 1,
                draft=draft,
                scores=scores,
                diagnosis=diagnosis,
            )
            iterations.append(iteration)

            # Pass gate — stop iterating
            if scores.passed:
                break

        return AgentOutput(
            agent_name=self.name,
            final_draft=best_draft,
            final_scores=best_scores or ScoreCard(dimensions=[], aggregate=0),
            iterations=iterations,
            passed=best_scores.passed if best_scores else False,
            total_iterations=len(iterations),
            cost_usd=cost,
        )

    @abstractmethod
    async def write(self, input: AgentInput) -> str:
        """Generate an initial draft."""
        ...

    async def rewrite(self, input: AgentInput, last_iteration: Iteration) -> str:
        """Rewrite based on diagnosis. Default: call write with diagnosis context.

        Subclasses can override for more sophisticated rewrite strategies.
        """
        return await self.write(input, diagnosis=last_iteration.diagnosis)

    def _estimate_call_cost(self) -> float:
        """Estimate cost of one Claude API call (Sonnet)."""
        return 0.015  # ~$0.015 per call (input + output tokens)


class BaseManager(ABC):
    """Score output on N dimensions. Gate passage.

    Managers are the "bosses" — they reject bad work with specific
    feedback. The quality bar is configurable per tier.
    """

    @abstractmethod
    async def score(self, draft: str, context: AgentInput) -> ScoreCard:
        """Score a draft on all dimensions.

        Args:
            draft: The text to score
            context: Original input for reference

        Returns:
            ScoreCard with per-dimension scores and aggregate
        """
        ...

    @abstractmethod
    async def diagnose(
        self,
        draft: str,
        scores: ScoreCard,
        context: AgentInput,
    ) -> Diagnosis:
        """Generate actionable diagnosis for a failed draft.

        Args:
            draft: The failing text
            scores: What scored low
            context: Original input

        Returns:
            Diagnosis with specific rewrite guidance
        """
        ...

    def passes_gate(self, scores: ScoreCard, min_score: int) -> bool:
        """Check if scores meet the quality gate threshold."""
        return scores.aggregate >= min_score
