"""Data models for the multi-agent quality pipeline.

All agents share these models for consistent input/output and scoring.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


@dataclass
class AgentInput:
    """Input to any agent in the pipeline."""
    research_payload: Dict[str, Any]
    video_title: str
    hook_script: Optional[str] = None  # From idea concept
    thesis: Optional[str] = None
    framework_angle: Optional[str] = None
    brand_voice: Optional[str] = None  # Channel-specific voice description
    proven_patterns: List[str] = field(default_factory=list)  # From autopilot memory
    anti_patterns: List[str] = field(default_factory=list)
    ammunition: Optional[Dict[str, List[str]]] = None  # Indexed research facts


@dataclass
class ScoreDimension:
    """A single scoring dimension with its result."""
    name: str
    score: int  # 0-10
    weight: float  # 0.0-1.0
    reasoning: str = ""


@dataclass
class ScoreCard:
    """Multi-dimensional score from a manager."""
    dimensions: List[ScoreDimension]
    aggregate: float = 0.0  # Weighted average, 0-100
    passed: bool = False
    gate_threshold: int = 0

    def __post_init__(self):
        if self.dimensions and self.aggregate == 0.0:
            self.aggregate = self._calculate_aggregate()

    def _calculate_aggregate(self) -> float:
        total_weight = sum(d.weight for d in self.dimensions)
        if total_weight == 0:
            return 0.0
        weighted_sum = sum(d.score * d.weight for d in self.dimensions)
        return (weighted_sum / total_weight) * 10  # Scale to 0-100

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dimensions": [
                {"name": d.name, "score": d.score, "weight": d.weight, "reasoning": d.reasoning}
                for d in self.dimensions
            ],
            "aggregate": round(self.aggregate, 1),
            "passed": self.passed,
            "gate_threshold": self.gate_threshold,
        }


@dataclass
class Diagnosis:
    """Actionable feedback from a manager when a draft fails the gate."""
    failed_dimensions: List[str]  # Which dimensions scored lowest
    diagnosis: str  # What's wrong (specific, actionable)
    rewrite_guidance: str  # How to fix it
    priority: str = "high"  # high, medium, low


@dataclass
class Iteration:
    """Record of one write → score → diagnose cycle."""
    iteration_number: int
    draft: str
    scores: ScoreCard
    diagnosis: Optional[Diagnosis] = None
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "iteration": self.iteration_number,
            "draft": self.draft,
            "scores": self.scores.to_dict(),
            "diagnosis": {
                "failed_dimensions": self.diagnosis.failed_dimensions,
                "diagnosis": self.diagnosis.diagnosis,
                "rewrite_guidance": self.diagnosis.rewrite_guidance,
            } if self.diagnosis else None,
            "timestamp": self.timestamp,
        }


@dataclass
class AgentOutput:
    """Output from any agent — includes the final draft and full paper trail."""
    agent_name: str
    final_draft: str
    final_scores: ScoreCard
    iterations: List[Iteration] = field(default_factory=list)
    passed: bool = False
    total_iterations: int = 0
    cost_usd: float = 0.0
    variants: List[str] = field(default_factory=list)  # For agents that generate multiple options

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent": self.agent_name,
            "final_draft": self.final_draft,
            "final_scores": self.final_scores.to_dict(),
            "passed": self.passed,
            "total_iterations": self.total_iterations,
            "cost_usd": round(self.cost_usd, 4),
            "iterations": [i.to_dict() for i in self.iterations],
        }
