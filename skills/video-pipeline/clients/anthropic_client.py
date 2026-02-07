"""Anthropic Claude API client for script and prompt generation."""

import os
from anthropic import Anthropic
from typing import Optional, List, Dict, Tuple

from clients.style_engine import (
    STYLE_ENGINE,
    SceneType,
    CameraRole,
    SCENE_TYPE_CONFIG,
    get_documentary_pattern,
    get_scene_type_for_segment,
    PROMPT_MIN_WORDS,
    PROMPT_MAX_WORDS,
    EXAMPLE_PROMPTS,
)


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
    ) -> str:
        """Generate a completion using Claude.
        
        Args:
            prompt: The user prompt
            system_prompt: System instructions
            model: Model to use (claude-sonnet-4-5-20250929, claude-opus-4-5-20251101)
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature
            
        Returns:
            The generated text response
        """
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
        
        response = self.client.messages.create(**kwargs)
        
        return response.content[0].text
    
    async def generate_beat_sheet(self, video_data: dict) -> dict:
        """Generate a 20-scene beat sheet for a video.
        
        Uses the Script Architect prompt from the n8n workflow.
        """
        system_prompt = """You are a Master Storyteller and Narrative Architect.

Your task is to create a 20-scene Beat Sheet for documentary videos.

INSTRUCTIONS:
1. Analyze the input. Is it raw video DNA or a rejection?
2. Generate the beat sheet following this narrative arc:
   - INTRO (Scenes 1-4): Introduce the hook, the stakes, and the main question.
   - BUILD-UP (Scenes 5-16): Escalate tension. Reveal the Past Context and Modern Shift. Show cause-and-effect.
   - CONCLUSION (Scenes 17-20): Resolve the conflict with the Future Prediction. Echo the intro hook.

CRITICAL OUTPUT RULES:
- You must output valid JSON only.
- No markdown formatting.

REQUIRED JSON STRUCTURE:
{
  "script_outline": [
    { "scene_number": 1, "beat": "Description of scene 1..." },
    { "scene_number": 2, "beat": "Description of scene 2..." }
    // ... continues to 20
  ]
}"""
        
        prompt = f"""Create a 20-scene Beat Sheet for a documentary video titled: "{video_data['Video Title']}".

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
        return json.loads(clean_response)
    
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
    ) -> list[str]:
        """Generate 6 image prompts for a scene using Documentary Animation Prompt System v2.

        Uses the 5-layer architecture with scene type rotation and documentary camera pattern.
        """
        # Get documentary pattern for 6 images
        camera_pattern = get_documentary_pattern(6)

        # Build scene type assignments with rotation
        scene_assignments = []
        previous_scene_type = None
        for i in range(6):
            scene_type, camera_role = get_scene_type_for_segment(i, 6, previous_scene_type)
            scene_assignments.append({
                "index": i + 1,
                "shot_prefix": SCENE_TYPE_CONFIG[scene_type]["shot_prefix"],
                "camera_role": camera_role.value,
            })
            previous_scene_type = scene_type

        shot_guidance = "\n".join([
            f"Image {a['index']}: {a['camera_role'].upper()} → \"{a['shot_prefix']}...\""
            for a in scene_assignments
        ])

        system_prompt = f"""You are a visual director creating documentary-style image prompts for AI animation.

=== 5-LAYER PROMPT ARCHITECTURE ===
Every prompt MUST follow this structure ({PROMPT_MIN_WORDS}-{PROMPT_MAX_WORDS} words total):

[SHOT TYPE] + [SCENE COMPOSITION] + [FOCAL SUBJECT] + [ENVIRONMENTAL STORYTELLING] + [STYLE_ENGINE + LIGHTING]

1. SHOT TYPE (5 words): Use the assigned shot prefix
2. SCENE COMPOSITION (15 words): Physical scene/environment - be CONCRETE
3. FOCAL SUBJECT (20 words): Main character/object with action/emotion
4. ENVIRONMENTAL STORYTELLING (30 words): Symbolic objects, visual metaphors, data made physical
5. STYLE ENGINE + LIGHTING (50 words): "{STYLE_ENGINE}, [warm vs cool color contrast lighting]"

=== DOCUMENTARY CAMERA PATTERN ===
{shot_guidance}

=== DO NOT ===
- Repeat concepts in different words
- Explain economics (models don't understand abstract concepts)
- Use vague abstractions
- Include keyword spam
- Use double quotes (use single quotes)

=== DO ===
- Concrete nouns: "dollar sign barriers", "crumbling bridge", "glowing neon skyline"
- Specific colors: "warm amber", "cold blue-white", "muted earth tones with red warning accents"
- Spatial relationships: "left side dim, right side glowing"
- Texture words: "paper-cut", "layered", "brushstroke", "film grain"

=== EXAMPLE GOOD PROMPT ===
"{EXAMPLE_PROMPTS[0]}"

OUTPUT FORMAT (JSON only, no markdown):
{{
  "scene": {scene_number},
  "prompts": ["prompt 1...", "prompt 2...", ...]
}}"""

        prompt = f"""Create 6 image prompts for this scene following the documentary camera pattern:

Video Title: {video_title}
Scene Number: {scene_number}

SCENE TEXT:
{scene_text}

SHOT ASSIGNMENTS:
{shot_guidance}

Generate exactly 6 prompts, {PROMPT_MIN_WORDS}-{PROMPT_MAX_WORDS} words each. Every word must describe something VISUAL."""

        response = await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            model="claude-sonnet-4-5-20250929",
            max_tokens=4000,
        )

        import json
        clean_response = response.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_response)
        prompts = data.get("prompts", [])

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
        """Generate a single image prompt for a specific sentence using Documentary Animation Prompt System v2.

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

        system_prompt = f"""You are a visual director creating documentary-style image prompts for AI animation.

=== 5-LAYER PROMPT ARCHITECTURE ({PROMPT_MIN_WORDS}-{PROMPT_MAX_WORDS} words) ===

1. SHOT TYPE: "{shot_prefix}..." (Camera role: {camera_role.value})
2. SCENE COMPOSITION: Physical scene/environment (be CONCRETE)
3. FOCAL SUBJECT: Main character/object with action
4. ENVIRONMENTAL STORYTELLING: Symbolic objects, visual metaphors
5. STYLE ENGINE + LIGHTING: "{STYLE_ENGINE}, [warm vs cool lighting contrast]"

=== RULES ===
- This prompt illustrates ONE SPECIFIC SENTENCE
- The visual must directly represent what the sentence is saying
- Maintain visual continuity with previous image if provided
- Do not use double quotes (use single quotes)
- Every word must describe something VISUAL

OUTPUT: Return ONLY the prompt string, no JSON, no explanation."""

        continuity_note = ""
        if previous_prompt:
            continuity_note = f"\n\nPREVIOUS IMAGE (maintain continuity):\n{previous_prompt[:150]}..."

        prompt = f"""Create ONE image prompt for this sentence:

SHOT TYPE: {shot_prefix}...
CAMERA ROLE: {camera_role.value}

SENTENCE TO ILLUSTRATE:
"{sentence_text}"
{continuity_note}

Generate {PROMPT_MIN_WORDS}-{PROMPT_MAX_WORDS} word prompt ending with STYLE_ENGINE + lighting."""

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
        """Generate an image prompt for a semantic segment using Documentary Animation Prompt System v2."""
        # Get scene type and camera role for this segment
        scene_type, camera_role = get_scene_type_for_segment(
            segment_index - 1,  # Convert to 0-based
            total_segments,
            None  # We don't track previous here, handled in main method
        )
        shot_prefix = SCENE_TYPE_CONFIG[scene_type]["shot_prefix"]

        system_prompt = f"""You are a visual director creating documentary-style image prompts for AI animation.

=== 5-LAYER PROMPT ARCHITECTURE ===
Every prompt MUST follow this structure ({PROMPT_MIN_WORDS}-{PROMPT_MAX_WORDS} words total):

1. SHOT TYPE: "{shot_prefix}..." (Camera role: {camera_role.value})
2. SCENE COMPOSITION: Physical scene/environment (be CONCRETE)
3. FOCAL SUBJECT: Main character/object with action
4. ENVIRONMENTAL STORYTELLING: Symbolic objects, visual metaphors
5. STYLE ENGINE + LIGHTING: "{STYLE_ENGINE}, [warm vs cool lighting contrast]"

=== DO NOT ===
- Repeat concepts in different words
- Explain economics (models don't understand abstract concepts)
- Use vague abstractions
- Use double quotes (use single quotes)

=== DO ===
- Concrete nouns, specific colors, spatial relationships, texture words
- Every word describes something VISUAL

OUTPUT: Return ONLY the prompt string (no JSON, no explanation)."""

        continuity_note = ""
        if previous_prompt:
            continuity_note = f"\n\nPREVIOUS IMAGE (maintain visual continuity):\n{previous_prompt[:150]}..."

        prompt = f"""Create ONE image prompt for this segment:

SHOT TYPE: {shot_prefix}...
CAMERA ROLE: {camera_role.value}

NARRATION TEXT:
"{segment_text}"

VISUAL CONCEPT: {visual_concept}
{continuity_note}

Generate {PROMPT_MIN_WORDS}-{PROMPT_MAX_WORDS} word prompt. End with STYLE_ENGINE + lighting."""

        response = await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            model="claude-sonnet-4-5-20250929",
            max_tokens=500,
        )

        return response.strip()

    async def generate_thumbnail_prompt(
        self,
        thumbnail_spec_json: dict,
        video_title: str,
        thumbnail_concept: str = "",
    ) -> str:
        """Generate a detailed thumbnail image prompt from a Gemini-analyzed spec.

        Takes the structured spec from Gemini's vision analysis and produces
        a detailed image generation prompt suitable for Kie.

        Args:
            thumbnail_spec_json: Structured spec dict from Gemini's analysis
            video_title: Title of the video
            thumbnail_concept: Optional basic concept/idea for the thumbnail

        Returns:
            A detailed image generation prompt string
        """
        import json

        system_prompt = """You are an expert thumbnail prompt engineer for YouTube.

Your task is to take a structured thumbnail analysis (from a reference image) and produce
a DETAILED image generation prompt that recreates a similar style for a NEW video topic.

GUIDELINES:
1. Preserve the composition style, mood, and color palette from the reference analysis
2. Adapt the specific visual elements to match the NEW video's topic
3. Include specific details about: layout, colors, lighting, text placement, focal point
4. The prompt should be detailed enough for an AI image generator to produce a click-worthy thumbnail
5. Include any text overlays that should appear on the thumbnail
6. Keep the prompt under 300 words but be very specific

OUTPUT: Return ONLY the image generation prompt, no explanation or JSON."""

        concept_note = ""
        if thumbnail_concept:
            concept_note = f"\n\nBASIC THUMBNAIL CONCEPT (use as creative direction):\n{thumbnail_concept}"

        prompt = f"""Create a detailed thumbnail image generation prompt for this video:

VIDEO TITLE: "{video_title}"

REFERENCE THUMBNAIL ANALYSIS:
{json.dumps(thumbnail_spec_json, indent=2)}
{concept_note}

Generate a single detailed prompt that adapts the reference style to this video's topic."""

        response = await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            model="claude-sonnet-4-5-20250929",
            max_tokens=1000,
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
    ) -> list[dict]:
        """Segment scene text into visual concepts using Documentary Animation Prompt System v2.

        This implementation uses:
        1. 5-Layer Prompt Architecture (Shot Type → Scene Composition → Focal Subject → Environmental Storytelling → Style Engine + Lighting)
        2. Scene type rotation (6 types, no consecutive repeats)
        3. Documentary camera sequence (4-shot pattern)
        4. Hard word budget (80-120 words per prompt)

        Args:
            scene_text: Full scene narration text
            target_count: Target number of segments
            min_count: Minimum allowed segments
            max_count: Maximum allowed segments
            words_per_segment: Target words per segment for duration
            scene_number: The scene number (for documentary pattern)

        Returns:
            List of dicts with:
                - text: str (the narration text for this segment)
                - image_prompt: str (the generated image prompt)
        """
        # Get documentary pattern for this scene
        camera_pattern = get_documentary_pattern(target_count)

        # Build scene type assignments with rotation
        scene_type_assignments = []
        previous_scene_type = None
        for i in range(target_count):
            scene_type, camera_role = get_scene_type_for_segment(
                i, target_count, previous_scene_type
            )
            scene_type_assignments.append({
                "index": i + 1,
                "scene_type": scene_type,
                "camera_role": camera_role,
                "shot_prefix": SCENE_TYPE_CONFIG[scene_type]["shot_prefix"],
            })
            previous_scene_type = scene_type

        # Format scene type guidance for the prompt
        scene_type_guidance = "\n".join([
            f"Segment {a['index']}: {a['camera_role'].value.upper()} → Use \"{a['shot_prefix']}...\""
            for a in scene_type_assignments
        ])

        system_prompt = f"""You are a visual director creating documentary-style image prompts for AI animation.

YOUR TASK: Divide this scene into {target_count} visual segments ({min_count}-{max_count} range) and create image prompts.

=== CRITICAL DURATION RULE ===
- Each segment: ~{words_per_segment} words (±5 words)
- Ensures 6-10 second display per image
- Balance word counts - no segment 2x longer than another

=== 5-LAYER PROMPT ARCHITECTURE ===
Every prompt MUST follow this exact structure:

[SHOT TYPE] + [SCENE COMPOSITION] + [FOCAL SUBJECT] + [ENVIRONMENTAL STORYTELLING] + [STYLE_ENGINE + LIGHTING]

1. SHOT TYPE (5 words) — Camera framing. Use the assigned shot prefix.
2. SCENE COMPOSITION (15 words) — Physical scene/environment. Be CONCRETE: "a small dim apartment", not "economic stagnation"
3. FOCAL SUBJECT (20 words) — Main character/object with action: "young engineer at desk", "paper-cut workers reaching toward glow"
4. ENVIRONMENTAL STORYTELLING (30 words) — Symbolic objects, visual metaphors, data made physical
5. STYLE ENGINE + LIGHTING (50 words) — ALWAYS end with: "{STYLE_ENGINE}, [lighting description using warm vs cool color contrast]"

=== DOCUMENTARY CAMERA PATTERN ===
{scene_type_guidance}

=== HARD WORD BUDGET: {PROMPT_MIN_WORDS}-{PROMPT_MAX_WORDS} WORDS PER PROMPT ===

=== DO NOT ===
- Repeat concepts in different words (no "innovation slows" 5 ways)
- Explain economics (models don't understand "geographic mobility hit record lows")
- Use vague abstractions ("mobility paralysis", "economic stagnation")
- Include keyword spam at the end
- Use double quotes inside prompts (use single quotes)

=== DO ===
- State each visual concept ONCE with specific imagery
- Use concrete nouns: "dollar sign barriers", "crumbling bridge", "glowing neon skyline"
- Include specific colors: "warm amber", "cold blue-white", "muted earth tones with red warning accents"
- Describe spatial relationships: "left side dim, right side glowing"
- Include texture words: "paper-cut", "layered", "brushstroke", "film grain"

=== EXAMPLE GOOD PROMPTS ===

Example 1 (WIDE ESTABLISHING - Overhead Map):
"{EXAMPLE_PROMPTS[0][:300]}..."

Example 2 (MEDIUM HUMAN STORY - Side View):
"{EXAMPLE_PROMPTS[1][:300]}..."

Example 3 (DATA LANDSCAPE):
"{EXAMPLE_PROMPTS[3][:300]}..."

=== OUTPUT FORMAT (JSON only, no markdown) ===
{{
  "segments": [
    {{
      "text": "The narration text for this segment...",
      "image_prompt": "[SHOT_PREFIX] [scene composition], [focal subject], [environmental storytelling], {STYLE_ENGINE}, [lighting]"
    }}
  ]
}}"""

        prompt = f"""Segment this scene narration into {target_count} visual concepts:

SCENE TEXT:
{scene_text}

REQUIRED SHOT ASSIGNMENTS:
{scene_type_guidance}

Return JSON with segments array. Each segment has text and image_prompt.
REMEMBER: {PROMPT_MIN_WORDS}-{PROMPT_MAX_WORDS} words per prompt. Every word must describe something VISUAL."""

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

        # Validate and log word counts
        for i, seg in enumerate(segments):
            prompt_text = seg.get("image_prompt", "")
            word_count = len(prompt_text.split())
            if word_count < PROMPT_MIN_WORDS:
                print(f"      ⚠️ Segment {i+1} prompt too short: {word_count} words (min {PROMPT_MIN_WORDS})")
            elif word_count > PROMPT_MAX_WORDS:
                print(f"      ⚠️ Segment {i+1} prompt too long: {word_count} words (max {PROMPT_MAX_WORDS})")

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
        from .style_engine import SceneType, get_camera_motion, get_random_atmospheric_motion

        # Determine camera motion based on scene type
        camera_motion = "Slow push-in"  # default
        if scene_type:
            try:
                st = SceneType(scene_type.lower()) if isinstance(scene_type, str) else scene_type
                camera_motion = get_camera_motion(st, is_hero_shot)
            except (ValueError, KeyError):
                pass

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
5. The art style is lo-fi paper-cut collage. All motion should feel like animated illustrations:
   - Paper layers shifting with parallax
   - Figures swaying softly
   - Gentle, dreamlike movement
{hero_instruction}

CAMERA MOVEMENT FOR THIS SHOT (use this or adapt slightly):
{camera_motion}

MOTION VOCABULARY - USE ONLY THESE TYPES:

Figures/People:
- "figure gently turns head toward..."
- "silhouette slowly reaches hand forward"
- "paper-cut figures subtly sway in place"
- "character's hair and clothes drift as if underwater"

Environmental:
- "paper layers shift with gentle parallax depth"
- "leaves and particles drift slowly across frame"
- "smoke or fog wisps curl through the scene"
- "light beams slowly sweep across the surface"

Data/Abstract:
- "flow lines slowly pulse and travel along their paths"
- "numbers and text elements gently float upward"
- "graph lines draw themselves left to right"
- "cracks slowly spread across the surface"

Atmospheric (include at least one):
- "warm light gently pulses like breathing"
- "dust particles float through light beams"
- "subtle film grain flickers"
- "shadows slowly shift as if clouds passing overhead"

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

Generate a {word_limit}-word-max motion prompt:"""

        response = await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            model="claude-sonnet-4-5-20250929",
            max_tokens=200,
        )
        return response.strip()
