"""Hook Agent — specialized writer for video hooks (Act 1, first 15 seconds).

The hook is the #1 lever for AVD (average view duration). A strong hook
keeps viewers past the critical 15-second mark where YouTube decides to
promote. Thumbnail+title drive CTR (clicks); the hook drives retention.

This agent generates multiple hook variants, each scored on 5 dimensions
by the HookManager, iterating until quality gate passes.

Connects to autopilot memory: loads proven hook patterns from LEARNINGS.md.
After video performance is measured, hook scores get correlated with AVD —
feeding the same autoresearch compounding loop (Karpathy pattern).
"""

from __future__ import annotations

import json
from typing import Optional

from agents.base_agent import BaseAgent, BaseManager
from agents.models import AgentInput, AgentOutput, Diagnosis, Iteration
from agents.config import TierConfig, HookConfig


class HookAgent(BaseAgent):
    """Writes hooks — the first 15 seconds that determine if viewers stay."""

    name = "Hook Agent"

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
        """Generate multiple hook variants and iterate each to quality bar.

        This is the main entry point. Generates N variants per tier,
        scores each, iterates the best ones, returns the winner.
        """
        hook_cfg = tier_config.hook
        variants = []
        all_iterations = []
        total_cost = 0.0

        # Generate N variants
        for v in range(hook_cfg.variants):
            output = await self.run(
                input=input,
                tier=tier_config,
                max_iterations=hook_cfg.max_iterations,
                min_score=hook_cfg.min_score,
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
        """Generate a hook draft using Claude."""
        claude = await self._get_claude()

        # Build ammunition context
        ammo = ""
        if input.ammunition and input.ammunition.get("hook_ammunition"):
            facts = input.ammunition["hook_ammunition"][:5]
            ammo = "\n\nHook Ammunition (highest surprise-value facts):\n"
            ammo += "\n".join(f"- {f}" for f in facts)

        # Build proven patterns context (from autopilot memory)
        patterns = ""
        if input.proven_patterns:
            patterns = "\n\nProven Hook Patterns (from channel performance data):\n"
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

Write a NEW hook addressing these specific issues. Do NOT repeat the same approach."""

        # Brand voice
        voice = input.brand_voice or (
            "Investigative, cinematic POV. Data lives inside characters. "
            "Past→Present→Future framing. Every revelation has numbers."
        )

        prompt = f"""Write a compelling video hook (Act 1, first 15 seconds of narration).

VIDEO TITLE: {input.video_title}
THESIS: {input.thesis or 'Not specified'}
FRAMEWORK: {input.framework_angle or 'Not specified'}
{ammo}
{patterns}
{rewrite_ctx}

RULES:
1. ~70 words maximum (speakable in 15 seconds at 2.5 words/sec)
2. Must contain at least one specific, verifiable claim (number, name, date)
3. Must create a question the viewer NEEDS answered — don't state the conclusion
4. Must make the viewer FEEL something (fear, outrage, curiosity, awe)
5. Must be a concrete scene, not an abstraction — put the viewer somewhere specific

BRAND VOICE: {voice}

Write ONLY the hook narration text. No labels, no scene directions, no commentary."""

        response = await claude.generate(
            prompt=prompt,
            system="You are a specialized hook writer for documentary-style YouTube videos. "
                   "You write the first 15 seconds of narration that determine whether "
                   "viewers stay or leave. Every word must earn its place.",
            max_tokens=300,
        )

        return response.strip()

    async def rewrite(self, input: AgentInput, last_iteration: Iteration) -> str:
        """Rewrite hook with diagnosis context."""
        return await self.write(input, diagnosis=last_iteration.diagnosis)
