"""Quality tier configuration for the agent pipeline.

Tiers control cost vs quality tradeoff. Each tier defines how many
iterations, variants, and checks each agent performs.

SaaS-ready: tier is a config field set per-video or per-tenant,
not hardcoded. Scoring weights and thresholds are also configurable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict


class QualityTier(str, Enum):
    FAST = "fast"           # ~$3, 1 iteration, no weapons check
    STANDARD = "standard"   # ~$8, 3 iterations, act-level weapons check
    PREMIUM = "premium"     # ~$20, full pipeline, line-level weapons check


@dataclass
class HookConfig:
    """Hook agent configuration per tier."""
    variants: int = 2           # How many hook options to generate
    max_iterations: int = 3     # Max rewrite cycles per hook
    min_score: int = 70         # Minimum aggregate score to pass (0-100)


@dataclass
class BodyConfig:
    """Body agent configuration per tier."""
    max_iterations: int = 2
    min_score: int = 70


@dataclass
class WeaponsConfig:
    """Weapons check configuration per tier."""
    granularity: str = "none"   # "none" | "act" | "line"
    min_novelty: int = 7        # Minimum invention novelty score (0-10)
    min_intensity: int = 7      # Minimum copy intensity score (0-10)
    filler_threshold: int = 5   # Both below this = cut entirely


@dataclass
class CTAConfig:
    """CTA agent configuration per tier."""
    enabled: bool = False
    variants: int = 1
    min_score: int = 60


@dataclass
class TierConfig:
    """Full configuration for a quality tier."""
    tier: QualityTier
    hook: HookConfig
    body: BodyConfig
    weapons: WeaponsConfig
    cta: CTAConfig
    model: str = "claude-sonnet-4-20250514"  # Claude model for all agents


# --- Default Tier Configurations ---

TIER_CONFIGS: Dict[QualityTier, TierConfig] = {
    QualityTier.FAST: TierConfig(
        tier=QualityTier.FAST,
        hook=HookConfig(variants=1, max_iterations=1, min_score=50),
        body=BodyConfig(max_iterations=1, min_score=50),
        weapons=WeaponsConfig(granularity="none"),
        cta=CTAConfig(enabled=False),
    ),
    QualityTier.STANDARD: TierConfig(
        tier=QualityTier.STANDARD,
        hook=HookConfig(variants=2, max_iterations=3, min_score=70),
        body=BodyConfig(max_iterations=2, min_score=70),
        weapons=WeaponsConfig(granularity="act", min_novelty=7, min_intensity=7),
        cta=CTAConfig(enabled=True, variants=1, min_score=60),
    ),
    QualityTier.PREMIUM: TierConfig(
        tier=QualityTier.PREMIUM,
        hook=HookConfig(variants=4, max_iterations=3, min_score=85),
        body=BodyConfig(max_iterations=3, min_score=80),
        weapons=WeaponsConfig(granularity="line", min_novelty=7, min_intensity=7, filler_threshold=5),
        cta=CTAConfig(enabled=True, variants=2, min_score=70),
        model="claude-sonnet-4-20250514",
    ),
}


# --- Default Scoring Weights ---

DEFAULT_HOOK_WEIGHTS = {
    "data_backing": 0.25,
    "curiosity_gap": 0.25,
    "emotional_trigger": 0.20,
    "specificity": 0.20,
    "time_constraint": 0.10,
}

DEFAULT_BODY_WEIGHTS = {
    "promise_fulfillment": 0.30,
    "micro_payoff_density": 0.25,
    "character_consistency": 0.25,
    "pacing": 0.20,
}


def get_tier_config(tier: str | QualityTier) -> TierConfig:
    """Get config for a tier, with fallback to STANDARD."""
    if isinstance(tier, str):
        try:
            tier = QualityTier(tier.lower())
        except ValueError:
            tier = QualityTier.STANDARD
    return TIER_CONFIGS.get(tier, TIER_CONFIGS[QualityTier.STANDARD])
