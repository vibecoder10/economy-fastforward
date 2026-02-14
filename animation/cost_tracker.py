"""Cost tracking and budget enforcement for the animation pipeline."""

from typing import Optional

from animation.config import (
    VEO_COST_PER_CLIP,
    IMAGE_COST_PER_IMAGE,
    ANIMATION_BUDGET_DEFAULT,
    BUDGET_ALERT_THRESHOLD,
)


class CostTracker:
    """Tracks per-scene and per-video animation costs with budget enforcement."""

    def __init__(self, budget: Optional[float] = None):
        """Initialize cost tracker.

        Args:
            budget: Maximum animation budget. Uses default if not provided.
        """
        self.budget = budget or ANIMATION_BUDGET_DEFAULT
        self.total_spend = 0.0
        self.scene_costs: dict[int, float] = {}  # scene_order -> cost

    @property
    def remaining_budget(self) -> float:
        """How much budget remains."""
        return max(0.0, self.budget - self.total_spend)

    @property
    def budget_percentage(self) -> float:
        """Current spend as percentage of budget (0-100)."""
        if self.budget <= 0:
            return 100.0
        return (self.total_spend / self.budget) * 100

    @property
    def budget_exceeded(self) -> bool:
        """Whether total spend has exceeded the budget."""
        return self.total_spend > self.budget

    @property
    def budget_alert(self) -> bool:
        """Whether spend has crossed the alert threshold."""
        return self.total_spend >= (self.budget * BUDGET_ALERT_THRESHOLD)

    def record_image_cost(self, scene_order: int) -> float:
        """Record the cost of generating one image.

        Returns:
            The cost recorded.
        """
        cost = IMAGE_COST_PER_IMAGE
        self._add_cost(scene_order, cost)
        return cost

    def record_animation_cost(self, scene_order: int) -> float:
        """Record the cost of one Veo animation clip.

        Returns:
            The cost recorded.
        """
        cost = VEO_COST_PER_CLIP
        self._add_cost(scene_order, cost)
        return cost

    def get_scene_cost(self, scene_order: int) -> float:
        """Get total cost for a specific scene."""
        return self.scene_costs.get(scene_order, 0.0)

    def estimate_remaining_cost(
        self,
        animated_scenes_left: int,
        kb_scenes_left: int,
        static_scenes_left: int,
    ) -> float:
        """Estimate the cost to complete remaining scenes.

        Args:
            animated_scenes_left: Number of animated scenes still needed
            kb_scenes_left: Number of ken_burns scenes still needed
            static_scenes_left: Number of static scenes still needed

        Returns:
            Estimated remaining cost
        """
        # Animated: 2 images + 1 animation
        animated_cost = animated_scenes_left * (2 * IMAGE_COST_PER_IMAGE + VEO_COST_PER_CLIP)
        # Ken Burns: 1 image (start frame only, pan/zoom in Remotion)
        kb_cost = kb_scenes_left * IMAGE_COST_PER_IMAGE
        # Static: 1 image
        static_cost = static_scenes_left * IMAGE_COST_PER_IMAGE

        return animated_cost + kb_cost + static_cost

    def can_afford_scene(self, scene_type: str) -> bool:
        """Check if the budget allows generating another scene.

        Args:
            scene_type: "animated", "ken_burns", or "static"

        Returns:
            True if within budget
        """
        if scene_type == "animated":
            needed = 2 * IMAGE_COST_PER_IMAGE + VEO_COST_PER_CLIP
        elif scene_type == "ken_burns":
            needed = IMAGE_COST_PER_IMAGE
        else:
            needed = IMAGE_COST_PER_IMAGE

        return (self.total_spend + needed) <= self.budget

    def summary(self) -> dict:
        """Return a summary of costs."""
        return {
            "budget": self.budget,
            "total_spend": round(self.total_spend, 2),
            "remaining": round(self.remaining_budget, 2),
            "percentage_used": round(self.budget_percentage, 1),
            "scene_count": len(self.scene_costs),
            "budget_exceeded": self.budget_exceeded,
        }

    def _add_cost(self, scene_order: int, cost: float):
        """Internal: add cost to tracking."""
        self.total_spend += cost
        if scene_order not in self.scene_costs:
            self.scene_costs[scene_order] = 0.0
        self.scene_costs[scene_order] += cost
