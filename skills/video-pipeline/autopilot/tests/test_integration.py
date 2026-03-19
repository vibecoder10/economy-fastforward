"""Integration tests for autopilot."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
from autopilot.autopilot import Autopilot, CompetitorVideoFields
from autopilot.core.config_parser import AutopilotConfig
from autopilot.core.state_manager import StateManager, AutopilotState


class TestAutopilotIntegration:
    """Integration test for full autopilot cycle."""

    @pytest.fixture
    def mock_airtable(self):
        """Mock Airtable client."""
        mock = Mock()
        mock.get_competitor_videos = Mock(return_value=[
            {
                'id': 'rec123',
                'fields': {
                    'Title': "China's Economic Collapse",
                    'VPH': 150.0,
                    'Hours Old': 24,
                    'Published Date': '2026-03-17T12:00:00Z',
                }
            },
            {
                'id': 'rec456',
                'fields': {
                    'Title': "Why NATO is Failing",
                    'VPH': 80.0,
                    'Hours Old': 48,
                    'Published Date': '2026-03-16T12:00:00Z',
                }
            },
        ])
        return mock

    @pytest.fixture
    def mock_slack(self):
        """Mock Slack client."""
        return Mock()

    @pytest.fixture
    def temp_state_manager(self, tmp_path):
        """State manager with temporary file."""
        return StateManager(state_path=tmp_path / "autopilot_state.json")

    def test_full_cycle_selects_best_candidate(
        self,
        mock_airtable,
        mock_slack,
        temp_state_manager,
    ):
        """Full cycle should select highest-scoring candidate."""
        # Create autopilot with mocked dependencies
        config = AutopilotConfig()
        autopilot = Autopilot(
            config=config,
            state_manager=temp_state_manager,
            airtable_client=mock_airtable,
            slack_client=mock_slack,
        )

        # Run cycle
        result = autopilot.check_cycle()

        # Should have selected best candidate (China - higher VPH)
        assert result is True
        mock_slack.send_message.assert_called()

        # State should have been updated
        state = temp_state_manager.load()
        assert state.videos_produced == 1
        assert "China" in state.current_experiment.video_title

    def test_cycle_respects_cadence(
        self,
        mock_airtable,
        mock_slack,
        temp_state_manager,
    ):
        """Should not run if cadence says it's not time."""
        from datetime import datetime, timezone

        # Set last cycle to now (too recent)
        state = AutopilotState(
            autopilot_enabled=True,
            last_cycle=datetime.now(timezone.utc).isoformat(),
            videos_produced=5,
        )
        temp_state_manager.save(state)

        config = AutopilotConfig(production_interval_days=2)
        autopilot = Autopilot(
            config=config,
            state_manager=temp_state_manager,
            airtable_client=mock_airtable,
            slack_client=mock_slack,
        )

        # Run cycle
        result = autopilot.check_cycle()

        # Should not produce (not time yet)
        assert result is False
        mock_airtable.get_competitor_videos.assert_not_called()

    def test_force_ignores_cadence(
        self,
        mock_airtable,
        mock_slack,
        temp_state_manager,
    ):
        """Force flag should skip cadence check."""
        from datetime import datetime, timezone

        # Set last cycle to now (too recent)
        state = AutopilotState(
            autopilot_enabled=True,
            last_cycle=datetime.now(timezone.utc).isoformat(),
            videos_produced=5,
        )
        temp_state_manager.save(state)

        config = AutopilotConfig(production_interval_days=2)
        autopilot = Autopilot(
            config=config,
            state_manager=temp_state_manager,
            airtable_client=mock_airtable,
            slack_client=mock_slack,
        )

        # Run cycle with force
        result = autopilot.check_cycle(force=True)

        # Should produce despite cadence
        assert result is True
        mock_airtable.get_competitor_videos.assert_called()

    def test_disabled_autopilot_does_nothing(
        self,
        mock_airtable,
        mock_slack,
        temp_state_manager,
    ):
        """Should not run when disabled."""
        # Disable autopilot
        state = AutopilotState(autopilot_enabled=False)
        temp_state_manager.save(state)

        config = AutopilotConfig()
        autopilot = Autopilot(
            config=config,
            state_manager=temp_state_manager,
            airtable_client=mock_airtable,
            slack_client=mock_slack,
        )

        # Run cycle
        result = autopilot.check_cycle()

        # Should not produce
        assert result is False
        mock_airtable.get_competitor_videos.assert_not_called()

    def test_no_candidates_sends_notification(
        self,
        mock_slack,
        temp_state_manager,
    ):
        """Should notify when no candidates found."""
        # Mock airtable with no results
        mock_airtable = Mock()
        mock_airtable.get_competitor_videos = Mock(return_value=[])

        config = AutopilotConfig()
        autopilot = Autopilot(
            config=config,
            state_manager=temp_state_manager,
            airtable_client=mock_airtable,
            slack_client=mock_slack,
        )

        # Run cycle
        result = autopilot.check_cycle()

        # Should not produce but should notify
        assert result is False
        mock_slack.send_message.assert_called()
        message = mock_slack.send_message.call_args[0][0]
        assert "No candidates" in message or "no candidates" in message.lower()
