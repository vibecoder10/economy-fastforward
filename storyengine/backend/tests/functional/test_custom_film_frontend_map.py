"""M2-7 frontend contract: Custom Film is a section conductor, not a fifth profile."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
API = ROOT / "frontend" / "src" / "lib" / "api.ts"
MAP = ROOT / "frontend" / "src" / "components" / "chat" / "ChatPipelineMap.tsx"
CHAT = ROOT / "frontend" / "src" / "components" / "chat" / "ChatCore.tsx"


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
    """Was test_legacy_pipeline_copy_and_path_remain_intact for the old
    "Legacy video workflow" / "This older video..." fallback copy. Renamed
    and re-pinned 2026-07-27: that copy called a video created SECONDS ago
    "legacy" and "older" — false, and confusing, whenever a video simply has
    no production_style_snapshot (the normal case for anything created
    outside the four channel cards, e.g. DirectorHome's single-prompt entry
    box). The classification (no snapshot => no locked production profile)
    was correct; only the wording was wrong, so only the wording changed —
    the fallback branch and its structural anchors below are unchanged.

    Re-pinned again 2026-07-27 (fix/director-truth-bugs, commit 1ae14a9f):
    the plan-filtered list moved from `const visible = PIPELINE_STEPS.filter`
    straight to `legacyVisible`, a fallback ONLY used before the production
    guide has loaded — once `guide` is present every step renders (format-
    excluded ones show "skipped", not hidden). This is an intentional
    structural change (the stepper now reads real per-stage state instead of
    guessing from status order), not a regression — re-pin to the new
    anchors instead of the stale ones."""
    source = MAP.read_text()
    assert 'profile?.label || "Standard production"' in source
    assert (
        '"No locked production profile for this video — it runs the default pipeline."'
        in source
    )
    assert "Legacy video workflow" not in source
    assert "older video" not in source
    assert "legacyVisible = PIPELINE_STEPS.filter" in source
    assert "const visible = guide ? PIPELINE_STEPS : legacyVisible" in source
    assert "{isCustomFilm && (" in source


def test_custom_film_approval_uses_a_dedicated_creator_safe_blueprint():
    api_source = API.read_text()
    chat_source = CHAT.read_text()
    for field in (
        "ChatCustomFilmSection",
        "ChatCustomFilmTotals",
        "custom_film_sections",
        "custom_film_totals",
        "approval_notice",
        "finishing_engine",
        "finishing_notice",
    ):
        assert field in api_source
    for truth in (
        'if (card.id === "custom_film_approval")',
        "CustomFilmApprovalCard",
        "Ready for your review",
        "BYOK estimate",
        "Hard ceiling",
        "Unused headroom",
        "not reroll permission",
        "Approve paid production",
        "Keep editing",
        "Remotion finishing locked",
        "Verified fallback",
    ):
        assert truth in chat_source
    assert "custom_film_approval: value" in chat_source
