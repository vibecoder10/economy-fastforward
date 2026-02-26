"""Script Generation (Step 2).

Transforms a validated research brief into a full 25-minute narration script
with six-act structure and act markers.
"""

import json
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

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

    Every lens includes a PSYCHOLOGICAL DEPTH LAYER that instructs the model
    to connect the framework to the viewer's own life and human nature.
    """
    # Shared psychological depth layer appended to every lens
    _PSYCH_DEPTH = (
        "\n\nPSYCHOLOGICAL DEPTH LAYER:\n"
        "Every framework reference must also illuminate something about HUMAN NATURE.\n"
        "The viewer should see themselves in the pattern.\n\n"
        "- When referencing a Law of Power, show how the VIEWER unconsciously uses\n"
        "  or falls victim to this law in their own life\n"
        "- When citing Machiavelli, show how the same princely calculations happen\n"
        "  in office politics, relationships, and social dynamics\n"
        "- When applying Jung's Shadow, show how the viewer's own shadow is activated\n"
        "  by the story — what part of themselves are they projecting?\n"
        "- When using Game Theory, show how the viewer is trapped in the same games\n"
        "  at a personal scale\n\n"
        "The framework should feel PERSONALLY revelatory, not just analytically\n"
        "interesting. The viewer should think: \"I do this too\" or \"I've seen this\n"
        "in my own life\" at least twice during the script."
    )

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
        # --- NEW THINKER LENSES ---
        "Thucydides": (
            "=== PRIMARY ANALYTICAL LENS: THUCYDIDES TRAP ===\n\n"
            "Frame the narrative through the Thucydides Trap — the structural tension\n"
            "between established and rising powers that makes conflict nearly inevitable:\n\n"
            "- The Trap itself: When a rising power threatens to displace a ruling one,\n"
            "  the resulting fear makes war the default, not the exception\n"
            "- Fear, Honor, Interest: Thucydides' three drivers of conflict — show which\n"
            "  is operating in each major event\n"
            "- Democracies under pressure: How democratic systems make bad decisions\n"
            "  when driven by fear and populist pressure (the Mytilenean Debate)\n"
            "- Imperial overstretch: The Sicilian Expedition pattern — when ambition\n"
            "  exceeds capability and destroys the overreacher\n"
            "- Plague and collapse: Internal crises accelerate external decline\n\n"
            "Frame the current situation as a Thucydides Trap scenario. Identify who is\n"
            "the established power, who is rising, and whether the trap can be escaped.\n"
            "Reference Thucydides' History of the Peloponnesian War directly."
        ),
        "Taleb": (
            "=== PRIMARY ANALYTICAL LENS: NASSIM TALEB — ANTIFRAGILITY & BLACK SWANS ===\n\n"
            "Frame the narrative through Taleb's concepts of fragility, robustness,\n"
            "and antifragility:\n\n"
            "- Black Swans: Rare, high-impact events that are rationalized in hindsight.\n"
            "  Show what Black Swan is brewing in this story\n"
            "- Antifragility: Some systems GAIN from disorder — identify who benefits\n"
            "  from chaos while others break\n"
            "- Skin in the Game: Who bears the downside risk? Who is making decisions\n"
            "  with asymmetric consequences (upside for them, downside for others)?\n"
            "- The Turkey Problem: The turkey is fed every day and thinks life is great\n"
            "  — until Thanksgiving. Who is the turkey in this story?\n"
            "- Fragility hiding as stability: Systems that appear stable are often\n"
            "  accumulating hidden fragility until catastrophic failure\n"
            "- Fat tails: The extreme outcomes are far more likely than models predict\n\n"
            "Reference Taleb by name. Show that the 'experts' are blind to the fragility\n"
            "they've created. The viewer should question what hidden fragilities exist\n"
            "in their own assumptions about stability."
        ),
        "Girard": (
            "=== PRIMARY ANALYTICAL LENS: RENÉ GIRARD — MIMETIC DESIRE & SCAPEGOATING ===\n\n"
            "Frame the narrative through Girard's mimetic theory — the idea that we\n"
            "desire things not because they're inherently valuable, but because others\n"
            "desire them:\n\n"
            "- Mimetic Desire: We want what others want. Markets, arms races, and\n"
            "  geopolitical competition are mimetic rivalries\n"
            "- Mimetic Rivalry: When two actors desire the same thing, they become\n"
            "  mirrors of each other — each escalating because the other does\n"
            "- The Scapegoat Mechanism: When mimetic rivalry reaches crisis, societies\n"
            "  find a scapegoat to unite against — identify who is being scapegoated\n"
            "  and what crisis triggered it\n"
            "- Sacred Violence: Violence against the scapegoat restores temporary\n"
            "  social order — show how this plays out in trade wars, sanctions, etc.\n"
            "- Interdividual psychology: Identity is formed through others, not in\n"
            "  isolation — actors define themselves by their rivals\n\n"
            "Reference Girard by name. Show how the actors are trapped in mimetic\n"
            "rivalry — becoming the mirror image of what they claim to oppose."
        ),
        "Schmitt": (
            "=== PRIMARY ANALYTICAL LENS: CARL SCHMITT — THE FRIEND-ENEMY DISTINCTION ===\n\n"
            "Frame the narrative through Schmitt's concept that the fundamental category\n"
            "of all politics is the friend-enemy distinction:\n\n"
            "- The Political: Every political act ultimately answers one question —\n"
            "  who is the enemy? Everything else is subordinate\n"
            "- State of Exception: Who has the power to suspend normal rules? The\n"
            "  sovereign is whoever decides the exception\n"
            "- Decisionism: In moments of crisis, someone must DECIDE, and that\n"
            "  decision reveals (or creates) the true power structure\n"
            "- The enemy is not a personal adversary but an existential threat to\n"
            "  a way of life — show how actors construct enemies to justify power\n"
            "- Liberal depoliticization: The attempt to reduce politics to economics\n"
            "  or morality always fails — the friend-enemy distinction returns\n\n"
            "Reference Schmitt's The Concept of the Political. Show how every actor\n"
            "is constructing their 'enemy' to justify their own power moves."
        ),
        "Nietzsche": (
            "=== PRIMARY ANALYTICAL LENS: NIETZSCHE — WILL TO POWER & RESSENTIMENT ===\n\n"
            "Frame the narrative through Nietzsche's concepts of power, morality,\n"
            "and the drives beneath civilization's surface:\n\n"
            "- Will to Power: The fundamental drive is not survival but the expansion\n"
            "  of power and influence — show how actors are driven by this\n"
            "- Master vs Slave Morality: Distinguish between actors who create values\n"
            "  (master morality) and those who define themselves through opposition\n"
            "  (slave morality/ressentiment)\n"
            "- Ressentiment: The weak reframe their weakness as moral superiority.\n"
            "  Show which actors are using 'moral' framing to mask the will to dominate\n"
            "- Genealogy of Morals: The 'moral' framing of geopolitics is itself a\n"
            "  power move — trace whose interests the moral narrative serves\n"
            "- Eternal recurrence: These patterns repeat because the drives are\n"
            "  permanent features of human nature\n"
            "- Übermensch vs Last Man: Who is creating new values vs who is clinging\n"
            "  to comfortable mediocrity?\n\n"
            "Reference Nietzsche by name. Strip away the moral veneer from every\n"
            "actor's public position to reveal the will to power beneath."
        ),
        "Arendt": (
            "=== PRIMARY ANALYTICAL LENS: HANNAH ARENDT — BANALITY OF EVIL ===\n\n"
            "Frame the narrative through Arendt's insight that systemic evil operates\n"
            "through bureaucracy, compliance, and the failure to think:\n\n"
            "- The Banality of Evil: The most dangerous actors aren't ideological\n"
            "  fanatics — they're functionaries who 'just follow orders' and never\n"
            "  question the system they serve\n"
            "- Thoughtlessness: The inability or refusal to think from another's\n"
            "  perspective — show which actors have stopped thinking critically\n"
            "- The public vs private realm: Show how political space is being\n"
            "  colonized by economic/bureaucratic logic\n"
            "- Totalitarian elements: Identify isolation, atomization, and the\n"
            "  destruction of common sense in current events\n"
            "- The right to have rights: Show who is being excluded from the\n"
            "  political community and rendered rightless\n"
            "- Bureaucratic evil vs dramatic evil: The system harms people not\n"
            "  through malice but through indifference and process\n\n"
            "Reference Arendt by name. Show how ordinary compliance enables\n"
            "extraordinary harm. The viewer should question their own complicity\n"
            "in systems they've never examined."
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

    # Append psychological depth to every lens
    return framework + _PSYCH_DEPTH


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


# ---------------------------------------------------------------------------
# Stage 1 prompt: Structured outline
# ---------------------------------------------------------------------------

_OUTLINE_PROMPT_TEMPLATE = """\
You are the narrative architect for Economy FastForward, a YouTube channel
that reveals hidden power systems through the lens of strategic thinkers
like Machiavelli, Robert Greene, Sun Tzu, and Jung.

{FRAMEWORK_LENS_SECTION}

Given this research brief:
<research_brief>
Headline: {HEADLINE}
Thesis: {THESIS}
Executive Hook: {EXECUTIVE_HOOK}
Fact Sheet: {FACT_SHEET}
Historical Parallels: {HISTORICAL_PARALLELS}
Framework Analysis: {FRAMEWORK_ANALYSIS}
Character Dossier: {CHARACTER_DOSSIER}
Narrative Arc: {NARRATIVE_ARC}
Counter Arguments: {COUNTER_ARGUMENTS}
Visual Seeds: {VISUAL_SEEDS}
</research_brief>

{SOURCE_CITATIONS_SECTION}

Create a detailed 6-act outline. Return ONLY valid JSON.

CRITICAL — RETENTION-OPTIMIZED OPENING:
Acts 1 and 2 are the survival zone. You have 120 seconds before 40-60% of
viewers leave. The opening must NOT be a slow build. It must:

1. MICRO-PAYOFF IN FIRST 30 SECONDS: Deliver a genuine insight or revelation
   immediately. Not a tease, not "but first let me explain" — an actual
   "holy shit" moment that rewards the viewer for clicking.

2. PATTERN INTERRUPT AT 60 SECONDS: Just as the viewer thinks they understand
   the story, flip it. "But that's not what's really happening." The second
   layer of the revelation.

3. PSYCHOLOGICAL HOOK AT 90 SECONDS: Connect the geopolitical story to the
   viewer's own psychology. Why does this pattern repeat? Because of something
   in human nature itself. This is where the framework lens first appears —
   not as academic reference but as a mirror the viewer sees themselves in.

4. STAKES ESCALATION AT 120 SECONDS: "And here's why this matters to YOU
   specifically." Personal stakes established before the 2-minute mark.

The viewer should have received THREE micro-payoffs before minute 2:
- A shocking fact or counterintuitive truth (intellectual payoff)
- A framework insight that reframes how they see power (psychological payoff)
- A personal stakes connection (emotional payoff)

After this 2-minute hook zone, the script can breathe and build depth.

JSON STRUCTURE:
{{
  "acts": [
    {{
      "act_number": 1,
      "title": "Short evocative title",
      "timestamp": "0:00-1:30",
      "target_words": 225,
      "beats": [
        "Beat 1: [specific story beat with what happens and why]",
        "Beat 2: [next beat]"
      ],
      "framework_references": [
        "Specific framework concept to reference and HOW to apply it"
      ],
      "research_elements": [
        "Which facts from fact_sheet to cite here",
        "Which historical parallel to introduce/develop here"
      ],
      "sources_to_cite": ["Which sources to reference in this act"],
      "hook_strategy": "How this act maintains/builds viewer retention",
      "psychological_layer": "What psychological insight about power/human nature to weave in"
    }}
  ],
  "framework_arc": "How the framework lens builds across all 6 acts",
  "historical_parallel_placements": "Which acts reference which parallels",
  "audience_address_moments": ["Specific moments for direct 'you/your' address"]
}}
"""

# ---------------------------------------------------------------------------
# Stage 2 prompt: Per-act writing
# ---------------------------------------------------------------------------

_ACT_PROMPT_TEMPLATE = """\
You are the scriptwriter for Economy FastForward. You are writing ACT {ACT_NUMBER}
of a 6-act narration script.

=== CHANNEL VOICE — NON-NEGOTIABLE ===
This is NOT journalism. This is a DARK REVELATION. The viewer should feel
like an insider seeing what the masses cannot. Every sentence carries weight.

- DARK REVELATION TONE: "Here's what they don't want you to understand"
- EMPIRE / SOVEREIGN FRAMING: Companies and nations are empires executing
  strategies identical to historical power plays
- HISTORICAL PARALLELS AS RECURRING ANCHORS: Not one-time mentions — they
  prove this is a PATTERN
- DIRECT AUDIENCE ADDRESS: "Your feed. Your perception. Your reality."
  The viewer is personally implicated
- PSYCHOLOGICAL DEPTH: Every event reveals something about human nature
  itself — the drives, shadows, and tribal instincts that make these
  patterns inevitable

Your audience: Ambitious 18-35 males drawn to Machiavelli, Greene, Sun Tzu,
Jung. They value intelligence and strategy. They're skeptical of mainstream
narratives. They want to understand how power REALLY works — including the
power dynamics operating on their own psychology.

{FRAMEWORK_LENS_SECTION}

<research_brief>
{RESEARCH_BRIEF}
</research_brief>

{SOURCE_CITATIONS_SECTION}

<full_outline>
{FULL_OUTLINE}
</full_outline>

<previous_acts>
{PREVIOUS_ACTS}
</previous_acts>

<act_instructions>
Act {ACT_NUMBER}: {ACT_TITLE}
Timestamp: {TIMESTAMP}
Target words: {TARGET_WORDS}

Beats to hit:
{BEATS}

Framework references for this act:
{FRAMEWORK_REFERENCES}

Research elements to include:
{RESEARCH_ELEMENTS}

Sources to cite:
{SOURCES_TO_CITE}

Hook/retention strategy:
{HOOK_STRATEGY}

Psychological layer:
{PSYCHOLOGICAL_LAYER}
</act_instructions>

Write ACT {ACT_NUMBER} as continuous narration. Start with the act marker:
[ACT {ACT_NUMBER} — {ACT_TITLE} | {TIMESTAMP} | ~{TARGET_WORDS} words]

Rules:
- Write as spoken narration — no stage directions, no "[pause]" markers
- Do NOT include image descriptions
- Every factual claim must come from the research brief
- Maintain continuity with previous acts (reference callbacks where natural)
- Hit the target word count (±10%)
- The framework lens must appear in this act — it's the analytical backbone
- Weave source citations naturally ("According to Reuters...")
{ADDITIONAL_RULES}
"""

# Act-specific additional rules
_ACT_SPECIFIC_RULES = {
    1: (
        "\nCRITICAL — RETENTION ZONE:\n"
        "- First sentence must create immediate tension — a dark revelation\n"
        "- Deliver a micro-payoff (genuine insight) within 30 seconds (~75 words)\n"
        "- Pattern interrupt by 60 seconds — flip the viewer's assumption\n"
        "- Framework lens appears within 60 seconds — not academic, but as a\n"
        "  mirror revealing something about human nature\n"
        "- Personal stakes by 90 seconds — \"And this is where it touches YOUR life\"\n"
        "- The viewer must have received 3 micro-payoffs before this act ends:\n"
        "  intellectual, psychological, emotional\n"
        "- Do NOT do a slow build. Do NOT say \"but first, let me explain.\"\n"
        "  Start IN the revelation."
    ),
    2: (
        "\nCONTINUATION OF HOOK ZONE (viewer still deciding whether to stay):\n"
        "- Continue the revelation momentum from Act 1\n"
        "- Build factual foundation but KEEP delivering insights — every paragraph\n"
        "  must contain a \"wait, what?\" moment, not just setup\n"
        "- Each fact should be framed through the power dynamics lens — not\n"
        "  \"here's what happened\" but \"here's what this REVEALS about how power works\"\n"
        "- Drop the first deep historical parallel as a pattern proof\n"
        "- The viewer should feel increasingly like an insider by the end of this act"
    ),
    5: (
        "\nMAXIMUM STAKES — PERSONAL IMPLICATIONS:\n"
        "- Use direct audience address at least twice: \"your savings\", \"your data\",\n"
        "  \"your perception of reality\"\n"
        "- Apply the framework to predict WHAT COMES NEXT with specific scenarios\n"
        "- Steel-man the counter arguments genuinely — then use the framework to\n"
        "  explain why the evidence points your direction\n"
        "- The psychological layer here should make the viewer question their own\n"
        "  assumptions and biases\n"
        "- The viewer should feel genuinely unsettled"
    ),
    6: (
        "\nTHE LESSON — PERMANENT UPGRADE:\n"
        "- Specific, actionable takeaway — not \"be aware\" but \"here's how you\n"
        "  position yourself\" or \"here's what to watch for\"\n"
        "- Final framework reference as the key insight\n"
        "- Circle back to historical parallel one last time — the pattern closes\n"
        "- End with a line that lingers — the kind that makes someone sit in\n"
        "  silence after the video ends\n"
        "- The psychological insight should feel like a permanent upgrade to how\n"
        "  the viewer sees the world — and themselves"
    ),
}


def _parse_outline_json(raw: str) -> dict:
    """Extract and parse the JSON outline from the LLM response.

    Handles common issues like markdown code fences around the JSON.
    """
    text = raw.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        # Remove opening fence (```json or ```)
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        # Remove closing fence
        text = re.sub(r"\n?```\s*$", "", text)

    return json.loads(text)


def _format_research_brief_text(brief: dict) -> str:
    """Format the research brief dict into a text block for the act prompt."""
    parts = []
    for key in (
        "headline", "thesis", "executive_hook", "fact_sheet",
        "historical_parallels", "framework_analysis", "character_dossier",
        "narrative_arc", "counter_arguments", "visual_seeds",
    ):
        label = key.replace("_", " ").title()
        value = brief.get(key, "")
        if value:
            parts.append(f"{label}: {value}")
    return "\n".join(parts)


async def generate_script_staged(
    anthropic_client,
    brief: dict,
    model: str = "claude-sonnet-4-5-20250929",
) -> dict:
    """Generate script using 2-stage outline → per-act approach.

    Stage 1: Generate structured outline (1 call)
    Stage 2: Write each act individually with full context (6 calls)

    Falls back to monolithic generate_script() if staged approach fails.

    Returns:
        {
            "script": str (full script, all acts concatenated),
            "outline": dict (the structured outline),
            "validation": dict (word count, act count, issues),
            "acts": dict (individual act texts keyed by act number),
        }
    """
    framework_angle = brief.get("framework_angle", "")
    framework_lens = _build_framework_lens_section(framework_angle)
    source_citations = _build_source_citations_section(brief)

    # =====================================================================
    # STAGE 1: Generate structured outline
    # =====================================================================
    logger.info("Stage 1: Generating structured outline...")
    print("  📋 Stage 1: Generating structured outline...")

    outline_prompt = _OUTLINE_PROMPT_TEMPLATE.format(
        FRAMEWORK_LENS_SECTION=framework_lens,
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
        SOURCE_CITATIONS_SECTION=source_citations,
    )

    outline = None
    for attempt in range(2):  # 1 retry
        try:
            raw_outline = await anthropic_client.generate(
                prompt=outline_prompt,
                model=model,
                max_tokens=2000,
                temperature=0.7,
            )
            outline = _parse_outline_json(raw_outline)
            if "acts" not in outline or len(outline["acts"]) < 6:
                raise ValueError(
                    f"Outline has {len(outline.get('acts', []))} acts, expected 6"
                )
            logger.info(f"Stage 1 complete: {len(outline['acts'])} acts outlined")
            print(f"  ✅ Outline generated: {len(outline['acts'])} acts")
            break
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning(f"Outline attempt {attempt + 1} failed: {e}")
            print(f"  ⚠️  Outline attempt {attempt + 1} failed: {e}")
            if attempt == 1:
                # Exhausted retries — fall back to monolithic generation
                logger.warning("Falling back to monolithic generate_script()")
                print("  🔄 Falling back to monolithic script generation...")
                fallback = await generate_script(anthropic_client, brief, model=model)
                fallback["outline"] = None
                fallback["acts"] = extract_acts(fallback["script"])
                return fallback

    # =====================================================================
    # STAGE 2: Write each act individually
    # =====================================================================
    logger.info("Stage 2: Writing individual acts...")
    print("  ✍️  Stage 2: Writing individual acts...")

    research_brief_text = _format_research_brief_text(brief)
    outline_json_str = json.dumps(outline, indent=2)

    written_acts = {}  # act_number -> text
    act_failures = 0

    for act_info in sorted(outline["acts"], key=lambda a: a["act_number"]):
        act_num = act_info["act_number"]
        act_title = act_info.get("title", f"Act {act_num}")
        timestamp = act_info.get("timestamp", "")
        target_words = act_info.get("target_words", 600)

        # Build accumulated previous acts text
        previous_acts_text = ""
        if written_acts:
            previous_acts_text = "\n\n".join(
                written_acts[n] for n in sorted(written_acts.keys())
            )

        # Format list fields
        beats_text = "\n".join(act_info.get("beats", []))
        fw_refs_text = "\n".join(act_info.get("framework_references", []))
        research_text = "\n".join(act_info.get("research_elements", []))
        sources_text = "\n".join(act_info.get("sources_to_cite", []))
        hook_text = act_info.get("hook_strategy", "")
        psych_text = act_info.get("psychological_layer", "")

        additional_rules = _ACT_SPECIFIC_RULES.get(act_num, "")

        act_prompt = _ACT_PROMPT_TEMPLATE.format(
            ACT_NUMBER=act_num,
            FRAMEWORK_LENS_SECTION=framework_lens,
            RESEARCH_BRIEF=research_brief_text,
            SOURCE_CITATIONS_SECTION=source_citations,
            FULL_OUTLINE=outline_json_str,
            PREVIOUS_ACTS=previous_acts_text or "(This is the first act)",
            ACT_TITLE=act_title,
            TIMESTAMP=timestamp,
            TARGET_WORDS=target_words,
            BEATS=beats_text,
            FRAMEWORK_REFERENCES=fw_refs_text,
            RESEARCH_ELEMENTS=research_text,
            SOURCES_TO_CITE=sources_text,
            HOOK_STRATEGY=hook_text,
            PSYCHOLOGICAL_LAYER=psych_text,
            ADDITIONAL_RULES=additional_rules,
        )

        # Try writing this act (up to 2 retries)
        act_text = None
        for retry in range(3):
            try:
                act_text = await anthropic_client.generate(
                    prompt=act_prompt,
                    model=model,
                    max_tokens=2000,
                    temperature=0.8,
                )
                if not act_text or len(act_text.split()) < 50:
                    raise ValueError(
                        f"Act {act_num} too short: {len((act_text or '').split())} words"
                    )
                break
            except Exception as e:
                logger.warning(f"Act {act_num} attempt {retry + 1} failed: {e}")
                print(f"  ⚠️  Act {act_num} attempt {retry + 1} failed: {e}")
                if retry == 2:
                    act_failures += 1
                    logger.error(f"Act {act_num} failed after 3 attempts")
                    print(f"  ❌ Act {act_num} failed after 3 attempts")

        if act_text:
            written_acts[act_num] = act_text
            word_count = len(act_text.split())
            print(f"  ✅ Act {act_num} written: {word_count} words")

    # Check if too many acts failed
    if act_failures >= 3:
        logger.warning(
            f"{act_failures} acts failed — falling back to monolithic generation"
        )
        print(f"  🔄 {act_failures} acts failed — falling back to monolithic generation...")
        fallback = await generate_script(anthropic_client, brief, model=model)
        fallback["outline"] = outline
        fallback["acts"] = extract_acts(fallback["script"])
        return fallback

    # =====================================================================
    # Assemble final script
    # =====================================================================
    full_script = "\n\n".join(
        written_acts[n] for n in sorted(written_acts.keys())
    )

    validation = validate_script(full_script)

    logger.info(
        f"Staged generation complete: {validation['word_count']} words, "
        f"{validation['act_count']} acts, {act_failures} failures"
    )
    print(
        f"  📊 Final script: {validation['word_count']} words, "
        f"{validation['act_count']} acts"
    )

    return {
        "script": full_script,
        "outline": outline,
        "validation": validation,
        "acts": written_acts,
    }
