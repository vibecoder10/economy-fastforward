"""Scene-by-scene concept expansion.

Takes a single scene's narration text (from the Airtable Script table) and
expands it into 6-10 visual concepts. Each concept pairs an exact substring
of the narration with a filmable visual description.

This replaces the old batch-based system that glued 20 script records into
one big script and re-split them via LLM. The new system processes one
scene at a time — if one fails, only that scene retries.
"""

from __future__ import annotations

import json
from typing import Optional
from orchestrator.pipeline_constants import Models

# Re-export public symbols that callers depend on
from .expander_config import (
    _get_profile,
    get_valid_styles,
    get_valid_compositions,
    get_style_distribution,
    get_default_style,
    _pick_composition,
    _estimate_concept_count,
    _build_style_weights_text,
    _build_prompt,
    _parse_response,
    # Constants
    VALID_STYLES,
    VALID_COMPOSITIONS,
    STYLE_DISTRIBUTION,
    MIN_CONCEPTS,
    MAX_CONCEPTS,
    MIN_WORDS_PER_CONCEPT,
    MAX_WORDS_PER_CONCEPT,
)

from .concept_repair import (
    _repair_concept_text,
    _repair_all_concepts,
    _validate_concepts,
    _validate_concept_durations,
    _split_at_clause_boundary,
    _sentence_boundary_split,
)


async def _expand_with_scene_blocks(
    anthropic_client,
    scene_number: int,
    scene_text: str,
    story_bible: dict,
    visual_seeds: str,
    accent_color: str,
    act_number: int,
    voice_duration: Optional[float] = None,
) -> list[dict]:
    """Expand scene using V2 scene_blocks format.

    Two-layer approach:
    1. **Text splitting** — deterministic sentence-based splitter produces
       verbatim segments from the scene script (same as V1 path).
    2. **Visual context** — Story Bible scene_blocks provide location,
       lighting, characters per image.  Each deterministic segment is
       mapped to the closest Story Bible image by text overlap so it
       inherits the block context.

    This ensures sentence_text is ALWAYS a verbatim substring of the
    scene script while visual descriptions get the consistency benefits
    of the Story Bible's shared-block system.
    """
    from script.story_bible import get_all_images_from_blocks

    # --- Step 1: Deterministic text splitting (verbatim segments) -----------
    from shared.clients.deterministic_splitter import segment_scene_deterministic

    segments = segment_scene_deterministic(scene_text, voice_duration)
    if not segments:
        return [{
            "concept_index": 1,
            "sentence_text": scene_text,
            "visual_description": "Scene continues",
            "visual_style": get_default_style(),
            "composition": "medium",
            "mood": "neutral",
        }]

    print(f"    Scene {scene_number}: {len(segments)} segments from deterministic splitter "
          f"({', '.join(str(s['word_count']) + 'w' for s in segments)})")

    # --- Step 2: Pre-filter Story Bible images to THIS scene ---------------
    all_images = get_all_images_from_blocks(story_bible)

    scene_images: list[dict] = []
    if all_images:
        scene_lower = " ".join(scene_text.split()).lower()
        for img in all_images:
            excerpt = img.get("narration_excerpt", "").strip()
            if not excerpt:
                continue
            excerpt_lower = " ".join(excerpt.split()).lower()

            # Exact substring
            if excerpt_lower in scene_lower:
                scene_images.append(img)
                continue

            # First 4 words as anchor
            first_words = " ".join(excerpt_lower.split()[:4])
            if first_words and first_words in scene_lower:
                scene_images.append(img)
                continue

            # Last 4 words as anchor
            last_words = " ".join(excerpt_lower.split()[-4:])
            if last_words and last_words in scene_lower:
                scene_images.append(img)

        if not scene_images:
            # Fallback: filter by act
            scene_images = [img for img in all_images if img.get("block_act") == act_number]
            if scene_images:
                print(f"      ⚠️ Scene {scene_number}: No excerpt match, falling back to act {act_number}")

    # --- Step 3: Map each segment to closest Story Bible image (block context) ---
    def _find_block_context(segment_text: str, images: list[dict]) -> dict:
        """Find the Story Bible image whose narration_excerpt best overlaps this segment."""
        if not images:
            return {}

        seg_lower = " ".join(segment_text.split()).lower()
        seg_words = set(seg_lower.split())
        best_img = None
        best_score = 0.0

        for img in images:
            excerpt = img.get("narration_excerpt", "").strip()
            if not excerpt:
                continue
            excerpt_lower = " ".join(excerpt.split()).lower()

            # Exact substring match = best possible
            if excerpt_lower in seg_lower or seg_lower in excerpt_lower:
                return img

            # Word overlap score
            excerpt_words = set(excerpt_lower.split())
            if not excerpt_words:
                continue
            overlap = len(seg_words & excerpt_words) / max(len(excerpt_words), 1)
            if overlap > best_score:
                best_score = overlap
                best_img = img

        return best_img if best_img and best_score >= 0.3 else (images[0] if images else {})

    # Build segment → block context mapping
    segment_contexts: list[dict] = []
    used_images: set[int] = set()
    for seg in segments:
        ctx = _find_block_context(seg["text"], scene_images)
        segment_contexts.append(ctx)
        if ctx:
            idx = ctx.get("image_index")
            if idx is not None:
                used_images.add(idx)

    blocks_used = set(c.get("block_id", "?") for c in segment_contexts if c)
    print(f"    Scene {scene_number}: mapped to blocks: {', '.join(blocks_used)}")

    # --- Step 4: Generate visual descriptions per block (LLM) ---------------
    profile = _get_profile()
    is_holographic = profile is None or profile.profile_id == "holographic_hud"

    try:
        from script.story_bible import format_bible_for_prompt
        bible_context = format_bible_for_prompt(story_bible, scene_number)
    except ImportError:
        bible_context = ""

    # Group segments by block_id for batch LLM calls
    from collections import OrderedDict
    block_groups: OrderedDict[str, list[tuple[int, dict, dict]]] = OrderedDict()
    for i, (seg, ctx) in enumerate(zip(segments, segment_contexts)):
        bid = ctx.get("block_id", "unknown") if ctx else "unknown"
        if bid not in block_groups:
            block_groups[bid] = []
        block_groups[bid].append((i, seg, ctx))

    # LLM visual descriptions keyed by segment index
    # Each value is a dict: {"description": str, "scene_type": str}
    segment_descriptions: dict[int, dict] = {}

    # Safety cap: if a block has >20 segments, split into 2 calls with cross-reference
    _MAX_SEGMENTS_PER_CALL = 20

    for block_id, group in block_groups.items():
        first_ctx = group[0][2] if group[0][2] else {}
        block_location = first_ctx.get("block_location", "")
        block_lighting = first_ctx.get("block_lighting", "")
        block_characters = first_ctx.get("block_characters", [])
        block_location_id = first_ctx.get("block_location_id", "")
        block_mood = first_ctx.get("block_mood", "neutral")

        # Send all segments in one call so Claude can design a coherent visual arc.
        # Only split if >20 segments (safety cap — shouldn't happen with current splitter).
        sub_batches = [group[i:i+_MAX_SEGMENTS_PER_CALL] for i in range(0, len(group), _MAX_SEGMENTS_PER_CALL)]
        block_prev_descriptions: list[str] = []  # Cross-reference context for overflow batches

        for batch_idx, batch in enumerate(sub_batches):
            image_sequence = []
            for j, (seg_idx, seg, ctx) in enumerate(batch):
                cam = ctx.get("camera", "medium") if ctx else "medium"
                action = ctx.get("action", "") if ctx else ""
                narration = seg['text']
                image_sequence.append(
                    f"  Image {j+1} (camera: {cam}):\n"
                    f"    Narration: \"{narration}\"\n"
                    f"    Action note: {action}"
                )

            try:
                if not is_holographic and profile and profile.scene_description.system_prompt:
                    visual_desc_prompt = f"{profile.scene_description.system_prompt}\n\n"

                    if bible_context:
                        visual_desc_prompt += f"{bible_context}\n\n"

                    chars_str = ", ".join(block_characters) if block_characters else "none (environment/data shot)"
                    visual_desc_prompt += (
                        f"## BLOCK: {block_id}\n"
                        f"All images share this setting:\n"
                        f"- Location: {block_location_id} — {block_location}\n"
                        f"- Characters present: {chars_str}\n"
                        f"- Lighting: {block_lighting}\n"
                        f"- Mood: {block_mood}\n\n"
                        f"## IMAGE SEQUENCE ({len(batch)} images):\n"
                        + "\n".join(image_sequence) + "\n\n"
                    )

                    visual_desc_prompt += (
                        "Write a visual description (40-70 words) for EACH image.\n\n"

                        "SCENE TYPE — classify each image as one of:\n"
                        "- power_move: Two or more characters in tension/confrontation\n"
                        "- lone_figure: Single character at a turning point\n"
                        "- environment: Location establishing shot, no characters or tiny distant only\n"
                        "- data_hud: Data visualization, statistics, maps with overlays\n"
                        "- object_closeup: Physical object carrying narrative weight\n\n"

                        "CORE RULE — find the PRIMARY VERB in each narration and SHOW THAT ACTION:\n"
                        "- \"launched strikes\" → jets over desert, explosions on target\n"
                        "- \"sanctions crushed\" → empty factory floor, idle machinery, rusting equipment\n"
                        "- \"signed a treaty\" → two figures at table with document, pens, flags\n"
                        "- \"oil prices surged\" → tankers at sea, pump jacks working, price ticker\n"
                        "- \"protests erupted\" → scattered debris on empty street, overturned barriers\n"
                        "- Each narration has a DIFFERENT verb/action, so each image naturally differs\n"
                        "- If two narrations describe the same subject, use the camera angle to show\n"
                        "  a different aspect (wide = full scene, medium = key element, closeup = detail)\n\n"

                        "STORYTELLING DETAILS (one per image):\n"
                        "- Include ONE unstated contextual detail the narration doesn't mention\n"
                        "  (a circled location on a map, an empty chair, a clock showing a specific time,\n"
                        "   a document stamp, a price tag, a flag at half-mast)\n"
                        "- Describe specific lighting: warm amber/tungsten for interiors, cold steel blue\n"
                        "  for exteriors/threat, golden hour for transitions, harsh overhead for exposure\n"
                        "- For characters: describe their facial EXPRESSION and one piece of clothing detail\n\n"

                        "VISUAL ARC across all images in this block:\n"
                        "- Open with an ESTABLISHING shot (environment or wide)\n"
                        "- Build complexity through the middle (power moves, data reveals)\n"
                        "- End with the emotional payoff (lone figure realization, or personal stakes)\n"
                        "- Never put two identical scene types back to back\n\n"

                        "CONSISTENCY:\n"
                        "- Same location and lighting across all images in this block\n"
                        "- Characters keep EXACT same clothing and appearance\n\n"

                        "RULES:\n"
                        "1. Use EXACT character costumes from the Story Bible. Never omit clothing.\n"
                        "2. Use the shared location description — don't invent a different setting.\n"
                        "3. If characters_present is 'none', NO character figures — environment/data only.\n"
                        "4. Do NOT include style prefix (e.g. 'Cinematic animated illustration...') — added automatically.\n"
                        "5. Never mention letterbox bars, black bars, or widescreen framing — the image fills the full frame.\n"
                        "6. CONTINUITY — the story timeline only moves FORWARD. Once the story has\n"
                        "   RESOLVED something (a character healed, freed, reunited, saved, a problem\n"
                        "   fixed), NEVER depict the earlier unresolved state again as if it is happening\n"
                        "   (no re-injuring, re-bandaging, re-breaking, re-trapping). The ending state is\n"
                        "   permanent — later images must respect what earlier images already resolved.\n"
                        "7. RECAP / REVIEW / DEFINITION / OUTRO / CALL-TO-ACTION narration — when the\n"
                        "   narration is teaching a word, reviewing, summarizing, or addressing the viewer\n"
                        "   (e.g. \"Word one: Injured…\", \"That was a wonderful story\", \"subscribe\",\n"
                        "   \"tell us in the comments\"), this is NOT story action — do NOT literally\n"
                        "   re-enact the verb or re-stage a past plot moment. Instead use a NON-STORY\n"
                        "   visual: a clean word/title card, a character calmly facing the viewer, a simple\n"
                        "   symbolic prop, or a CALLBACK to an already-shown RESOLVED happy moment. A\n"
                        "   vocabulary word like \"bandage\" becomes a labeled card or a gentle callback,\n"
                        "   NEVER the characters re-performing the injury/treatment.\n\n"
                    )

                    # Add cross-reference descriptions from earlier overflow batches
                    if block_prev_descriptions:
                        recent = block_prev_descriptions[-5:]
                        visual_desc_prompt += (
                            "PREVIOUS IMAGES already generated for this block (make yours DIFFERENT):\n"
                        )
                        for k, prev in enumerate(recent, 1):
                            visual_desc_prompt += f"  {k}. {prev}\n"
                        visual_desc_prompt += "\n"

                    visual_desc_prompt += (
                        f"Visual seeds: {visual_seeds[:200] if visual_seeds else 'none'}\n\n"
                        f"Return a JSON array of {len(batch)} objects, one per image.\n"
                        f"Each object has \"scene_type\" and \"description\".\n"
                        f"Example: [{{\"scene_type\": \"environment\", \"description\": \"...\"}}, ...]\n"
                        "Return ONLY the JSON array, nothing else."
                    )
                else:
                    visual_desc_prompt = (
                        "You are creating visual descriptions for HOLOGRAPHIC DATA DISPLAYS "
                        "in an intelligence operations center.\n\n"
                        f"## BLOCK: {block_id} ({len(batch)} images in sequence)\n"
                        + "\n".join(image_sequence) + "\n\n"
                        "Write a 40-70 word visual description for EACH image.\n"
                        "Each should describe DATA, DOCUMENTS, MAPS, or CHARTS on a holographic screen.\n"
                        "Maintain visual consistency — same display theme, evolving data across images.\n\n"
                    )
                    if block_prev_descriptions:
                        recent = block_prev_descriptions[-5:]
                        visual_desc_prompt += (
                            "PREVIOUS IMAGES (make yours DIFFERENT):\n"
                        )
                        for k, prev in enumerate(recent, 1):
                            visual_desc_prompt += f"  {k}. {prev}\n"
                        visual_desc_prompt += "\n"
                    visual_desc_prompt += (
                        f"Return a JSON array of {len(batch)} objects.\n"
                        f"Each object has \"scene_type\" (one of: power_move, lone_figure, "
                        f"environment, data_hud, object_closeup) and \"description\".\n"
                        f"Example: [{{\"scene_type\": \"data_hud\", \"description\": \"...\"}}, ...]\n"
                        "Return ONLY the JSON array, nothing else."
                    )

                raw_response = await anthropic_client.generate(
                    prompt=visual_desc_prompt,
                    model=Models.CLAUDE_SONNET,
                    max_tokens=200 * len(batch),
                    temperature=0.4,
                )

                raw = raw_response.strip()
                if raw.startswith("```"):
                    raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
                descriptions = json.loads(raw)

                if isinstance(descriptions, list) and len(descriptions) == len(batch):
                    for j, (seg_idx, _seg, _ctx) in enumerate(batch):
                        item = descriptions[j]
                        if isinstance(item, dict):
                            desc = item.get("description", "").strip()
                            scene_type = item.get("scene_type", "")
                        else:
                            # Backward compat: plain string
                            desc = str(item).strip()
                            scene_type = ""
                        segment_descriptions[seg_idx] = {"description": desc, "scene_type": scene_type}
                        block_prev_descriptions.append(desc)
                    batch_label = f" (batch {batch_idx+1}/{len(sub_batches)})" if len(sub_batches) > 1 else ""
                    print(f"      Block {block_id}{batch_label}: {len(descriptions)} visual descriptions generated")
                else:
                    print(f"      ⚠️ Block {block_id}: Expected {len(batch)} descriptions, "
                          f"got {len(descriptions) if isinstance(descriptions, list) else 'non-list'}")
                    if isinstance(descriptions, list):
                        for j, (seg_idx, _seg, _ctx) in enumerate(batch):
                            if j < len(descriptions):
                                item = descriptions[j]
                                if isinstance(item, dict):
                                    desc = item.get("description", "").strip()
                                    scene_type = item.get("scene_type", "")
                                else:
                                    desc = str(item).strip()
                                    scene_type = ""
                                segment_descriptions[seg_idx] = {"description": desc, "scene_type": scene_type}
                                block_prev_descriptions.append(desc)

            except Exception as e:
                print(f"      ⚠️ Block {block_id}: LLM call failed: {e}")

    # --- Step 5: Build concept dicts from deterministic segments + block context ---
    composition_map = {
        "wide": "wide", "medium": "medium", "closeup": "closeup",
        "close-up": "closeup", "extreme_closeup": "closeup", "extreme-closeup": "closeup",
        "overhead": "overhead", "low_angle": "low_angle", "low-angle": "low_angle",
        "portrait": "portrait", "environmental": "environmental",
    }

    # Cinematic rotation: if Story Bible repeats the same camera, cycle through alternatives
    _ROTATION_ORDER = ["wide", "medium", "closeup", "low_angle", "overhead", "medium", "wide"]

    def _enforce_composition_rotation(requested: str, prev: str | None) -> str:
        """Prevent consecutive identical compositions — rotate to next if repeated."""
        if prev is None or requested != prev:
            return requested
        # Same as previous — pick the next in rotation after the requested type
        try:
            idx = _ROTATION_ORDER.index(requested)
            return _ROTATION_ORDER[(idx + 1) % len(_ROTATION_ORDER)]
        except ValueError:
            return "medium" if requested != "medium" else "closeup"

    concepts = []
    prev_composition = None
    for i, (seg, ctx) in enumerate(zip(segments, segment_contexts)):
        camera = (ctx.get("camera", "medium") if ctx else "medium").lower()
        composition = composition_map.get(camera, "medium")
        composition = _enforce_composition_rotation(composition, prev_composition)
        prev_composition = composition
        camera_direction = (ctx.get("action", "") if ctx else "").strip()
        block_mood = (ctx.get("block_mood", "neutral") if ctx else "neutral")

        # sentence_text is ALWAYS the verbatim deterministic segment
        sentence_text = seg["text"]

        # Visual description + scene_type from LLM, fallback to narration excerpt
        desc_data = segment_descriptions.get(i, {})
        if isinstance(desc_data, dict):
            visual_description = desc_data.get("description", "")
            scene_type_from_llm = desc_data.get("scene_type", "")
        else:
            visual_description = str(desc_data)
            scene_type_from_llm = ""
        if not visual_description:
            visual_description = (ctx.get("narration_excerpt", "") if ctx else "") or "Scene continues"

        # Validate scene_type against known values
        _VALID_SCENE_TYPES = {"power_move", "lone_figure", "environment", "data_hud", "object_closeup"}
        if scene_type_from_llm not in _VALID_SCENE_TYPES:
            scene_type_from_llm = ""

        concept = {
            "concept_index": i + 1,
            "sentence_text": sentence_text,
            "visual_description": visual_description,
            "visual_style": get_default_style(),
            "composition": composition,
            "mood": block_mood,
            "duration": seg["duration"],
            # LLM-assigned scene type (narrative-aware)
            "scene_type": scene_type_from_llm,
            # Block context for prompt builder
            "block_id": ctx.get("block_id") if ctx else None,
            "block_location": (ctx.get("block_location", "") if ctx else ""),
            "block_lighting": (ctx.get("block_lighting", "") if ctx else ""),
            "block_characters": (ctx.get("block_characters", []) if ctx else []),
            "block_location_id": (ctx.get("block_location_id", "") if ctx else ""),
            "global_image_index": ctx.get("image_index") if ctx else None,
            "camera_direction": camera_direction,
        }
        concepts.append(concept)

    return concepts


async def expand_scene_concepts_deterministic(
    anthropic_client,
    scene_number: int,
    scene_text: str,
    visual_seeds: str,
    accent_color: str,
    act_number: int,
    total_scenes: int = 14,
    voice_duration: Optional[float] = None,
    story_bible: Optional[dict] = None,
) -> list[dict]:
    """Expand one scene's narration into visual concepts using deterministic word-duration-aware splitting.

    Supports two Story Bible formats:
    - V1 (visual_arc): Uses deterministic splitter + LLM for visual descriptions
    - V2 (scene_blocks): Uses pre-defined blocks with shared location/lighting

    For V2 scene_blocks, each image has block context (location, lighting, characters)
    already defined. The scene_number maps to images via narration text overlap.

    Args:
        anthropic_client: AnthropicClient instance with generate() method
        scene_number: Scene number from the Script table
        scene_text: Exact narration text from the Script table
        visual_seeds: Visual seed concepts from research brief
        accent_color: Accent color for this video (e.g. "cold_teal")
        act_number: Which act this scene belongs to (1-6)
        total_scenes: Total number of scenes in the video
        voice_duration: Optional actual voice duration in seconds (for accurate WPS)
        story_bible: Optional Story Bible dict with characters, locations, visual_arc OR scene_blocks

    Returns:
        List of concept dicts, each with:
        - concept_index (int, 1-based)
        - sentence_text (str, exact substring of scene_text)
        - visual_description (str, 40-70 word filmable description for V2, 20-35 for V1)
        - visual_style (str, profile substyle name - DESCRIPTIVE, not prescriptive)
        - composition (str, wide/medium/closeup/etc.)
        - mood (str)
        - For V2 scene_blocks, also includes:
          - scene_type (str, LLM-assigned: power_move/lone_figure/environment/data_hud/object_closeup)
          - block_id, block_location, block_lighting, block_characters
    """
    import sys
    from pathlib import Path

    # Import Story Bible helpers
    try:
        from script.story_bible import (
            format_bible_for_prompt,
            has_scene_blocks,
            get_all_images_from_blocks,
        )
    except ImportError:
        def format_bible_for_prompt(bible, scene): return ""
        def has_scene_blocks(bible): return False
        def get_all_images_from_blocks(bible): return []

    # Check if Story Bible uses V2 scene_blocks format
    if story_bible and has_scene_blocks(story_bible):
        return await _expand_with_scene_blocks(
            anthropic_client=anthropic_client,
            scene_number=scene_number,
            scene_text=scene_text,
            story_bible=story_bible,
            visual_seeds=visual_seeds,
            accent_color=accent_color,
            act_number=act_number,
            voice_duration=voice_duration,
        )

    # V1 path: Use deterministic splitter + LLM visual descriptions
    from shared.clients.deterministic_splitter import segment_scene_deterministic

    # Step 1: Use deterministic splitter to get text segments with guaranteed durations
    segments = segment_scene_deterministic(scene_text, voice_duration)

    if not segments:
        # Empty scene - return minimal concept
        return [{
            "concept_index": 1,
            "sentence_text": scene_text,
            "visual_description": "Empty scene",
            "visual_style": get_default_style(),
            "composition": _pick_composition(get_default_style(), 0, []),
            "mood": "neutral",
        }]

    # Step 2: Get profile for styling decisions
    profile = _get_profile()
    is_holographic = profile is None or profile.profile_id == "holographic_hud"

    # For non-holographic profiles, we still assign styles for tracking/analytics
    # but they are DESCRIPTIVE (post-hoc classification), not PRESCRIPTIVE
    default_fallback_style = get_default_style()
    recent_comps: list[str] = []

    # Step 3: Format Story Bible context for this scene
    bible_context = ""
    scene_arcs = []  # List of ALL arc entries for this scene
    if story_bible:
        bible_context = format_bible_for_prompt(story_bible, scene_number)
        # Get ALL visual arc entries for this scene (Claude generates multiple per scene)
        try:
            from script.story_bible import get_scene_arcs
            scene_arcs = get_scene_arcs(story_bible, scene_number)
        except ImportError:
            scene_arcs = []
        # Debug: Show Story Bible state
        total_arc_count = len(story_bible.get("visual_arc", []))
        print(f"      📖 Story Bible: {total_arc_count} total arcs, {len(scene_arcs)} for scene {scene_number}")
        if scene_arcs:
            cameras = [a.get("camera_distance", "?") for a in scene_arcs]
            print(f"      📐 Scene {scene_number} arc cameras: {cameras}")
    else:
        print(f"      ⚠️ No Story Bible passed to scene expander")
    # Map arc camera distance to composition (Airtable Shot Type values)
    arc_composition_map = {
        # Wide shots
        "wide": "wide",
        "extreme-wide": "wide",
        "extreme wide": "wide",
        "establishing": "wide",
        # Medium shots
        "medium": "medium",
        "mid": "medium",
        # Close-up shots
        "close-up": "closeup",
        "close up": "closeup",
        "closeup": "closeup",
        "close": "closeup",
        "extreme-close-up": "closeup",
        "extreme close-up": "closeup",
        "extreme closeup": "closeup",
        # Other compositions
        "overhead": "overhead",
        "low-angle": "low_angle",
        "low angle": "low_angle",
        "portrait": "portrait",
    }

    # Step 4: Generate visual_description for each segment using LLM
    concepts = []
    prev_descriptions: list[str] = []  # Track previous descriptions for deduplication

    for i, seg in enumerate(segments):
        # Get the arc entry for THIS concept (cycle through if more concepts than arcs)
        if scene_arcs:
            arc_index = i % len(scene_arcs)
            concept_arc = scene_arcs[arc_index]
            arc_camera = concept_arc.get("camera_distance", "").lower().strip()
        else:
            concept_arc = {}
            arc_camera = ""

        # Use visual arc camera distance if available, otherwise fall back to rotation
        if arc_camera and arc_camera in arc_composition_map:
            composition = arc_composition_map[arc_camera]
            print(f"        Concept {i+1}: arc[{arc_index}] camera='{arc_camera}' → {composition}")
        else:
            composition = _pick_composition(default_fallback_style, i, recent_comps)
            if arc_camera:
                print(f"        Concept {i+1}: ⚠️ Unknown camera '{arc_camera}', fallback={composition}")
            elif not scene_arcs:
                pass  # No arcs at all, silently use rotation
        recent_comps.append(composition)

        # Generate visual description via LLM — NO SCENE TYPE CONSTRAINTS
        try:
            if not is_holographic and profile and profile.scene_description.system_prompt:
                # Build prompt with Story Bible context but NO scene type constraints
                # Claude decides what to write based on narration content
                visual_desc_prompt = (
                    f"{profile.scene_description.system_prompt}\n\n"
                )

                # Add Story Bible context if available
                if bible_context:
                    visual_desc_prompt += f"{bible_context}\n\n"

                # Add specific arc data for THIS concept
                if concept_arc:
                    arc_location = concept_arc.get("location_id", "")
                    arc_chars = concept_arc.get("characters_present", [])
                    arc_mood = concept_arc.get("mood", "")
                    arc_color = concept_arc.get("color_temperature", "")
                    arc_note = concept_arc.get("visual_note", "")
                    visual_desc_prompt += (
                        f"## THIS SHOT'S ARC:\n"
                        f"- Location: {arc_location}\n"
                        f"- Characters: {', '.join(arc_chars) if arc_chars else 'none (environment/data shot)'}\n"
                        f"- Mood: {arc_mood}\n"
                        f"- Color temperature: {arc_color}\n"
                        f"- Camera: {arc_camera}\n"
                        f"- What changes: {arc_note}\n\n"
                    )

                visual_desc_prompt += (
                    "VISUAL APPROACH — Before writing this prompt, identify the PRIMARY VERB in the narration:\n"
                    "- If the verb is an action (launched, struck, surged, collapsed, invaded, signed, declared) → show that action happening in the physical world\n"
                    "- If the verb is internal (realized, calculated, planned, knew) → THEN show a character in a contemplative setting\n"
                    "- If the verb describes data (cost, earned, spent, numbered) → show the physical manifestation of that data (infrastructure, currency, military hardware) OR a data display\n\n"
                    "Ask yourself: \"What would a documentary filmmaker POINT THE CAMERA AT for this line?\" The answer is almost never \"a person sitting at a desk.\" It's the event itself.\n\n"
                    "Examples of good visual verb matching:\n"
                    "- \"launched strikes\" → jets over desert, explosions on bunker complex\n"
                    "- \"oil prices surged\" → oil tankers at sea, pump jacks working, gas station price display changing\n"
                    "- \"signed a treaty\" → two figures at table with document and pens, flags behind them\n"
                    "- \"declared Russia the only winner\" → press conference podium, or newsroom with broadcast on screens\n"
                    "- \"sanctions were working\" → empty factory floor, closed shipping port, currency notes scattered\n"
                    "- \"enriched uranium\" → centrifuge arrays in underground facility, hazmat suited figures\n"
                    "- \"Patriot missiles fired\" → missile defense battery launching at night, streak of light across sky\n"
                    "- \"protests killed thousands\" → empty street with scattered debris, memorial candles, abandoned shoes\n"
                    "- \"oil revenues collapsed\" → rusting idle oil equipment, snow-covered abandoned derricks\n\n"
                    "Examples of BAD visual choices (avoid these):\n"
                    "- \"launched strikes\" → figure at desk reading about strikes ❌\n"
                    "- \"oil prices surged\" → chart on a holographic screen ❌ (save data displays for specific numbers)\n"
                    "- \"declared Russia the winner\" → figure in office watching TV ❌\n"
                    "- \"sanctions were working\" → figure reviewing documents at desk ❌\n\n"
                    "CRITICAL RULES:\n"
                    "1. If a character from the bible appears, use their EXACT costume description. Do not change or omit clothing.\n"
                    "2. If a location from the bible appears, use its EXACT description and signature detail.\n"
                    "3. Match the mood, color temperature, and camera distance from THIS SHOT'S ARC above.\n"
                    "4. If characters_present is 'none', do NOT include character figures — this is a data/environment shot.\n"
                    "5. Include the 'what changes' note — what makes this image DIFFERENT from the previous one.\n\n"
                )

                # Add clothing requirement for characters
                visual_desc_prompt += (
                    "CLOTHING RULE: Every character figure MUST have specific clothing described. "
                    "Never describe a character without clothing. If unsure, use 'wearing dark formal suit with white shirt.'\n\n"
                    "Write a 20-35 word visual description for this narration segment. "
                    "You decide whether this moment needs characters, environment, data, or objects — "
                    "write whatever best tells THIS story moment.\n\n"
                    "Do NOT start with the style prefix (e.g. 'Cinematic animated illustration...') — "
                    "that will be added automatically based on what you write.\n"
                    "End with a camera angle and lighting description that matches the arc.\n"
                    "Return ONLY the description, nothing else.\n\n"
                )

                # Add previous descriptions for deduplication
                if prev_descriptions:
                    recent = prev_descriptions[-3:]  # Last 3 descriptions
                    visual_desc_prompt += (
                        "PREVIOUS IMAGES IN THIS SCENE (you MUST make yours visually DISTINCT):\n"
                    )
                    for j, prev in enumerate(recent, 1):
                        visual_desc_prompt += f"  {j}. {prev}\n"
                    visual_desc_prompt += (
                        "Your image MUST show a DIFFERENT subject, angle, or setting. "
                        "Do NOT repeat the same primary subject. If the previous images show "
                        "the same object (e.g. ships, buildings, maps), zoom into a DETAIL, "
                        "show the CONSEQUENCE, show a DIFFERENT location, or show the HUMAN "
                        "element instead.\n\n"
                    )

                visual_desc_prompt += (
                    f"Narration: \"{seg['text']}\"\n"
                    f"Visual seeds for context: {visual_seeds[:200] if visual_seeds else 'none'}"
                )
            else:
                # Holographic default prompt (unchanged)
                visual_desc_prompt = (
                    "You are creating visual descriptions for HOLOGRAPHIC DATA DISPLAYS "
                    "in an intelligence operations center — not camera shots of real events.\n\n"
                    "NEVER describe:\n"
                    "- People (no politicians, officials, reporters, soldiers, analysts, or any human figures)\n"
                    "- Physical rooms or buildings as if a camera is there\n"
                    "- Events as if photographing them\n\n"
                    "ALWAYS describe:\n"
                    "- What DATA, DOCUMENTS, MAPS, or CHARTS would appear on a holographic screen analyzing this topic\n"
                    "- Information visualizations (price charts, treaty text, flow diagrams, network maps, timelines)\n"
                    "- At least one specific number, date, or percentage from the narration\n"
                    "- Data elements must come from THIS segment's text only, not from the broader script context\n\n"
                    "EXAMPLES:\n"
                    "BAD: 'Kremlin hall, Putin and Pezeshkian at long table with treaty document'\n"
                    "GOOD: 'Holographic treaty document floating in space, 47 articles visible with Section 12: Military Cooperation highlighted'\n\n"
                    "BAD: 'White House briefing room, reporters holding phones'\n"
                    "GOOD: 'Bloomberg terminal display showing headline with oil price ticker dropping from $120 to $68'\n\n"
                    "The subject is ALWAYS information/data being displayed, never the physical event itself.\n\n"
                    "Write a 20-35 word description of what DATA DISPLAY would visualize this narration. "
                    "Return ONLY the description, nothing else.\n\n"
                )

                # Add previous descriptions for deduplication
                if prev_descriptions:
                    recent = prev_descriptions[-3:]
                    visual_desc_prompt += (
                        "PREVIOUS IMAGES IN THIS SCENE (you MUST make yours visually DISTINCT):\n"
                    )
                    for j, prev in enumerate(recent, 1):
                        visual_desc_prompt += f"  {j}. {prev}\n"
                    visual_desc_prompt += (
                        "Your image MUST show a DIFFERENT data visualization type. "
                        "Do NOT repeat the same display format.\n\n"
                    )

                visual_desc_prompt += (
                    f"Narration: \"{seg['text']}\"\n"
                    f"Visual seeds for context: {visual_seeds[:200] if visual_seeds else 'none'}"
                )

            visual_description = await anthropic_client.generate(
                prompt=visual_desc_prompt,
                model=Models.CLAUDE_SONNET,
                max_tokens=200,
                temperature=0.4,
            )
            visual_description = visual_description.strip()

        except Exception as e:
            print(f"      ⚠️ LLM visual description failed for segment {i+1}: {e}")
            # Fallback: use the narration text as placeholder
            visual_description = seg['text']

        # Track for deduplication of subsequent concepts
        prev_descriptions.append(visual_description)

        # Scene type is now DESCRIPTIVE — assigned based on what Claude wrote
        # (detected by prompt_builder.py when assembling final prompt)
        concepts.append({
            "concept_index": i + 1,
            "sentence_text": seg['text'],
            "visual_description": visual_description,
            "visual_style": default_fallback_style,  # Default; actual type detected later
            "composition": composition,
            "mood": "tension",  # Default mood, could be enhanced later
        })

    print(f"    Scene {scene_number}: {len(concepts)} concepts from deterministic splitter "
          f"(max duration: {max(s['duration'] for s in segments):.1f}s)")

    return concepts


async def expand_scene_concepts(
    anthropic_client,
    scene_number: int,
    scene_text: str,
    visual_seeds: str,
    accent_color: str,
    act_number: int,
    total_scenes: int = 14,
) -> list[dict]:
    """Expand one scene's narration into 6-10 visual concepts.

    This is the core function of the new pipeline. It takes a single scene's
    text directly from the Script table and produces concepts ready to be
    written to the Airtable Images table.

    Uses 5 LLM attempts with progressively relaxed validation. A slightly
    imperfect LLM result (longer image durations, small gaps auto-absorbed)
    is always better than a mechanical fallback with generic templates.

    Args:
        anthropic_client: AnthropicClient instance with generate() method
        scene_number: Scene number from the Script table
        scene_text: Exact narration text from the Script table
        visual_seeds: Visual seed concepts from research brief
        accent_color: Accent color for this video (e.g. "cold_teal")
        act_number: Which act this scene belongs to (1-6)
        total_scenes: Total number of scenes in the video

    Returns:
        List of concept dicts, each with:
        - concept_index (int, 1-based)
        - sentence_text (str, exact substring of scene_text)
        - visual_description (str, 20-35 word filmable description)
        - visual_style (str, profile substyle name)
        - composition (str, wide/medium/closeup/etc.)
        - mood (str)
    """
    import asyncio

    concept_count = _estimate_concept_count(scene_text)

    prompt = _build_prompt(
        scene_number=scene_number,
        scene_text=scene_text,
        visual_seeds=visual_seeds,
        accent_color=accent_color,
        act_number=act_number,
        concept_count=concept_count,
        total_scenes=total_scenes,
    )

    max_attempts = 5
    last_error = ""
    # Track the best LLM result across all attempts so we can use it
    # even if it didn't pass strict validation.
    best_concepts: list[dict] | None = None
    best_error: str = ""

    for attempt in range(1, max_attempts + 1):
        # Use relaxed validation on attempts 4+ — auto-fix minor issues
        # instead of rejecting. A longer-duration image is better than
        # a wrong image.
        use_relaxed = attempt >= 4

        extra = ""
        if attempt == 2:
            extra = (
                "\n\nIMPORTANT: Your previous response had this issue: "
                f"{last_error}\n"
                "Fix this. The sentence_text fields must be EXACT substrings of "
                "the narration — copy-paste them character for character. "
                "Return ONLY valid JSON."
            )
        elif attempt == 3:
            extra = (
                "\n\nCRITICAL: Previous issue: "
                f"{last_error}\n"
                "You MUST copy sentence_text EXACTLY from the narration. "
                "Do not edit, rephrase, or fix anything. Character-for-character copy. "
                "Return ONLY a JSON object, no markdown fences."
            )
        elif attempt == 4:
            extra = (
                "\n\nPrevious issue: "
                f"{last_error}\n"
                "SIMPLIFY: Use FEWER, LONGER concepts if needed. "
                "It is better to have 4-5 longer concepts than to fail. "
                "Each concept can cover up to 40 words. "
                "Copy sentence_text EXACTLY from the narration."
            )
        elif attempt == 5:
            extra = (
                "\n\nFINAL ATTEMPT. Previous issue: "
                f"{last_error}\n"
                "Use as FEW concepts as needed (minimum 3). "
                "Each concept can be long — up to 50 words. "
                "Split at the most obvious sentence boundaries (periods). "
                "Copy sentence_text EXACTLY. Return ONLY JSON."
            )

        try:
            response = await anthropic_client.generate(
                prompt=prompt + extra,
                model=Models.CLAUDE_SONNET,
                max_tokens=6000,
                temperature=max(0.3, 0.7 - 0.1 * attempt),
            )

            parsed = _parse_response(response)
            concepts = parsed.get("concepts", [])

            # Number the concepts
            for i, c in enumerate(concepts):
                c["concept_index"] = i + 1

            is_valid, error = _validate_concepts(
                concepts, scene_text, concept_count, relaxed=use_relaxed,
            )

            if is_valid:
                concepts = _validate_concept_durations(concepts)
                return concepts

            # Track the best result — prefer the one with more valid concepts
            if concepts and (best_concepts is None or len(concepts) > len(best_concepts)):
                # Deep copy so subsequent relaxed validation doesn't mutate
                best_concepts = [dict(c) for c in concepts]
                best_error = error

            last_error = error
            print(f"    Scene {scene_number} attempt {attempt}/{max_attempts}: {error}")

        except (json.JSONDecodeError, ValueError) as exc:
            last_error = f"JSON parse failed: {exc}"
            print(f"    Scene {scene_number} attempt {attempt}/{max_attempts}: {last_error}")
        except Exception as exc:
            last_error = f"LLM error: {exc}"
            print(f"    Scene {scene_number} attempt {attempt}/{max_attempts}: {last_error}")

        if attempt < max_attempts:
            await asyncio.sleep(2)

    # All 5 attempts failed strict+relaxed validation.
    # Use the best LLM result we got — but ONLY after repairing all
    # sentence_text fields to be verbatim substrings of the source.
    if best_concepts:
        print(
            f"    Scene {scene_number}: using best LLM result "
            f"({len(best_concepts)} concepts, issue: {best_error})"
        )
        # Repair all concepts to guarantee verbatim sentence_text
        best_concepts = _repair_all_concepts(best_concepts, scene_text)

        # Force-fix: ensure every concept has required fields
        valid_styles = get_valid_styles()
        fallback_style = get_default_style()
        repair_comps: list[str] = []
        for i, c in enumerate(best_concepts):
            c["concept_index"] = i + 1
            if not c.get("visual_style") or c["visual_style"] not in valid_styles:
                c["visual_style"] = fallback_style
            if not c.get("composition") or c["composition"] not in get_valid_compositions():
                c["composition"] = _pick_composition(c["visual_style"], i, repair_comps)
            repair_comps.append(c["composition"])
            if not c.get("visual_description"):
                c["visual_description"] = c.get("sentence_text", "")
                c["needs_new_prompt"] = True
            if not c.get("mood"):
                c["mood"] = "tension"
        return _validate_concept_durations(best_concepts)

    # Absolute last resort: no LLM response at all (network errors on all
    # 5 attempts). Split at sentence boundaries with the sentence text as
    # the visual description placeholder — downstream prompt generation
    # will create proper descriptions. Never use static keyword templates.
    print(
        f"    Scene {scene_number}: no LLM response after {max_attempts} "
        f"attempts, creating sentence-boundary concepts"
    )
    return _sentence_boundary_split(scene_text)
