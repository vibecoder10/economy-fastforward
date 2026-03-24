"""CTA Manager — scores CTAs on 3 dimensions and gates passage.

The CTA must be actionable, empowering, and data-grounded. Generic
"like and subscribe" CTAs fail instantly. The viewer must leave feeling
ARMED — specific knowledge they can act on immediately.

Scoring dimensions:
  1. actionability (0.35) — Specific steps the viewer can take
  2. empowerment (0.35) — Viewer feels armed with knowledge
  3. data_grounding (0.30) — Numbers from research back up the call
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional

from agents.base_agent import BaseManager
from agents.models import AgentInput, Diagnosis, ScoreCard, ScoreDimension


DEFAULT_CTA_WEIGHTS = {
    "actionability": 0.35,
    "empowerment": 0.35,
    "data_grounding": 0.30,
}


class CTAManager(BaseManager):
    """Scores CTAs on 3 dimensions. Rejects weak closes with specific feedback."""

    DIMENSIONS = ["actionability", "empowerment", "data_grounding"]

    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        claude_client=None,
    ):
        self.weights = weights or DEFAULT_CTA_WEIGHTS
        self._claude = claude_client

    async def _get_claude(self):
        if self._claude is None:
            from shared.clients.anthropic_client import AnthropicClient
            self._claude = AnthropicClient()
        return self._claude

    async def score(self, draft: str, context: AgentInput) -> ScoreCard:
        """Score a CTA on 3 dimensions using Claude.

        Each dimension scored 0-10 with reasoning. Aggregate is
        weighted average scaled to 0-100.
        """
        claude = await self._get_claude()

        prompt = f"""Score this video CTA (closing call to action) on 3 dimensions. Be STRICT — a 7 means "good enough",
8 means "strong", 9 means "excellent", 10 means "viewer immediately acts on it".

CTA TO SCORE:
"{draft}"

VIDEO CONTEXT:
Title: {context.video_title}
Thesis: {context.thesis or 'Not specified'}

SCORING DIMENSIONS (score each 0-10):

1. ACTIONABILITY — Does it give the viewer specific, concrete steps they can take?
   0 = no action at all ("think about it"), 5 = vague direction ("do your research"),
   8 = specific action ("watch for X signal"), 10 = multiple concrete steps with specifics

2. EMPOWERMENT — Does the viewer leave feeling ARMED and powerful, not helpless?
   0 = doom/despair ending, 5 = neutral/informational, 8 = viewer feels informed and capable,
   10 = viewer feels they have an edge others don't

3. DATA_GROUNDING — Does the CTA reference specific numbers/facts from the video?
   0 = no data, 5 = vague reference to "the data", 8 = specific number referenced,
   10 = data directly supports why the action matters

Respond with ONLY a JSON object:
{{
  "actionability": {{"score": N, "reasoning": "..."}},
  "empowerment": {{"score": N, "reasoning": "..."}},
  "data_grounding": {{"score": N, "reasoning": "..."}}
}}"""

        response = await claude.generate(
            prompt=prompt,
            system="You are a strict quality manager for YouTube video CTAs. "
                   "You score honestly — most CTAs are 5-7, truly great ones are 8-9. "
                   "A 10 is rare. Generic subscribe CTAs score 0 on all dimensions.",
            max_tokens=400,
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
                weight = self.weights.get(dim_name, 0.33)

                dimensions.append(ScoreDimension(
                    name=dim_name,
                    score=min(10, max(0, score)),
                    weight=weight,
                    reasoning=reasoning,
                ))

            return ScoreCard(dimensions=dimensions)

        except (json.JSONDecodeError, KeyError, TypeError):
            return ScoreCard(
                dimensions=[
                    ScoreDimension(name=d, score=5, weight=self.weights.get(d, 0.33), reasoning="Parse error")
                    for d in self.DIMENSIONS
                ]
            )

    async def diagnose(
        self,
        draft: str,
        scores: ScoreCard,
        context: AgentInput,
    ) -> Diagnosis:
        """Generate specific, actionable diagnosis for a failed CTA."""
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

        prompt = f"""A video CTA failed quality gate. Diagnose WHY and give SPECIFIC rewrite guidance.

CTA:
"{draft}"

SCORES:
{scores_summary}

AGGREGATE: {scores.aggregate:.0f}/100 (need {scores.gate_threshold})
WORST DIMENSIONS: {', '.join(failed_names)}

DIAGNOSIS RULES:
- Be specific: "Empowerment scored 3 because the CTA ends on doom ('the economy will collapse') instead of arming the viewer"
- Give concrete guidance: "Replace the final sentence with a specific signal the viewer can watch for"
- Focus on the 1-2 weakest dimensions
- Reference the specific words/phrases that are weak
- Remember: CTAs MUST end on empowerment. If the last sentence is doom/despair, that's the #1 fix.

Respond with ONLY a JSON object:
{{
  "diagnosis": "What's wrong (specific, referencing the actual text)",
  "rewrite_guidance": "How to fix it (concrete instructions, not vague advice)"
}}"""

        response = await claude.generate(
            prompt=prompt,
            system="You are a script editor. When a CTA fails, you explain EXACTLY why "
                   "and give CONCRETE instructions for the rewrite. The #1 rule: CTAs must "
                   "end on empowerment. Never say 'make it better' — say 'replace X with Y because Z'.",
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
