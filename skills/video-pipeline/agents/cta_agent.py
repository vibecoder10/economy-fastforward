"""CTA Agent — specialized writer for Act 6 "The Play" (actionable close).

The CTA is the final impression. A strong CTA sends the viewer away
feeling EMPOWERED — armed with knowledge and specific steps, not helpless.
This is the Economy FastForward brand: we don't just explain, we equip.

This agent generates 1-2 CTA variants (configurable via CTAConfig.variants),
each scored on 3 dimensions by the CTAManager, iterating until quality gate passes.

RULE: Every CTA MUST end on empowerment. The viewer leaves feeling armed,
not overwhelmed. If the CTA ends on doom, it fails — regardless of other scores.
"""

from __future__ import annotations

from typing import Optional

from agents.base_agent import BaseAgent, BaseManager
from agents.models import AgentInput, AgentOutput, Diagnosis, Iteration
from agents.config import TierConfig, CTAConfig


class CTAAgent(BaseAgent):
    """Writes CTAs — the actionable close that sends viewers away empowered."""

    name = "CTA Agent"

    def __init__(self, manager: BaseManager, claude_client=None):
        super().__init__(manager)
        self._claude = claude_client

    async def _get_claude(self):
        """Lazy-load Claude client."""
        if self._claude is None:
            from shared.clients.anthropic_client import AnthropicClient
            self._claude = AnthropicClient()
        return self._claude

    async def run_with_variants(
        self,
        input: AgentInput,
        tier_config: TierConfig,
    ) -> AgentOutput:
        """Generate multiple CTA variants and iterate each to quality bar.

        This is the main entry point. Generates N variants per tier,
        scores each, iterates the best ones, returns the winner.
        """
        cta_cfg = tier_config.cta
        variants = []
        all_iterations = []
        total_cost = 0.0

        # Generate N variants
        for v in range(cta_cfg.variants):
            output = await self.run(
                input=input,
                tier=tier_config,
                max_iterations=3,  # CTA gets 3 attempts max
                min_score=cta_cfg.min_score,
            )
            variants.append(output)
            all_iterations.extend(output.iterations)
            total_cost += output.cost_usd

        # Pick best variant by aggregate score
        best = max(variants, key=lambda v: v.final_scores.aggregate)

        return AgentOutput(
            agent_name=self.name,
            final_draft=best.final_draft,
            final_scores=best.final_scores,
            iterations=all_iterations,
            passed=best.passed,
            total_iterations=sum(v.total_iterations for v in variants),
            cost_usd=total_cost,
            variants=[v.final_draft for v in variants],
        )

    async def write(self, input: AgentInput, diagnosis: Optional[Diagnosis] = None) -> str:
        """Generate a CTA draft using Claude."""
        claude = await self._get_claude()

        # Build ammunition context
        ammo = ""
        if input.ammunition and input.ammunition.get("cta_ammunition"):
            facts = input.ammunition["cta_ammunition"][:5]
            ammo = "\n\nCTA Ammunition (actionable data points):\n"
            ammo += "\n".join(f"- {f}" for f in facts)

        # Build proven patterns context (from autopilot memory)
        patterns = ""
        if input.proven_patterns:
            patterns = "\n\nProven CTA Patterns (from channel performance data):\n"
            patterns += "\n".join(f"- {p}" for p in input.proven_patterns[:5])

        if input.anti_patterns:
            patterns += "\n\nAnti-Patterns (avoid these — they underperform):\n"
            patterns += "\n".join(f"- {p}" for p in input.anti_patterns[:3])

        # Build rewrite context
        rewrite_ctx = ""
        if diagnosis:
            rewrite_ctx = f"""

REWRITE REQUIRED — Previous draft failed quality gate:
Failed dimensions: {', '.join(diagnosis.failed_dimensions)}
Diagnosis: {diagnosis.diagnosis}
Guidance: {diagnosis.rewrite_guidance}

Write a NEW CTA addressing these specific issues. Do NOT repeat the same approach."""

        # Brand voice
        voice = input.brand_voice or (
            "Investigative, cinematic POV. Data lives inside characters. "
            "Past->Present->Future framing. Every revelation has numbers."
        )

        prompt = f"""Write a compelling video CTA (Act 6 "The Play" — the actionable close).

VIDEO TITLE: {input.video_title}
THESIS: {input.thesis or 'Not specified'}
FRAMEWORK: {input.framework_angle or 'Not specified'}
{ammo}
{patterns}
{rewrite_ctx}

RULES:
1. ~50-80 words maximum (speakable in 20-30 seconds)
2. MUST end on EMPOWERMENT — the viewer leaves feeling ARMED with knowledge, not helpless or doomed
3. Must contain at least one specific, actionable step the viewer can take (research, watch for, prepare)
4. Must reference specific data from the video to ground the call to action in evidence
5. Must bridge from "what you now know" to "what you can do with it"
6. NO generic subscribe/like CTAs — this is about arming the viewer, not engagement farming

BRAND VOICE: {voice}

EMPOWERMENT RULE (non-negotiable):
The final sentence MUST leave the viewer feeling powerful, informed, and equipped.
NOT: "The economy might collapse." (doom)
YES: "Now you know the three signals to watch — and you'll see them before the headlines do." (empowerment)

Write ONLY the CTA narration text. No labels, no scene directions, no commentary."""

        response = await claude.generate(
            prompt=prompt,
            system="You are a specialized CTA writer for documentary-style YouTube videos. "
                   "You write the final 20-30 seconds that send viewers away feeling empowered "
                   "and armed with actionable knowledge. Every CTA must end on strength, not fear.",
            max_tokens=300,
        )

        return response.strip()

    async def rewrite(self, input: AgentInput, last_iteration: Iteration) -> str:
        """Rewrite CTA with diagnosis context."""
        return await self.write(input, diagnosis=last_iteration.diagnosis)
