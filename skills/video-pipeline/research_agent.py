"""
Research Agent — Standalone deep research module for Economy FastForward.

Performs deep thematic research on a topic and produces a structured
research_payload that feeds directly into the brief_translator pipeline.

This module was extracted during Pipeline Unification (Story 0) to serve
as the single source of deep research for all video ideas.

Usage (standalone):
    python research_agent.py --topic "Why the US Dollar Could Collapse by 2030"

Usage (imported):
    from research_agent import ResearchAgent, run_research

    agent = ResearchAgent(anthropic_client)
    payload = await agent.research("Why the US Dollar Could Collapse by 2030")
"""

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Research prompt template
RESEARCH_SYSTEM_PROMPT = """\
You are a deep research analyst for Economy FastForward, a documentary-style
YouTube channel covering economics, finance, geopolitics, and power dynamics.

Your job is to conduct exhaustive research on a topic and produce a structured
research brief that will be used to write a 25-minute narration script with
~140 AI-generated images.

The research must be DEEP — not surface-level summaries. You are producing the
intellectual foundation for a video that will be watched by hundreds of thousands
of people. Every fact must be specific, every parallel must be illuminating,
every angle must hook the viewer."""

RESEARCH_PROMPT_TEMPLATE = """\
Research the following topic in depth:

<topic>{TOPIC}</topic>

{SEED_URLS_SECTION}
{CONTEXT_SECTION}

Produce a structured research brief with ALL of the following sections.
Each section should be substantial (200-500 words). Do not skip any section.

Respond in the following JSON format (no markdown code blocks, just raw JSON):

{{
  "headline": "A compelling, specific video title (not generic)",
  "thesis": "The core argument or revelation of this video in 2-3 sentences",
  "executive_hook": "The opening 15-second hook that stops the scroll. Must create immediate curiosity gap.",
  "fact_sheet": "Detailed facts, statistics, data points, and verifiable claims. Include specific numbers, dates, dollar amounts, percentages. At least 10 distinct facts.",
  "historical_parallels": "Historical events that mirror or illuminate this topic. Include specific dates, figures, and outcomes. At least 3 distinct parallels with rich detail.",
  "framework_analysis": "The analytical framework for understanding this topic. What mental model explains why this is happening? Reference specific thinkers, theories, or frameworks (e.g., Machiavellian power dynamics, game theory, systems thinking).",
  "character_dossier": "Key figures involved. For each: name, role, specific actions taken, motivations, and visual description for imagery. At least 3 figures.",
  "narrative_arc": "The story structure: What happened → Why it matters → What comes next. Include specific turning points and revelations.",
  "counter_arguments": "The strongest arguments against the thesis. Acknowledge them honestly, then explain why the thesis still holds.",
  "visual_seeds": "Specific visual concepts for AI image generation. Describe scenes, settings, objects, and moods. At least 5 distinct visual concepts.",
  "source_bibliography": "Key sources, reports, and references used. Include organization names, report titles, and dates where possible.",
  "themes": "Thematic frameworks that give the video intellectual depth (e.g., 'Machiavellian power dynamics', 'technological disruption cycle', 'wealth inequality feedback loop'). At least 3 themes.",
  "psychological_angles": "Viewer hooks and emotional triggers. What makes this personally relevant to the audience? What fears, aspirations, or curiosities does it tap into?",
  "narrative_arc_suggestion": "Recommended 6-act structure with brief description of each act's focus and emotional arc.",
  "title_options": "3 alternative viral-worthy video titles, each on a new line",
  "thumbnail_concepts": "2-3 thumbnail visual concepts following the Problem→Payoff split composition"
}}

IMPORTANT:
- Every fact must be SPECIFIC (names, numbers, dates) — no vague generalizations
- Historical parallels must be ILLUMINATING, not just tangentially related
- The framework must feel like an intellectual revelation, not a textbook summary
- Visual seeds must describe SCENES, not abstract concepts
- The hook must create an irresistible curiosity gap in under 15 seconds of speech
"""


def _build_research_prompt(
    topic: str,
    seed_urls: Optional[list[str]] = None,
    context: Optional[str] = None,
) -> str:
    """Build the research prompt with optional seed URLs and context."""
    seed_section = ""
    if seed_urls:
        urls_text = "\n".join(f"- {url}" for url in seed_urls)
        seed_section = f"Use these URLs as starting points for research:\n{urls_text}"

    context_section = ""
    if context:
        context_section = f"Additional context:\n{context}"

    return RESEARCH_PROMPT_TEMPLATE.format(
        TOPIC=topic,
        SEED_URLS_SECTION=seed_section,
        CONTEXT_SECTION=context_section,
    )


def _parse_research_payload(response_text: str) -> dict:
    """Parse the JSON research payload from Claude's response.

    Handles potential formatting issues (markdown code blocks, etc.)
    """
    text = response_text.strip()

    # Strip markdown code block if present
    if text.startswith("```"):
        # Remove opening ```json or ```
        first_newline = text.index("\n")
        text = text[first_newline + 1:]
    if text.endswith("```"):
        text = text[:-3].rstrip()

    # Try to find JSON object
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end != -1:
        text = text[brace_start:brace_end + 1]

    payload = json.loads(text)

    # Validate required fields
    required_fields = [
        "headline", "thesis", "executive_hook", "fact_sheet",
        "historical_parallels", "framework_analysis", "character_dossier",
        "narrative_arc", "counter_arguments", "visual_seeds",
        "source_bibliography",
    ]

    missing = [f for f in required_fields if not payload.get(f)]
    if missing:
        logger.warning(f"Research payload missing fields: {missing}")

    return payload


class ResearchAgent:
    """Standalone deep research agent for video production.

    Produces structured research_payload objects that feed into the
    brief_translator pipeline.

    Usage:
        agent = ResearchAgent(anthropic_client)
        payload = await agent.research("Topic here")
    """

    def __init__(
        self,
        anthropic_client,
        model: str = "claude-sonnet-4-5-20250929",
    ):
        """Initialize the research agent.

        Args:
            anthropic_client: AnthropicClient instance for LLM calls
            model: Model to use for research (Sonnet for cost, Opus for depth)
        """
        self.anthropic = anthropic_client
        self.model = model

    async def research(
        self,
        topic: str,
        seed_urls: Optional[list[str]] = None,
        context: Optional[str] = None,
    ) -> dict:
        """Run deep research on a topic.

        Args:
            topic: The topic or idea to research
            seed_urls: Optional list of URLs to seed research
            context: Optional additional context

        Returns:
            Structured research_payload dict containing:
                - headline (str)
                - thesis (str)
                - executive_hook (str)
                - fact_sheet (str)
                - historical_parallels (str)
                - framework_analysis (str)
                - character_dossier (str)
                - narrative_arc (str)
                - counter_arguments (str)
                - visual_seeds (str)
                - source_bibliography (str)
                - themes (str)
                - psychological_angles (str)
                - narrative_arc_suggestion (str)
                - title_options (str)
                - thumbnail_concepts (str)
        """
        logger.info(f"Starting deep research on: {topic}")

        prompt = _build_research_prompt(topic, seed_urls, context)

        response = await self.anthropic.generate(
            prompt=prompt,
            system_prompt=RESEARCH_SYSTEM_PROMPT,
            model=self.model,
            max_tokens=8000,
            temperature=0.7,
        )

        payload = _parse_research_payload(response)
        logger.info(
            f"Research complete: {payload.get('headline', 'Untitled')} — "
            f"{len(payload)} fields populated"
        )

        return payload


async def run_research(
    anthropic_client,
    topic: str,
    seed_urls: Optional[list[str]] = None,
    context: Optional[str] = None,
    model: str = "claude-sonnet-4-5-20250929",
) -> dict:
    """Convenience function to run deep research.

    This is the main entry point for external callers.

    Args:
        anthropic_client: AnthropicClient instance
        topic: Topic to research
        seed_urls: Optional seed URLs
        context: Optional context
        model: LLM model to use

    Returns:
        Structured research_payload dict
    """
    agent = ResearchAgent(anthropic_client, model=model)
    return await agent.research(topic, seed_urls, context)


# === CLI Entry Point ===

async def _cli_main():
    """CLI entry point for standalone research agent testing."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Economy FastForward Deep Research Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  python research_agent.py --topic "Why the US Dollar Could Collapse by 2030"
  python research_agent.py --topic "AI replacing jobs" --urls "https://example.com/report"
  python research_agent.py --topic "Federal Reserve rate cuts" --output research.json
""",
    )
    parser.add_argument(
        "--topic",
        required=True,
        help="The topic to research",
    )
    parser.add_argument(
        "--urls",
        nargs="*",
        help="Optional seed URLs for research",
    )
    parser.add_argument(
        "--context",
        help="Optional additional context",
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

    args = parser.parse_args()

    # Load environment
    from dotenv import load_dotenv
    load_dotenv()

    from clients.anthropic_client import AnthropicClient

    anthropic = AnthropicClient()

    print(f"\n{'=' * 60}")
    print(f"RESEARCH AGENT — Deep Research")
    print(f"{'=' * 60}")
    print(f"Topic: {args.topic}")
    if args.urls:
        print(f"Seed URLs: {args.urls}")
    print(f"Model: {args.model}")
    print(f"{'=' * 60}\n")

    payload = await run_research(
        anthropic_client=anthropic,
        topic=args.topic,
        seed_urls=args.urls,
        context=args.context,
        model=args.model,
    )

    output_json = json.dumps(payload, indent=2)

    if args.output:
        Path(args.output).write_text(output_json)
        print(f"\n✅ Research saved to: {args.output}")
        print(f"   Headline: {payload.get('headline', 'N/A')}")
        print(f"   Fields: {len(payload)}")
    else:
        print(output_json)

    print(f"\n{'=' * 60}")
    print("Research complete.")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(_cli_main())
