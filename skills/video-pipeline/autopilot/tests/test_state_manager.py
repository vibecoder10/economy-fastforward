"""Tests for autopilot state manager."""

import pytest
import json
from pathlib import Path
from datetime import datetime, timezone
from autopilot.core.state_manager import (
    AutopilotState,
    StateManager,
    ExperimentState,
)


class TestStateManager:
    """Test suite for state management."""

    @pytest.fixture
    def temp_state_file(self, tmp_path):
        """Create a temporary state file path."""
        return tmp_path / "autopilot_state.json"

    def test_default_state(self, temp_state_file):
        """Should return default state when file doesn't exist."""
        manager = StateManager(state_path=temp_state_file)
        state = manager.load()

        assert state.autopilot_enabled is True
        assert state.videos_produced == 0
        assert state.channel_avg_ctr == 0.0
        assert state.current_experiment is None

    def test_save_and_load(self, temp_state_file):
        """Should persist state to file."""
        manager = StateManager(state_path=temp_state_file)

        state = AutopilotState(
            autopilot_enabled=True,
            last_cycle="2026-03-18T09:00:00Z",
            videos_produced=5,
            channel_avg_ctr=4.2,
        )
        manager.save(state)

        # Reload
        loaded = manager.load()
        assert loaded.videos_produced == 5
        assert loaded.channel_avg_ctr == 4.2
        assert loaded.last_cycle == "2026-03-18T09:00:00Z"

    def test_update_after_production(self, temp_state_file):
        """Should update state after video production."""
        manager = StateManager(state_path=temp_state_file)

        initial = manager.load()
        manager.record_production_cycle("Test Video Title")

        updated = manager.load()
        assert updated.videos_produced == initial.videos_produced + 1
        assert updated.last_cycle is not None
        assert updated.current_experiment is not None
        assert updated.current_experiment.video_title == "Test Video Title"

    def test_is_enabled(self, temp_state_file):
        """Should check enabled state."""
        manager = StateManager(state_path=temp_state_file)
        assert manager.is_enabled() is True

        state = manager.load()
        state.autopilot_enabled = False
        manager.save(state)

        assert manager.is_enabled() is False
