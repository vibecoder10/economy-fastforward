"""Tests for the graduation process (full pipeline write)."""

import json
import os
import tempfile
import pytest
from brief_translator.pipeline_writer import (
    save_scene_list,
    build_pipeline_record,
    generate_video_id,
)


SAMPLE_BRIEF = {
    "headline": "The $1.25 Trillion Power Play",
    "thesis": "Corporate consolidation as a Machiavellian strategy",
    "framework_angle": "Machiavelli's The Prince",
    "executive_hook": "On February 2nd, the largest merger in history...",
    "historical_parallels": "The East India Company parallel...",
    "framework_analysis": "Three principles of The Prince...",
    "narrative_arc": "Three scenarios emerge...",
    "counter_arguments": "Critics argue market efficiency...",
    "title_options": "The $1.25 Trillion Power Play\nAlternate Title",
    "source_urls": "https://example.com/source1",
    "thumbnail_concepts": "Dark merger visualization",
    "visual_seeds": "Boardroom, trading floor, network diagram",
    "character_dossier": "CEO profile with background",
    "date_deep_dived": "2026-02-14",
}

SAMPLE_SCRIPT = """[ACT 1 — THE HOOK | 0:00-1:30 | ~225 words]
On February 2nd, 2026, something unprecedented happened...

[ACT 2 — THE SETUP | 1:30-6:00 | ~675 words]
To understand what just happened, you need context...

[ACT 3 — THE FRAMEWORK | 6:00-12:00 | ~900 words]
In 1513, Machiavelli wrote something that explains all of this...

[ACT 4 — THE HISTORY | 12:00-17:00 | ~750 words]
In 1600, a group of London merchants received a charter...

[ACT 5 — THE IMPLICATIONS | 17:00-22:00 | ~750 words]
Now the defenders will tell you this is fine...

[ACT 6 — THE LESSON | 22:00-25:00 | ~450 words]
So what do you do with this information?..."""

SAMPLE_SCENES = [
    {
        "scene_number": i,
        "act": min(6, (i - 1) // 23 + 1),
        "style": ["dossier", "schema", "echo"][i % 3] if i % 3 != 2 or (i - 1) // 23 + 1 not in [1, 2, 6] else "dossier",
        "description": f"Scene {i} description",
        "script_excerpt": f"Narration for scene {i}",
        "composition_hint": "wide",
    }
    for i in range(1, 137)
]


class TestSaveSceneList:
    def test_saves_json_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = save_scene_list("vid_test_001", SAMPLE_SCENES[:5], tmpdir)
            assert os.path.exists(filepath)
            assert filepath.endswith("_scenes.json")

    def test_saved_json_is_valid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = save_scene_list("vid_test_002", SAMPLE_SCENES[:5], tmpdir)
            with open(filepath) as f:
                data = json.load(f)
            assert len(data) == 5

    def test_creates_directory_if_needed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            nested = os.path.join(tmpdir, "nested", "dir")
            filepath = save_scene_list("vid_test_003", SAMPLE_SCENES[:5], nested)
            assert os.path.exists(filepath)

    def test_filename_includes_video_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = save_scene_list("vid_20260214_120000", SAMPLE_SCENES[:5], tmpdir)
            assert "vid_20260214_120000" in filepath


class TestBuildPipelineRecord:
    def test_contains_all_required_fields(self):
        record = build_pipeline_record(
            SAMPLE_BRIEF, SAMPLE_SCRIPT, SAMPLE_SCENES,
            "cold_teal", "rec123", "/tmp/scenes.json", "vid_001"
        )
        required = [
            "Video Title", "Hook Script", "Past Context", "Present Parallel",
            "Future Prediction", "Writer Guidance", "Original DNA",
            "Status", "Script", "Scene File Path", "Accent Color",
            "Video ID", "Scene Count", "Validation Status",
        ]
        for field in required:
            assert field in record, f"Missing field: {field}"

    def test_scene_count_matches_list(self):
        record = build_pipeline_record(
            SAMPLE_BRIEF, SAMPLE_SCRIPT, SAMPLE_SCENES,
            "cold_teal", "rec123", "/tmp/scenes.json", "vid_001"
        )
        assert record["Scene Count"] == len(SAMPLE_SCENES)

    def test_status_is_queued(self):
        record = build_pipeline_record(
            SAMPLE_BRIEF, SAMPLE_SCRIPT, SAMPLE_SCENES,
            "cold_teal", "rec123", "/tmp/scenes.json", "vid_001"
        )
        assert record["Status"] == "Queued"

    def test_validation_status_is_validated(self):
        record = build_pipeline_record(
            SAMPLE_BRIEF, SAMPLE_SCRIPT, SAMPLE_SCENES,
            "cold_teal", "rec123", "/tmp/scenes.json", "vid_001"
        )
        assert record["Validation Status"] == "validated"

    def test_original_dna_traceable_to_source(self):
        record = build_pipeline_record(
            SAMPLE_BRIEF, SAMPLE_SCRIPT, SAMPLE_SCENES,
            "cold_teal", "recABC123", "/tmp/scenes.json", "vid_001"
        )
        dna = json.loads(record["Original DNA"])
        assert dna["meta_data"]["source_idea_id"] == "recABC123"
        assert dna["meta_data"]["framework"] == "Machiavelli's The Prince"


class TestFullGraduationFlow:
    """Integration-style tests for the full graduation data flow."""

    def test_brief_to_record_data_integrity(self):
        """Verify data flows correctly from brief through to pipeline record."""
        record = build_pipeline_record(
            SAMPLE_BRIEF, SAMPLE_SCRIPT, SAMPLE_SCENES,
            "cold_teal", "rec123", "/tmp/scenes.json", "vid_001"
        )

        # Title comes from first title option
        assert record["Video Title"] == "The $1.25 Trillion Power Play"

        # Hook comes from executive_hook
        assert record["Hook Script"] == SAMPLE_BRIEF["executive_hook"]

        # Past Context comes from historical_parallels
        assert record["Past Context"] == SAMPLE_BRIEF["historical_parallels"]

        # Present Parallel comes from framework_analysis
        assert record["Present Parallel"] == SAMPLE_BRIEF["framework_analysis"]

        # Future Prediction comes from narrative_arc
        assert record["Future Prediction"] == SAMPLE_BRIEF["narrative_arc"]

    def test_scene_list_roundtrip(self):
        """Verify scene list can be saved and loaded without data loss."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = save_scene_list("vid_roundtrip", SAMPLE_SCENES, tmpdir)
            with open(filepath) as f:
                loaded = json.load(f)

            assert len(loaded) == len(SAMPLE_SCENES)
            for original, loaded_scene in zip(SAMPLE_SCENES, loaded):
                assert original["scene_number"] == loaded_scene["scene_number"]
                assert original["style"] == loaded_scene["style"]
                assert original["description"] == loaded_scene["description"]
