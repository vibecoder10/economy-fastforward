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


# ---------------------------------------------------------------------------
# Prompt overrides — appended after the base template to update act structure,
# inject micro-payoff architecture, framework revelation engine, and
# per-act rules.  Keeps script.txt untouched.
# ---------------------------------------------------------------------------

_ACT_STRUCTURE_OVERRIDE_LEGACY = """\
=== UPDATED SCRIPT PARAMETERS — THESE OVERRIDE THE ACT STRUCTURE ABOVE ===

This is a 15-20 minute video. Follow these targets:

Target total: ~2,800 words (~17 minutes at 160 words/min)
Minimum: 2,200 words (~14 min). Maximum: 3,200 words (~20 min).

Act word targets:
- Act 1 (The Lie): ~350 words (0:00-2:00) — State the official narrative and break it with one contradicting fact
- Act 2 (The Setup): ~500 words (2:00-6:00) — Key players, incentives, incentive chain with specific numbers
- Act 3 (The Hidden Mechanism): ~550 words (6:00-11:00) — Money trail / power flow with evidence, framework invisible
- Act 4 (The Proof): ~500 words (11:00-15:00) — Historical parallel + NOW name the framework
- Act 5 (The Personal Stakes): ~500 words (15:00-18:00) — Dollar impact on the viewer, steel-man counter-arguments
- Act 6 (The Play): ~400 words (18:00-20:00) — Specific actionable strategy with historical data
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
=== MICRO-REVELATION ARCHITECTURE — NON-NEGOTIABLE ===

Every 90 seconds of narration must deliver a specific revelation — a fact, \
number, or connection the viewer didn't know. The viewer should never go \
more than 90 seconds without learning something specific and new.

Structure within each scene (60-90 seconds):

CLAIM (first 1-2 sentences): State a specific, verifiable claim with a \
number. "54% of all PE funding for the top 30 US AI companies comes from \
three Gulf sovereign wealth funds." This is not a question — it's insider \
intelligence.

EVIDENCE (middle): Build the case with more specific data. Each fact should \
connect to the incentive chain — WHO benefits, HOW MUCH, and WHY this \
matters. Every paragraph must contain at least one specific number.

REVELATION (last 1-2 sentences): The "oh shit" moment — a connection the \
viewer didn't see. This is NOT a cliffhanger — it's a REWARD.

BRIDGE (final sentence): The revelation naturally raises a NEW question \
that pulls them into the next scene. This is the explicit forward sell.

BAD example (vague, no numbers):
"And what happened next would change everything. But first, let's \
understand the background..."

GOOD example (specific, number-dense, investigative):
"Iran didn't strike Ras Tanura to destroy it. They struck it to prove \
that every dollar of Saudi oil wealth now exists at their mercy — and the \
cost of that proof was twenty thousand dollars. One drone against a \
facility processing 7 million barrels a day. That's the asymmetry that \
breaks empires. But the real question isn't whether Iran can do it again. \
It's what happens when Lloyd's of London decides the Strait isn't worth \
the $14 billion premium."
"""

_FRAMEWORK_REVELATION_ENGINE = """\
=== FRAMEWORK INTEGRATION — INVISIBLE ENGINE, NOT THE HEADLINE ===

The selected framework is the analytical engine that structures the \
investigation. But it is INVISIBLE SCAFFOLDING until Act 4. The viewer \
sees the pattern playing out in real events BEFORE you name it.

FRAMEWORK VISIBILITY RULES:
- Acts 1-3: The framework operates SILENTLY. Show the pattern through \
events, money trails, and incentive chains. NEVER name the framework, \
the author, or use academic terminology. The viewer should feel "something \
deeper is going on" without being told what it is.
- Act 4: NOW name the framework. "What you're watching is what [Author] \
identified as [Concept]." This lands as CONFIRMATION of what the viewer \
already intuited, not as new information being introduced.
- Acts 5-6: Reference the framework by name at most once more. Use it \
as a predictive tool: "If this follows the [framework] pattern, then..."

BAD (framework as lecture — kills the investigative tone):
"Machiavelli wrote in The Prince that consolidating power requires \
eliminating rival factions. What we're seeing with this company is \
a textbook application of Chapter 7..."

GOOD (framework invisible, pattern visible):
"Three weeks after the acquisition, every executive who opposed the \
deal was gone. Not fired — reassigned to roles with no budget and no \
staff. The board members who voted against? Their committee seats were \
quietly redistributed. Within 90 days, every voice of dissent had been \
neutralized without a single public confrontation."
(The viewer FEELS the Machiavellian pattern without being told about it.)

GOOD (framework revealed in Act 4):
"What you've been watching play out — the quiet purge, the strategic \
appointments, the controlled elimination of opposition — is what \
Machiavelli identified 500 years ago as the consolidation phase. And \
the historical record shows what comes next."

CRITICAL: If the framework/tactical/military mechanics section exceeds \
15% of total script time, the script has drifted into documentary mode. \
The incentive chain (WHO benefits, HOW MUCH, WHY) must always be the \
dominant content. The framework EXPLAINS the incentive chain — it does \
not replace it.

Maximum 2 direct references to the framework by name in the entire script. \
The rest is showing, not telling.
"""

_FRAMEWORK_SELECTION_RULES = """\
=== FRAMEWORK SELECTION — DYNAMIC PER-VIDEO ===

Before writing the outline, select 1-2 primary frameworks that BEST explain \
the incentive chain in this story. Do not default to Machiavelli. Choose the \
framework that creates the most powerful "who benefits" revelation.

Available frameworks (select 1-2):
1. Machiavelli / 48 Laws of Power — political maneuvering, deception, betrayal
2. Thucydides Trap — rising power vs established power, inevitable conflict
3. Taleb (Antifragile/Black Swan) — asymmetric risk, fragility, hidden tail risks
4. Game Theory — deterrence, prisoner's dilemma, Nash equilibrium, commitment
5. Sun Tzu (Art of War) — indirect warfare, winning without fighting, deception
6. Brzezinski / Grand Chessboard / Mackinder — geographic control, pivot states
7. Kindleberger Trap — hegemon withdrawal, public goods vacuum, systemic collapse
8. Schelling (Focal Points/Commitment) — brinkmanship, credible threats, red lines
9. Mancur Olson (Collective Action) — organized minorities vs disorganized majorities
10. Joseph Nye (Soft Power/Sharp Power) — influence without coercion, cultural dominance

Selection criteria:
- Which framework best explains the INCENTIVE CHAIN — who benefits and why?
- Which framework connects this specific event to a MONEY TRAIL the viewer \
can follow?
- Which framework gives the viewer a TOOL they can use to predict financial \
impact and position themselves?

State your framework selection at the top of the outline:
PRIMARY FRAMEWORK: [Name] — [One sentence on why this framework cracks open \
this story's incentive chain]
SECONDARY FRAMEWORK: [Name] — [One sentence on what additional dimension \
this adds]

REMEMBER: The framework is INVISIBLE in Acts 1-3. It structures your \
analysis silently. It is only NAMED in Act 4.
"""

_FRAMEWORK_PSYCH_SEPARATION = """\
=== EMOTIONAL ARC — THE INVESTIGATIVE JOURNEY ===

Each act has a specific emotional function in the investigative journey. \
The viewer goes from deceived → suspicious → enlightened → alarmed → empowered.

Emotional arc per act:
- Act 1 (The Lie): DECEPTION → SUSPICION. The viewer realizes they've been \
lied to. They feel betrayed by the official narrative. Curiosity gap opened.
- Act 2 (The Setup): CURIOSITY → RECOGNITION. The viewer starts seeing the \
incentive chain. "Oh, so THAT'S why..." Each fact adds to the picture.
- Act 3 (The Hidden Mechanism): RECOGNITION → REVELATION. The money trail \
clicks into place. The viewer feels like they're seeing behind the curtain.
- Act 4 (The Proof): REVELATION → CONVICTION. The historical parallel proves \
this is a PATTERN, not coincidence. The framework name confirms what they \
already intuited. "I knew something was off."
- Act 5 (The Personal Stakes): CONVICTION → ALARM. The abstract becomes \
personal. Dollar amounts hit the viewer's life directly. Genuine unsettlement.
- Act 6 (The Play): ALARM → EMPOWERMENT. The viewer receives specific tools \
and actions. They leave feeling SMARTER and MORE CAPABLE. Not scared — armed.

CRITICAL: The arc must end on EMPOWERMENT. The viewer must leave every video \
feeling like they gained an advantage, not like they lost hope.
"""

_CINEMATIC_VOICE_RULES = """\
=== CINEMATIC VOICE — IMMERSIVE POV WRITING ===

0. DATA LIVES INSIDE CHARACTERS — THE #1 RULE:

Once you enter a character's perspective at the start of an act, you \
DO NOT LEAVE IT until the act ends. Every statistic, every percentage, \
every dollar amount must be something that character sees, knows, fears, \
or discovers.

You are NOT a news anchor reading statistics. You are a camera operator \
standing behind a person who is living this moment.

TEST: For every sentence, ask "whose eyes am I seeing this through?" \
If the answer is "nobody — this is just information," REWRITE IT through \
the nearest character.

BAD (narrator breaks away to brief the audience):
"China receives 37.7% of all crude oil flowing through Hormuz, according \
to Visual Capitalist's Q1 2025 data. Saudi Arabia exports 37.2% through \
the strait. Iraq: 22.8%."

GOOD (the destroyer captain knows this because it's his problem):
"The captain knows what's anchored behind him. Tankers bound for China, \
which takes 37% of everything that flows through this strait. Tankers \
for Japan, South Korea, India. His mission is to protect them all. His \
ship has 90 missile cells. There are 3,000 speedboats."

BAD (narrator lectures about cost asymmetry):
"This is the asymmetry that breaks empires. Iran fires a $50,000 drone. \
The U.S. spends $4 million to stop it. That's a 1-to-80 cost ratio."

GOOD (the captain is living the cost asymmetry):
"Every time his ship fires a $4 million interceptor at a drone that \
cost $50,000 to build, the captain is watching his ammunition budget \
evaporate. He has 90 cells. Iran has 2,500 missiles and thousands of \
drones. He can do the math."

BAD (narrator delivers a history lesson):
"On April 18, 1988, Operation Praying Mantis saw U.S. forces destroy \
one Iranian frigate, one gunboat, three speedboats, and two platforms \
in the largest U.S. naval engagement since World War II."

GOOD (Tangsiri remembers it because he lived through it):
"Tangsiri was a junior officer in 1988 when American ships destroyed \
an Iranian frigate, a gunboat, three speedboats, and two platforms in \
a single afternoon. Forty-five sailors died. He spent the next 35 years \
making sure Iran would never fight that way again."

THE RULE: If you find yourself writing "according to" or listing \
percentages without a character reacting to them, you've left the \
scene. Get back inside.

CITATIONS: Source attributions still appear — but weave them into the \
character's world. "The Pentagon's own assessment landed on his desk: \
1 to 6 months" not "A Defense Intelligence Agency assessment estimates \
1 to 6 months, according to CNN."

MICRO-INSIGHTS: These are the character's earned wisdom, said in their \
voice at the end of their scene. Not narrator commentary. The captain \
thinks it. Tangsiri knows it. The family feels it. Van Riper proved it.

ACT 4 IS THE HARDEST ACT TO KEEP IN CHARACTER. This is where the \
framework drops and the temptation is to break into professor mode. \
DO NOT.

The Act 4 character is the prophet — the person who predicted or \
proved this pattern before. The framework insight belongs to THEM, \
not to a narrator explaining theory.

BAD: "What you're watching is what military theorists call asymmetric \
cost imposition — the strategic principle that..."

GOOD: "Van Riper quit the war game in protest. He'd proved something \
the Pentagon didn't want to hear: you don't have to win a fight. You \
just have to make winning too expensive for the other guy. Twenty-four \
years later, he's watching Iran prove him right."

BAD: "Halford Mackinder wrote in 1904 that geography determines \
destiny. Zbigniew Brzezinski updated it for the modern era."

GOOD: "Van Riper didn't need Mackinder to tell him what the map \
already showed. Twenty-one miles of shallow water with 100 miles of \
hostile coastline. No carrier group in history was built for this."

THE RULE FOR ACT 4: The framework name can appear ONCE. One sentence. \
Then immediately return to the character's experience. If you find \
yourself writing two consecutive sentences of theory without a \
character acting, seeing, or deciding — you've left the scene.

THE APEX must be said in plain language a teenager could repeat:
GOOD: "You don't have to win. You just have to make winning too \
expensive for the other guy."
BAD: "This demonstrates asymmetric cost imposition where the \
defender's expenditure exceeds the attacker's investment ratio."

1. SCENE-DRIVEN ACT OPENINGS: Open every act with a specific scene — a place, \
a person, an action — in the first 2-3 sentences. Ground the viewer in a \
visual moment BEFORE transitioning to analysis.

GOOD: "In a warehouse outside Isfahan, Iranian engineers loaded the first \
batch of Shahed drones onto transport planes."
BAD: "Iran needed regional dominance without direct confrontation."

CRITICAL: The scene you open with IS the act. You don't open with a \
scene and then leave it to deliver analysis. The analysis happens \
INSIDE the scene. If Act 2 opens on the destroyer bridge, Act 2 \
STAYS on the destroyer bridge. The trade flow percentages, the \
insurance data, the cost ratios — the captain knows all of this \
because it's his operational reality.

2. ACTIVE FRAMING: Replace passive analytical statements with active cinematic \
ones. Same facts, cinematic delivery.

GOOD: "Iran's generals studied the map and saw an opportunity."
BAD: "Iran needed regional dominance."

GOOD: "Three engineers in a Kyiv garage plugged in a 3D printer."
BAD: "What emerged wasn't a government program."

3. SCENE TRANSITIONS: Cut between locations like a film editor. Use geographic \
and temporal cuts to move between acts — NOT abstract narrative bridges.

GOOD: "Six hundred miles south, at a shipping container in Kuwait, a US \
sergeant checked the perimeter for the last time."
BAD: "But here's what none of this explains."

4. POV ANCHOR: Each act must have ONE moment where the viewer is placed \
inside the scene — standing in a boardroom, watching a screen, hearing the \
announcement. This is the cinematic "you are here" beat.

GOOD: "You're sitting in the trading floor when the ticker flashes red."
GOOD: "Picture standing on that shipping container watching the tankers queue."

5. SENTENCE RHYTHM: Short fragments during action and revelation. Longer \
flowing sentences during explanation and context-building. The rhythm itself \
creates tension and release.

ACTION: "The phone rang. The CFO answered. Three words. Then silence."
EXPLANATION: "What nobody outside the Pentagon understood was that this \
particular supply chain had been quietly subsidized for two decades."

6. THE "YOU" PIVOT: The direct address to the viewer ("you", "your wallet", \
"your 401k") happens ONCE in Act 5 — not scattered throughout. Save it for \
maximum impact when personal stakes are introduced.

7. HERO VISUAL MOMENT: Each act gets ONE vivid visual beat that could be a \
movie still — a face, a place, an object that crystallizes the act's theme. \
Describe it in sensory detail.

8. FORWARD PULL: End every act (except the last) with explicit forward momentum. \
The final sentence should create genuine curiosity about what comes next.

Every act opening should feel like a camera cutting to a new location. The \
viewer should SEE the scene before hearing the analysis.

9. THE POWER DOCTRINE APEX (Act 4):

Every video has one moment where the story stops being about the headline \
and becomes a truth the viewer can use forever. This is the reward for staying.

THREE RULES:

A) BUILD A GAP IN ACTS 1-3: Something doesn't add up. The viewer feels a \
contradiction they can't resolve:
- "If Iran is losing, why are the tankers still frozen?"
- "If America has the strongest military, why can't it open a 21-mile strait?"

B) DROP THE INSIGHT THROUGH A CHARACTER: Not as a lecture. As something a \
person discovered, proved, or lived. The insight belongs to them.

GOOD: "Van Riper proved it in 2002. You don't have to win. You just have to \
make winning too expensive for the other guy."
BAD: "This illustrates Nash equilibrium in asymmetric conflict theory."

C) SIMPLE ENOUGH TO REPEAT: If a teenager couldn't say it back to a friend \
in one sentence, rewrite it.

PLACEMENT: Act 4. Never earlier. Never Act 5 — that's the personal stakes return.

10. MICRO-INSIGHT BREADCRUMBS (Every Act):

Every act ends with one simple truth the viewer takes with them. These build \
toward the apex but each one works alone. A viewer who leaves after Act 2 \
still learned two things they can use.

PATTERN:
- Act 1: A truth about money, prices, or how hidden systems hit your life
- Act 2: A truth about perception, appearances, or what power looks like
- Act 3: A truth about strategy, systems, or how the game was changed
- Act 4: THE APEX — the big transferable insight
- Act 5: A truth about signals — how to read what's really happening
- Act 6: A truth about patterns — how to spot this playing out again

RULES:
- One sentence. Two at most.
- Plain language only. No theory names. No economist citations.
- Delivered through the character's experience, not narrator commentary.
- Must pass the "text it to a friend" test.

GOOD: "You don't pay more because something bad happened. You pay more \
because something bad might happen."
GOOD: "If everyone believes you can hurt them, you don't actually have to."
GOOD: "Don't listen to what people say. Watch where the money goes."

BAD: "This demonstrates deterrence through perceived capability rather than \
actual force deployment."

The micro-insights form a chain. Each makes the next feel inevitable. By the \
time the apex drops, the viewer has already been thinking in the right direction.

11. EMOTIONAL ARC AND ACT STRUCTURE:

The viewer is the common person. They are the through-line. The story starts \
with their life, leaves to explore the machinery behind their pain, then \
returns with understanding.

THE ARC:
- Act 1 — "THAT'S ME": Open with the ordinary person affected. Gas pump, \
grocery bill, rent increase. They don't understand why. The viewer identifies \
immediately.
- Act 2 — "THEY'RE LYING": The official story falls apart. The person in \
charge can't solve it. The viewer feels the gap between what they're told and \
what's happening.
- Act 3 — "SOMEONE BUILT THIS": Meet the architect. The adversary or system \
designer who planned this deliberately over years or decades. The viewer feels \
dread and grudging respect.
- Act 4 — "NOW I UNDERSTAND": The apex. A historical proof or character who \
demonstrated this truth before. The viewer gets the framework that explains \
everything they've seen.
- Act 5 — "IT'S HITTING MY LIFE": Return to the ordinary person. Now every \
link is visible. The tankers, the insurance, the supply chain — all traced \
back to the mechanism revealed in Acts 2-4. The abstract becomes personal.
- Act 6 — "I KNOW WHAT TO WATCH": Return to Act 2's character or scene. Same \
situation, but the viewer sees it completely differently. Close with what \
signals to monitor and how to spot this pattern next time.

THE CHARACTER MAP:
- Act 1: The ordinary person (the viewer's stand-in)
- Act 2: The front-line operator failing to solve the crisis
- Act 3: The architect who built the system causing the crisis
- Act 4: The prophet who predicted or proved this before
- Act 5: Return to Act 1's ordinary person — now with understanding
- Act 6: Return to Act 2's operator — same scene, new meaning

This structure means the viewer's own life bookends the story. They enter \
through their experience, travel through the hidden machinery, and return to \
their own life with the ability to see what was invisible before. That \
transformation is why they subscribe.

12. ACT 6 — THE RETURN, NOT THE BRIEFING:

Act 6 returns to the Act 1 and Act 2 characters. The viewer sees the \
same scene with new understanding. This is emotional payoff, not a \
financial newsletter.

Actionable signals (insurance markets, pipeline capacity, specific \
indicators) must be delivered THROUGH a character's perspective, not \
as a numbered list.

BAD: "Watch for three specific indicators. One: insurance premium \
movements. Two: bypass pipeline utilization. Three: Chinese vessel \
transit patterns."

GOOD: "The captain will know it's over when the tankers start moving. \
Not when the Pentagon says it's safe — when Lloyd's of London says \
it's insurable. That's the signal. Insurance desks in London will \
call the end of this crisis before any general does."

BAD: "The sectors that move first: energy obviously, but also \
shipping insurance, defense contractors..."

GOOD: "That family in Ohio will fill up again next week. If the \
price drops, someone solved the insurance problem. If it doesn't, \
the 21-mile kill zone is still open for business. You'll know which \
one happened before the news tells you — just watch the price."

The final act is a STORY ENDING, not a research report. The viewer \
should feel closure and empowerment, not like they just read a \
Bloomberg terminal.
"""

_STRICT_GROUNDING_RULE = """\
=== STRICT FACTUAL GROUNDING RULE — NON-NEGOTIABLE ===

Every factual claim, entity name, company name, person name, event, date, \
and dollar amount in the script MUST come directly from the research payload \
provided. You may NOT introduce:
- Companies, people, or events not mentioned in the research
- Dollar amounts or statistics not in the fact sheet
- Historical events not in the historical parallels section
- Dates or timelines not supported by the source material

If you need a transition, analogy, or rhetorical device, use only the \
entities and events from the research payload. Do NOT substitute \
similar-sounding companies (e.g. DeepSeek for Anthropic) or similar topics \
(e.g. tariffs for Pentagon contracts).

Before finalizing each act, verify: is every proper noun, date, statistic, \
and event traceable to the research payload? If not, remove it or replace \
it with something from the research.

The ONLY exception is well-known historical figures or events used in \
framework references (e.g. Machiavelli, Sun Tzu, Athens vs Sparta) that \
are part of the analytical framework, NOT part of the factual narrative.

=== CRITICAL — FACTUAL GROUNDING (EXTENDED) ===

1. Every specific claim (names, numbers, dates, events, tactics, weapons, \
quotes) MUST come from the research payload provided. If a fact is not in \
the payload, DO NOT USE IT.

2. You may describe HOW something happened cinematically, but you MUST NOT \
invent WHAT happened. Example: You can describe a missile strike \
dramatically. You CANNOT invent a cyber attack that is not in the sources.

3. Never fabricate technical details (weapon systems, military tactics, \
operational specifics) to fill narrative gaps. If the payload does not \
explain HOW something happened, say "analysts believe" or "evidence \
suggests" — do not present speculation as confirmed fact.

4. Historical parallels must come from the research payload's \
historical_parallels field. Do not invent additional parallels.

5. If a scene needs content the payload does not provide, use the \
framework analysis to EXPLAIN the event rather than inventing new events. \
The analytical framework is your gap-filler, not fabricated details.

6. After writing each scene, mentally verify: "Could I cite a specific \
source from the payload for every factual claim in this scene?" If not, \
rewrite.

WHAT YOU CAN CREATE:
- Dramatic pacing, sentence structure, rhetorical questions
- Emotional framing of sourced facts
- Analytical connections between sourced facts using the framework
- Metaphors and analogies that illustrate sourced concepts

WHAT YOU CANNOT CREATE:
- Events that did not happen
- Technical details not in the payload (cyber attacks, specific weapon \
deployments, operational sequences)
- Quotes from people unless quoted in the payload
- Statistics, percentages, or numbers not in the payload
- Specific military tactics or operations not documented in sources
"""

_ACT_SPECIFIC_RULES = """\
=== ACT-SPECIFIC RULES (V2 — INVESTIGATIVE VOICE) ===

Act 1 (The Lie):
Open with the headline event (one sentence, present tense, specific date). \
State what "everyone" is being told. Drop ONE fact that contradicts the \
narrative (with a specific number). If multiple official rationales exist, \
walk through each and let them contradict each other — this is more \
devastating than breaking one narrative. End with: "When you follow the \
[money/data/contracts], you find something completely different." \
Minimum 2 specific numbers. Explicit cliffhanger teasing Act 3.

Act 2 (The Setup):
Introduce key players by their POSITIONS and INCENTIVES, not biographies. \
Build the incentive chain: Player A needs X → requires Y → depends on Z. \
Every paragraph must contain at least one specific number or date. Name \
sources: "according to the Congressional Budget Office" not "experts say." \
NO framework language yet — pure facts and observable patterns. End with: \
"But here's what none of this explains..." Minimum 5 specific numbers. \
Explicit cliffhanger teasing the hidden mechanism.

Act 3 (The Hidden Mechanism):
Reveal the real dynamic through EVIDENCE, not theory. This is the money \
trail / power flow / strategic logic with specific data. Connect dots the \
mainstream coverage missed. Introduce the first historical parallel as \
PROOF the pattern is real. The framework principles operate here but are \
NOT named — show don't tell. Each sub-section must have a mini-revelation. \
Minimum 4 specific numbers. Cliffhanger: "And there's one more layer \
that affects you directly."

Act 4 (The Proof):
Historical parallel in vivid detail — specific dates, figures, events, \
outcomes. Point-by-point mapping: "In 1973, [X]. In 2026, [X]." \
NOW name the framework: "What you're watching is what [Author] identified \
as [Concept]." Use the framework to PREDICT what comes next based on \
historical precedent. The framework arrives as CONFIRMATION of what the \
viewer already sees. Minimum 3 specific numbers. Cliffhanger about \
personal financial impact.

Act 5 (The Personal Stakes):
"Here's what this means for your wallet." Use "you" and "your" heavily. \
Specific scenarios with dollar amounts: "If [mechanism] continues, gas \
hits $X within Y days and your 401k drops Z%." Steel-man the strongest \
counterargument — it must be genuinely strong. Then dismantle it with \
evidence, not opinion. The viewer should feel genuinely unsettled. \
Minimum 3 specific numbers. Cliffhanger: "So what do you actually DO \
with this information? That's exactly what the final section reveals."

Act 6 (The Play):
"So what do you actually DO with this information?" This is NON-NEGOTIABLE \
— the viewer MUST receive a specific, actionable strategy. The close must:

1. Give the SPECIFIC ACTION: investment thesis, risk to hedge, sector to \
watch, signal to monitor. Not "diversify your portfolio" but "watch the \
[specific index/signal]." Include historical performance data: "Smart money \
moved [X days] after [similar events], not during."

2. NAME the frameworks and patterns taught in this video by name. The \
viewer must hear them repeated so they stick.

3. Give 2-3 DETECTION INSTRUCTIONS: "When you see X, ask Y. When A \
happens, look for B within 48 hours." Concrete, specific.

4. End on AGENCY: the final line connects back to the opening lie and \
lingers. The viewer leaves feeling SMARTER and MORE CAPABLE. NOT scared, \
NOT helpless, NOT cynical.

BAD close: "The window is closing and nobody will notice." (passive, hopeless)
GOOD close: "The repricing window opens 11-14 days after the shock. That's \
when smart money has moved in every conflict since Pearl Harbor. You now know \
what [framework] looks like in real time. When [specific signal] appears, \
you'll know the pattern has entered its final phase. The question isn't \
whether the system works this way. You just watched it happen. The question \
is whether you position yourself before or after everyone else figures it out."

If Act 6 does NOT contain a specific action AND at least 2 detection \
instructions, the script has FAILED.
"""


def load_script_prompt() -> str:
    """Load the script generation prompt template."""
    return PROMPT_TEMPLATE_PATH.read_text()


def _build_framework_lens_section(framework_angle: str) -> str:
    """Build the framework-specific instructions for the script prompt.

    Each framework gets detailed instructions on HOW to apply it throughout
    every act of the script. This is the analytical backbone.

    The 10-framework toolkit gives the channel its identity: 'there is ALWAYS
    a hidden playbook operating behind world events and we are the channel
    that shows you which one.'
    """
    framework_instructions = {
        "Machiavelli": (
            "=== PRIMARY ANALYTICAL LENS: MACHIAVELLI / 48 LAWS OF POWER ===\n\n"
            "Use for: Political maneuvering, deception, betrayal, alliance manipulation, "
            "strategic theater.\n\n"
            "Frame the entire narrative through Machiavelli and Robert Greene's Laws of "
            "Power. The corporate and political actors ARE princes managing their "
            "principalities. Reference specific concepts throughout:\n\n"
            "- Conceal intentions, use selective honesty, crush enemies totally\n"
            "- Court attention at all costs, appear as a friend while working as a spy\n"
            "- The Fox and the Lion — cunning to recognize traps, fierce to terrify wolves\n"
            "- Fortune vs Virtù — strategic skill vs circumstances\n"
            "- Whether it's better to be feared or loved\n"
            "- New principalities vs hereditary — market entrants vs incumbents\n\n"
            "Reference specific Laws by number or quote Machiavelli/Greene directly at "
            "least 3-4 times. Every major actor should be analyzed AS a Machiavellian "
            "prince executing a deliberate strategy."
        ),
        "48 Laws": (
            "=== PRIMARY ANALYTICAL LENS: THE 48 LAWS OF POWER (Robert Greene) ===\n\n"
            "Use for: Political maneuvering, deception, betrayal, alliance manipulation, "
            "strategic theater.\n\n"
            "You MUST explicitly reference specific Laws of Power throughout the entire\n"
            "script. Each act should tie to a specific law. The laws are the analytical\n"
            "backbone — they explain WHY the actors are behaving as they are.\n\n"
            "Key concepts: Conceal intentions, use selective honesty, crush enemies totally, "
            "court attention, appear as a friend while working as a spy.\n\n"
            "Reference at least 4-5 DIFFERENT laws across the 6 acts. Name the law number\n"
            "and title every time. The viewer should feel like they're getting a masterclass\n"
            "in power dynamics while watching current events unfold."
        ),
        "Thucydides Trap": (
            "=== PRIMARY ANALYTICAL LENS: THE THUCYDIDES TRAP ===\n\n"
            "Use for: Rising power vs established power dynamics, inevitable conflict "
            "between status quo and challenger.\n\n"
            "Frame the entire narrative through the structural tension between a rising "
            "power and the established power that fears it. Key concepts:\n\n"
            "- The established power fears the rising one — preventive action becomes rational\n"
            "- Security dilemma: defensive moves by one side look offensive to the other\n"
            "- Structural inevitability: the trap is NOT about individual leaders but about\n"
            "  the position of the powers relative to each other\n"
            "- Historical cases: Athens/Sparta, Britain/Germany, Portugal/Spain, US/USSR\n"
            "- The question is not WHETHER conflict comes but WHAT FORM it takes\n\n"
            "Reference Thucydides and Graham Allison by name. Show how the same structural\n"
            "dynamic has produced the same results for 2,500 years. The viewer should feel\n"
            "the weight of historical inevitability."
        ),
        "Antifragile": (
            "=== PRIMARY ANALYTICAL LENS: TALEB — ANTIFRAGILE / BLACK SWAN / SKIN IN THE GAME ===\n\n"
            "Use for: Asymmetric risk, fragility of complex systems, things that gain from "
            "disorder, hidden tail risks.\n\n"
            "Frame the entire narrative through Nassim Taleb's framework of fragility:\n\n"
            "- Fragile vs Robust vs Antifragile: categorize every actor and system\n"
            "- Skin in the game: who bears the consequences of their decisions?\n"
            "- Turkey problem: the thing that has 'never happened' is the biggest risk\n"
            "- Barbell strategy: how smart actors position for extreme outcomes\n"
            "- Black Swans: the events nobody models that change everything\n"
            "- Lindy Effect: the old has survived; the new is fragile\n\n"
            "Reference Taleb by name. Show how complexity creates hidden fragility that\n"
            "looks like strength until the moment it shatters. The viewer should see\n"
            "fragility in systems they assumed were strong."
        ),
        "Game Theory": (
            "=== PRIMARY ANALYTICAL LENS: GAME THEORY ===\n\n"
            "Use for: Deterrence, credible threats, prisoner's dilemma, Nash equilibrium, "
            "commitment devices.\n\n"
            "Frame the entire narrative through game-theoretic structures:\n\n"
            "- Nash Equilibrium: actors locked into suboptimal outcomes neither can escape\n"
            "- Prisoner's Dilemma: mutual defection hurts everyone but is individually rational\n"
            "- Mutually assured destruction: when both sides can destroy each other\n"
            "- First-mover advantage: why timing determines winners\n"
            "- Signaling: costly actions that communicate intent\n"
            "- Credible vs non-credible threats: why some threats work and others don't\n"
            "- Tit-for-Tat escalation: retaliatory spirals\n\n"
            "The viewer should understand that actors aren't making random choices — they're\n"
            "trapped in game-theoretic structures that make outcomes nearly inevitable.\n"
            "Name the specific game/equilibrium being played."
        ),
        "Sun Tzu": (
            "=== PRIMARY ANALYTICAL LENS: SUN TZU — THE ART OF WAR ===\n\n"
            "Use for: Indirect warfare, winning without fighting, deception as strategy, "
            "exploiting weakness.\n\n"
            "Frame the entire narrative as strategic warfare:\n\n"
            '- "All warfare is based on deception" — the recurring theme\n'
            '- "Supreme excellence consists in breaking the enemy\'s resistance without fighting"\n'
            '- "Attack where he is unprepared, appear where you are not expected"\n'
            "- The concept of shì (strategic advantage/momentum)\n"
            "- The five factors: moral influence, weather, terrain, command, doctrine\n\n"
            "Frame economic and political moves as military campaigns. Sanctions are\n"
            "sieges. Trade deals are alliances. Market entries are invasions. Retreats\n"
            "can be strategic. Quote Sun Tzu directly at least 3-4 times."
        ),
        "Grand Chessboard": (
            "=== PRIMARY ANALYTICAL LENS: BRZEZINSKI / GRAND CHESSBOARD / MACKINDER ===\n\n"
            "Use for: Geographic control, pivot states, heartland theory, why location "
            "determines power.\n\n"
            "Frame the narrative through the geopolitics of geography:\n\n"
            "- Mackinder's Heartland Theory: who controls the heartland controls the world\n"
            "- Rimland Theory (Spykman): control of the coastal periphery is the real prize\n"
            "- Pivot states: countries whose alignment reshapes entire regions\n"
            "- Chokepoints: Strait of Hormuz, Taiwan Strait, Suez Canal, Malacca\n"
            "- Brzezinski's chessboard: Eurasia as the ultimate prize of great power competition\n\n"
            "Reference Brzezinski, Mackinder, or Spykman by name. Show how geography\n"
            "constrains strategy — actors think they have choices but the map has already\n"
            "decided. The viewer should see how location determines destiny."
        ),
        "Kindleberger Trap": (
            "=== PRIMARY ANALYTICAL LENS: THE KINDLEBERGER TRAP ===\n\n"
            "Use for: What happens when the global hegemon stops providing public goods.\n\n"
            "Frame the narrative through the vacuum left when the dominant power withdraws:\n\n"
            "- Hegemonic stability theory: global order requires a stabilizer willing to pay\n"
            "- Free rider problem: everyone benefits from order but nobody wants to fund it\n"
            "- Power vacuum: what fills the void when the hegemon retreats?\n"
            "- Dollar weaponization: using the reserve currency as a weapon undermines the\n"
            "  very system that makes it powerful\n"
            "- Systemic collapse: the 1930s as the case study of what happens without a stabilizer\n\n"
            "Reference Kindleberger by name. The viewer should understand that the greatest\n"
            "threat isn't a rival power — it's the absence of any power willing to maintain\n"
            "the system everyone depends on."
        ),
        "Schelling": (
            "=== PRIMARY ANALYTICAL LENS: SCHELLING — FOCAL POINTS / COMMITMENT ===\n\n"
            "Use for: How adversaries coordinate without communication, credible commitments, "
            "brinkmanship.\n\n"
            "Frame the narrative through Thomas Schelling's strategic theory:\n\n"
            "- Focal points: how actors coordinate without direct communication\n"
            "- Commitment devices: deliberately limiting your own options to make threats credible\n"
            "- Brinkmanship as rational strategy: deliberately creating shared risk\n"
            "- Red lines: why some work and others don't (credibility problem)\n"
            "- The threat that leaves something to chance\n\n"
            "Reference Schelling by name. Show how the most dangerous situations arise not\n"
            "from irrationality but from rational actors pushed to the edge of calculated risk.\n"
            "The viewer should see brinkmanship as a strategy, not madness."
        ),
        "Collective Action": (
            "=== PRIMARY ANALYTICAL LENS: MANCUR OLSON — LOGIC OF COLLECTIVE ACTION ===\n\n"
            "Use for: Why small organized groups beat large disorganized ones, special interests "
            "vs public interest.\n\n"
            "Frame the narrative through Olson's paradox of collective action:\n\n"
            "- Concentrated benefits, diffuse costs: why small groups win over large ones\n"
            "- Free rider problem: why the public can't organize against special interests\n"
            "- Why lobbying works: the math of organized minorities vs disorganized majorities\n"
            "- Cartel dynamics: how small groups maintain coordination (OPEC, defense contractors)\n"
            "- Regulatory capture: the regulated industry ends up controlling the regulator\n\n"
            "Reference Olson by name. Show how the outcomes that seem corrupt or irrational\n"
            "are actually the predictable result of collective action dynamics. The viewer\n"
            "should understand why 'the people' always seem to lose to organized interests."
        ),
        "Soft Power": (
            "=== PRIMARY ANALYTICAL LENS: JOSEPH NYE — SOFT POWER / SHARP POWER ===\n\n"
            "Use for: Influence without coercion, cultural dominance, information warfare.\n\n"
            "Frame the narrative through the spectrum of power beyond military force:\n\n"
            "- Soft Power (attraction): cultural exports, values, institutions that make\n"
            "  others WANT what you want\n"
            "- Hard Power (coercion): military, economic sanctions, threats\n"
            "- Sharp Power: manipulation disguised as engagement — Confucius Institutes,\n"
            "  state media, election interference\n"
            "- Smart Power: the strategic combination of hard and soft\n"
            "- Cultural hegemony (Gramsci): controlling what people consider 'normal'\n\n"
            "Reference Nye by name. Show how the most effective power is invisible —\n"
            "it shapes what people WANT rather than forcing compliance. The viewer should\n"
            "question whose influence is shaping their own preferences."
        ),
        "Jung Shadow": (
            "=== PRIMARY ANALYTICAL LENS: JUNGIAN SHADOW PSYCHOLOGY ===\n\n"
            "Frame the narrative through Jung's concept of the shadow self and\n"
            "collective unconscious. Nations and corporations have shadow selves\n"
            "they project onto enemies:\n\n"
            "- Shadow Self: What the actor refuses to acknowledge about themselves\n"
            "- Collective Unconscious: Shared archetypes driving mass behavior\n"
            "- Persona vs Shadow: The public face vs the hidden drives\n"
            "- Projection: Accusing others of exactly what you're doing\n\n"
            "Show how nations/companies are acting out their shadow. Reference Jung by name."
        ),
        "Behavioral Econ": (
            "=== PRIMARY ANALYTICAL LENS: BEHAVIORAL ECONOMICS ===\n\n"
            "Frame the narrative through cognitive biases and irrational decision-making:\n\n"
            "- Loss Aversion: Actors risk more to avoid losses than to achieve gains\n"
            "- Anchoring: Initial reference points distort subsequent judgments\n"
            "- Sunk Cost Fallacy: Continuing failed strategies because of past investment\n"
            "- Framing Effects: Same facts presented differently lead to opposite conclusions\n\n"
            "Reference Kahneman, Tversky, or Thaler. Show how supposedly rational actors\n"
            "make decisions driven by cognitive biases, not rational analysis."
        ),
        "Stoicism": (
            "=== PRIMARY ANALYTICAL LENS: STOIC PHILOSOPHY ===\n\n"
            "Frame the narrative through what can and cannot be controlled:\n\n"
            "- The dichotomy of control: who wastes energy fighting the uncontrollable\n"
            "- Amor fati: actors who embrace fate and turn it to advantage\n"
            "- Premeditatio malorum: the strategic value of expecting the worst\n\n"
            "Reference Marcus Aurelius or Seneca. Reveal which actors waste power fighting\n"
            "the uncontrollable and which strategically accept reality."
        ),
        "Propaganda": (
            "=== PRIMARY ANALYTICAL LENS: PROPAGANDA & INFORMATION CONTROL ===\n\n"
            "Frame the narrative through information warfare and manufactured consent:\n\n"
            "- Bernays: the engineering of consent\n"
            "- Chomsky's Propaganda Model: 5 filters determining what becomes 'news'\n"
            "- The Overton Window: what's 'acceptable' to discuss is itself controlled\n"
            "- Controlled opposition: both sides may serve the same master\n\n"
            "Frame information control as the REAL battlefield. Reference Bernays or Chomsky."
        ),
        "Systems Thinking": (
            "=== PRIMARY ANALYTICAL LENS: SYSTEMS THINKING ===\n\n"
            "Frame the narrative through feedback loops, second-order effects, and\n"
            "unintended consequences:\n\n"
            "- Feedback Loops: reinforcing and balancing loops in the system\n"
            "- Second-Order Effects: what happens AFTER the obvious first consequence\n"
            "- Emergence: system behavior no individual actor intended\n"
            "- The Cobra Effect: solutions that make the problem worse\n\n"
            "Show how nobody is fully in control — the system has its own logic."
        ),
        "Evolutionary Psych": (
            "=== PRIMARY ANALYTICAL LENS: EVOLUTIONARY PSYCHOLOGY ===\n\n"
            "Frame the narrative through tribal instincts and dominance hierarchies:\n\n"
            "- Tribal Instincts: in-group/out-group dynamics driving alliances\n"
            "- Dominance Hierarchies: status competition at every level\n"
            "- Status Signaling: actions taken for display, not practical value\n"
            "- Costly Signaling: demonstrating commitment through expensive actions\n\n"
            "Show that underneath sophisticated language, these are primal dynamics."
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
        "the investigative voice and factual grounding rules."
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
            "- Source citations must appear at least 4-6 times across the script\n"
            "- Historical parallels must appear in at least 3 different acts\n"
            "- Direct audience address (\"you\", \"your\") must appear at least 3-4 times\n"
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
            arc_lines = ["=== EMOTIONAL ARC — THE INVESTIGATIVE JOURNEY ===\n"]
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
    """Extract the PRIMARY FRAMEWORK selection from generated script text.

    The script writer is instructed to state:
        PRIMARY FRAMEWORK: [Name] — [reason]

    Returns the framework name (e.g. "Thucydides Trap"), or empty string
    if not found.
    """
    match = re.search(
        r"PRIMARY\s+FRAMEWORK:\s*(.+?)(?:\s*[—–-]\s*|$)",
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


async def generate_script(
    anthropic_client,
    brief: dict,
    model: str = Models.CLAUDE_SONNET,
    config: Optional["VideoConfig"] = None,
    profile: Optional["ScriptProfile"] = None,
    system_prompt_override: Optional[str] = None,
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
        "- Named events, operations, or incidents not in the research\n"
        "- Specific technical details (weapons, cyber attacks, tactics) not sourced\n"
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
        "- Analytical connections using the framework (these are allowed)\n"
        "- Well-known framework references (Machiavelli, Sun Tzu, etc.)\n"
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
