"""Body Manager — scores script bodies on 4 dimensions and gates passage.

Scores Acts 2-5 on promise fulfillment, micro-payoff density, character
consistency, and pacing. Provides specific, actionable diagnosis when
the body fails the quality gate.

Scoring connects to the autoresearch loop: after video publishes,
body scores get correlated with retention curves (where do viewers
drop off?). Patterns that produce high-retention bodies get loaded
as proven_patterns.
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional

from agents.base_agent import BaseManager
from agents.models import AgentInput, Diagnosis, ScoreCard, ScoreDimension
from agents.config import DEFAULT_BODY_WEIGHTS


class BodyManager(BaseManager):
    """Scores bodies on 4 dimensions. Rejects bad work with specific feedback."""

    DIMENSIONS = [
        "promise_fulfillment",
        "micro_payoff_density",
        "character_consistency",
        "pacing",
    ]

    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        claude_client=None,
    ):
        self.weights = weights or DEFAULT_BODY_WEIGHTS
        self._claude = claude_client

    async def _get_claude(self):
        if self._claude is None:
            from shared.clients.anthropic_client import AnthropicClient
            self._claude = AnthropicClient()
        return self._claude

    async def score(self, draft: str, context: AgentInput) -> ScoreCard:
        """Score a body on 4 dimensions using Claude.

        Each dimension scored 0-10 with reasoning. Aggregate is
        weighted average scaled to 0-100.
        """
        claude = await self._get_claude()

        hook_text = context.hook_script or "(no hook provided)"

        prompt = f"""Score this script body (Acts 2-5) on 4 dimensions. Be STRICT — a 7 means "good enough",
8 means "strong", 9 means "excellent", 10 means "would keep any viewer watching".

BODY TO SCORE:
"{draft}"

VIDEO CONTEXT:
Title: {context.video_title}
Thesis: {context.thesis or 'Not specified'}
Approved Hook (Act 1): "{hook_text}"

SCORING DIMENSIONS (score each 0-10):

1. PROMISE_FULFILLMENT — Does each act deliver on the hook's implied promise?
   0 = completely ignores the hook, 5 = loosely related, 8 = clearly delivers, 10 = exceeds expectation

2. MICRO_PAYOFF_DENSITY — Is there a revelation/insight every ~90 seconds (~225 words)?
   0 = monotone info-dump, 5 = occasional payoff, 8 = consistent payoffs, 10 = every paragraph delivers

3. CHARACTER_CONSISTENCY — Does data live inside characters (not raw statistics)?
   0 = pure data dump, 5 = mix of data and character, 8 = mostly character-driven, 10 = every fact through a person

4. PACING — Is word count per act within targets? (~750 words/act, ~3000 total)
   Count approximate words per act. 700-800 per act = 10, 600-900 = 7, <500 or >1000 = 4

Respond with ONLY a JSON object:
{{
  "promise_fulfillment": {{"score": N, "reasoning": "..."}},
  "micro_payoff_density": {{"score": N, "reasoning": "..."}},
  "character_consistency": {{"score": N, "reasoning": "..."}},
  "pacing": {{"score": N, "reasoning": "..."}}
}}"""

        response = await claude.generate(
            prompt=prompt,
            system="You are a strict quality manager for YouTube video scripts. "
                   "You score honestly — most bodies are 5-7, truly great ones are 8-9. "
                   "A 10 is rare. Never inflate scores.",
            max_tokens=600,
        )

        return self._parse_scores(response)

    def _parse_scores(self, response: str) -> ScoreCard:
        """Parse Claude's scoring response into a ScoreCard."""
        try:
            text = response.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]

            data = json.loads(text.strip())

            dimensions = []
            for dim_name in self.DIMENSIONS:
                dim_data = data.get(dim_name, {})
                score = int(dim_data.get("score", 5)) if isinstance(dim_data, dict) else 5
                reasoning = dim_data.get("reasoning", "") if isinstance(dim_data, dict) else ""
                weight = self.weights.get(dim_name, 0.25)

                dimensions.append(ScoreDimension(
                    name=dim_name,
                    score=min(10, max(0, score)),
                    weight=weight,
                    reasoning=reasoning,
                ))

            return ScoreCard(dimensions=dimensions)

        except (json.JSONDecodeError, KeyError, TypeError):
            # Return neutral scores on parse failure
            return ScoreCard(
                dimensions=[
                    ScoreDimension(name=d, score=5, weight=self.weights.get(d, 0.25), reasoning="Parse error")
                    for d in self.DIMENSIONS
                ]
            )

    async def diagnose(
        self,
        draft: str,
        scores: ScoreCard,
        context: AgentInput,
    ) -> Diagnosis:
        """Generate specific, actionable diagnosis for a failed body."""
        claude = await self._get_claude()

        failed = [d for d in scores.dimensions if d.score < 7]
        failed_names = [d.name for d in failed]

        if not failed:
            failed = sorted(scores.dimensions, key=lambda d: d.score)[:2]
            failed_names = [d.name for d in failed]

        scores_summary = "\n".join(
            f"  {d.name}: {d.score}/10 — {d.reasoning}"
            for d in scores.dimensions
        )

        hook_text = context.hook_script or "(no hook provided)"

        prompt = f"""A script body (Acts 2-5) failed quality gate. Diagnose WHY and give SPECIFIC rewrite guidance.

BODY:
"{draft[:2000]}..."

APPROVED HOOK (Act 1):
"{hook_text}"

SCORES:
{scores_summary}

AGGREGATE: {scores.aggregate:.0f}/100 (need {scores.gate_threshold})
WORST DIMENSIONS: {', '.join(failed_names)}

DIAGNOSIS RULES:
- Be specific: "Promise fulfillment scored 4 because Act 3 introduces NATO but the hook promised China economics"
- Give concrete guidance: "Act 3 should pivot from the trade deficit to the Treasury holdings mentioned in the hook"
- Focus on the 1-2 weakest dimensions — don't try to fix everything at once
- Reference specific acts and passages that are weak

Respond with ONLY a JSON object:
{{
  "diagnosis": "What's wrong (specific, referencing actual acts and text)",
  "rewrite_guidance": "How to fix it (concrete instructions per act)"
}}"""

        response = await claude.generate(
            prompt=prompt,
            system="You are a script editor. When a body fails, you explain EXACTLY why "
                   "and give CONCRETE instructions for the rewrite. Never say 'make it better' — "
                   "say 'Act 3 needs X because Y'.",
            max_tokens=500,
        )

        try:
            text = response.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            data = json.loads(text.strip())

            return Diagnosis(
                failed_dimensions=failed_names,
                diagnosis=data.get("diagnosis", "Quality gate not met"),
                rewrite_guidance=data.get("rewrite_guidance", "Improve weakest dimensions"),
            )
        except (json.JSONDecodeError, KeyError):
            return Diagnosis(
                failed_dimensions=failed_names,
                diagnosis=f"Aggregate {scores.aggregate:.0f}/100 below threshold. "
                          f"Weakest: {', '.join(f'{d.name}={d.score}' for d in failed)}",
                rewrite_guidance="Focus on improving " + " and ".join(failed_names),
            )
