"""Hook Manager — scores hooks on 5 dimensions and gates passage.

The boss that won't pass anything below the bar. Provides specific,
actionable diagnosis when hooks fail — not vague feedback.

Scoring connects to the autoresearch loop: after video publishes,
the hook's agent scores get correlated with actual AVD (average view
duration). The hook drives retention, not CTR — thumbnail+title drive CTR.
Patterns that produce high-AVD hooks get loaded as proven_patterns.
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional

from agents.base_agent import BaseManager
from agents.models import AgentInput, Diagnosis, ScoreCard, ScoreDimension
from agents.config import DEFAULT_HOOK_WEIGHTS


class HookManager(BaseManager):
    """Scores hooks on 5 dimensions. Rejects bad work with specific feedback."""

    DIMENSIONS = ["data_backing", "curiosity_gap", "emotional_trigger", "specificity", "time_constraint"]

    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        claude_client=None,
    ):
        self.weights = weights or DEFAULT_HOOK_WEIGHTS
        self._claude = claude_client

    async def _get_claude(self):
        if self._claude is None:
            from shared.clients.anthropic_client import AnthropicClient
            self._claude = AnthropicClient()
        return self._claude

    async def score(self, draft: str, context: AgentInput) -> ScoreCard:
        """Score a hook on 5 dimensions using Claude.

        Each dimension scored 0-10 with reasoning. Aggregate is
        weighted average scaled to 0-100.
        """
        claude = await self._get_claude()

        prompt = f"""Score this video hook on 5 dimensions. Be STRICT — a 7 means "good enough",
8 means "strong", 9 means "excellent", 10 means "would make you stop scrolling".

HOOK TO SCORE:
"{draft}"

VIDEO CONTEXT:
Title: {context.video_title}
Thesis: {context.thesis or 'Not specified'}

SCORING DIMENSIONS (score each 0-10):

1. DATA_BACKING — Does it contain a specific, verifiable claim? (number, name, date, fact)
   0 = no data at all, 5 = vague reference, 8 = specific claim, 10 = shocking specific data

2. CURIOSITY_GAP — Does it create a question the viewer NEEDS answered?
   0 = states conclusion, 5 = mildly interesting, 8 = "I need to know", 10 = irresistible tension

3. EMOTIONAL_TRIGGER — Does the viewer FEEL something? (fear, outrage, curiosity, awe)
   0 = purely informational, 5 = intellectually interesting, 8 = gut reaction, 10 = visceral

4. SPECIFICITY — Is it a concrete scene vs vague abstraction?
   0 = abstract concept, 5 = general situation, 8 = specific scene, 10 = "I can see it"

5. TIME_CONSTRAINT — Is it ~70 words (speakable in 15 seconds)?
   Count the words. 60-80 words = 10, 50-60 or 80-90 = 7, <50 or >90 = 4, >100 = 0

Respond with ONLY a JSON object:
{{
  "data_backing": {{"score": N, "reasoning": "..."}},
  "curiosity_gap": {{"score": N, "reasoning": "..."}},
  "emotional_trigger": {{"score": N, "reasoning": "..."}},
  "specificity": {{"score": N, "reasoning": "..."}},
  "time_constraint": {{"score": N, "reasoning": "..."}}
}}"""

        response = await claude.generate(
            prompt=prompt,
            system="You are a strict quality manager for YouTube video hooks. "
                   "You score honestly — most hooks are 5-7, truly great ones are 8-9. "
                   "A 10 is rare. Never inflate scores.",
            max_tokens=600,
        )

        return self._parse_scores(response)

    def _parse_scores(self, response: str) -> ScoreCard:
        """Parse Claude's scoring response into a ScoreCard."""
        try:
            # Extract JSON from response
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
                weight = self.weights.get(dim_name, 0.2)

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
                    ScoreDimension(name=d, score=5, weight=self.weights.get(d, 0.2), reasoning="Parse error")
                    for d in self.DIMENSIONS
                ]
            )

    async def diagnose(
        self,
        draft: str,
        scores: ScoreCard,
        context: AgentInput,
    ) -> Diagnosis:
        """Generate specific, actionable diagnosis for a failed hook."""
        claude = await self._get_claude()

        # Identify failed dimensions (below 7)
        failed = [d for d in scores.dimensions if d.score < 7]
        failed_names = [d.name for d in failed]

        if not failed:
            failed = sorted(scores.dimensions, key=lambda d: d.score)[:2]
            failed_names = [d.name for d in failed]

        scores_summary = "\n".join(
            f"  {d.name}: {d.score}/10 — {d.reasoning}"
            for d in scores.dimensions
        )

        prompt = f"""A video hook failed quality gate. Diagnose WHY and give SPECIFIC rewrite guidance.

HOOK:
"{draft}"

SCORES:
{scores_summary}

AGGREGATE: {scores.aggregate:.0f}/100 (need {scores.gate_threshold})
WORST DIMENSIONS: {', '.join(failed_names)}

DIAGNOSIS RULES:
- Be specific: "Curiosity gap scored 4 because the hook states the conclusion instead of raising a question"
- Give concrete guidance: "Rewrite to end with an unanswered tension — replace the final statement with a question"
- Focus on the 1-2 weakest dimensions — don't try to fix everything at once
- Reference the specific words/phrases that are weak

Respond with ONLY a JSON object:
{{
  "diagnosis": "What's wrong (specific, referencing the actual text)",
  "rewrite_guidance": "How to fix it (concrete instructions, not vague advice)"
}}"""

        response = await claude.generate(
            prompt=prompt,
            system="You are a script editor. When a hook fails, you explain EXACTLY why "
                   "and give CONCRETE instructions for the rewrite. Never say 'make it better' — "
                   "say 'replace X with Y because Z'.",
            max_tokens=400,
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
