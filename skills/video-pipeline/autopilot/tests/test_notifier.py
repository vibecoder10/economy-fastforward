"""Tests for autopilot notifier."""

import pytest
from unittest.mock import Mock, patch
from autopilot.core.notifier import AutopilotNotifier
from autopilot.core.confidence_scorer import IdeaCandidate, ScoredIdea


class TestNotifier:
    """Test suite for Slack notifications."""

    @pytest.fixture
    def mock_slack(self):
        return Mock()

    @pytest.fixture
    def notifier(self, mock_slack):
        return AutopilotNotifier(slack_client=mock_slack)

    @pytest.fixture
    def scored_idea(self):
        candidate = IdeaCandidate(
            record_id="rec123",
            title="China's $3T Dollar Trap",
            source_type="competitor",
            competitor_vph=150.0,
            competitor_title="China's Economic Collapse",
            hours_old=24,
        )
        return ScoredIdea(
            candidate=candidate,
            score=78.5,
            reasoning=["VPH 150 → 72/100", "Age 24h → 86/100"],
            component_scores={
                "competitor_vph": 72,
                "timing_freshness": 86,
                "topic_channel_fit": 50,
            },
        )

    def test_notify_production_start(self, notifier, mock_slack, scored_idea):
        """Should send formatted production start message."""
        notifier.notify_production_start(scored_idea)

        mock_slack.send_message.assert_called_once()
        message = mock_slack.send_message.call_args[0][0]

        assert "AUTOPILOT" in message
        assert "China's $3T Dollar Trap" in message
        assert "78" in message  # score
        assert "China's Economic Collapse" in message  # modeled from

    def test_notify_not_ready(self, notifier, mock_slack):
        """Should send not ready message with next date."""
        notifier.notify_not_ready(days_until=2, next_date="2026-03-20")

        mock_slack.send_message.assert_called_once()
        message = mock_slack.send_message.call_args[0][0]

        assert "not time" in message.lower() or "2 days" in message.lower()

    def test_notify_no_candidates(self, notifier, mock_slack):
        """Should notify when no candidates meet threshold."""
        notifier.notify_no_candidates(threshold=60, best_score=45)

        mock_slack.send_message.assert_called_once()
        message = mock_slack.send_message.call_args[0][0]

        assert "no candidates" in message.lower() or "threshold" in message.lower()

    def test_format_reasoning(self, notifier, scored_idea):
        """Should format reasoning as bullet list."""
        formatted = notifier._format_reasoning(scored_idea)

        assert "VPH" in formatted
        assert "•" in formatted or "-" in formatted
