#!/usr/bin/env python3
"""
Research Intelligence Agent - Phase 1 Runner

Execute broad environmental scan and write results to Airtable.

Usage:
    python -m research_agent.run_scan              # Full scan + Airtable write
    python -m research_agent.run_scan --scan-only  # Scan only, no Airtable
    python -m research_agent.run_scan --dry-run    # Print results, no Airtable
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


async def run_phase1(
    write_to_airtable: bool = True,
    dry_run: bool = False,
    trigger_type: str = "manual_api",
) -> dict:
    """Execute Phase 1: Broad Scan + Scoring + Airtable Write.

    Args:
        write_to_airtable: Whether to write results to Airtable
        dry_run: If True, print results but don't write anywhere
        trigger_type: "cron", "manual_slash", or "manual_api"

    Returns:
        Complete scan results dict
    """
    from research_agent.scanner import ResearchScanner
    from research_agent.airtable_writer import ResearchAirtableWriter

    print("=" * 60)
    print("RESEARCH INTELLIGENCE AGENT - PHASE 1")
    print(f"Started: {datetime.utcnow().isoformat()}")
    print("=" * 60)

    # Initialize scanner
    try:
        scanner = ResearchScanner()
    except ValueError as e:
        print(f"\nERROR: {e}")
        print("\nMake sure you have these environment variables set:")
        print("  - TAVILY_API_KEY")
        print("  - ANTHROPIC_API_KEY")
        return {"error": str(e)}

    # Run the scan
    scan_result = await scanner.run_full_phase1()

    # Print summary
    print("\n" + "=" * 60)
    print("SCAN RESULTS SUMMARY")
    print("=" * 60)

    metadata = scan_result.get("scan_metadata", {})
    print(f"Duration: {metadata.get('duration_sec', 0)} seconds")
    print(f"Total candidates: {metadata.get('candidates_generated', 0)}")
    print(f"Categories scanned: {', '.join(metadata.get('categories_scanned', []))}")

    # Print top candidates
    print("\n--- TOP CANDIDATES ---")
    for i, candidate in enumerate(scan_result.get("all_candidates", [])[:5], 1):
        rec = candidate.get("selection_recommendation", "backlog")
        score = candidate.get("composite_score", 0)
        headline = candidate.get("headline", "")[:60]
        kill_flags = candidate.get("kill_flags", [])

        status_icon = {"primary": "***", "secondary": "**", "backlog": "", "reject": "[X]"}.get(rec, "")
        flags_str = f" KILL: {kill_flags}" if kill_flags else ""

        print(f"  {i}. {status_icon} [{score:.1f}] {headline}{flags_str}")

    # Print primary pick details
    primary = scan_result.get("primary_pick")
    if primary:
        print("\n--- PRIMARY PICK (for deep dive) ---")
        print(f"  Headline: {primary.get('headline', '')}")
        print(f"  Category: {primary.get('source_category', '')}")
        print(f"  Composite Score: {primary.get('composite_score', 0):.2f}")
        print(f"    - Timeliness: {primary.get('timeliness_score', 0)}/10")
        print(f"    - Audience Fit: {primary.get('audience_fit_score', 0)}/10")
        print(f"    - Content Gap: {primary.get('content_gap_score', 0)}/10")
        print(f"  Framework: {primary.get('framework_hint', '')}")
        print(f"  Sources: {', '.join(primary.get('source_urls', []))[:100]}")
        if primary.get("reasoning"):
            print(f"  Reasoning: {primary.get('reasoning', '')[:200]}")

    # Print secondary pick
    secondary = scan_result.get("secondary_pick")
    if secondary:
        print("\n--- SECONDARY PICK (backup) ---")
        print(f"  Headline: {secondary.get('headline', '')}")
        print(f"  Score: {secondary.get('composite_score', 0):.2f}")

    # Dry run - just print
    if dry_run:
        print("\n[DRY RUN] Results not written to Airtable")
        print("\nFull JSON output:")
        print(json.dumps(scan_result, indent=2, default=str))
        return scan_result

    # Write to Airtable
    if write_to_airtable:
        print("\n" + "=" * 60)
        print("WRITING TO AIRTABLE")
        print("=" * 60)

        try:
            writer = ResearchAirtableWriter()
            write_result = writer.write_scan_results(
                scan_result=scan_result,
                trigger_type=trigger_type,
            )
            print(f"\nScan record ID: {write_result['scan_record_id']}")
            print(f"Ideas created: {len(write_result['idea_record_ids'])}")
            if write_result.get('primary_pick_id'):
                print(f"Primary pick ID: {write_result['primary_pick_id']}")
            if write_result.get('secondary_pick_id'):
                print(f"Secondary pick ID: {write_result['secondary_pick_id']}")

            scan_result["airtable_result"] = write_result
        except ValueError as e:
            print(f"\nERROR connecting to Airtable: {e}")
            print("\nMake sure you have these environment variables set:")
            print("  - AIRTABLE_API_KEY")
            print("\nAnd that you've created the required tables. Run:")
            print("  from research_agent.airtable_writer import create_tables_instructions")
            print("  print(create_tables_instructions())")
        except Exception as e:
            print(f"\nERROR writing to Airtable: {e}")
            print("\nThis might mean the tables don't exist yet.")
            print("See airtable_writer.py for table creation instructions.")

    print("\n" + "=" * 60)
    print(f"PHASE 1 COMPLETE - {datetime.utcnow().isoformat()}")
    print("=" * 60)

    return scan_result


def main():
    """Main entry point for command line usage."""
    parser = argparse.ArgumentParser(
        description="Research Intelligence Agent - Phase 1 Scanner"
    )
    parser.add_argument(
        "--scan-only",
        action="store_true",
        help="Run scan but don't write to Airtable",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print results only, no Airtable write",
    )
    parser.add_argument(
        "--trigger",
        choices=["cron", "manual_slash", "manual_api"],
        default="manual_api",
        help="Trigger type for logging",
    )

    args = parser.parse_args()

    result = asyncio.run(run_phase1(
        write_to_airtable=not args.scan_only,
        dry_run=args.dry_run,
        trigger_type=args.trigger,
    ))

    # Exit with error code if scan failed
    if result.get("error"):
        sys.exit(1)


if __name__ == "__main__":
    main()
