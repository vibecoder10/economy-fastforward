"""Story Bible Generation — Complete Visual Storytelling Engine.

Generates a comprehensive Story Bible for visual consistency and narrative
escalation across an entire video. Run ONCE before generating any image prompts.

The Story Bible provides:
1. Character Bible: Recurring characters with EXACT costume/appearance
2. Location Bible: Recurring locations with EXACT environment details
3. Scene Blocks: Groups of 2-5 images sharing environment/lighting (NEW)
4. Visual Arc: Per-scene mood, color, camera, tension mapping (LEGACY)

Claude receives the Story Bible context when writing each visual
description, ensuring the same character appears identically across
all their scenes, locations maintain visual continuity, and the
visual arc escalates properly.

Scene Blocks (v2):
- Each block groups 2-5 consecutive images that share the same location
  and lighting, creating visual continuity within narrative beats
- Only camera angle, action, and expression change within a block
- Act boundaries MUST be scene block boundaries
- First image of each block is always a wide establishing shot
"""

# Scene block sizing configuration
SCENE_BLOCK_CONFIG = {
    "min_images_per_block": 2,
    "max_images_per_block": 5,
    "target_blocks_10_min": 15,  # ~60 images / 4 per block
    "target_blocks_12_min": 18,  # ~72 images / 4 per block
    "first_image_must_be_wide": True,
    "act_boundary_forces_new_block": True,
}

import json
from typing import Optional
from orchestrator.pipeline_constants import Models
from shared.json_utils import parse_json_response


# System prompt for generating the Story Bible
STORY_BIBLE_SYSTEM_PROMPT = """You are a cinematographer planning the visual storytelling for a documentary-style YouTube video. Read the entire script below and produce a Story Bible that ensures visual consistency and narrative escalation across all images.

Your bible will be used by another AI to write specific image prompts. Every character and location description you write will be COPIED EXACTLY into multiple image prompts. So be specific, consistent, and visually concrete.

Be SPECIFIC. Don't write "formal suit" — write "dark charcoal three-button suit with crisp white dress shirt, dark navy silk tie, and gold watch visible on left wrist." The image model needs consistent, specific details.

CRITICAL VISUAL RULE — SHOW THE ACTION, NOT THE REACTION:
When designing the visual arc, each scene's image should show the ACTION the narration describes, not a character reacting to it in an office.

Rules:
- Military events → show the military hardware, operations, explosions, landscapes. Jets in the sky, ships in the strait, missiles launching, bunkers exploding. No character reading about it at a desk.
- Economic events → show the physical infrastructure. Oil fields pumping, tanker ships, factory floors, stock tickers, gas station price displays, empty shelves. Not a chart on a screen.
- Political events → show the event itself. Press conference with cameras, signing ceremony, protest in streets, parliament in session. Not someone watching it on TV.
- Declarations/speeches → show the speaker AT the podium or on a broadcast screen in a control room. Not someone hearing about it secondhand.
- Historical parallels → show the historical event itself with period-appropriate visuals. 1973 oil embargo = tankers stopped at sea, gas lines. 1979 Afghanistan = Soviet helicopters over mountains. Not a character reading a history book.

Scene type distribution for a typical video:
- 30% ACTION SCENES: Military operations, infrastructure, physical events happening in the world
- 25% CHARACTER SCENES: Illustrated figures performing specific actions (signing, declaring, confronting) — NOT sitting at desks
- 20% ENVIRONMENT SCENES: Locations that tell the story (strait, oil field, city, desert, war zone)
- 15% DATA SCENES: Holographic displays for specific statistics and numbers
- 10% OBJECT CLOSEUPS: Documents, weapons, currency, physical evidence

Maximum 20% of images should be interior office/desk scenes. The remaining 80% should show the world.

NARRATION → VISUAL TRANSLATION EXAMPLES:

"Russia and Iran signed a 20-year strategic partnership" → Two illustrated figures in formal attire at ornate signing table, both leaning forward with pens touching document, crossed flags behind, cameras flashing

"The United States launched strikes on Iran" → Cinematic wide shot of desert at dawn, military jets banking over terrain, explosion clouds rising from concrete bunker complex, contrails in sky

"Oil hit $120 per barrel" → Close-up of crude oil price ticker display showing $120 in large red numbers, trading floor screens visible in background with red declining charts

"The Strait of Hormuz effectively closed" → Aerial view of Strait of Hormuz waterway, single oil tanker stopped mid-channel, military patrol boats creating wake patterns, empty shipping lanes where traffic should be

"Sanctions were working. Oil revenues collapsed." → Vast Russian oil field in winter, pump jacks frozen and idle, snow covering equipment, pipeline valve sealed shut, desolate industrial landscape

"Every Patriot missile fired in Iran is one not defending Ukraine" → Split composition: left side shows Patriot battery launching missile against night sky in desert, right side shows empty missile launcher rack in Ukrainian field with city lights under attack in background

"For the average driver, that's $500-800 more per year" → Illustrated figure in casual clothes standing at gas pump, LED price display showing $3.45, hand reaching toward wallet, suburban gas station in harsh daylight

"What Sun Tzu identified as the supreme art of war" → Extreme close-up of hands in dark suit resting on open leather-bound book, page showing calligraphic text, warm amber desk lamp casting sharp shadows, mahogany desk surface"""


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
- Every character MUST have specific clothing. No unclothed or unspecified figures.
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
- For scenes showing data/statistics/charts, use PHYSICAL settings, NOT holographic displays:
  - "war_room" — military briefing room with wall maps, pins, printed reports on table, physical screens
  - "newsroom" — TV studio with monitors showing footage, anchor desk, printed scripts, teleprompter
  - "government_office" — office with documents spread on desk, wall charts, filing cabinets, desk lamp
  - "archive" — library or records room with shelved documents, newspaper clippings on corkboard, reading lamp
- Maximum 8-10 locations. Merge similar settings.

LOCATION VARIETY REQUIREMENT:
- Maximum 3 interior office/government building locations per video
- Minimum 4 exterior/action locations (military sites, infrastructure, landscapes, urban environments)
- Minimum 2 "everyday" locations for personal impact scenes (gas station, kitchen, grocery store)
- At least 1 historical location for parallel scenes (1970s setting, Cold War era, etc.)

For each location, specify whether it is:
- INTERIOR (office, conference room, control room)
- EXTERIOR (landscape, cityscape, military site, infrastructure)
- EVERYDAY (domestic, commercial, street-level)
- HISTORICAL (period-specific setting)

The video's location mix should be approximately:
- 30% EXTERIOR action environments
- 25% INTERIOR government/military settings
- 20% DATA settings (war_room, newsroom, office with screens, archive)
- 15% EVERYDAY personal impact settings
- 10% HISTORICAL period settings

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

⚠️ HARD RULES FOR THE ARC (VIOLATIONS WILL BE REJECTED):

1. **LOCATION INTERCUT RULE** — NEVER assign the same location_id to more than 2 consecutive scenes. If scenes 5, 6, 7 are all about data/charts, you MUST cut away: scene 5 = war_room, scene 6 = kremlin_office (reaction shot), scene 7 = newsroom. This creates visual rhythm even when the narration stays on one topic.

2. **CAMERA DISTANCE RULE** — NEVER the same camera_distance for more than 2 consecutive scenes. Alternate: wide → medium → close-up → wide. Breathing room.

3. **COLOR TEMPERATURE RULE** — NEVER the same color_temperature for more than 3 consecutive scenes. The palette must shift with the narrative arc.

4. **DATA SCENE LIMIT** — Data presentation settings (war_room, newsroom, archive, office with charts) should appear in NO MORE than 30% of total scenes. If you have 14 scenes, max 4-5 should be data-focused. The rest should be physical locations with characters in action.

5. **TENSION ESCALATION** — Tension_level should generally rise from ~3-4 at the start to ~8-9 at the climax, with 1-2 intentional dips for breathing room after major revelations.

6. **BOOKEND STRUCTURE** — The FIRST and LAST scenes should use the same location_id (visual rhyme) but with different mood/tension.

7. **CONTRAST HISTORICAL SCENES** — Historical parallel scenes (1973, 1979, etc.) should use "desaturated archival" color_temperature, NOT the same warm/cold as present-day scenes.

8. **PERSONAL IMPACT SCENES** — When the narration mentions everyday impact (gas prices, grocery costs, heating bills), use everyday locations (gas_station, kitchen, trading_floor) NOT the operations room.

Before outputting, VERIFY:
- Count consecutive same-location scenes. If any location appears 3+ times in a row, FIX IT by inserting a reaction shot in a different location.
- Count data-presentation scenes (war_room, newsroom, archive, office). If > 30% of total scenes, reduce by moving some data to physical locations (character looking at screen, document on desk, etc.)

Respond ONLY with valid JSON. No markdown fences, no explanation, no preamble."""


# V2 Prompt: Scene Blocks format (replaces visual_arc with scene_blocks)
STORY_BIBLE_USER_PROMPT_V2 = """Read this entire video script and produce a Story Bible.

VIDEO LENGTH: {video_duration_minutes} minutes
TOTAL IMAGES REQUIRED: {total_images}

FULL SCRIPT:
{full_script_text}

Produce a JSON response with these three sections:

## 1. "characters"

Identify every recurring character or role. For each:
- "id": short snake_case identifier (e.g., "russian_leader", "eu_official")
- "costume": EXACT clothing description that will be used EVERY time this character appears. Be specific: fabric, color, accessories.
- "scenes_present": list of scene numbers where this character appears
- "role": protagonist / antagonist / observer / victim
- "signature_pose": their default body language (e.g., "hands clasped behind back")

Rules:
- Every character MUST have specific clothing. No unclothed figures.
- Use contextual costume cues for nationality/role.
- Maximum 5-6 characters. Merge minor references into existing archetypes.

## 2. "locations"

Identify every distinct location/setting. For each:
- "id": short snake_case identifier (e.g., "kremlin_office", "strait_of_hormuz")
- "description": EXACT environment description (20-40 words) that will be reused every time this location appears
- "lighting": specific lighting description (e.g., "warm amber from brass desk lamp, cold blue from window")
- "color_temperature": warm / cold / neutral
- "type": INTERIOR / EXTERIOR / EVERYDAY / HISTORICAL / DATA_SETTING

For data/statistics scenes, use physical settings (NOT holographic):
- war_room (military briefing room with wall maps, pins, printed reports, physical screens)
- newsroom (TV studio with monitors, anchor desk, teleprompter)
- government_office (documents on desk, wall charts, filing cabinets)
- archive (library, records room, newspaper clippings on corkboard)

Location mix guidelines:
- 30% EXTERIOR action environments
- 25% INTERIOR government/military settings
- 20% DATA_SETTING (war_room, newsroom, office, archive)
- 15% EVERYDAY personal impact settings
- 10% HISTORICAL period settings

Maximum 8-10 locations. Maximum 3 interior office locations.

## 3. "scene_blocks" (REPLACES visual_arc)

Group ALL {total_images} images into 12-24 SCENE BLOCKS. Each block = 2-5 consecutive images that share:
- Same location (from your locations list)
- Same lighting setup
- Same characters present

ONLY camera angle, action, and expression change within a block.

For EACH block:
- "block_id": "block_1", "block_2", etc.
- "act": which act this block belongs to (1-6)
- "location_id": which location from your locations list
- "location": FULL environment description copied from your location entry (20-40 words)
- "lighting": EXACT lighting setup from your location entry
- "mood": one word — tense / desperate / revelatory / threatening / clinical / archival / personal
- "characters_present": list of character IDs (empty list for environment/data scenes)
- "images": array of 2-5 image specs, EACH with:
  - "image_index": global 1-based index (images are numbered 1, 2, 3... up to {total_images})
  - "camera": "wide" / "medium" / "closeup" / "extreme_closeup"
  - "action": one sentence describing the specific moment (10-20 words)
  - "narration_excerpt": the ~15 words of script this image illustrates

⚠️ CRITICAL BLOCK RULES (VIOLATIONS WILL BE REJECTED):

1. **FIRST IMAGE = WIDE** — Every block's first image MUST have camera: "wide"
2. **ACT BOUNDARIES = BLOCK BOUNDARIES** — When a new act starts, START A NEW BLOCK
3. **LOCATION CHANGES = NEW BLOCK** — When location changes, START A NEW BLOCK
4. **BLOCK SIZE** — Minimum 2 images, maximum 5 images per block
5. **CAMERA PROGRESSION** — Within a block: wide → medium → closeup (general pattern)
6. **NO CONSECUTIVE SAME-LOCATION BLOCKS** — Never 2 consecutive blocks with same location_id
7. **TOTAL IMAGES** — You MUST output EXACTLY {total_images} images total across all blocks
8. **SEQUENTIAL NUMBERING** — image_index must count 1, 2, 3... sequentially with NO gaps
9. **FORWARD CONTINUITY** — the story timeline only moves FORWARD. Once an "action" has RESOLVED something (a character healed, freed, reunited, saved; a problem fixed), NO later image may re-stage the earlier unresolved state as if it is happening (no re-injuring, re-bandaging, re-breaking, re-trapping). The ending state is permanent.
10. **RECAP / REVIEW / OUTRO IMAGES** — for narration_excerpts that TEACH a word, REVIEW, SUMMARIZE, or address the viewer (e.g. "Word one: Injured…", "That was a wonderful story", "subscribe", "tell us in the comments"), the "action" must NOT re-enact a past plot moment. Use a NON-STORY action: a labeled word/title card, a character calmly facing the viewer, a simple symbolic prop, or a CALLBACK to an already-RESOLVED happy moment — never the characters re-performing an earlier problem.

Before outputting, VERIFY:
- Total blocks: 12-24 (aim for {target_blocks})
- Total images across all blocks: EXACTLY {total_images}
- image_index values: 1 through {total_images} with no gaps
- Every block starts with camera: "wide"
- No block has more than 5 images or fewer than 2
- Act transitions (1→2, 2→3, etc.) align with block boundaries
- No two consecutive blocks share the same location_id

Respond ONLY with valid JSON. No markdown fences, no explanation."""


async def generate_story_bible(
    anthropic_client,
    full_script_text: str,
    video_title: str = "",
    total_scenes: int = 14,
    use_scene_blocks: bool = False,
    total_images: int = 60,
    video_duration_minutes: int = 10,
) -> dict:
    """Generate a complete Story Bible from the full script.

    This should be called ONCE per video, BEFORE any image prompts
    are generated. The resulting bible is stored in Airtable and
    passed to Claude for every subsequent visual description.

    Args:
        anthropic_client: AnthropicClient instance with generate() method
        full_script_text: Combined text of ALL scenes in the video
        video_title: Video title for logging/context
        total_scenes: Total number of scenes for arc validation (legacy V1)
        use_scene_blocks: If True, use V2 scene_blocks format instead of visual_arc
        total_images: Target number of images for the video (V2 only)
        video_duration_minutes: Video duration in minutes (V2 only)

    Returns:
        Dict with keys: characters, locations, and either visual_arc (V1) or scene_blocks (V2)
        Returns empty dict if generation fails.
    """
    if not full_script_text or len(full_script_text.strip()) < 100:
        print(f"  ⚠️ Script too short for story bible: {len(full_script_text)} chars")
        return {}

    # Choose prompt based on version
    if use_scene_blocks:
        # V2: Scene blocks format
        target_blocks = max(12, min(24, total_images // 4))  # ~4 images per block average
        prompt = STORY_BIBLE_USER_PROMPT_V2.format(
            full_script_text=full_script_text,
            total_images=total_images,
            video_duration_minutes=video_duration_minutes,
            target_blocks=target_blocks,
        )
        version_label = "V2 (scene_blocks)"
    else:
        # V1: Legacy visual_arc format
        prompt = STORY_BIBLE_USER_PROMPT.format(full_script_text=full_script_text)
        version_label = "V1 (visual_arc)"

    try:
        response = await anthropic_client.generate(
            prompt=prompt,
            system_prompt=STORY_BIBLE_SYSTEM_PROMPT,
            model=Models.CLAUDE_SONNET,
            max_tokens=12000 if use_scene_blocks else 8000,  # V2 needs more tokens
            temperature=0.3,  # Low temperature for consistency
        )

        # Parse JSON response
        bible = _parse_json_response(response)

        if not bible:
            print(f"  ⚠️ Failed to parse story bible JSON")
            return {}

        # Validate and normalize based on version
        if use_scene_blocks:
            bible = _validate_and_normalize_scene_blocks(bible, total_images)
            # Log summary
            total_block_images = sum(
                len(b.get("images", [])) for b in bible.get("scene_blocks", [])
            )
            print(f"  📖 Story Bible {version_label} generated:")
            print(f"      {len(bible.get('characters', []))} characters")
            print(f"      {len(bible.get('locations', []))} locations")
            print(f"      {len(bible.get('scene_blocks', []))} scene blocks")
            print(f"      {total_block_images} total images")
        else:
            bible = _validate_and_normalize(bible, total_scenes)
            # Log summary
            print(f"  📖 Story Bible {version_label} generated:")
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
    return parse_json_response(response_text)


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


def _validate_and_normalize_scene_blocks(bible: dict, expected_images: int = 60) -> dict:
    """Validate and normalize scene_blocks structure.

    Ensures all blocks have required fields, enforces first-image-wide rule,
    and validates sequential image indexing.

    Args:
        bible: The raw Story Bible dict from Claude
        expected_images: Expected total number of images (from VideoConfig)

    Returns:
        Normalized bible dict with scene_blocks
    """
    # Ensure all sections exist
    if "characters" not in bible:
        bible["characters"] = []
    if "locations" not in bible:
        bible["locations"] = []
    if "scene_blocks" not in bible:
        bible["scene_blocks"] = []

    # Normalize characters (same as V1)
    for char in bible["characters"]:
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

    # Normalize locations (same as V1)
    for loc in bible["locations"]:
        if "description" not in loc:
            loc["description"] = "interior setting"
        if "lighting" not in loc:
            loc["lighting"] = "ambient lighting"
        if "color_temperature" not in loc:
            loc["color_temperature"] = "neutral"
        if "type" not in loc:
            loc["type"] = "INTERIOR"

    # Normalize scene blocks
    total_images = 0
    for i, block in enumerate(bible["scene_blocks"]):
        # Ensure required fields
        if "block_id" not in block:
            block["block_id"] = f"block_{i + 1}"
        if "act" not in block:
            block["act"] = 1
        if "location_id" not in block:
            block["location_id"] = bible["locations"][0]["id"] if bible["locations"] else "unknown"
        if "location" not in block:
            # Try to copy from location bible
            loc = next((l for l in bible["locations"] if l.get("id") == block["location_id"]), None)
            block["location"] = loc["description"] if loc else "unspecified environment"
        if "lighting" not in block:
            loc = next((l for l in bible["locations"] if l.get("id") == block["location_id"]), None)
            block["lighting"] = loc["lighting"] if loc else "ambient lighting"
        if "mood" not in block:
            block["mood"] = "neutral"
        if "characters_present" not in block:
            block["characters_present"] = []
        if "images" not in block:
            block["images"] = []

        # Normalize images within block
        for j, img in enumerate(block["images"]):
            if "camera" not in img:
                # First image in block must be wide
                img["camera"] = "wide" if j == 0 else "medium"
            if "action" not in img:
                img["action"] = "scene continues"
            if "narration_excerpt" not in img:
                img["narration_excerpt"] = ""

        # Enforce first image = wide
        if block["images"] and block["images"][0].get("camera") != "wide":
            print(f"      ⚠️ Block {block['block_id']}: fixing first image to wide (was {block['images'][0].get('camera')})")
            block["images"][0]["camera"] = "wide"

        total_images += len(block["images"])

    # Validate total image count
    if total_images != expected_images:
        print(f"      ⚠️ Scene blocks have {total_images} images, expected {expected_images}")

    # Validate consecutive block locations
    blocks = bible["scene_blocks"]
    for i in range(1, len(blocks)):
        if blocks[i].get("location_id") == blocks[i - 1].get("location_id"):
            print(f"      ⚠️ Consecutive blocks {blocks[i-1]['block_id']} and {blocks[i]['block_id']} "
                  f"share location {blocks[i]['location_id']}")

    return bible


# === SCENE BLOCK HELPER FUNCTIONS ===


def has_scene_blocks(story_bible: dict) -> bool:
    """Check if Story Bible uses V2 scene_blocks format.

    Args:
        story_bible: The Story Bible dict

    Returns:
        True if scene_blocks exists and has content, False otherwise
    """
    if not story_bible:
        return False
    return bool(story_bible.get("scene_blocks"))


def get_story_bible_version(story_bible: dict) -> int:
    """Return Story Bible version based on content.

    Args:
        story_bible: The Story Bible dict

    Returns:
        2 if scene_blocks format (V2)
        1 if visual_arc format (V1)
        0 if empty/invalid
    """
    if not story_bible:
        return 0
    if story_bible.get("scene_blocks"):
        return 2
    if story_bible.get("visual_arc"):
        return 1
    return 0


def get_block_for_image(story_bible: dict, image_index: int) -> Optional[dict]:
    """Find the scene block containing a specific image index.

    Args:
        story_bible: The Story Bible dict with scene_blocks
        image_index: Global 1-based image index

    Returns:
        The block dict containing this image, or None if not found
    """
    if not story_bible:
        return None

    for block in story_bible.get("scene_blocks", []):
        for img in block.get("images", []):
            if img.get("image_index") == image_index:
                return block
    return None


def get_image_spec_by_index(story_bible: dict, image_index: int) -> Optional[dict]:
    """Get the image spec for a specific global image index.

    Args:
        story_bible: The Story Bible dict with scene_blocks
        image_index: Global 1-based image index

    Returns:
        The image spec dict, or None if not found
    """
    if not story_bible:
        return None

    for block in story_bible.get("scene_blocks", []):
        for img in block.get("images", []):
            if img.get("image_index") == image_index:
                return img
    return None


def get_all_images_from_blocks(story_bible: dict) -> list[dict]:
    """Get all images from scene_blocks in sequential order.

    Each returned dict includes the image spec PLUS block context:
    - block_id, location, lighting, mood, characters_present

    Args:
        story_bible: The Story Bible dict with scene_blocks

    Returns:
        List of image dicts with block context, sorted by image_index
    """
    if not story_bible:
        return []

    images = []
    for block in story_bible.get("scene_blocks", []):
        block_context = {
            "block_id": block.get("block_id"),
            "block_location": block.get("location", ""),
            "block_lighting": block.get("lighting", ""),
            "block_mood": block.get("mood", "neutral"),
            "block_characters": block.get("characters_present", []),
            "block_location_id": block.get("location_id", ""),
            "block_act": block.get("act", 1),
        }
        for img in block.get("images", []):
            # Merge image spec with block context
            full_img = {**img, **block_context}
            images.append(full_img)

    # Sort by image_index to ensure sequential order
    images.sort(key=lambda x: x.get("image_index", 0))
    return images


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
    """Get the FIRST visual arc entry for a specific scene.

    DEPRECATED: Use get_scene_arcs() to get ALL arc entries for a scene.
    This function only returns the first match, which loses granularity
    when Claude generates multiple arc entries per scene (one per shot/cut).

    Args:
        story_bible: The full Story Bible dict
        scene_number: Scene number to look up

    Returns:
        The first arc dict for this scene, or empty dict if not found
    """
    if not story_bible:
        return {}

    arcs = story_bible.get("visual_arc", [])
    return next((a for a in arcs if a.get("scene") == scene_number), {})


def get_scene_arcs(story_bible: dict, scene_number: int) -> list[dict]:
    """Get ALL visual arc entries for a specific scene.

    Claude generates multiple arc entries per scene (one per shot/location cut).
    This function returns all of them so they can be applied per-concept.

    Args:
        story_bible: The full Story Bible dict
        scene_number: Scene number to look up

    Returns:
        List of arc dicts for this scene (may be empty, may have 1+)
    """
    if not story_bible:
        return []

    arcs = story_bible.get("visual_arc", [])
    return [a for a in arcs if a.get("scene") == scene_number]


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
