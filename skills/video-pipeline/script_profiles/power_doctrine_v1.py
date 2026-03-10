"""Power Doctrine v1 — Framework Explainer Voice.

This is the LEGACY editorial voice. It takes a documentary scriptwriter
approach, explaining geopolitical frameworks directly to the audience.
The narrator is a master storyteller teaching the viewer how power works.

Key differences from v2:
- Framework is introduced earlier (Act 3 vs Act 4)
- Teaching posture vs investigative/revealing posture
- Less emphasis on incentive chains, more on framework mechanics
- Acts named: Hook, Context, Framework, Proof, Consequences, Empowerment
- Less number-dense, more narrative-driven
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
    profile_id="power_doctrine_v1",
    profile_name="Power Doctrine — Framework Explainer",
    version="1.0",
    description=(
        "Documentary scriptwriter voice that explains geopolitical "
        "frameworks directly. Master storyteller teaching the viewer "
        "how power works through historical parallels and analytical lenses."
    ),
    channel="economy_fastforward",

    # === Voice Definition ===
    voice=VoiceConfig(
        identity=(
            "Documentary scriptwriter and master storyteller who reveals "
            "the hidden playbooks behind world events"
        ),
        tone="Authoritative, urgent, educational, dramatic but grounded",
        audience=(
            "Curious adults who want to understand geopolitics and power "
            "dynamics through analytical frameworks and historical patterns."
        ),
        audience_values=["framework understanding", "historical context", "pattern recognition"],
        audience_repelled_by=["sensationalism", "conspiracy theories", "unsourced claims"],
        narrator_posture="teaching",
    ),

    # === Structural Laws ===
    structural_laws=[
        (
            "Hook with a compelling event. Open with a specific headline "
            "event that has broader strategic implications. Set up the "
            "central question within 30 seconds."
        ),
        (
            "Build context before the framework. Give the viewer enough "
            "background to understand why the framework matters before "
            "introducing it."
        ),
        (
            "Every claim needs evidence. Use specific numbers, dates, and "
            "named sources. Avoid vague qualifiers."
        ),
        (
            "The framework IS the video. Unlike v2 where incentive chains "
            "dominate, here the analytical framework is the star. Explain "
            "it clearly, apply it to events, and teach detection."
        ),
        (
            "End with empowerment. The viewer must leave with frameworks "
            "and detection tools they can apply to future events."
        ),
        (
            "Use cliffhangers at act transitions. Keep the viewer engaged "
            "across the full 15-25 minute runtime."
        ),
    ],

    # === Content Ratio ===
    content_ratio={
        "framework_mechanics": {"min": 0.25, "max": 0.35},
        "historical_proof": {"min": 0.20, "max": 0.25},
        "current_events_application": {"min": 0.20, "max": 0.25},
        "personal_impact": {"min": 0.10, "max": 0.15},
        "empowerment_detection": {"min": 0.10, "max": 0.15},
    },

    # === Act Structure ===
    act_structure={
        "act_count": 6,
        "acts": [
            ActDefinition(
                act_number=1,
                name="THE EVENT",
                purpose="Hook with a compelling headline event",
                structure=[
                    "Open with breaking news or dramatic event",
                    "Establish the central question",
                    "Hint at deeper strategic dynamics",
                    "Tease the analytical framework that explains it",
                ],
                cliffhanger_template="But to understand why, you need to see the pattern. And it starts {teaser}.",
                psychological_beat="curiosity",
                min_numbers=2,
                word_pct=0.15,
            ),
            ActDefinition(
                act_number=2,
                name="THE CONTEXT",
                purpose="Background the viewer needs to understand the framework",
                structure=[
                    "Key players and their positions",
                    "Historical background with specific facts",
                    "What mainstream analysis gets right and wrong",
                    "Set up why a deeper lens is needed",
                ],
                cliffhanger_template="And that deeper lens has a name. It's been describing this exact scenario for {timeframe}.",
                psychological_beat="building_understanding",
                min_numbers=4,
                word_pct=0.15,
            ),
            ActDefinition(
                act_number=3,
                name="THE FRAMEWORK",
                purpose="Introduce and explain the analytical lens",
                structure=[
                    "Name the framework and its originator",
                    "Explain the core mechanics clearly",
                    "Show how it applies to the current event",
                    "Use the framework to reveal hidden dynamics",
                ],
                cliffhanger_template="And if you think this is just theory, history has proven it. Multiple times.",
                psychological_beat="intellectual_excitement",
                min_numbers=3,
                word_pct=0.17,
            ),
            ActDefinition(
                act_number=4,
                name="THE PROOF",
                purpose="Historical parallels proving the pattern is real",
                structure=[
                    "Historical event in vivid detail",
                    "Point-by-point mapping to the present",
                    "What the historical precedent predicts",
                    "Why this time the stakes are higher",
                ],
                cliffhanger_template="And here's what nobody is telling you about how this affects your life.",
                psychological_beat="conviction",
                min_numbers=3,
                word_pct=0.20,
            ),
            ActDefinition(
                act_number=5,
                name="THE CONSEQUENCES",
                purpose="Personal impact cascade — what this means for the viewer",
                structure=[
                    "Translate the framework to personal impact",
                    "Specific scenarios with dollar amounts",
                    "Address the strongest counterargument",
                    "Why the pattern is harder to escape than people think",
                ],
                cliffhanger_template=None,
                psychological_beat="personal_stakes",
                min_numbers=3,
                word_pct=0.18,
            ),
            ActDefinition(
                act_number=6,
                name="EMPOWERMENT",
                purpose="Frameworks taught + detection tools + what to watch",
                structure=[
                    "Name the frameworks and patterns from this video",
                    "Give 2-3 detection instructions",
                    "Specific signals to watch for",
                    "End with empowerment — the viewer is now equipped",
                ],
                cliffhanger_template=None,
                psychological_beat="empowerment",
                min_numbers=2,
                word_pct=0.15,
            ),
        ],
    },

    # === Number Density ===
    number_density=NumberDensityConfig(
        minimum_total=15,
        per_act={1: 2, 2: 4, 3: 3, 4: 3, 5: 3, 6: 2},
        definition=(
            "dollar amount, percentage, date, count, ratio, or named statistic"
        ),
        anti_words=["significant", "massive", "unprecedented"],
    ),

    # === Retention Engineering ===
    retention=RetentionConfig(
        cliffhanger_frequency="every_act_transition",
        micro_revelation_cadence_seconds=120,
        explicit_forward_sell=True,
        forward_sell_template=(
            "And in the next section, you'll see {teaser}."
        ),
    ),

    # === Language Rules ===
    language=LanguageConfig(
        use_phrases=[
            "Here's the pattern",
            "What history shows us",
            "The framework predicts",
            "When you see this pattern",
            "The analytical lens reveals",
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
        ],
        framework_naming_rules={
            "first_mention_act": 3,
            "max_direct_references": 5,
            "intro_template": (
                "{author} described this as {concept}, and what we're "
                "watching right now is a textbook case"
            ),
        },
    ),

    # === Framework Integration ===
    framework_integration=FrameworkIntegrationConfig(
        available_frameworks=[
            {"id": "machiavelli", "name": "Machiavelli", "domain": "power consolidation"},
            {"id": "thucydides", "name": "Thucydides Trap", "domain": "rising vs established power"},
            {"id": "antifragile", "name": "Antifragile / Black Swan", "domain": "asymmetric risk"},
            {"id": "game_theory", "name": "Game Theory", "domain": "deterrence, equilibrium"},
            {"id": "sun_tzu", "name": "Sun Tzu", "domain": "indirect warfare, deception"},
            {"id": "grand_chessboard", "name": "Grand Chessboard", "domain": "geographic control"},
            {"id": "kindleberger", "name": "Kindleberger Trap", "domain": "hegemon withdrawal"},
            {"id": "schelling", "name": "Schelling", "domain": "brinkmanship, focal points"},
            {"id": "collective_action", "name": "Collective Action", "domain": "organized minorities"},
            {"id": "soft_power", "name": "Soft Power", "domain": "influence without coercion"},
        ],
        selection_method="per_video",
        integration_style="explicit_teaching",
        max_runtime_pct=0.35,
    ),

    # === Incentive Chain ===
    incentive_chain=IncentiveChainConfig(
        required=False,
        must_complete_before_script=False,
        chain_template="",
        min_links=0,
        must_end_at_viewer=False,
        stored_in="Research Payload",
    ),

    # === Multi-Rationale Teardown ===
    teardown=TeardownConfig(
        enabled=False,
        trigger="",
        template=[],
    ),

    # === Script Validation Rules ===
    validation=ValidationConfig(
        min_words=2500,
        max_words=4500,
        min_acts=3,
        max_acts=8,
        number_density_check=True,
        kill_phrase_check=True,
        cliffhanger_check=True,
        incentive_chain_presence=False,
        framework_max_pct_check=False,
        personal_stakes_presence=True,
        actionable_ending_check=True,
        retry_on_fail=True,
        max_retries=2,
    ),

    # === Template Metadata ===
    template_metadata=TemplateMetadata(
        display_name="Power Doctrine — Framework Explainer",
        category="geopolitics_education",
        tags=["documentary", "frameworks", "education", "geopolitics"],
        description=(
            "Documentary-style explainer that teaches geopolitical frameworks "
            "through current events. Authoritative narrator guides the viewer "
            "through the analytical lens."
        ),
        best_for=["geopolitics", "history", "international relations", "strategy"],
        example_titles=[
            "The Thucydides Trap Explained — Why Great Powers Always Clash",
            "How the Grand Chessboard Predicts the Next Global Conflict",
        ],
    ),

    # === Emotional Arc ===
    emotional_arc={
        1: "SURPRISE -> CURIOSITY. A dramatic event hooks the viewer and raises the central question.",
        2: "CURIOSITY -> UNDERSTANDING. Context builds the viewer's mental model of the situation.",
        3: "UNDERSTANDING -> INSIGHT. The framework clicks into place and the viewer sees the pattern.",
        4: "INSIGHT -> CONVICTION. Historical proof shows the pattern is real, not coincidence.",
        5: "CONVICTION -> CONCERN. The abstract becomes personal — the viewer's life is affected.",
        6: "CONCERN -> EMPOWERMENT. Detection tools and frameworks equip the viewer for the future.",
    },

    # === Act-Specific Rules ===
    act_specific_rules="""\
=== ACT-SPECIFIC RULES (V1 — FRAMEWORK EXPLAINER VOICE) ===

Act 1 (The Event):
Open with a compelling headline event. Set up the central question \
within 30 seconds. Hint at the deeper pattern. The viewer should \
feel "this is bigger than they're telling us." Minimum 2 numbers.

Act 2 (The Context):
Provide the historical and strategic background. Key players, their \
positions, the conventional analysis. Build toward: "but conventional \
analysis misses the deeper pattern." Minimum 4 numbers.

Act 3 (The Framework):
Name the framework and its originator. Explain the core mechanics \
clearly — the viewer should understand the concept. Apply it to the \
current event. This is the intellectual core of the video. Minimum 3 numbers.

Act 4 (The Proof):
Historical parallel in vivid detail. Point-by-point mapping to the \
present. The historical record PROVES the framework works. What \
the precedent predicts for the current situation. Minimum 3 numbers.

Act 5 (The Consequences):
Make it personal. Specific scenarios with dollar amounts. Address \
the strongest counterargument fairly. Show why the pattern matters \
for the viewer's life. Minimum 3 numbers.

Act 6 (Empowerment):
Name every framework and pattern taught in this video. Give 2-3 \
detection instructions. End on empowerment — the viewer leaves \
equipped, not afraid. NEVER end with dread or helplessness.
""",

    # === Micro-Payoff Architecture ===
    micro_payoff_architecture="""\
=== MICRO-REVELATION ARCHITECTURE ===

Every 2 minutes of narration should deliver a specific insight — a fact, \
historical connection, or framework application the viewer didn't know.

Structure within each scene:
- SETUP: Establish the context or claim
- FRAMEWORK APPLICATION: Apply the analytical lens
- INSIGHT: The "aha" moment — what the framework reveals
- BRIDGE: Connect to the next scene
""",

    # === Framework Selection Rules ===
    framework_selection_rules="""\
=== FRAMEWORK SELECTION ===

Select 1-2 primary frameworks that BEST explain the events in this story.

State your framework selection at the top of the outline:
PRIMARY FRAMEWORK: [Name] — [Why this framework explains these events]
SECONDARY FRAMEWORK: [Name] — [What additional dimension this adds]
""",

    # === Framework Revelation Engine ===
    framework_revelation_engine="""\
=== FRAMEWORK INTEGRATION — EXPLICIT TEACHING ===

The framework is the star of the video. Introduce it in Act 3 with \
clear explanation. Apply it throughout Acts 4-6. The viewer should \
leave understanding the framework well enough to apply it themselves.

Reference the framework author by name. Use specific concepts and \
terminology. The viewer is here to LEARN the framework, not just \
see it operating invisibly.
""",

    # === Strict Grounding Rule ===
    strict_grounding_rule="""\
=== FACTUAL GROUNDING RULE ===

Every factual claim must come from the research payload. You may NOT \
introduce companies, people, events, or statistics not in the research.

Historical parallels must come from the research payload's \
historical_parallels field. Framework references (Machiavelli, Sun Tzu, \
etc.) are always allowed as analytical tools.

WHAT YOU CAN CREATE:
- Dramatic pacing, rhetorical questions
- Analytical connections using the framework
- Metaphors and analogies

WHAT YOU CANNOT CREATE:
- Events that did not happen
- Statistics not in the payload
- Quotes not in the payload
""",
)
