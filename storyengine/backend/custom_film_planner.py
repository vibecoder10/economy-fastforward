"""Constrained Custom Film planning and deterministic compilation.

The text model proposes only section intent plus three public component sources:
the structural production shape, writing profile, and visual profile. It never
receives authority to emit provider IDs, runtime knobs, section IDs, prices, or
generation actions. The compiler resolves every value from the validated M2-1
capability manifest and returns a separate user-safe explanation.

Planning is intentionally side-effect free. Persistence, pricing, approval, and
generation dispatch belong to later milestones.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator

from custom_film_contract import (
    CapabilityManifest,
    CustomFilmContractError,
    RECIPE_ROLES,
    canonical_json,
    find_recipe_duplicate,
    load_capability_manifest,
    normalize_plan,
    normalize_recipe,
    plan_hash,
    recipe_signature,
)
from production_styles import PUBLIC_PRODUCTION_STYLE_IDS, REQUIRED_KNOB_KEYS


PUBLIC_SOURCE = Literal[
    "bilingual_character_animation",
    "simple_language_animation",
    "photo_documentary",
    "animated_investigative_documentary",
]

CUSTOM_FILM_SECTION_NAMESPACE = UUID("7c75538d-0114-4a43-a745-7587e45a6b91")
MAX_PLANNER_SECTIONS = 12
ROLE_PURPOSES = {
    "full_film": "Carry one coherent approach through the whole film about {focus}",
    "opening": "Set up {focus} and give the audience a reason to keep watching",
    "context": "Give the background needed to understand {focus}",
    "explanation": "Make {focus} clear and easy to follow",
    "evidence": "Present the strongest concrete evidence about {focus}",
    "contrast": "Show the key difference or tension within {focus}",
    "case_study": "Ground {focus} in one concrete example",
    "resolution": "Bring the evidence about {focus} into one clear conclusion",
    "closing": "Leave the audience with the main takeaway about {focus}",
}
_FOCUS_BOILERPLATE_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "animated",
        "animation",
        "about",
        "assemble",
        "chapter",
        "chapters",
        "character",
        "characters",
        "closing",
        "create",
        "creator",
        "custom",
        "documentary",
        "ending",
        "explanation",
        "film",
        "first",
        "fourth",
        "full",
        "generation",
        "investigative",
        "language",
        "make",
        "movie",
        "opening",
        "part",
        "parts",
        "photo",
        "plan",
        "planning",
        "production",
        "profile",
        "profiles",
        "request",
        "camera",
        "dubbing",
        "second",
        "section",
        "sections",
        "segmentation",
        "style",
        "styles",
        "the",
        "third",
        "treatment",
        "video",
        "visual",
    }
)
_INTERNAL_FOCUS_TERMS = frozenset(
    set(PUBLIC_PRODUCTION_STYLE_IDS)
    | {key for key in REQUIRED_KNOB_KEYS if "_" in key}
    | {
        "api_key",
        "compatibility_version",
        "duration_weight",
        "estimated_media",
        "model_id",
        "plan_hash",
        "planner_proposal",
        "provider_id",
        "recipe_signature",
        "section_id",
        "structure_source",
        "writing_source",
        "visual_source",
    }
)
_QUOTE_OR_PRICE_FOCUS_PATTERN = re.compile(
    r"(?:\$\s*\d|\b(?:cents?|dollars?|estimate(?:d|s)?|price|prices|pricing|"
    r"quote|quotes|quoted|usd)\b|\bcost\s+(?:estimate|quote|breakdown)\b)",
    flags=re.IGNORECASE,
)
_OPERATIONAL_FOCUS_PATTERN = re.compile(
    r"\b(?:using|via|through|powered\s+by)"
    r"(?:\s+\w+){0,6}\s+(?:api|clips?|images?|media|models?|photos?|"
    r"pictures?|providers?|rendering|renderers?|generation|generators?|"
    r"videos?)\b|"
    r"\b(?:animate|animated|generate|generated|render|rendered)"
    r"(?:\s+\w+){0,6}\s+(?:by|with)\b",
    flags=re.IGNORECASE,
)
_KNOWN_PROVIDER_OR_MODEL_TERMS = frozenset(
    {
        "anthropic",
        "claude",
        "gemini",
        "google veo",
        "grok",
        "kie",
        "kie.ai",
        "openai",
        "runway",
        "sora",
        "storyengine",
        "veo",
        "veo3",
    }
)
_FUSED_PROVIDER_CUES = (
    "ai",
    "ml",
    "forge",
    "lab",
    "labs",
    "gen",
    "studio",
    "media",
    "video",
    "image",
    "vision",
    "motion",
    "cloud",
    "tech",
)


def _has_terminal_provider_or_model_cue(focus: str) -> bool:
    """Recognize provider-like tails without guessing that all proper nouns are tools."""
    match = re.search(
        r"\b(?:using|via|through|powered\s+by)\s+(?:the\s+)?(.+?)\s*$",
        focus,
        flags=re.IGNORECASE,
    )
    if not match:
        return False
    tail = re.sub(r"\s+", " ", match.group(1).strip()).casefold()
    if tail in _KNOWN_PROVIDER_OR_MODEL_TERMS:
        return True
    words = re.findall(r"[a-z0-9._-]+", tail)
    if len(words) > 3:
        return False
    terminal_word = words[-1]
    if re.search(r"[a-z0-9-]+\.[a-z0-9-]+", terminal_word):
        return True
    if re.search(r"(?:[a-z]\d|\d[a-z])", terminal_word):
        return True
    return any(
        len(terminal_word) > len(cue) and terminal_word.endswith(cue)
        for cue in _FUSED_PROVIDER_CUES
    )

NO_KEY_MESSAGE = (
    "I can assemble that Custom Film plan, but I need one of your own text-model "
    "keys first. Add your Kie.ai or Anthropic key under Profile → API Keys, then "
    "send the request again. Nothing has been generated or charged."
)
PLANNER_FAILURE_MESSAGE = (
    "I couldn't assemble a safe Custom Film plan from that response. Please try "
    "the request again or describe the sections a little more plainly. Nothing "
    "was generated or charged."
)
SECTION_COUNT_CHANGE_MESSAGE = (
    "I kept your current unapproved plan unchanged. This planning pass can revise "
    "what each existing section does and how it feels, but adding, removing, or "
    "reordering sections arrives with the section-aware estimate and edit binding "
    "in the next Custom Film step. Nothing was generated or charged."
)


class CustomFilmPlannerError(ValueError):
    """A creator-safe, pre-generation planner failure."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PlannerSection(_StrictModel):
    """The complete and deliberately small authority granted to the model."""

    role: str
    focus: str = Field(min_length=1, max_length=120)
    duration_weight: Decimal = Field(gt=0, le=1_000_000)
    structure_source: PUBLIC_SOURCE
    writing_source: PUBLIC_SOURCE
    visual_source: PUBLIC_SOURCE

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        if value not in RECIPE_ROLES:
            raise ValueError(f"Unknown section role: {value}")
        return value

class PlannerProposal(_StrictModel):
    sections: list[PlannerSection] = Field(min_length=1, max_length=MAX_PLANNER_SECTIONS)


@dataclass(frozen=True)
class CompiledCustomFilm:
    """Both sides of one compile: private execution contract and safe display."""

    internal_plan: dict[str, Any]
    display_plan: dict[str, Any]
    planner_proposal: dict[str, Any]
    normalized_recipe: dict[str, Any]
    plan_hash: str
    recipe_signature: str


@dataclass(frozen=True)
class NoveltyResult:
    is_novel: bool
    duplicate_kind: str | None = None
    duplicate_id: str | None = None


def is_custom_film_intent(message: str) -> bool:
    """Recognize explicit composer asks without stealing ordinary film requests."""
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    if not text:
        return False
    if re.search(
        r"\b(?:what is|what does|define|explain what|how does)\b.{0,40}"
        r"\bcustom[- ]film\b",
        text,
    ):
        return False
    if re.search(
        r"\b(?:do not|don't|dont|never|avoid|stop)\b.{0,40}"
        r"\b(?:make|create|assemble|plan)?\b.{0,20}\bcustom[- ]film\b",
        text,
    ):
        return False
    if re.search(
        r"\b(?:i|we)\s+(?:made|created|analyzed|analysed|reviewed|watched|"
        r"discussed)\b.{0,60}\bcustom[- ]film\b",
        text,
    ):
        return False
    if re.search(
        r"\b(?:i|we)\s+(?:mixed|combined)\b.{0,40}\b(?:last|previous|past)\b"
        r".{0,30}\b(?:film|video)\b",
        text,
    ):
        return False
    if re.search(r"\bcustom[- ]film\b", text):
        return True
    if re.search(r"\bmix(?:ed|ing)?\b.*\b(?:styles?|profiles?|formats?)\b", text):
        return bool(
            re.search(r"\b(?:section(?:s)?|part(?:s)?|chapter(?:s)?|film|video)\b", text)
        )
    if re.search(r"\bcombine\b.*\b(?:styles?|profiles?|formats?)\b", text):
        return bool(re.search(r"\b(?:section by section|sections?|film|video)\b", text))
    # Natural composer requests often describe the transitions instead of
    # naming the feature. Require both explicit section/order language and at
    # least two distinct production-treatment families so ordinary narrative
    # "start with a mystery, then reveal the answer" prompts stay in Producer.
    has_section_order = bool(
        re.search(r"\b(?:sections?|chapters?|parts?)\b", text)
        or (
            re.search(r"\b(?:opening|beginning)\b", text)
            and re.search(r"\b(?:ending|closing|finish)\b", text)
        )
        or (
            re.search(r"\b(?:open|start|begin)\b", text)
            and re.search(r"\b(?:then|switch|transition|finish|end)\b", text)
        )
    )
    if has_section_order:
        treatment_patterns = (
            r"\b(?:still(?:s)?|still photographs?|photo[- ]documentary|static photos?)\b",
            r"\b(?:animated|animation|investigative animation|animated investigation)\b",
            r"\b(?:bilingual|two[- ]language|character dialogue|dialogue|characters?)\b",
            r"\b(?:simple[- ]language|beginner[- ]friendly|language learners?)\b",
        )
        treatment_count = sum(
            bool(re.search(pattern, text)) for pattern in treatment_patterns
        )
        if treatment_count >= 2:
            return True
    return False


def is_custom_film_exit_intent(message: str) -> bool:
    """Recognize an explicit request to leave Custom Film for ordinary Producer."""
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    if not text:
        return False
    if re.fullmatch(
        r"(?:please\s+)?(?:cancel|stop|exit|never mind|nevermind)(?:\s+this)?[.!]?",
        text,
    ):
        return True
    if re.search(r"\b(?:go back|return)\s+to\s+(?:the\s+)?producer\b", text):
        return True
    if re.search(r"\bmake\s+(?:a\s+)?(?:normal|regular)\s+(?:film|video)\b", text):
        return True
    if re.search(
        r"\b(?:cancel|exit|leave|stop|discard|scrap|forget)\b.{0,35}"
        r"\bcustom[- ]film\b",
        text,
    ):
        return True
    if re.search(
        r"\b(?:do not|don't|dont|no longer)\b.{0,20}"
        r"\b(?:make|use|continue|want)\b.{0,25}\bcustom[- ]film\b",
        text,
    ):
        return True
    if re.search(
        r"\b(?:instead|switch|change)\b.{0,35}\b(?:normal|regular|single[- ]style|"
        r"photo[- ]documentary|character animation|investigative documentary)\b",
        text,
    ):
        return True
    return False


def is_custom_film_ordinary_video_request(message: str) -> bool:
    """True when an exit turn also asks ordinary Producer to plan a video."""
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    return bool(
        re.search(
            r"\b(?:make|create|plan|switch to|change to)\b.{0,30}"
            r"\b(?:normal|regular|single[- ]style|photo[- ]documentary|"
            r"character animation|investigative documentary|video|film)\b",
            text,
        )
    )


def is_section_count_change_request(message: str) -> bool:
    """M2-2 revises stable slots; M2-3 will bind structural edits to estimates."""
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    return bool(
        re.search(
            r"\b(?:add|insert|append|remove|delete|drop|split|merge|reorder|"
            r"move)\b.{0,30}\b(?:sections?|chapters?|parts?)\b",
            text,
        )
        or re.search(
            r"\b(?:more|fewer)\s+(?:sections?|chapters?|parts?)\b",
            text,
        )
    )


def planner_json_schema() -> dict[str, Any]:
    """Expose the exact fake/real-client response schema used by tests and prompt."""
    return PlannerProposal.model_json_schema()


def _extract_json_object(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, str) or not raw.strip():
        raise CustomFilmPlannerError(PLANNER_FAILURE_MESSAGE)
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise CustomFilmPlannerError(PLANNER_FAILURE_MESSAGE)
    try:
        parsed = json.loads(text[start : end + 1])
    except (json.JSONDecodeError, TypeError) as exc:
        raise CustomFilmPlannerError(PLANNER_FAILURE_MESSAGE) from exc
    if not isinstance(parsed, dict):
        raise CustomFilmPlannerError(PLANNER_FAILURE_MESSAGE)
    return parsed


def _planner_prompt(
    user_request: str,
    manifest: CapabilityManifest,
    prior_proposal: PlannerProposal | None = None,
) -> str:
    sources = [
        {
            "id": style_id,
            "label": str(profile.get("label") or style_id),
            "description": str(profile.get("description") or ""),
        }
        for style_id, profile in sorted(manifest.profiles.items())
    ]
    prior_context = (
        "\n\nCURRENT CONSTRAINED PLAN TO REVISE:\n"
        f"{canonical_json(prior_proposal.model_dump(mode='json'))}"
        "\nReturn the full revised plan. Preserve its section count and order exactly, "
        "and change only what the follow-up requests. Section-count and reorder edits "
        "are handled outside this planning pass."
        if prior_proposal is not None
        else ""
    )
    return (
        "Assemble a section-by-section Custom Film proposal for the creator's request. "
        "Return exactly one JSON object matching the supplied schema.\n\n"
        "You may choose only the listed public source IDs. `structure_source` chooses "
        "the complete safe production shape; `writing_source` chooses its writing "
        "approach; `visual_source` chooses its visual treatment. Do not return knobs, "
        "provider names or IDs, model names, prices, section IDs, purpose prose, "
        "approval, or any generation instruction. For each `focus`, copy a concise "
        "exact content-topic phrase from the creator request, not Custom Film or "
        "production-treatment boilerplate and not an internal field/profile name; "
        "on a revision it may instead exactly reuse that section's prior focus. "
        "Never paraphrase or invent focus text. "
        "StoryEngine derives creator-facing purpose text from role + validated focus. "
        "Use two to six purposeful sections unless the creator clearly asks for a "
        "different count.\n\n"
        f"PUBLIC SOURCES:\n{canonical_json(sources)}\n\n"
        f"JSON SCHEMA:\n{canonical_json(planner_json_schema())}\n\n"
        f"CREATOR REQUEST:\n{user_request.strip()}"
        f"{prior_context}"
    )


def _section_id(
    user_request: str,
    index: int,
) -> str:
    # IDs are tied to the request and durable ordered slot, not mutable purpose
    # prose or component choices. Editing one section therefore does not remap
    # every section before M2-4 assigns script scenes against these IDs.
    seed = canonical_json(
        {
            "request": re.sub(r"\s+", " ", user_request.strip()),
            "section_index": index,
        }
    )
    return str(uuid5(CUSTOM_FILM_SECTION_NAMESPACE, seed))


def _validated_prior_section_ids(
    prior_section_ids: list[str] | None,
    section_count: int,
) -> list[str] | None:
    if prior_section_ids is None:
        return None
    if len(prior_section_ids) != section_count:
        raise CustomFilmPlannerError(PLANNER_FAILURE_MESSAGE)
    try:
        normalized = [str(UUID(str(value))) for value in prior_section_ids]
    except (TypeError, ValueError, AttributeError) as exc:
        raise CustomFilmPlannerError(PLANNER_FAILURE_MESSAGE) from exc
    if len(normalized) != len(set(normalized)):
        raise CustomFilmPlannerError(PLANNER_FAILURE_MESSAGE)
    return normalized


def _normalized_grounded_focus(
    focus: str,
    user_request: str,
    prior_focus: str | None,
) -> str:
    normalized = re.sub(r"\s+", " ", focus.strip())
    if not normalized or re.search(r"[\n\r<>{}\[\]`]", normalized):
        raise CustomFilmPlannerError(PLANNER_FAILURE_MESSAGE)
    folded = normalized.casefold()
    for internal_term in _INTERNAL_FOCUS_TERMS:
        aliases = {internal_term.casefold(), internal_term.replace("_", " ").casefold()}
        if any(
            re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", folded)
            for alias in aliases
        ):
            raise CustomFilmPlannerError(PLANNER_FAILURE_MESSAGE)
    if _QUOTE_OR_PRICE_FOCUS_PATTERN.search(normalized):
        raise CustomFilmPlannerError(PLANNER_FAILURE_MESSAGE)
    if _OPERATIONAL_FOCUS_PATTERN.search(normalized):
        raise CustomFilmPlannerError(PLANNER_FAILURE_MESSAGE)
    if _has_terminal_provider_or_model_cue(normalized):
        raise CustomFilmPlannerError(PLANNER_FAILURE_MESSAGE)
    content_words = re.findall(r"[a-z0-9]+", folded)
    if not any(word not in _FOCUS_BOILERPLATE_WORDS for word in content_words):
        raise CustomFilmPlannerError(PLANNER_FAILURE_MESSAGE)
    if prior_focus is not None and normalized.casefold() == prior_focus.casefold():
        return prior_focus
    phrase_pattern = re.sub(r"\\ ", r"\\s+", re.escape(normalized))
    match = re.search(
        rf"(?<!\w){phrase_pattern}(?!\w)",
        user_request,
        flags=re.IGNORECASE,
    )
    if not match:
        raise CustomFilmPlannerError(PLANNER_FAILURE_MESSAGE)
    prefix = user_request[max(0, match.start() - 100) : match.start()]
    suffix = user_request[match.end() : match.end() + 50]
    if re.search(
        r"\b(?:using|via|through|powered\s+by)\s+(?:the\s+)?$|"
        r"\b(?:animate|animated|generate|generated|render|rendered)"
        r"(?:\s+\w+){0,6}\s+(?:by|with)\s+(?:the\s+)?$",
        prefix,
        flags=re.IGNORECASE,
    ):
        raise CustomFilmPlannerError(PLANNER_FAILURE_MESSAGE)
    if re.match(
        r"\s+(?:api|images?|model|provider|render(?:er)?|video\s+model)\b",
        suffix,
        flags=re.IGNORECASE,
    ):
        raise CustomFilmPlannerError(PLANNER_FAILURE_MESSAGE)
    return re.sub(r"\s+", " ", match.group(0).strip())


def _validated_focuses(
    proposal: PlannerProposal,
    user_request: str,
    prior_focuses: list[str] | None,
) -> list[str]:
    if prior_focuses is not None and len(prior_focuses) != len(proposal.sections):
        raise CustomFilmPlannerError(PLANNER_FAILURE_MESSAGE)
    return [
        _normalized_grounded_focus(
            section.focus,
            user_request,
            prior_focuses[index] if prior_focuses is not None else None,
        )
        for index, section in enumerate(proposal.sections)
    ]


def _compile_knobs(
    section: PlannerSection,
    manifest: CapabilityManifest,
) -> dict[str, Any]:
    """Resolve all executable values from public snapshots, never planner prose."""
    knobs = copy.deepcopy(manifest.profiles[section.structure_source]["knobs"])
    knobs["script_profile"] = copy.deepcopy(
        manifest.profiles[section.writing_source]["knobs"]["script_profile"]
    )
    knobs["visual_profile"] = copy.deepcopy(
        manifest.profiles[section.visual_source]["knobs"]["visual_profile"]
    )
    return knobs


def _duration_seconds(
    section: PlannerSection,
    proposal: PlannerProposal,
    total_seconds: int | None,
) -> Decimal:
    if total_seconds is None:
        return Decimal(0)
    total_weight = sum(
        (candidate.duration_weight for candidate in proposal.sections),
        Decimal(0),
    )
    value = Decimal(total_seconds) * section.duration_weight / total_weight
    return value.quantize(Decimal("0.001"))


def _expected_media(knobs: dict[str, Any]) -> str:
    render_mode = knobs["render_mode"]
    language_mode = knobs["language"]["mode"]
    density_mode = knobs["image_density"]["mode"]
    if render_mode == "static_docu":
        return (
            "Grounded still photographs, three complementary views per item, "
            "gentle movement, captions, and one continuous narration track."
        )
    if density_mode == "dialogue_shape" and language_mode == "bilingual":
        return (
            "Performed bilingual character scenes, matching animated coverage, "
            "captions, and a translated voice treatment."
        )
    if density_mode == "dialogue_shape":
        return (
            "Clear single-language character scenes with matching animated "
            "coverage and captions."
        )
    return (
        "Animated investigative coverage built around concrete visual cues, "
        "with captions and continuous narration."
    )


def _feel(knobs: dict[str, Any]) -> str:
    writing = (
        "tightly argued investigative writing"
        if knobs["script_profile"] == "power_doctrine_v2"
        else "direct, accessible writing"
    )
    look = (
        "a cinematic illustrated look"
        if knobs["visual_profile"] == "cinematic_illustration"
        else "a clean, adaptable look"
    )
    return f"{writing.capitalize()} with {look}."


def _role_label(role: str) -> str:
    return role.replace("_", " ").capitalize()


def compile_planner_proposal(
    user_request: str,
    raw_proposal: Any,
    manifest: CapabilityManifest,
    *,
    total_duration_seconds: int | None = None,
    prior_section_ids: list[str] | None = None,
    prior_focuses: list[str] | None = None,
) -> CompiledCustomFilm:
    """Compile untrusted proposal JSON into one deterministic validated contract."""
    if total_duration_seconds is not None and (
        total_duration_seconds < 5 or total_duration_seconds > 24 * 60 * 60
    ):
        raise CustomFilmPlannerError(PLANNER_FAILURE_MESSAGE)
    try:
        proposal = PlannerProposal.model_validate(raw_proposal)
        reusable_ids = _validated_prior_section_ids(
            prior_section_ids,
            len(proposal.sections),
        )
        grounded_focuses = _validated_focuses(
            proposal,
            user_request,
            prior_focuses,
        )
        normalized_proposal = proposal.model_dump(mode="json")
        for index, focus in enumerate(grounded_focuses):
            normalized_proposal["sections"][index]["focus"] = focus
        raw_sections: list[dict[str, Any]] = []
        recipe_sections: list[dict[str, Any]] = []
        for index, section in enumerate(proposal.sections):
            knobs = _compile_knobs(section, manifest)
            purpose = ROLE_PURPOSES[section.role].format(
                focus=grounded_focuses[index]
            )
            duration = _duration_seconds(
                section,
                proposal,
                total_duration_seconds,
            )
            raw_sections.append(
                {
                    "section_id": (
                        reusable_ids[index]
                        if reusable_ids is not None
                        else _section_id(user_request, index)
                    ),
                    "role": section.role,
                    "purpose": purpose,
                    "duration_weight": section.duration_weight,
                    "knobs": knobs,
                    # M2-2 records duration only. Section-aware counts/prices are
                    # deliberately deferred to M2-3's shared estimator.
                    "estimated_media": {
                        "still_images": 0,
                        "animation_clips": 0,
                        "voice_tracks": 0,
                        "duration_seconds": duration,
                    },
                }
            )
            recipe_sections.append(
                {
                    "role": section.role,
                    "duration_weight": section.duration_weight,
                    "knobs": knobs,
                }
            )
        normalized = normalize_plan(
            {
                "compatibility_version": manifest.version,
                "sections": raw_sections,
            },
            manifest,
        )
        recipe = normalize_recipe(
            {
                "compatibility_version": manifest.version,
                "sections": recipe_sections,
            },
            manifest,
        )
    except (CustomFilmContractError, ValueError, TypeError, KeyError) as exc:
        raise CustomFilmPlannerError(PLANNER_FAILURE_MESSAGE) from exc

    display_sections: list[dict[str, Any]] = []
    for section in normalized["sections"]:
        display_sections.append(
            {
                "section_id": section["section_id"],
                "order": section["order_index"] + 1,
                "role": _role_label(section["role"]),
                "purpose": section["purpose"],
                "share_percent": round(section["duration_units"] / 10_000, 2),
                "feel": _feel(section["knobs"]),
                "expected_media": _expected_media(section["knobs"]),
                "why": f"This section is assembled to {section['purpose'].rstrip('.').lower()}.",
            }
        )
    display = {
        "kind": "custom_film",
        "summary": (
            f"I assembled {len(display_sections)} ordered sections from the proven "
            "production capabilities already available in StoryEngine."
        ),
        "sections": display_sections,
        "byok_notice": (
            "Any later production would use only your connected AI accounts. "
            "This plan includes no price or approval yet."
        ),
        "status": (
            "Planning only — generation has not started. You will review an itemized "
            "estimate and explicitly approve the exact current plan before any work begins."
        ),
    }
    return CompiledCustomFilm(
        internal_plan=normalized,
        display_plan=display,
        planner_proposal=normalized_proposal,
        normalized_recipe=recipe,
        plan_hash=plan_hash(normalized),
        recipe_signature=recipe_signature(recipe),
    )


async def plan_custom_film(
    user_request: str,
    manifest: CapabilityManifest,
    client: Any,
    *,
    total_duration_seconds: int | None = None,
    prior_proposal: dict[str, Any] | None = None,
    prior_section_ids: list[str] | None = None,
) -> CompiledCustomFilm:
    """Run one tenant-owned planning inference, then compile it fail-closed."""
    if client is None:
        raise CustomFilmPlannerError(NO_KEY_MESSAGE)
    try:
        normalized_prior = (
            PlannerProposal.model_validate(prior_proposal)
            if prior_proposal is not None
            else None
        )
        raw = await client.generate(
            prompt=_planner_prompt(user_request, manifest, normalized_prior),
            system_prompt=(
                "You are a constrained film-structure planner. Follow the JSON schema "
                "exactly and never propose providers, prices, runtime knobs, or actions."
            ),
            max_tokens=2_000,
            temperature=0,
        )
        parsed = _extract_json_object(raw)
        return compile_planner_proposal(
            user_request,
            parsed,
            manifest,
            total_duration_seconds=total_duration_seconds,
            prior_section_ids=prior_section_ids,
            prior_focuses=(
                [section.focus for section in normalized_prior.sections]
                if normalized_prior is not None
                else None
            ),
        )
    except CustomFilmPlannerError:
        raise
    except Exception as exc:  # noqa: BLE001 - provider details must not leak to chat
        raise CustomFilmPlannerError(PLANNER_FAILURE_MESSAGE) from exc


async def classify_plan_novelty(
    tenant_id: str,
    compiled: CompiledCustomFilm,
    manifest: CapabilityManifest,
) -> NoveltyResult:
    """Classify only; M2-2 never saves a recipe or presents a save action."""
    duplicate = await find_recipe_duplicate(
        tenant_id,
        compiled.normalized_recipe,
        manifest,
    )
    if duplicate:
        return NoveltyResult(
            is_novel=False,
            duplicate_kind=duplicate[0],
            duplicate_id=duplicate[1],
        )
    return NoveltyResult(is_novel=True)
