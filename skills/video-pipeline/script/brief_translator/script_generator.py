"""Script Generation (Step 2).

Transforms a validated research brief into a narration script
with dynamic act structure, micro-payoff architecture, and act markers.

Word counts and act counts are driven by VideoConfig (pipeline_config.py).
Script profiles (script_profiles/) control the editorial voice — tone,
structural laws, act structure, validation rules, and language constraints.

Legacy constants are kept as defaults for backward compatibility when no
config or profile is provided.
"""

import logging
import re
from pathlib import Path
from typing import Optional, TYPE_CHECKING
from orchestrator.pipeline_constants import Models

if TYPE_CHECKING:
    from orchestrator.pipeline_config import VideoConfig
    from shared.profiles.script.schema import ScriptProfile

logger = logging.getLogger(__name__)

PROMPT_TEMPLATE_PATH = Path(__file__).parent / "prompts" / "script.txt"

# Legacy defaults — used when no VideoConfig is provided
SCRIPT_MIN_WORDS = 2200
SCRIPT_MAX_WORDS = 3200
SCRIPT_TARGET_WORDS = 2800
EXPECTED_ACT_COUNT = 6

# Act marker regex pattern — full format: [ACT 1 — Title | 0:00 - 4:10 | ~500 words]
# The timestamp range separator must accept en/em dashes too (—–), not just a
# hyphen: the model routinely emits "0:00–1:45" (en-dash). When it only matched
# a hyphen, en-dash scripts parsed as 0 acts → 0 scene rows written → the split
# step 500'd ("No scripts found") and the UI showed "Script Not Generated Yet"
# despite a perfectly good script. Mirror the title separator's [—–-] class.
ACT_MARKER_PATTERN = re.compile(
    r"\[ACT\s+(\d+)\s*[—–-]\s*(.*?)\s*\|\s*([\d:]+\s*[—–-]\s*[\d:]+)\s*(?:\|\s*~?\s*(\d+)\s*words?)?\s*\]",
    re.IGNORECASE,
)

# Fallback regex for simple markers: [ACT 1], [ACT 2], etc.
# Used when script is reassembled from Airtable records without full act metadata.
ACT_MARKER_SIMPLE_PATTERN = re.compile(
    r"\[ACT\s+(\d+)\s*\]",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Prompt overrides — appended after the base template to update act structure,
# inject micro-payoff architecture, framework revelation engine, and
# per-act rules.  Keeps script.txt untouched.
# ---------------------------------------------------------------------------

_ACT_STRUCTURE_OVERRIDE_LEGACY = """\
=== SCRIPT PARAMETERS ===

Target total: ~2,800 words (~17 minutes at ~160 words/min).
Minimum: 2,200 words (~14 min). Maximum: 3,200 words (~20 min).

Shape the script in clear sections (acts), and let the subject and audience
decide how many and what each one does. Whatever the shape:
- Open with a concrete hook that sets up the through-line.
- Build with escalating value or tension — never plateau.
- Sustain retention with a payoff every ~90 seconds, and open a loop at every
  section transition.
- Land the payoff the opening promised.
- Close on a deliberate final beat (never a subscribe plea).

Mark each section: [ACT X — TITLE | TIMESTAMP | ~WORD COUNT].
"""


def _build_act_structure_override(config: Optional["VideoConfig"] = None) -> str:
    """Build act structure override dynamically from VideoConfig."""
    if config is None:
        return _ACT_STRUCTURE_OVERRIDE_LEGACY

    from orchestrator.pipeline_config import ACT_TEMPLATES, get_act_word_targets

    act_targets = get_act_word_targets(config)
    duration_min = config.video_length_minutes

    lines = [
        "=== UPDATED SCRIPT PARAMETERS — THESE OVERRIDE THE ACT STRUCTURE ABOVE ===\n",
        f"This is a {duration_min}-minute video. Follow these targets:\n",
        f"Target total: ~{config.total_script_words} words (~{duration_min} minutes at 150 words/min)",
        f"Minimum: {config.script_min_words} words. Maximum: {config.script_max_words} words.\n",
        f"This video has {config.act_count} acts (NOT 6 unless specified).\n",
        "Act word targets:",
    ]

    cumulative_seconds = 0
    for at in act_targets:
        act_seconds = int(config.total_seconds * at["pct"])
        start_ts = f"{cumulative_seconds // 60}:{cumulative_seconds % 60:02d}"
        cumulative_seconds += act_seconds
        end_ts = f"{cumulative_seconds // 60}:{cumulative_seconds % 60:02d}"
        lines.append(
            f"- Act {at['act_number']} ({at['name']}): ~{at['word_target']} words "
            f"({start_ts}-{end_ts}) — {at['purpose']}"
        )

    return "\n".join(lines) + "\n"

_MICRO_PAYOFF_ARCHITECTURE = """\
=== MICRO-PAYOFF ARCHITECTURE — NON-NEGOTIABLE ===

Every ~90 seconds of narration must deliver a payoff — a specific fact, a \
turn, a vivid image, or a connection the viewer didn't have a moment ago. \
The viewer should never go more than ~90 seconds without being rewarded for \
staying.

Structure within each beat (about 60-90 seconds):

SETUP (first 1-2 sentences): Open the beat on something concrete and \
specific — a claim, a moment, a question. Not a warm-up; the first line \
already does work.

BUILD (middle): Develop it with specific detail. Give the precise example, \
the exact moment, the real number — not vague intensifiers. Each detail \
should advance the through-line.

PAYOFF (last 1-2 sentences): The reward — the "oh, that makes sense" or the \
detail that lands. This is what the viewer stayed for.

BRIDGE (final sentence): The payoff naturally raises a NEW question or \
promise that pulls the viewer into the next beat. This is the open loop.

BAD example (vague, no payoff, stalls the viewer):
"And what happened next would change everything. But first, let's \
understand the background..."

GOOD example (concrete setup, specific build, real payoff, forward bridge):
"Most people add the garlic first. That's exactly why it burns. Garlic \
scorches in about 30 seconds in a hot pan — long before the onions are \
soft. So the fix is almost insultingly simple: onions in first, garlic in \
last, off the heat if you have to. Do that and the whole dish stops \
tasting bitter. But there's one more thing happening in that pan that \
nobody tells you about — and it decides whether the sauce ever comes \
together."
"""

_FRAMEWORK_REVELATION_ENGINE = """\
=== RECURRING LENS / FRAMEWORK — SHOW IT, DON'T LECTURE IT ===

If this channel uses a recurring lens, framework, or idea to make sense of \
its subject, that lens should ORGANIZE the script quietly — it is not the \
subject of the script and it is never a lecture.

HOW TO WEAVE A LENS IN:
- Show the idea in action through concrete specifics before you ever name \
it. Let the viewer feel the pattern first.
- If you name the lens at all, name it as CONFIRMATION of what the viewer \
has already seen — not as new theory dropped on them. Keep it to a sentence, \
then return immediately to the concrete story.
- Use the lens as a tool the viewer can reuse ("when you see X, that's Y \
happening again"), not as terminology to memorize.

BAD (lens as lecture — kills momentum):
"The author wrote that successful teaching requires comprehensible input \
slightly above the learner's level. What we're applying here is a textbook \
case of stage-three acquisition theory, in which..."

GOOD (lens invisible, pattern visible):
"Notice you understood that sentence without translating it. That's not \
luck — it's because every new word sat next to three you already knew. \
That's the whole trick, and we'll use it on purpose for the next ten \
minutes."

CRITICAL: The lens explains the content; it never replaces it. If you find \
yourself explaining theory or terminology for more than a moment, stop and \
return to the concrete material the viewer actually came for. Keep direct \
references to any named framework to a minimum — the rest is showing, not \
telling.
"""

_FRAMEWORK_SELECTION_RULES = """\
=== ANGLE / LENS SELECTION — PER-VIDEO ===

Before writing the outline, decide the ONE angle or lens that makes this \
specific subject most worth watching for this audience. The right angle is \
the one that creates the strongest reason to keep watching — the clearest \
through-line and the most satisfying payoff.

If the channel provides recurring frameworks or signature segments, choose \
the one that best fits this subject; otherwise pick the angle the material \
itself suggests. Do not force a framework that doesn't fit.

Selection criteria:
- Which angle gives the cleanest through-line — one spine from hook to payoff?
- Which angle creates the strongest reason for THIS audience to care?
- Which angle gives the viewer something they can use or remember afterward?

State your choice at the top of the outline:
ANGLE: [Name] — [One sentence on why this angle is the most compelling way \
into this subject for this audience]

REMEMBER: A recurring lens organizes the script quietly. Show it in action \
through concrete specifics; name it only as confirmation, never as a lecture.
"""

_FRAMEWORK_PSYCH_SEPARATION = """\
=== EMOTIONAL ARC — THE VIEWER'S JOURNEY ===

A script is not just information in order; it is an emotional journey. The \
viewer should FEEL something change from the first beat to the last. Decide \
the arc that fits this subject and audience, and make every section move it \
forward.

How to build the arc:
- Open by making the viewer FEEL the question, curiosity, or stakes — not \
just learn the topic. Give them a reason to care in the first beat.
- Through the middle, deepen that feeling step by step. Each section should \
shift the viewer's emotional state, not just add facts: curiosity → \
understanding, confusion → clarity, tension → release.
- The payoff is emotional as well as informational: the satisfying answer, \
the click of understanding, the resolution the opening promised.
- End on the feeling that fits this channel — most often a sense of being \
rewarded, capable, or moved. The viewer should leave better off than they \
arrived.

CRITICAL: The arc must resolve. The viewer must leave feeling the payoff \
landed — never stranded, never cheated, never told a problem with no way \
through it.
"""

_CINEMATIC_VOICE_RULES = """\
=== IMMERSIVE VOICE — WRITE SCENES, NOT SUMMARIES ===

The difference between narration that holds a viewer and narration they \
click away from is immersion. Don't report the subject from a distance — \
put the viewer inside it. Make them see, hear, and feel each beat before \
(or as) you explain it.

1. CONCRETE, SCENE-DRIVEN OPENINGS:
Open every section on something specific the viewer can picture — a moment, \
a place, a person, a concrete example — in the first 1-2 sentences. Ground \
them before you abstract.

GOOD: "You crack the egg into the pan and it slides instead of sizzling. \
That's the whole problem, right there."
BAD: "Temperature control is an important factor in cooking eggs."

2. ACTIVE FRAMING:
Replace flat, passive statements with active, vivid ones — same fact, \
better delivery.

GOOD: "The dough fights back when you knead it too soon."
BAD: "Premature kneading can be counterproductive."

3. SCENE TRANSITIONS:
Move between sections like a film editor cutting between shots — a clean \
cut to the next concrete moment — not with abstract connective filler.

GOOD: "Now move to the pan that's been waiting on the back burner."
BAD: "But here's what none of this explains."

4. PUT THE VIEWER IN THE MOMENT:
Each section should have at least one beat where the viewer is placed \
inside the experience — watching it happen, doing it themselves, feeling \
the moment. This is the "you are here" beat.

GOOD: "Picture the first word landing and you actually understanding it, \
no translation."

5. SENTENCE RHYTHM:
Short fragments during action and reveals. Longer, flowing sentences during \
explanation and context. The rhythm itself creates tension and release.

ACTION: "The timer beeps. You lift the lid. Steam everywhere."
EXPLANATION: "What's actually happening underneath is that the starches \
have finally absorbed enough water to hold their shape."

6. THE "YOU" PIVOT — USE IT DELIBERATELY:
Direct address to the viewer ("you", "your") is powerful precisely because \
it's not constant. Reserve the strongest "this is about YOU" moment for \
where it lands hardest, rather than scattering it through every line.

7. ONE VIVID IMAGE PER SECTION:
Each section earns one image that could be a still frame — a face, a place, \
an object, a moment — described in enough sensory detail that the viewer \
can see it. That image carries the section's point.

8. FORWARD PULL:
End every section (except the last) with explicit forward momentum. The \
final sentence should open a loop — genuine curiosity about what comes next.

=== THE APEX — THE ONE LINE THEY KEEP ===

Most strong videos have a single moment where the piece stops being about \
the specific topic and becomes a truth the viewer carries away. This is the \
reward for staying.

THREE RULES:
A) BUILD TOWARD IT: Earlier sections set up a question, gap, or tension the \
viewer wants resolved.
B) DELIVER IT THROUGH SOMETHING CONCRETE: Land the insight on a specific \
moment, example, or person — not as abstract theory.
C) SIMPLE ENOUGH TO REPEAT: If the viewer couldn't say it back to a friend \
in one sentence, rewrite it.

GOOD: "You don't need a bigger knife. You need a sharper one."
BAD: "Edge geometry and honing angle jointly determine cutting efficiency."

=== MICRO-INSIGHT BREADCRUMBS (EVERY SECTION) ===

Every section ends with one simple truth the viewer takes with them. These \
build toward the apex, but each one also works alone — a viewer who leaves \
early still learned something they can use.

RULES:
- One sentence. Two at most.
- Plain language only. No jargon, no terminology to memorize.
- Delivered through the concrete material, not as detached commentary.
- Must pass the "text it to a friend" test.

GOOD: "Salt early and you season the food; salt late and you just season \
the surface."

=== THE CLOSE — AN ENDING, NOT A SIGN-OFF ===

The final section is a deliberate ending, not a checklist or a sign-off. \
Land the payoff the opening promised and leave the viewer with the feeling \
that fits this channel — resolved, rewarded, or moved. Deliver any takeaways \
through the concrete material, not as a bulleted list, and never close on a \
subscribe plea.
"""

_STRICT_GROUNDING_RULE = """\
=== STRICT FACTUAL GROUNDING RULE — NON-NEGOTIABLE ===

Every factual claim, name, place, event, date, and number in the script MUST \
come directly from the research brief / source material provided. You may NOT \
introduce:
- People, places, organizations, or events not mentioned in the research
- Numbers, amounts, or statistics not in the source material
- Examples or parallels not supported by the source material
- Dates or timelines not supported by the source material

If you need a transition, analogy, or rhetorical device, build it only from \
the material in the brief. Do NOT substitute similar-sounding names or swap in \
a related-but-different topic.

Before finalizing each section, verify: is every proper noun, date, number, \
and event traceable to the research brief? If not, remove it or replace it \
with something that is.

=== CRITICAL — FACTUAL GROUNDING (EXTENDED) ===

1. Every specific claim (names, numbers, dates, events, quotes, technical \
details) MUST come from the brief. If a fact is not in the brief, DO NOT \
USE IT.

2. You may describe HOW something happened vividly, but you MUST NOT invent \
WHAT happened. You can dramatize a sourced event; you cannot invent an event \
that isn't in the sources.

3. Never fabricate specifics to fill a narrative gap. If the brief does not \
explain HOW something happened, hedge honestly ("the records suggest", \
"it's not fully known") rather than presenting a guess as fact.

4. Examples, parallels, and case studies must come from the brief. Do not \
invent additional ones.

5. If a beat needs content the brief does not provide, lean on the chosen \
angle/lens to EXPLAIN what is sourced, rather than inventing new facts. The \
lens is your gap-filler, not fabricated detail.

6. After writing each beat, mentally verify: "Could I point to a specific \
place in the brief for every factual claim here?" If not, rewrite.

WHAT YOU CAN CREATE:
- Pacing, sentence structure, rhetorical questions
- Emotional and vivid framing of sourced facts
- Connections between sourced facts via the chosen angle
- Metaphors and analogies that illustrate sourced ideas

WHAT YOU CANNOT CREATE:
- Events that did not happen
- Specifics not in the brief
- Quotes from people unless quoted in the brief
- Numbers or statistics not in the brief
"""

_ACT_SPECIFIC_RULES = """\
=== SECTION CRAFT — APPLIES TO EVERY SECTION ===

These rules apply to each section/act of the script, whatever the subject \
and however many sections it has. Let the material and the audience decide \
the shape; apply this craft within it.

OPENING SECTION:
Open cold on something concrete the viewer can picture or feel — a moment, a \
question, a vivid example. Establish the through-line: the single question, \
story, or promise the whole script will pay off. Give the viewer a reason to \
care immediately. End the section on an open loop that pulls them forward.

MIDDLE SECTIONS:
Each middle section must ADVANCE the story relative to the section before it — \
add new information, a complication, a turn, or higher stakes. Never plateau and \
never restate: do NOT restage the previous beat in a new setting (the same \
character doing the same thing somewhere else, or the same point remade with \
fresh examples). If a section would repeat the one before it, escalate or turn \
instead. Ground every claim in the source material. Deliver a payoff at least \
every ~90 seconds and end each section on an open loop into the next. Specifics \
over vagueness, always.

PAYOFF SECTION:
Deliver the resolution, answer, or transformation the opening promised. This \
is the emotional and informational high point — the moment the viewer stayed \
for. Make it land through concrete material, not abstract summary.

FINAL SECTION:
A deliberate ending, not a sign-off. Close the through-line, leave the viewer \
with the feeling that fits this channel (rewarded, capable, or moved), and \
give any takeaway through the concrete material rather than a bulleted list. \
The final line should feel intentional and complete.

GOOD close: a line that resolves the opening and lingers — the kind of ending \
that makes the whole piece feel finished.
BAD close: trailing off, a flat recap, or "like and subscribe."

EVERY section: open concretely, escalate, pay off, and pull forward (except \
the final section, which lands the ending).
"""


def load_script_prompt() -> str:
    """Load the script generation prompt template."""
    return PROMPT_TEMPLATE_PATH.read_text()


def _build_framework_lens_section(framework_angle: str) -> str:
    """Build the lens/angle instructions for the script prompt.

    A channel may steer each video through a recurring lens or angle (a free-text
    ``framework_angle`` carried on the research brief). This is NEUTRAL: it does
    not hardcode any particular subject matter or named thinker — it simply tells
    the writer to apply the channel's chosen angle consistently and to show it
    through concrete material rather than lecture it. When the brief carries no
    angle, returns "" so the script craft drives the shape on its own.
    """
    angle = (framework_angle or "").strip()
    if not angle:
        return ""

    return (
        "=== ANGLE / LENS FOR THIS VIDEO ===\n\n"
        f"Tell this story through the following lens: {angle}\n\n"
        "Apply it consistently so the whole script shares one point of view, but "
        "keep it INVISIBLE craft, not a lecture:\n"
        "- Show the lens in action through concrete, specific material before you "
        "ever name it. Let the viewer feel the pattern first.\n"
        "- If you name the lens, do it once, as confirmation of what the viewer "
        "has already seen — then return immediately to the concrete story.\n"
        "- Use the lens to connect and explain the sourced material; never let it "
        "replace the material or become the subject of the video.\n"
    )


def _build_writer_guidance_section(brief: dict) -> str:
    """Build the writer guidance section for the prompt.

    Writer Guidance is a per-video override field that lets the user inject
    specific instructions for the script (e.g., "Focus on the personal angle",
    "Use more historical parallels", "Emphasize the conspiracy angle").
    """
    writer_guidance = brief.get("writer_guidance", "")
    if not writer_guidance:
        return ""

    return (
        "=== WRITER GUIDANCE — PER-VIDEO OVERRIDE ===\n\n"
        "The following instructions are specific to THIS video and override "
        "general guidelines when they conflict:\n\n"
        f"{writer_guidance}\n\n"
        "Apply these instructions throughout the script while maintaining "
        "the channel's voice and the factual grounding rules."
    )


def _build_source_citations_section(brief: dict) -> str:
    """Build the source citations instruction section for the prompt."""
    source_urls = brief.get("source_urls", "")
    source_bib = brief.get("source_bibliography", "")

    sources = source_urls or source_bib
    if not sources:
        return ""

    return (
        "=== SOURCE CITATIONS — LOCKED TO RESEARCH ===\n\n"
        "CRITICAL RULE: You may ONLY cite sources that appear in [brackets] next to "
        "facts in the research brief. If a fact has [EIA 2024] next to it, cite it as "
        "'According to the EIA...' — NOT another source.\n\n"
        "FORBIDDEN:\n"
        "- Do NOT cite a source that doesn't appear in the research brief\n"
        "- Do NOT guess which source supports a fact if no [bracket] is present\n"
        "- Do NOT pluralize singular sources ('one CEO' stays 'one CEO', not 'CEOs')\n"
        "- Do NOT cross-attribute (historical fact to fact_sheet source)\n\n"
        "If a fact has NO [Source] tag, use vague attribution: 'According to industry "
        "reports...' or state the fact without attribution.\n\n"
        "Aim for at least 4-6 source citations across the full script. Each citation "
        "must match a [bracketed source] from the fact_sheet.\n\n"
        f"Available sources from research:\n{sources}\n"
    )


_SELF_VALIDATION_INSTRUCTION = """
=== SELF-VALIDATION (MANDATORY) ===

After writing the script, output a validation block. For EACH source citation in your
script, verify it matches a [bracketed source] from the fact_sheet. For EACH act
transition (Acts 1-5), verify there's a forward-selling cliffhanger.

Output at the END of your response (after the full script):
```json
{
  "self_validation": {
    "source_citations_verified": true,
    "citations_used": ["EIA 2024", "Reuters March 2026"],
    "cliffhangers_present": {"act_1": true, "act_2": true, "act_3": true, "act_4": true, "act_5": true},
    "all_passed": true
  }
}
```

If any check fails, FIX IT before outputting the final script. Do not output a script
with unverified source attributions or missing cliffhangers.
"""


def _parse_self_validation(response_text: str) -> dict:
    """Extract self-validation JSON from script response.

    Returns:
        Parsed validation dict, or empty dict if parsing fails.
    """
    import re
    import json

    # Look for JSON block at end of response
    match = re.search(
        r'```json\s*(\{.*?"self_validation".*?\})\s*```',
        response_text,
        re.DOTALL,
    )
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    return {}


def _strip_validation_json(script_text: str) -> str:
    """Remove the self-validation JSON block from the script text."""
    import re

    return re.sub(
        r'```json\s*\{.*?"self_validation".*?\}\s*```',
        '',
        script_text,
        flags=re.DOTALL,
    ).strip()


def build_script_prompt(
    brief: dict,
    config: Optional["VideoConfig"] = None,
    profile: Optional["ScriptProfile"] = None,
) -> str:
    """Build the script generation prompt from a research brief.

    Args:
        brief: Validated research brief dict.
        config: Optional VideoConfig for dynamic word counts and act structure.
            When None, falls back to legacy 6-act / 2800-word defaults.
        profile: Optional ScriptProfile for editorial voice. When provided,
            the voice/tone preamble is assembled from the profile instead of
            the static ``prompts/script.txt`` template.
    """
    # Build framework lens section based on Framework Angle field
    framework_angle = brief.get("framework_angle", "")
    framework_lens = _build_framework_lens_section(framework_angle)

    # Build source citations section
    source_citations = _build_source_citations_section(brief)

    if profile is not None:
        # Assemble the voice preamble from the profile
        from shared.profiles.script.schema import build_script_system_prompt

        preamble = build_script_system_prompt(profile)

        # Insert the framework lens and research brief
        # IMPORTANT: Cinematic voice rules come SECOND (after role identity)
        # so Claude internalizes voice/tone BEFORE structural constraints.
        rendered = preamble + "\n\n"
        rendered += _CINEMATIC_VOICE_RULES + "\n\n"

        # Inject writer guidance if present (per-video override)
        writer_guidance_section = _build_writer_guidance_section(brief)
        if writer_guidance_section:
            rendered += writer_guidance_section + "\n\n"

        if framework_lens:
            rendered += framework_lens + "\n\n"

        rendered += (
            "<research_brief>\n"
            f"Headline: {brief.get('headline', '')}\n"
            f"Thesis: {brief.get('thesis', '')}\n"
            f"Executive Hook: {brief.get('executive_hook', '')}\n"
            f"Fact Sheet: {brief.get('fact_sheet', '')}\n"
            f"Historical Parallels: {brief.get('historical_parallels', '')}\n"
            f"Framework Analysis: {brief.get('framework_analysis', '')}\n"
            f"Character Dossier: {brief.get('character_dossier', '')}\n"
            f"Narrative Arc: {brief.get('narrative_arc', '')}\n"
            f"Counter Arguments: {brief.get('counter_arguments', '')}\n"
            f"Visual Seeds: {brief.get('visual_seeds', '')}\n"
            "</research_brief>"
        )

        if source_citations:
            rendered += "\n\n" + source_citations

        # Use profile's word count targets or fall back to config/legacy
        v = profile.validation
        min_w = config.script_min_words if config else v.min_words
        max_w = config.script_max_words if config else v.max_words
        target_w = config.total_script_words if config else (min_w + max_w) // 2
        act_count = config.act_count if config else profile.act_structure.get("act_count", 6)

        rendered += (
            f"\n\nWrite a complete narration script (~{target_w} words). "
            f"Minimum: {min_w} words. Maximum: {max_w} words.\n"
            f"Structure it in {act_count} acts with clear markers:\n"
            "[ACT X — TITLE | TIMESTAMP | ~WORD COUNT]\n\n"
            "IMPORTANT FORMATTING RULES:\n"
            "- Mark each act clearly: [ACT X — TITLE | TIMESTAMP | WORD COUNT]\n"
            "- Write as continuous narration — no stage directions, no \"[pause]\" markers\n"
            "- Do NOT include image descriptions in the script\n"
            "- Every factual claim must be verifiable from the research brief\n"
            "- If the research brief includes sources, weave them into the narration naturally (never as footnotes); never invent a source\n"
        )

        # Append profile-specific text blocks
        rendered += "\n\n" + _build_act_structure_override(config)
        if profile.micro_payoff_architecture:
            rendered += "\n\n" + profile.micro_payoff_architecture
        else:
            rendered += "\n\n" + _MICRO_PAYOFF_ARCHITECTURE

        if profile.framework_selection_rules:
            rendered += "\n\n" + profile.framework_selection_rules
        else:
            rendered += "\n\n" + _FRAMEWORK_SELECTION_RULES

        if profile.framework_revelation_engine:
            rendered += "\n\n" + profile.framework_revelation_engine
        else:
            rendered += "\n\n" + _FRAMEWORK_REVELATION_ENGINE

        # Emotional arc (profile-specific, replaces _FRAMEWORK_PSYCH_SEPARATION)
        if profile.emotional_arc:
            arc_lines = ["=== EMOTIONAL ARC — THE VIEWER'S JOURNEY ===\n"]
            for act_num in sorted(profile.emotional_arc.keys()):
                arc_lines.append(f"- Act {act_num}: {profile.emotional_arc[act_num]}")
            rendered += "\n\n" + "\n".join(arc_lines)
        else:
            rendered += "\n\n" + _FRAMEWORK_PSYCH_SEPARATION

        # Cinematic voice rules already added at top of prompt (after preamble)

        if profile.act_specific_rules:
            rendered += "\n\n" + profile.act_specific_rules
        else:
            rendered += "\n\n" + _ACT_SPECIFIC_RULES

        if profile.strict_grounding_rule:
            rendered += "\n\n" + profile.strict_grounding_rule
        else:
            rendered += "\n\n" + _STRICT_GROUNDING_RULE

        # Append self-validation instruction
        rendered += "\n\n" + _SELF_VALIDATION_INSTRUCTION

        return rendered

    # --- Legacy path: no profile, use static template ---
    template = load_script_prompt()

    rendered = template.format(
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

    # IMPORTANT: Cinematic voice rules come FIRST after template
    # so Claude internalizes voice/tone BEFORE structural constraints.
    rendered += "\n\n" + _CINEMATIC_VOICE_RULES

    # Inject writer guidance if present (per-video override)
    writer_guidance_section = _build_writer_guidance_section(brief)
    if writer_guidance_section:
        rendered += "\n\n" + writer_guidance_section

    # Append updated act structure (dynamic from config or legacy),
    # micro-payoff architecture, framework selection rules, revelation
    # engine, and act-specific rules.
    rendered += "\n\n" + _build_act_structure_override(config)
    rendered += "\n\n" + _MICRO_PAYOFF_ARCHITECTURE
    rendered += "\n\n" + _FRAMEWORK_SELECTION_RULES
    rendered += "\n\n" + _FRAMEWORK_REVELATION_ENGINE
    rendered += "\n\n" + _FRAMEWORK_PSYCH_SEPARATION
    rendered += "\n\n" + _ACT_SPECIFIC_RULES
    rendered += "\n\n" + _STRICT_GROUNDING_RULE

    # Append self-validation instruction
    rendered += "\n\n" + _SELF_VALIDATION_INSTRUCTION

    return rendered


def validate_script(
    script: str,
    config: Optional["VideoConfig"] = None,
    profile: Optional["ScriptProfile"] = None,
) -> dict:
    """Validate script structure and word count.

    Args:
        script: Generated script text.
        config: Optional VideoConfig for dynamic thresholds. Falls back to
            legacy constants when None.
        profile: Optional ScriptProfile for editorial-voice-aware validation.
            When provided, uses profile's validation rules for word count
            thresholds and kill phrase checking.

    Returns:
        {
            "valid": bool,
            "word_count": int,
            "act_count": int,
            "issues": list[str],
            "acts": list[dict],  # parsed act info
        }
    """
    if config:
        min_words = config.script_min_words
        max_words = config.script_max_words
        expected_acts = config.act_count
    elif profile:
        min_words = profile.validation.min_words
        max_words = profile.validation.max_words
        expected_acts = profile.act_structure.get("act_count", EXPECTED_ACT_COUNT)
    else:
        min_words = SCRIPT_MIN_WORDS
        max_words = SCRIPT_MAX_WORDS
        expected_acts = EXPECTED_ACT_COUNT

    issues = []
    word_count = len(script.split())

    # Check word count
    if word_count < min_words:
        issues.append(
            f"Script too short: {word_count} words (minimum {min_words})"
        )
    elif word_count > max_words:
        issues.append(
            f"Script too long: {word_count} words (maximum {max_words})"
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

    if len(acts) < expected_acts:
        issues.append(
            f"Only {len(acts)} act markers found (expected {expected_acts})"
        )

    # Check act numbers are sequential
    act_numbers = [a["number"] for a in acts]
    expected_numbers = list(range(1, expected_acts + 1))
    if act_numbers != expected_numbers[: len(act_numbers)]:
        issues.append(f"Act numbers not sequential: {act_numbers}")

    # Profile-aware validation: kill phrase check
    if profile and profile.validation.kill_phrase_check:
        script_lower = script.lower()
        for phrase in profile.language.kill_phrases:
            if phrase.lower() in script_lower:
                issues.append(f"Kill phrase detected: '{phrase}'")

    return {
        "valid": len(issues) == 0,
        "word_count": word_count,
        "act_count": len(acts),
        "issues": issues,
        "acts": acts,
    }


def extract_framework_from_script(script: str) -> str:
    """Extract the chosen angle/lens selection from generated script text.

    The script writer is instructed to state the per-video angle as:
        ANGLE: [Name] — [reason]
    (legacy scripts may instead say ``PRIMARY FRAMEWORK: [Name] — [reason]``).

    Returns the angle/framework name, or empty string if not found.
    """
    match = re.search(
        r"(?:ANGLE|PRIMARY\s+FRAMEWORK):\s*(.+?)(?:\s*[—–-]\s*|$)",
        script,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip().rstrip("—–- ")
    return ""


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


def _find_foreign_speakers(script: str, allowed: list) -> list:
    """Speaker labels in the script that aren't in the allowed cast.

    Advisory only - surfaces 'the model invented a speaking character' in the
    validation report instead of silently shipping it. A label is a short
    capitalized name at line start followed by a colon ('**Ryan:**',
    'SEÑORA MARTÍNEZ:'). Narration prose (no label) is never flagged."""
    import re as _re
    from collections import Counter
    allowed_cf = {str(a).strip().casefold() for a in (allowed or [])}
    counts = Counter()
    for raw in script.splitlines():
        line = raw.strip()
        m = _re.match(r"^\*{0,2}([^\n:*]{1,40}?)\*{0,2}\s*:", line)
        if not m:
            continue
        name = m.group(1).strip()
        words = name.split()
        if not words or len(words) > 3:
            continue
        # A speaker label is a NAME: every word capitalized (Title or ALLCAPS)
        if not all(w[0].isupper() for w in words if w[0].isalpha()):
            continue
        if any(ch in name for ch in ".!?\""):
            continue
        if name.casefold() in allowed_cf:
            continue
        if name.upper() in ("ACT", "SCENE", "NOTE", "TITLE", "HOOK", "OPENING"):
            continue
        counts[name] += 1
    # Real speaking characters speak repeatedly; a single capitalized
    # sentence-opener with a colon ("Honestly: ...") is prose, not a speaker.
    return sorted(n for n, c in counts.items() if c >= 2)


async def generate_script(
    anthropic_client,
    brief: dict,
    model: str = Models.CLAUDE_SONNET,
    config: Optional["VideoConfig"] = None,
    profile: Optional["ScriptProfile"] = None,
    system_prompt_override: Optional[str] = None,
    format_contract: Optional[str] = None,
    allowed_speakers: Optional[list] = None,
) -> dict:
    """Generate a full narration script from a validated research brief.

    Args:
        anthropic_client: AnthropicClient instance
        brief: Validated research brief dict
        model: Model to use (defaults to Sonnet, can use Opus for higher quality)
        config: Optional VideoConfig for dynamic word counts and act structure.
        profile: Optional ScriptProfile for editorial voice control.

    Returns:
        {
            "script": str,
            "validation": dict,
        }
    """
    if config:
        min_words = config.script_min_words
        max_words = config.script_max_words
        target_words = config.total_script_words
    elif profile:
        min_words = profile.validation.min_words
        max_words = profile.validation.max_words
        target_words = (min_words + max_words) // 2
    else:
        min_words = SCRIPT_MIN_WORDS
        max_words = SCRIPT_MAX_WORDS
        target_words = SCRIPT_TARGET_WORDS

    prompt = build_script_prompt(brief, config=config, profile=profile)

    # The format contract goes LAST - after the topic brief and every craft
    # block - because the model weights the end of the prompt heaviest. This
    # is what stops a topic brief ("an instructor who only speaks Spanish")
    # from out-pulling the channel's locked cast and closing beats.
    if format_contract:
        prompt = prompt + "\n\n" + format_contract

    script = await anthropic_client.generate(
        prompt=prompt,
        model=model,
        max_tokens=8000,
        temperature=0.8,
        system_prompt=system_prompt_override or "",
    )

    # Parse and strip self-validation JSON from the response
    self_validation = _parse_self_validation(script)
    if self_validation:
        script = _strip_validation_json(script)
        logger.info(f"Self-validation parsed: {self_validation}")

    validation = validate_script(script, config=config, profile=profile)

    # Locked-cast speaker check (advisory, deterministic): any speaker label
    # outside the allowed cast is reported in the validation panel - the
    # creator sees "invented speaker: X" at the gate instead of silence.
    if allowed_speakers:
        foreign = _find_foreign_speakers(script, allowed_speakers)
        if foreign:
            validation.setdefault("issues", []).append(
                "Invented speaking character(s) outside the locked cast: " + ", ".join(foreign)
            )
            validation["foreign_speakers"] = foreign
            validation["valid"] = False
            logger.warning(f"Foreign speakers outside locked cast: {foreign}")

    # Add self-validation to the validation dict
    if self_validation:
        validation["self_validation"] = self_validation.get("self_validation", {})

    # Word-count validation is advisory — log but never regenerate.
    # The validator is a quality report, not a gatekeeper.
    if not validation["valid"]:
        if validation["word_count"] < min_words:
            logger.warning(
                f"Script under target: {validation['word_count']}/{min_words} words "
                f"— continuing (no retry)"
            )
        elif validation["word_count"] > max_words:
            logger.warning(
                f"Script over target: {validation['word_count']}/{max_words} words "
                f"— continuing (no retry)"
            )

    # Validate empowerment close on the final act
    from .scene_validator import validate_act6_empowerment

    acts = extract_acts(script)
    final_act_num = config.act_count if config else 6
    final_act_text = acts.get(final_act_num, "")
    empowerment_check = validate_act6_empowerment(final_act_text)
    if not empowerment_check["valid"]:
        validation["act6_empowerment_issues"] = empowerment_check["issues"]
        for issue in empowerment_check["issues"]:
            if "issues" not in validation:
                validation["issues"] = []
            validation["issues"].append(issue)
            validation["valid"] = False

    # === Editorial Voice v2: Post-Generation Validation ===
    from .script_validator import (
        validate_script_editorial,
        ScriptValidationConfig,
    )

    editorial_config = (
        ScriptValidationConfig.from_profile(profile)
        if profile is not None
        else ScriptValidationConfig()
    )
    if not acts:
        acts = extract_acts(script)

    editorial_result = validate_script_editorial(
        script=script, brief=brief, acts=acts, config=editorial_config,
    )

    # Editorial validation is advisory — report results, never retry or block.
    # Generate once → validate → report → move on.
    editorial_dict = editorial_result.to_dict()
    editorial_dict["retries_used"] = 0
    validation["editorial"] = editorial_dict

    if not editorial_result.passed:
        failed_names = [c.name for c in editorial_result.failed_checks]
        logger.warning(
            f"Editorial validation failed: {', '.join(failed_names)} "
            f"— continuing (advisory, no retry)"
        )

    return {
        "script": script,
        "validation": validation,
    }


async def verify_script_claims(
    anthropic_client,
    script: str,
    brief: dict,
) -> str:
    """Verify factual claims in the script against the research payload.

    Uses a fast model (Haiku) to compare each scene's factual claims against
    the research payload and flag any claim that cannot be traced back.

    This is a NON-BLOCKING check — the script still advances to the next
    pipeline stage regardless of the result. The output is stored in Airtable
    for manual review.

    Args:
        anthropic_client: AnthropicClient instance.
        script: The full generated script text.
        brief: The research brief dict containing the source material.

    Returns:
        A string summarizing unverified claims, or empty string if all clean.
    """
    import logging

    logger = logging.getLogger(__name__)

    # Build a condensed version of the research payload for comparison
    payload_sections = []
    for field in [
        "fact_sheet", "source_bibliography", "historical_parallels",
        "character_dossier", "narrative_arc", "counter_arguments",
        "thesis", "executive_hook", "framework_analysis", "headline",
    ]:
        value = brief.get(field, "")
        if value:
            payload_sections.append(f"=== {field} ===\n{value}")

    research_text = "\n\n".join(payload_sections)

    system_prompt = (
        "You are a fact-checking assistant. Your job is to compare a video "
        "script against the research payload that was used to write it, and "
        "flag TWO types of problems:\n\n"
        "1. UNVERIFIED CLAIMS — factual claims that cannot be traced to the research\n"
        "2. MISATTRIBUTED SOURCES — sources cited in the script that don't match "
        "the [Source] tags in the research payload\n\n"
        "For UNVERIFIED CLAIMS, check:\n"
        "- Named events, places, or incidents not in the research\n"
        "- Specific technical or procedural details not sourced\n"
        "- Statistics, numbers, dates, or percentages not in the research\n"
        "- Quotes attributed to people that don't appear in the research\n"
        "- Historical parallels not from the historical_parallels field\n\n"
        "For MISATTRIBUTED SOURCES, check:\n"
        "- 'According to [Source]' where that source doesn't appear in source_bibliography\n"
        "- A fact that has [Source A] in the research but is cited as Source B in the script\n"
        "- A fact marked [unverified] in research but cited to a specific source in script\n"
        "- Singular sources pluralized ('one CEO' becomes 'CEOs')\n\n"
        "IGNORE:\n"
        "- Dramatic phrasing, rhetorical questions, metaphors\n"
        "- Connections drawn using the channel's chosen angle (these are allowed)\n"
        "- Well-known general references that aren't specific factual claims\n"
        "- General knowledge that doesn't constitute a specific factual claim\n\n"
        "Output format:\n"
        "=== UNVERIFIED CLAIMS ===\n"
        "- [Act N] \"<the claim>\" — not found in research payload\n\n"
        "=== MISATTRIBUTED SOURCES ===\n"
        "- [Act N] Cited as [Source B] but research shows [Source A]\n\n"
        "If all claims are grounded AND all sources match, respond with exactly: "
        "ALL CLAIMS VERIFIED"
    )

    prompt = (
        f"<research_payload>\n{research_text}\n</research_payload>\n\n"
        f"<script>\n{script}\n</script>\n\n"
        "Compare the script against the research payload. List any specific "
        "factual claims in the script that cannot be traced to the research "
        "payload."
    )

    try:
        result = await anthropic_client.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            model=Models.CLAUDE_HAIKU,
            max_tokens=2000,
            temperature=0.0,
        )
    except Exception as e:
        logger.warning(f"Claim verification failed (non-blocking): {e}")
        return ""

    if not result or "ALL CLAIMS VERIFIED" in result.upper():
        return ""

    # Truncate if extremely long (Airtable Long Text field)
    if len(result) > 5000:
        result = result[:4950] + "\n\n[truncated]"

    return result
