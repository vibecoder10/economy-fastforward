"""Script Generation (Step 2).

Transforms a validated research brief into a full 25-minute narration script
with six-act structure and act markers.
"""

import re
from pathlib import Path
from typing import Optional

PROMPT_TEMPLATE_PATH = Path(__file__).parent / "prompts" / "script.txt"

# Word count bounds for the full script
SCRIPT_MIN_WORDS = 3000
SCRIPT_MAX_WORDS = 4500
SCRIPT_TARGET_WORDS = 3750

# Expected act count
EXPECTED_ACT_COUNT = 6

# Act marker regex pattern
ACT_MARKER_PATTERN = re.compile(
    r"\[ACT\s+(\d+)\s*[—–-]\s*(.*?)\s*\|\s*([\d:]+\s*-\s*[\d:]+)\s*(?:\|\s*~?\s*(\d+)\s*words?)?\s*\]",
    re.IGNORECASE,
)


def load_script_prompt() -> str:
    """Load the script generation prompt template."""
    return PROMPT_TEMPLATE_PATH.read_text()


def build_script_prompt(brief: dict) -> str:
    """Build the script generation prompt from a research brief."""
    template = load_script_prompt()
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
    )


def validate_script(script: str) -> dict:
    """Validate script structure and word count.

    Returns:
        {
            "valid": bool,
            "word_count": int,
            "act_count": int,
            "issues": list[str],
            "acts": list[dict],  # parsed act info
        }
    """
    issues = []
    word_count = len(script.split())

    # Check word count
    if word_count < SCRIPT_MIN_WORDS:
        issues.append(
            f"Script too short: {word_count} words (minimum {SCRIPT_MIN_WORDS})"
        )
    elif word_count > SCRIPT_MAX_WORDS:
        issues.append(
            f"Script too long: {word_count} words (maximum {SCRIPT_MAX_WORDS})"
        )

    # Parse act markers
    acts = []
    for match in ACT_MARKER_PATTERN.finditer(script):
        acts.append({
            "number": int(match.group(1)),
            "title": match.group(2).strip(),
            "timestamp": match.group(3).strip(),
            "target_words": int(match.group(4)) if match.group(4) else None,
        })

    if len(acts) < EXPECTED_ACT_COUNT:
        issues.append(
            f"Only {len(acts)} act markers found (expected {EXPECTED_ACT_COUNT})"
        )

    # Check act numbers are sequential
    act_numbers = [a["number"] for a in acts]
    expected_numbers = list(range(1, EXPECTED_ACT_COUNT + 1))
    if act_numbers != expected_numbers[: len(act_numbers)]:
        issues.append(f"Act numbers not sequential: {act_numbers}")

    return {
        "valid": len(issues) == 0,
        "word_count": word_count,
        "act_count": len(acts),
        "issues": issues,
        "acts": acts,
    }


def extract_acts(script: str) -> dict[int, str]:
    """Split script text into individual acts.

    Returns:
        Dict mapping act number (1-6) to the text content of that act.
    """
    acts = {}
    markers = list(ACT_MARKER_PATTERN.finditer(script))

    for i, match in enumerate(markers):
        act_num = int(match.group(1))
        start = match.end()
        end = markers[i + 1].start() if i + 1 < len(markers) else len(script)
        acts[act_num] = script[start:end].strip()

    return acts


async def generate_script(
    anthropic_client,
    brief: dict,
    model: str = "claude-sonnet-4-5-20250929",
) -> dict:
    """Generate a full narration script from a validated research brief.

    Args:
        anthropic_client: AnthropicClient instance
        brief: Validated research brief dict
        model: Model to use (defaults to Sonnet, can use Opus for higher quality)

    Returns:
        {
            "script": str,
            "validation": dict,
        }
    """
    prompt = build_script_prompt(brief)

    script = await anthropic_client.generate(
        prompt=prompt,
        model=model,
        max_tokens=8000,
        temperature=0.8,
    )

    validation = validate_script(script)

    # If script is too short, try once more with explicit expansion instruction
    if not validation["valid"] and validation["word_count"] < SCRIPT_MIN_WORDS:
        expansion_prompt = (
            f"{prompt}\n\n"
            f"CRITICAL: Your previous attempt was only {validation['word_count']} words. "
            f"The script MUST be at least {SCRIPT_MIN_WORDS} words. "
            f"Expand the thinner acts with more specific details and examples."
        )
        script = await anthropic_client.generate(
            prompt=expansion_prompt,
            model=model,
            max_tokens=8000,
            temperature=0.8,
        )
        validation = validate_script(script)

    return {
        "script": script,
        "validation": validation,
    }
