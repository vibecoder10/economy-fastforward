"""
Storyboard Bot — Cinematic shot planning and contact sheet generation.

Generates 3x3 cinematic contact sheet storyboards for each narrative beat
BEFORE individual image generation. A Claude-powered directive generator
acts as a trailer director — analyzing script text, planning emotional arcs,
choosing shot types/angles/durations, and outputting keyframe specifications.

This is an OPTIONAL pre-step. When disabled, the pipeline flows as normal.
Manual trigger only via Slack commands (!storyboard-go, !storyboard-beat).

Pipeline flow (with storyboard enabled):
  Ready For Image Prompts → image_prompt_bot generates prompts (unchanged)
      ↓
  Ready For Storyboards → storyboard_bot (NEW — manual trigger)
      ↓
  Ready For Video Scripts (skips image_bot — images already generated)
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import re
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from channel_profile import ChannelProfile, ModelProfile, load_profile
from pipeline_constants import ImageFields, IdeaFields, Models, ScriptFields

logger = logging.getLogger(__name__)


# =============================================================================
# Grid Count Calculator
# =============================================================================

def calculate_grid_count(
    video_length_minutes: int,
    clip_duration_seconds: int = 10,
) -> dict:
    """Calculate how many storyboard grids are needed for a video.

    Returns dict with grid_count, total_panels, and cost estimate.
    """
    total_seconds = video_length_minutes * 60
    total_clips = total_seconds // clip_duration_seconds

    grid_count = math.ceil(total_clips / 9)
    total_panels = grid_count * 9

    cost_claude = grid_count * 0.03
    cost_grids = grid_count * 0.075
    cost_upscale = total_panels * 0.045
    total_cost = cost_claude + cost_grids + cost_upscale

    return {
        "grid_count": grid_count,
        "total_panels": total_panels,
        "surplus_panels": total_panels - total_clips,
        "cost_claude": cost_claude,
        "cost_grids": cost_grids,
        "cost_upscale": cost_upscale,
        "total_cost": total_cost,
    }


# =============================================================================
# Scene-Based Storyboard Prompt Generator
# =============================================================================


def generate_scene_storyboard_prompts(
    scene_images: list[dict],
    scene_number: int,
    video_title: str,
    profile: ChannelProfile,
) -> list[dict]:
    """Generate storyboard prompts for a scene from its existing image prompts.

    Takes the image records (with their existing prompts) and groups them into
    3x3 storyboard grids with unified visual consistency anchors.

    Args:
        scene_images: List of image records for this scene (sorted by index)
        scene_number: Scene number
        video_title: Video title
        profile: Channel visual profile for style consistency

    Returns:
        List of dicts, each containing:
            - grid_number: 1, 2, or 3
            - panel_count: Number of actual panels (1-9)
            - prompt: The full storyboard prompt text
            - panels: List of panel details (sentence, image_prompt)
    """
    # Sort images by index
    sorted_images = sorted(
        scene_images,
        key=lambda x: x.get("fields", x).get(
            ImageFields.IMAGE_INDEX,
            x.get("fields", x).get(ImageFields.SENTENCE_INDEX, 0)
        )
    )

    # Calculate grids needed
    total_panels = len(sorted_images)
    grid_count = math.ceil(total_panels / 9)

    storyboard_prompts = []

    for grid_idx in range(grid_count):
        start_idx = grid_idx * 9
        end_idx = min(start_idx + 9, total_panels)
        grid_images = sorted_images[start_idx:end_idx]

        # Build panel data
        panels = []
        for i, img in enumerate(grid_images):
            fields = img.get("fields", img)
            panels.append({
                "panel_number": i + 1,
                "sentence": fields.get(ImageFields.SENTENCE_TEXT, ""),
                "image_prompt": fields.get(ImageFields.IMAGE_PROMPT, ""),
            })

        # Generate the unified storyboard prompt
        prompt = _build_storyboard_grid_prompt(
            panels=panels,
            scene_number=scene_number,
            grid_number=grid_idx + 1,
            total_grids=grid_count,
            video_title=video_title,
            profile=profile,
        )

        storyboard_prompts.append({
            "grid_number": grid_idx + 1,
            "panel_count": len(panels),
            "blank_panels": 9 - len(panels),
            "prompt": prompt,
            "panels": panels,
        })

    return storyboard_prompts


def _build_storyboard_grid_prompt(
    panels: list[dict],
    scene_number: int,
    grid_number: int,
    total_grids: int,
    video_title: str,
    profile: ChannelProfile,
) -> str:
    """Build a unified 3x3 contact sheet prompt from panel data.

    This prompt ensures all 9 panels share:
    - Same visual style
    - Same lighting direction and quality
    - Same color palette
    - Consistent character appearances
    - Consistent environment details
    """
    # Style prefix from channel profile
    style_prefix = f"""**{profile.visual_style_directive}**

3×3 contact sheet storyboard grid (3 rows × 3 columns) with clearly separated panels.
Each panel is a cinematic frame from Scene {scene_number}, Grid {grid_number}/{total_grids}.
Title: "{video_title}"

**VISUAL CONSISTENCY REQUIREMENTS:**
- Color palette: {profile.color_grade.primary_palette}
- Lighting: {profile.color_grade.time_of_day_default}, {profile.color_grade.shadow_treatment}
- Texture: {profile.lens_profile.grain}
- All panels must share the same environment, lighting direction, and atmosphere.

"""

    # Build panel descriptions
    panel_descriptions = []
    for p in panels:
        panel_num = p["panel_number"]
        # Extract core visual from the existing prompt (first 150 chars after style prefix)
        prompt = p["image_prompt"]
        # Remove common style prefixes to get the core content
        core_prompt = prompt
        for prefix in ["Cinematic 2D animated illustration of ", "cinematic_illustration style, "]:
            if core_prompt.lower().startswith(prefix.lower()):
                core_prompt = core_prompt[len(prefix):]
                break

        row = (panel_num - 1) // 3 + 1
        col = (panel_num - 1) % 3 + 1
        panel_descriptions.append(
            f"**Panel {panel_num} (Row {row}, Col {col}):** {core_prompt[:200]}"
        )

    # Add blank panel descriptions if needed
    for i in range(len(panels) + 1, 10):
        row = (i - 1) // 3 + 1
        col = (i - 1) % 3 + 1
        panel_descriptions.append(
            f"**Panel {i} (Row {row}, Col {col}):** BLACK PANEL - solid black fill"
        )

    panels_section = "\n".join(panel_descriptions)

    return f"""{style_prefix}
**PANEL LAYOUT:**
{panels_section}

**TECHNICAL SPECS:**
- Output as single image containing all 9 panels in 3×3 grid
- Thin black dividers between panels
- 16:9 aspect ratio per panel
- Consistent cinematic illustration style across all panels
"""


async def generate_storyboard_prompts_for_video(
    video_title: str,
    airtable_client=None,
    save_to_airtable: bool = True,
) -> dict:
    """Generate storyboard prompts for all scenes in a video.

    Groups existing image prompts into 3x3 storyboards and optionally
    saves the prompts to the Scripts table for review.

    Args:
        video_title: Title of the video
        airtable_client: Optional Airtable client
        save_to_airtable: Whether to save prompts to Scripts table

    Returns:
        Dict with scene_number -> list of storyboard prompts
    """
    if airtable_client is None:
        from clients.airtable_client import AirtableClient
        airtable_client = AirtableClient()

    # Get script records to find scene IDs
    scripts = airtable_client.get_scripts_by_title(video_title)
    if not scripts:
        logger.error(f"No scripts found for '{video_title}'")
        return {}

    # Get all images
    images = airtable_client.get_all_images_for_video(video_title)
    if not images:
        logger.error(f"No images found for '{video_title}'")
        return {}

    # Load channel profile
    ideas = airtable_client.get_ideas_by_status(None)  # Get all to find by title
    idea_record = None
    for idea in ideas:
        if idea.get(IdeaFields.VIDEO_TITLE) == video_title:
            idea_record = idea
            break

    if idea_record:
        profile = load_profile(idea_record)
    else:
        profile = load_profile({})  # Default profile

    # Group images by scene
    from collections import defaultdict
    images_by_scene = defaultdict(list)
    for img in images:
        fields = img.get("fields", img)
        scene = fields.get("Scene", fields.get("scene", 0))
        images_by_scene[scene].append(img)

    # Build scene_id -> record_id map
    scene_to_record = {}
    for s in scripts:
        fields = s.get("fields", s)
        scene_num = fields.get(ScriptFields.SCENE, 0)
        scene_to_record[scene_num] = s.get("id", "")

    results = {}

    for scene_num in sorted(images_by_scene.keys()):
        scene_images = images_by_scene[scene_num]
        logger.info(f"Scene {scene_num}: {len(scene_images)} images")

        # Generate storyboard prompts
        storyboard_prompts = generate_scene_storyboard_prompts(
            scene_images=scene_images,
            scene_number=scene_num,
            video_title=video_title,
            profile=profile,
        )

        results[scene_num] = storyboard_prompts

        # Save to Airtable
        if save_to_airtable:
            record_id = scene_to_record.get(scene_num)
            if record_id:
                # Combine all prompts into one text block
                prompts_text = []
                for sb in storyboard_prompts:
                    prompts_text.append(f"=== STORYBOARD {sb['grid_number']}/{len(storyboard_prompts)} ===")
                    prompts_text.append(f"Panels: {sb['panel_count']} (+ {sb['blank_panels']} blank)")
                    prompts_text.append("")
                    prompts_text.append(sb["prompt"])
                    prompts_text.append("")
                    prompts_text.append("---")
                    prompts_text.append("")

                try:
                    airtable_client.update_script_record(record_id, {
                        ScriptFields.STORYBOARD_PROMPTS: "\n".join(prompts_text),
                    })
                    logger.info(f"Saved storyboard prompts for Scene {scene_num}")
                except Exception as e:
                    logger.warning(f"Failed to save prompts for Scene {scene_num}: {e}")

    return results


# =============================================================================
# Narrative Beat Segmentation
# =============================================================================

def segment_script_into_beats(
    script_records: list[dict],
    target_seconds_per_beat: int = 40,
    words_per_second: float = 2.5,
    image_records: list[dict] | None = None,
) -> list[dict]:
    """Divide the full script into narrative beats for storyboard generation.

    If image_records is provided, beats are calculated based on image count:
    - Each beat = 9 images (one 3x3 grid)
    - Number of beats = ceil(total_images / 9)

    Otherwise falls back to narration-based segmentation (~40s per beat).

    Args:
        script_records: Airtable script records with 'Scene', 'Scene text' fields.
        target_seconds_per_beat: Target duration per beat in seconds (fallback).
        words_per_second: Narration speed (2.5 wps standard).
        image_records: Optional list of image records to calculate beats from.

    Returns:
        List of beats, each with beat_number, scenes, text, word_count,
        estimated_duration_seconds.
    """
    import math
    from collections import defaultdict

    # If image_records provided, calculate beats PER SCENE based on image count
    if image_records:
        # Group images by scene
        scene_images: dict[int, list] = defaultdict(list)
        for img in image_records:
            fields = img.get("fields", img)
            scene_num = fields.get(ImageFields.SCENE, 0)
            scene_images[scene_num].append(img)

        # Sort images within each scene by index
        for scene_num in scene_images:
            scene_images[scene_num].sort(
                key=lambda r: r.get("fields", r).get(ImageFields.IMAGE_INDEX, 0)
            )

        # Build scene text map
        scene_texts = {}
        for record in script_records:
            fields = record.get("fields", record)
            scene_num = fields.get(ScriptFields.SCENE, 0)
            scene_text = fields.get(ScriptFields.SCENE_TEXT, "")
            scene_texts[scene_num] = scene_text

        # Generate beats per scene
        beats: list[dict] = []
        global_beat_num = 0

        for scene_num in sorted(scene_images.keys()):
            imgs = scene_images[scene_num]
            scene_beat_count = max(1, math.ceil(len(imgs) / 9))

            for scene_beat_idx in range(scene_beat_count):
                global_beat_num += 1
                start_idx = scene_beat_idx * 9
                end_idx = min(start_idx + 9, len(imgs))
                beat_images = imgs[start_idx:end_idx]

                # Build text from Sentence Text fields in image records
                sentence_texts = [
                    img.get("fields", img).get(ImageFields.SENTENCE_TEXT, "")
                    for img in beat_images
                ]
                beat_text = " ".join(t for t in sentence_texts if t).strip()
                word_count = len(beat_text.split())

                # Store image record IDs for accurate filtering later
                image_record_ids = [img.get("id", "") for img in beat_images]

                beats.append({
                    "beat_number": global_beat_num,
                    "scenes": [scene_num],  # Single scene per beat
                    "scene_beat_index": scene_beat_idx + 1,  # Beat # within this scene
                    "scene_beat_total": scene_beat_count,  # Total beats for this scene
                    "text": beat_text,
                    "word_count": word_count,
                    "estimated_duration_seconds": word_count / words_per_second,
                    "image_count": len(beat_images),
                    "image_record_ids": image_record_ids,
                    "start_idx": start_idx,
                    "end_idx": end_idx,
                })

        return beats

    # Fallback: narration-based segmentation
    target_words_per_beat = int(target_seconds_per_beat * words_per_second)

    beats: list[dict] = []
    current_beat_text = ""
    current_beat_scenes: list[int] = []
    current_word_count = 0
    beat_number = 1

    sorted_records = sorted(
        script_records,
        key=lambda r: r.get(ScriptFields.SCENE, r.get("fields", {}).get(ScriptFields.SCENE, 0)),
    )

    for record in sorted_records:
        # Handle both flat {"Scene": N} and nested {"fields": {"Scene": N}}
        fields = record.get("fields", record)
        scene_num = fields.get(ScriptFields.SCENE, 0)
        scene_text = fields.get(ScriptFields.SCENE_TEXT, "")
        scene_words = len(scene_text.split())

        # If adding this scene exceeds 130% of target AND we already have content,
        # close the current beat and start a new one
        if (
            current_word_count + scene_words > target_words_per_beat * 1.3
            and current_word_count > 0
        ):
            beats.append({
                "beat_number": beat_number,
                "scenes": list(current_beat_scenes),
                "text": current_beat_text.strip(),
                "word_count": current_word_count,
                "estimated_duration_seconds": current_word_count / words_per_second,
            })
            beat_number += 1
            current_beat_text = ""
            current_beat_scenes = []
            current_word_count = 0

        current_beat_text += f"\n{scene_text}"
        current_beat_scenes.append(scene_num)
        current_word_count += scene_words

    # Don't forget the last beat
    if current_word_count > 0:
        beats.append({
            "beat_number": beat_number,
            "scenes": list(current_beat_scenes),
            "text": current_beat_text.strip(),
            "word_count": current_word_count,
            "estimated_duration_seconds": current_word_count / words_per_second,
        })

    return beats


# =============================================================================
# Story Bible → Storyboard Context Formatter
# =============================================================================


def _format_story_bible_for_beat(
    story_bible: dict | None,
    beat_scenes: list[int],
) -> str:
    """Format Story Bible characters, locations, and arc data for a beat.

    Extracts only the characters and locations relevant to the scenes
    covered by this beat, providing binding visual constraints for the
    directive generator.

    Returns formatted string to inject into the user prompt, or empty
    string if no Story Bible exists.
    """
    if not story_bible:
        return ""

    lines: list[str] = []

    # === CHARACTERS relevant to this beat ===
    chars = story_bible.get("characters", [])
    if chars:
        lines.append("<visual_bible_characters>")
        lines.append("USE THESE EXACT DESCRIPTIONS for visual consistency across all panels.")
        for char in chars:
            char_id = char.get("id", "unknown")
            costume = char.get("costume") or char.get("description", "")
            pose = char.get("signature_pose", "")
            scenes = char.get("scenes_present", [])
            # Include if character appears in any of this beat's scenes, or if
            # scenes_present is empty (character appears everywhere)
            if not scenes or any(s in scenes for s in beat_scenes):
                lines.append(f"\n  {char_id.upper()}:")
                lines.append(f"    Appearance: {costume}")
                if pose:
                    lines.append(f"    Default pose: {pose}")
        lines.append("</visual_bible_characters>")

    # === LOCATIONS relevant to this beat ===
    locs = story_bible.get("locations", [])
    if locs:
        lines.append("\n<visual_bible_locations>")
        lines.append("USE THESE EXACT ENVIRONMENTS for visual consistency.")
        for loc in locs:
            loc_id = loc.get("id", "unknown")
            desc = loc.get("description", "")
            lighting = loc.get("lighting", "")
            signature = loc.get("signature_detail", "")
            loc_type = loc.get("type", "")
            scenes = loc.get("scenes_present", [])
            if not scenes or any(s in scenes for s in beat_scenes):
                lines.append(f"\n  {loc_id.upper()}:")
                lines.append(f"    {desc}")
                if lighting:
                    lines.append(f"    Lighting: {lighting}")
                if signature:
                    lines.append(f"    Signature detail: {signature}")
                if loc_type:
                    lines.append(f"    Type: {loc_type}")
        lines.append("</visual_bible_locations>")

    # === VISUAL ARC entries for this beat's scenes ===
    arcs = story_bible.get("visual_arc", [])
    beat_arcs = [a for a in arcs if a.get("scene") in beat_scenes]
    if beat_arcs:
        lines.append("\n<visual_arc>")
        lines.append("Visual progression planned for this beat:")
        for arc in beat_arcs:
            scene_num = arc.get("scene", "?")
            mood = arc.get("mood", "neutral")
            camera = arc.get("camera_distance", "medium")
            tension = arc.get("tension_level", 5)
            color_temp = arc.get("color_temperature", "neutral")
            visual_note = arc.get("visual_note", "")
            loc_id = arc.get("location_id", "")
            chars_present = arc.get("characters_present", [])
            lines.append(
                f"  Scene {scene_num}: {loc_id} | mood={mood} | "
                f"camera={camera} | tension={tension}/10 | "
                f"color_temp={color_temp}"
            )
            if chars_present:
                lines.append(f"    Characters: {', '.join(chars_present)}")
            if visual_note:
                lines.append(f"    Note: {visual_note}")
        lines.append("</visual_arc>")

    # === SCENE BLOCKS (V2) for this beat ===
    scene_blocks = story_bible.get("scene_blocks", [])
    if scene_blocks:
        # Find blocks that overlap with this beat's scenes
        # Scene blocks use image_index, but we can match by act or just
        # include blocks whose act number is in the beat's scene range
        beat_blocks = []
        for block in scene_blocks:
            block_act = block.get("act")
            # Include block if its act number falls within this beat's scenes
            if block_act in beat_scenes:
                beat_blocks.append(block)

        if beat_blocks:
            lines.append("\n<scene_blocks>")
            lines.append(
                "Pre-planned visual groupings. Each block shares location "
                "+ lighting. Only camera, action, expression change within."
            )
            for block in beat_blocks:
                block_id = block.get("block_id", "?")
                location = block.get("location", "")
                lighting = block.get("lighting", "")
                mood = block.get("mood", "")
                chars_present = block.get("characters_present", [])
                images = block.get("images", [])
                lines.append(f"\n  Block {block_id}: {location}")
                if lighting:
                    lines.append(f"    Lighting: {lighting}")
                if mood:
                    lines.append(f"    Mood: {mood}")
                if chars_present:
                    lines.append(
                        f"    Characters: {', '.join(chars_present)}"
                    )
                if images:
                    for img in images:
                        idx = img.get("image_index", "?")
                        cam = img.get("camera", "medium")
                        action = img.get("action", "")
                        lines.append(f"    [{idx}] {cam} — {action}")
            lines.append("</scene_blocks>")

    if not lines:
        return ""

    return "\n".join(lines)


# =============================================================================
# Cinematic Directive Generator — Core Intelligence
# =============================================================================

def _build_directive_system_prompt(profile: ChannelProfile, beat_duration_seconds: float = 120) -> str:
    """Build the system prompt for the cinematic directive generator.

    Args:
        profile: Channel visual profile
        beat_duration_seconds: Target duration for this beat's keyframes (from word count)
    """
    return f"""\
<role>
You are an award-winning trailer director, cinematographer, and storyboard artist working \
on a cinematic documentary-style video. Your job: turn script narration into a cohesive \
cinematic shot sequence, then output AI-video-ready keyframes as a 3×3 contact sheet.
</role>

<channel_identity>
Channel: {profile.channel_name}
Visual Style: {profile.visual_style_directive}
</channel_identity>

<lens_and_camera>
Focal Range: {profile.lens_profile.focal_range}
Depth of Field Tendency: {profile.lens_profile.dof_tendency}
Movement Vocabulary: {', '.join(profile.lens_profile.movement_vocabulary)}
Shutter Feel: {profile.lens_profile.shutter_feel}
Grain/Texture: {profile.lens_profile.grain}
</lens_and_camera>

<color_grade>
Primary Palette: {profile.color_grade.primary_palette}
Contrast: {profile.color_grade.contrast}
Shadow Treatment: {profile.color_grade.shadow_treatment}
Highlight Treatment: {profile.color_grade.highlight_treatment}
Material Priorities: {profile.color_grade.material_priorities}
Time of Day: {profile.color_grade.time_of_day_default}
</color_grade>

<character_handling>
Mode: {profile.character_handling.mode}
{profile.character_handling.description}
</character_handling>

<non_negotiable_rules>
1) Analyze the scene narration to identify ALL key subjects, environments, and narrative beats. \
Describe spatial relationships and interactions.
2) Do NOT use real political figure names. Imply through context (setting, wardrobe, insignia).
3) Strict continuity across ALL 9 panels: same subjects, same wardrobe/appearance, same \
environment, same time-of-day and lighting. Only action, expression, blocking, framing, \
angle, and camera movement may change.
4) Depth of field must be realistic per the lens profile. Keep ONE consistent cinematic color \
grade across the entire sequence per the color grade profile.
5) Do NOT introduce new characters/objects not supported by the narration. If you need \
tension/conflict beyond what's described, imply it off-screen (shadow, reflection, gaze).
6) If a VISUAL BIBLE is provided in the user message, it contains BINDING character and \
location descriptions. Use the EXACT costume/appearance for each character and the EXACT \
environment description for each location. These are visual anchors that ensure consistency \
across the entire video — do NOT deviate from them. The visual bible is your single source \
of truth for what characters look like and what environments look like.
</non_negotiable_rules>

<goal>
Expand the scene narration into a 9-keyframe cinematic sequence with a clear emotional \
progression following the 4-beat arc: {profile.emotional_arc.beat_1} → \
{profile.emotional_arc.beat_2} → {profile.emotional_arc.beat_3} → \
{profile.emotional_arc.beat_4}.

CRITICAL: Total duration for all 9 keyframes MUST equal approximately {beat_duration_seconds:.0f} seconds \
(calculated from the narration word count at 2.5 words/second). Distribute the duration across \
keyframes based on the pacing of the narration — longer dialogue sections get longer keyframes, \
quick action moments get shorter keyframes. The sum of all keyframe durations must match the \
narration length so the visuals sync with the audio.
</goal>

<output_format>
You MUST output ALL of the following sections in order:

## SCENE BREAKDOWN
- Subjects: list each key subject (A/B/C...), describe visible traits, relative positions, \
facing direction, action/state, and any interaction.
- Environment & Lighting: interior/exterior, spatial layout, background elements, light \
direction & quality, implied time-of-day, 3-8 vibe keywords.
- Visual Anchors: list 3-6 visual traits that MUST stay constant across all 9 panels \
(palette, signature prop, key light source, weather/atmosphere, background markers).

## THEME & STORY
- Theme: one sentence.
- Logline: one restrained sentence grounded in the narration.
- Emotional Arc: 4 beats (setup/build/turn/payoff), one line each.

## CINEMATIC APPROACH
- Shot progression strategy: how you move from wide to close (or reverse) to serve the beats.
- Camera movement plan: which movements from the channel's vocabulary and WHY.
- Lens & exposure: focal lengths, DoF shifts, shutter feel.
- Light & color: how the channel's color grade applies to THIS scene specifically.

## KEYFRAMES
Output exactly 9 keyframes. Use this EXACT format per keyframe:

[KF# | shot_type | duration_seconds]
- Composition: subject placement, foreground/mid/background, leading lines, gaze direction
- Action/beat: what visibly happens (simple, executable by an image model)
- Camera: height, angle, movement description
- Lens/DoF: focal length (mm), DoF (shallow/medium/deep), focus target
- Lighting & grade: consistent with color grade profile; note highlight/shadow emphasis
- Sound/atmos: one line (wind, city hum, footsteps, paper rustling) — for editing rhythm reference

Hard requirements for the 9 keyframes:
{chr(10).join('- ' + req for req in profile.shot_requirements.mandatory_shots)}

Edit continuity rules:
{chr(10).join('- ' + rule for rule in profile.shot_requirements.edit_rules)}

## CONTACT SHEET PROMPT
Finally, output a SINGLE image generation prompt that will produce a 3×3 contact sheet \
grid containing all 9 keyframes as panels. This prompt will be sent directly to an image \
generation model.

The contact sheet prompt MUST:
- Start with: "Generate in 16:9 widescreen aspect ratio."
- Begin with the channel's visual style directive
- Describe a 3×3 grid layout (3 rows, 3 columns) with clearly separated panels
- Include panel labels: [KF# | shot_type | duration] in the top-left corner of each panel
- Describe each panel's content in sequence (KF1 top-left → KF9 bottom-right)
- Enforce consistent character appearance, environment, and color grade across all panels
- End with technical specs: the channel's lens profile, grain/texture, and color grade
</output_format>"""


def _build_directive_user_prompt(
    beat_number: int,
    beat_text: str,
    beat_scenes: list[int],
    video_title: str,
    image_prompts: list[str],
    story_bible: dict | None = None,
) -> str:
    """Build the user message for the directive generator."""
    formatted_prompts = "\n".join(
        f"  [{i + 1}] {p}" for i, p in enumerate(image_prompts) if p
    ) or "  (no existing image prompts)"

    # Format Story Bible data as binding visual constraints
    visual_bible_block = _format_story_bible_for_beat(story_bible, beat_scenes)

    parts = [
        f'Generate the cinematic storyboard directive for Beat {beat_number} '
        f'of "{video_title}".',
        f"\nScenes covered: {', '.join(str(s) for s in beat_scenes)}",
        f"\nBeat narration:\n{beat_text}",
    ]

    if visual_bible_block:
        parts.append(
            f"\n--- VISUAL BIBLE (binding visual anchors) ---\n"
            f"{visual_bible_block}\n"
            f"--- END VISUAL BIBLE ---\n\n"
            f"IMPORTANT: The visual bible above defines EXACT character "
            f"appearances and location descriptions. Use them verbatim in "
            f"your keyframe descriptions and contact sheet prompt to ensure "
            f"visual consistency across the entire video."
        )

    parts.append(
        f"\nReference image prompts (use as context for subjects and "
        f"environments):\n{formatted_prompts}"
    )

    return "\n".join(parts)


async def generate_storyboard_directive(
    beat_number: int,
    beat_text: str,
    beat_scenes: list[int],
    video_title: str,
    image_prompts: list[str],
    profile: ChannelProfile,
    anthropic_client=None,
    story_bible: dict | None = None,
    beat_duration_seconds: float = 120.0,
) -> dict:
    """Generate a cinematic directive for one narrative beat via Claude.

    Args:
        beat_duration_seconds: Target duration for keyframes (from word count / 2.5 wps)

    Returns dict with:
        scene_breakdown, theme_and_story, cinematic_approach,
        keyframes (parsed list), contact_sheet_prompt, full_response.
    """
    if anthropic_client is None:
        from clients.anthropic_client import AnthropicClient
        anthropic_client = AnthropicClient()

    system_prompt = _build_directive_system_prompt(profile, beat_duration_seconds)
    user_prompt = _build_directive_user_prompt(
        beat_number, beat_text, beat_scenes, video_title, image_prompts,
        story_bible=story_bible,
    )

    response = await anthropic_client.generate(
        prompt=user_prompt,
        system_prompt=system_prompt,
        model=Models.CLAUDE_SONNET,
        max_tokens=8000,  # Increased from 6000 - directive format requires ~7000 tokens
        temperature=0.9,
    )

    # Parse sections from the response
    keyframes = parse_keyframe_metadata(response)
    contact_sheet_prompt = extract_contact_sheet_prompt(response)

    return {
        "beat_number": beat_number,
        "scene_breakdown": _extract_section(response, "SCENE BREAKDOWN"),
        "theme_and_story": _extract_section(response, "THEME & STORY"),
        "cinematic_approach": _extract_section(response, "CINEMATIC APPROACH"),
        "keyframes": keyframes,
        "contact_sheet_prompt": contact_sheet_prompt,
        "full_response": response,
    }


# =============================================================================
# Response Parsers
# =============================================================================

def parse_keyframe_metadata(directive_text: str) -> list[dict]:
    """Parse the KEYFRAMES section to extract per-panel metadata.

    Looks for patterns like: [KF1 | ELS | 2.0]
    Returns list of dicts with shot_type, duration_seconds, and sub-field text.
    """
    # Extract only the KEYFRAMES section to avoid matching keyframe refs in other sections
    keyframes_start = directive_text.find("## KEYFRAMES")
    if keyframes_start == -1:
        keyframes_start = directive_text.find("KEYFRAMES")
    if keyframes_start == -1:
        keyframes_start = 0

    # Find the end of KEYFRAMES section (next ## header or CONTACT SHEET)
    keyframes_section = directive_text[keyframes_start:]
    section_end = re.search(r"\n##\s+(?!KEYFRAME)", keyframes_section)
    if section_end:
        keyframes_section = keyframes_section[: section_end.start()]

    # Also stop at CONTACT SHEET PROMPT marker
    contact_marker = keyframes_section.find("CONTACT SHEET")
    if contact_marker != -1:
        keyframes_section = keyframes_section[:contact_marker]

    # Match pattern: [KF# | shot_type | duration]
    pattern = r"\[KF(\d+)\s*\|\s*([^|]+?)\s*\|\s*([\d.]+)\s*s?\s*\]"
    matches = list(re.finditer(pattern, keyframes_section))

    if not matches:
        logger.warning("No keyframe headers found in directive response")
        return []

    keyframes: list[dict] = []

    for i, match in enumerate(matches):
        kf_number = int(match.group(1))
        shot_type = match.group(2).strip()
        duration = float(match.group(3))

        # Extract description block between this header and the next
        start_pos = match.end()
        end_pos = matches[i + 1].start() if i < len(matches) - 1 else len(keyframes_section)
        description_block = keyframes_section[start_pos:end_pos].strip()

        # Stop at section boundaries (## headers)
        section_break = re.search(r"\n##\s", description_block)
        if section_break:
            description_block = description_block[: section_break.start()].strip()

        keyframes.append({
            "kf_number": kf_number,
            "shot_type": shot_type,
            "duration_seconds": duration,
            "composition": _extract_field(description_block, "Composition"),
            "action_beat": _extract_field(description_block, "Action/beat")
            or _extract_field(description_block, "Action"),
            "camera": _extract_field(description_block, "Camera"),
            "lens_dof": _extract_field(description_block, "Lens/DoF")
            or _extract_field(description_block, "Lens"),
            "lighting_grade": _extract_field(description_block, "Lighting & grade")
            or _extract_field(description_block, "Lighting"),
            "sound_atmos": _extract_field(description_block, "Sound/atmos")
            or _extract_field(description_block, "Sound"),
            "full_description": description_block,
        })

    return keyframes


def extract_contact_sheet_prompt(directive_text: str) -> str:
    """Extract the contact sheet image generation prompt from the directive.

    Looks for the ## CONTACT SHEET PROMPT section.
    """
    markers = [
        "## CONTACT SHEET PROMPT",
        "CONTACT SHEET PROMPT",
        "Contact Sheet Prompt",
        "MASTER GRID",
    ]

    idx = -1
    marker_len = 0
    for marker in markers:
        idx = directive_text.find(marker)
        if idx != -1:
            marker_len = len(marker)
            break

    if idx == -1:
        raise ValueError("Could not find CONTACT SHEET PROMPT section in directive")

    prompt_text = directive_text[idx + marker_len :].strip()

    # Remove any subsequent markdown sections
    next_section = re.search(r"\n##\s", prompt_text)
    if next_section:
        prompt_text = prompt_text[: next_section.start()].strip()

    return prompt_text


def _extract_section(text: str, section_name: str) -> str:
    """Extract a named ## section from the directive response."""
    pattern = rf"##\s*{re.escape(section_name)}\s*\n(.*?)(?=\n##\s|\Z)"
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1).strip() if match else ""


def _extract_field(text: str, field_name: str) -> str:
    """Extract a field value from a keyframe description block.

    Handles both plain and bold markdown formats:
    - Composition: value
    - **Composition:** value
    """
    # Pattern handles optional ** markdown around field name
    pattern = rf"-\s*(?:\*\*)?{re.escape(field_name)}(?:\*\*)?[^:]*:\s*(.+?)(?=\n-|\n\n|\Z)"
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        return ""
    # Strip whitespace and any leading/trailing ** markdown
    value = match.group(1).strip()
    if value.startswith("**"):
        value = value[2:]
    if value.endswith("**"):
        value = value[:-2]
    return value.strip()


# =============================================================================
# Beat Preview Formatter (for Slack / --directive-only)
# =============================================================================

def format_beat_preview(
    video_title: str,
    beat: dict,
    total_beats: int,
    keyframes: list[dict],
    directive: dict,
) -> str:
    """Format a single beat's directive into a readable summary.

    Used by --directive-only mode and !storyboard-preview Slack command.
    """
    lines = [
        f"🎬 Beat {beat['beat_number']}/{total_beats} — \"{video_title}\"",
        f"📍 Scenes {', '.join(str(s) for s in beat['scenes'])} | "
        f"~{beat['estimated_duration_seconds']:.0f}s | {beat['word_count']} words",
        "",
    ]

    # Theme & arc from directive
    theme_story = directive.get("theme_and_story", "")
    if theme_story:
        # Extract theme line
        theme_match = re.search(r"Theme:\s*(.+)", theme_story)
        if theme_match:
            lines.append(f"Theme: {theme_match.group(1).strip()}")

    # Shot plan
    lines.append("")
    lines.append("Shot Plan:")
    for kf in keyframes:
        action = kf.get("action_beat", "")
        # Truncate action to ~60 chars for readability
        if len(action) > 60:
            action = action[:57] + "..."
        lines.append(
            f"  KF{kf['kf_number']} | {kf['shot_type']:5s} | "
            f"{kf['duration_seconds']:.1f}s — {action}"
        )

    # Total duration
    total_dur = sum(kf.get("duration_seconds", 0) for kf in keyframes)
    lines.append(f"\n  Total: {total_dur:.1f}s across {len(keyframes)} keyframes")

    return "\n".join(lines)


# =============================================================================
# Storyboard Plan Generator (cost estimate, no execution)
# =============================================================================

async def generate_storyboard_plan(
    idea_record: dict,
    airtable_client=None,
) -> dict:
    """Generate a storyboard plan WITHOUT executing it.

    Called by !storyboard command to show cost estimate and beat breakdown.
    """
    if airtable_client is None:
        from clients.airtable_client import AirtableClient
        airtable_client = AirtableClient()

    fields = idea_record.get("fields", idea_record)
    video_title = fields.get("Video Title", "")
    video_length = fields.get("Video Length (min)", 10)
    clip_duration = fields.get("Clip Duration (s)", 10)

    script_records = airtable_client.get_scripts_by_title(video_title)
    if not script_records:
        return {"error": f"No script found for '{video_title}'"}

    total_words = sum(
        len(r.get("fields", r).get(ScriptFields.SCENE_TEXT, "").split())
        for r in script_records
    )
    scene_count = len(script_records)

    # Get images to calculate accurate beat count
    image_records = airtable_client.get_all_images_for_video(video_title)
    beats = segment_script_into_beats(script_records, image_records=image_records)
    grid_count = len(beats)
    total_panels = len(image_records) if image_records else grid_count * 9

    cost = calculate_grid_count(video_length, clip_duration)

    return {
        "video_title": video_title,
        "total_words": total_words,
        "scene_count": scene_count,
        "video_length_minutes": video_length,
        "clip_duration_seconds": clip_duration,
        "beat_count": grid_count,
        "total_panels": total_panels,
        "beats": beats,
        "cost_claude": cost["cost_claude"],
        "cost_grids": cost["cost_grids"],
        "cost_upscale": cost["cost_upscale"],
        "total_cost": cost["total_cost"],
    }


# =============================================================================
# Directive-Only Preview (Claude calls, no image generation)
# =============================================================================

async def run_storyboard_preview(
    idea_record: dict,
    airtable_client=None,
    anthropic_client=None,
    single_beat: Optional[int] = None,
) -> list[dict]:
    """Run directives only — no image generation.

    Returns list of beat results, each containing the directive and
    formatted preview. Used by !storyboard-preview and --directive-only.
    """
    if airtable_client is None:
        from clients.airtable_client import AirtableClient
        airtable_client = AirtableClient()
    if anthropic_client is None:
        from clients.anthropic_client import AnthropicClient
        anthropic_client = AnthropicClient()

    fields = idea_record.get("fields", idea_record)
    video_title = fields.get("Video Title", "")
    profile = load_profile(fields)
    idea_id = idea_record.get("id", "")
    video_length_min = fields.get(IdeaFields.VIDEO_LENGTH_MIN, 10) or 10

    # Load Story Bible for visual consistency across beats
    story_bible = _load_story_bible(fields)

    script_records = airtable_client.get_scripts_by_title(video_title)
    if not script_records:
        logger.error(f"No script found for '{video_title}'")
        return []

    # Generate Story Bible if missing
    if story_bible is None and idea_id:
        logger.info(f"Story Bible missing for preview — generating now...")
        story_bible = await _generate_story_bible_for_storyboard(
            anthropic_client=anthropic_client,
            airtable_client=airtable_client,
            idea_id=idea_id,
            video_title=video_title,
            script_records=script_records,
            video_length_min=int(video_length_min),
            slack_client=None,  # No Slack notifications in preview mode
        )

    # Get images first to calculate beats based on image count
    image_records = airtable_client.get_all_images_for_video(video_title)
    beats = segment_script_into_beats(script_records, image_records=image_records)
    if single_beat is not None:
        beats = [b for b in beats if b["beat_number"] == single_beat]

    results: list[dict] = []

    for beat in beats:
        beat_images = _get_images_for_beat(image_records, beat)
        image_prompts = [
            img.get(ImageFields.IMAGE_PROMPT, "")
            for img in beat_images
        ]

        directive = await generate_storyboard_directive(
            beat_number=beat["beat_number"],
            beat_text=beat["text"],
            beat_scenes=beat["scenes"],
            video_title=video_title,
            image_prompts=image_prompts,
            profile=profile,
            anthropic_client=anthropic_client,
            story_bible=story_bible,
            beat_duration_seconds=beat.get("estimated_duration_seconds", 120.0),
        )

        preview = format_beat_preview(
            video_title=video_title,
            beat=beat,
            total_beats=len(beats),
            keyframes=directive["keyframes"],
            directive=directive,
        )

        results.append({
            "beat": beat,
            "directive": directive,
            "preview": preview,
        })

        logger.info(f"Beat {beat['beat_number']}/{len(beats)} directive generated")

    # Save directive per-scene to Scripts table
    # Each beat covers 1+ scenes - save the directive to each scene's script record
    if results and script_records:
        from pipeline_constants import ScriptFields

        # Build a map of scene number -> script record ID
        scene_to_record_id = {}
        for rec in script_records:
            fields = rec.get("fields", rec)
            scene_num = fields.get(ScriptFields.SCENE, 0)
            record_id = rec.get("id", "")
            if scene_num and record_id:
                scene_to_record_id[scene_num] = record_id

        for r in results:
            beat = r["beat"]
            preview = r["preview"]

            # Save to each scene covered by this beat
            for scene_num in beat.get("scenes", []):
                record_id = scene_to_record_id.get(scene_num)
                if record_id:
                    try:
                        airtable_client.update_script_record(record_id, {
                            ScriptFields.STORYBOARD_DIRECTIVE: preview,
                        })
                        logger.info(f"Saved storyboard directive to Scene {scene_num}")
                    except Exception as e:
                        logger.warning(f"Failed to save directive for Scene {scene_num}: {e}")

    return results


# =============================================================================
# Duration-Aware Sentence Binning
# =============================================================================

WORDS_PER_SECOND = 2.5


def assign_clip_durations(
    segments: list[dict],
    model: ModelProfile,
) -> list[dict]:
    """Assign each text segment to the smallest model duration that fits.

    Rules:
    1. Use smallest duration >= spoken_duration
    2. Stay at or below preferred_max when possible
    3. If segment exceeds preferred_max and allow_max_override is True,
       use next duration up only if splitting would create tiny fragments
    4. Segments exceeding all durations are split at sentence boundaries
    5. Segments < 60% of smallest duration merge with adjacent segment
    """
    available = sorted(model.durations)
    preferred = [d for d in available if d <= model.preferred_max]
    min_viable = available[0] * 0.6

    result: list[dict] = []

    for seg in segments:
        spoken = seg["spoken_duration_seconds"]

        # Too short — merge with previous
        if spoken < min_viable and result:
            prev = result[-1]
            prev["text"] += " " + seg["text"]
            prev["word_count"] += seg["word_count"]
            prev["spoken_duration_seconds"] += spoken
            prev["assigned_duration"] = _best_fit_duration(
                prev["spoken_duration_seconds"], preferred, available, model,
            )
            prev["estimated_cost"] = model.cost_per_clip.get(
                prev["assigned_duration"], 0,
            )
            continue

        # Too long — split at sentence boundaries
        max_duration = available[-1]
        if spoken > max_duration:
            result.extend(_split_long_segment(seg, model))
            continue

        # Normal — assign best-fit
        duration = _best_fit_duration(spoken, preferred, available, model)
        seg["assigned_duration"] = duration
        seg["estimated_cost"] = model.cost_per_clip.get(duration, 0)
        result.append(seg)

    return result


def _best_fit_duration(
    spoken: float,
    preferred: list[int],
    available: list[int],
    model: ModelProfile,
) -> int:
    """Find the smallest duration that fits the spoken length."""
    for d in preferred:
        if d >= spoken:
            return d

    if model.allow_max_override:
        for d in available:
            if d >= spoken:
                return d

    return available[-1]


def _split_long_segment(
    segment: dict,
    model: ModelProfile,
) -> list[dict]:
    """Split a segment exceeding the model's max duration at sentence boundaries."""
    max_duration = (
        model.preferred_max if not model.allow_max_override
        else max(model.durations)
    )
    max_words = int(max_duration * WORDS_PER_SECOND)

    text = segment["text"]
    sentences = re.split(r"(?<=[.!?])\s+", text)

    available = sorted(model.durations)
    preferred = [d for d in available if d <= model.preferred_max]

    sub_segments: list[dict] = []
    current_text = ""
    current_words = 0

    for sentence in sentences:
        sentence_words = len(sentence.split())

        if current_words + sentence_words > max_words and current_words > 0:
            sub = _make_segment(current_text.strip(), current_words)
            sub["assigned_duration"] = _best_fit_duration(
                sub["spoken_duration_seconds"], preferred, available, model,
            )
            sub["estimated_cost"] = model.cost_per_clip.get(
                sub["assigned_duration"], 0,
            )
            sub_segments.append(sub)
            current_text = ""
            current_words = 0

        current_text += " " + sentence
        current_words += sentence_words

    if current_words > 0:
        sub = _make_segment(current_text.strip(), current_words)
        sub["assigned_duration"] = _best_fit_duration(
            sub["spoken_duration_seconds"], preferred, available, model,
        )
        sub["estimated_cost"] = model.cost_per_clip.get(
            sub["assigned_duration"], 0,
        )
        sub_segments.append(sub)

    return sub_segments


def _make_segment(text: str, word_count: int) -> dict:
    """Create a segment dict from text and word count."""
    return {
        "text": text,
        "word_count": word_count,
        "spoken_duration_seconds": word_count / WORDS_PER_SECOND,
    }


def calculate_video_cost(
    segments: list[dict],
    model: ModelProfile,
) -> dict:
    """Calculate total video generation cost from duration-assigned segments."""
    by_duration: dict[int, dict] = {}
    for seg in segments:
        d = seg.get("assigned_duration", 10)
        if d not in by_duration:
            by_duration[d] = {"count": 0, "cost": 0.0}
        by_duration[d]["count"] += 1
        by_duration[d]["cost"] += seg.get("estimated_cost", 0)

    total_clips = sum(v["count"] for v in by_duration.values())
    total_cost = sum(v["cost"] for v in by_duration.values())
    total_duration = sum(v["count"] * d for d, v in by_duration.items())

    return {
        "model": model.display_name,
        "total_clips": total_clips,
        "total_duration_seconds": total_duration,
        "total_cost": total_cost,
        "by_duration": by_duration,
    }


# =============================================================================
# Multi-Grid Beat Handling
# =============================================================================

def group_segments_into_grids(segments: list[dict]) -> list[dict]:
    """Group duration-assigned segments into storyboard grids of 9.

    Each grid becomes one contact sheet. If the last grid has fewer
    than 9 segments, remaining panels are black (not generated).
    """
    grids: list[dict] = []
    grid_number = 1

    for i in range(0, len(segments), 9):
        chunk = segments[i : i + 9]
        grids.append({
            "grid_number": grid_number,
            "segments": chunk,
            "panel_count": len(chunk),
            "black_panels": 9 - len(chunk),
        })
        grid_number += 1

    return grids


# =============================================================================
# Panel Extraction (PIL)
# =============================================================================

def extract_panels(
    grid_image_path: str,
    output_dir: str,
    grid_number: int,
    expected_real_panels: int = 9,
) -> list[str]:
    """Extract panels from a 3x3 grid image, skipping black/blank panels.

    Crops with inset margin (2% x, 4% y) to trim panel borders/labels.
    Returns list of file paths for REAL panels only (reading order).
    """
    from PIL import Image

    img = Image.open(grid_image_path)
    width, height = img.size

    panel_width = width // 3
    panel_height = height // 3

    margin_x = int(panel_width * 0.02)
    margin_y = int(panel_height * 0.04)

    real_panels: list[str] = []

    for row in range(3):
        for col in range(3):
            left = col * panel_width + margin_x
            upper = row * panel_height + margin_y
            right = (col + 1) * panel_width - margin_x
            lower = (row + 1) * panel_height - margin_y

            panel = img.crop((left, upper, right, lower))

            if is_blank_panel(panel):
                logger.info(
                    f"Grid {grid_number} panel {len(real_panels) + 1} is black — skipping"
                )
                continue

            kf_number = len(real_panels) + 1
            panel_path = os.path.join(
                output_dir,
                f"grid_{grid_number}_kf{kf_number}.png",
            )
            panel.save(panel_path, quality=95)
            real_panels.append(panel_path)

            if len(real_panels) >= expected_real_panels:
                break
        if len(real_panels) >= expected_real_panels:
            break

    return real_panels


def is_blank_panel(panel_image, threshold: int = 15) -> bool:
    """Check if an extracted panel is solid black (filler).

    Returns True if mean pixel value is below threshold.
    Works with PIL Image objects.
    """
    import numpy as np

    pixels = np.array(panel_image)
    return float(pixels.mean()) < threshold


# =============================================================================
# Contact Sheet Generation + Upscaling
# =============================================================================

async def generate_contact_sheet(
    contact_sheet_prompt: str,
    real_panel_count: int = 9,
    image_client=None,
    character_reference_url: str | None = None,
) -> str:
    """Generate a 3x3 contact sheet via Nano Banana Pro.

    When a character_reference_url is provided, it's passed as image_input
    so the generated panels maintain visual consistency with the reference
    character (BYOC — bring your own character).

    Returns Google Drive URL of the generated grid image.
    """
    if image_client is None:
        from clients.image_client import ImageClient
        image_client = ImageClient()

    # Prepend technical grid wrapper
    full_prompt = (
        "CRITICAL OUTPUT FORMAT: Generate a single image containing a 3×3 grid "
        "(3 rows × 3 columns) of 9 cinematic panels. Each panel must be clearly "
        "separated. Panel labels [KF# | shot_type | duration] must appear in the "
        "top-left margin of each panel, small and non-intrusive.\n\n"
    )

    if real_panel_count < 9:
        full_prompt += (
            f"IMPORTANT: Panels {real_panel_count + 1} through 9 must be SOLID "
            f"BLACK with no content. Only panels 1 through {real_panel_count} "
            f"contain scene imagery.\n\n"
        )

    full_prompt += contact_sheet_prompt

    if character_reference_url:
        # Use reference-based generation for character consistency
        result = await image_client.generate_with_reference(
            prompt=full_prompt,
            reference_image_url=character_reference_url,
            aspect_ratio="16:9",
        )
        # generate_with_reference returns dict with 'url' key
        return result.get("url") if isinstance(result, dict) else result
    else:
        # No reference image — use standard text-to-image
        result = await image_client.generate_and_wait(
            prompt=full_prompt,
            aspect_ratio="16:9",
            model=Models.IMAGE_THUMBNAIL,
        )
        # generate_and_wait returns list of URLs
        return result[0] if result else None


async def upscale_panel(
    panel_image_url: str,
    keyframe_desc: str,
    profile: ChannelProfile,
    image_client=None,
) -> str:
    """Upscale an extracted panel via Nano Banana 2 with image_input.

    Uses the individual keyframe's description (not the generic image prompt)
    to ensure the upscaled image matches the storyboard's cinematic intent.
    """
    if image_client is None:
        from clients.image_client import ImageClient
        image_client = ImageClient()

    prompt = (
        f"{profile.visual_style_directive}\n\n"
        f"{keyframe_desc}\n\n"
        f"Technical: {profile.lens_profile.grain}. "
        f"{profile.color_grade.primary_palette}. "
        f"{profile.color_grade.contrast}."
    )

    result = await image_client.generate_scene_image(
        prompt=prompt,
        image_input=panel_image_url,
        aspect_ratio="16:9",
    )

    return result


# =============================================================================
# Two-Phase Orchestration
# =============================================================================

async def run_storyboard_prompts(
    idea_record: dict,
    airtable_client=None,
    anthropic_client=None,
    slack_client=None,
) -> dict:
    """Phase 1A: Generate storyboard prompts via Claude.

    Generates Claude directives and saves to Storyboard Prompts field.
    Does NOT generate images — that's Phase 1B (run_storyboard_images).

    Returns dict with beat_count, prompts_generated, and cost.
    """
    if airtable_client is None:
        from clients.airtable_client import AirtableClient
        airtable_client = AirtableClient()
    if anthropic_client is None:
        from clients.anthropic_client import AnthropicClient
        anthropic_client = AnthropicClient()

    def notify(msg: str):
        """Send Slack notification if client available."""
        if slack_client:
            try:
                slack_client.send_message(msg)
            except Exception:
                pass

    fields = idea_record.get("fields", idea_record)
    video_title = fields.get("Video Title", "")
    profile = load_profile(fields)
    idea_id = idea_record.get("id", "")
    video_length_min = fields.get(IdeaFields.VIDEO_LENGTH_MIN, 10) or 10

    # Load Story Bible for visual consistency across beats
    story_bible = _load_story_bible(fields)

    script_records = airtable_client.get_scripts_by_title(video_title)
    if not script_records:
        return {"error": f"No script found for '{video_title}'"}

    # Generate Story Bible if missing — CRITICAL for visual consistency
    if story_bible is None:
        logger.info(f"Story Bible missing for '{video_title}' — generating now...")
        story_bible = await _generate_story_bible_for_storyboard(
            anthropic_client=anthropic_client,
            airtable_client=airtable_client,
            idea_id=idea_id,
            video_title=video_title,
            script_records=script_records,
            video_length_min=int(video_length_min),
            slack_client=slack_client,
        )
        if story_bible:
            logger.info(f"Story Bible generated successfully for '{video_title}'")

    # Build scene_to_record_id map for per-scene saving
    scene_to_record_id: dict[int, str] = {}
    for rec in script_records:
        fields = rec.get("fields", rec)
        scene_num = fields.get(ScriptFields.SCENE, 0)
        rec_id = rec.get("id", "")
        if scene_num and rec_id:
            scene_to_record_id[scene_num] = rec_id

    # Fallback for legacy behavior
    first_script_id = script_records[0].get("id", "")

    # Get images FIRST to calculate beats based on image count
    image_records = airtable_client.get_all_images_for_video(video_title)
    if not image_records:
        return {"error": f"No images found for '{video_title}' — run image prompts first"}

    # Calculate beats based on image count (9 images per beat/grid)
    beats = segment_script_into_beats(script_records, image_records=image_records)
    logger.info(f"Calculated {len(beats)} beats for {len(image_records)} images")
    notify(f"📝 Storyboard prompts: *{video_title}*\n• {len(image_records)} images → {len(beats)} beat(s)")

    # Track per-scene prompts for resume support
    scene_prompts: dict[int, str] = {}
    scene_beat_counts: dict[int, int] = {}
    for rec in script_records:
        fields = rec.get("fields", rec)
        scene_num = fields.get(ScriptFields.SCENE, 0)
        existing = fields.get("Storyboard Prompts", "") or ""
        scene_prompts[scene_num] = existing
        scene_beat_counts[scene_num] = existing.count("--- BEAT ")

    total_cost = 0.0
    prompts_generated = 0
    failed_beats: list[tuple[int, int]] = []  # (scene, beat)

    # Count how many beats we'll skip (already exist)
    skipped_count = 0
    for beat in beats:
        target_scene = beat["scenes"][0] if beat["scenes"] else 1
        scene_beat_idx = beat.get("scene_beat_index", 1)
        existing_count = scene_beat_counts.get(target_scene, 0)
        if scene_beat_idx <= existing_count:
            skipped_count += 1

    if skipped_count > 0:
        notify(f"⏭️ Skipping {skipped_count} already-generated beats, resuming from beat {skipped_count + 1}")
        logger.info(f"Resuming: skipping {skipped_count} beats that already exist")

    for beat in beats:
        beat_num = beat["beat_number"]
        # Target scene is the first scene this beat covers
        target_scene = beat["scenes"][0] if beat["scenes"] else 1
        target_record_id = scene_to_record_id.get(target_scene, first_script_id)

        # Use per-scene beat info from segment_script_into_beats
        scene_beat_idx = beat.get("scene_beat_index", 1)
        total_scene_beats = beat.get("scene_beat_total", 1)

        # Skip already-completed beats for this scene
        existing_count = scene_beat_counts.get(target_scene, 0)
        if scene_beat_idx <= existing_count:
            logger.info(f"Scene {target_scene}, Beat {scene_beat_idx}/{total_scene_beats} already exists, skipping")
            continue

        beat_images = _get_images_for_beat(image_records, beat)
        image_prompts = [
            img.get(ImageFields.IMAGE_PROMPT, "")
            for img in beat_images
        ]

        # Generate directive via Claude with retry on failure
        directive = None
        for attempt in range(2):  # Max 2 attempts
            try:
                directive = await generate_storyboard_directive(
                    beat_number=beat_num,
                    beat_text=beat["text"],
                    beat_scenes=beat["scenes"],
                    video_title=video_title,
                    image_prompts=image_prompts,
                    profile=profile,
                    anthropic_client=anthropic_client,
                    story_bible=story_bible,
                    beat_duration_seconds=beat.get("estimated_duration_seconds", 120.0),
                )
                total_cost += 0.03
                break  # Success
            except ValueError as e:
                logger.warning(f"Scene {target_scene}, Beat {scene_beat_idx} attempt {attempt + 1} failed: {e}")
                if attempt == 0:
                    notify(f"⚠️ Scene {target_scene}, Beat {scene_beat_idx} retry...")
                    await asyncio.sleep(2)  # Brief pause before retry
                else:
                    notify(f"❌ Scene {target_scene}, Beat {scene_beat_idx} FAILED: {e}")
                    failed_beats.append((target_scene, scene_beat_idx))
                    continue

        if directive is None:
            continue  # Skip to next beat

        # Save prompt to THIS scene's Scripts record
        contact_sheet_prompt = directive["contact_sheet_prompt"]
        prompt_block = f"\n\n--- BEAT {scene_beat_idx} ---\n{contact_sheet_prompt}"
        scene_prompts[target_scene] = scene_prompts.get(target_scene, "") + prompt_block

        if target_record_id:
            try:
                airtable_client.update_script_record(target_record_id, {
                    "Storyboard Prompts": scene_prompts[target_scene],
                    "Storyboard Status": f"prompts_{scene_beat_idx}_of_{total_scene_beats}",
                })
                logger.info(f"Scene {target_scene}, Beat {scene_beat_idx}/{total_scene_beats} prompt saved")
                notify(f"✅ Scene {target_scene}, Beat {scene_beat_idx}/{total_scene_beats} saved")
                prompts_generated += 1
            except Exception as e:
                logger.warning(f"Failed to checkpoint prompt: {e}")
                notify(f"⚠️ Scene {target_scene}, Beat {scene_beat_idx} failed: {e}")

    # Final status update on ALL scene records
    for scene_num, record_id in scene_to_record_id.items():
        if record_id:
            try:
                scene_beats = [b for b in beats if b["scenes"] and b["scenes"][0] == scene_num]
                airtable_client.update_script_record(record_id, {
                    "Storyboard Status": "prompts_ready",
                    "Storyboard Beat Count": len(scene_beats),
                })
            except Exception as e:
                logger.warning(f"Failed to write final status for scene {scene_num}: {e}")

    if failed_beats:
        notify(f"⚠️ Storyboard prompts partial: {prompts_generated}/{len(beats)} beats, {len(failed_beats)} failed")
    else:
        notify(f"✅ Storyboard prompts complete: {prompts_generated} beats across {len(scene_to_record_id)} scenes")

    result = {
        "video_title": video_title,
        "beat_count": len(beats),
        "prompts_generated": prompts_generated,
        "total_cost": total_cost,
    }
    if failed_beats:
        result["failed_beats"] = failed_beats
        result["error"] = f"Failed to generate prompts for {len(failed_beats)} beat(s): {failed_beats}"

    return result


async def run_storyboard_images(
    idea_record: dict,
    airtable_client=None,
    image_client=None,
    slack_client=None,
) -> dict:
    """Phase 1B: Generate storyboard images from prompts.

    Reads prompts from Storyboard Prompts field, generates contact sheets,
    saves to Storyboard 1, Storyboard 2, Storyboard 3 fields.

    Returns dict with grids_generated and cost.
    """
    if airtable_client is None:
        from clients.airtable_client import AirtableClient
        airtable_client = AirtableClient()
    if image_client is None:
        from clients.image_client import ImageClient
        image_client = ImageClient()

    def notify(msg: str):
        """Send Slack notification if client available."""
        if slack_client:
            try:
                slack_client.send_message(msg)
            except Exception:
                pass

    fields = idea_record.get("fields", idea_record)
    video_title = fields.get("Video Title", "")
    idea_id = idea_record.get("id", "")

    # Load character reference image for BYOC visual lock
    character_ref_url = _load_character_reference(fields)

    # Get script records for reading prompts and writing images
    script_records = airtable_client.get_scripts_by_title(video_title)
    if not script_records:
        return {"error": f"No script found for '{video_title}'"}

    # Build scene_to_record_id map for per-scene saving
    scene_to_record_id: dict[int, str] = {}
    scene_to_fields: dict[int, dict] = {}
    for rec in script_records:
        fields = rec.get("fields", rec)
        scene_num = fields.get(ScriptFields.SCENE, 0)
        rec_id = rec.get("id", "")
        if scene_num and rec_id:
            scene_to_record_id[scene_num] = rec_id
            scene_to_fields[scene_num] = fields

    first_script_id = script_records[0].get("id", "")

    # Read prompts from ALL scenes' records and collect per-scene
    import re
    beat_pattern = r"--- BEAT (\d+) ---\n(.*?)(?=--- BEAT \d+|$)"
    scene_prompts: dict[int, list[tuple[int, str]]] = {}  # scene -> [(beat_num, prompt)]

    for scene_num, fields in scene_to_fields.items():
        prompts_text = fields.get("Storyboard Prompts", "") or ""
        matches = re.findall(beat_pattern, prompts_text, re.DOTALL)
        if matches:
            scene_prompts[scene_num] = [(int(b), p.strip()) for b, p in matches]

    if not scene_prompts:
        return {"error": "No storyboard prompts found — run prompt generation first"}

    # Get images and calculate beats based on image count
    image_records = airtable_client.get_all_images_for_video(video_title)
    beats = segment_script_into_beats(script_records, image_records=image_records)

    # Check existing grids per scene (resume support)
    scene_existing_grids: dict[int, list[str]] = {}
    for scene_num, fields in scene_to_fields.items():
        existing = []
        for field_name in ["Storyboard 1", "Storyboard 2", "Storyboard 3"]:
            field_val = fields.get(field_name, [])
            if field_val and isinstance(field_val, list) and len(field_val) > 0:
                existing.append(field_val[0].get("url", ""))
        scene_existing_grids[scene_num] = existing

    total_cost = 0.0
    failed_beats: list[tuple[int, int]] = []  # (scene, beat)
    total_grids = 0
    scene_grid_urls: dict[int, list[str]] = {s: list(g) for s, g in scene_existing_grids.items()}

    # Count total prompts across all scenes
    total_prompts = sum(len(prompts) for prompts in scene_prompts.values())

    # Process each scene's prompts
    for scene_num in sorted(scene_prompts.keys()):
        prompts = scene_prompts[scene_num]
        target_record_id = scene_to_record_id.get(scene_num)
        if not target_record_id:
            continue

        completed_beats = len([g for g in scene_existing_grids.get(scene_num, []) if g])
        scene_grid_urls.setdefault(scene_num, [])

        for beat_num, prompt in prompts:
            # Skip already-completed beats
            if beat_num <= completed_beats:
                logger.info(f"Scene {scene_num}, Beat {beat_num} grid already exists, skipping")
                continue

            # Get panel count for this beat from beats list
            real_panels = 9
            matching_beat = next(
                (b for b in beats if b["scenes"] and b["scenes"][0] == scene_num),
                None
            )
            if matching_beat:
                beat_images = _get_images_for_beat(image_records, matching_beat)
                real_panels = min(len(beat_images), 9)

            try:
                grid_url = await generate_contact_sheet(
                    contact_sheet_prompt=prompt,
                    real_panel_count=real_panels,
                    image_client=image_client,
                    character_reference_url=character_ref_url,
                )
                total_cost += 0.075

                if grid_url:
                    scene_grid_urls[scene_num].append(grid_url)
                    total_grids += 1

                    # Save to Storyboard 1/2/3 fields in THIS scene's Scripts record
                    try:
                        update_fields = {}
                        for i, url in enumerate(scene_grid_urls[scene_num]):
                            if i < 3 and url:
                                field_name = f"Storyboard {i + 1}"
                                update_fields[field_name] = [{"url": url}]
                        update_fields["Storyboard Status"] = f"images_{len(scene_grid_urls[scene_num])}_of_{len(prompts)}"
                        airtable_client.update_script_record(target_record_id, update_fields)
                        logger.info(f"Scene {scene_num}, Beat {beat_num}/{len(prompts)} grid saved")
                        notify(f"✅ Scene {scene_num}, Beat {beat_num}/{len(prompts)} grid saved")
                    except Exception as e:
                        logger.warning(f"Failed to checkpoint grid: {e}")
                        notify(f"⚠️ Scene {scene_num}, Beat {beat_num} save failed: {e}")
                else:
                    logger.error(f"Scene {scene_num}, Beat {beat_num} grid generation returned None")
                    failed_beats.append((scene_num, beat_num))

            except Exception as e:
                logger.error(f"Scene {scene_num}, Beat {beat_num} grid generation failed: {e}")
                failed_beats.append((scene_num, beat_num))
                continue

            logger.info(f"Scene {scene_num}, Beat {beat_num} grid generated (${total_cost:.2f} so far)")

    # Final updates - per scene
    for scene_num, record_id in scene_to_record_id.items():
        if record_id:
            grids = scene_grid_urls.get(scene_num, [])
            prompts = scene_prompts.get(scene_num, [])
            scene_failed = [b for s, b in failed_beats if s == scene_num]
            final_status = "grids_generated" if not scene_failed else f"partial_{len(grids)}_of_{len(prompts)}"
            try:
                update_fields = {"Storyboard Status": final_status}
                for i, url in enumerate(grids):
                    if i < 3 and url:
                        update_fields[f"Storyboard {i + 1}"] = [{"url": url}]
                airtable_client.update_script_record(record_id, update_fields)
            except Exception as e:
                logger.warning(f"Failed to write final status for scene {scene_num}: {e}")

    notify(f"✅ Storyboard images complete: {total_grids} grids across {len(scene_prompts)} scenes")

    all_grid_urls = []
    for scene_num in sorted(scene_grid_urls.keys()):
        all_grid_urls.extend(scene_grid_urls[scene_num])

    result = {
        "video_title": video_title,
        "beat_count": total_prompts,
        "grid_urls": all_grid_urls,
        "grids_generated": total_grids,
        "total_cost": total_cost,
    }

    if failed_beats:
        result["failed_beats"] = failed_beats
        result["warning"] = f"Failed to generate grids for beats: {failed_beats}"

    return result


# Legacy function for backward compatibility
async def run_storyboard_grids(
    idea_record: dict,
    airtable_client=None,
    anthropic_client=None,
    image_client=None,
    single_beat: Optional[int] = None,
) -> dict:
    """Legacy: Runs both prompt generation and image generation.

    Use run_storyboard_prompts + run_storyboard_images for split workflow.
    """
    # Run prompts first
    prompt_result = await run_storyboard_prompts(
        idea_record=idea_record,
        airtable_client=airtable_client,
        anthropic_client=anthropic_client,
    )
    if prompt_result.get("error"):
        return prompt_result

    # Refresh idea record to get updated prompts
    if airtable_client is None:
        from clients.airtable_client import AirtableClient
        airtable_client = AirtableClient()

    idea_id = idea_record.get("id", "")
    if idea_id:
        updated_idea = airtable_client.get_idea(idea_id)
        if updated_idea:
            idea_record = {
                "id": idea_id,
                "fields": updated_idea.get("fields", updated_idea),
            }

    # Run images
    image_result = await run_storyboard_images(
        idea_record=idea_record,
        airtable_client=airtable_client,
        image_client=image_client,
    )

    # Combine results
    return {
        "video_title": prompt_result.get("video_title"),
        "beat_count": prompt_result.get("beat_count"),
        "grid_urls": image_result.get("grid_urls", []),
        "grids_generated": image_result.get("grids_generated", 0),
        "directives": [],
        "total_cost": prompt_result.get("total_cost", 0) + image_result.get("total_cost", 0),
        "failed_beats": image_result.get("failed_beats"),
    }


async def run_storyboard_extract(
    idea_record: dict,
    airtable_client=None,
    image_client=None,
    google_client=None,
) -> dict:
    """Phase 2: Extract panels from grids, upscale, and write to Images table.

    Triggered by !storyboard-approve after reviewing grids.
    Resume-safe: checks existing panel status before processing.
    """
    if airtable_client is None:
        from clients.airtable_client import AirtableClient
        airtable_client = AirtableClient()
    if image_client is None:
        from clients.image_client import ImageClient
        image_client = ImageClient()
    if google_client is None:
        from clients.google_client import GoogleClient
        google_client = GoogleClient()

    fields = idea_record.get("fields", idea_record)
    video_title = fields.get("Video Title", "")
    profile = load_profile(fields)

    image_records = airtable_client.get_all_images_for_video(video_title)

    # Get grid URLs from Storyboard Preview field
    storyboard_preview = fields.get("Storyboard Preview", [])
    if not storyboard_preview:
        return {"error": "No storyboard grids found — run !storyboard-go first"}

    grid_urls = [
        att.get("url", "") for att in storyboard_preview if att.get("url")
    ]

    # Group image records into grids of 9
    grids = group_segments_into_grids(image_records)

    total_panels = 0
    total_cost = 0.0

    for grid_idx, grid_url in enumerate(grid_urls):
        if grid_idx >= len(grids):
            break

        grid = grids[grid_idx]
        grid_images = grid["segments"]
        real_panels = grid["panel_count"]

        # Download grid image
        temp_dir = f"/tmp/storyboard_{video_title.replace(' ', '_')}_grid_{grid_idx + 1}"
        os.makedirs(temp_dir, exist_ok=True)

        try:
            grid_local_path = await google_client.download_file_to_local(
                grid_url, os.path.join(temp_dir, f"grid_{grid_idx + 1}.png"),
            )
        except Exception as e:
            logger.error(f"Failed to download grid {grid_idx + 1}: {e}")
            continue

        # Extract panels
        panel_paths = extract_panels(
            grid_local_path, temp_dir, grid_idx + 1, real_panels,
        )

        # Upscale each panel and write back
        for panel_idx, panel_path in enumerate(panel_paths):
            if panel_idx >= len(grid_images):
                break

            img_record = grid_images[panel_idx]
            record_id = img_record.get("id", "")

            # Resume check
            if (
                img_record.get("Generation Method") == "storyboard"
                and img_record.get(ImageFields.STATUS) == "Done"
            ):
                continue

            # Upload extracted panel to Drive
            panel_drive_url = await google_client.upload_file(
                panel_path, video_title,
            )

            # Upscale
            try:
                upscaled_url = await upscale_panel(
                    panel_image_url=panel_drive_url,
                    keyframe_desc="",  # Will use grid context
                    profile=profile,
                    image_client=image_client,
                )
                total_cost += 0.045
            except Exception as e:
                logger.warning(f"Upscale failed for panel {panel_idx + 1}: {e}")
                upscaled_url = panel_drive_url  # Fall back to non-upscaled

            # Write to Airtable
            if record_id:
                try:
                    airtable_client.update_image_record(record_id, {
                        ImageFields.IMAGE: [{"url": upscaled_url}],
                        ImageFields.STATUS: "Done",
                        "Storyboard Grid URL": grid_url,
                        "Panel Position": f"{panel_idx // 3}_{panel_idx % 3}",
                        "Generation Method": "storyboard",
                    })
                except Exception as e:
                    logger.warning(f"Airtable write failed for panel {panel_idx + 1}: {e}")

            total_panels += 1

    # Update storyboard status
    idea_id = idea_record.get("id", "")
    if idea_id:
        try:
            airtable_client.update_idea_fields(idea_id, {
                "Storyboard Status": "extracted",
            })
        except Exception as e:
            logger.warning(f"Failed to update storyboard status: {e}")

    return {
        "video_title": video_title,
        "total_panels": total_panels,
        "total_cost": total_cost,
    }


# =============================================================================
# Internal Helpers
# =============================================================================


def _load_story_bible(fields: dict) -> dict | None:
    """Load Story Bible from the idea record's fields.

    The Story Bible is stored as a JSON string in the 'Story Bible' field.
    Returns parsed dict, or None if not present or unparseable.
    """
    import json

    raw = fields.get(IdeaFields.STORY_BIBLE) or fields.get("Story Bible")
    if not raw:
        logger.info("No Story Bible found — storyboard will generate without visual bible")
        return None

    if isinstance(raw, dict):
        return raw

    try:
        bible = json.loads(raw)
        char_count = len(bible.get("characters", []))
        loc_count = len(bible.get("locations", []))
        logger.info(
            f"Loaded Story Bible: {char_count} characters, {loc_count} locations"
        )
        return bible
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning(f"Failed to parse Story Bible JSON: {e}")
        return None


async def _generate_story_bible_for_storyboard(
    anthropic_client,
    airtable_client,
    idea_id: str,
    video_title: str,
    script_records: list,
    video_length_min: int = 10,
    slack_client=None,
) -> dict | None:
    """Generate Story Bible if not present, and save to Airtable.

    This ensures storyboard prompts have visual consistency even when
    run before image prompts (or when image prompts ran without Story Bible).

    Args:
        anthropic_client: AnthropicClient for Claude API calls
        airtable_client: AirtableClient for saving Story Bible
        idea_id: Airtable record ID for the idea
        video_title: Video title for logging
        script_records: List of script records with scene text
        video_length_min: Video length in minutes (default 10)
        slack_client: Optional SlackClient for notifications

    Returns:
        Generated Story Bible dict, or None on failure
    """
    import json
    from bots.story_bible import generate_story_bible, has_scene_blocks

    def notify(msg: str):
        if slack_client:
            try:
                slack_client.send_message(msg)
            except Exception:
                pass

    logger.info(f"Generating Story Bible for '{video_title}'...")
    notify(f"📖 Generating Story Bible for *{video_title}* (required for visual consistency)...")

    try:
        # Calculate total images based on video length
        try:
            from pipeline_config import VideoConfig
            video_config = VideoConfig(int(video_length_min), 10)
            total_images = video_config.total_clips
        except (ValueError, TypeError, ImportError):
            total_images = 60  # Default fallback

        # Combine all scene text
        full_script_text = "\n\n".join(
            f"[SCENE {rec.get('fields', rec).get(ScriptFields.SCENE, 0)}]\n"
            f"{rec.get('fields', rec).get(ScriptFields.SCENE_TEXT, '') or rec.get('fields', rec).get(IdeaFields.SCRIPT, '')}"
            for rec in script_records
        )

        if not full_script_text.strip():
            logger.warning("No script text found for Story Bible generation")
            return None

        # Generate Story Bible via Claude
        story_bible = await generate_story_bible(
            anthropic_client=anthropic_client,
            full_script_text=full_script_text,
            video_title=video_title,
            use_scene_blocks=True,
            total_images=total_images,
            video_duration_minutes=int(video_length_min),
        )

        if story_bible:
            # Save to Airtable
            airtable_client.update_idea_fields(
                idea_id,
                {IdeaFields.STORY_BIBLE: json.dumps(story_bible, ensure_ascii=False)}
            )
            logger.info(f"Story Bible saved to Airtable for '{video_title}'")

            # Log and notify
            char_count = len(story_bible.get("characters", []))
            loc_count = len(story_bible.get("locations", []))

            if has_scene_blocks(story_bible):
                block_count = len(story_bible.get("scene_blocks", []))
                total_block_images = sum(
                    len(b.get("images", []))
                    for b in story_bible.get("scene_blocks", [])
                )
                notify(
                    f"📖 Story Bible generated for *{video_title}*:\n"
                    f"• {char_count} characters, {loc_count} locations\n"
                    f"• {block_count} scene blocks ({total_block_images} images)"
                )
            else:
                arc_count = len(story_bible.get("visual_arc", []))
                notify(
                    f"📖 Story Bible generated for *{video_title}*:\n"
                    f"• {char_count} characters, {loc_count} locations\n"
                    f"• {arc_count} visual arcs"
                )

            return story_bible
        else:
            logger.warning("Story Bible generation returned empty result")
            return None

    except Exception as e:
        logger.error(f"Story Bible generation failed: {e}")
        notify(f"⚠️ Story Bible generation failed for *{video_title}*: {e}")
        return None


def _load_character_reference(fields: dict) -> str | None:
    """Load character reference image URL from the idea record.

    The Character Reference field is an Airtable attachment field.
    Returns the first image URL, or None if not set.
    """
    attachments = fields.get(IdeaFields.CHARACTER_REFERENCE) or fields.get(
        "Character Reference"
    )
    if not attachments:
        return None

    if isinstance(attachments, list) and attachments:
        url = attachments[0].get("url", "")
        if url:
            logger.info(f"Loaded character reference image: {url[:80]}...")
            return url

    return None


def _get_images_for_beat(
    all_image_records: list[dict],
    beat: dict,
) -> list[dict]:
    """Filter image records to those belonging to this beat.

    If beat has image_record_ids (from image-count-based segmentation),
    uses those for exact matching. Otherwise falls back to scene-based filtering.
    """
    # Use exact image IDs if available (new image-count-based beats)
    if "image_record_ids" in beat and beat["image_record_ids"]:
        record_ids = set(beat["image_record_ids"])
        return [img for img in all_image_records if img.get("id", "") in record_ids]

    # Fallback: filter by scene (old narration-based beats)
    beat_scenes = set(beat["scenes"])
    return [
        img for img in all_image_records
        if img.get(ImageFields.SCENE, img.get("fields", {}).get(ImageFields.SCENE, 0))
        in beat_scenes
    ]
