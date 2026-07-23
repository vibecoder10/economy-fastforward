"""Runtime contract tests for the four public production styles."""

import asyncio
import json
import os
from pathlib import Path

import pytest
from fastapi import BackgroundTasks

import production_styles
import routes.billing as billing_route
import routes.characters as characters_route
import routes.projects as projects_route
import routes.script_templates as script_templates_route
import routes.videos as videos_route
import static_docu
import vault
from models import CreateVideoRequest
from scripts.coverage_to_app import (
    _coverage_shape,
    _require_tenant_kie_key,
    _visual_cue_count,
)


def _profile(style_id: str, **knob_overrides):
    rows = {
        "bilingual_character_animation": {
            "label": "Bilingual Character Animation",
            "knobs": {
                "render_mode": "coverage",
                "script_profile": "neutral_v1",
                "visual_profile": "neutral_v1",
                "image_density": {"mode": "dialogue_shape"},
                "animation": {"enabled": True, "mode": "grok_native"},
                "language": {"mode": "bilingual"},
                "dubbing": {"enabled": True, "mode": "speech_to_speech"},
                "segmentation": {"mode": "speaker_turn"},
                "camera": {"mode": "dialogue_coverage"},
                "quality_laws": ["character_continuity"],
                "image_source": "generate",
            },
        },
        "simple_language_animation": {
            "label": "Simple-Language Animation",
            "knobs": {
                "render_mode": "coverage",
                "script_profile": "neutral_v1",
                "visual_profile": "neutral_v1",
                "image_density": {"mode": "dialogue_shape"},
                "animation": {"enabled": True, "mode": "grok_native"},
                "language": {"mode": "simple_single_language"},
                "dubbing": {"enabled": False, "mode": "none"},
                "segmentation": {"mode": "speaker_turn"},
                "camera": {"mode": "dialogue_coverage"},
                "quality_laws": ["clear_language"],
                "image_source": "generate",
            },
        },
        "photo_documentary": {
            "label": "Photo Documentary",
            "knobs": {
                "render_mode": "static_docu",
                "script_profile": "neutral_v1",
                "visual_profile": "neutral_v1",
                "image_density": {"mode": "per_item"},
                "animation": {"enabled": False, "mode": "ken_burns"},
                "language": {"mode": "narrator"},
                "dubbing": {"enabled": False, "mode": "none"},
                "segmentation": {"mode": "item"},
                "camera": {"mode": "three_complementary_views"},
                "quality_laws": ["verified_reference"],
                "image_source": "generate",
            },
        },
        "animated_investigative_documentary": {
            "label": "Animated Investigative Documentary",
            "knobs": {
                "render_mode": "coverage",
                "script_profile": "power_doctrine_v2",
                "visual_profile": "cinematic_illustration",
                "image_density": {"mode": "visual_cue"},
                "animation": {"enabled": True, "mode": "grok_native"},
                "language": {"mode": "narrator"},
                "dubbing": {"enabled": False, "mode": "none"},
                "segmentation": {"mode": "visual_cue"},
                "camera": {"mode": "investigative_coverage"},
                "quality_laws": ["source_grounding"],
                "image_source": "generate",
            },
        },
    }
    row = rows[style_id]
    knobs = {**row["knobs"], **knob_overrides}
    return {
        "id": style_id,
        "version": 1,
        "label": row["label"],
        "description": f"{row['label']} description",
        "knobs": knobs,
        "estimate": {},
        "requires_byok": True,
        "sort": 1,
    }


def test_dimension_values_select_the_existing_runtime_paths():
    assert production_styles.runtime_values(
        _profile("bilingual_character_animation")
    ) == {
        "render_mode": "coverage",
        "script_profile": "neutral_v1",
        "visual_profile": "neutral_v1",
        "dialogue_audio": "voice_over",
    }
    assert production_styles.runtime_values(
        _profile("simple_language_animation")
    ) == {
        "render_mode": "coverage",
        "script_profile": "neutral_v1",
        "visual_profile": "neutral_v1",
        "dialogue_audio": "grok_native",
    }
    assert production_styles.runtime_values(_profile("photo_documentary")) == {
        "render_mode": "static_docu",
        "script_profile": "neutral_v1",
        "visual_profile": "neutral_v1",
        "dialogue_audio": "voice_over",
    }
    assert production_styles.runtime_values(
        _profile("animated_investigative_documentary")
    ) == {
        "render_mode": "coverage",
        "script_profile": "power_doctrine_v2",
        "visual_profile": "cinematic_illustration",
        "dialogue_audio": "voice_over",
    }


def test_create_video_persists_each_profile_on_its_existing_runtime_seams(monkeypatch):
    inserts = []

    async def noop(*_args, **_kwargs):
        return None

    async def fake_project(_tenant_id):
        return {"id": "project-a"}

    async def fake_get_profile(style_id):
        return _profile(style_id)

    async def fake_fetch_one(query, *args):
        if "FROM style_presets" in query:
            return {"id": args[0]}
        if "INSERT INTO videos" not in query:
            raise AssertionError(query)
        inserts.append((query, args))
        return {
            "id": f"video-{len(inserts)}",
            "video_title": args[2],
            "status": args[3],
            "thumbnail_url": None,
            "accent_color": "#00D4AA",
            "total_cost": 0,
            "views": 0,
            "ctr": None,
            "created_at": "now",
            "updated_at": "now",
        }

    monkeypatch.setattr(billing_route, "check_plan_limits", noop)
    monkeypatch.setattr(billing_route, "enforce_video_length_cap", noop)
    monkeypatch.setattr(billing_route, "increment_usage", noop)
    monkeypatch.setattr(projects_route, "_get_or_create_project", fake_project)
    monkeypatch.setattr(production_styles, "get_public_profile", fake_get_profile)
    monkeypatch.setattr(videos_route, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(script_templates_route, "apply_default_template", noop)
    monkeypatch.setattr("channel_format.apply_format_defaults", noop)
    monkeypatch.setattr(characters_route, "apply_locked_cast", noop)

    expected = {
        "bilingual_character_animation": (
            "coverage", "neutral_v1", "neutral_v1", "voice_over"
        ),
        "simple_language_animation": (
            "coverage", "neutral_v1", "neutral_v1", "grok_native"
        ),
        "photo_documentary": (
            "static_docu", "neutral_v1", "neutral_v1", "voice_over"
        ),
        "animated_investigative_documentary": (
            "coverage",
            "power_doctrine_v2",
            "cinematic_illustration",
            "voice_over",
        ),
    }
    for style_id in expected:
        asyncio.run(
            videos_route.create_video(
                CreateVideoRequest(
                    title=f"{style_id} video",
                    production_style_id=style_id,
                ),
                BackgroundTasks(),
                "tenant-a",
            )
        )

    assert len(inserts) == 4
    for (query, args), (style_id, runtime) in zip(inserts, expected.items()):
        render_mode, script_profile, visual_profile, dialogue_audio = runtime
        assert "production_style_snapshot" in query
        assert args[17] == render_mode
        assert args[19] == visual_profile
        assert args[20] == script_profile
        assert args[21:23] == (style_id, 1)
        assert json.loads(args[23])["id"] == style_id
        assert args[24] == dialogue_audio
        assert "PRODUCTION STYLE:" in args[7]
        if style_id == "photo_documentary":
            stage_plan = json.loads(args[15])
            assert "voice" in stage_plan
            assert "video" not in stage_plan
            assert "sound" not in stage_plan


def test_profile_guidance_reaches_language_and_segmentation_seams():
    bilingual = production_styles.merge_script_guidance(
        "Keep the opening short.",
        _profile("bilingual_character_animation"),
    )
    simple = production_styles.merge_script_guidance(
        None,
        _profile("simple_language_animation"),
    )
    photo = production_styles.merge_script_guidance(
        None,
        _profile("photo_documentary"),
    )
    investigative = production_styles.merge_script_guidance(
        None,
        _profile("animated_investigative_documentary"),
    )
    assert "two languages" in bilingual and "Keep the opening short." in bilingual
    assert "one clear target language" in simple
    assert "item by item" in photo
    assert "one dominant visual idea" in investigative
    assert all(
        brand not in "\n".join((bilingual, simple, photo, investigative)).lower()
        for brand in ("poco", "easy english", "dvsu", "power doctrine")
    )


def test_investigative_density_targets_one_frame_per_meaningful_sentence():
    sentences = [
        f"Evidence point {index} reveals a concrete mechanism with a visible consequence for investigators today."
        for index in range(50)
    ]
    text = " ".join(sentences)
    snapshot = _profile("animated_investigative_documentary")
    assert 675 <= len(text.split()) <= 725
    assert _coverage_shape(text, "voice_over", snapshot) == (50, 0, 0, 50)


def test_visual_cue_counter_folds_trivial_fragments_into_neighbors():
    text = (
        "Then. A procurement memo moves the deadline into the next fiscal year. "
        "Why? The revised diagram exposes a second production bottleneck. "
        "At last. Factory footage shows the missing tooling arrive on site."
    )
    assert _visual_cue_count(text) == 3


def test_legacy_narration_shape_is_unchanged_without_a_profile_snapshot():
    assert _coverage_shape("Just narration, no speakers at all.") == (3, 2, 3, None)
    assert _coverage_shape(
        "Just narration, no speakers at all.",
        "voice_over",
        json.dumps({"knobs": {"image_density": {"mode": "visual_cue"}}}),
    ) == (1, 0, 0, 1)


def test_channel_profile_link_and_legacy_identity_both_enable_photo_mode(monkeypatch):
    async def linked(*_args):
        return {"production_style_id": "photo_documentary", "channel_identity": {}}

    monkeypatch.setattr(static_docu, "fetch_one", linked)
    assert asyncio.run(static_docu.static_mode_for_tenant("tenant-a")) is True

    async def legacy(*_args):
        return {
            "production_style_id": None,
            "channel_identity": {
                "visual_format": {"motion": "static photos with Ken Burns"}
            },
        }

    monkeypatch.setattr(static_docu, "fetch_one", legacy)
    assert asyncio.run(static_docu.static_mode_for_tenant("tenant-a")) is True

    async def explicit_animated(*_args):
        return {
            "production_style_id": "simple_language_animation",
            "channel_identity": {
                "visual_format": {"motion": "static photos with Ken Burns"}
            },
        }

    monkeypatch.setattr(static_docu, "fetch_one", explicit_animated)
    assert asyncio.run(static_docu.static_mode_for_tenant("tenant-a")) is False


def test_required_tenant_secret_ignores_a_service_environment_key(monkeypatch):
    async def missing(*_args, **_kwargs):
        return None

    monkeypatch.setattr(vault, "get_secret", missing)
    monkeypatch.setenv("KIE_AI_API_KEY", "operator-funded-key")
    with pytest.raises(RuntimeError, match="does not use a shared provider key"):
        asyncio.run(
            vault.get_required_tenant_secret(
                "kie_ai_api_key",
                "tenant-a",
                provider_label="Kie.ai",
            )
        )


def test_coverage_image_key_gate_is_byok_even_with_env_key(monkeypatch):
    async def missing(*_args, **_kwargs):
        return None

    import scripts.coverage_to_app as coverage

    monkeypatch.setattr(coverage, "get_secret", missing)
    monkeypatch.setenv("KIE_AI_API_KEY", "operator-funded-key")
    with pytest.raises(RuntimeError, match="does not use a shared provider key"):
        asyncio.run(_require_tenant_kie_key("tenant-a"))


def test_create_and_generation_sources_consume_the_snapshot_not_profile_names():
    backend = Path(__file__).resolve().parents[2]
    videos_source = (backend / "routes" / "videos.py").read_text()
    coverage_source = (backend / "scripts" / "coverage_to_app.py").read_text()
    pipeline_source = (backend / "pipeline_executor.py").read_text()
    assert "runtime_values(production_style_snapshot)" in videos_source
    assert "merge_script_guidance" in videos_source
    assert "production_style_snapshot" in coverage_source
    # The old Power Doctrine implementation's functional contract survives on
    # the merged live coverage path: each visual cue becomes a stored still
    # prompt, then the still plus its cue feeds a stored motion prompt, and clip
    # generation consumes that prompt. Do not resurrect the retired storyboard
    # engine just to recreate this chain.
    assert "sentence_text, image_prompt" in coverage_source
    assert "SELECT id, shot_type, image_prompt, sentence_text" in coverage_source
    assert "UPDATE assets SET video_prompt=$1" in coverage_source
    assert 'vp = (r.get("video_prompt") or "").strip()' in pipeline_source
    assert "or os.getenv(\"KIE_AI_API_KEY\")" not in coverage_source


def test_all_first_party_creation_surfaces_require_the_public_style_pick():
    backend = Path(__file__).resolve().parents[2]
    frontend = backend.parent / "frontend" / "src"
    selector = (
        frontend
        / "components"
        / "production"
        / "ProductionStyleSelector.tsx"
    ).read_text()
    onboarding = (
        frontend / "components" / "onboarding" / "CreateVideoStep.tsx"
    ).read_text()
    first_video = (
        frontend / "components" / "pipeline" / "FirstVideoFlow.tsx"
    ).read_text()
    pipeline = (frontend / "app" / "pipeline" / "page.tsx").read_text()

    assert "getProductionStyles" in selector
    assert "Nothing is preselected" in selector
    assert "images_per_minute * durationMinutes" in selector
    assert "Bring your own provider keys" in selector
    assert "Design Your Own" not in selector and "Custom Film" not in selector

    assert "<ProductionStyleSelector" in onboarding
    assert "production_style_id: productionStyleId" in onboarding
    assert "if (!selectedTitle.trim() || !productionStyleId) return" in onboarding
    assert "disabled={creating || !productionStyleId}" in onboarding

    assert "<ProductionStyleSelector" in first_video
    assert "productionStyleId: ProductionStyleId" in first_video
    assert "disabled={creating || !productionStyleId}" in first_video

    assert "<ProductionStyleSelector" in pipeline
    assert "production_style_id: newProductionStyleId" in pipeline
    assert "!newProductionStyleId || createMutation.isPending" in pipeline
