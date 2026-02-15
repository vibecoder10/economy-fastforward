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


def _repair_json(text: str) -> str:
    """Attempt to repair truncated or malformed JSON.

    Common issues from LLM output:
    - Unterminated strings (truncation mid-value)
    - Trailing commas before closing braces
    - Missing closing braces/brackets
    """
    import re as _re

    # Step 1: Close any unterminated string
    # Walk through tracking quote state
    in_string = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == '\\' and in_string:
            i += 2  # skip escaped char
            continue
        if ch == '"':
            in_string = not in_string
        i += 1

    if in_string:
        # We're inside an unterminated string — close it
        text = text + '"'

    # Step 2: Remove trailing commas before } or ]
    text = _re.sub(r',\s*([\]\}])', r'\1', text)

    # Step 3: Balance braces and brackets
    open_braces = text.count('{') - text.count('}')
    open_brackets = text.count('[') - text.count(']')

    # Trim any dangling comma at the end
    text = text.rstrip()
    if text.endswith(','):
        text = text[:-1]

    text += ']' * max(0, open_brackets)
    text += '}' * max(0, open_braces)

    return text


def _extract_fields_regex(text: str) -> dict:
    """Extract JSON key-value pairs using regex when json.loads fails.

    Finds patterns like "key": "value" and reconstructs a dict.
    """
    import re as _re

    payload = {}

    # Match "key": "value" pairs (handles multi-line values via DOTALL)
    pattern = _re.compile(
        r'"(\w+)"\s*:\s*"((?:[^"\\]|\\.)*)(?:"|$)',
        _re.DOTALL,
    )

    for match in pattern.finditer(text):
        key = match.group(1)
        value = match.group(2)
        # Unescape basic JSON escapes
        value = (
            value.replace('\\"', '"')
            .replace('\\n', '\n')
            .replace('\\\\', '\\')
        )
        payload[key] = value

    return payload


def _build_fallback_payload(raw_text: str) -> dict:
    """Build a minimal research payload from raw text when all parsing fails.

    Preserves the raw text so partial research isn't lost.
    """
    lines = raw_text.strip().split("\n")
    headline = "Research output (parsing failed)"
    for line in lines[:10]:
        line = line.strip().strip('"').strip(',')
        if 10 < len(line) < 200 and not line.startswith("{"):
            headline = line
            break

    return {
        "headline": headline,
        "thesis": "",
        "executive_hook": "",
        "fact_sheet": raw_text[:2000] if len(raw_text) > 200 else "",
        "historical_parallels": "",
        "framework_analysis": "",
        "character_dossier": "",
        "narrative_arc": "",
        "counter_arguments": "",
        "visual_seeds": "",
        "source_bibliography": "",
        "themes": "",
        "psychological_angles": "",
        "narrative_arc_suggestion": "",
        "title_options": "",
        "thumbnail_concepts": "",
        "_raw_text": raw_text,
        "_parse_status": "fallback",
    }


def _validate_payload_fields(payload: dict):
    """Log warnings for missing required fields."""
    required_fields = [
        "headline", "thesis", "executive_hook", "fact_sheet",
        "historical_parallels", "framework_analysis", "character_dossier",
        "narrative_arc", "counter_arguments", "visual_seeds",
        "source_bibliography",
    ]
    missing = [f for f in required_fields if not payload.get(f)]
    if missing:
        logger.warning(f"Research payload missing fields: {missing}")


def _parse_research_payload(response_text: str) -> dict:
    """Parse the JSON research payload from Claude's response.

    Handles:
    - Markdown code blocks
    - Truncated JSON (unterminated strings, missing closing braces)
    - Trailing commas
    - Complete parse failures (returns fallback with raw text)

    If all parsing attempts fail, returns a minimal payload with the raw
    text preserved — partial research is better than no research.
    """
    text = response_text.strip()

    # Strip markdown code block if present
    if text.startswith("```"):
        first_newline = text.index("\n")
        text = text[first_newline + 1:]
    if text.endswith("```"):
        text = text[:-3].rstrip()

    # Try to find JSON object boundaries
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
        text = text[brace_start:brace_end + 1]
    elif brace_start != -1:
        # Opening brace but no closing — truncated response
        text = text[brace_start:]

    # Attempt 1: Direct parse
    try:
        payload = json.loads(text)
        _validate_payload_fields(payload)
        return payload
    except json.JSONDecodeError as e:
        logger.warning(f"JSON parse failed (attempt 1 — direct): {e}")

    # Attempt 2: Repair truncated JSON
    try:
        repaired = _repair_json(text)
        payload = json.loads(repaired)
        logger.info("JSON repair successful (attempt 2 — repaired truncation)")
        _validate_payload_fields(payload)
        return payload
    except json.JSONDecodeError as e:
        logger.warning(f"JSON repair failed (attempt 2): {e}")

    # Attempt 3: Extract individual fields with regex
    try:
        payload = _extract_fields_regex(text)
        if payload and len(payload) >= 3:
            logger.info(
                f"Regex field extraction recovered {len(payload)} fields (attempt 3)"
            )
            _validate_payload_fields(payload)
            return payload
    except Exception as e:
        logger.warning(f"Regex extraction failed (attempt 3): {e}")

    # Attempt 4: Fallback — save raw text as partial payload
    logger.error(
        "All JSON parsing attempts failed — saving raw text as fallback payload"
    )
    return _build_fallback_payload(response_text)


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

        # max_tokens=16000 to prevent truncation — the research payload is
        # 15 fields of 200-500 words each (~5000-7500 words = ~7000-10000 tokens),
        # plus JSON structure overhead. 8000 was causing truncated JSON.
        response = await self.anthropic.generate(
            prompt=prompt,
            system_prompt=RESEARCH_SYSTEM_PROMPT,
            model=self.model,
            max_tokens=16000,
            temperature=0.7,
        )

        payload = _parse_research_payload(response)
        logger.info(
            f"Research complete: {payload.get('headline', 'Untitled')} — "
            f"{len(payload)} fields populated"
        )

        return payload


def infer_framework_from_research(payload: dict) -> str:
    """Determine the best analytical framework from a research payload.

    The research agent has deep context about the topic at this point,
    so it can make a more informed framework choice than the discovery scanner.
    This field is CRITICAL — the brief translator reads it to determine
    which voice to write the script in.

    Returns:
        One of the 10 valid Framework Angle values.
    """
    # Combine all rich text fields for analysis
    text = " ".join([
        payload.get("framework_analysis", ""),
        payload.get("themes", ""),
        payload.get("thesis", ""),
        payload.get("historical_parallels", ""),
        payload.get("narrative_arc", ""),
    ]).lower()

    # Score each framework based on keyword presence
    framework_signals = {
        "48 Laws": ["law of power", "48 laws", "robert greene", "conceal your intentions",
                     "crush your enemy", "court power", "appear weak",
                     "power dynamics", "power play", "strategic deception"],
        "Machiavelli": ["machiavelli", "the prince", "virtù", "fortuna",
                         "feared or loved", "fox and lion", "principality",
                         "statecraft", "political realism"],
        "Sun Tzu": ["sun tzu", "art of war", "all warfare is deception",
                     "supreme excellence", "know your enemy", "terrain",
                     "military strategy", "flanking", "strategic retreat"],
        "Game Theory": ["game theory", "nash equilibrium", "prisoner's dilemma",
                         "zero-sum", "positive-sum", "dominant strategy",
                         "payoff matrix", "incentive structure", "tit for tat"],
        "Jung Shadow": ["shadow self", "jung", "collective unconscious", "projection",
                         "persona", "archetype", "individuation", "shadow work"],
        "Behavioral Econ": ["behavioral economics", "loss aversion", "anchoring",
                             "sunk cost", "nudge", "kahneman", "tversky",
                             "cognitive bias", "irrational"],
        "Stoicism": ["stoic", "marcus aurelius", "seneca", "epictetus",
                      "what you can control", "memento mori", "amor fati",
                      "virtue ethics", "tranquility"],
        "Propaganda": ["propaganda", "bernays", "chomsky", "manufacturing consent",
                        "media manipulation", "narrative control", "information warfare",
                        "public relations", "perception management"],
        "Systems Thinking": ["systems thinking", "feedback loop", "second-order effects",
                              "unintended consequences", "complexity", "emergent behavior",
                              "cascade", "systemic risk", "interconnected"],
        "Evolutionary Psych": ["evolutionary psychology", "tribal instinct",
                                "dominance hierarchy", "in-group", "out-group",
                                "status signaling", "survival instinct", "primal"],
    }

    best_framework = "48 Laws"
    best_score = 0

    for framework, keywords in framework_signals.items():
        score = sum(1 for kw in keywords if kw in text)
        if score > best_score:
            best_score = score
            best_framework = framework

    return best_framework


def write_to_airtable(airtable_client, payload: dict) -> dict:
    """Write a research payload to the Idea Concepts table.

    Creates a new idea record with the full research payload attached
    as a JSON string in the research_payload field, plus key fields
    mapped to their respective Airtable columns.

    Args:
        airtable_client: AirtableClient instance
        payload: Structured research_payload dict from ResearchAgent

    Returns:
        Created Airtable record dict with id
    """
    # Serialize full payload as JSON for the research_payload field
    research_payload_json = json.dumps(payload)

    # Validate payload size (Airtable long text limit ~100k chars)
    if len(research_payload_json) > 100000:
        logger.warning(
            f"Research payload is {len(research_payload_json)} chars — "
            f"may exceed Airtable field limit"
        )

    # Determine the best framework angle
    framework_angle = infer_framework_from_research(payload)
    logger.info(f"Inferred Framework Angle: {framework_angle}")

    # Build the idea data dict compatible with AirtableClient.create_idea()
    idea_data = {
        "viral_title": payload.get("headline", ""),
        "hook_script": payload.get("executive_hook", ""),
        "narrative_logic": {
            "past_context": payload.get("historical_parallels", ""),
            "present_parallel": payload.get("framework_analysis", ""),
            "future_prediction": payload.get("narrative_arc", ""),
        },
        "thumbnail_visual": (
            payload.get("thumbnail_concepts", "").split("\n")[0]
            if payload.get("thumbnail_concepts")
            else ""
        ),
        "writer_guidance": payload.get("thesis", ""),
        "original_dna": json.dumps({
            "source": "research_agent",
            "themes": payload.get("themes", ""),
            "psychological_angles": payload.get("psychological_angles", ""),
        }),
        # Rich schema fields
        "Framework Angle": framework_angle,
        "Executive Hook": payload.get("executive_hook", ""),
        "Thesis": payload.get("thesis", ""),
        "Source URLs": payload.get("source_bibliography", ""),
        "Research Payload": research_payload_json,
        "Thematic Framework": payload.get("themes", ""),
    }

    # Create the record with source="research_agent"
    record = airtable_client.create_idea(idea_data, source="research_agent")
    record_id = record["id"]

    logger.info(f"Research written to Idea Concepts: {record_id}")
    return record


async def run_research(
    anthropic_client,
    topic: str,
    seed_urls: Optional[list[str]] = None,
    context: Optional[str] = None,
    model: str = "claude-sonnet-4-5-20250929",
    airtable_client=None,
) -> dict:
    """Convenience function to run deep research.

    This is the main entry point for external callers.

    Args:
        anthropic_client: AnthropicClient instance
        topic: Topic to research
        seed_urls: Optional seed URLs
        context: Optional context
        model: LLM model to use
        airtable_client: Optional AirtableClient — if provided, writes
                         research payload to Idea Concepts table

    Returns:
        Structured research_payload dict (with airtable_record_id if written)
    """
    agent = ResearchAgent(anthropic_client, model=model)
    payload = await agent.research(topic, seed_urls, context)

    # Write to Airtable if client provided
    if airtable_client is not None:
        record = write_to_airtable(airtable_client, payload)
        payload["_airtable_record_id"] = record["id"]

    return payload


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
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save research payload to Airtable Idea Concepts table",
    )

    args = parser.parse_args()

    # Load environment
    from dotenv import load_dotenv
    load_dotenv()

    from clients.anthropic_client import AnthropicClient

    anthropic = AnthropicClient()

    # Optionally initialize Airtable client
    airtable = None
    if args.save:
        from clients.airtable_client import AirtableClient
        airtable = AirtableClient()

    print(f"\n{'=' * 60}")
    print(f"RESEARCH AGENT — Deep Research")
    print(f"{'=' * 60}")
    print(f"Topic: {args.topic}")
    if args.urls:
        print(f"Seed URLs: {args.urls}")
    print(f"Model: {args.model}")
    print(f"Save to Airtable: {'Yes' if args.save else 'No'}")
    print(f"{'=' * 60}\n")

    payload = await run_research(
        anthropic_client=anthropic,
        topic=args.topic,
        seed_urls=args.urls,
        context=args.context,
        model=args.model,
        airtable_client=airtable,
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
