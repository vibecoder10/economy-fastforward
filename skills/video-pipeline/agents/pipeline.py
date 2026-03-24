"""Agent Pipeline Orchestrator — runs the full multi-agent quality pipeline.

This is the SaaS entry point. Takes a research payload in, outputs a
scored script with full paper trail. Tier controls cost vs quality.

Connects to the autoresearch compounding loop:
- Loads proven patterns from autopilot memory BEFORE writing
- After video publishes → agent scores get correlated with AVD/CTR
- Next cycle loads updated patterns → compounding improvement

Usage:
    from agents.pipeline import AgentPipeline
    from agents.config import QualityTier

    pipeline = AgentPipeline(tier=QualityTier.STANDARD)
    output = await pipeline.run(research_payload, video_title="...")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.config import QualityTier, TierConfig, get_tier_config
from agents.models import AgentInput, AgentOutput
from agents.hook_agent import HookAgent
from agents.hook_manager import HookManager
from agents.body_agent import BodyAgent
from agents.body_manager import BodyManager
from agents.cta_agent import CTAAgent
from agents.cta_manager import CTAManager
from agents.weapons_check import WeaponsCheck
from agents.ammunition_indexer import index_ammunition


@dataclass
class PipelineOutput:
    """Full output from the agent pipeline."""
    tier: str
    hook: AgentOutput
    body: Optional[AgentOutput] = None
    cta: Optional[AgentOutput] = None
    weapons_report: Optional[Dict[str, Any]] = None
    ammunition: Optional[Dict[str, List[str]]] = None
    full_script: str = ""
    total_cost: float = 0.0
    total_iterations: int = 0
    passed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tier": self.tier,
            "hook": self.hook.to_dict(),
            "body": self.body.to_dict() if self.body else None,
            "cta": self.cta.to_dict() if self.cta else None,
            "weapons_report": self.weapons_report,
            "full_script": self.full_script,
            "total_cost": round(self.total_cost, 2),
            "total_iterations": self.total_iterations,
            "passed": self.passed,
        }

    def to_paper_trail(self) -> Dict[str, Any]:
        """Generate the 3-tab paper trail output."""
        return {
            "research_tab": {
                "ammunition": self.ammunition or {},
            },
            "working_tab": {
                "hook_iterations": [i.to_dict() for i in self.hook.iterations],
                "body_iterations": [i.to_dict() for i in self.body.iterations] if self.body else [],
                "cta_iterations": [i.to_dict() for i in self.cta.iterations] if self.cta else [],
                "weapons_report": self.weapons_report,
            },
            "final_tab": {
                "script": self.full_script,
                "scores": {
                    "hook": round(self.hook.final_scores.aggregate, 1),
                    "body": round(self.body.final_scores.aggregate, 1) if self.body else None,
                    "cta": round(self.cta.final_scores.aggregate, 1) if self.cta else None,
                },
                "total_cost": round(self.total_cost, 2),
                "total_iterations": self.total_iterations,
            },
        }


class AgentPipeline:
    """Run the full agent pipeline. SaaS-ready interface.

    Orchestrates: Ammunition Indexing → Hook Agent → Body Agent →
    Weapons Check → CTA Agent → Assembly
    """

    def __init__(
        self,
        tier: QualityTier | str = QualityTier.STANDARD,
        claude_client=None,
        pattern_loader=None,
    ):
        self.tier_config = get_tier_config(tier)

        # Initialize agents with their managers
        self.hook_manager = HookManager(claude_client=claude_client)
        self.hook_agent = HookAgent(manager=self.hook_manager, claude_client=claude_client)

        self.body_manager = BodyManager(claude_client=claude_client)
        self.body_agent = BodyAgent(manager=self.body_manager, claude_client=claude_client)

        self.cta_manager = CTAManager(claude_client=claude_client)
        self.cta_agent = CTAAgent(manager=self.cta_manager, claude_client=claude_client)

        self.weapons_check = WeaponsCheck(claude_client=claude_client)

        self._pattern_loader = pattern_loader

    async def _load_patterns(self) -> tuple[list, list]:
        """Load proven/anti patterns from autopilot memory."""
        if self._pattern_loader:
            return self._pattern_loader()

        proven, anti = [], []
        try:
            from autopilot.learning.pattern_library import PatternLibrary
            library = PatternLibrary()
            proven = library.get_proven_patterns("hook", limit=5)
            anti = library.get_anti_patterns("hook", limit=3)
        except Exception:
            pass
        return proven, anti

    async def run(
        self,
        research_payload: Dict[str, Any],
        video_title: str,
        thesis: Optional[str] = None,
        framework_angle: Optional[str] = None,
        brand_voice: Optional[str] = None,
        hook_script: Optional[str] = None,
    ) -> PipelineOutput:
        """Run the full agent pipeline.

        Args:
            research_payload: 14-field research payload from research agent
            video_title: Video title
            thesis: Core thesis/argument
            framework_angle: Analytical framework
            brand_voice: Channel-specific voice (injected into all agent prompts)
            hook_script: Pre-existing hook to use instead of generating

        Returns:
            PipelineOutput with scored script and full paper trail
        """
        total_cost = 0.0
        total_iterations = 0

        # 1. Index ammunition from research
        ammunition = index_ammunition(research_payload)

        # 2. Load proven patterns from autopilot memory
        proven_patterns, anti_patterns = await self._load_patterns()

        # 3. Build agent input
        agent_input = AgentInput(
            research_payload=research_payload,
            video_title=video_title,
            thesis=thesis or research_payload.get("thesis", ""),
            framework_angle=framework_angle or research_payload.get("framework_analysis", ""),
            brand_voice=brand_voice,
            hook_script=hook_script,
            proven_patterns=proven_patterns,
            anti_patterns=anti_patterns,
            ammunition=ammunition,
        )

        # 4. Hook Agent
        hook_output = await self.hook_agent.run_with_variants(
            input=agent_input,
            tier_config=self.tier_config,
        )
        total_cost += hook_output.cost_usd
        total_iterations += hook_output.total_iterations

        # 5. Body Agent
        body_output = await self.body_agent.run_body(
            input=agent_input,
            tier_config=self.tier_config,
            approved_hook=hook_output.final_draft,
        )
        total_cost += body_output.cost_usd
        total_iterations += body_output.total_iterations

        # 6. Weapons Check
        full_draft = f"{hook_output.final_draft}\n\n{body_output.final_draft}"
        weapons_report = None

        if self.tier_config.weapons.granularity != "none":
            report = await self.weapons_check.check(
                script=full_draft,
                granularity=self.tier_config.weapons.granularity,
                min_novelty=self.tier_config.weapons.min_novelty,
                min_intensity=self.tier_config.weapons.min_intensity,
                filler_threshold=self.tier_config.weapons.filler_threshold,
            )
            weapons_report = report.to_dict()
            total_cost += 0.03 * len(report.blocks)  # Estimate per-block cost

        # 7. CTA Agent (if enabled)
        cta_output = None
        if self.tier_config.cta.enabled:
            cta_output = await self.cta_agent.run_with_variants(
                input=agent_input,
                tier_config=self.tier_config,
            )
            total_cost += cta_output.cost_usd
            total_iterations += cta_output.total_iterations

        # 8. Assemble full script
        parts = [hook_output.final_draft, body_output.final_draft]
        if cta_output:
            parts.append(cta_output.final_draft)
        full_script = "\n\n".join(parts)

        # 9. Determine overall pass
        all_passed = hook_output.passed and body_output.passed
        if cta_output:
            all_passed = all_passed and cta_output.passed

        return PipelineOutput(
            tier=self.tier_config.tier.value,
            hook=hook_output,
            body=body_output,
            cta=cta_output,
            weapons_report=weapons_report,
            ammunition=ammunition,
            full_script=full_script,
            total_cost=total_cost,
            total_iterations=total_iterations,
            passed=all_passed,
        )
