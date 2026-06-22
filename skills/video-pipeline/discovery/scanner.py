"""
Discovery Scanner — Scans headlines AND competitor videos, filters through
Machiavellian lens, and generates title variants using the pattern library.

Two idea sources (50/50 split):
  1. WORLD NEWS: Current headlines across geopolitics, finance, tech, economic policy
  2. COMPETITORS: Top-performing videos from competitor channels (past 7 days)

Both sources are filtered through the channel's dark power dynamics lens and
formatted into proven MF (Master Formula) title structures.

Usage (standalone):
    python discovery_scanner.py
    python discovery_scanner.py --focus "BRICS currency"
    python discovery_scanner.py --output discoveries.json

Usage (imported):
    from discovery.scanner import DiscoveryScanner, run_discovery

    scanner = DiscoveryScanner(anthropic_client, apify_client, airtable_client)
    ideas = await scanner.scan()
"""

import asyncio
import json
import logging
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Import competitor VPH calculation
from competitor_scraper.scraper import calculate_vph
from shared.clients.narrative_extractor import extract_narrative_fields_from_concept
from orchestrator.pipeline_constants import IdeaFields, Models
from shared.json_utils import parse_json_response

# Source categories for headline scanning
SCAN_SOURCES = {
    "geopolitics": [
        "Reuters world news",
        "AP News international",
        "BBC World",
        "Al Jazeera",
    ],
    "finance": [
        "Bloomberg markets",
        "Financial Times",
        "Wall Street Journal",
        "CNBC",
    ],
    "tech_business": [
        "TechCrunch",
        "Ars Technica",
        "Fortune",
        "Forbes",
    ],
    "economic_policy": [
        "Federal Reserve announcements",
        "IMF reports",
        "World Bank",
        "central bank policy",
    ],
}


def _load_title_patterns() -> dict:
    """Load the title pattern library from title_patterns.json."""
    patterns_path = Path(__file__).resolve().parent.parent / "title_patterns.json"
    if not patterns_path.exists():
        raise FileNotFoundError(
            f"title_patterns.json not found at {patterns_path}. "
            f"Run Story 0 first to create it."
        )
    with open(patterns_path) as f:
        return json.load(f)


def _load_discovery_prompt() -> str:
    """Load the discovery scanner system prompt from discovery_prompt.md."""
    prompt_path = Path(__file__).parent / "discovery_prompt.md"
    if not prompt_path.exists():
        raise FileNotFoundError(
            f"discovery_prompt.md not found at {prompt_path}. "
            f"Run Story 4 first to create it."
        )
    with open(prompt_path) as f:
        return f.read()



def _build_headline_scan_prompt(
    headlines: str,
    title_patterns: dict,
    focus: Optional[str] = None,
) -> str:
    """Build the user prompt for the discovery scanner LLM call.

    Combines the gathered headlines with the Power Doctrine formula library
    and instructions for viewer-first title generation.
    """
    # Extract master formulas only (v3) — legacy PD formulas excluded from primary generation
    master_formulas = title_patterns.get("master_formulas", [])
    # Also support old v2 format where formulas are under "formulas" key
    if not master_formulas:
        master_formulas = title_patterns.get("formulas", [])

    formulas_summary = "\n".join(
        f"- {f['id']}: {f['name']} — Template: \"{f['template']}\""
        for f in master_formulas
    )

    # Extract scoring rules if available (v3 feature)
    scoring_rules = title_patterns.get("scoring_rules", {})
    scoring_text = ""
    if scoring_rules:
        criteria = scoring_rules.get("criteria", [])
        scoring_text = "\n\n=== TITLE SCORING CRITERIA ===\n"
        scoring_text += "\n".join(
            f"- {c['name']} (weight: {c['weight']}): {c['rule']}"
            for c in criteria
        )
        hard_rules = scoring_rules.get("hard_rules", [])
        if hard_rules:
            scoring_text += "\nHard rules:\n" + "\n".join(f"- {r}" for r in hard_rules)

    # Extract thumbnail system rules
    thumbnail_system = title_patterns.get("thumbnail_system", {})
    thumbnail_rules = thumbnail_system.get("rules", [])
    thumbnail_text = "\n".join(f"- {r}" for r in thumbnail_rules)
    # Include good/bad examples if available
    good_examples = thumbnail_system.get("good_examples", [])
    bad_examples = thumbnail_system.get("bad_examples", [])
    if good_examples:
        thumbnail_text += "\nGood examples: " + ", ".join(good_examples)
    if bad_examples:
        thumbnail_text += "\nBad examples (DO NOT USE): " + ", ".join(bad_examples)

    focus_instruction = ""
    if focus:
        clean_focus = focus.strip("[]")
        focus_instruction = (
            f"\n\nFOCUS TOPIC: '{clean_focus}'\n"
            f"ALL ideas MUST be directly about this topic. "
            f"Generate different angles/perspectives on this specific topic. "
            f"Do NOT include ideas about unrelated topics regardless of their "
            f"appeal score.\n"
            f"If the headlines contain no relevant results for this topic, "
            f"say so explicitly — do not substitute unrelated headlines."
        )

    return f"""\
Analyze these current headlines and select the 2-3 best stories for
Economy FastForward videos. Apply the analytical lens and generate
3 title options per story using the Master Formula (MF) title system.

=== CURRENT HEADLINES ===
{headlines}

=== TITLE FORMULA LIBRARY (MF system — use ONLY these) ===
{formulas_summary}

=== FULL FORMULA LIBRARY (for variable reference and examples) ===
{json.dumps(master_formulas, indent=2)}
{scoring_text}

=== THUMBNAIL STRATEGIC VERDICT SYSTEM ===
{thumbnail_text}
{focus_instruction}

TITLE GENERATION RULES (STRICT):

You are generating titles for Economy FastForward, a geopolitical analysis YouTube channel.

MODEL THESE CHANNELS (study their title patterns):
- CaspianReport (1.8M subs): "How the Iran War set off a regional conflict" — short, declarative, proper noun first
- AiTelly (2M subs): "How Iran Breached US Israeli Air Defenses" — direct mechanism, tells you exactly what you'll learn

HARD RULES:
1. MAXIMUM 55 characters. Ideal is 35-50. Count every character.
2. Start with "How" or "Why" — these are the two highest-performing openers in this niche
3. First word after How/Why MUST be a proper noun (country, company, institution, person)
4. NEVER use "YOU" or "YOUR" — this is analysis, not self-help
5. NEVER use commands (NEVER, STOP, DON'T) — this is not Mindplicit
6. NEVER use ALL CAPS words except acronyms (US, NATO, PBOC, LNG)
7. No em dashes (—), no parenthetical asides, no pipe separators (|)
8. No cleverness. The event itself is interesting. Just state what the video explains.
9. Declarative statements only. No question marks unless genuinely unanswered.
10. The title should read like a military briefing header or CaspianReport episode title.

FORMULA OPTIONS (pick the best fit):
- MF-0: "How [Entity] [Clear Action] [Target]" — for breaking events, mechanisms
- MF-1: "How [Entity] [Secret Action] [Surprising Detail]" — for hidden strategies
- MF-2: "Why [Country/Entity] [Dramatic Present-Tense Claim]" — for causal analysis
- MF-6: "[Country]'s [Adjective] [Crisis/Collapse/Trap]" — for decline stories (shortest format)

Generate exactly 3 title candidates per story. Each must use a DIFFERENT formula. Score each 0-100.

INSTRUCTIONS:
1. Select exactly 2-3 stories (not more, not less)
2. Each story must pass the power dynamics filter (minimum 6/10)
3. Generate 3 title options per story, each using a DIFFERENT MF formula
4. Every title MUST contain at least one proper noun (country, company, person)
5. For EACH title, generate a 2-word ALL CAPS thumbnail verdict (strategic judgment, no YOUR language)
6. Score each title 0-100 using the scoring criteria
7. Rate each story's appeal (1-10) with breakdown by criterion
8. Suggest a historical parallel for the research phase
9. Write a 2-3 sentence hook that creates a curiosity gap
10. Pick the best-fit analytical framework for each idea from: 48 Laws, Sun Tzu, Machiavelli, Thucydides Trap, Antifragile, Grand Chessboard, Kindleberger Trap, Schelling, Collective Action, Soft Power, Game Theory, Systems Thinking, Propaganda, Behavioral Econ

Return your response as valid JSON following the output format specified
in your system prompt. No markdown code blocks — raw JSON only.
"""


def _parse_scanner_output(response_text: str) -> dict:
    """Parse the JSON output from the discovery scanner LLM.

    Handles potential formatting issues (markdown code blocks, etc.)
    """
    result = parse_json_response(response_text, default=None)
    if result is None:
        raise json.JSONDecodeError("Failed to parse scanner output", response_text, 0)

    # Validate structure
    ideas = result.get("ideas", [])
    if not ideas:
        raise ValueError("Scanner output contains no ideas")

    if len(ideas) > 3:
        logger.warning(
            f"Scanner returned {len(ideas)} ideas, trimming to 3"
        )
        result["ideas"] = ideas[:3]

    # Validate each idea has required fields
    required_fields = [
        "headline_source",
        "our_angle",
        "title_options",
        "hook",
        "estimated_appeal",
    ]
    for i, idea in enumerate(result["ideas"]):
        missing = [f for f in required_fields if f not in idea]
        if missing:
            logger.warning(f"Idea {i+1} missing fields: {missing}")

        # Validate title_options have formula_id and thumbnail_text
        title_opts = idea.get("title_options", [])
        if len(title_opts) < 3:
            logger.warning(
                f"Idea {i+1} has {len(title_opts)} title options "
                f"(expected 3, one per MF formula)"
            )
        for j, title_opt in enumerate(title_opts):
            if "formula_id" not in title_opt:
                logger.warning(
                    f"Idea {i+1}, title option {j+1} missing formula_id"
                )
            if "thumbnail_text" not in title_opt:
                logger.warning(
                    f"Idea {i+1}, title option {j+1} missing thumbnail_text"
                )

    return result


def _parse_competitor_output(response_text: str) -> dict:
    """Parse the JSON output from the competitor idea generator.

    Similar to _parse_scanner_output but expects 'competitor_ideas' key.
    """
    result = parse_json_response(response_text, default=None)
    if result is None:
        raise json.JSONDecodeError("Failed to parse competitor output", response_text, 0)

    # Validate structure
    ideas = result.get("competitor_ideas", [])
    if not ideas:
        logger.warning("Competitor output contains no ideas")
        result["competitor_ideas"] = []
        return result

    # Validate each idea has required fields
    required_fields = [
        "competitor_title",
        "title_options",
    ]
    for i, idea in enumerate(ideas):
        missing = [f for f in required_fields if f not in idea]
        if missing:
            logger.warning(f"Competitor idea {i+1} missing fields: {missing}")

        # Ensure title_options exist
        if not idea.get("title_options"):
            logger.warning(f"Competitor idea {i+1} has no title_options")

    return result


class DiscoveryScanner:
    """Scans headlines AND competitor videos, generates ideas through Machiavellian lens.

    Usage:
        scanner = DiscoveryScanner(anthropic_client, apify_client, airtable_client)
        result = await scanner.scan()
        # result["news_ideas"] contains 2-3 ideas from world news headlines
        # result["competitor_ideas"] contains 3-5 ideas from competitor top performers
    """

    # Competitor scanning config
    COMPETITOR_VPH_THRESHOLD = 50  # Min views per hour
    COMPETITOR_MAX_AGE_HOURS = 168  # 7 days
    COMPETITOR_MAX_IDEAS = 5  # Max competitor ideas to present

    def __init__(
        self,
        anthropic_client,
        apify_client=None,
        airtable_client=None,
        model: str = Models.CLAUDE_SONNET,
    ):
        """Initialize the discovery scanner.

        Args:
            anthropic_client: AnthropicClient instance for LLM calls
            apify_client: Optional ApifyYouTubeClient for competitor scraping
            airtable_client: Optional AirtableClient for competitor channels
            model: Model to use (Sonnet 4.5 for cost efficiency)
        """
        self.anthropic = anthropic_client
        self.apify = apify_client
        self.airtable = airtable_client
        self.model = model
        self.title_patterns = _load_title_patterns()
        self.system_prompt = _load_discovery_prompt()

    async def _gather_headlines(
        self,
        focus: Optional[str] = None,
    ) -> str:
        """Gather current headlines via web search.

        Uses the Anthropic web search tool to find real, current
        headlines rather than relying on training data.

        Args:
            focus: Optional niche keyword to focus the scan

        Returns:
            String containing gathered headlines
        """
        from shared.clients.anthropic_client import WEB_SEARCH_TOOL

        if focus:
            scan_prompt = f"""\
Search the web for current news about: {focus}

Find 10-15 real headlines from the past 48 hours related to this topic.
Search from sources like: {', '.join(SCAN_SOURCES['geopolitics'] + SCAN_SOURCES['finance'])}.

For each headline, include:
- The actual headline text
- The source publication
- The date published
- A 1-sentence summary with specific facts (numbers, names, dates)

Only return headlines you actually find via web search.
Do NOT fabricate headlines or sources.
If you find fewer than 10 results about this specific topic, that's fine —
return what you find. Do NOT pad with unrelated headlines.
"""
        else:
            scan_prompt = f"""\
Search the web for the most important current news headlines from the past 48 hours.

Cover these categories:
1. GEOPOLITICS: {', '.join(SCAN_SOURCES['geopolitics'])}
2. FINANCE: {', '.join(SCAN_SOURCES['finance'])}
3. ECONOMIC POLICY: {', '.join(SCAN_SOURCES['economic_policy'])}
4. TECH/BUSINESS: {', '.join(SCAN_SOURCES['tech_business'])}

For each headline, include:
- The actual headline text
- The source publication
- The date published
- A 1-sentence summary with specific facts (numbers, names, dates)

List 15-25 headlines total. Only return headlines you actually find
via web search. Do NOT fabricate headlines or sources.

Focus on stories with:
- Major power shifts between nations or institutions
- Economic policy changes with global implications
- Financial market disruptions or systemic risks
- Technology moves that shift power dynamics
- Trade wars, sanctions, or economic warfare

DO NOT include: celebrity news, sports, entertainment, or
purely domestic politics without global economic implications.
"""

        headlines = await self.anthropic.generate(
            prompt=scan_prompt,
            system_prompt=(
                "You are a financial and geopolitical news aggregator. "
                "Use web search to find real, current headlines. Be factual "
                "and specific — include numbers, names, and dates. "
                "Only report headlines you find via search."
            ),
            model=self.model,
            max_tokens=8000,
            temperature=0.3,
            tools=[WEB_SEARCH_TOOL],
        )

        return headlines

    async def _gather_competitor_winners(self) -> list[dict]:
        """Gather top-performing videos from competitor channels.

        Scrapes competitor channels via Apify and filters to winners
        (high VPH videos from the past 7 days).

        Returns:
            List of winner video dicts with: title, url, channel, views, vph
        """
        if not self.apify or not self.airtable:
            logger.info("Competitor scanning skipped (no apify/airtable client)")
            return []

        logger.info("Gathering competitor top performers...")

        # Get active channels from Airtable
        try:
            channels = self.airtable.get_active_competitor_channels()
        except Exception as e:
            logger.warning(f"Could not fetch competitor channels: {e}")
            return []

        if not channels:
            logger.info("No active competitor channels found")
            return []

        channel_urls = [
            c.get("Channel URL") for c in channels if c.get("Channel URL")
        ]
        logger.info(f"Scraping {len(channel_urls)} competitor channels...")

        # Scrape videos via Apify
        try:
            videos = await self.apify.scrape_channel_videos(
                channel_urls=channel_urls,
                max_videos_per_channel=10,
            )
        except Exception as e:
            logger.warning(f"Competitor scrape failed: {e}")
            return []

        # Calculate VPH and filter to winners
        winners = []
        for video in videos:
            vph, hours_old = calculate_vph(
                video.get("views", 0),
                video.get("published_at", ""),
            )
            video["vph"] = round(vph, 1)
            video["hours_old"] = round(hours_old, 1)

            # Apply filters
            if vph >= self.COMPETITOR_VPH_THRESHOLD and hours_old <= self.COMPETITOR_MAX_AGE_HOURS:
                winners.append(video)

        # Sort by VPH descending
        winners.sort(key=lambda v: v.get("vph", 0), reverse=True)

        logger.info(f"Found {len(winners)} competitor winners (VPH >= {self.COMPETITOR_VPH_THRESHOLD})")
        return winners

    async def _generate_competitor_ideas(self, winners: list[dict]) -> list[dict]:
        """Generate MF-formatted ideas from competitor winners.

        Takes top competitor videos and generates our own angle + MF titles,
        preserving the original title and URL for reference.

        Args:
            winners: List of high-VPH competitor videos

        Returns:
            List of idea dicts with title_options, original title, url, etc.
        """
        if not winners:
            return []

        # Limit to top performers
        top_winners = winners[:self.COMPETITOR_MAX_IDEAS]

        logger.info(f"Generating MF titles for {len(top_winners)} competitor videos...")

        # Build context for Claude
        winners_context = "\n".join(
            f"{i+1}. \"{v.get('title', '')}\" — {v.get('channel', '')} "
            f"({v.get('views', 0):,} views, {v.get('vph', 0):.0f} VPH)\n"
            f"   URL: {v.get('url', '')}"
            for i, v in enumerate(top_winners)
        )

        # Extract master formulas for the prompt
        master_formulas = self.title_patterns.get("master_formulas", [])
        if not master_formulas:
            master_formulas = self.title_patterns.get("formulas", [])
        formulas_summary = "\n".join(
            f"- {f['id']}: {f['name']} — Template: \"{f['template']}\""
            for f in master_formulas
        )

        prompt = f"""\
These are the TOP PERFORMING videos from competitor YouTube channels in the past 7 days.
For EACH video, create an Economy FastForward angle with 3 MF title options.

=== COMPETITOR TOP PERFORMERS ===
{winners_context}

=== TITLE FORMULA LIBRARY (MF system — use ONLY these) ===
{formulas_summary}

=== INSTRUCTIONS ===
For EACH competitor video above, generate:
1. Three title options using DIFFERENT MF formulas
2. A 2-word thumbnail verdict (ALL CAPS strategic judgment)
3. Our unique Machiavellian/power dynamics angle
4. A hook (first 15 seconds)
5. The best-fit analytical framework

TITLE RULES (STRICT):
- MAXIMUM 55 characters
- Start with "How" or "Why" (or MF-6 possessive format)
- First word after How/Why MUST be a proper noun
- NO "YOU" or "YOUR"
- NO ALL CAPS except acronyms

Return ONLY a JSON object with this structure:
{{
  "competitor_ideas": [
    {{
      "competitor_title": "The EXACT original competitor title",
      "competitor_channel": "Channel name",
      "competitor_url": "Video URL",
      "competitor_views": 123456,
      "competitor_vph": 500,
      "our_angle": "Our unique Machiavellian/power dynamics spin",
      "title_options": [
        {{
          "title": "How China Is Weaponizing Rare Earth Exports",
          "formula_id": "MF-0",
          "thumbnail_text": "CHOKE POINT",
          "score": 85
        }}
      ],
      "hook": "Opening 15 seconds creating curiosity gap",
      "framework": "One of: 48 Laws, Sun Tzu, Machiavelli, Thucydides Trap, etc.",
      "estimated_appeal": 8
    }}
  ]
}}

Generate ideas for ALL {len(top_winners)} videos. Raw JSON only, no markdown."""

        response = await self.anthropic.generate(
            prompt=prompt,
            system_prompt=self.system_prompt,
            model=self.model,
            max_tokens=6000,
            temperature=0.7,
        )

        # Parse response
        try:
            result = _parse_competitor_output(response)
            ideas = result.get("competitor_ideas", [])

            # Enrich with source data
            for i, idea in enumerate(ideas):
                idea["source_type"] = "competitor"
                # Map back to original winner data if available
                if i < len(top_winners):
                    winner = top_winners[i]
                    idea["competitor_url"] = idea.get("competitor_url") or winner.get("url", "")
                    idea["competitor_views"] = idea.get("competitor_views") or winner.get("views", 0)
                    idea["competitor_vph"] = idea.get("competitor_vph") or winner.get("vph", 0)
                    idea["competitor_channel"] = idea.get("competitor_channel") or winner.get("channel", "")
                    idea["competitor_title"] = idea.get("competitor_title") or winner.get("title", "")

            logger.info(f"Generated {len(ideas)} competitor ideas")
            return ideas

        except Exception as e:
            logger.warning(f"Failed to parse competitor ideas: {e}")
            return []

    async def scan(
        self,
        focus: Optional[str] = None,
        headlines: Optional[str] = None,
        include_competitors: bool = True,
    ) -> dict:
        """Run the full discovery scan (news + competitors).

        Gathers headlines AND competitor top performers, filters through the
        Machiavellian lens, and generates title variants for both.

        Args:
            focus: Optional niche keyword to focus the news scan
            headlines: Optional pre-gathered headlines (skips headline gathering)
            include_competitors: Whether to include competitor scanning (default True)

        Returns:
            Dict with:
              - "ideas": news headline ideas (2-3)
              - "competitor_ideas": competitor video ideas (3-5)
              - "_metadata": scan metadata
        """
        logger.info(
            f"Starting discovery scan"
            + (f" (focus: {focus})" if focus else "")
            + (" (with competitors)" if include_competitors else "")
        )

        # Run news headlines and competitor scraping in parallel
        tasks = []

        # Task 1: Gather and analyze news headlines
        async def _news_pipeline():
            nonlocal headlines
            if headlines is None:
                logger.info("Gathering current headlines...")
                headlines = await self._gather_headlines(focus)
                logger.info(f"Gathered {len(headlines.splitlines())} headline lines")

            analysis_prompt = _build_headline_scan_prompt(
                headlines=headlines,
                title_patterns=self.title_patterns,
                focus=focus,
            )
            logger.info("Analyzing headlines through Machiavellian lens...")
            response = await self.anthropic.generate(
                prompt=analysis_prompt,
                system_prompt=self.system_prompt,
                model=self.model,
                max_tokens=4000,
                temperature=0.7,
            )
            return _parse_scanner_output(response), headlines

        tasks.append(_news_pipeline())

        # Task 2: Gather and analyze competitor videos (if enabled)
        async def _competitor_pipeline():
            if not include_competitors:
                return []
            winners = await self._gather_competitor_winners()
            if not winners:
                return []
            return await self._generate_competitor_ideas(winners)

        tasks.append(_competitor_pipeline())

        # Run both in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process news results
        news_result, gathered_headlines = ({"ideas": []}, headlines)
        if not isinstance(results[0], Exception):
            news_result, gathered_headlines = results[0]
        else:
            logger.error(f"News pipeline failed: {results[0]}")

        # Process competitor results
        competitor_ideas = []
        if not isinstance(results[1], Exception):
            competitor_ideas = results[1]
        else:
            logger.error(f"Competitor pipeline failed: {results[1]}")

        # Mark news ideas with source type
        for idea in news_result.get("ideas", []):
            idea["source_type"] = "news"

        news_count = len(news_result.get("ideas", []))
        comp_count = len(competitor_ideas)
        logger.info(
            f"Discovery scan complete: {news_count} news ideas, {comp_count} competitor ideas"
        )

        # Build combined result
        result = {
            "ideas": news_result.get("ideas", []),
            "competitor_ideas": competitor_ideas,
            "_metadata": {
                "focus": focus,
                "model": self.model,
                "headline_count": len(gathered_headlines.splitlines()) if gathered_headlines else 0,
                "source_categories": list(SCAN_SOURCES.keys()),
                "competitor_ideas_count": comp_count,
                "include_competitors": include_competitors,
            },
        }

        return result


async def run_discovery(
    anthropic_client,
    apify_client=None,
    airtable_client=None,
    focus: Optional[str] = None,
    headlines: Optional[str] = None,
    include_competitors: bool = True,
    model: str = Models.CLAUDE_SONNET,
) -> dict:
    """Convenience function to run discovery scan (news + competitors).

    This is the main entry point for external callers (Slack bot, pipeline).

    Args:
        anthropic_client: AnthropicClient instance
        apify_client: Optional ApifyYouTubeClient for competitor scraping
        airtable_client: Optional AirtableClient for competitor channels
        focus: Optional niche keyword to focus the news scan
        headlines: Optional pre-gathered headlines
        include_competitors: Whether to include competitor top performers (default True)
        model: LLM model to use (default: Sonnet 4.5)

    Returns:
        Dict with:
          - "ideas": news headline ideas (2-3)
          - "competitor_ideas": competitor video ideas (3-5)
    """
    scanner = DiscoveryScanner(
        anthropic_client,
        apify_client=apify_client,
        airtable_client=airtable_client,
        model=model,
    )
    return await scanner.scan(
        focus=focus,
        headlines=headlines,
        include_competitors=include_competitors,
    )


def format_ideas_for_slack(result: dict) -> str:
    """Format discovery results as a readable Slack message.

    Shows two sections:
      1. NEWS IDEAS: From world headlines (2-3 ideas)
      2. COMPETITOR IDEAS: From competitor top performers (3-5 ideas)

    Each idea shows title options with emoji reactions for selection.

    Args:
        result: Output from DiscoveryScanner.scan()

    Returns:
        Formatted Slack message string
    """
    news_ideas = result.get("ideas", [])
    competitor_ideas = result.get("competitor_ideas", [])

    if not news_ideas and not competitor_ideas:
        return "No ideas found. Try running with a different focus keyword."

    # Letter emojis for A-Z options (extends beyond 9)
    letter_emojis = [
        "\U0001F1E6", "\U0001F1E7", "\U0001F1E8", "\U0001F1E9", "\U0001F1EA",  # A-E
        "\U0001F1EB", "\U0001F1EC", "\U0001F1ED", "\U0001F1EE", "\U0001F1EF",  # F-J
        "\U0001F1F0", "\U0001F1F1", "\U0001F1F2", "\U0001F1F3", "\U0001F1F4",  # K-O
        "\U0001F1F5", "\U0001F1F6", "\U0001F1F7", "\U0001F1F8", "\U0001F1F9",  # P-T
    ]

    lines = []
    option_num = 0  # Running count across ALL ideas (both sections)

    # === NEWS IDEAS SECTION ===
    if news_ideas:
        lines.append("*" + "=" * 40 + "*")
        lines.append("*NEWS IDEAS* (from world headlines)")
        lines.append("*" + "=" * 40 + "*\n")

        for i, idea in enumerate(news_ideas, 1):
            appeal = idea.get("estimated_appeal", "?")
            source = idea.get("headline_source", "Unknown source")

            lines.append(f"*--- News {i} ---* (Appeal: {appeal}/10)")
            lines.append(f"_{source}_\n")

            # Each title option gets its own selectable letter
            for j, title_opt in enumerate(idea.get("title_options", []), 1):
                if option_num < len(letter_emojis):
                    emoji = letter_emojis[option_num]
                else:
                    emoji = f"({option_num + 1})"
                formula_id = title_opt.get("formula_id", "?")
                title = title_opt.get("title", "Untitled")
                thumbnail = title_opt.get("thumbnail_text", "")
                lines.append(f"{emoji}  *{title}*")
                thumb_display = f" | {thumbnail}" if thumbnail else ""
                lines.append(f"      _Formula: {formula_id}{thumb_display}_")
                option_num += 1

            lines.append("")

            # Hook (truncated)
            hook = idea.get("hook", "")
            if hook:
                lines.append(f"  *Hook:* {hook[:150]}...")

            lines.append("\n" + "-" * 40 + "\n")

    # === COMPETITOR IDEAS SECTION ===
    if competitor_ideas:
        lines.append("*" + "=" * 40 + "*")
        lines.append("*COMPETITOR IDEAS* (proven performers)")
        lines.append("*" + "=" * 40 + "*\n")

        for i, idea in enumerate(competitor_ideas, 1):
            comp_title = idea.get("competitor_title", "Unknown")
            comp_channel = idea.get("competitor_channel", "?")
            comp_views = idea.get("competitor_views", 0)
            comp_vph = idea.get("competitor_vph", 0)
            comp_url = idea.get("competitor_url", "")
            appeal = idea.get("estimated_appeal", "?")

            lines.append(f"*--- Competitor {i} ---* (Appeal: {appeal}/10)")
            lines.append(f"_Original:_ \"{comp_title}\"")
            lines.append(f"_Channel:_ {comp_channel} | {comp_views:,} views | {comp_vph:.0f} VPH")
            if comp_url:
                lines.append(f"_Link:_ {comp_url}")
            lines.append("")

            # Our MF title options
            lines.append("*Our Angles:*")
            for j, title_opt in enumerate(idea.get("title_options", []), 1):
                if option_num < len(letter_emojis):
                    emoji = letter_emojis[option_num]
                else:
                    emoji = f"({option_num + 1})"
                formula_id = title_opt.get("formula_id", "?")
                title = title_opt.get("title", "Untitled")
                thumbnail = title_opt.get("thumbnail_text", "")
                lines.append(f"{emoji}  *{title}*")
                thumb_display = f" | {thumbnail}" if thumbnail else ""
                lines.append(f"      _Formula: {formula_id}{thumb_display}_")
                option_num += 1

            lines.append("")

            # Our angle
            angle = idea.get("our_angle", "")
            if angle:
                lines.append(f"  *Angle:* {angle[:150]}...")

            lines.append("\n" + "-" * 40 + "\n")

    # Instructions
    news_count = len(news_ideas)
    comp_count = len(competitor_ideas)
    lines.append(
        f"*{news_count} news ideas + {comp_count} competitor ideas*\n"
        f"Type a number (1-9) or letter (a-t) to pick your idea. "
        f"I'll auto-research it and queue it for the 12 PM pipeline run."
    )

    return "\n".join(lines)


def build_option_map(result: dict) -> list[dict]:
    """Build a flat list mapping option indices to idea + title combinations.

    Used by both the Slack bot and cron discovery to map emoji reactions
    to the correct idea + title combination. Handles both news and competitor ideas.

    Args:
        result: Full result dict from DiscoveryScanner.scan() with 'ideas' and 'competitor_ideas'

    Returns:
        List of dicts with 'idea_index', 'title_index', 'idea', 'title', 'source_type'
    """
    options = []

    # Process news ideas first
    news_ideas = result.get("ideas", [])
    for i, idea in enumerate(news_ideas):
        for j, title_opt in enumerate(idea.get("title_options", [])):
            options.append({
                "idea_index": i,
                "title_index": j,
                "idea": idea,
                "title": title_opt.get("title", "Untitled"),
                "formula_id": title_opt.get("formula_id", ""),
                "thumbnail_text": title_opt.get("thumbnail_text", ""),
                "source_type": "news",
            })

    # Process competitor ideas
    competitor_ideas = result.get("competitor_ideas", [])
    for i, idea in enumerate(competitor_ideas):
        for j, title_opt in enumerate(idea.get("title_options", [])):
            options.append({
                "idea_index": i,
                "title_index": j,
                "idea": idea,
                "title": title_opt.get("title", "Untitled"),
                "formula_id": title_opt.get("formula_id", ""),
                "thumbnail_text": title_opt.get("thumbnail_text", ""),
                "source_type": "competitor",
                "competitor_title": idea.get("competitor_title", ""),
                "competitor_url": idea.get("competitor_url", ""),
                "competitor_channel": idea.get("competitor_channel", ""),
            })

    return options


def infer_framework_angle(idea: dict) -> str:
    """Infer the best-fit analytical framework for a discovery idea.

    Maps story characteristics to one of the 10 framework options based on
    keywords and thematic signals in the angle, hook, and headline.
    """
    text = " ".join([
        idea.get("our_angle", ""),
        idea.get("hook", ""),
        idea.get("headline_source", ""),
        idea.get("historical_parallel_hint", ""),
    ]).lower()

    # Keyword-to-framework mapping (ordered by specificity)
    # Must match all 17 frameworks in script_generator._build_framework_lens_section()
    framework_signals = [
        ("48 Laws", ["law of power", "48 laws", "robert greene", "conceal",
                      "crush your enemy", "court power", "law 3", "law 15",
                      "power play", "power grab"]),
        ("Sun Tzu", ["art of war", "sun tzu", "military", "warfare",
                      "deception", "terrain", "flank", "siege",
                      "strategic retreat", "battle"]),
        ("Machiavelli", ["machiavelli", "the prince", "prince", "virtù",
                          "fortuna", "feared or loved", "fox and lion",
                          "principality", "sovereignty"]),
        ("Thucydides Trap", ["thucydides", "rising power", "established power",
                              "security dilemma", "power transition",
                              "athens and sparta", "inevitable conflict",
                              "graham allison", "hegemonic war", "challenger"]),
        ("Antifragile", ["antifragile", "black swan", "nassim taleb", "taleb",
                          "fragility", "tail risk", "skin in the game",
                          "barbell strategy", "fat tail", "lindy effect"]),
        ("Grand Chessboard", ["brzezinski", "grand chessboard", "mackinder",
                               "heartland", "rimland", "spykman", "pivot state",
                               "chokepoint", "strait of hormuz", "eurasia"]),
        ("Kindleberger Trap", ["kindleberger", "hegemonic stability", "public goods",
                                "power vacuum", "stabilizer", "reserve currency",
                                "dollar weaponization", "bretton woods"]),
        ("Schelling", ["schelling", "focal point", "brinkmanship", "credible threat",
                        "commitment device", "red line", "escalation dominance",
                        "deterrence", "coercive diplomacy"]),
        ("Collective Action", ["collective action", "mancur olson", "free rider",
                                "concentrated benefits", "diffuse costs", "lobbying",
                                "regulatory capture", "cartel", "special interest"]),
        ("Soft Power", ["soft power", "joseph nye", "sharp power", "cultural hegemony",
                         "gramsci", "influence operation", "confucius institute",
                         "smart power", "cultural dominance"]),
        ("Game Theory", ["game theory", "nash equilibrium", "prisoner",
                          "dilemma", "zero-sum", "incentive", "payoff",
                          "dominant strategy", "tit for tat"]),
        ("Jung Shadow", ["shadow", "jung", "unconscious", "projection",
                          "persona", "archetype", "collective unconscious"]),
        ("Behavioral Econ", ["behavioral", "loss aversion", "anchoring",
                              "sunk cost", "nudge", "kahneman", "bias",
                              "irrational", "heuristic"]),
        ("Stoicism", ["stoic", "marcus aurelius", "seneca", "epictetus",
                       "control", "fate", "virtue", "endure"]),
        ("Propaganda", ["propaganda", "bernays", "chomsky", "manufacturing consent",
                         "media", "narrative control", "information war",
                         "censorship", "perception management"]),
        ("Systems Thinking", ["system", "feedback loop", "second-order",
                               "unintended consequences", "complexity",
                               "emergent", "cascade", "interconnected"]),
        ("Evolutionary Psych", ["evolutionary", "tribal", "dominance hierarchy",
                                 "in-group", "out-group", "status", "instinct",
                                 "survival", "primal"]),
    ]

    # Score each framework
    best_framework = "48 Laws"  # default fallback
    best_score = 0

    for framework, keywords in framework_signals:
        score = sum(1 for kw in keywords if kw in text)
        if score > best_score:
            best_score = score
            best_framework = framework

    # If no strong signal, use heuristic based on story type
    if best_score == 0:
        if any(w in text for w in ["corporate", "company", "ceo", "merger", "monopoly"]):
            best_framework = "48 Laws"
        elif any(w in text for w in ["china", "beijing", "superpower", "rival", "overtake"]):
            best_framework = "Thucydides Trap"
        elif any(w in text for w in ["sanction", "tariff", "trade war", "embargo"]):
            best_framework = "Game Theory"
        elif any(w in text for w in ["currency", "dollar", "debt", "inflation", "fed"]):
            best_framework = "Systems Thinking"
        elif any(w in text for w in ["army", "nato", "defense", "missile", "nuclear"]):
            best_framework = "Sun Tzu"
        elif any(w in text for w in ["strait", "canal", "pipeline", "arctic", "corridor"]):
            best_framework = "Grand Chessboard"
        elif any(w in text for w in ["lobby", "regulation", "subsidy", "bail"]):
            best_framework = "Collective Action"

    return best_framework


def build_idea_record_from_discovery(
    idea: dict,
    idea_number: int = 1,
    title_override: str = "",
    thumbnail_text_override: str = "",
    source_type: str = "news",
) -> dict:
    """Build a full Airtable record from a discovery scanner idea.

    Maps all discovery fields to the rich Idea Concepts schema including
    Framework Angle, scores, Source URLs, and more.

    Uses the title scoring system to pick the best title from the options
    (highest score wins, falling back to first option if no scores).

    Handles both news ideas (from headlines) and competitor ideas (from YouTube).

    Args:
        idea: Single idea dict from discovery scanner output
        idea_number: Which idea was selected
        title_override: If set, use this title instead of auto-selecting
        thumbnail_text_override: If set, use this thumbnail text instead of auto-selecting
        source_type: "news" or "competitor" to indicate idea source

    Returns:
        Dict ready for AirtableClient.create_idea()
    """
    # Pick the best title from title_options (highest score, or first)
    title_options = idea.get("title_options", [])
    best_title = ""
    best_thumbnail = ""
    if title_options:
        # Sort by score if available, pick highest
        scored_options = [t for t in title_options if t.get("score")]
        if scored_options:
            scored_options.sort(key=lambda t: t.get("score", 0), reverse=True)
            best_title = scored_options[0].get("title", "")
            best_thumbnail = scored_options[0].get("thumbnail_text", "")
        else:
            best_title = title_options[0].get("title", "")
            best_thumbnail = title_options[0].get("thumbnail_text", "")

    # Apply overrides
    if title_override:
        best_title = title_override
    if thumbnail_text_override:
        best_thumbnail = thumbnail_text_override

    # Extract appeal scores
    appeal_breakdown = idea.get("appeal_breakdown", {})

    # Handle different source types
    is_competitor = source_type == "competitor" or idea.get("source_type") == "competitor"

    if is_competitor:
        # Competitor idea - use competitor fields
        headline_source = idea.get("competitor_title", "")
        source_urls = idea.get("competitor_url", "")
        reference_url = idea.get("competitor_url", "")
        source_channel = idea.get("competitor_channel", "")
        source_views = idea.get("competitor_views", 0)
        source_vph = idea.get("competitor_vph", 0)
        dna_source = "competitor_scanner"
    else:
        # News idea - use headline fields
        headline_source = idea.get("headline_source", "")
        source_urls = headline_source
        reference_url = ""
        source_channel = ""
        source_views = 0
        source_vph = 0
        dna_source = "discovery_scanner"

    # Extract narrative fields using shared helper
    narrative = extract_narrative_fields_from_concept(idea)
    # Fallback: if our_angle exists but present_parallel is empty, use our_angle
    if not narrative["present_parallel"] and idea.get("our_angle"):
        narrative["present_parallel"] = idea.get("our_angle", "")
    # Fallback: if historical_parallel_hint exists but past_context empty, use hint
    if not narrative["past_context"] and idea.get("historical_parallel_hint"):
        narrative["past_context"] = idea.get("historical_parallel_hint", "")

    record = {
        "viral_title": best_title or f"Discovery Idea {idea_number}",
        "hook_script": idea.get("hook", ""),
        "writer_guidance": idea.get("our_angle", ""),
        "narrative_logic": narrative,
        # Rich schema fields
        IdeaFields.FRAMEWORK_ANGLE: idea.get("framework") or infer_framework_angle(idea),
        IdeaFields.HEADLINE: headline_source.split(" — ")[0] if " — " in headline_source else headline_source,
        "Timeliness Score": min(10, max(1, idea.get("estimated_appeal", 7))),
        "Audience Fit Score": min(10, max(1, appeal_breakdown.get("emotional_trigger", 7))),
        "Content Gap Score": min(10, max(1, appeal_breakdown.get("hidden_system", 7))),
        IdeaFields.SOURCE_URLS: source_urls,
        IdeaFields.EXECUTIVE_HOOK: idea.get("hook", ""),
        IdeaFields.THESIS: idea.get("our_angle", ""),
        "Date Surfaced": date.today().isoformat(),
        # Thumbnail text for yin-yang overlay (independent from title)
        IdeaFields.THUMBNAIL_TEXT: best_thumbnail,
        # Title Candidates — full JSON array of all title options with scores
        "Title Candidates": json.dumps(title_options) if title_options else "",
        # Store full discovery data as Original DNA for downstream use
        "original_dna": json.dumps({
            "source": dna_source,
            "idea_number": idea_number,
            "title_options": title_options,
            "appeal_breakdown": appeal_breakdown,
            "historical_parallel_hint": idea.get("historical_parallel_hint", ""),
            "headline_source": headline_source,
            # Competitor-specific fields
            "competitor_title": idea.get("competitor_title", "") if is_competitor else "",
            "competitor_url": idea.get("competitor_url", "") if is_competitor else "",
            "competitor_channel": idea.get("competitor_channel", "") if is_competitor else "",
            "competitor_views": source_views,
            "competitor_vph": source_vph,
        }),
    }

    # Add reference URL for competitor ideas
    if reference_url:
        record["reference_url"] = reference_url

    # Add source channel and views for competitor ideas
    if is_competitor:
        record["Source Channel"] = source_channel
        record["Source Views"] = source_views

    return record


def format_ideas_for_json(result: dict) -> str:
    """Format discovery results as pretty-printed JSON.

    Args:
        result: Output from DiscoveryScanner.scan()

    Returns:
        Pretty-printed JSON string
    """
    return json.dumps(result, indent=2)


# === CLI Entry Point ===

async def _cli_main():
    """CLI entry point for standalone discovery scanner."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Economy FastForward Discovery Scanner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  python discovery_scanner.py
  python discovery_scanner.py --focus "BRICS currency"
  python discovery_scanner.py --output discoveries.json
  python discovery_scanner.py --focus "sanctions" --output discoveries.json
""",
    )
    parser.add_argument(
        "--focus",
        help="Optional niche keyword to focus the scan",
    )
    parser.add_argument(
        "--output",
        help="Output file path (default: stdout as JSON)",
    )
    parser.add_argument(
        "--model",
        default=Models.CLAUDE_SONNET,
        help="Model to use (default: claude-sonnet-4-5-20250929)",
    )
    parser.add_argument(
        "--slack-format",
        action="store_true",
        help="Output in Slack message format instead of JSON",
    )

    args = parser.parse_args()

    # Load environment
    from dotenv import load_dotenv
    load_dotenv()

    from shared.clients.anthropic_client import AnthropicClient

    anthropic = AnthropicClient()

    print(f"\n{'=' * 60}")
    print(f"DISCOVERY SCANNER — Headline Analysis")
    print(f"{'=' * 60}")
    if args.focus:
        print(f"Focus: {args.focus}")
    print(f"Model: {args.model}")
    print(f"{'=' * 60}\n")

    result = await run_discovery(
        anthropic_client=anthropic,
        focus=args.focus,
        model=args.model,
    )

    # Format output
    if args.slack_format:
        output = format_ideas_for_slack(result)
    else:
        output = format_ideas_for_json(result)

    if args.output:
        Path(args.output).write_text(output)
        idea_count = len(result.get("ideas", []))
        print(f"\n{idea_count} ideas saved to: {args.output}")
    else:
        print(output)

    print(f"\n{'=' * 60}")
    print("Discovery scan complete.")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(_cli_main())
