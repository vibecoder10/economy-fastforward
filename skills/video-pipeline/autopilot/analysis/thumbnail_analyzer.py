"""Analyze competitor thumbnails using Claude vision."""

import json
import base64
import httpx
from typing import Optional
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential


class ThumbnailAnalysis(BaseModel):
    """Extracted thumbnail elements."""
    colors: dict = {}  # background, text, accents
    composition: str = ""  # face_left_text_right, centered, etc.
    text: dict = {}  # lines, size_pct, style
    subject: dict = {}  # face, expression, type
    style: str = ""  # editorial illustration, photorealistic, etc.
    confidence: float = 0.0  # 0-1

    model_config = {"extra": "allow"}


class ThumbnailAnalyzer:
    """Analyze thumbnails using Claude vision."""

    VISION_PROMPT = '''Analyze this YouTube thumbnail and extract the following elements.
Be specific and precise in your descriptions.

1. **Colors**: What are the dominant colors?
   - Background color/gradient
   - Text color and outline
   - Accent colors

2. **Composition**: Where are elements positioned?
   - Subject position (left, right, center)
   - Text position (left, right, center)
   - Use format like "face_left_text_right" or "centered_subject"

3. **Text**: Describe the text styling
   - Number of lines (1, 2, 3)
   - Approximate percentage of frame width (e.g., 65)
   - Style (bold, caps, outline, shadow)

4. **Subject**: What is the main subject?
   - Is there a face? (true/false)
   - Expression if face present (stern, smiling, shocked)
   - Type of subject (leader portrait, map, chart, object)

5. **Style**: Overall visual style
   - Editorial illustration, photorealistic, minimalist, etc.

Return ONLY valid JSON in this exact format:
{
  "colors": {"background": "...", "text": "...", "accents": "..."},
  "composition": "...",
  "text": {"lines": N, "size_pct": N, "style": "..."},
  "subject": {"face": true/false, "expression": "...", "type": "..."},
  "style": "...",
  "confidence": 0.0-1.0
}

Set confidence based on image clarity and how certain you are about the analysis.'''

    def __init__(self, anthropic_client=None):
        """Initialize analyzer.

        Args:
            anthropic_client: Anthropic client instance. If None, will import from shared.clients.
        """
        self.client = anthropic_client

    def _get_client(self):
        """Get or create Anthropic client."""
        if self.client is None:
            import anthropic
            self.client = anthropic.Anthropic()
        return self.client

    @staticmethod
    def get_thumbnail_url(video_id: str, quality: str = "maxres") -> str:
        """Get YouTube thumbnail URL for a video ID.

        Args:
            video_id: YouTube video ID
            quality: maxres, high, medium, default

        Returns:
            Thumbnail URL
        """
        quality_map = {
            "maxres": "maxresdefault",
            "high": "hqdefault",
            "medium": "mqdefault",
            "default": "default"
        }
        quality_code = quality_map.get(quality, "maxresdefault")
        return f"https://img.youtube.com/vi/{video_id}/{quality_code}.jpg"

    async def _download_image(self, url: str) -> Optional[bytes]:
        """Download image from URL.

        Args:
            url: Image URL

        Returns:
            Image bytes or None if failed
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    return response.content
                # Try fallback to hqdefault if maxres fails
                if "maxresdefault" in url:
                    fallback_url = url.replace("maxresdefault", "hqdefault")
                    response = await client.get(fallback_url)
                    if response.status_code == 200:
                        return response.content
                return None
        except Exception as e:
            print(f"Error downloading image: {e}")
            return None

    def _parse_response(self, response_text: str) -> Optional[ThumbnailAnalysis]:
        """Parse Claude response into ThumbnailAnalysis.

        Args:
            response_text: Raw text from Claude

        Returns:
            ThumbnailAnalysis or None if parsing fails
        """
        try:
            # Try direct JSON parse
            data = json.loads(response_text)
            return ThumbnailAnalysis(**data)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code block
            import re
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
            if json_match:
                try:
                    data = json.loads(json_match.group(1))
                    return ThumbnailAnalysis(**data)
                except:
                    pass
            # Try to find raw JSON object
            json_match = re.search(r'\{[^{}]*"colors"[^{}]*\}', response_text, re.DOTALL)
            if json_match:
                try:
                    data = json.loads(json_match.group(0))
                    return ThumbnailAnalysis(**data)
                except:
                    pass
        except Exception as e:
            print(f"Error parsing vision response: {e}")

        return None

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def analyze(self, image_url: str) -> Optional[ThumbnailAnalysis]:
        """Analyze a thumbnail image.

        Args:
            image_url: URL to the thumbnail image

        Returns:
            ThumbnailAnalysis or None if analysis fails
        """
        # Download image
        image_bytes = await self._download_image(image_url)
        if image_bytes is None:
            print(f"Failed to download image: {image_url}")
            return None

        # Encode as base64
        image_b64 = base64.b64encode(image_bytes).decode('utf-8')

        # Send to Claude vision
        try:
            client = self._get_client()
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/jpeg",
                                    "data": image_b64
                                }
                            },
                            {
                                "type": "text",
                                "text": self.VISION_PROMPT
                            }
                        ]
                    }
                ]
            )

            # Parse response
            response_text = response.content[0].text
            analysis = self._parse_response(response_text)

            if analysis and analysis.confidence < 0.6:
                print(f"Low confidence analysis ({analysis.confidence}), proceeding with partial data")

            return analysis

        except Exception as e:
            print(f"Vision analysis failed: {e}")
            raise  # Let tenacity handle retry

    async def analyze_from_video_id(self, video_id: str) -> Optional[ThumbnailAnalysis]:
        """Analyze thumbnail for a YouTube video ID.

        Args:
            video_id: YouTube video ID

        Returns:
            ThumbnailAnalysis or None if analysis fails
        """
        url = self.get_thumbnail_url(video_id)
        return await self.analyze(url)
