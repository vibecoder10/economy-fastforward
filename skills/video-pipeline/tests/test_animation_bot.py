"""Tests for AnimationBot — the adapter between animation_prompt_engine and Grok Imagine."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bots.animation_bot import AnimationBot
from pipeline_config import VideoConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_image_record(
    scene=1, index=1, status="Done", has_clip=False,
    drive_url="https://drive.google.com/file/d/abc123/view",
    intensity="low", content_type="B_data_terminal",
    video_prompt=None,
):
    rec = {
        "id": f"rec_{scene}_{index}",
        "Scene": scene,
        "Image Index": index,
        "Status": status,
        "Drive Image URL": drive_url,
        "Intensity": intensity,
        "Content Type": content_type,
    }
    if has_clip:
        rec["Video Clip URL"] = "https://drive.google.com/already_done"
    if video_prompt:
        rec["Video Prompt"] = video_prompt
    return rec


def _mock_clients(image_records):
    """Create mocked image_client, airtable, and google clients."""
    image_client = AsyncMock()
    image_client.generate_video = AsyncMock(return_value="https://cdn.kie.ai/video123.mp4")
    image_client.download_image = AsyncMock(return_value=b"fake_video_bytes")

    airtable = MagicMock()
    airtable.get_all_images_for_video.return_value = image_records
    airtable.update_image_animation_fields.return_value = {"id": "rec_ok"}

    google = MagicMock()
    google.get_direct_drive_url.return_value = "https://drive.google.com/uc?id=abc123"
    google.upload_video.return_value = {"id": "drive_file_id"}
    google.make_file_public.return_value = "https://drive.google.com/uc?id=drive_file_id"

    return image_client, airtable, google


# ---------------------------------------------------------------------------
# Tests: AnimationBot.run()
# ---------------------------------------------------------------------------

class TestAnimationBotRun:
    """Test the main run() flow."""

    def test_skips_already_animated(self):
        """Images with Video Clip URL are skipped."""
        records = [
            _make_image_record(scene=1, index=1, has_clip=True),
            _make_image_record(scene=1, index=2, has_clip=True),
        ]
        image_client, airtable, google = _mock_clients(records)
        bot = AnimationBot(image_client, airtable, google)
        config = VideoConfig(video_length_minutes=5, clip_duration_seconds=6)

        result = asyncio.get_event_loop().run_until_complete(
            bot.run("Test Video", config, "folder_id")
        )

        assert result["clips_generated"] == 0
        assert result["clips_failed"] == 0
        image_client.generate_video.assert_not_called()

    def test_generates_clips_for_pending_images(self):
        """Pending images get animated via Grok Imagine."""
        records = [
            _make_image_record(scene=1, index=1),
            _make_image_record(scene=1, index=2),
            _make_image_record(scene=2, index=1),
        ]
        image_client, airtable, google = _mock_clients(records)
        bot = AnimationBot(image_client, airtable, google)
        config = VideoConfig(video_length_minutes=5, clip_duration_seconds=6)

        result = asyncio.get_event_loop().run_until_complete(
            bot.run("Test Video", config, "folder_id")
        )

        assert result["clips_generated"] == 3
        assert result["clips_failed"] == 0
        assert result["actual_cost"] == pytest.approx(0.30, abs=0.01)
        assert image_client.generate_video.call_count == 3

        # Verify clip duration passed to Grok
        for call in image_client.generate_video.call_args_list:
            assert call.kwargs.get("duration") == 6 or call.args[2] == 6

    def test_respects_10s_clip_duration(self):
        """Config with 10s clips passes duration=10 to Grok."""
        records = [_make_image_record(scene=1, index=1)]
        image_client, airtable, google = _mock_clients(records)
        bot = AnimationBot(image_client, airtable, google)
        config = VideoConfig(video_length_minutes=10, clip_duration_seconds=10)

        asyncio.get_event_loop().run_until_complete(
            bot.run("Test Video", config, "folder_id")
        )

        call_args = image_client.generate_video.call_args
        # duration is the 3rd positional arg or keyword
        assert call_args[1].get("duration") == 10 or call_args[0][2] == 10

    def test_handles_generation_failure(self):
        """Failed Grok calls mark the record as Failed."""
        records = [_make_image_record(scene=1, index=1)]
        image_client, airtable, google = _mock_clients(records)
        image_client.generate_video = AsyncMock(return_value=None)
        bot = AnimationBot(image_client, airtable, google)
        config = VideoConfig(video_length_minutes=5, clip_duration_seconds=6)

        result = asyncio.get_event_loop().run_until_complete(
            bot.run("Test Video", config, "folder_id")
        )

        assert result["clips_generated"] == 0
        assert result["clips_failed"] == 1
        # Should have been marked "Failed"
        airtable.update_image_animation_fields.assert_any_call(
            "rec_1_1", animation_status="Failed"
        )

    def test_skips_non_done_images(self):
        """Only Status=Done images are processed."""
        records = [
            _make_image_record(scene=1, index=1, status="Pending"),
            _make_image_record(scene=1, index=2, status="Done"),
        ]
        image_client, airtable, google = _mock_clients(records)
        bot = AnimationBot(image_client, airtable, google)
        config = VideoConfig(video_length_minutes=5, clip_duration_seconds=6)

        result = asyncio.get_event_loop().run_until_complete(
            bot.run("Test Video", config, "folder_id")
        )

        assert result["clips_generated"] == 1
        assert image_client.generate_video.call_count == 1

    def test_mixed_success_and_failure(self):
        """Some clips succeed, some fail — counts are correct."""
        records = [
            _make_image_record(scene=1, index=1),
            _make_image_record(scene=1, index=2),
            _make_image_record(scene=2, index=1),
        ]
        image_client, airtable, google = _mock_clients(records)
        # First succeeds, second fails, third succeeds
        image_client.generate_video = AsyncMock(
            side_effect=["https://cdn.kie.ai/v1.mp4", None, "https://cdn.kie.ai/v3.mp4"]
        )
        bot = AnimationBot(image_client, airtable, google)
        config = VideoConfig(video_length_minutes=5, clip_duration_seconds=6)

        result = asyncio.get_event_loop().run_until_complete(
            bot.run("Test Video", config, "folder_id")
        )

        assert result["clips_generated"] == 2
        assert result["clips_failed"] == 1
        assert result["actual_cost"] == pytest.approx(0.20, abs=0.01)


# ---------------------------------------------------------------------------
# Tests: AnimationBot._build_prompt()
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    """Test prompt generation from image record metadata."""

    def _make_bot(self):
        image_client, airtable, google = _mock_clients([])
        return AnimationBot(image_client, airtable, google)

    def test_uses_existing_video_prompt(self):
        """If Video Prompt field exists, uses it directly."""
        bot = self._make_bot()
        record = _make_image_record(video_prompt="Custom Grok prompt here")
        prompt = bot._build_prompt(record, 10)
        assert prompt == "Custom Grok prompt here"

    def test_generates_from_intensity_metadata(self):
        """Without Video Prompt, generates from intensity + content type."""
        bot = self._make_bot()
        record = _make_image_record(intensity="high", content_type="A_geographic_map")
        prompt = bot._build_prompt(record, 6)
        assert "6 seconds" in prompt
        assert "shockwave" in prompt.lower() or "Dramatic" in prompt

    def test_defaults_to_low_intensity(self):
        """Unknown intensity falls back to low."""
        bot = self._make_bot()
        record = _make_image_record(intensity="EXTREME")
        prompt = bot._build_prompt(record, 10)
        assert "Subtle" in prompt or "ambient" in prompt.lower()

    def test_default_content_type(self):
        """Missing content type defaults to B_data_terminal."""
        bot = self._make_bot()
        record = _make_image_record(content_type="")
        prompt = bot._build_prompt(record, 10)
        # Should contain data terminal motion text
        assert "10 seconds" in prompt


# ---------------------------------------------------------------------------
# Tests: AnimationBot._get_image_url()
# ---------------------------------------------------------------------------

class TestGetImageUrl:
    """Test image URL extraction from records."""

    def _make_bot(self):
        image_client, airtable, google = _mock_clients([])
        return AnimationBot(image_client, airtable, google)

    def test_prefers_drive_url(self):
        bot = self._make_bot()
        record = {
            "Drive Image URL": "https://drive.google.com/file/d/abc",
            "Image": [{"url": "https://airtable.cdn/expiring.png"}],
        }
        assert bot._get_image_url(record) == "https://drive.google.com/file/d/abc"

    def test_falls_back_to_attachment(self):
        bot = self._make_bot()
        record = {"Image": [{"url": "https://airtable.cdn/img.png"}]}
        assert bot._get_image_url(record) == "https://airtable.cdn/img.png"

    def test_returns_none_when_no_url(self):
        bot = self._make_bot()
        assert bot._get_image_url({}) is None
        assert bot._get_image_url({"Image": []}) is None


# ---------------------------------------------------------------------------
# Tests: Pipeline integration (status wiring)
# ---------------------------------------------------------------------------

class TestPipelineStatusWiring:
    """Verify the animation status is wired into pipeline constants."""

    def test_status_constant_in_pipeline_source(self):
        """STATUS_READY_ANIMATION is defined in pipeline.py source."""
        pipeline_path = os.path.join(os.path.dirname(__file__), "..", "pipeline.py")
        source = open(pipeline_path).read()
        assert 'STATUS_READY_ANIMATION = "Ready For Animation"' in source

    def test_animation_in_run_from_stage(self):
        """run_from_stage mapping includes 'animation'."""
        pipeline_path = os.path.join(os.path.dirname(__file__), "..", "pipeline.py")
        source = open(pipeline_path).read()
        assert '"animation": self.STATUS_READY_ANIMATION' in source

    def test_animation_in_run_next_step(self):
        """run_next_step routes Ready For Animation to animation bot."""
        pipeline_path = os.path.join(os.path.dirname(__file__), "..", "pipeline.py")
        source = open(pipeline_path).read()
        assert "STATUS_READY_ANIMATION" in source
        assert "Animation Bot" in source
