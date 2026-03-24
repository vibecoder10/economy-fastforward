"""Senior Editor Pass — Single-Shot Script Correction.

After script validation identifies issues (BROKEN_PROMISE, PACING_DRIFT,
number_density, framework_density, personal_stakes, actionable_close,
cliffhanger_presence), this module makes ONE Claude call to fix them.

Flow:
    1. receive script + validation flags
    2. single Claude call with surgical edit instructions
    3. return corrected script + changelog

Cost ceiling: one Sonnet call (~$0.03).
No retry loop — if the editor can't fix it, pipeline blocks for manual review.
"""

import logging
import re
from typing import Optional
from orchestrator.pipeline_constants import Models

logger = logging.getLogger(__name__)


async def run_senior_editor(
    anthropic_client,
    script: str,
    acts: dict[int, str],
    failed_checks: list,
    brief: dict,
    model: str = Models.CLAUDE_SONNET,
) -> dict:
    """Run a single senior editor pass to fix validation failures.

    Args:
        anthropic_client: AnthropicClient instance
        script: The full script text
        acts: Dict mapping act number to act text
        failed_checks: List of CheckResult objects that failed
        brief: Research brief dict (for context)
        model: Model to use (default Sonnet)

    Returns:
        {
            "script": str,  # Corrected script
            "changelog": list[str],  # What was changed
            "acts_modified": list[int],  # Which acts were touched
            "success": bool,  # Whether edits were applied
        }
    """
    if not failed_checks:
        return {
            "script": script,
            "changelog": [],
            "acts_modified": [],
            "success": True,
        }

    # Build the editorial prompt
    system_prompt = _build_system_prompt()
    edit_instructions = _build_edit_instructions(failed_checks, acts, brief)

    prompt = (
        f"{edit_instructions}\n\n"
        f"=== FULL SCRIPT TO EDIT ===\n\n{script}\n\n"
        f"=== END OF SCRIPT ===\n\n"
        f"Output the COMPLETE corrected script with all act markers intact. "
        f"After the script, include a brief CHANGELOG section listing what "
        f"you changed in each act."
    )

    try:
        response = await anthropic_client.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            model=model,
            max_tokens=10000,  # Scripts can be 3000+ words
            temperature=0.4,  # Lower temp for surgical edits
        )
    except Exception as e:
        logger.error(f"Senior editor call failed: {e}")
        return {
            "script": script,
            "changelog": [f"Editor call failed: {e}"],
            "acts_modified": [],
            "success": False,
        }

    # Parse the response
    corrected_script, changelog = _parse_editor_response(response)

    if not corrected_script:
        logger.warning("Senior editor returned empty or unparseable response")
        return {
            "script": script,
            "changelog": ["Editor returned unparseable response"],
            "acts_modified": [],
            "success": False,
        }

    # Identify which acts were modified
    acts_modified = _identify_modified_acts(acts, corrected_script)

    logger.info(
        f"Senior editor complete: {len(changelog)} changes, "
        f"acts modified: {acts_modified}"
    )

    return {
        "script": corrected_script,
        "changelog": changelog,
        "acts_modified": acts_modified,
        "success": True,
    }


def _build_system_prompt() -> str:
    """Build the system prompt for the senior editor."""
    return """\
You are a senior script editor for a YouTube documentary channel. Your job is
to make surgical fixes to scripts that failed quality validation checks.

RULES:
1. ONLY fix the specific issues listed in the edit instructions
2. Do NOT rewrite sections that aren't flagged
3. Preserve all [ACT X — TITLE | TIMESTAMP | ~WORD COUNT] markers exactly
4. Maintain the overall word count (±5%)
5. Keep the narrative voice and tone consistent
6. Do NOT add new framework references or academic language
7. When adding content to resolve promises, use FACTS from the research brief
8. When cutting for coherence, prioritize keeping investigative/money trail content

OUTPUT FORMAT:
- Output the COMPLETE script with all acts
- End with a CHANGELOG section in this format:
  ```changelog
  - Act 2: Added payoff for "what the numbers reveal" promise
  - Act 5: Cut paragraph about [topic] to maintain focus on [main topic]
  ```
"""


def _build_edit_instructions(
    failed_checks: list,
    acts: dict[int, str],
    brief: dict,
) -> str:
    """Build specific edit instructions from failed checks."""
    instructions = ["=== SENIOR EDITOR INSTRUCTIONS ===\n"]
    instructions.append(
        "The following validation checks FAILED. Fix ONLY these issues:\n"
    )

    for check in failed_checks:
        instructions.append(f"\n### {check.name.upper()}\n")
        instructions.append(f"Issue: {check.detail}\n")
        if check.retry_prompt:
            # Extract the fix instructions part only
            instructions.append(f"\n{check.retry_prompt}\n")

    # Add research context for fact-based fixes
    fact_sheet = brief.get("fact_sheet", "")
    if fact_sheet:
        instructions.append("\n=== RESEARCH FACTS (use for adding content) ===\n")
        instructions.append(fact_sheet[:2000])  # Truncate if very long

    return "\n".join(instructions)


def _parse_editor_response(response: str) -> tuple[str, list[str]]:
    """Parse the editor's response into script and changelog.

    Returns (corrected_script, changelog_list).
    """
    if not response:
        return "", []

    # Look for changelog section
    changelog_match = re.search(
        r'```changelog\s*(.*?)\s*```',
        response,
        re.DOTALL | re.IGNORECASE,
    )

    changelog = []
    if changelog_match:
        changelog_text = changelog_match.group(1)
        # Parse changelog lines
        for line in changelog_text.strip().split('\n'):
            line = line.strip()
            if line.startswith('-'):
                changelog.append(line[1:].strip())
            elif line:
                changelog.append(line)
        # Remove changelog from response to get clean script
        response = response[:changelog_match.start()].strip()

    # Also try CHANGELOG: header format
    if not changelog:
        changelog_header = re.search(
            r'(?:CHANGELOG|Changes?|Edits?):\s*\n((?:[-•*]\s*.+\n?)+)',
            response,
            re.IGNORECASE,
        )
        if changelog_header:
            for line in changelog_header.group(1).strip().split('\n'):
                line = line.strip().lstrip('-•* ')
                if line:
                    changelog.append(line)
            response = response[:changelog_header.start()].strip()

    # Clean up the script
    script = response.strip()

    # Remove any trailing instructions or meta-text
    script = re.sub(
        r'\n*(?:---+|===+)\s*(?:END|CHANGELOG|CHANGES).*$',
        '',
        script,
        flags=re.IGNORECASE | re.DOTALL,
    )

    return script.strip(), changelog


def _identify_modified_acts(
    original_acts: dict[int, str],
    corrected_script: str,
) -> list[int]:
    """Identify which acts were modified by comparing content.

    Returns list of act numbers that changed.
    """
    from .script_generator import extract_acts

    corrected_acts = extract_acts(corrected_script)
    modified = []

    for act_num, original_text in original_acts.items():
        corrected_text = corrected_acts.get(act_num, "")

        # Simple diff: if word count changed by >5% or key content differs
        orig_words = len(original_text.split())
        corr_words = len(corrected_text.split())

        if orig_words == 0:
            if corr_words > 0:
                modified.append(act_num)
            continue

        word_diff_pct = abs(corr_words - orig_words) / orig_words

        if word_diff_pct > 0.05:
            modified.append(act_num)
        elif original_text.strip() != corrected_text.strip():
            # Word count similar but content changed
            modified.append(act_num)

    return sorted(modified)


def format_editor_summary(result: dict) -> str:
    """Format the editor result for logging/Slack."""
    if not result.get("success"):
        return f"❌ Senior editor failed: {result.get('changelog', ['Unknown error'])[0]}"

    if not result.get("changelog"):
        return "✅ Senior editor: no changes needed"

    lines = ["📝 Senior editor changes:"]
    for change in result["changelog"][:5]:  # Cap at 5 for readability
        lines.append(f"  - {change}")

    if result.get("acts_modified"):
        lines.append(f"  Acts modified: {result['acts_modified']}")

    return "\n".join(lines)
