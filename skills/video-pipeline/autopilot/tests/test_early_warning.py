# skills/video-pipeline/autopilot/tests/test_early_warning.py
"""Tests for early warning CTR classification system."""

import pytest
from autopilot.monitoring.early_warning import (
    AlertLevel,
    CTRVerdict,
    CTRAlert,
    EarlyWarning,
)


class TestEarlyWarning:
    """Test suite for CTR early warning system."""

    @pytest.fixture
    def warning(self):
        return EarlyWarning()

    def test_classify_critical(self, warning):
        """CTR < 2.5% should be CRITICAL."""
        assert warning.classify(2.4) == AlertLevel.CRITICAL
        assert warning.classify(1.0) == AlertLevel.CRITICAL
        assert warning.classify(0.0) == AlertLevel.CRITICAL

    def test_classify_warning(self, warning):
        """CTR 2.5-3.5% should be WARNING."""
        assert warning.classify(2.5) == AlertLevel.WARNING
        assert warning.classify(3.0) == AlertLevel.WARNING
        assert warning.classify(3.49) == AlertLevel.WARNING

    def test_classify_normal(self, warning):
        """CTR 3.5-5.0% should be NORMAL."""
        assert warning.classify(3.5) == AlertLevel.NORMAL
        assert warning.classify(4.0) == AlertLevel.NORMAL
        assert warning.classify(4.99) == AlertLevel.NORMAL

    def test_classify_strong(self, warning):
        """CTR >= 5.0% should be STRONG."""
        assert warning.classify(5.0) == AlertLevel.STRONG
        assert warning.classify(7.5) == AlertLevel.STRONG
        assert warning.classify(10.0) == AlertLevel.STRONG

    def test_verdict_keep(self, warning):
        """CTR >= 4.0% should be KEEP verdict."""
        assert warning.get_verdict(4.0) == CTRVerdict.KEEP
        assert warning.get_verdict(5.5) == CTRVerdict.KEEP
        assert warning.get_verdict(8.0) == CTRVerdict.KEEP

    def test_verdict_discard(self, warning):
        """CTR <= 2.5% should be DISCARD verdict."""
        assert warning.get_verdict(2.5) == CTRVerdict.DISCARD
        assert warning.get_verdict(1.5) == CTRVerdict.DISCARD
        assert warning.get_verdict(0.0) == CTRVerdict.DISCARD

    def test_verdict_neutral(self, warning):
        """CTR between 2.5% and 4.0% should be NEUTRAL verdict."""
        assert warning.get_verdict(2.6) == CTRVerdict.NEUTRAL
        assert warning.get_verdict(3.0) == CTRVerdict.NEUTRAL
        assert warning.get_verdict(3.9) == CTRVerdict.NEUTRAL

    def test_create_alert_has_message(self, warning):
        """create_alert should return CTRAlert with emoji message."""
        alert = warning.create_alert(
            video_title="China's $3T Dollar Trap",
            ctr=2.1,
            impressions=5000,
            hours_since_publish=6,
        )

        assert isinstance(alert, CTRAlert)
        assert alert.video_title == "China's $3T Dollar Trap"
        assert alert.ctr == 2.1
        assert alert.impressions == 5000
        assert alert.hours_since_publish == 6
        assert alert.alert_level == AlertLevel.CRITICAL
        assert len(alert.message) > 0
        # Should have emoji indicator
        assert any(emoji in alert.message for emoji in ["🚨", "⚠️", "📊", "✅"])
