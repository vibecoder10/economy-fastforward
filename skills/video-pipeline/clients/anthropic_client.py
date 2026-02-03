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
        min_segment_duration: float = 6.0,
        max_segments_per_scene: int = 10,
        actual_scene_duration: float = None,
    ) -> list[dict]:
        """Generate image prompts based on semantic visual segments.

        This is the smart segmentation approach that:
        1. Groups sentences by visual concept (not mechanical splitting)
        2. Only creates new images when the visual FUNDAMENTALLY shifts
        3. Enforces duration range (6-10s) for AI video generation
        4. Limits to max 10 segments per ~70 second scene
        5. Uses actual voice duration when available for accurate timing

        Args:
            scene_number: The scene number
            scene_text: Full scene narration text
            video_title: Title of the video
            max_segment_duration: Maximum seconds per segment (default 10s)
            min_segment_duration: Minimum seconds per segment (default 6s)
            max_segments_per_scene: Maximum segments allowed (default 10)
            actual_scene_duration: Actual voice duration in seconds (if available)

        Returns:
            List of dicts with:
                - segment_index: int
                - segment_text: str (combined sentences)
                - duration_seconds: float (6-10s range)
                - cumulative_start: float
                - image_prompt: str
                - visual_concept: str (description of why this is a segment)
        """
        # Step 1: Have Claude analyze and segment the scene semantically
        segments = await self._analyze_visual_segments(
            scene_text,
            max_duration=max_segment_duration,
            min_duration=min_segment_duration,
            max_segments=max_segments_per_scene,
            actual_total_duration=actual_scene_duration,
        )

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
        min_duration: float = 6.0,
        max_segments: int = 10,
        actual_total_duration: float = None,
    ) -> list[dict]:
        """Use Claude to semantically segment a scene into visual concepts.

        Returns list of segments, each with:
            - text: the narration for this segment
            - visual_concept: why this is a distinct visual
            - duration: duration in seconds (6-10s range)
        """
        from clients.sentence_utils import estimate_sentence_duration

        # Use actual duration if available, otherwise estimate ~70s
        scene_duration = actual_total_duration if actual_total_duration else 70.0
        ideal_segments = max(3, min(max_segments, int(scene_duration / 8)))  # Aim for ~8s per segment

        system_prompt = f"""You are an expert video editor segmenting narration for AI-animated documentary videos.

YOUR TASK: Group the scene narration into VISUAL CONCEPT SEGMENTS (NOT sentence-by-sentence splitting).

SCENE INFO:
- Total scene duration: {scene_duration:.1f} seconds
- Target segments: {ideal_segments} (aim for {min_duration}-{max_duration}s each)

CRITICAL RULES:
1. Create {ideal_segments} segments (MAX {max_segments}, MIN 3)
2. Each segment MUST be {min_duration}-{max_duration} seconds (HARD requirement for AI video generation)
3. Group multiple sentences together if they share the SAME visual concept
4. Only create a NEW segment when the visual FUNDAMENTALLY changes
5. Short rhetorical phrases = ONE segment, not multiple

WHAT CONSTITUTES A VISUAL SHIFT (create new segment):
- New metaphor or analogy being introduced
- Shift from abstract to concrete (or vice versa)
- New historical example or time period
- New character/entity being discussed
- Dramatic reveal or conclusion

WHAT DOES NOT CONSTITUTE A VISUAL SHIFT (keep in same segment):
- Continuing to explain the same concept
- Adding details to current metaphor
- Rhetorical emphasis phrases ("Different decade. Different industry." = SAME segment)
- Cause and effect of same topic

DURATION CALCULATION:
- Speaking rate: 173 words per minute
- Formula: (word_count / 173) * 60 = seconds
- Segment durations should sum to approximately {scene_duration:.0f} seconds

OUTPUT FORMAT (JSON only, no markdown):
{{
  "segments": [
    {{
      "sentences": ["First sentence.", "Second sentence.", "Third sentence."],
      "visual_concept": "Brief description of the core visual",
      "estimated_duration": 8.5
    }}
  ]
}}

Remember: Fewer, longer segments = better video. Target {ideal_segments} segments."""

        prompt = f"""Segment this {scene_duration:.0f} second scene into {ideal_segments} visual concept groups:

SCENE TEXT:
{scene_text}

Return JSON. Each segment should be {min_duration}-{max_duration} seconds. Total should equal ~{scene_duration:.0f}s."""

        response = await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            model="claude-sonnet-4-5-20250929",
            max_tokens=2000,
        )

        # Parse the response
        import json
        clean_response = response.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_response)

        # Convert to our format and calculate proportional durations
        results = []
        raw_segments = data.get("segments", [])

        # Calculate word-based proportions to distribute actual duration
        total_words = 0
        for seg in raw_segments:
            text = " ".join(seg.get("sentences", []))
            total_words += len(text.split())

        for seg in raw_segments:
            text = " ".join(seg.get("sentences", []))
            word_count = len(text.split())

            if actual_total_duration and total_words > 0:
                # Distribute actual duration proportionally by word count
                proportion = word_count / total_words
                duration = actual_total_duration * proportion
            else:
                # Fall back to estimate
                duration = estimate_sentence_duration(text)

            # Enforce min/max duration
            if duration < min_duration:
                duration = min_duration
            elif duration > max_duration:
                duration = max_duration

            results.append({
                "text": text,
                "visual_concept": seg.get("visual_concept", ""),
                "duration": round(duration, 1),
            })

        # If we still have too many segments, merge the shortest ones
        while len(results) > max_segments and len(results) > 1:
            # Find the shortest segment
            min_idx = min(range(len(results)), key=lambda i: results[i]["duration"])

            # Merge with adjacent segment (prefer next, fallback to previous)
            if min_idx < len(results) - 1:
                merge_idx = min_idx + 1
            else:
                merge_idx = min_idx - 1

            # Merge
            merged_text = results[min_idx]["text"] + " " + results[merge_idx]["text"]
            merged_concept = results[min_idx]["visual_concept"] + " (merged)"
            merged_duration = min(results[min_idx]["duration"] + results[merge_idx]["duration"], max_duration)

            # Remove both and insert merged
            results[min(min_idx, merge_idx)] = {
                "text": merged_text,
                "visual_concept": merged_concept,
                "duration": merged_duration,
            }
            results.pop(max(min_idx, merge_idx))

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

Generate a single prompt that visually represents this segment's core concept."""

        response = await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            model="claude-sonnet-4-5-20250929",
            max_tokens=500,
        )

        return response.strip()

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
