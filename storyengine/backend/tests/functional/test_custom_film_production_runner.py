from __future__ import annotations

import copy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

VIDEO_PIPELINE = Path(__file__).parents[4] / "skills" / "video-pipeline"
if str(VIDEO_PIPELINE) not in sys.path:
    sys.path.insert(0, str(VIDEO_PIPELINE))

import custom_film_production_runner as production
import custom_film_provider_operations as operations
import pipeline_executor
import worker
from custom_film_contract import CustomFilmContractError
from custom_film_section_runtime import SectionStageAdapter
from shared.clients.elevenlabs_client import ElevenLabsClient


def _adapter(
    stage: str,
    *,
    section_id: str = "section-a",
    seconds: int = 12,
    profile: str = "neutral_v1",
    language_mode: str = "narrator",
    dialogue_audio: str = "voice_over",
    dubbing: bool = False,
    static: bool = False,
    media_count: int | None = None,
) -> SectionStageAdapter:
    resolved_media_count = media_count if media_count is not None else (3 if static else 1)
    return SectionStageAdapter(
        runtime_hash="a" * 64,
        plan_id="plan-1",
        video_id="video-1",
        section_id=section_id,
        order_index=0 if section_id == "section-a" else 1,
        stage=stage,
        duration_seconds=seconds,
        role="evidence" if section_id == "section-a" else "explanation",
        purpose=(
            "Show the sourced evidence"
            if section_id == "section-a"
            else "Explain why the mechanism matters"
        ),
        render_mode="static_docu" if static else "coverage",
        script_profile=profile,
        visual_profile="neutral_v1",
        dialogue_audio=dialogue_audio,
        image_density=(
            {"mode": "per_item", "target": 3, "minimum": 2}
            if static
            else {"mode": "visual_cue", "target_per_minute": 8}
        ),
        language={"mode": language_mode},
        dubbing={
            "enabled": dubbing,
            "mode": "speech_to_speech" if dubbing else "none",
        },
        animation={
            "enabled": not static,
            "mode": "ken_burns" if static else "grok_native",
        },
        segmentation={
            "mode": (
                "speaker_turn"
                if dubbing or language_mode == "simple_single_language"
                else "visual_cue"
            )
        },
        camera={
            "mode": (
                "three_complementary_views"
                if static
                else "investigative_coverage"
            )
        },
        quality_laws=(
            "source_grounding",
            "visual_cue_fidelity",
        ),
        image_source="generate",
        provenance={"script_profile": [profile]},
        estimated_media={
            "still_images": resolved_media_count,
            "animation_clips": 0 if static else resolved_media_count,
            "voice_tracks": 2 if dubbing else 1,
        },
    )


class _FakeSeams:
    def __init__(
        self,
        mode=operations.RECONCILIATION_QUERY,
        *,
        provider_task_id: str | None = None,
        task_id_per_scene: bool = False,
        fail_after_submit_scene: str | None = None,
    ):
        self.mode = mode
        self.provider_task_id = provider_task_id
        self.task_id_per_scene = task_id_per_scene
        self.fail_after_submit_scene = fail_after_submit_scene
        self.requests = []
        self.queries = []
        self.checkpoints = {}
        self.checkpoint_requests = []

    def operation_metadata(self, request):
        return f"fake-{request.stage}", self.mode

    async def submit(self, request, *, on_submitted):
        self.requests.append(request)
        task_id = self.provider_task_id
        if task_id and self.task_id_per_scene:
            task_id = f"{task_id}:{request.scene_ids[0]}"
        if task_id:
            await on_submitted(task_id)
        if (
            self.fail_after_submit_scene
            and request.scene_ids == (self.fail_after_submit_scene,)
        ):
            self.fail_after_submit_scene = None
            raise RuntimeError("synthetic crash after provider submission")
        result = {
            "exact_seconds": request.exact_seconds,
            "section_id": request.section_id,
            "stage": request.stage,
        }
        if request.stage == "script":
            result["scene_ids"] = [f"{request.section_id}-scene"]
        if request.stage in {"pictures", "motion", "clips"}:
            result["artifacts"] = [
                {
                    "artifact_id": f"{request.stage}:{request.scene_ids[0]}",
                    "artifact_url": f"fake://{request.stage}/{request.scene_ids[0]}",
                }
            ]
        return production.SectionProductionResult(
            result,
            task_id,
        )

    async def query(self, request, provider_operation_id):
        self.queries.append((request, provider_operation_id))
        result = {"reconciled": True}
        if request.stage == "script":
            result["scene_ids"] = [f"{request.section_id}-scene"]
        if request.stage in {"pictures", "motion", "clips"}:
            result["artifacts"] = [
                {
                    "artifact_id": f"{request.stage}:{request.scene_ids[0]}",
                    "artifact_url": f"fake://{request.stage}/{request.scene_ids[0]}",
                }
            ]
        return production.SectionProductionResult(result, provider_operation_id)

    async def checkpoint(self, request):
        self.checkpoint_requests.append(request)
        return copy.deepcopy(self.checkpoints.get(request.scene_ids))


class _FakeJournal:
    def __init__(self):
        self.rows = {}
        self.events = []

    def seed_parent(self, operation_id, adapter):
        self.rows[operation_id] = SimpleNamespace(
            tenant_id="tenant-1",
            video_id=adapter.video_id,
            runtime_job_id="custom-film-runtime:" + adapter.runtime_hash,
            runtime_hash=adapter.runtime_hash,
            stage_key=adapter.stage_key,
            operation_id=operation_id,
            provider="storyengine-section-voice",
            request_hash="0" * 64,
            reconciliation_mode=operations.RECONCILIATION_IDEMPOTENCY,
            state="prepared",
            provider_operation_id=None,
            result=None,
        )

    async def load_operation(self, operation_id):
        row = self.rows.get(operation_id)
        if row is None:
            raise CustomFilmContractError(
                "Custom Film provider reconciliation state is missing; retry is blocked"
            )
        return copy.deepcopy(row)

    async def prepare_operation(self, **kwargs):
        operation_id = kwargs["operation_id"]
        spec = kwargs["spec"]
        existing = self.rows.get(operation_id)
        if existing is None:
            existing = SimpleNamespace(
                tenant_id=kwargs["tenant_id"],
                video_id=kwargs["video_id"],
                runtime_job_id=kwargs["runtime_job_id"],
                runtime_hash=kwargs["runtime_hash"],
                stage_key=kwargs["stage_key"],
                operation_id=operation_id,
                provider=spec.provider,
                request_hash=spec.request_hash,
                reconciliation_mode=spec.reconciliation_mode,
                state="prepared",
                provider_operation_id=None,
                result=None,
            )
            self.rows[operation_id] = existing
            self.events.append(("prepared", operation_id))
        else:
            assert existing.provider == spec.provider
            assert existing.request_hash == spec.request_hash
            assert existing.reconciliation_mode == spec.reconciliation_mode
        return copy.deepcopy(existing)

    async def mark_submitted(self, operation_id, task_id):
        row = self.rows[operation_id]
        assert row.provider_operation_id in {None, task_id}
        row.provider_operation_id = task_id
        row.state = "submitted"
        self.events.append(("submitted", operation_id, task_id))
        return copy.deepcopy(row)

    async def mark_completed(self, operation_id, result, **_kwargs):
        row = self.rows[operation_id]
        assert row.result in {None, result} if not isinstance(result, dict) else (
            row.result is None or row.result == result
        )
        row.result = copy.deepcopy(result)
        row.state = "completed"
        self.events.append(("completed", operation_id))

    async def mark_reconciliation_required(self, operation_id, detail):
        row = self.rows[operation_id]
        row.state = "reconciliation_required"
        row.reconciliation_detail = detail

    @staticmethod
    def reconciliation_action(record):
        if record.state == "completed":
            return "return_completed"
        if record.state == "submitted":
            if (
                record.reconciliation_mode == operations.RECONCILIATION_QUERY
                and record.provider_operation_id
            ):
                return "query_provider"
        if (
            record.state == "prepared"
            and record.reconciliation_mode
            == operations.RECONCILIATION_IDEMPOTENCY
        ):
            return "retry_same_operation"
        raise CustomFilmContractError("automatic retry is blocked")


class _AsyncContext:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *_args):
        return None


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _AsyncContext(self.conn)


@pytest.mark.asyncio
async def test_mixed_sections_deliver_distinct_values_into_concrete_runner_seams(
    monkeypatch,
):
    submitted = []

    async def mark_submitted(operation_id, provider_task_id):
        submitted.append((operation_id, provider_task_id))

    monkeypatch.setattr(production, "mark_submitted", mark_submitted)
    seams = _FakeSeams(provider_task_id="provider-task-1")
    runner = production.CustomFilmProductionRunner("tenant-1", seams=seams)
    script_a = _adapter("script")
    script_b = _adapter(
        "script",
        section_id="section-b",
        seconds=19,
        profile="power_doctrine_v2",
        language_mode="bilingual",
        dubbing=True,
    )
    result_a = await runner(script_a, (), "custom-film-op:" + "1" * 64)
    result_b = await runner(script_b, (), "custom-film-op:" + "2" * 64)
    assert result_a["scene_ids"] == ["section-a-scene"]
    assert result_b["scene_ids"] == ["section-b-scene"]
    first, second = seams.requests
    assert (first.script_profile, first.exact_seconds, first.role) == (
        "neutral_v1",
        12,
        "evidence",
    )
    assert (second.script_profile, second.exact_seconds, second.role) == (
        "power_doctrine_v2",
        19,
        "explanation",
    )
    assert second.purpose == "Explain why the mechanism matters"
    assert second.language["mode"] == "bilingual"
    assert second.dubbing == {
        "enabled": True,
        "mode": "speech_to_speech",
    }
    assert submitted == [
        ("custom-film-op:" + "1" * 64, "provider-task-1"),
        ("custom-film-op:" + "2" * 64, "provider-task-1"),
    ]


@pytest.mark.asyncio
async def test_voice_and_quality_receive_exact_assignments_behavior_and_laws(
    monkeypatch,
):
    async def mark_submitted(*_args):
        return None

    monkeypatch.setattr(production, "mark_submitted", mark_submitted)
    seams = _FakeSeams(
        provider_task_id="provider-task-voice",
        task_id_per_scene=True,
    )
    journal = _FakeJournal()
    runner = production.CustomFilmProductionRunner(
        "tenant-1",
        seams=seams,
        journal=journal,
    )
    scene_ids = ("scene-1", "scene-2")
    bilingual = _adapter(
        "voice",
        seconds=19,
        language_mode="bilingual",
        dubbing=True,
    )
    parent_operation_id = "custom-film-op:" + "3" * 64
    journal.seed_parent(parent_operation_id, bilingual)
    await runner(
        bilingual,
        scene_ids,
        parent_operation_id,
    )
    await runner(
        _adapter("quality", seconds=19),
        scene_ids,
        "custom-film-op:" + "4" * 64,
    )
    voice_one, voice_two, quality_request = seams.requests
    assert voice_one.scene_ids == ("scene-1",)
    assert voice_two.scene_ids == ("scene-2",)
    assert voice_one.dialogue_audio == voice_two.dialogue_audio == "voice_over"
    assert voice_one.language["mode"] == voice_two.language["mode"] == "bilingual"
    assert voice_one.dubbing["mode"] == voice_two.dubbing["mode"] == "speech_to_speech"
    assert voice_one.exact_seconds == voice_two.exact_seconds == 19
    assert quality_request.scene_ids == scene_ids
    assert quality_request.quality_laws == (
        "source_grounding",
        "visual_cue_fidelity",
    )
    assert quality_request.exact_seconds == 19
    child_rows = [
        row
        for operation_id, row in journal.rows.items()
        if operation_id != parent_operation_id
    ]
    assert len(child_rows) == 2
    assert all(row.state == "completed" for row in child_rows)
    assert {row.provider_operation_id for row in child_rows} == {
        "provider-task-voice:scene-1",
        "provider-task-voice:scene-2",
    }


@pytest.mark.asyncio
async def test_multi_scene_voice_crash_queries_first_child_without_duplicate_create():
    adapter = _adapter(
        "voice",
        seconds=19,
        language_mode="bilingual",
        dubbing=True,
    )
    parent_operation_id = "custom-film-op:" + "c" * 64
    journal = _FakeJournal()
    journal.seed_parent(parent_operation_id, adapter)
    seams = _FakeSeams(
        provider_task_id="provider-task",
        task_id_per_scene=True,
        fail_after_submit_scene="scene-1",
    )
    runner = production.CustomFilmProductionRunner(
        "tenant-1",
        seams=seams,
        journal=journal,
    )
    with pytest.raises(RuntimeError, match="synthetic crash"):
        await runner(
            adapter,
            ("scene-1", "scene-2"),
            parent_operation_id,
        )
    assert [request.scene_ids for request in seams.requests] == [("scene-1",)]
    assert len(
        [event for event in journal.events if event[0] == "prepared"]
    ) == 1

    result = await runner(
        adapter,
        ("scene-1", "scene-2"),
        parent_operation_id,
    )
    assert result["scene_ids"] == ["scene-1", "scene-2"]
    assert [request.scene_ids for request in seams.requests] == [
        ("scene-1",),
        ("scene-2",),
    ]
    assert [(request.scene_ids, task_id) for request, task_id in seams.queries] == [
        (("scene-1",), "provider-task:scene-1")
    ]
    assert len(
        [event for event in journal.events if event[0] == "prepared"]
    ) == 2
    completed = [event for event in journal.events if event[0] == "completed"]
    assert len(completed) == 2
    first_completed_index = journal.events.index(completed[0])
    second_prepared_index = [
        index
        for index, event in enumerate(journal.events)
        if event[0] == "prepared"
    ][1]
    assert first_completed_index < second_prepared_index


@pytest.mark.asyncio
async def test_direct_voice_child_crash_fails_closed_without_duplicate_create():
    adapter = _adapter("voice")
    parent_operation_id = "custom-film-op:" + "d" * 64
    journal = _FakeJournal()
    journal.seed_parent(parent_operation_id, adapter)
    seams = _FakeSeams(
        mode=operations.RECONCILIATION_QUERY,
        fail_after_submit_scene="scene-1",
    )
    runner = production.CustomFilmProductionRunner(
        "tenant-1",
        seams=seams,
        journal=journal,
    )
    with pytest.raises(RuntimeError, match="synthetic crash"):
        await runner(adapter, ("scene-1",), parent_operation_id)
    with pytest.raises(CustomFilmContractError, match="automatic retry"):
        await runner(adapter, ("scene-1",), parent_operation_id)
    assert [request.scene_ids for request in seams.requests] == [("scene-1",)]
    child = next(
        row
        for operation_id, row in journal.rows.items()
        if operation_id != parent_operation_id
    )
    assert child.state == "reconciliation_required"


@pytest.mark.asyncio
async def test_completed_voice_child_retry_returns_journal_result_without_seam_work():
    adapter = _adapter("voice")
    parent_operation_id = "custom-film-op:" + "e" * 64

    class CrashAfterCompletionJournal(_FakeJournal):
        def __init__(self):
            super().__init__()
            self.crash_once = True
            self.completed_writes = 0

        async def mark_completed(self, operation_id, result, **kwargs):
            self.completed_writes += 1
            await super().mark_completed(operation_id, result, **kwargs)
            if self.crash_once:
                self.crash_once = False
                raise RuntimeError("synthetic crash after child completion")

    journal = CrashAfterCompletionJournal()
    journal.seed_parent(parent_operation_id, adapter)
    seams = _FakeSeams(provider_task_id="provider-task-scene-1")
    runner = production.CustomFilmProductionRunner(
        "tenant-1",
        seams=seams,
        journal=journal,
    )
    with pytest.raises(RuntimeError, match="after child completion"):
        await runner(adapter, ("scene-1",), parent_operation_id)

    child = next(
        row
        for operation_id, row in journal.rows.items()
        if operation_id != parent_operation_id
    )
    completed_result = copy.deepcopy(child.result)
    assert child.state == "completed"
    assert len(seams.requests) == 1
    assert seams.checkpoint_requests == []

    result = await runner(adapter, ("scene-1",), parent_operation_id)
    assert result["child_operations"][0]["result"] == completed_result
    assert len(seams.requests) == 1
    assert seams.queries == []
    assert seams.checkpoint_requests == []
    assert journal.completed_writes == 1


@pytest.mark.asyncio
async def test_unresolved_voice_child_checkpoint_is_completed_with_canonical_result():
    adapter = _adapter("voice", seconds=13)
    parent_operation_id = "custom-film-op:" + "f" * 64
    journal = _FakeJournal()
    journal.seed_parent(parent_operation_id, adapter)
    seams = _FakeSeams(
        provider_task_id="provider-task-scene-1",
        fail_after_submit_scene="scene-1",
    )
    runner = production.CustomFilmProductionRunner(
        "tenant-1",
        seams=seams,
        journal=journal,
    )
    with pytest.raises(RuntimeError, match="after provider submission"):
        await runner(adapter, ("scene-1",), parent_operation_id)
    seams.checkpoints[("scene-1",)] = {
        "artifact_id": "artifact-1",
        "artifact_url": "https://drive.test/artifact-1",
        "reused_artifact": True,
    }

    result = await runner(adapter, ("scene-1",), parent_operation_id)
    child_result = result["child_operations"][0]["result"]
    assert child_result["scene_ids"] == ["scene-1"]
    assert child_result["voiced_scene_ids"] == ["scene-1"]
    assert child_result["voice_behavior"] == "narration"
    assert child_result["language"] == adapter.language
    assert child_result["dubbing"] == adapter.dubbing
    assert child_result["dialogue_audio"] == "voice_over"
    assert child_result["exact_seconds"] == 13
    assert child_result["artifacts"] == [
        {
            "scene_id": "scene-1",
            "artifact_id": "artifact-1",
            "artifact_url": "https://drive.test/artifact-1",
            "reused": True,
        }
    ]
    assert seams.queries == []
    child = next(
        row
        for operation_id, row in journal.rows.items()
        if operation_id != parent_operation_id
    )
    assert child.state == "completed"
    assert child.result == child_result


def test_request_hash_binds_exact_values_assignments_and_operation_identity():
    seams = _FakeSeams()
    runner = production.CustomFilmProductionRunner("tenant-1", seams=seams)
    adapter = _adapter("voice")
    operation_id = "custom-film-op:" + "5" * 64
    first = runner.operation_spec(adapter, ("scene-1",), operation_id)
    assert first == runner.operation_spec(adapter, ("scene-1",), operation_id)
    changed_scene = runner.operation_spec(adapter, ("scene-2",), operation_id)
    changed_seconds = runner.operation_spec(
        _adapter("voice", seconds=13),
        ("scene-1",),
        operation_id,
    )
    changed_profile = runner.operation_spec(
        _adapter("voice", profile="power_doctrine_v2"),
        ("scene-1",),
        operation_id,
    )
    assert len(
        {
            first.request_hash,
            changed_scene.request_hash,
            changed_seconds.request_hash,
            changed_profile.request_hash,
        }
    ) == 4


@pytest.mark.asyncio
async def test_query_reconciliation_uses_same_operation_and_provider_task():
    seams = _FakeSeams()
    runner = production.CustomFilmProductionRunner("tenant-1", seams=seams)
    adapter = _adapter("quality")
    operation_id = "custom-film-op:" + "6" * 64
    record = SimpleNamespace(
        operation_id=operation_id,
        provider_operation_id="provider-task-6",
    )
    result = await runner.reconcile(
        adapter,
        ("scene-1",),
        operation_id,
        record,
    )
    assert result == {"reconciled": True}
    assert seams.queries[0][0].scene_ids == ("scene-1",)
    assert seams.queries[0][1] == "provider-task-6"


@pytest.mark.asyncio
async def test_missing_duplicate_or_unsupported_assignment_stops_before_seam():
    seams = _FakeSeams()
    runner = production.CustomFilmProductionRunner("tenant-1", seams=seams)
    with pytest.raises(CustomFilmContractError, match="assignments"):
        await runner(
            _adapter("voice"),
            (),
            "custom-film-op:" + "7" * 64,
        )
    with pytest.raises(CustomFilmContractError, match="assignments"):
        await runner(
            _adapter("quality"),
            ("scene-1", "scene-1"),
            "custom-film-op:" + "8" * 64,
        )
    picture_spec = runner.operation_spec(
        _adapter("pictures"),
        ("scene-1",),
        "custom-film-op:" + "9" * 64,
    )
    assert picture_spec.provider == "storyengine-section-pictures"
    invalid_combo = _adapter(
        "voice",
        dialogue_audio="grok_native",
        language_mode="narrator",
    )
    with pytest.raises(CustomFilmContractError, match="language, dubbing"):
        await runner(
            invalid_combo,
            ("scene-1",),
            "custom-film-op:" + "d" * 64,
        )
    assert seams.requests == []


@pytest.mark.asyncio
async def test_grok_native_voice_is_local_idempotent_and_never_calls_voice_client(
    monkeypatch,
):
    request = production._request(
        _adapter(
            "voice",
            dialogue_audio="grok_native",
            language_mode="simple_single_language",
        ),
        ("scene-1",),
        "custom-film-op:" + "a" * 64,
    )
    seams = production.SharedSectionProductionSeams("tenant-1")

    async def rows(_request):
        return [{"id": "scene-1", "scene": 1, "scene_text": "Hola"}]

    async def must_not_initialize():
        raise AssertionError("voice provider must not initialize")

    monkeypatch.setattr(seams, "_scene_rows", rows)
    monkeypatch.setattr(seams, "_ready_executor", must_not_initialize)
    assert seams.operation_metadata(request) == (
        "storyengine-local",
        operations.RECONCILIATION_IDEMPOTENCY,
    )
    result = await seams._voice(request)
    assert result["voice_behavior"] == "performed_in_clip"
    assert result["scene_ids"] == ["scene-1"]


@pytest.mark.asyncio
async def test_shared_quality_seam_passes_approved_laws_to_real_critic_contract(
    monkeypatch,
):
    request = production._request(
        _adapter("quality", seconds=17),
        ("scene-1",),
        "custom-film-op:" + "b" * 64,
    )
    seams = production.SharedSectionProductionSeams("tenant-1")
    calls = []

    async def rows(_request):
        return [{"id": "scene-1", "scene": 1, "scene_text": "Sourced evidence."}]

    class Executor:
        def __init__(self):
            self._pipeline = SimpleNamespace(anthropic=object())

        async def _ensure_initialized(self):
            return None

    async def critique(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(
            failing_gates=[],
            needs_revision=False,
            verdict="pass",
            score=97,
        )

    monkeypatch.setattr(seams, "_scene_rows", rows)
    async def media_preflight(_request):
        return {"timing_status": "exact", "timing_transforms": []}
    monkeypatch.setattr(seams, "_quality_media_preflight", media_preflight)
    seams._executor = Executor()
    monkeypatch.setattr("script_quality.critique_script", critique)
    result = await seams._quality(request)
    assert result["quality_laws"] == [
        "source_grounding",
        "visual_cue_fidelity",
    ]
    assert result["exact_seconds"] == 17
    assert "source_grounding:" in calls[0][1]["rules_text"]
    assert calls[0][1]["severity_by_rule"] == {
        "source_grounding": "hard_gate",
        "visual_cue_fidelity": "hard_gate",
    }


@pytest.mark.asyncio
async def test_shared_script_seam_uses_profile_purpose_language_exact_seconds_and_stable_id(
    monkeypatch,
):
    request = production._request(
        _adapter(
            "script",
            section_id="section-b",
            seconds=19,
            profile="power_doctrine_v2",
            language_mode="bilingual",
            dubbing=True,
        ),
        (),
        "custom-film-op:" + "e" * 64,
    )
    seams = production.SharedSectionProductionSeams("tenant-1")
    calls = []
    profile = object()

    class Executor:
        def __init__(self):
            self._pipeline = SimpleNamespace(anthropic=object())

        async def _ensure_initialized(self):
            return None

        async def _get_video(self, video_id):
            assert video_id == "video-1"
            return {
                "video_title": "A mixed film",
                "research_payload": {"fact_sheet": "Sourced facts"},
            }

    async def generate(client, brief, **kwargs):
        calls.append((client, copy.deepcopy(brief), kwargs))
        return {
            "script": "A bilingual sourced explanation.",
            "validation": {"valid": True},
        }

    class Connection:
        def __init__(self):
            self.ids = []
            self.updates = []

        async def fetchrow(self, sql, *args):
            assert "INSERT INTO scripts" in sql
            self.ids.append(str(args[0]))
            return {"id": args[0]}

        async def execute(self, sql, *args):
            assert "UPDATE videos" in sql
            self.updates.append(args)
            return "UPDATE 1"

    conn = Connection()

    async def get_pool():
        return _Pool(conn)

    seams._executor = Executor()
    monkeypatch.setattr(
        "script.brief_translator.script_generator.generate_script",
        generate,
    )
    monkeypatch.setattr(
        "shared.profiles.script.load_script_profile",
        lambda profile_id: profile
        if profile_id == "power_doctrine_v2"
        else None,
    )
    monkeypatch.setattr("database.get_pool", get_pool)
    first = await seams._script(request)
    second = await seams._script(request)
    assert first["scene_ids"] == second["scene_ids"]
    assert conn.ids == [first["scene_ids"][0], first["scene_ids"][0]]
    assert calls[0][2]["profile"] is profile
    config = calls[0][2]["config"]
    assert config.total_seconds == 19
    assert config.total_script_words == 48
    guidance = calls[0][1]["writer_guidance"]
    assert "Explain why the mechanism matters" in guidance
    assert "exactly 19 seconds" in guidance
    assert "bilingual speaker turns" in guidance
    assert "speech_to_speech" in guidance
    assert "source_grounding" in guidance


@pytest.mark.asyncio
async def test_shared_voice_seam_filters_assigned_dialogue_and_journals_kie_task(
    monkeypatch,
):
    request = production._request(
        _adapter(
            "voice",
            seconds=19,
            language_mode="bilingual",
            dubbing=True,
        ),
        ("scene-1",),
        "custom-film-op:" + "f" * 64,
    )
    seams = production.SharedSectionProductionSeams("tenant-1")
    submitted = []
    voice_calls = []

    async def rows(_request):
        return [
            {
                "id": "scene-1",
                "scene": 1,
                "scene_text": "Narrator setup.\nAna: Hola, ¿cómo estás?",
                "voice_id": "voice-1",
                "voice_status": None,
                "voice_over_url": None,
            }
        ]

    class Voice:
        async def generate_and_wait(
            self,
            text,
            voice_id=None,
            task_id_callback=None,
        ):
            voice_calls.append((text, voice_id))
            await task_id_callback("kie-task-section-1")
            return "/tmp/fake-section.mp3"

        async def download_audio(self, path):
            assert path == "/tmp/fake-section.mp3"
            return b"fake-audio"

        async def query_task(self, task_id):
            assert task_id == "kie-task-section-1"
            return {"audio_content": b"fake-audio"}

    class Google:
        def __init__(self):
            self.files = {}

        def get_or_create_folder(self, name):
            assert name == "custom-film-video-1"
            return {"id": "folder-1"}

        def search_file(self, filename, folder_id):
            assert folder_id == "folder-1"
            return self.files.get(filename)

        def upload_audio(self, content, filename, folder_id):
            assert content == b"fake-audio"
            assert filename.startswith("custom-film-voice-")
            assert folder_id == "folder-1"
            result = {"id": "drive-audio-1"}
            self.files[filename] = result
            return result

    class Executor:
        def __init__(self):
            self._pipeline = SimpleNamespace(
                elevenlabs=Voice(),
                google=Google(),
            )

        async def _ensure_initialized(self):
            return None

    class Connection:
        async def execute(self, sql, *args):
            assert "UPDATE scripts" in sql
            assert args[2] == "scene-1"
            assert "drive-audio-1" in args[3]
            assert args[4].startswith("custom-film-voice:")
            return "UPDATE 1"

    async def get_pool():
        return _Pool(Connection())

    async def on_submitted(task_id):
        submitted.append(task_id)

    monkeypatch.setattr(seams, "_scene_rows", rows)
    seams._executor = Executor()
    monkeypatch.setattr("database.get_pool", get_pool)
    assert seams.operation_metadata(request) == (
        "tenant-voice-generation",
        operations.RECONCILIATION_QUERY,
    )
    result = await seams._voice(request, on_submitted=on_submitted)
    assert submitted == ["kie-task-section-1"]
    assert voice_calls == [("Narrator setup.", "voice-1")]
    assert result["scene_ids"] == ["scene-1"]
    assert result["voiced_scene_ids"] == ["scene-1"]
    assert result["voice_behavior"] == (
        "narration_plus_clip_speech_to_speech"
    )
    assert result["language"] == {"mode": "bilingual"}
    assert result["dubbing"]["mode"] == "speech_to_speech"
    assert result["exact_seconds"] == 19
    reconciled = await seams.query(request, "kie-task-section-1")
    assert reconciled.provider_operation_id == "kie-task-section-1"
    assert reconciled.result["voiced_scene_ids"] == ["scene-1"]


@pytest.mark.asyncio
async def test_voice_artifact_checkpoint_reuses_one_upload_after_outer_crash(
    monkeypatch,
):
    request = production._request(
        _adapter("voice", seconds=12),
        ("scene-1",),
        "custom-film-op:" + "9" * 64,
    )
    seams = production.SharedSectionProductionSeams("tenant-1")
    row = {
        "id": "scene-1",
        "scene": 1,
        "scene_text": "Narration that must survive recovery.",
        "voice_id": "voice-1",
        "voice_status": None,
        "voice_over_url": None,
    }
    counts = {"provider": 0, "upload": 0, "search": 0, "db": 0}
    drive_file = {}

    async def rows(_request):
        return [copy.deepcopy(row)]

    class Voice:
        async def generate_and_wait(
            self, _text, voice_id=None, task_id_callback=None
        ):
            counts["provider"] += 1
            await task_id_callback("kie-task-artifact")
            return "/tmp/fake-artifact.mp3"

        async def download_audio(self, _path):
            return b"audio"

    class Google:
        def get_or_create_folder(self, _name):
            return {"id": "folder-1"}

        def search_file(self, _filename, _folder_id):
            counts["search"] += 1
            return copy.deepcopy(drive_file) or None

        def upload_audio(self, _content, _filename, _folder_id):
            counts["upload"] += 1
            drive_file["id"] = "drive-stable-1"
            return copy.deepcopy(drive_file)

    class Executor:
        def __init__(self):
            self._pipeline = SimpleNamespace(
                elevenlabs=Voice(),
                google=Google(),
            )

        async def _ensure_initialized(self):
            return None

    class Connection:
        async def execute(self, _sql, *args):
            counts["db"] += 1
            if counts["db"] == 1:
                raise RuntimeError("synthetic crash after upload")
            row["voice_over_url"] = args[3]
            row["voice_status"] = args[4]
            return "UPDATE 1"

    async def get_pool():
        return _Pool(Connection())

    async def submitted(_task_id):
        return None

    monkeypatch.setattr(seams, "_scene_rows", rows)
    seams._executor = Executor()
    monkeypatch.setattr("database.get_pool", get_pool)
    with pytest.raises(RuntimeError, match="synthetic crash after upload"):
        await seams._voice(request, on_submitted=submitted)
    # Recovery finds the stable operation-derived artifact by name and
    # checkpoints it without a second provider request or upload.
    recovered = await seams.checkpoint(request)
    assert recovered is not None
    assert recovered.result["reused_artifact"] is True
    assert recovered.result["artifact_url"] == row["voice_over_url"]
    # A later outer-operation retry reuses the DB checkpoint directly.
    recovered_again = await seams.checkpoint(request)
    assert recovered_again.result["artifact_url"] == row["voice_over_url"]
    assert counts == {"provider": 1, "upload": 1, "search": 2, "db": 2}


@pytest.mark.asyncio
async def test_worker_installs_concrete_runner_while_legacy_handlers_stay_unchanged(
    monkeypatch,
):
    captured = {}
    render_calls = []
    publication_calls = []
    runtime_hash = "c" * 64
    runtime_job_id = "custom-film-runtime:" + runtime_hash

    async def consume(tenant_id, video_id, job_id, **kwargs):
        captured.update(
            tenant_id=tenant_id,
            video_id=video_id,
            job_id=job_id,
            **kwargs,
        )
        finalization = await kwargs["finalizer"](
            tenant_id,
            video_id,
            job_id,
            {"video_id": video_id, "runtime_hash": runtime_hash},
        )
        return {"status": "completed", "finalization": finalization}

    class Executor:
        def __init__(self, tenant_id):
            self.tenant_id = tenant_id

        async def run_render(self, video_id, **kwargs):
            render_calls.append((self.tenant_id, video_id, kwargs))
            return {
                "status": "rendered",
                "final_video_url": "storage://exact-film",
                "render_engine": "remotion",
            }

        async def run_upload(self, *_args, **_kwargs):
            publication_calls.append("upload")
            raise AssertionError("automatic finalization must not publish")

    monkeypatch.setattr(
        "custom_film_section_runtime.consume_runtime_schedule",
        consume,
    )
    monkeypatch.setattr("pipeline_executor.PipelineExecutor", Executor)
    result = await worker.arq_run_custom_film_runtime(
        {"job_try": 1},
        "video-1",
        "tenant-1",
        2,
        runtime_job_id,
    )
    assert result["status"] == "completed"
    assert result["finalization"]["final_video_url"] == "storage://exact-film"
    assert isinstance(
        captured["stage_runner"],
        production.CustomFilmProductionRunner,
    )
    assert callable(captured["finalizer"])
    assert captured["attempt"] == 2
    assert render_calls == [
        (
            "tenant-1",
            "video-1",
            {"custom_film_runtime_job_id": runtime_job_id},
        )
    ]
    assert publication_calls == []
    assert worker.arq_run_script.__name__ == "arq_run_script"
    assert worker.arq_run_voice.__name__ == "arq_run_voice"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "render_result",
    [
        {"status": "failed", "error": "renderer stopped"},
        {"status": "rendered", "render_engine": "remotion"},
        {
            "status": "rendered",
            "final_video_url": "storage://film",
            "render_engine": "unknown",
        },
    ],
)
async def test_worker_rejects_incomplete_final_artifact_result(
    monkeypatch,
    render_result,
):
    runtime_hash = "d" * 64
    runtime_job_id = "custom-film-runtime:" + runtime_hash

    async def consume(tenant_id, video_id, job_id, **kwargs):
        return await kwargs["finalizer"](
            tenant_id,
            video_id,
            job_id,
            {"video_id": video_id, "runtime_hash": runtime_hash},
        )

    class Executor:
        def __init__(self, _tenant_id):
            pass

        async def run_render(self, _video_id, **_kwargs):
            return copy.deepcopy(render_result)

    monkeypatch.setattr(
        "custom_film_section_runtime.consume_runtime_schedule",
        consume,
    )
    monkeypatch.setattr("pipeline_executor.PipelineExecutor", Executor)
    with pytest.raises(
        CustomFilmContractError,
        match="no exact final artifact",
    ):
        await worker.arq_run_custom_film_runtime(
            {"job_try": 1},
            "video-1",
            "tenant-1",
            1,
            runtime_job_id,
        )


@pytest.mark.asyncio
async def test_pipeline_custom_film_render_forwards_exact_active_runtime_only(
    monkeypatch,
):
    runtime_job_id = "custom-film-runtime:" + ("e" * 64)
    captured = {}
    executor = object.__new__(pipeline_executor.PipelineExecutor)
    executor.tenant_id = "tenant-1"

    async def log_activity(*_args, **_kwargs):
        return None

    async def log_transition(*_args, **_kwargs):
        return None

    async def charge(*_args, **_kwargs):
        return None

    async def render(video_id, tenant_id, **kwargs):
        captured.update(video_id=video_id, tenant_id=tenant_id, **kwargs)
        return {
            "status": "rendered",
            "video_id": video_id,
            "final_video_url": "storage://exact-film",
            "render_engine": "remotion",
            "section_count": 4,
            "duration_seconds": 300,
            "resolution": "1920x1080",
        }

    executor._log_activity = log_activity
    executor._log_transition = log_transition
    executor._charge_render_minutes = charge
    monkeypatch.setattr(
        "custom_film_compositor.render_custom_film_video",
        render,
    )
    result = await executor._run_custom_film_render(
        "video-1",
        {"video_title": "Exact film"},
        "ready_for_scripting",
        runtime_job_id=runtime_job_id,
    )
    assert result["status"] == "rendered"
    assert captured["runtime_job_id"] == runtime_job_id
    assert captured["render_engine"] == "showcase_auto"
    assert callable(captured["remotion_renderer"])
    assert "run_upload" not in captured


@pytest.mark.asyncio
async def test_kie_voice_exposes_real_task_id_before_polling_without_network(
    monkeypatch,
):
    events = []

    class Response:
        def __init__(self, payload=None, content=b"", headers=None):
            self._payload = payload or {}
            self.content = content
            self.headers = headers or {}
            self.text = "present"
            self.status_code = 200

        def json(self):
            return copy.deepcopy(self._payload)

        def raise_for_status(self):
            return None

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            events.append("create")
            return Response({"data": {"taskId": "kie-task-1"}})

        async def get(self, url, **kwargs):
            if kwargs.get("params"):
                events.append("poll")
                return Response(
                    {
                        "data": {
                            "state": "success",
                            "resultJson": {
                                "resultUrls": ["https://fake.invalid/audio"]
                            },
                        }
                    }
                )
            assert url == "https://fake.invalid/audio"
            events.append("download")
            return Response(content=b"fake-mp3")

    async def no_sleep(_seconds):
        return None

    async def submitted(task_id):
        events.append(f"submitted:{task_id}")

    monkeypatch.setattr(
        "shared.clients.elevenlabs_client.httpx.AsyncClient",
        lambda **_kwargs: Client(),
    )
    monkeypatch.setattr("asyncio.sleep", no_sleep)
    client = ElevenLabsClient(api_key="tenant-key", voice_id="voice-1")
    client._kie_mode = True
    result = await client._generate_via_kie(
        "Narration",
        "voice-1",
        0.5,
        0.75,
        task_id_callback=submitted,
    )
    assert result["audio_content"] == b"fake-mp3"
    assert events == [
        "create",
        "submitted:kie-task-1",
        "poll",
        "download",
    ]


def test_visual_request_carries_exact_static_and_animated_contracts():
    static = production._request(
        _adapter("pictures", seconds=17, static=True),
        ("static-scene",),
        "custom-film-op:" + "1" * 64,
    )
    animated = production._request(
        _adapter("clips", seconds=29),
        ("animated-scene",),
        "custom-film-op:" + "2" * 64,
    )
    assert static.render_mode == "static_docu"
    assert static.visual_profile == "neutral_v1"
    assert static.image_density == {
        "mode": "per_item",
        "target": 3,
        "minimum": 2,
    }
    assert static.animation == {"enabled": False, "mode": "ken_burns"}
    assert static.camera == {"mode": "three_complementary_views"}
    assert static.exact_seconds == 17
    assert animated.render_mode == "coverage"
    assert animated.image_density["mode"] == "visual_cue"
    assert animated.animation == {"enabled": True, "mode": "grok_native"}
    assert animated.camera == {"mode": "investigative_coverage"}
    assert animated.exact_seconds == 29


def test_visual_request_rejects_tampered_static_motion_before_seam():
    adapter = _adapter("motion", static=True)
    with pytest.raises(
        CustomFilmContractError,
        match="Static Custom Film sections cannot schedule",
    ):
        production._request(
            adapter,
            ("scene-1",),
            "custom-film-op:" + "3" * 64,
        )
    tampered = copy.copy(_adapter("pictures"))
    object.__setattr__(tampered, "camera", {"mode": "three_complementary_views"})
    with pytest.raises(
        CustomFilmContractError,
        match="Unsupported Custom Film imagery",
    ):
        production._request(
            tampered,
            ("scene-1",),
            "custom-film-op:" + "4" * 64,
        )


@pytest.mark.asyncio
async def test_media_children_record_tasks_and_reconcile_without_duplicate():
    adapter = _adapter("pictures", seconds=23, media_count=2)
    parent_id = "custom-film-op:" + "5" * 64
    journal = _FakeJournal()
    journal.seed_parent(parent_id, adapter)
    seams = _FakeSeams(
        operations.RECONCILIATION_QUERY,
        provider_task_id="image-task",
        task_id_per_scene=True,
        fail_after_submit_scene="scene-b",
    )
    runner = production.CustomFilmProductionRunner(
        "tenant-1",
        seams=seams,
        journal=journal,
    )
    with pytest.raises(RuntimeError, match="synthetic crash"):
        await runner(adapter, ("scene-a", "scene-b"), parent_id)
    result = await runner(adapter, ("scene-a", "scene-b"), parent_id)
    assert [item["scene_id"] for item in result["child_operations"]] == [
        "scene-a",
        "scene-b",
    ]
    assert [request.scene_ids for request in seams.requests] == [
        ("scene-a",),
        ("scene-b",),
    ]
    assert seams.queries[0][1] == "image-task:scene-b"
    child_states = [
        row.state
        for operation_id, row in journal.rows.items()
        if operation_id != parent_id
    ]
    assert child_states == ["completed", "completed"]


@pytest.mark.asyncio
async def test_shared_picture_seam_routes_real_static_and_coverage_inputs(
    monkeypatch,
):
    seams = production.SharedSectionProductionSeams("tenant-1")
    captured = []
    recorded = []
    raw_call_counts = {}

    async def scene_number(_request):
        return 7

    async def checkpoint(request):
        return {
            "scene_ids": list(request.scene_ids),
            "artifacts": [
                {"artifact_id": "asset-1", "artifact_url": "fake://asset-1"}
            ],
        }

    async def raw_rows(request):
        key = request.render_mode
        raw_call_counts[key] = raw_call_counts.get(key, 0) + 1
        legacy = {
            "id": f"legacy-{key}",
            "status": "done",
            "image_url": "fake://legacy",
            "drive_image_url": "fake://legacy",
            "generation_method": (
                "static_docu" if request.render_mode == "static_docu" else "coverage"
            ),
        }
        if raw_call_counts[key] == 1:
            return [legacy]
        count = request.expected_still_images
        method = "static_docu" if request.render_mode == "static_docu" else "coverage"
        return [legacy] + [
            {
                "id": f"{key}-asset-{index}",
                "status": "done",
                "image_url": f"fake://image/{index}",
                "drive_image_url": f"fake://image/{index}",
                "generation_method": method,
            }
            for index in range(count)
        ]

    async def record(request, rows, **_kwargs):
        recorded.append((request.render_mode, [row["id"] for row in rows]))
        return None

    async def static_call(video_id, tenant_id, **kwargs):
        captured.append(("static", video_id, tenant_id, kwargs))
        return {"status": "completed"}

    async def coverage_call(video_id, tenant_id, **kwargs):
        captured.append(("coverage", video_id, tenant_id, kwargs))
        return {"status": "completed"}

    monkeypatch.setattr(seams, "_scene_number", scene_number)
    monkeypatch.setattr(seams, "_media_artifact_checkpoint", checkpoint)
    monkeypatch.setattr(seams, "_raw_asset_rows", raw_rows)
    monkeypatch.setattr(seams, "_record_media_provenance", record)
    monkeypatch.setattr(
        "static_docu.generate_static_images_for_video",
        static_call,
    )
    monkeypatch.setattr(
        "scripts.coverage_to_app.generate_coverage_for_video",
        coverage_call,
    )
    static_request = production._request(
        _adapter("pictures", seconds=17, static=True),
        ("scene-static",),
        "custom-film-op:" + "6" * 64,
    )
    animated_request = production._request(
        _adapter("pictures", seconds=31),
        ("scene-animated",),
        "custom-film-op:" + "7" * 64,
    )
    await seams._pictures(static_request)
    await seams._pictures(animated_request)
    assert captured[0][3]["only_scenes"] == {7}
    assert captured[0][3]["section_contract"]["camera"] == {
        "mode": "three_complementary_views"
    }
    assert captured[0][3]["section_contract"]["exact_seconds"] == 17
    assert captured[1][3]["section_contract"]["visual_profile"] == "neutral_v1"
    assert captured[1][3]["section_contract"]["image_density"]["mode"] == (
        "visual_cue"
    )
    assert captured[1][3]["section_contract"]["exact_seconds"] == 31
    assert captured[1][3]["section_contract"]["auxiliary_image_policy"] == {
        "auto_cast_generation": "forbidden",
        "auto_character_population": "forbidden",
    }
    assert recorded == [
        (
            "static_docu",
            ["static_docu-asset-0", "static_docu-asset-1", "static_docu-asset-2"],
        ),
        ("coverage", ["coverage-asset-0"]),
    ]


@pytest.mark.asyncio
async def test_shared_motion_and_clip_seams_receive_camera_and_exact_seconds(
    monkeypatch,
):
    seams = production.SharedSectionProductionSeams("tenant-1")
    motion_calls = []
    clip_calls = []

    class Executor:
        def __init__(self):
            self._pipeline = SimpleNamespace(anthropic=object())

        async def _ensure_initialized(self):
            return None

        async def run_clip_generation(self, video_id, **kwargs):
            clip_calls.append((video_id, kwargs))
            return {
                "status": "completed",
                "requested_asset_ids": ["asset-1"],
                "generated_asset_ids": ["asset-1"],
                "generated_artifacts": [
                    {
                        "asset_id": "asset-1",
                        "video_clip_url": "fake://clip/1",
                        "provider_model": "grok-imagine",
                        "duration_seconds": "6",
                    }
                ],
                "clips_generated": 1,
                "clips_failed": 0,
                "clips_blocked": 0,
                "clips_in_progress_elsewhere": 0,
            }

    async def scene_number(_request):
        return 4

    async def checkpoint(request):
        return {
            "scene_ids": list(request.scene_ids),
            "artifacts": [
                {
                    "artifact_id": f"{request.stage}-asset",
                    "artifact_url": f"fake://{request.stage}-asset",
                }
            ],
        }

    async def write_motion(*args, **kwargs):
        motion_calls.append((args, kwargs))
        return {
            "written": 1,
            "asset_ids": ["asset-1"],
            "artifacts": [
                {
                    "asset_id": "asset-1",
                    "video_prompt": "Locked camera move",
                }
            ],
        }

    async def completed_rows(*_args, **_kwargs):
        return [
            {
                "id": "asset-1",
                "status": "done",
                "image_url": "fake://image/1",
                "drive_image_url": "fake://image/1",
                "generation_method": "coverage",
            }
        ]

    raw_calls = {"motion": 0, "clips": 0}

    async def raw_rows(request):
        raw_calls[request.stage] += 1
        motion_done = request.stage == "clips" or raw_calls[request.stage] > 1
        clip_done = request.stage == "clips" and raw_calls[request.stage] > 1
        return [
            {
                "id": "asset-1",
                "status": "done",
                "image_url": "fake://image/1",
                "drive_image_url": "fake://image/1",
                "video_prompt": "Locked camera move" if motion_done else None,
                "video_clip_url": "fake://clip/1" if clip_done else None,
                "model_used": "grok-imagine" if clip_done else None,
                "video_duration": "6" if clip_done else None,
                "duration_seconds": "37",
                "assigned_video_duration": "37",
                "generation_method": "coverage",
            }
        ]

    async def provenance_transition(*_args, **_kwargs):
        return None

    class Conn:
        async def execute(self, *_args):
            return "UPDATE 1"

        def transaction(self):
            return _AsyncContext(None)

    async def get_pool():
        return _Pool(Conn())

    monkeypatch.setattr(seams, "_scene_number", scene_number)
    monkeypatch.setattr(seams, "_media_artifact_checkpoint", checkpoint)
    monkeypatch.setattr(seams, "_section_completed_rows", completed_rows)
    monkeypatch.setattr(seams, "_raw_asset_rows", raw_rows)
    monkeypatch.setattr(
        seams,
        "_prepare_media_provenance",
        provenance_transition,
    )
    monkeypatch.setattr(
        seams,
        "_complete_media_provenance",
        provenance_transition,
    )
    monkeypatch.setattr("database.get_pool", get_pool)
    seams._executor = Executor()
    monkeypatch.setattr(
        "scripts.coverage_to_app._write_motion_prompts",
        write_motion,
    )
    monkeypatch.setattr(
        "shared.channel_profile.claude_model_for_direct_client",
        lambda _client: "claude-test",
    )
    request_motion = production._request(
        _adapter("motion", seconds=37),
        ("scene-1",),
        "custom-film-op:" + "8" * 64,
    )
    request_clips = production._request(
        _adapter("clips", seconds=37),
        ("scene-1",),
        "custom-film-op:" + "9" * 64,
    )
    await seams._motion(request_motion)
    await seams._clips(request_clips)
    assert motion_calls[0][1]["section_contract"]["camera"] == {
        "mode": "investigative_coverage"
    }
    assert motion_calls[0][1]["section_contract"]["exact_seconds"] == 37
    assert clip_calls[0][1]["asset_ids"] == ["asset-1"]
    assert clip_calls[0][1]["section_contract"]["animation"] == {
        "enabled": True,
        "mode": "grok_native",
    }
    assert clip_calls[0][1]["section_contract"]["exact_seconds"] == 37
