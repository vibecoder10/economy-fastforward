"""
CompetitorScraper - Scrapes competitor YouTube channels and generates ideas.

Pipeline:
1. Read active channels from Airtable "Competitor Channels" table
2. Scrape recent videos via Apify (scrape_channel_videos)
3. Calculate VPH (views per hour) for each video
4. Filter to top winners (VPH > threshold)
5. Generate Power Doctrine angle ideas using Claude
6. Save ideas to Airtable Idea Concepts table
7. Notify Slack with results
"""

import json
import re
from datetime import datetime, timezone
from typing import Optional
from pipeline_constants import Models


def calculate_vph(views: int, published_at: str) -> tuple[float, float]:
    """Calculate views per hour since upload.

    Args:
        views: Current view count
        published_at: ISO format publish date string

    Returns:
        Tuple of (vph, hours_since_upload), or (0.0, 0.0) if date parsing fails
    """
    if not published_at:
        return 0.0, 0.0

    try:
        # Handle various date formats from Apify
        if "T" in published_at:
            # ISO format: 2024-03-10T15:30:00Z or 2024-03-10T15:30:00+00:00
            published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        else:
            # Date-only strings: 2024-03-10
            published = datetime.strptime(published_at, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )

        now = datetime.now(timezone.utc)
        hours_since = (now - published).total_seconds() / 3600

        if hours_since <= 0:
            return 0.0, 0.0

        return views / hours_since, hours_since
    except (ValueError, TypeError):
        return 0.0, 0.0


class CompetitorScraper:
    """Scrapes competitor channels and generates Power Doctrine ideas."""

    # VPH threshold for "winner" classification
    # 50 VPH = 1,200 views in first 24 hours (modest performer)
    # 500 VPH = 12,000 views in first 24 hours (strong performer)
    DEFAULT_VPH_THRESHOLD = 50

    # Max age in hours for videos to consider
    MAX_AGE_HOURS = 168  # 7 days

    def __init__(
        self,
        apify_client,
        anthropic_client,
        airtable_client,
        slack_client=None,
    ):
        """Initialize with required clients.

        Args:
            apify_client: ApifyYouTubeClient for channel scraping
            anthropic_client: AnthropicClient for idea generation
            airtable_client: AirtableClient for reading channels / saving ideas
            slack_client: Optional SlackClient for notifications
        """
        self.apify = apify_client
        self.anthropic = anthropic_client
        self.airtable = airtable_client
        self.slack = slack_client

    async def scrape_channels(
        self,
        max_videos_per_channel: int = 10,
    ) -> list[dict]:
        """Scrape videos from all active competitor channels.

        Returns:
            List of video dicts with VPH calculated
        """
        # Get active channels from Airtable
        channels = self.airtable.get_active_competitor_channels()

        if not channels:
            print("  No active competitor channels found in Airtable")
            return []

        channel_urls = [
            c.get("Channel URL") for c in channels if c.get("Channel URL")
        ]

        print(f"\n  Scraping {len(channel_urls)} competitor channels...")
        for url in channel_urls:
            print(f"    - {url}")

        # Use existing Apify client method
        videos = await self.apify.scrape_channel_videos(
            channel_urls=channel_urls,
            max_videos_per_channel=max_videos_per_channel,
        )

        # Calculate VPH for each video
        for video in videos:
            vph, hours_old = calculate_vph(
                video.get("views", 0),
                video.get("published_at", ""),
            )
            video["vph"] = round(vph, 1)
            video["hours_old"] = round(hours_old, 1)

        # Update last scraped timestamps
        for channel in channels:
            try:
                self.airtable.update_channel_last_scraped(channel["id"])
            except Exception as e:
                print(
                    f"    Warning: Could not update Last Scraped for "
                    f"{channel.get('Channel Name')}: {e}"
                )

        return videos

    def filter_winners(
        self,
        videos: list[dict],
        vph_threshold: float = None,
        max_age_hours: float = None,
    ) -> list[dict]:
        """Filter videos to top performers by VPH.

        Args:
            videos: List of video dicts with 'vph' calculated
            vph_threshold: Minimum VPH to be considered a winner
            max_age_hours: Maximum age in hours to consider

        Returns:
            Filtered and sorted list of winner videos
        """
        threshold = vph_threshold or self.DEFAULT_VPH_THRESHOLD
        max_age = max_age_hours or self.MAX_AGE_HOURS

        winners = []

        for video in videos:
            # Check VPH threshold
            if video.get("vph", 0) < threshold:
                continue

            # Check age
            hours_old = video.get("hours_old", 0)
            if hours_old > max_age:
                continue

            winners.append(video)

        # Sort by VPH descending
        winners.sort(key=lambda v: v.get("vph", 0), reverse=True)

        return winners

    async def generate_ideas_from_winners(
        self,
        winners: list[dict],
        num_ideas: int = 3,
    ) -> list[dict]:
        """Generate Power Doctrine angle ideas from winning videos.

        Args:
            winners: List of high-VPH videos
            num_ideas: Number of ideas to generate

        Returns:
            List of idea dicts ready for Airtable
        """
        if not winners:
            print("  No winners to generate ideas from")
            return []

        print(f"\n  Generating {num_ideas} ideas from {len(winners)} winners...")

        # Build context from winners
        winners_context = "\n".join(
            f"- \"{v.get('title', '')}\" ({v.get('views', 0):,} views, "
            f"{v.get('vph', 0):.0f} VPH) - {v.get('channel', '')}"
            for v in winners[:10]  # Limit context to top 10
        )

        system_prompt = """You are the Editorial Director for Economy FastForward, a documentary-style YouTube channel covering geopolitics, finance, and economics through a Machiavellian/power dynamics lens.

Your audience wants to see what's BEHIND the news — the power dynamics, hidden systems, historical cycles, and strategic maneuvers that shape the world.

CHANNEL STYLE:
- Past -> Present -> Future narrative structure
- Dramatic, urgent, predictive documentary tone
- Topics: Economy, finance, AI/tech, macroeconomics, geopolitics
- Visual style: Cinematic photorealistic documentary

TITLE RULES:
- Direct and specific — tell the viewer exactly what they'll learn
- Use numbers, years, or dollar amounts when relevant
- ALL CAPS for 1-2 words max (COLLAPSE, EXPOSED, WARNING)
- Future dates perform well (2025, 2026, 2030)
- Model CaspianReport/AiTelly style: "How [Entity] [Action] [Target]"

OUTPUT FORMAT:
Return a JSON object with a "concepts" array:
{
  "concepts": [
    {
      "viral_title": "The actual YouTube title",
      "source_title": "The EXACT competitor title that inspired this",
      "source_channel": "Channel name",
      "power_doctrine_angle": "The Machiavellian/power dynamics framing",
      "thumbnail_visual": "Thumbnail concept (2-word verdict style)",
      "hook_script": "First 15 seconds of the video",
      "narrative_logic": {
        "past_context": "Historical parallel or precedent",
        "present_parallel": "Current situation being analyzed",
        "future_prediction": "Where this leads"
      },
      "writer_guidance": "Key angles for the scriptwriter"
    }
  ]
}"""

        user_prompt = f"""Analyze these TOP PERFORMING competitor videos and generate {num_ideas} ORIGINAL Economy FastForward video concepts:

## HIGH-VELOCITY WINNERS (sorted by views per hour):
{winners_context}

---

Create {num_ideas} concepts that:
1. Take a DIFFERENT ANGLE on similar topics (don't copy titles)
2. Apply the Power Doctrine lens (who gains power, who loses, what's the hidden mechanism)
3. Connect to historical parallels
4. Project into the future

Return ONLY the JSON object."""

        response = await self.anthropic.generate(
            prompt=user_prompt,
            system_prompt=system_prompt,
            model=Models.CLAUDE_SONNET,
        )

        # Parse response (following existing JSON parsing pattern)
        clean_response = response.replace("```json", "").replace("```", "").strip()

        try:
            data = json.loads(clean_response)
        except json.JSONDecodeError:
            # Try extracting JSON from response
            json_match = re.search(r"\{.*\}", clean_response, re.DOTALL)
            if json_match:
                try:
                    data = json.loads(json_match.group())
                except json.JSONDecodeError:
                    print("  Failed to parse JSON response")
                    return []
            else:
                print("  Failed to parse JSON response")
                return []

        ideas = data.get("concepts", [])

        # Enrich with source attribution
        for idea in ideas:
            idea["original_dna"] = json.dumps(
                {
                    "source": "competitor_scraper",
                    "winners_analyzed": len(winners),
                    "top_winner": winners[0].get("title") if winners else None,
                }
            )

            # Find matching source video
            source_title = idea.get("source_title", "")
            for winner in winners:
                winner_title = winner.get("title", "")
                if source_title and (
                    source_title.lower() in winner_title.lower()
                    or winner_title.lower() in source_title.lower()
                ):
                    idea["reference_url"] = winner.get("url", "")
                    idea["source_views"] = winner.get("views", 0)
                    idea["source_channel"] = winner.get("channel", "")
                    idea["source_vph"] = winner.get("vph", 0)
                    break

        return ideas

    async def run(
        self,
        max_videos_per_channel: int = 10,
        vph_threshold: float = None,
        num_ideas: int = 3,
        save_to_airtable: bool = True,
        notify_slack: bool = True,
    ) -> dict:
        """Full pipeline: scrape -> filter -> generate -> save -> notify.

        Args:
            max_videos_per_channel: Videos to scrape per channel
            vph_threshold: Minimum VPH for winners
            num_ideas: Ideas to generate
            save_to_airtable: Whether to save ideas
            notify_slack: Whether to notify Slack

        Returns:
            Dict with scrape_results, winners, and ideas
        """
        print("\n" + "=" * 60)
        print("COMPETITOR CHANNEL SCRAPER")
        print("=" * 60)

        try:
            return await self._run_pipeline(
                max_videos_per_channel=max_videos_per_channel,
                vph_threshold=vph_threshold,
                num_ideas=num_ideas,
                save_to_airtable=save_to_airtable,
                notify_slack=notify_slack,
            )
        except Exception as e:
            error_msg = f"Competitor scraper failed: {e}"
            print(f"\n  ERROR: {error_msg}")
            # Send error notification to Slack (non-blocking)
            if self.slack:
                try:
                    self.slack.notify(f":x: *Competitor Scraper FAILED*\n```{error_msg}```")
                except Exception:
                    pass
            raise

    async def _run_pipeline(
        self,
        max_videos_per_channel: int,
        vph_threshold: float,
        num_ideas: int,
        save_to_airtable: bool,
        notify_slack: bool,
    ) -> dict:
        """Internal pipeline implementation."""
        # Step 1: Scrape
        videos = await self.scrape_channels(max_videos_per_channel)
        print(f"  Scraped {len(videos)} videos total")

        # Step 2: Filter winners
        threshold = vph_threshold or self.DEFAULT_VPH_THRESHOLD
        winners = self.filter_winners(videos, vph_threshold)
        print(f"  Found {len(winners)} winners (VPH > {threshold})")

        if winners:
            print("\n  TOP WINNERS:")
            for i, w in enumerate(winners[:5], 1):
                title = w.get("title", "")[:50]
                print(f"    {i}. {title}...")
                print(
                    f"       {w.get('views', 0):,} views | "
                    f"{w.get('vph', 0):.0f} VPH | {w.get('channel', '')}"
                )

        # Step 3: Generate ideas
        ideas = await self.generate_ideas_from_winners(winners, num_ideas)

        if ideas:
            print(f"\n  GENERATED {len(ideas)} IDEAS:")
            for i, idea in enumerate(ideas, 1):
                print(f"    {i}. {idea.get('viral_title', 'Untitled')}")

        # Step 4: Save to Airtable
        saved_records = []
        if save_to_airtable and ideas:
            print("\n  SAVING TO AIRTABLE...")
            for i, idea in enumerate(ideas, 1):
                try:
                    record = self.airtable.create_idea(idea, source="competitor_scraper")
                    saved_records.append(record)
                    print(f"    Saved idea {i}: {record.get('id')}")
                except Exception as e:
                    print(f"    Failed to save idea {i}: {e}")

        # Step 5: Notify Slack
        if notify_slack and self.slack:
            try:
                self._send_slack_notification(winners, ideas)
                print("  Slack notification sent")
            except Exception as e:
                print(f"  Slack notification failed: {e}")

        print("\n" + "=" * 60)
        print("COMPETITOR SCRAPER COMPLETE")
        print("=" * 60)

        return {
            "videos_scraped": len(videos),
            "winners": winners,
            "ideas": ideas,
            "saved_records": saved_records,
        }

    def _send_slack_notification(self, winners: list[dict], ideas: list[dict]):
        """Send formatted Slack notification."""
        message = "*COMPETITOR SCRAPER RESULTS*\n\n"

        # Winners section
        if winners:
            message += "*Top Performers:*\n"
            for w in winners[:3]:
                title = w.get("title", "")[:50]
                message += f"• {title}...\n"
                message += (
                    f"  {w.get('views', 0):,} views | "
                    f"{w.get('vph', 0):.0f} VPH | {w.get('channel', '')}\n"
                )
            message += "\n"

        # Ideas section
        if ideas:
            message += "*Generated Ideas:*\n"
            for i, idea in enumerate(ideas, 1):
                message += f"{i}. {idea.get('viral_title', 'Untitled')}\n"
                hook = idea.get("hook_script", "")[:80]
                if hook:
                    message += f"   Hook: {hook}...\n"

        self.slack.notify(message)
