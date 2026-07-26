"""Storyboard-driven direction contracts for Custom Film.

The public production profiles are shot-level techniques. They never own film
identity. This module puts one immutable story/style/cast/environment contract
above those techniques, compiles exact ordered shots, and exposes deterministic
storyboard, visual-verification, Remotion-admission, and staged-spend gates.

Nothing in this module calls a model or provider.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from itertools import pairwise
from typing import Any, Literal
from uuid import UUID, uuid5

from custom_film_contract import (
    CustomFilmContractError,
    canonical_hash,
    canonical_json,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

DIRECTOR_SCHEMA_VERSION = 1
DIRECTOR_FPS = 24
DIRECTOR_CONTRACT_NAMESPACE = UUID("e3f38a46-b80f-4dc4-bd1d-cb7fed479ab7")
THIRD_PERSON_NARRATOR_ID = "third_person_narrator"

SHOT_TECHNIQUES = frozenset(
    {
        "poco_dialogue",
        "dvsu_documentary",
        "power_doctrine_exposition",
        "cinematic_action",
    }
)
PERFORMANCE_MODES = frozenset({"dialogue", "exposition", "silent_action"})
TRANSITION_KINDS = frozenset(
    {"opening", "continuous", "time_cut", "location_cut", "montage", "memory"}
)
PROGRESSION_KINDS = frozenset(
    {"story", "action", "information", "emotion", "spatial"}
)
STAGE_SEQUENCE = (
    "script_director",
    "storyboards",
    "final_pictures",
    "animation_voice",
    "assembly",
)
VISUAL_ISSUE_CODES = frozenset(
    {
        "action_missing",
        "character_drift",
        "closing_state_mismatch",
        "continuity_break",
        "environment_drift",
        "lip_sync_mismatch",
        "motion_missing",
        "opening_state_mismatch",
        "style_drift",
    }
)
_SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        frozen=True,
    )


def _slug(value: str, label: str) -> str:
    if not _SLUG_RE.fullmatch(value):
        raise ValueError(
            f"{label} must be a lowercase snake_case identifier"
        )
    return value


def _hash(value: str, label: str) -> str:
    if not _HASH_RE.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _nonempty_unique(values: Sequence[str], label: str) -> tuple[str, ...]:
    normalized = tuple(str(value).strip() for value in values)
    if (
        not normalized
        or any(not value for value in normalized)
        or len(normalized) != len(set(normalized))
    ):
        raise CustomFilmContractError(
            f"Custom Film {label} must be non-empty and unique"
        )
    return normalized


class StyleLock(_StrictModel):
    medium: str = Field(min_length=3, max_length=160)
    rendering_approach: str = Field(min_length=3, max_length=240)
    palette: tuple[str, ...] = Field(min_length=2, max_length=12)
    texture: str = Field(min_length=3, max_length=160)
    lens_language: str = Field(min_length=3, max_length=240)
    lighting_law: str = Field(min_length=3, max_length=240)
    aspect_ratio: Literal["16:9", "9:16", "1:1", "4:5"]
    negative_constraints: tuple[str, ...] = Field(min_length=1, max_length=20)

    @field_validator("palette", "negative_constraints")
    @classmethod
    def validate_unique_text(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("Style-lock lists cannot contain duplicates")
        return value


class CharacterLock(_StrictModel):
    character_id: str
    display_name: str = Field(min_length=1, max_length=100)
    story_role: str = Field(min_length=3, max_length=200)
    identity_prompt: str = Field(min_length=20, max_length=2_000)
    face_body_lock: str = Field(min_length=10, max_length=1_000)
    wardrobe_lock: str = Field(min_length=5, max_length=1_000)
    voice_lock: str = Field(min_length=5, max_length=500)
    performance_law: str = Field(min_length=5, max_length=500)
    forbidden_drift: tuple[str, ...] = Field(min_length=1, max_length=20)

    @field_validator("character_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _slug(value, "character_id")


class PropLock(_StrictModel):
    prop_id: str
    description: str = Field(min_length=3, max_length=500)
    home_position: str = Field(min_length=3, max_length=500)
    continuity_law: str = Field(min_length=3, max_length=500)

    @field_validator("prop_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _slug(value, "prop_id")


class EnvironmentLock(_StrictModel):
    environment_id: str
    display_name: str = Field(min_length=1, max_length=120)
    story_function: str = Field(min_length=3, max_length=300)
    identity_prompt: str = Field(min_length=20, max_length=2_000)
    architecture_lock: str = Field(min_length=5, max_length=1_000)
    lighting_time_weather_lock: str = Field(min_length=5, max_length=1_000)
    geography_lock: str = Field(min_length=5, max_length=1_000)
    palette_lock: str = Field(min_length=3, max_length=500)
    props: tuple[PropLock, ...] = Field(default=(), max_length=20)

    @field_validator("environment_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _slug(value, "environment_id")

    @model_validator(mode="after")
    def validate_props(self) -> EnvironmentLock:
        prop_ids = [prop.prop_id for prop in self.props]
        if len(prop_ids) != len(set(prop_ids)):
            raise ValueError("Environment prop IDs must be unique")
        return self


class FilmBible(_StrictModel):
    title: str = Field(min_length=1, max_length=200)
    logline: str = Field(min_length=20, max_length=1_000)
    throughline: str = Field(min_length=20, max_length=1_000)
    central_question: str = Field(min_length=10, max_length=500)
    beginning_state: str = Field(min_length=10, max_length=1_000)
    ending_state: str = Field(min_length=10, max_length=1_000)
    visual_motif: str = Field(min_length=5, max_length=500)
    timeline_law: str = Field(min_length=10, max_length=1_000)
    geography_law: str = Field(min_length=10, max_length=1_000)
    narrator_mode: Literal["none", "third_person", "character"]
    narrator_character_id: str | None = None
    style: StyleLock
    characters: tuple[CharacterLock, ...] = Field(min_length=1, max_length=40)
    environments: tuple[EnvironmentLock, ...] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def validate_lock_graph(self) -> FilmBible:
        character_ids = [row.character_id for row in self.characters]
        environment_ids = [row.environment_id for row in self.environments]
        if len(character_ids) != len(set(character_ids)):
            raise ValueError("Film-bible character IDs must be unique")
        if len(environment_ids) != len(set(environment_ids)):
            raise ValueError("Film-bible environment IDs must be unique")
        if self.narrator_mode == "character":
            if self.narrator_character_id not in character_ids:
                raise ValueError(
                    "Character narration must bind to a locked character"
                )
        elif self.narrator_character_id is not None:
            raise ValueError(
                "Only character narration may set narrator_character_id"
            )
        if self.beginning_state == self.ending_state:
            raise ValueError("A story must change between beginning and ending")
        return self


class StoryState(_StrictModel):
    story_facts: tuple[str, ...] = Field(min_length=1, max_length=20)
    character_positions: dict[str, str] = Field(default_factory=dict)
    prop_states: dict[str, str] = Field(default_factory=dict)
    emotional_state: dict[str, str] = Field(default_factory=dict)


class SpokenLine(_StrictModel):
    speaker_id: str
    kind: Literal["dialogue", "narration"]
    text: str = Field(min_length=1, max_length=600)
    language: str = Field(min_length=2, max_length=40)
    delivery: str = Field(min_length=2, max_length=240)
    addressee_id: str | None = None


class ShotDraft(_StrictModel):
    shot_key: str
    section_id: UUID
    duration_frames: int = Field(ge=1, le=86_400)
    technique: Literal[
        "poco_dialogue",
        "dvsu_documentary",
        "power_doctrine_exposition",
        "cinematic_action",
    ]
    performance_mode: Literal["dialogue", "exposition", "silent_action"]
    narrative_purpose: str = Field(min_length=10, max_length=1_000)
    caused_by: tuple[str, ...] = Field(default=(), max_length=8)
    progression_kinds: tuple[
        Literal["story", "action", "information", "emotion", "spatial"], ...
    ] = Field(min_length=1, max_length=5)
    story_value: str = Field(min_length=10, max_length=1_000)
    opening_state: StoryState
    action_beats: tuple[str, ...] = Field(min_length=1, max_length=12)
    closing_state: StoryState
    transition_from_previous: Literal[
        "opening", "continuous", "time_cut", "location_cut", "montage", "memory"
    ]
    continuity_bridge: str | None = Field(default=None, max_length=1_000)
    environment_id: str
    character_ids: tuple[str, ...] = Field(min_length=1, max_length=20)
    active_prop_ids: tuple[str, ...] = Field(default=(), max_length=20)
    screen_direction: str = Field(min_length=3, max_length=300)
    shot_size: str = Field(min_length=2, max_length=160)
    camera_move: str = Field(min_length=2, max_length=300)
    spoken_lines: tuple[SpokenLine, ...] = Field(default=(), max_length=20)
    storyboard_composition: str = Field(min_length=20, max_length=2_000)
    final_picture_intent: str = Field(min_length=20, max_length=2_000)
    motion_intent: str = Field(min_length=20, max_length=2_000)

    @field_validator("shot_key")
    @classmethod
    def validate_shot_key(cls, value: str) -> str:
        return _slug(value, "shot_key")

    @field_validator("environment_id")
    @classmethod
    def validate_environment_id(cls, value: str) -> str:
        return _slug(value, "environment_id")

    @field_validator(
        "caused_by",
        "progression_kinds",
        "character_ids",
        "active_prop_ids",
    )
    @classmethod
    def validate_unique_values(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("Shot bindings cannot contain duplicates")
        return value

    @model_validator(mode="after")
    def validate_performance(self) -> ShotDraft:
        if self.opening_state == self.closing_state:
            raise ValueError("Every shot must visibly change story state")
        if self.performance_mode == "dialogue":
            if self.technique != "poco_dialogue":
                raise ValueError(
                    "Back-and-forth dialogue uses the Poco dialogue technique"
                )
            if len(self.spoken_lines) < 2:
                raise ValueError("Dialogue needs at least two spoken turns")
            if any(line.kind != "dialogue" for line in self.spoken_lines):
                raise ValueError(
                    "Narration cannot substitute inside a dialogue performance"
                )
            speakers = [line.speaker_id for line in self.spoken_lines]
            if len(set(speakers)) < 2:
                raise ValueError("Dialogue needs at least two speakers")
            if any(left == right for left, right in pairwise(speakers)):
                raise ValueError(
                    "Dialogue turns must alternate instead of repeating one speaker"
                )
        elif self.performance_mode == "exposition":
            if self.technique not in {
                "dvsu_documentary",
                "power_doctrine_exposition",
            }:
                raise ValueError(
                    "Exposition must use a documentary or Power Doctrine technique"
                )
            if not self.spoken_lines or any(
                line.kind != "narration" for line in self.spoken_lines
            ):
                raise ValueError(
                    "Exposition requires purposeful narration, not dialogue labels"
                )
        else:
            if self.technique != "cinematic_action":
                raise ValueError(
                    "Silent action uses the cinematic action technique"
                )
            if self.spoken_lines:
                raise ValueError("Silent action cannot contain spoken lines")
        return self


class DirectorDraft(_StrictModel):
    film_bible: FilmBible
    shots: tuple[ShotDraft, ...] = Field(min_length=1, max_length=2_000)


def _state_payload(value: StoryState) -> dict[str, Any]:
    return value.model_dump(mode="json")


def _style_lock_text(style: StyleLock) -> str:
    negatives = "; ".join(style.negative_constraints)
    palette = ", ".join(style.palette)
    return (
        f"GLOBAL STYLE LOCK — medium: {style.medium}; rendering: "
        f"{style.rendering_approach}; palette: {palette}; texture: "
        f"{style.texture}; lens: {style.lens_language}; lighting: "
        f"{style.lighting_law}; aspect: {style.aspect_ratio}; never: {negatives}."
    )


def _compiled_shot_prompts(
    shot: ShotDraft,
    bible: FilmBible,
    characters: Mapping[str, CharacterLock],
    environments: Mapping[str, EnvironmentLock],
) -> dict[str, str]:
    character_lock = " | ".join(
        (
            f"{characters[character_id].display_name}: "
            f"{characters[character_id].identity_prompt}; "
            f"{characters[character_id].face_body_lock}; "
            f"{characters[character_id].wardrobe_lock}"
        )
        for character_id in shot.character_ids
    )
    environment = environments[shot.environment_id]
    prop_by_id = {prop.prop_id: prop for prop in environment.props}
    prop_lock = " | ".join(
        (
            f"{prop_by_id[prop_id].description} at "
            f"{prop_by_id[prop_id].home_position}; "
            f"{prop_by_id[prop_id].continuity_law}"
        )
        for prop_id in shot.active_prop_ids
    )
    invariant = (
        f"{_style_lock_text(bible.style)} "
        f"CHARACTER LOCKS — {character_lock}. "
        f"ENVIRONMENT LOCK — {environment.display_name}: "
        f"{environment.identity_prompt}; {environment.architecture_lock}; "
        f"{environment.lighting_time_weather_lock}; "
        f"{environment.geography_lock}; {environment.palette_lock}. "
        f"PROP LOCKS — {prop_lock or 'none'}."
    )
    action = " Then ".join(shot.action_beats)
    state_change = (
        f"Open on {canonical_json(_state_payload(shot.opening_state))}. "
        f"Visible action: {action}. "
        f"End on {canonical_json(_state_payload(shot.closing_state))}."
    )
    return {
        "storyboard_prompt": (
            f"{invariant} STORYBOARD CONTRACT — {shot.storyboard_composition}. "
            f"{state_change} Screen direction: {shot.screen_direction}; "
            f"shot size: {shot.shot_size}; camera: {shot.camera_move}."
        ),
        "final_picture_prompt": (
            f"{invariant} FINAL PICTURE — {shot.final_picture_intent}. "
            f"Depict only the opening state needed to perform this shot: "
            f"{canonical_json(_state_payload(shot.opening_state))}. "
            f"Composition: {shot.storyboard_composition}."
        ),
        "motion_prompt": (
            f"{invariant} MOTION CONTRACT — {shot.motion_intent}. "
            f"{state_change} Preserve identities, environment, props, and "
            f"screen direction. Camera: {shot.camera_move}."
        ),
    }


def _director_error(message: str) -> CustomFilmContractError:
    return CustomFilmContractError(
        f"{message}; no storyboard, final picture, animation, or provider work "
        "was started"
    )


def compile_director_contract(
    raw: Mapping[str, Any],
    *,
    plan_id: str,
    plan_hash: str,
    section_ids: Sequence[str],
    total_frames: int,
    fps: int = DIRECTOR_FPS,
) -> dict[str, Any]:
    """Compile one film bible and ordered shot list into immutable direction."""
    try:
        parsed_plan_id = str(UUID(str(plan_id)))
        _hash(str(plan_hash), "plan_hash")
        if type(fps) is not int or fps < 1 or fps > 120:
            raise ValueError("fps must be an exact positive integer")
        if type(total_frames) is not int or total_frames < 1:
            raise ValueError("total_frames must be an exact positive integer")
        expected_sections = _nonempty_unique(section_ids, "section IDs")
        expected_sections = tuple(str(UUID(value)) for value in expected_sections)
        draft = DirectorDraft.model_validate(raw)
    except (ValueError, TypeError) as exc:
        raise _director_error(f"Custom Film director contract is invalid: {exc}") from exc

    bible = draft.film_bible
    characters = {row.character_id: row for row in bible.characters}
    environments = {row.environment_id: row for row in bible.environments}
    prop_ids = {
        environment_id: {prop.prop_id for prop in environment.props}
        for environment_id, environment in environments.items()
    }
    shot_keys = [shot.shot_key for shot in draft.shots]
    if len(shot_keys) != len(set(shot_keys)):
        raise _director_error("Custom Film shot keys are duplicated")
    if sum(shot.duration_frames for shot in draft.shots) != total_frames:
        raise _director_error(
            "Custom Film shot durations do not reconcile to the approved film"
        )

    seen_shot_keys: set[str] = set()
    used_sections: list[str] = []
    spoken_texts: set[str] = set()
    compiled_shots: list[dict[str, Any]] = []
    previous: ShotDraft | None = None
    start_frame = 0
    for order_index, shot in enumerate(draft.shots):
        section_id = str(shot.section_id)
        if section_id not in expected_sections:
            raise _director_error(
                f"Shot {shot.shot_key} references an unapproved section"
            )
        if used_sections and expected_sections.index(section_id) < expected_sections.index(
            used_sections[-1]
        ):
            raise _director_error("Custom Film shots move backward across sections")
        used_sections.append(section_id)
        if shot.environment_id not in environments:
            raise _director_error(
                f"Shot {shot.shot_key} references an unlocked environment"
            )
        if any(character_id not in characters for character_id in shot.character_ids):
            raise _director_error(
                f"Shot {shot.shot_key} references an unlocked character"
            )
        if not set(shot.active_prop_ids).issubset(prop_ids[shot.environment_id]):
            raise _director_error(
                f"Shot {shot.shot_key} references an unlocked environment prop"
            )
        state_character_ids = (
            set(shot.opening_state.character_positions)
            | set(shot.opening_state.emotional_state)
            | set(shot.closing_state.character_positions)
            | set(shot.closing_state.emotional_state)
        )
        if not state_character_ids.issubset(set(shot.character_ids)):
            raise _director_error(
                f"Shot {shot.shot_key} state names an unbound character"
            )
        state_prop_ids = set(shot.opening_state.prop_states) | set(
            shot.closing_state.prop_states
        )
        if not state_prop_ids.issubset(set(shot.active_prop_ids)):
            raise _director_error(
                f"Shot {shot.shot_key} state names an unbound prop"
            )
        line_speakers = {
            line.speaker_id
            for line in shot.spoken_lines
            if line.speaker_id != THIRD_PERSON_NARRATOR_ID
        }
        if not line_speakers.issubset(set(shot.character_ids)):
            raise _director_error(
                f"Shot {shot.shot_key} gives speech to an unbound character"
            )
        for line in shot.spoken_lines:
            if line.addressee_id and line.addressee_id not in shot.character_ids:
                raise _director_error(
                    f"Shot {shot.shot_key} addresses an unbound character"
                )
            folded = re.sub(r"\s+", " ", line.text).casefold()
            if folded in spoken_texts:
                raise _director_error(
                    "Custom Film repeats an already-owned spoken line"
                )
            spoken_texts.add(folded)
        if shot.performance_mode == "exposition":
            allowed_narrator = (
                {THIRD_PERSON_NARRATOR_ID}
                if bible.narrator_mode == "third_person"
                else (
                    {str(bible.narrator_character_id)}
                    if bible.narrator_mode == "character"
                    else set()
                )
            )
            if not allowed_narrator or any(
                line.speaker_id not in allowed_narrator
                for line in shot.spoken_lines
            ):
                raise _director_error(
                    f"Shot {shot.shot_key} narration is not owned by the film bible"
                )
        if previous is None:
            if (
                shot.transition_from_previous != "opening"
                or shot.caused_by
                or shot.continuity_bridge is not None
            ):
                raise _director_error(
                    "The first Custom Film shot must be the uncaused opening"
                )
        else:
            if shot.transition_from_previous == "opening":
                raise _director_error("Only the first shot may be an opening")
            if not shot.caused_by or not set(shot.caused_by).issubset(seen_shot_keys):
                raise _director_error(
                    f"Shot {shot.shot_key} has no valid earlier cause"
                )
            if shot.transition_from_previous == "continuous":
                if (
                    shot.continuity_bridge is not None
                    or canonical_json(_state_payload(shot.opening_state))
                    != canonical_json(_state_payload(previous.closing_state))
                ):
                    raise _director_error(
                        f"Shot {shot.shot_key} breaks continuous story state"
                    )
            elif not shot.continuity_bridge:
                raise _director_error(
                    f"Shot {shot.shot_key} needs a visible transition bridge"
                )
        seen_shot_keys.add(shot.shot_key)
        prompts = _compiled_shot_prompts(shot, bible, characters, environments)
        shot_id = str(
            uuid5(
                DIRECTOR_CONTRACT_NAMESPACE,
                canonical_json(
                    {
                        "plan_id": parsed_plan_id,
                        "plan_hash": plan_hash,
                        "shot_key": shot.shot_key,
                    }
                ),
            )
        )
        shot_payload = {
            **shot.model_dump(mode="json"),
            "shot_id": shot_id,
            "order_index": order_index,
            "start_frame": start_frame,
            "end_frame": start_frame + shot.duration_frames - 1,
            **prompts,
        }
        shot_payload["style_lock_hash"] = canonical_hash(
            bible.style.model_dump(mode="json")
        )
        shot_payload["character_lock_hashes"] = {
            character_id: canonical_hash(
                characters[character_id].model_dump(mode="json")
            )
            for character_id in shot.character_ids
        }
        shot_payload["environment_lock_hash"] = canonical_hash(
            environments[shot.environment_id].model_dump(mode="json")
        )
        shot_payload["shot_hash"] = canonical_hash(shot_payload)
        compiled_shots.append(shot_payload)
        start_frame += shot.duration_frames
        previous = shot

    if set(used_sections) != set(expected_sections):
        raise _director_error("Every approved section needs at least one shot")
    if compiled_shots[0]["opening_state"]["story_facts"][0] != bible.beginning_state:
        raise _director_error("First shot does not open on the film-bible beginning")
    if compiled_shots[-1]["closing_state"]["story_facts"][-1] != bible.ending_state:
        raise _director_error("Last shot does not land the film-bible ending")

    contract = {
        "schema_version": DIRECTOR_SCHEMA_VERSION,
        "fps": fps,
        "plan_id": parsed_plan_id,
        "plan_hash": plan_hash,
        "film_bible": bible.model_dump(mode="json"),
        "film_bible_hash": canonical_hash(bible.model_dump(mode="json")),
        "section_ids": list(expected_sections),
        "total_frames": total_frames,
        "shots": compiled_shots,
    }
    contract["contract_hash"] = canonical_hash(contract)
    return contract


def validate_director_contract(
    value: Mapping[str, Any],
    *,
    expected_plan_hash: str | None = None,
) -> dict[str, Any]:
    """Recompile and prove a stored director contract has not drifted."""
    if not isinstance(value, Mapping):
        raise _director_error("Custom Film director contract is missing")
    contract = copy.deepcopy(dict(value))
    claimed_hash = str(contract.pop("contract_hash", ""))
    if claimed_hash != canonical_hash(contract):
        raise _director_error("Custom Film director contract hash changed")
    if contract.get("schema_version") != DIRECTOR_SCHEMA_VERSION:
        raise _director_error("Custom Film director schema version changed")
    if expected_plan_hash is not None and contract.get("plan_hash") != expected_plan_hash:
        raise _director_error("Custom Film director plan binding changed")
    shots = contract.get("shots")
    if not isinstance(shots, list) or not shots:
        raise _director_error("Custom Film director shots are missing")
    if [shot.get("order_index") for shot in shots] != list(range(len(shots))):
        raise _director_error("Custom Film director shot order changed")
    if shots[0].get("start_frame") != 0:
        raise _director_error("Custom Film director timing no longer starts at zero")
    for previous, current in pairwise(shots):
        if current.get("start_frame") != previous.get("end_frame") + 1:
            raise _director_error("Custom Film director timing has a frame gap")
    if shots[-1].get("end_frame") != contract.get("total_frames") - 1:
        raise _director_error("Custom Film director timing no longer reconciles")
    for shot in shots:
        shot_copy = copy.deepcopy(shot)
        claimed_shot_hash = str(shot_copy.pop("shot_hash", ""))
        if claimed_shot_hash != canonical_hash(shot_copy):
            raise _director_error("Custom Film shot contract hash changed")
    return {**contract, "contract_hash": claimed_hash}


class StoryboardReview(_StrictModel):
    shot_id: UUID
    contract_hash: str
    reference_gate_hash: str
    storyboard_artifact_id: str = Field(min_length=1, max_length=300)
    storyboard_image_sha256: str
    storyboard_prompt_hash: str
    style_match: bool
    character_lock_match: bool
    environment_lock_match: bool
    action_progresses: bool
    continuity_match: bool
    verdict: Literal["approved", "rejected"]
    notes: str = Field(default="", max_length=2_000)

    @field_validator(
        "contract_hash",
        "reference_gate_hash",
        "storyboard_image_sha256",
        "storyboard_prompt_hash",
    )
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return _hash(value, "storyboard review hash")

    @model_validator(mode="after")
    def validate_verdict(self) -> StoryboardReview:
        passed = all(
            (
                self.style_match,
                self.character_lock_match,
                self.environment_lock_match,
                self.action_progresses,
                self.continuity_match,
            )
        )
        if (self.verdict == "approved") != passed:
            raise ValueError("Storyboard verdict must match its review checks")
        if not passed and not self.notes:
            raise ValueError("Rejected storyboard reviews need repair notes")
        return self


class LockReferenceReview(_StrictModel):
    lock_kind: Literal["character", "environment"]
    lock_id: str
    contract_hash: str
    reference_artifact_id: str = Field(min_length=1, max_length=300)
    reference_image_sha256: str
    lock_prompt_hash: str
    identity_match: bool
    style_match: bool
    verdict: Literal["approved", "rejected"]
    notes: str = Field(default="", max_length=2_000)

    @field_validator("lock_id")
    @classmethod
    def validate_lock_id(cls, value: str) -> str:
        return _slug(value, "lock reference ID")

    @field_validator(
        "contract_hash",
        "reference_image_sha256",
        "lock_prompt_hash",
    )
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return _hash(value, "lock reference hash")

    @model_validator(mode="after")
    def validate_verdict(self) -> LockReferenceReview:
        passed = self.identity_match and self.style_match
        if (self.verdict == "approved") != passed:
            raise ValueError("Lock-reference verdict must match its review checks")
        if not passed and not self.notes:
            raise ValueError("Rejected lock references need repair notes")
        return self


def compile_reference_gate(
    director_contract: Mapping[str, Any],
    references: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Require approved visual anchors for every character and environment."""
    director = validate_director_contract(director_contract)
    try:
        parsed = [
            LockReferenceReview.model_validate(reference)
            for reference in references
        ]
    except (ValueError, TypeError) as exc:
        raise _director_error(
            f"Custom Film lock reference is invalid: {exc}"
        ) from exc
    bible = director["film_bible"]
    expected: dict[tuple[str, str], dict[str, Any]] = {
        ("character", str(row["character_id"])): row
        for row in bible["characters"]
    }
    expected.update(
        {
            ("environment", str(row["environment_id"])): row
            for row in bible["environments"]
        }
    )
    by_lock = {(row.lock_kind, row.lock_id): row for row in parsed}
    if len(by_lock) != len(parsed) or set(by_lock) != set(expected):
        raise _director_error(
            "Custom Film lock references do not match the exact film bible"
        )
    approvals: list[dict[str, Any]] = []
    for lock_key, lock_payload in expected.items():
        review = by_lock[lock_key]
        if review.contract_hash != director["contract_hash"]:
            raise _director_error("Custom Film lock reference uses stale direction")
        if review.lock_prompt_hash != canonical_hash(lock_payload):
            raise _director_error("Custom Film lock-reference prompt binding changed")
        if review.verdict != "approved":
            raise _director_error(
                f"Custom Film {review.lock_kind} {review.lock_id} is not approved"
            )
        approvals.append(review.model_dump(mode="json"))
    approvals.sort(key=lambda row: (row["lock_kind"], row["lock_id"]))
    gate = {
        "gate_version": 1,
        "director_contract_hash": director["contract_hash"],
        "reference_count": len(approvals),
        "approvals": approvals,
    }
    gate["reference_gate_hash"] = canonical_hash(gate)
    return gate


def compile_storyboard_gate(
    director_contract: Mapping[str, Any],
    reference_gate: Mapping[str, Any],
    reviews: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Require one approved, contract-bound storyboard for every exact shot."""
    director = validate_director_contract(director_contract)
    references = copy.deepcopy(dict(reference_gate))
    claimed_reference_hash = str(references.pop("reference_gate_hash", ""))
    if (
        claimed_reference_hash != canonical_hash(references)
        or references.get("director_contract_hash") != director["contract_hash"]
    ):
        raise _director_error("Custom Film lock-reference gate changed")
    try:
        parsed = [StoryboardReview.model_validate(review) for review in reviews]
    except (ValueError, TypeError) as exc:
        raise _director_error(f"Custom Film storyboard review is invalid: {exc}") from exc
    shot_by_id = {str(shot["shot_id"]): shot for shot in director["shots"]}
    review_by_id = {str(review.shot_id): review for review in parsed}
    if len(review_by_id) != len(parsed) or set(review_by_id) != set(shot_by_id):
        raise _director_error(
            "Custom Film storyboard reviews do not match the exact shot list"
        )
    approvals: list[dict[str, Any]] = []
    for shot_id, shot in shot_by_id.items():
        review = review_by_id[shot_id]
        if review.contract_hash != director["contract_hash"]:
            raise _director_error("Custom Film storyboard uses stale direction")
        if review.reference_gate_hash != claimed_reference_hash:
            raise _director_error(
                "Custom Film storyboard uses stale character or environment locks"
            )
        expected_prompt_hash = canonical_hash(shot["storyboard_prompt"])
        if review.storyboard_prompt_hash != expected_prompt_hash:
            raise _director_error("Custom Film storyboard prompt binding changed")
        if review.verdict != "approved":
            raise _director_error(
                f"Custom Film storyboard {shot['shot_key']} is not approved"
            )
        approvals.append(review.model_dump(mode="json"))
    gate = {
        "gate_version": 1,
        "director_contract_hash": director["contract_hash"],
        "reference_gate_hash": claimed_reference_hash,
        "shot_count": len(approvals),
        "approvals": approvals,
    }
    gate["storyboard_gate_hash"] = canonical_hash(gate)
    return gate


class FrameObservation(_StrictModel):
    checkpoint: Literal["start", "middle", "end"]
    frame_sha256: str
    style_lock_hash: str
    character_lock_hashes: dict[str, str]
    environment_lock_hash: str
    observed_state: StoryState
    action_evidence: str = Field(min_length=1, max_length=2_000)

    @field_validator("frame_sha256", "style_lock_hash", "environment_lock_hash")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return _hash(value, "frame observation hash")

    @field_validator("character_lock_hashes")
    @classmethod
    def validate_character_hashes(cls, value: dict[str, str]) -> dict[str, str]:
        for digest in value.values():
            _hash(digest, "character lock hash")
        return value


class ShotVerification(_StrictModel):
    shot_id: UUID
    contract_hash: str
    storyboard_gate_hash: str
    clip_artifact_id: str = Field(min_length=1, max_length=300)
    observations: tuple[FrameObservation, FrameObservation, FrameObservation]
    motion_visible: bool
    action_progressed: bool
    continuity_match: bool
    lip_sync_match: bool | None = None
    repair_instruction: str = Field(default="", max_length=2_000)

    @field_validator("contract_hash", "storyboard_gate_hash")
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return _hash(value, "shot verification hash")

    @model_validator(mode="after")
    def validate_checkpoint_order(self) -> ShotVerification:
        if tuple(row.checkpoint for row in self.observations) != (
            "start",
            "middle",
            "end",
        ):
            raise ValueError(
                "Visual verification must inspect start, middle, and end in order"
            )
        return self


def _verification_issues(
    shot: Mapping[str, Any],
    verification: ShotVerification,
) -> list[str]:
    start, middle, end = verification.observations
    issues: list[str] = []
    if any(row.style_lock_hash != shot["style_lock_hash"] for row in (start, middle, end)):
        issues.append("style_drift")
    expected_characters = shot["character_lock_hashes"]
    if any(row.character_lock_hashes != expected_characters for row in (start, middle, end)):
        issues.append("character_drift")
    if any(
        row.environment_lock_hash != shot["environment_lock_hash"]
        for row in (start, middle, end)
    ):
        issues.append("environment_drift")
    if canonical_json(start.observed_state.model_dump(mode="json")) != canonical_json(
        shot["opening_state"]
    ):
        issues.append("opening_state_mismatch")
    if canonical_json(end.observed_state.model_dump(mode="json")) != canonical_json(
        shot["closing_state"]
    ):
        issues.append("closing_state_mismatch")
    if not verification.motion_visible:
        issues.append("motion_missing")
    if not verification.action_progressed or not middle.action_evidence.strip():
        issues.append("action_missing")
    if not verification.continuity_match:
        issues.append("continuity_break")
    if (
        shot["performance_mode"] == "dialogue"
        and verification.lip_sync_match is not True
    ):
        issues.append("lip_sync_mismatch")
    return sorted(set(issues))


def compile_visual_gate(
    director_contract: Mapping[str, Any],
    storyboard_gate: Mapping[str, Any],
    verifications: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Admit clips only after exact start/middle/end verification passes."""
    director = validate_director_contract(director_contract)
    storyboard = copy.deepcopy(dict(storyboard_gate))
    claimed_storyboard_hash = str(storyboard.pop("storyboard_gate_hash", ""))
    if (
        claimed_storyboard_hash != canonical_hash(storyboard)
        or storyboard.get("director_contract_hash") != director["contract_hash"]
    ):
        raise _director_error("Custom Film storyboard gate changed")
    try:
        parsed = [
            ShotVerification.model_validate(verification)
            for verification in verifications
        ]
    except (ValueError, TypeError) as exc:
        raise _director_error(
            f"Custom Film visual verification is invalid: {exc}"
        ) from exc
    shot_by_id = {str(shot["shot_id"]): shot for shot in director["shots"]}
    verification_by_id = {str(row.shot_id): row for row in parsed}
    if (
        len(verification_by_id) != len(parsed)
        or set(verification_by_id) != set(shot_by_id)
    ):
        raise _director_error(
            "Custom Film visual verifications do not match the exact shot list"
        )
    approved: list[dict[str, Any]] = []
    for shot_id, shot in shot_by_id.items():
        verification = verification_by_id[shot_id]
        if (
            verification.contract_hash != director["contract_hash"]
            or verification.storyboard_gate_hash != claimed_storyboard_hash
        ):
            raise _director_error(
                f"Custom Film verification for {shot['shot_key']} is stale"
            )
        issues = _verification_issues(shot, verification)
        if issues:
            if not verification.repair_instruction:
                raise _director_error(
                    f"Custom Film shot {shot['shot_key']} failed "
                    f"{', '.join(issues)} without a repair instruction"
                )
            raise _director_error(
                f"Custom Film shot {shot['shot_key']} failed "
                f"{', '.join(issues)} and is blocked for repair"
            )
        approved.append(
            {
                **verification.model_dump(mode="json"),
                "issue_codes": [],
                "verdict": "approved",
            }
        )
    gate = {
        "gate_version": 1,
        "director_contract_hash": director["contract_hash"],
        "storyboard_gate_hash": claimed_storyboard_hash,
        "shot_count": len(approved),
        "approved_verifications": approved,
    }
    gate["visual_gate_hash"] = canonical_hash(gate)
    return gate


def build_remotion_admission(
    director_contract: Mapping[str, Any],
    storyboard_gate: Mapping[str, Any],
    visual_gate: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the only shot manifest allowed to enter layered Remotion."""
    director = validate_director_contract(director_contract)
    storyboard = copy.deepcopy(dict(storyboard_gate))
    storyboard_hash = str(storyboard.pop("storyboard_gate_hash", ""))
    if storyboard_hash != canonical_hash(storyboard):
        raise _director_error("Custom Film storyboard admission hash changed")
    visual = copy.deepcopy(dict(visual_gate))
    visual_hash = str(visual.pop("visual_gate_hash", ""))
    if visual_hash != canonical_hash(visual):
        raise _director_error("Custom Film visual admission hash changed")
    if (
        storyboard.get("director_contract_hash") != director["contract_hash"]
        or visual.get("director_contract_hash") != director["contract_hash"]
        or visual.get("storyboard_gate_hash") != storyboard_hash
        or visual.get("shot_count") != len(director["shots"])
    ):
        raise _director_error("Custom Film admission gates do not bind together")
    clip_by_shot = {
        str(row["shot_id"]): str(row["clip_artifact_id"])
        for row in visual["approved_verifications"]
    }
    if set(clip_by_shot) != {str(shot["shot_id"]) for shot in director["shots"]}:
        raise _director_error("Custom Film approved clip set is incomplete")
    manifest = {
        "admission_version": 1,
        "director_contract_hash": director["contract_hash"],
        "storyboard_gate_hash": storyboard_hash,
        "visual_gate_hash": visual_hash,
        "fps": director["fps"],
        "total_frames": director["total_frames"],
        "shots": [
            {
                "shot_id": shot["shot_id"],
                "shot_key": shot["shot_key"],
                "section_id": shot["section_id"],
                "order_index": shot["order_index"],
                "start_frame": shot["start_frame"],
                "end_frame": shot["end_frame"],
                "duration_frames": shot["duration_frames"],
                "technique": shot["technique"],
                "performance_mode": shot["performance_mode"],
                "clip_artifact_id": clip_by_shot[str(shot["shot_id"])],
                "spoken_lines": copy.deepcopy(shot["spoken_lines"]),
                "screen_direction": shot["screen_direction"],
                "camera_move": shot["camera_move"],
                "shot_hash": shot["shot_hash"],
            }
            for shot in director["shots"]
        ],
    }
    manifest["admission_hash"] = canonical_hash(manifest)
    return manifest


class StageOperation(_StrictModel):
    operation_kind: str = Field(min_length=2, max_length=120)
    count: int = Field(ge=0, le=100_000)
    unit_max_cents: int = Field(ge=0, le=100_000_000)
    helper_operation: bool = False


class StageAuthority(_StrictModel):
    stage: Literal[
        "script_director",
        "storyboards",
        "final_pictures",
        "animation_voice",
        "assembly",
    ]
    stage_binding_hash: str
    upstream_gate_hash: str
    quote_hash: str
    prior_cumulative_cents: int = Field(ge=0)
    approved_cumulative_cents: int = Field(ge=0)
    operations: tuple[StageOperation, ...] = Field(min_length=1, max_length=200)

    @field_validator(
        "stage_binding_hash",
        "upstream_gate_hash",
        "quote_hash",
    )
    @classmethod
    def validate_hashes(cls, value: str) -> str:
        return _hash(value, "stage authority hash")


def compile_stage_authority(
    raw: Mapping[str, Any],
    *,
    expected_stage: str,
    expected_binding_hash: str,
    expected_upstream_gate_hash: str,
) -> dict[str, Any]:
    """Bind one exact cumulative approval to one explicit stage bill of materials."""
    try:
        authority = StageAuthority.model_validate(raw)
    except (ValueError, TypeError) as exc:
        raise _director_error(
            f"Custom Film stage authority is invalid: {exc}"
        ) from exc
    if expected_stage not in STAGE_SEQUENCE or authority.stage != expected_stage:
        raise _director_error("Custom Film spend stage changed")
    if (
        authority.stage_binding_hash != expected_binding_hash
        or authority.upstream_gate_hash != expected_upstream_gate_hash
    ):
        raise _director_error("Custom Film spend authority is stale")
    if len({row.operation_kind for row in authority.operations}) != len(
        authority.operations
    ):
        raise _director_error("Custom Film stage bill of materials is duplicated")
    stage_max_cents = sum(
        row.count * row.unit_max_cents for row in authority.operations
    )
    exact_required = authority.prior_cumulative_cents + stage_max_cents
    if authority.approved_cumulative_cents != exact_required:
        raise _director_error(
            "Custom Film approval is not the exact cumulative stage amount"
        )
    payload = authority.model_dump(mode="json")
    payload["stage_max_cents"] = stage_max_cents
    payload["authority_hash"] = canonical_hash(payload)
    return payload
