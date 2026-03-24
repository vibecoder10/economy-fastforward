"""Idea generation step — creates video concepts from URLs, topics, or trends.

Reads: User input (URL or concept text), or trending YouTube videos
Writes: Idea records to Airtable Ideas table
Status: Creates records at "Idea Logged"
Clients: anthropic, airtable, gemini, slack, apify (trending only)
"""

from typing import Optional

from orchestrator.pipeline_constants import Statuses
from title_idea.idea_bot import IdeaBot
from title_idea.trending_idea_bot import TrendingIdeaBot


async def run_idea(pipeline, input_text: str) -> dict:
    """Generate video ideas from a YouTube URL or concept."""
    print("\n" + "=" * 60)
    print("💡 IDEA BOT - Generating Video Concepts")
    print("=" * 60)

    idea_bot = IdeaBot(
        anthropic_client=pipeline.anthropic,
        airtable_client=pipeline.airtable,
        gemini_client=pipeline.gemini,
        slack_client=pipeline.slack,
    )

    ideas = await idea_bot.generate_ideas(
        input_text=input_text,
        save_to_airtable=True,
        notify_slack=True,
    )

    print("\n" + "=" * 60)
    print("✅ IDEA BOT COMPLETE")
    print("=" * 60)
    print(f"Generated {len(ideas)} ideas:")
    for i, idea in enumerate(ideas, 1):
        print(f"  {i}. {idea.get('viral_title', 'Untitled')}")
    print("\nNext steps:")
    print("  1. Review ideas in Airtable")
    print("  2. Set your chosen idea's status to 'Ready For Scripting'")
    print("  3. Run: python pipeline.py")

    return {
        "status": "ideas_generated",
        "count": len(ideas),
        "ideas": [idea.get("viral_title") for idea in ideas],
    }


async def run_trending(
    pipeline,
    search_queries: Optional[list[str]] = None,
    num_ideas: int = 3,
) -> dict:
    """Generate video ideas by analyzing trending YouTube content."""
    if not pipeline.apify:
        return {"error": "Apify API key not configured. Add APIFY_API_KEY to .env"}

    trending_bot = TrendingIdeaBot(
        apify_client=pipeline.apify,
        anthropic_client=pipeline.anthropic,
        airtable_client=pipeline.airtable,
        gemini_client=pipeline.gemini,
        slack_client=pipeline.slack,
    )

    result = await trending_bot.generate_from_trending(
        search_queries=search_queries,
        num_ideas=num_ideas,
        save_to_airtable=True,
        notify_slack=True,
    )

    return {
        "status": "trending_ideas_generated",
        "videos_analyzed": len(result.get("trending_data", {}).get("videos", [])),
        "ideas": [idea.get("viral_title") for idea in result.get("ideas", [])],
    }
