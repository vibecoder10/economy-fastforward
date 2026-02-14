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
        # Don't raise here - allow lazy initialization for pipelines that don't need Gemini
        if not self.api_key:
            print("  GEMINI_API_KEY not found - thumbnail analysis will be skipped")

    def _require_api_key(self):
        """Raise error if API key is missing (called before actual API use)."""
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not found in environment")

    def _parse_json_response(self, text: str) -> Optional[dict]:
        """Robustly parse JSON from Gemini response.

        Handles various formatting issues that Gemini might produce.
        """
        # Step 1: Remove markdown code blocks
        clean = text.replace("```json", "").replace("```", "").strip()

        # Step 2: Try direct parse
        try:
            return json.loads(clean)
        except json.JSONDecodeError:
            pass

        # Step 3: Try to extract JSON object from the text
        # Find the first { and last } to extract just the JSON portion
        start_idx = clean.find("{")
        end_idx = clean.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            json_portion = clean[start_idx : end_idx + 1]
            try:
                return json.loads(json_portion)
            except json.JSONDecodeError:
                pass

            # Step 4: Try fixing common issues
            fixed = json_portion

            # Fix unescaped quotes inside strings (common issue)
            # This is tricky - we need to be careful not to break valid JSON

            # Remove trailing commas before } or ]
            fixed = re.sub(r",\s*([}\]])", r"\1", fixed)

            # Try parsing again
            try:
                return json.loads(fixed)
            except json.JSONDecodeError:
                pass

        return None

    def _extract_fields_from_text(self, text: str, video_title: str) -> dict:
        """Extract thumbnail spec fields from raw text when JSON parsing fails.

        Uses regex patterns to find key information in the response.
        Falls back to house style defaults if extraction fails.
        """
        # House style defaults - these produce on-brand thumbnails
        spec = {
            "composition_layout": "left-right split, 60-40",
            "figure_pose": "shocked expression, reaching forward",
            "figure_clothing": "business suit with loosened tie",
            "background_element": "crumbling structure",
            "background_mood_color": "deep navy to charcoal gradient",
            "payoff_element": "glowing golden protective dome",
            "payoff_glow_color": "intense golden glow",
            "separator_type": "diagonal divide with red arrow",
            "color_contrast": "dark navy vs golden glow",
            "text_placement": "upper 20% of frame, centered",
            "text_style": "bold white condensed all caps with black outline",
            "overall_brightness": "bright",
        }

        # Try to extract from text, fall back to house style defaults above
        field_patterns = {
            "composition_layout": r'"?composition_layout"?\s*[:=]\s*"([^"]+)"',
            "figure_pose": r'"?figure_pose"?\s*[:=]\s*"([^"]+)"',
            "figure_clothing": r'"?figure_clothing"?\s*[:=]\s*"([^"]+)"',
            "background_element": r'"?background_element"?\s*[:=]\s*"([^"]+)"',
            "background_mood_color": r'"?background_mood_color"?\s*[:=]\s*"([^"]+)"',
            "payoff_element": r'"?payoff_element"?\s*[:=]\s*"([^"]+)"',
            "payoff_glow_color": r'"?payoff_glow_color"?\s*[:=]\s*"([^"]+)"',
            "separator_type": r'"?separator_type"?\s*[:=]\s*"([^"]+)"',
            "color_contrast": r'"?color_contrast"?\s*[:=]\s*"([^"]+)"',
            "text_placement": r'"?text_placement"?\s*[:=]\s*"([^"]+)"',
            "text_style": r'"?text_style"?\s*[:=]\s*"([^"]+)"',
            "overall_brightness": r'"?overall_brightness"?\s*[:=]\s*"([^"]+)"',
        }

        for field, pattern in field_patterns.items():
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                spec[field] = match.group(1).strip()[:200]

        return spec

    async def generate_thumbnail_spec(
        self,
        reference_image_url: str,
        video_title: str,
        video_summary: str = "",
    ) -> dict:
        """Analyze a reference thumbnail and produce a structured spec.

        The spec captures STYLE elements (composition, color, pose) that can be
        adapted to new topics while maintaining the Economy FastForward house style.

        Args:
            reference_image_url: URL of the reference thumbnail image
            video_title: Title of the video (for context)
            video_summary: Optional summary/description of the video

        Returns:
            Dict with structured thumbnail spec (style elements only, not topic/text)
        """
        self._require_api_key()

        # Updated prompt for v2 - focus on STYLE extraction, not content
        user_prompt = f"""Analyze this YouTube thumbnail image for a finance/economics channel.

Extract ONLY the visual style elements (not the topic or text content).

Output this exact JSON format. Keep each value under 80 characters:

{{
  "composition_layout": "spatial arrangement (e.g., left-right split, centered, diagonal)",
  "figure_pose": "body language and visible emotion of the human figure",
  "figure_clothing": "what the figure is wearing",
  "background_element": "the ONE main background object or scene element",
  "background_mood_color": "dominant background color or gradient",
  "payoff_element": "what is on the bright/answer side of the image",
  "payoff_glow_color": "color of the glow or brightness on the payoff side",
  "separator_type": "how the two sides are divided (arrow, line, contrast shift)",
  "color_contrast": "the main color tension (e.g., dark navy vs golden glow)",
  "text_placement": "where text sits relative to image elements",
  "text_style": "font weight, color, outline treatment observed",
  "overall_brightness": "bright or medium or dark overall luminance"
}}

IMPORTANT:
- Return ONLY the JSON object, no other text.
- Describe STYLE, not content. "man in suit reaching" not "man reaching for gold"
- Do NOT include the reference's specific text or topic in any field."""

        url = f"{self.BASE_URL}/models/gemini-2.0-flash:generateContent"
        params = {"key": self.api_key}

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": user_prompt},
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
                "temperature": 0.3,  # Lower temperature for more structured output
                "maxOutputTokens": 1024,  # Shorter response = less likely to break
                "responseMimeType": "application/json",  # Request JSON response
            },
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, params=params, json=payload)
                response.raise_for_status()

            data = response.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]

            # Try to parse the JSON response
            result = self._parse_json_response(text)
            if result:
                print(f"  Gemini analysis: {result.get('composition_layout', 'N/A')} layout, {result.get('overall_brightness', 'N/A')} brightness")
                return result

            # If parsing failed, extract what we can from the raw text
            print(f"  JSON parsing failed, extracting fields from text...")
            return self._extract_fields_from_text(text, video_title)

        except httpx.HTTPStatusError as e:
            print(f"  Gemini API error: {e.response.status_code}")
            # Return a basic fallback
            return self._get_fallback_spec(video_title)
        except Exception as e:
            print(f"  Gemini error: {e}")
            return self._get_fallback_spec(video_title)

    def _get_fallback_spec(self, video_title: str) -> dict:
        """Return house style defaults when Gemini fails."""
        return {
            "composition_layout": "left-right split, 60-40",
            "figure_pose": "shocked expression, reaching forward",
            "figure_clothing": "business suit with loosened tie",
            "background_element": "crumbling structure",
            "background_mood_color": "deep navy to charcoal gradient",
            "payoff_element": "glowing golden protective dome",
            "payoff_glow_color": "intense golden glow",
            "separator_type": "diagonal divide with red arrow",
            "color_contrast": "dark navy vs golden glow",
            "text_placement": "upper 20% of frame, centered",
            "text_style": "bold white condensed all caps with black outline",
            "overall_brightness": "bright",
        }

    async def _fetch_image_base64(self, url: str) -> str:
        """Download an image and return its base64-encoded content."""
        import base64

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()

        return base64.b64encode(response.content).decode("utf-8")
