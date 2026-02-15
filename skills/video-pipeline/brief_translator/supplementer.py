"""Targeted Supplemental Research (Step 1b).

When validation identifies specific gaps, this module runs focused
research to fill only those gaps without re-running the entire deep dive.
"""

from pathlib import Path
from typing import Optional

PROMPT_TEMPLATE_PATH = Path(__file__).parent / "prompts" / "supplemental.txt"

# Maximum supplemental research passes before giving up
MAX_SUPPLEMENT_PASSES = 2

# Map criterion names to the brief fields they relate to
CRITERION_TO_FIELDS = {
    "hook_strength": ["executive_hook"],
    "fact_density": ["fact_sheet"],
    "framework_depth": ["framework_analysis"],
    "historical_parallel_richness": ["historical_parallels"],
    "character_visualizability": ["character_dossier"],
    "implication_specificity": ["narrative_arc"],
    "visual_variety": ["visual_seeds"],
    "structural_completeness": [
        "fact_sheet",
        "historical_parallels",
        "framework_analysis",
        "narrative_arc",
    ],
}


def load_supplemental_prompt() -> str:
    """Load the supplemental research prompt template."""
    return PROMPT_TEMPLATE_PATH.read_text()


def build_supplemental_prompt(brief: dict, gaps: str) -> str:
    """Build supplemental research prompt with gaps and relevant existing research.

    Only includes the sections of the brief that are related to the identified gaps.
    """
    template = load_supplemental_prompt()

    # Collect relevant existing research sections based on gap text
    relevant_sections = []
    gaps_lower = gaps.lower()

    for criterion_name, fields in CRITERION_TO_FIELDS.items():
        if criterion_name.replace("_", " ") in gaps_lower or criterion_name in gaps_lower:
            for field in fields:
                value = brief.get(field, "")
                if value:
                    relevant_sections.append(f"## {field}\n{value}")

    # If we couldn't match specific criteria, include the most commonly needed sections
    if not relevant_sections:
        for field in ["fact_sheet", "historical_parallels", "framework_analysis", "narrative_arc"]:
            value = brief.get(field, "")
            if value:
                relevant_sections.append(f"## {field}\n{value}")

    existing_research = "\n\n".join(relevant_sections) if relevant_sections else "(No matching sections found)"

    return template.format(
        HEADLINE=brief.get("headline", ""),
        EXISTING_RESEARCH=existing_research,
        GAPS=gaps,
    )


def merge_supplement_into_brief(brief: dict, supplement_text: str, gaps: str) -> dict:
    """Merge supplemental research results into the appropriate brief fields.

    Appends new research to existing fields rather than replacing them.

    Args:
        brief: The original research brief dict
        supplement_text: Raw text response from supplemental research
        gaps: The gaps string that was used to trigger supplemental research

    Returns:
        Updated brief dict with merged supplemental research
    """
    updated = dict(brief)
    gaps_lower = gaps.lower()

    # Determine which fields to append to
    target_fields = set()
    for criterion_name, fields in CRITERION_TO_FIELDS.items():
        if criterion_name.replace("_", " ") in gaps_lower or criterion_name in gaps_lower:
            target_fields.update(fields)

    # If no specific fields matched, append to a general supplemental field
    if not target_fields:
        target_fields = {"fact_sheet", "historical_parallels"}

    supplement_header = "\n\n--- SUPPLEMENTAL RESEARCH ---\n\n"

    for field in target_fields:
        existing = updated.get(field, "")
        updated[field] = existing + supplement_header + supplement_text

    return updated


async def run_supplemental_research(
    anthropic_client,
    brief: dict,
    gaps: str,
) -> str:
    """Run targeted supplemental research to fill identified gaps.

    Args:
        anthropic_client: AnthropicClient instance
        brief: Research brief dict
        gaps: Specific gaps identified by validation

    Returns:
        Supplemental research text
    """
    prompt = build_supplemental_prompt(brief, gaps)

    response = await anthropic_client.generate(
        prompt=prompt,
        model="claude-sonnet-4-5-20250929",
        max_tokens=4000,
        temperature=0.5,
    )

    return response.strip()
