"""Anthropic Claude API client for script and prompt generation."""

import os
from anthropic import Anthropic
from typing import Optional, List, Dict, Tuple

from .style_engine import (
    # New holographic system
    ContentType,
    DisplayFormat,
    ColorMood,
    CONTENT_TYPE_CONFIG,
    CONTENT_TYPE_KEYWORDS,
    DISPLAY_FORMAT_CONFIG,
    CONTENT_FORMAT_AFFINITY,
    COLOR_MOOD_CONFIG,
    COLOR_MOOD_KEYWORDS,
    HOLOGRAPHIC_SUFFIX,
    PROMPT_MIN_WORDS,
    PROMPT_MAX_WORDS,
    EXAMPLE_PROMPTS,
    resolve_content_type,
    resolve_color_mood,
    resolve_display_format,
    # Legacy compatibility (animation pipeline)
    STYLE_ENGINE,
    STYLE_ENGINE_PREFIX,
    STYLE_ENGINE_SUFFIX,
    MATERIAL_VOCABULARY,
    TEXT_RULE_WITH_TEXT,
    TEXT_RULE_NO_TEXT,
    SceneType,
    CameraRole,
    SCENE_TYPE_CONFIG,
    get_documentary_pattern,
    get_scene_type_for_segment,
)

# Web search tool for real-time headline gathering and fact verification.
# Pass as tools=[WEB_SEARCH_TOOL] to generate() to enable web search.
WEB_SEARCH_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
    "max_uses": 5,
}

# Thumbnail System v2 - Locked House Style
ANTHROPIC_THUMBNAIL_SYSTEM_PROMPT = """You are the thumbnail prompt engineer for Economy FastForward, \
a finance/economics YouTube channel.

Your job: Generate a detailed image generation prompt for Nano Banana Pro that produces \
a click-worthy, on-brand thumbnail.

HOUSE STYLE (always enforce these rules):

COMPOSITION:
- Left 60% = THE TENSION (dramatic scene, emotional figure, the problem)
- Right 40% = THE PAYOFF (the answer, protection, opportunity — brightest element)
- Clean diagonal divide line or contrast shift between sides
- Bold red arrow pointing from tension to payoff

FIGURE:
- ONE central human figure in left 60%, comic/editorial illustration style
- Thick bold black outlines, expressive face readable at small size
- Upper body minimum, professional clothing (suit/tie)
- Body language matches the topic's emotion (shock, reaching, stumbling, pointing)

BACKGROUND:
- Maximum THREE elements total (one environmental, one scattered object, one atmospheric)
- ONE dominant mood color (deep navy, dark red, or dark green gradient)

PAYOFF:
- Glowing dome/shield/bubble OR upward growth element
- BRIGHTEST element in entire thumbnail
- Radiating golden or green light
- Contains clear visual symbols of the topic's "answer"

COLOR:
- 2+1 rule: one dark background color, one bright pop accent, white text
- Right side always brighter than left side

TEXT (critical — include in every prompt):
- Position: Upper 20% of frame, two lines stacked
- Line 1 (larger): The hook — year, number, or dramatic claim, max 5 words
- Line 2 (slightly smaller): The question or tension, max 5 words
- Style: Bold white condensed sans-serif, ALL CAPS, thick black outline stroke + drop shadow
- ONE word highlighted in bright red (the curiosity trigger word)
- Text must NOT overlap the figure's face or the payoff element

TECHNICAL:
- Thick black outlines on all figures and objects
- Flat cel-shaded coloring, high contrast, high saturation
- Bright overall luminance (dark thumbnails disappear on YouTube)
- 16:9 aspect ratio

WHEN A REFERENCE SPEC IS PROVIDED:
Incorporate specific style cues from the reference (pose, color choices, separator style) \
BUT always enforce the house style rules above. The house style overrides any reference \
element that conflicts with it.

WHEN NO REFERENCE SPEC IS PROVIDED:
Generate the thumbnail prompt purely from the house style rules and video topic. \
This is the normal operating mode. The house style is sufficient to produce on-brand thumbnails.

OUTPUT FORMAT:
Return ONLY the image generation prompt. No explanations, no JSON, no labels. \
The prompt should be 150-200 words and follow this structure:
1. Style declaration
2. Left tension scene (figure + background)
3. Right payoff scene (dome/element + contents)
4. Separator description
5. Text block (exact text, placement, styling, highlight word)
6. Technical style rules"""


class AnthropicClient:
    """Client for Anthropic Claude API."""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not found in environment")
        self.client = Anthropic(api_key=self.api_key)
    
    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        model: str = "claude-sonnet-4-5-20250929",
        max_tokens: int = 4096,
        temperature: float = 1.0,
        tools: list = None,
    ) -> str:
        """Generate a completion using Claude.

        Args:
            prompt: The user prompt
            system_prompt: System instructions
            model: Model to use (claude-sonnet-4-5-20250929, claude-opus-4-5-20251101)
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature
            tools: Optional list of tool definitions (e.g. [WEB_SEARCH_TOOL])

        Returns:
            The generated text response

        Raises:
            RuntimeError: If the API returns empty content on both
                          the initial call and the retry.
        """
        import asyncio as _asyncio

        messages = [{"role": "user", "content": prompt}]

        # Build kwargs - only include system if provided
        kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if tools:
            kwargs["tools"] = tools

        response = self.client.messages.create(**kwargs)

        text = self._extract_text(response)
        if text:
            return text

        # Empty content — retry once after a short delay
        print("    ⚠️ API returned empty content, retrying in 2s...")
        await _asyncio.sleep(2)
        response = self.client.messages.create(**kwargs)

        text = self._extract_text(response)
        if text:
            return text

        raise RuntimeError("Anthropic API returned empty content on both attempts")

    @staticmethod
    def _extract_text(response) -> str:
        """Extract text from a response that may contain mixed content blocks.

        When tools like web_search are enabled, the response contains
        tool_use and tool_result blocks alongside text blocks. This
        method extracts only the text.
        """
        if not response.content:
            return ""
        text_parts = []
        for block in response.content:
            if hasattr(block, "text"):
                text_parts.append(block.text)
        return "\n".join(text_parts)
    
    async def generate_beat_sheet(self, video_data: dict) -> dict:
        """Generate a 14-scene beat sheet for a video (legacy path).

        Uses the Script Architect prompt from the n8n workflow.
        For the unified pipeline, use brief_translator's scene expansion instead.
        """
        system_prompt = """You are a Master Storyteller and Narrative Architect.

Your task is to create a 14-scene Beat Sheet for documentary videos.
Target: 15-20 minutes (~2,800 words total, ~200 words per scene).

INSTRUCTIONS:
1. Analyze the input. Is it raw video DNA or a rejection?
2. Generate the beat sheet following this narrative arc:
   - INTRO (Scenes 1-3): Introduce the hook, the stakes, and the main question.
   - BUILD-UP (Scenes 4-11): Escalate tension. Reveal the Past Context and Modern Shift. Show cause-and-effect.
   - CONCLUSION (Scenes 12-14): Resolve the conflict with the Future Prediction. Echo the intro hook. End on EMPOWERMENT — the viewer leaves with frameworks and detection tools, feeling smarter, NOT scared or helpless.

CRITICAL OUTPUT RULES:
- You must output valid JSON only.
- No markdown formatting.
- EXACTLY 14 scenes. Not 20. Not 17. Fourteen.

REQUIRED JSON STRUCTURE:
{
  "script_outline": [
    { "scene_number": 1, "beat": "Description of scene 1..." },
    { "scene_number": 2, "beat": "Description of scene 2..." }
    // ... continues to 14
  ]
}"""

        prompt = f"""Create a 14-scene Beat Sheet for a documentary video titled: "{video_data['Video Title']}".
Target: 15-20 minutes (~2,800 words total). Do NOT exceed 14 scenes.

CONTEXT:
Here is the core Narrative DNA (Past/Present/Future):
Past Context: {video_data.get('Past Context', '')}
Present Parallel: {video_data.get('Present Parallel', '')}
Future Prediction: {video_data.get('Future Prediction', '')}

Here is the REQUIRED Opening Hook (Use this for Scene 1):
"{video_data.get('Hook Script', '')}"

Here is the Writer Guidance/Tone:
"{video_data.get('Writer Guidance', '')}\""""
        
        response = await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            model="claude-opus-4-5-20251101",  # Use Opus for beat sheet
        )
        
        # Parse JSON response
        import json
        clean_response = response.replace("```json", "").replace("```", "").strip()
        result = json.loads(clean_response)

        # Hard ceiling: cap at 14 scenes regardless of what the LLM returns
        MAX_SCENES = 14
        outline = result.get("script_outline", [])
        if len(outline) > MAX_SCENES:
            result["script_outline"] = outline[:MAX_SCENES]

        return result

    async def write_scene(
        self,
        scene_number: int,
        scene_beat: str,
        video_title: str,
    ) -> str:
        """Write the voiceover narration for a single scene.
        
        Uses the Writer Bot prompt from the n8n workflow.
        """
        system_prompt = """You are the Voiceover Scriptwriter for a high-retention YouTube documentary.

STYLE GUIDE:
- LENGTH: Strictly 180-200 words.
- TONE: Urgent, authoritative, clear.
- FORMAT: Spoken word only. No "Scene 1" labels. No "Camera pans".
- CONTINUITY: If this is Scene 1, start with a hook. If it is Scene 20, conclude the thought.

INSTRUCTION:
Write the script for the scene provided. Return ONLY the narration text."""
        
        prompt = f"""Write the spoken narration for SCENE {scene_number} ONLY.

CONTEXT:
Video Title: "{video_title}"
Current Scene Goal: "{scene_beat}\""""
        
        return await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            model="claude-opus-4-5-20251101",
        )
    
    async def generate_image_prompts(
        self,
        scene_number: int,
        scene_text: str,
        video_title: str,
        research_payload: str = "",
    ) -> list[str]:
        """Generate 6 image prompts for a scene using holographic intelligence display style.

        Uses the 3-variable architecture: Display Content + Display Format + Color Mood.
        Every frame is a holographic projection in a dark intelligence operations center.
        Zero human figures — only data, maps, charts, and analytical visualizations.

        Args:
            scene_number: The scene number in the video
            scene_text: The narration text for this scene
            video_title: The video title
            research_payload: Optional research payload JSON for extracting real data points
        """
        # Build content type descriptions for the system prompt
        content_type_ref = "\n".join([
            f"Type {chr(65+i)} — {cfg['label']}: {cfg['use_for']}\n  Key elements: {cfg['key_elements']}"
            for i, (ct, cfg) in enumerate(CONTENT_TYPE_CONFIG.items())
        ])

        # Build format descriptions
        format_ref = "\n".join([
            f"Format {i+1} — {cfg['label']}: {cfg['framing']}"
            for i, (fmt, cfg) in enumerate(DISPLAY_FORMAT_CONFIG.items())
        ])

        # Build color mood descriptions
        mood_ref = "\n".join([
            f"Palette {i+1} — {cfg['label']}: {cfg['use_for']}\n  Prompt language: \"{cfg['prompt_language']}\""
            for i, (mood, cfg) in enumerate(COLOR_MOOD_CONFIG.items())
        ])

        system_prompt = f"""You are a visual director creating HOLOGRAPHIC INTELLIGENCE DISPLAY image prompts.

=== CORE AESTHETIC ===
Every image exists inside a dark, high-security intelligence operations center.
The room is barely visible — dark walls, subtle ambient equipment glow.
The star of every frame is the HOLOGRAPHIC PROJECTION SURFACE — a table, wall display,
or floating mid-air projection showing analytical content.

Think: war room from Tom Clancy crossed with Bloomberg Terminal crossed with Minority Report.
Clinical. Precise. Authoritative.

=== ABSOLUTE RULES ===
1. NEVER include human figures, faces, hands, or human silhouettes
2. NEVER include real flags or government seals (analytical references OK)
3. ALL text must be analytical labels, data readouts, classification stamps
4. Room is barely visible (10-15% of frame max)
5. Every image MUST contain at least one quantitative data element (number, %, date)
6. Text must be data-formatted ("$148.20", "21 MILES", "70% DECLINE"), NOT narrative
7. Holographic projection MUST have visible depth/dimensionality (floating, projected, wireframe)
8. Scale and proportion matter — include distance markers, size labels, specific numbers

=== 3-VARIABLE PROMPT ARCHITECTURE ({PROMPT_MIN_WORDS}-{PROMPT_MAX_WORDS} words) ===

[DISPLAY FORMAT framing] + [DISPLAY CONTENT with specific data] + [COLOR MOOD palette] + [UNIVERSAL SUFFIX]

Variable 1 — DISPLAY CONTENT TYPES:
{content_type_ref}

Variable 2 — DISPLAY FORMAT TEMPLATES:
{format_ref}

Variable 3 — COLOR MOOD PALETTES:
{mood_ref}

=== UNIVERSAL SUFFIX (append to EVERY prompt) ===
"{HOLOGRAPHIC_SUFFIX}"

=== ROTATION RULES ===
- Never use the same content type for more than 2 consecutive images
- Never use the same format for more than 2 consecutive images
- Never use the same color palette for more than 3 consecutive images
- Vary formats across the 6 images for visual variety

=== EXAMPLE GOOD PROMPT ===
"{EXAMPLE_PROMPTS[0]}"

=== OUTPUT FORMAT (JSON only, no markdown) ===
{{
  "scene": {scene_number},
  "prompts": [
    {{
      "content_type": "geographic_map",
      "display_format": "war_table",
      "color_mood": "strategic",
      "prompt": "the full prompt text..."
    }}
  ]
}}"""

        research_context = ""
        if research_payload:
            research_context = f"""

RESEARCH DATA (use specific numbers, dates, and facts from this in your prompts):
{research_payload[:3000]}"""

        prompt = f"""Create 6 holographic intelligence display image prompts for this scene:

Video Title: {video_title}
Scene Number: {scene_number}

SCENE TEXT:
{scene_text}
{research_context}

For each prompt:
1. Analyze the scene text for analytical content and data points
2. Select the best content type (A-H), format (1-5), and color mood (1-6)
3. Write a {PROMPT_MIN_WORDS}-{PROMPT_MAX_WORDS} word prompt describing the holographic display
4. Include SPECIFIC data points from the scene text and research
5. End every prompt with the universal suffix

Generate exactly 6 prompts. Every prompt describes a holographic projection, NOT a real scene."""

        response = await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            model="claude-sonnet-4-5-20250929",
            max_tokens=6000,
        )

        import json
        clean_response = response.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_response)
        prompt_entries = data.get("prompts", [])

        # Extract just the prompt strings, handling both formats
        prompts = []
        for entry in prompt_entries:
            if isinstance(entry, dict):
                prompts.append(entry.get("prompt", ""))
            else:
                prompts.append(str(entry))

        # Validate word counts
        for i, p in enumerate(prompts):
            word_count = len(p.split())
            if word_count < PROMPT_MIN_WORDS or word_count > PROMPT_MAX_WORDS:
                print(f"      ⚠️ Prompt {i+1} word count: {word_count} (target {PROMPT_MIN_WORDS}-{PROMPT_MAX_WORDS})")

        return prompts
    
    async def generate_video_ideas(self, video_dna: dict) -> list[dict]:
        """Generate 3 video concept ideas from analyzed video DNA.
        
        Uses the Idea Bot 3.0 prompt from the n8n workflow.
        """
        system_prompt = """You are the Executive Producer for 'Economy Fast-Forward'. Your objective is to transform the input into exactly 3 DISTINCT video concepts.

INSTRUCTIONS:
1. Analyze the input video DNA.
2. Generate 3 distinct futuristic scenarios:
   - Concept 1: The Direct Sequel (Closely related)
   - Concept 2: The Contrarian Pivot (Opposite view)
   - Concept 3: The Black Swan (High risk/reward)
3. Follow the "Abstraction -> Substitution -> Projection" logic for every idea.

CRITICAL OUTPUT RULES:
- You must output valid JSON only.
- Do NOT output a single object. You must output an ARRAY of 3 objects inside a "concepts" key.
- No markdown formatting.

REQUIRED JSON STRUCTURE:
{
  "concepts": [
    {
      "viral_title": "Title 1",
      "thumbnail_visual": "Visual 1",
      "hook_script": "Hook 1",
      "narrative_logic": {
        "past_context": "...",
        "present_parallel": "...",
        "future_prediction": "..."
      },
      "writer_guidance": "..."
    },
    { "viral_title": "Title 2", ... },
    { "viral_title": "Title 3", ... }
  ]
}"""
        
        prompt = f"""Analyze this video DNA: {video_dna}

CRITICAL TASK: You must generate exactly 3 DISTINCT video concepts. Return them as a JSON Array inside a concepts key."""
        
        response = await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            model="claude-sonnet-4-5-20250929",
        )
        
        import json
        clean_response = response.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_response)
        
        # Handle various response formats
        if "concepts" in data:
            return data["concepts"]
        elif isinstance(data, list):
            return data
        else:
            return [data]

    async def generate_sentence_image_prompt(
        self,
        sentence_text: str,
        sentence_index: int,
        total_sentences: int,
        scene_number: int,
        video_title: str,
        previous_prompt: str = "",
    ) -> str:
        """Generate a single image prompt for a sentence using cinematic photorealistic style.

        This creates visually coherent, sentence-aligned image prompts.

        Args:
            sentence_text: The specific sentence to illustrate
            sentence_index: Position in scene (1-based)
            total_sentences: Total sentences in scene
            scene_number: The scene number
            video_title: Title of the video
            previous_prompt: The previous image prompt (for visual continuity)

        Returns:
            A single image prompt string ({PROMPT_MIN_WORDS}-{PROMPT_MAX_WORDS} words)
        """
        # Get scene type and camera role for this sentence
        scene_type, camera_role = get_scene_type_for_segment(
            sentence_index - 1, total_sentences, None
        )
        shot_prefix = SCENE_TYPE_CONFIG[scene_type]["shot_prefix"]

        system_prompt = f"""You are a visual director creating cinematic photorealistic documentary image prompts.

=== STYLE: CINEMATIC PHOTOREALISTIC DOCUMENTARY ===
Dark moody atmosphere, desaturated palette, Rembrandt lighting, deep shadows.
Anonymous human figures with faces obscured by shadow, silhouette, or backlighting.
Every prompt should feel like a still from a prestige documentary.

=== 5-LAYER ARCHITECTURE ({PROMPT_MIN_WORDS}-{PROMPT_MAX_WORDS} words) ===
CRITICAL: Style engine prefix goes FIRST.

1. STYLE_ENGINE_PREFIX (always first): "{STYLE_ENGINE_PREFIX}"
2. SHOT TYPE: "{shot_prefix}..." (Camera role: {camera_role.value})
3. SCENE COMPOSITION: Real-world environment with cinematic lighting
4. FOCAL SUBJECT: Anonymous figures, faces hidden by shadow/angle/backlighting, with BODY LANGUAGE
5. ENVIRONMENTAL STORYTELLING: Objects that tell the story
6. STYLE_ENGINE_SUFFIX + LIGHTING: "{STYLE_ENGINE_SUFFIX}, [warm vs cool contrast]"
7. TEXT RULE: "{TEXT_RULE_NO_TEXT}" (or specify max 3 elements with surfaces)

=== RULES ===
- This prompt illustrates ONE SPECIFIC SENTENCE
- Visual must directly represent what the sentence says
- Maintain visual continuity with previous image
- Cinematic environments: boardrooms, trading floors, vaults, corridors, war rooms
- Body language conveys emotion (shoulders slumped, arms crossed, leaning forward)

OUTPUT: Return ONLY the prompt string, no JSON, no explanation."""

        continuity_note = ""
        if previous_prompt:
            continuity_note = f"\n\nPREVIOUS IMAGE (maintain continuity):\n{previous_prompt[:150]}..."

        prompt = f"""Create ONE image prompt for this sentence using cinematic photorealistic documentary style:

SHOT TYPE: {shot_prefix}...
CAMERA ROLE: {camera_role.value}

SENTENCE TO ILLUSTRATE:
"{sentence_text}"
{continuity_note}

Generate {PROMPT_MIN_WORDS}-{PROMPT_MAX_WORDS} word prompt.
Start with style engine prefix, end with style engine suffix + lighting + text rule."""

        response = await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            model="claude-sonnet-4-5-20250929",
            max_tokens=500,
        )

        return response.strip()

    async def generate_sentence_level_prompts(
        self,
        scene_number: int,
        scene_text: str,
        video_title: str,
    ) -> list[dict]:
        """Generate image prompts aligned to sentences in the scene.

        DEPRECATED: Use generate_semantic_segments() for smarter segmentation.

        This is the old sentence-level approach (one image per sentence).
        """
        from clients.sentence_utils import analyze_scene_for_images

        # Analyze the scene into sentences
        sentences = analyze_scene_for_images(scene_text)

        results = []
        previous_prompt = ""

        for sentence_data in sentences:
            # Generate prompt for this sentence
            prompt = await self.generate_sentence_image_prompt(
                sentence_text=sentence_data["sentence_text"],
                sentence_index=sentence_data["sentence_index"],
                total_sentences=len(sentences),
                scene_number=scene_number,
                video_title=video_title,
                previous_prompt=previous_prompt,
            )

            results.append({
                "sentence_index": sentence_data["sentence_index"],
                "sentence_text": sentence_data["sentence_text"],
                "duration_seconds": sentence_data["duration_seconds"],
                "cumulative_start": sentence_data["cumulative_start"],
                "image_prompt": prompt,
            })

            previous_prompt = prompt

        return results

    async def generate_semantic_segments(
        self,
        scene_number: int,
        scene_text: str,
        video_title: str,
        max_segment_duration: float = 10.0,
    ) -> list[dict]:
        """Generate image prompts based on semantic visual segments.

        This is the smart segmentation approach that:
        1. Groups sentences by visual concept (not mechanical splitting)
        2. Only creates new images when the visual needs to shift
        3. Enforces max duration per segment (for AI video generation limits)

        Args:
            scene_number: The scene number
            scene_text: Full scene narration text
            video_title: Title of the video
            max_segment_duration: Maximum seconds per segment (default 10s for AI video)

        Returns:
            List of dicts with:
                - segment_index: int
                - segment_text: str (combined sentences)
                - duration_seconds: float
                - cumulative_start: float
                - image_prompt: str
                - visual_concept: str (description of why this is a segment)
        """
        # Step 1: Have Claude analyze and segment the scene semantically
        segments = await self._analyze_visual_segments(scene_text, max_segment_duration)

        # Step 2: Generate image prompts for each segment
        results = []
        previous_prompt = ""
        cumulative_time = 0.0

        for i, segment in enumerate(segments):
            # Generate prompt for this segment
            prompt = await self._generate_segment_image_prompt(
                segment_text=segment["text"],
                visual_concept=segment["visual_concept"],
                segment_index=i + 1,
                total_segments=len(segments),
                scene_number=scene_number,
                video_title=video_title,
                previous_prompt=previous_prompt,
            )

            results.append({
                "segment_index": i + 1,
                "segment_text": segment["text"],
                "duration_seconds": segment["duration"],
                "cumulative_start": round(cumulative_time, 1),
                "image_prompt": prompt,
                "visual_concept": segment["visual_concept"],
            })

            cumulative_time += segment["duration"]
            previous_prompt = prompt

        return results

    async def _analyze_visual_segments(
        self,
        scene_text: str,
        max_duration: float = 10.0,
    ) -> list[dict]:
        """Use Claude to semantically segment a scene into visual concepts.

        Returns list of segments, each with:
            - text: the narration for this segment
            - visual_concept: why this is a distinct visual
            - duration: estimated duration in seconds
        """
        from clients.sentence_utils import split_into_sentences, estimate_sentence_duration

        system_prompt = """You are an expert video editor segmenting narration for AI-animated documentary videos.

YOUR TASK: Analyze the scene narration and group sentences into VISUAL SEGMENTS.

RULES FOR SEGMENTATION:
1. Group sentences that share the SAME visual concept (keep together)
2. Create a NEW segment when the visual needs to SHIFT (new concept, new metaphor, new subject)
3. Each segment MUST be ≤{max_duration} seconds (this is a hard technical limit for AI video generation)
4. Short rhetorical phrases ("Different decade. Different industry.") should stay TOGETHER if same concept
5. Aim for 4-8 segments per scene (not too few, not too many)

DURATION CALCULATION:
- Average speaking rate: 173 words per minute
- Formula: (word_count / 173) * 60 = seconds
- Minimum 2 seconds per segment

OUTPUT FORMAT (JSON only, no markdown):
{{
  "segments": [
    {{
      "sentences": ["First sentence.", "Second sentence that continues same idea."],
      "visual_concept": "Brief description of what visual this represents",
      "estimated_duration": 8.5
    }},
    {{
      "sentences": ["New concept starts here."],
      "visual_concept": "Description of new visual",
      "estimated_duration": 4.2
    }}
  ]
}}

CRITICAL: If a segment would exceed {max_duration}s, you MUST split it even if same concept.
Add "(continued)" to visual_concept for split segments."""

        prompt = f"""Segment this scene narration into visual segments (max {max_duration}s each):

SCENE TEXT:
{scene_text}

Return JSON with segments array. Each segment groups sentences by visual concept."""

        response = await self.generate(
            prompt=prompt,
            system_prompt=system_prompt.format(max_duration=max_duration),
            model="claude-sonnet-4-5-20250929",
            max_tokens=2000,
        )

        # Parse the response
        import json
        clean_response = response.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_response)

        # Convert to our format and validate durations
        results = []
        for seg in data.get("segments", []):
            text = " ".join(seg.get("sentences", []))
            # Recalculate duration to be accurate
            duration = estimate_sentence_duration(text)
            # Enforce max duration
            if duration > max_duration:
                duration = max_duration

            results.append({
                "text": text,
                "visual_concept": seg.get("visual_concept", ""),
                "duration": round(duration, 1),
            })

        return results

    async def _generate_segment_image_prompt(
        self,
        segment_text: str,
        visual_concept: str,
        segment_index: int,
        total_segments: int,
        scene_number: int,
        video_title: str,
        previous_prompt: str = "",
    ) -> str:
        """Generate an image prompt for a semantic segment using cinematic photorealistic style."""
        # Get scene type and camera role for this segment
        scene_type, camera_role = get_scene_type_for_segment(
            segment_index - 1,  # Convert to 0-based
            total_segments,
            None  # We don't track previous here, handled in main method
        )
        shot_prefix = SCENE_TYPE_CONFIG[scene_type]["shot_prefix"]

        system_prompt = f"""You are a visual director creating cinematic photorealistic documentary image prompts.

=== STYLE: CINEMATIC PHOTOREALISTIC DOCUMENTARY ===
Dark moody atmosphere, desaturated palette, Rembrandt lighting, deep shadows.
Anonymous human figures with faces obscured by shadow, silhouette, or backlighting.
Every prompt should feel like a still from a prestige documentary.

=== 5-LAYER ARCHITECTURE ({PROMPT_MIN_WORDS}-{PROMPT_MAX_WORDS} words) ===
CRITICAL: Style engine prefix goes FIRST.

1. STYLE_ENGINE_PREFIX (always first): "{STYLE_ENGINE_PREFIX}"
2. SHOT TYPE: "{shot_prefix}..." (Camera role: {camera_role.value})
3. SCENE COMPOSITION: Real-world environment with cinematic lighting
4. FOCAL SUBJECT: Anonymous figures, faces hidden by shadow/angle/backlighting
5. ENVIRONMENTAL STORYTELLING: Objects that tell the story
6. STYLE_ENGINE_SUFFIX + LIGHTING: "{STYLE_ENGINE_SUFFIX}, [warm vs cool contrast]"
7. TEXT RULE: "{TEXT_RULE_NO_TEXT}"

=== DO NOT ===
- Use illustration, 2D, or stylized references
- Show clear facial features (faces always obscured)
- Use double quotes (use single quotes)

=== DO ===
- Cinematic environments: boardrooms, trading floors, vaults, corridors
- Body language for emotion: shoulders slumped, arms crossed, leaning forward
- Every word describes something VISUAL
- Camera: Arri Alexa 65, 35mm Master Prime lens, Kodak Vision3 500T

OUTPUT: Return ONLY the prompt string (no JSON, no explanation)."""

        continuity_note = ""
        if previous_prompt:
            continuity_note = f"\n\nPREVIOUS IMAGE (maintain visual continuity):\n{previous_prompt[:150]}..."

        prompt = f"""Create ONE image prompt for this segment using cinematic photorealistic documentary style:

SHOT TYPE: {shot_prefix}...
CAMERA ROLE: {camera_role.value}

NARRATION TEXT:
"{segment_text}"

VISUAL CONCEPT: {visual_concept}
{continuity_note}

Generate {PROMPT_MIN_WORDS}-{PROMPT_MAX_WORDS} word prompt.
Start with style engine prefix, end with style engine suffix + lighting + text rule."""

        response = await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            model="claude-sonnet-4-5-20250929",
            max_tokens=500,
        )

        return response.strip()

    async def generate_thumbnail_prompt(
        self,
        video_title: str,
        video_summary: str,
        thumbnail_spec_json: dict = None,
        thumbnail_concept: str = "",
    ) -> str:
        """Generate a detailed thumbnail image prompt.

        Works with OR without a reference thumbnail spec.
        Always enforces Economy FastForward house style.

        Args:
            video_title: The video's title
            video_summary: Brief summary of the video's content
            thumbnail_spec_json: Optional Gemini-analyzed reference spec
            thumbnail_concept: Optional basic concept/direction from Airtable

        Returns:
            Complete image generation prompt for Nano Banana Pro
        """
        import json

        prompt_parts = [
            f'Generate a thumbnail prompt for this Economy FastForward video:',
            f'',
            f'VIDEO TITLE: "{video_title}"',
            f'VIDEO SUMMARY: {video_summary}',
        ]

        if thumbnail_spec_json:
            prompt_parts.append(f'')
            prompt_parts.append(f'REFERENCE THUMBNAIL ANALYSIS (adapt style cues, enforce house style):')
            prompt_parts.append(json.dumps(thumbnail_spec_json, indent=2))

        if thumbnail_concept:
            prompt_parts.append(f'')
            prompt_parts.append(f'CREATIVE DIRECTION: {thumbnail_concept}')

        prompt_parts.extend([
            f'',
            f'THUMBNAIL TEXT TO INCLUDE:',
            f'Generate two lines of text for the thumbnail based on the video title.',
            f'Line 1: The hook (year/number/dramatic claim) — max 5 words, ALL CAPS',
            f'Line 2: The question/tension — max 5 words, ALL CAPS',
            f'Pick ONE word to highlight in red (the curiosity trigger).',
            f'',
            f'Generate the complete image prompt now.',
        ])

        user_prompt = '\n'.join(prompt_parts)

        response = await self.generate(
            prompt=user_prompt,
            system_prompt=ANTHROPIC_THUMBNAIL_SYSTEM_PROMPT,
            model="claude-sonnet-4-5-20250929",
            max_tokens=1200,
        )

        return response.strip()

    async def segment_scene_into_concepts(
        self,
        scene_text: str,
        target_count: int,
        min_count: int,
        max_count: int,
        words_per_segment: int = 20,
        scene_number: int = 1,
        pipeline_type: str = "animation",
        research_payload: str = "",
    ) -> list[dict]:
        """Segment scene text into visual concepts using holographic intelligence display style.

        Args:
            scene_text: Full scene narration text
            target_count: Target number of segments
            min_count: Minimum allowed segments
            max_count: Maximum allowed segments
            words_per_segment: Target words per segment for duration
            scene_number: The scene number
            pipeline_type: "youtube" or "animation" (both now use holographic style)
            research_payload: Optional research data for extracting specific data points

        Returns:
            List of dicts with:
                - text: str (the narration text for this segment)
                - image_prompt: str (the generated image prompt)
                - shot_type: str (the display format for this segment)
        """
        # Build display format guidance
        format_guidance = "\n".join([
            f"Segment {i+1}: Use \"{DISPLAY_FORMAT_CONFIG[list(DISPLAY_FORMAT_CONFIG.keys())[i % len(DISPLAY_FORMAT_CONFIG)]]['framing']}...\""
            for i in range(target_count)
        ])

        system_prompt = f"""You are a visual director creating HOLOGRAPHIC INTELLIGENCE DISPLAY image prompts.

YOUR TASK: Divide this scene into {target_count} visual segments ({min_count}-{max_count} range) and create image prompts.

=== CORE AESTHETIC ===
Every image exists inside a dark, high-security intelligence operations center.
The room is barely visible. The star of every frame is the HOLOGRAPHIC PROJECTION.
Think: war room from Tom Clancy crossed with Bloomberg Terminal crossed with Minority Report.

=== ABSOLUTE RULES ===
1. NEVER include human figures, faces, hands, or human silhouettes
2. ALL text must be analytical labels, data readouts, or classification stamps
3. Every image MUST contain at least one quantitative data element
4. Holographic projection MUST have visible depth/dimensionality

=== CRITICAL DURATION RULE ===
- Each segment: ~{words_per_segment} words (±5 words)
- Ensures 6-10 second display per image
- Balance word counts — no segment 2x longer than another

=== PROMPT ARCHITECTURE ({PROMPT_MIN_WORDS}-{PROMPT_MAX_WORDS} words) ===

[DISPLAY FORMAT framing] + [DISPLAY CONTENT with specific data] + [COLOR MOOD palette] + [UNIVERSAL SUFFIX]

Content Types: geographic_map, data_terminal, object_comparison, document_display, network_diagram, timeline, satellite_recon, concept_viz
Display Formats: war_table, wall_display, floating, multi_panel, close_up_detail
Color Moods: strategic (teal), alert (red), archive (gold), contagion (green-to-red), power (navy), personal (orange)

=== UNIVERSAL SUFFIX (append to EVERY prompt) ===
"{HOLOGRAPHIC_SUFFIX}"

=== DISPLAY FORMAT ROTATION ===
{format_guidance}

=== OUTPUT FORMAT (JSON only, no markdown) ===
{{
  "segments": [
    {{
      "text": "The narration text for this segment...",
      "image_prompt": "[format framing] [content description with data] [color mood]{HOLOGRAPHIC_SUFFIX}",
      "shot_type": "war_table"
    }}
  ]
}}

=== SHOT TYPE VALUES (display formats) ===
- war_table (overhead angled, holographic table)
- wall_display (front-facing wall screen)
- floating (objects floating in dark space)
- multi_panel (multiple display panels)
- close_up_detail (tight crop on data point)"""

        research_context = ""
        if research_payload:
            research_context = f"""

RESEARCH DATA (use specific numbers, dates, and facts from this):
{research_payload[:2000]}"""

        prompt = f"""Segment this scene into {target_count} holographic intelligence display visualizations:

SCENE TEXT:
{scene_text}
{research_context}

Return JSON with segments array. Each segment has text, image_prompt, and shot_type.
REMEMBER: {PROMPT_MIN_WORDS}-{PROMPT_MAX_WORDS} words per prompt. NO human figures.
Every prompt describes a holographic projection with specific data points."""

        response = await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            model="claude-sonnet-4-5-20250929",
            max_tokens=4000,
        )

        # Parse the response
        import json
        clean_response = response.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_response)

        segments = data.get("segments", [])

        # Valid shot types (display formats)
        valid_shot_types = [
            "war_table", "wall_display", "floating", "multi_panel", "close_up_detail",
            # Legacy compatibility
            "wide_establishing", "isometric_diorama", "medium_human_story",
            "close_up_vignette", "data_landscape", "split_screen",
            "pull_back_reveal", "overhead_map", "journey_shot",
        ]

        # Validate and log word counts, ensure shot_type is valid
        for i, seg in enumerate(segments):
            prompt_text = seg.get("image_prompt", "")
            word_count = len(prompt_text.split())
            if word_count < PROMPT_MIN_WORDS:
                print(f"      ⚠️ Segment {i+1} prompt too short: {word_count} words (min {PROMPT_MIN_WORDS})")
            elif word_count > PROMPT_MAX_WORDS:
                print(f"      ⚠️ Segment {i+1} prompt too long: {word_count} words (max {PROMPT_MAX_WORDS})")

            # Validate/default shot_type
            shot_type = seg.get("shot_type", "").lower().strip()
            if shot_type not in valid_shot_types:
                shot_type = "war_table"  # safe default
                print(f"      ⚠️ Segment {i+1} missing/invalid shot_type, using: {shot_type}")
            seg["shot_type"] = shot_type

        return segments

    async def generate_video_prompt(
        self,
        image_prompt: str,
        sentence_text: str = "",
        scene_type: str = None,
        is_hero_shot: bool = False,
    ) -> str:
        """Generate a motion prompt for image-to-video animation.

        Creates a motion-only prompt for Grok Imagine that describes camera movement,
        subject motion, and atmospheric effects WITHOUT re-describing the scene.

        Args:
            image_prompt: The prompt used to generate the static image.
            sentence_text: The narration being spoken during this image (for alignment).
            scene_type: Scene type string (e.g., "isometric_diorama", "split_screen").
            is_hero_shot: If True, generate a richer prompt for 10s duration (vs 6s standard).

        Returns:
            Motion prompt (max 40 words for 6s, max 55 words for 10s hero).
        """
        from .style_engine import get_camera_motion

        # Determine camera motion based on scene type
        # Pass string directly - get_camera_motion handles both strings and SceneType enums
        camera_motion = get_camera_motion(scene_type, is_hero_shot) if scene_type else "Slow push-in"

        # Word limit based on duration
        word_limit = 55 if is_hero_shot else 40
        duration_note = "10-second HERO SHOT" if is_hero_shot else "6-second clip"
        hero_instruction = """
For this HERO SHOT (10s), include one additional motion element after the primary subject motion.
The camera movement can have a secondary phase (e.g., "gradually revealing the full map").""" if is_hero_shot else ""

        system_prompt = f"""You are an expert motion prompt engineer for AI image-to-video generation (Grok Imagine).

CRITICAL RULES:
1. The source image ALREADY contains the full scene. NEVER re-describe the scene.
2. You ONLY describe what MOVES and HOW it moves.
3. Use this exact structure: [Camera movement] + [Primary subject motion] + [Ambient motion]
4. Maximum {word_limit} words for this {duration_note}.
5. The art style is cinematic photorealistic documentary photography. Motion should feel subtle and cinematic:
   - Figures subtly shifting weight, silhouettes slowly turning
   - Atmospheric haze drifting, light sweeping across surfaces
   - Dust particles, lens flare, reflections on wet pavement
{hero_instruction}

REQUIRED CAMERA MOVEMENT (START your response with this exact movement):
"{camera_motion}"

CRITICAL: Your response MUST begin with this camera movement. Do NOT substitute "push-in" or "zoom".

MOTION VOCABULARY - CINEMATIC DOCUMENTARY STYLE:

Human Figures:
- "figure subtly shifts weight"
- "silhouette slowly turns"
- "figure's arm gradually lifts"
- "figure's head gently tilts down"
- "fingers slowly close around handle"

Mechanical/Industrial:
- "gears slowly rotate"
- "pipes subtly vibrate"
- "gauge needles drift toward red zone"
- "lever gradually pulls down"
- "cracks slowly spread through concrete"

Environmental:
- "dust particles float through light beams"
- "fog wisps curl between objects"
- "light slowly sweeps across chrome surface"
- "reflections shift on metallic surfaces"

Data/Abstract:
- "chart bars slowly rise"
- "trend line gradually draws itself"
- "numerals gently pulse with light"
- "glass panel slowly illuminates"

Atmospheric (include at least one):
- "warm spotlight slowly brightens"
- "shadows gradually lengthen"
- "ambient light subtly shifts from cool to warm"
- "lens flare drifts across frame"

SPEED WORDS - MANDATORY:
ALWAYS use: slow, subtle, gentle, soft, gradual, drifting, easing
NEVER use: fast, sudden, dramatic, explosive, rapid, intense, quick

OUTPUT: Return ONLY the motion prompt text. No explanations, no formatting, no labels."""

        narration_context = ""
        if sentence_text:
            narration_context = f"\n\nNarration being spoken during this image: \"{sentence_text}\""

        prompt = f"""Image Prompt (for context, do NOT repeat scene descriptions):
{image_prompt}
{narration_context}

The camera movement is ALREADY DECIDED: "{camera_motion}"
Generate ONLY the subject motion + ambient motion ({word_limit - 10} words max).
Do NOT include any camera movement - I will prepend it."""

        response = await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            model="claude-sonnet-4-5-20250929",
            max_tokens=200,
        )

        # Prepend the camera motion to guarantee variety
        subject_motion = response.strip()
        return f"{camera_motion}. {subject_motion}"
