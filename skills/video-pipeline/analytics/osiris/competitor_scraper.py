"""
Osiris Competitor Scraper - Scrapes and persists ALL competitor videos.

Unlike discovery_scanner which only processes "winners" (high VPH videos),
Osiris persists EVERY scraped video to build training data over time.

After 3 months of daily scrapes, you'll have thousands of data points showing:
- Which topics consistently get high VPH
- Which channels are outperforming
- Seasonal patterns in topic performance

Usage:
    python -m osiris.competitor_scraper
    python -m osiris.competitor_scraper --dry-run

Cron (5 AM PT):
    0 5 * * * cd $PROJECT && python -m osiris.competitor_scraper
"""

import asyncio
import logging
import sys
from datetime import date
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Reuse existing VPH calculation
from competitor_scraper.scraper import calculate_vph


class OsirisCompetitorScraper:
    """Scrapes competitor channels and persists ALL videos to Airtable.

    This is the data collection layer for Osiris. Every video scraped
    gets saved to the Competitor Videos table, not just winners.

    Usage:
        scraper = OsirisCompetitorScraper(apify_client, airtable_client)
        result = await scraper.scrape_and_persist()
        print(f"Saved {result['new_videos_saved']} new videos")
    """

    def __init__(
        self,
        apify_client,
        airtable_client,
        slack_client=None,
        max_videos_per_channel: int = 20,
    ):
        """Initialize the Osiris scraper.

        Args:
            apify_client: ApifyYouTubeClient instance for scraping
            airtable_client: AirtableClient instance for persistence
            slack_client: Optional SlackClient for notifications
            max_videos_per_channel: Videos to fetch per channel (default 20)
        """
        self.apify = apify_client
        self.airtable = airtable_client
        self.slack = slack_client
        self.max_videos_per_channel = max_videos_per_channel

    async def scrape_and_persist(
        self,
        dry_run: bool = False,
    ) -> dict:
        """Full pipeline: scrape all channels -> dedupe -> persist.

        Args:
            dry_run: If True, prints what would be saved without writing

        Returns:
            {
                "channels_scraped": int,
                "videos_scraped": int,
                "new_videos_saved": int,
                "duplicates_skipped": int,
                "errors": list[str],
            }
        """
        result = {
            "channels_scraped": 0,
            "videos_scraped": 0,
            "new_videos_saved": 0,
            "duplicates_skipped": 0,
            "errors": [],
        }

        # Step 1: Get active channels
        logger.info("Fetching active competitor channels...")
        try:
            channels = self.airtable.get_active_competitor_channels()
        except Exception as e:
            error = f"Failed to fetch channels: {e}"
            logger.error(error)
            result["errors"].append(error)
            return result

        if not channels:
            logger.info("No active competitor channels found")
            return result

        channel_urls = [
            c.get("Channel URL") for c in channels if c.get("Channel URL")
        ]
        result["channels_scraped"] = len(channel_urls)
        logger.info(f"Found {len(channel_urls)} active channels to scrape")

        # Step 2: Scrape videos via Apify
        logger.info("Scraping videos via Apify...")
        try:
            videos = await self.apify.scrape_channel_videos(
                channel_urls=channel_urls,
                max_videos_per_channel=self.max_videos_per_channel,
            )
        except Exception as e:
            error = f"Apify scrape failed: {e}"
            logger.error(error)
            result["errors"].append(error)
            return result

        result["videos_scraped"] = len(videos)
        logger.info(f"Scraped {len(videos)} videos")

        if not videos:
            return result

        # Step 3: Calculate VPH for each video
        logger.info("Calculating VPH metrics...")
        for video in videos:
            vph, hours_old = calculate_vph(
                video.get("views", 0),
                video.get("published_at", ""),
            )
            video["vph"] = round(vph, 1)
            video["hours_old"] = round(hours_old, 1)

        # Step 4: Get existing video IDs for deduplication
        logger.info("Fetching existing video IDs for deduplication...")
        existing_ids = await self._get_existing_video_ids()
        logger.info(f"Found {len(existing_ids)} existing videos in table")

        # Step 5: Filter to new videos only
        new_videos = [
            v for v in videos
            if v.get("video_id") and v.get("video_id") not in existing_ids
        ]
        result["duplicates_skipped"] = len(videos) - len(new_videos)
        logger.info(
            f"New videos: {len(new_videos)}, duplicates: {result['duplicates_skipped']}"
        )

        if not new_videos:
            logger.info("No new videos to save")
            return result

        # Step 6: Persist new videos
        if dry_run:
            logger.info(f"DRY RUN: Would save {len(new_videos)} videos:")
            for v in new_videos[:10]:  # Show first 10
                logger.info(
                    f"  - {v.get('title', '?')[:50]} | {v.get('channel', '?')} | "
                    f"{v.get('views', 0):,} views | {v.get('vph', 0):.0f} VPH"
                )
            if len(new_videos) > 10:
                logger.info(f"  ... and {len(new_videos) - 10} more")
            result["new_videos_saved"] = len(new_videos)
        else:
            logger.info(f"Persisting {len(new_videos)} new videos...")
            saved, failed = await self._persist_videos(new_videos)
            result["new_videos_saved"] = saved
            if failed:
                result["errors"].append(f"{failed} videos failed to save")
            logger.info(f"Saved {saved} videos, {failed} failed")

        # Step 7: Update Last Scraped on channels
        if not dry_run:
            for channel in channels:
                try:
                    self.airtable.update_channel_last_scraped(channel["id"])
                except Exception as e:
                    logger.warning(
                        f"Failed to update Last Scraped for {channel.get('Channel Name')}: {e}"
                    )

        # Step 8: Send Slack notification (non-blocking)
        if self.slack and not dry_run:
            try:
                self._send_summary_notification(result)
            except Exception as e:
                logger.warning(f"Slack notification failed: {e}")

        return result

    async def _get_existing_video_ids(self) -> set[str]:
        """Fetch all existing video_ids from Competitor Videos table."""
        # Run sync method in executor to avoid blocking
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.airtable.get_all_competitor_video_ids,
        )

    async def _persist_videos(self, videos: list[dict]) -> tuple[int, int]:
        """Persist new videos to Airtable.

        Returns:
            (saved_count, failed_count)
        """
        loop = asyncio.get_event_loop()

        try:
            # Use batch create for efficiency
            created = await loop.run_in_executor(
                None,
                self.airtable.batch_create_competitor_videos,
                videos,
            )
            return len(created), 0
        except Exception as e:
            logger.error(f"Batch create failed: {e}")
            # Fallback to individual creates
            saved = 0
            failed = 0
            for video in videos:
                try:
                    await loop.run_in_executor(
                        None,
                        self.airtable.create_competitor_video,
                        video,
                    )
                    saved += 1
                except Exception as ind_err:
                    logger.warning(f"Failed to save {video.get('video_id')}: {ind_err}")
                    failed += 1
            return saved, failed

    def _send_summary_notification(self, result: dict):
        """Send Slack summary of the scrape."""
        msg = (
            f"*Osiris Competitor Scrape Complete*\n"
            f"Channels: {result['channels_scraped']}\n"
            f"Videos scraped: {result['videos_scraped']}\n"
            f"New saved: {result['new_videos_saved']}\n"
            f"Duplicates skipped: {result['duplicates_skipped']}"
        )
        if result["errors"]:
            msg += f"\nErrors: {len(result['errors'])}"

        self.slack.send_message(msg)


async def run_osiris_scraper(
    apify_client=None,
    airtable_client=None,
    slack_client=None,
    dry_run: bool = False,
    max_videos_per_channel: int = 20,
) -> dict:
    """Convenience function to run the Osiris competitor scraper.

    Creates clients if not provided, runs the full scrape pipeline.

    Args:
        apify_client: Optional ApifyYouTubeClient (created if None)
        airtable_client: Optional AirtableClient (created if None)
        slack_client: Optional SlackClient (created if None)
        dry_run: If True, prints without saving
        max_videos_per_channel: Videos per channel (default 20)

    Returns:
        Result dict with scrape statistics
    """
    # Create clients if not provided
    if apify_client is None:
        from shared.clients.apify_client import ApifyYouTubeClient
        apify_client = ApifyYouTubeClient()

    if airtable_client is None:
        from shared.clients.airtable_client import AirtableClient
        airtable_client = AirtableClient()

    if slack_client is None and not dry_run:
        try:
            from shared.clients.slack_client import SlackClient
            slack_client = SlackClient()
        except Exception:
            slack_client = None

    scraper = OsirisCompetitorScraper(
        apify_client=apify_client,
        airtable_client=airtable_client,
        slack_client=slack_client,
        max_videos_per_channel=max_videos_per_channel,
    )

    return await scraper.scrape_and_persist(dry_run=dry_run)


async def _cli_main():
    """CLI entry point for `python -m osiris.competitor_scraper`."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Osiris Competitor Scraper - Scrape and persist competitor videos"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be saved without writing to Airtable",
    )
    parser.add_argument(
        "--max-videos",
        type=int,
        default=20,
        help="Max videos per channel (default: 20)",
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
    print("OSIRIS COMPETITOR SCRAPER")
    print("=" * 60)
    print(f"  Date: {date.today().isoformat()}")
    print(f"  Dry run: {args.dry_run}")
    print(f"  Max videos/channel: {args.max_videos}")
    print("=" * 60)
    print()

    result = await run_osiris_scraper(
        dry_run=args.dry_run,
        max_videos_per_channel=args.max_videos,
    )

    print()
    print("=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"  Channels scraped:    {result['channels_scraped']}")
    print(f"  Videos scraped:      {result['videos_scraped']}")
    print(f"  New videos saved:    {result['new_videos_saved']}")
    print(f"  Duplicates skipped:  {result['duplicates_skipped']}")

    if result["errors"]:
        print(f"  Errors:              {len(result['errors'])}")
        for err in result["errors"]:
            print(f"    - {err}")

    print("=" * 60)

    # Exit with error code if there were errors
    if result["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(_cli_main())
