"""Tests for thumbnail analyzer."""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from autopilot.analysis.thumbnail_analyzer import ThumbnailAnalyzer, ThumbnailAnalysis


class TestThumbnailAnalyzer:
    """Test suite for thumbnail analysis."""

    @pytest.fixture
    def mock_anthropic(self):
        """Mock Anthropic client."""
        mock = Mock()
        mock.messages = Mock()
        mock.messages.create = Mock()  # Anthropic SDK is sync, not async
        return mock

    @pytest.fixture
    def analyzer(self, mock_anthropic):
        return ThumbnailAnalyzer(anthropic_client=mock_anthropic)

    @pytest.fixture
    def sample_vision_response(self):
        """Sample Claude vision response."""
        return {
            "colors": {
                "background": "deep red gradient",
                "text": "bright yellow with black outline",
                "accents": "white, gold"
            },
            "composition": "face_left_text_right",
            "text": {
                "lines": 2,
                "size_pct": 65,
                "style": "bold caps"
            },
            "subject": {
                "face": True,
                "expression": "stern/serious",
                "type": "leader portrait"
            },
            "style": "editorial illustration, high saturation",
            "confidence": 0.85
        }

    def test_parse_vision_response(self, analyzer, sample_vision_response):
        """Should parse vision response into ThumbnailAnalysis."""
        import json
        analysis = analyzer._parse_response(json.dumps(sample_vision_response))

        assert analysis is not None
        assert analysis.composition == "face_left_text_right"
        assert analysis.colors["background"] == "deep red gradient"
        assert analysis.text["lines"] == 2
        assert analysis.confidence == 0.85

    def test_parse_invalid_response(self, analyzer):
        """Should return None for invalid JSON."""
        analysis = analyzer._parse_response("not valid json")
        assert analysis is None

    def test_parse_incomplete_response(self, analyzer):
        """Should handle incomplete but valid JSON."""
        partial = '{"colors": {"background": "red"}, "composition": "centered", "confidence": 0.5}'
        analysis = analyzer._parse_response(partial)

        assert analysis is not None
        assert analysis.colors["background"] == "red"
        assert analysis.composition == "centered"
        # Missing fields should have defaults
        assert analysis.text == {}
        assert analysis.subject == {}

    def test_analyze_success(self, analyzer, mock_anthropic, sample_vision_response):
        """Should analyze thumbnail and return structured data."""
        import json
        # Mock successful API response
        mock_response = Mock()
        mock_response.content = [Mock(text=json.dumps(sample_vision_response))]
        mock_anthropic.messages.create.return_value = mock_response

        async def run_test():
            with patch.object(analyzer, '_download_image', new_callable=AsyncMock) as mock_download:
                mock_download.return_value = b"fake_image_bytes"
                return await analyzer.analyze("https://example.com/thumb.jpg")

        analysis = asyncio.run(run_test())

        assert analysis is not None
        assert analysis.composition == "face_left_text_right"

    def test_analyze_image_404(self, analyzer):
        """Should return None on image download failure."""
        async def run_test():
            with patch.object(analyzer, '_download_image', new_callable=AsyncMock) as mock_download:
                mock_download.return_value = None
                return await analyzer.analyze("https://example.com/notfound.jpg")

        analysis = asyncio.run(run_test())

        assert analysis is None

    def test_get_thumbnail_url_maxres(self):
        """Should prefer maxres thumbnail."""
        url = ThumbnailAnalyzer.get_thumbnail_url("dQw4w9WgXcQ")
        assert "maxresdefault" in url or "hqdefault" in url

    def test_vision_prompt_contains_required_elements(self, analyzer):
        """Vision prompt should ask for all required elements."""
        prompt = analyzer.VISION_PROMPT
        assert "colors" in prompt.lower()
        assert "composition" in prompt.lower()
        assert "text" in prompt.lower()
        assert "subject" in prompt.lower()
        assert "style" in prompt.lower()
