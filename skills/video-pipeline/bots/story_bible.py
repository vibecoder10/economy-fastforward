"""Story Bible Generation.

Generates character and location bibles for visual consistency across
an entire video. Run ONCE before generating any image prompts.

The Story Bible provides:
1. Character Bible: Recurring characters with EXACT clothing/appearance
2. Location Bible: Recurring locations with EXACT environment details
3. Visual Arc: Mood and color progression per scene

Claude receives the Story Bible context when writing each visual
description, ensuring the same character appears identically across
all their scenes, and locations maintain visual continuity.
"""

import json
from typing import Optional


# System prompt for generating the Story Bible
STORY_BIBLE_SYSTEM_PROMPT = """You are a visual story bible creator for a documentary video production.

Your job is to analyze the FULL script and identify recurring visual elements that need to stay consistent across the entire video.

The goal: If the same character appears in scenes 2, 5, and 12, they must wear IDENTICAL clothing and be described EXACTLY the same way in all three scenes. If the same location appears in scenes 3 and 10, it must look EXACTLY the same.

You are creating a reference document that the image prompt writer will consult for EVERY image. When they write a prompt featuring "the Russian leader", they will copy the EXACT description from your character bible.

Be SPECIFIC. Don't write "formal suit" — write "dark charcoal three-button suit with white shirt, dark navy tie, gold watch on left wrist." The image model needs consistent details."""


STORY_BIBLE_USER_PROMPT = """Read this entire video script and produce a visual story bible.

FULL SCRIPT:
{full_script_text}

Produce a JSON response with these sections:

1. "characters": A list of recurring characters/roles. For each:
   - "id": short snake_case identifier (e.g., "russian_leader", "eu_official", "iranian_general")
   - "description": EXACT clothing and appearance description to use in EVERY image. Must include:
     * Specific clothing items with colors (e.g., "dark charcoal suit with white shirt and dark navy tie")
     * Body position defaults (e.g., "standing with hands behind back" or "seated at desk")
     * Any distinguishing props (e.g., "gold pen in breast pocket", "military medals on chest")
   - "scenes_present": list of scene numbers where they appear
   - "role": protagonist, antagonist, supporting, background

2. "locations": A list of locations. For each:
   - "id": short snake_case identifier (e.g., "kremlin_office", "tehran_facility", "trading_floor")
   - "description": EXACT environment description to reuse. Must include:
     * Architectural details (e.g., "wood-paneled walls with tall bookshelves")
     * Key objects (e.g., "heavy mahogany desk with brass desk lamp")
     * Ambient elements (e.g., "large window showing Moscow skyline at dusk")
   - "scenes_present": list of scene numbers set in this location
   - "lighting": default lighting mood (e.g., "warm amber single-source from window")

3. "visual_arc": A list defining the emotional progression. For EACH scene number:
   - "scene": scene number (1, 2, 3, etc.)
   - "mood": emotional tone (tense, revelatory, escalating, calm, crisis, triumphant, ominous)
   - "color_temperature": warm/cold/neutral
   - "intensity": 1-10 (how dramatic/urgent the visuals should feel)

4. "recurring_props": Objects that appear in multiple scenes:
   - "id": short identifier (e.g., "treaty_document", "satellite_phone", "oil_chart")
   - "description": EXACT visual description
   - "scenes_present": list of scene numbers

CRITICAL RULES:
- Every character that appears MORE THAN ONCE needs an entry
- Every location that appears MORE THAN ONCE needs an entry
- Character descriptions MUST include specific clothing — no naked mannequins!
- If a character's role isn't explicitly stated, infer from context
- Default clothing if unknown: "dark formal suit with white shirt"

Respond ONLY with valid JSON. No markdown fences, no explanation."""


async def generate_story_bible(
    anthropic_client,
    full_script_text: str,
    video_title: str = "",
) -> dict:
    """Generate a complete Story Bible from the full script.

    This should be called ONCE per video, BEFORE any image prompts
    are generated. The resulting bible is stored in Airtable and
    passed to Claude for every subsequent visual description.

    Args:
        anthropic_client: AnthropicClient instance with generate() method
        full_script_text: Combined text of ALL scenes in the video
        video_title: Video title for logging/context

    Returns:
        Dict with keys: characters, locations, visual_arc, recurring_props
        Returns empty dict if generation fails.
    """
    if not full_script_text or len(full_script_text.strip()) < 100:
        print(f"  ⚠️ Script too short for story bible: {len(full_script_text)} chars")
        return {}

    prompt = STORY_BIBLE_USER_PROMPT.format(full_script_text=full_script_text)

    try:
        response = await anthropic_client.generate(
            prompt=prompt,
            system_prompt=STORY_BIBLE_SYSTEM_PROMPT,
            model="claude-sonnet-4-5-20250929",
            max_tokens=8000,
            temperature=0.3,  # Low temperature for consistency
        )

        # Parse JSON response
        bible = _parse_json_response(response)

        if not bible:
            print(f"  ⚠️ Failed to parse story bible JSON")
            return {}

        # Validate required sections
        if "characters" not in bible:
            bible["characters"] = []
        if "locations" not in bible:
            bible["locations"] = []
        if "visual_arc" not in bible:
            bible["visual_arc"] = []
        if "recurring_props" not in bible:
            bible["recurring_props"] = []

        # Log summary
        print(f"  📖 Story Bible generated:")
        print(f"      {len(bible['characters'])} characters")
        print(f"      {len(bible['locations'])} locations")
        print(f"      {len(bible['visual_arc'])} scene arcs")
        print(f"      {len(bible['recurring_props'])} recurring props")

        return bible

    except Exception as e:
        print(f"  ⚠️ Story bible generation failed: {e}")
        return {}


def _parse_json_response(response_text: str) -> dict:
    """Extract JSON from LLM response with fallback parsing."""
    import re

    # Try direct parse first
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try finding raw JSON braces
    brace_start = response_text.find("{")
    brace_end = response_text.rfind("}")
    if brace_start != -1 and brace_end != -1:
        try:
            return json.loads(response_text[brace_start:brace_end + 1])
        except json.JSONDecodeError:
            pass

    return {}


def format_bible_for_prompt(story_bible: dict, current_scene: int) -> str:
    """Format the Story Bible as context for Claude's image prompt generation.

    Produces a condensed text block that Claude can reference when
    writing visual descriptions for a specific scene.

    Args:
        story_bible: The full Story Bible dict
        current_scene: The scene number being generated (1-indexed)

    Returns:
        Formatted string to include in Claude's prompt context
    """
    if not story_bible:
        return ""

    lines = []

    # Character Bible section
    chars = story_bible.get("characters", [])
    if chars:
        lines.append("=== CHARACTER BIBLE (use EXACT descriptions) ===")
        for char in chars:
            char_id = char.get("id", "unknown")
            desc = char.get("description", "")
            scenes = char.get("scenes_present", [])
            if current_scene in scenes or not scenes:
                lines.append(f"\n{char_id.upper()}:")
                lines.append(f"  {desc}")
                lines.append(f"  [Appears in scenes: {', '.join(map(str, scenes))}]")

    # Location Bible section
    locs = story_bible.get("locations", [])
    if locs:
        lines.append("\n=== LOCATION BIBLE (use EXACT descriptions) ===")
        for loc in locs:
            loc_id = loc.get("id", "unknown")
            desc = loc.get("description", "")
            lighting = loc.get("lighting", "")
            scenes = loc.get("scenes_present", [])
            if current_scene in scenes or not scenes:
                lines.append(f"\n{loc_id.upper()}:")
                lines.append(f"  {desc}")
                if lighting:
                    lines.append(f"  Lighting: {lighting}")
                lines.append(f"  [Appears in scenes: {', '.join(map(str, scenes))}]")

    # Visual arc for current scene
    arcs = story_bible.get("visual_arc", [])
    current_arc = next((a for a in arcs if a.get("scene") == current_scene), None)
    if current_arc:
        lines.append(f"\n=== SCENE {current_scene} VISUAL ARC ===")
        lines.append(f"  Mood: {current_arc.get('mood', 'neutral')}")
        lines.append(f"  Color temperature: {current_arc.get('color_temperature', 'neutral')}")
        lines.append(f"  Intensity: {current_arc.get('intensity', 5)}/10")

    # Recurring props
    props = story_bible.get("recurring_props", [])
    if props:
        lines.append("\n=== RECURRING PROPS ===")
        for prop in props:
            prop_id = prop.get("id", "unknown")
            desc = prop.get("description", "")
            scenes = prop.get("scenes_present", [])
            if current_scene in scenes or not scenes:
                lines.append(f"  {prop_id}: {desc}")

    if not lines:
        return ""

    return "\n".join(lines)


def get_character_description(story_bible: dict, character_hint: str) -> Optional[str]:
    """Look up a character's exact description from the bible.

    Args:
        story_bible: The full Story Bible dict
        character_hint: A term that might identify the character
            (e.g., "Russian", "leader", "russian_leader")

    Returns:
        The exact character description if found, None otherwise
    """
    if not story_bible:
        return None

    chars = story_bible.get("characters", [])
    hint_lower = character_hint.lower().replace(" ", "_")

    for char in chars:
        char_id = char.get("id", "").lower()
        if hint_lower in char_id or char_id in hint_lower:
            return char.get("description")

    return None


def get_location_description(story_bible: dict, location_hint: str) -> Optional[str]:
    """Look up a location's exact description from the bible.

    Args:
        story_bible: The full Story Bible dict
        location_hint: A term that might identify the location
            (e.g., "Kremlin", "office", "kremlin_office")

    Returns:
        The exact location description if found, None otherwise
    """
    if not story_bible:
        return None

    locs = story_bible.get("locations", [])
    hint_lower = location_hint.lower().replace(" ", "_")

    for loc in locs:
        loc_id = loc.get("id", "").lower()
        if hint_lower in loc_id or loc_id in hint_lower:
            return loc.get("description")

    return None
