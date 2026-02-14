#!/usr/bin/env python3
"""
Research Intelligence Agent - Phase 2 Deep Dive Runner

Execute comprehensive research on a selected topic from Ideas Bank.

Usage:
    python -m research_agent.run_deep_dive                    # Deep dive on primary pick
    python -m research_agent.run_deep_dive --record-id recXXX # Deep dive on specific record
    python -m research_agent.run_deep_dive --dry-run          # Research only, no Airtable
"""

import os
import sys
import json
import asyncio
import argparse
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '..', '.env'))


async def run_deep_dive(
    record_id: str = None,
    write_to_airtable: bool = True,
    dry_run: bool = False,
) -> dict:
    """Execute Phase 2 deep dive on a topic.

    Args:
        record_id: Specific Airtable record ID to research (or None for primary pick)
        write_to_airtable: Whether to update Airtable with results
        dry_run: If True, print results but don't write anywhere

    Returns:
        Complete research brief dict
    """
    from research_agent.deep_diver import DeepDiver
    from research_agent.airtable_writer import ResearchAirtableWriter

    print("=" * 60)
    print("RESEARCH INTELLIGENCE AGENT - PHASE 2 DEEP DIVE")
    print(f"Started: {datetime.utcnow().isoformat()}")
    print("=" * 60)

    # Initialize Airtable client
    try:
        writer = ResearchAirtableWriter()
    except ValueError as e:
        print(f"\nERROR: {e}")
        return {"error": str(e)}

    # Get the topic to research
    if record_id:
        print(f"\n  Fetching record: {record_id}")
        # Fetch specific record
        import requests
        api_key = os.getenv("AIRTABLE_PAT") or os.getenv("AIRTABLE_API_KEY")
        base_id = os.getenv("AIRTABLE_BASE_ID", "appCIcC58YSTwK3CE")
        url = f"https://api.airtable.com/v0/{base_id}/Ideas%20Bank/{record_id}"
        headers = {"Authorization": f"Bearer {api_key}"}
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            print(f"  ERROR: Could not fetch record: {response.text}")
            return {"error": "Record not found"}
        topic = response.json().get("fields", {})
        topic["record_id"] = record_id
    else:
        print("\n  Finding primary pick (status=selected)...")
        records = writer.get_ideas_by_status("selected", max_records=1)
        if not records:
            print("  No selected topics found. Run Phase 1 first.")
            return {"error": "No selected topics"}
        topic = records[0].get("fields", records[0])
        record_id = records[0].get("id")
        topic["record_id"] = record_id

    print(f"\n  Topic: {topic.get('Headline', topic.get('headline', ''))[:60]}...")
    print(f"  Record ID: {record_id}")

    # Initialize deep diver
    try:
        diver = DeepDiver()
    except ValueError as e:
        print(f"\nERROR: {e}")
        return {"error": str(e)}

    # Run the deep dive
    brief = await diver.run_deep_dive(topic)

    # Print results
    print("\n" + "=" * 60)
    print("DEEP DIVE RESULTS")
    print("=" * 60)

    print(f"\n--- EXECUTIVE HOOK ---")
    print(brief.executive_hook[:500] if brief.executive_hook else "(not generated)")

    print(f"\n--- THESIS ---")
    print(brief.thesis if brief.thesis else "(not generated)")

    print(f"\n--- TITLE OPTIONS ---")
    print(brief.title_options[:500] if brief.title_options else "(not generated)")

    print(f"\n--- FACT SHEET (excerpt) ---")
    print(brief.fact_sheet[:800] + "..." if brief.fact_sheet else "(not generated)")

    print(f"\n--- HISTORICAL PARALLELS (excerpt) ---")
    print(brief.historical_parallels[:500] + "..." if brief.historical_parallels else "(not generated)")

    print(f"\n--- FRAMEWORK ANALYSIS (excerpt) ---")
    print(brief.framework_analysis[:500] + "..." if brief.framework_analysis else "(not generated)")

    print(f"\n--- NARRATIVE ARC (excerpt) ---")
    print(brief.narrative_arc[:500] + "..." if brief.narrative_arc else "(not generated)")

    print(f"\n--- VISUAL SEEDS ---")
    print(brief.visual_seeds[:500] if brief.visual_seeds else "(not generated)")

    print(f"\n--- STATS ---")
    print(f"  Duration: {brief.research_duration_sec:.1f} seconds")
    print(f"  Sources: {brief.total_sources_used}")

    # Dry run
    if dry_run:
        print("\n[DRY RUN] Results not written to Airtable")
        return brief.to_dict()

    # Write to Airtable
    if write_to_airtable and record_id:
        print("\n" + "=" * 60)
        print("UPDATING AIRTABLE")
        print("=" * 60)

        try:
            writer.update_with_deep_dive(record_id, brief.to_dict())
            print(f"  [OK] Updated record {record_id} with deep dive results")
            print(f"  [OK] Status changed to 'researched'")
        except Exception as e:
            print(f"  [FAIL] Could not update Airtable: {e}")

    print("\n" + "=" * 60)
    print(f"PHASE 2 COMPLETE - {datetime.utcnow().isoformat()}")
    print("=" * 60)

    return brief.to_dict()


def main():
    """Main entry point for command line usage."""
    parser = argparse.ArgumentParser(
        description="Research Intelligence Agent - Phase 2 Deep Dive"
    )
    parser.add_argument(
        "--record-id",
        type=str,
        help="Specific Airtable record ID to research",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print results only, no Airtable write",
    )

    args = parser.parse_args()

    result = asyncio.run(run_deep_dive(
        record_id=args.record_id,
        write_to_airtable=not args.dry_run,
        dry_run=args.dry_run,
    ))

    if result.get("error"):
        sys.exit(1)


if __name__ == "__main__":
    main()
