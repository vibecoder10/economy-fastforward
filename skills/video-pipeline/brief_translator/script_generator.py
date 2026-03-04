"""Script Generation (Step 2).

Transforms a validated research brief into a 15-20 minute narration script
with six-act structure, micro-payoff architecture, and act markers.
"""

import re
from pathlib import Path

PROMPT_TEMPLATE_PATH = Path(__file__).parent / "prompts" / "script.txt"

# Word count bounds for the full script (15-20 min at ~160 wpm)
SCRIPT_MIN_WORDS = 2200
SCRIPT_MAX_WORDS = 3200
SCRIPT_TARGET_WORDS = 2800

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


# ---------------------------------------------------------------------------
# Prompt overrides — appended after the base template to update act structure,
# inject micro-payoff architecture, framework revelation engine, and
# per-act rules.  Keeps script.txt untouched.
# ---------------------------------------------------------------------------

_ACT_STRUCTURE_OVERRIDE = """\
=== UPDATED SCRIPT PARAMETERS — THESE OVERRIDE THE ACT STRUCTURE ABOVE ===

This is a 15-20 minute video, NOT a 25-minute video. Follow these targets:

Target total: ~2,800 words (~17 minutes at 160 words/min)
Minimum: 2,200 words (~14 min). Maximum: 3,200 words (~20 min).

Act word targets:
- Act 1 (The Hook): ~350 words (0:00-2:10) — Immediate revelation, pattern interrupt, personal stakes
- Act 2 (The Foundation): ~450 words (2:10-5:00) — First historical parallel, factual foundation with insights woven in
- Act 3 (The Mechanism): ~500 words (5:00-8:10) — How the system actually works, the hidden machinery
- Act 4 (The Mirror): ~500 words (8:10-11:20) — Historical parallel deepened, framework analysis peak
- Act 5 (The Stakes): ~500 words (11:20-14:30) — Personal implications, counter-arguments addressed
- Act 6 (The Lesson): ~500 words (14:30-17:30) — Prediction, actionable insight, lingering close
"""

_MICRO_PAYOFF_ARCHITECTURE = """\
=== MICRO-PAYOFF ARCHITECTURE — NON-NEGOTIABLE ===

Every scene (60-90 seconds of narration) must follow this structure:

HOOK (first 1-2 sentences): Open with a question, a bold claim, or a \
"wait what?" moment that makes the viewer need to hear the next 60 seconds. \
This hooks them into THIS scene specifically.

BUILD (middle): Develop the point with evidence, examples, or narrative. \
Each fact should reframe what the viewer thought they knew.

PAYOFF (last 1-2 sentences): Deliver a genuine micro-revelation — a \
"holy shit" insight, a counterintuitive conclusion, or a reframe that \
changes how they see the topic. This is NOT a cliffhanger — it's a \
REWARD for watching this scene.

BRIDGE (final sentence): The payoff naturally raises a NEW question that \
pulls them into the next scene. "But that raises an even darker \
question..." or "And that's exactly what made the next move inevitable."

The viewer should feel REWARDED every 60-90 seconds. Not teased — rewarded. \
Each micro-payoff is a genuine insight they can take away even if they stop \
watching. But the bridge makes them unable to stop.

Think of it like chapters in a thriller — each one delivers a satisfying \
conclusion while making the next chapter irresistible.

BAD example (tease without payoff):
"And what happened next would change everything. But first, let's \
understand the background..."

GOOD example (payoff + bridge):
"Iran didn't strike Ras Tanura to destroy it. They struck it to prove \
that every dollar of Saudi oil wealth now exists at their mercy — and the \
cost of that proof was twenty thousand dollars. One drone. That's the \
asymmetry that breaks empires. But the real question isn't whether Iran \
can do it again. It's what happens when the insurance companies decide \
the Strait isn't worth the risk."
"""

_FRAMEWORK_REVELATION_ENGINE = """\
=== FRAMEWORK INTEGRATION — THE FRAMEWORK IS THE PAYOFF ===

The selected framework isn't decoration. It IS the insight. \
Every micro-payoff should be a framework revelation applied to the story.

The pattern for every scene:
1. Present the EVENT (what happened)
2. Apply the FRAMEWORK (why it happened — through the selected lens)
3. Deliver the PAYOFF (what this reveals about power/human nature)

BAD: "Iran struck Ras Tanura. This is an example of asymmetric warfare."
(Framework as label — boring, academic, forgettable)

GOOD: "Iran struck Ras Tanura with a twenty-thousand-dollar drone. The \
selected framework explains WHY this specific move was inevitable — and \
reveals a deeper truth the viewer didn't see. The framework doesn't just \
describe what happened, it shows the hidden logic that MADE it happen."
(Framework as revelation — the framework EXPLAINS the deeper truth the \
viewer didn't see)

The framework should make the viewer feel like they've been given X-ray \
vision. They're not just learning what happened — they're learning HOW TO \
SEE power dynamics everywhere.

EVERY ACT must have at least one moment where the framework creates an \
"I'll never see the world the same way" insight. These are the moments \
viewers screenshot and share.

Framework escalation across acts:
- Act 1: Introduce the selected framework as a surprising lens on the \
headline event
- Act 2: Apply the framework to the factual foundation — "now watch what \
happens when you see these facts through this lens"
- Act 3: The framework reveals the HIDDEN MECHANISM — the thing nobody \
else is explaining
- Act 4: The historical parallel PROVES the framework — "this exact pattern \
played out before because the same dynamic was operating"
- Act 5: Turn the framework on the VIEWER — "and here's the uncomfortable \
truth: you're subject to this same dynamic in your own life. When your boss \
does X, when markets do Y, when you feel Z — that's this exact pattern \
operating on you"
- Act 6: The framework becomes a PERMANENT TOOL — "now that you see it, you \
can't unsee it. Watch for X. When you see Y happening, you'll know Z is \
coming. That's not prediction — that's pattern recognition."

The viewer should leave every video feeling like they've been handed a new \
pair of glasses. The framework IS the product. The geopolitical story is \
just the case study.

CRITICAL: Do NOT name-drop frameworks without applying them. Every framework \
reference must REVEAL something the viewer didn't see before. The framework \
must be followed by showing HOW it explains a specific hidden move in the \
story that the viewer missed.

CRITICAL: The framework must feel like a REVELATION, not an academic label. \
Do not say 'This is an example of the Thucydides Trap.' Say 'There is a \
pattern that has preceded every major war for 2,500 years. Athens and Sparta. \
Britain and Germany. And right now, the same pattern is playing out between \
Washington and Beijing and we are at the exact stage where Thucydides says \
the trap becomes inescapable.'

The viewer should leave every video having LEARNED A FRAMEWORK they can apply \
to other situations. That is the product. The geopolitical story is just the \
delivery vehicle.
"""

_FRAMEWORK_SELECTION_RULES = """\
=== FRAMEWORK SELECTION — DYNAMIC PER-VIDEO ===

Before writing the outline, select 1-2 primary frameworks that BEST explain \
the power dynamics in this story. Do not default to Machiavelli. Choose the \
framework that creates the most powerful revelation.

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
- Which framework makes the viewer see a HIDDEN MECHANISM they did not know \
was operating?
- Which framework connects this specific event to a UNIVERSAL PATTERN the \
viewer will see everywhere?
- Which framework gives the viewer a TOOL they can use to predict what happens next?

State your framework selection at the top of the outline:
PRIMARY FRAMEWORK: [Name] — [One sentence on why this framework cracks open \
this story]
SECONDARY FRAMEWORK: [Name] — [One sentence on what additional dimension \
this adds]

The primary framework drives Acts 1-4. The secondary framework enriches \
Acts 4-6.
"""

_FRAMEWORK_PSYCH_SEPARATION = """\
=== FRAMEWORK vs PSYCHOLOGICAL ANGLE — TWO DIFFERENT TOOLS ===

FRAMEWORK (constant across entire video): The intellectual lens that \
explains WHY. Selected once during outline. Every act analyzes through this \
same lens, building deeper understanding with each act.

PSYCHOLOGICAL ANGLE (varies per act): The emotional lever that makes each \
act FEEL different. Creates an emotional arc across the video. Use different \
angles per act:
- Act 1: Shock, betrayal, or pattern interrupt
- Act 2: Paranoia, curiosity, or revelation
- Act 3: Fascination with the hidden mechanism
- Act 4: Historical dread or recognition
- Act 5: Personal vulnerability or anger
- Act 6: Empowerment, clarity, or permanent reframe

The framework is the WHAT (intellectual). The psych angle is the HOW \
(emotional). Together they create videos where the viewer both LEARNS \
something and FEELS something every 60 seconds.

Each act should apply the SAME framework but through a DIFFERENT emotional \
lens. Act 1 reveals the framework through shock. Act 4 proves the framework \
through historical dread. Act 6 delivers the framework as empowerment.
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
"""

_ACT_SPECIFIC_RULES = """\
=== ACT-SPECIFIC RULES (UPDATED) ===

Act 1 (The Hook):
This act must contain at least 2 micro-payoffs. The viewer must have \
learned something genuinely surprising within the first 60 seconds AND \
again before the act ends.

Act 2 (The Foundation):
Every paragraph must contain at least one 'wait, what?' fact. Do not dump \
context without insight. If you're explaining background, frame it as a \
revelation: not 'Iran has proxies' but 'Iran built a shadow empire across \
4 countries that costs less to maintain than a single US aircraft carrier.'

Act 3 (The Mechanism):
This is the MECHANISM act — explain HOW the hidden system works. Each \
paragraph should make the viewer feel like they're being let in on a \
secret. End with a payoff that makes them see the mechanism in everything.

Act 4 (The Mirror):
The historical parallel should feel like proof that this is a PATTERN, \
not coincidence. The payoff should be the moment the viewer realizes \
'this has happened before and the outcome was...' Bridge to stakes.

Act 5 (The Stakes):
Make it personal. The viewer should feel this in their wallet, their \
career, their daily life. Counter-arguments should be steel-manned then \
dismantled through the framework. Payoff: the viewer now sees something \
they can't unsee.

Act 6 (The Lesson):
The prediction must be specific and falsifiable — not 'things will change' \
but 'watch for X within Y months.'

Act 6 MUST end with EMPOWERMENT. The final scene is where the viewer \
receives their permanent toolkit. This is NON-NEGOTIABLE. The close must:

1. NAME the specific frameworks taught in this video by name (e.g. \
'regulatory capture', 'sovereign exception', 'the panopticon effect'). \
List them explicitly — the viewer must hear the framework names repeated \
so they stick.

2. Give DETECTION INSTRUCTIONS: 'When you see X, ask Y. When A happens, \
look for B within 48 hours.' Concrete, actionable, specific to the \
frameworks taught. At least 2-3 detection rules.

3. Frame knowledge as POWER: the viewer now sees what 99% of people miss. \
They have X-ray vision for power dynamics. They are now part of the small \
minority who understand how the game actually works.

4. End on AGENCY: 'Now that you see the pattern, you can't unsee it. \
That's not paranoia. That's pattern recognition.' The viewer must leave \
feeling SMARTER and MORE POWERFUL than when they started. NOT scared. \
NOT helpless. NOT cynical. NOT passive.

BAD close (DO NOT WRITE ANYTHING LIKE THIS):
'The window is closing and nobody will notice.' (passive, fearful, helpless)
'Whether anyone will notice before it's too late.' (dread, no agency)
'The cage is closing and you're trapped.' (helpless)

GOOD close (THIS IS THE MODEL — study its structure):
'You just learned regulatory capture, sovereign exception, and the \
panopticon effect. When a company gets designated, ask who signs a \
contract within 48 hours. When you see all lawful purposes in any \
agreement, find the classified interpretation. When one player gets \
punished, watch who self-censors without being told. You now read the \
game better than most people in Washington. The question isn't whether \
the system is rigged. You now know how. The question is what you do \
with that.'

If the final scene does NOT contain explicit framework names AND at least \
2 concrete detection instructions, the script has FAILED this requirement.
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

    # Append updated act structure, micro-payoff architecture, framework
    # selection rules, revelation engine, and act-specific rules.  These
    # override the older 25-minute / 3,750-word instructions baked into
    # script.txt.
    rendered += "\n\n" + _ACT_STRUCTURE_OVERRIDE
    rendered += "\n\n" + _MICRO_PAYOFF_ARCHITECTURE
    rendered += "\n\n" + _FRAMEWORK_SELECTION_RULES
    rendered += "\n\n" + _FRAMEWORK_REVELATION_ENGINE
    rendered += "\n\n" + _FRAMEWORK_PSYCH_SEPARATION
    rendered += "\n\n" + _ACT_SPECIFIC_RULES
    rendered += "\n\n" + _STRICT_GROUNDING_RULE

    return rendered


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

    # If script is too long, try once more with explicit compression instruction
    if not validation["valid"] and validation["word_count"] > SCRIPT_MAX_WORDS:
        compression_prompt = (
            f"{prompt}\n\n"
            f"CRITICAL: Your previous attempt was {validation['word_count']} words. "
            f"The script MUST NOT exceed {SCRIPT_MAX_WORDS} words. Target: {SCRIPT_TARGET_WORDS} words. "
            f"Cut unnecessary examples, reduce redundant transitions, and tighten each act. "
            f"Do NOT cut framework references or detection instructions from Act 6."
        )
        script = await anthropic_client.generate(
            prompt=compression_prompt,
            model=model,
            max_tokens=8000,
            temperature=0.7,
        )
        validation = validate_script(script)

    # Validate Act 6 empowerment close
    from .scene_validator import validate_act6_empowerment

    acts = extract_acts(script)
    act6_text = acts.get(6, "")
    empowerment_check = validate_act6_empowerment(act6_text)
    if not empowerment_check["valid"]:
        validation["act6_empowerment_issues"] = empowerment_check["issues"]
        # Log but don't block — the issues list in validation already
        # drives downstream decisions
        for issue in empowerment_check["issues"]:
            if "issues" not in validation:
                validation["issues"] = []
            validation["issues"].append(issue)
            validation["valid"] = False

    return {
        "script": script,
        "validation": validation,
    }
