"""Production Readiness Validation (Step 1).

Validates that a research brief has enough material to produce
a full 25-minute documentary-style video with ~140 AI-generated images.
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

PROMPT_TEMPLATE_PATH = Path(__file__).parent / "prompts" / "validation.txt"

# Validation criteria names in order
CRITERIA_NAMES = [
    "hook_strength",
    "fact_density",
    "framework_depth",
    "historical_parallel_richness",
    "character_visualizability",
    "implication_specificity",
    "visual_variety",
    "structural_completeness",
]


def load_validation_prompt() -> str:
    """Load the validation prompt template from disk."""
    return PROMPT_TEMPLATE_PATH.read_text()


def build_validation_prompt(brief: dict) -> str:
    """Build the validation prompt by filling in research brief fields."""
    template = load_validation_prompt()
    return template.format(
        HEADLINE=brief.get("headline", ""),
        THESIS=brief.get("thesis", ""),
        EXECUTIVE_HOOK=brief.get("executive_hook", ""),
        FACT_SHEET=brief.get("fact_sheet", ""),
        HISTORICAL_PARALLELS=brief.get("historical_parallels", ""),
        FRAMEWORK_ANALYSIS=brief.get("framework_analysis", ""),
        CHARACTER_DOSSIER=brief.get("character_dossier", ""),
        NARRATIVE_ARC=brief.get("narrative_arc", ""),
        COUNTER_ARGUMENTS=brief.get("counter_arguments", ""),
        VISUAL_SEEDS=brief.get("visual_seeds", ""),
        SOURCE_BIBLIOGRAPHY=brief.get("source_bibliography", ""),
    )


def parse_validation_xml(response_text: str) -> dict:
    """Parse the XML validation response from Claude.

    Returns:
        {
            "criteria": [{"name": str, "score": str, "assessment": str}, ...],
            "overall_verdict": str,
            "gaps": str,
        }
    """
    # Extract the <validation> block
    match = re.search(r"<validation>(.*?)</validation>", response_text, re.DOTALL)
    if not match:
        raise ValueError("Could not find <validation> block in response")

    xml_content = match.group(1).strip()

    # Parse criteria
    criteria = []
    for criterion_match in re.finditer(
        r'<criterion\s+name="([^"]+)"\s+score="([^"]+)">\s*(.*?)\s*</criterion>',
        xml_content,
        re.DOTALL,
    ):
        criteria.append({
            "name": criterion_match.group(1),
            "score": criterion_match.group(2).upper(),
            "assessment": criterion_match.group(3).strip(),
        })

    # Parse overall verdict
    verdict_match = re.search(
        r"<overall_verdict>\s*(.*?)\s*</overall_verdict>", xml_content
    )
    overall_verdict = verdict_match.group(1).strip() if verdict_match else "REJECT"

    # Parse gaps
    gaps_match = re.search(r"<gaps>\s*(.*?)\s*</gaps>", xml_content, re.DOTALL)
    gaps = gaps_match.group(1).strip() if gaps_match else ""

    return {
        "criteria": criteria,
        "overall_verdict": overall_verdict,
        "gaps": gaps,
    }


def evaluate_validation(validation_result: dict) -> str:
    """Determine action based on validation scores.

    Returns:
        "READY" - Proceed to script generation
        "NEEDS_SUPPLEMENT" - Run targeted supplemental research
        "REJECT" - Too many gaps, skip this brief
    """
    scores = [c["score"] for c in validation_result["criteria"]]

    fail_count = scores.count("FAIL")
    weak_count = scores.count("WEAK")

    if fail_count == 0 and weak_count <= 2:
        return "READY"
    elif fail_count <= 2 or (fail_count == 0 and weak_count > 2):
        return "NEEDS_SUPPLEMENT"
    else:
        return "REJECT"


async def validate_brief(anthropic_client, brief: dict) -> dict:
    """Run production readiness validation on a research brief.

    Args:
        anthropic_client: AnthropicClient instance
        brief: Research brief dict with fields from Ideas Bank

    Returns:
        {
            "criteria": [...],
            "overall_verdict": str,
            "gaps": str,
            "decision": str,  # READY | NEEDS_SUPPLEMENT | REJECT
        }
    """
    prompt = build_validation_prompt(brief)

    response = await anthropic_client.generate(
        prompt=prompt,
        model="claude-sonnet-4-5-20250929",
        max_tokens=2000,
        temperature=0.3,
    )

    result = parse_validation_xml(response)
    result["decision"] = evaluate_validation(result)

    return result


def format_validation_summary(result: dict) -> str:
    """Format validation result as a human-readable summary."""
    lines = [f"Validation: {result['decision']}"]
    for criterion in result["criteria"]:
        icon = {"PASS": "✅", "WEAK": "⚠️", "FAIL": "❌"}.get(
            criterion["score"], "?"
        )
        lines.append(f"  {icon} {criterion['name']}: {criterion['score']}")
    if result.get("gaps"):
        lines.append(f"\nGaps:\n{result['gaps']}")
    return "\n".join(lines)
