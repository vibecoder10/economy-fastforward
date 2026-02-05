"""
TrendingIdeaBot - Generates video ideas based on trending YouTube content.

This bot:
1. Scrapes trending videos in the finance/economy niche via Apify
2. Analyzes title patterns, keywords, and performance metrics
3. Uses Claude to model new ideas based on what's working NOW
4. Generates clickbait-worthy titles that fit the channel's style
"""

from typing import Optional


class TrendingIdeaBot:
    """Generates video ideas by analyzing trending content.

    Channel: Economy Fast-Forward
    Angle: Futuristic predictions using past → present → future narrative
    Style: Dramatic, urgent, predictive documentary-style content
    """

    # Default search queries organized by category
    DEFAULT_SEARCH_QUERIES = [
        # Economy & Finance
        "economy collapse 2025",
        "stock market crash prediction",
        "federal reserve rate cuts",
        "inflation crisis",
        "dollar collapse",
        "recession warning",
        "bank crisis",
        "financial crisis prediction",

        # AI & Technology
        "AI bubble burst",
        "artificial intelligence takeover",
        "AI replacing jobs",
        "tech layoffs 2025",
        "nvidia stock crash",
        "AI regulation",

        # Robotics & Automation
        "robots replacing workers",
        "humanoid robots",
        "automation crisis",
        "tesla optimus robot",

        # Macroeconomics
        "treasury bond crisis",
        "national debt crisis",
        "hyperinflation",
        "BRICS dollar replacement",
        "de-dollarization",
        "central bank digital currency",

        # Geopolitics
        "china economy collapse",
        "tariff war",
        "world war 3 economy",
        "sanctions impact",
        "taiwan invasion economic",

        # Real Estate & Housing
        "real estate crash 2025",
        "housing bubble burst",
        "commercial real estate collapse",

        # Crypto & Alternative Assets
        "bitcoin crash",
        "crypto crash prediction",
        "gold price prediction",
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
        max_results_per_query: int = 10,
        upload_date: str = "month",
    ) -> dict:
        """Scrape and analyze trending videos.

        Args:
            search_queries: Custom search terms, or use defaults
            max_results_per_query: Videos per search query
            upload_date: Recency filter - "week", "month", "year"

        Returns:
            Analysis dict with trends, patterns, top performers
        """
        queries = search_queries or self.DEFAULT_SEARCH_QUERIES

        print(f"\n🔍 SCRAPING: {len(queries)} search queries...")

        videos = await self.apify.search_trending_videos(
            search_queries=queries,
            max_results_per_query=max_results_per_query,
            sort_by="viewCount",  # Sort by most viewed
            upload_date=upload_date,
        )

        print(f"\n📊 ANALYZING: {len(videos)} total videos...")

        analysis = self.apify.analyze_trending_patterns(videos)

        return {
            "videos": videos,
            "analysis": analysis,
        }

    async def generate_ideas_from_trends(
        self,
        trending_data: dict,
        num_ideas: int = 3,
        save_to_airtable: bool = True,
        notify_slack: bool = True,
    ) -> list[dict]:
        """Generate video ideas based on trending analysis.

        Args:
            trending_data: Output from scrape_trending()
            num_ideas: Number of ideas to generate
            save_to_airtable: Whether to save to Airtable
            notify_slack: Whether to send Slack notification

        Returns:
            List of generated video concept dicts
        """
        analysis = trending_data.get("analysis", {})

        # Build context for Claude
        top_videos = analysis.get("top_10_by_views", [])
        top_keywords = analysis.get("top_keywords", [])[:15]
        all_titles = analysis.get("all_titles", [])[:30]
        patterns = analysis.get("title_patterns", {})

        print(f"\n💡 GENERATING {num_ideas} ideas from trends...")

        # Create the prompt for Claude
        system_prompt = """You are the Executive Producer for 'Economy Fast-Forward', a faceless YouTube channel that projects current events into dramatic future scenarios.

CHANNEL IDENTITY:
- Style: Documentary-style, dramatic narration, futuristic projections
- Topics: Economy, finance, AI/tech, robotics, macroeconomics, geopolitics
- Angle: "What history teaches us about what's coming next"
- Narrative: Always use PAST → PRESENT → FUTURE structure

Your job is to analyze trending video titles and patterns, then CREATE ORIGINAL video concepts that:
1. MODEL the successful patterns (title structure, keywords, emotional hooks)
2. DO NOT COPY - create unique FUTURE-FOCUSED angles
3. Connect current events to historical parallels AND future predictions

TITLE RULES:
- Create URGENCY and CURIOSITY
- Use specific numbers, years, or dollar amounts ($2.7 Trillion, 2027, 89%)
- ALL CAPS for 1-2 words max (COLLAPSE, CRASH, EXPOSED, WARNING)
- Colons work well: "The $X Crisis: What Happens Next"
- Future dates perform well (2025, 2026, 2027, 2030)
- Mysterious authority hooks: "THEY Just...", "The Document Nobody Read..."

TOPIC MIX - Generate ideas across these categories:
- Financial crises & market predictions
- AI/Tech disruption & job displacement
- Geopolitical shifts & their economic impact
- Historical parallels to current events

OUTPUT FORMAT:
Return a JSON object with a "concepts" array containing exactly {num_ideas} video concepts:
{{
  "concepts": [
    {{
      "viral_title": "The actual YouTube title",
      "modeled_from": "Brief note on which pattern/title inspired this",
      "thumbnail_visual": "Thumbnail concept description",
      "hook_script": "First 15 seconds of the video script",
      "narrative_logic": {{
        "past_context": "Historical event this relates to",
        "present_parallel": "What's happening NOW",
        "future_prediction": "What this means for the future"
      }},
      "writer_guidance": "Key points for the scriptwriter"
    }}
  ]
}}"""

        user_prompt = f"""Analyze these TRENDING video patterns and generate {num_ideas} ORIGINAL video concepts:

## TOP PERFORMING TITLES (by views):
{chr(10).join(f'- "{v["title"]}" ({v["views"]:,} views) - {v["channel"]}' for v in top_videos[:10])}

## TOP KEYWORDS IN TRENDING TITLES:
{', '.join(f'{word} ({count})' for word, count in top_keywords)}

## TITLE PATTERN ANALYSIS:
- Titles with numbers: {patterns.get('has_number', 0)}/{len(all_titles)}
- Titles with questions: {patterns.get('has_question', 0)}/{len(all_titles)}
- Titles with colons: {patterns.get('has_colon', 0)}/{len(all_titles)}
- Titles with ALL CAPS words: {patterns.get('has_caps_word', 0)}/{len(all_titles)}
- Titles with year references: {patterns.get('has_year', 0)}/{len(all_titles)}

## SAMPLE OF ALL TRENDING TITLES:
{chr(10).join(f'- {title}' for title in all_titles[:20])}

---
Generate {num_ideas} ORIGINAL concepts that MODEL these successful patterns.
Each concept should feel like it could be the #1 trending video tomorrow.
Return ONLY the JSON object, no other text."""

        response = await self.anthropic.generate(
            prompt=user_prompt,
            system_prompt=system_prompt.format(num_ideas=num_ideas),
            model="claude-sonnet-4-5-20250929",
        )

        # Parse response
        import json
        clean_response = response.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_response)

        ideas = data.get("concepts", [])

        print(f"  Generated {len(ideas)} ideas:")
        for i, idea in enumerate(ideas, 1):
            title = idea.get("viral_title", "Untitled")
            modeled = idea.get("modeled_from", "")[:50]
            print(f"    {i}. {title}")
            print(f"       (modeled from: {modeled}...)")

        # Add trending analysis reference and top video URL to each idea
        top_videos = analysis.get("top_10_by_views", [])
        top_video_url = top_videos[0].get("url", "") if top_videos else ""

        for idea in ideas:
            idea["original_dna"] = f"Trending analysis: {len(trending_data.get('videos', []))} videos analyzed"
            # Add the top-viewed video URL as reference for thumbnail creation
            if top_video_url:
                idea["reference_url"] = top_video_url

        # Save to Airtable
        if save_to_airtable:
            print("  Saving to Airtable...")
            for i, idea in enumerate(ideas, 1):
                try:
                    record = self.airtable.create_idea(idea)
                    print(f"    ✅ Saved idea {i}: {record.get('id')}")
                except Exception as e:
                    print(f"    ❌ Failed to save idea {i}: {e}")

        # Notify Slack
        if notify_slack and self.slack:
            try:
                self.slack.notify_idea_generated(ideas)
                print("  ✅ Slack notification sent")
            except Exception as e:
                print(f"  ⚠️ Slack notification failed: {e}")

        return ideas

    async def generate_from_trending(
        self,
        search_queries: Optional[list[str]] = None,
        max_results_per_query: int = 10,
        num_ideas: int = 3,
        save_to_airtable: bool = True,
        notify_slack: bool = True,
    ) -> dict:
        """Full pipeline: scrape trends → analyze → generate ideas.

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
        print("📈 TRENDING IDEA BOT - Analyzing What's Working NOW")
        print("=" * 60)

        # Step 1: Scrape trending videos
        trending_data = await self.scrape_trending(
            search_queries=search_queries,
            max_results_per_query=max_results_per_query,
        )

        # Step 2: Generate ideas from analysis
        ideas = await self.generate_ideas_from_trends(
            trending_data=trending_data,
            num_ideas=num_ideas,
            save_to_airtable=save_to_airtable,
            notify_slack=notify_slack,
        )

        print("\n" + "=" * 60)
        print("✅ TRENDING IDEA BOT COMPLETE")
        print("=" * 60)
        print(f"Analyzed: {len(trending_data.get('videos', []))} trending videos")
        print(f"Generated: {len(ideas)} original concepts")
        print("\nNext steps:")
        print("  1. Review ideas in Airtable")
        print("  2. Set your chosen idea's status to 'Ready For Scripting'")
        print("  3. Run: python pipeline.py")

        return {
            "trending_data": trending_data,
            "ideas": ideas,
        }
