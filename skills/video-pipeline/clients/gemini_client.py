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
        """
        spec = {
            "composition": "",
            "dominant_colors": [],
            "text_elements": "",
            "focal_point": "",
            "mood": "",
            "key_objects": [],
            "style_notes": "",
            "background": "",
            "suggested_adaptations": "",
        }

        # Try to find quoted values after field names
        field_patterns = {
            "composition": r'"?composition"?\s*[:=]\s*"([^"]+)"',
            "text_elements": r'"?text_elements"?\s*[:=]\s*"([^"]+)"',
            "focal_point": r'"?focal_point"?\s*[:=]\s*"([^"]+)"',
            "mood": r'"?mood"?\s*[:=]\s*"([^"]+)"',
            "style_notes": r'"?style_notes"?\s*[:=]\s*"([^"]+)"',
            "background": r'"?background"?\s*[:=]\s*"([^"]+)"',
            "suggested_adaptations": r'"?suggested_adaptations"?\s*[:=]\s*"([^"]+)"',
        }

        for field, pattern in field_patterns.items():
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                spec[field] = match.group(1).strip()[:500]  # Cap at 500 chars

        # Extract arrays
        colors_match = re.search(
            r'"?dominant_colors"?\s*[:=]\s*\[([^\]]+)\]', text, re.IGNORECASE
        )
        if colors_match:
            colors_str = colors_match.group(1)
            colors = re.findall(r'"([^"]+)"', colors_str)
            spec["dominant_colors"] = colors[:10]  # Cap at 10 colors

        objects_match = re.search(
            r'"?key_objects"?\s*[:=]\s*\[([^\]]+)\]', text, re.IGNORECASE
        )
        if objects_match:
            objects_str = objects_match.group(1)
            objects = re.findall(r'"([^"]+)"', objects_str)
            spec["key_objects"] = objects[:10]  # Cap at 10 objects

        # If we got nothing, create a basic spec from the raw text summary
        if not any(
            [
                spec["composition"],
                spec["mood"],
                spec["focal_point"],
                spec["dominant_colors"],
            ]
        ):
            # Use the raw text as a general description
            spec["composition"] = f"Reference thumbnail for: {video_title}"
            spec["mood"] = "dramatic"
            spec["dominant_colors"] = ["dark", "accent color"]
            spec["focal_point"] = "center"
            spec["suggested_adaptations"] = text[:1000] if text else "Match reference style"

        return spec

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
        self._require_api_key()

        # Simplified prompt that's less likely to produce parsing issues
        user_prompt = f"""Analyze this YouTube thumbnail image for a video titled: "{video_title}"

Describe the thumbnail in this exact JSON format. Keep each field value SHORT (under 100 characters):

{{
  "composition": "layout description",
  "dominant_colors": ["color1", "color2", "color3"],
  "text_elements": "text style and placement",
  "focal_point": "what draws attention",
  "mood": "emotional tone",
  "key_objects": ["object1", "object2", "object3"],
  "style_notes": "artistic style",
  "background": "background description",
  "suggested_adaptations": "how to adapt for new topic"
}}

IMPORTANT: Return ONLY the JSON object, no other text. Keep values short and simple."""

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
                print(f"  Gemini analysis: {result.get('mood', 'N/A')} mood, {len(result.get('key_objects', []))} key objects")
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
        """Return a basic fallback spec when Gemini fails."""
        return {
            "composition": f"Thumbnail for: {video_title}",
            "dominant_colors": ["dark blue", "orange accent", "white text"],
            "text_elements": "Bold title text with high contrast",
            "focal_point": "Center with dramatic imagery",
            "mood": "dramatic and urgent",
            "key_objects": ["text overlay", "symbolic imagery"],
            "style_notes": "High contrast, bold colors, clean composition",
            "background": "Dark gradient or dramatic scene",
            "suggested_adaptations": "Use bold text, dramatic lighting, and a clear focal point",
        }

    async def _fetch_image_base64(self, url: str) -> str:
        """Download an image and return its base64-encoded content."""
        import base64

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()

        return base64.b64encode(response.content).decode("utf-8")
