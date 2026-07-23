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
        (static.section_id, "voice"),
        (static.section_id, "pictures"),
        (static.section_id, "quality"),
        (animated.section_id, "script"),
        (animated.section_id, "voice"),
        (animated.section_id, "pictures"),
        (animated.section_id, "motion"),
        (animated.section_id, "clips"),
        (animated.section_id, "quality"),
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
    def transaction(self):
        context = _Context()
        context.value = self
        return context

    async def fetchrow(self, sql, *_args):
        if "SELECT v.custom_film_plan_id" in sql:
            return copy.deepcopy(self.row)
        if "SELECT job_id FROM background_tasks" in sql:
            return copy.deepcopy(self.task)
        if "INSERT INTO background_tasks" in sql:
            if self.task:
                return None
            self.task = {"id": "task-1", "job_id": _args[2]}
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
    assert second == {
        "scheduled": False,
        "job_id": first["job_id"],
        "video_id": "video-1",
    }
    assert first["job_id"].startswith("custom-film-runtime:")
    assert conn.row["custom_film_approval_hash"] is None
    assert conn.row["approval_hash"] is None
    assert len([sql for sql, _ in conn.executed if "UPDATE videos" in sql]) == 1


async def _async_value(value):
    return value


def test_runtime_adapter_has_no_custom_film_branch_in_provider_translation():
    source = __import__("inspect").getsource(
        __import__("production_styles").runtime_values_from_knobs
    )
    assert "custom_film" not in source
    assert "PUBLIC_PRODUCTION_STYLE_IDS" not in source
