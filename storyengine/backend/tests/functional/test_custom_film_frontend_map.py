"""M2-7 frontend contract: Custom Film is a section conductor, not a fifth profile."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
API = ROOT / "frontend" / "src" / "lib" / "api.ts"
MAP = ROOT / "frontend" / "src" / "components" / "chat" / "ChatPipelineMap.tsx"


def test_video_detail_types_the_optional_custom_film_plan():
    source = API.read_text()
    assert "export interface CustomFilmPlanSection" in source
    assert "export interface CustomFilmPlan" in source
    assert "custom_film_plan?: CustomFilmPlan | null" in source
    for field in ("order_index", "role", "purpose", "duration_units"):
        assert field in source


def test_pipeline_map_shows_only_creator_safe_ordered_mix():
    source = MAP.read_text()
    for truth in (
        "Custom Film",
        "Ordered section mix",
        "customFilmSectionViews",
        "customFilmStatusLabel",
        "section.role",
        "section.share",
        "section.purpose",
        "section.feel",
    ):
        assert truth in source
    for hidden_internal in (
        "bilingual_character_animation",
        "simple_language_animation",
        "photo_documentary",
        "animated_investigative_documentary",
        "provider_id",
        "model_id",
        "compatibility_version}",
        "plan_hash}",
    ):
        assert hidden_internal not in source
    assert "fifth" not in source.lower()
    assert "SelectorCards" not in source


def test_legacy_pipeline_copy_and_path_remain_intact():
    source = MAP.read_text()
    assert 'profile?.label || "Legacy video workflow"' in source
    assert (
        '"This older video keeps its original inferred production settings."'
        in source
    )
    assert "const visible = PIPELINE_STEPS.filter" in source
    assert "{isCustomFilm && (" in source
