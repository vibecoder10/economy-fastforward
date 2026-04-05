"""Tests for the video dispatch system."""

import json
import pytest
from unittest.mock import AsyncMock, patch

from video_dispatch.models import (
    Bridge,
    ContinuityBible,
    Keyframe,
    ProductionSheet,
    TaskStatus,
)
from video_dispatch.dispatch import (
    DispatchClient,
    dispatch_keyframes,
    dispatch_bridges,
    run_dispatch,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_SHEET = {
    "title": "Test Story",
    "total_duration_s": 30,
    "visual_style": "cinematic",
    "aspect_ratio": "16:9",
    "bible": {
        "characters": [{"name": "Agent X", "appearance": "tall, dark suit"}],
        "locations": [{"name": "Office", "description": "modern glass building"}],
        "lighting": "Rembrandt lighting",
        "camera": "Arri Alexa",
        "color_grade": "teal and orange",
        "aspect_ratio": "16:9",
    },
    "keyframes": [
        {
            "keyframe_id": "KF-001",
            "shot_type": "wide establishing",
            "prompt": "A tall man in a dark suit stands before a modern glass building at dusk.",
        },
        {
            "keyframe_id": "KF-002",
            "shot_type": "medium",
            "prompt": "The man walks through the lobby, light reflecting off marble floors.",
        },
        {
            "keyframe_id": "KF-003",
            "shot_type": "close-up",
            "prompt": "Close-up of the man's face, determination in his eyes.",
        },
    ],
    "bridges": [
        {
            "bridge_id": "BR-001",
            "from_keyframe": "KF-001",
            "to_keyframe": "KF-002",
            "prompt": "Camera slowly dollies forward as the man begins walking toward the entrance.",
            "duration": 6,
        },
        {
            "bridge_id": "BR-002",
            "from_keyframe": "KF-002",
            "to_keyframe": "KF-003",
            "prompt": "Camera pushes in as the man pauses, turning to face the camera.",
            "duration": 6,
        },
    ],
}


@pytest.fixture
def sample_sheet():
    return ProductionSheet.from_dict(SAMPLE_SHEET)


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class TestModels:
    def test_continuity_bible_from_dict(self):
        bible = ContinuityBible.from_dict(SAMPLE_SHEET["bible"])
        assert len(bible.characters) == 1
        assert bible.characters[0]["name"] == "Agent X"
        assert bible.lighting == "Rembrandt lighting"
        assert bible.aspect_ratio == "16:9"

    def test_continuity_bible_defaults(self):
        bible = ContinuityBible.from_dict({})
        assert bible.characters == []
        assert bible.aspect_ratio == "16:9"

    def test_production_sheet_from_dict(self, sample_sheet):
        assert sample_sheet.title == "Test Story"
        assert len(sample_sheet.keyframes) == 3
        assert len(sample_sheet.bridges) == 2
        assert sample_sheet.total_duration_s == 30

    def test_keyframe_defaults(self, sample_sheet):
        kf = sample_sheet.keyframes[0]
        assert kf.status == TaskStatus.PENDING
        assert kf.task_id is None
        assert kf.image_url is None
        assert kf.aspect_ratio == "16:9"

    def test_bridge_defaults(self, sample_sheet):
        br = sample_sheet.bridges[0]
        assert br.status == TaskStatus.PENDING
        assert br.duration == 6
        assert br.mode == "normal"
        assert br.resolution == "720p"

    def test_assembly_order_auto_generated(self, sample_sheet):
        order = sample_sheet.assembly_order
        assert len(order) == 5  # 3 keyframes + 2 bridges interleaved
        assert order[0] == {"type": "keyframe", "id": "KF-001"}
        assert order[1] == {"type": "bridge", "id": "BR-001"}
        assert order[2] == {"type": "keyframe", "id": "KF-002"}

    def test_explicit_assembly_order(self):
        data = {**SAMPLE_SHEET, "assembly_order": [{"type": "keyframe", "id": "KF-003"}]}
        sheet = ProductionSheet.from_dict(data)
        assert len(sheet.assembly_order) == 1
        assert sheet.assembly_order[0]["id"] == "KF-003"

    def test_bridge_duration_inherits_default(self):
        data = {
            **SAMPLE_SHEET,
            "bridges": [
                {
                    "bridge_id": "BR-X",
                    "from_keyframe": "KF-001",
                    "to_keyframe": "KF-002",
                    "prompt": "test",
                }
            ],
        }
        sheet = ProductionSheet.from_dict(data)
        assert sheet.bridges[0].duration == 6


# ---------------------------------------------------------------------------
# Dispatch client tests (mocked API)
# ---------------------------------------------------------------------------

class TestDispatchClient:
    @pytest.mark.asyncio
    async def test_generate_keyframe_success(self):
        client = DispatchClient(api_key="test-key")
        kf = Keyframe(keyframe_id="KF-001", shot_type="wide", prompt="test prompt")

        with patch.object(client, "_create_task", new_callable=AsyncMock) as mock_create, \
             patch.object(client, "_poll", new_callable=AsyncMock) as mock_poll:
            mock_create.return_value = "task-123"
            mock_poll.return_value = ["https://example.com/image.png"]

            result = await client.generate_keyframe(kf)
            assert result.status == TaskStatus.COMPLETED
            assert result.image_url == "https://example.com/image.png"
            assert result.task_id == "task-123"

    @pytest.mark.asyncio
    async def test_generate_keyframe_create_fails(self):
        client = DispatchClient(api_key="test-key")
        kf = Keyframe(keyframe_id="KF-001", shot_type="wide", prompt="test")

        with patch.object(client, "_create_task", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = None

            result = await client.generate_keyframe(kf)
            assert result.status == TaskStatus.FAILED
            assert "Failed to create task" in result.error

    @pytest.mark.asyncio
    async def test_generate_keyframe_poll_fails(self):
        client = DispatchClient(api_key="test-key")
        kf = Keyframe(keyframe_id="KF-001", shot_type="wide", prompt="test")

        with patch.object(client, "_create_task", new_callable=AsyncMock) as mock_create, \
             patch.object(client, "_poll", new_callable=AsyncMock) as mock_poll:
            mock_create.return_value = "task-123"
            mock_poll.return_value = None

            result = await client.generate_keyframe(kf)
            assert result.status == TaskStatus.FAILED

    @pytest.mark.asyncio
    async def test_generate_bridge_success(self):
        client = DispatchClient(api_key="test-key")
        br = Bridge(
            bridge_id="BR-001",
            from_keyframe="KF-001",
            to_keyframe="KF-002",
            prompt="camera moves forward",
            duration=6,
        )

        with patch.object(client, "_create_task", new_callable=AsyncMock) as mock_create, \
             patch.object(client, "_poll", new_callable=AsyncMock) as mock_poll:
            mock_create.return_value = "task-456"
            mock_poll.return_value = ["https://example.com/video.mp4"]

            result = await client.generate_bridge(br, "https://example.com/kf.png")
            assert result.status == TaskStatus.COMPLETED
            assert result.video_url == "https://example.com/video.mp4"

    @pytest.mark.asyncio
    async def test_generate_bridge_retries(self):
        client = DispatchClient(api_key="test-key")
        br = Bridge(
            bridge_id="BR-001",
            from_keyframe="KF-001",
            to_keyframe="KF-002",
            prompt="test",
        )

        with patch.object(client, "_create_task", new_callable=AsyncMock) as mock_create, \
             patch.object(client, "_poll", new_callable=AsyncMock) as mock_poll:
            # First two attempts fail, third succeeds
            mock_create.side_effect = ["t1", "t2", "t3"]
            mock_poll.side_effect = [None, None, ["https://example.com/v.mp4"]]

            result = await client.generate_bridge(br, "https://img.com/kf.png")
            assert result.status == TaskStatus.COMPLETED
            assert mock_create.call_count == 3

    @pytest.mark.asyncio
    async def test_generate_bridge_clamps_duration(self):
        client = DispatchClient(api_key="test-key")
        br = Bridge(
            bridge_id="BR-001",
            from_keyframe="KF-001",
            to_keyframe="KF-002",
            prompt="test",
            duration=50,  # Over max
        )

        with patch.object(client, "_create_task", new_callable=AsyncMock) as mock_create, \
             patch.object(client, "_poll", new_callable=AsyncMock) as mock_poll:
            mock_create.return_value = "t1"
            mock_poll.return_value = ["https://example.com/v.mp4"]

            await client.generate_bridge(br, "https://img.com/kf.png")
            # Check the payload had duration clamped to 30
            call_payload = mock_create.call_args[0][0]
            assert call_payload["input"]["duration"] == 30


# ---------------------------------------------------------------------------
# Orchestration tests
# ---------------------------------------------------------------------------

class TestOrchestration:
    @pytest.mark.asyncio
    async def test_dispatch_keyframes(self):
        client = DispatchClient(api_key="test-key")
        keyframes = [
            Keyframe(keyframe_id="KF-001", shot_type="wide", prompt="p1"),
            Keyframe(keyframe_id="KF-002", shot_type="medium", prompt="p2"),
        ]

        with patch.object(client, "_create_task", new_callable=AsyncMock) as mock_create, \
             patch.object(client, "_poll", new_callable=AsyncMock) as mock_poll:
            mock_create.side_effect = ["t1", "t2"]
            mock_poll.side_effect = [
                ["https://img1.com/a.png"],
                ["https://img2.com/b.png"],
            ]

            results = await dispatch_keyframes(client, keyframes)
            assert len(results) == 2
            assert all(kf.status == TaskStatus.COMPLETED for kf in results)

    @pytest.mark.asyncio
    async def test_dispatch_bridges_skips_missing_source(self, sample_sheet):
        # Mark first keyframe as failed (no image)
        sample_sheet.keyframes[0].status = TaskStatus.FAILED

        client = DispatchClient(api_key="test-key")

        with patch.object(client, "_create_task", new_callable=AsyncMock) as mock_create, \
             patch.object(client, "_poll", new_callable=AsyncMock) as mock_poll:
            mock_create.return_value = "t1"
            mock_poll.return_value = ["https://v.com/v.mp4"]

            results = await dispatch_bridges(client, sample_sheet)
            # BR-001 should be skipped (KF-001 has no image)
            assert results[0].status == TaskStatus.FAILED
            assert "has no image" in results[0].error.lower()

    @pytest.mark.asyncio
    async def test_dry_run(self, sample_sheet):
        manifest = await run_dispatch(sample_sheet, dry_run=True)
        assert manifest["status"] == "dry_run"
        assert manifest["keyframes"] == 3
        assert manifest["bridges"] == 2


# ---------------------------------------------------------------------------
# End-to-end manifest test
# ---------------------------------------------------------------------------

class TestManifest:
    @pytest.mark.asyncio
    async def test_full_manifest_structure(self, sample_sheet):
        with patch.object(DispatchClient, "_create_task", new_callable=AsyncMock) as mock_create, \
             patch.object(DispatchClient, "_poll", new_callable=AsyncMock) as mock_poll:
            mock_create.side_effect = ["t1", "t2", "t3", "t4", "t5"]
            mock_poll.side_effect = [
                ["https://img1.png"],
                ["https://img2.png"],
                ["https://img3.png"],
                ["https://vid1.mp4"],
                ["https://vid2.mp4"],
            ]

            manifest = await run_dispatch(sample_sheet, api_key="test")
            assert manifest["title"] == "Test Story"
            assert manifest["summary"]["keyframes_completed"] == 3
            assert manifest["summary"]["bridges_completed"] == 2
            assert len(manifest["keyframes"]) == 3
            assert len(manifest["bridges"]) == 2
            assert manifest["assembly_order"][0]["type"] == "keyframe"
