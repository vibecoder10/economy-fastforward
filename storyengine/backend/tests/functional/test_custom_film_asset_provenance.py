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
            {"asset_id": "a", "image_url": "i:a", "status": "done"},
            {"asset_id": "b", "image_url": "i:b", "status": "done"},
        ],
        "motion": [
            {
                "asset_id": "a",
                "video_prompt": "move a",
                "motion_gate_status": None,
            },
            {
                "asset_id": "b",
                "video_prompt": "move b",
                "motion_gate_status": None,
            },
        ],
        "clips": [
            {
                "asset_id": "a",
                "video_clip_url": "c:a",
                "exact_duration_seconds": Decimal("3.5"),
            },
            {
                "asset_id": "b",
                "video_clip_url": "c:b",
                "exact_duration_seconds": Decimal("3.5"),
            },
        ],
    }

    class Conn:
        async def fetch(self, _sql, *args):
            return copy.deepcopy(stage_rows[args[5]])

    async def get_pool():
        return _Pool(Conn())

    monkeypatch.setattr("database.get_pool", get_pool)
    await seams._quality_media_preflight(request)
    stage_rows["motion"][1]["asset_id"] = "stale-legacy"
    with pytest.raises(CustomFilmContractError, match="same approved asset"):
        await seams._quality_media_preflight(request)
    stage_rows["motion"][1]["asset_id"] = "b"
    stage_rows["clips"][1]["exact_duration_seconds"] = Decimal("3.4")
    with pytest.raises(CustomFilmContractError, match="exact section seconds"):
        await seams._quality_media_preflight(request)
