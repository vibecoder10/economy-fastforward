"""Google Gemini API client for image analysis."""

import os
import base64
import json
import httpx
from typing import Optional


class GeminiClient:
    """Client for Google Gemini API (REST, via httpx)."""

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
    DEFAULT_MODEL = "gemini-2.0-flash"

    THUMBNAIL_SPEC_SYSTEM_PROMPT = """You are a universal YouTube thumbnail reverse-engineer.
You will receive:
- A reference thumbnail image to model (style + layout)
- A NEW video title and NEW video idea

You must output ONLY valid JSON (no markdown, no commentary).

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
{
  "has_text": boolean,
  "text_blocks": [
    {
      "id": "A",
      "text": "STRING",
      "case_style": "ALL_CAPS | Title_Case | mixed",
      "tone": "playful | serious | urgent | sarcastic | clinical",
      "font_vibe": "blocky | rounded | condensed | handwritten | serif",
      "fill_color": "color name",
      "outline": { "enabled": boolean, "color": "color name", "thickness": "none|thin|medium|thick" },
      "shadow": { "enabled": boolean, "style": "none|soft|hard", "direction": "down-right|down|down-left|none" },
      "position": "top-left | top-right | bottom-left | bottom-right | center-top | center-bottom",
      "size": "small | medium | large | huge",
      "max_words": integer
    }
  ],
  "style_fingerprint": {
    "render_style": "flat_cartoon | vector_like | cel_shaded | painterly_comic | 3dish",
    "outlines": "none | thin | medium | thick_black",
    "shading": "none | minimal | soft_gradient | heavy_render",
    "background": "solid | simple_gradient | detailed_scene",
    "effects": ["none or list like glow, motion_lines, arrows, spark_particles, lightning"],
    "palette": ["color1","color2","color3","color4"]
  },
  "composition": {
    "layout": "left_subject_right_object | right_subject_left_object | centered_subject | split_diagonal | other",
    "camera": "wide | medium | closeup",
    "subject_scale": "small | medium | large",
    "negative_space": ["areas that must stay clean, e.g. top-left behind text"]
  },
  "scene_roles_for_new_video": {
    "character_role": "what person/character should represent (emotion + pose)",
    "main_object_role": "main symbol/object for the NEW video (single dominant object)",
    "action_role": "what is happening (arrow, motion, impact, transformation)",
    "supporting_icons": ["0-3 optional small icons if the reference uses them"]
  }
}

IMPORTANT:
- text_blocks must match the reference structure. If the reference has 2 text blocks, output 2. If 1, output 1. If none, output [].
- Fill text_blocks[].text with NEW text based on NEW_VIDEO_TITLE and NEW_VIDEO_IDEA while matching the reference style constraints.
- Output ONLY the JSON object."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not found in environment")

    async def generate_thumbnail_spec(
        self,
        reference_image_url: str,
        video_title: str,
        video_summary: str,
    ) -> dict:
        """Analyze a reference thumbnail and produce a THUMBNAIL_SPEC JSON.

        Downloads the reference image, sends it to Gemini with the analysis
        prompt, and returns the parsed spec dict.

        Args:
            reference_image_url: URL of the reference thumbnail image
            video_title: Title of the NEW video
            video_summary: Summary / idea of the NEW video

        Returns:
            Parsed THUMBNAIL_SPEC dict
        """
        # Download the reference image
        async with httpx.AsyncClient() as client:
            img_response = await client.get(
                reference_image_url, timeout=30.0, follow_redirects=True,
            )
            img_response.raise_for_status()

        image_bytes = img_response.content
        content_type = img_response.headers.get("content-type", "image/png")
        # Normalise mime type
        if "jpeg" in content_type or "jpg" in content_type:
            mime_type = "image/jpeg"
        elif "webp" in content_type:
            mime_type = "image/webp"
        else:
            mime_type = "image/png"

        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        user_prompt = (
            f"NEW_VIDEO_TITLE: {video_title}\n"
            f"NEW_VIDEO_IDEA: {video_summary}\n\n"
            "Analyze the attached reference thumbnail and output the THUMBNAIL_SPEC JSON."
        )

        # Build Gemini REST request
        url = f"{self.BASE_URL}/{self.DEFAULT_MODEL}:generateContent?key={self.api_key}"
        payload = {
            "systemInstruction": {
                "parts": [{"text": self.THUMBNAIL_SPEC_SYSTEM_PROMPT}],
            },
            "contents": [
                {
                    "parts": [
                        {"text": user_prompt},
                        {
                            "inlineData": {
                                "mimeType": mime_type,
                                "data": image_b64,
                            },
                        },
                    ],
                },
            ],
            "generationConfig": {
                "temperature": 0.4,
                "maxOutputTokens": 4096,
            },
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=60.0)
            response.raise_for_status()

        result = response.json()
        text = result["candidates"][0]["content"]["parts"][0]["text"]

        # Strip markdown fences if present
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]  # drop opening fence line
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()

        return json.loads(text)
