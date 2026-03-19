# skills/video-pipeline/autopilot/monitoring/early_warning.py
"""Early warning system for CTR classification.

Classifies CTR into alert levels and provides verdicts for pattern decisions.
Based on spec Section 4: CTR Monitoring & Early Warning.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class AlertLevel(Enum):
    """CTR alert levels for early warning system.

    From spec:
    - CRITICAL: CTR < 2.5% -> Consider thumbnail/title swap
    - WARNING: CTR < 3.5% -> Monitor closely
    - NORMAL: CTR 3.5-5.0% -> On track
    - STRONG: CTR >= 5.0% -> Pattern working
    """
    CRITICAL = "critical"
    WARNING = "warning"
    NORMAL = "normal"
    STRONG = "strong"


class CTRVerdict(Enum):
    """Final verdict for pattern decision after 48h.

    From spec:
    - KEEP: CTR >= 4.0%, pattern confirmed
    - DISCARD: CTR <= 2.5%, pattern failed
    - NEUTRAL: In between, need more data
    """
    KEEP = "keep"
    DISCARD = "discard"
    NEUTRAL = "neutral"


@dataclass
class CTRAlert:
    """Alert data for a video's CTR performance."""
    video_title: str
    ctr: float
    impressions: int
    hours_since_publish: float
    alert_level: AlertLevel
    message: str


class EarlyWarning:
    """CTR early warning classifier.

    Classifies CTR into alert levels and generates verdicts.
    Thresholds from spec Section 4.
    """

    # Alert level thresholds
    CRITICAL_THRESHOLD = 2.5   # CTR < this = CRITICAL
    WARNING_THRESHOLD = 3.5    # CTR < this = WARNING
    STRONG_THRESHOLD = 5.0     # CTR >= this = STRONG

    # Verdict thresholds
    KEEP_THRESHOLD = 4.0       # CTR >= this = KEEP
    DISCARD_THRESHOLD = 2.5    # CTR <= this = DISCARD

    # Alert level emoji and messages
    ALERT_CONFIG = {
        AlertLevel.CRITICAL: {
            "emoji": "🚨",
            "label": "CRITICAL",
            "action": "Consider thumbnail/title swap",
        },
        AlertLevel.WARNING: {
            "emoji": "⚠️",
            "label": "WARNING",
            "action": "Monitor closely",
        },
        AlertLevel.NORMAL: {
            "emoji": "📊",
            "label": "NORMAL",
            "action": "On track",
        },
        AlertLevel.STRONG: {
            "emoji": "✅",
            "label": "STRONG",
            "action": "Pattern working",
        },
    }

    def classify(self, ctr: float) -> AlertLevel:
        """Classify CTR into an alert level.

        Args:
            ctr: Click-through rate as percentage (e.g., 4.5 for 4.5%)

        Returns:
            AlertLevel based on thresholds
        """
        if ctr < self.CRITICAL_THRESHOLD:
            return AlertLevel.CRITICAL
        elif ctr < self.WARNING_THRESHOLD:
            return AlertLevel.WARNING
        elif ctr < self.STRONG_THRESHOLD:
            return AlertLevel.NORMAL
        else:
            return AlertLevel.STRONG

    def get_verdict(self, ctr: float) -> CTRVerdict:
        """Get final verdict for pattern decision.

        Used after 48h+ when we have reliable CTR data.

        Args:
            ctr: Click-through rate as percentage

        Returns:
            CTRVerdict (KEEP, DISCARD, or NEUTRAL)
        """
        if ctr >= self.KEEP_THRESHOLD:
            return CTRVerdict.KEEP
        elif ctr <= self.DISCARD_THRESHOLD:
            return CTRVerdict.DISCARD
        else:
            return CTRVerdict.NEUTRAL

    def create_alert(
        self,
        video_title: str,
        ctr: float,
        impressions: int,
        hours_since_publish: float,
    ) -> CTRAlert:
        """Create a full alert with classification and message.

        Args:
            video_title: Title of the video
            ctr: Click-through rate as percentage
            impressions: Number of impressions
            hours_since_publish: Hours since video was published

        Returns:
            CTRAlert with all data and formatted message
        """
        alert_level = self.classify(ctr)
        config = self.ALERT_CONFIG[alert_level]

        message = (
            f"{config['emoji']} *{config['label']}*: {video_title}\n"
            f"CTR: {ctr:.1f}% | Impressions: {impressions:,} | {hours_since_publish:.0f}h since publish\n"
            f"_{config['action']}_"
        )

        return CTRAlert(
            video_title=video_title,
            ctr=ctr,
            impressions=impressions,
            hours_since_publish=hours_since_publish,
            alert_level=alert_level,
            message=message,
        )
