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

    async def generate_video_prompt(self, image_prompt: str) -> str:
        """Generate a concise motion prompt based on the image description.
        
        Args:
            image_prompt: The prompt used to generate the static image.
            
        Returns:
            A short motion prompt (e.g., "slow zoom on the red smoke, dust particles floating").
        """
        system_prompt = """You are an expert motion prompt engineer for AI video generation (Seed Dance / Kling).
Your task is to take a detailed IMAGE PROMPT and convert it into a CONCISE (max 15 words) MOTION PROMPT.

GUIDELINES:
1. Identify the key visual elements in the prompt (e.g. "rain", "smoke", "crowd", "light").
2. Assign subtle, cinematic movement to them.
3. Add camera movement (Slow zoom, Pan).
4. Do NOT describe the scene from scratch. Focus on MOVING what is already there.

Example Input: "Atmospheric lo-fi... Anchor A: Digital Void. A glowing red pill crumbling into dust... darker background."
Example Output: "Slow zoom on crumbling pill, dust particles floating upwards, cinematic lighting."
"""
        
        prompt = f"Image Prompt: {image_prompt}\n\nGenerate motion prompt:"
        
        # Use a faster model for simple prompts
        response = await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            model="claude-sonnet-4-5-20250929", 
        )
        return response.strip()
