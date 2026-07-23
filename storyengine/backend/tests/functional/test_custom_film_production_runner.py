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
) -> SectionStageAdapter:
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
        render_mode="coverage",
        script_profile=profile,
        visual_profile="neutral_v1",
        dialogue_audio=dialogue_audio,
        image_density={"mode": "visual_cue", "target_per_minute": 8},
        language={"mode": language_mode},
        dubbing={
            "enabled": dubbing,
            "mode": "speech_to_speech" if dubbing else "none",
        },
        animation={"enabled": True, "mode": "grok_native"},
        segmentation={
            "mode": (
                "speaker_turn"
                if dubbing or language_mode == "simple_single_language"
                else "visual_cue"
            )
        },
        camera={"mode": "investigative_coverage"},
        quality_laws=(
            "source_grounding",
            "visual_cue_fidelity",
        ),
        image_source="generate",
        provenance={"script_profile": [profile]},
        estimated_media={"voice_tracks": 2 if dubbing else 1},
    )


class _FakeSeams:
    def __init__(
        self,
        mode=operations.RECONCILIATION_QUERY,
        *,
        provider_task_id: str | None = None,
    ):
        self.mode = mode
        self.provider_task_id = provider_task_id
        self.requests = []
        self.queries = []

    def operation_metadata(self, request):
        return f"fake-{request.stage}", self.mode

    async def submit(self, request, *, on_submitted):
        self.requests.append(request)
        if self.provider_task_id:
            await on_submitted(self.provider_task_id)
        result = {
            "exact_seconds": request.exact_seconds,
            "section_id": request.section_id,
            "stage": request.stage,
        }
        if request.stage == "script":
            result["scene_ids"] = [f"{request.section_id}-scene"]
        return production.SectionProductionResult(
            result,
            self.provider_task_id,
        )

    async def query(self, request, provider_operation_id):
        self.queries.append((request, provider_operation_id))
        result = {"reconciled": True}
        if request.stage == "script":
            result["scene_ids"] = [f"{request.section_id}-scene"]
        return production.SectionProductionResult(result, provider_operation_id)


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
    seams = _FakeSeams(provider_task_id="provider-task-voice")
    runner = production.CustomFilmProductionRunner("tenant-1", seams=seams)
    scene_ids = ("scene-1", "scene-2")
    bilingual = _adapter(
        "voice",
        seconds=19,
        language_mode="bilingual",
        dubbing=True,
    )
    await runner(
        bilingual,
        scene_ids,
        "custom-film-op:" + "3" * 64,
    )
    await runner(
        _adapter("quality", seconds=19),
        scene_ids,
        "custom-film-op:" + "4" * 64,
    )
    voice_request, quality_request = seams.requests
    assert voice_request.scene_ids == scene_ids
    assert voice_request.dialogue_audio == "voice_over"
    assert voice_request.language["mode"] == "bilingual"
    assert voice_request.dubbing["mode"] == "speech_to_speech"
    assert voice_request.exact_seconds == 19
    assert quality_request.scene_ids == scene_ids
    assert quality_request.quality_laws == (
        "source_grounding",
        "visual_cue_fidelity",
    )
    assert quality_request.exact_seconds == 19


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
    with pytest.raises(CustomFilmContractError, match="next runtime chunk"):
        runner.operation_spec(
            _adapter("pictures"),
            ("scene-1",),
            "custom-film-op:" + "9" * 64,
        )
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
        def get_or_create_folder(self, name):
            assert name == "custom-film-video-1"
            return {"id": "folder-1"}

        def upload_audio(self, content, filename, folder_id):
            assert content == b"fake-audio"
            assert filename == "Section 1 Scene 1.mp3"
            assert folder_id == "folder-1"
            return {"id": "drive-audio-1"}

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
async def test_worker_installs_concrete_runner_while_legacy_handlers_stay_unchanged(
    monkeypatch,
):
    captured = {}

    async def consume(tenant_id, video_id, job_id, **kwargs):
        captured.update(
            tenant_id=tenant_id,
            video_id=video_id,
            job_id=job_id,
            **kwargs,
        )
        return {"status": "completed"}

    monkeypatch.setattr(
        "custom_film_section_runtime.consume_runtime_schedule",
        consume,
    )
    result = await worker.arq_run_custom_film_runtime(
        {"job_try": 1},
        "video-1",
        "tenant-1",
        2,
        "custom-film-runtime:" + "c" * 64,
    )
    assert result["status"] == "completed"
    assert isinstance(
        captured["stage_runner"],
        production.CustomFilmProductionRunner,
    )
    assert captured["attempt"] == 2
    assert worker.arq_run_script.__name__ == "arq_run_script"
    assert worker.arq_run_voice.__name__ == "arq_run_voice"


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
