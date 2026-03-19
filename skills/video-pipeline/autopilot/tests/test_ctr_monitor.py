# skills/video-pipeline/autopilot/tests/test_ctr_monitor.py
"""Tests for CTR monitor."""

import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from autopilot.monitoring.ctr_monitor import CTRMonitor, CTRCheckpoint
from autopilot.monitoring.early_warning import AlertLevel


class TestGetDueMilestones:
    """Test milestone detection based on time elapsed."""

    @pytest.fixture
    def monitor(self):
        return CTRMonitor(airtable_client=None)

    def test_get_due_milestones_none(self, monitor):
        """No milestones if < 6h elapsed."""
        # Published 2 hours ago
        publish_date = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        milestones = monitor.get_due_milestones(publish_date)
        assert milestones == []

    def test_get_due_milestones_6h(self, monitor):
        """Returns ['6h'] if 6-24h elapsed."""
        # Published 12 hours ago
        publish_date = (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat()
        milestones = monitor.get_due_milestones(publish_date)
        assert milestones == ["6h"]

    def test_get_due_milestones_24h(self, monitor):
        """Returns ['6h', '24h'] if 24-48h elapsed."""
        # Published 30 hours ago
        publish_date = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        milestones = monitor.get_due_milestones(publish_date)
        assert milestones == ["6h", "24h"]

    def test_get_due_milestones_48h(self, monitor):
        """Returns all milestones if >= 48h elapsed."""
        # Published 50 hours ago
        publish_date = (datetime.now(timezone.utc) - timedelta(hours=50)).isoformat()
        milestones = monitor.get_due_milestones(publish_date)
        assert milestones == ["6h", "24h", "48h"]

    def test_get_due_milestones_7d(self, monitor):
        """Returns all milestones including 7d if >= 168h elapsed."""
        # Published 8 days ago
        publish_date = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        milestones = monitor.get_due_milestones(publish_date)
        assert milestones == ["6h", "24h", "48h", "7d"]


class TestCheck6hCTR:
    """Test 6h CTR check via YouTube Analytics API."""

    def test_check_6h_ctr_returns_none_when_no_token(self, tmp_path):
        """Graceful when no YouTube token file exists."""
        monitor = CTRMonitor(
            airtable_client=None,
            token_path=tmp_path / "nonexistent_token.json",
        )

        import asyncio
        result = asyncio.run(monitor.check_6h_ctr("test_video_id"))

        assert result is None


class TestGetCTRFromAirtable:
    """Test CTR lookup from Airtable."""

    def test_get_ctr_from_airtable(self):
        """Reads CTR from mocked Airtable."""
        mock_airtable = Mock()
        mock_airtable.get_idea_by_title.return_value = {
            "id": "rec123",
            "fields": {
                "Video Title": "Test Video",
                "CTR (%)": 4.5,
                "Impressions": 10000,
            }
        }

        monitor = CTRMonitor(airtable_client=mock_airtable)
        result = monitor.get_ctr_from_airtable("Test Video")

        assert result is not None
        assert result["ctr"] == 4.5
        assert result["impressions"] == 10000
        mock_airtable.get_idea_by_title.assert_called_once_with("Test Video")

    def test_get_ctr_from_airtable_no_data(self):
        """Returns None when no CTR data in Airtable."""
        mock_airtable = Mock()
        mock_airtable.get_idea_by_title.return_value = {
            "id": "rec123",
            "fields": {
                "Video Title": "Test Video",
                # No CTR field
            }
        }

        monitor = CTRMonitor(airtable_client=mock_airtable)
        result = monitor.get_ctr_from_airtable("Test Video")

        assert result is None

    def test_get_ctr_from_airtable_no_record(self):
        """Returns None when video not found."""
        mock_airtable = Mock()
        mock_airtable.get_idea_by_title.return_value = None

        monitor = CTRMonitor(airtable_client=mock_airtable)
        result = monitor.get_ctr_from_airtable("Nonexistent Video")

        assert result is None

    def test_get_ctr_from_airtable_no_client(self):
        """Returns None when no Airtable client configured."""
        monitor = CTRMonitor(airtable_client=None)
        result = monitor.get_ctr_from_airtable("Test Video")

        assert result is None


class TestCheckExperiment:
    """Test full experiment checking flow."""

    def test_check_experiment_creates_alert(self):
        """Full flow with mock data creates proper alert."""
        mock_airtable = Mock()
        mock_airtable.get_idea_by_title.return_value = {
            "id": "rec123",
            "fields": {
                "Video Title": "China's $3T Dollar Trap",
                "CTR (%)": 5.2,
                "Impressions": 15000,
            }
        }

        monitor = CTRMonitor(airtable_client=mock_airtable)

        # Experiment published 25 hours ago (past 24h milestone)
        experiment = {
            "video_title": "China's $3T Dollar Trap",
            "publish_date": (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(),
            "modeled_from": "Competitor Video",
        }

        import asyncio
        alert = asyncio.run(monitor.check_experiment(experiment))

        assert alert is not None
        assert alert.video_title == "China's $3T Dollar Trap"
        assert alert.ctr == 5.2
        assert alert.impressions == 15000
        assert alert.alert_level == AlertLevel.STRONG  # CTR >= 5.0

    def test_check_experiment_no_ctr_data(self):
        """Returns None when no CTR data available."""
        mock_airtable = Mock()
        mock_airtable.get_idea_by_title.return_value = None

        monitor = CTRMonitor(airtable_client=mock_airtable)

        experiment = {
            "video_title": "Test Video",
            "publish_date": (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(),
            "modeled_from": None,
        }

        import asyncio
        alert = asyncio.run(monitor.check_experiment(experiment))

        assert alert is None

    def test_check_experiment_too_early(self):
        """Returns None when video too new for any milestone."""
        mock_airtable = Mock()

        monitor = CTRMonitor(airtable_client=mock_airtable)

        experiment = {
            "video_title": "Test Video",
            "publish_date": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
            "modeled_from": None,
        }

        import asyncio
        alert = asyncio.run(monitor.check_experiment(experiment))

        assert alert is None
        # Should not even query Airtable if no milestones due
        mock_airtable.get_idea_by_title.assert_not_called()


class TestGetActiveExperiments:
    """Test fetching active experiments from state."""

    def test_get_active_experiments_with_monitoring(self, tmp_path):
        """Returns experiments in monitoring status."""
        from autopilot.core.state_manager import StateManager, AutopilotState, ExperimentState

        state_file = tmp_path / "state.json"
        state_manager = StateManager(state_path=state_file)

        # Set up state with monitoring experiment
        state = AutopilotState(
            autopilot_enabled=True,
            current_experiment=ExperimentState(
                video_title="Test Video",
                status="monitoring",
                publish_date=(datetime.now(timezone.utc) - timedelta(hours=12)).isoformat(),
                modeled_from="Competitor",
            )
        )
        state_manager.save(state)

        monitor = CTRMonitor(airtable_client=None)
        monitor.state_manager = state_manager

        experiments = monitor.get_active_experiments()

        assert len(experiments) == 1
        assert experiments[0]["video_title"] == "Test Video"
        assert experiments[0]["modeled_from"] == "Competitor"

    def test_get_active_experiments_producing_status(self, tmp_path):
        """Does not return experiments still in producing status."""
        from autopilot.core.state_manager import StateManager, AutopilotState, ExperimentState

        state_file = tmp_path / "state.json"
        state_manager = StateManager(state_path=state_file)

        state = AutopilotState(
            autopilot_enabled=True,
            current_experiment=ExperimentState(
                video_title="Test Video",
                status="producing",  # Not monitoring yet
                publish_date=None,
            )
        )
        state_manager.save(state)

        monitor = CTRMonitor(airtable_client=None)
        monitor.state_manager = state_manager

        experiments = monitor.get_active_experiments()

        assert len(experiments) == 0

    def test_get_active_experiments_no_experiment(self, tmp_path):
        """Returns empty list when no current experiment."""
        from autopilot.core.state_manager import StateManager, AutopilotState

        state_file = tmp_path / "state.json"
        state_manager = StateManager(state_path=state_file)

        state = AutopilotState(
            autopilot_enabled=True,
            current_experiment=None,
        )
        state_manager.save(state)

        monitor = CTRMonitor(airtable_client=None)
        monitor.state_manager = state_manager

        experiments = monitor.get_active_experiments()

        assert len(experiments) == 0
