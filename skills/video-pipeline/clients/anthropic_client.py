"""Anthropic Claude API client for script and prompt generation."""

import os
from anthropic import Anthropic
from typing import Optional


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
        """Generate 6 image prompts for a scene.
        
        Uses the Image Prompt Agent from the n8n workflow.
        """
        system_prompt = """You are an expert JSON image prompt creator for a faceless YouTube channel.

STRICT STYLE GUIDELINES:
The style is "Cinematic Lofi Digital".
Your output MUST start with "Atmospheric lo-fi 2D digital illustration, 16:9." and strictly follow the structure below.

VISUAL ANCHOR PROTOCOL:
Frame every prompt using one of these "Anchor Settings":
* Anchor A: "The Digital Void" – Abstract concepts in dark space.
* Anchor B: "The Urban Exterior" – Futuristic cityscapes at twilight.
* Anchor C: "The Data Landscape" – Physical representations of data in deserts.
* Anchor D: "The Macro Lens" – Symbolic objects in close-up.

REQUIRED PROMPT STRUCTURE (Strict Adherence):
"Atmospheric lo-fi 2D digital illustration, 16:9. Anchor [Letter]: [Anchor Name]. [Primary Visual Description]. [Secondary Details]. Text '[TEXT]' appears in [Color/Style]. The [Concept Name] visualization. Hand-drawn [Specific Elements], soft painterly [Texture/Contrast], [Color A] versus [Color B], cinematic [Mood]."

FEW-SHOT EXAMPLES (Use these as style guides for tone and structure):

Example 1:
"Atmospheric lo-fi 2D digital illustration, 16:9. Anchor A: Digital Void. Two parallel paths diverge in space. Upper path shows degraded useless pills crumbling into dust labeled 'DONE WRONG: MEDICALLY USELESS' in failure gray. Lower path shows properly stored medications glowing with maintained potency labeled 'KNOWLEDGE WITH PROPER EXECUTION' in mastery gold. Chess pieces symbolize strategic thinking. The execution divide visualization. Hand-drawn gambling with chemically unstable medications, soft painterly proper execution versus worthless knowledge, degradation grays and useless pill dust versus execution mastery golds and maintained potency greens, atmospheric the difference between success and failure, the strategic mastery mood."

Example 2 (The Memory Callback):
"Atmospheric lo-fi 2D digital illustration, 16:9. Anchor B: Urban Exterior. Silhouette of mother holding child's hand stands at crossroads where currency bills swirl like falling leaves around them. Behind her, fading cityscape dissolves into mist with broken promises text floating away. Wedding ring glows faintly in her palm. Text 'REMEMBER HER' appears in haunting amber. The memory callback visualization. Hand-drawn Venezuelan collapse story returns, soft painterly she never saw it coming, worthless currency grays and dissolving cityscape blues versus wedding ring sacrifice golds and mother's silhouette blacks, cinematic nobody does see it coming, the haunting reminder mood."

Example 3 (The Pattern Recognition):
"Atmospheric lo-fi 2D digital illustration, 16:9. Anchor C: Data Landscape. Massive domino chain of economic systems toppling through landscape. Each domino labeled with failed currencies, broken supply chains, vanished permanent systems. Text 'THE QUESTION WAS NEVER WHETHER' appears in inevitable gray. Lightning cracks illuminate pattern of historical collapses repeating. The pattern recognition visualization. Hand-drawn currencies fail supply chains break systems vanish overnight, soft painterly this is not pessimism its pattern recognition, domino toppling grays and system collapse reds versus lightning pattern illumination whites and historical repetition golds, atmospheric economic crisis could happen here, the inevitable pattern mood."

OUTPUT FORMAT:
{
  "scene": <scene_number>,
  "prompts": [
    "prompt 1...",
    "prompt 2...",
    "prompt 3...",
    "prompt 4...",
    "prompt 5...",
    "prompt 6..."
  ]
}

IMPORTANT RULES:
1. Do not use double quotes (") inside the prompt text. Use single quotes for labels.
2. Every prompt must start with "Atmospheric lo-fi 2D digital illustration, 16:9."
3. Include the "The [Name] visualization" sentence.
4. Include "Hand-drawn [elements]" and "soft painterly [elements]" descriptors.
5. Contrast "Color A versus Color B" in the description.
"""
        
        prompt = f"""Take the scene provided and make 6 JSON image prompts for this scene.

***
Video Title: {video_title}
Current Scene Number: {scene_number}
Current Scene Text: {scene_text}
***

Generate exactly 6 unique image prompts that build off each other to make a cohesive storyline. Follow the STRICT STYLE GUIDELINES."""
        
        response = await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            model="claude-sonnet-4-5-20250929",
        )
        
        import json
        clean_response = response.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_response)
        return data.get("prompts", [])
    
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
        """Generate a single image prompt for a specific sentence.
        
        This creates visually coherent, sentence-aligned image prompts.
        
        Args:
            sentence_text: The specific sentence to illustrate
            sentence_index: Position in scene (1-based)
            total_sentences: Total sentences in scene
            scene_number: The scene number
            video_title: Title of the video
            previous_prompt: The previous image prompt (for visual continuity)
            
        Returns:
            A single image prompt string
        """
        system_prompt = """You are an expert image prompt creator for a faceless YouTube channel.

STRICT STYLE GUIDELINES:
The style is "Cinematic Lofi Digital".
Your output MUST start with "Atmospheric lo-fi 2D digital illustration, 16:9."

VISUAL ANCHOR PROTOCOL:
Frame using one of these "Anchor Settings":
* Anchor A: "The Digital Void" – Abstract concepts in dark space.
* Anchor B: "The Urban Exterior" – Futuristic cityscapes at twilight.
* Anchor C: "The Data Landscape" – Physical representations of data in deserts.
* Anchor D: "The Macro Lens" – Symbolic objects in close-up.

REQUIRED PROMPT STRUCTURE:
"Atmospheric lo-fi 2D digital illustration, 16:9. Anchor [Letter]: [Anchor Name]. [Primary Visual Description]. [Secondary Details]. Text '[TEXT]' appears in [Color/Style]. The [Concept Name] visualization. Hand-drawn [elements], soft painterly [contrast], [Color A] versus [Color B], cinematic [mood]."

IMPORTANT:
- This prompt illustrates ONE SPECIFIC SENTENCE
- The visual must directly represent what the sentence is saying
- Maintain visual continuity with the previous image if provided
- Do not use double quotes inside the prompt, use single quotes

OUTPUT: Return ONLY the prompt string, no JSON, no explanation."""

        continuity_note = ""
        if previous_prompt:
            continuity_note = f"\n\nPREVIOUS IMAGE (maintain visual continuity):\n{previous_prompt[:200]}..."

        prompt = f"""Create ONE image prompt for this specific sentence:

VIDEO: {video_title}
SCENE: {scene_number}
POSITION: Sentence {sentence_index} of {total_sentences}

SENTENCE TO ILLUSTRATE:
"{sentence_text}"
{continuity_note}

Generate a single prompt that visually represents THIS EXACT SENTENCE."""

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
        """Generate an image prompt for a semantic segment."""
        CHANNEL_STYLE = """Atmospheric lo-fi 2D digital illustration style. Hand-drawn aesthetic with soft painterly textures.
Dark moody backgrounds with glowing accent elements. Muted color palette with strategic bright highlights.
16:9 aspect ratio composition. Cinematic documentary feel."""

        system_prompt = f"""You are a visual director segmenting narration into image concepts.
Each concept will become ONE image shown while that portion of the narration plays.

REQUIRED VISUAL STYLE FOR ALL IMAGES:
{CHANNEL_STYLE}

Every image_prompt you generate MUST start with "Atmospheric lo-fi 2D digital illustration, 16:9." and incorporate the hand-drawn, painterly aesthetic described above.

VISUAL ANCHOR PROTOCOL:
Frame using one of these "Anchor Settings":
* Anchor A: "The Digital Void" – Abstract concepts in dark space.
* Anchor B: "The Urban Exterior" – Futuristic cityscapes at twilight.
* Anchor C: "The Data Landscape" – Physical representations of data in deserts.
* Anchor D: "The Macro Lens" – Symbolic objects in close-up.

REQUIRED PROMPT STRUCTURE:
"Atmospheric lo-fi 2D digital illustration, 16:9. Anchor [Letter]: [Anchor Name]. [Primary Visual Description]. [Secondary Details]. Text '[TEXT]' appears in [Color/Style]. The [Concept Name] visualization. Hand-drawn [elements], soft painterly [contrast], [Color A] versus [Color B], cinematic [mood]."

IMPORTANT:
- This prompt illustrates a SEMANTIC SEGMENT (may contain multiple sentences)
- The visual must represent the CORE CONCEPT being explained
- Maintain visual continuity with the previous image if provided
- Do not use double quotes inside the prompt, use single quotes

OUTPUT: Return ONLY the prompt string, no JSON, no explanation."""

        continuity_note = ""
        if previous_prompt:
            continuity_note = f"\n\nPREVIOUS IMAGE (maintain visual continuity):\n{previous_prompt[:200]}..."

        prompt = f"""Create ONE image prompt for this narrative segment:

VIDEO: {video_title}
SCENE: {scene_number}
SEGMENT: {segment_index} of {total_segments}

VISUAL CONCEPT: {visual_concept}

NARRATION TEXT:
"{segment_text}"
{continuity_note}

Generate a single prompt that visually represents this segment's core concept.

REMINDER: Start with 'Atmospheric lo-fi 2D digital illustration, 16:9.' then describe the scene with hand-drawn aesthetic, soft painterly textures, moody lighting, and specific color palette. 100+ words."""

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
    ) -> list[dict]:
        """Segment scene text into visual concepts based on duration targets.

        This is the duration-based approach that:
        1. Divides scene text into target_count segments (within min/max range)
        2. Each segment represents a distinct visual concept
        3. Returns text chunks and image prompts for each

        Args:
            scene_text: Full scene narration text
            target_count: Target number of segments
            min_count: Minimum allowed segments
            max_count: Maximum allowed segments

        Returns:
            List of dicts with:
                - text: str (the narration text for this segment)
                - image_prompt: str (the generated image prompt)
        """
        CHANNEL_STYLE = """Atmospheric lo-fi 2D digital illustration style. Hand-drawn aesthetic with soft painterly textures.
Dark moody backgrounds with glowing accent elements. Muted color palette with strategic bright highlights.
16:9 aspect ratio composition. Cinematic documentary feel."""

        system_prompt = f"""You are an expert video editor and image prompt creator for a faceless YouTube documentary channel.

YOUR TASK: Divide this scene narration into {target_count} visual segments (minimum {min_count}, maximum {max_count}).

CRITICAL DURATION RULE:
- Each segment MUST be roughly EQUAL in word count
- Target: Each segment should have approximately {words_per_segment} words (±5 words)
- This ensures each image displays for 6-10 seconds (not more, not less)
- DO NOT create segments with vastly different lengths - no segment should exceed {int(words_per_segment * 1.3)} words

SEGMENTATION RULES:
1. Each segment should represent a DISTINCT visual concept
2. Keep sentences together when they describe the same visual
3. Create natural breakpoints where the imagery would need to change
4. BALANCE word counts across all segments - no segment should be 2x longer than another

REQUIRED VISUAL STYLE FOR ALL IMAGE PROMPTS:
{CHANNEL_STYLE}

VISUAL ANCHOR PROTOCOL:
Frame using one of these "Anchor Settings":
* Anchor A: "The Digital Void" – Abstract concepts in dark space.
* Anchor B: "The Urban Exterior" – Futuristic cityscapes at twilight.
* Anchor C: "The Data Landscape" – Physical representations of data in deserts.
* Anchor D: "The Macro Lens" – Symbolic objects in close-up.

REQUIRED PROMPT STRUCTURE (MUST BE 80-120 WORDS):
"Atmospheric lo-fi 2D digital illustration, 16:9. Anchor [Letter]: [Anchor Name]. [SPECIFIC VISUAL METAPHOR - name 2-3 concrete objects that symbolize the concept, describe how they interact in the scene]. [SECONDARY DETAILS - add atmospheric elements, lighting, movement]. Text '[KEY PHRASE FROM NARRATION]' appears in [thematic color] [style]. The [concept name] visualization. Hand-drawn [FULL DESCRIPTIVE PHRASE about what's being drawn, not just nouns], soft painterly [FULL PHRASE describing the artistic contrast], [thematic color name] [what it represents] versus [contrasting thematic color] [what it represents], cinematic [FULL PHRASE capturing the key insight or emotional beat], the [mood name] mood."

EXAMPLE OF GOOD PROMPT (follow this level of detail):
"Atmospheric lo-fi 2D digital illustration, 16:9. Anchor C: Data Landscape. Roblox blocks, TikTok algorithms, Discord servers materialize as stepping stones across economic chasm. Each childhood activity glows revealing hidden preparation for future economy. Text 'IT WAS ALL PREPARATION' appears in revelation gold. Pattern connects seemingly unrelated skills into coherent training path. The hidden training visualization. Hand-drawn childhood games revealing economic preparation, soft painterly every algorithm mastered every server managed, childhood play grays and meaningless activity blacks versus preparation revelation golds and skill connection whites, cinematic they've been training for this economy, the preparation revelation mood."

OUTPUT FORMAT (JSON only, no markdown):
{{
  "segments": [
    {{
      "text": "The narration text for this segment...",
      "image_prompt": "Atmospheric lo-fi 2D digital illustration, 16:9. Anchor A: Digital Void. [rest of prompt]..."
    }},
    {{
      "text": "Next segment's narration...",
      "image_prompt": "Atmospheric lo-fi 2D digital illustration, 16:9. Anchor B: Urban Exterior. [rest of prompt]..."
    }}
  ]
}}

IMPORTANT:
- Split into exactly {target_count} segments (between {min_count} and {max_count})
- Each image_prompt MUST start with "Atmospheric lo-fi 2D digital illustration, 16:9."
- Do not use double quotes inside prompts, use single quotes
- Maintain visual continuity between segments"""

        prompt = f"""Segment this scene narration into {target_count} visual concepts:

SCENE TEXT:
{scene_text}

Return JSON with segments array. Each segment has text and image_prompt."""

        response = await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            model="claude-sonnet-4-5-20250929",
            max_tokens=3000,
        )

        # Parse the response
        import json
        clean_response = response.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_response)

        return data.get("segments", [])

    async def generate_video_prompt(
        self,
        image_prompt: str,
        sentence_text: str = "",
    ) -> str:
        """Generate a concise motion prompt based on the image and narration.

        Args:
            image_prompt: The prompt used to generate the static image.
            sentence_text: The narration being spoken during this image (for alignment).

        Returns:
            A short motion prompt (e.g., "slow zoom on the red smoke, dust particles floating").
        """
        system_prompt = """You are an expert motion prompt engineer for AI video generation (Seed Dance / Kling / Grok Imagine).
Your task is to create a CONCISE (max 15 words) MOTION PROMPT that:
1. Animates the key visual elements in the image
2. ALIGNS with the emotional tone and content of what's being narrated

GUIDELINES:
1. Read both the IMAGE PROMPT and the NARRATION TEXT.
2. Identify key visual elements (e.g. "rain", "smoke", "crowd", "light", "text").
3. Choose motion that MATCHES the narration mood (tension = slow zoom in, revelation = camera pan, etc.)
4. Add subtle cinematic movement - don't overanimate.
5. Do NOT describe the scene from scratch. Focus on MOVING what is already there.

Example:
- Image: "Digital void with crumbling red pill..."
- Narration: "The answer should terrify every investor..."
- Motion: "Slow dramatic zoom on crumbling pill, dust particles floating upwards, ominous lighting shift."
"""

        narration_context = ""
        if sentence_text:
            narration_context = f"\n\nNarration being spoken: \"{sentence_text}\""

        prompt = f"Image Prompt: {image_prompt}{narration_context}\n\nGenerate motion prompt:"
        
        # Use a faster model for simple prompts
        response = await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            model="claude-sonnet-4-5-20250929", 
        )
        return response.strip()
