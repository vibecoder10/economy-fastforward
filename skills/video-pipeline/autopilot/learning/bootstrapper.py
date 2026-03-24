# skills/video-pipeline/autopilot/learning/bootstrapper.py
"""Bootstrap memory files from historical video performance.

Scans ALL existing videos with CTR data in Airtable and extracts
patterns to populate memory files with a day-1 baseline.

Usage:
    python -m autopilot.learning.bootstrapper --dry-run
    python -m autopilot.learning.bootstrapper --scan-all
"""

import os
import sys
import argparse
import asyncio
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict, Any
import logging

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv()

from autopilot.learning.learning_extractor import LearningExtractor, ThemeData, ExperimentResult
from autopilot.learning.memory_writer import MemoryWriter
from autopilot.analysis.theme_extractor import ThemeExtractor

logger = logging.getLogger(__name__)


class Bootstrapper:
    """Bootstrap memory from historical video performance data."""

    # Airtable field names for Ideas table
    TITLE_FIELD = "Video Title"
    CTR_FIELD = "CTR (%)"
    CTR_48H_FIELD = "CTR 48h (%)"
    THUMBNAIL_OVERRIDE_FIELD = "Thumbnail Style Override"
    UPLOAD_DATE_FIELD = "Upload Date"
    STATUS_FIELD = "Status"

    def __init__(self, airtable_client=None, dry_run: bool = False):
        """Initialize bootstrapper.

        Args:
            airtable_client: Airtable client (optional, will create if None)
            dry_run: If True, don't write to memory files
        """
        self.airtable = airtable_client
        self.dry_run = dry_run
        self.extractor = LearningExtractor()
        self.theme_extractor = ThemeExtractor()
        self.writer = MemoryWriter()
        self._initialized = False

    def _init_clients(self):
        """Initialize Airtable client if not provided."""
        if self._initialized:
            return

        if self.airtable is None:
            try:
                from shared.clients.airtable_client import AirtableClient
                self.airtable = AirtableClient()
            except ImportError as e:
                logger.error(f"Could not import AirtableClient: {e}")
                return

        self._initialized = True

    def get_videos_with_ctr(self) -> List[Dict[str, Any]]:
        """Fetch all videos that have CTR data from Airtable.

        Returns:
            List of Airtable records with CTR data
        """
        self._init_clients()

        if self.airtable is None:
            logger.warning("No Airtable client available")
            return []

        try:
            # Get ideas that are uploaded and have CTR data
            # Filter: Status contains "Uploaded" or "Complete" and CTR exists
            records = self.airtable.get_ideas_by_status(["Uploaded", "Complete"])

            # Filter to only records with CTR data
            videos_with_ctr = []
            for record in records:
                fields = record.get('fields', {})
                ctr = fields.get(self.CTR_FIELD) or fields.get(self.CTR_48H_FIELD)
                if ctr is not None and ctr > 0:
                    videos_with_ctr.append(record)

            return videos_with_ctr

        except Exception as e:
            logger.error(f"Error fetching videos: {e}")
            return []

    async def analyze_video(self, record: Dict[str, Any]) -> Optional[ExperimentResult]:
        """Analyze a single video and extract learnings.

        Args:
            record: Airtable record with video data

        Returns:
            ExperimentResult or None if analysis failed
        """
        fields = record.get('fields', {})
        title = fields.get(self.TITLE_FIELD)
        if not title:
            return None

        # Get CTR (prefer 48h, fall back to current)
        ctr = fields.get(self.CTR_48H_FIELD) or fields.get(self.CTR_FIELD)
        if ctr is None or ctr <= 0:
            return None

        thumbnail_override = fields.get(self.THUMBNAIL_OVERRIDE_FIELD)

        # Extract theme using Claude
        theme_analysis = await self.theme_extractor.extract(title)

        # Convert to ThemeData
        theme_data = None
        if theme_analysis:
            theme_data = ThemeData(
                primary_theme=theme_analysis.primary_theme,
                secondary_themes=theme_analysis.secondary_themes,
                angle_type=theme_analysis.angle_type,
                emotional_hooks=theme_analysis.emotional_hooks,
                topic_category=theme_analysis.topic_category,
                title_formula=theme_analysis.title_formula,
                formula_variables=theme_analysis.formula_variables,
            )

        # Extract all learnings
        result = self.extractor.extract_all(
            video_title=title,
            ctr=ctr,
            thumbnail_override=thumbnail_override,
            modeled_from=None,  # Historical videos weren't necessarily modeled
            theme_data=theme_data,
        )

        return result

    async def scan_all(self) -> Dict[str, Any]:
        """Scan all videos with CTR data and extract patterns.

        Returns:
            Summary statistics of the scan
        """
        print("🔍 Bootstrapper: Scanning historical videos...")

        videos = self.get_videos_with_ctr()
        if not videos:
            print("   No videos with CTR data found.")
            return {"videos_scanned": 0, "patterns_extracted": 0}

        print(f"   Found {len(videos)} videos with CTR data.")

        all_results: List[ExperimentResult] = []
        total_ctr = 0.0
        best_ctr = 0.0
        best_title = ""

        for i, record in enumerate(videos):
            fields = record.get('fields', {})
            title = fields.get(self.TITLE_FIELD, "Unknown")
            ctr = fields.get(self.CTR_48H_FIELD) or fields.get(self.CTR_FIELD, 0)

            print(f"   [{i+1}/{len(videos)}] Analyzing: {title[:50]}... (CTR: {ctr:.1f}%)")

            if self.dry_run:
                print(f"      [DRY RUN] Would extract patterns")
                continue

            result = await self.analyze_video(record)
            if result:
                all_results.append(result)
                total_ctr += result.actual_ctr

                if result.actual_ctr > best_ctr:
                    best_ctr = result.actual_ctr
                    best_title = result.video_title

                # Write to memory files
                self.writer.process_result(result)

        # Update LEARNINGS.md summary
        if all_results and not self.dry_run:
            avg_ctr = total_ctr / len(all_results) if all_results else 0
            self.writer.update_learnings_summary(
                videos_produced=len(all_results),
                avg_ctr=avg_ctr,
                best_ctr=best_ctr,
                best_title=best_title,
            )
            print(f"\n✅ Bootstrap complete!")
            print(f"   Videos analyzed: {len(all_results)}")
            print(f"   Avg CTR: {avg_ctr:.1f}%")
            print(f"   Best CTR: {best_ctr:.1f}% (\"{best_title}\")")

        # Count total patterns extracted
        total_patterns = sum(len(r.learnings) for r in all_results)

        return {
            "videos_scanned": len(all_results),
            "patterns_extracted": total_patterns,
            "avg_ctr": total_ctr / len(all_results) if all_results else 0,
            "best_ctr": best_ctr,
            "best_title": best_title,
        }


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Bootstrap memory from historical videos")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to memory files")
    parser.add_argument("--scan-all", action="store_true", help="Scan all videos with CTR data")

    args = parser.parse_args()

    if not args.scan_all and not args.dry_run:
        parser.print_help()
        return

    bootstrapper = Bootstrapper(dry_run=args.dry_run)

    if args.scan_all or args.dry_run:
        asyncio.run(bootstrapper.scan_all())


if __name__ == "__main__":
    main()
