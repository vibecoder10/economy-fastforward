"""Manage production cadence (videos per month)."""

import math
from datetime import datetime, timezone, timedelta
from typing import Optional
from autopilot.core.config_parser import AutopilotConfig
from autopilot.core.state_manager import AutopilotState


class CadenceManager:
    """Check if it's time to produce the next video."""

    def __init__(self, config: AutopilotConfig, state: AutopilotState):
        """Initialize cadence manager.

        Args:
            config: Autopilot configuration
            state: Current autopilot state
        """
        self.config = config
        self.state = state
        self._last_cycle = self._parse_last_cycle()

    def _parse_last_cycle(self) -> Optional[datetime]:
        """Parse last_cycle string to datetime."""
        if self.state.last_cycle is None:
            return None
        try:
            return datetime.fromisoformat(
                self.state.last_cycle.replace('Z', '+00:00')
            )
        except ValueError:
            return None

    def is_production_slot_available(self) -> bool:
        """Check if enough time has passed since last production.

        Returns:
            True if ready to produce next video
        """
        if self._last_cycle is None:
            # Never run before - ready to go
            return True

        elapsed = datetime.now(timezone.utc) - self._last_cycle
        required = timedelta(days=self.config.production_interval_days)

        return elapsed >= required

    def get_next_production_date(self) -> datetime:
        """Calculate when next production should occur.

        Returns:
            datetime of next production slot
        """
        if self._last_cycle is None:
            return datetime.now(timezone.utc)

        return self._last_cycle + timedelta(days=self.config.production_interval_days)

    def days_until_next(self) -> int:
        """Calculate days until next production slot.

        Returns:
            Number of days (0 = ready now)
        """
        if self._last_cycle is None:
            return 0

        next_date = self.get_next_production_date()
        delta = next_date - datetime.now(timezone.utc)

        # Use ceiling to round up partial days
        days = math.ceil(delta.total_seconds() / 86400)
        return max(0, days)
