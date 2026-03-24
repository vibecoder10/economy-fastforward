# skills/video-pipeline/autopilot/monitoring/ctr_monitor.py
"""Monitor CTR at 6h/24h/48h milestones.

Polls YouTube Analytics API for early (6h) checks and reads from Airtable
for later milestones (24h/48h/7d) since performance_tracker populates those.

Based on spec Section 4 (CTR Monitoring & Early Warning) and Section 8.3
(CTR Monitoring API Strategy).
"""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass

from autopilot.monitoring.early_warning import EarlyWarning, CTRAlert
from autopilot.core.state_manager import StateManager


@dataclass
class CTRCheckpoint:
    """CTR measurement at a milestone."""
    video_id: str
    video_title: str
    milestone: str  # "6h", "24h", "48h", "7d"
    ctr: Optional[float]
    impressions: Optional[int]
    checked_at: datetime
    data_available: bool


class CTRMonitor:
    """Monitor CTR at milestones for active experiments.

    Timeline from spec:
    - 0h: Video goes live
    - 6h: Early warning check (YouTube Analytics API)
    - 24h: First read (Airtable via performance_tracker)
    - 48h: Full data + verdict
    - 7d: Final verdict + learning extraction
    """

    # Milestones in hours
    MILESTONES = {
        "6h": 6,
        "24h": 24,
        "48h": 48,
        "7d": 168,
    }

    def __init__(
        self,
        airtable_client=None,
        token_path: Optional[Path] = None,
    ):
        """Initialize CTR monitor.

        Args:
            airtable_client: AirtableClient instance for CTR lookups
            token_path: Path to YouTube OAuth token file
        """
        self.airtable = airtable_client
        self.token_path = token_path or Path(__file__).parent.parent.parent / ".youtube-token.json"
        self.early_warning = EarlyWarning()
        self.state_manager = StateManager()
        self._youtube_analytics = None

    def _get_youtube_analytics(self):
        """Get or create YouTube Analytics API client (lazy init).

        Returns:
            YouTube Analytics API client or None if unavailable
        """
        # Return cached client if already initialized
        if self._youtube_analytics is not None:
            return self._youtube_analytics

        # Check if token file exists
        if not self.token_path.exists():
            return None

        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            with open(self.token_path) as f:
                token_data = json.load(f)

            creds = Credentials(
                token=token_data.get("token"),
                refresh_token=token_data.get("refresh_token"),
                token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
                client_id=token_data.get("client_id"),
                client_secret=token_data.get("client_secret"),
                scopes=["https://www.googleapis.com/auth/yt-analytics.readonly"],
            )

            # Refresh token if expired
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())

            self._youtube_analytics = build("youtubeAnalytics", "v2", credentials=creds)
            return self._youtube_analytics
        except Exception as e:
            print(f"Failed to initialize YouTube Analytics: {e}")
            return None

    async def check_6h_ctr(self, video_id: str) -> Optional[float]:
        """Early CTR check via YouTube Analytics API.

        Per spec 8.3: Use YouTube Analytics API for 6h check.
        Available ~4-6 hours after publish.

        Args:
            video_id: YouTube video ID

        Returns:
            CTR as percentage (e.g., 4.5 for 4.5%) or None if unavailable
        """
        analytics = self._get_youtube_analytics()
        if analytics is None:
            return None

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        try:
            response = analytics.reports().query(
                ids="channel==MINE",
                startDate=today,
                endDate=today,
                metrics="impressionClickThroughRate,impressions",
                filters=f"video=={video_id}",
            ).execute()

            if response.get("rows"):
                ctr_decimal = response["rows"][0][0]
                return ctr_decimal * 100  # Convert to percentage
            return None  # Data not yet available
        except Exception as e:
            print(f"6h CTR check failed: {e}")
            return None  # Non-blocking, will retry

    def get_ctr_from_airtable(self, video_title: str) -> Optional[dict]:
        """Get CTR data from Airtable (populated by performance_tracker).

        Per spec 8.3: Use existing performance_tracker data for 24h/48h/7d.

        Args:
            video_title: Video title to look up

        Returns:
            Dict with 'ctr' and 'impressions' keys, or None if not found
        """
        if self.airtable is None:
            return None

        try:
            record = self.airtable.get_idea_by_title(video_title)
            if record:
                fields = record.get("fields", {})
                ctr = fields.get("CTR (%)")
                impressions = fields.get("Impressions")
                if ctr is not None:
                    return {"ctr": ctr, "impressions": impressions}
        except Exception as e:
            print(f"Airtable CTR lookup failed: {e}")

        return None

    def get_active_experiments(self) -> List[dict]:
        """Get videos currently being monitored.

        Reads from state_manager to find experiments in 'monitoring' status.

        Returns:
            List of experiment dicts with video_title, publish_date, modeled_from
        """
        state = self.state_manager.load()
        experiments = []

        if state.current_experiment:
            exp = state.current_experiment
            # Only include if status is 'monitoring' and has publish date
            if exp.status == "monitoring" and exp.publish_date:
                experiments.append({
                    "video_title": exp.video_title,
                    "publish_date": exp.publish_date,
                    "modeled_from": exp.modeled_from,
                })

        return experiments

    def get_due_milestones(self, publish_date: str) -> List[str]:
        """Determine which milestones are due for checking.

        Args:
            publish_date: ISO format publish date string

        Returns:
            List of milestone strings that have been reached (e.g., ["6h", "24h"])
        """
        pub_dt = datetime.fromisoformat(publish_date.replace('Z', '+00:00'))
        hours_elapsed = (datetime.now(timezone.utc) - pub_dt).total_seconds() / 3600

        due = []
        # Sort by hours to return in order
        for milestone, hours in sorted(self.MILESTONES.items(), key=lambda x: x[1]):
            if hours_elapsed >= hours:
                due.append(milestone)

        return due

    async def check_experiment(self, experiment: dict) -> Optional[CTRAlert]:
        """Check CTR for an experiment at its current milestone.

        Args:
            experiment: Dict with video_title, publish_date, modeled_from

        Returns:
            CTRAlert if data available, None otherwise
        """
        milestones = self.get_due_milestones(experiment["publish_date"])
        if not milestones:
            # Too early for any milestone
            return None

        latest = milestones[-1]

        # Get CTR data
        ctr_data = None
        if latest == "6h":
            # For 6h, would need video_id for YouTube Analytics API
            # Fallback to Airtable if available
            ctr_data = self.get_ctr_from_airtable(experiment["video_title"])
        else:
            # For 24h/48h/7d, use Airtable (populated by performance_tracker)
            ctr_data = self.get_ctr_from_airtable(experiment["video_title"])

        if ctr_data is None:
            return None

        # Calculate hours since publish
        pub_dt = datetime.fromisoformat(
            experiment["publish_date"].replace('Z', '+00:00')
        )
        hours = (datetime.now(timezone.utc) - pub_dt).total_seconds() / 3600

        # Create alert using early_warning system
        return self.early_warning.create_alert(
            video_title=experiment["video_title"],
            ctr=ctr_data["ctr"],
            impressions=ctr_data.get("impressions") or 0,
            hours_since_publish=hours,
        )

    async def check_all_active(self) -> List[CTRAlert]:
        """Check CTR for all active experiments.

        Returns:
            List of CTRAlerts for experiments with available data
        """
        experiments = self.get_active_experiments()
        alerts = []

        for exp in experiments:
            alert = await self.check_experiment(exp)
            if alert:
                alerts.append(alert)

        return alerts


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

async def main_async():
    """Async entry point for CTR monitoring."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))

    from shared.clients.airtable_client import AirtableClient
    from shared.clients.slack_client import SlackClient

    print("🔍 CTR Monitor: Checking active experiments...")

    airtable = AirtableClient()
    slack = SlackClient()
    monitor = CTRMonitor(airtable_client=airtable)

    alerts = await monitor.check_all_active()

    if not alerts:
        print("   No experiments ready for CTR check.")
        return

    for alert in alerts:
        print(f"   {alert.message}")
        # Send to Slack
        try:
            slack.send_message(
                f"📊 *CTR Check: {alert.video_title}*\n"
                f"{alert.message}\n"
                f"_Impressions: {alert.impressions:,} | Hours: {alert.hours_since_publish:.0f}_"
            )
        except Exception as e:
            print(f"   Warning: Failed to send Slack alert: {e}")

    print(f"   Checked {len(alerts)} experiment(s).")


def main():
    """CLI entry point."""
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(description="CTR Monitor")
    parser.add_argument("--check-active", action="store_true", help="Check all active experiments")
    args = parser.parse_args()

    if args.check_active:
        asyncio.run(main_async())
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
