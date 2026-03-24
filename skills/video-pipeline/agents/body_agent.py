"""Body Agent — specialized writer for the script body (Acts 2-5).

The body is where the hook's promise gets fulfilled. Each act must deliver
a micro-payoff (revelation, insight, or emotional beat) roughly every 90
seconds to keep viewers watching. Data always lives inside characters —
never presented as raw info-dump.

Receives the approved hook text and writes acts 2-5 to fulfill the
hook's implied promise while maintaining brand voice (Past -> Present ->
Future framing, investigative cinematic POV).

Connects to autopilot memory: loads proven body patterns from LEARNINGS.md.
After video performance is measured, body scores get correlated with
retention curves — feeding the autoresearch compounding loop.
"""

from __future__ import annotations

import json
from typing import Optional

from agents.base_agent import BaseAgent, BaseManager
from agents.models import AgentInput, AgentOutput, Diagnosis, Iteration
from agents.config import TierConfig, BodyConfig


class BodyAgent(BaseAgent):
    """Writes the script body (Acts 2-5) to fulfill the hook's promise."""

    name = "Body Agent"

    def __init__(self, manager: BaseManager, claude_client=None):
        super().__init__(manager)
        self._claude = claude_client

    async def _get_claude(self):
        """Lazy-load Claude client."""
        if self._claude is None:
            from shared.clients.anthropic_client import AnthropicClient
            self._claude = AnthropicClient()
        return self._claude

    async def run_body(
        self,
        input: AgentInput,
        tier_config: TierConfig,
        approved_hook: str,
    ) -> AgentOutput:
        """Generate Acts 2-5, iterating until quality bar passes.

        Args:
            input: Research payload and context
            tier_config: Quality tier configuration
            approved_hook: The approved hook text (Act 1) this body must fulfill

        Returns:
            AgentOutput with final body draft and full paper trail
        """
        body_cfg = tier_config.body

        # Stash approved hook on input so write() can reference it
        input.hook_script = approved_hook

        output = await self.run(
            input=input,
            tier=tier_config,
            max_iterations=body_cfg.max_iterations,
            min_score=body_cfg.min_score,
        )
        return output

    async def write(self, input: AgentInput, diagnosis: Optional[Diagnosis] = None) -> str:
        """Generate Acts 2-5 body narration using Claude."""
        claude = await self._get_claude()

        # Build research context
        research = ""
        rp = input.research_payload or {}
        if rp.get("fact_sheet"):
            research += f"\nFACT SHEET:\n{rp['fact_sheet']}"
        if rp.get("historical_parallels"):
            research += f"\nHISTORICAL PARALLELS:\n{rp['historical_parallels']}"
        if rp.get("character_dossier"):
            research += f"\nCHARACTER DOSSIER:\n{rp['character_dossier']}"
        if rp.get("counter_arguments"):
            research += f"\nCOUNTER-ARGUMENTS:\n{rp['counter_arguments']}"

        # Build ammunition context
        ammo = ""
        if input.ammunition and input.ammunition.get("body_ammunition"):
            facts = input.ammunition["body_ammunition"][:10]
            ammo = "\n\nBody Ammunition (key facts for Acts 2-5):\n"
            ammo += "\n".join(f"- {f}" for f in facts)

        # Build proven patterns context
        patterns = ""
        if input.proven_patterns:
            patterns = "\n\nProven Body Patterns (from channel performance data):\n"
            patterns += "\n".join(f"- {p}" for p in input.proven_patterns[:5])
        if input.anti_patterns:
            patterns += "\n\nAnti-Patterns (avoid these — they lose viewers):\n"
            patterns += "\n".join(f"- {p}" for p in input.anti_patterns[:3])

        # Build rewrite context
        rewrite_ctx = ""
        if diagnosis:
            rewrite_ctx = f"""

REWRITE REQUIRED — Previous draft failed quality gate:
Failed dimensions: {', '.join(diagnosis.failed_dimensions)}
Diagnosis: {diagnosis.diagnosis}
Guidance: {diagnosis.rewrite_guidance}

Write a NEW body addressing these specific issues. Do NOT repeat the same approach."""

        # Brand voice
        voice = input.brand_voice or (
            "Investigative, cinematic POV. Data lives inside characters. "
            "Past->Present->Future framing. Every revelation has numbers."
        )

        hook_text = input.hook_script or "(no hook provided)"

        prompt = f"""Write the script body (Acts 2-5) for a documentary-style YouTube video.

VIDEO TITLE: {input.video_title}
THESIS: {input.thesis or 'Not specified'}
FRAMEWORK: {input.framework_angle or 'Not specified'}

APPROVED HOOK (Act 1 — the promise you MUST fulfill):
"{hook_text}"
{research}
{ammo}
{patterns}
{rewrite_ctx}

STRUCTURE (4 acts, ~750 words each, ~3000 words total):

ACT 2 — THE SETUP (minutes 1-4):
Establish the world. Who are the players? What's at stake?
Ground the viewer in the situation with specific details.

ACT 3 — THE ESCALATION (minutes 4-7):
Raise the stakes. Introduce complications, hidden factors, or
surprising connections. Each revelation should be a mini "whoa" moment.

ACT 4 — THE TURN (minutes 7-10):
The paradigm shift. What does the viewer NOT see coming?
This is the "everything you thought was wrong" moment.

ACT 5 — THE IMPLICATIONS (minutes 10-13):
So what? What does this mean for the viewer, the world, the future?
Past->Present->Future framing lands here.

RULES:
1. Every 90 seconds (~225 words), deliver a micro-payoff: a revelation, a
   surprising fact, or an emotional beat that re-hooks the viewer
2. Data ALWAYS lives inside characters — "Zhang Wei knew the $3.2T figure
   by heart" not "China holds $3.2T in US Treasuries"
3. Maintain the hook's promise — if the hook raises a question, the body
   must ANSWER it by Act 5
4. No info-dumps. Every paragraph must move the narrative forward.
5. Each act should be clearly separated with a blank line and act label

BRAND VOICE: {voice}

Write Acts 2-5 only. Label each act. No scene directions or commentary."""

        response = await claude.generate(
            prompt=prompt,
            system="You are a specialized body writer for documentary-style YouTube videos. "
                   "You write Acts 2-5 — the substance that fulfills the hook's promise. "
                   "Every 90 seconds must deliver a micro-payoff. Data lives inside characters, "
                   "never as raw statistics. Past->Present->Future framing throughout.",
            max_tokens=4000,
        )

        return response.strip()

    async def rewrite(self, input: AgentInput, last_iteration: Iteration) -> str:
        """Rewrite body with diagnosis context."""
        return await self.write(input, diagnosis=last_iteration.diagnosis)
