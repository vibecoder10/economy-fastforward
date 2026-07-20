"""
Idea Modeling Module - Variable decomposition and format extraction for viral titles.
Part of Idea Engine v2.
"""

import json
import logging
from typing import Optional
from collections import defaultdict
from orchestrator.pipeline_constants import Models
from shared.json_utils import parse_json_response

logger = logging.getLogger(__name__)

DECOMPOSE_SYSTEM_PROMPT = """You are a YouTube title analyst. Given a video title, decompose it into typed variables.

Variable types:
- number: A concrete number (7, 30, Top 10)
- authority_qualifier: Credibility word (Most, Best, Expert)
- core_topic: The main subject noun
- extreme_benefit: The big promise or consequence
- specific_mechanism: The concrete detail that grounds it
- time_anchor: Temporal element (In 2026, Right Now)
- target_audience: Who this is for (For Beginners, Every American)

Also classify which psychological triggers this title uses:
longevity, fear, practical_value, curiosity_gap, authority, urgency, contrarian, aspiration, outrage, scale

Respond in JSON only. No markdown, no explanation. Example format:
{
  "variables": {
    "number": "30",
    "authority_qualifier": "Most Reliable",
    "core_topic": "Cars",
    "extreme_benefit": "Forever Lasting",
    "specific_mechanism": "Engines"
  },
  "formula": "[Number] + [Authority Qualifier] + [Core Topic] + [Extreme Benefit] + [Specific Mechanism]",
  "psychological_triggers": ["longevity", "practical_value", "scale"]
}"""


async def decompose_title(title: str, anthropic_client) -> Optional[dict]:
    """
    Decompose a video title into typed variables using Claude Sonnet.

    Args:
        title: The video title to analyze
        anthropic_client: shared.clients.anthropic_client.AnthropicClient
            instance (or any object exposing the same async .generate()
            method) — every real caller (TrendingIdeaBot, pipeline.py's
            --more-ideas path, and the tenant-scoped MCP path added in C59)
            passes the wrapper class, not a raw anthropic.AsyncAnthropic.

    Returns:
        Dict with original_title, variables, formula, psychological_triggers
        None on error
    """
    try:
        content = await anthropic_client.generate(
            prompt=title,
            system_prompt=DECOMPOSE_SYSTEM_PROMPT,
            model=Models.CLAUDE_SONNET,
            max_tokens=1024,
        )

        content = content.strip()
        data = parse_json_response(content, default=None)
        if data is None:
            raise json.JSONDecodeError("Failed to parse decomposition", content, 0)
        
        return {
            "original_title": title,
            "variables": data.get("variables", {}),
            "formula": data.get("formula", ""),
            "psychological_triggers": data.get("psychological_triggers", [])
        }
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse decomposition for title: {e}")
        return None
    except Exception as e:
        logger.error(f"Error decomposing title: {e}")
        return None


def extract_format(decomposed_titles: list) -> list:
    """
    Group decomposed titles by similar formula patterns.
    No API call needed - just string matching on the formula field.
    
    Args:
        decomposed_titles: List of decomposed title dicts from decompose_title()
        
    Returns:
        List of format dicts with format_id, formula, example_titles, times_seen
    """
    if not decomposed_titles:
        return []
    
    # Group by formula
    formula_groups = defaultdict(list)
    for dt in decomposed_titles:
        if dt and dt.get("formula"):
            formula_groups[dt["formula"]].append(dt["original_title"])
    
    # Convert to format list
    formats = []
    for i, (formula, titles) in enumerate(formula_groups.items()):
        # Generate format_id from formula
        format_id = formula.lower()
        format_id = format_id.replace("[", "").replace("]", "")
        format_id = format_id.replace(" + ", "_")
        format_id = format_id.replace(" ", "_")[:50]
        
        formats.append({
            "format_id": format_id,
            "formula": formula,
            "example_titles": titles,
            "times_seen": len(titles)
        })
    
    # Sort by times_seen descending
    formats.sort(key=lambda x: x["times_seen"], reverse=True)
    
    return formats


GENERATE_PROMPT_TEMPLATE = """You are a YouTube strategist for the channel "Economy FastForward" — a finance/economics channel for Americans interested in how economic forces affect their daily lives.

Here are proven title formats extracted from high-performing videos:
{formats}

Here are our niche variables:
{niche_variables}

Generate {num_ideas} video ideas by rebuilding these proven formats with our niche variables.

Rules:
- Swap 1-2 variables max from each format
- Synonym swaps do not count — the replacement must change the actual content
- Each idea must use a different format if possible
- For each idea, state which format it is based on and what was swapped

Respond in JSON array only. No markdown, no explanation. Each item must have:
- viral_title: the generated title
- based_on_format: format_id
- original_example: the original title this format came from
- variables_swapped: list like ["core_topic: Cars to Banks", "extreme_benefit: Forever Lasting to Will Collapse"]
- psychological_triggers: list of trigger ids
- hook_summary: one sentence on why this works"""


async def generate_modeled_ideas(
    formats: list,
    config: dict,
    anthropic_client,
    num_ideas: int = 5
) -> list:
    """
    Generate video ideas by applying niche variables to proven formats.
    
    Args:
        formats: List of format dicts from extract_format()
        config: Config dict with niche_variables
        anthropic_client: shared.clients.anthropic_client.AnthropicClient
            instance (or any object exposing the same async .generate()
            method) — see decompose_title's docstring for why this matters.
        num_ideas: Number of ideas to generate

    Returns:
        List of idea dicts with viral_title, based_on_format, etc.
        Empty list on error
    """
    if not formats:
        logger.warning("No formats provided for idea generation")
        return []

    try:
        # Build prompt
        prompt = GENERATE_PROMPT_TEMPLATE.format(
            formats=json.dumps(formats, indent=2),
            niche_variables=json.dumps(config.get("niche_variables", {}), indent=2),
            num_ideas=num_ideas
        )

        content = await anthropic_client.generate(
            prompt=prompt,
            model=Models.CLAUDE_SONNET,
            max_tokens=2048,
        )

        content = content.strip()
        ideas = parse_json_response(content, default=None)
        if ideas is None:
            raise json.JSONDecodeError("Failed to parse generated ideas", content, 0)
        
        if not isinstance(ideas, list):
            logger.error(f"Expected list, got {type(ideas)}")
            return []
            
        return ideas
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse generated ideas: {e}")
        return []
    except Exception as e:
        logger.error(f"Error generating modeled ideas: {e}")
        return []
