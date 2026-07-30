"""StoryEngine-native Story Bible generator (checklist D10-2ab).

Backend-native replacement for the legacy generator at
``skills/video-pipeline/script/story_bible.py`` (historically reached via
``pipeline_executor.run_story_bible`` -> ``storyboard.bot.
_generate_story_bible_for_storyboard``, a sys.path import into the legacy
pipeline root, persisted through the Airtable-shim
``supabase_adapter.update_idea_fields`` — a full-column replace of
``videos.story_bible``). This module owns the SAME extended-prompt
generation, in ONE Claude call, but lives entirely inside ``backend/`` so
``run_story_bible`` no longer needs either the legacy import or the shim.

Schema contract (D10-1 design sweep, file:line-verified consumers):
  - ``characters`` / ``locations`` / ``scene_blocks`` are the SAME sub-key
    shape the legacy V2 (``use_scene_blocks=True``) normalizer produces.
    V2 is what's actually in production — the one real call site
    (``storyboard.bot._generate_story_bible_for_storyboard``) always passes
    ``use_scene_blocks=True``, so scene_blocks (not V1's ``visual_arc``) is
    the schema every current consumer already tolerates. The normalizer
    logic below is a NATIVE re-implementation of ``script.story_bible.
    _validate_and_normalize_scene_blocks`` — same field defaults, same
    warnings, no cross-root import (backend never reaches into
    skills/video-pipeline for this step; the one exception every other
    ``run_*`` stage already relies on is the shared
    ``shared.clients.anthropic_client.AnthropicClient`` bridge itself,
    unrelated to this module).
  - Three NEW top-level sections no consumer has seen before: ``narrative``,
    ``relationships``, ``arcs``. Every tolerant-key-access consumer found in
    the sweep (routes/characters.py:679, routes/environments.py:687,
    production_guide.py:391, scripts/coverage_to_app.py:906,
    channel_profile_documents.py:605, skills/video-pipeline/storyboard/
    bot.py:539) reads named keys off the dict and ignores the rest, so
    adding keys is safe. But persistence is a full ``UPDATE videos SET
    story_bible = $1`` (column replace, no merge) — so this module must
    assemble the WHOLE document in one shot.
  - ``relationships``/``arcs`` reference character ids from the SAME
    generation's ``characters`` section. Dangling references (an id the
    model invented but didn't also put in ``characters``) are DROPPED with
    a logged warning — generation must never fail over this.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

# Same-root reuse — mirrors script_quality.py's own
# `from originality import ..., _extract_json` (never a cross-root import).
from originality import _extract_json


# ---------------------------------------------------------------------------
# Prompts — ported from skills/video-pipeline/script/story_bible.py's
# STORY_BIBLE_SYSTEM_PROMPT (:42-83) and STORY_BIBLE_USER_PROMPT_V2
# (:185-278), same wording and same rules (including the forward-continuity
# rule at :266 and the recap/outro rule at :267), extended with instructions
# for the three new sections.
# ---------------------------------------------------------------------------

NATIVE_STORY_BIBLE_SYSTEM_PROMPT = """You are a cinematographer AND story editor planning the visual storytelling and narrative structure for a documentary-style YouTube video. Read the entire script below and produce a Story Bible that ensures visual consistency, narrative escalation, and story-logic coherence across the whole video.

Your bible will be used by another AI to write specific image prompts, and by editorial tooling to reason about character relationships and arcs. Every character and location description you write will be COPIED EXACTLY into multiple image prompts. So be specific, consistent, and visually concrete.

Be SPECIFIC. Don't write "formal suit" — write "dark charcoal three-button suit with crisp white dress shirt, dark navy silk tie, and gold watch visible on left wrist." The image model needs consistent, specific details.

CRITICAL VISUAL RULE — SHOW THE ACTION, NOT THE REACTION:
When designing scene blocks, each image should show the ACTION the narration describes, not a character reacting to it in an office.

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

"What Sun Tzu identified as the supreme art of war" → Extreme close-up of hands in dark suit resting on open leather-bound book, page showing calligraphic text, warm amber desk lamp casting sharp shadows, mahogany desk surface

BEYOND VISUALS — YOU ALSO OWN THE STORY LOGIC:
In addition to the visual sections, you produce three narrative-structure sections: the story's genre/tone/themes/conflict, the web of relationships between the characters you identified, and each character's emotional arc across the video. These are read by editorial tooling, not an image model — write them as clean structured facts, not prose paragraphs."""


NATIVE_STORY_BIBLE_USER_PROMPT = """Read this entire video script and produce a Story Bible.

VIDEO LENGTH: {video_duration_minutes} minutes
TOTAL IMAGES REQUIRED: {total_images}

FULL SCRIPT:
{full_script_text}

Produce a JSON response with these six sections:

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

## 3. "scene_blocks"

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

## 4. "narrative"

The story's structural facts as ONE object:
- "genre": one or two words (e.g. "geopolitical thriller", "explainer")
- "tone": one or two words (e.g. "tense", "clinical", "hopeful")
- "themes": list of 2-5 short theme phrases (e.g. ["power vacuum", "cost of complacency"])
- "conflict": one sentence naming the central conflict driving the video
- "stakes": one sentence naming what is lost if the conflict resolves badly
- "time_period": the setting's time period (e.g. "present day", "1973-2026")
- "world_rules": list of 0-5 short factual constraints the story operates under (e.g. ["Strait of Hormuz carries 20% of world oil"]) — omit if none apply

## 5. "relationships"

The web of relationships BETWEEN the characters you identified in section 1. One entry per meaningful pair:
- "characters": exactly two character ids from section 1's "id" values, e.g. ["russian_leader", "eu_official"]
- "dynamic": one short phrase naming the relationship (e.g. "uneasy allies", "adversaries", "mentor and pupil")
- "tension_source": one sentence naming what creates friction between them
- "evolves_to": one short phrase naming where the relationship ends up by the video's end (can equal the start if it doesn't change)

Only use character ids that also appear in section 1's "characters" list. Omit this section (empty list) if the video has fewer than 2 characters.

## 6. "arcs"

Each character's emotional/status arc across the video, as ONE object keyed by character id (using the SAME ids from section 1):
- "start_state": one short phrase for where this character starts (e.g. "confident, in control")
- "end_state": one short phrase for where this character ends up (e.g. "isolated, cornered")
- "turning_scenes": list of scene numbers (integers) where this character's arc visibly turns

Only key this object with character ids that also appear in section 1's "characters" list. Omit a character here if their state never changes.

Before outputting, VERIFY:
- Total blocks: 12-24 (aim for {target_blocks})
- Total images across all blocks: EXACTLY {total_images}
- image_index values: 1 through {total_images} with no gaps
- Every block starts with camera: "wide"
- No block has more than 5 images or fewer than 2
- Act transitions (1→2, 2→3, etc.) align with block boundaries
- No two consecutive blocks share the same location_id
- Every character id used in "relationships" and "arcs" also appears in "characters"

Respond ONLY with valid JSON. No markdown fences, no explanation."""


def _compute_total_images(video_length_minutes: int) -> int:
    """Trivial re-derivation of the legacy VideoConfig(total_clips) formula
    (orchestrator.pipeline_config.VideoConfig: total_clips = total_seconds //
    clip_duration_seconds, with the default 10s clip duration) — inlined
    rather than imported so this module never reaches into the legacy root
    for a one-line arithmetic fact."""
    minutes = int(video_length_minutes or 10)
    minutes = max(1, min(30, minutes))
    total_seconds = minutes * 60
    return max(6, total_seconds // 10)


def _parse_json_response(response_text: str) -> dict:
    """Extract a JSON object from an LLM response (handles ``` fences)."""
    try:
        return json.loads(_extract_json(response_text))
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}


# ---------------------------------------------------------------------------
# Normalizers — native re-implementation of script.story_bible.
# _validate_and_normalize_scene_blocks (:467-564). Same field defaults, same
# warning conditions, same "first image = wide" enforcement.
# ---------------------------------------------------------------------------

def _normalize_characters(bible: dict) -> None:
    if "characters" not in bible or not isinstance(bible.get("characters"), list):
        bible["characters"] = []
    for char in bible["characters"]:
        if not isinstance(char, dict):
            continue
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


def _normalize_locations(bible: dict) -> None:
    if "locations" not in bible or not isinstance(bible.get("locations"), list):
        bible["locations"] = []
    for loc in bible["locations"]:
        if not isinstance(loc, dict):
            continue
        if "description" not in loc:
            loc["description"] = "interior setting"
        if "lighting" not in loc:
            loc["lighting"] = "ambient lighting"
        if "color_temperature" not in loc:
            loc["color_temperature"] = "neutral"
        if "type" not in loc:
            loc["type"] = "INTERIOR"


def _normalize_scene_blocks(bible: dict, expected_images: int) -> None:
    if "scene_blocks" not in bible or not isinstance(bible.get("scene_blocks"), list):
        bible["scene_blocks"] = []

    locations = bible.get("locations") or []
    total_images = 0
    for i, block in enumerate(bible["scene_blocks"]):
        if not isinstance(block, dict):
            continue
        if "block_id" not in block:
            block["block_id"] = f"block_{i + 1}"
        if "act" not in block:
            block["act"] = 1
        if "location_id" not in block:
            block["location_id"] = locations[0]["id"] if locations else "unknown"
        if "location" not in block:
            loc = next((l for l in locations if l.get("id") == block["location_id"]), None)
            block["location"] = loc["description"] if loc else "unspecified environment"
        if "lighting" not in block:
            loc = next((l for l in locations if l.get("id") == block["location_id"]), None)
            block["lighting"] = loc["lighting"] if loc else "ambient lighting"
        if "mood" not in block:
            block["mood"] = "neutral"
        if "characters_present" not in block:
            block["characters_present"] = []
        if "images" not in block or not isinstance(block.get("images"), list):
            block["images"] = []

        for j, img in enumerate(block["images"]):
            if not isinstance(img, dict):
                continue
            if "camera" not in img:
                img["camera"] = "wide" if j == 0 else "medium"
            if "action" not in img:
                img["action"] = "scene continues"
            if "narration_excerpt" not in img:
                img["narration_excerpt"] = ""

        if block["images"] and block["images"][0].get("camera") != "wide":
            print(
                f"  [story_bible_native] block {block['block_id']}: fixing first "
                f"image to wide (was {block['images'][0].get('camera')})",
                flush=True,
            )
            block["images"][0]["camera"] = "wide"

        total_images += len(block["images"])

    if total_images != expected_images:
        print(
            f"  [story_bible_native] scene blocks have {total_images} images, "
            f"expected {expected_images}",
            flush=True,
        )

    blocks = bible["scene_blocks"]
    for i in range(1, len(blocks)):
        if blocks[i].get("location_id") == blocks[i - 1].get("location_id"):
            print(
                f"  [story_bible_native] consecutive blocks {blocks[i-1].get('block_id')} "
                f"and {blocks[i].get('block_id')} share location {blocks[i].get('location_id')}",
                flush=True,
            )


# ---------------------------------------------------------------------------
# NEW sections — narrative / relationships / arcs. Relationships and arcs
# validate against the character ids the SAME generation produced; dangling
# references are dropped with a warning, never a failure.
# ---------------------------------------------------------------------------

def _normalize_narrative(bible: dict) -> None:
    narrative = bible.get("narrative")
    if not isinstance(narrative, dict):
        narrative = {}
    normalized = {
        "genre": str(narrative.get("genre") or ""),
        "tone": str(narrative.get("tone") or ""),
        "themes": [str(t) for t in (narrative.get("themes") or []) if str(t).strip()],
        "conflict": str(narrative.get("conflict") or ""),
        "stakes": str(narrative.get("stakes") or ""),
        "time_period": str(narrative.get("time_period") or ""),
        "world_rules": [str(r) for r in (narrative.get("world_rules") or []) if str(r).strip()],
    }
    bible["narrative"] = normalized


def _normalize_relationships(bible: dict, char_ids: set) -> None:
    raw = bible.get("relationships")
    if not isinstance(raw, list):
        raw = []

    normalized: List[Dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        pair = entry.get("characters")
        if not isinstance(pair, list) or len(pair) != 2:
            print(
                f"  [story_bible_native] dropping relationship with malformed "
                f"characters field: {pair!r}",
                flush=True,
            )
            continue
        a, b = str(pair[0]), str(pair[1])
        if a not in char_ids or b not in char_ids:
            print(
                f"  [story_bible_native] dropping relationship {a!r}<->{b!r}: "
                f"dangling character id (not in characters section)",
                flush=True,
            )
            continue
        normalized.append({
            "characters": [a, b],
            "dynamic": str(entry.get("dynamic") or ""),
            "tension_source": str(entry.get("tension_source") or ""),
            "evolves_to": str(entry.get("evolves_to") or ""),
        })
    bible["relationships"] = normalized


def _normalize_arcs(bible: dict, char_ids: set) -> None:
    raw = bible.get("arcs")
    if not isinstance(raw, dict):
        raw = {}

    normalized: Dict[str, Dict[str, Any]] = {}
    for char_id, arc in raw.items():
        key = str(char_id)
        if key not in char_ids:
            print(
                f"  [story_bible_native] dropping arc for {key!r}: dangling "
                f"character id (not in characters section)",
                flush=True,
            )
            continue
        if not isinstance(arc, dict):
            arc = {}
        turning_scenes = []
        for s in (arc.get("turning_scenes") or []):
            try:
                turning_scenes.append(int(s))
            except (TypeError, ValueError):
                continue
        normalized[key] = {
            "start_state": str(arc.get("start_state") or ""),
            "end_state": str(arc.get("end_state") or ""),
            "turning_scenes": turning_scenes,
        }
    bible["arcs"] = normalized


def normalize_story_bible(bible: dict, expected_images: int) -> dict:
    """Apply every normalizer in place and return the same dict.

    Order matters: characters must be normalized (and their ids collected)
    before relationships/arcs can validate against them.
    """
    if not isinstance(bible, dict):
        bible = {}

    _normalize_characters(bible)
    _normalize_locations(bible)
    _normalize_scene_blocks(bible, expected_images)

    char_ids = {c.get("id") for c in bible["characters"] if isinstance(c, dict) and c.get("id")}

    _normalize_narrative(bible)
    _normalize_relationships(bible, char_ids)
    _normalize_arcs(bible, char_ids)

    return bible


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def generate_story_bible_native(
    anthropic_client: Any,
    full_script_text: str,
    video_title: str = "",
    video_length_minutes: int = 10,
) -> dict:
    """Generate a complete Story Bible in ONE extended Claude call.

    ``anthropic_client`` is any object with an async
    ``generate(prompt, system_prompt, max_tokens, temperature) -> str``
    method — the same duck-typed contract ``script_quality.critique_script``
    already uses (the tenant's ``shared.clients.anthropic_client.
    AnthropicClient``, reached via ``pipeline_executor``'s
    ``self._pipeline.anthropic``).

    Returns the normalized bible dict (characters, locations, scene_blocks,
    narrative, relationships, arcs). Raises on a client error or an
    unparseable/empty response — the caller (``run_story_bible``) is
    responsible for catching that and reporting "failed", never
    "completed", exactly as it already does for every other failure mode.
    """
    if not full_script_text or len(full_script_text.strip()) < 100:
        raise ValueError(f"Script too short for story bible: {len(full_script_text or '')} chars")

    total_images = _compute_total_images(video_length_minutes)
    target_blocks = max(12, min(24, total_images // 4))

    prompt = NATIVE_STORY_BIBLE_USER_PROMPT.format(
        full_script_text=full_script_text,
        total_images=total_images,
        video_duration_minutes=int(video_length_minutes or 10),
        target_blocks=target_blocks,
    )

    raw = await anthropic_client.generate(
        prompt=prompt,
        system_prompt=NATIVE_STORY_BIBLE_SYSTEM_PROMPT,
        max_tokens=16000,
        temperature=0.3,  # low, for consistency — matches the legacy generator
    )

    bible = _parse_json_response(raw)
    if not bible:
        raise ValueError("Story bible response could not be parsed as JSON")

    bible = normalize_story_bible(bible, total_images)

    print(
        f"  [story_bible_native] generated for '{video_title}': "
        f"{len(bible['characters'])} characters, {len(bible['locations'])} locations, "
        f"{len(bible['scene_blocks'])} scene blocks, "
        f"{len(bible['relationships'])} relationships, {len(bible['arcs'])} arcs",
        flush=True,
    )

    return bible
