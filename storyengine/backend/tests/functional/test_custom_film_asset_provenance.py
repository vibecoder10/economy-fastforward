from __future__ import annotations

import copy
import sys
from decimal import Decimal
from pathlib import Path

import pytest

VIDEO_PIPELINE = Path(__file__).parents[4] / "skills" / "video-pipeline"
if str(VIDEO_PIPELINE) not in sys.path:
    sys.path.insert(0, str(VIDEO_PIPELINE))

import custom_film_production_runner as production
from custom_film_contract import CustomFilmContractError
from custom_film_section_runtime import SectionStageAdapter
from scripts.coverage_to_app import _coverage_shape


def _adapter(
    stage: str,
    *,
    seconds: int = 12,
    static: bool = False,
    media_count: int | None = None,
) -> SectionStageAdapter:
    count = media_count if media_count is not None else (3 if static else 1)
    return SectionStageAdapter(
        runtime_hash="a" * 64,
        plan_id="11111111-1111-1111-1111-111111111111",
        video_id="22222222-2222-2222-2222-222222222222",
        section_id="33333333-3333-3333-3333-333333333333",
        order_index=0,
        stage=stage,
        duration_seconds=seconds,
        role="evidence",
        purpose="Show exact evidence",
        render_mode="static_docu" if static else "coverage",
        script_profile="neutral_v1",
        visual_profile="neutral_v1",
        dialogue_audio="voice_over",
        image_density=(
            {"mode": "per_item", "target": 3, "minimum": 2}
            if static
            else {"mode": "visual_cue", "target_per_minute": count}
        ),
        language={"mode": "narrator"},
        dubbing={"enabled": False, "mode": "none"},
        animation={
            "enabled": not static,
            "mode": "ken_burns" if static else "grok_native",
        },
        segmentation={"mode": "item" if static else "visual_cue"},
        camera={
            "mode": (
                "three_complementary_views"
                if static
                else "investigative_coverage"
            )
        },
        quality_laws=("source_grounding",),
        image_source="generate",
        provenance={"visual_profile": ["neutral_v1"]},
        estimated_media={
            "still_images": count,
            "animation_clips": 0 if static else count,
            "voice_tracks": 1,
        },
    )


class _Context:
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
        return _Context(self.conn)


def test_migration_126_and_fresh_schema_bind_backend_owned_asset_provenance():
    root = Path(__file__).parents[3]
    migration = (
        root / "backend/migrations/126_custom_film_asset_provenance.sql"
    ).read_text()
    schema = (root / "schema.sql").read_text()
    for text in (migration, schema):
        assert "CREATE TABLE IF NOT EXISTS custom_film_asset_provenance" in text
        assert "section_contract_hash" in text
        assert "FOREIGN KEY (tenant_id, video_id, asset_id)" in text
        assert "FOREIGN KEY (tenant_id, plan_id, video_id, section_id)" in text
        assert "operation_id, tenant_id, video_id, runtime_hash" in text
        assert "asset provenance identity is immutable" in text
        assert "asset provenance status cannot regress" in text
        assert "'prepared', 'submitted', 'completed', 'failed'" in text
        assert "asset provider model is write-once" in text
        assert "actual_duration_ms BIGINT" in text
        assert "assigned_duration_ms BIGINT" in text
        assert "timing_transform JSONB" in text
        assert "asset actual duration is write-once" in text
        assert "asset assigned duration is write-once" in text
        assert "asset timing transform is write-once" in text
        assert "'prepared', 'submitted', 'failed'" in text
        assert "'prepared', 'submitted', 'completed', 'failed'" not in text[
            text.index("OLD.status = 'prepared'"):
            text.index("OR (OLD.status = 'submitted'")
        ]
        assert "ENABLE ROW LEVEL SECURITY" in text
        assert "REVOKE ALL" in text


def test_approved_density_count_materially_changes_coverage_plan():
    low = {
        "expected_still_images": 2,
        "image_density": {"mode": "visual_cue", "target_per_minute": 2},
    }
    high = {
        "expected_still_images": 20,
        "image_density": {"mode": "visual_cue", "target_per_minute": 20},
    }
    assert _coverage_shape("One cue. Another cue.", section_contract=low) == (
        2,
        0,
        0,
        2,
    )
    assert _coverage_shape("One cue. Another cue.", section_contract=high) == (
        20,
        0,
        0,
        20,
    )


def test_exact_seconds_allocate_without_rounding_drift():
    values = production._allocate_seconds(10, 3)
    assert values == (Decimal("3.334"), Decimal("3.333"), Decimal("3.333"))
    assert sum(values) == Decimal("10")


@pytest.mark.asyncio
async def test_picture_provenance_rejects_placeholder_and_count_overflow():
    seams = production.SharedSectionProductionSeams("tenant-1")
    request = production._request(
        _adapter("pictures", static=True),
        ("scene-1",),
        "custom-film-op:" + "1" * 64,
    )
    valid = {
        "id": "asset-1",
        "status": "done",
        "image_url": "fake://generated",
        "drive_image_url": "fake://generated",
        "generation_method": "static_docu",
        "image_model": "gpt-image-2",
    }
    placeholder = {**valid, "status": "pending", "image_url": None}
    with pytest.raises(CustomFilmContractError, match="approved estimate"):
        await seams._record_media_provenance(request, [valid, valid, valid, valid])
    with pytest.raises(CustomFilmContractError, match="genuinely generated"):
        await seams._record_media_provenance(
            request,
            [valid, {**valid, "id": "asset-2"}, {**placeholder, "id": "asset-3"}],
        )


@pytest.mark.asyncio
async def test_checkpoint_rejects_stale_or_wrong_contract_rows(monkeypatch):
    seams = production.SharedSectionProductionSeams("tenant-1")
    request = production._request(
        _adapter("pictures"),
        ("scene-1",),
        "custom-film-op:" + "2" * 64,
    )

    async def wrong_rows(_request):
        return []

    monkeypatch.setattr(seams, "_provenance_rows", wrong_rows)
    assert await seams._media_artifact_checkpoint(request) is None
    changed = copy.copy(request)
    object.__setattr__(changed, "camera", {"mode": "dialogue_coverage"})
    assert production.SharedSectionProductionSeams._section_contract_hash(
        changed
    ) != production.SharedSectionProductionSeams._section_contract_hash(request)


@pytest.mark.asyncio
async def test_picture_checkpoint_binds_complete_canonical_card(monkeypatch):
    seams = production.SharedSectionProductionSeams("tenant-1")
    request = production._request(
        _adapter("pictures", static=True),
        ("scene-1",),
        "custom-film-op:" + "8" * 64,
    )
    card = {
        "title": "Aircraft",
        "sub": "Verified",
        "specs": ["Range 8,800 mi"],
        "view_role": "engineering_detail",
        "label": "Evidence A",
        "rendered_note": {"line": 2},
    }
    row = {
        "id": "asset-1",
        "status": "done",
        "image_url": "fake://generated",
        "drive_image_url": "fake://generated",
        "generation_method": "static_docu",
        "caption": copy.deepcopy(card),
    }

    async def rows(_request):
        return [copy.deepcopy(row)]

    monkeypatch.setattr(seams, "_provenance_rows", rows)
    checkpoint = await seams._media_artifact_checkpoint(request)
    artifact = checkpoint["artifacts"][0]
    expected = production.canonical_caption_card(card)
    assert artifact["caption_card"] == expected
    assert artifact["caption_hash"] == production.canonical_hash(
        {"caption_card": expected}
    )
    request_hash = production.canonical_hash(request.payload())
    original_hash = seams._artifact_identity_hash(
        request,
        row,
        stage="pictures",
        request_hash=request_hash,
        provider_model="image-test",
    )
    mutated = copy.deepcopy(row)
    mutated["caption"]["label"] = "Changed"
    assert seams._artifact_identity_hash(
        request,
        mutated,
        stage="pictures",
        request_hash=request_hash,
        provider_model="image-test",
    ) != original_hash


@pytest.mark.asyncio
async def test_quality_preflight_requires_same_assets_counts_and_exact_timing(
    monkeypatch,
):
    request = production._request(
        _adapter("quality", seconds=7, media_count=2),
        ("scene-1",),
        "custom-film-op:" + "3" * 64,
    )
    seams = production.SharedSectionProductionSeams("tenant-1")
    stage_rows = {
        "pictures": [
            {
                "asset_id": "a",
                "image_url": "i:a",
                "drive_image_url": "i:a",
                "image_model": "image-test",
                "generation_method": "coverage",
                "status": "done",
            },
            {
                "asset_id": "b",
                "image_url": "i:b",
                "drive_image_url": "i:b",
                "image_model": "image-test",
                "generation_method": "coverage",
                "status": "done",
            },
        ],
        "motion": [
            {
                "asset_id": "a",
                "video_prompt": "move a",
                    "motion_gate_status": None,
                    "generation_method": "coverage",
            },
            {
                "asset_id": "b",
                "video_prompt": "move b",
                    "motion_gate_status": None,
                    "generation_method": "coverage",
            },
        ],
        "clips": [
            {
                "asset_id": "a",
                "video_clip_url": "c:a",
                "model_used": "clip-test",
                "video_duration": Decimal("3.5"),
                "duration_seconds": Decimal("3.5"),
                "assigned_video_duration": Decimal("3.5"),
                "actual_duration_ms": 3500,
                "assigned_duration_ms": 3500,
                "timing_transform": production._timing_transform(3500, 3500),
                "generation_method": "coverage",
            },
            {
                "asset_id": "b",
                "video_clip_url": "c:b",
                "model_used": "clip-test",
                "video_duration": Decimal("3.5"),
                "duration_seconds": Decimal("3.5"),
                "assigned_video_duration": Decimal("3.5"),
                "actual_duration_ms": 3500,
                "assigned_duration_ms": 3500,
                "timing_transform": production._timing_transform(3500, 3500),
                "generation_method": "coverage",
            },
        ],
    }
    provider_models = {
        "pictures": "image-test",
        "motion": "claude-test",
        "clips": "clip-test",
    }
    for stage, rows in stage_rows.items():
        request_hash = production.canonical_hash({"stage": stage, "test": True})
        for row in rows:
            row["provenance_provider_model"] = provider_models[stage]
            row["provenance_request_hash"] = request_hash
            row["provenance_generation_method"] = row["generation_method"]
            row["provenance_artifact_hash"] = seams._artifact_identity_hash(
                request,
                row,
                stage=stage,
                    request_hash=request_hash,
                    provider_model=provider_models[stage],
                    actual_duration_ms=row.get("actual_duration_ms"),
                    assigned_duration_ms=row.get("assigned_duration_ms"),
                    timing_transform=row.get("timing_transform"),
            )

    class Conn:
        async def fetch(self, _sql, *args):
            return copy.deepcopy(stage_rows[args[5]])

    async def get_pool():
        return _Pool(Conn())

    monkeypatch.setattr("database.get_pool", get_pool)
    await seams._quality_media_preflight(request)
    stage_rows["motion"][1]["asset_id"] = "stale-legacy"
    with pytest.raises(CustomFilmContractError, match="tampered motion"):
        await seams._quality_media_preflight(request)
    stage_rows["motion"][1]["asset_id"] = "b"
    stage_rows["clips"][1]["assigned_duration_ms"] = 3400
    stage_rows["clips"][1]["duration_seconds"] = Decimal("3.4")
    stage_rows["clips"][1]["assigned_video_duration"] = Decimal("3.4")
    stage_rows["clips"][1]["timing_transform"] = production._timing_transform(
        3500, 3400
    )
    clip_row = stage_rows["clips"][1]
    clip_row["provenance_artifact_hash"] = seams._artifact_identity_hash(
        request,
        clip_row,
        stage="clips",
        request_hash=clip_row["provenance_request_hash"],
        provider_model=clip_row["provenance_provider_model"],
        actual_duration_ms=clip_row["actual_duration_ms"],
        assigned_duration_ms=clip_row["assigned_duration_ms"],
        timing_transform=clip_row["timing_transform"],
    )
    with pytest.raises(CustomFilmContractError, match="exact section seconds"):
        await seams._quality_media_preflight(request)


def test_completed_provenance_rejects_artifact_and_provider_model_tamper():
    seams = production.SharedSectionProductionSeams("tenant-1")
    request = production._request(
        _adapter("quality", seconds=7),
        ("scene-1",),
        "custom-film-op:" + "4" * 64,
    )
    rows = {
        "pictures": {
            "asset_id": "asset-1",
            "image_url": "fake://image",
            "drive_image_url": "fake://image",
            "image_model": "image-test",
            "generation_method": "coverage",
        },
        "motion": {
            "asset_id": "asset-1",
            "video_prompt": "exact motion",
            "generation_method": "coverage",
        },
        "clips": {
            "asset_id": "asset-1",
            "video_clip_url": "fake://clip",
            "model_used": "clip-test",
            "video_duration": Decimal("7"),
            "duration_seconds": Decimal("7"),
            "assigned_video_duration": Decimal("7"),
            "actual_duration_ms": 7000,
            "assigned_duration_ms": 7000,
            "timing_transform": production._timing_transform(7000, 7000),
            "generation_method": "coverage",
        },
    }
    models = {
        "pictures": "image-test",
        "motion": "claude-test",
        "clips": "clip-test",
    }
    for stage, row in rows.items():
        request_hash = production.canonical_hash({"stage": stage})
        row["provenance_provider_model"] = models[stage]
        row["provenance_request_hash"] = request_hash
        row["provenance_generation_method"] = row["generation_method"]
        row["provenance_artifact_hash"] = seams._artifact_identity_hash(
            request,
            row,
            stage=stage,
            request_hash=request_hash,
            provider_model=models[stage],
            actual_duration_ms=row.get("actual_duration_ms"),
            assigned_duration_ms=row.get("assigned_duration_ms"),
            timing_transform=row.get("timing_transform"),
        )
        assert seams._completed_provenance_is_exact(request, row, stage=stage)

    changed = copy.deepcopy(rows["pictures"])
    changed["image_url"] = "fake://substituted"
    assert not seams._completed_provenance_is_exact(
        request, changed, stage="pictures"
    )
    changed = copy.deepcopy(rows["motion"])
    changed["video_prompt"] = "concurrent rewrite"
    assert not seams._completed_provenance_is_exact(
        request, changed, stage="motion"
    )
    changed = copy.deepcopy(rows["clips"])
    changed["video_clip_url"] = "fake://substituted"
    assert not seams._completed_provenance_is_exact(
        request, changed, stage="clips"
    )
    changed = copy.deepcopy(rows["clips"])
    changed["provenance_provider_model"] = "wrong-model"
    assert not seams._completed_provenance_is_exact(
        request, changed, stage="clips"
    )
    changed = copy.deepcopy(rows["clips"])
    changed["assigned_video_duration"] = Decimal("6.9")
    assert not seams._completed_provenance_is_exact(
        request, changed, stage="clips"
    )
    changed = copy.deepcopy(rows["clips"])
    changed["generation_method"] = "legacy-manual"
    assert not seams._completed_provenance_is_exact(
        request, changed, stage="clips"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stage", "field"),
    (("motion", "video_prompt"), ("clips", "video_clip_url")),
)
async def test_preexisting_unprovenanced_target_fails_before_provider_claim(
    monkeypatch,
    stage,
    field,
):
    seams = production.SharedSectionProductionSeams("tenant-1")
    request = production._request(
        _adapter(stage),
        ("scene-1",),
        "custom-film-op:" + "5" * 64,
        asset_ids=("asset-1",),
    )

    async def forbidden_pool():
        raise AssertionError("pre-existing artifact must fail before DB/provider")

    monkeypatch.setattr("database.get_pool", forbidden_pool)
    row = {
        "id": "asset-1",
        "generation_method": "coverage",
        field: "unexplained-existing-result",
    }
    with pytest.raises(
        CustomFilmContractError,
        match="unexplained pre-existing artifacts",
    ):
        await seams._prepare_media_provenance(
            request,
            [row],
            provider_models={"asset-1": "provider-test"},
        )


@pytest.mark.asyncio
async def test_exact_asset_claim_is_submitted_before_provider_and_race_rejects(
    monkeypatch,
):
    seams = production.SharedSectionProductionSeams("tenant-1")
    request = production._request(
        _adapter("motion"),
        ("scene-1",),
        "custom-film-op:" + "6" * 64,
        asset_ids=("asset-1",),
    )

    class Conn:
        def __init__(self, *, loses_race=False):
            self.loses_race = loses_race
            self.queries = []

        async def execute(self, sql, *_args):
            self.queries.append(sql)
            if "INSERT INTO custom_film_asset_provenance" in sql:
                return "INSERT 0 0" if self.loses_race else "INSERT 0 1"
            return "UPDATE 1"

        def transaction(self):
            return _Context(None)

    conn = Conn()

    async def get_pool():
        return _Pool(conn)

    monkeypatch.setattr("database.get_pool", get_pool)
    await seams._prepare_media_provenance(
        request,
        [
            {
                "id": "asset-1",
                "generation_method": "coverage",
                "video_prompt": None,
            }
        ],
        provider_models={"asset-1": "claude-test"},
    )
    assert "status, assigned_duration_ms" in conn.queries[0]
    assert "'prepared'" in conn.queries[0]
    assert "SET status = 'submitted'" in conn.queries[1]

    losing_conn = Conn(loses_race=True)

    async def losing_pool():
        return _Pool(losing_conn)

    monkeypatch.setattr("database.get_pool", losing_pool)
    with pytest.raises(CustomFilmContractError, match="already claimed or changed"):
        await seams._prepare_media_provenance(
            request,
            [
                {
                    "id": "asset-1",
                    "generation_method": "coverage",
                    "video_prompt": None,
                }
            ],
            provider_models={"asset-1": "claude-test"},
        )


def test_provider_result_validators_reject_partial_wrong_or_failed_outputs():
    asset_ids = ("a", "b")
    motion = {
        "written": 2,
        "asset_ids": ["a", "b"],
        "artifacts": [
            {"asset_id": "a", "video_prompt": "move a"},
            {"asset_id": "b", "video_prompt": "move b"},
        ],
    }
    assert set(production._exact_motion_result(motion, asset_ids)) == set(asset_ids)
    for changed in (
        {**motion, "written": 1},
        {**motion, "asset_ids": ["a", "wrong"]},
        {**motion, "artifacts": motion["artifacts"][:1]},
    ):
        with pytest.raises(CustomFilmContractError):
            production._exact_motion_result(changed, asset_ids)

    clips = {
        "status": "completed",
        "requested_asset_ids": ["a", "b"],
        "generated_asset_ids": ["a", "b"],
        "generated_artifacts": [
            {
                "asset_id": "a",
                "video_clip_url": "clip:a",
                "provider_model": "grok",
                "duration_seconds": "3.5",
            },
            {
                "asset_id": "b",
                "video_clip_url": "clip:b",
                "provider_model": "grok",
                "duration_seconds": "3.5",
            },
        ],
        "clips_generated": 2,
        "clips_failed": 0,
        "clips_blocked": 0,
        "clips_in_progress_elsewhere": 0,
    }
    assert set(production._exact_clip_result(clips, asset_ids)) == set(
        asset_ids
    )
    for changed in (
        {**clips, "clips_generated": 1},
        {**clips, "generated_asset_ids": ["a", "wrong"]},
        {**clips, "generated_asset_ids": ["a", "a"]},
        {**clips, "generated_asset_ids": ["a", "b", "extra"]},
        {**clips, "clips_failed": 1},
        {**clips, "clips_blocked": 1},
        {**clips, "clips_in_progress_elsewhere": 1},
        {**clips, "generated_artifacts": clips["generated_artifacts"][:1]},
        {
            **clips,
            "generated_artifacts": [
                clips["generated_artifacts"][0],
                clips["generated_artifacts"][0],
            ],
        },
    ):
        with pytest.raises(CustomFilmContractError):
            production._exact_clip_result(changed, asset_ids)
    for wrong_duration in (None, "wrong", "0"):
        changed = copy.deepcopy(clips)
        changed["generated_artifacts"][1]["duration_seconds"] = wrong_duration
        with pytest.raises(CustomFilmContractError, match="duration"):
            production._exact_clip_result(changed, asset_ids)


def test_concurrent_artifact_write_cannot_be_adopted():
    asset_ids = ("a",)
    with pytest.raises(CustomFilmContractError, match="changed concurrently"):
        production._assert_current_provider_artifacts(
            "motion",
            [{"id": "a", "video_prompt": "concurrent rewrite"}],
            asset_ids,
            {"a": "provider-returned prompt"},
        )
    with pytest.raises(CustomFilmContractError, match="changed concurrently"):
        production._assert_current_provider_artifacts(
            "clips",
            [
                {
                    "id": "a",
                    "video_clip_url": "clip:concurrent",
                    "model_used": "wrong-model",
                    "video_duration": "6",
                }
            ],
            asset_ids,
            {
                "a": {
                    "video_clip_url": "clip:provider",
                    "provider_model": "grok",
                    "duration_seconds": "6",
                }
            },
        )


@pytest.mark.asyncio
async def test_actual_six_target_thirty_seven_is_honest_needs_compositor(
    monkeypatch,
):
    request = production._request(
        _adapter("quality", seconds=37),
        ("scene-1",),
        "custom-film-op:" + "7" * 64,
    )
    seams = production.SharedSectionProductionSeams("tenant-1")
    transform = production._timing_transform(6000, 37000)
    assert transform == {
        "mode": "repeat_then_trim",
        "source_duration_ms": 6000,
        "repeat_count": 7,
        "final_repeat_duration_ms": 1000,
        "output_duration_ms": 37000,
    }
    stage_rows = {
        "pictures": [
            {
                "asset_id": "asset-1",
                "image_url": "image:1",
                "drive_image_url": "image:1",
                "image_model": "image-test",
                "generation_method": "coverage",
                "status": "done",
            }
        ],
        "motion": [
            {
                "asset_id": "asset-1",
                "video_prompt": "move",
                "motion_gate_status": None,
                "generation_method": "coverage",
            }
        ],
        "clips": [
            {
                "asset_id": "asset-1",
                "video_clip_url": "clip:1",
                "model_used": "clip-test",
                "video_duration": Decimal("6"),
                "duration_seconds": Decimal("37"),
                "assigned_video_duration": Decimal("37"),
                "actual_duration_ms": 6000,
                "assigned_duration_ms": 37000,
                "timing_transform": transform,
                "generation_method": "coverage",
            }
        ],
    }
    models = {
        "pictures": "image-test",
        "motion": "claude-test",
        "clips": "clip-test",
    }
    for stage, rows in stage_rows.items():
        request_hash = production.canonical_hash({"stage": stage, "37v6": True})
        for row in rows:
            row["provenance_provider_model"] = models[stage]
            row["provenance_request_hash"] = request_hash
            row["provenance_generation_method"] = row["generation_method"]
            row["provenance_artifact_hash"] = seams._artifact_identity_hash(
                request,
                row,
                stage=stage,
                request_hash=request_hash,
                provider_model=models[stage],
                actual_duration_ms=row.get("actual_duration_ms"),
                assigned_duration_ms=row.get("assigned_duration_ms"),
                timing_transform=row.get("timing_transform"),
            )

    class Conn:
        async def fetch(self, _sql, *args):
            return copy.deepcopy(stage_rows[args[5]])

    async def get_pool():
        return _Pool(Conn())

    monkeypatch.setattr("database.get_pool", get_pool)
    evidence = await seams._quality_media_preflight(request)
    assert evidence["timing_status"] == "needs_compositor"
    assert evidence["timing_transforms"][0]["actual_duration_ms"] == 6000
    assert evidence["timing_transforms"][0]["assigned_duration_ms"] == 37000

    stage_rows["clips"][0]["timing_transform"]["repeat_count"] = 6
    with pytest.raises(CustomFilmContractError, match="tampered clips"):
        await seams._quality_media_preflight(request)


@pytest.mark.asyncio
async def test_completion_persists_actual_target_and_transform_separately(
    monkeypatch,
):
    seams = production.SharedSectionProductionSeams("tenant-1")
    request = production._request(
        _adapter("clips", seconds=37),
        ("scene-1",),
        "custom-film-op:" + "8" * 64,
        asset_ids=("asset-1",),
    )

    class Conn:
        def __init__(self):
            self.args = None
            self.sql = ""

        async def execute(self, sql, *args):
            self.sql = sql
            self.args = args
            return "UPDATE 1"

        def transaction(self):
            return _Context(None)

    conn = Conn()

    async def get_pool():
        return _Pool(conn)

    monkeypatch.setattr("database.get_pool", get_pool)
    await seams._complete_media_provenance(
        request,
        [
            {
                "id": "asset-1",
                "video_clip_url": "clip:1",
                "model_used": "grok",
                "video_duration": Decimal("6"),
                "duration_seconds": Decimal("37"),
                "assigned_video_duration": Decimal("37"),
                "generation_method": "coverage",
            }
        ],
        provider_models={"asset-1": "grok"},
        durations={"asset-1": Decimal("37")},
        actual_durations={"asset-1": Decimal("6")},
    )
    assert "actual_duration_ms = $10" in conn.sql
    assert conn.args[9] == 6000
    assert conn.args[10] == 37000
    assert '"mode": "repeat_then_trim"' in conn.args[11]
    assert '"repeat_count": 7' in conn.args[11]
