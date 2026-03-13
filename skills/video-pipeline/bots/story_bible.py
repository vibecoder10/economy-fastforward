"""Story Bible Generation — Complete Visual Storytelling Engine.

Generates a comprehensive Story Bible for visual consistency and narrative
escalation across an entire video. Run ONCE before generating any image prompts.

The Story Bible provides:
1. Character Bible: Recurring characters with EXACT costume/appearance
2. Location Bible: Recurring locations with EXACT environment details
3. Visual Arc: Per-scene mood, color, camera, tension mapping

Claude receives the Story Bible context when writing each visual
description, ensuring the same character appears identically across
all their scenes, locations maintain visual continuity, and the
visual arc escalates properly.
"""

import json
from typing import Optional


# System prompt for generating the Story Bible
STORY_BIBLE_SYSTEM_PROMPT = """You are a cinematographer planning the visual storytelling for a documentary-style YouTube video. Read the entire script below and produce a Story Bible that ensures visual consistency and narrative escalation across all images.

Your bible will be used by another AI to write specific image prompts. Every character and location description you write will be COPIED EXACTLY into multiple image prompts. So be specific, consistent, and visually concrete.

Be SPECIFIC. Don't write "formal suit" — write "dark charcoal three-button suit with crisp white dress shirt, dark navy silk tie, and gold watch visible on left wrist." The image model needs consistent, specific details."""


STORY_BIBLE_USER_PROMPT = """Read this entire video script and produce a Story Bible.

FULL SCRIPT:
{full_script_text}

Produce a JSON response with these three sections:

## 1. "characters"

Identify every recurring character or role. For each:
- "id": short snake_case identifier (e.g., "russian_leader", "eu_official")
- "costume": EXACT clothing description that will be used EVERY time this character appears. Be specific: fabric, color, accessories. Example: "dark charcoal three-button suit with crisp white dress shirt, dark navy silk tie, and gold watch visible on left wrist"
- "scenes_present": list of scene numbers where this character appears or is referenced
- "role": protagonist / antagonist / observer / victim
- "signature_pose": their default body language when not performing a specific action (e.g., "hands clasped behind back", "leaning forward over desk")

Rules:
- Every character MUST have specific clothing. No naked or unspecified mannequins.
- Use contextual costume cues for nationality/role (Mao collar = Chinese, turban + robes = Iranian cleric, etc.)
- Maximum 5-6 characters. Merge minor references into existing archetypes.
- If the same entity appears in different time periods (e.g., 1973 vs 2026), create separate character entries with period-appropriate costumes.

## 2. "locations"

Identify every distinct location/setting. For each:
- "id": short snake_case identifier (e.g., "kremlin_office", "strait_of_hormuz")
- "description": EXACT environment description that will be reused every time this location appears. Include: room/space type, key furniture/objects, wall details, window/door details, floor material.
- "scenes_present": list of scene numbers set in this location
- "lighting": specific lighting description (e.g., "warm amber from brass desk lamp, cold blue from snow-lit window")
- "color_temperature": warm / cold / neutral
- "signature_detail": one unique visual detail that makes this location instantly recognizable (e.g., "the tall window showing snow-covered Red Square", "the crossed Russian-Iranian flags")

Rules:
- Same location appearing in multiple scenes MUST use identical description.
- Include 2-3 "everyday" locations for personal impact scenes (gas station, kitchen table, trading floor).
- Data/holographic display scenes count as a location: "dark operations room."
- Maximum 8-10 locations. Merge similar settings.

## 3. "visual_arc"

Map the emotional and visual progression of the ENTIRE video. For EACH scene:
- "scene": scene number
- "location_id": which location from the bible (must match a location.id)
- "characters_present": list of character IDs present (empty list for environment/data scenes)
- "mood": one word — tense / desperate / revelatory / threatening / clinical / archival / personal / resolute
- "color_temperature": specific — "cold steel blue" / "warm amber" / "shifting amber to red" / "desaturated archival" / "harsh red alert" / "warm personal coral"
- "camera_distance": wide / medium / close-up / extreme-close-up
- "tension_level": 1-10 (must generally escalate across the video, with intentional dips for breathing room)
- "visual_note": one sentence describing what makes this specific image different from the one before it. What CHANGES between this frame and the last? This is the key to avoiding repetition.

Rules for the arc:
- NEVER the same location more than 2 scenes in a row. Intercut between worlds.
- NEVER the same camera distance more than 2 scenes in a row. Breathe: wide-medium-close-wide.
- NEVER the same color temperature more than 3 scenes in a row. The palette must shift with the narrative.
- Tension should generally rise but include 1-2 deliberate dips (after a revelation, before the next escalation) for rhythm.
- The FIRST and LAST scenes should visually rhyme — same location or same composition, but the viewer now understands it differently (bookend).
- Historical parallel scenes should visually contrast with present-day scenes (desaturated/archival vs vivid/present).
- Personal impact scenes (wallet, gas prices) should use completely different environments from the geopolitical scenes.

Respond ONLY with valid JSON. No markdown fences, no explanation, no preamble."""


async def generate_story_bible(
    anthropic_client,
    full_script_text: str,
    video_title: str = "",
    total_scenes: int = 14,
) -> dict:
    """Generate a complete Story Bible from the full script.

    This should be called ONCE per video, BEFORE any image prompts
    are generated. The resulting bible is stored in Airtable and
    passed to Claude for every subsequent visual description.

    Args:
        anthropic_client: AnthropicClient instance with generate() method
        full_script_text: Combined text of ALL scenes in the video
        video_title: Video title for logging/context
        total_scenes: Total number of scenes for arc validation

    Returns:
        Dict with keys: characters, locations, visual_arc
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

        # Validate and normalize required sections
        bible = _validate_and_normalize(bible, total_scenes)

        # Log summary
        print(f"  📖 Story Bible generated:")
        print(f"      {len(bible['characters'])} characters")
        print(f"      {len(bible['locations'])} locations")
        print(f"      {len(bible['visual_arc'])} scene arcs")

        # Validate arc constraints
        _validate_arc_constraints(bible)

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


def _validate_and_normalize(bible: dict, total_scenes: int) -> dict:
    """Validate and normalize the bible structure."""
    # Ensure all sections exist
    if "characters" not in bible:
        bible["characters"] = []
    if "locations" not in bible:
        bible["locations"] = []
    if "visual_arc" not in bible:
        bible["visual_arc"] = []

    # Normalize characters
    for char in bible["characters"]:
        # Support both "costume" and "description" field names
        if "description" in char and "costume" not in char:
            char["costume"] = char["description"]
        if "costume" not in char:
            char["costume"] = "dark formal suit with white shirt"
        if "signature_pose" not in char:
            char["signature_pose"] = "standing with composed posture"
        if "scenes_present" not in char:
            char["scenes_present"] = []
        if "role" not in char:
            char["role"] = "supporting"

    # Normalize locations
    for loc in bible["locations"]:
        if "description" not in loc:
            loc["description"] = "interior setting"
        if "lighting" not in loc:
            loc["lighting"] = "ambient lighting"
        if "color_temperature" not in loc:
            loc["color_temperature"] = "neutral"
        if "signature_detail" not in loc:
            loc["signature_detail"] = ""
        if "scenes_present" not in loc:
            loc["scenes_present"] = []

    # Normalize visual arc
    for arc in bible["visual_arc"]:
        if "scene" not in arc:
            continue
        if "location_id" not in arc:
            arc["location_id"] = bible["locations"][0]["id"] if bible["locations"] else "unknown"
        if "characters_present" not in arc:
            arc["characters_present"] = []
        if "mood" not in arc:
            arc["mood"] = "tense"
        if "color_temperature" not in arc:
            arc["color_temperature"] = "neutral"
        if "camera_distance" not in arc:
            arc["camera_distance"] = "medium"
        if "tension_level" not in arc:
            arc["tension_level"] = 5
        if "visual_note" not in arc:
            arc["visual_note"] = ""
        # Support legacy "intensity" field
        if "intensity" in arc and "tension_level" not in arc:
            arc["tension_level"] = arc["intensity"]

    return bible


def _validate_arc_constraints(bible: dict) -> None:
    """Log warnings for arc constraint violations."""
    arcs = bible.get("visual_arc", [])
    if len(arcs) < 2:
        return

    # Check for repeated locations
    for i in range(2, len(arcs)):
        if (arcs[i].get("location_id") == arcs[i-1].get("location_id") ==
                arcs[i-2].get("location_id")):
            print(f"      ⚠️ Arc constraint: location repeats 3x at scenes "
                  f"{arcs[i-2].get('scene')}-{arcs[i].get('scene')}")

    # Check for repeated camera distance
    for i in range(2, len(arcs)):
        if (arcs[i].get("camera_distance") == arcs[i-1].get("camera_distance") ==
                arcs[i-2].get("camera_distance")):
            print(f"      ⚠️ Arc constraint: camera distance repeats 3x at scenes "
                  f"{arcs[i-2].get('scene')}-{arcs[i].get('scene')}")

    # Check bookend
    if arcs[0].get("location_id") != arcs[-1].get("location_id"):
        print(f"      ℹ️ Arc note: first and last scenes use different locations "
              f"(no bookend)")


def format_bible_for_prompt(story_bible: dict, current_scene: int) -> str:
    """Format the Story Bible as context for Claude's image prompt generation.

    Produces a detailed context block that Claude uses when writing
    visual descriptions for a specific scene.

    Args:
        story_bible: The full Story Bible dict
        current_scene: The scene number being generated (1-indexed)

    Returns:
        Formatted string to include in Claude's prompt context
    """
    if not story_bible:
        return ""

    lines = []

    # === CHARACTERS SECTION ===
    chars = story_bible.get("characters", [])
    if chars:
        lines.append("=== CHARACTER BIBLE (use EXACT costume descriptions) ===")
        for char in chars:
            char_id = char.get("id", "unknown")
            costume = char.get("costume") or char.get("description", "")
            pose = char.get("signature_pose", "")
            scenes = char.get("scenes_present", [])
            # Include character if they appear in this scene or if scene list is empty
            if current_scene in scenes or not scenes:
                lines.append(f"\n{char_id.upper()}:")
                lines.append(f"  Costume: {costume}")
                if pose:
                    lines.append(f"  Default pose: {pose}")
                if scenes:
                    lines.append(f"  [Appears in scenes: {', '.join(map(str, scenes))}]")

    # === LOCATIONS SECTION ===
    locs = story_bible.get("locations", [])
    if locs:
        lines.append("\n=== LOCATION BIBLE (use EXACT descriptions) ===")
        for loc in locs:
            loc_id = loc.get("id", "unknown")
            desc = loc.get("description", "")
            lighting = loc.get("lighting", "")
            signature = loc.get("signature_detail", "")
            scenes = loc.get("scenes_present", [])
            if current_scene in scenes or not scenes:
                lines.append(f"\n{loc_id.upper()}:")
                lines.append(f"  {desc}")
                if lighting:
                    lines.append(f"  Lighting: {lighting}")
                if signature:
                    lines.append(f"  Signature detail: {signature}")
                if scenes:
                    lines.append(f"  [Appears in scenes: {', '.join(map(str, scenes))}]")

    # === VISUAL ARC FOR THIS SCENE ===
    arcs = story_bible.get("visual_arc", [])
    current_arc = next((a for a in arcs if a.get("scene") == current_scene), None)
    if current_arc:
        lines.append(f"\n=== VISUAL ARC FOR SCENE {current_scene} ===")
        lines.append(f"  Location: {current_arc.get('location_id', 'unknown')}")
        chars_present = current_arc.get('characters_present', [])
        if chars_present:
            lines.append(f"  Characters present: {', '.join(chars_present)}")
        else:
            lines.append(f"  Characters present: none (environment/data scene)")
        lines.append(f"  Mood: {current_arc.get('mood', 'neutral')}")
        lines.append(f"  Color temperature: {current_arc.get('color_temperature', 'neutral')}")
        lines.append(f"  Camera distance: {current_arc.get('camera_distance', 'medium')}")
        lines.append(f"  Tension level: {current_arc.get('tension_level', 5)}/10")
        visual_note = current_arc.get('visual_note', '')
        if visual_note:
            lines.append(f"  Visual note: {visual_note}")

    if not lines:
        return ""

    return "\n".join(lines)


def get_scene_arc(story_bible: dict, scene_number: int) -> dict:
    """Get the visual arc data for a specific scene.

    Args:
        story_bible: The full Story Bible dict
        scene_number: Scene number to look up

    Returns:
        The arc dict for this scene, or empty dict if not found
    """
    if not story_bible:
        return {}

    arcs = story_bible.get("visual_arc", [])
    return next((a for a in arcs if a.get("scene") == scene_number), {})


def get_character_by_id(story_bible: dict, char_id: str) -> Optional[dict]:
    """Look up a character by ID.

    Args:
        story_bible: The full Story Bible dict
        char_id: The character's snake_case ID

    Returns:
        The character dict if found, None otherwise
    """
    if not story_bible:
        return None

    chars = story_bible.get("characters", [])
    char_id_lower = char_id.lower().replace(" ", "_")

    for char in chars:
        if char.get("id", "").lower() == char_id_lower:
            return char

    return None


def get_location_by_id(story_bible: dict, loc_id: str) -> Optional[dict]:
    """Look up a location by ID.

    Args:
        story_bible: The full Story Bible dict
        loc_id: The location's snake_case ID

    Returns:
        The location dict if found, None otherwise
    """
    if not story_bible:
        return None

    locs = story_bible.get("locations", [])
    loc_id_lower = loc_id.lower().replace(" ", "_")

    for loc in locs:
        if loc.get("id", "").lower() == loc_id_lower:
            return loc

    return None


def get_character_costume(story_bible: dict, character_hint: str) -> Optional[str]:
    """Look up a character's exact costume from the bible.

    Args:
        story_bible: The full Story Bible dict
        character_hint: A term that might identify the character
            (e.g., "Russian", "leader", "russian_leader")

    Returns:
        The exact costume description if found, None otherwise
    """
    if not story_bible:
        return None

    chars = story_bible.get("characters", [])
    hint_lower = character_hint.lower().replace(" ", "_")

    for char in chars:
        char_id = char.get("id", "").lower()
        if hint_lower in char_id or char_id in hint_lower:
            return char.get("costume") or char.get("description")

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
