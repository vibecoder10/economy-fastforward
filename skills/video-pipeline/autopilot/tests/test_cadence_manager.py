"""Tests for cadence manager."""

import pytest
from datetime import datetime, timezone, timedelta
from autopilot.core.cadence_manager import CadenceManager
from autopilot.core.config_parser import AutopilotConfig
from autopilot.core.state_manager import AutopilotState


class TestCadenceManager:
    """Test suite for cadence management."""

    def test_first_run_is_ready(self):
        """Should be ready on first run (no previous cycle)."""
        config = AutopilotConfig(videos_per_month=15, production_interval_days=2)
        state = AutopilotState(last_cycle=None)

        manager = CadenceManager(config, state)
        assert manager.is_production_slot_available() is True

    def test_too_soon(self):
        """Should not be ready if last cycle was too recent."""
        config = AutopilotConfig(videos_per_month=15, production_interval_days=2)

        # Last cycle was 1 day ago (need 2 days)
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        state = AutopilotState(last_cycle=yesterday.isoformat())

        manager = CadenceManager(config, state)
        assert manager.is_production_slot_available() is False

    def test_ready_after_interval(self):
        """Should be ready after interval passes."""
        config = AutopilotConfig(videos_per_month=15, production_interval_days=2)

        # Last cycle was 3 days ago (need 2 days)
        three_days_ago = datetime.now(timezone.utc) - timedelta(days=3)
        state = AutopilotState(last_cycle=three_days_ago.isoformat())

        manager = CadenceManager(config, state)
        assert manager.is_production_slot_available() is True

    def test_next_production_date(self):
        """Should calculate next production date."""
        config = AutopilotConfig(videos_per_month=15, production_interval_days=2)

        last = datetime.now(timezone.utc) - timedelta(days=1)
        state = AutopilotState(last_cycle=last.isoformat())

        manager = CadenceManager(config, state)
        next_date = manager.get_next_production_date()

        # Should be last_cycle + 2 days
        expected = last + timedelta(days=2)
        assert abs((next_date - expected).total_seconds()) < 1

    def test_days_until_next(self):
        """Should calculate days until next production."""
        config = AutopilotConfig(videos_per_month=15, production_interval_days=2)

        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        state = AutopilotState(last_cycle=yesterday.isoformat())

        manager = CadenceManager(config, state)
        days = manager.days_until_next()

        # 1 day until next (interval=2, elapsed=1)
        assert days == 1
