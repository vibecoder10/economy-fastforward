"""
Osiris Performance Analyzer - Post-mortem analysis and learning extraction.

Analyzes YOUR channel's YouTube performance and extracts patterns that
feed back into video generation prompts.

The 48-hour mark is critical: YouTube's algorithm makes push/kill decisions there.
We analyze at 48h for early intervention (title/thumbnail swap), then at 7d for
final learnings that persist.

Usage:
    python -m osiris analyze
    python -m osiris analyze --dry-run
    python -m osiris.performance_analyzer --dry-run

Cron (7:30 AM PT, after performance_tracker):
    30 7 * * * cd $PROJECT && python -m osiris analyze
"""

import asyncio
import json
import logging
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

from pipeline_constants import IdeaFields

logger = logging.getLogger(__name__)


# Performance thresholds based on YouTube niche benchmarks
CTR_THRESHOLDS = {
    "strong": 5.0,   # >5% is excellent for educational content
    "average": 3.0,  # 3-5% is average
    # <3% is weak
}

RETENTION_THRESHOLDS = {
    "strong": 55.0,  # >55% is excellent for 15-25 min videos
    "average": 40.0,  # 40-55% is average
    # <40% is weak
}


@dataclass
class PostMortemResult:
    """Result of a video post-mortem analysis."""
    video_id: str
    video_title: str
    analysis_type: str  # "48h" or "7d"
    ctr_verdict: str  # "strong", "average", "weak"
    retention_verdict: str  # "strong", "average", "weak"
    overall_verdict: str  # "strong", "average", "weak"
    recommendations: list[str]
    learnings: list[dict]
    raw_metrics: dict


class PerformanceAnalyzer:
    """Analyzes video performance and extracts learnings.

    Runs post-mortems at 48h and 7d milestones:
    - 48h: Early warning for title/thumbnail swaps
    - 7d: Final verdict + learning extraction for future videos

    Usage:
        analyzer = PerformanceAnalyzer(airtable_client)
        results = await analyzer.run_post_mortems()
    """

    def __init__(
        self,
        airtable_client,
        slack_client=None,
    ):
        """Initialize the performance analyzer.

        Args:
            airtable_client: AirtableClient instance
            slack_client: Optional SlackClient for notifications
        """
        self.airtable = airtable_client
        self.slack = slack_client

    async def run_post_mortems(
        self,
        dry_run: bool = False,
    ) -> dict:
        """Run post-mortems on all videos that need analysis.

        Args:
            dry_run: If True, prints what would be done without writing

        Returns:
            {
                "videos_analyzed": int,
                "learnings_extracted": int,
                "weak_performers": list[str],  # Video titles needing attention
                "errors": list[str],
            }
        """
        result = {
            "videos_analyzed": 0,
            "learnings_extracted": 0,
            "weak_performers": [],
            "errors": [],
            "details": [],
        }

        # Get videos needing post-mortem
        logger.info("Fetching videos needing post-mortem...")
        try:
            loop = asyncio.get_event_loop()
            videos = await loop.run_in_executor(
                None,
                self.airtable.get_videos_needing_postmortem,
            )
        except Exception as e:
            error = f"Failed to fetch videos: {e}"
            logger.error(error)
            result["errors"].append(error)
            return result

        if not videos:
            logger.info("No videos need post-mortem analysis")
            return result

        logger.info(f"Found {len(videos)} videos needing analysis")

        # Process each video
        for video in videos:
            analysis_type = video.get("_analysis_type", "48h")
            title = video.get(IdeaFields.VIDEO_TITLE, "Unknown")
            record_id = video.get("id")

            logger.info(f"Analyzing: {title} ({analysis_type} post-mortem)")

            try:
                if analysis_type == "48h":
                    pm_result = await self._analyze_48h(video)
                else:
                    pm_result = await self._analyze_7d(video)

                result["videos_analyzed"] += 1
                result["details"].append({
                    "title": title,
                    "type": analysis_type,
                    "verdict": pm_result.overall_verdict,
                    "learnings": len(pm_result.learnings),
                })

                if pm_result.overall_verdict == "weak":
                    result["weak_performers"].append(title)

                # Persist results
                if not dry_run:
                    # Save post-mortem analysis to Ideas table
                    field_name = IdeaFields.POST_MORTEM_48H if analysis_type == "48h" else IdeaFields.POST_MORTEM_7D
                    analysis_json = json.dumps({
                        "ctr_verdict": pm_result.ctr_verdict,
                        "retention_verdict": pm_result.retention_verdict,
                        "overall_verdict": pm_result.overall_verdict,
                        "recommendations": pm_result.recommendations,
                        "analyzed_at": datetime.now(timezone.utc).isoformat(),
                        "metrics": pm_result.raw_metrics,
                    })
                    await self._update_idea_field(record_id, field_name, analysis_json)

                    # Save Performance Verdict (simplified for filtering)
                    await self._update_idea_field(
                        record_id,
                        IdeaFields.PERFORMANCE_VERDICT,
                        pm_result.overall_verdict,
                    )

                    # Extract and save learnings (7d only - final verdict)
                    if analysis_type == "7d" and pm_result.learnings:
                        for learning in pm_result.learnings:
                            try:
                                await self._create_learning(learning)
                                result["learnings_extracted"] += 1
                            except Exception as e:
                                logger.warning(f"Failed to save learning: {e}")
                else:
                    logger.info(f"  DRY RUN: Would save {analysis_type} post-mortem")
                    if pm_result.learnings:
                        logger.info(f"  DRY RUN: Would extract {len(pm_result.learnings)} learnings")
                        for learning in pm_result.learnings:
                            logger.info(f"    - {learning.get('category')}: {learning.get('pattern')[:50]}...")

            except Exception as e:
                error = f"Failed to analyze {title}: {e}"
                logger.error(error)
                result["errors"].append(error)

        # Send Slack notification for weak performers
        if self.slack and not dry_run and result["weak_performers"]:
            try:
                self._send_weak_performer_alert(result["weak_performers"])
            except Exception as e:
                logger.warning(f"Slack notification failed: {e}")

        return result

    async def _analyze_48h(self, video: dict) -> PostMortemResult:
        """48-hour post-mortem: Early warning analysis.

        Focuses on CTR and early retention signals. If CTR is weak,
        recommends title/thumbnail swap before algorithm gives up.
        """
        title = video.get(IdeaFields.VIDEO_TITLE, "Unknown")
        video_id = video.get(IdeaFields.YOUTUBE_VIDEO_ID, "")

        # Get metrics (prefer 48h snapshots, fall back to current)
        ctr = video.get(IdeaFields.CTR_48H) or video.get(IdeaFields.CTR)
        retention = video.get(IdeaFields.RETENTION_48H) or video.get(IdeaFields.AVG_RETENTION)
        impressions = video.get(IdeaFields.IMPRESSIONS, 0)
        views_48h = video.get(IdeaFields.VIEWS_48H) or video.get(IdeaFields.VIEWS, 0)

        raw_metrics = {
            "ctr": ctr,
            "retention": retention,
            "impressions": impressions,
            "views_48h": views_48h,
        }

        # Diagnose
        ctr_verdict = self._diagnose_ctr(ctr)
        retention_verdict = self._diagnose_retention(retention)
        overall_verdict = self._calculate_overall_verdict(ctr_verdict, retention_verdict)

        # Generate recommendations
        recommendations = []
        if ctr_verdict == "weak":
            recommendations.append("Consider A/B testing a new thumbnail")
            recommendations.append("Review title for curiosity/urgency hooks")
        if retention_verdict == "weak":
            recommendations.append("Review hook script (first 30 seconds)")
            recommendations.append("Check for slow pacing in opening act")

        return PostMortemResult(
            video_id=video_id,
            video_title=title,
            analysis_type="48h",
            ctr_verdict=ctr_verdict,
            retention_verdict=retention_verdict,
            overall_verdict=overall_verdict,
            recommendations=recommendations,
            learnings=[],  # No learning extraction at 48h
            raw_metrics=raw_metrics,
        )

    async def _analyze_7d(self, video: dict) -> PostMortemResult:
        """7-day post-mortem: Final verdict + learning extraction.

        Full analysis with learning extraction. These insights get
        persisted and fed back into generation prompts.
        """
        title = video.get(IdeaFields.VIDEO_TITLE, "Unknown")
        video_id = video.get(IdeaFields.YOUTUBE_VIDEO_ID, "")

        # Get final metrics
        ctr = video.get(IdeaFields.CTR)
        retention = video.get(IdeaFields.AVG_RETENTION)
        impressions = video.get(IdeaFields.IMPRESSIONS, 0)
        views = video.get(IdeaFields.VIEWS, 0)
        views_7d = video.get(IdeaFields.VIEWS_7D) or views
        watch_time = video.get(IdeaFields.WATCH_TIME_HOURS, 0)
        framework = video.get(IdeaFields.FRAMEWORK_ANGLE, "")
        hook_script = video.get(IdeaFields.HOOK_SCRIPT, "")

        raw_metrics = {
            "ctr": ctr,
            "retention": retention,
            "impressions": impressions,
            "views": views,
            "views_7d": views_7d,
            "watch_time_hours": watch_time,
            "framework": framework,
        }

        # Diagnose
        ctr_verdict = self._diagnose_ctr(ctr)
        retention_verdict = self._diagnose_retention(retention)
        overall_verdict = self._calculate_overall_verdict(ctr_verdict, retention_verdict)

        # Generate recommendations
        recommendations = []
        if overall_verdict == "strong":
            recommendations.append("Continue with similar title patterns")
            recommendations.append("Document what worked for future reference")
        elif overall_verdict == "weak":
            recommendations.append("Analyze competitor titles in same topic")
            recommendations.append("Review thumbnail against top performers")

        # Extract learnings (only for videos with enough data)
        learnings = []
        if ctr is not None and impressions >= 1000:
            learnings.extend(self._extract_title_learnings(video, ctr, ctr_verdict))
        if retention is not None and views >= 500:
            learnings.extend(self._extract_retention_learnings(video, retention, retention_verdict))
        if framework and (ctr is not None or retention is not None):
            learnings.extend(self._extract_framework_learnings(video, ctr, retention, framework))

        return PostMortemResult(
            video_id=video_id,
            video_title=title,
            analysis_type="7d",
            ctr_verdict=ctr_verdict,
            retention_verdict=retention_verdict,
            overall_verdict=overall_verdict,
            recommendations=recommendations,
            learnings=learnings,
            raw_metrics=raw_metrics,
        )

    def _diagnose_ctr(self, ctr: Optional[float]) -> str:
        """Diagnose CTR performance."""
        if ctr is None:
            return "unknown"
        if ctr >= CTR_THRESHOLDS["strong"]:
            return "strong"
        if ctr >= CTR_THRESHOLDS["average"]:
            return "average"
        return "weak"

    def _diagnose_retention(self, retention: Optional[float]) -> str:
        """Diagnose retention performance."""
        if retention is None:
            return "unknown"
        if retention >= RETENTION_THRESHOLDS["strong"]:
            return "strong"
        if retention >= RETENTION_THRESHOLDS["average"]:
            return "average"
        return "weak"

    def _calculate_overall_verdict(self, ctr: str, retention: str) -> str:
        """Calculate overall performance verdict.

        Both strong = strong
        One weak = average
        Both weak = weak
        Unknown handled gracefully
        """
        if ctr == "unknown" and retention == "unknown":
            return "unknown"
        if ctr == "strong" and retention == "strong":
            return "strong"
        if ctr == "weak" or retention == "weak":
            if ctr == "weak" and retention == "weak":
                return "weak"
            return "average"
        return "average"

    def _extract_title_learnings(
        self,
        video: dict,
        ctr: float,
        verdict: str,
    ) -> list[dict]:
        """Extract learnings from title performance."""
        title = video.get(IdeaFields.VIDEO_TITLE, "")
        learnings = []

        # Only extract positive learnings (CTR > 4%) or notable negative (<2%)
        if verdict not in ("strong", "weak"):
            return learnings

        # Detect title patterns
        patterns_found = []

        # Question titles
        if "?" in title:
            patterns_found.append("Question format title")

        # Number/statistic titles
        if re.search(r'\$[\d,]+|\d+%|\d{4}', title):
            patterns_found.append("Numbers/statistics in title")

        # Future date titles
        if re.search(r'20\d{2}', title):
            patterns_found.append("Future year in title")

        # ALL CAPS words
        if re.search(r'\b[A-Z]{4,}\b', title):
            patterns_found.append("ALL CAPS emphasis word")

        # Colon structure
        if ":" in title:
            patterns_found.append("Colon structure (Topic: Hook)")

        # Create learning for each pattern
        for pattern in patterns_found:
            learnings.append({
                "category": "title",
                "pattern": f"{pattern}: {verdict} CTR ({ctr:.1f}%)",
                "confidence": 60 if verdict == "strong" else 40,
                "sample_size": 1,
                "avg_ctr": ctr,
                "source_videos": [title],
            })

        return learnings

    def _extract_retention_learnings(
        self,
        video: dict,
        retention: float,
        verdict: str,
    ) -> list[dict]:
        """Extract learnings from retention performance."""
        title = video.get(IdeaFields.VIDEO_TITLE, "")
        hook = video.get(IdeaFields.HOOK_SCRIPT, "")
        learnings = []

        if verdict not in ("strong", "weak"):
            return learnings

        # Analyze hook style
        if hook:
            hook_lower = hook.lower()

            # Counter-narrative hook
            if any(word in hook_lower for word in ["but", "however", "actually", "truth"]):
                learnings.append({
                    "category": "hook",
                    "pattern": f"Counter-narrative hook: {verdict} retention ({retention:.1f}%)",
                    "confidence": 55,
                    "sample_size": 1,
                    "avg_retention": retention,
                    "source_videos": [title],
                })

            # Question hook
            if "?" in hook[:100]:
                learnings.append({
                    "category": "hook",
                    "pattern": f"Question opening: {verdict} retention ({retention:.1f}%)",
                    "confidence": 55,
                    "sample_size": 1,
                    "avg_retention": retention,
                    "source_videos": [title],
                })

            # Statistic hook
            if re.search(r'\$[\d,]+|\d+%', hook[:150]):
                learnings.append({
                    "category": "hook",
                    "pattern": f"Statistic/number hook: {verdict} retention ({retention:.1f}%)",
                    "confidence": 55,
                    "sample_size": 1,
                    "avg_retention": retention,
                    "source_videos": [title],
                })

        return learnings

    def _extract_framework_learnings(
        self,
        video: dict,
        ctr: Optional[float],
        retention: Optional[float],
        framework: str,
    ) -> list[dict]:
        """Extract framework-specific performance learnings."""
        title = video.get(IdeaFields.VIDEO_TITLE, "")
        learnings = []

        pattern_parts = [f"Framework '{framework}'"]
        if ctr is not None:
            pattern_parts.append(f"CTR {ctr:.1f}%")
        if retention is not None:
            pattern_parts.append(f"retention {retention:.1f}%")

        learnings.append({
            "category": "framework",
            "pattern": " | ".join(pattern_parts),
            "confidence": 50,
            "sample_size": 1,
            "avg_ctr": ctr,
            "avg_retention": retention,
            "source_videos": [title],
        })

        return learnings

    async def _update_idea_field(self, record_id: str, field: str, value) -> None:
        """Update a single field on an Ideas record."""
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                None,
                lambda: self.airtable.update_idea_fields(record_id, {field: value}),
            )
        except Exception as e:
            logger.warning(f"Failed to update {field}: {e}")

    async def _create_learning(self, learning: dict) -> None:
        """Create a learning record."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            self.airtable.create_learning,
            learning,
        )

    def _send_weak_performer_alert(self, weak_performers: list[str]) -> None:
        """Send Slack alert for weak performers."""
        msg = "*Osiris Performance Alert*\n\n"
        msg += f"{len(weak_performers)} video(s) need attention (weak CTR or retention):\n"
        for title in weak_performers[:5]:
            msg += f"  - {title}\n"
        if len(weak_performers) > 5:
            msg += f"  ... and {len(weak_performers) - 5} more\n"
        msg += "\nConsider title/thumbnail A/B testing."

        self.slack.send_message(msg)


async def run_performance_analyzer(
    airtable_client=None,
    slack_client=None,
    dry_run: bool = False,
) -> dict:
    """Convenience function to run performance analysis.

    Args:
        airtable_client: Optional AirtableClient (created if None)
        slack_client: Optional SlackClient (created if None)
        dry_run: If True, prints without saving

    Returns:
        Result dict with analysis statistics
    """
    # Create clients if not provided
    if airtable_client is None:
        from clients.airtable_client import AirtableClient
        airtable_client = AirtableClient()

    if slack_client is None and not dry_run:
        try:
            from clients.slack_client import SlackClient
            slack_client = SlackClient()
        except Exception:
            slack_client = None

    analyzer = PerformanceAnalyzer(
        airtable_client=airtable_client,
        slack_client=slack_client,
    )

    return await analyzer.run_post_mortems(dry_run=dry_run)


async def _cli_main():
    """CLI entry point for performance analyzer."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Osiris Performance Analyzer - Post-mortem analysis"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without writing",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    print("=" * 60)
    print("OSIRIS PERFORMANCE ANALYZER")
    print("=" * 60)
    print(f"  Date: {date.today().isoformat()}")
    print(f"  Dry run: {args.dry_run}")
    print("=" * 60)
    print()

    result = await run_performance_analyzer(dry_run=args.dry_run)

    print()
    print("=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"  Videos analyzed:      {result['videos_analyzed']}")
    print(f"  Learnings extracted:  {result['learnings_extracted']}")
    print(f"  Weak performers:      {len(result['weak_performers'])}")

    if result["details"]:
        print("\n  Details:")
        for detail in result["details"]:
            print(f"    - {detail['title'][:40]} ({detail['type']}): {detail['verdict']}")

    if result["weak_performers"]:
        print("\n  Needs attention:")
        for title in result["weak_performers"]:
            print(f"    - {title}")

    if result["errors"]:
        print(f"\n  Errors: {len(result['errors'])}")
        for err in result["errors"]:
            print(f"    - {err}")

    print("=" * 60)

    if result["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(_cli_main())
