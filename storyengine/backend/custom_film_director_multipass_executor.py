"""No-provider-wired executor for the Custom Film multipass director contract.

The executor accepts only an explicit single-attempt text protocol and an
append-only receipt journal. StoryEngine does not provide a production adapter
here; tests use fakes. An unresolved started receipt is never retried.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal, Protocol
from uuid import UUID

from custom_film_contract import (
    CustomFilmContractError,
    canonical_hash,
    canonical_json,
)
from custom_film_director import (
    DIRECTOR_FPS,
    FilmBible,
    ShotDraft,
    compile_director_contract,
    validate_director_contract,
)
from custom_film_director_multipass import (
    INITIAL_OPERATION_KINDS,
    MULTIPASS_EXECUTION_MODEL,
    REPAIR_OPERATION_KINDS,
    validate_multipass_stage_contract,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TERMINAL_EVENT_KINDS = frozenset({"attempt_completed", "attempt_failed"})
NANOUSD_PER_CENT = 10_000_000


def _executor_error(message: str) -> CustomFilmContractError:
    return CustomFilmContractError(
        f"{message}; no storyboard, image, animation, voice, render, or upload "
        "was started"
    )


class DirectorReconciliationRequired(CustomFilmContractError):
    """A text attempt may have spent and must not be repeated automatically."""


class SingleAttemptTextClient(Protocol):
    """Future adapters must issue exactly one external request per invocation."""

    async def execute_once(
        self,
        *,
        operation: Mapping[str, Any],
        prompt: str,
        system_prompt: str,
        max_tokens: int,
    ) -> Mapping[str, Any]: ...


class DirectorCallJournal(Protocol):
    """Append-only claim and terminal-receipt boundary."""

    async def claim(self, operation: Mapping[str, Any]) -> Mapping[str, Any]: ...

    async def complete(
        self,
        operation: Mapping[str, Any],
        result: Mapping[str, Any],
        output_payload: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...

    async def fail(
        self,
        operation: Mapping[str, Any],
        result: Mapping[str, Any],
        *,
        failure_code: str,
        output_payload: Mapping[str, Any] | None,
    ) -> Mapping[str, Any]: ...

    def events(self) -> Sequence[Mapping[str, Any]]: ...


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        frozen=True,
    )


class ShotOutlineRow(_StrictModel):
    shot_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
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
    opening_story_fact: str = Field(min_length=10, max_length=1_000)
    closing_story_fact: str = Field(min_length=10, max_length=1_000)
    environment_id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    character_ids: tuple[str, ...] = Field(min_length=1, max_length=20)

    @field_validator("caused_by", "progression_kinds", "character_ids")
    @classmethod
    def unique_values(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("Outline bindings must be unique")
        return value

    @model_validator(mode="after")
    def performance_matches_technique(self) -> ShotOutlineRow:
        if self.performance_mode == "dialogue" and self.technique != "poco_dialogue":
            raise ValueError("Dialogue outline rows use the Poco technique")
        if self.performance_mode == "exposition" and self.technique not in {
            "dvsu_documentary",
            "power_doctrine_exposition",
        }:
            raise ValueError("Exposition outline rows use evidence or doctrine")
        if (
            self.performance_mode == "silent_action"
            and self.technique != "cinematic_action"
        ):
            raise ValueError("Silent outline rows use cinematic action")
        if self.opening_story_fact == self.closing_story_fact:
            raise ValueError("Every outline row must advance story state")
        return self


class ShotOutlineDraft(_StrictModel):
    shots: tuple[ShotOutlineRow, ...] = Field(min_length=1, max_length=2_000)


def build_director_call_event(
    operation: Mapping[str, Any],
    *,
    event_kind: str,
    result: Mapping[str, Any] | None = None,
    output_payload: Mapping[str, Any] | None = None,
    failure_code: str | None = None,
) -> dict[str, Any]:
    actual_cost_cents = int(result.get("actual_cost_cents") or 0) if result else 0
    actual_cost_nusd = (
        int(
            result.get(
                "actual_cost_nusd",
                actual_cost_cents * NANOUSD_PER_CENT,
            )
        )
        if result
        else 0
    )
    payload = {
        "event_version": 1,
        "execution_model": MULTIPASS_EXECUTION_MODEL,
        "operation_id": operation["operation_id"],
        "operation_kind": operation["operation_kind"],
        "input_hash": operation["input_hash"],
        "event_kind": event_kind,
        "request_id": result.get("request_id") if result else None,
        "model": result.get("model") if result else None,
        "input_tokens": result.get("input_tokens") if result else None,
        "output_tokens": result.get("output_tokens") if result else None,
        "actual_cost_nusd": actual_cost_nusd,
        "actual_cost_cents": actual_cost_cents,
        "finish_reason": result.get("finish_reason") if result else None,
        "output_payload": (
            copy.deepcopy(dict(output_payload)) if output_payload is not None else None
        ),
        "output_hash": (
            canonical_hash(output_payload) if output_payload is not None else None
        ),
        "failure_code": failure_code,
    }
    payload["event_hash"] = canonical_hash(payload)
    return payload


class InMemoryDirectorCallJournal:
    """Reference receipt semantics for tests and future durable adapters."""

    def __init__(self, events: Sequence[Mapping[str, Any]] | None = None):
        self._events = [copy.deepcopy(dict(row)) for row in (events or ())]
        self._validate_all()

    def _validate_all(self) -> None:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for raw in self._events:
            row = copy.deepcopy(raw)
            claimed_hash = row.pop("event_hash", None)
            if claimed_hash != canonical_hash(row):
                raise _executor_error("Custom Film director receipt changed")
            operation_id = str(row.get("operation_id") or "")
            grouped.setdefault(operation_id, []).append(raw)
        for rows in grouped.values():
            kinds = [str(row.get("event_kind") or "") for row in rows]
            if (
                not kinds
                or kinds[0] != "attempt_started"
                or len(kinds) > 2
                or len(kinds) == 2
                and kinds[1] not in TERMINAL_EVENT_KINDS
            ):
                raise _executor_error("Custom Film director receipt order is invalid")

    def _rows(self, operation_id: str) -> list[dict[str, Any]]:
        return [row for row in self._events if row["operation_id"] == operation_id]

    async def claim(self, operation: Mapping[str, Any]) -> Mapping[str, Any]:
        rows = self._rows(str(operation["operation_id"]))
        if not rows:
            started = build_director_call_event(
                operation,
                event_kind="attempt_started",
            )
            self._events.append(started)
            return {"status": "claimed", "event": copy.deepcopy(started)}
        if rows[0].get("input_hash") != operation.get("input_hash") or rows[0].get(
            "operation_kind"
        ) != operation.get("operation_kind"):
            raise _executor_error("Custom Film director receipt input changed")
        if len(rows) == 1:
            return {
                "status": "reconciliation_required",
                "event": copy.deepcopy(rows[0]),
            }
        terminal = copy.deepcopy(rows[1])
        if terminal["event_kind"] == "attempt_completed":
            return {"status": "completed", "event": terminal}
        return {"status": "failed", "event": terminal}

    async def complete(
        self,
        operation: Mapping[str, Any],
        result: Mapping[str, Any],
        output_payload: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        rows = self._rows(str(operation["operation_id"]))
        if len(rows) != 1 or rows[0]["event_kind"] != "attempt_started":
            raise _executor_error("Custom Film director completion is not claim-bound")
        completed = build_director_call_event(
            operation,
            event_kind="attempt_completed",
            result=result,
            output_payload=output_payload,
        )
        self._events.append(completed)
        return copy.deepcopy(completed)

    async def fail(
        self,
        operation: Mapping[str, Any],
        result: Mapping[str, Any],
        *,
        failure_code: str,
        output_payload: Mapping[str, Any] | None,
    ) -> Mapping[str, Any]:
        rows = self._rows(str(operation["operation_id"]))
        if len(rows) != 1 or rows[0]["event_kind"] != "attempt_started":
            raise _executor_error("Custom Film director failure is not claim-bound")
        failed = build_director_call_event(
            operation,
            event_kind="attempt_failed",
            result=result,
            output_payload=output_payload,
            failure_code=failure_code,
        )
        self._events.append(failed)
        return copy.deepcopy(failed)

    def events(self) -> Sequence[Mapping[str, Any]]:
        return copy.deepcopy(self._events)


def _strict_json(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, str) or not raw.strip():
        raise _executor_error("Custom Film director response is empty")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _executor_error(
            "Custom Film director response is not complete JSON"
        ) from exc
    if not isinstance(value, dict):
        raise _executor_error("Custom Film director response is not an object")
    return value


def _normalized_result(
    raw: Mapping[str, Any],
    operation: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise _executor_error("Custom Film director attempt receipt is invalid")
    result = copy.deepcopy(dict(raw))
    for field in ("request_id", "model", "text", "finish_reason"):
        if not isinstance(result.get(field), str) or not result[field].strip():
            raise _executor_error("Custom Film director attempt receipt is incomplete")
    for field in (
        "attempt_count",
        "input_tokens",
        "output_tokens",
        "actual_cost_nusd",
        "actual_cost_cents",
    ):
        if field == "actual_cost_nusd" and field not in result:
            result[field] = int(result.get("actual_cost_cents") or 0) * NANOUSD_PER_CENT
        if type(result.get(field)) is not int or result[field] < 0:
            raise _executor_error("Custom Film director attempt usage is invalid")
    if result["attempt_count"] != 1:
        raise _executor_error("Custom Film director adapter hid multiple attempts")
    if result["actual_cost_cents"] > int(operation["unit_max_cents"]):
        raise _executor_error("Custom Film director operation exceeded its ceiling")
    if (
        result["actual_cost_cents"]
        != (result["actual_cost_nusd"] + NANOUSD_PER_CENT - 1) // NANOUSD_PER_CENT
    ):
        raise _executor_error("Custom Film director exact cost does not reconcile")
    if result["output_tokens"] > int(operation["max_tokens"]):
        raise _executor_error(
            "Custom Film director response exceeded its token ceiling"
        )
    return result


def _conservative_failure_result(
    raw: Any,
    operation: Mapping[str, Any],
) -> dict[str, Any]:
    value = dict(raw) if isinstance(raw, Mapping) else {}

    def exact_nonnegative_int(field: str, fallback: int) -> int:
        observed = value.get(field)
        return observed if type(observed) is int and observed >= 0 else fallback

    return {
        "request_id": str(value.get("request_id") or "unknown"),
        "model": str(value.get("model") or "unknown"),
        "attempt_count": exact_nonnegative_int("attempt_count", 0),
        "input_tokens": exact_nonnegative_int("input_tokens", 0),
        "output_tokens": exact_nonnegative_int(
            "output_tokens",
            int(operation["max_tokens"]),
        ),
        # A malformed receipt cannot prove a lower actual charge. Preserve the
        # full authorized unit as conservative exposure until reconciliation.
        "actual_cost_cents": exact_nonnegative_int(
            "actual_cost_cents",
            int(operation["unit_max_cents"]),
        ),
        "actual_cost_nusd": exact_nonnegative_int(
            "actual_cost_nusd",
            exact_nonnegative_int(
                "actual_cost_cents",
                int(operation["unit_max_cents"]),
            )
            * NANOUSD_PER_CENT,
        ),
        "finish_reason": str(value.get("finish_reason") or "unknown"),
        "text": str(value.get("text") or ""),
    }


def _completed_output(event: Mapping[str, Any]) -> dict[str, Any]:
    payload = event.get("output_payload")
    if not isinstance(payload, Mapping) or canonical_hash(payload) != event.get(
        "output_hash"
    ):
        raise _executor_error("Custom Film director stored output changed")
    return copy.deepcopy(dict(payload))


def _film_bible_payload(raw: Mapping[str, Any]) -> dict[str, Any]:
    try:
        value = FilmBible.model_validate(raw.get("film_bible"))
    except (ValueError, TypeError) as exc:
        raise _executor_error("Custom Film film bible is invalid") from exc
    return {"film_bible": value.model_dump(mode="json")}


def _outline_payload(
    raw: Mapping[str, Any],
    *,
    film_bible: Mapping[str, Any],
    planning: Mapping[str, Any],
    fps: int,
) -> dict[str, Any]:
    try:
        outline = ShotOutlineDraft.model_validate(raw)
    except (ValueError, TypeError) as exc:
        raise _executor_error("Custom Film shot outline is invalid") from exc
    shots = list(outline.shots)
    total_shots = planning["totals"]["planned_shots"]
    if len(shots) != total_shots:
        raise _executor_error("Custom Film shot outline count changed")
    shot_keys = [row.shot_key for row in shots]
    if len(shot_keys) != len(set(shot_keys)):
        raise _executor_error("Custom Film shot outline keys are duplicated")
    section_ids = [section["section_id"] for section in planning["sections"]]
    section_frames = {
        section["section_id"]: section["duration_seconds"] * fps
        for section in planning["sections"]
    }
    section_shots = {
        section["section_id"]: section["planned_shots"]
        for section in planning["sections"]
    }
    actual_section_frames = {
        section_id: sum(
            row.duration_frames for row in shots if str(row.section_id) == section_id
        )
        for section_id in section_ids
    }
    actual_section_shots = {
        section_id: sum(1 for row in shots if str(row.section_id) == section_id)
        for section_id in section_ids
    }
    if (
        actual_section_frames != section_frames
        or actual_section_shots != section_shots
        or sum(row.duration_frames for row in shots)
        != planning["totals"]["duration_seconds"] * fps
    ):
        raise _executor_error("Custom Film shot outline timing changed")
    characters = {str(row["character_id"]) for row in film_bible["characters"]}
    environments = {str(row["environment_id"]) for row in film_bible["environments"]}
    seen: set[str] = set()
    previous: ShotOutlineRow | None = None
    used_sections: list[str] = []
    for index, row in enumerate(shots):
        section_id = str(row.section_id)
        if section_id not in section_ids:
            raise _executor_error("Custom Film shot outline section changed")
        if used_sections and section_ids.index(section_id) < section_ids.index(
            used_sections[-1]
        ):
            raise _executor_error("Custom Film shot outline moves backward")
        used_sections.append(section_id)
        if row.environment_id not in environments or not set(
            row.character_ids
        ).issubset(characters):
            raise _executor_error("Custom Film shot outline uses an unlocked identity")
        if index == 0:
            if row.caused_by:
                raise _executor_error("Custom Film shot outline opening has a cause")
        elif not row.caused_by or not set(row.caused_by).issubset(seen):
            raise _executor_error("Custom Film shot outline has no earlier cause")
        if previous and row.opening_story_fact != previous.closing_story_fact:
            raise _executor_error("Custom Film shot outline breaks story progression")
        seen.add(row.shot_key)
        previous = row
    if set(used_sections) != set(section_ids):
        raise _executor_error("Custom Film shot outline omits a section")
    if shots[0].opening_story_fact != film_bible["beginning_state"]:
        raise _executor_error("Custom Film shot outline changed the beginning")
    if shots[-1].closing_story_fact != film_bible["ending_state"]:
        raise _executor_error("Custom Film shot outline changed the ending")
    return {"shots": [row.model_dump(mode="json") for row in shots]}


def _batch_payload(
    raw: Mapping[str, Any],
    *,
    operation: Mapping[str, Any],
    film_bible: Mapping[str, Any],
    outline: Mapping[str, Any],
    accepted_shots: Sequence[Mapping[str, Any]],
    plan_id: str,
    plan_hash: str,
    fps: int,
) -> dict[str, Any]:
    rows = raw.get("shots")
    if not isinstance(rows, list):
        raise _executor_error("Custom Film shot batch is invalid")
    start = operation["shot_start_index"]
    end = operation["shot_end_index"]
    expected_outline = outline["shots"][start : end + 1]
    if len(rows) != len(expected_outline):
        raise _executor_error("Custom Film shot batch count changed")
    try:
        parsed = [ShotDraft.model_validate(row) for row in rows]
    except (ValueError, TypeError) as exc:
        raise _executor_error("Custom Film shot batch contract is invalid") from exc
    for shot, expected in zip(parsed, expected_outline, strict=True):
        exact_fields = {
            "shot_key": shot.shot_key,
            "section_id": str(shot.section_id),
            "duration_frames": shot.duration_frames,
            "technique": shot.technique,
            "performance_mode": shot.performance_mode,
            "narrative_purpose": shot.narrative_purpose,
            "caused_by": list(shot.caused_by),
            "progression_kinds": list(shot.progression_kinds),
            "story_value": shot.story_value,
            "opening_story_fact": shot.opening_state.story_facts[0],
            "closing_story_fact": shot.closing_state.story_facts[-1],
            "environment_id": shot.environment_id,
            "character_ids": list(shot.character_ids),
        }
        normalized_expected = {
            **expected,
            "section_id": str(expected["section_id"]),
        }
        if canonical_json(exact_fields) != canonical_json(normalized_expected):
            raise _executor_error("Custom Film shot batch drifted from its outline")

    prefix_rows = [copy.deepcopy(dict(row)) for row in accepted_shots] + [
        shot.model_dump(mode="json") for shot in parsed
    ]
    prefix_bible = copy.deepcopy(dict(film_bible))
    prefix_bible["ending_state"] = prefix_rows[-1]["closing_state"]["story_facts"][-1]
    prefix_section_ids: list[str] = []
    for row in prefix_rows:
        section_id = str(row["section_id"])
        if section_id not in prefix_section_ids:
            prefix_section_ids.append(section_id)
    prefix_frames = {
        section_id: sum(
            int(row["duration_frames"])
            for row in prefix_rows
            if str(row["section_id"]) == section_id
        )
        for section_id in prefix_section_ids
    }
    prefix_counts = {
        section_id: sum(
            1 for row in prefix_rows if str(row["section_id"]) == section_id
        )
        for section_id in prefix_section_ids
    }
    compile_director_contract(
        {"film_bible": prefix_bible, "shots": prefix_rows},
        plan_id=plan_id,
        plan_hash=plan_hash,
        section_ids=prefix_section_ids,
        total_frames=sum(prefix_frames.values()),
        section_frame_counts=prefix_frames,
        section_shot_counts=prefix_counts,
        fps=fps,
    )
    return {"shots": [shot.model_dump(mode="json") for shot in parsed]}


def _prompt(
    operation: Mapping[str, Any],
    *,
    user_request: str,
    planning: Mapping[str, Any],
    film_bible: Mapping[str, Any] | None,
    outline: Mapping[str, Any] | None,
    accepted_shots: Sequence[Mapping[str, Any]],
    prior_candidate: Mapping[str, Any] | None,
    prior_failure: str | None,
) -> tuple[str, str]:
    kind = str(operation["operation_kind"])
    context: dict[str, Any] = {
        "creator_request": user_request,
        "planning_contract": planning,
        "operation_contract": operation["input_payload"],
    }
    if film_bible is not None:
        context["locked_film_bible"] = film_bible
    if outline is not None:
        if kind in {"shot_batch", "shot_batch_repair"}:
            start = operation["shot_start_index"]
            end = operation["shot_end_index"]
            context["approved_outline_slice"] = outline["shots"][start : end + 1]
            context["previous_accepted_shot"] = (
                accepted_shots[-1] if accepted_shots else None
            )
        else:
            context["approved_outline"] = outline
    if prior_candidate is not None:
        context["invalid_candidate"] = prior_candidate
        context["validation_failure"] = prior_failure

    if kind in {"film_bible", "film_bible_repair"}:
        schema = {"film_bible": FilmBible.model_json_schema()}
        assignment = (
            "Return one immutable film bible. Lock one style, cast, wardrobe, "
            "voices, environments, props, geography, timeline, beginning, and ending."
        )
    elif kind in {"shot_outline", "shot_outline_repair"}:
        schema = ShotOutlineDraft.model_json_schema()
        assignment = (
            "Return the complete ordered shot spine. Every shot changes the story; "
            "Poco dialogue, documentary evidence, Power Doctrine exposition, and "
            "silent action are selected by narrative need under the film-bible locks."
        )
    else:
        schema = {"shots": {"items": ShotDraft.model_json_schema()}}
        assignment = (
            "Return only this approved shot batch as complete ShotDraft records. "
            "Match every outline field exactly and preserve prior closing state."
        )
    prompt = (
        f"{assignment}\nReturn exactly one complete JSON object and no markdown.\n"
        f"SCHEMA:\n{canonical_json(schema)}\n"
        f"CONTEXT:\n{canonical_json(context)}"
    )
    system_prompt = (
        "You are the screenplay writer, storyboard planner, and continuity "
        "director for one locked film. Make one single response. Never mention "
        "providers, prices, approvals, or generation."
    )
    return prompt, system_prompt


def _receipt_result(event: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "request_id": event.get("request_id"),
        "model": event.get("model"),
        "attempt_count": 1,
        "input_tokens": event.get("input_tokens"),
        "output_tokens": event.get("output_tokens"),
        "actual_cost_cents": event.get("actual_cost_cents"),
        "actual_cost_nusd": event.get("actual_cost_nusd"),
        "finish_reason": event.get("finish_reason"),
        "text": "",
    }


async def _attempt(
    operation: Mapping[str, Any],
    *,
    client: SingleAttemptTextClient,
    journal: DirectorCallJournal,
    prompt: str,
    system_prompt: str,
    validate: Callable[[Mapping[str, Any]], dict[str, Any]],
) -> tuple[str, dict[str, Any], str | None]:
    claim = await journal.claim(operation)
    status = claim.get("status")
    event = claim.get("event")
    if status == "reconciliation_required":
        raise DirectorReconciliationRequired(
            "Custom Film director attempt needs spend reconciliation"
        )
    if status == "completed":
        output = _completed_output(event)
        return "valid", validate(output), None
    if status == "failed":
        if event.get("failure_code") == "authorization_violation":
            raise DirectorReconciliationRequired(
                "Custom Film director authorization violation needs spend "
                "reconciliation"
            )
        output = event.get("output_payload")
        return (
            "invalid",
            copy.deepcopy(dict(output)) if isinstance(output, Mapping) else {},
            str(event.get("failure_code") or "stored_validation_failure"),
        )
    if status != "claimed":
        raise _executor_error("Custom Film director claim state is invalid")

    try:
        raw_result = await client.execute_once(
            operation=copy.deepcopy(dict(operation)),
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=int(operation["max_tokens"]),
        )
    except Exception as exc:
        raise DirectorReconciliationRequired(
            "Custom Film director attempt ended without a terminal receipt"
        ) from exc

    try:
        result = _normalized_result(raw_result, operation)
    except CustomFilmContractError as exc:
        # A returned receipt proves the attempt happened, but hidden retries or
        # over-ceiling usage are authorization failures, not repair candidates.
        fallback = _conservative_failure_result(raw_result, operation)
        await journal.fail(
            operation,
            fallback,
            failure_code="authorization_violation",
            output_payload=None,
        )
        raise DirectorReconciliationRequired(
            f"{exc}; spend reconciliation is required"
        ) from exc

    candidate: dict[str, Any] | None = None
    failure_code: str | None = None
    try:
        if result["finish_reason"] != "stop":
            failure_code = "incomplete_response"
            raise _executor_error("Custom Film director response was truncated")
        candidate = _strict_json(result["text"])
        output = validate(candidate)
    except CustomFilmContractError as exc:
        failure_code = failure_code or "validation_failure"
        await journal.fail(
            operation,
            result,
            failure_code=failure_code,
            output_payload=candidate,
        )
        return "invalid", candidate or {}, str(exc)
    await journal.complete(operation, result, output)
    return "valid", output, None


async def _attempt_with_repair(
    initial: Mapping[str, Any],
    repair: Mapping[str, Any],
    *,
    client: SingleAttemptTextClient,
    journal: DirectorCallJournal,
    prompt_factory: Callable[
        [Mapping[str, Any] | None, str | None],
        tuple[str, str],
    ],
    validate: Callable[[Mapping[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    prompt, system_prompt = prompt_factory(None, None)
    status, output, failure = await _attempt(
        initial,
        client=client,
        journal=journal,
        prompt=prompt,
        system_prompt=system_prompt,
        validate=validate,
    )
    if status == "valid":
        return output
    repair_prompt, repair_system = prompt_factory(output, failure)
    repaired_status, repaired_output, repaired_failure = await _attempt(
        repair,
        client=client,
        journal=journal,
        prompt=repair_prompt,
        system_prompt=repair_system,
        validate=validate,
    )
    if repaired_status != "valid":
        detail = repaired_failure or "invalid output"
        raise _executor_error(
            f"Custom Film director repair failed: {detail}"
        )
    return repaired_output


def _operation_pairs(
    operations: Sequence[Mapping[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    initial_by_id = {
        str(row["operation_id"]): copy.deepcopy(dict(row))
        for row in operations
        if row["operation_kind"] in INITIAL_OPERATION_KINDS
    }
    repair_by_initial = {
        str(row["repairs_operation_id"]): copy.deepcopy(dict(row))
        for row in operations
        if row["operation_kind"] in REPAIR_OPERATION_KINDS
    }
    if len(initial_by_id) * 2 != len(operations) or set(initial_by_id) != set(
        repair_by_initial
    ):
        raise _executor_error("Custom Film director operation pairs changed")
    return [(row, repair_by_initial[row_id]) for row_id, row in initial_by_id.items()]


def _journal_spend(events: Sequence[Mapping[str, Any]]) -> int:
    return sum(
        int(row.get("actual_cost_cents") or 0)
        for row in events
        if row.get("event_kind") in TERMINAL_EVENT_KINDS
    )


async def execute_multipass_director(
    *,
    stage_contract: Mapping[str, Any],
    user_request: str,
    client: SingleAttemptTextClient,
    journal: DirectorCallJournal,
    fps: int = DIRECTOR_FPS,
) -> dict[str, Any]:
    """Execute only an already-approved v2 manifest through supplied fakes/adapters."""
    if not isinstance(user_request, str) or not user_request.strip():
        raise _executor_error("Custom Film creator request is missing")
    if client is None or journal is None:
        raise _executor_error("Custom Film director execution boundary is missing")
    contract = validate_multipass_stage_contract(stage_contract)
    manifest = contract["manifest"]
    schedule_by_id = {row["operation_id"]: row for row in contract["schedule"]["tasks"]}
    pairs = _operation_pairs(manifest["operations"])
    pairs = [
        (
            schedule_by_id[initial["operation_id"]],
            schedule_by_id[repair["operation_id"]],
        )
        for initial, repair in pairs
    ]
    planning = manifest["planning_contract"]
    plan_id = manifest["plan_id"]
    plan_hash = manifest["plan_hash"]
    film_bible: dict[str, Any] | None = None
    outline: dict[str, Any] | None = None
    accepted_shots: list[dict[str, Any]] = []

    for initial, repair in pairs:
        kind = initial["operation_kind"]

        def prompt_factory(
            prior_candidate: Mapping[str, Any] | None,
            prior_failure: str | None,
            _initial: Mapping[str, Any] = initial,
            _repair: Mapping[str, Any] = repair,
            _film_bible: Mapping[str, Any] | None = film_bible,
            _outline: Mapping[str, Any] | None = outline,
        ) -> tuple[str, str]:
            return _prompt(
                _repair if prior_candidate is not None else _initial,
                user_request=user_request,
                planning=planning,
                film_bible=_film_bible,
                outline=_outline,
                accepted_shots=accepted_shots,
                prior_candidate=prior_candidate,
                prior_failure=prior_failure,
            )

        if kind == "film_bible":
            result = await _attempt_with_repair(
                initial,
                repair,
                client=client,
                journal=journal,
                prompt_factory=prompt_factory,
                validate=_film_bible_payload,
            )
            film_bible = result["film_bible"]
        elif kind == "shot_outline":
            if film_bible is None:
                raise _executor_error("Custom Film film bible is not available")

            def validate_outline(
                raw: Mapping[str, Any],
                _film_bible: Mapping[str, Any] = film_bible,
            ) -> dict[str, Any]:
                return _outline_payload(
                    raw,
                    film_bible=_film_bible,
                    planning=planning,
                    fps=fps,
                )

            outline = await _attempt_with_repair(
                initial,
                repair,
                client=client,
                journal=journal,
                prompt_factory=prompt_factory,
                validate=validate_outline,
            )
        else:
            if film_bible is None or outline is None:
                raise _executor_error("Custom Film shot dependencies are not available")

            def validate_batch(
                raw: Mapping[str, Any],
                _initial: Mapping[str, Any] = initial,
                _film_bible: Mapping[str, Any] = film_bible,
                _outline: Mapping[str, Any] = outline,
            ) -> dict[str, Any]:
                return _batch_payload(
                    raw,
                    operation=_initial,
                    film_bible=_film_bible,
                    outline=_outline,
                    accepted_shots=accepted_shots,
                    plan_id=plan_id,
                    plan_hash=plan_hash,
                    fps=fps,
                )

            result = await _attempt_with_repair(
                initial,
                repair,
                client=client,
                journal=journal,
                prompt_factory=prompt_factory,
                validate=validate_batch,
            )
            accepted_shots.extend(result["shots"])

    if film_bible is None or outline is None:
        raise _executor_error("Custom Film director execution is incomplete")
    sections = planning["sections"]
    director = compile_director_contract(
        {"film_bible": film_bible, "shots": accepted_shots},
        plan_id=plan_id,
        plan_hash=plan_hash,
        section_ids=[row["section_id"] for row in sections],
        total_frames=planning["totals"]["duration_seconds"] * fps,
        section_frame_counts={
            row["section_id"]: row["duration_seconds"] * fps for row in sections
        },
        section_shot_counts={
            row["section_id"]: row["planned_shots"] for row in sections
        },
        fps=fps,
    )
    events = list(journal.events())
    spend_cents = _journal_spend(events)
    if spend_cents > contract["stage_quote"]["stage_max_cents"]:
        raise _executor_error("Custom Film director receipts exceeded stage authority")
    return {
        "execution_model": MULTIPASS_EXECUTION_MODEL,
        "manifest_hash": manifest["manifest_hash"],
        "authority_hash": contract["authority_hash"],
        "director_contract": director,
        "director_contract_hash": director["contract_hash"],
        "initial_operation_count": manifest["initial_model_calls"],
        "repair_operation_count": sum(
            row.get("event_kind") in TERMINAL_EVENT_KINDS
            and row.get("operation_kind") in REPAIR_OPERATION_KINDS
            for row in events
        ),
        "terminal_call_count": sum(
            row.get("event_kind") in TERMINAL_EVENT_KINDS for row in events
        ),
        "actual_spend_cents": spend_cents,
        "receipt_events": events,
        "execution_hash": canonical_hash(
            {
                "manifest_hash": manifest["manifest_hash"],
                "authority_hash": contract["authority_hash"],
                "director_contract_hash": director["contract_hash"],
                "receipt_event_hashes": [row["event_hash"] for row in events],
                "actual_spend_cents": spend_cents,
            }
        ),
    }


def validate_multipass_execution_result(
    raw: Mapping[str, Any],
    *,
    stage_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate one complete execution before durable director persistence."""
    if not isinstance(raw, Mapping):
        raise _executor_error("Custom Film director execution result is invalid")
    result = copy.deepcopy(dict(raw))
    expected_keys = {
        "execution_model",
        "manifest_hash",
        "authority_hash",
        "director_contract",
        "director_contract_hash",
        "initial_operation_count",
        "repair_operation_count",
        "terminal_call_count",
        "actual_spend_cents",
        "receipt_events",
        "execution_hash",
    }
    if set(result) != expected_keys:
        raise _executor_error("Custom Film director execution result shape changed")
    approved = validate_multipass_stage_contract(stage_contract)
    manifest = approved["manifest"]
    if (
        result.get("execution_model") != MULTIPASS_EXECUTION_MODEL
        or result.get("manifest_hash") != manifest["manifest_hash"]
        or result.get("authority_hash") != approved["authority_hash"]
    ):
        raise _executor_error("Custom Film director execution binding changed")
    director = validate_director_contract(
        result.get("director_contract"),
        expected_plan_hash=manifest["plan_hash"],
    )
    if result.get("director_contract_hash") != director["contract_hash"]:
        raise _executor_error("Custom Film director execution contract changed")

    events = result.get("receipt_events")
    if not isinstance(events, list):
        raise _executor_error("Custom Film director receipt evidence is invalid")
    InMemoryDirectorCallJournal(events)
    operations = {row["operation_id"]: row for row in approved["schedule"]["tasks"]}
    event_groups: dict[str, list[Mapping[str, Any]]] = {}
    for event in events:
        operation = operations.get(str(event.get("operation_id") or ""))
        if (
            operation is None
            or event.get("operation_kind") != operation["operation_kind"]
            or event.get("input_hash") != operation["input_hash"]
        ):
            raise _executor_error("Custom Film director receipt is not authorized")
        actual_cost = event.get("actual_cost_cents")
        actual_cost_nusd = event.get("actual_cost_nusd")
        if (
            type(actual_cost) is not int
            or actual_cost < 0
            or actual_cost > int(operation["unit_max_cents"])
            or type(actual_cost_nusd) is not int
            or actual_cost_nusd < 0
            or actual_cost
            != (actual_cost_nusd + NANOUSD_PER_CENT - 1) // NANOUSD_PER_CENT
        ):
            raise _executor_error("Custom Film director receipt cost is unauthorized")
        if event.get("event_kind") == "attempt_started":
            if (
                actual_cost != 0
                or event.get("output_payload") is not None
                or event.get("output_hash") is not None
            ):
                raise _executor_error("Custom Film director start receipt changed")
        else:
            output_payload = event.get("output_payload")
            output_hash = event.get("output_hash")
            if (
                output_payload is not None
                and canonical_hash(output_payload) != output_hash
            ):
                raise _executor_error("Custom Film director receipt output changed")
            if event.get("event_kind") == "attempt_completed" and not isinstance(
                output_payload, Mapping
            ):
                raise _executor_error(
                    "Custom Film director completion output is missing"
                )
        event_groups.setdefault(operation["operation_id"], []).append(event)

    initial_operations = [
        row
        for row in operations.values()
        if row["operation_kind"] in INITIAL_OPERATION_KINDS
    ]
    repair_by_initial = {
        row["repairs_operation_id"]: row
        for row in operations.values()
        if row["operation_kind"] in REPAIR_OPERATION_KINDS
    }
    used_repairs = 0
    for initial in initial_operations:
        initial_events = event_groups.get(initial["operation_id"], [])
        if (
            len(initial_events) != 2
            or initial_events[0]["event_kind"] != "attempt_started"
            or initial_events[1]["event_kind"] not in TERMINAL_EVENT_KINDS
        ):
            raise _executor_error("Custom Film director initial receipt is incomplete")
        repair = repair_by_initial.get(initial["operation_id"])
        if repair is None:
            raise _executor_error("Custom Film director repair authority changed")
        repair_events = event_groups.get(repair["operation_id"], [])
        if initial_events[1]["event_kind"] == "attempt_completed":
            if repair_events:
                raise _executor_error("Custom Film director used an unneeded repair")
            continue
        if initial_events[1].get("failure_code") not in {
            "validation_failure",
            "incomplete_response",
        }:
            raise _executor_error(
                "Custom Film director authorization failure cannot be repaired"
            )
        if (
            len(repair_events) != 2
            or repair_events[0]["event_kind"] != "attempt_started"
            or repair_events[1]["event_kind"] != "attempt_completed"
        ):
            raise _executor_error("Custom Film director repair receipt is incomplete")
        used_repairs += 1
    if any(
        operation["operation_kind"] in REPAIR_OPERATION_KINDS
        and operation_id
        not in {
            repair_by_initial[initial["operation_id"]]["operation_id"]
            for initial in initial_operations
            if event_groups.get(initial["operation_id"], [])[-1]["event_kind"]
            == "attempt_failed"
        }
        for operation_id, operation in operations.items()
        if event_groups.get(operation_id)
    ):
        raise _executor_error("Custom Film director repair receipt is unpaired")

    spend_cents = _journal_spend(events)
    terminal_calls = sum(
        row.get("event_kind") in TERMINAL_EVENT_KINDS for row in events
    )
    if (
        type(result.get("actual_spend_cents")) is not int
        or result["actual_spend_cents"] != spend_cents
        or spend_cents > approved["stage_quote"]["stage_max_cents"]
        or result.get("initial_operation_count") != len(initial_operations)
        or result.get("repair_operation_count") != used_repairs
        or result.get("terminal_call_count") != terminal_calls
    ):
        raise _executor_error(
            "Custom Film director execution receipts do not reconcile"
        )
    expected_execution_hash = canonical_hash(
        {
            "manifest_hash": manifest["manifest_hash"],
            "authority_hash": approved["authority_hash"],
            "director_contract_hash": director["contract_hash"],
            "receipt_event_hashes": [row["event_hash"] for row in events],
            "actual_spend_cents": spend_cents,
        }
    )
    if result.get("execution_hash") != expected_execution_hash:
        raise _executor_error("Custom Film director execution hash changed")
    result["director_contract"] = director
    return result
