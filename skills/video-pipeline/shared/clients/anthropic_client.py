"""Anthropic Claude API client for script and prompt generation."""

from __future__ import annotations

import os
import re
from anthropic import Anthropic
from typing import Optional, List, Dict, Tuple

from orchestrator.pipeline_constants import Models


def _get_profile():
    """Return the active visual profile, or None."""
    try:
        from shared.profiles.visual import load_profile
        return load_profile()
    except Exception:
        return None

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

# Thumbnail System v3 - Map + Strategic Verdict (default) with editorial illustration fallback
ANTHROPIC_THUMBNAIL_SYSTEM_PROMPT = """You are the thumbnail prompt engineer for Economy FastForward, \
a geopolitical/economics YouTube channel.

Your job: Generate a detailed image generation prompt for Nano Banana Pro that produces \
a click-worthy, on-brand thumbnail.

DETERMINE TEMPLATE FIRST:
- If the topic is about a COUNTRY, REGION, TRADE ROUTE, MILITARY ACTION, or GEOPOLITICAL EVENT → use MAP TEMPLATE (default)
- If the topic is about FINANCE, TECH, CORPORATE, or has no clear geographic element → use EDITORIAL ILLUSTRATION TEMPLATE (fallback)

=== MAP TEMPLATE (DEFAULT — for all geopolitical content) ===

Bright editorial illustration of a top-down map of [REGION], \
clean cartographic style with warm tan landmasses and light blue water, \
[ONE strategic overlay: thick red barrier/arrows/zone marking], \
[relevant icons: ships/military assets/infrastructure clustered near key area], \
bold white block capital text reading "[2-WORD VERDICT]" in the bottom-left \
corner at roughly 35% of frame width with thick black outline and heavy \
drop shadow, country name labels in smaller black text on landmasses, \
the map geography should be clearly visible and not obscured by text, \
clean minimal composition, no people no faces no figures, \
must be readable at 160x90 pixels, 16:9 aspect ratio.

COMPOSITION RULES (MAP):
- Map is the PRIMARY visual element (60%+ of frame)
- ONE strategic overlay only (red barrier, arrows, or zone)
- Text in bottom-left corner, ~35% of frame width
- Country labels in small black text on landmasses
- Maximum 3-4 colors total (tan, blue, red, white/yellow text)
- No people, no faces, no comic illustrations
- Must read at phone thumbnail size (160x90px)

=== EDITORIAL ILLUSTRATION TEMPLATE (FALLBACK — non-geographic topics) ===

Bright editorial illustration, 16:9 landscape aspect ratio, \
high contrast, high saturation, thick black outlines on all figures, \
flat cel-shaded coloring, bold composition.

- ONE central visual metaphor for the topic (system, machine, institution)
- Clean background with ONE dominant mood color
- Bold white block capital text reading "[2-WORD VERDICT]" \
  with thick black outline and heavy drop shadow
- No faces, no figures when possible — focus on systems and symbols
- Must be readable at 160x90 pixels

=== THUMBNAIL TEXT RULES (BOTH TEMPLATES) ===

Thumbnail text is a 2-word STRATEGIC VERDICT stamped on the image.

RULES:
1. EXACTLY 2 words. Maximum 3 words only if absolutely necessary.
2. No "YOUR" or "YOU" language — ever.
3. Must be a JUDGMENT about the situation, not a description or consequence.
4. Think: what would a general say in a briefing room after seeing the evidence?
5. White or yellow bold text with thick black outline.

GOOD EXAMPLES: CHOKE POINT, PROXY WAR, DRONE WALL, ART OF WAR, \
DESIGNED TO FAIL, EXITS LOCKED, MISSILE STRATEGY, FORCED WAR, POWER VACUUM

BAD EXAMPLES (DO NOT USE): YOUR MONEY GETS LOCKED, $9 GAS IS COMING, \
YOUR AI JUST GOT WEAPONIZED, YOUR BANK IS NEXT

FRAMEWORK-TO-VERDICT MAPPING (use when framework is known):
- Thucydides Trap → FORCED WAR, COLLISION COURSE, NO EXIT
- Machiavelli → POWER GRAB, RIGGED GAME, PUPPET MASTER
- Antifragile → HOUSE OF CARDS, ONE SPARK, FRAGILE
- Game Theory → TRAPPED, NO GOOD MOVES, LOSE-LOSE
- Sun Tzu → INVISIBLE ARMY, DECOY, AMBUSH
- Grand Chessboard → CHECKMATE, GRAND PLAY, CHOKE POINT
- Kindleberger → POWER VACUUM, NO LEADER, LEADERLESS
- Schelling → BLUFF CALLED, RED LINE, ULTIMATUM
- Collective Action → ROTTING EMPIRE, PARALYSIS, DEAD WEIGHT
- Soft Power → SILENT CONQUEST, SOFT KILL, INFLUENCE WAR

OUTPUT FORMAT:
Return ONLY the image generation prompt. No explanations, no JSON, no labels. \
The prompt should be 100-150 words."""


# Kie.ai's Claude gateway only knows undated model aliases
# (claude-sonnet-4-5, not claude-sonnet-4-5-20250929).
_DATED_MODEL_RE = re.compile(r"^(claude-[a-z]+-\d(?:-\d)?)-\d{8}$")


class AnthropicClient:
    """Client for Anthropic Claude API.

    When ANTHROPIC_BASE_URL is set (e.g. https://api.kie.ai/claude — Kie.ai's
    Anthropic-compatible gateway), the client switches to gateway mode:
    Bearer auth instead of x-api-key, a custom User-Agent (Kie's WAF blocks
    the SDK's default UA), undated model aliases, and server-side tools
    (web_search) stripped because the gateway doesn't execute them.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not found in environment")
        base_url = os.getenv("ANTHROPIC_BASE_URL")
        self._gateway_mode = bool(base_url)
        if base_url:
            # max_retries=4: Kie's gateway throws intermittent 500s under
            # sustained load (observed killing a 5-minute research run).
            self.client = Anthropic(
                auth_token=self.api_key,
                base_url=base_url,
                default_headers={"User-Agent": "StoryEngine/1.0"},
                max_retries=4,
            )
        else:
            self.client = Anthropic(api_key=self.api_key)

    def _normalize_model(self, model: str) -> str:
        """Map dated model ids to undated aliases in gateway mode."""
        if not self._gateway_mode:
            return model
        match = _DATED_MODEL_RE.match(model or "")
        return match.group(1) if match else model

    def _filter_tools(self, tools):
        """Drop Anthropic server-side tools (web_search) in gateway mode —
        the gateway returns them unexecuted, which yields empty text."""
        if not self._gateway_mode or not tools:
            return tools
        kept = [t for t in tools if not str(t.get("type", "")).startswith("web_search")]
        if len(kept) != len(tools):
            print("    ⚠️ Gateway mode: dropped server-side web_search tool (gateway doesn't execute it)")
        return kept or None
    
    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        model: str = Models.CLAUDE_SONNET,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        tools: list = None,
    ) -> str:
        """Generate a completion using Claude.

        Args:
            prompt: The user prompt
            system_prompt: System instructions
            model: Model to use (Models.CLAUDE_SONNET, Models.CLAUDE_OPUS)
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
            "model": self._normalize_model(model),
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        tools = self._filter_tools(tools)
        if tools:
            kwargs["tools"] = tools

        def _create():
            if self._gateway_mode:
                # Kie's gateway 500s when a non-streaming response takes longer
                # than ~110s to generate (verified live: every 16k-token research
                # call failed; the same call streamed completes fine). Stream
                # and accumulate so long generations survive.
                with self.client.messages.stream(**kwargs) as stream:
                    return stream.get_final_message()
            return self.client.messages.create(**kwargs)

        async def _create_with_5xx_retry():
            """The SDK already retries transient statuses internally; this outer
            loop covers longer upstream blips (Kie 500s can persist past the
            SDK's quick backoff) without failing a multi-minute pipeline stage."""
            import anthropic as _anthropic
            last = None
            for attempt, delay in enumerate((0, 15, 45)):
                if delay:
                    print(f"    ⚠️ Upstream 5xx — retrying in {delay}s (attempt {attempt + 1}/3)...", flush=True)
                    await _asyncio.sleep(delay)
                try:
                    return await _asyncio.to_thread(_create)
                except _anthropic.APIStatusError as e:
                    if e.status_code < 500:
                        raise
                    last = e
                except _anthropic.APIConnectionError as e:
                    last = e
            raise last

        response = await _create_with_5xx_retry()

        text = self._extract_text(response)
        if text:
            return text

        # Empty content — retry once after a short delay
        print("    ⚠️ API returned empty content, retrying in 2s...")
        await _asyncio.sleep(2)
        response = await _create_with_5xx_retry()

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
            model=Models.CLAUDE_OPUS,  # Use Opus for beat sheet
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

CRITICAL — FACTUAL GROUNDING:
- Every specific claim (names, numbers, dates, events, tactics, quotes) MUST \
come from the scene beat provided. Do NOT invent facts, technical details, \
or events not present in the source material.
- You may describe events cinematically, but you MUST NOT invent WHAT happened. \
Only dramatize HOW sourced events unfolded.
- Never fabricate technical details (weapon systems, cyber attacks, operational \
specifics) to fill narrative gaps. Use hedging language ("analysts believe", \
"evidence suggests") instead of presenting speculation as fact.
- Do not invent quotes, statistics, or specific military/political operations \
not present in the scene beat.

INSTRUCTION:
Write the script for the scene provided. Return ONLY the narration text."""
        
        prompt = f"""Write the spoken narration for SCENE {scene_number} ONLY.

CONTEXT:
Video Title: "{video_title}"
Current Scene Goal: "{scene_beat}\""""
        
        return await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            model=Models.CLAUDE_OPUS,
        )
    
    async def generate_image_prompts(
        self,
        scene_number: int,
        scene_text: str,
        video_title: str,
        research_payload: str = "",
    ) -> list[str]:
        """Generate 6 image prompts for a scene.

        When a visual profile is active, reads the system prompt from the
        profile's scene_description config. Falls back to the holographic
        intelligence display system when no profile or holographic profile.

        Args:
            scene_number: The scene number in the video
            scene_text: The narration text for this scene
            video_title: The video title
            research_payload: Optional research payload JSON for extracting real data points
        """
        # Check active visual profile
        profile = _get_profile()
        is_holographic = profile is None or profile.profile_id == "holographic_hud"

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

        if not is_holographic and profile and profile.scene_description.system_prompt:
            # Profile-driven system prompt
            profile_suffix = profile.style_system.style_suffix or ""
            system_prompt = f"""{profile.scene_description.system_prompt}

=== PROMPT ARCHITECTURE ({PROMPT_MIN_WORDS}-{PROMPT_MAX_WORDS} words) ===

[STYLE PREFIX] + [SCENE CONTENT description] + [STYLE SUFFIX]

Style prefix: "{profile.style_system.style_prefix}"
Style suffix: "{profile_suffix}"

=== OUTPUT FORMAT (JSON only, no markdown) ===
{{
  "scene": {scene_number},
  "prompts": [
    {{
      "content_type": "scene",
      "display_format": "medium",
      "color_mood": "neutral",
      "prompt": "the full prompt text..."
    }}
  ]
}}"""
        else:
            # Holographic default system prompt
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

=== ABSOLUTE RULE — NO HUMANS IN ANY FORM ===
Never describe people, operators, officers, analysts, figures, silhouettes, hands, or any human presence in image prompts. Not even as "holographic" or "wireframe" humans.
Instead of "officers at consoles" → "unmanned consoles with active displays"
Instead of "analyst workstation" → "workstation with open data feeds"
Instead of "commander issues orders" → "command terminal with priority alerts flashing"
The room is ALWAYS empty of people. Equipment operates autonomously.

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

        if not is_holographic and profile:
            prompt = f"""Create 6 image prompts for this scene using the {profile.profile_name} visual style:

Video Title: {video_title}
Scene Number: {scene_number}

SCENE TEXT:
{scene_text}
{research_context}

For each prompt:
1. Analyze the scene text for visual storytelling opportunities
2. Write a {PROMPT_MIN_WORDS}-{PROMPT_MAX_WORDS} word prompt
3. Start each prompt with the style prefix and end with the style suffix
4. Include visual details that serve the narrative

Generate exactly 6 prompts."""
        else:
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
            model=Models.CLAUDE_SONNET,
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

=== MANDATORY TITLE PATTERNS (DATA-DRIVEN) ===
These patterns have proven 3-5x higher engagement. USE THEM:

**PRIMARY (Use for 2+ of 3 titles):**
"Why [Major Power/Entity] Can't/Won't/Didn't [Strategic Action]"
- Impossibility framing drives curiosity (avg 1073 VPH, 6.89% CTR)
- Examples: "Why Saudi Arabia Can't Retaliate", "Why China Can't Stop the Dollar"

**SECONDARY:**
"How Would [Major Event/Operation] Actually Happen?"
- Scenario framing with "Actually" adds authority
- Example: "How Would a Taiwan Invasion Actually Happen?"

**TERTIARY:**
"The $[Amount] [Noun]: Why [X] Can't [Y]"
- Combine money hook with impossibility framing
- Example: "The $400 Billion Hostage: Why Saudi Arabia Can't Retaliate"

AVOID: Generic titles, single-word drama words without impossibility framing

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
            model=Models.CLAUDE_SONNET,
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
            model=Models.CLAUDE_SONNET,
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
        from .sentence_utils import analyze_scene_for_images

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
        from .sentence_utils import split_into_sentences, estimate_sentence_duration

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
            model=Models.CLAUDE_SONNET,
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
            model=Models.CLAUDE_SONNET,
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
            f'Generate a 2-word STRATEGIC VERDICT for the thumbnail based on the video topic.',
            f'This should be a judgment about the situation (like CHOKE POINT, PROXY WAR, POWER VACUUM).',
            f'EXACTLY 2 words, ALL CAPS. No YOUR/YOU language. No descriptions — a verdict.',
            f'',
            f'Generate the complete image prompt now.',
        ])

        user_prompt = '\n'.join(prompt_parts)

        response = await self.generate(
            prompt=user_prompt,
            system_prompt=ANTHROPIC_THUMBNAIL_SYSTEM_PROMPT,
            model=Models.CLAUDE_SONNET,
            max_tokens=1200,
        )

        return response.strip()

    async def generate_video_prompt(
        self,
        image_prompt: str,
        sentence_text: str = "",
        scene_type: str = None,
        is_hero_shot: bool = False,
        prev_cameras: list[str] | None = None,
        system_prompt_override: str = None,
    ) -> str:
        """Generate a motion prompt for image-to-video animation.

        Creates a motion-only prompt for Grok Imagine that describes camera movement,
        subject motion, and atmospheric effects WITHOUT re-describing the scene.

        Args:
            image_prompt: The prompt used to generate the static image.
            sentence_text: The narration being spoken during this image (for alignment).
            scene_type: Scene type string (e.g., "isometric_diorama", "split_screen").
            is_hero_shot: If True, generate a richer prompt for 10s duration (vs 6s standard).
            prev_cameras: Recent camera movements (most recent last) for rotation enforcement.

        Returns:
            Motion prompt (max 40 words for 6s, max 55 words for 10s hero).
        """
        from .style_engine import get_camera_motion

        # Determine camera purpose from sentence text
        # Camera is STATIC by default — only moves for REVEAL, SCALE, or ISOLATION
        from animation_prompt_engine import classify_camera_purpose, CAMERA_PURPOSE_STATIC
        camera_purpose = classify_camera_purpose(sentence_text)

        # Only request camera motion when purpose justifies it
        if camera_purpose != CAMERA_PURPOSE_STATIC and scene_type:
            camera_motion = get_camera_motion(scene_type, is_hero_shot)
        else:
            camera_motion = "Static shot"

        # Word limit based on duration
        word_limit = 55 if is_hero_shot else 40
        duration_note = "10-second HERO SHOT" if is_hero_shot else "6-second clip"
        hero_instruction = """
For this HERO SHOT (10s), you may use 2 subject actions instead of 1, but still no more than 2 total animated elements.""" if is_hero_shot else ""

        if system_prompt_override:
            # Use the per-video override with variable substitution
            system_prompt = system_prompt_override.format(
                duration_note=duration_note,
                word_limit=word_limit,
                hero_instruction=hero_instruction,
                camera_purpose=camera_purpose,
                camera_motion=camera_motion,
            )
        if not system_prompt_override:
            # NEUTRAL last-resort fallback (engine/identity split, Phase 2). Fires
            # only when no system_prompt_override is passed. Self-contained — this
            # skill package CANNOT import the backend's engine_templates — but it
            # carries the SAME universal motion craft: verb-first / camera static
            # by default / max 2 actions / banned filler / emotional-motion
            # vocabulary. No "never show people" rule (that was Power-Doctrine
            # data-viz identity); animate whatever the scene contains. Examples
            # are niche-neutral, not geopolitical.
            system_prompt = f"""You are a cinematographer writing motion instructions for AI video generation.
Each prompt animates a single static image into a {duration_note}. The narrator will be speaking the Sentence Text over this clip.

YOUR JOB: Write motion that LITERALLY ENACTS the verb in the narration. You are not decorating — you are directing a film.

CRITICAL: The source image ALREADY contains the full scene. Do NOT re-describe the scene. Only describe what MOVES and HOW.
Animate whatever the scene actually contains — a person, a character, an object, a place, a chart, a hand. There is no restriction on what may move; the right motion is the one that enacts the narration.
Maximum {word_limit} words.
{hero_instruction}

## RULE 1 — VERB-FIRST MOTION DESIGN

Before writing ANY motion, do this:
1. Read the Sentence Text
2. Identify the CORE VERB or action ("turns", "opens", "rises", "rolls", "fills")
3. The subject animation must LITERALLY ENACT that verb
4. Everything else in frame HOLDS STILL — the animated verb is the only motion

Examples:
- "She turns to face the door" → the character pivots, eyes lifting to the doorway, everything else still
- "The door creaks open" → the door swings inward, light widening across the floor
- "Steam rises off the pan" → a single ribbon of steam lifts and curls upward from the surface
- "The ball rolls to the edge" → the ball rolls across the table and stops at the lip
- "The total climbs" → the number ticks upward and the bar fills left to right

The verb IS the animation. Not a metaphor for it. Not a decoration around it.

## RULE 2 — CAMERA MOVES ONLY WHEN CAMERA IS THE MEANING

Camera must be STATIC by default. Only add camera motion if it serves exactly one of three purposes:
1. REVEAL — motion uncovers something new (a pan that exposes who else is in the room)
2. SCALE — motion communicates size (a pull-back showing how big the space really is)
3. ISOLATION — motion narrows focus (a push-in on the one detail that matters)

If the camera move doesn't serve REVEAL, SCALE, or ISOLATION — it's a static shot.
Remove all default orbit/drift/push-in that exists as cinematography habit.

WRONG: "Slow orbit around the kitchen with gradual push-in. The cook stirs the pot, steam rises, a timer ticks, light flickers..."
→ Camera eating attention budget, 4+ simultaneous actions

RIGHT: "Static medium shot of the kitchen. The cook stirs the pot once, slowly, as steam lifts off the surface."
→ Camera still, one meaningful motion

## RULE 3 — TWO ACTIONS MAXIMUM PER CLIP

Each animation prompt gets AT MOST:
- 1 camera action (only if it passes Rule 2) + 1 subject action
- OR 0 camera action + 2 subject actions
- NEVER more than 2 total animated elements

Count your actions before submitting. If you have more than 2, delete until you have 2.

## MOTION VOCABULARY — USE VERBS, NOT ADJECTIVES

BANNED WORDS (never use):
- gently, softly, subtly, slightly (as filler)
- "ambient glow intensifies/dims"
- "dust particles drift"
- "reflections shift across surfaces"
- "light pulses"
- Any motion that could apply to ANY image regardless of narration

REQUIRED: Every motion must be a specific VERB acting on a specific OBJECT:
- "Her hand closes around the cup" (specific object + specific action)
- "The dough folds over onto itself" (specific object + specific action)
- "Lights switch on room by room from left to right" (specific object + specific action + specific direction)

## THE PAYOFF LINE TEST

Read your final line. Does it create a VISUAL IMAGE that lands emotionally?
- GOOD: "...until she finally looks up and meets the camera"
- GOOD: "...the last light clicks off, leaving the room dark"
- BAD: "...ambient glow softly dims"
- BAD: "...elements gently pulse"
If your final line could be a screensaver, rewrite the entire prompt.

## EMOTIONAL MOTION DICTIONARY

COLLAPSE / FAILURE: freeze, stutter, slump, dim in sequence, go dark one by one, slow to a crawl, lock up, fall apart, dissolve, drain
ESCALATION / BUILD: accelerate, multiply, cascade, spread outward, stack up, swarm, converge, tighten, rise
REVELATION / DISCOVERY: snap into focus, illuminate, peel back, turn toward, resolve from blur, sharpen, open, materialize
TENSION / ANTICIPATION: hold unnaturally still, hover, strain, pull apart slowly, balance on the edge
RELEASE / ARRIVAL: settle, exhale, land, fall into place, bloom, spill, open out
LOSS / ABSENCE: fade to nothing, leave empty, hollow out, slip away, scatter, recede

## CAMERA DECISION

The camera purpose for this clip is: "{camera_purpose}"
The camera direction is: "{camera_motion}"

If camera is "Static shot", do NOT add any camera motion. Your entire budget is for subject action.

OUTPUT: Return ONLY the motion prompt text. No explanations, no formatting, no labels."""

        narration_context = ""
        if sentence_text:
            narration_context = f"\n\nNarration being spoken during this image: \"{sentence_text}\""

        # Camera history context for rotation enforcement
        camera_history_context = ""
        if prev_cameras:
            recent = prev_cameras[-2:]
            camera_history_context = (
                f"\n\nPREVIOUS CAMERA MOVEMENTS (do NOT repeat the most recent): "
                f"{', '.join(recent)}"
            )

        prompt = f"""Image Prompt (for context, do NOT repeat scene descriptions):
{image_prompt}
{narration_context}{camera_history_context}

Camera decision: "{camera_motion}" (purpose: {camera_purpose})
Generate the subject motion ({word_limit - 10} words max).
RULE 3 CHECK: Your response + camera = MAX 2 animated elements total.
If camera is "Static shot", you may have up to 2 subject actions."""

        response = await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            model=Models.CLAUDE_SONNET,
            max_tokens=200,
        )

        # Prepend the camera motion to guarantee format.
        # Strip any leading camera prefix Claude may have included to avoid
        # duplication like "Static shot. Static wide shot."
        subject_motion = response.strip()
        subject_motion = re.sub(
            r"^(?:Static\s+(?:wide\s+)?shot|Camera\s+(?:is\s+)?static)[.,:]?\s*",
            "",
            subject_motion,
            flags=re.IGNORECASE,
        )
        if camera_motion == "Static shot":
            return f"Static shot. {subject_motion}"
        # Also strip if Claude echoed the non-static camera direction
        subject_motion = re.sub(
            r"^" + re.escape(camera_motion) + r"[.,:]?\s*",
            "",
            subject_motion,
            flags=re.IGNORECASE,
        )
        return f"{camera_motion}. {subject_motion}"
