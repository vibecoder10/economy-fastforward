"""Script Profile schema definition.

A script profile is a self-contained configuration that captures every
aspect of a channel's editorial voice: act structure, tone, audience,
structural laws, number density, retention engineering, language rules,
framework integration, and validation thresholds.

Swapping the entire editorial approach = changing one profile reference.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ActDefinition:
    """Definition of a single act within the script structure."""
    act_number: int = 1
    name: str = ""
    purpose: str = ""
    structure: list[str] = field(default_factory=list)
    cliffhanger_template: Optional[str] = None
    psychological_beat: str = ""
    min_numbers: int = 0
    word_pct: float = 0.0


@dataclass
class VoiceConfig:
    """Voice and audience definition."""
    identity: str = ""
    tone: str = ""
    audience: str = ""
    audience_values: list[str] = field(default_factory=list)
    audience_repelled_by: list[str] = field(default_factory=list)
    narrator_posture: str = "revealing"  # "revealing" | "explaining" | "teaching"


@dataclass
class NumberDensityConfig:
    """Number density requirements for the script."""
    minimum_total: int = 19
    per_act: dict[int, int] = field(default_factory=dict)
    definition: str = "dollar amount, percentage, date, count, ratio, or named statistic"
    anti_words: list[str] = field(default_factory=list)


@dataclass
class RetentionConfig:
    """Retention engineering rules."""
    cliffhanger_frequency: str = "every_act_transition"
    micro_revelation_cadence_seconds: int = 90
    explicit_forward_sell: bool = True
    forward_sell_template: str = ""


@dataclass
class LanguageConfig:
    """Language rules — approved phrases, kill phrases, framework naming."""
    use_phrases: list[str] = field(default_factory=list)
    kill_phrases: list[str] = field(default_factory=list)
    framework_naming_rules: dict[str, Any] = field(default_factory=dict)


@dataclass
class FrameworkIntegrationConfig:
    """Framework integration rules."""
    available_frameworks: list[dict[str, str]] = field(default_factory=list)
    selection_method: str = "per_video"
    integration_style: str = "invisible_scaffolding"
    max_runtime_pct: float = 0.15


@dataclass
class IncentiveChainConfig:
    """Incentive chain requirements."""
    required: bool = True
    must_complete_before_script: bool = True
    chain_template: str = ""
    min_links: int = 4
    must_end_at_viewer: bool = True
    stored_in: str = "Research Payload"


@dataclass
class TeardownConfig:
    """Multi-rationale teardown structure."""
    enabled: bool = True
    trigger: str = "multiple_official_rationales"
    template: list[str] = field(default_factory=list)


@dataclass
class ValidationConfig:
    """Script validation rules."""
    min_words: int = 2200
    max_words: int = 3200
    min_acts: int = 3
    max_acts: int = 8
    number_density_check: bool = True
    kill_phrase_check: bool = True
    cliffhanger_check: bool = True
    incentive_chain_presence: bool = True
    framework_max_pct_check: bool = True
    personal_stakes_presence: bool = True
    actionable_ending_check: bool = True
    retry_on_fail: bool = True
    max_retries: int = 2
    # When True, the LLM brief-readiness judge (validate_brief) must approve the
    # brief before script generation — it checks documentary-grade depth
    # (fact density, framework depth, supporting evidence, etc.). This is the
    # Power Doctrine behavior. When False (the neutral default), a simple
    # premise (ESL, cooking, a story) proceeds straight to generation without
    # being rejected for lacking research-brief depth.
    requires_research_brief: bool = True


@dataclass
class TemplateMetadata:
    """StoryEngine template metadata — what customers see during onboarding."""
    display_name: str = ""
    category: str = ""
    tags: list[str] = field(default_factory=list)
    description: str = ""
    best_for: list[str] = field(default_factory=list)
    example_titles: list[str] = field(default_factory=list)


@dataclass
class ScriptProfile:
    """Complete editorial voice definition. Self-contained and pluggable.

    Every aspect of how scripts are written — tone, structure, act
    definitions, validation rules, language constraints — is captured
    here. The pipeline reads the active profile at runtime.
    """

    # Identity
    profile_id: str = ""
    profile_name: str = ""
    version: str = "1.0"
    description: str = ""
    channel: str = "economy_fastforward"

    # Sections
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    structural_laws: list[str] = field(default_factory=list)
    content_ratio: dict[str, dict[str, float]] = field(default_factory=dict)
    act_structure: dict[str, Any] = field(default_factory=dict)
    number_density: NumberDensityConfig = field(default_factory=NumberDensityConfig)
    retention: RetentionConfig = field(default_factory=RetentionConfig)
    language: LanguageConfig = field(default_factory=LanguageConfig)
    framework_integration: FrameworkIntegrationConfig = field(
        default_factory=FrameworkIntegrationConfig
    )
    incentive_chain: IncentiveChainConfig = field(
        default_factory=IncentiveChainConfig
    )
    teardown: TeardownConfig = field(default_factory=TeardownConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    template_metadata: TemplateMetadata = field(default_factory=TemplateMetadata)

    # System prompt template with {placeholders} for runtime assembly.
    # If empty, the default assembly logic in build_script_system_prompt() is used.
    system_prompt_template: str = ""

    # Emotional arc per act — maps act number to emotional description
    emotional_arc: dict[int, str] = field(default_factory=dict)

    # Act-specific rules text block (appended to prompt)
    act_specific_rules: str = ""

    # Micro-payoff architecture text block
    micro_payoff_architecture: str = ""

    # Framework selection rules text block
    framework_selection_rules: str = ""

    # Framework revelation engine text block
    framework_revelation_engine: str = ""

    # Strict grounding rule text block
    strict_grounding_rule: str = ""


def build_script_system_prompt(profile: ScriptProfile) -> str:
    """Assemble the script system prompt from profile sections.

    This builds the voice/tone/structure preamble that precedes the
    research brief in the final prompt. It replaces the hardcoded
    content in ``prompts/script.txt`` when a profile is active.
    """
    acts = profile.act_structure.get("acts", [])

    # Voice block
    voice = profile.voice
    voice_block = f"""You are {voice.identity}.

=== YOUR VOICE — NON-NEGOTIABLE ===

- {voice.tone}
- Investigative, not academic. You found something. You're showing your work.

=== YOUR AUDIENCE ===

{voice.audience}
They value: {', '.join(voice.audience_values)}.
They will leave immediately if they feel: {', '.join(voice.audience_repelled_by)}."""

    # Structural laws
    laws_lines = []
    for i, law in enumerate(profile.structural_laws):
        laws_lines.append(f"{i + 1}. {law}")
    laws_block = "=== STRUCTURAL LAWS — NON-NEGOTIABLE ===\n\n" + "\n\n".join(laws_lines)

    # Content ratio
    ratio_lines = []
    for k, v in profile.content_ratio.items():
        label = k.replace("_", " ").title()
        ratio_lines.append(f"- {label}: {v['min']*100:.0f}-{v['max']*100:.0f}% of runtime")
    ratio_block = "=== STRUCTURAL RATIO (NON-NEGOTIABLE) ===\n\n" + "\n".join(ratio_lines)

    # Number density
    nd = profile.number_density
    per_act_lines = []
    for act_num in sorted(nd.per_act.keys()):
        per_act_lines.append(f"- Act {act_num}: {nd.per_act[act_num]}+ numbers")
    numbers_block = (
        "=== NUMBER DENSITY REQUIREMENTS ===\n\n"
        "Minimum specific, verifiable numbers per act:\n"
        + "\n".join(per_act_lines)
        + f"\nTotal minimum: {nd.minimum_total} specific, verifiable numbers across the full script.\n"
        f'"Specific number" means: {nd.definition}.\n'
        f'"' + '", "'.join(nd.anti_words) + '" are NOT numbers.'
    )

    # Retention engineering
    ret = profile.retention
    retention_block = (
        f"=== RETENTION ENGINEERING ===\n\n"
        f"- Deliver a mini-revelation every {ret.micro_revelation_cadence_seconds} seconds "
        f"— a fact, number, or connection the viewer didn't know\n"
        f"- End each act with an explicit cliffhanger that sells the next section\n"
        f"- Never go more than {ret.micro_revelation_cadence_seconds} seconds "
        f"without giving the viewer something specific"
    )

    # Kill words
    kill_block = (
        '=== WORDS TO NEVER USE ===\n\n'
        + ", ".join(f'"{p}"' for p in profile.language.kill_phrases)
    )

    # Framework integration rules
    fr = profile.language.framework_naming_rules
    framework_block = (
        "=== FRAMEWORK INTEGRATION RULES ===\n\n"
        f"1. The framework is NEVER named before Act {fr.get('first_mention_act', 4)}.\n"
        f"2. Maximum {fr.get('max_direct_references', 2)} direct references to the "
        f"framework by name in the entire script.\n"
        f"3. Introduced as: \"{fr.get('intro_template', '')}\""
    )

    # Act structure block
    act_lines = []
    for act in acts:
        if isinstance(act, ActDefinition):
            a = act
        else:
            a = ActDefinition(**act)

        act_header = f"[ACT {a.act_number} — {a.name}]"
        act_lines.append(f"{act_header}")
        act_lines.append(f"Purpose: {a.purpose}")
        act_lines.append(f"Min numbers: {a.min_numbers}")
        act_lines.append(f"Word allocation: {a.word_pct*100:.0f}% of total")
        for s in a.structure:
            act_lines.append(f"- {s}")
        if a.cliffhanger_template:
            act_lines.append(f"CLIFFHANGER: {a.cliffhanger_template}")
        act_lines.append("")

    acts_block = "=== ACT STRUCTURE ===\n\n" + "\n".join(act_lines)

    # Emotional arc
    if profile.emotional_arc:
        arc_lines = []
        for act_num in sorted(profile.emotional_arc.keys()):
            arc_lines.append(f"- Act {act_num}: {profile.emotional_arc[act_num]}")
        arc_block = "=== EMOTIONAL ARC ===\n\n" + "\n".join(arc_lines)
    else:
        arc_block = ""

    # Assemble
    sections = [
        voice_block,
        laws_block,
        ratio_block,
        numbers_block,
        retention_block,
        kill_block,
        framework_block,
        acts_block,
    ]
    if arc_block:
        sections.append(arc_block)

    return "\n\n".join(sections)
