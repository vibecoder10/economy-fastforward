"""Slack notifications for autopilot decisions."""

from typing import Optional
from autopilot.core.confidence_scorer import ScoredIdea


class AutopilotNotifier:
    """Send formatted notifications to Slack."""

    def __init__(self, slack_client):
        """Initialize notifier.

        Args:
            slack_client: SlackClient instance
        """
        self.slack = slack_client

    def _format_reasoning(self, scored: ScoredIdea) -> str:
        """Format scoring reasoning as bullet list.

        Args:
            scored: Scored idea with reasoning

        Returns:
            Formatted string
        """
        lines = [f"• {r}" for r in scored.reasoning]
        return "\n".join(lines)

    def notify_production_start(self, scored: ScoredIdea) -> None:
        """Send notification that production is starting.

        Args:
            scored: The idea being produced
        """
        candidate = scored.candidate

        message = f"""🎬 *AUTOPILOT: Starting production*

*VIDEO:* {candidate.title}
*CONFIDENCE:* {scored.score:.0f}/100

*WHY THIS IDEA:*
{self._format_reasoning(scored)}
"""

        if candidate.competitor_title:
            message += f"\n*MODELING:* {candidate.competitor_title}"
            if candidate.competitor_vph:
                message += f" (VPH: {candidate.competitor_vph:.0f})"

        message += "\n\n_Production begins. Reply STOP to abort._"

        self.slack.send_message(message)

    def notify_not_ready(self, days_until: int, next_date: str) -> None:
        """Send notification that it's not time yet.

        Args:
            days_until: Days until next production slot
            next_date: Date string for next production
        """
        message = f"""⏳ *AUTOPILOT: Not time yet*

Next production slot in *{days_until} day(s)* ({next_date}).

Cadence is on track. Checking again later."""

        self.slack.send_message(message)

    def notify_no_candidates(self, threshold: int, best_score: Optional[float] = None) -> None:
        """Send notification that no candidates meet threshold.

        Args:
            threshold: Minimum confidence score required
            best_score: Score of the best candidate (if any)
        """
        message = f"""📭 *AUTOPILOT: No candidates ready*

No ideas meet the confidence threshold of *{threshold}*.
"""

        if best_score is not None:
            message += f"Best candidate scored *{best_score:.0f}* (need ≥{threshold}).\n"

        message += "\nWaiting for better opportunities. Will check again next cycle."

        self.slack.send_message(message)

    def notify_disabled(self) -> None:
        """Send notification that autopilot is disabled."""
        message = """🔴 *AUTOPILOT: Disabled*

Autopilot is currently OFF. To enable:
• Edit `autopilot_program.md` and set `autopilot: ON`
• Or send `autopilot on` command"""

        self.slack.send_message(message)

    def notify_error(self, error: str, context: Optional[str] = None) -> None:
        """Send error notification.

        Args:
            error: Error message
            context: Additional context (optional)
        """
        message = f"""🚨 *AUTOPILOT: Error*

{error}
"""

        if context:
            message += f"\n_Context: {context}_"

        self.slack.send_message(message)
