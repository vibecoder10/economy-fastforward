"""Gemini Vision thumbnail analysis — extracts visual DNA from competitor thumbnails.

Downloads the thumbnail image and uses Gemini to analyze:
- Face presence and emotion
- Text overlay content and style
- Color palette and composition
- Visual complexity and layout pattern

Cost: ~$0.005 per thumbnail (Gemini Flash vision).
"""

import base64
import json
import httpx
import logging
from typing import Optional

logger = logging.getLogger("storyengine")

GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

THUMBNAIL_ANALYSIS_PROMPT = """Analyze this YouTube video thumbnail and extract structured visual intelligence. Return ONLY valid JSON.

Video title for context: {title}

Extract this JSON structure:
{{
  "face_present": true or false,
  "face_count": 0,
  "face_emotion": "shock | anger | curiosity | fear | surprise | neutral | smirk | concern | none",
  "face_prominence": "dominant | secondary | background | none",
  "text_overlay": {{
    "present": true or false,
    "text": "exact text visible on thumbnail",
    "word_count": 0,
    "font_size": "large | medium | small | none",
    "text_color": "primary color of text",
    "text_position": "top | center | bottom | left | right | overlay_on_face"
  }},
  "composition": {{
    "layout": "face_closeup | face_with_text | split_screen | before_after | single_subject | collage | data_chart | scenic | object_focus",
    "visual_complexity": "minimal | clean | moderate | busy | chaotic",
    "depth_of_field": "shallow | medium | deep",
    "subject_position": "center | rule_of_thirds_left | rule_of_thirds_right | full_frame"
  }},
  "colors": {{
    "dominant_color": "the primary color",
    "secondary_color": "the secondary color",
    "palette": ["top 3-4 colors"],
    "contrast_level": "low | medium | high | extreme",
    "saturation": "muted | natural | vivid | oversaturated",
    "mood": "dark | neutral | bright | neon"
  }},
  "brand_elements": {{
    "has_logo": true or false,
    "has_border": true or false,
    "has_arrow_or_circle": true or false,
    "has_emoji_or_icon": true or false
  }},
  "clickbait_signals": {{
    "red_circle_arrow": true or false,
    "exaggerated_expression": true or false,
    "before_after": true or false,
    "money_or_numbers": true or false,
    "celebrity_or_known_face": true or false
  }},
  "overall_style": "professional | editorial | vlog_style | news | documentary | sensational | minimalist | cinematic"
}}"""


async def _download_thumbnail(url: str) -> Optional[bytes]:
    """Download thumbnail image bytes from URL."""
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "image" not in content_type and len(response.content) < 1000:
                return None
            return response.content
    except Exception as e:
        logger.warning("[Thumbnail] Download failed for %s: %s", url[:80], e)
        return None


async def analyze_thumbnail(
    thumbnail_url: str,
    title: str,
    api_key: str,
) -> Optional[dict]:
    """Analyze a thumbnail image using Gemini Vision.

    Returns structured thumbnail DNA dict, or None if analysis fails.
    """
    # Download the image
    image_bytes = await _download_thumbnail(thumbnail_url)
    if not image_bytes:
        return None

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    # Determine MIME type from URL or default to jpeg
    mime_type = "image/jpeg"
    if ".png" in thumbnail_url.lower():
        mime_type = "image/png"
    elif ".webp" in thumbnail_url.lower():
        mime_type = "image/webp"

    prompt = THUMBNAIL_ANALYSIS_PROMPT.format(title=title or "Unknown")

    url = GEMINI_API_URL.format(model=GEMINI_MODEL)
    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {
                    "inline_data": {
                        "mime_type": mime_type,
                        "data": image_b64,
                    }
                },
            ]
        }],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 1024,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{url}?key={api_key}",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        # Extract text from Gemini response
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()

        # Parse JSON (handle markdown code blocks)
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        return json.loads(text)

    except Exception as e:
        logger.error("[Thumbnail] Gemini analysis failed: %s", e)
        return None
