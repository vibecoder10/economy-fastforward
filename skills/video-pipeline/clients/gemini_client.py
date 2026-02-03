"""Google Gemini API client for image analysis."""

import os
import httpx
import base64
from typing import Optional
import json


class GeminiClient:
    """Client for Google Gemini API image analysis."""

    API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GOOGLE_GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GOOGLE_GEMINI_API_KEY not found in environment")

    async def analyze_reference_thumbnail(
        self,
        image_url: str,
        video_title: str,
        video_summary: str,
    ) -> dict:
        """Analyze a reference thumbnail and extract THUMBNAIL_SPEC JSON.

        Args:
            image_url: URL of the reference thumbnail image
            video_title: Title of the new video
            video_summary: Summary/description of the new video idea

        Returns:
            THUMBNAIL_SPEC dict with style analysis
        """
        prompt = f"""You are a universal YouTube thumbnail reverse-engineer.
You will receive:
- A reference thumbnail image to model (style + layout)
- A NEW video title and NEW video idea
You must output ONLY valid JSON (no markdown, no commentary).
Inputs:
NEW_VIDEO_TITLE: {video_title}
NEW_VIDEO_IDEA: {video_summary}
GOAL:
Extract a strict THUMBNAIL_SPEC from the reference image so another model can recreate a new thumbnail for the NEW video, matching the reference style and layout.
RULES:
- Do NOT impose any fixed house style. The reference image is the source of truth for style.
- Detect whether the reference has text. If no text exists, output text_blocks as an empty array and do not instruct adding text later.
- If text exists, replicate its structure: number of blocks, placement, hierarchy, casing style, punctuation style, color, outline, shadow, and approximate word counts.
- Generate NEW on-image text that fits the reference text style AND fits the NEW video title/idea. Do NOT copy the reference's exact words.
- Capture composition as zones with relative positions (top-left, top-right, left third, right third) and subject scale (small/medium/large).
- Capture palette as 3-6 dominant colors with approximate names (navy, yellow, white, etc).
- Capture rendering style constraints: flat vs painterly, outline thickness, shading intensity, background simplicity, effects like glow/motion lines.
OUTPUT JSON SCHEMA (must follow):
{{
  "has_text": boolean,
  "text_blocks": [
    {{
      "id": "A",
      "text": "STRING",
      "case_style": "ALL_CAPS | Title_Case | mixed",
      "tone": "playful | serious | urgent | sarcastic | clinical",
      "font_vibe": "blocky | rounded | condensed | handwritten | serif",
      "fill_color": "color name",
      "outline": {{ "enabled": boolean, "color": "color name", "thickness": "none|thin|medium|thick" }},
      "shadow": {{ "enabled": boolean, "style": "none|soft|hard", "direction": "down-right|down|down-left|none" }},
      "position": "top-left | top-right | bottom-left | bottom-right | center-top | center-bottom",
      "size": "small | medium | large | huge",
      "max_words": integer
    }}
  ],
  "style_fingerprint": {{
    "render_style": "flat_cartoon | vector_like | cel_shaded | painterly_comic | 3dish",
    "outlines": "none | thin | medium | thick_black",
    "shading": "none | minimal | soft_gradient | heavy_render",
    "background": "solid | simple_gradient | detailed_scene",
    "effects": ["none" or list like "glow","motion_lines","arrows","spark_particles","lightning"],
    "palette": ["color1","color2","color3","color4"]
  }},
  "composition": {{
    "layout": "left_subject_right_object | right_subject_left_object | centered_subject | split_diagonal | other",
    "camera": "wide | medium | closeup",
    "subject_scale": "small | medium | large",
    "negative_space": ["areas that must stay clean, e.g. top-left behind text"]
  }},
  "scene_roles_for_new_video": {{
    "character_role": "what person/character should represent (emotion + pose)",
    "main_object_role": "main symbol/object for the NEW video (single dominant object)",
    "action_role": "what is happening (arrow, motion, impact, transformation)",
    "supporting_icons": ["0-3 optional small icons if the reference uses them"]
  }}
}}"""

        # Download and encode the image
        image_data = await self._fetch_image_as_base64(image_url)

        # Build request payload
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": image_data
                            }
                        },
                        {
                            "text": prompt
                        }
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 4096,
            }
        }

        # Make API request
        url = f"{self.API_URL}?key={self.api_key}"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json=payload,
                timeout=60.0,
            )
            response.raise_for_status()
            result = response.json()

        # Extract text from response
        text = result["candidates"][0]["content"]["parts"][0]["text"]

        # Parse JSON from response (handle potential markdown wrapping)
        clean_text = text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_text)

    async def _fetch_image_as_base64(self, image_url: str) -> str:
        """Fetch an image from URL and return as base64 string."""
        async with httpx.AsyncClient() as client:
            response = await client.get(image_url, timeout=30.0)
            response.raise_for_status()
            image_bytes = response.content

        return base64.b64encode(image_bytes).decode("utf-8")
