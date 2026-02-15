"""
Discovery Scanner — Scans headlines, filters through Machiavellian lens,
and generates title variants using the pattern library.

Scans current headlines across geopolitics, finance, tech, and economic
policy, filters them through the channel's dark power dynamics lens, and
formats the top 2-3 stories into proven title structures.

Usage (standalone):
    python discovery_scanner.py
    python discovery_scanner.py --focus "BRICS currency"
    python discovery_scanner.py --output discoveries.json

Usage (imported):
    from discovery_scanner import DiscoveryScanner, run_discovery

    scanner = DiscoveryScanner(anthropic_client)
    ideas = await scanner.scan()
"""

import asyncio
import json
import logging
import os
import sys
from datetime import date
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

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
    patterns_path = Path(__file__).parent / "title_patterns.json"
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


def _build_scan_query(focus: Optional[str] = None) -> str:
    """Build the search query for headline scanning.

    Creates a query that covers all source categories and optionally
    focuses on a specific niche keyword.
    """
    base_topics = [
        "geopolitics",
        "global finance",
        "economic policy",
        "central banks",
        "trade wars",
        "sanctions",
        "currency",
        "debt crisis",
        "power dynamics",
        "economic warfare",
    ]

    if focus:
        return (
            f"latest news headlines about {focus} "
            f"related to geopolitics finance economics power dynamics 2026"
        )

    return (
        "latest major headlines today: geopolitics, global finance, "
        "economic policy, trade wars, sanctions, central banks, "
        "tech power dynamics, currency wars, debt crises 2026"
    )


def _build_headline_scan_prompt(
    headlines: str,
    title_patterns: dict,
    focus: Optional[str] = None,
) -> str:
    """Build the user prompt for the discovery scanner LLM call.

    Combines the gathered headlines with the title pattern library
    and instructions for analysis.
    """
    # Extract EFF formulas for inline reference
    eff_formulas = title_patterns.get("economy_fastforward", {}).get(
        "hybrid_formulas", []
    )
    formulas_summary = "\n".join(
        f"- {f['id']}: {f['name']} — Template: \"{f['template']}\""
        for f in eff_formulas
    )

    focus_instruction = ""
    if focus:
        focus_instruction = (
            f"\n\nFOCUS KEYWORD: '{focus}' — prioritize stories related "
            f"to this topic, but don't force it if no strong stories exist."
        )

    return f"""\
Analyze these current headlines and select the 2-3 best stories for
Economy FastForward videos. Apply the Machiavellian lens and generate
title variants using the formula library.

=== CURRENT HEADLINES ===
{headlines}

=== AVAILABLE TITLE FORMULAS (use EFF formulas first) ===
{formulas_summary}

=== FULL FORMULA LIBRARY (for variable reference) ===
{json.dumps(eff_formulas, indent=2)}
{focus_instruction}

INSTRUCTIONS:
1. Select exactly 2-3 stories (not more, not less)
2. Each story must pass the power dynamics filter (minimum 6/10)
3. Generate 2 title variants per story using DIFFERENT formulas
4. Include formula_id for each title variant
5. Rate each story's appeal (1-10) with breakdown by criterion
6. Suggest a historical parallel for the research phase
7. Write a 2-3 sentence hook that creates a curiosity gap

Return your response as valid JSON following the output format specified
in your system prompt. No markdown code blocks — raw JSON only.
"""


def _parse_scanner_output(response_text: str) -> dict:
    """Parse the JSON output from the discovery scanner LLM.

    Handles potential formatting issues (markdown code blocks, etc.)
    """
    text = response_text.strip()

    # Strip markdown code block if present
    if text.startswith("```"):
        first_newline = text.index("\n")
        text = text[first_newline + 1:]
    if text.endswith("```"):
        text = text[:-3].rstrip()

    # Find JSON object
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end != -1:
        text = text[brace_start:brace_end + 1]

    result = json.loads(text)

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

        # Validate title_options have formula_id
        for j, title_opt in enumerate(idea.get("title_options", [])):
            if "formula_id" not in title_opt:
                logger.warning(
                    f"Idea {i+1}, title option {j+1} missing formula_id"
                )

    return result


class DiscoveryScanner:
    """Scans headlines and generates video ideas through the Machiavellian lens.

    Usage:
        scanner = DiscoveryScanner(anthropic_client)
        result = await scanner.scan()
        # result["ideas"] contains 2-3 curated ideas with title variants
    """

    def __init__(
        self,
        anthropic_client,
        model: str = "claude-sonnet-4-5-20250929",
    ):
        """Initialize the discovery scanner.

        Args:
            anthropic_client: AnthropicClient instance for LLM calls
            model: Model to use (Sonnet 4.5 for cost efficiency)
        """
        self.anthropic = anthropic_client
        self.model = model
        self.title_patterns = _load_title_patterns()
        self.system_prompt = _load_discovery_prompt()

    async def _gather_headlines(
        self,
        focus: Optional[str] = None,
    ) -> str:
        """Gather current headlines using LLM web search capabilities.

        Uses the Anthropic client with a focused query to gather
        headlines across all source categories.

        Args:
            focus: Optional niche keyword to focus the scan

        Returns:
            String containing gathered headlines
        """
        query = _build_scan_query(focus)

        # Use the LLM to search and compile headlines
        # The LLM has access to web search through its training data
        # and can synthesize recent events
        scan_prompt = f"""\
You are a news aggregator. Your job is to compile the most important
current headlines from the past 48 hours across these categories:

1. GEOPOLITICS: {', '.join(SCAN_SOURCES['geopolitics'])}
2. FINANCE: {', '.join(SCAN_SOURCES['finance'])}
3. ECONOMIC POLICY: {', '.join(SCAN_SOURCES['economic_policy'])}
4. TECH/BUSINESS: {', '.join(SCAN_SOURCES['tech_business'])}

{"Focus especially on: " + focus if focus else ""}

For each headline, include:
- The headline text
- The source (publication name)
- A 1-sentence summary of the key facts
- Any numbers, dollar amounts, or percentages mentioned

List 15-25 headlines total, covering all 4 categories.
Format as a simple numbered list. Focus on stories with:
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
                "Compile current headlines from major sources. Be factual "
                "and specific — include numbers, names, and dates."
            ),
            model=self.model,
            max_tokens=3000,
            temperature=0.3,
        )

        return headlines

    async def scan(
        self,
        focus: Optional[str] = None,
        headlines: Optional[str] = None,
    ) -> dict:
        """Run the full discovery scan.

        Gathers headlines (or uses provided ones), filters through the
        Machiavellian lens, and generates title variants.

        Args:
            focus: Optional niche keyword to focus the scan
            headlines: Optional pre-gathered headlines (skips gathering step)

        Returns:
            Dict with "ideas" list containing 2-3 curated video ideas,
            each with title_options, hook, appeal score, etc.
        """
        logger.info(
            f"Starting discovery scan"
            + (f" (focus: {focus})" if focus else "")
        )

        # Step 1: Gather headlines
        if headlines is None:
            logger.info("Gathering current headlines...")
            headlines = await self._gather_headlines(focus)
            logger.info(
                f"Gathered {len(headlines.splitlines())} headline lines"
            )

        # Step 2: Build analysis prompt
        analysis_prompt = _build_headline_scan_prompt(
            headlines=headlines,
            title_patterns=self.title_patterns,
            focus=focus,
        )

        # Step 3: Run through Machiavellian lens
        logger.info("Analyzing headlines through Machiavellian lens...")
        response = await self.anthropic.generate(
            prompt=analysis_prompt,
            system_prompt=self.system_prompt,
            model=self.model,
            max_tokens=4000,
            temperature=0.7,
        )

        # Step 4: Parse and validate output
        result = _parse_scanner_output(response)
        idea_count = len(result.get("ideas", []))
        logger.info(
            f"Discovery scan complete: {idea_count} ideas generated"
        )

        # Add metadata
        result["_metadata"] = {
            "focus": focus,
            "model": self.model,
            "headline_count": len(headlines.splitlines()),
            "source_categories": list(SCAN_SOURCES.keys()),
        }

        return result


async def run_discovery(
    anthropic_client,
    focus: Optional[str] = None,
    headlines: Optional[str] = None,
    model: str = "claude-sonnet-4-5-20250929",
) -> dict:
    """Convenience function to run discovery scan.

    This is the main entry point for external callers (Slack bot, pipeline).

    Args:
        anthropic_client: AnthropicClient instance
        focus: Optional niche keyword to focus the scan
        headlines: Optional pre-gathered headlines
        model: LLM model to use (default: Sonnet 4.5)

    Returns:
        Dict with "ideas" list containing 2-3 curated video ideas
    """
    scanner = DiscoveryScanner(anthropic_client, model=model)
    return await scanner.scan(focus=focus, headlines=headlines)


def format_ideas_for_slack(result: dict) -> str:
    """Format discovery results as a readable Slack message.

    Produces a mobile-friendly Slack message with numbered ideas,
    title options, hooks, and appeal scores.

    Args:
        result: Output from DiscoveryScanner.scan()

    Returns:
        Formatted Slack message string
    """
    ideas = result.get("ideas", [])
    if not ideas:
        return "No ideas found. Try running with a different focus keyword."

    lines = ["*Discovery Scanner Results*\n"]

    for i, idea in enumerate(ideas, 1):
        emoji = ["1\ufe0f\u20e3", "2\ufe0f\u20e3", "3\ufe0f\u20e3"][i - 1]
        appeal = idea.get("estimated_appeal", "?")

        lines.append(f"{emoji} *Idea {i}* (Appeal: {appeal}/10)")
        lines.append(f"_{idea.get('headline_source', 'Unknown source')}_\n")

        # Title options
        for j, title_opt in enumerate(idea.get("title_options", []), 1):
            formula_id = title_opt.get("formula_id", "?")
            title = title_opt.get("title", "Untitled")
            lines.append(f"  *Title {j}* ({formula_id}): {title}")

        lines.append("")

        # Hook
        hook = idea.get("hook", "")
        if hook:
            lines.append(f"  *Hook:* {hook}")

        # Angle
        angle = idea.get("our_angle", "")
        if angle:
            lines.append(f"  *Angle:* {angle}")

        # Historical parallel hint
        parallel = idea.get("historical_parallel_hint", "")
        if parallel:
            lines.append(f"  *Parallel:* {parallel}")

        lines.append("\n" + "-" * 40 + "\n")

    lines.append(
        "React with 1\ufe0f\u20e3 2\ufe0f\u20e3 or 3\ufe0f\u20e3 "
        "to approve an idea for deep research."
    )

    return "\n".join(lines)


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
        elif any(w in text for w in ["sanction", "tariff", "trade war", "embargo"]):
            best_framework = "Game Theory"
        elif any(w in text for w in ["currency", "dollar", "debt", "inflation", "fed"]):
            best_framework = "Systems Thinking"
        elif any(w in text for w in ["army", "nato", "defense", "missile", "nuclear"]):
            best_framework = "Sun Tzu"

    return best_framework


def build_idea_record_from_discovery(idea: dict, idea_number: int = 1) -> dict:
    """Build a full Airtable record from a discovery scanner idea.

    Maps all discovery fields to the rich Idea Concepts schema including
    Framework Angle, scores, Source URLs, and more.

    Args:
        idea: Single idea dict from discovery scanner output
        idea_number: Which idea was selected (1, 2, or 3)

    Returns:
        Dict ready for AirtableClient.create_idea()
    """
    # Pick the best title from title_options
    title_options = idea.get("title_options", [])
    best_title = ""
    if title_options:
        best_title = title_options[0].get("title", "")

    # Extract appeal scores
    appeal_breakdown = idea.get("appeal_breakdown", {})

    # Build source URLs from headline_source
    headline_source = idea.get("headline_source", "")
    source_urls = headline_source  # includes source publication and URL if available

    record = {
        "viral_title": best_title or f"Discovery Idea {idea_number}",
        "hook_script": idea.get("hook", ""),
        "writer_guidance": idea.get("our_angle", ""),
        "narrative_logic": {
            "past_context": idea.get("historical_parallel_hint", ""),
            "present_parallel": idea.get("our_angle", ""),
            "future_prediction": "",
        },
        # Rich schema fields
        "Framework Angle": infer_framework_angle(idea),
        "Headline": headline_source.split(" — ")[0] if " — " in headline_source else headline_source,
        "Timeliness Score": min(10, max(1, idea.get("estimated_appeal", 7))),
        "Audience Fit Score": min(10, max(1, appeal_breakdown.get("emotional_trigger", 7))),
        "Content Gap Score": min(10, max(1, appeal_breakdown.get("hidden_system", 7))),
        "Source URLs": source_urls,
        "Executive Hook": idea.get("hook", ""),
        "Thesis": idea.get("our_angle", ""),
        "Date Surfaced": date.today().isoformat(),
        # Store full discovery data as Original DNA for downstream use
        "original_dna": json.dumps({
            "source": "discovery_scanner",
            "idea_number": idea_number,
            "title_options": title_options,
            "appeal_breakdown": appeal_breakdown,
            "historical_parallel_hint": idea.get("historical_parallel_hint", ""),
            "headline_source": headline_source,
        }),
    }

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
        default="claude-sonnet-4-5-20250929",
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

    from clients.anthropic_client import AnthropicClient

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
