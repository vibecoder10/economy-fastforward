"""
TrendingIdeaBot - Generates video ideas based on trending YouTube content.

This bot (v2 — Idea Engine):
1. Scrapes trending videos in the finance/economy niche via Apify
2. Decomposes each title into typed variables (number, topic, benefit, etc.)
3. Extracts reusable format patterns from decomposed titles
4. Classifies psychological triggers (fear, urgency, aspiration, etc.)
5. Rebuilds proven formats with Economy FastForward niche variables
6. Persists discovered formats for compounding over time
"""

import json
from typing import Optional

from .idea_modeling import (
    decompose_title,
    extract_format,
    generate_modeled_ideas,
    load_config,
    save_config,
    update_format_library,
)


class TrendingIdeaBot:
    """Generates video ideas by analyzing trending content.

    Channel: Economy Fast-Forward
    Angle: Futuristic predictions using past -> present -> future narrative
    Style: Dramatic, urgent, predictive documentary-style content
    """

    # Focused search queries - top performers only
    DEFAULT_SEARCH_QUERIES = [
        # Core economy topics (high performers)
        "economy collapse 2025",
        "stock market crash prediction",
        "recession warning 2025",
        # AI & Tech disruption
        "AI bubble burst",
        "AI replacing jobs 2025",
        # Macro/Geopolitics
        "dollar collapse prediction",
        "china economy collapse",
        "tariff war economic impact",
    ]

    # Competitor channels - similar futuristic/documentary style
    COMPETITOR_CHANNELS = [
        # Direct competitors (same style niche)
        "https://www.youtube.com/@EconomyRewind",
        "https://www.youtube.com/@chillfinancialhistorian",
        "https://www.youtube.com/@IndependentFinancialHistorian",
        # Broader finance/economy channels
        "https://www.youtube.com/@Heresy_Financial",
        "https://www.youtube.com/@StevenVanMetre",
        "https://www.youtube.com/@MoneyGPS",
        "https://www.youtube.com/@EconomicsExplained",
    ]

    def __init__(
        self,
        apify_client,
        anthropic_client,
        airtable_client,
        gemini_client=None,
        slack_client=None,
    ):
        """Initialize with required clients.

        Args:
            apify_client: For scraping YouTube trending videos
            anthropic_client: For generating ideas with Claude
            airtable_client: For saving ideas to Airtable
            gemini_client: Optional, for thumbnail analysis
            slack_client: Optional, for notifications
        """
        self.apify = apify_client
        self.anthropic = anthropic_client
        self.airtable = airtable_client
        self.gemini = gemini_client
        self.slack = slack_client

    async def scrape_trending(
        self,
        search_queries: Optional[list[str]] = None,
        max_results_per_query: int = 5,
        upload_date: str = "month",
        top_n: int = 15,
    ) -> dict:
        """Scrape and analyze trending videos.

        Args:
            search_queries: Custom search terms, or use defaults
            max_results_per_query: Videos per search query (default 5)
            upload_date: Recency filter - "week", "month", "year"
            top_n: Only analyze top N videos by views (default 15)

        Returns:
            Analysis dict with trends, patterns, top performers
        """
        queries = search_queries or self.DEFAULT_SEARCH_QUERIES

        print(f"\n🔍 SCRAPING: {len(queries)} queries × {max_results_per_query} results = ~{len(queries) * max_results_per_query} videos")

        videos = await self.apify.search_trending_videos(
            search_queries=queries,
            max_results_per_query=max_results_per_query,
            sort_by="viewCount",  # Sort by most viewed
            upload_date=upload_date,
        )

        print(f"  Scraped {len(videos)} videos total")

        # Sort by views and keep only top N
        videos_sorted = sorted(videos, key=lambda x: x.get("views", 0), reverse=True)
        top_videos = videos_sorted[:top_n]

        print(f"\n📊 ANALYZING: Top {len(top_videos)} videos by views...")
        for i, v in enumerate(top_videos[:5], 1):
            print(f"  {i}. {v.get('title', '')[:50]}... ({v.get('views', 0):,} views)")

        analysis = self.apify.analyze_trending_patterns(top_videos)

        return {
            "videos": top_videos,
            "analysis": analysis,
        }

    async def generate_ideas_from_trends(
        self,
        trending_data: dict,
        num_ideas: int = 3,
        save_to_airtable: bool = True,
        notify_slack: bool = True,
    ) -> list[dict]:
        """Generate video ideas using v2 format-modeling pipeline.

        Flow: decompose titles -> extract formats -> generate modeled ideas -> persist formats

        Args:
            trending_data: Output from scrape_trending()
            num_ideas: Number of ideas to generate
            save_to_airtable: Whether to save to Airtable
            notify_slack: Whether to send Slack notification

        Returns:
            List of generated video concept dicts
        """
        all_videos = trending_data.get("videos", [])
        analysis = trending_data.get("analysis", {})

        # Load modeling config
        try:
            config = load_config()
        except Exception as e:
            print(f"  ⚠️ Could not load modeling config: {e}")
            print("  Falling back to defaults...")
            config = {"psychological_triggers": [], "variable_types": [], "format_library": [], "niche_variables": {}}

        # --- Step 1: Decompose each title into variables ---
        print(f"\n🔬 DECOMPOSING: {len(all_videos)} titles into variables...")
        decomposed = []
        for i, video in enumerate(all_videos):
            title = video.get("title", "")
            views = video.get("views", 0)
            if not title:
                continue
            result = await decompose_title(title, self.anthropic, views=views)
            decomposed.append(result)
            if result.get("formula"):
                print(f"  ✅ {i+1}. {title[:45]}...")
                print(f"       Formula: {result['formula']}")
            else:
                print(f"  ⚠️ {i+1}. {title[:45]}... (no formula extracted)")

        successful = sum(1 for d in decomposed if d.get("formula"))
        print(f"\n  Decomposed {successful}/{len(decomposed)} titles successfully")

        # --- Step 2: Extract reusable formats ---
        print(f"\n📐 EXTRACTING reusable formats...")
        formats = extract_format(decomposed)
        print(f"  Found {len(formats)} distinct format patterns:")
        for fmt in formats[:5]:
            print(f"    • {fmt['formula']}")
            print(f"      Seen {fmt['times_seen']}x, avg {fmt['avg_views']:,} views")
            print(f"      Example: \"{fmt['example_titles'][0][:50]}...\"")

        # --- Step 3: Persist formats to library ---
        print(f"\n💾 UPDATING format library...")
        old_count = len(config.get("format_library", []))
        config = update_format_library(formats, config)
        new_count = len(config.get("format_library", []))
        try:
            save_config(config)
            print(f"  Library: {old_count} -> {new_count} formats ({new_count - old_count} new)")
        except Exception as e:
            print(f"  ⚠️ Failed to save format library: {e}")

        # --- Step 4: Generate modeled ideas ---
        print(f"\n💡 GENERATING {num_ideas} format-modeled ideas...")
        modeled_ideas = await generate_modeled_ideas(
            formats=formats,
            config=config,
            anthropic_client=self.anthropic,
            num_ideas=num_ideas,
        )

        print(f"  Generated {len(modeled_ideas)} modeled ideas:")
        for i, idea in enumerate(modeled_ideas, 1):
            print(f"    {i}. {idea.get('viral_title', 'Untitled')}")
            print(f"       Format: {idea.get('based_on_format', 'unknown')}")
            swaps = idea.get("variables_swapped", [])
            if swaps:
                print(f"       Swapped: {', '.join(swaps[:3])}")

        # Enrich ideas with source video data and Airtable-compatible fields
        ideas = self._enrich_ideas(modeled_ideas, all_videos, analysis, decomposed)

        # Save to Airtable
        if save_to_airtable:
            print("  Saving to Airtable...")
            for i, idea in enumerate(ideas, 1):
                try:
                    record = self.airtable.create_idea(idea)
                    print(f"    ✅ Saved idea {i}: {record.get('id')}")
                except Exception as e:
                    print(f"    ❌ Failed to save idea {i}: {e}")

        # Notify Slack with v2 format
        if notify_slack and self.slack:
            try:
                self._send_v2_slack_notification(
                    ideas=modeled_ideas,
                    num_videos=len(all_videos),
                    num_formats=len(formats),
                )
                print("  ✅ Slack notification sent (v2 format)")
            except Exception as e:
                print(f"  ⚠️ Slack notification failed: {e}")

        return ideas

    def _enrich_ideas(
        self,
        modeled_ideas: list[dict],
        all_videos: list[dict],
        analysis: dict,
        decomposed: list[dict],
    ) -> list[dict]:
        """Enrich modeled ideas with source video data for Airtable compatibility.

        Converts v2 idea format to the existing Airtable-compatible format while
        preserving the v2 modeling metadata.
        """
        top_videos = analysis.get("top_10_by_views", [])
        enriched = []

        for idea in modeled_ideas:
            # Build Airtable-compatible record
            record = {
                "viral_title": idea.get("viral_title", ""),
                "source_title": idea.get("original_example", ""),
                "modeled_from": (
                    f"Format: {idea.get('based_on_format', 'N/A')} | "
                    f"Swapped: {', '.join(idea.get('variables_swapped', []))} | "
                    f"Triggers: {', '.join(idea.get('psychological_triggers', []))} | "
                    f"{idea.get('hook_summary', '')}"
                ),
                "original_dna": f"v2 format-modeled: {len(all_videos)} videos analyzed",
                # Preserve v2 metadata
                "_v2_format": idea.get("based_on_format", ""),
                "_v2_triggers": idea.get("psychological_triggers", []),
                "_v2_swaps": idea.get("variables_swapped", []),
            }

            # Match to source video for URL + metrics
            source_title = idea.get("original_example", "")
            matched_video = None

            if source_title:
                for v in all_videos:
                    if v.get("title", "").lower() == source_title.lower():
                        matched_video = v
                        break
                if not matched_video:
                    for v in all_videos:
                        vtitle = v.get("title", "").lower()
                        stitle = source_title.lower()
                        if stitle in vtitle or vtitle in stitle:
                            matched_video = v
                            break

            if matched_video:
                record["reference_url"] = matched_video.get("url", "")
                record["source_views"] = matched_video.get("views", 0)
                record["source_channel"] = matched_video.get("channel", "")
            elif top_videos:
                record["reference_url"] = top_videos[0].get("url", "")
                record["source_views"] = top_videos[0].get("views", 0)
                record["source_channel"] = top_videos[0].get("channel", "")

            enriched.append(record)

        return enriched

    def _send_v2_slack_notification(
        self,
        ideas: list[dict],
        num_videos: int,
        num_formats: int,
    ) -> None:
        """Send Slack notification in the v2 format with format attribution."""
        lines = [
            "🎯 *IDEA ENGINE v2 — Format-Modeled Ideas*",
            "",
            f"📊 Analyzed {num_videos} trending videos → Extracted {num_formats} reusable formats",
            "",
            "---",
        ]

        for i, idea in enumerate(ideas, 1):
            title = idea.get("viral_title", "Untitled")
            fmt = idea.get("based_on_format", "unknown")
            original = idea.get("original_example", "N/A")
            swaps = idea.get("variables_swapped", [])
            triggers = idea.get("psychological_triggers", [])
            hook = idea.get("hook_summary", "")

            lines.append("")
            lines.append(f"💡 *Idea {i}:* \"{title}\"")
            lines.append(f"📐 Format: {fmt}")
            lines.append(f"🧠 Based on: \"{original}\"")
            if swaps:
                lines.append(f"🔄 Swapped: {', '.join(swaps)}")
            if triggers:
                lines.append(f"🎯 Triggers: {', '.join(triggers)}")
            if hook:
                lines.append(f"💬 {hook}")

        lines.append("")
        lines.append("---")
        lines.append("Type `--more-ideas` for 3 more from these formats")

        self.slack.send_message("\n".join(lines))

    async def generate_from_trending(
        self,
        search_queries: Optional[list[str]] = None,
        max_results_per_query: int = 10,
        num_ideas: int = 3,
        save_to_airtable: bool = True,
        notify_slack: bool = True,
    ) -> dict:
        """Full pipeline: scrape trends -> decompose -> extract formats -> generate ideas.

        Args:
            search_queries: Custom search terms
            max_results_per_query: Videos per query
            num_ideas: Number of ideas to generate
            save_to_airtable: Save to Airtable
            notify_slack: Send Slack notification

        Returns:
            Dict with trending_data and generated ideas
        """
        print("\n" + "=" * 60)
        print("📈 IDEA ENGINE v2 — Format-Modeled Trending Analysis")
        print("=" * 60)

        # Step 1: Scrape trending videos
        trending_data = await self.scrape_trending(
            search_queries=search_queries,
            max_results_per_query=max_results_per_query,
        )

        # Step 2: Decompose, extract formats, generate modeled ideas
        ideas = await self.generate_ideas_from_trends(
            trending_data=trending_data,
            num_ideas=num_ideas,
            save_to_airtable=save_to_airtable,
            notify_slack=notify_slack,
        )

        print("\n" + "=" * 60)
        print("✅ IDEA ENGINE v2 COMPLETE")
        print("=" * 60)
        print(f"Analyzed: {len(trending_data.get('videos', []))} trending videos")
        print(f"Generated: {len(ideas)} format-modeled concepts")
        print("\nNext steps:")
        print("  1. Review ideas in Airtable")
        print("  2. Set your chosen idea's status to 'Ready For Scripting'")
        print("  3. Run: python pipeline.py")

        return {
            "trending_data": trending_data,
            "ideas": ideas,
        }
