from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

import actions
import custom_film_contract as contract
import custom_film_runtime as runtime


def _knobs(*, static: bool) -> dict:
    if static:
        return {
            "render_mode": "static_docu",
            "script_profile": "neutral_v1",
            "visual_profile": "neutral_v1",
            "image_density": {"mode": "per_item", "target": 3, "minimum": 2},
            "animation": {"enabled": False, "mode": "ken_burns"},
            "language": {"mode": "narrator"},
            "dubbing": {"enabled": False, "mode": "none"},
            "segmentation": {"mode": "item"},
            "camera": {"mode": "three_complementary_views"},
            "quality_laws": [
                "verified_reference",
                "variant_accuracy",
                "caption_grounding",
            ],
            "image_source": "generate",
        }
    return {
        "render_mode": "coverage",
        "script_profile": "power_doctrine_v2",
        "visual_profile": "cinematic_illustration",
        "image_density": {"mode": "visual_cue", "target_per_minute": 10},
        "animation": {"enabled": True, "mode": "grok_native"},
        "language": {"mode": "narrator"},
        "dubbing": {"enabled": False, "mode": "none"},
        "segmentation": {"mode": "visual_cue"},
        "camera": {"mode": "investigative_coverage"},
        "quality_laws": [
            "source_grounding",
            "visual_cue_fidelity",
            "motion_prompt_presence",
        ],
        "image_source": "generate",
    }


def _plan() -> dict:
    return {
        "schema_version": 1,
        "compatibility_version": "test-v1",
        "sections": [
            {
                "section_id": "00000000-0000-4000-8000-000000000001",
                "order_index": 0,
                "role": "evidence",
                "purpose": "Establish the evidence",
                "duration_units": 400_000,
                "knobs": _knobs(static=True),
                "provenance": {"render_mode": ["photo_documentary"]},
                "estimated_media": {},
            },
            {
                "section_id": "00000000-0000-4000-8000-000000000002",
                "order_index": 1,
                "role": "explanation",
                "purpose": "Explain the mechanism",
                "duration_units": 600_000,
                "knobs": _knobs(static=False),
                "provenance": {
                    "render_mode": ["animated_investigative_documentary"]
                },
                "estimated_media": {},
            },
        ],
    }


async def _compiled(seconds: int = 5):
    plan = _plan()
    quote = await actions.estimate_custom_film_plan(
        plan, total_duration_seconds=seconds
    )
    plan_digest = contract.plan_hash(plan)
    quote_digest = contract.canonical_hash(quote)
    approval = contract.approval_binding_hash(plan_digest, quote)
    compiled = runtime.compile_runtime_plan(
        video_id="video-1",
        plan_id="plan-1",
        normalized_plan=plan,
        quote_inputs=quote,
        expected_plan_hash=plan_digest,
        expected_quote_inputs_hash=quote_digest,
        expected_approval_hash=approval,
        max_spend=float(quote["totals"]["estimated_cost"]),
    )
    return compiled, plan, quote, approval


@pytest.mark.asyncio
async def test_compiler_carries_exact_seconds_ids_and_every_major_runtime_seam():
    compiled, _plan_value, quote, _approval = await _compiled(5)
    assert [section.section_id for section in compiled.sections] == [
        row["section_id"] for row in quote["sections"]
    ]
    assert [section.duration_seconds for section in compiled.sections] == [2, 3]
    assert sum(section.duration_seconds for section in compiled.sections) == 5
    static, animated = compiled.sections
    assert static.render_mode == "static_docu"
    assert static.script_profile == "neutral_v1"
    assert static.image_density["mode"] == "per_item"
    assert static.animation["enabled"] is False
    assert static.language["mode"] == "narrator"
    assert static.dialogue_audio == "voice_over"
    assert static.quality_laws == (
        "verified_reference",
        "variant_accuracy",
        "caption_grounding",
    )
    assert animated.render_mode == "coverage"
    assert animated.script_profile == "power_doctrine_v2"
    assert animated.visual_profile == "cinematic_illustration"
    assert animated.image_density["mode"] == "visual_cue"
    assert animated.animation["enabled"] is True
    assert animated.camera["mode"] == "investigative_coverage"
    stages = [(row["section_id"], row["stage"]) for row in compiled.stage_plan()]
    assert stages == [
        (static.section_id, "script"),
        (animated.section_id, "script"),
        (static.section_id, "voice"),
        (static.section_id, "pictures"),
        (static.section_id, "quality"),
        (animated.section_id, "voice"),
        (animated.section_id, "pictures"),
        (animated.section_id, "motion"),
        (animated.section_id, "clips"),
        (animated.section_id, "quality"),
    ]


@pytest.mark.asyncio
async def test_compiler_pins_approved_visual_beats_into_runtime_sections():
    plan = _plan()
    quote = await actions.estimate_custom_film_plan(
        plan,
        total_duration_seconds=30,
    )
    quote["orchestration"] = {
        "approved_beat_plan": {
            "recipes": [
                {
                    "sectionIndex": 1,
                    "narrativeFunction": "reveal",
                    "presentation": "NetworkExplainer",
                    "requestedCapabilities": [
                        "media.approved_primary",
                        "motion.network_explainer",
                        "motion.incident_timeline",
                    ],
                    "signals": {
                        "intents": ["network", "timeline", "recovery"],
                        "handoff": "network_to_master",
                    },
                    "transition": {"mode": "transform-carry"},
                }
            ]
        }
    }
    plan_digest = contract.plan_hash(plan)
    quote_digest = contract.canonical_hash(quote)
    approval = contract.approval_binding_hash(plan_digest, quote)

    compiled = runtime.compile_runtime_plan(
        video_id="video-1",
        plan_id="plan-1",
        normalized_plan=plan,
        quote_inputs=quote,
        expected_plan_hash=plan_digest,
        expected_quote_inputs_hash=quote_digest,
        expected_approval_hash=approval,
        max_spend=float(quote["totals"]["estimated_cost"]),
    )

    expected = (
        {
            "narrative_function": "reveal",
            "presentation": "NetworkExplainer",
            "intents": ("network", "timeline", "recovery"),
            "handoff": "network_to_master",
            "transition": "transform-carry",
            "motion_capabilities": (
                "motion.network_explainer",
                "motion.incident_timeline",
            ),
        },
    )
    assert compiled.sections[0].approved_visual_beats == ()
    assert compiled.sections[1].approved_visual_beats == expected
    assert compiled.envelope()["sections"][1]["approved_visual_beats"] == [
        {
            **expected[0],
            "intents": list(expected[0]["intents"]),
            "motion_capabilities": list(expected[0]["motion_capabilities"]),
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", ["seconds", "order", "hash", "cap", "source"])
async def test_compiler_fails_closed_before_a_schedule_for_unsupported_or_stale_input(
    tamper,
):
    _compiled_value, plan, quote, approval = await _compiled(30)
    plan_digest = contract.plan_hash(plan)
    quote_digest = contract.canonical_hash(quote)
    max_spend = float(quote["totals"]["estimated_cost"])
    if tamper == "seconds":
        quote["sections"][0]["duration_seconds"] += 1
        quote_digest = contract.canonical_hash(quote)
        approval = contract.approval_binding_hash(plan_digest, quote)
    elif tamper == "order":
        quote["sections"][0]["order_index"] = 9
        quote_digest = contract.canonical_hash(quote)
        approval = contract.approval_binding_hash(plan_digest, quote)
    elif tamper == "hash":
        plan["sections"][0]["purpose"] = "Changed after approval"
    elif tamper == "cap":
        max_spend = 0
    elif tamper == "source":
        plan["sections"][0]["knobs"]["image_source"] = "library"
        plan_digest = contract.plan_hash(plan)
        approval = contract.approval_binding_hash(plan_digest, quote)
    with pytest.raises(contract.CustomFilmContractError):
        runtime.compile_runtime_plan(
            video_id="video-1",
            plan_id="plan-1",
            normalized_plan=plan,
            quote_inputs=quote,
            expected_plan_hash=plan_digest,
            expected_quote_inputs_hash=quote_digest,
            expected_approval_hash=approval,
            max_spend=max_spend,
        )


class _Context:
    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *_args):
        return None


class _FakeConnection:
    def __init__(self, row):
        self.row = row
        self.task = None
        self.executed = []
        self.queries = []
    def transaction(self):
        context = _Context()
        context.value = self
        return context

    async def fetchrow(self, sql, *_args):
        self.queries.append(sql)
        if "SELECT v.custom_film_plan_id" in sql:
            return copy.deepcopy(self.row)
        if "SELECT job_id, runtime_envelope" in sql:
            if not self.task:
                return None
            if len(_args) >= 5 and (
                self.task["job_id"] != _args[2]
                or self.task["runtime_envelope"]["approval_hash"] != _args[3]
                or self.task["runtime_envelope"]["runtime_hash"] != _args[4]
            ):
                return None
            if len(_args) == 3 and (
                self.task["runtime_envelope"]["approval_hash"] != _args[2]
            ):
                return None
            return copy.deepcopy(self.task)
        if "INSERT INTO background_tasks" in sql:
            if self.task:
                return None
            self.task = {
                "id": "task-1",
                "job_id": _args[2],
                "runtime_envelope": __import__("json").loads(_args[3]),
            }
            return {"id": "task-1"}
        raise AssertionError(sql)

    async def execute(self, sql, *_args):
        self.executed.append((sql, _args))
        if "UPDATE videos" in sql:
            self.row["custom_film_approval_hash"] = None
            return "UPDATE 1"
        if "UPDATE custom_film_plans" in sql:
            self.row["approval_hash"] = None
            return "UPDATE 1"
        raise AssertionError(sql)


class _FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        context = _Context()
        context.value = self.conn
        return context


@pytest.mark.asyncio
async def test_schedule_transaction_consumes_both_approvals_and_replay_converges(
    monkeypatch,
):
    compiled, plan, quote, approval = await _compiled(30)
    row = {
        "custom_film_plan_id": "plan-1",
        "custom_film_plan_hash": compiled.plan_hash,
        "custom_film_quote_inputs_hash": compiled.quote_inputs_hash,
        "custom_film_approval_hash": approval,
        "max_spend": compiled.max_spend,
        "plan": plan,
        "plan_hash": compiled.plan_hash,
        "quote_inputs": quote,
        "quote_inputs_hash": compiled.quote_inputs_hash,
        "approval_hash": approval,
    }
    conn = _FakeConnection(row)
    monkeypatch.setattr(runtime, "get_pool", lambda: _async_value(_FakePool(conn)))
    first = await runtime.consume_approval_and_schedule("tenant-1", "video-1", approval)
    second = await runtime.consume_approval_and_schedule("tenant-1", "video-1", approval)
    assert first["scheduled"] is True
    assert second["scheduled"] is False
    assert second["job_id"] == first["job_id"]
    assert second["video_id"] == "video-1"
    assert second["envelope"] == first["envelope"]
    assert first["job_id"].startswith("custom-film-runtime:")
    assert conn.row["custom_film_approval_hash"] is None
    assert conn.row["approval_hash"] is None
    assert len([sql for sql, _ in conn.executed if "UPDATE videos" in sql]) == 1
    assert any("FOR UPDATE OF v, p" in sql for sql in conn.queries)
    assert any("ON CONFLICT (job_id)" in sql for sql in conn.queries)


async def _async_value(value):
    return value


def test_runtime_adapter_has_no_custom_film_branch_in_provider_translation():
    source = __import__("inspect").getsource(
        __import__("production_styles").runtime_values_from_knobs
    )
    assert "custom_film" not in source
    assert "PUBLIC_PRODUCTION_STYLE_IDS" not in source


@pytest.mark.asyncio
async def test_nested_runtime_values_are_deeply_immutable_and_copy_safe():
    compiled, plan, _quote, _approval = await _compiled(30)
    before_hash = compiled.runtime_hash
    before_stage = compiled.stage_plan()
    plan["sections"][0]["knobs"]["image_density"]["target"] = 999
    with pytest.raises(TypeError):
        compiled.sections[0].image_density["target"] = 999
    mutable_copy = compiled.sections[0].stage_values()
    mutable_copy["image_density"]["target"] = 999
    mutable_copy["provenance"]["render_mode"].append("injected")
    assert compiled.runtime_hash == before_hash
    assert compiled.stage_plan() == before_stage
    assert compiled.sections[0].image_density["target"] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("duration_seconds", 5.9),
        ("duration_seconds", True),
        ("order_index", 0.0),
        ("order_index", False),
        ("still_images", 3.2),
        ("still_images", True),
        ("animation_clips", 1.1),
        ("voice_tracks", False),
        ("requested_duration_seconds", 30.0),
    ],
)
async def test_fractional_and_boolean_count_fields_are_rejected(field, value):
    _compiled_value, plan, quote, approval = await _compiled(30)
    if field == "requested_duration_seconds":
        quote[field] = value
    else:
        quote["sections"][0][field] = value
    quote_digest = contract.canonical_hash(quote)
    approval = contract.approval_binding_hash(contract.plan_hash(plan), quote)
    with pytest.raises(contract.CustomFilmContractError, match="exact integer"):
        runtime.compile_runtime_plan(
            video_id="video-1",
            plan_id="plan-1",
            normalized_plan=plan,
            quote_inputs=quote,
            expected_plan_hash=contract.plan_hash(plan),
            expected_quote_inputs_hash=quote_digest,
            expected_approval_hash=approval,
            max_spend=999,
        )


@pytest.mark.asyncio
async def test_durable_envelope_round_trips_for_restart_and_detects_tampering():
    compiled, _plan_value, _quote, _approval = await _compiled(30)
    encoded = __import__("json").dumps(compiled.envelope())
    restored = runtime.validate_runtime_envelope(encoded)
    assert restored["runtime_hash"] == compiled.runtime_hash
    assert restored["stage_plan"] == list(compiled.stage_plan())
    restored["stage_plan"][0]["duration_seconds"] += 1
    with pytest.raises(contract.CustomFilmContractError, match="hash"):
        runtime.validate_runtime_envelope(restored)


@pytest.mark.asyncio
async def test_restart_loader_recovers_the_exact_persisted_stage_plan(monkeypatch):
    compiled, plan, quote, approval = await _compiled(30)
    row = {
        "custom_film_plan_id": "plan-1",
        "custom_film_plan_hash": compiled.plan_hash,
        "custom_film_quote_inputs_hash": compiled.quote_inputs_hash,
        "custom_film_approval_hash": None,
        "max_spend": compiled.max_spend,
        "plan": plan,
        "plan_hash": compiled.plan_hash,
        "quote_inputs": quote,
        "quote_inputs_hash": compiled.quote_inputs_hash,
        "approval_hash": None,
    }
    conn = _FakeConnection(row)
    conn.task = {
        "id": "task-1",
        "job_id": f"custom-film-runtime:{compiled.runtime_hash}",
        "runtime_envelope": __import__("json").loads(
            __import__("json").dumps(compiled.envelope())
        ),
    }
    monkeypatch.setattr(runtime, "get_pool", lambda: _async_value(_FakePool(conn)))
    recovered = await runtime.load_exact_runtime_schedule(
        "tenant-1", "video-1", approval
    )
    assert recovered["job_id"] == conn.task["job_id"]
    assert recovered["envelope"]["stage_plan"] == list(compiled.stage_plan())
    assert recovered["envelope"]["sections"][0]["duration_seconds"] == 12


@pytest.mark.asyncio
async def test_exact_replay_rejects_an_unrelated_runtime_task(monkeypatch):
    compiled, plan, quote, approval = await _compiled(30)
    row = {
        "custom_film_plan_id": "plan-1",
        "custom_film_plan_hash": compiled.plan_hash,
        "custom_film_quote_inputs_hash": compiled.quote_inputs_hash,
        "custom_film_approval_hash": None,
        "max_spend": compiled.max_spend,
        "plan": plan,
        "plan_hash": compiled.plan_hash,
        "quote_inputs": quote,
        "quote_inputs_hash": compiled.quote_inputs_hash,
        "approval_hash": None,
    }
    conn = _FakeConnection(row)
    unrelated = compiled.envelope()
    unrelated["approval_hash"] = "f" * 64
    unrelated["runtime_hash"] = "e" * 64
    conn.task = {
        "id": "task-other",
        "job_id": "custom-film-runtime:" + ("e" * 64),
        "runtime_envelope": unrelated,
    }
    monkeypatch.setattr(runtime, "get_pool", lambda: _async_value(_FakePool(conn)))
    with pytest.raises(contract.CustomFilmContractError, match="stale or was already"):
        await runtime.consume_approval_and_schedule(
            "tenant-1", "video-1", approval
        )


class _RollbackTransaction(_Context):
    def __init__(self, conn):
        self.value = conn
        self.conn = conn
        self.snapshot = None

    async def __aenter__(self):
        self.snapshot = (copy.deepcopy(self.conn.row), copy.deepcopy(self.conn.task))
        return self.conn

    async def __aexit__(self, exc_type, *_args):
        if exc_type:
            self.conn.row, self.conn.task = self.snapshot
        return None


class _FailingVideoUpdateConnection(_FakeConnection):
    def transaction(self):
        return _RollbackTransaction(self)

    async def execute(self, sql, *_args):
        if "UPDATE videos" in sql:
            return "UPDATE 0"
        return await super().execute(sql, *_args)


@pytest.mark.asyncio
async def test_consume_failure_rolls_back_task_and_plan_approval(monkeypatch):
    compiled, plan, quote, approval = await _compiled(30)
    row = {
        "custom_film_plan_id": "plan-1",
        "custom_film_plan_hash": compiled.plan_hash,
        "custom_film_quote_inputs_hash": compiled.quote_inputs_hash,
        "custom_film_approval_hash": approval,
        "max_spend": compiled.max_spend,
        "plan": plan,
        "plan_hash": compiled.plan_hash,
        "quote_inputs": quote,
        "quote_inputs_hash": compiled.quote_inputs_hash,
        "approval_hash": approval,
    }
    conn = _FailingVideoUpdateConnection(row)
    monkeypatch.setattr(runtime, "get_pool", lambda: _async_value(_FakePool(conn)))
    with pytest.raises(contract.CustomFilmContractError, match="could not be consumed"):
        await runtime.consume_approval_and_schedule(
            "tenant-1", "video-1", approval
        )
    assert conn.task is None
    assert conn.row["approval_hash"] == approval
    assert conn.row["custom_film_approval_hash"] == approval


def test_runtime_envelope_schema_and_migration_are_in_lockstep():
    from pathlib import Path

    root = Path(__file__).parents[3]
    migration = (
        root / "backend/migrations/123_custom_film_runtime_envelope.sql"
    ).read_text()
    schema = (root / "schema.sql").read_text()
    for token in (
        "runtime_envelope JSONB",
        "background_tasks_custom_film_runtime_envelope_check",
        "background_tasks_custom_film_approval_idx",
        "custom-film-runtime-v1",
    ):
        assert token in migration
        assert token in schema
