#!/usr/bin/env python3
# skills/video-pipeline/curiosity_gap/seed_patterns.py
"""Seed the pattern library with competitor analysis.

This script analyzes existing competitor videos in Airtable and populates
the curiosity gap pattern library. Run this BEFORE using the title generator.

Usage:
    python -m curiosity_gap.seed_patterns --dry-run   # Preview only
    python -m curiosity_gap.seed_patterns             # Analyze and save
    python -m curiosity_gap.seed_patterns --limit 10  # Limit to N videos
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from curiosity_gap.competitor_analyzer import CompetitorAnalyzer, should_deep_analyze
from curiosity_gap.structures import CuriosityStructure
from clients.airtable_client import AirtableClient
from pipeline_constants import CompetitorVideoFields, CURIOSITY_GAP_ENABLED


async def seed_patterns(
    dry_run: bool = False,
    limit: int = 50,
    min_vph: float = 50,
) -> Dict:
    """Analyze competitor videos and seed pattern library.

    Args:
        dry_run: If True, don't write to Airtable or memory files
        limit: Maximum videos to analyze
        min_vph: Minimum VPH threshold

    Returns:
        Summary dict with counts
    """
    # Kill switch - instant rollback mechanism
    if not CURIOSITY_GAP_ENABLED:
        print("Curiosity gap system is DISABLED (CURIOSITY_GAP_ENABLED=False)")
        print("   Set CURIOSITY_GAP_ENABLED=True in pipeline_constants.py to enable")
        return {"analyzed": 0, "errors": 0, "disabled": True}

    print(f"Seeding curiosity gap patterns...")
    print(f"   Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"   Limit: {limit} videos, min VPH: {min_vph}")
    print()

    airtable = AirtableClient()
    analyzer = CompetitorAnalyzer()

    # Get unanalyzed videos (sync call - AirtableClient uses pyairtable which is sync)
    print("Fetching unanalyzed competitor videos...")
    videos = airtable.get_unanalyzed_competitor_videos(
        min_vph=min_vph,
        limit=limit,
    )
    print(f"   Found {len(videos)} videos to analyze")

    if not videos:
        print("   No videos to analyze. Run competitor scraper first.")
        return {"analyzed": 0, "errors": 0}

    # Track results
    results = {
        "analyzed": 0,
        "deep_analyzed": 0,
        "errors": 0,
        "by_structure": {},
    }

    for structure in CuriosityStructure:
        results["by_structure"][structure.value] = 0

    # Analyze each video
    for i, record in enumerate(videos, 1):
        fields = record.get("fields", {})
        title = fields.get(CompetitorVideoFields.TITLE, "")
        vph = fields.get(CompetitorVideoFields.VPH, 0)
        video_id = fields.get(CompetitorVideoFields.VIDEO_ID, "")
        channel = fields.get(CompetitorVideoFields.CHANNEL, "unknown")

        print(f"\n[{i}/{len(videos)}] {title[:50]}...")
        print(f"   Channel: {channel}, VPH: {vph:.0f}")

        try:
            # Phase 1: Title analysis
            title_analysis = await analyzer.analyze_title(title)
            print(f"   Structure: {title_analysis.structure.value} ({title_analysis.confidence}%)")

            results["by_structure"][title_analysis.structure.value] += 1

            # Check if qualifies for Phase 2
            deep_analyze = await should_deep_analyze(vph, channel)
            thumbnail_analysis = None

            if deep_analyze and video_id:
                print(f"   Top 20% - running thumbnail analysis...")
                thumbnail_analysis = await analyzer.analyze_thumbnail(video_id, title)
                if thumbnail_analysis:
                    print(f"   Thumbnail: {thumbnail_analysis.text_extracted or 'no text'}")
                    print(f"   Yin/Yang: {thumbnail_analysis.yin_yang_approach}")
                    results["deep_analyzed"] += 1

            # Save to Airtable (sync call - AirtableClient uses pyairtable which is sync)
            if not dry_run:
                airtable.update_competitor_curiosity_analysis(
                    record_id=record["id"],
                    structure=title_analysis.structure.value,
                    structure_confidence=title_analysis.confidence,
                    thumbnail_style_json=json.dumps({
                        "colors": thumbnail_analysis.colors if thumbnail_analysis else [],
                        "composition": thumbnail_analysis.composition if thumbnail_analysis else "",
                    }) if thumbnail_analysis else None,
                    yin_yang_approach=thumbnail_analysis.yin_yang_approach if thumbnail_analysis else None,
                    yin_yang_text=thumbnail_analysis.text_extracted if thumbnail_analysis else None,
                )
                print(f"   Saved to Airtable")
            else:
                print(f"   (dry run - not saved)")

            results["analyzed"] += 1

        except Exception as e:
            print(f"   Error: {e}")
            results["errors"] += 1

        # Rate limiting
        await asyncio.sleep(0.5)

    # Update memory file
    if not dry_run and results["analyzed"] > 0:
        await update_memory_file(results)

    # Summary
    print("\n" + "=" * 50)
    print("SEEDING COMPLETE")
    print("=" * 50)
    print(f"Analyzed: {results['analyzed']} videos")
    print(f"Deep analyzed (thumbnails): {results['deep_analyzed']}")
    print(f"Errors: {results['errors']}")
    print("\nBy structure:")
    for structure, count in results["by_structure"].items():
        if count > 0:
            print(f"  {structure}: {count}")

    return results


async def update_memory_file(results: Dict) -> None:
    """Update competitor_patterns.md with analysis results.

    Args:
        results: Results dict from seed_patterns
    """
    import re

    memory_path = Path(__file__).parent.parent / "autopilot" / "memory" / "competitor_patterns.md"

    # Read existing content
    if memory_path.exists():
        content = memory_path.read_text()
    else:
        content = "# Competitor Patterns\n\n"

    # Update header - use separate if statements so both can match
    lines = content.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("Last updated:"):
            lines[i] = f"Last updated: {datetime.now().strftime('%Y-%m-%d')}"
        if line.startswith("Videos analyzed:"):
            # Extract current count and add
            match = re.search(r'\d+', line)
            current = int(match.group()) if match else 0
            lines[i] = f"Videos analyzed: {current + results['analyzed']}"

    memory_path.write_text("\n".join(lines))
    print(f"\nUpdated {memory_path}")


def main():
    parser = argparse.ArgumentParser(description="Seed curiosity gap pattern library")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, don't save")
    parser.add_argument("--limit", type=int, default=50, help="Max videos to analyze")
    parser.add_argument("--min-vph", type=float, default=50, help="Minimum VPH threshold")

    args = parser.parse_args()

    asyncio.run(seed_patterns(
        dry_run=args.dry_run,
        limit=args.limit,
        min_vph=args.min_vph,
    ))


if __name__ == "__main__":
    main()
