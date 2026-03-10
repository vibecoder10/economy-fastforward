"""Power Doctrine v2 — Investigative Reveal Voice.

This is the CURRENT production editorial voice for Economy FastForward.
It traces hidden incentive chains behind major geopolitical and economic
events. The narrator is an investigative analyst who followed the money
trail and found something the public isn't being told.

Extracted from:
- brief_translator/prompts/script.txt
- brief_translator/script_generator.py (_ACT_SPECIFIC_RULES, etc.)
- pipeline_config.py (ACT_TEMPLATES for 6-act structure)
"""

from .schema import (
    ActDefinition,
    FrameworkIntegrationConfig,
    IncentiveChainConfig,
    LanguageConfig,
    NumberDensityConfig,
    RetentionConfig,
    ScriptProfile,
    TeardownConfig,
    TemplateMetadata,
    ValidationConfig,
    VoiceConfig,
)

PROFILE = ScriptProfile(
    # === Identity ===
    profile_id="power_doctrine_v2",
    profile_name="Power Doctrine — Investigative Reveal",
    version="2.0",
    description=(
        "Investigative analyst voice that traces incentive chains behind "
        "major geopolitical and economic events. Follows the money trail "
        "and reveals what the public isn't being told."
    ),
    channel="economy_fastforward",

    # === Voice Definition ===
    voice=VoiceConfig(
        identity=(
            "Investigative Analyst who followed the money trail and found "
            "something the public isn't being told"
        ),
        tone="Pragmatic, unsentimental, data-driven, urgent but controlled",
        audience=(
            "Ambitious 18-45 adults who want to understand how power and "
            "money actually move. They are skeptical of mainstream narratives."
        ),
        audience_values=["intelligence", "specificity", "actionable insight"],
        audience_repelled_by=["lectures", "vague claims", "academic framing"],
        narrator_posture="revealing",
    ),

    # === Structural Laws ===
    structural_laws=[
        (
            "Lead with the lie, not the truth. Open by stating the official "
            "narrative and breaking it with one contradicting fact. When "
            "multiple official rationales exist, walk through each and let "
            "them contradict each other. The viewer must feel 'wait, that "
            "doesn't add up' within 30 seconds."
        ),
        (
            "Build the incentive chain first. Before explaining HOW "
            "something happened, trace WHO benefits and WHY. Every player "
            "has a specific incentive — political survival, capital flows, "
            "market position, regime legitimacy. Connect these incentives "
            "into a chain leading from the headline event to the viewer's "
            "wallet. This chain IS the video. 40-50% of runtime."
        ),
        (
            "Every claim gets a number. No 'significant' or 'massive' — "
            "give the dollar amount, percentage, date, or count. Numbers "
            "create the feeling of insider intelligence briefing."
        ),
        (
            "The framework is invisible scaffolding until Act 4. Show the "
            "pattern playing out before you name it. Never say 'Machiavelli "
            "wrote that...' in the first 10 minutes. Framework/tactical "
            "mechanics must never exceed 15% of total script time."
        ),
        (
            "End with a specific action, not an insight. Investment thesis, "
            "sector to watch, risk to hedge, signal to monitor. The viewer "
            "should be able to DO something with what they learned."
        ),
        (
            "Explicit cliffhangers at every act transition. Sell the next "
            "section to the viewer. These are the moments viewers are most "
            "likely to click away. The cliffhanger catches them."
        ),
    ],

    # === Content Ratio ===
    content_ratio={
        "incentive_chain_money_trail": {"min": 0.40, "max": 0.50},
        "personal_stakes": {"min": 0.15, "max": 0.20},
        "historical_proof": {"min": 0.15, "max": 0.20},
        "framework_mechanics": {"min": 0.05, "max": 0.15},
        "actionable_strategy": {"min": 0.05, "max": 0.10},
    },

    # === Act Structure ===
    act_structure={
        "act_count": 6,
        "acts": [
            ActDefinition(
                act_number=1,
                name="THE LIE",
                purpose="State the official story and plant the seed of doubt",
                structure=[
                    "Open with headline event (one sentence, present tense, specific date)",
                    "State what 'everyone' is being told",
                    "Drop ONE contradicting fact with a specific number",
                    "Thesis preview: 'When you follow the [money], you find something different'",
                ],
                cliffhanger_template="And what you'll see by Part {next_act} is that {teaser}.",
                psychological_beat="shock",
                min_numbers=2,
                word_pct=0.10,
            ),
            ActDefinition(
                act_number=2,
                name="THE SETUP",
                purpose="Key players, their POSITIONS and INCENTIVES, factual foundation",
                structure=[
                    "Introduce key players by their incentives, not biographies",
                    "Facts with specific numbers, dates, named sources",
                    "What surface analysis says and why it's incomplete",
                    "End with: 'But here's what none of this explains...'",
                ],
                cliffhanger_template="And that missing piece is exactly what Part {next_act} reveals.",
                psychological_beat="paranoia",
                min_numbers=5,
                word_pct=0.20,
            ),
            ActDefinition(
                act_number=3,
                name="THE HIDDEN MECHANISM",
                purpose="Reveal the real dynamic — money trail, power flow, strategic logic",
                structure=[
                    "Present the mechanism through evidence, not theory",
                    "Show the money trail with specific data",
                    "Connect dots mainstream coverage missed",
                    "First historical parallel as PROOF the pattern is real",
                ],
                cliffhanger_template=(
                    "But there's one more layer that changes everything "
                    "— and it affects you directly."
                ),
                psychological_beat="fascination",
                min_numbers=4,
                word_pct=0.25,
            ),
            ActDefinition(
                act_number=4,
                name="THE PROOF",
                purpose="Historical parallel validates the mechanism. Framework named HERE.",
                structure=[
                    "Historical event in vivid detail (dates, figures, outcomes)",
                    "Point-by-point mapping to present",
                    "NOW name the framework: 'What you're watching is what [Author] called...'",
                    "What the historical precedent PREDICTS",
                ],
                cliffhanger_template=(
                    "And here's the part that every "
                    "[retail investor/worker/person with savings] needs to hear."
                ),
                psychological_beat="historical_dread",
                min_numbers=3,
                word_pct=0.20,
            ),
            ActDefinition(
                act_number=5,
                name="THE PERSONAL STAKES",
                purpose="Make it about the viewer's money, career, life. Steel-man opposition.",
                structure=[
                    "'Here's what this means for your [wallet/portfolio/job]'",
                    "Specific scenarios with dollar amounts",
                    "Steel-man the strongest counterargument",
                    "Dismantle it with evidence, not opinion",
                ],
                cliffhanger_template=None,
                psychological_beat="personal_vulnerability",
                min_numbers=3,
                word_pct=0.15,
            ),
            ActDefinition(
                act_number=6,
                name="THE PLAY",
                purpose="Specific, actionable strategy based on everything learned",
                structure=[
                    "'So what do you actually DO with this?'",
                    "Specific action: investment thesis, risk to hedge, sector to watch",
                    "Historical data supporting the timing/approach",
                    "Final line connecting back to opening lie — make it linger",
                ],
                cliffhanger_template=None,
                psychological_beat="empowerment",
                min_numbers=2,
                word_pct=0.10,
            ),
        ],
    },

    # === Number Density ===
    number_density=NumberDensityConfig(
        minimum_total=19,
        per_act={1: 2, 2: 5, 3: 4, 4: 3, 5: 3, 6: 2},
        definition=(
            "dollar amount, percentage, date, count, ratio, or named statistic"
        ),
        anti_words=["significant", "massive", "unprecedented", "growing"],
    ),

    # === Retention Engineering ===
    retention=RetentionConfig(
        cliffhanger_frequency="every_act_transition",
        micro_revelation_cadence_seconds=90,
        explicit_forward_sell=True,
        forward_sell_template=(
            "And what you'll see in {next_section} is {teaser}. "
            "That's where {payoff_preview}."
        ),
    ),

    # === Language Rules ===
    language=LanguageConfig(
        use_phrases=[
            "Follow the money",
            "Here's what doesn't add up",
            "Nobody is talking about this part",
            "The official story is... but the actual [data/timeline] shows...",
            "Position yourself",
            "When you look at the actual numbers...",
        ],
        kill_phrases=[
            "In this video, we'll explore",
            "Let's dive into",
            "It's important to understand",
            "Many experts believe",
            "This is significant because",
            "Throughout history",
            "In conclusion",
            "Like and subscribe",
            "What do you think? Leave a comment",
        ],
        framework_naming_rules={
            "first_mention_act": 4,
            "max_direct_references": 2,
            "intro_template": (
                "What you're watching is what {author} identified as {concept}"
            ),
        },
    ),

    # === Framework Integration ===
    framework_integration=FrameworkIntegrationConfig(
        available_frameworks=[
            {"id": "machiavelli", "name": "Machiavelli", "domain": "power consolidation"},
            {"id": "48_laws", "name": "48 Laws of Power", "domain": "strategic theater"},
            {"id": "thucydides", "name": "Thucydides Trap", "domain": "rising vs established power"},
            {"id": "antifragile", "name": "Antifragile / Black Swan", "domain": "asymmetric risk"},
            {"id": "game_theory", "name": "Game Theory", "domain": "deterrence, equilibrium"},
            {"id": "sun_tzu", "name": "Sun Tzu", "domain": "indirect warfare, deception"},
            {"id": "grand_chessboard", "name": "Grand Chessboard", "domain": "geographic control"},
            {"id": "kindleberger", "name": "Kindleberger Trap", "domain": "hegemon withdrawal"},
            {"id": "schelling", "name": "Schelling", "domain": "brinkmanship, focal points"},
            {"id": "collective_action", "name": "Collective Action", "domain": "organized minorities"},
            {"id": "soft_power", "name": "Soft Power", "domain": "influence without coercion"},
            {"id": "jung_shadow", "name": "Jung Shadow", "domain": "projection, shadow self"},
            {"id": "behavioral_econ", "name": "Behavioral Econ", "domain": "cognitive biases"},
            {"id": "stoicism", "name": "Stoicism", "domain": "control, fate acceptance"},
            {"id": "propaganda", "name": "Propaganda", "domain": "information control"},
            {"id": "systems_thinking", "name": "Systems Thinking", "domain": "feedback loops"},
            {"id": "evolutionary_psych", "name": "Evolutionary Psych", "domain": "tribal instincts"},
        ],
        selection_method="per_video",
        integration_style="invisible_scaffolding",
        max_runtime_pct=0.15,
    ),

    # === Incentive Chain ===
    incentive_chain=IncentiveChainConfig(
        required=True,
        must_complete_before_script=True,
        chain_template=(
            "Player A needs X -> requires Y -> depends on Z -> "
            "headline threatens this -> viewer impact"
        ),
        min_links=4,
        must_end_at_viewer=True,
        stored_in="Research Payload",
    ),

    # === Multi-Rationale Teardown ===
    teardown=TeardownConfig(
        enabled=True,
        trigger="multiple_official_rationales",
        template=[
            "First, we were told {rationale_1}. But {contradicting_fact_1}.",
            "Then the story changed to {rationale_2}. But {contradicting_fact_2}.",
            "Then {rationale_3}.",
            "Want to know why the story keeps changing? Because {real_reason}.",
        ],
    ),

    # === Script Validation Rules ===
    validation=ValidationConfig(
        min_words=2200,
        max_words=3200,
        min_acts=3,
        max_acts=8,
        number_density_check=True,
        kill_phrase_check=True,
        cliffhanger_check=True,
        incentive_chain_presence=True,
        framework_max_pct_check=True,
        personal_stakes_presence=True,
        actionable_ending_check=True,
        retry_on_fail=True,
        max_retries=2,
    ),

    # === Template Metadata (for StoryEngine) ===
    template_metadata=TemplateMetadata(
        display_name="Power Doctrine — Investigative Reveal",
        category="geopolitics_finance",
        tags=["investigative", "power dynamics", "finance", "geopolitics"],
        description=(
            "Traces hidden incentive chains behind major events. Follows "
            "the money from headline to viewer's wallet. Investigative "
            "analyst voice — pragmatic, data-driven, specific."
        ),
        best_for=["geopolitics", "finance", "corporate power", "economic policy"],
        example_titles=[
            "The Iran War Isn't About Nukes — Follow the Money",
            "Why China's Real Target Isn't Taiwan (It's Your 401k)",
        ],
    ),

    # === Emotional Arc ===
    emotional_arc={
        1: (
            "DECEPTION -> SUSPICION. The viewer realizes they've been lied to. "
            "They feel betrayed by the official narrative. Curiosity gap opened."
        ),
        2: (
            "CURIOSITY -> RECOGNITION. The viewer starts seeing the incentive "
            "chain. 'Oh, so THAT'S why...' Each fact adds to the picture."
        ),
        3: (
            "RECOGNITION -> REVELATION. The money trail clicks into place. "
            "The viewer feels like they're seeing behind the curtain."
        ),
        4: (
            "REVELATION -> CONVICTION. The historical parallel proves this is "
            "a PATTERN, not coincidence. The framework name confirms what they "
            "already intuited."
        ),
        5: (
            "CONVICTION -> ALARM. The abstract becomes personal. Dollar amounts "
            "hit the viewer's life directly. Genuine unsettlement."
        ),
        6: (
            "ALARM -> EMPOWERMENT. The viewer receives specific tools and "
            "actions. They leave feeling SMARTER and MORE CAPABLE. Not scared "
            "— armed."
        ),
    },

    # === Act-Specific Rules ===
    act_specific_rules="""\
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
Build the incentive chain: Player A needs X -> requires Y -> depends on Z. \
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
Minimum 3 specific numbers.

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
""",

    # === Micro-Payoff Architecture ===
    micro_payoff_architecture="""\
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
""",

    # === Framework Selection Rules ===
    framework_selection_rules="""\
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
""",

    # === Framework Revelation Engine ===
    framework_revelation_engine="""\
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
""",

    # === Strict Grounding Rule ===
    strict_grounding_rule="""\
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
""",
)
