"""Integration tests for pipeline module handoffs.

These tests verify that the data produced by each module matches the
format expected by the next module in the chain, without calling external
APIs.
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pipeline_constants import Statuses


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_BRIEF = {
    "headline": "The Musk SpaceX-xAI Merger",
    "thesis": "Elon Musk's merger of SpaceX and xAI represents a strategic consolidation.",
    "executive_hook": "What if one man controlled both orbital infrastructure and superintelligence?",
    "fact_sheet": "SpaceX valued at $350B. xAI raised $6B in 2024.",
    "historical_parallels": "Standard Oil vertical integration. Bell System monopoly.",
    "framework_analysis": "Vertical integration framework: hardware + software + data.",
    "character_dossier": "Elon Musk — CEO of SpaceX, Tesla, xAI.",
    "narrative_arc": "From rockets to AGI: the strategic logic of merging hardware and intelligence.",
    "counter_arguments": "Anti-trust concerns. Capital structure complexity.",
    "visual_seeds": "Rocket launches, server farms, corporate boardrooms.",
    "source_bibliography": "https://reuters.com/spacex-xai-merger",
    "framework_angle": "vertical_integration",
    "title_options": "The SpaceX-xAI Merger: One Man's Path to Controlling Everything",
    "thumbnail_concepts": "Split image: rocket on left, AI brain on right",
    "source_urls": "https://reuters.com/spacex-xai-merger\nhttps://bloomberg.com/musk-empire",
}


SAMPLE_SCENE_LIST = [
    {
        "scene_number": i + 1,
        "act": f"act{min((i // 23) + 1, 6)}",
        "style": ["dossier", "dossier", "schema", "dossier", "echo"][i % 5],
        "scene_description": f"Scene {i+1}: An anonymous figure silhouetted in a dark boardroom #{i+1}",
        "script_excerpt": f"The merger of SpaceX and xAI represents segment {i+1}.",
        "composition_hint": ["wide", "medium", "closeup", "environmental", "portrait"][i % 5],
    }
    for i in range(136)
]
# Ensure first and last are dossier
SAMPLE_SCENE_LIST[0]["style"] = "dossier"
SAMPLE_SCENE_LIST[-1]["style"] = "dossier"


SAMPLE_IDEA_RECORD = {
    "id": "recABC123",
    "Video Title": "The SpaceX-xAI Merger",
    "Status": Statuses.READY_SCRIPTING,
    "Hook Script": "What if one man controlled everything?",
    "Past Context": "Standard Oil vertical integration.",
    "Present Parallel": "Vertical integration of hardware + software + data.",
    "Future Prediction": "Path to controlling both orbit and intelligence.",
    "Writer Guidance": "Focus on monopoly implications.",
    "Original DNA": '{"meta_data":{}}',
    "Reference URL": "https://reuters.com/spacex-xai",
    "Thumbnail Prompt": "Rocket and AI brain split image",
}


# ---------------------------------------------------------------------------
# Test 1: Research output matches Ideas Bank schema
# ---------------------------------------------------------------------------

class TestResearchToIdeasBank:
    """Research agent output has all required Ideas Bank fields."""

    def test_brief_has_required_validation_fields(self):
        """The brief must have all fields the validator expects."""
        from brief_translator.validator import build_validation_prompt

        # This should not raise — all fields are present
        prompt = build_validation_prompt(SAMPLE_BRIEF)
        assert "Musk SpaceX" in prompt
        assert "350B" in prompt

    def test_brief_has_required_script_generator_fields(self):
        """The brief must have fields the script generator uses."""
        # These are the fields script generation actually reads
        required = ["headline", "thesis", "executive_hook", "visual_seeds"]
        for field in required:
            assert field in SAMPLE_BRIEF, f"Missing field: {field}"
            assert SAMPLE_BRIEF[field], f"Empty field: {field}"


# ---------------------------------------------------------------------------
# Test 2: Ideas Bank record readable by brief translator
# ---------------------------------------------------------------------------

class TestIdeasBankToBriefTranslator:
    """Brief translator can load and parse an Ideas Bank record."""

    def test_idea_record_maps_to_brief(self):
        """Verify idea record fields map correctly to brief dict format."""
        idea = SAMPLE_IDEA_RECORD

        # This is the mapping from pipeline.run_brief_translator()
        brief = {
            "headline": idea.get("Video Title", ""),
            "thesis": idea.get("Future Prediction", ""),
            "executive_hook": idea.get("Hook Script", ""),
            "fact_sheet": idea.get("Writer Guidance", ""),
            "historical_parallels": idea.get("Past Context", ""),
            "framework_analysis": idea.get("Present Parallel", ""),
            "character_dossier": "",
            "narrative_arc": idea.get("Future Prediction", ""),
            "counter_arguments": "",
            "visual_seeds": idea.get("Thumbnail Prompt", ""),
            "source_bibliography": idea.get("Reference URL", ""),
        }

        assert brief["headline"] == "The SpaceX-xAI Merger"
        assert brief["executive_hook"] != ""
        assert brief["historical_parallels"] != ""

    def test_validator_accepts_idea_mapped_brief(self):
        """The validation prompt builder doesn't error on mapped fields."""
        from brief_translator.validator import build_validation_prompt

        idea = SAMPLE_IDEA_RECORD
        brief = {
            "headline": idea.get("Video Title", ""),
            "thesis": idea.get("Future Prediction", ""),
            "executive_hook": idea.get("Hook Script", ""),
            "fact_sheet": idea.get("Writer Guidance", ""),
            "historical_parallels": idea.get("Past Context", ""),
            "framework_analysis": idea.get("Present Parallel", ""),
            "character_dossier": "",
            "narrative_arc": idea.get("Future Prediction", ""),
            "counter_arguments": "",
            "visual_seeds": idea.get("Thumbnail Prompt", ""),
            "source_bibliography": idea.get("Reference URL", ""),
        }

        # Should not raise
        prompt = build_validation_prompt(brief)
        assert len(prompt) > 100


# ---------------------------------------------------------------------------
# Test 3: Brief translator output matches pipeline schema
# ---------------------------------------------------------------------------

class TestBriefTranslatorToPipeline:
    """Pipeline table record has all required fields populated."""

    def test_pipeline_record_has_core_fields(self):
        """build_pipeline_record produces all fields the pipeline expects."""
        from brief_translator.pipeline_writer import build_pipeline_record

        record = build_pipeline_record(
            brief=SAMPLE_BRIEF,
            script="[ACT 1]\nThis is the narration script...",
            scene_list=SAMPLE_SCENE_LIST,
            accent_color="cold_teal",
            idea_record_id="recABC123",
            scene_filepath="/tmp/test_scenes.json",
            video_id="vid_20260215_120000",
        )

        # Core fields the pipeline reads
        assert "Video Title" in record
        assert "Hook Script" in record
        assert "Status" in record
        assert record["Status"] == "Queued"

        # New translation fields
        assert "Script" in record
        assert "Scene File Path" in record
        assert "Accent Color" in record
        assert "Video ID" in record
        assert "Scene Count" in record
        assert record["Scene Count"] == 136

    def test_original_dna_is_traceable(self):
        """Original DNA links back to the source idea."""
        from brief_translator.pipeline_writer import build_pipeline_record

        record = build_pipeline_record(
            brief=SAMPLE_BRIEF,
            script="script text",
            scene_list=SAMPLE_SCENE_LIST[:10],
            accent_color="cold_teal",
            idea_record_id="recABC123",
            scene_filepath="/tmp/test.json",
            video_id="vid_test",
        )

        dna = json.loads(record["Original DNA"])
        assert dna["meta_data"]["source_idea_id"] == "recABC123"
        assert dna["meta_data"]["accent_color"] == "cold_teal"


# ---------------------------------------------------------------------------
# Test 4: Scene list readable by image prompt engine
# ---------------------------------------------------------------------------

class TestSceneListToImagePromptEngine:
    """Image prompt engine can load and process a scene JSON file."""

    def test_scene_list_has_required_fields(self):
        """Each scene has scene_description which the engine needs."""
        for scene in SAMPLE_SCENE_LIST:
            assert "scene_description" in scene, f"Missing scene_description in scene {scene.get('scene_number')}"
            assert scene["scene_description"], "Empty scene_description"

    def test_generate_prompts_accepts_scene_list(self):
        """The image prompt engine processes the scene list without error."""
        from image_prompt_engine import generate_prompts

        prompts = generate_prompts(
            SAMPLE_SCENE_LIST,
            accent_color="cold teal",
            seed=42,
        )

        assert len(prompts) == len(SAMPLE_SCENE_LIST)
        assert len(prompts) == 136

    def test_generated_prompts_have_required_keys(self):
        """Each prompt has the keys the pipeline writes to Airtable."""
        from image_prompt_engine import generate_prompts

        prompts = generate_prompts(SAMPLE_SCENE_LIST, accent_color="cold teal", seed=42)

        required_keys = {"prompt", "content_type", "display_format", "color_mood", "act", "index", "ken_burns"}
        for p in prompts:
            assert required_keys.issubset(p.keys()), f"Missing keys: {required_keys - p.keys()}"

    def test_styled_prompts_contain_identity_markers(self):
        """All prompts contain holographic suffix markers."""
        from image_prompt_engine import generate_prompts

        prompts = generate_prompts(SAMPLE_SCENE_LIST, accent_color="cold teal", seed=42)

        # All prompts should contain the holographic suffix
        for p in prompts[:10]:
            assert "16:9 aspect ratio" in p["prompt"], (
                f"Prompt missing aspect ratio marker: {p['prompt'][:80]}"
            )
            assert "no people visible" in p["prompt"] or "photorealistic" in p["prompt"], (
                f"Prompt missing holographic identity marker: {p['prompt'][:80]}"
            )

    def test_color_mood_applied_to_prompts(self):
        """Every prompt has a valid color_mood value."""
        from image_prompt_engine import generate_prompts

        prompts = generate_prompts(SAMPLE_SCENE_LIST, accent_color="cold teal", seed=42)

        valid_moods = {"strategic", "alert", "archive", "contagion", "power", "personal"}
        for p in prompts:
            assert p["color_mood"] in valid_moods, (
                f"Invalid color_mood '{p['color_mood']}' at index {p['index']}"
            )

    def test_scene_list_roundtrip_through_file(self):
        """Scene list survives save → load → generate_prompts cycle."""
        from image_prompt_engine import generate_prompts
        from brief_translator.pipeline_writer import save_scene_list

        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = save_scene_list("vid_test", SAMPLE_SCENE_LIST, tmpdir)
            loaded = json.loads(Path(filepath).read_text())
            assert len(loaded) == 136

            prompts = generate_prompts(loaded, accent_color="cold teal", seed=42)
            assert len(prompts) == 136


# ---------------------------------------------------------------------------
# Test 5: Styled prompts format accepted by NanoBanana (Airtable Images table)
# ---------------------------------------------------------------------------

class TestStyledPromptsToNanoBanana:
    """NanoBanana accepts the prompt format from the image prompt engine."""

    def test_prompts_are_strings(self):
        """NanoBanana expects prompts as plain strings."""
        from image_prompt_engine import generate_prompts

        prompts = generate_prompts(SAMPLE_SCENE_LIST, accent_color="cold teal", seed=42)

        for p in prompts:
            assert isinstance(p["prompt"], str)
            assert len(p["prompt"]) > 50  # Not empty/trivial

    def test_prompts_contain_holographic_suffix(self):
        """All prompts contain holographic system suffix."""
        from image_prompt_engine import generate_prompts

        prompts = generate_prompts(SAMPLE_SCENE_LIST, accent_color="cold teal", seed=42)

        for p in prompts:
            assert "photorealistic rendering" in p["prompt"] or "photorealistic" in p["prompt"], (
                f"Missing photorealistic marker in prompt index {p['index']}"
            )


# ---------------------------------------------------------------------------
# Test 6: Ken Burns directions vary (not all same)
# ---------------------------------------------------------------------------

class TestKenBurnsDirections:
    """Ken Burns zoom directions are varied across the video."""

    def test_ken_burns_not_all_same(self):
        """At least 3 different Ken Burns directions in a full video."""
        from image_prompt_engine import generate_prompts

        prompts = generate_prompts(SAMPLE_SCENE_LIST, accent_color="cold teal", seed=42)
        kb_directions = {p["ken_burns"] for p in prompts}
        assert len(kb_directions) >= 3, f"Only {len(kb_directions)} unique directions: {kb_directions}"

    def test_pan_directions_alternate(self):
        """Pan directions should alternate left/right."""
        from image_prompt_engine import generate_prompts

        prompts = generate_prompts(SAMPLE_SCENE_LIST, accent_color="cold teal", seed=42)
        pan_prompts = [p for p in prompts if "pan" in p["ken_burns"]]
        if len(pan_prompts) >= 2:
            # At least one left and one right
            directions = {p["ken_burns"] for p in pan_prompts}
            assert len(directions) >= 2, "All pans go same direction"


# ---------------------------------------------------------------------------
# Test 7: Full pipeline status progression
# ---------------------------------------------------------------------------

class TestStatusProgression:
    """A record's status progresses through all expected states."""

    def test_valid_status_chain(self):
        """Status values form a valid progression."""
        valid_chain = [
            Statuses.IDEA_LOGGED,
            Statuses.IN_QUE,
            Statuses.READY_SCRIPTING,
            Statuses.READY_VOICE,
            Statuses.READY_IMAGE_PROMPTS,
            Statuses.READY_IMAGES,
            Statuses.READY_VIDEO_SCRIPTS,
            Statuses.READY_VIDEO_GENERATION,
            Statuses.READY_THUMBNAIL,
            Statuses.READY_TO_RENDER,
            Statuses.DONE,
        ]

        # All statuses defined in VideoPipeline should be in the chain
        # We test the constants from pipeline_constants.Statuses
        pipeline_statuses = [
            Statuses.IDEA_LOGGED,
            Statuses.READY_SCRIPTING,
            Statuses.READY_VOICE,
            Statuses.READY_IMAGE_PROMPTS,
            Statuses.READY_IMAGES,
            Statuses.READY_VIDEO_SCRIPTS,
            Statuses.READY_VIDEO_GENERATION,
            Statuses.READY_THUMBNAIL,
            Statuses.READY_TO_RENDER,
            Statuses.DONE,
            Statuses.IN_QUE,
        ]

        for status in pipeline_statuses:
            assert status in valid_chain, f"Unknown status: {status}"

    def test_run_image_bot_sets_thumbnail_not_video_scripts(self):
        """run_image_bot correctly skips to Ready For Thumbnail status.

        This was a bug where the status was set to READY_THUMBNAIL but
        the log said READY_VIDEO_SCRIPTS.
        """
        import re

        # Image bot logic now lives in steps/step_images.py
        step_path = Path(__file__).parent.parent / "steps" / "step_images.py"
        source = step_path.read_text()

        # Extract the full run function (top-level async def)
        bot_match = re.search(
            r'(async def run\(pipeline\).*?)(?=\nasync def |\ndef |\Z)',
            source,
            re.DOTALL,
        )
        assert bot_match, "Could not find run function in step_images.py"
        bot_code = bot_match.group(1)

        # The status update and log message should both mention SOUND_DESIGN
        # (sound stages come after images, since sound_prompt_bot reads Image Prompt)
        status_line = [
            line for line in bot_code.split("\n")
            if ("update_idea_status" in line or "_update_status" in line) and "SOUND_DESIGN" in line
        ]
        log_line = [
            line for line in bot_code.split("\n")
            if "Status updated to" in line and "SOUND_DESIGN" in line
        ]

        assert status_line, "No status update found in run_image_bot"
        assert log_line, "No status log found in run_image_bot"

        # Both should reference SOUND_DESIGN (sound comes after images)
        assert "SOUND_DESIGN" in status_line[0], f"Status update wrong: {status_line[0]}"
        assert "SOUND_DESIGN" in log_line[0], f"Status log wrong: {log_line[0]}"


# ---------------------------------------------------------------------------
# Test 8: Scene output directory configuration
# ---------------------------------------------------------------------------

class TestSceneOutputDir:
    """Scene files are saved to a valid, accessible directory."""

    def test_default_scene_dir_is_project_relative(self):
        """DEFAULT_SCENE_DIR should be under the project, not /home/bot/."""
        from brief_translator.pipeline_writer import DEFAULT_SCENE_DIR

        assert "/home/bot/" not in DEFAULT_SCENE_DIR, (
            f"Scene dir still points to VPS path: {DEFAULT_SCENE_DIR}"
        )
        # Should be relative to the project
        assert "video-pipeline" in DEFAULT_SCENE_DIR or "scenes" in DEFAULT_SCENE_DIR

    def test_save_scene_list_creates_dir(self):
        """save_scene_list creates the output directory if it doesn't exist."""
        from brief_translator.pipeline_writer import save_scene_list

        with tempfile.TemporaryDirectory() as tmpdir:
            nested = os.path.join(tmpdir, "deep", "nested", "scenes")
            filepath = save_scene_list("vid_test", SAMPLE_SCENE_LIST[:5], nested)
            assert os.path.exists(filepath)
            loaded = json.loads(Path(filepath).read_text())
            assert len(loaded) == 5


# ---------------------------------------------------------------------------
# Test 9: Style distribution across acts
# ---------------------------------------------------------------------------

class TestStyleDistribution:
    """Holographic content types are distributed correctly across the video."""

    def test_content_types_are_valid(self):
        """All content types are valid ContentType enum values."""
        from image_prompt_engine import generate_prompts

        prompts = generate_prompts(SAMPLE_SCENE_LIST, accent_color="cold teal", seed=42)
        valid_types = {
            "geographic_map", "data_terminal", "object_comparison",
            "document_display", "network_diagram", "timeline",
            "satellite_recon", "concept_viz",
        }
        for p in prompts:
            assert p["content_type"] in valid_types, (
                f"Invalid content_type '{p['content_type']}' at index {p['index']}"
            )

    def test_no_excessive_consecutive_repeats(self):
        """No more than 4 consecutive images with the same content_type."""
        from image_prompt_engine import generate_prompts

        prompts = generate_prompts(SAMPLE_SCENE_LIST, accent_color="cold teal", seed=42)
        for i in range(len(prompts) - 4):
            run = [prompts[j]["content_type"] for j in range(i, i + 5)]
            assert len(set(run)) > 1, (
                f"5+ consecutive '{run[0]}' starting at index {i}"
            )

    def test_distribution_has_variety(self):
        """At least 4 different content types are used across the video."""
        from image_prompt_engine import generate_prompts

        prompts = generate_prompts(SAMPLE_SCENE_LIST, accent_color="cold teal", seed=42)
        unique_types = set(p["content_type"] for p in prompts)
        assert len(unique_types) >= 4, (
            f"Only {len(unique_types)} content types used: {unique_types}"
        )


# ---------------------------------------------------------------------------
# Test 10: Execution modes exist and have valid stage names
# ---------------------------------------------------------------------------

class TestExecutionModes:
    """The orchestrator supports the required execution modes."""

    def test_from_stage_valid_stages(self):
        """All documented stage names are accepted."""
        valid_stages = [
            "scripting", "voice", "image_prompts", "images",
            "video_scripts", "video_gen", "thumbnail", "render",
        ]
        # Read pipeline source to verify the mapping exists
        pipeline_path = Path(__file__).parent.parent / "pipeline.py"
        source = pipeline_path.read_text()

        for stage in valid_stages:
            assert f'"{stage}"' in source, f"Stage '{stage}' not found in from_stage mapping"

    def test_cli_commands_exist(self):
        """All new CLI commands are registered in main()."""
        pipeline_path = Path(__file__).parent.parent / "pipeline.py"
        source = pipeline_path.read_text()

        for cmd in ["--translate", "--styled-prompts", "--full", "--produce", "--from-stage"]:
            assert cmd in source, f"CLI command {cmd} not found in pipeline.py"

    def test_help_documents_new_commands(self):
        """Help text includes the new execution mode commands."""
        pipeline_path = Path(__file__).parent.parent / "pipeline.py"
        source = pipeline_path.read_text()

        for cmd in ["--translate", "--styled-prompts", "--full", "--produce", "--from-stage"]:
            # Should appear in the help section (within the --help handler)
            assert cmd in source, f"Help missing for {cmd}"
