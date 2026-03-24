"""
Run the Competitor Scraper to find winning videos and generate ideas.

Scrapes competitor YouTube channels, identifies winners by VPH (views per hour),
and generates Power Doctrine angle ideas from proven topics.

Usage:
    python run_competitor_scraper.py
    python run_competitor_scraper.py --threshold 100
    python run_competitor_scraper.py --ideas 5
    python run_competitor_scraper.py --dry-run
"""

import os
import sys
import asyncio
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

from shared.clients.apify_client import ApifyYouTubeClient
from shared.clients.anthropic_client import AnthropicClient
from shared.clients.airtable_client import AirtableClient
from shared.clients.slack_client import SlackClient
from competitor_scraper.scraper import CompetitorScraper


async def main():
    parser = argparse.ArgumentParser(
        description="Scrape competitor channels and generate ideas"
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="Minimum VPH (views per hour) to qualify as a winner (default: 50)",
    )
    parser.add_argument(
        "--ideas",
        type=int,
        default=3,
        help="Number of ideas to generate (default: 3)",
    )
    parser.add_argument(
        "--videos-per-channel",
        type=int,
        default=10,
        help="Max videos to scrape per channel (default: 10)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape and analyze only, don't save to Airtable or notify Slack",
    )
    parser.add_argument(
        "--no-slack",
        action="store_true",
        help="Skip Slack notification",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("COMPETITOR CHANNEL SCRAPER")
    print("=" * 60)

    # Initialize clients
    try:
        apify = ApifyYouTubeClient()
    except ValueError as e:
        print(f"ERROR: {e}")
        print("Add APIFY_API_KEY to your .env file")
        sys.exit(1)

    anthropic = AnthropicClient()
    airtable = AirtableClient()

    slack = None
    if not args.no_slack and not args.dry_run:
        try:
            slack = SlackClient()
        except ValueError:
            print("Note: Slack notifications disabled (no SLACK_BOT_TOKEN)")

    # Run scraper
    scraper = CompetitorScraper(
        apify_client=apify,
        anthropic_client=anthropic,
        airtable_client=airtable,
        slack_client=slack,
    )

    try:
        result = await scraper.run(
            max_videos_per_channel=args.videos_per_channel,
            vph_threshold=args.threshold,
            num_ideas=args.ideas,
            save_to_airtable=not args.dry_run,
            notify_slack=not args.dry_run and not args.no_slack,
        )

        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"  Videos scraped: {result['videos_scraped']}")
        print(f"  Winners found: {len(result['winners'])}")
        print(f"  Ideas generated: {len(result['ideas'])}")
        if args.dry_run:
            print("  (dry-run mode — nothing saved)")

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
