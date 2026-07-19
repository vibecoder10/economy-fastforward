"""
Autopilot Brain - Main Orchestrator

This is the entry point for the autopilot system. It:
1. Loads config and state
2. Checks if enabled and if production slot is available
3. Gathers candidates from Competitor Videos table
4. Scores candidates using weighted signals
5. Picks the best idea and notifies Slack
6. Extracts theme/formula from competitor video
7. Creates original idea in Airtable via modeling

Usage:
    python -m autopilot.autopilot --check-cycle
    python -m autopilot.autopilot --status
    python -m autopilot.autopilot --force
    python -m autopilot.autopilot --dry-run  # Test without creating records
"""

import os
import sys
import argparse
import asyncio
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
from autopilot.core.confidence_scorer import ConfidenceScorer, IdeaCandidate, ScoredIdea
from autopilot.analysis.theme_extractor import ThemeExtractor
from autopilot.production.idea_creator import IdeaCreator


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
        anthropic_client=None,
    ):
        """Initialize autopilot with all dependencies.

        Args:
            config: Config override (for testing)
            state_manager: State manager override (for testing)
            airtable_client: Airtable client override (for testing)
            slack_client: Slack client override (for testing)
            anthropic_client: Anthropic client override (for testing)
        """
        self.config = config or load_config()
        self.state_manager = state_manager or StateManager()
        self.airtable = airtable_client
        self.slack = slack_client
        self.anthropic = anthropic_client
        self.scorer = ConfidenceScorer(self.config)

        # Theme extractor and idea creator (lazy init)
        self.theme_extractor: Optional[ThemeExtractor] = None
        self.idea_creator: Optional[IdeaCreator] = None

        # Lazy load clients if not provided
        self._clients_initialized = (airtable_client is not None and slack_client is not None)

    def _init_clients(self):
        """Initialize API clients (lazy load)."""
        # Initialize external API clients if not already provided
        if not self._clients_initialized:
            try:
                from shared.clients.airtable_client import AirtableClient
                from shared.clients.slack_client import SlackClient
                self.airtable = AirtableClient()
                self.slack = SlackClient()
                self._clients_initialized = True
            except ImportError as e:
                print(f"Warning: Could not import clients: {e}")
                print("Running in test mode without external dependencies.")

        # Always initialize theme extractor and idea creator if not yet done
        if self.theme_extractor is None:
            self.theme_extractor = ThemeExtractor(anthropic_client=self.anthropic)

        if self.idea_creator is None and self.airtable is not None:
            self.idea_creator = IdeaCreator(
                airtable_client=self.airtable,
                anthropic_client=self.anthropic,
            )

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

    async def _create_modeled_idea(
        self,
        best: ScoredIdea,
        dry_run: bool = False,
    ) -> Optional[dict]:
        """Extract theme from competitor and create original idea.

        Args:
            best: The best scored idea (competitor video)
            dry_run: If True, don't create Airtable record

        Returns:
            Created Airtable record or None
        """
        if self.theme_extractor is None or self.idea_creator is None:
            print("   Warning: Theme extractor or idea creator not initialized")
            return None

        competitor_title = best.candidate.competitor_title or best.candidate.title

        # 1. Extract theme, angle, formula from competitor title
        print(f"   Extracting theme from: {competitor_title}")
        theme_analysis = await self.theme_extractor.extract(competitor_title)

        if theme_analysis is None:
            print("   Warning: Theme extraction failed, using quick extraction")
            # Fall back to quick extraction (no API call)
            from autopilot.analysis.theme_extractor import ThemeAnalysis
            theme_analysis = ThemeAnalysis(
                primary_theme=competitor_title,
                angle_type=ThemeExtractor.quick_extract_angle(competitor_title),
                topic_category=ThemeExtractor.quick_extract_topic_category(competitor_title),
                confidence=0.5,
            )

        print(f"   Theme: {theme_analysis.primary_theme}")
        print(f"   Angle: {theme_analysis.angle_type}")
        print(f"   Formula: {theme_analysis.title_formula}")
        print(f"   Confidence: {theme_analysis.confidence:.0%}")

        if dry_run:
            print("   [DRY RUN] Would create idea using this formula")
            print(f"   [DRY RUN] Formula: {theme_analysis.title_formula}")
            print(f"   [DRY RUN] Variables: {theme_analysis.formula_variables}")
            # In dry run, we skip the API call to avoid needing async mocks in tests
            # The actual generation is tested in test_idea_creator.py
            return None

        # 2. Create idea in Airtable
        print("   Creating original idea in Airtable...")
        record = await self.idea_creator.create_idea_from_competitor(
            candidate=best.candidate,
            theme_analysis=theme_analysis,
            idea_index=0,  # Use first generated idea
        )

        if record:
            print(f"   ✅ Created idea: {record.get('id', 'unknown')}")
            # Notify Slack with the created idea
            idea_title = record.get('fields', {}).get('Video Title', 'Unknown')
            self._notify(
                f"✨ *AUTOPILOT: Original idea created*\n\n"
                f"*TITLE:* {idea_title}\n"
                f"*MODELED FROM:* {competitor_title}\n"
                f"*FORMULA:* {theme_analysis.title_formula}\n"
                f"*ANGLE:* {theme_analysis.angle_type}\n\n"
                f"_Idea ready for pipeline. Approve to start production._"
            )
        else:
            print("   ⚠️ Failed to create idea")

        return record

    def check_cycle(self, force: bool = False, dry_run: bool = False) -> bool:
        """Run one autopilot cycle.

        Args:
            force: Skip cadence check and run anyway
            dry_run: If True, don't create Airtable records (test mode)

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
            best_score_str = f"{best_score:.0f}" if best_score is not None else "N/A"
            print(f"   No candidates meet threshold. Best: {best_score_str}")
            self._notify(
                f"📭 *AUTOPILOT: No candidates ready*\n\n"
                f"No ideas meet the confidence threshold of *{self.config.thresholds.min_confidence_score}*.\n"
                f"Best candidate scored *{best_score_str}*."
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

        # 7. Extract theme and create original idea
        print(f"   ✅ Selected competitor: {best.candidate.title}")

        if dry_run:
            print("   [DRY RUN] Testing idea creation without saving...")
            # Run async idea creation (dry run - no actual API calls)
            asyncio.run(self._create_modeled_idea(best, dry_run=True))
            # Record state with competitor title (no idea created)
            self.state_manager.record_production_cycle(
                video_title=best.candidate.title,
                modeled_from=best.candidate.competitor_title,
                idea_record_id=None,
            )
            print("   [DRY RUN] Cycle complete (no records created)")
            return True

        # Run async idea creation (real mode)
        record = asyncio.run(self._create_modeled_idea(best, dry_run=False))

        if record is None:
            print("   ⚠️ Idea creation failed")
            return False

        # 8. Record state with created idea
        idea_record_id = record.get('id') if record else None
        idea_title = record.get('fields', {}).get('Video Title', best.candidate.title) if record else best.candidate.title

        self.state_manager.record_production_cycle(
            video_title=idea_title,
            modeled_from=best.candidate.competitor_title,
            idea_record_id=idea_record_id,
        )

        print(f"   ✅ Idea created and ready for pipeline: {idea_title}")

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
    parser.add_argument("--dry-run", action="store_true", help="Test without creating Airtable records")

    args = parser.parse_args()

    autopilot = Autopilot()

    if args.status:
        autopilot.status()
    elif args.check_cycle or args.force or args.dry_run:
        autopilot.check_cycle(force=args.force, dry_run=args.dry_run)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
