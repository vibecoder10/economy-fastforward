"""Google Gemini API client for vision-based thumbnail analysis."""

import os
import json
import re
from typing import Optional
import httpx


class GeminiClient:
    """Client for Google Gemini API (REST-based, no SDK dependency)."""

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not found in environment")

    async def generate_thumbnail_spec(
        self,
        reference_image_url: str,
        video_title: str,
        video_summary: str = "",
    ) -> dict:
        """Analyze a reference thumbnail image and produce a structured spec.

        Uses Gemini's vision capabilities to break down the reference
        thumbnail into composition, colors, text placement, mood, etc.

        Args:
            reference_image_url: URL of the reference thumbnail image
            video_title: Title of the video
            video_summary: Optional summary/description of the video

        Returns:
            Dict with structured thumbnail spec (composition, colors, text, mood, etc.)
        """
        system_prompt = (
            "You are an expert YouTube thumbnail analyst. "
            "Analyze the provided reference thumbnail image and extract a detailed spec."
        )

        user_prompt = f"""Analyze this reference thumbnail for a video titled: "{video_title}"

Video context: {video_summary or 'N/A'}

Break down the thumbnail into a structured JSON spec with these fields:

{{
  "composition": "Describe the layout and arrangement of elements",
  "dominant_colors": ["list", "of", "main", "colors"],
  "text_elements": "Describe any text overlays, their style, size, position",
  "focal_point": "What draws the eye first",
  "mood": "Overall emotional tone (e.g. dramatic, urgent, mysterious)",
  "key_objects": ["list", "of", "main", "visual", "elements"],
  "style_notes": "Any notable artistic style choices (lighting, contrast, filters)",
  "background": "Describe the background",
  "suggested_adaptations": "How to adapt this style for the new video topic"
}}

Return ONLY valid JSON, no markdown formatting."""

        url = f"{self.BASE_URL}/models/gemini-2.5-flash:generateContent"
        params = {"key": self.api_key}

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": f"{system_prompt}\n\n{user_prompt}"},
                        {
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": await self._fetch_image_base64(reference_image_url),
                            }
                        },
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 8192,
            },
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, params=params, json=payload)
            response.raise_for_status()

        data = response.json()
        response_text = data["candidates"][0]["content"]["parts"][0]["text"]

        # Clean up response - remove markdown code blocks if present
        clean = response_text.strip()
        if clean.startswith("```json"):
            clean = clean[7:]
        if clean.startswith("```"):
            clean = clean[3:]
        if clean.endswith("```"):
            clean = clean[:-3]
        clean = clean.strip()

        # Try to extract JSON object even if there's extra text
        json_match = re.search(r'\{[\s\S]*\}', clean)
        if json_match:
            clean = json_match.group(0)

        try:
            return json.loads(clean)
        except json.JSONDecodeError as e:
            print(f"  ⚠️ Gemini returned invalid JSON: {e}")
            print(f"  Raw response: {response_text[:500]}...")
            # Return minimal spec so pipeline can continue with fallback
            return {
                "error": "Invalid JSON from Gemini",
                "raw_response": response_text[:1000],
            }

    async def _fetch_image_base64(self, url: str) -> str:
        """Download an image and return its base64-encoded content."""
        import base64

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()

        return base64.b64encode(response.content).decode("utf-8")
