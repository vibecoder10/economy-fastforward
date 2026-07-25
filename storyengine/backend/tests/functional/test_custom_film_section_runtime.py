from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import custom_film_contract as contract
import custom_film_provider_operations as provider_operations
import custom_film_runtime
import custom_film_section_runtime as section_runtime


STATIC_ID = "00000000-0000-4000-8000-000000000001"
ANIMATED_ID = "00000000-0000-4000-8000-000000000002"


def _section(
    section_id: str,
    order_index: int,
    duration_seconds: int,
    *,
    animated: bool,
) -> dict:
    if animated:
        values = {
            "render_mode": "coverage",
            "script_profile": "power_doctrine_v2",
            "visual_profile": "cinematic_illustration",
            "dialogue_audio": "voice_over",
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
    else:
        values = {
            "render_mode": "static_docu",
            "script_profile": "neutral_v1",
            "visual_profile": "neutral_v1",
            "dialogue_audio": "voice_over",
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
        "section_id": section_id,
        "order_index": order_index,
        "duration_seconds": duration_seconds,
        "role": "evidence" if not animated else "explanation",
        "purpose": "Show evidence" if not animated else "Explain the mechanism",
        **values,
        "provenance": {"render_mode": ["photo" if not animated else "investigative"]},
        "estimated_media": {
            "still_images": 2 if not animated else 5,
            "animation_clips": 0 if not animated else 5,
            "voice_tracks": 1,
        },
    }


def _envelope() -> dict:
    static = _section(STATIC_ID, 0, 12, animated=False)
    animated = _section(ANIMATED_ID, 1, 18, animated=True)
    stage_plan = []
    for section in (static, animated):
        stages = ["script", "voice", "pictures"]
        if section["animation"]["enabled"]:
            stages += ["motion", "clips"]
        stages.append("quality")
        for stage in stages:
            stage_plan.append(
                {
                    "section_id": section["section_id"],
                    "order_index": section["order_index"],
                    "stage": stage,
                    "duration_seconds": section["duration_seconds"],
                    "values": copy.deepcopy(section),
                }
            )
    base = {
        "runtime_version": custom_film_runtime.RUNTIME_VERSION,
        "video_id": "video-1",
        "plan_id": "plan-1",
        "plan_hash": "a" * 64,
        "quote_inputs_hash": "b" * 64,
        "approval_hash": "c" * 64,
        "total_duration_seconds": 30,
        "max_spend": 10.0,
        "sections": [static, animated],
        "stage_plan": stage_plan,
    }
    return {"runtime_hash": contract.canonical_hash(base), **base}


def _rehash(envelope: dict) -> None:
    base = copy.deepcopy(envelope)
    base.pop("runtime_hash", None)
    envelope["runtime_hash"] = contract.canonical_hash(base)


def test_adapter_resolves_every_section_dimension_and_exact_seconds():
    adapters = section_runtime.compile_stage_adapters(_envelope())
    assert [adapter.duration_seconds for adapter in adapters] == [
        12,
        12,
        12,
        12,
        18,
        18,
        18,
        18,
        18,
        18,
    ]
    static = adapters[0].provider_values()
    animated = adapters[4].provider_values()
    for field in (
        "script_profile",
        "visual_profile",
        "image_density",
        "language",
        "dubbing",
        "dialogue_audio",
        "animation",
        "segmentation",
        "camera",
        "quality_laws",
        "duration_seconds",
    ):
        assert field in static
        assert field in animated
    assert static["render_mode"] == "static_docu"
    assert static["image_density"]["mode"] == "per_item"
    assert static["camera"]["mode"] == "three_complementary_views"
    assert animated["render_mode"] == "coverage"
    assert animated["animation"]["enabled"] is True
    assert animated["quality_laws"][-1] == "motion_prompt_presence"


def test_adapter_values_are_immutable_and_provider_copy_is_detached():
    adapter = section_runtime.compile_stage_adapters(_envelope())[0]
    with pytest.raises(TypeError):
        adapter.image_density["target"] = 99
    values = adapter.provider_values()
    values["image_density"]["target"] = 99
    values["quality_laws"].append("injected")
    assert adapter.image_density["target"] == 3
    assert "injected" not in adapter.quality_laws


@pytest.mark.parametrize(
    "tamper",
    [
        "missing_section",
        "duplicate_section",
        "fractional_seconds",
        "work_values",
        "work_order",
        "unsupported_stage",
        "missing_quality",
        "static_motion",
        "cross_mode",
    ],
)
def test_adapter_fails_closed_for_missing_tampered_or_cross_mode_input(tamper):
    envelope = _envelope()
    if tamper == "missing_section":
        envelope["stage_plan"][0]["section_id"] = "missing"
    elif tamper == "duplicate_section":
        envelope["sections"][1]["section_id"] = STATIC_ID
    elif tamper == "fractional_seconds":
        envelope["sections"][0]["duration_seconds"] = 12.5
    elif tamper == "work_values":
        envelope["stage_plan"][0]["values"]["camera"]["mode"] = "wrong"
    elif tamper == "work_order":
        envelope["stage_plan"][0], envelope["stage_plan"][1] = (
            envelope["stage_plan"][1],
            envelope["stage_plan"][0],
        )
    elif tamper == "unsupported_stage":
        envelope["stage_plan"][0]["stage"] = "upload"
    elif tamper == "missing_quality":
        envelope["sections"][0]["quality_laws"] = []
    elif tamper == "static_motion":
        envelope["sections"][0]["animation"]["enabled"] = True
    elif tamper == "cross_mode":
        envelope["sections"][1]["language"]["mode"] = "bilingual"
    _rehash(envelope)
    with pytest.raises(contract.CustomFilmContractError):
        section_runtime.compile_stage_adapters(envelope)


class _Context:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *_args):
        return None


class _FakeConnection:
    def __init__(self, envelope: dict):
        self.task = {
            "job_id": f"custom-film-runtime:{envelope['runtime_hash']}",
            "runtime_envelope": copy.deepcopy(envelope),
            "runtime_progress": None,
            "status": "pending",
        }
        self.assignments: dict[str, list[str]] = {}
        self.updates: list[tuple[str, tuple]] = []

    def transaction(self):
        return _Context(self)

    async def fetchrow(self, sql, *_args):
        if "FROM background_tasks" in sql:
            if _args[2] != self.task["job_id"]:
                return None
            return copy.deepcopy(self.task)
        raise AssertionError(sql)

    async def fetch(self, sql, *_args):
        if "FROM custom_film_section_scenes" in sql:
            return [
                {"script_id": script_id}
                for script_id in self.assignments.get(str(_args[3]), [])
            ]
        raise AssertionError(sql)

    async def execute(self, sql, *_args):
        self.updates.append((sql, _args))
        if "DELETE FROM custom_film_section_scenes" in sql:
            self.assignments[str(_args[3])] = []
        elif "INSERT INTO custom_film_section_scenes" in sql:
            self.assignments.setdefault(str(_args[3]), []).append(str(_args[4]))
        elif "SET runtime_progress" in sql:
            self.task["runtime_progress"] = json.loads(_args[3])
        elif "SET status = 'running'" in sql:
            self.task["status"] = "running"
        elif "SET status = 'completed'" in sql:
            self.task["status"] = "completed"
        elif "SET status = 'failed'" in sql:
            self.task["status"] = "failed"
            self.task["error_message"] = _args[3]
        else:
            raise AssertionError(sql)
        return "UPDATE 1"


class _RollbackContext(_Context):
    def __init__(self, conn):
        super().__init__(conn)
        self.conn = conn
        self.snapshot = None

    async def __aenter__(self):
        self.snapshot = (
            copy.deepcopy(self.conn.task),
            copy.deepcopy(self.conn.assignments),
        )
        return self.conn

    async def __aexit__(self, exc_type, *_args):
        if exc_type:
            self.conn.task, self.conn.assignments = self.snapshot
        return None


class _FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _Context(self.conn)


async def _value(value):
    return value


class _JournalConnection(_FakeConnection):
    def __init__(self, envelope):
        super().__init__(envelope)
        self.operations = {}

    async def fetchrow(self, sql, *_args):
        if "FROM custom_film_provider_operations" in sql:
            row = self.operations.get(str(_args[0]))
            return copy.deepcopy(row) if row else None
        return await super().fetchrow(sql, *_args)

    async def execute(self, sql, *_args):
        if "INSERT INTO custom_film_provider_operations" in sql:
            (
                tenant_id,
                video_id,
                runtime_job_id,
                runtime_hash,
                stage_key,
                operation_id,
                provider,
                request_hash,
                mode,
            ) = _args
            self.operations.setdefault(
                str(operation_id),
                {
                    "tenant_id": tenant_id,
                    "video_id": video_id,
                    "runtime_job_id": runtime_job_id,
                    "runtime_hash": runtime_hash,
                    "stage_key": stage_key,
                    "operation_id": operation_id,
                    "provider": provider,
                    "request_hash": request_hash,
                    "reconciliation_mode": mode,
                    "state": "prepared",
                    "provider_operation_id": None,
                    "result": None,
                },
            )
            return "INSERT 0 1"
        if "SET state = 'completed'" in sql:
            operation_id, result_json = _args
            row = self.operations[str(operation_id)]
            result = json.loads(result_json)
            if row["result"] is not None and row["result"] != result:
                return "UPDATE 0"
            row["state"] = "completed"
            row["result"] = result
            return "UPDATE 1"
        if "SET state = 'reconciliation_required'" in sql:
            operation_id, detail = _args
            row = self.operations[str(operation_id)]
            row["state"] = "reconciliation_required"
            row["reconciliation_detail"] = detail
            return "UPDATE 1"
        return await super().execute(sql, *_args)


class _OperationAwareRunner:
    def __init__(self, mode=provider_operations.RECONCILIATION_IDEMPOTENCY):
        self.mode = mode
        self.calls = []
        self.reconciliations = []

    def operation_spec(self, adapter, scene_ids, operation_id):
        return provider_operations.ProviderOperationSpec(
            provider=f"fake-{adapter.stage}",
            request_hash=contract.canonical_hash(
                {
                    "operation_id": operation_id,
                    "values": adapter.provider_values(),
                    "scene_ids": list(scene_ids),
                }
            ),
            reconciliation_mode=self.mode,
        )

    async def __call__(self, adapter, scene_ids, operation_id):
        self.calls.append((adapter.stage_key, operation_id))
        if adapter.stage == "script":
            return {"scene_ids": [f"{adapter.section_id}-scene-1"]}
        return {"ok": True}

    async def reconcile(self, adapter, scene_ids, operation_id, record):
        self.reconciliations.append(
            (adapter.stage_key, operation_id, record.provider_operation_id)
        )
        if adapter.stage == "script":
            return {"scene_ids": [f"{adapter.section_id}-scene-1"]}
        return {"ok": True}


@pytest.mark.asyncio
async def test_consumer_holds_claim_persists_assignments_and_passes_resolved_values(
    monkeypatch,
):
    envelope = _envelope()
    conn = _FakeConnection(envelope)
    claim_events = []
    calls = []

    async def acquire(*args, **kwargs):
        claim_events.append(("acquire", args, kwargs))
        return True

    async def release(*args):
        claim_events.append(("release", args, {}))

    async def runner(adapter, scene_ids, operation_id):
        calls.append((adapter, scene_ids, operation_id))
        if adapter.stage == "script":
            return {"scene_ids": [f"{adapter.section_id}-scene-1"]}
        return {"ok": True}

    monkeypatch.setattr(section_runtime.database, "get_pool", lambda: _value(_FakePool(conn)))
    monkeypatch.setattr(section_runtime.generation_claims, "acquire", acquire)
    monkeypatch.setattr(section_runtime.generation_claims, "release", release)
    result = await section_runtime.consume_runtime_schedule(
        "tenant-1",
        "video-1",
        conn.task["job_id"],
        stage_runner=runner,
    )
    assert result["status"] == "completed"
    assert conn.task["status"] == "completed"
    assert conn.assignments == {
        STATIC_ID: [f"{STATIC_ID}-scene-1"],
        ANIMATED_ID: [f"{ANIMATED_ID}-scene-1"],
    }
    assert len(calls) == 10
    assert all(
        not scenes or scenes == (f"{adapter.section_id}-scene-1",)
        for adapter, scenes, _operation_id in calls
    )
    assert all(
        operation_id.startswith("custom-film-op:")
        and len(operation_id) == len("custom-film-op:") + 64
        for _adapter, _scenes, operation_id in calls
    )
    assert calls[0][0].provider_values()["script_profile"] == "neutral_v1"
    assert calls[4][0].provider_values()["script_profile"] == "power_doctrine_v2"
    assert claim_events[0][0] == "acquire"
    assert claim_events[-1][0] == "release"


@pytest.mark.asyncio
async def test_operation_aware_consumer_journals_and_completes_every_stage(
    monkeypatch,
):
    conn = _JournalConnection(_envelope())
    pool = _FakePool(conn)
    runner = _OperationAwareRunner()

    async def acquire(*_args, **_kwargs):
        return True

    async def release(*_args):
        return None

    monkeypatch.setattr(section_runtime.database, "get_pool", lambda: _value(pool))
    monkeypatch.setattr(provider_operations.database, "get_pool", lambda: _value(pool))
    monkeypatch.setattr(section_runtime.generation_claims, "acquire", acquire)
    monkeypatch.setattr(section_runtime.generation_claims, "release", release)
    result = await section_runtime.consume_runtime_schedule(
        "tenant-1",
        "video-1",
        conn.task["job_id"],
        stage_runner=runner,
    )
    assert result["status"] == "completed"
    assert len(runner.calls) == 10
    assert len(conn.operations) == 10
    assert all(row["state"] == "completed" for row in conn.operations.values())
    assert all(row["result"] is not None for row in conn.operations.values())
    assert runner.reconciliations == []


@pytest.mark.asyncio
async def test_consumer_finalizes_only_after_full_durable_prefix(monkeypatch):
    envelope = _envelope()
    conn = _FakeConnection(envelope)
    finalizer_calls = []

    async def acquire(*_args, **_kwargs):
        return True

    async def release(*_args):
        return None

    async def runner(adapter, _scene_ids, _operation_id):
        if adapter.stage == "script":
            return {"scene_ids": [f"{adapter.section_id}-scene-1"]}
        return {"ok": True}

    async def finalizer(tenant_id, video_id, job_id, exact_envelope):
        assert conn.task["status"] == "running"
        adapters = section_runtime.compile_stage_adapters(exact_envelope)
        assert conn.task["runtime_progress"] == {
            "runtime_hash": envelope["runtime_hash"],
            "completed_stage_keys": [adapter.stage_key for adapter in adapters],
            "last_stage_key": adapters[-1].stage_key,
            "in_flight": None,
        }
        finalizer_calls.append((tenant_id, video_id, job_id))
        return {
            "status": "rendered",
            "final_video_url": "storage://exact-film",
            "render_engine": "remotion",
        }

    monkeypatch.setattr(
        section_runtime.database, "get_pool", lambda: _value(_FakePool(conn))
    )
    monkeypatch.setattr(section_runtime.generation_claims, "acquire", acquire)
    monkeypatch.setattr(section_runtime.generation_claims, "release", release)
    result = await section_runtime.consume_runtime_schedule(
        "tenant-1",
        "video-1",
        conn.task["job_id"],
        stage_runner=runner,
        finalizer=finalizer,
    )
    assert finalizer_calls == [
        ("tenant-1", "video-1", conn.task["job_id"])
    ]
    assert result["finalization"]["final_video_url"] == "storage://exact-film"
    assert conn.task["status"] == "completed"


@pytest.mark.asyncio
async def test_stage_failure_never_calls_finalizer(monkeypatch):
    conn = _FakeConnection(_envelope())
    finalizer_calls = []

    async def acquire(*_args, **_kwargs):
        return True

    async def release(*_args):
        return None

    async def runner(*_args):
        raise RuntimeError("stage stopped")

    async def finalizer(*args):
        finalizer_calls.append(args)
        return {}

    monkeypatch.setattr(
        section_runtime.database, "get_pool", lambda: _value(_FakePool(conn))
    )
    monkeypatch.setattr(section_runtime.generation_claims, "acquire", acquire)
    monkeypatch.setattr(section_runtime.generation_claims, "release", release)
    with pytest.raises(RuntimeError, match="stage stopped"):
        await section_runtime.consume_runtime_schedule(
            "tenant-1",
            "video-1",
            conn.task["job_id"],
            stage_runner=runner,
            finalizer=finalizer,
        )
    assert finalizer_calls == []
    assert conn.task["status"] == "failed"


@pytest.mark.asyncio
async def test_finalizer_retry_skips_all_durable_provider_work(monkeypatch):
    conn = _FakeConnection(_envelope())
    stage_calls = []
    finalizer_calls = 0

    async def acquire(*_args, **_kwargs):
        return True

    async def release(*_args):
        return None

    async def runner(adapter, _scene_ids, _operation_id):
        stage_calls.append(adapter.stage_key)
        if adapter.stage == "script":
            return {"scene_ids": [f"{adapter.section_id}-scene-1"]}
        return {"ok": True}

    async def finalizer(*_args):
        nonlocal finalizer_calls
        finalizer_calls += 1
        if finalizer_calls == 1:
            raise RuntimeError("render host restarted")
        return {
            "status": "rendered",
            "final_video_url": "storage://resumed-film",
            "render_engine": "ffmpeg",
        }

    monkeypatch.setattr(
        section_runtime.database, "get_pool", lambda: _value(_FakePool(conn))
    )
    monkeypatch.setattr(section_runtime.generation_claims, "acquire", acquire)
    monkeypatch.setattr(section_runtime.generation_claims, "release", release)
    with pytest.raises(RuntimeError, match="render host restarted"):
        await section_runtime.consume_runtime_schedule(
            "tenant-1",
            "video-1",
            conn.task["job_id"],
            stage_runner=runner,
            finalizer=finalizer,
        )
    first_stage_calls = list(stage_calls)
    assert conn.task["status"] == "failed"
    assert len(first_stage_calls) == len(
        section_runtime.compile_stage_adapters(_envelope())
    )

    result = await section_runtime.consume_runtime_schedule(
        "tenant-1",
        "video-1",
        conn.task["job_id"],
        stage_runner=runner,
        finalizer=finalizer,
        attempt=2,
    )
    assert stage_calls == first_stage_calls
    assert finalizer_calls == 2
    assert result["finalization"]["final_video_url"] == "storage://resumed-film"
    assert conn.task["status"] == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "provider_task_id", "expected_path"),
    [
        (provider_operations.RECONCILIATION_IDEMPOTENCY, None, "retry"),
        (provider_operations.RECONCILIATION_QUERY, "provider-task-1", "query"),
        (provider_operations.RECONCILIATION_NONE, None, "blocked"),
    ],
)
async def test_in_flight_operation_uses_only_provider_safe_reconciliation_path(
    monkeypatch,
    mode,
    provider_task_id,
    expected_path,
):
    envelope = _envelope()
    conn = _JournalConnection(envelope)
    pool = _FakePool(conn)
    runner = _OperationAwareRunner(mode)
    first_adapter = section_runtime.compile_stage_adapters(envelope)[0]
    operation_id = section_runtime._operation_id(
        "tenant-1", conn.task["job_id"], first_adapter
    )
    spec = runner.operation_spec(first_adapter, (), operation_id)
    conn.operations[operation_id] = {
        "tenant_id": "tenant-1",
        "video_id": "video-1",
        "runtime_job_id": conn.task["job_id"],
        "runtime_hash": envelope["runtime_hash"],
        "stage_key": first_adapter.stage_key,
        "operation_id": operation_id,
        "provider": spec.provider,
        "request_hash": spec.request_hash,
        "reconciliation_mode": mode,
        "state": "submitted" if provider_task_id else "prepared",
        "provider_operation_id": provider_task_id,
        "result": None,
    }
    conn.task["runtime_progress"] = {
        "runtime_hash": envelope["runtime_hash"],
        "completed_stage_keys": [],
        "last_stage_key": None,
        "in_flight": {
            "stage_key": first_adapter.stage_key,
            "operation_id": operation_id,
            "state": "started",
        },
    }

    async def acquire(*_args, **_kwargs):
        return True

    async def release(*_args):
        return None

    monkeypatch.setattr(section_runtime.database, "get_pool", lambda: _value(pool))
    monkeypatch.setattr(provider_operations.database, "get_pool", lambda: _value(pool))
    monkeypatch.setattr(section_runtime.generation_claims, "acquire", acquire)
    monkeypatch.setattr(section_runtime.generation_claims, "release", release)
    if expected_path == "blocked":
        with pytest.raises(
            contract.CustomFilmContractError,
            match="cannot query or deduplicate",
        ):
            await section_runtime.consume_runtime_schedule(
                "tenant-1",
                "video-1",
                conn.task["job_id"],
                stage_runner=runner,
            )
        assert runner.calls == []
        assert runner.reconciliations == []
        assert conn.operations[operation_id]["state"] == "reconciliation_required"
        assert "cannot query or deduplicate" in conn.operations[operation_id][
            "reconciliation_detail"
        ]
        return

    await section_runtime.consume_runtime_schedule(
        "tenant-1",
        "video-1",
        conn.task["job_id"],
        stage_runner=runner,
    )
    if expected_path == "retry":
        assert runner.calls[0] == (first_adapter.stage_key, operation_id)
        assert runner.reconciliations == []
    else:
        assert runner.reconciliations == [
            (first_adapter.stage_key, operation_id, "provider-task-1")
        ]
        assert all(stage_key != first_adapter.stage_key for stage_key, _ in runner.calls)


@pytest.mark.asyncio
async def test_script_assignment_remap_replaces_ids_in_stable_returned_order():
    adapter = section_runtime.compile_stage_adapters(_envelope())[0]
    conn = _FakeConnection(_envelope())
    conn.assignments[STATIC_ID] = ["old-1", "old-2"]
    await section_runtime._replace_assignments(
        conn,
        "tenant-1",
        adapter,
        ("new-2", "new-1"),
    )
    assert conn.assignments[STATIC_ID] == ["new-2", "new-1"]
    inserts = [
        args
        for sql, args in conn.updates
        if "INSERT INTO custom_film_section_scenes" in sql
    ]
    assert [args[-1] for args in inserts] == [0, 1]


@pytest.mark.asyncio
async def test_assignment_remap_rolls_back_if_any_scene_insert_fails():
    class FailingConnection(_FakeConnection):
        def transaction(self):
            return _RollbackContext(self)

        async def execute(self, sql, *_args):
            if (
                "INSERT INTO custom_film_section_scenes" in sql
                and str(_args[4]) == "bad-scene"
            ):
                raise RuntimeError("foreign key rejected")
            return await super().execute(sql, *_args)

    envelope = _envelope()
    conn = FailingConnection(envelope)
    conn.assignments[STATIC_ID] = ["old-scene"]

    async def acquire(*_args, **_kwargs):
        return True

    async def release(*_args):
        return None

    async def runner(adapter, _scene_ids, _operation_id):
        if adapter.stage == "script":
            return {"scene_ids": ["new-scene", "bad-scene"]}
        return {"ok": True}

    original = conn.assignments[STATIC_ID][:]
    pool = _FakePool(conn)
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(section_runtime.database, "get_pool", lambda: _value(pool))
        monkeypatch.setattr(section_runtime.generation_claims, "acquire", acquire)
        monkeypatch.setattr(section_runtime.generation_claims, "release", release)
        with pytest.raises(RuntimeError, match="foreign key rejected"):
            await section_runtime.consume_runtime_schedule(
                "tenant-1",
                "video-1",
                conn.task["job_id"],
                stage_runner=runner,
            )
    assert conn.assignments[STATIC_ID] == original


@pytest.mark.asyncio
async def test_restart_resumes_after_last_durable_stage_without_replaying_it(monkeypatch):
    envelope = _envelope()
    conn = _FakeConnection(envelope)
    first_stage_key = f"0:{STATIC_ID}:script"
    conn.assignments[STATIC_ID] = ["scene-static"]
    conn.task["runtime_progress"] = {
        "runtime_hash": envelope["runtime_hash"],
        "completed_stage_keys": [first_stage_key],
        "last_stage_key": first_stage_key,
        "in_flight": None,
    }

    async def acquire(*_args, **_kwargs):
        return True

    async def release(*_args):
        return None

    second_calls = []

    async def finish(adapter, _scene_ids, _operation_id):
        second_calls.append(adapter.stage_key)
        if adapter.stage == "script":
            return {"scene_ids": ["scene-animated"]}
        return {"ok": True}

    monkeypatch.setattr(section_runtime.database, "get_pool", lambda: _value(_FakePool(conn)))
    monkeypatch.setattr(section_runtime.generation_claims, "acquire", acquire)
    monkeypatch.setattr(section_runtime.generation_claims, "release", release)
    await section_runtime.consume_runtime_schedule(
        "tenant-1",
        "video-1",
        conn.task["job_id"],
        stage_runner=finish,
    )
    assert first_stage_key not in second_calls
    assert conn.task["status"] == "completed"


@pytest.mark.asyncio
async def test_restart_with_completed_script_but_missing_assignment_stops_pre_runner(
    monkeypatch,
):
    envelope = _envelope()
    conn = _FakeConnection(envelope)
    conn.task["runtime_progress"] = {
        "runtime_hash": envelope["runtime_hash"],
        "completed_stage_keys": [f"0:{STATIC_ID}:script"],
        "last_stage_key": f"0:{STATIC_ID}:script",
        "in_flight": None,
    }
    calls = []

    async def acquire(*_args, **_kwargs):
        return True

    async def release(*_args):
        return None

    async def runner(adapter, _scene_ids, _operation_id):
        calls.append(adapter.stage_key)
        return {"ok": True}

    monkeypatch.setattr(section_runtime.database, "get_pool", lambda: _value(_FakePool(conn)))
    monkeypatch.setattr(section_runtime.generation_claims, "acquire", acquire)
    monkeypatch.setattr(section_runtime.generation_claims, "release", release)
    with pytest.raises(contract.CustomFilmContractError, match="assignment is missing"):
        await section_runtime.consume_runtime_schedule(
            "tenant-1",
            "video-1",
            conn.task["job_id"],
            stage_runner=runner,
        )
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("completed", "last_stage_key", "in_flight"),
    [
        ([f"0:{STATIC_ID}:voice"], f"0:{STATIC_ID}:voice", None),
        (
            [f"0:{STATIC_ID}:script", f"0:{STATIC_ID}:pictures"],
            f"0:{STATIC_ID}:pictures",
            None,
        ),
        ([f"0:{STATIC_ID}:script"], None, None),
        (
            [f"0:{STATIC_ID}:script"],
            f"0:{STATIC_ID}:script",
            {
                "stage_key": f"0:{STATIC_ID}:pictures",
                "operation_id": "custom-film-op:" + ("a" * 64),
                "state": "started",
            },
        ),
    ],
)
async def test_nonprefix_reordered_or_inconsistent_progress_stops_before_callback(
    monkeypatch, completed, last_stage_key, in_flight
):
    envelope = _envelope()
    conn = _FakeConnection(envelope)
    conn.task["runtime_progress"] = {
        "runtime_hash": envelope["runtime_hash"],
        "completed_stage_keys": completed,
        "last_stage_key": last_stage_key,
        "in_flight": in_flight,
    }
    calls = []

    async def acquire(*_args, **_kwargs):
        return True

    async def release(*_args):
        return None

    async def runner(*args):
        calls.append(args)
        return {"ok": True}

    monkeypatch.setattr(section_runtime.database, "get_pool", lambda: _value(_FakePool(conn)))
    monkeypatch.setattr(section_runtime.generation_claims, "acquire", acquire)
    monkeypatch.setattr(section_runtime.generation_claims, "release", release)
    with pytest.raises(contract.CustomFilmContractError):
        await section_runtime.consume_runtime_schedule(
            "tenant-1",
            "video-1",
            conn.task["job_id"],
            stage_runner=runner,
        )
    assert calls == []


@pytest.mark.asyncio
async def test_crash_after_callback_before_complete_never_replays_callback(monkeypatch):
    class CrashAfterCallbackConnection(_FakeConnection):
        def __init__(self, envelope):
            super().__init__(envelope)
            self.progress_writes = 0

        def transaction(self):
            return _RollbackContext(self)

        async def execute(self, sql, *_args):
            if "SET runtime_progress" in sql:
                self.progress_writes += 1
                if self.progress_writes == 2:
                    raise RuntimeError("checkpoint connection dropped")
            return await super().execute(sql, *_args)

    envelope = _envelope()
    conn = CrashAfterCallbackConnection(envelope)
    calls = []

    async def acquire(*_args, **_kwargs):
        return True

    async def release(*_args):
        return None

    async def runner(adapter, _scene_ids, operation_id):
        calls.append((adapter.stage_key, operation_id))
        return {"scene_ids": ["scene-static"]}

    monkeypatch.setattr(section_runtime.database, "get_pool", lambda: _value(_FakePool(conn)))
    monkeypatch.setattr(section_runtime.generation_claims, "acquire", acquire)
    monkeypatch.setattr(section_runtime.generation_claims, "release", release)
    with pytest.raises(RuntimeError, match="checkpoint connection dropped"):
        await section_runtime.consume_runtime_schedule(
            "tenant-1",
            "video-1",
            conn.task["job_id"],
            stage_runner=runner,
        )
    assert len(calls) == 1
    stable_operation_id = calls[0][1]
    assert conn.task["runtime_progress"]["in_flight"] == {
        "stage_key": f"0:{STATIC_ID}:script",
        "operation_id": stable_operation_id,
        "state": "started",
    }

    with pytest.raises(
        section_runtime.CustomFilmReconciliationRequired,
        match="Reconciliation is required",
    ):
        await section_runtime.consume_runtime_schedule(
            "tenant-1",
            "video-1",
            conn.task["job_id"],
            stage_runner=runner,
        )
    assert len(calls) == 1
    assert "checkpoint connection dropped" not in conn.task["error_message"]
    assert "Reconciliation is required" in conn.task["error_message"]


@pytest.mark.asyncio
async def test_raw_callback_error_is_humanized_before_persistence(monkeypatch):
    envelope = _envelope()
    conn = _FakeConnection(envelope)

    async def acquire(*_args, **_kwargs):
        return True

    async def release(*_args):
        return None

    async def runner(*_args):
        raise RuntimeError(
            "provider secret sk-live-123 at https://private.example failed"
        )

    monkeypatch.setattr(section_runtime.database, "get_pool", lambda: _value(_FakePool(conn)))
    monkeypatch.setattr(section_runtime.generation_claims, "acquire", acquire)
    monkeypatch.setattr(section_runtime.generation_claims, "release", release)
    with pytest.raises(RuntimeError):
        await section_runtime.consume_runtime_schedule(
            "tenant-1",
            "video-1",
            conn.task["job_id"],
            stage_runner=runner,
        )
    assert conn.task["error_message"] == (
        "Custom Film section runtime stopped. Please try again."
    )
    assert "sk-live" not in conn.task["error_message"]
    assert "private.example" not in conn.task["error_message"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["claim", "missing_assignment", "job_mismatch"])
async def test_consumer_stops_before_runner_for_claim_assignment_or_identity_failure(
    monkeypatch, failure
):
    envelope = _envelope()
    conn = _FakeConnection(envelope)
    calls = []

    async def acquire(*_args, **_kwargs):
        return failure != "claim"

    async def release(*_args):
        return None

    async def runner(adapter, _scene_ids, _operation_id):
        calls.append(adapter.stage_key)
        if adapter.stage == "script":
            if failure == "missing_assignment":
                return {"ok": True}
            return {"scene_ids": ["scene-1"]}
        return {"ok": True}

    monkeypatch.setattr(section_runtime.database, "get_pool", lambda: _value(_FakePool(conn)))
    monkeypatch.setattr(section_runtime.generation_claims, "acquire", acquire)
    monkeypatch.setattr(section_runtime.generation_claims, "release", release)
    job_id = "custom-film-runtime:" + ("f" * 64) if failure == "job_mismatch" else conn.task["job_id"]
    with pytest.raises(contract.CustomFilmContractError):
        await section_runtime.consume_runtime_schedule(
            "tenant-1", "video-1", job_id, stage_runner=runner
        )
    if failure in {"claim", "job_mismatch"}:
        assert calls == []
    else:
        assert calls == [f"0:{STATIC_ID}:script"]


@pytest.mark.asyncio
async def test_default_worker_runner_fails_closed_without_provider_call(monkeypatch):
    envelope = _envelope()
    conn = _FakeConnection(envelope)

    async def acquire(*_args, **_kwargs):
        return True

    async def release(*_args):
        return None

    monkeypatch.setattr(section_runtime.database, "get_pool", lambda: _value(_FakePool(conn)))
    monkeypatch.setattr(section_runtime.generation_claims, "acquire", acquire)
    monkeypatch.setattr(section_runtime.generation_claims, "release", release)
    with pytest.raises(contract.CustomFilmContractError, match="not installed"):
        await section_runtime.consume_runtime_schedule(
            "tenant-1", "video-1", conn.task["job_id"]
        )
    assert conn.assignments == {}
    assert conn.task["status"] == "failed"


@pytest.mark.asyncio
async def test_claim_is_released_when_database_pool_load_fails(monkeypatch):
    events = []

    async def acquire(*_args, **_kwargs):
        events.append("acquire")
        return True

    async def release(*_args):
        events.append("release")

    async def fail_pool():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(section_runtime.database, "get_pool", fail_pool)
    monkeypatch.setattr(section_runtime.generation_claims, "acquire", acquire)
    monkeypatch.setattr(section_runtime.generation_claims, "release", release)
    with pytest.raises(RuntimeError, match="database unavailable"):
        await section_runtime.consume_runtime_schedule(
            "tenant-1", "video-1", "custom-film-runtime:" + ("a" * 64)
        )
    assert events == ["acquire", "release"]


@pytest.mark.asyncio
async def test_queue_requires_and_forwards_durable_runtime_job_id():
    import job_queue

    class Pool:
        def __init__(self):
            self.call = None

        async def enqueue_job(
            self,
            function,
            *args,
            _job_id=None,
            _queue_name=None,
            _defer_until=None,
            _defer_by=None,
            _expires=None,
            _job_try=None,
            **handler_kwargs,
        ):
            self.call = {
                "function": function,
                "args": args,
                "job_id": _job_id,
                "queue_name": _queue_name,
                "defer_until": _defer_until,
                "defer_by": _defer_by,
                "expires": _expires,
                "job_try": _job_try,
                "handler_kwargs": handler_kwargs,
            }
            return object()

    pool = Pool()
    with pytest.raises(ValueError, match="runtime_job_id"):
        await job_queue.enqueue_stage(
            pool, "custom_film_runtime", "video-1", "tenant-1"
        )
    runtime_job_id = "custom-film-runtime:" + ("a" * 64)
    queued = await job_queue.enqueue_stage(
        pool,
        "custom_film_runtime",
        "video-1",
        "tenant-1",
        runtime_job_id=runtime_job_id,
    )
    assert queued == f"custom-film-worker:{runtime_job_id}:1"
    assert pool.call == {
        "function": "arq_run_custom_film_runtime",
        "args": ("video-1", "tenant-1", 1),
        "job_id": f"custom-film-worker:{runtime_job_id}:1",
        "queue_name": None,
        "defer_until": None,
        "defer_by": None,
        "expires": None,
        "job_try": None,
        "handler_kwargs": {"runtime_job_id": runtime_job_id},
    }
    assert "_job_timeout" not in pool.call["handler_kwargs"]

    await job_queue.enqueue_stage(
        pool,
        "thumbnail",
        "video-2",
        "tenant-1",
        attempt=2,
        force=True,
    )
    assert pool.call["function"] == "arq_run_thumbnail"
    assert pool.call["args"] == ("video-2", "tenant-1", 2)
    assert pool.call["job_id"] == "thumbnail:video-2:2"
    assert pool.call["handler_kwargs"] == {"force": True}


@pytest.mark.asyncio
async def test_startup_recovery_reenqueues_exact_runtime_job_identity(monkeypatch):
    import main

    runtime_job_id = "custom-film-runtime:" + ("d" * 64)
    calls = []

    async def recover():
        calls.append(("recover",))
        return 1

    async def fetch(_sql):
        assert "job_id" in _sql
        return [
            {
                "video_id": "video-1",
                "tenant_id": "tenant-1",
                "task_type": "custom_film_runtime",
                "job_id": runtime_job_id,
                "attempt": 1,
            }
        ]

    async def enqueue(*args, **kwargs):
        calls.append(("enqueue", args, kwargs))
        return "queued"

    monkeypatch.setattr(main, "recover_stale_tasks", recover)
    monkeypatch.setattr(main, "fetch_all", fetch)
    monkeypatch.setattr(main, "enqueue_stage", enqueue)
    app = SimpleNamespace(state=SimpleNamespace(arq=object()))
    assert await main._recover_stale_tasks_to_queue(app) == 1
    enqueue_call = calls[-1]
    assert enqueue_call[0] == "enqueue"
    assert enqueue_call[1][1:] == (
        "custom_film_runtime",
        "video-1",
        "tenant-1",
        2,
    )
    assert enqueue_call[2] == {"runtime_job_id": runtime_job_id}


def test_runtime_progress_schema_migration_worker_and_queue_are_in_lockstep():
    root = Path(__file__).parents[3]
    migration = (
        root / "backend/migrations/124_custom_film_runtime_progress.sql"
    ).read_text()
    schema = (root / "schema.sql").read_text()
    worker = (root / "backend/worker.py").read_text()
    queue = (root / "backend/job_queue.py").read_text()
    for token in (
        "runtime_progress JSONB",
        "background_tasks_custom_film_runtime_progress_check",
        "completed_stage_keys",
        "custom-film-op:",
        "in_flight",
    ):
        assert token in migration
        assert token in schema
    assert "arq_run_custom_film_runtime" in worker
    assert '"custom_film_runtime": "arq_run_custom_film_runtime"' in queue


def test_legacy_worker_stage_path_is_unchanged_by_section_consumer():
    import inspect
    import worker

    source = inspect.getsource(worker._run_stage)
    assert "custom_film" not in source
    assert "SectionStageAdapter" not in source
