"""
Autopilot Brain - Main Orchestrator

This is the entry point for the autopilot system. It:
1. Loads config and state
2. Checks if enabled and if production slot is available
3. Gathers candidates from Competitor Videos table
4. Scores candidates using weighted signals
5. Picks the best idea and notifies Slack
6. Triggers pipeline execution

Usage:
    python -m autopilot.autopilot --check-cycle
    python -m autopilot.autopilot --status
    python -m autopilot.autopilot --force
"""

import os
import sys
import argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Optional

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from autopilot.core.config_parser import load_config, AutopilotConfig
from autopilot.core.state_manager import StateManager, AutopilotState
from autopilot.core.cadence_manager import CadenceManager
from autopilot.core.confidence_scorer import ConfidenceScorer, IdeaCandidate


# Competitor video field names (matches Airtable schema)
class CompetitorVideoFields:
    """Field names for Competitor Videos table."""
    VIDEO_ID = "Video ID"
    TITLE = "Title"
    URL = "URL"
    CHANNEL = "Channel"
    VIEWS = "Views"
    VPH = "VPH"
    HOURS_OLD = "Hours Old"
    PUBLISHED_DATE = "Published Date"
    SCRAPE_DATE = "Scrape Date"
    MODELED = "Modeled"


class Autopilot:
    """Main autopilot orchestrator."""

    def __init__(
        self,
        config: Optional[AutopilotConfig] = None,
        state_manager: Optional[StateManager] = None,
        airtable_client=None,
        slack_client=None,
    ):
        """Initialize autopilot with all dependencies.

        Args:
            config: Config override (for testing)
            state_manager: State manager override (for testing)
            airtable_client: Airtable client override (for testing)
            slack_client: Slack client override (for testing)
        """
        self.config = config or load_config()
        self.state_manager = state_manager or StateManager()
        self.airtable = airtable_client
        self.slack = slack_client
        self.scorer = ConfidenceScorer(self.config)

        # Lazy load clients if not provided
        self._clients_initialized = (airtable_client is not None and slack_client is not None)

    def _init_clients(self):
        """Initialize API clients (lazy load)."""
        if self._clients_initialized:
            return

        try:
            from clients.airtable_client import AirtableClient
            from clients.slack_client import SlackClient
            self.airtable = AirtableClient()
            self.slack = SlackClient()
            self._clients_initialized = True
        except ImportError as e:
            print(f"Warning: Could not import clients: {e}")
            print("Running in test mode without external dependencies.")

    def _get_candidates_from_competitor_videos(self) -> List[IdeaCandidate]:
        """Fetch candidate ideas from Competitor Videos table.

        Returns:
            List of IdeaCandidate objects
        """
        if self.airtable is None:
            print("   Warning: No Airtable client available")
            return []

        # Get recent competitor videos with high VPH
        min_vph = self.config.thresholds.min_competitor_vph
        max_age_days = self.config.thresholds.max_idea_age_days

        try:
            # Check if method exists (will be implemented in Chunk 2)
            if hasattr(self.airtable, 'get_competitor_videos'):
                records = self.airtable.get_competitor_videos(
                    min_vph=min_vph,
                    max_age_days=max_age_days,
                    exclude_modeled=True,
                )
            else:
                print("   Note: get_competitor_videos not yet implemented")
                return []
        except Exception as e:
            print(f"   Error fetching competitor videos: {e}")
            return []

        candidates = []
        for record in records:
            fields = record.get('fields', {})

            # Calculate hours old
            published = fields.get(CompetitorVideoFields.PUBLISHED_DATE)
            hours_old = 0
            if published:
                try:
                    pub_dt = datetime.fromisoformat(published.replace('Z', '+00:00'))
                    hours_old = (datetime.now(timezone.utc) - pub_dt).total_seconds() / 3600
                except:
                    pass

            candidate = IdeaCandidate(
                record_id=record['id'],
                title=fields.get(CompetitorVideoFields.TITLE, "Unknown"),
                source_type="competitor",
                competitor_vph=fields.get(CompetitorVideoFields.VPH, 0),
                competitor_title=fields.get(CompetitorVideoFields.TITLE),
                hours_old=hours_old,
            )
            candidates.append(candidate)

        return candidates

    def _notify(self, message: str) -> None:
        """Send Slack notification.

        Args:
            message: Message to send
        """
        if self.slack is None:
            print(f"   [Slack disabled] {message[:100]}...")
            return

        try:
            self.slack.send_message(message)
        except Exception as e:
            print(f"   Warning: Could not send Slack message: {e}")

    def check_cycle(self, force: bool = False) -> bool:
        """Run one autopilot cycle.

        Args:
            force: Skip cadence check and run anyway

        Returns:
            True if production started, False otherwise
        """
        print("🤖 Autopilot: Checking cycle...")

        # Initialize clients
        self._init_clients()

        # 1. Check if enabled
        state = self.state_manager.load()
        if not state.autopilot_enabled:
            print("   Autopilot is disabled.")
            return False

        # 2. Check cadence (unless forced)
        if not force:
            cadence = CadenceManager(self.config, state)
            if not cadence.is_production_slot_available():
                days = cadence.days_until_next()
                next_date = cadence.get_next_production_date().strftime("%Y-%m-%d")
                print(f"   Not time yet. Next slot in {days} day(s) ({next_date}).")
                return False

        # 3. Gather candidates
        print("   Gathering candidates...")
        candidates = self._get_candidates_from_competitor_videos()

        if not candidates:
            print("   No candidates found.")
            self._notify(f"📭 *AUTOPILOT: No candidates ready*\n\nNo ideas found in Competitor Videos table.")
            return False

        print(f"   Found {len(candidates)} candidates.")

        # 4. Score and pick best
        best = self.scorer.get_best(candidates)

        if best is None:
            # Get best score for notification
            all_scored = self.scorer.rank(candidates)
            best_score = all_scored[0].score if all_scored else None
            print(f"   No candidates meet threshold. Best: {best_score:.0f if best_score else 'N/A'}")
            self._notify(
                f"📭 *AUTOPILOT: No candidates ready*\n\n"
                f"No ideas meet the confidence threshold of *{self.config.thresholds.min_confidence_score}*.\n"
                f"Best candidate scored *{best_score:.0f if best_score else 'N/A'}*."
            )
            return False

        print(f"   Best candidate: {best.candidate.title} (score: {best.score:.0f})")

        # 5. Format reasoning
        reasoning_lines = [f"• {r}" for r in best.reasoning]
        reasoning_text = "\n".join(reasoning_lines)

        # 6. Notify Slack
        message = f"""🎬 *AUTOPILOT: Starting production*

*VIDEO:* {best.candidate.title}
*CONFIDENCE:* {best.score:.0f}/100

*WHY THIS IDEA:*
{reasoning_text}
"""
        if best.candidate.competitor_title:
            message += f"\n*MODELING:* {best.candidate.competitor_title}"
            if best.candidate.competitor_vph:
                message += f" (VPH: {best.candidate.competitor_vph:.0f})"

        message += "\n\n_Production begins. Reply STOP to abort._"

        self._notify(message)

        # 7. Record state
        self.state_manager.record_production_cycle(
            video_title=best.candidate.title,
            modeled_from=best.candidate.competitor_title,
        )

        # 8. Trigger pipeline (placeholder for Chunk 2)
        print(f"   ✅ Selected: {best.candidate.title}")
        print("   TODO: Trigger pipeline (Chunk 2)")

        return True

    def status(self) -> None:
        """Print current autopilot status."""
        state = self.state_manager.load()

        print("\n🤖 Autopilot Status")
        print("=" * 40)
        print(f"Enabled: {'✅ ON' if state.autopilot_enabled else '🔴 OFF'}")
        print(f"Videos produced: {state.videos_produced}")
        print(f"Avg CTR: {state.channel_avg_ctr:.1f}%")

        if state.last_cycle:
            print(f"Last cycle: {state.last_cycle}")
            cadence = CadenceManager(self.config, state)
            if cadence.is_production_slot_available():
                print("Next slot: ✅ Ready now")
            else:
                days = cadence.days_until_next()
                next_date = cadence.get_next_production_date().strftime("%Y-%m-%d")
                print(f"Next slot: {next_date} ({days} day(s))")
        else:
            print("Last cycle: Never run")
            print("Next slot: ✅ Ready now")

        if state.current_experiment:
            exp = state.current_experiment
            print(f"\nCurrent experiment:")
            print(f"  Title: {exp.video_title}")
            print(f"  Status: {exp.status}")
            if exp.modeled_from:
                print(f"  Modeled from: {exp.modeled_from}")

        print("=" * 40)


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Autopilot Brain")
    parser.add_argument("--check-cycle", action="store_true", help="Run one autopilot cycle")
    parser.add_argument("--status", action="store_true", help="Show current status")
    parser.add_argument("--force", action="store_true", help="Force production (skip cadence)")

    args = parser.parse_args()

    autopilot = Autopilot()

    if args.status:
        autopilot.status()
    elif args.check_cycle or args.force:
        autopilot.check_cycle(force=args.force)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
