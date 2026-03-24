"""Gemini Creative Director — analyzes 3 draft thumbnails and generates optimal #4.

Uses gemini-3-pro-image-preview which supports both vision (analyzing the 3 drafts)
AND image generation in a single call. Gemini reasons through what works in each draft,
considers the full video context, then generates the optimal thumbnail directly —
no separate Nano Banana Pro render step needed.

Non-blocking: if Gemini fails, the 3 Claude thumbnails still complete.
"""

import base64
from typing import Optional

import httpx

from json_utils import parse_json_response


async def run_gemini_director(
    gemini_client,
    image_client,
    google_client,
    v1_image_urls: list[str],
    video_title: str,
    thumbnail_text: str,
    research_payload: dict,
    script_text: str,
    framework_angle: str,
    channel_ctr_history: list[dict],
    palette: str,
    drive_folder_id: Optional[str] = None,
) -> Optional[dict]:
    """Gemini analyzes 3 draft thumbnails + full context, generates optimal #4.

    Uses gemini-3-pro-image-preview with response_modalities=['TEXT', 'IMAGE']
    to analyze drafts and generate the final thumbnail in one call.

    Args:
        gemini_client: Initialized GeminiClient instance.
        image_client: Initialized ImageClient (unused — kept for signature compat).
        google_client: Initialized GoogleClient for uploading generated image.
        v1_image_urls: 3 rendered thumbnail URLs from Claude-prompted variants.
        video_title: The video title.
        thumbnail_text: The yin-yang overlay text (line_1 + line_2).
        research_payload: Full research payload dict from Airtable.
        script_text: Full concatenated script text (all acts).
        framework_angle: e.g. "Machiavelli", "Game Theory".
        channel_ctr_history: Recent video CTR data (list of dicts).
        palette: Detected palette key (middle_east, finance, etc.).
        drive_folder_id: Google Drive folder to upload the generated image.

    Returns:
        Dict with v4_url, analysis, visual_metaphor, reasoning.
        None if Gemini fails or no images could be fetched.
    """
    gemini_client._require_api_key()

    # Step 1: Download all 3 draft images as base64
    image_parts = []
    for i, url in enumerate(v1_image_urls):
        try:
            b64_data = await gemini_client._fetch_image_base64(url)
            image_parts.append({
                "inline_data": {
                    "mime_type": "image/png",
                    "data": b64_data,
                }
            })
            print(f"    Fetched draft thumbnail {i + 1} for Gemini analysis")
        except Exception as e:
            print(f"    Failed to fetch draft thumbnail {i + 1}: {e}")

    if not image_parts:
        print("    No draft thumbnails could be fetched — skipping Gemini director")
        return None

    # Step 2: Build context sections
    words = thumbnail_text.strip().upper().split()
    if len(words) <= 3:
        line_1 = thumbnail_text.strip().upper()
        line_2 = ""
    elif len(words) == 4:
        line_1 = " ".join(words[:2])
        line_2 = " ".join(words[2:])
    else:
        line_1 = " ".join(words[:3])
        line_2 = " ".join(words[3:])

    # Format CTR history
    if channel_ctr_history:
        ctr_lines = []
        for entry in channel_ctr_history[:5]:
            title = entry.get("title", "")
            ctr = entry.get("ctr", 0)
            views = entry.get("views", 0)
            thumb_text = entry.get("thumbnail_text", "")
            ctr_lines.append(f"- {title} | CTR: {ctr}% | Views: {views:,} | Thumb text: {thumb_text}")
        formatted_ctr = "\n".join(ctr_lines)
    else:
        formatted_ctr = "No CTR history available yet."

    # Extract key research fields (truncate for token budget)
    thesis = ""
    fact_sheet = ""
    narrative_arc = ""
    if isinstance(research_payload, dict):
        thesis = str(research_payload.get("thesis", ""))[:500]
        fact_sheet = str(research_payload.get("fact_sheet", ""))[:2000]
        narrative_arc = str(research_payload.get("narrative_arc", ""))[:1000]

    # Step 3: Build the prompt — ask Gemini to analyze AND generate
    prompt_text = f"""You are the creative director for a YouTube channel producing geopolitical \
and economic analysis videos. You are reviewing {len(image_parts)} thumbnail drafts and will \
create the definitive final version.

## VIDEO CONTEXT
Title: {video_title}
Thumbnail overlay text: {thumbnail_text}
Framework: {framework_angle}
Thesis: {thesis}
Key facts: {fact_sheet}
Narrative arc: {narrative_arc}

## FULL SCRIPT (abbreviated)
{script_text[:4000]}

## THUMBNAIL RULES (data-driven from channel performance)
- Bright editorial illustration, NOT photorealistic, NOT cinematic
- Text is the LARGEST element (60-70% of frame width)
- Yellow (#FFD700) bold block capitals with thick black outline, heavy drop shadow
- Maximum 3-4 dominant colors, no rainbow, no neon
- Must read at 160x90px (phone size in Suggested feed)
- One clear visual metaphor — not a collage of elements
- Personal threat framing outperforms neutral framing
- Simple recognizable backgrounds (maps, single symbols)
- Dark cinematic thumbnails get 0.7-1.9% CTR (BAD)
- Bright editorial illustrations get 4.2-7.4% CTR (GOOD)
- Thumbnail text and title must be yin-yang: title = intellectual HOW, \
thumbnail = emotional WHAT. Never repeat the same words.

## RECENT CHANNEL PERFORMANCE
{formatted_ctr}

## YOUR TASK
1. Analyze all {len(image_parts)} draft thumbnails (attached images)
2. For each: what works, what doesn't, what's too busy at phone size, \
which visual metaphor is strongest, what reads instantly
3. Consider the full script and research — what is THE single most \
compelling visual image that captures this story's conflict?
4. Generate the OPTIMAL thumbnail image that synthesizes the best elements

The generated thumbnail MUST have:
- The EXACT overlay text: line 1 = '{line_1}', line 2 = '{line_2}'
- Text: yellow (#FFD700), bold block capitals, thick black outline, \
heavy drop shadow, 60-70% of frame width
- A SPECIFIC visual metaphor with named objects and relationships
- Color palette: 3-4 colors max from {palette} palette
- Bright editorial illustration style
- NO dark/cinematic/photorealistic look

First write your analysis as text, then generate the optimal thumbnail image.

Format your text analysis as:
ANALYSIS: [What you took from each of the {len(image_parts)} drafts, 2-3 sentences]
METAPHOR: [The core visual metaphor in 1 sentence]
REASONING: [Why this will outperform the {len(image_parts)} drafts, 1-2 sentences]

Then generate the image."""

    # Step 4: Call gemini-3-pro-image-preview with vision input + image generation
    url = f"{gemini_client.BASE_URL}/models/gemini-3-pro-image-preview:generateContent"
    params = {"key": gemini_client.api_key}

    parts = [{"text": prompt_text}] + image_parts

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 4096,
            "response_modalities": ["TEXT", "IMAGE"],
            "image_config": {
                "aspect_ratio": "16:9",
                "image_size": "2K",
            },
        },
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, params=params, json=payload)
        response.raise_for_status()

    data = response.json()
    candidates = data.get("candidates", [])
    if not candidates:
        print("    Gemini returned no candidates")
        return None

    response_parts = candidates[0].get("content", {}).get("parts", [])

    # Step 5: Extract text analysis and generated image from response parts
    text_parts = []
    image_data = None
    image_mime = "image/png"

    for part in response_parts:
        if "text" in part:
            text_parts.append(part["text"])
        elif "inline_data" in part:
            image_data = part["inline_data"].get("data")
            image_mime = part["inline_data"].get("mime_type", "image/png")

    analysis_text = "\n".join(text_parts)

    if not image_data:
        print("    Gemini did not generate an image — falling back to prompt extraction")
        # Try to extract a prompt from the text and use Nano Banana Pro as fallback
        return await _fallback_to_nano_banana(
            image_client, analysis_text, line_1, line_2, palette
        )

    # Decode the generated image
    image_bytes = base64.b64decode(image_data)
    print(f"    Gemini generated thumbnail image ({len(image_bytes)} bytes)")

    # Step 6: Upload generated image to Google Drive
    ext = "png" if "png" in image_mime else "jpeg"
    slug = video_title.lower().replace(" ", "_").replace("'", "")[:50]
    filename = f"{slug}_thumbnail_gemini.{ext}"

    drive_result = google_client.upload_file(
        content=image_bytes,
        name=filename,
        folder_id=drive_folder_id or "",
        mime_type=image_mime,
    )
    file_id = drive_result.get("id", "")

    # Make it public so we get a usable direct URL
    v4_url = ""
    if file_id:
        try:
            v4_url = google_client.make_file_public(file_id)
            print(f"    Gemini thumbnail uploaded to Drive: {v4_url[:60]}...")
        except Exception as e:
            print(f"    Failed to make Gemini thumbnail public: {e}")
            # uc?id= format still works for public files in Slack image blocks
            v4_url = f"https://drive.google.com/uc?id={file_id}"

    if not v4_url:
        print("    Failed to upload Gemini-generated thumbnail to Drive")
        return None

    # Step 7: Parse the text analysis
    analysis = _extract_field(analysis_text, "ANALYSIS")
    metaphor = _extract_field(analysis_text, "METAPHOR")
    reasoning = _extract_field(analysis_text, "REASONING")

    return {
        "v4_url": v4_url,
        "v4_file_id": file_id,
        "analysis": analysis,
        "visual_metaphor": metaphor,
        "reasoning": reasoning,
        "prompt": "(generated directly by Gemini 3 Pro — no text prompt used)",
    }


def _extract_field(text: str, field_name: str) -> str:
    """Extract a labeled field from Gemini's text output.

    Looks for patterns like 'ANALYSIS: ...' up to the next label or end.
    """
    import re
    pattern = rf"{field_name}:\s*(.+?)(?=\n(?:ANALYSIS|METAPHOR|REASONING):|$)"
    match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


async def _fallback_to_nano_banana(
    image_client,
    analysis_text: str,
    line_1: str,
    line_2: str,
    palette: str,
) -> Optional[dict]:
    """Fallback: extract a prompt from Gemini's text and render via Nano Banana Pro.

    Used when Gemini returns text analysis but no generated image.
    """
    # Try to find anything that looks like a generation prompt
    prompt = None
    for marker in ["PROMPT:", "prompt:", "Generate:", "generate:"]:
        if marker in analysis_text:
            idx = analysis_text.index(marker) + len(marker)
            prompt = analysis_text[idx:idx + 500].strip().split("\n\n")[0].strip()
            break

    if not prompt:
        print("    Fallback: no prompt found in Gemini text output")
        return None

    print(f"    Fallback: using extracted prompt with Nano Banana Pro")
    v4_urls = await image_client.generate_thumbnail(prompt)
    if not v4_urls:
        print("    Fallback: Nano Banana Pro generation failed")
        return None

    analysis = _extract_field(analysis_text, "ANALYSIS")
    metaphor = _extract_field(analysis_text, "METAPHOR")
    reasoning = _extract_field(analysis_text, "REASONING")

    return {
        "v4_url": v4_urls[0],
        "analysis": analysis,
        "visual_metaphor": metaphor,
        "reasoning": reasoning,
        "prompt": prompt,
    }
