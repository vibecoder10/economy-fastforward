"""Tests for pipeline field mapping (Step 4)."""

import json
import pytest
from brief_translator.pipeline_writer import (
    build_writer_guidance,
    build_original_dna,
    build_pipeline_record,
    generate_video_id,
)


SAMPLE_BRIEF = {
    "headline": "The $1.25 Trillion Power Play",
    "thesis": "Corporate consolidation as a Machiavellian strategy",
    "framework_angle": "Machiavelli's The Prince",
    "executive_hook": "On February 2nd, the largest merger in history...",
    "historical_parallels": "The East India Company...",
    "framework_analysis": "Three principles of The Prince map directly...",
    "narrative_arc": "This trajectory leads to three scenarios...",
    "counter_arguments": "Defenders will argue this is simply market efficiency...",
    "title_options": "The $1.25 Trillion Power Play\nWhen Corporations Become Empires\nThe Machiavelli Merger",
    "source_urls": "https://example.com/article1\nhttps://example.com/article2",
    "thumbnail_concepts": "Dark silhouette merging two spheres\nPower handshake over city",
    "visual_seeds": "Modern boardroom, historical trading floor, data network",
    "character_dossier": "Central figure: CEO profile...",
    "date_deep_dived": "2026-02-14",
}


class TestBuildWriterGuidance:
    def test_includes_framework(self):
        guidance = build_writer_guidance(SAMPLE_BRIEF, "cold_teal", 136)
        assert "Machiavelli" in guidance

    def test_includes_accent_color(self):
        guidance = build_writer_guidance(SAMPLE_BRIEF, "cold_teal", 136)
        assert "cold_teal" in guidance

    def test_includes_scene_count(self):
        guidance = build_writer_guidance(SAMPLE_BRIEF, "cold_teal", 140)
        assert "140" in guidance

    def test_truncates_counter_arguments(self):
        brief = dict(SAMPLE_BRIEF)
        brief["counter_arguments"] = "x" * 500
        guidance = build_writer_guidance(brief, "cold_teal", 136)
        assert guidance.endswith("...")

    def test_includes_style_directions(self):
        guidance = build_writer_guidance(SAMPLE_BRIEF, "warm_amber", 136)
        assert "Dossier" in guidance
        assert "Schema" in guidance
        assert "Echo" in guidance


class TestBuildOriginalDNA:
    def test_returns_valid_json(self):
        dna = build_original_dna(SAMPLE_BRIEF, "rec123", "cold_teal", 136)
        parsed = json.loads(dna)
        assert "meta_data" in parsed

    def test_includes_source_idea_id(self):
        dna = build_original_dna(SAMPLE_BRIEF, "rec123", "cold_teal", 136)
        parsed = json.loads(dna)
        assert parsed["meta_data"]["source_idea_id"] == "rec123"

    def test_includes_scene_count(self):
        dna = build_original_dna(SAMPLE_BRIEF, "rec123", "cold_teal", 140)
        parsed = json.loads(dna)
        assert parsed["meta_data"]["scene_count"] == 140

    def test_includes_accent_color(self):
        dna = build_original_dna(SAMPLE_BRIEF, "rec123", "warm_amber", 136)
        parsed = json.loads(dna)
        assert parsed["meta_data"]["accent_color"] == "warm_amber"

    def test_includes_translated_at_timestamp(self):
        dna = build_original_dna(SAMPLE_BRIEF, "rec123", "cold_teal", 136)
        parsed = json.loads(dna)
        assert "translated_at" in parsed["meta_data"]


class TestBuildPipelineRecord:
    def test_maps_video_title_from_first_option(self):
        record = build_pipeline_record(
            SAMPLE_BRIEF, "script text", [], "cold_teal", "rec123", "/tmp/scenes.json", "vid_001"
        )
        assert record["Video Title"] == "The $1.25 Trillion Power Play"

    def test_falls_back_to_headline_when_no_title_options(self):
        brief = dict(SAMPLE_BRIEF)
        brief.pop("title_options")
        record = build_pipeline_record(
            brief, "script text", [], "cold_teal", "rec123", "/tmp/scenes.json", "vid_001"
        )
        assert record["Video Title"] == "The $1.25 Trillion Power Play"

    def test_maps_hook_script(self):
        record = build_pipeline_record(
            SAMPLE_BRIEF, "script text", [], "cold_teal", "rec123", "/tmp/scenes.json", "vid_001"
        )
        assert "February 2nd" in record["Hook Script"]

    def test_extracts_reference_url(self):
        record = build_pipeline_record(
            SAMPLE_BRIEF, "script text", [], "cold_teal", "rec123", "/tmp/scenes.json", "vid_001"
        )
        assert record["Reference URL"] == "https://example.com/article1"

    def test_extracts_thumbnail_prompt(self):
        record = build_pipeline_record(
            SAMPLE_BRIEF, "script text", [], "cold_teal", "rec123", "/tmp/scenes.json", "vid_001"
        )
        assert "silhouette" in record["Thumbnail Prompt"]

    def test_sets_queued_status(self):
        record = build_pipeline_record(
            SAMPLE_BRIEF, "script text", [], "cold_teal", "rec123", "/tmp/scenes.json", "vid_001"
        )
        assert record["Status"] == "Queued"

    def test_includes_script(self):
        record = build_pipeline_record(
            SAMPLE_BRIEF, "full script content", [], "cold_teal", "rec123", "/tmp/scenes.json", "vid_001"
        )
        assert record["Script"] == "full script content"

    def test_includes_scene_file_path(self):
        record = build_pipeline_record(
            SAMPLE_BRIEF, "script", [], "cold_teal", "rec123", "/tmp/scenes.json", "vid_001"
        )
        assert record["Scene File Path"] == "/tmp/scenes.json"

    def test_includes_accent_color(self):
        record = build_pipeline_record(
            SAMPLE_BRIEF, "script", [], "muted_crimson", "rec123", "/tmp/scenes.json", "vid_001"
        )
        assert record["Accent Color"] == "muted_crimson"

    def test_includes_scene_count(self):
        scenes = [{"scene_number": i} for i in range(1, 137)]
        record = build_pipeline_record(
            SAMPLE_BRIEF, "script", scenes, "cold_teal", "rec123", "/tmp/scenes.json", "vid_001"
        )
        assert record["Scene Count"] == 136

    def test_original_dna_is_valid_json(self):
        record = build_pipeline_record(
            SAMPLE_BRIEF, "script", [], "cold_teal", "rec123", "/tmp/scenes.json", "vid_001"
        )
        parsed = json.loads(record["Original DNA"])
        assert parsed["meta_data"]["source_idea_id"] == "rec123"


class TestGenerateVideoId:
    def test_starts_with_vid_prefix(self):
        vid_id = generate_video_id()
        assert vid_id.startswith("vid_")

    def test_contains_timestamp(self):
        vid_id = generate_video_id()
        # Format: vid_YYYYMMDD_HHMMSS
        parts = vid_id.split("_")
        assert len(parts) == 3
        assert len(parts[1]) == 8  # date
        assert len(parts[2]) == 6  # time
