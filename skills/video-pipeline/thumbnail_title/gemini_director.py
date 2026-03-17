"""Gemini Creative Director — analyzes 3 draft thumbnails and creates optimal #4.

Receives all 3 rendered thumbnail images via Gemini Vision, plus the full video
context (title, research payload, script, CTR history), and synthesizes the best
elements into one optimal Nano Banana Pro prompt.

This is the key differentiator: Gemini sees the actual rendered images AND has the
full script/research context, so it can judge what works visually AND what best
captures the story's conflict.

Non-blocking: if Gemini fails, the 3 Claude thumbnails still complete.
"""

import json
from typing import Optional

from json_utils import parse_json_response


async def run_gemini_director(
    gemini_client,
    image_client,
    v1_image_urls: list[str],
    video_title: str,
    thumbnail_text: str,
    research_payload: dict,
    script_text: str,
    framework_angle: str,
    channel_ctr_history: list[dict],
    palette: str,
) -> Optional[dict]:
    """Gemini analyzes 3 draft thumbnails + full context, generates optimal #4.

    Args:
        gemini_client: Initialized GeminiClient instance.
        image_client: Initialized ImageClient for generating thumbnail #4.
        v1_image_urls: 3 rendered thumbnail URLs from Claude-prompted variants.
        video_title: The video title.
        thumbnail_text: The yin-yang overlay text (line_1 + line_2).
        research_payload: Full research payload dict from Airtable.
        script_text: Full concatenated script text (all acts).
        framework_angle: e.g. "Machiavelli", "Game Theory".
        channel_ctr_history: Recent video CTR data (list of dicts).
        palette: Detected palette key (middle_east, finance, etc.).

    Returns:
        Dict with v4_url, analysis, visual_metaphor, reasoning, prompt.
        None if Gemini fails or no images could be fetched.
    """
    gemini_client._require_api_key()

    # Step 1: Download all 3 images as base64
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

    # Step 2: Build the context sections
    # Parse thumbnail text into line_1/line_2
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

    # Step 3: Build the Gemini prompt
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
4. Synthesize the best elements into ONE optimal thumbnail prompt

Write a Nano Banana Pro image generation prompt (80-150 words) that \
produces this optimal thumbnail. The prompt MUST include:
- The EXACT overlay text: line 1 = '{line_1}', line 2 = '{line_2}'
- Text: yellow (#FFD700), bold block capitals, thick black outline, \
heavy drop shadow, 60-70% of frame width
- A SPECIFIC visual metaphor with named objects and relationships \
(e.g., "Russian nesting doll shaped like an open bear trap \
containing a burlap money sack labeled CASH $$$, realistic hand \
pulling a rope attached to the trap mechanism")
- Color palette: 3-4 colors max from {palette}
- Bright editorial illustration style, 16:9, 1280x720
- NO dark/cinematic/photorealistic language

Return JSON:
{{
    "analysis": "What you took from each of the {len(image_parts)} drafts (2-3 sentences)",
    "visual_metaphor": "The core metaphor in 1 sentence",
    "prompt": "The full Nano Banana Pro generation prompt (80-150 words)",
    "reasoning": "Why this will outperform the {len(image_parts)} drafts (1-2 sentences)"
}}"""

    # Step 4: Assemble the Gemini API call with vision + text
    import httpx

    url = f"{gemini_client.BASE_URL}/models/gemini-2.0-flash:generateContent"
    params = {"key": gemini_client.api_key}

    # Build parts: text prompt first, then all images
    parts = [{"text": prompt_text}] + image_parts

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": 0.7,  # Higher creativity for thumbnails
            "maxOutputTokens": 2048,
            "responseMimeType": "application/json",
        },
    }

    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await client.post(url, params=params, json=payload)
        response.raise_for_status()

    data = response.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]

    # Step 5: Parse the response
    result = parse_json_response(text, default=None)
    if not result or "prompt" not in result:
        print(f"    Gemini director returned unparseable response")
        return None

    gemini_prompt = result["prompt"]
    print(f"    Gemini director prompt: {gemini_prompt[:100]}...")

    # Step 6: Generate thumbnail #4 with Nano Banana Pro
    v4_urls = await image_client.generate_thumbnail(gemini_prompt)
    if not v4_urls:
        print(f"    Gemini-directed thumbnail generation failed")
        return None

    v4_url = v4_urls[0]
    print(f"    Gemini-directed thumbnail generated: {v4_url[:60]}...")

    return {
        "v4_url": v4_url,
        "analysis": result.get("analysis", ""),
        "visual_metaphor": result.get("visual_metaphor", ""),
        "reasoning": result.get("reasoning", ""),
        "prompt": gemini_prompt,
    }
