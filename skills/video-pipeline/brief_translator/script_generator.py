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

# Act marker regex pattern — full format: [ACT 1 — Title | 0:00 - 4:10 | ~500 words]
ACT_MARKER_PATTERN = re.compile(
    r"\[ACT\s+(\d+)\s*[—–-]\s*(.*?)\s*\|\s*([\d:]+\s*-\s*[\d:]+)\s*(?:\|\s*~?\s*(\d+)\s*words?)?\s*\]",
    re.IGNORECASE,
)

# Fallback regex for simple markers: [ACT 1], [ACT 2], etc.
# Used when script is reassembled from Airtable records without full act metadata.
ACT_MARKER_SIMPLE_PATTERN = re.compile(
    r"\[ACT\s+(\d+)\s*\]",
    re.IGNORECASE,
)


def load_script_prompt() -> str:
    """Load the script generation prompt template."""
    return PROMPT_TEMPLATE_PATH.read_text()


def _build_framework_lens_section(framework_angle: str) -> str:
    """Build the framework-specific instructions for the script prompt.

    Each framework gets detailed instructions on HOW to apply it throughout
    every act of the script. This is the analytical backbone.
    """
    framework_instructions = {
        "48 Laws": (
            "=== PRIMARY ANALYTICAL LENS: THE 48 LAWS OF POWER (Robert Greene) ===\n\n"
            "You MUST explicitly reference specific Laws of Power throughout the entire\n"
            "script. Each act should tie to a specific law. The laws are the analytical\n"
            "backbone — they explain WHY the actors are behaving as they are.\n\n"
            "Examples of how to weave laws into narration:\n"
            '- "This is Law 3: Conceal Your Intentions. And [actor] has mastered it."\n'
            '- "Law 15: Crush Your Enemy Totally — and [actor] learned this lesson early."\n'
            '- "Robert Greene wrote: \'Never outshine the master.\' Law 1. [Actor] violated\n'
            '  this principle and paid the price."\n'
            '- "This is textbook Law 6: Court Attention at All Costs."\n\n'
            "Reference at least 4-5 DIFFERENT laws across the 6 acts. Name the law number\n"
            "and title every time. The viewer should feel like they're getting a masterclass\n"
            "in power dynamics while watching current events unfold."
        ),
        "Machiavelli": (
            "=== PRIMARY ANALYTICAL LENS: THE PRINCE (Niccolò Machiavelli) ===\n\n"
            "Frame the entire narrative through Machiavelli's The Prince. The corporate\n"
            "and political actors ARE princes managing their principalities. Reference\n"
            "specific chapters and concepts throughout:\n\n"
            '- The Fox and the Lion: "A prince must be both fox and lion — cunning enough\n'
            '  to recognize traps, and fierce enough to terrify wolves."\n'
            '- Fortune vs Virtù: Frame success/failure as the interplay between strategic\n'
            '  skill (virtù) and circumstances (fortuna)\n'
            '- Whether it\'s better to be feared or loved: Apply this to corporate/national\n'
            '  actors directly\n'
            '- New Principalities vs Hereditary: Frame market entrants vs incumbents\n'
            '- Armed prophets vs unarmed: Those who back vision with force succeed\n\n'
            "Every major actor should be analyzed AS a Machiavellian prince. Their moves\n"
            "should be compared to specific passages from The Prince. Reference Machiavelli\n"
            "by name at least 3-4 times."
        ),
        "Sun Tzu": (
            "=== PRIMARY ANALYTICAL LENS: THE ART OF WAR (Sun Tzu) ===\n\n"
            "Frame the entire narrative as strategic warfare. Every move is a military\n"
            "maneuver. Use Sun Tzu's principles as recurring analytical tools:\n\n"
            '- "All warfare is based on deception" — the recurring theme\n'
            '- "Supreme excellence consists in breaking the enemy\'s resistance without\n'
            '  fighting" — the ultimate strategic goal\n'
            '- "Know your enemy and know yourself; in a hundred battles you will never\n'
            '  be defeated"\n'
            '- The five factors: moral influence, weather, terrain, command, doctrine\n'
            '- "Attack where he is unprepared, appear where you are not expected"\n'
            '- The concept of shì (strategic advantage/momentum)\n\n'
            "Frame economic and political moves as military campaigns. Sanctions are\n"
            "sieges. Trade deals are alliances. Market entries are invasions. Retreats\n"
            "can be strategic. Quote Sun Tzu directly at least 3-4 times."
        ),
        "Game Theory": (
            "=== PRIMARY ANALYTICAL LENS: GAME THEORY ===\n\n"
            "Frame the entire narrative through game-theoretic structures. Show how\n"
            "actors are trapped in strategic interactions with predictable dynamics:\n\n"
            "- Nash Equilibrium: Show where actors are locked into suboptimal outcomes\n"
            "  that neither can unilaterally escape\n"
            "- Prisoner's Dilemma: Frame cooperation failures where mutual defection\n"
            "  hurts everyone but is individually rational\n"
            "- Zero-Sum vs Positive-Sum: Identify whether the situation is truly\n"
            "  zero-sum or if actors are mistakenly treating it as one\n"
            "- Credible Commitments: Show how actors try (or fail) to make binding\n"
            "  promises that change the game\n"
            "- Tit-for-Tat escalation: Show retaliatory spirals\n\n"
            "The viewer should understand that the actors aren't making random choices\n"
            "— they're trapped in game-theoretic structures that make certain outcomes\n"
            "nearly inevitable. Name the specific game/equilibrium being played."
        ),
        "Jung Shadow": (
            "=== PRIMARY ANALYTICAL LENS: JUNGIAN SHADOW PSYCHOLOGY ===\n\n"
            "Frame the narrative through Jung's concept of the shadow self and\n"
            "collective unconscious. Nations and corporations have shadow selves\n"
            "they project onto enemies:\n\n"
            "- Shadow Self: What the actor refuses to acknowledge about themselves,\n"
            "  projected onto the 'enemy'\n"
            "- Collective Unconscious: Shared archetypes driving mass behavior\n"
            "- Persona vs Shadow: The public face vs the hidden drives\n"
            "- Projection: Accusing others of exactly what you're doing\n"
            "- Individuation: The painful process of integrating the shadow\n\n"
            "Show how nations/companies are acting out their shadow — the qualities\n"
            "they project onto rivals are actually their own. Reference Jung by name.\n"
            "This lens should make viewers question the moral framing they've accepted."
        ),
        "Behavioral Econ": (
            "=== PRIMARY ANALYTICAL LENS: BEHAVIORAL ECONOMICS ===\n\n"
            "Frame the narrative through cognitive biases and irrational decision-making\n"
            "that drives geopolitical and economic behavior:\n\n"
            "- Loss Aversion: Actors risk more to avoid losses than to achieve gains\n"
            "- Anchoring: Initial reference points distort all subsequent judgments\n"
            "- Sunk Cost Fallacy: Continuing failed strategies because of past investment\n"
            "- Availability Heuristic: Decisions based on vivid/recent events, not data\n"
            "- Endowment Effect: Overvaluing what you already have\n"
            "- Framing Effects: The same facts presented differently lead to opposite\n"
            "  conclusions\n\n"
            "Reference Kahneman, Tversky, or Thaler when introducing concepts. Show how\n"
            "supposedly rational actors (governments, central banks, corporations) are\n"
            "making decisions driven by cognitive biases, not rational analysis."
        ),
        "Stoicism": (
            "=== PRIMARY ANALYTICAL LENS: STOIC PHILOSOPHY ===\n\n"
            "Frame the narrative through Stoic philosophy — what can and cannot be\n"
            "controlled, and how actors respond to forces beyond their control:\n\n"
            '- Marcus Aurelius: "The impediment to action advances action. What stands\n'
            '  in the way becomes the way."\n'
            '- Seneca on fortune: "It is not that we have a short time to live, but\n'
            '  that we waste a great deal of it."\n'
            "- The dichotomy of control: Separate what actors can control from what\n"
            "  they cannot — show who is wasting energy fighting the uncontrollable\n"
            "- Amor fati: Some actors embrace their fate and turn it to advantage\n"
            "- Premeditatio malorum: The strategic value of expecting the worst\n\n"
            "The Stoic lens should reveal which actors are wasting power fighting\n"
            "the uncontrollable, and which are strategically accepting reality."
        ),
        "Propaganda": (
            "=== PRIMARY ANALYTICAL LENS: PROPAGANDA & INFORMATION CONTROL ===\n\n"
            "Frame the entire narrative through the lens of information warfare and\n"
            "manufactured consent. The real battlefield is perception:\n\n"
            "- Bernays: The engineering of consent — how public opinion is manufactured\n"
            "- Chomsky's Propaganda Model: The 5 filters that determine what becomes\n"
            "  'news' (ownership, advertising, sourcing, flak, anti-ideology)\n"
            "- Manufacturing Consent: Show how the narrative you're told serves the\n"
            "  interests of those telling it\n"
            "- The Overton Window: What's 'acceptable' to discuss is itself controlled\n"
            "- Controlled opposition: Both sides of the debate may serve the same master\n\n"
            "The viewer should question every narrative they've accepted. Frame\n"
            "information control as the REAL battlefield — more powerful than any army\n"
            "or economy. Reference Bernays or Chomsky by name."
        ),
        "Systems Thinking": (
            "=== PRIMARY ANALYTICAL LENS: SYSTEMS THINKING ===\n\n"
            "Frame the entire narrative through feedback loops, second-order effects,\n"
            "and unintended consequences. Show how interventions create the problems\n"
            "they claim to solve:\n\n"
            "- Feedback Loops: Identify reinforcing and balancing loops in the system\n"
            "- Second-Order Effects: What happens AFTER the obvious first consequence?\n"
            "- Unintended Consequences: Show how interventions backfire predictably\n"
            "- Emergence: System behavior that no individual actor intended\n"
            "- Leverage Points: Where small changes could shift the whole system\n"
            "- The Cobra Effect: Solutions that make the problem worse\n\n"
            "The viewer should understand that nobody is fully in control — the system\n"
            "has its own logic that overrides individual intentions. Show the cascade\n"
            "of consequences that makes outcomes feel inevitable in hindsight."
        ),
        "Evolutionary Psych": (
            "=== PRIMARY ANALYTICAL LENS: EVOLUTIONARY PSYCHOLOGY ===\n\n"
            "Frame the narrative through tribal instincts and dominance hierarchies\n"
            "that drive geopolitical and corporate behavior:\n\n"
            "- Tribal Instincts: In-group/out-group dynamics driving alliance formation\n"
            "- Dominance Hierarchies: Status competition at every level of organization\n"
            "- Coalition Building: Strategic alliance formation for collective defense\n"
            "- Status Signaling: Actions taken not for practical value but for display\n"
            "- Reciprocal Altruism: Strategic generosity that creates obligation\n"
            "- Costly Signaling: Demonstrating commitment through expensive actions\n\n"
            "Show that underneath the sophisticated economic and political language,\n"
            "these are primal dynamics — the same ones that governed tribal politics\n"
            "100,000 years ago. We've upgraded the weapons but not the wetware."
        ),
    }

    framework = framework_instructions.get(framework_angle, "")
    if not framework:
        # Fallback to a generic power dynamics lens
        framework = (
            "=== PRIMARY ANALYTICAL LENS: POWER DYNAMICS ===\n\n"
            "Apply a dark power dynamics analysis to every event. Who gains power?\n"
            "Who loses it? What strategic maneuver is being executed? Frame every\n"
            "actor as pursuing a deliberate strategy, not reacting to events.\n"
            "Reference relevant thinkers (Machiavelli, Greene, Sun Tzu) throughout."
        )

    return framework


def _build_source_citations_section(brief: dict) -> str:
    """Build the source citations instruction section for the prompt."""
    source_urls = brief.get("source_urls", "")
    source_bib = brief.get("source_bibliography", "")

    sources = source_urls or source_bib
    if not sources:
        return ""

    return (
        "=== SOURCE CITATIONS ===\n\n"
        "The following sources were used in research. Weave citations naturally\n"
        "into the narration — NOT as footnotes, but as authority-building references.\n"
        "Aim for at least 4-6 source citations across the full script.\n\n"
        "Examples of natural citation style:\n"
        '- "According to Reuters reporting from January 14th..."\n'
        '- "Internal documents obtained by the Financial Times reveal..."\n'
        '- "Data from the Federal Reserve shows..."\n'
        '- "A 2024 study published in Nature found..."\n'
        '- "Bloomberg reported last week that..."\n\n'
        "Citations add credibility and authority — this channel presents EVIDENCE,\n"
        "not just opinion. The viewer should feel that every claim is backed by\n"
        "real journalism and data.\n\n"
        f"Available sources:\n{sources}\n"
    )


def build_script_prompt(brief: dict) -> str:
    """Build the script generation prompt from a research brief.

    Now includes Framework Angle as the primary analytical lens and
    source citations section.
    """
    template = load_script_prompt()

    # Build framework lens section based on Framework Angle field
    framework_angle = brief.get("framework_angle", "")
    framework_lens = _build_framework_lens_section(framework_angle)

    # Build source citations section
    source_citations = _build_source_citations_section(brief)

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
        FRAMEWORK_LENS_SECTION=framework_lens,
        SOURCE_CITATIONS_SECTION=source_citations,
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

    Tries the full act marker format first (with title, timestamps, word
    count).  Falls back to simple ``[ACT N]`` markers which are produced
    when the pipeline reassembles Airtable Script records into a full
    script.

    Returns:
        Dict mapping act number (1-6) to the text content of that act.
    """
    acts = {}
    markers = list(ACT_MARKER_PATTERN.finditer(script))

    # Fallback: try simple [ACT N] markers if full pattern found nothing
    if not markers:
        markers = list(ACT_MARKER_SIMPLE_PATTERN.finditer(script))

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
