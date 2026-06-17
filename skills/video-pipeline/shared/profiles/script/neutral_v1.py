"""Neutral v1 — Universal Craft (the default profile).

This is the DEFAULT editorial voice for StoryEngine. It encodes only the
UNIVERSAL craft of a good narration script — a clear arc, concrete scenes,
honest factual grounding, retention through curiosity — and NOTHING about any
particular channel's identity.

The identity (the voice, the recurring lens, the audience, the signature
structure) is injected per channel at runtime. A fresh creator, an ESL
channel, a cooking channel, or a story channel all generate fine under this
profile because every Power-Doctrine-specific gate is OFF:

- No required number density (a story script has no statistics).
- No required incentive chain ("who benefits → your wallet").
- No required framework / lens (the channel may have none).
- No required "personal stakes" (your 401k) or actionable/investment close.
- No documentary research-brief gate — a simple premise is enough to start.

Power Doctrine is reintroduced as an OPT-IN profile (power_doctrine_v2),
selected via the ``SCRIPT_PROFILE`` env var or an explicit profile_id, NOT as
the hard-wired default.

Note on text blocks (micro_payoff_architecture, framework_selection_rules,
framework_revelation_engine, act_specific_rules, strict_grounding_rule): these
are intentionally left EMPTY. The script generator already falls back to its
own identity-neutral defaults for each of these (see script_generator.py),
which are written generically (cooking/ESL examples, no geopolitics). Leaving
them empty here keeps the neutral profile from re-introducing any identity.
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
    profile_id="neutral_v1",
    profile_name="Neutral — Universal Craft",
    version="1.0",
    description=(
        "Neutral universal craft — the default. Encodes only the universal "
        "craft of a strong narration script (clear arc, concrete scenes, "
        "factual grounding, retention). The channel's identity — voice, "
        "audience, recurring lens — is injected per channel at runtime."
    ),
    channel="",

    # === Voice Definition — generic, no identity ===
    voice=VoiceConfig(
        identity="a clear, engaging narrator for this channel's audience",
        tone="Clear, engaging, and concrete — write scenes, not summaries",
        audience="this channel's audience",
        audience_values=["clarity", "being respected", "a satisfying payoff"],
        audience_repelled_by=["padding", "vague claims", "condescension"],
        narrator_posture="explaining",
    ),

    # === Structural Laws — universal craft only ===
    structural_laws=[
        (
            "Open on something concrete the viewer can picture, and give them "
            "a reason to care in the first beat."
        ),
        (
            "Every section moves the viewer forward — emotionally and "
            "informationally. No padding, no detours that don't pay off."
        ),
        (
            "Ground every claim in the material you were given. Don't invent "
            "facts to fill a gap."
        ),
        (
            "End with a real payoff — resolve the question the opening "
            "promised. Leave the viewer better off than they arrived."
        ),
    ],

    # === Content Ratio — none required ===
    content_ratio={},

    # === Act Structure — short, flexible, unconstrained ===
    act_structure={
        "act_count": 3,
        "acts": [
            ActDefinition(
                act_number=1,
                name="OPEN",
                purpose="Hook the viewer and set up the question or stakes",
                structure=[
                    "Open on something concrete the viewer can picture",
                    "Make the viewer feel the question, curiosity, or stakes",
                ],
                cliffhanger_template=None,
                psychological_beat="curiosity",
                min_numbers=0,
                word_pct=0.25,
            ),
            ActDefinition(
                act_number=2,
                name="BUILD",
                purpose="Deepen understanding step by step toward the payoff",
                structure=[
                    "Develop the subject through concrete, specific beats",
                    "Each beat shifts the viewer's understanding or feeling",
                ],
                cliffhanger_template=None,
                psychological_beat="understanding",
                min_numbers=0,
                word_pct=0.50,
            ),
            ActDefinition(
                act_number=3,
                name="PAYOFF",
                purpose="Land the answer the opening promised; resolve the arc",
                structure=[
                    "Deliver the satisfying answer or resolution",
                    "Leave the viewer with one thing they take away",
                ],
                cliffhanger_template=None,
                psychological_beat="resolution",
                min_numbers=0,
                word_pct=0.25,
            ),
        ],
    },

    # === Number Density — none required ===
    number_density=NumberDensityConfig(
        minimum_total=0,
        per_act={},
        definition="any specific, verifiable detail",
        anti_words=[],
    ),

    # === Retention Engineering — universal, no forced cliffhangers ===
    retention=RetentionConfig(
        cliffhanger_frequency="as_appropriate",
        micro_revelation_cadence_seconds=90,
        explicit_forward_sell=False,
        forward_sell_template="",
    ),

    # === Language Rules — only universal kill phrases ===
    language=LanguageConfig(
        use_phrases=[],
        kill_phrases=[
            "In this video, we'll explore",
            "Let's dive into",
            "It's important to understand",
            "In conclusion",
            "Like and subscribe",
            "What do you think? Leave a comment",
        ],
        framework_naming_rules={},
    ),

    # === Framework Integration — none required ===
    framework_integration=FrameworkIntegrationConfig(
        available_frameworks=[],
        selection_method="per_video",
        integration_style="invisible_scaffolding",
        max_runtime_pct=0.0,
    ),

    # === Incentive Chain — not required ===
    incentive_chain=IncentiveChainConfig(
        required=False,
        must_complete_before_script=False,
        chain_template="",
        min_links=0,
        must_end_at_viewer=False,
        stored_in="",
    ),

    # === Teardown — disabled ===
    teardown=TeardownConfig(
        enabled=False,
        trigger="",
        template=[],
    ),

    # === Script Validation Rules — every PD gate OFF ===
    validation=ValidationConfig(
        min_words=150,   # low floor so short ESL / story scripts pass
        max_words=6000,
        min_acts=1,
        max_acts=8,
        number_density_check=False,
        kill_phrase_check=True,        # universal — keep
        cliffhanger_check=False,       # don't force cliffhangers on every niche
        incentive_chain_presence=False,
        framework_max_pct_check=False,
        personal_stakes_presence=False,
        actionable_ending_check=False,
        retry_on_fail=True,
        max_retries=1,
        requires_research_brief=False,  # simple premise is enough — no doc gate
    ),

    # === Template Metadata (for StoryEngine) ===
    template_metadata=TemplateMetadata(
        display_name="Neutral — Universal Craft",
        category="general",
        tags=["default", "universal", "neutral"],
        description=(
            "The default. Strong universal scriptcraft with no built-in "
            "identity — the channel's voice, audience, and recurring lens are "
            "injected per channel. Use this for any niche: stories, ESL, "
            "cooking, explainers, and more."
        ),
        best_for=["any channel", "stories", "ESL", "cooking", "explainers"],
        example_titles=[],
    ),

    # === Emotional Arc — left empty; the generator's neutral default applies ===
    emotional_arc={},

    # === Text blocks — intentionally EMPTY ===
    # The generator falls back to its own identity-neutral defaults for each of
    # these. Leaving them empty keeps the neutral profile free of any identity.
    act_specific_rules="",
    micro_payoff_architecture="",
    framework_selection_rules="",
    framework_revelation_engine="",
    strict_grounding_rule="",
)
