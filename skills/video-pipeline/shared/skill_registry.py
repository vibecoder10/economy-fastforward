"""Skill Registry — discovers and manages pipeline skills from manifest.json files.

Each bot folder can register itself as a skill by including a manifest.json.
The registry scans for these at startup and provides a queryable interface
for the Claude orchestrator and API layer.

Usage:
    from shared.skill_registry import get_registry

    registry = get_registry()
    skills = registry.list_skills()
    voice = registry.get_skill("voice")
    pipeline_skills = registry.get_pipeline_skills()
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CostEstimate(BaseModel):
    """Estimated cost for running this skill."""
    per_run: float = 0.0
    per_video: float = 0.0
    unit: str = "USD"


class ConfigParam(BaseModel):
    """A configurable parameter for a skill."""
    type: str = "string"
    default: Any = None
    description: str = ""


class SkillManifest(BaseModel):
    """Metadata describing a pipeline skill."""
    skill_id: str
    name: str
    type: str = "pipeline_stage"  # pipeline_stage, data_gathering, quality_agent
    description: str = ""
    entry_point: str = ""  # Python module path (e.g., "voice.run")
    function: Optional[str] = None  # Single entry function name
    functions: Optional[Dict[str, str]] = None  # Multiple entry functions
    pipeline_stage: bool = True
    required_status: Optional[str] = None
    output_status: Optional[str] = None
    output_status_alt: Optional[str] = None  # Alternate output (e.g., storyboard branch)
    required_keys: List[str] = Field(default_factory=list)
    inputs: List[str] = Field(default_factory=list)
    outputs: List[str] = Field(default_factory=list)
    cost_estimate: CostEstimate = Field(default_factory=CostEstimate)
    dependencies: List[str] = Field(default_factory=list)
    configurable_params: Dict[str, Any] = Field(default_factory=dict)

    @property
    def estimated_cost(self) -> float:
        """Get the primary cost estimate."""
        return self.cost_estimate.per_run or self.cost_estimate.per_video


class SkillRegistry:
    """Registry of all available pipeline skills.

    Scans bot folders for manifest.json files and provides
    query methods for the orchestrator and API layer.
    """

    def __init__(self, pipeline_root: Optional[Path] = None):
        self._skills: Dict[str, SkillManifest] = {}
        self._pipeline_root = pipeline_root or Path(__file__).parent.parent

    def load(self) -> None:
        """Scan all directories for manifest.json files."""
        self._skills.clear()

        for manifest_path in self._pipeline_root.glob("*/manifest.json"):
            try:
                data = json.loads(manifest_path.read_text())
                manifest = SkillManifest(**data)
                self._skills[manifest.skill_id] = manifest
            except Exception as e:
                print(f"[skill_registry] Failed to load {manifest_path}: {e}")

    def get_skill(self, skill_id: str) -> Optional[SkillManifest]:
        """Get a skill by ID."""
        return self._skills.get(skill_id)

    def list_skills(self) -> List[SkillManifest]:
        """List all registered skills."""
        return list(self._skills.values())

    def get_pipeline_skills(self) -> List[SkillManifest]:
        """Get skills that are part of the main pipeline (status-driven)."""
        return [s for s in self._skills.values() if s.pipeline_stage]

    def get_pipeline_order(self) -> List[SkillManifest]:
        """Get pipeline skills in execution order (topological sort by dependencies)."""
        pipeline = self.get_pipeline_skills()

        # Simple topological sort
        ordered = []
        remaining = {s.skill_id: s for s in pipeline}
        resolved = set()

        while remaining:
            # Find skills whose dependencies are all resolved
            ready = [
                s for s in remaining.values()
                if all(d in resolved or d not in remaining for d in s.dependencies)
            ]

            if not ready:
                # Circular dependency or missing dep — add remaining in any order
                ordered.extend(remaining.values())
                break

            for skill in ready:
                ordered.append(skill)
                resolved.add(skill.skill_id)
                del remaining[skill.skill_id]

        return ordered

    def get_skills_for_status(self, status: str) -> List[SkillManifest]:
        """Get skills that can run at a given pipeline status."""
        return [
            s for s in self._skills.values()
            if s.required_status == status
        ]

    def get_available_skills(self, configured_keys: List[str]) -> List[SkillManifest]:
        """Get skills available to a tenant based on their configured API keys."""
        return [
            s for s in self._skills.values()
            if all(k in configured_keys for k in s.required_keys)
        ]

    def get_total_pipeline_cost(self) -> float:
        """Estimate total cost to run the full pipeline."""
        return sum(s.estimated_cost for s in self.get_pipeline_skills())

    def to_context_string(self, skills: Optional[List[SkillManifest]] = None) -> str:
        """Format skills as a context string for Claude orchestrator prompts."""
        skills = skills or self.list_skills()
        lines = ["Available Skills:"]
        for s in skills:
            cost = f"~${s.estimated_cost:.2f}" if s.estimated_cost else "free"
            status = f" (requires: {s.required_status})" if s.required_status else ""
            lines.append(f"- {s.skill_id}: {s.description} [{cost}]{status}")
            if s.configurable_params:
                for param, config in s.configurable_params.items():
                    desc = config.get("description", "") if isinstance(config, dict) else ""
                    lines.append(f"    param: {param} — {desc}")
        return "\n".join(lines)

    @property
    def skill_count(self) -> int:
        return len(self._skills)


# Module-level singleton
_registry: Optional[SkillRegistry] = None


def get_registry(pipeline_root: Optional[Path] = None) -> SkillRegistry:
    """Get or create the skill registry singleton."""
    global _registry
    if _registry is None:
        _registry = SkillRegistry(pipeline_root)
        _registry.load()
    return _registry


def reload_registry() -> SkillRegistry:
    """Force reload the registry (useful after adding new skills)."""
    global _registry
    _registry = None
    return get_registry()
