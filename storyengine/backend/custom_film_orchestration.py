"""Approval-bound deterministic scene orchestration for Custom Film.

The planner owns semantic inputs and public capability choices. This module
owns the strict, provider-opaque translation into executable layered recipes.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from custom_film_contract import CustomFilmContractError, canonical_hash

ORCHESTRATION_CONTRACT_VERSION = "storyengine-layered-orchestration-v1"
DECISION_RULES_VERSION = "storyengine-layered-recipe-rules-v1"
REFERENCE_STORY_IDENTITY = (
    "internet-outage-investigation-witness-recovery-storyengine"
)
REFERENCE_REQUIRED_CONCEPTS = frozenset(
    {"internet", "outage", "evidence", "witness", "network", "storyengine"}
)
CAPABILITY_CATALOG_VERSION = "storyengine-custom-film-capabilities-v1"

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
ALLOWED_MEDIA_KINDS = frozenset({"image", "video", "adaptive"})
ALLOWED_HANDOFFS = frozenset(
    {
        "pulse", "silence", "pulse_to_route", "route",
        "route_to_connector", "connector", "connector_to_waveform",
        "waveform", "waveform_to_key", "key_to_network", "network",
        "network_to_master", "master",
    }
)
ALLOWED_INTENTS = frozenset(
    {
        "cinematic", "outage", "network", "signal", "radio", "title",
        "transition", "map", "evidence", "documents", "timeline",
        "witness", "code", "recovery", "product",
    }
)
MOTION_PRIORITY = (
    ("cinematic", "CinematicOpening"),
    ("product", "StoryEngineReveal"),
    ("network", "NetworkExplainer"),
    ("code", "RadioWaveform"),
    ("radio", "RadioWaveform"),
    ("timeline", "IncidentTimeline"),
    ("documents", "EvidenceBoard"),
    ("evidence", "EvidenceBoard"),
    ("map", "OutageMap"),
    ("witness", "BilingualCaptions"),
)
KNOB_KEYS = (
    "render_mode", "script_profile", "visual_profile", "image_density",
    "animation", "language", "dubbing", "segmentation", "camera",
    "quality_laws", "image_source",
)
CAPABILITY_TO_PRIMITIVE = {
    "motion.signal_pulse": "SignalPulse",
    "motion.outage_map": "OutageMap",
    "motion.evidence_board": "EvidenceBoard",
    "motion.incident_timeline": "IncidentTimeline",
    "motion.radio_waveform": "RadioWaveform",
    "motion.bilingual_captions": "BilingualCaptions",
    "motion.network_explainer": "NetworkExplainer",
    "motion.storyengine_reveal": "StoryEngineReveal",
    "audio.motion_system": "MotionAudioSystem",
}
NON_VISUAL_PRIMITIVES = frozenset(
    {"MotionAudioSystem", "BilingualCaptions"}
)


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CustomFilmContractError(f"{label} must be an object")
    return dict(value)


def _sequence(value: Any, label: str) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise CustomFilmContractError(f"{label} must be a list")
    return list(value)


def _reference_path() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "remotion-video/src/showcase/orchestration-plan-v1.json"
    )


def load_reference_semantic_plan() -> dict[str, Any]:
    try:
        plan = json.loads(_reference_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CustomFilmContractError(
            "Custom Film orchestration reference is unavailable"
        ) from exc
    if set(plan) != {
        "version", "decision_rules_version", "story_identity",
        "required_concepts", "fps", "width", "height", "total_frames",
        "sections", "cues",
    }:
        raise CustomFilmContractError(
            "Custom Film orchestration reference shape changed"
        )
    if (
        plan["version"] != ORCHESTRATION_CONTRACT_VERSION
        or plan["decision_rules_version"] != DECISION_RULES_VERSION
        or plan["story_identity"] != REFERENCE_STORY_IDENTITY
        or set(plan["required_concepts"]) != REFERENCE_REQUIRED_CONCEPTS
        or (plan["fps"], plan["width"], plan["height"], plan["total_frames"])
        != (24, 1920, 1080, 7200)
    ):
        raise CustomFilmContractError(
            "Custom Film orchestration reference identity changed"
        )
    expected_frame = 0
    section_starts: list[int] = []
    running = 0
    for section in _sequence(plan["sections"], "orchestration sections"):
        section_starts.append(running)
        running += int(_mapping(section, "orchestration section")["duration_frames"])
    if running != 7200:
        raise CustomFilmContractError(
            "Custom Film orchestration sections changed"
        )
    for value in _sequence(plan["cues"], "orchestration cues"):
        cue = _mapping(value, "orchestration cue")
        if set(cue) != {"id", "section_index", "from", "to", "signals"}:
            raise CustomFilmContractError(
                "Custom Film orchestration cue shape changed"
            )
        section_index = int(cue["section_index"])
        start, end = int(cue["from"]), int(cue["to"])
        signals = _mapping(cue["signals"], "orchestration signals")
        if (
            start != expected_frame or end < start
            or section_index < 0 or section_index >= len(section_starts)
            or start < section_starts[section_index]
            or end >= section_starts[section_index] + int(plan["sections"][section_index]["duration_frames"])
            or set(signals) != {
                "media_kind", "dialogue", "captions", "intents",
                "energy", "handoff",
            }
            or signals["media_kind"] not in ALLOWED_MEDIA_KINDS
            or signals["handoff"] not in ALLOWED_HANDOFFS
            or not isinstance(signals["dialogue"], bool)
            or not isinstance(signals["captions"], bool)
            or not isinstance(signals["energy"], int)
            or not 0 <= signals["energy"] <= 3
            or not set(signals["intents"]).issubset(ALLOWED_INTENTS)
        ):
            raise CustomFilmContractError(
                "Custom Film orchestration signals changed"
            )
        expected_frame = end + 1
    if expected_frame != 7200:
        raise CustomFilmContractError(
            "Custom Film orchestration cues do not fill the film"
        )
    return copy.deepcopy(plan)


def _focus_from_purpose(role: str, purpose: str) -> str:
    template = ROLE_PURPOSES.get(role)
    if not template:
        raise CustomFilmContractError("Custom Film orchestration role changed")
    prefix, suffix = template.split("{focus}")
    if not purpose.startswith(prefix) or not purpose.endswith(suffix):
        raise CustomFilmContractError(
            "Custom Film purpose is not compiler-owned role/focus text"
        )
    end = len(purpose) - len(suffix) if suffix else len(purpose)
    focus = purpose[len(prefix):end].strip()
    if not focus or template.format(focus=focus) != purpose:
        raise CustomFilmContractError(
            "Custom Film orchestration focus changed"
        )
    return focus


def semantic_input_from_approved_plan(
    internal_plan_value: Any,
    quote_inputs_value: Any,
    planner_proposal_value: Any | None = None,
) -> dict[str, Any]:
    plan = _mapping(internal_plan_value, "approved Custom Film plan")
    quote = _mapping(quote_inputs_value, "approved Custom Film quote")
    plan_sections = _sequence(plan.get("sections"), "approved plan sections")
    quote_sections = _sequence(quote.get("sections"), "approved quote sections")
    quote_by_id = {
        str(_mapping(row, "approved quote section").get("section_id")):
        _mapping(row, "approved quote section")
        for row in quote_sections
    }
    sections: list[dict[str, Any]] = []
    proposal_sections = (
        _sequence(
            _mapping(planner_proposal_value, "planner proposal").get("sections"),
            "planner proposal sections",
        )
        if planner_proposal_value is not None
        else None
    )
    if proposal_sections is not None and len(proposal_sections) != len(plan_sections):
        raise CustomFilmContractError(
            "Custom Film orchestration planner section count changed"
        )
    for index, value in enumerate(plan_sections):
        section = _mapping(value, "approved plan section")
        section_id = str(section.get("section_id") or "")
        row = quote_by_id.get(section_id)
        knobs = _mapping(section.get("knobs"), "approved section knobs")
        estimated = _mapping(
            section.get("estimated_media"), "approved estimated media"
        )
        role = str(section.get("role") or "")
        purpose = str(section.get("purpose") or "")
        focus = _focus_from_purpose(role, purpose)
        if (
            row is None
            or int(section.get("order_index", -1)) != index
            or int(row.get("order_index", -1)) != index
            or int(row.get("duration_seconds", -1))
            != int(float(estimated.get("duration_seconds", -1)))
        ):
            raise CustomFilmContractError(
                "Custom Film orchestration section identity changed"
            )
        semantic_section = {
                "section_id": section_id,
                "order_index": index,
                "role": role,
                "purpose": purpose,
                "focus": focus,
                "duration_seconds": int(row["duration_seconds"]),
                "knobs": {
                    key: copy.deepcopy(knobs[key])
                    for key in KNOB_KEYS if key in knobs
                },
                "requested_capabilities": [
                    f"render:{knobs['render_mode']}",
                    f"visual:{knobs['visual_profile']}",
                    f"animation:{knobs['animation']}",
                    f"camera:{knobs['camera']}",
                    f"language:{knobs['language']}",
                    f"dubbing:{knobs['dubbing']}",
                    f"segmentation:{knobs['segmentation']}",
                ],
                "estimated_media": {
                    "still_images": int(row["still_images"]),
                    "animation_clips": int(row["animation_clips"]),
                    "voice_tracks": int(row["voice_tracks"]),
                },
        }
        if proposal_sections is not None:
            proposal = _mapping(
                proposal_sections[index], "planner proposal section"
            )
            if str(proposal.get("focus") or "") != focus:
                raise CustomFilmContractError(
                    "Custom Film orchestration planner focus changed"
                )
            beats = proposal.get("beats")
            if beats is not None:
                semantic_section["beats"] = copy.deepcopy(
                    _sequence(beats, "planner orchestration beats")
                )
        sections.append(semantic_section)
    totals = _mapping(quote.get("totals"), "approved quote totals")
    if sum(section["duration_seconds"] for section in sections) != int(
        totals.get("duration_seconds", -1)
    ):
        raise CustomFilmContractError(
            "Custom Film orchestration quote duration changed"
        )
    return {
        "capability_catalog_version": CAPABILITY_CATALOG_VERSION,
        "compatibility_version": str(plan.get("compatibility_version") or ""),
        "total_duration_seconds": int(totals["duration_seconds"]),
        "sections": sections,
    }


def resolve_layered_recipe(cue_value: Any) -> dict[str, Any]:
    cue = _mapping(cue_value, "semantic cue")
    signals = _mapping(cue["signals"], "semantic signals")
    requested = cue.get("requested_capabilities")
    # Every executable beat gets two real visual finishing systems even when
    # the planner requests only approved media plus motion audio.
    primitives = ["SignalPulse", "MediaKinetics"]
    if requested is not None:
        for capability_id in _sequence(
            requested, "requested orchestration capabilities"
        ):
            primitive = CAPABILITY_TO_PRIMITIVE.get(str(capability_id))
            if primitive and primitive not in primitives:
                primitives.append(primitive)
    else:
        for intent, primitive in MOTION_PRIORITY:
            if intent in signals["intents"] and primitive not in primitives:
                primitives.append(primitive)
    if "MotionAudioSystem" not in primitives:
        primitives.append("MotionAudioSystem")
    if (signals["dialogue"] or signals["captions"]) and "BilingualCaptions" not in primitives:
        primitives.append("BilingualCaptions")
    energy = int(signals["energy"])
    layers = []
    for index, primitive in enumerate(primitives):
        layers.append(
            {
                "primitive": primitive,
                "zIndex": 60 if primitive == "SignalPulse" else 0 if primitive == "MotionAudioSystem" else 40 + index,
                "blend": "screen" if primitive in {"SignalPulse", "RadioWaveform"} else "normal",
                "intensity": round(min(1, 0.28 + energy * 0.22), 2),
                "safeZone": "full-title-safe" if primitive == "SignalPulse" else "center-critical",
            }
        )
    presentation = "Boundary" if "transition" in signals["intents"] else "SignalPulse"
    witness_caption_lead = (
        signals["dialogue"]
        and signals["captions"]
        and "witness" in signals["intents"]
        and "code" not in signals["intents"]
    )
    if witness_caption_lead:
        presentation = "BilingualCaptions"
    if presentation != "Boundary":
        if not witness_caption_lead:
            for intent, primitive in MOTION_PRIORITY:
                if intent in signals["intents"]:
                    presentation = primitive
                    break
    transform_carry = "_to_" in signals["handoff"]
    boundary = "transition" in signals["intents"]
    return {
        "id": cue["id"],
        "sectionIndex": cue["section_index"],
        "from": cue["from"],
        "to": cue["to"],
        "durationInFrames": cue["to"] - cue["from"] + 1,
        "signals": copy.deepcopy(signals),
        "narrativeFunction": cue.get("narrative_function"),
        "requestedCapabilities": copy.deepcopy(requested or []),
        "media": {
            "primary": "approved-overlap",
            "secondary": "approved-overlap-optional",
            "primaryZIndex": 10,
            "secondaryZIndex": 14,
            "secondaryBlend": "screen",
            "secondaryIntensity": round(0.14 + energy * 0.08, 2),
        },
        "motionLayers": layers,
        "presentation": presentation,
        "caption": {
            "mode": "bilingual-word-emphasis" if signals["captions"] and signals["dialogue"] else "approved" if signals["captions"] else "none",
            "zIndex": 90,
            "safeZone": "center-critical",
        },
        "camera": {
            "mode": "locked" if energy == 0 else "reactive-push" if signals["dialogue"] else "investigative-drift" if set(signals["intents"]) & {"map", "evidence", "timeline"} else "slow-push",
            # Keep whole-number endpoints as integers. Python otherwise
            # canonicalizes 0.0 differently from JSON.parse/JavaScript (0),
            # which would make an unchanged approved recipe fail its
            # cross-runtime contract hash after durable serialization.
            "intensity": energy // 3 if energy in {0, 3} else round(energy / 3, 3),
        },
        "transition": {
            "mode": "dip" if boundary and energy == 0 else "fade" if boundary else "transform-carry" if transform_carry else "none",
            "carry": signals["handoff"],
            "overlapFrames": 0,
        },
        "audio": {
            "bedGain": 0 if signals["handoff"] == "silence" else 0.22,
            "dialogueDuck": 0.24 if signals["dialogue"] else 1,
            "pulse": signals["handoff"] != "silence",
            "dataClicks": bool(set(signals["intents"]) & {"map", "evidence", "timeline", "code"}),
            "silenceDrop": signals["handoff"] == "silence",
            "transitionEnvelope": boundary or transform_carry,
        },
    }


def _allocate_frames(weights: list[float], total: int) -> list[int]:
    if not weights or total < len(weights):
        raise CustomFilmContractError(
            "Custom Film orchestration beat duration is invalid"
        )
    weight_total = sum(weights)
    exact = [weight / weight_total * total for weight in weights]
    allocated = [max(1, int(value)) for value in exact]
    delta = total - sum(allocated)
    if delta > 0:
        order = sorted(
            range(len(weights)),
            key=lambda index: (-(exact[index] - int(exact[index])), index),
        )
        for index in range(delta):
            allocated[order[index % len(order)]] += 1
    elif delta < 0:
        order = sorted(
            range(len(weights)),
            key=lambda index: (exact[index] - int(exact[index]), -index),
        )
        for index in range(-delta):
            target = next(
                candidate for candidate in order if allocated[candidate] > 1
            )
            allocated[target] -= 1
    if sum(allocated) != total or any(value <= 0 for value in allocated):
        raise CustomFilmContractError(
            "Custom Film orchestration frame allocation changed"
        )
    return allocated


def resolve_semantic_input_plan(
    semantic_input_value: Any,
) -> dict[str, Any] | None:
    semantic_input = _mapping(semantic_input_value, "orchestration semantic input")
    sections = _sequence(semantic_input["sections"], "orchestration semantic sections")
    if any("beats" not in _mapping(section, "semantic section") for section in sections):
        return None
    recipes: list[dict[str, Any]] = []
    frame = 0
    for section in sections:
        beats = _sequence(section["beats"], "semantic section beats")
        section_frames = int(section["duration_seconds"]) * 24
        durations = _allocate_frames(
            [float(_mapping(beat, "semantic beat")["duration_weight"]) for beat in beats],
            section_frames,
        )
        for beat_index, (beat_value, duration) in enumerate(zip(beats, durations)):
            beat = _mapping(beat_value, "semantic beat")
            capabilities = _sequence(
                beat.get("capability_ids"), "beat capability ids"
            )
            if (
                len(capabilities) != len(set(capabilities))
                or "media.approved_primary" not in capabilities
                or "audio.motion_system" not in capabilities
                or any(
                    str(value) not in {
                        "media.approved_primary", "media.approved_secondary",
                        *CAPABILITY_TO_PRIMITIVE,
                    }
                    for value in capabilities
                )
            ):
                raise CustomFilmContractError(
                    "Custom Film orchestration capability choice changed"
                )
            cue = {
                "id": f"{section['section_id']}:beat:{beat_index}",
                "section_index": section["order_index"],
                "from": frame,
                "to": frame + duration - 1,
                "requested_capabilities": capabilities,
                "narrative_function": beat["narrative_function"],
                "signals": {
                    "media_kind": beat["media_kind"],
                    "dialogue": beat["dialogue"],
                    "captions": beat["captions"],
                    "intents": beat["intents"],
                    "energy": beat["energy"],
                    "handoff": beat["handoff"],
                },
            }
            recipes.append(resolve_layered_recipe(cue))
            frame += duration
    expected = int(semantic_input["total_duration_seconds"]) * 24
    if frame != expected:
        raise CustomFilmContractError(
            "Custom Film orchestration recipes do not fill the film"
        )
    return {
        "fps": 24,
        "total_frames": frame,
        "recipes": recipes,
    }


def _contract_from_semantic_input(semantic_input_value: Any) -> dict[str, Any]:
    semantic_input = copy.deepcopy(
        _mapping(semantic_input_value, "approved orchestration semantic input")
    )
    plan = load_reference_semantic_plan()
    approved_beat_plan = resolve_semantic_input_plan(semantic_input)
    content = " ".join(
        f"{section['focus']} {section['purpose']}"
        for section in semantic_input["sections"]
    ).casefold()
    concepts = {
        concept for concept in REFERENCE_REQUIRED_CONCEPTS
        if re.search(rf"\b{re.escape(concept)}\b", content)
    }
    reference_compatible = (
        [(s["role"], s["duration_seconds"]) for s in semantic_input["sections"]]
        == [("opening", 45), ("evidence", 105), ("case_study", 90), ("explanation", 60)]
        and concepts == REFERENCE_REQUIRED_CONCEPTS
        and approved_beat_plan is not None
        and {
            layer["primitive"]
            for recipe in approved_beat_plan["recipes"]
            for layer in recipe["motionLayers"]
        }.issuperset(
            {
                "SignalPulse", "OutageMap", "EvidenceBoard",
                "IncidentTimeline", "RadioWaveform", "BilingualCaptions",
                "NetworkExplainer", "StoryEngineReveal", "MotionAudioSystem",
            }
        )
    )
    # The executable plan is always the planner-selected, deterministically
    # resolved beat plan. The tracked outage fixture is parity evidence only;
    # it may never replace an approved vision with a different recipe.
    resolved_plan = approved_beat_plan
    contract = {
        "contract_version": ORCHESTRATION_CONTRACT_VERSION,
        "decision_rules_version": DECISION_RULES_VERSION,
        "semantic_input": semantic_input,
        "semantic_input_hash": canonical_hash(semantic_input),
        "approved_beat_plan": approved_beat_plan,
        "approved_beat_plan_hash": (
            canonical_hash(approved_beat_plan)
            if approved_beat_plan is not None else None
        ),
        "resolved_plan": resolved_plan,
        "resolved_plan_hash": (
            canonical_hash(resolved_plan) if resolved_plan is not None else None
        ),
        "reference_compatible": reference_compatible,
        "story_identity": plan["story_identity"] if reference_compatible else canonical_hash(semantic_input),
        "signals_hash": (
            canonical_hash(
                [recipe["signals"] for recipe in resolved_plan["recipes"]]
            )
            if resolved_plan is not None else None
        ),
        "recipe_hash": (
            canonical_hash(resolved_plan["recipes"])
            if resolved_plan is not None else None
        ),
        "reference_plan_version": plan["version"] if reference_compatible else None,
    }
    return {**contract, "contract_hash": canonical_hash(contract)}


def validate_executable_orchestration(
    value: Any,
    *,
    total_duration_seconds: int,
    section_duration_seconds: Sequence[int],
    fps: int = 24,
) -> dict[str, Any]:
    """Apply the one approval-to-render executable recipe law."""
    actual = _mapping(value, "executable orchestration contract")
    body = copy.deepcopy(actual)
    contract_hash = body.pop("contract_hash", None)
    resolved = _mapping(
        actual.get("resolved_plan"), "executable resolved plan"
    )
    recipes = _sequence(
        resolved.get("recipes"), "executable resolved recipes"
    )
    if (
        actual.get("contract_version") != ORCHESTRATION_CONTRACT_VERSION
        or actual.get("decision_rules_version") != DECISION_RULES_VERSION
        or contract_hash != canonical_hash(body)
        or actual.get("semantic_input_hash")
        != canonical_hash(
            _mapping(
                actual.get("semantic_input"),
                "executable semantic input",
            )
        )
        or actual.get("resolved_plan_hash") != canonical_hash(resolved)
        or actual.get("recipe_hash") != canonical_hash(recipes)
        or not isinstance(fps, int)
        or fps <= 0
        or resolved.get("fps") != fps
        or not isinstance(total_duration_seconds, int)
        or total_duration_seconds <= 0
        or resolved.get("total_frames") != total_duration_seconds * fps
    ):
        raise CustomFilmContractError(
            "Custom Film orchestration is not executable"
        )
    durations = [
        int(duration) for duration in section_duration_seconds
        if isinstance(duration, int) and duration > 0
    ]
    if (
        len(durations) != len(section_duration_seconds)
        or sum(durations) != total_duration_seconds
    ):
        raise CustomFilmContractError(
            "Custom Film orchestration section timing is not executable"
        )
    section_bounds: list[tuple[int, int]] = []
    section_frame = 0
    for duration in durations:
        end = section_frame + duration * fps
        section_bounds.append((section_frame, end))
        section_frame = end
    recipe_frame = 0
    for recipe_value in recipes:
        recipe = _mapping(recipe_value, "executable recipe")
        section_index = recipe.get("sectionIndex")
        start = recipe.get("from")
        end = recipe.get("to")
        duration = recipe.get("durationInFrames")
        layers = [
            _mapping(layer, "executable motion layer")
            for layer in _sequence(
                recipe.get("motionLayers"), "executable motion layers"
            )
        ]
        visual_primitives = {
            str(layer.get("primitive") or "")
            for layer in layers
            if str(layer.get("primitive") or "")
            not in NON_VISUAL_PRIMITIVES
        }
        if (
            not isinstance(section_index, int)
            or section_index < 0
            or section_index >= len(section_bounds)
            or start != recipe_frame
            or not isinstance(end, int)
            or end < start
            or duration != end - start + 1
            or len(visual_primitives) < 2
            or not isinstance(recipe.get("media"), Mapping)
            or not isinstance(recipe.get("audio"), Mapping)
        ):
            raise CustomFilmContractError(
                "Custom Film orchestration recipe is not executable"
            )
        section_start, section_end = section_bounds[section_index]
        if start < section_start or end >= section_end:
            raise CustomFilmContractError(
                "Custom Film orchestration recipe crossed its section"
            )
        recipe_frame = end + 1
    if recipe_frame != total_duration_seconds * fps:
        raise CustomFilmContractError(
            "Custom Film orchestration recipes do not fill the film"
        )
    return copy.deepcopy(actual)


def compile_approved_orchestration(
    internal_plan_value: Any,
    quote_inputs_value: Any,
    planner_proposal_value: Any | None = None,
) -> dict[str, Any]:
    semantic_input = semantic_input_from_approved_plan(
        internal_plan_value, quote_inputs_value, planner_proposal_value
    )
    compiled = _contract_from_semantic_input(semantic_input)
    if compiled.get("resolved_plan") is not None:
        validate_executable_orchestration(
            compiled,
            total_duration_seconds=int(
                semantic_input["total_duration_seconds"]
            ),
            section_duration_seconds=[
                int(section["duration_seconds"])
                for section in semantic_input["sections"]
            ],
        )
    return compiled


def validate_approved_orchestration(
    value: Any,
    internal_plan_value: Any,
    quote_inputs_value: Any,
) -> dict[str, Any]:
    actual = _mapping(value, "approved orchestration contract")
    quote_without_orchestration = copy.deepcopy(
        _mapping(quote_inputs_value, "approved quote")
    )
    quote_without_orchestration.pop("orchestration", None)
    base_semantic = semantic_input_from_approved_plan(
        internal_plan_value, quote_without_orchestration
    )
    actual_semantic = _mapping(
        actual.get("semantic_input"), "approved orchestration semantic input"
    )
    if (
        set(actual_semantic) != set(base_semantic)
        or any(
            actual_semantic[key] != base_semantic[key]
            for key in base_semantic
            if key != "sections"
        )
    ):
        raise CustomFilmContractError(
            "Custom Film approved orchestration semantic input changed"
        )
    base_sections = _sequence(base_semantic["sections"], "base semantic sections")
    actual_sections = _sequence(actual_semantic.get("sections"), "actual semantic sections")
    if len(base_sections) != len(actual_sections):
        raise CustomFilmContractError(
            "Custom Film approved orchestration section count changed"
        )
    for base, candidate in zip(base_sections, actual_sections):
        candidate_without_beats = copy.deepcopy(_mapping(candidate, "semantic section"))
        candidate_without_beats.pop("beats", None)
        if candidate_without_beats != base:
            raise CustomFilmContractError(
                "Custom Film approved orchestration semantic input changed"
            )
    expected = _contract_from_semantic_input(actual_semantic)
    if actual != expected:
        raise CustomFilmContractError(
            "Custom Film approved orchestration identity changed"
        )
    if actual.get("resolved_plan") is not None:
        validate_executable_orchestration(
            actual,
            total_duration_seconds=int(
                actual_semantic["total_duration_seconds"]
            ),
            section_duration_seconds=[
                int(section["duration_seconds"])
                for section in actual_semantic["sections"]
            ],
        )
    return copy.deepcopy(actual)
