"""Claude Orchestrator — intelligent decision-making for pipeline execution.

Replaces the dumb status-to-handler map with Claude-driven decisions.
Claude reads context (video state, available skills, learnings, user intent)
and returns a structured decision about what to do next.

Usage:
    orchestrator = ClaudeOrchestrator(tenant_id="...")
    decision = await orchestrator.decide(video_id)
    result = await orchestrator.execute(decision, video_id)

Design: Single Claude API call per decision (Option C — Claude decides, Python executes).
No agent sessions, no mid-execution adaptation. Post-mortem learning happens via autopilot.
"""

import os
import sys
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from pydantic import BaseModel, Field

# Add pipeline to path
PIPELINE_PATH = Path(__file__).parent.parent.parent / "skills" / "video-pipeline"
if str(PIPELINE_PATH) not in sys.path:
    sys.path.insert(0, str(PIPELINE_PATH))

from shared.skill_registry import get_registry, SkillManifest
from database import fetch_one, fetch_all, execute


# --- Models ---

class Decision(BaseModel):
    """A structured decision from Claude about what to do next."""
    action: str = "invoke_skill"  # invoke_skill, wait, ask_user, skip
    skill_id: Optional[str] = None
    reasoning: str = ""
    parameters: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0  # 0-1, below threshold = ask user
    alternatives: List[Dict[str, str]] = Field(default_factory=list)
    estimated_cost: float = 0.0


class OrchestratorResult(BaseModel):
    """Result of executing a decision."""
    success: bool
    decision: Decision
    execution_result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


# --- Orchestrator ---

class ClaudeOrchestrator:
    """Intelligent pipeline orchestrator powered by Claude.

    Makes one Claude API call per decision point. Reads video state,
    available skills, tenant learnings, and optional user intent to
    determine what skill to invoke and with what parameters.
    """

    CONFIDENCE_THRESHOLD = 0.7  # Below this, return alternatives for user approval
    DECISION_MODEL = "claude-sonnet-4-20250514"

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self._registry = get_registry(PIPELINE_PATH)

    async def _get_video_context(self, video_id: str) -> Dict[str, Any]:
        """Load video state from Supabase."""
        video = await fetch_one(
            "SELECT * FROM videos WHERE id = $1 AND tenant_id = $2",
            video_id, self.tenant_id,
        )
        if not video:
            return {}
        return dict(video)

    async def _get_tenant_learnings(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Load top learnings for this tenant."""
        try:
            rows = await fetch_all(
                """SELECT category, pattern, confidence, avg_ctr
                   FROM learnings
                   WHERE tenant_id = $1 AND active = true
                   ORDER BY confidence DESC
                   LIMIT $2""",
                self.tenant_id, limit,
            )
            return [dict(r) for r in rows] if rows else []
        except Exception:
            return []

    async def _get_recent_activity(self, video_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Get recent bot activity for this video."""
        try:
            rows = await fetch_all(
                """SELECT bot_name, status, message, cost, created_at
                   FROM bot_activity
                   WHERE video_id = $1 AND tenant_id = $2
                   ORDER BY created_at DESC
                   LIMIT $3""",
                video_id, self.tenant_id, limit,
            )
            return [dict(r) for r in rows] if rows else []
        except Exception:
            return []

    def _build_context_prompt(
        self,
        video: Dict[str, Any],
        skills_context: str,
        learnings: List[Dict[str, Any]],
        activity: List[Dict[str, Any]],
        user_intent: Optional[str] = None,
    ) -> str:
        """Build the prompt that Claude receives to make a decision."""
        status = video.get("status", "unknown")
        title = video.get("video_title", "Untitled")

        learnings_text = ""
        if learnings:
            learnings_text = "\n\nTenant Learnings (proven patterns):\n"
            for l in learnings:
                ctr = f" (avg CTR: {l['avg_ctr']}%)" if l.get('avg_ctr') else ""
                learnings_text += f"- [{l.get('category', '?')}] {l.get('pattern', '')}{ctr}\n"

        activity_text = ""
        if activity:
            activity_text = "\n\nRecent Activity:\n"
            for a in activity:
                activity_text += f"- {a.get('bot_name', '?')}: {a.get('status', '?')} — {a.get('message', '')}\n"

        intent_text = ""
        if user_intent:
            intent_text = f"\n\nUser Intent: {user_intent}"

        return f"""You are the pipeline orchestrator for a YouTube video production system.
Your job: decide which skill to invoke next for this video.

Current Video:
- Title: {title}
- Status: {status}
- Video ID: {video.get('id', 'unknown')}

{skills_context}
{learnings_text}
{activity_text}
{intent_text}

Based on the video's current status and context, decide:
1. Which skill to invoke next (skill_id from the list above)
2. Any parameter overrides based on learnings or user intent
3. Your confidence level (0-1)

If the status doesn't match any skill's required_status, or if the video is done,
set action to "wait" or "skip" with an explanation.

Respond with a JSON object:
{{
  "action": "invoke_skill" | "wait" | "ask_user" | "skip",
  "skill_id": "<skill_id or null>",
  "reasoning": "<why this decision>",
  "parameters": {{}},
  "confidence": <0.0-1.0>,
  "alternatives": [{{"skill_id": "...", "reason": "..."}}],
  "estimated_cost": <USD>
}}"""

    async def decide(
        self,
        video_id: str,
        user_intent: Optional[str] = None,
    ) -> Decision:
        """Make a decision about what to do next for a video.

        This is the core intelligence — one Claude API call that reads
        all context and returns a structured decision.

        Args:
            video_id: Supabase video UUID
            user_intent: Optional natural language from user (e.g., "make thumbnail more aggressive")

        Returns:
            Decision with skill_id, parameters, reasoning, and confidence
        """
        # Gather context
        video = await self._get_video_context(video_id)
        if not video:
            return Decision(
                action="skip",
                reasoning="Video not found",
                confidence=1.0,
            )

        learnings = await self._get_tenant_learnings()
        activity = await self._get_recent_activity(video_id)
        skills_context = self._registry.to_context_string()

        # Build prompt
        prompt = self._build_context_prompt(
            video, skills_context, learnings, activity, user_intent
        )

        # Call Claude
        try:
            import anthropic

            client = anthropic.Anthropic()
            response = client.messages.create(
                model=self.DECISION_MODEL,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )

            # Parse response
            response_text = response.content[0].text
            # Extract JSON from response (handle markdown fences)
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0]

            decision_data = json.loads(response_text.strip())
            decision = Decision(**decision_data)

            # Validate skill_id exists
            if decision.skill_id and not self._registry.get_skill(decision.skill_id):
                decision.action = "skip"
                decision.reasoning = f"Claude suggested unknown skill: {decision.skill_id}"
                decision.confidence = 0.0

            return decision

        except Exception as e:
            # Fallback: use the dumb status map (never block on Claude failure)
            return self._fallback_decision(video)

    def _fallback_decision(self, video: Dict[str, Any]) -> Decision:
        """Fallback when Claude API fails — use status-based routing."""
        status = video.get("status", "")
        skills = self._registry.get_skills_for_status(status)

        if skills:
            skill = skills[0]
            return Decision(
                action="invoke_skill",
                skill_id=skill.skill_id,
                reasoning=f"Fallback: status '{status}' maps to '{skill.skill_id}' (Claude API unavailable)",
                confidence=0.9,
                estimated_cost=skill.estimated_cost,
            )

        return Decision(
            action="wait",
            reasoning=f"No skill matches status '{status}'",
            confidence=1.0,
        )

    async def execute(
        self,
        decision: Decision,
        video_id: str,
        executor: Any = None,
    ) -> OrchestratorResult:
        """Execute a decision by invoking the chosen skill.

        Args:
            decision: The decision to execute
            video_id: Supabase video UUID
            executor: PipelineExecutor instance

        Returns:
            OrchestratorResult with success/failure and execution details
        """
        if decision.action != "invoke_skill" or not decision.skill_id:
            return OrchestratorResult(
                success=True,
                decision=decision,
                execution_result={"action": decision.action, "reasoning": decision.reasoning},
            )

        if not executor:
            return OrchestratorResult(
                success=False,
                decision=decision,
                error="No executor provided",
            )

        # Map skill_id to existing executor method
        skill_to_method = {
            "research": executor.run_research,
            "script": executor.run_script,
            "voice": executor.run_voice,
            "image_prompts": executor.run_prompts,
            "storyboard": executor.run_storyboard_prompts,
            "images": executor.run_images,
            "sound": executor.run_sound_prompts,
            "video_motion": executor.run_video_scripts,
            "thumbnail": executor.run_thumbnail,
            "render": executor.run_render,
            "upload": executor.run_upload,
        }

        method = skill_to_method.get(decision.skill_id)
        if not method:
            return OrchestratorResult(
                success=False,
                decision=decision,
                error=f"No executor method for skill '{decision.skill_id}'",
            )

        try:
            # Log the decision
            await execute(
                """INSERT INTO bot_activity (tenant_id, bot_name, video_id, status, message, cost)
                   VALUES ($1, $2, $3, $4, $5, $6)""",
                self.tenant_id,
                "Claude Orchestrator",
                video_id,
                "decided",
                f"Invoking {decision.skill_id}: {decision.reasoning}",
                0,
            )

            # Execute the skill
            result = await method(video_id)

            return OrchestratorResult(
                success=not result.get("error"),
                decision=decision,
                execution_result=result,
                error=result.get("error"),
            )

        except Exception as e:
            from error_utils import humanize_error
            return OrchestratorResult(
                success=False,
                decision=decision,
                error=humanize_error(e, context=f"Executing {decision.skill_id} hit an error"),
            )
