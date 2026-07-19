"""Integration tests for autopilot."""

import pytest
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from pathlib import Path
from autopilot.autopilot import Autopilot, CompetitorVideoFields
from autopilot.core.config_parser import AutopilotConfig
from autopilot.core.state_manager import StateManager, AutopilotState
from autopilot.analysis.theme_extractor import ThemeAnalysis


class TestAutopilotIntegration:
    """Integration test for full autopilot cycle."""

    @pytest.fixture
    def mock_airtable(self):
        """Mock Airtable client."""
        # Published Date must stay fresh relative to "now" (ConfidenceScorer
        # scores freshness off hours-since-publication, MAX_HOURS=168) - a
        # hardcoded absolute date rots past that window and starves both
        # candidates of freshness score. Compute it from the intended
        # "Hours Old" age instead so the fixture always represents the
        # 24h/48h-old candidates it was written to be (see C32b).
        now = datetime.now(timezone.utc)
        mock = Mock()
        mock.get_competitor_videos = Mock(return_value=[
            {
                'id': 'rec123',
                'fields': {
                    'Title': "China's Economic Collapse",
                    'VPH': 150.0,
                    'Hours Old': 24,
                    'Published Date': (now - timedelta(hours=24)).isoformat().replace('+00:00', 'Z'),
                }
            },
            {
                'id': 'rec456',
                'fields': {
                    'Title': "Why NATO is Failing",
                    'VPH': 80.0,
                    'Hours Old': 48,
                    'Published Date': (now - timedelta(hours=48)).isoformat().replace('+00:00', 'Z'),
                }
            },
        ])
        # Mock create_idea for idea creation
        mock.create_idea = Mock(return_value={
            'id': 'recNEW123',
            'fields': {'Video Title': "How China Manufactured the Taiwan Crisis"}
        })
        return mock

    @pytest.fixture
    def mock_slack(self):
        """Mock Slack client."""
        return Mock()

    @pytest.fixture
    def mock_anthropic(self):
        """Mock Anthropic client for theme extraction and idea generation."""
        mock = Mock()
        # Mock for theme extraction (sync call in ThemeExtractor)
        theme_response = Mock()
        theme_response.content = [Mock(text='{"primary_theme": "China economy", "secondary_themes": ["trade", "debt"], "angle_type": "hidden_truth", "emotional_hooks": ["fear", "curiosity_gap"], "topic_category": "economy", "title_formula": "How [Power] [Verb] the [Event]", "formula_variables": {"power": "China", "verb": "Collapsed", "event": "Economy"}, "confidence": 0.9}')]
        # Mock for idea generation (async call in IdeaCreator)
        ideas_response = Mock()
        ideas_response.content = [Mock(text='[{"viral_title": "How China Manufactured the Taiwan Crisis", "hook_script": "The real story...", "thumbnail_visual": "Map with arrows", "past_context": "Decades of tension", "present_parallel": "Current moves", "future_prediction": "Coming conflict", "writer_guidance": "Focus on covert ops", "variables_swapped": ["power: US → China"]}]')]

        # IdeaCreator uses AsyncAnthropic, so we need AsyncMock for messages.create
        # But ThemeExtractor uses sync Anthropic, so we need regular Mock
        # Solution: Use a side_effect that returns the right response
        mock.messages = Mock()
        mock.messages.create = Mock(side_effect=[theme_response, ideas_response])
        return mock

    @pytest.fixture
    def mock_async_anthropic(self):
        """Mock AsyncAnthropic client for idea generation."""
        mock = AsyncMock()
        ideas_response = Mock()
        ideas_response.content = [Mock(text='[{"viral_title": "How China Manufactured the Taiwan Crisis", "hook_script": "The real story...", "thumbnail_visual": "Map with arrows", "past_context": "Decades of tension", "present_parallel": "Current moves", "future_prediction": "Coming conflict", "writer_guidance": "Focus on covert ops", "variables_swapped": ["power: US → China"]}]')]
        mock.messages.create = AsyncMock(return_value=ideas_response)
        return mock

    @pytest.fixture
    def temp_state_manager(self, tmp_path):
        """State manager with temporary file."""
        return StateManager(state_path=tmp_path / "autopilot_state.json")

    def test_full_cycle_selects_best_candidate(
        self,
        mock_airtable,
        mock_slack,
        mock_anthropic,
        temp_state_manager,
    ):
        """Full cycle should select highest-scoring candidate (dry run mode)."""
        # Create autopilot with mocked dependencies
        config = AutopilotConfig()
        autopilot = Autopilot(
            config=config,
            state_manager=temp_state_manager,
            airtable_client=mock_airtable,
            slack_client=mock_slack,
            anthropic_client=mock_anthropic,
        )
        # Force initialization of theme_extractor and idea_creator
        autopilot._init_clients()

        # Run cycle in dry run mode (tests flow without needing async mocks)
        result = autopilot.check_cycle(dry_run=True)

        # Should have selected best candidate (China - higher VPH)
        assert result is True

        # State should have been updated (dry_run still updates state)
        state = temp_state_manager.load()
        assert state.videos_produced == 1
        assert state.current_experiment is not None
        # In dry_run, the title is the competitor title (no idea created)
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
        mock_anthropic,
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
            anthropic_client=mock_anthropic,
        )
        # Force initialization of theme_extractor and idea_creator
        autopilot._init_clients()

        # Run cycle with force (using dry_run to avoid async mock issues)
        result = autopilot.check_cycle(force=True, dry_run=True)

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
